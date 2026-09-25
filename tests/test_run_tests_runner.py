"""run_tests.py: the default run is unchanged, and --all runs every suite at the same time.

`python run_tests.py` has always meant "the core suite, verbose" — twenty-odd docs and specs say so,
Pre-build_check.md among them — so the default must stay exactly what it was. `--all` starts the core
suite and every module suite as separate processes at once and reports them together
(docs/agent instructions/Parallel_Test_Runner_Spec.md). No real pytest is started here: the suite
runs are faked, so this file costs milliseconds.
"""
import os
import sys
import locale
import subprocess
import threading
import pytest

import run_tests


def _layout(root, modules):
    """A fake checkout: tests/, plus modules/<name>/ with a tests/ dir only where asked."""
    os.makedirs(os.path.join(root, "tests"))
    for name, has_tests in modules.items():
        os.makedirs(os.path.join(root, "modules", name, "tests" if has_tests else ""), exist_ok=True)


# --- The default run ------------------------------------------------------------------------------
def test_default_run_is_unchanged(monkeypatch):
    """No flag: exactly `pytest tests -v -ra`, the caller's cwd, output straight to the console."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, 3)

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_tests.py"])
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()

    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    assert seen["cmd"] == [sys.executable, "-m", "pytest", os.path.join(root, "tests"), "-v", "-ra"]
    assert set(seen["kwargs"]) == {"env"}, "no cwd and no capture, as before"
    assert exit_info.value.code == 3, "pytest's exit code is passed on"


# --- Which suites --all runs ----------------------------------------------------------------------
def test_suites_are_core_first_then_each_module_suite_on_disk(tmp_path):
    _layout(str(tmp_path), {"youtube_downloader": True, "immersion_architect": True, "koe": False})
    assert run_tests._suites(str(tmp_path)) == [
        "tests", "modules/immersion_architect/tests", "modules/youtube_downloader/tests"]


def test_a_checkout_without_modules_runs_the_core_suite_only(tmp_path):
    """The open-source checkout has no modules/ at all."""
    _layout(str(tmp_path), {})
    assert run_tests._suites(str(tmp_path)) == ["tests"]


def test_each_suite_is_its_own_pytest_process_from_the_project_root(tmp_path, monkeypatch):
    """The documented module command, from the root (the satoru suite has no conftest), with the
    shared pytest cache off and the environment passed through unchanged."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=b"= 3 passed in 0.1s =\n")

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    suite, code, output, _secs = run_tests._run_suite(str(tmp_path), "modules/koe/tests")

    assert seen["cmd"] == [sys.executable, "-m", "pytest", "modules/koe/tests", "-ra",
                           "-p", "no:cacheprovider"]
    assert seen["kwargs"]["cwd"] == str(tmp_path)
    assert seen["kwargs"]["env"] == dict(os.environ)
    assert (suite, code) == ("modules/koe/tests", 0)
    assert run_tests._last_line(output) == "3 passed in 0.1s"


# --- Running them ---------------------------------------------------------------------------------
def test_every_suite_runs_at_the_same_time(tmp_path, monkeypatch, capsys):
    """The barrier only opens once all three suites are running together. A one-at-a-time runner
    fails here by timing out, with no speed threshold that could flake on a busy machine."""
    _layout(str(tmp_path), {"junban": True, "koe": True})
    barrier = threading.Barrier(3, timeout=10)

    def fake_suite(project_root, suite):
        barrier.wait()
        return suite, 0, "= 3 passed in 0.1s =\n", 0.1

    monkeypatch.setattr(run_tests, "_run_suite", fake_suite)

    assert run_tests.run_all(str(tmp_path)) == 0
    assert "[PASS]  ALL 3 SUITES PASSED" in capsys.readouterr().out


def test_a_failing_suite_fails_the_run_and_prints_its_output(tmp_path, monkeypatch, capsys):
    """One red suite turns the whole run red and shows its full output; a green suite shows only
    its summary line."""
    _layout(str(tmp_path), {"junban": True})
    outputs = {
        "tests": "......\n= 6 passed in 0.2s =\n",
        "modules/junban/tests": "F\nE   AssertionError: 辿り着く was not placed\n= 1 failed in 0.1s =\n",
    }

    def fake_suite(project_root, suite):
        return suite, (1 if "junban" in suite else 0), outputs[suite], 0.1

    monkeypatch.setattr(run_tests, "_run_suite", fake_suite)

    assert run_tests.run_all(str(tmp_path)) == 1
    out = capsys.readouterr().out
    assert "PASS  tests" in out and "6 passed in 0.2s" in out
    assert "FAIL  modules/junban/tests" in out
    assert "AssertionError: 辿り着く was not placed" in out
    assert "......" not in out, "a passing suite's progress output stays out of the way"
    assert "[FAIL]  1 OF 2 SUITES FAILED: modules/junban/tests" in out


def test_main_with_all_exits_with_the_runs_result(monkeypatch):
    monkeypatch.setattr(run_tests, "run_all", lambda project_root: 1)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", "--all"])
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()
    assert exit_info.value.code == 1


# --- Reading a suite's output ---------------------------------------------------------------------
def test_output_is_decoded_the_way_the_child_wrote_it(monkeypatch):
    """The children inherit our environment, so they write in PYTHONIOENCODING if it is set, else
    in the locale's encoding. Decoding is display-only and never raises."""
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    assert run_tests._decode("辿り着く — 1 failed".encode("utf-8")) == "辿り着く — 1 failed"

    monkeypatch.setenv("PYTHONIOENCODING", "no-such-codec")
    assert run_tests._decode("辿り着く".encode("utf-8")) == "辿り着く", "an unknown codec falls back"

    monkeypatch.delenv("PYTHONIOENCODING")
    text = "1227 passed — 2 skipped"
    raw = text.encode(locale.getpreferredencoding(False), errors="replace")
    assert run_tests._decode(raw) == raw.decode(locale.getpreferredencoding(False))
