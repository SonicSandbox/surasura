"""run_tests.py: the default run is unchanged, and --all runs every suite at the same time.

`python run_tests.py` has always meant "the core suite, verbose" — twenty-odd docs and specs say so,
Pre-build_check.md among them — so the default must stay exactly what it was. `--all` starts the core
suite and every module suite as separate processes at once and reports them together
(docs/agent instructions/Parallel_Test_Runner_Spec.md). No real pytest is started here: the suite
runs are faked, so this file costs milliseconds.
"""
import ast
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
    quiet = {"creationflags", "stdin", "stdout", "stderr"}    # no console here: no window, this process's own streams
    assert set(seen["kwargs"]) - quiet == {"env"}, "no cwd and no capture, as before"
    for name in ("stdout", "stderr"):
        assert seen["kwargs"].get(name) in (None, getattr(sys, name), subprocess.DEVNULL), "never captured"
    assert exit_info.value.code == 3, "pytest's exit code is passed on"


# --- This user's packages under a redirected APPDATA (2026-11-24) ---------------------------------------------------
def _planted_user_site(tmp_path, monkeypatch):
    """A profile of the test's own (~ = it) whose user base holds one package: this user's `pip install --user`."""
    import sysconfig
    from tests import user_bases
    roaming = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    assert os.path.normcase(user_bases._roaming_folder() or roaming) == os.path.normcase(roaming), \
        "Windows' own roaming folder, asked (this PC's is not relocated)"
    monkeypatch.setattr(user_bases, "_roaming_folder", lambda: str(tmp_path / "profile" / "AppData" / "Roaming"))
    real = user_bases.real_user_base()
    assert real == str(tmp_path / "profile" / "AppData" / "Roaming" / "Python")
    site_dir = sysconfig.get_path("purelib", f"{os.name}_user", vars={"userbase": real})
    os.makedirs(site_dir)
    with open(os.path.join(site_dir, "surasura_user_site_probe.py"), "w", encoding="utf-8") as f:
        f.write("HERE = 1\n")
    monkeypatch.setenv("PYTHONUSERBASE", "")             # (set first: what main() writes is put back after)
    monkeypatch.delenv("PYTHONUSERBASE")
    monkeypatch.setenv("APPDATA", str(tmp_path / "throwaway" / "Roaming"))      # the lane's, as with-lock.sh asks
    return real


@pytest.mark.skipif(sys.platform != "win32", reason="Python finds a user's packages under %APPDATA% on Windows only")
def test_a_user_site_package_stays_importable_in_a_child_when_appdata_names_a_throwaway_folder(tmp_path, monkeypatch):
    """Why: a lane points APPDATA at its throwaway folder, and Python looks for this user's own packages under it —
    certifi was gone from three of a level-2 --all's shards, which ran nothing. The runner names the real profile's
    base for its children (PYTHONUSERBASE) unless one is set; a child then imports a package only the user base has."""
    from tests import user_bases
    real = _planted_user_site(tmp_path, monkeypatch)
    probe = [sys.executable, "-c", "import surasura_user_site_probe"]
    hidden = subprocess.run(probe, env=dict(os.environ), capture_output=True, timeout=60)
    assert hidden.returncode != 0, "the case itself: the package is hidden under the throwaway APPDATA"
    env = dict(os.environ)
    assert user_bases.keep_user_site(env) == real
    kept = subprocess.run(probe, env=env, capture_output=True, text=True, timeout=60)
    assert kept.returncode == 0, kept.stderr[-2000:]
    assert user_bases.keep_user_site(dict(env)) is None, "one set already is kept"
    assert user_bases.keep_user_site({"APPDATA": os.path.dirname(real)}) is None, "the real APPDATA needs nothing"


@pytest.mark.skipif(sys.platform != "win32", reason="Python finds a user's packages under %APPDATA% on Windows only")
def test_the_runners_child_run_gets_the_real_user_base(tmp_path, monkeypatch):
    real = _planted_user_site(tmp_path, monkeypatch)
    seen = {}
    monkeypatch.setattr(run_tests.subprocess, "run",
                        lambda cmd, **kwargs: seen.update(kwargs) or subprocess.CompletedProcess(cmd, 0))
    monkeypatch.setattr(sys, "argv", ["run_tests.py"])
    with pytest.raises(SystemExit):
        run_tests.main()
    assert seen["env"]["PYTHONUSERBASE"] == real


# --- No console windows (2026-11-21: every shard opened one and took the focus) ----------------------------------------
def test_from_a_terminal_a_child_starts_exactly_as_before(monkeypatch):
    monkeypatch.setattr(run_tests, "_has_console", lambda: True)
    assert run_tests._quiet({"env": {}}) == {"env": {}}


@pytest.mark.skipif(os.name != "nt", reason="a console window is Windows'")
def test_without_a_console_a_child_gets_no_window_and_this_processs_own_streams(monkeypatch):
    """Started from a program with no console (an AI app's shell), each child opened a console window of its own.
    It gets CREATE_NO_WINDOW and, so its output isn't lost in that windowless console, this process's own streams —
    never in place of streams the call names itself (a shard's own log, a captured run)."""
    monkeypatch.setattr(run_tests, "_has_console", lambda: False)
    got = run_tests._quiet({"env": {}})
    assert got["creationflags"] == subprocess.CREATE_NO_WINDOW and got["env"] == {}
    for name in ("stdin", "stdout", "stderr"):
        assert got[name] in (getattr(sys, name), subprocess.DEVNULL)
    named = run_tests._quiet({"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT})
    assert named["stdout"] == subprocess.PIPE and named["stderr"] == subprocess.STDOUT


@pytest.mark.skipif(os.name != "nt", reason="a console window is Windows'")
def test_a_shard_and_what_it_starts_have_no_console_window(tmp_path):
    """The real thing, from a process with no console: a child through `_popen` (as each --all shard), and a plain
    child of that one (as a test's own subprocess) — neither has a console window, and both write to our stdout."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import ctypes, subprocess, sys\n"
        "print(sys.argv[1], ctypes.windll.kernel32.GetConsoleWindow(), flush=True)\n"
        "if sys.argv[1] == 'shard':\n"
        "    subprocess.run([sys.executable, __file__, 'child'])\n", encoding="utf-8")
    parent = ("import subprocess, sys, run_tests\n"
              f"run_tests._popen([sys.executable, {str(probe)!r}, 'shard']).wait()\n")
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    # DETACHED_PROCESS: the parent has no console at all, as under an AI app's shell (TERM-POPUPS: started with
    # CREATE_NO_WINDOW it had a console, its children shared it, and the test passed without `_quiet`)
    out = subprocess.run([sys.executable, "-c", parent], cwd=root, capture_output=True, text=True, timeout=60,
                         creationflags=0x00000008)
    assert out.stdout.split() == ["shard", "0", "child", "0"], out.stdout + out.stderr


# --- --help, and a flag it doesn't know (2026-11-15) ------------------------------------------------------------------
def _no_run(monkeypatch):
    """Any pytest started — the default run, --all's suites and shards, the stress runs — fails the test."""
    monkeypatch.setattr(run_tests.subprocess, "run", lambda *a, **k: pytest.fail(f"a run started: {a[0] if a else k}"))
    monkeypatch.setattr(run_tests.subprocess, "Popen", lambda *a, **k: pytest.fail(f"a run started: {a[0] if a else k}"))


@pytest.mark.parametrize("argv", [["--help"], ["-h"], ["--all", "--help"], ["--shard", "1/4", "-h"]])
def test_help_prints_the_usage_and_starts_nothing(monkeypatch, capsys, argv):
    """Why: the runner had no --help, so `python run_tests.py --help` started the whole core suite — outside
    with-lock.sh and its throwaway data folders (two lanes in one day). It prints the usage and exits 0, whatever else
    is on the line."""
    _no_run(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", *argv])
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--all", "--shard I/N", "--stress [N]", "--stress-changed [BASE]", "--help"):
        assert flag in out, f"the usage names {flag}"


@pytest.mark.parametrize("argv", [["--verbose"], ["--all", "-x"], ["--stres"], ["--shard=1/4", "--al"]])
def test_a_flag_it_does_not_know_runs_nothing_and_fails(monkeypatch, capsys, argv):
    """The same trap through a typo: an unknown flag was ignored and the whole core suite ran. It says which flag, prints
    the usage and exits 2 (argparse's code for a bad command line), nothing run."""
    _no_run(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", *argv])
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()
    assert exit_info.value.code == 2
    out = capsys.readouterr().out
    assert repr(argv[-1]) in out and "--stress-changed [BASE]" in out


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


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_the_tracked_times_pack_a_copy_with_none_of_its_own_and_its_own_win_where_both_have_a_file(tmp_path):
    """GitHub and a fresh copy have no debug/ times: they pack by tests/test_times.json, not by file size (the slowest
    of four size-packed shards took 27-38 min against the fastest's 20-26). A copy's own --all times are newer, on its
    own machine: they win for the files they have; the tracked ones fill the rest."""
    root = str(tmp_path)
    _core(root, {"test_store.py": 10, "test_plan.py": 10, "test_kana.py": 90000})
    _write_json(os.path.join(root, "tests", "test_times.json"),
                {"tests/test_store.py": 60, "tests/test_plan.py": 50, "tests/test_kana.py": 1})
    shards = run_tests._shards(root, run_tests._core_files(root), 2)
    assert ["tests/test_store.py"] in shards, "packed by the tracked times: by size, test_kana (~9 s) would sit alone"
    _write_json(os.path.join(root, "debug", "test_times.json"), {"tests/test_kana.py": 200})
    assert run_tests._read_times(root) == {"tests/test_store.py": 60, "tests/test_plan.py": 50,
                                           "tests/test_kana.py": 200}
    assert ["tests/test_kana.py"] in run_tests._shards(root, run_tests._core_files(root), 2)


def test_a_bad_entry_in_the_times_drops_that_file_alone(tmp_path):
    """One hand-edited null, string, NaN or negative must not send every shard back to packing by size."""
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "tests"))
    with open(os.path.join(root, "tests", "test_times.json"), "w", encoding="utf-8") as f:
        f.write('{"tests/test_a.py": null, "tests/test_b.py": "slow", "tests/test_c.py": NaN, "tests/test_d.py": -1,'
                ' "tests/test_e.py": true, "tests/test_f.py": Infinity, "tests/test_g.py": 12.5, "tests/test_h.py": 3}')
    assert run_tests._read_times(root) == {"tests/test_g.py": 12.5, "tests/test_h.py": 3.0}


def test_save_times_without_git_on_the_path_writes_nothing(tmp_path, monkeypatch, capsys):
    root = str(tmp_path)
    _core(root, {"test_store.py": 10})
    _write_json(os.path.join(root, "debug", "test_times.json"), {"tests/test_store.py": 5.0})

    def no_git(cmd, **kwargs):
        raise FileNotFoundError(2, "git")
    monkeypatch.setattr(run_tests.subprocess, "run", no_git)
    assert run_tests.save_times(root) == 2
    assert not os.path.exists(os.path.join(root, "tests", "test_times.json"))
    assert "nothing written" in capsys.readouterr().out


@pytest.mark.parametrize("broken", ["{not json", "[1, 2]", '{"tests/test_a.py": "slow"}'])
def test_a_broken_tracked_times_file_packs_by_this_copys_times_or_by_size(tmp_path, broken):
    root = str(tmp_path)
    with open(os.path.join(root, "test_times.json"), "w", encoding="utf-8") as f:
        f.write(broken)
    os.makedirs(os.path.join(root, "tests"))
    os.replace(os.path.join(root, "test_times.json"), os.path.join(root, "tests", "test_times.json"))
    assert run_tests._read_times(root) == {}
    _write_json(os.path.join(root, "debug", "test_times.json"), {"tests/test_b.py": 2.5})
    assert run_tests._read_times(root) == {"tests/test_b.py": 2.5}


def test_save_times_writes_only_the_core_test_files_git_tracks(tmp_path, capsys):
    """A real repository. The copy's times also name a local-only suite's file (git-ignored, as tests/parsing/ is), a
    file deleted since, and a helper: only the tracked core test files reach the tracked file, to a tenth of a second,
    sorted, with LF line ends (one diff line a file); a core file with no time packs by size."""
    root = str(tmp_path)
    _git(root, "init", "-q", "-b", "base")
    _git(root, "config", "core.autocrlf", "true")
    _core(root, {"test_store.py": 10, "connect/test_inbox.py": 10, "test_kana.py": 10, "helpers.py": 10,
                 "parsing/test_cases.py": 10})
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("tests/parsing/\ndebug/\n")
    _git(root, "add", ".gitignore", "tests")
    _git(root, "commit", "-q", "-m", "base")
    _write_json(os.path.join(root, "debug", "test_times.json"),
                {"tests/test_store.py": 61.04, "tests/connect/test_inbox.py": 3.36, "tests/helpers.py": 1.0,
                 "tests/parsing/test_cases.py": 38.0, "tests/test_gone.py": 4.0})
    assert run_tests.save_times(root) == 0
    path = os.path.join(root, "tests", "test_times.json")
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"tests/connect/test_inbox.py": 3.4, "tests/test_store.py": 61.0}
    with open(path, "rb") as f:
        raw = f.read()
    assert b"\r" not in raw and raw.index(b"connect") < raw.index(b"test_store") and raw.endswith(b"}\n")
    out = capsys.readouterr().out
    assert "2 files' times" in out and "1 core file(s) without one" in out and "3 name(s) left out" in out
    assert b"parsing" not in raw, "a local-only suite's names never go public"


def test_save_times_with_no_times_of_its_own_or_no_git_writes_nothing(tmp_path, capsys):
    """No debug/ times (no --all ran here): the tracked file is left as it is — never rewritten from itself. No git (or
    not a repository): nothing can say what is tracked, so nothing is written."""
    root = str(tmp_path / "repo")
    os.makedirs(root)
    _git(root, "init", "-q", "-b", "base")
    _core(root, {"test_store.py": 10})
    _git(root, "add", "tests")
    _git(root, "commit", "-q", "-m", "base")
    assert run_tests.save_times(root) == 2
    assert not os.path.exists(os.path.join(root, "tests", "test_times.json"))
    other = str(tmp_path / "plain")
    _core(other, {"test_store.py": 10})
    _write_json(os.path.join(other, "debug", "test_times.json"), {"tests/test_store.py": 5.0})
    assert run_tests.save_times(other) == 2 and not os.path.exists(os.path.join(other, "tests", "test_times.json"))
    assert capsys.readouterr().out.count("nothing written") == 2


def test_save_times_that_cannot_replace_the_file_keeps_the_old_one_and_fails(tmp_path, monkeypatch, capsys):
    """Windows: an editor or a scanner holding tests/test_times.json fails the move: the old file stays whole, no .tmp
    is left beside it, and the command says so (exit 2) instead of a traceback."""
    root = str(tmp_path)
    _git(root, "init", "-q", "-b", "base")
    _core(root, {"test_store.py": 10})
    _git(root, "add", "tests")
    _git(root, "commit", "-q", "-m", "base")
    _write_json(os.path.join(root, "tests", "test_times.json"), {"tests/test_store.py": 7.0})
    _write_json(os.path.join(root, "debug", "test_times.json"), {"tests/test_store.py": 9.0})

    def held(src, dst):
        raise PermissionError(13, "the file is held open")
    monkeypatch.setattr(run_tests.os, "replace", held)
    assert run_tests.save_times(root) == 2
    with open(os.path.join(root, "tests", "test_times.json"), encoding="utf-8") as f:
        assert json.load(f) == {"tests/test_store.py": 7.0}
    assert not os.path.exists(os.path.join(root, "tests", "test_times.json.tmp"))
    assert "could not be written" in capsys.readouterr().out


def test_main_with_save_times_saves_them_and_runs_no_test(monkeypatch):
    seen = []
    monkeypatch.setattr(run_tests, "save_times", lambda root: seen.append(root) or 0)
    monkeypatch.setattr(run_tests.subprocess, "run", lambda *a, **k: pytest.fail("no test run for --save-times"))
    monkeypatch.setattr(sys, "argv", ["run_tests.py", "--save-times"])
    with pytest.raises(SystemExit) as exit_:
        run_tests.main()
    assert exit_.value.code == 0 and seen == [os.path.dirname(os.path.abspath(run_tests.__file__))]


def test_the_tracked_times_file_names_only_test_files_git_would_track():
    """tests/test_times.json is public: a name git ignores (tests/parsing/ is local only) must never be in it. A file
    deleted since the last save may linger (it packs nothing); --save-times drops it at the next train."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    with open(os.path.join(root, "tests", "test_times.json"), encoding="utf-8") as f:
        times = json.load(f)
    assert times and all(isinstance(v, (int, float)) and v >= 0 for v in times.values())
    assert all(k.startswith("tests/") and os.path.basename(k).startswith("test_") and k.endswith(".py") for k in times)
    ignored = subprocess.run(["git", "-c", "core.quotepath=false", "check-ignore", "--no-index", "--stdin"], cwd=root,
                             input="\n".join(times), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             encoding="utf-8")
    assert ignored.returncode in (0, 1), "git check-ignore itself failed"
    assert ignored.stdout.split() == []
    assert not any(k.startswith("tests/parsing/") for k in times)


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


def _pr_shard_count(root):
    with open(os.path.join(root, ".github", "workflows", "pr.yml"), encoding="utf-8") as f:
        matrix = f.read().split("\n  shards:\n", 1)[1].split("        shard: [", 1)[1].split("]", 1)[0]
    return len(matrix.split(","))


def test_this_checkout_splits_into_pr_ymls_shards_holding_every_test_file():
    """The real tests/ folder, as pr.yml splits it (by the tracked times). pytest also collects *_test.py by default:
    none may exist here, or the shards (test_*.py only) would skip it where `pytest tests` ran it."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    files = run_tests._core_files(root)
    count = _pr_shard_count(root)
    assert count == 8
    shards = [run_tests._shard_of(root, f"{i}/{count}") for i in range(1, count + 1)]
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
    shards = text.split("\n  shards:\n", 1)[1].split("\n  modules:\n", 1)[0]
    matrix = shards.split("matrix:\n", 1)[1].split("\n    steps:", 1)[0]
    lines = [line.strip() for line in matrix.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert len(lines) == 1 and lines[0].startswith("shard: ["), "one matrix dimension: the shard"
    numbers = [int(n) for n in lines[0].split("[", 1)[1].split("]", 1)[0].split(",")]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 2
    assert "run: python run_tests.py --shard ${{ matrix.shard }}/${{ strategy.job-total }}" in shards
    assert "fail-fast: false" in shards
    tests = text.split("\n  tests:\n", 1)[1].split("\n  unreview:\n", 1)[0]
    assert "needs: [changes, shards, modules]" in tests
    assert "if: ${{ always() && needs.changes.outputs.code != 'false' }}" in tests
    assert 'test "$SHARDS" = success && test "$MODULES" = success' in tests
    assert "SHARDS: ${{ needs.shards.result }}" in tests and "MODULES: ${{ needs.modules.result }}" in tests


def test_pr_yml_runs_every_public_module_suite_with_the_shards_install():
    """GitHub ran no module suite before 2026-11-21 (Junban's 1,941 tests, YouTube's 459). Every module suite this
    repository tracks runs in the `modules` job, each in its own pytest process as --all runs it, the second even after
    a red first; the job installs exactly what the shards install, so a pin moved in one place only shows here."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    with open(os.path.join(root, ".github", "workflows", "pr.yml"), encoding="utf-8") as f:
        text = f.read()
    shards = text.split("\n  shards:\n", 1)[1].split("\n  modules:\n", 1)[0]
    modules = text.split("\n  modules:\n", 1)[1].split("\n  tests:\n", 1)[0]
    tracked = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "--", "modules"], cwd=root,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8")
    assert tracked.returncode == 0, "git ls-files failed"
    suites = sorted({"/".join(p.split("/")[:3]) for p in tracked.stdout.split()
                     if len(p.split("/")) > 3 and p.split("/")[2] == "tests"})
    assert suites == ["modules/junban/tests", "modules/ukai/tests", "modules/youtube_downloader/tests"]
    runs = [line.strip() for line in modules.splitlines() if line.strip().startswith("run: python -m pytest")]
    assert runs == [f"run: python -m pytest {suite} -v -ra -p no:cacheprovider" for suite in suites]
    assert modules.count("if: ${{ !cancelled() }}") == len(suites) - 1
    assert "needs: changes" in modules and "if: ${{ !cancelled() && needs.changes.outputs.code != 'false' }}" in modules

    def install(job):
        return job.split("- name: Install (the versions the release is built with)\n", 1)[1].split("- name:", 1)[0]
    assert install(modules) == install(shards) and "pytest==" in install(shards)


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
    monkeypatch.setattr(run_tests, "run_stress_changed", lambda root, b, **k: seen.append(b) or 0)
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
        cmd, 0, stdout=answers[tuple(cmd[3:] if cmd[1:3] == ["-c", "core.quotepath=false"] else cmd[1:])].encode()))
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
    assert "passed under load: 3 of them 3 times" in capsys.readouterr().out    # (unreadable files: every repeat)


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


# --- --stress-changed: only the tests that wait on time repeat (Minato-TS, 2026-11-20) ------------------------------- #
# Mado-EZC's stress runs took 12m49s and 56m05s, ~70 % of their tests with no wait on the clock or a thread: those run
# once now, the rest 20 times. What the old gate caught must still be caught: a test that waits (a sleep, a Qt wait,
# a thread, a deadline), whether its own lines wait or a helper's, a fixture's of its conftest, or one imported from
# a tests.* module does.
_TIMING_FILE = '''import threading
import time
import pytest
from tests.waits import settle_soon


def _poll(box):
    deadline = time.perf_counter() + 2
    while not box and time.perf_counter() < deadline:
        time.sleep(0.01)


def _count(words):
    return len(words)


def test_a_sleep_of_its_own():
    time.sleep(0.01)


def test_a_helpers_deadline():
    _poll(["雨"])


def test_a_conftest_fixtures_timer(qt_ticker):
    assert qt_ticker


def test_a_waiting_helper_from_a_tests_module():
    settle_soon()


def test_counts_words_and_nothing_waits():
    assert _count(["猫", "犬"]) == 2


def test_joins_a_path_never_a_thread():
    assert "/".join(["data", "ja"]) == "data/ja"


class TestShelf:
    def test_plain(self):
        assert ["本"]


class TestWaits:
    def setup_method(self):
        self.t = threading.Thread(target=lambda: None)

    def test_with_a_thread_in_its_class(self):
        assert self.t
'''


def _timing_tree(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text(
        "import pytest\n\n\n@pytest.fixture\ndef qt_ticker():\n    from PyQt6.QtCore import QTimer\n    return QTimer()\n",
        encoding="utf-8")
    (tmp_path / "tests" / "waits.py").write_text("def settle_soon():\n    qWait(10)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_mix.py").write_text(_TIMING_FILE, encoding="utf-8")
    return str(tmp_path)


def test_stress_repeats_only_the_tests_that_wait_on_time_or_threads(tmp_path):
    root = _timing_tree(tmp_path)
    ids = ["tests/test_mix.py::" + n for n in (
        "test_a_sleep_of_its_own", "test_a_helpers_deadline", "test_a_conftest_fixtures_timer",
        "test_a_waiting_helper_from_a_tests_module", "test_counts_words_and_nothing_waits",
        "test_joins_a_path_never_a_thread", "TestShelf::test_plain", "TestWaits::test_with_a_thread_in_its_class")]
    timed, steady = run_tests._timing_tests(root, ids)
    assert timed == ids[:4] + ids[7:], "own sleep, a helper's deadline, a conftest timer, an imported wait, a class's thread"
    assert steady == ids[4:7], "no wait anywhere it reaches: once ('/'.join is no thread's join)"


def test_a_files_own_autouse_fixture_that_waits_makes_every_test_of_it_wait(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auto.py").write_text(
        "import time\nimport pytest\n\n\n@pytest.fixture(autouse=True)\ndef _quiet():\n    yield\n    time.sleep(0.01)\n"
        "\n\ndef test_reads():\n    assert '本'\n", encoding="utf-8")
    assert run_tests._timing_tests(str(tmp_path), ["tests/test_auto.py::test_reads"]) == (
        ["tests/test_auto.py::test_reads"], [])


def test_a_file_that_cant_be_read_or_parsed_repeats_whole_as_before(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_half.py").write_text("def test_a(:\n", encoding="utf-8")
    ids = ["tests/test_half.py", "tests/test_gone.py::test_b"]
    assert run_tests._timing_tests(str(tmp_path), ids) == (ids, [])


def test_stress_changed_runs_the_steady_tests_once_and_the_waiting_ones_n_times(tmp_path, monkeypatch, capsys):
    root = _timing_tree(tmp_path)
    monkeypatch.setattr(run_tests, "_changed_tests", lambda r, b: ([
        "tests/test_mix.py::test_a_sleep_of_its_own", "tests/test_mix.py::test_counts_words_and_nothing_waits"], []))
    monkeypatch.setattr(run_tests.subprocess, "Popen", lambda cmd, **k: type("P", (), {"poll": lambda self: None})())
    monkeypatch.setattr(run_tests, "_end_tree", lambda proc: None)
    runs = []
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **k: runs.append(cmd[3:-4]) or
                        subprocess.CompletedProcess(cmd, 0, stdout=b"1 passed"))
    assert run_tests.run_stress_changed(root, "base", times=4) == 0
    assert runs == [["tests/test_mix.py::test_counts_words_and_nothing_waits"]] + \
        [["tests/test_mix.py::test_a_sleep_of_its_own"]] * 4
    out = capsys.readouterr().out
    assert "1 wait on time or threads, 4 times each; 1 don't, once" in out and "1 of them 4 times, 1 once" in out


def test_stress_changed_list_prints_the_counts_and_runs_nothing(tmp_path, monkeypatch, capsys):
    root = _timing_tree(tmp_path)
    monkeypatch.setattr(run_tests, "_changed_tests", lambda r, b: (["tests/test_mix.py::test_a_sleep_of_its_own"], []))
    _no_run(monkeypatch)
    assert run_tests.run_stress_changed(root, "base", listing=True) == 0
    assert "x20  tests/test_mix.py::test_a_sleep_of_its_own" in capsys.readouterr().out


# --- --touched-callers: a lane's touched run is the callers of what it changed (Minato-TS, 2026-11-20) -------------- #
# Kura-SO's touched run took 25m35s over all 29 test_library_store_*.py; 6 reached the change. The picks are the test
# files that name a changed definition (the branch's own test files whole), a changed conftest's folder, a changed
# helper's importers, a changed data file's readers, and the area's guards.
def _touched_tree(tmp_path):
    t = tmp_path
    for d in ("app/connect", "tests/connect", "tests/qt", "templates"):
        (t / d).mkdir(parents=True)
    (t / "app" / "connect" / "library.py").write_text(
        "SHELF = '本棚'\n\n\ndef place_episode(rows):\n    return rows\n\n\ndef replace(rows):\n    return rows[::-1]\n",
        encoding="utf-8")
    (t / "templates" / "web_app.html").write_text("<p>読む</p>\n", encoding="utf-8")
    files = {
        "tests/connect/test_places.py": "from app.connect import library\n\n\ndef test_a():\n"
                                        "    assert library.place_episode(['一話'])\n",
        "tests/connect/test_by_rare_name.py": "from tests.helpers import shelf\n\n\ndef test_b():\n"
                                              "    assert shelf.place_episode\n",
        "tests/connect/test_changed.py": "def test_j():\n    assert '変'\n",
        "tests/connect/test_common_name_unimported.py": "def test_c():\n    assert '猫'.replace('猫', '犬')\n",
        "tests/connect/test_common_name_imported.py": "from app.connect.library import replace\n\n\ndef test_d():\n"
                                                     "    assert replace([1, 2]) == [2, 1]\n",
        "tests/connect/test_name_in_a_comment.py": "# place_episode is mentioned only here\ndef test_e():\n    assert 1\n",
        "tests/connect/test_patch_target.py": "def test_f(monkeypatch):\n"
                                              "    monkeypatch.setattr('app.connect.library.place_episode', len)\n",
        "tests/qt/test_page.py": "def test_g():\n    assert '頁'\n",
        "tests/test_report.py": "import os\n\n\ndef test_h():\n    assert os.path.join('templates', 'web_app.html')\n",
        "tests/test_unrelated.py": "def test_i():\n    assert '雪'\n",
        "tests/test_comment_only.py": "# web_app.html is read by the report's tests\ndef test_k():\n    assert '書'\n",
    }
    for path, text in files.items():
        (t / path).write_text(text, encoding="utf-8")
    # `replace` is a common name: a dozen and more test files use it (str.replace), so naming it alone picks nothing
    for n in range(run_tests.RARE_TESTS + 1):
        (t / "tests" / f"test_filler_{n:02d}.py").write_text(f"def test_{n}():\n    assert 'あ'.replace('あ', 'い')\n",
                                                            encoding="utf-8")
    (t / "tests" / "qt" / "conftest.py").write_text("import pytest\n", encoding="utf-8")
    return str(t)


def test_touched_callers_picks_the_files_that_name_what_changed(tmp_path, monkeypatch):
    root = _touched_tree(tmp_path)
    monkeypatch.setattr(run_tests, "_changed_lines", lambda r, b: {
        "app/connect/library.py": {5, 9}, "templates/web_app.html": {1}, "tests/qt/conftest.py": {1},
        "tests/connect/test_changed.py": {2}})
    monkeypatch.setattr(run_tests, "_changed_test_files", lambda r, b: ["tests/connect/test_changed.py"])
    monkeypatch.setattr(run_tests, "GUARDS", {"tests/test_unrelated.py": ("templates/",),
                                              "tests/test_report.py::test_h": ("app/qt/",)})
    picked, why, notes = run_tests._touched_callers(root, "base")
    assert picked == ["tests/connect/test_by_rare_name.py", "tests/connect/test_changed.py",
                      "tests/connect/test_common_name_imported.py",
                      "tests/connect/test_patch_target.py", "tests/connect/test_places.py", "tests/qt/test_page.py",
                      "tests/test_report.py", "tests/test_unrelated.py"], why
    assert why["tests/connect/test_changed.py"] == "changed on the branch"
    assert "place_episode" in why["tests/connect/test_by_rare_name.py"], "a rare name counts unimported (a helper's)"
    assert "replace" in why["tests/connect/test_common_name_imported.py"], "a common name counts where it is imported"
    assert "place_episode" in why["tests/connect/test_patch_target.py"], "a patch target names it"
    assert why["tests/qt/test_page.py"] == "uses tests/qt/conftest.py (changed)"
    assert "web_app.html" in why["tests/test_report.py"]
    assert why["tests/test_unrelated.py"].startswith("the area's guard (templates/")
    assert "tests/connect/test_name_in_a_comment.py" not in why, "a comment is no caller"
    assert "tests/test_comment_only.py" not in why, "a comment naming a changed file is no reader"
    assert "tests/connect/test_common_name_unimported.py" not in why, "str.replace is not library.replace"


def test_touched_callers_says_so_when_nothing_changed(tmp_path, monkeypatch, capsys):
    root = _touched_tree(tmp_path)
    monkeypatch.setattr(run_tests, "_changed_lines", lambda r, b: {})
    monkeypatch.setattr(run_tests, "_changed_test_files", lambda r, b: [])
    monkeypatch.setattr(run_tests, "_removed_app_names", lambda r, b: {})
    _no_run(monkeypatch)
    assert run_tests.run_touched_callers(root, "base") == 0
    out = capsys.readouterr().out
    assert "nothing changed since base" in out and "0 test file(s)" in out


def test_touched_callers_runs_each_suite_under_the_read_audit(tmp_path, monkeypatch, capsys):
    root = _touched_tree(tmp_path)
    monkeypatch.setattr(run_tests, "_touched_callers", lambda r, b: (
        ["modules/junban/tests/test_x.py", "tests/test_a.py"], {"modules/junban/tests/test_x.py": "w",
                                                                "tests/test_a.py": "w"}, []))
    runs = []
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **k: runs.append((cmd[3:], k["env"])) or
                        subprocess.CompletedProcess(cmd, 0, stdout=b"3 passed in 0.1s"))
    assert run_tests.run_touched_callers(root, "base") == 0
    assert sorted(r[0][0] for r in runs) == ["modules/junban/tests/test_x.py", "tests/test_a.py"]
    assert all(r[0][-2:] == ["-p", "tests.read_audit"] and r[1]["SURASURA_READ_AUDIT"] == "ignored" for r in runs)


# --- --guards: the whole-repo guard tests before every push (Minato-TS, 2026-11-20) --------------------------------- #
def test_every_guard_is_a_test_file_of_this_checkout_and_the_set_is_not_empty():
    """GUARDS names files GitHub runs (the public checkout): a guard renamed or removed without its row would leave a
    window-wide scan out of every lane's pre-push run, silently."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    assert run_tests.GUARDS
    for node, folders in run_tests.GUARDS.items():
        path = node.split("::", 1)[0]
        assert run_tests._is_test_file(path) and os.path.isfile(os.path.join(root, path)), node
        assert folders and all(isinstance(f, str) and f for f in folders), node


def test_guards_run_each_suite_once_under_the_read_audit_and_name_what_is_missing(tmp_path, monkeypatch, capsys):
    (tmp_path / "tests" / "qt").mkdir(parents=True)
    (tmp_path / "tests" / "qt" / "test_scan.py").write_text("def test_a():\n    assert '画'\n", encoding="utf-8")
    monkeypatch.setattr(run_tests, "GUARDS", {"tests/qt/test_scan.py": ("app/qt/",),
                                              "tests/test_gone.py::test_b": ("app/",)})
    runs = []
    monkeypatch.setattr(run_tests.subprocess, "run", lambda cmd, **k: runs.append((cmd[3:], k["env"])) or
                        subprocess.CompletedProcess(cmd, 1, stdout=b"1 failed in 0.1s"))
    assert run_tests.run_guards(str(tmp_path)) == 1
    assert [r[0][0] for r in runs] == ["tests/qt/test_scan.py"]
    assert runs[0][1]["SURASURA_READ_AUDIT"] == "ignored" and runs[0][0][-2:] == ["-p", "tests.read_audit"]
    out = capsys.readouterr().out
    assert "tests/test_gone.py::test_b" in out and "[FAIL]  the guard set" in out


@pytest.mark.parametrize("argv", [["--guards", "--list"], ["--touched-callers", "--list"],
                                  ["--touched-callers", "origin/2.x-dev", "--list"], ["--stress-changed", "--list"]])
def test_list_prints_the_picks_and_starts_nothing(monkeypatch, capsys, argv):
    monkeypatch.setattr(run_tests, "_changed_lines", lambda r, b: {})
    monkeypatch.setattr(run_tests, "_changed_test_files", lambda r, b: [])
    monkeypatch.setattr(run_tests, "_changed_tests", lambda r, b: ([], []))
    monkeypatch.setattr(run_tests, "_test_files", lambda r: [])
    monkeypatch.setattr(run_tests, "_removed_app_names", lambda r, b: {})
    _no_run(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", *argv])
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()
    assert exit_info.value.code == 0


@pytest.mark.parametrize("argv", [["--list"], ["--all", "--list"], ["--list", "--shard", "1/4"]])
def test_list_without_a_flag_it_lists_for_runs_nothing_and_fails(monkeypatch, capsys, argv):
    """Why: `--list` alone (or with --all / --shard) fell through to the whole core run (train 53's keeper) — outside
    with-lock.sh and its throwaway data folders, like --help once did. It says what --list goes with and exits 2."""
    _no_run(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", *argv])
    with pytest.raises(SystemExit) as exit_info:
        run_tests.main()
    assert exit_info.value.code == 2
    assert "--touched-callers" in capsys.readouterr().out


def test_a_nanosecond_clock_and_a_window_exposed_wait_are_waits(tmp_path):
    """(Train 53's keeper: time.time_ns and qWaitForWindowExposed slipped past the timing pattern, so such a test ran
    once in --stress-changed.)"""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_clock.py").write_text(
        "import time\n\n\ndef test_ns():\n    assert time.time_ns() > 0\n\n\n"
        "def test_s():\n    assert time.time() > 0\n\n\n"
        "def test_exposed(qtbot, window):\n    qtbot.qWaitForWindowExposed(window)\n\n\n"
        "def test_still():\n    assert '本'\n", encoding="utf-8")
    ids = ["tests/test_clock.py::test_ns", "tests/test_clock.py::test_s", "tests/test_clock.py::test_exposed",
           "tests/test_clock.py::test_still"]
    assert run_tests._timing_tests(str(tmp_path), ids) == (ids[:3], ids[3:])


# (The 2026-11-20 review's misses, each one a wait or a caller the first cut didn't see.)
def test_waits_reached_through_from_tests_import_a_platform_helper_a_join_and_a_bom_still_repeat(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "helpers.py").write_text("import time\n\n\ndef wait_flag():\n    time.sleep(0.01)\n",
                                                   encoding="utf-8")
    (tmp_path / "tests" / "test_more.py").write_text(
        "import sys\nfrom tests import helpers\n\nif sys.platform == 'win32':\n    def _settle_files():\n"
        "        return time.sleep(0.05)\nelse:\n    def _settle_files():\n        return None\n\n\n"
        "def test_through_a_helper_module():\n    helpers.wait_flag()\n\n\n"
        "def test_through_a_platform_helper():\n    _settle_files()\n\n\n"
        "def test_a_join_with_what_is_left(t, left):\n    t.join(left)\n\n\n"
        "def test_a_word_list():\n    assert ', '.join(['雨', '雪']) == '雨, 雪'\n", encoding="utf-8")
    (tmp_path / "tests" / "test_bom.py").write_bytes("﻿def test_plain():\n    assert '本'\n".encode("utf-8"))
    ids = ["tests/test_more.py::" + n for n in ("test_through_a_helper_module", "test_through_a_platform_helper",
                                                "test_a_join_with_what_is_left", "test_a_word_list")]
    timed, steady = run_tests._timing_tests(str(tmp_path), ids + ["tests/test_bom.py::test_plain"])
    assert timed == ids[:3] and steady == [ids[3], "tests/test_bom.py::test_plain"], (timed, steady)


def test_a_removed_function_picks_the_test_file_that_still_calls_it(tmp_path):
    """A real repository: the branch deletes app/shelf.py's `old_count`; the test calling it is unchanged, and goes
    red — the touched run must pick it."""
    root = str(tmp_path)
    _git(root, "init", "-q", "-b", "base")
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "shelf.py").write_text("def old_count(books):\n    return len(books)\n\n\n"
                                               "def count(books):\n    return len(books)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_shelf_count.py").write_text(
        "from app import shelf\n\n\ndef test_counts():\n    assert shelf.old_count(['本']) == 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text("def test_other():\n    assert '雪'\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "lane")
    (tmp_path / "app" / "shelf.py").write_text("def count(books):\n    return len(books)\n", encoding="utf-8")
    picked, why, _notes = run_tests._touched_callers(root, "base")
    assert picked == ["tests/test_shelf_count.py"] and "old_count" in why["tests/test_shelf_count.py"], why


# --- --local-only: what GitHub's pull request run can't run (Minato-GH, 2026-11-22) -----------------------------------
# A train's gate is its pull request green on GitHub (the public core and module suites on the merge commit) plus the
# local --local-only. Nothing may fall between the two: the set is derived on every run (never a hand-kept list), and
# two guards below hold it on the real tree. The fake repositories use invented module names (kaminari, hoshi, oboro).

def _local_repo(tmp_path, private_repo=True):
    """A public repository and a private one beside it (<top folder>.priv.git, as `git priv` finds it). The public one
    tracks the core files and Junban; it ignores the private modules and the local-only suite tests/sakura/, which the
    private one tracks. modules/hoshi is tracked privately but not checked out here; modules/oboro is here, tracked by
    neither, with no tests/ folder."""
    root = tmp_path / "repo"
    public = {
        ".gitignore": "modules/*\n!modules/junban/\ntests/sakura/\n",
        "tests/conftest.py": "",
        "tests/test_store.py": "def test_store():\n    assert '本棚'\n",
        "tests/test_voice.py": "import pytest\nvoice = pytest.importorskip('modules.kaminari.voice')\n",
        "tests/test_join.py": "import os\nPATH = os.path.join('modules', 'kaminari')\n",
        "tests/test_from.py": "from modules import junban, kaminari\n",
        "tests/test_slash.py": "# 雷の声: reads modules\\kaminari\\data when it is there\r\nDATA = 'modules/kaminari/雷.json'\r\n",
        "tests/test_lookalike.py": "OLD = 'modules.kaminari_old'\nSINGULAR = 'module.kaminari'\nWORD = 'kaminari'\n",
        "tests/kaminari_help.py": "PATH = 'modules/kaminari'\n",
        "tests/test_through_helper.py": "from tests import kaminari_help\n",
        "tests/sub/conftest.py": "import modules.kaminari\n",
        "tests/sub/test_below.py": "def test_below():\n    assert '雪'\n",
        "tests/test_names_the_suite.py": "SUITE = 'tests/sakura'\n",
        "tests/test_paren.py": "from modules import (\n    junban,\n    kaminari,\n)\n",
        "tests/deep/conftest.py": "from tests import kaminari_help\n",
        "tests/deep/test_deep.py": "def test_deep():\n    assert '深い'\n",
        "modules/junban/__init__.py": "",
        "modules/junban/tests/test_j.py": "def test_j():\n    assert '順番'\n",
    }
    private = {
        "tests/sakura/test_cases.py": "def test_case():\n    assert '桜'\n",
        "modules/kaminari/__init__.py": "",
        "modules/kaminari/tests/test_k.py": "def test_k():\n    assert '雷'\n",
        "modules/hoshi/__init__.py": "",
    }
    left_over = {"modules/oboro/__init__.py": "", "modules/kumo/__pycache__/gone.cpython-311.pyc": ""}
    for rel, text in {**public, **private, **left_over}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    _git(str(root), "init", "-q", "-b", "base")
    _git(str(root), "add", *public)
    _git(str(root), "commit", "-q", "-m", "public")
    if private_repo:
        priv = ["--git-dir=" + str(root) + ".priv.git", "--work-tree=" + str(root)]
        _git(str(root), *priv, "init", "-q")
        _git(str(root), *priv, "add", "-f", *private)
        _git(str(root), *priv, "commit", "-q", "-m", "private")
    (root / "modules" / "hoshi" / "__init__.py").unlink()
    (root / "modules" / "hoshi").rmdir()
    return str(root)


def test_local_only_is_the_untracked_suite_the_private_suites_and_every_file_naming_a_private_folder(tmp_path):
    """Each way a core file can name a private folder counts: a dotted import, os.path.join's parts, `from modules
    import` (one line or bracketed over several), a Windows path in a CRLF file with Japanese in it, a helper it
    imports, a conftest above it, a conftest above it that imports such a helper; a lookalike name (kaminari_old,
    module.kaminari, the bare word) doesn't. A private folder the private repo tracks but this checkout lacks, and a
    private module here with no suite, are named — never skipped quietly; a module folder left holding only
    __pycache__ is no module."""
    root = _local_repo(tmp_path)
    part = run_tests.local_only(root)
    assert part["core"] == {
        "tests/deep/test_deep.py": "names modules/kaminari (through tests/kaminari_help.py)",
        "tests/sakura/test_cases.py": "in tests/sakura/, which the public repo doesn't track",
        "tests/sub/test_below.py": "names modules/kaminari (through tests/sub/conftest.py)",
        "tests/test_from.py": "names modules/kaminari",
        "tests/test_join.py": "names modules/kaminari",
        "tests/test_names_the_suite.py": "names tests/sakura",
        "tests/test_paren.py": "names modules/kaminari",
        "tests/test_slash.py": "names modules/kaminari",
        "tests/test_through_helper.py": "names modules/kaminari (through tests/kaminari_help.py)",
        "tests/test_voice.py": "names modules/kaminari",
    }
    assert part["suites"] == ["modules/kaminari/tests"], "the public module's suite is GitHub's"
    assert part["missing"] == ["modules/hoshi", "modules/oboro/tests"] and part["private_repo"]
    summary = run_tests._local_only_summary(part)
    assert summary.startswith("Local-only set: 10 core test file(s) (1 the public repo doesn't track, 9 naming a "
                              "private folder) + 1 private module suite(s): modules/kaminari/tests")
    assert "NOT HERE" in summary and "modules/hoshi, modules/oboro/tests" in summary


def test_local_only_without_a_private_repo_still_finds_the_modules_here_and_says_what_it_cant_know(tmp_path):
    """A checkout with no private repo beside it (a hand-made copy): the private modules on disk still count (the
    public repo tracks nothing of theirs), and the output says a module it lacks can't be named."""
    root = _local_repo(tmp_path, private_repo=False)
    part = run_tests.local_only(root)
    assert part["suites"] == ["modules/kaminari/tests"] and part["missing"] == ["modules/oboro/tests"]
    assert "tests/test_voice.py" in part["core"] and "tests/sakura/test_cases.py" in part["core"]
    assert part["core"]["tests/sakura/test_cases.py"] == "not tracked by the public repo"
    assert "tests/test_names_the_suite.py" not in part["core"], "unknown as a private folder without the private repo"
    assert not part["private_repo"] and "can't be named" in run_tests._local_only_summary(part)


def test_a_private_repo_git_cannot_read_fails_local_only_never_an_empty_set(tmp_path, monkeypatch, capsys):
    """The private repo is there but git can't read it (not a repository, a locked index, an owner git refuses): the
    set can't be told, so nothing runs and the gate fails — never read as "the private repo tracks nothing"."""
    root = _local_repo(tmp_path)
    real = run_tests._run

    def failing_private(cmd, *a, **k):
        if any(str(part).startswith("--git-dir=") for part in cmd):
            return subprocess.CompletedProcess(cmd, 128, b"", b"")
        return real(cmd, *a, **k)
    monkeypatch.setattr(run_tests, "_run", failing_private)
    assert run_tests.local_only(root) is None
    monkeypatch.setattr(run_tests, "run_all", lambda *a, **k: pytest.fail("ran without knowing the set"))
    assert run_tests.run_local_only(root) == 2 and "nothing was run" in capsys.readouterr().out


def test_local_only_without_git_runs_nothing_and_fails(tmp_path, monkeypatch, capsys):
    """No repository (or no git): the set can't be told, so nothing runs and the gate fails (exit 2), never a pass."""
    _no_run(monkeypatch)
    _core(str(tmp_path), {"test_a.py": 10})
    monkeypatch.setattr(run_tests, "_public_files", lambda root: None)
    assert run_tests.run_local_only(str(tmp_path)) == 2
    assert "nothing was run" in capsys.readouterr().out


def _fake_runs(monkeypatch, red=()):
    seen = {"shards": [], "suites": []}

    def fake_shard(project_root, label, files, times_path):
        seen["shards"].append(files)
        return label, 0, f"= {len(files)} passed in 0.1s =\n", 0.1

    def fake_suite(project_root, suite):
        seen["suites"].append(suite)
        return (suite, 1, "= 1 failed, 2 passed in 0.1s =\n", 0.1) if suite in red else \
            (suite, 0, "= 3 passed in 0.1s =\n", 0.1)
    monkeypatch.setattr(run_tests, "_run_shard", fake_shard)
    monkeypatch.setattr(run_tests, "_run_suite", fake_suite)
    monkeypatch.setattr(run_tests, "_idle_cpus", lambda cpus: None)
    return seen


def test_local_only_runs_its_part_side_by_side_and_never_the_whole_core_suite(tmp_path, monkeypatch, capsys):
    """One core file and one private suite: the file runs as a shard of its own (`pytest tests` would be the whole core
    suite, GitHub's half), beside the suite; the set's size is said first."""
    root = str(tmp_path)
    _core(root, {"test_voice.py": 10, "test_store.py": 10})
    part = {"core": {"tests/test_voice.py": "names modules/kaminari"}, "suites": ["modules/kaminari/tests"],
            "missing": [], "private_repo": True}
    monkeypatch.setattr(run_tests, "local_only", lambda project_root: part)
    seen = _fake_runs(monkeypatch)
    assert run_tests.run_local_only(root) == 0
    assert seen == {"shards": [["tests/test_voice.py"]], "suites": ["modules/kaminari/tests"]}
    out = capsys.readouterr().out
    assert out.index("Local-only set: 1 core test file(s)") < out.index("--local-only: what GitHub")
    assert "[PASS]  ALL 2 SUITES PASSED" in out


def test_a_red_private_suite_fails_local_only_and_prints_its_output(tmp_path, monkeypatch, capsys):
    root = str(tmp_path)
    _core(root, {"test_voice.py": 10, "test_join.py": 10, "test_from.py": 10})
    part = {"core": {f"tests/{n}": "names modules/kaminari" for n in ("test_from.py", "test_join.py", "test_voice.py")},
            "suites": ["modules/kaminari/tests"], "missing": ["modules/hoshi"], "private_repo": True}
    monkeypatch.setattr(run_tests, "local_only", lambda project_root: part)
    monkeypatch.setattr(run_tests, "_shard_count", lambda free_mb, cpus, idle: 2)
    seen = _fake_runs(monkeypatch, red=("modules/kaminari/tests",))
    assert run_tests.run_local_only(root) == 1
    assert sorted(sum(seen["shards"], [])) == sorted(part["core"]) and len(seen["shards"]) == 2
    out = capsys.readouterr().out
    assert "NOT HERE" in out and "FAILED: modules/kaminari/tests" in out and "1 OF 2 SUITES FAILED" in out


def test_local_only_with_nothing_local_here_runs_nothing_and_passes(tmp_path, monkeypatch, capsys):
    """A public-only checkout (GitHub's): nothing is local-only, so nothing runs and it says so."""
    _no_run(monkeypatch)
    monkeypatch.setattr(run_tests, "local_only", lambda project_root: {"core": {}, "suites": [], "missing": [],
                                                                       "private_repo": False})
    assert run_tests.run_local_only(str(tmp_path)) == 0
    assert "Nothing to run" in capsys.readouterr().out


@pytest.mark.parametrize("argv, listing", [(["--local-only"], False), (["--local-only", "--list"], True)])
def test_main_with_local_only_runs_or_lists_the_set(monkeypatch, argv, listing):
    seen = []
    monkeypatch.setattr(run_tests, "run_local_only", lambda root, listing=False: seen.append(listing) or 0)
    _no_run(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_tests.py", *argv])
    with pytest.raises(SystemExit) as exit_:
        run_tests.main()
    assert exit_.value.code == 0 and seen == [listing]


def test_local_only_list_names_each_file_and_why_and_runs_nothing(tmp_path, monkeypatch, capsys):
    root = _local_repo(tmp_path)
    monkeypatch.setattr(run_tests, "run_all", lambda *a, **k: pytest.fail("--list ran the set"))
    assert run_tests.run_local_only(root, listing=True) == 0
    out = capsys.readouterr().out
    assert "  tests/test_join.py  (names modules/kaminari)" in out
    assert "  modules/kaminari/tests  (a private module's suite)" in out


# The two guards on the real tree (run_tests.py GUARDS: before every push, and in every train's --guards).

def test_githubs_run_and_the_local_only_run_hold_every_file_of_all_between_them():
    """The cover check. --all runs whole files (the core suite's test files in shards, each module suite whole), and so
    do GitHub's shards and --local-only: a file held is every test id of it held. GitHub's half is what pr.yml runs on
    its checkout (the files the public repo tracks): `--shard I/N` for each I of its matrix, packed by the same
    _shards, and its module suites; the local half is local_only(). Every file of this checkout's --all must be in
    one of them. On GitHub's checkout (nothing private) the local half is empty and the check still holds."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    part = run_tests.local_only(root)
    public = run_tests._public_files(root)
    assert part is not None and public, "git can't list this checkout's files"
    with open(os.path.join(root, ".github", "workflows", "pr.yml"), encoding="utf-8") as f:
        text = f.read()
    shards = text.split("\n  shards:\n", 1)[1].split("\n  modules:\n", 1)[0]
    assert "run: python run_tests.py --shard ${{ matrix.shard }}/${{ strategy.job-total }}" in shards
    numbers = [int(n) for n in shards.split("shard: [", 1)[1].split("]", 1)[0].split(",")]
    github_core = [path for path in run_tests._core_files(root) if path in public]     # GitHub's checkout's walk
    packed = run_tests._shards(root, github_core, len(numbers))
    on_github = {path for i in numbers if i <= len(packed) for path in packed[i - 1]}
    modules = text.split("\n  modules:\n", 1)[1].split("\n  tests:\n", 1)[0]
    github_suites = {line.split("python -m pytest ", 1)[1].split()[0] for line in modules.splitlines()
                     if line.strip().startswith("run: python -m pytest ")}               # (never a commented-out one)
    everything = run_tests._core_files(root)
    assert set(part["core"]) <= set(everything), "a local-only file --all doesn't run"
    fell_between = [path for path in everything if path not in on_github and path not in part["core"]]
    assert fell_between == [], f"core test files neither half runs: {fell_between}"
    suites = run_tests._suites(root)[1:]
    assert [s for s in suites if s not in github_suites and s not in part["suites"]] == [], "a module suite neither runs"
    assert all(s in public or any(p.startswith(s + "/") for p in public) for s in github_suites), \
        "pr.yml runs a module suite GitHub's checkout lacks"


def _private_imports(source, names):
    """The private modules (of `names`) a test source imports, by its syntax tree: `import modules.x`, `from modules
    import x`, `from modules.x import …`, and a string naming the dotted module (importorskip, import_module,
    monkeypatch targets, sys.modules keys)."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            dotted = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            dotted = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            dotted = [node.value]
        else:
            continue
        for name in dotted:
            parts = name.split(".")
            if len(parts) > 1 and parts[0] == "modules" and parts[1] in names:
                found.add(parts[1])
    return found


def test_no_tracked_core_test_file_imports_a_private_module_outside_the_local_only_set():
    """The import check: the set comes from a text scan; this reads each tracked core test file's syntax tree instead
    (and each conftest and helper of tests/, for the test files below it or importing it). A test file that imports a
    private module (one installed here that the public repo tracks nothing of) takes another path on GitHub, so it must
    be in --local-only; one outside it is red. Only files the public repo tracks are read (the read audit)."""
    root = os.path.dirname(os.path.abspath(run_tests.__file__))
    part = run_tests.local_only(root)
    public = run_tests._public_files(root)
    assert part is not None and public, "git can't list this checkout's files"
    names = {suite.split("/")[1] for suite in part["suites"]}
    names |= {m.split("/")[1] for m in part["missing"] if m.startswith("modules/")}
    core = [path for path in run_tests._core_files(root) if path in public]
    sources = {}
    for path in (p for p in public if p.startswith("tests/") and p.endswith(".py")):
        with open(os.path.join(root, path), encoding="utf-8-sig") as f:
            text = f.read()
        if "modules" in text and any(name in text for name in names):
            sources[path] = text
    outside = []
    for path, text in sources.items():
        found = _private_imports(text, names)
        if not found:
            continue
        base = os.path.basename(path)
        if base.startswith("test_"):
            users = [path] if path in core else []
        elif base == "conftest.py":
            users = [p for p in core if p.startswith(path[:-len(base)])]
        else:
            stem = base[:-3]
            users = [p for p in core if stem in _imported_names(root, p)]
        outside += [f"{user} ({', '.join(sorted(found))})" for user in users if user not in part["core"]]
    assert outside == [], f"imports a private module, not in --local-only: {outside}"


def _imported_names(root, path):
    """Every name a test file's imports bind or load (each dotted part)."""
    with open(os.path.join(root, path), encoding="utf-8-sig") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(part for alias in node.names for part in alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            names.update((node.module or "").split(".") + [alias.name for alias in node.names])
    return names
