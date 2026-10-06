"""scripts/cli_smoke.py stays honest (P1.1 row 1.1.7): the release build runs it on the frozen surasura-cli.exe, and the
suite runs the same checks on `python -m app.cli`, so a contract change that breaks the smoke shows up here first."""
import os
import subprocess
import sys

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
