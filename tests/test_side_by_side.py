"""Kyou-A: *New cards come from: Current's top two, side by side* — the library's side (SCOPE §2; Sonic's answers 1–5,
2026-11-15): one rule (`library_store.turns` / `side_titles` / `woven`) read by the mine line Connect fills (decision 5:
the two titles take turns filling the top 20), Generate's order (so a row's *N new* and *Learned on the way* follow the
side-by-side order), the Soon line (both titles stay above it) and the window's drawn top line.

What a wrong answer would cost a learner: the second title getting no cards because the first fills the whole line
(the tester's case: a long book on top), a title with nothing left to study taking a turn, a watched or missing file
mined, the Soon line hiding the second title being studied, an Undo that leaves the order moved — or, switched off, any
reader of the library answering differently from today.

Every test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with real words
from tests/Test Resources/ (`library_store_support.names`).
"""
import pytest

from app import library_store as ls
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES, entry, names, roots, touch, write_manifest


# --- the rule, pure ---------------------------------------------------------------------------------------------- #

def test_turns_take_one_from_each_and_the_ones_left_go_on():
    assert ls.turns([["約束1", "約束2", "約束3"], ["冒険1"]]) == ["約束1", "冒険1", "約束2", "約束3"]
    assert ls.turns([["a1", "a2"], [], ["c1", "c2", "c3"]]) == ["a1", "c1", "a2", "c2", "c3"]   # any number (N5)
    assert ls.turns([]) == [] and ls.turns([[], []]) == []


def test_woven_stands_where_the_first_title_stood_and_keeps_every_other_file_in_order():
    title = {"x1": "X", "a1": "A", "a2": "A", "b1": "B", "y1": "Y", "b2": "B", "a3": "A"}.get
    ids = ["x1", "a1", "a2", "b1", "y1", "b2", "a3"]
    assert ls.woven(ids, title, ["A", "B"]) == ["x1", "a1", "b1", "a2", "b2", "a3", "y1"]
    assert ls.woven(ids, title, []) == ids


def test_the_first_two_titles_are_those_with_a_file_to_study():
    """A title whose every file is watched (keep_watched off), missing or waiting takes no turn; an item with no work
    is a title of its own."""
    rows = [(1, "now", 10, "available", 1), (2, "now", 10, "missing", 0), (3, "now", 11, "waiting", 0),
            (4, "now", 12, "available", 0), (5, "now", None, "available", 0), (6, "soon", 13, "available", 0)]
    assert ls.side_titles(rows) == [("w", 12), ("i", 5)]
    assert ls.side_titles(rows, keep=True) == [("w", 10), ("w", 12)]


# --- a library: a long book's worth of files on top, a short show second -------------------------------------------- #

def _library(language, first=6, second=3):
    """NOW: show A (`first` episodes), show B (`second`), one loose file; Soon: show D (2 episodes). The Soon line sits
    under NOW. Returns (store, A's ids, B's ids, the loose id, D's ids)."""
    data_dir, user_files_dir = roots(language)
    words = names(language)
    a, b, loose, d = words[0], words[1], words[2], words[3]
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    now = []
    for show, count in ((a, first), (b, second)):
        for e in range(1, count + 1):
            rel = f"HighPriority/{show}/{show}_第{e:02d}話.srt"
            touch(data_dir, rel, f"{show} {e}\n")
            now.append(entry(rel))
    rel = f"HighPriority/{loose}.txt"
    touch(data_dir, rel, f"{loose}\n")
    now.append(entry(rel))
    soon = []
    for e in range(1, 3):
        rel = f"LowPriority/{d}/{d}_第{e:02d}話.srt"
        touch(data_dir, rel, f"{d} {e}\n")
        soon.append(entry(rel))
    doc["schedule"][ls.TIERS["now"][0]] = now
    doc["schedule"][ls.TIERS["soon"][0]] = soon
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    store.set_soon_line(len(store.ids("now")))
    ids = store.ids("now")
    return store, ids[:first], ids[first:first + second], ids[-1], store.ids("soon")


def _scheduled(store):
    return [e["physical_path"] for rows in store.schedule().values() for e in rows]


def _paths(store, ids):
    return [store.item(i)["rel_path"] for i in ids]


@pytest.mark.parametrize("language", LANGUAGES)
def test_off_every_reader_answers_as_today_and_on_the_two_titles_take_turns(language):
    store, a, b, loose, d = _library(language)
    before = (store._mine_ids(4), store._mine_ids(20), _scheduled(store), store.scheduled_ids(), store.ids("now"))
    assert before[0] == a[:4], "off: the top of Current, in order"
    assert store.side_by_side() == []
    version = store.versions()["order_version"]
    change = store.set_library_options(side_by_side=True)
    assert change is not None and store.versions()["order_version"] > version, "the order moved: Generate follows"
    assert store.read_feed()["options"]["side_by_side"] == 1
    assert store._mine_ids(4) == [a[0], b[0], a[1], b[1]], "decision 5: the line filled by turns"
    turned = [a[0], b[0], a[1], b[1], a[2], b[2], a[3], a[4], a[5]]
    assert store._mine_ids(9) == turned, "B runs out: A takes the rest"
    assert store._mine_ids(20) == turned + [loose] + d, "then title 3 onward, then Soon, as before"
    assert _scheduled(store)[:len(turned) + 1] == _paths(store, turned + [loose]), "Generate's order follows"
    assert [i for i, _t in store.scheduled_ids()] == turned + [loose] + d, "the window's numbers read the same order"
    assert store.side_by_side() == [a, b]
    store.undo(change)
    assert (store._mine_ids(4), store._mine_ids(20), _scheduled(store), store.scheduled_ids(),
            store.ids("now")) == before, "one Undo: every reader as before"
    assert store.read_feed()["options"]["side_by_side"] == 0
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_title_to_study_reads_exactly_as_off(language):
    """Only A holds a file to study (B's watched, the loose file and D finished): nothing to weave — today's order."""
    store, a, b, loose, d = _library(language)
    store.set_watched(b)
    store.finish([loose])
    store.finish(d)
    off = (store._mine_ids(20), _scheduled(store), store.scheduled_ids())
    store.set_library_options(side_by_side=True)
    assert (store._mine_ids(20), _scheduled(store), store.scheduled_ids()) == off
    assert store.side_by_side() == []
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_watched_or_missing_file_is_never_mined_and_a_title_with_nothing_left_takes_no_turn(language):
    store, a, b, loose, d = _library(language)
    store.set_library_options(side_by_side=True)
    store.set_watched(a[:2])
    assert store._mine_ids(4) == [a[2], b[0], a[3], b[1]]
    with store._writing():
        store.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (b[0],))
    assert store._mine_ids(4) == [a[2], b[1], a[3], b[2]]
    store.set_watched(a)                                  # A has nothing left: B and the loose file are the two
    assert store._mine_ids(4) == [b[1], loose, b[2]] + d[:1]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_soon_line_keeps_both_titles_above_it_and_comes_back_when_switched_off(language):
    """Sonic's answer 5: the Soon line after 3 files would leave B under it while it's studied; side by side, the
    first 3 turns take B's first episode, so every row down to it stays in NOW — and off again, the line is back."""
    store, a, b, loose, d = _library(language)
    store.set_soon_line(3)
    assert store.ids("now") == a[:3]
    store.set_library_options(side_by_side=True)
    assert store.ids("now") == a + b[:1]
    assert store._mine_ids(4) == [a[0], b[0], a[1], b[1]]
    store.set_library_options(side_by_side=False)
    assert store.ids("now") == a[:3]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_window_draws_the_top_by_turns(language):
    """The window's own copy of the rule (`view_rows.build`): with the line at 4, B's first two episodes are in the top
    and A's third is not; the top line is drawn through B's row after its second; off, the line is through A."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4)

    def view():
        feed = store.read_feed()
        items = {r["id"]: r for r in feed["items"]}
        works = {w["id"]: w for w in feed["works"]}
        return view_rows.build(items, works, feed["options"], pieces={p["id"]: p for p in feed["pieces"]})

    def in_top(v):
        return [e.id for row in v.rows for e in row.episodes if e.in_top]

    off = view()
    assert in_top(off) == a[:4] and off.side_by_side is False
    store.set_library_options(side_by_side=True)
    on = view()
    assert on.side_by_side is True
    assert set(in_top(on)) == set(a[:2] + b[:2])
    top = next(ln for ln in on.lines if ln.kind == "top")
    assert b[1] in {e.id for e in on.rows[top.after].episodes} and top.split == 2
    store.close()


# --- the review's cases (KA-6 … KA-8, KA-11) ------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_soon_line_at_the_top_with_side_by_side_on_still_lets_every_command_through(language):
    """KA-6: the line at 0 (nothing in NOW) is today's line; turning side by side on, moving and adding all work."""
    store, a, b, loose, d = _library(language)
    store.set_soon_line(0)
    assert store.set_library_options(side_by_side=True) is not None
    store.set_soon_line(0)
    store.move([b[0]], "soon")
    assert store.ids("now") == []
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_watched_show_above_both_titles_never_pushes_them_under_the_soon_line(language):
    """KA-7: A (6 episodes) is all watched and stays on top; the Soon line after 3 files would hold only A's watched
    files — side by side, B and the loose file are the two studied, so every row down to the turns' third stays above
    it. KA-8: the mark alone (no tier moved) settles the line at once."""
    store, a, b, loose, d = _library(language)
    store.set_soon_line(3)
    store.set_library_options(side_by_side=True)
    store.set_watched(a)
    now = store.ids("now")
    assert set(b[:2]) <= set(now) and loose in now, now
    assert store._mine_ids(3) == [b[0], loose, b[1]]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_top_line_is_drawn_after_the_lowest_row_the_turns_mine_in(language):
    """KA-11: B (3 episodes) runs out first with the line at 8: the turns mine A1–A5 and all of B, so the line sits
    after B's row, never inside A's above B's mined episodes."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=8, side_by_side=True)
    feed = store.read_feed()
    view = view_rows.build({r["id"]: r for r in feed["items"]}, {w["id"]: w for w in feed["works"]}, feed["options"],
                           pieces={p["id"]: p for p in feed["pieces"]})
    top = next(ln for ln in view.lines if ln.kind == "top")
    assert {e.id for e in view.rows[top.after].episodes} == set(b) and top.split is None
    store.close()
