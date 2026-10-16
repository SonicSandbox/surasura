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


@pytest.mark.parametrize("name", [".hidden", ".stversions", ".trash", "$RECYCLE.BIN", "$Recycle.Bin", "#recycle",
                                  "@eaDir", "System Volume Information"])
def test_the_walk_skips_hidden_recycled_and_old_version_folders(name, tmp_path):
    """B3: Syncthing's .stversions, the recycle bins (Windows' and a NAS's), a NAS's @eaDir thumbnails and the trash
    hold removed or old versions: read, they would bring back episodes removed on purpose."""
    folder = tmp_path / name
    folder.mkdir()
    assert ls.skip_dir(name, str(folder)) is True


@pytest.mark.parametrize("name", ["フリーレン", "夜市", "Season 1", "Specials", "第2期"])
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
        moved = dict(f, origin=shutil.copyfile(f["origin"], os.path.join(src, "moved.srt")))
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
        shutil.copyfile(f["origin"], hato_file)
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
