"""K75 (S1.1): an update waits for everything of Surasura's that holds this install's programs.

updater.exe waits only on the dashboard's own PID, so a パターン build, a Content Manager, an importer's child or a
command line hato started would hold Surasura.exe while it is swapped — the swap fails, rolls back, and that version
becomes manual-only. Since 2.5 "Update now" holds every new child, downloads meanwhile, names what still runs in a
non-modal window with *Stop it* / *Stop all and update now* / *Cancel*, and hands over only when nothing is left.

Real child processes (Python sleeping, standing in for this install's exe) and the real Windows process listing; the
real dashboard, its waiting window and its buttons. The download and the helper's launch are stubbed — what they do is
K99's (tests/test_updater_file_list.py)."""
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

from app import path_utils
from app import updater
from app.update_checker import UpdateInfo

backfill = pytest.importorskip("modules.junban.backfill")


_REAL_POPEN = subprocess.Popen


def _sleeper(seconds=30):
    return _REAL_POPEN([sys.executable, "-c", f"import time; time.sleep({seconds})"])


@pytest.fixture
def procs():
    started = []
    yield started
    for p in started:
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _free_hold():
    yield
    with updater._DEFERRED_LOCK:
        updater._DEFERRED.clear()
    updater._HOLD.clear()


@pytest.fixture
def dash(monkeypatch):
    """The real dashboard, with the update ready to apply: staging and the hand-over are recorded, not done."""
    from app.main import MasterDashboardApp
    root = tk.Tk()                       # shown: the waiting window is the dashboard's transient, as in real use
    real_destroy = root.destroy
    app = MasterDashboardApp(root)
    app._update_info = UpdateInfo(version="2.5.1", update_type="app", sha256="ab" * 32,
                                  app_package_url="https://example.invalid/Surasura_app_v2.5.1.zip")
    app._update_class = "APP"
    calls = {"armed": [], "destroyed": 0, "discarded": 0, "staged": {"target_version": "2.5.1", "targets": []}}
    monkeypatch.setattr(updater, "can_auto_apply", lambda info=None: True)
    monkeypatch.setattr(updater, "prepare_update", lambda info, progress_cb=None: calls["staged"])
    monkeypatch.setattr(updater, "arm_and_launch", lambda staged: calls["armed"].append(staged))
    monkeypatch.setattr(updater, "discard_staged", lambda: calls.__setitem__("discarded", calls["discarded"] + 1))
    monkeypatch.setattr(root, "destroy", lambda: calls.__setitem__("destroyed", calls["destroyed"] + 1))
    monkeypatch.setattr(backfill, "_PROCESS", None)
    app.calls = calls
    yield app
    job = app._update_job
    if job is not None:
        app._end_update(job)
    try:
        real_destroy()
    except Exception:
        pass


def _pump(app, until, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.root.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


def _wait_window(app):
    for w in app.root.winfo_children():
        if isinstance(w, tk.Toplevel) and w.winfo_exists() and w.title() == "Update waiting":
            return w
    return None


def _esc(win):
    win.focus_force()
    win.update()
    win.event_generate("<Escape>", when="now")


def _widgets(widget, kind):
    out = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            out.append(child)
        out.extend(_widgets(child, kind))
    return out


def _texts(win):
    return [w.cget("text") for w in _widgets(win, ttk.Label)]


def _button(win, text):
    hits = [b for b in _widgets(win, ttk.Button) if b.cget("text") == text]
    assert hits, f"no {text!r} button"
    return hits


# --- running_children(): what holds this install's programs ----------------------------------------------------------

def test_running_children_names_the_dashboards_child_and_the_pattern_build(procs, monkeypatch):
    generate, build = _sleeper(), _sleeper()
    procs += [generate, build]
    generate.surasura_desc = "Generate"
    monkeypatch.setattr(backfill, "_PROCESS", build)
    children = updater.running_children([generate], images=[])
    assert {c["name"] for c in children} == {"Generate", "Building パターン data"}
    for c in children:
        c["stop"]()
    assert generate.wait(timeout=10) is not None and build.wait(timeout=10) is not None
    assert updater.running_children([generate], images=[]) == []


@pytest.mark.skipif(sys.platform != "win32", reason="the in-place updater (and its process listing) is Windows'")
def test_a_process_running_this_installs_program_is_found_through_the_real_listing(procs):
    """sys.executable stands in for this install's Surasura.exe: a child of nobody we track (a grandchild, a command
    line hato started) is found by its program alone."""
    stray = _sleeper()
    procs.append(stray)
    children = updater.running_children([], images=[sys.executable])
    mine = [c for c in children if c["pid"] == stray.pid]
    assert mine and mine[0]["name"] == "Another Surasura window"
    assert os.getpid() not in {c["pid"] for c in children}
    mine[0]["stop"]()                                    # stop_pid: a process we hold no Popen for
    assert stray.wait(timeout=10) is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' process listing")
def test_a_command_line_is_named_as_one(procs, tmp_path):
    """surasura-cli.exe gets its own name (hato's command line), found by its image like the app's."""
    cli = tmp_path / "surasura-cli.exe"
    import shutil
    shutil.copy(sys.executable, cli)
    p = subprocess.Popen([str(cli), "-c", "import time; time.sleep(30)"])
    procs.append(p)
    children = updater.running_children([], images=[str(cli)])
    assert [c["name"] for c in children if c["pid"] == p.pid] == ["Surasura's command line"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' process listing")
def test_the_update_waits_for_a_process_found_only_by_its_program(dash, procs, monkeypatch):
    """The real listing delays the real update: no Popen of ours, only the program's path."""
    stray = _sleeper(2)
    procs.append(stray)
    monkeypatch.setattr(updater, "_install_images", lambda: [sys.executable])
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: _wait_window(dash) is not None)
    assert "Another Surasura window" in _texts(_wait_window(dash))
    assert dash.calls["armed"] == []
    stray.wait(timeout=10)
    # Our own python (the test) is excluded; other pythons (other test suites running) may still be listed.
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    assert _pump(dash, lambda: dash.calls["armed"])
    assert dash.calls["destroyed"] == 1


# --- the wait ---------------------------------------------------------------------------------------------------------

def test_an_update_during_a_pattern_build_waits_then_succeeds(dash, procs, monkeypatch):
    build = _sleeper(1.5)
    procs.append(build)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: _wait_window(dash) is not None)
    win = _wait_window(dash)
    assert "Building パターン data" in _texts(win)
    assert dash.calls["armed"] == [] and dash.calls["destroyed"] == 0
    # While it waits: the update lock is held, so the command line answers update-staged.
    assert path_utils.try_lock(updater.update_lock_path()) is None
    build.wait(timeout=10)
    assert _pump(dash, lambda: dash.calls["armed"])
    assert dash.calls["armed"] == [dash.calls["staged"]]
    assert dash.calls["destroyed"] == 1


def test_stop_it_stops_the_build_and_the_update_goes_on(dash, procs, monkeypatch):
    build = _sleeper(60)
    procs.append(build)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: _wait_window(dash) is not None)
    _button(_wait_window(dash), "Stop it")[0].invoke()
    assert build.wait(timeout=10) is not None
    assert _pump(dash, lambda: dash.calls["armed"])


def test_stop_all_stops_everything_and_updates(dash, procs, monkeypatch):
    build, generate = _sleeper(60), _sleeper(60)
    procs += [build, generate]
    generate.surasura_desc = "Generate"
    dash.active_processes.append(generate)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: _wait_window(dash) is not None and len(_button(_wait_window(dash), "Stop it")) == 2)
    assert {"Generate", "Building パターン data"} <= set(_texts(_wait_window(dash)))
    _button(_wait_window(dash), "Stop all and update now")[0].invoke()
    assert build.wait(timeout=10) is not None and generate.wait(timeout=10) is not None
    assert _pump(dash, lambda: dash.calls["armed"])


def test_every_button_in_the_waiting_window_has_a_tooltip(dash, procs, monkeypatch):
    build = _sleeper(60)
    procs.append(build)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    tips = []
    import app.main as main
    real = main.ToolTip
    monkeypatch.setattr(main, "ToolTip", lambda widget, text, *a, **k: (tips.append(widget), real(widget, text))[1])
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: _wait_window(dash) is not None)
    buttons = _widgets(_wait_window(dash), ttk.Button)
    assert len(buttons) == 3 and all(b in tips for b in buttons)


def test_a_child_asked_for_during_the_wait_is_deferred_and_starts_on_cancel(dash, procs, monkeypatch):
    build = _sleeper(60)
    procs.append(build)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    import app.main as main
    started = []
    monkeypatch.setattr(main.subprocess, "Popen", lambda args, **kw: started.append(args) or _sleeper(0))
    rebuilds = []
    monkeypatch.setattr(backfill, "start_rebuild", lambda *a, **k: rebuilds.append(a) or None)
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: _wait_window(dash) is not None)
    dash.run_command_async(["content_importer_gui.py", "--language", "ja"], "Content Manager")
    assert backfill.rebuild_in_background("ja") is False
    _pump(dash, lambda: False, timeout=0.3)
    assert started == [] and rebuilds == []
    assert "Content Manager will start if the update is cancelled." == dash.status_var.get()
    _esc(_wait_window(dash))
    assert _pump(dash, lambda: started and rebuilds)
    assert dash.calls["armed"] == []


def test_a_build_asked_for_by_its_window_during_the_wait_does_not_start(procs, monkeypatch):
    updater.hold_children()
    assert backfill.start_rebuild("ja") is None
    assert backfill.building() is False


def test_esc_during_the_wait_leaves_nothing_armed_and_the_update_is_offered_again(dash, procs, monkeypatch):
    build = _sleeper(60)
    procs.append(build)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: _wait_window(dash) is not None)
    job = dash._update_job                               # kept alive: the lock must be RELEASED, not collected
    _esc(_wait_window(dash))
    _pump(dash, lambda: False, timeout=0.5)
    assert _wait_window(dash) is None
    assert dash._update_job is None and not updater.children_held()
    assert dash.calls["armed"] == [] and dash.calls["discarded"] == 1
    assert not os.path.exists(updater.marker_path())
    assert updater.consume_result() is None              # the next start: nothing to report
    lock = path_utils.try_lock(updater.update_lock_path())
    assert lock is not None                              # free: the command line runs again
    path_utils.release_lock(lock)
    assert build.poll() is None                          # cancelling stops nothing
    assert job["lock"] is not None
    assert dash._update_info is not None                 # still offered


def test_closing_the_dashboard_during_the_wait_cancels_the_update(dash, procs, monkeypatch):
    build = _sleeper(60)
    procs.append(build)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: _wait_window(dash) is not None)
    dash.on_closing()
    assert dash._update_job is None and dash.calls["armed"] == []
    assert not os.path.exists(updater.marker_path())


def test_a_second_update_now_while_one_waits_starts_nothing_more(dash, procs, monkeypatch):
    build = _sleeper(60)
    procs.append(build)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    import app.main as main
    told = []
    monkeypatch.setattr(main.messagebox, "showinfo", lambda title, msg: told.append(msg))
    dash._do_auto_update(MagicMock())
    job = dash._update_job
    dash._do_auto_update(MagicMock())
    assert dash._update_job is job
    assert told == ["Another Surasura update is already in progress."]


def test_nothing_running_hands_over_without_a_window(dash, monkeypatch):
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    dash._do_auto_update(MagicMock())
    assert _pump(dash, lambda: dash.calls["armed"])
    assert _wait_window(dash) is None


def test_the_last_check_runs_in_the_final_callback(dash, procs, monkeypatch):
    """Something that started after the poll's listing (a command line, between two polls) is caught by the final
    callback's own check: no hand-over, the wait goes on."""
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    late = _sleeper(60)
    procs.append(late)
    late.surasura_desc = "Generate"
    job = {"info": dash._update_info, "lock": None, "staged": dash.calls["staged"], "window": None,
           "children": [], "done": True, "error": None}
    dash._update_job = job
    dash.active_processes.append(late)
    assert dash._apply_and_restart(job) is False
    assert dash.calls["armed"] == []
    dash._update_job = None


# --- the auto-Generate guard and Junban's automatic steps -------------------------------------------------------------

def _auto_generate_ready(dash, monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    dash.var_anki_auto_generate.set(True)
    dash._auto_generate_pending = True
    dash._generate_running = None
    dash._last_auto_generate = float("-inf")
    monkeypatch.setattr(dash, "_library_has_content", lambda: True)
    runs = []
    monkeypatch.setattr(dash, "run_analyzer", lambda quiet=False: runs.append(quiet))
    return runs


def test_the_auto_generate_guard_still_lets_a_generate_go_ahead_of_a_pattern_build(dash, procs, monkeypatch):
    """Backfill's design: a Generate started meanwhile goes first. The update's check is not the guard's."""
    build = _sleeper(60)
    procs.append(build)
    monkeypatch.setattr(backfill, "_PROCESS", build)
    runs = _auto_generate_ready(dash, monkeypatch)
    assert dash._maybe_auto_generate() is True and runs == [True]


def test_no_auto_generate_while_an_update_waits(dash, monkeypatch):
    runs = _auto_generate_ready(dash, monkeypatch)
    updater.hold_children()
    assert dash._maybe_auto_generate() is False and runs == []


def test_junbans_automatic_steps_wait_for_the_update(dash, monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    dash.var_enable_junban.set(True)
    import app.main as main
    asked = []
    monkeypatch.setattr(main.settings_manager, "load_settings", lambda *a, **k: asked.append(1) or {})
    updater.hold_children()
    dash._maybe_junban_auto(force=True)
    assert asked == []
    updater.release_children()
    dash._maybe_junban_auto(force=True)
    assert asked == [1]
