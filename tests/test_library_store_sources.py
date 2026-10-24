"""3.0's Sources in the store (SRC K1a, the RUNBOOK's §1b): the folders Surasura reads where they are (`add_source`,
`sources`, `stop_source`), the one content folder every new text copy goes into (`Library/<show>/…`), and the scan's
take-in (`take_in`): its first scan quiet in Current, later files joining their show in order or waiting in New
arrivals, every origin recorded once (`src:` + the origin's path key), a removed one never taken in again.

Why these matter: a source folder is where Surasura *finds* text; its own copy lives in the data folder. A file read
twice, a removed episode coming back, a scan that places what nobody asked for (and so gets mined), a source that
holds the data folder itself (its .trash brought back as new episodes), or a copy the disk sync adopts before the
scan places it, each breaks a rule Sonic set (SRC-1, SRC-2, SRC-7, SRC-8, B1-B3). Every test runs for Japanese and
Chinese alike, under the per-test SURASURA_TEST_ROOT, with real subtitles and texts from tests/Test Resources/ copied
into the test's data folder and into a second temp "source" folder (never a real folder of anyone's).
"""
import hashlib
import json
import os
import shutil
import sys

import pytest

from app import library_store as ls
from app.connect import fit_check
from app.connect import library as connect_library
from tests.test_library_store_support import LANGUAGES, RESOURCES, library, migrated, names, roots, write_manifest
from tests.test_sources_scan import _fresh_module_state  # noqa: F401  (D5's looks: each a new run of the app)

# Real text per language: subtitles and a text, each episode told apart by a line of real words appended
_TEXTS = {"ja": ("placed_episode.srt", "library_episode.ass", "phrases_sample.srt", "context_test.txt"),
          "zh": ("night_market.srt", "chinese_text_1.txt", "traditional_news.txt", "context_test.txt")}


def _source_root(name="source"):
    """A second "drive": a temp folder beside the test's data folder, never inside it."""
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", name)
    os.makedirs(path, exist_ok=True)
    return path


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _episode_text(language, n, extra=""):
    """A real subtitle or text with one more line of real words, so every episode's bytes differ."""
    base = _TEXTS[language][n % len(_TEXTS[language])]
    with open(os.path.join(RESOURCES, language, base), encoding="utf-8") as f:
        text = f.read()
    w = names(language)
    return text + f"\n{w[n % len(w)]}{w[(n + 7) % len(w)]} {n}{extra}\n"


def _origin(language, src, show, file_name, n, extra=""):
    """The original in the source folder: `<src>/<show>/<file_name>`."""
    path = os.path.join(src, *show.split("/"), file_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_episode_text(language, n, extra))
    return path


def _copied(data_dir, origin, show, file_name=None):
    """K1b's copy, made before `take_in` as moves' drop does: `Library/<show>/<name>` in the data folder."""
    rel = f"{ls.CONTENT_FOLDER}/{show}/{file_name or os.path.basename(origin)}"
    dest = os.path.join(data_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(origin, dest)
    return rel


def _found(language, data_dir, src, show, file_name, n, copy=True, **more):
    """One found file as the scan hands it to `take_in` (the origin's stats, the text's sha256, the copy's rel)."""
    origin = _origin(language, src, show, file_name, n)
    st = os.stat(origin)
    f = {"origin": origin, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": _sha(origin), "show": show}
    if copy:
        f["rel"] = _copied(data_dir, origin, show)
    f.update(more)
    return f


def _empty(language):
    """A 3.0 library with nothing in it yet (setup's start): the Soon line at 25, New arrivals on."""
    data_dir, user_files_dir, doc = library(language, shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return ls.open_store(language, data_dir, user_files_dir), data_dir


def _current(store):
    return [e["physical_path"] for t in ("now", "soon") for _i, e, _a in store.ordered(t)]


def _tier(store, tier):
    return [e["physical_path"] for _i, e, _a in store.ordered(tier)]


def _events(store):
    return [tuple(r) for r in store.conn.execute("SELECT item_id, kind, by, explicit FROM placement_log ORDER BY id")]


def _exclusions(store):
    return [(r[0], r[1], r[2], json.loads(r[3])) for r in store.conn.execute(
        "SELECT root_id, pattern, kind, note FROM exclusions ORDER BY id")]


def _hato(key, episode, title="Example", **more):
    record = {"schema": 1, "content_key": key, "producer": "hato", "video_path": f"D:/Shows/{title} - {episode:02d}.mkv",
              "video_size": 1473922811, "show": {"title": title, "season": 1, "episode": episode}}
    record.update(more)
    return record


# --- the sources: add, again, stop, refused (§1, B3) ----------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_source_is_one_row_and_adding_it_again_turns_it_back_on(language):
    store, data_dir = _empty(language)
    src = _source_root()
    with store:
        first = store.add_source(src)
        assert store.add_source(src + os.sep) == first                     # the same folder, written otherwise
        assert store.add_source(src.upper() if sys.platform == "win32" else src) == first
        assert store.sources() == [{"id": first, "path": os.path.normpath(src), "on": True, "items": 0}]
        assert store.stop_source(first) is True
        assert store.stop_source(first) is False                           # already off: nothing written
        assert store.sources() == []
        assert store.sources(all=True) == [{"id": first, "path": os.path.normpath(src), "on": False, "items": 0}]
        assert store.add_source(src) == first                              # back on, never a second row
        assert [s["on"] for s in store.sources(all=True)] == [True]
        rows = store.conn.execute("SELECT kind, placement, catalogue_only FROM roots WHERE id = ?", (first,)).fetchall()
        assert rows == [("source", None, 0)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_source_may_never_be_or_hold_surasuras_own_folders(language):
    """B3: a scan of the data folder (or of a folder holding it) would bring back its .trash as new episodes and read
    the word lists as books; a drive root or the user's profile holds them or far too much."""
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    os.makedirs(os.path.join(data_dir, ls.CONTENT_FOLDER), exist_ok=True)
    os.makedirs(user_files_dir, exist_ok=True)
    test_root = os.environ["SURASURA_TEST_ROOT"]
    a_file = os.path.join(_source_root(), "x.srt")
    with open(a_file, "w", encoding="utf-8") as f:
        f.write(_episode_text(language, 1))
    refused = {
        "the data folder": data_dir,
        "a folder inside it": os.path.join(data_dir, ls.CONTENT_FOLDER),
        "every language's data": os.path.dirname(data_dir),
        "the user files": user_files_dir,
        "every language's user files": os.path.dirname(user_files_dir),
        "the store's folder": os.path.dirname(store.db_path),
        "a folder holding them all": test_root,
        "a file": a_file,
        "a folder that isn't there": os.path.join(test_root, "elsewhere", "not there"),
        "a drive root": os.path.splitdrive(test_root)[0] + os.sep if sys.platform == "win32" else os.sep,
        "the user's profile": os.path.expanduser("~"),
    }
    with store:
        before = store.conn.execute("SELECT * FROM roots").fetchall()
        reasons = {}
        for what, path in refused.items():
            with pytest.raises(ls.NotASource) as caught:
                store.add_source(path)
            assert caught.value.reason, what                               # a reason the window shows
            reasons[what] = caught.value.reason
        # each refused for its own reason (a drive root and the profile hold the test's folders too)
        assert "drive" in reasons["a drive root"] and "user folder" in reasons["the user's profile"]
        assert reasons["a file"] == reasons["a folder that isn't there"] != reasons["the data folder"]
        assert reasons["a folder holding them all"] != reasons["the data folder"] == reasons["a folder inside it"]
        assert store.conn.execute("SELECT * FROM roots").fetchall() == before    # nothing written
        assert store.add_source(_source_root()) is not None                 # a folder beside them is fine


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_old_surasura_folder_is_no_source_but_the_shows_inside_its_data_are(language):
    """The 2.x import brings no shows (Sonic 2026-10-23): the learner adds them again, and a 2.x keeps its only copy
    in its own data folder. Added whole, that folder's scan would read the program's files, the word lists and the
    trash as books; a show's folder inside its data is read as any folder is. A folder that merely holds a `data`
    folder is no Surasura."""
    store, _data_dir = _empty(language)
    old = _source_root("旧すらすら 2.5")
    for rel in ("Surasura.exe", os.path.join("_internal", "base_library.zip"),
                os.path.join("User Files", language, "IgnoreList.txt")):
        os.makedirs(os.path.dirname(os.path.join(old, rel)), exist_ok=True)
        with open(os.path.join(old, rel), "w", encoding="utf-8") as f:
            f.write("#")
    show = os.path.join(old, "data", language, "HighPriority", "冒険")
    trash = os.path.join(old, "data", language, ".trash", "removed")
    for folder in (show, trash):
        os.makedirs(folder)
        with open(os.path.join(folder, "01.srt"), "w", encoding="utf-8") as f:
            f.write(_episode_text(language, 1))
    program = _source_root("Surasura 3")                     # a program folder with no library beside it
    os.makedirs(os.path.join(program, "_internal"))
    refused = [old, os.path.join(old, "User Files"), os.path.join(old, "User Files", language),
               os.path.join(old, "_internal"), os.path.join(old, "data"), os.path.join(old, "data", language),
               trash, os.path.dirname(trash), program]
    plain = _source_root("アニメ")                            # holds a folder called data: no Surasura
    os.makedirs(os.path.join(plain, "data", language))
    with store:
        before = store.conn.execute("SELECT * FROM roots").fetchall()
        for path in refused:
            with pytest.raises(ls.NotASource) as caught:
                store.add_source(path)
            assert "data folder" in caught.value.reason, path
        assert store.conn.execute("SELECT * FROM roots").fetchall() == before    # nothing written
        assert store.add_source(show) is not None
        assert store.add_source(plain) is not None


@pytest.mark.parametrize("name", [".AppleDouble", ".Trashes", ".Spotlight-V100", ".fseventsd", ".TemporaryItems",
                                  ".stversions", ".trash", "$RECYCLE.BIN", "$Recycle.Bin", "#recycle", "@eaDir",
                                  "System Volume Information"])
def test_the_walk_skips_hidden_recycled_and_old_version_folders(name, tmp_path):
    """B3: Syncthing's .stversions, the recycle bins (Windows' and a NAS's), a NAS's @eaDir thumbnails and the trash
    hold removed or old versions: read, they would bring back episodes removed on purpose."""
    folder = tmp_path / name
    folder.mkdir()
    assert ls.skip_dir(name, str(folder)) is True


@pytest.mark.parametrize("name", ["フリーレン", "夜市", "Season 1", "Specials", "第2期", ".hack Sign"])   # LF-21: a title
def test_the_walk_reads_an_ordinary_show_folder(name, tmp_path):
    folder = tmp_path / name
    folder.mkdir()
    assert ls.skip_dir(name, str(folder)) is False
    assert ls.skip_dir(name, next(iter(os.scandir(str(tmp_path))))) is False   # a DirEntry from the listing too


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is a Windows folder link")
def test_the_walk_never_follows_a_junction(tmp_path):
    """B3: a folder link that loops (or points at the data folder) is never followed."""
    import _winapi
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    _winapi.CreateJunction(str(target), str(link))
    assert ls.skip_dir("link", str(link)) is True
    entry = [e for e in os.scandir(str(tmp_path)) if e.name == "link"][0]
    assert ls.skip_dir("link", entry) is True
    assert ls.skip_dir("real", str(target)) is False


def test_a_cloud_placeholder_is_never_read():
    """B3 / RD-S1: a cloud placeholder's read downloads it silently; its attributes (Connect's `_on_disk` check) say so,
    and a stat without them (POSIX) is an ordinary file (S17)."""
    class St:
        st_file_attributes = 0x400000                # RECALL_ON_DATA_ACCESS
    assert ls.is_placeholder(St()) is True
    for attrs in (0x1000, 0x40000):
        St.st_file_attributes = attrs
        assert ls.is_placeholder(St()) is True
    St.st_file_attributes = 0x20                     # ARCHIVE: an ordinary file
    assert ls.is_placeholder(St()) is False
    assert ls.is_placeholder(object()) is False      # no attributes at all (POSIX)


# --- the content folder (§1, B2) ------------------------------------------------------------------------------------- #

def test_the_content_folder_groups_like_a_tier_folder_and_never_gives_a_place():
    for rel in ("Library/夜市/Season 1/x.srt", "HighPriority/夜市/Season 1/x.srt", "GoalContent/夜市/Season 1/x.srt"):
        assert ls._below_tier(rel) == "夜市/Season 1"
    assert ls.folder_key_of("Library/夜市/x.srt") == ls.folder_key_of("HighPriority/夜市/x.srt")
    # N3: written in another case, it is the same folder where the file system says so (as take_in accepts it)
    folded = sys.platform in ("win32", "darwin")
    assert ls._below_tier("library/夜市/x.srt") == ("夜市" if folded else "library/夜市")
    assert ls.CONTENT_FOLDER not in ls.TIER_OF_FOLDER
    assert ls.WALK_FOLDERS == ("HighPriority", "LowPriority", "GoalContent", "Library")


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_walk_and_reset_see_the_content_folder(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    src = _source_root()
    show = names(language)[40]
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep01.srt", 1)
        store.take_in(root, [f])
        assert f["rel"] in [r for r, _s, _m in ls.walk_library(data_dir)["files"]]
        assert f["rel"] in ls.reset_walk(data_dir)
        assert ls.CONTENT_FOLDER in list(ls.Round(store).queue)
        assert store.reset_order() is None or f["rel"] in _current(store) + _tier(store, "arrivals")


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_sync_never_adds_an_untracked_file_under_the_content_folder(language):
    """B2: the window's disk sync would place the scan's copy before `take_in` does (the top of Current, an
    `entered_mine_line` event: mined, though nobody placed it). It keeps went / came / refresh for known items there."""
    store = migrated(language)
    data_dir, _u = roots(language)
    src = _source_root()
    show = names(language)[41]
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep01.srt", 1)           # copied; take_in not yet called
        before = store.versions()
        assert store.sync_disk() is None
        assert store.item_id(f["rel"]) is None and store.versions() == before
        change = store.take_in(root, [f])
        item = change.added[0]
        full = os.path.join(data_dir, *f["rel"].split("/"))
        os.remove(full)
        assert store.sync_disk()["missing"] == [item]                      # went: marked, never removed (SRC-8)
        shutil.copyfile(f["origin"], full)
        assert store.sync_disk()["back"] == [item]
        with open(full, "a", encoding="utf-8") as fh:
            fh.write(_episode_text(language, 9))
        store.sync_disk()
        assert store.item(item)["size"] == os.path.getsize(full)          # refreshed
        looked = []                                                        # S19: the walk sees them, no stat each
        real_exists = os.path.exists
        monkey = lambda p: looked.append(p) or real_exists(p)               # noqa: E731
        ls.os.path.exists, saved = monkey, ls.os.path.exists
        try:
            store.sync_disk()
        finally:
            ls.os.path.exists = saved
        assert not [p for p in looked if os.sep + ls.CONTENT_FOLDER + os.sep in os.path.normpath(p)]
        orphan = _copied(data_dir, _origin(language, src, show, "ep02.srt", 2), show)   # a crash's copy, left
        assert store.sync_disk() is None and store.item_id(orphan) is None
        assert orphan not in _current(store) + _tier(store, "arrivals")
        assert store.reset_order() is None or store.item_id(orphan) is None   # Reset never adds it either


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_read_only_schedule_leaves_an_untracked_copy_out(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.close()
    show = names(language)[42]
    orphan = _copied(data_dir, _origin(language, _source_root(), show, "ep01.srt", 1), show)
    schedule = ls.read_only_schedule(language, data_dir, user_files_dir)
    assert orphan not in [e["physical_path"] for rows in schedule.values() if isinstance(rows, list) for e in rows]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_sync_never_adds_a_file_kept_out_as_a_duplicate(language):
    """K1a.5 for K3: a data-folder file that is another item's episode is kept out by its `duplicate` exclusion."""
    store = migrated(language)
    data_dir, _u = roots(language)
    rel = f"HighPriority/{names(language)[43]}/dup.srt"
    with store:
        with store._writing():
            store.conn.execute("INSERT INTO exclusions (root_id, pattern, kind, created_at) VALUES (1, ?, 'duplicate', ?)",
                               (ls.path_key(rel), ls._now()))
        path = os.path.join(data_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_episode_text(language, 3))
        assert store.sync_disk() is None and store.item_id(rel) is None
        other = f"HighPriority/{names(language)[43]}/kept.srt"
        shutil.copyfile(path, os.path.join(data_dir, *other.split("/")))
        assert store.sync_disk()["added"] and store.item_id(other) is not None    # the rule is that path only


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_left_at_its_target_is_reused_never_copied_again_as_name_2(language):
    """B2: a crash between the copy and the commit leaves the copy; the next look re-uses it (same name, same bytes)
    instead of making `name (2)`. A different file of that name steps to the next free name, as moves' copy does."""
    _store, data_dir = _empty(language)
    _store.close()
    src = _source_root()
    show = names(language)[44]
    origin = _origin(language, src, show, "ep01.srt", 1)
    size, sha = os.path.getsize(origin), _sha(origin)
    rel = f"{ls.CONTENT_FOLDER}/{show}/ep01.srt"
    assert ls.content_target(data_dir, rel, size, sha) == (rel, False)              # free: copy it there
    _copied(data_dir, origin, show)
    assert ls.content_target(data_dir, rel, size, sha) == (rel, True)               # there, same bytes: re-use
    other = _origin(language, src, show + "x", "ep01.srt", 2)
    assert ls.content_target(data_dir, rel, os.path.getsize(other), _sha(other)) == \
        (f"{ls.CONTENT_FOLDER}/{show}/ep01 (2).srt", False)
    assert ls.sha256_of(origin) == sha


# --- take_in: the first scan (SRC-1, S1) ----------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_first_scan_lands_at_the_end_of_current_by_show_in_natural_order_and_logs_nothing(language):
    """SRC-1: setup's scan lands in Current, grouped by show (shows in name order, ep2 before ep10); S1: it logs no
    placement event, so Connect makes no card of it by itself."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    a, b = sorted([w[45], w[46]], key=lambda t: ls.search_fold(t, language))
    with store:
        store.register_reader("connect")
        root = store.add_source(src)
        found = [_found(language, data_dir, src, b, "ep10.srt", 10), _found(language, data_dir, src, a, "ep2.srt", 2),
                 _found(language, data_dir, src, b, "ep2.srt", 3), _found(language, data_dir, src, a, "ep10.srt", 4),
                 _found(language, data_dir, src, a, "ep1.srt", 5)]
        before = _events(store)
        change = store.take_in(root, found, first=True)
        want = [f"Library/{a}/ep1.srt", f"Library/{a}/ep2.srt", f"Library/{a}/ep10.srt", f"Library/{b}/ep2.srt",
                f"Library/{b}/ep10.srt"]
        assert _current(store) == want and len(change.added) == 5
        assert _events(store) == before                                    # quiet: nothing to mine
        later = _found(language, data_dir, src, w[47], "ep1.srt", 6)        # a second first-scan batch: after them
        store.take_in(root, [later], first=True)
        assert _current(store) == want + [later["rel"]]
        assert change.kind == "take_in"
        with pytest.raises(ls.UndoRefused):                                # S6: not on the user's Undo
            store.undo(change)


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_origin_is_one_record_keyed_by_its_path_with_its_source_and_show(language):
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[48]
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep01.srt", 1, video_path="D:/Shows/x.mkv", video_size=12,
                   video_key="v1-abc")
        item = store.take_in(root, [f], first=True).added[0]
        rows = store.conn.execute("SELECT content_key, item_id, pairing FROM pairings").fetchall()
        assert [(k, i) for k, i, _p in rows] == [("src:" + ls.path_key(os.path.abspath(f["origin"])), item)]
        record = json.loads(rows[0][2])
        assert record == {"producer": "source", "channel_id": root, "root": root, "origin": os.path.abspath(f["origin"]),
                          "size": f["size"], "mtime_ns": f["mtime_ns"], "sha256": f["sha256"], "show": {"title": show},
                          "video_path": "D:/Shows/x.mkv", "video_size": 12, "video_key": "v1-abc"}
        origins = store.origins()
        assert list(origins) == [ls.path_key(os.path.abspath(f["origin"]))]
        assert origins[ls.path_key(os.path.abspath(f["origin"]))].item_id == item
        assert store.sources()[0]["items"] == 1
        assert store.item(item)["work_id"] is not None


# --- take_in: later looks (SRC-2, S2, S3, S14) ----------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_episode_joins_its_show_in_current_in_order_silently(language):
    """SRC-2: a show already shown takes a later file in silently (minable); S3: a gap filled lands in order — ep3
    between ep2 and ep4, never after ep4 — and K4's episode numbers order it when both have one."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[49]
    with store:
        root = store.add_source(src)
        store.take_in(root, [_found(language, data_dir, src, show, f"ep{n}.srt", n) for n in (1, 2, 4)], first=True)
        store.register_reader("connect")
        three = store.take_in(root, [_found(language, data_dir, src, show, "ep3.srt", 3)])
        assert _current(store) == [f"Library/{show}/ep{n}.srt" for n in (1, 2, 3, 4)]
        assert ("placed", "source", 0) in [e[1:] for e in _events(store) if e[0] == three.added[0]]
        store.take_in(root, [_found(language, data_dir, src, show, "ep5.srt", 5)])
        assert _current(store)[-1] == f"Library/{show}/ep5.srt"
        # numbered by K4 (names that don't sort): the numbers decide
        other = names(language)[50]
        store.take_in(root, [_found(language, data_dir, src, other, "b.srt", 11, episode=1),
                             _found(language, data_dir, src, other, "a.srt", 12, episode=3)], first=True)
        store.take_in(root, [_found(language, data_dir, src, other, "c.srt", 13, episode=2)])
        assert [p for p in _current(store) if f"/{other}/" in p] == [f"Library/{other}/{n}.srt" for n in "bca"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_episode_of_a_show_only_in_goal_or_finished_leads_current(language):
    """S2 (Q4-9, as built): a show with rows only in 6+ Months or Finished takes its new episode at the top of
    Current."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        keep = store.take_in(root, [_found(language, data_dir, src, w[51], "ep1.srt", 1)], first=True).added
        parked = store.take_in(root, [_found(language, data_dir, src, w[52], "ep1.srt", 2)], first=True).added
        store.move(parked, "goal")
        new = store.take_in(root, [_found(language, data_dir, src, w[52], "ep2.srt", 3)]).added
        assert _current(store)[0] == f"Library/{w[52]}/ep2.srt"
        done = store.take_in(root, [_found(language, data_dir, src, w[53], "ep1.srt", 4)], first=True).added
        store.finish(done + new)
        store.take_in(root, [_found(language, data_dir, src, w[53], "ep2.srt", 5)])
        assert _current(store)[:2] == [f"Library/{w[53]}/ep2.srt", f"Library/{w[51]}/ep1.srt"]
        assert keep


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_never_shown_waits_in_new_arrivals_and_its_next_episode_joins_it_there(language):
    """SRC-2 / S14: a later look's (or a folder added after setup's) new show waits in New arrivals; with New arrivals
    off it leads Current; a placing rule for the source still places an arrival (D30, S13: `source:<id>`)."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        store.take_in(root, [_found(language, data_dir, src, w[54], "ep1.srt", 1)], first=True)
        store.take_in(root, [_found(language, data_dir, src, w[55], "ep2.srt", 2)])
        assert _tier(store, "arrivals") == [f"Library/{w[55]}/ep2.srt"]
        store.take_in(root, [_found(language, data_dir, src, w[55], "ep1.srt", 3)])
        assert _tier(store, "arrivals") == [f"Library/{w[55]}/ep1.srt", f"Library/{w[55]}/ep2.srt"]
        ruled = store.take_in(root, [_found(language, data_dir, src, w[56], "ep1.srt", 4)],
                              rules={f"source:{root}": "goal"})
        assert _tier(store, "goal") == [f"Library/{w[56]}/ep1.srt"] and ruled.added
        store.take_in(root, [_found(language, data_dir, src, w[57], "ep1.srt", 5)], rules={"source": "wait"})
        assert _tier(store, "arrivals")[-1] == f"Library/{w[57]}/ep1.srt"
        store.set_library_options(arrivals_on=False)
        store.take_in(root, [_found(language, data_dir, src, w[58], "ep1.srt", 6)])
        assert _current(store)[0] == f"Library/{w[58]}/ep1.srt"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_2x_show_folder_and_its_library_copies_are_one_title(language):
    """§1: `_below_tier` strips Library, so `HighPriority/<show>` and `Library/<show>` share a folder key: one title,
    and a new copy joins the old show after its last row in Current (SRC-2 for free)."""
    store = migrated(language)
    data_dir, _u = roots(language)
    first = _current(store)[0]
    show = first.split("/")[1]
    src = _source_root()
    with store:
        old_work = store.item(store.item_id(first))["work_id"]
        root = store.add_source(src)
        new = f"{show}_第{5:02d}話.srt"                                # the next episode, named as the old ones
        item = store.take_in(root, [_found(language, data_dir, src, show, new, 1)]).added[0]
        assert store.item(item)["work_id"] == old_work
        rows = [p for p in _current(store) if p.split("/")[1] == show]
        assert rows[-1] == f"Library/{show}/{new}"
        assert _current(store).index(rows[-1]) == _current(store).index(rows[-2]) + 1


# --- take_in: never twice, never a removed one (SRC-7, SRC-8, S6) ---------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_one_origin_is_taken_in_once_across_overlapping_sources_and_within_a_batch(language):
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[59]
    with store:
        wide = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep1.srt", 1)
        narrow = store.add_source(os.path.join(src, show))                 # S:\Video and S:\Video\Anime
        change = store.take_in(wide, [f, dict(f)], first=True)
        assert len(change.added) == 1 and len(change.skipped["known"]) == 1
        again = store.take_in(narrow, [dict(f, origin=os.path.join(src, show, "EP1.srt") if sys.platform == "win32"
                                             else f["origin"])])
        assert again.added == [] and len(again.skipped["known"]) == 1
        assert store.conn.execute("SELECT COUNT(*) FROM pairings").fetchone()[0] == 1
        assert len(_current(store)) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_take_in_records_an_origin_on_an_item_it_names_or_finds_at_its_copy(language):
    """K1b's checks (a) and (b) hand `take_in` the item an origin belongs to (hato's, or one with the same bytes):
    the origin is recorded on it, no item is added and nothing moves. A copy already an item is that item."""
    store = migrated(language)
    data_dir, _u = roots(language)
    src = _source_root()
    held = _current(store)[0]
    with store:
        root = store.add_source(src)
        held_id = store.item_id(held)
        order = _current(store)
        f = _found(language, data_dir, src, names(language)[60], "ep1.srt", 1, copy=False, item_id=held_id)
        change = store.take_in(root, [f])
        assert change.added == [] and change.attached == [held_id] and _current(store) == order
        assert store.origins()[ls.path_key(os.path.abspath(f["origin"]))].item_id == held_id
        g = _found(language, data_dir, src, names(language)[61], "ep1.srt", 2)
        store.take_in(root, [g], first=True)
        h = _found(language, data_dir, src, names(language)[61], "ep1b.srt", 2, copy=False)
        h["rel"] = g["rel"]                                                # another origin, same copy
        assert store.take_in(root, [h]).attached == [store.item_id(g["rel"])]
        gone = store.take_in(root, [_found(language, data_dir, src, "x", "y.srt", 3, copy=False, item_id=999999)])
        assert gone.added == [] and gone.attached == [] and gone.skipped["gone"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_remove_keeps_every_origin_out_and_undo_lets_it_back(language):
    """SRC-8 / S6: Remove writes an exclusion per origin (its path, with the text's size and sha256 and the video's
    key); a scan never takes it in again — nor the same bytes found elsewhere (a moved original), nor a subtitle of
    the same video. Undo of the Remove deletes them."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[62]
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep1.srt", 1, video_key="v1-feed")
        item = store.take_in(root, [f], first=True).added[0]
        removed = store.remove([item])
        assert _exclusions(store) == [(root, ls.path_key(os.path.abspath(f["origin"])), "removed",
                                       {"size": f["size"], "sha256": f["sha256"], "video_key": "v1-feed"})]
        assert ls.path_key(os.path.abspath(f["origin"])) in store.excluded()
        assert store.excluded([root + 1]) == {}
        back = store.take_in(root, [dict(f)])
        assert back.added == [] and len(back.skipped["excluded"]) == 1
        retimed = dict(f, sha256="0" * 64, size=f["size"] + 1, video_key=None)   # its path, other bytes (a v2)
        assert store.take_in(root, [retimed]).skipped["excluded"]
        moved = dict(f, origin=shutil.copyfile(f["origin"], os.path.join(src, "moved.srt")), video_key=None)
        assert store.take_in(root, [moved]).skipped["excluded"]               # the same bytes, moved
        other = _found(language, data_dir, src, show, "ep1.en.srt", 7, video_key="v1-feed")
        assert store.take_in(root, [other]).skipped["excluded"]                # the same video's other subtitle
        assert _current(store) == [] and _tier(store, "arrivals") == []
        store.undo(removed)
        assert _exclusions(store) == [] and _current(store) == [f["rel"]]
        assert store.take_in(root, [dict(f)]).skipped["known"]                 # its record came back with it


@pytest.mark.parametrize("language", LANGUAGES)
def test_put_back_from_the_trash_lets_the_origin_back_and_finish_keeps_it(language):
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, w[63], "ep1.srt", 1)
        item = store.take_in(root, [f], first=True).added[0]
        trashed = store.remove([item]).trash_ids
        assert _exclusions(store)
        store.restore(trashed)
        assert _exclusions(store) == []
        store.finish([item])                                                  # Finish keeps the records
        assert ls.path_key(os.path.abspath(f["origin"])) in store.origins()
        assert store.take_in(root, [dict(f)]).skipped["known"]
        assert _exclusions(store) == []
        undo_add = store.take_in(root, [_found(language, data_dir, src, w[64], "ep1.srt", 2)], first=True)
        undone = store.remove(undo_add.added, kind="undo_add")                # every way out keeps it out
        assert len(_exclusions(store)) == 1
        store.undo(undone)
        assert _exclusions(store) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_take_in_refuses_a_copy_outside_the_content_folder_and_a_stopped_source(language):
    store, data_dir = _empty(language)
    src = _source_root()
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, names(language)[65], "ep1.srt", 1)
        before = store.versions()
        for rel in ("HighPriority/x/ep1.srt", "../outside.srt", "Library"):
            with pytest.raises(ValueError):
                store.take_in(root, [dict(f, rel=rel)])
        store.stop_source(root)
        with pytest.raises(ls.NotASource):
            store.take_in(root, [f])
        with pytest.raises(ls.NotASource):
            store.take_in(root + 99, [f])
        assert store.versions() == before
        assert store.take_in(store.add_source(src), []) is None             # nothing found: nothing written


# --- what Connect reads (B1) ----------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_connect_reads_hatos_record_before_a_source_and_a_recopy_never_moves_its_pairing(language):
    """B1: an origin row never shadows hato's video path, ids and episode numbers; a re-copy rewrites only the size,
    time and sha256 of its row, so Connect's pairing version stays (else: "the pairing keeps changing; nothing was
    mined")."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[66]
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep1.srt", 1)
        only = store.take_in(root, [f], first=True).added[0]
        seen = connect_library.pairing_of(store, only)
        assert seen["producer"] == "source" and not {"size", "mtime_ns", "sha256"} & set(seen)
        version = fit_check.version(seen)
        assert store.update_origin(f["origin"], f["size"] + 1, f["mtime_ns"] + 1, "0" * 64) is True
        assert store.update_origin(f["origin"], f["size"] + 1, f["mtime_ns"] + 1, "0" * 64) is False
        assert fit_check.version(connect_library.pairing_of(store, only)) == version
        assert store.origins()[ls.path_key(os.path.abspath(f["origin"]))].sha256 == "0" * 64
        assert store.update_origin(os.path.join(src, "never seen.srt"), 1, 1, "1" * 64) is False
        # hato's record first, whichever is newer
        hato_file = os.path.join(data_dir, "HighPriority", "Hato", f"{show}.srt")
        os.makedirs(os.path.dirname(hato_file))
        with open(hato_file, "w", encoding="utf-8") as fh:      # hato's own text (the same bytes would be the
            fh.write(_episode_text(language, 5))                # source's episode: K3, no item of its own)
        paired = store.register(hato_file, _hato("v1-hh", 5, show)).added[0]
        g = _found(language, data_dir, src, show, "hato copy.srt", 2, copy=False, item_id=paired)
        store.take_in(root, [g])
        assert connect_library.pairing_of(store, paired)["content_key"] == "v1-hh"
        version = fit_check.version(connect_library.pairing_of(store, paired))
        store.update_origin(g["origin"], 5, 5, "2" * 64)
        assert fit_check.version(connect_library.pairing_of(store, paired)) == version


@pytest.mark.parametrize("language", LANGUAGES)
def test_place_after_show_reads_hatos_episode_not_a_newer_origin_row(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    src = _source_root()
    show = names(language)[67]
    with store:
        store.set_library_options(arrivals_on=False)
        root = store.add_source(src)
        ids = {}
        for ep in (1, 2, 4, 3):
            path = os.path.join(data_dir, "HighPriority", show, f"{show}_{ep}.srt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_episode_text(language, ep))
            ids[ep] = store.register(path, _hato(f"v1-{ep}", ep, show)).added[0]
        store.move([ids[3]], "goal")
        g = _found(language, data_dir, src, show, "three.srt", 3, copy=False, item_id=ids[3])
        store.take_in(root, [g])                                              # the newest row is the origin's
        with store._writing():                                                # beside hato's ep 2: an origin row
            store.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES (?, ?, ?, ?)",
                               ("src:y", ids[2], json.dumps({"producer": "source", "show": {"title": show, "episode": 9}}),
                                ls._now()))                                   # naming another episode: never read
        store.place([ids[3]], "after-show")
        order = [store.item_id(p) for p in _current(store)]
        assert order.index(ids[3]) == order.index(ids[2]) + 1 == order.index(ids[4]) - 1   # by hato's episode 3


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_reads_a_source_row_only_when_its_item_has_no_other(language):
    """B1 for `_work_by_record`: hato's season decides whether a record joins a title; an origin row beside hato's
    (here one written with a season of its own) is never read."""
    store, data_dir = _empty(language)
    show = names(language)[68]
    with store:
        path = os.path.join(data_dir, "HighPriority", "Hato", f"{show}.srt")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_episode_text(language, 1))
        item = store.register(path, _hato("v1-s1", 1, show)).added[0]
        work = store.item(item)["work_id"]
        with store._writing():
            store.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES (?, ?, ?, ?)",
                               ("src:x", item, json.dumps({"producer": "source", "show": {"title": show, "season": 2,
                                                                                         "episode": 1}}), ls._now()))
        assert store._work_by_record({"show": {"title": show, "season": 1, "episode": 2}}) == work
        assert store._work_by_record({"show": {"title": show, "season": 2, "episode": 2}}) is None


# --- the guard, and a library with no sources (K1a.6, K1a.7) --------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_trash_file_never_moves_a_file_outside_the_data_folder(language, tmp_path):
    data_dir, _u = roots(language)
    outside = tmp_path / "original.srt"
    outside.write_text(_episode_text(language, 1), encoding="utf-8")
    for rel in (str(outside), "../original.srt", None, ""):
        assert ls.trash_file(data_dir, rel) is None
    assert outside.exists()
    inside = os.path.join(data_dir, "Library", "x", "ep.srt")
    os.makedirs(os.path.dirname(inside))
    shutil.copyfile(str(outside), inside)
    assert ls.trash_file(data_dir, "Library/x/ep.srt").startswith(".trash/") and not os.path.exists(inside)
    if sys.platform == "win32":                                             # a folder link out of the data folder
        import _winapi
        far = tmp_path / "far"
        far.mkdir()
        (far / "ep.srt").write_text(_episode_text(language, 2), encoding="utf-8")
        _winapi.CreateJunction(str(far), os.path.join(data_dir, "Library", "linked"))
        assert ls.trash_file(data_dir, "Library/linked/ep.srt") is None and (far / "ep.srt").exists()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_with_no_sources_copies_as_before(language):
    """Today's libraries come out byte-identical: no table added to the copy, a sync of a library with no content
    folder changes nothing, and the copy written again is the same bytes."""
    assert ls.COPY_TABLES == ("roots", "pieces", "trash", "exclusions", "anki_links", "anki_changes", "pairings",
                              "placement_log", "made_words", "made_lines", "works")
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    with store:
        assert store.sources(all=True) == [] and store.origins() == {} and store.excluded() == {}
        before = store.versions()
        assert store.sync_disk() is None and store.versions() == before
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        first = f.read()
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        assert f.read() == first
    doc = json.loads(first.decode("utf-8"))
    tables = doc["surasura_library"]["tables"]
    assert [r[1] for r in tables["roots"]["rows"]] == ["library"] and tables["exclusions"]["rows"] == []


# --- the review's fixes (SRC-K1a-adversary A1-A6) ------------------------------------------------------------------- #

def _junction(target, link):
    """A folder link: a junction on Windows, a symlink elsewhere (the walk follows both into a 2.x tier folder)."""
    os.makedirs(os.path.dirname(str(link)), exist_ok=True)
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(str(target), str(link), target_is_directory=True)


@pytest.mark.parametrize("language", LANGUAGES)
def test_remove_trashes_a_file_in_a_linked_2x_show_folder_as_before_and_the_sync_never_brings_it_back(language,
                                                                                                    tmp_path):
    """A1: a 2.x tier's show folder that is a junction (the walk follows it) had its file moved to `.trash` on Remove
    before Sources; it still does. Left in place with its row deleted, the next sync would add it again as a new item,
    which could then be mined."""
    from app.services import moves
    store = migrated(language)
    data_dir, _u = roots(language)
    far = tmp_path / "far"
    far.mkdir()
    (far / "ep1.srt").write_text(_episode_text(language, 1), encoding="utf-8")
    _junction(far, os.path.join(data_dir, "HighPriority", "Linked"))
    with store:
        assert store.sync_disk() is not None
        item = store.item_id("HighPriority/Linked/ep1.srt")
        assert item is not None
        change = moves.Writer._remove(None, store, {"ids": [item]})
        assert change is not None and store.item(item) is None
        assert not (far / "ep1.srt").exists()                               # moved, as the base did
        trashed = store.conn.execute("SELECT trashed_path FROM trash").fetchall()
        assert len(trashed) == 1 and trashed[0][0].startswith(".trash/")
        assert os.path.isfile(os.path.join(data_dir, *trashed[0][0].split("/")))
        assert store.sync_disk() is None                                     # nothing to bring back


@pytest.mark.parametrize("language", LANGUAGES)
def test_remove_and_undo_add_refuse_to_drop_a_row_whose_file_isnt_surasuras_to_move(language, tmp_path):
    """A1: a copy under `Library/` that a folder link leads out of the data folder is never moved (it may be a source's
    original); Remove and every Undo of an add (Add, Extract, the finished import) then refuse, the row kept, rather
    than delete a row whose file stays on disk for a sync to find again."""
    from types import SimpleNamespace
    from app.services import moves
    store, data_dir = _empty(language)
    src = _source_root()
    far = tmp_path / "far"
    far.mkdir()
    (far / "ep1.srt").write_text(_episode_text(language, 1), encoding="utf-8")
    _junction(far, os.path.join(data_dir, ls.CONTENT_FOLDER, "linked"))
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, "linked", "ep1.srt", 1, copy=False)
        f["rel"] = f"{ls.CONTENT_FOLDER}/linked/ep1.srt"
        item = store.take_in(root, [f], first=True).added[0]
        before = store.versions()
        with pytest.raises(ls.StoreConflict):
            moves.Writer._remove(None, store, {"ids": [item]})
        for kind in ("insert", "import_finished"):
            added = SimpleNamespace(kind=kind, copied=[f["rel"]], added=[item], items=[item])
            with pytest.raises(ls.StoreConflict):
                moves.Writer._undo_added(None, store, added, [item])
        assert store.item(item) is not None and (far / "ep1.srt").exists()
        assert store.versions() == before and _exclusions(store) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' path spellings")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_source_is_one_folder_whatever_its_spelling_for_the_refusals_and_for_again(language, tmp_path, monkeypatch):
    """A2 / A6: a long-path prefix, the long UNC prefix, this computer's admin share and a junction all name one
    folder: the data folder written so is refused like the data folder, and a source written so is that source again
    (its row and its path as first written, so its origins' keys never change)."""
    store, data_dir = _empty(language)
    src = _source_root()

    def spellings(path):
        drive, rest = os.path.splitdrive(path)
        share = drive[0] + "$" + rest
        return {"long": "\\\\?\\" + path, "long UNC": "\\\\?\\UNC\\localhost\\" + share,
                "admin share": "\\\\localhost\\" + share, "loopback": "\\\\127.0.0.1\\" + share,
                "forward": "//?/" + path.replace("\\", "/")}
    with store:
        before = store.conn.execute("SELECT * FROM roots").fetchall()
        own = {"the data folder": data_dir, "every language's data": os.path.dirname(data_dir),
               "a folder holding them": os.environ["SURASURA_TEST_ROOT"],
               "a folder inside": os.path.join(data_dir, ls.CONTENT_FOLDER)}
        os.makedirs(own["a folder inside"], exist_ok=True)
        for what, path in own.items():
            for how, spelled in spellings(path).items():
                with pytest.raises(ls.NotASource):
                    store.add_source(spelled)
        link = tmp_path / "to data"
        _junction(os.path.dirname(data_dir), link)
        with pytest.raises(ls.NotASource):
            store.add_source(str(link))                                     # a junction to every language's data
        link_in = tmp_path / "to inside"
        _junction(own["a folder inside"], link_in)
        with pytest.raises(ls.NotASource):
            store.add_source("\\\\?\\" + str(link_in))
        assert store.conn.execute("SELECT * FROM roots").fetchall() == before
        first = store.add_source(src)
        for how, spelled in spellings(src).items():
            assert store.add_source(spelled) == first, how
        to_src = tmp_path / "to source"
        _junction(src, to_src)
        assert store.add_source(str(to_src)) == first                       # across a junction
        assert store.sources() == [{"id": first, "path": os.path.normpath(src), "on": True, "items": 0}]
        (tmp_path / "far").mkdir()
        new = store.add_source("\\\\?\\" + str(tmp_path / "far"))
        assert new != first and store.sources()[-1] == {"id": new, "path": str(tmp_path / "far"), "on": True,
                                                        "items": 0}
        # each layer alone: the spelling read back...
        for how, spelled in spellings(src).items():
            assert ls.folder_path(spelled) == os.path.normpath(src), how
        # ...and the identity, for a spelling no rule reads back (a share, a mapped drive): here this computer's own
        share = spellings(data_dir)["admin share"]
        if os.path.isdir(share):                                            # admin shares on (the default)
            plain = lambda p: os.path.normpath(os.path.abspath(p))            # noqa: E731
            with monkeypatch.context() as m:
                m.setattr(ls, "folder_path", plain)
                for path in own.values():
                    with pytest.raises(ls.NotASource):
                        store.add_source(spellings(path)["admin share"])
                assert store.add_source(spellings(src)["admin share"]) == first
            assert store.sources()[0]["path"] == os.path.normpath(src)


def test_content_target_never_takes_a_name_it_couldnt_check(monkeypatch, tmp_path):
    """A3: a stat that fails for any reason but "not found" (access denied, a name Windows rejects) is raised, never
    read as "taken, try the next": that loops for ever and the scan never ends."""
    data_dir = str(tmp_path)
    os.makedirs(os.path.join(data_dir, "Library", "show"))
    real, calls = os.stat, []

    def denied(path, *a, **kw):
        if "show" in str(path):
            calls.append(path)
            if len(calls) > 50:
                raise RuntimeError("looping")
            raise PermissionError(13, "Access is denied", str(path))
        return real(path, *a, **kw)
    monkeypatch.setattr(os, "stat", denied)
    with pytest.raises(PermissionError):
        ls.content_target(data_dir, "Library/show/ep1.srt")
    monkeypatch.setattr(os, "stat", real)
    if sys.platform == "win32":
        with pytest.raises(OSError):
            ls.content_target(data_dir, "Library/show/ep1?.srt")             # WinError 123
    assert ls.content_target(data_dir, "Library/show/ep1.srt") == ("Library/show/ep1.srt", False)


@pytest.mark.parametrize("language", LANGUAGES)
def test_connects_pairing_keeps_the_first_origin_and_its_video_when_another_origin_is_attached(language):
    """A4: among an item's origin rows, one naming a video comes first, then the oldest: a later origin without a
    video (a moved original, a duplicate attached) never drops the video Connect mines nor moves its pairing version
    (else a job being mined is picked again)."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, w[69], "ep1.srt", 1, video_path="D:/Shows/ep1.mkv", video_size=1234,
                   video_key="v1-ep1")
        item = store.take_in(root, [f], first=True).added[0]
        version = fit_check.version(connect_library.pairing_of(store, item))
        g = _found(language, data_dir, src, w[69], "ep1 moved.srt", 1, copy=False, item_id=item)
        store.take_in(root, [g])
        later = connect_library.pairing_of(store, item)
        assert later["video_path"] == "D:/Shows/ep1.mkv" and later["origin"] == os.path.abspath(f["origin"])
        assert fit_check.version(later) == version
        # no video first, then two later origins: the one naming a video is read, and stays read
        h = _found(language, data_dir, src, w[70], "ep2.srt", 2)
        other = store.take_in(root, [h], first=True).added[0]
        oldest = connect_library.pairing_of(store, other)
        assert oldest["origin"] == os.path.abspath(h["origin"]) and "video_path" not in oldest
        m = _found(language, data_dir, src, w[70], "ep2 b.srt", 2, copy=False, item_id=other)
        store.take_in(root, [m])
        assert connect_library.pairing_of(store, other)["origin"] == os.path.abspath(h["origin"])
        k = _found(language, data_dir, src, w[70], "ep2 c.srt", 2, copy=False, item_id=other,
                   video_path="D:/Shows/ep2.mkv")
        store.take_in(root, [k])
        assert connect_library.pairing_of(store, other)["video_path"] == "D:/Shows/ep2.mkv"
        n = _found(language, data_dir, src, w[70], "ep2 d.srt", 2, copy=False, item_id=other,
                   video_path="D:/Shows/ep2 other.mkv")
        store.take_in(root, [n])
        assert connect_library.pairing_of(store, other)["origin"] == os.path.abspath(k["origin"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_batch_with_the_same_bytes_twice_adds_one_item(language):
    """A5 (SRC-7): two names for one file in one look (`ep1.srt` and its copy) are one item: the second origin is
    recorded on the first's item, and its copy, which no item holds, is named for the caller to send to the trash."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[71]
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep1.srt", 1)
        twin = shutil.copyfile(f["origin"], os.path.join(src, show, "ep1 - Copy.srt"))
        g = dict(f, origin=twin, rel=_copied(data_dir, twin, show))
        change = store.take_in(root, [g, f], first=True)
        assert len(change.added) == 1 and change.attached == change.added
        assert {o.item_id for o in store.origins().values()} == set(change.added)
        assert len(store.origins()) == 2 and len(_current(store)) == 1
        kept = store.item(change.added[0])["rel_path"]
        assert sorted(change.unused + [kept]) == sorted([f["rel"], g["rel"]])
        again = store.take_in(root, [dict(f)])                              # skipped: its copy is the item's own
        assert again.skipped["known"] and again.unused == ([] if kept == f["rel"] else [f["rel"]])


@pytest.mark.parametrize("language", LANGUAGES)
def test_item_of_video_key_finds_the_live_item_holding_a_video(language):
    """K1b's check (a): the item whose record holds a video (hato's key, or an origin's `video_key`), else None."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[72]
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep1.srt", 1, video_key="v1-src")
        item = store.take_in(root, [f], first=True).added[0]
        hato_file = os.path.join(data_dir, "HighPriority", "Hato", f"{show}.srt")
        os.makedirs(os.path.dirname(hato_file))
        with open(hato_file, "w", encoding="utf-8") as fh:
            fh.write(_episode_text(language, 2))
        paired = store.register(hato_file, _hato("v1-hato", 2, show)).added[0]
        assert store.item_of_video_key("v1-src") == item
        assert store.item_of_video_key("v1-hato") == paired
        assert store.item_of_video_key("v1-none") is None and store.item_of_video_key(None) is None
        assert store.item_of_video_key(ls.origin_key(f["origin"])) is None   # an origin's own key is no video
        store.remove([item])
        assert store.item_of_video_key("v1-src") is None                     # live items only
    assert ls.rename_no_overwrite is ls._rename_no_overwrite


# --- batch 1's fix round B ------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_episode_is_placed_by_the_folders_rule_after_show_by_default_and_waits_when_it_says_wait(language):
    """Decision 1 (lean): a later file's place is `placing_rules`' — on by default for folders and hato alike
    (`after-show`, Sonic's Q2-3 setting): handed no rules, a file of a show in Current joins it in order (S3); the
    user who sets folders to Wait (or has no rule at all) sees it in New arrivals; a rule for this folder wins over
    the folders' line (S13)."""
    from app import settings_manager
    assert settings_manager.DEFAULT_SETTINGS["placing_rules"] == {"hato": "after-show", "source": "after-show"}
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[112]
    ep = lambda n: _found(language, data_dir, src, show, f"ep{n}.srt", n)      # noqa: E731
    with store:
        root = store.add_source(src)
        store.take_in(root, [ep(1), ep(2), ep(4)], first=True)
        store.take_in(root, [ep(3)])                                          # no rules handed in: the default
        assert _current(store) == [f"Library/{show}/ep{n}.srt" for n in (1, 2, 3, 4)]
        waited = store.take_in(root, [ep(5)], rules={"source": "wait"})
        assert list(waited.placed.values()) == ["arrivals"] and _tier(store, "arrivals") == [f"Library/{show}/ep5.srt"]
        store.take_in(root, [ep(6)], rules={})                                # every rule off: it waits too
        assert _tier(store, "arrivals") == [f"Library/{show}/ep{n}.srt" for n in (5, 6)]
        store.take_in(root, [ep(7)], rules={f"source:{root}": "wait", "source": "after-show"})
        assert _tier(store, "arrivals")[-1] == f"Library/{show}/ep7.srt" and len(_current(store)) == 4


@pytest.mark.parametrize("held, joins", [({}, True), ({"hato": "top"}, True), ({"source": "wait"}, False)])
def test_the_folders_look_reads_the_rules_merged_so_an_empty_or_partial_dict_keeps_after_show(held, joins):
    """SRC W1 fix (the lead's call 3): the folders' look hands `take_in` the rules as the window's settings service
    reads them (`SourceLooks(rules=lambda: settings.get().get("placing_rules"))`). A settings.json holding {} or
    naming only hato used to hand the store a dict without `source`: a later episode waited in New arrivals though
    Settings showed *After its show*. Merged per key, only an explicit `wait` keeps it waiting."""
    from app.services.settings import SettingsService, thaw
    language = "ja"
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"target_language": language, "placing_rules": held}, f)
    rules = thaw(SettingsService(load=True).get()).get("placing_rules")
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[113]
    ep = lambda n: _found(language, data_dir, src, show, f"ep{n}.srt", n)      # noqa: E731
    with store:
        root = store.add_source(src)
        store.take_in(root, [ep(1), ep(2)], first=True)
        store.take_in(root, [ep(3)], rules=rules)
        if joins:
            assert _current(store) == [f"Library/{show}/ep{n}.srt" for n in (1, 2, 3)]
            assert _tier(store, "arrivals") == []
        else:
            assert _tier(store, "arrivals") == [f"Library/{show}/ep3.srt"] and len(_current(store)) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_item_of_video_key_reads_the_pairings_once_while_nothing_is_written(language):
    """Review H17: K1b asks once per video it finds (2,000 on a big first scan); each ask scanning every origin's
    record made a first scan quadratic. The answers come from one read, read again after any write, its contract
    kept: the lowest live id, a waiting item left out, a removed one gone, another connection's write seen."""
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        a = store.take_in(root, [_found(language, data_dir, src, w[113], "ep1.srt", 1, video_key="v1-h17a")],
                          first=True).added[0]
        twin = store.take_in(root, [_found(language, data_dir, src, w[113], "ep1b.srt", 2, video_key="v1-h17a")],
                             first=True).added[0]
        video = os.path.join(src, w[114], "ep1.mkv")
        os.makedirs(os.path.dirname(video))
        with open(video, "wb") as fh:
            fh.write(b"\x1aE\xdf\xa3" + bytes(60))
        store.take_in(root, [{"origin": video, "size": 64, "mtime_ns": 1, "show": w[114], "video_path": video,
                              "video_size": 64, "video_key": "v1-h17w", "rel": f"Library/{w[114]}/ep1.mkv"}])
        reads = []
        store.conn.set_trace_callback(lambda sql: reads.append(sql) if "pairings" in sql else None)
        try:
            for _ in range(50):
                assert store.item_of_video_key("v1-h17a") == min(a, twin)
                assert store.item_of_video_key("v1-h17w") is None                   # waiting: left out
                assert store.item_of_video_key("v1-none") is None
        finally:
            store.conn.set_trace_callback(None)
        assert len(reads) == 1, reads
        store.remove([min(a, twin)])
        assert store.item_of_video_key("v1-h17a") == max(a, twin), "a write in between is seen"
        other = ls.open_store(language, data_dir, user_files_dir)
        with other:
            other.remove([max(a, twin)])
        assert store.item_of_video_key("v1-h17a") is None, "another connection's write is seen"


@pytest.mark.parametrize("language", LANGUAGES)
def test_take_in_never_reads_a_file_whose_origin_is_already_recorded(language, monkeypatch):
    """Review H19: a file the look hands over again is skipped as known; preparing it first (its stat, and the read
    of its source mark) was waste on every such file. Known origins are skipped before anything is read."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[115]
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, show, "ep1.srt", 1)
        store.take_in(root, [f], first=True)
        g = _found(language, data_dir, src, show, "ep2.srt", 2)
        read = []
        real = ls._detect_source_type
        monkeypatch.setattr(ls, "_detect_source_type", lambda path, cache=None: read.append(path) or real(path, cache))
        change = store.take_in(root, [dict(f), g])
        assert change.skipped["known"] == [os.path.abspath(f["origin"])] and change.unused == []
        assert [os.path.basename(p) for p in read] == ["ep2.srt"], "only the new file is read"


# --- the performance round (SRC batch 1, the smoothness register) --------------------------------------------------- #

def _all_rows(conn):
    """Every row of every table, in a fixed order: what an index may never change."""
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
        out[name] = conn.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
    return out


def _has_pairings_index(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'pairings_item'").fetchone())


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_made_before_the_pairings_index_gets_it_at_open_and_nothing_else_changes(language):
    """An item's records are read by `pairings(item_id)`; without it, every take-in placed each file by scanning
    every origin once per row of its show (a first scan's batch held the write lock for seconds, a window move waited
    behind it). The index changes no data and no schema version (an older Surasura reads the store as it was): a new
    store is made with it, one made before gets it at its first open by a writer — and comes out the same otherwise:
    the same rows, the same copy, byte for byte, the same version, integrity ok."""
    import sqlite3
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    src = _source_root()
    show = names(language)[120]
    with store:
        assert _has_pairings_index(store.conn), "a new store has it"
        root = store.add_source(src)
        store.take_in(root, [_found(language, data_dir, src, show, f"ep{n}.srt", n, episode=n) for n in (1, 2, 3)],
                      first=True)
        ls.export_copy(store)
    db = ls.library_db_path(language, data_dir)
    raw = sqlite3.connect(db)
    raw.execute("DROP INDEX pairings_item")                                   # the store as an older build made it
    raw.commit()
    rows, version = _all_rows(raw), raw.execute("PRAGMA user_version").fetchone()[0]
    raw.close()
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        copy = f.read()
    reader = ls.Store(db, language, data_dir, user_files_dir, role="reader")
    try:
        assert not _has_pairings_index(reader.conn), "a reader never writes, not even the index"
    finally:
        reader.close()
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        assert _has_pairings_index(store.conn)
        assert _all_rows(store.conn) == rows
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == version == ls.STORE_SCHEMA
        assert store.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert ls.export_copy(store) is False, "nothing for the copy to say"
        doc, _version, _dirty = store.export_snapshot()
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        assert f.read() == copy
    held = json.loads(copy.decode("utf-8"))["surasura_library"]
    assert doc["surasura_library"]["tables"] == held["tables"], "the copy written again holds the same rows"
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        assert f.read() == copy
    rang = []                                                                 # every commit rings the windows
    real = ls.library_watch.ring
    ls.library_watch.ring = lambda db: rang.append(db) or real(db)
    try:
        ls.open_store(language, data_dir, user_files_dir).close()
    finally:
        ls.library_watch.ring = real
    assert rang == [], "an open of a store that has it writes nothing"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_items_records_are_read_through_the_pairings_index(language):
    """The reads that place a file in its show's run (`_episodes_of`, `_PREFERRED_ROW`'s check for another
    record) look an item's records up by the index — never a scan of every record per row."""
    store, _data_dir = _empty(language)
    with store:
        sql = f"SELECT p.item_id, p.pairing FROM pairings p WHERE p.item_id IN (?, ?) AND {ls._PREFERRED_ROW}"
        plan = " | ".join(r[-1] for r in store.conn.execute("EXPLAIN QUERY PLAN " + sql, (1, 2)).fetchall())
        assert "pairings_item" in plan and "SCAN q" not in plan and "SCAN p" not in plan, plan


@pytest.mark.parametrize("language", LANGUAGES)
def test_take_in_reads_a_shows_episode_numbers_once_a_batch(language):
    """Placing each file of a batch in its show's run read the episode number of every row of the run again —
    per file, so a long show's batch was quadratic. Now once a batch (a new item's number is its record's), the
    order the same: K4's numbers decide where names don't sort, and an item given an origin in the batch is read
    again."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[121]
    ep = lambda n: _found(language, data_dir, src, show, f"x{9 - n}.srt", n, episode=n)   # noqa: E731
    with store:
        root = store.add_source(src)
        store.take_in(root, [ep(n) for n in (2, 4, 6)], first=True)
        reads, runs = [], []
        store.conn.set_trace_callback(lambda s: reads.append(s) if "p.item_id IN" in s else
                                      runs.append(s) if "rel_path FROM items WHERE work_id" in s else None)
        try:
            store.take_in(root, [ep(n) for n in (1, 3, 5, 7, 8)], first=True)
        finally:
            store.conn.set_trace_callback(None)
        assert len(reads) == 1, reads                                          # the three rows there before, once
        assert len(runs) == 1, runs                                            # and the show's run, once
        assert _current(store) == [f"Library/{show}/x{9 - n}.srt" for n in range(1, 9)]
        other = names(language)[122]
        store.take_in(root, [_found(language, data_dir, src, other, "z.srt", 11),            # no number yet
                             _found(language, data_dir, src, other, "d.srt", 13, episode=3)], first=True)
        z = store.conn.execute("SELECT id FROM items WHERE rel_path = ?", (f"Library/{other}/z.srt",)).fetchone()[0]
        # one batch: c (ep 2) placed, ep 4 recorded on z's item (its number now 4), then h (ep 5) placed after it
        store.take_in(root, [_found(language, data_dir, src, other, "c.srt", 12, episode=2),
                             dict(_found(language, data_dir, src, other, "z4.srt", 14, copy=False), episode=4,
                                  item_id=z),
                             _found(language, data_dir, src, other, "h.srt", 15, episode=5)], first=True)
        assert [p for p in _current(store) if f"/{other}/" in p] == [f"Library/{other}/{n}.srt" for n in "cdzh"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_looks_video_map_is_read_once_and_hatos_pairing_is_asked_at_its_row(language):
    """A look asks for every video it finds; the origins' videos come from one read it keeps up to date, and a
    video hato pairs meanwhile is found at its own row — the lowest live id either way, a waiting item never."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        a = store.take_in(root, [_found(language, data_dir, src, w[123], "ep1.srt", 1, video_key="v1-f2a")],
                          first=True).added[0]
        video = os.path.join(src, w[124], "ep1.mkv")
        os.makedirs(os.path.dirname(video))
        with open(video, "wb") as fh:
            fh.write(b"\x1aE\xdf\xa3" + bytes(60))
        store.take_in(root, [{"origin": video, "size": 64, "mtime_ns": 1, "show": w[124], "video_path": video,
                              "video_size": 64, "video_key": "v1-f2w", "rel": f"Library/{w[124]}/ep1.mkv"}])
        held = store.origin_videos()
        assert held == {"v1-f2a": a}, "the waiting video is no item's"
        assert store.item_of_video_key("v1-f2a", origins=held) == a
        assert store.item_of_video_key("v1-f2w", origins=held) is None
        hato_file = os.path.join(data_dir, "HighPriority", "Hato", f"{w[125]}.srt")
        os.makedirs(os.path.dirname(hato_file))
        with open(hato_file, "w", encoding="utf-8") as fh:
            fh.write(_episode_text(language, 3))
        paired = store.register(hato_file, _hato("v1-f2h", 3, w[125])).added[0]
        assert store.item_of_video_key("v1-f2h", origins=held) == paired, "hato's pairing, made after the read"
        assert store.item_of_video_key("v1-f2h", origins={"v1-f2h": paired + 10}) == paired, "the lowest id"
        assert store.item_of_video_key("v1-f2h", origins={"v1-f2h": a}) == min(a, paired)
        assert store.item_of_video_key(ls.origin_key(video), origins=held) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_sources_counts_their_items_without_a_grouped_read_and_a_look_asks_for_none(language):
    """`sources()` counts each source's items (the offline line) — an item with two origins in one source once,
    one in two sources in each; `counts=False` (a look, Connect's index) reads the roots alone."""
    store, data_dir = _empty(language)
    src, other = _source_root("a"), _source_root("b")
    show = names(language)[126]
    with store:
        one, two = store.add_source(src), store.add_source(other)
        item = store.take_in(one, [_found(language, data_dir, src, show, "ep1.srt", 1),
                                   _found(language, data_dir, src, show, "ep2.srt", 2)], first=True).added[0]
        store.take_in(one, [dict(_found(language, data_dir, src, show, "ep1b.srt", 1, copy=False), item_id=item)])
        store.take_in(two, [dict(_found(language, data_dir, other, show, "ep1.srt", 1, copy=False), item_id=item)])
        assert [(s["id"], s["items"]) for s in store.sources()] == [(one, 2), (two, 1)]
        reads = []
        store.conn.set_trace_callback(reads.append)
        try:
            listed = store.sources(all=True, counts=False)
        finally:
            store.conn.set_trace_callback(None)
        assert [s["id"] for s in listed] == [one, two] and not [s for s in reads if "pairings" in s]


@pytest.mark.parametrize("language", LANGUAGES)
def test_take_in_keeps_the_waiting_videos_between_its_batches_while_nothing_else_writes(language):
    """Every batch of a look read every origin's record for the videos still waiting for their subtitle (22 ms a
    batch, under the write lock, at 20k origins). Now one read, kept by take_in itself from batch to batch — and read
    again after anyone else's write: a video another handle's look left waiting meanwhile is filled by its subtitle,
    never a second item."""
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    src = _source_root()
    show = names(language)[127]

    def video(n):
        path = os.path.join(src, show, f"ep{n}.mkv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"\x1aE\xdf\xa3" + bytes([n]) * 60)
        return {"origin": path, "size": 64, "mtime_ns": 1, "show": show, "video_path": path, "video_size": 64,
                "video_key": f"v1-f4w{n}", "rel": f"Library/{show}/ep{n}.mkv"}
    with store:
        root = store.add_source(src)
        waiting = store.take_in(root, [video(n) for n in (1, 2, 3)]).added
        reads = []
        store.conn.set_trace_callback(lambda s: reads.append(s) if "availability = 'waiting'" in s else None)
        try:
            one = store.take_in(root, [_found(language, data_dir, src, show, "ep1.srt", 1, video_key="v1-f4w1")])
            assert one.attached == [waiting[0]] and not one.added and reads == [], "the videos' own batch left them"
            two = store.take_in(root, [_found(language, data_dir, src, show, "ep2.srt", 2, video_key="v1-f4w2")])
            assert two.attached == [waiting[1]] and reads == [], "nor the next"
            other = ls.open_store(language, data_dir, user_files_dir)
            with other:
                four = other.take_in(root, [video(4)]).added                  # another handle's look meanwhile
            three = store.take_in(root, [_found(language, data_dir, src, show, "ep4.srt", 4, video_key="v1-f4w4")])
        finally:
            store.conn.set_trace_callback(None)
        assert len(reads) == 1, "read again after another connection's write"
        assert three.attached == four and not three.added, "its waiting row filled, never a second item"
        avail = dict(store.conn.execute("SELECT id, availability FROM items").fetchall())
        assert avail[waiting[0]] == avail[waiting[1]] == avail[four[0]] == "available"
        assert avail[waiting[2]] == "waiting"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("then", ("alone", "after_a_new_item", "after_a_new_waiting_video"))
def test_a_take_in_rolled_back_inside_an_outer_write_leaves_no_waiting_video_behind(language, then):
    """P1 (perf review): take_in kept its copy of the waiting videos for the next batch even inside an outer write. A
    rollback moves neither of the copy's stamps and the ids come round again, so the copy named a row that no longer
    existed: every later take-in of that video failed — or a new item that took the id in the same batch was 'filled'
    with the subtitle, its own copy no longer held. Now the copy is kept only when take_in is the outermost write, and a
    gap whose row is no longer a waiting one is no gap: the subtitle is an item of its own, every item its own copy."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[130]

    def video(n, **more):
        path = os.path.join(src, show, f"ep{n}.mkv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"\x1aE\xdf\xa3" + bytes([n]) * 60)
        return dict({"origin": path, "size": 64, "mtime_ns": 1, "show": show, "video_path": path, "video_size": 64,
                     "video_key": f"v1-p1w{n}", "rel": f"Library/{show}/ep{n}.mkv"}, **more)
    with store:
        root = store.add_source(src)
        waiting = store.take_in(root, [video(1)]).added
        with pytest.raises(RuntimeError):
            with store._writing():
                store.take_in(root, [video(2)])
                raise RuntimeError("the outer write fails: all of it rolled back")
        assert [r[0] for r in store.conn.execute("SELECT id FROM items")] == waiting
        batch = [_found(language, data_dir, src, show, "ep2.srt", 2, video_key="v1-p1w2", episode=2)]
        if then == "after_a_new_item":                      # sorted first: it takes the id the rolled-back row had
            batch.insert(0, _found(language, data_dir, src, show, "x1.srt", 9, episode=1))
        elif then == "after_a_new_waiting_video":           # the same id, and a waiting row: never filled for ep2
            batch.insert(0, video(5, episode=1))
        change = store.take_in(root, batch)
        assert len(change.added) == len(batch) and change.attached == []
        rows = dict(store.conn.execute("SELECT id, rel_path FROM items").fetchall())
        assert sorted(rows[i] for i in change.added) == sorted(f["rel"] for f in batch)
        if then == "after_a_new_waiting_video":
            assert store.conn.execute("SELECT availability FROM items WHERE rel_path = ?",
                                      (batch[0]["rel"],)).fetchone()[0] == "waiting"
        assert store.conn.execute("SELECT availability FROM items WHERE id = ?", (waiting[0],)).fetchone()[0] == \
            "waiting"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("named", ("gone", "not_waiting"))
def test_a_waiting_videos_copy_naming_a_row_that_is_no_gap_any_more_fills_nothing(language, named):
    """P1, the fill itself: a waiting videos' copy that names a row gone, or one no longer waiting (another item's),
    fills nothing — the subtitle is an item of its own, the other item untouched."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[132]
    with store:
        root = store.add_source(src)
        other = store.take_in(root, [_found(language, data_dir, src, show, "ep1.srt", 1, episode=1)]).added[0]
        stale = other if named == "not_waiting" else other + 50
        store._gaps = ((store.conn.total_changes, store.conn.execute("PRAGMA data_version").fetchone()[0]),
                       {"v1-p1stale": stale})
        change = store.take_in(root, [_found(language, data_dir, src, show, "ep2.srt", 2, episode=2,
                                             video_key="v1-p1stale")])
        assert len(change.added) == 1 and change.attached == []
        assert store.item(other)["rel_path"] == f"Library/{show}/ep1.srt"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_origin_whose_record_is_not_a_json_object_reads_as_one_with_no_fields(language):
    """`origins()` reads the records' fields in SQLite now (F13): a record that is not JSON, or not an object, still
    reads as an origin with no fields — never an error that would end every look."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[133]
    with store:
        root = store.add_source(src)
        ids = store.take_in(root, [_found(language, data_dir, src, show, f"ep{n}.srt", n) for n in (1, 2, 3)]).added
        keys = [k for (k,) in store.conn.execute("SELECT content_key FROM pairings ORDER BY content_key")]
        good = store.origins()
        with store._writing():
            store.conn.execute("UPDATE pairings SET pairing = 'not json' WHERE content_key = ?", (keys[0],))
            store.conn.execute("UPDATE pairings SET pairing = '[1, 2]' WHERE content_key = ?", (keys[1],))
        read = store.origins()
        assert set(read) == set(good) and sorted(o.item_id for o in read.values()) == sorted(ids)
        for k in keys[:2]:
            o = read[k[len(ls.SOURCE_KEY):]]
            assert (o.root, o.origin, o.size, o.mtime_ns, o.sha256) == (None,) * 5 and o.rel_path
        assert read[keys[2][len(ls.SOURCE_KEY):]] == good[keys[2][len(ls.SOURCE_KEY):]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_file_of_a_show_still_waiting_reads_none_of_its_records(language):
    """The folders' rule (after-show) placed each later file by reading every record of its show first — under
    the write lock, per file — even for a show with nothing in Current, Finished or 6+ Months, which it never
    places. Such a file waits in New arrivals as before, its show's records unread; a show in Current is still read
    and placed in order."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[128]
    ep = lambda n: _found(language, data_dir, src, show, f"ep{n}.srt", n, episode=n)   # noqa: E731
    with store:
        root = store.add_source(src)
        store.take_in(root, [ep(1), ep(2)])                                   # never shown: they wait
        reads = []
        store.conn.set_trace_callback(lambda s: reads.append(s) if "SELECT id FROM items WHERE work_id" in s else None)
        try:
            store.take_in(root, [ep(3), ep(4)])
        finally:
            store.conn.set_trace_callback(None)
        assert reads == [] and _tier(store, "arrivals") == [f"Library/{show}/ep{n}.srt" for n in (1, 2, 3, 4)]
        other = names(language)[129]
        store.take_in(root, [_found(language, data_dir, src, other, f"ep{n}.srt", n + 20, episode=n)
                             for n in (1, 3)], first=True)
        store.take_in(root, [_found(language, data_dir, src, other, "ep2.srt", 22, episode=2)])
        assert [p for p in _current(store) if f"/{other}/" in p] == [f"Library/{other}/ep{n}.srt" for n in (1, 2, 3)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_added_inside_another_source_counts_the_episodes_under_it(language):
    """Item 8b (the laptop's *0 episodes*): a source's count is its folder's — the live items with an origin under that
    folder, whichever source recorded them. A show's folder added after the folder around it was read (and stopped)
    counts the episodes the outer one took in; the outer one, stopped, still counts them; a folder whose name only
    starts the same (`<show>` beside `<show> S2`) counts none of them; a removed episode counts nowhere."""
    store, data_dir = _empty(language)
    downloads = _source_root("Downloads")
    near = names(language)[141]
    show = f"{near} S2"
    with store:
        outer = store.add_source(downloads)
        ids = store.take_in(outer, [_found(language, data_dir, downloads, show, f"[Grp] {show} - {n:02d} (1080p).srt",
                                           n) for n in (9, 10, 11)], first=True).added
        os.makedirs(os.path.join(downloads, near))
        store.stop_source(outer)
        inner = store.add_source(os.path.join(downloads, show))
        beside = store.add_source(os.path.join(downloads, near))
        assert [(s["id"], s["items"]) for s in store.sources()] == [(inner, 3), (beside, 0)]
        assert [(s["id"], s["items"]) for s in store.sources(all=True)] == [(outer, 3), (inner, 3), (beside, 0)]
        store.remove([ids[0]])
        assert [(s["id"], s["items"]) for s in store.sources(all=True)] == [(outer, 2), (inner, 2), (beside, 0)]


# --- D5 (the moves scope §4, Kura's half; PROVISIONAL): an original that moved marks its old record --------------- #
# Why: after a show's folder moves from one folder Surasura reads to another, its items hold two origin records — the
# old one dead. The old folder's line must not keep counting episodes that left it, and Connect must be able to tell
# the live record from the dead one (Michi's half orders the marked one last). The mark is a field in the old record,
# never a deleted record: it goes again when the file is back.

def _scanned_show(language, a, show, count=4):
    from tests.test_sources_scan import _settle, _text, _write
    for n in range(1, count + 1):
        _write(os.path.join(a, show, f"[Grp] {show} - {n:02d}.{language}.srt"), _text(language, n))
    _settle(a)
    return [os.path.join(a, show, f"[Grp] {show} - {n:02d}.{language}.srt") for n in range(1, count + 1)]


def _moved_to(store, path):
    return store.origins()[ls.path_key(os.path.abspath(path))].moved_to


def _counts(store):
    return [s["items"] for s in store.sources(all=True)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_moved_original_marks_its_old_record_and_the_old_folder_no_longer_counts_it(language):
    """The show's folder cut from A and pasted into B: A's records say where each original went, A counts 0 and B 4;
    the records stay (nothing deleted) and Connect's record never carries the mark. Connect reads the live origin's
    record (M4c, D5: `pairing_of` live first), so its pairing version moves once: the fit is checked once at B."""
    from tests.test_sources_scan import _look, _settle
    store, data_dir = _empty(language)
    show = names(language)[71]
    a, b = _source_root("driveA"), _source_root("driveB")
    old = _scanned_show(language, a, show)
    with store:
        root_a = store.add_source(a)
        ids = _look(store, language, root_a, first=True)["ids"]
        versions = {i: fit_check.version(connect_library.pairing_of(store, i)) for i in ids}
        shutil.move(os.path.join(a, show), os.path.join(b, show))
        _settle(b)
        root_b = store.add_source(b)
        assert _look(store, language, root_b)["attached"] == 4
        assert _counts(store) == [0, 4]
        for path in old:
            assert _moved_to(store, path) == ls.path_key(os.path.abspath(os.path.join(b, show,
                                                                                      os.path.basename(path))))
            assert _moved_to(store, os.path.join(b, show, os.path.basename(path))) is None
        assert len(store.origins()) == 8
        for i in ids:
            record = connect_library.pairing_of(store, i)
            assert "moved_to" not in record and fit_check.version(record) != versions[i]
            assert os.path.normcase(record["origin"]).startswith(os.path.normcase(os.path.join(b, show))), "B's"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_old_folder_offline_marks_nothing(language):
    """A's drive unplugged while B holds the same files: nothing says A's originals moved (they may be on the drive) —
    A keeps counting its episodes (*its 4 episodes are kept*)."""
    from tests.test_sources_scan import _look, _settle
    store, data_dir = _empty(language)
    show = names(language)[71]
    a, b = _source_root("driveA"), _source_root("driveB")
    old = _scanned_show(language, a, show)
    with store:
        _look(store, language, store.add_source(a), first=True)
        shutil.copytree(os.path.join(a, show), os.path.join(b, show), copy_function=shutil.copy2)
        _settle(b)
        os.rename(a, a + " (unplugged)")
        try:
            assert _look(store, language, store.add_source(b))["attached"] == 4
            assert _counts(store) == [4, 4] and all(_moved_to(store, p) is None for p in old)
        finally:
            os.rename(a + " (unplugged)", a)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_original_back_in_its_old_place_clears_the_mark(language):
    """Moved to B, then copied back into A: A's look lists the originals again — the mark goes, A counts them again."""
    from tests.test_sources_scan import _look, _settle
    store, data_dir = _empty(language)
    show = names(language)[71]
    a, b = _source_root("driveA"), _source_root("driveB")
    old = _scanned_show(language, a, show)
    with store:
        root_a = store.add_source(a)
        _look(store, language, root_a, first=True)
        shutil.move(os.path.join(a, show), os.path.join(b, show))
        _settle(b)
        _look(store, language, store.add_source(b))
        assert _counts(store) == [0, 4]
        shutil.copytree(os.path.join(b, show), os.path.join(a, show), copy_function=shutil.copy2)
        _settle(a)
        _look(store, language, root_a, full=True)
        assert _counts(store) == [4, 4] and all(_moved_to(store, p) is None for p in old)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_not_a_move_marks_nothing(language):
    """The show copied to B (A's files still there): both folders hold it, both count it, no record is marked."""
    from tests.test_sources_scan import _look, _settle
    store, data_dir = _empty(language)
    show = names(language)[71]
    a, b = _source_root("driveA"), _source_root("driveB")
    old = _scanned_show(language, a, show)
    with store:
        _look(store, language, store.add_source(a), first=True)
        shutil.copytree(os.path.join(a, show), os.path.join(b, show), copy_function=shutil.copy2)
        _settle(b)
        assert _look(store, language, store.add_source(b))["attached"] == 4
        assert _counts(store) == [4, 4]
        assert all(o.moved_to is None for o in store.origins().values()) and len(old) == 4


@pytest.mark.parametrize("language", LANGUAGES)
def test_take_in_marks_only_its_own_items_live_records(language):
    """`take_in` checks again, inside its write: a `moved_from` naming another item's record, or one marked already,
    is left as it is."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        f = _found(language, data_dir, src, w[69], "ep1.srt", 1)
        g = _found(language, data_dir, src, w[70], "ep2.srt", 2)
        first = store.take_in(root, [f, g], first=True).recorded[os.path.abspath(f["origin"])]
        h =_found(language, data_dir, src, w[69], "moved/ep1.srt", 1, copy=False, item_id=first,
                   moved_from=[ls.path_key(os.path.abspath(g["origin"])), ls.path_key(os.path.abspath(f["origin"]))])
        store.take_in(root, [h])
        assert _moved_to(store, f["origin"]) == ls.path_key(os.path.abspath(h["origin"]))
        assert _moved_to(store, g["origin"]) is None
        k = _found(language, data_dir, src, w[69], "again/ep1.srt", 1, copy=False, item_id=first,
                   moved_from=[ls.path_key(os.path.abspath(f["origin"]))])
        store.take_in(root, [k])
        assert _moved_to(store, f["origin"]) == ls.path_key(os.path.abspath(h["origin"]))
        assert "moved_from" not in json.loads(store.conn.execute(
            "SELECT pairing FROM pairings WHERE content_key = ?", (ls.origin_key(h["origin"]),)).fetchone()[0])
