"""A skipped folder is skipped for hato too (Kura-NA, a Send report of 2026-11-18: a folder skipped in Surasura kept
its rows in New arrivals, and hato kept finding subtitles for it and handing them over).

hato finds a video in a folder Surasura also reads, writes its subtitle beside the video and hands a copy over
(`register`, its record naming the video's path). Three rules, one list — the store's skipped folders:
  * **the skip takes what hato brought from there** — an item hato's record ties to a video under the folder (hato's
    own item, or a source item hato took over) leaves with the folder's others, one command, one Undo; an item with
    anything outside the folder stays;
  * **the hand-over of a skipped folder's video is refused** (`landed` "skipped": no item, no record, the drop file
    left where hato wrote it), also for a back-fill; once read again, it is taken as before;
  * **hato is told the list** (`tools_entry.entry`'s `skipped_folders`, per language), so it never fetches for them.

What a wrong answer costs a learner: a skipped folder's episodes still in New arrivals, coming back with every hato pass,
or a skip that throws away an episode that also lives elsewhere. Every test runs for Japanese and Chinese with real
subtitles from tests/Test Resources/, made-up show names and a few bytes as a fake video, under SURASURA_TEST_ROOT.
"""
import json
import os

import pytest

from app import library_store as ls
from app import sources
from app.connect import videos
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _SHOWS, _drive, _empty, _look, _text, _video, _write


@pytest.fixture(autouse=True)
def _fresh_module_state():
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


def _hato_drop(data_dir, language, video, episode):
    """hato's hand-over of `video`'s subtitle: the copy in its drop folder and its record (the video where hato found
    it) -> (path, record)."""
    show = _SHOWS[language][1]
    name = os.path.splitext(os.path.basename(video))[0] + ".srt"
    path = _write(os.path.join(data_dir, *ls.HATO_FOLDER.split("/"), show, name), _text(language, 40 + episode), age=0)
    record = {"schema": 1, "content_key": videos.content_key(video), "producer": "hato",
              "video_path": os.path.abspath(video), "video_size": os.path.getsize(video),
              "show": {"title": show, "season": 1, "episode": episode}}
    return path, record


def _downloads(language):
    """A downloads folder read as a source, with a `Downloading` folder inside it holding one video -> (src, inside,
    video)."""
    src = _drive("Downloads")
    inside = os.path.join(src, "Downloading")
    show = _SHOWS[language][1]
    video = _video(os.path.join(inside, f"{show} - 03.mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska 3 ")
    return src, inside, video


def _ids(store):
    return [r[0] for r in store.conn.execute("SELECT id FROM items ORDER BY id")]


@pytest.mark.parametrize("language", LANGUAGES)
def test_skipping_a_folder_takes_hatos_item_of_a_video_there_and_undo_brings_it_back(language):
    """hato's own item (no origin: its record names a video under the folder) leaves with the skip; Undo puts it back."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        path, record = _hato_drop(data_dir, language, video, 3)
        item = store.register(path, record).added[0]
        assert store.items_under(inside) == [item]
        change = store.skip_folder(inside)
        assert store.item(item) is None and len(change.trash_ids) == 1
        store.undo(change)
        assert store.item(item) is not None


@pytest.mark.parametrize("language", LANGUAGES)
def test_skipping_a_folder_takes_a_source_item_hato_took_over(language):
    """The look found the episode first (its origin under the folder), then hato handed its own subtitle over (R2:
    the item now reads hato's file and carries hato's record): one item, and the skip takes it."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    _write(os.path.join(inside, os.path.splitext(os.path.basename(video))[0] + ".srt"), _text(language, 3))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        (item,) = _ids(store)
        path, record = _hato_drop(data_dir, language, video, 3)
        assert store.register(path, record).pairing_item == item and _ids(store) == [item]
        store.skip_folder(inside)
        assert _ids(store) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_hato_ties_to_a_video_elsewhere_stays(language):
    """hato's record names a video outside the skipped folder: the item stays (only what lies there leaves)."""
    store, data_dir = _empty(language)
    src, inside, _video_in = _downloads(language)
    outside = _video(os.path.join(src, f"{_SHOWS[language][1]} - 04.mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska 4 ")
    with store:
        store.add_source(src)
        path, record = _hato_drop(data_dir, language, outside, 4)
        item = store.register(path, record).added[0]
        assert store.items_under(inside) == []
        store.skip_folder(inside)
        assert store.item(item) is not None


@pytest.mark.parametrize("language", LANGUAGES)
def test_hatos_hand_over_of_a_skipped_folders_video_is_refused_and_taken_once_read_again(language):
    """Skipped first: hato's hand-over answers `skipped` — no item, no record, hato's file left where it is. Read again
    (Settings), the same hand-over is taken."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        store.skip_folder(inside)
        (folder,) = [f["id"] for f in store.skipped_folders()]
    path, record = _hato_drop(data_dir, language, video, 3)
    done = ls.register_headless(language, path, record, data_dir=data_dir,
                                user_files_dir=store.user_files_dir, looks=0)
    assert done.code == ls.EXIT_DONE and done.landed == "skipped" and done.file_id is None
    assert os.path.isfile(path)                                                   # hato's file: never Surasura's
    with ls.open_store(language, data_dir, store.user_files_dir) as again:
        assert _ids(again) == [] and again.conn.execute("SELECT COUNT(*) FROM pairings").fetchone()[0] == 0
        again.read_folder_again(folder)
    done = ls.register_headless(language, path, record, data_dir=data_dir,
                                user_files_dir=store.user_files_dir, looks=0)
    assert done.code == ls.EXIT_DONE and done.landed == "arrivals" and done.file_id is not None


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_skipped_folders_hold_by_the_videos_path_however_it_is_spelled(language):
    """`skipped_holding` reads the record's video (and the subtitle hato wrote beside it) by the one path key: another
    case, a trailing separator — the same folder; a folder beside it with a longer name is not inside it."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        store.skip_folder(inside + os.sep)
        assert store.skipped_holding([video.upper()]) == ls.folder_path(inside)
        assert store.skipped_holding([None, os.path.join(src, "Downloading 2", "x.mkv")]) is None
        assert store.skipped_holding([]) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_hato_arrival_offers_the_folder_of_its_video_to_skip(language):
    """New arrivals' ⋯ *Never read this folder* on hato's row (no origin of its own): the folders of the video its record
    names, deepest first, up to (never) the source — the same choices a row the look found offers."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        path, record = _hato_drop(data_dir, language, video, 3)
        item = store.register(path, record).added[0]
        assert store.skip_choices([item]) == [ls.folder_path(inside)]
        outside, rec2 = _hato_drop(data_dir, language, _video(os.path.join(_drive("Elsewhere"), "x - 05.mkv")), 5)
        other = store.register(outside, rec2).added[0]
        assert store.skip_choices([other]) == []                                 # a video in no folder being read
