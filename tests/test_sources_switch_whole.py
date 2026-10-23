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


# --- an edition's Undo as ONE change; what a look may never wait on for ever ------------------------------------- #

STEP_CRASH = r"""
import os, sys
sys.path.insert(0, os.getcwd())
from app import library_store as ls, sources
lang, data_dir, uf, root, mode, n, work = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5], \
    int(sys.argv[6]), int(sys.argv[7])
ls.SWITCH_BATCH = 1
calls = []
if mode in ("trash-before", "trash-after", "undo-before", "undo-after"):
    real = ls.trash_file
    def die(*a, **k):
        calls.append(1)
        if len(calls) == n and mode.endswith("before"):
            os._exit(3)                   # killed just before the n-th file move
        out = real(*a, **k)
        if len(calls) == n:
            os._exit(3)                   # killed just after it
        return out
    ls.trash_file = die
elif mode == "remove":
    real = ls.Store.remove
    def die(self, *a, **k):
        if k.get("exclude") is False:
            os._exit(3)                   # killed as the parts past the end are taken out (their copies moved)
        return real(self, *a, **k)
    ls.Store.remove = die
elif mode == "takein":
    real = ls.Store.take_in
    def die(self, root_id, found, **k):
        if any("#" in str(f.get("origin", "")) and f.get("rel") for f in found):
            os._exit(3)                   # killed as the new edition's extra parts go in (their files there)
        return real(self, root_id, found, **k)
    ls.Store.take_in = die
store = ls.open_store(lang, data_dir, uf)
if mode.startswith("undo"):
    store.undo_switch(work)
else:
    sources.scan(store, lang, root)
"""


def _crash(language, data_dir, uf, root, mode, n=0, work=0):
    child = subprocess.run([sys.executable, "-c", STEP_CRASH, language, data_dir, uf, str(root), mode, str(n),
                            str(work)], cwd=os.getcwd(), capture_output=True, text=True)
    assert child.returncode == 3, child.stderr[-800:]


def _pending(store):
    return [k for k in store.meta() if k.startswith(ls.SWITCH_PENDING)]


def _holding(monkeypatch, rel):
    """The copy `rel` held open in a reader: Windows refuses to move it (the switch's trash move)."""
    real = ls.trash_file

    def trash(d, r, to=None):
        if r == rel:
            raise PermissionError(r)
        return real(d, r, to=to)
    monkeypatch.setattr(ls, "trash_file", trash)
    return real


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_editions_undo_with_a_part_held_changes_nothing_and_finishes_at_the_next_look(language, monkeypatch):
    """An edition's Undo is ONE change: one part's copy held open as the learner presses Undo — nothing changes (every
    part keeps the new edition), the Undo says it waits and stays the title's last switch; once let go, the next look
    finishes it: the whole old edition, no last switch, and no look switches to the declined edition again."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    old = _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        assert olds == _parts(old, language)
        work = store.item(before[0][0])["work_id"]
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        assert _look(store, language, root)["switched"] == len(before)
        news = [_copy(data_dir, rel) for _i, rel in before]
        assert news == _parts(new, language)
        real = _holding(monkeypatch, before[-1][1])
        out = store.undo_switch(work)
        assert getattr(out, "waiting", False) and out.notes
        assert [_copy(data_dir, rel) for _i, rel in before] == news, "a part held: nothing undone"
        assert (store.last_switch(work) or {}).get("kind") == "edition", "the Undo is still there"
        assert _look(store, language, root, full=True)["switched"] == 0
        assert [_copy(data_dir, rel) for _i, rel in before] == news, "still held: still the whole new edition"
        monkeypatch.setattr(ls, "trash_file", real)
        result = _look(store, language, root, full=True)
        assert (result["switched"], result["switched_works"]) == (0, []), "an Undo finished is no switch of the look"
        assert _items(store) == before and [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None and not _pending(store)
        assert _look(store, language, root, full=True)["switched"] == 0
        assert [_copy(data_dir, rel) for _i, rel in before] == olds


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_editions_undo_with_an_added_part_held_takes_nothing_out(language, monkeypatch):
    """A longer edition's Undo whose added part is held open: its parts never go back alone (the added part not out,
    the old parts not back) — the whole new edition stays until the next look finishes the Undo whole."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        work = store.item(before[0][0])["work_id"]
        longer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2),
                       language)
        _look(store, language, root)
        grown = _items(store)
        assert len(grown) == len(_parts(longer, language)) > len(before)
        real = _holding(monkeypatch, grown[-1][1])
        out = store.undo_switch(work)
        assert getattr(out, "waiting", False)
        assert _items(store) == grown and _whole(data_dir, grown, _parts(longer, language))
        monkeypatch.setattr(ls, "trash_file", real)
        _look(store, language, root, full=True)
        assert _items(store) == before and [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None


@pytest.mark.parametrize("times", [2, 1])
@pytest.mark.parametrize("language", LANGUAGES)
def test_an_editions_undo_puts_the_whole_old_book_back_shorter_or_longer(language, times):
    """An Undo of a shorter edition brings the parts past its end back; of a longer one takes its added parts out —
    the book exactly as it was, and the next look changes nothing."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", times), language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        work = store.item(before[0][0])["work_id"]
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 3 - times),
                    language)
        _look(store, language, root)
        assert len(_items(store)) == len(_parts(new, language)) != len(before)
        store.undo_switch(work)
        assert _items(store) == before and [_copy(data_dir, rel) for _i, rel in before] == olds
        again = _look(store, language, root, full=True)
        assert (again["switched"], again["added"]) == (0, 0) and _items(store) == before


@pytest.mark.parametrize("mode", ["undo-before", "undo-after"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_crash_inside_an_editions_undo_is_finished_at_the_next_look(language, mode, monkeypatch):
    """The process killed in the middle of an edition's Undo — inside its second part's swap, or as its added parts
    are taken out — leaves one note: the next look finishes the Undo, so the book is the whole old edition (its added
    parts out), never half old and half new, and the title has no last switch left."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        work = store.item(before[0][0])["work_id"]
        _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2), language)
        _look(store, language, root)
        assert len(_items(store)) > len(before)
        uf = store.user_files_dir
    _crash(language, data_dir, uf, root, mode, 2 if mode == "undo-before" else len(before) + 1, work)
    monkeypatch.setattr(ls, "SWITCH_STALE_S", 0)
    store = ls.open_store(language, data_dir, uf)
    with store:
        assert _look(store, language, root, full=True)["switched"] == 0
        assert _items(store) == before and [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None and not _pending(store)
        assert not [f for f in _library_files(data_dir) if f.endswith(".part")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_second_undo_of_a_changed_declined_edition_stands(language):
    """Undo, the declined edition's file changes, the look switches to it again, Undo again: the second Undo declines
    the file's new bytes — the next look switches nothing."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    old = _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        work = store.item(before[0][0])["work_id"]
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        assert _look(store, language, root)["switched"] == len(before)
        store.undo_switch(work)
        _epub(new, _chapters(language, "再"), language, age=30)
        assert _look(store, language, root, full=True)["switched"] == len(before)
        store.undo_switch(work)
        assert [_copy(data_dir, rel) for _i, rel in before] == _parts(old, language)
        assert _look(store, language, root, full=True)["switched"] == 0
        assert [_copy(data_dir, rel) for _i, rel in before] == _parts(old, language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_edition_is_never_split_again_when_its_settling_fails(language, monkeypatch):
    """A book's new edition waiting (a part held open): a look whose settling of it fails still knows it waits —
    the EPUB is neither hashed nor split again."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        new = os.path.abspath(_epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"),
                                    _chapters(language, "改"), language))
        _holding(monkeypatch, before[-1][1])
        assert _look(store, language, root)["switched"] == 0
        assert [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)]
        split, hashed = [], []
        real_parts, real_sha = sources.book_parts, ls.sha256_of

        def fails(*_a, **_k):
            raise RuntimeError("the store's disk is busy")
        with monkeypatch.context() as patched:
            patched.setattr(store, "settle_editions", fails)
            patched.setattr(sources, "book_parts", lambda p, lang: split.append(p) or real_parts(p, lang))
            patched.setattr(ls, "sha256_of", lambda p: (hashed.append(p) if os.path.abspath(p) == new else None)
                            or real_sha(p))
            _look(store, language, root, full=True)
        assert (split, hashed) == ([], [])


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_new_editions_in_one_look_while_a_part_is_held_make_one_note(language, monkeypatch):
    """Two newer editions of one book in one look, the first's switch held: the second never starts a switch of its
    own over the same parts (one note for the book); once let go, the book ends whole on the newest edition."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "二"), language, age=40)
        third = {"ja": "星の歌 (第3版)", "zh": "灯下书简（增订版）"}[language]
        e3 = _epub(os.path.join(src, "Books", f"{third}.epub"), _chapters(language, "三"), language, age=20)
        real = _holding(monkeypatch, before[-1][1])
        _look(store, language, root)
        assert len([k for k in store.meta() if k.startswith(ls.EDITION_PENDING)]) == 1
        monkeypatch.setattr(ls, "trash_file", real)
        _look(store, language, root, full=True)
        _look(store, language, root, full=True)
        assert _items(store) == before and _whole(data_dir, before, _parts(e3, language))
        assert not _pending(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_extra_parts_name_taken_meanwhile_never_keeps_the_edition_waiting(language, monkeypatch):
    """A longer edition's extra part that couldn't go in (its move refused), then a file of the learner's at its name:
    the next look puts the part in under a free name (never over the file, never taking it for the part) and the
    edition is done — the title's last switch, its Undo there."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        work = store.item(before[0][0])["work_id"]
        longer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2),
                       language)
        parts = _parts(longer, language)
        real = ls.rename_no_overwrite

        def refused(a, b):
            if ".trash" in a.replace("\\", "/").split("/"):
                raise PermissionError(a)          # the staged extra part can't be moved in yet
            return real(a, b)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "rename_no_overwrite", refused)
            _look(store, language, root)
        assert [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)]
        folder, name = before[-1][1].rsplit("/", 1)
        stray = f"{folder}/{name.rsplit('_', 1)[0]}_{len(before) + 1:02d}.txt"
        assert not os.path.exists(os.path.join(data_dir, *stray.split("/")))
        _write(os.path.join(data_dir, *stray.split("/")), _text(language, 1, " the learner's own file"))
        _look(store, language, root, full=True)
        now = _items(store)
        assert len(now) == len(parts) and [_copy(data_dir, rel) for _i, rel in now] == parts
        assert _copy(data_dir, stray) == _text(language, 1, " the learner's own file").encode("utf-8")
        assert (store.last_switch(work) or {}).get("kind") == "edition"
        assert not [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_extra_parts_whose_source_is_no_longer_read_never_keep_the_edition_waiting(language, monkeypatch):
    """A longer edition's extra parts waiting to go in (the store busy), then the learner stops reading that folder:
    the edition finishes without them (said in its notes), the title's last switch recorded and its Undo there —
    never a note waiting for ever; no file of theirs left behind in the library."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        start = _library_files(data_dir)
        work = store.item(before[0][0])["work_id"]
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
        assert store.stop_source(root)
        (change,) = store.settle_editions()
        assert change.switched == [i for i, _r in before] and change.notes
        assert _items(store) == before and _whole(data_dir, before, parts[:len(before)])
        assert not [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)]
        assert _library_files(data_dir) == start
        assert (store.last_switch(work) or {}).get("kind") == "edition"
        store.undo_switch(work)
        assert [_copy(data_dir, rel) for _i, rel in before] == olds


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_running_edition_keeps_its_note_fresh_so_no_other_process_takes_it_over(language, monkeypatch):
    """A long edition switch (a step a part, a slow disk): its note's time is renewed as it works, so another
    process's look never takes it for a crashed one (older than SWITCH_STALE_S) while it runs."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        monkeypatch.setattr(ls, "SWITCH_BATCH", 1)
        late, ages = [0.0], []
        real_time, real_step = time.time, ls.Store._switch_step
        monkeypatch.setattr(time, "time", lambda: real_time() + late[0])

        def slow(self, *a, **k):
            late[0] += 0.7 * ls.SWITCH_STALE_S         # each part's step takes most of the stale time
            for _key, value in self.conn.execute("SELECT key, value FROM meta WHERE key >= ? AND key < ?",
                                                 (ls.EDITION_PENDING, ls.EDITION_PENDING[:-1] + ";")).fetchall():
                ages.append(time.time() - float(ls._json_dict(value)["at"]))
            return real_step(self, *a, **k)
        monkeypatch.setattr(ls.Store, "_switch_step", slow)
        assert _look(store, language, root)["switched"] == len(before)
        assert len(ages) == len(before) and max(ages) <= ls.SWITCH_STALE_S, ages


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_held_better_version_is_not_read_again_while_its_copy_stays_held(language, monkeypatch):
    """A better version judged and held (the item's copy open in a player): while the copy stays held, a look reads
    the version not at all (a probe of the copy, no read, no `.part` written); let go, it switches."""
    store, data_dir = _empty(language)
    src = _drive("Anime")
    show, v, s = _synced_show(language, src)
    t = _OURS[language]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        copy = os.path.abspath(os.path.join(data_dir, *before[0][1].split("/")))
        synced = os.path.abspath(_write(os.path.join(src, show, "synced", f"{show} - 01.{t}.srt"),
                                        _text(language, 1, " synced")))
        opened, real_open = [], open
        moves = {name: getattr(os, name) for name in ("rename", "replace", "link")}

        def held(name):
            def move(a, b, *x, **k):
                if os.path.abspath(a) == copy:
                    raise PermissionError(a)        # Windows: a file open elsewhere can't be moved
                return moves[name](a, b, *x, **k)
            return move

        def watch(path, *a, **k):
            if isinstance(path, str) and os.path.abspath(path) == synced and "b" in (a[0] if a else k.get("mode", "")):
                opened.append(path)
            return real_open(path, *a, **k)
        with monkeypatch.context() as patched:
            for name in moves:
                patched.setattr(os, name, held(name))
            patched.setattr("builtins.open", watch)
            assert sources.scan(store, language, root)["switched"] == 0
            opened.clear()
            assert sources.scan(store, language, root, full=True)["switched"] == 0
            assert opened == [], "held still: the version is not read"
            assert not [f for f in _library_files(data_dir) if f.endswith(".part")]
        assert _look(store, language, root, full=True)["switched"] == 1
        assert _copy(data_dir, store.item(before[0][0])["rel_path"]) == _text(language, 1, " synced").encode("utf-8")


@pytest.mark.parametrize("mode", ["trash-before", "trash-after", "remove"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_crash_while_the_parts_past_the_end_go_ends_whole(language, mode, monkeypatch):
    """The process killed as a shorter edition takes out the parts past its end — before or after the first one's
    copy moves to the trash, or once all moved, as their rows go — the next look ends it whole: the new edition's
    parts, the rest in the trash (Put back-able), the title's last switch whose Undo brings the whole book back."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        uf = store.user_files_dir
    new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
    short = _parts(new, language)
    _crash(language, data_dir, uf, root, mode, len(short) + 1)
    monkeypatch.setattr(ls, "SWITCH_STALE_S", 0)
    store = ls.open_store(language, data_dir, uf)
    with store:
        _look(store, language, root, full=True)
        now = _items(store)
        assert now == before[:len(short)] and [_copy(data_dir, rel) for _i, rel in now] == short
        assert store.conn.execute("SELECT COUNT(*) FROM trash").fetchone()[0] == len(before) - len(short)
        assert not _pending(store)
        work = store.item(now[0][0])["work_id"]
        assert store.last_switch(work)["kind"] == "edition"
        store.undo_switch(work)
        assert _items(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_crash_while_the_extra_parts_go_in_ends_whole(language, monkeypatch):
    """The process killed as a longer edition's extra parts go in (their files in the library, no rows yet): the next
    look takes them in — the whole new edition — and its Undo brings the old book back exactly."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        uf = store.user_files_dir
    longer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2), language)
    parts = _parts(longer, language)
    _crash(language, data_dir, uf, root, "takein")
    monkeypatch.setattr(ls, "SWITCH_STALE_S", 0)
    store = ls.open_store(language, data_dir, uf)
    with store:
        _look(store, language, root, full=True)
        now = _items(store)
        assert now[:len(before)] == before and len(now) == len(parts)
        assert [_copy(data_dir, rel) for _i, rel in now] == parts
        work = store.item(now[0][0])["work_id"]
        store.undo_switch(work)
        assert _items(store) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unreadable_old_part_keeps_the_whole_old_edition_until_it_reads(language, monkeypatch):
    """An old part's copy that can't be read as the new edition is planned (its Undo needs its bytes' sha256):
    nothing switches, nothing is noted; once it reads, the next look switches the whole edition, and its Undo
    brings every old part back."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        work = store.item(before[0][0])["work_id"]
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        locked = os.path.abspath(os.path.join(data_dir, *before[1][1].split("/")))
        real = ls.sha256_of

        def unreadable(path):
            if os.path.abspath(path) == locked:
                raise PermissionError(path)
            return real(path)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "sha256_of", unreadable)
            assert _look(store, language, root)["switched"] == 0
        assert [_copy(data_dir, rel) for _i, rel in before] == olds and not _pending(store)
        assert _look(store, language, root, full=True)["switched"] == len(before)
        assert _whole(data_dir, before, _parts(new, language))
        store.undo_switch(work)
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
