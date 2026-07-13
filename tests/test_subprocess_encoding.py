"""Regression tests for the analyzer-subprocess stdout ENCODING crash.

The GUI (app/main.py run_command_async) launches the analyzer as a subprocess, pipes its stdout,
and reads it as STRICT UTF-8. In source mode the analyzer is launched directly, so on Windows its
stdout is encoded in the OS locale (cp1252) unless told otherwise. A single non-ASCII byte then
breaks the parent's UTF-8 read:

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0x97 in position 794: invalid start byte

This actually happened on the run-signature SKIP path ("rerun on a setting I've run before"): an
em-dash in that message became cp1252 0x97. Two independent guards below:
  1. build_subprocess_env() forces the child's stdio to UTF-8 (the root fix).
  2. The analyzer's hot-path stdout stays ASCII-clean, so it survives even a hostile locale.
"""

import os
import sys
import subprocess

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYZER = os.path.join(PROJECT_ROOT, "app", "analyzer.py")

# '冒険' recurs (clears the default band floor) so the cold run writes real outputs.
JA = "冒険。冒険する。冒険だ。今日はいい天気です。"


def test_build_subprocess_env_forces_utf8_stdio(monkeypatch):
    """The child-env builder MUST force UTF-8 stdio even when the OS locale / inherited env is
    cp1252 — otherwise the analyzer's stdout is emitted as cp1252 and the parent's strict-UTF-8
    capture crashes on the first non-ASCII byte. This is the root fix; guard it directly."""
    from app.main import build_subprocess_env
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")   # hostile base (emulates a Windows locale)
    env = build_subprocess_env(frozen=True)            # frozen=True: skip the source-mode PYTHONPATH branch
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_build_subprocess_env_adds_project_root_in_source_mode(monkeypatch):
    """Source mode must put the project root on PYTHONPATH so the child's `from app import ...`
    resolves, without clobbering an existing PYTHONPATH."""
    from app.main import build_subprocess_env
    monkeypatch.setenv("PYTHONPATH", "/some/existing")
    env = build_subprocess_env(frozen=False)
    assert PROJECT_ROOT in env["PYTHONPATH"]
    assert "/some/existing" in env["PYTHONPATH"]      # preserved, not overwritten
    assert env["PYTHONIOENCODING"] == "utf-8"


@pytest.fixture
def library(tmp_path):
    """A minimal, isolated on-disk library the analyzer subprocess can run against via
    SURASURA_TEST_ROOT (so it never touches real data or the real token store)."""
    (tmp_path / "data" / "ja" / "HighPriority").mkdir(parents=True)
    (tmp_path / "data" / "ja" / "HighPriority" / "t.txt").write_text(JA, encoding="utf-8")
    (tmp_path / "User Files" / "ja").mkdir(parents=True)
    (tmp_path / "User Files" / "ja" / "KnownWord.json").write_text('{"words": []}', encoding="utf-8")
    (tmp_path / "results").mkdir()
    return tmp_path


def test_analyzer_rerun_skip_path_is_utf8_capturable_under_cp1252(library):
    """The user's exact crash scenario, reproduced portably: launch the analyzer the way source
    mode does but with a HOSTILE cp1252 child locale, and capture stdout as STRICT UTF-8 (exactly
    as run_command_async does). Run twice so the second hits the run-signature SKIP path — whose
    message previously carried an em-dash (-> cp1252 0x97 -> decode crash). The analyzer's stdout
    must be ASCII-clean, so the capture succeeds and the skip message is present."""
    env = os.environ.copy()
    env["SURASURA_TEST_ROOT"] = str(library)
    env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    # Force the pre-fix hostile condition on ANY OS: child emits cp1252, parent decodes strict UTF-8.
    env["PYTHONIOENCODING"] = "cp1252"

    def run():
        # Capture RAW bytes, then decode strict UTF-8 exactly as run_command_async reads the pipe.
        p = subprocess.run([sys.executable, ANALYZER, "--language", "ja"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180, env=env)
        try:
            text = p.stdout.decode("utf-8")       # a cp1252 0x97 (the reported bug) raises here
        except UnicodeDecodeError as e:
            pytest.fail(f"analyzer stdout is not UTF-8 capturable (the reported crash): {e}")
        return p.returncode, text

    cold_rc, cold_out = run()                     # tokenizes, writes outputs + stores run signature
    assert cold_rc == 0, f"cold run failed:\n{cold_out}"
    warm_rc, warm_out = run()                     # nothing changed -> run-signature SKIP path
    assert warm_rc == 0, f"warm run failed:\n{warm_out}"
    assert "reusing existing results" in warm_out, \
        "second run should hit the run-signature skip path (whose message must be UTF-8 capturable)"


def test_analyzer_stdout_hotpath_has_no_nonascii(library):
    """Guards the codebase's ASCII-stdout convention on the analyzer's normal path: the captured
    stdout of a plain run must be pure ASCII, so no launch locale can ever turn it into an invalid
    UTF-8 byte. (Non-ASCII content like filenames is deliberately guarded with UnicodeEncodeError
    fallbacks in the analyzer; this test keeps that guarantee from silently regressing.)"""
    env = os.environ.copy()
    env["SURASURA_TEST_ROOT"] = str(library)
    env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, ANALYZER, "--language", "ja"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", timeout=180, env=env)
    assert r.returncode == 0, f"run failed:\n{r.stdout}"
    nonascii = sorted({c for c in r.stdout if ord(c) > 127})
    assert not nonascii, f"analyzer emitted non-ASCII to stdout (crash risk under a cp1252 pipe): {nonascii!r}"
