# 🪐 Orbit Server Manager

<div align="center">

![Orbit Server Manager Banner](logo.png)

### Modern, High-Performance Minecraft Java Server Management Suite

[![Python Version](https://img.shields.io/badge/Python-3.11%2B-A855F7?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-3B82F6?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com/windows)
[![UI Framework](https://img.shields.io/badge/GUI-CustomTkinter-C084FC?style=for-the-badge)](https://github.com/TomSchimansky/CustomTkinter)
[![Tunnel](https://img.shields.io/badge/Tunnel-Playit.gg-1BD96A?style=for-the-badge)](https://playit.gg)
[![API](https://img.shields.io/badge/API-Modrinth%20v2-00AF5C?style=for-the-badge&logo=modrinth&logoColor=white)](https://modrinth.com)

*A desktop application designed to streamline server installation, configuration, public tunneling, world management, and mod deployment into a cohesive Cosmic Purple workspace.*

</div>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [System Requirements](#-system-requirements)
- [Project Architecture](#-project-architecture)
- [Installation & Running from Source](#-installation--running-from-source)
- [Building Standalone Binary (.exe)](#-building-standalone-binary-exe)
- [Module Breakdown](#-module-breakdown)
- [Configuration Reference](#-configuration-reference)
- [Troubleshooting & Defensive Handling](#-troubleshooting--defensive-handling)
- [Dedication](#-dedication)

---

## 🌟 Overview

Running a Minecraft server locally usually involves juggling batch scripts, finding server JAR links, manually tracking Java compatibility, editing flat configuration files, and troubleshooting port-forwarding router tables. 

**Orbit Server Manager** solves this with a single GUI:
- Automates core JAR downloads across **Vanilla**, **Paper**, and **Fabric**.
- Integrates native zero-config public tunneling via **Playit.gg**.
- Provides a full in-app **Content Hub** for searching and installing mods, plugins, datapacks, and resource packs directly from Modrinth.
- Features a visual **World Manager** for dimension resets and active world swaps.
- Eliminates standard blocking popups with an animated, non-intrusive **Toast Notification Engine**.

---

## ⚡ Key Features

### 🌐 Zero-Config Public Tunneling (Playit.gg)
- Built-in background integration for the `playit.exe` tunneling agent.
- Auto-downloads the official binary if missing.
- Surfaces claim URLs directly for account linkage and generates public join addresses (e.g., `*.gl.joinmc.link` / `*.playit.gg`) right in the top bar.
- One-click clipboard copy for friends—no router port-forwarding required.

### 📦 Universal Modrinth Content Hub
- Search and download **Mods**, **Plugins**, **Datapacks**, and **Resourcepacks** without leaving the app.
- Auto-resolves compatibility matrix: `Exact (MC + Loader)` ➔ `Loader Fallback` ➔ `Latest Release`.
- Recursive required dependency resolution.
- One-click update engine that inspects installed packages, queries Modrinth API, and replaces outdated binaries.
- Dedicated `+ Import Local File` option for manual `.jar` and `.zip` packages.

### 🌍 Visual World & Dimension Manager
- Scans and visualizes all world directories containing `level.dat`.
- Swap the server's active world without editing `server.properties` by hand.
- **Dimension Resets**: One-click cleanup of Nether (`DIM-1`) or The End (`DIM1`) to regenerate dimensions on demand.
- Isolated single-world zip backups with automated timestamping.

### 📁 In-App File Manager & Editor
- Integrated dual-pane directory explorer and raw text editor.
- Navigate folders, inspect file sizes, and view last-modified timestamps.
- Create, delete, and modify server configuration files (`server.properties`, `ops.json`, `whitelist.json`) with direct in-app saving.

### 💻 Subprocess Management & Live Terminal
- Non-blocking I/O streaming with ANSI/log line parsing.
- Dynamic color coding for `ERROR`, `WARN`, and `SYSTEM` tags.
- Player tracking via log regex, enabling one-click actions: `/op`, `/deop`, `/kick`, and `/ban`.
- Command input field with execution history (navigate via `Up` / `Down` arrows).
- Graceful shutdown sequence (`stop` command ➔ configurable timeout watcher ➔ process termination if hung).

### ⚙ Auto-Scheduler & Safe Backups
- Background daemon thread executing recurring world backups without interrupting gameplay.
- Automatically issues `save-off` and `save-all flush` before archiving to avoid file lock issues.
- Configurable backup retention limit to keep disk usage controlled.
- Automated restart countdown timer with in-game `/say` broadcasts.

---

## 🖥 System Requirements

| Requirement | Specification |
| :--- | :--- |
| **Operating System** | Windows 10 / Windows 11 (64-bit) |
| **Python Runtime** | Python 3.11 or higher (if running from source) |
| **Java Environment** | Java 8, 17, or 21+ installed and linked in system `PATH` |
| **Hardware** | Minimum 4 GB RAM (8 GB recommended for modded environments) |
| **Disk Space** | Minimum 2 GB free disk space on target partition |

---

## 🏗 Project Architecture

OrbitServerManager/
├── logo.png                # High-res UI header banner
├── logo.ico                # Windows executable icon (multi-resolution)
├── config.json             # Runtime profiles and user preferences (auto-generated)
├── app.log                 # Rolling debug and error trace log
├── requirements.txt        # Python dependency manifest
├── version_info.txt        # PE metadata descriptor for PyInstaller
├── server_manager.py       # Core server process, APIs, properties, and tunneling
├── modrinth_api.py         # Modrinth v2 REST API client and updater engine
└── main.py                 # CustomTkinter UI presentation and event orchestration


---

## 🚀 Installation & Running from Source

### Step 1: Clone the Repository
```powershell
git clone [https://github.com/](https://github.com/)<YOUR_USERNAME>/OrbitServerManager.git
cd OrbitServerManager
Step 2: Set Up Virtual Environment
PowerShell
python -m venv venv
.\venv\Scripts\Activate.ps1
Step 3: Install Required Dependencies
PowerShell
pip install -r requirements.txt
Step 4: Launch Application
PowerShell
python main.py
📦 Building Standalone Binary (.exe)
Compile the entire project into a single, portable Windows .exe that includes all themes, icons, and dependencies:

PowerShell
# 1. Install PyInstaller
pip install pyinstaller

# 2. Extract CustomTkinter package assets location
$ctk_dir = py -c "import customtkinter, os; print(os.path.dirname(customtkinter.__file__))"

# 3. Compile standalone windowed executable
py -m PyInstaller --noconfirm --onefile --windowed `
    --name "OrbitServerManager" `
    --icon "logo.ico" `
    --add-data "$ctk_dir;customtkinter/" `
    --add-data "logo.png;." `
    --add-data "logo.ico;." `
    --hidden-import "requests" `
    --hidden-import "psutil" `
    --hidden-import "packaging" `
    --hidden-import "PIL" `
    main.py
After compilation finishes, your single-file executable will be ready at:

Plaintext
dist\OrbitServerManager.exe
🧩 Module Breakdown
server_manager.py
Contains all operating system interactions, process lifecycle orchestration, and network communications:

ProfileManager: CRUD operations on local server configuration profiles stored in config.json.

JavaEnvironment: Scans the environment to match installed Java major version against chosen Minecraft releases.

ServerDownloader: Fetches manifests from Mojang, PaperMC, and Fabric APIs with live stream progress callback.

ServerPropertiesManager: Reads and writes Minecraft's standard key-value properties file.

ServerProcess: Spawns and supervises non-blocking subprocess pipes (stdin, stdout, stderr).

BackupManager: Creates compressed zip archives of world saves while filtering out session.lock.

TaskScheduler: Background daemon running interval-based backup and server restart loops.

PlayitTunnel: Manages the playit.exe subprocess lifecycle, parses claim tokens, and reads dynamic domain assignments.

modrinth_api.py
Dedicated client for interacting with the Modrinth v2 REST API:

search_projects: Queries Modrinth projects with faceted loader and category filtering.

resolve_best_version: Evaluates game version and loader compatibility to pick the right file release.

resolve_dependencies: Recursively crawls and queues required third-party mods.

check_update_for_file: Compares local file builds with upstream remote releases.

Rate Limit Handling: Exponential backoff and retry mechanisms when encountering HTTP 429 errors.

main.py
Presentation and event coordination layer using CustomTkinter:

Pure presentation layer: delegates all background tasks to daemon threads and processes updates through a thread-safe queue.Queue.

Houses custom animated ToastManager sliding cards.

Controls sidebar switching, file browsing, console updates, and layout resizing.

⚙ Configuration Reference
The application automatically generates and maintains a local config.json:

JSON
{
    "settings": {
        "default_ram_gb": 4,
        "java_path_override": "",
        "backup_dir": "backups",
        "auto_start_last": false,
        "last_selected_profile": "Survival-1.20"
    },
    "profiles": {
        "Survival-1.20": {
            "name": "Survival-1.20",
            "folder_path": "C:\\Servers\\Survival",
            "mc_version": "1.20.4",
            "loader": "Paper",
            "ram_gb": 6,
            "jar_name": "server.jar"
        }
    }
}
🛠 Troubleshooting & Defensive Handling
1. Port Conflict (Port 25565 already in use)
Cause: Another Minecraft server, Docker container, or background Java task is already bound to the port.

Resolution: Change the server-port value in the Setup & Config tab or close the conflicting application via Task Manager.

2. Java Compatibility Warning
Cause: Modern Minecraft (1.20.5+) requires Java 21+, while versions 1.18–1.20.4 require Java 17, and 1.16 or older typically run on Java 8.

Resolution: Install the required JDK release and specify its executable path directly under App Settings ➔ Java Executable Path Override.

3. Modrinth 429 Rate Limiting
Cause: Rapid queries to the Modrinth API endpoints.

Resolution: The internal API client automatically reads Retry-After headers and pauses requests with exponential backoff before surfacing errors.

4. Application Logging
If an unexpected issue occurs, inspect app.log in the application root directory for full stack traces and debug output.

💜 Dedication
Plaintext
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Made specially for someone who is special for The Dev. ✨
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Developed with care by @yugansh_raj96 / OrbitOmen.
