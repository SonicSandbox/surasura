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
from app.update_checker import check_for_updates

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
        # Add delay to prevent flickering and improve "feel"
        self.id = self.widget.after(500, self.show_tip)

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
        self.root.title(f"Surasura - Readability Analyzer Dashboard v{__version__}")
        self.root.geometry("520x650") 
        self.root.resizable(True, True)
        self.root.minsize(520, 550)
        self.root.configure(bg=BG_COLOR)
        

        
        self.style = ttk.Style()
        self.apply_dark_theme()
        
        # Initialize variables for Analyzer settings
        self.var_exclude_single = tk.BooleanVar(value=True) 
        self.var_min_freq = tk.IntVar(value=1) 
        self.var_zen_limit = tk.IntVar(value=50) 
        self.var_zen_limit = tk.IntVar(value=50) 
        self.var_open_app_mode = tk.BooleanVar(value=False)
        self.var_strategy = tk.StringVar(value="freq")
        self.var_target_coverage = tk.IntVar(value=90)
        self.var_split_length = tk.IntVar(value=1500)
        self.onboarding_completed = tk.BooleanVar(value=False)
        
        # Initialize status var early to satisfy linter
        self.status_var = tk.StringVar(value="Ready")
        self.terminal: Optional[tk.Text] = None
        self.spinner: Optional[ttk.Progressbar] = None
        self.settings_window: Optional[tk.Toplevel] = None
        
        # Queue for thread-safe GUI updates
        self.gui_queue = queue.Queue()
        self.check_queue()

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
        self.var_zen_limit.trace_add("write", self.save_settings)
        self.var_open_app_mode.trace_add("write", self.save_settings)
        self.combo_theme.bind("<<ComboboxSelected>>", self.save_settings)
        
        # Start update check in background
        threading.Thread(target=self.check_updates_thread, daemon=True).start()
        
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

    def update_strategy_ui(self):
        strategy = self.var_strategy.get()
        if strategy == "freq":
            self.freq_frame.pack(side=tk.TOP, fill=tk.X)
            self.coverage_frame.pack_forget()
        else:
            self.freq_frame.pack_forget()
            self.coverage_frame.pack(side=tk.TOP, fill=tk.X)
            self.save_settings() # Save on switch
        
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="15") # Reduced padding 25 -> 15
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(pady=(0, 10)) # Reduced pady 20 -> 10
        
        if hasattr(self, 'logo_header'):
            logo_label = ttk.Label(header_frame, image=self.logo_header)
            logo_label.pack(side=tk.LEFT, padx=(0, 10))
            
        header_text = ttk.Label(header_frame, text="Surasura - Readability Analyzer", style="Header.TLabel")
        header_text.pack(side=tk.LEFT)
        
        # 1. Vocabulary Tools
        vocab_frame = ttk.LabelFrame(main_frame, text=" 📚 Import Known Vocabulary", padding="10")
        vocab_frame.pack(fill=tk.X, pady=(0, 5)) # Reduced pady 10 -> 5
        
        # Single Row: [Migaku] [Jiten] [Edit Ignore List (fills rest)]
        vocab_row = ttk.Frame(vocab_frame)
        vocab_row.pack(fill=tk.X)

        btn_migaku = ttk.Button(vocab_row, text="Migaku", width=12,
                   command=self.run_migaku_importer)
        btn_migaku.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(btn_migaku, "Import known words from Migaku database export.")

        btn_jiten = ttk.Button(vocab_row, text="Jiten", width=12,
                   command=self.run_jiten_importer)
        btn_jiten.pack(side=tk.LEFT, padx=(0, 10))
        ToolTip(btn_jiten, "Import known words from Jiten API using your API key.")
        
        # This button expands to fill all remaining space
        btn_ignore = ttk.Button(vocab_row, text="Edit Ignore List", style="Action.TButton",
                     command=self.open_ignore_list)
        btn_ignore.pack(side=tk.LEFT, expand=True, fill=tk.X)
        ToolTip(btn_ignore, "Open your IgnoreList.txt to manually edit excluded words.")

        # 2. Library Tools
        lib_frame = ttk.LabelFrame(main_frame, text=" 📦 Library Content", padding="10")
        lib_frame.pack(fill=tk.X, pady=(0, 5)) # Reduced pady 10 -> 5

        btn_open_data = ttk.Button(lib_frame, text="Launch Content Importer", style="Action.TButton",
                                    command=self.run_content_importer)
        btn_open_data.pack(side=tk.LEFT, padx=(0, 5), expand=True, fill=tk.X)
        ToolTip(btn_open_data, "Launch the wizard to import content into priority folders.")

        btn_epub = ttk.Button(lib_frame, text="Extract / Splice", style="Action.TButton", 
                   command=self.run_file_importer)
        btn_epub.pack(side=tk.LEFT, padx=(0, 5), expand=True, fill=tk.X)
        ToolTip(btn_epub, "Import and split EPUB, TXT, MD, or SRT files for analysis.")

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

        # Run Analyzer Button
        btn_analyze = ttk.Button(analyze_frame, text="Run Analysis", style="Action.TButton",
                                 command=self.run_analyzer)
        btn_analyze.pack(anchor=tk.W, fill=tk.X)
        ToolTip(btn_analyze, "Analyze text files and generate readability report. Auto-launches static page.")

        # Spinner (Initially hidden)
        self.spinner = ttk.Progressbar(analyze_frame, mode='indeterminate', style="TProgressbar")
        
        # 4. Results Viewer
        view_frame = ttk.LabelFrame(main_frame, text=" 📊 Results Viewer", padding="10")
        view_frame.pack(fill=tk.X, pady=(0, 2)) # Further reduced pady

        # Theme Selector and App Mode Toggle
        theme_app_frame = ttk.Frame(view_frame)
        theme_app_frame.pack(fill=tk.X, pady=(0, 8))

        themes = ['Default (Dark)', 'Dark Flow', 'Midnight (Vibrant)', 'Modern Light', 'Zen Focus']
        self.combo_theme = ttk.Combobox(theme_app_frame, values=themes, state="readonly", width=20)
        self.combo_theme.set('Dark Flow')
        self.combo_theme.pack(side=tk.LEFT)
        ToolTip(self.combo_theme, "Select the visual theme for the generated reading list.")
        
        chk_app_mode = ttk.Checkbutton(theme_app_frame, text="Open in New Window", variable=self.var_open_app_mode)
        chk_app_mode.pack(side=tk.LEFT, padx=(20, 0))
        ToolTip(chk_app_mode, "RECOMMENDS keeping it off until the migaku or lookupextension is turned on for that site.")
        
        # Zen Limit Slider (Inline with Results)
        zen_frame = ttk.Frame(view_frame)
        zen_frame.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Label(zen_frame, text="Zen Word Limit:").pack(side=tk.LEFT)
        
        zen_limit_slider = tk.Scale(zen_frame, from_=25, to=125, orient=tk.HORIZONTAL, 
                                    variable=self.var_zen_limit, showvalue=False,
                                    bg=BG_COLOR, fg=TEXT_COLOR, highlightthickness=0,
                                    activebackground=ACCENT_COLOR, troughcolor=SURFACE_COLOR)
        zen_limit_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        zen_val_label = ttk.Label(zen_frame, textvariable=self.var_zen_limit, width=3)
        zen_val_label.pack(side=tk.LEFT)
        
        ToolTip(zen_frame, "Only for Zen Focus mode: Number of words to include across all files.")

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
        
        # Credit
        credit_box = ttk.Frame(footer_frame)
        credit_box.pack(side=tk.RIGHT)
        
        ttk.Label(credit_box, text="Created by SonicSandbox | ", style="Footer.TLabel").pack(side=tk.LEFT)
        self.github_link = ttk.Label(credit_box, text="GitHub", style="Link.TLabel", cursor="hand2")
        self.github_link.pack(side=tk.LEFT)
        # UPDATED LINK to the new repo
        self.github_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/SonicSandbox/surasura"))

        # Settings Button (Icon only, Bottom Right)
        # Use a simple gear unicode or similar if no image
        btn_settings = ttk.Button(credit_box, text="⚙", command=self.toggle_settings_window, width=3)
        btn_settings.pack(side=tk.LEFT, padx=(10, 0))
        ToolTip(btn_settings, "Open Settings & Logs")

    def complete_onboarding(self):
        self.onboarding_completed.set(True)
        self.save_settings()

    def create_settings_window(self):
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Settings & Logs")
        self.settings_window.geometry("600x400")
        self.settings_window.protocol("WM_DELETE_WINDOW", self.toggle_settings_window)
        
        # Bind Escape to hide the settings window
        self.settings_window.bind("<Escape>", lambda e: self.toggle_settings_window())
        
        self.settings_window.withdraw() # Hide initially
        
        # Apply theme to settings window too (requires style sharing which ttk does automatically for same root)
        self.settings_window.configure(bg=BG_COLOR)

        # Settings
        settings_frame = ttk.LabelFrame(self.settings_window, text=" Advanced Settings", padding="10")
        settings_frame.pack(fill=tk.X, padx=10, pady=10)
        
        chk_single = ttk.Checkbutton(settings_frame, text="Exclude 1-character words", variable=self.var_exclude_single)
        chk_single.pack(anchor=tk.W)
        ToolTip(chk_single, "Ignore 1-char words (Recommended)")

        # Split Length Setting
        split_frame = ttk.Frame(settings_frame)
        split_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(split_frame, text="Default Split Length (Chars):").pack(side=tk.LEFT)
        ttk.Entry(split_frame, textvariable=self.var_split_length, width=8).pack(side=tk.LEFT, padx=5)
        self.var_split_length.trace_add("write", self.save_settings)
        ToolTip(split_frame, "Initial character limit used when splitting files in the File Importer.")

        # Frequency List Manager
        btn_freq = ttk.Button(settings_frame, text="Add Frequency List", command=self.run_frequency_list_manager)
        btn_freq.pack(anchor=tk.W, pady=(10, 0))
        ToolTip(btn_freq, "Manage custom frequency lists for word analysis.")

        # Logs
        log_frame = ttk.LabelFrame(self.settings_window, text=" Processing Log", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.terminal = tk.Text(log_frame, height=10, bg=SURFACE_COLOR, fg=TEXT_COLOR, 
                                insertbackground=TEXT_COLOR, font=("Consolas", 9),
                                relief=tk.FLAT, borderwidth=0, state=tk.DISABLED,
                                wrap=tk.NONE)
        self.terminal.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.terminal.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.terminal.config(yscrollcommand=scrollbar.set)
        
    def toggle_settings_window(self):
        if self.settings_window is None or not self.settings_window.winfo_exists():
            self.create_settings_window()
            
        if self.settings_window.state() == "withdrawn":
            self.settings_window.deiconify()
            self.settings_window.lift()
        else:
            self.settings_window.withdraw()

    def check_updates_thread(self):
        """Background thread to check for updates"""
        try:
            update_info = check_for_updates(__version__)
            if update_info:
                new_tag, release_url = update_info
                def _notify_update():
                    self.github_link.config(
                        text=f"Update Available! ({new_tag})",
                        foreground=ACCENT_COLOR # Ensure it stands out if theme allows
                    )
                    # Tooltip update would be nice but requires ToolTip instance access
                    # For now, just change text and link
                    self.github_link.bind("<Button-1>", lambda e: webbrowser.open(release_url))
                    self.status_var.set(f"Update Available: {new_tag}")
                
                self.gui_queue.put(_notify_update)
        except Exception as e:
            print(f"Update check failed: {e}")

    def log_to_terminal(self, message):
        """Appends text to the terminal widget safely via queue"""
        def _update():
            if self.terminal:
                self.terminal.config(state=tk.NORMAL)
                self.terminal.insert(tk.END, message + "\n")
                self.terminal.see(tk.END)
                self.terminal.config(state=tk.DISABLED)
        self.gui_queue.put(_update)

    def load_settings(self):
        try:
            from app.path_utils import get_user_file
            settings_path = get_user_file("settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.var_exclude_single.set(settings.get("exclude_single", True))
                    self.var_min_freq.set(settings.get("min_freq", 1))
                    self.var_zen_limit.set(settings.get("zen_limit", 50))
                    self.var_open_app_mode.set(settings.get("open_app_mode", False))
                    theme = settings.get("theme", "Dark Flow")
                    if theme in self.combo_theme['values']:
                        self.combo_theme.set(theme)
                    
                    self.var_strategy.set(settings.get("strategy", "freq"))
                    self.var_target_coverage.set(settings.get("target_coverage", 90))
                    self.var_split_length.set(settings.get("split_length", 1500))
                    self.onboarding_completed.set(settings.get("onboarding_completed", False))
                    self.update_strategy_ui() # Apply state
        except Exception as e:
            print(f"Warning: Could not load settings: {e}")

    def save_settings(self, *args):
        try:
            from app.path_utils import get_user_file
            settings_path = get_user_file("settings.json")
            settings = {
                "exclude_single": self.var_exclude_single.get(),
                "min_freq": self.var_min_freq.get(),
                "zen_limit": self.var_zen_limit.get(),
                "open_app_mode": self.var_open_app_mode.get(),
                "theme": self.combo_theme.get(),
                "strategy": self.var_strategy.get(),
                "target_coverage": self.var_target_coverage.get(),
                "split_length": self.var_split_length.get(),
                "onboarding_completed": self.onboarding_completed.get()
            }
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Warning: Could not save settings: {e}")

    def open_data_folder(self):
        """Opens the data folder in File Explorer"""
        try:
            from app.path_utils import get_user_file, ensure_data_setup
            ensure_data_setup()
            data_path = get_user_file("data")
            
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
            from app.path_utils import get_user_file
            ignore_path = get_user_file("User Files/IgnoreList.txt")
            
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
                    bufsize=1,
                    universal_newlines=True,
                    creationflags=creation_flags,
                    env=env
                )
                
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

    def run_migaku_importer(self):
        self.run_command_async(['migaku_db_importer_gui.py'], "Migaku Importer")

    def run_jiten_importer(self):
        self.run_command_async(['jiten_db_importer_gui.py'], "Jiten Sync")

    def run_content_importer(self):
        self.run_command_async(['content_importer_gui.py'], "Content Importer")

    def run_file_importer(self):
        self.run_command_async(['epub_importer.py'], "File Importer")

    def run_frequency_list_manager(self):
        self.run_command_async(['frequency_list_gui.py'], "Frequency List Manager")

    def run_analyzer(self):
        from app.path_utils import ensure_data_setup
        ensure_data_setup()
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
        
        # Add theme argument
        theme_map = {
            'Default (Dark)': 'default',
            'Dark Flow': 'world-class',
            'Midnight (Vibrant)': 'midnight-vibrant',
            'Modern Light': 'modern-light',
            'Zen Focus': 'zen-focus'
        }
        selected_theme = self.combo_theme.get()
        theme_arg = theme_map.get(selected_theme, 'default')
        args.append(f'--theme={theme_arg}')
        args.append(f'--zen-limit={self.var_zen_limit.get()}')
        
        if self.var_open_app_mode.get():
            args.append('--app-mode')
            
        self.run_command_async(args, "Analyzer", capture_output=True, show_spinner=True)

    def run_static_page(self):
        # Add theme argument for static page generation only
        args = ['static_html_generator.py']
        theme_map = {
            'Default (Dark)': 'default',
            'Dark Flow': 'world-class',
            'Midnight (Vibrant)': 'midnight-vibrant',
            'Modern Light': 'modern-light',
            'Zen Focus': 'zen-focus'
        }
        selected_theme = self.combo_theme.get()
        theme_arg = theme_map.get(selected_theme, 'default')
        args.append(f'--theme={theme_arg}')
        args.append(f'--zen-limit={self.var_zen_limit.get()}')

        if self.var_open_app_mode.get():
            args.append('--app-mode')

        self.run_command_async(args, "Static Page", capture_output=True, show_spinner=True)

def main():
    root = tk.Tk()
    app = MasterDashboardApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
