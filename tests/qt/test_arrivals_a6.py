"""Alpha 6's New arrivals fixes from a tester's notes (#3, #4): a long title's full words in its row's hover, and a pick
in an arrival's ⋯ menu where the menu hangs outside the tray — real Japanese and Chinese titles, on the window's seed.

What a wrong answer would cost a learner:
  * books in a series whose titles differ only at the end (the volume) cut to the same words, with no way to tell
    which row is which before placing one;
  * the tray closing under the hand when an entry of the ⋯ menu is picked outside it (*Goal*), so every placement
    after it means opening the tray again — and the pick's place unclear.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QHelpEvent, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.qt import arrivals, strings
from tests.qt.conftest import wait_until
from tests.qt.test_arrivals import calls, open_tray, settle, tray_of, tray_rows, world  # noqa: F401


# --- #3: the full title in the row's hover ------------------------------------------------------------------------ #
def test_a_rows_hover_carries_its_full_title_and_an_audiobooks_line_after_it():
    # a series whose volumes differ only at the end: the painted row cuts them alike, the hover tells them apart
    vol3 = type("A", (), {"title": "本好きの下剋上 ～司書になるためには手段を選んでいられません～ 第三部 領主の養女 3",
                          "audio": "", "tip": ""})()
    vol4 = type("A", (), {"title": "本好きの下剋上 ～司書になるためには手段を選んでいられません～ 第三部 領主の養女 4",
                          "audio": "🎧 本好きの下剋上 4 (audiobook) — waits for Anki Miner", "tip": ""})()
    assert arrivals.part_tip(vol3, "row") == vol3.title
    assert arrivals.part_tip(vol4, "row") == vol4.title + "\n" + vol4.audio
    zh = type("A", (), {"title": "三体Ⅱ：黑暗森林", "audio": "", "tip": ""})()
    assert arrivals.part_tip(zh, "row") == "三体Ⅱ：黑暗森林"


@pytest.mark.parametrize("language, title", [
    ("ja", "本好きの下剋上 ～司書になるためには手段を選んでいられません～ 第三部「領主の養女」4"),
    ("zh", "三体Ⅱ：黑暗森林（刘慈欣科幻小说系列·第二部·典藏版·上下两册合集）"),
])
def test_hovering_a_tray_row_shows_its_full_title_in_the_windows_bubble_wrapped(world, language, title):
    # the window's bubble, as Current's rows: wrapped at its width, never one line across the window
    seed, win, _w = world(language=language)
    tray = open_tray(win)
    first = next(g for g in tray.groups if g.rows)
    tray.set_groups([g._replace(rows=(g.rows[0]._replace(title=title),) + tuple(g.rows[1:])) if g is first else g
                     for g in tray.groups])
    settle()
    row = next(r for r in tray_rows(win) if r.arrival.title == title)
    vp = tray.view.viewport()
    at = row.rect("row").topLeft() + QPoint(60, 6)                   # on the title (no control there)
    QApplication.sendEvent(vp, QHelpEvent(QEvent.Type.ToolTip, at, vp.mapToGlobal(at)))
    assert wait_until(lambda: win.tooltips.showing() == title, 3)
    assert win.tooltips.bubble.width() < tray.width()                 # wrapped
    QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, QPointF(row.rect("icon").center()),
                                           QPointF(vp.mapToGlobal(row.rect("icon").center())), Qt.MouseButton.NoButton,
                                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert win.tooltips.showing() is None                             # the hand left the title: it goes


# --- #4: a pick in the ⋯ menu outside the tray ------------------------------------------------------------------- #
def _press_on_menu_window(menu, act):
    """A real press and release on the menu's own window (as the system delivers them: to the QWindow first, then
    its widget), at `act`'s centre — the hand moved onto it first, as a learner's does (QMenu ignores a release where
    the cursor hasn't moved since it opened: the release of the click that opened it)."""
    at = menu.actionGeometry(act).center()
    for k in range(8, -1, -1):
        QTest.mouseMove(menu.windowHandle(), at + QPoint(0, 3 * k))
    QTest.mouseClick(menu.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_pick_in_the_menu_where_it_hangs_outside_the_tray_keeps_the_tray_open(world, language, monkeypatch):
    monkeypatch.setattr(arrivals.ArrivalsTray, "_has_show", lambda _self, _a: True)
    seed, win, writer = world(language=language)
    tray = open_tray(win)
    row = tray_rows(win)[0]
    outside = tray.mapToGlobal(QPoint(-300, 10))                      # the menu opened left of the tray, on screen
    menu = tray.menu(row.key, at=outside)
    assert wait_until(lambda: menu.isVisible(), 3)
    act = next(a for a in menu.actions() if a.text() == strings.TRAY_MENU["goal"][0])
    centre = menu.mapToGlobal(menu.actionGeometry(act).center())
    assert not tray.rect().contains(tray.mapFromGlobal(centre))      # the entry lies outside the tray
    _press_on_menu_window(menu, act)
    settle()
    assert calls(writer, "place") == [("place", list(row.arrival.item_ids), {"where": "goal"})]
    assert tray.isVisible()                                           # still open for the next one


def test_a_click_away_still_closes_the_tray_when_no_menu_is_open(world):
    seed, win, _w = world()
    tray = open_tray(win)
    lst = win.page_widgets["current"].list
    at = lst.viewport().mapToGlobal(QPoint(20, 20))
    QTest.mouseClick(win.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     win.mapFromGlobal(at))
    assert wait_until(lambda: not tray.isVisible(), 3)
