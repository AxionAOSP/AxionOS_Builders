from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime, timezone
import asyncio
import json
from utils import (
    OWNER_ID, ROLE_ADMIN, ROLE_USER, ROLE_OWNER, 
    restricted_command, get_redis, get_user_data, update_user_data,
    fetch_db_from_github, save_db_to_github, RK_CHATS, RK_USERS
)

# NO restricted_command here because we need to run it in UNAPPROVED chats to approve them!
async def approve_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    sender_id = user.id

    # 1. Check Permissions (Admin or Owner)
    # We check ADMIN_USER_IDS from ENV first as it's the safest way for the owner
    from utils import ADMIN_USER_IDS
    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    
    is_admin = (sender_id == OWNER_ID) or (sender_id in ADMIN_USER_IDS) or sender_role in [ROLE_ADMIN, ROLE_OWNER]
    
    if not is_admin:
        # Silently ignore or reply if it's a private chat
        if chat.type == "private":
            await update.message.reply_text("⛔ **Access Denied.**")
        return

    chat_id = str(chat.id)
    chat_title = chat.title or "Private Chat"

    # 2. Add to Redis (Instant)
    r = await get_redis()
    is_new = await r.sadd(RK_CHATS, chat_id)

    if is_new:
        # DO NOT trigger GitHub backup here as per user request
        await update.message.reply_text(f"✅ **Chat Approved (Local Only)**\nTitle: `{chat_title}`\nID: `{chat_id}`\n\nUsers in this group can now use bot commands. Use `/save` to persist this across bot restarts.")
    else:
        await update.message.reply_text(f"⚠️ Chat `{chat_id}` is already approved.")

@restricted_command
async def save_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force a Redis -> GitHub sync"""
    user = update.effective_user
    sender_id = user.id
    
    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or sender_role in [ROLE_ADMIN, ROLE_OWNER]

    if not is_admin:
        await update.message.reply_text("⛔ Admin only.")
        return
    
    status_msg = await update.message.reply_text("💾 Saving Redis state to GitHub...")
    success = await save_db_to_github(f"database: Manual save by {user.username or user.id}")
    
    if success:
        await status_msg.edit_text("✅ database.json has been updated on GitHub.")
    else:
        await status_msg.edit_text("❌ Save failed. Check logs.")

@restricted_command
async def sync_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force a GitHub -> Redis sync"""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ Owner only.")
        return
    
    status_msg = await update.message.reply_text("🔄 Syncing Redis with GitHub...")
    success = await fetch_db_from_github()
    
    if success:
        await status_msg.edit_text("✅ Redis cache has been refreshed from GitHub.")
    else:
        await status_msg.edit_text("❌ Sync failed. Check logs.")

async def resolve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper to resolve a user from reply, username, or ID"""
    target_id = None
    target_username = "Unknown"
    
    # 1. Check if it's a reply
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        return str(user.id), (user.username or user.first_name)

    # 2. Check arguments
    if not context.args:
        return None, None
    
    target_input = context.args[0]
    
    # Check if it's a username (@username)
    if target_input.startswith("@"):
        username = target_input[1:].lower()
        r = await get_redis()
        all_users = await r.hgetall(RK_USERS)
        for uid, u_raw in all_users.items():
            u_data = json.loads(u_raw)
            if u_data.get("username", "").lower() == username:
                return uid, u_data.get("username")
        
        # If not in our DB, try resolving via Telegram API (expensive but works for new users)
        try:
            chat = await context.bot.get_chat(target_input)
            return str(chat.id), (chat.username or chat.first_name)
        except:
            return None, None
            
    # Check if it's a numeric ID
    if target_input.isdigit():
        return target_input, target_input
        
    return None, None

@restricted_command
async def set_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = user.id

    # --- 1. Check Owner Permission ---
    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None

    if not (sender_id == OWNER_ID or sender_role == ROLE_OWNER):
        await update.message.reply_text("⛔ **Access Denied:** Only the Owner can use this command.")
        return

    # --- 2. Resolve User ---
    target_id, target_name = await resolve_user(update, context)
    if not target_id:
        await update.message.reply_text("⚠️ Usage: Reply to a user OR use `/setrole <Role> <@username/ID> [Limit]`", parse_mode="Markdown")
        return

    # --- 3. Parse Role and Limit ---
    args = context.args
    new_role = None
    custom_limit = None

    if update.message.reply_to_message:
        if len(args) >= 1: new_role = args[0].lower()
        if len(args) >= 2: custom_limit = args[1]
    else:
        if len(args) >= 1: new_role = args[0].lower()
        if len(args) >= 3: custom_limit = args[2]

    if not new_role or new_role not in [ROLE_ADMIN, ROLE_USER]:
        await update.message.reply_text(f"⚠️ Invalid role. Use `{ROLE_ADMIN}` or `{ROLE_USER}`.", parse_mode="Markdown")
        return

    if custom_limit:
        try:
            custom_limit = int(str(custom_limit).lower().replace("/d", "").replace("/day", ""))
        except: custom_limit = None

    # 4. Update
    def role_mod(data):
        data["role"] = new_role
        if custom_limit is not None:
            data["daily_limit"] = custom_limit
        return True

    success = await update_user_data(target_id, role_mod, commit_msg=f"database: Set {target_name} to {new_role} (Limit: {custom_limit})")

    if success:
        limit_text = f" (Limit: {custom_limit}/day)" if custom_limit is not None else ""
        await update.message.reply_text(f"✅ **Updated:** `{target_name}` is now `{new_role.upper()}`{limit_text}.")
    else:
        await update.message.reply_text("❌ Failed to update.")

@restricted_command
async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = user.id

    # --- 1. Check Permissions ---
    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or sender_role in [ROLE_ADMIN, ROLE_OWNER]
    
    if not is_admin:
        await update.message.reply_text("⛔ **Access Denied:** Admin only command.")
        return

    # --- 2. Resolve User ---
    target_id, target_username = await resolve_user(update, context)
    
    if not target_id:
        await update.message.reply_text("⚠️ Usage: Reply to a user OR use `/adduser <@username/ID> [role]`", parse_mode="Markdown")
        return

    # Determine role
    args = context.args
    target_role = ROLE_USER
    if update.message.reply_to_message and args:
        target_role = args[0].lower()
    elif len(args) > 1:
        target_role = args[1].lower()
    
    if target_role not in [ROLE_ADMIN, ROLE_USER]:
        await update.message.reply_text(f"⚠️ Invalid role. Use `{ROLE_ADMIN}` or `{ROLE_USER}`.", parse_mode="Markdown")
        return

    # --- 3. Update (Instant) ---
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def add_user_mod(data):
        data.update({
            "username": target_username.replace("@", ""),
            "role": target_role,
            "added_by": str(sender_id),
            "added_date": today_utc,
            "daily_count": 0,
            "last_build_date": ""
        })
        return True

    success = await update_user_data(target_id, add_user_mod, commit_msg=f"database: Add {target_username} as {target_role}")

    if success:
        await update.message.reply_text(f"✅ **User Added:** `{target_username}` (`{target_id}`) as `{target_role.upper()}`.")
    else:
        await update.message.reply_text("❌ Failed to update.")

@restricted_command
async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = user.id

    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or sender_role in [ROLE_ADMIN, ROLE_OWNER]

    if not is_admin:
        await update.message.reply_text("⛔ **Access Denied:** Admin only command.")
        return

    target_id, target_name = await resolve_user(update, context)
    if not target_id:
        await update.message.reply_text("⚠️ Usage: Reply to a user OR use `/removeuser <@username/ID>`", parse_mode="Markdown")
        return

    r = await get_redis()
    if not await r.hexists(RK_USERS, target_id):
        await update.message.reply_text(f"❌ User `{target_name}` not found in database.")
        return

    # Remove from Redis
    await r.hdel(RK_USERS, target_id)
    asyncio.create_task(save_db_to_github(f"database: Remove user {target_name} ({target_id})"))
    await update.message.reply_text(f"✅ **User Removed:** `{target_name}`.")

@restricted_command
async def add_quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = user.id

    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None

    if not (sender_id == OWNER_ID or sender_role == ROLE_OWNER):
        await update.message.reply_text("⛔ **Access Denied:** Owner only command.")
        return

    # --- 1. Resolve User ---
    target_id, target_name = await resolve_user(update, context)
    if not target_id:
        await update.message.reply_text("⚠️ Usage: Reply to a user OR use `/addquota <@username/ID> <Limit>`", parse_mode="Markdown")
        return

    # --- 2. Parse Limit ---
    args = context.args
    limit_val = None
    if update.message.reply_to_message:
        if len(args) >= 1: limit_val = args[0]
    else:
        if len(args) >= 2: limit_val = args[1]

    if not limit_val:
        await update.message.reply_text("⚠️ Please specify a limit.")
        return

    try:
        new_limit = int(str(limit_val).lower().replace("/d", "").replace("/day", ""))
        if new_limit < 0: raise ValueError
    except:
        await update.message.reply_text("⚠️ Limit must be a positive number.")
        return

    def quota_mod(data):
        data["daily_limit"] = new_limit
        return True

    success = await update_user_data(target_id, quota_mod, commit_msg=f"database: Set {target_name} daily limit to {new_limit}")

    if success:
        await update.message.reply_text(f"✅ **Limit Set:** `{target_name}` daily limit is now `{new_limit}`.")
    else:
        await update.message.reply_text("❌ Update failed.")

@restricted_command
async def set_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the global main output channel for build notifications"""
    user = update.effective_user
    sender_id = user.id

    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    if not (sender_id == OWNER_ID or sender_role in [ROLE_ADMIN, ROLE_OWNER]):
        await update.message.reply_text("⛔ Admin only.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/setchannel <ChannelID>`\nExample: `/setchannel -100123456789`", parse_mode="Markdown")
        return

    target_channel = context.args[0]
    r = await get_redis()
    
    # Verify it's a valid ID format
    if not (target_channel.startswith("-") and target_channel[1:].isdigit()):
        await update.message.reply_text("❌ Invalid Channel ID format.")
        return

    from utils import RK_CONFIG
    await r.hset(RK_CONFIG, "main_output_channel", target_channel)
    await update.message.reply_text(f"✅ **Main Output Channel Set**\nID: `<code>{target_channel}</code>`", parse_mode="HTML")

@restricted_command
async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes the global main output channel"""
    user = update.effective_user
    sender_id = user.id

    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    if not (sender_id == OWNER_ID or sender_role in [ROLE_ADMIN, ROLE_OWNER]):
        await update.message.reply_text("⛔ Admin only.")
        return

    r = await get_redis()
    from utils import RK_CONFIG
    await r.hdel(RK_CONFIG, "main_output_channel")
    await update.message.reply_text("✅ **Main Output Channel Removed.**\nBuild notifications will now stay in the group where they were triggered.")

