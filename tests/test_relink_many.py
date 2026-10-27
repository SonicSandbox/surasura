"""K3 / K1 (alpha 4, the intent keeper's #3): *Choose a folder…* on a folder's or the library's card relinks every
matched file in ONE command — `Store.relink_many`, `Writer.relink_many` — one change, one Undo.

What a wrong answer would cost a learner: a moved folder of 3,000 copies matched file by file made 3,000 commands, 3,000
toasts' worth of saving and 3,000 Ctrl+Z to take it back; a pair that can't be (another item's file, no file there,
outside the library) must never stop the others, nor take another item's place.

A real migrated library (`tests/test_services_moves.Library`: three shows of four episodes and a loose file in NOW, Soon
and 6+ Months, Japanese and Chinese names), its files moved into a new folder inside the data folder as a learner's move
would.
"""
import os
import shutil
import time

from app import library_store as ls
from tests import services_helpers as h
from tests.test_services_moves import lib, make_writer  # noqa: F401 (fixtures)


def _move_away(lib, ids, to="moved"):
    """The files of `ids` moved into `<data>/<to>/…` keeping their places; their items marked missing as a sync would.
    -> [(item_id, new path)]."""
    pairs = []
    for i in ids:
        rel = lib.store.conn.execute("SELECT rel_path FROM items WHERE id = ?", (i,)).fetchone()[0]
        src = os.path.join(lib.data_dir, *rel.split("/"))
        dst = os.path.join(lib.data_dir, to, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        pairs.append((i, dst))
    with lib.store._writing():
        lib.store.conn.executemany("UPDATE items SET availability = 'missing' WHERE id = ?", [(i,) for i in ids])
    return pairs


def _rel(lib, i):
    return lib.store.conn.execute("SELECT rel_path, availability FROM items WHERE id = ?", (i,)).fetchone()


def test_many_files_are_relinked_in_one_change_and_one_undo_points_every_one_back(lib):
    ids = lib.current()[:5]
    before = {i: _rel(lib, i)[0] for i in ids}
    pairs = _move_away(lib, ids)
    change = lib.store.relink_many(pairs)
    assert change is not None and len(change.relinks) == 5 and change.left == []
    assert all(_rel(lib, i)[0].startswith("moved/") and _rel(lib, i)[1] == "available" for i in ids)
    lib.store.undo(change)
    assert {i: _rel(lib, i)[0] for i in ids} == before and all(_rel(lib, i)[1] == "missing" for i in ids)


def test_a_pair_that_cant_be_is_named_and_never_stops_the_others(lib):
    ids = lib.current()[:3]
    pairs = _move_away(lib, ids)
    other = lib.current()[5]
    other_path = os.path.join(lib.data_dir, *_rel(lib, other)[0].split("/"))
    outside = os.path.join(os.path.dirname(lib.data_dir), "outside.srt")
    with open(outside, "w", encoding="utf-8") as f:
        f.write("字幕")
    bad = [(ids[1], other_path), (ids[2], outside), (ids[0], pairs[0][1])]
    change = lib.store.relink_many(bad)
    assert [r["id"] for r in change.relinks] == [ids[0]]
    assert sorted(i for i, _why in change.left) == sorted([ids[1], ids[2]])
    assert _rel(lib, other)[1] == "available"                       # another item's file stays its own
    assert lib.store.relink_many([(ids[1], other_path)]) is None    # nothing it could do: no change


def test_the_writer_relinks_the_matches_in_one_command_and_one_undo(lib, make_writer):
    w, heard = make_writer()
    ids = lib.current()[:4]
    pairs = _move_away(lib, ids)
    w.relink_many(pairs, label="4 found")
    assert h.until(lambda: heard.saved)
    time.sleep(0.1)
    assert len(heard.saved) == 1 and all(_rel(lib, i)[1] == "available" for i in ids)
    w.undo(label="undo")
    assert h.until(lambda: heard.undone)
    assert len(heard.undone) == 1 and all(_rel(lib, i)[1] == "missing" for i in ids)
