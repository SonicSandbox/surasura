"""bench_drag's own pieces (M4.1 row 4, package A): the stand-in writer the bench's window moves through, and the rows
its finish toast is played on.

What a wrong answer would cost: hold 2 blaming the window for the bench's own work, or judging a moment that never ran.
Hold 1 found the stand-in writer working a nudge out where it was called (a copy of all 20,001 items and a sort on the
GUI thread inside key-up / key-down), its placement copying every item on every move (6–60 ms on its thread, holding
Python's lock under the window), a drop on another part of the same title raising in the child (the stand-in had no
`join`; the hold keeps a child's stderr only when it fails), and toast-done-all running 10 repetitions with no toast and
no skip noted (its rows were NOW's only, and the menu moves before it had used them). Once the stand-in could join, the
key case at 20,000 files and 150 % ran menu-soon, menu-goal, key-up and key-down with no frame: the join opened its
result (as the window does), the open row filled the list, and no row was whole on screen for the moments after it.
"""
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from tests.fixtures.standin_store import StandinLibrary
from tests.qt import bench_drag
from tests.qt.test_drag import lift, move_global, release_global, settle
from tests.qt.test_item_menu import lst_of, middle_point, rows_of, split_parts, world  # noqa: F401

TITLES = ("進撃の巨人", "葬送のフリーレン", "薬屋のひとりごと", "ぼっち・ざ・ろっく！")


def _library():
    """Four titles of three episodes each, one piece a title: two in NOW, one in Soon, one in Goal."""
    items, works = [], []
    tiers = ("now", "now", "soon", "goal")
    for w, (title, tier) in enumerate(zip(TITLES, tiers), start=1):
        works.append({"id": w, "title": title})
        for e in range(1, 4):
            i = w * 10 + e
            items.append({"id": i, "tier": tier, "ord": float(w * 1024 + e * 8), "work_id": w, "piece_id": 100 + w,
                          "rel_path": f"HighPriority/{title}/{title} - {e:02d}.srt", "title": f"{title} - {e:02d}.srt",
                          "availability": "available", "watched": 0})
    return StandinLibrary(items, works)


class _Numbers:
    def __init__(self):
        self.calls = []

    def after_move(self, ids, tier, before_id=None, after_id=None):
        self.calls.append((list(ids), tier, before_id, after_id, threading.current_thread()))
        return {}


def _writer(lib):
    w = bench_drag.StandinWriter(lib, _Numbers())
    w.saved = threading.Event()
    w.changes = []

    def on_saved(change, label):
        w.changes.append(change.ids)
        w.saved.set()
    w.on_saved = on_saved
    return w


def _order(lib, tier):
    return [i for _o, i, _p in sorted(lib.tier_keys(tier))]


def _reads_on_this_thread(monkeypatch, lib):
    """Every read of the stand-in's items on the calling thread, recorded."""
    here, seen = threading.current_thread(), []
    for name in ("items", "tier_keys"):
        real = getattr(lib, name)

        def spy(*a, _real=real, _name=name, **k):
            if threading.current_thread() is here:
                seen.append(_name)
            return _real(*a, **k)
        monkeypatch.setattr(lib, name, spy)
    return seen


# --- A3: a nudge is worked out on the writer's thread -------------------------------------------------------------- #
def test_a_nudge_reads_nothing_of_the_library_on_the_callers_thread_and_lands_one_place_down(monkeypatch):
    lib = _library()
    seen = _reads_on_this_thread(monkeypatch, lib)
    w = _writer(lib)
    assert w.nudge([11, 12, 13], "down") is not None
    assert w.saved.wait(5)
    assert seen == []                                    # the GUI thread only queued it
    assert _order(lib, "now") == [21, 22, 23, 11, 12, 13]   # after the whole run of the title below
    ids, tier, before_id, after_id, thread = w.numbers.calls[0]
    assert (tier, before_id, after_id) == ("now", None, 23) and thread is not threading.current_thread()


def test_a_nudge_up_goes_before_the_whole_run_above_and_nothing_moves_at_the_tiers_top():
    lib = _library()
    w = _writer(lib)
    w.nudge([21, 22, 23], "up")
    assert w.saved.wait(5)
    assert _order(lib, "now") == [21, 22, 23, 11, 12, 13]
    w.saved.clear()
    w.nudge([21, 22, 23], "up")                         # already first: the store's nudge does nothing
    assert w.saved.wait(5)
    assert _order(lib, "now") == [21, 22, 23, 11, 12, 13]
    assert len(w.numbers.calls) == 1


# --- A4: the placement reads only its tier ------------------------------------------------------------------------ #
def test_the_placement_never_copies_every_item_and_lands_beside_its_anchor(monkeypatch):
    lib = _library()
    monkeypatch.setattr(lib, "items", lambda: pytest.fail("the placement copied every item"))
    bench_drag._place(lib, [11], "goal", before_id=42, after_id=None)
    assert _order(lib, "goal") == [41, 11, 42, 43]
    bench_drag._place(lib, [12, 13], "goal", before_id=None, after_id=43)
    assert _order(lib, "goal") == [41, 11, 42, 43, 12, 13]
    bench_drag._place(lib, [31], "goal", before_id=None, after_id=None)     # no anchor: the tier's top
    assert _order(lib, "goal") == [31, 41, 11, 42, 43, 12, 13]
    assert _order(lib, "now") == [21, 22, 23] and _order(lib, "soon") == [32, 33]
    bench_drag._place(lib, [32], "soon", before_id=999, after_id=None)      # an anchor gone: its top, never a raise
    assert _order(lib, "soon") == [32, 33]


def test_the_tier_index_follows_every_commit_and_tombstone():
    lib = _library()
    lib.commit(items=[{"id": 41, "tier": "now", "ord": 1.0}], order=True)
    lib.commit(items=[{"id": 99, "tier": "arrivals", "ord": 5.0, "piece_id": 7}], gone=[("item", 33)])
    assert _order(lib, "now") == [41, 11, 12, 13, 21, 22, 23]
    assert _order(lib, "goal") == [42, 43]
    assert _order(lib, "soon") == [31, 32]
    assert lib.tier_keys("arrivals") == [(5.0, 99, 7)]
    assert sorted(i for t in ("now", "soon", "goal", "arrivals") for i in _order(lib, t)) == \
        sorted(r["id"] for r in lib.items())


# --- A5: a drop on another part of the same title (W3.2 Q8) ------------------------------------------------------- #
def test_a_join_lands_the_other_part_after_the_first_parts_last_episode_in_its_piece():
    lib = _library()
    lib.commit(items=[{"id": 13, "piece_id": 900, "tier": "soon", "ord": 3000.0}], order=True)   # a split-off part
    w = _writer(lib)
    assert w.join([101, 900], label="進撃の巨人 1–3") is not None
    assert w.saved.wait(5)
    assert _order(lib, "now") == [11, 12, 13, 21, 22, 23]
    assert {r["piece_id"] for r in lib.items() if r["id"] in (11, 12, 13)} == {101}
    assert w.changes == [[11, 12, 13]]


def test_a_join_ahead_puts_the_earlier_episodes_just_before_the_first_part():
    lib = _library()
    lib.commit(items=[{"id": 11, "piece_id": 900, "tier": "soon", "ord": 3000.0}], order=True)   # episode 1 apart
    w = _writer(lib)
    w.join([101, 900], ahead=True)
    assert w.saved.wait(5)
    assert _order(lib, "now") == [11, 12, 13, 21, 22, 23]
    assert {r["piece_id"] for r in lib.items() if r["id"] == 11} == {101}


# --- A2: the finish toast's rows ---------------------------------------------------------------------------------- #
def _row(key, tier, watched=(0, 0, 0), source="files"):
    eps = [SimpleNamespace(id=key * 10 + n, watched=bool(x), number=n) for n, x in enumerate(watched, start=1)]
    return SimpleNamespace(key=key, tier=tier, source=source, work_id=key, episodes=eps)


def test_the_finish_toast_takes_a_soon_row_once_nows_rows_are_used():
    # the menu moves before it used Current's NOW rows: a Done finishes any Current row, so Soon's are played on
    rows_ = [_row(1, "now"), _row(2, "now"), _row(3, "soon"), _row(4, "soon", watched=(1, 1, 1)),
             _row(5, "soon", source="hato"), _row(6, "soon", watched=(0,))]
    assert [r.key for r in bench_drag.done_candidates(rows_, used={2})] == [3]
    assert [r.key for r in bench_drag.done_candidates(rows_, used={2, 3})] == []


def test_the_finish_toast_never_plays_on_up_next_or_a_goal_row():
    rows_ = [_row(1, "now"), _row(2, "goal"), _row(3, "now")]
    assert [r.key for r in bench_drag.done_candidates(rows_, used=set())] == [3]


# --- a row a join opened is closed before the next moment's row is chosen ---------------------------------------- #
def test_a_row_the_join_opened_is_closed_and_the_list_laid_out_before_the_next_moment(world):  # noqa: F811
    _seed, win, _writer = world()
    lst = lst_of(win)
    a, b = split_parts(win)
    lift(win, b)
    to = middle_point(win, a)
    move_global(win, to)
    release_global(win, to)
    settle()
    assert lst.model().open_key == rows_of(win)[a].key           # the window opens the joined part
    under = lst.model().index(a + 1, 0)                           # the row under it, pushed down by its episodes
    opened_top = lst.visualRect(under).top()
    told = []
    lst.opened.connect(told.append)
    assert bench_drag.close_open_row(lst) is True
    assert lst.model().open_key is None and told == [None]
    closed = lst.visualRect(under)
    assert closed.top() < opened_top                              # back in its place when the next row is chosen
    settle()
    assert lst.visualRect(under) == closed
    assert bench_drag.close_open_row(lst) is False and told == [None]


def test_a_moment_that_drew_no_frame_is_named_whatever_was_noted():
    # the key case's shape: the key moves noted nothing, menu-goal noted "no action"; each drew no frame
    moments = {"menu-top": {"reps": 10, "frames_n": 21}, "menu-goal": {"reps": 10, "frames_n": 0},
               "key-up": {"reps": 10, "frames_n": 0}, "key-down": {"reps": 10, "frames_n": 0},
               "toast-connect": {"reps": 10, "frames_n": 183}, "idle": {"reps": 0, "frames_n": 0}}
    assert bench_drag.unplayed(moments) == {"menu-goal": 10, "key-up": 10, "key-down": 10}
