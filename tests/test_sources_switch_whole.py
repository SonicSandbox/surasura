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
from tests.test_sources_groups import _a_minute_later, _show
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
    _a_minute_later(monkeypatch)
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
            patched.setattr(sources, "book_parts", lambda p, lang, **kw: split.append(p) or real_parts(p, lang, **kw))
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
    _a_minute_later(monkeypatch)
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
            patched.setattr(sources, "book_parts", lambda p, lang, **kw: split.append(p) or real_parts(p, lang, **kw))
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows refuses to move a file held open")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_held_better_version_is_not_read_again_while_its_copy_stays_held(language, monkeypatch):
    """A better version judged and held (the item's copy really open, as in a player): while the copy stays held, a
    look reads the version not at all (a check of the copy, no read, no `.part` written); let go, it switches."""
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

        def watch(path, *a, **k):
            if isinstance(path, str) and os.path.abspath(path) == synced and "b" in (a[0] if a else k.get("mode", "")):
                opened.append(path)
            return real_open(path, *a, **k)
        with real_open(copy, "rb"), monkeypatch.context() as patched:     # held open: Windows refuses its move
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
    _a_minute_later(monkeypatch)
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
    _a_minute_later(monkeypatch)
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


# --- an edition's Undo carried by one runner at a time; what is left out stays Put back-able --------------------- #

def _switched(store, data_dir, language, src, root, more=1):
    """The book in, then its new edition switched -> (the items, the old copies, the new edition's parts, the title)."""
    _look(store, language, root, first=True)
    before = _items(store)
    olds = [_copy(data_dir, rel) for _i, rel in before]
    work = store.item(before[0][0])["work_id"]
    new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", more), language)
    _look(store, language, root)
    news = _parts(new, language)
    assert news != olds
    return before, olds, news, work


def _notes(store):
    return [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)]


def _press_again_while_it_runs(store, before, olds, news, work, monkeypatch):
    """Undo pressed (runner A: a look's settle, a worker thread, another process); between two of A's part steps —
    the next part's copy mid-move — Undo is pressed again (B). -> B's Change."""
    monkeypatch.setattr(ls, "SWITCH_BATCH", 1)
    real = ls.Store._switch_step
    calls, inner, out = [], [False], []
    at = next(i for i, (o, n) in enumerate(zip(olds, news)) if o != n) + 2    # once a part that differs went back
    assert at <= len(before)

    def step(self, kind, by, work_id, ready, *a, **k):
        if kind == "undo" and not inner[0] and ready:
            calls.append(1)
            if len(calls) == at:
                part = ready[0]["part"]
                os.replace(part, part + ".moving")           # A's move of this part under way
                inner[0] = True
                try:
                    out.append(store.undo_switch(work))
                finally:
                    inner[0] = False
                    os.replace(part + ".moving", part)
        return real(self, kind, by, work_id, ready, *a, **k)
    with monkeypatch.context() as patched:
        patched.setattr(ls.Store, "_switch_step", step)
        store.undo_switch(work)
    return out[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_pressed_again_while_it_runs_is_told_it_is_under_way_and_never_runs_twice(language, monkeypatch):
    """An edition's Undo running (between two of its part steps) when Undo is pressed again: the second press is
    told the Undo is under way (waiting) and changes nothing — never a second runner of the same note, which undid
    what the first had done and left the book half old with no Undo. The first ends it whole: the old edition, no
    note, no last switch."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        before, olds, news, work = _switched(store, data_dir, language, src, root)
        assert [_copy(data_dir, rel) for _i, rel in before] == news
        second = _press_again_while_it_runs(store, before, olds, news, work, monkeypatch)
        assert second.waiting and second.notes and not second.switched
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None and not _notes(store) and not _pending(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_runners_of_one_undo_still_end_whole_at_the_next_look(language, monkeypatch):
    """Under the claim: should two runners ever carry one Undo (the claim forced open here), the one that finishes
    drops the note and the last switch only once every part reads the old edition — else the note waits, the Undo
    stays, and the next look ends the book whole."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        before, olds, news, work = _switched(store, data_dir, language, src, root)
        monkeypatch.setattr(ls, "_edition_take", lambda *a, **k: True, raising=False)
        _press_again_while_it_runs(store, before, olds, news, work, monkeypatch)
        now = [_copy(data_dir, rel) for _i, rel in before]
        assert now == olds or (_notes(store) and store.last_switch(work) is not None), "a mixed book with no Undo"
        _look(store, language, root, full=True)
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None and not _notes(store) and not _pending(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_pressed_again_soon_after_a_crash_inside_it_waits_for_the_look(language, monkeypatch):
    """Killed inside the Undo's second part step, the learner restarts and presses Undo again before the crashed
    step counts as crashed: the press is told the Undo is under way and changes nothing (never carrying the note
    past the crashed step, which the next look would then put back over it: a mixed book, records disagreeing with
    the copy, no Undo). The next look puts the step back and finishes the Undo: the whole old edition."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        before, olds, news, work = _switched(store, data_dir, language, src, root)
        uf = store.user_files_dir
    _crash(language, data_dir, uf, root, "undo-before", 2, work)
    store = ls.open_store(language, data_dir, uf)
    with store:
        assert _notes(store) and _pending(store)
        held = [_copy(data_dir, rel) for _i, rel in before]
        again = store.undo_switch(work)
        assert again.waiting and again.notes
        assert [_copy(data_dir, rel) for _i, rel in before] == held and _notes(store)
        _a_minute_later(monkeypatch)
        _look(store, language, root, full=True)
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None and not _notes(store) and not _pending(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_running_undos_time_renewal_never_rewrites_what_another_runner_wrote(language):
    """A runner renewing its note's time writes the time only: the note's waiting mark, its held files and its
    tries as the store holds them stay (never put back from the runner's own older copy of the note)."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        before, _olds, _news, work = _switched(store, data_dir, language, src, root)
        key = ls.EDITION_PENDING + "renewal"
        mine = {"at": 0, "waiting": False, "parts": [], "extras": [], "surplus": [], "work": work}
        store.bookkeeping({key: ls._dumps(dict(mine, waiting=True, held=[before[0][0]], tries=2))})
        at = ls._edition_touch(store, key, mine, 0)
        now = ls._json_dict(store.meta()[key])
        assert at > 0 and now["at"] == at
        assert (now["waiting"], now["held"], now["tries"]) == (True, [before[0][0]], 2)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_extra_part_whose_move_in_fails_look_after_look_is_in_the_trash_to_put_back(language, monkeypatch):
    """A longer edition's extra part whose move in fails look after look (EDITION_TRIES): the edition finishes
    without it, and each part sits in the trash with its row — Put back brings it into the library with its text, as
    after any removal (never a file in the trash nothing can bring back)."""
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
        assert len(parts) > len(before)
        rows = len(store.trash_rows())
        real = ls.rename_no_overwrite

        def refused(a, b):
            if ".trash" in a.replace("\\", "/").split("/"):
                raise PermissionError(a)          # the staged extra part can't be moved in
            return real(a, b)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "rename_no_overwrite", refused)
            _look(store, language, root)
            for _n in range(ls.EDITION_TRIES):
                if _notes(store):
                    _look(store, language, root, full=True)
        assert not _notes(store) and (store.last_switch(work) or {}).get("kind") == "edition"
        assert _items(store) == before and _whole(data_dir, before, parts[:len(before)])
        extra = store.trash_rows()[rows:]
        assert len(extra) == len(parts) - len(before)
        rels = {}
        for row in extra:
            assert row["trashed_path"] and os.path.isfile(os.path.join(data_dir, *row["trashed_path"].split("/")))
            rels[row["id"]], _why = ls.put_back(data_dir, row["trashed_path"], row["rel_path"])
        store.restore(sorted(rels), rels)
        now = _items(store)
        assert len(now) == len(parts) and [_copy(data_dir, r) for _i, r in now] == parts


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_short_failure_taking_the_extra_parts_in_is_waited_out(language, monkeypatch):
    """A longer edition's extra parts the store fails to take in once (a short failure, not a busy store): the
    edition waits for the next look, which takes them in — never left out at once."""
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
        real = store.take_in

        def flaky(root_id, found, **k):
            if any(str(f.get("origin", "")).startswith(os.path.abspath(longer)) for f in found):
                raise ls.StoreError("disk I/O error")
            return real(root_id, found, **k)
        with monkeypatch.context() as patched:
            patched.setattr(store, "take_in", flaky)
            _look(store, language, root)
        assert _notes(store), "a short failure waits for the next look"
        _look(store, language, root, full=True)
        now = _items(store)
        assert now[:len(before)] == before and [_copy(data_dir, r) for _i, r in now] == parts
        assert not _notes(store) and (store.last_switch(work) or {}).get("kind") == "edition"


@pytest.mark.parametrize("gone", ["file", "row"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undo_whose_parts_past_the_end_are_gone_for_good_is_refused(language, gone):
    """A shorter edition's Undo when a part past its end is gone from the trash for good (its file purged, or its
    row deleted): refused in plain words before anything is written — never an old edition back without its tail
    and no Undo left. The new edition and its last switch stay."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        before, _olds, news, work = _switched(store, data_dir, language, src, root)
        now = _items(store)
        assert len(now) == len(news) < len(before)
        (row,) = [r for r in store.trash_rows() if r["item_id"] == before[-1][0]]
        if gone == "file":
            os.remove(os.path.join(data_dir, *row["trashed_path"].split("/")))
        else:
            with store._writing():
                store.conn.execute("DELETE FROM trash WHERE id = ?", (row["id"],))
        last = store.last_switch(work)
        with pytest.raises(ls.UndoRefused) as refused:
            store.undo_switch(work)
        assert "nothing was undone" in str(refused.value)
        assert _items(store) == now and [_copy(data_dir, rel) for _i, rel in now] == news
        assert store.last_switch(work) == last and not _notes(store) and not _pending(store)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows refuses to move a file held open")
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_held_check_never_moves_the_learners_copy(language, tmp_path, monkeypatch):
    """Is a copy held open? Asked without moving it: a crash or a failing move can never leave the copy under
    another name (the item missing). Held → not free; let go → free; the copy never renamed either way."""
    copy = str(tmp_path / "第01話.txt")
    _write(copy, _text(language, 1))
    moved = []
    for name in ("rename", "replace"):
        def watch(a, b, *x, _real=getattr(os, name), **k):
            moved.append(a)
            return _real(a, b, *x, **k)
        monkeypatch.setattr(os, name, watch)
    with open(copy, "rb"):
        assert ls._free_to_move(copy) is False
    assert ls._free_to_move(copy) is True
    assert moved == [] and os.listdir(str(tmp_path)) == ["第01話.txt"]


# --- an edition's Undo: carried on when pressed again, refused whole, never re-reading its EPUBs ------------------ #

def _new_edition(store, data_dir, language, times=1):
    """(Inside the store.) A book in, then its new edition switched whole -> (root, before, olds, work, the EPUB)."""
    src = _drive("Shelf")
    _book(language, src)
    root = store.add_source(src)
    _look(store, language, root, first=True)
    before = _items(store)
    olds = [_copy(data_dir, rel) for _i, rel in before]
    work = store.item(before[0][0])["work_id"]
    new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", times), language)
    _look(store, language, root)
    assert _items(store)[:len(before)] == before and len(_items(store)) == len(_parts(new, language))
    return root, before, olds, work, new


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_editions_undo_pressed_again_once_let_go_carries_the_same_undo_on(language, monkeypatch):
    """An edition's Undo waiting (a part held open), pressed again once the part is let go: the same Undo is carried
    on — the whole old edition back, no note left, no last switch — never refused as another switch of the book."""
    store, data_dir = _empty(language)
    with store:
        root, before, olds, work, _new = _new_edition(store, data_dir, language)
        real = _holding(monkeypatch, before[-1][1])
        assert getattr(store.undo_switch(work), "waiting", False)
        monkeypatch.setattr(ls, "trash_file", real)
        out = store.undo_switch(work)
        assert not getattr(out, "waiting", False) and out.switched == [i for i, _r in before]
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None
        assert not [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)]


@pytest.mark.parametrize("why", ["changed", "purged", "switching"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_an_editions_undo_that_cant_go_whole_is_refused_and_changes_nothing(language, why, monkeypatch):
    """An edition's Undo refused whole (`UndoRefused`), nothing changed — every part keeps the new edition and the
    title keeps its last switch — when a part changed since (its copy gone, marked missing), when an old part's copy
    is no longer in the trash (purged), or while another edition of the book is under way (one change of a book at a
    time)."""
    store, data_dir = _empty(language)
    with store:
        root, before, _olds, work, new = _new_edition(store, data_dir, language)
        news = [_copy(data_dir, rel) for _i, rel in before]
        kept = before
        if why == "changed":
            os.remove(os.path.join(data_dir, *before[0][1].split("/")))
            store.sync_disk()                            # the window's disk sync marks the copy missing
            assert store.item(before[0][0])["availability"] != "available"
            kept, news = before[1:], news[1:]
        elif why == "purged":
            record = ls._json_dict(store.meta()[ls.LAST_SWITCH + str(work)])
            os.remove(os.path.join(data_dir, ls._strip(record["swaps"][1]["trash"])))
        else:
            _holding(monkeypatch, before[-1][1])
            third = {"ja": "星の歌 (第3版)", "zh": "灯下书简（增订版）"}[language]
            _epub(os.path.join(os.path.dirname(new), f"{third}.epub"), _chapters(language, "三"), language, age=20)
            assert _look(store, language, root)["switched"] == 0
            assert [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)], "the third edition waits"
        with pytest.raises(ls.UndoRefused):
            store.undo_switch(work)
        assert [_copy(data_dir, rel) for _i, rel in kept] == news, "nothing undone"
        assert (store.last_switch(work) or {}).get("kind") == "edition", "the Undo is still there"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_editions_undo_takes_its_added_parts_out_when_every_old_part_was_removed(language):
    """A longer edition whose old parts the learner has all removed since: its Undo still takes out the parts the
    edition added (the removed ones stay removed) — the book is as the learner left the old edition."""
    store, data_dir = _empty(language)
    with store:
        root, before, _olds, work, _new = _new_edition(store, data_dir, language, times=2)
        grown = _items(store)
        assert len(grown) > len(before)
        store.remove([i for i, _r in before])
        assert _items(store) == grown[len(before):]
        store.undo_switch(work)
        assert _items(store) == []
        assert store.last_switch(work) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_editions_undo_keeps_its_epub_from_being_read_again_even_changed(language, monkeypatch):
    """An edition's Undo waiting (a part held open), the new edition's EPUB rewritten meanwhile: no look hashes or
    splits it while the Undo's note stands (the next look carries the Undo on first)."""
    store, data_dir = _empty(language)
    with store:
        root, before, _olds, work, new = _new_edition(store, data_dir, language)
        _holding(monkeypatch, before[-1][1])
        assert getattr(store.undo_switch(work), "waiting", False)
        new = os.path.abspath(_epub(new, _chapters(language, "再"), language, age=30))
        split, hashed = [], []
        real_parts, real_sha = sources.book_parts, ls.sha256_of
        with monkeypatch.context() as patched:
            patched.setattr(sources, "book_parts", lambda p, lang, **kw: split.append(p) or real_parts(p, lang, **kw))
            patched.setattr(ls, "sha256_of", lambda p: (hashed.append(p) if os.path.abspath(p) == new else None)
                            or real_sha(p))
            _look(store, language, root, full=True)
        assert (split, hashed) == ([], [])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_second_undo_of_a_changed_declined_edition_is_not_read_again(language, monkeypatch):
    """Undo, the declined edition's EPUB rewritten, the look switches to it, Undo again: the second Undo's declined
    records hold the EPUB's bytes and stats as they are now — the next look neither hashes nor splits it (S19)."""
    store, data_dir = _empty(language)
    with store:
        root, before, olds, work, new = _new_edition(store, data_dir, language)
        store.undo_switch(work)
        new = os.path.abspath(_epub(new, _chapters(language, "再"), language, age=30))
        assert _look(store, language, root, full=True)["switched"] == len(before)
        store.undo_switch(work)
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
        split, hashed = [], []
        real_parts, real_sha = sources.book_parts, ls.sha256_of
        with monkeypatch.context() as patched:
            patched.setattr(sources, "book_parts", lambda p, lang, **kw: split.append(p) or real_parts(p, lang, **kw))
            patched.setattr(ls, "sha256_of", lambda p: (hashed.append(p) if os.path.abspath(p) == new else None)
                            or real_sha(p))
            assert _look(store, language, root, full=True)["switched"] == 0
        assert (split, hashed) == ([], [])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_same_path_editions_undo_is_not_read_again_by_the_next_look(language, monkeypatch):
    """A3: the Undo of a same-path new edition keeps the old text's records with the EPUB's stats as they are now —
    the next look neither hashes nor splits the EPUB (S19), and switches nothing."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    book = os.path.abspath(_book(language, src))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        _epub(book, _chapters(language, "改"), language, age=30)
        assert _look(store, language, root)["switched"] == len(before)
        store.undo_switch(store.item(before[0][0])["work_id"])
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
        split, hashed = [], []
        real_parts, real_sha = sources.book_parts, ls.sha256_of
        with monkeypatch.context() as patched:
            patched.setattr(sources, "book_parts", lambda p, lang, **kw: split.append(p) or real_parts(p, lang, **kw))
            patched.setattr(ls, "sha256_of", lambda p: (hashed.append(p) if os.path.abspath(p) == book else None)
                            or real_sha(p))
            assert _look(store, language, root, full=True)["switched"] == 0
        assert (split, hashed) == ([], [])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_part_renamed_while_its_new_edition_waits_is_switched_at_its_new_name(language, monkeypatch):
    """A new edition waiting (a part held open), meanwhile another part's copy renamed in the library and linked
    again by the learner (*Link a file*): the waiting change is judged again, never carried on at the old name — the
    next looks end on the whole new edition, the renamed part at its new name, nothing at the old one."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        real = _holding(monkeypatch, before[-1][1])
        assert _look(store, language, root)["switched"] == 0
        assert [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)], "the edition waits"
        folder, name = before[0][1].rsplit("/", 1)
        moved = f"{folder}/renamed {name}"
        os.rename(os.path.join(data_dir, *before[0][1].split("/")), os.path.join(data_dir, *moved.split("/")))
        store.relink(before[0][0], os.path.join(data_dir, *moved.split("/")))   # the window's *Link a file*
        assert store.item(before[0][0])["rel_path"] == moved
        monkeypatch.setattr(ls, "trash_file", real)
        _look(store, language, root, full=True)
        _look(store, language, root, full=True)
        now = _items(store)
        assert now == [(before[0][0], moved)] + before[1:]
        assert _whole(data_dir, now, _parts(new, language))
        assert not os.path.exists(os.path.join(data_dir, *before[0][1].split("/")))
        assert not [k for k in store.meta() if k.startswith(ls.SWITCH_PENDING)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_editions_staged_part_lost_meanwhile_is_judged_again_never_waits_for_ever(language, monkeypatch):
    """A new edition waiting (a part held open), meanwhile one of its staged new parts gone from the trash: once let
    go, the waiting change is dropped (its bytes no longer there to take), the book judged again — the next looks end
    on the whole new edition, no note left."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        real = _holding(monkeypatch, before[-1][1])
        assert _look(store, language, root)["switched"] == 0
        (value,) = [v for k, v in store.meta().items() if k.startswith(ls.EDITION_PENDING)]
        os.remove(os.path.join(data_dir, ls._strip(ls._json_dict(value)["parts"][0]["part"])))
        monkeypatch.setattr(ls, "trash_file", real)
        _look(store, language, root, full=True)
        _look(store, language, root, full=True)
        assert _items(store) == before and _whole(data_dir, before, _parts(new, language))
        assert not [k for k in store.meta() if k.startswith(ls.SWITCH_PENDING)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_crashed_edition_whose_part_changed_keeps_its_note_until_every_part_is_back(language, monkeypatch):
    """A crash mid-switch (the first part's swap committed), then another part linked to a new name by the learner:
    the next look takes the change back — and while the first part's copy is held open it can't go back, so the note
    stays (never dropped with the book half old, half new); let go, the book ends whole on one edition."""
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
    _a_minute_later(monkeypatch)
    store = ls.open_store(language, data_dir, uf)
    with store:
        folder, name = before[-1][1].rsplit("/", 1)
        moved = f"{folder}/renamed {name}"
        os.rename(os.path.join(data_dir, *before[-1][1].split("/")), os.path.join(data_dir, *moved.split("/")))
        store.relink(before[-1][0], os.path.join(data_dir, *moved.split("/")))   # the window's *Link a file*
        real = _holding(monkeypatch, before[0][1])
        _look(store, language, root, full=True)
        assert [k for k in store.meta() if k.startswith(ls.EDITION_PENDING)], "a part not back yet: the note stays"
        monkeypatch.setattr(ls, "trash_file", real)
        _look(store, language, root, full=True)
        _look(store, language, root, full=True)
        now = _items(store)
        assert [i for i, _r in now] == [i for i, _r in before]
        assert _whole(data_dir, now, _parts(new, language))
        assert not [k for k in store.meta() if k.startswith(ls.SWITCH_PENDING)]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows refuses to move a file held open")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_edition_whose_part_is_still_held_swaps_nothing_at_the_next_look(language, monkeypatch):
    """A new edition waiting on a part held open: while it stays held, the next look probes that part first and
    swaps nothing (no part switched and switched back); let go, it switches whole."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        copy = os.path.abspath(os.path.join(data_dir, *before[-1][1].split("/")))
        real = _holding(monkeypatch, before[-1][1])
        assert _look(store, language, root)["switched"] == 0
        steps, real_step = [], ls.Store._switch_step
        with monkeypatch.context() as patched, open(copy, "rb"):     # still open in a reader
            patched.setattr(ls.Store, "_switch_step", lambda self, *a, **k: steps.append(1) or real_step(self, *a, **k))
            assert _look(store, language, root, full=True)["switched"] == 0
        assert steps == []
        monkeypatch.setattr(ls, "trash_file", real)
        assert _look(store, language, root, full=True)["switched"] == len(before)
        assert _whole(data_dir, before, _parts(new, language))


# --- a book's new edition: a busy library never gives a part up; a failing step leaves the whole old book --------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_busy_library_never_leaves_an_editions_extra_parts_out(language, monkeypatch):
    """A longer edition's extra parts meeting a busy library (another window writing) look after look, more looks
    than a failing part may wait: the edition waits each time (busy is never a reason to give a part up) and, once
    the library is free, every part goes in."""
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
        real = store.take_in

        def busy(root_id, found, **k):
            if any(str(f.get("origin", "")).startswith(os.path.abspath(longer)) for f in found):
                raise ls.StoreBusy("database is locked")
            return real(root_id, found, **k)
        with monkeypatch.context() as patched:
            patched.setattr(store, "take_in", busy)
            _look(store, language, root)
            for _n in range(ls.EDITION_TRIES + 1):
                assert _notes(store), "a busy library: the edition waits"
                _look(store, language, root, full=True)
        assert _notes(store) and len(_items(store)) == len(before)
        _look(store, language, root, full=True)
        now = _items(store)
        assert now[:len(before)] == before and [_copy(data_dir, r) for _i, r in now] == parts
        assert not _notes(store) and (store.last_switch(work) or {}).get("kind") == "edition"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_part_step_failing_mid_edition_keeps_the_whole_old_book_until_the_next_look(language, monkeypatch):
    """A longer new edition whose second part step fails (the store failing, not a file held): every part goes back,
    so until the next look the book is the whole old edition (no part new, no extra part in), and the next look
    switches it whole."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        longer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2),
                       language)
        parts = _parts(longer, language)
        monkeypatch.setattr(ls, "SWITCH_BATCH", 1)
        real, calls = ls.Store._switch_step, []

        def step(self, kind, *a, **k):
            calls.append(kind)
            if len(calls) == 2:
                raise ls.StoreError("disk I/O error")
            return real(self, kind, *a, **k)
        with monkeypatch.context() as patched:
            patched.setattr(ls.Store, "_switch_step", step)
            _look(store, language, root)
        assert len(calls) > 2, "the first part went back"
        assert _items(store) == before and [_copy(data_dir, rel) for _i, rel in before] == olds
        assert _notes(store)
        _look(store, language, root, full=True)
        now = _items(store)
        assert now[:len(before)] == before and [_copy(data_dir, r) for _i, r in now] == parts
        assert not _notes(store)


def _shorter(store, data_dir, language, src):
    """A two-chapter book in, then a one-chapter new edition switched -> (root, before, olds, now, work)."""
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    root = store.add_source(src)
    _look(store, language, root, first=True)
    before = _items(store)
    olds = [_copy(data_dir, rel) for _i, rel in before]
    work = store.item(before[0][0])["work_id"]
    _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 1), language)
    _look(store, language, root)
    now = _items(store)
    assert len(before) - len(now) >= 2, "two parts past the new edition's end"
    return root, before, olds, now, work


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undos_parts_past_the_end_go_back_when_one_was_put_back_by_hand_meanwhile(language, monkeypatch):
    """A shorter edition's Undo waiting (a part held open), meanwhile the learner puts one of the parts past its end
    back from the trash by hand: once let go, the Undo puts the others back too: the whole old book, nothing left in
    the trash, no Undo left."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    with store:
        root, before, olds, now, work = _shorter(store, data_dir, language, src)
        real = _holding(monkeypatch, now[-1][1])
        assert getattr(store.undo_switch(work), "waiting", False)
        tail = [r for r in store.trash_rows() if r["item_id"] in {i for i, _r in before[len(now):]}
                and not r["restored_at"]]
        assert len(tail) >= 2
        rel, _why = ls.put_back(data_dir, tail[0]["trashed_path"], tail[0]["rel_path"])
        store.restore([tail[0]["id"]], {tail[0]["id"]: rel} if rel != tail[0]["rel_path"] else None)
        monkeypatch.setattr(ls, "trash_file", real)
        _look(store, language, root, full=True)
        assert sorted(_items(store)) == sorted(before)
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
        assert not [r for r in store.trash_rows() if r["id"] in {t["id"] for t in tail} and not r["restored_at"]]
        assert store.last_switch(work) is None and not _notes(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undo_meeting_a_busy_library_as_it_puts_the_tail_back_waits_and_ends_whole(language, monkeypatch):
    """A shorter edition's Undo whose putting back of the parts past its end meets a busy library (another window
    writing): the Undo waits (said so) instead of ending without them; the next look puts them back: the whole old
    book, no Undo left."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    with store:
        root, before, olds, _now, work = _shorter(store, data_dir, language, src)
        real, calls = store.restore, []

        def busy(*a, **k):
            if k.get("kind") == "undo" and not calls:
                calls.append(1)
                raise ls.StoreBusy("database is locked")
            return real(*a, **k)
        with monkeypatch.context() as patched:
            patched.setattr(store, "restore", busy)
            out = store.undo_switch(work)
        assert calls and getattr(out, "waiting", False)
        assert _notes(store) and (store.last_switch(work) or {}).get("kind") == "edition"
        _look(store, language, root, full=True)
        assert _items(store) == before and [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None and not _notes(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_extra_part_left_out_counts_its_thirty_days_in_the_trash_from_then(language, monkeypatch):
    """A longer edition's extra part whose move in fails look after look, its staged file a month old by then: left
    out, the file sits in the trash with its 30 days counted from the leaving out, never purged at the next clean-up
    (as after any removal)."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2), language)
        rows = len(store.trash_rows())
        real = ls.rename_no_overwrite

        def refused(a, b):
            if ".trash" in a.replace("\\", "/").split("/"):
                raise PermissionError(a)          # the staged extra part can't be moved in
            return real(a, b)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "rename_no_overwrite", refused)
            _look(store, language, root)
            (value,) = [v for k, v in store.meta().items() if k.startswith(ls.EDITION_PENDING)]
            old = time.time() - 40 * 86400
            staged = [os.path.join(data_dir, ls._strip(x["part"])) for x in ls._json_dict(value)["extras"]]
            assert staged
            for path in staged:
                os.utime(path, (old, old))
            for _n in range(ls.EDITION_TRIES):
                if _notes(store):
                    _look(store, language, root, full=True)
        assert not _notes(store) and len(_items(store)) == len(before)
        extra = store.trash_rows()[rows:]
        assert extra
        for row in extra:
            path = os.path.join(data_dir, *row["trashed_path"].split("/"))
            assert time.time() - os.path.getmtime(path) < 86400, "its 30 days count from the leaving out"


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_runners_of_one_new_edition_still_end_whole_at_the_next_look(language, monkeypatch):
    """Under the claim: should a second runner ever carry a new edition while the first works (the second meeting a
    part held open, so it puts the switched parts back and waits), the first, ending, drops the note and writes the
    last switch only once every part reads the new edition; else the note waits and the next look ends the book
    whole (never a mixed book with nothing left to finish it)."""
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
        news = _parts(new, language)
        at = next(i for i, (o, n) in enumerate(zip(olds, news)) if o != n) + 2     # once a part that differs went in
        assert at <= len(before)
        monkeypatch.setattr(ls, "SWITCH_BATCH", 1)
        real, real_trash = ls.Store._switch_step, ls.trash_file
        calls, inner = [], [False]

        def step(self, kind, by, work_id, ready, *a, **k):
            if kind == "switch_version" and not inner[0] and ready:
                calls.append(1)
                if len(calls) == at:
                    (key,) = _notes(store)
                    inner[0] = True
                    try:
                        with monkeypatch.context() as patched:   # the second runner: this part's copy held open
                            patched.setattr(ls, "trash_file", lambda d, r, to=None: (_ for _ in ()).throw(
                                PermissionError(r)) if r == before[at - 1][1] else real_trash(d, r, to=to))
                            store._edition_go(key)
                    finally:
                        inner[0] = False
            return real(self, kind, by, work_id, ready, *a, **k)
        with monkeypatch.context() as patched:
            patched.setattr(ls.Store, "_switch_step", step)
            _look(store, language, root)
        assert len(calls) >= at
        now = [_copy(data_dir, rel) for _i, rel in before]
        assert now == news or _notes(store), "a mixed book with nothing left to finish it"
        _look(store, language, root, full=True)
        assert _items(store) == before and _whole(data_dir, before, news)
        assert not _notes(store) and not _pending(store)
        assert (store.last_switch(work) or {}).get("kind") == "edition"


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_pressed_again_once_its_note_counts_as_crashed_but_its_step_not_yet_waits(language, monkeypatch):
    """Killed inside the Undo's second part step, its note's time renewed up to a quarter minute before that step
    began: pressed again once the note counts as crashed but the step not yet, the press is told the Undo is under
    way and changes nothing (the crashed step is put back first, by a later look); the look then finishes the Undo:
    the whole old edition."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        before, olds, news, work = _switched(store, data_dir, language, src, root)
        uf = store.user_files_dir
    _crash(language, data_dir, uf, root, "undo-before", 2, work)
    store = ls.open_store(language, data_dir, uf)
    with store:
        (key,) = _notes(store)
        assert _pending(store) != [key]
        note = ls._json_dict(store.meta()[key])
        store.bookkeeping({key: ls._dumps(dict(note, at=time.time() - ls.SWITCH_STALE_S - 1))})
        held = [_copy(data_dir, rel) for _i, rel in before]
        again = store.undo_switch(work)
        assert again.waiting and again.notes
        assert [_copy(data_dir, rel) for _i, rel in before] == held and _notes(store)
        _a_minute_later(monkeypatch)
        _look(store, language, root, full=True)
        assert [_copy(data_dir, rel) for _i, rel in before] == olds
        assert store.last_switch(work) is None and not _notes(store) and not _pending(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_shorter_edition_whose_part_past_its_end_goes_missing_as_it_switches_waits(language, monkeypatch):
    """A7 for the parts past the end, at the store: a shorter new edition whose part past its end has its copy
    deleted outside the app just as the switch begins (the window's disk sync marking it missing): nothing switched,
    nothing taken out; the part back, the next look switches it whole."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        gone = os.path.join(data_dir, *before[-1][1].split("/"))
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 1), language)
        news = _parts(new, language)
        assert len(news) < len(before)
        real = store.switch_parts

        def meanwhile(*a, **k):
            os.remove(gone)
            store.sync_disk()                            # the window's disk sync marks the copy missing
            return real(*a, **k)
        with monkeypatch.context() as patched:
            patched.setattr(store, "switch_parts", meanwhile)
            assert _look(store, language, root)["switched"] == 0
        assert store.item(before[-1][0])["availability"] != "available"
        assert _items(store) == before and not _notes(store)
        assert [_copy(data_dir, rel) for _i, rel in before[:-1]] == olds[:-1]
        with open(gone, "wb") as f:
            f.write(olds[-1])
        store.sync_disk()                                # back: the part available again
        assert _look(store, language, root, full=True)["switched"] == len(news)
        assert _items(store) == before[:len(news)] and _whole(data_dir, before[:len(news)], news)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_edition_that_must_wait_for_another_leaves_no_staged_file_behind(language, monkeypatch):
    """A third edition of a book while the second still waits (a part held open): the third waits its turn (one
    change of a book at a time) and its parts, staged for it, are cleared away; nothing new is left in the trash."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
        _holding(monkeypatch, before[-1][1])
        assert _look(store, language, root)["switched"] == 0
        assert _notes(store), "the second edition waits"
        trash = os.path.join(data_dir, ".trash")
        kept = sorted(os.listdir(trash))
        third = {"ja": "星の歌 (第3版)", "zh": "灯下书简（增订版）"}[language]
        _epub(os.path.join(os.path.dirname(new), f"{third}.epub"), _chapters(language, "三"), language, age=20)
        split = []
        real_parts = sources.book_parts
        with monkeypatch.context() as patched:
            patched.setattr(sources, "book_parts", lambda p, lang, **kw: split.append(p) or real_parts(p, lang, **kw))
            assert _look(store, language, root, full=True)["switched"] == 0
        assert split, "the third edition was read"
        assert sorted(os.listdir(trash)) == kept


@pytest.mark.parametrize("mode", ["trash-after", "remove"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_part_past_the_end_moved_before_a_crash_comes_back_with_its_text_on_undo(language, mode, monkeypatch):
    """The process killed once a shorter edition's part past its end had its copy moved to the trash (before its row
    went): the next look ends the edition with that part's trash row naming its file, so the Undo brings the whole
    old book back with every part's own text (never a part back with no file)."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        olds = [_copy(data_dir, rel) for _i, rel in before]
        uf = store.user_files_dir
    new = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改"), language)
    short = _parts(new, language)
    _crash(language, data_dir, uf, root, mode, len(short) + 1)
    _a_minute_later(monkeypatch)
    store = ls.open_store(language, data_dir, uf)
    with store:
        _look(store, language, root, full=True)
        rows = [r for r in store.trash_rows() if r["item_id"] in {i for i, _r in before[len(short):]}]
        assert rows and all(r["trashed_path"] for r in rows)
        store.undo_switch(store.item(before[0][0])["work_id"])
        assert _items(store) == before
        assert [_copy(data_dir, rel) for _i, rel in before] == olds


# --- round 4: a part given up goes to the trash list in the write that takes it in; one runner's waiting mark ------ #

class _Killed(BaseException):
    """The process killed here (no `except Exception` catches it)."""


def _refused(real):
    """The staged extra parts can't be moved in (their move out of the trash refused, look after look)."""
    def refused(a, b):
        if ".trash" in a.replace("\\", "/").split("/"):
            raise PermissionError(a)
        return real(a, b)
    return refused


@pytest.mark.parametrize("language", LANGUAGES)
def test_killed_between_the_given_up_parts_take_in_and_its_removal_never_loses_its_text(language, monkeypatch):
    """A longer edition's extra parts given up (their move in failing EDITION_TRIES looks) are taken in at a free name
    and sent to the trash list. Killed between the two: the take-in is never kept without its removal (one write), so
    the stored note still names each staged file, and the next look — the move working again — takes every part in
    with its text (never a part in the library with no copy and its staged text deleted)."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        longer = _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2),
                       language)
        parts = _parts(longer, language)
        real_remove = store.remove

        def remove(ids, trashed_paths=None, **k):
            if trashed_paths and k.get("exclude") is False and k.get("by") != "undo":
                raise _Killed()
            return real_remove(ids, trashed_paths=trashed_paths, **k)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "rename_no_overwrite", _refused(ls.rename_no_overwrite))
            patched.setattr(store, "remove", remove)
            _look(store, language, root)
            with pytest.raises(_Killed):
                for _n in range(ls.EDITION_TRIES + 1):
                    _look(store, language, root, full=True)
        (key,) = _notes(store)
        note = ls._edition_note(store, key)
        staged = [x["part"] for x in note["extras"] if x.get("part")]
        assert staged and all(os.path.isfile(os.path.join(data_dir, *p.split("/"))) for p in staged)
        _a_minute_later(monkeypatch)
        _look(store, language, root, full=True)
        assert not _notes(store)
        now = _items(store)
        holes = [rel for _i, rel in now if not os.path.isfile(os.path.join(data_dir, *rel.split("/")))]
        assert not holes, f"{len(holes)} part(s) in the library with no copy"
        assert [_copy(data_dir, r) for _i, r in now] == parts


@pytest.mark.parametrize("language", LANGUAGES)
def test_killed_once_the_given_up_parts_are_on_the_trash_list_keeps_them_there(language, monkeypatch):
    """Killed after the given-up parts' write (taken in, removed: each a trash row naming its staged file) but before
    the edition ends: the stored note says they were given up, so the next look never moves a staged file out from
    under its trash row (nor takes it in a second time) — each row still brings its part back with its text."""
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
        rows = len(store.trash_rows())

        def done(*a, **k):
            raise _Killed()
        with monkeypatch.context() as patched:
            patched.setattr(ls, "rename_no_overwrite", _refused(ls.rename_no_overwrite))
            patched.setattr(ls, "_edition_done", done)
            _look(store, language, root)
            with pytest.raises(_Killed):
                for _n in range(ls.EDITION_TRIES + 1):
                    _look(store, language, root, full=True)
        assert _notes(store)
        _a_minute_later(monkeypatch)                # the move works again
        _look(store, language, root, full=True)
        assert not _notes(store) and _items(store) == before
        extra = store.trash_rows()[rows:]
        assert len(extra) == len(parts) - len(before)
        rels = {}
        for row in extra:
            assert row["trashed_path"] and os.path.isfile(os.path.join(data_dir, *row["trashed_path"].split("/")))
            rels[row["id"]], _why = ls.put_back(data_dir, row["trashed_path"], row["rel_path"])
        store.restore(sorted(rels), rels)
        now = _items(store)
        assert len(now) == len(parts) and [_copy(data_dir, r) for _i, r in now] == parts


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_extra_part_given_up_never_removes_the_learners_item_holding_its_name(language, monkeypatch):
    """A longer edition's extra part given up, its name free on disk but held by an item of the learner's (its copy
    missing): the part goes in at a name no row holds either, and only what the take-in itself added goes to the
    trash list — the learner's item stays, and the part's trash row still brings it back with its text."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        before = _items(store)
        _epub(os.path.join(src, "Books", f"{_EDITION[language]}.epub"), _chapters(language, "改", 2), language)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "rename_no_overwrite", _refused(ls.rename_no_overwrite))
            _look(store, language, root)
            (key,) = _notes(store)
            x = ls._edition_note(store, key)["extras"][0]
            full = os.path.join(data_dir, *x["rel"].split("/"))
            _write(full, _text(language, 9, " 私の"))
            store.insert([full], "now")
            mine = store.item_id(x["rel"])
            assert mine is not None and mine not in [i for i, _r in before]
            os.remove(full)                             # its copy gone since: the item stays, missing
            for _n in range(ls.EDITION_TRIES + 1):
                if _notes(store):
                    _look(store, language, root, full=True)
        assert not _notes(store)
        assert store.item(mine) is not None, "the learner's item was removed by the edition"
        assert not [r for r in store.trash_rows() if r["item_id"] == mine]
        (row,) = [r for r in store.trash_rows() if r["trashed_path"] == x["part"]]
        assert ls.path_key(row["rel_path"]) != ls.path_key(x["rel"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_settle_whose_own_claim_fails_busy_never_marks_a_carried_note_waiting(language, monkeypatch):
    """An Undo left waiting (a part held). A look's settle reads the note as due; meanwhile the learner's re-press
    claims it (carried). The look's own claim then meets a busy library: it leaves the note as the re-press holds it
    — never marked waiting again, for a third runner to take while the re-press carries it."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _book(language, src)
    with store:
        root = store.add_source(src)
        before, _olds, _news, work = _switched(store, data_dir, language, src, root)
        real = _holding(monkeypatch, before[-1][1])
        assert store.undo_switch(work).waiting
        monkeypatch.setattr(ls, "trash_file", real)
        (key,) = _notes(store)
        assert ls._json_dict(store.meta()[key])["waiting"]
        real_take = ls._edition_take
        claimed = []

        def take(self, k, now=None):
            if not claimed:
                claimed.append(real_take(self, k))     # the re-press claims it first
                raise ls.StoreBusy("the write lock timed out")    # the look's own claim: busy
            return real_take(self, k, now)
        with monkeypatch.context() as patched:
            patched.setattr(ls, "_edition_take", take)
            patched.setattr(ls.Store, "_edition_go", lambda self, k: pytest.fail("the look never runs it"),
                            raising=False)
            store.settle_editions()
        assert claimed == [True], "the re-press carries the note"
        note = ls._json_dict(store.meta()[key])
        assert not ls._edition_due(note), "a note the re-press carries was marked waiting by the look's failed claim"
        assert real_take(store, key) is False, "a third runner took the note the re-press carries"


def _aged(path, days=40):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undo_claimed_restarts_the_thirty_days_of_every_file_it_will_put_back(language, monkeypatch):
    """A shorter edition's Undo claimed (here it waits: a part held): the old edition's copies in the trash and the
    parts past its end each count their 30 days from now, so none is purged while the Undo waits."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        before, _olds, _news, work = _switched(store, data_dir, language, src, root)
        now = _items(store)
        swaps = ls._json_dict(store.meta()[ls.LAST_SWITCH + str(work)])["swaps"]
        gone = {i for i, _r in before} - {i for i, _r in now}
        tail = [r["trashed_path"] for r in store.trash_rows() if r["item_id"] in gone and not r["restored_at"]]
        files = [os.path.join(data_dir, *p.split("/")) for p in tail + [s["trash"] for s in swaps]]
        assert tail and all(os.path.isfile(f) for f in files)
        for f in files:
            _aged(f)
        _holding(monkeypatch, now[0][1])
        started = time.time() - 60
        assert store.undo_switch(work).waiting
        assert all(os.path.getmtime(f) > started for f in files), "a file the Undo puts back kept its old clock"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undo_waiting_while_its_tail_is_purged_is_refused_whole(language, monkeypatch):
    """A shorter edition's Undo waits (a part held); meanwhile the parts past its end leave the trash for good. The
    next look never finishes it with parts missing: refused whole, said in its notes — the new edition stays, every
    part with its copy."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        before, _olds, news, work = _switched(store, data_dir, language, src, root)
        now = _items(store)
        assert len(now) == len(news) < len(before)
        real = _holding(monkeypatch, now[0][1])
        assert store.undo_switch(work).waiting
        gone = {i for i, _r in before} - {i for i, _r in now}
        for r in store.trash_rows():
            if r["item_id"] in gone and not r["restored_at"] and r["trashed_path"]:
                os.remove(os.path.join(data_dir, *r["trashed_path"].split("/")))     # purged meanwhile
        monkeypatch.setattr(ls, "trash_file", real)
        changes = store.settle_editions()
        assert not _notes(store)
        assert any("no longer in the trash" in n for c in changes for n in c.notes)
        assert _items(store) == now and [_copy(data_dir, rel) for _i, rel in now] == news
        assert all((store.item(i) or {}).get("availability") == "available" for i, _r in now)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_undo_with_no_parts_killed_between_its_tail_moves_and_restore_finishes_whole(language, monkeypatch):
    """A shorter edition; the learner then removes every part it kept and presses Undo: only the parts past the end to
    put back. Killed after their files left the trash for their library names, before the one restore commits. The
    next look reads those files as moved back, not purged, and finishes the restore: every part an item again, none at
    its library name with no item and its trash row unrestored."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        before, _olds, _news, work = _switched(store, data_dir, language, src, root)
        now = _items(store)
        assert len(now) < len(before)
        gone = {i for i, _r in before} - {i for i, _r in now}
        store.remove([i for i, _r in now])                 # the learner removes every part the edition kept
        real_restore = store.restore

        def restore(ids, rel_paths=None, **k):
            if k.get("kind") == "undo":
                raise _Killed()
            return real_restore(ids, rel_paths, **k)
        with monkeypatch.context() as patched:
            patched.setattr(store, "restore", restore)
            with pytest.raises(_Killed):
                store.undo_switch(work)
        assert _notes(store), "the Undo's note stands after the kill"
        _a_minute_later(monkeypatch)
        changes = store.settle_editions()
        notes = [n for c in changes for n in c.notes]
        assert not _notes(store) and not any("no longer in the trash" in n for n in notes), notes
        rows = [r for r in store.trash_rows() if r["item_id"] in gone]
        assert rows and all(r["restored_at"] for r in rows), "a part past the end left with its trash row unrestored"
        for r in rows:
            assert store.item_id(r["rel_path"]) is not None
            assert os.path.isfile(os.path.join(data_dir, *r["rel_path"].split("/")))


@pytest.mark.parametrize("language", LANGUAGES)
# why: an Undo of swapped parts skips a part the learner removed since and still puts every other part back to the old
# edition; stopping at the removed part would leave the rest of the book on the new edition.
def test_an_undo_of_swapped_parts_skips_a_removed_part_and_still_puts_the_others_back(language):
    """Every old part changed in place (none dropped; a longer edition adds its extra parts at the end). The learner
    removed the first part since; the Undo keeps that part removed and puts every other part back to the old edition's
    bytes."""
    store, data_dir = _empty(language)
    src = _drive("Shelf")
    _epub(os.path.join(src, "Books", f"{_BOOKS[language]}.epub"), _chapters(language, "", 2), language)
    with store:
        root = store.add_source(src)
        before, olds, _news, work = _switched(store, data_dir, language, src, root, more=2)
        assert _items(store)[:len(before)] == before      # the switch dropped no old part; a longer edition adds at the end
        now = _items(store)                               # the parts the store holds after the switch, not the old list
        assert len(now) > 1
        store.remove([now[0][0]])
        assert _items(store) == now[1:]
        store.undo_switch(work)
        assert _items(store) == before[1:]
        assert [_copy(data_dir, rel) for _i, rel in _items(store)] == olds[1:]
