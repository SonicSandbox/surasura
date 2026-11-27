"""The window's listeners that must hear the library shown now (BRIDGE-2; SEARCH-BRIDGE found them).

What a wrong answer would cost: Settings' level numbers (the readout under the level, each band's words and hours)
that never move when the library does — they listened on the window's main bridge, built without a library, so no
view ever reached them; or the opposite, a read of the level for every view while Settings is not even shown. And a
window opened without a library whose search never comes back once a language with one is shown.

A real window, a real reader over the seed library, the drag tests' writer (`apply`: a move lands in the library, so
the reader's next view holds it). Only `read_level` is wrapped, to count it (the real read runs).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import settings_live as live
from app.qt import shell
from app.services import library_reader
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, _stones_sheet, world  # noqa: F401  (the stones' sheet, the window)


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
    """Wait until the level's reads stop: none running, none started for `quiet` seconds -> their count."""
    n = -1
    while n != len(reads):
        n = len(reads)
        wait_until(lambda: len(reads) != n, quiet)
        assert wait_until(lambda: not page.live._level["busy"], 10)
    return len(reads)


def open_settings(win):
    win.show_tab("settings")
    page = win.settings_page
    assert wait_until(lambda: page.built, 20)
    return page


def a_move(seed, writer, n=0):
    """A learner's move: a Soon title to 6+ Months (the writer saves it into the library; the reader publishes)."""
    soon = [r["id"] for r in seed.items if r["tier"] == "soon"]
    writer.move([soon[n]], "goal")


def test_a_move_while_settings_is_open_reads_the_level_numbers_again_once(world, monkeypatch):
    # the readout under the level says how much of your library each band covers: a move changes it, and Settings
    # open must show the new numbers (before: the listener was on the main bridge, which no view ever reaches)
    reads = count_reads(monkeypatch)
    seed, win, writer = world()
    page = open_settings(win)
    before = settled(reads, page)
    views = views_of(win)
    a_move(seed, writer)
    assert wait_until(lambda: views, 10)
    after = settled(reads, page)
    assert after - before == 1, (after - before, len(views))       # one read for the move, never one per view


def test_a_move_while_settings_is_hidden_reads_nothing_until_settings_shows_then_once(world, monkeypatch):
    # the lead's call: no read per move — a move while Settings is out of sight only marks the numbers stale; the
    # next time Settings shows they are read once (two moves meanwhile: still once)
    reads = count_reads(monkeypatch)
    seed, win, writer = world()
    page = open_settings(win)
    win.show_tab("current")
    before = settled(reads, page)
    views = views_of(win)
    a_move(seed, writer, 0)
    assert wait_until(lambda: views, 10)
    a_move(seed, writer, 1)
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
    seed, win, writer = world()
    page = open_settings(win)
    first = win.library_bridge
    win._show_switched(win._reader_shown, writer)                   # the switch's bridge steps, forced (no sleep)
    assert win.library_bridge is not first
    before = settled(reads, page)
    views = views_of(win)
    a_move(seed, writer)
    assert wait_until(lambda: views, 10)
    assert settled(reads, page) == before + 1


def test_a_window_opened_without_a_library_shows_the_search_once_a_library_is_switched_to(qapp):
    # a first open with no library hides the search; picking a language that has one must bring it back
    services = shell.Services()
    win = shell.open_window(qapp, services)
    seed = window_seed.build(files=window_seed.SMALL)
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
    writer = FakeWriter(seed.library)
    try:
        win.show()
        assert win.search.isHidden()
        services.library, services.writer = reader, writer           # what `Services._switch_library` sets
        win._show_switched(reader, writer)
        QApplication.processEvents()
        assert not win.search.isHidden()
    finally:
        win.close()
        services.shutdown(0.5)
