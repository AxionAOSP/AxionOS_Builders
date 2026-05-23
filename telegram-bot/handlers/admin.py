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

async def approve_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    sender_id = user.id

    from utils import ADMIN_USER_IDS
    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or (sender_id in ADMIN_USER_IDS) or sender_role in [ROLE_ADMIN, ROLE_OWNER]
    
    if not is_admin:
        if chat.type == "private": await update.message.reply_text("⛔ **Access Denied.**")
        return

    if context.args:
        chat_id = context.args[0]
        chat_title = f"Manual ID: {chat_id}"
    else:
        chat_id = str(chat.id)
        chat_title = chat.title or "Private Chat"

    r = await get_redis()
    is_new = await r.sadd(RK_CHATS, chat_id)

    if is_new:
        await update.message.reply_text(f"✅ **Chat Approved (Local Only)**\nTitle: `{chat_title}`\nID: `{chat_id}`\n\nUse `/save` to persist.")
    else:
        await update.message.reply_text(f"⚠️ Chat `{chat_id}` already approved.")

@restricted_command
async def disapprove_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes chat from approved list"""
    user = update.effective_user
    chat = update.effective_chat
    sender_id = user.id

    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or sender_role in [ROLE_ADMIN, ROLE_OWNER]
    
    if not is_admin:
        await update.message.reply_text("⛔ **Access Denied.**")
        return

    target_id = context.args[0] if context.args else str(chat.id)
    r = await get_redis()
    existed = await r.srem(RK_CHATS, target_id)

    if existed:
        await update.message.reply_text(f"🗑️ **Chat Disapproved (Local Only)**\nID: `{target_id}`\n\nUse `/save` to persist.")
    else:
        await update.message.reply_text(f"❌ Chat `{target_id}` not found in list.")

@restricted_command
async def save_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force Redis -> GitHub sync"""
    user = update.effective_user
    sender_id = user.id
    
    sender_data = await get_user_data(sender_id)
    sender_role = sender_data.get("role") if sender_data else None
    is_admin = (sender_id == OWNER_ID) or sender_role in [ROLE_ADMIN, ROLE_OWNER]

    if not is_admin:
        await update.message.reply_text("⛔ Admin only.")
        return
    
    status_msg = await update.message.reply_text("💾 Syncing Redis to GitHub...")
    success = await save_db_to_github(f"database: Manual save by {user.username or user.id}")
    
    if success:
        await status_msg.edit_text("✅ database.json updated on GitHub.")
    else:
        await status_msg.edit_text("❌ Save failed.")

@restricted_command
async def sync_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force GitHub -> Redis sync"""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ Owner only.")
        return
    
    status_msg = await update.message.reply_text("🔄 Refreshing Redis from GitHub...")
    success = await fetch_db_from_github()
    
    if success:
        await status_msg.edit_text("✅ Redis cache refreshed.")
    else:
        await status_msg.edit_text("❌ Sync failed.")

async def resolve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resolves user from reply, mention, ID, or username"""
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        return str(user.id), (user.username or user.first_name)

    if update.message.entities:
        for ent in update.message.entities:
            if ent.type == "text_mention" and ent.user:
                return str(ent.user.id), (ent.user.username or ent.user.first_name)

    if not context.args: return None, None
    
    for target_input in context.args[:2]:
        if target_input.isdigit(): return target_input, target_input
            
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
            
            try:
                chat = await context.bot.get_chat(target_input)
                return str(chat.id), (chat.username or chat.first_name)
            except: continue
                
    return None, None

@restricted_command
async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcasts message to all groups (Owner only)"""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ **Access Denied.**")
        return

    broadcast_text = None
    reply_to = None

    if update.message.reply_to_message:
        broadcast_text = update.message.reply_to_message.text_html or update.message.reply_to_message.text
        reply_to = update.message.reply_to_message
    elif context.args:
        broadcast_text = " ".join(context.args)
    else:
        await update.message.reply_text("⚠️ Usage: `/announce <msg>` or reply to a message", parse_mode="Markdown")
        return

    r = await get_redis()
    from utils import RK_CONFIG
    chats = list(await r.smembers(RK_CHATS))
    main_chan = await r.hget(RK_CONFIG, "main_output_channel")
    if main_chan and main_chan not in chats: chats.append(main_chan)
    
    if not chats:
        await update.message.reply_text("❌ No target chats found.")
        return

    status_msg = await update.message.reply_text(f"📢 Broadcasting to {len(chats)} targets...")
    success_count, fail_count = 0, 0
    header = "📢 **OFFICIAL ANNOUNCEMENT**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    full_message = f"{header}{broadcast_text}"

    for chat_id in chats:
        try:
            if reply_to and (reply_to.photo or reply_to.document or reply_to.video):
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=reply_to.message_id,
                    caption=f"{header}{reply_to.caption or ''}",
                    parse_mode=ParseMode.HTML
                )
            else:
                await context.bot.send_message(chat_id=chat_id, text=full_message, parse_mode=ParseMode.HTML)
            success_count += 1
            await asyncio.sleep(0.1)
        except: fail_count += 1

    await status_msg.edit_text(f"✅ **Broadcast Complete**\nSuccess: `{success_count}` | Failed: `{fail_count}`", parse_mode="Markdown")

@restricted_command
async def set_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets user role (Admin only)"""
    user = update.effective_user
    sender_data = await get_user_data(user.id)
    sender_role = sender_data.get("role") if sender_data else None

    # Allow Admins and Owner to set roles
    if not (user.id == OWNER_ID or sender_role in [ROLE_ADMIN, ROLE_OWNER]):
        await update.message.reply_text("⛔ **Access Denied.**")
        return

    target_id, target_name = await resolve_user(update, context)
    if not target_id:
        await update.message.reply_text("⚠️ Usage: `/setrole <Role> <@user/ID>`", parse_mode="Markdown")
        return

    args = context.args
    new_role = None

    for arg in args:
        if arg.lower() in [ROLE_ADMIN, ROLE_USER]:
            new_role = arg.lower()
            break

    if not new_role:
        await update.message.reply_text(f"⚠️ Invalid role. Use `{ROLE_ADMIN}` or `{ROLE_USER}`.", parse_mode="Markdown")
        return

    def role_mod(data):
        is_new = "added_date" not in data
        data["role"] = new_role
        data["username"] = str(target_name).replace("@", "")
        if is_new:
            data["added_by"] = str(user.id)
            data["added_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return True

    success = await update_user_data(target_id, role_mod, commit_msg=f"database: Set {target_name} to {new_role}")
    if success:
        await update.message.reply_text(f"✅ **Success:** `{target_name}` is now `{new_role.upper()}`.")
    else:
        await update.message.reply_text("❌ Operation failed.")

@restricted_command
async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a maintainer (Admin only)"""
    user = update.effective_user
    sender_data = await get_user_data(user.id)
    sender_role = sender_data.get("role") if sender_data else None
    if not (user.id == OWNER_ID or sender_role in [ROLE_ADMIN, ROLE_OWNER]):
        await update.message.reply_text("⛔ **Access Denied.**")
        return

    target_id, target_name = await resolve_user(update, context)
    if not target_id:
        await update.message.reply_text("⚠️ Usage: `/removeuser <@user/ID>`", parse_mode="Markdown")
        return

    r = await get_redis()
    if not await r.hexists(RK_USERS, target_id):
        await update.message.reply_text(f"❌ User `{target_name}` not found.")
        return

    await r.hdel(RK_USERS, target_id)
    asyncio.create_task(save_db_to_github(f"database: Remove user {target_name}"))
    await update.message.reply_text(f"✅ **User Removed:** `{target_name}`.")

@restricted_command
async def list_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows approved groups and main channel"""
    user = update.effective_user
    sender_data = await get_user_data(user.id)
    sender_role = sender_data.get("role") if sender_data else None
    if not (user.id == OWNER_ID or sender_role in [ROLE_ADMIN, ROLE_OWNER]):
        await update.message.reply_text("⛔ **Access Denied.**")
        return

    r = await get_redis()
    from utils import RK_CONFIG
    main_chan = await r.hget(RK_CONFIG, "main_output_channel")
    groups = await r.smembers(RK_CHATS)
    
    msg = "<b>📡 NETWORK CONFIG</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"<b>📢 Main Channel:</b>\n└ <code>{main_chan or 'None'}</code>\n\n"
    msg += f"<b>👥 Groups ({len(groups)}):</b>\n"
    if groups:
        for g_id in sorted(list(groups)): msg += f"├ <code>{g_id}</code>\n"
    else: msg += "└ <i>None approved.</i>"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

@restricted_command
async def set_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets main output channel"""
    user = update.effective_user
    sender_data = await get_user_data(user.id)
    sender_role = sender_data.get("role") if sender_data else None
    if not (user.id == OWNER_ID or sender_role in [ROLE_ADMIN, ROLE_OWNER]):
        await update.message.reply_text("⛔ Admin only.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/setchannel <ChannelID>`")
        return

    target = context.args[0]
    if not (target.startswith("-") and target[1:].isdigit()):
        await update.message.reply_text("❌ Invalid ID format.")
        return

    r = await get_redis()
    from utils import RK_CONFIG
    await r.hset(RK_CONFIG, "main_output_channel", target)
    await update.message.reply_text(f"✅ **Main Channel Set:** <code>{target}</code>", parse_mode="HTML")

@restricted_command
async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes main output channel"""
    user = update.effective_user
    sender_data = await get_user_data(user.id)
    sender_role = sender_data.get("role") if sender_data else None
    if not (user.id == OWNER_ID or sender_role in [ROLE_ADMIN, ROLE_OWNER]):
        await update.message.reply_text("⛔ Admin only.")
        return

    r = await get_redis()
    from utils import RK_CONFIG
    await r.hdel(RK_CONFIG, "main_output_channel")
    await update.message.reply_text("✅ **Main Channel Removed.**")
