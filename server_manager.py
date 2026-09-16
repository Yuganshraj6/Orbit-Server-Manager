import os
import sys
import json
import time
import shutil
import socket
import logging
import zipfile
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable

# App Logger
logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

CONFIG_FILE = "config.json"
DEFAULT_HEADERS = {
    "User-Agent": "MinecraftServerManager/1.0 (Windows NT 10.0; Win64; x64)"
}

DEFAULT_CONFIG = {
    "settings": {
        "default_ram_gb": 4,
        "java_path_override": "",
        "backup_dir": "backups",
        "auto_start_last": False,
        "last_selected_profile": ""
    },
    "profiles": {}
}


def log_exception(exc: Exception, context: str = ""):
    logging.error(f"Exception in {context}: {str(exc)}", exc_info=True)


class ProfileManager:
    def __init__(self, filepath: str = CONFIG_FILE):
        self.filepath = filepath
        self.data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.filepath):
            self._save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_exception(e, "ProfileManager._load")
            return DEFAULT_CONFIG.copy()

    def _save(self, data: dict):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            log_exception(e, "ProfileManager._save")

    def get_settings(self) -> dict:
        return self.data.setdefault("settings", DEFAULT_CONFIG["settings"].copy())

    def update_settings(self, new_settings: dict):
        self.data["settings"].update(new_settings)
        self._save(self.data)

    def get_profiles(self) -> Dict[str, dict]:
        return self.data.setdefault("profiles", {})

    def get_profile(self, name: str) -> Optional[dict]:
        return self.data.get("profiles", {}).get(name)

    def save_profile(self, name: str, profile_data: dict):
        self.data.setdefault("profiles", {})[name] = profile_data
        self._save(self.data)

    def delete_profile(self, name: str):
        if name in self.data.get("profiles", {}):
            del self.data["profiles"][name]
            if self.data.get("settings", {}).get("last_selected_profile") == name:
                self.data["settings"]["last_selected_profile"] = ""
            self._save(self.data)


class JavaEnvironment:
    @staticmethod
    def get_java_executable(override_path: str = "") -> str:
        if override_path and os.path.isfile(override_path):
            return override_path
        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            candidate = os.path.join(java_home, "bin", "java.exe" if sys.platform == "win32" else "java")
            if os.path.isfile(candidate):
                return candidate
        return "java"

    @classmethod
    def detect_java_version(cls, java_exec: str) -> Optional[int]:
        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            res = subprocess.run(
                [java_exec, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo,
                timeout=5
            )
            raw = res.stderr or res.stdout
            for line in raw.splitlines():
                if "version" in line.lower():
                    parts = line.split('"')
                    if len(parts) > 1:
                        ver_str = parts[1]
                        if ver_str.startswith("1."):
                            return int(ver_str.split(".")[1])
                        return int(ver_str.split(".")[0])
        except Exception as e:
            log_exception(e, "detect_java_version")
        return None

    @staticmethod
    def get_required_java_for_mc(mc_version: str) -> int:
        try:
            tokens = mc_version.split(".")
            major = int(tokens[0])
            minor = int(tokens[1]) if len(tokens) > 1 else 0
            patch = int(tokens[2]) if len(tokens) > 2 else 0

            if major == 1:
                if minor >= 20 and patch >= 5:
                    return 21
                if minor >= 18:
                    return 17
                if minor == 17:
                    return 16
                return 8
            elif major >= 2:
                return 21
        except Exception:
            pass
        return 17


class ServerDownloader:
    """Robust version fetcher with fallback chains for PaperMC 410 issues."""

    @staticmethod
    def fetch_mojang_versions() -> List[str]:
        import requests
        url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()
        return [v["id"] for v in data.get("versions", []) if v.get("type") == "release"]

    @staticmethod
    def fetch_paper_versions() -> List[str]:
        import requests
        # 1. Try PaperMC v2 API with proper headers
        try:
            url = "https://api.papermc.io/v2/projects/paper"
            res = requests.get(url, headers=DEFAULT_HEADERS, timeout=5)
            if res.status_code == 200:
                vers = res.json().get("versions", [])
                if vers:
                    return vers[::-1]
        except Exception:
            pass

        # 2. Fallback: Purpur API (100% Paper compatible, live endpoint)
        try:
            url = "https://api.purpurmc.org/v2/purpur"
            res = requests.get(url, headers=DEFAULT_HEADERS, timeout=5)
            if res.status_code == 200:
                vers = res.json().get("versions", [])
                if vers:
                    return vers[::-1]
        except Exception:
            pass

        # 3. Fallback: Filter Mojang release manifest for Paper-compatible releases (1.16+)
        try:
            mojang = ServerDownloader.fetch_mojang_versions()
            return [v for v in mojang if v.startswith("1.2") or v.startswith("1.19") or v.startswith("1.18") or v.startswith("1.17") or v.startswith("1.16")]
        except Exception:
            pass

        # 4. Static offline fallback list (Prevents UI crashes under any circumstance)
        return [
            "1.21.4", "1.21.3", "1.21.1", "1.21",
            "1.20.6", "1.20.4", "1.20.2", "1.20.1",
            "1.19.4", "1.19.2", "1.18.2", "1.16.5"
        ]

    @staticmethod
    def fetch_fabric_game_versions() -> List[str]:
        import requests
        url = "https://meta.fabricmc.net/v2/versions/game"
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=10)
        res.raise_for_status()
        return [v["version"] for v in res.json() if v.get("stable", True)]

    @classmethod
    def get_download_url(cls, loader: str, mc_version: str) -> str:
        import requests
        loader = loader.lower()
        if loader == "vanilla":
            manifest = requests.get("https://launchermeta.mojang.com/mc/game/version_manifest.json", headers=DEFAULT_HEADERS, timeout=10).json()
            for v in manifest.get("versions", []):
                if v["id"] == mc_version:
                    v_meta = requests.get(v["url"], headers=DEFAULT_HEADERS, timeout=10).json()
                    return v_meta["downloads"]["server"]["url"]
            raise ValueError(f"Vanilla server jar not found for version {mc_version}")

        elif loader == "paper":
            # Attempt Paper official build
            try:
                builds_url = f"https://api.papermc.io/v2/projects/paper/versions/{mc_version}/builds"
                b_res = requests.get(builds_url, headers=DEFAULT_HEADERS, timeout=8)
                if b_res.status_code == 200:
                    builds = b_res.json().get("builds", [])
                    if builds:
                        latest_build = builds[-1]
                        build_num = latest_build["build"]
                        download_name = latest_build["downloads"]["application"]["name"]
                        return f"https://api.papermc.io/v2/projects/paper/versions/{mc_version}/builds/{build_num}/downloads/{download_name}"
            except Exception:
                pass

            # Fallback to Purpur jar (Drop-in Paper replacement)
            purpur_url = f"https://api.purpurmc.org/v2/purpur/{mc_version}/latest/download"
            return purpur_url

        elif loader == "fabric":
            loader_url = "https://meta.fabricmc.net/v2/versions/loader"
            l_data = requests.get(loader_url, headers=DEFAULT_HEADERS, timeout=10).json()
            latest_loader = l_data[0]["version"]
            installer_url = "https://meta.fabricmc.net/v2/versions/installer"
            inst_data = requests.get(installer_url, headers=DEFAULT_HEADERS, timeout=10).json()
            latest_installer = inst_data[0]["version"]
            return (f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/"
                    f"{latest_loader}/{latest_installer}/server/jar")

        raise NotImplementedError(f"Loader '{loader}' automatic download is not supported.")

    @staticmethod
    def download_file(url: str, dest_path: str, progress_callback: Optional[Callable[[int, int], None]] = None):
        import requests
        response = requests.get(url, headers=DEFAULT_HEADERS, stream=True, timeout=25)
        response.raise_for_status()
        total_length = int(response.headers.get("content-length", 0))
        downloaded = 0
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_length)


class ServerPropertiesManager:
    DEFAULTS = {
        "gamemode": "survival",
        "difficulty": "easy",
        "pvp": "true",
        "online-mode": "true",
        "white-list": "false",
        "max-players": "20",
        "server-port": "25565",
        "level-name": "world",
        "motd": "A Minecraft Server Managed by Python",
        "enable-command-block": "false",
        "spawn-protection": "16",
        "view-distance": "10"
    }

    @staticmethod
    def ensure_files_exist(server_dir: str):
        Path(server_dir).mkdir(parents=True, exist_ok=True)
        eula_path = os.path.join(server_dir, "eula.txt")
        if not os.path.exists(eula_path):
            with open(eula_path, "w", encoding="utf-8") as f:
                f.write("# EULA accepted by Minecraft Server Manager\neula=true\n")

        prop_path = os.path.join(server_dir, "server.properties")
        if not os.path.exists(prop_path):
            with open(prop_path, "w", encoding="utf-8") as f:
                for k, v in ServerPropertiesManager.DEFAULTS.items():
                    f.write(f"{k}={v}\n")

    @staticmethod
    def read_properties(server_dir: str) -> Dict[str, str]:
        prop_path = os.path.join(server_dir, "server.properties")
        if not os.path.exists(prop_path):
            ServerPropertiesManager.ensure_files_exist(server_dir)
        properties = {}
        with open(prop_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    properties[k.strip()] = v.strip()
        return properties

    @staticmethod
    def write_properties(server_dir: str, updates: Dict[str, str]):
        prop_path = os.path.join(server_dir, "server.properties")
        current = ServerPropertiesManager.read_properties(server_dir)
        current.update(updates)
        with open(prop_path, "w", encoding="utf-8") as f:
            f.write("# Minecraft Server Properties (Updated by Server Manager)\n")
            for k, v in sorted(current.items()):
                f.write(f"{k}={v}\n")


class ServerProcess:
    def __init__(self, profile: dict, global_settings: dict, on_line_output: Callable[[str], None], on_stop_callback: Callable[[], None]):
        self.profile = profile
        self.global_settings = global_settings
        self.on_line_output = on_line_output
        self.on_stop_callback = on_stop_callback
        self.process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self.players: List[str] = []

    def check_preflight(self) -> Tuple[bool, str]:
        server_dir = self.profile.get("folder_path", "")
        if not os.path.isdir(server_dir):
            return False, f"Server directory does not exist: {server_dir}"

        try:
            total, used, free = shutil.disk_usage(server_dir)
            if free < 1024 * 1024 * 1024:
                return False, f"Insufficient disk space. Free space: {free // (1024*1024)} MB. Minimum 1 GB required."
        except Exception as e:
            log_exception(e, "check_preflight disk check")

        props = ServerPropertiesManager.read_properties(server_dir)
        port = int(props.get("server-port", 25565))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            result = s.connect_ex(("127.0.0.1", port))
            if result == 0:
                return False, f"Port {port} is already in use by another application."

        jar_name = self.profile.get("jar_name", "server.jar")
        if not os.path.exists(os.path.join(server_dir, jar_name)):
            return False, f"Server executable '{jar_name}' was not found in directory."

        return True, "Preflight OK"

    def start(self) -> Tuple[bool, str]:
        ok, msg = self.check_preflight()
        if not ok:
            return False, msg

        server_dir = self.profile["folder_path"]
        ServerPropertiesManager.ensure_files_exist(server_dir)

        java_bin = JavaEnvironment.get_java_executable(self.global_settings.get("java_path_override", ""))
        ram_gb = self.profile.get("ram_gb", self.global_settings.get("default_ram_gb", 4))
        jar_name = self.profile.get("jar_name", "server.jar")

        cmd = [
            java_bin,
            f"-Xms{ram_gb}G",
            f"-Xmx{ram_gb}G",
            "-XX:+UseG1GC",
            "-jar",
            jar_name,
            "nogui"
        ]

        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.process = subprocess.Popen(
                cmd,
                cwd=server_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                startupinfo=startupinfo
            )
            logging.info(f"Server started: {' '.join(cmd)}")
            self._reader_thread = threading.Thread(target=self._stream_output, daemon=True)
            self._reader_thread.start()
            return True, "Server started successfully."
        except Exception as e:
            log_exception(e, "ServerProcess.start")
            return False, str(e)

    def _stream_output(self):
        if not self.process or not self.process.stdout:
            return
        for line in iter(self.process.stdout.readline, ''):
            clean_line = line.rstrip('\r\n')
            self._parse_player_presence(clean_line)
            self.on_line_output(clean_line)

        self.process.stdout.close()
        self.process.wait()
        self.on_stop_callback()

    def _parse_player_presence(self, line: str):
        if "joined the game" in line:
            parts = line.split("]: ")
            if len(parts) > 1:
                p = parts[1].replace(" joined the game", "").strip()
                if p and p not in self.players:
                    self.players.append(p)
        elif "left the game" in line:
            parts = line.split("]: ")
            if len(parts) > 1:
                p = parts[1].replace(" left the game", "").strip()
                if p in self.players:
                    self.players.remove(p)
        elif "players online:" in line:
            parts = line.split("players online:")
            if len(parts) > 1:
                raw_names = parts[1].strip()
                self.players = [n.strip() for n in raw_names.split(",") if n.strip()]

    def send_command(self, command: str):
        if self.is_running() and self.process.stdin:
            try:
                self.process.stdin.write(command + "\n")
                self.process.stdin.flush()
                logging.info(f"Command executed: {command}")
            except Exception as e:
                log_exception(e, "ServerProcess.send_command")

    def stop(self, timeout_sec: int = 15):
        if not self.is_running():
            return
        self.on_line_output("[MANAGER]: Initiating graceful stop command...")
        self.send_command("stop")

        def watcher():
            start_t = time.time()
            while time.time() - start_t < timeout_sec:
                if not self.is_running():
                    return
                time.sleep(0.5)
            if self.is_running():
                self.on_line_output(f"[MANAGER]: Force killing server process (exceeded {timeout_sec}s timeout)...")
                try:
                    self.process.kill()
                except Exception as e:
                    log_exception(e, "ServerProcess.stop kill")

        threading.Thread(target=watcher, daemon=True).start()

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None


class BackupManager:
    @staticmethod
    def create_backup(server_dir: str, backup_dir: str, retention_count: int = 5) -> Tuple[bool, str]:
        try:
            world_dir = os.path.join(server_dir, "world")
            if not os.path.exists(world_dir):
                props = ServerPropertiesManager.read_properties(server_dir)
                custom_name = props.get("level-name", "world")
                world_dir = os.path.join(server_dir, custom_name)

            if not os.path.exists(world_dir):
                return False, f"World directory '{world_dir}' does not exist."

            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"backup_{timestamp}.zip"
            archive_path = os.path.join(backup_dir, archive_name)

            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for root, dirs, files in os.walk(world_dir):
                    for file in files:
                        if file == "session.lock":
                            continue
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, os.path.join(world_dir, ".."))
                        zip_file.write(full_path, rel_path)

            BackupManager.enforce_retention(backup_dir, retention_count)
            return True, f"Backup created successfully: {archive_name}"
        except Exception as e:
            log_exception(e, "BackupManager.create_backup")
            return False, str(e)

    @staticmethod
    def enforce_retention(backup_dir: str, retention_count: int):
        try:
            files = [
                os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
                if f.startswith("backup_") and f.endswith(".zip")
            ]
            files.sort(key=os.path.getmtime)
            while len(files) > retention_count:
                oldest = files.pop(0)
                os.remove(oldest)
                logging.info(f"Enforced backup retention: removed {oldest}")
        except Exception as e:
            log_exception(e, "BackupManager.enforce_retention")


class TaskScheduler:
    def __init__(self, get_active_process: Callable[[], Optional[ServerProcess]], get_active_profile: Callable[[], Optional[dict]], get_global_settings: Callable[[], dict], log_callback: Callable[[str], None]):
        self.get_active_process = get_active_process
        self.get_active_profile = get_active_profile
        self.get_global_settings = get_global_settings
        self.log_callback = log_callback
        self.backup_interval_min = 0
        self.restart_interval_min = 0
        self.running = False
        self._thread: Optional[threading.Thread] = None

    def start(self, backup_interval_min: int, restart_interval_min: int):
        self.backup_interval_min = backup_interval_min
        self.restart_interval_min = restart_interval_min
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _run(self):
        last_backup = time.time()
        last_restart = time.time()

        while self.running:
            time.sleep(10)
            now = time.time()
            proc = self.get_active_process()
            profile = self.get_active_profile()

            if not proc or not proc.is_running() or not profile:
                continue

            if self.backup_interval_min > 0 and (now - last_backup >= self.backup_interval_min * 60):
                self.log_callback("[SCHEDULER]: Executing scheduled world backup...")
                proc.send_command("save-off")
                proc.send_command("save-all flush")
                time.sleep(3)
                settings = self.get_global_settings()
                success, msg = BackupManager.create_backup(profile["folder_path"], settings.get("backup_dir", "backups"))
                proc.send_command("save-on")
                self.log_callback(f"[SCHEDULER]: {msg}")
                last_backup = now

            if self.restart_interval_min > 0 and (now - last_restart >= self.restart_interval_min * 60):
                self._execute_warned_restart(proc)
                last_restart = now

    def _execute_warned_restart(self, proc: ServerProcess):
        warnings = [60, 30, 10, 5]
        for sec in warnings:
            proc.send_command(f"say Server will restart in {sec} seconds for scheduled maintenance.")
            time.sleep(min(sec, 10))
        proc.send_command("say Server restarting now!")
        proc.stop(timeout_sec=15)
        import re

class PlayitTunnel:
    """Manages the Playit.gg agent subprocess, auto-download, and IP resolution."""
    DOWNLOAD_URL = "https://github.com/playit-cloud/playit-agent/releases/latest/download/playit-windows-x86_64.exe"

    def __init__(self, base_dir: str, on_log: Callable[[str], None], on_status_update: Callable[[str, Optional[str]], None]):
        self.base_dir = base_dir
        self.exe_path = os.path.join(base_dir, "playit.exe")
        self.on_log = on_log
        self.on_status_update = on_status_update  # (status, address_or_claim_url)
        self.process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self.public_address: Optional[str] = None
        self.claim_url: Optional[str] = None

    def ensure_binary(self) -> bool:
        if os.path.exists(self.exe_path):
            return True
        try:
            import requests
            self.on_log("[PLAYIT]: playit.exe not found. Downloading official agent binary...")
            res = requests.get(self.DOWNLOAD_URL, stream=True, timeout=30)
            res.raise_for_status()
            with open(self.exe_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            self.on_log("[PLAYIT]: Agent downloaded successfully.")
            return True
        except Exception as e:
            log_exception(e, "PlayitTunnel.ensure_binary")
            self.on_log(f"[PLAYIT ERROR]: Failed to download binary: {str(e)}")
            return False

    def start(self) -> Tuple[bool, str]:
        if not self.ensure_binary():
            return False, "Could not obtain playit.exe agent."

        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            self.process = subprocess.Popen(
                [self.exe_path, "run"],
                cwd=self.base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                startupinfo=startupinfo
            )
            self.on_status_update("STARTING", None)
            self._reader_thread = threading.Thread(target=self._stream_output, daemon=True)
            self._reader_thread.start()
            return True, "Playit process initiated."
        except Exception as e:
            log_exception(e, "PlayitTunnel.start")
            return False, str(e)

    def _stream_output(self):
        if not self.process or not self.process.stdout:
            return

        for line in iter(self.process.stdout.readline, ''):
            clean = line.strip()
            self.on_log(f"[PLAYIT]: {clean}")

            # Parse Claim URL (first time run)
            if "playit.gg/claim/" in clean:
                match = re.search(r"https://playit\.gg/claim/\S+", clean)
                if match:
                    self.claim_url = match.group(0)
                    self.on_status_update("CLAIM_REQUIRED", self.claim_url)

            # Parse Public Server Domain / Address
            if any(ext in clean for ext in [".joinmc.link", ".playit.gg", ".ply.gg"]):
                match = re.search(r"([a-zA-Z0-9\.\-_]+\.(?:joinmc\.link|playit\.gg|ply\.gg)(?::\d+)?)", clean)
                if match:
                    self.public_address = match.group(1)
                    self.on_status_update("ONLINE", self.public_address)

        self.process.wait()
        self.on_status_update("OFFLINE", None)

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.on_log("[PLAYIT]: Tunnel stopped.")
        self.on_status_update("OFFLINE", None)

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None