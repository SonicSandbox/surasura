"""The switch to the library store (Library_Store_Spec §7 Phase 2, §10 WP-L8; L2.1 row 2.1.3).

`STORE_LIVE` is on: the dashboard's checks run on workers, the helper runs when it has something to do (at open,
2 s after the last trigger, at close in-process), the updater waits for a running helper and holds every
language's maintenance lock until the swap, and the dashboard's notice offers Repair and Try again. 2.4.0's
Content Manager on a 2.5 library is caught by the next 2.5 start (L-Q1, Q4-8).

Every test runs under conftest's temp SURASURA_TEST_ROOT, with libraries named with real Japanese and Chinese
words (tests/test_library_store_support.py); every store proof runs for both languages. Timed bounds are tight
only in the timed run (`SURASURA_STORE_BENCH=1`).
"""

import os
import subprocess
import sys
import threading
import time
import types
from unittest.mock import MagicMock, patch

import pytest
import tkinter as tk

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, library, migrated, names, read_doc, roots,
                                              subprocess_env, touch, write_manifest)

BENCH = bool(os.environ.get("SURASURA_STORE_BENCH"))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _store_library(language, **kw):
    data_dir, user_files_dir, doc = library(language, **kw)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return data_dir, user_files_dir, doc


def _pump(root, until, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def dashboard():
    """The real dashboard on a hidden root (as tests/test_zh_script_dashboard.py builds it)."""
    from app.main import MasterDashboardApp
    made = []

    def make(language="ja"):
        root = tk.Tk()
        root.withdraw()
        with patch.object(MasterDashboardApp, "check_updates_thread"):
            app = MasterDashboardApp(root)
        app.var_language.set(language)
        made.append(root)
        return app
    yield make
    for root in made:
        try:
            root.destroy()
        except Exception:
            pass


# --- #1 hato's drop reaches the next Generate with the Content Manager closed ------------------------- #

def _generated(language):
    """The library as a Generate left it: the run signature in the token store, the results and their stamp
    (the reopen-only path's own checks, `journey_is_current`)."""
    from app import analyzer, token_index
    argv = ["analyzer.py", "--language", language, "--static"]
    a = analyzer.parse_analysis_args(argv[1:])
    known = os.path.join(roots(language)[1], "KnownWord.json")
    with open(known, "w", encoding="utf-8") as f:
        f.write('{"words": []}')
    sig = analyzer.compute_run_signature(language, analyzer.resolve_found_files(language, verbose=False), a)
    store = token_index.open_store(language)
    store.set_meta("last_run_signature", sig)
    store.close()
    results = os.path.join(os.environ["SURASURA_TEST_ROOT"], "results")
    os.makedirs(results, exist_ok=True)
    for name in ("priority_learning_list.csv", "progressive_learning_list.csv", "word_stats.json"):
        with open(os.path.join(results, name), "w", encoding="utf-8") as f:
            f.write("x")
    analyzer._set_run_stamp(results, sig)
    return argv


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_hato_drop_turns_the_check_off_and_leads_the_next_generate(language):
    """WP-L8 #1: with the Content Manager closed, a file hato drops into HighPriority/Hato is taken in by the
    journey check's sync (the ✓ turns off), at the top of NOW, and the next Generate reads it first."""
    from app import analyzer
    data_dir, _uf, _doc = _store_library(language)
    argv = _generated(language)
    assert analyzer.journey_is_current(argv, language) is True
    rel = f"{ls.HATO_FOLDER}/{names(language)[40]}.srt"
    touch(data_dir, rel, names(language)[41])
    assert analyzer.journey_is_current(argv, language) is False, "the ✓ stays on after a hato drop"
    found = analyzer.resolve_found_files(language, verbose=False)
    assert os.path.relpath(found[0][0], data_dir).replace("\\", "/") == rel


@pytest.mark.parametrize("language", LANGUAGES)
def test_journey_checks_asked_together_share_their_syncs(language, monkeypatch):
    """§7: the journey check's syncs run one at a time; checks asked while one runs share one follow-up — five at
    once cost two walks, not five."""
    from app import analyzer
    walks = []
    monkeypatch.setattr(ls, "sync_for_window", lambda store: walks.append(1) or time.sleep(0.3))
    first = threading.Thread(target=analyzer._journey_sync, args=(ls, None, language))
    first.start()
    time.sleep(0.05)
    rest = [threading.Thread(target=analyzer._journey_sync, args=(ls, None, language)) for _ in range(4)]
    for t in rest:
        t.start()
    for t in [first] + rest:
        t.join(10)
    assert len(walks) == 2, walks
    analyzer._journey_sync(ls, None, language)                     # asked after both ended: a walk of its own
    assert len(walks) == 3


# --- #2 the focus handler never waits on the library ------------------------------------------------- #

@pytest.mark.parametrize("mode", ["store", "json"])
def test_the_focus_handler_hands_the_library_to_workers(dashboard, mode, monkeypatch):
    """WP-L8 #2: every library check focus starts (the content check, the indexer's list and stats, the journey
    check, the helper's trigger, the notice) runs on a worker — each mocked to take 300 ms, as a large library
    would; the handler itself returns in under 5 ms (timed run)."""
    from app import main as main_mod
    if mode == "store":
        _store_library("ja")
    else:
        data_dir, user_files_dir, doc = library("ja")
        write_manifest(user_files_dir, doc)
    app = dashboard("ja")
    slow = lambda *a, **k: time.sleep(0.3) or False                           # noqa: E731
    on_thread = []

    seen_off_thread = set()

    def watch(fn, name):
        def wrapped(*a, **k):
            (on_thread.append if threading.current_thread() is threading.main_thread() else seen_off_thread.add)(name)
            return fn(*a, **k)
        return wrapped
    for name in ("_folders_have_content", "_index_needed", "_library_state"):
        monkeypatch.setattr(main_mod.MasterDashboardApp, name, staticmethod(watch(slow, name)))
    monkeypatch.setattr(main_mod, "journey_is_current", watch(slow, "journey_is_current"))
    monkeypatch.setattr(ls, "sync_for_window", watch(slow, "sync_for_window"))
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    monkeypatch.delenv("SURASURA_NO_AUTOINDEX", raising=False)           # the indexer's check too (mocked: no launch)
    app._last_index_check = float("-inf")
    took = []
    for _ in range(3):
        app.__dict__.pop("_folder_content_walks", None)
        t0 = time.perf_counter()
        app.root.event_generate("<FocusIn>", when="now")
        took.append(time.perf_counter() - t0)
        app._last_index_check = float("-inf")
        app._indexer_busy = False
    _pump(app.root, lambda: False, timeout=1.5)                                 # the 600 ms / 2 s timers fire
    assert on_thread == [], f"ran on the window's thread: {on_thread}"
    assert seen_off_thread >= {"_index_needed", "_library_state"}, seen_off_thread
    took.sort()
    print(f"\n[{mode} mode] focus handler p50 {took[1] * 1000:.1f} ms, max {took[-1] * 1000:.1f} ms")
    assert took[1] < (0.005 if BENCH else 0.15), took


def test_generates_press_asks_on_a_worker_and_a_second_press_waits_for_it(dashboard, monkeypatch):
    """§7 (A10, A12): pressing Generate asks whether the report still holds on a worker (it syncs and stats every
    file) and goes on from the answer on the window's thread; a press while it asks starts nothing more."""
    from app import main as main_mod
    _store_library("ja")
    app = dashboard("ja")
    asked = []
    monkeypatch.setattr(main_mod.MasterDashboardApp, "_report_reusable",
                        lambda self, args: asked.append(threading.current_thread()) or time.sleep(0.3))
    started = []
    monkeypatch.setattr(app, "run_command_async", lambda *a, **k: started.append(a[0]))
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    t0 = time.perf_counter()
    app.run_analyzer()
    app.run_analyzer()                                             # a double click
    took = time.perf_counter() - t0
    assert took < (0.005 if BENCH else 0.1), took
    deadline = time.monotonic() + 5
    while not started and time.monotonic() < deadline:            # the window's queue, as its timer drains it
        try:
            app.gui_queue.get(timeout=0.05)()
        except Exception:
            pass
    assert len(asked) == 1 and asked[0] is not threading.main_thread()
    assert len(started) == 1 and started[0][0] == "analyzer.py"
    assert app._generate_running == "manual"
    assert not app._open_report_when_generated, "the second press would reopen the report after the run"


# --- #3 the close order; the updater waits for a running helper ---------------------------------------- #

def test_close_terminates_children_destroys_the_window_then_maintains():
    """§6.7 Close: the dashboard terminates its children, destroys its window, then runs the helper's work
    in-process for each language — never before the window is gone."""
    from app.main import MasterDashboardApp
    order = []
    app = MagicMock()
    app._update_job = None
    child = MagicMock()
    child.poll.return_value = None
    child.terminate.side_effect = lambda: order.append("terminate")
    app.active_processes = [child]
    app.root.destroy.side_effect = lambda: order.append("destroy")
    with patch.object(ls, "maintain_at_close", side_effect=lambda lang: order.append(f"maintain {lang}")):
        MasterDashboardApp.on_closing(app)
    assert order == ["terminate", "destroy", "maintain ja", "maintain zh"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_maintain_at_close_runs_only_with_something_to_do_and_never_waits(language):
    data_dir, user_files_dir, _doc = _store_library(language)
    assert ls.maintain_at_close(language) is None                              # exported already: nothing
    store = ls.open_store(language, data_dir, user_files_dir)
    ids = store.ids("now")
    store.move([ids[0]], "now", after_id=ids[-1])
    store.close()
    lock = ls.MaintenanceLock(ls.library_db_path(language, data_dir))
    assert lock.try_acquire()
    try:
        t0 = time.monotonic()
        assert ls.maintain_at_close(language) == ls.EXIT_BUSY                   # a helper is on it: no wait
        assert time.monotonic() - t0 < 1.0
    finally:
        lock.close()
    assert ls.maintain_at_close(language) == ls.EXIT_DONE
    assert read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"][-1]["physical_path"] == \
        read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"][-1]["physical_path"]


HOLD = ("import sys, time; sys.path.insert(0, %r)\n"
        "from app import library_store as ls\n"
        "lock = ls.MaintenanceLock(ls.library_db_path(%r, %r))\n"
        "assert lock.try_acquire()\n"
        "open(%r, 'w').close()\n"
        "time.sleep(%r)\n"
        "lock.close()\n")


def _hold_maintenance_lock(language, data_dir, flag, seconds):
    proc = subprocess.Popen([sys.executable, "-c", HOLD % (REPO, language, data_dir, flag, seconds)],
                            env=subprocess_env())
    deadline = time.monotonic() + 30
    while not os.path.exists(flag) and time.monotonic() < deadline:
        time.sleep(0.01)
    return proc


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_updater_waits_for_a_running_helper_then_holds_every_lock(language, tmp_path):
    """§7: the hand-over waits while a helper (another process) holds a maintenance lock — as for a running
    child — and once free takes every language's lock, held until this process exits."""
    from app import updater
    from app.main import MasterDashboardApp
    for lang in LANGUAGES:
        _store_library(lang)
    data_dir, _uf = roots(language)
    holder = _hold_maintenance_lock(language, data_dir, str(tmp_path / "held"), 30)
    try:
        assert updater.hold_library_locks() is None
        app = MagicMock()
        app._busy_threads.return_value = False
        job = {"staged": "x", "children": ["a helper"]}
        with patch.object(updater, "can_update_now", return_value=True), \
             patch.object(updater, "arm_and_launch") as arm:
            assert MasterDashboardApp._apply_and_restart(app, job) is False
        arm.assert_not_called()
        app.root.destroy.assert_not_called()
    finally:
        holder.kill()
        holder.wait(30)
    held = updater.hold_library_locks()
    try:
        assert held is not None and len(held) == len(LANGUAGES)
        out = subprocess.run([sys.executable, "-c",
                              "import sys; sys.path.insert(0, %r)\nfrom app import library_store as ls\n"
                              "sys.exit(ls.main(['maintain', '--language', %r]))" % (REPO, language)],
                             env=subprocess_env(), timeout=60)
        assert out.returncode == ls.EXIT_BUSY, "a helper ran while the updater held the lock"
    finally:
        updater.release_library_locks(held)


# --- #4 the update staged ---------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_update_staged_starts_no_helper_and_register_exits_5(language, real_store_helper):
    """S1.1: the update lock ("Update now" until the hand-over) is the store's update-staged signal: a helper
    the dashboard tries to spawn is never started, and hato's `register` exits 5."""
    from app import updater
    data_dir, user_files_dir, _doc = _store_library(language)
    lock = updater.take_update_lock()
    assert lock is not None
    try:
        assert ls.update_staged()
        assert ls.spawn_maintain(language) is None
        rel = touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[42]}.srt")
        assert ls.register_headless(language, rel, None) == ls.EXIT_BUSY
    finally:
        updater.drop_update_lock(lock)
    assert not ls.update_staged()


# --- #5 a burst of triggers costs one helper --------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_burst_of_triggers_within_2_s_spawns_one_helper(language, store_helper_spawns, monkeypatch):
    """§6.7 Idle: focus returns and a language switch inside 2 s → one check, one helper (a change is due)."""
    from app.main import MasterDashboardApp
    data_dir, user_files_dir, _doc = _store_library(language)
    with ls.open_store(language, data_dir, user_files_dir) as store:
        ids = store.ids("now")
        store.move([ids[0]], "now", after_id=ids[-1])
    root = tk.Tk()
    root.withdraw()
    try:
        app = types.SimpleNamespace(root=root, var_language=types.SimpleNamespace(get=lambda: language))
        app._maybe_maintain = lambda: MasterDashboardApp._maybe_maintain(app)
        monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
        for _ in range(5):
            MasterDashboardApp._schedule_maintain(app)
            _pump(root, lambda: False, timeout=0.2)
        assert store_helper_spawns == []
        assert _pump(root, lambda: bool(store_helper_spawns), timeout=4.0)
        _pump(root, lambda: False, timeout=0.5)
        assert store_helper_spawns == [(language,)]
        MasterDashboardApp._schedule_maintain(app)                           # the same stat: handed once
        _pump(root, lambda: False, timeout=2.6)
        assert len(store_helper_spawns) == 2, "a change still due is handed again"
    finally:
        root.destroy()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_first_start_on_a_2_4_library_starts_the_build(language, store_helper_spawns):
    """WP-L8 #9's last step: a 2.4.0 library (a manifest, no store) — the dashboard's trigger starts the helper,
    which builds the store (the analyzer builds it too, at Generate)."""
    from app.main import MasterDashboardApp
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    app = types.SimpleNamespace(var_language=types.SimpleNamespace(get=lambda: language))
    ls._build_spawned.pop(language, None)
    MasterDashboardApp._maybe_maintain(app)
    deadline = time.monotonic() + 10
    while not store_helper_spawns and time.monotonic() < deadline:
        time.sleep(0.02)
    assert store_helper_spawns == [(language,)]
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE      # what that helper does
    assert ls.check_mode(language, data_dir)[0] == "store"


# --- #6 a killed helper's temp file ------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_killed_helpers_temp_is_deleted_once_an_hour_old(language):
    data_dir, user_files_dir, _doc = _store_library(language)
    target = ls.manifest_path(user_files_dir)
    old, fresh = target + ".1234.tmp", target + ".5678.tmp"
    for path in (old, fresh):
        with open(path, "w", encoding="utf-8") as f:
            f.write("{")
    two_hours = time.time() - 7200
    os.utime(old, (two_hours, two_hours))
    with ls.open_store(language, data_dir, user_files_dir) as store:
        ids = store.ids("now")
        store.move([ids[0]], "now", after_id=ids[-1])
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert not os.path.exists(old) and os.path.exists(fresh)


# --- #7 Repair from the dashboard's notice ------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_repair_from_the_notice_closes_the_dashboards_own_handles_first(dashboard, language, real_store_helper):
    """§6.9: a damaged store shows the notice with Repair; Repair closes this window's own handles (Windows refuses
    the rename while one is open), runs the helper, and the store is back with its order."""
    data_dir, user_files_dir, _doc = _store_library(language)
    app = dashboard(language)
    with ls.open_store(language, data_dir, user_files_dir) as store:
        order = store.ids("now")
    assert app._library_handle(language) is not None                         # the dashboard's own handle, open
    db = ls.library_db_path(language, data_dir)
    ls.mark_damaged(db, "test")
    app._update_library_notice()
    assert app.library_notice.winfo_manager() == "pack" and "repair" in app.library_notice_var.get()
    assert app.btn_library_notice.cget("text") == "Repair"
    app._library_notice_action()
    assert _pump(app.root, lambda: not app.__dict__.get("_library_notice_busy"), timeout=60)
    assert "repaired" in app.status_var.get().lower(), app.status_var.get()
    assert not os.path.exists(ls.damaged_marker(db))
    assert any(".corrupt." in n for n in os.listdir(os.path.dirname(db))), "the damaged files are kept aside"
    assert ls.check_mode(language, data_dir)[0] == "store"
    with ls.open_store(language, data_dir, user_files_dir) as store:
        assert store.ids("now") == order
    assert app.library_notice.winfo_manager() == ""


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_failed_move_offers_try_again(dashboard, language, store_helper_spawns):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    with patch.object(ls, "_migrate", side_effect=RuntimeError("disk full")):
        assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    app = dashboard(language)
    app._update_library_notice()
    assert "couldn't be moved" in app.library_notice_var.get()
    assert app.btn_library_notice.cget("text") == "Try again"
    app._library_notice_action()
    assert store_helper_spawns == [(language, "--retry")]


# --- #9 2.5 arrives in place from 2.4.0 ---------------------------------------------------------------- #

REQUIREMENTS_2_4_0 = ["pandas", "fugashi", "unidic-lite", "pysrt", "EbookLib", "beautifulsoup4", "requests",
                      "tkinterdnd2; platform_system=='Windows'", "jieba", "pytest", "python-dotenv"]


def test_2_5_needs_no_new_runtime():
    """WP-L8 #9: the in-place update carries Surasura.exe, templates/ and RELEASE_NOTES.md only, so 2.5 may add no
    dependency 2.4.0's runtime lacks. The one line requirements.txt gained since 2.4.0, `zstandard` (S0.2), names a
    package 2.4.0 already imported (app/anki_utils.py, the .anki21b reader); the store is standard library only."""
    with open(os.path.join(REPO, "requirements.txt"), encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    assert [l for l in lines if l not in REQUIREMENTS_2_4_0] == ["zstandard"]
    assert all(l in lines for l in REQUIREMENTS_2_4_0)
    import ast
    tree = ast.parse(open(ls.__file__, encoding="utf-8").read())
    imported = {(n.module if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [None]) if n.__class__ is ast.Import or n.module}
    assert imported <= set(sys.stdlib_module_names) | {"app"}, imported - set(sys.stdlib_module_names)


def test_the_build_names_the_store_as_a_hidden_import():
    """§7: every caller imports the store inside a function; without the hidden import the frozen app would run
    in JSON mode for good and its helper would fail."""
    source = open(os.path.join(REPO, "packaging", "Surasura.spec"), encoding="utf-8").read()
    start = source.index("hiddenimports = [")
    assert "'app.library_store'" in source[start:source.index("]", start)]


# --- #10 2.4.0's Content Manager on a 2.5 library, then 2.5 again ------------------------------------- #

def _content_manager_2_4_0(language):
    """2.4.0's Content Manager as it touches the copy: 2.5's JSON mode (its code path, kept through Phase 2)."""
    from app.content_importer_gui import ContentImporterApp
    data_dir, user_files_dir = roots(language)
    cm = ContentImporterApp.__new__(ContentImporterApp)
    cm.language, cm.data_root, cm.user_files_root = language, data_dir, user_files_dir
    cm._warn_manifest_once = lambda *a, **k: None
    cm._manifest_unreadable = False
    cm._store_mode, cm._store = (lambda: "json"), (lambda: None)
    return cm


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_returning_2_4_0_puts_graduated_files_in_now_and_2_5_takes_them_back_out(language):
    """L-Q1 / K13: 2.4.0's disk sync puts a graduated file (still in its folder) back into NOW in the copy; on
    2.5's next start the item stays graduated, quietly (one item is under the size guard's 5 %)."""
    data_dir, user_files_dir, _doc = _store_library(language, shows=6, episodes=6)
    with ls.open_store(language, data_dir, user_files_dir) as store:
        graduated = store.ids("now")[0]
        rel = store.item(graduated)["rel_path"]
        store.set_tier([graduated], "graduated")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert rel not in [e["physical_path"] for e in read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"]]
    _content_manager_2_4_0(language)._sync_disk_to_manifest()
    assert rel in [e["physical_path"] for e in read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"]], \
        "2.4.0's sync puts it back (the caveat)"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    with ls.open_store(language, data_dir, user_files_dir) as store:
        assert store.item(graduated)["tier"] == "graduated"
        assert not store.meta().get("reimport_pending")
    assert rel not in [e["physical_path"] for e in read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"]], \
        "the copy is written again from the store"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NOTHING


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_returning_2_4_0s_big_change_waits_for_the_user(language):
    """Q4-8: 2.4.0's Content Manager reverses 6+ Months (well over 5 % of the items) → 2.5 asks first."""
    data_dir, user_files_dir, _doc = _store_library(language, shows=6, episodes=6)
    cm = _content_manager_2_4_0(language)
    cm.get_manifest_path = lambda: ls.manifest_path(user_files_dir)
    manifest = cm.load_manifest()
    manifest["schedule"]["PHASE_3_LATER"].reverse()
    cm.save_manifest(manifest)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    with ls.open_store(language, data_dir, user_files_dir) as store:
        assert store.meta().get("reimport_pending")


# --- L2.1 review (reviews/L2.1-adversary.md, L2.1-intent-keeper.md) ---------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_no_helper_is_spawned_while_a_size_guard_question_waits(language):
    """Adversary #5: while the user hasn't answered the size guard, the helper could only exit 4 — every trigger
    spawning it would start an exe per focus for nothing."""
    data_dir, user_files_dir, _doc = _store_library(language, shows=6, episodes=6)
    copy = read_doc(user_files_dir)
    copy["schedule"]["PHASE_3_LATER"].reverse()
    write_manifest(user_files_dir, copy)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    with ls.open_store(language, data_dir, user_files_dir) as store:
        ids = store.ids("now")
        store.move([ids[0]], "now", after_id=ids[-1])             # a change is due…
        assert store.export_due()
        assert ls.maintain_due(store)[0] is False                  # …but nothing to spawn until the answer


@pytest.mark.parametrize("language", LANGUAGES)
def test_read_only_mode_gives_every_reader_generates_list(language):
    """Adversary #6 / intent #10: in read-only mode the journey check, the indexer and the readers take the list
    Generate takes — the copy plus a file dropped in since — so the ✓ and Junban's check can match."""
    from app import analyzer, indexer
    data_dir, user_files_dir, _doc = _store_library(language)
    ls.mark_damaged(ls.library_db_path(language, data_dir), "test")
    rel = f"HighPriority/{names(language)[49]}.srt"
    touch(data_dir, rel, names(language)[50])
    generate = ls.read_only_schedule(language, data_dir, user_files_dir)
    schedule, _v = analyzer.read_library_schedule(language)
    assert schedule == generate
    listed = [os.path.relpath(p, data_dir).replace("\\", "/") for p, *_ in
              analyzer.resolve_found_files(language, verbose=False)]
    assert rel in listed
    assert os.path.normpath(os.path.join(data_dir, rel)) in         [os.path.normpath(p) for p in indexer._content_files(data_dir, language)]


def test_the_indexer_runs_for_the_language_it_was_checked_for():
    """Adversary #7: a language switch while the check runs must not index the other language."""
    from app.main import MasterDashboardApp
    app = MagicMock()
    app.var_language.get.return_value = "ja"                      # switched since the check asked about zh
    MasterDashboardApp._index_checked(app, True, "zh")
    assert app.run_command_async.call_args[0][0] == ["indexer.py", "--language", "zh"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_outside_change_taken_in_is_told_quietly_once(dashboard, language):
    """Intent #1 (D27 / Q4-8): a small outside edit of the order file is applied "and tells you quietly": the
    dashboard's status line says so once, and the note is cleared."""
    data_dir, user_files_dir, _doc = _store_library(language, shows=6, episodes=6)
    copy = read_doc(user_files_dir)
    now = copy["schedule"]["PHASE_1_NOW"]
    now.insert(0, now.pop())                                     # one row moved: under the 5 % guard
    write_manifest(user_files_dir, copy)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    app = dashboard(language)
    app._update_library_notice()
    assert "changed outside Surasura" in app.status_var.get(), app.status_var.get()
    app.status_var.set("Ready")
    app._update_library_notice()
    assert app.status_var.get() == "Ready", "told once"
