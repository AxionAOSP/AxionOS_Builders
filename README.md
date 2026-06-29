# AxionOS Build System 🚀

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg?style=for-the-badge&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20Linux-orange.svg?style=for-the-badge&logo=linux&logoColor=white)

A high-performance CI/CD pipeline for building AxionOS and other Android ROMs. This system bridges GitHub Actions with a Telegram bot interface, allowing for remote-controlled build management, surgical artifact detection, and real-time monitoring.

---

## 📂 Repository Structure

### 🏗️ `builder/`
Contains the core build logic executed on the self-hosted runner.
*   **`build.sh` / `sync.sh`**: Core AOSP sync and compilation scripts. Now includes a robust blocking loop to ensure the ROM ZIP is ready before finalizing.
*   **`tmux_runner.sh`**: Orchestrates the build within a persistent `tmux` session. Uses `pipe-pane` for high-performance, real-time log streaming with zero CPU overhead.
*   **`reporter.py`**: Background monitoring tool. Uses surgical log parsing (`Package Complete:`) to identify artifacts with 100% accuracy.
*   **`utils/telegram.py`**: Shared utility for Telegram API interactions.

### 🤖 `telegram-bot/`
The control center for the entire system.
*   **`main.py`**: Entry point for the Telegram bot. Now includes structured logging with a clean terminal interface.
*   **`handlers/`**: Modularized command logic.
    *   `github.py`: Build triggers, automatic manifest discovery, and queue management.
    *   `admin.py`: User management, chat authorization, channel redirection, and broadcast tools.
*   **`utils.py`**: Helper functions for bot operations and Redis interactions.

---

## 🚀 Key Features

*   **Smart Manifest Discovery**: Just run `/build <codename>`. The bot automatically pulls the manifest from the `AxionAOSP/device_manifests` repository.
*   **Automated CDN Uploads**: Optional high-speed R2 mirroring for ROM ZIPs directly from the build menu.
*   **Dynamic Upload Streams**: Toggle between Gofile and Pixeldrain as your main free upload stream with the `/usepd` command, complete with automatic fallback logic.
*   **Zero-Overhead Monitoring**: Real-time progress bars and log summaries streamed via high-performance I/O.
*   **Channel Redirection**: Redirect build notifications and artifact reports to a dedicated Telegram channel.
*   **Surgical Artifact Detection**: Extracts the exact output path from build logs to ensure the correct files are uploaded every time.
*   **Broadcast System**: Owner-only `/announce` command to communicate with all maintainers across all approved groups and channels.
*   **Dynamic Authorization**: Easily approve or disapprove groups by ID or directly within the chat.

---

## 🤖 Bot Commands

To view all available commands, their usage guidelines, and detailed administrative options, simply run the **`/help`** command inside an authorized Telegram group, or interact with the bot's dynamic commands menu directly in your chat interface.

---

## 📸 Preview

### Build Setup Menu
The `/build` command triggers an interactive menu to customize your build:
*   **Type**: Toggle build type (`user`, `userdebug`, `eng`).
*   **GMS**: Choose variant (`GMS`, `PICO`, `CORE`, `VANILLA`).
*   **Clean**: Toggle `mka clean` before building (Full Clean).
*   **Release Build**: Toggle automated Cloudflare R2 CDN mirroring for the ROM ZIP on success (creates premium high-speed release download links).
*   **Target**: Dynamically redirects to your main channel if configured.

### Artifact Delivery
Once a build is complete, you get a premium delivery card:
*   **💿 DOWNLOAD ROM ZIP**: Primary artifact link (points to Gofile/Pixeldrain in regular builds).
*   **🚀 CDN MIRROR**: Premium, high-speed release download link (available if the **"Release Build"** toggle was enabled).
*   **📦 TARGET FILES**: The generated `target_files.zip` (available only when **"Release Build"** is enabled). To save premium Cloudflare R2 storage, this developer-only asset (used to compile future **incremental OTA packages**) is uploaded to the free storage stream (Gofile/Pixeldrain), keeping your CDN exclusively reserved for user-facing ROM downloads.
*   **📥 IMAGE ARTIFACTS**: Boot, Recovery, and Vendor images grouped for a clean, cohesive user interface.
*   **📄 OTA JSON**: Direct link to the generated release metadata.

---

## ⚙️ Setup & Configuration

This system utilizes a **dual-configuration model** to maintain security and portability:
1. **Local Server Config (`private.env`)**: Governs the local Telegram Bot service running on your server.
2. **GitHub Repository Secrets**: Injected securely into the GitHub Actions runner pipeline during active builds.

### 1. Local Server Config (`telegram-bot/private.env`)
To run the local Telegram bot on your server, copy the template and configure your variables:
```bash
cp private.env.example telegram-bot/private.env
nano telegram-bot/private.env
```

Ensure the following variables are defined (see `private.env.example` for details):
*   `BOT_TOKEN`: Your Telegram Bot Token (from @BotFather).
*   `CHANNEL_ID`: Chat ID where build updates are sent.
*   `TOPIC_BUILDER`: Thread ID (if using a Forum group).
*   `OWNER_ID`: Your personal Telegram User ID.
*   `GITHUB_TOKEN`: GitHub Personal Access Token (PAT) with `repo` scope.
*   `GITHUB_REPO_NAME`: Your GitHub Repository (e.g., `Owner/RepoName`).
*   `GITHUB_BRANCH`: Active branch (e.g., `actions`).
*   `REDIS_URL`: Redis connection string (e.g., `redis://localhost:6379/4`).
*   `ALLOWED_CHAT_IDS`: List of permitted Group IDs.
*   `ADMIN_USER_IDS`: List of authorized Admin User IDs.
*   `PD_API_KEY`: Optional Pixeldrain API Key.

---

### 2. GitHub Repository Secrets (Set on GitHub.com)
The build pipeline runner executes on GitHub's ecosystem. You **must NOT** save any CDN or build notification secrets in your local `private.env` file. Instead, configure them as **Repository Secrets** on your GitHub repository (under `Settings -> Secrets and variables -> Actions`):

#### 🏗️ Builder Pipeline Secrets:
*   `GH_PAT`: GitHub Personal Access Token (same as `GITHUB_TOKEN` above).
*   `TELEGRAM_TOKEN`: Bot Token (same as `BOT_TOKEN` above).
*   `TELEGRAM_CHAT_ID`: Notification group ID (same as `CHANNEL_ID` above).
*   `TOPIC_BUILDER`: Thread ID (same as `TOPIC_BUILDER` above).
*   `TOPIC_ERROR_LOGS`: Thread ID dedicated to posting compile error logs.
*   `TOPIC_RELEASE_JSON`: Thread ID dedicated to posting OTA release JSON artifacts.

#### ☁️ Cloudflare R2 CDN Secrets (Optional - for Success Mirroring):
*   `R2_ACCESS_KEY`: Cloudflare R2 Access Key ID.
*   `R2_SECRET_KEY`: Cloudflare R2 Secret Access Key.
*   `R2_ACCOUNT_ID`: Cloudflare R2 Account ID.
*   `R2_BUCKET`: Target R2 bucket name (e.g., `axionos-releases`).
*   `R2_CDN_DOMAIN`: Custom CDN domain mapped to your bucket (e.g., `https://cdn.axionos.org`).

---

## 🛠️ Prerequisites

Install all required system and builder dependencies:

```bash
pip install -r requirements.txt
```

---

## 🖥️ Monitoring & Debugging

### Live Logs
The bot saves structured logs to `telegram-bot/bot.log` while maintaining a clean, human-readable terminal output. Monitor them in real-time:
```bash
tail -f telegram-bot/bot.log
```

### Persistent Console
Monitor the raw build environment from the server:
```bash
TMUX= tmux attach -t axion_build
```
