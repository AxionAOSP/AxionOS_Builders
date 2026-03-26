# AxionOS Build System 🚀

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg?style=for-the-badge&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20Linux-orange.svg?style=for-the-badge&logo=linux&logoColor=white)

An automated **CI/CD pipeline** designed for building **AxionOS** (and other Android ROMs), fully integrated with a **Telegram Bot** for remote management and monitoring.

## 📋 Table of Contents
- [✨ Key Features](#-key-features)
- [🎯 Project Goal](#-project-goal)
- [📂 Project Structure](#-project-structure)
- [🛠️ Installation & Setup](#%EF%B8%8F-installation--setup)
- [🤖 Usage](#-usage)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)

---

## ✨ Key Features

*   **🤖 Telegram Bot Integration:** Control your build infrastructure from anywhere using simple commands.
*   **🏗 Remote Build Triggering:** Launch GitHub Actions workflows to build ROMs for specific devices (`/build`).
*   **👥 User Management:** Role-based access control (User, Admin, Owner) with whitelist support.
*   **⏳ Quota System:** Enforced daily build limits per user to manage resources efficiently.
*   **📊 Real-time Status:** Get live updates on build progress and success/failure notifications.
*   **📦 Artifact Delivery:** Automated upload of ROMs and images to GoFile with direct Telegram links.
*   **🧹 Smart Cleanup:** Intelligent logic to manage disk space between builds.

---

## 🎯 Project Goal

The primary goal of this project is to democratize and streamline the Android ROM compilation process. By bridging the gap between complex CI/CD infrastructure (GitHub Actions) and a user-friendly interface (Telegram), we aim to:

1.  **Reduce Friction:** Eliminate the need for constant terminal monitoring and manual server management.
2.  **Enhance Accessibility:** Allow developers to trigger and monitor builds from mobile devices.
3.  **Ensure Stability:** Enforce resource quotas and automated cleanups to maintain a healthy build environment.

---

## 📂 Project Structure

```text
/
├── .github/
│   └── workflows/
│       └── build.yml          # GitHub Actions CI workflow definition
├── builder/                   # Core build scripts & logic
│   ├── build.sh               # Main Axion build script (axion & ax)
│   ├── fsgen_control.sh       # Controls filesystem generation options
│   ├── quota_manager.py       # Manages user quotas & database updates
│   ├── reporter.py            # Reports build status/results & uploads artifacts
│   ├── sync.sh                # Repo sync script (axionSync)
│   ├── tmux_runner.sh         # Wrapper to run builds in background tmux sessions
│   └── sign.sh                # Signs target files and packages final ZIP
├── telegram-bot/              # Telegram Bot source code
│   ├── handlers/              # Command handlers
│   │   ├── admin.py           # Admin commands (adduser, setrole, etc.)
│   │   ├── general.py         # General commands (start, help, guide)
│   │   └── github.py          # GitHub interaction (build, status, cancel)
│   ├── main.py                # Bot entry point and startup logic
│   ├── requirements.txt       # Python dependencies for the bot
│   └── utils.py               # Shared utility functions (formatting, redis)
├── database.json              # User database (roles, quotas, history)
└── README.md                  # Project documentation
```

---

## 🛠️ Installation & Setup

### Prerequisites

*   **Python 3.8+**
*   **Redis Server** (for state management)
*   **GitHub Account** (for hosting the repo & running Actions)
*   **Telegram Bot Token** (from @BotFather)

### Installation

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/AxionAOSP/AxionOS-Builders

    cd AxionOS-Builders
    ```

2.  **Install Dependencies**
    ```bash
    pip install -r telegram-bot/requirements.txt
    ```

3.  **Configuration**
    Set up your environment variables (e.g., in a `.env` file or system env):
    *   `BOT_TOKEN`: Your Telegram Bot API Token.
    *   `REDIS_URL`: Connection string for Redis.
    *   `GITHUB_TOKEN`: Personal Access Token (PAT) with `repo` and `workflow` scopes.
    *   `GITHUB_REPO_NAME`: `username/repo`.
    *   `TELEGRAM_CHAT_ID`: Admin/Log chat ID.
    *   `OWNER_ID`: Telegram ID of the bot owner.

4.  **Run the Bot**
    ```bash
    python telegram-bot/main.py
    ```

---

## 🤖 Usage

### 👤 Telegram Bot Commands
| Command | Description |
| :--- | :--- |
| `/start` | Check if the bot is online. |
| `/help` | Show available commands based on your role. |
| `/guide` | View detailed build options & guide. |
| `/build <device>` | Trigger a new build via GitHub Actions. |
| `/status` | Check the status of running builds. |
| `/quota` | View your remaining daily build quota. |
| `/cancel <RunID>` | Cancel your own running build. |
| `/listuser` | List all registered users. |

### 🛡️ Admin Commands
*Accessible to Admins and Owner.*

| Command | Description |
| :--- | :--- |
| `/adduser <id> <name> [role]` | Whitelist a new user or update existing one. |
| `/removeuser <id>` | Remove a user from the database. |
| `/setrole <id> <role>` | Promote/Demote users (Roles: `user`, `admin`). |
| **Note** | Admins have unlimited build quota and can cancel *any* build. |

---
