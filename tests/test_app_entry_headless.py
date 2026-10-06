"""app_entry.py --headless (P0.3 02-contract §1, P1.1 row 1.1.5): a subcommand another program started never opens a
window. A crash is logged and exits 1 with no Critical Error box; an unknown or missing command exits 2 and never opens
the dashboard; the log is in the local data folder, not the folder the program was started from.

Each case runs app_entry.main() in a fresh process with tkinter and the dashboard blocked at import, so a regression
records the attempt instead of opening a real dialog that would hang the run.
"""
import json
import os
import subprocess
import sys
import textwrap

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_entry(root, argv, analyzer_main="raise"):
    """app_entry.main() with `argv`. Returns (exit code, the GUI imports it attempted, the argv the analyzer saw)."""
    script = textwrap.dedent(f"""
        import json, sys

        class Block:
            attempted = []
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in ("tkinter", "_tkinter") or name == "app.main":
                    self.attempted.append(name)
                    raise ImportError("blocked by the test: " + name)
                return None
        block = Block()
        sys.meta_path.insert(0, block)

        import app_entry
        from app import analyzer
        seen = []
        def fake_main():
            seen.append(list(sys.argv[1:]))
            if {analyzer_main!r} == "raise":
                raise RuntimeError("forced analyzer failure")
        analyzer.main = fake_main

        sys.argv = ["Surasura.exe"] + {argv!r}
        try:
            app_entry.main()
            code = 0
        except SystemExit as e:
            code = e.code
        sys.stdout.write("\\n" + json.dumps([code, block.attempted, seen]) + "\\n")
    """)
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root))
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(root), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout.decode("utf-8").splitlines()[-1])


def _app_log(root):
    with open(os.path.join(str(root), "local", "logs", "app_debug_log.txt"), encoding="utf-8") as f:
        return f.read()


def test_a_forced_analyzer_exception_headless_exits_1_with_no_tk(tmp_path):
    code, attempted, seen = _run_entry(tmp_path, ["analyzer", "--headless", "--no-open"])
    assert code == 1 and attempted == []
    assert seen == [["--no-open"]]                       # the analyzer never sees --headless
    log = _app_log(tmp_path)
    assert "CRITICAL ERROR" in log and "forced analyzer failure" in log


def test_without_headless_the_crash_still_reaches_for_its_dialog(tmp_path):
    # The window's own behaviour is unchanged (and this is the check's witness: the blocker sees the attempt).
    code, attempted, _seen = _run_entry(tmp_path, ["analyzer"])
    assert code == 1 and "tkinter" in attempted


def test_headless_success_exits_cleanly(tmp_path):
    code, attempted, seen = _run_entry(tmp_path, ["--headless", "analyzer", "--lang", "ja"], analyzer_main="ok")
    assert code is None or code == 0
    assert attempted == [] and seen == [["--lang", "ja"]]


def test_an_unknown_command_headless_never_opens_the_dashboard(tmp_path):
    code, attempted, _seen = _run_entry(tmp_path, ["nope", "--headless"])
    assert code == 2 and attempted == []
    assert "Unknown command: nope" in _app_log(tmp_path)


def test_headless_alone_never_opens_the_dashboard(tmp_path):
    code, attempted, _seen = _run_entry(tmp_path, ["--headless"])
    assert code == 2 and attempted == []


def test_the_log_is_never_written_where_the_program_was_started(tmp_path):
    # Before P1.1 the log went to <working folder>/debug/: a caller's folder (Connect's, a shortcut's) got a debug/.
    _run_entry(tmp_path, ["analyzer", "--headless"])
    assert not os.path.exists(os.path.join(str(tmp_path), "debug"))
    assert "App starting" in _app_log(tmp_path)
