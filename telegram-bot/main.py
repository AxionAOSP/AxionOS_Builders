import os
import sys
import asyncio
import time
import json
import logging

bot_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(bot_dir, "bot.log")

file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(message)s'))

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger("BotMain")

custom_lib_path = os.path.expanduser("~/pylib")
if os.path.isdir(custom_lib_path):
    if custom_lib_path not in sys.path:
        sys.path.insert(0, custom_lib_path)
        print(f"[INIT] Loading custom libraries from: {custom_lib_path}")

import redis.asyncio as redis
from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeAllGroupChats, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

from utils import BOT_TOKEN, REDIS_URL, fetch_db_from_github, get_redis, RedisPersistence, OWNER_ID

from handlers.github import (
    build_command, status_command, queue_command, cancel_command,
    handle_github_callbacks, get_workflow_runs
)
from handlers.admin import (
    remove_user_command, set_role_command, 
    approve_chat_command, disapprove_chat_command,
    sync_db_command, save_db_command, set_channel_command, remove_channel_command,
    announce_command, list_chats_command, usepd_command
)
from handlers.general import (
    start_command, help_command, list_users_command, guide_command,
    health_command, history_command, full_history_command
)

async def set_bot_commands(app):
    """Sets bot commands for Telegram menu"""
    commands = [
        BotCommand("build", "🚀 Start a new ROM build"),
        BotCommand("status", "📊 View real-time progress"),
        BotCommand("queue", "🔭 View GitHub Actions queue"),
        BotCommand("history", "📜 View recent build history"),
        BotCommand("health", "🖥️ Check server disk & RAM"),
        BotCommand("listuser", "👤 List all authorized admins"),
        BotCommand("cancel", "🛑 Cancel a build (Self or Any if Admin)"),
        BotCommand("cancelall", "🛑 Cancel all queued/running builds (Owner)"),
        BotCommand("save", "💾 Force sync Redis to GitHub (Admin)"),
        BotCommand("sync", "🔄 Force sync GitHub to Redis (Owner)"),
        BotCommand("announce", "📢 Broadcast message to all groups (Owner)"),
        BotCommand("listchats", "📡 View all authorized groups & channel (Admin)"),
        BotCommand("setchannel", "📢 Set main output channel (Admin)"),
        BotCommand("removechannel", "🗑️ Remove main output channel (Admin)"),
        BotCommand("approvechat", "✅ Authorize a group (Admin)"),
        BotCommand("disapprovechat", "🗑️ Unauthorize a group (Admin)"),
        BotCommand("usepd", "📡 Toggle or set Pixeldrain upload stream (Admin)"),
        BotCommand("help", "📖 Show help & documentation")
    ]

    try:
        await app.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        await app.bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
        print("[INIT] Bot commands registered.")
    except Exception as e:
        print(f"[ERROR] Failed to set commands: {e}")

async def sync_active_builds():
    """Syncs active/queued GitHub runs to Redis on startup"""
    active_runs = await get_workflow_runs(status="in_progress") or []
    queued_runs = await get_workflow_runs(status="queued") or []
    runs = active_runs + queued_runs
    
    if not runs: return
    
    r = await get_redis()
    logger.info(f"Found {len(runs)} active/queued builds. Syncing Redis...")
    
    for run in runs:
        title = run.get("display_title", "") or run.get("name", "")
        device = "Unknown"
        if "(" in title: device = title.split("(")[0].strip()
        elif "|" in title: device = title.split("|")[0].strip()
            
        status_key = f"build_status:{device}"
        current_status = "Resumed (Active)" if run.get("status") == "in_progress" else "Queued (Waiting)"
        
        if not await r.exists(status_key):
            data = {
                "status": current_status,
                "device": device,
                "url": run.get("html_url"),
                "run_id": run.get("id"),
                "updated_at": int(time.time()),
                "progress": "Bot restarted - Resuming monitoring..."
            }
            await r.set(status_key, json.dumps(data), ex=86400)
            await r.set("active_build_device", device, ex=86400)
            logger.info(f"Resumed tracking for {device}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs error and notifies owner"""
    print(f"[ERROR] Exception: {context.error}")
    if OWNER_ID:
        try:
            err_msg = str(context.error)
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"🚨 **Bot Error Detected**\n\n<code>{err_msg[:4000]}</code>",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[ERROR] Failed to notify owner: {e}")

async def main():
    if not BOT_TOKEN or not REDIS_URL:
        logger.error("Config Missing. Check private.env")
        return

    r = await get_redis()
    try:
        await r.ping()
        logger.info("Redis Connected.")
        await fetch_db_from_github()
        await sync_active_builds()
    except Exception as e:
        logger.critical(f"Startup Failure: {e}")
        return

    trequest = HTTPXRequest(
        connection_pool_size=30,
        read_timeout=60.0,
        write_timeout=60.0,
        connect_timeout=60.0,
        pool_timeout=60.0
    )
    
    persistence = RedisPersistence()
    app = ApplicationBuilder().token(BOT_TOKEN).request(trequest).persistence(persistence).build()
    app.add_error_handler(error_handler)
    app.bot_data["redis"] = r

    # Register Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("guide", guide_command))
    app.add_handler(CommandHandler("listuser", list_users_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("fullhistory", full_history_command))

    app.add_handler(CommandHandler("sync", sync_db_command))
    app.add_handler(CommandHandler("save", save_db_command))
    app.add_handler(CommandHandler("setchannel", set_channel_command))
    app.add_handler(CommandHandler("removechannel", remove_channel_command))
    app.add_handler(CommandHandler("approvechat", approve_chat_command))
    app.add_handler(CommandHandler("disapprovechat", disapprove_chat_command))
    app.add_handler(CommandHandler("listchats", list_chats_command))
    app.add_handler(CommandHandler("removeuser", remove_user_command))
    app.add_handler(CommandHandler("setrole", set_role_command))
    app.add_handler(CommandHandler("announce", announce_command))
    app.add_handler(CommandHandler("usepd", usepd_command))

    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    from handlers.github import cancel_all_command
    app.add_handler(CommandHandler("cancelall", cancel_all_command))

    app.add_handler(CallbackQueryHandler(handle_github_callbacks, pattern=r"^(build_).*"))

    logger.info("🚀 Bot is Running")
    await app.initialize()
    await set_bot_commands(app)
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Shutting down...")
        await r.close()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Bot Stopped.")

if __name__ == "__main__":
    asyncio.run(main())
