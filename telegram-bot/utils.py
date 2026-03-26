import os
import json
import asyncio
import requests
import time
from datetime import datetime, timezone, timedelta
from functools import partial, wraps
from dotenv import load_dotenv

# === CONFIGURATION ===
# Load env relative to this file
base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(base_dir, 'private.env'))

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
REDIS_URL = os.environ.get("REDIS_URL")
STICKER_ID = os.environ.get("STICKER_ID")

DONATE_URL = "https://t.me/donate_zero/6"
AXN_SUPPORT = "https://t.me/AxionOS"
SOURCE_CHANGELOGS_URL = "https://axionos.com/changelog/"

import base64

TEST_GROUP_ID = int(os.environ.get("TEST_GROUP_ID", "0"))
TEST_CHANNEL_ID = os.environ.get("TEST_CHANNEL_ID")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# GitHub Config
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
# Use DB_REPO if set, otherwise fallback to GITHUB_REPO_NAME
DB_REPO = os.environ.get("DB_REPO", GITHUB_REPO_NAME) 
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "actions")
DB_FILE_PATH = "database.json" # Path in repo

# Parse Lists
def parse_list(env_str):
    if not env_str: return []
    result = []
    for x in env_str.split(","):
        try:
            result.append(int(x.strip()))
        except ValueError:
            pass
    return result

ALLOWED_CHAT_IDS = parse_list(os.environ.get("ALLOWED_CHAT_IDS", ""))
if TEST_GROUP_ID != 0 and TEST_GROUP_ID not in ALLOWED_CHAT_IDS:
    ALLOWED_CHAT_IDS.append(TEST_GROUP_ID)

ADMIN_USER_IDS = parse_list(os.environ.get("ADMIN_USER_IDS", ""))

# === CONSTANTS ===
MAX_QUOTA_USER = 5
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_OWNER = "owner"

# === DECORATORS ===
def restricted_command(func):
    """Decorator to restrict command usage to specific chats."""
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        chat_id = update.effective_chat.id
        if chat_id not in ALLOWED_CHAT_IDS:
            # Optional: Log attempt or silently ignore
            # print(f"[SECURITY] Ignored command from unauthorized chat: {chat_id}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# === DATABASE UTILS (GITHUB) ===
def get_github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

def load_db():
    """Load DB from GitHub only"""
    if not GITHUB_TOKEN or not DB_REPO:
        print("[DB ERROR] Missing GITHUB_TOKEN or DB_REPO")
        return {"users": {}}

    url = f"https://api.github.com/repos/{DB_REPO}/contents/{DB_FILE_PATH}?ref={GITHUB_BRANCH}"
    try:
        resp = requests.get(url, headers=get_github_headers(), timeout=10)
        if resp.status_code == 200:
            content = base64.b64decode(resp.json()['content']).decode('utf-8')
            return json.loads(content)
        else:
            print(f"[DB ERROR] GitHub Load Failed ({resp.status_code}): {resp.text}")
            return {"users": {}}
    except Exception as e:
        print(f"[DB ERROR] GitHub Load Exception: {e}")
        return {"users": {}}

def commit_db_to_github(new_data, commit_message):
    """Commit new DB state to GitHub"""
    if not GITHUB_TOKEN or not DB_REPO:
        print("[DB ERROR] Missing GITHUB_TOKEN or DB_REPO")
        return False
    
    url = f"https://api.github.com/repos/{DB_REPO}/contents/{DB_FILE_PATH}"
    headers = get_github_headers()
    
    try:
        # 1. Get current SHA
        sha = None
        get_resp = requests.get(f"{url}?ref={GITHUB_BRANCH}", headers=headers, timeout=10)
        if get_resp.status_code == 200:
            sha = get_resp.json()['sha']
        
        # 2. Prepare Payload
        json_str = json.dumps(new_data, indent=2)
        b64_content = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        
        payload = {
            "message": commit_message,
            "content": b64_content,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha
            
        # 3. PUT Request
        put_resp = requests.put(url, headers=headers, json=payload, timeout=15)
        if put_resp.status_code in [200, 201]:
            # Also update local file for consistency -> REMOVED PER USER REQUEST
            return True
        else:
            print(f"[DB ERROR] Commit Failed: {put_resp.text}")
            return False
            
    except Exception as e:
        print(f"[DB ERROR] Commit Exception: {e}")
        return False

def atomic_db_update(modifier_func, commit_message, max_retries=3):
    """
    Atomically updates the database with retries for race conditions.
    :param modifier_func: Function that takes 'db' dict as input. 
                          Should modify it in place and return True/False.
                          If False, update is aborted.
    """
    attempt = 0
    while attempt < max_retries:
        # 1. Fetch Latest DB
        db = load_db()
        
        # 2. Apply Modification
        # We pass a copy or just rely on 'load_db' returning a fresh dict (it does)
        should_proceed = modifier_func(db)
        
        if not should_proceed:
            # Modifier decided to abort (e.g. user not found)
            return False
            
        # 3. Try Commit
        if commit_db_to_github(db, commit_message):
            return True
        
        # 4. Retry Logic
        attempt += 1
        print(f"[DB WARN] Atomic update failed (Race condition?). Retrying {attempt}/{max_retries}...")
        time.sleep(1 + attempt) # Exponential backoffish
        
    print("[DB ERROR] Atomic update failed after max retries.")
    return False

def get_user_data(user_id):
    db = load_db()
    return db["users"].get(str(user_id))

def get_quota_status(user_id):
    user_data = get_user_data(user_id)
    if not user_data: return None, 0, 0
    role = user_data.get("role", ROLE_USER)
    
    last_date = user_data.get("last_build_date", "")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    used = user_data.get("daily_count", 0) if last_date == today_str else 0
    limit = 999 if role in [ROLE_ADMIN, ROLE_OWNER] else MAX_QUOTA_USER
    return role, used, limit - used

# === REDIS UTILS ===
async def run_redis_command(redis_client, command_name, *args, **kwargs):
    try:
        cmd = getattr(redis_client, command_name)
        sync_call = partial(cmd, *args, **kwargs)
        return await asyncio.to_thread(sync_call)
    except Exception as e:
        print(f"[REDIS ERROR] {e}")
        return None

# === FORMATTING UTILS ===
def convert_to_raw_url(url):
    if not url: return ""
    
    # GitHub
    if "github.com" in url and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    
    # GitLab (Official)
    if "gitlab.com" in url and "/blob/" in url:
        return url.replace("/blob/", "/raw/")

    # Bitbucket
    if "bitbucket.org" in url and "/src/" in url:
        return url.replace("/src/", "/raw/")

    # GitHub Gist
    if "gist.github.com" in url and "/raw" not in url:
        return url.rstrip("/") + "/raw"

    # Generic Fallback (Gitea, Forgejo, Self-hosted GitLab, etc.)
    # Most git frontends use /blob/ for UI and /raw/ for raw content
    if "/blob/" in url:
        return url.replace("/blob/", "/raw/")
        
    return url

def bytes_to_gb(size_bytes):
    if not isinstance(size_bytes, (int, float)) or size_bytes == 0: return "N/A"
    return f"{size_bytes / (1024 ** 3):.2f} GB"

def format_date(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%d %B %Y")
