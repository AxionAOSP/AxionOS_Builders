import os
import json
import asyncio
import httpx
import time
import base64
import logging
from datetime import datetime, timezone, timedelta
from functools import partial, wraps
from dotenv import load_dotenv
import redis.asyncio as redis

logger = logging.getLogger("BotUtils")
base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(base_dir, 'private.env'))

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
REDIS_URL = os.environ.get("REDIS_URL")
STICKER_ID = os.environ.get("STICKER_ID")

TEST_GROUP_ID = int(os.environ.get("TEST_GROUP_ID", "0"))
TEST_CHANNEL_ID = os.environ.get("TEST_CHANNEL_ID")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

DONATE_URL = "https://t.me/donate_zero/6"
AXN_SUPPORT = "https://t.me/AxionOS"
SOURCE_CHANGELOGS_URL = "https://axionos.com/changelog/"

def parse_list(env_str):
    if not env_str: return []
    return [int(x.strip()) for x in env_str.split(",") if x.strip().isdigit()]

ADMIN_USER_IDS = parse_list(os.environ.get("ADMIN_USER_IDS", ""))

# GitHub Config
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
DB_REPO = os.environ.get("DB_REPO", GITHUB_REPO_NAME) 
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "actions")
DB_FILE_PATH = "database.json"

# Constants
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_OWNER = "owner"

# Redis Keys
RK_USERS = "axn:users"
RK_CHATS = "axn:chats"
RK_CONFIG = "axn:config"
RK_PERSIST_USER = "axn:persist:user"
RK_PERSIST_CHAT = "axn:persist:chat"
RK_PERSIST_BOT = "axn:persist:bot"

from telegram.ext import BasePersistence

class RedisPersistence(BasePersistence):
    """Redis-based persistence for Telegram Bot"""
    def __init__(self):
        super().__init__()
        self.store_user_data = True
        self.store_chat_data = True
        self.store_bot_data = True
        self.r = None

    async def _init_redis(self):
        if not self.r:
            self.r = await get_redis()

    async def get_user_data(self):
        await self._init_redis()
        data = await self.r.hgetall(RK_PERSIST_USER)
        return {int(k): json.loads(v) for k, v in data.items()}

    async def update_user_data(self, user_id, data):
        await self._init_redis()
        await self.r.hset(RK_PERSIST_USER, str(user_id), json.dumps(data))

    async def get_chat_data(self):
        await self._init_redis()
        data = await self.r.hgetall(RK_PERSIST_CHAT)
        return {int(k): json.loads(v) for k, v in data.items()}

    async def update_chat_data(self, chat_id, data):
        await self._init_redis()
        await self.r.hset(RK_PERSIST_CHAT, str(chat_id), json.dumps(data))

    async def get_bot_data(self):
        await self._init_redis()
        data = await self.r.get(RK_PERSIST_BOT)
        return json.loads(data) if data else {}

    async def update_bot_data(self, data):
        await self._init_redis()
        await self.r.set(RK_PERSIST_BOT, json.dumps(data))

    async def refresh_bot_data(self, bot_data): pass
    async def refresh_chat_data(self, chat_id, chat_data): pass
    async def refresh_user_data(self, user_id, user_data): pass

    async def drop_chat_data(self, chat_id):
        await self._init_redis()
        await self.r.hdel(RK_PERSIST_CHAT, str(chat_id))

    async def drop_user_data(self, user_id):
        await self._init_redis()
        await self.r.hdel(RK_PERSIST_USER, str(user_id))

    async def get_conversations(self, name):
        await self._init_redis()
        data = await self.r.hget(RK_PERSIST_BOT, f"conv:{name}")
        return json.loads(data) if data else {}

    async def update_conversation(self, name, key, new_state):
        await self._init_redis()
        convs = await self.get_conversations(name)
        convs[str(key)] = new_state
        await self.r.hset(RK_PERSIST_BOT, f"conv:{name}", json.dumps(convs))

    async def get_callback_data(self): return None
    async def update_callback_data(self, data): pass
    async def get_conversation_data(self): return {}
    async def update_conversation_data(self, name, key, data): pass
    async def flush(self): pass

_redis_pool = None

async def get_redis():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_pool

def get_github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AxionOS-Bot"
    }

async def fetch_db_from_github():
    """Sync database from GitHub to Redis"""
    url = f"https://api.github.com/repos/{DB_REPO}/contents/{DB_FILE_PATH}?ref={GITHUB_BRANCH}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=get_github_headers(), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                content = base64.b64decode(data['content']).decode('utf-8')
                db = json.loads(content)
                
                r = await get_redis()
                pipe = r.pipeline()
                
                pipe.delete(RK_CHATS)
                chats = db.get("allowed_chats", [])
                if chats: pipe.sadd(RK_CHATS, *chats)
                
                pipe.delete(RK_USERS)
                users = db.get("users", {})
                for uid, udata in users.items():
                    pipe.hset(RK_USERS, uid, json.dumps(udata))
                
                pipe.hset(RK_CONFIG, "db_sha", data['sha'])
                await pipe.execute()
                logger.info("Redis cache refreshed from GitHub")
                return db
        except Exception as e:
            logger.error(f"GitHub Fetch Failed: {e}")
    return None

async def save_db_to_github(commit_message="database: update from bot"):
    """Sync Redis state to GitHub database.json"""
    r = await get_redis()
    chats = await r.smembers(RK_CHATS)
    raw_users = await r.hgetall(RK_USERS)
    users = {uid: json.loads(udata) for uid, udata in raw_users.items()}
    
    db = {"users": users, "allowed_chats": list(chats)}
    sha = await r.hget(RK_CONFIG, "db_sha")
    
    url = f"https://api.github.com/repos/{DB_REPO}/contents/{DB_FILE_PATH}"
    json_str = json.dumps(db, indent=2)
    b64_content = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
    
    payload = {
        "message": commit_message,
        "content": b64_content,
        "branch": GITHUB_BRANCH,
        "sha": sha,
        "committer": {"name": "github-actions[bot]", "email": "41898282+github-actions[bot]@users.noreply.github.com"},
        "author": {"name": "github-actions[bot]", "email": "41898282+github-actions[bot]@users.noreply.github.com"}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.put(url, headers=get_github_headers(), json=payload, timeout=20)
            if resp.status_code in [200, 201]:
                new_sha = resp.json()['content']['sha']
                await r.hset(RK_CONFIG, "db_sha", new_sha)
                logger.info(f"GitHub backup successful: {commit_message}")
                return True
        except Exception as e:
            logger.error(f"GitHub Sync Failed: {e}")
    return False

async def is_chat_allowed(chat_id):
    """Check if chat is approved"""
    if TEST_GROUP_ID != 0 and chat_id == TEST_GROUP_ID:
        return True
    
    env_allowed = parse_list(os.environ.get("ALLOWED_CHAT_IDS", ""))
    if chat_id in env_allowed:
        return True
    
    r = await get_redis()
    return await r.sismember(RK_CHATS, str(chat_id))

def restricted_command(func):
    """Decorator to restrict commands to allowed chats"""
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        if not update.effective_chat: return
        if not await is_chat_allowed(update.effective_chat.id):
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def get_user_data(user_id):
    r = await get_redis()
    data = await r.hget(RK_USERS, str(user_id))
    return json.loads(data) if data else None

async def update_user_data(user_id, modifier_func, commit_msg=None):
    """Update user in Redis + sync to GitHub in background"""
    r = await get_redis()
    uid = str(user_id)
    
    raw = await r.hget(RK_USERS, uid)
    data = json.loads(raw) if raw else {"role": ROLE_USER}
    
    if not modifier_func(data): return False
    
    await r.hset(RK_USERS, uid, json.dumps(data))
    if commit_msg:
        asyncio.create_task(save_db_to_github(commit_msg))
    
    return True

def convert_to_raw_url(url):
    """Converts Git web UI URLs into raw content URLs"""
    if not url: return ""
    url = url.strip()
    
    if "github.com" in url:
        if "raw.githubusercontent.com" in url: return url
        if "/blob/" in url: return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        if "/raw/" in url: return url.replace("github.com", "raw.githubusercontent.com").replace("/raw/", "/")
        
    if "gitlab.com" in url:
        if "/raw/" in url: return url
        if "/blob/" in url: return url.replace("/blob/", "/raw/")

    if "bitbucket.org" in url:
        if "/raw/" in url: return url
        if "/src/" in url: return url.replace("/src/", "/raw/")

    if "gist.github.com" in url and "/raw" not in url:
        return url.rstrip("/") + "/raw"

    return url

def bytes_to_gb(size_bytes):
    if not isinstance(size_bytes, (int, float)) or size_bytes == 0: return "N/A"
    return f"{size_bytes / (1024 ** 3):.2f} GB"

def format_date(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%d %B %Y")
