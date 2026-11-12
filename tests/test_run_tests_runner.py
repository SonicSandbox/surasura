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
    """The documented module command, from the root (each module conftest imports tests.harness_guards), with the
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


@pytest.mark.parametrize("idle, shards", [
    (23.5, 8),          # a quiet machine: memory decides
    (11.0, 5),          # another run going: half the idle CPUs
    (1.2, 1),           # two other runs filling the machine: unsplit
    (None, 8),          # idle time unreadable: memory decides
])
def test_the_shard_count_follows_the_idle_cpus(monkeypatch, idle, shards):
    """Three runs started together all see the memory free; the CPUs busy with runs already going are what the later
    one sees first (three runs of 8 shards each were ~39 processes on 24 CPUs)."""
    monkeypatch.delenv("SURASURA_TEST_SHARDS", raising=False)
    assert run_tests._shard_count(24000, 24, idle) == shards


def test_the_idle_cpus_are_read_from_this_machine():
    """A real reading: some share of the CPUs, never more than there are."""
    idle = run_tests._idle_cpus(4, seconds=0.05)
    assert idle is None or 0 <= idle <= 4


def test_the_shard_count_can_be_chosen(monkeypatch):
    """SURASURA_TEST_SHARDS=1 runs the core suite unsplit, as before (the split's proof compares the two)."""
    monkeypatch.setenv("SURASURA_TEST_SHARDS", "1")
    assert run_tests._shard_count(24000, 24) == 1
    monkeypatch.setenv("SURASURA_TEST_SHARDS", "3")
    assert run_tests._shard_count(1000, 2, 0.5) == 3


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
    monkeypatch.setattr(run_tests, "_shard_count", lambda free_mb, cpus, idle: 3)
    monkeypatch.setattr(run_tests, "_idle_cpus", lambda cpus: None)
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
    monkeypatch.setattr(run_tests, "_shard_count", lambda free_mb, cpus, idle: 2)
    monkeypatch.setattr(run_tests, "_idle_cpus", lambda cpus: None)

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


@pytest.mark.parametrize("pytest_code, code", [(5, 0), (1, 1), (0, 0)])
def test_a_shard_of_files_without_tests_passes(tmp_path, monkeypatch, pytest_code, code):
    """A helper named test_*.py holds no tests: alone in a shard, pytest says 5 ("no tests collected"), not a failure."""
    monkeypatch.setattr(run_tests.subprocess, "run",
                        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, pytest_code, stdout=b"= no tests ran =\n"))
    assert run_tests._run_shard(str(tmp_path), "tests [1/2]", ["tests/test_support.py"], "t.json")[1] == code


# --- One shard of the core suite (--shard I/N, GitHub's PR tests) ----------------------------------
# pr.yml runs the core suite as N jobs side by side, each under the runner's 30-minute cap (3.0-dev's single run had
# reached 25-28 min); the merge gate reads one "tests" job that passes only if every shard did. So the split must hold
# every core file exactly once, the same on every job, and a shard's result must be pytest's.
def test_the_shards_of_a_split_hold_every_core_file_exactly_once(tmp_path):
    """No times recorded (a fresh GitHub checkout): packed by size, nested folders included, and the same split twice."""
    root = str(tmp_path)
    _core(root, {"test_store.py": 9000, "test_plan.py": 4000, "connect/test_inbox.py": 3000, "qt/test_window.py": 500,
                 "test_kana.py": 200, "helpers.py": 50000})
    shards = [run_tests._shard_of(root, f"{i}/3") for i in (1, 2, 3)]
    assert sorted(sum(shards, [])) == run_tests._core_files(root), "every core file in exactly one shard"
    assert all(shards) and all(shard == sorted(shard) for shard in shards)
    assert shards == [run_tests._shard_of(root, f"{i}/3") for i in (1, 2, 3)], "every job packs it the same way"


def test_this_checkout_splits_into_four_shards_holding_every_test_file():
    """The real tests/ folder, as pr.yml splits it. pytest also collects *_test.py by default: none may exist here,
    or the shards (test_*.py only) would skip it where `pytest tests` ran it."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    files = run_tests._core_files(root)
    shards = [run_tests._shard_of(root, f"{i}/4") for i in (1, 2, 3, 4)]
    assert sorted(sum(shards, [])) == files and all(shards)
    stray = [os.path.join(d, n) for d, _, names in os.walk(os.path.join(root, "tests"))
             for n in names if n.endswith("_test.py") and "__pycache__" not in d]
    assert stray == []


def test_more_shards_than_files_leaves_the_extra_shards_empty(tmp_path):
    _core(str(tmp_path), {"test_a.py": 10, "test_b.py": 10})
    assert [run_tests._shard_of(str(tmp_path), f"{i}/3") for i in (1, 2, 3)] == [
        ["tests/test_a.py"], ["tests/test_b.py"], []]


def test_an_empty_shard_passes_without_starting_pytest(tmp_path, monkeypatch):
    """A job whose shard holds no files has nothing to fail: it passes, and starts no pytest (given no files, pytest
    would collect the whole folder it starts in)."""
    _core(str(tmp_path), {"test_a.py": 10})
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **kwargs: pytest.fail("no pytest for an empty shard"))
    assert run_tests.run_shard(str(tmp_path), "2/2") == 0


@pytest.mark.parametrize("pytest_code, code", [(0, 0), (1, 1), (5, 5)])
@pytest.mark.parametrize("flag", [["--shard", "2/4"], ["--shard=2/4"]])
def test_main_with_shard_runs_that_shards_files_verbose_from_the_root(monkeypatch, pytest_code, code, flag):
    """`--shard 2/4`: one pytest process over shard 2's files, from the project root (the paths are relative to it),
    verbose like the default run, its exit code passed on — 5 (nothing collected) fails, as `pytest tests` did."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, pytest_code)

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", *flag])
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()
    assert seen["cmd"] == [sys.executable, "-m", "pytest", *run_tests._shard_of(root, "2/4"), "-v", "-ra"]
    assert seen["kwargs"]["cwd"] == root
    assert exit_info.value.code == code


@pytest.mark.parametrize("argv", [["--shard", "0/4"], ["--shard", "5/4"], ["--shard", "a/4"], ["--shard", "4"],
                                  ["--shard", "1/2/3"], ["--shard"]])
def test_a_bad_shard_runs_nothing_and_fails(monkeypatch, capsys, argv):
    """A typo in the workflow must fail its job, never pass it by running no tests."""
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **kwargs: pytest.fail("no pytest for a bad shard"))
    monkeypatch.setattr(sys, "argv", ["run_tests.py", *argv])
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()
    assert exit_info.value.code == 2
    assert "--shard takes I/N" in capsys.readouterr().out


def test_a_checkout_with_no_core_test_files_fails_every_shard(tmp_path, monkeypatch, capsys):
    """A wrong root or an empty checkout must not pass four green shards: `pytest tests` failed there too."""
    os.makedirs(os.path.join(str(tmp_path), "tests"))
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **kwargs: pytest.fail("nothing to run"))
    assert run_tests.run_shard(str(tmp_path), "1/4") == 2
    assert "No core test files" in capsys.readouterr().out


def test_pr_yml_runs_every_shard_once_and_one_tests_job_reads_them_all():
    """pr.yml's matrix is one list, 1..N in order, and each job passes `<its shard>/<the job count>`: a repeated or
    missing number, or a second matrix dimension (job-total would double), would drop files and still pass. The
    `tests` job (the branch's required check, the job pr-merge.yml reads) runs after the shards even when the run is
    cancelled (always()), so a cancelled run is never a skipped, green `tests`. Read as text: no YAML parser here."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    with open(os.path.join(root, ".github", "workflows", "pr.yml"), encoding="utf-8") as f:
        text = f.read()
    shards = text.split("\n  shards:\n", 1)[1].split("\n  tests:\n", 1)[0]
    matrix = shards.split("matrix:\n", 1)[1].split("\n    steps:", 1)[0]
    lines = [line.strip() for line in matrix.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert len(lines) == 1 and lines[0].startswith("shard: ["), "one matrix dimension: the shard"
    numbers = [int(n) for n in lines[0].split("[", 1)[1].split("]", 1)[0].split(",")]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 2
    assert "run: python run_tests.py --shard ${{ matrix.shard }}/${{ strategy.job-total }}" in shards
    assert "fail-fast: false" in shards
    tests = text.split("\n  tests:\n", 1)[1].split("\n  unreview:\n", 1)[0]
    assert "needs: [changes, shards]" in tests
    assert "if: ${{ always() && needs.changes.outputs.code != 'false' }}" in tests
    assert 'test "$SHARDS" = success' in tests and "SHARDS: ${{ needs.shards.result }}" in tests


@pytest.mark.parametrize("code, words", [(3221225477, "exit 0xC0000005, an access violation"),
                                         (3221226505, "exit 0xC0000409, a fail-fast"), (3221225786, "exit 0xC000013A"),
                                         (3, "exit 3: abort()")])
def test_a_shard_whose_pytest_died_says_so_in_hex_never_only_127(tmp_path, monkeypatch, capsys, code, words):
    """GitHub's bash shows a pytest process that died by a Windows status as 127, which names nothing (#285's core
    4/4, flakes-2026-11-05 #5): the shard says how it died, and its exit code is still the child's (red)."""
    _core(str(tmp_path), {"test_a.py": 10})
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, code))
    assert run_tests.run_shard(str(tmp_path), "1/1") == code
    assert words in capsys.readouterr().out


@pytest.mark.parametrize("code", [0, 1, 2, 4, 5, 75, 127, 255, -11])
def test_pytests_own_exit_codes_are_no_death(code):
    assert run_tests.death(code) is None


# --- --stress, --stress-changed (tests/FLAKES.md) ----------------------------------------------------------------- #
def test_the_stress_set_is_never_a_core_file_nor_collected_by_a_plain_run(tmp_path):
    """tests/stress/ is opt-in: no shard (--all, GitHub's) holds its files; a folder of that name deeper down does."""
    _core(str(tmp_path), {"test_a.py": 10, "stress/test_stress_store.py": 10, "qt/stress/test_x.py": 10})
    assert run_tests._core_files(str(tmp_path)) == ["tests/qt/stress/test_x.py", "tests/test_a.py"]
    with open(os.path.join(os.path.dirname(os.path.abspath(run_tests.__file__)), "tests", "conftest.py"),
              encoding="utf-8") as f:
        assert 'collect_ignore = [] if os.environ.get("SURASURA_STRESS") else ["stress"]' in f.read()


def test_stress_runs_the_stress_set_n_times_with_its_switch_and_stops_at_the_first_red(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs["env"].get("SURASURA_STRESS")))
        return subprocess.CompletedProcess(cmd, 1 if len(calls) == 2 else 0, stdout=b"1 failed in 2.0s")
    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    assert run_tests.run_stress("root", 5) == 1
    assert len(calls) == 2, "stopped at the first red"
    assert all(cmd[3] == os.path.join("tests", "stress") and on == "1" for cmd, on in calls)
    assert "run 2" in capsys.readouterr().out


@pytest.mark.parametrize("argv, times", [(["run_tests.py", "--stress"], 1), (["run_tests.py", "--stress", "20"], 20),
                                         (["run_tests.py", "--stress=3"], 3)])
def test_main_with_stress_takes_its_count(monkeypatch, argv, times):
    seen = []
    monkeypatch.setattr(run_tests, "run_stress", lambda root, n: seen.append(n) or 0)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()
    assert seen == [times] and exit_info.value.code == 0


@pytest.mark.parametrize("argv, base", [(["run_tests.py", "--stress-changed"], "origin/3.0-dev"),
                                        (["run_tests.py", "--stress-changed", "origin/2.x-dev"], "origin/2.x-dev")])
def test_main_with_stress_changed_takes_its_base(monkeypatch, argv, base):
    seen = []
    monkeypatch.setattr(run_tests, "run_stress_changed", lambda root, b: seen.append(b) or 0)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        run_tests.main()
    assert seen == [base]


def test_the_changed_test_files_are_the_branchs_and_the_uncommitted_ones_still_on_disk(tmp_path, monkeypatch):
    _core(str(tmp_path), {"test_a.py": 10, "qt/test_b.py": 10})
    os.makedirs(tmp_path / "modules" / "junban" / "tests")
    (tmp_path / "modules" / "junban" / "tests" / "test_c.py").write_text("", encoding="utf-8")
    answers = {("diff", "--name-only", "base...HEAD"): "tests/test_a.py\napp/sources.py\ntests/test_gone.py\n"
                                                         "modules/junban/tests/test_c.py\ntests/helpers.py\n",
               ("diff", "--name-only", "HEAD"): "tests/qt/test_b.py\n"}
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 0, stdout=answers[tuple(cmd[1:])].encode()))
    assert run_tests._changed_test_files(str(tmp_path), "base") == [
        "modules/junban/tests/test_c.py", "tests/qt/test_b.py", "tests/test_a.py"]
    assert [run_tests._suite_of(p) for p in run_tests._changed_test_files(str(tmp_path), "base")] == [
        "modules/junban/tests", "tests", "tests"]


def test_stress_changed_repeats_each_suites_tests_in_its_own_process_beside_two_load_shards(monkeypatch, capsys):
    monkeypatch.setattr(run_tests, "_changed_tests", lambda root, base: ([
        "modules/junban/tests/test_c.py::test_one", "tests/qt/test_b.py::TestB::test_two", "tests/test_a.py::test_three"],
        []))
    loads, runs, lock = [], [], threading.Lock()

    class Load:
        def __init__(self, cmd, **kwargs):
            with lock:
                loads.append(cmd[2:])
            self.pid = 0

        def poll(self):
            return None
    ended = []
    monkeypatch.setattr(run_tests.subprocess, "Popen", Load)
    monkeypatch.setattr(run_tests, "_end_tree", lambda proc: ended.append(proc))
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **k: runs.append(cmd[3:-4]) or
                        subprocess.CompletedProcess(cmd, 0, stdout=b"3 passed in 1.0s"))
    assert run_tests.run_stress_changed("root", "base", times=3) == 0
    assert runs == [["modules/junban/tests/test_c.py::test_one"],
                    ["tests/qt/test_b.py::TestB::test_two", "tests/test_a.py::test_three"]] * 3
    assert sorted(loads) == [["--shard", "1/4"], ["--shard", "3/4"]] and len(ended) == 2, "the load ended with them"
    assert "passed 3 times under load" in capsys.readouterr().out


def test_stress_changed_with_no_changed_test_passes_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(run_tests, "_changed_tests", lambda root, base: ([], ["tests/test_a.py: no test changed"]))
    assert run_tests.run_stress_changed("root", "base") == 0
    out = capsys.readouterr().out
    assert "No test changed" in out and "tests/test_a.py: no test changed" in out


def test_stress_changed_splits_a_suites_tests_where_one_command_would_be_too_long(monkeypatch):
    """Windows' command line holds 32,767 characters: hundreds of node ids go in more than one process per run."""
    ids = [f"tests/test_a.py::test_{n:03d}_a_long_descriptive_name_as_this_repo_writes_them" for n in range(6)]
    monkeypatch.setattr(run_tests, "_changed_tests", lambda root, base: (ids, []))
    monkeypatch.setattr(run_tests, "ARGS_MAX", 200)
    monkeypatch.setattr(run_tests.subprocess, "Popen", lambda cmd, **k: type("P", (), {"poll": lambda self: None})())
    monkeypatch.setattr(run_tests, "_end_tree", lambda proc: None)
    runs = []
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **k: runs.append(cmd[3:-4]) or
                        subprocess.CompletedProcess(cmd, 0, stdout=b"3 passed"))
    assert run_tests.run_stress_changed("root", "base", times=1) == 0
    assert [n for run in runs for n in run] == ids and len(runs) > 1
    assert all(sum(len(n) + 1 for n in run) <= 200 for run in runs)


# The changed tests by function (Tool-T, 2026-11-12): a lane's gate held a slot for hours when one edited line of a
# 300-test file repeated all 300 tests 20 times.
_TESTS_FILE = """import pytest
from app import sources

BUDGET = 0.05


def _seed(store):
    return store.add("いつか見た景色")


def _seeded(store):
    return _seed(store)


@pytest.fixture
def store(tmp_path):
    return tmp_path


def test_unchanged_reads_a_line():
    assert "雨が降る" != "雪が降る"


def test_edited_body():
    assert sources.scan is not None


@pytest.mark.parametrize("n", [1, 2])
def test_with_a_changed_decorator(n):
    assert n


def test_uses_the_changed_helper_through_another(store):
    assert _seeded(store)


def test_uses_the_changed_budget():
    assert BUDGET < 1


def test_uses_the_changed_app_function():
    assert sources.look_again


class _Shelf:
    def count(self):
        return 3


def test_counts_with_the_changed_helper_class():
    assert _Shelf().count() == 3


def test_counts_a_list_never_the_helper_classs_method():
    assert ["本", "棚"].count("本") == 1


class TestShelf:
    def setup_method(self):
        self.shelf = []

    def test_one(self):
        assert self.shelf == []

    def test_two(self):
        assert not self.shelf


class TestOther:
    def test_three(self):
        assert True
"""


def _line_of(text, needle):
    return text.splitlines().index(needle) + 1


def test_the_changed_tests_are_by_function_never_the_whole_file(tmp_path, monkeypatch):
    """Edited, added or decorated tests; tests that use a changed helper (also through another helper), helper class,
    fixture or constant of their file, or a function the branch changed in the app; every test of a class whose own
    fixture changed — and nothing else of the file (a helper class's changed method counts as the class: `.count` on
    a list is not `_Shelf.count`)."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_shelf.py").write_text(_TESTS_FILE, encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "sources.py").write_text("def scan():\n    return 1\n\n\ndef look_again():\n    return 2\n",
                                                 encoding="utf-8")
    t = _TESTS_FILE
    changed = {_line_of(t, "def test_edited_body():"), _line_of(t, '@pytest.mark.parametrize("n", [1, 2])'),
               _line_of(t, "def _seed(store):"), _line_of(t, "BUDGET = 0.05"),
               _line_of(t, "    def setup_method(self):"), _line_of(t, "        return 3")}
    monkeypatch.setattr(run_tests, "_changed_lines", lambda root, base: {
        "tests/test_shelf.py": changed, "app/sources.py": {5}})
    monkeypatch.setattr(run_tests, "_changed_test_files", lambda root, base: ["tests/test_shelf.py"])
    ids, notes = run_tests._changed_tests(str(tmp_path), "base")
    assert ids == ["tests/test_shelf.py::" + n for n in (
        "test_edited_body", "test_with_a_changed_decorator", "test_uses_the_changed_helper_through_another",
        "test_uses_the_changed_budget", "test_uses_the_changed_app_function",
        "test_counts_with_the_changed_helper_class", "TestShelf::test_one",
        "TestShelf::test_two")] and notes == []


def test_a_test_file_changed_only_outside_its_tests_picks_none_and_says_so(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_shelf.py").write_text(_TESTS_FILE, encoding="utf-8")
    monkeypatch.setattr(run_tests, "_changed_lines", lambda root, base: {"tests/test_shelf.py": {1, 2}})   # imports
    monkeypatch.setattr(run_tests, "_changed_test_files", lambda root, base: ["tests/test_shelf.py"])
    ids, notes = run_tests._changed_tests(str(tmp_path), "base")
    assert ids == [] and notes == ["tests/test_shelf.py: no test changed (its changed lines are outside every test "
                                   "and helper)"]


def test_a_test_file_that_doesnt_parse_goes_whole(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_half.py").write_text("def test_a(:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(run_tests, "_changed_lines", lambda root, base: {"tests/test_half.py": {1}})
    monkeypatch.setattr(run_tests, "_changed_test_files", lambda root, base: ["tests/test_half.py"])
    assert run_tests._changed_tests(str(tmp_path), "base") == (["tests/test_half.py"],
                                                               ["tests/test_half.py: doesn't parse, run whole"])


def _git(root, *args):
    subprocess.run(["git", "-c", "user.name=Tool-T", "-c", "user.email=tool-t@example.invalid", *args], cwd=root,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_the_changed_tests_come_from_gits_diff_committed_and_not_yet(tmp_path):
    """A real repository: the base's file, one test edited in a commit on the branch, one added and not committed, one
    deleted line inside a third, a CRLF file and a Japanese line among them — each changed test once, no other."""
    root = str(tmp_path)
    _git(root, "init", "-q", "-b", "base")
    _git(root, "config", "core.autocrlf", "true")                              # (as every copy here)
    (tmp_path / "tests").mkdir()
    head = "import time\n\n\n"
    tests = ["def test_a():\n    assert '猫' != '犬'\n", "def test_b():\n    x = 1\n    y = 2\n    assert x < 3\n",
             "def test_c():\n    assert True\n"]
    (tmp_path / "tests" / "test_x.py").write_bytes((head + "\n\n".join(tests)).encode("utf-8"))
    (tmp_path / "tests" / "test_crlf.py").write_bytes(b"def test_d():\r\n    assert 1\r\n\r\n\r\ndef test_e():\r\n"
                                                      b"    assert 2\r\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "lane")
    tests[0] = "def test_a():\n    assert '猫' != '鳥'\n"                          # edited, committed
    tests[1] = "def test_b():\n    x = 1\n    assert x < 3\n"                    # a line deleted, committed
    (tmp_path / "tests" / "test_x.py").write_bytes((head + "\n\n".join(tests)).encode("utf-8"))
    _git(root, "commit", "-q", "-am", "lane")
    (tmp_path / "tests" / "test_crlf.py").write_bytes(b"def test_d():\r\n    assert 1\r\n\r\n\r\ndef test_e():\r\n"
                                                      b"    assert 2\r\n\r\n\r\ndef test_f():\r\n    assert 3\r\n")
    ids, notes = run_tests._changed_tests(root, "base")
    assert ids == ["tests/test_crlf.py::test_f", "tests/test_x.py::test_a", "tests/test_x.py::test_b"], (ids, notes)
