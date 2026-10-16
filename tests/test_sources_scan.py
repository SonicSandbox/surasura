"""3.0's Sources, the scan (SRC K1b, the RUNBOOK's §1b): a look at a folder Surasura reads where it is — every new text
copied into the data folder's `Library/<show>/` and handed to the store's `take_in`, never a duplicate (SRC-7: a video
already paired, the same bytes, one subtitle per video per language, a v2 being its episode), a removed item never
brought back (S6), a changed original followed with its old copy kept in the trash (S5), only what changed listed
again (S4), an EPUB split once (S11), an unreachable folder left alone (SRC-3); the cadence (SRC-9) and the local /
network split the shell's watching reads (D5).

Why these matter: the scan writes the user's library. A copy made twice floods a show with duplicates; a removed
episode coming back undoes his Remove; a re-copy that loses the old text, or writes an empty or half-written file over
a good copy, loses words he already read; and a scan that wrote anything into his own folders would touch files that
are his alone. So every scan here runs through `_look`, which proves both source roots ("two drives", temp folders
beside the test's data folder) byte-identical before and after. Every test uses real Japanese or Chinese subtitles and
texts from tests/Test Resources/, made-up show names, and a few bytes as a fake video.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from app import library_store as ls
from app import sources
from app.connect import videos
from tests.test_library_store_support import LANGUAGES, RESOURCES, library, write_manifest

# Real text per language (each episode told apart by a numbered line appended)
_TEXTS = {"ja": ("placed_episode.srt", "library_episode.ass", "phrases_sample.srt", "context_test.txt"),
          "zh": ("night_market.srt", "chinese_text_1.txt", "traditional_news.txt", "context_test.txt")}
_SHOWS = {"ja": ("月影の旅人", "Hoshizora Kissa"), "zh": ("夜市小记", "Lanterns of Qinghe")}   # made-up show names
_OURS = {"ja": "ja", "zh": "zh"}
_OTHER = {"ja": "zh", "zh": "ja"}


@pytest.fixture(autouse=True)
def _fresh_module_state():
    """Each test starts as a new run of the app: no look made yet this run, no scan running."""
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


# --- helpers ------------------------------------------------------------------------------------------------------- #

def _drive(name):
    """A second "drive": a temp folder beside the test's data folder, never inside it."""
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", name)
    os.makedirs(path, exist_ok=True)
    return path


def _text(language, n, extra=""):
    base = _TEXTS[language][n % len(_TEXTS[language])]
    with open(os.path.join(RESOURCES, language, base), encoding="utf-8") as f:
        return f.read() + f"\n{n}{extra}\n"


def _write(path, text, age=60):
    """A file in a source folder, its time `age` seconds back (settled: older than the half-written wait)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if age:
        t = time.time() - age
        os.utime(path, (t, t))
    return path


def _video(path, body=b"\x1a\x45\xdf\xa3 fake matroska ", age=60):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(body)
    t = time.time() - age
    os.utime(path, (t, t))
    return path


def _empty(language):
    """A 3.0 library with nothing in it yet (setup's start): the Soon line at 25, New arrivals on."""
    data_dir, user_files_dir, doc = library(language, shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return ls.open_store(language, data_dir, user_files_dir), data_dir


def _tree(root):
    """Every folder and file under `root`: (rel, bytes' sha256, size, mtime_ns) — the source's state."""
    out = []
    for where, dirs, files in os.walk(root):
        dirs.sort()
        rel = os.path.relpath(where, root)
        out.append((rel, None, None, os.stat(where).st_mtime_ns))
        for name in sorted(files):
            p = os.path.join(where, name)
            with open(p, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            st = os.stat(p)
            out.append((os.path.join(rel, name), digest, st.st_size, st.st_mtime_ns))
    return out


def _look(store, language, root, **kw):
    """`sources.scan`, proving nothing under either source drive was written, renamed, touched or added."""
    drives = [os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere")]
    before = [_tree(d) for d in drives if os.path.isdir(d)]
    result = sources.scan(store, language, root, **kw)
    after = [_tree(d) for d in drives if os.path.isdir(d)]
    assert before == after, "the scan wrote under a source folder"
    return result


def _library_files(data_dir):
    top = os.path.join(data_dir, ls.CONTENT_FOLDER)
    out = []
    for where, _d, files in os.walk(top):
        for name in files:
            out.append(os.path.relpath(os.path.join(where, name), data_dir).replace("\\", "/"))
    return sorted(out)


def _current(store):
    return [e["physical_path"] for t in ("now", "soon") for _i, e, _a in store.ordered(t)]


def _items(store):
    return store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _cache(language):
    with open(sources.cache_path(language), encoding="utf-8") as f:
        return json.load(f)


class _ScandirSpy:
    """Records every folder the scan's own `os.scandir` lists (S4: an unchanged folder is never listed again) — not
    the test's own walks of the source drives."""

    def __init__(self, monkeypatch):
        self.listed = []
        real = os.scandir

        def spy(path="."):
            if os.path.samefile(sys._getframe(1).f_code.co_filename, sources.__file__):
                self.listed.append(os.path.normcase(os.path.abspath(os.fspath(path))))
            return real(path)
        monkeypatch.setattr(os, "scandir", spy)

    def saw(self, path):
        return os.path.normcase(os.path.abspath(path)) in self.listed


# --- the first look, later looks (SRC-1, SRC-2, SRC-4) ------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_first_scan_copies_each_episode_into_library_by_show_and_lands_it_in_current(language):
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    for n in (2, 1, 10):
        _write(os.path.join(src, a, f"{a} - {n:02d}.srt"), _text(language, n))
    _write(os.path.join(src, b, "notes.txt"), _text(language, 3))
    calls = []
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True, progress=lambda f, s: calls.append((f, s)))
        assert result["reachable"] is True
        assert (result["found"], result["shows"], result["added"], result["attached"]) == (4, 2, 4, 0)
        assert _library_files(data_dir) == sorted([f"Library/{a}/{a} - 01.srt", f"Library/{a}/{a} - 02.srt",
                                                   f"Library/{a}/{a} - 10.srt", f"Library/{b}/notes.txt"])
        # every copy holds the original's bytes; Current holds them, each show's episodes in order
        for rel in _library_files(data_dir):
            show, name = rel.split("/")[1:]
            assert _sha(os.path.join(data_dir, rel)) == _sha(os.path.join(src, show, name))
        cur = _current(store)
        assert sorted(cur) == _library_files(data_dir)
        mine = [r for r in cur if f"/{a}/" in r]
        assert mine == [f"Library/{a}/{a} - 01.srt", f"Library/{a}/{a} - 02.srt", f"Library/{a}/{a} - 10.srt"]
        assert calls and calls[-1] == (4, 2)                                    # the setup line's last numbers


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_scan_copies_only_the_new_file_and_leaves_the_others_alone(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        copy = os.path.join(data_dir, "Library", a, "ep01.srt")
        before = os.stat(copy).st_mtime_ns
        _write(os.path.join(src, a, "ep02.srt"), _text(language, 2))
        result = _look(store, language, root)
        assert (result["added"], result["attached"]) == (1, 0)
        assert os.stat(copy).st_mtime_ns == before                              # never copied again
        assert _library_files(data_dir) == [f"Library/{a}/ep01.srt", f"Library/{a}/ep02.srt"]
        assert _current(store) == [f"Library/{a}/ep01.srt", f"Library/{a}/ep02.srt"]   # joined its show (SRC-2)
        again = _look(store, language, root, full=True)
        assert (again["added"], again["attached"]) == (0, 0) and _items(store) == 2


# --- S4: only what changed is listed again ------------------------------------------------------------------------- #

def test_an_unchanged_folder_is_not_listed_again_and_refresh_lists_everything(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    _write(os.path.join(src, b, "ep01.srt"), _text(language, 2))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)                                # the first look this run: all
        assert set(_cache(language)["roots"][str(root)]["dirs"])                # written after the commit
        _write(os.path.join(src, b, "ep02.srt"), _text(language, 3))           # b's folder time moves
        t = time.time() - 30
        os.utime(os.path.join(src, b), (t, t + 1))                              # (and surely differs)
        spy = _ScandirSpy(monkeypatch)
        result = _look(store, language, root)
        assert result["added"] == 1
        assert spy.saw(os.path.join(src, b)) and not spy.saw(os.path.join(src, a)) and not spy.saw(src)
        spy.listed.clear()
        _look(store, language, root, full=True)                                 # Refresh: every folder listed
        assert spy.saw(os.path.join(src, a)) and spy.saw(os.path.join(src, b)) and spy.saw(src)


def test_the_first_look_after_a_start_lists_everything_and_a_cache_of_another_store_is_dropped(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        cache = _cache(language)
        assert os.path.dirname(sources.cache_path(language)) == os.path.dirname(videos.index_path(language))
        assert (cache["store_id"], cache["epoch"]) == (store.meta()["store_id"], store.meta()["epoch"])
        sources._LOOKED.clear()                                                  # a new run of the app
        spy = _ScandirSpy(monkeypatch)
        _look(store, language, root)
        assert spy.saw(os.path.join(src, a))
        cache["epoch"] = int(cache["epoch"]) + 1                                 # a rebuilt store: the times are void
        with open(sources.cache_path(language), "w", encoding="utf-8") as f:
            json.dump(cache, f)
        spy.listed.clear()
        _look(store, language, root)
        assert spy.saw(os.path.join(src, a))


# --- SRC-3: an unreachable folder ---------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unreachable_folder_writes_nothing(language):
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        shutil.rmtree(src)                                                       # the drive is unplugged
        version = store.meta()["state_version"]
        result = sources.scan(store, language, root, first=True)
        assert result["reachable"] is False and result["added"] == 0
        assert store.meta()["state_version"] == version and _items(store) == 0
        assert not os.path.exists(os.path.join(data_dir, "Library"))
        assert not os.path.exists(sources.cache_path(language))
        assert store.sources()[0]["on"] is True                                  # nothing marked either


# --- the half-written wait ------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_written_in_the_last_seconds_waits_for_the_next_look(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1), age=0)   # still being written
    _settle(src)                                                                  # (only the file is new)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 0 and result["waiting"] == 1
        assert _library_files(data_dir) == [] and _items(store) == 0
        t = time.time() - 10
        os.utime(path, (t, t))                                                    # settled; its folder's time did not move
        result = _look(store, language, root)                                    # a quick look still lists that folder
        assert result["added"] == 1 and _library_files(data_dir) == [f"Library/{a}/ep01.srt"]


def test_a_file_that_changes_while_copied_is_not_taken_and_leaves_no_part(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    _settle(src)
    real = sources._copy_part

    def growing(origin, part):
        digest = real(origin, part)
        with open(origin, "a", encoding="utf-8") as f:                         # the downloader writes more
            f.write("続き\n")
        return digest
    monkeypatch.setattr(sources, "_copy_part", growing)
    with store:
        root = store.add_source(src)
        result = sources.scan(store, language, root, first=True)                # (the test itself writes the source)
        assert result["added"] == 0 and result["waiting"] == 1
        assert _library_files(data_dir) == [] and _items(store) == 0
        monkeypatch.setattr(sources, "_copy_part", real)
        t = time.time() - 10
        os.utime(path, (t, t))
        result = _look(store, language, root)
        assert result["added"] == 1
        assert _sha(os.path.join(data_dir, "Library", a, "ep01.srt")) == _sha(path)


def test_a_file_that_cannot_be_read_waits_and_the_look_goes_on(monkeypatch):
    """A file locked by another program (or gone) as it is read: that one waits, every other file is taken in."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    locked = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    _write(os.path.join(src, a, "ep02.srt"), _text(language, 2))
    _settle(src)
    real = ls.sha256_of

    def sha(p):
        if os.path.abspath(p) == os.path.abspath(locked):
            raise PermissionError(13, "in use by another program", p)
        return real(p)
    monkeypatch.setattr(ls, "sha256_of", sha)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], result["waiting"]) == (1, 1)
        assert _library_files(data_dir) == [f"Library/{a}/ep02.srt"]
        monkeypatch.setattr(ls, "sha256_of", real)
        assert _look(store, language, root)["added"] == 1                     # its folder is listed again


# --- S5: a changed original ----------------------------------------------------------------------------------------- #

def _trash(data_dir):
    folder = os.path.join(data_dir, ".trash")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_changed_original_is_copied_again_with_the_old_copy_kept_in_the_trash(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        copy = os.path.join(data_dir, "Library", a, "ep01.srt")
        old = open(copy, "rb").read()
        tier = store.item(item)["tier"]
        _write(path, _text(language, 1, extra="、修正版の字幕"), age=30)       # a corrected subtitle
        _write(os.path.join(src, a, "ep02.srt"), _text(language, 2))           # its folder is listed again
        quick = _look(store, language, root)                                    # S4: a quick look compares no stats
        assert quick["recopied"] == 0 and quick["added"] == 1 and open(copy, "rb").read() == old
        result = _look(store, language, root, full=True)
        assert result["recopied"] == 1 and result["added"] == 0
        assert _sha(copy) == _sha(path)
        trashed = _trash(data_dir)
        assert len(trashed) == 1 and open(os.path.join(data_dir, ".trash", trashed[0]), "rb").read() == old
        origin = store.origins()[ls.path_key(os.path.abspath(path))]
        assert (origin.item_id, origin.sha256, origin.size) == (item, _sha(path), os.path.getsize(path))
        assert store.item(item)["tier"] == tier and _items(store) == 2          # the item keeps its place
        assert not [n for n in os.listdir(os.path.dirname(copy)) if n.endswith(".part")]


def test_an_original_only_touched_keeps_its_copy_and_the_old_copy_goes_to_the_trash_on_a_fresh_clock():
    """Its time moved, its bytes didn't: the record takes the new time, nothing is copied or trashed. Then a real
    change: the trashed old copy's 30 days count from now, not from when the copy was made (else purged at once)."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        copy = os.path.join(data_dir, "Library", a, "ep01.srt")
        t = time.time() - 30
        os.utime(path, (t, t))
        result = _look(store, language, root, full=True)
        assert result["recopied"] == 0 and _trash(data_dir) == []
        assert store.origins()[ls.path_key(os.path.abspath(path))].mtime_ns == os.stat(path).st_mtime_ns
        old = time.time() - 40 * 86400
        os.utime(copy, (old, old))                                              # a copy made 40 days ago
        _write(path, _text(language, 1, extra="、修正版"), age=20)
        assert _look(store, language, root, full=True)["recopied"] == 1
        trashed = os.path.join(data_dir, ".trash", _trash(data_dir)[0])
        assert time.time() - os.stat(trashed).st_mtime < 60


@pytest.mark.parametrize("change", ["empty", "under half", "placeholder"])
def test_a_changed_original_is_never_followed_when_empty_much_smaller_or_a_placeholder(change, monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1) * 4)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        copy = os.path.join(data_dir, "Library", a, "ep01.srt")
        old = open(copy, "rb").read()
        if change == "empty":
            _write(path, "", age=30)
        elif change == "under half":
            _write(path, _text(language, 1)[:200], age=30)
        else:
            _write(path, _text(language, 1) * 5, age=30)
            size = os.path.getsize(path)
            monkeypatch.setattr(ls, "is_placeholder", lambda st: st.st_size == size)   # its download not here
        result = _look(store, language, root, full=True)
        assert result["recopied"] == 0 and open(copy, "rb").read() == old and _trash(data_dir) == []


def test_an_origin_attached_to_a_file_outside_library_never_rewrites_that_file():
    """A 2.x item (in HighPriority) whose bytes a source holds gets the origin recorded (check b); a later change of
    that original never rewrites the 2.x file — only copies in Library are Surasura's to re-copy (S5)."""
    language = "ja"
    data_dir, user_files_dir, doc = library(language, shows=1, episodes=1, loose=0, tiers=("now",))
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    rel = doc["schedule"][ls.TIERS["now"][0]][0]["physical_path"]
    old = open(os.path.join(data_dir, rel), "rb").read()
    src = _drive("driveA")
    path = os.path.join(src, "Show", "ep01.srt")
    os.makedirs(os.path.dirname(path))
    with open(path, "wb") as f:
        f.write(old)
    t = time.time() - 60
    os.utime(path, (t, t))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], result["attached"]) == (0, 1) and _library_files(data_dir) == []
        _write(path, _text(language, 1) * 3, age=30)
        result = _look(store, language, root, full=True)
        assert result["recopied"] == 0 and open(os.path.join(data_dir, rel), "rb").read() == old


# --- S6: removed stays removed ------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_item_is_never_copied_again_even_moved_renamed_or_on_another_drive(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        store.remove([item])                                                    # (its file is the caller's to trash)
        count, files = _items(store), _library_files(data_dir)
        assert _look(store, language, root, full=True)["added"] == 0
        renamed = os.path.join(src, a, "renamed.srt")
        os.rename(path, renamed)
        assert _look(store, language, root, full=True)["added"] == 0             # same bytes, new name
        moved = os.path.join(src, "elsewhere in it", "ep01.srt")
        os.makedirs(os.path.dirname(moved))
        os.rename(renamed, moved)
        assert _look(store, language, root, full=True)["added"] == 0             # same bytes, moved
        shutil.copyfile(moved, os.path.join(other, "ep01.srt"))
        second = store.add_source(other)
        assert _look(store, language, second, full=True)["added"] == 0           # same bytes, another drive
        _write(path, _text(language, 1, extra="、修正"), age=30)                  # new bytes at its own path: still out
        assert _look(store, language, root, full=True)["added"] == 0
        assert _current(store) == [] and store.ordered("arrivals") == []
        assert _items(store) == count and _library_files(data_dir) == files      # nothing copied again


# --- B2: a crash between the copy and its take_in ------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_crash_between_copy_and_take_in_leaves_a_copy_the_next_look_reuses(language, monkeypatch):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)

        def crash(*args, **kw):
            raise RuntimeError("the app was closed mid-scan")
        monkeypatch.setattr(store, "take_in", crash)
        with pytest.raises(RuntimeError):
            _look(store, language, root, first=True)
        assert _library_files(data_dir) == [f"Library/{a}/ep01.srt"] and _items(store) == 0
        assert not os.path.exists(sources.cache_path(language))                 # no times kept for an unfinished look
        del store.take_in                                                        # the next run
        result = _look(store, language, root, first=True)
        assert result["added"] == 1
        assert _library_files(data_dir) == [f"Library/{a}/ep01.srt"]             # re-used, never "ep01 (2).srt"
        assert _current(store) == [f"Library/{a}/ep01.srt"]


def test_a_copy_never_overwrites_a_file_that_appears_at_its_name_meanwhile(monkeypatch):
    """Another program writes a file at the copy's name between the look choosing it and the rename: that file is
    kept as it is and the episode waits (a rename that never overwrites)."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    other = os.path.join(data_dir, "Library", a, "ep01.srt")
    real = ls.content_target

    def raced(data_dir_, rel, size=None, sha256=None):
        out = real(data_dir_, rel, size, sha256)
        _write(other, _text(language, 5))                                        # it appears just then
        return out
    monkeypatch.setattr(ls, "content_target", raced)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], result["waiting"]) == (0, 1)
        assert open(other, encoding="utf-8").read() == _text(language, 5)
        assert _library_files(data_dir) == [f"Library/{a}/ep01.srt"]


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows' folder link")
def test_a_library_folder_that_links_elsewhere_is_never_written_through():
    """The data folder's Library turned into a link to another drive: the look writes nothing through it."""
    language = "ja"
    store, data_dir = _empty(language)
    src, landing = _drive("driveA"), _drive("driveB")
    _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"), _text(language, 1))
    import _winapi
    os.makedirs(data_dir, exist_ok=True)
    _winapi.CreateJunction(landing, os.path.join(data_dir, "Library"))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)                       # (_look: driveB untouched)
        assert result["added"] == 0 and result["waiting"] == 1 and _items(store) == 0


def test_a_different_file_of_the_same_name_already_there_gets_a_free_name():
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    stray = os.path.join(data_dir, "Library", a, "ep01.srt")
    _write(stray, _text(language, 2))
    stray_bytes = open(stray, "rb").read()
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1
        assert _current(store) == [f"Library/{a}/ep01 (2).srt"] and open(stray, "rb").read() == stray_bytes


# --- SRC-7: never a duplicate --------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_subtitle_of_a_video_already_in_is_that_episode_and_no_new_item(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    _video(os.path.join(src, a, "ep01.mkv"))
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    _video(os.path.join(other, a, "ep01.mkv"))                                   # the same video's bytes elsewhere
    _write(os.path.join(other, a, "ep01.srt"), _text(language, 1, extra=" 別の訳"))
    with store:
        root = store.add_source(src)
        first = _look(store, language, root, first=True)
        item = first["ids"][0]
        origin = store.origins()[ls.path_key(os.path.abspath(os.path.join(src, a, "ep01.srt")))]
        assert origin.item_id == item
        record = json.loads(store.conn.execute("SELECT pairing FROM pairings WHERE item_id = ?", (item,)).fetchone()[0])
        assert record["video_key"] == videos.content_key(os.path.join(src, a, "ep01.mkv"))
        second = store.add_source(other)
        result = _look(store, language, second)
        assert (result["added"], result["attached"]) == (0, 1) and _items(store) == 1
        assert store.origins()[ls.path_key(os.path.abspath(os.path.join(other, a, "ep01.srt")))].item_id == item
        assert _library_files(data_dir) == [f"Library/{a}/ep01.srt"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_same_bytes_found_again_are_that_item_and_never_copied(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        dup = os.path.join(other, "backup", "copy of ep01.srt")
        os.makedirs(os.path.dirname(dup))
        shutil.copy2(path, dup)
        result = _look(store, language, store.add_source(other))
        assert (result["added"], result["attached"]) == (0, 1) and _items(store) == 1
        assert store.origins()[ls.path_key(os.path.abspath(dup))].item_id == item
        assert _library_files(data_dir) == [f"Library/{a}/ep01.srt"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_subtitle_per_video_per_language_and_other_languages_skipped(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    ours, theirs = _OURS[language], _OTHER[language]
    src = _drive("driveA")
    folder = os.path.join(src, a)
    _video(os.path.join(folder, "ep01.mkv"))
    _write(os.path.join(folder, f"ep01.{ours}.ass"), _text(language, 1))
    _write(os.path.join(folder, f"ep01.{ours}.srt"), _text(language, 2))
    _write(os.path.join(folder, "ep01.srt"), _text(language, 3))
    _write(os.path.join(folder, "ep01.en.srt"), "1\n00:00:01,000 --> 00:00:02,000\nGood evening.\n")
    _write(os.path.join(folder, f"ep02.{theirs}.srt"), _text(_OTHER[language], 4))
    _write(os.path.join(folder, "ep03.srt"), _text(language, 5))
    _write(os.path.join(folder, f"ep03.{ours}.srt"), _text(language, 6))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 2
        assert _library_files(data_dir) == [f"Library/{a}/ep01.{ours}.ass", f"Library/{a}/ep03.{ours}.srt"]
        _write(os.path.join(folder, "ep01.ssa"), _text(language, 7))           # another later: still that episode
        again = _look(store, language, root, full=True)
        assert again["added"] == 0 and _items(store) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_v2_of_an_episode_already_in_is_that_episode_followed_as_a_changed_original(language):
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    v1 = _write(os.path.join(src, f"[Grp] {show} - 05 (1080p).{_OURS[language]}.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        copy = os.path.join(data_dir, *store.item(item)["rel_path"].split("/"))
        old = open(copy, "rb").read()
        v2 = _write(os.path.join(src, f"[Grp] {show} - 05v2 (1080p).{_OURS[language]}.srt"),
                    _text(language, 1, extra="、訂正"))
        result = _look(store, language, root)
        assert (result["added"], result["attached"], result["recopied"]) == (0, 1, 1) and _items(store) == 1
        assert _sha(copy) == _sha(v2) and store.origins()[ls.path_key(os.path.abspath(v2))].item_id == item
        assert open(os.path.join(data_dir, ".trash", _trash(data_dir)[0]), "rb").read() == old
        assert ls.path_key(os.path.abspath(v1)) in store.origins()


# --- S12 and the loose file's show ---------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_season_folder_gets_the_source_folders_name_in_front(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive(a)                                                              # the source is the show's folder
    _write(os.path.join(src, "Season 2", "ep01.srt"), _text(language, 1))
    _write(os.path.join(src, "Specials", "sp01.srt"), _text(language, 2))
    _write(os.path.join(src, "第2期", "ep01.srt"), _text(language, 3))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _library_files(data_dir) == sorted([f"Library/{a}/Season 2/ep01.srt", f"Library/{a}/Specials/sp01.srt",
                                                   f"Library/{a}/第2期/ep01.srt"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_loose_files_show_comes_from_its_name_else_the_source_folders(language):
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("Downloads")
    _write(os.path.join(src, f"[Grp] {show} - 03 (1080p) [ABCD1234].srt"), _text(language, 1))
    _write(os.path.join(src, "01.srt"), _text(language, 2))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _library_files(data_dir) == sorted([f"Library/{show}/[Grp] {show} - 03 (1080p) [ABCD1234].srt",
                                                   "Library/Downloads/01.srt"])


# --- B3: what a look skips ------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("folder", [".stversions", "$RECYCLE.BIN", "#recycle", "@eaDir", ".trash",
                                    "System Volume Information", ".hidden"])
def test_a_look_skips_the_folders_no_show_lives_in(folder):
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, folder, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 0 and _items(store) == 0


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows' folder link")
def test_a_look_never_follows_a_folder_link():
    language = "ja"
    store, data_dir = _empty(language)
    src, target = _drive("driveA"), _drive("driveB")
    _write(os.path.join(target, "Show", "ep01.srt"), _text(language, 1))
    import _winapi
    _winapi.CreateJunction(target, os.path.join(src, "link"))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 0 and _items(store) == 0


def test_a_look_never_follows_a_file_link(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    src, target = _drive("driveA"), _drive("driveB")
    real = _write(os.path.join(target, "ep01.srt"), _text(language, 1))
    try:
        os.symlink(real, os.path.join(src, "ep01.srt"))
    except OSError:
        pytest.skip("this system makes no file links for this user")
    read = []
    real_sha = ls.sha256_of
    monkeypatch.setattr(ls, "sha256_of", lambda p: read.append(p) or real_sha(p))
    monkeypatch.setattr(sources, "SETTLE_S", 0)                                  # (the link's own time is just now)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 0 and _items(store) == 0
        assert read == []                                                        # never even read


def test_a_cloud_placeholder_is_never_read_text_or_video(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    ghost_text = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    ghost_video = _video(os.path.join(src, a, "ep02.mkv"), body=b"\x1a\x45\xdf\xa3 not downloaded yet  ")
    _write(os.path.join(src, a, "ep02.srt"), _text(language, 2))
    sizes = {os.path.getsize(ghost_text), os.path.getsize(ghost_video)}
    monkeypatch.setattr(ls, "is_placeholder", lambda st: st.st_size in sizes)
    read = []
    real_key, real_sha = videos.content_key, ls.sha256_of
    monkeypatch.setattr(videos, "content_key", lambda p: read.append(p) or real_key(p))
    monkeypatch.setattr(ls, "sha256_of", lambda p: read.append(p) or real_sha(p))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 1 and _library_files(data_dir) == [f"Library/{a}/ep02.srt"]
        assert os.path.abspath(ghost_text) not in map(os.path.abspath, read)
        assert os.path.abspath(ghost_video) not in map(os.path.abspath, read)
        record = json.loads(store.conn.execute("SELECT pairing FROM pairings").fetchone()[0])
        assert "video_key" not in record


# --- S11: an EPUB --------------------------------------------------------------------------------------------------- #

def _epub(path, chapters):
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("src-k1b")
    book.set_title("星の歌")
    book.set_language("ja")
    items = []
    for n, body in enumerate(chapters, 1):
        c = epub.EpubHtml(title=f"第{n}章", file_name=f"c{n}.xhtml", lang="ja")
        c.content = f"<html><body>{body}</body></html>"
        book.add_item(c)
        items.append(c)
    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    os.makedirs(os.path.dirname(path), exist_ok=True)
    epub.write_epub(str(path), book)
    t = time.time() - 60
    os.utime(path, (t, t))
    return str(path)


def _chapters():
    with open(os.path.join(RESOURCES, "ja", "context_test.txt"), encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    return ["".join(f"<p>{ln}</p>" for ln in lines) * 6] * 3                    # about 2,500 characters: 2 parts


def test_an_epub_is_split_into_a_free_folder_once_all_parts_in_one_take_in(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", "星の歌.epub"), _chapters())
    taken = os.path.join(data_dir, "Library", "星の歌", "mine.txt")              # the name's folder is taken
    _write(taken, _text(language, 9))
    calls = []
    with store:
        real = store.take_in
        monkeypatch.setattr(store, "take_in", lambda *a, **k: calls.append(len(a[1])) or real(*a, **k))
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        parts = [r for r in _library_files(data_dir) if r.startswith("Library/星の歌 (2)/") and r.endswith(".txt")]
        assert len(parts) >= 2 and result["added"] == len(parts) and calls == [len(parts)]
        assert not [r for r in _library_files(data_dir) if r.endswith(".part")]
        keys = store.origins()
        assert all(ls.path_key(os.path.abspath(book) + f"#{n}") in keys for n in range(1, len(parts) + 1))
        assert open(taken, "rb").read() == _text(language, 9).encode("utf-8")
        from app import extract
        opened = []
        real_chunks = extract.chunks_of
        monkeypatch.setattr(extract, "chunks_of", lambda *a, **k: opened.append(a[0]) or real_chunks(*a, **k))
        again = _look(store, language, root, full=True)                         # a known EPUB is never split again
        assert opened == []                                                      # nor even read
        assert again["added"] == 0 and _items(store) == len(parts)
        assert len([r for r in _library_files(data_dir) if r.endswith(".txt")]) == len(parts) + 1


# --- progress, stop, batches, one scan at a time -------------------------------------------------------------------- #

def test_stop_ends_the_look_between_files_with_what_it_took_in_whole(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    for n in range(1, 4):
        _write(os.path.join(src, a, f"ep{n:02d}.srt"), _text(language, n))
        _write(os.path.join(src, b, f"ep{n:02d}.srt"), _text(language, n + 10))
    copied = []
    real = sources._copy_part
    monkeypatch.setattr(sources, "_copy_part", lambda o, p: copied.append(o) or real(o, p))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True, stop=lambda: len(copied) >= 2)
        assert result["stopped"] is True and result["added"] == 2 and _items(store) == 2
        assert len(_library_files(data_dir)) == 2                                # each copy taken in, none left over
        assert not os.path.exists(sources.cache_path(language))
        result = _look(store, language, root, first=True)
        assert result["added"] == 4 and _items(store) == 6


def test_batches_are_one_take_in_per_show_of_at_most_the_batch_size(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    for n in range(1, 6):
        _write(os.path.join(src, a, f"ep{n:02d}.srt"), _text(language, n))
    _write(os.path.join(src, b, "ep01.srt"), _text(language, 20))
    monkeypatch.setattr(sources, "BATCH", 2)
    calls = []
    with store:
        real = store.take_in
        monkeypatch.setattr(store, "take_in", lambda r, found, **k: calls.append(
            sorted({f["show"] for f in found}) + [len(found)]) or real(r, found, **k))
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 6
        assert sorted(calls) == sorted([[a, 2], [a, 2], [a, 1], [b, 1]])


def test_progress_is_called_as_the_look_goes(monkeypatch):
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    for n in range(1, 4):
        _write(os.path.join(src, _SHOWS[language][0], f"ep{n:02d}.srt"), _text(language, n))
    monkeypatch.setattr(sources, "PROGRESS_S", 0)
    calls = []
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True, progress=lambda f, s: calls.append((f, s)))
    assert len(calls) >= 3 and calls[-1] == (3, 1) and calls == sorted(calls)


def test_two_looks_at_one_store_never_run_at_once():
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        sources._RUNNING.add(sources._store_key(store))                        # another worker's look is running
        result = _look(store, language, root, first=True)
        assert result["busy"] is True and result["added"] == 0 and _items(store) == 0
        sources._RUNNING.clear()
        assert _look(store, language, root, first=True)["added"] == 1


def test_a_source_turned_off_is_not_looked_at():
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        store.stop_source(root)
        with pytest.raises(ls.NotASource):
            sources.scan(store, language, root, first=True)
        assert _items(store) == 0 and not os.path.exists(os.path.join(data_dir, "Library"))


@pytest.mark.parametrize("language", LANGUAGES)
def test_overlapping_sources_never_copy_one_file_twice(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    outer = _drive("Video")
    _write(os.path.join(outer, "Anime", a, "ep01.srt"), _text(language, 1))
    with store:
        first = store.add_source(outer)
        assert _look(store, language, first, first=True)["added"] == 1
        inner = store.add_source(os.path.join(outer, "Anime"))
        result = _look(store, language, inner, full=True)
        assert (result["added"], result["attached"]) == (0, 0) and _items(store) == 1


# --- the cadence (SRC-9) and local or network (D5) ------------------------------------------------------------------ #

def test_the_cadence_refresh_now_focus_every_five_minutes_else_hourly_never_hidden():
    t = 100_000.0
    assert sources.due(t, False, False, None) is True                            # the first look
    assert sources.due(t, False, True, t - 1) is True                            # Refresh: now
    assert sources.due(t, True, True, t - 1, shown=False) is True                # Refresh is a look he asked for
    assert sources.due(t, True, False, t - 299) is False                         # focus: at most every 5 min
    assert sources.due(t, True, False, t - 300) is True
    assert sources.due(t, False, False, t - 3599) is False                       # else hourly
    assert sources.due(t, False, False, t - 3600) is True
    assert sources.due(t, True, False, t - 7200, shown=False) is False           # behind or minimized: never
    assert sources.due(t, False, False, None, shown=False) is False
    assert sources.due(t, True, False, t + 50) is True                           # the clock went back: look


def test_local_or_network():
    assert sources.local_or_network(os.environ["SURASURA_TEST_ROOT"]) == "local"
    if sys.platform == "win32":
        assert sources.local_or_network(r"\\nas\video\Anime") == "network"


# --- the fix round (the adversary's K1–K7 and the N rows taken) ----------------------------------------------------- #

def _settle(root, age=60):
    """Every folder under `root` a minute old: a folder's time in the last seconds is never trusted (N5), so a test
    of the folder-time cache ages its folders first."""
    t = time.time() - age
    for where, _dirs, _files in os.walk(root, topdown=False):
        os.utime(where, (t, t))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_v1_and_its_v2_in_one_look_are_one_item_holding_the_v2(language):
    """K1 (SRC-7): the first scan meets both releases of one episode; the v2 is taken, the v1 is skipped — then and in
    every later look (it is an earlier release of an episode already in)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    tag = _OURS[language]
    _write(os.path.join(src, show, f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 1))
    v2 = _write(os.path.join(src, show, f"[Grp] {show} - 05v2 (1080p).{tag}.srt"), _text(language, 1, extra="、訂正"))
    _write(os.path.join(src, show, f"[Grp] {show} - 06 (1080p).{tag}.srt"), _text(language, 2))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 2 and _items(store) == 2
        copies = _library_files(data_dir)
        assert copies == sorted([f"Library/{show}/[Grp] {show} - 05v2 (1080p).{tag}.srt",
                                 f"Library/{show}/[Grp] {show} - 06 (1080p).{tag}.srt"])
        assert _sha(os.path.join(data_dir, copies[0])) == _sha(v2)
        again = _look(store, language, root, full=True)
        assert (again["added"], again["attached"]) == (0, 0) and _items(store) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_v2_of_a_removed_episode_stays_out(language):
    """K2 (S6): Remove keeps an episode out by its show and number too (the exclusion's note), so its re-release —
    a new path and new bytes, no video beside it — never brings it back."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    tag = _OURS[language]
    _write(os.path.join(src, show, f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        store.remove([item])
        note = json.loads(store.conn.execute("SELECT note FROM exclusions WHERE kind = 'removed'").fetchone()[0])
        assert (note["show"], note["episode"]) == (show, 5)
        _write(os.path.join(src, show, f"[Grp] {show} - 05v2 (1080p).{tag}.srt"), _text(language, 1, extra="、訂正"))
        _write(os.path.join(src, show, f"[Grp] {show} - 06v2 (1080p).{tag}.srt"), _text(language, 2))
        result = _look(store, language, root, full=True)
        assert result["added"] == 1                                              # 06's v2 is no removed episode
        assert [r for r in _library_files(data_dir) if " - 05" in r] == \
            [f"Library/{show}/[Grp] {show} - 05 (1080p).{tag}.srt"]              # (the Remove's caller trashes it)


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_subtitle_per_video_per_language_tracked_by_the_video(language):
    """K3 (1): two subtitles that both go with one video, in one look — one item; the other waits and the next look
    records it on that item through its video (check a), never a second item."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    folder = os.path.join(src, a)
    _video(os.path.join(folder, "ep01.mkv"))
    _write(os.path.join(folder, f"ep01.{_OURS[language]}.srt"), _text(language, 1))
    _write(os.path.join(folder, "ep01.alt.srt"), _text(language, 2))                     # an unknown tag: untagged
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], result["waiting"]) == (1, 1) and _items(store) == 1
        again = _look(store, language, root)
        assert (again["added"], again["attached"]) == (0, 1) and _items(store) == 1
        assert len(_library_files(data_dir)) == 1


@pytest.mark.parametrize("name, expected", [
    ("S01E01.ja.forced.srt", ("S01E01", "ja", {"forced"})),
    ("S01E01.ja.sdh.srt", ("S01E01", "ja", {"sdh"})),
    ("S01E01.ja.hi.srt", ("S01E01", "ja", {"hi"})),                    # Bazarr's hearing-impaired, never Hindi
    ("S01E01.JA.CC.srt", ("S01E01", "ja", {"cc"})),
    ("S01E01.forced.ja.srt", ("S01E01", "ja", {"forced"})),
    ("ep01.cze.srt", ("ep01", "other", set())), ("ep01.fin.srt", ("ep01", "other", set())),
    ("ep01.heb.srt", ("ep01", "other", set())), ("ep01.gre.srt", ("ep01", "other", set())),
    ("ep01.pt-BR.srt", ("ep01", "other", set())), ("ep01.hin.srt", ("ep01", "other", set())),
    ("ep01.jpn.srt", ("ep01", "ja", set())), ("ep01.jap.srt", ("ep01", "ja", set())),
    ("ep01.ja-JP.srt", ("ep01", "ja", set())),
    ("ep01.chi.srt", ("ep01", "zh", set())), ("ep01.zho.srt", ("ep01", "zh", set())),
    ("ep01.chs.srt", ("ep01", "zh", set())), ("ep01.cht.srt", ("ep01", "zh", set())),
    ("ep01.sc.srt", ("ep01", "zh", set())), ("ep01.tc.srt", ("ep01", "zh", set())),
    ("ep01.zh-Hant.srt", ("ep01", "zh", set())),
    ("ep01.director.srt", ("ep01.director", None, set())),            # an unknown tag reads as untagged
    ("ep01.srt", ("ep01", None, set())), ("ep01.hi.srt", ("ep01", None, {"hi"})),
])
def test_a_subtitles_language_tag_and_flags_are_read_from_the_right(name, expected):
    assert sources._tag(name) == expected


@pytest.mark.parametrize("language", LANGUAGES)
def test_flagged_subtitles_rank_after_the_plain_one_and_a_forced_track_is_never_taken(language):
    """K3 (2)(3): `.forced` (only the signs) is never an episode's text; `.sdh` / `.hi` / `.cc` are ours, taken only
    where no plain one is; another language's tag skipped whatever the list misses (`cze`)."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    tag = _OURS[language]
    src = _drive("driveA")
    folder = os.path.join(src, a)
    _write(os.path.join(folder, f"ep01.{tag}.sdh.srt"), _text(language, 1))
    _write(os.path.join(folder, f"ep01.{tag}.srt"), _text(language, 2))
    _write(os.path.join(folder, f"ep01.{tag}.forced.srt"), _text(language, 3))
    _write(os.path.join(folder, f"ep02.{tag}.hi.srt"), _text(language, 4))                # the only one: taken
    _write(os.path.join(folder, f"ep03.{tag}.forced.srt"), _text(language, 5))            # forced alone: skipped
    _write(os.path.join(folder, "ep04.cze.srt"), "1\n00:00:01,000 --> 00:00:02,000\nDobrý večer.\n")
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 2
        assert _library_files(data_dir) == [f"Library/{a}/ep01.{tag}.srt", f"Library/{a}/ep02.{tag}.hi.srt"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_subtitle_with_flags_finds_the_video_beside_it(language):
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _video(os.path.join(src, a, "ep01.mkv"))
    _write(os.path.join(src, a, f"ep01.{_OURS[language]}.sdh.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        record = json.loads(store.conn.execute("SELECT pairing FROM pairings").fetchone()[0])
        assert record["video_key"] == videos.content_key(os.path.join(src, a, "ep01.mkv"))


def test_a_renamed_or_moved_epub_is_the_same_book_and_is_never_read_or_copied_again(monkeypatch):
    """K4 (SRC-7): each part's record holds the EPUB file's sha256, so a renamed or moved copy of the book is known by
    its bytes: its parts' origins recorded on the items already in, nothing parsed, nothing written."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", "星の歌.epub"), _chapters())
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        assert len(ids) >= 2
        record = json.loads(store.conn.execute("SELECT pairing FROM pairings ORDER BY item_id").fetchone()[0])
        assert record["sha256"] == _sha(book)
        files = _library_files(data_dir)
        from app import extract
        opened = []
        real_chunks = extract.chunks_of
        monkeypatch.setattr(extract, "chunks_of", lambda *a, **k: opened.append(a[0]) or real_chunks(*a, **k))
        renamed = os.path.join(src, "Books", "星の歌 第一巻.epub")
        os.rename(book, renamed)
        result = _look(store, language, root, full=True)
        assert (result["added"], result["attached"]) == (0, len(ids)) and _items(store) == len(ids)
        assert opened == [] and _library_files(data_dir) == files
        keys = store.origins()
        assert all(keys[ls.path_key(os.path.abspath(renamed) + f"#{n}")].item_id == i for n, i in enumerate(ids, 1))


def test_a_removed_book_moved_or_renamed_is_never_written_again(monkeypatch):
    """K4 (S6): Remove keeps the book's bytes out — a moved copy is neither parsed nor written into Library."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", "星の歌.epub"), _chapters())
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        rels = [store.item(i)["rel_path"] for i in ids]
        store.remove(ids)
        for rel in rels:                                                         # the Remove's caller trashes them
            ls.trash_file(data_dir, rel)
        files = _library_files(data_dir)
        from app import extract
        opened = []
        monkeypatch.setattr(extract, "chunks_of", lambda *a, **k: opened.append(a[0]) or ([], None))
        os.makedirs(os.path.join(src, "Moved"))
        os.rename(book, os.path.join(src, "Moved", "星の歌.epub"))
        result = _look(store, language, root, full=True)
        assert result["added"] == 0 and opened == [] and _library_files(data_dir) == files


def test_a_book_whose_parts_are_already_in_writes_nothing():
    """K4 (b) for a book: an EPUB new to the sources whose every part's text an item already holds (the same book
    from another file) — each part's origin recorded on that item, nothing written."""
    language = "ja"
    store, data_dir = _empty(language)
    src, other = _drive("driveA"), _drive("driveB")
    book = _epub(os.path.join(src, "Books", "星の歌.epub"), _chapters())
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        files = _library_files(data_dir)
        again = _epub(os.path.join(other, "星の歌 (copy).epub"), _chapters())  # written again: the same text
        if _sha(again) == _sha(book):                                            # (the same bytes: make them differ)
            with open(again, "ab") as f:
                f.write(b"\0")
            t = time.time() - 60
            os.utime(again, (t, t))
        result = _look(store, language, store.add_source(other), full=True)
        assert (result["added"], result["attached"]) == (0, len(ids)) and _library_files(data_dir) == files


def test_an_epub_with_no_text_is_read_once_until_it_changes(monkeypatch):
    """K5 (SRC-9, S19): a book Extract can't read (no text, DRM, broken) is remembered by its size and time in the
    scan's cache — never parsed again at a start or a Refresh, read again once it changes."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", "鍵のかかった本.epub"), _chapters())
    from app import extract
    opened = []
    monkeypatch.setattr(extract, "chunks_of", lambda *a, **k: opened.append(a[0]) or ([], None))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 0
        sources._LOOKED.clear()                                                  # a start
        _look(store, language, root)
        _look(store, language, root, full=True)                                  # a Refresh
        assert len(opened) == 1
        t = time.time() - 30
        os.utime(book, (t, t))                                                   # it changed: read again
        _look(store, language, root, full=True)
        assert len(opened) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_overlapping_sources_give_a_folder_one_show_whichever_looks(language):
    """K6 (SRC-2): `Video` took ep01 in as show `Anime/<show>`; the inner source `Video/Anime` finding ep02 names it
    by the outermost source too — it joins its show in Current, never a new title in New arrivals."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    outer = _drive("Video")
    _write(os.path.join(outer, "Anime", a, "ep01.srt"), _text(language, 1))
    with store:
        first = store.add_source(outer)
        _look(store, language, first, first=True)
        inner = store.add_source(os.path.join(outer, "Anime"))
        _write(os.path.join(outer, "Anime", a, "ep02.srt"), _text(language, 2))
        assert _look(store, language, inner, full=True)["added"] == 1
        assert _current(store) == [f"Library/Anime/{a}/ep01.srt", f"Library/Anime/{a}/ep02.srt"]
        assert store.ordered("arrivals") == []
        assert store.conn.execute("SELECT COUNT(DISTINCT work_id) FROM items").fetchone()[0] == 1


@pytest.mark.parametrize("folder", ["@Recycle", "#snapshot", "@Recently-Snapshot", "~snapshot", ".snapshot",
                                    "#recycle"])
def test_a_look_skips_a_nas_recycle_bin_and_its_snapshots(folder):
    """K7 (B3): QNAP's and Synology's recycle bins and snapshot folders hold what the user deleted and older
    versions: never read."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, folder, "Show", "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 0 and _items(store) == 0


def test_a_recopy_the_held_open_copy_refuses_leaves_no_trash_copy(monkeypatch):
    """N1: the old copy can't be replaced (Generate holds it open): the trash keeps no copy of a text never
    replaced — however many looks try."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        copy = os.path.join(data_dir, "Library", a, "ep01.srt")
        old = open(copy, "rb").read()
        _write(path, _text(language, 1, extra="、修正版"), age=30)
        real = os.replace

        def held(s, d):
            if os.path.abspath(d) == os.path.abspath(copy):
                raise PermissionError(13, "in use by another program", d)
            return real(s, d)
        monkeypatch.setattr(os, "replace", held)
        for _ in range(3):
            assert _look(store, language, root, full=True)["waiting"] == 1
        assert _trash(data_dir) == [] and open(copy, "rb").read() == old


def test_a_trashed_old_copy_has_a_fresh_time_even_if_its_clock_cannot_be_restarted(monkeypatch):
    """N8: the old copy's trash file is made with a fresh time (never the old copy's own), so a failed clock restart
    can't have it purged at the next cleanup."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        copy = os.path.join(data_dir, "Library", a, "ep01.srt")
        old = time.time() - 40 * 86400
        os.utime(copy, (old, old))
        monkeypatch.setattr(sources, "restart_trash_clock", lambda p: None)
        _write(path, _text(language, 1, extra="、修正版"), age=20)
        assert _look(store, language, root, full=True)["recopied"] == 1
        assert time.time() - os.stat(os.path.join(data_dir, ".trash", _trash(data_dir)[0])).st_mtime < 60


def test_a_v2_whose_recopy_is_refused_is_not_recorded_on_the_episode():
    """N9: a v2 under half its episode's copy is refused — and not recorded either (its record would name bytes the
    item doesn't hold, and it would never be tried again)."""
    language = "ja"
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, show, f"[Grp] {show} - 05 (1080p).ja.srt"), _text(language, 1) * 4)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        v2 = _write(os.path.join(src, show, f"[Grp] {show} - 05v2 (1080p).ja.srt"), _text(language, 1)[:200])
        result = _look(store, language, root, full=True)
        assert (result["added"], result["attached"], result["recopied"]) == (0, 0, 0)
        assert ls.path_key(os.path.abspath(v2)) not in store.origins()


def test_copies_take_in_cannot_take_go_to_the_trash(monkeypatch):
    """N3: the source stopped mid-look (take_in refuses): the copies this look made are trashed, never left in Library
    untracked for the folder readers."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)

        def stopped(*args, **kw):
            raise ls.NotASource("That folder isn't being read any more.")
        monkeypatch.setattr(store, "take_in", stopped)
        result = _look(store, language, root, first=True)
        assert result["stopped"] is True and _library_files(data_dir) == [] and len(_trash(data_dir)) == 1


def test_a_folder_loop_with_no_link_is_listed_once(monkeypatch):
    """N4: a share that shows a loop as an ordinary folder (Samba following links): a folder already listed this look,
    by its device and file number, is not listed again."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, "Show", "ep01.srt"), _text(language, 1))
    _write(os.path.join(src, "Show", "loop", "ep01.srt"), _text(language, 1, extra=" again"))
    loop, show = os.path.join(src, "Show", "loop"), os.path.join(src, "Show")
    real = os.stat

    def same_inode(p, *a, **k):
        if isinstance(p, str) and os.path.normcase(os.path.abspath(p)) == os.path.normcase(loop):
            return real(show, *a, **k)
        return real(p, *a, **k)
    monkeypatch.setattr(os, "stat", same_inode)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1


def test_a_folder_whose_time_is_in_the_last_seconds_is_listed_again():
    """N5: a folder listed within SETTLE_S of its own time (a FAT32 or coarse share's tick) may gain a file in the
    same tick: its time is not kept, so the next look lists it."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, "Show", "ep01.srt"), _text(language, 1))
    _settle(src)
    os.utime(os.path.join(src, "Show"), None)                                    # just now
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        dirs = _cache(language)["roots"][str(root)]["dirs"]
        assert dirs[ls.path_key(os.path.join(src, "Show"))]["mtime_ns"] is None
        assert dirs[ls.path_key(src)]["mtime_ns"] is not None


def test_books_land_among_the_shows_in_name_order_on_the_first_scan():
    """N7 (SRC-1): setup's first scan places a book where its name falls among the shows, not after them all."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, "Alpha Line", "ep01.srt"), _text(language, 1))
    _write(os.path.join(src, "Gamma Line", "ep01.srt"), _text(language, 2))
    _epub(os.path.join(src, "Beta Book.epub"), _chapters())
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        shows = [r.split("/")[1] for r in _current(store)]
        assert shows[0] == "Alpha Line" and shows[-1] == "Gamma Line" and set(shows[1:-1]) == {"Beta Book"}


def test_a_cloud_placeholder_folder_is_never_listed(monkeypatch):
    """N13: a folder the cloud hasn't brought down (its attributes a placeholder's): listing it could download it."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, "Cloud", "ep01.srt"), _text(language, 1))
    _write(os.path.join(src, "Here", "ep01.srt"), _text(language, 2))
    import stat as stat_
    t = time.time() - 12345
    os.utime(os.path.join(src, "Cloud"), (t, t))
    ghost = os.stat(os.path.join(src, "Cloud")).st_mtime_ns                     # (a listing's stat has no inode)
    real = ls.is_placeholder
    monkeypatch.setattr(ls, "is_placeholder", lambda st: (stat_.S_ISDIR(st.st_mode) and st.st_mtime_ns == ghost)
                        or real(st))
    with store:
        root = store.add_source(src)
        spy = _ScandirSpy(monkeypatch)
        assert _look(store, language, root, first=True)["added"] == 1
        assert not spy.saw(os.path.join(src, "Cloud"))
