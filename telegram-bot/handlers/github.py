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
    get_github_headers, get_redis, RK_CONFIG
)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "actions")
WORKFLOW_ID = "axion_build.yml"

BUILD_OPTIONS = {
    'RELEASETYPE': ['user', 'userdebug', 'eng'],
    'GMS_VARIANT': ['GMS', 'Core', 'Vanilla'],
    'FULLCLEAN': ['No', 'Yes']
}

def get_build_menu_keyboard(params):
    def btn(l, k): return InlineKeyboardButton(f"{l}: {params[k]}", callback_data=f"build_set:{k}")
    return InlineKeyboardMarkup([
        [btn("Type", "RELEASETYPE"), btn("Variant", "GMS_VARIANT")],
        [btn("Full Clean", "FULLCLEAN")],
        [InlineKeyboardButton("✅ START", callback_data="build_action:start"), InlineKeyboardButton("❌ CANCEL", callback_data="build_action:cancel")]
    ])

async def trigger_workflow(inputs):
    """Triggers GitHub Actions workflow"""
    url = f"https://api.github.com/repos/{GITHUB_REPO_NAME}/actions/workflows/{WORKFLOW_ID}/dispatches"
    payload = {"ref": GITHUB_BRANCH, "inputs": inputs}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=get_github_headers(), json=payload, timeout=20)
            return resp.status_code == 204
        except Exception as e:
            print(f"[GH ERROR] Trigger failed: {e}")
            return False

async def get_workflow_runs(status=None):
    """Fetches recent workflow runs"""
    url = f"https://api.github.com/repos/{GITHUB_REPO_NAME}/actions/runs"
    params = {"branch": GITHUB_BRANCH, "per_page": 15}
    if status: params["status"] = status
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=get_github_headers(), params=params, timeout=15)
            if resp.status_code == 200: return resp.json().get("workflow_runs", [])
        except Exception as e: print(f"[GH ERROR] Fetch runs failed: {e}")
    return []

async def cancel_workflow_run(run_id):
    """Cancels a workflow run"""
    url = f"https://api.github.com/repos/{GITHUB_REPO_NAME}/actions/runs/{run_id}/cancel"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=get_github_headers(), timeout=15)
            return resp.status_code == 202
        except Exception as e:
            print(f"[GH ERROR] Cancel failed: {e}")
            return False

@restricted_command
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows real-time build progress from Redis"""
    r = await get_redis()
    chat_id = update.effective_chat.id
    
    last_mid = context.chat_data.get("last_status_mid")
    if last_mid:
        try: await context.bot.delete_message(chat_id, last_mid)
        except: pass

    device = context.args[0] if context.args else await r.get("active_build_device")
    
    if not device:
        runs = await get_workflow_runs(status="in_progress")
        if runs:
            title = runs[0].get("display_title", "") or runs[0].get("name", "")
            if "(" in title: device = title.split("(")[0].strip()

    if not device:
        msg = await update.message.reply_text("✅ **No active builds.**\nUse `/queue` for system status.", parse_mode="Markdown")
        context.chat_data["last_status_mid"] = msg.message_id
        return

    raw_data = await r.get(f"build_status:{device}")
    if not raw_data:
        msg = await update.message.reply_text(f"❌ No live data for `{device}`.", parse_mode="Markdown")
        context.chat_data["last_status_mid"] = msg.message_id
        return

    data = json.loads(raw_data)
    progress_display = data.get("progress", "Starting...")
    if "%" in progress_display:
        try:
            pct = int(progress_display.split("%")[0].strip())
            bar = "▰" * (pct // 10) + "▱" * (10 - (pct // 10))
            progress_display = f"<code>[{bar}]</code> {progress_display}"
        except: pass
    
    diff = int(time.time()) - data.get("updated_at", 0)
    msg_text = (
        f"<b>✨ ACTIVE BUILD STATUS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📱 Device</b>   : <code>{device}</code>\n"
        f"<b>🚦 Status</b>   : <code>{data.get('status', 'Unknown')}</code>\n"
        f"<b>📊 Progress</b> : {progress_display}\n"
        f"<b>🧬 Variant</b>  : <code>{data.get('gms', 'N/A')}</code>\n"
        f"<b>👤 User</b>     : @{html.escape(data.get('user', 'Unknown'))}\n"
        f"<b>🆔 Run ID</b>   : <code>{data.get('run_id', 'N/A')}</code>\n"
        f"<b>⏱️ Updated</b>  : <code>{diff}s ago</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n🔗 <a href='{data.get('url', '#')}'><b>VIEW LIVE LOGS</b></a>"
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
    msg = "<b> Telescope SYSTEM STATUS</b>\n<code>GitHub Queue</code>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    active_found = False

    def parse_run_info(run):
        u_name, dev_name = "Unknown", "Unknown"
        name = run.get("display_title", "") or run.get("name", "")
        if "User: " in name:
            try:
                dev_name = name.split("(")[0].strip()
                u_name = name.split("User: ")[1].rsplit(" (", 1)[0]
            except: pass
        return html.escape(u_name), html.escape(dev_name)

    for run in runs:
        if run['status'] not in ["in_progress", "queued", "waiting", "pending"]: continue
        active_found = True
        username, device = parse_run_info(run)
        icon = "🟢" if run['status'] == "in_progress" else "🔵"
        label = "RUNNING" if run['status'] == "in_progress" else "QUEUED"
        
        time_str = ""
        if run['status'] == "in_progress":
            try:
                start_raw = run.get("run_started_at") or run.get("created_at")
                if start_raw:
                    start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    mins = int((datetime.now(timezone.utc) - start_dt).total_seconds() / 60)
                    time_str = f"\n├ <b>Time</b> : <code>{mins // 60}h {mins % 60}m</code>" if mins >= 60 else f"\n├ <b>Time</b> : <code>{mins}m</code>"
            except: pass

        msg += (
            f"{icon} <b>{label} BUILD</b>\n├ <b>By</b> : <code>{username}</code>\n"
            f"├ <b>Device</b> : <code>{device}</code>\n"
            f"├ <b>RunID</b> : <code>{run['id']}</code>{time_str}\n"
            f"└ 🔗 <a href='{run['html_url']}'><b>VIEW LOGS</b></a>\n\n"
        )

    if not active_found: msg += "✅ <b>SYSTEM IDLE</b>\nReady to build."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="build_status:refresh")]])
    return msg, kb

@restricted_command
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/cancel <RunID>`")
        return
    run_id = context.args[0]
    status_msg = await update.message.reply_text(f"⏳ Cancelling Run {run_id}...")
    if await cancel_workflow_run(run_id):
        await status_msg.edit_text(f"🛑 **Run {run_id} Cancelled.**", parse_mode="Markdown")
    else: await status_msg.edit_text("❌ Failed to cancel.")

@restricted_command
async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role, used, remaining = await get_quota_status(update.effective_user.id)
    if not role:
        await update.message.reply_text("⛔ Not registered.")
        return
    h, m = ((datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)) - datetime.now(timezone.utc)).seconds // 3600, ((datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)) - datetime.now(timezone.utc)).seconds // 60 % 60
    limit_str = "Unlimited" if role in [ROLE_ADMIN, ROLE_OWNER] else str(used + remaining)
    msg = (
        f"📊 <b>Quota Status</b>\n├ User: <code>{html.escape(update.effective_user.first_name)}</code>\n"
        f"├ Role: <code>{role.upper()}</code>\n├ Usage: <code>{used}/{limit_str}</code>\n└ Reset: <code>{h}h {m}m</code>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

@restricted_command
async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role, _, rem = await get_quota_status(update.effective_user.id)
    if role is None:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    if role not in [ROLE_ADMIN, ROLE_OWNER] and rem <= 0:
        await update.message.reply_text("⛔ Quota Exceeded.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/build <device> [manifest_url]`")
        return

    dev = context.args[0]
    url = convert_to_raw_url(context.args[1]) if len(context.args) >= 2 else f"https://github.com/AxionAOSP/device_manifests/raw/main/{dev}.xml"
    status_msg = await update.message.reply_text(f"🔎 Validating Manifest...")
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=10, follow_redirects=True)
            if resp.status_code != 200:
                await status_msg.edit_text("❌ **Manifest Not Found.**", parse_mode="Markdown")
                return
            root = ET.fromstring(resp.content)
            if root.tag != "manifest":
                await status_msg.edit_text("❌ **Invalid Manifest XML.**", parse_mode="Markdown")
                return
        except Exception as e:
            await status_msg.edit_text(f"❌ **Validation Failed:** `{e}`", parse_mode="Markdown")
            return

    await status_msg.delete()
    params = {
        'DEVICE': dev, 'RELEASETYPE': 'userdebug', 'GMS_VARIANT': 'GMS',
        'FULLCLEAN': 'No', 'LOCAL_MANIFEST_URL': url,
        'BUILD_USER': update.effective_user.username or update.effective_user.first_name,
        'BUILD_USER_ID': str(update.effective_user.id),
        'CHAT_ID': str(update.effective_chat.id),
        'TOPIC_ID': str(update.effective_message.message_thread_id or "")
    }
    context.user_data['pending_build'] = params
    msg = (
        f"<b>🚀 AXIONOS BUILD</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📱 Device</b> : <code>{dev}</code>\n"
        f"<b>👤 User</b>   : @{html.escape(params['BUILD_USER'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n<i>Adjust config:</i>"
    )
    await update.message.reply_text(msg, reply_markup=get_build_menu_keyboard(params), parse_mode=ParseMode.HTML)

async def handle_github_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "build_status:refresh":
        msg, kb = await generate_queue_message()
        try: await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
        except: pass
        await query.answer("Refreshed!")
        return

    if query.data.startswith("build_action:"):
        act = query.data.split(":")[1]
        if act == "cancel":
            await query.edit_message_text("❌ <b>Build Cancelled.</b>", parse_mode=ParseMode.HTML)
            context.user_data.pop('pending_build', None)
        elif act == "start":
            p = context.user_data.get('pending_build')
            if not p:
                await query.answer("Session Expired", show_alert=True)
                return
            r = await get_redis()
            main_chan = await r.hget(RK_CONFIG, "main_output_channel")
            kb = None
            if main_chan:
                p["CHAT_ID"], p["TOPIC_ID"] = main_chan, "none"
                if str(main_chan).startswith("-100"):
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📣 VIEW CHANNEL", url=f"https://t.me/c/{str(main_chan)[4:]}/1")]])
            
            await query.edit_message_text("⏳ <b>Dispatching...</b>", parse_mode=ParseMode.HTML)
            if await trigger_workflow(p):
                await query.edit_message_text(f"✅ <b>Build Started!</b>\nDevice: <code>{p['DEVICE']}</code>", parse_mode=ParseMode.HTML, reply_markup=kb)
                await update_user_data(query.from_user.id, lambda d: d.update({"daily_count": d.get("daily_count", 0)+1, "last_build_date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}) or True)
            else: await query.edit_message_text("❌ <b>API Error.</b>", parse_mode=ParseMode.HTML)
            context.user_data.pop('pending_build', None)

    elif query.data.startswith("build_set:"):
        k = query.data.split(":")[1]
        p = context.user_data.get('pending_build')
        if p:
            opts = BUILD_OPTIONS[k]
            p[k] = opts[(opts.index(p[k]) + 1) % len(opts)]
            try: await query.edit_message_reply_markup(get_build_menu_keyboard(p))
            except: pass
        await query.answer()
