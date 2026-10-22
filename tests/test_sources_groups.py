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
        assert rels_after == rels, "the same items and files"
        assert [after[i] for i in ids] == [_sha(b[1]), _sha(b[2]), _sha(a[3])]
        sizes = dict(store.conn.execute("SELECT id, size FROM items"))
        assert all(sizes[i] == os.path.getsize(os.path.join(data_dir, *rels[i].split("/"))) for i in ids),             "the item's size is its new copy's (a later same-bytes check reads it)"
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
        undone = store.undo(change)
        assert undone.kind == "undo" and undone.switched == ids[:2] and not undone.notes
        assert _picks(store, data_dir)[0] == copies
        assert _records(store) == records
        assert store.group_of(work) == group_before


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

        def trash(data, rel):
            if rel == held_rel:
                raise PermissionError("held open")
            return real(data, rel)
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

        def meanwhile(self, plan):
            if plan["item"] == ids[0]:
                self.update_origin(os.path.abspath(a[1]), 7, 8, _sha(a[1]))
            return real(self, plan)
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
        target = _group_b(store)
        real = os.replace

        def replace(src_path, dst):
            if str(src_path).endswith(".part") and os.path.normcase(dst) == os.path.normcase(
                    os.path.join(data_dir, *rel.split("/"))):
                raise PermissionError("held open")
            return real(src_path, dst)
        with monkeypatch.context() as patched:
            patched.setattr(ls.os, "replace", replace)
            change = store.switch_group(_work(store), target)
        assert (change.switched, change.held) == ([ids[1]], [ids[0]])
        assert _picks(store, data_dir)[0][ids[0]] == _sha(a[1])
        assert library.pairing_of(store, ids[0])["origin"] == os.path.abspath(a[1])
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
