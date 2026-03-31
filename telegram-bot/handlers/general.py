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
    """Shows the last 5 builds from history."""
    import os
    history_file = os.path.join(os.path.expanduser("~"), "build_history.json")
    
    if not os.path.exists(history_file):
        await update.message.reply_text("📂 **History is empty.**", parse_mode="Markdown")
        return

    try:
        with open(history_file, 'r') as f:
            data = json.load(f)
        
        if not data:
            await update.message.reply_text("📂 **History is empty.**", parse_mode="Markdown")
            return

        msg = "<b>📜 RECENT BUILD HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        # Sort by timestamp descending to ensure newest are first
        data.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        # Show top 5
        for build in data[:5]:
            dt = datetime.fromtimestamp(build['timestamp']).strftime("%d/%m %H:%M")
            status_icon = "✅" if build['status'] == "SUCCESS" else "❌" if build['status'] == "FAILURE" else "🛑"
            
            msg += (
                f"{status_icon} <b>{build['device']}</b> ({build.get('user', 'Unknown')})\n"
                f"├ <b>Time</b>   : <code>{dt}</code>\n"
                f"└ <b>Status</b> : <code>{build['status']}</code>\n\n"
            )
        
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Use /fullhistory to get the complete log file.</i>"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Error reading history: {e}")

@restricted_command
async def full_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the full build_history.json file."""
    import os
    history_file = os.path.join(os.path.expanduser("~"), "build_history.json")
    if os.path.exists(history_file):
        with open(history_file, 'rb') as f:
            await update.message.reply_document(f, caption="📄 **Full Build History**", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No history file found.")

@restricted_command
async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows server health statistics."""
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
            f"<b>🖥️ SERVER HEALTH REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>💾 Disk (/)</b> : <code>{disk}</code>\n"
            f"<b>🧠 RAM      </b> : <code>{ram}</code>\n"
            f"<b>⚙️ Load     </b> : <code>{load}</code>\n"
            f"<b>🤖 Runner   </b> : <code>{runner_alive}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <i>System is ready for builds.</i>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to fetch health: {e}")

@restricted_command
async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = await get_redis()
    raw_users = await r.hgetall(RK_USERS)
    
    if not raw_users:
        await update.message.reply_text("📂 Database is empty.")
        return

    owners, admins, regular_users = [], [], []
    for uid, udata_raw in raw_users.items():
        udata = json.loads(udata_raw)
        role = udata.get("role", ROLE_USER)
        entry = (udata.get("username", "Unknown"), uid)
        
        if role == ROLE_OWNER: owners.append(entry)
        elif role == ROLE_ADMIN: admins.append(entry)
        else: regular_users.append(entry)

    msg = ""
    blocks = []
    if owners: blocks.append(('Owner', owners, '👑'))
    if admins: blocks.append(('Admin', admins, '🛡'))
    if regular_users: blocks.append(('User', regular_users, '👤'))

    for title, items, icon in blocks:
        msg += f"{icon} **{title}s**\n"
        items.sort(key=lambda x: x[0].lower())
        for j, (name, uid) in enumerate(items):
            sub_branch = "└" if j == len(items) - 1 else "├"
            msg += f"{sub_branch} `{name}` (`{uid}`)\n"
        msg += "\n"

    await update.message.reply_text(msg.strip() or "No users found.", parse_mode="Markdown")

@restricted_command
async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 **AxionOS Builder Guide**\n\n"
        "🟢 **Starting a Build**\n"
        "├ `/build <device> <manifest>`\n"
        "├ `device`: Codename (e.g. `citrus`)\n"
        "└ `manifest`: XML URL (Required)\n\n"
        "📊 **Monitoring Build**\n"
        "├ `/status`: Live info in Telegram\n"
        "├ `/queue`: Check Action runs\n"
        "└ **Terminal (Byobu/Tmux):**\n"
        "  `TMUX= tmux attach -t axion_build`\n\n"
        "⚙️ **Build Options**\n"
        "├ **GMS Variant**\n"
        "│ ├ `Core`: Essential GApps (Default)\n"
        "│ ├ `Pico`: Minimal GApps\n"
        "│ └ `Vanilla`: No GApps\n"
        "│\n"
        "├ **Clean Options**\n"
        "│ └ `Full Clean`: `make clean` (Wipe Out)\n"
        "└ **Note:** Build status is live in Telegram.\n\n"
        "📄 **Local Manifest**\n"
        "├ Use for extra repos (Kernel/Vendor)\n"
        "└ [Reference XML Template](https://raw.githubusercontent.com/Arata-Labs/local_manifest/refs/heads/axn-16/local_manifests.xml)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

@restricted_command
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Welcome to AxionOS Build Bot!**\n\n"
        "I can help you manage ROM builds via GitHub Actions.\n"
        "Type `/help` to see available commands.",
        parse_mode="Markdown"
    )

@restricted_command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    # Load Role
    user_data = await get_user_data(uid)
    role = user_data.get("role", ROLE_USER) if user_data else ROLE_USER
    
    is_owner = (uid == OWNER_ID) or (role == ROLE_OWNER)
    is_admin = is_owner or (role == ROLE_ADMIN) or (uid in ADMIN_USER_IDS)

    help_text = (
        "🤖 **AxionOS Bot Help**\n\n"
        "**👤 User Commands:**\n"
        "`/guide` - View detailed build options & guide.\n"
        "`/build <device> <manifest_url>` - Start a new build.\n"
        "`/status [device]` - Show real-time ROM build progress.\n"
        "`/queue` - View GitHub Actions workflow queue.\n"
        "`/history` - Show last 5 build attempts.\n"
        "`/health` - Check build server health.\n"
        "`/cancel <RunID>` - Cancel a running build.\n"
        "`/quota` - Check your daily build quota.\n"
        "`/listuser` - List all registered users.\n\n"
    )

    if is_admin:
        help_text += (
            "**🛡️ Admin Commands:**\n"
            "`/approvechat` - Approve this group for bot usage.\n"
            "`/adduser <Username> [role]` - Add/Update a user.\n"
            "`/removeuser <ID>` - Remove a user from DB.\n"
            "`/setrole <Role> <User> [Limit]` - Change permissions.\n"
            "_(Admins and Owner have unlimited quota)_\n\n"
        )
    
    if is_owner:
        help_text += (
            "**👑 Owner Commands:**\n"
            "`/sync` - Force GitHub -> Redis sync.\n"
            "`/addquota <User> <Limit>` - Set custom daily limit.\n"
        )
    elif not is_admin:
        help_text += "_Request admin access for more features._"

    await update.message.reply_text(help_text, parse_mode="Markdown")
