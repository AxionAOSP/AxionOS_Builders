from telegram import Update
from telegram.ext import ContextTypes
from utils import ADMIN_USER_IDS, load_db, ROLE_ADMIN, ROLE_USER, ROLE_OWNER, restricted_command

@restricted_command
async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    users = db.get("users", {})
    
    if not users:
        await update.message.reply_text("📂 Database is empty.")
        return

    # Grouping
    owners, admins, regular_users = [], [], []
    for uid, data in users.items():
        role = data.get("role", ROLE_USER)
        entry = (data.get("username", "Unknown"), uid)
        
        if role == ROLE_OWNER: owners.append(entry)
        elif role == ROLE_ADMIN: admins.append(entry)
        else: regular_users.append(entry)

    msg = ""

    blocks = []
    if owners: blocks.append(('Owner', owners, '👑'))
    if admins: blocks.append(('Admin', admins, '🛡'))
    if regular_users: blocks.append(('User', regular_users, '👤'))

    for title, items, icon in blocks:
        # Title is the Root of this block's tree
        msg += f"{icon} **{title}s**\n"
        
        items.sort(key=lambda x: x[0].lower())
        for j, (name, uid) in enumerate(items):
            is_last_item = (j == len(items) - 1)
            sub_branch = "└" if is_last_item else "├"
            
            msg += f"{sub_branch} `{name}` (`{uid}`)\n"
        
        # Add spacing between blocks
        msg += "\n"

    if not msg:
        msg = "No users found."

    await update.message.reply_text(msg.strip(), parse_mode="Markdown")

@restricted_command
async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 **AxionOS Builder Guide**\n\n"
        
        "🟢 **Starting a Build**\n"
        "├ `/build <device> <manifest>`\n"
        "├ `device`: Codename (e.g. `citrus`)\n"
        "└ `manifest`: XML URL (Required)\n\n"
        
        "⚙️ **Build Options**\n"
        "├ **Release Type**\n"
        "│ ├ `user`: Stable/Secure\n"
        "│ ├ `userdebug`: Root/Debug (Default)\n"
        "│ └ `eng`: Engineering/Unsafe\n"
        "│\n"
        "├ **GMS Variant**\n"
        "│ ├ `Tree default`: Device default\n"
        "│ ├ `Core/Basic`: Minimal GApps\n"
        "│ └ `Full/Vanilla`: Full suite/None\n"
        "│\n"
        "├ **Clean Options**\n"
        "│ ├ `Clean`: `make installclean`\n"
        "│ └ `Full Clean`: `make clean`\n"
        "│\n"
        "└ **Others**\n"
        "  ├ `FSGen`: Auto-gen filesystem\n"
        "  └ `Release`: Generate OTA JSON\n\n"
        
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
    user = update.effective_user
    uid = user.id
    
    # Load DB & Check Role
    db = load_db()
    user_data = db.get("users", {}).get(str(uid), {})
    role = user_data.get("role", ROLE_USER)
    
    is_owner = (role == ROLE_OWNER)
    is_db_admin = (role == ROLE_ADMIN)
    is_env_admin = uid in ADMIN_USER_IDS
    
    is_admin = is_env_admin or is_db_admin or is_owner

    help_text = (
        "🤖 **AxionOS Bot Help**\n\n"
        "**👤 User Commands:**\n"
        "`/guide` - View detailed build options & guide.\n"
        "`/build <device> <manifest_url>` - Start a new build (Manifest required).\n"
        "`/cancel <RunID>` - Cancel a running build (ID from /status).\n"
        "`/quota` - Check your daily build quota.\n"
        "`/status` - View current build queue.\n"
        "`/listuser` - List all registered users.\n\n"
    )

    if is_admin:
        help_text += (
            "**🛡️ Admin Commands:**\n"
            "`/adduser <Username> [role]` - Add/Update a user (Try @username first).\n"
            "`/removeuser <ID>` - Remove a user from DB.\n"
            "`/setrole <Username/ID> <role>` - Change user role.\n"
            "_(Admins and Owner have unlimited quota and can cancel any build)_\n\n"
        )
    
    if is_owner:
        help_text += (
            "**👑 Owner Commands:**\n"
            "`/setrole <ID> <role>` - Promote/Demote users (admin/user).\n"
            "`/addquota <User> <Amt>` - Add extra quota (Owner Only).\n"
        )
    elif not is_admin:
        help_text += "_Request admin access for more features._"

    await update.message.reply_text(help_text, parse_mode="Markdown")
