"""`app_entry.py` routing on the 3.0 line (W2.1 row 10; the window's spec 01 §1.6; RUNBOOK G-1).

What a wrong answer would cost: the 3.0 line still opening the Tk dashboard (the window never seen), or a build
without PyQt6 crashing at start instead of opening the dashboard; the Tk dashboard unreachable while the window can't
do its work yet (until W3.5); a headless verb (the analyzer Connect runs, the store's helper) loading Qt.

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


def _run(tmp_path, argv, hide_qt=False, fake_window=True):
    """-> (exit code, what opened: ["window"] / ["dashboard"], Qt modules loaded, the log)."""
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
        tele.init = lambda *a, **k: None
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
