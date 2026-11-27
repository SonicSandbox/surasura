"""Settings' level numbers read again only when what they are read from moves (BRIDGE-2; SEARCH-BRIDGE found the dead
listener).

The numbers (the readout under the level, each band's words and hours) are read from the token store, the learner's
word lists and the band the last Generate remembered — never the library's order. So: a move reads nothing; a word
list's write, a Generate's end and the indexer's run each read once while Settings shows; out of sight each only marks
the numbers stale, read once at the next show. What a wrong answer would cost: a read of the whole token store for
every move (the listener the lead first asked for), or numbers that stay old after an Ignore word or a Generate.

A real window, a real reader over the seed library, the drag tests' writer (`apply`: a move lands in the library).
Only `read_level` is wrapped, to count it (the real read runs).
"""
import threading

import pytest

pytest.importorskip("PyQt6")
from app.qt import settings_live as live
from app.services import generate
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


def settled(reads, page, quiet=0.4):
    """Wait until the level's reads stop: none waiting to be read, none running, none started for `quiet` seconds ->
    their count."""
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


def views_of(win):
    seen = []
    win.library_bridge.library_changed.connect(seen.append)
    return seen


def a_move(win, n=0):
    """A learner's move, as the window sends it: Current's `n`-th Soon row's *Goal* (its ⋯ / the picks' command:
    the window's expectation first, then the writer's commit — two views)."""
    from app.qt import drag
    base = win.moves.base()
    row = [r for r in base.rows if r.tier == "soon" and r.work_id is not None][n]
    assert win.moves.send_picks("goal", drag.ids_of(row), 1, keys=(row.key,)) is not None


def a_word_written(win, language="ja"):
    """A Known / Ignore / Still learning write landed, as *Your words* and the word card tell the window
    (`Services.words_marked`, on their worker)."""
    t = threading.Thread(target=win.services.words_marked, args=(language,))
    t.start()
    t.join(5)


def a_generate_ended(page):
    """The controller's states of one Generate, as the main bridge carries them: running, then done."""
    page.bridge.generate_changed.emit(generate.State("running", "Reading", 1, 4, "", None, 7, 1))
    page.bridge.generate_changed.emit(generate.State("done", "", 4, 4, "", None, 7, 2))


def test_a_move_with_settings_open_reads_nothing(world, monkeypatch):
    # the order isn't among what the numbers are read from: a move can't change them
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)    # (the window's reader)
    page = open_settings(win)
    before = settled(reads, page)
    views = views_of(win)
    a_move(win)
    assert wait_until(lambda: len(views) >= 2, 10)                   # the move's views came (expectation, commit)
    assert settled(reads, page) == before


def test_moves_while_settings_is_hidden_leave_nothing_to_read_at_the_next_show(world, monkeypatch):
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)
    page = open_settings(win)
    win.show_tab("current")
    before = settled(reads, page)
    views = views_of(win)
    a_move(win, 0)
    assert wait_until(lambda: len(views) >= 2, 10)
    win.show_tab("settings")
    assert settled(reads, page) == before


def test_a_word_lists_write_with_settings_open_reads_once(world, monkeypatch):
    # an Ignore word leaves the known count as it is: only the write's own news reaches Settings
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)
    page = open_settings(win)
    before = settled(reads, page)
    a_word_written(win)
    assert settled(reads, page) == before + 1
    a_word_written(win, "zh")                                        # another language's lists: not this page's
    assert settled(reads, page) == before + 1


def test_a_word_lists_write_and_a_generate_while_hidden_read_once_at_the_next_show(world, monkeypatch):
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)
    page = open_settings(win)
    win.show_tab("current")
    before = settled(reads, page)
    a_word_written(win)
    a_generate_ended(page)
    page.bridge.indexed.emit("ja")
    assert settled(reads, page) == before and page.live._level["stale"]      # hidden: nothing read
    win.show_tab("settings")
    assert settled(reads, page) == before + 1                        # shown: once for the three
    win.show_tab("current")
    win.show_tab("settings")
    assert settled(reads, page) == before + 1                        # shown again with nothing moved: no read


def test_a_generates_end_with_settings_open_reads_once_and_its_progress_never(world, monkeypatch):
    # the band Automatic remembers is written at a run's end (`record_auto_band`): its steps on the way move nothing
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)
    page = open_settings(win)
    before = settled(reads, page)
    page.bridge.generate_changed.emit(generate.State("running", "Reading", 1, 4, "", None, 7, 1))
    page.bridge.generate_changed.emit(generate.State("running", "Counting", 2, 4, "", None, 7, 2))
    assert settled(reads, page) == before
    page.bridge.generate_changed.emit(generate.State("done", "", 4, 4, "", None, 7, 3))
    assert settled(reads, page) == before + 1


def test_the_indexer_with_settings_open_reads_once(world, monkeypatch):
    reads = count_reads(monkeypatch)
    seed, win, writer = world(coalesce=True)
    page = open_settings(win)
    before = settled(reads, page)
    page.bridge.indexed.emit("ja")
    assert settled(reads, page) == before + 1
