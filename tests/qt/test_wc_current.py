"""Work counts on Current (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what a move, a drop, an Undo, a row opened and closed, a wheel notch and the ⋯ menu cost the window — paints and where
they land, rows drawn afresh (`RowDelegate.renders`), widgets made — counted, never timed.

What a wrong answer would cost a learner: a move that repaints the whole list (on the laptop each whole-list paint is a
frame he sees stutter while he drags), a scroll that repaints every row, a ⋯ that builds its menu again each time.

S19's written skip (rows.py `RowsView.set_entries`): a relayout — a row opened or closed, a drop's lines moving — has
Qt's QListView repaint the whole viewport whatever is asked; there the rule is that no row is drawn afresh (every row
from its kept picture), never the area. The window is built once for the file (`work_counts.kept`); every test puts
back what it moved, unmeasured.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.qt import rows, stones
from tests.fixtures import window_seed
from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_drag import UndoingWriter, lift, move_global, open_window, release_global, row_point, settle


@pytest.fixture(scope="module")
def screen(qapp, tmp_path_factory):
    """(seed, win, writer): the window on the synthetic library (Japanese titles), its moves written into the stand-in
    store and undone back, built once for the file."""
    with wc.module_env(tmp_path_factory, "current"):
        key = stones._key(1.0, "M")
        if key not in stones._SHEETS:
            stones._landed(key, stones.build(*key))
        seed = window_seed.build()
        writer = UndoingWriter(seed.library)
        win, services = open_window(qapp, seed, writer)
        wc.kept(win)
        settle(300)
        yield seed, win, writer
        wc.close_kept(win, services)


def lst_of(win):
    return win.page_widgets["current"].list


def keys_of(win):
    return [getattr(e[1], "key", None) for e in lst_of(win).model().entries]


@pytest.fixture(autouse=True)
def _at_rest(screen):
    """Each test from the same place: Current shown, at its top, no row open, the order as the seed made it."""
    seed, win, writer = screen
    win.show_tab("current")
    lst = lst_of(win)
    lst.verticalScrollBar().setValue(0)
    order = keys_of(win)
    settle(150)
    yield
    while writer.saved and keys_of(win) != order:                 # every move a test made, undone back (unmeasured)
        n = len(writer.undone)
        writer.undo()
        assert wait_until(lambda: len(writer.undone) > n, 3)
        settle(150)
        writer.saved.pop()
    if lst.model().open_key is not None:
        i = next(i for i, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) == lst.model().open_key)
        lst.toggle(lst.model().index(i, 0))
    settle(150)


def _row_band(lst, first, last):
    """The rows `first`…`last` of the list, in the window's coordinates."""
    vp = wc.rect_in_window(lst.viewport())
    a, b = lst.visualRect(lst.model().index(first, 0)), lst.visualRect(lst.model().index(last, 0))
    return QRect(vp.left(), vp.top() + a.top(), vp.width(), b.bottom() - a.top() + 1)


def _allowed_outside_the_list(win):
    """What a press may repaint outside the list: the toast it raises (with its shadow and the parts under it), the
    bottom bar's line (the press's mark and its words) and the edge strips over the list's ends."""
    toast = wc.rect_in_window(win.toasts.card).adjusted(-48, -48, 48, 48)
    bar = QRect(0, wc.rect_in_window(win.dock).top() - 24, win.width(), win.height())
    return [toast, bar]


def _closed_row(lst, at_least=0):
    return next(i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and i >= at_least)


# --- R3: a move repaints the rows that changed ------------------------------------------------------------------- #
def test_r3_a_nudge_repaints_the_two_rows_it_swapped_and_nothing_else_in_the_list(screen):
    """Alt+↓ on a row: it and the row under it trade places — those two repaint (and the keyboard ring with them, a
    row's height at most more), never the list; outside it, only the toast and the bar's line."""
    seed, win, writer = screen
    lst = lst_of(win)
    i = _closed_row(lst, 3)
    lst.setCurrentIndex(lst.model().index(i, 0))
    lst.setFocus()
    settle(100)
    saved = len(writer.saved)
    renders = lst.delegate.renders
    with wc.measure(win, readers=[win.services.library]) as w:
        QTest.keyClick(lst, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
        assert wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [], 3)
        settle(150)
    vp = wc.rect_in_window(lst.viewport())
    band = _row_band(lst, i - 1, i + 1)                           # the pair, and one row's ring of slack above
    in_list = [p for p in w.paints if vp.contains(p.rect)]
    assert w.union_in(vp) <= band.width() * band.height() + vp.width() * wc.STRIP_SLACK_PX * 2, w.report()
    assert all(band.adjusted(0, 0, 0, 0).intersects(p.rect) or p.rect.height() <= 8 for p in in_list), w.report()
    outside = [p for p in w.paints if not vp.contains(p.rect) and not vp.intersects(p.rect)
               and not any(r.contains(p.rect) for r in _allowed_outside_the_list(win))]
    assert outside == [], (outside, w.report())
    assert lst.delegate.renders - renders <= 2, w.report()        # the two rows' new pictures at most
    assert w.builds <= 1, w.report()                               # one view for one move


def test_r3_a_drop_draws_afresh_only_the_rows_whose_place_changed(screen):
    """A row dropped four places up: S19's written skip — the drop's relayout repaints the viewport — so the rule is
    the pictures: only the rows the drop moved are drawn afresh (each shows its place number), one view built,
    nothing in the header repainted."""
    seed, win, writer = screen
    lst = lst_of(win)
    lift(win, 6)
    target = row_point(win, 2)
    move_global(win, target)
    settle(100)
    saved = len(writer.saved)
    renders = lst.delegate.renders
    with wc.measure(win, readers=[win.services.library]) as w:
        release_global(win, target)
        assert wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [], 3)
        settle(200)
    assert lst.delegate.renders - renders <= 6 - 2 + 1, w.report()          # rows 2…6, no other
    assert w.builds <= 1, w.report()
    header = wc.rect_in_window(win.header) if hasattr(win, "header") else QRect()
    assert not any(header.contains(p.rect) for p in w.paints), w.report()


def test_r3_an_undo_draws_afresh_only_the_rows_it_puts_back(screen):
    """The toast's Undo of a drop: the rows go back — one view, only the rows the drop had moved drawn afresh."""
    seed, win, writer = screen
    lst = lst_of(win)
    lift(win, 6)
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    assert wait_until(lambda: writer.saved and win.moves.tickets == [], 3)
    settle(300)
    undone = len(writer.undone)
    renders = lst.delegate.renders
    with wc.measure(win, readers=[win.services.library]) as w:
        win.toasts.card.buttons[0].click()
        assert wait_until(lambda: len(writer.undone) > undone, 3)
        settle(300)
    writer.saved.pop()                                             # undone: nothing for the clean-up to undo
    assert lst.delegate.renders - renders <= 6 - 2 + 1, w.report()          # rows 2…6, no other
    assert w.builds <= 2, w.report()                               # (the undo's view; the optimistic one at most)
    assert w.created == 0, w.report()


# --- R4: a row opened and closed ----------------------------------------------------------------------------------- #
def test_r4_opening_and_closing_a_row_draws_only_its_own_episodes_afresh(screen):
    """A row with episodes opened, then closed: S19's written skip (a relayout repaints the viewport, from pictures):
    opening draws its head and its episodes at most, closing draws nothing afresh; nothing outside the list and its
    scroll bar repaints; no widget made."""
    seed, win, writer = screen
    lst = lst_of(win)
    k = next(i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and len(e[1].episodes) >= 2)
    episodes = len(lst.model().entries[k][1].episodes)
    box = wc.rect_in_window(lst)
    for opening in (True, False):
        renders = lst.delegate.renders
        with wc.measure(win, readers=[win.services.library]) as w:
            lst.toggle(lst.model().index(k, 0))
            settle(100)
        drawn = lst.delegate.renders - renders
        assert drawn <= (1 + episodes if opening else 0), (opening, drawn, w.report())
        assert w.paints_outside_rect(box) == [] or all(p[0] in ("ShellWindow", "QWidget", "QStackedWidget",
                                                                 "CurrentPage") and box.contains(p[2])
                                                       for p in w.paints_outside_rect(box)), w.report()
        assert w.created == 0 and w.builds == 0, w.report()


# --- R2: a wheel notch paints the strip it uncovers ---------------------------------------------------------------- #
def test_r2_a_wheel_notch_paints_only_the_strip_that_came_into_view(screen):
    """A notch on the list (2,000-file shapes aside, the seed's ~40 rows scroll too): Qt moves what is drawn and the
    list paints the strip that came in (the opaque viewport, W2.2's profile) — plus the scroll bar; no row drawn
    afresh beyond the ones coming in."""
    seed, win, writer = screen
    lst = lst_of(win)
    vp = lst.viewport()
    bar = lst.verticalScrollBar()
    assert bar.maximum() > 0
    view = wc.rect_in_window(vp)
    for _ in range(3):
        v0 = bar.value()
        with wc.measure(win) as w:
            pos = QPointF(vp.width() / 2, vp.height() / 2)
            QApplication.sendEvent(vp, QWheelEvent(pos, QPointF(vp.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                                   QPoint(0, -120), Qt.MouseButton.NoButton,
                                                   Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                                                   False))
        moved = wc.exposed(v0, bar.value())
        assert moved > 0
        assert w.union_in(view) <= (moved + wc.STRIP_SLACK_PX) * vp.width(), (moved, w.report())
        assert w.created == 0 and w.builds == 0, w.report()


# --- R5: the ⋯ menu built once ------------------------------------------------------------------------------------- #
@pytest.mark.xfail(strict=True, reason="WC found.md F4: each ⋯ open makes its submenus again (5 widgets)")
def test_r5_the_rows_menu_opened_again_makes_no_widget(screen):
    """⋯ on a row, closed, then ⋯ on another: the list keeps one menu (C4) — the second open makes no widget and no
    native window."""
    seed, win, writer = screen
    rs = win.page_widgets["current"].view_model.rows
    at = win.mapToGlobal(QPoint(300, 300))
    first = win.items.menu(rs[5], at)
    settle(50)
    first.close()
    settle(50)
    with wc.measure(win) as w:
        m = win.items.menu(rs[4], at)
        settle(50)
    try:
        assert m is first
        assert w.created == 0, w.report()
    finally:
        m.close()
        settle(50)
