import asyncio
import os
import html
import requests
import xml.etree.ElementTree as ET
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest
from datetime import datetime, timezone, timedelta
from utils import (
    get_quota_status, get_user_data, convert_to_raw_url,
    MAX_QUOTA_USER, ROLE_ADMIN, ROLE_OWNER, restricted_command
)
from github import Github

# Env Vars
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME") # e.g. "AxionOS/build_server"
# Unified Branch Config: Defaults to 'actions' if not set in ENV
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "actions")
WORKFLOW_FILENAME = 251648982 # Fixed ID for AxionOS Builder

# === CONSTANTS ===
BUILD_OPTIONS = {
    'RELEASETYPE': ['user', 'userdebug', 'eng'],
    'GMS_VARIANT': ['Core', 'Pico', 'Vanilla'],
    'INSTALLCLEAN': ['Yes', 'No'],
    'FULLCLEAN': ['No', 'Yes'],
    'FSGEN': ['Enable', 'Disable']
}

# === KEYBOARDS ===
def get_build_menu_keyboard(params):
    def btn(l, k): return InlineKeyboardButton(f"{l}: {params[k]}", callback_data=f"build_set:{k}")
    return InlineKeyboardMarkup([
        [btn("Type", "RELEASETYPE"), btn("GMS", "GMS_VARIANT")],
        [btn("Clean", "INSTALLCLEAN"), btn("Full Clean", "FULLCLEAN")],
        [btn("FSGen", "FSGEN")],
        [InlineKeyboardButton("✅ START", callback_data="build_action:start"), InlineKeyboardButton("❌ CANCEL", callback_data="build_action:cancel")]
    ])

# === HELPERS ===
def get_github_client(context):
    return context.bot_data.get("github_client")

def get_repo(context):
    g = get_github_client(context)
    if not g: return None
    try:
        return g.get_repo(GITHUB_REPO_NAME)
    except Exception as e:
        print(f"[GH ERROR] Failed to get repo: {e}")
        return None

# === HANDLERS ===

@restricted_command
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Cancels a workflow run.
    Usage: /cancel <RunID>
    """
    uid = update.effective_user.id
    repo = await asyncio.to_thread(get_repo, context)
    
    if not repo:
        await update.message.reply_text("⚠️ GitHub Disconnected.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/cancel <RunID>`", parse_mode="Markdown")
        return

    try:
        run_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Run ID must be a number.")
        return

    status_msg = await update.message.reply_text(f"⏳ Searching for Run {run_id}...")

    try:
        workflow_run = await asyncio.to_thread(repo.get_workflow_run, run_id)
        
        # --- AUTHORIZATION CHECK ---
        u_data = get_user_data(uid)
        u_role = u_data.get('role', 'user') if u_data else 'user'
        is_superuser = (u_role in [ROLE_ADMIN, ROLE_OWNER])
        
        # Parse Owner ID from Run Name 
        # Format set in YAML: "DEVICE (TYPE) | User: Name (123456789)"
        build_owner_id = None
        run_name = workflow_run.name or ""
        
        if "User:" in run_name:
            try:
                # Extract content inside the last parenthesis
                # Split by '(' -> take last part -> remove ')' -> strip
                id_part = run_name.split("(")[-1].replace(")", "").strip()
                build_owner_id = int(id_part)
            except:
                pass
        
        # Verification Logic
        if is_superuser:
            pass # Admin/Owner can cancel anything
        elif build_owner_id:
            if build_owner_id != uid:
                await status_msg.edit_text(f"⛔ **Access Denied**\nThis build belongs to User ID `{build_owner_id}`.", parse_mode="Markdown")
                return
        else:
            # If we can't identify owner from name (e.g. legacy build or manual trigger), restrict to Admin
            await status_msg.edit_text("⚠️ **Unknown Owner.** Only Admins can cancel this build.")
            return

        if workflow_run.status in ["completed", "cancelled", "failure", "success"]:
             await status_msg.edit_text(f"⚠️ Run {run_id} is already {workflow_run.status}.")
             return

        await asyncio.to_thread(workflow_run.cancel)
        await status_msg.edit_text(f"🛑 **Run {run_id} Cancelled.**", parse_mode="Markdown")

    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")

@restricted_command
async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Same as before
    uid = update.effective_user.id
    role, used, remaining = get_quota_status(uid)
    if not role:
        await update.message.reply_text("⛔ **Not registered.** Ask an admin to add you.", parse_mode="Markdown")
        return

    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    h, r = divmod((tomorrow - now).seconds, 3600)
    m, _ = divmod(r, 60)
    
    lim = "Unlimited" if role in [ROLE_ADMIN, ROLE_OWNER] else f"{MAX_QUOTA_USER}"
    
    msg = (
        f"📊 <b>Quota Status</b>\n"
        f"├ User: <code>{html.escape(update.effective_user.first_name)}</code>\n"
        f"├ Role: <code>{role.upper()}</code>\n"
        f"├ Usage: <code>{used}/{lim}</code>\n"
        f"└ Reset: <code>{h}h {m}m</code>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

def _sync_status_generation(repo):
    try:
        # Get active runs (Blocking calls)
        runs = list(repo.get_workflow_runs(status="in_progress"))
        queued = list(repo.get_workflow_runs(status="queued"))
        waiting = list(repo.get_workflow_runs(status="waiting"))
        pending = list(repo.get_workflow_runs(status="pending"))
        
        msg = f"<b>🔭 System Status</b>\n<pre>GitHub Actions</pre>\n\n"
        has_activity = False

        def parse_run_info(run):
            # Default fallback
            u_name = run.actor.login
            u_id = "Unknown"
            
            # Format: "DEVICE (TYPE) | User: Username (123456)"
            name = run.name or ""
            if "User: " in name:
                try:
                    # Ambil bagian setelah "User: " -> "Username (123456)"
                    parts = name.split("User: ")
                    if len(parts) > 1:
                        user_part = parts[1].strip()
                        if "(" in user_part and user_part.endswith(")"):
                            # Pisahkan nama dan ID
                            split_part = user_part.rsplit(" (", 1)
                            u_name = split_part[0]
                            u_id = split_part[1].replace(")", "")
                except: pass
            return html.escape(u_name), html.escape(u_id)

        # In Progress
        for run in runs:
            has_activity = True
            username, userid = parse_run_info(run)
            
            # Calculate Duration from JOB start time (Precision)
            duration_str = "Starting..."
            try:
                # Fetch jobs to get real execution start time
                jobs = run.jobs()
                start_dt = None
                
                # Find the active job
                for j in jobs:
                    if j.status == "in_progress":
                        start_dt = j.started_at
                        # If we find the specific 'build' job, prefer it
                        if j.name == "build": 
                            break
                
                if start_dt:
                    start_time = start_dt.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    diff = now - start_time
                    total_seconds = int(diff.total_seconds())
                    hours, remainder = divmod(total_seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    if hours > 0: duration_str = f"{hours}h {minutes}m"
                    else: duration_str = f"{minutes}m"
            except Exception: 
                pass

            msg += (
                f"🟢 <b>Status : Running Build</b>\n"
                f"├ By : <code>{username}</code>\n"
                f"├ UserID : <code>{userid}</code>\n"
                f"├ Running ID : <code>{run.id}</code>\n"
                f"├ Duration : {duration_str}\n"
                f"└ <a href='{run.html_url}'>🗒️ View Logs</a>\n\n"
            )
        
        # Queued / Waiting / Pending
        from itertools import chain
        
        # Combine all queue types
        all_queued = list(chain(queued, waiting, pending))
        
        # Sort by creation time ASCENDING (Oldest first -> First in Line)
        # Handle cases where created_at might be None just in case
        all_queued.sort(key=lambda x: x.created_at if x.created_at else datetime.now(timezone.utc))

        for run in all_queued:
            has_activity = True
            username, userid = parse_run_info(run)
            
            # Display actual status (Queued/Waiting/Pending)
            status_label = run.status.capitalize() if run.status else "Queued"

            msg += (
                f"🔵 <b>Status : {status_label}</b>\n"
                f"├ By : <code>{username}</code>\n"
                f"├ UserID : <code>{userid}</code>\n"
                f"└ Running ID : <code>{run.id}</code>\n\n"
            )
        
        if not has_activity:
            msg += "✅ <b>System Idle</b>\nReady to build."

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh Status", callback_data="build_status:refresh")]])
        return msg, kb

    except Exception as e:
        return f"❌ Error: {e}", None

async def generate_status_message(repo):
    # Run heavy API calls in a separate thread to avoid blocking the bot
    return await asyncio.to_thread(_sync_status_generation, repo)

@restricted_command
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repo = await asyncio.to_thread(get_repo, context)
    if not repo:
        await update.message.reply_text("⚠️ GitHub Disconnected.")
        return

    status_msg = await update.message.reply_text("🔍 Scanning workflows...")
    msg, kb = await generate_status_message(repo)
    await status_msg.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)

@restricted_command
async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    role, _, rem = get_quota_status(uid)
    
    if role is None:
        await update.message.reply_text("⛔ **Unauthorized.** Ask an admin to add you.", parse_mode="Markdown")
        return
    if role not in [ROLE_ADMIN, ROLE_OWNER] and rem <= 0:
        await update.message.reply_text("⛔ **Quota Exceeded.** Please wait for reset.", parse_mode="Markdown")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ **Usage:** `/build <device> <manifest_url>`\nManifest is now required.", parse_mode="Markdown")
        return

    dev = context.args[0]
    url = convert_to_raw_url(context.args[1])
    
    if not url.startswith("http"):
         await update.message.reply_text("❌ **Invalid URL.** Must start with http/https.", parse_mode="Markdown")
         return

    status_msg = await update.message.reply_text("🔎 Validating Manifest URL...")
    
    try:
        # Download content (Timeout 10s to be safe)
        resp = await asyncio.to_thread(requests.get, url, allow_redirects=True, timeout=10)
        
        if resp.status_code != 200:
            await status_msg.edit_text(f"❌ **URL Error.** Server returned status: `{resp.status_code}`", parse_mode="Markdown")
            return
            
        # Parse XML
        try:
            root = ET.fromstring(resp.content)
            if root.tag != "manifest":
                await status_msg.edit_text("❌ **Invalid Manifest.** Root tag must be `<manifest>`.", parse_mode="Markdown")
                return

            # --- SECURITY VALIDATION ---
            # 1. Check for Forbidden Remove-Projects
            for rm in root.findall('remove-project'):
                rm_path = rm.get('path', '')
                rm_name = rm.get('name', '')
                
                if "vendor/axion-priv/keys" in rm_path:
                    await status_msg.edit_text("⛔ **Security Violation.**\nRemoving `vendor/axion-priv/keys` is forbidden.", parse_mode="Markdown")
                    return
                
                if "AxionOS/vendor_axion-priv_keys" in rm_name:
                    await status_msg.edit_text("⛔ **Security Violation.**\nRemoving keys repo by name is forbidden.", parse_mode="Markdown")
                    return

            # 2. Check for Forbidden Projects (Overwrites)
            for proj in root.findall('project'):
                p_path = proj.get('path', '')
                
                # Check for exact matches or sub-paths if necessary. 
                # User requested strict blocking for these paths.
                if p_path in ["vendor/axion-priv/keys", "vendor/axion-priv"]:
                    await status_msg.edit_text(f"⛔ **Security Violation.**\nOverwriting `{p_path}` is forbidden.", parse_mode="Markdown")
                    return
            # ---------------------------

        except ET.ParseError as e:
            await status_msg.edit_text(f"❌ **XML Syntax Error.**\n`{str(e)}`", parse_mode="Markdown")
            return
            
    except Exception as e:
        await status_msg.edit_text(f"❌ **Connection Failed.**\nError: `{str(e)}`", parse_mode="Markdown")
        return

    # Cleanup status msg
    await status_msg.delete()

    params = {
        'DEVICE': dev, 'RELEASETYPE': 'user', 'GMS_VARIANT': 'Core',
        'INSTALLCLEAN': 'Yes', 'FULLCLEAN': 'No', 'FSGEN': 'Enable',
        'LOCAL_MANIFEST_URL': url,
        'BUILD_USER': update.effective_user.username or update.effective_user.first_name,
        'BUILD_USER_ID': str(uid)
    }
    context.user_data['pending_build'] = params
    
    lim_str = "Unlimited" if role in [ROLE_ADMIN, ROLE_OWNER] else f"{rem} left"
    msg = f"<b>🛠 Build Config</b>\n👤 {params['BUILD_USER']} ({lim_str})\n📱 {dev}\n\n<i>Adjust settings & Start.</i>"
    await update.message.reply_text(msg, reply_markup=get_build_menu_keyboard(params), parse_mode=ParseMode.HTML)

async def handle_github_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_str = query.data
    
    if data_str == "build_status:refresh":
        repo = await asyncio.to_thread(get_repo, context)
        if repo:
            try:
                msg, kb = await generate_status_message(repo)
                await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
                await query.answer("Refreshed!")
            except BadRequest as e:
                if "message is not modified" in str(e).lower():
                    await query.answer("✅ Status is up to date!")
                else:
                    print(f"[BOT ERROR] Refresh Bad Request: {e}")
                    await query.answer("Refresh Error")
            except Exception as e:
                print(f"[BOT ERROR] Refresh Failed: {e}")
                await query.answer("Refresh failed")
        return

    if data_str.startswith("build_action:"):
        act = data_str.split(":")[1]
        if act == "cancel":
            await query.edit_message_text("❌ <b>Cancelled by user.</b>", parse_mode=ParseMode.HTML)
            if 'pending_build' in context.user_data: del context.user_data['pending_build']
        elif act == "start":
            role, _, rem = get_quota_status(query.from_user.id)
            if role not in [ROLE_ADMIN, ROLE_OWNER] and rem <= 0:
                await query.answer("⛔ Quota exceeded!", show_alert=True)
                return
            
            p = context.user_data.get('pending_build')
            if not p:
                await query.edit_message_text("⚠️ <b>Session Expired.</b>", parse_mode=ParseMode.HTML)
                return
            
            repo = await asyncio.to_thread(get_repo, context)
            if not repo:
                await query.answer("⚠️ GitHub Unreachable", show_alert=True)
                return

            print(f"[DEBUG] Repo: {repo.full_name}, Workflow: {WORKFLOW_FILENAME}")
            try:
                # Trigger Workflow
                wf = await asyncio.to_thread(repo.get_workflow, WORKFLOW_FILENAME)
                success = await asyncio.to_thread(wf.create_dispatch, ref=GITHUB_BRANCH, inputs=p)

                if success:
                    try:
                        msg = (
                            f"✅ <b>Workflow Dispatched!</b>\n"
                            f"Device: <code>{p['DEVICE']}</code>\n"
                            f"Branch: <code>{GITHUB_BRANCH}</code>\n"
                            f"Check status shortly."
                        )
                        await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
                    except BadRequest as e:
                        # Ignore "Message is not modified" (happens on double clicks or network lag)
                        if "message is not modified" not in str(e).lower():
                            print(f"[BOT UI ERROR] {e}")
                else:
                    await query.edit_message_text("❌ Dispatch returned False.")
            except Exception as e:
                await query.edit_message_text(f"❌ Failed to queue: {e}")

    elif data_str.startswith("build_set:"):
        k = data_str.split(":")[1]
        p = context.user_data.get('pending_build')
        if not p: return
        
        if k == 'FULLCLEAN':
            role, _, _ = get_quota_status(query.from_user.id)
            if role not in [ROLE_ADMIN, ROLE_OWNER]:
                await query.answer("⛔ Full Clean is restricted!", show_alert=True)
                return

        opts = BUILD_OPTIONS.get(k)
        if opts:
            try: p[k] = opts[(opts.index(p[k])+1)%len(opts)]
            except: p[k] = opts[0]
            context.user_data['pending_build'] = p
            try: await query.edit_message_reply_markup(get_build_menu_keyboard(p))
            except: pass
        await query.answer()