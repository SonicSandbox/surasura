"""The Settings page as data (W3.3 P1; the RUNBOOK's *The catalog*): its sections, its rows in order, when each shows,
what each control reads, and what a change writes. Qt-free and Tk-free: the page (`settings_page.py`) paints what this
says and hands every change on through `change()`; it decides nothing.

- **Sections** in the mock's order, with Language & Parsing after Level (05 §5.7). A section with no visible row is left
  out of the page and the nav.
- **Rows** (`Row`): `keys` the settings a control writes (a top-level key, or a dotted `logic.` path); `reaches` the
  ones a door row's window holds (decks, fields, the deck pickers, Speech's tunables, Backfill's note types — reached
  there, shown here, never written here: 🧭 call 3); `adv` under *More options*; `group` a group name above it; `sub`
  indented under the row above; `when(settings, language, ctx)` whether it shows; `door` the opener names
  (`app/qt/windows.OPENERS`) its buttons open; `target` the section a summary's *Change ›* goes to.
- **Kinds:** `toggle` · `choice` (one of a few) · `cards` (choice cards, a line under each) · `tablets` (a list value's
  picks, or several bool keys as one row) · `list` (a list value: its items + the empty bed) · `slider` (the level) ·
  `number` · `range` (two numbers) · `text` · `select` (a long one-of) · `door` · `status` · `summary` (Your setup) ·
  `link` · `action` (an export, P11) · `custom` (a row its own package draws: Connect's switch, the store lines, the
  placing rules, Anki Miner's card, the credits…).
- `ctx`: a frozenset of the optional modules found (`installed_modules()`: "modules.junban", …), "koe_revealed" (the
  Speech reveal gate: `enable_koe` is in settings.json, `koe.is_revealed()`) and the known-words road chosen on the page
  ("road:anki" / "road:import"; page state, never a key — RUNBOOK 🧭 4).
- **Saving** (the RUNBOOK's rule, CLAUDE.md §6): `change()` returns only the row's own keys, and nothing for a value
  already there. A per-language value (`connect_backlog_cap`, `connect_video_folders`) comes back whole with only this
  language's entry changed, plus `update(file_dict)` that re-applies this one entry onto the file's value at write time
  (the intent keeper's S1; the settings service's `set(changes, update=update)`).

`NOT_SHOWN` names every setting no row shows, with why; `reachable()` every key a row shows. The test holds them to
`PLACED`: every setting in exactly one place.
"""
import copy
import importlib.util
import unicodedata
from collections import namedtuple
from collections.abc import Mapping

from app.connect import settings_values
from app.qt import settings_strings as S

Section = namedtuple("Section", "id icon name")
Row = namedtuple("Row",
                 "id section kind keys label help tip words options adv group sub when door reaches target bounds")

MODULES = ("modules.junban", "modules.koe", "modules.youtube_downloader")
LANGUAGES = ("ja", "zh")
PER_LANGUAGE = ("connect_backlog_cap", "connect_video_folders")

SECTIONS = tuple(Section(id_, icon, S.SECTIONS[id_]) for id_, icon in (
    ("setup", "star"), ("known", "words"), ("anki", "anki"), ("junban", "order"), ("backfill", "fill"),
    ("level", "level"), ("parsing", "text"), ("content", "content"), ("arrivals", "inbox"), ("connect", "link"),
    ("reading", "reading"), ("sentences", "sentence"), ("export", "export"), ("app", "app")))

# Doors no `OPENERS` entry held when this was written, and who brings each (the intent keeper's S8: none pending at
# release — `pending(registered)` lists the ones still missing; an entry that has landed is harmless until tidied).
PENDING_OPENERS = {
    "apkg_known": "W3.4 row 2", "migaku": "W3.4 row 2", "jiten": "W3.4 row 2", "extract": "W3.4 row 2",
    "anki": "W3.4 row 3", "youtube-downloader": "W3.4 row 4", "youtube-preview": "W3.4 row 4", "koe": "W3.4 row 4",
    "backfill": "W3.4 row 5", "junban": "W3.4 row 6", "put-back": "W3.4 row 6",
}

# Who fills each empty slot the page leaves (a summary, status, custom or action row: `SettingsPage.custom_row`): the
# module that draws it, or "pending: <who>" for a row still to come (the intent keeper's B2: a slot nobody fills is a
# row with nothing to click — the test fails on one missing here). PL's logos sit beside the words, never in a slot.
_LIVE, _CONNECT_ROWS, _RULES = "app.qt.settings_live", "app.qt.settings_connect", "app.qt.settings_rules"
FILLED_BY = {
    "setup_known": _LIVE, "setup_anki": _LIVE, "setup_mining": _LIVE, "setup_level": _LIVE, "setup_cards": _LIVE,
    "anki_connection": _LIVE, "hato": _LIVE, "jimaku": _LIVE, "anilist": _LIVE, "more_from_houseki": _LIVE,
    "export_frequency_list": _LIVE, "export_reading_words": _LIVE, "export_sentence_list": _LIVE,
    "logs": _LIVE, "data_credits": _LIVE, "version": _LIVE,
    "new_cards_a_day": _CONNECT_ROWS, "connect_enabled": _CONNECT_ROWS, "anki_miner": _CONNECT_ROWS,
    "placing_rules": _RULES,
    "mine_line": "pending: P6", "soon_line": "pending: P6",
    "set_up_again": "pending: W3.5 part 3", "covers_download": "pending: the covers owner (G1.2-19)",
}


# --- when a row shows ---------------------------------------------------------------------------------------------- #
def _get(settings, key, default=None):
    """`key` (top-level, or a dotted `logic.` path) in `settings`, or `default` when it isn't there."""
    node = settings
    for part in key.split(".") if key.startswith("logic.") else [key]:
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def _on(key):
    return lambda settings, language, ctx: bool(value_of(settings, key))


def _module(name):
    return lambda settings, language, ctx: name in ctx


def _all(*tests):
    return lambda settings, language, ctx: all(test(settings, language, ctx) for test in tests)


def _ja(settings, language, ctx):
    return language == "ja"


def _zh(settings, language, ctx):
    return language == "zh"


def _never(settings, language, ctx):
    return False


def known_road(settings, language, ctx=frozenset()):
    """The known-words road shown: the one the page chose ("road:anki" / "road:import" in `ctx`), else Anki when this
    language has decks chosen in `anki_sync_decks`, else Import (RUNBOOK 🧭 4: page state, never a key)."""
    if "road:import" in ctx:
        return "import"
    if "road:anki" in ctx:
        return "anki"
    return "anki" if _decks(settings, language) else "import"


def _road(road):
    return lambda settings, language, ctx: known_road(settings, language, ctx) == road


def _anki_set_up(settings, language, ctx):
    """2.4's rule (`main.anki_sync_is_set_up`): decks chosen for any language."""
    decks = _get(settings, "anki_sync_decks")
    return isinstance(decks, Mapping) and any(bool(chosen) for chosen in decks.values())


def _coverage(settings, language, ctx):
    return value_of(settings, "strategy") == "coverage"


_JUNBAN = _module("modules.junban")
_JUNBAN_ON = _all(_JUNBAN, _on("enable_junban"))
_CONNECT = _on("connect_enabled")
_KOE = _all(_module("modules.koe"), lambda settings, language, ctx: "koe_revealed" in ctx)
_YOUTUBE = _module("modules.youtube_downloader")


# --- the rows ------------------------------------------------------------------------------------------------------ #
def _row(id_, section, kind, keys=(), options=None, adv=False, group=None, sub=False, when=None, door=(), reaches=(),
         target=None, bounds=None):
    label, help_, tip, words = S.ROWS[id_]
    return Row(id_, section, kind, tuple(keys), label, help_, tip, words, options, adv, group, sub, when, tuple(door),
               tuple(reaches), target, bounds)


ROWS = (
    # Your setup: five live summaries (P4), each *Change ›* to its section
    _row("setup_known", "setup", "summary", target="known"),
    _row("setup_anki", "setup", "summary", target="anki"),
    _row("setup_mining", "setup", "summary", target="anki"),
    _row("setup_level", "setup", "summary", target="level"),
    _row("setup_cards", "setup", "summary", target="junban", when=_JUNBAN),

    # Known words: one road, its rows under it
    _row("known_road", "known", "choice", options=("anki", "import")),
    _row("anki_decks", "known", "door", sub=True, when=_road("anki"), door=("anki",),
         reaches=("anki_sync_decks", "anki_sync_fields")),
    _row("anki_sync_auto", "known", "toggle", ("anki_sync_auto",), sub=True, when=_road("anki")),
    _row("anki_auto_generate", "known", "toggle", ("anki_auto_generate",), sub=True, when=_road("anki")),
    _row("known_import", "known", "door", sub=True, when=_road("import"), door=("migaku", "jiten", "apkg_known")),
    _row("words_to_leave_out", "known", "door", door=("word-lists",)),
    _row("anki_sync_include_suspended", "known", "toggle", ("anki_sync_include_suspended",), adv=True,
         group="counts_as_known"),

    # Anki & mining
    _row("anki_connection", "anki", "status"),
    _row("new_cards_a_day", "anki", "custom", ("words_per_day",), bounds=(0, None)),       # P9: Anki's own value
    _row("connect_enabled", "anki", "custom", ("connect_enabled",)),                        # P5: Connect's switch
    _row("connect_mine_words", "anki", "cards", ("connect_mine_words",), options=("list", "unknown", "i1"),
         group="from_library", when=_CONNECT),
    _row("mine_line", "anki", "custom", when=_CONNECT),                                     # P6: the store's line
    _row("connect_send_grammar", "anki", "toggle", ("connect_send_grammar",), when=_CONNECT),
    _row("connect_open_anki", "anki", "choice", ("connect_open_anki",), options=(False, True), when=_CONNECT),
    _row("connect_backlog_cap", "anki", "number", ("connect_backlog_cap",), when=_CONNECT, bounds=(0, 5000)),
    _row("known_from_anki", "anki", "tablets", ("known_from_anki",),
         options=tuple(term for term, _label in settings_values.KNOWN), when=_CONNECT),
    _row("connect_video_folders", "anki", "list", ("connect_video_folders",), when=_CONNECT),
    _row("junban_own_tag", "anki", "text", ("junban_own_tag",), group="in_anki", when=_all(_CONNECT, _JUNBAN)),
    _row("junban_order_all", "anki", "toggle", ("junban_order_all",), when=_all(_CONNECT, _JUNBAN)),
    _row("anki_sync_delay_min", "anki", "choice", ("anki_sync_delay_min",), adv=True, group="anki"),
    _row("automation", "anki", "toggle", ("logic.automation",), adv=True),
    _row("journey_settle_s", "anki", "number", ("journey_settle_s",), adv=True, bounds=(0, None)),
    _row("journey_settle_battery_s", "anki", "number", ("journey_settle_battery_s",), adv=True, bounds=(0, None)),
    _row("connect_anki_miner_profile", "anki", "text", ("connect_anki_miner_profile",), adv=True, when=_CONNECT),
    _row("anki_connect_url", "anki", "text", ("anki_connect_url",), adv=True),

    # Junban (with modules/junban; its rows follow the switch, Put Anki back stays: N3)
    _row("enable_junban", "junban", "toggle", ("enable_junban",), when=_JUNBAN),
    _row("junban_scope", "junban", "choice", ("junban_scope",), options=("deck", "all"), when=_JUNBAN_ON,
         door=("junban",), reaches=("junban_deck",)),
    _row("junban_order", "junban", "choice", ("junban_order",), options=("content", "priority"), when=_JUNBAN_ON),
    _row("junban_unlisted", "junban", "choice", ("junban_unlisted",), options=("list_first", "journey", "back"),
         when=_JUNBAN_ON),
    _row("junban_first", "junban", "tablets", ("junban_phrases", "junban_ready_first"),
         options=("junban_phrases", "junban_ready_first"), when=_JUNBAN_ON),
    _row("junban_later", "junban", "tablets", ("junban_later_tag", "junban_later_flag", "junban_later_suspend"),
         options=("junban_later_tag", "junban_later_flag", "junban_later_suspend"), when=_JUNBAN_ON),
    _row("junban_auto_reorder", "junban", "toggle", ("junban_auto_reorder",), when=_JUNBAN_ON),
    _row("junban_auto_actions", "junban", "toggle", ("junban_auto_actions",), when=_JUNBAN_ON),
    _row("junban_door", "junban", "door", when=_JUNBAN_ON, door=("junban",), reaches=("junban_word_fields",)),
    _row("put_back", "junban", "door", when=_JUNBAN, door=("put-back",)),
    _row("junban_write_frequency", "junban", "toggle", ("junban_write_frequency",), adv=True, when=_JUNBAN_ON),
    _row("junban_frequency_field", "junban", "text", ("junban_frequency_field",), adv=True, sub=True,
         when=_JUNBAN_ON),
    _row("junban_write_freqsort", "junban", "toggle", ("junban_write_freqsort",), adv=True, when=_JUNBAN_ON),
    _row("junban_tag", "junban", "text", ("junban_tag",), adv=True, when=_JUNBAN_ON),
    _row("junban_tag_markers", "junban", "toggle", ("junban_tag_markers",), adv=True, when=_JUNBAN_ON),
    _row("junban_only_markers", "junban", "tablets", ("junban_only_markers",), options=("star", "lopsided", "reading"),
         adv=True, when=_JUNBAN_ON),
    _row("junban_chunk_size", "junban", "number", ("junban_chunk_size",), adv=True, when=_JUNBAN_ON, bounds=(1, None)),

    # Backfill (with modules/junban; hides with Junban's switch, as in 2.4: N3)
    _row("junban_backfill_fills", "backfill", "tablets", ("junban_backfill_fills",), options=("patterns", "sentence"),
         when=_JUNBAN_ON),
    _row("junban_backfill_cards", "backfill", "choice", ("junban_backfill_cards",), options=("all", "new"),
         when=_JUNBAN_ON, door=("backfill",), reaches=("junban_backfill_deck",)),
    _row("junban_backfill_replace", "backfill", "toggle", ("junban_backfill_replace",), when=_JUNBAN_ON),
    _row("junban_auto_backfill", "backfill", "toggle", ("junban_auto_backfill",), when=_JUNBAN_ON),
    _row("backfill_door", "backfill", "door", when=_JUNBAN_ON, door=("backfill",)),
    _row("backfill_fields", "backfill", "door", adv=True, when=_JUNBAN_ON, door=("backfill",),
         reaches=("junban_backfill_fields", "junban_backfill_note_languages")),

    # Level (New words a day went to Anki & mining's *New cards a day*: G1.2-5)
    _row("level", "level", "slider", ("logic.selection.band", "logic.selection.auto")),
    _row("strategy", "level", "choice", ("strategy",), options=("freq", "coverage")),
    _row("target_coverage", "level", "number", ("target_coverage",), sub=True, when=_coverage, bounds=(1, 100)),
    _row("show_words_per_day", "level", "toggle", ("show_words_per_day",), adv=True),
    _row("min_count", "level", "number", ("logic.selection.min_count",), adv=True, bounds=(1, None)),
    _row("minutes_per_file", "level", "number", ("logic.selection.minutes_per_file",), adv=True, bounds=(1, None)),
    _row("auto_max_words", "level", "number", ("logic.selection.auto_max_words",), adv=True, bounds=(1, None)),

    # Language & Parsing (05 §5.7): the script for Chinese, the rest Japanese only
    _row("zh_script", "parsing", "choice", ("zh_script",), options=("asis", "s", "t"), when=_zh),
    _row("paren_readings", "parsing", "choice", ("logic.paren_readings",), options=("hiragana", "any", "off"),
         when=_ja),
    _row("names_katakana", "parsing", "toggle", ("logic.names_katakana",), group="names", when=_ja),
    _row("names_recurring", "parsing", "toggle", ("logic.names_recurring",), when=_ja),
    _row("names_kanji", "parsing", "toggle", ("logic.names_kanji",), when=_ja),
    _row("names_work_terms", "parsing", "toggle", ("logic.names_work_terms",), when=_ja),
    _row("ignore_names", "parsing", "toggle", ("logic.ignore_names",), when=_ja),
    _row("phrases_and_titles", "parsing", "toggle", ("logic.phrases_and_titles",), group="words_phrases", when=_ja),
    _row("pronoun_bases", "parsing", "toggle", ("logic.pronoun_bases",), when=_ja),
    _row("phrase_rows", "parsing", "toggle", ("logic.phrase_rows",), when=_ja),
    _row("exclude_single", "parsing", "toggle", ("exclude_single",), when=_ja),
    _row("how_parsing_works", "parsing", "link"),

    # Content
    _row("target_language", "content", "choice", ("target_language",), options=LANGUAGES),
    _row("soon_line", "content", "custom"),                                                 # P6: the store's line
    _row("split_length", "content", "number", ("split_length",), bounds=(1, None)),
    _row("enable_youtube_transcripts", "content", "toggle", ("enable_youtube_transcripts",), when=_YOUTUBE),
    _row("enable_youtube_preview", "content", "toggle", ("enable_youtube_preview",), when=_YOUTUBE),
    _row("content_doors", "content", "door", door=("extract", "youtube-downloader", "youtube-preview")),

    # New arrivals: one line per source, a line set to Wait leaves the dict (D30, RD-S16)
    _row("placing_rules", "arrivals", "custom", ("placing_rules",),
         options=("wait", "top", "after-show", "soon", "goal", "finished")),

    # Connections (docked)
    _row("anki_miner", "connect", "custom", ("connect_anki_miner_path",)),                   # P8: Anki Miner's card
    _row("hato", "connect", "status", group="houseki"),
    _row("jimaku", "connect", "status"),
    _row("anilist", "connect", "status"),
    _row("more_from_houseki", "connect", "status"),

    # Journey
    _row("theme", "reading", "select", ("theme",),
         options=("Default (Dark)", "Dark Flow", "Midnight (Vibrant)", "Modern Light", "Zen Mode")),
    _row("open_app_mode", "reading", "toggle", ("open_app_mode",)),
    _row("source_display", "reading", "choice", ("source_display",), options=("off", "icon", "filename", "full")),
    _row("word_search_enabled", "reading", "toggle", ("word_search_enabled",)),
    _row("anki_backlog_on_generate", "reading", "toggle", ("anki_backlog_on_generate",), when=_anki_set_up),
    _row("inline_completed_files", "reading", "toggle", ("logic.inline_completed_files",)),
    _row("hide_audio_button", "reading", "toggle", ("logic.hide_audio_button",)),
    _row("word_search_category", "reading", "choice", ("word_search_category",),
         options=("all", "anime", "liveaction", "youtube"), adv=True),
    _row("zen_limit", "reading", "number", ("zen_limit",), adv=True, bounds=(25, 125)),
    _row("enable_koe", "reading", "toggle", ("enable_koe",), adv=True, when=_KOE),
    _row("koe_door", "reading", "door", adv=True, sub=True, when=_KOE, door=("koe",),
         reaches=("koe_voice", "koe_model", "koe_style", "koe_temperature", "koe_daily_cap")),

    # Sentences
    _row("sentence_length", "sentences", "range", ("logic.context.min_chars", "logic.context.preferred_max_chars"),
         bounds=(0, None)),
    _row("max_contexts", "sentences", "number", ("logic.context.max_contexts",), bounds=(1, 10)),
    _row("ensure_audio_example", "sentences", "toggle", ("ensure_audio_example",)),
    _row("only_i_plus_one", "sentences", "toggle", ("only_i_plus_one",)),
    _row("max_chars", "sentences", "number", ("logic.context.max_chars",), adv=True, bounds=(1, None)),

    # Export (P11 wires the three actions)
    _row("sentence_dictionary", "export", "door", door=("sentence-dictionary",)),
    _row("export_frequency_list", "export", "action"),
    _row("export_reading_words", "export", "action"),
    _row("export_sentence_list", "export", "action"),
    _row("sentence_dictionary_source", "export", "toggle", ("sentence_dictionary_source",), adv=True),
    _row("frequency_lists", "export", "door", adv=True, door=("frequency-lists",)),

    # App (no theme picker: one theme in 3.0, RS-1)
    _row("text_size", "app", "choice", ("text_size",), options=("S", "M", "L")),
    _row("app_motion", "app", "choice", ("app_motion",), options=("follow", "full", "reduced")),
    _row("auto_update_enabled", "app", "toggle", ("auto_update_enabled",)),
    _row("telemetry_enabled", "app", "toggle", ("telemetry_enabled",)),
    _row("logs", "app", "custom"),
    _row("data_credits", "app", "custom"),
    _row("version", "app", "custom"),
    _row("set_up_again", "app", "custom", when=_never),          # S10: shown once the wizard (W3.5 part 3) lands
    _row("covers_download", "app", "custom", when=_never),       # S10: shown once the covers owner lands (G1.2-19)
)
ROW = {row.id: row for row in ROWS}

# Every setting no row shows, and why (the test holds it to PLACED).
NOT_SHOWN = {
    "app_theme": "one theme in 3.0 (RS-1): no theme picker",
    "onboarding_completed": "state: the first start's",
    "setup_seen": "state: the version whose setup pages were seen (the wizard, WZ-8)",
    "setup_passed": "state: the setup pages saved before setup finished (the wizard)",
    "covers_download": "the wizard's *Your shows* page; its row here shows once the covers owner lands (G1.2-19)",
    "open_count": "state: a launch counter",
    "skipped_version": "state: its way back is App's *Offer <version> again*",
    "youtube_risk_acknowledged": "the downloader's own one-time ask",
    "add_graduated_words": "retired with Graduate (D23)",
    "index_pool_workers": "speed only: every file's tokens are the same either way",
    "koe_port": "settings.json only: the speech helper's port",
    "junban_replan_preview": "2.x's preview: 3.0 writes the plan always",
    "junban_replan_language": "2.x's preview: 3.0 writes the plan always",
    "junban_replan_deck": "2.x's preview: 3.0 writes the plan always",
    "logic.chunk_size": "settings.json only (A5)",
    "logic.weights.high": "settings.json only (A5)",
    "logic.weights.low": "settings.json only (A5)",
    "logic.weights.goal": "settings.json only (A5)",
    "logic.tiers.thresholds": "settings.json only (A5)",
    "logic.context.search_range": "settings.json only (A5)",
    "logic.context.max_extra": "settings.json only (A5)",
    "logic.context.recency_files": "settings.json only (A5)",
    "logic.sentence_boundaries.ja": "settings.json only (A5)",
    "logic.sentence_boundaries.zh": "settings.json only (A5)",
    "logic.gui.tooltip_delay": "dead: nothing reads it",
    "logic.priority_markers.priority_threshold": "settings.json only (A5)",
    "logic.priority_markers.priority_min": "settings.json only (A5)",
    "logic.priority_markers.lopsided_threshold": "settings.json only (A5)",
    "logic.selection.bands_ppm": "settings.json only (A5)",
    "logic.modality.target_hours": "settings.json only (A5)",
    "logic.modality.min_series": "settings.json only (A5)",
    "logic.modality.min_lib_count": "settings.json only (A5)",
    "logic.modality.min_library_series": "settings.json only (A5)",
    "logic.importer.split_overflow": "settings.json only (A5)",
}
NOT_SHOWN.update({key: "Reels: sunset (2026-09-22), excluded from every build" for key in (
    "enable_reels", "reels_context_cues", "reels_exclude_numerals", "reels_exclude_proper_nouns", "reels_ffmpeg_dir",
    "reels_gap_seconds", "reels_max_folder_gb", "reels_max_unknown", "reels_open_player", "reels_output_dir",
    "reels_subsync_path", "reels_words_per_part")})


# --- reading ------------------------------------------------------------------------------------------------------- #
_DEFAULTS = []


def defaults():
    """The settings as `settings_manager` fills them in: the core defaults and each present module's."""
    if not _DEFAULTS:
        from app import settings_manager
        merged = copy.deepcopy(settings_manager.DEFAULT_SETTINGS)
        merged.update(copy.deepcopy(settings_manager._optional_module_defaults()))
        _DEFAULTS.append(merged)
    return _DEFAULTS[0]


def plain(value):
    """A plain, changeable copy of a settings value (the service's `get()` is frozen: mappings and tuples)."""
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def value_of(settings, key):
    """`key` as the settings hold it, else its default (`enable_koe`: absent is off)."""
    missing = object()
    found = _get(settings, key, missing)
    if found is missing:
        found = _get(defaults(), key, False if key == "enable_koe" else None)
    return found


def _decks(settings, language):
    decks = value_of(settings, "anki_sync_decks")
    return list((decks or {}).get(language) or []) if isinstance(decks, Mapping) else []


def _one(settings, key, language):
    """A key's value as its control shows it: a per-language key this language's entry."""
    if key == "connect_backlog_cap":
        return settings_values.cap_of(plain(value_of(settings, key)), language)
    if key == "connect_video_folders":
        from app.connect import videos
        return videos.configured({key: plain(value_of(settings, key))}, language)
    found = plain(value_of(settings, key))
    if key == "known_from_anki" and isinstance(found, str):
        found = [found]
    return found


def value(row, settings, language):
    """What `row`'s control shows: one key's value; several keys as {key: value}; a door its window's value for this
    language where it shows one (the decks); the road its side; None for a row that holds no setting."""
    if row.id == "known_road":
        return known_road(settings, language)
    if row.id == "anki_decks":
        return _decks(settings, language)
    if not row.keys:
        return None
    switch = row.kind == "toggle" or row.kind in ("tablets", "slider") and len(row.keys) > 1
    shown = {key: _one(settings, key, language) for key in row.keys}
    if switch:                  # a switch not in the defaults (the dashboard's `logic.hide_audio_button`) reads as off
        shown = {key: bool(v) if row.kind != "slider" or key.endswith(".auto") else v for key, v in shown.items()}
    return shown[row.keys[0]] if len(row.keys) == 1 else shown


def options(row, settings, language):
    """`row`'s choices as (value, label, line) — line "" where none: the level's bands, the sync's three and a held
    fourth (`settings_values.sync_choices`), each other choice from the strings table."""
    if row.kind == "slider":
        from app import word_selection
        return tuple((band, word_selection.band_label(band), "") for band in word_selection.BANDS_ORDER)
    if row.id == "anki_sync_delay_min":
        return tuple((v, label, "") for label, v in settings_values.sync_choices(value_of(settings, row.keys[0])))
    labels, lines = S.OPTIONS.get(row.id, {}), S.OPTION_LINES.get(row.id, {})
    return tuple((v, labels.get(v, str(v)), lines.get(v, "")) for v in (row.options or ()))


def rows(section_id):
    """The rows of a section, in order."""
    return [row for row in ROWS if row.section == section_id]


def visible(row, settings, language, ctx=frozenset()):
    """Whether `row` shows for this settings, language and context. A door row also needs its opener available — the
    page's to ask (`windows.available`)."""
    return row.when is None or bool(row.when(settings, language, ctx))


def sections(settings, language, ctx=frozenset()):
    """The sections with a row to show, in order."""
    return [section for section in SECTIONS if any(visible(row, settings, language, ctx) for row in rows(section.id))]


def installed_modules():
    """The optional modules found (a file look: a worker's call)."""
    found = set()
    for name in MODULES:
        try:
            if importlib.util.find_spec(name) is not None:
                found.add(name)
        except (ImportError, ValueError):
            pass
    return frozenset(found)


def doors():
    """Every opener name a row opens."""
    return {name for row in ROWS for name in row.door}


def pending(registered):
    """The doors a row opens that no opener in `registered` (the names of `windows.OPENERS`) holds yet: {name: who
    brings it}. Empty at release (S8)."""
    return {name: PENDING_OPENERS.get(name, "nobody") for name in sorted(doors() - set(registered))}


def reachable():
    """Every setting a row shows: the keys its control writes and the ones its door's window holds."""
    return {key for row in ROWS for key in row.keys + row.reaches}


def rows_for(keys):
    """The ids of the rows showing any of `keys` (a write's keys: which rows repaint)."""
    keys = set(keys)
    return [row.id for row in ROWS if keys & set(row.keys + row.reaches)]


def locate(target):
    """(section id, row id or None) for a reveal target: a section id, a row id or a key; None when it is none."""
    if any(section.id == target for section in SECTIONS):
        return target, None
    if target in ROW:
        return ROW[target].section, target
    found = rows_for([target])
    return (ROW[found[0]].section, found[0]) if found else None


def _fold(text):
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def find(query, settings, language, ctx=frozenset()):
    """The ids of the visible rows whose label, help, search words or choice labels hold `query` (NFKC, case-folded);
    an empty query: every visible row."""
    q = _fold(query).strip()
    found = []
    for row in ROWS:
        if not visible(row, settings, language, ctx):
            continue
        labels = [label for _v, label, _l in options(row, settings, language)]
        text = " ".join([row.label, row.help, row.words] + labels)
        if not q or q in _fold(text):
            found.append(row.id)
    return found


# --- changing ------------------------------------------------------------------------------------------------------ #
def _number(row, new):
    n = int(new)
    low, high = row.bounds or (None, None)
    if low is not None:
        n = max(low, n)
    if high is not None:
        n = min(high, n)
    return n


def _merge(key, compute):
    """`update(file_dict)`: this language's entry re-applied onto the file's own value at write time (S1)."""
    def update(on_file):
        on_file[key] = compute(plain(on_file.get(key, value_of(defaults(), key))))
    return update


def _per_language(row, settings, language, new):
    key = row.keys[0]
    if key == "connect_backlog_cap":
        n = _number(row, new)
        if n == _one(settings, key, language):
            return {}, None
        def compute(current):
            return settings_values.cap_value(current, language, n)
    else:
        folders = [str(f) for f in (new or ()) if str(f).strip()]
        if folders == _one(settings, key, language):
            return {}, None
        def compute(current):
            return settings_values.folders_value(current, language, folders)
    return {key: compute(plain(value_of(settings, key)))}, _merge(key, compute)


def change(row, settings, language, new):
    """What a control's new value writes: `(changes, update)` — `changes` {key: value}, only the row's own keys and only
    those whose value isn't already what the settings hold (`{}` for none; a row holding no setting never writes);
    `update` None, or for a per-language key the function that re-applies this language's entry onto the file's value at
    write time. `new` by kind: a bool, a value, a number; `range` a (low, high) pair; `tablets` the picks (a list
    value's values, or several bool keys' keys on — a {key: bool} dict too); `list` the items; the level a band name (a hand
    pick: Automatic goes off with it, S2) or {"logic.selection.auto": bool}; the placing rules (source, target) — Wait
    removes the source — or the whole {source: target} dict."""
    if not row.keys:
        return {}, None
    if row.keys[0] in PER_LANGUAGE:
        return _per_language(row, settings, language, new)
    wanted = _wanted(row, settings, language, new)
    current = value(row, settings, language)
    if len(row.keys) == 1:
        current = {row.keys[0]: current}
    return {key: v for key, v in wanted.items() if key in row.keys and current.get(key) != v}, None


def _wanted(row, settings, language, new):
    """{key: the value `new` means} for `row` (before dropping what is already there)."""
    keys = row.keys
    if row.kind == "slider":
        if isinstance(new, Mapping):
            return {k: bool(v) if k.endswith(".auto") else v for k, v in new.items()}
        if new not in {band for band, _l, _ in options(row, settings, language)}:
            raise ValueError(f"not a level: {new!r}")
        return {keys[0]: new, keys[1]: False}
    if row.kind == "range":
        return {key: _number(row, n) for key, n in zip(keys, new)}
    if row.kind == "tablets" and len(keys) > 1:
        picked = new if isinstance(new, Mapping) else {key: key in set(new) for key in keys}
        return {key: bool(v) for key, v in picked.items()}
    key = keys[0]
    if row.kind == "tablets":
        picked = set(new or ())
        if key == "known_from_anki":
            return {key: settings_values.known_value(picked)}
        return {key: [v for v in row.options if v in picked]}
    if row.id == "placing_rules":
        held = plain(value_of(settings, key))
        rules = dict(held) if isinstance(held, Mapping) else {}       # a hand-edited non-dict: the pick starts afresh
        if isinstance(new, Mapping):
            rules = {source: target for source, target in new.items()}
            picked = list(rules.values())
        else:
            source, target = new
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f"not a source: {source!r}")
            rules[source] = target
            picked = [target]           # another line's hand-edited target stays as written (rules.py skips it)
        unknown = [t for t in picked if t not in row.options]
        if unknown:
            raise ValueError(f"not a place: {unknown[0]!r}")
        return {key: {source: target for source, target in rules.items() if target != "wait"}}
    if row.kind == "toggle" or key == "connect_enabled":
        return {key: bool(new)}
    if row.kind == "number" or key == "words_per_day":
        return {key: _number(row, new)}
    if row.kind == "text" or key == "connect_anki_miner_path":
        return {key: str(new or "").strip()}
    choices = [v for v, _label, _line in options(row, settings, language)]
    if choices and new not in choices:
        raise ValueError(f"not a choice of {row.id}: {new!r}")
    return {key: new}
