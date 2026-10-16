"""W3.1a: the one title width read from the reader's answer (review B2, L6, L9) and the rows' move
path (S3), on the synthetic seed through the stand-in store, offscreen.

What a wrong answer would cost a learner:
  * a list that stutters: every Current row's string planned on the window's thread inside a paint — a tenth of a second
    at 2,000 rows the first time Current shows, and again at every text size (B2);
  * one row's change redrawing every row on screen when the title width didn't move (L6);
  * a screen reader's question re-planning a row's string each time it asks (L9);
  * a drop that lays the whole list out again and repaints every row on screen, ~80 ms at 20,000 rows, where only the
    rows it moved changed (S3).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import rows
from app.services import stone_plan, view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_current import _stones_sheet, current, seeded   # noqa: F401  (fixtures)
from tests.qt.test_rows_string import _paint_spy, _settle


def _walked(d, width, monkeypatch):
    """The title width as the window worked it out before B2: every row's plan, walked on this thread."""
    with monkeypatch.context() as m:
        m.setattr(d, "_worst", lambda: None)
        d._tw = None
        tw = d.title_w(width)
    d._tw = None
    return tw


def test_the_title_width_comes_from_the_readers_answer_without_planning_or_walking_the_rows(seeded, monkeypatch):
    seed, win = seeded(files=400, size=(1024, 800))
    lst = current(win)
    d = lst.delegate
    width = lst.visualRect(lst.model().index(1, 0)).width()
    view = win.page_widgets["current"].view_model
    assert view.worst and d._worst() is view.worst                     # the reader's answer, read from the page's view
    assert all(r.string == (stone_plan.plan_of(r), max(stone_plan.tightest(stone_plan.plan_of(r)),
                                                        stone_plan.ahead(stone_plan.plan_of(r)))) for r in view.rows)
    expected = _walked(d, width, monkeypatch)
    looked = []
    monkeypatch.setattr(d, "_info", lambda row: looked.append(row) or pytest.fail("a row looked at"))
    monkeypatch.setattr(stone_plan, "plan_of", lambda row: pytest.fail("a row planned on the window's thread"))
    d._tw, d._stat_ws = None, {}                                       # cold: a new look
    assert d.title_w(width) == expected and looked == []
    assert len(d._stat_ws) == len(view.worst)                          # the font asked once per kind of Anki count


def test_entries_that_arent_the_pages_view_are_walked_as_before(seeded, monkeypatch):
    """A list showing entries of its own (a test's, an optimistic order the page hasn't taken in) never borrows a
    view's answer that doesn't describe them."""
    seed, win = seeded(files=400, size=(1024, 800))
    lst = current(win)
    d = lst.delegate
    model = lst.model()
    model.entries = model.entries[:-1]                                 # no longer the view's rows
    assert d._worst() is None
    model.entries = [(k, r, l) for k, r, l in reversed(model.entries)]
    assert d._worst() is None


def test_a_change_on_a_row_that_isnt_the_worst_keeps_the_width_and_redraws_that_row_alone(seeded, monkeypatch):
    """L6: the one title width moves only with the row that needs the most room; a file watched on another row redraws
    that row and leaves every other row's picture (each picture keys on the width)."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    d, model = lst.delegate, lst.model()
    width = lst.visualRect(model.index(1, 0)).width()
    tw = d.title_w(width)
    worst = max(need + d._stat_w_of(kind) for kind, (need, _p) in win.page_widgets["current"].view_model.worst.items())
    lst.viewport().repaint()
    assert wait_until(lambda: not lst._warm.isActive())
    i = next(n for n, (k, r, _l) in enumerate(model.entries)
             if k == rows.ROW and r.key != model.open_key and len(r.episodes) >= 2 and
             r.string[1] + d._stat_w_of(view_rows.stat_kind(r.status)) < worst - 1 and
             any(not e.watched for e in r.episodes[r.next_index + 1:]) and
             lst.viewport().rect().contains(lst.visualRect(model.index(n, 0))))
    row = model.entries[i][1]
    ep = next(e for e in row.episodes[row.next_index + 1:] if not e.watched)
    painted = _paint_spy(lst, monkeypatch)
    renders = d.renders
    seed.library.commit(items=[{"id": ep.id, "watched": 1}])
    assert wait_until(lambda: model.entries[i][1] is not row, 10)
    _settle()
    assert d.title_w(width) == tw
    assert sorted(set(painted)) == [i] and d.renders == renders + 1


def test_painting_a_row_reads_the_readers_plan_never_plans_it_again(seeded, monkeypatch):
    """(W02) Every paint, hit-test and geometry asks `_info`: the row's own plan, the very object the reader made."""
    seed, win = seeded()
    lst = current(win)
    d = lst.delegate
    monkeypatch.setattr(stone_plan, "plan_of", lambda row: pytest.fail("planned on the window's thread"))
    d._infos.clear()
    for kind, row, _l in lst.model().entries[:8]:
        plan, need, _stat = d._info(row)
        assert plan is row.string[0] and need == row.string[1]
    lst.viewport().repaint()
    assert d._infos == {}


def test_a_screen_reader_reading_a_row_never_plans_its_string_again(seeded, monkeypatch):
    """L9: the row's words come from the reader's plan."""
    seed, win = seeded()
    lst = current(win)
    model = lst.model()
    monkeypatch.setattr(stone_plan, "plan_of", lambda row: pytest.fail("planned again"))
    for n in (0, 1, 2):
        text = model.data(model.index(n, 0), Qt.ItemDataRole.AccessibleDescriptionRole)
        row = model.entries[n][1]
        assert text.endswith(stone_plan.words(row.string[0], rows.strings.STRING_WORDS))


# --- S3: a drop moves rows, never a reset ----------------------------------------------------------------------------- #
def _big_list(win, n=2000):
    """A list of its own holding `n` one-line rows (the seed's rows over again, each its own key), shown offscreen."""
    seen = [(k, r) for k, r, _l in current(win).model().entries if k == rows.ROW]
    hero = current(win).model().entries[0]
    entries = [(rows.HERO, hero[1], ())]
    for j in range(n - 1):
        k, r = seen[j % len(seen)]
        entries.append((rows.ROW, r._replace(key=f"{r.key}-{j}"), ()))
    host = QWidget()
    host.resize(1100, 900)
    lst = rows.RowsView("Current", parent=host)
    lst.resize(1100, 900)
    host.show()
    lst.set_entries(entries)
    for _ in range(30):
        QApplication.processEvents()
    return host, lst, entries


def _moved(entries, a, b):
    out = list(entries)
    out.insert(b, out.pop(a))
    return out


def test_a_drop_at_two_thousand_rows_moves_the_rows_without_a_reset_or_a_relayout(seeded, monkeypatch):
    seed, win = seeded()
    host, lst, entries = _big_list(win)
    try:
        model, d = lst.model(), lst.delegate
        lst.viewport().repaint()
        _settle()
        resets, hints, heights = [], [], []
        model.modelReset.connect(lambda: resets.append(1))
        real, real_heights = d.sizeHint, d._heights_now
        monkeypatch.setattr(d, "sizeHint", lambda o, ix: (hints.append(ix.row()), real(o, ix))[1])
        monkeypatch.setattr(d, "_heights_now", lambda m: (heights.append(1), real_heights(m))[1])
        painted = _paint_spy(lst, monkeypatch)
        renders = d.renders
        moved = _moved(entries, 9, 3)                                  # the row at 9 dropped at 3
        assert lst.set_entries(moved) == "moved"
        lst._warm.stop()                                               # (no rows painted ahead: only the drop's own)
        assert model.changed == list(range(3, 10)) and model.entries[3][1] is entries[9][1]
        _settle()
        # no reset and no relayout: a layout asks every row's height (2,000 calls) and makes the height list again
        assert resets == [] and heights == [] and len(hints) < 100 and d._h_entries is model.entries
        assert painted and set(painted) <= set(range(3, 10))          # only the moved span repainted
        assert d.renders == renders                                    # from the rows' kept pictures
        far = _moved(moved, 1500, 1990)                                # below the screen: nothing on it repaints
        painted.clear()
        hints.clear()
        assert lst.set_entries(far) == "moved"
        lst._warm.stop()
        _settle()
        assert painted == [] and resets == [] and heights == [] and len(hints) < 100
    finally:
        host.close()


def test_a_move_that_lands_with_another_rows_change_repaints_that_row_too(seeded):
    """The drop's view can carry another change (a sync's new count on a row far from the drop): that row is listed
    with the moved span, as a "same" refresh would list it."""
    seed, win = seeded()
    host, lst, entries = _big_list(win, n=60)
    try:
        moved = _moved(entries, 9, 3)
        moved[30] = (rows.ROW, moved[30][1]._replace(line="変わった"), ())
        assert lst.set_entries(moved) == "moved" and lst.model().changed == list(range(3, 10)) + [30]
    finally:
        host.close()


def test_up_next_dropped_into_the_list_is_a_move_too(seeded):
    """The hero's row coming down (and the next row going up into the hero) is the same rows in another order: each
    place keeps its kind and its height."""
    seed, win = seeded()
    host, lst, entries = _big_list(win, n=60)
    try:
        moved = [(rows.HERO, entries[1][1], ()), (rows.ROW, entries[0][1], ())] + entries[2:]
        assert lst.set_entries(moved) == "moved" and lst.model().changed == [0, 1]
    finally:
        host.close()


def test_a_reorder_that_changes_a_places_height_or_the_rows_is_no_move(seeded):
    seed, win = seeded()
    host, lst, entries = _big_list(win, n=60)
    try:
        model = lst.model()
        line = view_rows.Line("soon", 5, "", None)
        lined = _moved(entries, 9, 3)
        lined[5] = (lined[5][0], lined[5][1], (line,))                # a line now under place 5: a new height there
        assert lst.set_entries(lined) == "reset"
        gone = entries[:20] + entries[21:]                             # a row left
        assert lst.set_entries(gone) == "reset"
        swapped = list(gone)
        swapped[4] = (rows.ROW, entries[20][1], ())                    # another row in its place: not a move
        assert lst.set_entries(swapped) == "reset"
        assert model._moved_span(model.keys, model.entries) is None    # the same order: nothing moved
    finally:
        host.close()
