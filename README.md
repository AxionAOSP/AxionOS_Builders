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
*   **Zero-Overhead Monitoring**: Real-time progress bars and log summaries streamed via high-performance I/O.
*   **Channel Redirection**: Redirect build notifications and artifact reports to a dedicated Telegram channel.
*   **Surgical Artifact Detection**: Extracts the exact output path from build logs to ensure the correct files are uploaded every time.
*   **Broadcast System**: Owner-only `/announce` command to communicate with all maintainers across all approved groups and channels.
*   **Dynamic Authorization**: Easily approve or disapprove groups by ID or directly within the chat.

---

## 🤖 Bot Commands

### 👤 User Commands
| Command | Description |
| :--- | :--- |
| `/build <device> [url]` | Start a new build (Authorized groups only). |
| `/status [device]` | Show real-time ROM build progress. |
| `/queue` | View the current GitHub Actions workflow queue. |
| `/cancel <RunID>` | Cancel your active build. |
| `/history` | View the last 5 build attempts. |
| `/health` | Monitor server disk, RAM, and runner status. |
| `/listuser` | List all authorized admins. |
| `/guide` | View detailed build options and manifest templates. |

### 🛡️ Admin Commands
| Command | Description |
| :--- | :--- |
| `/approvechat [ID]` | Authorize a group for bot usage. |
| `/disapprovechat [ID]` | Remove a group from the authorized list. |
| `/listchats` | View all authorized groups and the current output channel. |
| `/removeuser <ID>` | Remove an admin from the database. |
| `/setrole <role> <user>` | Promote/Demote an admin. |
| `/setchannel <ID>` | Redirect all build notifications to a specific channel. |
| `/save` | Force a manual sync of the Redis state to the GitHub DB. |
| `/cancel <RunID>` | Cancel any active GitHub workflow run. |

### 👑 Owner Commands
| Command | Description |
| :--- | :--- |
| `/announce <msg>` | Broadcast an official announcement to all groups and the main channel. |
| `/sync` | Force a manual sync of the GitHub DB to the Redis cache. |

---

## 📸 Preview

### Build Setup Menu
The `/build` command triggers an interactive menu to customize your build:
*   **Type**: Toggle build type (user, userdebug, eng).
*   **GMS**: Choose variant (GMS, PICO, CORE, VANILLA).
*   **Clean**: Toggle `mka clean` before building.
*   **Target**: Dynamically redirects to your main channel if configured.

### Artifact Delivery
Once a build is complete, you get a premium delivery card:
*   **💿 DOWNLOAD ROM ZIP**: Primary artifact link.
*   **📥 IMAGE ARTIFACTS**: Boot, Recovery, and Vendor images grouped for a clean UI.
*   **📄 OTA JSON**: Direct link to the generated release metadata.

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
