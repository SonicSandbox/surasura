"""OPEN-RACE (3.0.19): the covers' disk scan waits for the window's boot, as the duties do.

What a wrong answer would cost a learner: the scan reads the whole library and walks its folders on a thread of its
own; started at the first frame it took turns at Python's lock with the numbers' first load and the list's first
build (a 20,000-file open's first view with numbers 0.5-1 s later). It needs nothing the first view shows: the covers
already recorded come from the store. A window opened without the boot's watch (no duties: a test's) scans at once.
"""
from tests.qt.test_boot_first import _Reader, _settle, _view, gated, lines, wait_until  # noqa: F401  (fixtures)


def _scans(win):
    got = []
    win.scan_covers = lambda *a, **k: got.append(1)
    return got


def test_the_covers_scan_waits_for_the_boot_then_runs_once(gated, lines):
    gated.services.library = _Reader(_view(loading=True))
    scans = _scans(gated.win)
    gated.win.start_duties()                                # (main's first slot on `first_frame`: the boot's watch)
    gated.win._frame_flushed()
    _settle()
    assert scans == [], "no scan before the list from disk is drawn"
    gated.win.show_library(_view(loading=False))
    assert wait_until(lambda: scans == [1])
    _settle()
    assert scans == [1]


def test_a_window_without_the_boots_watch_scans_at_once(gated, lines):
    gated.services.library = _Reader(_view(loading=True))
    scans = _scans(gated.win)
    gated.win._frame_flushed()                              # (no duties started: `_framed` never set)
    assert scans == [1]
