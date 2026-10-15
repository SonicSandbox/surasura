"""`app_entry.py` routing on the 3.0 line (W2.1 row 10; the window's spec 01 §1.6; RUNBOOK G-1).

What a wrong answer would cost: the 3.0 line still opening the Tk dashboard (the window never seen), or a build
without PyQt6 crashing at start instead of opening the dashboard; the Tk dashboard unreachable while the window can't
do its work yet (until W3.4's last row); a second heartbeat from the window; a headless verb (the analyzer Connect runs, the store's helper) loading Qt.

Each case runs app_entry.main() in a fresh process with the window and the dashboard replaced by recorders, so
nothing opens.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(tmp_path, argv, hide_qt=False, fake_window=True, beats=False):
    """-> (exit code, what opened: ["window"] / ["dashboard"] — with `beats`, each heartbeat too, as "heartbeat" —, Qt
    modules loaded, the log)."""
    script = textwrap.dedent(f"""
        import json, sys, types
        opened = []

        class Block:
            def find_spec(self, name, path=None, target=None):
                if {hide_qt!r} and name.split(".")[0] == "PyQt6":
                    raise ModuleNotFoundError("No module named 'PyQt6'", name="PyQt6")
                return None
        sys.meta_path.insert(0, Block())

        dash = types.ModuleType("app.main")
        dash.main = lambda: opened.append("dashboard")
        sys.modules["app.main"] = dash
        tele = types.ModuleType("app.telemetry")
        tele.init = lambda *a, **k: opened.append("heartbeat") if {beats!r} else None
        sys.modules["app.telemetry"] = tele
        if {fake_window!r} and not {hide_qt!r}:
            win = types.ModuleType("app.qt.shell")
            win.main = lambda argv=None: opened.append("window") or 0
            import app.qt
            sys.modules["app.qt.shell"] = win
            app.qt.shell = win

        import app_entry
        from app import analyzer
        analyzer.main = lambda: 0
        sys.argv = ["Surasura.exe"] + {argv!r}
        try:
            app_entry.main()
            code = 0
        except SystemExit as e:
            code = e.code
        qt = sorted(m for m in sys.modules if m.startswith("PyQt6"))
        sys.stdout.write("\\n" + json.dumps([code, opened, qt]) + "\\n")
    """)
    env = dict(os.environ, PYTHONPATH=ROOT, SURASURA_TEST_ROOT=str(tmp_path))
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(tmp_path), env=env, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]
    code, opened, qt = json.loads(proc.stdout.strip().splitlines()[-1])
    log_file = os.path.join(str(tmp_path), "local", "logs", "app_debug_log.txt")
    log = open(log_file, encoding="utf-8").read() if os.path.exists(log_file) else ""
    return code, opened, qt, log


def test_the_default_start_opens_the_window(tmp_path):
    code, opened, _qt, log = _run(tmp_path, [])
    assert opened == ["window"] and code in (0, None)
    assert "Launching the window" in log


def test_the_window_route_sends_the_heartbeat_once_before_the_window(tmp_path):
    """IK-27 (W3.5 RUNBOOK row 6: the heartbeat stays where it is — `app_entry.py` sends it before either window
    opens): the window's route sends it once, before the window; nothing in the window or its services starts another
    (the update's own event, `send_update_event`, is the reconcile's)."""
    code, opened, _qt, _log = _run(tmp_path, [], beats=True)
    assert opened == ["heartbeat", "window"] and code in (0, None)
    for folder in (os.path.join(ROOT, "app", "qt"), os.path.join(ROOT, "app", "services")):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    assert "telemetry.init" not in f.read(), name


def test_without_pyqt6_the_dashboard_opens_and_the_log_says_why(tmp_path):
    code, opened, qt, log = _run(tmp_path, [], hide_qt=True)
    assert opened == ["dashboard"] and qt == []
    assert "needs PyQt6" in log


def test_the_dashboard_verb_keeps_the_tk_dashboard_reachable(tmp_path):
    code, opened, qt, _log = _run(tmp_path, ["dashboard"])
    assert opened == ["dashboard"] and qt == []


def test_an_unknown_command_still_opens_the_window_not_the_dashboard(tmp_path):
    code, opened, _qt, log = _run(tmp_path, ["nope"])
    assert opened == ["window"] and "Unknown command: nope" in log


@pytest.mark.parametrize("argv", [["analyzer", "--headless", "--no-open"], ["dashboard", "--headless"], ["--headless"]])
def test_a_headless_start_loads_no_qt_and_opens_nothing(tmp_path, argv):
    code, opened, qt, _log = _run(tmp_path, argv, fake_window=False)
    assert opened == [] and qt == []


HEAVY = ("pandas", "numpy", "requests", "app.static_html_generator")
# Proof the duties ran: made (chores), their controls attached (duties), started, and the start's last timer rang (the
# Rarity tables' warm-up at `chores.WARM_AT` reads the one-kanji table).
RAN = ("app.services.chores", "app.qt.duties", "app.one_kanji_data")


def test_the_window_start_brings_in_no_pandas_numpy_or_requests(tmp_path):
    """The start-light fix (2026-10-14): the real start — `app_entry.py`, the window, its first frame, the duties made
    and started on their workers, the start's timers up to the Rarity warm-up, a few seconds idle — imports neither pandas nor numpy (asking
    whether a journey exists imported the report's generator for its file name: pandas → numpy, whose OpenBLAS reserves
    a buffer per CPU thread — idle went from 65 MB to ~890 MB on a 24-thread desktop, ~360 MB on the laptop, budget
    ≤ ~250), nor requests (the heartbeat's module imported it at every start, ~0.1 s before the first frame: only a
    heartbeat that is sent imports it now, on its own thread). What a wrong answer would cost: the laptop's budgets."""
    import site
    root = tmp_path / "root"
    root.mkdir()
    probe = tmp_path / "probe.json"
    entry = os.path.join(ROOT, "app_entry.py")
    env = dict(os.environ, PYTHONPATH=ROOT, SURASURA_TEST_ROOT=str(root), SURASURA_SHELL_PROBE=str(probe),
               SURASURA_SHELL_PROBE_IDLE="4.5", TELEMETRY_ENV="dev", TELEMETRY_URL="",
               APPDATA=str(tmp_path / "appdata"), LOCALAPPDATA=str(tmp_path / "localappdata"),
               PYTHONUSERBASE=site.getuserbase())     # the packages installed for this user stay importable
    env.pop("SURASURA_NO_UI_TIMERS", None)            # the start's timers run (a chore at 1.5 s is the start's too)
    for gate in ("SURASURA_NO_AUTOINDEX", "SURASURA_NO_ANKI_SYNC", "SURASURA_NO_UPDATE_CHECK"):
        env[gate] = "1"                               # no indexer, Anki or GitHub from a test
    script = textwrap.dedent(f"""
        import json, runpy, sys
        sys.argv = [{entry!r}]
        try:
            runpy.run_path({entry!r}, run_name="__main__")
        except SystemExit:
            pass
        sys.stdout.write("\\n" + json.dumps([sorted(m for m in {HEAVY!r} if m in sys.modules),
                                              sorted(m for m in {RAN!r} if m in sys.modules)]) + "\\n")
    """)
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(root), env=env, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]
    with open(probe, encoding="utf-8") as f:
        assert json.load(f)["first_frame_ms"] > 0             # the window reached its first frame and idled
    log_file = root / "local" / "logs" / "app_debug_log.txt"
    log = log_file.read_text(encoding="utf-8")
    assert "Launching the window" in log
    assert "duties not made" not in log and "duties at start" not in log
    heavy, ran = json.loads(proc.stdout.strip().splitlines()[-1])
    assert ran == sorted(RAN), "the duties were made, attached and started, and the warm-up rang"
    assert heavy == []
