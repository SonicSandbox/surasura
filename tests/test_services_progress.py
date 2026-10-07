"""PROGRESS: the analyzer's `--progress-json` lines and their reader (`app/services/progress.py`) — W1.3, the window's
spec 04 §4.2 and §4.4 gap 8; the line shapes are P0.3's (02-contract §2).

What a wrong answer would cost:
  * a different list — the flag must change stdout only: every output byte-identical with and without it, and the run
    signature the same (else every window's Generate is a new analysis);
  * a bar that lies — steps out of order, `done` past `total`, or the final line not last;
  * a window that stutters — one update per printed line instead of at most one per 100 ms;
  * a stuck bar — the newest step held back while the run goes quiet, or no final line on the skip or the busy exit.

Real Japanese and Chinese files, the real analyzer as a child, each under the test's own root.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from app import analyzer
from app.services import progress
from tests import services_helpers as h


# --- the reader ------------------------------------------------------------------------------------------------- #
def test_parse_tells_the_protocol_from_the_analyzers_text():
    assert progress.parse('{"type": "progress", "step": "Counting words", "done": null, "total": null}\n') == \
        ("progress", progress.Update("Counting words", None, None))
    assert progress.parse('{"type": "result", "contract": 1, "ok": true, "ran": true}')[0] == "result"
    assert progress.parse('{"type": "error", "contract": 1, "ok": false, "code": "busy"}')[0] == "error"
    assert progress.parse("Processing 第01話.srt...\n") == ("text", "Processing 第01話.srt...")
    assert progress.parse('{"type": broken') == ("text", '{"type": broken')
    assert progress.parse('{"word": "x"}') == ("text", '{"word": "x"}')


def test_a_thousand_lines_in_50_ms_make_at_most_two_updates_and_the_last_one_arrives():
    """The window repaints per update: a burst is one at once and the newest once the 100 ms are up."""
    got = []
    c = progress.Coalescer(got.append, interval=0.1)
    start = time.monotonic()
    for n in range(1000):
        c.feed(json.dumps({"type": "progress", "step": "Reading your files", "done": n + 1, "total": 1000}))
    assert time.monotonic() - start < 0.1
    assert len(got) == 1
    assert h.until(lambda: len(got) == 2, seconds=2)
    time.sleep(0.25)
    assert len(got) == 2 and got[-1] == progress.Update("Reading your files", 1000, 1000)


def test_the_final_line_comes_after_a_held_update_and_only_once():
    events = []
    c = progress.Coalescer(lambda u: events.append(("update", u.done)), on_final=lambda k, r: events.append((k,)),
                           interval=10)
    c.feed('{"type": "progress", "step": "Reading your files", "done": 1, "total": 3}')
    c.feed('{"type": "progress", "step": "Reading your files", "done": 3, "total": 3}')
    c.feed('{"type": "result", "contract": 1, "ok": true, "ran": true}')
    c.end()
    assert events == [("update", 1), ("update", 3), ("result",)]
    assert c.final[0] == "result"


def test_text_lines_go_to_the_log_as_they_come():
    text = []
    c = progress.Coalescer(lambda u: None, on_text=text.append)
    progress.read(iter(["Configuration: ja\n", '{"type": "progress", "step": "Counting words"}\n', "\n",
                        "Saved priority list\n"]), c)
    assert text == ["Configuration: ja", "Saved priority list"]


# --- the analyzer's lines ---------------------------------------------------------------------------------------- #
def _analyzer(lang, *extra, env=None):
    from app import run_args, settings_manager
    argv = run_args.analyzer_args(settings_manager.load_settings(), lang)
    child_env = dict(os.environ, PYTHONPATH=h.PROJECT_ROOT)
    child_env.pop("PYTEST_CURRENT_TEST", None)
    child_env.update(env or {})
    return subprocess.run([sys.executable, os.path.join(h.PROJECT_ROOT, "app_entry.py"), "analyzer"] + argv[1:]
                          + ["--no-open"] + list(extra), cwd=h.root(), env=child_env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=900)


def _records(proc):
    out = proc.stdout.decode("utf-8", "replace").splitlines()
    return [json.loads(line) for line in out if line.startswith('{"type"')]


def _outputs():
    folder = os.path.join(h.root(), "results")
    return {name: hashlib.sha256(open(os.path.join(folder, name), "rb").read()).hexdigest()
            for name in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, name))}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_steps_come_in_order_and_the_result_line_is_last(lang):
    h.seed_library(lang)
    h.write_settings({"target_language": lang, "anki_connect_url": "http://127.0.0.1:9"})
    proc = _analyzer(lang, "--progress-json")
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-2000:]
    records = _records(proc)
    steps = [r["step"] for r in records if r["type"] == "progress"]
    order = [analyzer.PROGRESS_STEPS.index(s) for s in steps]
    assert order == sorted(order) and set(steps) == set(analyzer.PROGRESS_STEPS), steps
    files = [r for r in records if r.get("step") == "Reading your files"]
    assert files[0]["done"] == 0 and files[-1]["done"] == files[-1]["total"] == len(h.LIBRARY[lang])
    assert all(r["done"] <= r["total"] for r in files)
    assert records[-1] == {"type": "result", "contract": 1, "ok": True, "ran": True}
    assert all(line.isascii() for line in proc.stdout.decode("utf-8").splitlines() if line.startswith('{"type"'))

    again = _records(_analyzer(lang, "--progress-json"))
    assert again == [{"type": "progress", "step": "Writing the journey", "done": None, "total": None},
                     {"type": "result", "contract": 1, "ok": True, "ran": False, "skipped": "nothing changed"}], \
        "the skip path writes the sidecars (and may re-render): it says so, so a cancel waits"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_every_output_is_byte_identical_with_and_without_the_flag(lang):
    """The flag changes stdout only. Same root, same files: a forced run without it, then with it."""
    h.seed_library(lang)
    h.write_settings({"target_language": lang, "anki_connect_url": "http://127.0.0.1:9"})
    plain = _analyzer(lang, env={"SURASURA_FORCE_RUN": "1"})
    assert plain.returncode == 0
    assert not _records(plain), "without the flag the analyzer prints no protocol line"
    without = _outputs()
    flagged = _analyzer(lang, "--progress-json", env={"SURASURA_FORCE_RUN": "1"})
    assert flagged.returncode == 0
    assert _outputs() == without
    assert len(without) == 13


def test_the_flag_never_enters_the_run_signature():
    h.seed_library("ja")
    from app import run_args, settings_manager
    argv = run_args.analyzer_args(settings_manager.load_settings(), "ja")
    assert "--progress-json" not in argv
    files = analyzer.resolve_found_files("ja")
    plain = analyzer.compute_run_signature("ja", files, analyzer.parse_analysis_args(argv[1:]))
    flagged = analyzer.compute_run_signature("ja", files, analyzer.parse_analysis_args(argv[1:] + ["--progress-json"]))
    assert plain and plain == flagged


def test_the_busy_exit_ends_with_an_error_line():
    """Another program holds `results` past the wait: exit 75, nothing written, and the error line last."""
    h.seed_library("ja")
    with h.Holder("results", "Generate"):
        proc = _analyzer("ja", "--progress-json", env={"SURASURA_RESULTS_WAIT": "0"})
    assert proc.returncode == analyzer.RESULTS_BUSY
    records = _records(proc)
    assert records and records[-1]["type"] == "error" and records[-1]["code"] == "busy"
    assert [r for r in records if r["type"] == "progress"] == []



# --- the run's own cancel and its last line (tracks/window/reviews/W1.3-adversary.md #6, #7, #10) ----------------- #
def test_a_run_asked_to_stop_before_writing_stops_itself_and_writes_nothing(tmp_path):
    """The cancel file exists from the start: the run stops at its first step, answers `cancelled` (exit 76) last, and
    every output but the stamp it dropped is byte for byte the last run's."""
    h.seed_library("ja")
    h.write_settings({"target_language": "ja", "anki_connect_url": "http://127.0.0.1:9"})
    assert _analyzer("ja").returncode == 0
    before = {k: v for k, v in _outputs().items() if k != "run_signature.txt"}
    flag = tmp_path / "cancel.flag"
    flag.write_text("cancel")
    proc = _analyzer("ja", "--progress-json", env={"SURASURA_FORCE_RUN": "1", "SURASURA_CANCEL_FILE": str(flag)})
    assert proc.returncode == analyzer.GENERATE_CANCELLED
    records = _records(proc)
    assert records[-1]["type"] == "error" and records[-1]["code"] == "cancelled"
    assert [r for r in records if r["type"] == "progress"] == []
    assert {k: v for k, v in _outputs().items() if k != "run_signature.txt"} == before


def test_the_cancel_point_holds_until_writing_and_never_after(tmp_path, monkeypatch):
    flag = tmp_path / "cancel.flag"
    flag.write_text("cancel")
    monkeypatch.setitem(analyzer._PROGRESS, "on", True)
    monkeypatch.setitem(analyzer._PROGRESS, "cancel_file", str(flag))
    monkeypatch.setitem(analyzer._PROGRESS, "writing", False)
    with pytest.raises(analyzer._GenerateCancelled):
        analyzer._progress("Picking sentences")
    with pytest.raises(analyzer._GenerateCancelled):
        analyzer._cancellable(lambda path: {})("a file")
    monkeypatch.setitem(analyzer._PROGRESS, "writing", True)
    analyzer._progress("Writing the journey")              # past *Writing your list*: it finishes
    analyzer._cancel_point()


def _wrapped(run, argv, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", argv)
    try:
        code = analyzer._reporting_progress(run)()
    except BaseException as e:                              # the run's own exception, without the flag
        code = e
    return code, capsys.readouterr()


def test_a_crash_with_the_flag_ends_with_the_error_line_after_the_traceback(capsys, monkeypatch):
    def crash():
        raise RuntimeError("the tokenizer's dictionary is missing")
    code, out = _wrapped(crash, ["analyzer.py", "--progress-json"], capsys, monkeypatch)
    assert code == 1
    last = json.loads(out.out.strip().splitlines()[-1])
    assert last["type"] == "error" and last["code"] == "failed" and "dictionary is missing" in last["message"]
    assert "Traceback" in out.err


def test_without_the_flag_a_crash_goes_on_as_it_always_did_and_nothing_is_printed(capsys, monkeypatch):
    def crash():
        raise RuntimeError("boom")
    code, out = _wrapped(crash, ["analyzer.py"], capsys, monkeypatch)
    assert isinstance(code, RuntimeError) and out.out == ""


def test_each_call_starts_afresh(capsys, monkeypatch, tmp_path):
    """Tests (and a long-lived caller) run main() again and again: a flag, a cancel file or a writing mark from one call
    never reaches the next."""
    flag = tmp_path / "cancel.flag"
    flag.write_text("cancel")
    monkeypatch.setenv("SURASURA_CANCEL_FILE", str(flag))

    def writing():
        analyzer._progress("Writing your list")
    _wrapped(writing, ["analyzer.py", "--progress-json"], capsys, monkeypatch)
    monkeypatch.delenv("SURASURA_CANCEL_FILE")
    code, out = _wrapped(lambda: None, ["analyzer.py"], capsys, monkeypatch)
    assert code is None and out.out == ""
    assert analyzer._PROGRESS == {"on": False, "ran": False, "cancel_file": None, "writing": False}


def test_static_only_says_report_only(capsys, monkeypatch):
    code, out = _wrapped(lambda: None, ["analyzer.py", "--static-only", "--progress-json"], capsys, monkeypatch)
    assert json.loads(out.out.strip())["skipped"] == "report only"
