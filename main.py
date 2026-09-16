import os
import sys
import queue
import shutil
import logging
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog
from datetime import datetime
from typing import Optional, List, Dict
import customtkinter as ctk

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from server_manager import (
    ProfileManager, JavaEnvironment, ServerDownloader,
    ServerPropertiesManager, ServerProcess, BackupManager, TaskScheduler,
    PlayitTunnel, log_exception
)
from modrinth_api import ModrinthAPI

ctk.set_appearance_mode("Dark")

# ==========================================
# COSMIC PURPLE THEME PALETTE
# ==========================================
PURPLE_ACCENT = "#A855F7"         # Electric Amethyst
PURPLE_HOVER = "#9333EA"          # Deep Violet Hover
PURPLE_GLOW = "#C084FC"           # Soft Lavender Glow
PURPLE_DARK_BTN = "#2D1F47"       # Dark Violet Button Base

BG_DARK = "#0D0B14"               # Cosmic Obsidian
SIDEBAR_BG = "#13101E"            # Elevated Dark Violet
CARD_BG = "#191528"               # Card Surface
INPUT_BG = "#221D35"              # Input / Listbox Surface
BORDER_COLOR = "#322B4D"          # Border Stroke
TEXT_MAIN = "#F3F0FF"             # Pure Lavender White
TEXT_MUTED = "#9D93B8"            # Soft Muted Purple-Gray


class ToastManager:
    """Sliding animated toast notifications in Purple Theme."""
    THEMES = {
        "success": {"border": PURPLE_ACCENT, "bg": "#221333", "icon": "✔", "fg": PURPLE_ACCENT},
        "error": {"border": "#EF4444", "bg": "#2A1216", "icon": "✖", "fg": "#EF4444"},
        "info": {"border": "#818CF8", "bg": "#171630", "icon": "ℹ", "fg": "#818CF8"},
        "warn": {"border": "#F59E0B", "bg": "#2A1D10", "icon": "⚠", "fg": "#F59E0B"}
    }

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.active_toasts: List[ctk.CTkFrame] = []

    def show(self, message: str, toast_type: str = "info", duration_ms: int = 3400):
        theme = self.THEMES.get(toast_type, self.THEMES["info"])

        toast = ctk.CTkFrame(
            self.root,
            fg_color=theme["bg"],
            border_color=theme["border"],
            border_width=1.5,
            corner_radius=10,
            width=330,
            height=62
        )
        toast.pack_propagate(False)

        content = ctk.CTkFrame(toast, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=8)

        ctk.CTkLabel(content, text=theme["icon"], font=("Segoe UI", 16, "bold"), text_color=theme["fg"], width=26).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(content, text=message, font=("Segoe UI", 11, "bold"), text_color="#F8FAFC", wraplength=240, justify="left", anchor="w").pack(side="left", fill="both", expand=True)

        target_y = 20 + (len(self.active_toasts) * 72)
        self.active_toasts.append(toast)
        self._animate_slide(toast, current_y=-70, target_y=target_y, step=9, callback=lambda: self.root.after(duration_ms, lambda: self._dismiss(toast)))

    def _animate_slide(self, widget: ctk.CTkFrame, current_y: int, target_y: int, step: int, callback=None):
        if not widget.winfo_exists():
            return
        if current_y < target_y:
            current_y = min(current_y + step, target_y)
            widget.place(relx=0.98, y=current_y, anchor="ne")
            self.root.after(12, lambda: self._animate_slide(widget, current_y, target_y, step, callback))
        else:
            widget.place(relx=0.98, y=target_y, anchor="ne")
            if callback:
                callback()

    def _dismiss(self, widget: ctk.CTkFrame):
        if not widget.winfo_exists():
            return

        def slide_out(curr_y):
            if not widget.winfo_exists():
                return
            if curr_y > -80:
                widget.place(relx=0.98, y=curr_y - 12, anchor="ne")
                self.root.after(12, lambda: slide_out(curr_y - 12))
            else:
                if widget in self.active_toasts:
                    self.active_toasts.remove(widget)
                widget.destroy()
                self._realign_toasts()

        slide_out(widget.winfo_y())

    def _realign_toasts(self):
        for idx, t in enumerate(self.active_toasts):
            if t.winfo_exists():
                target_y = 20 + (idx * 72)
                t.place(relx=0.98, y=target_y, anchor="ne")


class MinecraftServerManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Orbit Server Manager")
        self.geometry("1220x820")
        self.minsize(960, 640)
        self.resizable(True, True)
        self.configure(fg_color=BG_DARK)

        if os.path.exists("logo.ico"):
            try:
                self.iconbitmap("logo.ico")
            except Exception:
                pass

        self.profile_mgr = ProfileManager()
        self.modrinth = ModrinthAPI()
        self.active_server: ServerProcess | None = None
        self.scheduler = TaskScheduler(
            get_active_process=lambda: self.active_server,
            get_active_profile=self._get_current_profile_dict,
            get_global_settings=self.profile_mgr.get_settings,
            log_callback=self._queue_console_line
        )

        self.playit = PlayitTunnel(
            base_dir=os.path.abspath("."),
            on_log=self._queue_console_line,
            on_status_update=self._on_playit_status_update
        )

        self.toast = ToastManager(self)
        self.ui_queue = queue.Queue()
        self.cmd_history = []
        self.history_index = -1
        self.auto_scroll_enabled = True

        self.current_fm_dir = ""
        self.editing_filepath: Optional[str] = None
        self.playit_claim_link: Optional[str] = None

        self.sidebar_buttons: Dict[str, ctk.CTkButton] = {}
        self.content_frames: Dict[str, ctk.CTkFrame] = {}

        self._create_shell()
        self._build_all_views()
        self._switch_view("console")

        self._refresh_profiles_dropdown()
        self._load_global_settings()

        self.after(100, self._process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_shell(self):
        # 1. Left Sidebar
        self.sidebar = ctk.CTkFrame(self, width=225, corner_radius=0, fg_color=SIDEBAR_BG, border_color=BORDER_COLOR, border_width=1)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Brand Header / Logo
        brand_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand_box.pack(fill="x", padx=14, pady=(16, 12))

        if os.path.exists("logo.png") and PIL_AVAILABLE:
            try:
                raw_img = Image.open("logo.png")
                logo_img = ctk.CTkImage(light_image=raw_img, dark_image=raw_img, size=(190, 190))
                logo_label = ctk.CTkLabel(brand_box, image=logo_img, text="")
                logo_label.pack(pady=(0, 6))
            except Exception:
                self._fallback_brand_header(brand_box)
        else:
            self._fallback_brand_header(brand_box)

        # Nav Buttons Container
        nav_container = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav_container.pack(fill="both", expand=True)

        nav_items = [
            ("console", "⚡ Console & Run"),
            ("worlds", "🌍 World Manager"),
            ("content", "📦 Content & Packs"),
            ("files", "📁 File Manager"),
            ("setup", "⚙ Setup & Config"),
            ("backups", "💾 Auto Backups"),
            ("logs", "📜 Live Logs"),
            ("settings", "🛠 App Settings")
        ]

        for key, label in nav_items:
            btn = ctk.CTkButton(
                nav_container,
                text=label,
                anchor="w",
                height=38,
                font=("Segoe UI", 12, "bold"),
                fg_color="transparent",
                text_color="#D8B4FE",
                hover_color=CARD_BG,
                corner_radius=8,
                command=lambda k=key: self._switch_view(k)
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.sidebar_buttons[key] = btn

        # Dedication Note at Sidebar Bottom
        dedication_frame = ctk.CTkFrame(self.sidebar, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        dedication_frame.pack(side="bottom", fill="x", padx=12, pady=16)

        ctk.CTkLabel(
            dedication_frame,
            text="✨ Special Edition",
            font=("Segoe UI", 10, "bold"),
            text_color=PURPLE_GLOW
        ).pack(padx=10, pady=(8, 2))

        ctk.CTkLabel(
            dedication_frame,
            text="Made specially for someone\nwho is special for The Dev 💜",
            font=("Segoe UI", 9, "italic"),
            text_color="#E9D5FF",
            justify="center"
        ).pack(padx=8, pady=(0, 8))

        # 2. Main Container
        self.main_container = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        self.main_container.pack(side="right", fill="both", expand=True)

        # Top Bar
        self.top_bar = ctk.CTkFrame(self.main_container, height=60, fg_color=SIDEBAR_BG, corner_radius=0, border_color=BORDER_COLOR, border_width=1)
        self.top_bar.pack(side="top", fill="x")

        ctk.CTkLabel(self.top_bar, text="PROFILE:", font=("Segoe UI", 11, "bold"), text_color=TEXT_MUTED).pack(side="left", padx=(14, 6))
        self.profile_var = ctk.StringVar(value="None")
        self.profile_dropdown = ctk.CTkOptionMenu(
            self.top_bar,
            variable=self.profile_var,
            width=135,
            fg_color=INPUT_BG,
            button_color=BORDER_COLOR,
            button_hover_color=PURPLE_HOVER,
            text_color=TEXT_MAIN,
            command=self._on_profile_selected
        )
        self.profile_dropdown.pack(side="left", padx=4)

        ctk.CTkButton(self.top_bar, text="+ New", width=55, height=28, fg_color=CARD_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._prompt_new_profile).pack(side="left", padx=3)
        ctk.CTkButton(self.top_bar, text="Delete", width=55, height=28, fg_color="#4A1818", hover_color="#631F1F", text_color="#F87171", command=self._delete_profile).pack(side="left", padx=3)

        # Playit Public IP Box
        self.playit_box = ctk.CTkFrame(self.top_bar, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=8)
        self.playit_box.pack(side="left", padx=12, pady=8)

        self.btn_playit_toggle = ctk.CTkButton(
            self.playit_box,
            text="🌐 Enable Tunnel",
            width=115,
            height=26,
            font=("Segoe UI", 11, "bold"),
            fg_color=INPUT_BG,
            hover_color=BORDER_COLOR,
            text_color=PURPLE_GLOW,
            command=self._toggle_playit_tunnel
        )
        self.btn_playit_toggle.pack(side="left", padx=(6, 4), pady=4)

        self.lbl_playit_ip = ctk.CTkLabel(self.playit_box, text="Tunnel Offline", font=("Consolas", 11), text_color=TEXT_MUTED)
        self.lbl_playit_ip.pack(side="left", padx=8)

        self.btn_copy_ip = ctk.CTkButton(self.playit_box, text="Copy IP", width=65, height=24, fg_color=BORDER_COLOR, hover_color=PURPLE_HOVER, text_color=TEXT_MAIN, font=("Segoe UI", 10, "bold"), state="disabled", command=self._copy_playit_ip)
        self.btn_copy_ip.pack(side="left", padx=(0, 6))

        self.btn_claim = ctk.CTkButton(self.playit_box, text="Claim Setup", width=80, height=24, fg_color="#F59E0B", hover_color="#D97706", text_color="#000", font=("Segoe UI", 10, "bold"), command=self._open_claim_url)

        # Status Badges
        self.server_status_badge = ctk.CTkLabel(self.top_bar, text="● STOPPED", font=("Segoe UI", 12, "bold"), text_color="#EF4444")
        self.server_status_badge.pack(side="right", padx=(8, 16))

        self.btn_top_stop = ctk.CTkButton(self.top_bar, text="STOP", width=70, height=28, fg_color="#EF4444", hover_color="#DC2626", text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), state="disabled", command=self._stop_server)
        self.btn_top_stop.pack(side="right", padx=3)

        self.btn_top_start = ctk.CTkButton(self.top_bar, text="START", width=70, height=28, fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 12, "bold"), command=self._start_server)
        self.btn_top_start.pack(side="right", padx=3)

        self.view_host = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.view_host.pack(fill="both", expand=True, padx=12, pady=10)

    def _fallback_brand_header(self, parent):
        ctk.CTkLabel(parent, text="🪐 ORBIT", font=("Segoe UI", 20, "bold"), text_color=PURPLE_ACCENT).pack(anchor="w")
        ctk.CTkLabel(parent, text="SERVER MANAGER", font=("Segoe UI", 10, "bold"), text_color=TEXT_MUTED).pack(anchor="w")

    def _switch_view(self, view_key: str):
        for k, btn in self.sidebar_buttons.items():
            if k == view_key:
                btn.configure(fg_color=CARD_BG, text_color=PURPLE_ACCENT)
            else:
                btn.configure(fg_color="transparent", text_color="#D8B4FE")

        for k, frame in self.content_frames.items():
            if k == view_key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        if view_key == "worlds":
            self._refresh_worlds_tab()
        elif view_key == "files":
            self._fm_refresh()

    def _build_all_views(self):
        views = ["console", "worlds", "content", "files", "setup", "backups", "logs", "settings"]
        for v in views:
            self.content_frames[v] = ctk.CTkFrame(self.view_host, fg_color="transparent")

        self._build_console_view(self.content_frames["console"])
        self._build_worlds_view(self.content_frames["worlds"])
        self._build_content_view(self.content_frames["content"])
        self._build_files_view(self.content_frames["files"])
        self._build_setup_view(self.content_frames["setup"])
        self._build_backups_view(self.content_frames["backups"])
        self._build_logs_view(self.content_frames["logs"])
        self._build_settings_view(self.content_frames["settings"])

    # --- 1. CONSOLE VIEW ---
    def _build_console_view(self, parent):
        paned = ctk.CTkFrame(parent, fg_color="transparent")
        paned.pack(fill="both", expand=True)

        left_col = ctk.CTkFrame(paned, width=210, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        left_col.pack(side="left", fill="y", padx=(0, 10))
        left_col.pack_propagate(False)

        ctk.CTkLabel(left_col, text="Online Players", font=("Segoe UI", 13, "bold"), text_color=TEXT_MAIN).pack(pady=10)
        self.player_listbox = tk.Listbox(left_col, bg=INPUT_BG, fg=TEXT_MAIN, selectbackground=PURPLE_ACCENT, selectforeground="#FFFFFF", bd=0, highlightthickness=0)
        self.player_listbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        btn_box = ctk.CTkFrame(left_col, fg_color="transparent")
        btn_box.pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(btn_box, text="Op", width=42, height=28, fg_color=INPUT_BG, hover_color=PURPLE_HOVER, text_color=TEXT_MAIN, command=lambda: self._exec_player_action("op")).grid(row=0, column=0, padx=2, pady=2)
        ctk.CTkButton(btn_box, text="Deop", width=42, height=28, fg_color=INPUT_BG, hover_color=PURPLE_HOVER, text_color=TEXT_MAIN, command=lambda: self._exec_player_action("deop")).grid(row=0, column=1, padx=2, pady=2)
        ctk.CTkButton(btn_box, text="Kick", width=42, height=28, fg_color="#78350F", hover_color="#92400E", text_color="#FDE68A", command=lambda: self._exec_player_action("kick")).grid(row=1, column=0, padx=2, pady=2)
        ctk.CTkButton(btn_box, text="Ban", width=42, height=28, fg_color="#7F1D1D", hover_color="#991B1B", text_color="#FECACA", command=lambda: self._exec_player_action("ban")).grid(row=1, column=1, padx=2, pady=2)

        ctk.CTkButton(left_col, text="Save World", height=28, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=lambda: self._send_cmd("save-all")).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(left_col, text="Backup Now", height=28, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._trigger_instant_backup).pack(fill="x", padx=8, pady=(3, 10))

        right_col = ctk.CTkFrame(paned, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        right_col.pack(side="right", fill="both", expand=True)

        tool_bar = ctk.CTkFrame(right_col, height=32, fg_color="transparent")
        tool_bar.pack(fill="x", padx=8, pady=6)
        self.chk_autoscroll = ctk.CTkCheckBox(tool_bar, text="Auto-scroll", font=("Segoe UI", 11), checkbox_width=18, checkbox_height=18, fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, checkmark_color="#FFFFFF", command=self._toggle_autoscroll)
        self.chk_autoscroll.select()
        self.chk_autoscroll.pack(side="left", padx=4)
        ctk.CTkButton(tool_bar, text="Clear Console", width=85, height=24, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, font=("Segoe UI", 11), command=self._clear_console).pack(side="right", padx=4)

        self.console_box = tk.Text(right_col, bg="#0A0810", fg="#EDE9FE", insertbackground=PURPLE_ACCENT, wrap="char", font=("Consolas", 10), state="disabled", bd=0, padx=8, pady=8)
        self.console_box.tag_config("WARN", foreground="#FBBF24")
        self.console_box.tag_config("ERROR", foreground="#F87171")
        self.console_box.tag_config("SYSTEM", foreground=PURPLE_GLOW)
        self.console_box.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        cmd_bar = ctk.CTkFrame(right_col, fg_color="transparent")
        cmd_bar.pack(fill="x", padx=8, pady=(0, 8))
        self.cmd_entry = ctk.CTkEntry(cmd_bar, placeholder_text="Type command (e.g. say Hello) and hit Enter...", fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.cmd_entry.bind("<Return>", lambda e: self._submit_cmd())
        self.cmd_entry.bind("<Up>", self._hist_up)
        self.cmd_entry.bind("<Down>", self._hist_down)

        ctk.CTkButton(cmd_bar, text="Send", width=70, fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 12, "bold"), command=self._submit_cmd).pack(side="right")

    # --- 2. WORLDS VIEW ---
    def _build_worlds_view(self, parent):
        top_box = ctk.CTkFrame(parent, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        top_box.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(top_box, text="World Manager", font=("Segoe UI", 15, "bold"), text_color=TEXT_MAIN).pack(side="left", padx=14, pady=12)
        ctk.CTkButton(top_box, text="+ Create New World", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=self._wm_create_world_modal).pack(side="right", padx=12, pady=10)
        ctk.CTkButton(top_box, text="⟳ Refresh", width=70, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._refresh_worlds_tab).pack(side="right", padx=4)

        split = ctk.CTkFrame(parent, fg_color="transparent")
        split.pack(fill="both", expand=True)

        left_box = ctk.CTkFrame(split, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        left_box.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ctk.CTkLabel(left_box, text="Detected Worlds", font=("Segoe UI", 12, "bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=12, pady=8)
        self.wm_world_listbox = tk.Listbox(left_box, bg=INPUT_BG, fg=TEXT_MAIN, selectbackground=PURPLE_ACCENT, selectforeground="#FFFFFF", bd=0, font=("Segoe UI", 10))
        self.wm_world_listbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.wm_world_listbox.bind("<<ListboxSelect>>", self._wm_on_select_world)

        self.wm_card = ctk.CTkFrame(split, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        self.wm_card.pack(side="right", fill="both", expand=True, padx=(6, 0))

        self.wm_title_label = ctk.CTkLabel(self.wm_card, text="Select a world from the list", font=("Segoe UI", 15, "bold"), text_color=TEXT_MAIN)
        self.wm_title_label.pack(anchor="w", padx=16, pady=(14, 4))

        self.wm_info_label = ctk.CTkLabel(self.wm_card, text="Size: -- | Status: --", font=("Segoe UI", 11), text_color=TEXT_MUTED)
        self.wm_info_label.pack(anchor="w", padx=16, pady=(0, 14))

        self.wm_actions_frame = ctk.CTkFrame(self.wm_card, fg_color="transparent")
        self.wm_actions_frame.pack(fill="x", padx=16)

        ctk.CTkButton(self.wm_actions_frame, text="Set as Active Server World", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 12, "bold"), command=self._wm_set_active_world).pack(fill="x", pady=4)
        ctk.CTkButton(self.wm_actions_frame, text="Reset Nether (Delete DIM-1)", fg_color="#78350F", hover_color="#92400E", text_color="#FDE68A", font=("Segoe UI", 11, "bold"), command=self._wm_reset_nether).pack(fill="x", pady=4)
        ctk.CTkButton(self.wm_actions_frame, text="Reset The End (Delete DIM1)", fg_color="#581C87", hover_color="#6B21A8", text_color="#E9D5FF", font=("Segoe UI", 11, "bold"), command=self._wm_reset_end).pack(fill="x", pady=4)
        ctk.CTkButton(self.wm_actions_frame, text="Backup This World (.zip)", fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._wm_backup_selected).pack(fill="x", pady=4)
        ctk.CTkButton(self.wm_actions_frame, text="Delete Entire World", fg_color="#7F1D1D", hover_color="#991B1B", text_color="#FECACA", command=self._wm_delete_selected).pack(fill="x", pady=(14, 4))

    # --- 3. CONTENT VIEW ---
    def _build_content_view(self, parent):
        top_box = ctk.CTkFrame(parent, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        top_box.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(top_box, text="Category:", font=("Segoe UI", 11, "bold"), text_color=TEXT_MUTED).pack(side="left", padx=(14, 6), pady=12)
        self.content_type_var = ctk.StringVar(value="mod")

        self.content_type_opt = ctk.CTkSegmentedButton(
            top_box,
            values=["mod", "plugin", "datapack", "resourcepack"],
            variable=self.content_type_var,
            selected_color=PURPLE_ACCENT,
            selected_hover_color=PURPLE_HOVER,
            unselected_color=PURPLE_DARK_BTN,
            unselected_hover_color="#3D295C",
            text_color="#FFFFFF",
            font=("Segoe UI", 11, "bold"),
            command=lambda v: self._on_content_type_switched()
        )
        self.content_type_opt.pack(side="left", padx=5)

        ctk.CTkButton(top_box, text="+ Import Local (.jar/.zip)", fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._import_local_content_file).pack(side="right", padx=12)
        ctk.CTkButton(top_box, text="Check Updates", fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._check_installed_updates).pack(side="right", padx=4)

        search_box = ctk.CTkFrame(parent, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        search_box.pack(fill="x", pady=(0, 10))

        self.mod_search_entry = ctk.CTkEntry(search_box, placeholder_text="Search Modrinth (Lithium, Chunky, Terralith, Faithful)...", fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN, height=36)
        self.mod_search_entry.pack(side="left", fill="x", expand=True, padx=10, pady=8)
        self.mod_search_entry.bind("<Return>", lambda e: self._search_modrinth())

        ctk.CTkButton(search_box, text="Search", width=85, height=34, fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=self._search_modrinth).pack(side="right", padx=10)

        split = ctk.CTkFrame(parent, fg_color="transparent")
        split.pack(fill="both", expand=True)

        res_card = ctk.CTkFrame(split, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        res_card.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ctk.CTkLabel(res_card, text="Modrinth Discover", font=("Segoe UI", 12, "bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=12, pady=8)

        self.search_results_scroll = ctk.CTkScrollableFrame(res_card, fg_color="transparent")
        self.search_results_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        inst_card = ctk.CTkFrame(split, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        inst_card.pack(side="right", fill="both", expand=True, padx=(5, 0))

        ctk.CTkLabel(inst_card, text="Installed Content", font=("Segoe UI", 12, "bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=12, pady=8)
        self.installed_listbox = tk.Listbox(inst_card, bg=INPUT_BG, fg=TEXT_MAIN, selectbackground=PURPLE_ACCENT, selectforeground="#FFFFFF", bd=0)
        self.installed_listbox.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        inst_bottom = ctk.CTkFrame(inst_card, fg_color="transparent")
        inst_bottom.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(inst_bottom, text="Delete Selected", fg_color="#7F1D1D", hover_color="#991B1B", text_color="#FECACA", command=self._delete_selected_mod).pack(side="left")
        ctk.CTkButton(inst_bottom, text="Refresh", width=70, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._refresh_installed_mods).pack(side="right")

    # --- 4. FILE MANAGER VIEW ---
    def _build_files_view(self, parent):
        paned = ctk.CTkFrame(parent, fg_color="transparent")
        paned.pack(fill="both", expand=True)

        nav_bar = ctk.CTkFrame(paned, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        nav_bar.pack(fill="x", pady=(0, 10))

        ctk.CTkButton(nav_bar, text="⬆ Up", width=55, height=28, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._fm_navigate_up).pack(side="left", padx=(10, 4), pady=8)
        ctk.CTkButton(nav_bar, text="⟳ Refresh", width=65, height=28, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._fm_refresh).pack(side="left", padx=4)

        self.fm_path_label = ctk.CTkLabel(nav_bar, text="", font=("Segoe UI", 11, "bold"), text_color=TEXT_MUTED, anchor="w")
        self.fm_path_label.pack(side="left", fill="x", expand=True, padx=10)

        ctk.CTkButton(nav_bar, text="+ File", width=60, height=28, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._fm_create_file).pack(side="right", padx=3)
        ctk.CTkButton(nav_bar, text="+ Folder", width=70, height=28, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._fm_create_folder).pack(side="right", padx=3)
        ctk.CTkButton(nav_bar, text="Delete", width=60, height=28, fg_color="#7F1D1D", hover_color="#991B1B", text_color="#FECACA", command=self._fm_delete_selected).pack(side="right", padx=3)
        ctk.CTkButton(nav_bar, text="Edit", width=55, height=28, fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=self._fm_open_editor).pack(side="right", padx=(3, 10))

        split = ctk.CTkFrame(paned, fg_color="transparent")
        split.pack(fill="both", expand=True)

        self.fm_tree_frame = ctk.CTkFrame(split, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        self.fm_tree_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=INPUT_BG, foreground="#EDE9FE", fieldbackground=INPUT_BG, borderwidth=0, font=("Segoe UI", 10), rowheight=24)
        style.map("Treeview", background=[("selected", PURPLE_ACCENT)], foreground=[("selected", "#FFFFFF")])
        style.configure("Treeview.Heading", background=BORDER_COLOR, foreground="#EDE9FE", font=("Segoe UI", 10, "bold"))

        self.fm_tree = ttk.Treeview(self.fm_tree_frame, columns=("size", "modified"), selectmode="browse")
        self.fm_tree.heading("#0", text=" Name", anchor="w")
        self.fm_tree.heading("size", text="Size", anchor="e")
        self.fm_tree.heading("modified", text="Modified", anchor="center")
        self.fm_tree.column("#0", width=220)
        self.fm_tree.column("size", width=80, anchor="e")
        self.fm_tree.column("modified", width=140, anchor="center")

        self.fm_tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.fm_tree.bind("<Double-1>", self._fm_on_double_click)

        self.editor_frame = ctk.CTkFrame(split, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        self.editor_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        editor_top = ctk.CTkFrame(self.editor_frame, height=36, fg_color="transparent")
        editor_top.pack(fill="x", padx=10, pady=8)

        self.lbl_editing_file = ctk.CTkLabel(editor_top, text="No file opened for editing", font=("Segoe UI", 11, "italic"), text_color=TEXT_MUTED)
        self.lbl_editing_file.pack(side="left")

        ctk.CTkButton(editor_top, text="Save File", width=80, height=26, fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=self._fm_save_file).pack(side="right")

        self.editor_text = tk.Text(self.editor_frame, bg="#0A0810", fg="#EDE9FE", insertbackground=PURPLE_ACCENT, wrap="none", font=("Consolas", 10), undo=True, bd=0, padx=8, pady=8)
        self.editor_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # --- 5. SETUP VIEW ---
    def _build_setup_view(self, parent):
        scrollable = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scrollable.pack(fill="both", expand=True)

        setup_box = ctk.CTkFrame(scrollable, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        setup_box.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(setup_box, text="Download Server Jar", font=("Segoe UI", 14, "bold"), text_color=TEXT_MAIN).grid(row=0, column=0, columnspan=5, padx=14, pady=(12, 8), sticky="w")

        ctk.CTkLabel(setup_box, text="Loader:", text_color=TEXT_MUTED).grid(row=1, column=0, padx=14, pady=5, sticky="w")
        self.loader_var = ctk.StringVar(value="Paper")
        self.loader_opt = ctk.CTkOptionMenu(setup_box, variable=self.loader_var, values=["Vanilla", "Paper", "Fabric"], fg_color=INPUT_BG, button_color=BORDER_COLOR, button_hover_color=PURPLE_HOVER, text_color=TEXT_MAIN, command=self._on_loader_changed)
        self.loader_opt.grid(row=1, column=1, padx=6, pady=5)

        ctk.CTkLabel(setup_box, text="MC Version:", text_color=TEXT_MUTED).grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.version_var = ctk.StringVar(value="")
        self.version_opt = ctk.CTkOptionMenu(setup_box, variable=self.version_var, fg_color=INPUT_BG, button_color=BORDER_COLOR, button_hover_color=PURPLE_HOVER, text_color=TEXT_MAIN)
        self.version_opt.grid(row=1, column=3, padx=6, pady=5)

        ctk.CTkButton(setup_box, text="Fetch Versions", width=105, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._fetch_versions_async).grid(row=1, column=4, padx=10, pady=5)

        self.lbl_java_status = ctk.CTkLabel(setup_box, text="Detected Java: Detecting...", text_color=TEXT_MUTED)
        self.lbl_java_status.grid(row=2, column=0, columnspan=3, padx=14, pady=8, sticky="w")

        ctk.CTkButton(setup_box, text="Download Server Jar", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=self._download_jar_async).grid(row=2, column=3, columnspan=2, padx=10, pady=8, sticky="e")

        self.download_progress = ctk.CTkProgressBar(setup_box, progress_color=PURPLE_ACCENT)
        self.download_progress.set(0)
        self.download_progress.grid(row=3, column=0, columnspan=5, sticky="ew", padx=14, pady=(4, 14))

        prop_box = ctk.CTkFrame(scrollable, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        prop_box.pack(fill="x", pady=5)

        ctk.CTkLabel(prop_box, text="server.properties Configuration Form", font=("Segoe UI", 14, "bold"), text_color=TEXT_MAIN).grid(row=0, column=0, columnspan=4, padx=14, pady=(12, 8), sticky="w")

        ctk.CTkLabel(prop_box, text="Gamemode:", text_color=TEXT_MUTED).grid(row=1, column=0, padx=14, pady=5, sticky="w")
        self.prop_gamemode = ctk.CTkOptionMenu(prop_box, values=["survival", "creative", "adventure", "spectator"], fg_color=INPUT_BG, button_color=BORDER_COLOR, button_hover_color=PURPLE_HOVER, text_color=TEXT_MAIN)
        self.prop_gamemode.grid(row=1, column=1, padx=6, pady=5)

        ctk.CTkLabel(prop_box, text="Difficulty:", text_color=TEXT_MUTED).grid(row=1, column=2, padx=14, pady=5, sticky="w")
        self.prop_difficulty = ctk.CTkOptionMenu(prop_box, values=["peaceful", "easy", "normal", "hard"], fg_color=INPUT_BG, button_color=BORDER_COLOR, button_hover_color=PURPLE_HOVER, text_color=TEXT_MAIN)
        self.prop_difficulty.grid(row=1, column=3, padx=6, pady=5)

        self.prop_pvp = ctk.CTkCheckBox(prop_box, text="PvP Enabled", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, checkmark_color="#FFFFFF", text_color=TEXT_MAIN)
        self.prop_pvp.grid(row=2, column=0, padx=14, pady=8)

        self.prop_online = ctk.CTkCheckBox(prop_box, text="Online Mode (Auth)", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, checkmark_color="#FFFFFF", text_color=TEXT_MAIN)
        self.prop_online.grid(row=2, column=1, padx=14, pady=8)

        self.prop_whitelist = ctk.CTkCheckBox(prop_box, text="Whitelist Active", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, checkmark_color="#FFFFFF", text_color=TEXT_MAIN)
        self.prop_whitelist.grid(row=2, column=2, padx=14, pady=8)

        ctk.CTkLabel(prop_box, text="Max Players:", text_color=TEXT_MUTED).grid(row=3, column=0, padx=14, pady=5, sticky="w")
        self.prop_max_players = ctk.CTkEntry(prop_box, fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.prop_max_players.grid(row=3, column=1, padx=6, pady=5)

        ctk.CTkLabel(prop_box, text="Server Port:", text_color=TEXT_MUTED).grid(row=3, column=2, padx=14, pady=5, sticky="w")
        self.prop_port = ctk.CTkEntry(prop_box, fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.prop_port.grid(row=3, column=3, padx=6, pady=5)

        ctk.CTkLabel(prop_box, text="MOTD:", text_color=TEXT_MUTED).grid(row=4, column=0, padx=14, pady=5, sticky="w")
        self.prop_motd = ctk.CTkEntry(prop_box, width=380, fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.prop_motd.grid(row=4, column=1, columnspan=3, padx=6, pady=5, sticky="w")

        btn_prop_frame = ctk.CTkFrame(scrollable, fg_color="transparent")
        btn_prop_frame.pack(fill="x", pady=10)
        ctk.CTkButton(btn_prop_frame, text="Reload", width=80, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._load_current_properties).pack(side="left")
        ctk.CTkButton(btn_prop_frame, text="Save Properties Directly", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=self._save_properties_form).pack(side="right")

    # --- 6. BACKUPS VIEW ---
    def _build_backups_view(self, parent):
        top_box = ctk.CTkFrame(parent, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        top_box.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(top_box, text="Automatic Scheduler", font=("Segoe UI", 14, "bold"), text_color=TEXT_MAIN).grid(row=0, column=0, columnspan=4, padx=14, pady=(12, 8), sticky="w")

        ctk.CTkLabel(top_box, text="Backup Every (min):", text_color=TEXT_MUTED).grid(row=1, column=0, padx=14, pady=6, sticky="w")
        self.entry_sched_backup = ctk.CTkEntry(top_box, width=70, fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.entry_sched_backup.insert(0, "60")
        self.entry_sched_backup.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(top_box, text="Restart Every (min):", text_color=TEXT_MUTED).grid(row=1, column=2, padx=14, pady=6, sticky="w")
        self.entry_sched_restart = ctk.CTkEntry(top_box, width=70, fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.entry_sched_restart.insert(0, "0")
        self.entry_sched_restart.grid(row=1, column=3, padx=6, pady=6, sticky="w")

        self.btn_toggle_scheduler = ctk.CTkButton(top_box, text="Start Scheduler", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=self._toggle_scheduler)
        self.btn_toggle_scheduler.grid(row=2, column=0, columnspan=4, padx=14, pady=(6, 14), sticky="w")

        bot_box = ctk.CTkFrame(parent, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        bot_box.pack(fill="both", expand=True)

        ctk.CTkLabel(bot_box, text="Existing World Backups", font=("Segoe UI", 13, "bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=14, pady=10)
        self.backups_listbox = tk.Listbox(bot_box, bg=INPUT_BG, fg=TEXT_MAIN, selectbackground=PURPLE_ACCENT, selectforeground="#FFFFFF", bd=0)
        self.backups_listbox.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        act_bar = ctk.CTkFrame(bot_box, fg_color="transparent")
        act_bar.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(act_bar, text="Manual Backup Now", fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._trigger_instant_backup).pack(side="left")
        ctk.CTkButton(act_bar, text="Refresh", width=75, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._refresh_backups_list).pack(side="right")

    # --- 7. LOGS VIEW ---
    def _build_logs_view(self, parent):
        tool_bar = ctk.CTkFrame(parent, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        tool_bar.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(tool_bar, text="Tail / Refresh logs/latest.log", fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._tail_latest_log).pack(side="left", padx=10, pady=8)

        self.logs_box = tk.Text(parent, bg="#0A0810", fg="#EDE9FE", wrap="none", font=("Consolas", 9), bd=0, padx=8, pady=8)
        self.logs_box.pack(fill="both", expand=True)

    # --- 8. SETTINGS VIEW ---
    def _build_settings_view(self, parent):
        box = ctk.CTkFrame(parent, fg_color=CARD_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=10)
        box.pack(fill="both", expand=True, padx=2, pady=2)

        ctk.CTkLabel(box, text="Application Preferences", font=("Segoe UI", 16, "bold"), text_color=TEXT_MAIN).grid(row=0, column=0, columnspan=3, padx=16, pady=(16, 20), sticky="w")

        ctk.CTkLabel(box, text="Default RAM Allocation (GB):", text_color=TEXT_MUTED).grid(row=1, column=0, padx=16, pady=8, sticky="w")
        self.pref_ram = ctk.CTkEntry(box, width=80, fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.pref_ram.grid(row=1, column=1, sticky="w", pady=8)

        ctk.CTkLabel(box, text="Java Executable Path Override:", text_color=TEXT_MUTED).grid(row=2, column=0, padx=16, pady=8, sticky="w")
        self.pref_java_override = ctk.CTkEntry(box, width=320, fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.pref_java_override.grid(row=2, column=1, sticky="w", pady=8)
        ctk.CTkButton(box, text="Browse", width=70, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._browse_java_override).grid(row=2, column=2, padx=6, pady=8)

        ctk.CTkLabel(box, text="Backups Output Folder:", text_color=TEXT_MUTED).grid(row=3, column=0, padx=16, pady=8, sticky="w")
        self.pref_backup_dir = ctk.CTkEntry(box, width=320, fg_color=INPUT_BG, border_color=BORDER_COLOR, text_color=TEXT_MAIN)
        self.pref_backup_dir.grid(row=3, column=1, sticky="w", pady=8)
        ctk.CTkButton(box, text="Browse", width=70, fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=TEXT_MAIN, command=self._browse_backup_dir).grid(row=3, column=2, padx=6, pady=8)

        self.pref_autostart = ctk.CTkCheckBox(box, text="Auto-start last active server profile on launch", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, checkmark_color="#FFFFFF", text_color=TEXT_MAIN)
        self.pref_autostart.grid(row=4, column=0, columnspan=2, padx=16, pady=16, sticky="w")

        ctk.CTkButton(box, text="Save Preferences", fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=self._save_global_settings).grid(row=5, column=0, padx=16, pady=10, sticky="w")

    # ================= LOGIC & RUNTIME HANDLERS =================
    def _toggle_playit_tunnel(self):
        if not self.playit.is_running():
            ok, msg = self.playit.start()
            if ok:
                self.btn_playit_toggle.configure(text="🌐 Stop Tunnel", fg_color="#7F1D1D", hover_color="#991B1B", text_color="#FECACA")
                self.lbl_playit_ip.configure(text="Starting Agent...", text_color="#FBBF24")
                self.toast.show("Launching Playit background tunnel...", "info")
            else:
                self.toast.show(f"Playit error: {msg}", "error")
        else:
            self.playit.stop()
            self.btn_playit_toggle.configure(text="🌐 Enable Tunnel", fg_color=INPUT_BG, hover_color=BORDER_COLOR, text_color=PURPLE_GLOW)
            self.lbl_playit_ip.configure(text="Tunnel Offline", text_color=TEXT_MUTED)
            self.btn_copy_ip.configure(state="disabled")
            self.btn_claim.pack_forget()
            self.toast.show("Playit tunnel stopped.", "info")

    def _on_playit_status_update(self, status: str, payload: Optional[str]):
        self.ui_queue.put(("PLAYIT_EVENT", (status, payload)))

    def _copy_playit_ip(self):
        addr = self.lbl_playit_ip.cget("text")
        if addr and "Offline" not in addr:
            self.clipboard_clear()
            self.clipboard_append(addr)
            self.update()
            self.toast.show(f"Copied '{addr}' to clipboard!", "success")

    def _open_claim_url(self):
        if self.playit_claim_link:
            webbrowser.open(self.playit_claim_link)
            self.toast.show("Opened Playit claim URL in browser!", "info")

    def _queue_console_line(self, line: str):
        self.ui_queue.put(("CONSOLE", line))

    def _process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                msg_type, payload = self.ui_queue.get_nowait()
                if msg_type == "CONSOLE":
                    self._append_console(payload)
                elif msg_type == "STATUS":
                    status, color = payload
                    self.server_status_badge.configure(text=f"● {status}", text_color=color)
                elif msg_type == "PROGRESS":
                    self.download_progress.set(payload)
                elif msg_type == "TOAST":
                    text, t_type = payload
                    self.toast.show(text, t_type)
                elif msg_type == "UPDATE_PLAYERS":
                    self._refresh_player_list_ui()
                elif msg_type == "PLAYIT_EVENT":
                    status, arg = payload
                    if status == "ONLINE":
                        self.lbl_playit_ip.configure(text=arg, text_color=PURPLE_GLOW)
                        self.btn_copy_ip.configure(state="normal")
                        self.btn_claim.pack_forget()
                        self.toast.show(f"Playit Online: {arg}", "success")
                    elif status == "CLAIM_REQUIRED":
                        self.playit_claim_link = arg
                        self.lbl_playit_ip.configure(text="Action Required", text_color="#FBBF24")
                        self.btn_claim.pack(side="left", padx=(0, 6))
                        self.toast.show("Claim code received! Click 'Claim Setup' to bind account.", "warn")
                    elif status == "OFFLINE":
                        self.lbl_playit_ip.configure(text="Tunnel Offline", text_color=TEXT_MUTED)
                        self.btn_copy_ip.configure(state="disabled")
                        self.btn_claim.pack_forget()
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_ui_queue)

    def _append_console(self, line: str):
        self.console_box.configure(state="normal")
        tag = None
        if "ERROR" in line or "Exception" in line:
            tag = "ERROR"
        elif "WARN" in line:
            tag = "WARN"
        elif line.startswith("[MANAGER]") or line.startswith("[SCHEDULER]") or line.startswith("[MODRINTH]") or line.startswith("[PLAYIT]"):
            tag = "SYSTEM"

        if tag:
            self.console_box.insert("end", line + "\n", tag)
        else:
            self.console_box.insert("end", line + "\n")

        if self.auto_scroll_enabled:
            self.console_box.see("end")
        self.console_box.configure(state="disabled")

    def _start_server(self):
        prof = self._get_current_profile_dict()
        if not prof:
            self.toast.show("Select a profile first!", "warn")
            return

        self.active_server = ServerProcess(
            profile=prof,
            global_settings=self.profile_mgr.get_settings(),
            on_line_output=self._queue_console_line,
            on_stop_callback=self._on_server_stopped
        )

        ok, msg = self.active_server.start()
        if not ok:
            self.toast.show(f"Launch Failed: {msg}", "error")
            return

        self.btn_top_start.configure(state="disabled")
        self.btn_top_stop.configure(state="normal")
        self.server_status_badge.configure(text="● RUNNING", text_color=PURPLE_ACCENT)
        self.toast.show("Minecraft server starting up!", "success")

    def _stop_server(self):
        if self.active_server:
            self.active_server.stop()
            self.btn_top_stop.configure(state="disabled")
            self.toast.show("Stop command dispatched.", "info")

    def _on_server_stopped(self):
        self.ui_queue.put(("STATUS", ("STOPPED", "#EF4444")))
        self.ui_queue.put(("CONSOLE", "[MANAGER]: Server closed cleanly."))
        self.btn_top_start.configure(state="normal")
        self.btn_top_stop.configure(state="disabled")
        self.player_listbox.delete(0, "end")
        self.ui_queue.put(("TOAST", ("Server stopped.", "info")))

    def _submit_cmd(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        self.cmd_entry.delete(0, "end")
        self.cmd_history.append(cmd)
        self.history_index = len(self.cmd_history)
        self._send_cmd(cmd)

    def _send_cmd(self, cmd: str):
        if self.active_server and self.active_server.is_running():
            self._append_console(f"> {cmd}")
            self.active_server.send_command(cmd)
            if cmd.startswith("list"):
                self.after(1000, self._refresh_player_list_ui)
        else:
            self._append_console("[MANAGER]: Cannot send command. Server is offline.")
            self.toast.show("Server is offline!", "warn")

    def _hist_up(self, event):
        if self.cmd_history and self.history_index > 0:
            self.history_index -= 1
            self.cmd_entry.delete(0, "end")
            self.cmd_entry.insert(0, self.cmd_history[self.history_index])

    def _hist_down(self, event):
        if self.cmd_history and self.history_index < len(self.cmd_history) - 1:
            self.history_index += 1
            self.cmd_entry.delete(0, "end")
            self.cmd_entry.insert(0, self.cmd_history[self.history_index])
        else:
            self.history_index = len(self.cmd_history)
            self.cmd_entry.delete(0, "end")

    def _exec_player_action(self, action: str):
        sel = self.player_listbox.curselection()
        if not sel:
            self.toast.show("Select a player from list!", "warn")
            return
        player = self.player_listbox.get(sel[0])
        self._send_cmd(f"{action} {player}")

    def _refresh_player_list_ui(self):
        if self.active_server:
            self.player_listbox.delete(0, "end")
            for p in self.active_server.players:
                self.player_listbox.insert("end", p)

    def _clear_console(self):
        self.console_box.configure(state="normal")
        self.console_box.delete("1.0", "end")
        self.console_box.configure(state="disabled")

    def _toggle_autoscroll(self):
        self.auto_scroll_enabled = bool(self.chk_autoscroll.get())

    def _refresh_worlds_tab(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        server_dir = prof["folder_path"]
        self.wm_world_listbox.delete(0, "end")
        props = ServerPropertiesManager.read_properties(server_dir)
        active_world = props.get("level-name", "world")
        if os.path.exists(server_dir):
            for item in sorted(os.listdir(server_dir)):
                p = os.path.join(server_dir, item)
                if os.path.isdir(p) and os.path.exists(os.path.join(p, "level.dat")):
                    prefix = "★ [ACTIVE] " if item == active_world else "   "
                    self.wm_world_listbox.insert("end", f"{prefix}{item}")

    def _get_selected_world_name(self) -> Optional[str]:
        sel = self.wm_world_listbox.curselection()
        if not sel:
            return None
        text = self.wm_world_listbox.get(sel[0])
        return text.replace("★ [ACTIVE] ", "").strip()

    def _wm_on_select_world(self, event):
        world = self._get_selected_world_name()
        if not world:
            return
        prof = self._get_current_profile_dict()
        p = os.path.join(prof["folder_path"], world)
        total_size = sum(os.path.getsize(os.path.join(dirpath, f)) for dirpath, _, filenames in os.walk(p) for f in filenames)
        size_mb = round(total_size / (1024 * 1024), 2)
        has_nether = os.path.exists(os.path.join(p, "DIM-1"))
        has_end = os.path.exists(os.path.join(p, "DIM1"))
        self.wm_title_label.configure(text=f"World: {world}")
        self.wm_info_label.configure(text=f"Size: {size_mb} MB | Nether: {'Detected' if has_nether else 'None'} | The End: {'Detected' if has_end else 'None'}")

    def _wm_set_active_world(self):
        world = self._get_selected_world_name()
        if not world:
            self.toast.show("Select a world from list!", "warn")
            return
        prof = self._get_current_profile_dict()
        ServerPropertiesManager.write_properties(prof["folder_path"], {"level-name": world})
        self.toast.show(f"Set '{world}' as active level-name!", "success")
        self._refresh_worlds_tab()

    def _wm_reset_nether(self):
        world = self._get_selected_world_name()
        if not world:
            return
        prof = self._get_current_profile_dict()
        p = os.path.join(prof["folder_path"], world, "DIM-1")
        if os.path.exists(p):
            shutil.rmtree(p)
            self.toast.show(f"Nether reset for {world}!", "success")
            self._wm_on_select_world(None)
        else:
            self.toast.show("Nether (DIM-1) folder not found.", "info")

    def _wm_reset_end(self):
        world = self._get_selected_world_name()
        if not world:
            return
        prof = self._get_current_profile_dict()
        p = os.path.join(prof["folder_path"], world, "DIM1")
        if os.path.exists(p):
            shutil.rmtree(p)
            self.toast.show(f"The End reset for {world}!", "success")
            self._wm_on_select_world(None)
        else:
            self.toast.show("The End (DIM1) folder not found.", "info")

    def _wm_backup_selected(self):
        world = self._get_selected_world_name()
        if not world:
            return
        prof = self._get_current_profile_dict()
        settings = self.profile_mgr.get_settings()
        bdir = settings.get("backup_dir", "backups")
        os.makedirs(bdir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_zip = os.path.join(bdir, f"{world}_{ts}")
        shutil.make_archive(target_zip, "zip", os.path.join(prof["folder_path"], world))
        self.toast.show(f"Backed up {world}!", "success")

    def _wm_delete_selected(self):
        world = self._get_selected_world_name()
        if not world:
            return
        prof = self._get_current_profile_dict()
        try:
            shutil.rmtree(os.path.join(prof["folder_path"], world))
            self.toast.show(f"Deleted '{world}'.", "info")
            self._refresh_worlds_tab()
        except Exception as e:
            self.toast.show(f"Delete failed: {str(e)}", "error")

    def _wm_create_world_modal(self):
        dialog = ctk.CTkInputDialog(text="Enter new World Name:", title="Create World")
        name = dialog.get_input()
        if not name:
            return
        name = name.strip()
        prof = self._get_current_profile_dict()
        ServerPropertiesManager.write_properties(prof["folder_path"], {"level-name": name})
        self.toast.show(f"level-name set to '{name}'.", "success")
        self._refresh_worlds_tab()

    def _on_content_type_switched(self):
        self._refresh_installed_mods()

    def _get_target_content_dir(self, ctype: str) -> str:
        prof = self._get_current_profile_dict()
        base = prof["folder_path"]
        if ctype == "plugin":
            d = os.path.join(base, "plugins")
        elif ctype == "datapack":
            props = ServerPropertiesManager.read_properties(base)
            w_name = props.get("level-name", "world")
            d = os.path.join(base, w_name, "datapacks")
        elif ctype == "resourcepack":
            d = os.path.join(base, "resourcepacks")
        else:
            d = os.path.join(base, "mods")
        os.makedirs(d, exist_ok=True)
        return d

    def _import_local_content_file(self):
        ctype = self.content_type_var.get()
        target_dir = self._get_target_content_dir(ctype)
        file_path = filedialog.askopenfilename(title=f"Select {ctype.capitalize()} Archive", filetypes=[("Archives / Jars", "*.jar *.zip"), ("All Files", "*.*")])
        if not file_path:
            return
        filename = os.path.basename(file_path)
        shutil.copyfile(file_path, os.path.join(target_dir, filename))
        self.toast.show(f"Imported {filename} into {ctype}s!", "success")
        self._refresh_installed_mods()

    def _search_modrinth(self):
        query = self.mod_search_entry.get().strip()
        if not query:
            return
        prof = self._get_current_profile_dict()
        loader = prof.get("loader", "Paper") if prof else "Paper"
        ptype = self.content_type_var.get()

        for w in self.search_results_scroll.winfo_children():
            w.destroy()

        def worker():
            try:
                hits = self.modrinth.search_projects(query, loader, ptype)
                self.after(0, lambda: self._render_modrinth_results(hits))
            except Exception as e:
                log_exception(e, "search_modrinth")
                self.ui_queue.put(("TOAST", ("Search failed.", "error")))

        threading.Thread(target=worker, daemon=True).start()

    def _render_modrinth_results(self, hits: List[dict]):
        if not hits:
            ctk.CTkLabel(self.search_results_scroll, text="No compatible releases found.", text_color=TEXT_MUTED).pack(pady=20)
            return

        for hit in hits:
            card = ctk.CTkFrame(self.search_results_scroll, fg_color=INPUT_BG, border_color=BORDER_COLOR, border_width=1, corner_radius=8)
            card.pack(fill="x", pady=4, padx=2)

            title = hit.get("title", "Unknown")
            desc = hit.get("description", "")[:95] + "..."
            ctk.CTkLabel(card, text=title, font=("Segoe UI", 12, "bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=8, pady=(4, 0))
            ctk.CTkLabel(card, text=desc, font=("Segoe UI", 10), text_color=TEXT_MUTED).pack(anchor="w", padx=8)

            btn = ctk.CTkButton(card, text="Install", width=80, height=24, fg_color=PURPLE_ACCENT, hover_color=PURPLE_HOVER, text_color="#FFFFFF", font=("Segoe UI", 11, "bold"), command=lambda p=hit["project_id"], t=title: self._install_modrinth_content(p, t))
            btn.pack(anchor="e", padx=8, pady=6)

    def _install_modrinth_content(self, project_id: str, title: str):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        mc_ver = prof.get("mc_version", "1.20.4")
        loader = prof.get("loader", "Paper")
        ptype = self.content_type_var.get()
        target_dir = self._get_target_content_dir(ptype)

        def worker():
            try:
                self.ui_queue.put(("CONSOLE", f"[MODRINTH]: Resolving release for {title}..."))
                best_ver = self.modrinth.resolve_best_version(project_id, mc_ver, loader)
                if not best_ver:
                    self.ui_queue.put(("TOAST", (f"No compatible version for {mc_ver}.", "warn")))
                    return

                deps = self.modrinth.resolve_dependencies(best_ver, mc_ver, loader)
                if deps:
                    for d in deps:
                        self.modrinth.download_version_file(d["version_data"], target_dir)

                ok, msg = self.modrinth.download_version_file(best_ver, target_dir)
                if ok:
                    self.ui_queue.put(("TOAST", (f"Installed {title}!", "success")))
                    self.after(0, self._refresh_installed_mods)
                else:
                    self.ui_queue.put(("TOAST", (msg, "error")))
            except Exception as e:
                log_exception(e, "_install_modrinth_content")
                self.ui_queue.put(("TOAST", (f"Install failed: {str(e)}", "error")))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_installed_mods(self):
        self.installed_listbox.delete(0, "end")
        prof = self._get_current_profile_dict()
        if not prof:
            return
        ctype = self.content_type_var.get()
        target_dir = self._get_target_content_dir(ctype)
        if os.path.exists(target_dir):
            for item in sorted(os.listdir(target_dir)):
                if item.endswith(".jar") or item.endswith(".zip"):
                    self.installed_listbox.insert("end", item)

    def _delete_selected_mod(self):
        sel = self.installed_listbox.curselection()
        if not sel:
            return
        filename = self.installed_listbox.get(sel[0])
        ctype = self.content_type_var.get()
        target = os.path.join(self._get_target_content_dir(ctype), filename)
        if os.path.exists(target):
            os.remove(target)
            self.toast.show(f"Removed {filename}", "info")
            self._refresh_installed_mods()

    def _check_installed_updates(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        mc_ver = prof.get("mc_version", "1.20.4")
        loader = prof.get("loader", "Paper")
        ctype = self.content_type_var.get()
        target_dir = self._get_target_content_dir(ctype)

        def worker():
            count = 0
            for item in self.modrinth.scan_installed(target_dir):
                res = self.modrinth.check_update_for_file(item["filename"], mc_ver, loader)
                if res:
                    count += 1
                    os.remove(item["path"])
                    self.modrinth.download_version_file(res["version_data"], target_dir)
                    self.ui_queue.put(("CONSOLE", f"[UPDATE]: Updated {item['filename']} -> {res['new_filename']}"))
            self.ui_queue.put(("TOAST", (f"Scan complete. {count} items updated.", "info")))
            self.after(0, self._refresh_installed_mods)

        threading.Thread(target=worker, daemon=True).start()

    def _fm_refresh(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        base_dir = prof["folder_path"]
        if not self.current_fm_dir or not os.path.exists(self.current_fm_dir):
            self.current_fm_dir = base_dir

        rel_path = os.path.relpath(self.current_fm_dir, base_dir)
        self.fm_path_label.configure(text=f"📂 Root/{'' if rel_path == '.' else rel_path.replace(os.sep, '/')}")

        for row in self.fm_tree.get_children():
            self.fm_tree.delete(row)

        try:
            entries = os.listdir(self.current_fm_dir)
            folders = sorted([e for e in entries if os.path.isdir(os.path.join(self.current_fm_dir, e))])
            files = sorted([e for e in entries if os.path.isfile(os.path.join(self.current_fm_dir, e))])

            for folder in folders:
                p = os.path.join(self.current_fm_dir, folder)
                mod_time = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
                self.fm_tree.insert("", "end", text=f"📁 {folder}", values=("<DIR>", mod_time))

            for file in files:
                p = os.path.join(self.current_fm_dir, file)
                size_kb = f"{round(os.path.getsize(p) / 1024, 1)} KB"
                mod_time = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
                self.fm_tree.insert("", "end", text=f"📄 {file}", values=(size_kb, mod_time))
        except Exception as e:
            log_exception(e, "_fm_refresh")
            self.toast.show(f"Read Error: {str(e)}", "error")

    def _fm_navigate_up(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        base_dir = prof["folder_path"]
        if os.path.abspath(self.current_fm_dir) != os.path.abspath(base_dir):
            self.current_fm_dir = os.path.dirname(self.current_fm_dir)
            self._fm_refresh()

    def _fm_on_double_click(self, event):
        sel = self.fm_tree.selection()
        if not sel:
            return
        item_text = self.fm_tree.item(sel[0], "text")
        name = item_text[2:].strip()
        target_path = os.path.join(self.current_fm_dir, name)
        if os.path.isdir(target_path):
            self.current_fm_dir = target_path
            self._fm_refresh()
        else:
            self._fm_load_into_editor(target_path)

    def _fm_open_editor(self):
        sel = self.fm_tree.selection()
        if not sel:
            return
        name = self.fm_tree.item(sel[0], "text")[2:].strip()
        target_path = os.path.join(self.current_fm_dir, name)
        if os.path.isfile(target_path):
            self._fm_load_into_editor(target_path)

    def _fm_load_into_editor(self, filepath: str):
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self.editing_filepath = filepath
            self.lbl_editing_file.configure(text=f"Editing: {os.path.basename(filepath)}")
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", content)
            self.toast.show(f"Loaded {os.path.basename(filepath)}", "info")
        except Exception as e:
            self.toast.show(f"Cannot open: {str(e)}", "error")

    def _fm_save_file(self):
        if not self.editing_filepath:
            return
        try:
            content = self.editor_text.get("1.0", "end-1c")
            with open(self.editing_filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self.toast.show(f"Saved {os.path.basename(self.editing_filepath)}!", "success")
            self._fm_refresh()
        except Exception as e:
            self.toast.show(f"Save failed: {str(e)}", "error")

    def _fm_create_file(self):
        dialog = ctk.CTkInputDialog(text="Enter filename (e.g. ops.json):", title="New File")
        name = dialog.get_input()
        if not name:
            return
        p = os.path.join(self.current_fm_dir, name.strip())
        with open(p, "w", encoding="utf-8") as f:
            f.write("")
        self.toast.show(f"Created {name}!", "success")
        self._fm_refresh()

    def _fm_create_folder(self):
        dialog = ctk.CTkInputDialog(text="Enter folder name:", title="New Folder")
        name = dialog.get_input()
        if not name:
            return
        p = os.path.join(self.current_fm_dir, name.strip())
        os.makedirs(p, exist_ok=True)
        self.toast.show(f"Created folder '{name}'!", "success")
        self._fm_refresh()

    def _fm_delete_selected(self):
        sel = self.fm_tree.selection()
        if not sel:
            return
        name = self.fm_tree.item(sel[0], "text")[2:].strip()
        path = os.path.join(self.current_fm_dir, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            self.toast.show(f"Deleted {name}", "info")
            self._fm_refresh()
        except Exception as e:
            self.toast.show(f"Delete failed: {str(e)}", "error")

    def _refresh_profiles_dropdown(self):
        profiles = list(self.profile_mgr.get_profiles().keys())
        if not profiles:
            profiles = ["None"]
        self.profile_dropdown.configure(values=profiles)
        last = self.profile_mgr.get_settings().get("last_selected_profile", "")
        if last in profiles:
            self.profile_var.set(last)
            self._on_profile_selected(last)
        else:
            self.profile_var.set(profiles[0])
            self._on_profile_selected(profiles[0])

    def _get_current_profile_dict(self) -> Optional[dict]:
        name = self.profile_var.get()
        return self.profile_mgr.get_profile(name)

    def _prompt_new_profile(self):
        dialog = ctk.CTkInputDialog(text="Enter Profile Name:", title="Create Profile")
        name = dialog.get_input()
        if not name:
            return
        name = name.strip()
        folder = filedialog.askdirectory(title=f"Select Base Folder for Profile: {name}")
        if not folder:
            return

        profile_data = {
            "name": name,
            "folder_path": folder,
            "mc_version": "1.20.4",
            "loader": "Paper",
            "ram_gb": self.profile_mgr.get_settings().get("default_ram_gb", 4),
            "jar_name": "server.jar"
        }
        self.profile_mgr.save_profile(name, profile_data)
        self._refresh_profiles_dropdown()
        self.profile_var.set(name)
        self._on_profile_selected(name)
        self.toast.show(f"Profile '{name}' created!", "success")

    def _delete_profile(self):
        name = self.profile_var.get()
        if name == "None":
            return
        self.profile_mgr.delete_profile(name)
        self._refresh_profiles_dropdown()
        self.toast.show(f"Deleted '{name}'.", "info")

    def _on_profile_selected(self, name: str):
        if name == "None":
            return
        prof = self.profile_mgr.get_profile(name)
        if not prof:
            return
        self.profile_mgr.update_settings({"last_selected_profile": name})
        self.loader_var.set(prof.get("loader", "Paper"))
        self.version_var.set(prof.get("mc_version", "1.20.4"))
        self.current_fm_dir = prof["folder_path"]
        self._load_current_properties()
        self._refresh_installed_mods()
        self._refresh_backups_list()
        self._check_java_compatibility()
        self._refresh_worlds_tab()

    def _check_java_compatibility(self):
        java_exec = JavaEnvironment.get_java_executable(self.profile_mgr.get_settings().get("java_path_override", ""))
        installed_ver = JavaEnvironment.detect_java_version(java_exec)
        mc_ver = self.version_var.get() or "1.20.4"
        required_ver = JavaEnvironment.get_required_java_for_mc(mc_ver)

        if installed_ver is None:
            self.lbl_java_status.configure(text="Java Runtime: NOT DETECTED", text_color="#EF4444")
            return
        if installed_ver < required_ver:
            self.lbl_java_status.configure(text=f"Java Warning: Found Java {installed_ver}, needs {required_ver}+!", text_color="#F59E0B")
        else:
            self.lbl_java_status.configure(text=f"Java OK: Java {installed_ver} (Target: {required_ver}+)", text_color=PURPLE_GLOW)

    def _on_loader_changed(self, loader: str):
        self._fetch_versions_async()

    def _fetch_versions_async(self):
        loader = self.loader_var.get()

        def worker():
            try:
                if loader == "Vanilla":
                    vers = ServerDownloader.fetch_mojang_versions()
                elif loader == "Paper":
                    vers = ServerDownloader.fetch_paper_versions()
                elif loader == "Fabric":
                    vers = ServerDownloader.fetch_fabric_game_versions()
                else:
                    vers = []
                if vers:
                    self.version_opt.configure(values=vers[:50])
                    self.version_var.set(vers[0])
                    self._check_java_compatibility()
                    self.ui_queue.put(("TOAST", (f"Loaded {len(vers[:50])} {loader} releases!", "info")))
            except Exception as e:
                log_exception(e, "fetch_versions_async")
                self.ui_queue.put(("TOAST", ("Version fetch failed.", "error")))

        threading.Thread(target=worker, daemon=True).start()

    def _download_jar_async(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        loader = self.loader_var.get()
        version = self.version_var.get()
        if not version:
            return

        def worker():
            try:
                self.ui_queue.put(("CONSOLE", f"[MANAGER]: Resolving download for {loader} {version}..."))
                url = ServerDownloader.get_download_url(loader, version)
                dest = os.path.join(prof["folder_path"], "server.jar")

                def progress(downloaded, total):
                    if total > 0:
                        self.ui_queue.put(("PROGRESS", downloaded / total))

                ServerDownloader.download_file(url, dest, progress)
                prof["loader"] = loader
                prof["mc_version"] = version
                prof["jar_name"] = "server.jar"
                self.profile_mgr.save_profile(prof["name"], prof)
                ServerPropertiesManager.ensure_files_exist(prof["folder_path"])
                self.ui_queue.put(("TOAST", (f"Downloaded {loader} {version} server.jar!", "success")))
                self.ui_queue.put(("CONSOLE", "[MANAGER]: Download completed and EULA accepted."))
            except Exception as e:
                log_exception(e, "download_jar_async")
                self.ui_queue.put(("TOAST", (f"Download Error: {str(e)}", "error")))

        threading.Thread(target=worker, daemon=True).start()

    def _load_current_properties(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        props = ServerPropertiesManager.read_properties(prof["folder_path"])
        self.prop_gamemode.set(props.get("gamemode", "survival"))
        self.prop_difficulty.set(props.get("difficulty", "easy"))
        if props.get("pvp", "true").lower() == "true":
            self.prop_pvp.select()
        else:
            self.prop_pvp.deselect()
        if props.get("online-mode", "true").lower() == "true":
            self.prop_online.select()
        else:
            self.prop_online.deselect()
        if props.get("white-list", "false").lower() == "true":
            self.prop_whitelist.select()
        else:
            self.prop_whitelist.deselect()
        self.prop_max_players.delete(0, "end")
        self.prop_max_players.insert(0, props.get("max-players", "20"))
        self.prop_port.delete(0, "end")
        self.prop_port.insert(0, props.get("server-port", "25565"))
        self.prop_motd.delete(0, "end")
        self.prop_motd.insert(0, props.get("motd", "Minecraft Server"))

    def _save_properties_form(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        updates = {
            "gamemode": self.prop_gamemode.get(),
            "difficulty": self.prop_difficulty.get(),
            "pvp": "true" if self.prop_pvp.get() else "false",
            "online-mode": "true" if self.prop_online.get() else "false",
            "white-list": "true" if self.prop_whitelist.get() else "false",
            "max-players": self.prop_max_players.get().strip() or "20",
            "server-port": self.prop_port.get().strip() or "25565",
            "motd": self.prop_motd.get()
        }
        ServerPropertiesManager.write_properties(prof["folder_path"], updates)
        self.toast.show("Properties saved!", "success")

    def _refresh_backups_list(self):
        self.backups_listbox.delete(0, "end")
        settings = self.profile_mgr.get_settings()
        bdir = settings.get("backup_dir", "backups")
        if os.path.exists(bdir):
            for f in sorted(os.listdir(bdir), reverse=True):
                if f.endswith(".zip"):
                    size = round(os.path.getsize(os.path.join(bdir, f)) / (1024 * 1024), 2)
                    self.backups_listbox.insert("end", f"{f}  [{size} MB]")

    def _trigger_instant_backup(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return

        def worker():
            if self.active_server and self.active_server.is_running():
                self.active_server.send_command("save-off")
                self.active_server.send_command("save-all flush")
                import time
                time.sleep(2)

            settings = self.profile_mgr.get_settings()
            success, msg = BackupManager.create_backup(prof["folder_path"], settings.get("backup_dir", "backups"))

            if self.active_server and self.active_server.is_running():
                self.active_server.send_command("save-on")

            if success:
                self.ui_queue.put(("TOAST", ("World backup created!", "success")))
            else:
                self.ui_queue.put(("TOAST", (f"Backup Failed: {msg}", "error")))
            self.after(0, self._refresh_backups_list)

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_scheduler(self):
        if not self.scheduler.running:
            b_val = int(self.entry_sched_backup.get() or "0")
            r_val = int(self.entry_sched_restart.get() or "0")
            self.scheduler.start(b_val, r_val)
            self.btn_toggle_scheduler.configure(text="Stop Scheduler", fg_color="#7F1D1D", text_color="#FECACA")
            self.toast.show("Scheduler enabled!", "success")
        else:
            self.scheduler.stop()
            self.btn_toggle_scheduler.configure(text="Start Scheduler", fg_color=PURPLE_ACCENT, text_color="#FFFFFF")
            self.toast.show("Scheduler suspended.", "info")

    def _tail_latest_log(self):
        prof = self._get_current_profile_dict()
        if not prof:
            return
        log_file = os.path.join(prof["folder_path"], "logs", "latest.log")
        self.logs_box.delete("1.0", "end")
        if not os.path.exists(log_file):
            self.logs_box.insert("end", f"No log file found at: {log_file}")
            return
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                self.logs_box.insert("end", "".join(lines[-250:]))
                self.logs_box.see("end")
            self.toast.show("Tailed latest.log", "info")
        except Exception as e:
            log_exception(e, "_tail_latest_log")

    def _load_global_settings(self):
        s = self.profile_mgr.get_settings()
        self.pref_ram.delete(0, "end")
        self.pref_ram.insert(0, str(s.get("default_ram_gb", 4)))
        self.pref_java_override.delete(0, "end")
        self.pref_java_override.insert(0, s.get("java_path_override", ""))
        self.pref_backup_dir.delete(0, "end")
        self.pref_backup_dir.insert(0, s.get("backup_dir", "backups"))
        if s.get("auto_start_last", False):
            self.pref_autostart.select()
            if self.profile_var.get() != "None":
                self.after(1000, self._start_server)

    def _save_global_settings(self):
        try:
            ram = int(self.pref_ram.get().strip() or "4")
        except ValueError:
            ram = 4
        new_settings = {
            "default_ram_gb": ram,
            "java_path_override": self.pref_java_override.get().strip(),
            "backup_dir": self.pref_backup_dir.get().strip() or "backups",
            "auto_start_last": bool(self.pref_autostart.get())
        }
        self.profile_mgr.update_settings(new_settings)
        self.toast.show("Preferences saved!", "success")
        self._check_java_compatibility()

    def _browse_java_override(self):
        p = filedialog.askopenfilename(title="Select java.exe", filetypes=[("Executables", "*.exe"), ("All Files", "*.*")])
        if p:
            self.pref_java_override.delete(0, "end")
            self.pref_java_override.insert(0, p)

    def _browse_backup_dir(self):
        d = filedialog.askdirectory(title="Select Backups Directory")
        if d:
            self.pref_backup_dir.delete(0, "end")
            self.pref_backup_dir.insert(0, d)

    def _on_close(self):
        if self.playit.is_running():
            self.playit.stop()
        if self.active_server and self.active_server.is_running():
            self.scheduler.stop()
            self.active_server.stop()
        else:
            self.scheduler.stop()
        self.destroy()


if __name__ == "__main__":
    app = MinecraftServerManagerApp()
    app.mainloop()