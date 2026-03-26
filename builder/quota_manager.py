#!/usr/bin/env python3
import os
import sys

# === CUSTOM LIBRARY LOADER ===
custom_lib_path = os.path.expanduser("~/pylib")
if os.path.isdir(custom_lib_path):
    if custom_lib_path not in sys.path:
        sys.path.insert(0, custom_lib_path)
        print(f"[INIT] Loading custom libraries from: {custom_lib_path}")

import json
from datetime import datetime, timezone
from github import Github, Auth, InputGitAuthor
from utils.telegram import TelegramBot

# Configuration
MAX_QUOTA = 5
ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"

# GitHub Actions Bot Identity
GHA_NAME = "github-actions[bot]"
GHA_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

def get_env_var(name, default=None):
    val = os.environ.get(name, default)
    if not val and default is None:
        print(f"[ERROR] Environment variable {name} is missing.")
        sys.exit(1)
    return val

def main():
    if len(sys.argv) < 3:
        print("Usage: quota_manager.py <USER_ID> <USERNAME> [FULL_CLEAN]")
        sys.exit(1)

    user_id = sys.argv[1]
    username = sys.argv[2]
    is_full_clean = sys.argv[3] if len(sys.argv) > 3 else "No"

    # 1. Setup GitHub Connection
    token = get_env_var("GITHUB_TOKEN")
    repo_name = get_env_var("GITHUB_REPO_NAME")
    
    # Determine Branch: Prefer GITHUB_BRANCH, fallback to GITHUB_REF_NAME, then 'actions'
    branch = os.environ.get("GITHUB_BRANCH") or os.environ.get("GITHUB_REF_NAME") or "actions"
    
    # Strip 'refs/heads/' if present (common in GITHUB_REF)
    if branch.startswith("refs/heads/"):
        branch = branch.replace("refs/heads/", "")

    print(f"[API] Connecting to {repo_name} on branch {branch}...")
    
    try:
        auth = Auth.Token(token)
        g = Github(auth=auth)
        repo = g.get_repo(repo_name)
        
        # 2. Get Database File
        try:
            file_content = repo.get_contents("database.json", ref=branch)
            db = json.loads(file_content.decoded_content.decode())
        except Exception as e:
            print(f"[API ERROR] Failed to fetch database.json: {e}")
            sys.exit(1)

        # 3. Process Logic
        print(f"Processing quota for User: {username} (ID: {user_id})")
        
        if user_id not in db["users"]:
            print("User not found in DB. Skipping quota update.")
            sys.exit(0)

        user_data = db["users"][user_id]
        role = user_data.get("role", "user")

        # Security Check: Full Clean
        if is_full_clean == "Yes" and role not in [ROLE_ADMIN, ROLE_OWNER]:
            print("⛔ SECURITY ALERT: Full Clean is restricted to Admins only!")
            sys.exit(1)

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        last_date = user_data.get("last_build_date", "")

        if last_date != today_str:
            print(f"New day detected (Last: {last_date}, Today: {today_str}). Resetting counter.")
            user_data["daily_count"] = 0
            user_data["last_build_date"] = today_str

        # Check Limit
        current_count = user_data.get("daily_count", 0)
        if role not in [ROLE_ADMIN, ROLE_OWNER] and current_count >= MAX_QUOTA:
            print(f"[ERROR] Quota Exceeded! Used: {current_count}/{MAX_QUOTA}")
            
            # Notification Handler
            token_bot = os.environ.get("TELEGRAM_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            topic_id = os.environ.get("TOPIC_BUILDER")
            
            if token_bot and chat_id:
                try:
                    bot = TelegramBot(token_bot)
                    now = datetime.now(timezone.utc)
                    reset_time = (now.replace(hour=23, minute=59, second=59, microsecond=999999) - now)
                    hours, remainder = divmod(reset_time.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    
                    msg = (
                        f"⛔ **Quota Exceeded**\n\n"
                        f"👤 **User:** `{username}`\n"
                        f"🏷 **Role:** `{role.upper()}`\n"
                        f"🔢 **Used:** `{current_count}/{MAX_QUOTA}`\n"
                        f"⏳ **Reset in:** `{hours}h {minutes}m`\n\n"
                        f"Please wait for the daily reset or ask an admin."
                    )
                    bot.send_message(chat_id, msg, topic_id=topic_id)
                except Exception as e:
                    print(f"[NOTIF ERROR] Failed to send notification: {e}")

            # Create marker file
            workspace = os.environ.get("WORKSPACE", ".")
            with open(os.path.join(workspace, ".quota_exceeded"), "w") as f:
                f.write("true")
            sys.exit(1)

        # Increment
        user_data["daily_count"] += 1
        user_data["username"] = username

        # 4. Commit Changes via API
        print("[API] Updating database.json...")
        new_content = json.dumps(db, indent=2)
        commit_message = f"quota: Update build quota for {username}"
        
        # Create Author Object
        author = InputGitAuthor(name=GHA_NAME, email=GHA_EMAIL)

        repo.update_file(
            path=file_content.path,
            message=commit_message,
            content=new_content,
            sha=file_content.sha,
            branch=branch,
            author=author,
            committer=author
        )
        print("[API] Success.")

    except Exception as e:
        print(f"[CRITICAL ERROR] Script failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()