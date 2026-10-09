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
from app.update_checker import get_update_info, classify_update, parse_version
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
# The logo's blue (app/assets/images/app_icon.png) — the Generate button's "run me" border.
SURASURA_BLUE = "#1a6bb5"
CHECK_GRAY = "#8a8a8a"   # the Generate button's "up to date" check — quiet, like the ⓘ beside the slider


def journey_is_current(args, language):
    """Would Generate compute anything new? (`analyzer.journey_is_current`: it lives beside the run signature
    it asks, Library_Store_Spec §7.) Imported on call, so the dashboard never loads the analyzer at start."""
    from app import analyzer as _analyzer
    return _analyzer.journey_is_current(args, language)


def anki_sync_is_set_up(settings):
    """Has the user chosen Anki decks in the Anki window, for any language? The Anki-only settings
    are shown only then — someone without Anki never sees them (Junban_Backlog_Spec §11.1 item 3)."""
    decks = (settings or {}).get("anki_sync_decks")
    return isinstance(decks, dict) and any(bool(chosen) for chosen in decks.values())


def build_subprocess_env(frozen=None):
    """`path_utils.build_subprocess_env` (moved there so the Tk-free library store can use it too)."""
    from app.path_utils import build_subprocess_env as _build
    return _build(frozen)


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


# Settings -> Data & System -> Credits (a hover): every data source Surasura ships or is built from — the licences ask
# for it wherever the data goes, and an in-place update carries only the app, never README. Keep it with README's Data
# Credits, and with the generated modules that name their source (app/*_data.py). {jmdict} is JMdict's own date.
DATA_CREDITS = """Data credits — what Surasura ships or is built from

Dictionaries
• JMdict and JMnedict (JMdict created {jmdict}) — the Electronic Dictionary Research and Development Group (EDRDG), CC BY-SA 4.0: the set phrases, which compounds are phrases or titles, the お / ご words of their own, the words the tokenizer cuts at their grammar (くだらない, いつも), kanji spellings, the one-kanji words the list can offer, and person names (via anki_miner's name lists). Those tables are shared under the same licence.
• UniDic, as unidic-lite — the UniDic Consortium, BSD licence; read by MeCab (BSD) through fugashi (MIT): how Japanese is split into words.
• jieba — MIT licence: how Chinese is split into words.
• OpenCC 1.4.2 — Carbo Kuo and contributors, Apache License 2.0: Simplified and Traditional Chinese, Traditional in Taiwan's standard characters.
• CC-CEDICT — MDBG, CC BY-SA 4.0: which of jieba's phrases are words, the numbers and doubled forms Chinese counts as their word, the Traditional spellings read as their Simplified pair, the surnames a name jieba guesses starts with, and the Chinese measure words. Those tables (app/cedict_data.py, and those phrases of app/zh_script_data.py) are shared under the same licence.
• Universal Dependencies Chinese treebanks (GSDSimp, HK, CFL) — CC BY-SA 4.0: which Chinese counts are a number and a measure word (一个 is 一 + 个).

Frequency lists (ranks only)
• JPDB 2024 and Jiten: which compounds, affixed words, set phrases, adverbs cut at their particles and one-kanji words are words, and which words live only inside a phrase.
• TMW Netflix, Anime & J-drama, Novels and VN lists: the 文 reading-word badge.

Text, counted into statistics only (never a sentence)
• RealPersonaChat — Yamashita et al. (2023), CC BY-SA 4.0.
• Aozora Bunko — public-domain works, via aozorabunko-clean (CC BY 4.0).
• Japanese and Chinese Wikipedia — Wikipedia contributors, CC BY-SA 4.0.
• Leipzig Corpora Collection — Universität Leipzig, CC BY 4.0: Japanese news and web text, Chinese news.
• Tatoeba — CC BY 2.0 FR. KdConv — Zhou et al. (2020), Apache License 2.0. Chinese Wikinews — CC BY 4.0.

The shared パターン data is shared under CC BY-SA 4.0."""


def data_credits():
    """DATA_CREDITS with JMdict's date, as the shipped dictionary table records it ("unknown" when it can't be read)."""
    try:
        from app import dictionary_data
        created = dictionary_data.JMDICT_CREATED
    except Exception:
        created = ""
    return DATA_CREDITS.replace("{jmdict}", created or "unknown")


class ToolTip:
    def __init__(self, widget, text, above=False, wrap=300):
        self.widget = widget
        self.text = text          # str, or a zero-arg callable returning the current text
        self.above = above        # show above the widget (e.g. so a slider's preview stays visible)
        self.wrap = wrap          # the width a long tip wraps at (px): wider for a list (Settings' Credits)
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
        wrap = self.wrap if len(text) > 50 else 0
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
        elif self.wrap != 300:
            # A tall tip (Settings' Credits) stays on the screen instead of running off its bottom.
            tw.update_idletasks()
            y = max(0, min(y, tw.winfo_screenheight() - tw.winfo_height() - 40))
        tw.wm_geometry(f"+{x}+{y}")

    def hide_tip(self, event=None):
        self.unschedule()
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

# Junban's keys a dashboard save carries only as settings.json holds them — never a default into a 2.5 user's file:
# Connect's preview's (P1.4-1: your own cards' tag, "order all"; shown in 順 only while it is on) and the fast
# re-plan's preview switch, its language and deck (E1.1 04 §1; 順's option, saved once touched).
JUNBAN_AS_WRITTEN = ("junban_own_tag", "junban_order_all",
                     "junban_replan_preview", "junban_replan_language", "junban_replan_deck")


def carry_as_written(out, keys):
    """Copy each of `keys` that settings.json holds, as the file holds it, into `out` (a save being built): a key the
    user set is never dropped, and a default is never written into a file that lacks it. No file, or one that can't be
    read, holds none of them."""
    try:
        from app.path_utils import get_user_file, read_text
        as_is = json.loads(read_text(get_user_file("settings.json")))
    except Exception:
        as_is = {}
    if isinstance(as_is, dict):
        for key in keys:
            if key in as_is:
                out[key] = as_is[key]
    return out


class MasterDashboardApp:
    # Per-sentence source badge in the report: stored key -> the label shown in Advanced Settings.
    SOURCE_DISPLAY_LABELS = {
        "off": "Off",
        "icon": "Icon only",
        "filename": "File name",
        "full": "Icon + file name",
    }

    # Word lookup button (⌕): stored key -> the label shown in Advanced Settings. The key is sent
    # to Nadeshiko verbatim as ?category=, so 'all' means "no category filter" (no query at all).
    WORD_SEARCH_LABELS = {
        "all": "All",
        "anime": "Anime",
        "liveaction": "Live action",
        "youtube": "YouTube",
    }

    @classmethod
    def _source_display_key(cls, label):
        """Settings label -> stored key. Unknown labels fall back to 'off' (the default)."""
        for key, text in cls.SOURCE_DISPLAY_LABELS.items():
            if text == label:
                return key
        return "off"

    @classmethod
    def _word_search_key(cls, label):
        """Settings label -> stored key. Unknown labels fall back to 'all' (the default)."""
        for key, text in cls.WORD_SEARCH_LABELS.items():
            if text == label:
                return key
        return "all"

    # Chinese script (`zh_script`): stored key -> the label shown under Language & Parsing.
    ZH_SCRIPT_LABELS = {
        "asis": "As-is",
        "s": "Simplified (简体)",
        "t": "Traditional (繁體)",
    }

    @classmethod
    def _zh_script_key(cls, label):
        """Settings label -> stored key. Unknown labels fall back to 'asis' (the default)."""
        for key, text in cls.ZH_SCRIPT_LABELS.items():
            if text == label:
                return key
        return "asis"

    # Kana in ( ) right after kanji in a Japanese book (`logic.paren_readings`, read by
    # analyzer.strip_text_conventions): stored key -> the label shown under Language & Parsing.
    PAREN_READINGS_LABELS = {
        "hiragana": "Hiragana only (recommended)",
        "any": "Any kana",
        "off": "Keep as text",
    }

    @classmethod
    def _paren_readings_key(cls, label):
        """Settings label -> stored key. Unknown labels fall back to 'hiragana' (the default)."""
        for key, text in cls.PAREN_READINGS_LABELS.items():
            if text == label:
                return key
        return "hiragana"

    def _effective_zh_script(self, lang):
        """The conversion that applies to `lang` right now — "asis" unless it's Chinese with a script
        chosen. UI thread only (reads a Tk variable); workers get it passed in."""
        from app.zh_script import effective
        return effective(lang, self.var_zh_script.get())

    def __init__(self, root):
        self.root = root
        self.root.title(f"Surasura - Immersion Architect Dashboard v{__version__}")
        self.root.geometry("520x550")   # trimmed to fit content (~525px) after the Library Content collapse
        self.root.resizable(True, True)
        self.root.minsize(520, 520)
        self.root.configure(bg=BG_COLOR)

        # The Rarity slider's first refresh decodes tables before it can count — the compound table, the one-kanji
        # words, KnownWord.json's ignored entries: about a quarter of a second on a large library. Decoded here, in
        # the background while the window is built, the refresh reads only the store (token_index.prepare_preview).
        # Skipped under test, as the deferred startup timers are: no background work racing a test's patches.
        self._preview_prepared = None
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self._preview_prepared = threading.Thread(target=self._prepare_preview, daemon=True)
            self._preview_prepared.start()

        self.style = ttk.Style()
        self.apply_dark_theme()
        
        # Initialize variables for Analyzer settings
        self.var_exclude_single = tk.BooleanVar(value=True) 
        # Density-band word selection (replaces the retired min-freq slider).
        self.var_band = tk.StringVar(value="occasional")
        # Automatic rarity (logic.selection.auto): the band is picked for you and the slider locked on
        # it — display only, never written to var_band (turning it off is the one exception, D3).
        self.var_auto_band = tk.BooleanVar(value=False)
        self._band_locked = False    # the slider currently shows that lock (_show_band_lock)
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
        self.var_zh_script = tk.StringVar(value="asis")  # read all Chinese as one script (asis/s/t)
        self.var_paren_readings = tk.StringVar(value="hiragana")  # 漢字(かな) in a book: hiragana/any/off
        # Names are one word, not pieces (app/names.py), Japanese only: katakana names, names the library repeats,
        # kanji names, a story's own kanji terms — each its own switch (logic.names_*), on by default.
        self.var_names_katakana = tk.BooleanVar(value=True)
        self.var_names_recurring = tk.BooleanVar(value=True)
        self.var_names_kanji = tk.BooleanVar(value=True)
        self.var_names_work_terms = tk.BooleanVar(value=True)
        # Phrases and titles as one word (logic.phrases_and_titles), Japanese only, on by default.
        self.var_phrases_and_titles = tk.BooleanVar(value=True)
        # Pronouns with a suffix as one word (logic.pronoun_bases), Japanese only, on by default.
        self.var_pronoun_bases = tk.BooleanVar(value=True)
        # Idioms and set phrases on your list (logic.phrase_rows), Japanese only, on by default.
        self.var_phrase_rows = tk.BooleanVar(value=True)
        # Ignore names (logic.ignore_names), Japanese only, off by default: a learner learns names too.
        self.var_ignore_names = tk.BooleanVar(value=False)
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
        self.var_hide_audio = tk.BooleanVar(value=False)
        self.var_enable_youtube = tk.BooleanVar(value=False)
        self.youtube_risk_acknowledged = False
        self.var_enable_preview = tk.BooleanVar(value=False)
        self.var_enable_koe = tk.BooleanVar(value=False)  # Gemini speech for report sentences
        self.var_enable_reels = tk.BooleanVar(value=False)  # local video -> one mineable reel
        self.var_enable_junban = tk.BooleanVar(value=False)  # reorder Anki's new-card queue
        self.var_anki_sync_auto = tk.BooleanVar(value=False)  # pull known words from a running Anki
        self.var_anki_backlog_on_generate = tk.BooleanVar(value=True)  # Generate reads the Anki backlog
        self.var_anki_auto_generate = tk.BooleanVar(value=False)  # Generate quietly on new known words
        self.anki_sync_window = None
        # The Anki window's syncs and the background auto-sync append to the same file; one lock
        # so two appends can never interleave (each re-reads before writing, but not atomically).
        self._anki_sync_lock = threading.Lock()
        # The throttles start as "never", not 0.0: on Windows time.monotonic() counts from when the
        # computer started, so 0.0 read as "just now" and turned the focus sync, 順's reorder and the
        # automatic Generate away for the first minutes after every boot.
        self._last_anki_sync = float("-inf")
        self._anki_spin_job = None
        # Connect's session start (P2.3, `_connect_session`): the last look at Anki, and whether one is running.
        self._connect_looked = float("-inf")
        self._connect_looking = False
        self._connect_opened = False        # the window's first look (the only one that may open Anki) has run
        # Junban's automatic reorder (a test option in settings.json) — the same shape as the sync.
        self._junban_auto_lock = threading.Lock()
        self._last_junban_auto = float("-inf")
        self._junban_spin_job = None
        self._last_junban_auto_message = ""
        # The automatic Generate (Anki brought in known words) and the Generate button's state.
        self._last_auto_generate = float("-inf")
        # False, or the language Anki brought words in for ("ja"), which no Generate of it has run since.
        # True (from before it held the language) still means the language open now.
        self._auto_generate_pending = False
        self._auto_generate_job = None        # the alarm for when the 10-minute limit is up
        # The running Generate — None, "manual" (the button), "quiet" (順's "Generate & preview") or
        # "automatic" (Anki's words) — so there are never two at once. Set until its process ends,
        # however it ends (run_command_async's on_exit).
        self._generate_running = None
        self._open_report_when_generated = False   # Generate was pressed while a quiet one ran
        self._journey_state_job = None
        self._journey_gen = 0                 # generation counter: a late up-to-date answer is dropped
        self._journey_spin_job = None         # the automatic Generate's spinner in the check mark's spot
        self.var_auto_update = tk.BooleanVar(value=True) # One-click in-place updates
        self.var_source_display = tk.StringVar(value="off")  # per-sentence source badge in the report
        self.var_word_search = tk.BooleanVar(value=True)      # ⌕ lookup button on each report card
        self.var_word_search_category = tk.StringVar(value="all")
        self.var_sentence_dictionary_source = tk.BooleanVar(value=False)  # the export dialog's choice
        self._lock_ui_updates = False

        # Update state (populated by the background check; consumed by the footer indicator)
        self._update_info = None
        self._update_class = "NONE"
        self._update_job = None            # "Update now" until the hand-over (or a cancel): _start_update
        self.skipped_version = ""          # "Skip this version": never offered again
        self.failed_update_version = ""    # its in-app update failed: a manual download from then on
        self.btn_offer_skipped = None      # Settings' way back from a skip (`_sync_skipped_row`)
        self.update_label: Optional[ttk.Label] = None

        # Initialize status var early to satisfy linter
        self.status_var = tk.StringVar(value="Ready")
        self.terminal: Optional[tk.Text] = None
        self.spinner: Optional[ttk.Progressbar] = None
        self.settings_window: Optional[tk.Toplevel] = None
        self.btn_youtube: Optional[ttk.Button] = None
        self.btn_preview: Optional[ttk.Button] = None
        self.btn_reels: Optional[ttk.Button] = None
        self.btn_junban: Optional[ttk.Button] = None
        self.lang_frame: Optional[ttk.Frame] = None
        self.lang_options_frame: Optional[ttk.Frame] = None
        self.zh_script_frame: Optional[ttk.Frame] = None
        self.paren_readings_frame: Optional[ttk.Frame] = None
        self.names_frame: Optional[ttk.Frame] = None
        self.chk_phrases_and_titles: Optional[ttk.Checkbutton] = None
        self.chk_pronoun_bases: Optional[ttk.Checkbutton] = None
        self.chk_phrase_rows: Optional[ttk.Checkbutton] = None
        self.chk_ignore_names: Optional[ttk.Checkbutton] = None
        self.lbl_credits: Optional[ttk.Label] = None
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

        # Settings are written off this thread, under the `settings` lock (P0.3 04 §2): queued and retried, never
        # dropped. A child process, a journey check or closing the window flushes it first (`_flush_settings`).
        self._settings_writer = settings_manager.SettingsWriter(
            on_saved=lambda _s: self.gui_queue.put(self._on_settings_saved),
            on_error=lambda _e: self.gui_queue.put(lambda: self.status_var.set(self.SETTINGS_WAIT_LINE)))
        # Set when the window closes: a worker still waiting on a lock (a background Generate's) stops.
        self._closing_event = threading.Event()

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
        # Automatic rarity: saved, and the slider locked or unlocked, the moment it is switched.
        self.var_auto_band.trace_add("write", self._on_auto_band_toggled)
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
        self.var_enable_youtube.trace_add("write", self.save_settings)
        self.var_enable_youtube.trace_add("write", lambda n, i, m: self.update_youtube_visibility())
        self.var_enable_preview.trace_add("write", self.save_settings)
        self.var_enable_preview.trace_add("write", lambda n, i, m: self.update_preview_visibility())
        self.var_enable_koe.trace_add("write", self.save_settings)
        self.var_enable_koe.trace_add("write", lambda n, i, m: self.apply_koe_state())
        self.var_enable_reels.trace_add("write", self.save_settings)
        self.var_enable_reels.trace_add("write", lambda n, i, m: self.update_reels_visibility())
        self.var_enable_junban.trace_add("write", self.save_settings)
        self.var_enable_junban.trace_add("write", lambda n, i, m: self.update_junban_visibility())
        self.var_auto_update.trace_add("write", self.save_settings)
        self.var_anki_sync_auto.trace_add("write", self.save_settings)
        self.var_anki_backlog_on_generate.trace_add("write", self.save_settings)
        self.var_anki_auto_generate.trace_add("write", self.save_settings)
        # Selecting a theme both persists it AND toggles the Zen Limit slider's visibility. (A single
        # <<ComboboxSelected>> binding — a second bind() without add="+" would replace this one.)
        self.combo_theme.bind("<<ComboboxSelected>>",
                              lambda e: (self.save_settings(), self._update_zen_visibility()))

        # Always-fresh preview: when the window regains focus (e.g. after editing content in
        # Explorer or importing words), cheaply check for a delta and re-index in the background.
        self.root.bind("<FocusIn>", lambda e: (self._maybe_launch_indexer(), self._update_generate_state(),
                                               self._connect_session(), self._maybe_anki_sync(),
                                               self._maybe_junban_auto(),
                                               self._maybe_auto_generate(), self._schedule_journey_state(),
                                               self._schedule_maintain(), self._update_library_notice(),
                                               self._replan_focus(), self._maybe_replan_generate()))
        # Deferred startup timers are skipped under test — a test destroys the window long before
        # they fire, and a pending `after` whose Tcl command died with the interpreter keeps firing
        # into nothing (see the _no_ui_timers fixture in tests/conftest.py). Guarding the callback
        # body is not enough; it is never invoked.
        # A command-line call that fails while the window is open shows in the bottom bar (P0.3 02 §4, ✅ G0.3-1).
        self._cli_events = None
        self._cli_events_reading = False
        try:
            from app.cli import events as cli_events
            self._cli_events = cli_events.Reader()
        except Exception as e:
            print(f"Command-line events not watched: {e}")
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self.root.after(self.CLI_EVENTS_EVERY, self._watch_cli_events)
            # And once shortly after startup, so the preview appears without a manual Generate.
            self.root.after(1500, lambda: self._maybe_launch_indexer(force=True))

            # Reconcile the result of any update applied since we last ran (toast / manual-retry).
            self.root.after(800, self.reconcile_update_result)

            # Connect's preview on: a session starts — Anki seen open gets the session's sync, or with Open Anki for me
            # on, Anki closed is opened for you (P2.3). Before the known-words sync below.
            self.root.after(1800, lambda: self._connect_session(opening=True))

            # Pick up words studied in Anki since last time (only if the user turned it on).
            self.root.after(2000, lambda: self._maybe_anki_sync(force=True))

            # The fast re-plan's preview, when 順's switch is on: a re-order left owed, cards no re-order placed.
            self.root.after(2500, self._replan_start)

            # Whether the journey is up to date — the Generate button's border / check mark.
            self.root.after(1200, self._schedule_journey_state)

            # The library store's helper, when it has something to do (Library_Store_Spec §6.7: at open), and its
            # notice once that has had a moment to build the store.
            self.root.after(1500, self._maybe_maintain)
            self.root.after(1600, self._update_library_notice)

            # Connect's preview on: name what another program (hato) added while Surasura was closed (P2.1 row 2.1.7)
            self.root.after(2500, self._arrivals_notice)

        # Start update check in background. Skipped under test (the _no_gui_update_check fixture in
        # tests/conftest.py): it calls the real GitHub API, and every test that builds this window
        # would otherwise go online.
        if not os.environ.get("SURASURA_NO_UPDATE_CHECK"):
            threading.Thread(target=self.check_updates_thread, daemon=True).start()

        # The note naming this install's data folder, for 3.0's first start (K100). Frozen builds only; off the
        # window's thread, and a failure is only logged (write_install_note never raises).
        threading.Thread(target=self._write_install_note, daemon=True).start()

        # Initial UI update for language
        self.update_ui_for_language()
        
        # Trace language changes
        self.var_language.trace_add("write", lambda *args: self.update_ui_for_language())
        # Known words are per language, and so are the chosen decks.
        self.var_language.trace_add("write", lambda *args: self._maybe_anki_sync(force=True))
        self.var_language.trace_add("write", lambda *args: self._replan_start())
        # And so is the band preview: its numbers, and the band Automatic rarity locks the slider on,
        # come from that language's store. The indexer refreshes it only when the store has work to do,
        # so a switch to an up-to-date Chinese store kept the Japanese numbers — and the Japanese
        # automatic band, which turning Automatic rarity off then saved as yours. The preview's
        # signature holds the language, so this recomputes on a real switch only.
        self.var_language.trace_add("write", lambda *args: self._refresh_band_preview())

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
        # Cleared when it fires, so it means "a save is pending": a click on the locked slider (automatic
        # rarity) then flushes nothing — the locked slider never writes settings.json (I2).
        self._band_save_after = self.root.after(
            250, lambda: (setattr(self, "_band_save_after", None), self.save_settings(skip_ui=True)))

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
        preview lines. Pure arithmetic over cached counts — instant, no tokenization.

        Does nothing while automatic rarity is on: the slider is locked, and Tk calls this for a
        programmatic set() too — placing it on the automatic band must never write var_band (I2)."""
        if self.var_auto_band.get():
            return
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
        identically.

        With automatic rarity on, the slider is locked on the band it picks ("Auto" until a preview
        exists). Display only: var_band is never written then — settings.json is in the run
        signature, so saving the automatic band after every Generate would turn the button blue (I2)."""
        if not hasattr(self, "band_slider"):
            self._update_band_preview_labels(self.var_band.get())
            return
        bands = self._effective_bands or list(word_selection.BANDS_ORDER)
        self.band_slider.config(to=max(0, len(bands) - 1))
        auto = self.var_auto_band.get()
        band = self._auto_band_choice() if auto else self.var_band.get()
        if band is not None and band not in bands:
            band = bands[-1]              # hidden band -> its identical, still-visible neighbour
            if not auto:
                self.var_band.set(band)   # trace -> save; harmless (same selection)
        if band is not None:
            self.band_slider.config(state=tk.NORMAL)   # Tk ignores set() on a disabled Scale
            self.band_slider.set(bands.index(band))
        self._show_band_lock(auto)
        self.var_band_name.set(word_selection.band_label(band) if band else "Auto")
        self._update_band_preview_labels(band)

    def _auto_max_words(self):
        """Automatic rarity's line: logic.selection.auto_max_words (edited in settings.json only)."""
        try:
            return self._current_settings["logic"]["selection"]["auto_max_words"]
        except Exception:
            return word_selection.DEFAULT_AUTO_MAX_WORDS

    def _auto_max_words_text(self):
        """The line as the tooltips say it: 850 with its thousands separator, or as written when a hand
        edit made it something else ("850" in quotes) — `:,` raises on a string, and the tooltip then
        never showed."""
        n = self._auto_max_words()
        return f"{n:,}" if isinstance(n, (int, float)) else str(n)

    def _auto_step_back_text(self):
        """Q4-3's second line as the tooltips say it: 1,100, or the first line when a hand edit put it higher."""
        try:
            return f"{max(word_selection.DEFAULT_AUTO_STEP_BACK_WORDS, int(self._auto_max_words())):,}"
        except (TypeError, ValueError):
            return f"{word_selection.DEFAULT_AUTO_STEP_BACK_WORDS:,}"

    def _auto_band_choice(self):
        """The band automatic rarity picks from the current preview — word_selection.auto_band over the
        numbers the slider shows, the rule the analyzer applies on the same ones (I3) — or None before
        any preview exists. A line the rule can't compare with ("850" in quotes, hand-edited into
        settings.json) makes the analyzer keep your own band; so that is the band shown, locked."""
        if not self._band_previews:
            return None
        try:
            return word_selection.auto_band(self._band_previews, self._auto_max_words(),
                                            remembered=getattr(self, "_auto_remembered", None))
        except Exception:
            return self.var_band.get()

    def _show_band_lock(self, locked):
        """Automatic rarity's look (D2): the slider locked and greyed — flat, in muted colours, still
        showing where the band sits between Core and Native — and "Rarity (auto):" beside it."""
        self._band_locked = locked
        if locked:
            self.band_slider.config(state=tk.DISABLED, sliderrelief=tk.FLAT,
                                    bg=SURFACE_COLOR, troughcolor=BG_COLOR)
        else:
            self.band_slider.config(state=tk.NORMAL, sliderrelief=tk.RAISED,
                                    bg=BG_COLOR, troughcolor=SURFACE_COLOR)
        self.lbl_rarity.config(text="Rarity (auto):" if locked else "Rarity:")

    def _on_auto_band_toggled(self, *args):
        """Automatic rarity switched on or off (Settings → Sentences & Logic): saved at once, and the
        slider locked on the band it picks — or, switched off, unlocked on that same band, which then
        becomes yours (D3): the list doesn't change the moment you switch it off."""
        auto = self.var_auto_band.get()
        if auto == self._band_locked:
            return    # a reload that changes nothing (Tk traces every write, the same value too)
        if not auto:
            band = self._auto_band_choice()
            if band and band != self.var_band.get():
                self.var_band.set(band)   # its trace arms the band save, flushed just below
        if getattr(self, "_band_save_after", None):
            self._flush_band_save()       # one save, with the switch in it
        else:
            self.save_settings(skip_ui=True)
        self._apply_effective_bands()

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
        current = getattr(self, "_current_settings", {}) or {}
        sel = current.get("logic", {}).get("selection", {})
        script = self._effective_zh_script(lang)     # read here: the worker must not touch Tk vars
        # Which of the library's name tables the counts take: the store reads the three switches from
        # analyzer.LOGIC (token_index._library_switches), which this process loaded once, at its first
        # import — so a switch flipped in Settings kept counting the old way until a restart. Set them
        # from the settings now, as a run reads its own (the YouTube preview updates LOGIC the same way).
        try:
            from app import analyzer
            for key in ("names_recurring", "names_kanji", "names_work_terms"):
                analyzer.LOGIC[key] = bool((current.get("logic") or {}).get(key, True))
        except Exception:
            pass

        # Cache hit: same inputs as the last good compute -> reuse the cached previews, no worker.
        sig = self._preview_signature(lang, sel, script)
        if (not force and sig is not None and sig == getattr(self, "_preview_sig", None)
                and getattr(self, "_band_previews", None) is not None):
            self._update_band_preview_labels(
                self._auto_band_choice() if self.var_auto_band.get() else self.var_band.get())
            return

        self._preview_gen = getattr(self, "_preview_gen", 0) + 1
        gen = self._preview_gen
        self.var_band_coverage.set("Calculating…")

        def _work():
            prepared = getattr(self, "_preview_prepared", None)
            if prepared is not None:
                prepared.join()             # the tables the window's opening decodes (never on the window's thread)
            if gen != self._preview_gen:
                return                      # a newer refresh started meanwhile: only its numbers are ever shown
            previews = self._compute_band_previews(lang, sel, script)
            self.gui_queue.put(lambda: self._apply_preview_result(gen, previews, sig))

        threading.Thread(target=_work, daemon=True).start()

    def _prepare_preview(self):
        """(On a background thread, as the window opens — never touches Tk.) Decode what the Rarity slider's first
        refresh reads besides the store, for the language the settings open in (token_index.prepare_preview)."""
        try:
            from app.path_utils import get_user_files_path
            lang = settings_manager.load_settings().get("target_language", "ja")
            token_index.prepare_preview(lang, get_user_files_path(lang))
        except Exception:
            pass

    def _preview_signature(self, lang, sel, script="asis"):
        """Cheap stat-only fingerprint of everything the band preview depends on: the token store
        (its mtime moves whenever a run/indexer rewrites it), the known-words file, the ignore
        lists and Ignore names (the library's names become ignored words), the set phrases switch (their rows
        count), which one-character words count (exclude_single), which of the library's name tables apply (they
        join words, so they change the counts), the selection settings, and the Chinese script they're all read in.
        Returns None if it can't be computed (forces a refresh)."""
        try:
            from app.path_utils import get_user_files_path
            uf = get_user_files_path(lang)
            db = token_index.store_path_for(lang)
            db_mtime = os.path.getmtime(db) if os.path.exists(db) else 0
            known_path = os.path.join(uf, "KnownWord.json")
            ksig = token_index.known_signature(known_path, script)
            # mtime and size, as known_signature: two writes within one clock tick share an mtime.
            lists = tuple(
                (os.path.getmtime(p), os.path.getsize(p)) if os.path.exists(p) else 0
                for p in (os.path.join(uf, n) for n in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"))
            )
            current = getattr(self, "_current_settings", {}) or {}
            logic = current.get("logic") or {}
            names = bool(logic.get("ignore_names"))
            phrases = bool(logic.get("phrase_rows", True))
            singles = bool(current.get("exclude_single", True))     # which one-character words count
            tables = tuple(bool(logic.get(key, True)) for key in ("names_recurring", "names_kanji", "names_work_terms"))
            return (lang, db_mtime, ksig, lists, names, phrases, singles, tables, json.dumps(sel, sort_keys=True),
                    script)
        except Exception:
            return None

    def _compute_band_previews(self, lang, sel, script="asis"):
        """The heavy read (token store + known-words file). Runs on a WORKER thread — it must NOT
        touch any tk widget; it only returns the {band: preview} dict (or None). The distribution is
        token_index.preview_frequencies: the analyzer's automatic rarity decides from the same one."""
        try:
            try:                       # Q4-3: the band Automatic last chose, read here, never on the window's thread
                from app import library_store
                from app.path_utils import get_data_path
                self._auto_remembered = library_store.read_auto_band(lang, get_data_path(lang))
            except Exception:
                self._auto_remembered = None
            store = token_index.open_store(lang)
            try:
                from app.path_utils import get_user_files_path
                freqs = token_index.preview_frequencies(store, lang, get_user_files_path(lang), script)
                if freqs is None:
                    return None
                avg_file = freqs["total_tokens"] / (store.file_count() or 1)
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

    def _load_ignore_for_preview(self, lang, script="asis"):
        """The ignore/blacklist/graduated words as the preview reads them (token_index.preview_ignore_set)."""
        from app.path_utils import get_user_files_path
        return token_index.preview_ignore_set(get_user_files_path(lang), lang, script)

    def _load_known_approx(self, lang, script="asis"):
        """Known lemmas without the tokenizer, for a stale known cache (token_index.preview_known_approx)."""
        from app.path_utils import get_user_files_path
        return token_index.preview_known_approx(get_user_files_path(lang), lang, script)

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
        lang = self.var_language.get() or "ja"
        script = self._effective_zh_script(lang)
        # The whole check runs on a worker (Library_Store_Spec §7, A12): the list and needs_reconcile's stat of
        # every file. The list is the indexer's own (`indexer._content_files`: the store's in store and read-only
        # modes, K2, else the folders), so a file Graduate left in its folder never reads as "to index" forever.
        self._indexer_busy = True
        self._run_on_worker(lambda: self._index_needed(lang, script), lambda need: self._index_checked(need, lang))

    @staticmethod
    def _index_needed(lang, script):
        """Would the indexer have anything to do for `lang`? Stat-only (no tokenizer); False when it can't tell."""
        try:
            from app.path_utils import get_data_path, get_user_files_path
            from app.indexer import _content_files
            files = _content_files(get_data_path(lang), lang)
            store = token_index.open_store(lang)
            try:
                known_file = os.path.join(get_user_files_path(lang), "KnownWord.json")
                # needs_reconcile is stat-only, so a tokenizer change (the Chinese script)
                # alone would never re-index: compare the identity the store was built with too.
                return bool(store.needs_reconcile(files)
                            or store.get_meta("build_sig") != token_index.build_signature(lang, script=script)
                            or store.get_cached_known(token_index.known_signature(known_file, script)) is None)
            finally:
                store.close()
        except Exception:
            return False

    def _index_checked(self, need, lang=None):
        """The indexer check's answer, on this thread: launch the indexer for the language checked, or stand down."""
        if not need:
            self._indexer_busy = False
            return

        def _done():
            self._indexer_busy = False
            self._refresh_band_preview(force=True)   # store just changed -> recompute, don't trust cache
            self._maybe_auto_generate()              # one waiting for the indexer can go now

        self.run_command_async(['indexer.py', '--language', lang or self.var_language.get()],
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

            # Reels serves only some languages, so switching library changes whether it can appear.
            self.update_reels_visibility()

            # 3. Update Settings Toggles (if window created)
            if self.settings_window and self.settings_window.winfo_exists():
                if self.zh_script_frame:
                    self.zh_script_frame.pack_forget()
                if self.paren_readings_frame:
                    self.paren_readings_frame.pack_forget()
                if self.names_frame:
                    self.names_frame.pack_forget()
                if self.chk_phrases_and_titles:
                    self.chk_phrases_and_titles.pack_forget()
                if self.chk_pronoun_bases:
                    self.chk_pronoun_bases.pack_forget()
                if self.chk_phrase_rows:
                    self.chk_phrase_rows.pack_forget()
                if self.chk_ignore_names:
                    self.chk_ignore_names.pack_forget()

                if lang == 'zh':
                    if self.zh_script_frame:
                        self.zh_script_frame.pack(anchor=tk.W, pady=(2, 0))
                else:
                    # zh_script is deliberately NOT reset: it belongs to the Chinese library, and
                    # a trip to Japanese and back must not silently change how Chinese is read.
                    # (Nor is paren_readings on the way to Chinese: it belongs to the Japanese one.)
                    if self.paren_readings_frame:
                        self.paren_readings_frame.pack(anchor=tk.W, pady=(2, 0))
                    if self.names_frame:
                        self.names_frame.pack(anchor=tk.W, pady=(2, 0))
                    if self.chk_phrases_and_titles:
                        self.chk_phrases_and_titles.pack(anchor=tk.W)
                    if self.chk_pronoun_bases:
                        self.chk_pronoun_bases.pack(anchor=tk.W)
                    if self.chk_phrase_rows:
                        self.chk_phrase_rows.pack(anchor=tk.W)
                    if self.chk_ignore_names:
                        self.chk_ignore_names.pack(anchor=tk.W)

            self.save_settings()
        finally:
            self._lock_ui_updates = False

        # A language switch points at a different store — re-index that language in the background.
        self._maybe_launch_indexer(force=True)
        self._schedule_maintain()
        self._update_library_notice()
        self._update_generate_state()   # different language -> different library -> re-check emptiness

    def _library_has_content(self):
        """True if the current language's library has at least one analyzable content file. With a library
        store: an available file in an analysed tier, read from this thread's long-lived handle (a Graduate
        leaves its file in the tier folder, so the folders no longer answer). Without one, the folders: the
        extensions MUST match what the analyzer actually reads (analyzer.get_files_recursive:
        path_utils.is_content_file) — otherwise Generate could enable on files the analysis then
        ignores (e.g. a tier of only .vtt), yielding an empty journey."""
        lang = self.var_language.get() or "ja"
        store = self._library_handle(lang)
        if store is not None:
            try:
                return store.has_content()
            except Exception:
                pass
        # The folders are walked on a worker (Library_Store_Spec §7, A12); this thread reads the last answer
        # (Generate stays on until the first one), and the button follows when the answer changes.
        answers = self.__dict__.setdefault("_folder_content", {})
        walking = self.__dict__.setdefault("_folder_content_walks", set())
        if lang not in walking:
            walking.add(lang)

            def landed(has):
                walking.discard(lang)
                changed = answers.get(lang) != has
                answers[lang] = has
                if changed and (self.var_language.get() or "ja") == lang:
                    self._update_generate_state()
            self._run_on_worker(lambda: self._folders_have_content(lang), landed)
        return answers.get(lang, True)

    @staticmethod
    def _folders_have_content(lang):
        from app.path_utils import get_data_path, is_content_file
        base = get_data_path(lang)
        for tier in ("HighPriority", "LowPriority", "GoalContent"):
            d = os.path.join(base, tier)
            if os.path.isdir(d):
                for _r, _dirs, files in os.walk(d):
                    if any(is_content_file(f) for f in files):
                        return True
        return False

    @staticmethod
    def _library_state(lang):
        """(mode, reason, waiting) for `lang`'s library store, read on a worker: `waiting` is an outside edit of
        the copy that waits for the user's answer (the size guard, Q4-8)."""
        try:
            from app import library_store
            from app.path_utils import get_data_path, get_user_files_path
            data_dir = get_data_path(lang)
            mode, reason = library_store.check_mode(lang, data_dir, busy_wait=0.0)
            waiting, note = False, None
            if mode == "store":
                store = library_store.open_store(lang, data_dir, get_user_files_path(lang), role="window",
                                                 busy_wait=0.0)
                if store is not None:
                    with store:
                        meta = store.meta()
                        waiting = bool(meta.get("reimport_pending"))
                        if meta.get("reimport_note"):
                            note = json.loads(meta["reimport_note"])
                            store.bookkeeping({"reimport_note": ""})      # told once (D27: "tells you quietly")
            return mode, reason, waiting, note
        except Exception:
            return None, None, False, None

    def _update_library_notice(self):
        """Re-check the library's mode (on focus, at open, on a language switch, after Repair or Try again) on a
        worker, and show what the user needs to know — never a modal (§6.9: the mode is checked, not fixed)."""
        if not hasattr(self, "library_notice") or self.__dict__.get("_library_notice_busy"):
            return
        lang = self.var_language.get() or "ja"
        self._run_on_worker(lambda: self._library_state(lang), lambda state: self._show_library_notice(lang, state))

    def _show_library_notice(self, lang, state):
        mode, reason, waiting, note = state
        if mode is None or (self.var_language.get() or "ja") != lang:
            return
        if note:
            count = note.get("count")
            self.status_var.set("Your library's order file was changed outside Surasura: the change was taken in"
                                + (f" ({count} item{'s' if count != 1 else ''} moved)." if count else "."))
        before = self._library_mode_seen.get(lang)
        self._library_mode_seen[lang] = mode
        if before == "json" and mode == "store":
            self.status_var.set("Library moved to the new store.")
        kind, text = None, ""
        if mode == "read-only" and reason == "damaged":
            kind = "damaged"
            text = ("Your library needs repair. Until then its order can't be changed, and new files are read "
                    "but can't be added to it. Generate still works.")
        elif mode == "read-only" and "newer" in (reason or ""):
            text = "This library was saved by a newer Surasura: its order can't be changed here."
        elif mode == "read-only" and reason != "busy":
            text = "Your library can't be changed right now. Generate still works."
        elif mode == "json" and reason == "migration failed":
            kind = "failed"
            text = ("Your library couldn't be moved to the new store, so its order stays in its file for now "
                    "(details: library_maintain.log in Surasura's local data folder).")
        elif waiting:
            text = "Your library's order file was changed outside Surasura. Open Import Content to choose an order."
        self._library_notice_kind = kind
        self.library_notice_var.set(text)
        if kind:
            self.btn_library_notice.config(text="Repair" if kind == "damaged" else "Try again", state=tk.NORMAL)
            self.btn_library_notice.pack(side=tk.RIGHT, padx=(5, 0), pady=(6, 0))
        else:
            self.btn_library_notice.pack_forget()
        if text:
            self.library_notice.pack(fill=tk.X, side=tk.BOTTOM, before=self.btn_open_data)
        else:
            self.library_notice.pack_forget()

    def _close_library_handles(self):
        """This process's own store handles (the dashboard's long-lived ones): Repair renames the files, which
        Windows refuses while any is open (§6.9). They reopen on the next use."""
        for opener in self.__dict__.get("_library_openers", {}).values():
            try:
                opener.close()
            except Exception:
                pass

    def _library_notice_action(self):
        """Repair (a damaged store) or Try again (a failed move), run as the helper. Repair first closes the
        Content Manager windows and this window's own handles, and waits for no Generate (§6.9)."""
        kind, lang = self._library_notice_kind, self.var_language.get() or "ja"
        if kind not in ("damaged", "failed"):
            return
        if kind == "damaged":
            if self._generate_running is not None:
                self.status_var.set("Repair waits for Generate to finish — try again in a moment.")
                return
            for proc in list(self.active_processes):
                if getattr(proc, "surasura_desc", "") == "Content Importer":
                    try:
                        if proc.poll() is None:
                            proc.terminate()
                            proc.wait(5)
                    except Exception:
                        pass
            self._close_library_handles()
        try:
            from app import library_store
            proc = library_store.spawn_maintain(lang, "--repair" if kind == "damaged" else "--retry")
        except Exception:
            proc = None
        if proc is None:
            self.status_var.set("Couldn't start that just now (an update may be waiting) — try again shortly.")
            return
        self._library_notice_busy = True
        self.btn_library_notice.config(state=tk.DISABLED)
        self.status_var.set("Repairing your library…" if kind == "damaged" else "Moving your library to the store…")

        def wait_for_it():
            code = proc.poll()
            if code is None:
                self.root.after(300, wait_for_it)
                return
            self._library_notice_busy = False
            if code in (0, 3):
                self.status_var.set("Library repaired." if kind == "damaged" else "Library moved to the new store.")
            elif kind == "damaged":
                self.status_var.set("Repair couldn't finish: close any other Surasura windows, then press Repair "
                                    "again.")
            else:
                self.status_var.set("Your library still couldn't be moved — it keeps working from its file.")
            self._update_library_notice()
            self._update_generate_state()
            self._schedule_journey_state()
        self.root.after(300, wait_for_it)

    def _schedule_maintain(self):
        """The library store's helper, 2 s after the last trigger (focus, a language switch): one check for a burst
        of them (Library_Store_Spec §6.7: idle 2 s, and a copy that may have changed)."""
        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        job = self.__dict__.get("_maintain_job")
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._maintain_job = self.root.after(2000, self._maybe_maintain)

    def _maybe_maintain(self):
        """On a worker: spawn the helper (detached) when it has something to do — no store yet but a manifest to
        build from, a change since the last export, or a copy someone else rewrote (once per new stat)."""
        self._maintain_job = None
        lang = self.var_language.get() or "ja"
        handed = self.__dict__.setdefault("_maintain_handed", {})

        def work():
            try:
                from app import library_store
                from app.path_utils import get_data_path, get_user_files_path
                data_dir, user_files_dir = get_data_path(lang), get_user_files_path(lang)
                mode, _reason = library_store.check_mode(lang, data_dir, busy_wait=0.0)
                if mode == "json":
                    library_store.spawn_build_if_waiting(lang, data_dir, user_files_dir)
                    return
                if mode != "store":
                    return
                store = library_store.open_store(lang, data_dir, user_files_dir, role="window", busy_wait=0.0)
                if store is None:
                    return
                with store:
                    due, seen = library_store.maintain_due(store, handed.get(lang, ""))
                if due:
                    handed[lang] = seen
                    library_store.spawn_maintain(lang)
            except Exception as e:
                print(f"Library store helper check: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _arrivals_notice(self):
        """With Connect's preview on: on a worker, the items another program registered while Surasura was closed,
        named once in the bottom bar (`app/connect/notice.py`). With it off nothing of Connect's is imported."""
        if not (getattr(self, "_current_settings", None) or {}).get("connect_enabled"):
            return
        lang = self.var_language.get() or "ja"

        def work():
            try:
                from app.connect import notice
                line = notice.at_open(lang)
            except Exception as e:
                print(f"Arrivals notice: {e}")
                return
            if line:
                self.gui_queue.put(lambda: self.status_var.set(line))
        threading.Thread(target=work, daemon=True).start()

    CONNECT_LOOK_EVERY = 60     # seconds between two of Connect's looks at Anki on focus (FocusIn fires per widget)

    def _connect_session(self, opening=False):
        """Connect's preview on (P2.3; ✅ Q4-4, Q4-16): a session's start, looked at on a worker — at the window's start
        (`opening`) and when it comes back into focus, at most once a minute (`anki_session.at_window`, which 3.0's
        window calls too). Anki seen closed is recorded, so the next look starts a session with a sync; at the window's
        start, with *Open Anki for me* on, a closed Anki is opened for you — never at any other moment, never after
        mining; Anki open and a session starting: its one sync, so your phone's reviews are in before anything reads
        or writes Anki, then the known-words sync (when it's on) and a Connect kick. Off: nothing, and nothing of
        Connect's is imported."""
        if os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return
        s = getattr(self, "_current_settings", None) or {}
        if not s.get("connect_enabled"):
            self._connect_opened = self._connect_opened or opening     # switched on later: a focus may look
            return
        import time
        now = time.monotonic()
        if not opening and (not self._connect_opened or now - self._connect_looked < self.CONNECT_LOOK_EVERY):
            return                      # a focus before the window's first look never takes its place
        if self._connect_looking:
            return
        self._connect_looked, self._connect_looking, self._connect_opened = now, True, True
        try:
            s = settings_manager.load_settings() or s
        except Exception:
            pass

        def say(line):
            self.gui_queue.put(lambda: self.status_var.set(line))

        def work():
            done = None
            try:
                from app.connect import anki_session
                done = anki_session.at_window(dict(s), opening=opening, say=say)
            except Exception as e:
                print(f"Connect's session: {e}")
            finally:
                self._connect_looking = False
            sync = (done or {}).get("sync")
            if sync == "synced" and done.get("opened"):
                say("Anki is open and synced: your phone's reviews are in.")
            if (done or {}).get("anki") == "open":
                # The session's sync has answered — the known-words sync waited for this look (Q4-1): right away once
                # your phone's reviews are in, else at its own five-minute pace
                fresh = sync == "synced"
                self.gui_queue.put(lambda: self._maybe_anki_sync(force=fresh))
            if sync == "synced":
                # … and let Connect see what's waiting
                try:
                    from app.connect import kick
                    kick.kick(s)
                except Exception as e:
                    print(f"Connect wasn't started: {e}")
            elif sync == "not-signed-in":
                say("Anki isn't signed in to AnkiWeb, so your phone won't get Surasura's cards and order until it is.")
            elif sync == "full-sync":
                say("AnkiWeb wants a full sync, which only you can choose: open Anki and click Sync.")
            elif sync and sync.startswith("failed"):
                say("Anki couldn't sync with AnkiWeb just now. Surasura asks again later.")
            elif done and done.get("opened") and done.get("anki") != "open":
                say("Anki didn't open within two minutes. Open it yourself when you're ready.")
        threading.Thread(target=work, daemon=True).start()

    def _library_handle(self, lang):
        """This thread's long-lived library store handle for `lang` (Library_Store_Spec §6.2), or None
        outside store mode. The mode is re-checked on every call (cheap: no scans, never waits here)."""
        try:
            from app import library_store
            from app.path_utils import get_data_path, get_user_files_path
            openers = self.__dict__.setdefault("_library_openers", {})
            opener = openers.get(lang)
            if opener is None:
                opener = openers[lang] = library_store.StoreOpener(lang, get_data_path(lang),
                                                                    get_user_files_path(lang))
            if opener.check() != "store":
                return None
            return opener.handle()
        except Exception:
            return None

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
                   command=self.open_anki_sync)
        self.btn_anki.pack(side=tk.LEFT, padx=(0, 10))
        ToolTip(self.btn_anki, "Add known words from the cards you've studied in Anki (Anki must be "
                               "running), or import an .apkg file.")
        
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
        self.btn_open_data = btn_open_data
        ToolTip(btn_open_data, "Add and manage your immersion content — files, EPUB / Anki, and YouTube.")
        # The library store's notice (Library_Store_Spec §6.8, §6.9): a damaged store (Repair), a move to the store
        # that failed (Try again), a library from a newer Surasura, an outside edit waiting for an answer.
        # Packed below the button row only while there is something to say (_update_library_notice).
        self.library_notice = ttk.Frame(lib_frame)
        self.library_notice_var = tk.StringVar(value="")
        ttk.Label(self.library_notice, textvariable=self.library_notice_var, foreground=ERROR_COLOR,
                  wraplength=330, justify=tk.LEFT).pack(side=tk.LEFT, fill=tk.X, expand=True, pady=(6, 0))
        self.btn_library_notice = ttk.Button(self.library_notice, text="Repair", width=10,
                                             command=self._library_notice_action)
        ToolTip(self.btn_library_notice, lambda: (
            "Rebuild your library's store from what can still be read and its saved copy. Content Manager windows "
            "close first; the damaged files are kept aside, never deleted."
            if self._library_notice_kind == "damaged" else
            "Try moving your library order into the new store again."))
        self._library_notice_kind = None
        self._library_mode_seen = {}
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
        self.lbl_rarity = ttk.Label(band_row, text="Rarity:")   # "Rarity (auto):" under automatic rarity
        self.lbl_rarity.pack(side=tk.LEFT, padx=(0, 8))
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
        # Shown ABOVE so it doesn't cover the coverage line below. Locked by automatic rarity, it says
        # why and where to turn that off.
        ToolTip(self.band_slider, lambda: (
                f"Chosen for you by Automatic rarity: the rarest band with {self._auto_max_words_text()} "
                f"words or fewer, kept until its list passes {self._auto_step_back_text()}. "
                "To choose it yourself, turn off Automatic rarity in "
                "Settings → Sentences & Logic."
                if self.var_auto_band.get() else
                "Which words to include, by how common they are in your library:\n\n"
                "• Core: only the most common words (~50% coverage)\n"
                "• Native: everything except one-off words (~99% coverage)\n\n"
                "Slide right to learn rarer, less frequent words."),
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
        # A thin Surasura-blue border while Generate has something new to compute (the library, known
        # words or an analysis setting changed since the last run), and a quiet check mark beside it
        # once the journey is up to date. Invisible until the first check answers — see
        # _refresh_journey_state.
        self._journey_state = None
        self.journey_border = tk.Frame(self.journey_row, bg=BG_COLOR, highlightthickness=2,
                                       highlightbackground=BG_COLOR, highlightcolor=BG_COLOR)
        self.journey_border.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn_journey = ttk.Button(self.journey_border, text="Generate Journey", style="Action.TButton",
                                 command=self.run_analyzer)
        self.btn_journey.pack(fill=tk.X, expand=True)
        ToolTip(self.btn_journey, lambda: (
            "Generate your learning path and open it in the browser. Reuses the last analysis if "
            "nothing changed, so theme / Zen limit apply instantly."
            + (" Your library, known words or settings changed since the last Generate."
               if self._journey_state is False else "")))
        # The check sits ON the button, at its right edge, so the button never changes length (the
        # user, 2026-09-23). It wears the button's own colours — dark, and purple under the pointer
        # like the button — and a click on it is a click on the button.
        self.lbl_journey_state = tk.Label(self.journey_border, text="✓", bg=SURFACE_COLOR, fg=CHECK_GRAY,
                                          font=("Segoe UI", 10, "bold"), bd=0, padx=0, pady=0)
        ToolTip(self.lbl_journey_state, self._journey_check_tip)
        self.lbl_journey_state.bind("<Button-1>", lambda e: self.btn_journey.invoke(), add="+")
        self.btn_journey.bind("<Enter>", lambda e: self._light_journey_check(True), add="+")
        self.btn_journey.bind("<Leave>", lambda e: self._light_journey_check(False), add="+")
        self.lbl_journey_state.bind("<Enter>", lambda e: self._light_journey_check(True, on_check=True),
                                    add="+")
        self.lbl_journey_state.bind("<Leave>", lambda e: self._light_journey_check(False, on_check=True),
                                    add="+")

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
        self.lbl_flag.pack(side=tk.LEFT, padx=(10, 5))

        # Settings Button (Icon only). ALWAYS the right-most button: the optional module buttons are
        # packed before it (see _module_slot), so the footer reads [flag] 🎬 順 ⚙ however many
        # modules are on and in whatever order they were switched on.
        self.btn_settings = ttk.Button(credit_box, text="⚙", command=self.toggle_settings_window, width=3)
        self.btn_settings.pack(side=tk.LEFT, padx=(5, 0))
        ToolTip(self.btn_settings, "Open Settings & Logs")

        # Reels Button (optional module). Created unpacked; load_settings decides whether it shows.
        self.btn_reels = ttk.Button(credit_box, text="🎬", command=self.open_reels, width=3)
        ToolTip(self.btn_reels, "Reels: turn a series you own into one video containing every word "
                                "you need, to mine in bulk after you watch.")

        # Junban Button (optional module). Created unpacked; load_settings decides whether it shows.
        self.btn_junban = ttk.Button(credit_box, text="順", command=self.open_junban, width=3)
        ToolTip(self.btn_junban, "順番 (Junban): reorder the new cards already waiting in your "
                                 "Anki backlog so they come up in this learn order. It only moves "
                                 "cards — it never adds, edits or deletes any.")

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
        grid_frame.pack(fill=tk.BOTH, expand=True)
        grid_frame.columnconfigure(0, weight=2, uniform="settings_col") # Strictly 2:1
        grid_frame.columnconfigure(1, weight=1, uniform="settings_col")
        grid_frame.rowconfigure(0, weight=1)

        # Two INDEPENDENT columns, each a simple stack. With shared grid rows, the tallest group in
        # a row set that row's height for both sides (Data & System stretched Language & Parsing to
        # match), and with the optional-module toggles present the third row fell off the bottom of
        # a 720px screen. Stacked, each column is only as tall as its own groups; the log takes
        # whatever is left.
        left_col = ttk.Frame(grid_frame)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        right_col = ttk.Frame(grid_frame)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        # --- LEFT COLUMN (Col 0) ---
        
        # 1. 🌐 Language & Parsing
        group_lang = ttk.LabelFrame(left_col, text=" 🌐 Language & Parsing", padding="10")
        group_lang.pack(fill=tk.X, pady=5)

        # Language Selection
        self.lang_frame = ttk.Frame(group_lang)
        self.lang_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(self.lang_frame, text="Target Language:").pack(side=tk.LEFT)
        ttk.Radiobutton(self.lang_frame, text="Japanese (日本語)", variable=self.var_language, value="ja", command=self.save_settings).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(self.lang_frame, text="Chinese (中文)", variable=self.var_language, value="zh", command=self.save_settings).pack(side=tk.LEFT)

        # Language Specific Options Container (Indented)
        self.lang_options_frame = ttk.Frame(group_lang)
        self.lang_options_frame.pack(fill=tk.X, padx=(10, 0), pady=(0, 5))

        # Script (Chinese): read the whole library in one script. Packed by update_ui_for_language.
        # Changing it re-indexes the library in the background.
        self.zh_script_frame = ttk.Frame(self.lang_options_frame)
        ttk.Label(self.zh_script_frame, text="Script:").pack(side=tk.LEFT)
        combo_script = ttk.Combobox(self.zh_script_frame, values=list(self.ZH_SCRIPT_LABELS.values()),
                                    state="readonly", width=16)
        combo_script.set(self.ZH_SCRIPT_LABELS.get(self.var_zh_script.get(), "As-is"))
        combo_script.pack(side=tk.LEFT, padx=(5, 0))
        combo_script.bind("<<ComboboxSelected>>",
                          lambda e: (self.var_zh_script.set(self._zh_script_key(combo_script.get())),
                                     self.save_settings()))
        ToolTip(combo_script, "Read all Chinese content and known words in one script, so 学习 and "
                              "學習 count as one word. Your files are not changed. Traditional is "
                              "written in Taiwan's standard characters (為, 裡); Simplified→"
                              "Traditional can occasionally pick the wrong character.")

        # Readings in parentheses (Japanese): kana right after kanji in a book is that kanji's reading,
        # a stand-in for ruby, not more words. Packed by update_ui_for_language for Japanese only;
        # changing it re-indexes the library in the background, like Script above.
        self.paren_readings_frame = ttk.Frame(self.lang_options_frame)
        ttk.Label(self.paren_readings_frame, text="Readings in ( ) in books:").pack(side=tk.LEFT)
        combo_readings = ttk.Combobox(self.paren_readings_frame,
                                      values=list(self.PAREN_READINGS_LABELS.values()),
                                      state="readonly", width=27)
        combo_readings.set(self.PAREN_READINGS_LABELS.get(self.var_paren_readings.get(),
                                                          self.PAREN_READINGS_LABELS["hiragana"]))
        combo_readings.pack(side=tk.LEFT, padx=(5, 0))
        combo_readings.bind("<<ComboboxSelected>>",
                            lambda e: (self.var_paren_readings.set(self._paren_readings_key(combo_readings.get())),
                                       self.save_settings()))
        ToolTip(combo_readings, "Drops a kanji's reading written after it in brackets, so it isn't "
                                "counted twice: 山田太郎(やまだ・たろう) → 山田太郎. Katakana there is "
                                "often a note, so it stays by default.")

        # Names as one word (Japanese): a name the tagger cuts into pieces is one word, not words it isn't. Packed by
        # update_ui_for_language for Japanese only, like the readings row above. The katakana switch changes how every
        # file is read, so it re-indexes the library in the background; the other three use the library's own tables
        # and take effect at the next Generate.
        self.names_frame = ttk.Frame(self.lang_options_frame)
        for var, text, tip in (
                (self.var_names_katakana, "Katakana names as one word",
                 "A katakana name no dictionary lists stays one word instead of being cut into "
                 "pieces that count as other words: ミロ + ナイ → ミロナイ. Repeated sounds "
                 "(ワンワンワン), stutters (バッバカ) and laughter (アッハハ) stay apart."),
                (self.var_names_recurring, "Names your library repeats as one word",
                 "Ordinary katakana words your content keeps using together, and hardly ever "
                 "apart, become one word — the name of a place or a person in your story. "
                 "Takes effect at the next Generate."),
                (self.var_names_kanji, "Kanji names as one word",
                 "A person's name cut into kanji is one word when a names dictionary "
                 "(JMnedict) lists it and your library uses it 3+ times: 奏 + 汰 → 奏汰. "
                 "Takes effect at the next Generate."),
                (self.var_names_work_terms, "Kanji terms your library repeats as one word",
                 "Kanji words a story makes up — its techniques, places and names — become "
                 "one word when your library keeps using them together: 斬魄刀, 写輪眼. A word "
                 "a dictionary lists never joins this way, and auto-generated captions don't "
                 "count. Takes effect at the next Generate.")):
            # The Rarity slider counts with the library's name tables too: it follows at once.
            chk = ttk.Checkbutton(self.names_frame, text=text, variable=var,
                                  command=lambda: (self.save_settings(), self._refresh_band_preview()))
            chk.pack(anchor=tk.W)
            ToolTip(chk, tip)

        # Phrases and titles as one word (Japanese): a dictionary compound that is a phrase pattern, 元 + a noun or a
        # title is one word, or its parts. Packed by update_ui_for_language below the names switches, Japanese only;
        # it changes how every file is read, so flipping it re-indexes the library in the background.
        self.chk_phrases_and_titles = ttk.Checkbutton(self.lang_options_frame, text="Phrases and titles as one word",
                                                      variable=self.var_phrases_and_titles,
                                                      command=self.save_settings)
        ToolTip(self.chk_phrases_and_titles, "On: 予想通り, こと自体, 元首相 and もののけ姫 each count as one word. "
                                             "Off: they count as their parts (予想 + 通り).")

        # Pronouns with a suffix as one word (Japanese): a pronoun + a suffix the lists carry as a word of its own is
        # one word, or its parts. Packed by update_ui_for_language right below the phrases-and-titles switch, Japanese
        # only; it changes how every file is read, so flipping it re-indexes the library in the background.
        self.chk_pronoun_bases = ttk.Checkbutton(self.lang_options_frame, text="Pronouns with a suffix as one word",
                                                 variable=self.var_pronoun_bases, command=self.save_settings)
        ToolTip(self.chk_pronoun_bases, "On: 何様, 俺様, お前さん and それなり each count as one word. "
                                        "Off: they count as their parts (何 + 様).")

        # Idioms and set phrases on your list (Japanese): the dictionary's set phrases the library meets often enough
        # get rows of their own; nothing is joined in the text, so flipping it re-reads no file — the next Generate
        # lists them, and the Rarity slider counts them once the library's phrases are counted (in the background).
        # Packed by update_ui_for_language right below the pronouns switch, Japanese only.
        self.chk_phrase_rows = ttk.Checkbutton(self.lang_options_frame, text="Idioms and set phrases on your list",
                                               variable=self.var_phrase_rows,
                                               command=lambda: (self.save_settings(), self._refresh_band_preview()))
        ToolTip(self.chk_phrase_rows, "Adds dictionary phrases your library uses often — 気がする, 腑に落ちる, "
                                      "もしかしたら — as rows of their own, each ready once you know the words in it. "
                                      "Their words keep their own rows.")

        # Ignore names (Japanese): a learner learns names too, unless they choose not to — then a name is an ignored
        # word. Packed by update_ui_for_language below the phrases switch, Japanese only. The token store already knows
        # which words are names, so flipping it re-reads nothing: the Rarity slider's numbers follow at once, the
        # list at the next Generate.
        self.chk_ignore_names = ttk.Checkbutton(self.lang_options_frame, text="Ignore names",
                                                variable=self.var_ignore_names,
                                                command=lambda: (self.save_settings(), self._refresh_band_preview()))
        ToolTip(self.chk_ignore_names, "On: people's names (田中, ミロナイ) are treated as ignored words — off your "
                                       "list, and never counted as unknown in a sentence. Takes effect at the next "
                                       "Generate.")

        # Japanese one-character words (exclude_single, the key kept): on, only one-kanji dictionary words are listed,
        # where they stand on their own, and nothing else of one character counts in a sentence; off, every one is
        # listed. It moves the Rarity slider's numbers too (token_index.singles_rule), so the preview follows at once.
        chk_single = ttk.Checkbutton(group_lang, text="List one-kanji words only when they're dictionary words",
                                     variable=self.var_exclude_single,
                                     command=lambda: self._refresh_band_preview())
        chk_single.pack(anchor=tk.W)
        ToolTip(chk_single, "Particles and endings (は, た) and pieces of names or made-up terms stay off your list. "
                            "Words like 手, 目 and 顔 are listed.")

        # How parsing works: the one-page guide (docs/How Parsing Works.md, opened on GitHub like the Tutorial) — what
        # counts as one word, what each switch above changes, with examples. Shown for both languages.
        self.lbl_parsing_guide = ttk.Label(group_lang, text="How parsing works", style="Link.TLabel", cursor="hand2")
        self.lbl_parsing_guide.pack(anchor=tk.W, pady=(4, 0))
        self.lbl_parsing_guide.bind("<Button-1>", lambda e: self.open_parsing_guide())
        ToolTip(self.lbl_parsing_guide, "Opens a one-page guide in your browser: what Surasura counts as one word and "
                                        "what each switch here changes, with examples.")

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
            ToolTip(chk_youtube, "Show a transcript downloader (YouTube and bilibili.tv) in Library Content. Also controls whether it is bundled when you build the app.")

            chk_preview = ttk.Checkbutton(group_lang, text="Enable YouTube Preview", variable=self.var_enable_preview)
            chk_preview.pack(anchor=tk.W, pady=(4, 0))
            ToolTip(chk_preview, "Show a 'Preview against library' button next to Generate Journey, and cache a library frequency map on runs so the preview is fast.")

        # Reels is SUNSET (2026-09-22): no Settings toggle. The module stays on disk and the rest of
        # its wiring stays dormant (enable_reels false, excluded from every build) — see
        # docs/agent instructions/Reels_Module_Spec.md for how to bring it back.

        # Junban toggle (optional module). Shown only when the module is present locally. Unlike
        # Reels there is no language condition — reordering an Anki backlog works for ja and zh alike.
        try:
            import modules.junban  # noqa: F401
            _junban_module_available = True
        except Exception:
            _junban_module_available = False
        if _junban_module_available:
            chk_junban = ttk.Checkbutton(group_lang, text="Enable Anki reordering", variable=self.var_enable_junban)
            chk_junban.pack(anchor=tk.W, pady=(4, 0))
            ToolTip(chk_junban, "Show the 順 button, which reorders the new cards already in your Anki "
                                "backlog to follow this learn order. Needs Anki open with AnkiConnect. "
                                "Also controls whether it is bundled when you build the app.")

        # 2. 📊 Experience & UI
        group_ui = ttk.LabelFrame(left_col, text=" 📊 Experience & UI", padding="10")
        group_ui.pack(fill=tk.X, pady=5)

        chk_inline = ttk.Checkbutton(group_ui, text="Show 'Target Met' inline", variable=self.var_inline_completed)
        chk_inline.pack(anchor=tk.W)
        ToolTip(chk_inline, "Keep met files in order instead of moving them down.")

        chk_hide_audio = ttk.Checkbutton(group_ui, text="Hide Audio Button (Speaker)", variable=self.var_hide_audio)
        chk_hide_audio.pack(anchor=tk.W)
        ToolTip(chk_hide_audio, "Hide speaker icon in the report.")

        # "Label backlogged Anki words" (Junban_Backlog_Spec WP-B8): mark each word a new card is
        # already waiting for in Anki. Presentation only — it re-renders, never re-analyzes. Shown
        # only once Anki sync is set up (decks chosen in the Anki window): without Anki there is
        # nothing to label, and no checkbox to wonder about (§11.1 item 3).
        if anki_sync_is_set_up(settings_manager.load_settings()):
            chk_anki_label = ttk.Checkbutton(group_ui, text="Label backlogged Anki words",
                                             variable=self.var_anki_backlog_on_generate)
            chk_anki_label.pack(anchor=tk.W)
            ToolTip(chk_anki_label, "Mark each word that already has a new card waiting in your Anki "
                                    "decks: a small card icon on the word, an 'In Anki' Show filter, "
                                    "and a count per episode. Reads the decks chosen in the Anki "
                                    "window. Takes effect on your next Generate.")

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

        # Word lookup (⌕) button on each card. Presentation only, like the badge above: both the
        # toggle and the category re-render the report but never re-analyze.
        chk_word_search = ttk.Checkbutton(group_ui, text="Show word lookup button (⌕)",
                                          variable=self.var_word_search,
                                          command=self.save_settings)
        chk_word_search.pack(anchor=tk.W, pady=(8, 0))
        ToolTip(chk_word_search, "Show a search icon beside Ignore on every word, opening that word "
                                 "on Nadeshiko in a new tab. Hotkey: \\")

        ws_frame = ttk.Frame(group_ui)
        ws_frame.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(ws_frame, text="Lookup examples from:").pack(side=tk.LEFT)
        combo_ws = ttk.Combobox(ws_frame, values=list(self.WORD_SEARCH_LABELS.values()),
                                state="readonly", width=13)
        combo_ws.set(self.WORD_SEARCH_LABELS.get(self.var_word_search_category.get(), "All"))
        combo_ws.pack(side=tk.LEFT, padx=(5, 0))
        combo_ws.bind("<<ComboboxSelected>>",
                      lambda e: (self.var_word_search_category.set(self._word_search_key(combo_ws.get())),
                                 self.save_settings()))
        ToolTip(combo_ws, "Which kind of example sentences the lookup opens. 'All' searches "
                          "everything; the others filter to anime, live action or YouTube.")

        # Speech. Grouped here because its control in the report IS the source badge above: with
        # speech on, clicking a badge reads the sentence aloud instead of copying the path.
        #
        # Shown only to someone who has deliberately added `"enable_koe"` to their settings.json.
        # The module ships with the app, but for everyone who hasn't asked for it there is no
        # toggle, no helper and no trace in their settings — the app is unchanged.
        try:
            import modules.koe as _koe_ui
            _koe_module_available = _koe_ui.is_revealed()
        except Exception:
            _koe_module_available = False
        if _koe_module_available:
            koe_frame = ttk.Frame(group_ui)
            koe_frame.pack(fill=tk.X, pady=(8, 0))
            chk_koe = ttk.Checkbutton(koe_frame, text="Speak sentences (Gemini)",
                                      variable=self.var_enable_koe)
            chk_koe.pack(side=tk.LEFT)
            ToolTip(chk_koe, "Click a sentence's source badge in the report to hear it read aloud. "
                             "Needs a Gemini API key and sends that sentence to Google — the only "
                             "part of Surasura that uses the internet. YouTube badges still open "
                             "the video instead.")
            btn_koe = ttk.Button(koe_frame, text="Speech settings…", width=17,
                                 command=self.open_koe_settings)
            btn_koe.pack(side=tk.LEFT, padx=(8, 0))
            ToolTip(btn_koe, "Set the API key, voice and delivery for spoken sentences.")

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
        group_logic = ttk.LabelFrame(right_col, text=" 🧠 Sentences & Logic", padding="10")
        group_logic.pack(fill=tk.X, pady=5)

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

        # Automatic rarity (logic.selection.auto): every Generate picks the Rarity band itself and the
        # main window's slider is locked on it. The line is logic.selection.auto_max_words.
        chk_auto_band = ttk.Checkbutton(group_logic, text="Automatic rarity", variable=self.var_auto_band)
        chk_auto_band.pack(anchor=tk.W)
        ToolTip(chk_auto_band, lambda: (
            f"Picks the Rarity band for you: the rarest band with {self._auto_max_words_text()} words or "
            f"fewer, and keeps it until its list passes {self._auto_step_back_text()}, so your list doesn't "
            "flip back and forth. It moves on by itself as you learn. The slider on the main window is locked while "
            "this is on. By Commonness only."))


        # --- RIGHT COLUMN (Col 1) ---

        # 4. 🧮 Data & System
        group_data = ttk.LabelFrame(right_col, text=" 🧮 Data & System", padding="10")
        group_data.pack(fill=tk.X, pady=5, before=group_logic)   # Data first, then Sentences

        chk_telemetry = ttk.Checkbutton(group_data, text="Enable Anonymous Telemetry", variable=self.var_telemetry_enabled)
        chk_telemetry.pack(anchor=tk.W, pady=(0, 10))
        ToolTip(chk_telemetry, "Send anonymous usage stats.")

        chk_auto_update = ttk.Checkbutton(group_data, text="Automatic Updates", variable=self.var_auto_update)
        chk_auto_update.pack(anchor=tk.W, pady=(0, 10))
        ToolTip(chk_auto_update, "Offer one-click in-app updates for minor releases. Major updates always download manually.")

        # The way back from "Skip this version", which hides that version's offer for good (the user,
        # 2026-09-25: one accidental Skip left no way to update in one click). Shown only while the
        # skipped version is still newer than this one (`_sync_skipped_row`).
        self._chk_auto_update = chk_auto_update
        self.btn_offer_skipped = ttk.Button(group_data, command=self._offer_skipped_again, width=20)
        ToolTip(self.btn_offer_skipped, "You chose Skip this version. Offer it again as a one-click update.")
        self._sync_skipped_row()

        # The Anki options live in the Anki button's window, beside the decks they depend on (the
        # user, 2026-09-23): "Sync automatically when Anki is running" — one setting, which used to
        # have a second checkbox here — and "Generate when Anki adds known words". Reading the Anki
        # backlog is "Label backlogged Anki words" in Experience & UI, with the label it switches.

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
        btn_reading_words.pack(fill=tk.X, pady=(0, 5))
        ToolTip(btn_reading_words, "A Yomitan list of words you'll read but hardly ever hear. If a word shows up in it while mining, make it a reading card.")

        btn_sentence_dictionary = ttk.Button(group_data, text="Export Sentence Dictionary", command=self.export_sentence_dictionary, width=20)
        btn_sentence_dictionary.pack(fill=tk.X)
        ToolTip(btn_sentence_dictionary, "A Yomitan dictionary of up to 8 of the best sentences for every word in your library — hover a word in your browser to see them.")

        # Credits: hover to read every data source Surasura ships or is built from, with its licence (DATA_CREDITS).
        self.lbl_credits = ttk.Label(group_data, text="ⓘ Data credits", cursor="question_arrow")
        self.lbl_credits.pack(anchor=tk.W, pady=(8, 0))
        ToolTip(self.lbl_credits, data_credits, wrap=520)

        # 5. 📜 Processing Log (Right Side)
        log_frame = ttk.LabelFrame(right_col, text=" 📜 Processing Log", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

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

    @staticmethod
    def _write_install_note():
        try:
            from app import path_utils
            path_utils.write_install_note()
        except Exception as e:
            print(f"Install note: {e}")

    def check_updates_thread(self):
        """Background thread: check GitHub, classify, and surface a non-blocking indicator.

        The network is entirely optional here — any failure (offline, timeout, no release)
        leaves the app running normally with no indicator. The decision to update is always
        the user's; this only lights the footer.
        """
        try:
            info = get_update_info()
            cls = classify_update(__version__, info)
            # Apply the skip / kill-switch / anti-loop guard using saved settings (thread-safe: we
            # read the plain dict, not tk vars). A skipped version isn't offered at all; a disabled
            # toggle, a missing updater.exe, or a version that already failed downgrades an APP
            # update to manual.
            cur = getattr(self, "_current_settings", {}) or {}
            cls = updater.effective_class(
                cls, info,
                skipped_version=cur.get("skipped_version", ""),
                auto_enabled=cur.get("auto_update_enabled", True),
                can_apply=updater.can_auto_apply(info),
                failed_version=updater.failed_version(cur),
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

        body = self._update_body(cls, info, getattr(self, "failed_update_version", ""))
        ttk.Label(wrapper, text=body, wraplength=400, justify=tk.LEFT,
                  foreground=TEXT_COLOR, background=BG_COLOR, font=('Segoe UI', 10)).pack(anchor=tk.W, pady=(0, 16))

        btn_row = ttk.Frame(wrapper)
        btn_row.pack(fill=tk.X)

        if cls == "INSTALLER":
            btn_now = ttk.Button(btn_row, text="Update now", style="Action.TButton",
                                 command=lambda: self._do_installer_update(dialog))
            btn_now.pack(side=tk.LEFT)
            ToolTip(btn_now, "Download Surasura's installer, close Surasura and start it.")
            btn_skip = ttk.Button(btn_row, text="Skip this version",
                                  command=lambda: self._skip_update(dialog))
            btn_skip.pack(side=tk.LEFT, padx=(8, 0))
            ToolTip(btn_skip, "Don't offer this version again.")
        elif cls == "APP":
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

    @staticmethod
    def _update_body(cls, info, failed_version=""):
        """What the update dialog says. A version whose in-app update already failed is a manual
        download for that reason — it isn't "a larger update", and saying so sent people looking."""
        if cls == "INSTALLER":
            return ("This version installs with its own installer: Surasura closes, the installer starts, "
                    "and it brings your library, words and settings with it.")
        if cls == "APP":
            return ("This is a quick in-app update — it refreshes only the program code and "
                    "report templates (about 15–20 MB). Your words, data, settings, and file "
                    "order are never touched. Surasura will briefly close and reopen.")
        version = getattr(info, "version", "")
        if failed_version and version == failed_version:
            return (f"The in-app update to v{version} didn't finish last time, so this one is a "
                    "manual download. Your personal data stays where it is.")
        return ("This is a larger update and should be downloaded manually (it changes more "
                "than the app code). Your personal data stays where it is.")

    def _skip_update(self, dialog):
        """Remember this version so it is never offered again — a newer one is, and Settings → Data &
        System can bring this one back — and hide the indicator."""
        info = self._update_info
        if info:
            self.skipped_version = info.version
            self.save_settings()
            self._sync_skipped_row()
        if self.update_label:
            self.update_label.pack_forget()
        self.status_var.set("Ready")
        dialog.destroy()

    def _sync_skipped_row(self):
        """Settings' "vX skipped — Offer again": there only while a skipped version is still newer than
        this one (after a manual update to it, or past it, there's nothing to bring back)."""
        button = getattr(self, "btn_offer_skipped", None)
        if button is None:
            return
        version = getattr(self, "skipped_version", "")
        try:
            if version and parse_version(version) > parse_version(__version__):
                button.config(text=f"v{version} skipped — Offer again")
                if button.winfo_manager() != "pack":
                    button.pack(fill=tk.X, pady=(0, 10), after=self._chk_auto_update)
            elif button.winfo_manager() == "pack":
                button.pack_forget()
        except tk.TclError:
            pass

    def _offer_skipped_again(self):
        """Undo "Skip this version": forget the skip and check again, so the footer offers it — in one
        click, unless its in-app update once failed."""
        self.skipped_version = ""
        self.save_settings()
        self._sync_skipped_row()
        if not os.environ.get("SURASURA_NO_UPDATE_CHECK"):
            threading.Thread(target=self.check_updates_thread, daemon=True).start()

    def _do_auto_update(self, dialog):
        """"Update now": stage the app package (`updater.prepare_update`) while everything else of Surasura's that
        holds this install's programs finishes (K75), then hand over to updater.exe."""
        dialog.destroy()
        info = self._update_info
        if not info:
            return
        if not updater.can_auto_apply(info):
            # No bundled updater.exe (e.g. running from source), or a file list naming a destination an in-place
            # update may not write — fall back to manual.
            webbrowser.open(info.notes_url)
            return
        self._start_update(info, updater.prepare_update)

    def _do_installer_update(self, dialog):
        """"Update now" on an installer release (3.0, S1.3-6): the same wait (K75), then the installer starts and the
        app exits. Never reached by a 2.x release (`update_checker.installer_ready`)."""
        dialog.destroy()
        info = self._update_info
        if not info:
            return
        from app.path_utils import is_frozen
        if not is_frozen():
            webbrowser.open(info.notes_url)
            return
        self._start_update(info, updater.prepare_installer)

    def _start_update(self, info, stage):
        """From "Update now" until the hand-over: the update lock held (the command line answers `update-staged`), no
        new child process started (`updater.hold_children`), the download running on a worker meanwhile, and a
        non-modal window naming whatever still runs, polled with `after`. Nothing is written for the helper until
        the final callback (`_apply_and_restart`), so a cancel, a close or a crash leaves nothing armed."""
        lock = updater.take_update_lock()
        if lock is None:                              # this window's own update, or another install's
            messagebox.showinfo("Update", "Another Surasura update is already in progress.")
            return
        updater.hold_children()
        self._replan_stop_for_update()
        job = {"info": info, "lock": lock, "staged": None, "error": None, "done": False, "children": None,
               "listing": False, "window": None, "rows": None, "after": None}
        self._update_job = job
        self.status_var.set("Downloading update…")

        def worker():
            try:
                job["staged"] = stage(info)
            except Exception as e:
                job["error"] = e
            job["done"] = True
            # Back on the window's thread: a failure is said at once; a finished download may hand over now.
            self.gui_queue.put(lambda: self._update_downloaded(job))

        threading.Thread(target=worker, daemon=True).start()
        self._update_poll(job)

    def _update_downloaded(self, job):
        if job.get("ended"):
            # Cancelled (or closed) while it downloaded: its staging is discarded and the lock freed only now, so a
            # new "Update now" can never stage into the folder this worker was still writing.
            updater.discard_staged()
            updater.drop_update_lock(job.get("lock"))
            if job.get("start_held"):
                self._replan_restart()                 # a cancel during the download (pass 5 #1)
            return
        if job is not getattr(self, "_update_job", None):
            return
        err = job["error"]
        if err is None:
            self.status_var.set("Update downloaded.")
            self._update_poll(job)
            return
        self._end_update(job)
        report = updater.write_report("download", err, to_version=getattr(job["info"], "version", ""))
        messagebox.showerror(
            "Update",
            f"Couldn't download the update:\n{err}\n\n"
            "You can try again later, or update manually from the releases page."
            + self._update_report_note(report))
        self.status_var.set("Ready")

    def _list_update_children(self, job):
        """Worker: what still runs (`updater.running_children`), for the next poll — the listing never runs on the
        window's thread while the update waits."""
        try:
            job["children"] = self._busy_threads() + updater.running_children(list(self.active_processes))
        except Exception as e:
            print(f"Update: {e}")
            job["children"] = []
        job["listing"] = False

    def _busy_threads(self):
        """This window's own background work that writes to Anki (the known-words sync, Junban's automatic reorder and
        Backfill): no process to list, but an exit mid-write would leave Anki half-written. Waited for; no Stop.
        A thread here holding the Anki-write lock (順, Backfill, the automatic step: E1.4) is one entry naming what it
        writes; when that is the automatic step, in place of its own lock's entry — never listed twice."""
        from app import anki_connect, locks
        writing = locks.held_in_process(anki_connect.WRITER_LOCK)
        busy = []
        for attr, name in (("_anki_sync_lock", "Anki sync"), ("_junban_auto_lock", "Junban's automatic reorder")):
            lock = getattr(self, attr, None)
            if lock is not None and lock.locked() and not (
                    attr == "_junban_auto_lock" and writing == anki_connect.AUTOMATIC_STEP):
                busy.append({"pid": None, "name": name, "stop": None})
        if writing is not None:
            busy.append({"pid": None, "name": f"Writing to Anki ({writing or 'Surasura'})", "stop": None})
        return busy

    def _update_poll(self, job):
        """Every 300 ms while the update waits: refresh the list of what it waits for (on a worker), show it, and hand
        over once the download is done and nothing is left."""
        if job is not getattr(self, "_update_job", None):
            return
        if job.get("after") is not None:
            try:
                self.root.after_cancel(job["after"])
            except Exception:
                pass
            job["after"] = None
        children = job["children"]
        if children:
            self._show_update_wait(job, children)
        elif children is not None and job["done"] and job["error"] is None:
            if self._apply_and_restart(job):
                return
        elif job["window"] is not None:
            self._show_update_wait(job, children or [])
        if not job["listing"]:
            job["listing"] = True
            threading.Thread(target=self._list_update_children, args=(job,), daemon=True).start()
        try:
            job["after"] = self.root.after(300, lambda: self._update_poll(job))
        except Exception:
            pass

    def _show_update_wait(self, job, children):
        """The waiting window: non-modal, one row per running item with *Stop it*, *Stop all and update now*, and
        *Cancel* (Esc, or closing it, cancels too)."""
        win = job["window"]
        if win is None or not win.winfo_exists():
            win = tk.Toplevel(self.root)
            win.title("Update waiting")
            win.configure(bg=BG_COLOR)
            win.transient(self.root)
            win.resizable(False, False)
            win.bind("<Escape>", lambda e: self._cancel_update(job))
            win.protocol("WM_DELETE_WINDOW", lambda: self._cancel_update(job))
            wrapper = ttk.Frame(win, padding=10)
            wrapper.pack(fill=tk.BOTH, expand=True)
            ttk.Label(wrapper, text=f"Surasura v{getattr(job['info'], 'version', '')} will install when these finish:",
                      font=('Segoe UI', 11, 'bold'), foreground=SECONDARY_COLOR, background=BG_COLOR,
                      wraplength=420, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 8))
            job["list_frame"] = ttk.Frame(wrapper)
            job["list_frame"].pack(fill=tk.X)
            job["status"] = ttk.Label(wrapper, text="", foreground="#aaa", background=BG_COLOR)
            job["status"].pack(anchor=tk.W, pady=(8, 8))
            btn_row = ttk.Frame(wrapper)
            btn_row.pack(fill=tk.X)
            stop_all = ttk.Button(btn_row, text="Stop all and update now", style="Action.TButton",
                                  command=lambda: self._stop_update_children(job, None))
            stop_all.pack(side=tk.LEFT)
            ToolTip(stop_all, "Stop everything listed here, then install the update and reopen Surasura.")
            cancel = ttk.Button(btn_row, text="Cancel", command=lambda: self._cancel_update(job))
            cancel.pack(side=tk.RIGHT)
            ToolTip(cancel, "Don't update now. Everything keeps running; the update is offered again later.")
            job["window"], job["rows"] = win, None
        pids = tuple(c["pid"] or c["name"] for c in children)
        if job["rows"] != pids:
            job["rows"] = pids
            for w in job["list_frame"].winfo_children():
                w.destroy()
            if not children:
                ttk.Label(job["list_frame"], text="Nothing left to wait for.", background=BG_COLOR,
                          foreground=TEXT_COLOR).pack(anchor=tk.W)
            for child in children:
                row = ttk.Frame(job["list_frame"])
                row.pack(fill=tk.X, pady=2)
                ttk.Label(row, text=child["name"], background=BG_COLOR, foreground=TEXT_COLOR).pack(side=tk.LEFT)
                if child["stop"] is None:              # this window's own work: it finishes by itself
                    ttk.Label(row, text="finishing…", background=BG_COLOR, foreground="#888").pack(side=tk.RIGHT)
                    continue
                stop = ttk.Button(row, text="Stop it", command=lambda c=child: self._stop_update_children(job, [c]))
                stop.pack(side=tk.RIGHT)
                ToolTip(stop, f"Close \"{child['name']}\" as if you closed it yourself (it finishes what it is doing; "
                              "a task without a window is stopped). The update goes on once nothing else is running.")
        job["status"].config(text="Downloading the update…" if not job["done"] else "The update is downloaded.")

    def _stop_update_children(self, job, children):
        """*Stop it* (one item) or *Stop all* (None: everything listed)."""
        for child in (job["children"] or []) if children is None else children:
            if child.get("stop") is None:
                continue
            try:
                child["stop"]()
            except Exception:
                pass
        job["children"] = None                         # ask again, now
        self._update_poll(job)

    def _cancel_update(self, job, start_held=True):
        """Esc / Cancel / closing the waiting window: nothing armed, the lock released, children free to start (those
        asked for meanwhile start now — but not when the dashboard itself is closing: `start_held=False`, they would
        outlive it); the update is offered again later."""
        if job is not getattr(self, "_update_job", None):
            return
        self._end_update(job, start_held)
        if job.get("done"):
            updater.discard_staged()               # else the download worker discards it when it ends
        self.status_var.set("Update cancelled.")

    def _end_update(self, job, start_held=True):
        self._update_job = None
        job["ended"] = True
        if job.get("after") is not None:
            try:
                self.root.after_cancel(job["after"])
            except Exception:
                pass
        win = job.get("window")
        try:
            if win is not None and win.winfo_exists():
                win.destroy()
        except Exception:
            pass
        job["start_held"] = start_held
        if job.get("done"):
            updater.drop_update_lock(job.get("lock"))  # else when the download worker ends (_update_downloaded)
        updater.release_children(start=start_held)
        if start_held:
            try:
                self._maybe_auto_generate()            # one held back meanwhile
            except Exception:
                pass
            if job.get("done"):
                self._replan_restart()                 # else once the download worker drops the lock (pass 5 #1)

    def _replan_restart(self):
        """The preview's helper, stopped at "Update now", started again once the update's lock is gone — a helper
        started while it is held would find an update staged and leave the jobs to this window's process."""
        try:
            self._replan_start()
        except Exception:
            pass

    def _apply_and_restart(self, job):
        """The final callback, all on the window's thread: the last check (`can_update_now`), the note (K100), the
        marker and the helper's launch, then the exit. -> True when it handed over or gave up (the update is over);
        False when something started meanwhile (the wait goes on)."""
        if self._busy_threads() or not updater.can_update_now(list(self.active_processes)):
            job["children"] = None
            return False
        # The library store's helper (a detached process, not a child): its maintenance lock, every language,
        # held from here until this process exits — the swap comes after (Library_Store_Spec §7).
        locks = updater.hold_library_locks()
        if locks is None:
            job["children"] = None
            return False
        self._update_library_locks = locks
        self._write_install_note()
        try:
            updater.arm_and_launch(job["staged"])
        except Exception as e:
            updater.release_library_locks(self.__dict__.pop("_update_library_locks", None))
            self._end_update(job)
            report = updater.write_report("start updater", e,
                                          to_version=getattr(self._update_info, "version", ""))
            messagebox.showerror("Update", f"Couldn't start the updater:\n{e}"
                                 + self._update_report_note(report))
            self.status_var.set("Ready")
            return True
        self.root.destroy()                            # updater.exe waits on this process; the OS frees the lock
        return True

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
            # the manual path. This is the loop-breaker — its own mark, not a skip: the version is
            # still offered, as a download.
            ver = res.get("to") or ""
            if ver:
                self.failed_update_version = ver
                updater.record_failed_version(ver)     # this install's update_state.json, never settings.json
            reason = res.get("reason", "")
            report = updater.write_report("install", reason, to_version=ver,
                                          from_version=res.get("from") or "")
            detail = f" ({reason})" if reason else ""
            if messagebox.askyesno(
                "Update",
                f"The automatic update didn't finish{detail}."
                + self._update_report_note(report)
                + "\n\nOpen the download page to update manually?"):
                webbrowser.open("https://github.com/SonicSandbox/surasura/releases/latest")

    @staticmethod
    def _update_report_note(report):
        """The dialog lines naming a saved update report ('' when none could be written)."""
        if not report:
            return ""
        return ("\n\nA report was saved to:\n" + report +
                "\nIf this keeps happening, please attach it to an issue at "
                "github.com/SonicSandbox/surasura/issues.")

    def log_to_terminal(self, message):
        """Appends text to the terminal widget safely via queue"""
        def _update():
            if self.terminal:
                self.terminal.config(state=tk.NORMAL)
                self.terminal.insert(tk.END, message + "\n")
                self.terminal.see(tk.END)
                self.terminal.config(state=tk.DISABLED)
        self.gui_queue.put(_update)

    # Footer order of the optional module buttons, left to right. Settings (⚙) always follows them.
    _MODULE_BUTTONS = ("btn_reels", "btn_junban")

    def _module_slot(self, btn):
        """The footer widget a module button must be packed BEFORE, so the buttons keep one fixed
        order and ⚙ stays right-most: the next module button that is currently shown, else ⚙."""
        names = self._MODULE_BUTTONS
        buttons = [getattr(self, n, None) for n in names]
        start = buttons.index(btn) + 1 if btn in buttons else len(buttons)
        for later in buttons[start:]:
            try:
                if later is not None and later.winfo_manager():   # packed (mapped or not yet drawn)
                    return later
            except tk.TclError:
                pass
        return self.btn_settings

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

    def open_koe_settings(self):
        # Orchestration lives in the module; the core only needs a thin, lazy entry point.
        try:
            from modules.koe import open_koe_settings
        except (ImportError, ModuleNotFoundError):
            return
        open_koe_settings(self)

    def apply_koe_state(self):
        """Start or stop the speech helper to match the toggle, and keep the badge reachable.

        The report's speech control IS the per-sentence source badge, so with
        `source_display = "off"` there would be no button to click. Turning speech on therefore
        promotes the badge to at least "Icon only" — a display change, which re-renders the report
        but never re-analyzes (see analyzer.compute_render_signature).
        """
        # `import modules.koe` rather than `from modules import koe`: the latter reads the ATTRIBUTE
        # off the already-imported parent package, which survives even when the submodule is gone,
        # so the guard would not fire. This is also the form update_youtube_visibility uses.
        try:
            import modules.koe as koe
        except (ImportError, ModuleNotFoundError):
            return

        enabled = self.var_enable_koe.get()
        if enabled and self.var_source_display.get() == "off":
            self.var_source_display.set("icon")     # traced -> persisted by save_settings
            self.save_settings()

        try:
            if enabled:
                koe.start_server(self)
            else:
                koe.stop_server()
        except Exception as e:
            print(f"Warning: could not change the speech helper state: {e}")

    def open_reels(self):
        # Orchestration (linking, pairing, syncing, merging, cutting) lives in the module; the core
        # only needs a thin, lazy entry point.
        try:
            from modules.reels import open_reels
        except (ImportError, ModuleNotFoundError):
            return
        open_reels(self)

    def update_reels_visibility(self):
        """Shows the Reels button only if enabled in settings, the module is available, AND the
        active language is one it can serve.

        The language question is asked of the module rather than answered here: its cue merger reads
        UniDic inflection features that Jieba has no equivalent for, and that is the module's
        business to know. A feature that cannot work is hidden rather than shown failing.
        """
        if not hasattr(self, 'btn_reels') or self.btn_reels is None:
            return

        should_show = False
        if self.var_enable_reels.get():
            try:
                import modules.reels as reels
                should_show = reels.supports_language(self.var_language.get())
            except (ImportError, ModuleNotFoundError):
                # Module absent (open-source build or excluded by the conditional build)
                should_show = False

        if should_show:
            if not self.btn_reels.winfo_ismapped():
                self.btn_reels.pack(side=tk.LEFT, padx=(5, 0), before=self._module_slot(self.btn_reels))
        else:
            self.btn_reels.pack_forget()

    def open_junban(self):
        # Everything — AnkiConnect, the match index, the planner, the undo snapshot and the panel
        # — lives in the module; the core only needs a thin, lazy entry point.
        try:
            from modules.junban import open_junban
        except (ImportError, ModuleNotFoundError):
            return
        open_junban(self)

    def update_junban_visibility(self):
        """Shows the 順 button only if enabled in settings AND the module is available.

        No language condition, unlike Reels: reordering an Anki backlog by rank is language-agnostic,
        and the one Japanese-specific part (the orthBase match key) has no Chinese equivalent to
        miss — zh simply degrades to the lemma key.
        """
        if not hasattr(self, 'btn_junban') or self.btn_junban is None:
            return

        should_show = False
        if self.var_enable_junban.get():
            try:
                # `import modules.junban` rather than `from modules import junban`: the latter reads
                # the ATTRIBUTE off the already-imported parent package, which survives even when the
                # submodule is gone, so the guard would not fire (see apply_koe_state).
                import modules.junban  # noqa: F401
                should_show = True
            except (ImportError, ModuleNotFoundError):
                # Module absent (open-source build or excluded by the conditional build)
                should_show = False

        if should_show:
            if not self.btn_junban.winfo_ismapped():
                self.btn_junban.pack(side=tk.LEFT, padx=(5, 0), before=self._module_slot(self.btn_junban))
        else:
            self.btn_junban.pack_forget()
        # The Anki window's "Backfill cards…" follows the same switch (the user, 2026-09-24).
        window = getattr(self, "anki_sync_window", None)
        try:
            if window is not None and window.winfo_exists():
                window.sync_backfill_button()
        except Exception:
            pass

    def backfill_available(self):
        """Is Anki Backfill offered? Only while Junban is switched on AND importable — it lives there.
        Asked by the Anki window, which must not import a module itself (Anki_Known_Sync_Spec I1)."""
        if not self.var_enable_junban.get():
            return False
        try:
            import modules.junban  # noqa: F401
        except (ImportError, ModuleNotFoundError):
            return False
        return True

    def open_backfill(self):
        # One window, whichever door: the module keeps it on this dashboard (`host.backfill_window`).
        if not self.backfill_available():
            return
        from modules.junban import open_backfill
        open_backfill(self)

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

            zh_mode = settings.get("zh_script", "asis")
            self.var_zh_script.set(zh_mode if zh_mode in self.ZH_SCRIPT_LABELS else "asis")
            src_mode = settings.get("source_display", "off")
            self.var_source_display.set(src_mode if src_mode in self.SOURCE_DISPLAY_LABELS else "off")
            self.var_word_search.set(settings.get("word_search_enabled", True))
            ws_cat = settings.get("word_search_category", "all")
            self.var_word_search_category.set(ws_cat if ws_cat in self.WORD_SEARCH_LABELS else "all")
            self.var_sentence_dictionary_source.set(bool(settings.get("sentence_dictionary_source", False)))
            self.var_telemetry_enabled.set(settings.get("telemetry_enabled", True))
            self.var_only_i_plus_one.set(settings.get("only_i_plus_one", False))
            self.var_ensure_audio.set(settings.get("ensure_audio_example", False))
            self.var_add_graduated.set(settings.get("add_graduated_words", True))
            self.var_words_per_day.set(settings.get("words_per_day", 5))
            self.var_show_words_per_day.set(settings.get("show_words_per_day", True))
            self.var_zen_limit.set(settings.get("zen_limit", 50))

            self.onboarding_completed.set(settings.get("onboarding_completed", False))
            self.var_open_count.set(settings.get("open_count", 0))

            self.var_enable_youtube.set(settings.get("enable_youtube_transcripts", False))
            self.youtube_risk_acknowledged = settings.get("youtube_risk_acknowledged", False)
            self.update_youtube_visibility()

            self.var_enable_preview.set(settings.get("enable_youtube_preview", False))
            self.update_preview_visibility()

            self.var_enable_koe.set(settings.get("enable_koe", False))
            self.apply_koe_state()

            self.var_enable_reels.set(settings.get("enable_reels", False))
            self.update_reels_visibility()

            self.var_enable_junban.set(settings.get("enable_junban", False))
            self.update_junban_visibility()

            self.var_auto_update.set(settings.get("auto_update_enabled", True))
            self.var_anki_sync_auto.set(bool(settings.get("anki_sync_auto", False)))
            self.var_anki_backlog_on_generate.set(bool(settings.get("anki_backlog_on_generate", True)))
            self.var_anki_auto_generate.set(bool(settings.get("anki_auto_generate", False)))
            self.skipped_version = settings.get("skipped_version", "")
            self.failed_update_version = updater.failed_version(settings)
            self._sync_skipped_row()

            # Load Logic Settings
            self.logic_settings = settings.get("logic", {})
            self.var_inline_completed.set(self.logic_settings.get("inline_completed_files", False))
            self.var_hide_audio.set(self.logic_settings.get("hide_audio_button", False))
            readings = self.logic_settings.get("paren_readings", "hiragana")
            self.var_paren_readings.set(readings if readings in self.PAREN_READINGS_LABELS else "hiragana")
            self.var_names_katakana.set(bool(self.logic_settings.get("names_katakana", True)))
            self.var_names_recurring.set(bool(self.logic_settings.get("names_recurring", True)))
            self.var_names_kanji.set(bool(self.logic_settings.get("names_kanji", True)))
            self.var_names_work_terms.set(bool(self.logic_settings.get("names_work_terms", True)))
            self.var_phrases_and_titles.set(bool(self.logic_settings.get("phrases_and_titles", True)))
            self.var_pronoun_bases.set(bool(self.logic_settings.get("pronoun_bases", True)))
            self.var_phrase_rows.set(bool(self.logic_settings.get("phrase_rows", True)))
            self.var_ignore_names.set(bool(self.logic_settings.get("ignore_names", False)))
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
            # Automatic rarity: the slider locks on the band it picks ("Auto" until a preview lands).
            self.var_auto_band.set(sel.get("auto") is True)
            if self.var_auto_band.get():
                self._apply_effective_bands()

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
        """The widgets are read here, on the window's thread; the file is read and written by the settings writer
        (`settings_manager.SettingsWriter`, P0.3 04 §2) on its worker, under the `settings` lock — this thread never
        waits on it. Under test, or with no writer, it is written here at once."""
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
                "zh_script": self.var_zh_script.get(),
                "source_display": self.var_source_display.get(),
                "word_search_enabled": self.var_word_search.get(),
                "word_search_category": self.var_word_search_category.get(),
                "sentence_dictionary_source": self.var_sentence_dictionary_source.get(),
                "telemetry_enabled": self.var_telemetry_enabled.get(),
                "only_i_plus_one": self.var_only_i_plus_one.get(),
                "ensure_audio_example": self.var_ensure_audio.get(),
                "add_graduated_words": self.var_add_graduated.get(),
                "words_per_day": self._iv(self.var_words_per_day, cur.get("words_per_day", 5)),
                "show_words_per_day": self.var_show_words_per_day.get(),
                "zen_limit": self._iv(self.var_zen_limit, cur.get("zen_limit", 50)),
                "onboarding_completed": self.onboarding_completed.get(),
                "open_count": self._iv(self.var_open_count, cur.get("open_count", 0)),
                "auto_update_enabled": self.var_auto_update.get(),
                "anki_sync_auto": self.var_anki_sync_auto.get(),
                "anki_backlog_on_generate": self.var_anki_backlog_on_generate.get(),
                "anki_auto_generate": self.var_anki_auto_generate.get(),
                "skipped_version": getattr(self, "skipped_version", ""),
                "logic": {
                    **self.logic_settings,
                    "inline_completed_files": self.var_inline_completed.get(),
                    "hide_audio_button": self.var_hide_audio.get(),
                    "paren_readings": self.var_paren_readings.get(),
                    "names_katakana": self.var_names_katakana.get(),
                    "names_recurring": self.var_names_recurring.get(),
                    "names_kanji": self.var_names_kanji.get(),
                    "names_work_terms": self.var_names_work_terms.get(),
                    "phrases_and_titles": self.var_phrases_and_titles.get(),
                    "pronoun_bases": self.var_pronoun_bases.get(),
                    "phrase_rows": self.var_phrase_rows.get(),
                    "ignore_names": self.var_ignore_names.get(),
                    # Persist the whole selection block (bands_ppm / min_count / minutes_per_file /
                    # auto_max_words are user-editable in settings.json, like 'weights'); the slider
                    # sets 'band', the Automatic rarity checkbox 'auto'.
                    "selection": {
                        **self.logic_settings.get("selection", {}),
                        "band": self.var_band.get(),
                        "auto": self.var_auto_band.get(),
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

            # The speech module ships inside the app but stays hidden until the user adds the
            # `enable_koe` line to settings.json themselves. Nothing about it is written back
            # unless that line is already there — otherwise the first save would scatter koe_*
            # keys through every user's settings and the feature would announce itself.
            carried = []        # (key, also when absent from the file) — read from the file as it is when written
            try:
                import modules.koe as _koe
                if _koe.is_revealed():
                    settings["enable_koe"] = self.var_enable_koe.get()
                    carried += ["koe_voice", "koe_model", "koe_style", "koe_temperature", "koe_port", "koe_daily_cap"]
            except (ImportError, ModuleNotFoundError):
                pass

            # Reels: the toggle plus whichever of its own tunables the user already has. Written
            # only when the module imports, so a build without it never gains those keys — and the
            # module's own defaults are carried through rather than reset on every save.
            try:
                import modules.reels as _reels
                settings["enable_reels"] = self.var_enable_reels.get()
                carried += [k for k in _reels.SETTINGS_DEFAULTS if k != "enable_reels"]
            except (ImportError, ModuleNotFoundError):
                pass

            # Junban: the same shape as Reels — the toggle plus whichever of the module's own
            # tunables the user already has, written only when the module imports so a build
            # without it never gains those keys. The carry-through matters because the panel writes
            # junban_deck / junban_scope itself and this dict is rebuilt from scratch on every save.
            try:
                import modules.junban as _junban
                settings["enable_junban"] = self.var_enable_junban.get()
                carried += [k for k in _junban.SETTINGS_DEFAULTS
                            if k != "enable_junban" and k not in JUNBAN_AS_WRITTEN]
            except (ImportError, ModuleNotFoundError):
                pass
            carried += ["anki_sync_decks", "anki_sync_fields", "anki_sync_include_suspended"]
            # Connect's settings (P1.3's mine path, P2.1's switch and placing rules): no control here yet (P2.x / P3.1).
            # Carried only as the file holds them — a save never drops one the user set, and never writes a default
            # into a settings.json that lacks it (or one that can't be read)
            as_written = ["connect_mine_words", "connect_send_grammar", "connect_anki_miner_path",
                          "connect_anki_miner_profile", "connect_open_anki", "connect_enabled", "placing_rules",
                          # the sync rule's minute (E1.1 04 §3, 順's "Sync AnkiWeb") and Junban's as-written keys
                          "anki_sync_delay_min", *JUNBAN_AS_WRITTEN]

            def build():
                # Keys that OTHER windows write (Junban's deck, Reels/Koe tunables, the Anki window's
                # decks and fields) are carried through from DISK, not from `cur`: `cur` is this
                # dashboard's snapshot from its own last load/save, so carrying from it silently
                # reverted — or dropped — whatever a panel had saved since. Read when the file is
                # written, inside the lock, so a panel's save just before is carried too.
                try:
                    panel = settings_manager.load_settings() or cur
                except Exception:
                    panel = cur
                out = dict(settings)
                for key in carried:
                    if key in panel:
                        out[key] = panel[key]
                carry_as_written(out, as_written)
                # The Anki window owns these (core keys, so always written). The address is the one every
                # Anki caller reads (`anki_connect.address`), so a hand-edited 2.x `junban_url` carries over
                # here and the file then holds one address.
                from app import anki_connect
                out["anki_connect_url"] = anki_connect.address(panel)
                return out

            writer = getattr(self, "_settings_writer", None)
            if isinstance(writer, settings_manager.SettingsWriter) and not os.environ.get("SURASURA_NO_UI_TIMERS"):
                writer.submit(build)            # written on its worker; the journey check follows (_on_settings_saved)
                self._current_settings = {**cur, **settings}
            else:
                built = build()
                settings_manager.save_settings(built)
                self._current_settings = built
                # An analysis setting may have changed what Generate would compute — re-check the button.
                self._schedule_journey_state()

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

    def open_parsing_guide(self):
        try:
            webbrowser.open("https://github.com/SonicSandbox/surasura/blob/main/docs/How%20Parsing%20Works.md")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open the parsing guide: {e}")
            
    SETTINGS_WAIT_LINE = "Saving your settings waits for another Surasura program…"

    def _on_settings_saved(self):
        """The settings writer wrote: the journey check follows, and its waiting line (if shown) goes."""
        if self.status_var.get() == self.SETTINGS_WAIT_LINE:
            self.status_var.set("Ready")
        self._schedule_journey_state()

    CLI_EVENTS_EVERY = 3000     # ms between looks at the command line's events file (a stat; the read is a worker's)

    def _watch_cli_events(self):
        """Every few seconds: a stat of the command line's events file on this thread; when it changed, the new lines
        are read on a worker and the newest failure lands in the bottom bar (`_show_cli_event`). Never a box."""
        try:
            self._check_cli_events()
        finally:
            try:
                self.root.after(self.CLI_EVENTS_EVERY, self._watch_cli_events)
            except Exception:
                pass

    def _check_cli_events(self):
        reader = getattr(self, "_cli_events", None)
        if reader is None or self._cli_events_reading or not reader.changed():
            return
        self._cli_events_reading = True

        def work():
            try:
                event = reader.newest_to_show()
            except Exception:
                event = None
            self.gui_queue.put(lambda: self._show_cli_event(event))

        threading.Thread(target=work, daemon=True).start()

    def _show_cli_event(self, event):
        self._cli_events_reading = False
        if event is None:
            return
        from app.cli import events as cli_events
        self.status_var.set(cli_events.plain(event))

    def _flush_settings(self, timeout=10.0):
        """Wait until the settings writer has written what it holds: a child process or a check reads settings.json
        from disk. On a worker, or once the window is gone — never on the window's thread while it is up."""
        writer = getattr(self, "_settings_writer", None)
        if isinstance(writer, settings_manager.SettingsWriter):
            writer.flush(timeout)
        settings_manager.flush_keys(timeout)        # the other windows' saves that met a held lock

    def run_command_async(self, cmd, desc, capture_output=False, show_spinner=False, on_complete=None,
                          clear_log=True, on_exit=None, extra_env=None):
        """Runs a command with optional output redirection to the terminal.

        on_complete: optional zero-arg callable run on the GUI thread after the process exits
        (e.g. refreshing the band preview once a new analysis has written its token index).
        clear_log: False keeps what the log already shows (the automatic Generate appends to it).
        extra_env: variables for this command's process only (the analyzer's wait for `results`).
        on_exit: like on_complete, but run however the command ends — also when it could not be
        started at all (Generate's "one is running" must never stick).
        Whenever a command ends, an automatic Generate waiting for it gets its chance
        (_maybe_auto_generate).
        While an update waits for Surasura's programs (K75) nothing new starts: the command is kept and starts if the
        update is cancelled."""
        if updater.defer_child(lambda: self.run_command_async(cmd, desc, capture_output, show_spinner, on_complete,
                                                              clear_log, on_exit, extra_env)):
            self.status_var.set(f"{desc} will start if the update is cancelled.")
            return
        
        # UI updates must be queued
        def _start_loading():
            self.status_var.set(f"Running {desc}...")
            
            # Show spinner only if requested
            if show_spinner and self.spinner:
                self.spinner.pack(fill=tk.X, pady=(5, 0))
                self.spinner.start(10)

            # Clear terminal only if it exists
            if capture_output and self.terminal and clear_log:
                self.terminal.config(state=tk.NORMAL)
                self.terminal.delete(1.0, tk.END)
                self.terminal.config(state=tk.DISABLED)
        
        self.gui_queue.put(_start_loading)

        def task():
            self._flush_settings()          # every child reads settings.json: the newest choice first
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
                'indexer.py': 'index',
                'sentence_corpus.py': 'sentence_corpus'
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
                env.update(extra_env or {})
                
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
                
                # Register process for coordinated shutdown (and named for an update's wait, K75)
                process.surasura_desc = desc
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
                if on_exit:
                    self.gui_queue.put(on_exit)
                # An automatic Generate held back while this ran (the Content Manager, an importer, the
                # indexer, a Generate) can go now. It does nothing unless one is waiting.
                self.gui_queue.put(self._maybe_auto_generate)
                self.gui_queue.put(self._replan_after_child)     # the fast re-plan's preview: catch up, its Generate
                    
        threading.Thread(target=task, daemon=True).start()

    def on_closing(self):
        """Coordinated shutdown: terminate all active sub-processes"""
        if self._replan_finishing():
            return                      # the fast re-plan's re-order or sync finishes first; this runs again after
        job = getattr(self, "_update_job", None)
        if job is not None:
            self._cancel_update(job, start_held=False)   # closing while an update waits: nothing armed, nothing started
        # The speech helper is a daemon thread, so it would die with the process anyway — but
        # closing it here releases the port immediately, so relaunching the app doesn't have to
        # fall through to the next one.
        try:
            import modules.koe as koe
            koe.stop_server()
        except Exception:
            pass
        if self.active_processes:
            self.status_var.set("Closing sub-windows...")
            for proc in self.active_processes:
                try:
                    if proc.poll() is None: # Still running
                        proc.terminate()
                except Exception:
                    pass
        self._closing_event.set()
        self.root.destroy()
        # What the settings writer still holds is written before the process ends (the window is gone: nothing waits).
        self._flush_settings(timeout=10.0)
        # Connect's preview on: what arrived while the window was open was seen here — never named at the next start
        if (getattr(self, "_current_settings", None) or {}).get("connect_enabled"):
            try:
                from app.connect import notice
                notice.at_close(self.var_language.get() or "ja")
            except Exception as e:
                print(f"Arrivals notice at close: {e}")
        # This window's own store handles closed first, through the store's close (§6.12: never at the process's
        # end, where a plain close that is the last checkpoints outside the write lock)
        self._close_library_handles()
        # The library store's close trigger (Library_Store_Spec §6.7): in-process, now that no window is left to
        # freeze — the copy brought up to date for each language with something to do. Never waits for a helper.
        try:
            from app import library_store
            for lang in ("ja", "zh"):
                try:
                    library_store.maintain_at_close(lang)
                except Exception as e:
                    print(f"Library store ({lang}) at close: {e}")
        except Exception:
            pass

    def run_migaku_importer(self):
        self.run_command_async(['migaku_db_importer_gui.py', '--language', self.var_language.get()], "Migaku Importer")

    def run_jiten_importer(self):
        self.run_command_async(['jiten_db_importer_gui.py', '--language', self.var_language.get()], "Jiten Sync")

    def run_anki_importer(self):
        """The offline .apkg importer (a subprocess — it loads the tokenizer)."""
        self.run_command_async(['anki_db_importer_gui.py', '--language', self.var_language.get()], "Anki Known Words")

    def open_anki_sync(self):
        """The Anki Known Words window — in-process, since syncing needs no tokenizer."""
        try:
            from app.anki_sync_gui import open_anki_sync
        except Exception as e:
            print(f"Error loading Anki Known Words: {e}")
            self.run_anki_importer()
            return
        open_anki_sync(self)

    def _maybe_anki_sync(self, force=False):
        """Background known-words sync from a running Anki. Silent when Anki is closed.

        Throttled to once per 5 minutes: FocusIn fires for every child widget, so a debounce of a
        couple of seconds (the indexer's) would still sync on nearly every click. Runs on a daemon
        thread — a closed localhost port can take ~2 s to refuse on Windows.
        """
        if not self.var_anki_sync_auto.get() or os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return
        if self.__dict__.get("_connect_looking"):
            return      # Connect's session look is running: it reads your known words once its sync is in (Q4-1)
        import time
        now = time.monotonic()
        if not force and now - self._last_anki_sync < 300:
            return
        lang = self.var_language.get()
        s = getattr(self, "_current_settings", {}) or {}
        try:
            s = settings_manager.load_settings() or s
        except Exception:
            pass
        # The gates every sync shares (`anki_sync.may_sync`: the test switch, decks chosen, and the FIRST sync being
        # the user's own "Sync now"); the 5-minute limit is this window's own count, above.
        try:
            from app import anki_sync
            if anki_sync.may_sync(lang, s, throttle=False) is not None:
                return
        except Exception:
            return
        decks = list((s.get("anki_sync_decks") or {}).get(lang) or [])
        if updater.children_held():
            return                      # an update waits (K75): no Anki write may begin
        if not self._anki_sync_lock.acquire(blocking=False):
            return                      # a sync is already running (here or in the Anki window)
        self._last_anki_sync = now
        fields = list((s.get("anki_sync_fields") or {}).get(lang) or [])
        suspended = bool(s.get("anki_sync_include_suspended", False))

        def work():
            result = None
            try:
                from app import anki_connect, anki_sync
                url = anki_connect.address(s)
                if anki_connect.probe(url).get("ok"):
                    result = anki_sync.sync(lang, url, decks, fields, include_suspended=suspended)
                    # The same decks' new cards, for the report's backlog marks (read-only).
                    anki_sync.sync_backlog(lang, url, decks, fields)
            except Exception as e:
                print(f"Anki sync skipped: {e}")
            finally:
                self._anki_sync_lock.release()
                self.gui_queue.put(lambda: self._anki_spinner(False))
                if result is not None:
                    # Words for `lang`, the language this sync read — the window may be on another by now.
                    self.gui_queue.put(lambda: self._on_anki_sync_result(result, auto=True, language=lang))

        self._anki_spinner(True)
        threading.Thread(target=work, daemon=True).start()

    def _maybe_backlog_sync(self):
        """Generate's own read of the Anki backlog (Junban_Backlog_Spec WP-B7): the new cards waiting
        in the decks chosen with the Anki button, into User Files/<lang>/anki_backlog.json.

        In the background and never waited for — the report is rendered at the END of the analysis,
        long after a read from a running Anki (well under a second) is done — so Generate is never
        slower for it. Nothing at all without decks chosen; silent when Anki is closed (a closed port
        can take ~2 s to refuse, on this thread, not the window's).
        """
        if not self.var_anki_backlog_on_generate.get() or os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return
        lang = self.var_language.get()
        try:
            s = settings_manager.load_settings() or {}
        except Exception:
            return
        decks = list((s.get("anki_sync_decks") or {}).get(lang) or [])
        if not decks:
            return
        fields = list((s.get("anki_sync_fields") or {}).get(lang) or [])

        def work():
            try:
                from app import anki_connect, anki_sync
                url = anki_connect.address(s)
                if anki_connect.probe(url).get("ok"):
                    anki_sync.sync_backlog(lang, url, decks, fields)
            except Exception as e:
                print(f"Anki backlog skipped: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _maybe_junban_auto(self, force=False):
        """Junban's automatic reorder — a test option, `junban_auto_reorder` in settings.json.

        After a Generate (`force`) and when the window comes back into focus (at most every 5
        minutes, like the Anki sync), on a daemon thread with a spinner on the 順 button. Every
        decision about whether to write lives in the module (`modules/junban/auto.py`: `blocked` —
        the test switch, the module off, an update waiting, a 順 window open — and the reorder's own
        guards); this only schedules it.
        """
        import time
        host = self.__dict__.get("_replan_host")
        if host is not None and force:
            host.after_generate()       # the fast re-plan's preview re-orders from the new plan (E1.1 04 §3)
        now = time.monotonic()
        if not force and now - self._last_junban_auto < 300:
            return
        try:
            settings = dict(settings_manager.load_settings() or {})
            from modules.junban import auto
        except Exception:
            return
        settings["target_language"] = self.var_language.get()
        settings["enable_junban"] = bool(self.var_enable_junban.get())     # the switch as shown, saved or not yet
        if host is not None and self._replan_runs(settings):
            settings["junban_auto_reorder"] = False     # the preview's host re-orders; the Backfill step stays
        if not auto.enabled(settings) or auto.blocked(settings, window=False):
            return
        window = getattr(self, "junban_window", None)
        try:
            if window is not None and window.winfo_exists():
                return                  # this window's own 順 panel, before its lock is even taken
        except Exception:
            pass
        if not self._junban_auto_lock.acquire(blocking=False):
            return
        self._last_junban_auto = now
        # Read on this thread (the widgets), asked on the worker's: is the list up to date — the
        # Generate button's own question, so a reorder never follows a list that is behind.
        args, language = self._analyzer_args(), self.var_language.get()

        def work():
            message = ""
            try:
                if auto.window_open():          # a lock look: on this worker, never the window's thread
                    return
                self._flush_settings()
                message = auto.run_quietly(settings, list_current=journey_is_current(args, language))
            finally:
                self._junban_auto_lock.release()
                self.gui_queue.put(lambda: self._junban_spinner(False))
                if message:
                    self.gui_queue.put(lambda: self._on_junban_auto(message))

        self._junban_spinner(True)
        threading.Thread(target=work, daemon=True).start()

    # --- the fast re-plan's preview (E1.1 04 §3; app/replan_preview.py) --------------------------------------------- #
    # With 順's "Re-order Anki as I move content (preview)" on, this window catches up — a re-order the Content
    # Manager left owed, cards Anki holds that no re-order placed — at start and on focus, re-orders after every
    # Generate (the host's helper process, 順 spinning), and runs the automatic Generate the preview asks for (moves made,
    # switched on, the plan can't serve a move): quietly, shown working, never with the Content Manager open, never two.
    # Off (the default): no host, 2.5's window.

    def _replan_start(self):
        """Start, stop or re-aim the host (startup, 順's switch, the language): one per language."""
        try:
            from app import replan_preview
            settings = dict(settings_manager.load_settings() or {})
            settings["enable_junban"] = bool(self.var_enable_junban.get())
            language = self.var_language.get() or "ja"
            on = replan_preview.is_on(settings, language)
            if settings.get(replan_preview.SWITCH) is not True and not settings.get("connect_enabled"):
                # switched off: a pending sync is let go (Anki's close carries it) — unless Connect's preview, whose
                # verbs leave one for Connect to send, is on (P2.3)
                from app import anki_sync_rule
                anki_sync_rule.drop_pending()
        except Exception:
            on, language = False, self.var_language.get() or "ja"
        host = self.__dict__.get("_replan_host")
        if host is not None and (not on or host.language != language):
            host.stop()
            host = self._replan_host = None
        if on and host is None and self.__dict__.get("_update_job") is not None:
            return                                     # an update waits: started again when it ends (pass 5 #1)
        if on and host is None:
            host = self._replan_host = replan_preview.open_host(
                language, say=lambda line: self.gui_queue.put(lambda: self._replan_said(line)),
                working=lambda busy: self.gui_queue.put(lambda: self._junban_spinner(busy)),
                generate=lambda reason: self.gui_queue.put(lambda: self._want_replan_generate(reason)))
        if host is not None:
            self._replan_focus()

    def _replan_stop_for_update(self):
        """"Update now": the preview's helper is a Surasura process the update would wait for, and this window's hold
        isn't its own (E3.1 pass 4 #1) — stopped now (a job in hand goes on for at most CLOSE_WAIT_S; pass 5 #3), started
        again by a cancel once the update's lock is gone."""
        host = self.__dict__.get("_replan_host")
        if host is not None:
            host.stop()
            self._replan_host = None

    def replan_preview_changed(self):
        """順's window: its "Re-order Anki as I move content" switch (or its sync choice) changed."""
        self._replan_start()

    @staticmethod
    def _replan_runs(settings):
        """The preview's host re-orders for these settings (else 2.5's automatic reorder keeps its own switch)."""
        try:
            from app import replan_preview
            return (replan_preview.is_on(settings, settings.get("target_language"))
                    and replan_preview.unavailable(settings) is None)
        except Exception:
            return False

    def _child_running(self):
        try:
            return any(proc.poll() is None for proc in list(self.active_processes))
        except Exception:
            return True

    def _replan_focus(self):
        """The catch-up (04 §3): on focus and at start — not while a program of this window runs (the Content
        Manager re-orders itself; a Generate's end re-orders)."""
        host = self.__dict__.get("_replan_host")
        if host is not None and not self._child_running():
            host.catch_up()

    def _replan_after_child(self):
        """A program of this window ended (the Content Manager closing): catch up, and run a Generate that waited."""
        self._replan_focus()
        self._maybe_replan_generate()

    def _replan_said(self, line):
        """The host's line, in the bottom bar for a few seconds (the Content Manager shows its own)."""
        if not line:
            return
        self.status_var.set(line)
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self.root.after(6000, lambda: self.status_var.get() == line and self.status_var.set("Ready"))

    def _want_replan_generate(self, reason):
        self._replan_generate_reason = reason
        self._maybe_replan_generate()

    def _maybe_replan_generate(self):
        """The preview's automatic Generate (04 §3, ✅ G1.5-2 / G1.5-5), when nothing holds it back: never with the
        Content Manager (or any program of this window) open, never during a Generate or an update, never for the
        other language. Quiet — the report written, not opened — and shown working: the check mark's spot spins,
        the bottom bar says so. A request held back waits for focus or the next program's end."""
        reason = self.__dict__.get("_replan_generate_reason")
        host = self.__dict__.get("_replan_host")
        if not reason or host is None or host.language != self.var_language.get():
            return False
        if self._generate_running is not None or updater.children_held() or self._child_running():
            return False
        if not self._library_has_content():
            return False
        self._replan_generate_reason = None
        self.log_to_terminal("Re-order as you move: refreshing your list (Generate) so Anki follows your moves "
                             "— the report is not opened.")
        self.status_var.set("Refreshing your list (Generate)… · Anki is re-ordered when it's done")
        self.run_analyzer(quiet=True)
        if self._generate_running == "quiet":
            self._generate_running = "automatic"
            self._replan_generating = True
            self._journey_spinner(True)                # the check mark's spot spins until it ends
        return True

    def _replan_finishing(self):
        """Closing (04 §2.5): a re-order running or a sync pending finishes first — at most CLOSE_WAIT_S, the bottom
        bar saying so — then `on_closing` runs again. False when nothing waits (closing goes on at once)."""
        host = self.__dict__.get("_replan_host")
        if host is None:
            return False
        import time
        from app import replan_preview
        deadline = self.__dict__.get("_replan_closing_at")
        if deadline is None:
            host.close()
            deadline = self._replan_closing_at = time.monotonic() + replan_preview.CLOSE_WAIT_S
            self.status_var.set("Finishing the re-order in Anki…")
        if host.busy() and time.monotonic() < deadline and not os.environ.get("SURASURA_NO_UI_TIMERS"):
            self.root.after(100, self.on_closing)
            return True
        host.stop()
        self._replan_host = None
        return False

    def _tell_junban_list_changed(self):
        """After any Generate: an open 順 window that was waiting for an up-to-date list (its
        "Generate & preview", Junban_Backlog_Spec §16.9) previews again. The window decides."""
        window = getattr(self, "junban_window", None)
        try:
            if window is not None and window.winfo_exists():
                window.on_list_updated()
        except Exception:
            pass

    def _maybe_auto_generate(self):
        """The quiet Generate, when the Anki sync brought in known words — returns True if it started.

        The user's choices (2026-09-23): only for new known words from Anki, never for new episodes
        (those are theirs to order first — the sync alone sets `_auto_generate_pending`); the report
        is written, not opened; at most every 10 minutes; never while a Generate, an import, the
        indexer or the Content Manager is running (each is a child process of this window). A
        pending one waits — the same words will not arrive a second time — and is retried when the
        window regains focus, when any child process ends (`run_command_async`), and — when the
        10-minute limit is all that holds it back — by an alarm for the moment the limit is up.
        Anki's words belong to the language they came for: Japanese words wait while Chinese is open.
        (The alarm used to run a Chinese Generate then, which cleared them without generating them.)
        """
        pending = self._auto_generate_pending
        if not pending or not self.var_anki_auto_generate.get():
            return False
        if os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return False
        if pending is not True and pending != self.var_language.get():
            return False                # for the other language: it runs once that one is open again
        if self._generate_running is not None:
            return False                # a Generate is running (or starting): its end asks again
        if updater.children_held():
            return False                # an update waits (K75): asked again if it is cancelled
        try:
            if any(proc.poll() is None for proc in list(self.active_processes)):
                return False
        except Exception:
            return False
        if not self._library_has_content():
            return False
        import math
        import time
        now = time.monotonic()
        wait = 600 - (now - self._last_auto_generate)
        if wait > 0:
            # Only the limit is in the way: one alarm for when it is up, which asks all of this again.
            # Replaced, never stacked; not scheduled under test (testing.md §5.4).
            if not os.environ.get("SURASURA_NO_UI_TIMERS"):
                if self._auto_generate_job is not None:
                    try:
                        self.root.after_cancel(self._auto_generate_job)
                    except Exception:
                        pass
                self._auto_generate_job = self.root.after(int(math.ceil(wait * 1000)),
                                                          self._auto_generate_alarm)
            return False
        self._last_auto_generate = now
        self.log_to_terminal("Anki brought in words you know now — generating in the background; "
                             "the report is not opened.")
        self.run_analyzer(quiet=True)
        if self._generate_running == "quiet":          # it started, and it is Anki's own:
            self._generate_running = "automatic"
            self._journey_spinner(True)                # the check mark's spot spins until it ends
        return True

    def _auto_generate_alarm(self):
        """The 10-minute limit is up: a Generate that waited only for it runs now, unless something
        else holds it back by then (`_maybe_auto_generate` asks everything again)."""
        self._auto_generate_job = None
        self._maybe_auto_generate()

    def _schedule_journey_state(self):
        """Check, shortly, whether the journey is up to date. Debounced: FocusIn fires for every child
        widget, and several triggers can arrive at once."""
        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        if self._journey_state_job is not None:
            try:
                self.root.after_cancel(self._journey_state_job)
            except Exception:
                pass
        self._journey_state_job = self.root.after(600, self._refresh_journey_state)

    def _refresh_journey_state(self):
        """Ask the analyzer's own signature, off the GUI thread (it stats every library file), whether
        Generate would compute anything new — and show the answer on the Generate button.

        Answers land in order: each check has a generation, like the band preview's `_preview_gen`, and
        one that a newer check has overtaken is dropped — a check asked during a Generate must never
        land after the one asked when it finished."""
        self._journey_state_job = None
        self._journey_gen += 1
        gen = self._journey_gen
        if not hasattr(self, "btn_journey") or not self._library_has_content():
            self._set_journey_state(None)
            return
        args, language = self._analyzer_args(), self.var_language.get()

        def work():
            self._flush_settings()          # the check reads settings.json
            state = journey_is_current(args, language)
            self.gui_queue.put(lambda: gen == self._journey_gen and self._set_journey_state(state))

        threading.Thread(target=work, daemon=True).start()

    def _set_journey_state(self, current):
        """`False` — a thin Surasura-blue border: Generate has something new to compute. `True` — no
        border, a quiet check mark on the button's right edge. `None` (cannot tell, no content) —
        neither. The button itself never changes size."""
        self._journey_state = current
        try:
            color = SURASURA_BLUE if current is False else BG_COLOR
            self.journey_border.config(highlightbackground=color, highlightcolor=color)
            if self._generate_running == "automatic":
                return                  # its spinner keeps the spot; the check after it fills it
            if current is True:
                self.lbl_journey_state.place(in_=self.btn_journey, relx=1.0, rely=0.5, anchor="e", x=-10)
                self.lbl_journey_state.lift()
            else:
                self.lbl_journey_state.place_forget()
        except Exception:
            pass

    def _journey_check_tip(self):
        """The check mark's tooltip — or, while the automatic Generate spins in its place, what runs."""
        if self._generate_running == "automatic":
            return ("Generating automatically — your list catches up with your moves (Re-order as you move)."
                    if self.__dict__.get("_replan_generating") else
                    "Generating automatically — Anki brought in known words.")
        return "Up to date — nothing has changed since your last Generate."

    def _journey_spinner(self, on):
        """The Anki button's spinner, in the check mark's spot on Generate, while the automatic Generate
        runs. The spot sits on the button's right edge, so the button never changes size. Off, the spot
        is left empty: the up-to-date check that follows every Generate puts the ✓ back, or doesn't."""
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        if self._journey_spin_job is not None:
            try:
                self.root.after_cancel(self._journey_spin_job)
            except Exception:
                pass
            self._journey_spin_job = None
        try:
            if not on:
                self.lbl_journey_state.config(text="✓")
                self.lbl_journey_state.place_forget()
                return
            self.lbl_journey_state.place(in_=self.btn_journey, relx=1.0, rely=0.5, anchor="e", x=-10)
            self.lbl_journey_state.lift()
        except Exception:
            return

        def tick(i=0):
            self.lbl_journey_state.config(text=frames[i % len(frames)])
            self._journey_spin_job = self.root.after(100, tick, i + 1)
        tick()

    def _light_journey_check(self, lit, on_check=False):
        """The check follows the button's hover colours. With the pointer on the check itself, the
        button stays lit, as if the pointer were still on it."""
        try:
            self.lbl_journey_state.config(bg=ACCENT_COLOR if lit else SURFACE_COLOR,
                                          fg=BG_COLOR if lit else CHECK_GRAY)
            if on_check:
                self.btn_journey.state(["active"] if lit else ["!active"])
        except Exception:
            pass

    def _on_junban_auto(self, message):
        """One line in the log — and never the same one twice running, so a reason to wait ("choose
        one deck") is said once rather than every five minutes."""
        if message == self._last_junban_auto_message:
            return
        self._last_junban_auto_message = message
        self.log_to_terminal(message)
        if message.startswith("順 (automatic)"):
            self.status_var.set("✓ 順: new cards reordered")
            self.root.after(6000, lambda: self.status_var.get() == "✓ 順: new cards reordered"
                            and self.status_var.set("Ready"))

    def _junban_spinner(self, on):
        """The Anki button's spinner, on the 順 button, while the automatic reorder runs."""
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        if self._junban_spin_job is not None:
            try:
                self.root.after_cancel(self._junban_spin_job)
            except Exception:
                pass
            self._junban_spin_job = None
        if self.btn_junban is None:
            return
        if not on:
            self.btn_junban.config(text="順", width=3)
            return

        def tick(i=0):
            self.btn_junban.config(text=f"順{frames[i % len(frames)]}", width=4)
            self._junban_spin_job = self.root.after(100, tick, i + 1)
        tick()

    def _anki_spinner(self, on):
        """A small braille spinner on the Anki button while a background sync runs."""
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        if self._anki_spin_job is not None:
            try:
                self.root.after_cancel(self._anki_spin_job)
            except Exception:
                pass
            self._anki_spin_job = None
        if not on:
            self.btn_anki.config(text="Anki")
            return

        def tick(i=0):
            self.btn_anki.config(text=f"Anki {frames[i % len(frames)]}")
            self._anki_spin_job = self.root.after(100, tick, i + 1)
        tick()

    def _on_anki_sync_result(self, result, auto=False, language=None):
        """After any sync: say so briefly, and refresh the commonness preview straight away (it
        would otherwise wait for the next FocusIn to notice the known words changed). `language` is
        the one the sync read — the background sync's, or the Anki window's own; None, the one open."""
        if result.error:
            if auto:
                print(f"Anki sync: {result.error}")
            return
        if result.added > 0 or result.mode in ("replace", "restore"):
            if auto:
                message = f"✓ Anki: +{result.added:,} known word{'s' if result.added != 1 else ''}"
                self.status_var.set(message)
                self.root.after(6000, lambda: self.status_var.get() == message and self.status_var.set("Ready"))
            # The known words changed, so the list is out of date. With "Generate when Anki adds known
            # words" on, a quiet Generate runs now — it re-reads the store itself, so no separate
            # re-index — or as soon as nothing else is running (_maybe_auto_generate). Pending for the
            # language the words came for, so a Generate of another one never uses them up.
            if self.var_anki_auto_generate.get():
                self._auto_generate_pending = language or self.var_language.get()
            if not self._maybe_auto_generate():
                self._maybe_launch_indexer(force=True)
            self._schedule_journey_state()
        win = getattr(self, "anki_sync_window", None)
        if auto and win is not None:
            try:
                if win.winfo_exists():
                    win.refresh_known()
            except Exception:
                pass

    def run_content_importer(self):
        self.run_command_async(['content_importer_gui.py', '--language', self.var_language.get()], "Content Importer")

    def run_file_importer(self):
        self.run_command_async(['epub_importer.py', '--language', self.var_language.get()], "File Importer")

    def run_frequency_list_manager(self):
        self.run_command_async(['frequency_list_gui.py', '--language', self.var_language.get()], "Frequency List Manager")

    def run_analyzer(self, quiet=False):
        """Generate. `quiet` is the automatic run after the Anki sync brought in known words
        (`_maybe_auto_generate`): the report is written, not opened; the log is not cleared; and the
        reopen-only fast path below is skipped, since all it does is open the report.

        Never two at once — both would write results/ and the report, and one could read the other's
        half-written CSV. A press while a quiet one runs waits for it, then opens the report; a press
        while a pressed one runs starts nothing and says so; a quiet request while any runs starts
        nothing (the running one tells an open 順 window when it's done)."""
        if self._generate_running is not None:
            if self._generate_running == "checking":
                return                          # this press's own check is still answering
            if not quiet:
                if self._generate_running != "manual":
                    self._open_report_when_generated = True     # _on_generate_exit opens it
                    if self.spinner:
                        self.spinner.pack(fill=tk.X, pady=(5, 0))
                        self.spinner.start(10)
                self.status_var.set("Already generating — the report opens when it's done.")
            return
        from app.path_utils import ensure_data_setup
        ensure_data_setup(self.var_language.get())
        self._maybe_backlog_sync()          # in the background; see its docstring

        # This run includes whatever the Anki sync brought in — for its own language: Japanese words
        # stay pending through a Chinese Generate, for the Japanese one they are waiting for.
        if self._auto_generate_pending is True or self._auto_generate_pending == self.var_language.get():
            self._auto_generate_pending = False
        args = self._analyzer_args()

        # --- Fast no-change path: reopen the existing report WITHOUT spawning the analyzer ---
        # If nothing analysis-affecting changed since the last run AND presentation is unchanged AND
        # the report exists, just reopen it in-process. This skips the whole analyzer subprocess
        # (a ~1-2s cold-start in a frozen build). It uses the analyzer's OWN signature functions, so
        # the GUI's decision can never diverge from what the analyzer would decide. Any hiccup falls
        # through to the normal subprocess run — the fast path is a pure optimization, never required.
        if quiet:
            args.append('--no-open')     # written, not opened — and no fast path to open it
            self._start_analyzer(args, quiet)
            return
        # Whether the report still holds is asked on a worker (Library_Store_Spec §7, A10 / A12): the check syncs
        # the library with its folders and stats every file, never on this thread. The press goes on from the answer.
        self._generate_running = "checking"
        self._run_on_worker(lambda: (self._flush_settings(), self._report_reusable(args))[1],    # the file, then the check
                            lambda reusable: self._generate_checked(args, reusable))

    def _run_on_worker(self, work, then):
        """`work()` on a worker thread, then `then(result)` on this one (through gui_queue). Headless or under test
        (no UI timers drain the queue) both run here, at once."""
        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            then(work())
            return

        def run():
            try:
                result = work()
            except Exception:
                result = None
            self.gui_queue.put(lambda: then(result))
        threading.Thread(target=run, daemon=True).start()

    def _generate_checked(self, args, reusable):
        """Generate's press, on this thread again: reopen the report when the worker found it current, else run
        the analyzer."""
        self._generate_running = None
        if reusable is not None and self._open_existing_report(reusable):
            self._maybe_junban_auto(force=True)
            self._schedule_journey_state()
            self._tell_junban_list_changed()
            return
        self._start_analyzer(args, quiet=False)

    def _start_analyzer(self, args, quiet):
        """Start the analyzer, once no other program's Generate holds `results` (P0.3 04 §2): a headless one
        (`surasura-cli generate`) is waited for on a worker, with a line in the bottom bar, never a box; this thread
        never waits. The analyzer takes the lock itself, so the two can never write results/ together."""
        self._generate_running = "quiet" if quiet else "manual"

        def wait_for_results():
            from app import locks
            try:
                if locks.read_holder("results") is None and locks.unopenable("results"):
                    return True             # no program to wait for: the analyzer's own take says why (its log)
                with locks.take("results", "Generate (waiting)", wait=None, cancel=self._closing_event,
                                on_wait=lambda _holder: self.gui_queue.put(
                                    lambda: self.status_var.set("Waiting for a background Generate…"))):
                    pass
            except locks.Cancelled:
                return False                # the window closed while it waited: nothing starts
            except Exception:
                pass                        # the lock can't be read here: the analyzer decides
            return True

        def start():
            self.run_command_async(args, "Analyzer (automatic)" if quiet else "Analyzer",
                                   capture_output=True, show_spinner=not quiet, clear_log=not quiet,
                                   on_complete=lambda: (self._refresh_band_preview(force=True),
                                                        self._maybe_junban_auto(force=True),
                                                        self._schedule_journey_state(),
                                                        self._tell_junban_list_changed()),
                                   on_exit=self._on_generate_exit,
                                   # It has waited its turn already; started in the moment another program's
                                   # Generate also starts, it waits for that one (closing the window ends it).
                                   extra_env={"SURASURA_RESULTS_WAIT": "forever"})

        def go():
            if not wait_for_results():
                return
            self.gui_queue.put(start)

        if os.environ.get("SURASURA_NO_UI_TIMERS"):
            # Under test nothing drains the queue: a free lock starts the analyzer here, at once; a held one is
            # waited for on a worker, as in use.
            from app import locks
            try:
                with locks.take("results", "Generate (waiting)"):
                    pass
            except locks.Busy:
                threading.Thread(target=go, daemon=True).start()
                return
            except Exception:
                pass
            start()
            return
        threading.Thread(target=go, daemon=True).start()

    def _on_generate_exit(self):
        """However a Generate ended — finished, failed, or never started — the next one may run. The
        automatic one's spinner leaves the check mark's spot, the up-to-date check answers (✓, or the
        blue border if it failed), and a press that waited for a quiet one is honoured: the normal
        Generate, which reopens the report at once when the journey is up to date."""
        if self._generate_running == "automatic":
            self._journey_spinner(False)
        self._generate_running = None
        self._replan_generating = False
        self._schedule_journey_state()
        if self._open_report_when_generated:
            self._open_report_when_generated = False
            self.run_analyzer()

    def _analyzer_args(self):
        """The analyzer's argv as Generate passes it, from the widgets — read on the GUI thread. One builder for the
        window and the command line (`app/run_args.py`), so their runs hash alike."""
        from app import run_args
        return run_args.analyzer_args(self._run_settings(), self.var_language.get())

    def _run_settings(self):
        """The widgets Generate reads, in settings.json's shape (what `run_args.analyzer_args` takes)."""
        return {
            "exclude_single": self.var_exclude_single.get(),
            "strategy": self.var_strategy.get(),
            "target_coverage": self.var_target_coverage.get(),
            "target_language": self.var_language.get(),
            "zh_script": self.var_zh_script.get(),
            "ensure_audio_example": self.var_ensure_audio.get(),
            "only_i_plus_one": self.var_only_i_plus_one.get(),
            "logic": {"context": {"min_chars": self.var_context_min_chars.get(),
                                  "preferred_max_chars": self.var_context_max_chars.get(),
                                  "max_contexts": self.var_max_contexts.get()}},
            "theme": self.combo_theme.get(),
            "open_app_mode": self.var_open_app_mode.get(),
            "zen_limit": self.var_zen_limit.get(),
        }

    def _try_open_existing_report(self, args):
        """Return True and reopen the existing report if a full analysis is provably unnecessary (the check and
        the reopen together; Generate's press asks `_report_reusable` on a worker instead)."""
        reusable = self._report_reusable(args)
        return reusable is not None and self._open_existing_report(reusable)

    def _open_existing_report(self, a):
        """Reopen the report `_report_reusable` found current; True when it opened."""
        try:
            try:
                from app import static_html_generator
            except ImportError:
                import static_html_generator
            static_html_generator.open_report(app_mode=a.app_mode)
            self._refresh_band_preview()   # inputs unchanged -> cache hit, no recompute
            return True
        except Exception:
            return False

    def _report_reusable(self, args):
        """The parsed analyzer args if a full analysis is provably unnecessary, else None. Safe on a worker: it
        reads no widget (`args` and the language come from the press).

        Mirrors the analyzer's own skip gate (compute_run_signature + outputs-present + render-sig),
        computed in-process so we can avoid the subprocess entirely. Conservative: only the pure
        'nothing changed, same presentation' case short-circuits; a changed theme/zen or any missing
        piece falls through so the subprocess handles the re-render/analysis as before."""
        try:
            from app import analyzer as _analyzer
            from app import token_index as _ti
            from app.path_utils import get_user_file

            a = _analyzer.parse_analysis_args(args[1:])   # args[0] is the 'analyzer.py' script name
            lang = a.language                              # from the press's args: no widget read here
            # Analysis unchanged: the analyzer's own signature AND the results stamp — results/ is
            # shared by both languages, and without the stamp a Japanese -> Chinese -> Japanese switch
            # reopened the Chinese report (see analyzer.read_run_stamp). The Generate button's border
            # asks the very same question (journey_is_current), so the two cannot disagree.
            if journey_is_current(args, lang) is not True:
                return None
            report = os.path.join(get_user_file("results"), "reading_list_static.html")
            if not os.path.exists(report):
                return None
            store = _ti.open_store(lang)
            try:
                stored_render = store.get_meta("last_render_sig")
            finally:
                store.close()

            # ...and presentation unchanged -> the existing report can be reopened as-is.
            if stored_render == _analyzer.compute_render_signature(a):   # shared with the engine
                return a
        except Exception:
            pass  # fall through to the normal subprocess run
        return None

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

    def export_sentence_dictionary(self):
        """Settings → Data & System → Export Sentence Dictionary: "Surasura Corpus (<lang>)", a Yomitan
        dictionary of up to 8 of the best sentences for every word in the library
        (app/sentence_corpus.py).

        A small dialog asks first whether to write where each sentence came from under it — off by
        default, since file names crowd the popup (each sentence's hover shows its file either way).
        The answer is remembered (`sentence_dictionary_source`)."""
        from app.analyzer import resolve_found_files
        from app.sentence_corpus import dictionary_title

        lang = self.var_language.get()
        if not resolve_found_files(lang, verbose=False):
            messagebox.showwarning("No Content", "Add content to your library first — the dictionary is "
                                                 "built from your own files.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Export Sentence Dictionary")
        dialog.geometry("420x230")
        dialog.resizable(False, False)
        dialog.configure(bg=BG_COLOR)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.bind("<Escape>", lambda e: dialog.destroy())

        wrapper = ttk.Frame(dialog, padding=20)
        wrapper.pack(fill=tk.BOTH, expand=True)
        ttk.Label(wrapper, text=dictionary_title(lang), font=('Segoe UI', 11, 'bold'),
                  foreground=TEXT_COLOR, background=BG_COLOR).pack(anchor=tk.W, pady=(0, 12))

        # The box edits a copy: Cancel / Esc leave the remembered answer as it was.
        show_source = tk.BooleanVar(value=self.var_sentence_dictionary_source.get())
        chk_source = ttk.Checkbutton(wrapper, text="Show where each sentence came from",
                                     variable=show_source)
        chk_source.pack(anchor=tk.W)
        ToolTip(chk_source, "Adds a short file name under each sentence. Off keeps the popup cleaner — "
                            "hovering a sentence still shows where it came from.")
        ttk.Label(wrapper, text="Off: hover a sentence to see it", foreground="#aaaaaa",
                  font=('Segoe UI', 8, 'italic')).pack(anchor=tk.W, padx=(22, 0))

        def _export():
            dialog.destroy()
            self.var_sentence_dictionary_source.set(show_source.get())
            self.save_settings()        # remember the choice
            self._export_sentence_dictionary(lang, show_source.get())

        buttons = ttk.Frame(wrapper)
        buttons.pack(side=tk.BOTTOM, fill=tk.X)
        btn_cancel = ttk.Button(buttons, text="Cancel", command=dialog.destroy)
        btn_cancel.pack(side=tk.RIGHT)
        ToolTip(btn_cancel, "Close without exporting.")
        btn_export = ttk.Button(buttons, text="Export", command=_export, style="Action.TButton")
        btn_export.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(btn_export, "Choose where to save the dictionary, then build it.")

    def _export_sentence_dictionary(self, lang, show_source):
        """Save dialog, then the export itself. It reads the whole library's cached sentences, so it
        runs as its own process, the way Generate does — the window stays responsive, its memory is
        returned when it ends, and its progress shows in the Processing Log. The zip only appears once
        it is complete, so a fresh file is how this side knows the run succeeded."""
        import time
        import zipfile
        from tkinter import filedialog
        from app.sentence_corpus import dictionary_title

        title = dictionary_title(lang)
        save_path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            initialfile=f"{title}.zip",
            filetypes=[("Zip Files", "*.zip")],
            title="Save Sentence Dictionary"
        )
        if not save_path:
            return
        started = time.time()

        def _done():
            try:
                made = os.path.getmtime(save_path) >= started - 2
            except OSError:
                made = False
            if not made:
                messagebox.showerror("Sentence Dictionary",
                                     "The dictionary couldn't be made — the Processing Log says why.")
                return
            try:
                with zipfile.ZipFile(save_path) as zf:
                    summary = json.loads(zf.read("index.json")).get("description", "")
            except Exception:
                summary = ""
            messagebox.showinfo(
                "Sentence Dictionary",
                f"{title} is ready.\n{summary}\n\n"
                f"In Yomitan: Settings → Dictionaries → Import, then choose:\n{save_path}\n\n"
                "Already have an older one? Delete it in Yomitan first — Yomitan won't import a second "
                "dictionary with the same name.")

        cmd = ["sentence_corpus.py", "--language", lang, "--output", save_path]
        if show_source:
            cmd.append("--show-source")
        self.run_command_async(cmd, "Sentence Dictionary", capture_output=True, show_spinner=True,
                               on_complete=_done)

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
