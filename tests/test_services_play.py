"""The file ▶ opens (`app/services/play.py`; laptop fix "play", FEEDBACK row 5; review AD-2 – AD-6, IK-3), Qt-free: a
real store with a source folder read in place, real Japanese subtitles and an EPUB from tests/Test Resources, made-up
show names, video stand-ins (never played: nothing here opens a file).

What a wrong answer would cost a learner:
  * ▶ on an episode from a folder read in place that says "no video beside it" while the video sits beside the
    original (the subtitle's copy is in `Library/`, the video never is) — the bug Sonic hit;
  * ▶ on a book that opens a text copy of one part instead of his EPUB;
  * a video hato paired passed over for another file of the same name, or a relative path opened wherever the
    process runs; one that moved left unfound, or another episode under its name opened in its place;
  * an offline share (N:\\Media\\…) that makes ▶ wait in silence, a stat per name and extension, or a book on one
    swapped for its text copy unsaid;
  * "no video" said when the truth is that the library can't be read just now;
  * ▶ and the row's status disagreeing: a `.ts` Connect mines that ▶ can't find, a cloud placeholder ▶ downloads that
    Connect refuses, a video only Connect's index knows.
"""
import json
import os
import time

import pytest

from app import library_store as ls
from app import path_utils, sources
from app.connect import videos
from app.services import play
from tests.test_library_store_support import library, write_manifest
from tests.test_sources_scan import _chapters, _epub

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
SHOW = "月影の旅人"                                   # a made-up show
GROUP = "[Hoshizora Subs]"                            # a made-up release group


@pytest.fixture(autouse=True)
def _fresh_run():
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


def _name(n, ext):
    """A release's name, as a download folder holds them: `[group] <show> - 09 (1080p) [crc].mkv`."""
    return f"{GROUP} {SHOW} - {n:02d} (1080p) [8F3A2C1D]{ext}"


def _subtitle(path, n):
    with open(os.path.join(RESOURCES, "ja", "phrases_sample.srt"), encoding="utf-8") as f:
        text = f.read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + f"\n{n}\n")
    t = time.time() - 60
    os.utime(path, (t, t))
    return path


def _video(path):
    """A video stand-in (Matroska's magic, a few bytes), settled like a finished download."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x1a\x45\xdf\xa3 stand-in matroska " + os.path.basename(path).encode("utf-8"))
    t = time.time() - 60
    os.utime(path, (t, t))
    return path


def _store():
    data_dir, user_files_dir, doc = library("ja", shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain("ja", data_dir, user_files_dir) == ls.EXIT_DONE
    return ls.open_store("ja", data_dir, user_files_dir)


def _read_in_place(folder):
    """`folder` added as a source and read (setup's first look) -> {origin: (item_id, rel_path)}."""
    store = _store()
    with store:
        root = store.add_source(folder)
        assert sources.scan(store, "ja", root, first=True)["added"] >= 1
        return {o.origin: (o.item_id, o.rel_path) for o in store.origins().values()}


def _elsewhere(*parts):
    return os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", *parts)


def _copy(name):
    """A subtitle's copy in `Library/<show>/` with no store record (a 2.x library's file) -> (rel_path, its folder)."""
    rel = f"Library/{SHOW}/{name}"
    path = os.path.join(path_utils.get_data_path("ja"), *rel.split("/"))
    _subtitle(path, 1)
    return rel, os.path.dirname(path)


# --- a folder read in place: the real store's record ------------------------------------------------------------ #
def test_an_episode_from_a_folder_read_in_place_opens_the_video_beside_its_original():
    folder = _elsewhere("Downloads", SHOW)
    subs = {n: _subtitle(os.path.join(folder, _name(n, ".ja.srt")), n) for n in (9, 10, 11, 12)}
    v09 = _video(os.path.join(folder, _name(9, ".mkv")))                 # there at the look: the record names it
    items = _read_in_place(folder)
    v10 = _video(os.path.join(folder, _name(10, ".MKV")))                # downloaded after its subtitle, any case
    v11 = _video(os.path.join(folder, _name(11, ".ts")))                 # a broadcast recording: Connect mines it
    found = {n: play.to_open("ja", *items[os.path.abspath(subs[n])], "anime") for n in subs}
    assert found[9] == (os.path.abspath(v09), None)
    assert found[10] == (v10, None)
    assert found[11] == (v11, None)
    assert found[12] == (None, "no video beside it on disk")


def test_part_two_of_an_epub_a_folder_holds_opens_the_book_itself():
    book = _epub(_elsewhere("Books", "星の歌.epub"), _chapters())
    items = _read_in_place(_elsewhere("Books"))
    item_id, rel = items[os.path.abspath(book) + "#2"]
    assert rel.startswith("Library/") and rel.endswith(".txt")           # the part's text copy...
    assert play.to_open("ja", item_id, rel, "book") == (os.path.abspath(book), None)   # ... but ▶ opens the book


# --- the record's video ------------------------------------------------------------------------------------------- #
def test_a_hato_records_video_wins_over_one_beside_the_copy_and_a_relative_one_is_never_taken(monkeypatch):
    rel, copies = _copy(_name(9, ".ja.srt"))
    beside = _video(os.path.join(copies, _name(9, ".mkv")))
    paired = _video(_elsewhere("hato", "第9話.mkv"))
    monkeypatch.setattr(play, "pairing", lambda language, item_id: {"producer": "hato", "video_path": paired})
    assert play.to_open("ja", 1, rel, "anime") == (paired, None)
    # AD-4: a relative path would open a file wherever the process happens to run
    monkeypatch.chdir(os.path.dirname(paired))
    monkeypatch.setattr(play, "pairing", lambda language, item_id: {"producer": "hato", "video_path": "第9話.mkv"})
    assert play.to_open("ja", 1, rel, "anime") == (beside, None)


@pytest.mark.parametrize("producer", ["hato", "source"])
def test_a_paired_video_that_moved_opens_where_the_index_holds_its_name_and_size_only_when_its_bytes_match(
        monkeypatch, producer):
    """R2-2/R2-3, Connect's one rule (`runner.paired_video`): the named path gone, a file of that name and size in
    Connect's index is the video only when its content key is the pairing's — another episode re-released under the
    same name never opens. A second file of the name at another size makes the size the only thing that tells them
    apart; with no index lookup the moved video is never found."""
    rel, _copies = _copy(_name(9, ".ja.srt"))
    named = _elsewhere("hato", "old", _name(9, ".mkv"))                  # where it was paired; moved since
    os.makedirs(os.path.dirname(named))                                  # (its folder still there)
    moved = _video(_elsewhere("Videos", SHOW, _name(9, ".mkv")))
    other = _video(_elsewhere("Videos", "Re-release", _name(9, ".mkv")))
    with open(other, "ab") as f:
        f.write(b" another episode, a few bytes longer")
    videos.Index("ja").refresh([], [_elsewhere("Videos")])              # Connect's own refresh, saved
    key = "video_key" if producer == "source" else "content_key"
    record = {"producer": producer, "video_path": named, "video_size": os.path.getsize(moved),
              key: videos.content_key(moved)}
    monkeypatch.setattr(play, "pairing", lambda language, item_id: record)
    assert play.to_open("ja", 1, rel, "anime") == (moved, None)
    record[key] = videos.content_key(other)                              # its bytes are another episode's
    assert play.to_open("ja", 1, rel, "anime") == (None, "no video beside it on disk")


def test_a_cloud_placeholder_is_never_opened(monkeypatch):
    """As Connect refuses one (`runner._on_disk`): opening it would download the whole file."""
    from app.connect import runner
    rel, copies = _copy(_name(9, ".ja.srt"))
    cloud = _video(os.path.join(copies, _name(9, ".mkv")))
    monkeypatch.setattr(runner, "_on_disk", lambda path: os.path.normcase(path) != os.path.normcase(cloud))
    assert play.to_open("ja", 1, rel, "anime") == (None, "no video beside it on disk")
    monkeypatch.setattr(play, "pairing", lambda language, item_id: {"producer": "hato", "video_path": cloud})
    assert play.to_open("ja", 1, rel, "anime") == (None, "no video beside it on disk")     # named, still never


def test_a_video_only_connects_index_knows_is_found_there_as_connect_last_listed_it(monkeypatch):
    rel, _copies = _copy(_name(9, ".ja.srt"))
    far = _video(_elsewhere("Videos", SHOW, _name(9, ".mp4")))
    index = videos.Index("ja")
    index.refresh([], [_elsewhere("Videos")])                           # Connect's own refresh, saved
    listed = []
    monkeypatch.setattr(videos, "_list", lambda *a, **k: listed.append(a) or None)   # ▶ never lists for the index
    assert play.to_open("ja", 1, rel, "anime") == (far, None)
    assert listed == []


# --- no record, an unreadable store, an offline share ---------------------------------------------------------- #
@pytest.mark.parametrize("answer", ["raises", "empty"])
def test_with_no_record_the_video_beside_the_copy_still_opens(monkeypatch, answer):
    rel, copies = _copy(_name(10, ".ja.srt"))
    video = _video(os.path.join(copies, _name(10, ".mkv")))
    if answer == "raises":
        def broken(*a, **k):
            raise OSError("the store's disk went away")
        monkeypatch.setattr(ls, "check_mode", lambda *a, **k: ("store", "ready"))
        monkeypatch.setattr(ls, "open_store", broken)
    else:
        monkeypatch.setattr(play, "pairing", lambda language, item_id: {})
    assert play.to_open("ja", 1, rel, "anime") == (video, None)


def test_an_unreadable_store_says_so_and_a_2x_library_says_no_video(monkeypatch):
    rel, _copies = _copy(_name(11, ".ja.srt"))
    monkeypatch.setattr(ls, "open_store", lambda *a, **k: None)
    monkeypatch.setattr(ls, "check_mode", lambda *a, **k: ("read-only", "busy"))
    assert play.to_open("ja", 1, rel, "anime") == (None, "the library can't be read just now")
    monkeypatch.setattr(ls, "check_mode", lambda *a, **k: ("json", "no store"))
    assert play.to_open("ja", 1, rel, "anime") == (None, "no video beside it on disk")


def test_the_store_is_probed_once_and_one_not_ready_after_it_is_never_called_a_2x_library(monkeypatch):
    """R2-5: the store probed as ready, then not ready at the open (made read-only meanwhile) is "can't be read just
    now" — a second probe could answer anything by then, and "no video" would be said of a video that is there."""
    rel, _copies = _copy(_name(11, ".ja.srt"))
    probes = []
    monkeypatch.setattr(ls, "check_mode", lambda *a, **k: probes.append(a) or ("store", "ready"))
    monkeypatch.setattr(ls, "open_store", lambda *a, **k: None)
    assert play.to_open("ja", 1, rel, "anime") == (None, "the library can't be read just now")
    assert len(probes) == 1


def test_each_folder_is_listed_once_and_an_offline_share_is_said_at_once(monkeypatch):
    rel, copies = _copy(_name(9, ".ja.srt"))
    share = os.path.join(os.environ["SURASURA_TEST_ROOT"], "N", "Media", "Shows", SHOW)
    origin = os.path.join(share, _name(9, ".ja.srt"))
    monkeypatch.setattr(play, "pairing", lambda language, item_id: {"producer": "source", "origin": origin})
    listed, real = [], os.listdir
    stats = []
    real_exists = os.path.exists

    def offline(folder):
        listed.append(folder)
        if folder == share:
            raise OSError(64, "The specified network name is no longer available")
        return real(folder)
    monkeypatch.setattr(os, "listdir", offline)              # `runner.beside`'s one listing of a folder
    monkeypatch.setattr(os.path, "exists", lambda p: stats.append(p) or real_exists(p))
    assert play.to_open("ja", 1, rel, "anime") == (None, "its folder can't be reached just now")
    assert listed == [copies, share]                         # one listing each, never a stat per name and extension
    assert not [p for p in stats if os.path.dirname(p) in (copies, share)]
    video = _video(os.path.join(share, _name(9, ".mkv")))     # back online
    monkeypatch.setattr(os, "listdir", real)
    assert play.to_open("ja", 1, rel, "anime") == (video, None)


def test_a_book_on_an_offline_share_is_said_never_swapped_for_its_text_copy(monkeypatch):
    """R2-6: the book's folder gone (a share offline) says so rather than opening the part's text copy unsaid; the
    folder there and the book alone gone (deleted, renamed) still opens the copy, the text it was read from."""
    rel, _copies = _copy("星の歌 - 2.txt")
    share = os.path.join(os.environ["SURASURA_TEST_ROOT"], "N", "Media", "Books")
    origin = os.path.join(share, "星の歌.epub") + "#2"
    monkeypatch.setattr(play, "pairing", lambda language, item_id: {"producer": "source", "origin": origin})
    assert play.to_open("ja", 1, rel, "book") == (None, "its folder can't be reached just now")
    os.makedirs(share)                                        # back online, the book no longer in it
    assert play.to_open("ja", 1, rel, "book") == (os.path.join(path_utils.get_data_path("ja"), *rel.split("/")), None)


def test_no_content_path_is_never_the_data_folder():
    """AD-5: an episode with no file of its own never opens the data folder (Explorer on it)."""
    os.makedirs(path_utils.get_data_path("ja"), exist_ok=True)
    assert play.to_open("ja", 1, None, "text") == (None, "it isn't on disk")
    assert play.to_open("ja", 1, "", "anime") == (None, "no video beside it on disk")


def test_the_store_record_read_is_closed_and_never_written():
    """▶'s read opens a reader's handle on the worker and closes it: the store's file is unchanged after."""
    folder = _elsewhere("Downloads", SHOW)
    sub = _subtitle(os.path.join(folder, _name(9, ".ja.srt")), 9)
    items = _read_in_place(folder)
    db = ls.library_db_path("ja", path_utils.get_data_path("ja"))
    before = (os.path.getsize(db), os.path.getmtime(db))
    record = play.pairing("ja", items[os.path.abspath(sub)][0])
    assert record["producer"] == "source" and record["origin"] == os.path.abspath(sub)
    assert "sha256" not in record                             # read as Connect reads it (`pairing_of`)
    assert (os.path.getsize(db), os.path.getmtime(db)) == before
    json.dumps(record)
