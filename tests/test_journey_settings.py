"""Journey v3's page settings (J-SET; SPEC §1.4, the settings table J-SET-TABLE.md, Sonic's answers 2026-11-22):
`app/services/journey_settings.py`, the Settings rows it brings (`settings_catalog.use_v3`) and the door's
`settings/set`.

What a wrong answer would cost: a learner's look or sentences changed by the update with no press of theirs (a value
saved before the page read as something else, or rewritten on load); the YouTube preview — which keeps the old page —
painting the wrong look or badge after a press on the new page; a second key for a setting the app already has; a
setting the page writes that export, import or Reset (Journey) forget; a page press that writes another key, or a
`logic.` key that replaces the whole block. Before the cut-over, anything a learner sees moving at all.

Real settings: a Japanese and a Chinese learner's files saved before journey v3, every retired or re-mapped value in
them (`tests/Test Resources/settings/settings_*_before_journey_v3.json`), and the 3.0 ones beside them.
"""
import json
import os
import sys
import types

import pytest

from app import path_utils, settings_manager, settings_placement
from app.qt import settings_catalog as catalog
from app.services import journey_settings as J
from app.services import settings_io

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "settings")
NEW_KEYS = ("journey_pitch", "journey_meanings", "journey_word_size", "journey_sentence_size", "journey_keys",
            "journey_first_meeting")
SHARED_KEYS = ("theme", "source_display", "logic.context.max_contexts")


def _fixture(name):
    with open(os.path.join(RESOURCES, name), encoding="utf-8") as f:
        return json.load(f)


def _install(settings):
    path = path_utils.get_settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    return path


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture
def v3():
    """Settings as the cut-over shows them, put back after (the import-time variant is the one before it)."""
    J.ON = True
    catalog.use_v3(True)
    yield
    J.ON = False
    catalog.use_v3(False)


@pytest.fixture
def old_ja():
    return _fixture("settings_ja_before_journey_v3.json")


@pytest.fixture
def old_zh():
    return _fixture("settings_zh_before_journey_v3.json")


# --- the keys: six new, three the app already has ---------------------------------------------------------------- #
def test_the_page_has_nine_settings_six_new_keys_and_three_it_shares():
    """The table's count: no new key where one means the same — the theme is `theme`, where-from `source_display`,
    sentences `logic.context.max_contexts` — and every new key a default, a place and no run signature."""
    assert set(J.KEYS) == set(NEW_KEYS) | set(SHARED_KEYS)
    defaults = settings_manager.DEFAULT_SETTINGS
    assert {key: defaults[key] for key in NEW_KEYS} == {
        "journey_pitch": "shown", "journey_meanings": "en", "journey_word_size": "m", "journey_sentence_size": "m",
        "journey_keys": "qwerty", "journey_first_meeting": True}
    for key in NEW_KEYS:
        assert settings_placement.PLACED[key] == "neither", key
    # the table's §2: the page and the data use these names, never a twin
    assert not {"journey_theme", "journey_source", "journey_where_from", "journey_text_size"} & set(defaults)
    assert J.LOOKS == set(J.KEYS) - {"logic.context.max_contexts", "journey_meanings"}


def test_a_fresh_profile_reads_the_pages_defaults():
    """No settings.json yet: Night, Icon, three sentences, the rest as SPEC §1.4 rules them."""
    assert J.page_values(settings_manager.DEFAULT_SETTINGS) == {
        "logic.context.max_contexts": 3, "journey_pitch": "shown", "journey_meanings": "en",
        "source_display": "icon", "journey_word_size": "m", "journey_sentence_size": "m", "theme": "night",
        "journey_keys": "qwerty", "journey_first_meeting": True}


# --- a value saved before the page reads as its new meaning ------------------------------------------------------ #
@pytest.mark.parametrize("saved, reads", [
    ("Dark Flow", "night"), ("Default (Dark)", "night"), ("Midnight (Vibrant)", "night"), ("Zen Mode", "night"),
    ("Modern Light", "light"), ("modern-light", "light"), ("zen-focus", "night"), ("ライト", "night"), (None, "night"),
    (7, "night")])
def test_every_look_saved_before_reads_as_night_but_modern_light(saved, reads):
    """Sonic, 66 d: the five looks become Night · Light — Modern Light is Light, every dark one Night; Zen Mode is
    retired (66 a): Night. A hand-edited value is Night, the default."""
    assert J.page_value({"theme": saved}, "theme") == reads


@pytest.mark.parametrize("saved, reads", [
    ("off", "icon"), ("icon", "icon"), ("filename", "icon_name"), ("full", "icon_name"), ("hover", "hover"),
    ("Icon", "icon"), ("", "icon"), (None, "icon")])
def test_where_a_sentence_came_from_saved_before_reads_as_its_new_choice(saved, reads):
    """Icon stays Icon; File name and Icon + file name become Icon + name; Hidden reads as Icon (PROVISIONAL, table
    Q4: most learners have Hidden only because it was the default)."""
    assert J.page_value({"source_display": saved}, "source_display") == reads


@pytest.mark.parametrize("saved, reads", [(3, 3), (1, 1), (10, 10), (0, 0), (15, 15), (-1, 0), ("5", 3), (True, 3),
                                          (None, 3), (2.5, 3)])
def test_sentences_per_word_reads_its_number_and_0_is_all(saved, reads):
    """0 is All (never "no sentences"); a hand-edited 15 is what the run reads; below 0 reads as All, as the run
    reads it (`plan_rules.context_limit`); a non-number the default."""
    assert J.page_value({"logic": {"context": {"max_contexts": saved}}}, "logic.context.max_contexts") == reads


def test_an_old_japanese_learners_file_reads_as_the_page_reads_it_and_is_never_written(old_ja, v3):
    """Zen Mode, File name, 7 sentences, the retired rows' values: read, never rewritten (settings criteria 11) —
    neither by the page's read nor by Settings' rows."""
    path = _install(old_ja)
    before = _bytes(path)
    settings = settings_manager.load_settings()
    assert J.page_values(settings) == dict(J.page_values(settings_manager.DEFAULT_SETTINGS), **{
        "theme": "night", "source_display": "icon_name", "logic.context.max_contexts": 7})
    row = catalog.ROW
    assert catalog.value(row["journey_theme"], settings, "ja") == J.NIGHT          # shown lit: Night
    assert catalog.words_of(row["journey_theme"], settings, "ja") == "Night"
    assert catalog.value(row["journey_source"], settings, "ja") == "full"          # Icon + name
    assert catalog.value(row["sentences_per_word"], settings, "ja") == 7
    assert _bytes(path) == before
    # the retired rows' values are still the file's (the preview reads them)
    assert settings["zen_limit"] == 75 and settings["show_words_per_day"] is False
    assert settings["logic"]["inline_completed_files"] is True and settings["logic"]["hide_audio_button"] is True


def test_an_old_chinese_learners_midnight_and_hidden_read_as_night_and_icon(old_zh, v3):
    _install(old_zh)
    settings = settings_manager.load_settings()
    assert J.page_value(settings, "theme") == "night"
    assert J.page_value(settings, "source_display") == "icon"
    assert J.page_value(settings, "logic.context.max_contexts") == 10
    # Night and Icon are the defaults: no changed dot on either row
    assert catalog.is_default(catalog.ROW["journey_theme"], settings, "zh")
    assert catalog.is_default(catalog.ROW["journey_source"], settings, "zh")


# --- a press: what it stores ------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", J.KEYS)
def test_every_choice_the_page_offers_stores_a_value_that_reads_back_as_it(key):
    for choice in J.CHOICES[key]:
        stored = J.stored(key, choice)
        holder = {}
        from app.services.settings import put
        put(holder, key, stored)
        assert J.page_value(holder, key) == choice, (key, choice, stored)


def test_night_and_light_store_the_previews_own_names_and_icon_name_stores_full():
    """What the YouTube preview (the old page) reads stays one of its own values."""
    assert J.stored("theme", "night") == "Dark Flow" and J.stored("theme", "light") == "Modern Light"
    assert [J.stored("source_display", v) for v in ("icon", "icon_name", "hover")] == ["icon", "full", "hover"]


@pytest.mark.parametrize("key, value", [
    ("logic.context.max_contexts", 11), ("logic.context.max_contexts", True), ("logic.context.max_contexts", "3"),
    ("logic.context.max_contexts", -1), ("theme", "Dark Flow"), ("theme", "Zen Mode"), ("source_display", "full"),
    ("source_display", "off"), ("journey_pitch", "Shown"), ("journey_word_size", "xl"), ("journey_keys", "azerty"),
    ("journey_keys", {"known": "q", "nope": "x"}), ("journey_keys", {"known": "toolongakeyname"}),
    ("journey_first_meeting", "hidden"), ("journey_first_meeting", 1), ("journey_theme", "night"),
    ("target_language", "zh"), ("logic.automation", False)])
def test_a_key_or_value_the_page_doesnt_offer_is_refused(key, value):
    with pytest.raises(ValueError):
        J.stored(key, value)


def test_your_own_key_map_is_kept_as_you_set_it():
    own = {"known": "j", "ignore": "k", "lookup": ""}
    assert J.stored("journey_keys", own) == own
    assert J.page_value({"journey_keys": own}, "journey_keys") == own


# --- Settings under journey v3 ----------------------------------------------------------------------------------- #
def test_under_v3_journey_sits_under_app_before_apps_own_section_and_the_old_rows_are_gone(v3):
    """Q10 (ruled): App › Journey, the one section, before App's own (its links stay the page's last block); the old
    page's rows Sonic removed (66 c) and Zen (66 a), target days (66 b) leave Settings."""
    assert dict(catalog.HEADS)["app"] == ("connect", "reading", "app")
    assert "reading" not in dict(catalog.HEADS)["library"]
    assert catalog.HEAD_OF["reading"] == "app"
    ids = [row.id for row in catalog.rows("reading")]
    assert ids[:8] == list(catalog._V3_ROWS)
    for gone in ("theme", "source_display", "inline_completed_files", "hide_audio_button", "zen_limit",
                 "enable_koe", "koe_door", "show_words_per_day", "max_contexts"):
        assert gone not in catalog.ROW, gone
    for kept in ("open_app_mode", "word_search_enabled", "word_search_category", "anki_backlog_on_generate",
                 "line_player"):
        assert catalog.ROW[kept].section == "reading", kept
    # Sentences per word: the same key, still in Cards › Sentences beside the other sentence rules (Q8)
    assert catalog.ROW["sentences_per_word"].section == "sentences"
    assert catalog.ROW["sentences_per_word"].keys == ("logic.context.max_contexts",)
    for key in ("logic.inline_completed_files", "logic.hide_audio_button", "zen_limit", "show_words_per_day"):
        assert "YouTube preview" in catalog.NOT_SHOWN[key] or "old page" in catalog.NOT_SHOWN[key], key


def test_before_the_cut_over_settings_is_as_it_was():
    """Inert until J-CUT: the rows, heads and the theme's five choices exactly as before."""
    assert not J.v3()
    assert dict(catalog.HEADS)["library"] == ("content", "arrivals", "parsing", "reading", "export")
    assert catalog.ROW["theme"].options == ("Default (Dark)", "Dark Flow", "Midnight (Vibrant)", "Modern Light",
                                            "Zen Mode")
    assert catalog.ROW["max_contexts"].bounds == (1, 10)
    assert not {"journey_pitch", "sentences_per_word"} & set(catalog.ROW)
    assert catalog.value(catalog.ROW["theme"], {"theme": "Zen Mode"}, "ja") == "Zen Mode"


def test_the_cut_overs_switch_is_the_doors(monkeypatch):
    """One switch: J-CUT turns the door on (`journey_door.ON`), and these rows with it."""
    door = types.ModuleType("app.services.journey_door")
    door.ON = False
    monkeypatch.setitem(sys.modules, "app.services.journey_door", door)
    assert not J.v3()
    door.ON = True
    assert J.v3()


def test_under_v3_every_setting_is_still_in_exactly_one_row_or_not_shown(v3):
    from tests import test_settings_catalog as T
    T.test_every_installed_placed_setting_is_in_exactly_one_row_or_not_shown()
    T.test_every_row_key_and_every_not_shown_key_is_a_placed_setting()
    T.test_every_row_section_choice_and_door_has_its_words()


ROW_PRESS = [   # (row, the press, what it writes) — one key each, the stored value
    ("journey_pitch", "hidden", {"journey_pitch": "hidden"}),
    ("journey_meanings", "yours_en", {"journey_meanings": "yours_en"}),
    ("journey_source", "hover", {"source_display": "hover"}),
    ("journey_source", "full", {"source_display": "full"}),
    ("journey_first_meeting", False, {"journey_first_meeting": False}),
    ("journey_word_size", "l", {"journey_word_size": "l"}),
    ("journey_sentence_size", "s", {"journey_sentence_size": "s"}),
    ("journey_theme", "Modern Light", {"theme": "Modern Light"}),
    ("journey_keys", "dvorak", {"journey_keys": "dvorak"}),
    ("sentences_per_word", 0, {"logic.context.max_contexts": 0}),
    ("sentences_per_word", 10, {"logic.context.max_contexts": 10}),
]


@pytest.mark.parametrize("row_id, press, writes", ROW_PRESS)
def test_each_rows_press_writes_its_own_key_alone(row_id, press, writes, v3):
    settings = settings_manager.load_settings()
    row = catalog.ROW[row_id]
    changes, update = catalog.change(row, settings, "ja", press)
    assert (changes, update) == (writes, None)


@pytest.mark.parametrize("row_id", sorted({r for r, _p, _w in ROW_PRESS}))
def test_a_press_on_what_a_row_already_shows_writes_nothing(row_id, old_ja, v3):
    """An old *Zen Mode* reads as Night: a press on Night writes nothing (no value changed: criteria 11)."""
    _install(old_ja)
    settings = settings_manager.load_settings()
    row = catalog.ROW[row_id]
    assert catalog.change(row, settings, "ja", catalog.control_value(row, settings, "ja")) == ({}, None)


def test_a_choice_not_offered_is_refused_by_the_row(v3):
    settings = settings_manager.load_settings()
    with pytest.raises(ValueError):
        catalog.change(catalog.ROW["journey_theme"], settings, "ja", "Zen Mode")
    with pytest.raises(ValueError):
        catalog.change(catalog.ROW["sentences_per_word"], settings, "ja", 11)


def test_reset_journey_puts_every_row_back_to_its_default(old_ja, v3):
    """Rule 12: Reset (Journey) — every value row of the section that isn't at its default goes back, one write; the
    page's Undo takes that write back (`SettingsPage.reset_section`, tests/qt)."""
    old_ja.update(journey_pitch="hidden", journey_meanings="yours", journey_word_size="l", journey_sentence_size="s",
                  journey_keys={"known": "j"}, journey_first_meeting=False, theme="Modern Light")
    _install(old_ja)
    settings = settings_manager.load_settings()
    out = catalog.reset_changes(catalog.rows("reading"), settings, "ja")
    assert out == {"journey_pitch": "shown", "journey_meanings": "en", "journey_word_size": "m",
                   "journey_sentence_size": "m", "journey_keys": "qwerty", "journey_first_meeting": True,
                   "theme": "Dark Flow", "source_display": "icon", "open_app_mode": False,
                   "word_search_enabled": True, "word_search_category": "all"}
    # Sentences per word lives in Cards › Sentences: its own section's reset
    assert "logic.context.max_contexts" not in out
    assert catalog.reset_changes(catalog.rows("sentences"), settings, "ja")["logic.context.max_contexts"] == 3


# --- export / import carry them (rule 13) ------------------------------------------------------------------------ #
def test_export_and_import_carry_the_pages_settings(tmp_path, old_ja):
    old_ja.update(journey_pitch="hidden", journey_meanings="yours_en", journey_word_size="s",
                  journey_sentence_size="l", journey_keys={"known": "j", "ignore": "k"}, journey_first_meeting=False,
                  theme="Modern Light", source_display="hover")
    old_ja["logic"]["context"]["max_contexts"] = 0
    _install(old_ja)
    out = tmp_path / "設定.json"
    assert settings_io.export(out).ok
    exported = json.loads(out.read_text(encoding="utf-8"))
    for key in NEW_KEYS + ("theme", "source_display"):
        assert exported["settings"][key] == old_ja[key], key
    assert exported["settings"]["logic"]["context"]["max_contexts"] == 0
    plan = settings_io.read(out, isdir=lambda p: True)
    for key in NEW_KEYS:
        assert plan.settings[key] == old_ja[key], key


# --- the door's settings/set and its read-back ------------------------------------------------------------------- #
class _RouteError(Exception):
    def __init__(self, message, kind):
        super().__init__(message)
        self.kind = kind


@pytest.fixture
def door(monkeypatch):
    """`app.door`'s RouteError (J-DOOR's), or a stand-in until it lands."""
    try:
        from app import door as real
        return real
    except ImportError:
        stand_in = types.ModuleType("app.door")
        stand_in.RouteError = _RouteError
        monkeypatch.setitem(sys.modules, "app.door", stand_in)
        import app
        monkeypatch.setattr(app, "door", stand_in, raising=False)
        return stand_in


class _Service:
    def __init__(self, settings):
        self.sets, self._settings = [], settings

    def set(self, changes, update=None, now=False):
        self.sets.append(dict(changes))

    def get(self):
        return self._settings


def test_the_pages_press_writes_its_one_key_through_the_windows_settings(door):
    service = _Service({})
    app = types.SimpleNamespace(services=types.SimpleNamespace(settings=service))
    assert J.door_route({"key": "theme", "value": "light"}, app) == {"saved": "light"}
    assert J.door_route({"key": "source_display", "value": "icon_name", "at": 1}, app) == {"saved": "icon_name"}
    assert J.door_route({"key": "logic.context.max_contexts", "value": 0}, app) == {"saved": 0}
    assert service.sets == [{"theme": "Modern Light"}, {"source_display": "full"}, {"logic.context.max_contexts": 0}]


def test_without_the_window_a_logic_key_is_put_in_its_place_and_the_block_is_kept(door, old_ja):
    path = _install(old_ja)
    J.door_route({"key": "logic.context.max_contexts", "value": 0}, types.SimpleNamespace(services=None))
    settings_manager.flush_keys() if hasattr(settings_manager, "flush_keys") else None
    with open(path, encoding="utf-8") as f:
        on_file = json.load(f)
    assert on_file["logic"]["context"] == dict(old_ja["logic"]["context"], max_contexts=0)
    assert on_file["logic"]["inline_completed_files"] is True
    assert {k: v for k, v in on_file.items() if k != "logic"} == {k: v for k, v in old_ja.items() if k != "logic"}


@pytest.mark.parametrize("body", [{"key": "theme", "value": "Zen Mode"}, {"key": "target_language", "value": "zh"},
                                  {"key": "journey_pitch"}, {}, {"key": ["theme"], "value": "night"}])
def test_the_route_refuses_what_the_page_doesnt_offer_and_writes_nothing(body, door):
    service = _Service({})
    with pytest.raises(door.RouteError) as raised:
        J.door_route(body, types.SimpleNamespace(services=types.SimpleNamespace(settings=service)))
    assert raised.value.kind == "refused"
    assert service.sets == []


def test_the_read_back_gives_every_setting_in_the_pages_words_once_settings_changed(old_zh):
    path = _install(old_zh)
    app = types.SimpleNamespace(services=None)
    values = J.door_state("zh", None, app)
    assert values["theme"] == "night" and values["source_display"] == "icon"
    assert values["logic.context.max_contexts"] == 10
    changed = os.stat(path).st_mtime_ns
    assert J.door_state("zh", changed, app) is None                 # nothing changed since the render
    assert J.door_state("zh", changed - 1, app) == values
