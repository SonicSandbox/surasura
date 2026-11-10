"""The sort screen's *Start sorting over* — the store half (Mado-O, alpha 8, Sonic 2026-10-31: "the ability to reset
from the beginning"): `Store.unsort(placed)` undoes every placement the screen made in ONE command — each title back
in New arrivals where it stood, its values (watched, the Finished date) put back — and is itself one change whose Undo
puts every title back exactly where the sort had it, after which each placement's own Undo works again. What counts
as placed on the screen (PROVISIONAL): its own placements that still stand — a title moved since (dragged in Current,
finished later) stays where the learner put it.

What a wrong answer would cost a learner:
  * a reset that leaves some sorted shows in Current, or drags along a show he moved by hand since;
  * an Undo of the reset that scatters his sorted order, or loses the Finished dates;
  * an already-watched show coming back as unwatched (it would read as *New* and its words count again);
  * a crash's replay (the journal's record of the placements) putting back something else than the press did.

Real Japanese / Chinese texts from tests/Test Resources in temp folders beside the test's data folder; made-up shows.
"""
import json
import os

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES
from tests.test_setup_sort_store import SHOWS, _source
from tests.test_sources_scan import _empty, _fresh_module_state, _look  # noqa: F401

COLUMNS = "id, tier, graduated_at, watched, in_learning_order, pinned, piece_id, changed_in"


@pytest.fixture
def library():
    """A library just read for sorting: every show in New arrivals. `library(language)` -> (store, {show: [ids in
    order]}); closed after the test."""
    opened = []

    def make(language):
        store, _data = _empty(language)
        names = SHOWS[language] + (("海辺の手紙",) if language == "ja" else ("山城旧事",))
        src = _source(language, {names[0]: 3, names[1]: 2, names[2]: 2})
        store.__enter__()
        store.test_source = src                          # (where the shows' folders are: an Ignore skips one)
        opened.append(store)
        _look(store, language, store.add_source(src), first=ls.SORT)
        by_show = {}
        for i, rel in store.conn.execute("SELECT id, rel_path FROM items ORDER BY ord, id"):
            by_show.setdefault(rel.split("/")[1], []).append(i)
        return store, by_show
    yield make
    for store in opened:
        store.__exit__(None, None, None)


def _state(store):
    """Every item's tier, values and place: (per tier the ids in order, {id: (graduated_at, watched, order, pin,
    changed_in)})."""
    order = {}
    for i, tier in store.conn.execute("SELECT id, tier FROM items ORDER BY ord, id"):
        order.setdefault(tier, []).append(i)
    values = {r[0]: r[2:] for r in store.conn.execute(f"SELECT {COLUMNS} FROM items")}
    return order, values


def _groups(values):
    """{id: values} without the piece's id, and the titles grouped as the pieces group them."""
    pieces = {}
    for i, v in values.items():
        pieces.setdefault(v[4], set()).add(i)
    return {i: v[:4] for i, v in values.items()}, sorted(sorted(g) for g in pieces.values())


def _no_versions(state):
    order, values = state
    return order, {i: v[:-1] for i, v in values.items()}


@pytest.mark.parametrize("language", LANGUAGES)
def test_start_over_puts_every_placement_back_in_new_arrivals_and_its_undo_puts_the_sort_back(language, library):
    """Current, Soon, Goal, Finished and a *Put the rest in…* — one `unsort` brings every title back to New arrivals
    as it stood before the sort (order, values); its Undo puts the sorted library back exactly (order, Finished date,
    watched, changed_in: so the placements' own Undo works again)."""
    store, shows = library(language)
    a, b, c = shows.values()
    unsorted = _state(store)
    placed = [store.place(a, "top"), store.place(b[:1], "finished"), store.place(b[1:], "goal"),
              store.place(c, "soon")]
    assert all(p is not None for p in placed)
    sorted_ = _state(store)
    assert "arrivals" not in sorted_[0]
    version = store.meta()["state_version"]

    change = store.unsort(placed)
    assert change is not None and store.meta()["state_version"] == version + 1, "ONE command"
    order, values = _no_versions(_state(store))
    assert order == _no_versions(unsorted)[0], "every title back in New arrivals, in its order"
    assert values == _no_versions(unsorted)[1], "its Finished date and values put back"

    assert store.undo(change) is not None
    assert _state(store) == sorted_, "the reset's Undo: the sort exactly as it was"
    assert store.undo(placed[-1]) is not None, "… and each placement's own Undo works again"
    assert set(c) <= set(_state(store)[0]["arrivals"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_moved_since_its_placement_stays_where_the_learner_put_it(language, library):
    """Placed on the screen, then dragged in Current or finished from there: the reset leaves it (the conflict rule);
    the others go back. Its Undo touches only what the reset moved."""
    store, shows = library(language)
    a, b, c = shows.values()
    placed = [store.place(a, "top"), store.place(b, "soon"), store.place(c, "goal")]
    store.move(a[:1], "goal")                                  # dragged elsewhere since
    store.finish(c[:1])                                        # finished later, from Goal
    moved = _state(store)[1]
    change = store.unsort(placed)
    order, values = _state(store)
    assert set(order["arrivals"]) == set(a[1:] + b + c[1:])
    assert a[0] in order["goal"] and c[0] in order["graduated"]
    assert values[a[0]] == moved[a[0]] and values[c[0]] == moved[c[0]], "untouched"
    assert {it["id"] for it in change.items} == set(a[1:] + b + c[1:])
    store.undo(change)
    order, _v = _state(store)
    assert not order.get("arrivals") and a[0] in order["goal"] and c[0] in order["graduated"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_already_watched_title_finished_on_the_screen_comes_back_watched(language, library):
    """An arrival he had watched (*Already watched*), then Finished on the screen: back in New arrivals still watched
    and with no Finished date; an unwatched one Finished comes back unwatched."""
    store, shows = library(language)
    a, b, c = shows.values()
    store.set_watched(a, True)
    before = _state(store)[1]
    placed = [store.place(a, "finished"), store.place(b, "finished"), store.place(c, "finished")]
    after_sort = _state(store)
    assert all(after_sort[1][i][0] for i in a + b + c), "dated Finished"
    change = store.unsort(placed)
    values = _state(store)[1]
    for i in a + b + c:                                    # (b and c each a placement whose values come back)
        assert values[i][:-1] == before[i][:-1]
    store.undo(change)
    assert _state(store) == after_sort


@pytest.mark.parametrize("language", LANGUAGES)
def test_nothing_left_to_put_back_writes_nothing(language, library):
    """No placements, or every title moved since: None, and the library's version doesn't move."""
    store, shows = library(language)
    a, _b, _c = shows.values()
    version = store.meta()["state_version"]
    assert store.unsort([]) is None
    assert store.meta()["state_version"] == version
    placed = store.place(a, "soon")
    store.move(a, "goal")
    version = store.meta()["state_version"]
    assert store.unsort([placed]) is None
    assert store.meta()["state_version"] == version


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_journals_record_of_the_placements_puts_back_the_same_as_the_changes(language, library):
    """`change_record` → JSON → `unsort` (a crash's replay reads the journal): the same library as the changes give."""
    store, shows = library(language)
    a, b, c = shows.values()
    placed = [store.place(a, "top"), store.place(b, "finished"), store.place(c, "goal")]
    records = json.loads(json.dumps([ls.change_record(p) for p in placed], ensure_ascii=False))
    change = store.unsort(records)
    assert change is not None and set(_state(store)[0]) == {"arrivals"}
    store.undo(change)
    assert store.unsort(placed) is not None and set(_state(store)[0]) == {"arrivals"}
    assert store.unsort(records) is None, "landed already: a second replay puts back nothing"


@pytest.mark.parametrize("language", LANGUAGES)
def test_titles_the_soon_line_moved_as_others_were_placed_still_go_back(language, library):
    """Adversary #1 (a8): more than the Soon line's worth placed in Current — each placement pushes the earlier ones'
    rows over the line (the crossing takes the pushing placement's version). Still where the screen put them (Current
    is one place): every one goes back, and the reset's Undo puts the sort back exactly."""
    store, shows = library(language)
    a, b, c = shows.values()
    store.set_soon_line(2)
    unsorted = _no_versions(_state(store))
    placed = [store.place(a, "top"), store.place(b, "top"), store.place(c, "soon")]
    sorted_ = _state(store)
    change = store.unsort(placed)
    assert _no_versions(_state(store)) == unsorted
    store.undo(change)
    assert _no_versions(_state(store)) == _no_versions(sorted_)
    assert {i: v[-1] for i, v in _state(store)[1].items()} == {i: v[-1] for i, v in sorted_[1].items()}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_in_two_placements_goes_back_by_the_newest_alone(language, library):
    """Adversary #5 (a8): finished, then put on top (not a screen path today, a store caller's): the reset undoes the
    newest placement only — the title back in Finished, watched, as that one placement's own Undo leaves it."""
    store, shows = library(language)
    a, _b, _c = shows.values()
    p1 = store.place(a, "finished")
    p2 = store.place(a, "top")
    store.unsort([p1, p2])
    rows = [store.conn.execute("SELECT watched, tier FROM items WHERE id = ?", (i,)).fetchone() for i in a]
    assert rows == [(1, "graduated")] * len(a)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_record_of_anything_but_a_placement_is_left_alone(language, library):
    """A journal record holds a placement's fields only: a record of another kind (a Remove) is never undone from it."""
    store, shows = library(language)
    a, b, _c = shows.values()
    placed = store.place(a, "goal")
    record = dict(ls.change_record(placed), kind="nudge")   # (undone from its fields, it would move the title)
    assert store.unsort([record]) is None and set(a) <= set(_state(store)[0]["goal"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_watched_mark_changed_after_the_sort_is_left_and_the_resets_undo_never_writes_it(language, library):
    """The value check: Finished on the screen (watched), then marked unwatched by hand — the reset leaves the mark, and
    its Undo never marks it watched again."""
    store, shows = library(language)
    _a, b, _c = shows.values()
    placed = store.place(b, "finished")
    store.set_watched(b[:1], False)
    change = store.unsort([placed])
    assert store.conn.execute("SELECT watched FROM items WHERE id = ?", (b[0],)).fetchone()[0] == 0
    assert all(st[0] != b[0] for st in change.status)
    store.undo(change)
    assert store.conn.execute("SELECT watched FROM items WHERE id = ?", (b[0],)).fetchone()[0] == 0


# --- SO-1 (Sonic 2026-10-31: "I did accidentally ignore something"): the screen's Ignores come back too ------------ #
@pytest.mark.parametrize("language", LANGUAGES)
def test_titles_ignored_on_the_screen_come_back_to_sort_with_the_rest(language, library):
    """An Ignore that took the title out (`remove`) and one that skipped its folder (`skip_folder`): the reset brings
    both back to New arrivals where they stood — the folder read again — beside the placements, in ONE command; the
    change names what it brought back (`ignored`), for its Undo (the writer's) to ignore again."""
    store, shows = library(language)
    a, b, c = shows.values()
    unsorted = _no_versions(_state(store))
    folder_c = os.path.join(store.test_source, list(shows)[2])
    placed = [store.place(a, "top"), store.remove(b), store.skip_folder(folder_c)]
    assert set(_state(store)[0].get("arrivals", ())) == set(), "every title sorted or ignored"
    assert store.skipped_folders()
    version = store.meta()["state_version"]
    change = store.unsort(placed)
    assert store.meta()["state_version"] == version + 1, "ONE command"
    order, values = _no_versions(_state(store))
    assert order == unsorted[0], "every title back where it stood"
    assert _groups(values) == _groups(unsorted[1]), "its values and its groups (a Remove's Undo makes new piece rows)"
    assert store.skipped_folders() == [], "the folder read again"
    assert sorted((sorted(i["ids"]), bool(i["folder"])) for i in change.ignored) ==         sorted([(sorted(b), False), (sorted(c), True)])
    store.undo(change)                                   # (the store's half: the placement back; the writer ignores)
    assert set(a) <= set(_state(store)[0]["now"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_ignore_put_back_meanwhile_is_left_and_its_record_round_trips(language, library):
    """An Ignore whose title was put back already (its own Undo, the trash's Put back) brings nothing twice; the
    journal's record of an Ignore (`change_record` → JSON) brings it back as the change does."""
    store, shows = library(language)
    a, b, _c = shows.values()
    gone = store.remove(a)
    store.undo(gone)                                     # put back meanwhile
    assert store.unsort([gone]) is None
    ignored = store.remove(b)
    record = json.loads(json.dumps(ls.change_record(ignored), ensure_ascii=False))
    change = store.unsort([record])
    assert change is not None and set(b) <= set(_state(store)[0]["arrivals"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_skipped_folder_is_read_again_by_start_over_and_skipped_again_by_its_undo(language, library):
    """The writer's half (`Writer._start_over` / `_undo_start_over`, called as the writer's thread calls them): an
    Ignore that skipped the title's folder — Start over reads the folder again and the title is back to sort; its Undo
    skips the folder again in the same write, and the Ignore's own Undo then takes back that new skip."""
    import threading
    from app.services import moves as M
    store, shows = library(language)
    _a, _b, c = shows.values()
    w = M.Writer.__new__(M.Writer)                       # (no thread: only what these steps read)
    w._cond, w._replaced, w._undo = threading.Condition(), {}, []
    ignore = M.Writer._skip_folder(w, store, {"op": "skip_folder", "path": os.path.join(store.test_source,
                                                                                         list(shows)[2])})
    reset = w._start_over(store, {"placed": [ls.change_record(ignore)]})
    reset.sources = [ignore]
    assert set(c) <= set(_state(store)[0]["arrivals"]) and store.skipped_folders() == []
    w._undo_start_over(store, reset, {})
    assert not set(c) & set(_state(store)[1]) and len(store.skipped_folders()) == 1
    again = w._replaced[ignore]
    w._undo_removed(store, again, {})
    assert set(c) <= set(_state(store)[0]["arrivals"]) and store.skipped_folders() == []


def _writer_steps():
    """The writer's steps alone (no thread): what `_start_over` / `_undo_start_over` read."""
    import threading
    from app.services import moves as M
    w = M.Writer.__new__(M.Writer)
    w._cond, w._replaced, w._undo = threading.Condition(), {}, []
    return M, w


def _skip_and_start_over(store, shows, placed=()):
    """Ignore show C by skipping its folder (and any `placed` before it), then Start over. -> (writer, ignore, reset)."""
    M, w = _writer_steps()
    ignore = M.Writer._skip_folder(w, store, {"op": "skip_folder", "path": os.path.join(store.test_source,
                                                                                         list(shows)[2])})
    changes = list(placed) + [ignore]
    reset = w._start_over(store, {"placed": [ls.change_record(c) for c in changes]})
    reset.sources = changes
    return w, ignore, reset


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_resets_undo_ignores_only_the_untouched_titles_when_one_was_placed_since(language, library):
    """Intent SO-1 #1: a title of the skipped folder placed after the reset — its Undo leaves that one, ignores the
    rest as titles alone, and leaves the folder read (it holds a placed title now)."""
    store, shows = library(language)
    _a, _b, c = shows.values()
    w, _ignore, reset = _skip_and_start_over(store, shows)
    store.place(c[:1], "goal")
    w._undo_start_over(store, reset, {})
    order = _state(store)[0]
    assert c[0] in order["goal"] and not set(c[1:]) & set(_state(store)[1])
    assert store.skipped_folders() == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_that_cant_be_skipped_again_has_its_titles_ignored_alone(language, library, monkeypatch):
    """Its folder refused now (a folder above it skipped since, or no source): the titles are ignored alone."""
    store, shows = library(language)
    _a, _b, c = shows.values()
    w, _ignore, reset = _skip_and_start_over(store, shows)
    monkeypatch.setattr(store, "skip_refused", lambda path: "inside a skipped folder")
    w._undo_start_over(store, reset, {})
    assert not set(c) & set(_state(store)[1]) and store.skipped_folders() == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_ignores_are_given_again_even_when_every_placement_moved_since(language, library):
    """Every placement moved since the reset (left as it is): the Ignore is still given again."""
    store, shows = library(language)
    a, _b, c = shows.values()
    place = store.place(a, "top")
    w, _ignore, reset = _skip_and_start_over(store, shows, placed=[place])
    store.move(a, "goal")
    w._undo_start_over(store, reset, {})
    assert set(a) <= set(_state(store)[0]["goal"]) and not set(c) & set(_state(store)[1])
    assert len(store.skipped_folders()) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_resets_undo_with_nothing_left_to_put_back_says_it_cant(language, library):
    """Every title it brought back placed since: nothing to give again — refused (*Can't undo*), nothing written."""
    store, shows = library(language)
    _a, _b, c = shows.values()
    w, _ignore, reset = _skip_and_start_over(store, shows)
    store.place(c, "soon")
    before = _state(store)
    with pytest.raises(ls.UndoRefused):
        w._undo_start_over(store, reset, {})
    assert _state(store) == before and store.skipped_folders() == []
