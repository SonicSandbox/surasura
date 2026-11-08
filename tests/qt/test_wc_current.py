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
from PyQt6.QtCore import QObject, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import rows, strings
from app.qt.item_menu import ep_name
from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_drag import lift, move_global, press, release, release_global, row_point, settle


@pytest.fixture(scope="module")
def screen(qapp, tmp_path_factory):
    """(seed, win, writer): the window on the synthetic library (Japanese titles), its moves written into the stand-in
    store and undone back, built once for the file."""
    with wc.window_screen(qapp, tmp_path_factory, "current") as s:
        yield s


def lst_of(win):
    return win.page_widgets["current"].list


def keys_of(win):
    return [getattr(e[1], "key", None) for e in lst_of(win).model().entries]


@pytest.fixture(autouse=True)
def _at_rest(screen, monkeypatch):
    """Each test from the same place: the file's own root, Current shown, at its top, no row open, the order as the
    seed made it; at its end everything on its way landed (`wc.quiet`)."""
    wc.home(monkeypatch, "current")
    seed, win, writer = screen
    win.show_tab("current")
    lst = lst_of(win)
    lst.verticalScrollBar().setValue(0)
    wc.pointer_away(lst)                                           # its own pointer state, never a test before's
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
    wc.quiet(win)


def _row_band(lst, first, last):
    """The rows `first`…`last` of the list, in the window's coordinates."""
    vp = wc.rect_in_window(lst.viewport())
    a, b = lst.visualRect(lst.model().index(first, 0)), lst.visualRect(lst.model().index(last, 0))
    return QRect(vp.left(), vp.top() + a.top(), vp.width(), b.bottom() - a.top() + 1)


def _allowed_outside_the_list(win):
    """What a press may repaint outside the list: the toast it raises (with its shadow and the parts under it), the
    bottom bar's line (the press's mark and its words), the edge strips over the list's ends and the header's 1 px
    progress line (a press that waits on a worker shows its mark there: `press.py`)."""
    from PyQt6.QtWidgets import QWidget
    toast = wc.rect_in_window(win.toasts.card).adjusted(-48, -48, 48, 48)
    bar = QRect(0, wc.rect_in_window(win.dock).top() - 24, win.width(), win.height())
    progress = win.findChild(QWidget, "progress")
    return [toast, bar] + ([wc.rect_in_window(progress)] if progress is not None else [])


def _closed_row(lst, at_least=0):
    return next(i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and i >= at_least)


def part(lst, i, name):
    """The painted parts of row `i` called `name` (as test_current.part): (name, rect, tip, extra) tuples."""
    entry = lst.model().entries[i]
    return [p for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0))) if p[0] == name]


# --- R3: a move repaints the rows that changed ------------------------------------------------------------------- #
def test_r3_a_nudge_repaints_the_two_rows_it_swapped_and_nothing_else_in_the_list(screen):
    """Alt+↓ on a row: it and the row under it trade places — those two repaint, never the list; outside it, only
    the toast and the bar's line. Both presses counted: the first one also turns the keyboard's ring on (its row
    lifts and parts its neighbours — §3's hover: found.md F5's third row; the 8 px strip at the list's foot is the
    toast's shadow coming over it), so it may reach one row above; the second, the ring already on, the pair alone."""
    seed, win, writer = screen
    lst = lst_of(win)
    i = _closed_row(lst, 3)
    lst.setCurrentIndex(lst.model().index(i, 0))
    lst.setFocus()
    settle(100)
    saved = len(writer.saved)
    with wc.measure(win, readers=[win.services.library]) as first:      # the first: the ring comes on with it
        QTest.keyClick(lst, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
        if not wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [], 3):
            pytest.fail("the first Alt+↓ was never saved")
        settle(150)
    vp = wc.rect_in_window(lst.viewport())
    band = _row_band(lst, i - 1, i + 1)                           # the pair, and the ring's one row above
    assert first.union_in(vp) <= band.width() * band.height() + vp.width() * wc.STRIP_SLACK_PX * 2, first.report()
    assert all(band.intersects(p.rect) or p.rect.height() <= 8 for p in first.paints if vp.contains(p.rect)),         first.report()
    settle(600)                                                   # (its springs and its toast at rest)
    i = lst.currentIndex().row()
    saved = len(writer.saved)
    renders = lst.delegate.renders
    with wc.measure(win, readers=[win.services.library]) as w:
        QTest.keyClick(lst, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
        assert wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [], 3)
        settle(150)
    vp = wc.rect_in_window(lst.viewport())
    j = lst.currentIndex().row()
    band = _row_band(lst, min(i, j), max(i, j))                   # the pair
    in_list = [p for p in w.paints if vp.contains(p.rect)]
    assert w.union_in(vp) <= band.width() * band.height() + vp.width() * wc.STRIP_SLACK_PX * 2, w.report()
    assert all(band.intersects(p.rect) or p.rect.height() <= 8 for p in in_list), w.report()
    outside = [p for p in w.paints if not vp.contains(p.rect) and not vp.intersects(p.rect)
               and not any(r.contains(p.rect) for r in _allowed_outside_the_list(win))]
    assert outside == [], (outside, w.report())
    assert lst.delegate.renders - renders <= 2, w.report()        # the two rows' new pictures at most
    # (no view: the test's writer records a nudge without writing the stand-in store — the rows shown are the
    #  optimistic move's, which is what the learner sees at the press)
    assert w.builds == 0, w.report()


def test_r4_down_moves_the_ring_repainting_only_its_two_rows_and_their_neighbours(screen):
    """↓ with the keyboard's ring on: the ring leaves one row for the next — the row it left settles back and lets its
    neighbours close, the row it reached lifts and parts its own (§3's hover: three rows while their springs run), so
    those four rows repaint and nothing else; the two rows whose look changed drawn afresh at most, no view built. (Catalogue C09: found.md F7's
    four-row paint is this, not waste: `theme.SPRINGS` neighbour-px 1.5.)"""
    seed, win, writer = screen
    lst = lst_of(win)
    i = _closed_row(lst, 3)
    lst.setCurrentIndex(lst.model().index(i, 0))
    lst.setFocus()
    settle(100)
    QTest.keyClick(lst, Qt.Key.Key_Down)                          # the ring on, unmeasured
    settle(600)
    i = lst.currentIndex().row()
    if not 1 <= i < lst.model().rowCount() - 2:
        pytest.fail(f"the ring stands at row {i}: no room for the test's rows")
    renders = lst.delegate.renders
    with wc.measure(win, readers=[win.services.library]) as w:
        QTest.keyClick(lst, Qt.Key.Key_Down)
        settle(600)                                               # (both springs at rest)
    if lst.currentIndex().row() != i + 1 or not w.painted:
        pytest.fail(f"↓ didn't move the ring to the next row: {w.report()}")
    vp = wc.rect_in_window(lst.viewport())
    band = _row_band(lst, i - 1, i + 2)
    assert w.paints_outside_rect(band, *_allowed_outside_the_list(win)) == [], w.report()
    assert lst.delegate.renders - renders <= 2, w.report()        # the ring's two rows' pictures at most
    assert w.builds == 0 and w.created == 0, w.report()


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
    reader = win.services.library
    built = reader.builds
    with wc.measure(win, readers=[reader]) as w:
        release_global(win, target)
        assert wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [] and reader.builds > built, 3)
        settle(200)
    assert lst.delegate.renders - renders <= 6 - 2 + 1, w.report()          # rows 2…6, no other
    assert w.builds == 1, w.report()
    assert w.paints_outside_rect(wc.rect_in_window(lst), *_allowed_outside_the_list(win)) == [], w.report()


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
    reader = win.services.library
    built = reader.builds
    with wc.measure(win, readers=[reader]) as w:
        win.toasts.card.buttons[0].click()
        assert wait_until(lambda: len(writer.undone) > undone and reader.builds > built and win.moves.tickets == [], 3)
        settle(200)
    writer.saved.pop()                                             # undone: nothing for the clean-up to undo
    assert lst.delegate.renders - renders <= 6 - 2 + 1, w.report()          # rows 2…6, no other
    assert 1 <= w.builds <= 2, w.report()                          # (the undo's view; the optimistic one at most)
    assert w.paints_outside_rect(wc.rect_in_window(lst), *_allowed_outside_the_list(win)) == [], w.report()
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
        assert w.paints_outside_rect(box) == [], w.report()
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


def test_r5_a_kept_menus_submenus_hold_only_this_opens_entries(screen):
    """⋯ on a row, closed, and ⋯ on the same row again: the kept menu lends the same submenus back (R5), each emptied
    as the menu hid — so each shows exactly the entries it showed the first time, never the last open's as well."""
    seed, win, writer = screen
    rs = win.page_widgets["current"].view_model.rows
    at = win.mapToGlobal(QPoint(300, 300))

    def shape(m):
        return [(a.text(), [x.text() for x in a.menu().actions()] if a.menu() is not None else None)
                for a in m.actions()]
    row = next((r for r in rs[1:] if any(a.menu() is not None for a in win.items.menu(r, at).actions())), None)
    win.items.last_menu.close()
    settle(50)
    if row is None:
        pytest.fail("no row of the seed has a submenu in its ⋯")
    first = shape(win.items.menu(row, at))
    settle(50)
    win.items.last_menu.close()
    settle(50)
    try:
        assert shape(win.items.menu(row, at)) == first
    finally:
        win.items.last_menu.close()
        settle(50)


def test_r3_a_row_down_button_pressed_and_released_repaints_the_two_rows_it_swapped_and_nothing_else_in_the_list(screen):
    """A row's ↓ button, pressed and released by the mouse: it and the row under it trade places — those two repaint
    (and the keyboard ring with them), never the list; outside it, only the toast and the bar's line."""
    seed, win, writer = screen
    lst = lst_of(win)
    i = _closed_row(lst, 3)
    lst.setCurrentIndex(lst.model().index(i, 0))
    settle(100)
    downs = part(lst, i, "down")
    assert downs, "the row shows its ↓ button"
    at = downs[0][1].center()
    saved = len(writer.saved)
    renders = lst.delegate.renders
    before = keys_of(win)
    key = before[i]
    assert key is not None, "the row has a key to follow"
    with wc.measure(win, readers=[win.services.library]) as w:
        press(lst, at)
        release(lst, at)
        assert wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [], 3)
        settle(150)
    assert keys_of(win).index(key) == i + 1, "the row moved one place down, not up"
    vp = wc.rect_in_window(lst.viewport())
    band = _row_band(lst, i - 1, i + 1)                           # the pair, and one row's ring of slack above
    in_list = [p for p in w.paints if vp.contains(p.rect)]
    assert w.union_in(vp) <= band.width() * band.height() + vp.width() * wc.STRIP_SLACK_PX * 2, w.report()
    assert all(band.intersects(p.rect) or p.rect.height() <= 8 for p in in_list), w.report()
    outside = [p for p in w.paints if not vp.contains(p.rect) and not vp.intersects(p.rect)
               and not any(r.contains(p.rect) for r in _allowed_outside_the_list(win))]
    assert outside == [], (outside, w.report())
    assert lst.delegate.renders - renders <= 2, w.report()        # the two rows' new pictures at most
    assert w.builds == 0, w.report()


def test_r5_the_episode_menu_opened_again_on_another_episode_makes_no_widget(screen):
    """⋯ on an open row's episode, closed, then ⋯ on another episode: the list keeps its one menu (C4) — the second
    open makes no widget."""
    seed, win, writer = screen
    lst = lst_of(win)
    k = next(i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and len(e[1].episodes) >= 2)
    row = lst.model().entries[k][1]
    at = win.mapToGlobal(QPoint(300, 300))
    lst.toggle(lst.model().index(k, 0))
    settle(100)
    try:
        first = win.items.episode_menu(row, row.episodes[0], at)
        settle(50)
        first.close()
        settle(50)
        with wc.measure(win) as w:
            m = win.items.episode_menu(row, row.episodes[1], at)
            settle(50)
        try:
            assert m is first                        # the list's one menu, reopened for episode 1
            assert m.isVisible()
            assert m.accessibleName() == strings.ITEM_EP_MENU_NAME.format(ep=ep_name(row, row.episodes[1]))
            assert w.created == 0, w.report()
        finally:
            m.close()
            settle(50)
    finally:
        lst.toggle(lst.model().index(k, 0))
        settle(100)


# --- R4: a fold line pressed -------------------------------------------------------------------------------------- #
def test_r4_a_fold_line_pressed_draws_afresh_only_its_row_and_the_parts_it_lists(screen):
    """A fold line pressed (its group's parts listed after it), then pressed again (folded): S19's written skip (a
    relayout repaints the viewport, from pictures): listing draws the fold's line and its parts afresh at most
    (and does draw), folding draws nothing afresh; the fold flips; nothing above the pressed row, nor outside the
    list, repaints; no widget made."""
    seed, win, writer = screen
    lst = lst_of(win)
    model = lst.model()
    k, fold = next(((i, f) for i, e in enumerate(model.entries) if e[0] in (rows.HERO, rows.ROW)
                    for f in rows.row_folds(e[1], e[2]) if f.ids), (None, None))
    assert fold is not None, "the seed has a row with a fold"
    lst.toggle(model.index(k, 0))
    settle(100)
    box = wc.rect_in_window(lst)
    vp = wc.rect_in_window(lst.viewport())

    def fold_line():
        return next((item for _r, item in lst.delegate.episode_lines(
            model.entries[k], lst.visualRect(model.index(k, 0))) if item.ids == fold.ids), None)

    presses = 0
    try:
        for _press in range(2):
            line = fold_line()
            assert line is not None, "a fold line is shown"
            opening = not lst.fold_open(fold)
            renders = lst.delegate.renders
            with wc.measure(win, readers=[win.services.library]) as w:
                lst.toggle_fold(line)
                presses += 1
                settle(100)
            drawn = lst.delegate.renders - renders
            assert bool(lst.fold_open(fold)) is opening, (opening, "the press flipped the fold")
            assert drawn <= (1 + len(line.ids) if opening else 0), (opening, drawn, w.report())
            assert w.paints_outside_rect(box) == [], w.report()
            assert w.created == 0 and w.builds == 0, w.report()
            # nothing above the pressed row repaints: its picture and the rows after it (moved, from pictures) only
            top = lst.visualRect(model.index(k, 0)).top()
            below = QRect(vp.left(), vp.top() + top, vp.width(), vp.height() - top)
            in_list = [p for p in w.paints if vp.contains(p.rect)]
            assert all(below.intersects(p.rect) or p.rect.height() <= 8 for p in in_list), (opening, w.report())
            assert w.union_in(below) > 0, (opening, w.report())
            if opening:
                assert drawn >= 1, (opening, drawn, w.report())
    finally:
        if presses % 2 == 1:
            f = fold_line()
            if f is not None:
                lst.toggle_fold(f)
            settle(100)


def test_r3_a_ctrl_click_on_a_closed_row_repaints_that_row_and_nothing_else_in_the_list(screen):
    """Ctrl+click on a closed row's title: the row is picked — its row repaints (drawn afresh, painted), never the
    list; outside it, only the toast and the bar's line."""
    from PyQt6.QtCore import QEvent
    from tests.qt.test_drag import mouse
    seed, win, writer = screen
    lst = lst_of(win)
    i = _closed_row(lst, 3)
    key = keys_of(win)[i]
    assert key is not None, "the row has a key to pick by"
    g = lst.delegate.line_geometry(lst.model().entries[i][1], lst.delegate.slab_of(lst.visualRect(lst.model().index(i, 0))))
    at = QPoint(g["main"].left() + 20, g["main"].center().y())
    ctrl = Qt.KeyboardModifier.ControlModifier
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton

    def click():
        mouse(lst.viewport(), QEvent.Type.MouseButtonPress, at, left, left, ctrl)
        mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, at, left, none, ctrl)

    renders = lst.delegate.renders
    try:
        with wc.measure(win, readers=[win.services.library]) as w:
            click()
            settle(150)
        assert key in lst.picked_rows, "the row is picked"
        vp = wc.rect_in_window(lst.viewport())
        band = _row_band(lst, i, i)
        slack = vp.width() * wc.STRIP_SLACK_PX * 2
        assert w.union_in(band) > 0, w.report()                   # the picked row was painted
        assert w.union_in(vp) <= band.width() * band.height() + slack, w.report()
        in_list = [p for p in w.paints if vp.contains(p.rect)]
        assert all(band.intersects(p.rect) or p.rect.height() <= 8 for p in in_list), w.report()
        outside = [p for p in w.paints if not vp.contains(p.rect) and not vp.intersects(p.rect)
                   and not any(r.contains(p.rect) for r in _allowed_outside_the_list(win))]
        assert outside == [], (outside, w.report())
        assert lst.delegate.renders - renders <= 2, w.report()    # the row itself, a ring at most
        assert w.builds == 0, w.report()
    finally:
        lst.clear_picks()
        settle(100)


def test_r3_ctrl_z_after_a_drop_draws_afresh_only_the_rows_it_puts_back(screen):
    """Ctrl+Z after a drop: the newest move is undone — the rows go back, one view, only the rows the drop had moved
    drawn afresh, nothing outside the list but the toast and the bar's line."""
    seed, win, writer = screen
    lst = lst_of(win)
    before = keys_of(win)
    lift(win, 6)
    target = row_point(win, 2)
    move_global(win, target)
    release_global(win, target)
    assert wait_until(lambda: writer.saved and win.moves.tickets == [], 3)
    settle(300)
    moved = keys_of(win)
    assert moved != before
    undone = len(writer.undone)
    renders = lst.delegate.renders
    reader = win.services.library
    built = reader.builds
    with wc.measure(win, readers=[reader]) as w:
        QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert wait_until(lambda: len(writer.undone) > undone and reader.builds > built and win.moves.tickets == [], 3)
        settle(200)
    writer.saved.pop()                                             # undone: nothing for the clean-up to undo
    assert keys_of(win) == before, w.report()                      # the newest move is the one put back
    assert lst.delegate.renders - renders <= 6 - 2 + 1, w.report()          # rows 2…6, no other
    assert 1 <= w.builds <= 2, w.report()                          # (the undo's view; the optimistic one at most)
    assert w.paints_outside_rect(wc.rect_in_window(lst), *_allowed_outside_the_list(win)) == [], w.report()
    assert w.created == 0, w.report()


def test_r3_the_menus_soon_on_a_row_draws_afresh_only_the_rows_it_passes_and_writes_a_soon_move(screen):
    """⋯ › Soon on a row: it goes to the top of Soon — the write is a Soon move after the anchor the rule gives, the
    order is the rule's, and only the rows it passed (a few, the move is pinned short) are drawn afresh, the paints
    staying in the list but for the toast and the bar's line."""
    from app.qt import drag
    seed, win, writer = screen
    lst = lst_of(win)
    rs = list(win.moves.base().rows)
    src, row = None, None
    for n, r in enumerate(rs):
        if r.tier != "soon" and 2 <= drag.soon_slot(rs, n)[0] - n <= 5:
            src, row = n, r
            break
    assert row is not None, [(r.key, r.tier) for r in rs]
    slot, files, after_id = drag.soon_slot(rs, src)
    expected = drag.order_after([r.key for r in rs], row.key, slot)
    place = expected.index(row.key)
    changed = abs(place - src) + 1
    assert changed <= 6
    calls = len(writer.calls)
    saved = len(writer.saved)
    renders = lst.delegate.renders
    reader = win.services.library
    built = reader.builds
    with wc.measure(win, readers=[reader]) as w:
        win.moves.menu_pick(row, "soon")
        assert wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [] and reader.builds > built, 3)
        settle(200)
    op, ids, kw = writer.calls[-1]
    assert len(writer.calls) == calls + 1 and op == "move" and kw["tier"] == "soon", writer.calls[-1]
    assert kw["after_id"] == after_id, writer.calls[-1]
    assert [k for k in keys_of(win) if k is not None] == expected, w.report()
    entry = next(e[1] for e in lst.model().entries if getattr(e[1], "key", None) == row.key)
    assert entry.tier == "soon", w.report()
    drawn = lst.delegate.renders - renders
    assert 1 <= drawn <= changed + 1, w.report()                  # the rows from its old place to its new, no other
    assert w.builds == 1, w.report()
    assert w.paints_outside_rect(wc.rect_in_window(lst), *_allowed_outside_the_list(win)) == [], w.report()


def test_r0_the_pointer_leaving_the_list_after_resting_on_a_row_repaints_only_that_row_and_its_neighbours(screen):
    """The pointer rests on a row, then leaves the list: the hovered row repaints, with at most its two neighbours
    (the hover-neighbour spring releases them too) — no other row of the list, nothing outside it but the toast and
    the bar's line — and no row is drawn afresh. The paints are judged by where they fall (rows), not by how many
    frames the release spring takes."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QMouseEvent
    seed, win, writer = screen
    lst = lst_of(win)
    i = _closed_row(lst, 3)
    pos = QPointF(lst.visualRect(lst.model().index(i, 0)).center())
    QApplication.sendEvent(lst.viewport(), QMouseEvent(QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
                                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    try:
        assert wait_until(lambda: lst._hover == i, 3)                  # the row is hovered: the press is not a no-op
        assert wait_until(lambda: not lst._hover_warm.isActive() and not lst._warm.isActive(), 3)
        settle(300)                                                    # the lift's springs ended before we measure
        wc.quiet(win)
        renders = lst.delegate.renders
        paints = lst.delegate.paints
        band = _row_band(lst, i - 1, i + 1)
        row_i = _row_band(lst, i, i)
        with wc.measure(win, readers=[win.services.library]) as w:
            QApplication.sendEvent(lst, QEvent(QEvent.Type.Leave))
            wc.rest(500)                                               # long enough for the release springs to end
        assert lst._hover is None, w.report()
        assert lst.delegate.paints > paints, w.report()                # the release did paint something
        assert any(row_i.intersects(p.rect) for p in w.paints), w.report()   # the hovered row itself repainted
        assert w.paints_outside_rect(band, *_allowed_outside_the_list(win)) == [], w.report()
        assert lst.delegate.renders == renders, w.report()             # from kept pictures: nothing drawn afresh
    finally:
        try:
            QApplication.sendEvent(lst, QEvent(QEvent.Type.Leave))
        except RuntimeError:
            pass
        settle(100)
        wc.quiet(win)


def test_r4_the_arrow_keys_step_the_ring_and_repaint_only_the_two_rows_it_moves_between(screen):
    """↓ then ↑ on the list (no Alt): the keyboard ring steps from one closed row to the next and back — only those
    two rows repaint (a row's height of slack above and below), never the list; nothing outside it, nothing made."""
    seed, win, writer = screen
    lst = lst_of(win)
    ents = lst.model().entries
    i = next(k for k in range(3, len(ents) - 1) if ents[k][0] == rows.ROW and ents[k + 1][0] == rows.ROW)
    first = lst.currentIndex()
    lst.setCurrentIndex(lst.model().index(i, 0))
    lst.setFocus()
    settle(150)
    try:
        band = _row_band(lst, i - 1, i + 2)                       # the pair, and one row's ring of slack each side
        vp = wc.rect_in_window(lst.viewport())
        for key, want in ((Qt.Key.Key_Down, i + 1), (Qt.Key.Key_Up, i)):
            with wc.measure(win, readers=[win.services.library]) as w:
                QTest.keyClick(lst, key)
                settle(150)
            assert lst.currentIndex().row() == want, w.report()
            assert w.painted > 0, w.report()
            assert w.union_in(vp) <= band.width() * band.height(), w.report()
            assert all(band.intersects(p.rect) for p in w.paints if vp.contains(p.rect)), w.report()
            outside = [p for p in w.paints if not vp.intersects(p.rect)
                       and not any(r.contains(p.rect) for r in _allowed_outside_the_list(win))]
            assert outside == [], (outside, w.report())
            assert w.created == 0 and w.builds == 0, w.report()
    finally:
        lst.setCurrentIndex(first)
        settle(100)


class _DeletedActions(QObject):
    """QActions deleted later (their deferred deletes) while it is installed on the application."""
    n = 0

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QAction
        if event.type() == QEvent.Type.DeferredDelete and isinstance(obj, QAction):
            self.n += 1
        return False


def _menu_act(m, name):
    return next(a for a in m.actions() if a.text() == strings.MENU_ITEMS[name][0])


def test_r5_the_rows_menu_opened_again_makes_no_action_and_its_close_deletes_none(screen):
    """⋯ on a row, closed, ⋯ on another, closed: the kept menu takes back the actions the last open used (`drag.
    menu_action`) — the second open makes no QAction and its close deletes none. (Up next at 20,000 files: each ⋯ made
    ~13 actions, deleted after the pick in ~13 deferred deletes, 2–5 ms each while the writer's and the reader's
    threads ran: half the press's stretch.)"""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QAction
    seed, win, writer = screen
    rs = win.page_widgets["current"].view_model.rows
    at = win.mapToGlobal(QPoint(300, 300))
    m = win.items.menu(rs[5], at)
    settle(50)
    m.close()
    settle(50)
    made = len(m.findChildren(QAction))
    with wc.measure(win) as w:
        m = win.items.menu(rs[4], at)
        settle(50)
        shown = len([a for a in m.actions() if not a.isSeparator()])
        m.close()
    assert shown >= 5 and w.kinds[QEvent.Type.DeferredDelete] == 0, w.report()
    assert len(m.findChildren(QAction)) <= made + 2, (made, len(m.findChildren(QAction)))    # (the submenus' own)


def test_r3_up_next_picked_in_the_menu_repaints_the_rows_it_moves_never_the_window_nor_lays_it_out(screen):
    """⋯ › Up next, picked as a click picks it (the menu hidden, then its action): the rows from its old place to the top
    are drawn afresh, nothing outside the list repaints but the toast and the bar's line — never the whole window as the
    focus comes back from the menu (`shell.Central`: Qt repaints a widget whole as it gains the focus, and the central
    widget is the whole window) — and no layout pass of the central widget or the window at the toast's words
    (`toast.ToastCard.body`). The close deletes no action (`drag.menu_action`)."""
    from PyQt6.QtCore import QEvent
    seed, win, writer = screen
    lst = lst_of(win)
    win.activateWindow()
    win._rest.setFocus()                                          # (where the focus rests: the bench's, a click's)
    settle(30)
    rs = list(win.moves.base().rows)
    src = 6
    row = rs[src]
    rect = lst.visualRect(lst.model().index(next(i for i, e in enumerate(lst.model().entries)
                                                  if getattr(e[1], "key", None) == row.key), 0))
    at = lst.viewport().mapToGlobal(rect.bottomLeft())
    m = win.items.menu(row, at)                                   # (a first open: the kept menu's actions made)
    settle(50)
    m.close()
    settle(50)
    m = win.items.menu(row, at)
    settle(50)
    act = _menu_act(m, "up-next")
    win.toasts.show(strings.DRAG_UP_NEXT.format(title=rs[1].title), undo=lambda: None)   # (the last move's, still up)
    settle(30)
    reader = win.services.library
    saved, built, renders = len(writer.saved), reader.builds, lst.delegate.renders
    central = win.centralWidget()
    actions = _DeletedActions()
    QApplication.instance().installEventFilter(actions)
    try:
        with wc.measure(win, readers=[reader]) as w:
            m.hide()
            act.trigger()
            assert wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [] and reader.builds > built,
                              3)
            settle(200)
    finally:
        QApplication.instance().removeEventFilter(actions)
    assert [k for k in keys_of(win) if k is not None][0] == row.key, w.report()
    assert 1 <= lst.delegate.renders - renders <= src + 2, w.report()   # the rows from its old place to the top
    assert actions.n == 0, w.report()                                  # (13 before: every action of the menu)
    assert w.layouts_of(central) == 0 and w.layouts_of(win) == 0, w.report()
    assert w.paints_outside_rect(wc.rect_in_window(lst), *_allowed_outside_the_list(win)) == [], w.report()


def test_r1_goal_from_the_menu_lays_the_window_out_never_whatever_its_toast_and_counts_do(screen):
    """⋯ › Goal on a row: the count in the header's sub-line changes and a toast shows afresh (none was up) — neither
    lays the window or its content out (Up next 2): the sub-line sits in a holder that asks the header only when its
    size changes (`shell.SubLine`), and the overlays sit on the central widget, which keeps no layout of its own — the
    content is laid out in its `body` (`shell.Central`). (Each Goal was a 6 ms pass of the window at 20,000 files.)"""
    seed, win, writer = screen
    win.toasts.close()
    settle(30)
    rs = list(win.moves.base().rows)
    row = next(r for r in rs[3:] if r.tier == "now")
    reader = win.services.library
    saved, built = len(writer.saved), reader.builds
    sub = win.subline.text()
    with wc.measure(win, readers=[reader]) as w:
        win.moves.menu_pick(row, "goal")
        assert wait_until(lambda: len(writer.saved) > saved and win.moves.tickets == [] and reader.builds > built, 3)
        settle(200)
    assert win.toasts.card.isVisible() and win.subline.text() != sub, w.report()    # (both did change)
    assert w.layouts_of(win) == 0 and w.layouts_of(win.centralWidget().body) == 0, w.report()
    assert w.layouts_of(win.findChild(QWidget, "header")) == 0, w.report()


def test_r1_the_sub_lines_new_count_asks_the_header_nothing_and_a_longer_line_takes_its_room(screen):
    """The header's sub-line: new digits at the same size lay nothing out; a line that grows is laid out once and its
    holder takes the new size (the search cut after it moves along, as it did when the label sat in the layout)."""
    seed, win, writer = screen
    line, header = win.subline, win.findChild(QWidget, "header")
    before = line.text()
    try:
        line.setText("日本語 · 12 in Current · 58 files")
        settle(30)
        with wc.measure(win) as w:
            line.setText("日本語 · 13 in Current · 58 files")
        assert w.layouts_of(header) == 0 and w.layouts_of(win) == 0, w.report()
        width = line.holder.width()
        with wc.measure(win) as w:
            line.setText("日本語 · 13 in Current · 58 files · 進撃の巨人 · 鬼灭之刃 第三季")
        assert w.layouts_of(header) == 1, w.report()
        assert line.holder.width() > width and line.geometry() == line.holder.rect()
    finally:
        line.setText(before)
        settle(30)
