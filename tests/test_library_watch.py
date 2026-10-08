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
from tests.test_library_store_support import LANGUAGES, library, migrated, names, touch

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


# --- the hourly round, the slow look, the retry and the copy's watch ------------------------------------- #

def _full_round(store):
    """Every batch of one full round, the folders it hands back, in order."""
    rnd = ls.Round(store)
    found = []
    while not rnd.done:
        found += rnd.step()
    return found


def test_a_round_finds_a_file_dropped_into_a_folder_that_holds_no_item():
    # The old poll never looked at a folder with no item in it, so a file dropped there went unseen. A synced
    # library gives a round nothing to report; the new folder's file is the only thing it can find.
    store = migrated("ja")
    try:
        assert _full_round(store) == []
        folder = f"{ls.FOLDER_OF_TIER['now']}/新しい番組"
        touch(store.data_dir, f"{folder}/第01話.srt", "新しい番組 1\n")
        assert _full_round(store) == [folder]
    finally:
        store.close()


def test_a_round_batch_lists_at_most_max_folders(tmp_path):
    # Why: the hourly round is spread over many small batches so a big library never holds the window's thread;
    # a batch that lists past its folder cap defeats that. max_s is generous here, so only the cap can stop a batch.
    store = migrated("ja", shows=3, episodes=2, loose=1)
    try:
        rnd = ls.Round(store)
        k = 2
        for _ in range(200):                  # a bound: the queue must empty long before this
            if rnd.done:
                break
            before = rnd.listed
            rnd.step(max_folders=k, max_s=60.0)
            n, _seconds = rnd.batches[-1]
            assert n <= k, rnd.batches[-1]
            assert rnd.listed - before <= k
        assert rnd.done
        full = ls.Round(store)                # the same folders in one batch: the round covers every one of them
        full.step(max_s=60.0)
        assert full.done
        assert rnd.listed == full.listed and rnd.listed > k
    finally:
        store.close()


def test_a_round_batch_stops_when_its_time_is_up_but_always_lists_one_folder():
    # The hourly round (L3.2) works a batch at a time so a window never freezes: the time check stops a batch
    # even when `max_folders` is large. A fake clock (0.03 s a call) keeps the test instant and exact.
    store = migrated("ja")
    try:
        whole = ls.Round(store)
        while not whole.done:
            whole.step(max_s=10)
        total = whole.listed
        assert total > 3                                   # enough folders for a time limit to bite

        ticks = [0.0]

        def clock():
            now = ticks[0]
            ticks[0] += 0.03
            return now

        timed = ls.Round(store)
        timed.step(max_folders=10_000, max_s=0.05, clock=clock)
        assert 1 <= timed.listed <= 3                      # stopped after a few folders, not all of them
        assert timed.listed < total
        assert timed.batches[-1][0] == timed.listed

        # Time already up at the first folder: that one is still listed, and no more.
        ticks[0] = 0.0
        instant = ls.Round(store)
        instant.step(max_folders=10_000, max_s=0.0, clock=clock)
        assert instant.listed == 1
    finally:
        store.close()


def test_a_missing_item_whose_file_is_still_on_disk_makes_its_folder_differ():
    # why: only available items count as held, so a file the store marks missing is one it doesn't hold
    store = migrated("ja")
    try:
        assert _full_round(store) == []                 # the synced store is quiet first (the mutant's baseline)
        item = store.ids("now")[0]
        rel = store.item(item)["rel_path"]
        folder = rel.rsplit("/", 1)[0]
        with store._writing():
            store.conn.execute("UPDATE items SET availability = 'missing' WHERE id = ?", (item,))
        assert os.path.exists(os.path.join(store.data_dir, *rel.split("/")))   # the file really is still there
        assert folder in _full_round(store)
    finally:
        store.close()


def test_an_available_item_whose_file_was_deleted_makes_its_folder_differ():
    # why: a held item with no file on disk is a difference the round must report for a scoped sync
    store = migrated("zh")
    try:
        assert _full_round(store) == []
        item = store.ids("now")[0]
        rel = store.item(item)["rel_path"]
        folder = rel.rsplit("/", 1)[0]
        os.remove(os.path.join(store.data_dir, *rel.split("/")))
        assert folder in _full_round(store)
    finally:
        store.close()


def test_the_slow_look_runs_only_in_front_and_at_most_once_per_slow_s(monkeypatch):
    # Off Windows there is no tree watch, so the slow look stands in for it: it runs while the window is in front,
    # at most once per SLOW_S (a fake hour: 360 looks in front), and never behind — a background window never polls.
    monkeypatch.setattr(lw.sys, "platform", "linux")
    store = migrated("ja")
    now = [1000.0]
    look = lw.Lookout(store.data_dir, db_path=store.db_path, clock=lambda: now[0]).open()
    try:
        look.set_front(False)
        behind = 0
        for k in range(3600):
            now[0] = 1000.0 + k
            behind += look.jobs(now=now[0]).slow
        assert behind == 0 and look.slow_looks == 0

        look.set_front(True)
        looks = []
        for k in range(3600):
            now[0] = 5000.0 + k
            if look.jobs(now=now[0]).slow:
                looks.append(now[0])
        assert len(looks) == 3600 // lw.SLOW_S
        assert all(b - a >= lw.SLOW_S for a, b in zip(looks, looks[1:]))
    finally:
        look.close()
        store.close()


# --- the window's focus (Windows) ------------------------------------------------------------------------- #

@windows_only
def test_a_root_renamed_away_is_noticed_on_focus_and_watched_again_once_back(tmp_path):
    # Windows sends no report for the watched folder's own rename, so focus() compares the folder at the path with
    # the one watched: renamed away, the watch falls back; a folder put back at the path is watched again.
    now = [1000.0]
    data_dir = str(tmp_path / "ライブラリ")
    os.makedirs(os.path.join(data_dir, "LowPriority", "番組"))
    lk = lw.Lookout(data_dir, under=TIER_FOLDERS, clock=lambda: now[0]).open()
    try:
        assert lk.tree.state == "watching"
        os.rename(data_dir, str(tmp_path / "ライブラリ_退避"))
        assert lk.focus(now=now[0]) is False and lk.tree.state == "fallback"
        os.makedirs(data_dir)
        assert lk.focus(now=now[0]) is True and lk.tree.state == "watching"
    finally:
        lk.close()


@windows_only
def test_focus_without_a_rename_leaves_the_watch_alone(tmp_path):
    # The same folder at the path: focus() restarts nothing, so the watch thread that is running stays the one.
    now = [1000.0]
    data_dir = str(tmp_path / "ライブラリ")
    os.makedirs(os.path.join(data_dir, "LowPriority", "番組"))
    lk = lw.Lookout(data_dir, under=TIER_FOLDERS, clock=lambda: now[0]).open()
    try:
        thread = lk.tree._thread
        assert lk.focus(now=now[0]) is False
        assert lk.tree.state == "watching" and lk.tree._thread is thread
    finally:
        lk.close()


def test_the_round_waits_an_hour_then_hands_out_one_batch_every_two_seconds():
    # The hourly round (L3.2) on a fake clock: due an hour after the last full look, then one batch per ROUND_GAP_S.
    # A batch in the same two seconds is refused (a gap-less round would hand the same Round back at +0.5 s), and a
    # full look drops a round under way and restarts the hour.
    store = migrated("ja")
    now = [1000.0]
    rounds = []

    def make_round():
        rounds.append(ls.Round(store))
        return rounds[-1]

    lk = lw.Lookout(store.data_dir, make_round=make_round, clock=lambda: now[0]).open()
    lk.set_front(False)                                   # no slow look: its wait would hide the round's own
    try:
        assert lk.jobs(now=now[0]).round is None
        now[0] = 1000.0 + lw.ROUND_S
        first = lk.jobs(now=now[0]).round
        assert isinstance(first, ls.Round)
        now[0] += 0.5
        assert lk.jobs(now=now[0]).round is None          # inside the gap: no batch
        now[0] = 1000.0 + lw.ROUND_S + lw.ROUND_GAP_S
        assert lk.jobs(now=now[0]).round is first         # the gap has passed: the same round's next batch
        lk.looked(now=now[0])
        assert lk.jobs(now=now[0]).round is None          # the full look covered it: no round under way
        assert abs(lk.timeout(now=now[0]) - lw.ROUND_S) < 1.0
    finally:
        lk.close()
        store.close()


@windows_only
def test_a_failed_watch_is_retried_after_retry_s_and_then_asks_one_full_look(tmp_path):
    # A library folder that doesn't exist yet can't be watched, so the watch falls back. It is retried only once
    # RETRY_S has passed, and the restart asks one full look PROVEN_S later, the watch still up: it missed what happened
    # while it was down.
    now = [1000.0]
    data_dir = str(tmp_path / "ライブラリ")
    lk = lw.Lookout(data_dir, under=TIER_FOLDERS, clock=lambda: now[0]).open()
    try:
        assert lk.tree.state == "fallback"
        os.makedirs(data_dir)
        now[0] += lw.RETRY_S - 1                              # just short of the retry: still no watch, no full look
        early = lk.jobs(now=now[0])
        assert lk.tree.state == "fallback" and early.full is False
        now[0] += 1                                           # RETRY_S exactly: the watch starts; its look waits
        late = lk.jobs(now=now[0])
        assert lk.tree.state == "watching" and late.full is False
        assert lk.timeout(now=now[0]) <= lw.PROVEN_S          # the worker wakes for it
        now[0] += lw.PROVEN_S                                 # still up PROVEN_S later: one full look
        assert lk.jobs(now=now[0]).full is True
        assert lk.jobs(now=now[0]).full is False              # once
    finally:
        lk.close()


@windows_only
def test_the_copy_watch_wakes_on_the_copy_saved_by_rename_and_not_on_other_files(tmp_path):
    # The library's copy is saved by a rename (temp file + os.replace), which Windows reports at once; a write to any
    # other file in the same folder must not look at the copy, or every KnownWord save would re-read the library.
    folder = tmp_path / "番組"
    folder.mkdir()
    w = lw.FileWatch(str(folder), ["master_manifest.json"])
    assert w.start(), (w.state, w.error)
    try:
        (folder / "KnownWord.json").write_text('{"語": 1}', encoding="utf-8")
        w.wait(0.5)                                       # bounded: proving an absence
        folders, full = w.take()
        assert folders == [] and not full
        tmp = folder / "master_manifest.json.tmp"
        tmp.write_text('{"order": []}', encoding="utf-8")
        os.replace(str(tmp), str(folder / "master_manifest.json"))
        folders, full = _settled(w, full=True)
        assert folders == set() and full
    finally:
        w.close()


@windows_only
def test_a_window_with_no_bell_slot_keeps_the_slow_look_until_focus_finds_one(tmp_path):
    # A ninth window watches its tree but can't hear other processes, so it keeps the slow look; the first focus
    # after a slot frees (the window coming back) takes that slot, and the slow look stops.
    data_dir, _u, _doc = library("ja")
    db = str(tmp_path / "library_ja_fedcba9876543210.db")
    now = [1000.0]
    holders = [lw.Bell(db, lambda: None) for _ in range(lw.BELL_SLOTS)]
    w = None
    try:
        assert all(b.slot is not None for b in holders)
        w = lw.Lookout(data_dir, under=TIER_FOLDERS, db_path=db, clock=lambda: now[0]).open()
        assert w.tree.alive and w.bell.slot is None         # watching, yet no slot
        assert w.slow                                       # so the slow look stands in
        holders[3].close()
        w.focus(now=now[0])
        assert w.bell.slot == 3 and not w.slow              # the freed slot is the window's now
    finally:
        if w is not None:
            w.close()
        for b in holders:
            b.close()


# --- the first review's fixes: tier folders, a thread that ends, the damaged mark, retries, paging ----------- #

@windows_only
def test_a_file_outside_the_tier_folders_is_no_report_while_a_tier_file_is():
    # Under the data folder, a folder that is no tier folder (その他, a note of the user's) is no sync: the watch's
    # `under` filter drops its report, and the tier folder's report still comes through, once.
    data_dir, _u, _doc = library("ja")
    w = _watch(data_dir)
    try:
        soon = os.path.join(data_dir, "LowPriority")
        show = sorted(d for d in os.listdir(soon) if os.path.isdir(os.path.join(soon, d)))[0]
        touch(data_dir, "その他/メモ.srt", "メモ\n")
        touch(data_dir, f"LowPriority/{show}/{show}_第98話.srt", f"{show}\n")
        seen, full = _settled(w, want=[f"LowPriority/{show}"])
        time.sleep(0.2)                                   # the outside report, if one came, has settled too
        seen |= set(w.take(time.monotonic() + 10)[0])
        assert seen == {f"LowPriority/{show}"} and not full   # never the その他 folder, never the whole tier
    finally:
        w.close()


@windows_only
def test_a_tier_folder_spelled_in_capitals_on_disk_is_still_matched(tmp_path):
    # NTFS compares names in any case, so a show dropped into HIGHPRIORITY/ is the High priority tier's: `under` is
    # lowered once in TreeWatch, and the report's name must be lowered too. The capitals on disk are what make the
    # test sensitive to that: a lowercase spelling would match the un-lowered comparison as well.
    root = str(tmp_path / "library")
    os.makedirs(os.path.join(root, "HIGHPRIORITY"))
    w = lw.TreeWatch(root, settle=0.05, under=("HighPriority",))
    assert w.start(), (w.state, w.error)
    try:
        touch(root, "HIGHPRIORITY/番組/第01話.srt", "第01話\n")
        seen, _full = _settled(w, want=["HIGHPRIORITY/番組"])
        assert "HIGHPRIORITY/番組" in seen
    finally:
        w.close()


@windows_only
def test_the_copy_watch_wakes_on_the_copy_rewritten_in_place(tmp_path):
    # The deprecated Immersion Architect saves the copy by opening the existing file and writing over it, not by a
    # rename. Windows reports that only as a last-write change, so the watch must listen for it or an in-place save
    # goes unseen.
    folder = tmp_path / "番組"
    folder.mkdir()
    manifest = folder / "master_manifest.json"
    manifest.write_text('{"order": []}', encoding="utf-8")
    w = lw.FileWatch(str(folder), ["master_manifest.json"])
    assert w.start(), (w.state, w.error)
    try:
        with open(str(manifest), "w", encoding="utf-8") as f:
            f.write('{"order": ["LowPriority/番組"]}')
        folders, full = _settled(w, full=True)
        assert folders == set() and full
    finally:
        w.close()


def test_a_tier_folder_renamed_away_is_its_own_sync(tmp_path):
    # A tier folder gone from the top (renamed or deleted) is reported as itself: its scoped sync marks its items
    # missing. Never "" (the root): that report would be dropped and the tier's items would stay "present".
    root = str(tmp_path)
    assert lw.folders_of(root, "LowPriority", 4) == ["LowPriority"]       # renamed away: old name
    assert lw.folders_of(root, "LowPriority", 2) == ["LowPriority"]       # deleted


@windows_only
def test_a_tier_folder_renamed_away_is_reported_itself():
    # The live half of the same rule: renaming LowPriority/ away wakes a sync of LowPriority itself (Windows sends
    # the old name), and the new top-level name, not a tier folder, wakes nothing.
    data_dir, _u, _doc = library("ja")
    w = _watch(data_dir)
    try:
        tier = os.path.join(data_dir, "LowPriority")
        os.rename(tier, os.path.join(data_dir, "LowPriority_改"))
        seen, _f = _settled(w, want=["LowPriority"])
        time.sleep(0.2)                                   # the new name's report, if one came, has settled too
        seen |= set(w.take(time.monotonic() + 10)[0])
        assert "LowPriority" in seen and seen <= {"LowPriority"}
    finally:
        w.close()


@windows_only
def test_a_watch_thread_that_ends_by_itself_reads_ended_and_wakes_the_window_closed_reads_closed():
    # Windows' wait fails at once and nothing closes the watch: the thread ends on its own. That must read "ended"
    # and wake the window (so its retry takes over) — never sit as "watching". close() is the contrast: "closed".
    # A fresh watch has no handle yet, so start() doesn't set the wake event: a wake seen here came from the thread.
    data_dir, _u, _doc = library("ja")
    w = lw.TreeWatch(data_dir, under=TIER_FOLDERS)
    w._read = lambda buf, got: None
    try:
        assert w.start()
        woke = w.wait(2.0)
        assert woke, "the window was not woken when its watch thread ended"
        assert w.state == "ended" and not w.alive
    finally:
        w.close()

    w2 = _watch(data_dir)
    assert w2.alive
    w2.close()
    assert w2.state == "closed" and not w2.alive


@windows_only
def test_marking_a_store_damaged_rings_its_bell():
    # A window sleeping on its watch must look again when the store is marked damaged (L3.2): the marker alone
    # is not enough, the listener on that store has to be rung once by mark_damaged itself.
    store = migrated("ja")
    bell = lw.Bell(store.db_path, lambda: None)
    try:
        assert bell.slot is not None                         # it really listens, or the ring proves nothing
        ls.mark_damaged(store.db_path, "テスト")
        assert _rung(bell) == 1                              # one ring, from the damage and nothing else
        assert os.path.exists(ls.damaged_marker(store.db_path))
    finally:
        if os.path.exists(ls.damaged_marker(store.db_path)):
            os.remove(ls.damaged_marker(store.db_path))      # the marker must not outlive this test
        bell.close()
        store.close()


@windows_only
def test_a_copy_watch_that_stopped_is_started_again_at_the_retry_and_asks_a_look(tmp_path):
    # The copy's watch that ended on its own is not started at once: it waits RETRY_S, as the tree's watch does, and
    # the restart reports the copy as changed, because the copy may have been saved while no watch was listening.
    data_dir, user_files, _doc = library("ja")
    os.makedirs(user_files, exist_ok=True)                    # the copy's folder: the watch can't start without it
    copy_path = os.path.join(user_files, "master_manifest.json")
    now = [1000.0]
    lk = lw.Lookout(data_dir, under=TIER_FOLDERS, copy=copy_path, clock=lambda: now[0]).open()
    try:
        assert lk.copy.alive
        lk.copy.close()                                       # as if the copy's watch had ended by itself
        assert not lk.copy.alive
        now[0] += lw.RETRY_S - 1                              # just short of the retry: the copy's watch stays down
        early = lk.jobs(now=now[0])
        assert early.copy is False and not lk.copy.alive
        now[0] += 1                                           # RETRY_S exactly: started again, and the copy is asked
        late = lk.jobs(now=now[0])
        assert lk.copy.alive and late.copy is True
    finally:
        lk.close()


def test_a_round_reads_a_folder_of_more_than_one_page_of_items():
    # Why: the round reads a folder's held items a page of 256 at a time (`Round._held`). A folder of 300 episodes
    # is two pages, so the round must read the second page too: it finds nothing while the folder matches the
    # store, and it finds the folder when an episode past the first page is deleted.
    store = migrated("ja")
    try:
        folder = f"{ls.FOLDER_OF_TIER['now']}/長い番組"
        paths = [touch(store.data_dir, f"{folder}/第{i:03d}話.srt", f"長い番組 {i}\n") for i in range(1, 301)]
        ls.sync_for_window(store, folders=[folder])
        assert store.conn.execute("SELECT COUNT(*) FROM items WHERE rel_key LIKE ?",
                                  (ls.path_key(folder) + "/%",)).fetchone()[0] == 300
        assert _full_round(store) == []
        os.remove(paths[299])                  # the 300th episode: only the second page holds it
        assert _full_round(store) == [folder]
    finally:
        store.close()


@windows_only
def test_a_bell_whose_thread_ended_reads_deaf_and_slow_until_focus_makes_a_new_one(tmp_path):
    # Why: a bell whose thread ended by itself (its wait failed) hears nothing, so the window must not sit on the
    # watch's quiet path: it reads deaf and slow (the slow look stands in) until a focus makes a new bell in a slot.
    data_dir, _u, _doc = library("ja")
    db = str(tmp_path / "library_ja_0123456789abcdef.db")
    now = [1000.0]
    look = lw.Lookout(data_dir, under=TIER_FOLDERS, db_path=db, clock=lambda: now[0]).open()
    try:
        assert look.bell is not None and look.bell.slot is not None and look.bell.alive
        assert not look.deaf and not look.slow
        look.bell._k32.SetEvent(look.bell._stop)              # end the bell's thread without closing the bell
        look.bell._thread.join(2.0)
        assert not look.bell.alive
        assert look.deaf and look.slow
        look.focus(now=now[0])                                # the retry: a new bell, in a slot
        assert look.bell.alive and not look.deaf and not look.slow
    finally:
        look.close()


@windows_only
def test_a_watch_whose_events_cant_be_made_falls_back_and_starts_no_thread(monkeypatch, tmp_path):
    # the folder opens but its event objects can't be made: the watch gives up cleanly (no watching state, no
    # thread that never wakes), so the window keeps its slow look instead of a watch that hangs half-open
    real_k32 = lw._k32

    class _NoEvents:
        def __init__(self, k32):
            self._k32 = k32

        def __getattr__(self, name):
            return getattr(self._k32, name)

        def CreateEventW(self, *args):
            return 0

    monkeypatch.setattr(lw, "_k32", lambda: _NoEvents(real_k32()))
    w = lw.TreeWatch(str(tmp_path))
    try:
        assert w.start() is False
        assert w.state == "fallback"
        assert w.alive is False
    finally:
        w.close()


@windows_only
def test_a_watch_that_ends_at_once_after_its_retry_costs_no_full_look(monkeypatch, tmp_path):
    # A share that opens but can't report: the retry starts the watch, its first read fails at once and the thread
    # ends. The slow look stands in for it, so PROVEN_S later there is no full look (one every RETRY_S would be a
    # full tree look for each retry on a share that never reports). The contrast, a watch that stays up, is above.
    monkeypatch.setattr(lw, "_last_error", lambda: 64)    # ERROR_NETNAME_DELETED
    now = [1000.0]
    data_dir = str(tmp_path / "ライブラリ")
    lk = lw.Lookout(data_dir, under=TIER_FOLDERS, clock=lambda: now[0]).open()
    try:
        assert lk.tree.state == "fallback"
        os.makedirs(data_dir)
        now[0] += lw.RETRY_S
        lk.tree._read = lambda buf, got: False            # the share opens, but its first read fails at once
        assert lk.jobs(now=now[0]).full is False          # the retry starts the watch; its look is owed, not yet
        deadline = time.monotonic() + 5.0
        while lk.tree.state != "ended" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert lk.tree.state == "ended" and lk.tree.alive is False
        now[0] += lw.PROVEN_S
        assert lk.jobs(now=now[0]).full is False          # it ended meanwhile: no full look
    finally:
        lk.close()


@windows_only
def test_a_folder_reported_before_the_watch_ended_still_wakes_the_worker_at_its_settle_time(tmp_path):
    # A folder the watch reported just before its thread ended is still owed its sync: the worker must wake at the
    # settle time (seconds), not at the retry's RETRY_S, and hand the folder out once it has settled. The clock is
    # fake and no thread runs: the state and the pending report are set directly, so nothing waits on the disk.
    data_dir, _u, _doc = library("ja")
    now = [5000.0]
    lk = lw.Lookout(data_dir, under=TIER_FOLDERS, clock=lambda: now[0])
    lk.front = False                                      # no slow look: its own timer would hide the settle time
    try:
        lk.tree.state = "ended"                           # the watch's thread ended by itself after the report
        lk.tree._pending["HighPriority"] = now[0]
        wait = lk.timeout(now=now[0])
        assert wait <= lk.tree.settle + 1e-6, f"worker sleeps {wait:.1f} s, past the settle time"
        assert wait < lw.RETRY_S / 2

        now[0] += lk.tree.settle / 2                      # not yet settled: nothing handed out
        assert lk.jobs(now=now[0]).folders == []

        now[0] += lk.tree.settle                          # settled: the folder is handed out
        assert lk.jobs(now=now[0]).folders == ["HighPriority"]
    finally:
        lk.tree._pending.clear()
        lk.tree.state = "closed"
        lk.close()


@windows_only
def test_an_old_watch_thread_that_outlives_close_leaves_the_new_watch_alone(monkeypatch):
    # a hung share: the first thread's read is still stuck when close() gives up waiting (CLOSE_JOIN_S), and it fails
    # only after a new start(). That late end must not mark the new watch "ended": it stays watching, its thread alive
    import threading
    monkeypatch.setattr(lw, "CLOSE_JOIN_S", 0.05)
    monkeypatch.setattr(lw, "_last_error", lambda: 64)    # ERROR_NETNAME_DELETED: a failed read, not our own close
    data_dir, _u, _doc = library("ja")
    release, entered, calls = threading.Event(), threading.Event(), []

    def read(buf, got):
        if not calls:                       # the first thread only: a read that hangs, then fails late
            calls.append(1)
            entered.set()
            release.wait(5.0)
            return False
        deadline = time.monotonic() + 5.0   # the new thread reads until its own watch is closed
        while w.state == "watching" and time.monotonic() < deadline:
            time.sleep(0.01)
        return None

    w = lw.TreeWatch(data_dir, under=TIER_FOLDERS)
    w._read = read
    try:
        assert w.start()
        old = w._thread
        assert entered.wait(5.0), "the first watch thread never reached its read"
        w.close()                           # waits 0.05 s; the first thread is still stuck in its read
        assert w.start()
        release.set()
        old.join(5.0)
        assert not old.is_alive(), "the late read never ended"
        assert w.state == "watching" and w.alive
        assert w.error is None
    finally:
        release.set()
        w.close()


def test_a_show_folder_deleted_from_disk_makes_its_tier_folder_differ():
    # why: the store still holds items in a show folder that is gone from disk, with no sync: the round must hand back
    # the tier folder that held it, and never the vanished show folder itself (nothing lists it any more)
    store = migrated("ja")
    try:
        assert _full_round(store) == []                       # a synced library is quiet first
        rels = [store.item(i)["rel_path"] for i in store.ids("now")]
        rel = next(r for r in rels if r.count("/") >= 2)      # an item inside a show folder, not a loose file
        tier, show = rel.split("/")[0], rel.rsplit("/", 1)[0]
        shutil.rmtree(os.path.join(store.data_dir, *show.split("/")))
        found = _full_round(store)
        assert tier in found
        assert show not in found
    finally:
        store.close()
