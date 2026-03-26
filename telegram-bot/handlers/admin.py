from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime, timezone
import asyncio
from utils import ADMIN_USER_IDS, load_db, commit_db_to_github, atomic_db_update, ROLE_ADMIN, ROLE_USER, ROLE_OWNER, restricted_command

@restricted_command
async def set_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = str(user.id)
    
    # --- 1. Check Owner Permission (DB Based) ---
    db = load_db()
    sender_data = db.get("users", {}).get(sender_id, {})
    sender_role = sender_data.get("role", ROLE_USER)
    
    if sender_role != ROLE_OWNER:
        await update.message.reply_text("⛔ **Access Denied:** Only the Owner can use this command.")
        return

    # --- 2. Parse Arguments ---
    # Usage: /setrole <Username/ID> <Role>
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ **Invalid Usage**\n\n"
            "Format: `/setrole <Username/ID> <Role>`\n"
            f"Roles: `{ROLE_ADMIN}`, `{ROLE_USER}`",
            parse_mode="Markdown"
        )
        return

    target_input = args[0]
    new_role = args[1].lower()
    
    # Validate Role (Owner role cannot be set via command for safety, only admin/user)
    if new_role not in [ROLE_ADMIN, ROLE_USER]:
        await update.message.reply_text(f"⚠️ Invalid role. Use `{ROLE_ADMIN}` or `{ROLE_USER}`.", parse_mode="Markdown")
        return

    # --- 3. Resolve User (Username -> ID) ---
    target_id = None
    
    # Try finding by username in DB first
    for uid, udata in db.get("users", {}).items():
        u_name = udata.get("username", "")
        if u_name.lower() == target_input.lower().replace("@", ""):
            target_id = uid
            break
            
    # If not found by name, check if input is ID
    if not target_id and target_input.isdigit():
        if target_input in db.get("users", {}):
            target_id = target_input

    if not target_id:
        await update.message.reply_text(f"❌ User `{target_input}` not found in database.", parse_mode="Markdown")
        return

    # Update role
    old_role = db["users"][target_id].get("role", "unknown")
    db["users"][target_id]["role"] = new_role
    target_username = db["users"][target_id].get("username", "Unknown")

    status_msg = await update.message.reply_text("⏳ Syncing role change to GitHub...")
    
    def set_role_modifier(db):
        if "users" not in db or target_id not in db["users"]:
            return False
        db["users"][target_id]["role"] = new_role
        return True

    commit_msg = f"database: Change {target_username} role from {old_role} to {new_role}"
    
    success = await asyncio.to_thread(atomic_db_update, set_role_modifier, commit_msg)
    
    if success:
        msg = (
            f"✅ **Role Updated**\n\n"
            f"👤 **User:** `{target_username}` (`{target_id}`)\n"
            f"🔰 **Old Role:** `{old_role}`\n"
            f"🆕 **New Role:** `{new_role}`\n"
            f"☁️ **Synced:** GitHub"
        )
        await status_msg.edit_text(msg, parse_mode="Markdown")
    else:
        await status_msg.edit_text("❌ Failed to sync to GitHub. Check logs.")

@restricted_command
async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = user.id
    
    # --- 1. Check Permissions ---
    # Allow if sender is in ENV ADMIN list OR has 'admin' role in DB
    is_env_admin = sender_id in ADMIN_USER_IDS
    
    db = load_db()
    user_data = db.get("users", {}).get(str(sender_id), {})
    is_db_admin = user_data.get("role") == ROLE_ADMIN
    
    if not (is_env_admin or is_db_admin):
        await update.message.reply_text("⛔ **Access Denied:** Admin only command.")
        return

    # --- 2. Parse Arguments ---
    # Usage: /adduser <Username> [role]
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "⚠️ **Invalid Usage**\n\n"
            "Format: `/adduser <Username> [role]`\n"
            "Example: `/adduser @username admin`",
            parse_mode="Markdown"
        )
        return

    target_input = args[0]
    target_role = args[1].lower() if len(args) > 1 else ROLE_USER
    
    # Validate Role
    if target_role not in [ROLE_ADMIN, ROLE_USER]:
        await update.message.reply_text(f"⚠️ Invalid role. Use `{ROLE_ADMIN}` or `{ROLE_USER}`.", parse_mode="Markdown")
        return

    # --- 3. Resolve ID ---
    target_id = None
    target_username = target_input

    status_msg = await update.message.reply_text(f"🔎 Resolving `{target_input}`...")

    # Try resolving via API
    try:
        # get_chat works with @username if bot has interacted or sometimes globally
        chat = await context.bot.get_chat(target_input)
        target_id = str(chat.id)
        # Use the official username if available, else input
        if chat.username:
            target_username = chat.username
    except Exception:
        # If failed, maybe they passed an ID?
        if target_input.isdigit():
            target_id = target_input
            target_username = f"User_{target_id}" # Fallback name
        else:
            await status_msg.edit_text(
                "❌ **Could not resolve username.**\n"
                "The bot may not have seen this user yet.\n"
                "Please ask the user to `/start` the bot, or provide their Numeric ID."
            )
            return

    # --- 4. Prepare Data ---
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    new_user_data = {
        "username": target_username,
        "role": target_role,
        "last_build_date": today_utc,
        "daily_count": 0
    }
    
    # --- 5. Update & Save (ATOMIC) ---
    status_msg = await update.message.reply_text("⏳ Syncing to GitHub...")
    
    # Define atomic modifier
    def add_user_modifier(db):
        if "users" not in db: db["users"] = {}
        # Double-check inside lock
        if str(target_id) in db["users"]:
            return False # Fail if appeared during race
        db["users"][str(target_id)] = new_user_data
        return True

    commit_msg = f"database: Add {target_username} to database as {target_role}"
    
    # Run blocking IO in thread
    success = await asyncio.to_thread(atomic_db_update, add_user_modifier, commit_msg)

    if success:
        msg = (
            f"✅ **User Added/Updated**\n\n"
            f"🆔 **ID:** `{target_id}`\n"
            f"👤 **Name:** `{target_username}`\n"
            f"🔰 **Role:** `{target_role}`\n"
            f"📅 **Date:** `{today_utc}` (UTC)\n"
            f"☁️ **Synced:** GitHub"
        )
        await status_msg.edit_text(msg, parse_mode="Markdown")
    else:
        await status_msg.edit_text("❌ Failed to sync (or User already exists).")

@restricted_command
async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = user.id
    
    # --- 1. Check Permissions ---
    is_env_admin = sender_id in ADMIN_USER_IDS
    db = load_db()
    user_data = db.get("users", {}).get(str(sender_id), {})
    is_db_admin = user_data.get("role") == ROLE_ADMIN
    
    if not (is_env_admin or is_db_admin):
        await update.message.reply_text("⛔ **Access Denied:** Admin only command.")
        return

    # --- 2. Parse Arguments ---
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "⚠️ **Invalid Usage**\n\n"
            "Format: `/removeuser <TelegramID>`\n"
            "Example: `/removeuser 123456789`",
            parse_mode="Markdown"
        )
        return

    target_id = args[0]
    
    if "users" not in db or target_id not in db["users"]:
        await update.message.reply_text(f"❌ User ID `{target_id}` not found in database.", parse_mode="Markdown")
        return

    # --- 3. Process Removal (ATOMIC) ---
    target_username = db["users"][target_id].get("username", "Unknown")
    # Don't delete from local 'db' yet, do it in modifier
    
    status_msg = await update.message.reply_text("⏳ Syncing removal to GitHub...")
    
    def remove_user_modifier(db):
        if "users" not in db or target_id not in db["users"]:
            return False
        del db["users"][target_id]
        return True

    commit_msg = f"database: Remove {target_username} from database"
    
    success = await asyncio.to_thread(atomic_db_update, remove_user_modifier, commit_msg)
    
    if success:
        msg = (
            f"✅ **User Removed**\n\n"
            f"🆔 **ID:** `{target_id}`\n"
            f"👤 **Name:** `{target_username}`\n"
            f"🗑 **Action:** Removed from DB\n"
            f"☁️ **Synced:** GitHub"
        )
        await status_msg.edit_text(msg, parse_mode="Markdown")
    else:
        await status_msg.edit_text("❌ Failed to sync to GitHub. Check logs.")

@restricted_command
async def add_quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sender_id = user.id
    
    # --- 1. Check Permissions ---
    # STRICTLY OWNER ONLY
    db = load_db()
    sender_data = db.get("users", {}).get(str(sender_id), {})
    sender_role = sender_data.get("role")
    
    if sender_role != ROLE_OWNER:
        await update.message.reply_text("⛔ **Access Denied:** Owner only command.")
        return

    # --- 2. Parse Arguments ---
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ **Invalid Usage**\n\n"
            "Format: `/addquota <Username> <Amount>`\n"
            "Example: `/addquota UserA 2`\n"
            "(This decreases their used count, giving them more builds)",
            parse_mode="Markdown"
        )
        return

    target_username = args[0]
    try:
        amount = int(args[1])
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Amount must be a positive integer.")
        return

    # --- 3. Find User ID by Username ---
    target_id = None
    target_real_name = ""
    if "users" in db:
        for uid, udata in db["users"].items():
            if udata.get("username", "").lower() == target_username.lower():
                target_id = uid
                target_real_name = udata.get("username", target_username)
                break
    
    if not target_id:
        await update.message.reply_text(f"❌ User `{target_username}` not found in database.", parse_mode="Markdown")
        return

    # --- 4. Update Logic (ATOMIC) ---
    # We calculate 'new_used' here just for display, but real calculation happens in modifier
    current_used = db["users"][target_id].get("daily_count", 0)
    new_used_display = max(0, current_used - amount)
    
    if new_used_display == current_used and current_used == 0:
        await update.message.reply_text(f"⚠️ User `{target_real_name}` already has 0 used builds (Full Quota).")
        return

    status_msg = await update.message.reply_text("⏳ Syncing quota change to GitHub...")
    
    def add_quota_modifier(db):
        if "users" not in db or target_id not in db["users"]:
            return False
        
        # Recalculate inside lock
        curr = db["users"][target_id].get("daily_count", 0)
        new_val = max(0, curr - amount)
        db["users"][target_id]["daily_count"] = new_val
        return True

    commit_msg = f"quota: Add {amount} more quota for {target_real_name}"
    
    success = await asyncio.to_thread(atomic_db_update, add_quota_modifier, commit_msg)
    
    if success:
        msg = (
            f"✅ **Quota Added**\n\n"
            f"👤 **User:** `{target_real_name}`\n"
            f"📉 **Used:** `{current_used}` ➔ `{new_used_display}`\n"
            f"➕ **Added:** `{amount}` builds\n"
            f"☁️ **Synced:** GitHub"
        )
        await status_msg.edit_text(msg, parse_mode="Markdown")
    else:
        await status_msg.edit_text("❌ Failed to sync to GitHub. Check logs.")
