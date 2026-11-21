"""scripts/cli_smoke.py stays honest (P1.1 row 1.1.7): the release build runs it on the frozen surasura-cli.exe, and the
suite runs the same checks on `python -m app.cli`, so a contract change that breaks the smoke shows up here first."""
import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_smoke_passes_from_source():
    proc = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "scripts", "cli_smoke.py"), "--source"],
                          cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    output = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0 and output.rstrip().endswith("SMOKE OK"), output


def test_the_smoke_fails_on_a_missing_build(tmp_path):
    # Pointed at a folder with no surasura-cli.exe, the smoke says so and exits 1 (never a false SMOKE OK).
    proc = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "scripts", "cli_smoke.py"), str(tmp_path)],
                          cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    assert proc.returncode == 1 and b"SMOKE FAILED" in proc.stdout


# The Package job's move of dist was refused 0.4 s after the smoke (2026-11-20, 3 of 5 attempts on one PR): the frozen
# smoke now waits for the build's own programs to end, and names what lingered.
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
import cli_smoke  # noqa: E402


@pytest.mark.skipif(sys.platform != "win32", reason="the process list is read through Windows' own calls")
def test_the_programs_running_from_a_folder_are_found_by_their_path(tmp_path):
    """This test's own Python runs from its folder; an empty folder runs nothing."""
    here = cli_smoke.running_from(os.path.dirname(sys.executable))
    assert os.getpid() in here and here[os.getpid()].lower().endswith("python.exe"), here
    assert cli_smoke.running_from(str(tmp_path)) == {}


def test_the_smoke_waits_for_the_builds_programs_and_says_what_lingered_and_what_never_ended():
    now = [0.0]
    seen = [{7: "D:/a/dist/Surasura/Surasura.exe"}, {7: "D:/a/dist/Surasura/Surasura.exe"}, {}]
    looks = iter(seen)
    clock = lambda: now[0]

    def look(_folder):
        now[0] += 0.5
        return next(looks)
    assert cli_smoke.wait_for_build_processes("D:/a/dist/Surasura", timeout=60, clock=clock, look=look) == (
        1.5, ["D:/a/dist/Surasura/Surasura.exe"], [])
    now[0] = 0.0
    stuck = lambda _folder: (now.__setitem__(0, now[0] + 30), {9: "D:/a/dist/Surasura/Surasura.exe"})[1]
    waited, _first, left = cli_smoke.wait_for_build_processes("D:/a/dist/Surasura", timeout=60, clock=clock, look=stuck)
    assert left == ["D:/a/dist/Surasura/Surasura.exe"] and waited >= 60, "bounded: it says what never ended"

