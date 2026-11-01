"""The Settings page as data (W3.3 P1: `app/qt/settings_catalog.py`, its strings, `app/credits.py`).

What a wrong answer would cost: a setting no row shows is a setting 3.0 users can no longer change (the RUNBOOK's "every
setting placed"); a key two rows draw is two controls that fight; a `change()` that writes more than its own key, or a
whole per-language value from a stale copy, puts back what another window or program just saved (CLAUDE.md §6, D31); a
row shown in the wrong language or without its module is a switch that does nothing; and the credits are what the data
licences ask for wherever the data goes.

The catalog reads no library: the values here are settings as a user's file holds them (real deck names, real folders).
"""
import ast
import importlib.util
import os
import subprocess
import sys
from types import MappingProxyType

import pytest

from app import settings_manager, settings_placement
from app.connect import settings_values
from app.qt import settings_catalog as catalog
from app.qt import settings_strings as S
from app.services.settings import freeze
from app.settings_placement import OWNERS, PLACED

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVERYTHING = frozenset(catalog.MODULES) | {"koe_revealed", "hato_found", "miner_found"}   # + row 13's tools
NOTHING = frozenset()


def _found(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ImportError:
        return False


# rows that read a module's own data (its options, its defaults) are checked where the modules are: the local --all;
# GitHub's checkout has none of them (the page then never shows those rows: `found` leaves them out)
WITH_MODULES = pytest.mark.skipif(not all(_found(m) for m in catalog.MODULES),
                                  reason="the optional modules aren't in this checkout (the local --all runs this)")


def _placed(key):
    """A key PLACED holds, or one under a placed block (`logic.selection.bands_ppm.rare`)."""
    path = key
    while path not in PLACED and "." in path:
        path = path.rsplit(".", 1)[0]
    return path in PLACED


def _places():
    """key -> where it shows: each row whose keys or door hold it, and NOT_SHOWN. A list setting's switches (Q31: one
    of its values each) are one place — a value two switches draw still counts twice."""
    places, values = {}, {}
    for row in catalog.ROWS:
        for key in row.keys + row.reaches:
            if catalog._member(row):
                held = values.setdefault(key, set())
                first, value = not held, row.options[0]
                if not first and value not in held:
                    held.add(value)
                    continue                         # another value of the same list: the same place
                held.add(value)
            places.setdefault(key, []).append(row.id)
    for key in catalog.NOT_SHOWN:
        places.setdefault(key, []).append("NOT_SHOWN")
    return places


def _switches_apart():
    """AD-8: a list setting's switches (Q31) count as one place only while they sit together — next to each other in
    `ROWS`, in one section; -> {key: [(row id, section)]} for each key whose switches don't."""
    by_key = {}
    for i, row in enumerate(catalog.ROWS):
        if catalog._member(row):
            by_key.setdefault(row.keys[0], []).append((i, row.id, row.section))
    return {key: [(row_id, section) for _i, row_id, section in found] for key, found in by_key.items()
            if len({section for _i, _r, section in found}) > 1
            or [i for i, _r, _s in found] != list(range(found[0][0], found[0][0] + len(found)))}


def test_one_list_settings_switches_sit_together_or_the_one_place_rule_fails(monkeypatch):
    """AD-8: the rule above counts a list's switches as one place; split across sections, or with another row between
    them, they are two places a person has to find — the check says so."""
    assert _switches_apart() == {}
    rows = list(catalog.ROWS)
    i = next(n for n, row in enumerate(rows) if row.id == "backfill_sentence")
    moved = rows.pop(i)
    monkeypatch.setattr(catalog, "ROWS", tuple(rows[:i + 1] + [moved] + rows[i + 1:]))      # a row between them
    assert "junban_backfill_fills" in _switches_apart()
    monkeypatch.setattr(catalog, "ROWS", tuple(rows[:i] + [moved._replace(section="junban")] + rows[i:]))
    assert _switches_apart()["junban_backfill_fills"][-1] == ("backfill_sentence", "junban")


def _owner(key):
    return next((module for prefix, module in OWNERS if key.startswith(prefix)), None)


# --- every setting in exactly one place ------------------------------------------------------------------------------ #
def test_every_installed_placed_setting_is_in_exactly_one_row_or_not_shown():
    """Each setting 3.0 has is reachable from one place: one row's control or door, or NOT_SHOWN with its reason — never
    both, never two rows (A5 found three drawn twice in the mock)."""
    places = _places()
    installed = [key for key in PLACED if settings_placement._installed(key)]
    missing = sorted(key for key in installed if key not in places)
    assert not missing, f"no row shows these and NOT_SHOWN doesn't name them: {missing}"
    twice = {key: where for key, where in places.items() if len(where) > 1}
    assert not twice, f"settings in more than one place: {twice}"
    apart = _switches_apart()
    assert not apart, f"one list setting's switches not side by side in one section: {apart}"
    assert all(reason.strip() for reason in catalog.NOT_SHOWN.values()), "every NOT_SHOWN key says why"
    unfilled = _unfilled_slots()
    assert not unfilled, f"rows the page leaves an empty slot for that nothing fills: {unfilled}"


SLOT_KINDS = ("summary", "status", "custom", "action")      # the page's PLACEHOLDER_KINDS: an empty slot each


def _unfilled_slots():
    """The intent keeper's B2: a summary / status / custom / action row is an empty slot on the page until its package
    fills it, and `reachable()` counts its keys either way — so each names its filler in `catalog.FILLED_BY`: a module
    whose source names the row (it asks `custom_row` / its tables for it), or "pending: <who>". -> {row id: why}."""
    found = {}
    for row in catalog.ROWS:
        if row.kind not in SLOT_KINDS:
            continue
        filler = catalog.FILLED_BY.get(row.id)
        if not filler:
            found[row.id] = "no filler named"
        elif filler.startswith("pending: "):
            if not filler[len("pending: "):].strip():
                found[row.id] = "pending with nobody named"
        else:
            path = os.path.join(ROOT, *filler.split(".")) + ".py"
            if not os.path.exists(path):
                found[row.id] = f"{filler} isn't there"
            else:
                with open(path, encoding="utf-8") as f:
                    if f'"{row.id}"' not in f.read():
                        found[row.id] = f"{filler} never names it"
    stray = set(catalog.FILLED_BY) - {row.id for row in catalog.ROWS if row.kind in SLOT_KINDS}
    found.update({row_id: "named as filled, but it is no slot row" for row_id in stray})
    return found


def test_an_empty_slot_row_with_no_filler_fails_the_placement_proof(monkeypatch):
    """The proof can fail: the placing rules' filler taken out, or pointed at a module that never names the row."""
    assert "placing_rules" not in _unfilled_slots()
    monkeypatch.delitem(catalog.FILLED_BY, "placing_rules")
    assert _unfilled_slots() == {"placing_rules": "no filler named"}
    monkeypatch.setitem(catalog.FILLED_BY, "placing_rules", "app.qt.settings_connect")
    assert _unfilled_slots() == {"placing_rules": "app.qt.settings_connect never names it"}
    monkeypatch.setitem(catalog.FILLED_BY, "placing_rules", "pending: ")
    assert _unfilled_slots() == {"placing_rules": "pending with nobody named"}
    with open(os.path.join(ROOT, "app", "qt", "settings_page.py"), encoding="utf-8") as f:      # Qt-free: its text
        kinds = next(node.value for node in ast.parse(f.read()).body if isinstance(node, ast.Assign)
                     and getattr(node.targets[0], "id", None) == "PLACEHOLDER_KINDS")
    assert ast.literal_eval(kinds) == SLOT_KINDS, "the proof walks the kinds the page leaves a slot for"


def test_every_row_key_and_every_not_shown_key_is_a_placed_setting():
    """A row writing a key PLACED doesn't hold would write a setting nothing reads — or one the signatures don't know."""
    stray = sorted(key for key in _places() if not _placed(key))
    assert not stray, f"keys the catalog names that PLACED doesn't: {stray}"


def test_without_the_optional_modules_every_core_setting_still_has_its_place_and_no_module_row_shows(monkeypatch):
    """A checkout without modules/ (the `_installed` rule): the core settings are all placed, and no row of a module's
    setting shows — Junban and Backfill leave the page and the nav."""
    real_find = settings_placement.importlib.util.find_spec
    monkeypatch.setattr(settings_placement.importlib.util, "find_spec",
                        lambda name, *a: None if name.startswith("modules.") else real_find(name, *a))
    installed = [key for key in PLACED if settings_placement._installed(key)]
    assert "enable_junban" not in installed and "logic.automation" in installed
    places = _places()
    assert all(len(places.get(key, ())) == 1 for key in installed)
    for language in ("ja", "zh"):
        settings = {"target_language": language, "enable_koe": True, "connect_enabled": True}
        shown = [row for row in catalog.ROWS if catalog.visible(row, settings, language, NOTHING)]
        module_keys = sorted(key for row in shown for key in row.keys + row.reaches if _owner(key))
        assert not module_keys, module_keys
        ids = [section.id for section in catalog.sections(settings, language, NOTHING)]
        assert "junban" not in ids and "backfill" not in ids and "setup" in ids


def test_the_catalogs_modules_are_the_ones_the_placement_rule_knows():
    assert set(catalog.MODULES) == {module for _prefix, module in OWNERS} - {"modules.reels"}


# --- doors ------------------------------------------------------------------------------------------------------------ #
def test_every_door_opens_a_registered_window_or_one_still_to_come():
    """A door row's opener is in `windows.OPENERS` or listed as pending with the row that brings it (S8: `pending()` is
    empty at release). A landed one may linger in the table — the rows land on their own clocks — but never a door
    nobody brings."""
    pytest.importorskip("PyQt6")
    from app.qt import windows
    registered = {opener.name for opener in windows.OPENERS}
    waiting = catalog.pending(registered)
    assert "nobody" not in waiting.values(), f"doors no opener holds and nothing brings: {waiting}"
    assert set(catalog.PENDING_OPENERS) <= catalog.doors()
    assert {"frequency-lists", "sentence-dictionary"} <= registered and not set(waiting) & registered


def test_settings_held_by_a_window_are_reached_through_its_door_row():
    """Decks, fields, the deck pickers, Speech's tunables and Backfill's note types live in their windows (🧭 call 3): each
    is listed once, on the door row that opens that window — never in NOT_SHOWN too."""
    reached = {key: row.id for row in catalog.ROWS for key in row.reaches}
    assert reached["anki_sync_decks"] == reached["anki_sync_fields"] == "anki_decks"
    assert reached["junban_word_fields"] == "junban_door"
    assert reached["junban_deck"] == "junban_scope"
    assert reached["junban_backfill_deck"] == "junban_backfill_cards"
    assert reached["junban_backfill_fields"] == reached["junban_backfill_note_languages"] == "backfill_fields"
    for key in ("koe_voice", "koe_model", "koe_style", "koe_temperature", "koe_daily_cap"):
        assert reached[key] == "koe_door" and key not in catalog.NOT_SHOWN
    for row in catalog.ROWS:
        if row.reaches:
            assert row.door, f"{row.id} reaches a window's settings without a door to it"


# --- change(): only the row's own keys ------------------------------------------------------------------------------- #
def _other(row, settings, language):
    """A new value for `row` that differs from what it shows."""
    shown = catalog.value(row, settings, language)
    if row.kind == "slider":
        return "rare" if settings_manager.DEFAULT_SETTINGS["logic"]["selection"]["band"] != "rare" else "core"
    if row.kind == "range":
        low, high = shown.values()
        return (low + 2, high + 3)
    if row.kind == "tablets" and len(row.keys) > 1:
        return [key for key in row.keys if not shown[key]]
    if row.kind == "tablets":
        return [v for v in row.options if v not in shown] or row.options[:1]
    if row.kind == "list":
        return list(shown) + [r"D:\Anime\ひとり・で・ぽっぷ！"]
    if row.id == "placing_rules":
        return ("hato", "top")
    if row.kind in ("choice", "cards", "select"):
        return next(v for v, _l, _line in catalog.options(row, settings, language) if v != shown)
    if row.kind == "toggle" or isinstance(shown, bool):
        return not shown
    if row.kind == "number" or isinstance(shown, int):
        low, high = row.bounds or (0, None)
        return shown - 1 if high is not None and shown >= high else shown + 1
    if row.kind == "text" or isinstance(shown, str) and not row.options and row.id != "anki_sync_delay_min":
        return (shown or "") + "日本語"
    choices = [v for v, _l, _line in catalog.options(row, settings, language)]
    return next(v for v in choices if v != shown)


@WITH_MODULES
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_each_rows_change_writes_its_own_keys_and_nothing_else(language):
    """Every row with a setting, each kind: a new value writes only that row's key(s) — the dotted `logic.` path, never
    the whole block — and the value it gives back reads as the new value."""
    settings = settings_manager.load_settings()
    settings["target_language"] = language
    for row in catalog.ROWS:
        if not row.keys:
            assert catalog.change(row, settings, language, "x") == ({}, None)
            continue
        new = _other(row, settings, language)
        changes, update = catalog.change(row, settings, language, new)
        assert changes, f"{row.id}: a new value wrote nothing"
        assert set(changes) <= set(row.keys), f"{row.id} wrote {sorted(changes)}"
        assert (update is not None) == (row.keys[0] in catalog.PER_LANGUAGE), row.id
        for key in changes:
            assert not key.startswith("logic.") or key.count(".") >= 1 and key != "logic"


@WITH_MODULES
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_value_set_to_what_is_already_there_writes_nothing(language):
    """Picking the value shown, retyping the same number, re-picking the same tablets: nothing to write (S19)."""
    settings = freeze(settings_manager.load_settings())
    for row in catalog.ROWS:
        if not row.keys:
            continue
        shown = catalog.value(row, settings, language)
        if row.kind == "slider":
            shown = {"logic.selection.auto": shown["logic.selection.auto"]}
        elif row.kind == "range":
            shown = tuple(shown.values())
        elif row.kind == "tablets" and len(row.keys) > 1:
            shown = [key for key, on in shown.items() if on]
        elif row.id == "placing_rules":
            shown = dict(shown or {})
        assert catalog.change(row, settings, language, shown) == ({}, None), row.id


def test_toggles_choices_numbers_and_text_write_their_value():
    settings = {"target_language": "ja", "logic": {"names_kanji": True}}
    assert catalog.change(catalog.ROW["names_kanji"], settings, "ja", False) == ({"logic.names_kanji": False}, None)
    assert catalog.change(catalog.ROW["zh_script"], settings, "zh", "t") == ({"zh_script": "t"}, None)
    assert catalog.change(catalog.ROW["connect_mine_words"], settings, "ja", "i1")[0] == {"connect_mine_words": "i1"}
    assert catalog.change(catalog.ROW["connect_open_anki"], settings, "ja", True)[0] == {"connect_open_anki": True}
    assert catalog.change(catalog.ROW["theme"], settings, "ja", "Modern Light")[0] == {"theme": "Modern Light"}
    # a number past its bounds is held to them (2.4's spinbox: 1–10 sentences, a coverage of at most 100 %)
    assert catalog.change(catalog.ROW["max_contexts"], settings, "ja", 40)[0] == {"logic.context.max_contexts": 10}
    assert catalog.change(catalog.ROW["target_coverage"], settings, "ja", "95")[0] == {"target_coverage": 95}
    # typed text is kept without the spaces around it (Junban's own windows strip it too)
    assert catalog.change(catalog.ROW["junban_own_tag"], settings, "ja", "  immersion ")[0] == \
        {"junban_own_tag": "immersion"}
    assert catalog.change(catalog.ROW["new_cards_a_day"], settings, "ja", 20)[0] == {"words_per_day": 20}
    with pytest.raises(ValueError):
        catalog.change(catalog.ROW["zh_script"], settings, "zh", "simplified")       # the mock's word, not a value


def test_the_sentence_length_range_writes_only_the_end_that_moved():
    settings = {"logic": {"context": {"min_chars": 10, "preferred_max_chars": 50}}}
    row = catalog.ROW["sentence_length"]
    assert catalog.change(row, settings, "ja", (12, 50)) == ({"logic.context.min_chars": 12}, None)
    assert catalog.change(row, settings, "ja", (10, 60)) == ({"logic.context.preferred_max_chars": 60}, None)


def test_tablets_write_a_list_in_the_settings_order_or_only_the_bool_keys_that_flipped():
    settings = {"known_from_anki": ["suspended"], "junban_backfill_fills": ["patterns"]}
    # known_from_anki: every state picked must hold ("and"), saved in the setting's own order; none picked is off
    assert catalog.change(catalog.ROW["known_from_anki"], settings, "ja", {"flag:3", "suspended"})[0] == \
        {"known_from_anki": ["suspended", "flag:3"]}
    assert catalog.change(catalog.ROW["known_from_anki"], settings, "ja", [])[0] == {"known_from_anki": []}
    # Q31: a list's values as switches — one switch writes the whole list, its values in the switches' order
    assert catalog.change(catalog.ROW["backfill_sentence"], settings, "ja", True)[0] == \
        {"junban_backfill_fills": ["patterns", "sentence"]}
    assert catalog.change(catalog.ROW["backfill_patterns"], settings, "ja", False)[0] == {"junban_backfill_fills": []}
    assert catalog.change(catalog.ROW["backfill_patterns"], settings, "ja", True) == ({}, None)      # already there
    # a value the file holds that no switch names (hand-edited) is kept, never dropped
    assert catalog.change(catalog.ROW["backfill_sentence"], {"junban_backfill_fills": ["patterns", "glossary"]}, "ja",
                          True)[0] == {"junban_backfill_fills": ["patterns", "sentence", "glossary"]}
    assert catalog.value(catalog.ROW["backfill_sentence"], {"junban_backfill_fills": ["sentence"]}, "ja") is True
    assert catalog.value(catalog.ROW["backfill_patterns"], {"junban_backfill_fills": "patterns"}, "ja") is False
    # IK-4: ✦ ⚖ 📖 are glyph tablets again, written in the marks' order
    assert catalog.change(catalog.ROW["junban_only_markers"], {}, "ja", ["reading", "star"])[0] == \
        {"junban_only_markers": ["star", "reading"]}
    # several bool keys: a switch each, only its own key written
    flag = catalog.ROW["junban_later_flag"]
    assert catalog.change(flag, {}, "ja", True) == ({"junban_later_flag": True}, None)
    assert catalog.change(flag, {"junban_later_flag": True}, "ja", False)[0] == {"junban_later_flag": False}


@WITH_MODULES
def test_your_own_cards_is_one_choice_and_their_tag_sits_under_it_never_greyed():
    """Q29: *Your own cards first* was a tag field and *Order all cards by the list* a toggle — the tag read as the
    "first". Now one choice writes `junban_order_all` (First → False, In your list's order → True) and *Their tag* is
    indented under it, shown under both choices (the tag keeps a card from being suspended either way)."""
    row, tag = catalog.ROW["junban_order_all"], catalog.ROW["junban_own_tag"]
    assert (row.kind, row.keys, row.options, row.group) == ("choice", ("junban_order_all",), (False, True), "in_anki")
    assert (tag.kind, tag.keys, tag.sub) == ("text", ("junban_own_tag",), True)
    ids = [r.id for r in catalog.ROWS]
    assert ids.index("junban_own_tag") == ids.index("junban_order_all") + 1
    labels = [label for _v, label, _l in catalog.options(row, {}, "ja")]
    assert labels == ["First, in the order you made them", "In your list’s order"]
    assert catalog.change(row, {}, "ja", True) == ({"junban_order_all": True}, None)
    assert catalog.change(row, {"junban_order_all": True}, "ja", False) == ({"junban_order_all": False}, None)
    assert catalog.change(row, {"junban_order_all": False}, "ja", False) == ({}, None)
    for order_all in (False, True):
        shown = _shown({"connect_enabled": True, "junban_order_all": order_all}, "ja")
        assert {"junban_order_all", "junban_own_tag"} <= shown, order_all
    assert all(S.OPTION_TIPS["junban_order_all"].get(v) for v in (False, True))     # each choice says what it does
    assert "suspended" in tag.tip and "suspended" in row.tip
    # IK-6: with *Tag the notes I move* filled in, a card of yours that moves is tagged — what never happens to it is
    # Junban's not-on-your-list marking
    for words in (row.help, row.tip):
        assert "never tagged" not in words and "never marked or suspended as not on your list" in words, words


@WITH_MODULES
def test_phrases_and_i_plus_one_first_are_two_switches_for_japanese_not_at_the_back():
    """Q31: one row of two pills under "First" read as pick one; they work together. Two plain switches, each its own
    key, hidden for Chinese and with "At the back" (Junban's reorder uses neither there)."""
    for row_id in ("junban_phrases", "junban_ready_first"):
        row = catalog.ROW[row_id]
        assert (row.kind, row.keys, row.group) == ("toggle", (row_id,), None)
        assert catalog.change(row, {row_id: False}, "ja", True) == ({row_id: True}, None)
        assert catalog.change(row, {row_id: True}, "ja", False) == ({row_id: False}, None)
        for unlisted in ("list_first", "journey"):
            assert row_id in _shown({"junban_unlisted": unlisted}, "ja"), (row_id, unlisted)
        assert row_id not in _shown({"junban_unlisted": "back"}, "ja")
        assert row_id not in _shown({}, "zh")
        assert row_id not in _shown({"enable_junban": False}, "ja")
        # IK-3: Junban's own rule — a marker filter moves only the chosen words, so neither switch is asked then
        assert row_id not in _shown({"junban_only_markers": ["star"]}, "ja")
        assert row_id not in _shown({"junban_only_markers": ["Reading"]}, "ja")      # hand-edited, read as Junban does
        assert row_id in _shown({"junban_only_markers": ["sparkle"]}, "ja")         # no mark Junban knows: no filter
    assert "junban_first" not in catalog.ROW and "junban_first" not in S.ROWS
    assert catalog.ROW["junban_ready_first"].label.startswith("i+1 first: ")


@WITH_MODULES
def test_the_first_switches_ask_junbans_own_rule_and_hide_when_it_cant_be_asked(monkeypatch):
    """IK-3: the page asks `reposition.first_applies` — the one rule the run decides by — never a copy of it; a Junban
    that can't be imported (an optional module, half there) hides both rows, never breaks the page."""
    from modules.junban import reposition
    asked = []
    monkeypatch.setattr(reposition, "first_applies", lambda settings, language: asked.append(language) or False)
    assert "junban_phrases" not in _shown({}, "ja") and asked
    monkeypatch.setitem(sys.modules, "modules.junban.reposition", None)          # an import that fails
    assert not {"junban_phrases", "junban_ready_first"} & _shown({}, "ja")
    assert "junban_order" in _shown({}, "ja")                                    # the rest of Junban's rows stay


@WITH_MODULES
def test_only_words_marked_reads_the_file_as_junbans_filter_does():
    """IK-5: one reader — `anki_match.normalize_markers`, the one Junban filters by — so a hand-edited "Star" shows ✦
    lit (Junban moves only starred words), a mark this version doesn't know shows nothing, a lone string is one mark."""
    row = catalog.ROW["junban_only_markers"]
    assert catalog.value(row, {"junban_only_markers": ["Reading", "star", "sparkle"]}, "ja") == ["star", "reading"]
    assert catalog.value(row, {"junban_only_markers": "lopsided"}, "ja") == ["lopsided"]
    assert catalog.value(row, {"junban_only_markers": 3}, "ja") == []
    assert catalog.value(row, {}, "ja") == []


def test_no_multi_pick_reads_as_a_pick_one():
    """Q31 (IK-1): no multi-pick looks like a pick-one — a tablets row is one list value's picks, each lit one ticked
    and never veined (the control's rule, proven where the page draws them); several bool keys are a switch each; a
    list's switches each name one of its values."""
    tablets = [row for row in catalog.ROWS if row.kind == "tablets"]
    assert all(len(row.keys) == 1 and row.options for row in tablets), [row.id for row in tablets]
    assert {row.id for row in tablets} == {"known_from_anki", "junban_only_markers"}
    member = [row for row in catalog.ROWS if catalog._member(row)]
    assert {row.id for row in member} == {"backfill_patterns", "backfill_sentence"}
    assert all(len(row.options) == 1 for row in member)


def test_a_hand_picked_level_turns_automatic_off_in_the_same_change():
    """S2: with Automatic on, a band picked by hand writes the band and Automatic off together; Automatic alone writes
    only itself."""
    row = catalog.ROW["level"]
    auto_on = {"logic": {"selection": {"band": "occasional", "auto": True}}}
    assert catalog.change(row, auto_on, "ja", "rare")[0] == {"logic.selection.band": "rare",
                                                             "logic.selection.auto": False}
    assert catalog.change(row, auto_on, "ja", "occasional")[0] == {"logic.selection.auto": False}
    manual = {"logic": {"selection": {"band": "rare", "auto": False}}}
    assert catalog.change(row, manual, "ja", "rare") == ({}, None)
    assert catalog.change(row, manual, "ja", {"logic.selection.auto": True})[0] == {"logic.selection.auto": True}
    with pytest.raises(ValueError):
        catalog.change(row, manual, "ja", "Very Rare")                                   # a label, not a band


def test_placing_rules_wait_removes_a_source_without_a_default_and_writes_a_defaults_wait():
    """D30: a line set to Wait leaves the dict, another source's rule stays — but the rules merge per key (SRC W1
    fix), so hato's and the folders' Wait is written (left out, after-show would come back), and what is written is
    the merged dict: a file's {} reads as the defaults, so hato's Wait there moves it."""
    row = catalog.ROW["placing_rules"]
    channel = "youtube:UCgx8nPpXp9c0Kv4bUk1D3ng"
    settings = {"placing_rules": {"hato": "top", channel: "soon"}}
    assert catalog.change(row, settings, "ja", ("hato", "wait"))[0] == \
        {"placing_rules": {"hato": "wait", "source": "after-show", channel: "soon"}}
    assert catalog.change(row, settings, "ja", (channel, "wait"))[0] == \
        {"placing_rules": {"hato": "top", "source": "after-show"}}
    assert catalog.change(row, settings, "ja", ("hato", "after-show"))[0] == \
        {"placing_rules": {"hato": "after-show", "source": "after-show", channel: "soon"}}
    for empty in ({"placing_rules": {}}, {}):                                   # {} and no key: the defaults
        assert catalog.change(row, empty, "ja", ("hato", "after-show")) == ({}, None), "nothing moved"
        assert catalog.change(row, empty, "ja", ("hato", "wait"))[0] == \
            {"placing_rules": {"hato": "wait", "source": "after-show"}}
        assert catalog.change(row, empty, "ja", ("source", "wait"))[0] == \
            {"placing_rules": {"hato": "after-show", "source": "wait"}}
    waiting = {"placing_rules": {"hato": "wait", "source": "after-show"}}
    assert catalog.change(row, waiting, "ja", ("hato", "wait")) == ({}, None)
    # the whole dict handed in is merged too: one naming only a default's own place moved nothing
    assert catalog.change(row, {}, "ja", {"hato": "after-show"}) == ({}, None)
    assert catalog.change(row, {}, "ja", {"hato": "top"})[0] == {"placing_rules": {"hato": "top", "source": "after-show"}}
    assert catalog.value(row, {"placing_rules": {"hato": "top"}}, "ja") == {"hato": "top", "source": "after-show"}
    with pytest.raises(ValueError):
        catalog.change(row, settings, "ja", ("hato", "graduated"))


def test_placing_rules_a_hand_edited_value_never_blocks_a_pick_and_another_lines_target_stays_as_written():
    """A target no place names on one line (hand-edited; `rules.py` skips it) doesn't refuse a pick on another line,
    and stays; a `placing_rules` that isn't a dict reads as the defaults, the pick laid over them; a source that is no
    text is refused."""
    row = catalog.ROW["placing_rules"]
    edited = {"placing_rules": {"youtube:UCgx8nPpXp9c0Kv4bUk1D3ng": "graduated"}}
    assert catalog.change(row, edited, "ja", ("hato", "finished"))[0] == \
        {"placing_rules": {"hato": "finished", "source": "after-show", "youtube:UCgx8nPpXp9c0Kv4bUk1D3ng": "graduated"}}
    assert catalog.change(row, {"placing_rules": ["hato", "top"]}, "ja", ("hato", "top"))[0] == \
        {"placing_rules": {"hato": "top", "source": "after-show"}}
    for source in ("", "  ", None, 3):
        with pytest.raises(ValueError):
            catalog.change(row, {}, "ja", (source, "top"))


def test_a_per_language_cap_keeps_the_other_language_and_merges_onto_the_file_at_write_time():
    """`connect_backlog_cap`: a plain number is every language's; changing Japanese's makes it {"ja", "zh"} keeping
    Chinese's effective cap. The update re-applies only Japanese's entry onto the file's value when written, so a
    Chinese cap another window saved meanwhile is kept (S1, D31)."""
    row = catalog.ROW["connect_backlog_cap"]
    changes, update = catalog.change(row, {"connect_backlog_cap": 300}, "ja", 200)
    assert changes == {"connect_backlog_cap": {"ja": 200, "zh": 300}}
    on_file = {"connect_backlog_cap": {"ja": 300, "zh": 120}, "target_language": "ja"}
    update(on_file)
    assert on_file == {"connect_backlog_cap": {"ja": 200, "zh": 120}, "target_language": "ja"}
    legacy = {"connect_backlog_cap": 250}
    update(legacy)
    assert legacy == {"connect_backlog_cap": {"ja": 200, "zh": 250}}
    nothing = {}
    update(nothing)
    assert nothing == {"connect_backlog_cap": {"ja": 200, "zh": 300}}          # the default, for the other language
    # a dict: Chinese's own entry changes, Japanese's stays; Japanese's value shown as itself
    changes, _ = catalog.change(row, {"connect_backlog_cap": {"ja": 200, "zh": 300}}, "zh", 80)
    assert changes == {"connect_backlog_cap": {"ja": 200, "zh": 80}}
    assert catalog.value(row, {"connect_backlog_cap": {"ja": 200}}, "zh") == 300


def test_per_language_video_folders_keep_the_other_language():
    row = catalog.ROW["connect_video_folders"]
    ja_folder, zh_folder = r"D:\Anime\ひとり・で・ぽっぷ！", r"D:\剧集\云笺传"
    changes, update = catalog.change(row, {"connect_video_folders": [r"D:\Downloads"]}, "ja", [ja_folder])
    assert changes == {"connect_video_folders": {"ja": [ja_folder], "zh": [r"D:\Downloads"]}}
    on_file = {"connect_video_folders": {"ja": [], "zh": [zh_folder]}}
    update(on_file)
    assert on_file == {"connect_video_folders": {"ja": [ja_folder], "zh": [zh_folder]}}
    assert catalog.value(row, {"connect_video_folders": {"zh": [zh_folder]}}, "zh") == [zh_folder]


def test_blank_folder_lines_are_never_written_and_a_list_only_blank_lines_longer_writes_nothing():
    """A folder line left empty (or spaces) is no folder: it is dropped before the compare, so the list shown with one
    blank line more is the same list and nothing is written (S19)."""
    row = catalog.ROW["connect_video_folders"]
    ja_folder = r"D:\Anime\ひとり・で・ぽっぷ！"
    changes, _update = catalog.change(row, {}, "ja", [ja_folder, "", "   "])
    assert changes["connect_video_folders"]["ja"] == [ja_folder]
    held = {"connect_video_folders": {"ja": [ja_folder], "zh": []}}
    assert catalog.change(row, held, "ja", [ja_folder, " "]) == ({}, None)


def test_a_change_never_writes_a_key_outside_its_own_row():
    """A mapping handed in (the level's {auto}, several switches' {key: bool}) that carries a key the row doesn't
    draw: only the row's own keys are written — a stray key would put back what another window saved (D31)."""
    level = catalog.ROW["level"]
    manual = {"logic": {"selection": {"band": "rare", "auto": False}}, "words_per_day": 12}
    assert catalog.change(level, manual, "ja", {"logic.selection.auto": True, "words_per_day": 40})[0] == \
        {"logic.selection.auto": True}
    known = catalog.ROW["known_from_anki"]
    assert set(catalog.change(known, {}, "ja", ["marked"])[0]) == {"known_from_anki"}


def test_values_read_dotted_paths_per_language_entries_and_defaults_from_a_frozen_copy():
    """What the page reads is the settings service's frozen copy: mappings and tuples."""
    settings = freeze({"logic": {"selection": {"band": "rare"}}, "anki_sync_decks": {"ja": ["日本語::Mining"]},
                       "connect_backlog_cap": {"zh": 80}})
    assert isinstance(settings, MappingProxyType)
    assert catalog.value(catalog.ROW["level"], settings, "ja") == {"logic.selection.band": "rare",
                                                                    "logic.selection.auto": False}
    assert catalog.value(catalog.ROW["anki_decks"], settings, "ja") == ["日本語::Mining"]
    assert catalog.value(catalog.ROW["anki_decks"], settings, "zh") == []
    assert catalog.value(catalog.ROW["automation"], settings, "ja") is True             # D29's default: on
    assert catalog.value(catalog.ROW["connect_backlog_cap"], settings, "zh") == 80
    assert catalog.value(catalog.ROW["enable_koe"], settings, "ja") is False            # absent: off
    assert catalog.value(catalog.ROW["known_road"], settings, "ja") == "anki"
    assert catalog.value(catalog.ROW["known_road"], settings, "zh") == "import"


def test_the_sync_choice_shows_a_held_value_outside_the_three_and_keeps_it():
    """S9: 順's "5 minutes after" (5) shows as itself, beside Settings' three, until another is picked."""
    row = catalog.ROW["anki_sync_delay_min"]
    shown = catalog.options(row, {"anki_sync_delay_min": 5}, "ja")
    assert [v for v, _l, _line in shown] == [1, 0, "off", 5]
    assert shown[-1][1] == "5 minutes after"
    assert catalog.change(row, {"anki_sync_delay_min": 5}, "ja", 5) == ({}, None)
    assert catalog.change(row, {"anki_sync_delay_min": 5}, "ja", "off")[0] == {"anki_sync_delay_min": "off"}
    assert row.when is None, "never greyed or hidden (IK-11)"


# --- visible() -------------------------------------------------------------------------------------------------------- #
def _shown(settings, language, ctx=EVERYTHING):
    return {row.id for row in catalog.ROWS if catalog.visible(row, settings, language, ctx)}


def test_check_for_updates_is_an_app_switch_on_by_default_and_update_automatically_sits_under_it():
    """*Check for updates* (Settings → App; Sonic 2026-10-31): its own key, on by default; off hides *Update
    automatically* (nothing is offered to update), which comes back with it."""
    row = catalog.ROW["update_check_enabled"]
    assert (row.section, row.kind, row.keys) == ("app", "toggle", ("update_check_enabled",))
    assert settings_manager.DEFAULT_SETTINGS["update_check_enabled"] is True
    assert catalog.change(row, {}, "ja", False) == ({"update_check_enabled": False}, None)
    app = [r.id for r in catalog.rows("app")]
    assert app.index("auto_update_enabled") == app.index("update_check_enabled") + 1
    assert catalog.ROW["auto_update_enabled"].sub
    for language in ("ja", "zh"):
        assert {"update_check_enabled", "auto_update_enabled"} <= _shown({}, language)
        assert "auto_update_enabled" not in _shown({"update_check_enabled": False}, language)
        assert "update_check_enabled" in _shown({"update_check_enabled": False}, language)


def test_update_check_on_reads_only_a_saved_false_as_off():
    """`settings_manager.update_check_on`: missing, None or a frozen copy read as on (the default); only False is off."""
    on = settings_manager.update_check_on
    assert on({}) and on(None) and on(freeze({"update_check_enabled": True}))
    assert not on({"update_check_enabled": False}) and not on(freeze({"update_check_enabled": False}))


def test_japanese_rows_hide_for_chinese_and_the_script_shows_only_for_chinese():
    japanese_only = {"paren_readings", "names_katakana", "names_recurring", "names_kanji", "names_work_terms",
                     "ignore_names", "phrases_and_titles", "pronoun_bases", "phrase_rows", "exclude_single"}
    assert japanese_only <= _shown({}, "ja") and "zh_script" not in _shown({}, "ja")
    assert not japanese_only & _shown({}, "zh") and "zh_script" in _shown({}, "zh")
    assert "how_parsing_works" in _shown({}, "zh")
    # every Japanese-only setting PLACED names ("analysis:ja") hides for Chinese, and the reverse
    for row in catalog.ROWS:
        places = {PLACED.get(key) for key in row.keys}
        if places == {"analysis:ja"}:
            assert row.id not in _shown({}, "zh"), row.id
        if places == {"analysis:zh"}:
            assert row.id not in _shown({}, "ja"), row.id


@WITH_MODULES
def test_module_rows_hide_without_their_module():
    without = {row for row in _shown({"enable_koe": True}, "ja", frozenset({"koe_revealed"}))}
    for row_id in ("enable_junban", "junban_scope", "put_back", "backfill_patterns", "enable_youtube_transcripts",
                   "enable_youtube_preview", "enable_koe", "koe_door", "setup_cards"):
        assert row_id not in without, row_id
        assert row_id in _shown({"enable_koe": True}, "ja"), row_id


def test_speech_shows_only_once_revealed_in_settings_json():
    """The reveal gate (`koe.is_revealed`: the key present in the file): its module alone shows nothing."""
    assert not {"enable_koe", "koe_door"} & _shown({}, "ja", frozenset(catalog.MODULES))
    assert {"enable_koe", "koe_door"} <= _shown({"enable_koe": False}, "ja", EVERYTHING)


@WITH_MODULES
def test_junban_rows_follow_its_switch_but_put_anki_back_stays_and_backfill_leaves_with_it():
    """N3: the way back from what Surasura did to Anki stays shown with Junban off; Backfill hides with it (2.4)."""
    off = _shown({"enable_junban": False}, "ja")
    assert {"enable_junban", "put_back"} <= off
    assert not {"junban_scope", "junban_order", "junban_door", "junban_chunk_size"} & off
    ids = [section.id for section in catalog.sections({"enable_junban": False}, "ja", EVERYTHING)]
    assert "junban" in ids and "backfill" not in ids
    assert "backfill" in [section.id for section in catalog.sections({}, "ja", EVERYTHING)]


def test_connects_rows_show_only_with_its_switch_on():
    connect_rows = {"connect_mine_words", "mine_line", "connect_send_grammar", "connect_open_anki",
                    "connect_backlog_cap", "known_from_anki", "connect_video_folders", "connect_trust_timing",
                    "junban_own_tag", "junban_order_all", "connect_anki_miner_profile"}
    assert not connect_rows & _shown({}, "ja")
    assert connect_rows <= _shown({"connect_enabled": True}, "ja")
    # the switch itself, the sync minute, the automation switch and the address show either way
    assert {"connect_enabled", "anki_sync_delay_min", "automation", "anki_connect_url"} <= _shown({}, "ja")
    assert "junban_own_tag" not in _shown({"connect_enabled": True}, "ja", frozenset({"koe_revealed"}))


def test_the_coverage_number_shows_only_on_the_coverage_road():
    assert "target_coverage" not in _shown({"strategy": "freq"}, "ja")
    assert "target_coverage" in _shown({"strategy": "coverage"}, "ja")


def test_the_known_words_road_starts_on_anki_with_decks_and_the_page_can_turn_it():
    decks = {"anki_sync_decks": {"ja": ["日本語::Mining"], "zh": []}}
    anki_rows, import_rows = {"anki_decks", "anki_sync_auto", "anki_auto_generate"}, {"known_import"}
    assert anki_rows <= _shown(decks, "ja") and not import_rows & _shown(decks, "ja")
    assert import_rows <= _shown(decks, "zh") and not anki_rows & _shown(decks, "zh")
    turned = _shown(decks, "ja", EVERYTHING | {"road:import"})
    assert import_rows <= turned and not anki_rows & turned
    assert "road:import" not in str(catalog.change(catalog.ROW["known_road"], decks, "ja", "import"))
    assert catalog.change(catalog.ROW["known_road"], decks, "ja", "import") == ({}, None)        # page state


def test_rows_waiting_for_their_owner_and_the_anki_label_without_decks_stay_hidden():
    assert "set_up_again" in _shown({}, "ja")               # its owner landed (W3.5 part 3: `settings_store`)
    assert "anki_backlog_on_generate" not in _shown({}, "ja")
    assert "anki_backlog_on_generate" in _shown({"anki_sync_decks": {"zh": ["中文::挖矿"]}}, "ja")


# --- W3.2 L3: the covers' switch in Connections -------------------------------------------------------------------- #
def test_download_covers_is_a_connections_toggle_writing_only_its_key_and_remove_is_an_action_under_it():
    """The window's spec 01 §1.3 C1: Settings → Connections holds *Download covers* (its own key, nothing else) with
    *Remove downloaded covers* under it — shown in both languages, the switch off or on (old covers can be removed)."""
    row, remove = catalog.ROW["covers_download"], catalog.ROW["remove_downloaded_covers"]
    assert (row.section, row.kind, row.keys) == ("connect", "toggle", ("covers_download",))
    assert (remove.section, remove.kind, remove.keys, remove.sub) == ("connect", "action", (), True)
    ids = [r.id for r in catalog.ROWS]
    assert ids.index("remove_downloaded_covers") == ids.index("covers_download") + 1
    for language in ("ja", "zh"):
        for on in (False, True):
            assert {"covers_download", "remove_downloaded_covers"} <= _shown({"covers_download": on}, language)
    assert catalog.change(row, {"covers_download": False}, "ja", True) == ({"covers_download": True}, None)
    assert catalog.FILLED_BY["remove_downloaded_covers"] == "app.qt.settings_live"
    assert "covers_download" not in catalog.NOT_SHOWN and "covers_download" not in catalog.FILLED_BY
    assert row.help == ("Sends each show's AniList id or name to AniList, and a video's id to YouTube. "
                        "Nothing else.")                                                # what is sent, in one line


def test_anki_miner_card_credits_zero_in_sonics_words_on_two_lines():
    """Sonic's words for Zero, whole (2026-10-30): the line breaks before *He's*, so the card never wraps mid-sentence,
    and Settings search still finds the card by either line. A no-break space keeps ":)" with *love* (an RC capture
    wrapped it onto a line of its own); search folds it to a plain space, so "love :)" typed still finds the card."""
    row = catalog.ROW["anki_miner"]
    assert row.help == ("Makes your cards from your own videos. Free, made by Zero.\n"
                        "He's awesome. Please give him some love :)")
    assert "anki_miner" in catalog.find("made by zero", {}, "ja", EVERYTHING)
    assert "anki_miner" in catalog.find("give him some love", {}, "ja", EVERYTHING)
    assert "anki_miner" in catalog.find("some love :)", {}, "ja", EVERYTHING)


# --- find()------------------------------------------------------------------------------------------------------------ #
def test_find_matches_labels_help_search_words_and_choice_labels():
    assert "ignore_names" in catalog.find("ignore names", {}, "ja", EVERYTHING)
    assert "paren_readings" in catalog.find("ruby", {}, "ja", EVERYTHING)                 # its help line
    assert "word_search_enabled" in catalog.find("Nadeshiko", {}, "ja", EVERYTHING)
    assert "zh_script" in catalog.find("traditional", {}, "zh", EVERYTHING)                # a choice's label
    assert "zh_script" not in catalog.find("traditional", {}, "ja", EVERYTHING)            # not shown for Japanese
    assert "theme" not in catalog.find("sapphire", {}, "ja", EVERYTHING)                    # no theme picker


@WITH_MODULES
def test_find_reads_japanese_and_full_width_letters():
    assert "backfill_patterns" in catalog.find("パターン", {}, "ja", EVERYTHING)
    assert "backfill_sentence" in catalog.find("例文", {}, "ja", EVERYTHING)
    assert "phrase_rows" in catalog.find("腑に落ちる", {}, "ja", EVERYTHING)
    assert catalog.find("ＩＧＮＯＲＥ　ＮＡＭＥＳ", {}, "ja", EVERYTHING) == catalog.find("ignore names", {}, "ja",
                                                                                     EVERYTHING)


def test_an_empty_search_is_every_visible_row_and_a_miss_is_none():
    everything = catalog.find("", {}, "ja", EVERYTHING)
    assert everything == [row.id for row in catalog.ROWS if catalog.visible(row, {}, "ja", EVERYTHING)]
    assert catalog.find("   ", {}, "ja", EVERYTHING) == everything
    assert catalog.find("ｚｚｚ no such setting", {}, "ja", EVERYTHING) == []


def test_reveal_targets_and_written_keys_find_their_rows():
    assert catalog.locate("known") == ("known", None)
    assert catalog.locate("mine_line") == ("anki", "mine_line")
    assert catalog.locate("soon_line") == ("content", "soon_line")
    assert catalog.locate("logic.names_kanji") == ("parsing", "names_kanji")
    assert catalog.locate("koe_voice") == ("reading", "koe_door")
    assert catalog.locate("app_theme") is None
    assert catalog.rows_for(["logic.selection.auto"]) == ["level"]


# --- the strings ------------------------------------------------------------------------------------------------------ #
def test_every_row_section_choice_and_door_has_its_words():
    """Tooltips on every button and toggle (D17); a help line is one line; the readout never says "% known" (S4)."""
    for row in catalog.ROWS:
        assert row.id in S.ROWS and row.tip, row.id
        assert "\n" not in row.label, row.id
        # Anki Miner's card alone: Sonic's two lines for Zero, broken before "He's" (2026-10-30)
        assert "\n" not in row.help or row.id == "anki_miner", row.id
        if row.options and row.kind != "slider":
            labels = S.OPTIONS[row.id]
            assert all(v in labels for v in row.options), row.id
        if row.group:
            assert row.group in S.GROUPS
    for name in catalog.doors():
        assert name in S.DOORS and all(S.DOORS[name]), name
    for section in catalog.SECTIONS:
        assert section.name == S.SECTIONS[section.id]
    words = [w for entry in S.ROWS.values() for w in entry] + [S.LEVEL_READOUT]
    assert not any("% known" in w for w in words)
    assert all(len(catalog.options(catalog.ROW["level"], {}, "ja")) == 7 for _ in (0,))


def test_the_catalog_its_strings_and_the_credits_bring_in_no_qt_tk_or_pandas():
    """The page decides nothing: what a value means is Qt-free code a headless test or tool can import."""
    modules = ["app.qt.settings_catalog", "app.qt.settings_strings", "app.credits", "app.connect.settings_values"]
    probe = (f"import sys, json; [__import__(m) for m in {modules!r}]; "
             "print(json.dumps([m for m in ('tkinter', '_tkinter', 'PyQt6', 'pandas') if m in sys.modules]))")
    proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip().splitlines()[-1] == "[]"


def test_the_tk_panel_still_has_the_moved_values():
    """The pure move: Connect's Tk panel reads the same functions from their Tk-free home."""
    from app.connect import settings_panel
    for name in ("cap_value", "cap_of", "folders_value", "sync_choices", "sync_label", "known_value", "WORDS", "SYNC",
                 "KNOWN", "LANGUAGES"):
        assert getattr(settings_panel, name) is getattr(settings_values, name), name


# --- the credits -------------------------------------------------------------------------------------------------- #
def _credits_before_the_move():
    """DATA_CREDITS as app/main.py held it before W3.3 moved it (git: the newest main.py that defines it)."""
    def defined(text):
        for node in ast.parse(text).body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "DATA_CREDITS" for t in node.targets):
                return ast.literal_eval(node.value)
        return None

    def show(rev):
        proc = subprocess.run(["git", "show", f"{rev}:app/main.py"], cwd=ROOT, capture_output=True, timeout=60)
        return proc.stdout.decode("utf-8") if proc.returncode == 0 else None

    try:
        text = show("HEAD")
        if text is not None and defined(text) is not None:
            return defined(text)
        proc = subprocess.run(["git", "log", "-1", "--format=%H", "-S", 'DATA_CREDITS = """', "--", "app/main.py"],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)
        sha = proc.stdout.strip()
        text = show(f"{sha}^") if sha else None
        return defined(text) if text else None
    except (OSError, subprocess.SubprocessError, SyntaxError, ValueError):
        return None


def test_the_credits_are_2_4s_text_byte_for_byte_and_the_tk_window_still_reads_them():
    from app import credits, dictionary_data
    import app.main as main_module
    before = _credits_before_the_move()
    if before is None:
        pytest.skip("git history isn't readable here")
    assert credits.DATA_CREDITS == before
    assert credits.data_credits() == before.replace("{jmdict}", dictionary_data.JMDICT_CREATED or "unknown")
    assert main_module.DATA_CREDITS is credits.DATA_CREDITS
    assert main_module.data_credits is credits.data_credits


def test_readmes_data_credits_are_all_named_in_the_app():
    """S11: an in-place update ships no README, so the in-app credits must name every source README credits."""
    from app import credits
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    sources = credits.readme_sources(readme)
    assert {"JMdict", "JMnedict", "CC-CEDICT", "Tatoeba"} <= set(sources)
    assert credits.missing_from_credits(readme) == []
    made_up = "## 🙏 Data Credits\n\n- [Kanjidic2](https://www.edrdg.org/) — CC BY-SA 4.0\n\n## 📜License\n"
    assert credits.missing_from_credits(made_up) == ["Kanjidic2"]
    assert credits.missing_from_credits("no credits here") == []


def test_the_licence_line_is_the_licence_files_first_and_copyright_lines(monkeypatch, tmp_path):
    from app import credits, path_utils
    with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    monkeypatch.setattr(credits, "_LICENCE", [])
    assert credits.LICENCE_LINE == f"{lines[0]} · {next(l for l in lines if l.startswith('Copyright'))}"
    # frozen: the program's folder, where README sits; none there -> no line at all, never a guess
    monkeypatch.setattr(credits, "_LICENCE", [])
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Surasura.exe"))
    assert credits.licence_line() == ""
    (tmp_path / "LICENSE").write_text("MIT License\n\nCopyright (c) 2026 SonicSandbox\n\nPermission is hereby…\n",
                                      encoding="utf-8")
    monkeypatch.setattr(credits, "_LICENCE", [])
    assert credits.licence_line() == "MIT License · Copyright (c) 2026 SonicSandbox"


# --- row 13 (laptop fixes): the rows of a tool not here yet hide; a saved value is never touched --------------------- #
LOOKED = EVERYTHING | {"looked"}
NO_MINER = LOOKED - {"miner_found"}


def test_placeholders_for_tools_not_built_yet_never_show_and_download_covers_stays():
    """Row 13: jimaku (*coming with hato*), AniList (*coming later*) and More from Houseki (*coming later*) are words
    with nothing behind them — hidden, whatever is found. Download covers (which does reach AniList) and hato's own
    row stay. The rows stay in the catalog (strings, logos), so nothing they name is lost."""
    for ctx in (LOOKED, frozenset()):
        shown = _shown({}, "ja", ctx)
        assert not {"jimaku", "anilist", "more_from_houseki"} & shown
        assert {"hato", "covers_download", "anki_miner"} <= shown
    assert {"jimaku", "anilist", "more_from_houseki"} <= set(catalog.ROW)


def test_make_cards_for_me_waits_for_anki_miner_as_one_line_that_says_so():
    """Row 13: Anki Miner found → *Make cards for me* (Connect's switch), no needs line. Not found and Connect off →
    the switch hides and one line says it needs Anki Miner (the wizard's ORDER_OFF) — only once the look answered, so
    a learner with Anki Miner never sees it flash. Not found but Connect already on → the switch stays: it is the
    learner's way off, and the saved `connect_enabled` is never flipped by hiding."""
    found = _shown({}, "ja", LOOKED)
    assert "connect_enabled" in found and "connect_needs_miner" not in found
    missing = _shown({}, "ja", NO_MINER)
    assert "connect_enabled" not in missing and "connect_needs_miner" in missing
    before_look = _shown({}, "ja", EVERYTHING - {"miner_found"})
    assert "connect_enabled" not in before_look and "connect_needs_miner" not in before_look
    on = _shown({"connect_enabled": True}, "ja", NO_MINER)
    assert "connect_enabled" in on and "connect_needs_miner" not in on
    assert {"connect_mine_words", "mine_line"} <= on                       # Connect's own rows follow its switch
    row = catalog.ROW["connect_needs_miner"]
    assert row.section == "anki" and row.keys == () and row.label == "Make cards for me"
    assert "Anki Miner" in row.help and row.tip


def test_B2_7_one_look_says_which_tools_are_here_and_one_rule_when_make_cards_is_offered(monkeypatch, tmp_path):
    """B2-7 / IK2-3: hato's and Anki Miner's presence is one look (`services.tools_found`) — Settings' gates, hato's
    row, Needs you and Anki Miner's card ask it — and *Make cards for me* is offered by one rule the wizard shares:
    Anki Miner installed (any fuller look's state but missing), or the switch already on (M3: its way off)."""
    from app import tools_entry
    from app.connect import anki_miner
    from app.qt import settings_live, settings_page
    from app.services import tools_found as T
    monkeypatch.setattr(tools_entry, "read", lambda tool: {"version": "1.2"} if tool == "hato" else None)
    exe = tmp_path / "AnkiMiner.exe"
    exe.write_bytes(b"")
    found = T.tools_found({"connect_anki_miner_path": str(exe)})
    assert found == T.Found(hato=True, miner=T.INSTALLED) and T.hato_version() == "1.2"
    assert settings_page._tools_found({"connect_anki_miner_path": str(exe)}) == {"hato_found", "miner_found"}
    assert settings_live.read_hato() == "1.2"
    monkeypatch.setattr(tools_entry, "read", lambda tool: None)
    monkeypatch.setattr(anki_miner, "find", lambda settings: None)
    assert T.tools_found({}) == T.Found(hato=False, miner=T.MISSING) and settings_page._tools_found({}) == set()

    def broken(_settings):
        raise OSError("stand-in: the look failed")
    monkeypatch.setattr(anki_miner, "find", broken)
    said = []
    assert T.tools_found({}, log=said.append).miner == T.MISSING and said    # absent, and said; never a raise
    # the one scale for a fuller look (the wizard's states, the card's) and the one rule
    assert [T.miner_level(s) for s in (None, "missing", "too-old", "needs-setup", "setup", "ready")] == [
        T.MISSING, T.MISSING, T.INSTALLED, T.INSTALLED, T.INSTALLED, T.READY]
    assert [T.make_cards_shown(level) for level in (T.MISSING, T.INSTALLED, T.READY)] == [False, True, True]
    assert T.make_cards_shown(T.MISSING, on=True)
    # the wizard's answer (WZ-4): ready only, whatever the switch
    assert [T.make_cards_shown(level, ready=True) for level in (T.MISSING, T.INSTALLED, T.READY)] == [
        False, False, True]
    assert not T.make_cards_shown(T.INSTALLED, on=True, ready=True)


# --- a7 (Sonic's alpha 6 try, DIAGNOSIS 3–5): where three of Connect's rows sit, and what they say ------------------- #
CONNECT_ON = {"connect_enabled": True}


def test_count_as_known_in_anki_sits_in_known_words_beside_count_suspended_cards_and_each_names_the_other():
    """DIAGNOSIS 3: *Count as known in Anki* sat in Anki & mining while *Count suspended cards as known* sat in Known
    words saying suspended cards are ones you struggled with — two answers to one question, apart and contradicting.
    Now side by side under *What counts as known*, still shown only with Connect on, and each says what the other
    does."""
    ids = [r.id for r in catalog.ROWS]
    row, suspended = catalog.ROW["known_from_anki"], catalog.ROW["anki_sync_include_suspended"]
    assert (row.section, row.adv, row.kind) == ("known", True, "tablets")
    assert ids.index("known_from_anki") == ids.index("anki_sync_include_suspended") + 1
    assert suspended.group == "counts_as_known" and row.group is None          # under the one group name
    assert "known_from_anki" in _shown(CONNECT_ON, "ja") and "known_from_anki" not in _shown({}, "ja")
    assert "Count as known in Anki" in suspended.tip and "Count suspended cards as known" in row.tip
    assert "every state you pick" in row.help                                   # the "and", in the line itself
    assert "struggled" in suspended.tip and "whenever you suspended them" in suspended.tip
    # A7S-1: the sync reads studied cards only (`-is:new`); the signal reads new ones too — each row says which
    assert "New cards you suspend never count here" in suspended.tip and "New cards count too" in row.tip


def test_count_as_known_in_ankis_line_names_every_state_picked_so_an_and_is_never_silent():
    """His `["suspended", "marked"]` counted only cards both suspended AND marked — almost none — with nothing on the
    page saying so. Two states or more: the line names them, all at once; one or none: the row's own line."""
    row = catalog.ROW["known_from_anki"]
    two = dict(CONNECT_ON, known_from_anki=["suspended", "marked"])
    assert catalog.help_line(row, two, "ja") == "Counts only cards that are Suspended + Marked, all at once"
    flagged = dict(CONNECT_ON, known_from_anki=["flag:4", "marked", "suspended"])
    assert catalog.help_line(row, flagged, "zh") == ("Counts only cards that are Suspended + Marked + Flag 4 (Blue), "
                                                     "all at once")                # in the setting's order
    two_flags = dict(CONNECT_ON, known_from_anki=["flag:3", "suspended", "flag:1"])
    assert catalog.help_line(row, two_flags, "ja") == ("A card has one flag at a time: Flag 1 (Red) + Flag 3 (Green) "
                                                       "counts no card")           # A7S-7: never a match
    for one in (["suspended"], [], "marked", ["suspended", "flag:33"]):        # a term it doesn't know is no state
        assert catalog.help_line(row, dict(CONNECT_ON, known_from_anki=one), "ja") == row.help, one
    assert catalog.help_line(catalog.ROW["connect_backlog_cap"], two, "ja") == catalog.ROW["connect_backlog_cap"].help


def test_words_to_make_cards_from_says_your_list_is_i_plus_one_and_the_rest_and_only_i_plus_one_another_set():
    """DIAGNOSIS 4 (Sonic: "worth mentioning that it is i+1 AND the other stuff so people don't see i+1 and jump on
    it"): `pick.py`'s *Your list* takes every listed word, an i+1 line first; *Only i+1* any word with one, list or not.
    Both Settings (3.0's and 2.x's Tk panel) read one copy of the words."""
    row = catalog.ROW["connect_mine_words"]
    lines = {v: line for v, _label, line in catalog.options(row, CONNECT_ON, "ja")}
    assert lines["list"].startswith("i+1 and more") and "every unknown word on your list" in lines["list"]
    assert "the list's order" in row.tip                  # A7S-2: i+1 picks each card's line, never the words' order
    assert "on your list or not" in lines["i1"] and "The rest get no card" in lines["i1"]
    assert "i+1 lines where it can" in row.help and "Only i+1" in row.help
    assert S.OPTION_LINES[row.id] == {v: line for v, _l, line in settings_values.WORDS}
    assert S.OPTIONS[row.id] == {v: label for v, label, _line in settings_values.WORDS}


def test_more_video_folders_is_an_extra_under_more_options_that_says_the_library_is_always_searched():
    """DIAGNOSIS 5: *Where videos are looked for* asked for folders the library's own already are; it is an extra now,
    for videos kept elsewhere — under Anki & mining's *More options*, with Connect on."""
    row = catalog.ROW["connect_video_folders"]
    assert (row.section, row.adv, row.kind, row.label) == ("anki", True, "list", "More video folders")
    assert "always searched" in row.help and "somewhere else" in row.help
    assert "connect_video_folders" in _shown(CONNECT_ON, "ja") and "connect_video_folders" not in _shown({}, "ja")


@pytest.mark.parametrize("query, row_id", [("where videos", "connect_video_folders"),
                                           ("more video", "connect_video_folders"),
                                           ("suspended", "known_from_anki"),
                                           ("suspended", "anki_sync_include_suspended"),
                                           ("i+1", "connect_mine_words")])
def test_the_moved_rows_are_found_by_search_under_their_old_and_new_words(query, row_id):
    assert row_id in catalog.find(query, CONNECT_ON, "ja", EVERYTHING)
