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
    assert frozen == ["Surasura.exe", "sentence_corpus", "--language", "ja", "--output",
                      "C:/out/Surasura Corpus (ja).zip"]
    source = tools.command(argv, frozen=False, executable="python")
    assert source[0] == "python" and source[2:] == argv[1:]
    assert os.path.normcase(source[1]) == os.path.normcase(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(tools.__file__))), "sentence_corpus.py"))
    # a script the map doesn't know runs as itself (the Tk map's `get(cmd[0], cmd[0])`)
    assert tools.command(["unknown.py", "-x"], frozen=True, executable="S.exe") == ["S.exe", "unknown.py", "-x"]


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
    slow = _script(tmp_path, f"""
        import os, time
        while not os.path.exists({str(gate)!r}):
            time.sleep(0.01)
        print("first done")
    """, "slow.py")
    quick = _script(tmp_path, "print('second done')\n", "quick.py")
    registry = jobs_module.JobRegistry()
    status = status_service.StatusService(registry)
    first = tools.run(registry, "sentence-corpus", "Building the sentence dictionary", [slow], frozen=False)
    second = tools.run(registry, "sentence-corpus", "Building the sentence dictionary", [quick], frozen=False)
    assert _wait(lambda: first.view().pid is not None)
    assert first.view().state == jobs_module.RUNNING and second.view().state == jobs_module.WAITING
    assert any("Building the sentence dictionary" in line for line in status.snapshot().lines)
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


def test_run_returns_at_once(tmp_path):
    slow = _script(tmp_path, "import time; time.sleep(2)\n")
    registry = jobs_module.JobRegistry()
    t0 = time.perf_counter()
    job = tools.run(registry, "sentence-corpus", "x", [slow], frozen=False)
    assert time.perf_counter() - t0 < 0.2
    job.cancel()
    assert job.wait(20)
