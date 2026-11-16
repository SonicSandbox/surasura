"""Kyou-D (PROVISIONAL, Sonic refines it): the small *side by side* pill on the rows of the two titles side by side has
on — read from the one shared rule (`view_rows.side_on` over `library_store.side_pair`), so it sits on exactly the two
titles Connect's top 20 and Junban take turns with; its tooltip names the other title; it moves at a drop, before the
store answers; side by side off, no row has one.

What a wrong answer would cost a learner: a pill on a title that gets no cards (or none on one that does), a pill that
stays on the old title after a drag until the store catches up, or a pill shown with the option off.

Every test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with real words
from tests/Test Resources/ (`library_store_support.names`).
"""
import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import drag, rows, strings
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES
from tests.test_side_by_side_guard import _library


def _view(store):
    feed = store.read_feed()
    return view_rows.build({r["id"]: r for r in feed["items"]}, {w["id"]: w for w in feed["works"]}, feed["options"],
                           pieces={p["id"]: p for p in feed["pieces"]})


def _pills(view, ids):
    """{letter of the row's title: the other title named} for each row with a pill."""
    of = {i: letter for letter, group in ids.items() for i in group}
    return {of[r.episodes[0].id]: r.side_with for r in view.rows if r.side_with}


def _title(view, ids, letter):
    return next(r.title for r in view.rows if r.episodes[0].id in ids[letter])


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_pill_is_on_exactly_the_two_titles_on_and_names_the_other(language):
    """The keeper's library (A2 B100 C12, the line at 20): A and B are on, C below the line isn't. Each pill's words
    name the other title; off, none."""
    store, ids = _library(language, [("A", 2), ("B", 100), ("C", 12)], 20)
    view = _view(store)
    assert _pills(view, ids) == {"A": _title(view, ids, "B"), "B": _title(view, ids, "A")}
    store.set_library_options(side_by_side=False)
    off = _view(store)
    assert _pills(off, ids) == {} and off.side_on == ()
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_pill_moves_when_a_title_runs_out_or_has_no_list_word_left(language):
    """A's files watched: it is done, C (above the line at 6) steps in — the pills move to B and C. Then C counted no
    list word still new, its next file mined: it steps aside, and with nothing else above the line, B alone is on —
    no pill at all (one title is no pair)."""
    store, ids = _library(language, [("A", 2), ("B", 3), ("C", 3)], 6)
    assert set(_pills(_view(store), ids)) == {"A", "B"}
    store.set_watched(ids["A"])
    assert set(_pills(_view(store), ids)) == {"B", "C"}
    store.receipt(ids["C"][0], "2026-10-16T00:00:00")
    store.set_side_cards([(ids["B"], 1), (ids["C"], 0)])
    assert _pills(_view(store), ids) == {}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_pill_moves_at_the_drop_where_the_store_will_put_it(language):
    """C dragged from under the book to just under A: C is above the line now and steps in beside A — the drop's own
    view (`drag.reordered`) moves the pill from B to C before the store has moved anything, and the store's view
    agrees."""
    store, ids = _library(language, [("A", 2), ("B", 30), ("C", 5)], 20)
    view = _view(store)
    assert set(_pills(view, ids)) == {"A", "B"}
    keys = [r.key for r in view.rows]
    c_key = next(r.key for r in view.rows if r.episodes[0].id in ids["C"])
    keys.remove(c_key)
    keys.insert(1, c_key)
    dropped = drag.reordered(view, keys)
    store.move(ids["C"], "now", after_id=ids["A"][-1])
    stored = _view(store)
    assert _pills(dropped, ids) == _pills(stored, ids) == {"A": _title(view, ids, "C"), "C": _title(view, ids, "A")}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_pill_is_painted_with_its_tooltip_on_up_next_and_a_row(qapp, language):
    """The list paints the pill into the two rows' pictures (Up Next's beside its *UP NEXT*, a row's at its title's
    end) and each has a hit area whose tooltip names the other title; no other row has one."""
    store, ids = _library(language, [("A", 2), ("B", 3), ("C", 3)], 6)
    view = _view(store)
    host = QWidget()
    host.resize(1100, 700)
    lst = rows.RowsView("Current", parent=host)
    lst.resize(1100, 700)
    host.show()
    entries = [(rows.HERO, view.rows[0], ())] + [(rows.ROW, r, ()) for r in view.rows[1:]]
    lst.set_entries(entries)
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    tips = {}
    for i, entry in enumerate(lst.model().entries):
        rect = lst.visualRect(lst.model().index(i, 0))
        side = [p for p in lst.delegate.parts(entry, rect) if p[0] == "side"]
        if side:
            assert rect.contains(side[0][1])
            tips[entry[1].title] = side[0][2]
    a, b = _title(view, ids, "A"), _title(view, ids, "B")
    assert tips == {a: view_rows.STRINGS["side_tip"].format(other=b), b: view_rows.STRINGS["side_tip"].format(other=a)}
    assert strings.ROWS_SIDE_PILL
    host.close()
    store.close()
