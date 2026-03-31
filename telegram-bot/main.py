import os
import sys
import asyncio

# === CUSTOM LIBRARY LOADER ===
custom_lib_path = os.path.expanduser("~/pylib")
if os.path.isdir(custom_lib_path):
    if custom_lib_path not in sys.path:
        sys.path.insert(0, custom_lib_path)
        print(f"[INIT] Loading custom libraries from: {custom_lib_path}")

# === IMPORTS ===
import redis.asyncio as redis
from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeAllGroupChats
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

# Import Utils
from utils import BOT_TOKEN, REDIS_URL, fetch_db_from_github, get_redis

# Import Handlers
from handlers.github import (
    build_command, status_command, queue_command, quota_command, cancel_command,
    handle_github_callbacks
)
from handlers.admin import (
    add_user_command, remove_user_command, set_role_command, 
    add_quota_command, approve_chat_command, sync_db_command
)
from handlers.general import (
    start_command, help_command, list_users_command, guide_command,
    health_command, history_command, full_history_command
)

async def set_bot_commands(app):
    """Sets the bot commands for the Telegram menu with global scope."""
    commands = [
        BotCommand("build", "Start a new ROM build"),
        BotCommand("status", "Show real-time progress"),
        BotCommand("queue", "View GitHub Actions queue"),
        BotCommand("history", "View build history"),
        BotCommand("health", "Check server health"),
        BotCommand("quota", "Check build limits"),
        BotCommand("cancel", "Cancel a running build"),
        BotCommand("help", "Show all commands")
    ]
    try:
        # Set for Private Chats (Default)
        await app.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        # Set for all Groups
        await app.bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
        print("[INIT] Bot commands registered for all scopes.")
    except Exception as e:
        print(f"[ERROR] Failed to set commands: {e}")

async def main():
    if not BOT_TOKEN or not REDIS_URL:
        print("[ERROR] Config Missing. Check private.env")
        return

    # 1. Init Redis & DB Cache
    r = await get_redis()
    try:
        await r.ping()
        print("[INIT] Redis Connected.")
        # Load fresh data from GitHub into Redis on startup
        print("[INIT] Refreshing DB cache from GitHub...")
        await fetch_db_from_github()
    except Exception as e:
        print(f"[ERROR] Startup: {e}")
        return

    # 2. Build App with Optimized HTTPX Request
    trequest = HTTPXRequest(
        connection_pool_size=30,
        read_timeout=60.0,
        write_timeout=60.0,
        connect_timeout=60.0,
        pool_timeout=60.0
    )
    app = ApplicationBuilder().token(BOT_TOKEN).request(trequest).build()

    # Inject Redis into bot_data (Async compatible)
    app.bot_data["redis"] = r

    # 3. Register Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("guide", guide_command))
    app.add_handler(CommandHandler("listuser", list_users_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("fullhistory", full_history_command))

    app.add_handler(CommandHandler("sync", sync_db_command))
    app.add_handler(CommandHandler("approvechat", approve_chat_command))
    app.add_handler(CommandHandler("adduser", add_user_command))
    app.add_handler(CommandHandler("removeuser", remove_user_command))
    app.add_handler(CommandHandler("setrole", set_role_command))
    app.add_handler(CommandHandler("addquota", add_quota_command))

    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("quota", quota_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    app.add_handler(CallbackQueryHandler(handle_github_callbacks, pattern=r"^(build_).*"))

    # 4. Run Loop
    print("🚀 Bot is Running (Fully Optimized Mode)")
    await app.initialize()
    await set_bot_commands(app)
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("Shutting down...")
        await r.close()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        print("Bot Stopped.")

if __name__ == "__main__":
    asyncio.run(main())
