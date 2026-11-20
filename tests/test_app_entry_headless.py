"""app_entry.py --headless (P0.3 02-contract §1, P1.1 row 1.1.5): a subcommand another program started never opens a
window. A crash is logged and exits 1 with no Critical Error box; an unknown or missing command exits 2 and never opens
the dashboard; the log is in the local data folder, not the folder the program was started from.

Each case runs app_entry.run() in a fresh process with tkinter and the dashboard blocked at import, so a regression
records the attempt instead of opening a real dialog that would hang the run.
"""
import json
import os
import subprocess
import sys
import textwrap

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_entry(root, argv, analyzer_main="raise"):
    """app_entry.run() (the program as it starts: the dispatch, its end logged) with `argv`. Returns (exit code, the GUI
    imports it attempted, the argv the analyzer saw)."""
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
            app_entry.run()
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


def _run_entry_window_gone(root, argv, main="cancel"):
    """app_entry.run() with `argv` as Surasura.exe's analyzer child after its window closed: stdout and stderr a real
    pipe whose reading end is already closed (Windows answers a write with OSError 22, elsewhere a broken pipe), the
    real `_reporting_progress` around a run that reaches its first step with its cancel file made, tkinter blocked.
    Returns (exit code, the GUI imports it attempted), through a file (stdout is the broken pipe)."""
    answer = os.path.join(str(root), "answer.json")
    flag = os.path.join(str(root), "cancel.flag")
    with open(flag, "w", encoding="utf-8") as f:
        f.write("cancel")
    script = textwrap.dedent(f"""
        import json, os, sys

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
        if {main!r} == "cancel":
            analyzer.main = analyzer._reporting_progress(lambda: analyzer._progress("Reading your files"))
        else:                                           # a child's plain line, no wrapper of its own
            analyzer.main = lambda: print("Processing 第01話.srt...", flush=True)

        read, write = os.pipe()
        os.close(read)                                  # the window has gone
        sys.stdout = open(write, "w", encoding="utf-8")
        sys.stderr = open(os.dup(write), "w", encoding="utf-8")
        sys.argv = ["Surasura.exe"] + {argv!r}
        try:
            app_entry.run()
            code = 0
        except SystemExit as e:
            code = e.code
        with open({answer!r}, "w", encoding="utf-8") as f:
            json.dump([code, block.attempted], f)
    """)
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root), SURASURA_CANCEL_FILE=flag)
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(root), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert os.path.exists(answer), proc.stderr.decode("utf-8", "replace")
    with open(answer, encoding="utf-8") as f:
        return json.load(f)


def test_a_cancelled_generate_whose_window_closed_exits_cancelled_with_no_dialog(tmp_path):
    # Haya-CL 3.0.17 (Sonic's laptop, 3.0.16): the window closed mid-Generate; the cancel's last line to the closed
    # pipe raised OSError 22 into the Critical Error box, which then held the child ~57 s until he closed it. Started
    # as 3.0.16's window started it (no --headless): no exception, the cancel's exit code, no dialog.
    from app import analyzer
    code, attempted = _run_entry_window_gone(tmp_path, ["analyzer", "--progress-json"])
    assert code == analyzer.GENERATE_CANCELLED and attempted == []
    assert "CRITICAL ERROR" not in _app_log(tmp_path)
    assert "Ended analyzer after" in _app_log(tmp_path) and f"(exit {analyzer.GENERATE_CANCELLED})" in _app_log(tmp_path)


def test_any_childs_plain_line_to_a_window_that_closed_goes_nowhere(tmp_path):
    # app_entry's own guard, for every command (the arrivals worker, the indexer, a Generate without --progress-json):
    # a print to the closed pipe ends nothing and opens nothing
    code, attempted = _run_entry_window_gone(tmp_path, ["analyzer"], main="print")
    assert code == 0 and attempted == []
    assert "CRITICAL ERROR" not in _app_log(tmp_path)


def test_every_child_the_window_starts_from_the_program_is_headless(monkeypatch):
    # Haya-CL 3.0.17: a crash of a child the learner can't see is logged and ends it (the window shows its own
    # failure), never a Critical Error box from Surasura.exe — as tools.command, the arrivals worker and the paste's
    # child already were. Generate, the indexer and Junban's library build weren't.
    from app import path_utils
    from app.services import chores, generate
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert generate.command_line(["analyzer.py", "--language=ja", "--progress-json"])[1:3] == ["analyzer", "--headless"]
    assert chores.indexer_command("zh")[1:3] == ["index", "--headless"]
    try:
        from modules.junban import backfill
    except ImportError:
        return
    assert backfill.rebuild_command("zh")[0][1:3] == ["junban_patterns", "--headless"]


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


def test_every_log_line_is_stamped_and_each_command_logs_its_end_with_its_length(tmp_path):
    # a7 (an alpha's setup): the log had no times, so how long a Generate ran, or how many ran in a burst, could only
    # be guessed. Each line now starts with the time and the process; each command's end says how long and how.
    import re
    _run_entry(tmp_path, ["analyzer", "--headless", "--lang", "ja"], analyzer_main="ok")
    _run_entry(tmp_path, ["analyzer", "--headless"])                        # a crash: exit 1
    _run_entry(tmp_path, ["nope", "--headless"])                            # an unknown command: exit 2
    lines = [line for line in _app_log(tmp_path).splitlines()                      # a traceback's lines aside
             if "App starting" in line or "Ended " in line or "CRITICAL ERROR" in line or "Unknown command" in line]
    stamp = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} \[\d+\] "
    assert lines and all(re.match(stamp, line) for line in lines), lines
    ends = [msg for msg in (re.sub(stamp, "", line) for line in lines) if msg.startswith("Ended ")]
    assert [re.sub(r"after \d+\.\d s", "after N s", end) for end in ends] == [
        "Ended analyzer after N s (exit 0)", "Ended analyzer after N s (exit 1)", "Ended nope after N s (exit 2)"]
    starts = [line.split(" ", 3)[2] for line in lines if "App starting" in line]
    assert len(set(starts)) == 3, "three processes, each named on its lines"


def test_the_windows_log_lines_are_stamped_too(monkeypatch, tmp_path):
    from app import path_utils
    from app.qt import applog
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path))
    applog.log("wizard", "the setup wizard didn't open: 例のエラー")
    line = _app_log(tmp_path).splitlines()[-1]
    assert line.endswith(f"[{os.getpid()}] window (wizard): the setup wizard didn't open: 例のエラー")
    assert path_utils.get_local_data_path().startswith(str(tmp_path))
