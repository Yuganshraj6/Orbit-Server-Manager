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
