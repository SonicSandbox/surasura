"""+ Add and an Explorer drop remember where a file came from (laptop fixes, K21; SRC B1's origin record): each file
copied in from outside the data folder gets an origin record on its new item, in the same store command as the
insert — the original's absolute path, its size and time, the sha256 of the bytes copied, no source (`root` None),
`via` "add", and the video beside the original when one with its name is there (found by a listing, never opened).
Connect's `video()` then looks beside the original too, after hato's pairing and the copy's own folder.

What a wrong answer would cost a learner:
  * a subtitle added from the folder its video sits in, never paired: *No video*, the episode never mined although
    the video is right beside the file they picked;
  * a folder read later as a source bringing the same episode in a second time (SRC-7), or bringing back an episode
    they removed (SRC-8);
  * a pasted text, or a file already in the library, carrying an origin that names a temporary or Surasura's own file;
  * an Undo of an add keeping the episode out of a folder read later (an Undo is no Remove).

The library is the suite's migrated one (`lib`: ja and zh); the subtitle is a real one from tests/Test Resources under
a made-up release name in a temp "elsewhere" folder beside the test's data folder, with a few bytes as its video.
"""
import hashlib
import json
import os
import time

import pytest

from app import library_store as ls
from app.connect import runner
from tests import services_helpers as h
from tests.test_services_moves import Heard, lib, make_writer  # noqa: F401  (fixtures)
from tests.test_sources_scan import _drive, _fresh_module_state, _items, _look, _video, _write  # noqa: F401

SUBTITLE = {"ja": "placed_episode.srt", "zh": "night_market.srt"}
RELEASE = "[GroupSubs] Hoshizora Kissa - 1121 (1080p) [A1B2C3D4]"          # a made-up release name


def _original(language, folder, extra="", video=True):
    """The episode in a folder outside the library: a real subtitle (`<release>.<lang>.srt`, settled a minute back) and,
    with `video`, a few-byte `.mkv` of the same stem -> (subtitle, video or None)."""
    with open(os.path.join(h.RESOURCES, language, SUBTITLE[language]), encoding="utf-8") as f:
        text = f.read() + extra
    sub = _write(os.path.join(folder, f"{RELEASE}.{language}.srt"), text)
    mkv = _video(os.path.join(folder, f"{RELEASE}.mkv")) if video else None
    return sub, mkv


def _add(w, heard, paths, **kw):
    """+ Add's write, as the window gives it (`Adder.add_files` → `Writer.insert_at`, the top of Current) -> the new
    item's id."""
    before = len(heard.saved)
    w.insert_at(list(paths), "now", label="added", **kw)
    assert h.until(lambda: len(heard.saved) > before), heard.notes
    return heard.saved[-1][0].added[0]


def _record(store, path):
    row = store.conn.execute("SELECT item_id, pairing FROM pairings WHERE content_key = ?",
                             (ls.origin_key(path),)).fetchone()
    return (row[0], json.loads(row[1])) if row else (None, None)


def _same(a, b):
    return a is not None and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _video_of(language, item_id):
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:9"})
    return steps.video(language, {"id": 1, "item_id": item_id})


def test_an_added_subtitle_records_its_original_and_connect_finds_the_video_beside_it(lib, make_writer):
    # why: the laptop try — one episode's subtitle added through + Add › Files…, its video right beside the original;
    # the copy sits in Library/, where no video is, so only the original's folder can pair it
    w, heard = make_writer()
    sub, mkv = _original(lib.language, _drive("driveA"))
    new = _add(w, heard, [sub])
    item_id, record = _record(lib.store, sub)
    assert item_id == new
    st = os.stat(sub)
    with open(sub, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    assert record["origin"] == os.path.abspath(sub) and record["root"] is None and record["via"] == "add"
    assert (record["size"], record["mtime_ns"], record["sha256"]) == (st.st_size, st.st_mtime_ns, sha)
    assert record["producer"] == ls.SOURCE_PRODUCER                   # the origin's shape: Connect reads it as a folder's
    assert _same(record["video_path"], mkv) and record["video_size"] == os.path.getsize(mkv)
    assert "video_key" not in record                                  # the video is never opened to be recorded
    assert lib.store.origins()[ls.path_key(os.path.abspath(sub))].item_id == new
    copy = lib.store.item(new)["rel_path"]
    assert copy.startswith(ls.CONTENT_FOLDER + "/")                   # the item reads Surasura's own copy
    assert _same(_video_of(lib.language, new), mkv)


def test_a_video_that_arrives_beside_the_original_after_the_add_is_found(lib, make_writer):
    # why: a subtitle is often added before its episode finished downloading; the record names no video then, so
    # Connect must look beside the original itself (not only the copy's folder and the index)
    w, heard = make_writer()
    folder = _drive("driveA")
    sub, _none = _original(lib.language, folder, video=False)
    new = _add(w, heard, [sub])
    assert "video_path" not in _record(lib.store, sub)[1]
    assert _video_of(lib.language, new) is None                       # No video yet, never a guess
    mkv = _video(os.path.join(folder, f"{RELEASE}.mkv"))
    assert _same(_video_of(lib.language, new), mkv)
    assert _same(runner.beside_origin(_record(lib.store, sub)[1]), mkv)    # the one Qt-free lookup (▶ may call it)
    assert runner.beside_origin({"producer": "hato", "origin": sub}) is None
    assert runner.beside_origin(None) is None


def test_a_pasted_text_and_a_file_already_in_the_data_folder_get_no_origin(lib, make_writer):
    # why: a pasted text lives in a temporary folder that is removed once it lands, and a file inside the data folder
    # is Surasura's own: an origin naming either would point a later look or Connect at nothing real
    w, heard = make_writer()
    paste = _write(os.path.join(_drive("paste"), "台所の会話.txt"), "朝ごはんは何にする？\n昨日の味噌汁が残ってるよ。\n")
    pasted = _add(w, heard, [paste], origin=False)
    assert _record(lib.store, paste) == (None, None)
    trashed, _v = _original(lib.language, os.path.join(lib.data_dir, ".trash"), video=False)
    again = _add(w, heard, [trashed])                                 # the data folder's trash is copied in: no origin
    assert _record(lib.store, trashed) == (None, None)
    held = lib.store.conn.execute("SELECT COUNT(*) FROM pairings WHERE item_id IN (?, ?)", (pasted, again))
    assert held.fetchone()[0] == 0


def test_a_folder_read_later_never_brings_the_added_episode_in_twice_even_after_the_original_changed(lib, make_writer):
    # why: SRC-7 — the original is known by its record, so a source over its folder takes the file as known (followed
    # into Surasura's copy when it changed: S5), never as a second item beside the one the learner added
    w, heard = make_writer()
    folder = _drive("driveA")
    sub, _mkv = _original(lib.language, folder)
    new = _add(w, heard, [sub])
    with open(sub, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n12\n00:10:00,000 --> 00:10:02,000\n訂正版の一行。\n")
    t = time.time() - 30
    os.utime(sub, (t, t))
    count = _items(lib.store)
    root = lib.store.add_source(folder)
    result = _look(lib.store, lib.language, root)
    assert result["added"] == 0 and _items(lib.store) == count
    assert _record(lib.store, sub)[0] == new


def test_a_removed_added_episode_stays_out_of_a_folder_read_later(lib, make_writer):
    # why: SRC-8 — Remove is the way out; its exclusion (no source: `root_id` NULL) keeps a later look from bringing
    # the episode back
    w, heard = make_writer()
    folder = _drive("driveA")
    sub, _mkv = _original(lib.language, folder)
    new = _add(w, heard, [sub])
    w.remove([new], label="removed")
    assert h.until(lambda: lib.store.item(new) is None)
    rows = lib.store.conn.execute("SELECT root_id, pattern FROM exclusions WHERE kind = 'removed'").fetchall()
    assert rows == [(None, ls.path_key(os.path.abspath(sub)))]
    count = _items(lib.store)
    root = lib.store.add_source(folder)
    result = _look(lib.store, lib.language, root)
    assert result["added"] == 0 and _items(lib.store) == count


def test_an_undone_add_keeps_nothing_out_of_a_folder_read_later(lib, make_writer):
    # why: an Undo takes the add back as if it never happened; it is no Remove, so a folder read later brings the
    # episode in as any new one
    w, heard = make_writer()
    folder = _drive("driveA")
    sub, _mkv = _original(lib.language, folder)
    new = _add(w, heard, [sub])
    w.undo()
    assert h.until(lambda: heard.undone)
    assert lib.store.item(new) is None
    assert lib.store.conn.execute("SELECT COUNT(*) FROM exclusions").fetchone()[0] == 0
    count = _items(lib.store)
    root = lib.store.add_source(folder)
    result = _look(lib.store, lib.language, root)
    assert result["added"] == 1 and _items(lib.store) == count + 1


def test_the_same_original_added_again_after_it_changed_moves_its_record_to_the_new_item(lib, make_writer):
    # why: one origin, one record (its key is the table's key): the second add of a changed original must land, its
    # record on the item that holds the bytes the original has now — never a failed add
    w, heard = make_writer()
    sub, _mkv = _original(lib.language, _drive("driveA"))
    first = _add(w, heard, [sub])
    with open(sub, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n12\n00:10:00,000 --> 00:10:02,000\n訂正版の一行。\n")
    second = _add(w, heard, [sub])
    assert second != first and lib.store.item(first) is not None
    item_id, record = _record(lib.store, sub)
    assert item_id == second and record["size"] == os.path.getsize(sub)


def test_an_episode_added_after_its_shows_last_episode_records_its_original_too(lib, make_writer):
    # why: + Add puts an episode whose show is in Current right after its last episode (the store's `insert_at` at an
    # anchor, not the top): that path must record the origin as well
    w, heard = make_writer()
    now = [(i, lib.store.item(i)["rel_path"]) for i in lib.ids("now")]
    folder = next(rel.rsplit("/", 1)[0] for _i, rel in now if rel.count("/") >= 2)
    last = [i for i, rel in now if rel.startswith(folder + "/")][-1]
    sub, mkv = _original(lib.language, _drive("driveA"))
    new = _add(w, heard, [sub], after_id=last, into=folder)
    ids = lib.ids("now")
    assert ids[ids.index(last) + 1] == new
    assert _record(lib.store, sub)[0] == new
    assert _same(_video_of(lib.language, new), mkv)


# --- the review fix round (LF register: LF-7, H16, H6) --------------------------------------------------------------- #

def test_adding_a_changed_original_a_folder_already_reads_keeps_that_items_record(lib, make_writer):
    # why: LF-7 — the folder's item holds the original's record; he edits the original and adds it with + Add before a
    # look. The REPLACE moved the record to the new item: the folder's item was no longer followed, restorable or
    # counted. A record a folder's look wrote stays its item's; the new item records none
    w, heard = make_writer()
    folder = _drive("driveA")
    sub, _mkv = _original(lib.language, folder)
    root = lib.store.add_source(folder)
    held = _look(lib.store, lib.language, root, full=True)["ids"][0]
    assert _record(lib.store, sub)[0] == held
    with open(sub, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n12\n00:10:00,000 --> 00:10:02,000\n訂正版の一行。\n")
    new = _add(w, heard, [sub])
    assert new != held
    item_id, record = _record(lib.store, sub)
    assert item_id == held and record["root"] == root and record.get("via") != "add"
    assert [s["items"] for s in lib.store.sources() if s["id"] == root] == [1]


def test_an_original_whose_record_cant_be_made_is_still_added(lib, make_writer, monkeypatch):
    # why: H16 — the record is a help (Connect's video beside it); a file it can't stat or list beside (a share's
    # hiccup) must never stop the add after the copy is made
    from app.services import moves
    w, heard = make_writer()
    sub, _mkv = _original(lib.language, _drive("driveA"))

    def broken(*_a, **_k):
        raise PermissionError(13, "the share went away")
    monkeypatch.setattr(moves, "_origin_of", broken)
    new = _add(w, heard, [sub])
    assert lib.store.item(new) is not None and _record(lib.store, sub) == (None, None)


def test_one_add_lists_each_originals_folder_once(lib, make_writer, monkeypatch):
    # why: H6 — the video beside each original was found by listing its folder once per file: a season added at once
    # from a share listed the same folder once per episode
    w, heard = make_writer()
    folder = _drive("driveA")
    with open(os.path.join(h.RESOURCES, lib.language, SUBTITLE[lib.language]), encoding="utf-8") as f:
        text = f.read()
    subs = []
    for n in (1, 2, 3):                                                # three episodes of one show, one folder
        path = _write(os.path.join(folder, f"[GroupSubs] Hoshizora Kissa - {n:02d} (1080p).{lib.language}.srt"),
                      text + "。" * n)
        _video(path[:-len(f".{lib.language}.srt")] + ".mkv", body=b"fake matroska %d" % n)
        subs.append(path)
    listed, real = [], os.listdir

    def listdir(p="."):
        listed.append(os.path.normcase(os.path.abspath(p)))
        return real(p)
    monkeypatch.setattr(runner.os, "listdir", listdir)
    _add(w, heard, subs)
    monkeypatch.setattr(runner.os, "listdir", real)                  # (never `undo`: it drops the test root too)
    assert listed.count(os.path.normcase(os.path.abspath(folder))) == 1
    assert all(_record(lib.store, s)[1].get("video_path") for s in subs)


def test_a_subtitle_brought_in_for_a_video_the_learner_picked_names_that_video(lib, make_writer):
    # why: alpha 8 (A8P-6 / IK-2) — setup's *Choose a file…* given a video finds its subtitle by the library's one
    # pairing rule, which may pair by episode number; Connect looks beside by name only, so the add must name the
    # video the learner picked, else the episode is *No video* although they chose the very file
    w, heard = make_writer()
    folder = _drive("driveA")
    sub, _none = _original(lib.language, folder, video=False)
    mkv = _video(os.path.join(folder, "Hoshizora.Kissa.E1121.WEB.mkv"))           # another name, the same episode
    assert runner.beside(sub) is None                                              # (by name: nothing)
    new = _add(w, heard, [sub], origin={sub: mkv})
    _item, record = _record(lib.store, sub)
    assert _same(record["video_path"], mkv) and record["video_size"] == os.path.getsize(mkv)
    assert _same(_video_of(lib.language, new), mkv)


def test_a_picked_video_gone_before_the_add_falls_back_to_the_one_beside_by_name(lib, make_writer):
    w, heard = make_writer()
    sub, mkv = _original(lib.language, _drive("driveA"))
    _add(w, heard, [sub], origin={sub: os.path.join(os.path.dirname(sub), "deleted meanwhile.mkv")})
    assert _same(_record(lib.store, sub)[1]["video_path"], mkv)
