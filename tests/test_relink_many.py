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
from app.services import moves as M
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


def test_every_pair_it_didnt_take_is_named_and_one_undo_unwinds_a_chain(lib):
    """The lenses' findings: an item gone or already at its file is named in `left`; and A → Y then B → A's old place
    undoes newest first, so both go back (forward, A's old place was still B's)."""
    a, b = lib.current()[:2]
    rel_a, rel_b = _rel(lib, a)[0], _rel(lib, b)[0]
    full_a = os.path.join(lib.data_dir, *rel_a.split("/"))
    full_b = os.path.join(lib.data_dir, *rel_b.split("/"))
    y = os.path.join(lib.data_dir, "moved", "y.srt")
    os.makedirs(os.path.dirname(y), exist_ok=True)
    shutil.move(full_a, y)                                           # A's file moved to Y …
    shutil.move(full_b, full_a)                                      # … and B's into A's old place
    with lib.store._writing():
        lib.store.conn.executemany("UPDATE items SET availability = 'missing' WHERE id = ?", [(a,), (b,)])
    change = lib.store.relink_many([(a, y), (b, full_a), (b, full_a), (10 ** 6, y)])
    assert [r["id"] for r in change.relinks] == [a, b]
    assert sorted(why for _i, why in change.left) == ["gone from the library", "there already"]
    shutil.move(full_a, full_b)                                      # the files back where the records were
    shutil.move(y, full_a)
    lib.store.undo(change)
    assert _rel(lib, a)[0] == rel_a and _rel(lib, b)[0] == rel_b



def test_a_file_in_the_trash_is_never_a_gone_files_new_place(lib):
    """The adversary's #4: the learner chooses his data folder; a removed copy in its `.trash` (purged in 30 days) is
    never what a gone episode is pointed at."""
    a = lib.current()[0]
    rel = _rel(lib, a)[0]
    trashed = os.path.join(lib.data_dir, ".trash", os.path.basename(rel))
    os.makedirs(os.path.dirname(trashed), exist_ok=True)
    shutil.move(os.path.join(lib.data_dir, *rel.split("/")), trashed)
    with lib.store._writing():
        lib.store.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (a,))
    assert lib.store.relink_many([(a, trashed)]) is None
    assert _rel(lib, a) == (rel, "missing")
    from app.services import needs
    line = needs.NeedLine(key="item:1", text="", item_id=a, label="x", number=None, rel_path=rel, actions=())
    assert needs.match_tree(lib.data_dir, "", [line]) == []                  # never found there either


def test_none_relinked_still_names_why_and_leaves_no_undo(lib, make_writer):
    """Alpha 5 (Mado): with none relinked the store returns None (an empty change would be an Undo for nothing) but
    still hands out why (`left_out`); the writer gives it to the press's ticket on the empty landing (`ticket.left`),
    so the bar can say why — and nothing is saved, nothing is on the Undo stack, the journal is emptied."""
    a, b = lib.current()[:2]
    full_b = os.path.join(lib.data_dir, *_rel(lib, b)[0].split("/"))
    outside = os.path.join(os.path.dirname(lib.data_dir), "外.srt")
    with open(outside, "w", encoding="utf-8") as f:
        f.write("字幕")
    left = []
    assert lib.store.relink_many([(a, full_b), (b, outside)], left_out=left) is None
    assert left == [(a, "another item's file"), (b, "not in the library")]
    assert lib.store.relink_many([], left_out=left) is None and len(left) == 2    # nothing asked: nothing added

    class Press:                                         # the window's ticket (`drag.Ticket`: `left` None until told)
        left = None
    w, heard = make_writer()
    press = Press()
    w.relink_many([(a, full_b), (b, outside)], label=press)
    got = []
    assert h.until(lambda: got.extend(w.landed_empty()) or press in got)
    assert press.left == [(a, "another item's file"), (b, "not in the library")]
    assert h.until(lambda: not os.path.exists(M.journal_path(lib.language)))       # its journal entry gone too
    assert heard.saved == [] and not w._undo
    assert _rel(lib, a)[0] != _rel(lib, b)[0]                     # nothing moved


def test_a_label_with_no_left_and_a_relink_that_took_some_are_as_before(lib, make_writer):
    """A plain text label (no `left`) lands as nothing unharmed; a relink that took one pair is a change with
    `change.left`, never a ticket's (its "saved" says why)."""
    a, b = lib.current()[:2]
    full_b = os.path.join(lib.data_dir, *_rel(lib, b)[0].split("/"))
    w, heard = make_writer()
    w.relink_many([(a, full_b)], label="none")
    got = []
    assert h.until(lambda: got.extend(w.landed_empty()) or "none" in got)
    (_i, moved), = _move_away(lib, [a])

    class Press:
        left = None
    press = Press()
    w.relink_many([(a, moved), (b, full_b)], label=press)
    assert h.until(lambda: heard.saved)
    assert press.left is None and heard.saved[0][0].left == [(b, "there already")]
