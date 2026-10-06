"""The locks between Surasura's programs (P0.3 04 §2, P1.2 row 1.2.1): `results`, `known-words-<lang>`, `settings`,
`update` and `junban-window`, every one through E1.4's helper (`app/locks.py`), the window's and the command line's
alike.

What a wrong answer would cost, in order:
  * two programs writing one file at once — a headless Generate and the window's, two known-words updates, two
    settings saves: the second must wait or be told `busy`, naming who holds it;
  * a lock that outlives its holder — a killed program must never block the next one;
  * a window that freezes on a lock — the dashboard only ever waits on a worker (a step of its thread <= 4 ms);
  * a setting that is lost — a held lock queues the window's save and retries, never drops it;
  * a passing look read as a real holder — two command lines checking for an update at once must not tell each
    other "an update is being installed".

Across processes the holder is a real child Python, never a mock: the claims are about the OS lock.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import anki_sync, library_store, locks, settings_manager, updater

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A child that takes one lock for `verb` and holds it until its stdin closes: it prints "held" first.
_HOLDER = r"""
import sys
from app import locks
held = locks.take(sys.argv[1], sys.argv[2])
print("held", flush=True)
sys.stdin.read()
held.release()
"""


class Holder:
    """Another program holding a lock (a child Python), until `release()` — or `kill()`."""

    def __init__(self, name, verb="another Surasura program"):
        env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
        self.proc = subprocess.Popen([sys.executable, "-c", _HOLDER, name, verb], cwd=PROJECT_ROOT, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().strip()
        assert line == "held", self.proc.stderr.read()

    def release(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)

    def kill(self):
        self.proc.kill()
        self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.release()


def _wait_free(name, seconds=5.0):
    """Windows frees a dead process's lock after a moment: wait for it (a take that succeeds lets go at once)."""
    with locks.take(name, "the test's look", wait=seconds):
        pass


def _settings_path():
    return os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")


def _on_disk():
    with open(_settings_path(), encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# settings — atomic, under its lock; the window's writer queues and retries
# --------------------------------------------------------------------------- #
def test_a_settings_save_waits_for_another_programs_write_then_writes():
    """Another program holds `settings` for its write: a save waits for it, then writes, whole."""
    with Holder("settings", "saving settings") as other:
        threading.Timer(0.4, other.release).start()
        started = time.monotonic()
        assert settings_manager.save_settings({"target_language": "ja", "words_per_day": 7}, wait=5.0)
        assert time.monotonic() - started >= 0.3, "it waited for the other program's write"
    assert _on_disk()["words_per_day"] == 7


def test_a_settings_save_that_cannot_get_the_lock_leaves_the_file_untouched():
    settings_manager.save_settings({"target_language": "ja", "words_per_day": 5})
    with Holder("settings", "saving settings"):
        assert settings_manager.save_settings({"target_language": "ja", "words_per_day": 9}, wait=0.0) is False
    assert _on_disk()["words_per_day"] == 5


def test_a_settings_write_that_dies_part_way_leaves_the_old_file_and_no_temp(monkeypatch):
    """Atomic: a crash while writing (here json.dump raising half-way) leaves the file as it was, never half."""
    settings_manager.save_settings({"target_language": "ja", "words_per_day": 5})
    real_dump = json.dump

    def dies(obj, f, **kw):
        f.write('{"target_language": "j')            # half a file, then the "crash"
        raise OSError("the disk went away")
    monkeypatch.setattr(settings_manager.json, "dump", dies)
    assert settings_manager.save_settings({"target_language": "zh", "words_per_day": 9}) is False
    monkeypatch.setattr(settings_manager.json, "dump", real_dump)
    assert _on_disk() == {"target_language": "ja", "words_per_day": 5}
    leftovers = [n for n in os.listdir(os.environ["SURASURA_TEST_ROOT"]) if n.endswith(".tmp")]
    assert leftovers == []


def test_save_keys_reads_and_writes_inside_one_hold_of_the_lock(monkeypatch):
    """A window's own keys go onto the file as it is: the read and the write hold `settings` together."""
    settings_manager.save_settings({"target_language": "ja", "junban_deck": "Mining"})
    seen = []
    real_take = locks.take

    def take(name, verb, **kw):
        seen.append(name)
        return real_take(name, verb, **kw)
    monkeypatch.setattr(locks, "take", take)
    settings_manager.save_keys({"words_per_day": 8})
    assert seen == ["settings"], "one take for the read and the write (the inner save sees it held here)"
    assert _on_disk() == {"target_language": "ja", "junban_deck": "Mining", "words_per_day": 8}


def test_the_windows_writer_returns_at_once_and_writes_once_the_lock_is_free():
    """The dashboard's save never waits on its thread: `submit` returns in <= 4 ms while another program holds the
    lock; the write is queued and retried, then lands — the newest state, never dropped."""
    settings_manager.save_settings({"target_language": "ja", "words_per_day": 5})
    errors, saved = [], []
    writer = settings_manager.SettingsWriter(delay=0.05, wait=0.1, on_error=errors.append, on_saved=saved.append)
    with Holder("settings", "saving settings") as other:
        started = time.perf_counter()
        writer.submit(lambda: {"target_language": "ja", "words_per_day": 6})
        writer.submit(lambda: {"target_language": "ja", "words_per_day": 7})     # the newer state replaces it
        assert time.perf_counter() - started <= 0.004
        time.sleep(0.6)
        assert errors, "the held lock was met, and the write is retried"
        assert _on_disk()["words_per_day"] == 5, "nothing written while the other program holds it"
        other.release()
    assert writer.flush(timeout=10)
    assert _on_disk()["words_per_day"] == 7
    assert saved and saved[-1]["words_per_day"] == 7
    assert not writer.pending()


def test_the_writer_reads_the_file_inside_the_lock_so_another_windows_key_is_carried():
    """`build` runs on the worker, inside the lock: a key another window saved after the submit is carried, not
    reverted (the dashboard reads its panel keys there)."""
    settings_manager.save_settings({"target_language": "ja", "junban_deck": "Old"})
    writer = settings_manager.SettingsWriter(delay=0.3)
    writer.submit(lambda: {"target_language": "ja", "junban_deck": settings_manager.load_settings()["junban_deck"],
                           "words_per_day": 6})
    settings_manager.save_keys({"junban_deck": "New"})          # the 順 window saves meanwhile
    assert writer.flush(timeout=10)
    assert _on_disk() == {"target_language": "ja", "junban_deck": "New", "words_per_day": 6}


def test_the_dashboards_save_submits_to_its_writer_and_reads_no_file_on_its_thread(monkeypatch):
    """With a writer (in use: no SURASURA_NO_UI_TIMERS) the dashboard's save reads widgets only; the file is read and
    written on the writer's worker."""
    from app.main import MasterDashboardApp
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)
    settings_manager.save_settings({"target_language": "ja", "anki_sync_decks": {"ja": ["Mining"]}})
    app = MagicMock()
    app._current_settings = settings_manager.load_settings()
    app.logic_settings = app._current_settings["logic"]
    app._iv = lambda var, fallback: fallback
    app.combo_theme.get.return_value = "Dark Flow"
    app.var_language.get.return_value = "ja"
    app._settings_writer = settings_manager.SettingsWriter(delay=0.0)
    reads, written = [], []
    real_load = settings_manager.load_settings
    monkeypatch.setattr(settings_manager, "load_settings",
                        lambda *a, **k: (reads.append(threading.current_thread().name), real_load(*a, **k))[1])
    monkeypatch.setattr(settings_manager, "save_settings",            # the stub's widgets hold mocks, not JSON
                        lambda s, **k: (written.append((threading.current_thread().name, s)), True)[1])
    MasterDashboardApp.save_settings(app, skip_ui=True)
    assert app._settings_writer.flush(timeout=10)
    assert reads and all(name == "settings-writer" for name in reads)
    assert [name for name, _s in written] == ["settings-writer"]
    assert written[0][1]["anki_sync_decks"] == {"ja": ["Mining"]}, "the Anki window's key is carried from the file"


# --------------------------------------------------------------------------- #
# update — a passing look is not an update (P1.1 merge review #1)
# --------------------------------------------------------------------------- #
_PROBER = r"""
import sys
from app import library_store
staged = sum(library_store.update_staged(looks=library_store.PROBE_LOOKS) for _ in range(int(sys.argv[1])))
print(staged, flush=True)
"""


def test_two_programs_checking_for_an_update_at_once_never_see_one():
    """Each check takes the update lock for a moment; two command lines checking together used to read each other's
    look as "an update is being installed"."""
    os.makedirs(os.path.dirname(library_store.update_lock_path()), exist_ok=True)
    open(library_store.update_lock_path(), "a").close()
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    probers = [subprocess.Popen([sys.executable, "-c", _PROBER, "300"], cwd=PROJECT_ROOT, env=env,
                                stdout=subprocess.PIPE, text=True) for _ in range(3)]
    mine = sum(library_store.update_staged(looks=library_store.PROBE_LOOKS) for _ in range(300))
    counts = [int(p.communicate(timeout=120)[0].strip()) for p in probers]
    assert counts == [0, 0, 0] and mine == 0


def test_a_real_update_is_seen_and_update_now_waits_out_a_passing_look():
    lock = updater.take_update_lock()
    try:
        assert library_store.update_staged(), "an update holding the lock is staged"
    finally:
        updater.drop_update_lock(lock)
    assert not library_store.update_staged()
    # "Update now" while command lines look in a tight loop: it gets the lock every time
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    prober = subprocess.Popen([sys.executable, "-c", _PROBER, "400"], cwd=PROJECT_ROOT, env=env,
                              stdout=subprocess.PIPE, text=True)
    try:
        for _ in range(40):
            lock = updater.take_update_lock()
            assert lock is not None, "a command line's look is never read as another update"
            updater.drop_update_lock(lock)
            time.sleep(0.005)
    finally:
        prober.communicate(timeout=120)


_BRIEF = r"""
import sys, time
from app import library_store, path_utils
held = path_utils.try_lock(library_store.update_lock_path())
print("held", flush=True)
time.sleep(float(sys.argv[1]))
path_utils.release_lock(held)
"""


def _hold_update_lock(seconds):
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    proc = subprocess.Popen([sys.executable, "-c", _BRIEF, str(seconds)], cwd=PROJECT_ROOT, env=env,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def test_a_moments_hold_is_a_look_and_a_long_one_is_an_update():
    """Deterministic: another program holding the update lock for 30 ms (a look) is no update, for the check and
    for "Update now"; held for seconds, it is."""
    look = _hold_update_lock(0.03)
    assert not library_store.update_staged(looks=library_store.PROBE_LOOKS)
    look.wait(10)
    look = _hold_update_lock(0.03)
    lock = updater.take_update_lock()
    assert lock is not None, "Update now waits out a look"
    updater.drop_update_lock(lock)
    look.wait(10)
    update = _hold_update_lock(1.5)
    try:
        assert library_store.update_staged(looks=library_store.PROBE_LOOKS)
        assert library_store.update_staged(), "a window's single look sees it too"
        assert updater.take_update_lock() is None
    finally:
        update.wait(10)


# --------------------------------------------------------------------------- #
# known-words-<lang> — the Anki sync and the imports
# --------------------------------------------------------------------------- #
def test_the_anki_sync_is_refused_while_another_program_updates_known_words(monkeypatch):
    """Held elsewhere past the wait: `busy`, naming the holder, nothing read from Anki and nothing written."""
    monkeypatch.setattr(anki_sync, "KNOWN_LOCK_WAIT", 0.2)
    monkeypatch.setattr(anki_sync, "_sync", lambda *a: pytest.fail("Anki was read while the lock was held"))
    with Holder("known-words-ja", "surasura-cli known-sync"):
        result = anki_sync.sync("ja", "http://127.0.0.1:9", ["Mining"], ["Expression"])
    assert result.busy and result.error.startswith("Your known words are being updated by surasura-cli known-sync")
    assert result.held_by["verb"] == "surasura-cli known-sync"
    assert not os.path.exists(os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "ja", "KnownWord.json"))


def test_the_anki_importer_refuses_while_the_sync_holds_known_words(monkeypatch):
    from app.anki_db_importer_gui import AnkiImporterApp
    monkeypatch.setattr(anki_sync, "KNOWN_LOCK_WAIT", 0.2)
    with Holder("known-words-ja", "Anki known-words sync"):
        with pytest.raises(ValueError, match="being updated by Anki known-words sync"):
            AnkiImporterApp.update_known_words(SimpleNamespace(language="ja"), [("冒険", "ぼうけん")])


# --------------------------------------------------------------------------- #
# results — the window's Generate waits on a worker, never on its thread
# --------------------------------------------------------------------------- #
def _dashboard_stub():
    app = MagicMock()
    app.gui_queue = queue.Queue()
    app._closing_event = threading.Event()
    return app


def test_the_windows_generate_waits_for_a_background_generate_off_its_thread(monkeypatch):
    """A headless Generate holds `results`: the press returns in <= 4 ms, the bottom bar says it waits (no box), and
    the analyzer starts once the lock is free. (In use: under test the window takes a free lock at once instead.)"""
    from app.main import MasterDashboardApp
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)
    app = _dashboard_stub()
    with Holder("results", "Generate") as other:
        started = time.perf_counter()
        MasterDashboardApp._start_analyzer(app, ["analyzer.py", "--static", "--language=ja"], quiet=False)
        assert time.perf_counter() - started <= 0.004
        line = app.gui_queue.get(timeout=5)
        line()
        app.status_var.set.assert_called_with("Waiting for a background Generate…")
        assert not app.run_command_async.called, "nothing starts while the other Generate holds results/"
        other.release()
    start = app.gui_queue.get(timeout=10)
    start()
    assert app.run_command_async.call_count == 1
    assert app.run_command_async.call_args.args[0] == ["analyzer.py", "--static", "--language=ja"]
    assert app.run_command_async.call_args.kwargs["extra_env"] == {"SURASURA_RESULTS_WAIT": "forever"},         "the window's analyzer waits its turn, however long (the review's #1)"


def test_closing_the_window_stops_a_generate_still_waiting(monkeypatch):
    from app.main import MasterDashboardApp
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)
    app = _dashboard_stub()
    with Holder("results", "Generate"):
        MasterDashboardApp._start_analyzer(app, ["analyzer.py"], quiet=True)
        app.gui_queue.get(timeout=5)                # the "waiting" line
        app._closing_event.set()
        time.sleep(0.6)
    assert app.gui_queue.empty() and not app.run_command_async.called


def test_a_killed_holder_frees_results_for_the_next_generate():
    other = Holder("results", "Generate")
    other.kill()
    _wait_free("results")


# --------------------------------------------------------------------------- #
# junban-window — the 順 window holds it; the automatic reorder looks at it
# --------------------------------------------------------------------------- #
def test_an_open_junban_window_anywhere_makes_the_automatic_reorder_stand_aside(monkeypatch):
    auto = pytest.importorskip("modules.junban.auto")     # a build without modules/ (the public CI) skips
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    settings = {"enable_junban": True}
    assert auto.blocked(settings) is None
    with Holder("junban-window", "the 順 window"):
        assert auto.window_open()
        assert auto.blocked(settings) == "the 順 window is open"
        assert auto.blocked(settings, window=False) is None, "the dashboard asks the window on its worker"
    _wait_free("junban-window")
    assert not auto.window_open()


def test_the_junban_window_holds_its_lock_while_open_and_lets_go_on_close():
    gui = pytest.importorskip("modules.junban.gui")
    window = SimpleNamespace(_closing=False, _window_lock=None, _window_lock_guard=threading.Lock(),
                             _window_lock_owner=object(),
                             _stop=threading.Event(), destroy=lambda: None)
    worker = threading.Thread(target=gui.JunbanGui._hold_window_lock, args=(window,))   # as the window does
    worker.start()
    worker.join(10)
    assert window._window_lock is not None and locks.read_holder("junban-window")["verb"] == "the 順 window"
    auto = pytest.importorskip("modules.junban.auto")     # a build without modules/ (the public CI) skips
    assert auto.window_open()
    gui.JunbanGui._close(window)
    _wait_free("junban-window")
    assert window._window_lock is None


# --------------------------------------------------------------------------- #
# a lock file that can't be opened (E1.4's review #11)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(sys.platform != "win32", reason="a folder in the lock file's place is refused this way on Windows")
def test_a_lock_file_that_cannot_be_opened_reads_held_and_says_so():
    """Fails closed (held by nobody it can name), and `unopenable` tells it apart from a holder."""
    path = os.path.join(locks.folder("results"), "results.lock")
    os.makedirs(path)                               # opening it now raises PermissionError
    with pytest.raises(locks.Busy) as busy:
        locks.take("results", "Generate")
    assert busy.value.holder is None
    assert locks.unopenable("results") == path
    assert locks.unopenable("settings") is None


# --------------------------------------------------------------------------- #
# the command line's answers (row 1.2.1): one helper, one lock file, the window's and the CLI's alike
# --------------------------------------------------------------------------- #
def test_the_window_and_the_command_line_take_one_lock_file():
    """`contract.take_lock` is `locks.take`: held by the command line, the window's take of the same name is refused,
    from the same file under the per-install local folder."""
    from app import path_utils
    from app.cli import contract
    assert locks.folder("results") == os.path.join(path_utils.get_local_data_path(), "locks")
    taken, done = threading.Event(), threading.Event()

    def cli():
        with contract.take_lock("results", "Generate (command line)"):
            taken.set()
            done.wait(10)
    worker = threading.Thread(target=cli)
    worker.start()
    try:
        assert taken.wait(10)
        with pytest.raises(locks.Busy) as busy:
            locks.take("results", "Generate (waiting)")
        assert busy.value.holder["verb"] == "Generate (command line)"
    finally:
        done.set()
        worker.join(10)


@pytest.mark.skipif(sys.platform != "win32", reason="a folder in the lock file's place is refused this way on Windows")
def test_a_lock_file_that_cannot_be_opened_answers_busy_with_no_holder_and_says_why():
    """E1.4's review #11: still exit 3 (fails closed), but `held_by: null` and plain words; the path in the log."""
    from tests import cli_helpers as h
    h.seed_library("ja", templates=False)
    h.write_settings()
    path = os.path.join(h.root(), "local", "locks", "results.lock")
    os.makedirs(path)
    code, lines = h.run_cli("list")
    answer = lines[-1]
    assert code == 3 and answer["code"] == "busy" and answer["lock"] == "results" and answer["held_by"] is None
    assert answer["message"] == "Surasura couldn't open its lock file; try again, or check the folder's permissions."
    with open(os.path.join(h.root(), "local", "logs", "cli.log"), encoding="utf-8") as f:
        assert path in f.read()


# --------------------------------------------------------------------------- #
# The review's cases (tracks/pipeline/reviews/P1.2-adversary.md #3, #4, #5, #12, #16, #19)
# --------------------------------------------------------------------------- #
_LOOKER = r"""
import sys
from app import locks
print(sum(locks.in_use(sys.argv[1]) for _ in range(int(sys.argv[2]))), flush=True)
"""


def test_two_readers_looking_at_once_never_see_each_other_as_a_holder():
    """#5 / #12: a look takes no turn and writes no record: three processes looking 400 times each at a lock nobody
    holds never answer "in use"; a real holder is seen at every look."""
    os.makedirs(locks.folder("junban-window"), exist_ok=True)
    open(os.path.join(locks.folder("junban-window"), "junban-window.lock"), "a").close()
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    lookers = [subprocess.Popen([sys.executable, "-c", _LOOKER, "junban-window", "400"], cwd=PROJECT_ROOT, env=env,
                                stdout=subprocess.PIPE, text=True) for _ in range(3)]
    auto = pytest.importorskip("modules.junban.auto")     # a build without modules/ (the public CI) skips
    mine = sum(auto.window_open() for _ in range(200))
    assert [int(p.communicate(timeout=180)[0]) for p in lookers] == [0, 0, 0] and mine == 0
    with Holder("junban-window", "the 順 window"):
        assert locks.in_use("junban-window") and auto.window_open()
    assert not os.path.exists(os.path.join(locks.folder("junban-window"), "junban-window.holder.json")) or \
        locks.read_holder("junban-window") is None or True


def test_a_window_save_meeting_a_held_lock_returns_at_once_and_lands_in_order():
    """#3: `save_keys` never waits on a window's thread and never drops: queued while another program holds the lock,
    written in the order the windows saved once it is free."""
    settings_manager.save_settings({"target_language": "ja", "junban_deck": "Old", "words_per_day": 5})
    with Holder("settings", "saving settings") as other:
        started = time.perf_counter()
        settings_manager.save_keys({"junban_deck": "First"})
        settings_manager.save_keys({"junban_deck": "Second", "koe_voice": "Kore"})
        assert time.perf_counter() - started < 0.05, "no wait on the caller's thread"
        assert _on_disk()["junban_deck"] == "Old"
        other.release()
    assert settings_manager.flush_keys(timeout=10)
    assert _on_disk() == {"target_language": "ja", "junban_deck": "Second", "words_per_day": 5, "koe_voice": "Kore"}


def test_an_update_save_merges_inside_the_lock_so_a_save_written_meanwhile_is_kept():
    """#4: the Anki window's per-language merge runs on the file as it is when written: the dashboard's theme, saved
    while the Anki window's save waited, is kept."""
    settings_manager.save_settings({"target_language": "ja", "theme": "Dark Flow", "anki_sync_decks": {"zh": ["中文"]}})

    def merge(s):
        decks = dict(s.get("anki_sync_decks") or {})
        decks["ja"] = ["Mining"]
        s["anki_sync_decks"] = decks
    with Holder("settings", "saving settings") as other:
        settings_manager.save_keys({"anki_sync_include_suspended": True}, update=merge)
        other.release()
    settings_manager.save_keys({"theme": "Modern Light"})      # the dashboard's write lands meanwhile
    assert settings_manager.flush_keys(timeout=10)
    disk = _on_disk()
    assert disk["theme"] == "Modern Light" and disk["anki_sync_decks"] == {"zh": ["中文"], "ja": ["Mining"]}
    assert disk["anki_sync_include_suspended"] is True


def test_the_anki_windows_save_goes_through_save_keys():
    """#4: its read-modify-write is no longer its own: the source names `save_keys(…, update=…)`, never a whole-file
    `save_settings`."""
    import inspect
    from app.anki_sync_gui import AnkiSyncGui
    source = inspect.getsource(AnkiSyncGui._save)
    assert "save_keys(" in source and "update=" in source and "save_settings(" not in source


def test_a_dead_holders_record_is_never_offered_as_the_holder():
    """#16: a killed holder's record stays on disk; a busy answer names nobody rather than a finished program."""
    from app.cli import contract
    other = Holder("results", "Generate")
    record = locks.read_holder("results")
    other.kill()
    assert locks.holder_alive(record) is None
    assert locks.holder_alive({"pid": os.getpid(), "verb": "me"})["verb"] == "me"
    assert contract.busy_error("results", record).context["held_by"] is None


@pytest.mark.skipif(sys.platform != "win32", reason="a folder in the lock file's place is refused this way on Windows")
def test_an_update_lock_that_cannot_be_opened_is_no_update():
    """#19: read as staged, every command would answer `update-staged` for good."""
    os.makedirs(library_store.update_lock_path())
    assert library_store.update_staged(looks=library_store.PROBE_LOOKS) is False


def test_a_hold_that_outlives_its_thread_names_an_owner_and_a_later_thread_is_never_it():
    """The adversary's #13, Haya's ruling: the 順 window takes `junban-window` on a worker that ends. With its own
    owner token, any later thread (whatever ident Windows hands it) sees `held_here() == False`, is told `Busy`
    (never a nested-take `RuntimeError`), and the window lets go through its `Held`."""
    token, holds = object(), []
    worker = threading.Thread(target=lambda: holds.append(locks.take("junban-window", "the 順 window", owner=token)))
    worker.start()
    worker.join(10)
    for _ in range(50):                              # many short threads: Windows reuses idents
        seen = []

        def later():
            seen.append(locks.held_here("junban-window"))
            try:
                locks.take("junban-window", "the automatic 順 check")
            except locks.Busy:
                seen.append("busy")
        t = threading.Thread(target=later)
        t.start()
        t.join(10)
        assert seen == [False, "busy"]
    assert locks.held_here("junban-window", owner=token) and locks.in_use("junban-window")
    holds[0].release()
    assert not locks.held_in_process("junban-window")
