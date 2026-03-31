# AxionOS Build System 🚀

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg?style=for-the-badge&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20Linux-orange.svg?style=for-the-badge&logo=linux&logoColor=white)

A high-performance CI/CD pipeline for building AxionOS and other Android ROMs. This system bridges GitHub Actions with a Telegram bot interface, allowing for remote-controlled build management and real-time monitoring.

---

## 📂 Repository Structure

### 🏗️ `builder/`
Contains the core build logic executed on the self-hosted runner.
*   **`build.sh` / `sync.sh`**: Core AOSP sync and compilation scripts.
*   **`tmux_runner.sh`**: Orchestrates the build within a persistent `tmux` session and extracts progress logs.
*   **`reporter.py`**: Background monitoring tool that updates Telegram with progress bars and handles artifact uploads.
*   **`quota_manager.py`**: Enforces daily build limits and updates user data via the GitHub API.
*   **`utils/telegram.py`**: Shared utility for Telegram API interactions.

### 🤖 `telegram-bot/`
The control center for the entire system.
*   **`main.py`**: Entry point for the Telegram bot.
*   **`handlers/`**: Modularized command logic (admin, github, general).
*   **`check_repo.py` / `check_workflows.py`**: Health check utilities for the runner and GitHub Actions.
*   **`utils.py`**: Helper functions for bot operations.

### ⚙️ `.github/workflows/`
*   **`axion_build.yml`**: The main workflow definition that triggers the builder scripts on the self-hosted runner.

---

## 🚀 Setup Guide

### 1. Build Server Prep (Ubuntu 22.04+)
Ensure your server is ready for Android compilation:
```bash
# Install Build Essentials
sudo apt update && sudo apt install -y git-core gnupg flex bison gperf build-essential zip curl zlib1g-dev gcc-multilib g++-multilib libc6-dev-i386 lib32ncurses5-dev x11proto-core-dev libx11-dev lib32z1-dev libgl1-mesa-dev libxml2-utils xsltproc unzip fontconfig redis-server python3-pip tmux

# Install Repo Tool
mkdir -p ~/bin && curl https://storage.googleapis.com/git-repo-downloads/repo > ~/bin/repo && chmod a+x ~/bin/repo
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

### 2. Deployment
1.  **Bot Config:** Create `telegram-bot/.env` (or set environment variables) with your tokens.
2.  **GitHub Secrets:** Add `GH_PAT`, `TELEGRAM_TOKEN`, and `TELEGRAM_CHAT_ID` to your repository settings.
3.  **Action Runner:** Register a new Self-Hosted Runner in GitHub and start it.
4.  **Launch Bot:** Run `python3 telegram-bot/main.py`.

---

## 🤖 Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Verify bot connectivity. |
| `/build <device>` | Trigger a new Build Action via GitHub dispatch. |
| `/status` | View real-time progress and live logs summary. |
| `/queue` | Check the current GitHub Actions workflow queue. |
| `/history` | View the last 5 build attempts. |
| `/health` | Monitor server disk, RAM, and runner status. |
| `/quota` | Check remaining daily build limits. |
| `/listuser` | List all authorized maintainers. |

### 🛡️ Admin Commands
| Command | Description |
| :--- | :--- |
| `/adduser <ID>` | Whitelist a new maintainer in `database.json`. |
| `/setrole <ID>` | Update a user's role (admin/user). |
| `/addquota <ID>` | Grant extra build slots manually. |

---

## 📸 Preview

### Build Status Dashboard
```text
✨ ACTIVE BUILD STATUS
━━━━━━━━━━━━━━━━━━━━━━━━
📱 Device   : begonia
🚦 Status   : Building
📊 Progress : [▰▰▰▱▱▱▱▱▱▱] 32% (4500/14000)
🧬 Variant  : Core - userdebug
👤 User     : @Saikrishna1504
⏱️ Updated  : 15s ago
━━━━━━━━━━━━━━━━━━━━━━━━
🔗 VIEW LIVE LOGS
```

### Artifact Delivery
```text
✨ BUILD COMPLETED SUCCESSFULLY
━━━━━━━━━━━━━━━━━━━━━━━━
├ 📱 Device  : begonia
├ 👤 Trigger : @Saikrishna1504
├ 🧬 Variant : Core - userdebug
└ ━━━━━━━━━━━━━━━━━━━━━━━

📦 Artifacts are ready for download below:

[ 💿 DOWNLOAD ROM ZIP ]
[ 📥 BOOT.IMG ] [ 📥 RECOVERY.IMG ]
[ 📄 OTA JSON ] [ 📊 VIEW RUN ]
```

---

## 🖥️ Monitoring & Debugging

### Persistent Console
Monitor the live terminal output (Sync + Build) from any shell:
```bash
TMUX= tmux attach -t axion_build
```

### Data Persistence
User quotas and permissions are stored in `database.json`, which is automatically updated by the `quota_manager.py` script via the GitHub API to ensure consistency across build runs.
