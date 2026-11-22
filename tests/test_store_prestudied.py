"""J-STORE (3.0.19; journey v3 SPEC §2.1–2.3, §3.3): the library store keeps which episodes are pre-studied.

Pre-studied is an episode or chapter whose words the learner went through before watching or reading it. The journey
page sets it — its end card reached (`why` 'end') or a press on its stone (`why` 'press', on or off) — through the door
(`app/services/prestudied.py`); the store keeps it in two added columns, `prestudied_at` (when) and `prestudied_by`
(how: 'end', 'press', or 'off' for an un-mark), and nothing else moves: not the order, not watched, not a tier, not a
card. An un-mark sticks (the end card met again never marks it back); Undo puts back how the mark was set. The columns
come the watched date's way: an older store gains them at a writer's open, an older Surasura never reads them, and the
copy, a Remove's trash row, Put back, Repair and a switch in place carry them.

What a wrong answer would cost a learner: an episode they un-marked lit again every time they reach its end; a mark
lost on a new PC, a Repair or a Put back; a press that re-plans or re-orders Anki; a page press kept while Surasura was
closed wiping a newer mark; a library an older build can't open.

Every test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with real
words from tests/Test Resources/.
"""
import os
import shutil
import sqlite3
import threading
import time

import pytest

from app import library_store as ls
from app.services import prestudied
from tests.test_library_store_support import LANGUAGES, library, migrated, roots, schema1_store

OLD_ITEM_FIELDS = tuple(f for f in ls.ITEM_FIELDS if f not in ls.PRESTUDIED_COLUMNS)   # an older build's copy fields
# What pre-studied must never move: an item's place, tier, watched mark and date, pins, cards' marks
OTHER_COLUMNS = ("id", "tier", "ord", "watched", "watched_at", "pinned", "changed_in", "graduated_at", "mined_at",
                 "in_learning_order", "mine_asked", "work_id", "piece_id", "availability")


def _mark(store, item_id):
    return tuple(store.conn.execute("SELECT prestudied_at, prestudied_by FROM items WHERE id = ?",
                                    (item_id,)).fetchone())


def _others(store):
    return store.conn.execute(f"SELECT {', '.join(OTHER_COLUMNS)} FROM items ORDER BY id").fetchall()


def _versions(store):
    meta = store.meta()
    return {k: meta.get(k) for k in ("state_version", "order_version", "pins_version", "availability_version")}


def _drop_columns(path):
    """The store as an older build left it: no index, no columns."""
    conn = sqlite3.connect(path)
    conn.execute("DROP INDEX IF EXISTS items_prestudied_at")
    conn.execute("ALTER TABLE items DROP COLUMN prestudied_at")
    conn.execute("ALTER TABLE items DROP COLUMN prestudied_by")
    conn.commit()
    conn.close()


def _move_db_away(db):
    for suffix in ("", "-wal", "-shm"):                         # a new PC: the JSON copy alone
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")


def _kind(call, *args):
    """The refusal a route raised (the door's RouteError, or its stand-in before the door is in the build)."""
    with pytest.raises(Exception) as caught:
        call(*args)
    assert hasattr(caught.value, "kind") and caught.value.message, caught.value
    return caught.value.kind


# --- the why rule: end card vs press vs off ----------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_end_card_marks_an_untouched_episode_and_nothing_else_moves(language):
    """Reaching the end card marks the episode pre-studied, dated now, 'end' — a status write: state_version moves, the
    order, the pins and the availability don't (no re-plan, no Anki re-order), and no other column of any item."""
    store = migrated(language)
    ep, other = store.ids("now")[:2]
    rows, versions = _others(store), _versions(store)
    change = store.set_prestudied([ep], True, "end")
    at, by = _mark(store, ep)
    assert change is not None and by == "end" and at and at <= ls._now()
    assert _mark(store, other) == (None, None), "only the episode reached"
    assert _others(store) == rows, "the order, watched, tiers and cards stay as they are"
    now = _versions(store)
    assert now["state_version"] > versions["state_version"]
    assert {k: v for k, v in now.items() if k != "state_version"} == \
        {k: v for k, v in versions.items() if k != "state_version"}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_un_mark_sticks_the_end_card_met_again_never_marks_it_back(language):
    """Marked at its end card, un-marked by a press: reaching the end card again (a re-read, a scroll back) writes
    nothing — the learner's un-mark stands. Only a press marks it again."""
    store = migrated(language)
    ep = store.ids("soon")[0]
    store.set_prestudied([ep], True, "end")
    assert store.set_prestudied([ep], False, "press") is not None
    assert _mark(store, ep) == (None, "off")
    assert store.set_prestudied([ep], True, "end") is None
    assert _mark(store, ep) == (None, "off"), "the un-mark sticks"
    store.set_prestudied([ep], True, "press")
    assert _mark(store, ep)[1] == "press"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_end_card_on_a_pressed_episode_keeps_the_press(language):
    """A press marked it; its end card reached later writes nothing: the date and 'press' stay (the chip's tip says
    *by your press*)."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.set_prestudied([ep], True, "press")
    first = _mark(store, ep)
    assert store.set_prestudied([ep], True, "end") is None
    assert _mark(store, ep) == first
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_press_writes_on_or_off_whatever_came_before(language):
    """A press always writes: off over an end card's mark, off over a never-touched episode (so its end card won't mark
    it later), on after off (a new date). A press on an episode already on keeps its date and how it was set (S19:
    nothing to write)."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    store.set_prestudied([a], True, "end")
    end = _mark(store, a)
    assert store.set_prestudied([a], True, "press") is None and _mark(store, a) == end, "already on"
    store.set_prestudied([a, b], False, "press")
    assert _mark(store, a) == _mark(store, b) == (None, "off")
    assert store.set_prestudied([a], False, "press") is None, "already off"
    assert store.set_prestudied([b], True, "end") is None
    store.set_prestudied([a], True, "press")
    at, by = _mark(store, a)
    assert by == "press" and at > end[0]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_end_card_never_un_marks_and_an_unknown_why_is_refused(language):
    """`why` 'end' only marks (an end card never takes a mark away); anything but 'end' or 'press' is a caller's bug,
    refused before anything is written."""
    store = migrated(language)
    ep = store.ids("now")[0]
    for on, why in ((False, "end"), (True, "off"), (True, None), (True, "watched")):
        with pytest.raises(ValueError):
            store.set_prestudied([ep], on, why)
    assert _mark(store, ep) == (None, None)
    assert store.set_prestudied([], True, "press") is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_press_kept_while_surasura_was_closed_never_erases_a_newer_mark(language):
    """G4: the page keeps a press while Surasura is closed and sends it later with its press time. An episode marked
    after that time keeps its newer mark; one marked before it (or never) takes the press."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    pressed = ls._now()
    store.set_prestudied([a], True, "end")                      # marked after the press was made
    store.set_prestudied([b], True, "end")
    newer = _mark(store, a)
    assert store.set_prestudied([a], False, "press", pressed_at=pressed) is None
    assert _mark(store, a) == newer
    later = ls._now()
    assert store.set_prestudied([b], False, "press", pressed_at=later) is not None
    assert _mark(store, b) == (None, "off")
    store.close()


# --- Undo --------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_puts_back_how_the_mark_was_set_and_undo_twice_gives_the_mark_again(language):
    """The toast's Undo: a press's mark undone leaves the episode as it was (never touched); undoing that Undo brings
    the very same mark back (its date, 'press'). An un-mark undone brings back the end card's mark — its date and
    'end', not a press's."""
    store = migrated(language)
    a, b = store.ids("soon")[:2]
    rows = _others(store)
    on = store.set_prestudied([a], True, "press")
    first = _mark(store, a)
    back = store.undo(on)
    assert _mark(store, a) == (None, None) and back.status
    again = store.undo(back)
    assert _mark(store, a) == first and again.status
    store.set_prestudied([b], True, "end")
    end = _mark(store, b)
    off = store.set_prestudied([b], False, "press")
    undone = store.undo(off)
    assert _mark(store, b) == end, "how it was set: the end card's"
    store.undo(undone)
    assert _mark(store, b) == (None, "off")
    assert _others(store) == rows
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_old_undo_after_a_newer_press_is_one_episode_left_as_it_is(language):
    """Marked, un-marked, marked again: the first mark's Undo finds the episode holding a newer mark and leaves it —
    one episode skipped (its date and how are one value, never two skips), the newer mark kept."""
    store = migrated(language)
    ep = store.ids("now")[0]
    first = store.set_prestudied([ep], True, "press")
    store.set_prestudied([ep], False, "press")
    store.set_prestudied([ep], True, "press")
    newest = _mark(store, ep)
    out = store.undo(first)
    assert _mark(store, ep) == newest
    assert out is not None and not out.status and out.notes == ["1 item changed since and was left as it is"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undo_kept_as_a_record_still_goes_back(language):
    """The window's journal keeps a Change as a record (`change_record`): a pre-studied change read back from it is
    still undone by its pair's value check."""
    store = migrated(language)
    ep = store.ids("now")[0]
    change = store.set_prestudied([ep], True, "end")
    store.undo(ls.change_from_record(ls.change_record(change)))
    assert _mark(store, ep) == (None, None)
    store.close()


# --- watched, Finished, the readers ------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_pre_studied_stays_after_watched_and_finished_and_is_never_a_sighting(language):
    """The mark stays once the episode is watched and once it's Finished (the stone keeps its add); the Best ranking's
    `seen_dates` ignores it: only watched and Finished are remembered context."""
    store = migrated(language)
    ep, alone = store.ids("now")[:2]
    store.set_prestudied([ep, alone], True, "press")
    marks = store.prestudied_marks()
    assert store.seen_dates() == {} and store.watched_dates() == {}, "pre-studied is not seen"
    store.set_watched([ep])
    store.finish([ep])
    assert store.prestudied_marks() == marks
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_reader_reads_ids_duplicates_unknown_ids_and_how(language):
    """`prestudied_marks`: {id: date} of the marked episodes only (an un-mark isn't one), of `ids` when given (none
    read nothing, a repeated id once, an unknown one isn't there); with `by`, {id: (date, how)}."""
    store = migrated(language)
    a, b, c = store.ids("now")[:3]
    store.set_prestudied([a], True, "end")
    store.set_prestudied([b], True, "press")
    store.set_prestudied([c], False, "press")
    assert store.prestudied_marks() == {a: _mark(store, a)[0], b: _mark(store, b)[0]}
    assert store.prestudied_marks([]) == {}
    assert store.prestudied_marks([a, a, c, 10 ** 9]) == {a: _mark(store, a)[0]}
    assert store.prestudied_marks(by=True) == {a: _mark(store, a), b: _mark(store, b)}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_command_over_many_ids_marks_only_the_library_s(language):
    """A run past the store's 500-id read chunks, with ids the store doesn't hold among them: every held one is marked
    once, in one Change, and its Undo takes them all back."""
    store = migrated(language, shows=4, episodes=10)
    held = store.ids("now") + store.ids("soon") + store.ids("goal")
    ids = held + list(range(10 ** 6, 10 ** 6 + 600))
    change = store.set_prestudied(ids, True, "end")
    assert set(store.prestudied_marks()) == set(held)
    assert len(change.status) == 2 * len(held)
    store.undo(change)
    assert store.prestudied_marks() == {}
    store.close()


# --- the columns: an older store, an older Surasura, the copy, a Remove, Repair, a switch in place ---------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_older_store_gains_the_columns_at_open_with_no_row_changed(language):
    """Additive, as the watched date: a store an older Surasura left gains both columns and their index at a writer's
    first open — every row as it was, the new columns empty, the schema version unchanged."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    path = store.db_path
    store.close()
    _drop_columns(path)
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert again._prestudied_column()
        names = [r[1] for r in again.conn.execute("PRAGMA table_info(items)")]
        assert names[-2:] == list(ls.PRESTUDIED_COLUMNS)
        now = again.conn.execute(f"SELECT {', '.join(names[:-2])} FROM items ORDER BY id").fetchall()
        assert now == rows and again.conn.execute("PRAGMA user_version").fetchone()[0] == version
        assert again.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'items_prestudied_at'").fetchone()
        assert again.prestudied_marks() == {}
    finally:
        again.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_2x_store_gains_the_columns_at_the_helpers_first_open(language):
    """A 2.5–2.7 store (schema 1) opened by the helper for its upgrade: the columns are made beside the date's, and the
    upgraded store keeps a mark."""
    _d, _u, doc = library(language, shows=2, episodes=3)
    data_dir, user_files_dir, db = schema1_store(language, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    conn = sqlite3.connect(db)
    try:
        assert set(ls.PRESTUDIED_COLUMNS) | {"watched_at"} <= {r[1] for r in conn.execute("PRAGMA table_info(items)")}
    finally:
        conn.close()
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        ep = store.ids("now")[0]
        store.set_prestudied([ep], True, "press")
        assert list(store.prestudied_marks()) == [ep]
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_still_without_the_columns_writes_nothing_and_reads_none(language, monkeypatch):
    """A busy first open leaves the columns to a later one: until then a mark writes nothing (None), the reader is
    empty, the copy carries no mark, a reader's look (mode=ro) never makes them — and none of it is an error."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    path = store.db_path
    store.close()
    _drop_columns(path)
    with monkeypatch.context() as busy:
        busy.setattr(ls.Store, "_added_prestudied", lambda self: None)     # the busy open
        store = ls.open_store(language, data_dir, user_files_dir)
        try:
            assert not store._prestudied_column()
            ep = store.ids("now")[0]
            assert store.set_prestudied([ep], True, "press") is None
            assert store.prestudied_marks() == {} and store.prestudied_marks([ep], by=True) == {}
            doc, _v, _d = store.export_snapshot()
            fields = doc["surasura_library"]["items"]["fields"]
            assert all(r[fields.index("prestudied_at")] is None for r in doc["surasura_library"]["items"]["rows"])
        finally:
            store.close()
    reader = ls.open_store(language, data_dir, user_files_dir, role="reader")
    if reader is not None:
        reader.close()
    conn = sqlite3.connect(path)
    try:
        assert "prestudied_at" not in {r[1] for r in conn.execute("PRAGMA table_info(items)")}
    finally:
        conn.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_older_surasura_still_opens_writes_and_rebuilds_a_store_we_marked(language, monkeypatch):
    """An older build knows neither column: it writes an item with its own column list (the new ones stay NULL),
    leaves the marks it doesn't know as they are, and a rebuild from our copy with its own copy fields works — the
    marks simply not read there."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ep = store.ids("now")[0]
    store.set_prestudied([ep], True, "press")
    mark = _mark(store, ep)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE      # the copy, with the marks
    version = store.conn.execute("PRAGMA user_version").fetchone()[0]
    db = store.db_path
    store.close()
    conn = sqlite3.connect(db)
    try:                                                        # an older build's writes, by its own columns
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version
        conn.execute("UPDATE items SET watched = 1 WHERE id = ?", (ep,))
        conn.commit()
        assert conn.execute("SELECT prestudied_at, prestudied_by FROM items WHERE id = ?", (ep,)).fetchone() == mark
    finally:
        conn.close()
    _move_db_away(db)
    with monkeypatch.context() as older:                        # the older build's copy fields
        older.setattr(ls, "ITEM_FIELDS", OLD_ITEM_FIELDS)
        assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert store.item(ep) is not None and store.prestudied_marks() == {}
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_marks_come_back_through_a_rebuild_from_the_copy_and_a_repair(language):
    """The JSON copy carries each item's mark and how (its item records): a library rebuilt from it (a new PC) and a
    Repair read the very same marks, an un-mark included (so the end card still never marks it)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    a, b, c = store.ids("now")[:3]
    store.set_prestudied([a], True, "end")
    store.set_prestudied([b], True, "press")
    store.set_prestudied([c], False, "press")
    want = {i: _mark(store, i) for i in (a, b, c)}
    store.record_growth({store.item(a)["rel_path"]: (120, 300, 41)})   # Kura-GS's snapshots ride the same copy
    growth = store.growth_of()
    assert growth
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = store.db_path
    store.close()
    _move_db_away(db)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert {i: _mark(store, i) for i in want} == want
    assert store.growth_of() == growth, "the growth snapshots beside the marks"
    store.close()
    ls.mark_damaged(db, "a test")                               # Repair
    assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert {i: _mark(store, i) for i in want} == want
    assert store.growth_of() == growth
    assert store.set_prestudied([c], True, "end") is None, "the un-mark still sticks"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_without_the_columns_rebuilt_from_its_own_newer_copy_keeps_every_mark(language, monkeypatch):
    """A database restored from a backup an older build made (no columns) meets its own newer copy at an open too busy
    to add them first: the rebuild makes the columns itself and keeps each mark."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ep = store.ids("now")[0]
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    db = store.db_path
    store.checkpoint()
    store.close()
    shutil.copyfile(db, db + ".backup")
    _drop_columns(db + ".backup")
    store = ls.open_store(language, data_dir, user_files_dir)
    store.set_prestudied([ep], True, "press")                   # the copy moves on past the backup, with a mark
    want = store.prestudied_marks(by=True)
    assert want and ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store.close()
    for suffix in ("-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)
    shutil.copyfile(db + ".backup", db)                         # restored
    with monkeypatch.context() as busy:
        busy.setattr(ls.Store, "_added_prestudied", lambda self: None)
        busy.setattr(ls.Store, "_added_indexes", lambda self: None)
        assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.prestudied_marks(by=True) == want, "rebuilt from the newer copy, marks and all"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_episode_put_back_keeps_its_mark(language):
    """A Remove keeps the item's whole state in its trash row; its Undo, and a later Put back from Removed, bring the
    episode back marked as it was (date and how)."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.set_prestudied([ep], True, "end")
    first = _mark(store, ep)
    change = store.remove([ep])
    assert store.prestudied_marks() == {}
    store.undo(change)
    assert _mark(store, ep) == first
    store.remove([ep])
    trash = store.conn.execute("SELECT id FROM trash WHERE item_id = ? AND restored_at IS NULL", (ep,)).fetchone()[0]
    store.restore([trash])
    assert _mark(store, ep) == first
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_trash_row_with_marks_a_store_can_t_hold_puts_back_as_never_touched(language):
    """A trash row's columns read through the pair's check: a date with no 'end' or 'press' beside it (a hand-edited
    or damaged row) comes back as never touched, an 'off' as an un-mark."""
    assert ls._prestudied_pair({"prestudied_at": "2026-11-21T10:00:00.000000Z", "prestudied_by": "end"}) == \
        ("2026-11-21T10:00:00.000000Z", "end")
    assert ls._prestudied_pair({"prestudied_at": "2026-11-21T10:00:00.000000Z", "prestudied_by": None}) == (None, None)
    assert ls._prestudied_pair({"prestudied_at": "2026-11-21T10:00:00.000000Z", "prestudied_by": "off"}) == \
        (None, "off")
    assert ls._prestudied_pair({"prestudied_at": 7, "prestudied_by": "press"}) == (None, None)
    assert ls._prestudied_pair({"prestudied_by": "watched"}) == (None, None)
    assert ls._prestudied_pair({}) == (None, None)
    store = migrated(language)
    ep = store.ids("now")[0]
    store.remove([ep])
    with store._writing():
        row = store.conn.execute("SELECT id, item_state FROM trash WHERE item_id = ?", (ep,)).fetchone()
        state = ls.json.loads(row[1])
        state["columns"].update(prestudied_at="2026-11-21T10:00:00.000000Z", prestudied_by="seen")
        store.conn.execute("UPDATE trash SET item_state = ? WHERE id = ?", (ls._dumps(state), row[0]))
    store.restore([row[0]])
    assert _mark(store, ep) == (None, None)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_books_new_edition_switched_in_place_keeps_its_parts_marks(language):
    """LM3: a book's new edition swaps each part's bytes in place, ids kept — every part keeps its mark."""
    from tests.test_sources_switch import _EDITION, _book, _chapters, _drive, _empty, _epub, _items, _look
    store, _data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        parts = [i for i, _rel in before]
        store.set_prestudied(parts[:1], True, "end")
        store.set_prestudied(parts[1:2], False, "press")
        want = {i: _mark(store, i) for i in parts}
        _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        assert _look(store, language, root)["switched"] == len(before)
        assert _items(store) == before
        assert {i: _mark(store, i) for i in parts} == want


# --- two writers -------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_two_writers_on_two_threads_lose_no_mark(language):
    """The door's handler thread opens a store of its own while the window holds its own: presses on both, at once,
    on different episodes and on the same one — every mark lands once, none lost, none an error; the same episode
    marked by both is one Change (the other finds it already on)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    eps = store.ids("now") + store.ids("soon")
    shared = eps[0]
    halves = (eps[1::2], eps[2::2])
    results, errors = [[], []], []
    start = threading.Barrier(2)

    def press(n):
        try:
            own = ls.open_store(language, data_dir, user_files_dir)
            try:
                start.wait()
                results[n].append(own.set_prestudied([shared], True, "press"))
                for ep in halves[n]:
                    results[n].append(own.set_prestudied([ep], True, "end"))
            finally:
                own.close()
        except Exception as e:                                  # (said below, never lost in the thread)
            errors.append(e)

    threads = [threading.Thread(target=press, args=(n,)) for n in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors
    assert sum(1 for r in (results[0][0], results[1][0]) if r is not None) == 1, "the shared episode: one Change"
    assert set(store.prestudied_marks()) == set(eps)
    store.close()


# --- the door's routes (app/services/prestudied.py) --------------------------------------------------------------- #

class _App:
    """The door's `journey_door.App`, as far as these routes read it: the window's language now."""

    def __init__(self, language):
        self._language = language

    def language(self):
        return self._language


def _state(language):
    return prestudied.door_state(language, None, None)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_route_marks_answers_the_mark_and_its_undo_takes_it_back(language):
    """`episode/prestudied` {id, on, why} -> {on, at, by, undo_id}; `episode/undo` {undo_id} -> {done}; the same
    undo_id asked again is gone. A press with nothing to write answers the mark now and no undo_id; the door's `state`
    answers every mark now."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.close()
    app = _App(language)
    out = prestudied.door_route({"id": ep, "on": True, "why": "end"}, app)
    assert out["on"] is True and out["by"] == "end" and out["at"] and isinstance(out["undo_id"], int)
    same = prestudied.door_route({"id": ep, "on": True, "why": "end"}, app)
    assert same == {"on": True, "at": out["at"], "by": "end", "undo_id": None}
    off = prestudied.door_route({"id": ep, "on": False, "why": "press"}, app)
    assert off["on"] is False and off["at"] is None and off["by"] == "off"
    assert prestudied.door_undo({"undo_id": off["undo_id"]}, app) == {"done": True}
    assert _state(language) == {ep: {"at": out["at"], "by": "end"}}
    assert _kind(prestudied.door_undo, {"undo_id": off["undo_id"]}, app) == "gone"
    assert prestudied.door_undo({"undo_id": out["undo_id"]}, app) == {"done": True}
    assert _state(language) == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_route_refuses_what_it_cannot_read_and_says_gone_and_stale(language):
    """Every body the page couldn't have meant is refused before the store is asked; an episode no longer in the
    library is 'gone'; a press made before a newer mark is 'stale' (the page drops it and draws the app's)."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    store.close()
    app = _App(language)
    for body in ({"id": str(a), "on": True, "why": "press"}, {"id": True, "on": True, "why": "press"},
                 {"id": a, "on": 1, "why": "press"}, {"id": a, "on": True, "why": "watched"},
                 {"id": a, "on": False, "why": "end"}, {"id": a, "on": True, "why": "press", "lang": "en"},
                 {"id": a, "on": True, "why": "press", "at": "yesterday"}, {"id": 10 ** 20, "on": True, "why": "press"},
                 {"id": 0, "on": True, "why": "press"}, {"id": a, "on": True, "why": "press", "at": 5e13},
                 {"id": a, "on": True, "why": "press", "at": -1}, {}):
        assert _kind(prestudied.door_route, body, app) == "refused", body
    assert _kind(prestudied.door_route, {"id": a, "on": True, "why": "press"}, None) == "refused", "no language"
    assert _kind(prestudied.door_route, {"id": 10 ** 9, "on": True, "why": "press"}, app) == "gone"
    pressed = int(time.time() * 1000) - 60_000                  # a press kept a minute ago
    prestudied.door_route({"id": b, "on": True, "why": "press"}, app)
    assert _kind(prestudied.door_route, {"id": b, "on": False, "why": "press", "at": pressed}, app) == "stale"
    assert _state(language)[b]["by"] == "press"
    late = prestudied.door_route({"id": b, "on": False, "why": "press", "at": int(time.time() * 1000) + 1000}, app)
    assert late["on"] is False
    for undo_id in (None, "1", True, 10 ** 12):
        assert _kind(prestudied.door_undo, {"undo_id": undo_id}, app) == "gone"


def test_the_page_s_language_wins_and_each_library_keeps_its_own_marks():
    """An episode's id is its language's store's: a page's `lang` opens that library, whatever the window's language
    is now — a Chinese page's press never marks the Japanese library's item of the same id."""
    ja = migrated("ja")
    ep = ja.ids("now")[0]
    ja.close()
    zh = migrated("zh")
    zh.close()
    out = prestudied.door_route({"id": ep, "on": True, "why": "press", "lang": "zh"}, _App("ja"))
    assert out["on"] is True
    assert list(_state("zh")) == [ep]
    assert _state("ja") == {}
    assert _state("en") is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_routes_answer_busy_or_nothing_while_the_library_isnt_ready(language):
    """No store yet (a library not built, JSON mode): a press is 'busy' (the page keeps it and sends it again), the
    state reader has nothing to say (None: the page keeps what it has) rather than failing."""
    data_dir, user_files_dir = roots(language)
    os.makedirs(data_dir, exist_ok=True)
    assert _kind(prestudied.door_route, {"id": 1, "on": True, "why": "press"}, _App(language)) == "busy"
    assert _state(language) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_route_on_the_doors_thread_beside_the_windows_store(language):
    """The door runs a route on its handler thread while the window's store is open on its own: the route's write is
    seen by the window's handle (a status write: its rows follow `state_version`)."""
    store = migrated(language)
    ep = store.ids("soon")[0]
    seen = store.meta()["state_version"]
    answers = []
    t = threading.Thread(target=lambda: answers.append(
        prestudied.door_route({"id": ep, "on": True, "why": "press"}, _App(language))))
    t.start()
    t.join(60)
    assert answers and answers[0]["on"] is True
    assert store.meta()["state_version"] > seen and store.prestudied_marks(by=True)[ep][1] == "press"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undo_asked_while_the_library_is_busy_keeps_its_id_for_the_next_ask(language, monkeypatch):
    """The page's Undo meets a busy library ('busy': it asks again): the write's id is still there, and the next ask
    takes the mark back; once it ran, the id is let go of."""
    store = migrated(language)
    ep = store.ids("now")[0]
    store.close()
    app = _App(language)
    out = prestudied.door_route({"id": ep, "on": True, "why": "press"}, app)
    with monkeypatch.context() as busy:
        busy.setattr(prestudied, "_store", lambda _language: None)
        assert _kind(prestudied.door_undo, {"undo_id": out["undo_id"]}, app) == "busy"
        assert _kind(prestudied.door_route, {"id": ep, "on": False, "why": "press"}, app) == "busy"
        assert _state(language) is None
    assert prestudied.door_undo({"undo_id": out["undo_id"]}, app) == {"done": True}
    assert _state(language) == {}
    assert _kind(prestudied.door_undo, {"undo_id": out["undo_id"]}, app) == "gone"


def test_the_undo_ids_kept_are_the_newest_hundred(monkeypatch):
    """The page can ask Undo for its last writes; the oldest beyond UNDO_KEPT are let go of (never a list that grows
    all session)."""
    monkeypatch.setattr(prestudied, "_KEPT", prestudied.OrderedDict())
    ids = [prestudied._keep("ja", object()) for _ in range(prestudied.UNDO_KEPT + 5)]
    assert list(prestudied._KEPT) == ids[5:]
