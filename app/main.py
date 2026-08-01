import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import csv
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
from app import word_selection
from app import token_index

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


def build_subprocess_env(frozen=None):
    """Environment for a child process launched by run_command_async (analyzer / importers / indexer).

    Forces the child's stdio to UTF-8 so the parent's strict-UTF-8 stdout capture never chokes on
    locale-encoded bytes: a source-mode script otherwise encodes stdout in the OS locale (cp1252 on
    Windows), turning e.g. an em-dash into byte 0x97 and crashing the capture with "invalid start
    byte". Also puts the project root on PYTHONPATH in source mode so `from app import ...` resolves.
    """
    from app.path_utils import is_frozen
    if frozen is None:
        frozen = is_frozen()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if not frozen:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = (project_root + os.pathsep + env["PYTHONPATH"]
                             if "PYTHONPATH" in env else project_root)
    return env


def csv_has_data_rows(path):
    """True if `path` is a CSV holding at least one row BELOW the header.

    File size can't answer this. The analyzer writes the reading-words header unconditionally, so a
    library with no read-only words leaves a small file that exists and is non-empty — a size check
    passed it, the format picker opened, and the user only learned there was nothing to export when
    the exporter failed with its own generic message. The explanation written for exactly that case
    was unreachable.

    Short-circuits on the first data row, so a multi-megabyte priority list costs one line.
    A missing or unreadable file is reported as "no data" rather than raised: this only gates a
    warning dialog, and the exporters validate their input again anyway.

    Module-level rather than a method on purpose: the export dialog is exercised with a MagicMock
    `self`, whose every attribute is a truthy Mock, so a `self.`-qualified check would be silently
    faked and the guard would never fire (see docs/agent instructions/testing.md §5.3).
    """
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            next(reader, None)                                   # header
            return any(any(cell.strip() for cell in row) for row in reader)
    except (OSError, UnicodeDecodeError, csv.Error):
        return False


class ToolTip:
    def __init__(self, widget, text, above=False):
        self.widget = widget
        self.text = text          # str, or a zero-arg callable returning the current text
        self.above = above        # show above the widget (e.g. so a slider's preview stays visible)
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
        text = self.text() if callable(self.text) else self.text
        if self.tip_window or not text:
            return

        root_x = self.widget.winfo_rootx()
        root_y = self.widget.winfo_rooty()
        widget_height = self.widget.winfo_height()
        widget_width = self.widget.winfo_width()

        # Default: just below-right of the widget.
        x = root_x + 20
        y = root_y + widget_height + 2

        # For very wide widgets (like checkboxes), push it to the right instead.
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

        # Wrap long tooltips onto multiple lines (per GUI guidelines); manual \n still break where
        # intended. Short tips (<=50 chars) stay single-line.
        wrap = 300 if len(text) > 50 else 0
        label = tk.Label(tw, text=text, justify=tk.LEFT, wraplength=wrap,
                      background=SURFACE_COLOR, foreground=TEXT_COLOR,
                      relief=tk.FLAT, borderwidth=0,
                      padx=8, pady=4, font=("Segoe UI", 9))
        label.pack()
        # XML-like border using frame or just background
        tw.configure(background=ACCENT_COLOR, padx=1, pady=1)

        # Position above the widget (needs the rendered height) — keeps the slider's preview
        # lines visible instead of covering them.
        if self.above:
            tw.update_idletasks()
            y = root_y - tw.winfo_height() - 4
        tw.wm_geometry(f"+{x}+{y}")

    def hide_tip(self, event=None):
        self.unschedule()
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

class MasterDashboardApp:
    # Per-sentence source badge in the report: stored key -> the label shown in Advanced Settings.
    SOURCE_DISPLAY_LABELS = {
        "off": "Off",
        "icon": "Icon only",
        "filename": "File name",
        "full": "Icon + file name",
    }

    @classmethod
    def _source_display_key(cls, label):
        """Settings label -> stored key. Unknown labels fall back to 'off' (the default)."""
        for key, text in cls.SOURCE_DISPLAY_LABELS.items():
            if text == label:
                return key
        return "off"

    def __init__(self, root):
        self.root = root
        self.root.title(f"Surasura - Immersion Architect Dashboard v{__version__}")
        self.root.geometry("520x550")   # trimmed to fit content (~525px) after the Library Content collapse
        self.root.resizable(True, True)
        self.root.minsize(520, 520)
        self.root.configure(bg=BG_COLOR)
        

        
        self.style = ttk.Style()
        self.apply_dark_theme()
        
        # Initialize variables for Analyzer settings
        self.var_exclude_single = tk.BooleanVar(value=True) 
        # Density-band word selection (replaces the retired min-freq slider).
        self.var_band = tk.StringVar(value="occasional")
        self.var_band_name = tk.StringVar(value="Occasional")     # slider-side label
        self.var_band_coverage = tk.StringVar(value="")           # "≈ 90% coverage · 801 words"
        self._band_hours_text = ""   # immersion-hours line, shown as a tooltip on the coverage text
        self._band_previews = None   # cached {band: preview} from the last analysis' token index
        self._preview_sig = None      # fingerprint of the inputs that produced _band_previews (cache key)
        self._effective_bands = list(word_selection.BANDS_ORDER)  # bands shown on the slider; a
        # trailing band identical to its neighbour (e.g. Native == Very Rare on this library) is hidden
        self._preview_gen = 0        # generation counter: async preview refreshes ignore stale results
        self._indexer_busy = False   # a background token-indexer subprocess is running
        self._last_index_check = 0.0  # debounce the cheap "does the library need re-indexing?" check
        self.var_open_app_mode = tk.BooleanVar(value=False)
        self.var_strategy = tk.StringVar(value="freq")
        self.var_target_coverage = tk.IntVar(value=90)
        self.var_split_length = tk.IntVar(value=3000)
        self.var_language = tk.StringVar(value="ja")
        self.var_reinforce = tk.BooleanVar(value=False) # For Chinese forced segmentation
        self.var_inline_completed = tk.BooleanVar(value=False) # Show completed files inline
        self.var_telemetry_enabled = tk.BooleanVar(value=True) # Anonymous Telemetry
        self.var_only_i_plus_one = tk.BooleanVar(value=False) # Only include i+1 sentences
        self.var_ensure_audio = tk.BooleanVar(value=False)    # Guarantee one example you can hear
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
        self.var_source_display = tk.StringVar(value="off")  # per-sentence source badge in the report
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

        # Generate stays disabled (with a short hint) until the library has content to analyze.
        self._update_generate_state()

        # Show onboarding if not completed
        if not self.onboarding_completed.get() and not os.environ.get("SURASURA_NO_UI_TIMERS"):
            try:
                from app.onboarding_gui import OnboardingGuide
                self.root.after(500, lambda: OnboardingGuide(self.root, self.complete_onboarding))
            except Exception as e:
                print(f"Warning: Could not show onboarding: {e}")
        
        # Add traces for auto-saving settings after initial load
        self.var_exclude_single.trace_add("write", self.save_settings)
        # The band slider fires this rapidly during a drag; a full save_settings (deep-merge + disk
        # write + UI relayout, ~5-10ms each) on every band boundary made the drag stutter. Debounce it
        # so the (cheap, cached) preview stays instant and the save happens once, ~250ms after you
        # settle (or immediately on mouse-release). See _save_band_debounced.
        self.var_band.trace_add("write", self._save_band_debounced)
        self.var_open_app_mode.trace_add("write", self.save_settings)
        self.var_inline_completed.trace_add("write", self.save_settings)
        self.var_telemetry_enabled.trace_add("write", self.save_settings)
        self.var_only_i_plus_one.trace_add("write", self.save_settings)
        self.var_ensure_audio.trace_add("write", self.save_settings)
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
        # Selecting a theme both persists it AND toggles the Zen Limit slider's visibility. (A single
        # <<ComboboxSelected>> binding — a second bind() without add="+" would replace this one.)
        self.combo_theme.bind("<<ComboboxSelected>>",
                              lambda e: (self.save_settings(), self._update_zen_visibility()))

        # Always-fresh preview: when the window regains focus (e.g. after editing content in
        # Explorer or importing words), cheaply check for a delta and re-index in the background.
        self.root.bind("<FocusIn>", lambda e: (self._maybe_launch_indexer(), self._update_generate_state()))
        # Deferred startup timers are skipped under test — a test destroys the window long before
        # they fire, and a pending `after` whose Tcl command died with the interpreter keeps firing
        # into nothing (see the _no_ui_timers fixture in tests/conftest.py). Guarding the callback
        # body is not enough; it is never invoked.
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            # And once shortly after startup, so the preview appears without a manual Generate.
            self.root.after(1500, lambda: self._maybe_launch_indexer(force=True))

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

        # Dark scrollbar (e.g. the Processing Log in Advanced Settings) — default renders it light.
        self.style.configure("Vertical.TScrollbar",
            background=SURFACE_COLOR, troughcolor=BG_COLOR, bordercolor=BG_COLOR,
            arrowcolor=TEXT_COLOR, darkcolor=SURFACE_COLOR, lightcolor=SURFACE_COLOR)
        self.style.map("Vertical.TScrollbar", background=[("active", ACCENT_COLOR), ("pressed", ACCENT_COLOR)])

    def update_strategy_ui(self):
        strategy = self.var_strategy.get()
        if strategy == "freq":
            self.freq_frame.pack(side=tk.TOP, fill=tk.X)
            self.coverage_frame.pack_forget()
            self._refresh_band_preview()
        else:
            self.freq_frame.pack_forget()
            self.coverage_frame.pack(side=tk.TOP, fill=tk.X)
            self.save_settings() # Save on switch

    # --- Density-band selection: slider + live preview (reads the last run's token index) ------
    def _save_band_debounced(self, *args):
        """Coalesce the band slider's saves. Each rapid var_band change reschedules a single save
        ~250ms out, so the drag itself does no disk work; a mouse-release flushes it immediately
        (_flush_band_save) so the setting is always persisted before the user can press Generate.
        skip_ui=True: a band change never affects the language-dependent UI, so we skip that relayout."""
        if getattr(self, "_band_save_after", None):
            try:
                self.root.after_cancel(self._band_save_after)
            except Exception:
                pass
        self._band_save_after = self.root.after(250, lambda: self.save_settings(skip_ui=True))

    def _flush_band_save(self, event=None):
        """Force any pending debounced band-save to happen now (bound to the slider's mouse-release)."""
        if getattr(self, "_band_save_after", None):
            try:
                self.root.after_cancel(self._band_save_after)
            except Exception:
                pass
            self._band_save_after = None
            self.save_settings(skip_ui=True)

    def _on_band_slide(self, value):
        """Slider moved: map its index to a band, update the side label, save, and refresh the
        preview lines. Pure arithmetic over cached counts — instant, no tokenization."""
        bands = self._effective_bands or word_selection.BANDS_ORDER
        try:
            idx = max(0, min(int(float(value)), len(bands) - 1))
        except (TypeError, ValueError):
            idx = 0
        band = bands[idx]
        self.var_band_name.set(word_selection.band_label(band))
        if self.var_band.get() != band:
            self.var_band.set(band)   # trace -> save_settings
        self._update_band_preview_labels(band)

    def _update_band_preview_labels(self, band):
        previews = self._band_previews
        if not previews or band not in previews:
            self.var_band_coverage.set("Generate a journey once to see live estimates.")
            self._band_hours_text = ""
            return
        p = previews[band]
        parts = [f"≈ {p['coverage_percent']:.1f}% coverage", f"{p['word_count']:,} words"]
        hrs = p.get("hours_between")
        if hrs and hrs > 0:
            # Compact, always-visible encounter rate; the full sentence stays in the tooltip.
            parts.append(f"every {self._fmt_hours(hrs)}")
            self._band_hours_text = f"You'll meet each word at least once every {self._fmt_hours(hrs)} of immersion."
        else:
            self._band_hours_text = ""
        self.var_band_coverage.set("   ·   ".join(parts))

    @staticmethod
    def _fmt_hours(hrs):
        """Human-friendly immersion time: minutes under an hour, else hours."""
        if hrs < 1:
            return f"~{max(1, round(hrs * 60))} minutes"
        if hrs < 10:
            return f"~{hrs:.1f} hours"
        return f"~{round(hrs)} hours"

    def _compute_effective_bands(self):
        """The bands the slider should actually offer. When the rare tail collapses (adjacent bands
        select IDENTICALLY at the min_count floor — e.g. Very Rare and Native pick the same words),
        the in-between band is redundant, so we drop it and KEEP the rarest one (Native) — the more
        meaningful/complete label to show. Falls back to all bands when there's no preview yet."""
        bands = list(word_selection.BANDS_ORDER)
        p = self._band_previews
        if not p:
            return bands

        def same(a, b):
            pa, pb = p.get(a), p.get(b)
            return (pa and pb and pa["word_count"] == pb["word_count"]
                    and abs(pa["coverage_percent"] - pb["coverage_percent"]) < 1e-9)

        while len(bands) > 1 and same(bands[-1], bands[-2]):
            bands.pop(-2)    # keep the rarest (Native); drop the redundant band just before it
        return bands

    def _apply_effective_bands(self):
        """Resize the slider to the currently-meaningful bands and keep the selection valid. A now-
        hidden band (e.g. Very Rare) folds into the last visible one (Native), which selects
        identically."""
        if not hasattr(self, "band_slider"):
            self._update_band_preview_labels(self.var_band.get())
            return
        bands = self._effective_bands or list(word_selection.BANDS_ORDER)
        self.band_slider.config(to=max(0, len(bands) - 1))
        band = self.var_band.get()
        if band not in bands:
            band = bands[-1]              # hidden band -> its identical, still-visible neighbour
            self.var_band.set(band)       # trace -> save; harmless (same selection)
        self.band_slider.set(bands.index(band))
        self.var_band_name.set(word_selection.band_label(band))
        self._update_band_preview_labels(band)

    def _refresh_band_preview(self, force=False):
        """Refresh the band-preview numbers WITHOUT blocking the GUI. Opening the SQLite store and
        reading the aggregate + the (multi-MB) known-words file can take a moment on a big library,
        so we do it on a worker thread: a "Calculating…" placeholder shows instantly (e.g. the
        moment you pick 'By Commonness'), and the real numbers land via the GUI queue when ready.

        Skips the worker entirely when nothing that affects the preview changed since the last
        successful compute (store, known words, ignore lists, selection settings) — this is what
        keeps repeated focus/strategy-switches from re-running the heavy read and stuttering the UI.
        Pass force=True right after an analyzer/indexer run: the store just changed and (under WAL)
        its .db mtime may not have moved yet, so we must recompute rather than trust the signature."""
        import threading
        lang = self.var_language.get() or "ja"
        sel = (getattr(self, "_current_settings", {}) or {}).get("logic", {}).get("selection", {})

        # Cache hit: same inputs as the last good compute -> reuse the cached previews, no worker.
        sig = self._preview_signature(lang, sel)
        if (not force and sig is not None and sig == getattr(self, "_preview_sig", None)
                and getattr(self, "_band_previews", None) is not None):
            self._update_band_preview_labels(self.var_band.get())
            return

        self._preview_gen = getattr(self, "_preview_gen", 0) + 1
        gen = self._preview_gen
        self.var_band_coverage.set("Calculating…")

        def _work():
            previews = self._compute_band_previews(lang, sel)
            self.gui_queue.put(lambda: self._apply_preview_result(gen, previews, sig))

        threading.Thread(target=_work, daemon=True).start()

    def _preview_signature(self, lang, sel):
        """Cheap stat-only fingerprint of everything the band preview depends on: the token store
        (its mtime moves whenever a run/indexer rewrites it), the known-words file, the ignore
        lists, and the selection settings. Returns None if it can't be computed (forces a refresh)."""
        try:
            from app.path_utils import get_user_files_path
            uf = get_user_files_path(lang)
            db = token_index.store_path_for(lang)
            db_mtime = os.path.getmtime(db) if os.path.exists(db) else 0
            known_path = os.path.join(uf, "KnownWord.json")
            ksig = token_index.known_signature(known_path)
            lists = tuple(
                os.path.getmtime(os.path.join(uf, n)) if os.path.exists(os.path.join(uf, n)) else 0
                for n in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt")
            )
            return (lang, db_mtime, ksig, lists, json.dumps(sel, sort_keys=True))
        except Exception:
            return None

    def _compute_band_previews(self, lang, sel):
        """The heavy read (token store + known-words file). Runs on a WORKER thread — it must NOT
        touch any tk widget; it only returns the {band: preview} dict (or None)."""
        try:
            store = token_index.open_store(lang)
            try:
                total = store.total_tokens()
                if not total:
                    return None
                from app.path_utils import get_user_files_path
                ignore_set = self._load_ignore_for_preview(lang)
                # Prefer the store's EXACT normalized known set when it's fresh (matches the current
                # KnownWord.json). Only when that cache is stale do we parse the multi-MB KnownWord.json
                # for the dictForm approximation — so the common (fresh) path never touches it.
                known_path = os.path.join(get_user_files_path(lang), "KnownWord.json")
                cached = store.get_cached_known(token_index.known_signature(known_path))
                if cached is not None:
                    known_tuples, known_lemmas = cached
                    freqs = store.unknown_frequencies(
                        known_tuples=known_tuples, known_lemmas=known_lemmas,
                        ignore_set=ignore_set, skip_singles=(lang == "ja"))
                else:
                    known_approx = self._load_known_approx(lang)
                    freqs = store.unknown_frequencies(
                        known_lemmas=known_approx, ignore_set=ignore_set, skip_singles=(lang == "ja"))
                avg_file = total / (store.file_count() or 1)
                return word_selection.band_previews(
                    freqs, sel.get("bands_ppm"), sel.get("min_count", word_selection.DEFAULT_MIN_COUNT),
                    avg_file, sel.get("minutes_per_file", word_selection.MINUTES_PER_FILE))
            finally:
                store.close()
        except Exception:
            return None

    def _apply_preview_result(self, gen, previews, sig=None):
        """Runs on the GUI thread (via the queue). Ignores results from a superseded refresh, then
        updates the cached previews, hides any redundant trailing band, and refreshes the labels.
        Records the input signature so an unchanged refresh can reuse this result without recomputing."""
        if gen != getattr(self, "_preview_gen", 0):
            return
        self._band_previews = previews
        # Cache the fingerprint only for a real result; a failed compute (None) leaves it unset so
        # the next refresh retries instead of caching an empty preview.
        self._preview_sig = sig if previews is not None else None
        self._effective_bands = self._compute_effective_bands()
        self._apply_effective_bands()

    def _load_ignore_for_preview(self, lang):
        """The ignore/blacklist/graduated words — cheap plain-text reads, loaded on every preview."""
        from app.path_utils import get_user_files_path
        uf = get_user_files_path(lang)
        ignore = set()
        for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
            try:
                with open(os.path.join(uf, name), encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if s and not s.startswith("#"):
                            ignore.add(s)
            except Exception:
                pass
        return ignore

    def _load_known_approx(self, lang):
        """Known lemmas WITHOUT the tokenizer (dictForm approximation). Only used when the store's
        normalized known-cache is stale — parsing KnownWord.json is the expensive bit on a big
        library, so it's kept off the common (fresh-cache) preview path."""
        from app.path_utils import get_user_files_path
        uf = get_user_files_path(lang)
        known = set()
        try:
            with open(os.path.join(uf, "KnownWord.json"), encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("words", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for e in entries:
                if e.get("knownStatus") == "KNOWN" or e.get("hasCard") == 1:
                    term = e.get("dictForm", "")
                    if term:
                        known.add(term)
        except Exception:
            pass
        return known

    def _maybe_launch_indexer(self, force=False):
        """Keep the token store (and thus the band preview) always-fresh: if the library or the
        known-words file changed since the store was last built, launch a short background indexer
        SUBPROCESS (so the tokenizer never enters the GUI) and refresh the preview when it finishes.
        The pre-check is stat-only (no tokenizer); debounced; never overlaps itself."""
        if os.environ.get("SURASURA_NO_AUTOINDEX") or self._indexer_busy:
            return
        import time
        now = time.monotonic()
        if not force and (now - self._last_index_check) < 2.0:
            return
        self._last_index_check = now
        try:
            lang = self.var_language.get() or "ja"
            from app.path_utils import get_data_path, get_user_files_path
            data_dir = get_data_path(lang)
            files = []
            for folder in ("HighPriority", "LowPriority", "GoalContent"):
                base = os.path.join(data_dir, folder)
                if os.path.isdir(base):
                    for r, _d, names in os.walk(base):
                        files += [os.path.join(r, n) for n in names
                                  if n.lower().endswith((".txt", ".md", ".srt", ".ass"))]
            store = token_index.open_store(lang)
            try:
                known_file = os.path.join(get_user_files_path(lang), "KnownWord.json")
                need = (store.needs_reconcile(files)
                        or store.get_cached_known(token_index.known_signature(known_file)) is None)
            finally:
                store.close()
        except Exception:
            return
        if not need:
            return

        self._indexer_busy = True

        def _done():
            self._indexer_busy = False
            self._refresh_band_preview(force=True)   # store just changed -> recompute, don't trust cache

        self.run_command_async(['indexer.py', '--language', self.var_language.get()],
                               "Indexing", on_complete=_done)

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

        # A language switch points at a different store — re-index that language in the background.
        self._maybe_launch_indexer(force=True)
        self._update_generate_state()   # different language -> different library -> re-check emptiness

    def _library_has_content(self):
        """True if the current language's library has at least one analyzable content file. The
        extensions MUST match what the analyzer actually reads (analyzer.get_files_recursive:
        .txt/.md/.srt/.ass) — otherwise Generate could enable on files the analysis then ignores
        (e.g. a tier of only .vtt), yielding an empty journey."""
        from app.path_utils import get_data_path
        base = get_data_path(self.var_language.get() or "ja")
        for tier in ("HighPriority", "LowPriority", "GoalContent"):
            d = os.path.join(base, tier)
            if os.path.isdir(d):
                for _r, _dirs, files in os.walk(d):
                    if any(f.lower().endswith((".txt", ".md", ".srt", ".ass")) for f in files):
                        return True
        return False

    def _update_generate_state(self):
        """Disable 'Generate Journey' (with a short hint) while the library is empty — there's nothing
        to analyze until content is added via Import Content. Re-checked on focus and language change."""
        if not hasattr(self, "btn_journey"):
            return
        has = self._library_has_content()
        self.btn_journey.config(state=tk.NORMAL if has else tk.DISABLED)
        if has:
            self.lbl_generate_hint.pack_forget()
        else:
            self.lbl_generate_hint.pack(fill=tk.X, pady=(2, 0))

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

        # 2. Library Tools — a single entry point. Extract/Splice and the YouTube downloader now live
        # INSIDE the Content Manager (opened by this button); the ▷ Preview stays on the main page.
        lib_frame = ttk.LabelFrame(main_frame, text=" 📦 Library Content", padding="10")
        lib_frame.pack(fill=tk.X, pady=(0, 5))

        btn_open_data = ttk.Button(lib_frame, text="Import Content", style="Action.TButton",
                                    command=self.run_content_importer)
        btn_open_data.pack(side=tk.LEFT, padx=(0, 5), expand=True, fill=tk.X)
        ToolTip(btn_open_data, "Add and manage your immersion content — files, EPUB / Anki, and YouTube.")
        # self.btn_youtube stays None (declared in __init__): the downloader button moved into the
        # Content Manager, so update_youtube_visibility() safely no-ops on the main GUI.

        # 3. Analyzer Tools
        analyze_frame = ttk.LabelFrame(main_frame, text=" 🔍 Analysis", padding="10")
        analyze_frame.pack(fill=tk.X, pady=(0, 5)) # Reduced pady 10 -> 5

        # Strategy Selection
        strategy_frame = ttk.Frame(analyze_frame)
        strategy_frame.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Label(strategy_frame, text="Generation Mode:").pack(side=tk.LEFT)
        ttk.Radiobutton(strategy_frame, text="By Commonness", variable=self.var_strategy, value="freq", command=self.update_strategy_ui).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Radiobutton(strategy_frame, text="Target % Coverage", variable=self.var_strategy, value="coverage", command=self.update_strategy_ui).pack(side=tk.LEFT, padx=(10, 0))

        # Dynamic Options Frame
        self.options_container = ttk.Frame(analyze_frame)
        self.options_container.pack(fill=tk.X, pady=(0, 8))

        # 1. Density-band slider (Default) — Core .. Native, with a live preview.
        self.freq_frame = ttk.Frame(self.options_container)

        # Left label + a half-length slider + the current band name to its right.
        band_row = ttk.Frame(self.freq_frame)
        band_row.pack(fill=tk.X)
        ttk.Label(band_row, text="Rarity:").pack(side=tk.LEFT, padx=(0, 8))
        # Band name pinned to the right (fixed width so it doesn't jitter as the label changes),
        # with a margin so it's never flush against the edge; the slider fills the space between.
        ttk.Label(band_row, textvariable=self.var_band_name, width=11,
                  foreground=ACCENT_COLOR, font=("Segoe UI", 11, "bold")).pack(side=tk.RIGHT, padx=(8, 14))
        self.band_slider = tk.Scale(band_row, from_=0, to=len(word_selection.BANDS_ORDER) - 1,
                                    orient=tk.HORIZONTAL, resolution=1, showvalue=False,
                                    command=self._on_band_slide,
                                    bg=BG_COLOR, fg=TEXT_COLOR, highlightthickness=0,
                                    activebackground=ACCENT_COLOR, troughcolor=SURFACE_COLOR)
        self.band_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        # Persist the setting the instant the drag ends (the debounce timer is the fallback).
        self.band_slider.bind("<ButtonRelease-1>", self._flush_band_save)
        # Shown ABOVE so it doesn't cover the coverage line below.
        ToolTip(self.band_slider,
                "Which words to include, by how common they are in your library:\n\n"
                "• Core: only the most common words (~50% coverage)\n"
                "• Native: everything except one-off words (~99% coverage)\n\n"
                "Slide right to learn rarer, less frequent words.",
                above=True)

        # Live preview line + an info (ppm) icon. Hovering the coverage text reveals the
        # immersion-time estimate (kept as a tooltip so it doesn't take extra space).
        preview_row = ttk.Frame(self.freq_frame)
        preview_row.pack(fill=tk.X, pady=(4, 0))
        cov_lbl = ttk.Label(preview_row, textvariable=self.var_band_coverage,
                            foreground=SECONDARY_COLOR)
        cov_lbl.pack(side=tk.LEFT)
        ToolTip(cov_lbl, lambda: self._band_hours_text, above=True)
        # Force a font that reliably carries the circled-i glyph (U+24D8). The default UI font on
        # some Windows 10 builds lacks it, so the icon rendered invisible there (tooltip still worked).
        info_lbl = ttk.Label(preview_row, text="ⓘ", foreground="#8a8a8a", font=("Segoe UI Symbol", 11))
        info_lbl.pack(side=tk.RIGHT)
        # No question-mark cursor; instead the icon brightens toward the coverage colour on hover.
        info_lbl.bind("<Enter>", lambda e: info_lbl.config(foreground="#4db6ac"), add="+")
        info_lbl.bind("<Leave>", lambda e: info_lbl.config(foreground="#8a8a8a"), add="+")
        ToolTip(info_lbl,
                "Measured in ppm (parts per million):\n"
                "how many times a word appears\n"
                "per million words in your library.\n"
                "Lower ppm = rarer words.")

        # 2. Coverage Entry (Hidden initially)
        self.coverage_frame = ttk.Frame(self.options_container)
        
        ttk.Label(self.coverage_frame, text="Target Coverage (%):").pack(side=tk.LEFT)
        ttk.Entry(self.coverage_frame, textvariable=self.var_target_coverage, width=5).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Label(self.coverage_frame, text="(e.g. 90, 95)").pack(side=tk.LEFT, padx=(5, 0))
        ToolTip(self.coverage_frame, "Generate a word list to reach this cumulative coverage % across all selected files.")

        # Initialize UI state
        self.update_strategy_ui()

        # The single "Generate Journey" action lives in the Results Viewer below (it generates the
        # analysis when needed AND opens the report — the old separate "View" step was merged in).

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
        
        # Zen Mode Limit Slider — only shown when the Zen Mode theme is selected (wired below).
        self.zen_limit_frame = ttk.Frame(view_frame)
        self.zen_limit_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(self.zen_limit_frame, text="Zen Limit:").pack(side=tk.LEFT)
        zen_slider_main = tk.Scale(self.zen_limit_frame, from_=25, to=125, orient=tk.HORIZONTAL,
                                   variable=self.var_zen_limit, showvalue=False,
                                   bg=BG_COLOR, fg=TEXT_COLOR, highlightthickness=0,
                                   activebackground=ACCENT_COLOR, troughcolor=SURFACE_COLOR, length=300)
        zen_slider_main.pack(side=tk.LEFT, padx=(5, 10))
        ToolTip(zen_slider_main, "Limit words for Zen Mode (25-125).")

        # Value Label on the right
        ttk.Label(self.zen_limit_frame, textvariable=self.var_zen_limit, width=4).pack(side=tk.LEFT)
        # The one main action: (re)generate the journey and open it. It reuses the last analysis
        # when nothing relevant changed — so theme / Zen limit apply instantly without a recompute.
        # The small red YouTube-preview button sits to its right (shown only when that feature is on).
        self.journey_row = ttk.Frame(view_frame)
        self.journey_row.pack(fill=tk.X)
        self.btn_journey = ttk.Button(self.journey_row, text="Generate Journey", style="Action.TButton",
                                 command=self.run_analyzer)
        self.btn_journey.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ToolTip(self.btn_journey, "Generate your learning path and open it in the browser. Reuses the last "
                             "analysis if nothing changed, so theme / Zen limit apply instantly.")

        self.btn_preview = ttk.Button(self.journey_row, text="▷", style="Youtube.TButton", width=3,
                                      command=self.open_youtube_preview)
        ToolTip(self.btn_preview, "Preview a YouTube video/playlist against your library (quick look, no full re-run).")

        # Short hint shown ONLY while the library is empty; Generate is disabled until content is added.
        self.lbl_generate_hint = ttk.Label(view_frame, text="Add content first — tap Import Content above.",
                                            foreground="#aaaaaa", font=("Segoe UI", 8, "italic"))

        # The Zen Limit only affects the Zen Mode theme -> show that slider only when it's chosen.
        # (The <<ComboboxSelected>> binding that drives this lives with the theme-save binding in
        # __init__; here we just set the initial state.)
        self._update_zen_visibility()
        
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
        self.settings_window.geometry("850x680")
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

        # Per-sentence source badge. Presentation only — changing it re-renders the report but
        # never re-analyzes (see analyzer.compute_render_signature).
        src_frame = ttk.Frame(group_ui)
        src_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(src_frame, text="Sentence source:").pack(side=tk.LEFT)
        combo_src = ttk.Combobox(src_frame, values=list(self.SOURCE_DISPLAY_LABELS.values()),
                                 state="readonly", width=16)
        combo_src.set(self.SOURCE_DISPLAY_LABELS.get(self.var_source_display.get(), "Off"))
        combo_src.pack(side=tk.LEFT, padx=(5, 0))
        combo_src.bind("<<ComboboxSelected>>",
                       lambda e: (self.var_source_display.set(self._source_display_key(combo_src.get())),
                                  self.save_settings()))
        ToolTip(combo_src, "Show which file each example sentence came from, to the right of the "
                           "sentence. Hover it for the full path; click to copy.")

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

        chk_ensure_audio = ttk.Checkbutton(group_logic, text="Always include a sentence with audio", variable=self.var_ensure_audio)
        chk_ensure_audio.pack(anchor=tk.W)
        ToolTip(chk_ensure_audio, "If none of a word's examples came from a video, give the last slot to one that did - so you can always study it by ear. Needs 2+ example sentences.")

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
        btn_export_freq.pack(fill=tk.X, pady=(0, 5))
        ToolTip(btn_export_freq, "Export internal frequency list for Migaku/Yomitan.")

        btn_reading_words = ttk.Button(group_data, text="Export Reading Words", command=self.generate_reading_words, width=20)
        btn_reading_words.pack(fill=tk.X)
        ToolTip(btn_reading_words, "A Yomitan list of words you'll read but hardly ever hear. If a word shows up in it while mining, make it a reading card.")

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

    def _update_zen_visibility(self, event=None):
        """Show the Zen Limit slider only when the Zen Mode theme is selected (it has no effect on
        any other theme). Re-packed BEFORE the journey button so it keeps its position above it."""
        if not hasattr(self, "zen_limit_frame"):
            return
        if self.combo_theme.get() == "Zen Mode":
            if not self.zen_limit_frame.winfo_ismapped():
                self.zen_limit_frame.pack(fill=tk.X, pady=(0, 8), before=self.journey_row)
        else:
            self.zen_limit_frame.pack_forget()

    def load_settings(self):
        try:
            settings = settings_manager.load_settings()
            self._current_settings = settings

            self.var_exclude_single.set(settings.get("exclude_single", True))
            self.var_open_app_mode.set(settings.get("open_app_mode", False))
            
            theme = settings.get("theme", "Dark Flow")
            if theme in self.combo_theme['values']:
                self.combo_theme.set(theme)
            self._update_zen_visibility()   # .set() fires no event -> sync the slider to the loaded theme

            self.var_strategy.set(settings.get("strategy", "freq"))
            self.var_target_coverage.set(settings.get("target_coverage", 90))
            self.var_split_length.set(settings.get("split_length", 3000))
            
            lang = settings.get("target_language", "ja")
            if not lang: lang = "ja"
            self.var_language.set(lang)

            self.var_reinforce.set(settings.get("reinforce_segmentation", False))
            src_mode = settings.get("source_display", "off")
            self.var_source_display.set(src_mode if src_mode in self.SOURCE_DISPLAY_LABELS else "off")
            self.var_telemetry_enabled.set(settings.get("telemetry_enabled", True))
            self.var_only_i_plus_one.set(settings.get("only_i_plus_one", False))
            self.var_ensure_audio.set(settings.get("ensure_audio_example", False))
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

            # Density-band selection: restore the chosen band and slider position.
            sel = self.logic_settings.get("selection", {})
            band = sel.get("band", "occasional")
            if band not in word_selection.BANDS_ORDER:
                band = "occasional"
            self.var_band.set(band)
            self.var_band_name.set(word_selection.band_label(band))
            if hasattr(self, "band_slider"):
                try:
                    self.band_slider.set(word_selection.BANDS_ORDER.index(band))
                except Exception:
                    pass

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

    def save_settings(self, *args, skip_ui=False):
        try:
            cur = getattr(self, "_current_settings", {}) or {}
            cur_ctx = cur.get("logic", {}).get("context", {}) if isinstance(cur.get("logic"), dict) else {}
            # Build settings dict from GUI vars
            settings = {
                "exclude_single": self.var_exclude_single.get(),
                "open_app_mode": self.var_open_app_mode.get(),
                "theme": self.combo_theme.get(),
                "strategy": self.var_strategy.get(),
                "target_coverage": self._iv(self.var_target_coverage, cur.get("target_coverage", 90)),
                "split_length": self._iv(self.var_split_length, cur.get("split_length", 3000)),
                "target_language": self.var_language.get(),
                "reinforce_segmentation": self.var_reinforce.get(),
                "source_display": self.var_source_display.get(),
                "telemetry_enabled": self.var_telemetry_enabled.get(),
                "only_i_plus_one": self.var_only_i_plus_one.get(),
                "ensure_audio_example": self.var_ensure_audio.get(),
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
                    # Persist the whole selection block (bands_ppm / min_count / minutes_per_file are
                    # user-editable in settings.json, like 'weights'); the slider sets 'band'.
                    "selection": {
                        **self.logic_settings.get("selection", {}),
                        "band": self.var_band.get(),
                    },
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

            # Update UI state (enable/disable language specific options). Skipped for band-slider
            # saves — a commonness-band change never affects the language-dependent UI, and the
            # relayout was part of the drag stutter.
            if not skip_ui and not getattr(self, '_lock_ui_updates', False):
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
            
    def run_command_async(self, cmd, desc, capture_output=False, show_spinner=False, on_complete=None):
        """Runs a command with optional output redirection to the terminal.

        on_complete: optional zero-arg callable run on the GUI thread after the process exits
        (e.g. refreshing the band preview once a new analysis has written its token index)."""
        
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
                'frequency_list_gui.py': 'frequency_list_manager',
                'indexer.py': 'index'
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

                # SET ENVIRONMENT: UTF-8 stdio (so the strict-UTF-8 stdout capture below never
                # chokes on locale-encoded bytes) + project root on PYTHONPATH in source mode.
                env = build_subprocess_env(is_frozen())
                
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
                    errors='replace',   # belt-and-suspenders: a stray non-UTF-8 byte in child output
                                        # must never crash the capture loop (it only feeds the log)
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
                if on_complete:
                    self.gui_queue.put(on_complete)

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
        # else: density-band selection. The analyzer reads logic.selection (band + ppm floors)
        # from settings, which are saved before this run. Raw --min-freq is retired from the UI
        # (kept only as a CLI override); the band slider writes logic.selection.band.

        args.append('--static')
        
        # Add Language
        args.append(f'--language={self.var_language.get()}')
        
        # Add Reinforce Flag if applicable
        if self.var_language.get() == 'zh' and self.var_reinforce.get():
            args.append('--reinforce')
            
        if self.var_ensure_audio.get():
            args.append('--ensure-audio-example')

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

        # --- Fast no-change path: reopen the existing report WITHOUT spawning the analyzer ---
        # If nothing analysis-affecting changed since the last run AND presentation is unchanged AND
        # the report exists, just reopen it in-process. This skips the whole analyzer subprocess
        # (a ~1-2s cold-start in a frozen build). It uses the analyzer's OWN signature functions, so
        # the GUI's decision can never diverge from what the analyzer would decide. Any hiccup falls
        # through to the normal subprocess run — the fast path is a pure optimization, never required.
        if self._try_open_existing_report(args):
            return

        self.run_command_async(args, "Analyzer", capture_output=True, show_spinner=True,
                               on_complete=lambda: self._refresh_band_preview(force=True))

    def _try_open_existing_report(self, args):
        """Return True and reopen the existing report if a full analysis is provably unnecessary.

        Mirrors the analyzer's own skip gate (compute_run_signature + outputs-present + render-sig),
        computed in-process so we can avoid the subprocess entirely. Conservative: only the pure
        'nothing changed, same presentation' case short-circuits; a changed theme/zen or any missing
        piece falls through so the subprocess handles the re-render/analysis as before."""
        try:
            from app import analyzer as _analyzer
            from app import token_index as _ti
            from app.path_utils import get_user_file

            lang = self.var_language.get()
            a = _analyzer.parse_analysis_args(args[1:])   # args[0] is the 'analyzer.py' script name
            found = _analyzer.resolve_found_files(lang, verbose=False)
            sig = _analyzer.compute_run_signature(lang, found, a)
            if not sig:
                return False

            results_dir = get_user_file("results")
            report = os.path.join(results_dir, "reading_list_static.html")
            outputs_present = all(os.path.exists(os.path.join(results_dir, f)) for f in
                                  ("priority_learning_list.csv", "progressive_learning_list.csv", "word_stats.json"))
            if not (outputs_present and os.path.exists(report)):
                return False

            render_sig = _analyzer.compute_render_signature(a)   # shared: cannot drift from the engine
            store = _ti.open_store(lang)
            try:
                stored_sig = store.get_meta("last_run_signature")
                stored_render = store.get_meta("last_render_sig")
            finally:
                store.close()

            # Analysis unchanged AND presentation unchanged -> reopen the existing report as-is.
            if stored_sig == sig and stored_render == render_sig:
                try:
                    from app import static_html_generator
                except ImportError:
                    import static_html_generator
                static_html_generator.open_report(app_mode=a.app_mode)
                self._refresh_band_preview()   # inputs unchanged -> cache hit, no recompute
                return True
        except Exception:
            pass  # fall through to the normal subprocess run
        return False

    def generate_reading_words(self):
        """Export the reading-only words as a word list.

        Same three formats as the ordinary frequency-list export — a Migaku user can't do anything
        with a Yomitan ZIP, and two export buttons that behave differently is just confusing. The
        list is a CSV with the same columns as the priority list, so every exporter reads it as-is.
        """
        from app.path_utils import get_user_file

        self._show_export_dialog(
            os.path.join(get_user_file("results"), "reading_words.csv"),
            initial_name="Surasura Reading Words",
            empty_message=("Generate your Vocab Journey first — the reading-words list is built "
                           "during analysis.\n\nIf you have already run one, then no read-only "
                           "words were found yet, which usually means there isn't enough content "
                           "for the comparison to be confident."))

    def generate_frequency_list(self):
        """Show dialog to choose export format"""
        from app.path_utils import get_user_file

        self._show_export_dialog(
            os.path.join(get_user_file("results"), "priority_learning_list.csv"),
            initial_name="MY Immersion FreqList",
            empty_message="You need to run an analysis first to generate data.")

    def _show_export_dialog(self, source_csv, initial_name, empty_message):
        """Format picker shared by both word-list exports.

        Only the source file and the suggested filename differ, so the dialog is written once —
        adding a format later can't leave one button behind the other.
        """
        # Rows, not bytes — a header-only list is "no data" too (see csv_has_data_rows).
        if not csv_has_data_rows(source_csv):
            messagebox.showwarning("No Data", empty_message)
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
        btn_migaku = ttk.Button(wrapper, text="Migaku", command=lambda: self.export_wrapper(dialog, "migaku", source_csv, initial_name))
        btn_migaku.pack(fill=tk.X, pady=5)
        ToolTip(btn_migaku, "Export as a JSON array (Standard Migaku Format).")
        
        btn_yomitan = ttk.Button(wrapper, text="Yomichan / Yomitan", command=lambda: self.export_wrapper(dialog, "yomitan", source_csv, initial_name))
        btn_yomitan.pack(fill=tk.X, pady=5)
        ToolTip(btn_yomitan, "Export as a frequency dict ZIP file (v3 format).")
        
        btn_txt = ttk.Button(wrapper, text="Word List (Text)", command=lambda: self.export_wrapper(dialog, "txt", source_csv, initial_name))
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


    def export_wrapper(self, dialog, format_type, csv_path, initial_name="MY Immersion FreqList"):
        from tkinter import filedialog
        from app.frequency_exporter import FrequencyExporter
        
        dialog.destroy()
        
        file_types = []
        def_ext = ""
        
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
