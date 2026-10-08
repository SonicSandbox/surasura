"""The library watched, not checked (L3.2, `app/library_watch.py`): Windows' change reports over the library's tree.

Every library here is synthetic, under the per-test SURASURA_TEST_ROOT, named with real Japanese and Chinese words
(`test_library_store_support.library`). Waits poll with a bound (never a fixed sleep): GitHub's runner is Windows too,
so the watch runs there for real.
"""

import os
import shutil
import sys
import time

import pytest

from app import library_store as ls
from app import library_watch as lw
from tests.test_library_store_support import LANGUAGES, library, names, touch

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows' change reports")
TIER_FOLDERS = tuple(ls.FOLDER_OF_TIER[t] for t in ls.ANALYSED)


def _settled(watch, want=None, full=None, timeout=5.0):
    """Take from the watch until `want` folders (all of them) or a full look shows up, within `timeout`."""
    seen, got_full = set(), False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        watch.wait(0.2)
        folders, f = watch.take()
        seen.update(folders)
        got_full = got_full or f
        if (want is not None and set(want) <= seen) or (full and got_full):
            break
    return seen, got_full


def _watch(data_dir, **kw):
    w = lw.TreeWatch(data_dir, settle=kw.pop("settle", 0.05), under=TIER_FOLDERS, **kw)
    assert w.start(), (w.state, w.error)
    return w


# --- the pure rules --------------------------------------------------------------------------------------- #

def test_ignored_names_never_trigger_a_sync():
    # The trash, the copy, Windows' folder file and the temp names a download or an editor writes first.
    for rel in ("SoonContent/.trash/話.srt", ".trash/a_20261008.srt", "LowPriority/番組/master_manifest.json",
                "LowPriority/番組/desktop.ini", "LowPriority/番組/第01話.srt.part", "HighPriority/x.ytdl",
                "HighPriority/~$台本.txt", "HighPriority/新しい.tmp", "HighPriority/a.crdownload"):
        assert lw.ignored(rel), rel
    for rel in ("HighPriority/番組/第01話.srt", "LowPriority/番組", "GoalContent/小説.txt"):
        assert not lw.ignored(rel), rel


def test_outermost_keeps_only_the_top_folder_of_each_branch():
    # A scoped sync takes everything under a folder it's given: a child in the same batch adds nothing.
    assert lw._outermost(["LowPriority/番組/特典", "LowPriority/番組", "HighPriority/映画"]) == \
        ["HighPriority/映画", "LowPriority/番組"]
    assert lw._outermost(["LowPriority/番組2", "LowPriority/番組"]) == ["LowPriority/番組", "LowPriority/番組2"]


def test_parse_reads_every_record_in_a_buffer():
    def rec(name, last=False):
        data = name.encode("utf-16-le")
        size = (12 + len(data) + 3) // 4 * 4
        head = (0 if last else size).to_bytes(4, "little") + (1).to_bytes(4, "little") + len(data).to_bytes(4, "little")
        return (head + data).ljust(size, b"\0")
    raw = rec("LowPriority\\番組\\第01話.srt") + rec("LowPriority\\番組", last=True)
    assert lw._parse(raw) == ["LowPriority\\番組\\第01話.srt", "LowPriority\\番組"]


def test_parse_can_carry_each_reports_action():
    data = "LowPriority\\番組".encode("utf-16-le")
    raw = (0).to_bytes(4, "little") + (3).to_bytes(4, "little") + len(data).to_bytes(4, "little") + data
    assert lw._parse(raw, actions=True) == [(3, "LowPriority\\番組")]


def test_a_folders_own_modified_report_asks_for_nothing(tmp_path):
    # Windows reports a folder "modified" whenever something inside it changes; that change has its own report.
    (tmp_path / "LowPriority" / "番組").mkdir(parents=True)
    root = str(tmp_path)
    assert lw.folders_of(root, "LowPriority/番組", lw.FILE_ACTION_MODIFIED) == []
    assert lw.folders_of(root, "LowPriority/番組", 1) == ["LowPriority/番組"]             # a folder arrived: itself
    assert lw.folders_of(root, "LowPriority/番組/第01話.srt", 1) == ["LowPriority/番組"]  # a file: its folder
    assert lw.folders_of(root, "LowPriority/消えた番組", 2) == ["LowPriority"]           # gone: its parent


def test_not_windows_falls_back_without_touching_windows(monkeypatch, tmp_path):
    # macOS / Linux keep the slow look: the watch says so and never loads kernel32.
    monkeypatch.setattr(lw.sys, "platform", "linux")
    monkeypatch.setattr(lw, "_k32", lambda: pytest.fail("kernel32 loaded off Windows"))
    w = lw.TreeWatch(str(tmp_path))
    assert w.start() is False and w.state == "fallback"


def test_a_missing_root_falls_back(tmp_path):
    w = lw.TreeWatch(str(tmp_path / "ない"))
    assert w.start() is False and w.state == "fallback"


# --- the live watch (Windows) ----------------------------------------------------------------------------- #

@windows_only
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_dropped_into_a_show_folder_is_reported_once_it_settles(language):
    data_dir, _u, _doc = library(language)
    w = _watch(data_dir)
    try:
        soon = os.path.join(data_dir, "LowPriority")
        show = sorted(d for d in os.listdir(soon) if os.path.isdir(os.path.join(soon, d)))[0]
        touch(data_dir, f"LowPriority/{show}/{show}_第99話.srt", f"{show}\n")
        seen, full = _settled(w, want=[f"LowPriority/{show}"])
        time.sleep(0.2)                                   # the tier folder's own report, if one came, has settled too
        seen |= set(w.take(time.monotonic() + 10)[0])
        assert seen == {f"LowPriority/{show}"} and not full   # the show's folder, never the whole tier
    finally:
        w.close()


@windows_only
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_copied_in_names_the_new_folder(language, tmp_path):
    # A show folder of 12 episodes copied in by hand: the new folder alone (its scoped sync takes its 12 files).
    data_dir, _u, _doc = library(language)
    src = tmp_path / "src"
    word = names(language)[20]
    for e in range(1, 13):
        touch(str(src), f"{word}_第{e:02d}話.srt")
    w = _watch(data_dir)
    try:
        shutil.copytree(src, os.path.join(data_dir, "GoalContent", word))
        seen, full = _settled(w, want=[f"GoalContent/{word}"])
        assert seen == {f"GoalContent/{word}"} and not full
    finally:
        w.close()


@windows_only
def test_renamed_moved_and_deleted_folders_are_reported():
    data_dir, _u, _doc = library("ja")
    w = _watch(data_dir)
    try:
        soon = os.path.join(data_dir, "LowPriority")
        a, b = sorted(d for d in os.listdir(soon) if os.path.isdir(os.path.join(soon, d)))[:2]
        os.rename(os.path.join(soon, a), os.path.join(soon, a + "_改"))
        seen, _f = _settled(w, want=["LowPriority"])
        assert "LowPriority" in seen
        shutil.move(os.path.join(soon, b), os.path.join(data_dir, "GoalContent", b))
        seen, _f = _settled(w, want=["LowPriority", f"GoalContent/{b}"])
        assert {"LowPriority", f"GoalContent/{b}"} <= seen
        shutil.rmtree(os.path.join(soon, a + "_改"))
        seen, _f = _settled(w, want=["LowPriority"])
        assert "LowPriority" in seen
    finally:
        w.close()


@windows_only
def test_the_trash_and_temp_names_wake_nothing():
    data_dir, _u, _doc = library("zh")
    w = _watch(data_dir)
    try:
        touch(data_dir, ".trash/旧_20261008.srt")
        touch(data_dir, "HighPriority/下载中.srt.part")
        touch(data_dir, "HighPriority/~$笔记.txt")
        time.sleep(0.3)                                   # bounded: proving an absence
        folders, full = w.take(time.monotonic() + 10)
        assert folders == [] and not full
    finally:
        w.close()


@windows_only
def test_a_file_still_being_written_waits_until_it_settles():
    # Reports keep coming while a copy runs; the folder is handed over only once it has been quiet for `settle`.
    data_dir, _u, _doc = library("ja")
    w = _watch(data_dir, settle=0.4)
    try:
        path = os.path.join(data_dir, "HighPriority", "長い字幕.srt")
        with open(path, "w", encoding="utf-8") as f:
            for i in range(6):
                f.write(f"{i}\n00:00:01,000 --> 00:00:02,000\n書いている途中\n\n" * 50)
                f.flush()
                os.fsync(f.fileno())
                time.sleep(0.1)
                assert w.take()[0] == [], "handed over mid-write"
        seen, _f = _settled(w, want=["HighPriority"])
        assert "HighPriority" in seen
    finally:
        w.close()


@windows_only
def test_an_overflow_asks_for_one_full_look():
    # Windows' buffer made tiny and the reader slowed: Windows says it lost track (0 bytes) → `full`, once.
    data_dir, _u, _doc = library("ja")
    w = lw.TreeWatch(data_dir, buffer=512, settle=0.05, under=TIER_FOLDERS)
    read = w._read

    def slow_read(buf, got):
        ok = read(buf, got)
        time.sleep(0.3)
        return ok
    w._read = slow_read
    assert w.start()
    try:
        for i in range(300):
            touch(data_dir, f"LowPriority/大量/大量_{i:04d}.srt")
        _seen, full = _settled(w, full=True, timeout=10)
        assert full
        assert w.take() == ([], False)                    # the full look replaces every pending folder
    finally:
        w.close()


@windows_only
def test_close_ends_the_thread_and_an_idle_watch_never_wakes():
    data_dir, _u, _doc = library("zh")
    w = _watch(data_dir)
    time.sleep(0.5)
    assert w.reports == 0 and w.alive                     # nothing happened: the thread never woke
    w.close()
    assert not w.alive and w.state == "closed"
    assert w.start() and w.alive                          # and it can start again (focus, the retry)
    w.close()


@windows_only
def test_a_refused_read_falls_to_ended_with_its_error(monkeypatch):
    # A share that stops answering (the call fails): the window falls back to the slow look and retries.
    data_dir, _u, _doc = library("ja")
    w = lw.TreeWatch(data_dir, under=TIER_FOLDERS)
    w._read = lambda buf, got: False
    monkeypatch.setattr(lw, "_last_error", lambda: 64)    # ERROR_NETNAME_DELETED
    assert w.start()
    deadline = time.monotonic() + 5
    while w.state == "watching" and time.monotonic() < deadline:
        w.wait(0.1)
    assert w.state == "ended" and w.error == 64 and not w.alive
    w.close()


# --- the writers' bell ------------------------------------------------------------------------------------ #

def _rung(bell, n=1, timeout=5.0):
    deadline = time.monotonic() + timeout
    while bell.rings < n and time.monotonic() < deadline:
        time.sleep(0.01)
    return bell.rings


@windows_only
def test_one_ring_from_another_process_wakes_every_listening_window(tmp_path):
    # Two windows on one store (each its own slot); a writer in a third process rings once: both wake.
    import subprocess
    db = str(tmp_path / "library_ja_0123456789abcdef.db")
    woke = []
    a, b = lw.Bell(db, lambda: woke.append("a")), lw.Bell(db, lambda: woke.append("b"))
    try:
        assert (a.slot, b.slot) == (0, 1)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-c", f"from app import library_watch as lw; print(lw.ring({db!r}))"],
                             cwd=root, capture_output=True, text=True, timeout=60)
        assert out.stdout.strip() == "2", out.stderr
        assert _rung(a) == 1 and _rung(b) == 1 and sorted(woke) == ["a", "b"]
    finally:
        a.close()
        b.close()


@windows_only
@pytest.mark.parametrize("language", LANGUAGES)
def test_every_committed_write_rings_and_a_no_write_never_does(language):
    from tests.test_library_store_support import migrated
    store = migrated(language)
    bell = lw.Bell(store.db_path, lambda: None)
    try:
        with store._writing():
            store._set_meta({"copy_dirty": store._meta().get("copy_dirty", 0) + 1})
        assert _rung(bell) == 1
        with pytest.raises(RuntimeError):
            with store._writing():
                raise RuntimeError("rolled back")
        time.sleep(0.2)                                   # bounded: proving an absence
        assert bell.rings == 1                            # a rolled-back write rings nothing
    finally:
        bell.close()
        store.close()


@windows_only
def test_a_ring_that_fails_never_fails_the_commit(monkeypatch):
    from tests.test_library_store_support import migrated
    store = migrated("zh")
    try:
        monkeypatch.setattr(lw, "_k32", lambda: (_ for _ in ()).throw(OSError("kernel32 gone")))
        with store._writing():
            store._set_meta({"copy_dirty": store._meta().get("copy_dirty", 0) + 1})
        assert lw.ring(store.db_path) == 0
    finally:
        store.close()


@windows_only
def test_a_ninth_window_finds_no_slot_and_a_closed_one_frees_its_slot(tmp_path):
    db = str(tmp_path / "library_zh_0123456789abcdef.db")
    bells = [lw.Bell(db, lambda: None) for _ in range(lw.BELL_SLOTS + 1)]
    try:
        assert [b.slot for b in bells] == list(range(lw.BELL_SLOTS)) + [None]   # the ninth keeps its slow look
        bells[3].close()
        again = lw.Bell(db, lambda: None)
        assert again.slot == 3
        bells[3] = again
        assert lw.ring(db) == lw.BELL_SLOTS
    finally:
        for b in bells:
            b.close()


def test_off_windows_the_bell_is_silent(monkeypatch, tmp_path):
    monkeypatch.setattr(lw.sys, "platform", "darwin")
    monkeypatch.setattr(lw, "_k32", lambda: pytest.fail("kernel32 loaded off Windows"))
    assert lw.ring(str(tmp_path / "x.db")) == 0
    assert lw.Bell(str(tmp_path / "x.db"), lambda: None).slot is None
