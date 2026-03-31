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

    # --- 2. Parse Arguments ---
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ **Invalid Usage**\n\n"
            "Format: `/setrole <Role> <Username/ID> [Limit]`\n"
            "Example: `/setrole admin @username`\n"
            "Example: `/setrole user @username 2`",
            parse_mode="Markdown"
        )
        return

    new_role = args[0].lower()
    target_input = args[1]
    
    custom_limit = None
    if len(args) >= 3:
        try:
            limit_str = args[2].lower().replace("/d", "").replace("/day", "")
            custom_limit = int(limit_str)
        except: pass

    if new_role not in [ROLE_ADMIN, ROLE_USER]:
        await update.message.reply_text(f"⚠️ Invalid role. Use `{ROLE_ADMIN}` or `{ROLE_USER}`.", parse_mode="Markdown")
        return

    # --- 3. Resolve User (from Redis Hash) ---
    target_id = None
    r = await get_redis()
    all_users = await r.hgetall(RK_USERS)
    
    for uid, u_raw in all_users.items():
        u_data = json.loads(u_raw)
        if u_data.get("username", "").lower() == target_input.lower().replace("@", ""):
            target_id = uid
            break

    if not target_id and target_input.isdigit():
        if await r.hexists(RK_USERS, target_input):
            target_id = target_input

    if not target_id:
        await update.message.reply_text(f"❌ User `{target_input}` not found. Use `/adduser` first.", parse_mode="Markdown")
        return

    # 4. Update (Instant)
    def role_mod(data):
        data["role"] = new_role
        if custom_limit is not None:
            data["daily_limit"] = custom_limit
        return True

    target_name = json.loads(all_users[target_id]).get("username", target_id)
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

    # --- 2. Parse Arguments ---
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("⚠️ Usage: `/adduser <Username> [role]`", parse_mode="Markdown")
        return

    target_input = args[0]
    target_role = args[1].lower() if len(args) > 1 else ROLE_USER
    
    if target_role not in [ROLE_ADMIN, ROLE_USER]:
        await update.message.reply_text(f"⚠️ Invalid role. Use `{ROLE_ADMIN}` or `{ROLE_USER}`.", parse_mode="Markdown")
        return

    # --- 3. Resolve ID ---
    target_id = None
    target_username = target_input

    status_msg = await update.message.reply_text(f"🔎 Resolving `{target_input}`...")

    try:
        chat = await context.bot.get_chat(target_input)
        target_id = str(chat.id)
        if chat.username: target_username = chat.username
    except Exception:
        if target_input.isdigit(): target_id = target_input
        else:
            await status_msg.edit_text(f"❌ Could not resolve `{target_input}`.")
            return

    # --- 4. Update (Instant) ---
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
        await status_msg.edit_text(f"✅ **User Added:** `{target_username}` (`{target_id}`) as `{target_role}`.")
    else:
        await status_msg.edit_text("❌ Failed to update.")

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

    args = context.args
    if len(args) < 1:
        await update.message.reply_text("⚠️ Usage: `/removeuser <TelegramID>`", parse_mode="Markdown")
        return

    target_id = args[0]
    r = await get_redis()
    
    if not await r.hexists(RK_USERS, target_id):
        await update.message.reply_text(f"❌ User ID `{target_id}` not found.")
        return

    # Remove from Redis
    await r.hdel(RK_USERS, target_id)
    asyncio.create_task(save_db_to_github(f"database: Remove user {target_id}"))
    await update.message.reply_text(f"✅ **User Removed:** `{target_id}`.")

@restricted_command
async def add_quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = user.id

    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None

    if not (sender_id == OWNER_ID or sender_role == ROLE_OWNER):
        await update.message.reply_text("⛔ **Access Denied:** Owner only command.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("⚠️ Usage: `/addquota <User> <Limit>`", parse_mode="Markdown")
        return

    target_input = args[0]
    try:
        limit_str = args[1].lower().replace("/d", "").replace("/day", "")
        new_limit = int(limit_str)
        if new_limit < 0: raise ValueError
    except:
        await update.message.reply_text("⚠️ Limit must be a positive number.")
        return

    # Resolve User
    target_id = None
    r = await get_redis()
    all_users = await r.hgetall(RK_USERS)
    
    for uid, u_raw in all_users.items():
        if json.loads(u_raw).get("username", "").lower() == target_input.lower().replace("@", ""):
            target_id = uid
            break
    
    if not target_id and target_input.isdigit():
        if target_id in all_users: target_id = target_input

    if not target_id:
        await update.message.reply_text(f"❌ User `{target_input}` not found.")
        return

    def quota_mod(data):
        data["daily_limit"] = new_limit
        return True

    success = await update_user_data(target_id, quota_mod, commit_msg=f"database: Set {target_input} daily limit to {new_limit}")

    if success:
        await update.message.reply_text(f"✅ **Limit Set:** `{target_input}` daily limit is now `{new_limit}`.")
    else:
        await update.message.reply_text("❌ Update failed.")
