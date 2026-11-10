"""Work counts on the header (tabs, the level, New arrivals' inset) (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: a tab switch or a pop that redraws the whole window.

The screen: the window built once for the file (`screen` -> (seed, win, writer)); every test puts back what it changed.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_arrivals import open_tray, tray_of


@pytest.fixture(scope="module")
def screen(qapp, tmp_path_factory):
    with wc.window_screen(qapp, tmp_path_factory, "header", writer="arrivals") as s:
        yield s


@pytest.fixture(autouse=True)
def _at_rest(screen, monkeypatch):
    """Each test in the file's own root, Current shown; at its end everything on its way landed."""
    wc.home(monkeypatch, "header")
    seed, win, writer = screen
    win.show_tab("current")
    wc.pointer_away(win.page_widgets["current"].list)
    wc.rest(200)
    yield
    wc.quiet(win)


# --- R5: an overlay opened again is built once --------------------------------------------------------------------- #
def test_r5_the_level_pop_opened_again_makes_no_widget(qapp, tmp_path):
    """The header's level button: its pop opened, closed, then opened again (the pop kept; no widget made the second time).
    The `screen` window has no duties (`open_window` gives none): the pop is the one `test_level_menu`'s World makes."""
    from tests.qt.test_jobs_bar import World
    world = World(qapp, logs_folder=str(tmp_path / "logs"))
    d = world.d
    try:
        d.level.click()
        assert wait_until(d.pop.isVisible, 3)
        d.level.click()
        assert wait_until(lambda: not d.pop.isVisible(), 3)
        with wc.measure(world.win) as m:
            d.level.click()
            assert wait_until(d.pop.isVisible, 3)
        assert m.created == 0, m.report()
    finally:
        if d.pop.isVisible():
            d.level.click()                                                # put back, unmeasured
        wc.settle()
        world.close()


def test_inset_from_another_tab_opens_the_tray_again_with_no_widget_made(screen):
    """The header's inset from another tab, the tray closed after its first open: the inset opens it again (R5) — the
    tray built once, so this open makes no widget and deletes none."""
    seed, win, writer = screen
    try:
        win.show_tab("finished")
        open_tray(win)
        wc.rest(150)
        tray_of(win).close()
        wc.rest(150)
        win.show_tab("finished")
        wc.rest(150)
        with wc.measure(win, readers=[win.services.library]) as w:
            open_tray(win)
            wc.rest(150)
        assert w.created == 0 and w.deleted == 0, w.report()
    finally:
        if tray_of(win).isVisible():
            tray_of(win).close()
        wc.rest(150)
