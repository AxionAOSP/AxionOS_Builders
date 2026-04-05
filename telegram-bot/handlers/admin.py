from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
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
    from utils import ADMIN_USER_IDS
    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or (sender_id in ADMIN_USER_IDS) or sender_role in [ROLE_ADMIN, ROLE_OWNER]
    
    if not is_admin:
        if chat.type == "private": await update.message.reply_text("⛔ **Access Denied.**")
        return

    # Determine Chat ID
    if context.args:
        chat_id = context.args[0]
        chat_title = f"Manual ID: {chat_id}"
    else:
        chat_id = str(chat.id)
        chat_title = chat.title or "Private Chat"

    # 2. Add to Redis
    r = await get_redis()
    is_new = await r.sadd(RK_CHATS, chat_id)

    if is_new:
        await update.message.reply_text(f"✅ **Chat Approved (Local Only)**\nTitle: `{chat_title}`\nID: `{chat_id}`\n\nUse `/save` to persist this across bot restarts.")
    else:
        await update.message.reply_text(f"⚠️ Chat `{chat_id}` is already approved.")

@restricted_command
async def disapprove_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a chat from approved list (Admin only)"""
    user = update.effective_user
    chat = update.effective_chat
    sender_id = user.id

    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or sender_role in [ROLE_ADMIN, ROLE_OWNER]
    
    if not is_admin:
        await update.message.reply_text("⛔ **Access Denied.**")
        return

    # Determine Target ID
    if context.args:
        target_id = context.args[0]
    else:
        target_id = str(chat.id)

    r = await get_redis()
    existed = await r.srem(RK_CHATS, target_id)

    if existed:
        await update.message.reply_text(f"🗑️ **Chat Disapproved (Local Only)**\nID: `{target_id}`\n\nUse `/save` to persist this change.")
    else:
        await update.message.reply_text(f"❌ Chat `{target_id}` was not in the approved list.")

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
    """Helper to resolve a user from reply, username, ID, or Mention"""
    
    # 1. Check if it's a reply (Priority)
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        return str(user.id), (user.username or user.first_name)

    # 2. Check for entities (Text Mentions)
    # text_mention is used when a user is tagged by name (blue clickable text)
    if update.message.entities:
        for ent in update.message.entities:
            if ent.type == "text_mention" and ent.user:
                return str(ent.user.id), (ent.user.username or ent.user.first_name)

    # 3. Check arguments
    if not context.args:
        return None, None
    
    # We'll try the first few arguments in case the ID/username is not at index 0 (like in /setrole)
    # We stop after 2 args to avoid picking up roles or other values.
    for target_input in context.args[:2]:
        # Check if it's a numeric ID
        if target_input.isdigit():
            return target_input, target_input
            
        # Check if it's a username (@username)
        if target_input.startswith("@"):
            username = target_input[1:].lower()
            r = await get_redis()
            all_users = await r.hgetall(RK_USERS)
            for uid, u_raw in all_users.items():
                try:
                    u_data = json.loads(u_raw)
                    if u_data.get("username", "").lower() == username:
                        return uid, u_data.get("username")
                except: continue
            
            # If not in our DB, try resolving via Telegram API
            try:
                chat = await context.bot.get_chat(target_input)
                return str(chat.id), (chat.username or chat.first_name)
            except Exception as e:
                # Silently fail for this arg and try next
                continue
                
    return None, None

@restricted_command
async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcaster: Sends a message to all allowed group chats (Owner Only)"""
    user = update.effective_user
    sender_id = user.id

    if sender_id != OWNER_ID:
        await update.message.reply_text("⛔ **Access Denied:** Owner only command.")
        return

    # 1. Get the message to broadcast
    broadcast_text = None
    reply_to = None

    if update.message.reply_to_message:
        broadcast_text = update.message.reply_to_message.text_html or update.message.reply_to_message.text
        reply_to = update.message.reply_to_message
    elif context.args:
        broadcast_text = " ".join(context.args)
    else:
        await update.message.reply_text("⚠️ **Usage:**\n- `/announce <Your Message>`\n- Reply to a message with `/announce`", parse_mode="Markdown")
        return

    # 2. Get all targets (Groups + Main Channel)
    r = await get_redis()
    from utils import RK_CONFIG
    
    chats = list(await r.smembers(RK_CHATS))
    main_chan = await r.hget(RK_CONFIG, "main_output_channel")
    
    if main_chan and main_chan not in chats:
        chats.append(main_chan)
    
    if not chats:
        await update.message.reply_text("❌ No approved chats or channels found in database.")
        return

    status_msg = await update.message.reply_text(f"📢 **Broadcasting to {len(chats)} targets...**", parse_mode="Markdown")
    
    success_count = 0
    fail_count = 0

    header = "📢 **OFFICIAL ANNOUNCEMENT**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    full_message = f"{header}{broadcast_text}"

    # 3. Loop and Send
    for chat_id in chats:
        try:
            # If it's a reply with media, we should ideally copy the message, 
            # but for simplicity, we'll start with text.
            if reply_to and (reply_to.photo or reply_to.document or reply_to.video):
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=reply_to.message_id,
                    caption=f"{header}{reply_to.caption or ''}",
                    parse_mode=ParseMode.HTML
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=full_message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                )
            success_count += 1
            await asyncio.sleep(0.1) # Prevent flood
        except Exception as e:
            print(f"[ANN ERROR] Failed for {chat_id}: {e}")
            fail_count += 1

    await status_msg.edit_text(
        f"✅ **Broadcast Complete**\n"
        f"├ Success: `{success_count}`\n"
        f"└ Failed: `{fail_count}`",
        parse_mode="Markdown"
    )

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

    # Role is either 'admin' or 'user'
    for arg in args:
        if arg.lower() in [ROLE_ADMIN, ROLE_USER]:
            new_role = arg.lower()
            break

    # Limit is usually a number or something with /day
    for arg in args:
        val = str(arg).lower().replace("/d", "").replace("/day", "")
        if val.isdigit():
            # If it's the role we found, skip it
            if arg.lower() == new_role: continue
            # If it's the identifier, skip it
            if str(arg) == target_id: continue
            custom_limit = int(val)
            break

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
    target_role = ROLE_USER # Default
    for arg in args:
        if arg.lower() in [ROLE_ADMIN, ROLE_USER]:
            target_role = arg.lower()
            break
    
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
    for arg in args:
        val = str(arg).lower().replace("/d", "").replace("/day", "")
        if val.isdigit():
            # If it's the identifier, skip it
            if str(arg) == target_id: continue
            limit_val = int(val)
            break

    if limit_val is None:
        await update.message.reply_text("⚠️ Please specify a limit (e.g. `/addquota @user 5`).", parse_mode="Markdown")
        return

    new_limit = limit_val

    def quota_mod(data):
        data["daily_limit"] = new_limit
        return True

    success = await update_user_data(target_id, quota_mod, commit_msg=f"database: Set {target_name} daily limit to {new_limit}")

    if success:
        await update.message.reply_text(f"✅ **Limit Set:** `{target_name}` daily limit is now `{new_limit}`.")
    else:
        await update.message.reply_text("❌ Update failed.")

@restricted_command
async def list_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows all approved group IDs and the current main output channel (Admin only)"""
    user = update.effective_user
    sender_id = user.id

    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or sender_role in [ROLE_ADMIN, ROLE_OWNER]

    if not is_admin:
        await update.message.reply_text("⛔ **Access Denied:** Admin only command.")
        return

    r = await get_redis()
    from utils import RK_CONFIG
    
    # 1. Get Main Channel
    main_chan = await r.hget(RK_CONFIG, "main_output_channel")
    
    # 2. Get Approved Groups
    groups = await r.smembers(RK_CHATS)
    
    msg = "<b>📡 SYSTEM NETWORK CONFIG</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += "<b>📢 Main Output Channel:</b>\n"
    if main_chan:
        msg += f"└ <code>{main_chan}</code> ✅\n\n"
    else:
        msg += "└ <i>None (Redirected to triggering group)</i>\n\n"
        
    msg += f"<b>👥 Approved Groups ({len(groups)}):</b>\n"
    if groups:
        sorted_groups = sorted(list(groups))
        for g_id in sorted_groups:
            msg += f"├ <code>{g_id}</code>\n"
        msg = msg.rstrip("\n") # Remove last newline
    else:
        msg += "└ <i>No groups approved yet.</i>"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

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
