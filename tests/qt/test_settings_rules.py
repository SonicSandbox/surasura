"""Settings › New arrivals › *Where new arrivals go* (W3.3 PR: `app/qt/settings_rules.py`; G1.2-12, D30, the intent
keeper's B2).

What a wrong answer would cost: the placing rules are the user's own settings (D30), and a rule places hato's drops
unattended — a pick that writes the whole settings file, or another key, puts back what another window just saved
(CLAUDE.md §6); a Wait that leaves its source in the dict keeps placing arrivals the user asked to wait (RD-S16: empty =
every arrival waits); an Esc or an unchanged pick that writes is a write the user never made; a hand-edited value that
breaks the page takes every other setting with it; a store read on the GUI thread freezes the window; a line added that
slides the page loses the reader's place (brief §2: "It shouldn't move").

The page is P3's, over the page tests' recorder (`Recorder`: every `set` kept, `land()` / `outside()` tell the
listeners); the sources seen come from a stand-in, and once from a real library store with real subtitles.
"""
import json
import os
import subprocess
import sys
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import settings_manager
from app.qt import settings_rules as sr
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_settings_page import EVERYTHING, ROOT, make_page

CHANNEL = "youtube:UCgx8nPpXp9c0Kv4bUk1D3ng"            # a real-shaped YouTube channel id
RULES = {"hato": "top", CHANNEL: "soon", "bilibili": "finished"}


@pytest.fixture(autouse=True)
def _no_direct_save(monkeypatch):
    def refused(*_a, **_k):
        raise AssertionError("the row saved settings.json itself: only the settings service may")
    monkeypatch.setattr(settings_manager, "save_settings", refused)
    monkeypatch.setattr(settings_manager, "save_keys", refused)


@pytest.fixture
def seen(monkeypatch):
    """The store's read stood in for: the sources it has seen, and the thread each read ran on."""
    calls = []
    found = {"hato", "youtube", CHANNEL, "bilibili", "youtube:UC-lHJZR3Gqxm24_Vd_AJ5Yw"}

    def read(languages=None):
        calls.append(threading.current_thread() is threading.main_thread())
        return set(found)
    monkeypatch.setattr(sr, "sources_seen", read)
    return calls


def rules_page(data=None, size=(1100, 700)):
    page, store = make_page(data or {}, "ja", found=EVERYTHING, size=size)
    rows = sr.attach(page)
    QApplication.processEvents()
    return page, store, rows


def shown(rows):
    """(source, target) of each line, in the column's order."""
    column = rows.box.layout()
    lines = [column.itemAt(i).widget() for i in range(column.count())]
    return [(line.source, line.select.value()) for line in lines if isinstance(line, sr.RuleLine)]


def pick(rows, source, target):
    """What a person's pick does: the line's menu chooses `target`."""
    select = rows.lines[source].select
    select._pick(target)


def open_menu(rows):
    rows.add.click()
    assert wait_until(lambda: rows.menu is not None and rows.add.isEnabled(), 5)
    return rows.menu


def menu_words(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def action(menu, text):
    return next(a for a in menu.actions() if a.text() == text)


# --- the lines -------------------------------------------------------------------------------------------------------- #
def test_one_line_per_rule_hato_first_then_each_source_in_order(qapp):
    page, store, rows = rules_page({"placing_rules": RULES})
    assert shown(rows) == [("hato", "top"), ("bilibili", "finished"), (CHANNEL, "soon")]
    words = rows.lines[CHANNEL].words.text()
    assert words.startswith("From ") and "youtube · channel UCgx8nPpXp9c0Kv4bUk1D3ng" in words
    labels = [label for _v, label in sr.RuleLine.options("top")]
    assert "Top of Current" in labels and "Goal" in labels and not any("HighPriority" in w for w in labels)
    assert store.calls == [], "showing the rules writes nothing"


def test_no_rule_shows_hatos_line_at_wait(qapp):
    page, store, rows = rules_page()
    assert shown(rows) == [("hato", "wait")]
    assert store.calls == []


# --- picking ---------------------------------------------------------------------------------------------------------- #
def test_a_pick_writes_only_placing_rules_with_the_new_dict(qapp):
    page, store, rows = rules_page({"placing_rules": RULES, "words_per_day": 15})
    pick(rows, CHANNEL, "after-show")
    assert store.calls == [({"placing_rules": {"hato": "top", CHANNEL: "after-show", "bilibili": "finished"}}, None)]
    store.land()
    QApplication.processEvents()
    assert store.file["placing_rules"] == {"hato": "top", CHANNEL: "after-show", "bilibili": "finished"}
    assert store.file["words_per_day"] == 15 and len(store.calls) == 1


def test_wait_takes_the_source_out_of_the_dict_and_its_line_goes(qapp):
    page, store, rows = rules_page({"placing_rules": RULES})
    pick(rows, CHANNEL, "wait")
    assert store.calls == [({"placing_rules": {"hato": "top", "bilibili": "finished"}}, None)]
    QApplication.processEvents()
    assert CHANNEL not in rows.lines and [s for s, _t in shown(rows)] == ["hato", "bilibili"]
    store.land()
    QApplication.processEvents()
    assert CHANNEL not in store.file["placing_rules"] and CHANNEL not in rows.lines


def test_wait_on_hato_leaves_its_line_at_wait_and_an_empty_dict_means_every_arrival_waits(qapp):
    page, store, rows = rules_page({"placing_rules": {"hato": "top"}})
    pick(rows, "hato", "wait")
    assert store.calls == [({"placing_rules": {}}, None)]
    store.land()
    QApplication.processEvents()
    assert shown(rows) == [("hato", "wait")] and store.file["placing_rules"] == {}


def test_an_unchanged_pick_writes_nothing(qapp):
    page, store, rows = rules_page({"placing_rules": RULES})
    pick(rows, "hato", "top")                     # the menu's own rule: the shown place again says nothing
    rows.pick("hato", "top")                      # and the row's: a value already there writes nothing
    rows.pick("bilibili", "finished")
    assert store.calls == []


def test_another_windows_write_repaints_only_the_line_that_changed(qapp, monkeypatch):
    page, store, rows = rules_page({"placing_rules": RULES})
    kept = {source: line for source, line in rows.lines.items()}
    painted = []
    real = sr.RuleLine.show_target
    monkeypatch.setattr(sr.RuleLine, "show_target", lambda self, t: (painted.append(self.source), real(self, t)))
    store.outside({"placing_rules": {"hato": "goal", CHANNEL: "soon", "bilibili": "finished", "nicovideo": "top"}})
    QApplication.processEvents()
    assert painted == ["hato", "nicovideo"], "only hato's place moved (and the new source's line was made)"
    assert all(rows.lines[s] is line for s, line in kept.items()), "the other lines are the same widgets"
    assert shown(rows) == [("hato", "goal"), ("bilibili", "finished"), ("nicovideo", "top"), (CHANNEL, "soon")]
    assert store.calls == []
    store.outside({"words_per_day": 30})          # a write of another key: no line touched
    QApplication.processEvents()
    assert painted == ["hato", "nicovideo"]


# --- + rule ----------------------------------------------------------------------------------------------------------- #
def test_plus_rule_offers_only_the_sources_seen_without_a_line_read_off_the_gui_thread(qapp, seen):
    page, store, rows = rules_page({"placing_rules": {CHANNEL: "soon"}})
    menu = open_menu(rows)
    assert seen == [False], "the store is read on a worker"
    assert menu_words(menu) == ["bilibili", "youtube", "youtube · channel UC-lHJZR3Gqxm24_Vd_AJ5Yw", S.RULE_TYPE]
    assert store.calls == []


def test_a_source_picked_from_plus_rule_waits_until_a_place_is_picked(qapp, seen):
    page, store, rows = rules_page({"placing_rules": {"hato": "top"}})
    action(open_menu(rows), "bilibili").trigger()
    QApplication.processEvents()
    assert shown(rows) == [("hato", "top"), ("bilibili", "wait")] and rows.lines["bilibili"].new
    assert store.calls == [], "a line at Wait is no rule: nothing saved"
    assert S.RULE_NEW_TIP.split("{")[0] in rows.lines["bilibili"].select.toolTip()
    pick(rows, "bilibili", "soon")
    assert store.calls == [({"placing_rules": {"hato": "top", "bilibili": "soon"}}, None)]
    assert not rows.lines["bilibili"].new
    assert "bilibili" not in menu_words(open_menu(rows)), "a source with a line is offered no more"


def test_a_source_typed_adds_its_line_and_esc_closes_the_field_adding_nothing(qapp, seen):
    page, store, rows = rules_page()
    action(open_menu(rows), S.RULE_TYPE).trigger()
    QApplication.processEvents()
    field = rows.typing
    assert field is not None and field.toolTip()
    QTest.keyClicks(field.edit, "  youtube:UCabc123  ")
    QTest.keyClick(field.edit, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert rows.typing is None and ("youtube:UCabc123", "wait") in shown(rows)
    action(open_menu(rows), S.RULE_TYPE).trigger()
    QApplication.processEvents()
    QTest.keyClicks(rows.typing.edit, "nicovideo")
    QTest.keyClick(rows.typing.edit, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert rows.typing is None and "nicovideo" not in rows.lines
    assert store.calls == []


def test_esc_closes_plus_rules_menu_adding_and_writing_nothing(qapp, seen):
    page, store, rows = rules_page()
    menu = open_menu(rows)
    assert wait_until(menu.isVisible, 2)
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    assert wait_until(lambda: not menu.isVisible(), 2)
    assert list(rows.lines) == ["hato"] and store.calls == []


def test_a_store_that_cannot_be_read_still_offers_typing(qapp, monkeypatch):
    def broken(languages=None):
        raise OSError("the library store is busy")
    monkeypatch.setattr(sr, "sources_seen", broken)
    page, store, rows = rules_page()
    assert menu_words(open_menu(rows)) == [S.RULE_SEEN_NONE, S.RULE_TYPE]


def test_tooltips_on_every_line_button_field_and_offer(qapp, seen):
    page, store, rows = rules_page({"placing_rules": RULES})
    assert rows.add.toolTip() == S.RULE_ADD_TIP
    for line in rows.lines.values():
        assert line.select.toolTip() and line.select.accessibleName()
    menu = open_menu(rows)
    assert all(a.toolTip() for a in menu.actions() if not a.isSeparator())
    action(menu, S.RULE_TYPE).trigger()
    QApplication.processEvents()
    assert rows.typing.toolTip() and rows.typing.edit.placeholderText()


# --- what the file holds, hand-edited --------------------------------------------------------------------------------- #
@pytest.mark.parametrize("held", [["hato", "top"], "finished", 7, None])
def test_a_placing_rules_that_is_no_dict_shows_hatos_line_and_a_pick_starts_it_afresh(qapp, held):
    page, store, rows = rules_page({"placing_rules": held})
    assert page.built and shown(rows) == [("hato", "wait")]
    pick(rows, "hato", "top")
    assert store.calls == [({"placing_rules": {"hato": "top"}}, None)]


def test_a_target_no_place_names_shows_as_itself_and_stays_when_another_line_is_picked(qapp):
    page, store, rows = rules_page({"placing_rules": {"hato": "graduated", CHANNEL: 3, "": "top", "bilibili": "wait"}})
    assert shown(rows) == [("hato", "graduated"), (CHANNEL, 3)], "an empty source and an explicit Wait are no line"
    assert "graduated" in rows.lines["hato"].select._options[-1][1]
    pick(rows, CHANNEL, "goal")
    assert store.calls == [({"placing_rules": {"hato": "graduated", CHANNEL: "goal", "": "top"}}, None)]
    pick(rows, "hato", "finished")
    assert store.calls[-1][0]["placing_rules"]["hato"] == "finished"


def test_a_missing_key_shows_hatos_line_and_the_whole_page_builds(qapp):
    page, store, rows = rules_page({"placing_rules": {"hato": "top"}})
    store.outside({"placing_rules": "garbage"})
    QApplication.processEvents()
    assert shown(rows) == [("hato", "wait")] and store.calls == []
    assert page.rows["telemetry_enabled"] is not None


# --- the page never moves --------------------------------------------------------------------------------------------- #
def _y(page, widget):
    return widget.mapTo(page.scroll.viewport(), QPoint(0, 0)).y()


def settle(page):
    """The page as a person meets it: its build's last reflow (a wrapped help line laid out at its final width) done
    before the hand arrives, so what moves after is the row's own doing."""
    page.body.layout().invalidate()
    last = None
    for _ in range(50):
        QApplication.processEvents()
        now = (page.body.height(), tuple(v.y() for v in page.rows.values()))
        if now == last:
            return
        last = now


def test_a_line_added_or_taken_away_never_moves_the_page(qapp, seen):
    page, store, rows = rules_page({"placing_rules": RULES}, size=(1100, 600))
    view, bar = page.rows["placing_rules"], page.scroll.verticalScrollBar()
    settle(page)
    # the row in the middle of the view: its top keeps its y
    bar.setValue(view.mapTo(page.body, QPoint(0, 0)).y() - page.scroll.viewport().height() // 2)
    QApplication.processEvents()
    y0 = _y(page, view)
    action(open_menu(rows), "youtube").trigger()
    QApplication.processEvents()
    assert _y(page, view) == y0
    pick(rows, "bilibili", "wait")
    QApplication.processEvents()
    assert _y(page, view) == y0
    # the reader below the row (Connections in view): another window's rules grow the row above, the reader stays
    below = page.rows["anki_miner"]
    bar.setValue(below.mapTo(page.body, QPoint(0, 0)).y() - 40)
    QApplication.processEvents()
    assert _y(page, view) + view.height() < 0 or _y(page, view) < _y(page, below)
    page._last = None
    y_below = _y(page, page._top_widget())
    top = page._top_widget()
    store.outside({"placing_rules": dict(RULES, nicovideo="top", **{"youtube:UCabc": "goal"})})
    QApplication.processEvents()
    assert _y(page, top) == y_below


@pytest.mark.parametrize("scale", ["2"])
def test_the_rows_lines_hold_the_page_at_200_percent_and_text_size_large(scale, tmp_path):
    # Windows' scaling stood in for by QT_SCALE_FACTOR in its own process (the page tests' way)
    env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM="offscreen", SURASURA_FREEZE_MOTION="1",
               SURASURA_TEST_ROOT=str(tmp_path), PYTHONIOENCODING="utf-8")
    code = ("import json\n"
            "from PyQt6.QtCore import QPoint\n"
            "from PyQt6.QtWidgets import QApplication\n"
            "app = QApplication(['settings-rules-scale'])\n"
            "from app.qt import style, bridge\n"
            "style.apply(app, 'night', 'L', 'ja')\n"
            "from tests.qt import test_settings_rules as t\n"
            "t.settings_manager.save_settings = t.settings_manager.save_keys = None\n"
            "page, store, rows = t.rules_page({'placing_rules': t.RULES}, size=(1400, 900))\n"
            "view, bar = page.rows['placing_rules'], page.scroll.verticalScrollBar()\n"
            "t.settle(page)\n"
            "bar.setValue(view.mapTo(page.body, QPoint(0, 0)).y() - page.scroll.viewport().height() // 2)\n"
            "app.processEvents()\n"
            "y0 = t._y(page, view)\n"
            "rows.add_line('nicovideo'); app.processEvents()\n"
            "y1 = t._y(page, view)\n"
            "t.pick(rows, t.CHANNEL, 'wait'); app.processEvents()\n"
            "y2 = t._y(page, view)\n"
            "fits = all(l.select.width() >= l.select.sizeHint().width() and l.words.width() >= "
            "l.words.sizeHint().width() for l in rows.lines.values())\n"
            "bridge.wait_for_workers(10000)\n"
            "dpr = app.primaryScreen().devicePixelRatio()\n"
            "print('RESULT ' + json.dumps([y0, y1, y2, fits, dpr, store.calls[-1][0]]))\n")
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=240)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line is not None, done.stdout[-2000:] + done.stderr[-4000:]
    y0, y1, y2, fits, dpr, last = json.loads(line[len("RESULT "):])
    assert abs(dpr - float(scale)) < 0.01
    assert y0 == y1 == y2 and fits
    assert last == {"placing_rules": {"hato": "top", "bilibili": "finished"}}


# --- the sources a real store has seen ------------------------------------------------------------------------------- #
def test_the_sources_seen_are_each_pairings_producer_and_its_channel():
    assert sr.sources_of([{"producer": "hato"}, {"producer": "youtube", "channel_id": " UCgx8nPpXp9c0Kv4bUk1D3ng "},
                          {}, "not a record", {"producer": "  ", "channel_id": ""}]) == \
        {"hato", "youtube", CHANNEL}


def test_the_sources_seen_come_from_the_library_stores_pairings():
    from tests import connect_helpers as c
    c.library("ja")
    with c.store("ja") as s:
        first = c.drop("ぼっち・ざ・ろっく！ - 05.ja.srt")
        s.register(first, c.record(first, "v5"))
        second = c.drop("ぼっち・ざ・ろっく！ - 06.ja.srt")
        s.register(second, c.record(second, "v6", producer="youtube", channel_id="UCgx8nPpXp9c0Kv4bUk1D3ng"))
    assert sr.sources_seen(("ja", "zh")) == {"hato", "youtube", CHANNEL}, "no Chinese store: it adds nothing"
