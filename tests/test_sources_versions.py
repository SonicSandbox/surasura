"""LM1b (the library model's sorting): ONE episode per key per show, and every other file of that episode another
VERSION — an origin on the same item flagged `version` (never a new item, never counted, never the item's text, video,
number or pairing). PROVISIONAL (Sonic 2026-10-21: accepted for building, to be checked in use).

What the scenario matrix (`test_sources_scenarios.py`, the items a learner sees) can't show: the records. Two sources
holding one show (A9), the readers that must never take a version (A8, A26: `origin_videos`, `item_of_video_key`,
`pairing_of`, `episodes_of`), Remove keeping a version's file out, a version's original changed or the item's copy
lost (K8: never copied from a version), the JSON rebuild keeping the flag, a video renamed after pairing (A20), a
number-joined subtitle of a removed episode (A12), `take_in`'s version entries, and the waiting video's type (Mado's
fincov root). Show names are made up; the texts are real Japanese / Chinese from tests/Test Resources/.
"""
import json
import os

import pytest

from app import library_store as ls
from app.connect import library, videos
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import (_OURS, _SHOWS, _drive, _empty, _fresh_module_state, _library_files,  # noqa: F401
                                     _look, _settle, _start_afresh, _text, _video, _write)


def _items(store):
    return store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]


def _versions(store):
    return {k: o for k, o in store.origins().items() if o.version}


def _sha(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _record(store, path):
    row = store.conn.execute("SELECT pairing FROM pairings WHERE content_key = ?", (ls.origin_key(path),)).fetchone()
    return json.loads(row[0]) if row else None


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_same_episode_from_a_second_source_is_a_version_never_a_second_item(language):
    """A9: one episode per show across sources — `driveB/<show>/[BD] <show> - 05.ass` beside an item from
    `driveA/<show>/<show> - 05.srt` is that item's other version: no new item, no copy, its record flagged and
    holding no video, its bytes known (Remove keeps them out)."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    first = _write(os.path.join(src, a, f"{a} - 05.{_OURS[language]}.srt"), _text(language, 5))
    second = _write(os.path.join(other, a, f"[BD] {a} - 05.{_OURS[language]}.ass"), _text(language, 5, " BD"))
    with store:
        item = _look(store, language, store.add_source(src), first=True)["ids"][0]
        second_root = store.add_source(other)
        result = _look(store, language, second_root)
        assert (result["added"], result["attached"], _items(store)) == (0, 0, 1)
        assert _library_files(data_dir) == [f"Library/{a}/{a} - 05.{_OURS[language]}.srt"]
        record = _record(store, second)
        assert record["version"] is True and "video_path" not in record and record["sha256"] == _sha(second)
        assert list(_versions(store)) == [ls.path_key(os.path.abspath(second))]
        assert _versions(store)[ls.path_key(os.path.abspath(second))].item_id == item
        assert _record(store, first).get("version") is None
        again = _look(store, language, second_root, full=True)                    # nothing new, nothing again
        assert (again["added"], again["attached"], _items(store)) == (0, 0, 1)


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_reader_takes_a_version_record(language):
    """A8, A26: a version's record (here one holding a video, as a switch may write it) is never the item's video
    (`origin_videos`, `item_of_video_key`, `video_holder`), its pairing (`pairing_of`, Connect's) or its number
    (`episodes_of`); the pick's are."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    _video(os.path.join(src, a, f"{a} - 03.mkv"))
    pick = _write(os.path.join(src, a, f"{a} - 03.{_OURS[language]}.srt"), _text(language, 3))
    with store:
        item = _look(store, language, store.add_source(src), first=True)["ids"][0]
        mine = _record(store, pick)
        other = os.path.join(_drive("driveB"), a, f"{a} - 07.srt")
        fake = {"producer": "source", "root": 1, "origin": other, "size": 1, "mtime_ns": 1, "sha256": "x",
                "show": {"title": a}, "episode": 7, "video_path": other[:-4] + ".mkv", "video_size": 9,
                "video_key": "v1-not-the-picks", "version": True}
        with store._writing():
            store.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES (?, ?, ?, ?)",
                               (ls.origin_key(other), item, json.dumps(fake), "2000-01-01T00:00:00"))   # the older
        assert "v1-not-the-picks" not in store.origin_videos()
        assert store.item_of_video_key("v1-not-the-picks") is None
        assert store.item_of_video_key("v1-not-the-picks", origins=store.origin_videos()) is None
        assert store._video_holder("v1-not-the-picks") is None
        assert store.item_of_video_key(mine["video_key"]) == item
        assert library.pairing_of(store, item)["video_path"] == mine["video_path"]
        assert store._episodes_of([item]) == {item: 3}
        assert store.origins()[ls.path_key(os.path.abspath(other))].version


@pytest.mark.parametrize("language", LANGUAGES)
def test_remove_keeps_every_version_of_the_episode_out(language):
    """S6 with LM1b: Remove of an item keeps out its versions' files too — none comes back as a new item."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} - 02.{_OURS[language]}.srt"), _text(language, 2))
    _write(os.path.join(src, a, f"[Other] {a} - 02 - Title.{_OURS[language]}.ass"), _text(language, 2, " other"))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        assert len(_versions(store)) == 1 and _items(store) == 1
        store.remove([item])
        result = _look(store, language, root, full=True)
        assert (result["added"], _items(store)) == (0, 0)
        assert len(store.excluded()) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_versions_original_changed_never_writes_over_the_items_copy(language):
    """LM1b, S5: a version is no copy's original — its file edited, the item's copy keeps the pick's text."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    pick = _write(os.path.join(src, a, f"{a} - 04.{_OURS[language]}.srt"), _text(language, 4))
    other = _write(os.path.join(src, a, f"{a} - 04.srt"), _text(language, 4, " untagged"))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert list(_versions(store)) == [ls.path_key(os.path.abspath(other))]
        copy = os.path.join(data_dir, "Library", a, os.path.basename(pick))
        _write(other, _text(language, 4, " untagged, edited and longer than before"))
        _settle(src)
        result = _look(store, language, root, full=True)
        assert result["recopied"] == 0 and _sha(copy) == _sha(pick)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_lost_copy_is_never_put_back_from_a_version_and_the_rebuild_keeps_the_flag(language):
    """K8 with LM1b: the data folder lost and the store rebuilt from its JSON copy — the version stays a version (no
    item made from it), and with the pick's original gone too the item stays missing: never filled with a version's
    bytes."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    pick = _write(os.path.join(src, a, f"{a} - 01.{_OURS[language]}.srt"), _text(language, 1))
    other = _write(os.path.join(src, a, f"{a} - 01.srt"), _text(language, 1, " untagged"))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert len(_versions(store)) == 1
    store = _start_afresh(language, store, data_dir)
    os.remove(pick)
    _settle(src)
    with store:
        assert list(_versions(store)) == [ls.path_key(os.path.abspath(other))] and _items(store) == 1
        result = _look(store, language, root)
        assert result["restored"] == 0 and _items(store) == 1
        assert store.conn.execute("SELECT availability FROM items").fetchone()[0] == "missing"
        assert _library_files(data_dir) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_renamed_after_pairing_is_found_by_its_size_and_content(language):
    """A20: `<show> - 05.mkv` renamed `<show> S01E05.mkv` after its subtitle was paired — the next look finds it beside
    the subtitle (same size, same content key) and records it on the origin; no new item."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    old = _video(os.path.join(src, a, f"{a} - 05.mkv"), body=b"\x1a\x45\xdf\xa3 episode five " * 3)
    sub = _write(os.path.join(src, a, f"{a} - 05.{_OURS[language]}.srt"), _text(language, 5))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        key = _record(store, sub)["video_key"]
        new = os.path.join(src, a, f"{a} S01E05.mkv")
        os.rename(old, new)
        _video(os.path.join(src, a, f"{a} - 04.mkv"), body=b"\x1a\x45\xdf\xa3 episode four " * 3)   # same size
        _settle(src)
        result = _look(store, language, root, full=True)
        record = _record(store, sub)
        assert record["video_path"] == os.path.abspath(new) and record["video_key"] == key
        assert (result["added"], _items(store)) == (0, 1)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_arriving_after_its_subtitle_is_recorded_on_its_origin(language):
    """A19: a subtitle in (no video), its video arrives later (another release's name, joined by number) — recorded on
    the subtitle's origin (`update_origin`), never a second item and never a waiting one."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    sub = _write(os.path.join(src, a, f"{a} 第3話.{_OURS[language]}.srt"), _text(language, 3))
    _write(os.path.join(src, a, f"{a} 第4話.{_OURS[language]}.srt"), _text(language, 4))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert "video_path" not in _record(store, sub)
        video = _video(os.path.join(src, a, f"[Grp] {a} - 03 (1080p).mkv"))
        _settle(src)
        result = _look(store, language, root)
        assert _record(store, sub)["video_path"] == os.path.abspath(video)
        assert (result["added"], _items(store)) == (0, 2)
        assert store.conn.execute("SELECT COUNT(*) FROM items WHERE availability = 'waiting'").fetchone()[0] == 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_many_late_videos_are_recorded_in_a_few_writes_never_one_per_subtitle(language, monkeypatch):
    """A19 at scale: an existing library's first look with LM1b finds the videos of every known subtitle at once (here
    30, LATE_BATCH made 7) — they are recorded LATE_BATCH to a write (5 writes), never one commit per subtitle, so the
    look's worker never holds the store's write lock once per row while the window saves."""
    from app import sources
    monkeypatch.setattr(sources, "LATE_BATCH", 7)
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    subs = [_write(os.path.join(src, a, f"{a} - {n:02d}.{_OURS[language]}.srt"), _text(language, n))
            for n in range(1, 31)]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _items(store) == 30 and not any("video_path" in _record(store, s) for s in subs)
        for n in range(1, 31):                       # each its own bytes, so its own content key
            _video(os.path.join(src, a, f"{a} - {n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska %d" % n)
        _settle(src)
        calls, writes, real = [], [], store._writing
        monkeypatch.setattr(store, "update_origins", lambda changes, f=store.update_origins: calls.append(
            len(changes)) or f(changes))

        def counted(*args, **kwargs):
            if not store._depth:
                writes.append(1)                     # an outermost write: one transaction, one commit
            return real(*args, **kwargs)
        monkeypatch.setattr(store, "_writing", counted)
        result = _look(store, language, root, full=True)
        assert [_record(store, s).get("video_path") for s in subs] == \
            [os.path.join(src, a, f"{a} - {n:02d}.mkv") for n in range(1, 31)]
        assert (result["added"], result["paired"], _items(store)) == (0, 30, 30)
        assert calls == [7, 7, 7, 7, 2] and len(calls) <= len(writes) <= len(calls) + 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_episode_stays_out_when_a_subtitle_of_another_name_joins_its_number(language):
    """A12: episode 5 removed (no video then); later its video and a subtitle of another name arrive — the subtitle
    joins the episode by its number, so it stays out like the one removed."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"[A] {a} - 05.{_OURS[language]}.srt"), _text(language, 5))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        store.remove([item])
        _video(os.path.join(src, a, f"[B] {a} - 05 (1080p).mkv"))
        _write(os.path.join(src, a, f"星の図書館 第5話.{_OURS[language]}.srt"), _text(language, 5, " jimaku"))
        _settle(src)
        result = _look(store, language, root, full=True)
        assert (result["added"], _items(store)) == (0, 0)


@pytest.mark.parametrize("language", LANGUAGES)
def test_take_in_records_a_version_after_its_pick_and_never_copies_it(language):
    """`take_in`'s version entries: `version_of` names the pick taken in the same batch (taken last whatever its
    show's name sorts as), `item_id` an item in; a version whose item isn't there is not recorded."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    root = None
    with store:
        root = store.add_source(src)
        lib = os.path.join(data_dir, "Library", a)
        os.makedirs(lib)
        with open(os.path.join(lib, "e1.srt"), "w", encoding="utf-8") as f:
            f.write(_text(language, 1))
        pick, v1, v2 = (os.path.join(src, a, n) for n in ("e1.srt", "e1.ass", "e1b.ass"))
        change = store.take_in(root, [
            {"origin": v1, "size": 3, "mtime_ns": 1, "sha256": "aa", "show": "", "version": True, "version_of": pick},
            {"origin": pick, "size": 3, "mtime_ns": 1, "sha256": "bb", "show": a, "rel": f"Library/{a}/e1.srt"},
            {"origin": v2, "size": 3, "mtime_ns": 1, "sha256": "cc", "show": a, "version": True, "item_id": 999}])
        item = change.added[0]
        assert change.versions == [item] and change.attached == []
        assert _record(store, v1)["version"] is True and store.origins()[ls.path_key(v1)].item_id == item
        assert _record(store, v2) is None and _items(store) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_waiting_for_its_subtitle_is_typed_as_a_subtitle_episode(language):
    """Mado's fincov root: a video-only episode's waiting item is typed from its video at take-in — a subtitle
    episode — never the fallback 'text', so its show reads as video (no media type guessed 'text')."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _video(os.path.join(src, a, f"{a} - 01.mkv"))
    with store:
        _look(store, language, store.add_source(src), first=True)
        assert store.conn.execute("SELECT source_type, availability FROM items").fetchall() == [("subtitle", "waiting")]
        work = store.conn.execute("SELECT work_id FROM items").fetchone()[0]
        assert store.media_type(work) == (None, None)                       # *Video*, never 'text' (a book's)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_arriving_beside_one_of_its_episode_already_in_is_its_version(language):
    """LM1b: `<show> - 04.srt` arriving later beside `<show> - 04.ja.srt`, in (one stem, one episode) — another version
    of it, recorded, never an item and never read again."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} - 04.{_OURS[language]}.srt"), _text(language, 4))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        later = _write(os.path.join(src, a, f"{a} - 04.ass"), _text(language, 4, " ass"))
        _settle(src)
        result = _look(store, language, root)
        assert (result["added"], _items(store)) == (0, 1)
        assert list(_versions(store)) == [ls.path_key(os.path.abspath(later))]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_release_follows_the_pick_never_a_version(language):
    """A8, S5: the pick's own group's `v2` is followed over the copy even when another group's `v2` is in as a version
    (a version is never the episode the look holds: `_held`)."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    tag = _OURS[language]
    _write(os.path.join(src, a, f"[Grp] {a} - 01.{tag}.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _write(os.path.join(src, a, f"[Other] {a} - 01v2.{tag}.srt"), _text(language, 1, " other v2"))
        _settle(src)
        _look(store, language, root)
        assert len(_versions(store)) == 1
        mine = _write(os.path.join(src, a, f"[Grp] {a} - 01v2.{tag}.srt"), _text(language, 1, " our v2"))
        _settle(src)
        result = _look(store, language, root)
        copy = os.path.join(data_dir, "Library", a, f"[Grp] {a} - 01.{tag}.srt")
        assert result["recopied"] == 1 and _sha(copy) == _sha(mine) and _items(store) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_take_in_never_records_a_version_whose_bytes_are_kept_out(language):
    """S6 at `take_in` (the look checks first): a version entry whose bytes Remove keeps out is not recorded."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    gone = _write(os.path.join(src, a, f"{a} - 08.{_OURS[language]}.srt"), _text(language, 8))
    keep = _write(os.path.join(src, a, f"{a} - 09.{_OURS[language]}.srt"), _text(language, 9))
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        by_path = {o.origin: o.item_id for o in store.origins().values()}
        store.remove([by_path[os.path.abspath(gone)]])
        other = os.path.join(src, a, "elsewhere copy.srt")
        change = store.take_in(root, [{"origin": other, "size": 5, "mtime_ns": 1, "sha256": _sha(gone), "show": a,
                                       "version": True, "item_id": by_path[os.path.abspath(keep)]}])
        assert change.versions == [] and _record(store, other) is None and len(ids) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_moved_to_another_drive_keeps_its_origins_and_comes_back(language):
    """A26: the same bytes found again in the same show (the folder moved to a new drive) are the pick's
    origin with their video, never a version — so a lost copy is put back from the new drive."""
    import shutil
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    _video(os.path.join(src, a, f"{a} - 01.mkv"))
    _write(os.path.join(src, a, f"{a} - 01.{_OURS[language]}.srt"), _text(language, 1))
    with store:                                       # one store for both looks (leaving `with` closes it)
        _look(store, language, store.add_source(src), first=True)
        shutil.copytree(os.path.join(src, a), os.path.join(other, a), copy_function=shutil.copy2)
        _settle(other)
        moved = os.path.join(other, a, f"{a} - 01.{_OURS[language]}.srt")
        second = store.add_source(other)
        _look(store, language, second)
        assert not _versions(store) and _record(store, moved)["video_path"] == os.path.join(other, a, f"{a} - 01.mkv")
    shutil.rmtree(os.path.join(src, a))
    store = _start_afresh(language, store, data_dir)
    with store:
        result = _look(store, language, second, full=True)
        assert result["restored"] == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_double_episode_arriving_after_its_first_half_is_its_own_item(language):
    """PROVISIONAL: `- 05` in, `[BD] - 05-06` arrives — episode 6 is held by nothing, so the double
    file is an item (episode 6's text counted), never a version of 05."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} - 05.{_OURS[language]}.srt"), _text(language, 5))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _write(os.path.join(src, a, f"[BD] {a} - 05-06.{_OURS[language]}.srt"), _text(language, 6, " BD"))
        _settle(src)
        assert _look(store, language, root)["added"] == 1 and _items(store) == 2 and not _versions(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_single_files_win_over_a_double_episode_found_in_the_same_look(language):
    """PROVISIONAL: no videos, `- 05.srt`, `- 06.srt` and `[J] - 05-06.ass` in one look — the singles are the two
    items (an `.ass` coming before an `.srt` never lifts the double over them), the double their version: each
    episode's text counted once."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} - 05.{_OURS[language]}.srt"), _text(language, 5))
    _write(os.path.join(src, a, f"{a} - 06.{_OURS[language]}.srt"), _text(language, 6))
    double = _write(os.path.join(src, a, f"[J] {a} - 05-06.{_OURS[language]}.ass"), _text(language, 6, " J"))
    with store:
        _look(store, language, store.add_source(src), first=True)
        assert _library_files(data_dir) == [f"Library/{a}/{a} - 05.{_OURS[language]}.srt",
                                            f"Library/{a}/{a} - 06.{_OURS[language]}.srt"]
        assert list(_versions(store)) == [ls.path_key(os.path.abspath(double))]


@pytest.mark.parametrize("language", LANGUAGES)
def test_singles_arriving_after_a_double_episode_are_its_versions_never_a_second_item(language):
    """PROVISIONAL: `[J] - 05-06` in first (held under both its numbers), `- 05` and `- 06` arrive — both are its
    versions; episode 6 is never a second item beside the double that holds it (counted twice). Switching to the
    singles is LM3's (the 3.1 test item covers these layouts)."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"[J] {a} - 05-06.{_OURS[language]}.ass"), _text(language, 6, " J"))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _write(os.path.join(src, a, f"{a} - 05.{_OURS[language]}.srt"), _text(language, 5))
        _write(os.path.join(src, a, f"{a} - 06.{_OURS[language]}.srt"), _text(language, 6))
        _settle(src)
        assert (_look(store, language, root)["added"], _items(store), len(_versions(store))) == (0, 1, 2)


@pytest.mark.xfail(strict=True, reason="PROVISIONAL, the 3.1 test item: a double whose numbers are held partly by an "
                                       "item already in and partly by a single new in the same look is an item too")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_double_episode_beside_a_held_single_and_a_new_single_in_one_look_is_their_version(language):
    """`- 05` in; then `- 06` and `[J] - 05-06` arrive in one look — every number the double claims is held (05 by the
    item, 06 by the new single), so the double is a version: two items, never three."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} - 05.{_OURS[language]}.srt"), _text(language, 5))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _write(os.path.join(src, a, f"{a} - 06.{_OURS[language]}.srt"), _text(language, 6))
        _write(os.path.join(src, a, f"[J] {a} - 05-06.{_OURS[language]}.ass"), _text(language, 6, " J"))
        _settle(src)
        _look(store, language, root)
        assert _items(store) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_arrival_row_names_the_folder_of_its_own_record_never_a_versions(language):
    """A waiting video on one drive, its episode's subtitle named like another release's video on a second: the item
    is filled in place and the first video's record becomes a version — New arrivals' folder name (`SourceLooks.
    folders`) is the subtitle's source, never the version's."""
    from app.services import source_looks
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    _video(os.path.join(src, a, f"[A] {a} - 05 (1080p).mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska A")
    with store:
        item = _look(store, language, store.add_source(src))["ids"][0]
        _video(os.path.join(other, a, f"[B] {a} - 05 (720p).mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska B")
        _write(os.path.join(other, a, f"[B] {a} - 05 (720p).{_OURS[language]}.srt"), _text(language, 5))
        _settle(other)
        _look(store, language, store.add_source(other))
        assert _items(store) == 1 and len(_versions(store)) == 1

        class _Opener:
            def handle(self):
                return store
        looks, got = source_looks.SourceLooks(_Opener(), language), {}
        try:
            looks._folders([item], got.update)
        finally:
            looks.close()
        assert got == {item: other}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_subtitle_edited_while_its_video_arrives_keeps_its_new_bytes_on_record(language):
    """The subtitle re-copied and its video recorded in one look — the record names the new bytes (the
    next look copies nothing again)."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    sub = _write(os.path.join(src, a, f"{a} 第3話.{_OURS[language]}.srt"), _text(language, 3))
    _write(os.path.join(src, a, f"{a} 第4話.{_OURS[language]}.srt"), _text(language, 4))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _write(sub, _text(language, 3, " edited, a little longer than it was"))
        _video(os.path.join(src, a, f"[Grp] {a} - 03 (1080p).mkv"))
        _settle(src)
        assert _look(store, language, root)["recopied"] == 1
        assert _record(store, sub)["sha256"] == _sha(sub) and _record(store, sub).get("video_path")
        assert _look(store, language, root, full=True)["recopied"] == 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_remove_keeps_out_every_later_file_of_the_episode_whatever_its_name(language):
    """PROVISIONAL: Remove keeps the episode out by its number in its show — another group's
    or a titled file of it arriving later never comes back."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"[A] {a} - 05.{_OURS[language]}.srt"), _text(language, 5))
    with store:
        root = store.add_source(src)
        store.remove(_look(store, language, root, first=True)["ids"])
        _write(os.path.join(src, a, f"[Other] {a} - 05 - The Lantern.{_OURS[language]}.ass"), _text(language, 5, " o"))
        _settle(src)
        assert (_look(store, language, root, full=True)["added"], _items(store)) == (0, 0)


@pytest.mark.parametrize("language", LANGUAGES)
def test_never_read_this_folder_takes_an_item_whose_versions_lie_elsewhere(language):
    """The folder's items are those whose every own origin lies inside it — a version under another
    source is no origin of the item's here (nor counted in that source's items)."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    _write(os.path.join(src, a, f"{a} - 05.{_OURS[language]}.srt"), _text(language, 5))
    _write(os.path.join(other, a, f"[BD] {a} - 05.{_OURS[language]}.ass"), _text(language, 5, " BD"))
    with store:
        item = _look(store, language, store.add_source(src), first=True)["ids"][0]
        second = store.add_source(other)
        _look(store, language, second)
        assert len(_versions(store)) == 1
        assert store.items_under(os.path.join(src, a)) == [item]
        assert [s.get("items") for s in store.sources() if s["id"] == second] in ([0], [None])


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_epub_part_among_an_episodes_picks_makes_its_copies_unreadable(language):
    """`_group_copies` (the reading behind Connect's other-subtitle list and the group switch): an episode whose picks
    include ONE EPUB part (`<book>.epub#3`, a book's part, never a folder's episode) has no copies at all — None — even
    when its other pick is an ordinary episode file."""
    store, _data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} - 04.{_OURS[language]}.srt"), _text(language, 4))
    with store:
        item = _look(store, language, store.add_source(src), first=True)["ids"][0]
        with store._reading():
            assert ls._group_copies(store, item) is not None           # the episode alone reads its copies
        with store._writing():
            store.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES (?, ?, ?, ?)",
                               ("src:book-part", item, json.dumps({"producer": "source",
                                                                  "origin": os.path.join(src, "Book.epub#3")}),
                                ls._now()))
        with store._reading():
            assert ls._group_copies(store, item) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_regular_file_where_a_source_folder_should_be_is_not_reached(language):
    """A file where a source folder should be is no folder: its reach is never REACHED."""
    # why: the look would otherwise read a file in place of the folder and take its listing as the show's.
    from app import sources
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a), _text(language, 1))
    with store:
        assert sources.reach(os.path.join(src, a)) != sources.REACHED


# why: a video already recorded to one item is never attached to another known text of the folder when it is
# found again later, even where the record holds no video key to tell the items apart (the scan's own claim is
# the only guard then); the other text stays a record with no video, and the first keeps its own.
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_recorded_to_one_item_is_not_attached_to_a_second_item_later(language):
    """A video recorded to an item's text (no video key on the record) is not attached to another known text of the
    folder when it is found again — that text stays a record with no video, and the first keeps its video."""
    store, data_dir = _empty(language)
    a, b = _SHOWS[language][0], _SHOWS[language][1]
    src = _drive("driveA")
    ep = _write(os.path.join(src, a, f"{a} 第3話.{_OURS[language]}.srt"), _text(language, 3))
    plain = _write(os.path.join(src, a, f"{b} 第3話.{_OURS[language]}.srt"), _text(language, 9))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        video = _video(os.path.join(src, a, f"[Grp] {a} - 03 (1080p).mkv"))
        _settle(src)
        rec = _record(store, ep)
        rec.update(video_path=os.path.abspath(video), video_size=os.path.getsize(video))   # recorded, no video_key
        with store._writing():
            store.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                               (json.dumps(rec), ls.origin_key(ep)))
        _look(store, language, root)
        assert (_record(store, ep) or {}).get("video_path") == os.path.abspath(video)
        assert (_record(store, plain) or {}).get("video_path") is None   # never attached to the second item


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_waiting_videos_read_takes_the_store_reader_guard(language):
    # why: the look reads the waiting items inside the store's reader guard, so no writer changes the
    # waiting set while it is read: every read of the waiting videos happens with the guard held.
    import contextlib
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} 第3話.{_OURS[language]}.srt"), _text(language, 3))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _video(os.path.join(src, a, f"[Grp] {a} - 03 (1080p).mkv"))
        _settle(src)
        real_reading, real_waiting = store._reading, store._waiting_videos
        depth, seen = [0], []

        @contextlib.contextmanager
        def guard():
            depth[0] += 1
            try:
                with real_reading():
                    yield
            finally:
                depth[0] -= 1

        def waiting(*args, **kwargs):
            seen.append(depth[0] > 0)
            return real_waiting(*args, **kwargs)

        store._reading, store._waiting_videos = guard, waiting
        try:
            _look(store, language, root)
        finally:
            store._reading, store._waiting_videos = real_reading, real_waiting
        assert seen and all(seen)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_changed_while_it_is_copied_is_never_accepted(language, monkeypatch):
    """A subtitle whose bytes change while it is being copied is dropped, not recorded: that look copies
    nothing, and once the file settles the next look copies it."""
    # why: a copy taken while the original changes may match neither the old nor the new bytes, so it must never count.
    from app import sources
    store, data_dir = _empty(language)
    a = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} 第3話.{_OURS[language]}.srt"), _text(language, 3))
    sub = os.path.join(src, a, f"{a} 第4話.{_OURS[language]}.srt")
    _write(sub, _text(language, 4))
    _video(os.path.join(src, a, f"[Grp] {a} - 04 (1080p).mkv"))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        old = _sha(sub)
        # why: a new subtitle is copied from memory, never through `_copy_part`; only a recorded one that changes is re-copied through it.
        assert _record(store, sub)["sha256"] == old
        _write(sub, _text(language, 4, " edited, a little longer than it was"))
        _settle(src)
        real_copy = sources._copy_part

        changed = []

        def copy_then_change(path, part, size):
            digest = real_copy(path, part, size)
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(sub)):
                _write(sub, _text(language, 4, " changed while it was being copied, a little longer"))
                changed.append(sub)
            return digest

        monkeypatch.setattr(sources, "_copy_part", copy_then_change)
        # why: the hook writes the subtitle during this look, which `_look`'s no-write guard would reject; the test's own
        # write is the change under test, so this look calls `sources.scan` directly.
        assert sources.scan(store, language, root)["recopied"] == 0
        # why: the hook must have fired, or the look proves nothing; and the copy taken while the bytes changed is never on record.
        assert changed == [sub] and _record(store, sub)["sha256"] == old
        monkeypatch.setattr(sources, "_copy_part", real_copy)
        _settle(src)
        # why: a recorded subtitle whose new bytes settle is a re-copy, so `recopied` counts it once.
        assert _look(store, language, root)["recopied"] == 1
        assert _record(store, sub)["sha256"] == _sha(sub)
