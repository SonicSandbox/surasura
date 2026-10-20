"""3.0's Sources, never a duplicate (SRC K3, SRC-7): an episode already in and the same episode handed over by hato are
one item, whichever came first. hato's hand-off of a video a source item holds takes that item over: the item reads
hato's file (the one hato timed), Surasura's `Library` copy goes to the trash and the folder's origin record stays —
the same end as when hato came first (K3 fix R2). hato's hand-off of the same bytes as any live item, or of a video
another item (a drop's, hato's own) holds, makes no item: its file is kept out by a `duplicate` exclusion (the disk
sync, Reset and read-only mode never add it) and hato's record goes on the existing item (SRC-7, every channel). A row the
disk sync made for hato's file a moment before the hand-off is taken out in the same command (R1); a folder's video
waiting for its subtitle takes hato's in place (R3). hato's file is never deleted or moved.

Why these matter: two items for one episode split its sentences, mine its cards twice and show it twice in Current; a
file deleted from hato's folder is hato's to keep or delete, never Surasura's. A library with no source folders must
register hato's files exactly as before. Every test runs for Japanese and Chinese with real subtitles from
tests/Test Resources/, made-up show names and a few bytes as a fake video, under the per-test SURASURA_TEST_ROOT.
"""
import hashlib
import json
import os
import shutil

import pytest

from app import library_store as ls
from app import sources
from app.connect import fit_check
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


def _trashed(data_dir, like):
    """Whether `.trash` holds a file with `like`'s bytes (the trash names it `<base>_<stamp><ext>`)."""
    trash = os.path.join(data_dir, ".trash")
    with open(like, "rb") as f:
        want = f.read()
    for name in os.listdir(trash) if os.path.isdir(trash) else ():
        with open(os.path.join(trash, name), "rb") as f:
            if f.read() == want:
                return True
    return False


def _library_files(data_dir):
    top = os.path.join(data_dir, ls.CONTENT_FOLDER)
    return sorted(os.path.relpath(os.path.join(d, n), top) for d, _s, files in os.walk(top) for n in files)


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
def test_hato_after_a_source_with_the_same_video_takes_the_source_item_over_with_its_own_file(language):
    """The video's key is the episode: hato's own subtitle (other bytes) of a video a source item holds is that item —
    no item added, the change that item's; the item now reads hato's file (R2: hato's is the one Connect's timing
    trusts), Surasura's `Library` copy is in `.trash`, the origin record stays on the item, no exclusion is written
    (hato's file is the item's), and hato's file stays where hato wrote it."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, key, sub = _source_episode(store, language, data_dir)
        copy = store.item(item)["rel_path"]
        hato_path = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7))
        change = store.register(hato_path, _hato(key, show))
        assert change.added == [] and change.pairing_item == item
        assert _items(store) == 1
        rel = ls.library_rel(data_dir, hato_path)
        assert store.item(item)["rel_path"] == rel and store.item(item)["availability"] == "available"
        assert store.item(item)["size"] == os.path.getsize(hato_path)
        assert _duplicates(store) == []
        assert change.unused == [copy] and not os.path.exists(os.path.join(data_dir, *copy.split("/")))
        assert _trashed(data_dir, sub)                                                # the copy, in the trash
        row = store.conn.execute("SELECT item_id FROM pairings WHERE content_key = ?", (key,)).fetchone()
        assert row[0] == item
        assert [o.item_id for o in store.origins().values()] == [item]                # the origin stays
        assert connect_library.pairing_of(store, item)["content_key"] == key         # hato's row wins (B1)
        assert os.path.isfile(hato_path)                                              # never deleted
        assert store.sync_disk() is None and _items(store) == 1                       # the sync adds nothing
        assert store.item_id(rel) == item


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
        item, _key, sub = _source_episode(store, language, data_dir, video=False)
        key = "v1-k3-retry"
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", like=sub)
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
def test_a_library_with_no_sources_never_gets_a_second_item_for_an_episode_already_in(language):
    """No source folder (SRC-7 "never a duplicate", every channel): the same bytes as a 2.x item, or
    a video hato already paired on another of its own items, make no second item either — the file kept out by its
    exclusion, hato's record on the item already holding the episode. Other bytes of another video: a new item."""
    store = migrated(language)
    data_dir, _u = roots(language)
    with store:
        before = _items(store)
        first_id, first_entry = store.ordered("now")[0][:2]
        first = first_entry["physical_path"]
        twin = _hato_file(data_dir, "twin.srt", like=os.path.join(data_dir, *first.split("/")))
        change = store.register(twin, _hato("v1-k3-twin", "Twin"))
        assert change.added == [] and change.pairing_item == first_id and _items(store) == before
        again = _hato_file(data_dir, "twin again.srt", _text(language, 5))
        change = store.register(again, _hato("v1-k3-twin", "Twin"))                 # hato's video, on that item
        assert change.added == [] and change.pairing_item == first_id and _items(store) == before
        assert [p for _r, p in _duplicates(store)] == [ls.path_key(ls.library_rel(data_dir, f)) for f in (twin, again)]
        assert os.path.isfile(twin) and os.path.isfile(again)
        other = _hato_file(data_dir, "other.srt", _text(language, 6))
        assert len(store.register(other, _hato("v1-k3-other", "Other")).added) == 1
        assert store.sync_disk() is None and _items(store) == before + 1


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
        _item, _key, sub = _source_episode(store, language, data_dir, video=False)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", like=sub)
        store.register(hato_path, _hato("v1-k3-ro", show))
        loose = _hato_file(data_dir, "unpaired.srt", _text(language, 3))           # never handed over: listed
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    with open(ls.manifest_path(user_files_dir), encoding="utf-8") as f:
        assert json.load(f)["surasura_library"]["tables"]["exclusions"]["rows"]
    schedule = ls.read_only_schedule(language, data_dir, user_files_dir)
    listed = [e["physical_path"] for rows in schedule.values() if isinstance(rows, list) for e in rows]
    assert ls.library_rel(data_dir, hato_path) not in listed
    assert ls.library_rel(data_dir, loose) in listed


# --- the K3 fix round (reviews/SRC-K3-adversary.md R1-R4, N1, N2) ---------------------------------------------- #

def _timed(record, path):
    """hato's record as hato hands over a subtitle it timed: Connect trusts it only on the file it timed."""
    out = dict(record, verdict="timed", timing={"segments": 1, "reference": "text-track"})
    with open(path, "rb") as f:
        out["subtitle_sha256"] = hashlib.sha256(f.read()).hexdigest()
    return out


def _sync_first(store, data_dir, hato_path):
    """The window's Lookout: hato's file lands, the folder settles, the disk sync adds it as a New arrival before
    hato's own `register` process comes (the normal case while the window is open)."""
    summary = store.sync_disk(folders=[ls.HATO_FOLDER])
    assert summary and len(summary["added"]) == 1
    assert store.item_id(ls.library_rel(data_dir, hato_path)) == summary["added"][0]
    return summary["added"][0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_R1_a_sync_before_hatos_register_still_leaves_one_item_by_video(language):
    """R1 (B): the sync's own row for hato's file (in New arrivals, no pairing) is taken out in the register's command;
    the source item takes hato's file over (R2) — one item, hato's file never deleted or moved."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, key, _sub = _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 7))
        synced = _sync_first(store, data_dir, hato_path)
        assert _items(store) == 2
        change = store.register(hato_path, _hato(key, show))
        assert _items(store) == 1 and store.item(synced) is None
        assert store.conn.execute("SELECT 1 FROM gone WHERE kind = 'item' AND id = ?", (synced,)).fetchone()  # the feed
        assert change.pairing_item == item and change.added == []
        assert store.item(item)["rel_path"] == ls.library_rel(data_dir, hato_path)
        assert os.path.isfile(hato_path) and _duplicates(store) == []
        assert not store.trash_rows()                                     # not a Remove: nothing to Put back
        assert store.sync_disk() is None and _items(store) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_R1_a_sync_before_hatos_register_still_leaves_one_item_by_bytes(language):
    """R1 (B), the same bytes: the sync's row taken out, the `duplicate` exclusion written, hato's record on the twin;
    the next sync keeps the file out."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, _key, sub = _source_episode(store, language, data_dir, video=False)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", like=sub)
        synced = _sync_first(store, data_dir, hato_path)
        change = store.register(hato_path, _hato("v1-k3-race", show))
        assert _items(store) == 1 and store.item(synced) is None and change.pairing_item == item
        assert _duplicates(store) == [(store._root_id(), ls.path_key(ls.library_rel(data_dir, hato_path)))]
        assert connect_library.pairing_of(store, item)["content_key"] == "v1-k3-race"
        assert os.path.isfile(hato_path)
        assert store.sync_disk() is None and _items(store) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_R1_a_synced_row_the_user_touched_is_never_taken_out(language):
    """Only the sync's own row is taken out: one the user moved out of New arrivals is the user's, and a record that
    isn't hato's (Connect's *Link…* of that file) never takes a row out — both kept and paired as before."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        _item, key, _sub = _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 7))
        synced = _sync_first(store, data_dir, hato_path)
        store.move([synced], "now")
        change = store.register(hato_path, _hato(key, show))
        assert store.item(synced) is not None and change.pairing_item == synced and _items(store) == 2
        linked = _hato_file(data_dir, f"{show} - 01 linked.srt", _text(language, 8))
        synced = _sync_first(store, data_dir, linked)
        change = store.register(linked, {"content_key": key, "producer": "surasura"})
        assert store.item(synced) is not None and change.pairing_item == synced and _items(store) == 3


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("hato_first", (False, True))
def test_R2_both_orders_end_alike_one_item_reading_hatos_timed_file(language, hato_first):
    """R2: hato then the folder, or the folder then hato, end the same — one item reading hato's file (so hato's
    `timed` verdict holds for Connect), hato's record and the folder's origin record on it, no copy left in `Library`,
    no exclusion — and a later look (the original changed meanwhile) copies nothing again (S5: an origin on hato's file
    never rewrites it)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    sub = _write(os.path.join(src, show, f"{show} - 01.srt"), _text(language, 1))
    key = videos.content_key(_video(os.path.join(src, show, f"{show} - 01.mkv")))
    hato_path = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7))
    record = _timed(_hato(key, show), hato_path)
    with store:
        if hato_first:
            store.register(hato_path, record)
            root = store.add_source(src)
            _look(store, language, root, first=True)
        else:
            root = store.add_source(src)
            _look(store, language, root, first=True)
            store.register(hato_path, record)
        rows = store.conn.execute("SELECT id, rel_path, availability FROM items").fetchall()
        assert len(rows) == 1
        item, rel, availability = rows[0]
        assert rel == ls.library_rel(data_dir, hato_path) and availability == "available"
        assert fit_check.hato_timed(connect_library.pairing_of(store, item), os.path.join(data_dir, *rel.split("/")))
        keys = sorted(k if not k.startswith(ls.SOURCE_KEY) else ls.SOURCE_KEY for (k,) in store.conn.execute(
            "SELECT content_key FROM pairings WHERE item_id = ?", (item,)))
        assert keys == sorted([key, ls.SOURCE_KEY])
        assert _library_files(data_dir) == [] and _duplicates(store) == []
        assert _trashed(data_dir, sub) is (not hato_first)                 # source first: its copy went to the trash
        _write(sub, _text(language, 1, extra=" v2"))
        sources._LOOKED.clear()
        _look(store, language, root)
        assert _items(store) == 1 and _library_files(data_dir) == []
        assert store.item(item)["rel_path"] == rel


@pytest.mark.parametrize("language", LANGUAGES)
def test_R2_a_missing_source_item_takes_hatos_file_and_is_back(language):
    """N2 with R2: the source item's copy deleted in Explorer (missing) still holds its video; hato's file is that
    episode's text now — the item available again, nothing added, no exclusion."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, key, _sub = _source_episode(store, language, data_dir)
        os.remove(os.path.join(data_dir, *store.item(item)["rel_path"].split("/")))
        store.sync_disk()
        assert store.item(item)["availability"] == "missing"
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 7))
        change = store.register(hato_path, _hato(key, show))
        assert change.added == [] and _items(store) == 1 and _duplicates(store) == []
        assert store.item(item)["availability"] == "available"
        assert store.item(item)["rel_path"] == ls.library_rel(data_dir, hato_path)


@pytest.mark.parametrize("language", LANGUAGES)
def test_R2_a_take_over_is_not_on_undo(language):
    """The episode's text moved to hato's file and the copy went to the trash: an Undo can't put that back, so it is
    refused (as a scan's take-in is), and nothing changes."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, key, _sub = _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 7))
        change = store.register(hato_path, _hato(key, show))
        versions = store.versions()
        with pytest.raises(ls.UndoRefused):
            store.undo(change)
        assert store.versions() == versions and store.item(item)["rel_path"] == ls.library_rel(data_dir, hato_path)


def _waiting_episode(store, language):
    """A source folder holding one video and no subtitle yet: the look leaves it waiting in New arrivals (K5) ->
    (item id, the video's key)."""
    show = _SHOWS[language][1]
    src = _drive("driveW")
    key = videos.content_key(_video(os.path.join(src, show, f"{show} - 03.mkv")))
    _look(store, language, store.add_source(src), first=True)
    rows = store.conn.execute("SELECT id, availability, tier FROM items").fetchall()
    assert [(r[1], r[2]) for r in rows] == [("waiting", "arrivals")]
    return rows[0][0], key, show


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("sync_first", (False, True))
def test_R3_hatos_subtitle_fills_a_waiting_video_in_place(language, sync_first):
    """R3: hato's subtitle for a folder's waiting video is that row's text — the waiting item takes hato's file, its
    id and place kept, `available`, hato's record on it; no second row, no exclusion (also when the sync added hato's
    file first)."""
    store, data_dir = _empty(language)
    with store:
        item, key, show = _waiting_episode(store, language)
        place = store.place_of(item)
        hato_path = _hato_file(data_dir, f"{show} - 03.srt", _text(language, 3))
        if sync_first:
            _sync_first(store, data_dir, hato_path)
        change = store.register(hato_path, _hato(key, show, 3))
        assert _items(store) == 1 and change.pairing_item == item and change.added == []
        row = store.item(item)
        assert row["availability"] == "available" and row["rel_path"] == ls.library_rel(data_dir, hato_path)
        assert store.place_of(item) == place
        assert connect_library.pairing_of(store, item)["content_key"] == key and _duplicates(store) == []
        assert store.sync_disk() is None and _items(store) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_R4_reset_with_new_arrivals_off_never_adds_a_kept_out_file(language):
    """R4: with New arrivals off Reset walks hato's folder too; a file kept out as another item's episode stays out."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        store.set_library_options(arrivals_on=False)
        _item, _key, sub = _source_episode(store, language, data_dir, video=False)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", like=sub)
        store.register(hato_path, _hato("v1-k3-reset", show))
        assert len(_duplicates(store)) == 1
        store.reset_order()
        assert _items(store) == 1 and store.item_id(ls.library_rel(data_dir, hato_path)) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_N1_undo_of_a_duplicate_hand_off_takes_its_exclusion_back_too(language):
    """N1: an Undo of the hand-off that put hato's record on the twin deletes the record and the exclusion it wrote,
    so hato's file is never left neither an item nor anyone's record: the next sync takes it in."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        _item, _key, sub = _source_episode(store, language, data_dir, video=False)
        hato_path = _hato_file(data_dir, f"{show} - 01.srt", like=sub)
        change = store.register(hato_path, _hato("v1-k3-undo", show))
        store.undo(change)
        assert _duplicates(store) == []
        assert store.conn.execute("SELECT 1 FROM pairings WHERE content_key = 'v1-k3-undo'").fetchone() is None
        assert store.sync_disk() is not None and _items(store) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_R2_a_second_hato_file_for_a_video_taken_over_is_kept_out_and_hatos_first_file_stays(language):
    """After the take-over the item reads hato's file, which is hato's: another subtitle hato hands over for the same
    video is kept out (a `duplicate` exclusion) — the item, its file and hato's first file never moved or trashed."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        item, key, _sub = _source_episode(store, language, data_dir)
        first = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 7))
        store.register(first, _hato(key, show))
        second = _hato_file(data_dir, f"{show} - 01 v2.srt", _text(language, 9))
        change = store.register(second, _hato(key, show))
        assert change.added == [] and getattr(change, "unused", None) is None and _items(store) == 1
        assert store.item(item)["rel_path"] == ls.library_rel(data_dir, first) and os.path.isfile(first)
        assert [p for _r, p in _duplicates(store)] == [ls.path_key(ls.library_rel(data_dir, second))]


@pytest.mark.parametrize("language", LANGUAGES)
def test_R2_a_folder_video_on_an_item_whose_file_is_not_a_library_copy_never_moves_that_file(language):
    """Only a `Library` copy is ever taken over: a folder's origin (with its video) attached by its bytes to hato's own
    item leaves that item's file hato's — hato's later subtitle for the folder's video is kept out, hato's first file
    neither repointed away from nor sent to the trash."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    with store:
        first = _hato_file(data_dir, f"{show} - 01.srt", _text(language, 1))
        item = store.register(first, _hato("v1-k3-unrelated", show)).added[0]
        _write(os.path.join(src, show, f"{show} - 01.srt"), _text(language, 1))      # hato's bytes, beside a video
        key = videos.content_key(_video(os.path.join(src, show, f"{show} - 01.mkv")))
        result = _look(store, language, store.add_source(src), first=True)
        assert result["attached"] == 1 and store.item_of_video_key(key) == item
        second = _hato_file(data_dir, f"{show} - 01 v2.srt", _text(language, 9))
        change = store.register(second, _hato(key, show))
        assert change.added == [] and getattr(change, "unused", None) is None and _items(store) == 1
        assert store.item(item)["rel_path"] == ls.library_rel(data_dir, first) and os.path.isfile(first)
        assert [p for _r, p in _duplicates(store)] == [ls.path_key(ls.library_rel(data_dir, second))]


@pytest.mark.parametrize("language", LANGUAGES)
def test_R1_a_sync_before_hatos_register_of_a_new_episode_keeps_the_syncs_row(language):
    """The everyday race with nothing already in: the sync's row for hato's file is that episode's row — never its own
    twin by its bytes — kept, titled and paired by hato's hand-off, as before K3."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 02.srt", _text(language, 2))
        synced = _sync_first(store, data_dir, hato_path)
        change = store.register(hato_path, _hato("v1-k3-new", show, 2))
        assert store.item(synced) is not None and _items(store) == 2 and _duplicates(store) == []
        assert store.conn.execute("SELECT item_id FROM pairings WHERE content_key = 'v1-k3-new'").fetchone()[0] == synced
        assert change.pairing_item == synced


# --- batch 2 final fix round: the twin found before the write lock (F12) ---------------------------------------- #

class _InLock:
    """What this store does while it holds the write lock: each SQL statement it sends, and each file hashed (whether
    the lock was held then)."""

    def __init__(self, monkeypatch, store):
        self.sql, self.hashed = [], []
        real = ls.sha256_of
        lock = store._wlock
        monkeypatch.setattr(ls, "sha256_of", lambda path: self.hashed.append((lock.depth > 0, path)) or real(path))
        store.conn.set_trace_callback(lambda s: self.sql.append(s) if lock.depth else None)

    def scans(self):
        """The reads of every record's video, every waiting row's records or every item of a size, held in the lock."""
        return [s for s in self.sql if "$.video_key" in s or "CROSS JOIN" in s or "i.size IN" in s]

    def hashed_inside(self):
        return [p for inside, p in self.hashed if inside]


def _same_size(text, n):
    """Real text told apart by a two-digit line: every one the same size, no two the same bytes."""
    return text + f"\n{n:02d}\n"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("kind", ("video", "bytes", "new", "waiting"))
def test_F12_hatos_hand_off_reads_no_record_and_hashes_no_file_while_it_holds_the_write_lock(monkeypatch, language,
                                                                                            kind):
    """F12 (B): `register` looked for the episode inside its command — every record's video read and decoded, every
    waiting row's records, every file of hato's size hashed — 0.1 s of write lock at 20k origins on every hand-off, and
    seconds when sizes repeat (a move refused as busy). Now the twin is found before the lock and only its one item is
    checked again inside: the same answers (a take-over, a kept-out twin, a new item, a gap filled), no scan and no
    hash while the lock is held."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        if kind == "waiting":
            item, key, show = _waiting_episode(store, language)
            path, pairing = _hato_file(data_dir, f"{show} - 03.srt", _text(language, 3)), _hato(key, show, 3)
        else:
            item, key, sub = _source_episode(store, language, data_dir, video=kind == "video")
            with open(sub, encoding="utf-8") as f:
                text = f.read()
            if kind == "video":
                path, pairing = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7)), _hato(key, show)
            elif kind == "bytes":
                path, pairing = _hato_file(data_dir, f"{show} - 01.srt", like=sub), _hato("v1-f12-bytes", show)
            else:                                     # the same size as the source's copy, other bytes: hashed, new
                flipped = text[:-2] + ("8" if text[-2] != "8" else "9") + text[-1:]
                path, pairing = _hato_file(data_dir, f"{show} - 02.srt", flipped), _hato("v1-f12-new", show, 2)
                assert os.path.getsize(path) == os.path.getsize(sub)
        seen = _InLock(monkeypatch, store)
        change = store.register(path, pairing)
        store.conn.set_trace_callback(None)
        if kind == "new":
            assert len(change.added) == 1 and _items(store) == 2
        else:
            assert change.added == [] and change.pairing_item == item and _items(store) == 1
        assert seen.scans() == [] and seen.hashed_inside() == []
        if kind in ("bytes", "new"):
            assert seen.hashed, "its bytes were still checked, before the lock"


@pytest.mark.parametrize("language", LANGUAGES)
def test_F12_a_hand_off_whose_size_many_items_share_is_checked_by_its_video_alone(monkeypatch, language):
    """F12: with many items of hato's size the twin check hashed each of them (2,942 of one size at 20k: 7 s). Up to
    TWIN_HASHES items of that size the bytes still decide; more, and no file is hashed — the hand-off is checked by its
    video alone (the same bytes then make a new item, as before K3; the same video still finds its item)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    base = _text(language, 1)
    many = ls.TWIN_HASHES + 1
    subs = [_write(os.path.join(src, show, f"{show} - {n:02d}.srt"), _same_size(base, n)) for n in range(1, many + 1)]
    key = videos.content_key(_video(os.path.join(src, show, f"{show} - 01.mkv")))
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        assert len(ids) == many and len({os.path.getsize(s) for s in subs}) == 1
        holder = store.item_of_video_key(key)
        seen = _InLock(monkeypatch, store)
        by_bytes = store.register(_hato_file(data_dir, f"{show} - 05.srt", like=subs[4]), _hato("v1-f12-many", show, 5))
        assert len(by_bytes.added) == 1 and seen.hashed == []                 # more than TWIN_HASHES: none hashed
        by_video = store.register(_hato_file(data_dir, f"{show} - 01.ja.srt", _same_size(base, 99)), _hato(key, show))
        assert by_video.added == [] and by_video.pairing_item == holder       # its video still finds its item
        assert seen.hashed == []
        store.conn.set_trace_callback(None)
        second = store.item_id(f"{ls.CONTENT_FOLDER}/{show}/{show} - 02.srt")
        store.remove(by_bytes.added + [i for i in ids if i not in (holder, second)])     # two of the size left
        hato = _hato_file(data_dir, f"{show} - 02.srt", like=subs[1])
        change = store.register(hato, _hato("v1-f12-few", show, 2))
        assert change.added == [] and change.pairing_item == second           # few enough: the bytes decide
        assert seen.hashed and seen.hashed_inside() == []


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("kind", ("video", "bytes"))
def test_F12_a_twin_removed_between_the_check_and_the_command_is_never_the_hand_offs_item(monkeypatch, language,
                                                                                         kind):
    """F12: the twin is found before the write lock, so a Remove can come in between: the item found is checked again
    inside the command, and when it is gone the check runs again there — hato's file is an item of its own, never a
    record on a removed one. The episode removed here is not the newest record or item, so only that check sees it."""
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    show = _SHOWS[language][0]
    with store:
        item, key, sub = _source_episode(store, language, data_dir, video=kind == "video")
        src = os.path.dirname(os.path.dirname(sub))
        _write(os.path.join(src, show, f"{show} - 02.srt"), _text(language, 2))
        if kind == "video":
            _video(os.path.join(src, show, f"{show} - 02.mkv"), body=b"\x1a\x45\xdf\xa3 the second episode")
        assert len(_look(store, language, store.sources()[0]["id"])["ids"]) == 1     # a newer record and item
        real = ls.Store._twin_seen

        def then_removed(self, *a):
            out = real(self, *a)
            if item in (out[2], (out[3] or (None,))[0]):
                other = ls.open_store(language, data_dir, user_files_dir)
                with other:
                    other.remove([item])
            return out
        monkeypatch.setattr(ls.Store, "_twin_seen", then_removed)
        if kind == "video":
            hato_path, pairing = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7)), _hato(key, show)
        else:
            hato_path, pairing = _hato_file(data_dir, f"{show} - 01.srt", like=sub), _hato("v1-f12-gone", show)
        change = store.register(hato_path, pairing)
        assert len(change.added) == 1 and store.item(item) is None and _items(store) == 2
        assert store.conn.execute("SELECT item_id FROM pairings WHERE content_key = ?",
                                  (pairing["content_key"],)).fetchone()[0] == change.added[0]
        assert _duplicates(store) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_F12_the_syncs_own_row_never_counts_against_the_hashing_bound(language):
    """F12: hato's file is checked by its bytes against TWIN_HASHES items of its size at most — never counting the row
    the disk sync made for that very file a moment before (it is never its own twin): with TWIN_HASHES other items of
    the size, the bytes still decide."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    base = _text(language, 1)
    subs = [_write(os.path.join(src, show, f"{show} - {n:02d}.srt"), _same_size(base, n))
            for n in range(1, ls.TWIN_HASHES + 1)]
    with store:
        ids = _look(store, language, store.add_source(src), first=True)["ids"]
        assert len(ids) == ls.TWIN_HASHES
        hato_path = _hato_file(data_dir, f"{show} - 03.srt", like=subs[2])
        synced = _sync_first(store, data_dir, hato_path)
        change = store.register(hato_path, _hato("v1-f12-bound", show, 3))
        third = store.item_id(f"{ls.CONTENT_FOLDER}/{show}/{show} - 03.srt")
        assert change.added == [] and change.pairing_item == third and store.item(synced) is None
        assert _items(store) == ls.TWIN_HASHES


@pytest.mark.parametrize("language", LANGUAGES)
def test_F12_a_twin_taken_in_between_the_check_and_the_command_is_still_found(monkeypatch, language):
    """F12: a look on another handle can take the same episode in between the check and the command: anything a twin
    would move (a record, an item, an availability) has moved, so the check runs again inside — one item, hato's file
    taking the folder's copy over as when the look came first."""
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, show, f"{show} - 01.srt"), _text(language, 1))
    key = videos.content_key(_video(os.path.join(src, show, f"{show} - 01.mkv")))
    with store:
        root = store.add_source(src)
        real = ls.Store._twin_seen
        looked = []

        def then_taken(self, *a):
            out = real(self, *a)
            if not looked:
                looked.append(out)
                other = ls.open_store(language, data_dir, user_files_dir)
                with other:
                    assert _look(other, language, root, first=True)["added"] == 1
            return out
        monkeypatch.setattr(ls.Store, "_twin_seen", then_taken)
        hato_path = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7))
        change = store.register(hato_path, _hato(key, show))
        assert looked[0][1:] == (None, None, None)                            # nothing there at the check
        assert change.added == [] and _items(store) == 1
        assert store.item(change.pairing_item)["rel_path"] == ls.library_rel(data_dir, hato_path)


def test_F12_a_hand_off_at_20k_origins_holds_the_write_lock_briefly_and_a_move_beside_it_waits_little(monkeypatch):
    """F12 (G1): at 20,000 origins every hato hand-off held the write lock 0.1 s (and seconds when sizes repeat), so
    a window's move beside it waited that long. In the timed run (SURASURA_STORE_BENCH=1), at 20k origins whose copies
    share a few sizes: a take-over by video, a file of a size thousands of items share and a new file each hold the
    lock within MOVE_BUDGET, and no move waits longer; elsewhere a short functional pass at 600."""
    from tests.test_sources_scan import BENCH, MOVE_BUDGET, _Holds, _seed
    import threading
    import time
    language = "ja"
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    src = _drive("driveA")
    count = 20_000 if BENCH else 600
    with store:
        root = store.add_source(src)
        _seed(store, root, data_dir, language, src, count)
        line = _text(language, 0).splitlines()[-2] or "x"
        common = _hato_file(data_dir, "Seeded - 01.srt", "")
        with open(common, "w", encoding="utf-8") as f:                         # written as the seeded copies are
            f.write(f"{line} {'z' * len(str(count - 1))}\n")
        sizes = store.items_of_size([os.path.getsize(common)])
        assert len(sizes[os.path.getsize(common)]) > ls.TWIN_HASHES
        twin_key = "v1-seed00000123"
        twin = store.item_of_video_key(twin_key)
        cases = [(_hato_file(data_dir, "Bench Show - 01.srt", _text(language, 7)), _hato(twin_key, "Bench Show")),
                 (common, _hato("v1-f12-common", "Seeded")),
                 (_hato_file(data_dir, "New Show - 01.srt", _text(language, 2)), _hato("v1-f12-new", "New Show"))]
        tier = "now" if store.ordered("now") else "soon"
        ids = [i for i, _e, _a in store.ordered(tier)][:6]
        holds = _Holds(monkeypatch, store.db_path)
        done, errors = threading.Event(), []

        def mover():
            other = ls.open_store(language, data_dir, user_files_dir)
            n = 0
            with other:
                while not done.is_set():
                    try:
                        other.move([ids[n % len(ids)]], tier, before_id=ids[(n + 3) % len(ids)])
                    except ls.StoreError as e:
                        errors.append(repr(e))
                    n += 1
                    done.wait(0.005)
        thread = threading.Thread(target=mover, name="mover")
        thread.start()
        changes = []
        try:
            for path, pairing in cases:
                time.sleep(0.05)
                changes.append(store.register(path, pairing))
            time.sleep(0.05)
        finally:
            done.set()
            thread.join()
        assert changes[0].added == [] and changes[0].pairing_item == twin
        assert len(changes[1].added) == 1 and len(changes[2].added) == 1
        assert errors == []
        mine = holds.of(threading.current_thread().name)
        assert mine
        if BENCH:
            assert max(mine) <= MOVE_BUDGET, sorted(mine)[-5:]
            assert max(holds.of("mover", "waits")) <= MOVE_BUDGET, sorted(holds.of("mover", "waits"))[-5:]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("twin", ("video", "bytes"))
def test_R1_with_new_arrivals_off_a_sync_before_hatos_register_still_leaves_one_item(language, twin):
    """K3 fix, left open: with New arrivals off the sync puts hato's file at the top of NOW, not in New arrivals, so
    its row was never taken out and the everyday race still gave the episode two items there. The sync's own row (no
    record, link, pin, watch, mining or placement by a person) is taken out wherever the sync put it."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        store.set_library_options(arrivals_on=False)
        item, key, sub = _source_episode(store, language, data_dir, video=twin == "video")
        if twin == "video":
            hato_path, pairing = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7)), _hato(key, show)
        else:
            hato_path, pairing = _hato_file(data_dir, f"{show} - 01.srt", like=sub), _hato("v1-r1-off", show)
        synced = _sync_first(store, data_dir, hato_path)
        assert store.item(synced)["tier"] == "now" and _items(store) == 2
        change = store.register(hato_path, pairing)
        assert _items(store) == 1 and store.item(synced) is None and change.pairing_item == item
        assert os.path.isfile(hato_path) and store.sync_disk() is None and _items(store) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_R1_with_new_arrivals_off_a_synced_row_the_user_moved_is_never_taken_out(language):
    """The user's own placement of the sync's row (a drag in NOW) makes it his: kept, as in New arrivals."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        store.set_library_options(arrivals_on=False)
        item, key, _sub = _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7))
        synced = _sync_first(store, data_dir, hato_path)
        assert store.item(item)["tier"] == "now"
        assert store.move([synced], "now", after_id=item) is not None             # a drag below the episode
        store.register(hato_path, _hato(key, show))
        assert store.item(synced) is not None and _items(store) == 2


# --- b2fix review (A1, A3, A4) ------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_F12_an_item_put_back_between_the_check_and_the_command_is_still_found(monkeypatch, language):
    """b2fix review A1: Undo of a Remove (and Put back) brings an item back under its old id, and a 2.x item has no
    record, so neither a record, an item id nor an availability moves: the stamp counts the trash's restored rows, so
    the check runs again inside the command — hato's file with that item's bytes is kept out, never a second item."""
    store = migrated(language)
    data_dir, _u = roots(language)
    with store:
        first_id = next(i for i, _e, _a in store.ordered("now") if not store.conn.execute(
            "SELECT 1 FROM pairings WHERE item_id = ?", (i,)).fetchone())
        before = _items(store)
        twin = _hato_file(data_dir, "twin.srt", like=os.path.join(data_dir, *store.item(first_id)["rel_path"].split("/")))
        removed = store.remove([first_id])
        real = ls.Store._twin_seen
        looked = []

        def then_put_back(self, *a):
            out = real(self, *a)
            if not looked:
                looked.append(out)
                assert self.undo(removed) is not None and self.item(first_id) is not None
            return out
        monkeypatch.setattr(ls.Store, "_twin_seen", then_put_back)
        change = store.register(twin, _hato("v1-a1-back", "Twin"))
        assert looked[0][1:] == (None, None, None)                            # nothing there at the check
        assert change.added == [] and change.pairing_item == first_id and _items(store) == before
        assert [p for _r, p in _duplicates(store)] == [ls.path_key(ls.library_rel(data_dir, twin))]


@pytest.mark.parametrize("language", LANGUAGES)
def test_R1_a_back_fill_never_takes_out_an_old_row_of_hatos(language):
    """b2fix review A3: a back-fill registers hato's old drops, rows the sync made long ago with no record yet — with
    New arrivals off, the whole top of NOW. Such a row is the user's episode, not the sync's row of a moment ago: it is
    never taken out (no trash row, no Put back); the record goes on it as before K3."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    with store:
        store.set_library_options(arrivals_on=False)
        item, key, _sub = _source_episode(store, language, data_dir)
        hato_path = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7))
        synced = _sync_first(store, data_dir, hato_path)
        change = store.register(hato_path, _hato(key, show), backfill=True)
        assert store.item(synced) is not None and change.pairing_item == synced and _items(store) == 2
        assert store.item(item) is not None and _duplicates(store) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_R3_a_gap_that_no_longer_waits_inside_the_command_fills_nothing_and_hatos_file_is_its_own_item(monkeypatch,
                                                                                                       language):
    """b2fix review A4: `_fill_gap` refuses a row that is no longer a waiting one (P1). `register` then went on with no
    item and failed (a TypeError, the command rolled back, the hand-off lost); now hato's file is an item of its own."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    key = videos.content_key(_video(os.path.join(src, show, f"{show} - 01.mkv")))
    with store:
        root = store.add_source(src)
        waiting = _look(store, language, root, first=True)["ids"]
        assert len(waiting) == 1 and store.item(waiting[0])["availability"] == "waiting"
        monkeypatch.setattr(ls.Store, "_fill_gap", lambda self, *a: None)
        hato_path = _hato_file(data_dir, f"{show} - 01.ja.srt", _text(language, 7))
        change = store.register(hato_path, _hato(key, show))
        assert len(change.added) == 1 and store.item_id(ls.library_rel(data_dir, hato_path)) == change.added[0]
        assert store.conn.execute("SELECT item_id FROM pairings WHERE content_key = ?", (key,)).fetchone()[0] ==             change.added[0]
