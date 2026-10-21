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
import threading
import time

import pytest

from app import library_store as ls
from app import sources
from app.connect import videos
from tests.test_library_store_support import LANGUAGES, RESOURCES, library, roots, write_manifest

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


def _book_text(language):
    """A loose `.txt` worth reading (T2-B4: BOOK_MIN_CHARS characters of the script or more): the app's own sample."""
    path = os.path.join(os.path.dirname(RESOURCES), os.pardir, "samples", language, "HighPriority",
                        "H_priority_sample_1.txt")
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


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


def _spy_reads(monkeypatch, read):
    """Every source file the look reads for its bytes (a new text, read once; a book's EPUB) goes into `read`."""
    real_sha, real_text = ls.sha256_of, sources._read_text
    monkeypatch.setattr(ls, "sha256_of", lambda p: read.append(p) or real_sha(p))
    monkeypatch.setattr(sources, "_read_text", lambda p, st: read.append(p) or real_text(p, st))


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
    _write(os.path.join(src, b, "notes.txt"), _book_text(language))
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
    """A text is read once (hashed, then copied from what was read): one that changes as it is read waits."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    _settle(src)
    real = sources._read_text

    def growing(origin, st):
        digest = real(origin, st)
        with open(origin, "a", encoding="utf-8") as f:                         # the downloader writes more
            f.write("続き\n")
        return digest
    monkeypatch.setattr(sources, "_read_text", growing)
    with store:
        root = store.add_source(src)
        result = sources.scan(store, language, root, first=True)                # (the test itself writes the source)
        assert result["added"] == 0 and result["waiting"] == 1
        assert _library_files(data_dir) == [] and _items(store) == 0
        monkeypatch.setattr(sources, "_read_text", real)
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
    real = sources._read_text

    def read(p, st):
        if os.path.abspath(p) == os.path.abspath(locked):
            raise PermissionError(13, "in use by another program", p)
        return real(p, st)
    monkeypatch.setattr(sources, "_read_text", read)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], result["waiting"]) == (1, 1)
        assert _library_files(data_dir) == [f"Library/{a}/ep02.srt"]
        monkeypatch.setattr(sources, "_read_text", real)
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
        _write(os.path.join(src, a, "ep02.srt"), _text(language, 2))           # its folder is listed again, the
        result = _look(store, language, root)                                   # listing bringing ep01's stats (H2)
        assert result["recopied"] == 1 and result["added"] == 1
        assert _look(store, language, root, full=True)["recopied"] == 0        # followed once
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
    _spy_reads(monkeypatch, read)
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
    real_key = videos.content_key
    monkeypatch.setattr(videos, "content_key", lambda p: read.append(p) or real_key(p))
    _spy_reads(monkeypatch, read)
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
    real = sources._write_part
    monkeypatch.setattr(sources, "_write_part", lambda p, data: copied.append(p) or real(p, data))
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



def test_a_copy_take_in_keeps_out_after_all_goes_to_the_trash(monkeypatch):
    """N3: an item removed between the look's read of the exclusions and its take_in — the look copied the file, take_in
    skips it as excluded: that copy is trashed, never left in Library untracked."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        rel = store.item(item)["rel_path"]
        store.remove([item])
        ls.trash_file(data_dir, rel)
        monkeypatch.setattr(store, "excluded", lambda root_ids=None: {})      # (the Remove came just after the read)
        result = _look(store, language, root, full=True)
        assert result["added"] == 0 and _library_files(data_dir) == [] and len(_trash(data_dir)) == 2

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


# --- K5: a video-only show waits, its subtitle fills the gap (end to end) ------------------------------------------- #

def _events(store):
    return [tuple(r) for r in store.conn.execute("SELECT item_id, kind, by, explicit FROM placement_log ORDER BY id")]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("first", (True, False))
def test_a_folder_of_videos_waits_in_new_arrivals_and_a_subtitle_later_fills_the_gap_silently(language, first,
                                                                                              monkeypatch):
    """SRC-2 (video), end to end: a show folder of videos and no subtitle — one item per video, waiting in New arrivals
    (even on setup's first scan), no file made, nothing counted; a look again reads no video twice; its subtitle comes
    later — the same item takes the copy in place (its id and place kept), silently, and counts from then."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    folder = os.path.join(src, a)
    for n in (2, 1):
        _video(os.path.join(folder, f"{a} - {n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska %d " % n)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=first)
        assert result["added"] == 2 and _items(store) == 2
        arrivals = store.ordered("arrivals")
        assert [e["physical_path"] for _i, e, _a in arrivals] == [f"Library/{a}/{a} - 01.mkv",
                                                                  f"Library/{a}/{a} - 02.mkv"]
        assert {av for _i, _e, av in arrivals} == {"waiting"}
        assert not os.path.exists(os.path.join(data_dir, "Library"))             # no file made
        assert all(not entries for entries in store.schedule().values())        # nothing counted
        keyed = []
        real_key = videos.content_key
        monkeypatch.setattr(videos, "content_key", lambda p: keyed.append(p) or real_key(p))
        again = _look(store, language, root, full=True)
        assert (again["added"], keyed) == (0, []) and _items(store) == 2      # recorded: never read again
        monkeypatch.setattr(videos, "content_key", real_key)
        ep1 = arrivals[0][0]
        events = _events(store)
        sub = _write(os.path.join(folder, f"{a} - 01.{_OURS[language]}.srt"), _text(language, 1))
        filled = _look(store, language, root)
        assert (filled["added"], filled["attached"]) == (0, 1) and _items(store) == 2
        item = store.item(ep1)
        assert (item["tier"], item["availability"]) == ("arrivals", "available")
        assert item["rel_path"] == f"Library/{a}/{a} - 01.{_OURS[language]}.srt"
        assert _sha(os.path.join(data_dir, item["rel_path"])) == _sha(sub)
        assert [i for i, _e, _a in store.ordered("arrivals")] == [i for i, _e, _a in arrivals]   # in place
        assert _events(store) == events                                          # silent: no event at all
        assert store.item(arrivals[1][0])["availability"] == "waiting"           # its neighbour still waits


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_videos_of_a_show_already_shown_never_wait(language):
    """Only a show never shown waits: a video-only folder of a show that already has an item (its subtitles came by
    another folder, a 2.x folder or hato) adds nothing; its subtitles join that show when they come."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        other = _drive("driveB")
        _video(os.path.join(other, a, "ep02.mkv"))
        result = _look(store, language, store.add_source(other), full=True)
        assert result["added"] == 0 and _items(store) == 1 and store.ordered("arrivals") == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_already_paired_never_waits(language):
    """A video hato (or any producer) already paired is that episode: no waiting row for it (check a)."""
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    _video(os.path.join(src, a, "ep01.mkv"))
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        other = _drive("driveB")
        _video(os.path.join(other, b, "ep01.mkv"))                               # the same video, another show name
        result = _look(store, language, store.add_source(other), full=True)
        assert result["added"] == 0 and _items(store) == 1


def test_a_removed_waiting_video_stays_out():
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _video(os.path.join(src, a, "ep01.mkv"))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        store.remove([item])
        assert _look(store, language, root, full=True)["added"] == 0 and _items(store) == 0
        _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))           # its subtitle: kept out too (S6)
        assert _look(store, language, root, full=True)["added"] == 0 and _items(store) == 0


def test_a_waiting_video_is_no_release_of_its_episode():
    """The v2 rule reads text origins only: a subtitle `- 05v2` beside a waiting `- 05.mkv` is taken in (never read as
    a re-copy over the video's name, which holds no file)."""
    language = "ja"
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    _video(os.path.join(src, show, f"[Grp] {show} - 05 (1080p).mkv"))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _write(os.path.join(src, show, f"[Grp] {show} - 05v2 (1080p).ja.srt"), _text(language, 1))
        assert _look(store, language, root, full=True)["added"] == 1


def test_a_removed_waiting_videos_key_is_never_read_again(monkeypatch):
    """S6, S19: the Remove keeps the video out by its path: a later look skips it before reading its key."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _video(os.path.join(src, a, "ep01.mkv"))
    with store:
        root = store.add_source(src)
        store.remove(_look(store, language, root, first=True)["ids"])
        keyed = []
        real_key = videos.content_key
        monkeypatch.setattr(videos, "content_key", lambda p: keyed.append(p) or real_key(p))
        assert _look(store, language, root, full=True)["added"] == 0 and keyed == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_video_of_a_show_that_only_waits_waits_beside_it(language):
    """A show shown only by its waiting videos is still a show with no text: its next video waits there too."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _video(os.path.join(src, a, "ep01.mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska 1 ")
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _video(os.path.join(src, a, "ep02.mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska 2 ")
        assert _look(store, language, root, full=True)["added"] == 1
        assert [(e["physical_path"], av) for _i, e, av in store.ordered("arrivals")] == \
            [(f"Library/{a}/ep01.mkv", "waiting"), (f"Library/{a}/ep02.mkv", "waiting")]


def test_a_placeholder_video_waits_by_its_path_its_key_never_read(monkeypatch):
    """B3: a cloud placeholder video is never read, not even for its key: it waits by its path alone (its subtitle,
    found beside it, fills the gap by that path)."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    ghost = _video(os.path.join(src, a, "ep01.mkv"), body=b"\x1a\x45\xdf\xa3 not downloaded yet   ")
    size = os.path.getsize(ghost)
    monkeypatch.setattr(ls, "is_placeholder", lambda st: st.st_size == size)
    keyed = []
    real_key = videos.content_key
    monkeypatch.setattr(videos, "content_key", lambda p: keyed.append(p) or real_key(p))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        assert keyed == [] and store.item(item)["availability"] == "waiting"
        record = json.loads(store.conn.execute("SELECT pairing FROM pairings").fetchone()[0])
        assert "video_key" not in record and record["video_path"] == os.path.abspath(ghost)
        _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
        assert _look(store, language, root)["attached"] == 1 and store.item(item)["availability"] == "available"


def test_a_video_still_being_written_waits_for_the_next_look():
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _video(os.path.join(src, a, "ep01.mkv"), age=0)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], result["waiting"]) == (0, 1) and _items(store) == 0
        t = time.time() - 10
        os.utime(path, (t, t))
        assert _look(store, language, root)["added"] == 1


def test_a_book_that_cannot_be_read_waits_and_the_look_goes_on(monkeypatch):
    """An EPUB locked by another program as it is read (or a Library folder that can't be listed): that book waits,
    every other show is taken in, and the look ends normally."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", "星の歌.epub"), _chapters())
    _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"), _text(language, 1))
    real = ls.sha256_of

    def sha(p):
        if os.path.abspath(p) == os.path.abspath(book):
            raise PermissionError(13, "in use by another program", p)
        return real(p)
    monkeypatch.setattr(ls, "sha256_of", sha)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], result["waiting"]) == (1, 1) and os.path.exists(sources.cache_path(language))


# --- fix round A (batch 1's reviews: the Haiku register H*, the intent register's Subs layout) --------------------- #

class _FlakyEntries:
    """The scan's own `os.scandir`, whose entry for `path` can't be read (`stat` fails: locked, a share's hiccup) — as a
    listing meets a file another program holds a moment. The test's own walks of the drives are left alone."""

    def __init__(self, monkeypatch, path):
        self.path, self.on = os.path.normcase(os.path.abspath(path)), True
        real, owner = os.scandir, self

        class Entry:
            def __init__(self, entry):
                self._entry = entry

            def __getattr__(self, name):
                return getattr(self._entry, name)

            def __fspath__(self):
                return self._entry.path

            def stat(self, **kw):
                if owner.on and os.path.normcase(self._entry.path) == owner.path:
                    raise PermissionError(13, "in use by another program", self._entry.path)
                return self._entry.stat(**kw)

        class Listing:
            def __init__(self, listing):
                self._listing = listing

            def __enter__(self):
                return (Entry(e) for e in self._listing.__enter__())

            def __exit__(self, *exc):
                return self._listing.__exit__(*exc)

        def scandir(path="."):
            caller = sys._getframe(1).f_code.co_filename
            if os.path.normcase(os.path.abspath(caller)) == os.path.normcase(os.path.abspath(sources.__file__)):
                return Listing(real(path))
            return real(path)
        monkeypatch.setattr(os, "scandir", scandir)


@pytest.mark.parametrize("what", ["file", "folder"])
def test_an_entry_that_cannot_be_read_as_its_folder_is_listed_has_the_folder_listed_again(what, monkeypatch):
    """H1: a file (or a show's folder) whose stat fails as its folder is listed is skipped for now — and its folder's
    time is not kept, so the next look, a quick one, lists it again and takes the file in; else it would wait until
    the folder changed or a Refresh."""
    language = "ja"
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    flaky = _write(os.path.join(src, a, "ep02.srt"), _text(language, 2)) if what == "file" else \
        os.path.dirname(_write(os.path.join(src, b, "ep01.srt"), _text(language, 3)))
    _settle(src)
    entries = _FlakyEntries(monkeypatch, flaky)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1
        entries.on = False                                                       # the hiccup is over
        assert _look(store, language, root)["added"] == 1 and _items(store) == 2


def test_a_quick_look_follows_a_changed_original_in_a_folder_it_lists_again_never_in_one_it_does_not():
    """H2: a folder listed again (its time moved: a file came) brings its known files' stats with the listing at no
    cost, so a changed original there is followed on that look; one in a folder whose time didn't move waits for a
    full look (S4: nothing more is stat'ed)."""
    language = "ja"
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    pa = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    pb = _write(os.path.join(src, b, "ep01.srt"), _text(language, 2))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        held = os.stat(os.path.join(src, b)).st_mtime_ns
        _write(pa, _text(language, 1, extra="、修正版"), age=30)
        _write(os.path.join(src, a, "ep02.srt"), _text(language, 4))           # a's folder is listed again
        _write(pb, _text(language, 2, extra="、修正版"), age=30)
        os.utime(os.path.join(src, b), ns=(held, held))                         # b's folder time didn't move
        t = time.time() - 30
        os.utime(os.path.join(src, a), (t, t + 1))
        quick = _look(store, language, root)
        assert (quick["added"], quick["recopied"]) == (1, 1)
        assert _sha(os.path.join(data_dir, "Library", a, "ep01.srt")) == _sha(pa)
        assert _sha(os.path.join(data_dir, "Library", b, "ep01.srt")) != _sha(pb)
        assert _look(store, language, root, full=True)["recopied"] == 1
        assert _sha(os.path.join(data_dir, "Library", b, "ep01.srt")) == _sha(pb)


def _refusing_trash(monkeypatch):
    calls = []

    def refused(data_dir, rel):
        calls.append(rel)
        raise PermissionError(13, "in use by another program", rel)
    monkeypatch.setattr(ls, "trash_file", refused)
    return calls


def test_a_copy_the_trash_cannot_take_after_the_source_stopped_never_aborts_the_look(monkeypatch):
    """H7: the source stopped mid-look and its copy can't go to the trash (held open): the look still ends normally,
    stopped, the copy left (logged), never an exception out of the scan."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)

        def stopped(*args, **kw):
            raise ls.NotASource("That folder isn't being read any more.")
        monkeypatch.setattr(store, "take_in", stopped)
        calls = _refusing_trash(monkeypatch)
        result = _look(store, language, root, first=True)
        assert result["stopped"] is True and len(calls) == 1


def test_a_copy_take_in_keeps_out_that_the_trash_cannot_take_never_aborts_the_look(monkeypatch):
    """H7: take_in keeps a copy out after all (an item removed just after the look read the exclusions) and the trash
    can't take it: the look goes on — the other show is taken in — and ends normally, its folder times saved."""
    language = "ja"
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        rel = store.item(item)["rel_path"]
        store.remove([item])
        ls.trash_file(data_dir, rel)
        _write(os.path.join(src, b, "ep01.srt"), _text(language, 2))
        monkeypatch.setattr(store, "excluded", lambda root_ids=None: {})
        os.remove(sources.cache_path(language))
        calls = _refusing_trash(monkeypatch)
        result = _look(store, language, root, full=True)
        assert result["added"] == 1 and calls == [f"Library/{a}/ep01.srt"]
        assert os.path.exists(sources.cache_path(language))


def test_a_books_parts_the_trash_cannot_take_are_each_still_tried(monkeypatch):
    """H7: a book's part can't be written, and the parts already written can't go to the trash either: each of them
    is still tried (one refused never leaves the next untried), and the look goes on."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _epub(os.path.join(src, "Books", "星の歌.epub"), _chapters() * 3)
    _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"), _text(language, 1))
    renamed = []
    real = ls.rename_no_overwrite

    def third_fails(src_, dst):
        if "星の歌" in dst:
            renamed.append(dst)
        if len(renamed) == 3 and renamed[-1] == dst:
            raise PermissionError(13, "in use by another program", dst)
        return real(src_, dst)
    monkeypatch.setattr(ls, "rename_no_overwrite", third_fails)
    calls = _refusing_trash(monkeypatch)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert len(calls) == 2 and result["added"] == 1 and result["waiting"] == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_season_folders_videos_of_one_name_wait_as_their_own_items(language):
    """H8, as reported: `Season 1/01.mkv` and `Season 2/01.mkv` of one video-only show are two waiting items — each
    season folder is its own show below the source (`<show>/Season 1`), so their rels never meet."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    for season in (1, 2):
        _video(os.path.join(src, a, f"Season {season}", "01.mkv"), body=b"\x1a\x45\xdf\xa3 season %d " % season)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 2
        assert sorted(e["physical_path"] for _i, e, _a in store.ordered("arrivals")) == \
            [f"Library/{a}/Season 1/01.mkv", f"Library/{a}/Season 2/01.mkv"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_v2_is_followed_only_once_take_in_records_it(language, monkeypatch):
    """H12: a v2 of an episode already in rewrites the episode's copy only after `take_in` recorded it there — a source
    stopped meanwhile leaves the copy as it was (the item's record and its text never disagree) and no trash copy;
    the next look follows it."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    tag = _OURS[language]
    _write(os.path.join(src, f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        copy = os.path.join(data_dir, *store.item(item)["rel_path"].split("/"))
        old = open(copy, "rb").read()
        v2 = _write(os.path.join(src, f"[Grp] {show} - 05v2 (1080p).{tag}.srt"), _text(language, 1, extra="、訂正"))
        real = store.take_in

        def stopped(*args, **kw):
            raise ls.NotASource("That folder isn't being read any more.")
        monkeypatch.setattr(store, "take_in", stopped)
        assert _look(store, language, root)["stopped"] is True
        assert open(copy, "rb").read() == old and _trash(data_dir) == []
        monkeypatch.setattr(store, "take_in", real)
        result = _look(store, language, root)
        assert (result["attached"], result["recopied"]) == (1, 1) and _sha(copy) == _sha(v2)
        assert store.origins()[ls.path_key(os.path.abspath(v2))].sha256 == _sha(v2)


def test_a_v2_whose_copy_must_wait_after_take_in_is_followed_by_the_next_look(monkeypatch):
    """H12: the v2 is recorded on its episode, then its copy can't be replaced (held open by Generate): its record
    names the copy's bytes and no time, so the next look — a quick one — follows it; never a record of bytes the copy
    doesn't hold, left as it is for good."""
    language = "ja"
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    _write(os.path.join(src, f"[Grp] {show} - 05 (1080p).ja.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        copy = os.path.join(data_dir, *store.item(item)["rel_path"].split("/"))
        old = open(copy, "rb").read()
        v2 = _write(os.path.join(src, f"[Grp] {show} - 05v2 (1080p).ja.srt"), _text(language, 1, extra="、訂正"))
        real = os.replace

        def held(s, d):
            if os.path.abspath(d) == os.path.abspath(copy):
                raise PermissionError(13, "in use by another program", d)
            return real(s, d)
        monkeypatch.setattr(os, "replace", held)
        result = _look(store, language, root)
        assert (result["attached"], result["recopied"], result["waiting"]) == (1, 0, 1)
        assert open(copy, "rb").read() == old
        assert store.origins()[ls.path_key(os.path.abspath(v2))].sha256 == _sha(copy)
        monkeypatch.setattr(os, "replace", real)
        again = _look(store, language, root)
        assert again["recopied"] == 1 and _sha(copy) == _sha(v2) and _items(store) == 1
        assert store.origins()[ls.path_key(os.path.abspath(v2))].sha256 == _sha(v2)


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_release_of_an_episode_already_in_is_skipped_never_a_second_item(language):
    """H13 (SRC-7): `[GrpB] Show - 05 (720p)` beside `[GrpA] Show - 05 (1080p)` — the same episode, another release
    of the same version, its name differing only in its tags — is skipped, found later or in the same look; a file
    whose name says more than its tags (`- 05 特別編`) is its own."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    tag = _OURS[language]
    folder = os.path.join(src, show)
    _write(os.path.join(folder, f"[GrpA] {show} - 05 (1080p).{tag}.srt"), _text(language, 1))
    _write(os.path.join(folder, f"[GrpB] {show} - 04 (720p).{tag}.srt"), _text(language, 3))
    _write(os.path.join(folder, f"[GrpA] {show} - 04 (1080p).{tag}.srt"), _text(language, 3, extra=" GrpA"))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 2 and _items(store) == 2
        _write(os.path.join(folder, f"[GrpB] {show} - 05 (720p).{tag}.srt"), _text(language, 1, extra=" GrpB"))
        _write(os.path.join(folder, f"[GrpB] {show} - 06 (720p).{tag}.srt"), _text(language, 2))
        _write(os.path.join(folder, f"{show} - 05 特別編.{tag}.srt"), _text(language, 4))
        result = _look(store, language, root, full=True)
        assert result["added"] == 2 and _items(store) == 4
        names_in = sorted(os.path.basename(p) for p in _library_files(data_dir))
        assert names_in == sorted([f"[GrpA] {show} - 04 (1080p).{tag}.srt", f"[GrpA] {show} - 05 (1080p).{tag}.srt",
                                   f"[GrpB] {show} - 06 (720p).{tag}.srt", f"{show} - 05 特別編.{tag}.srt"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_release_of_a_removed_episode_stays_out(language):
    """H13 with S6: Remove keeps the episode's other releases of that version out too (`[GrpB] … - 05 (720p)` after
    `[GrpA] … - 05 (1080p)` was removed) — never a file whose name says more (`… - 05 特別編`)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    tag = _OURS[language]
    folder = os.path.join(src, show)
    removed = _write(os.path.join(folder, f"[GrpA] {show} - 05 (1080p).{tag}.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        store.remove([_look(store, language, root, first=True)["ids"][0]])
        os.remove(removed)                                                       # he deleted that release too
        _write(os.path.join(folder, f"[GrpB] {show} - 05 (720p).{tag}.srt"), _text(language, 1, extra=" GrpB"))
        _write(os.path.join(folder, f"{show} - 05 特別編.{tag}.srt"), _text(language, 4))
        result = _look(store, language, root, full=True)
        assert result["added"] == 1
        assert os.path.basename(store.item(result["ids"][0])["rel_path"]) == f"{show} - 05 特別編.{tag}.srt"


def test_a_look_that_changes_nothing_never_rewrites_the_folder_times(monkeypatch):
    """H15 (S19): the folder-time cache is written when a look changed it — never by a look that found it as it was."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        saved = []
        real = sources._save_cache
        monkeypatch.setattr(sources, "_save_cache", lambda language_, data: saved.append(1) or real(language_, data))
        _look(store, language, root)
        _look(store, language, root, full=True)
        assert saved == []
        _write(os.path.join(src, a, "ep02.srt"), _text(language, 2))
        _look(store, language, root)
        assert saved == [1]


def test_a_quick_look_with_no_folder_changed_reads_no_origins_or_exclusions(monkeypatch):
    """H16 (S19): the origins and the exclusions are read only when a folder is listed — a quick look that finds every
    folder as it was reads neither table."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        reads = []
        real_origins, real_excluded = store.origins, store.excluded
        monkeypatch.setattr(store, "origins", lambda: reads.append("origins") or real_origins())
        monkeypatch.setattr(store, "excluded", lambda root_ids=None: reads.append("excluded") or real_excluded())
        assert _look(store, language, root)["added"] == 0 and reads == []
        _write(os.path.join(src, a, "ep02.srt"), _text(language, 2))
        assert _look(store, language, root)["added"] == 1 and sorted(reads) == ["excluded", "origins"]


def test_the_known_books_are_gathered_once_a_look(monkeypatch):
    """H20: the books already in (their parts' origins) are gathered once per look, not once per folder holding an
    EPUB."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    for shelf in ("Shelf A", "Shelf B"):
        _epub(os.path.join(src, shelf, f"星の歌 {shelf[-1]}.epub"), [c + f"<p>{shelf}</p>" for c in _chapters()])
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] >= 4

        class Counted(dict):
            walked = 0

            def __iter__(self):
                Counted.walked += 1
                return super().__iter__()
        real = store.origins
        monkeypatch.setattr(store, "origins", lambda: Counted(real()))
        assert _look(store, language, root, full=True)["added"] == 0
        assert Counted.walked == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_videos_of_a_show_already_shown_are_asked_about_once(language, monkeypatch):
    """H21 (S19): a video-only folder of a show already shown asks the library once whether its show is shown; later
    looks — the next start's full one too — remember it by the videos' stats and read no item."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    _video(os.path.join(other, a, "ep02.mkv"))
    with store:
        _look(store, language, store.add_source(src), first=True)
        second = store.add_source(other)
        assert _look(store, language, second, full=True)["added"] == 0
        sources._LOOKED.clear()                                                  # the next start
        read = []
        real = store.ordered
        monkeypatch.setattr(store, "ordered", lambda tier: read.append(tier) or real(tier))
        assert _look(store, language, second)["added"] == 0 and read == []
        assert _items(store) == 1 and store.ordered("arrivals") == []


# --- subtitles in a `Subs` folder pair with the videos above them --------------------------------------------------- #

def _subs_layout(language, folder, layout, n):
    """The subtitle of episode `n` in `layout` below the show's folder: `Subs/<show> - 0n.<ours>.srt`,
    `Subtitles/…`, or untagged in `Subs/<our language>/`."""
    if layout == "Subs/<lang>":
        return os.path.join(folder, "Subs", _OURS[language], f"{os.path.basename(folder)} - {n:02d}.srt")
    return os.path.join(folder, layout, f"{os.path.basename(folder)} - {n:02d}.{_OURS[language]}.srt")


def _record(store, origin):
    row = store.conn.execute("SELECT item_id, pairing FROM pairings WHERE content_key = ?",
                             (ls.origin_key(os.path.abspath(origin)),)).fetchone()
    return row[0], json.loads(row[1])


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("layout", ["Subs", "Subtitles", "Subs/<lang>"])
def test_subtitles_in_a_subs_folder_pair_with_the_videos_above_them_in_one_look(language, layout):
    """The Subs layout (SRC-7, SRC-2 (video)): videos in `<show>/` and their subtitles in `<show>/Subs/` (or
    `Subtitles/`, or `Subs/<language>/`) are one item per episode in one look: the copy is the show's
    (`Library/<show>/…`, never `<show>/Subs`), its record carries the video beside it, and the videos never wait as
    *no subtitles yet*."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    folder = os.path.join(src, a)
    vids = [_video(os.path.join(folder, f"{a} - {n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska %d " % n)
            for n in (1, 2)]
    subs = [_write(_subs_layout(language, folder, layout, n), _text(language, n)) for n in (1, 2)]
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], result["shows"]) == (2, 1) and _items(store) == 2
        assert store.ordered("arrivals") == []
        assert _current(store) == [f"Library/{a}/{os.path.basename(s)}" for s in subs]
        for video, sub in zip(vids, subs):
            item, record = _record(store, sub)
            assert store.item(item)["availability"] == "available"
            assert record["video_path"] == os.path.abspath(video)
            assert record["video_key"] == videos.content_key(video)
            assert record["show"]["title"] == a
        again = _look(store, language, root, full=True)
        assert (again["added"], again["attached"]) == (0, 0) and _items(store) == 2


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("subs_there", (True, False))
def test_subtitles_coming_later_into_a_subs_folder_fill_the_waiting_videos(language, subs_there):
    """The Subs layout over two looks: the videos wait (no subtitle anywhere yet); their subtitles come later into
    `Subs/` — a folder there already (the show's folder time doesn't move) or made with them — and the next look, a
    quick one, fills each waiting item in place: no new row, nothing twice."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    folder = os.path.join(src, a)
    vids = [_video(os.path.join(folder, f"{a} - {n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska %d " % n)
            for n in (1, 2)]
    if subs_there:
        os.makedirs(os.path.join(folder, "Subs"))
    _settle(src)
    with store:
        root = store.add_source(src)
        waiting = _look(store, language, root, first=True)["ids"]
        assert len(waiting) == 2 and {store.item(i)["availability"] for i in waiting} == {"waiting"}
        subs = [_write(_subs_layout(language, folder, "Subs", n), _text(language, n)) for n in (1, 2)]
        filled = _look(store, language, root)
        assert (filled["added"], filled["attached"]) == (0, 2) and _items(store) == 2
        for video, sub in zip(vids, subs):
            item, record = _record(store, sub)
            assert item in waiting and store.item(item)["availability"] == "available"
            assert store.item(item)["rel_path"] == f"Library/{a}/{os.path.basename(sub)}"
            assert record["video_path"] == os.path.abspath(video)
        assert [av for _i, _e, av in store.ordered("arrivals")] == ["available", "available"]


def test_a_video_kept_in_the_subs_folder_itself_still_pairs_with_its_subtitle():
    """The Subs layout: a video that sits in `Subs/` beside its subtitle is still seen and paired (the folder is
    listed with its show's folder, its videos with it) — one item of the show, never a `<show>/Subs` title."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    video = _video(os.path.join(src, a, "Subs", f"{a} - 01.mkv"))
    sub = _write(os.path.join(src, a, "Subs", f"{a} - 01.ja.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1 and _items(store) == 1
        item, record = _record(store, sub)
        assert record["video_path"] == os.path.abspath(video)
        assert store.item(item)["rel_path"] == f"Library/{a}/{a} - 01.ja.srt"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_subs_folder_of_another_language_leaves_the_videos_waiting(language):
    """The Subs layout with S7: `Subs/<another language>/` holds no subtitle of ours — skipped, so the show's videos
    still wait as *no subtitles yet*; `Subs/<ours>/` beside it is taken."""
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    _video(os.path.join(src, a, f"{a} - 01.mkv"))
    _write(os.path.join(src, a, "Subs", "English", f"{a} - 01.srt"), "1\n00:00:01,000 --> 00:00:02,000\nHello.\n")
    _video(os.path.join(src, b, f"{b} - 01.mkv"), body=b"\x1a\x45\xdf\xa3 another ")
    _write(os.path.join(src, b, "Subs", "English", f"{b} - 01.srt"), "1\n00:00:01,000 --> 00:00:02,000\nHello.\n")
    _write(os.path.join(src, b, "Subs", _OURS[language], f"{b} - 01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 2
        assert [(e["physical_path"], av) for _i, e, av in store.ordered("arrivals")] == \
            [(f"Library/{a}/{a} - 01.mkv", "waiting")]
        assert _current(store) == [f"Library/{b}/{b} - 01.srt"]


# --- the performance round (batch 1's smoothness register) ---------------------------------------------------------- #

BENCH = os.environ.get("SURASURA_STORE_BENCH") == "1"
MOVE_BUDGET = 0.05             # s: a window move made while a look takes files in waits no longer for the write lock


def test_a_look_that_finds_nothing_changed_reads_no_record_and_writes_nothing():
    """SRC-9, S19: a look finding every folder as it was reads the sources' rows once — no origin, no count (the
    counts' grouped read spilled a temporary table to disk: 29 MB written a look at 20k origins) — and writes
    nothing: no change in the store, the folder times' file untouched."""
    language = "ja"
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    for n in (1, 2):
        _write(os.path.join(src, a, f"ep{n:02d}.srt"), _text(language, n))
        _write(os.path.join(src, b, f"ep{n:02d}.srt"), _text(language, n + 10))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 4
        cache = sources.cache_path(language)
        with open(cache, "rb") as f:
            held = f.read()
        st, changes, versions = os.stat(cache), store.conn.total_changes, store.versions()
        sql = []
        store.conn.set_trace_callback(sql.append)
        try:
            result = _look(store, language, root)
        finally:
            store.conn.set_trace_callback(None)
        assert result["added"] == result["recopied"] == 0
        assert not [s for s in sql if "pairings" in s or "exclusions" in s], sql
        assert len([s for s in sql if "FROM roots" in s]) == 1, sql
        assert store.conn.total_changes == changes and store.versions() == versions
        with open(cache, "rb") as f:
            assert f.read() == held
        assert os.stat(cache).st_mtime_ns == st.st_mtime_ns


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_text_is_read_once_its_video_once_and_each_copy_flushed(language, monkeypatch):
    """SRC-9: a new text was read twice from the source (hashed, then copied); now once — hashed and copied
    from what was read (a subtitle is a few KB). Its video's key is read once (the record names it: Connect's check
    of a moved video), and every copy is still flushed to the disk before its record is written."""
    import builtins
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    texts = [_write(os.path.join(src, a, f"ep{n:02d}.srt"), _text(language, n)) for n in (1, 2, 3)]
    vids = [_video(os.path.join(src, a, f"ep{n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 " + bytes([n]) * 40)
            for n in (1, 2, 3)]
    _settle(src)
    opened, flushed = [], []
    real_open, real_fsync = builtins.open, os.fsync
    top = os.path.normcase(os.path.abspath(src))

    def spy_open(file, *a, **k):
        if isinstance(file, str) and os.path.normcase(os.path.abspath(file)).startswith(top + os.sep):
            opened.append(os.path.normcase(os.path.abspath(file)))
        return real_open(file, *a, **k)
    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(os, "fsync", lambda fd: flushed.append(fd) or real_fsync(fd))
    with store:
        root = store.add_source(src)
        result = sources.scan(store, language, root, first=True)
    monkeypatch.setattr(builtins, "open", real_open)
    assert result["added"] == 3
    for path in texts + vids:
        assert opened.count(os.path.normcase(os.path.abspath(path))) == 1, (path, opened)
    assert len(flushed) == 3                                                  # one per copy, before its record
    for n, path in enumerate(texts, 1):
        assert _sha(os.path.join(data_dir, "Library", a, f"ep{n:02d}.srt")) == _sha(path)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("at", [3, 5])                                       # before its last folder; at it
def test_a_source_that_goes_mid_look_is_unreachable_and_its_folder_times_are_kept(language, at, monkeypatch):
    """SRC-3: a source unplugged (or renamed away) while a look lists it is unreachable for that look, as one
    gone at its start: nothing taken in, nothing written, and the folder times kept whole — so the next look lists
    only what changed, not every folder it hadn't reached."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    shows = [f"{_SHOWS[language][0]} {n}" for n in range(1, 5)]
    for n, show in enumerate(shows):
        _write(os.path.join(src, show, "ep01.srt"), _text(language, n))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 4
        for n, show in enumerate(shows):
            _write(os.path.join(src, show, "ep02.srt"), _text(language, n + 10))
        _settle(src)
        with open(sources.cache_path(language), "rb") as f:
            held = f.read()
        items, versions = _items(store), store.versions()
        away = src + "_away"
        listed, real = [], sources._listing

        def unplugged(folder):
            listed.append(folder)
            if len(listed) == at:
                os.rename(src, away)                                          # the drive goes mid-look
            return real(folder)
        monkeypatch.setattr(sources, "_listing", unplugged)
        result = sources.scan(store, language, root, full=True)
        monkeypatch.setattr(sources, "_listing", real)
        assert result["reachable"] is False and result["added"] == 0
        assert _items(store) == items and store.versions() == versions
        with open(sources.cache_path(language), "rb") as f:
            assert f.read() == held
        assert _library_files(data_dir) == [f"Library/{s}/ep01.srt" for s in sorted(shows)]
        os.rename(away, src)
        assert _look(store, language, root)["added"] == 4


def test_a_long_look_checkpoints_every_so_many_take_ins_and_a_busy_one_waits(monkeypatch):
    """The window's handle never checkpoints by itself, so a first scan's write-ahead log grew to 122 MB at 20k.
    A look checkpoints (PASSIVE, under the write lock, never waiting for it) every CHECKPOINT_EVERY take-ins; one
    refused as busy is the next one's."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    for n in range(1, 6):
        _write(os.path.join(src, a, f"ep{n:02d}.srt"), _text(language, n))
    monkeypatch.setattr(sources, "BATCH", 1)
    monkeypatch.setattr(sources, "CHECKPOINT_EVERY", 2)
    with store:
        asked, real = [], store.checkpoint
        monkeypatch.setattr(store, "checkpoint", lambda wait=None: asked.append(wait) or real(wait=wait))
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 5
        assert asked == [0.1, 0.1]
        for n in range(6, 9):
            _write(os.path.join(src, a, f"ep{n:02d}.srt"), _text(language, n))

        def busy(wait=None):
            raise ls.StoreBusy("the library is busy; try again")
        monkeypatch.setattr(store, "checkpoint", busy)
        assert _look(store, language, root)["added"] == 3


def test_a_look_reads_the_origins_videos_once_whatever_its_take_ins(monkeypatch):
    """K1b's check (a) asks for each video a look finds; after every take-in (a write) the store read every
    record's video again — once a batch, so a first scan was quadratic. A look reads them once and keeps them up
    to date itself; the same video found in another source is still that episode."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src, other = _drive("driveA"), _drive("driveB")
    for n in range(1, 5):
        _write(os.path.join(src, a, f"ep{n:02d}.srt"), _text(language, n))
        _video(os.path.join(src, a, f"ep{n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 " + bytes([n]) * 40)
    _video(os.path.join(other, a, "ep04.mkv"), body=b"\x1a\x45\xdf\xa3 " + bytes([4]) * 40)   # ep04's bytes
    _write(os.path.join(other, a, "ep04.srt"), _text(language, 4, extra=" 別の訳"))
    monkeypatch.setattr(sources, "BATCH", 1)
    with store:
        root = store.add_source(src)
        sql = []
        store.conn.set_trace_callback(lambda s: sql.append(s) if "$.video_key" in s else None)
        try:
            first = _look(store, language, root, first=True)
        finally:
            store.conn.set_trace_callback(None)
        assert first["added"] == 4 and len(sql) == 1, sql
        result = _look(store, language, store.add_source(other))
        assert (result["added"], result["attached"]) == (0, 1) and _items(store) == 4


def test_a_video_taken_earlier_in_a_look_is_known_to_it_later():
    """The look's own video map is kept up to date as it takes files in — a video whose subtitle an earlier show
    brought in is that item's for the rest of the look (here a copy of it in a folder of videos alone: no waiting
    row for it)."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    body = b"\x1a\x45\xdf\xa3 the same episode"
    _write(os.path.join(src, "Aoi", "ep01.srt"), _text(language, 1))
    _video(os.path.join(src, "Aoi", "ep01.mkv"), body=body)
    _video(os.path.join(src, "Zen", "ep01.mkv"), body=body)                      # the same video, a folder of its own
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] == 1 and _items(store) == 1
        assert not store.conn.execute("SELECT 1 FROM items WHERE availability = 'waiting'").fetchone()


def test_a_subtitle_of_a_video_waiting_elsewhere_in_the_same_look_fills_its_gap():
    """The look's video map never names a waiting row (K5): a subtitle found later in the look beside the same
    video fills that row with its text — never recorded on it as an item already in, which would leave it waiting with
    no text."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    body = b"\x1a\x45\xdf\xa3 one episode, two copies"
    _video(os.path.join(src, "Aoi", "ep01.mkv"), body=body)                      # a folder of videos alone: it waits
    _video(os.path.join(src, "Zen", "ep01.mkv"), body=body)
    _write(os.path.join(src, "Zen", "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _items(store) == 1
        assert not store.conn.execute("SELECT 1 FROM items WHERE availability = 'waiting'").fetchone()
        assert len(_library_files(data_dir)) == 1


class _Holds:
    """Each outermost hold of the store's write lock (this process), and each wait for it, by thread."""

    def __init__(self, monkeypatch, db_path):
        self.lock = ls._write_lock_for(db_path)
        self.holds, self.waits = [], []
        acquire, release = self.lock.acquire, self.lock.release
        me = self

        def timed_acquire(timeout=ls.LOCK_TIMEOUT):
            t0 = time.perf_counter()
            acquire(timeout)
            if me.lock.depth == 1:
                me.lock.since = time.perf_counter()
                me.waits.append((threading.current_thread().name, me.lock.since - t0))

        def timed_release():
            if me.lock.depth == 1:
                me.holds.append((threading.current_thread().name, time.perf_counter() - me.lock.since))
            release()
        monkeypatch.setattr(self.lock, "acquire", timed_acquire)
        monkeypatch.setattr(self.lock, "release", timed_release)

    def of(self, name, what="holds"):
        return [s for n, s in getattr(self, what) if n == name]


def _seed(store, root, data_dir, language, src, count, per_show=50, name="e{e:03d}.srt"):
    """`count` origins already in (what a big first scan left): tiny copies in Library, taken in in big batches.
    `name`: each file's name ({show}, {e}: its number in its show from 0)."""
    line = _text(language, 0).splitlines()[-2] or "x"
    found = []
    for n in range(count):
        show = f"既存{n // per_show:04d}"
        file_name = name.format(show=show, e=n % per_show)
        rel = f"Library/{show}/{file_name}"
        full = os.path.join(data_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(f"{line} {n}\n")
        found.append({"origin": os.path.join(src, "seeded", show, file_name), "size": 10,
                      "mtime_ns": 1, "sha256": f"{n:064x}", "show": show, "rel": rel, "episode": n % per_show + 1,
                      "video_key": f"v1-seed{n:08d}"})
    for k in range(0, count, 1000):
        store.take_in(root, found[k:k + 1000], first=True)
    store.checkpoint()               # a library at rest: the helper (or a close) has checkpointed its log since


def test_a_window_move_during_a_look_lands_within_the_budget(monkeypatch):
    """G1: a window move waits for the write lock while a look takes files in. As built, a take-in of 200
    files at 2,000 origins held it for seconds (each file placed by scanning every origin per row of its show), so a
    drag waited — up to 5 s and then refused as busy. Now each take-in is small and indexed: in the timed run
    (SURASURA_STORE_BENCH=1), at 20,000 origins, no take-in holds the lock over MOVE_BUDGET and no move waits longer;
    elsewhere, a short functional pass at 600 (every move lands, none refused)."""
    language = "ja"
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    src = _drive("driveA")
    with store:
        root = store.add_source(src)
        _seed(store, root, data_dir, language, src, 20_000 if BENCH else 600)
        shows, per = (2, 250) if BENCH else (2, 30)
        for s in range(shows):
            for n in range(1, per + 1):
                stem = os.path.join(src, f"{_SHOWS[language][0]} {s}", f"[Grp] Show {s} - {n:03d}")
                _write(stem + ".ja.srt", _text(language, n, extra=f" {s}"))
                _video(stem + ".mkv", body=b"\x1a\x45\xdf\xa3 " + f"{s}-{n}".encode())
        _settle(src)
        tier = "now" if store.ordered("now") else "soon"
        ids = [i for i, _e, _a in store.ordered(tier)][:6]
        holds = _Holds(monkeypatch, store.db_path)
        done, moves, errors = threading.Event(), [], []

        def mover():
            other = ls.open_store(language, data_dir, user_files_dir)
            n = 0
            with other:
                while not done.is_set():
                    t0 = time.perf_counter()
                    try:
                        other.move([ids[n % len(ids)]], tier, before_id=ids[(n + 3) % len(ids)])
                        moves.append(time.perf_counter() - t0)
                    except ls.StoreError as e:
                        errors.append(repr(e))
                    n += 1
                    done.wait(0.02)
        thread = threading.Thread(target=mover, name="mover")
        thread.start()
        try:
            result = sources.scan(store, language, root)
        finally:
            done.set()
            thread.join()
        assert result["added"] == shows * per
        assert errors == [] and moves, errors
        scan = holds.of(threading.current_thread().name)
        assert scan
        if BENCH:
            waits = holds.of("mover", "waits")
            assert max(scan) <= MOVE_BUDGET, sorted(scan)[-5:]
            assert max(waits) <= MOVE_BUDGET, sorted(waits)[-5:]


# --- batch 2 final fix round: the look per folder (F13) and the perf review's N rows ------------------------------- #

def test_a_look_that_finds_one_new_file_reads_only_its_own_folders_origins(monkeypatch):
    """F13: the releases already in (S7) were worked out from every origin's name — at 20k, 1.3 s of a look that found
    one new file, the interpreter held all along, so a window's save made meanwhile took up to 0.5 s. Now only the
    folder of the new file is read; a v2 there still follows its episode and an earlier release is still skipped."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    shows = [f"{_SHOWS[language][0]} {n}" for n in range(1, 6)]
    for s, show in enumerate(shows):
        for e in (1, 2, 3):
            _write(os.path.join(src, show, f"[Grp] {show} - {e:02d}.srt"), _text(language, s * 10 + e))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 15
        _write(os.path.join(src, shows[2], f"[Grp] {shows[2]} - 04.srt"), _text(language, 24))  # not the first folder
        _write(os.path.join(src, shows[2], f"[Grp] {shows[2]} - 02v2.srt"), _text(language, 22, " v2"))
        _settle(os.path.join(src, shows[2]))                                 # only its folder listed again
        names, real = [], sources._episode_of
        monkeypatch.setattr(sources, "_episode_of", lambda name: names.append(name) or real(name))
        result = _look(store, language, root)
        assert result["added"] == 1 and result["attached"] == 1, result      # ep 4 new; the v2 is episode 2's
        assert names and not [n for n in names if shows[2] not in n], names   # no other show's origin was read


def test_a_show_folder_gone_mid_look_leaves_the_source_reachable_and_the_others_taken_in(monkeypatch):
    """A show's folder deleted while a look lists the source (the source itself still there) is that folder alone:
    the source stays reachable, the other shows are taken in, and the gone folder leaves the folder times (perf
    review P3: nothing told this from a source gone whole)."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    shows = [f"{_SHOWS[language][1]} {n}" for n in range(1, 5)]
    for n, show in enumerate(shows):
        _write(os.path.join(src, show, "ep01.srt"), _text(language, n))
    _settle(src)
    listed, real = [], sources._listing

    def one_goes(folder):
        listed.append(folder)
        if len(listed) == 2:
            shutil.rmtree(os.path.join(src, shows[2]))                       # a show's folder deleted mid-look
        return real(folder)
    monkeypatch.setattr(sources, "_listing", one_goes)
    with store:
        root = store.add_source(src)
        result = sources.scan(store, language, root, first=True)
        assert result["reachable"] is True and result["added"] == 3
        assert _library_files(data_dir) == sorted(f"Library/{s}/ep01.srt" for s in shows if s != shows[2])
    with open(sources.cache_path(language), encoding="utf-8") as f:
        dirs = json.load(f)["roots"][str(root)]["dirs"]
    assert ls.path_key(os.path.join(src, shows[2])) not in dirs and ls.path_key(os.path.join(src, shows[1])) in dirs


def test_a_text_read_shorter_than_its_listing_waits_and_its_copy_checks_its_length(monkeypatch):
    """The read-once copy recorded the listing's size whatever it read (perf review P5): a read of another length now
    waits for the next look — nothing copied or recorded — and a copy read whole checks its byte count too."""
    import builtins
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    path = _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"), _text(language, 1))
    _settle(src)
    real_open = builtins.open

    class Short:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

        def read(self, *a):
            return self.f.read(*a)[:-1]

    def short_open(file, mode="r", *a, **k):
        f = real_open(file, mode, *a, **k)
        return Short(f) if isinstance(file, str) and os.path.abspath(file) == os.path.abspath(path) else f
    with store:
        root = store.add_source(src)
        monkeypatch.setattr(sources, "open", short_open, raising=False)
        result = sources.scan(store, language, root, first=True)
        monkeypatch.delattr(sources, "open")
        assert result["added"] == 0 and result["waiting"] == 1 and _items(store) == 0
        assert _library_files(data_dir) == []
        assert _look(store, language, root)["added"] == 1
    part = os.path.join(data_dir, "check.part")
    size = os.path.getsize(path)
    assert sources._copy_part(path, part, size + 1) is None
    assert sources._copy_part(path, part, size) == _sha(path)


def test_a_changed_original_whose_copy_reads_another_length_waits_and_leaves_no_part_file(monkeypatch):
    """b2fix review A2: a recopy whose byte count isn't the listing's (`_copy_part` -> None) while the original still
    looks as listed waits for the next look — and its `.part` is removed, never left beside the copy in `Library`."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    path = _write(os.path.join(src, a, "ep01.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        copy = os.path.join(data_dir, "Library", a, "ep01.srt")
        old = _sha(copy)
        _write(path, _text(language, 1, extra="、修正版の字幕"), age=30)       # a corrected subtitle
        real = sources._copy_part

        def counted_short(origin, part, size=None):
            real(origin, part)                                                  # the bytes written, the count off
            return None
        monkeypatch.setattr(sources, "_copy_part", counted_short)
        assert _look(store, language, root, full=True)["recopied"] == 0
        assert not [n for n in os.listdir(os.path.dirname(copy)) if n.endswith(".part")]
        assert _sha(copy) == old and _trash(data_dir) == []
        monkeypatch.setattr(sources, "_copy_part", real)
        assert _look(store, language, root, full=True)["recopied"] == 1        # the next look follows it
        assert _sha(copy) == _sha(path)


def test_a_checkpoint_that_fails_with_a_database_error_never_ends_the_look(monkeypatch, caplog):
    """A checkpoint is housekeeping: one failing with SQLite's own error (disk I/O, a full disk), not only busy, is
    logged and the look goes on — every file taken in (perf review P6)."""
    import sqlite3
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    for n in range(1, 5):
        _write(os.path.join(src, a, f"ep{n:02d}.srt"), _text(language, n))
    monkeypatch.setattr(sources, "BATCH", 1)
    monkeypatch.setattr(sources, "CHECKPOINT_EVERY", 1)
    with store:
        def broken(wait=None):
            raise sqlite3.OperationalError("disk I/O error")
        monkeypatch.setattr(store, "checkpoint", broken)
        root = store.add_source(src)
        with caplog.at_level("WARNING", logger="surasura-cli"):
            assert _look(store, language, root, first=True)["added"] == 4
        assert "checkpoint" in caplog.text


def test_a_window_move_during_a_look_that_finds_one_new_file_saves_within_the_budget(monkeypatch):
    """F13 (G1): a window's move made while a look takes one new file in waited 5 ms for the lock, but its whole save
    took up to 0.5 s at 20k origins: the look's Python pass over every origin (their names, their records decoded)
    held the interpreter, and each of the move's SQLite calls waited for it again. In the timed run
    (SURASURA_STORE_BENCH=1), at 20,000 origins in 400 shows, every move made during such a look saves within
    MOVE_BUDGET, whole; elsewhere a short functional pass at 600.
    A move counts when its save overlapped the look (began before the look ended, saved after it began): one begun
    during the look's write is saved after the look returns. The look's pass over the new file starts only once a move
    has begun, so at least one overlaps whatever the runner's load (a look of one file at 600 origins can end before
    the mover's first move, and did on a loaded runner)."""
    language = "ja"
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    src = _drive("driveA")
    with store:
        root = store.add_source(src)
        _seed(store, root, data_dir, language, src, 20_000 if BENCH else 600,
              name="[Grp] {show} - {e:02d} (1080p).ja.srt")
        show = "既存0003"
        _write(os.path.join(src, "seeded", show, f"[Grp] {show} - 77 (1080p).ja.srt"), _text(language, 77))
        _settle(src)
        tier = "now" if store.ordered("now") else "soon"
        ids = [i for i, _e, _a in store.ordered(tier)][:6]
        began, done, moves, errors = threading.Event(), threading.Event(), [], []   # moves: (began, saved) of each

        def mover():
            other = ls.open_store(language, data_dir, user_files_dir)
            n = 0
            with other:
                while not done.is_set():
                    t0 = time.perf_counter()
                    began.set()
                    try:
                        other.move([ids[n % len(ids)]], tier, before_id=ids[(n + 3) % len(ids)])
                        moves.append((t0, time.perf_counter()))
                    except ls.StoreError as e:
                        errors.append(repr(e))
                    n += 1
                    done.wait(0.01)
        real_new = sources._Look._new

        def new_once_a_move_began(look, *args):
            assert began.wait(30), "the mover began no move"   # the look holds no lock here: the mover isn't held
            return real_new(look, *args)
        monkeypatch.setattr(sources._Look, "_new", new_once_a_move_began)
        thread = threading.Thread(target=mover, name="mover")
        thread.start()
        try:
            began.clear()                                    # a move begun before the look started doesn't count
            look_began = time.perf_counter()
            result = sources.scan(store, language, root)
            look_ended = time.perf_counter()
        finally:
            done.set()
            thread.join()
        assert result["added"] == 1 and result["reachable"]
        during = [saved - t0 for t0, saved in moves if t0 < look_ended and saved > look_began]
        assert errors == [] and during, (errors, moves, look_began, look_ended)
        if BENCH:
            assert max(during) <= MOVE_BUDGET, sorted(during)[-5:]


def test_the_releases_already_in_are_a_folders_own_never_its_subfolders():
    """S7 is per folder: worked out from the origins whose keys start with the folder's (F13), a subfolder's release
    (`Show/Season 1/… - 01`) is never the folder's own — a `… - 01` found beside it is an episode of its own."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    show = _SHOWS[language][1]
    _write(os.path.join(src, show, "Season 1", f"[Grp] {show} - 01.srt"), _text(language, 1))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1
        _write(os.path.join(src, show, f"[Grp] {show} - 01.srt"), _text(language, 5))
        _settle(os.path.join(src, show))
        assert _look(store, language, root)["added"] == 1 and _items(store) == 2


# --- item 8a: a copy gone with the data folder is copied back ------------------------------------------------------ #

def _start_afresh(language, store, data_dir):
    """The laptop's reset (item 8): the store's own folder and the sources' folder-time cache deleted, and the data
    folder's content — User Files, with the store's JSON copy, kept — then the app started again: `maintain` rebuilds
    the store from the copy (§6.8), every item pointing at a copy that is gone. -> the store, opened again."""
    import glob
    user_files_dir, db = store.user_files_dir, store.db_path
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE      # the JSON copy written
    for f in glob.glob(db + "*"):
        try:
            os.remove(f)
        except PermissionError:                                                 # the lock file, held by its process
            pass
    shutil.rmtree(os.path.dirname(sources.cache_path(language)), ignore_errors=True)
    for name in os.listdir(data_dir):
        p = os.path.join(data_dir, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    sources._LOOKED.clear()                                                     # a new run of the app
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE      # rebuilt from the copy
    return ls.open_store(language, data_dir, user_files_dir)


def _availability(store):
    return dict(store.conn.execute("SELECT rel_path, availability FROM items").fetchall())


@pytest.mark.parametrize("language", LANGUAGES)
def test_after_the_data_folder_is_lost_the_next_look_copies_each_live_item_back_into_its_place(language, monkeypatch):
    """Item 8a: the data folder emptied and the store rebuilt from its JSON copy, every item points at a copy that is
    gone and every original is a known origin — so no look ever copied it again, and the items stayed missing for
    good. Now the look copies each live item's original back into exactly its copy's place (Current, New arrivals and
    Finished alike), byte for byte, and the items are available again in that same look — the window hears it (the
    availability version moves); a second look reads no original and writes nothing. A removed episode's copy is
    never brought back (S6)."""
    store, data_dir = _empty(language)
    a, b = _SHOWS[language]
    src = _drive("driveA")
    tag = _OURS[language]
    paths = [_write(os.path.join(src, a, f"[Grp] {a} - {n:02d} (1080p).{tag}.srt"), _text(language, n))
             for n in (9, 10, 11, 12)]
    for p in paths:
        _video(p[:-len(f".{tag}.srt")] + ".mkv", body=b"\x1a\x45\xdf\xa3 fake matroska " + os.path.basename(p).encode())
    _settle(src)
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        assert len(ids) == 4
        later = _write(os.path.join(src, b, f"{b} - 01.srt"), _text(language, 3))   # (a loose .txt this short: K6 skips it)
        _settle(src)
        assert _look(store, language, root, full=True)["added"] == 1                   # New arrivals (SRC-2)
        store.finish([ids[0]])
        store.remove([ids[3]])                                                          # its copy is the caller's
        held = {r: _sha(os.path.join(data_dir, *r.split("/"))) for r in _availability(store)}
        assert len(held) == 4
    store = _start_afresh(language, store, data_dir)
    with store:
        assert set(_availability(store).values()) == {"missing"} and _library_files(data_dir) == []
        tiers = dict(store.conn.execute("SELECT rel_path, tier FROM items").fetchall())
        assert sorted(tiers.values()) == ["arrivals", "graduated", "now", "now"]
        version = store.meta()["availability_version"]
        result = _look(store, language, root)
        assert set(_availability(store).values()) == {"available"}
        assert store.meta()["availability_version"] > version
        assert result["restored"] == 4 and (result["added"], result["attached"]) == (0, 0)
        assert _library_files(data_dir) == sorted(held)                                 # the removed one isn't back
        for rel, sha in held.items():
            assert _sha(os.path.join(data_dir, *rel.split("/"))) == sha
        assert dict(store.conn.execute("SELECT rel_path, tier FROM items").fetchall()) == tiers   # places kept
        assert not any(f.endswith(".part") for f in _library_files(data_dir))
        read = []
        real = sources._copy_part
        monkeypatch.setattr(sources, "_copy_part", lambda *a, **k: read.append(a[0]) or real(*a, **k))
        again = _look(store, language, root, full=True)
        assert read == []                                                               # nothing copied, none read
        assert (again["restored"], again["added"], again["attached"]) == (0, 0, 0)
        assert _items(store) == 4


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_whose_original_is_gone_too_stays_missing_and_nothing_is_written(language):
    """Item 8a, SRC-8: a copy gone and its original gone too — the item stays as it is, missing, and the look writes
    nothing (no copy, no folder in Library, no record changed); the others are copied back."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    paths = [_write(os.path.join(src, a, f"{a} - {n:02d}.srt"), _text(language, n)) for n in (1, 2)]
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 2
    store = _start_afresh(language, store, data_dir)
    os.remove(paths[0])
    _settle(src)
    with store:
        records = store.conn.execute("SELECT content_key, pairing FROM pairings ORDER BY content_key").fetchall()
        result = _look(store, language, root)
        assert _availability(store) == {f"Library/{a}/{a} - 01.srt": "missing", f"Library/{a}/{a} - 02.srt": "available"}
        assert _library_files(data_dir) == [f"Library/{a}/{a} - 02.srt"]
        assert store.conn.execute("SELECT content_key, pairing FROM pairings ORDER BY content_key").fetchall() == records
        assert result["restored"] == 1
    store.close()
    store = _start_afresh(language, ls.open_store(language, data_dir, store.user_files_dir), data_dir)
    os.remove(paths[1])
    _settle(src)
    with store:
        result = _look(store, language, root)
        assert result["restored"] == 0 and set(_availability(store).values()) == {"missing"}
        assert not os.path.exists(os.path.join(data_dir, ls.CONTENT_FOLDER))            # nothing written at all


# --- item 11: a folder of versions of the episodes above it joins its show ----------------------------------------- #

def _versions_show(language):
    """A show's season folder: episode 5's video and subtitle — and the folder's own name, a season's (S12 stays)."""
    show = f"{_SHOWS[language][1]} S03"
    src = _drive("driveA")
    folder = os.path.join(src, show)
    tag = _OURS[language]
    _video(os.path.join(folder, f"[Grp] {show} - 05 (1080p).mkv"))
    sub = _write(os.path.join(folder, f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 5))
    return src, folder, show, tag, sub


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_versions_folder_of_the_episodes_above_it_is_that_shows_never_a_show_of_its_own(language):
    """Item 11 (the laptop's `<show>` and `<show>/synced` as two shows): a subfolder holding only subtitles of episodes
    the folder above holds — re-timed ones (`synced/`), no videos, no folders — is listed with the folder above, as
    `Subs/` is: one show, one subtitle per episode (SRC-7: the episode already in keeps its own), its folder time kept
    with the folder's (a quick look lists neither). A later version of that episode under another name is that
    episode's too, never a second item."""
    store, data_dir = _empty(language)
    src, folder, show, tag, sub = _versions_show(language)
    synced = _write(os.path.join(folder, "synced", f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 5, "。"))
    _settle(src)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["shows"], result["added"]) == (1, 1) and _items(store) == 1
        assert _library_files(data_dir) == [f"Library/{show}/{os.path.basename(sub)}"]
        entry = _cache(language)["roots"][str(root)]["dirs"][ls.path_key(folder)]
        assert entry["subtitles"] == [os.path.dirname(synced)]
        assert os.path.dirname(synced) not in entry["subs"]
        again = _look(store, language, root, full=True)
        assert (again["shows"], again["added"], again["attached"]) == (1, 0, 0) and _items(store) == 1
        _write(os.path.join(folder, "synced", f"[Other] {show} - 05 [synced].{tag}.srt"), _text(language, 5, "！"))
        later = _look(store, language, root)                         # synced/'s time moved: the show listed again
        assert (later["added"], later["attached"]) == (0, 0) and _items(store) == 1
        assert store.ordered("arrivals") == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_a_folder_named_for_versions_joins_its_show_never_one_guessed_from_its_files(language):
    """Item 11 by its NAME alone (LF-1): a subfolder of subtitles numbered like the folder's own — a split cour's
    `Part 2`, a `Movie` — is its own show, its text never taken for the folder's episodes (the guess from contents
    took Part 2's text for Part 1's three items); a versions folder, however its name is written (`Synced`, a
    full-width `ＲＥＴＩＭＥＤ`), joins whatever it holds; a season folder (`Season 2`) stays its own (S12)."""
    store, data_dir = _empty(language)
    src, folder, show, tag, sub = _versions_show(language)
    part2 = _write(os.path.join(folder, "Part 2", f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 5, "！"))
    _write(os.path.join(folder, "Movie", f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 5, "？"))
    _write(os.path.join(folder, "Synced", f"[Alt] {show} - 05.{tag}.srt"), _text(language, 5, "。"))
    _write(os.path.join(folder, "ＲＥＴＩＭＥＤ", f"[Third] {show} - 05.{tag}.srt"), _text(language, 5, "、"))
    _video(os.path.join(folder, "Synced", f"[Alt] {show} - 05.mkv"), body=b"\x1a\x45\xdf\xa3 another")
    _write(os.path.join(folder, "Season 2", f"{show} - 05.{tag}.srt"), _text(language, 7))
    _settle(src)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["shows"] == 4 and _items(store) == 4
        assert sorted({os.path.dirname(f) for f in _library_files(data_dir)}) == sorted(
            f"Library/{show}" + p for p in ("", "/Part 2", "/Movie", "/Season 2"))
        own = [f for f in _library_files(data_dir) if os.path.dirname(f) == f"Library/{show}"]
        assert len(own) == 1 and _sha(os.path.join(data_dir, *own[0].split("/"))) != _sha(part2)
        entry = _cache(language)["roots"][str(root)]["dirs"][ls.path_key(folder)]
        assert sorted(entry["subtitles"]) == sorted(os.path.join(folder, n) for n in ("Synced", "ＲＥＴＩＭＥＤ"))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_split_cours_part_2_of_same_named_subtitles_keeps_both_parts(language):
    """LF-1, the adversary's P1: `Show/` holds episodes 1-3 with videos and subtitles, `Show/Part 2/` subtitles only,
    named the same. Both parts are kept — six items — and each item holds its own part's text."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    show, tag = _SHOWS[language][0], _OURS[language]
    folder = os.path.join(src, show)
    one, two = [], []
    for n in (1, 2, 3):
        _video(os.path.join(folder, f"[Grp] {show} - {n:02d} (1080p).mkv"), body=b"fake matroska %d" % n)
        one.append(_write(os.path.join(folder, f"[Grp] {show} - {n:02d} (1080p).{tag}.srt"), _text(language, n)))
        two.append(_write(os.path.join(folder, "Part 2", f"[Grp] {show} - {n:02d} (1080p).{tag}.srt"),
                          _text(language, n, "、第二部")))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _items(store) == 6
        held = {_sha(os.path.join(data_dir, *f.split("/"))) for f in _library_files(data_dir)}
        assert held == {_sha(p) for p in one + two}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_versions_folder_that_gains_a_number_gives_the_show_its_next_episode_never_doubles(language):
    """LF-2, the adversary's P2: `synced/` joined; later it gains episode 4, which the folder lacks. It stays joined
    (never a show of its own, which brought its 1-3 in again: 3 items became 7) and 4 is the show's next episode."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    show, tag = _SHOWS[language][0], _OURS[language]
    folder = os.path.join(src, show)
    for n in (1, 2, 3):
        _video(os.path.join(folder, f"[Grp] {show} - {n:02d} (1080p).mkv"), body=b"fake matroska %d" % n)
        _write(os.path.join(folder, f"[Grp] {show} - {n:02d} (1080p).{tag}.srt"), _text(language, n))
        _write(os.path.join(folder, "synced", f"[Alt] {show} - {n:02d}.{tag}.srt"), _text(language, n, "、調整"))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 3 and _items(store) == 3
        four = _write(os.path.join(folder, "synced", f"[Alt] {show} - 04.{tag}.srt"), _text(language, 4, "、調整"))
        _settle(src)
        result = _look(store, language, root, full=True)
        assert (result["added"], _items(store), result["shows"]) == (1, 4, 1)
        assert f"Library/{show}/{os.path.basename(four)}" in _library_files(data_dir)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_back_never_writes_over_a_file_nor_from_an_empty_or_unsettled_original(language):
    """Item 8a's refusals: a file already at the copy's place is never written over (the item stays missing: the
    disk sync finds that file); an original emptied is never copied back (an empty text loses the words); one written
    in the last seconds waits for the next look — then is copied back, its record naming it. No `.part` is left."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    paths = [_write(os.path.join(src, a, f"{a} - {n:02d}.srt"), _text(language, n)) for n in (1, 2, 3, 4)]
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 4
    store = _start_afresh(language, store, data_dir)
    rels = [f"Library/{a}/{os.path.basename(p)}" for p in paths]
    other = _write(os.path.join(data_dir, *rels[0].split("/")), _text(language, 9), age=0)
    taken = _sha(other)
    _write(paths[1], "")
    _write(paths[2], _text(language, 3, "、新しい"), age=0)
    with store:
        result = _look(store, language, root)
        assert result["restored"] == 1 and result["waiting"] >= 1
        assert _availability(store) == {rels[0]: "missing", rels[1]: "missing", rels[2]: "missing",
                                        rels[3]: "available"}
        assert _sha(other) == taken and _library_files(data_dir) == [rels[0], rels[3]]
        t = time.time() - 60
        os.utime(paths[2], (t, t))
        again = _look(store, language, root, full=True)
        assert again["restored"] == 1 and _availability(store)[rels[2]] == "available"
        assert _sha(os.path.join(data_dir, *rels[2].split("/"))) == _sha(paths[2])
        record = store.origins()[ls.path_key(os.path.abspath(paths[2]))]
        assert (record.size, record.mtime_ns, record.sha256) == (os.stat(paths[2]).st_size,
                                                                 os.stat(paths[2]).st_mtime_ns, _sha(paths[2]))
        assert _sha(other) == taken and not any(f.endswith(".part") for f in _library_files(data_dir))


def test_a_copy_back_never_writes_a_missing_file_outside_library():
    """Item 8a: an origin recorded on a 2.x item (in HighPriority, check b) whose file is gone: never written back —
    only copies in Library are Surasura's (S5); the item stays missing."""
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
        assert _look(store, language, root, first=True)["attached"] == 1
        os.remove(os.path.join(data_dir, rel))
        store.sync_disk()
        assert _availability(store) == {rel: "missing"}
        result = _look(store, language, root, full=True)
        assert result["restored"] == 0 and _availability(store) == {rel: "missing"}
        assert not os.path.exists(os.path.join(data_dir, rel)) and _library_files(data_dir) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_copies_back_leaves_a_row_removed_moved_or_back_meanwhile_and_names_the_copies_no_item_holds(language):
    """Item 8a, the store's half (`Store.copies_back`): only an item still at that rel and still missing is made
    available, its size and time the copy's; a removed item's copy, and one for a row moved elsewhere, come back as no
    item's (the look trashes them, never left in Library untracked: B2); a row available already is left as it is;
    nothing done moves no version."""
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    for n in (1, 2, 3, 4):
        _write(os.path.join(src, a, f"{a} - {n:02d}.srt"), _text(language, n))
    _settle(src)
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        rels = [store.item(i)["rel_path"] for i in ids]
        with store._writing():
            store.conn.execute("UPDATE items SET availability = 'missing'")
            store.conn.execute("UPDATE items SET availability = 'available' WHERE id = ?", (ids[3],))
        store.remove([ids[1]])
        meta = store.meta()
        assert store.copies_back([]) == ([], [])
        st = os.stat(os.path.join(data_dir, *rels[0].split("/")))
        done, unused = store.copies_back([(ids[0], rels[0], st.st_size, st.st_mtime_ns), (ids[1], rels[1], 1, 1),
                                          (ids[2], rels[2] + ".moved", 1, 1), (ids[3], rels[3], 1, 1)])
        assert done == [ids[0]] and unused == [rels[1], rels[2] + ".moved"]
        assert [store.item(i)["availability"] for i in (ids[0], ids[2], ids[3])] == ["available", "missing",
                                                                                     "available"]
        assert (store.item(ids[0])["size"], store.item(ids[0])["mtime_ns"]) == (st.st_size, st.st_mtime_ns)
        assert store.meta()["availability_version"] == meta["availability_version"] + 1
        assert store.copies_back([(ids[3], rels[3], 1, 1)]) == ([], [])
        assert store.meta()["availability_version"] == meta["availability_version"] + 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_back_takes_the_text_its_item_last_followed(language):
    """Item 8a: an item holding two originals — an episode and its v2, followed into the copy (H12) — gets the v2's
    text back, the one its records last followed, never the earlier release's."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    tag = _OURS[language]
    _write(os.path.join(src, f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 1), age=120)
    _settle(src)
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        v2 = _write(os.path.join(src, f"[Grp] {show} - 05v2 (1080p).{tag}.srt"), _text(language, 1, "、訂正"))
        assert _look(store, language, root)["recopied"] == 1
        rel = store.item(item)["rel_path"]
    store = _start_afresh(language, store, data_dir)
    with store:
        assert _look(store, language, root)["restored"] == 1
        assert _sha(os.path.join(data_dir, *rel.split("/"))) == _sha(v2) and _items(store) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_back_takes_the_later_release_even_when_its_file_time_is_older(language):
    """LF-3, the adversary's P3: the v2 arrived with an older file time than its v1 (an archive keeps its time) and
    was followed into the copy. The copy back takes the v2 — the later release, then the record followed last —
    never the newest file time, which brought the v1's text back."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    src = _drive("driveA")
    tag = _OURS[language]
    _write(os.path.join(src, f"[Grp] {show} - 05 (1080p).{tag}.srt"), _text(language, 1), age=120)
    _settle(src)
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        v2 = _write(os.path.join(src, f"[Grp] {show} - 05v2 (1080p).{tag}.srt"), _text(language, 1, "、訂正"),
                    age=900)
        _settle(src, age=30)
        assert _look(store, language, root, full=True)["recopied"] == 1
        rel = store.item(item)["rel_path"]
    store = _start_afresh(language, store, data_dir)
    with store:
        assert _look(store, language, root)["restored"] == 1
        assert _sha(os.path.join(data_dir, *rel.split("/"))) == _sha(v2) and _items(store) == 1


@pytest.mark.parametrize("failure", ["the store busy", "the copy's stat"])
def test_a_copy_placed_but_not_recorded_is_removed_so_the_next_look_puts_it_back(failure, monkeypatch):
    """H15: the copy is renamed into its place before the store records it; the store busy, or the copy's stat
    failing, left an untracked file there — which no later look ever replaced (a file at the place is the sync's).
    One cleanup path: our just-placed copy is removed, the item stays missing, and the next look restores it."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    original = _write(os.path.join(src, a, f"{a} - 01.srt"), _text(language, 1))
    _settle(src)
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
        rel = store.item(item)["rel_path"]
    store = _start_afresh(language, store, data_dir)
    place = os.path.normcase(os.path.join(data_dir, *rel.split("/")))
    real_copies_back, real_stat = store.copies_back, os.stat
    if failure == "the store busy":
        def busy(*_a, **_k):
            raise ls.StoreBusy("the library is busy; try again")
        monkeypatch.setattr(store, "copies_back", busy)
    else:
        real = os.stat

        def stat(p, *args, **kw):
            if os.path.normcase(os.fspath(p)) == place:
                raise PermissionError(13, "held by a scanner")
            return real(p, *args, **kw)
        monkeypatch.setattr(sources.os, "stat", stat)
    with store:
        try:
            _look(store, language, root)
        except ls.StoreBusy:
            pass
        monkeypatch.setattr(store, "copies_back", real_copies_back)    # (never `undo`: it drops the test root too)
        monkeypatch.setattr(sources.os, "stat", real_stat)
        assert _library_files(data_dir) == [] and set(_availability(store).values()) == {"missing"}
        assert _look(store, language, root, full=True)["restored"] == 1
        assert _sha(os.path.join(data_dir, *rel.split("/"))) == _sha(original)


def test_a_copy_back_whose_item_went_meanwhile_goes_to_the_trash(monkeypatch):
    """Item 8a, B2: an item removed between its copy written back and the store told — the copy is no item's, so it
    goes to the trash, never left in Library untracked."""
    language = "ja"
    store, data_dir = _empty(language)
    a = _SHOWS[language][0]
    src = _drive("driveA")
    _write(os.path.join(src, a, f"{a} - 01.srt"), _text(language, 1))
    _settle(src)
    with store:
        root = store.add_source(src)
        item = _look(store, language, root, first=True)["ids"][0]
    store = _start_afresh(language, store, data_dir)
    real = store.copies_back

    def removed_meanwhile(back, records=None):
        store.remove([item])
        return real(back, records)
    monkeypatch.setattr(store, "copies_back", removed_meanwhile)
    with store:
        result = _look(store, language, root)
        assert result["restored"] == 0 and _library_files(data_dir) == [] and _items(store) == 0
        assert len(_trash(data_dir)) == 1


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("case", ["same name", "only the folder's tagged", "only the folder's named like the video",
                                  "ass above, srt in synced", "named like the video, untagged, above a tagged other",
                                  "named like the video but flagged, below a tagged other"])
def test_of_one_episodes_subtitles_listed_together_the_order_picks_the_one_taken(language, case):
    """Item 11, the order of one episode's subtitles (Sonic's answers, the library model 2 and T2-A1): named exactly
    like the video (no flag), then our language's tag, then in a versions folder (`synced/`), then `.ass` before `.srt`, then the first by name —
    the others are other versions, never counted. So `synced/`'s file wins over the folder's own unless the folder's
    wins at an earlier step; and once taken, it is the episode: a later release found beside the video is never a
    second item."""
    store, data_dir = _empty(language)
    show = f"{_SHOWS[language][1]} S03"
    src = _drive("driveA")
    folder = os.path.join(src, show)
    tag = _OURS[language]
    stem = f"[Grp] {show} - 05 (1080p)"
    _video(os.path.join(folder, stem + ".mkv"))
    own, synced, winner = {
        "same name": (f"{stem}.{tag}.srt", f"{stem}.{tag}.srt", "synced"),
        "only the folder's tagged": (f"{stem}.{tag}.srt", f"{stem}.srt", "own"),
        "only the folder's named like the video": (f"{stem}.{tag}.srt", f"[Alt] {show} - 05 [synced].{tag}.srt",
                                                   "own"),
        "ass above, srt in synced": (f"{stem}.{tag}.ass", f"{stem}.{tag}.srt", "synced"),
        # T2-A1: a subtitle made for this exact video is timed to it, so it goes before a tagged one of another name
        "named like the video, untagged, above a tagged other": (f"{stem}.srt",
                                                                f"[Alt] {show} - 05 [synced].{tag}.srt", "own"),
        # a flag (`.sdh`) is something added: no longer the exact name, so the tag decides
        "named like the video but flagged, below a tagged other": (f"{stem}.sdh.srt",
                                                                  f"[Alt] {show} - 05 [synced].{tag}.srt", "synced"),
    }[case]
    own = _write(os.path.join(folder, own), _text(language, 5))
    synced = _write(os.path.join(folder, "synced", synced), _text(language, 5, "。"))
    _settle(src)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["shows"], result["added"]) == (1, 1) and _items(store) == 1
        taken = own if winner == "own" else synced
        files = _library_files(data_dir)
        assert files == [f"Library/{show}/{os.path.basename(taken)}"] and _sha(os.path.join(data_dir, files[0])) == \
            _sha(taken)
        assert ls.path_key(os.path.abspath(taken)) in store.origins() and len(store.origins()) == 1
        _write(os.path.join(folder, f"[Third] {show} - 05 (720p).{tag}.srt"), _text(language, 5, "！"))
        later = _look(store, language, root)
        assert (later["added"], later["attached"]) == (0, 0) and _items(store) == 1


# --- LF-9 / I-R3: the exact-name step passes the one language rule too (K6's `_refusal`) -------------------------- #

_ENGLISH = ("1\n00:00:01,000 --> 00:00:03,000\nWhere are you going?\n\n2\n00:00:04,000 --> 00:00:06,000\n"
            "Home, before the rain comes.\n")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_subtitle_named_like_the_video_in_another_language_never_beats_ours(language):
    """LF-9 (the adversary's P6): `Show - 05.srt` named exactly like the video but in another language (English as a
    release ships it untagged; in a Chinese library a Japanese one) vs `[JP] Show - 05.<ours>.srt`. The exact name
    goes first (T2-A1), but every candidate passes K6's one language rule: the other language's file is out, ours is
    the episode — one item, never none."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    folder = os.path.join(src, show)
    _video(os.path.join(folder, f"{show} - 05.mkv"), body=b"fake matroska 5")
    _write(os.path.join(folder, f"{show} - 05.srt"), _ENGLISH if language == "ja" else _text("ja", 5))
    ours = _write(os.path.join(folder, f"[JP] {show} - 05.{_OURS[language]}.srt"), _text(language, 5))
    _settle(src)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        files = _library_files(data_dir)
        assert (result["added"], _items(store)) == (1, 1)
        assert [_sha(os.path.join(data_dir, *f.split("/"))) for f in files] == [_sha(ours)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_subtitle_named_like_the_video_in_our_language_still_beats_a_tagged_one(language):
    """T2-A1 holds with the rule: the untagged file named like the video, in our language, is the episode."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src = _drive("driveA")
    folder = os.path.join(src, show)
    _video(os.path.join(folder, f"{show} - 05.mkv"), body=b"fake matroska 5")
    exact = _write(os.path.join(folder, f"{show} - 05.srt"), _text(language, 5))
    _write(os.path.join(folder, f"[JP] {show} - 05.{_OURS[language]}.srt"), _text(language, 5, "。"))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1 and _items(store) == 1
        files = _library_files(data_dir)
        assert [_sha(os.path.join(data_dir, *f.split("/"))) for f in files] == [_sha(exact)]


# --- LF-15 / LF-16 / LF-17: the one named-folder rule (and its words at the end of a subtitle's name) --------------- #

_LANGUAGE_FOLDERS = {"ja": ["JP", "ja", "[Japanese]", "Japanese Subs", "日本語字幕"],
                     "zh": ["CHS", "zh", "[Chinese]", "中文字幕", "ＣＨＴ"]}


def _videos_above(language, show, n=2):
    src = _drive("driveA")
    folder = os.path.join(src, show)
    stems = [f"[Grp] {show} - {e:02d} (1080p)" for e in range(1, n + 1)]
    for e, stem in enumerate(stems, 1):
        _video(os.path.join(folder, stem + ".mkv"), body=b"fake matroska %d" % e)
    return src, folder, stems


def _waiting(store):
    return store.conn.execute("SELECT COUNT(*) FROM items WHERE availability = 'waiting'").fetchone()[0]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("at", range(5))
def test_a_folder_named_only_for_our_language_is_listed_with_the_videos_above_it(language, at):
    """LF-15 (scenario rows 29-32): `<Show>/` holds the videos, `<Show>/JP/` (or `[Japanese]`, `Japanese Subs`,
    `中文字幕`…) their untagged subtitles. By the name alone — the language names `Subs/<language>/` reads — it counts
    as `Subs/`: one show, each subtitle its video's, no video waiting. Its untagged texts are ours."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src, folder, stems = _videos_above(language, show)
    for e, stem in enumerate(stems, 1):
        _write(os.path.join(folder, _LANGUAGE_FOLDERS[language][at], stem + ".srt"), _text(language, e))
    _settle(src)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["shows"], _items(store), _waiting(store)) == (1, 2, 0)
        assert {os.path.dirname(f) for f in _library_files(data_dir)} == {f"Library/{show}"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_named_for_another_language_stays_a_folder_of_its_own(language):
    """LF-15's other side: `English/` beside the videos is never joined (its texts aren't ours anyway): the videos
    wait (even holding our text, it is a folder of its own)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src, folder, stems = _videos_above(language, show, n=1)
    _write(os.path.join(folder, "English", stems[0] + ".srt"), _text(language, 1))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _waiting(store) == 1
        assert {os.path.dirname(f) for f in _library_files(data_dir) if f.endswith(".srt")} == \
            {f"Library/{show}/English"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_download_unpacked_into_a_folder_named_like_the_show_is_that_shows(language):
    """LF-16 (row 45): `<Show>/<Show>/` holds a subtitle download named its own way (`<Show>.S01E01.WEBRip.ja.srt`):
    by its name — the show folder's own — it is the show's subtitle folder: one show. A folder named like the archive
    (`<Show> [archive]`) stays a show of its own."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src, folder, stems = _videos_above(language, show)
    for e in (1, 2):
        _write(os.path.join(folder, show,
                            f"{show}.S01E{e:02d}.WEBRip.{_OURS[language]}.srt"), _text(language, e))
        _write(os.path.join(folder, f"{show} [archive]", f"{show}.S01E{e:02d}.WEB.{_OURS[language]}.srt"),
               _text(language, e, "。"))
    _settle(src)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["shows"] == 2 and _items(store) == 4
        assert sorted({os.path.dirname(f) for f in _library_files(data_dir)}) == [
            f"Library/{show}", f"Library/{show}/{show} [archive]"]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("mark", ["{tag}.synced", "synced.{tag}", "{tag}.RETIMED"])
def test_a_retimed_file_beside_the_video_is_that_episode_never_a_second_item(language, mark):
    """LF-17 (row 44): `<video>.ja.srt` and a re-timer's `<video>.ja.synced.srt` (or `.synced.ja`, `.retimed`) beside
    it: the versions mark is the versions folders' word — one item, and the re-timed text is the one read (ranked as
    a versions folder's file)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    src, folder, stems = _videos_above(language, show, n=1)
    tag = _OURS[language]
    _write(os.path.join(folder, f"{stems[0]}.{tag}.srt"), _text(language, 1))
    retimed = _write(os.path.join(folder, f"{stems[0]}.{mark.format(tag=tag)}.srt"), _text(language, 1, "、調整"))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1 and _items(store) == 1
        files = _library_files(data_dir)
        assert [_sha(os.path.join(data_dir, *f.split("/"))) for f in files] == [_sha(retimed)]
