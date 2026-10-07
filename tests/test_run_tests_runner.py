"""run_tests.py: the default run is unchanged, and --all runs every suite at the same time.

`python run_tests.py` has always meant "the core suite, verbose" — twenty-odd docs and specs say so,
Pre-build_check.md among them — so the default must stay exactly what it was. `--all` starts the core
suite and every module suite as separate processes at once and reports them together
(docs/agent instructions/Parallel_Test_Runner_Spec.md). No real pytest is started here: the suite
runs are faked, so this file costs milliseconds.
"""
import json
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



# --- The core suite in shards (--all) ------------------------------------------------------------
def _core(root, sizes):
    """tests/ holding test files of the given sizes (bytes), plus a helper that is no test file."""
    for rel, size in sizes.items():
        path = os.path.join(root, "tests", *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#" * size)
    with open(os.path.join(root, "tests", "conftest.py"), "w", encoding="utf-8") as f:
        f.write("")


def test_core_files_are_every_test_file_under_tests_in_path_order(tmp_path):
    _core(str(tmp_path), {"test_b.py": 10, "test_a.py": 10, "connect/test_inbox.py": 10, "helpers.py": 10})
    assert run_tests._core_files(str(tmp_path)) == ["tests/connect/test_inbox.py", "tests/test_a.py",
                                                    "tests/test_b.py"]


@pytest.mark.parametrize("free_mb, cpus, shards", [
    (24000, 24, 8),     # a quiet machine: as many as SHARD_MAX
    (24000, 4, 4),      # never more than the CPUs
    (12000, 24, 8),     # 4.8 GB + 8 × 0.5 GB fits in 12 GB less the reserve
    (10000, 24, 5),     # two other runs going: fewer (4.8 GB + 4 × 0.5 GB fits in 7 GB)
    (6000, 24, 1),      # no room: one shard (the suite unsplit)
    (None, 24, 4),      # memory unreadable: half the CPUs, at most 4
])
def test_the_shard_count_follows_the_free_memory(monkeypatch, free_mb, cpus, shards):
    monkeypatch.delenv("SURASURA_TEST_SHARDS", raising=False)
    assert run_tests._shard_count(free_mb, cpus) == shards


def test_the_shard_count_can_be_chosen(monkeypatch):
    """SURASURA_TEST_SHARDS=1 runs the core suite unsplit, as before (the split's proof compares the two)."""
    monkeypatch.setenv("SURASURA_TEST_SHARDS", "1")
    assert run_tests._shard_count(24000, 24) == 1
    monkeypatch.setenv("SURASURA_TEST_SHARDS", "3")
    assert run_tests._shard_count(1000, 2) == 3


def test_shards_are_packed_by_the_recorded_times_each_file_once(tmp_path):
    """Longest first into the lightest shard: 60 s | 50 s | 10 s, and a file with no record weighs its size (50 KB ~
    5 s), so a new file joins the lightest shard."""
    _core(str(tmp_path), {"test_store.py": 10, "test_plan.py": 10, "test_kana.py": 10, "test_new.py": 50000})
    os.makedirs(os.path.join(str(tmp_path), "debug"))
    with open(os.path.join(str(tmp_path), "debug", "test_times.json"), "w", encoding="utf-8") as f:
        json.dump({"tests/test_store.py": 60, "tests/test_plan.py": 50, "tests/test_kana.py": 10}, f)
    files = run_tests._core_files(str(tmp_path))
    shards = run_tests._shards(str(tmp_path), files, 3)
    assert sorted(sum(shards, [])) == sorted(files), "every file in exactly one shard"
    assert ["tests/test_store.py"] in shards and ["tests/test_plan.py"] in shards
    assert ["tests/test_kana.py", "tests/test_new.py"] in shards, "the new file joins the lightest, in path order"


def test_shard_times_are_merged_into_the_record(tmp_path):
    root = str(tmp_path)
    for i, part in enumerate([{"tests/test_a.py": 1.5}, {"tests/test_b.py": 2.25}]):
        with open(os.path.join(root, f"{i}.json"), "w", encoding="utf-8") as f:
            json.dump(part, f)
    run_tests._save_times(root, [os.path.join(root, "0.json"), os.path.join(root, "1.json"),
                                 os.path.join(root, "missing.json")])
    assert run_tests._read_times(root) == {"tests/test_a.py": 1.5, "tests/test_b.py": 2.25}


def test_the_core_suite_runs_in_shards_beside_the_module_suites(tmp_path, monkeypatch, capsys):
    """Every shard and every module suite run at the same time; the summary still counts suites (core + modules), so
    'ALL 2 SUITES PASSED' reads as it always has."""
    root = str(tmp_path)
    _layout(root, {"junban": True})
    _core(root, {"test_a.py": 10, "test_b.py": 10, "test_c.py": 10})
    monkeypatch.setattr(run_tests, "_shard_count", lambda free_mb, cpus: 3)
    barrier = threading.Barrier(4, timeout=10)
    seen = []

    def fake_shard(project_root, label, files, times_path):
        barrier.wait()
        seen.append(files)
        return label, 0, f"= {len(files)} passed in 0.1s =\n", 0.1

    def fake_suite(project_root, suite):
        barrier.wait()
        return suite, 0, "= 3 passed in 0.1s =\n", 0.1

    monkeypatch.setattr(run_tests, "_run_shard", fake_shard)
    monkeypatch.setattr(run_tests, "_run_suite", fake_suite)

    assert run_tests.run_all(root) == 0
    out = capsys.readouterr().out
    assert sorted(sum(seen, [])) == ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    assert "the core suite in 3 shards" in out and "PASS  tests [2/3]" in out
    assert "[PASS]  ALL 2 SUITES PASSED" in out


def test_a_failing_shard_fails_the_core_suite_and_prints_its_output(tmp_path, monkeypatch, capsys):
    root = str(tmp_path)
    _core(root, {"test_a.py": 10, "test_b.py": 10})
    monkeypatch.setattr(run_tests, "_shard_count", lambda free_mb, cpus: 2)

    def fake_shard(project_root, label, files, times_path):
        if files == ["tests/test_b.py"]:
            return label, 1, "F\nE   AssertionError: 上層部 was read as 上層 + 部\n= 1 failed in 0.1s =\n", 0.1
        return label, 0, "= 1 passed in 0.1s =\n", 0.1

    monkeypatch.setattr(run_tests, "_run_shard", fake_shard)
    monkeypatch.setattr(run_tests, "_shards", lambda project_root, files, count: [["tests/test_a.py"],
                                                                                  ["tests/test_b.py"]])
    assert run_tests.run_all(root) == 1
    out = capsys.readouterr().out
    assert "FAILED: tests [2/2]" in out and "上層部 was read as 上層 + 部" in out
    assert "[FAIL]  1 OF 1 SUITES FAILED: tests" in out


def test_a_shard_records_its_file_times_through_the_conftest(tmp_path):
    """The real hook, in a real pytest run: SURASURA_TEST_TIMES gets each file's time, keyed as pytest names it."""
    times = tmp_path / "times.json"
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    env = dict(os.environ, SURASURA_TEST_TIMES=str(times))
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/test_run_tests_runner.py", "-q",
                             "-p", "no:cacheprovider", "-k", "core_files_are_every_test_file"],
                            cwd=root, env=env, capture_output=True)
    assert result.returncode == 0, result.stdout.decode("utf-8", "replace")
    recorded = json.loads(times.read_text(encoding="utf-8"))
    assert list(recorded) == ["tests/test_run_tests_runner.py"] and recorded["tests/test_run_tests_runner.py"] > 0
