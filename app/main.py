import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import os
import sys
import threading
import queue
import webbrowser
import json
from typing import Optional
from app import __version__
from app.update_checker import get_update_info, classify_update
from app import settings_manager
from app import updater

# Windows Taskbar Icon Fix (Set AppUserModelID)
if sys.platform == "win32":
    try:
        import ctypes
        myappid = f'SonicSandbox.Surasura.ReadabilityAnalyzer.{__version__}'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

# Custom Dark Theme Configuration
BG_COLOR = "#1e1e1e"
SURFACE_COLOR = "#2d2d2d"
TEXT_COLOR = "#e0e0e0"
ACCENT_COLOR = "#bb86fc"
SECONDARY_COLOR = "#03dac6"
ERROR_COLOR = "#cf6679"

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window: tk.Toplevel | None = None
        self.id = None
        self.widget.bind("<Enter>", self.schedule_tip)
        self.widget.bind("<Leave>", self.hide_tip)
        self.widget.bind("<ButtonPress>", self.hide_tip)

    def schedule_tip(self, event=None):
        self.unschedule()
        # Use delay from settings if available, else default 500
        delay = 500
        try:
            # Check if MasterDashboardApp has a stored delay
            # Tooltips are bound to widgets which have a master (app)
            # This is a bit hacky but works for this architecture
            app = self.widget.winfo_toplevel()
            if hasattr(app, 'logic_settings'):
                delay = app.logic_settings.get("gui", {}).get("tooltip_delay", 500)
        except Exception:
            pass
            
        self.id = self.widget.after(delay, self.show_tip)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
            
        # Optimization: Calculate position carefully to avoid "flashing" (cursor overlap)
        # Position to the right of the widget by default, or below if it's too wide
        bbox = self.widget.bbox("insert") 
        # Simple usage of root coordinates
        root_x = self.widget.winfo_rootx()
        root_y = self.widget.winfo_rooty()
        widget_height = self.widget.winfo_height()
        widget_width = self.widget.winfo_width()
        
        # Position: Bottom-Right of the start of the widget, but ensuring it's not under cursor
        # Moving it slightly down and right
        x = root_x + 20
        y = root_y + widget_height + 2
        
        # For very wide widgets (like checkboxes), maybe force it further right?
        # The user requested: "Add the tooltip to the right so it's visible for the 2 exclude toggles"
        if "Checkbutton" in self.widget.winfo_class():
             x = root_x + widget_width + 10
             y = root_y

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        # MacOS/Linux might need this to float on top
        try: 
            tw.wm_attributes("-topmost", True)
            tw.wm_attributes("-transparent", True) # Not supported on all, but harmless
        except:
             pass
             
        tw.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                      background=SURFACE_COLOR, foreground=TEXT_COLOR,
                      relief=tk.FLAT, borderwidth=0,
                      padx=8, pady=4, font=("Segoe UI", 9))
        label.pack()
        
        # XML-like border using frame or just background
        tw.configure(background=ACCENT_COLOR, padx=1, pady=1)

    def hide_tip(self, event=None):
        self.unschedule()
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

class MasterDashboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Surasura - Immersion Architect Dashboard v{__version__}")
        self.root.geometry("520x650") 
        self.root.resizable(True, True)
        self.root.minsize(520, 550)
        self.root.configure(bg=BG_COLOR)
        

        
        self.style = ttk.Style()
        self.apply_dark_theme()
        
        # Initialize variables for Analyzer settings
        self.var_exclude_single = tk.BooleanVar(value=True) 
        self.var_min_freq = tk.IntVar(value=1) 
        self.var_open_app_mode = tk.BooleanVar(value=False)
        self.var_strategy = tk.StringVar(value="freq")
        self.var_target_coverage = tk.IntVar(value=90)
        self.var_split_length = tk.IntVar(value=3000)
        self.var_language = tk.StringVar(value="ja")
        self.var_reinforce = tk.BooleanVar(value=False) # For Chinese forced segmentation
        self.var_inline_completed = tk.BooleanVar(value=False) # Show completed files inline
        self.var_telemetry_enabled = tk.BooleanVar(value=True) # Anonymous Telemetry
        self.var_only_i_plus_one = tk.BooleanVar(value=False) # Only include i+1 sentences
        self.var_add_graduated = tk.BooleanVar(value=True) # Add words on graduate
        self.var_context_min_chars = tk.IntVar(value=10)
        self.var_context_max_chars = tk.IntVar(value=50)
        self.var_words_per_day = tk.IntVar(value=5) # Target words per day
        self.var_show_words_per_day = tk.BooleanVar(value=True) # Show target days calculation
        self.var_zen_limit = tk.IntVar(value=50) # Default Zen Limit
        self.onboarding_completed = tk.BooleanVar(value=False)
        self.var_open_count = tk.IntVar(value=0)
        self.var_hide_satoru = tk.BooleanVar(value=False)
        self.var_hide_audio = tk.BooleanVar(value=False)
        self.var_enable_youtube = tk.BooleanVar(value=False)
        self.youtube_risk_acknowledged = False
        self.var_enable_preview = tk.BooleanVar(value=False)
        self.var_auto_update = tk.BooleanVar(value=True) # One-click in-place updates
        self._lock_ui_updates = False

        # Update state (populated by the background check; consumed by the footer indicator)
        self._update_info = None
        self._update_class = "NONE"
        self.skipped_version = ""
        self.update_label: Optional[ttk.Label] = None

        # Initialize status var early to satisfy linter
        self.status_var = tk.StringVar(value="Ready")
        self.terminal: Optional[tk.Text] = None
        self.spinner: Optional[ttk.Progressbar] = None
        self.settings_window: Optional[tk.Toplevel] = None
        self.btn_satori: Optional[ttk.Button] = None
        self.btn_youtube: Optional[ttk.Button] = None
        self.btn_preview: Optional[ttk.Button] = None
        self.lang_frame: Optional[ttk.Frame] = None
        self.lang_options_frame: Optional[ttk.Frame] = None
        self.chk_reinforce_widget: Optional[ttk.Checkbutton] = None
        self.max_contexts_frame: Optional[ttk.Frame] = None
        self.context_range_frame: Optional[ttk.Frame] = None
        self.wpd_frame: Optional[ttk.Frame] = None
        
        # Logic Settings (Magic Numbers)
        self.logic_settings = {}
        
        # Queue for thread-safe GUI updates
        self.gui_queue = queue.Queue()
        self.check_queue()

        # Track active child processes
        self.active_processes = []

        # Set Application Icon
        try:
            from app.path_utils import get_icon_path, get_ico_path
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                self.icon_photo = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, self.icon_photo) # True applies to all windows
                
                # Header Logo (Small version)
                # 512 / 12 ~= 42px. Good for header.
                self.logo_header = self.icon_photo.subsample(12, 12)
            
            # Windows Taskbar Icon - iconbitmap is often more reliable
            if sys.platform == "win32":
                ico_path = get_ico_path()
                if os.path.exists(ico_path):
                    self.root.iconbitmap(ico_path)
                    
        except Exception as e:
            print(f"Warning: Could not set icon: {e}")

        self.setup_ui()
        
        # Load saved settings
        self.load_settings()

        # Show onboarding if not completed
        if not self.onboarding_completed.get():
            try:
                from app.onboarding_gui import OnboardingGuide
                self.root.after(500, lambda: OnboardingGuide(self.root, self.complete_onboarding))
            except Exception as e:
                print(f"Warning: Could not show onboarding: {e}")
        
        # Add traces for auto-saving settings after initial load
        self.var_exclude_single.trace_add("write", self.save_settings)
        self.var_min_freq.trace_add("write", self.save_settings)
        self.var_open_app_mode.trace_add("write", self.save_settings)
        self.var_inline_completed.trace_add("write", self.save_settings)
        self.var_telemetry_enabled.trace_add("write", self.save_settings)
        self.var_only_i_plus_one.trace_add("write", self.save_settings)
        self.var_add_graduated.trace_add("write", self.save_settings)
        self.var_words_per_day.trace_add("write", self.save_settings)
        self.var_show_words_per_day.trace_add("write", self.save_settings)
        self.var_zen_limit.trace_add("write", self.save_settings) # Added trace for zen limit
        self.var_hide_audio.trace_add("write", self.save_settings)
        self.var_hide_satoru.trace_add("write", lambda n, i, m: self.update_satori_visibility())
        self.var_enable_youtube.trace_add("write", self.save_settings)
        self.var_enable_youtube.trace_add("write", lambda n, i, m: self.update_youtube_visibility())
        self.var_enable_preview.trace_add("write", self.save_settings)
        self.var_enable_preview.trace_add("write", lambda n, i, m: self.update_preview_visibility())
        self.var_auto_update.trace_add("write", self.save_settings)
        self.combo_theme.bind("<<ComboboxSelected>>", self.save_settings)

        # Reconcile the result of any update applied since we last ran (toast / manual-retry).
        self.root.after(800, self.reconcile_update_result)

        # Start update check in background
        threading.Thread(target=self.check_updates_thread, daemon=True).start()
        
        # Initial UI update for language
        self.update_ui_for_language()
        
        # Trace language changes
        self.var_language.trace_add("write", lambda *args: self.update_ui_for_language())

        # Bind close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def check_queue(self):
        """Poll the queue for GUI updates"""
        try:
            while True:
                task = self.gui_queue.get_nowait()
                if callable(task):
                    task()
                self.gui_queue.task_done()
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_queue)
        
    def apply_dark_theme(self):
        self.style.theme_use('default')
        
        # Cross-platform Fix for TCombobox Dropdown (Listbox) Visibility
        self.root.option_add('*TCombobox*Listbox.background', SURFACE_COLOR)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectBackground', ACCENT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectForeground', BG_COLOR)
        self.root.option_add('*TCombobox*Listbox.font', ('Segoe UI', 10))
        
        # General
        self.style.configure(".", 
            background=BG_COLOR, 
            foreground=TEXT_COLOR, 
            fieldbackground=SURFACE_COLOR,
            font=('Segoe UI', 10)
        )
        
        # Frames and Labelframes
        self.style.configure("TFrame", background=BG_COLOR)
        self.style.configure("TLabelframe", background=BG_COLOR, bordercolor=SURFACE_COLOR)
        self.style.configure("TLabelframe.Label", background=BG_COLOR, foreground=ACCENT_COLOR, font=('Segoe UI', 11, 'bold'))
        
        # Label
        self.style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR)
        self.style.configure("Header.TLabel", font=('Segoe UI', 18, 'bold'), foreground=SECONDARY_COLOR)
        self.style.configure("Footer.TLabel", font=('Segoe UI', 8), foreground="#666")
        self.style.configure("Link.TLabel", font=('Segoe UI', 8, 'underline'), foreground=ACCENT_COLOR)
        
        # Checkbutton
        self.style.configure("TCheckbutton", background=BG_COLOR, foreground=TEXT_COLOR)
        self.style.map("TCheckbutton",
            background=[('active', BG_COLOR)],
            foreground=[('active', ACCENT_COLOR)]
        )
        # Radiobutton
        self.style.configure("TRadiobutton", background=BG_COLOR, foreground=TEXT_COLOR, focuscolor=ACCENT_COLOR)
        self.style.map("TRadiobutton",
            foreground=[('active', TEXT_COLOR)],
            background=[('active', BG_COLOR)]
        )
        # Entry
        self.style.configure("TEntry",
            fieldbackground=SURFACE_COLOR,
            foreground=TEXT_COLOR,
            insertbackground=TEXT_COLOR, # Cursor color
            bordercolor=ACCENT_COLOR,
            lightcolor=ACCENT_COLOR,
            darkcolor=ACCENT_COLOR,
            selectbackground=ACCENT_COLOR,
            selectforeground=BG_COLOR
        )
        # Buttons
        self.style.configure("TButton", 
            background=SURFACE_COLOR, 
            foreground=TEXT_COLOR, 
            borderwidth=0,
            padding=8,
            font=('Segoe UI', 10, 'bold')
        )
        self.style.map("TButton",
            background=[('active', ACCENT_COLOR), ('pressed', ACCENT_COLOR)],
            foreground=[('active', BG_COLOR), ('pressed', BG_COLOR)]
        )

        # Progressbar
        self.style.configure("TProgressbar", thickness=4, background=ACCENT_COLOR, troughcolor=SURFACE_COLOR, borderwidth=0)
        
        # Combobox Styling (Fix for theme text visibility)
        self.style.configure("TCombobox", 
            fieldbackground=SURFACE_COLOR, 
            background=SURFACE_COLOR,
            foreground=TEXT_COLOR,
            arrowcolor=ACCENT_COLOR
        )
        self.style.map("TCombobox",
            fieldbackground=[('readonly', SURFACE_COLOR)],
            foreground=[('readonly', TEXT_COLOR)]
        )
        
        # Specific Button Styles
        self.style.configure("Action.TButton", width=24)
        # YouTube button: small, red play glyph that stays red on hover/press
        self.style.configure("Youtube.TButton", foreground="#ff0000")
        self.style.map("Youtube.TButton", foreground=[('active', "#ff0000"), ('pressed', "#ff0000")])

    def update_strategy_ui(self):
        strategy = self.var_strategy.get()
        if strategy == "freq":
            self.freq_frame.pack(side=tk.TOP, fill=tk.X)
            self.coverage_frame.pack_forget()
        else:
            self.freq_frame.pack_forget()
            self.coverage_frame.pack(side=tk.TOP, fill=tk.X)
            self.save_settings() # Save on switch
            
    def update_ui_for_language(self):
        """Updates UI elements based on selected language"""
        if getattr(self, '_lock_ui_updates', False):
            return
            
        self._lock_ui_updates = True
        try:
            lang = self.var_language.get()
            
            # 1. Update Flag Icon
            if hasattr(self, 'lbl_flag'):
                 flag_icon = "🇨🇳" if lang == "zh" else "🇯🇵"
                 self.lbl_flag.config(text=flag_icon)
    
            # 2. Update Tool/Button visibility
            if lang == 'zh':
                if hasattr(self, 'btn_jiten'):
                    self.btn_jiten.pack_forget()
            else:
                if hasattr(self, 'btn_jiten'):
                    # Re-insert in correct position (after migaku)
                    self.btn_jiten.pack(side=tk.LEFT, padx=(0, 5), after=self.btn_migaku)
                if hasattr(self, 'btn_anki'):
                    self.btn_anki.pack(side=tk.LEFT, padx=(0, 10), after=self.btn_jiten)
    
            # 3. Update Settings Toggles (if window created)
            if self.settings_window and self.settings_window.winfo_exists():
                if self.chk_reinforce_widget:
                    self.chk_reinforce_widget.pack_forget()

                if lang == 'zh':
                    # Show Reinforce for Chinese
                    if self.chk_reinforce_widget:
                        self.chk_reinforce_widget.pack(anchor=tk.W)
                        self.chk_reinforce_widget.configure(state='normal')
                else:
                    self.var_reinforce.set(False)
    
            self.save_settings()
        finally:
            self._lock_ui_updates = False
        
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="15") # Reduced padding 25 -> 15
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(pady=(0, 10)) # Reduced pady 20 -> 10
        
        if hasattr(self, 'logo_header'):
            logo_label = ttk.Label(header_frame, image=self.logo_header)
            logo_label.pack(side=tk.LEFT, padx=(0, 10))
            
        header_text = ttk.Label(header_frame, text="Surasura - Immersion Architect", style="Header.TLabel")
        header_text.pack(side=tk.LEFT)
        
        # 1. Vocabulary Tools
        vocab_frame = ttk.LabelFrame(main_frame, text=" 📚 Import Known Vocabulary", padding="10")
        vocab_frame.pack(fill=tk.X, pady=(0, 5)) # Reduced pady 10 -> 5
        
        # Single Row: [Migaku] [Jiten] [Edit Ignore List (fills rest)]
        vocab_row = ttk.Frame(vocab_frame)
        vocab_row.pack(fill=tk.X)

        self.btn_migaku = ttk.Button(vocab_row, text="Migaku", width=12,
                   command=self.run_migaku_importer)
        self.btn_migaku.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(self.btn_migaku, "Import known words from Migaku database export.")

        self.btn_jiten = ttk.Button(vocab_row, text="Jiten", width=12,
                   command=self.run_jiten_importer)
        self.btn_jiten.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(self.btn_jiten, "Import known words from Jiten API using your API key.")

        self.btn_anki = ttk.Button(vocab_row, text="Anki", width=12,
                   command=self.run_anki_importer)
        self.btn_anki.pack(side=tk.LEFT, padx=(0, 10))
        ToolTip(self.btn_anki, "Create a known-word list from an Anki deck field.")
        
        # This button expands to fill all remaining space
        btn_ignore = ttk.Button(vocab_row, text="Edit Ignore List", style="Action.TButton",
                     command=self.open_ignore_list)
        btn_ignore.pack(side=tk.LEFT, expand=True, fill=tk.X)
        ToolTip(btn_ignore, "Open your IgnoreList.txt to manually edit excluded words.")

        # 2. Library Tools
        lib_frame = ttk.LabelFrame(main_frame, text=" 📦 Library Content", padding="10")
        lib_frame.pack(fill=tk.X, pady=(0, 5)) # Reduced pady 10 -> 5

        btn_open_data = ttk.Button(lib_frame, text="Import Content", style="Action.TButton",
                                    command=self.run_content_importer)
        btn_open_data.pack(side=tk.LEFT, padx=(0, 5), expand=True, fill=tk.X)
        ToolTip(btn_open_data, "Launch the wizard to import content into priority folders.")

        btn_epub = ttk.Button(lib_frame, text="Extract / Splice", style="Action.TButton", 
                   command=self.run_file_importer)
        btn_epub.pack(side=tk.LEFT, padx=(0, 5), expand=True, fill=tk.X)
        ToolTip(btn_epub, "Import and split EPUB, TXT, MD, or SRT files for analysis.")

        # YouTube Transcripts (optional module): small red play button, right of Extract / Splice.
        # Packed/unpacked by update_youtube_visibility() based on the settings toggle + module presence.
        self.btn_youtube = ttk.Button(lib_frame, text="▶", style="Youtube.TButton", width=3,
                                      command=self.open_youtube_downloader)
        ToolTip(self.btn_youtube, "YouTube Transcripts — download captions into your Processed folder.")

        # 3. Analyzer Tools
        analyze_frame = ttk.LabelFrame(main_frame, text=" 🔍 Analysis", padding="10")
        analyze_frame.pack(fill=tk.X, pady=(0, 5)) # Reduced pady 10 -> 5

        # Strategy Selection
        strategy_frame = ttk.Frame(analyze_frame)
        strategy_frame.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Label(strategy_frame, text="Generation Mode:").pack(side=tk.LEFT)
        ttk.Radiobutton(strategy_frame, text="Min Frequency", variable=self.var_strategy, value="freq", command=self.update_strategy_ui).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Radiobutton(strategy_frame, text="Target % Coverage", variable=self.var_strategy, value="coverage", command=self.update_strategy_ui).pack(side=tk.LEFT, padx=(10, 0))

        # Dynamic Options Frame
        self.options_container = ttk.Frame(analyze_frame)
        self.options_container.pack(fill=tk.X, pady=(0, 8))

        # 1. Frequency Slider (Default)
        self.freq_frame = ttk.Frame(self.options_container)
        
        ttk.Label(self.freq_frame, text="Min Frequency:").pack(side=tk.LEFT)
        freq_slider = tk.Scale(self.freq_frame, from_=1, to=10, orient=tk.HORIZONTAL, 
                               variable=self.var_min_freq, showvalue=False,
                               bg=BG_COLOR, fg=TEXT_COLOR, highlightthickness=0,
                               activebackground=ACCENT_COLOR, troughcolor=SURFACE_COLOR)
        freq_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        ttk.Label(self.freq_frame, textvariable=self.var_min_freq, width=2).pack(side=tk.LEFT)
        ToolTip(self.freq_frame, "Show words with this frequency or higher. Default is 1 (shows all words).")

        # 2. Coverage Entry (Hidden initially)
        self.coverage_frame = ttk.Frame(self.options_container)
        
        ttk.Label(self.coverage_frame, text="Target Coverage (%):").pack(side=tk.LEFT)
        ttk.Entry(self.coverage_frame, textvariable=self.var_target_coverage, width=5).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Label(self.coverage_frame, text="(e.g. 90, 95)").pack(side=tk.LEFT, padx=(5, 0))
        ToolTip(self.coverage_frame, "Generate a word list to reach this cumulative coverage % across all selected files.")

        # Initialize UI state
        self.update_strategy_ui()

        # Run Analyzer Button (+ optional small red YouTube Preview button to its right)
        analyze_row = ttk.Frame(analyze_frame)
        analyze_row.pack(fill=tk.X)
        btn_analyze = ttk.Button(analyze_row, text="Generate Journey", style="Action.TButton",
                                 command=self.run_analyzer)
        btn_analyze.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ToolTip(btn_analyze, "Analyze text files and generate readability report. Auto-launches static page.")

        self.btn_preview = ttk.Button(analyze_row, text="▷", style="Youtube.TButton", width=3,
                                      command=self.open_youtube_preview)
        ToolTip(self.btn_preview, "Preview a YouTube video/playlist against your library (quick look, no full re-run).")

        # Spinner (Initially hidden)
        self.spinner = ttk.Progressbar(analyze_frame, mode='indeterminate', style="TProgressbar")
        
        # 4. Results Viewer
        view_frame = ttk.LabelFrame(main_frame, text=" 📊 Results Viewer", padding="10")
        view_frame.pack(fill=tk.X, pady=(0, 2)) # Further reduced pady

        # Theme Selector and App Mode Toggle
        theme_app_frame = ttk.Frame(view_frame)
        theme_app_frame.pack(fill=tk.X, pady=(0, 8))

        themes = ['Default (Dark)', 'Dark Flow', 'Midnight (Vibrant)', 'Modern Light', 'Zen Mode']
        self.combo_theme = ttk.Combobox(theme_app_frame, values=themes, state="readonly", width=20)
        self.combo_theme.set('Dark Flow')
        self.combo_theme.pack(side=tk.LEFT)
        ToolTip(self.combo_theme, "Select the visual theme for the generated reading list.")
        
        chk_app_mode = ttk.Checkbutton(theme_app_frame, text="Open in New Window", variable=self.var_open_app_mode)
        chk_app_mode.pack(side=tk.LEFT, padx=(20, 0))
        ToolTip(chk_app_mode, "RECOMMENDS keeping it off until the migaku or lookupextension is turned on for that site.")
        
        # Zen Mode Limit Slider (Main GUI)
        zen_limit_frame = ttk.Frame(view_frame)
        zen_limit_frame.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Label(zen_limit_frame, text="Zen Limit:").pack(side=tk.LEFT)
        zen_slider_main = tk.Scale(zen_limit_frame, from_=25, to=125, orient=tk.HORIZONTAL, 
                                   variable=self.var_zen_limit, showvalue=False,
                                   bg=BG_COLOR, fg=TEXT_COLOR, highlightthickness=0,
                                   activebackground=ACCENT_COLOR, troughcolor=SURFACE_COLOR, length=300)
        zen_slider_main.pack(side=tk.LEFT, padx=(5, 10))
        ToolTip(zen_slider_main, "Limit words for Zen Mode (25-125).")
        
        # Value Label on the right
        ttk.Label(zen_limit_frame, textvariable=self.var_zen_limit, width=4).pack(side=tk.LEFT)
        btn_static = ttk.Button(view_frame, text="View Vocab Journey", style="Action.TButton", 
                   command=self.run_static_page)
        btn_static.pack(anchor=tk.W, fill=tk.X)
        ToolTip(btn_static, "Refresh and open your personalized learning path in the web browser.")
        
        # Footer
        footer_frame = ttk.Frame(self.root, padding=(10, 0)) # Zero vertical padding for footer
        footer_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Status Bar
        status_bar = ttk.Label(footer_frame, textvariable=self.status_var, style="Footer.TLabel")
        status_bar.pack(side=tk.LEFT)

        # Update indicator (bottom-left, hidden until the background check finds an update).
        # Non-blocking: clicking it opens the update dialog; the app is never interrupted.
        self.update_label = ttk.Label(footer_frame, text="", style="Link.TLabel", cursor="hand2")
        self.update_label.bind("<Button-1>", lambda e: self.open_update_dialog())
        
        # Credit
        credit_box = ttk.Frame(footer_frame)
        credit_box.pack(side=tk.RIGHT)
        
        ttk.Label(credit_box, text="Created by SonicSandbox | ", style="Footer.TLabel").pack(side=tk.LEFT)
        self.github_link = ttk.Label(credit_box, text="GitHub", style="Link.TLabel", cursor="hand2")
        self.github_link.pack(side=tk.LEFT)
        # UPDATED LINK to the new repo
        self.github_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/SonicSandbox/surasura"))

        ttk.Label(credit_box, text=" | ", style="Footer.TLabel").pack(side=tk.LEFT)
        self.tutorial_link = ttk.Label(credit_box, text="Tutorial", style="Link.TLabel", cursor="hand2")
        self.tutorial_link.pack(side=tk.LEFT)
        self.tutorial_link.bind("<Button-1>", lambda e: self.open_tutorial())

        # Language Flag
        self.lbl_flag = ttk.Label(credit_box, text="🇯🇵", font=("Segoe UI Emoji", 10))
        self.lbl_flag.pack(side=tk.LEFT, padx=(10, 0))

        # Settings Button (Icon only, Bottom Right)
        # Use a simple gear unicode or similar if no image
        btn_settings = ttk.Button(credit_box, text="⚙", command=self.toggle_settings_window, width=3)
        btn_settings.pack(side=tk.LEFT, padx=(10, 0))
        ToolTip(btn_settings, "Open Settings & Logs")

        # Immersion Architect (Satori) Button
        self.btn_satori = ttk.Button(credit_box, text="悟", command=self.open_immersion_architect, width=3)
        if not self.var_hide_satoru.get():
            self.btn_satori.pack(side=tk.LEFT, padx=(5, 0))
        ToolTip(self.btn_satori, "Immersion Architect Intelligence")

    def complete_onboarding(self):
        # Reload to get the settings written by the onboarding window
        self.load_settings()
        # Mark as completed and save everything back
        self.onboarding_completed.set(True)
        self.update_ui_for_language() # Force UI update and save

    def create_settings_window(self):
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Settings & Logs")
        self.settings_window.geometry("850x580")
        self.settings_window.protocol("WM_DELETE_WINDOW", self.toggle_settings_window)
        
        # Bind Escape to hide the settings window
        self.settings_window.bind("<Escape>", lambda e: self.toggle_settings_window())
        
        self.settings_window.withdraw() # Hide initially
        
        # Apply theme to settings window too (requires style sharing which ttk does automatically for same root)
        self.settings_window.configure(bg=BG_COLOR)

        # Main Container
        main_container = ttk.Frame(self.settings_window, padding="15")
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Header (Follow Design Language but centered and smaller)
        self.style.configure("SettingsHeader.TLabel", font=('Segoe UI', 14, 'bold'), foreground=SECONDARY_COLOR)
        ttk.Label(main_container, text="Advanced Settings", style="SettingsHeader.TLabel").pack(pady=(0, 15))

        # Settings Grid
        grid_frame = ttk.Frame(main_container)
        grid_frame.pack(fill=tk.X)
        grid_frame.columnconfigure(0, weight=2, uniform="settings_col") # Strictly 2:1
        grid_frame.columnconfigure(1, weight=1, uniform="settings_col")

        # --- LEFT COLUMN (Col 0) ---
        
        # 1. 🌐 Language & Parsing
        group_lang = ttk.LabelFrame(grid_frame, text=" 🌐 Language & Parsing", padding="10")
        group_lang.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=5)

        # Language Selection
        self.lang_frame = ttk.Frame(group_lang)
        self.lang_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(self.lang_frame, text="Target Language:").pack(side=tk.LEFT)
        ttk.Radiobutton(self.lang_frame, text="Japanese (日本語)", variable=self.var_language, value="ja", command=self.save_settings).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(self.lang_frame, text="Chinese (中文)", variable=self.var_language, value="zh", command=self.save_settings).pack(side=tk.LEFT)

        # Language Specific Options Container (Indented)
        self.lang_options_frame = ttk.Frame(group_lang)
        self.lang_options_frame.pack(fill=tk.X, padx=(10, 0), pady=(0, 5))

        # Reinforce Segmentation (Chinese)
        self.chk_reinforce_widget = ttk.Checkbutton(self.lang_options_frame, text="Reinforce Chinese Seg", variable=self.var_reinforce, command=self.save_settings)
        ToolTip(self.chk_reinforce_widget, "Forces splitting of common collocations like '就把' -> '就', '把'.")

        chk_single = ttk.Checkbutton(group_lang, text="Exclude 1-character words", variable=self.var_exclude_single)
        chk_single.pack(anchor=tk.W)
        ToolTip(chk_single, "Ignore 1-char words (Recommended)")

        # Split Length Setting
        split_frame = ttk.Frame(group_lang)
        split_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(split_frame, text="Split Length:").pack(side=tk.LEFT)
        ttk.Entry(split_frame, textvariable=self.var_split_length, width=8).pack(side=tk.LEFT, padx=5)
        self.var_split_length.trace_add("write", self.save_settings)
        ToolTip(split_frame, "Default character limit for splitting files.")

        # YouTube toggles (optional module) — grouped with Language & Parsing.
        # Only shown when the module is present locally.
        try:
            import modules.youtube_downloader  # noqa: F401
            _yt_module_available = True
        except Exception:
            _yt_module_available = False
        if _yt_module_available:
            chk_youtube = ttk.Checkbutton(group_lang, text="Enable YouTube Transcripts", variable=self.var_enable_youtube)
            chk_youtube.pack(anchor=tk.W, pady=(10, 0))
            ToolTip(chk_youtube, "Show a YouTube transcript downloader in Library Content. Also controls whether it is bundled when you build the app.")

            chk_preview = ttk.Checkbutton(group_lang, text="Enable YouTube Preview", variable=self.var_enable_preview)
            chk_preview.pack(anchor=tk.W, pady=(4, 0))
            ToolTip(chk_preview, "Show a 'Preview against library' button next to Generate Journey, and cache a library frequency map on runs so the preview is fast.")

        # 2. 📊 Experience & UI
        group_ui = ttk.LabelFrame(grid_frame, text=" 📊 Experience & UI", padding="10")
        group_ui.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=5)

        chk_inline = ttk.Checkbutton(group_ui, text="Show 'Target Met' inline", variable=self.var_inline_completed)
        chk_inline.pack(anchor=tk.W)
        ToolTip(chk_inline, "Keep met files in order instead of moving them down.")

        chk_hide_audio = ttk.Checkbutton(group_ui, text="Hide Audio Button (Speaker)", variable=self.var_hide_audio)
        chk_hide_audio.pack(anchor=tk.W)
        ToolTip(chk_hide_audio, "Hide speaker icon in the report.")

        # Words Per Day Settings
        self.wpd_frame = ttk.Frame(group_ui)
        self.wpd_frame.pack(fill=tk.X, pady=(5, 0))
        chk_show_wpd = ttk.Checkbutton(self.wpd_frame, text="Show 'Target Days'", variable=self.var_show_words_per_day)
        chk_show_wpd.pack(anchor=tk.W)
        
        wpd_entry_frame = ttk.Frame(self.wpd_frame)
        wpd_entry_frame.pack(fill=tk.X)
        ttk.Label(wpd_entry_frame, text="Words Per Day:").pack(side=tk.LEFT)
        ttk.Entry(wpd_entry_frame, textvariable=self.var_words_per_day, width=5).pack(side=tk.LEFT, padx=(5, 0))
        ToolTip(self.wpd_frame, "Your daily target for completion estimates.")

        # 3. 🧠 Sentences & Logic
        group_logic = ttk.LabelFrame(grid_frame, text=" 🧠 Sentences & Logic", padding="10")
        group_logic.grid(row=2, column=0, sticky="nsew", padx=(0, 5), pady=5)

        # Ideal Sentence Range
        self.context_range_frame = ttk.Frame(group_logic)
        self.context_range_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(self.context_range_frame, text="Sentence range:").pack(side=tk.LEFT)
        ttk.Entry(self.context_range_frame, textvariable=self.var_context_min_chars, width=4).pack(side=tk.LEFT, padx=(5, 2))
        ttk.Label(self.context_range_frame, text="to").pack(side=tk.LEFT)
        ttk.Entry(self.context_range_frame, textvariable=self.var_context_max_chars, width=4).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Label(self.context_range_frame, text="chars").pack(side=tk.LEFT, padx=(5, 0))
        ToolTip(self.context_range_frame, "Preferred min/max length for context sentences.")
        
        def _validate_context_range(*args):
             try:
                 min_val = self.var_context_min_chars.get()
                 max_val = self.var_context_max_chars.get()
             except tk.TclError:
                 return # Still typing invalid char
             if min_val > max_val:
                 self.var_context_max_chars.set(min_val)
             self.save_settings()
             
        self.var_context_min_chars.trace_add("write", _validate_context_range)
        self.var_context_max_chars.trace_add("write", _validate_context_range)

        # Max Context Sentences
        self.max_contexts_frame = ttk.Frame(group_logic)
        self.max_contexts_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(self.max_contexts_frame, text="Max Sentences:").pack(side=tk.LEFT)
        if not hasattr(self, 'var_max_contexts') or not self.var_max_contexts:
            self.var_max_contexts = tk.IntVar(value=self.logic_settings.get("context", {}).get("max_contexts", 3))
        spin_max_contexts = ttk.Spinbox(self.max_contexts_frame, from_=1, to=10, textvariable=self.var_max_contexts, width=4, command=self.save_settings)
        spin_max_contexts.pack(side=tk.LEFT, padx=(5, 0))
        ToolTip(self.max_contexts_frame, "Maximum context sentences per word.")

        chk_i_plus_one = ttk.Checkbutton(group_logic, text="Only include i+1 sentences", variable=self.var_only_i_plus_one)
        chk_i_plus_one.pack(anchor=tk.W)
        ToolTip(chk_i_plus_one, "Swaps a word's media sentence for an i+1 example (only that word is new) when it isn't already i+1.")

        chk_add_graduated = ttk.Checkbutton(group_logic, text="Add Words on 'Graduate'", variable=self.var_add_graduated)
        chk_add_graduated.pack(anchor=tk.W)
        ToolTip(chk_add_graduated, "Uncheck to skip vocab extraction when graduating files.")


        # --- RIGHT COLUMN (Col 1) ---

        # 4. 🧮 Data & System
        group_data = ttk.LabelFrame(grid_frame, text=" 🧮 Data & System", padding="10")
        group_data.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=5)

        chk_telemetry = ttk.Checkbutton(group_data, text="Enable Anonymous Telemetry", variable=self.var_telemetry_enabled)
        chk_telemetry.pack(anchor=tk.W, pady=(0, 10))
        ToolTip(chk_telemetry, "Send anonymous usage stats.")

        chk_auto_update = ttk.Checkbutton(group_data, text="Automatic Updates", variable=self.var_auto_update)
        chk_auto_update.pack(anchor=tk.W, pady=(0, 10))
        ToolTip(chk_auto_update, "Offer one-click in-app updates for minor releases. Major updates always download manually.")

        btn_anki_sentences = ttk.Button(group_data, text="Generate Sentence List", command=self.generate_anki_sentence_warning, width=20)
        btn_anki_sentences.pack(fill=tk.X, pady=(0, 5))
        ToolTip(btn_anki_sentences, "Export an Anki-compatible CSV with sentences from your report.")

        # Frequency List Manager & Exporter
        btn_freq = ttk.Button(group_data, text="Add Frequency List", command=self.run_frequency_list_manager, width=20)
        btn_freq.pack(fill=tk.X, pady=(0, 5))
        ToolTip(btn_freq, "Manage custom frequency lists.")

        btn_export_freq = ttk.Button(group_data, text="Export Freq List", command=self.generate_frequency_list, width=20)
        btn_export_freq.pack(fill=tk.X)
        ToolTip(btn_export_freq, "Export internal frequency list for Migaku/Yomitan.")

        # 5. 📜 Processing Log (Right Side)
        log_frame = ttk.LabelFrame(grid_frame, text=" 📜 Processing Log", padding="10")
        log_frame.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(5, 0), pady=5)

        self.terminal = tk.Text(log_frame, height=3, width=1, bg=SURFACE_COLOR, fg=TEXT_COLOR, 
                                insertbackground=TEXT_COLOR, font=("Consolas", 9),
                                relief=tk.FLAT, borderwidth=0, state=tk.DISABLED,
                                wrap=tk.NONE)
        self.terminal.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.terminal.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.terminal.config(yscrollcommand=scrollbar.set)

        # Initial visibility set by update_ui
        self.update_ui_for_language()
        
    def toggle_settings_window(self):
        if self.settings_window is None or not self.settings_window.winfo_exists():
            self.create_settings_window()
            
        if self.settings_window.state() == "withdrawn":
            self.settings_window.deiconify()
            self.settings_window.lift()
        else:
            self.settings_window.withdraw()

    def open_immersion_architect(self):
        try:
            from modules.immersion_architect.gui import ImmersionArchitectGui
            # Create if not exists or if destroyed
            if not hasattr(self, 'satori_window') or self.satori_window is None or not self.satori_window.winfo_exists():
                self.satori_window = ImmersionArchitectGui(self.root)
            else:
                self.satori_window.lift()
        except Exception as e:
            print(f"Error launching Immersion Architect: {e}")
            messagebox.showerror("Error", f"Could not launch Immersion Architect:\n{e}")

    def check_updates_thread(self):
        """Background thread: check GitHub, classify, and surface a non-blocking indicator.

        The network is entirely optional here — any failure (offline, timeout, no release)
        leaves the app running normally with no indicator. The decision to update is always
        the user's; this only lights the footer.
        """
        try:
            info = get_update_info()
            cls = classify_update(__version__, info)
            # Apply the kill-switch / anti-loop guard using saved settings (thread-safe: we
            # read the plain dict, not tk vars). A disabled toggle, a missing updater.exe, or
            # a version that already failed/was skipped downgrades an APP update to manual.
            cur = getattr(self, "_current_settings", {}) or {}
            cls = updater.effective_class(
                cls, info,
                skipped_version=cur.get("skipped_version", ""),
                auto_enabled=cur.get("auto_update_enabled", True),
                can_apply=updater.can_auto_apply(),
            )
            if cls == "NONE" or info is None:
                return
            self._update_info = info
            self._update_class = cls
            self.gui_queue.put(self._show_update_indicator)
        except Exception as e:
            print(f"Update check failed: {e}")

    def _show_update_indicator(self):
        """Light the bottom-left update indicator (and status bar). Never blocks."""
        info = self._update_info
        if not info:
            return
        self.update_label.config(text=f"⬆ Update available (v{info.version})", foreground=ACCENT_COLOR)
        if not self.update_label.winfo_ismapped():
            self.update_label.pack(side=tk.LEFT, padx=(12, 0))
        self.status_var.set(f"Update available: v{info.version}")
        # A critical release escalates once to an opened dialog; the user still chooses.
        if getattr(info, "critical", False):
            self.open_update_dialog()

    def open_update_dialog(self):
        """Small themed dialog offering the update. Buttons depend on the update class."""
        info = self._update_info
        if not info:
            return
        cls = self._update_class

        dialog = tk.Toplevel(self.root)
        dialog.title("Update Available")
        dialog.geometry("440x260")
        dialog.resizable(False, False)
        dialog.configure(bg=BG_COLOR)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

        wrapper = ttk.Frame(dialog, padding=20)
        wrapper.pack(fill=tk.BOTH, expand=True)

        ttk.Label(wrapper, text=f"Surasura v{info.version} is available",
                  font=('Segoe UI', 13, 'bold'), foreground=SECONDARY_COLOR,
                  background=BG_COLOR).pack(anchor=tk.W, pady=(0, 8))

        if cls == "APP":
            body = ("This is a quick in-app update — it refreshes only the program code and "
                    "report templates (a few hundred KB). Your words, data, settings, and file "
                    "order are never touched. Surasura will briefly close and reopen.")
        else:
            body = ("This is a larger update and should be downloaded manually (it changes more "
                    "than the app code). Your personal data stays where it is.")
        ttk.Label(wrapper, text=body, wraplength=400, justify=tk.LEFT,
                  foreground=TEXT_COLOR, background=BG_COLOR, font=('Segoe UI', 10)).pack(anchor=tk.W, pady=(0, 16))

        btn_row = ttk.Frame(wrapper)
        btn_row.pack(fill=tk.X)

        if cls == "APP":
            btn_now = ttk.Button(btn_row, text="Update now", style="Action.TButton",
                                 command=lambda: self._do_auto_update(dialog))
            btn_now.pack(side=tk.LEFT)
            ToolTip(btn_now, "Download and install this update, then reopen Surasura.")
            btn_skip = ttk.Button(btn_row, text="Skip this version",
                                  command=lambda: self._skip_update(dialog))
            btn_skip.pack(side=tk.LEFT, padx=(8, 0))
            ToolTip(btn_skip, "Don't offer this version again.")
        else:
            btn_dl = ttk.Button(btn_row, text="Download", style="Action.TButton",
                                command=lambda: (webbrowser.open(info.notes_url), dialog.destroy()))
            btn_dl.pack(side=tk.LEFT)
            ToolTip(btn_dl, "Open the download page in your browser.")

        ttk.Button(btn_row, text="Later", command=dialog.destroy).pack(side=tk.RIGHT)

    def _skip_update(self, dialog):
        """Remember this version so it is never auto-offered again, and hide the indicator."""
        info = self._update_info
        if info:
            self.skipped_version = info.version
            self.save_settings()
        if self.update_label:
            self.update_label.pack_forget()
        self.status_var.set("Ready")
        dialog.destroy()

    def _do_auto_update(self, dialog):
        """Download+verify the app package on a worker thread, then arm+restart on the UI thread."""
        dialog.destroy()
        info = self._update_info
        if not info:
            return
        if not updater.can_auto_apply():
            # No bundled updater.exe (e.g. running from source) — fall back to manual.
            webbrowser.open(info.notes_url)
            return

        self.status_var.set("Downloading update…")

        def worker():
            try:
                marker = updater.prepare_update(info)
            except Exception as e:
                self.gui_queue.put(lambda: messagebox.showerror(
                    "Update",
                    f"Couldn't download the update:\n{e}\n\n"
                    "You can try again later, or update manually from the releases page."))
                self.gui_queue.put(lambda: self.status_var.set("Ready"))
                return
            # Arming + closing the app must happen on the main (UI) thread.
            self.gui_queue.put(lambda: self._apply_and_restart(marker))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_and_restart(self, marker):
        """Launch the detached helper, then close the app so it can swap files."""
        try:
            updater.launch_helper(marker)
        except Exception as e:
            messagebox.showerror("Update", f"Couldn't start the updater:\n{e}")
            self.status_var.set("Ready")
            return
        # Terminate child processes and wait briefly so their file handles are released before
        # the helper swaps program files (the helper also waits on our PID, but children are
        # separate processes it doesn't track).
        if self.active_processes:
            for proc in self.active_processes:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass
            for proc in self.active_processes:
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
        self.root.destroy()

    def reconcile_update_result(self):
        """On startup, surface the outcome of any update applied since last run."""
        try:
            res = updater.consume_result()
        except Exception:
            res = None
        if not res:
            return

        if res.get("status") == "success":
            self.status_var.set(f"Updated to v{__version__} ✓")
            # Fire the from->to telemetry event (reuses the opt-out/env-aware heartbeat).
            try:
                from app import telemetry
                telemetry.send_update_event(res.get("from") or res.get("to") or "")
            except Exception:
                pass
        else:
            # Failed / interrupted: remember the version so we never auto-retry it, and offer
            # the manual path. This is the loop-breaker.
            ver = res.get("to") or ""
            if ver:
                self.skipped_version = ver
                self.save_settings()
            reason = res.get("reason", "")
            detail = f" ({reason})" if reason else ""
            if messagebox.askyesno(
                "Update",
                f"The automatic update didn't finish{detail}.\n\n"
                "Open the download page to update manually?"):
                webbrowser.open("https://github.com/SonicSandbox/surasura/releases/latest")

    def log_to_terminal(self, message):
        """Appends text to the terminal widget safely via queue"""
        def _update():
            if self.terminal:
                self.terminal.config(state=tk.NORMAL)
                self.terminal.insert(tk.END, message + "\n")
                self.terminal.see(tk.END)
                self.terminal.config(state=tk.DISABLED)
        self.gui_queue.put(_update)

    def update_satori_visibility(self):
        """Hides or shows the Satori button based on settings and module availability"""
        if not hasattr(self, 'btn_satori'):
            return
            
        should_show = False
        
        # 1. User Preference Check
        if not self.var_hide_satoru.get():
            # 2. Module Availability Check
            try:
                import modules.immersion_architect
                should_show = True
            except (ImportError, ModuleNotFoundError):
                # Module is missing (Open Source build or Excluded)
                should_show = False
        
        if should_show:
            # Re-pack in the credit box
            # This is slightly tricky if other elements are added later,
            # but usually it's at the end.
            if not self.btn_satori.winfo_ismapped():
                self.btn_satori.pack(side=tk.LEFT, padx=(5, 0))
        else:
            self.btn_satori.pack_forget()

    def open_youtube_downloader(self):
        # Orchestration lives in the module; the core only needs a thin, lazy entry point.
        try:
            from modules.youtube_downloader import open_downloader
        except (ImportError, ModuleNotFoundError):
            return
        open_downloader(self)

    def update_youtube_visibility(self):
        """Shows the YouTube button only if enabled in settings AND the module is available."""
        if not hasattr(self, 'btn_youtube') or self.btn_youtube is None:
            return

        should_show = False
        if self.var_enable_youtube.get():
            try:
                import modules.youtube_downloader  # noqa: F401
                should_show = True
            except (ImportError, ModuleNotFoundError):
                # Module absent (open-source build or excluded by the conditional build)
                should_show = False

        if should_show:
            if not self.btn_youtube.winfo_ismapped():
                self.btn_youtube.pack(side=tk.LEFT, padx=(0, 0))
        else:
            self.btn_youtube.pack_forget()

    def open_youtube_preview(self):
        # Orchestration (cache check, analysis run, polling, dialog) lives in the module.
        try:
            from modules.youtube_downloader import open_preview
        except (ImportError, ModuleNotFoundError):
            return
        open_preview(self)

    def update_preview_visibility(self):
        """Shows the Preview button only if enabled in settings AND the module is available."""
        if not hasattr(self, 'btn_preview') or self.btn_preview is None:
            return
        should_show = False
        if self.var_enable_preview.get():
            try:
                import modules.youtube_downloader.preview  # noqa: F401
                should_show = True
            except (ImportError, ModuleNotFoundError):
                should_show = False
        if should_show:
            if not self.btn_preview.winfo_ismapped():
                self.btn_preview.pack(side=tk.LEFT, padx=(5, 0))
        else:
            self.btn_preview.pack_forget()

    def load_settings(self):
        try:
            settings = settings_manager.load_settings()
            self._current_settings = settings

            self.var_exclude_single.set(settings.get("exclude_single", True))
            self.var_min_freq.set(settings.get("min_freq", 1))
            self.var_open_app_mode.set(settings.get("open_app_mode", False))
            
            theme = settings.get("theme", "Dark Flow")
            if theme in self.combo_theme['values']:
                self.combo_theme.set(theme)
            
            self.var_strategy.set(settings.get("strategy", "freq"))
            self.var_target_coverage.set(settings.get("target_coverage", 90))
            self.var_split_length.set(settings.get("split_length", 3000))
            
            lang = settings.get("target_language", "ja")
            if not lang: lang = "ja"
            self.var_language.set(lang)

            self.var_reinforce.set(settings.get("reinforce_segmentation", False))
            self.var_telemetry_enabled.set(settings.get("telemetry_enabled", True))
            self.var_only_i_plus_one.set(settings.get("only_i_plus_one", False))
            self.var_add_graduated.set(settings.get("add_graduated_words", True))
            self.var_words_per_day.set(settings.get("words_per_day", 5))
            self.var_show_words_per_day.set(settings.get("show_words_per_day", True))
            self.var_zen_limit.set(settings.get("zen_limit", 50))

            self.onboarding_completed.set(settings.get("onboarding_completed", False))
            self.var_open_count.set(settings.get("open_count", 0))
            self.var_hide_satoru.set(settings.get("hide_satoru", False))
            self.update_satori_visibility()

            self.var_enable_youtube.set(settings.get("enable_youtube_transcripts", False))
            self.youtube_risk_acknowledged = settings.get("youtube_risk_acknowledged", False)
            self.update_youtube_visibility()

            self.var_enable_preview.set(settings.get("enable_youtube_preview", False))
            self.update_preview_visibility()

            self.var_auto_update.set(settings.get("auto_update_enabled", True))
            self.skipped_version = settings.get("skipped_version", "")

            # Load Logic Settings
            self.logic_settings = settings.get("logic", {})
            self.var_inline_completed.set(self.logic_settings.get("inline_completed_files", False))
            self.var_hide_audio.set(self.logic_settings.get("hide_audio_button", False))
            context_settings = self.logic_settings.get("context", {})
            self.var_context_min_chars.set(context_settings.get("min_chars", 10))
            self.var_context_max_chars.set(context_settings.get("preferred_max_chars", 50))
            
            # Use the existing IntVar if it exists, otherwise it will be created in setup_ui or create_settings_window
            if hasattr(self, 'var_max_contexts') and self.var_max_contexts:
                self.var_max_contexts.set(context_settings.get("max_contexts", 3))
            else:
                self.var_max_contexts = tk.IntVar(value=context_settings.get("max_contexts", 3))
            
            self.update_strategy_ui() # Apply state
        except Exception as e:
            print(f"Warning: Could not load settings: {e}")

    @staticmethod
    def _iv(var, fallback):
        """Read an IntVar tolerantly. A numeric Entry/Spinbox is momentarily EMPTY while the
        user edits it (e.g. deletes 3000 to type 500), and IntVar.get() then raises TclError.
        Returning the last-saved value keeps a mid-edit keystroke from aborting the whole save."""
        try:
            return var.get()
        except tk.TclError:
            return fallback

    def save_settings(self, *args):
        try:
            cur = getattr(self, "_current_settings", {}) or {}
            cur_ctx = cur.get("logic", {}).get("context", {}) if isinstance(cur.get("logic"), dict) else {}
            # Build settings dict from GUI vars
            settings = {
                "exclude_single": self.var_exclude_single.get(),
                "min_freq": self._iv(self.var_min_freq, cur.get("min_freq", 1)),
                "open_app_mode": self.var_open_app_mode.get(),
                "theme": self.combo_theme.get(),
                "strategy": self.var_strategy.get(),
                "target_coverage": self._iv(self.var_target_coverage, cur.get("target_coverage", 90)),
                "split_length": self._iv(self.var_split_length, cur.get("split_length", 3000)),
                "target_language": self.var_language.get(),
                "reinforce_segmentation": self.var_reinforce.get(),
                "telemetry_enabled": self.var_telemetry_enabled.get(),
                "only_i_plus_one": self.var_only_i_plus_one.get(),
                "add_graduated_words": self.var_add_graduated.get(),
                "words_per_day": self._iv(self.var_words_per_day, cur.get("words_per_day", 5)),
                "show_words_per_day": self.var_show_words_per_day.get(),
                "zen_limit": self._iv(self.var_zen_limit, cur.get("zen_limit", 50)),
                "onboarding_completed": self.onboarding_completed.get(),
                "open_count": self._iv(self.var_open_count, cur.get("open_count", 0)),
                "hide_satoru": self.var_hide_satoru.get(),
                "auto_update_enabled": self.var_auto_update.get(),
                "skipped_version": getattr(self, "skipped_version", ""),
                "logic": {
                    **self.logic_settings,
                    "inline_completed_files": self.var_inline_completed.get(),
                    "hide_audio_button": self.var_hide_audio.get(),
                    "context": {
                        **self.logic_settings.get("context", {}),
                        "min_chars": self._iv(self.var_context_min_chars, cur_ctx.get("min_chars", 10)),
                        "preferred_max_chars": self._iv(self.var_context_max_chars, cur_ctx.get("preferred_max_chars", 50)),
                        "max_contexts": self._iv(self.var_max_contexts, cur_ctx.get("max_contexts", 3))
                    }
                }
            }

            # Persist YouTube settings only when the optional module is present, so a build
            # without it never writes those keys back into settings.json.
            try:
                import modules.youtube_downloader  # noqa: F401
                settings["enable_youtube_transcripts"] = self.var_enable_youtube.get()
                settings["enable_youtube_preview"] = self.var_enable_preview.get()
                settings["youtube_risk_acknowledged"] = getattr(self, "youtube_risk_acknowledged", False)
            except (ImportError, ModuleNotFoundError):
                pass

            settings_manager.save_settings(settings)
            self._current_settings = settings

            # Update UI state (enable/disable language specific options)
            if not getattr(self, '_lock_ui_updates', False):
                self.update_ui_for_language()
                
        except Exception as e:
            print(f"Error: Could not save settings: {e}")

    def open_data_folder(self):
        """Opens the data folder in File Explorer"""
        try:
            from app.path_utils import get_data_path, ensure_data_setup
            lang = self.var_language.get()
            ensure_data_setup(lang)
            data_path = get_data_path(lang)
            
            # Create if it doesn't exist (safety)
            if not os.path.exists(data_path):
                os.makedirs(data_path, exist_ok=True)
                
            # Cross-platform opening
            if sys.platform == "win32":
                os.startfile(data_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", data_path])
            else:
                subprocess.Popen(["xdg-open", data_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open data folder: {e}")

    def open_ignore_list(self):
        try:
            from app.path_utils import get_user_files_path
            lang = self.var_language.get()
            user_files_dir = get_user_files_path(lang)
            ignore_path = os.path.join(user_files_dir, "IgnoreList.txt")
            
            # Ensure file exists
            if not os.path.exists(ignore_path):
                os.makedirs(os.path.dirname(ignore_path), exist_ok=True)
                with open(ignore_path, "w", encoding="utf-8") as f:
                    f.write("# Add words to ignore here (one per line)\n")
            
            # Cross-platform opening
            if sys.platform == "win32":
                os.startfile(ignore_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", ignore_path])
            else:
                subprocess.Popen(["xdg-open", ignore_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open ignore list: {e}")

    def open_tutorial(self):
        try:
            webbrowser.open("https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open tutorial: {e}")
            
    def run_command_async(self, cmd, desc, capture_output=False, show_spinner=False):
        """Runs a command with optional output redirection to the terminal"""
        
        # UI updates must be queued
        def _start_loading():
            self.status_var.set(f"Running {desc}...")
            
            # Show spinner only if requested
            if show_spinner and self.spinner:
                self.spinner.pack(fill=tk.X, pady=(5, 0))
                self.spinner.start(10)

            # Clear terminal only if it exists
            if capture_output and self.terminal:
                self.terminal.config(state=tk.NORMAL)
                self.terminal.delete(1.0, tk.END)
                self.terminal.config(state=tk.DISABLED)
        
        self.gui_queue.put(_start_loading)

        def task():
            # Dispatch Mapping for Frozen Environment
            SCRIPT_MAP = {
                'analyzer.py': 'analyzer',
                'epub_importer.py': 'epub_importer',
                'migaku_db_importer_gui.py': 'migaku_importer',
                'jiten_db_importer_gui.py': 'jiten_importer',
                'content_importer_gui.py': 'content_importer',
                'static_html_generator.py': 'static_generator',
                'migaku_converter.py': 'convert_db',
                'anki_db_importer_gui.py': 'anki_importer',
                'frequency_list_gui.py': 'frequency_list_manager'
            }
            
            try:
                from app.path_utils import is_frozen
                
                if is_frozen():
                    # Frozen: Use the keyword mapped in app_entry.py
                    command_name = SCRIPT_MAP.get(cmd[0], cmd[0])
                    # Use sys.executable as the launcher
                    final_args = [sys.executable, command_name] + cmd[1:]
                else:
                    # Normal Source Mode
                    app_dir = os.path.dirname(os.path.abspath(__file__))
                    project_root = os.path.dirname(app_dir)
                    script_path = os.path.join(app_dir, cmd[0])
                    final_args = [sys.executable, script_path] + cmd[1:]

                # SET ENVIRONMENT (Fix for No module named 'app')
                env = os.environ.copy()
                if not is_frozen():
                    # In source mode, add the project root to PYTHONPATH
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    if "PYTHONPATH" in env:
                        env["PYTHONPATH"] = project_root + os.pathsep + env["PYTHONPATH"]
                    else:
                        env["PYTHONPATH"] = project_root
                
                # subprocess.CREATE_NO_WINDOW can cause issues for GUI apps
                # but it's good for console tools like analyzer if we capture output.
                creation_flags = 0
                if sys.platform == "win32" and capture_output:
                    creation_flags = 0x08000000 # CREATE_NO_WINDOW

                process = subprocess.Popen(
                    final_args,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.STDOUT if capture_output else None,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    universal_newlines=True,
                    creationflags=creation_flags,
                    env=env
                )
                
                # Register process for coordinated shutdown
                self.active_processes.append(process)
                
                if capture_output and process.stdout:
                    for line in process.stdout:
                        # Log line safely
                        self.log_to_terminal(line.strip())
                    process.wait()
                else:
                    process.wait()
                
                if process.returncode != 0:
                     self.log_to_terminal(f"\n[ERROR] {desc} exited with code {process.returncode}")
                
                self.gui_queue.put(lambda: self.status_var.set("Ready"))
                
            except Exception as e:
                import traceback
                print(traceback.format_exc())
                # Queue the error message
                def _show_error(err=e):
                     # Wait, messagebox blocks. Be careful. 
                     # Better to just log state error, or use after.
                     # But messagebox is usually main-thread only.
                     messagebox.showerror("Error", f"Failed to run {desc}:\n{err}")
                     self.status_var.set("Error")
                self.gui_queue.put(_show_error)
            finally:
                def _stop_loading():
                    if capture_output and self.spinner:
                        self.spinner.stop()
                        self.spinner.pack_forget()
                self.gui_queue.put(_stop_loading)
                    
        threading.Thread(target=task, daemon=True).start()

    def on_closing(self):
        """Coordinated shutdown: terminate all active sub-processes"""
        if self.active_processes:
            self.status_var.set("Closing sub-windows...")
            for proc in self.active_processes:
                try:
                    if proc.poll() is None: # Still running
                        proc.terminate()
                except Exception:
                    pass
        self.root.destroy()

    def run_migaku_importer(self):
        self.run_command_async(['migaku_db_importer_gui.py', '--language', self.var_language.get()], "Migaku Importer")

    def run_jiten_importer(self):
        self.run_command_async(['jiten_db_importer_gui.py', '--language', self.var_language.get()], "Jiten Sync")

    def run_anki_importer(self):
        self.run_command_async(['anki_db_importer_gui.py', '--language', self.var_language.get()], "Anki Known Words")

    def run_content_importer(self):
        self.run_command_async(['content_importer_gui.py', '--language', self.var_language.get()], "Content Importer")

    def run_file_importer(self):
        self.run_command_async(['epub_importer.py', '--language', self.var_language.get()], "File Importer")

    def run_frequency_list_manager(self):
        self.run_command_async(['frequency_list_gui.py', '--language', self.var_language.get()], "Frequency List Manager")

    def run_analyzer(self):
        from app.path_utils import ensure_data_setup
        ensure_data_setup(self.var_language.get())
        args = ['analyzer.py']
        if not self.var_exclude_single.get():
            args.append('--include-single-chars')
        
        if self.var_strategy.get() == "coverage":
            coverage_target = self.var_target_coverage.get()
            args.append(f'--target-coverage={coverage_target}')
        else:
            min_freq = self.var_min_freq.get()
            if min_freq > 0:
                args.append(f'--min-freq={min_freq}')
        
        args.append('--static')
        
        # Add Language
        args.append(f'--language={self.var_language.get()}')
        
        # Add Reinforce Flag if applicable
        if self.var_language.get() == 'zh' and self.var_reinforce.get():
            args.append('--reinforce')
            
        if self.var_only_i_plus_one.get():
            args.append('--only-i-plus-one')
            
        args.append(f'--context-min={self.var_context_min_chars.get()}')
        args.append(f'--context-max={self.var_context_max_chars.get()}')
        
        max_c = self.var_max_contexts.get()
        if max_c != 3:
            args.append(f'--max-contexts={max_c}')
        
        # Add theme argument
        theme_map = {
            'Default (Dark)': 'default',
            'Dark Flow': 'world-class',
            'Midnight (Vibrant)': 'midnight-vibrant',
            'Modern Light': 'modern-light',
            'Zen Mode': 'zen-focus'
        }
        selected_theme = self.combo_theme.get()
        theme_arg = theme_map.get(selected_theme, 'default')
        args.append(f'--theme={theme_arg}')
        
        if self.var_open_app_mode.get():
            args.append('--app-mode')
            
        # Zen Limit (passed to analyzer just in case, or for consistency)
        zen_limit = self.var_zen_limit.get()
        if zen_limit > 0:
            args.append(f'--zen-limit={zen_limit}')

        self.run_command_async(args, "Analyzer", capture_output=True, show_spinner=True)

    def run_static_page(self):
        # Add theme argument for static page generation only
        args = ['static_html_generator.py']
        theme_map = {
            'Default (Dark)': 'default',
            'Dark Flow': 'world-class',
            'Midnight (Vibrant)': 'midnight-vibrant',
            'Modern Light': 'modern-light',
            'Zen Mode': 'Zen Mode'
        }
        selected_theme = self.combo_theme.get()
        theme_arg = theme_map.get(selected_theme, 'default')
        args.append(f'--theme={theme_arg}')

        if self.var_open_app_mode.get():
            args.append('--app-mode')

        # Zen Limit
        zen_limit = self.var_zen_limit.get()
        if zen_limit > 0:
            args.append(f'--zen-limit={zen_limit}')

        self.run_command_async(args, "Static Page", capture_output=True, show_spinner=True)

    def generate_frequency_list(self):
        """Show dialog to choose export format"""
        from app.path_utils import get_user_file
        
        results_dir = get_user_file("results")
        priority_csv = os.path.join(results_dir, "priority_learning_list.csv")

        if not os.path.exists(priority_csv) or os.path.getsize(priority_csv) == 0:
            messagebox.showwarning("No Data", "You need to run an analysis first to generate data.")
            return
            
        # Dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Format")
        dialog.geometry("400x250")
        dialog.resizable(False, False)
        dialog.configure(bg=BG_COLOR)
        
        # Center the dialog
        dialog.transient(self.root)
        dialog.grab_set()

        # Bind Escape to close
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        
        # UI
        wrapper = ttk.Frame(dialog, padding=20)
        wrapper.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(wrapper, text="Which format would you like to create?", 
                 font=('Segoe UI', 11, 'bold'), foreground=TEXT_COLOR, background=BG_COLOR).pack(pady=(0, 20))
                 
        # Buttons
        btn_migaku = ttk.Button(wrapper, text="Migaku", command=lambda: self.export_wrapper(dialog, "migaku", priority_csv))
        btn_migaku.pack(fill=tk.X, pady=5)
        ToolTip(btn_migaku, "Export as a JSON array (Standard Migaku Format).")
        
        btn_yomitan = ttk.Button(wrapper, text="Yomichan / Yomitan", command=lambda: self.export_wrapper(dialog, "yomitan", priority_csv))
        btn_yomitan.pack(fill=tk.X, pady=5)
        ToolTip(btn_yomitan, "Export as a frequency dict ZIP file (v3 format).")
        
        btn_txt = ttk.Button(wrapper, text="Word List (Text)", command=lambda: self.export_wrapper(dialog, "txt", priority_csv))
        btn_txt.pack(fill=tk.X, pady=5)
        ToolTip(btn_txt, "Export as a plain text file (one word per line).")

    def generate_anki_sentence_warning(self):
        from app.path_utils import get_user_file
        results_dir = get_user_file("results")
        priority_csv = os.path.join(results_dir, "priority_learning_list.csv")

        if not os.path.exists(priority_csv) or os.path.getsize(priority_csv) == 0:
            messagebox.showwarning("No Data", "You need to run an analysis first to generate data.")
            return

        # Warning Dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Anki Export Warning")
        dialog.geometry("450x420")
        dialog.resizable(False, False)
        dialog.configure(bg=BG_COLOR)
        
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

        wrapper = ttk.Frame(dialog, padding=20)
        wrapper.pack(fill=tk.BOTH, expand=True)

        warn_text = (
            "WARNING: You will learn words faster with higher retention practice "
            "if you mine directly from the スラスラ list. You can see multiple "
            "examples and mine with Yomitan / Migaku.\n\n"
            "FORMAT: This will generate a list to import into Anki / SRS software. "
            "Columns included: Index, Word, Reading, Main Sentence, Second Sentence, Tier, Sources.\n\n"
            "Are you sure you want to do this?"
        )
        
        ttk.Label(wrapper, text=warn_text, foreground=ERROR_COLOR, background=BG_COLOR, font=('Segoe UI', 10), wraplength=400, justify=tk.LEFT).pack(pady=(0, 20))
        
        confirm_var = tk.BooleanVar(value=False)
        chk_confirm = ttk.Checkbutton(wrapper, text="I understand", variable=confirm_var)
        chk_confirm.pack(anchor=tk.W, pady=(0, 20))
        
        def on_generate():
            if not confirm_var.get():
                messagebox.showwarning("Confirm", "Please check the box to confirm you understand.")
                return
            self.export_wrapper(dialog, "anki", priority_csv)
            
        btn_gen = ttk.Button(wrapper, text="Generate Sentence List", command=on_generate, style="Action.TButton")
        btn_gen.pack(fill=tk.X)


    def export_wrapper(self, dialog, format_type, csv_path):
        from tkinter import filedialog
        from app.frequency_exporter import FrequencyExporter
        
        dialog.destroy()
        
        file_types = []
        def_ext = ""
        initial_name = "MY Immersion FreqList"
        
        if format_type == "migaku":
            file_types = [("JSON Files", "*.json")]
            def_ext = ".json"
        elif format_type == "yomitan":
            file_types = [("Zip Files", "*.zip")]
            def_ext = ".zip"
        elif format_type == "txt":
            file_types = [("Text Files", "*.txt")]
            def_ext = ".txt"
        elif format_type == "anki":
            file_types = [("CSV Files", "*.csv")]
            def_ext = ".csv"
            initial_name = "Anki_Sentence_List"
            
        save_path = filedialog.asksaveasfilename(
            defaultextension=def_ext,
            initialfile=f"{initial_name}{def_ext}",
            filetypes=file_types,
            title=f"Save {format_type.capitalize()} List"
        )
        
        if not save_path:
            return
            
        try:
            if format_type == "migaku":
                FrequencyExporter.export_migaku(csv_path, save_path)
            elif format_type == "yomitan":
                lang = self.var_language.get()
                FrequencyExporter.export_yomitan(csv_path, save_path, language=lang)
            elif format_type == "txt":
                FrequencyExporter.export_word_list(csv_path, save_path)
            elif format_type == "anki":
                FrequencyExporter.export_anki_sentences(csv_path, save_path)
                
            messagebox.showinfo("Success", f"List generated successfully!\n\nSaved to: {save_path}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export:\n{e}")

def main():
    root = tk.Tk()
    app = MasterDashboardApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
