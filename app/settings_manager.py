import json
import os
import copy
import importlib
import threading
import time
from typing import Any, Callable, Dict, Optional
from app import locks
from app.path_utils import get_user_file, read_text

# --- SETTINGS TEMPLATE (DEFAULTS) ---
DEFAULT_SETTINGS = {
    "exclude_single": True,
    "open_app_mode": False,
    "theme": "Dark Flow",
    "strategy": "freq",
    "target_coverage": 90,
    "split_length": 3000,
    "target_language": "ja",
    # Chinese only: read the whole library as "s" (Simplified) or "t" (Traditional); "asis" leaves
    # every file's script as written. Files are never converted on disk (app/zh_script.py).
    "zh_script": "asis",
    "telemetry_enabled": True,
    "words_per_day": 5,
    "show_words_per_day": True,
    "zen_limit": 50,
    "onboarding_completed": False,
    "open_count": 0,
    "hide_satoru": True,  # This is the "internal" default
    "only_i_plus_one": False,
    "ensure_audio_example": False,
    "add_graduated_words": True,
    "auto_update_enabled": True,   # one-click in-place updates for minor releases
    "skipped_version": "",          # a version the user skipped — never offered again
    # Per-sentence source badge in the report: "off" | "icon" | "filename" | "full".
    # Presentation only — it never changes the analysis, just how each example sentence is labelled.
    "source_display": "off",
    # Word lookup button (⌕) on each report card. Presentation only — both re-render, neither
    # re-analyzes (see analyzer.compute_render_signature).
    "word_search_enabled": True,
    "word_search_category": "all",   # all | anime | liveaction | youtube
    # Sentence dictionary export (app/sentence_corpus.py): show a short file name under each
    # sentence. Off keeps the Yomitan popup clean — the file is still in each sentence's hover.
    # Export-only: never in the run signature (analyzer._NON_ANALYSIS_SETTINGS).
    "sentence_dictionary_source": False,
    # The token store's tokenizing pool (token_index.pool_size): None = sized from the CPU count and memory, 0 = one
    # process, N = N worker processes. Speed only: every file's tokens are the same either way (W1.3). Never in the run
    # signature (analyzer._NON_ANALYSIS_SETTINGS).
    "index_pool_workers": None,
    # The 3.0 window's look (Settings > App; W2.1, the window's spec 02 §2.1): its theme (app/theme.py THEMES: "hb" Blue,
    # "sky" Lighter blue, "sapphire" Sapphire) and text size ("S" / "M" / "L"). Set on the window before its first paint.
    # Never in the run signature (analyzer._NON_ANALYSIS_SETTINGS): no run or report reads them.
    "app_theme": "hb",
    "text_size": "M",
    # Surasura Connect's preview switch (P2.1; docs/agent instructions/3.0/P1.5-connect/): off until the user turns it
    # on (2.x: an opt-in preview); with it off, `register` writes nothing. `placing_rules` = {source: target}: where a
    # program's drop goes instead of waiting in New arrivals (3.0 only, the store's `arrivals_on`; ✅ Q2-3, RD-S16:
    # empty = every arrival waits). Sources: a record's producer ("hato"), "<producer>:<channel id>"; targets: wait ·
    # top · after-show · soon · goal · finished (app/connect/rules.py; the store's L2.2 05 §5.12). Read only by the
    # command line and Connect: never in a signature (analyzer._NON_ANALYSIS_SETTINGS).
    "connect_enabled": False,
    "placing_rules": {},
    # Live Anki -> known words (app/anki_sync.py). Loopback AnkiConnect only. Decks and fields are
    # per language ({"ja": [...], "zh": [...]}); copy these dicts before mutating (load_settings
    # deep-copies the defaults, but a caller holding the loaded dict shares it). Never in the run
    # signature (analyzer._NON_ANALYSIS_SETTINGS).
    "anki_connect_url": "http://127.0.0.1:8765",
    "anki_sync_auto": False,
    "anki_sync_decks": {},
    "anki_sync_fields": {},
    "anki_sync_include_suspended": False,
    # "Label backlogged Anki words" (Settings -> Experience & UI; Junban_Backlog_Spec WP-B8): Generate
    # reads the new-card backlog of those decks, in the background, when Anki is running
    # (anki_sync.sync_backlog -> User Files/<lang>/anki_backlog.json), and the report marks each word
    # a card is waiting for. Needs the decks above; without them it does nothing at all. In the
    # render signature, never the run signature.
    "anki_backlog_on_generate": True,
    # Generate on its own, quietly (the report is written, not opened), when the Anki sync brings
    # in known words. Only then — new episodes are the user's to order first. Never in the run
    # signature.
    "anki_auto_generate": False,
    # Surasura Connect's mine path (P1.3; docs/agent instructions/3.0/P1.3-mine-path/): which words of an episode
    # become cards (`list`: on your list, not known, no card yet · `unknown`: every word you don't know · `i1`: only
    # words with a line whose other words you know), whether grammar words go too (names follow logic.ignore_names:
    # G1.3), where Anki Miner is ("" = found by its installer's key) and the Anki Miner profile Connect mines with.
    # Read only by
    # `surasura-cli pick` and Connect: never in a signature (analyzer._NON_ANALYSIS_SETTINGS).
    "connect_mine_words": "list",
    "connect_send_grammar": True,
    "connect_anki_miner_path": "",
    "connect_anki_miner_profile": "Surasura",
    "logic": {
        "inline_completed_files": False,
        # Kana in ( ) right after kanji in a Japanese book (.txt / .md) — 山田太郎(やまだ・たろう), 窮鼠（きゅうそ）:
        # "hiragana" reads a hiragana group as that kanji's reading and drops it, as Aozora's 《ruby》 is dropped;
        # "any" a katakana group too; "off" keeps every group as text (analyzer.strip_text_conventions). It
        # changes what a run counts: in the run signature (never _NON_ANALYSIS_SETTINGS), and in the token
        # store's build signature when it isn't the default.
        "paren_readings": "hiragana",
        # Names are one word, not pieces (app/names.py; Settings -> Language & Parsing), Japanese only. Each
        # changes what a run counts: in the run signature (never _NON_ANALYSIS_SETTINGS). names_katakana: a
        # katakana name no dictionary list spells (トゥー + リ -> トゥーリ); read as a file is tokenized, so it is in
        # the token store's build signature when off. names_recurring: a katakana name the library keeps using
        # (リム + ハイ -> リムハイ); names_kanji: a kanji name (JMnedict) the library holds 3+ times (一 + 護 -> 一護);
        # names_work_terms: a story's own kanji words the library keeps using as one (写 + 輪 + 眼 -> 写輪眼) —
        # auto-generated captions don't count toward them. All three from the library's own tables, applied as the
        # cache is read: flipping one needs only a Generate.
        "names_katakana": True,
        "names_recurring": True,
        "names_kanji": True,
        "names_work_terms": True,
        # Phrases and titles as one word (Settings -> Language & Parsing), Japanese only: a dictionary compound that
        # is a phrase pattern (予想通り, こと自体), 元 + a noun (元首相) or a title (もののけ姫) is one word; off, it counts
        # as its parts (予想 + 通り). Other dictionary compounds are one word either way. It changes what a run
        # counts: in the run signature (never _NON_ANALYSIS_SETTINGS); read as a file is tokenized
        # (analyzer.join_affixes), so it is in the token store's build signature when off.
        "phrases_and_titles": True,
        # Pronouns with a suffix as one word (Settings -> Language & Parsing), Japanese only: a pronoun + a suffix the
        # lists carry as a word of its own (何様, 俺様, お前さん, それなり) is one word; off, it counts as its parts
        # (何 + 様). It changes what a run counts: in the run signature (never _NON_ANALYSIS_SETTINGS); read as a file
        # is tokenized (analyzer.join_affixes), so it is in the token store's build signature and the known-words
        # cache's key when off.
        "pronoun_bases": True,
        # Idioms and set phrases on your list (Settings -> Language & Parsing), Japanese only, on: JMdict's set phrases
        # the library meets as often as the cut-off asks of a word get rows of their own (気がする, 腑に落ちる,
        # もしかしたら — app/phrases.py); their words keep their rows. It changes what a run lists: in the run signature
        # (never _NON_ANALYSIS_SETTINGS), and in the known-words cache's key (a known phrase is also known as its
        # lemmas joined); not in the token store's build signature — tokenizing doesn't change, so flipping it needs
        # only a Generate. Off, every output is what it was without it.
        "phrase_rows": True,
        # Ignore names (Settings -> Language & Parsing), Japanese only, off: a learner learns names too. On, the
        # library's names (app/names.py) are ignored words everywhere — off the list, never an unknown in a sentence
        # (token_index.ignored_names). It changes what a run counts: in the run signature (never
        # _NON_ANALYSIS_SETTINGS). The token store always records which words are names, so flipping it needs only a
        # Generate.
        "ignore_names": False,
        "weights": {
            "_comment": "Multipliers for word scores based on folder. Higher = more important.",
            "high": 10,
            "low": 5,
            "goal": 2
        },
        "tiers": {
            "_comment": "Frequency rank thresholds for Tiers 1-4. Rank > last value = Tier 5.",
            "thresholds": [2500, 5000, 7500, 10000]
        },
        "context": {
            "_comment": "min_chars/preferred_max_chars: ideal sentence length range. max_chars: hard cap — sentences longer than this are excluded from candidate examples (a word's own/original sentence is still kept as a fallback). recency_files: tiebreaker only — among sentences that are otherwise equal (same i+1 cost, same length) prefer the one whose other words you met in this file or up to N files earlier; 0 = same file only, -1 = disable.",
            "search_range": 20,
            "min_chars": 10,
            "max_extra": 2,
            "preferred_max_chars": 50,
            "max_contexts": 3,
            "max_chars": 150,
            "recency_files": 1
        },
        "sentence_boundaries": {
            "_comment": "Characters that trigger a sentence split for each language. Includes the HALFWIDTH ideographic full stop \uff61, which anime subtitles use throughout (alongside halfwidth katakana) \u2014 without it their sentences never end and run together into one huge block \u2014 and, for Japanese, the FULLWIDTH full stop \uff0e of horizontal technical and official writing (a decimal point or an abbreviation's is told apart in code: \uff13\uff0e\uff11\uff14). Chinese ends a sentence at its full stops, ! and ? and a line end, never at \u2026\u2026 or \uff1b (GB/T 15834-2011: an ellipsis is a pause or an omission, a semicolon joins the clauses of one sentence).",
            "ja": "\u3002\uff61\uff0e\uff01\uff1f!?\n",
            "zh": "\u3002\uff61\uff01\uff1f!?\n"
        },
        "gui": {
            "_comment": "tooltip_delay: ms before tooltip appears.",
            "tooltip_delay": 500
        },
        "priority_markers": {
            "_comment": "Star (Priority): (High+Low)/Total >= priority_threshold AND Total >= priority_min. Scale (Lopsided): High/Total >= lopsided_threshold.",
            "priority_threshold": 0.5,
            "priority_min": 3,
            "lopsided_threshold": 0.85
        },
        "selection": {
            "_comment": "Density-band word selection (used when top-level 'strategy' == 'freq'; 'coverage' uses target_coverage instead). bands_ppm: per-band parts-per-million floors — how common a word must be to be included; scale-stable across library sizes; 'native' is a tiny 1ppm floor (~= min_count on typical libraries). band: the chosen tier. min_count: universal floor that drops one-off words from every band. minutes_per_file: immersion minutes per file, for the 'meet each word every N hours' estimate. auto (Automatic rarity, Settings -> Sentences & Logic): every Generate picks the band itself, the rarest band with auto_max_words words or fewer (the counts the Rarity slider shows), in place of 'band'; auto_max_words is edited here only. These are the single source of truth (no magic numbers in code).",
            "band": "occasional",
            "auto": False,
            "auto_max_words": 850,
            "min_count": 2,
            "minutes_per_file": 18,
            "bands_ppm": {"core": 2000, "common": 150, "occasional": 25, "uncommon": 10, "rare": 4, "very_rare": 2.5, "native": 1}
        },
        "modality": {
            "_comment": "Reading-vs-listening card routing. target_hours: a word counts as 'you'll hear it' if fewer than this many hours of listening pass between encounters — estimated from bundled reference data (app/reference_data.py), then overridden by your OWN subtitle/YouTube files wherever you have enough material. Observation can only ever REMOVE a reading badge, never add one. min_series: distinct works a word must appear in before it counts as general vocabulary rather than one story's jargon; skipped entirely until the library holds min_library_series works, since on a small library that says more about the library than the word. min_lib_count: universal floor, as in selection.",
            "target_hours": 60,
            "min_series": 5,
            "min_lib_count": 3,
            "min_library_series": 10
        },
        "importer": {
            "_comment": "split_overflow: max chars to search past target length for a clean boundary.",
            "split_overflow": 150
        },
        "chunk_size": 50
    }
}

# Optional modules may each expose a SETTINGS_DEFAULTS dict. Their keys are merged into the
# active settings only when the module is importable, keeping optional features fully "tacked
# on": the core defaults (and the shipped settings.json) stay free of their keys, and a build
# without the module never sees or persists them.
_OPTIONAL_MODULE_NAMES = ["modules.youtube_downloader", "modules.koe", "modules.reels", "modules.junban"]


def _optional_module_defaults() -> Dict[str, Any]:
    """Collect SETTINGS_DEFAULTS from any present optional modules."""
    merged: Dict[str, Any] = {}
    for name in _OPTIONAL_MODULE_NAMES:
        try:
            module = importlib.import_module(name)
            defaults = getattr(module, "SETTINGS_DEFAULTS", None)
            if isinstance(defaults, dict):
                merged.update(defaults)
        except Exception:
            pass
    return merged


# The Chinese sentence ends before 2.4, when …… and ； / ; ended a sentence too. A saved
# settings.json only ever gains characters (the union in load_settings), so the old default would live on in every
# saved file: naming it lets load_settings read it as the default it was, and leave a hand-edited set alone.
_OLD_ZH_BOUNDARIES = "\u3002\uff01\uff1f!?\n\uff1b;\u2026\u2026"


class SettingsError(Exception):
    """settings.json exists but can't be read (`load_settings(strict=True)`)."""


def load_settings(strict: bool = False) -> Dict[str, Any]:
    """Loads settings from disk and merges with defaults (plus any present optional modules).
    `strict`: a settings.json that exists but can't be read raises `SettingsError` instead of falling back to the
    defaults (the command line's `bad-data`: a fallback a later save would write back, P0.3 05 §1)."""
    settings_path = get_user_file("settings.json")
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    # Optional modules contribute their own defaults, but only when importable.
    settings.update(_optional_module_defaults())

    if os.path.exists(settings_path):
        try:
            # Hand-edited too (the reveal gates): read in its own encoding (path_utils.read_text), or a
            # BOM from Notepad loaded the defaults — which the dashboard's next save then wrote over it.
            user_settings = json.loads(read_text(settings_path))
            # Deep merge for 'logic'
            if "logic" in user_settings and isinstance(user_settings["logic"], dict):
                user_logic = user_settings["logic"]
                if not isinstance(settings.get("logic"), dict):
                    settings["logic"] = {}
                    
                for key, value in user_logic.items():
                    if key == "weights" and isinstance(value, dict) and isinstance(settings["logic"].get("weights"), dict):
                        settings["logic"]["weights"].update(value)
                    elif isinstance(value, dict) and isinstance(settings["logic"].get(key), dict):
                        settings["logic"][key].update(value)
                    else:
                        settings["logic"][key] = value
            
            # Update top-level settings (excluding logic which we handled)
            for key, value in user_settings.items():
                if key != "logic":
                    settings[key] = value
        except Exception as e:
            if strict:
                raise SettingsError(f"settings.json can't be read: {e}") from e
            print(f"Warning: Could not load settings, using defaults: {e}")

    # Sentence boundaries are user-editable, but a few characters are STRUCTURAL — without them
    # sentences simply never end. A saved settings.json overrides the defaults wholesale, so a user
    # who has ever opened the app carries their old copy forever; that's how the halfwidth '｡'
    # (which anime subtitles use throughout) stayed missing and let example sentences run through a
    # dozen subtitle cues. Union the configured set with the required base: custom additions are
    # kept, the essentials can't be lost.
    try:
        _boundaries = settings.setdefault("logic", {}).setdefault("sentence_boundaries", {})
        # A saved Chinese set that is still the old default — with or without the halfwidth full stop 2.1 added —
        # was never a choice: it reads as today's default. A set the user edited keeps its own characters.
        _zh = _boundaries.get("zh")
        if isinstance(_zh, str) and set(_zh) - {"\uff61"} == set(_OLD_ZH_BOUNDARIES):
            _boundaries["zh"] = DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["zh"]
        for _lang, _required in DEFAULT_SETTINGS["logic"]["sentence_boundaries"].items():
            if _lang.startswith("_"):
                continue
            _current = _boundaries.get(_lang) or ""
            _boundaries[_lang] = _current + "".join(c for c in _required if c not in _current)
    except Exception:
        pass

    # Selection: bands_ppm / min_count / minutes_per_file are user-editable (like 'weights'), but
    # fill any MISSING keys from defaults so a partial or older settings.json can't break the band
    # structure (e.g. a file predating the 'very_rare' band). User-provided values still win.
    try:
        default_sel = DEFAULT_SETTINGS["logic"]["selection"]
        sel = settings.setdefault("logic", {}).setdefault("selection", {})
        ppm = copy.deepcopy(default_sel["bands_ppm"])
        if isinstance(sel.get("bands_ppm"), dict):
            ppm.update(sel["bands_ppm"])      # user floors override; missing bands stay default
        sel["bands_ppm"] = ppm
        sel.setdefault("band", default_sel["band"])
        sel.setdefault("auto", default_sel["auto"])
        sel.setdefault("auto_max_words", default_sel["auto_max_words"])
        sel.setdefault("min_count", default_sel["min_count"])
        sel.setdefault("minutes_per_file", default_sel["minutes_per_file"])
    except Exception:
        pass

    return settings

# settings.json is written under the `settings` lock (`app/locks.py`, P0.3 04 §2), atomically: a temp file, then
# `os.replace`, retried briefly while another program holds the file open (02 §8). A writer waits this long for the lock;
# another program holds it only for one write.
LOCK_WAIT = 2.0
_REPLACE_TRIES = 5


def _write_atomically(path: str, to_save: Dict[str, Any]):
    """Temp file + `os.replace` (retried 5 x 100 ms while a reader holds the file open): old or new, never half."""
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=4)
            f.flush()
            os.fsync(f.fileno())                # on disk before it replaces the old file (a power cut: old or new)
        for attempt in range(_REPLACE_TRIES):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == _REPLACE_TRIES - 1:
                    raise
                time.sleep(0.1)
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass


def _settings_lock(wait: float):
    """The `settings` lock (a context manager), or None when this thread holds it already (a write inside
    `save_keys` or the window's writer). Raises `locks.Busy` when another holder keeps it past `wait`."""
    try:
        if locks.held_here("settings"):
            return None
        return locks.take("settings", "saving settings", wait=wait)
    except locks.Busy as e:
        if e.holder is None and locks.unopenable("settings"):
            # The lock file can't be opened (its folder's permissions): today's unlocked write beats losing the
            # setting. Every other program writing settings.json takes the same lock, so it can only race them.
            print("Warning: the settings lock can't be opened; saving without it.")
            return None
        raise
    except Exception as e:
        print(f"Warning: the settings lock can't be used ({e}); saving without it.")
        return None


def save_settings(settings: Dict[str, Any], clean_for_build: bool = False, wait: float = LOCK_WAIT) -> bool:
    """
    Saves settings to disk, atomically, under the `settings` lock (waiting up to `wait` seconds for it).
    If clean_for_build is True, or if the module is missing, 'hide_satoru' is stripped.
    Returns True once written; False when it could not be (the reason printed), the file untouched.
    """
    settings_path = get_user_file("settings.json")

    # 1. Start with a copy to avoid mutating the app's state
    # Ensure settings is a dict before calling copy
    if not isinstance(settings, dict):
        print(f"Error: save_settings expected dict, got {type(settings)}")
        return False
    to_save = copy.deepcopy(settings)

    # 2. Check for module availability
    module_exists = False
    try:
        import modules.immersion_architect
        module_exists = True
    except (ImportError, ModuleNotFoundError):
        module_exists = False

    # 3. Strip internal/locked variables if necessary
    if clean_for_build or not module_exists:
        to_save.pop("hide_satoru", None)

    # 4. Write to disk
    try:
        held = _settings_lock(wait)
        try:
            _write_atomically(settings_path, to_save)
        finally:
            if held is not None:
                held.release()
        return True
    except Exception as e:
        print(f"Error: Could not save settings: {e}")
        return False


def _read_file_as_is() -> Dict[str, Any]:
    try:
        settings = json.loads(read_text(get_user_file("settings.json")))   # a BOM too, as load_settings
        if not isinstance(settings, dict):
            raise ValueError("settings.json is not an object")
    except (OSError, ValueError):
        settings = load_settings()
    return settings


def save_keys(changes: Optional[Dict[str, Any]] = None, update: Optional[Callable] = None) -> Dict[str, Any]:
    """Saves a window's own keys (`changes`) onto settings.json AS IT IS ON DISK, every other key as the file holds it,
    and returns what was saved. Not onto `load_settings()`: that carries every default and every installed module's,
    so a window saving it put back a retired key the dashboard had dropped (a full Generate after each click) and wrote
    Speech's hidden keys for users who never turned Speech on. A file that can't be read falls back to the loaded
    settings. `update(settings)`, when given, changes the file's dict in place after `changes` (a window whose keys
    merge into what the file holds: the Anki window's per-language decks).

    The read and the write hold the `settings` lock together, so no other program's save lands between them. Never
    waits on the caller's thread (every window calls this from its own): the lock free, the file is written now; held
    by another program, the change is queued and written by a worker once it is free — retried, never dropped, in the
    order the windows saved (`flush_keys` waits for them; the process writes them before it ends)."""
    entry = (dict(changes or {}), update)
    try:
        held = locks.take("settings", "saving settings") if not locks.held_here("settings") else None
    except locks.Busy:
        with _QUEUED_LOCK:
            _QUEUED.append(entry)
        _queued_writer().submit(_build_queued)
        return _apply([entry], _read_file_as_is())
    except Exception as e:
        print(f"Warning: the settings lock can't be used ({e}); saving without it.")
        held = None
    try:
        settings = _apply([entry], _read_file_as_is())
        save_settings(settings)
    finally:
        if held is not None:
            held.release()
    return settings


def _apply(entries, settings):
    for changes, update in entries:
        settings.update(changes)
        if update is not None:
            update(settings)
    return settings


# The other windows' saves that met a held lock, in order; written by one worker (`_build_queued`).
_QUEUED = []
_QUEUED_LOCK = threading.Lock()
_QUEUED_WRITER = None
_WRITTEN_UPTO = [0]


def _build_queued():
    """The file as it is with every queued save applied in order (inside the lock, on the writer's worker)."""
    with _QUEUED_LOCK:
        entries = list(_QUEUED)
    _WRITTEN_UPTO[0] = len(entries)
    return _apply(entries, _read_file_as_is())


def _queued_written(_settings):
    with _QUEUED_LOCK:
        del _QUEUED[:_WRITTEN_UPTO[0]]


def _queued_writer():
    global _QUEUED_WRITER
    with _QUEUED_LOCK:
        if _QUEUED_WRITER is None:
            _QUEUED_WRITER = SettingsWriter(delay=0.0, on_saved=_queued_written)
            import atexit
            atexit.register(flush_keys, 10.0)
        return _QUEUED_WRITER


def flush_keys(timeout: Optional[float] = None) -> bool:
    """Wait until every queued window save is written (on a worker, or as the process ends). True when none is left."""
    writer = _QUEUED_WRITER
    return True if writer is None else writer.flush(timeout)


class SettingsWriter:
    """The window's settings writes, off its thread (P0.3 04 §2): `submit` hands over what to save and returns at
    once; one worker writes it `delay` seconds after the last submit, under the `settings` lock, atomically. A held
    lock or a refused replace is retried every `RETRY` seconds: queued, never dropped (the newest submit replaces an
    unwritten one, since each holds the window's whole state). Before the process ends, `flush` writes what is left.

    `submit(build)`: `build()` -> the settings dict, called on the worker inside the lock, so it may read the file as it
    is then: a key another window saved meanwhile is carried, never reverted. `on_saved(settings)` / `on_error(error)`
    run on the worker, never Tk: a window passes callbacks that only post to its own queue."""

    RETRY = 0.25

    def __init__(self, delay: float = 0.25, on_saved: Optional[Callable] = None,
                 on_error: Optional[Callable] = None, wait: float = LOCK_WAIT):
        self.delay = delay
        self.wait = wait
        self.on_saved = on_saved
        self.on_error = on_error
        self._cond = threading.Condition()
        self._pending = None            # the newest build not yet written
        self._submitted = 0             # submits so far
        self._written = 0               # the submit count the last write covered
        self._due = 0.0                 # when the pending build may be written (the debounce)
        self._worker = None

    def submit(self, build: Callable[[], Dict[str, Any]]):
        """Hand over the newest state to save. Never waits: safe on a window's thread."""
        with self._cond:
            self._pending = build
            self._submitted += 1
            self._due = time.monotonic() + self.delay
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name="settings-writer", daemon=True)
                self._worker.start()
            self._cond.notify_all()

    def pending(self) -> bool:
        with self._cond:
            return self._written < self._submitted

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Write what is pending now, and wait (on the caller's thread: never Tk's) until everything submitted so far
        is written. True when it is; False when `timeout` ran out first."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            target = self._submitted
            self._due = 0.0
            self._cond.notify_all()
            while self._written < target:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def _run(self):
        while True:
            with self._cond:
                while True:
                    if self._pending is None:
                        self._worker = None
                        return
                    quiet = self._due - time.monotonic()
                    if quiet <= 0:
                        break
                    self._cond.wait(quiet)
                build, upto = self._pending, self._submitted
            try:
                held = _settings_lock(self.wait)
                try:
                    settings = build()
                    if not save_settings(settings):
                        raise OSError("settings.json could not be written")
                finally:
                    if held is not None:
                        held.release()
            except Exception as e:
                if self.on_error is not None:
                    try:
                        self.on_error(e)
                    except Exception:
                        pass
                time.sleep(self.RETRY)                  # queued, never dropped: the same (or a newer) build again
                continue
            with self._cond:
                self._written = max(self._written, upto)
                if upto == self._submitted:
                    self._pending = None
                self._cond.notify_all()
            if self.on_saved is not None:
                try:
                    self.on_saved(settings)
                except Exception:
                    pass


def get_default_settings() -> Dict[str, Any]:
    """Returns a fresh copy of default settings."""
    return copy.deepcopy(DEFAULT_SETTINGS)
