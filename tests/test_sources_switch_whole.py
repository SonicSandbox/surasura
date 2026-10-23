"""LM3's fix round (its review's findings; every rule PROVISIONAL — Kura / the lead 2026-10-22, Sonic's "technical
calls just work"): a book's new edition switched as ONE change — one note for the whole edition (its parts' swaps,
its extra parts, the parts past its end), so a crash, a file held open or a failed write leaves the whole old edition
or the whole new one, the next look finishing it forward; parts paired by their number; `declined` keyed by the bytes;
one "is this hato's?"; the look's own switches reaching the window as the title's last switch; a look never ended by
a switch; what a look already judged never read again until it changed.
Show and book names are made up; the texts are real Japanese / Chinese from tests/Test Resources/.
"""
import os
import subprocess
import sys
import time

import pytest

from app import library_store as ls
from app import sources
from app.connect import library, videos
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_groups import _show
from tests.test_sources_scan import (_OURS, _SHOWS, _drive, _empty, _fresh_module_state, _library_files,  # noqa: F401
                                     _look, _text, _video, _write)
from tests.test_sources_switch import (_BOOKS, _EDITION, _book, _chapters, _copy, _drop, _epub, _hato, _items,
                                       _parts, _record, _synced_show)


def _whole(data_dir, items, parts):
    """Every part of the book holds that edition's part, by number — nothing of another edition between."""
    return [_copy(data_dir, rel) for _i, rel in items] == parts


EDITION_CRASH = r"""
import os, sys
sys.path.insert(0, os.getcwd())
from app import library_store as ls, sources
lang, data_dir, uf, root = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
ls.SWITCH_BATCH = 1
real, calls = ls.trash_file, []
def die(*a, **k):
    calls.append(1)
    if len(calls) == 2:
        os._exit(3)                       # killed inside the second part's swap, the first one committed
    return real(*a, **k)
ls.trash_file = die
store = ls.open_store(lang, data_dir, uf)
sources.scan(store, lang, root)
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_crash_inside_a_new_editions_switch_is_finished_whole_at_the_next_look(language, monkeypatch):
    """ROOT (A2, T2): the process killed while a new edition switches — the first part's swap committed, the second's
    files half moved — leaves one note for the whole edition: the next look finishes it forward (every new part's
    bytes were written and checked), so the book is the whole new edition, never half old and half new."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        uf = store.user_files_dir
    new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
    child = subprocess.run([sys.executable, "-c", EDITION_CRASH, language, data_dir, uf, str(root)],
                           cwd=os.getcwd(), capture_output=True, text=True)
    assert child.returncode == 3, child.stderr[-600:]
    monkeypatch.setattr(ls, "SWITCH_STALE_S", 0)
    store = ls.open_store(language, data_dir, uf)
    with store:
        _look(store, language, root, full=True)
        assert _items(store) == before and _whole(data_dir, before, _parts(new, language))
        assert all(library.pairing_of(store, i)["origin"] == f"{os.path.abspath(new)}#{n}"
                   for n, (i, _r) in enumerate(before, 1))
        assert not [k for k in store.meta() if k.startswith(ls.SWITCH_PENDING)]
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_editions_parts_pair_by_number_never_by_position(language):
    """A1: the learner removed part 2 of a book; its new edition beside it — part 3's item takes the new part 3 (its
    cards stay on its own chapter), new part 2 stays out (Remove keeps it out), and the next look splits nothing."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "原", 2), language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        assert len(before) >= 4
        store.remove([before[1][0]])
        kept = [before[0]] + before[2:]
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2), language)
        parts = _parts(new, language)
        assert len(parts) >= len(before)                 # (its longer title may make one part more: a new item)
        extra = len(parts) - len(before)
        result = _look(store, language, root)
        assert (result["switched"], result["added"]) == (len(kept), extra)
        now = _items(store)
        assert now[:len(kept)] == kept and len(now) == len(kept) + extra
        assert [_copy(data_dir, rel) for _i, rel in now] == [parts[0]] + parts[2:]
        again = _look(store, language, root, full=True)
        assert (again["switched"], again["added"]) == (0, 0)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_part_past_the_new_editions_end_held_open_keeps_the_whole_old_edition(language, monkeypatch):
    """B2 / S3 / S4: a longer book's new edition is shorter; one part past its end has its copy held open — nothing
    changes (every part keeps the old text, none taken out), the book waits; once let go, the next look switches the
    whole edition and takes the parts past its end out (to the trash: Put back brings them)."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        old = [_copy(data_dir, rel) for _i, rel in before]
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        short = _parts(new, language)
        assert len(short) < len(before)
        real, held = ls.trash_file, before[-1][1]

        def trash(d, rel, to=None):
            if rel == held:
                raise PermissionError(rel)           # open in a reader: Windows refuses the move
            return real(d, rel, to=to)
        monkeypatch.setattr(ls, "trash_file", trash)
        result = _look(store, language, root)
        assert result["switched"] == 0 and result["waiting"] >= 1
        assert _items(store) == before and [_copy(data_dir, rel) for _i, rel in before] == old
        monkeypatch.setattr(ls, "trash_file", real)
        later = _look(store, language, root)
        assert later["switched"] == len(short)
        assert _items(store) == before[:len(short)] and _whole(data_dir, before[:len(short)], short)
        assert store.conn.execute("SELECT COUNT(*) FROM trash").fetchone()[0] == len(before) - len(short)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_editions_extra_parts_that_fail_to_go_in_are_taken_in_by_the_next_look(language, monkeypatch):
    """S1 / A5: a longer new edition whose extra parts' take-in fails (the store busy) — the switch stays pending,
    never "logged and forgotten": the next look takes the extra parts in, and the book is the whole new edition."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        longer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2),
                       language)
        parts = _parts(longer, language)
        real = store.take_in

        def busy(root_id, found, **k):
            if any(str(f.get("origin", "")).startswith(os.path.abspath(longer)) for f in found):
                raise ls.StoreBusy("the library is busy; try again")
            return real(root_id, found, **k)
        with monkeypatch.context() as patched:
            patched.setattr(store, "take_in", busy)
            _look(store, language, root)
        _look(store, language, root)
        now = _items(store)
        assert now[:len(before)] == before and len(now) == len(parts)
        assert [_copy(data_dir, rel) for _i, rel in now] == parts


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_extra_parts_name_holding_other_bytes_is_never_taken_for_the_new_part(language):
    """B1 / S5: a file left at an extra part's name (`<book>_0n.txt`, other bytes) is never recorded as the new
    edition's part: the part goes in under a free name, holding its own bytes; the stray file is left as it is."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        folder, name = before[-1][1].rsplit("/", 1)
        stray = f"{folder}/{name.rsplit('_', 1)[0]}_{len(before) + 1:02d}.txt"
        _write(os.path.join(data_dir, *stray.split("/")), _text(language, 1, " a stray file"))
        longer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2),
                       language)
        parts = _parts(longer, language)
        _look(store, language, root)
        now = _items(store)
        assert len(now) == len(parts) and [_copy(data_dir, rel) for _i, rel in now] == parts
        assert _copy(data_dir, stray) == _text(language, 1, " a stray file").encode("utf-8")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_edition_whose_part_isnt_available_waits_and_isnt_split_again_until_something_changes(
        language, monkeypatch):
    """A7 / W1: a part's copy deleted outside the app (not available) — the new edition waits, remembered by the
    EPUB's stats: the next look neither hashes nor splits it; the part back, it switches."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        gone = os.path.join(data_dir, *before[0][1].split("/"))
        with open(gone, "rb") as f:
            body = f.read()
        os.remove(gone)
        store.sync_disk()                                # the window's disk sync marks the copy missing
        assert store.item(before[0][0])["availability"] != "available"
        new = os.path.abspath(_epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"),
                                    _chapters(language, "改"), language))
        assert _look(store, language, root)["switched"] == 0
        split, hashed = [], []
        real_parts, real_sha = sources.book_parts, ls.sha256_of
        with monkeypatch.context() as patched:
            patched.setattr(sources, "book_parts", lambda p, lang: split.append(p) or real_parts(p, lang))
            patched.setattr(ls, "sha256_of", lambda p: (hashed.append(p) if os.path.abspath(p) == new else None)
                            or real_sha(p))
            again = _look(store, language, root, full=True)
        assert (again["switched"], split, hashed) == (0, [], [])
        with open(gone, "wb") as f:
            f.write(body)
        store.sync_disk()                                # back: the part available again
        assert store.item(before[0][0])["availability"] == "available"
        assert _look(store, language, root, full=True)["switched"] == len(before)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_same_path_editions_undo_stands_when_its_file_is_only_touched(language):
    """A3: the learner's Undo of a same-path new edition declines its bytes: the EPUB touched later (the same bytes,
    a new time) is never switched to again."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    book = _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        old = [_copy(data_dir, rel) for _i, rel in before]
        _epub(book, _chapters(language, "改"), language, age=30)
        assert _look(store, language, root)["switched"] == len(before)
        store.undo_switch(store.item(before[0][0])["work_id"])
        assert [_copy(data_dir, rel) for _i, rel in before] == old
        past = time.time() - 5
        os.utime(book, (past, past))
        assert _look(store, language, root, full=True)["switched"] == 0
        assert [_copy(data_dir, rel) for _i, rel in before] == old


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_declined_version_touched_with_the_same_bytes_stays_declined(language):
    """A4: `declined` is keyed by the version's bytes: its file touched (a new time, the same bytes) keeps it — no
    switch."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        synced = _write(os.path.join(src, show, f"{show} - 01.{t}.synced.srt"), _text(language, 1, " synced"))
        assert _look(store, language, root)["switched"] == 1
        store.undo_switch(store.item(before[0][0])["work_id"])
        past = time.time() - 5
        os.utime(synced, (past, past))
        assert _look(store, language, root, full=True)["switched"] == 0
        with open(s[1], "rb") as f:
            assert _copy(data_dir, before[0][1]) == f.read()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_looks_switches_reach_the_window_as_the_titles_last_switch(language):
    """IK-L3-3 / ASK-1: a look's automatic switch is the title's last switch (by "source", kind "version" or
    "edition"), named in the look's result (`switched_works`); `undo_switch(work)` undoes it and declines what it
    switched to."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        work = store.item(before[0][0])["work_id"]
        _write(os.path.join(src, show, "synced", f"{show} - 01.{t}.srt"), _text(language, 1, " synced"))
        result = _look(store, language, root)
        assert (result["switched"], result["switched_works"]) == (1, [work])
        last = store.last_switch(work)
        assert (last["by"], last["kind"], last["switched"]) == ("source", "version", 1)
        store.undo_switch(work)
        with open(s[1], "rb") as f:
            assert _copy(data_dir, before[0][1]) == f.read()
        assert store.last_switch(work) is None
        assert _look(store, language, root, full=True)["switched"] == 0
        shelf = _drive("Shelf")
        _book(language, shelf)
        root = store.add_source(shelf)
        _look(store, language, root)
        book = [i for i, rel in _items(store) if (i, rel) not in before]
        work = store.item(book[0])["work_id"]
        _epub(os.path.join(shelf, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        result = _look(store, language, root)
        assert result["switched_works"] == [work] and store.last_switch(work)["kind"] == "edition"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_connect_link_on_a_folder_episode_is_not_hatos_text(language):
    """A8 / IK-L3-2: one "is this hato's?" — Connect's *Link…* record on a folder episode is Surasura's own, never
    hato's: the episode's `v2` is still followed and a re-timed copy still switched to."""
    from app.connect import link
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, t = _SHOWS[language][0], _OURS[language]
    for n in (1, 2):                                     # no video beside them: the learner links each one (*Link…*)
        _write(os.path.join(src, show, f"[SubsA] {show} - {n:02d}.{t}.srt"), _text(language, n))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        for item, _rel in before:
            link.link(store, item, _video(os.path.join(_drive("Videos"), f"{show} - {item:02d} [BD].mkv"),
                                          body=f"another video {item}".encode()))
        assert store.hato_items() == {}
        _write(os.path.join(src, show, f"[SubsA] {show} - 02v2.{t}.srt"), _text(language, 2, " v2"))
        _write(os.path.join(src, show, "synced", f"[SubsA] {show} - 01.{t}.srt"), _text(language, 1, " synced"))
        _look(store, language, root)
        assert _copy(data_dir, before[0][1]) == _text(language, 1, " synced").encode("utf-8")
        assert _copy(data_dir, before[1][1]) == _text(language, 2, " v2").encode("utf-8")


@pytest.mark.parametrize("language", LANGUAGES)
def test_other_groups_never_counts_a_waiting_videos_group(language):
    """A9: an episode still waiting for its text (its video `[Raws] <show> - 04.mkv` in first, alone: a waiting item;
    the show's subtitles after) is no subtitle group — though it is one of the title's episodes."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show = _SHOWS[language][1]
    _video(os.path.join(src, show, f"[Raws] {show} - 04.mkv"), body=b"video 4")
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        (waiting,) = [i for i, rel in _items(store)]
        assert store.item(waiting)["availability"] == "waiting"
        _show(language, src, video=False)
        _look(store, language, root)
        work = store.item(waiting)["work_id"]
        assert {store.item(i)["work_id"] for i, _r in _items(store)} == {work} and len(_items(store)) == 4
        assert [(g["label"], g["episodes"], g["of"]) for g in store.other_groups(work)] == [("SubsB", 2, 4)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_switch_that_raises_anything_never_ends_the_look(language, monkeypatch):
    """A6: a better version's switch or a new edition's raising anything (a KeyError: a record gone meanwhile)
    is logged and left for the next look: the look ends normally, and the next one switches both."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        books = len(_items(store)) - 2
        _write(os.path.join(src, show, "synced", f"{show} - 01.{t}.srt"), _text(language, 1, " synced"))
        _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)

        def fails(*_a, **_k):
            raise KeyError("a record gone")
        with monkeypatch.context() as patched:
            patched.setattr(store, "switch_versions", fails)
            patched.setattr(store, "switch_parts", fails)
            result = _look(store, language, root)
        assert (result["switched"], result["stopped"]) == (0, False)
        assert _look(store, language, root, full=True)["switched"] == 1 + books


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_editions_of_one_book_the_newer_file_counts(language):
    """D1 / A10: two editions of one book in one folder at the first read — the newer file (its time) is the book's
    text, the older's parts versions, never counted; an older edition's file arriving later never switches it; two new
    editions in one look leave the book whole on the newest."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    older = _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language), language, age=600)
    newer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
    with store:
        root = store.add_source(src)
        first = _look(store, language, root, first=True)
        items = _items(store)
        assert first["switched"] == 0 and _whole(data_dir, items, _parts(newer, language))
        assert _record(store, f"{older}#1")["version"] is True
        late = _epub(os.path.join(src, "Books", f"{_BOOKS[language]} (初版).epub"), _chapters(language, "初"),
                     language, age=900)
        assert _look(store, language, root)["switched"] == 0 and _whole(data_dir, items, _parts(newer, language))
        assert _record(store, f"{late}#1")["version"] is True
        third = _epub(os.path.join(src, "Books", f"{_BOOKS[language]} (第3版).epub"), _chapters(language, "三"),
                      language, age=20)
        fourth = _epub(os.path.join(src, "Books", f"{_BOOKS[language]} (第4版).epub"), _chapters(language, "四"),
                       language, age=10)
        _look(store, language, root)
        assert _items(store) == items and _whole(data_dir, items, _parts(fourth, language))
        assert _record(store, f"{third}#1")["version"] is True


@pytest.mark.parametrize("language", LANGUAGES)
def test_hatos_text_is_never_replaced_by_a_later_better_folder_copy(language):
    """D2 (A31): an episode whose text hato's timed drop took over keeps hato's text when a re-timed folder copy of
    that episode arrives: no switch."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, t = _SHOWS[language][0], _OURS[language]
    video = _video(os.path.join(src, show, f"{show} - 05.mkv"))
    _write(os.path.join(src, show, f"{show} - 05.{t}.srt"), _text(language, 5, " A"))
    with store:
        root = store.add_source(src)
        (item,) = _look(store, language, root, first=True)["ids"]
        drop = _drop(data_dir, f"{show} - 05.{t}.srt", _text(language, 5, " timed"))
        store.register(drop, _hato(videos.content_key(video), 5, show, os.path.abspath(video)))
        _write(os.path.join(src, show, "synced", f"{show} - 05.{t}.srt"), _text(language, 5, " synced"))
        assert _look(store, language, root)["switched"] == 0
        assert _copy(data_dir, store.item(item)["rel_path"]) == _text(language, 5, " timed").encode("utf-8")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_held_better_version_is_judged_once_and_read_once_a_look(language, monkeypatch):
    """W1-W3 / T1: the thin check reads the version once and hands its bytes to the swap (no second read); a switch
    held (the copy open in a player) keeps its verdict by both files (`fit`) — the next look reads the version once
    (the swap's), never the thin check again; `stop()` is asked between candidates."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        synced = os.path.abspath(_write(os.path.join(src, show, "synced", f"{show} - 01.{t}.srt"),
                                        _text(language, 1, " synced")))
        opened = []
        real_open = open

        def watch(path, *a, **k):
            if isinstance(path, str) and os.path.abspath(path) == synced and "b" in (a[0] if a else k.get("mode", "")):
                opened.append(path)
            return real_open(path, *a, **k)
        real = ls.trash_file
        monkeypatch.setattr(ls, "trash_file", lambda d, rel, to=None: None if rel == before[0][1] else
                            real(d, rel, to=to))
        monkeypatch.setattr("builtins.open", watch)       # (`sources.scan` itself: `_look`'s own check reads files)
        assert sources.scan(store, language, root)["switched"] == 0
        assert len(opened) == 2, "the look's own read as it takes the version in, then the switch's one read (the " \
            "thin check's bytes are the swap's)"
        opened.clear()
        assert sources.scan(store, language, root, full=True)["switched"] == 0
        assert len(opened) == 1, "the verdict kept: only the swap's read"
        monkeypatch.setattr(ls, "trash_file", real)
        assert store.switch_versions([before[0][0]], stop=lambda: True).switched == [], "stopped: nothing switched"
        with open(s[1], "rb") as f:
            assert _copy(data_dir, before[0][1]) == f.read()
        assert _look(store, language, root, full=True)["switched"] == 1


def test_edition_marks_are_read_where_the_other_name_readings_live():
    """IK-L3-4: one rule for an edition vs a volume, in `episode_names` beside the other name readings."""
    from app import episode_names
    assert episode_names.edition_name("星の歌 (第2版).epub") == episode_names.edition_name("星の歌.epub") == "星の歌"
    assert episode_names.edition_name("灯下书简（修订版）.epub") == "灯下书简"
    assert episode_names.edition_name("星の歌 2.epub") != "星の歌"
    assert sources.edition_name is episode_names.edition_name
