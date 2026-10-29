"""LM2 (the library model's pick-and-stick): ONE subtitle group per show, picked once. PROVISIONAL (Sonic 2026-10-21:
LM-1a, T2-A1, T2-A2, A29 — accepted for building, to be checked in use).

What the scenario matrix (`test_sources_scenarios.py`, the items a learner sees) can't show: the group recorded on the
show's title and never decided again over three looks (A29), and the store half Connect's first cards call (T2-A2):
`group_of`, `keep_group`, `other_subtitles` and `switch_group` — every episode holding the other group's copy takes it
in place (its id, place and file kept; the old copy in the trash; the video moved to the new pick's record) and one
Undo puts it back, from the original or, when that is gone, from the trash. Failures leave every copy as it was: an
original changed since the look, a copy held open, an error inside the command, a busy store. Show names are made up;
the texts are real Japanese / Chinese from tests/Test Resources/.
"""
import json
import os
import subprocess
import sys

import pytest

from app import library_store as ls
from app.connect import library
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import (_OURS, _SHOWS, _drive, _empty, _fresh_module_state, _library_files,  # noqa: F401
                                     _look, _text, _video, _write)


def _sha(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _sub(src, show, group, n, ext, language, extra=""):
    """`<src>/<show>/[Subs<group>] <show> - 0n.<lang>.<ext>`, its text its own (real text + the file's mark)."""
    return _write(os.path.join(src, show, f"[Subs{group}] {show} - {n:02d}{extra}.{_OURS[language]}.{ext}"),
                  _text(language, n, f" {group}{ext}{extra}"))


def _picks(store, data_dir):
    """{item id: the sha256 of its copy} and {item id: its rel_path}."""
    rows = store.conn.execute("SELECT id, rel_path FROM items WHERE availability = 'available' ORDER BY id").fetchall()
    return {i: _sha(os.path.join(data_dir, *rel.split("/"))) for i, rel in rows}, dict(rows)


def _records(store):
    return dict(store.conn.execute("SELECT content_key, pairing FROM pairings ORDER BY content_key").fetchall())


def _work(store):
    return store.conn.execute("SELECT DISTINCT work_id FROM items").fetchone()[0]


def _show(language, src, video=True):
    """A show of three episodes with videos `<show> - 0n.mkv`: group A's `.ass` for 01–03 (the pick: `.ass` first), B's
    `.srt` for 01–02 (versions). -> (show, {n: A's path}, {n: B's path}, {n: the video})."""
    show = _SHOWS[language][1]
    a = {n: _sub(src, show, "A", n, "ass", language) for n in (1, 2, 3)}
    b = {n: _sub(src, show, "B", n, "srt", language, " (WEB 1080p)") for n in (1, 2)}   # (another size than A's)
    v = {n: _video(os.path.join(src, show, f"{show} - {n:02d}.mkv"), body=f"video {n}".encode()) for n in (1, 2, 3)} \
        if video else {}
    return show, a, b, v


def _group_b(store):
    item = store.conn.execute("SELECT id FROM items ORDER BY id").fetchone()[0]
    return next(o["group"] for o in store.other_subtitles(item) if o["label"] == "SubsB")


def _a_minute_later(monkeypatch):
    """The next start, a minute after a crash: every switch note stamped before now is stale. -1 s, never 0: Python
    3.11's time.time() on Windows ticks every 15.6 ms, so a note stamped in the same tick is 0 s old, never > 0."""
    monkeypatch.setattr(ls, "SWITCH_STALE_S", -1)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_shows_group_is_recorded_at_its_first_take_in_and_never_decided_again(language):
    """A29: a show starting mid-season — 13 from A (`.srt`) and B (`.ass`): B is picked (`.ass` first) and recorded on
    the title; episode 1 arriving later from A alone takes A's (nothing else there) and changes nothing; 14 from both
    is B's, though A's 14 is the `.ass` and ep 1, the show's earliest now, is A's."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    _sub(src, show, "A", 13, "srt", language)
    b13 = _sub(src, show, "B", 13, "ass", language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        work = _work(store)
        recorded = store.group_of(work)
        assert (recorded["group"][0], recorded["label"], recorded["by"], recorded["checked"]) ==             ("subsb", "SubsB", "look", False)
        recorded = recorded["group"]
        a1 = _sub(src, show, "A", 1, "ass", language)
        _look(store, language, root)
        _sub(src, show, "A", 14, "ass", language)
        b14 = _sub(src, show, "B", 14, "srt", language)
        _look(store, language, root)
        copies = sorted(_picks(store, data_dir)[0].values())
        assert copies == sorted([_sha(b13), _sha(a1), _sha(b14)])
        assert store.group_of(work)["group"] == recorded, "never decided again"
        assert store.show_groups() == {ls.folder_key_of(f"{ls.CONTENT_FOLDER}/{show}/x"): tuple(recorded)}


@pytest.mark.parametrize("language", LANGUAGES)
def test_other_subtitles_names_each_other_group_once_never_a_signs_track_or_a_double(language):
    """Connect's first cards ask the other groups' copies of an episode: one per group (its best: `.ass` before
    `.srt`), never the pick's own group, a signs track (a flagged file is never the text) or a double-episode file."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    _sub(src, show, "A", 1, "ass", language)
    _sub(src, show, "A", 1, "srt", language, " (720p)")
    c_srt = _sub(src, show, "C", 1, "srt", language)
    c_ass = _sub(src, show, "C", 1, "ass", language, " (BD)")
    _write(os.path.join(src, show, f"[SubsD] {show} - 01.{_OURS[language]}.signs.ass"), _text(language, 1, " D"))
    _write(os.path.join(src, show, f"[SubsE] {show} - 01-02.{_OURS[language]}.srt"), _text(language, 1, " E"))
    with store:
        _look(store, language, store.add_source(src), first=True)
        (item,) = [i for (i,) in store.conn.execute("SELECT id FROM items")]
        others = store.other_subtitles(item)
        assert [(o["label"], o["path"]) for o in others] == [("SubsC", os.path.abspath(c_ass))]
        assert others[0]["content_key"] == ls.origin_key(c_ass) and others[0]["group"][0] == "subsc"
        assert os.path.abspath(c_srt) not in [o["path"] for o in others]
        assert store.other_subtitles(10 ** 6) == []
        work = _work(store)
        change = store.switch_group(work, store.group_of(work)["group"])
        assert change.switched == [] and change.missing == [], "the pick's own group: no other file of it taken"


@pytest.mark.parametrize("language", LANGUAGES)
def test_switch_group_swaps_each_episode_in_place_and_one_undo_puts_it_back(language):
    """T2-A2: Connect's check found B fits — every episode holding B's copy takes it IN PLACE (same item, same file,
    B's bytes; the old copy in the trash; B's record the item's, holding the video Connect pairs; A's a version), 03
    with no B copy is listed missing; the group is B's, checked. A Refresh changes nothing (no flip back). One Undo puts
    back the bytes, every record exactly and the group as the look had it."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        work = _work(store)
        copies, rels = _picks(store, data_dir)
        ids = sorted(copies)
        assert sorted(copies.values()) == sorted(_sha(p) for p in a.values())
        records, group_before = _records(store), store.group_of(work)
        assert group_before["label"] == "SubsA" and not group_before["checked"]
        change = store.switch_group(work, _group_b(store))
        assert (change.kind, change.switched, change.missing, change.held) == ("switch_group", ids[:2], [ids[2]], [])
        after, rels_after = _picks(store, data_dir)
        assert sorted(rels_after) == ids, "the same items"
        assert [rels_after[i].rsplit("/", 1)[1] for i in ids] == [os.path.basename(b[1]), os.path.basename(b[2]),
                                                                  os.path.basename(a[3])], \
            "each copy named as the subtitle it holds: an .srt's bytes never sit in an .ass"
        assert not any(os.path.exists(os.path.join(data_dir, *rels[i].split("/"))) for i in ids[:2])
        assert [after[i] for i in ids] == [_sha(b[1]), _sha(b[2]), _sha(a[3])]
        sizes = dict(store.conn.execute("SELECT id, size FROM items"))
        assert all(sizes[i] == os.path.getsize(os.path.join(data_dir, *rels_after[i].split("/"))) for i in ids),             "the item's size is its new copy's (a later same-bytes check reads it)"
        for n, item in zip((1, 2), ids):
            pairing = library.pairing_of(store, item)
            assert pairing["origin"] == os.path.abspath(b[n]) and pairing["video_path"] == os.path.abspath(v[n])
            old = json.loads(_records(store)[ls.origin_key(a[n])])
            assert old["version"] is True and "video_path" not in old
        trash = os.listdir(os.path.join(data_dir, ".trash"))
        assert len([t for t in trash if not t.startswith(".")]) >= 2, "the old copies are in the trash"
        group = store.group_of(work)
        assert (group["group"][0], group["label"], group["by"], group["checked"]) == ("subsb", "SubsB", "connect", True)
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]
        _look(store, language, root, full=True)
        assert _picks(store, data_dir)[0] == after, "a Refresh never switches back"
        assert store.last_switch(work)["switched"] == 2 and store.last_switch(work)["to"] == "SubsB"
        undone = store.undo(change)
        assert undone.kind == "undo" and undone.switched == ids[:2] and not undone.notes
        assert _picks(store, data_dir) == (copies, rels)
        assert _records(store) == records
        back = store.group_of(work)
        assert (back["group"], back["label"], back["by"], back["checked"]) == \
            (group_before["group"], "SubsA", "user", True), "Connect never switches it again by itself (S16)"
        assert store.last_switch(work) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_of_a_switch_takes_the_old_text_from_the_trash_when_its_original_is_gone(language):
    """The old pick's original deleted after the switch: Undo still puts its bytes back, from the copy the switch
    sent to the trash."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        copies, _rels = _picks(store, data_dir)
        change = store.switch_group(_work(store), _group_b(store))
        os.remove(a[1])
        os.remove(a[2])
        undone = store.undo(change)
        assert undone.switched == change.switched and _picks(store, data_dir)[0] == copies


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_switch_leaves_an_episode_whose_other_original_changed_since_the_look(language):
    """B's 02 edited after the look (its bytes no longer what the look read and checked): 02 keeps A's text, listed
    held; 01 switches."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids = sorted(_picks(store, data_dir)[0])
        _write(b[2], _text(language, 2, " edited"))
        change = store.switch_group(_work(store), _group_b(store))
        assert (change.switched, change.held) == ([ids[0]], [ids[1]])
        assert _picks(store, data_dir)[0][ids[1]] == _sha(a[2])
        assert library.pairing_of(store, ids[1])["origin"] == os.path.abspath(a[2])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_switch_leaves_an_episode_whose_copy_is_held_open(language, monkeypatch):
    """The copy of 01 can't go to the trash (held open by a reader, on Windows): 01 is left as it was, its part file
    gone; 02 switches."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids = sorted(_picks(store, data_dir)[0])
        held_rel = _picks(store, data_dir)[1][ids[0]]
        real = ls.trash_file

        def trash(data, rel, to=None):
            if rel == held_rel:
                raise PermissionError("held open")
            return real(data, rel, to=to)
        monkeypatch.setattr(ls, "trash_file", trash)
        change = store.switch_group(_work(store), _group_b(store))
        assert (change.switched, change.held) == ([ids[1]], [ids[0]])
        assert _picks(store, data_dir)[0][ids[0]] == _sha(a[1])
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_error_inside_the_switch_puts_every_copy_back(language, monkeypatch):
    """Anything failing inside the command after the copies were swapped: the write rolls back and every old copy
    goes back over the new one — the bytes, the records and the group as before, no part file left."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        copies, records, group = _picks(store, data_dir)[0], _records(store), store.group_of(_work(store))
        target = _group_b(store)
        real = store._set_meta

        def broken(values):
            if ls.SHOW_GROUPS in values:
                raise RuntimeError("the disk went away")
            return real(values)
        with monkeypatch.context() as patched:
            patched.setattr(store, "_set_meta", broken)
            with pytest.raises(RuntimeError):
                store.switch_group(_work(store), target)
        assert _picks(store, data_dir)[0] == copies and _records(store) == records
        assert store.group_of(_work(store)) == group
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_busy_store_switches_nothing_and_leaves_no_part_file(language, monkeypatch):
    """The write lock not to be had (another writer): StoreBusy, before any copy moved; the part files read for the
    swap are removed."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        copies, records = _picks(store, data_dir)[0], _records(store)
        target = _group_b(store)

        def busy(*_a, **_k):
            raise ls.StoreBusy("another writer")
        with monkeypatch.context() as patched:
            patched.setattr(store, "_command", busy)
            with pytest.raises(ls.StoreBusy):
                store.switch_group(_work(store), target)
        assert _picks(store, data_dir)[0] == copies and _records(store) == records
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_leaves_an_episode_whose_text_changed_after_the_switch(language):
    """After the switch B's 01 was re-copied (its original edited, a look followed it): Undo leaves 01 as it is, with
    a note; 02 goes back."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids = sorted(_picks(store, data_dir)[0])
        change = store.switch_group(_work(store), _group_b(store))
        store.update_origin(os.path.abspath(b[1]), 1, 2, "0" * 64)
        undone = store.undo(change)
        assert undone.switched == [ids[1]] and undone.notes == ["1 episode changed since and was left as it is"]
        assert _picks(store, data_dir)[0][ids[1]] == _sha(a[2])


@pytest.mark.parametrize("language", LANGUAGES)
def test_after_a_switch_the_next_episode_comes_from_the_switched_group(language):
    """The switch is remembered on the title: episode 4 arriving from both groups (A's `.ass` first by format) is B's."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        store.switch_group(_work(store), _group_b(store))
        _sub(src, show, "A", 4, "ass", language)
        b4 = _sub(src, show, "B", 4, "srt", language)
        result = _look(store, language, root)
        assert result["added"] == 1
        assert _sha(b4) in _picks(store, data_dir)[0].values()


@pytest.mark.parametrize("language", LANGUAGES)
def test_keep_group_marks_the_title_checked_once_and_the_copy_carries_the_group(language):
    """"Checked, kept" (Connect's first cards found the pick fits): `checked` set once, the group unchanged, no version
    moved; the library's JSON copy carries the record. A wrong group or title is refused before anything is written."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src, video=False)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work = _work(store)
        version = store.meta()["state_version"]
        assert store.keep_group(work) is True and store.keep_group(work) is False
        assert store.group_of(work)["checked"] is True and store.group_of(work)["label"] == "SubsA"
        assert store.meta()["state_version"] == version
        assert store.keep_group(10 ** 6) is False and store.group_of(10 ** 6) is None
        doc, _version, _dirty = store.export_snapshot()
        assert json.loads(doc["surasura_library"]["meta"]["show_groups"])[str(work)]["checked"] is True
        with pytest.raises(ValueError):
            store.switch_group(work, "SubsB")
        with pytest.raises(ValueError):
            store.switch_group(10 ** 6, ["subsb", "x"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_existing_shows_group_is_the_group_its_earliest_episode_was_picked_from(language):
    """A show already in before its group was recorded (a library from before LM2): 02 is B's, 05 A's; 06 arriving
    from both takes B — the group of the show's earliest episode in — and records it."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    _sub(src, show, "B", 2, "srt", language)
    _sub(src, show, "A", 5, "srt", language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        with store._writing():
            store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.SHOW_GROUPS,))
        _sub(src, show, "A", 6, "ass", language)
        b6 = _sub(src, show, "B", 6, "srt", language)
        _look(store, language, root)
        assert _sha(b6) in _picks(store, data_dir)[0].values()
        assert store.group_of(_work(store))["label"] == "SubsB"


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_of_a_switch_switched_again_since_leaves_the_episodes_and_the_group_as_they_are(language):
    """B, then back to A by a second switch: undoing the FIRST finds every episode changed since — each left as it is,
    and the title's group stays the second switch's (never put back over it)."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work = _work(store)
        group_a = store.group_of(work)["group"]
        first = store.switch_group(work, _group_b(store), by="connect")
        second = store.switch_group(work, group_a, by="user")
        copies, group = _picks(store, data_dir)[0], store.group_of(work)
        assert second.switched == first.switched and group["by"] == "user"
        undone = store.undo(first)
        assert undone.switched == [] and undone.notes == ["2 episodes changed since and were left as they are"]
        assert _picks(store, data_dir)[0] == copies and store.group_of(work) == group


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_switch_leaves_an_episode_whose_records_changed_while_its_text_was_read(language, monkeypatch):
    """Between the read of B's 01 (outside the write lock) and the swap, a look re-copied A's 01 (its record moved):
    01 is left as it is, never swapped on records it no longer matches; 02 switches."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids = sorted(_picks(store, data_dir)[0])
        target = _group_b(store)
        real = ls._read_into_part

        def meanwhile(self, plan, token):
            if plan["item"] == ids[0]:
                self.update_origin(os.path.abspath(a[1]), 7, 8, _sha(a[1]))
            return real(self, plan, token)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "_read_into_part", meanwhile)
            change = store.switch_group(_work(store), target)
        assert (change.switched, change.held) == ([ids[1]], [ids[0]])
        assert _picks(store, data_dir)[0][ids[0]] == _sha(a[1])
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_that_cant_be_replaced_gets_its_old_text_back_from_the_trash(language, monkeypatch):
    """The new bytes can't take 01's place (the copy reopened between the trash and the swap): the old copy comes back
    from the trash to its place — 01 keeps A's text, listed held, no part file left; 02 switches."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids = sorted(_picks(store, data_dir)[0])
        rel = _picks(store, data_dir)[1][ids[0]]
        mtime = os.stat(os.path.join(data_dir, *rel.split("/"))).st_mtime_ns
        target = _group_b(store)
        real = os.replace

        def replace(src_path, dst):
            if str(src_path).endswith(".part") and os.path.basename(dst) == os.path.basename(b[1]):
                raise PermissionError("held open")
            return real(src_path, dst)
        with monkeypatch.context() as patched:
            patched.setattr(ls.os, "replace", replace)
            change = store.switch_group(_work(store), target)
        assert (change.switched, change.held) == ([ids[1]], [ids[0]])
        assert _picks(store, data_dir)[0][ids[0]] == _sha(a[1])
        assert library.pairing_of(store, ids[0])["origin"] == os.path.abspath(a[1])
        assert os.stat(os.path.join(data_dir, *rel.split("/"))).st_mtime_ns == mtime, "its time as it was: no re-read"
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_recorded_group_is_never_written_over_by_a_later_take_in(language):
    """A29 at the store: a take-in handing another group for a title that has one (a look that couldn't see the
    record) leaves the recorded group as it is."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src, video=False)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work, root = _work(store), store.sources(all=True, counts=False)[0]["id"]
        recorded = store.group_of(work)
        item = sorted(_picks(store, data_dir)[0])[0]
        extra = _sub(src, show, "C", 1, "srt", language)
        store.take_in(root, [{"origin": os.path.abspath(extra), "size": os.path.getsize(extra), "mtime_ns": 1,
                              "sha256": _sha(extra), "show": show, "item_id": item,
                              "show_group": {"group": ["subsc", "x"], "label": "SubsC"}}])
        assert store.group_of(work) == recorded


def test_a_switch_that_switches_nothing_records_nothing_and_one_held_waits_as_pending():
    """B's originals offline: nothing switched — no group recorded, the check stays open. Then only 02's offline: 01
    switches, the group is B's, 02 `pending`; with the drive back, switch_group again takes 02 alone."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work, ids = _work(store), sorted(_picks(store, data_dir)[0])
        target, before = _group_b(store), store.group_of(work)
        for n in (1, 2):
            os.replace(b[n], b[n] + ".away")
        change = store.switch_group(work, target)
        assert (change.switched, sorted(change.held)) == ([], ids[:2])
        assert store.group_of(work) == before and store.last_switch(work) is None
        os.replace(b[1] + ".away", b[1])
        change = store.switch_group(work, target)
        assert (change.switched, change.held) == ([ids[0]], [ids[1]])
        assert store.group_of(work)["pending"] == [ids[1]] and store.group_of(work)["checked"]
        os.replace(b[2] + ".away", b[2])
        change = store.switch_group(work, target)
        assert change.switched == [ids[1]] and store.group_of(work)["pending"] == []


def test_a_group_switched_meanwhile_is_never_written_over(monkeypatch):
    """The learner switched the title themselves while Connect's switch read its originals: Connect's episodes may
    land, but the title's group stays the learner's (G4)."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work = _work(store)
        target = _group_b(store)
        theirs = dict(store.group_of(work), by="user", checked=True)
        real = ls._read_into_part

        def meanwhile(self, plan, token):
            with self._writing():
                self._set_meta({ls.SHOW_GROUPS: json.dumps({str(work): theirs})})
            return real(self, plan, token)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "_read_into_part", meanwhile)
            store.switch_group(work, target)
        assert store.group_of(work)["by"] == "user"


def test_undo_switch_reaches_connects_switch_from_another_store_handle():
    """Connect switches in its own process; the window undoes it from the kept record (`undo_switch`), after a
    restart too: a second handle on the same library."""
    language = "zh"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        copies, records, work = _picks(store, data_dir), _records(store), _work(store)
        store.switch_group(work, _group_b(store))
        uf = store.user_files_dir
    window = ls.open_store(language, data_dir, uf)
    with window:
        assert window.last_switch(work)["by"] == "connect"
        undone = window.undo_switch(work)
        assert len(undone.switched) == 2 and _picks(window, data_dir) == copies and _records(window) == records
        assert window.undo_switch(work) is None


def test_keep_group_with_the_groups_tried_leaves_the_check_open():
    """PROVISIONAL (Sonic 2026-10-21, to be checked in use): no group fit — the groups tried are recorded and `checked` stays False, so
    Connect checks again once another group's copy is there; the same groups again write nothing."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work = _work(store)
        mine, other = store.group_of(work)["group"], _group_b(store)
        assert store.keep_group(work, tried=[mine, other]) is True
        assert store.keep_group(work, tried=[other]) is False
        got = store.group_of(work)
        assert (got["checked"], got["tried"]) == (False, [mine, other])
        assert store.keep_group(work) is True and store.group_of(work)["tried"] == []


CRASH = r"""
import os, sys
sys.path.insert(0, os.getcwd())
from app import library_store as ls
lang, data_dir, uf, work, group = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5:7]
store = ls.open_store(lang, data_dir, uf)
real = store._set_meta
def die(values):
    if ls.SHOW_GROUPS in values:
        os._exit(3)                       # killed after the copies were swapped, before the commit
    return real(values)
store._set_meta = die
store.switch_group(work, group)
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_crash_inside_a_switch_is_put_back_at_the_next_look(language, monkeypatch):
    """G3: the process killed after the copies were swapped and before the commit — the records still say A's; the
    next look puts A's copies back from the trash (the step's note says where), so copies and records agree."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        copies, records, work, target = _picks(store, data_dir), _records(store), _work(store), _group_b(store)
        uf = store.user_files_dir
    child = subprocess.run([sys.executable, "-c", CRASH, language, data_dir, uf, str(work)] + list(target),
                           cwd=os.getcwd(), capture_output=True, text=True)
    assert child.returncode == 3, child.stderr[-600:]
    _a_minute_later(monkeypatch)
    store = ls.open_store(language, data_dir, uf)
    with store:
        old = os.path.join(data_dir, *copies[1][min(copies[1])].split("/"))
        assert not os.path.exists(old), "the crash left the old copy in the trash"
        _look(store, language, root, full=True)
        assert _picks(store, data_dir) == copies and _records(store) == records
        assert not [k for k in store.meta() if k.startswith(ls.SWITCH_PENDING)]
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_switch_across_formats_leaves_a_copy_its_readers_read(language):
    """A's `.ass` (real ASS) switched to B's `.srt` (real SRT): the copy is named as B's file, so Generate's text reader
    and Connect's cue reader (both by extension) read it — never an `.srt`'s bytes in an `.ass`."""
    from app import analyzer, cues
    from tests.test_sources_scan import RESOURCES
    read = lambda n: open(os.path.join(RESOURCES, language, n), encoding="utf-8").read()   # noqa: E731
    ass, srt = {"ja": ("library_episode.ass", "placed_episode.srt"), "zh": (None, "night_market.srt")}[language]
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    a_text = read(ass) if ass else ("[Events]\nFormat: Layer, Start, End, Style, Text\n" + "".join(
        f"Dialogue: 0,0:{n // 60:02d}:{n % 60:02d}.00,0:{n // 60:02d}:{n % 60:02d}.50,Default,{line}\n" for n, line in
        enumerate(t for block in read("night_market.srt").split("\n\n") for t in block.splitlines()[2:])))
    _write(os.path.join(src, show, f"[SubsA] {show} - 01.{_OURS[language]}.ass"), a_text + "\n")
    b = _write(os.path.join(src, show, f"[SubsB] {show} - 01.{_OURS[language]}.srt"), read(srt) + "\n")
    with store:
        _look(store, language, store.add_source(src), first=True)
        item = min(_picks(store, data_dir)[0])
        store.switch_group(_work(store), _group_b(store))
        rel = _picks(store, data_dir)[1][item]
        full = os.path.join(data_dir, *rel.split("/"))
        assert rel.endswith(".srt") and _sha(full) == _sha(b)
        assert len(analyzer.extract_text(full, language)) > 0 and len(cues.read(full, language)) > 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_v2_decides_and_is_taken_by_a_switch(language):
    """The release counts before the format: 01 is A's `.ass` and B's `01v2` `.srt` — B's v2 is episode 1's text and
    B the show's group (never A's, by the format); and a switch to a group with v1 and v2 takes the v2."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    _sub(src, show, "A", 1, "ass", language)
    b1 = _write(os.path.join(src, show, f"[SubsB] {show} - 01v2.{_OURS[language]}.srt"), _text(language, 1, " Bv2"))
    _sub(src, show, "A", 2, "ass", language)
    _sub(src, show, "B", 2, "srt", language)
    c1 = _write(os.path.join(src, show, f"[SubsC] {show} - 01.{_OURS[language]}.srt"), _text(language, 1, " C"))
    c1v2 = _write(os.path.join(src, show, f"[SubsC] {show} - 01v2.{_OURS[language]}.srt"), _text(language, 1, " Cv2"))
    with store:
        _look(store, language, store.add_source(src), first=True)
        work = _work(store)
        assert store.group_of(work)["label"] == "SubsB"
        picks = sorted(_picks(store, data_dir)[0].items())
        assert _sha(b1) == picks[0][1] and _sha(os.path.join(src, show, f"[SubsB] {show} - 02.{_OURS[language]}.srt"))             == picks[1][1], "02 from B too: the v2's group orders this look's other episodes"
        item = min(_picks(store, data_dir)[0])
        c = next(o for o in store.other_subtitles(item) if o["label"] == "SubsC")
        assert c["path"] == os.path.abspath(c1v2) and os.path.abspath(c1) not in [o["path"] for o in
                                                                                 store.other_subtitles(item)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_refused_first_pick_never_names_the_shows_group(language):
    """Episode 1's first file by the order is `[SubsAlpha]`'s, but English (refused by the language rule): `[SubsZeta]`'s
    Japanese one is taken — and the show's group is Zeta's, the file actually taken."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    from tests.test_sources_scenarios import ENGLISH
    for n in (1, 2):
        _write(os.path.join(src, show, f"[SubsAlpha] {show} - {n:02d}.ass"), ENGLISH + f"\n{n}\n")
        _write(os.path.join(src, show, f"[SubsZeta] {show} - {n:02d}.srt"), _text(language, n, " Z"))
    with store:
        _look(store, language, store.add_source(src), first=True)
        assert store.group_of(_work(store))["label"] == "SubsZeta"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_long_switch_goes_a_few_episodes_a_command_and_is_still_one_undo(language, monkeypatch):
    """SWITCH_BATCH episodes a command (the write lock held briefly, G1): 2 a step here, 3 episodes — one Change,
    one Undo, every step's note cleared."""
    monkeypatch.setattr(ls, "SWITCH_BATCH", 2)
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    for n in (1, 2, 3):
        _sub(src, show, "A", n, "ass", language)
        _sub(src, show, "B", n, "srt", language, " (WEB)")
    with store:
        _look(store, language, store.add_source(src), first=True)
        copies, records, work = _picks(store, data_dir), _records(store), _work(store)
        version = store.meta()["state_version"]
        change = store.switch_group(work, _group_b(store))
        assert len(change.switched) == 3 and store.meta()["state_version"] - version >= 2
        assert not [k for k in store.meta() if k.startswith(ls.SWITCH_PENDING)]
        store.undo(change)
        assert _picks(store, data_dir) == copies and _records(store) == records


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_shows_switched_group_goes_with_it_into_another_title(language):
    """*Same title as…* merges a switched show into another title (one with a group of its own, a look's): the
    switched group goes with it, and its next episode from both groups is still B's."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src, video=False)
    os.remove(b[1])                                  # 01 stays A's: its earliest episode never decides it again
    other = _SHOWS[language][0]
    _write(os.path.join(src, other, f"{other} - 01.{_OURS[language]}.srt"), _text(language, 3, " other"))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        works = dict(store.conn.execute("SELECT parent_folder, work_id FROM items"))
        work, keep = works[show], works[other]
        ep2 = sorted(i for (i,) in store.conn.execute("SELECT id FROM items WHERE work_id = ?", (work,)))[1]
        assert store.switch_group(work, store.other_subtitles(ep2)[0]["group"]).switched == [ep2]
        store.merge_works(keep, [work])
        assert store.group_of(keep)["label"] == "SubsB"
        _sub(src, show, "A", 4, "ass", language)
        b4 = _sub(src, show, "B", 4, "srt", language)
        _look(store, language, root)
        assert _sha(b4) in _picks(store, data_dir)[0].values()


def test_hatos_text_is_held_by_a_switch_never_written_over():
    """An episode whose text is hato's (its pairing row, K3): a switch leaves it as it is, listed held (LM3 reads
    hato's items), and counts every other episode as before."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src, video=False)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids, target = sorted(_picks(store, data_dir)[0]), _group_b(store)
        with store._writing():
            store.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES (?, ?, ?, ?)",
                               ("hato:ep1", ids[0], json.dumps({"producer": "hato"}), "2026-10-21T00:00:00.000000Z"))
        change = store.switch_group(_work(store), target)
        assert (change.switched, change.held, change.missing) == ([ids[1]], [ids[0]], [ids[2]])
        assert _picks(store, data_dir)[0][ids[0]] == _sha(a[1])


def test_a_bilingual_file_is_never_another_groups_copy():
    """A group whose only copy of 01 holds two languages (`.chs&jpn`) offers nothing for 01: a switch never makes a
    bilingual file the text of an episode picked in one language (LM1a-Q1)."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    _sub(src, show, "A", 1, "ass", language)
    _write(os.path.join(src, show, f"[SubsF] {show} - 01.chs&jpn.srt"), _text(language, 1, " F"))
    with store:
        _look(store, language, store.add_source(src), first=True)
        (item,) = [i for (i,) in store.conn.execute("SELECT id FROM items")]
        assert store.other_subtitles(item) == []


def test_a_part_file_changed_before_the_swap_is_never_put_in_place(monkeypatch):
    """The bytes read for 01 no longer what its part holds when the write lock is taken: 01 stays as it is, held."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids, target = sorted(_picks(store, data_dir)[0]), _group_b(store)
        real = ls._read_into_part

        def spoilt(self, plan, token):
            done = real(self, plan, token)
            if done and plan["item"] == ids[0]:
                with open(plan["part"], "ab") as f:
                    f.write(b"\n")
            return done
        with monkeypatch.context() as patched:
            patched.setattr(ls, "_read_into_part", spoilt)
            change = store.switch_group(_work(store), target)
        assert (change.switched, change.held) == ([ids[1]], [ids[0]])
        assert _picks(store, data_dir)[0][ids[0]] == _sha(a[1])


def test_a_later_steps_failure_keeps_the_earlier_steps_and_holds_the_rest(monkeypatch):
    """A switch's second command fails (one episode a step here): the first episode stays switched, recorded and
    undoable; the rest stay as they are, listed held — never a raise that loses the Change."""
    language = "ja"
    monkeypatch.setattr(ls, "SWITCH_BATCH", 1)
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids, target, work = sorted(_picks(store, data_dir)[0]), _group_b(store), _work(store)
        real, calls = ls._store_switch_step, []

        def second_fails(self, *args, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("the disk went away")
            return real(self, *args, **kw)
        with monkeypatch.context() as patched:
            patched.setattr(ls.Store, "_switch_step", second_fails)
            change = store.switch_group(work, target)
        assert (change.switched, change.held) == ([ids[0]], [ids[1]])
        assert store.group_of(work)["label"] == "SubsB" and store.group_of(work)["pending"] == [ids[1]]
        assert _picks(store, data_dir)[0][ids[1]] == _sha(a[2])


def test_a_switch_never_writes_over_a_file_with_the_new_name():
    """A file already named as B's subtitle in the show's Library folder (another item's, or left there): that episode
    is held, never written over; the next switches."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        ids, target = sorted(_picks(store, data_dir)[0]), _group_b(store)
        there = os.path.join(data_dir, ls.CONTENT_FOLDER, show, os.path.basename(b[1]))
        with open(there, "w", encoding="utf-8") as f:
            f.write("someone's own file\n")
        change = store.switch_group(_work(store), target)
        assert (change.switched, change.held) == ([ids[1]], [ids[0]])
        with open(there, encoding="utf-8") as f:
            assert f.read() == "someone's own file\n"


def test_a_step_that_switches_nothing_records_nothing(monkeypatch):
    """Every episode read but changed before the swap (each part spoilt): nothing switched — no group recorded, no
    switch kept to undo."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work, target, before = _work(store), _group_b(store), None
        before = store.group_of(work)
        real = ls._read_into_part

        def spoilt(self, plan, token):
            done = real(self, plan, token)
            if done:
                with open(plan["part"], "ab") as f:
                    f.write(b"+")
            return done
        with monkeypatch.context() as patched:
            patched.setattr(ls, "_read_into_part", spoilt)
            change = store.switch_group(work, target)
        assert change.switched == [] and store.group_of(work) == before and store.last_switch(work) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_takes_the_trash_copy_when_the_old_original_was_edited_since(language):
    """A's 02 edited after the switch (its bytes no longer the record's): Undo takes A's text from the copy the switch
    sent to the trash, never the edited original."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        copies = _picks(store, data_dir)
        change = store.switch_group(_work(store), _group_b(store))
        _write(a[2], _text(language, 2, " edited after the switch"))
        undone = store.undo(change)
        assert undone.switched == change.switched and _picks(store, data_dir) == copies


def test_second_keep_with_new_groups_tried_keeps_the_groups_tried_before():
    """A keep that finds no fitting group records the groups it tried; a second keep that tries another group adds it
    to those, so every group tried so far stays recorded and the check stays open."""
    # why: a group ruled out earlier must stay on record, or Connect would try it again on the next look.
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work = _work(store)
        mine, other = store.group_of(work)["group"], _group_b(store)
        assert store.keep_group(work, tried=[mine]) is True
        assert store.keep_group(work, tried=[other]) is True
        got = store.group_of(work)
        assert (got["checked"], got["tried"]) == (False, [mine, other])


@pytest.mark.parametrize("language", LANGUAGES)
def test_settling_a_stale_switch_keeps_a_new_copy_whose_bytes_differ_from_the_record(language):
    """A switch's new copy edited after the switch (its bytes no longer the recorded sha256): settling the stale
    switch keeps that copy on disk, never deletes it."""
    # why: the old copy is only safe to drop while the new copy still holds the switched bytes; an edited copy is
    # the user's own work and must survive the settle.
    import hashlib
    store, data_dir = _empty(language)
    with store:
        new = os.path.join(data_dir, "files", "new.srt")
        _write(new, _text(language, 1, " changed since the switch"))
        _write(os.path.join(data_dir, "trash", "old.srt"), _text(language, 1, " old copy"))
        recorded = hashlib.sha256(_text(language, 1, " the switched bytes").encode("utf-8")).hexdigest()
        note = {"at": 0, "moves": [{"rel": "files/old.srt", "to_rel": "files/new.srt",
                                    "trash": "trash/old.srt", "sha256": recorded}]}
        with store._writing():
            store.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)",
                               (ls.SWITCH_PENDING + "stale", json.dumps(note)))
        with open(new, "rb") as f:
            before = f.read()
        assert store.settle_switches(now=10 ** 9) == 1
        with open(new, "rb") as f:
            assert f.read() == before
