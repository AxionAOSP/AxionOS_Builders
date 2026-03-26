import os
import sys
import asyncio

# === CUSTOM LIBRARY LOADER (MUST BE FIRST) ===
custom_lib_path = os.path.expanduser("~/pylib")
if os.path.isdir(custom_lib_path):
    if custom_lib_path not in sys.path:
        sys.path.insert(0, custom_lib_path)
        print(f"[INIT] Loading custom libraries from: {custom_lib_path}")

# === IMPORTS ===
from github import Github, Auth
import redis
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

# Import Utils
from utils import BOT_TOKEN, REDIS_URL

# Import Handlers
# CHANGED: Import from github handler
from handlers.github import (
    build_command, status_command, quota_command, cancel_command,
    handle_github_callbacks
)
from handlers.admin import add_user_command, remove_user_command, set_role_command, add_quota_command
from handlers.general import start_command, help_command, list_users_command, guide_command

def get_github_client():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("[ERROR] GITHUB_TOKEN not found in environment.")
        return None
    try:
        auth = Auth.Token(token)
        # Add Timeout (60s) and Retry (5 times)
        g = Github(auth=auth, timeout=60, retry=5)
        # Test connection
        print(f"[INIT] GitHub Connected: {g.get_user().login}")
        return g
    except Exception as e:
        print(f"[ERROR] GitHub Connection Failed: {e}")
        return None

async def main():
    # Load env explicitly if needed, though utils.py does it too
    if not BOT_TOKEN or not REDIS_URL:
        print("[ERROR] Config Missing (BOT_TOKEN or REDIS_URL). Check private.env")
        return

    # 1. Init Connections
    redis_client = None
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        print("[INIT] Redis Connected.")
    except Exception as e:
        print(f"[ERROR] Redis: {e}")
        return

    gh_client = get_github_client()

    # 2. Build App
    # Fix Connection Timeout Issues
    trequest = HTTPXRequest(
        connection_pool_size=20,
        read_timeout=120.0,
        write_timeout=120.0,
        connect_timeout=120.0,
        pool_timeout=120.0
    )
    app = ApplicationBuilder().token(BOT_TOKEN).request(trequest).build()
    
    # Inject dependencies into bot_data
    app.bot_data["redis"] = redis_client
    app.bot_data["github_client"] = gh_client

    # 3. Register Handlers
    
    # --- GENERAL HANDLERS ---
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("guide", guide_command))
    app.add_handler(CommandHandler("listuser", list_users_command))

    # --- ADMIN HANDLERS ---
    app.add_handler(CommandHandler("adduser", add_user_command))
    app.add_handler(CommandHandler("removeuser", remove_user_command))
    app.add_handler(CommandHandler("setrole", set_role_command))
    app.add_handler(CommandHandler("addquota", add_quota_command))

    # --- GITHUB ACTIONS HANDLERS ---
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("quota", quota_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    
    # Regex pattern for GitHub Callbacks (starts with build_)
    app.add_handler(CallbackQueryHandler(handle_github_callbacks, pattern=r"^(build_).*"))

    # --- OTA HANDLERS ---
    
    # 4. Run Loop
    print("Bot is Running...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    try:
        # Keep running until interrupted
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # Graceful Shutdown
        print("Shutting down...")
        if redis_client: 
            redis_client.close()
            print("Redis closed.")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        print("Bot Stopped.")

if __name__ == "__main__":
    asyncio.run(main())