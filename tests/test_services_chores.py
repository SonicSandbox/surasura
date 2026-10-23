"""The window's chores (`app/services/chores.py`) — W3.5 row 6.

What a wrong answer would cost:
  * two indexers writing one token store, or an indexer beside Generate — a focus storm must start one;
  * a port held after the window closed — Koe's helper left serving, the next start falls to another port;
  * a window that dies with an optional module — Koe absent, the chores still run;
  * a chore run twice per trigger, or under the test switches the Tk dashboard honours;
  * settings.json written behind the user's back.

The indexer's child is a fake `Popen` (the claim is about when and how often it starts); its check is the real
stat-only `index_needed` over the suite's Japanese files where the claim is about the library.
"""
import os
import subprocess
import sys
import threading
import types

import pytest

from app.services import chores as C
from app.services import jobs as J
from app.services.jobs import JobRegistry
from tests import services_helpers as h


class _Settings:
    def __init__(self, **values):
        self.values = dict(values)
        self.writes = []
        self.flushes = 0

    def get(self):
        return dict(self.values)

    def set(self, changes):
        self.writes.append(dict(changes))
        self.values.update(changes)

    def flush(self, timeout=None):
        self.flushes += 1


class _Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class _Timer:
    def __init__(self, delay, call):
        self.delay, self.call, self.cancelled = delay, call, False

    def cancel(self):
        self.cancelled = True


class _Timers(list):
    def __call__(self, delay, call):
        timer = _Timer(delay, call)
        self.append(timer)
        return timer


class _Proc:
    """A child that runs until the test (or a terminate) ends it."""
    pid = 4321

    def __init__(self, args, **kw):
        self.args, self.kw = args, kw
        self.returncode = None
        self.done = threading.Event()
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.done.wait(timeout if timeout is not None else 30)
        return self.returncode

    def end(self, code=0):
        self.returncode = code
        self.done.set()

    def terminate(self):
        self.terminated = True
        self.end(-15)


class _Popen(list):
    def __call__(self, args, **kw):
        proc = _Proc(args, **kw)
        self.append(proc)
        return proc


@pytest.fixture
def timers_on(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)


@pytest.fixture
def indexing_on(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_AUTOINDEX", raising=False)


def _make(settings=None, needed=lambda language, script: True, staged=lambda: False, clock=None, timers=None,
          popen=None, lang="ja"):
    registry = JobRegistry()
    popen = popen if popen is not None else _Popen()
    chores = C.Chores(registry, settings or _Settings(target_language=lang), lang, update_staged=staged,
                      clock=clock or _Clock(), timer=timers if timers is not None else _Timers(), popen=popen,
                      needed=needed, log_folder=os.path.join(h.root(), "logs"))
    return chores, registry, popen


def _koe(monkeypatch, revealed=True):
    calls = []
    fake = types.ModuleType("modules.koe")
    fake.is_revealed = lambda: revealed
    fake.start_server = lambda app=None: calls.append("start") or 8787
    fake.stop_server = lambda: calls.append("stop")
    monkeypatch.setitem(sys.modules, "modules.koe", fake)
    return calls


# --- the indexer ------------------------------------------------------------------------------------------------- #
def test_a_focus_storm_starts_one_indexer(indexing_on):
    """`_maybe_launch_indexer`'s `_indexer_busy`: twenty activations while it runs are one child, one job; its end
    lets the next one start."""
    clock = _Clock(0.0)
    chores, registry, popen = _make(clock=clock)
    indexed = []
    chores.on_indexed(indexed.append)
    for _ in range(20):
        chores.activated()
        clock.now += 5.0
    assert h.until(lambda: len(popen) == 1, seconds=5)
    assert chores.worker.idle(5)
    assert len(popen) == 1 and len(registry.live("indexer")) == 1
    assert popen[0].args[-2:] == ["--language", "ja"]
    popen[0].end(0)
    assert h.until(lambda: indexed == ["ja"], seconds=5)
    assert h.until(lambda: not registry.live("indexer"), seconds=5)
    chores.index()
    assert h.until(lambda: len(popen) == 2, seconds=5)
    popen[1].end(0)
    chores.close()


def test_a_trigger_while_the_indexer_runs_asks_for_no_second_one(indexing_on):
    """`_indexer_busy`, from the check until the indexer's end (HR-11 clears it only when no job was made): a trigger
    while the indexer runs asks nothing — never a second indexer queued behind the first."""
    clock = _Clock(0.0)
    chores, registry, popen = _make(clock=clock)
    assert chores.index() is None
    assert h.until(lambda: len(popen) == 1, seconds=5) and chores.worker.idle(5)
    clock.now += 5.0
    assert chores.index() == "busy"
    assert chores.worker.idle(5) and len(registry.live("indexer")) == 1
    popen[0].end(0)
    assert h.until(lambda: not registry.live("indexer"), seconds=5)
    chores.close()


def test_a_forced_ask_while_the_indexer_runs_runs_it_once_more_when_it_ends(indexing_on):
    """A forced ask (a watched mark that changed what counts) while the indexer runs is answered *busy* but never lost:
    the running one may have read the library before the mark. However many come, one more run follows its end — and
    none after that one. A forced ask during the check alone (no job made) asks the check once more too."""
    chores, registry, popen = _make()
    assert chores.index(force=True) is None
    assert h.until(lambda: len(popen) == 1, seconds=5) and chores.worker.idle(5)
    assert [chores.index(force=True) for _ in range(3)] == ["busy"] * 3
    assert chores.index() == "busy"                         # an unforced trigger asks for nothing more
    popen[0].end(0)
    assert h.until(lambda: len(popen) == 2, seconds=5)
    popen[1].end(0)
    assert h.until(lambda: not registry.live("indexer") and not chores._indexing, seconds=5)
    assert chores.worker.idle(5) and len(popen) == 2
    chores.close()

    checks, gate = [], threading.Event()

    def needed(language, script):                           # the check is slow and finds nothing to do
        checks.append(language)
        gate.wait(5)
        return False
    chores, registry, popen = _make(needed=needed)
    assert chores.index(force=True) is None
    assert h.until(lambda: checks == ["ja"], seconds=5)
    assert chores.index(force=True) == "busy"
    gate.set()
    assert h.until(lambda: len(checks) == 2, seconds=5) and chores.worker.idle(5)
    assert h.until(lambda: not chores._indexing, seconds=5) and len(checks) == 2 and popen == []
    chores.close()


def test_the_indexer_check_is_throttled_two_seconds_unless_forced(indexing_on):
    """`if not force and (now - self._last_index_check) < 2.0: return` — counted from never."""
    clock = _Clock(0.0)
    asked = []
    chores, registry, popen = _make(clock=clock, needed=lambda language, script: asked.append(language) or False)
    assert chores.index() is None, "0.0 is not 'just now'"
    assert chores.worker.idle(5)
    clock.now = 1.9
    assert chores.index() == "throttled"
    assert chores.index(force=True) is None
    assert chores.worker.idle(5)
    clock.now = 4.0
    assert chores.index() is None
    assert chores.worker.idle(5)
    assert asked == ["ja", "ja", "ja"] and popen == []
    chores.close()


def test_the_indexer_never_runs_beside_generate(indexing_on):
    """Generate and the indexer both write the token store (`RESOURCES`): the indexer job waits for the Generate."""
    chores, registry, popen = _make()
    generate = registry.submit("generate", "Generating", start=lambda job: None)
    chores.index(force=True)
    assert h.until(lambda: registry.live("indexer") and registry.live("indexer")[0].state == J.WAITING, seconds=5)
    assert popen == []
    generate.finish(ok=True)
    assert h.until(lambda: len(popen) == 1, seconds=5)
    popen[0].end(0)
    chores.close()


@pytest.mark.parametrize("why", ["switch", "nothing-to-do", "update-staged"])
def test_no_indexer_when_held(indexing_on, monkeypatch, why):
    """`SURASURA_NO_AUTOINDEX`, the stat-only check finding nothing, an update waiting: no child; nothing left busy."""
    if why == "switch":
        monkeypatch.setenv("SURASURA_NO_AUTOINDEX", "1")
    chores, registry, popen = _make(needed=lambda language, script: why != "nothing-to-do",
                                    staged=lambda: why == "update-staged")
    chores.index(force=True)
    assert chores.worker.idle(5)
    assert popen == [] and not registry.snapshot()
    assert chores._indexing is False
    chores.close()


def test_quitting_stops_the_indexer(indexing_on):
    """The Tk `on_closing` terminates its children: the `indexer` job is `on_quit="cancel"`, its child stopped."""
    chores, registry, popen = _make()
    chores.index(force=True)
    assert h.until(lambda: len(popen) == 1, seconds=5)
    assert h.until(lambda: chores._proc is not None, seconds=5)
    left = registry.quit(timeout=5)
    assert popen[0].terminated and not left
    view = registry.snapshot()[-1]
    assert view.kind == "indexer" and view.cancelled
    chores.close()


def test_the_indexers_job_names_its_child_so_the_update_lists_it_once(indexing_on):
    """A frozen build's indexer is `Surasura.exe index …`: the update's scan of this install's programs finds it too.
    Its job carries the child's pid, so the wait list shows it as the job alone (never also as another window)."""
    chores, registry, popen = _make()
    chores.index(force=True)
    assert h.until(lambda: registry.live("indexer") and registry.live("indexer")[0].pid == 4321, seconds=5)
    popen[0].end(0)
    assert h.until(lambda: not registry.live("indexer"), seconds=5)
    chores.close()


def test_a_cancel_before_it_starts_leaves_nothing_busy(indexing_on):
    """Cancelled while it waits for a Generate: no child, and the next trigger may index."""
    chores, registry, popen = _make()
    generate = registry.submit("generate", "Generating", start=lambda job: None)
    chores.index(force=True)
    assert h.until(lambda: registry.live("indexer"), seconds=5)
    job = [j for j in registry._jobs if j.kind == "indexer"][0]
    job.cancel()
    assert chores._indexing is False
    generate.finish(ok=True)
    assert chores.worker.idle(5) and popen == []
    chores.close()


def test_a_cancelled_indexer_takes_its_follow_up_with_it(indexing_on):
    """A forced ask while the indexer runs is remembered for one more run — but *Stop it* on that indexer stops the
    indexing: no run starts again at its end."""
    chores, registry, popen = _make()
    assert chores.index(force=True) is None
    assert h.until(lambda: len(popen) == 1 and chores._proc is not None, seconds=5)
    assert chores.index(force=True) == "busy"                   # remembered for its end
    job = [j for j in registry._jobs if j.kind == "indexer"][0]
    job.cancel()
    assert popen[0].terminated
    assert h.until(lambda: not registry.live("indexer") and not chores._indexing, seconds=5)
    assert not h.until(lambda: len(popen) > 1, seconds=1), "the stopped indexer never restarts"
    chores.close()


def test_a_cancel_before_it_starts_leaves_no_follow_up_for_a_later_run(indexing_on):
    """Cancelled while it waits for a Generate, with a forced ask remembered meanwhile: that ask went with it. A later
    indexer, asked on its own, runs once — never one extra run at its end."""
    chores, registry, popen = _make()
    generate = registry.submit("generate", "Generating", start=lambda job: None)
    chores.index(force=True)
    assert h.until(lambda: registry.live("indexer"), seconds=5) and chores.worker.idle(5)
    assert chores.index(force=True) == "busy"
    [j for j in registry._jobs if j.kind == "indexer"][0].cancel()
    generate.finish(ok=True)
    assert chores.worker.idle(5) and popen == []
    assert chores.index(force=True) is None                      # a later, unrelated run
    assert h.until(lambda: len(popen) == 1, seconds=5)
    popen[0].end(0)
    assert h.until(lambda: not registry.live("indexer") and not chores._indexing, seconds=5)
    assert not h.until(lambda: len(popen) > 1, seconds=1), "no extra run left over from the cancelled one"
    chores.close()


def test_index_needed_reads_the_real_library(indexing_on, monkeypatch):
    """The ported `_index_needed` over the suite's Japanese files: a library never indexed needs the indexer; a check
    that fails answers False (the next trigger asks again)."""
    h.seed_library("ja")
    assert C.index_needed("ja", "asis") is True
    from app import token_index

    def unreadable(language):
        raise OSError("the store is held")
    monkeypatch.setattr(token_index, "open_store", unreadable)
    assert C.index_needed("ja", "asis") is False


def test_the_indexer_command_is_the_scripts_from_source():
    command = C.indexer_command("zh")
    assert command[1].endswith(os.path.join("app", "indexer.py")) and command[-2:] == ["--language", "zh"]


# --- Koe --------------------------------------------------------------------------------------------------------- #
def test_koe_starts_when_revealed_and_on_and_stops_at_close(monkeypatch):
    """`apply_koe_state` at the window's start; `on_closing`'s `koe.stop_server()` at close. A server this service
    owns, never a job (it never ends); nothing written to settings.json."""
    calls = _koe(monkeypatch)
    settings = _Settings(enable_koe=True, source_display="off")
    chores, registry, _p = _make(settings)
    chores.started()
    assert chores.worker.idle(5)
    assert calls == ["start"] and chores.state().koe_port == 8787
    assert settings.writes == [], "nothing automatic writes settings.json"
    assert not [v for v in registry.snapshot() if v.kind == "koe"]
    chores.close()
    assert calls == ["start", "stop"] and chores.state().koe_port is None


def test_koe_follows_its_switch(monkeypatch):
    calls = _koe(monkeypatch)
    settings = _Settings(enable_koe=False)
    chores, _r, _p = _make(settings)
    chores.koe_changed()
    assert chores.worker.idle(5) and "start" not in calls
    settings.values["enable_koe"] = True
    chores.koe_changed()
    assert chores.worker.idle(5) and calls[-1] == "start" and settings.flushes == 1
    settings.values["enable_koe"] = False
    chores.koe_changed()
    assert chores.worker.idle(5) and calls[-1] == "stop" and chores.state().koe_port is None
    chores.close()


def test_koe_hidden_never_starts(monkeypatch):
    """The reveal gate (`is_revealed`): `enable_koe` true but the line not the user's — nothing starts."""
    calls = _koe(monkeypatch, revealed=False)
    chores, _r, _p = _make(_Settings(enable_koe=True))
    chores.started()
    assert chores.worker.idle(5)
    assert "start" not in calls
    chores.close()


def test_koe_absent_the_chores_still_run(monkeypatch, timers_on):
    """RD-S10: the module removed — started, focus, close all run."""
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    timers = _Timers()
    chores, registry, _p = _make(_Settings(enable_koe=True), timers=timers)
    chores.started()
    chores.activated()
    chores.koe_changed()
    assert chores.worker.idle(5)
    assert len(timers) == 5, "the indexer, the store's helper, Connect's notice, the warm-up, the helper's debounce"
    chores.close()


# --- the start-up chores ----------------------------------------------------------------------------------------- #
def test_each_start_chore_runs_once_per_start(monkeypatch, timers_on):
    """`_write_install_note`, and the timers at 1.5 s / 1.5 s / 2.5 s / 3 s — the last the Rarity tables' warm-up
    (`_prepare_preview`), after the start's own work: at once it held the window's thread off 45 + 130 ms."""
    from app import path_utils, token_index
    notes, warm = [], []
    monkeypatch.setattr(path_utils, "write_install_note", lambda *a, **k: notes.append(1))
    monkeypatch.setattr(token_index, "prepare_preview", lambda language, folder: warm.append(language))
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    timers = _Timers()
    chores, _r, _p = _make(timers=timers)
    chores.started()
    assert chores.worker.idle(5)
    assert notes == [1] and warm == []                      # not at once: its timer
    assert sorted(t.delay for t in timers) == [C.START_INDEX, C.START_MAINTAIN, C.ARRIVALS_AT, C.WARM_AT]
    assert C.WARM_AT > max(C.START_INDEX, C.START_MAINTAIN, C.ARRIVALS_AT)
    [t for t in timers if t.delay == C.WARM_AT][0].call()
    assert chores.worker.idle(5)
    assert warm == ["ja"]
    chores.close()
    assert all(t.cancelled for t in timers)


def test_under_test_no_timer_and_no_warm_up(monkeypatch):
    """`SURASURA_NO_UI_TIMERS` (the suite's): no start timers, no warm-up, no store helper; the install note still
    (the Tk window writes it always: frozen builds only)."""
    from app import path_utils, token_index
    notes, warm = [], []
    monkeypatch.setattr(path_utils, "write_install_note", lambda *a, **k: notes.append(1))
    monkeypatch.setattr(token_index, "prepare_preview", lambda language, folder: warm.append(language))
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    timers = _Timers()
    chores, _r, _p = _make(timers=timers)
    chores.started()
    chores.activated()
    assert chores.worker.idle(5)
    assert notes == [1] and warm == [] and timers == []
    chores.close()


def test_the_window_start_writes_surasura_json_on_the_worker_connect_off(monkeypatch, tmp_path):
    """09-hato-layer §3 (v2 P10): surasura.json is written whenever Surasura runs, Connect on or off. The 3.0 window
    never runs surasura-cli, so its start is the only writer with Connect off: without it hato's automatic setting
    reads Surasura as absent and hands nothing off. Under the suite's no-timers switch too (the Tk window's start
    writes it always); on the worker, never the window's thread."""
    import json
    from app import path_utils, tools_entry
    monkeypatch.setattr(path_utils, "write_install_note", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    tools = tmp_path / "道具"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(tools))
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(tmp_path / "スラスラ" / "surasura-cli.cmd"))
    threads, real = [], tools_entry.refresh
    monkeypatch.setattr(tools_entry, "refresh", lambda settings=None: threads.append(threading.get_ident())
                        or real(settings))
    chores, _r, _p = _make(_Settings(connect_enabled=False))
    chores.started()
    assert chores.worker.idle(5)
    assert len(threads) == 1 and threads[0] != threading.get_ident()
    entry = json.loads((tools / "surasura.json").read_text(encoding="utf-8"))
    assert entry["cli"] == str(tmp_path / "スラスラ" / "surasura-cli.cmd") and entry["verbs"] == ["status"]
    chores.close()


def test_a_failing_surasura_json_refresh_is_only_printed_and_the_next_chore_runs(monkeypatch, capsys):
    """The tools folder unwritable, settings unreadable, anything: the window opens as ever and Koe still starts."""
    from app import path_utils, tools_entry
    monkeypatch.setattr(path_utils, "write_install_note", lambda *a, **k: None)
    def boom(settings=None):
        raise RuntimeError("the tools folder is a file")
    monkeypatch.setattr(tools_entry, "refresh", boom)
    calls = _koe(monkeypatch)
    chores, _r, _p = _make(_Settings(enable_koe=True, source_display="off"))
    chores.started()
    assert chores.worker.idle(5)
    assert calls == ["start"]
    assert "surasura.json: the tools folder is a file" in capsys.readouterr().out
    chores.close()


class _Store:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _library_store(monkeypatch, mode="store", due=True):
    from app import library_store
    spawned, handed = [], []
    monkeypatch.setattr(library_store, "check_mode", lambda language, data_dir, busy_wait=None: (mode, ""))
    monkeypatch.setattr(library_store, "open_store", lambda *a, **k: _Store())

    def maintain_due(store, seen=""):
        handed.append(seen)
        return due, "stat-1"
    monkeypatch.setattr(library_store, "maintain_due", maintain_due)

    def spawn(language, *extra):
        proc = _Proc(["maintain", language])
        spawned.append(proc)
        return proc
    monkeypatch.setattr(library_store, "spawn_maintain", spawn)
    monkeypatch.setattr(library_store, "spawn_build_if_waiting", lambda language, d, u: spawn(language))
    return spawned, handed


def test_the_store_helper_once_per_burst_and_detached(monkeypatch, timers_on):
    """`_schedule_maintain` (2 s after the last focus) → `_maybe_maintain`: one check for a burst; the helper a
    `library-maintain` job left running at quit (Library_Store_Spec §6.7); the copy's stat handed on."""
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    spawned, handed = _library_store(monkeypatch)
    timers = _Timers()
    chores, registry, _p = _make(timers=timers)
    for _ in range(10):
        chores.activated()
    live = [t for t in timers if not t.cancelled and t.delay == C.MAINTAIN_SETTLE]
    assert len(live) == 1
    live[0].call()
    assert chores.worker.idle(5)
    assert len(spawned) == 1 and handed == [""]
    job = registry.live("library-maintain")[0]
    assert job.on_quit == "detach"
    assert job.pid == _Proc.pid, "row 35: *Stop and quit* ends the helper by its own pid"
    registry.quit(timeout=0.5)
    assert spawned[0].returncode is None, "quitting leaves the helper running"
    spawned[0].end(0)
    assert h.until(lambda: not registry.live("library-maintain"), seconds=5)
    chores.activated()
    [t for t in timers if not t.cancelled and t.delay == C.MAINTAIN_SETTLE][-1].call()
    assert chores.worker.idle(5) and handed == ["", "stat-1"]
    chores.close()


def test_the_copys_stat_is_handed_on_only_when_a_helper_started(monkeypatch):
    """HR-24: `spawn_maintain` starts nothing while an update is staged (None) — that stat was never handed to a
    helper, so the next check offers it again instead of skipping the copy's upkeep for the rest of the session."""
    from app import library_store
    spawned, handed = _library_store(monkeypatch)
    spawn = library_store.spawn_maintain
    answers = [None]
    monkeypatch.setattr(library_store, "spawn_maintain",
                        lambda language, *extra: answers.pop(0) if answers else spawn(language, *extra))
    chores, registry, _p = _make()
    chores.worker.put(chores._maintain)
    chores.worker.put(chores._maintain)
    assert chores.worker.idle(5)
    assert handed == ["", ""] and len(spawned) == 1
    chores.worker.put(chores._maintain)
    assert chores.worker.idle(5) and handed == ["", "", "stat-1"]
    for proc in spawned:
        proc.end(0)
    chores.close()


def test_a_fault_in_the_indexer_check_leaves_nothing_busy(indexing_on, monkeypatch):
    """HR-11: whatever fails in the check before the indexer's job is made (the script, the settings, the update's
    flag) leaves the chores free to index on the next trigger — never "busy" for the rest of the session."""
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    broken = [True]

    def staged():
        if broken[0]:
            raise RuntimeError("the update's flag couldn't be read")
        return False
    chores, registry, popen = _make(staged=staged)
    assert chores.index(force=True) is None
    assert chores.worker.idle(5) and popen == []
    broken[0] = False
    assert chores.index(force=True) is None
    assert h.until(lambda: len(popen) == 1, seconds=5)
    popen[0].end(0)
    chores.close()


@pytest.mark.parametrize("mode, expected", [("json", 1), ("read-only", 0)])
def test_the_store_helper_by_mode(monkeypatch, mode, expected):
    """No store yet: the build is asked for (`spawn_build_if_waiting`); read-only: nothing."""
    spawned, _handed = _library_store(monkeypatch, mode=mode)
    chores, _r, _p = _make()
    chores.worker.put(chores._maintain)
    assert chores.worker.idle(5)
    assert len(spawned) == expected
    for proc in spawned:
        proc.end(0)
    chores.close()


@pytest.mark.parametrize("there", ["nothing", "a manifest", "a store file"])
def test_a_fresh_language_builds_its_store_from_its_folders_never_over_a_manifest_or_a_store(monkeypatch, there):
    """W3.2 P0 (IK0-2): no manifest and no store — a fresh install, a language never opened — the helper built nothing
    (it builds only from a manifest), so the window said *Getting ready* forever and refused every drop. Now it is
    built from the tiers' folders (`--from-folders`, once a minute at most); with a manifest (the helper builds from
    that) or a store file (mid-migration, or a failed build: their own paths) never."""
    from app import library_store, path_utils
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    spawned = []
    monkeypatch.setattr(library_store, "check_mode", lambda language, data_dir, busy_wait=None: ("json", "no store"))
    monkeypatch.setattr(library_store, "spawn_build_if_waiting", lambda language, d, u: None)

    def spawn(language, *extra):
        proc = _Proc(["maintain", language, *extra])
        spawned.append(proc)
        return proc
    monkeypatch.setattr(library_store, "spawn_maintain", spawn)
    if there == "a manifest":
        path = library_store.manifest_path(path_utils.get_user_files_path("ja"))
    elif there == "a store file":
        path = library_store.library_db_path("ja", path_utils.get_data_path("ja"))
    if there != "nothing":
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb"):
            pass
    clock = _Clock(100.0)
    chores, registry, _p = _make(clock=clock)
    chores.worker.put(chores._maintain)
    chores.worker.put(chores._maintain)                         # a second look within the minute
    assert chores.worker.idle(5)
    expected = [["maintain", "ja", "--from-folders"]] if there == "nothing" else []
    assert [p.args for p in spawned] == expected
    if there == "nothing":
        assert registry.live("library-maintain")                 # the bar's *Tidying your library* while it runs
        clock.now += C.FROM_FOLDERS_EVERY
        chores.worker.put(chores._maintain)
        assert chores.worker.idle(5) and len(spawned) == 2      # still none a minute on: asked again
    for proc in spawned:
        proc.end(0)
    chores.close()


@pytest.mark.parametrize("on", [True, False])
def test_connects_notices_only_with_it_on(monkeypatch, timers_on, on):
    """`_arrivals_notice` 2.5 s on and `notice.at_close` at close, while `connect_enabled`; off, nothing of
    Connect's is imported."""
    from app.connect import notice
    calls = []
    monkeypatch.setattr(notice, "at_open", lambda language: calls.append(("open", language)) or "3 arrived")
    monkeypatch.setattr(notice, "at_close", lambda language: calls.append(("close", language)))
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    timers = _Timers()
    chores, _r, _p = _make(_Settings(connect_enabled=on), timers=timers)
    chores.started()
    [t for t in timers if t.delay == C.ARRIVALS_AT][0].call()
    assert chores.worker.idle(5)
    chores.close()
    if on:
        assert calls == [("open", "ja"), ("close", "ja")] and chores.state().notice == "3 arrived"
    else:
        assert calls == [] and chores.state().notice is None



def test_connects_notice_timer_that_rang_as_the_quit_began_names_nothing(monkeypatch, timers_on):
    """A close in the first seconds: the notice's timer was already ringing as the quit took the timers back. A window
    about to close never asks Connect what arrived (nor shows it)."""
    from app.connect import notice
    calls = []
    monkeypatch.setattr(notice, "at_open", lambda language: calls.append(("open", language)) or "3 arrived")
    monkeypatch.setattr(notice, "at_close", lambda language: None)
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    timers = _Timers()
    chores, _r, _p = _make(_Settings(connect_enabled=True), timers=timers)
    chores.started()
    ringing = [t for t in timers if t.delay == C.ARRIVALS_AT][0]
    chores.halt()
    assert ringing.cancelled
    ringing.call()                                       # it rang anyway, a moment before it was taken back
    assert chores.worker.idle(5)
    assert calls == [] and chores.state().notice is None
    chores.close()

def test_close_runs_the_stores_close_trigger_for_each_language(monkeypatch):
    from app import library_store
    closed = []
    monkeypatch.setattr(library_store, "maintain_at_close", lambda language, *a: closed.append(language))
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    chores, _r, _p = _make()
    chores.close()
    assert closed == ["ja", "zh"]
    assert chores.index(force=True) in ("off", "busy")


def test_a_language_switch_reindexes_that_language(indexing_on, monkeypatch):
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    chores, registry, popen = _make()
    chores.language_changed("zh")
    assert h.until(lambda: len(popen) == 1, seconds=5)
    assert popen[0].args[-1] == "zh"
    popen[0].end(0)
    chores.close()


# --- W3.5 worker K: the Haiku mutant list's survivors ------------------------------------------------------------ #
def test_a_koe_start_queued_before_close_never_runs_after_it(monkeypatch):
    """`_koe`'s closed check: the worker still runs what was queued before `close()`; a Koe start among it never
    brings the helper back after the close stopped it (a port held after the window closed)."""
    calls = _koe(monkeypatch)
    chores, _r, _p = _make(_Settings(enable_koe=True))
    hold = threading.Event()
    chores.worker.put(hold.wait, 10)
    chores.koe_changed()
    chores.close()
    hold.set()
    assert chores.worker.idle(5)
    assert "start" not in calls and calls[-1] == "stop" and chores.state().koe_port is None


def test_after_close_no_trigger_arms_a_timer_or_asks_the_indexer(indexing_on, timers_on, monkeypatch):
    """`close()` marks the chores closed: a focus or a language switch after it arms no store-helper timer, and the
    indexer is refused as busy (`close()` leaves no timer)."""
    monkeypatch.setitem(sys.modules, "modules.koe", None)
    timers = _Timers()
    chores, registry, popen = _make(timers=timers)
    chores.close()
    chores.activated()
    chores.language_changed("zh")
    assert timers == []
    assert chores.index(force=True) == "busy"
    assert popen == [] and not registry.snapshot()


# --- row 35: *Stop and quit* ends the upkeep helper through its own Popen --------------------------------------- #
def test_stop_and_quit_ends_the_real_upkeep_helper_and_never_another_process():
    """The helper (`_watch`: a real child here) is ended through the Popen chores holds — its pid can't be reused
    while held — and the job ends cancelled; a live child the registry doesn't hold is left alone."""
    chores, registry, _p = _make()
    helper, bystander = (subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                          stdin=subprocess.DEVNULL) for _ in range(2))
    try:
        chores._watch(helper)
        job = registry.live("library-maintain")[0]
        assert job.pid == helper.pid and job.can_cancel
        assert J.stop_at_quit(registry) == (job.id,)
        assert helper.wait(10) is not None
        assert h.until(lambda: not registry.live("library-maintain"), seconds=5)
        assert registry.snapshot()[-1].cancelled
        assert bystander.poll() is None, "never a process the registry doesn't hold"
        assert J.stop_at_quit(registry) == ()                 # ended: nothing asked again
    finally:
        for proc in (helper, bystander):
            if proc.poll() is None:
                proc.kill()
            proc.wait(10)
        chores.close(store=False)
