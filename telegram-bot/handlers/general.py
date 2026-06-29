from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from datetime import datetime
from utils import (
    OWNER_ID, ADMIN_USER_IDS, ROLE_ADMIN, ROLE_USER, ROLE_OWNER, 
    restricted_command, get_user_data, get_redis, RK_USERS
)
import json

@restricted_command
async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows last 5 builds"""
    import os
    history_file = os.path.join(os.path.expanduser("~"), "build_history.json")
    if not os.path.exists(history_file):
        await update.message.reply_text("📂 History is empty.")
        return

    try:
        with open(history_file, 'r') as f: data = json.load(f)
        if not data:
            await update.message.reply_text("📂 History is empty.")
            return

        msg = "<b>📜 RECENT HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        data.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        for build in data[:5]:
            dt = datetime.fromtimestamp(build['timestamp']).strftime("%d/%m %H:%M")
            status_icon = "✅" if build['status'] == "SUCCESS" else "❌" if build['status'] == "FAILURE" else "🛑"
            msg += (
                f"{status_icon} <b>{build['device']}</b> ({build.get('user', 'Unknown')})\n"
                f"├ <b>Time</b>   : <code>{dt}</code>\n"
                f"└ <b>Status</b> : <code>{build['status']}</code>\n\n"
            )
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Use /fullhistory for full logs.</i>"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

@restricted_command
async def full_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends full history file"""
    import os
    history_file = os.path.join(os.path.expanduser("~"), "build_history.json")
    if os.path.exists(history_file):
        with open(history_file, 'rb') as f:
            await update.message.reply_document(f, caption="📄 **Full History**", parse_mode="Markdown")
    else: await update.message.reply_text("❌ No file.")

@restricted_command
async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Server health stats"""
    import subprocess
    try:
        disk = subprocess.check_output("df -h / | tail -1 | awk '{print $3 \"/\" $2 \" (\" $5 \")\"}'", shell=True).decode().strip()
        ram = subprocess.check_output("free -h | grep Mem | awk '{print $3 \"/\" $2}'", shell=True).decode().strip()
        load = subprocess.check_output("uptime | awk -F'load average:' '{ print $2 }'", shell=True).decode().strip()
        runner_alive = "❌ Dead"
        try:
            subprocess.check_call(["pgrep", "-f", "Runner.Listener"], stdout=subprocess.DEVNULL)
            runner_alive = "✅ Alive"
        except: pass

        msg = (
            f"<b>🖥️ SERVER HEALTH</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>💾 Disk (/)</b> : <code>{disk}</code>\n"
            f"<b>🧠 RAM      </b> : <code>{ram}</code>\n"
            f"<b>⚙️ Load     </b> : <code>{load}</code>\n"
            f"<b>🤖 Runner   </b> : <code>{runner_alive}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n✨ <i>Ready.</i>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

@restricted_command
async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists maintainers"""
    r = await get_redis()
    raw_users = await r.hgetall(RK_USERS)
    if not raw_users:
        await update.message.reply_text("📂 Database empty.")
        return

    owners, admins, regular_users = [], [], []
    for uid, udata_raw in raw_users.items():
        udata = json.loads(udata_raw)
        role, entry = udata.get("role", ROLE_USER), (udata.get("username", "Unknown"), uid)
        if role == ROLE_OWNER: owners.append(entry)
        elif role == ROLE_ADMIN: admins.append(entry)
        else: regular_users.append(entry)

    msg, blocks = "", []
    if owners: blocks.append(('Owner', owners, '👑'))
    if admins: blocks.append(('Admin', admins, '🛡'))
    if regular_users: blocks.append(('User', regular_users, '👤'))

    for title, items, icon in blocks:
        msg += f"{icon} **{title}s**\n"
        items.sort(key=lambda x: x[0].lower())
        for j, (name, uid) in enumerate(items):
            msg += f"{'└' if j == len(items)-1 else '├'} `{name}` (`{uid}`)\n"
        msg += "\n"
    await update.message.reply_text(msg.strip() or "No users.", parse_mode="Markdown")

@restricted_command
async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 **AxionOS Guide**\n\n"
        "🟢 **Starting**\n"
        "├ `/build <device> <manifest>`\n"
        "├ **Groups**: Anyone can build!\n"
        "└ **PM**: Restricted to Admins.\n\n"
        "📊 **Monitoring**\n"
        "├ `/status`: Live info\n"
        "├ `/queue`: GitHub runs\n"
        "└ `/cancel <ID>`: Stop your build.\n\n"
        "⚙️ **Options**\n"
        "├ **GMS Variant**: `GMS`, `PICO`, `CORE`, `VANILLA`\n"
        "├ **Clean**: `Full Clean` (`make clean` before compile)\n"
        "└ **Release Build**: Toggles high-speed Cloudflare R2 CDN Mirroring\n\n"
        "📄 **Local Manifest**\n"
        "└ [Reference Template](https://github.com/AxionAOSP/device_manifests/blob/main/begonia.xml)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

@restricted_command
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 **Welcome to AxionOS Build Bot!**\nUse `/help` for commands.", parse_mode="Markdown")

@restricted_command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data = await get_user_data(uid)
    role = user_data.get("role", ROLE_USER) if user_data else ROLE_USER
    is_owner = (uid == OWNER_ID) or (role == ROLE_OWNER)
    is_admin = is_owner or (role == ROLE_ADMIN) or (uid in ADMIN_USER_IDS)

    help_text = (
        "🤖 **AxionOS Bot Help**\n\n"
        "**👤 User Commands:**\n"
        "`/build <device> [url]` - Start build.\n"
        "`/status [device]` - Live progress.\n"
        "`/queue` - GitHub queue.\n"
        "`/cancel <ID>` - Cancel your build.\n"
        "`/history` - Last 5 builds.\n"
        "`/health` - Server health.\n"
        "`/listuser` - Admin list.\n"
        "`/guide` - Detailed guide.\n\n"
    )

    if is_admin:
        help_text += (
            "**🛡️ Admin Commands:**\n"
            "`/approvechat [ID]` | `/disapprovechat`\n"
            "`/listchats` | `/setchannel <ID>`\n"
            "`/removeuser` | `/setrole`\n"
            "`/save` | `/usepd [on|off]`\n"
            "`/cancel <RunID>` (Any)\n\n"
        )
    
    if is_owner:
        help_text += (
            "**👑 Owner Commands:**\n"
            "`/announce <msg>` | `/sync`\n"
        )
    elif not is_admin: help_text += "💡 _Request admin access for more features._"
    await update.message.reply_text(help_text, parse_mode="Markdown")
