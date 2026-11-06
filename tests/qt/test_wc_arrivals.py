"""Work counts on New arrivals (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work
counts*): what an arrival landing, the tray opened again, its ↑ *Top* and its ✓ *Finished* cost the window — paints and
where they land, Current's rows drawn afresh, widgets made, views built — counted, never timed.

What a wrong answer would cost a learner: hato dropping an episode while he reads repainting the whole window (S19's
"update only what changed"), a tray that builds itself again on every open, a placement that redraws every row of
Current. The window is built once for the file (`work_counts.kept`); the arrivals placed stay placed (each test takes
one the seed still has, or lands its own).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from app.qt import stones
from tests.fixtures import window_seed
from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_arrivals import ArrivalsWriter, _arrive, open_tray, open_window, tray_of, tray_rows
from tests.qt.test_drag import settle


@pytest.fixture(scope="module")
def screen(qapp, tmp_path_factory):
    """(seed, win, writer): the window on the synthetic library with its arrivals (a hato show in two evenings, a
    YouTube video, a watched hato show), placements written into the stand-in store; built once for the file."""
    with wc.module_env(tmp_path_factory, "arrivals"):
        key = stones._key(1.0, "M")
        if key not in stones._SHEETS:
            stones._landed(key, stones.build(*key))
        seed = window_seed.build()
        writer = ArrivalsWriter(seed.library)
        win, services = open_window(qapp, seed, writer)
        wc.kept(win)
        settle(300)
        yield seed, win, writer
        wc.close_kept(win, services)


def _with_shadow(win, widget):
    """`widget`'s rectangle with its shadow (the follower painted under it, `app/qt/shadow.py`)."""
    r = wc.rect_in_window(widget)
    for f in win.findChildren(QWidget, "shadowFollower"):
        fr = wc.rect_in_window(f)
        if f.isVisible() and fr.contains(r):
            return fr
    return r


@pytest.fixture(autouse=True)
def _at_rest(screen):
    """Each test from the same place: Current shown, the tray closed."""
    seed, win, writer = screen
    win.show_tab("current")
    settle(200)
    yield
    if tray_of(win).isVisible():
        tray_of(win).close()
    settle(200)


def test_an_arrival_landing_repaints_the_inset_alone(screen):
    """A file hato registers while the tray is closed: the header's inset repaints (its count, its covers) — nothing
    else in the window, no row of Current drawn, one view built."""
    seed, win, writer = screen
    inset = win.arrivals_inset
    lst = win.page_widgets["current"].list
    count = inset.count
    renders = lst.delegate.renders
    with wc.measure(win, readers=[win.services.library]) as w:
        _arrive(seed, title="葬送のフリーレン", added="2026-10-16T08:00:00Z")
        assert wait_until(lambda: inset.count == count + 1, 5)
        settle(200)
    assert w.painted > 0, w.report()
    assert w.paints_outside_rect(wc.rect_in_window(inset)) == [], w.report()
    assert lst.delegate.renders == renders, w.report()
    assert w.builds == 1 and w.created == 0, w.report()


def test_r5_the_tray_opened_again_makes_no_widget(screen):
    """The tray built at its first open; closed and opened again it makes no widget (R5) and lays nothing out."""
    seed, win, writer = screen
    open_tray(win)
    settle(200)
    tray_of(win).close()
    settle(200)
    with wc.measure(win, readers=[win.services.library]) as w:
        open_tray(win)
        settle(200)
    assert w.created == 0 and w.deleted == 0, w.report()
    assert w.builds == 0 and w.hints == 0, w.report()


def test_the_top_icon_draws_afresh_only_the_rows_its_arrival_changes_on_current(screen):
    """↑ *Top* on an arrival: it leaves the tray and lands at Current's top — S19's written skip (rows came: Qt lays
    the list out again, its viewport repainted from kept pictures), so the rule is the pictures: the new row, the
    hero that hands Up Next on and the row it becomes at most; one view; the toast its one new widget at most."""
    seed, win, writer = screen
    open_tray(win)
    settle(200)
    lst = win.page_widgets["current"].list
    row = next(r for r in tray_rows(win) if r.icon_kind == "top")
    n = len(tray_rows(win))
    renders = lst.delegate.renders
    with wc.measure(win, readers=[win.services.library]) as w:
        row.click("icon")
        assert wait_until(lambda: len(tray_rows(win)) == n - 1, 5)
        settle(200)
    assert lst.delegate.renders - renders <= 3, w.report()
    assert w.builds == 1, w.report()
    assert w.created <= 1, w.report()


def test_finished_on_a_watched_arrival_repaints_the_tray_and_its_toast_never_current(screen):
    """✓ *Finished* on the watched arrival: it leaves the tray for Finished (a page not shown) — the tray repaints
    (where it stood: it grew shorter), the inset's count, the toast with D14's choice and the bar's line; no row of
    Current drawn afresh, nothing of Current outside the tray repainted, one view built."""
    seed, win, writer = screen
    open_tray(win)
    settle(200)
    lst = win.page_widgets["current"].list
    fin = win.page_widgets["finished"]
    row = next(r for r in tray_rows(win) if r.icon_kind == "finished")
    n = len(tray_rows(win))
    renders = lst.delegate.renders
    tray = _with_shadow(win, tray_of(win))
    with wc.measure(win, readers=[win.services.library]) as w:
        row.click("icon")
        assert wait_until(lambda: len(tray_rows(win)) == n - 1, 5)
        settle(200)
    toast = wc.rect_in_window(win.toasts.card).adjusted(-48, -48, 48, 48)
    bar = QRect(0, wc.rect_in_window(win.dock).top() - 24, win.width(), win.height())
    assert lst.delegate.renders == renders, w.report()
    assert w.painted_in(fin) == 0, w.report()
    tabs = wc.rect_in_window(win.findChild(QWidget, "tabbar"))   # Finished's count: one more
    assert w.paints_outside_rect(tray, wc.rect_in_window(win.arrivals_inset), toast, bar, tabs) == [], w.report()
    assert w.builds == 1, w.report()
