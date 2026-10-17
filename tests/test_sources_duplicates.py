"""3.0's Sources, never a duplicate (SRC K3, SRC-7): an episode a source folder brought in and the same episode handed
over by hato are one item, whichever came first — hato's hand-off of a video a source item already holds (or of the
same bytes as one) makes no item: its file is kept out by a `duplicate` exclusion (the disk sync and read-only mode
never add it), hato's record goes on the existing item (its video-keyed row wins for Connect, B1), and its file stays
where hato wrote it.

Why these matter: two items for one episode split its sentences, mine its cards twice and show it twice in Current; a
file deleted from hato's folder is hato's to keep or delete, never Surasura's. A library with no source folders must
register hato's files exactly as before. Every test runs for Japanese and Chinese with real subtitles from
tests/Test Resources/, made-up show names and a few bytes as a fake video, under the per-test SURASURA_TEST_ROOT.
"""
import json
import os
import shutil

import pytest

from app import library_store as ls
from app import sources
from app.connect import library as connect_library
from app.connect import videos
from tests.test_library_store_support import LANGUAGES, migrated, roots
from tests.test_sources_scan import _SHOWS, _drive, _empty, _items, _look, _text, _video, _write


@pytest.fixture(autouse=True)
def _fresh_module_state():
    """Each test starts as a new run of the app: no look made yet this run, no scan running."""
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


def _hato(key, title, episode=1):
    return {"schema": 1, "content_key": key, "producer": "hato", "video_path": f"D:/Shows/{title} - {episode:02d}.mkv",
            "video_size": 1473922811, "show": {"title": title, "season": 1, "episode": episode}}


def _hato_file(data_dir, name, text=None, like=None):
    """The subtitle hato writes into its drop folder: its own text, or the bytes of `like`."""
    path = os.path.join(data_dir, *ls.HATO_FOLDER.split("/"), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if like is not None:
        shutil.copyfile(like, path)
    else:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return path


def _duplicates(store):
    return [(r[0], r[1]) for r in store.conn.execute(
        "SELECT root_id, pattern FROM exclusions WHERE kind = 'duplicate' ORDER BY id")]


def _source_episode(store, language, data_dir, video=True):
    """A source folder with one episode (its subtitle, and a fake video beside it), taken in by setup's first look ->
    (item id, the video's key or None, the source's subtitle path)."""
    show = _SHOWS[language][0]
    src = _drive("driveA")
    sub = _write(os.path.join(src, show, f"{show} - 01.srt"), _text(language, 1))
    key = None
    if video:
        key = videos.content_key(_video(os.path.join(src, show, f"{show} - 01.mkv")))
    root = store.add_source(src)
    ids = _look(store, language, root, first=True)["ids"]
    assert len(ids) == 1
    return ids[0], key, sub


# --- hato after a source (K3 (1)) ------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_hato_after_a_source_with_the_same_video_makes_no_item_and_its_record_goes_on_the_source_item(language):
    """The video's key is the episode: hato's own subtitle (other bytes) of a video a source item holds is that item.
    The change is that item's; hato's file stays where hato wrote it, kept out of the disk sync by its exclusion."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, key, _sub = _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7))
        change = store.register(hato_path, _hato(key, show))
        assert change.added == [] and change.pairing_item == item
        assert _items(store) == 1
        rel = ls.library_rel(data_dir, hato_path)
        assert _duplicates(store) == [(store._root_id(), ls.path_key(rel))]
        row = store.conn.execute("SELECT item_id FROM pairings WHERE content_key = ?", (key,)).fetchone()
        assert row[0] == item
        assert connect_library.pairing_of(store, item)["content_key"] == key         # hato's row wins (B1)
        assert os.path.isfile(hato_path)                                              # never deleted
        assert store.sync_disk() is None and _items(store) == 1                       # the sync keeps it out
        assert store.item_id(rel) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_hato_after_a_source_with_the_same_bytes_makes_no_item(language):
    """No video beside the source's subtitle: the same bytes (size first, then sha256) are the episode."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, _key, sub = _source_episode(store, language, data_dir, video=False)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", like=sub)
        change = store.register(hato_path, _hato("v1-k3-bytes", show))
        assert change.added == [] and change.pairing_item == item and _items(store) == 1
        assert _duplicates(store) == [(store._root_id(), ls.path_key(ls.library_rel(data_dir, hato_path)))]
        assert connect_library.pairing_of(store, item)["content_key"] == "v1-k3-bytes"
        # the same size, one character changed: not the same bytes — a new item (the sha256 decides, never the size)
        with open(sub, encoding="utf-8") as f:
            text = f.read()
        flipped = text[:-2] + ("8" if text[-2] != "8" else "9") + text[-1:]
        near = _hato_file(data_dir, f"{show} - 01 alt.srt", flipped)
        assert os.path.getsize(near) == os.path.getsize(sub)
        assert len(store.register(near, _hato("v1-k3-near", show)).added) == 1
        store.remove([_i for _i, e, _a in store.ordered("arrivals") if e["physical_path"].endswith("alt.srt")])
        # other bytes and another video: a new episode, a new item as before
        other = _hato_file(data_dir, f"{show} - 02.srt", _text(language, 2))
        assert store.register(other, _hato("v1-k3-other", show, 2)).added
        assert _items(store) == 2 and len(_duplicates(store)) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_hato_handing_over_the_same_duplicate_again_writes_one_exclusion_and_answers_with_the_item(language):
    """hato retries (a busy store, a second run): idempotent — one exclusion row, the same item, nothing added; the
    command line's answer names the existing item ("already")."""
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    show = _SHOWS[language][0]
    with store:
        item, key, _sub = _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 7))
        store.register(hato_path, _hato(key, show))
        versions = store.versions()
        again = store.register(hato_path, _hato(key, show))
        assert again is not None and again.pairing_item == item and again.added == []
        assert store.versions() == versions                                           # nothing written
        assert len(_duplicates(store)) == 1 and _items(store) == 1
        assert store.undo(again).notes                                           # nothing it wrote: nothing undone
        assert connect_library.pairing_of(store, item)["content_key"] == key and len(_duplicates(store)) == 1
    answer = ls.register_headless(language, hato_path, _hato(key, show), data_dir=data_dir,
                                  user_files_dir=user_files_dir)
    assert answer.code == ls.EXIT_DONE and answer.file_id == item and answer.landed == "already"
    assert answer.pairing == "same"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_source_item_no_longer_holds_its_episode_for_hato(language):
    """Only a live item is a duplicate's twin: after Remove, hato's hand-off is an item of its own as before."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, key, sub = _source_episode(store, language, data_dir)
        store.remove([item])
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", like=sub)
        change = store.register(hato_path, _hato(key, show))
        assert len(change.added) == 1 and _duplicates(store) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_with_no_sources_registers_hatos_files_as_before(language):
    """No source folder: the same bytes as a 2.x item, or a video hato already paired on another of its own items,
    still make an item each as before (K3 is about a source's episodes only)."""
    store = migrated(language)
    data_dir, _u = roots(language)
    with store:
        first = store.ordered("now")[0][1]["physical_path"]
        twin = _hato_file(data_dir, "twin.srt", like=os.path.join(data_dir, *first.split("/")))
        assert len(store.register(twin, _hato("v1-k3-twin", "Twin")).added) == 1
        again = _hato_file(data_dir, "twin again.srt", _text(language, 5))
        assert len(store.register(again, _hato("v1-k3-twin", "Twin")).added) == 1    # the key moves, as before
        assert _duplicates(store) == []


# --- a source after hato: the scan's check (a) ------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_source_after_hato_attaches_its_origin_to_hatos_item_and_copies_nothing(language):
    """hato paired the video first: the source's subtitle beside that video is hato's episode (check (a)) — its origin
    recorded on hato's item, no copy in `Library`, one item."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    key = videos.content_key(_video(os.path.join(src, show, f"{show} - 01.mkv")))
    _write(os.path.join(src, show, f"{show} - 01.srt"), _text(language, 1))
    with store:
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 7))
        hato_item = store.register(hato_path, _hato(key, show)).added[0]
        result = _look(store, language, store.add_source(src), first=True)
        assert result["added"] == 0 and result["attached"] == 1 and _items(store) == 1
        assert not os.path.exists(os.path.join(data_dir, ls.CONTENT_FOLDER))
        origin = next(iter(store.origins().values()))
        assert origin.item_id == hato_item and _duplicates(store) == []
        assert connect_library.pairing_of(store, hato_item)["content_key"] == key


# --- read-only mode honours the duplicates (K1a's N9) ----------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_read_only_schedule_never_lists_a_file_kept_out_as_a_duplicate(language):
    """New arrivals off (with it on, read-only mode never analyses hato's folder at all): an untracked drop is listed
    at the top of NOW as the store would place it, but never the duplicate's file."""
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    show = _SHOWS[language][0]
    with store:
        store.set_library_options(arrivals_on=False)
        _item, key, _sub = _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 7))
        store.register(hato_path, _hato(key, show))
        loose = _hato_file(data_dir, "unpaired.srt", _text(language, 3))           # never handed over: listed
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    with open(ls.manifest_path(user_files_dir), encoding="utf-8") as f:
        assert json.load(f)["surasura_library"]["tables"]["exclusions"]["rows"]
    schedule = ls.read_only_schedule(language, data_dir, user_files_dir)
    listed = [e["physical_path"] for rows in schedule.values() if isinstance(rows, list) for e in rows]
    assert ls.library_rel(data_dir, hato_path) not in listed
    assert ls.library_rel(data_dir, loose) in listed
