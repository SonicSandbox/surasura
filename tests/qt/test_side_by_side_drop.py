"""Kyou-B (KA-4): with *New cards come from: Current's top two, side by side* on, a drop (or a Done painted ahead of the
store) draws the top-20 line and reads what is *in the top* at once by the store's own turns (`view_rows.side_top`),
exactly where the store's next view puts them — the line never disappears while the drop waits for the store.

What a wrong answer would cost a learner: the line gone for a second after every drop (the press not reacting at
once), or drawn at the old prefix place and then jumping when the store's view lands, or the stones / *Waiting* of the
wrong files lit until then.

Every test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with real words
from tests/Test Resources/ (`library_store_support.names`).
"""
import pytest

from app.qt import drag
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES
from tests.test_side_by_side import _library


def _view(store):
    feed = store.read_feed()
    return view_rows.build({r["id"]: r for r in feed["items"]}, {w["id"]: w for w in feed["works"]}, feed["options"],
                           pieces={p["id"]: p for p in feed["pieces"]})


def _top(view):
    return next(((ln.after, ln.split) for ln in view.lines if ln.kind == "top"), None)


def _in_top(view):
    return {e.id for row in view.rows for e in row.episodes if e.in_top}


def _row_of(view, item_id):
    return next(k for k, r in enumerate(view.rows) if any(e.id == item_id for e in r.episodes))


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("which, line", [("loose_to_top", 4), ("b_above_a", 4), ("b_above_a", 3),
                                         ("b_above_a_one_missing", 4), ("as_is", 8)])
def test_a_drop_draws_the_side_by_side_line_at_once_where_the_store_will(language, which, line):
    """The line at 4 over show A (6), show B (3) and a loose file. Dropped first, the loose file is a title of its own:
    the turns mine it beside A1, then B steps into its place: A2, B1 (the line through B's row after 1). B dropped
    above A: B1, A1, B2, A2 (the
    line through A's row after 2); with B1's file missing, B2, A1, B3, A2 (a missing file never takes a turn; it waits
    in the top above B2). The drop's own view (`drag.reordered`) has the store's line and top, before the store has
    moved anything. At 3, B dropped above A: B1, A1, B2 — the last turn's file is B's, but the line goes after the
    lowest row the turns mine in (A's, after 1). At 8, as it is: A1–A4, B, the loose file — the line after the loose
    file's whole row, no split."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=line, side_by_side=True)
    if which.endswith("missing"):
        with store._writing():
            store.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (b[0],))
    view = _view(store)
    assert _top(view) is not None
    keys = [r.key for r in view.rows]
    if which != "as_is":
        moved = view.rows[_row_of(view, loose if which == "loose_to_top" else b[0])].key
        keys.remove(moved)
        keys.insert(0, moved)
    dropped = drag.reordered(view, keys)
    if which == "loose_to_top":
        store.move([loose], "now", before_id=a[0])
    elif which != "as_is":
        store.move(b, "now", before_id=a[0])
    stored = _view(store)
    assert [r.key for r in dropped.rows] == [r.key for r in stored.rows]
    assert _top(dropped) == _top(stored) and _top(stored) is not None
    assert _in_top(dropped) == _in_top(stored)
    assert [ln for ln in dropped.lines if ln.kind == "top"] == [ln for ln in stored.lines if ln.kind == "top"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_one_title_left_to_study_the_drop_reads_the_top_by_prefix_as_the_store_does(language):
    """Every file of B and the loose file watched (keep-watched off), Soon's D finished: only A is left to study, so
    the store's rule is today's prefix — the drop's view still matches the store's."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    store.set_watched(b + [loose])
    store.finish(d)
    view = _view(store)
    now = [r.key for r in view.rows if r.tier == "now"]
    keys = now[1:] + now[:1] + [r.key for r in view.rows if r.tier != "now"]     # A's row dropped last in NOW
    dropped = drag.reordered(view, keys)
    store.move(a, "now", after_id=loose)
    stored = _view(store)
    assert [r.key for r in dropped.rows] == [r.key for r in stored.rows]
    assert _top(dropped) == _top(stored)
    assert _in_top(dropped) == _in_top(stored)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_side_top_is_none_off_the_turns_and_reads_the_turns_while_two_titles_hold_files(language):
    """The pure read: the build's rows give the build's own top (two titles), and one title gives None."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    view = _view(store)
    ids, in_top = view_rows.side_top(view.rows, 4)
    assert ids == [a[0], b[0], a[1], b[1]] and in_top == _in_top(view)
    only_a = [r for r in view.rows if all(e.id in a for e in r.episodes)]
    assert view_rows.side_top(only_a, 4) is None
    store.close()
