"""`generate` and `junban --auto` run headless as the window runs them (P0.3 03, 05; P1.2 rows 1.2.5 and 1.2.6).

What a wrong answer would cost, in order:
  * two programs writing results/ at once — a headless Generate and the window's: the analyzer holds `results`
    itself, so even a killed command line leaves no writer without the lock, and the window waits its turn;
  * a report or browser window opening on the desktop from a background job (`--no-open`, never `--app-mode`);
  * a failed run that looks finished — a crash is exit 1 `crashed-child`, and no run stamp says the list is current;
  * an automatic reorder that writes more than positions, writes for "All decks", or writes while the user reviews.

Real Japanese files and the real analyzer; Anki is only the Junban suite's fake collection, never a live one.
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from unittest.mock import MagicMock

import pytest

from app import analyzer, locks
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _big_library(copies=40):
    """A library big enough that a Generate takes a few seconds: real transcript text, varied per file."""
    folder = h.seed_library("ja")
    text = open(os.path.join(h.RESOURCES, "ja", "runaway_transcript.txt"), encoding="utf-8").read()
    for n in range(copies):
        with open(os.path.join(folder, f"episode_{n:02d}.txt"), "w", encoding="utf-8") as f:
            f.write(text[n * 37:] + text[: n * 37])
    h.write_settings()


def _wait_for_the_child(cli, seconds=60):
    """The analyzer child holds `results` (its record names another pid than the command line's) -> its pid."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        holder = locks.read_holder("results")
        if holder and holder.get("pid") != cli.pid and holder.get("verb") == "Generate":
            return holder["pid"]
        assert cli.poll() is None, cli.communicate()
        time.sleep(0.05)
    raise AssertionError("the analyzer child never took results")


def _pid_alive(pid):
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #
def test_nothing_changed_answers_ran_false_without_loading_pandas():
    h.seed_library("ja")
    h.write_settings()
    assert h.run_cli("generate")[0] == 0
    script = textwrap.dedent("""
        import json, sys
        from app.cli import __main__ as cli
        code = cli.main(["generate"])
        sys.stdout.write("\\n" + json.dumps([code, "pandas" in sys.modules]) + "\\n")
    """)
    proc = subprocess.run([sys.executable, "-c", script], cwd=h.root(), env=h.child_env(), capture_output=True,
                          timeout=120)
    lines = proc.stdout.decode("ascii").splitlines()
    assert json.loads(lines[0])["ran"] is False
    assert json.loads(lines[-1]) == [0, False], "the nothing-changed answer never imports pandas"


def test_the_child_never_opens_anything_on_the_desktop(monkeypatch):
    """`--no-open` always and never `--app-mode`, whatever the window's "open as an app" says; started without a
    console window (CREATE_NO_WINDOW)."""
    from app.cli import verbs
    h.seed_library("ja")
    h.write_settings(open_app_mode=True)
    started = []

    class Child:
        pid = 4242

        def wait(self):
            return 0
    monkeypatch.setattr(verbs.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)) or Child())
    code, line = h.call("generate", "--force")
    assert code == 0 and line["ran"] is False, "the stand-in child wrote no run stamp: no analysis ran"
    (argv, kw), = started
    assert argv[argv.index("analyzer"):argv.index("analyzer") + 2] == ["analyzer", "--headless"]
    assert "--no-open" in argv and "--app-mode" not in argv
    if sys.platform == "win32":
        assert kw["creationflags"] & 0x08000000
    assert kw["env"]["SURASURA_RESULTS_WAIT"] == "10.0", "the hand-over's moment, at least"
    assert kw["env"]["SURASURA_FORCE_RUN"] == "1", "--force reaches the analyzer"
    started.clear()
    code, line = h.call("generate", "--force", "--wait", "45")
    (argv, kw), = started
    assert 40 < float(kw["env"]["SURASURA_RESULTS_WAIT"]) <= 45, "the child waits what is left of --wait"


def test_a_crashing_analyzer_is_crashed_child_with_no_run_stamp():
    """KnownWord.json cut short: the analyzer stops mid-run. Exit 1 `crashed-child`, the log named, no stamp, so
    `status` says the list is not current."""
    h.seed_library("ja")
    h.write_settings()
    with open(os.path.join(h.root(), "User Files", "ja", "KnownWord.json"), "w", encoding="utf-8") as f:
        f.write('{"words": [{"dictForm": "冒険"')
    code, lines = h.run_cli("generate")
    assert code == 1 and h.answer(lines)["code"] == "crashed-child" and h.answer(lines)["child_exit"] == 1
    assert os.path.exists(h.answer(lines)["log"])
    assert analyzer.read_run_stamp(os.path.join(h.root(), "results")) is None
    assert h.answer(h.run_cli("status")[1])["journey_current"] is not True
    events = [json.loads(x) for x in open(os.path.join(h.root(), "local", "logs", "cli-events.jsonl"), encoding="utf-8")]
    assert events[-1]["code"] == "crashed-child", "the window's bottom bar will show it"


def test_a_report_that_is_not_written_fails_the_run():
    """The report generator says a missing template and returns; the analyzer's exit code says it (1)."""
    h.seed_library("ja", templates=False)
    shutil.rmtree(os.path.join(h.root(), "templates"), ignore_errors=True)     # the test root's own copy
    h.write_settings()
    code, lines = h.run_cli("generate")
    assert code == 1 and h.answer(lines)["code"] == "crashed-child"


def test_a_second_generate_is_busy_naming_the_first_and_waits_when_asked():
    _big_library()
    first = h.start_cli("generate", "--force")
    try:
        _wait_for_the_child(first)
        code, lines = h.run_cli("generate")
        busy = h.answer(lines)
        assert code == 3 and busy["code"] == "busy" and busy["lock"] == "results"
        assert busy["held_by"]["verb"] == "Generate" and busy["held_by"]["pid"] != first.pid
        code, lines = h.run_cli("generate", "--wait", "120")
        assert code == 0 and h.answer(lines)["ran"] is False, "it waited for the first, which covered it"
    finally:
        first.communicate(timeout=300)
    assert first.returncode == 0


def test_the_parent_killed_mid_generate_leaves_the_child_holding_results_to_the_end():
    """Ctrl+C, a crash, Connect killed: the analyzer goes on alone and nobody else writes results/ meanwhile; when it
    ends, the lock is free and the stamp says its run."""
    _big_library()
    cli = h.start_cli("generate", "--force")
    child = _wait_for_the_child(cli)
    cli.kill()
    cli.wait(10)
    with pytest.raises(locks.Busy) as busy:
        locks.take("results", "a second Generate")
    assert busy.value.holder["pid"] == child, "the child still holds it"
    deadline = time.monotonic() + 300
    while _pid_alive(child) and time.monotonic() < deadline:
        time.sleep(0.2)
    with locks.take("results", "the test's look", wait=10):
        pass
    assert analyzer.read_run_stamp(os.path.join(h.root(), "results")), "the child finished its run alone"


def test_a_headless_generate_and_the_windows_never_write_together(monkeypatch):
    """The window's Generate pressed while `surasura-cli generate` runs: the bottom bar says it waits (no box, its
    thread free), and its analyzer starts only after the headless one let go."""
    from app.main import MasterDashboardApp
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)
    _big_library()
    cli = h.start_cli("generate", "--force")
    _wait_for_the_child(cli)
    app = MagicMock()
    app.gui_queue, app._closing_event = queue.Queue(), threading.Event()
    started = time.perf_counter()
    MasterDashboardApp._start_analyzer(app, ["analyzer.py", "--static", "--language=ja"], quiet=False)
    assert time.perf_counter() - started <= 0.004
    app.gui_queue.get(timeout=10)()
    app.status_var.set.assert_called_with("Waiting for a background Generate…")
    start = app.gui_queue.get(timeout=300)
    assert cli.poll() is not None or locks.read_holder("results") is None, "only once the headless run let go"
    start()
    assert app.run_command_async.call_count == 1
    cli.communicate(timeout=60)


# --------------------------------------------------------------------------- #
# junban --auto: the automatic reorder's guards, positions only
# --------------------------------------------------------------------------- #
FAKE_URL = "http://127.0.0.1:18765"         # nothing listens here: only the patched transport answers


@pytest.fixture
def junban(monkeypatch):
    rep = pytest.importorskip("modules.junban.tests.test_reposition")
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    rep._results(h.root(), progressive=rep._JOURNEY, library=rep._LIBRARY, floor=11)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)

    def setup(**over):
        cards, notes, _ = rep._collection(["須藤", "散歩", "図書館", "冒険"])
        fake = rep.FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend"),
                                  **{k: over.pop(k) for k in ("reviewing", "offline") if k in over})
        saved = rep._settings(junban_order="content", enable_junban=True, junban_later_tag=True,
                              junban_later_flag=True, junban_later_suspend=True, **over)
        saved.pop("junban_url", None)
        h.write_settings(**{**saved, "anki_connect_url": FAKE_URL})
        return fake, rep._patched(fake)
    return setup


def test_auto_writes_positions_only_even_with_every_action_switched_on(junban):
    fake, patched = junban(junban_auto_actions=True)
    with patched:
        code, line = h.call("junban", "--auto")
    assert code == 0 and line["moves"] > 0 and line["undo"], line
    assert fake.writes and fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == []
    assert not {"reloadCollection", "guiDeckBrowser"} & set(fake.action_names), "Anki's window is left alone"


def test_auto_for_all_decks_needs_you(junban):
    fake, patched = junban(junban_scope="all")
    with patched:
        code, line = h.call("junban", "--auto")
    assert code == 4 and line["code"] == "needs-you" and line["ask"] == "choose a deck in 順"
    assert fake.writes == []


def test_auto_while_the_user_reviews_is_anki_busy(junban):
    fake, patched = junban(reviewing=True)
    with patched:
        code, line = h.call("junban", "--auto")
    assert code == 3 and line["code"] == "anki-busy" and fake.writes == []


def test_auto_with_anki_closed_is_anki_closed(junban):
    fake, patched = junban(offline=True)
    with patched:
        code, line = h.call("junban", "--auto")
    assert code == 3 and line["code"] == "anki-closed"


def test_auto_while_a_junban_window_is_open_is_busy_and_waits_when_asked(junban):
    from tests.test_cli_locks import Holder
    fake, patched = junban()
    with Holder("junban-window", "the 順 window") as window, patched:
        code, line = h.call("junban", "--auto")
        assert code == 3 and line["code"] == "busy" and line["lock"] == "junban-window"
        assert line["held_by"]["verb"] == "the 順 window" and fake.writes == []
        threading.Timer(0.5, window.release).start()
        code, line = h.call("junban", "--auto", "--wait", "10")
    assert code == 0 and line["moves"] > 0


def test_auto_while_another_program_writes_to_anki_is_busy(junban):
    from tests.test_cli_locks import Holder
    fake, patched = junban()
    with Holder("anki-writer", "Backfill"), patched:
        code, line = h.call("junban", "--auto")
    assert code == 3 and line["code"] == "busy" and line["lock"] == "anki-writer"
    assert line["held_by"]["verb"] == "Backfill" and fake.writes == []


def test_auto_on_a_list_behind_the_library_skips(junban, monkeypatch):
    fake, patched = junban()
    monkeypatch.setattr(analyzer, "journey_is_current", lambda argv, lang: False)
    with patched:
        code, line = h.call("junban", "--auto")
    assert code == 0 and line["skipped"] == "the list is out of date: Generate first" and fake.writes == []


# --------------------------------------------------------------------------- #
# The review's cases (tracks/pipeline/reviews/P1.2-adversary.md #1, #2, #9)
# --------------------------------------------------------------------------- #
def _window_analyzer(*extra):
    """The analyzer as the window starts it: `app_entry.py analyzer …`, waiting for `results` without a limit."""
    from app import run_args, settings_manager
    argv = run_args.analyzer_args(settings_manager.load_settings(), "ja")
    env = h.child_env(SURASURA_RESULTS_WAIT="forever", SURASURA_FORCE_RUN="1")
    return subprocess.Popen([sys.executable, os.path.join(h.PROJECT_ROOT, "app_entry.py"), "analyzer"] + argv[1:]
                            + ["--no-open"] + list(extra), cwd=h.root(), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def test_a_window_generate_and_a_headless_one_started_together_both_finish():
    """#1: both start in the same moment (the hand-over): whichever takes `results` first runs, the other waits its
    turn — the window's without a limit, the command line's for what is left of --wait. Neither fails."""
    _big_library()
    window = _window_analyzer()
    cli = h.start_cli("generate", "--force", "--wait", "300")
    out, _err = cli.communicate(timeout=600)
    window_out, _ = window.communicate(timeout=600)
    assert cli.returncode == 0, out
    assert json.loads(out.decode("ascii").splitlines()[-1])["ran"] is True
    assert window.returncode == 0, window_out.decode("utf-8", "replace")[-2000:]


def test_a_crashing_analyzer_is_never_read_as_busy(tmp_path):
    """#2: a native abort exits 3 on Windows; the busy answer has its own code (75), so this is `crashed-child`, and
    the dead child's leftover holder record is never offered as `held_by`."""
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(textwrap.dedent("""
        import os, signal, sys, threading
        if os.environ.get("P12_ABORT_ANALYZER"):
            def _abort():
                if "app.analyzer" in sys.modules and "app.cli" not in sys.modules:     # the child, not the CLI
                    signal.raise_signal(signal.SIGABRT)
            threading.Timer(0.8, _abort).start()
    """), encoding="utf-8")
    _big_library()
    env = {"PYTHONPATH": str(hook) + os.pathsep + h.PROJECT_ROOT, "P12_ABORT_ANALYZER": "1"}
    code, lines = h.run_cli("generate", env=env)
    answer = h.answer(lines)
    assert code == 1 and answer["code"] == "crashed-child", answer
    assert answer["child_exit"] != analyzer.RESULTS_BUSY
    code, lines = h.run_cli("generate")                     # the lock is free again (the OS let go)
    assert code == 0, lines


def test_force_runs_the_analysis_and_ran_says_whether_it_did():
    """#9: `--force` runs the analysis though nothing changed (a new run stamp, `ran: true`); without it, `ran: false`."""
    h.seed_library("ja")
    h.write_settings()
    assert h.answer(h.run_cli("generate")[1])["ran"] is True
    assert h.answer(h.run_cli("generate")[1])["ran"] is False
    stamp = os.path.join(h.root(), "results", analyzer.RUN_STAMP_FILE)
    before = os.stat(stamp).st_mtime_ns
    code, lines = h.run_cli("generate", "--force")
    assert code == 0 and h.answer(lines)["ran"] is True and os.stat(stamp).st_mtime_ns != before
