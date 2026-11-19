"""Fine-tune (Mado-EZA: the Settings redesign's EZ-4 / EZ2-9 / §0.5 — every learner-visible word PROVISIONAL).

What a wrong answer would cost: a search box that scrolls away, so a learner deep in the page can't find a setting
(Sonic, 2026-11-18: "the search bar still there"); a left list that lights a section the learner isn't reading; a
*Reset section* that turns usage counts, the update check, automatic updates or *Run things by themselves* back on after
the learner turned them off, or changes their language or folders (EZ-4: never); a dot on a row the learner never
changed, or a *back to it* that writes another key; a save with no way back (EZ2-9: *Saved · Undo*); a fold line that
moves the page as its values change (brief §2: "It shouldn't move").

Real settings as a learner's file holds them (decks, folders), in Japanese and Chinese; the settings service is the page
tests' recorder (`Recorder`), so nothing touches a real settings.json.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.qt import settings_catalog as catalog
from app.qt import settings_strings as S
from tests.qt.test_settings_page import ALL_ON, change, make_page

# What EZ-4 says a reset never touches: each one turned the other way from its default, so a reset that touched it
# would show in the write
KEPT_OFF = {
    "telemetry_enabled": False, "update_check_enabled": False, "auto_update_enabled": False,
    "logic": {"automation": False}, "enable_junban": False,
}


# --- the heads, the order, the nav following the scroll -------------------------------------------------------- #
def test_the_sections_stand_under_three_heads_cards_library_app_each_once_in_page_order():
    heads = [head for head, _sections in catalog.HEADS]
    assert heads == ["cards", "library", "app"]
    order = [s.id for s in catalog.SECTIONS]
    headed = [section for _head, sections in catalog.HEADS for section in sections]
    assert sorted(headed) == sorted(set(order) - {"setup"})          # every section but Your setup, once
    assert order == ["setup"] + headed                               # the page's order is the heads' order
    assert {S.HEADS[h] for h in heads} == {"Cards", "Library", "App"}
    # the round-1 placing (EZ-4 §2.4): the covers' two rows read with Content
    assert catalog.ROW["covers_download"].section == catalog.ROW["remove_downloaded_covers"].section == "content"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_nav_shows_each_head_above_its_sections_and_hides_a_head_with_none(qapp, language):
    page, store = make_page(ALL_ON, language)
    box = page.nav_panel.layout()
    items = [box.itemAt(i).widget() for i in range(box.count()) if box.itemAt(i).widget() is not None]
    for head, sections in catalog.HEADS:
        label = page.nav_heads[head]
        assert label.text() == S.HEADS[head].upper()
        first = min(items.index(page.nav[s]) for s in sections)
        assert items.index(label) == first - 1                       # just above its first section
        assert label.isVisibleTo(page) == any(page.nav[s].isVisibleTo(page) for s in sections)


def test_the_nav_lights_each_section_as_the_page_is_scrolled_to_it(qapp):
    page, store = make_page(ALL_ON, "ja", size=(1100, 600))
    bar = page.scroll.verticalScrollBar()
    shown = [s.id for s in catalog.SECTIONS if page.slabs[s.id].isVisibleTo(page)]
    assert len(shown) >= 10
    for section_id in shown:
        top = page._y_in_body(page.slabs[section_id])
        if top > bar.maximum():
            continue                                  # the page's last screen: it can't stand at the top
        bar.setValue(top)
        QApplication.processEvents()
        assert [s for s, b in page.nav.items() if b.isChecked()] == [section_id]
    bar.setValue(bar.maximum())                       # the very end: the last section the page reaches is lit
    QApplication.processEvents()
    lit = [s for s, b in page.nav.items() if b.isChecked()]
    assert len(lit) == 1 and shown.index(lit[0]) >= shown.index(max(
        (s for s in shown if page._y_in_body(page.slabs[s]) <= bar.maximum()), key=shown.index))


# --- the search, pinned above the scroll ------------------------------------------------------------------------- #
def test_the_search_stays_in_view_at_every_scroll_position(qapp):
    page, store = make_page(ALL_ON, "ja", size=(1100, 600))
    bar = page.scroll.verticalScrollBar()
    assert bar.maximum() > 1000
    assert not page.scroll.isAncestorOf(page.search)            # it never scrolls: it stands above the page
    where = None
    for value in (0, bar.maximum() // 3, bar.maximum() // 2, bar.maximum()):
        bar.setValue(value)
        QApplication.processEvents()
        at = page.search.mapTo(page, QPoint(0, 0))
        assert page.search.isVisible() and 0 <= at.y() and at.y() + page.search.height() <= page.height()
        assert where is None or at == where
        where = at


def test_slash_focuses_the_search_from_deep_in_the_page_without_moving_it(qapp):
    page, store = make_page(ALL_ON, "ja", size=(1100, 600))
    bar = page.scroll.verticalScrollBar()
    bar.setValue(900)
    page.setFocus()
    QTest.keyClick(page, Qt.Key.Key_Slash)
    assert page.search.edit.hasFocus()
    assert bar.value() == 900                                   # the search was in view: nothing to bring there
    assert store.calls == []


@pytest.mark.parametrize("language, query, row_id", [("ja", "names", "names_katakana"),
                                                     ("zh", "script", "zh_script")])
def test_a_search_typed_deep_in_the_page_shows_its_matches_from_the_top(qapp, language, query, row_id):
    page, store = make_page(ALL_ON, language, size=(1100, 600))
    bar = page.scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    QTest.keyClicks(page.search.edit, query)
    QApplication.processEvents()
    assert bar.value() == 0
    assert page._in_view(page.rows[row_id])
    assert store.calls == []


# --- a changed row's dot, and back to it ------------------------------------------------------------------------- #
def test_at_the_defaults_no_value_row_reads_changed_in_either_language():
    defaults = catalog.defaults()
    for language in ("ja", "zh"):
        changed = [row.id for row in catalog.ROWS if catalog.holds_value(row)
                   and not catalog.is_default(row, defaults, language)]
        assert changed == [], (language, changed)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_changed_row_has_a_dot_whose_hover_names_the_default_and_whose_click_puts_it_back(qapp, language):
    page, store = make_page(dict(ALL_ON, connect_send_grammar=False), language)
    view = page.rows["connect_send_grammar"]
    assert view.dot.isVisibleTo(page)
    tip = view.dot.toolTip()
    assert tip.startswith(S.CHANGED_NAME) and S.TOGGLE_STATE[True] in tip and "• Click" in tip
    # rows at their defaults carry none (the Anki address, Generate's settle: never touched in this file)
    assert not page.rows["anki_connect_url"].dot.isVisibleTo(page)
    assert not page.rows["journey_settle_s"].dot.isVisibleTo(page)
    view.dot.click()
    assert store.calls == [({"connect_send_grammar": True}, None)]       # its own key, nothing else
    store.land()
    assert not view.dot.isVisibleTo(page)
    assert view.controls[0].value() is True


def test_a_per_language_rows_dot_reads_this_languages_entry_and_back_to_it_keeps_the_other(qapp):
    page, store = make_page(ALL_ON, "zh")                       # the cap: ja 40, zh 25 (the default 300)
    view = page.rows["connect_backlog_cap"]
    assert view.dot.isVisibleTo(page)
    view.dot.click()
    (changes, update), = store.calls
    on_file = {"connect_backlog_cap": {"ja": 40, "zh": 25}}
    update(on_file)
    assert on_file["connect_backlog_cap"]["ja"] == 40               # Japanese's own cap stays
    assert catalog.value(catalog.ROW["connect_backlog_cap"], on_file, "zh") == 300


# --- saved at once, with Undo ------------------------------------------------------------------------------------ #
def test_a_rows_change_saves_at_once_and_its_toast_undo_puts_the_old_value_back(qapp):
    page, store = make_page(ALL_ON, "ja")
    view = page.rows["only_i_plus_one"]
    change(view.controls[0], True)
    assert store.calls == [({"only_i_plus_one": True}, None)]
    message, undo = page.last_toast
    assert message == S.SAVED and undo is not None
    store.land()
    store.calls.clear()
    undo()
    assert store.calls == [({"only_i_plus_one": False}, None)]
    store.land()
    assert view.controls[0].value() is False


def test_undo_of_a_per_language_change_puts_back_this_languages_entry_only(qapp):
    page, store = make_page(ALL_ON, "ja")
    view = page.rows["connect_backlog_cap"]
    change(view.controls[0], 120)
    store.land()
    store.calls.clear()
    page.last_toast[1]()
    (changes, update), = store.calls
    on_file = {"connect_backlog_cap": {"ja": 120, "zh": 25}}
    update(on_file)
    assert on_file["connect_backlog_cap"] == {"ja": 40, "zh": 25}


def test_nothing_unchanged_makes_a_toast(qapp):
    page, store = make_page(ALL_ON, "ja")
    view = page.rows["only_i_plus_one"]
    change(view.controls[0], False)                             # the value it already holds
    assert store.calls == [] and page.last_toast is None


# --- Reset section ----------------------------------------------------------------------------------------------- #
def test_reset_never_touches_usage_counts_updates_automation_language_folders_or_a_per_language_value():
    settings = dict(ALL_ON, target_language="zh", **KEPT_OFF)
    for language in ("ja", "zh"):
        for section in catalog.SECTIONS:
            rows = [row for row in catalog.rows(section.id) if catalog.holds_value(row)]
            changes = catalog.reset_changes(rows, settings, language)
            touched = set(changes)
            assert not touched & {"telemetry_enabled", "update_check_enabled", "auto_update_enabled",
                                  "logic.automation", "target_language", "enable_junban"}, (section.id, touched)
            assert not touched & set(catalog.PER_LANGUAGE), (section.id, touched)


def test_reset_puts_a_sections_rows_back_including_two_switches_of_one_list():
    # Backfill's two switches share `junban_backfill_fills`: both flipped, the reset makes one list of both defaults
    settings = {"junban_backfill_fills": ["sentence"], "junban_backfill_replace": True}
    rows = catalog.rows("backfill")
    changes = catalog.reset_changes(rows, settings, "ja")
    defaults = catalog.defaults()
    assert changes == {"junban_backfill_fills": catalog.plain(defaults["junban_backfill_fills"]),
                       "junban_backfill_replace": False}


def test_reset_section_writes_once_keeps_the_exceptions_and_its_undo_puts_every_value_back(qapp):
    data = dict(ALL_ON, **KEPT_OFF, line_player=False, source_display="icon",
                zen_limit=80, enable_koe=False)
    page, store = make_page(data, "ja")
    slab = page.slabs["reading"]
    assert slab.reset.isVisibleTo(page) and slab.reset.isEnabled()
    slab.reset.click()
    (changes, update), = store.calls
    assert update is None
    assert changes == {"line_player": True, "source_display": "off", "zen_limit": 50}
    message, undo = page.last_toast
    assert message == S.RESET_DONE.format(section=S.SECTIONS["reading"])
    store.land()
    assert not slab.reset.isEnabled()                           # nothing left that differs
    store.calls.clear()
    undo()
    assert store.calls == [({"line_player": False, "source_display": "icon", "zen_limit": 80}, None)]
    # the App section: usage counts and both update switches are left as the learner set them
    store.land()
    store.calls.clear()
    app = page.slabs["app"]
    if app.reset.isEnabled():
        app.reset.click()
        for changes, _update in store.calls:
            assert not set(changes) & {"telemetry_enabled", "update_check_enabled", "auto_update_enabled"}


def test_reset_is_greyed_while_nothing_in_its_section_differs_and_writes_nothing(qapp):
    page, store = make_page({}, "ja")
    slab = page.slabs["sentences"]
    assert slab.reset.isVisibleTo(page) and not slab.reset.isEnabled()
    assert slab.reset.toolTip() == S.RESET_NOTHING_TIP
    slab.reset.click()
    assert store.calls == []


# --- a closed fold's values on one line -------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_closed_fold_shows_its_rows_values_on_one_line_and_never_moves_the_page(qapp, language):
    page, store = make_page(ALL_ON, language)
    slab = page.slabs["sentences"]
    words = slab.folded.text()
    max_chars = catalog.ROW["max_chars"]
    assert S.FOLDED_VALUE.format(label=max_chars.label, value="150") in words
    height = slab.more_row.height()
    store.outside({"logic.context.max_chars": 220})
    QApplication.processEvents()
    assert S.FOLDED_VALUE.format(label=max_chars.label, value="220") in slab.folded.text()
    assert slab.more_row.height() == height
    page.fold("sentences")                                      # opened: the rows themselves say it
    assert slab.folded.text() == ""
