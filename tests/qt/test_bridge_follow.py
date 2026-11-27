"""The window's listeners that must hear the library shown now (BRIDGE-2; SEARCH-BRIDGE found them).

What a wrong answer would cost: Settings' level numbers (the readout under the level, each band's words and hours)
that never move when the library does — they listened on the window's main bridge, built without a library, so no
view ever reached them; or the opposite, a read of the level for every view while Settings is not even shown.

A real window, a real reader over the seed library, the drag tests' writer (`apply`: a move lands in the library, so
the reader's next view holds it). Only `read_level` is wrapped, to count it (the real read runs).
"""
import pytest

pytest.importorskip("PyQt6")
from app.qt import settings_live as live
from tests.qt.conftest import wait_until
from tests.qt.test_drag import _stones_sheet, world  # noqa: F401  (the stones' sheet, the window)


def count_reads(monkeypatch):
    """Every `read_level` the live rows start, kept (the real read still runs)."""
    reads = []
    real = live.read_level

    def counted(*args):
        reads.append(args[1])
        return real(*args)
    monkeypatch.setattr(live, "read_level", counted)
    return reads


def views_of(win):
    """Every view the window's library bridge delivers from now on (its own list: a new bridge, a new list)."""
    seen = []
    win.library_bridge.library_changed.connect(seen.append)
    return seen


def settled(reads, page, quiet=0.4):
    """Wait until the level's reads stop: none waiting for a command's views to end, none running, none started for
    `quiet` seconds -> their count."""
    n = -1
    while n != len(reads):
        n = len(reads)
        moved = getattr(page.live, "_moved", None)           # (the build before BRIDGE-2 had none: red on reads)
        assert moved is None or wait_until(lambda: not moved.isActive(), 10)
        wait_until(lambda: len(reads) != n, quiet)
        assert wait_until(lambda: not page.live._level["busy"], 10)
    return len(reads)


def open_settings(win):
    win.show_tab("settings")
    page = win.settings_page
    assert wait_until(lambda: page.built, 20)
    return page


def a_move(win, n=0):
    """A learner's move, as the window sends it: Current's `n`-th Soon row's *Goal* (its ⋯ / the picks' command:
    the window's expectation first, then the writer's commit — two views, the reader's own)."""
    from app.qt import drag
    base = win.moves.base()
    row = [r for r in base.rows if r.tier == "soon" and r.work_id is not None][n]
    assert win.moves.send_picks("goal", drag.ids_of(row), 1, keys=(row.key,)) is not None


def test_a_move_while_settings_is_open_reads_the_level_numbers_again_once(world, monkeypatch):
    # the readout under the level says how much of your library each band covers: a move changes it, and Settings
    # open must show the new numbers (before: the listener was on the main bridge, which no view ever reaches)
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)    # (the window's reader: a move, one view)
    page = open_settings(win)
    before = settled(reads, page)
    views = views_of(win)
    a_move(win)
    assert wait_until(lambda: views, 10)
    after = settled(reads, page)
    assert after - before == 1, (after - before, len(views))       # one read for the move, never one per view


def test_a_move_while_settings_is_hidden_reads_nothing_until_settings_shows_then_once(world, monkeypatch):
    # the lead's call: no read per move — a move while Settings is out of sight only marks the numbers stale; the
    # next time Settings shows they are read once (two moves meanwhile: still once)
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)    # (the window's reader: a move, one view)
    page = open_settings(win)
    win.show_tab("current")
    before = settled(reads, page)
    views = views_of(win)
    a_move(win, 0)
    assert wait_until(lambda: views, 10)
    a_move(win, 1)
    assert wait_until(lambda: len(views) >= 2, 10)
    assert settled(reads, page) == before                            # hidden: nothing read
    win.show_tab("settings")
    assert settled(reads, page) == before + 1                        # shown: read once
    win.show_tab("current")
    win.show_tab("settings")
    assert settled(reads, page) == before + 1                        # shown again with nothing moved: no read


def test_after_a_language_switch_a_move_with_settings_open_reads_the_new_librarys_numbers(world, monkeypatch):
    # a switch makes the window a new library bridge and stops the old (`_show_switched`): Settings follows it
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)    # (the window's reader: a move, one view)
    page = open_settings(win)
    first = win.library_bridge
    win._show_switched(win._reader_shown, writer)                   # the switch's bridge steps, forced (no sleep)
    assert win.library_bridge is not first
    before = settled(reads, page)
    views = views_of(win)
    a_move(win)
    assert wait_until(lambda: views, 10)
    assert settled(reads, page) == before + 1
