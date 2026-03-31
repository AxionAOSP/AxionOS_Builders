import asyncio
import os
import html
import httpx
import xml.etree.ElementTree as ET
import time
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest
from datetime import datetime, timezone, timedelta
from utils import (
    get_quota_status, get_user_data, update_user_data, convert_to_raw_url,
    MAX_QUOTA_USER, ROLE_ADMIN, ROLE_OWNER, restricted_command,
    get_github_headers, get_redis
)

# Env Vars
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "actions")
WORKFLOW_ID = "axion_build.yml"

# === CONSTANTS ===
BUILD_OPTIONS = {
    'RELEASETYPE': ['user', 'userdebug', 'eng'],
    'GMS_VARIANT': ['Core', 'Pico', 'Vanilla'],
    'FULLCLEAN': ['No', 'Yes']
}

# === KEYBOARDS ===
def get_build_menu_keyboard(params):
    def btn(l, k): return InlineKeyboardButton(f"{l}: {params[k]}", callback_data=f"build_set:{k}")
    return InlineKeyboardMarkup([
        [btn("Type", "RELEASETYPE"), btn("GMS", "GMS_VARIANT")],
        [btn("Full Clean", "FULLCLEAN")],
        [InlineKeyboardButton("✅ START", callback_data="build_action:start"), InlineKeyboardButton("❌ CANCEL", callback_data="build_action:cancel")]
    ])

# === GITHUB API (ASYNC) ===

async def trigger_workflow(inputs):
    url = f"https://api.github.com/repos/{GITHUB_REPO_NAME}/actions/workflows/{WORKFLOW_ID}/dispatches"
    payload = {"ref": GITHUB_BRANCH, "inputs": inputs}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=get_github_headers(), json=payload, timeout=20)
            if resp.status_code != 204:
                print(f"[GH ERROR] Trigger failed with status {resp.status_code}: {resp.text}")
                return False
            return True
        except Exception as e:
            print(f"[GH ERROR] Trigger failed: {e}")
            return False

async def get_workflow_runs(status=None):
    url = f"https://api.github.com/repos/{GITHUB_REPO_NAME}/actions/runs"
    params = {"branch": GITHUB_BRANCH, "per_page": 15}
    if status: params["status"] = status
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=get_github_headers(), params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("workflow_runs", [])
        except Exception as e:
            print(f"[GH ERROR] Fetch runs failed: {e}")
    return []

async def cancel_workflow_run(run_id):
    url = f"https://api.github.com/repos/{GITHUB_REPO_NAME}/actions/runs/{run_id}/cancel"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=get_github_headers(), timeout=15)
            return resp.status_code == 202
        except Exception as e:
            print(f"[GH ERROR] Cancel failed: {e}")
            return False

# === HANDLERS ===

@restricted_command
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows real-time build status from Redis, with automatic GitHub-based device detection."""
    r = await get_redis()
    chat_id = update.effective_chat.id
    
    # 1. Cleanup old message
    last_mid = context.chat_data.get("last_status_mid")
    if last_mid:
        try: await context.bot.delete_message(chat_id, last_mid)
        except: pass

    # 2. Identify Device
    device = context.args[0] if context.args else None
    
    if not device:
        # Strategy A: Check Redis Pointer
        device = await r.get("active_build_device")
        
        # Strategy B: Check GitHub Action Queue if pointer is missing
        if not device:
            runs = await get_workflow_runs(status="in_progress")
            if runs:
                # Parse device from run title: "DEVICE (TYPE) | User: ..."
                title = runs[0].get("display_title", "") or runs[0].get("name", "")
                if "(" in title:
                    device = title.split("(")[0].strip()

    if not device:
        msg = await update.message.reply_text("✅ **No active builds found.**\nUse `/queue` for system-wide status.", parse_mode="Markdown")
        context.chat_data["last_status_mid"] = msg.message_id
        return

    # 3. Fetch Status Data
    raw_data = await r.get(f"build_status:{device}")
    if not raw_data:
        msg = await update.message.reply_text(f"❌ No live progress data for `{device}`.\n_The build may have just started or failed to connect to Redis._", parse_mode="Markdown")
        context.chat_data["last_status_mid"] = msg.message_id
        return

    data = json.loads(raw_data)
    status = data.get("status", "Unknown")
    progress_raw = data.get("progress", "Starting...")
    
    # Progress Bar Logic
    progress_display = progress_raw
    if "%" in progress_raw:
        try:
            pct_val = int(progress_raw.split("%")[0].strip())
            filled = int(pct_val / 10)
            bar = "▰" * filled + "▱" * (10 - filled)
            progress_display = f"<code>[{bar}]</code> {progress_raw}"
        except: pass
    
    diff = int(time.time()) - data.get("updated_at", 0)
    
    msg_text = (
        f"<b>✨ ACTIVE BUILD STATUS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📱 Device</b>   : <code>{device}</code>\n"
        f"<b>🚦 Status</b>   : <code>{status}</code>\n"
        f"<b>📊 Progress</b> : {progress_display}\n"
        f"<b>🧬 Variant</b>  : <code>{data.get('gms', 'N/A')}</code>\n"
        f"<b>👤 User</b>     : @{html.escape(data.get('user', 'Unknown'))}\n"
        f"<b>🆔 Run ID</b>   : <code>{data.get('run_id', 'N/A')}</code>\n"
        f"<b>⏱️ Updated</b>  : <code>{diff}s ago</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <a href='{data.get('url', '#')}'><b>VIEW LIVE LOGS</b></a>"
    )
    
    new_msg = await update.message.reply_text(msg_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    context.chat_data["last_status_mid"] = new_msg.message_id

@restricted_command
async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔍 Scanning GitHub Queue...")
    msg, kb = await generate_queue_message()
    await status_msg.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)

async def generate_queue_message():
    runs = await get_workflow_runs()
    msg = "<b>🔭 SYSTEM STATUS</b>\n<code>GitHub Actions Queue</code>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    active_found = False

    def parse_run_info(run):
        u_name = run.get("actor", {}).get("login", "Unknown")
        dev_name = "Unknown"
        
        name = run.get("display_title", "") or run.get("name", "")
        # Format: "DEVICE (TYPE) | User: Username (123456)"
        if "User: " in name:
            try:
                # Extract Device (everything before the first '(')
                dev_name = name.split("(")[0].strip()
                # Extract Username
                parts = name.split("User: ")[1].rsplit(" (", 1)
                u_name = parts[0]
            except: pass
        return html.escape(u_name), html.escape(dev_name)

    # Filter only relevant statuses
    for run in runs:
        if run['status'] not in ["in_progress", "queued", "waiting", "pending"]: continue
        
        active_found = True
        username, device = parse_run_info(run)
        icon = "🟢" if run['status'] == "in_progress" else "🔵"
        label = "RUNNING" if run['status'] == "in_progress" else "QUEUED"
        
        # Calculate Time for running builds
        time_str = ""
        if run['status'] == "in_progress":
            try:
                # Use run_started_at if available, fallback to created_at
                start_raw = run.get("run_started_at") or run.get("created_at")
                if start_raw:
                    start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    diff = datetime.now(timezone.utc) - start_dt
                    mins = int(diff.total_seconds() / 60)
                    if mins >= 60:
                        time_str = f"\n├ <b>Time</b> : <code>{mins // 60}h {mins % 60}m</code>"
                    else:
                        time_str = f"\n├ <b>Time</b> : <code>{mins}m</code>"
            except: pass

        msg += (
            f"{icon} <b>{label} BUILD</b>\n"
            f"├ <b>By</b> : <code>{username}</code>\n"
            f"├ <b>Device</b> : <code>{device}</code>\n"
            f"├ <b>RunID</b> : <code>{run['id']}</code>{time_str}\n"
            f"└ 🔗 <a href='{run['html_url']}'><b>VIEW LOGS</b></a>\n\n"
        )

    if not active_found:
        msg += "✅ <b>SYSTEM IDLE</b>\nReady to build."

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="build_status:refresh")]])
    return msg, kb

@restricted_command
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/cancel <RunID>`", parse_mode="Markdown")
        return

    run_id = context.args[0]
    status_msg = await update.message.reply_text(f"⏳ Cancelling Run {run_id}...")
    
    success = await cancel_workflow_run(run_id)
    if success:
        await status_msg.edit_text(f"🛑 **Run {run_id} Cancelled.**", parse_mode="Markdown")
    else:
        await status_msg.edit_text("❌ Failed to cancel. Check Run ID.")

@restricted_command
async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    role, used, remaining = await get_quota_status(uid)
    
    if not role:
        await update.message.reply_text("⛔ Not registered.")
        return

    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    diff = tomorrow - now
    h, m = diff.seconds // 3600, (diff.seconds // 60) % 60
    
    limit_str = "Unlimited" if role in [ROLE_ADMIN, ROLE_OWNER] else str(used + remaining)
    
    msg = (
        f"📊 <b>Quota Status</b>\n"
        f"├ User: <code>{html.escape(update.effective_user.first_name)}</code>\n"
        f"├ Role: <code>{role.upper()}</code>\n"
        f"├ Usage: <code>{used}/{limit_str}</code>\n"
        f"└ Reset: <code>{h}h {m}m</code>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

@restricted_command
async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    role, _, rem = await get_quota_status(uid)
    
    if role is None:
        await update.message.reply_text("⛔ Unauthorized. Use /adduser first.")
        return
    if role not in [ROLE_ADMIN, ROLE_OWNER] and rem <= 0:
        await update.message.reply_text("⛔ Quota Exceeded.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: `/build <device> <manifest_url>`")
        return

    dev, url = context.args[0], convert_to_raw_url(context.args[1])
    
    status_msg = await update.message.reply_text("🔎 Validating Manifest...")
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=10)
            if resp.status_code != 200:
                await status_msg.edit_text(f"❌ URL Error: {resp.status_code}")
                return
            
            root = ET.fromstring(resp.content)
            if root.tag != "manifest":
                await status_msg.edit_text("❌ Invalid Manifest XML.")
                return
        except Exception as e:
            await status_msg.edit_text(f"❌ Validation Failed: {e}")
            return

    await status_msg.delete()
    
    params = {
        'DEVICE': dev, 'RELEASETYPE': 'userdebug', 'GMS_VARIANT': 'Core',
        'FULLCLEAN': 'No', 'LOCAL_MANIFEST_URL': url,
        'BUILD_USER': update.effective_user.username or update.effective_user.first_name,
        'BUILD_USER_ID': str(uid)
    }
    context.user_data['pending_build'] = params
    
    lim_str = "Unlimited" if role in [ROLE_ADMIN, ROLE_OWNER] else f"{rem} left"
    msg = (
        f"<b>🚀 AXIONOS BUILD SYSTEM</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📱 Device</b>   : <code>{dev}</code>\n"
        f"<b>👤 Trigger</b>  : @{html.escape(params['BUILD_USER'])} (<code>{lim_str}</code>)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Adjust configuration:</i>"
    )
    await update.message.reply_text(msg, reply_markup=get_build_menu_keyboard(params), parse_mode=ParseMode.HTML)

async def handle_github_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "build_status:refresh":
        msg, kb = await generate_queue_message()
        try:
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
            await query.answer("Refreshed!")
        except: await query.answer()
        return

    if data.startswith("build_action:"):
        act = data.split(":")[1]
        if act == "cancel":
            await query.edit_message_text("❌ <b>Build Cancelled.</b>", parse_mode=ParseMode.HTML)
            context.user_data.pop('pending_build', None)
        elif act == "start":
            p = context.user_data.get('pending_build')
            if not p:
                await query.answer("Session Expired", show_alert=True)
                return
            
            await query.edit_message_text("⏳ <b>Dispatching Workflow...</b>", parse_mode=ParseMode.HTML)
            if await trigger_workflow(p):
                await query.edit_message_text(f"✅ <b>Build Started!</b>\nDevice: <code>{p['DEVICE']}</code>\nCheck /status shortly.", parse_mode=ParseMode.HTML)
                # Update Redis Locally (No commit to GitHub to avoid 2 commits)
                def inc_mod(d):
                    d["daily_count"] = d.get("daily_count", 0) + 1
                    d["last_build_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    return True
                await update_user_data(query.from_user.id, inc_mod, commit_msg=None)
            else:
                await query.edit_message_text("❌ <b>GitHub API Error.</b>", parse_mode=ParseMode.HTML)

    elif data.startswith("build_set:"):
        k = data.split(":")[1]
        p = context.user_data.get('pending_build')
        if not p: return
        
        opts = BUILD_OPTIONS.get(k)
        idx = (opts.index(p[k]) + 1) % len(opts)
        p[k] = opts[idx]
        
        try: await query.edit_message_reply_markup(get_build_menu_keyboard(p))
        except: pass
        await query.answer()
