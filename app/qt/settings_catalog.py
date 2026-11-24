"""The Settings page as data (W3.3 P1; the RUNBOOK's *The catalog*): its sections, its rows in order, when each shows,
what each control reads, and what a change writes. Qt-free and Tk-free: the page (`settings_page.py`) paints what this
says and hands every change on through `change()`; it decides nothing.

- **Sections** in the mock's order, with Language & Parsing after Level (05 §5.7). A section with no visible row is left
  out of the page and the nav.
- **Rows** (`Row`): `keys` the settings a control writes (a top-level key, or a dotted `logic.` path); `reaches` the
  ones a door row's window holds (decks, fields, the deck pickers, Speech's tunables, Backfill's note types — reached
  there, shown here, never written here: 🧭 call 3; a `PROGRAM_ROWS` row's program, its own picker's); `adv` under
  *More options*; `group` a group name above it; `sub` indented under the row above; `when(settings, language, ctx)`
  whether it shows; `door` the opener names (`app/qt/windows.OPENERS`) its buttons open; `target` the section a
  summary's *Change ›* goes to.
- **Kinds:** `toggle` (a bool key; with `options` one value of a list key, Q31) · `choice` (one of a few) · `cards`
  (choice cards, a line under each) · `tablets` (a list value's picks, each lit one ticked — never the vein a choice
  draws under its one, so no multi-pick reads as a pick-one: Q31; picks a word each says better are switches, a row
  each) · `list` (a list value: its items + the empty bed) · `slider` (the level) · `number` · `range` (two numbers) ·
  `text` · `select` (a long one-of) · `door` · `status` · `summary` (Your setup) · `link` · `links` (a block of its
  own: its title, then a button per page in `options` across its width, a9.1) · `action` (an export, P11) ·
  `custom` (a row its own package draws: Connect's switch, the store lines, the placing rules, Anki Miner's card, the
  credits…).
- `ctx`: a frozenset of the optional modules found (`installed_modules()`: "modules.junban", …), "koe_revealed" (the
  Speech reveal gate: `enable_koe` is in settings.json, `koe.is_revealed()`) and the known-words road chosen on the page
  ("road:anki" / "road:import"; page state, never a key — RUNBOOK 🧭 4). Row 13 (laptop fixes): "hato_found" (hato's
  entry in the shared tools folder), "miner_found" (`anki_miner.find`) and "looked" (the look has answered), each found
  on a worker — a row for a tool not here hides; its saved value is never touched.
- **Saving** (the RUNBOOK's rule, CLAUDE.md §6): `change()` returns only the row's own keys, and nothing for a value
  already there. A per-language value (`connect_backlog_cap`, `connect_video_folders`) comes back whole with only this
  language's entry changed, plus `update(file_dict)` that re-applies this one entry onto the file's value at write time
  (the intent keeper's S1; the settings service's `set(changes, update=update)`).

`NOT_SHOWN` names every setting no row shows, with why; `reachable()` every key a row shows. The test holds them to
`PLACED`: every setting in exactly one place.
"""
import copy
import importlib.util
import os
import unicodedata
from collections import namedtuple
from collections.abc import Mapping

from app import plan_rules, settings_manager
from app.connect import settings_values
from app.connect import known_signal, review_loop
from app.qt import settings_strings as S
from app.services import tools_found

Section = namedtuple("Section", "id icon name")
Row = namedtuple("Row",
                 "id section kind keys label help tip words options adv group sub when door reaches target bounds")

MODULES = ("modules.junban", "modules.koe", "modules.youtube_downloader", "modules.irodori")
LANGUAGES = ("ja", "zh")
PER_LANGUAGE = ("connect_backlog_cap", "connect_video_folders")
CHOSEN = "known_from_anki_chosen"                    # Kantan-B3: written beside its pick (`change`)

# Fine-tune's three heads (Mado-EZA: EZ-4, SPEC-r2 §0.5; PROVISIONAL): the sections under Cards · Library · App, in the
# page's order — Your setup above them all (Essentials takes it later); Connections under App until Tools takes it
HEADS = (
    ("cards", ("known", "anki", "junban", "backfill", "sentences", "level")),
    ("library", ("content", "arrivals", "parsing", "reading", "export")),
    ("app", ("connect", "app")),
)
HEAD_OF = {section: head for head, sections in HEADS for section in sections}
_ICONS = {"setup": "star", "known": "words", "anki": "anki", "junban": "order", "backfill": "fill", "level": "level",
          "parsing": "text", "content": "content", "arrivals": "inbox", "connect": "link", "reading": "reading",
          "sentences": "sentence", "export": "export", "app": "app"}
SECTIONS = tuple(Section(id_, _ICONS[id_], S.SECTIONS[id_])
                 for id_ in ("setup",) + tuple(s for _head, sections in HEADS for s in sections))

# Doors no `OPENERS` entry held when this was written, and who brings each (the intent keeper's S8: none pending at
# release — `pending(registered)` lists the ones still missing; an entry that has landed is harmless until tidied).
PENDING_OPENERS = {
    "apkg_known": "W3.4 row 2", "migaku": "W3.4 row 2", "jiten": "W3.4 row 2",
    "anki": "W3.4 row 3", "youtube-preview": "W3.4 row 4", "koe": "W3.4 row 4",
    "backfill": "W3.4 row 5", "junban": "W3.4 row 6", "put-back": "W3.4 row 6",
}

# Who fills each empty slot the page leaves (a summary, status, custom or action row: `SettingsPage.custom_row`): the
# module that draws it, or "pending: <who>" for a row still to come (the intent keeper's B2: a slot nobody fills is a
# row with nothing to click — the test fails on one missing here). PL's logos sit beside the words, never in a slot.
_LIVE, _CONNECT_ROWS, _RULES = "app.qt.settings_live", "app.qt.settings_connect", "app.qt.settings_rules"
_STORE = "app.qt.settings_store"
FILLED_BY = {
    "setup_known": _LIVE, "setup_anki": _LIVE, "setup_mining": _LIVE, "setup_level": _LIVE, "setup_cards": _LIVE,
    "anki_connection": _LIVE, "hato": _LIVE, "jimaku": _LIVE, "anilist": _LIVE, "more_from_houseki": _LIVE,
    "connect_needs_miner": _LIVE,               # row 13
    "export_frequency_list": _LIVE, "export_reading_words": _LIVE, "export_sentence_list": _LIVE,
    "logs": _LIVE, "data_credits": _LIVE, "version": _LIVE,
    "new_cards_a_day": _CONNECT_ROWS, "connect_enabled": _CONNECT_ROWS, "anki_miner": _CONNECT_ROWS,
    "placing_rules": _RULES,
    "library_folders": "app.qt.settings_sources",          # --- SRC W1b: the folders read where they are
    "fresh_library": "app.qt.settings_sources",            # --- K7: *Sort again or start over…*
    "mine_line": _STORE, "soon_line": _STORE, "set_up_again": _STORE,
    "settings_file": "app.qt.settings_io",                 # --- a6: *Export settings…* · *Import settings…*
    "keep_watched": _STORE,                     # --- W-1: the library's *Keep studying watched episodes*
    "new_cards_from": _STORE,                   # --- Kyou-A: the library's *Learn two shows at once* (Mado-PZ2)
    "remove_downloaded_covers": _LIVE,          # --- W3.2 L3
    "connect_tidy": _LIVE,                      # --- Kyou-SH2: *Tidy now*
    "practice_ai": _LIVE,                       # --- A6: the practice server's setup, one Copy per AI app
    "ai_audio": "modules.irodori.qt_settings",  # --- Iro-AA: the AI voice's beta (its switch, Install, Remove)
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


def _first_applies(settings, language, ctx):
    """Q31: whether *Idioms and set phrases* takes part in Junban's reorder — Junban's own rule
    (`reposition.first_applies`, the one its run asks: Japanese, no *Only words marked*
    pick); Junban absent or failing: never (the rows hide)."""
    try:
        from modules.junban.reposition import first_applies
        return bool(first_applies(settings, language))
    except Exception:
        return False


_JUNBAN_FIRST = _all(_JUNBAN_ON, _first_applies)


def _off_list(settings):
    """Kyou-MO: the switch for your own cards not on the list as Junban reads it (`unlisted.choice`: 3.0.17's keys
    while it is unset); "leave" when Junban is absent or failing."""
    try:
        from modules.junban import unlisted
        return unlisted.choice(settings)
    except Exception:
        return "leave"


def _aside(settings, language, ctx):
    return _off_list(settings) == "aside"


ASIDE_TICKS = ("junban_later_flag", "junban_later_suspend")


def _off_list_set(settings):
    """Has the learner (or setup) written the switch itself? Unset, `unlisted.choice` reads 3.0.17's keys."""
    return str(value_of(settings, "junban_off_list") or "").strip().lower() in ("leave", "back", "aside")
_CONNECT = _on("connect_enabled")
_KOE = _all(_module("modules.koe"), lambda settings, language, ctx: "koe_revealed" in ctx)
_YOUTUBE = _module("modules.youtube_downloader")
# Row 13 (laptop fixes): a tool's rows wait until the page's look finds it. *Make cards for me* by the one answer the
# wizard, *Needs you* and Anki Miner's card share (`services.tools_found.make_cards_shown`, B2-7): Anki Miner found, or
# the switch on already (its way off; the switch's own value, `connect_enabled`); without Anki Miner and off, one line
# says what it needs (the wizard's ORDER_OFF, IK-14)
def _connect_switch(settings, language, ctx):
    level = tools_found.INSTALLED if "miner_found" in ctx else tools_found.MISSING
    return tools_found.make_cards_shown(level, _CONNECT(settings, language, ctx))


def _update_check(settings, language, ctx):
    """*Update automatically* shows under *Check for updates* while it is on — the one rule the check obeys."""
    return settings_manager.update_check_on(settings)


def _needs_miner(settings, language, ctx):
    return "looked" in ctx and not _connect_switch(settings, language, ctx)


# --- the review loop's moves (Mado-LT) ------------------------------------------------------------------------------ #
MOVE_FLAGS = tuple(range(1, 8))             # Anki's flags 1 … 7 (red, orange, green, blue, pink, turquoise, purple)
MOVE_ROWS = ("known_from_anki", "loop_swap_flag", "loop_ignore_flag")     # the three move cards, in order


def taken_flags(row, settings):
    """The picks `row` can't take now: the flags the other moves hold (as the reader reads them, `move_flags`) —
    Known's as its terms ("flag:3"), Swap's and Ignore's as numbers."""
    flags = review_loop.move_flags(settings)
    known = set(known_signal.terms(settings))
    if row.id == "known_from_anki":
        return {f"flag:{n}" for n in flags.values()}
    other = flags[review_loop.IGNORE if row.id == "loop_swap_flag" else review_loop.SWAP]
    return {other} | {int(t[5:]) for t in known if t.startswith("flag:")}


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

    # Anki & mining
    _row("anki_connection", "anki", "status"),
    _row("new_cards_a_day", "anki", "custom", ("words_per_day",), bounds=(0, None)),       # P9: Anki's own value
    _row("new_cards_from", "anki", "custom"),          # Kyou-A: the library's option, a switch the store draws
    _row("connect_enabled", "anki", "custom", ("connect_enabled",), when=_connect_switch),  # P5: Connect's switch
    _row("connect_needs_miner", "anki", "status", when=_needs_miner),                        # row 13: until it's found
    _row("mine_line", "anki", "custom", when=_CONNECT, group="from_library"),               # P6: the store's line
    _row("connect_send_grammar", "anki", "toggle", ("connect_send_grammar",), when=_CONNECT),
    # Kantan-SD (the mining model's sentence dial; PROVISIONAL words): which sentence each card is cut from
    _row("connect_sentence_dial", "anki", "choice", ("connect_sentence_dial",), options=("best", "nearest"),
         when=_CONNECT),
    # Zh-C (CLAUDE.md §1): Chinese cards' word audio — the word sent to Google — only while this is on
    _row("connect_zh_word_audio", "anki", "toggle", ("connect_zh_word_audio",), when=_all(_CONNECT, _zh)),
    _row("connect_open_anki", "anki", "choice", ("connect_open_anki",), options=(False, True), when=_CONNECT),
    _row("connect_backlog_cap", "anki", "number", ("connect_backlog_cap",), when=_CONNECT, bounds=(0, 5000)),
    _row("connect_tidy", "anki", "action", sub=True, when=_CONNECT),        # Kyou-SH2: *Tidy now* (PROVISIONAL)
    _row("connect_trust_timing", "anki", "toggle", ("connect_trust_timing",), when=_CONNECT),
    # Mado-LT (3.0.18; WL mock 04, PROVISIONAL words): *Your daily loop* — the three moves, one formula each: the move =
    # what you do to its card in Anki. Known is *Count as known in Anki* (Kotoba-WS2: *Count suspended cards as known*
    # folded in; one key, always shown — with Make cards for me and Automation on, Connect's signal reads every card in
    # the picked states, off the known-words sync reads the studied ones, `anki_sync.counted_suspended`), moved here
    # from Known words' More options (one home). Swap and Ignore: a suspended card's flag, read only while Connect is
    # on (`anki_sync.read_known_signal`); a flag one move holds is never another's pick (`options`), and the reader
    # decides what a clash means (`review_loop.move_flags`)
    _row("known_from_anki", "anki", "tablets", ("known_from_anki",), group="loop",
         options=tuple(term for term, _label in settings_values.KNOWN)),
    _row("loop_swap_flag", "anki", "select", ("loop_swap_flag",), options=MOVE_FLAGS, when=_CONNECT),
    _row("loop_ignore_flag", "anki", "select", ("loop_ignore_flag",), options=MOVE_FLAGS, when=_CONNECT),
    # Kantan-B2 (PROVISIONAL): the words whose cards you deleted in Anki, never made again — each with *Allow again*
    _row("unmined_words", "anki", "door", when=_CONNECT, door=("unmined-words",)),
    # Michi-T1 (Sonic 2026-11-17; PROVISIONAL words): every episode's audio heard before its cards, under More options
    _row("connect_spot_every_episode", "anki", "toggle", ("connect_spot_every_episode",), adv=True, when=_CONNECT),
    # Kantan-MO (the mining model, PROVISIONAL words): your level decides which words get cards; this makes cards for
    # every new word of an episode, past your level too (they count toward *Keep up to*) — *Words to make cards from*
    # retired
    _row("connect_every_word", "anki", "toggle", ("connect_every_word",), adv=True, when=_CONNECT),
    # Michi-LP (PROVISIONAL words): how many clips Anki Miner cuts at once — Automatic (this PC's number), or yours
    _row("connect_clip_cuts", "anki", "select", ("connect_clip_cuts",), options=("auto", 1, 2, 3, 4, 5, 6), adv=True,
         when=_CONNECT),
    # Q29: *Your own cards* — first, or in the list's order — and, under it, the tag that marks them (it keeps them
    # from being suspended under either choice, so it is never greyed)
    _row("junban_order_all", "anki", "choice", ("junban_order_all",), options=(False, True), group="in_anki",
         when=_all(_CONNECT, _JUNBAN)),
    _row("junban_own_tag", "anki", "text", ("junban_own_tag",), sub=True, when=_all(_CONNECT, _JUNBAN)),
    # Mado-LT 4: a list, not three side by side — its longest words, and a held fourth (順's *5 minutes after*), set
    # side by side at Large text were wider than a small window's page: opening the fold widened the page past its
    # view (its right edge cut off) and laid and painted it all again
    _row("anki_sync_delay_min", "anki", "select", ("anki_sync_delay_min",), adv=True, group="anki"),
    _row("automation", "anki", "toggle", ("logic.automation",), adv=True),
    _row("journey_settle_s", "anki", "number", ("journey_settle_s",), adv=True, bounds=(0, None)),
    _row("journey_settle_battery_s", "anki", "number", ("journey_settle_battery_s",), adv=True, bounds=(0, None)),
    _row("connect_anki_miner_profile", "anki", "text", ("connect_anki_miner_profile",), adv=True, when=_CONNECT),
    # a7 (DIAGNOSIS 5): the library's own folders are always searched, so a folder here is only an extra
    _row("connect_video_folders", "anki", "list", ("connect_video_folders",), adv=True, when=_CONNECT),
    _row("anki_connect_url", "anki", "text", ("anki_connect_url",), adv=True),

    # Junban (with modules/junban; its rows follow the switch, Put Anki back stays: N3)
    _row("enable_junban", "junban", "toggle", ("enable_junban",), when=_JUNBAN),
    # a9.1: Junban's window has one door, here (it held *Preview order* on a row of its own too)
    _row("junban_scope", "junban", "choice", ("junban_scope",), options=("deck", "all"), when=_JUNBAN_ON,
         door=("junban",), reaches=("junban_deck", "junban_word_fields")),
    # Q31 (Japanese only); the unlocking word first is no switch since the mining model (Kyou-MO: always)
    _row("junban_phrases", "junban", "toggle", ("junban_phrases",), when=_JUNBAN_FIRST),
    # Kyou-MO (F24, PROVISIONAL words): one switch for your own cards not on the list — Leave · At the back · Set
    # aside (Surasura's are never set aside); under Set aside, what it does beside its tag
    _row("junban_off_list", "junban", "choice", ("junban_off_list",), options=("leave", "back", "aside"),
         group="not_on_list", when=_JUNBAN_ON),
    _row("junban_later_flag", "junban", "toggle", ("junban_later_flag",), sub=True, when=_all(_JUNBAN_ON, _aside)),
    _row("junban_later_suspend", "junban", "toggle", ("junban_later_suspend",), sub=True,
         when=_all(_JUNBAN_ON, _aside)),
    _row("junban_auto_reorder", "junban", "toggle", ("junban_auto_reorder",), when=_JUNBAN_ON),
    _row("junban_auto_actions", "junban", "toggle", ("junban_auto_actions",), when=_JUNBAN_ON),
    _row("put_back", "junban", "door", when=_JUNBAN, door=("put-back",)),
    _row("junban_write_frequency", "junban", "toggle", ("junban_write_frequency",), adv=True, when=_JUNBAN_ON),
    _row("junban_frequency_field", "junban", "text", ("junban_frequency_field",), adv=True, sub=True,
         when=_JUNBAN_ON),
    _row("junban_write_freqsort", "junban", "toggle", ("junban_write_freqsort",), adv=True, when=_JUNBAN_ON),
    _row("junban_tag", "junban", "text", ("junban_tag",), adv=True, when=_JUNBAN_ON),
    _row("junban_tag_markers", "junban", "toggle", ("junban_tag_markers",), adv=True, when=_JUNBAN_ON),
    # IK-4: ✦ ⚖ 📖 as glyph tablets, each picked one ticked (Q31's rule: never a choice's vein)
    _row("junban_only_markers", "junban", "tablets", ("junban_only_markers",), options=("star", "lopsided", "reading"),
         adv=True, when=_JUNBAN_ON),
    _row("junban_chunk_size", "junban", "number", ("junban_chunk_size",), adv=True, when=_JUNBAN_ON, bounds=(1, None)),

    # Backfill (with modules/junban; hides with Junban's switch, as in 2.4: N3)
    _row("backfill_patterns", "backfill", "toggle", ("junban_backfill_fills",), options=("patterns",),
         when=_JUNBAN_ON),
    _row("backfill_sentence", "backfill", "toggle", ("junban_backfill_fills",), options=("sentence",),
         when=_JUNBAN_ON),
    _row("backfill_furigana", "backfill", "toggle", ("junban_backfill_fills",), options=("furigana",),
         when=_JUNBAN_ON),
    _row("backfill_pitch", "backfill", "toggle", ("junban_backfill_fills",), options=("pitch",),
         when=_JUNBAN_ON),
    # a9.1: Backfill's window has one door, here (it had three: the deck, Preview, the fields)
    _row("junban_backfill_cards", "backfill", "choice", ("junban_backfill_cards",), options=("all", "new"),
         when=_JUNBAN_ON, door=("backfill",),
         reaches=("junban_backfill_deck", "junban_backfill_fields", "junban_backfill_note_languages")),
    _row("junban_backfill_replace", "backfill", "toggle", ("junban_backfill_replace",), when=_JUNBAN_ON),
    _row("junban_auto_backfill", "backfill", "toggle", ("junban_auto_backfill",), when=_JUNBAN_ON),

    # Level (New words a day went to Anki & mining's *New cards a day*: G1.2-5)
    _row("level", "level", "slider", ("logic.selection.band", "logic.selection.auto")),
    # Kantan-MO (ROLES.md: the list's): one study order for Connect, 順 and the journey (順's *Order* moved here)
    _row("study_order", "level", "choice", ("study_order",), options=("content", "priority")),
    _row("strategy", "level", "choice", ("strategy",), options=("freq", "coverage")),
    _row("target_coverage", "level", "number", ("target_coverage",), sub=True, when=_coverage, bounds=(1, 100)),
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
    _row("count_song_lyrics", "parsing", "toggle", ("logic.count_song_lyrics",)),       # Kotoba-OP: both languages
    _row("how_parsing_works", "parsing", "link"),

    # Content
    _row("target_language", "content", "choice", ("target_language",), options=LANGUAGES),
    _row("soon_line", "content", "custom"),                                                 # P6: the store's line
    _row("keep_watched", "content", "custom"),                     # W-1: the library's option, a toggle the store draws
    # SRC W1b: the store's sources, read where they are; row 32: a summary here, the folders in their own window
    _row("library_folders", "content", "custom", door=("library-folders",)),
    _row("fresh_library", "content", "custom"),                       # K7: the library set aside, the folders read again
    # Sonic 2026-11-05 (the mock's rows): what ▶ opens a file with, what finishing does to its cards — each its name
    # on one line, its choices under it (`STACKED`); the program kept beside the choice (`PROGRAM_ROWS`)
    _row("open_video", "content", "choice", ("open_video",), options=("default", "program"),
         reaches=("open_video_program",)),
    _row("open_book", "content", "choice", ("open_book",), options=("default", "program"),
         reaches=("open_book_program",)),
    _row("finish_cards", "content", "choice", ("finish_cards",), options=settings_manager.FINISH_CARDS),
    _row("split_books_by", "content", "choice", ("split_books_by",), options=("chapters", "even")),
    _row("split_length", "content", "number", ("split_length",), bounds=(1, None)),
    _row("use_every_core", "content", "toggle", ("use_every_core",), adv=True),      # K5 C4: big first reads
    _row("enable_youtube_transcripts", "content", "toggle", ("enable_youtube_transcripts",), when=_YOUTUBE),
    # a9.1: *Add from* went (Extract… and YouTube… are in + Add); *Preview a video…* sits on its switch, shown while on
    _row("enable_youtube_preview", "content", "toggle", ("enable_youtube_preview",), when=_YOUTUBE,
         door=("youtube-preview",)),

    # New arrivals: one line per source, merged per key with the defaults (D30, RD-S16; a default's Wait is kept)
    _row("placing_rules", "arrivals", "custom", ("placing_rules",),
         options=("wait", "top", "after-show", "soon", "goal", "finished")),

    # Connections (docked)
    _row("anki_miner", "connect", "custom", ("connect_anki_miner_path",)),                   # P8: Anki Miner's card
    _row("practice_ai", "connect", "custom"),                  # A6 (H9): Copy, per AI app, for the practice server
    _row("practice_keep_rounds", "connect", "toggle", ("practice_keep_rounds",), sub=True),   # A6: saved rounds
    _row("hato", "connect", "status", group="houseki"),
    _row("jimaku", "connect", "status", when=_never),          # row 13: hidden until hato hands its key over
    _row("anilist", "connect", "status", when=_never),         # row 13: hidden until AniList's import is built
    # --- W3.2 L3: the covers' switch (01 §1.3 C1: off until the user says yes) and *Remove downloaded covers*
    _row("covers_download", "content", "toggle", ("covers_download",)),      # (EZ-4 §2.4: read with Content)
    _row("remove_downloaded_covers", "content", "action", sub=True),
    # --- end W3.2 L3
    _row("more_from_houseki", "connect", "status", when=_never),   # row 13: hidden until a tool is listed there

    # Journey
    _row("theme", "reading", "select", ("theme",),
         options=("Default (Dark)", "Dark Flow", "Midnight (Vibrant)", "Modern Light")),
    _row("open_app_mode", "reading", "toggle", ("open_app_mode",)),
    _row("source_display", "reading", "choice", ("source_display",), options=("off", "icon", "filename", "full")),
    _row("word_search_enabled", "reading", "toggle", ("word_search_enabled",), when=_ja),   # Nadeshiko: Japanese
    _row("anki_backlog_on_generate", "reading", "toggle", ("anki_backlog_on_generate",), when=_anki_set_up),
    _row("line_player", "reading", "toggle", ("line_player",)),            # the journey's line player
    _row("word_search_category", "reading", "choice", ("word_search_category",),
         options=("all", "anime", "liveaction", "youtube"), adv=True, when=_ja),
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
    _row("update_check_enabled", "app", "toggle", ("update_check_enabled",)),
    _row("auto_update_enabled", "app", "toggle", ("auto_update_enabled",), sub=True, when=_update_check),
    _row("telemetry_enabled", "app", "toggle", ("telemetry_enabled",)),
    _row("version", "app", "custom"),                            # a9.1: the version, *Copy*
    _row("logs", "app", "custom"),                               # a9.1: *Data folder* · *Logs*, the one way to both
    _row("data_credits", "app", "custom"),
    _row("settings_file", "app", "custom"),                      # a6: export / import, `settings_io`
    _row("set_up_again", "app", "custom"),                       # S10: the wizard (W3.5 part 3), `settings_store`
    # The Beta list (Michi-LP, PROVISIONAL): one list under one name, each item a switch and one ? line, off as shipped
    # Iro-AA (PROVISIONAL): the AI voice's beta — its switch, then *Install* / *Remove* (`modules.irodori.qt_settings`)
    _row("ai_audio", "app", "custom", ("enable_irodori",), group="beta", when=_module("modules.irodori")),
    _row("connect_low_priority", "app", "toggle", ("connect_low_priority",), when=_CONNECT),     # Michi-LP
    # a9.1 (Sonic: "a button for each that launches"): a block of its own, three buttons evenly across — the server's
    # invite, surasura.dev, the star ask's GitHub (never prompted), each in the browser (*Start over completely* went:
    # Content's *Sort again or start over…* offers it). Never a row of the group above it (`settings_page`)
    _row("surasura", "app", "links", options=("github", "discord", "website")),
)
ROW = {row.id: row for row in ROWS}
# A row that stands stacked always (Sonic 2026-11-05: "One for the term and then a row or 2 for the buttons")
STACKED = ("open_video", "open_book", "finish_cards")
# A choice row whose "program" choice opens a program kept in another key: row id -> that key (its path; the page's
# picker writes it, *Change…* picks again)
PROGRAM_ROWS = {"open_video": "open_video_program", "open_book": "open_book_program"}

# Every setting no row shows, and why (the test holds it to PLACED).
NOT_SHOWN = {
    "app_theme": "one theme in 3.0 (RS-1): no theme picker",
    "onboarding_completed": "state: the first start's",
    "setup_seen": "state: the version whose setup pages were seen (the wizard, WZ-8)",
    "setup_passed": "state: the setup pages saved before setup finished (the wizard)",
    "known_from_anki_chosen": "state: written beside *Count as known in Anki*'s pick (Kantan-B3)",
    "sentence_length_chosen": "state: written beside *Length*'s pick once the sentence table is on (E-LENGTH)",
    "anki_sync_include_suspended": "retired (Kotoba-WS2): folded into *Count as known in Anki*, read once on load",
    "hints_seen": "state: the one-time hints shown, each per library (W-1's first watched mark)",
    "subs_with_hato": "the learner's one yes in Needs you (*Find them with hato*, NS-2; hato's card: 3.0.1's next step)",
    "subs_with_hato_zh": "the Chinese library's one yes in Needs you (*Find them with hato*, Zh-H)",
    "swap_in_place": "off in the tree until FS-2 lands its Settings row (*Swap gives a card a better sentence*)",
    "open_count": "state: a launch counter",
    "paused": "state: the circles paused with a click at the bar's bottom left (Mado-PZ), resumed the same way",
    "skipped_version": "state: its way back is App's *Offer <version> again*",
    "youtube_risk_acknowledged": "the downloader's own one-time ask",
    "add_graduated_words": "retired with Graduate (D23)",
    "connect_mine_words": "retired by the mining model (Kantan-MO): Level + *Cards for every new word*; read once",
    "junban_order": "retired by the mining model (Kantan-MO): the list's *Study order*; read when it isn't saved",
    "index_pool_workers": "speed only: every file's tokens are the same either way",
    "koe_port": "settings.json only: the speech helper's port",
    "irodori_voice": "settings.json only: the AI voice's pack (one ships; Sonic's own voice later is a second pack)",
    "junban_show_tags": "settings.json only: Junban's show labels, off for a positions-only run",
    "junban_replan_preview": "2.x's preview: 3.0 writes the plan always",
    "junban_replan_language": "2.x's preview: 3.0 writes the plan always",
    # Kyou-MO (the mining model): folded into *Your own cards* (`junban_off_list`), read while it is unset, and by 2.x
    "junban_unlisted": "3.0.17's *Cards too rare for your list go*: read only while *Your own cards* is unset",
    "junban_later_tag": "3.0.17's tag tick: *Set aside* always tags; read only while *Your own cards* is unset",
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


# --- Journey v3 (J-SET; SPEC §1.4, the settings table and Sonic's answers 2026-11-22; words PROVISIONAL) ---------- #
# The only Settings since the old page and Zen retired (J-RETIRE, Sonic 2026-11-23; `_journey_rows`, below): the
# Journey section is under App (before App's own section: its links stay the page's last block), the page's rows take
# the old *Look* and *Where a sentence came from* rows' place (the same keys: `journey_settings` is the one place for
# the keys, the choices and how an older value reads), *Up to* is *Sentences per word* (its key and home), and the old
# page's own rows are gone — their keys stay in settings.json, read by the YouTube preview's old page (`_V3_NOT_SHOWN`).
_V3_GONE = ("source_display", "enable_koe", "koe_door")     # Speech's two: the shelved Koe module's (D15)
_V3_ROWS = ("journey_pitch", "journey_meanings", "journey_source", "journey_first_meeting", "journey_word_size",
            "journey_sentence_size", "journey_theme", "journey_keys")           # in the page's ⚙ order (SPEC §1.4)
_OLD_PAGE = "retired from Settings by journey v3 (Sonic 2026-11-22): the YouTube preview's old page still reads it"
_V3_NOT_SHOWN = dict({
    "logic.inline_completed_files": _OLD_PAGE,
    "logic.hide_audio_button": _OLD_PAGE,
    "show_words_per_day": _OLD_PAGE,
}, **{key: "Speak sentences left the journey (D15): the shelved Koe module's own" for key in (
    "enable_koe", "koe_voice", "koe_model", "koe_style", "koe_temperature", "koe_daily_cap")})


def _v3_rows(before):
    """The rows under journey v3, from the rows before it (`before`)."""
    from app.services import journey_settings as J
    new = {
        "journey_pitch": _row("journey_pitch", "reading", "choice", ("journey_pitch",),
                              options=J.CHOICES["journey_pitch"]),
        "journey_meanings": _row("journey_meanings", "reading", "choice", ("journey_meanings",),
                                 options=J.CHOICES["journey_meanings"]),
        "journey_source": _row("journey_source", "reading", "choice", ("source_display",),
                               options=tuple(J.stored("source_display", v) for v in J.CHOICES["source_display"])),
        "journey_first_meeting": _row("journey_first_meeting", "reading", "toggle", ("journey_first_meeting",)),
        "journey_word_size": _row("journey_word_size", "reading", "choice", ("journey_word_size",),
                                  options=J.CHOICES["journey_word_size"]),
        "journey_sentence_size": _row("journey_sentence_size", "reading", "choice", ("journey_sentence_size",),
                                      options=J.CHOICES["journey_sentence_size"]),
        "journey_theme": _row("journey_theme", "reading", "choice", ("theme",),
                              options=tuple(J.stored("theme", v) for v in J.CHOICES["theme"])),
        "journey_keys": _row("journey_keys", "reading", "choice", ("journey_keys",), options=J.CHOICES["journey_keys"]),
    }
    out = []
    for row in before:
        if row.id == "theme":                   # the section's first row: the page's rows in its place
            out += [new[id_] for id_ in _V3_ROWS]
        elif row.id == "max_contexts":          # the same key and home, renamed, 1–10 or All (table Q3, Q8)
            out.append(_row("sentences_per_word", "sentences", "select", (J.SENTENCES,), options=J.SENTENCE_CHOICES))
        elif row.id not in _V3_GONE:
            out.append(row)
    return tuple(out)


def _journey_rows():
    """Journey v3's Settings, made once below from the rows above: the heads, the sections, the rows and NOT_SHOWN."""
    global HEADS, HEAD_OF, SECTIONS, ROWS, ROW, NOT_SHOWN
    HEADS = tuple((head, tuple(s for s in sections if s != "reading")[:-1] + ("reading", sections[-1])
                   if head == "app" else tuple(s for s in sections if s != "reading")) for head, sections in HEADS)
    ROWS = _v3_rows(ROWS)
    NOT_SHOWN = dict(NOT_SHOWN, **_V3_NOT_SHOWN)
    HEAD_OF = {section: head for head, sections in HEADS for section in sections}
    SECTIONS = tuple(Section(id_, _ICONS[id_], S.SECTIONS[id_])
                     for id_ in ("setup",) + tuple(s for _head, sections in HEADS for s in sections))
    ROW = {row.id: row for row in ROWS}


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
    """A key's value as its control shows it: a per-language key this language's entry; a key the journey's page
    shares as the page reads it (an old *Midnight* or *Zen Mode* is Night: `journey_settings.stored_now`)."""
    if key in ("theme", "source_display", "logic.context.max_contexts"):
        from app.services import journey_settings
        return journey_settings.stored_now(settings, key)
    if key == "connect_backlog_cap":
        return settings_values.cap_of(plain(value_of(settings, key)), language)
    if key == "connect_video_folders":
        from app.connect import videos
        return videos.configured({key: plain(value_of(settings, key))}, language)
    found = plain(value_of(settings, key))
    if key == "known_from_anki" and isinstance(found, str):
        found = [found]
    if key == "junban_off_list":                # Kyou-MO: as Junban reads it, 3.0.17's keys while it's unset
        return _off_list(settings)
    if key == "junban_only_markers":            # IK-5: read as Junban reads it, one reader (a hand-edited "Star" is ✦)
        from app.anki_match import normalize_markers
        found = list(normalize_markers(found))
    if key == "placing_rules":                  # merged per key: a source not named keeps its default (SRC W1 fix)
        from app import settings_manager
        found = settings_manager.placing_rules(found)
    return found


def help_line(row, settings, language):
    """The line under `row`'s label now: its help, except *Count as known in Anki* with two states or more picked —
    then it names them, all at once (a7, DIAGNOSIS 3: an "and" that catches almost nothing is never silent) — and, while
    the sync's own *Count suspended cards as known* (not on screen with it, a9.1) counts more than the picks, it says so
    (set there before, or in the Anki window)."""
    if row.id == "known_from_anki":
        held = set(value(row, settings, language) or ())
        picked = [t for t in row.options if t in held]                  # in the setting's order (`known_value`)
        names = S.OPTIONS[row.id]
        flags = [t for t in picked if t.startswith("flag:")]
        line = None
        if len(flags) > 1:                              # a card holds one flag: never two at once (A7S-7)
            line = S.KNOWN_FLAGS.format(flags=" + ".join(names.get(t, t) for t in flags))
        elif len(picked) > 1:
            line = S.KNOWN_ALL_OF.format(states=" + ".join(names.get(t, t) for t in picked))
        if held & set(known_signal.not_known_flags(settings)):  # the loop's Ignore / Swap flag: it counts no card
            line = S.KNOWN_RED_GREEN
        if line:
            return line
    if row.id == "connect_needs_miner":          # what it needs is a state, in sight; what you get behind its ? (S2)
        return S.NEEDS_MINER
    if row.id == "junban_scope" and value(row, settings, language) == "all":
        return S.JUNBAN_ALL_DECKS                # Kantan-T: in sight either way, so a choice never moves the page
    if row.id == "junban_scope":
        # Kantan-T (PROVISIONAL): the deck setup picked, named in sight — *Junban…* beside it changes it; this
        # language's deck only (`setup_wizard.junban_deck`: one recorded for the other language is none here)
        from app.services.setup_wizard import junban_deck
        deck = junban_deck(settings, language)
        return S.JUNBAN_DECK_LINE.format(deck=deck) if deck else S.JUNBAN_NO_DECK
    return row.help


def value(row, settings, language):
    """What `row`'s control shows: one key's value; several keys as {key: value}; a door its window's value for this
    language where it shows one (the decks); the road its side; None for a row that holds no setting."""
    if row.id == "known_road":
        return known_road(settings, language)
    if row.id == "anki_decks":
        return _decks(settings, language)
    if not row.keys:
        return None
    if _member(row):
        return row.options[0] in _held(settings, row.keys[0], language)
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
    if row.id in MOVE_ROWS:                     # Mado-LT: a flag another move holds is never this one's pick
        taken = taken_flags(row, settings)
        return tuple((v, labels.get(v, str(v)), lines.get(v, "")) for v in (row.options or ()) if v not in taken)
    if row.id == "connect_clip_cuts":           # Michi-LP: Automatic names what it picks on this PC now
        from app.connect import power
        labels = dict(labels, auto=S.CLIP_CUTS_AUTO.format(n=power.clip_cuts()))
    if row.id in PROGRAM_ROWS:
        labels = dict(labels, program=program_label(row, settings)[0])
    return tuple((v, labels.get(v, str(v)), lines.get(v, "")) for v in (row.options or ()))


def program(row, settings):
    """The program a `PROGRAM_ROWS` row keeps (its path, stripped), or "" — none chosen (or a hand-edited non-text)."""
    found = value_of(settings, PROGRAM_ROWS[row.id])
    return found.strip() if isinstance(found, str) else ""


def program_label(row, settings):
    """(label, tip) of a `PROGRAM_ROWS` row's "program" choice: the program's name (its file's, without .exe) and its
    path once one is chosen; before, *Choose a program…* and its own tip."""
    path = program(row, settings)
    if not path:
        return S.OPTIONS[row.id]["program"], S.OPTION_TIPS[row.id]["program"]
    return os.path.splitext(os.path.basename(path.replace("\\", "/")))[0] or path, path


def option_tips(row, settings):
    """{value: tip} of a choice's options: the strings table's, a program row's chosen program its path."""
    tips = dict(S.OPTION_TIPS.get(row.id, {}))
    if row.id in PROGRAM_ROWS:
        tips["program"] = program_label(row, settings)[1]
    return tips


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


# Kantan-T: a row whose line reads more than its own keys and reaches — *Which cards*' deck follows 順's recorded pair
# (`setup_wizard.junban_deck`: a deck recorded for the other language is no deck here)
LINE_READS = {"junban_scope": ("junban_replan_deck", "junban_replan_language"),
              # Mado-LT: the moves' picks leave out each other's flags (`options`), Known's line names a clash
              "known_from_anki": ("loop_ignore_flag", "loop_swap_flag"),
              "loop_swap_flag": ("loop_ignore_flag", "known_from_anki"),
              "loop_ignore_flag": ("loop_swap_flag", "known_from_anki")}


def lines_for(keys):
    """The ids of the rows whose line (`help_line`) reads any of `keys` beyond their own (`LINE_READS`)."""
    keys = set(keys)
    return [row_id for row_id, reads in LINE_READS.items() if keys & set(reads)]


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
    """The ids of the visible rows whose label, help, search words, choice labels or door labels hold `query` (NFKC,
    case-folded); an empty query: every visible row."""
    q = _fold(query).strip()
    found = []
    for row in ROWS:
        if not visible(row, settings, language, ctx):
            continue
        labels = [label for _v, label, _l in options(row, settings, language)]
        # a9.1: a door's own words find its row too (one opener per window: *Preview a video…* is on its switch)
        labels += [(S.ROW_DOORS.get(row.id, {}).get(name) or S.DOORS.get(name, ("",)))[0] for name in row.door]
        text = " ".join([row.label, row.help, row.words] + labels)
        if row.section in S.SECTION_TAGS:     # S1: 順 Junban / Backfill find their section's rows, and so does its
            text = " ".join((text, S.SECTION_TAGS[row.section]))      # name typed past its first word (no flood on
            name = _fold(S.SECTIONS[row.section])                     # "order" or "cards")
            if " " in q and name.startswith(q):
                text = " ".join((text, name))
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
    those whose value isn't already what the settings hold (`{}` for none; a row holding no setting never writes; a
    *Count as known in Anki* pick carries `CHOSEN` beside it; with the sentence table on, a *Length* change writes both
    ends and `sentence_length_chosen`);
    `update` None, or for a per-language key the function that re-applies this language's entry onto the file's value at
    write time. `new` by kind: a bool, a value, a number; `range` a (low, high) pair; `tablets` the picks (a list
    value's values, or several bool keys' keys on — a {key: bool} dict too); `list` the items; the level a band name (a hand
    pick: Automatic goes off with it, S2) or {"logic.selection.auto": bool}; the placing rules (source, target) — Wait
    removes a source that has no default — or the whole {source: target} dict."""
    if not row.keys:
        return {}, None
    if row.keys[0] in PER_LANGUAGE:
        return _per_language(row, settings, language, new)
    if _member(row):
        key, held = row.keys[0], _held(settings, row.keys[0], language)
        want = _with_member(key, held, row.options[0], bool(new))
        return ({key: want} if want != held else {}), None
    wanted = _wanted(row, settings, language, new)
    current = value(row, settings, language)
    if len(row.keys) == 1:
        current = {row.keys[0]: current}
    out = {key: v for key, v in wanted.items() if key in row.keys and current.get(key) != v}
    if row.id == "known_from_anki" and row.keys[0] in out:
        # Kantan-B3: a pick, never read as an old default again — written on every pick, even when the loaded settings
        # already say True: the old switch's fold sets it in memory only (Kotoba-WS2F, the keeper's F1)
        out[CHOSEN] = True
    if row.id == "sentence_length" and out and plan_rules.SENTENCE_TABLE >= 1:
        # E-LENGTH: a Length set with the sentence table on is the learner's own, never read as the old default again —
        # the pair as the row shows it (one end changed must not leave the file's other end on an old default)
        out = {key: wanted[key] for key in row.keys}
        out[settings_manager.SENTENCE_LENGTH_CHOSEN] = True
    if row.id in ASIDE_TICKS and out and not _off_list_set(settings) and _off_list(settings) == "aside":
        # Kyou-MO: unset, the switch is read from 3.0.17's ticks — a tick changed under *Set aside* pins it, so the
        # untick never flips it to *Leave*
        out["junban_off_list"] = "aside"
    return out, None


def _member(row):
    """Whether `row` is one value of a list setting as its own switch (Q31: a few independent picks are switches, never
    tablets that read as a pick-one): a toggle naming its value in `options`."""
    return row.kind == "toggle" and bool(row.options)


def _held(settings, key, language):
    found = _one(settings, key, language)
    return list(found) if isinstance(found, (list, tuple)) else []


def _with_member(key, held, member, on):
    """`held` with `member` on or off: the switches' values in their rows' order, then any other value the file holds
    (hand-edited) as it was — never dropped."""
    order = [row.options[0] for row in ROWS if _member(row) and row.keys[0] == key]
    picked = (set(held) - {member}) | ({member} if on else set())
    return [v for v in order if v in picked] + [v for v in held if v not in order]


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
    if row.id == "known_from_anki":
        return {key: settings_values.known_value(set(new or ()))}
    if row.kind == "tablets":
        return {key: [v for v in row.options if v in set(new or ())]}
    if row.id == "placing_rules":
        from app import settings_manager
        rules = _one(settings, key, language)       # merged per key; a hand-edited non-dict: the defaults
        defaults = settings_manager.placing_rules()
        if isinstance(new, Mapping):
            rules = settings_manager.placing_rules(new)        # the whole dict, a source it leaves out its default
            picked = list(new.values())
        else:
            source, target = new
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f"not a source: {source!r}")
            rules[source] = target
            picked = [target]           # another line's hand-edited target stays as written (rules.py skips it)
        unknown = [t for t in picked if t not in row.options]
        if unknown:
            raise ValueError(f"not a place: {unknown[0]!r}")
        # Wait takes a source out — but a source with a default keeps its Wait written, or its default comes back
        return {key: {source: target for source, target in rules.items() if target != "wait" or source in defaults}}
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


# --- Fine-tune (Mado-EZA: EZ-4, EZ2-9; PROVISIONAL): a row's value now and by default, in words, and a reset ------- #
VALUE_KINDS = ("toggle", "choice", "cards", "select", "tablets", "list", "slider", "number", "range", "text")
# What *Reset section* never touches (EZ-4): usage counts, the update check, *Update automatically*, *Run things by
# themselves* and 順's own switch (each sends data or runs by itself: a reset never turns one back on), the language and
# every per-language value (the video folders, the cap). Each keeps its own dot and *back to it*.
RESET_KEEPS = frozenset({"telemetry_enabled", "update_check_enabled", "auto_update_enabled", "logic.automation",
                         "enable_junban", "target_language"}) | frozenset(PER_LANGUAGE)


def holds_value(row):
    """Whether `row` is a value the page draws itself (a switch, a choice, a number…): one a dot, *back to it* and a
    reset read and write. A summary, status, custom, door or link row holds none; the road is the page's state."""
    return row.kind in VALUE_KINDS and bool(row.keys) and row.id != "known_road"


def control_value(row, settings, language):
    """`row`'s value as its control shows it and `change()` takes it: several switches as the keys on, a range as its
    (low, high)."""
    found = value(row, settings, language)
    if row.kind == "tablets" and len(row.keys) > 1:
        return [key for key in row.keys if found.get(key)]
    if row.kind == "range":
        return tuple(found[key] or 0 for key in row.keys)
    return found


def default_value(row, language):
    return control_value(row, defaults(), language)


def is_default(row, settings, language):
    """Whether `row` shows its default (a row holding no value never reads changed; nor one whose hand-edited value
    can't be read: its control shows the default then, `SettingsPage._make_controls`)."""
    if not holds_value(row):
        return True
    try:
        return control_value(row, settings, language) == default_value(row, language)
    except (ValueError, TypeError, KeyError, AttributeError):
        return True


def resets(row):
    """Whether *Reset section* puts `row` back: a value row holding none of `RESET_KEEPS`."""
    return holds_value(row) and not set(row.keys) & RESET_KEEPS


def reset_changes(rows_, settings, language):
    """{key: default} putting back each of `rows_` that `resets` and isn't at its default — one row after another on
    what the ones before wrote, so two switches of one list make one list."""
    from app.services.settings import put, thaw
    work, out = thaw(settings), {}
    for row in rows_:
        if not resets(row) or is_default(row, work, language):
            continue
        try:
            changes, _update = change(row, work, language, default_value(row, language))
        except (ValueError, TypeError):             # a value no default can replace in place: left as it is
            continue
        for key, v in changes.items():
            put(work, key, v)
            out[key] = plain(v)
    return out


def words_of(row, settings, language):
    """`row`'s value in a few words (a closed fold's line, a dot's default): On / Off, a choice's label, the picks, a
    number, a range, a list's count."""
    found = control_value(row, settings, language)
    labels = {v: label for v, label, _line in options(row, settings, language)}
    if row.kind == "toggle":
        return S.TOGGLE_STATE[bool(found)]
    if row.kind == "slider":
        words = labels.get(found[row.keys[0]], str(found[row.keys[0]]))
        return f"{words} · {S.LEVEL_AUTOMATIC}" if found[row.keys[1]] else words
    if row.kind == "range":
        return "–".join(str(n) for n in found)
    if row.kind == "list":
        return S.VALUE_COUNT.format(n=len(found)) if found else S.VALUE_NONE
    if row.kind == "tablets":
        return ", ".join(str(labels.get(v, v)) for v in found) if found else S.PICKED_NONE
    if row.kind == "text":
        return found or S.VALUE_NONE
    if row.kind == "number":
        return str(found)
    return str(labels.get(found, found))


_journey_rows()      # journey v3's Settings (above), the only ones since J-RETIRE
