"""*Open Anki for me*'s launcher (P2.3 row 2.3.3; ✅ Q4-16, K102): Anki found where its installers put it and never
searched for, started detached on the profile Connect was set up with, its environment cleaned of this program's own
Python / Tcl / Qt variables, and never the real Anki in a test (a stand-in script is started instead).
"""
import json
import os
import subprocess
import sys
import time

import pytest

from app.connect import open_anki

STAND_IN = """import json, os, sys
with open(os.environ["STAND_IN_OUT"], "w", encoding="utf-8") as f:
    json.dump({"argv": sys.argv[1:], "env": {k: v for k, v in os.environ.items()
                                            if k.startswith(("PYTHONPATH", "QT_", "TCL_", "STAND_IN"))}}, f)
"""


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """A stand-in "Anki": a script that writes down how it was started, then exits."""
    script = tmp_path / "anki_stand_in.py"
    script.write_text(STAND_IN, encoding="utf-8")
    out = tmp_path / "started.json"
    monkeypatch.setenv(open_anki.STAND_IN, str(script))
    monkeypatch.setenv("STAND_IN_OUT", str(out))
    return script, out


def _wait_for(path, seconds=30.0):
    deadline = time.monotonic() + seconds
    while not path.exists() or not path.stat().st_size:
        assert time.monotonic() < deadline, "the stand-in Anki never started"
        time.sleep(0.1)
    time.sleep(0.1)
    return json.loads(path.read_text(encoding="utf-8"))


def test_under_a_test_root_the_real_anki_is_never_found(monkeypatch):
    monkeypatch.delenv(open_anki.STAND_IN, raising=False)
    monkeypatch.setattr(open_anki, "_windows_places", lambda: [sys.executable])     # even with one "installed"
    assert open_anki.find() is None
    assert open_anki.start("日本語") is None


def test_the_stand_in_starts_detached_on_connects_profile_with_a_clean_environment(stand_in, monkeypatch):
    script, out = stand_in
    monkeypatch.setenv("PYTHONPATH", "C:\\Surasura\\app")
    monkeypatch.setenv("QT_PLUGIN_PATH", "C:\\Surasura\\PyQt6\\plugins")
    monkeypatch.setenv("TCL_LIBRARY", "C:\\Surasura\\tcl")
    process = open_anki.start("日本語の勉強")
    assert process is not None
    seen = _wait_for(out)
    process.wait(timeout=30)
    assert seen["argv"] == ["-p", "日本語の勉強"], "Anki opens on the profile Connect was set up with"
    assert set(seen["env"]) == {"STAND_IN_OUT"}, "none of this program's Python, Qt or Tcl variables reach Anki"


def test_without_a_profile_anki_opens_its_last_one(stand_in):
    _script, out = stand_in
    process = open_anki.start()
    assert _wait_for(out)["argv"] == []
    process.wait(timeout=30)


def test_it_starts_with_no_console_and_breaks_away_from_the_callers_job(stand_in, monkeypatch):
    seen = []

    class Recorded:
        def __init__(self, command, **options):
            seen.append((command, options))
    monkeypatch.setattr(subprocess, "Popen", Recorded)
    open_anki.start("中文")
    command, options = seen[0]
    assert command[-2:] == ["-p", "中文"]
    assert options["stdin"] == options["stdout"] == options["stderr"] == subprocess.DEVNULL
    if sys.platform == "win32":
        flags = options["creationflags"]
        assert flags & open_anki.DETACHED_PROCESS and flags & open_anki.CREATE_NEW_PROCESS_GROUP
        assert flags & open_anki.CREATE_BREAKAWAY_FROM_JOB


def test_a_job_that_forbids_breaking_away_still_starts_anki(stand_in, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows job objects")
    tries = []

    def popen(command, **options):
        tries.append(options["creationflags"])
        if options["creationflags"] & open_anki.CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError(5, "Access is denied")
        return "started"
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert open_anki.start() == "started" and len(tries) == 2


def test_anki_that_cant_start_is_none_never_a_crash(stand_in, monkeypatch):
    def popen(*a, **k):
        raise OSError("not a program")
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert open_anki.start("日本語") is None


def test_windows_looks_in_the_installers_places_then_the_apkg_association(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(open_anki, "_association", lambda: str(tmp_path / "Elsewhere" / "Anki.exe"))
    assert open_anki._windows_places() == [str(tmp_path / "Local" / "Programs" / "Anki" / "anki.exe"),
                                           str(tmp_path / "Program Files" / "Anki" / "anki.exe"),
                                           str(tmp_path / "Elsewhere" / "Anki.exe")]


@pytest.mark.parametrize("command, program", [
    ('"C:\\Users\\学習者\\AppData\\Local\\Programs\\Anki\\Anki.exe" "%1"',
     "C:\\Users\\学習者\\AppData\\Local\\Programs\\Anki\\Anki.exe"),
    ("C:\\Anki\\anki.exe %1", "C:\\Anki\\anki.exe"),
    ('"C:\\Program Files\\7-Zip\\7zFM.exe" "%1"', None),          # .apkg opened by something that isn't Anki
    ("", None),
])
def test_the_apkg_association_names_anki_only_when_it_is_anki(command, program):
    assert open_anki.program_of(command) == program


@pytest.mark.parametrize("listing, answer", [
    (b'"Anki.exe","23536","Console","1","412,000 K"\r\n', True),
    (b"INFO: No tasks are running which match the specified criteria.\r\n", False),
])
def test_running_reads_the_task_list(monkeypatch, listing, answer):
    if sys.platform != "win32":
        pytest.skip("tasklist is Windows'")

    class Done:
        stdout = listing
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert open_anki.running() is answer


def test_running_that_cant_tell_says_so(monkeypatch):
    if sys.platform != "win32":
        assert open_anki.running() is None
        return

    def fails(*a, **k):
        raise OSError("no tasklist")
    monkeypatch.setattr(subprocess, "run", fails)
    assert open_anki.running() is None


def test_the_environment_keeps_everything_else(monkeypatch):
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    monkeypatch.setenv("_MEIPASS2", "C:\\Temp\\_MEI123")
    monkeypatch.setenv("APPDATA", "C:\\Users\\学習者\\AppData\\Roaming")
    env = open_anki.environment()
    assert "_MEIPASS2" not in env and env["APPDATA"].endswith("Roaming") and "PATH" in env
