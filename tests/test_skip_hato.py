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
def test_a_found_episode_whose_hato_record_names_a_video_elsewhere_stays(language):
    """The look found the episode under the folder (its origin there), and hato handed over the same bytes naming a
    video in ANOTHER folder (its record goes on that item, SRC-7): part of it lies elsewhere, so the skip keeps it."""
    import shutil
    store, data_dir = _empty(language)
    src = _drive("Downloads")
    inside = os.path.join(src, "Downloading")
    sub = _write(os.path.join(inside, "%s - 05.srt" % _SHOWS[language][1]), _text(language, 5))
    outside = _video(os.path.join(_drive("Elsewhere"), "%s - 05.mkv" % _SHOWS[language][1]),
                     body=b"\x1a\x45\xdf\xa3 fake matroska 5 ")
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        (item,) = _ids(store)
        path, record = _hato_drop(data_dir, language, outside, 5)
        shutil.copyfile(sub, path)                                                # the same bytes as the found copy
        assert store.register(path, record).pairing_item == item and _ids(store) == [item]
        assert store.items_under(inside) == []
        store.skip_folder(inside)
        assert store.item(item) is not None


@pytest.mark.parametrize("language", LANGUAGES)
def test_hatos_hand_over_of_a_skipped_folders_video_is_refused_and_taken_once_read_again(language):
    """Skipped first: hato's hand-over answers `skipped` — no item, no record, hato's file left where it is. Read again
    (Settings) lets it in with the record it was refused with (train 43's keeper), so hato's same hand-over later is
    `already` that item."""
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
    assert done.code == ls.EXIT_DONE and done.landed == "already" and done.file_id is not None
    assert done.pairing == "same"                                                 # (Read again wrote that record)


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


# --- train 43's intent keeper (Kura-NA round 2) ------------------------------------------------------------------- #

def _pairing_of(store, item):
    row = store.conn.execute("SELECT pairing FROM pairings WHERE item_id = ? AND content_key NOT LIKE 'src:%'",
                             (item,)).fetchone()
    return json.loads(row[0]) if row else None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_refused_hand_over_never_comes_in_by_the_disk_sync_and_read_again_brings_it_with_its_video(language):
    """The refusal leaves hato's file where hato wrote it (never Surasura's to delete) — and the next disk sync never
    takes it in as an arrival with no record (it could never be mined, and hato never hands a skipped one over again).
    *Read again* brings it in WITH hato's record: its video link kept."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        store.skip_folder(inside)
        (folder,) = [f["id"] for f in store.skipped_folders()]
    path, record = _hato_drop(data_dir, language, video, 3)
    done = ls.register_headless(language, path, record, data_dir=data_dir, user_files_dir=store.user_files_dir,
                                looks=0)
    assert done.landed == "skipped" and os.path.isfile(path)
    with ls.open_store(language, data_dir, store.user_files_dir) as again:
        again.sync_disk()
        assert _ids(again) == []                                                  # kept out, as a Remove keeps out
        assert again.read_folder_again(folder)
        (item,) = _ids(again)
        assert again.item(item)["rel_path"] == ls.library_rel(data_dir, path)
        assert _pairing_of(again, item)["video_path"] == record["video_path"]   # hato's record: the video link
        again.sync_disk()
        assert _ids(again) == [item]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_drop_the_sync_took_in_before_its_refused_hand_over_leaves_new_arrivals(language):
    """The disk sync may meet hato's file a moment before its hand-over (R1): refused, that row goes too — no arrival
    with no record is left behind."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        store.skip_folder(inside)
        path, record = _hato_drop(data_dir, language, video, 3)
        store.sync_disk()
        assert len(_ids(store)) == 1                                              # (the sync met it first)
    done = ls.register_headless(language, path, record, data_dir=data_dir, user_files_dir=store.user_files_dir,
                                looks=0)
    assert done.landed == "skipped"
    with ls.open_store(language, data_dir, store.user_files_dir) as again:
        assert _ids(again) == []
        again.sync_disk()
        assert _ids(again) == []
        assert os.path.isfile(path)


@pytest.mark.parametrize("language", LANGUAGES)
def test_ignore_never_offers_a_folder_whose_skip_would_take_another_titles_hato_episode(language):
    """The sort screen's *Ignore* (`skip_choices(own=True)`) offers only a folder holding nothing but the title's own:
    a folder that also holds the video of another title's hato episode is never offered (its skip would take it)."""
    store, data_dir = _empty(language)
    src = _drive("Downloads")
    inside = os.path.join(src, "Seasonal")
    _write(os.path.join(inside, "%s - 01.srt" % _SHOWS[language][0]), _text(language, 1))
    video_b = _video(os.path.join(inside, "%s - 03.mkv" % _SHOWS[language][1]), body=b"fake matroska b3")
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        (item_a,) = _ids(store)
        path, record = _hato_drop(data_dir, language, video_b, 3)
        item_b = store.register(path, record).added[0]
        assert sorted(store.items_under(inside)) == sorted([item_a, item_b])
        assert ls.folder_path(inside) not in [ls.folder_path(f) for f in store.skip_choices([item_a], own=True)]
        assert ls.folder_path(inside) in [ls.folder_path(f) for f in store.skip_choices([item_a, item_b], own=True)]



@pytest.mark.parametrize("language", LANGUAGES)
def test_the_skips_undo_lets_a_refused_hand_over_in_with_its_video(language):
    """The skip undone (its toast's Undo or Ctrl+Z) reads the folder again: hato's file refused meanwhile comes in with
    the record it was refused with, inside the undo's own command."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        change = store.skip_folder(inside)
    path, record = _hato_drop(data_dir, language, video, 3)
    assert ls.register_headless(language, path, record, data_dir=data_dir, user_files_dir=store.user_files_dir,
                                looks=0).landed == "skipped"
    with ls.open_store(language, data_dir, store.user_files_dir) as again:
        again.undo(change)
        (item,) = _ids(again)
        assert _pairing_of(again, item)["video_path"] == record["video_path"]
        assert again.conn.execute("SELECT COUNT(*) FROM exclusions WHERE kind = ?", (ls.DROP_SKIPPED,)).fetchone()[0] == 0


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("arrivals", [1, 0])
def test_reset_never_takes_in_a_refused_hand_overs_file(language, arrivals):
    """Reset (`reset_order`: untracked files join as new) keeps a refused hand-over's file out as the disk sync does —
    also with New arrivals off (2.x's library, where Reset adds hato's files to NOW)."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        store.skip_folder(inside)
    path, record = _hato_drop(data_dir, language, video, 3)
    assert ls.register_headless(language, path, record, data_dir=data_dir, user_files_dir=store.user_files_dir,
                                looks=0).landed == "skipped"
    with ls.open_store(language, data_dir, store.user_files_dir) as again:
        again.bookkeeping({"arrivals_on": arrivals}, copy_carries=True)
        again.reset_order()
        assert _ids(again) == []
        again.sync_disk()
        assert _ids(again) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_kept_out_file_that_cant_be_registered_now_stays_kept_out_and_comes_in_at_the_next_try(language,
                                                                                                monkeypatch):
    """*Read again* lets the kept-out file in by its own write, after the folder's: one that fails then (a locked
    store, a conflict) stays kept out — never an arrival with no record — and comes in at the next call."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        store.skip_folder(inside)
        (folder,) = [f["id"] for f in store.skipped_folders()]
    path, record = _hato_drop(data_dir, language, video, 3)
    assert ls.register_headless(language, path, record, data_dir=data_dir, user_files_dir=store.user_files_dir,
                                looks=0).landed == "skipped"
    with ls.open_store(language, data_dir, store.user_files_dir) as again:
        real = again.register

        def broke(*_a, **_k):
            raise ls.StoreConflict("busy a moment")
        monkeypatch.setattr(again, "register", broke)
        assert again.read_folder_again(folder)
        again.sync_disk()
        assert _ids(again) == []                                                  # still kept out
        monkeypatch.setattr(again, "register", real)
        assert again.let_drops_back() == 1
        (item,) = _ids(again)
        assert _pairing_of(again, item)["video_path"] == record["video_path"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_newer_refused_record_replaces_the_one_kept_and_a_folder_read_again_meanwhile_takes_the_hand_over(language):
    """hato refused twice for one file: Read again brings it in by the NEWER record. And a hand-over whose folder was
    read again between Surasura's two looks at it is taken as any (never kept out by a skip that's gone)."""
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    with store:
        store.add_source(src)
        store.skip_folder(inside)
        (folder,) = [f["id"] for f in store.skipped_folders()]
    path, record = _hato_drop(data_dir, language, video, 3)
    newer = dict(record, show=dict(record["show"], title=record["show"]["title"] + " (new)"))
    for rec in (record, newer):
        assert ls.register_headless(language, path, rec, data_dir=data_dir, user_files_dir=store.user_files_dir,
                                    looks=0).landed == "skipped"
    with ls.open_store(language, data_dir, store.user_files_dir) as again:
        assert _ids(again) == []                                                  # still skipped: nothing came in
        assert again.let_drops_back() == 0
        assert _ids(again) == []
        assert again.keep_drop_out(path, newer, folder + 999) is False          # (a skip that isn't there)
        again.read_folder_again(folder)
        (item,) = _ids(again)
        assert _pairing_of(again, item)["show"]["title"] == newer["show"]["title"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_window_writers_undo_of_a_skip_lets_a_refused_hand_over_in_with_its_video(language):
    """The window's Undo goes through its writer, whose own write holds `Store.undo` (nested: the store's call waits):
    the writer lets the kept-out file in after it — the episode comes in with hato's record, no hato call needed."""
    import time
    from tests import services_helpers as h
    from tests.test_sources_skip import _writer
    store, data_dir = _empty(language)
    src, inside, video = _downloads(language)
    store.add_source(src)
    w, heard = _writer(language)
    try:
        w.skip_folder(inside, label="skipped")
        assert h.until(lambda: heard.saved)
        path, record = _hato_drop(data_dir, language, video, 3)
        assert ls.register_headless(language, path, record, data_dir=data_dir, user_files_dir=store.user_files_dir,
                                    looks=0).landed == "skipped"
        w.undo()
        assert h.until(lambda: heard.undone)
        assert h.until(lambda: len(_ids(store)) == 1)
        (item,) = _ids(store)
        assert _pairing_of(store, item)["video_path"] == record["video_path"]
    finally:
        w.finish(time.monotonic() + 5)
        store.close()
