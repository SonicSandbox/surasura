"""The child runner (W3.4 row 1; `app/services/tools.py`): a tool the window starts runs as a child, as a job.

What a wrong answer would cost: an export or an importer reported "done" when its child failed (the Tk dashboard judged
the export by a file's time alone); two exports racing on the same file; a child holding the window's thread; a secret
or the test harness's offscreen platform leaking into a child; a job that never ends in the bar (a cancel before it
started, a child that couldn't start); a frozen build launching a second window instead of the tool (a subcommand the
dispatch doesn't know).
"""
import inspect
import os
import sys
import textwrap
import time

import pytest

from app.services import jobs as jobs_module
from app.services import tools


def _script(tmp_path, body, name="tool.py"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


def _wait(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class Ends:
    """`on_end`'s record: every call, and when the first came."""

    def __init__(self):
        self.codes = []

    def __call__(self, code):
        self.codes.append(code)


# --- the frozen / source command map --------------------------------------------------------------------------- #
def test_a_frozen_build_runs_the_subcommand_and_source_runs_the_script():
    argv = ["sentence_corpus.py", "--language", "ja", "--output", "C:/out/Surasura Corpus (ja).zip"]
    frozen = tools.command(argv, frozen=True, executable="Surasura.exe")
    # --headless (AD1-5): a crash is logged and exits 1, never a Critical Error box from an invisible child; an
    # unknown word exits 2, never opens a second window (app_entry strips the flag before it dispatches)
    assert frozen == ["Surasura.exe", "sentence_corpus", "--headless", "--language", "ja", "--output",
                      "C:/out/Surasura Corpus (ja).zip"]
    source = tools.command(argv, frozen=False, executable="python")
    assert source[0] == "python" and source[2:] == argv[1:]
    assert os.path.normcase(source[1]) == os.path.normcase(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(tools.__file__))), "sentence_corpus.py"))
    # a script the map doesn't know runs as itself (the Tk map's `get(cmd[0], cmd[0])`)
    assert tools.command(["unknown.py", "-x"], frozen=True, executable="S.exe") == ["S.exe", "unknown.py", "--headless",
                                                                                   "-x"]
    assert "--headless" not in source                    # source mode runs the script itself: no app_entry to strip it


def test_every_subcommand_in_the_map_is_one_the_frozen_build_dispatches():
    """A frozen build launches `Surasura.exe <word>`: a word app_entry doesn't route opens a second window instead."""
    import app_entry
    dispatch = inspect.getsource(app_entry.main)
    for script, word in tools.SCRIPT_MAP.items():
        assert f"command == '{word}'" in dispatch, (script, word)


def test_the_map_is_the_tk_dashboards_map_as_it_is():
    from app.main import MasterDashboardApp
    source = inspect.getsource(MasterDashboardApp.run_command_async)
    for script, word in tools.SCRIPT_MAP.items():
        if script in tools.QT_SCRIPTS:                     # the 3.0 window's own tools (W3.4 row 2)
            continue
        assert f"'{script}': '{word}'" in source


# --- running a child as a job ---------------------------------------------------------------------------------- #
def test_a_child_that_exits_0_is_done_its_lines_reach_the_listener_and_its_log(tmp_path):
    script = _script(tmp_path, """
        print("Reading 第01話.txt")
        print("Saved Surasura Corpus (ja) — 1,234 words")
    """)
    registry, lines, ends = jobs_module.JobRegistry(), [], Ends()
    job = tools.run(registry, "sentence-corpus", "Building the sentence dictionary", [script],
                    on_line=lines.append, on_end=ends, frozen=False)
    assert job.wait(60)
    assert job.view().state == jobs_module.DONE and not job.view().cancelled
    assert lines == ["Reading 第01話.txt", "Saved Surasura Corpus (ja) — 1,234 words"]
    assert _wait(lambda: ends.codes == [0])
    log = open(tools.log_path("sentence-corpus"), encoding="utf-8").read()
    assert "Reading 第01話.txt" in log and "1,234 words" in log and "[exit 0]" in log


def test_a_nonzero_exit_is_a_failure_naming_the_log_whatever_the_child_printed(tmp_path):
    # The exit code decides — a child that printed "Saved" and then failed is a failure.
    script = _script(tmp_path, """
        import sys
        print("Saved, supposedly")
        sys.exit(1)
    """)
    registry, ends = jobs_module.JobRegistry(), Ends()
    job = tools.run(registry, "sentence-corpus", "Building the sentence dictionary", [script], on_end=ends,
                    frozen=False)
    assert job.wait(60)
    view = job.view()
    assert view.state == jobs_module.FAILED
    assert tools.log_path("sentence-corpus") in view.message and "code 1" in view.message
    assert _wait(lambda: ends.codes == [1])


def test_the_child_gets_its_own_variables_utf8_and_never_the_harness_platform(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    script = _script(tmp_path, """
        import os, sys
        print(os.environ.get("SURASURA_TOOL_SECRET"), os.environ.get("QT_QPA_PLATFORM"), os.environ.get("PYTHONIOENCODING"))
        print(sys.argv[1:])
    """)
    registry, lines = jobs_module.JobRegistry(), []
    job = tools.run(registry, "sentence-corpus", "x", [script, "--language", "ja"], env={"SURASURA_TOOL_SECRET": "k1"},
                    on_line=lines.append, frozen=False)
    assert job.wait(60) and job.view().state == jobs_module.DONE
    assert lines == ["k1 None utf-8", "['--language', 'ja']"]
    assert "k1" not in job.view().label


def test_before_runs_first_on_the_tools_thread(tmp_path):
    marker = tmp_path / "settings-written"
    script = _script(tmp_path, f"""
        import os
        print(os.path.exists({str(marker)!r}))
    """)
    registry, lines = jobs_module.JobRegistry(), []
    job = tools.run(registry, "sentence-corpus", "x", [script], on_line=lines.append,
                    before=lambda: marker.write_text("1"), frozen=False)
    assert job.wait(60) and lines == ["True"]


def test_a_failing_before_still_runs_the_child(tmp_path):
    script = _script(tmp_path, "print('ran')\n")
    registry, lines = jobs_module.JobRegistry(), []

    def before():
        raise OSError("the settings lock is held")
    job = tools.run(registry, "sentence-corpus", "x", [script], on_line=lines.append, before=before, frozen=False)
    assert job.wait(60) and job.view().state == jobs_module.DONE and lines == ["ran"]


def test_a_log_that_cant_be_opened_never_stops_the_child(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_open_log", lambda path: None)
    script = _script(tmp_path, "print('ran')\n")
    registry, lines = jobs_module.JobRegistry(), []
    job = tools.run(registry, "sentence-corpus", "x", [script], on_line=lines.append, frozen=False)
    assert job.wait(60) and job.view().state == jobs_module.DONE and lines == ["ran"]


def test_a_child_that_cant_start_is_a_failed_job_and_its_owner_hears_the_end(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "command", lambda argv, frozen=None: [str(tmp_path / "no-such-program.exe")])
    registry, ends = jobs_module.JobRegistry(), Ends()
    job = tools.run(registry, "sentence-corpus", "Building", ["sentence_corpus.py"], on_end=ends)
    assert job.wait(30)
    assert job.view().state == jobs_module.FAILED and "couldn't start" in job.view().message
    assert _wait(lambda: ends.codes == [None])


def test_a_second_tool_of_its_kind_waits_for_the_first_and_shows_in_the_bar(tmp_path):
    from app.services import status as status_service
    gate = tmp_path / "go"
    # The child gives up by itself after 2 minutes, and the gate opens whatever the asserts say: a failed assert (or a
    # planted bug in a mutant run) never leaves the child running after the test.
    slow = _script(tmp_path, f"""
        import os, time
        deadline = time.monotonic() + 120
        while not os.path.exists({str(gate)!r}) and time.monotonic() < deadline:
            time.sleep(0.01)
        print("first done")
    """, "slow.py")
    quick = _script(tmp_path, "print('second done')\n", "quick.py")
    registry = jobs_module.JobRegistry()
    status = status_service.StatusService(registry)
    first = tools.run(registry, "sentence-corpus", "Building the sentence dictionary", [slow], frozen=False)
    second = tools.run(registry, "sentence-corpus", "Building the sentence dictionary", [quick], frozen=False)
    try:
        assert _wait(lambda: first.view().pid is not None)
        assert first.view().state == jobs_module.RUNNING and second.view().state == jobs_module.WAITING
        assert any("Building the sentence dictionary" in line for line in status.snapshot().lines)
    finally:
        gate.write_text("1")
    assert first.wait(60) and second.wait(60)
    assert first.view().ended_at <= second.view().started_at
    assert second.view().state == jobs_module.DONE


def test_a_tool_waits_for_generate_which_shares_the_token_store(tmp_path):
    script = _script(tmp_path, "print('ran')\n")
    registry = jobs_module.JobRegistry()
    generate = registry.submit("generate", "Generating", start=lambda job: None)
    job = tools.run(registry, "sentence-corpus", "x", [script], frozen=False)
    assert job.view().state == jobs_module.WAITING
    generate.finish()
    assert job.wait(60) and job.view().state == jobs_module.DONE


def test_cancelling_a_running_tool_ends_its_child(tmp_path):
    slow = _script(tmp_path, """
        import time
        print("started", flush=True)
        time.sleep(60)
    """)
    registry, lines, ends = jobs_module.JobRegistry(), [], Ends()
    job = tools.run(registry, "sentence-corpus", "x", [slow], on_line=lines.append, on_end=ends, frozen=False)
    assert _wait(lambda: lines == ["started"])
    t0 = time.monotonic()
    job.cancel()
    assert job.wait(20) and time.monotonic() - t0 < 20
    assert job.view().state == jobs_module.DONE and job.view().cancelled
    assert _wait(lambda: len(ends.codes) == 1) and ends.codes[0] not in (0, None)


def test_a_tool_cancelled_before_it_started_never_starts_and_its_owner_hears_once(tmp_path):
    marker = tmp_path / "started"
    script = _script(tmp_path, f"open({str(marker)!r}, 'w').write('1')\n")
    registry, ends = jobs_module.JobRegistry(), Ends()
    generate = registry.submit("generate", "Generating", start=lambda job: None)
    job = tools.run(registry, "sentence-corpus", "x", [script], on_end=ends, frozen=False)
    job.cancel()
    generate.finish()
    assert job.view().state == jobs_module.DONE and job.view().cancelled
    assert ends.codes == [None]
    time.sleep(0.3)
    assert not marker.exists() and ends.codes == [None]


def test_a_tool_cancelled_while_its_settings_are_written_never_starts_its_child(tmp_path):
    # Cancelled during `before` (the settings flush): the child is never started at all — no pid, no process.
    import threading
    script = _script(tmp_path, "print('ran')\n")
    registry, ends, lines = jobs_module.JobRegistry(), Ends(), []
    flushing, go_on = threading.Event(), threading.Event()

    def before():
        flushing.set()
        go_on.wait(10)
    job = tools.run(registry, "sentence-corpus", "x", [script], on_line=lines.append, on_end=ends, before=before,
                    frozen=False)
    assert flushing.wait(10)
    job.cancel()
    go_on.set()
    assert job.wait(20) and job.view().cancelled
    assert job.view().pid is None and lines == []
    assert _wait(lambda: ends.codes == [None])


def test_a_cancel_while_the_child_is_starting_still_ends_it(tmp_path, monkeypatch):
    # The cancel lands after the child was made but before the runner holds it (the cancel can't reach it then):
    # the runner sees the ask and ends the child itself.
    import subprocess
    import threading
    slow = _script(tmp_path, "import time; time.sleep(60)\n")
    registry, holder, ready = jobs_module.JobRegistry(), {}, threading.Event()
    real = subprocess.Popen

    def popen(*a, **k):
        process = real(*a, **k)
        ready.wait(10)
        holder["job"].cancel()
        return process
    monkeypatch.setattr(subprocess, "Popen", popen)
    holder["job"] = tools.run(registry, "sentence-corpus", "x", [slow], frozen=False)
    ready.set()
    assert holder["job"].wait(20)
    assert holder["job"].view().cancelled


class _Racing:
    """A registry that hands the tool a cancel in the moment between starting it and its `start` call (the real
    registry's window between marking a job running and calling `start`, outside its lock)."""

    class Job:
        def __init__(self):
            self.ended = []
            self.pid = None

        def finish(self, **kw):
            self.ended.append(kw)

        def started_process(self, pid):
            self.pid = pid

    def submit(self, kind, label, start, cancel=None, **kw):
        job = self.Job()
        cancel(job)
        start(job)
        return job


def test_a_cancel_racing_the_start_tells_the_owner_once(tmp_path):
    script = _script(tmp_path, "print('ran')\n")
    ends = Ends()
    job = tools.run(_Racing(), "sentence-corpus", "x", [script], on_end=ends, frozen=False)
    assert _wait(lambda: job.ended)
    time.sleep(0.2)
    assert ends.codes == [None] and job.pid is None


# --- the fix round (the adversary's AD1-1, -7, -13, -14, -15; the intent keeper's IK-22) ---------------------------- #
def test_a_log_folder_that_cant_be_made_never_leaves_a_stuck_job(tmp_path, monkeypatch):
    # AD1-1: the log's folder raising (a profile folder it can't write) once killed the tool's thread before its try:
    # the job stayed running for the session and held the token store — every Generate waited for ever.
    def no_folder(kind):
        raise PermissionError("the local data folder can't be written")
    monkeypatch.setattr(tools, "log_path", no_folder)
    script = _script(tmp_path, "print('ran')\n")
    registry, ends, results = jobs_module.JobRegistry(), Ends(), []
    job = tools.run(registry, "sentence-corpus", "x", [script], on_end=ends, on_result=results.append, frozen=False)
    assert job.wait(30) and job.view().state == jobs_module.DONE
    assert _wait(lambda: ends.codes == [0]) and results[0].log is None
    generate = registry.submit("generate", "Generating", start=lambda j: None)
    assert generate.view().state == jobs_module.RUNNING        # nothing holds the token store any more


def test_a_tool_thread_that_cant_start_fails_its_job_and_tells_its_owner(tmp_path, monkeypatch):
    import threading
    script = _script(tmp_path, "print('ran')\n")

    def refuse(self):
        raise RuntimeError("can't start new thread")
    with monkeypatch.context() as patched:      # scoped: an undo() would also undo the harness's test root
        patched.setattr(threading.Thread, "start", refuse)
        registry, ends = jobs_module.JobRegistry(), Ends()
        job = tools.run(registry, "sentence-corpus", "x", [script], on_end=ends, frozen=False)
    assert job.view().state == jobs_module.FAILED
    assert ends.codes == [None]


def test_a_child_that_cant_start_says_why_in_its_log(tmp_path, monkeypatch):
    # AD1-7: the reason was only in the bar; *Open the log* opened a log with no word of it.
    monkeypatch.setattr(tools, "command", lambda argv, frozen=None: [str(tmp_path / "no-such-program.exe")])
    registry, results = jobs_module.JobRegistry(), []
    job = tools.run(registry, "sentence-corpus", "Building", ["sentence_corpus.py"], on_result=results.append)
    assert job.wait(30) and _wait(lambda: results)
    assert results[0].code is None and not results[0].cancelled and results[0].why
    log = open(tools.log_path("sentence-corpus"), encoding="utf-8").read()
    assert results[0].why in log


def test_the_result_says_whether_the_run_was_stopped(tmp_path):
    # IK-22 / AD1-7: a stop is not a failure — the owner hears which it was.
    slow = _script(tmp_path, "import time\nprint('started', flush=True)\ntime.sleep(60)\n", "slow.py")
    failing = _script(tmp_path, "import sys\nsys.exit(3)\n", "failing.py")
    registry, lines, stopped, failed = jobs_module.JobRegistry(), [], [], []
    job = tools.run(registry, "sentence-corpus", "x", [slow], on_line=lines.append, on_result=stopped.append,
                    frozen=False)
    assert _wait(lambda: lines == ["started"])
    job.cancel()
    assert job.wait(20) and _wait(lambda: stopped)
    assert stopped[0].cancelled and stopped[0].code not in (0, None)
    other = tools.run(registry, "sentence-corpus", "x", [failing], on_result=failed.append, frozen=False)
    assert other.wait(30) and _wait(lambda: failed)
    assert failed[0] == tools.Result(3, False, None, tools.log_path("sentence-corpus"))


def test_an_error_after_the_child_started_ends_the_child(tmp_path, monkeypatch):
    # AD1-13: a broken pipe after Popen once left the child running, untracked, writing the user's file.
    import subprocess
    slow = _script(tmp_path, "import time\nprint('started', flush=True)\ntime.sleep(60)\n")
    real = subprocess.Popen
    made = []

    class Broken:
        def __init__(self, process):
            self.process = process
            self.pid = process.pid

        @property
        def stdout(self):
            raise OSError("the pipe broke")

        def __getattr__(self, name):
            return getattr(self.process, name)

    def popen(*a, **k):
        process = real(*a, **k)
        made.append(process)
        return Broken(process)
    monkeypatch.setattr(subprocess, "Popen", popen)
    registry, results = jobs_module.JobRegistry(), []
    job = tools.run(registry, "sentence-corpus", "x", [slow], on_result=results.append, frozen=False)
    assert job.wait(30)
    assert made and made[0].poll() is not None                # ended, not left running
    assert job.view().state == jobs_module.FAILED and "couldn't start" not in job.view().message
    assert "the pipe broke" in job.view().message


def test_a_cancel_landing_as_the_child_exits_0_reads_as_done(tmp_path, monkeypatch):
    # AD1-15: the child finished; a cancel arriving just then must not make the bar say "cancelled".
    import subprocess
    quick = _script(tmp_path, "print('done')\n")
    real = subprocess.Popen
    holder = {}

    class LateCancel:
        def __init__(self, process):
            self.process = process

        def wait(self, *a, **k):
            code = self.process.wait(*a, **k)
            holder["job"].cancel()
            return code

        def __getattr__(self, name):
            return getattr(self.process, name)
    import threading
    ready = threading.Event()

    def popen(*a, **k):
        ready.wait(10)
        return LateCancel(real(*a, **k))
    monkeypatch.setattr(subprocess, "Popen", popen)
    registry, results = jobs_module.JobRegistry(), []
    holder["job"] = tools.run(registry, "sentence-corpus", "x", [quick], on_result=results.append, frozen=False)
    ready.set()
    assert holder["job"].wait(30)
    view = holder["job"].view()
    assert view.state == jobs_module.DONE and not view.cancelled
    assert _wait(lambda: results) and results[0].code == 0
    assert not results[0].cancelled                        # the owner hears "done" too, never "stopped"


def test_a_queued_tool_keeps_the_environment_it_was_asked_with(tmp_path, monkeypatch):
    # AD1-14: a job that starts after its asker's test root changed (a test's teardown) must not reach the real one.
    script = _script(tmp_path, "import os\nprint(os.environ.get('SURASURA_TEST_ROOT'))\n")
    asked_root = os.environ["SURASURA_TEST_ROOT"]
    registry, lines = jobs_module.JobRegistry(), []
    generate = registry.submit("generate", "Generating", start=lambda j: None)
    job = tools.run(registry, "sentence-corpus", "x", [script], on_line=lines.append, frozen=False)
    other = tmp_path / "another-root"
    other.mkdir()
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(other))
    generate.finish()
    assert job.wait(30) and lines == [asked_root]
    assert not os.path.exists(os.path.join(str(other), "local"))   # no log written under a root it wasn't asked in


def test_run_returns_at_once(tmp_path):
    slow = _script(tmp_path, "import time; time.sleep(2)\n")
    registry = jobs_module.JobRegistry()
    t0 = time.perf_counter()
    job = tools.run(registry, "sentence-corpus", "x", [slow], frozen=False)
    assert time.perf_counter() - t0 < 0.2
    job.cancel()
    assert job.wait(20)


def test_the_3_0_tools_run_as_their_subcommands_when_frozen():
    for script, word in (("anki_db_import.py", "apkg_known_import"), ("extract.py", "extract"),
                         ("jiten_converter.py", "convert_jiten")):
        assert tools.command([script, "--language", "ja"], frozen=True, executable="S.exe") == \
            ["S.exe", word, "--headless", "--language", "ja"]


def test_each_run_writes_its_log_fresh(tmp_path):
    # The log is one run's lines: Open the log never shows an older run's success under a new failure.
    first = _script(tmp_path, "print('first run: Saved')\n", "first.py")
    second = _script(tmp_path, "import sys\nprint('second run')\nsys.exit(1)\n", "second.py")
    registry = jobs_module.JobRegistry()
    assert tools.run(registry, "sentence-corpus", "x", [first], frozen=False).wait(30)
    assert tools.run(registry, "sentence-corpus", "x", [second], frozen=False).wait(30)
    log = open(tools.log_path("sentence-corpus"), encoding="utf-8").read()
    assert "second run" in log and "first run" not in log
