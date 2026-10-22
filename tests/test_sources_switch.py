"""LM3 (the library model's switch versions, in place). PROVISIONAL (Sonic 2026-10-21: answer 3, LM-1a, T2-B6 A —
accepted for building, to be checked in use; the technical calls built at the lean).

What the scenario matrix (`test_sources_scenarios.py`, the items a learner sees) can't show:
- **hato's items in a show's episodes** (A9, LM1b deferred): a folder subtitle of an episode hato holds — hato's own text, or
  a folder episode whose text hato's timed drop took over (A31, K3 R2) — is that item's other version, never a second
  item nor a second pick; a version written in the last seconds waits (counted waiting); a version holding a removed
  item's bytes is read once, not every look.
- **a better version later** (answer 3): a re-timed copy (`synced/`, `.synced`) of the pick's own group switched to IN
  PLACE — the item keeps its id, place and cards; its copy takes the new bytes (the old copy in the trash); the records
  swap; one Undo puts it all back. Never another group's file (the show's group is LM2's), never a signs track, never
  on its name alone; one the switch couldn't take is taken at a later look.
- **Use [B]'s subtitles** (the store half of the ⋯ entry): `other_groups`, `switch_group(by="user")`, `last_switch`'s
  item ids.
- **a book's new edition** (T2-B6 A): an EPUB with the same name (its edition marks off) in the same folder, or the same
  path with new bytes, is that book's `v2`: switched WHOLE (each part in place, the old parts' copies in the trash,
  place and cards kept), never added beside it; ONE splitter (`sources.book_parts`) for a new book and a new edition.
Show and book names are made up; the texts are real Japanese / Chinese from tests/Test Resources/.
"""
import hashlib
import json
import os
import time

import pytest

from app import library_store as ls
from app import sources
from app.connect import library, videos
from tests.test_library_store_support import LANGUAGES, RESOURCES
from tests.test_sources_groups import _group_b, _show, _sub
from tests.test_sources_scenarios import _THIN
from tests.test_sources_scan import (_OURS, _SHOWS, _drive, _empty, _fresh_module_state, _library_files,  # noqa: F401
                                     _look, _text, _video, _write)

_BOOKS = {"ja": "星の歌", "zh": "灯下书简"}                       # made-up book titles
_EDITION = {"ja": "星の歌 (第2版)", "zh": "灯下书简（修订版）"}      # the same book, its new edition
_OTHER = {"ja": "月の庭", "zh": "江边小记"}                        # another made-up book


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _record(store, path):
    row = store.conn.execute("SELECT pairing FROM pairings WHERE content_key = ?", (ls.origin_key(path),)).fetchone()
    return json.loads(row[0]) if row else None


def _records(store):
    return dict(store.conn.execute("SELECT content_key, pairing FROM pairings ORDER BY content_key").fetchall())


def _items(store):
    return store.conn.execute("SELECT id, rel_path FROM items ORDER BY id").fetchall()


def _copy(data_dir, rel):
    with open(os.path.join(data_dir, *rel.split("/")), "rb") as f:
        return f.read()


def _trash(data_dir):
    folder = os.path.join(data_dir, ".trash")
    return sorted(n for n in os.listdir(folder) if not n.startswith(".")) if os.path.isdir(folder) else []


def _hato(key, episode, title, video):
    """hato's record for a drop of `title`'s episode, timed to `video`."""
    return {"schema": 1, "content_key": key, "producer": "hato", "video_path": video, "video_size": 1473922811,
            "show": {"title": title, "season": 1, "episode": episode}}


def _drop(data_dir, name, text):
    """hato's drop: a subtitle in its drop folder of the data folder."""
    return _write(os.path.join(data_dir, *ls.HATO_FOLDER.split("/"), name), text)


# --- 0: hato's items are a show's episodes (A9, LM1b deferred) ------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_subtitle_of_an_episode_hato_holds_is_that_items_version(language):
    """A9: hato holds episode 5 of a show the folder holds 04 of (its drop timed to another video file of 05); the
    folder's own `[SubsB] <show> - 05` arriving later is hato's item's other version — no second item, never counted —
    and a Refresh changes nothing."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, t = _SHOWS[language][1], _OURS[language]
    _write(os.path.join(src, show, f"{show} - 04.{t}.srt"), _text(language, 4))
    with store:
        root = store.add_source(src)
        (first,) = _look(store, language, root, first=True)["ids"]
        work = store.item(first)["work_id"]
        drop = _drop(data_dir, f"{show} - 05.{t}.srt", _text(language, 5, " hato"))
        hato = store.register(drop, _hato("v1-ep5", 5, show, f"D:/Videos/{show} - 05 [BD].mkv")).added[0]
        assert store.item(hato)["work_id"] == work, "hato's drop is the show's (its title)"
        later = _write(os.path.join(src, show, f"[SubsB] {show} - 05.{t}.ass"), _text(language, 5, " B"))
        result = _look(store, language, root)
        assert (result["added"], len(_items(store))) == (0, 2), "hato's episode 5 is that episode: no second item"
        record = _record(store, later)
        assert record is not None and record["version"] is True and "video_path" not in record
        assert store.origins()[ls.path_key(os.path.abspath(later))].item_id == hato
        v2 = _write(os.path.join(src, show, f"{show} - 05v2.{t}.srt"), _text(language, 5, " v2"))
        result = _look(store, language, root)
        assert (result["added"], len(_items(store))) == (0, 2)
        assert _record(store, v2)["version"] is True, "hato's text is never followed by a v2: the v2 is a version"
        assert _copy(data_dir, store.item(hato)["rel_path"]) == _text(language, 5, " hato").encode("utf-8")
        again = _look(store, language, root, full=True)
        assert (again["added"], len(_items(store))) == (0, 2)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_episode_whose_text_hatos_timed_drop_took_over_takes_later_files_as_its_versions(language):
    """A31 (K3 R2): hato's timed drop for a folder episode's video takes that item over in place (its id kept, its text
    hato's); another group's subtitle of that episode arriving later is the item's version — never a second pick
    recorded on it by its video."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, t = _SHOWS[language][0], _OURS[language]
    video = _video(os.path.join(src, show, f"{show} - 05.mkv"))
    _write(os.path.join(src, show, f"[SubsA] {show} - 05.{t}.srt"), _text(language, 5, " A"))
    with store:
        root = store.add_source(src)
        (item,) = _look(store, language, root, first=True)["ids"]
        drop = _drop(data_dir, f"{show} - 05.{t}.srt", _text(language, 5, " timed"))
        change = store.register(drop, _hato(videos.content_key(video), 5, show, os.path.abspath(video)))
        assert getattr(change, "took_over", None) == item, "hato's timed text is the episode's (K3 R2)"
        assert _copy(data_dir, store.item(item)["rel_path"]) == _text(language, 5, " timed").encode("utf-8")
        later = _write(os.path.join(src, show, f"[SubsB] {show} - 05.{t}.ass"), _text(language, 5, " B"))
        result = _look(store, language, root)
        assert (result["added"], len(_items(store))) == (0, 1)
        record = _record(store, later)
        assert record is not None and record.get("version") is True, "a version, never a second pick by its video"
        assert library.pairing_of(store, item)["content_key"] == videos.content_key(video), "hato's record is read"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_version_written_in_the_last_seconds_waits_and_is_counted_waiting(language):
    """LM1b N5: another version of an episode in, written a moment ago (it may still be being written), waits for the
    next look — counted waiting, never skipped — and is recorded once it settled."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, t = _SHOWS[language][0], _OURS[language]
    _write(os.path.join(src, show, f"{show} - 05.{t}.srt"), _text(language, 5))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        fresh = _write(os.path.join(src, show, f"[SubsB] {show} - 05.{t}.ass"), _text(language, 5, " B"), age=0)
        result = _look(store, language, root)
        assert (result["waiting"], result["skipped"], result["added"]) == (1, 0, 0)
        assert _record(store, fresh) is None
        past = time.time() - 60
        os.utime(fresh, (past, past))
        _look(store, language, root, full=True)
        assert _record(store, fresh)["version"] is True


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_version_holding_a_removed_items_bytes_is_read_once_not_every_look(language, monkeypatch):
    """LM1b N5: a file of an episode in whose bytes are a removed item's (S6: kept out) is remembered by its stats:
    the next look never reads it again until it changes."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, t = _SHOWS[language][0], _OURS[language]
    _write(os.path.join(src, show, f"{show} - 05.{t}.srt"), _text(language, 5))
    gone = _write(os.path.join(src, show, f"{show} - 06.{t}.srt"), _text(language, 6))
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        by_path = {store.origins()[ls.path_key(os.path.abspath(gone))].item_id}
        store.remove(sorted(by_path))
        out = _write(os.path.join(src, show, f"[SubsB] {show} - 05.{t}.ass"), _text(language, 6))   # 06's bytes
        reads = []
        real = sources._read_text
        monkeypatch.setattr(sources, "_read_text", lambda p, st: reads.append(os.path.abspath(p)) or real(p, st))
        _look(store, language, root)
        assert _record(store, out) is None, "a removed item's bytes stay out"
        assert reads.count(os.path.abspath(out)) == 1
        _look(store, language, root, full=True)
        assert reads.count(os.path.abspath(out)) == 1, "remembered by its stats: never read again"
        assert len(ids) == 2


# --- 1 (a): a better version later, switched to in place (answer 3) --------------------------------------------------- #

def _synced_show(language, src):
    """`<show> - 01.mkv` + `<show> - 01.<lang>.srt`, `- 02` likewise. -> (show, {n: video}, {n: subtitle})."""
    show, t = _SHOWS[language][0], _OURS[language]
    v = {n: _video(os.path.join(src, show, f"{show} - {n:02d}.mkv"), body=f"video {n}".encode()) for n in (1, 2)}
    s = {n: _write(os.path.join(src, show, f"{show} - {n:02d}.{t}.srt"), _text(language, n)) for n in (1, 2)}
    return show, v, s


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_synced_copy_arriving_later_is_switched_to_in_place(language):
    """Answer 3: `synced/` (a re-timer's copies) arriving after the episodes are in — each item takes its re-timed
    text IN PLACE: the same item, place and file; the synced bytes; the old copy in the trash (its clock restarted); the
    synced subtitle's record the item's, holding the video; the old one a version. A Refresh never switches back."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        synced = {n: _write(os.path.join(src, show, "synced", f"{show} - {n:02d}.{t}.srt"),
                            _text(language, n, " synced")) for n in (1, 2)}
        result = _look(store, language, root)
        assert result["switched"] == 2 and result["added"] == 0
        assert _items(store) == before, "the same items, the same places"
        for (item, rel), n in zip(before, (1, 2)):
            assert _copy(data_dir, rel) == _text(language, n, " synced").encode("utf-8")
            pairing = library.pairing_of(store, item)
            assert pairing["origin"] == os.path.abspath(synced[n]) and pairing["video_path"] == os.path.abspath(v[n])
            assert _record(store, s[n])["version"] is True and "video_path" not in _record(store, s[n])
        assert len(_trash(data_dir)) == 2, "the old copies are in the trash"
        again = _look(store, language, root, full=True)
        assert again["switched"] == 0 and all(_copy(data_dir, rel) == _text(language, n, " synced").encode("utf-8")
                                              for (_i, rel), n in zip(before, (1, 2)))


@pytest.mark.parametrize("language", LANGUAGES)
def test_switch_versions_is_one_change_and_one_undo_puts_everything_back(language, monkeypatch):
    """The store's half (`Store.switch_versions`): the item's best version, when the look's order ranks it above the
    pick, swapped in place through LM2's one swap path; `Store.undo` puts back the bytes, the name and every record
    (from the original, else the trash) — the version it took kept a version marked declined, so no later look
    switches to it again (the learner's Undo stands)."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before, records = _items(store), _records(store)
        copies = {i: _copy(data_dir, rel) for i, rel in before}
        synced = _write(os.path.join(src, show, f"{show} - 01.{t}.synced.srt"), _text(language, 1, " synced"))
        held_off = ls.Change("switch_version", 0, 0)
        held_off.switched = []
        with monkeypatch.context() as patched:
            patched.setattr(store, "switch_versions", lambda *a, **k: held_off)
            _look(store, language, root)                             # recorded, not switched yet (the store held off)
        versions_in = _records(store)
        item = before[0][0]
        change = store.switch_versions([i for i, _r in before])
        assert (change.kind, change.switched, change.held) == ("switch_version", [item], [])
        assert _copy(data_dir, before[0][1]) == _text(language, 1, " synced").encode("utf-8")
        assert store.switch_versions([item]).switched == [], "switched already: nothing better"
        undone = store.undo(change)
        assert undone.switched == [item] and not undone.notes
        assert {i: _copy(data_dir, rel) for i, rel in _items(store)} == copies and _items(store) == before
        now, target = _records(store), ls.origin_key(synced)
        assert {k: v for k, v in now.items() if k != target} == {k: v for k, v in versions_in.items() if k != target}
        was = json.loads(versions_in[target])
        assert json.loads(now[target]) == dict(was, declined=[was["size"], was["mtime_ns"]]), "declined, by its stats"
        assert set(records) < set(versions_in)
        assert _look(store, language, root, full=True)["switched"] == 0, "the learner's Undo stands"
        assert {i: _copy(data_dir, rel) for i, rel in _items(store)} == copies
        assert store.group_of(store.item(item)["work_id"])["by"] == "look", "a version switch never touches the group"


def _watch_reads(monkeypatch, store):
    """Every read a look or a switch makes of a source file (`sources._read_text`, the switch's bytes, the thin
    check) and every `switch_versions` asked -> (paths read, items asked)."""
    reads, asked = [], []
    real_text, real_part, real_thin = sources._read_text, ls._read_into_part, ls._thin_switch
    monkeypatch.setattr(sources, "_read_text", lambda p, st: reads.append(os.path.abspath(p)) or real_text(p, st))
    monkeypatch.setattr(ls, "_read_into_part", lambda st_, plan, token: reads.extend(plan["origins"]) or
                        real_part(st_, plan, token))
    monkeypatch.setattr(ls, "_thin_switch", lambda st_, plan: reads.extend(plan["origins"]) or real_thin(st_, plan))
    real_switch = store.switch_versions
    monkeypatch.setattr(store, "switch_versions", lambda ids, **k: asked.append(list(ids)) or real_switch(ids, **k))
    return reads, asked


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_declined_version_is_never_read_again_until_its_file_changes(language, monkeypatch):
    """S19 (update only what changed): after the learner's Undo declined a better version, a look reads nothing of it
    and asks no switch — the record remembers the file by its size and time; the same file with new bytes is judged
    again, and switched to."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        synced = _write(os.path.join(src, show, f"{show} - 01.{t}.synced.srt"), _text(language, 1, " synced"))
        held_off = ls.Change("switch_version", 0, 0)
        held_off.switched = []
        with monkeypatch.context() as patched:
            patched.setattr(store, "switch_versions", lambda *a, **k: held_off)
            _look(store, language, root)
        store.undo(store.switch_versions([before[0][0]]))
        with monkeypatch.context() as patched:
            reads, asked = _watch_reads(patched, store)
            again = _look(store, language, root, full=True)
        assert again["switched"] == 0 and os.path.abspath(synced) not in reads and asked == [], "nothing read again"
        _write(synced, _text(language, 1, " synced again, re-timed once more"), age=30)
        with monkeypatch.context() as patched:
            reads, asked = _watch_reads(patched, store)
            changed = _look(store, language, root, full=True)
        assert changed["switched"] == 1 and os.path.abspath(synced) in reads
        assert _copy(data_dir, before[0][1]) == _text(language, 1, " synced again, re-timed once more").encode("utf-8")
        assert _items(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_thin_version_is_judged_once_and_again_only_when_its_file_changes(language, monkeypatch):
    """A6 with S19: the pick's own group's signs-only `.ass` (better by its format, too thin to be the text) is read
    once and remembered by its stats — the next look reads neither file nor asks a switch; the same file holding the
    episode's dialogue later is judged again and switched to."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, t = _SHOWS[language][1], _OURS[language]
    _write(os.path.join(src, show, f"[SubsA] {show} - 01.{t}.srt"), _text(language, 4, " A"))
    with store:
        root = store.add_source(src)
        (item,) = _look(store, language, root, first=True)["ids"]
        rel = store.item(item)["rel_path"]
        thin = _write(os.path.join(src, show, f"[SubsA] {show} - 01.{t}.ass"), _THIN[language] + "; signs\n")
        assert _look(store, language, root)["switched"] == 0
        record = _record(store, thin)
        assert record["version"] is True and record["thin"] == [record["size"], record["mtime_ns"]]
        with monkeypatch.context() as patched:
            reads, asked = _watch_reads(patched, store)
            again = _look(store, language, root, full=True)
        assert again["switched"] == 0 and os.path.abspath(thin) not in reads and asked == []
        full = _text(language, 8, " A, the full release")             # (the dialogue, as the pick holds it)
        _write(thin, full, age=30)
        changed = _look(store, language, root, full=True)
        assert changed["switched"] == 1 and _copy(data_dir, store.item(item)["rel_path"]) == full.encode("utf-8")
        assert store.item(item)["rel_path"] != rel, "the copy takes the `.ass` name (its format changed)"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_better_version_is_never_another_groups_nor_a_signs_track_nor_its_name_alone(language):
    """The show's group stays LM2's: another group's `.ass` arriving later (better by its format alone) is no switch;
    nor is the pick's own group's signs-only `.ass` (A6: under a quarter of the pick's lines), its `.sdh` track, or a
    copy that differs from the pick by its name alone (`<show> - 01 copy`)."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, t = _SHOWS[language][1], _OURS[language]
    pick = _write(os.path.join(src, show, f"[SubsA] {show} - 01.{t}.srt"), _text(language, 4, " A"))   # its cues
    with store:
        root = store.add_source(src)
        (item,) = _look(store, language, root, first=True)["ids"]
        rel = store.item(item)["rel_path"]
        _write(os.path.join(src, show, f"[SubsB] {show} - 01.{t}.ass"), _text(language, 1, " B"))
        _write(os.path.join(src, show, f"[SubsA] {show} - 01.{t}.ass"), _THIN[language] + "; signs\n")
        _write(os.path.join(src, show, f"[SubsA] {show} - 01.{t}.sdh.ass"), _text(language, 1, " sdh"))
        result = _look(store, language, root)
        assert result["switched"] == 0 and result["added"] == 0
        assert store.item(item)["rel_path"] == rel and _copy(data_dir, rel) == open(pick, "rb").read()
        assert library.pairing_of(store, item)["origin"] == os.path.abspath(pick)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_better_version_the_switch_couldnt_take_is_taken_at_a_later_look(language, monkeypatch):
    """A9: a switch target whose original can't be read at the switch (a drive gone, a file held) is never switched
    to; it stays a version, and a later look that lists its folder switches it."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        synced = _write(os.path.join(src, show, "synced", f"{show} - 01.{t}.srt"), _text(language, 1, " synced"))
        real = ls._read_into_part
        monkeypatch.setattr(ls, "_read_into_part", lambda store_, plan, token: False)
        held = _look(store, language, root)
        assert held["switched"] == 0 and _copy(data_dir, before[0][1]) == open(s[1], "rb").read()
        assert _record(store, synced)["version"] is True
        monkeypatch.setattr(ls, "_read_into_part", real)
        later = _look(store, language, root, full=True)
        assert later["switched"] == 1 and _copy(data_dir, before[0][1]) == open(synced, "rb").read()
        assert _items(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_better_versions_switch_that_fails_never_ends_the_look(language, monkeypatch):
    """A switch that raises (the database or a file failing mid-switch) is logged and left for the next look: the look
    finishes, the episode that arrived with the re-timed copy is taken in, the copy stays a version — and the next look
    switches it."""
    import sqlite3
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        synced = _write(os.path.join(src, show, "synced", f"{show} - 01.{t}.srt"), _text(language, 1, " synced"))
        _video(os.path.join(src, show, f"{show} - 03.mkv"), body=b"video 3")
        _write(os.path.join(src, show, f"{show} - 03.{t}.srt"), _text(language, 3))

        def fails(*_a, **_k):
            raise sqlite3.OperationalError("disk I/O error")
        with monkeypatch.context() as patched:
            patched.setattr(store, "switch_versions", fails)
            result = _look(store, language, root)
        assert (result["added"], result["switched"], result["stopped"]) == (1, 0, False)
        assert _copy(data_dir, before[0][1]) == open(s[1], "rb").read()
        assert _record(store, synced)["version"] is True
        later = _look(store, language, root, full=True)
        assert later["switched"] == 1 and _copy(data_dir, before[0][1]) == open(synced, "rb").read()


# --- 2 (b): Use [B]'s subtitles, the store half (A27) --------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_other_groups_names_each_other_group_with_how_many_episodes_it_has(language):
    """A27: the ⋯ entry's list — each group but the show's, best first in the look's order, with how many of the
    title's episodes have its copy: C (`.ass`, 01 only) before B (`.srt`, 01–02), of 3; none for an unknown title."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    _sub(src, show, "C", 1, "ass", language, " (BD)")
    with store:
        _look(store, language, store.add_source(src), first=True)
        work = store.conn.execute("SELECT DISTINCT work_id FROM items").fetchone()[0]
        groups = store.other_groups(work)
        assert [(g["label"], g["episodes"], g["of"]) for g in groups] == [("SubsC", 1, 3), ("SubsB", 2, 3)]
        assert groups[1]["group"] == _group_b(store) and groups[0]["group"][0] == "subsc"
        assert store.other_groups(10 ** 6) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_learners_switch_is_his_choice_and_last_switch_names_the_episodes(language):
    """*Use [B]'s subtitles*: `switch_group(work, B, by="user")` records B as the learner's choice, checked (Connect
    never switches it again); `last_switch` names the switched count and the episodes with no B copy (`missing_items`)
    or held (`held_items`) for the toast ("2 of 3 episodes switched; 3 has no SubsB subtitles"); after it the list
    offers A."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, a, b, v = _show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        work = store.conn.execute("SELECT DISTINCT work_id FROM items").fetchone()[0]
        ids = [i for i, _r in _items(store)]
        change = store.switch_group(work, _group_b(store), by="user")
        assert change.switched == ids[:2]
        group = store.group_of(work)
        assert (group["label"], group["by"], group["checked"]) == ("SubsB", "user", True)
        last = store.last_switch(work)
        assert (last["by"], last["switched"], last["missing"], last["held"]) == ("user", 2, 1, 0)
        assert (last["missing_items"], last["held_items"]) == ([ids[2]], [])
        assert [(g["label"], g["episodes"], g["of"]) for g in store.other_groups(work)] == [("SubsA", 3, 3)]
        store.undo_switch(work)
        assert store.last_switch(work) is None


# --- 3 (c): a book's new edition, switched whole (T2-B6 A) ------------------------------------------------------------ #

def _chapters(language, extra="", times=1):
    name = "context_test.txt" if language == "ja" else "chinese_text_1.txt"
    with open(os.path.join(RESOURCES, language, name), encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    text, n = [], 0
    while sum(map(len, text)) < 1600:                          # a chapter of about a part's length (1,500)
        text.append(lines[n % len(lines)])
        n += 1
    return ["".join(f"<p>{ln}</p>" for ln in text) + f"<p>{extra}</p>"] * (3 * times)


def _epub(path, chapters, language, age=60):
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("lm3-edition")
    book.set_title(os.path.splitext(os.path.basename(path))[0])
    book.set_language(language)
    items = []
    for n, body in enumerate(chapters, 1):
        c = epub.EpubHtml(title=f"{n}", file_name=f"c{n}.xhtml", lang=language)
        c.content = f"<html><body>{body}</body></html>"
        book.add_item(c)
        items.append(c)
    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    os.makedirs(os.path.dirname(path), exist_ok=True)
    epub.write_epub(str(path), book)
    t = time.time() - age
    os.utime(path, (t, t))
    return str(path)


def _parts(path, language):
    parts, why = sources.book_parts(path, language)
    assert why is None
    return parts


def _book(language, src):
    """A book of several parts in -> (the EPUB, its items [(id, rel)])."""
    return _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language), language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_edition_beside_the_book_is_switched_whole_in_place(language, monkeypatch):
    """T2-B6 A: `<book> (第2版).epub` beside `<book>.epub` — the same book's new edition: no new items; each part keeps
    its id and place and takes the new edition's part (the old copies in the trash); the new edition's records are the
    parts', the old one's versions (it is never split again); a Refresh changes nothing. One Undo puts it back."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    old = _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        assert len(before) >= 2
        records = _records(store)
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        changes = []
        real = store.switch_parts
        with monkeypatch.context() as patched:
            patched.setattr(store, "switch_parts", lambda *a, **k: changes.append(real(*a, **k)) or changes[-1])
            result = _look(store, language, root)
        assert (result["added"], result["switched"]) == (0, len(before))
        assert _items(store) == before, "the same items, the same places"
        parts = _parts(new, language)
        assert [_copy(data_dir, rel) for _i, rel in before] == parts
        for n, (item, _rel) in enumerate(before, 1):
            assert library.pairing_of(store, item)["origin"] == f"{os.path.abspath(new)}#{n}"
            assert _record(store, f"{old}#{n}")["version"] is True
        assert len(_trash(data_dir)) == len(before)
        from app import extract
        opened = []
        real_chunks = extract.chunks_of
        with monkeypatch.context() as patched:
            patched.setattr(extract, "chunks_of", lambda *a, **k: opened.append(a[0]) or real_chunks(*a, **k))
            again = _look(store, language, root, full=True)
        assert (again["added"], again["switched"], opened) == (0, 0, []), "neither edition is split again"
        undone = store.undo(changes[0])
        assert undone.switched == [i for i, _r in before]
        assert [_copy(data_dir, rel) for _i, rel in before] == _parts(old, language)
        now = _records(store)
        assert {k: v for k, v in now.items() if k in records} == records
        kept = [json.loads(v) for k, v in now.items() if k not in records]
        assert len(kept) == len(before) and all(r["version"] and r["declined"] for r in kept), \
            "the declined edition stays known: never split nor switched to again"
        again = _look(store, language, root, full=True)
        assert (again["added"], again["switched"]) == (0, 0)
        assert [_copy(data_dir, rel) for _i, rel in before] == _parts(old, language)
        _epub(new, _chapters(language, "再"), language, age=30)          # the declined edition's file changed
        changed = _look(store, language, root, full=True)
        assert (changed["added"], changed["switched"]) == (0, len(before)), "judged again once its file changed"
        assert [_copy(data_dir, rel) for _i, rel in before] == _parts(new, language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_same_path_with_new_bytes_is_the_books_new_edition(language):
    """T2-B6 A: the EPUB itself replaced by its new edition (same path, new bytes): switched whole in place, its
    records naming the new bytes; a touched EPUB (same bytes, new time) switches nothing and is not hashed again."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    book = _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        _epub(book, _chapters(language, "改"), language, age=30)
        result = _look(store, language, root)
        assert (result["added"], result["switched"]) == (0, len(before)) and _items(store) == before
        assert [_copy(data_dir, rel) for _i, rel in before] == _parts(book, language)
        assert _record(store, f"{book}#1")["sha256"] == _sha(book)
        past = time.time() - 10
        os.utime(book, (past, past))
        touched = _look(store, language, root)
        assert (touched["added"], touched["switched"]) == (0, 0)
        assert _record(store, f"{book}#1")["mtime_ns"] == os.stat(book).st_mtime_ns, "its stats followed"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_longer_new_edition_adds_its_extra_parts_and_a_shorter_one_takes_its_surplus_out(language):
    """T2-B6 A, whole: a new edition with more parts — the book's parts switched in place and the extra ones new items
    of the book; then one with fewer — the parts beyond its end taken out (their copies in the trash: Put back brings
    them), never left holding the old edition's text."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    book = _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        longer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2),
                       language)
        parts = _parts(longer, language)
        assert len(parts) > len(before)
        result = _look(store, language, root)
        assert (result["switched"], result["added"]) == (len(before), len(parts) - len(before))
        now = _items(store)
        assert now[:len(before)] == before and len(now) == len(parts)
        assert [_copy(data_dir, rel) for _i, rel in now] == parts
        os.remove(longer)
        os.remove(book)
        shorter = _epub(os.path.join(src, "Books", f"{_BOOKS[language]} 改訂版.epub"),
                        [_chapters(language, "短")[0]], language)
        short = _parts(shorter, language)
        assert len(short) < len(before)
        result = _look(store, language, root, full=True)
        assert result["switched"] == len(short)
        left = _items(store)
        assert left == now[:len(short)] and [_copy(data_dir, rel) for _i, rel in left] == short
        trashed = store.conn.execute("SELECT COUNT(*) FROM trash").fetchone()[0]
        assert trashed == len(now) - len(short), "the surplus parts are in the trash, Put back brings them"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_edition_one_of_whose_parts_cant_switch_waits_whole(language, monkeypatch):
    """Switched WHOLE: one part the switch can't take (its copy held open) — nothing switched (each part keeps the old
    edition's text, no record of the new one), the look waits; the next look switches the book."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    book = _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        old = [_copy(data_dir, rel) for _i, rel in before]
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        real = ls.trash_file
        held = before[-1][1]
        monkeypatch.setattr(ls, "trash_file", lambda d, rel, to=None: None if rel == held else real(d, rel, to=to))
        result = _look(store, language, root)
        assert result["switched"] == 0 and result["waiting"] >= 1
        assert [_copy(data_dir, rel) for _i, rel in before] == old
        assert _record(store, f"{new}#1") is None
        monkeypatch.setattr(ls, "trash_file", real)
        later = _look(store, language, root)
        assert later["switched"] == len(before) and [_copy(data_dir, rel) for _i, rel in before] == \
            _parts(new, language)
        assert book


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_editions_switch_that_fails_never_ends_the_look(language, monkeypatch):
    """`switch_parts` raising (the database failing; a file the system refuses was already the book's own wait): the
    book keeps its old edition and waits, the look goes on and takes in the other new book on the shelf; the next look
    switches the edition."""
    import sqlite3
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        old = [_copy(data_dir, rel) for _i, rel in before]
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        _epub(os.path.join(src, "Novels", f"{_OTHER[language]}.epub"), _chapters(language, "別"), language)

        def fails(*_a, **_k):
            raise sqlite3.DatabaseError("database disk image is malformed")
        with monkeypatch.context() as patched:
            patched.setattr(store, "switch_parts", fails)
            result = _look(store, language, root)
        assert (result["switched"], result["stopped"]) == (0, False) and result["added"] >= 2, "the other book is in"
        assert _items(store)[:len(before)] == before and [_copy(data_dir, rel) for _i, rel in before] == old
        assert _record(store, f"{new}#1") is None
        later = _look(store, language, root)
        assert later["switched"] == len(before)
        assert [_copy(data_dir, rel) for _i, rel in before] == _parts(new, language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_volume_is_never_an_edition_and_one_splitter_reads_every_book(language, monkeypatch):
    """`<book> 2.epub` (a second volume: a number is no edition mark) is a book of its own beside the first; a new book
    and a new edition are both split by ONE function, `sources.book_parts` (LM7's restore calls it too)."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    split = []
    real = sources.book_parts
    monkeypatch.setattr(sources, "book_parts", lambda p, lang: split.append(os.path.basename(p)) or real(p, lang))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        _epub(os.path.join(src, "Books", f"{_BOOKS[language]} 2.epub"), _chapters(language, "二"), language)
        result = _look(store, language, root)
        assert result["switched"] == 0 and result["added"] >= 2 and _items(store)[:len(before)] == before
        _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        assert _look(store, language, root)["switched"] == len(before)
        assert split == [f"{_BOOKS[language]}.epub", f"{_BOOKS[language]} 2.epub", f"{_EDITION[language]}.epub"]
