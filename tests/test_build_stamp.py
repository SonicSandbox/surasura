"""S3.1 row 3.1.8 (D18): the start-up check. A frozen program compares its own version and build id with its folder's
`_internal/build_stamp.json`; the command line refuses a mismatch, and a library store a newer Surasura wrote, with
`version-skew` (exit 2); the window logs it and shows it. Both programs hold the `<data name>.Running` mutex, the
installer's AppMutex. "Frozen" is simulated (sys.frozen, the stamp under the test root, which is the frozen program's
base path in a test); nothing here runs a built program."""
import ctypes
import io
import json
import os
import sqlite3
import subprocess
import sys
import uuid

import pytest

import app_entry
from app import __version__, build_info, library_store, path_utils
from app.cli import __main__ as cli

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = "20261012T080000Z-1a2b3c4d"


def _stamp(root, version=__version__, build_id=BUILD, data_name="Surasura-test"):
    path = os.path.join(root, path_utils.BUILD_STAMP)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"build_id": build_id, "data_name": data_name, "version": version}, f)
    return path


@pytest.fixture
def frozen(monkeypatch):
    """A frozen program of build BUILD whose base path (its `_internal`) is the test root."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(build_info, "BUILD_ID", BUILD)
    monkeypatch.setattr(build_info, "_running", None)
    return os.environ["SURASURA_TEST_ROOT"]


# --- the comparison ---------------------------------------------------------------------------------------------------

def test_from_source_nothing_is_compared_even_beside_another_builds_stamp(monkeypatch):
    # A checkout has no stamp of its own: a stray stamp in the root (another build's) never stops a source run.
    monkeypatch.delattr(sys, "frozen", raising=False)
    _stamp(os.environ["SURASURA_TEST_ROOT"], version="9.9.9", build_id="other")
    assert build_info.stamp_skew() is None


def test_a_frozen_program_and_its_own_stamp_match(frozen):
    _stamp(frozen)
    assert build_info.stamp_skew() is None


def test_another_version_in_the_folder_is_skew_and_says_both(frozen):
    _stamp(frozen, version="3.0.1")
    skew = build_info.stamp_skew()
    assert skew == {"program": {"version": __version__, "build_id": BUILD},
                    "folder": {"version": "3.0.1", "build_id": BUILD}}
    text = build_info.skew_text(skew)
    assert __version__ in text and "3.0.1" in text


def test_the_same_version_from_another_build_is_skew(frozen):
    # Two test builds of one version (an _internal swapped from a rebuild): the build id tells them apart.
    _stamp(frozen, build_id="20261012T090000Z-ffffffff")
    assert build_info.stamp_skew()["folder"]["build_id"] == "20261012T090000Z-ffffffff"


def test_a_frozen_program_with_no_stamp_is_skew(frozen):
    skew = build_info.stamp_skew()
    assert skew["folder"] is None and "no build stamp" in build_info.skew_text(skew)


def test_an_unreadable_stamp_is_skew(frozen):
    with open(os.path.join(frozen, path_utils.BUILD_STAMP), "wb") as f:
        f.write(b"\xff\xfe not json")
    assert build_info.stamp_skew()["folder"] is None


def test_a_frozen_program_without_a_build_id_is_never_a_match(frozen, monkeypatch):
    # A freeze always carries BUILD_ID; one that doesn't can't prove it is its folder's build.
    monkeypatch.setattr(build_info, "BUILD_ID", None)
    _stamp(frozen, build_id=None)
    assert build_info.stamp_skew() is not None


def test_the_packagers_appended_build_id_wins_over_the_sources_none(tmp_path):
    # package_app's _release_flag appends BUILD_ID = "<id>" to app/build_info.py for the freeze: the module then reads
    # that id, not the None the source carries.
    with open(os.path.join(PROJECT_ROOT, "app", "build_info.py"), encoding="utf-8") as f:
        text = f.read()
    assert "BUILD_ID = None" in text and "RELEASE_BUILD = False" in text
    namespace = {}
    exec(compile(text.rstrip("\r\n") + f'\nBUILD_ID = "{BUILD}"\n', "build_info.py", "exec"), namespace)
    assert namespace["BUILD_ID"] == BUILD


# --- the command line -------------------------------------------------------------------------------------------------

def _cli(*argv):
    out = io.StringIO()
    code = cli.main(list(argv), out=out)
    return code, [json.loads(line) for line in out.getvalue().splitlines()]


def test_the_cli_refuses_a_mixed_program_folder_with_version_skew(frozen):
    _stamp(frozen, version="3.0.1")
    code, lines = _cli("_selftest", "ok")
    assert code == 2 and len(lines) == 1
    assert lines[0]["code"] == "version-skew" and lines[0]["folder"]["version"] == "3.0.1"
    assert lines[0]["program"] == {"version": __version__, "build_id": BUILD}


def test_the_cli_answers_version_skew_for_version_too(frozen):
    # The swapper proves an update by `--version`: a mixed folder must never pass that proof with the exe's version.
    _stamp(frozen, build_id="another-build")
    code, lines = _cli("--version")
    assert code == 2 and lines[0]["code"] == "version-skew"


def test_the_cli_runs_when_program_and_stamp_match(frozen):
    _stamp(frozen)
    code, lines = _cli("_selftest", "ok", "--echo", "上層部")
    assert code == 0 and lines[0]["echo"] == "上層部"


def _library_store(language, version):
    """A library store file where this test root's CLI looks for it, at schema `version`."""
    path = library_store.library_db_path(language, path_utils.get_data_path(language))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('migrated_at', '2026-10-12T08:00:00')")
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    return path


def _run_cli(root, *args):
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root))
    environment.pop("PYTHONUTF8", None)
    proc = subprocess.run([sys.executable, "-m", "app.cli", *args], cwd=str(root), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    return proc.returncode, [json.loads(line) for line in proc.stdout.decode("ascii").splitlines()]


def test_a_library_store_from_a_newer_surasura_is_version_skew_and_left_untouched():
    root = os.environ["SURASURA_TEST_ROOT"]
    path = _library_store("zh", library_store.STORE_SCHEMA + 1)
    before = open(path, "rb").read()
    code, lines = _run_cli(root, "_selftest", "ok")
    assert code == 2 and lines[0]["code"] == "version-skew"
    assert lines[0]["language"] == "zh" and lines[0]["store_schema"] == library_store.STORE_SCHEMA + 1
    assert lines[0]["schema"] == library_store.STORE_SCHEMA
    assert open(path, "rb").read() == before and not os.path.exists(path + "-wal")
    code, lines = _run_cli(root, "--version")                      # --version still says what it is
    assert code == 0 and lines[0]["store"] == library_store.STORE_SCHEMA


@pytest.mark.parametrize("offset", [0, -1])
def test_a_library_store_of_this_or_an_older_schema_passes(offset):
    # An older store is the program's own to upgrade, never a refusal.
    _library_store("ja", library_store.STORE_SCHEMA + offset)
    code, _lines = _run_cli(os.environ["SURASURA_TEST_ROOT"], "_selftest", "ok")
    assert code == 0


def test_no_library_store_is_fine(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    code, _lines = _run_cli(root, "_selftest", "ok")
    assert code == 0 and not os.path.isdir(root / "data")         # the check made no data folder ...
    assert not list(root.glob("**/library_*.db"))                  # ... and no library store


# --- the window -------------------------------------------------------------------------------------------------------

def test_the_window_logs_and_shows_a_mixed_folder_and_exits_2(frozen, monkeypatch):
    _stamp(frozen, version="3.0.1")
    shown, logged = [], []
    monkeypatch.setattr(app_entry, "_error_box", lambda title, text: shown.append((title, text)))
    monkeypatch.setattr(app_entry, "log_error", logged.append)
    assert app_entry._start_checks(headless=False) == 2
    assert len(shown) == 1 and "3.0.1" in shown[0][1]
    assert any("version-skew" in line for line in logged)


def test_a_headless_start_never_shows_a_box(frozen, monkeypatch):
    _stamp(frozen, version="3.0.1")
    shown = []
    monkeypatch.setattr(app_entry, "_error_box", lambda title, text: shown.append(text))
    monkeypatch.setattr(app_entry, "log_error", lambda msg: None)
    assert app_entry._start_checks(headless=True) == 2 and shown == []


def test_the_window_goes_on_when_the_stamp_matches(frozen, monkeypatch):
    _stamp(frozen)
    monkeypatch.setattr(app_entry, "_error_box", lambda *a: pytest.fail("no box when the builds match"))
    assert app_entry._start_checks(headless=False) is None


# --- the Running mutex ------------------------------------------------------------------------------------------------

def test_the_mutex_is_named_after_the_data_folder(frozen, monkeypatch):
    # The installer's AppMutex is <data name>.Running: a test build's own name, never the real Surasura's.
    _stamp(frozen, data_name="Surasura-test")
    made = []
    monkeypatch.setattr(build_info, "create_mutex", lambda name: made.append(name) or 1234)
    monkeypatch.setattr(sys, "platform", "win32")
    assert build_info.hold_running_mutex() == 1234
    assert build_info.hold_running_mutex() == 1234 and made == ["Surasura-test.Running"]   # once a process


def test_from_source_no_mutex_is_made(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(build_info, "_running", None)
    monkeypatch.setattr(build_info, "create_mutex", lambda name: pytest.fail("a source run holds no mutex"))
    assert build_info.hold_running_mutex() is None


def test_a_mutex_that_cant_be_made_never_stops_start_up(frozen, monkeypatch):
    _stamp(frozen)

    def broken(name):
        raise OSError("no kernel32 here")
    monkeypatch.setattr(build_info, "create_mutex", broken)
    monkeypatch.setattr(sys, "platform", "win32")
    assert build_info.hold_running_mutex() is None
    assert app_entry._start_checks(headless=True) is None


@pytest.mark.skipif(sys.platform != "win32", reason="named mutexes are Windows")
def test_the_mutex_is_a_real_named_mutex_another_process_can_open():
    # What Inno Setup does with AppMutex: OpenMutexW by name finds it while it is held, and not after.
    name = f"Surasura-pytest-{uuid.uuid4().hex}.Running"
    probe = ("import ctypes,sys; k=ctypes.WinDLL('kernel32'); k.OpenMutexW.restype=ctypes.c_void_p; "
             "h=k.OpenMutexW(0x00100000, False, sys.argv[1]); print(1 if h else 0)")
    handle = build_info.create_mutex(name)
    assert handle
    try:
        seen = subprocess.run([sys.executable, "-c", probe, name], capture_output=True, text=True).stdout.strip()
        assert seen == "1"
    finally:
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(handle))
    seen = subprocess.run([sys.executable, "-c", probe, name], capture_output=True, text=True).stdout.strip()
    assert seen == "0"
