"""Work counts on the library search (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: a search that lags on every keystroke.

The screen: test_search's `world` fixture (one window a test: a real store for the titles).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_search import ask, calls, hits_of, rows_of, world   # noqa: F401
from tests.qt.test_drag import _stones_sheet   # noqa: F401  (autouse: the stones drawn before the window opens)


def test_down_in_the_results_repaints_only_the_two_hits_that_change(world):
    """Down in the open results (the picked hit moves from one row to the next): only those two hit rows repaint,
    nothing else of the window."""
    seed, win, _writer = world()
    results = ask(win, "星")
    assert len(results.hits) >= 3
    wait_until(lambda: not results.scroll.verticalScrollBar().isSliderDown(), 1)
    wc.rest(150)
    results.pick(1)                       # the first hit picked, unmeasured
    wc.rest(150)
    old, new = results.hits[0], results.hits[1]
    assert results.picked == 0 and old.current and not new.current
    with wc.measure(win) as w:
        results.pick(1)
        wc.rest(150)
    assert results.picked == 1 and new.current and not old.current
    assert w.painted > 0, w.report()
    view = wc.rect_in_window(results.scroll.viewport())
    for hit in (old, new):                # both hits repaint, whole (the part the scroll view shows)
        seen = wc.rect_in_window(hit).intersected(view)
        assert seen.width() * seen.height() > 0
        assert w.union_in(seen) == seen.width() * seen.height(), (hit, w.report())
        assert w.painted_in(hit) > 0, (hit, w.report())
    # The one exemption: the focused search field. A probe showed the caret blink (a 10x15 px paint at the field)
    # lands in the 150 ms window; the test is not about the field, the hit checks above carry the repaint half.
    outside = w.paints_outside_rect(wc.rect_in_window(old), wc.rect_in_window(new),
                                    wc.rect_in_window(win.search.edit))
    assert outside == [], (outside, w.report())


def test_r5_the_results_opened_closed_with_esc_and_opened_again_by_typing_make_no_widget(world):
    """The results opened, closed with Esc, and opened again by typing the same search: the same overlay comes back
    with the same hits, and the reopen makes no widget (R5: built once)."""
    seed, win, _writer = world()
    cut = win.search
    try:
        results = ask(win, "星")
    except AssertionError as e:                                        # setup: never the xfail's AssertionError
        pytest.fail(f"setup: the results didn't open: {e}")
    shown = len(hits_of(results))
    QTest.keyClick(cut.edit, Qt.Key.Key_Escape)                      # cleared, results closed
    if results.isVisible() or cut.edit.text() != "":
        pytest.fail("Esc didn't clear the search and close its results")
    with wc.measure(win, readers=[win.services.library]) as w:
        try:
            reopened = ask(win, "星")                                 # opened again by typing
        except AssertionError as e:
            pytest.fail(f"setup: the results didn't open again: {e}")
        wc.rest(150)
    if reopened is not results or len(hits_of(results)) != shown:
        pytest.fail(f"the reopen didn't show the same overlay with the same hits: {w.report()}")
    assert w.created == 0, w.report()


def test_a_refill_with_fewer_hits_keeps_only_its_own_rows_showing(world):
    """The results kept their rows (R5, C2) — so a refill that shows fewer hits must let the others go: every hit row
    left in the results is one the fill lists, none from the last fill stays on screen."""
    from app.qt.search import HitRow
    seed, win, _writer = world()
    try:
        results = ask(win, "星")
    except AssertionError as e:                                        # setup: never the rule's AssertionError
        pytest.fail(f"setup: the results didn't open: {e}")
    groups = results.groups
    if sum(len(g.hits) for g in groups) < 2:
        pytest.fail("setup: the seed's search shows fewer than two hits")
    fewer = tuple(g._replace(hits=g.hits[:1]) for g in groups)
    results.show_groups(results.query, fewer)
    wc.settle()
    shown = [w for w in results.body.findChildren(HitRow) if w.isVisible()]
    assert sorted(map(id, shown)) == sorted(map(id, results.hits))
    assert [r.hit for r in results.hits] == [h for g in fewer for h in g.hits]
