"""S3.1 row 3.1.4 (D7–D10): the swapper — updater_helper.run_folder — replaces the user's installed program.

Every swap here is a real one, on disk: a 3.0.0 program installed in a temp folder with a Japanese name (Inno's
uninstaller and the library's own folders beside it), a signed 3.0.1 release assembled by the app's own
`prepare_update` (tests/update_kit.py), and the swapper run on the marker the app writes. What it asks of Windows —
which processes run from the folder, start the window, is it on screen, what does the command line say — is
`FakeOps` unless a test says otherwise; the stand-in reads the version out of the fake command line's own bytes, so
the proof sees what is really in place. Real processes are used where the guard is about Windows itself: a held file,
a program that won't exit, a window's title, Setup's exit code, the splash.

The uninstall entry is only ever written under a throwaway HKCU key (`update_kit.isolate_registry`), deleted after."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

import updater_helper
from tests import update_kit as kit
from app import path_utils
from app import update_checker
from app import updater

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    """The swapper's waits, short: every test still waits for real, only for less."""
    for name, value in (("POLL", 0.01), ("WINDOW_SETTLE", 0.05), ("WAIT_FOR_WINDOW", 1.0), ("WAIT_TO_UNDO", 0.5),
                        ("RENAME_GAP", 0.01), ("RENAME_TRIES", 5)):
        monkeypatch.setattr(updater_helper, name, value)


# The suite's windows open on a desktop of their own (tests/quiet_windows.py), never on the user's. The splash draws on
# a thread of its own and a child process starts on the user's desktop, so both move there first.
QUIET = ("import sys; sys.path.insert(0, " + repr(PROJECT) + ")\n"
         "from tests import quiet_windows; quiet_windows.quiet_windows()\n"
         "import updater_helper as h\n"
         "def _moved(splash, _real=h._splash_thread):\n"
         "    import ctypes\n"
         "    if quiet_windows._held:\n"
         "        u = ctypes.WinDLL('user32'); u.SetThreadDesktop.argtypes = [ctypes.c_void_p]\n"
         "        u.SetThreadDesktop(quiet_windows._held[0])\n"
         "    _real(splash)\n"
         "h._splash_thread = _moved\n")


@pytest.fixture(autouse=True)
def _splash_on_the_tests_desktop(monkeypatch):
    from tests import quiet_windows
    real = updater_helper._splash_thread

    def moved(splash):
        import ctypes
        if quiet_windows._held:
            user32 = ctypes.WinDLL("user32")
            user32.SetThreadDesktop.argtypes = [ctypes.c_void_p]
            user32.SetThreadDesktop(quiet_windows._held[0])
        real(splash)
    monkeypatch.setattr(updater_helper, "_splash_thread", moved)


@pytest.fixture
def registry(monkeypatch):
    """A throwaway HKCU uninstall root (never the real one) -> make(app_id, app_path, **values); deleted after."""
    import winreg
    root = kit.isolate_registry(monkeypatch)
    assert "SurasuraTests" in root and "Microsoft" not in root
    made = []

    def make(app_id, app_path, **values):
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{root}\\{app_id}_is1")
        made.append(key)
        winreg.SetValueEx(key, "Inno Setup: App Path", 0, winreg.REG_SZ, str(app_path))
        for name, value in values.items():
            kind = winreg.REG_SZ if isinstance(value, str) else winreg.REG_DWORD
            winreg.SetValueEx(key, name.replace("_", " "), 0, kind, value)
        return f"{root}\\{app_id}_is1"
    yield make
    for key in made:
        key.Close()
    _delete_tree(winreg, root.rsplit("\\", 1)[0])           # Software\SurasuraTests\<id>
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\SurasuraTests")
    except OSError:
        pass


def _delete_tree(winreg, path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            names = []
            while True:
                try:
                    names.append(winreg.EnumKey(key, len(names)))
                except OSError:
                    break
        for name in names:
            _delete_tree(winreg, f"{path}\\{name}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def _values(path):
    import winreg
    out = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        i = 0
        while True:
            try:
                name, value, _kind = winreg.EnumValue(key, i)
            except OSError:
                return out
            out[name] = value
            i += 1


@pytest.fixture(autouse=True)
def runonce(monkeypatch):
    """Installer mode's recovery entry (S3.1-5) goes under a throwaway HKCU key, never the user's RunOnce: the variable
    reaches the swapper in this process and in a child; the key is deleted after. -> its path."""
    import uuid
    import winreg
    base = rf"Software\SurasuraTests\{uuid.uuid4().hex}"
    monkeypatch.setenv(updater_helper.TEST_RUNONCE_ENV, rf"{base}\RunOnce")
    assert updater_helper._runonce_root() == rf"{base}\RunOnce"
    yield rf"{base}\RunOnce"
    _delete_tree(winreg, base)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\SurasuraTests")
    except OSError:
        pass


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """3.0.0 installed, 3.0.1 assembled -> (install folder, marker as the app built it, the install's tree)."""
    kit.isolate_registry(monkeypatch)
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    marker = updater.prepare_update(update_checker.get_update_info())
    return root, marker, kit.tree(root)


def _run(marker, ops):
    path = updater.write_marker(marker)
    code = updater_helper.run(path, ops=ops)
    with open(updater.result_path(), "r", encoding="utf-8") as f:
        result = json.load(f)
    assert not os.path.exists(path), "the marker goes, success or not"
    return code, result


def _program_part(tree_):
    return {p: s for p, s in tree_.items() if not p.startswith(tuple(kit.FOREIGN)) and not p.startswith("unins")}


def _foreign(tree_):
    return {p: s for p, s in tree_.items() if p in kit.FOREIGN}


# --- the swap ------------------------------------------------------------------------------------------------------

def test_a_swap_installs_exactly_the_release_and_keeps_every_foreign_file(staged, monkeypatch):
    root, marker, before = staged
    inodes = {p: os.stat(root / p).st_ino for p in kit.FOREIGN}
    moved = []
    real_rename = updater_helper._rename
    monkeypatch.setattr(updater_helper, "_rename", lambda s, d, sleep=None: moved.append(s) or real_rename(s, d))
    ops = kit.FakeOps(window=1)
    code, result = _run(marker, ops)

    assert code == 0 and result["status"] == "success" and result["to"] == kit.NEW and result["from"] == kit.OLD
    after = kit.tree(root)
    assert _program_part(after) == kit.digests(kit.program(kit.NEW)), "the installed bytes are the release's"
    assert "_internal/old_only.dll" not in after and "UPDATE_INSTRUCTIONS.md" not in after, "stale files go"
    assert _foreign(after) == _foreign(before) and {p: os.stat(root / p).st_ino for p in kit.FOREIGN} == inodes
    assert not any(os.path.basename(s) in ("unins000.exe", "unins000.dat", "User Files", "data", "results",
                                           "settings.json") for s in moved), "never moved"
    # the old program kept whole for Go back, with its own list; the stage emptied and gone
    previous = os.path.join(updater.previous_root(), kit.OLD)
    assert kit.tree(previous) == kit.digests(kit.old_program())
    with open(previous + ".files.json", encoding="utf-8") as f:
        assert json.load(f) == kit.digests(kit.old_program())
    assert not os.path.exists(marker["staged"])
    # the window it started is the NEW one, and the old one was never started again
    assert [exe for exe, _b in ops.started] == [str(root / "Surasura.exe")]
    assert ops.started[0][1] == kit.program(kit.NEW)["Surasura.exe"]


def test_a_headless_swap_is_proven_by_its_files_and_command_line_alone(staged, monkeypatch):
    root, marker, _before = staged
    marker["window"] = False
    shown = []
    monkeypatch.setattr(updater_helper, "show_splash", lambda *a, **k: shown.append(a))
    ops = kit.FakeOps(window=None)
    code, result = _run(marker, ops)
    assert code == 0 and result["status"] == "success" and ops.started == [] and shown == [], \
        "nothing started, no splash: nobody is watching"
    assert _program_part(kit.tree(root)) == kit.digests(kit.program(kit.NEW))


def test_the_person_closing_the_new_window_at_once_is_a_success(staged):
    root, marker, _before = staged
    code, result = _run(marker, kit.FakeOps(window=0, exits=2, code=0))
    assert result["status"] == "success"


# --- every way it can fail puts the old program back ---------------------------------------------------------------------

FAILURES = {
    "a staged file damaged after its check": "staged_damage",
    "the command line reports another version": "version",
    "the command line doesn't run": "no_version",
    "the window never shows": "no_window",
    "the window closes on a crash as it opens": "crash_at_once",
    "the window crashes during its settle": "crash_in_settle",
}


@pytest.mark.parametrize("failure", sorted(FAILURES))
def test_a_failed_proof_puts_the_old_program_back_and_starts_it(staged, failure):
    root, marker, before = staged
    kind = FAILURES[failure]
    ops = {"version": kit.FakeOps(version="2.9.9"), "no_version": kit.FakeOps(version=""),
           "no_window": kit.FakeOps(window=None), "crash_at_once": kit.FakeOps(window=None, exits=0, code=3221226505),
           "crash_in_settle": kit.FakeOps(window=0, exits=2, code=1)}.get(kind, kit.FakeOps())
    if kind == "staged_damage":
        with open(os.path.join(marker["staged"], "_internal", "templates", "web_app.html"), "ab") as f:
            f.write("改ざん".encode("utf-8"))
    code, result = _run(marker, ops)

    assert code == 2 and result["status"] == "failed" and result["touched"] is True
    assert kit.tree(root) == before, "every move undone: the install is byte-identical"
    assert not os.path.exists(os.path.join(updater.previous_root(), kit.OLD)), "nothing kept: the old one is back"
    restarted = [b for exe, b in ops.started if b == kit.old_program()["Surasura.exe"]]
    assert len(restarted) == 1, "the old version started again"
    if kind in ("crash_at_once", "crash_in_settle", "no_window"):
        assert ops.processes[0].stopped or ops.processes[0].poll() is not None, "the new window ended first"
    assert "could not be put back" not in result["reason"]


@pytest.mark.parametrize("nth", range(1, 12))
def test_a_rename_failing_at_any_step_is_undone(staged, monkeypatch, nth):
    """The n-th rename of the swap fails (out to previous, or in from the stage): every move before it goes back."""
    root, marker, before = staged
    real_rename, calls = os.rename, []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == nth:
            raise PermissionError(13, "simulated: held by another process", src)
        return real_rename(src, dst)
    monkeypatch.setattr(updater_helper.os, "rename", flaky)
    monkeypatch.setattr(updater_helper, "RENAME_TRIES", 1)
    code, result = _run(marker, kit.FakeOps())
    monkeypatch.setattr(updater_helper.os, "rename", real_rename)
    assert result["status"] == "failed" and "could not be moved" in result["reason"]
    assert kit.tree(root) == before


def test_a_rename_held_briefly_is_retried_and_succeeds(staged, monkeypatch):
    """Antivirus scanning a new file holds it for a moment: the rename is tried again, the swap completes."""
    root, marker, _before = staged
    real_rename, refused = os.rename, []

    def busy_once(src, dst):
        if not refused:
            refused.append(src)
            raise PermissionError(32, "simulated: being scanned", src)
        return real_rename(src, dst)
    monkeypatch.setattr(updater_helper.os, "rename", busy_once)
    code, result = _run(marker, kit.FakeOps())
    assert result["status"] == "success" and len(refused) == 1


def test_a_staged_file_held_open_is_retried_then_everything_rolled_back(staged):
    """A real open handle on a file inside the staged _internal: Windows refuses to move the folder. After its
    retries the swap undoes the moves already made (the old entries went to previous) and leaves the install as it
    was."""
    root, marker, before = staged
    held = open(os.path.join(marker["staged"], "_internal", "python311.dll"), "rb")
    try:
        code, result = _run(marker, kit.FakeOps())
    finally:
        held.close()
    assert result["status"] == "failed" and "PermissionError" in result["reason"]
    assert kit.tree(root) == before


def test_a_file_held_open_then_let_go_during_the_retries_lands(staged, monkeypatch):
    root, marker, _before = staged
    monkeypatch.setattr(updater_helper, "RENAME_TRIES", 200)
    held = open(os.path.join(marker["staged"], "_internal", "python311.dll"), "rb")
    threading.Timer(0.3, held.close).start()
    code, result = _run(marker, kit.FakeOps())
    held.close()
    assert result["status"] == "success"
    assert _program_part(kit.tree(root)) == kit.digests(kit.program(kit.NEW))


def test_a_rollback_that_cant_put_an_entry_back_says_so(staged, monkeypatch):
    root, marker, _before = staged
    real_rename = os.rename

    def stuck(src, dst):
        if os.path.basename(src) == "README.md" and "previous" in src:     # coming back from previous
            raise PermissionError(5, "simulated: locked for good", src)
        return real_rename(src, dst)
    monkeypatch.setattr(updater_helper.os, "rename", stuck)
    monkeypatch.setattr(updater_helper, "RENAME_TRIES", 1)
    code, result = _run(marker, kit.FakeOps(version="2.9.9"))
    assert result["status"] == "failed" and "1 item(s) could not be put back" in result["reason"]


# --- the wait: never ends a process -------------------------------------------------------------------------------

def test_a_program_still_running_from_the_folder_abandons_the_update_untouched(staged, tmp_path):
    """A real process whose program lives in the install folder, and won't exit: after the wait the update is
    abandoned — nothing moved, nothing ended — and the old window started again."""
    root, marker, before = staged
    helper = root / "helpers" / "stubborn.exe"
    helper.parent.mkdir()
    shutil.copy(kit.PYTHON, helper)
    go = tmp_path / "go"
    proc = subprocess.Popen([str(helper), "-c", "import os, time\n"
                             f"while not os.path.exists({str(go)!r}): time.sleep(0.05)"])
    try:
        real = updater_helper.WinOps()
        deadline = time.monotonic() + 10
        while proc.pid not in real.processes_in(str(root)) and time.monotonic() < deadline:
            time.sleep(0.05)
        ops = kit.FakeOps(running=real.processes_in)
        marker["wait_timeout"] = 0.5
        before = kit.tree(root)
        code, result = _run(marker, ops)
        assert result["status"] == "failed" and "still running" in result["reason"] and result["touched"] is False
        assert proc.poll() is None, "never ended"
        assert ops.stopped_pids == []
        assert kit.tree(root) == before and os.path.isdir(marker["staged"]), "nothing moved; the stage kept"
        assert [b for _e, b in ops.started] == [kit.old_program()["Surasura.exe"]]
    finally:
        go.write_text("", encoding="utf-8")
        proc.wait(timeout=10)


def test_a_program_that_ends_during_the_wait_lets_the_swap_go_ahead(staged):
    root, marker, _before = staged
    looks = []
    ops = kit.FakeOps(running=lambda folder: looks.append(folder) or ([4242] if len(looks) < 4 else []))
    code, result = _run(marker, ops)
    assert result["status"] == "success" and len(looks) >= 4


def test_what_the_new_version_started_is_ended_before_the_moves_go_back(staged):
    """After a failed proof, a process running from the folder is the new version's (the folder was free when the
    swap began): it is ended so the old entries can come back."""
    root, marker, before = staged
    calls = []

    def running(folder):
        calls.append(1)
        return [] if len(calls) == 1 else [5151]              # free at the wait; the new window's child after
    ops = kit.FakeOps(running=running, version="2.9.9")
    code, result = _run(marker, ops)
    assert result["status"] == "failed" and 5151 in ops.stopped_pids


def test_the_real_listing_finds_a_program_in_the_folder_and_nothing_outside_it(tmp_path):
    folder = tmp_path / "スラスラ" / "_internal"
    folder.mkdir(parents=True)
    exe = folder.parent / "helpers" / "Surasura.exe"
    exe.parent.mkdir()
    shutil.copy(kit.PYTHON, exe)
    go = tmp_path / "go"
    proc = subprocess.Popen([str(exe), "-c", "import os, time\n"
                             f"while not os.path.exists({str(go)!r}): time.sleep(0.05)"])
    try:
        ops = updater_helper.WinOps()
        deadline = time.monotonic() + 10
        while proc.pid not in ops.processes_in(str(folder.parent)) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert proc.pid in ops.processes_in(str(folder.parent))
        assert proc.pid not in ops.processes_in(str(folder)), "a sibling folder holds it, not this one"
        assert proc.pid not in ops.processes_in(str(tmp_path / "スラ")), "a folder whose name it merely starts with"
        assert os.getpid() not in ops.processes_in(os.path.dirname(kit.PYTHON)), "never itself"
    finally:
        go.write_text("", encoding="utf-8")
        proc.wait(timeout=10)


# --- the proof, by Windows itself ------------------------------------------------------------------------------------

def test_the_window_proof_needs_surasuras_title(tmp_path):
    """A real window: titled as Surasura's, it counts; a crash dialog's title, visible all the same, doesn't."""
    script = QUIET + ("import tkinter as tk\nroot = tk.Tk()\nroot.title(sys.argv[1])\nroot.geometry('200x80+40+40')\n"
                      "root.after(6000, root.destroy)\nroot.mainloop()\n")
    ops = updater_helper.WinOps()
    for title, counts in (("Surasura — The Immersion Architect", True), ("Unhandled exception in script", False),
                          ("Surasura - Immersion Architect Dashboard v3.0.1", True), ("Surasurana", False)):
        proc = subprocess.Popen([kit.PYTHON, "-c", script, title])
        try:
            deadline, seen = time.monotonic() + 15, False
            while time.monotonic() < deadline and not seen:
                seen = bool(updater_helper._visible_titles(proc.pid))
                time.sleep(0.05)
            assert seen, "the test window never showed"
            assert ops.window_visible(proc.pid) is counts, title
        finally:
            proc.kill()
            proc.wait(timeout=10)


def test_the_command_line_proof_reads_its_result_line(tmp_path):
    cli = tmp_path / "cli.cmd"
    cli.write_text('@echo {"type":"result","contract":1,"ok":true,"app":"3.0.1","engine":20}\r\n', encoding="ascii")
    assert updater_helper.WinOps().version(str(cli)) == "3.0.1"
    cli.write_text("@echo Python 3.11.2\r\n", encoding="ascii")
    assert updater_helper.WinOps().version(str(cli)) is None
    assert updater_helper.WinOps().version(str(tmp_path / "missing.exe")) is None


def test_a_real_swapper_process_puts_back_a_version_whose_command_line_wont_run(staged):
    """The swapper as its own process (python updater_helper.py --marker …), real Windows calls throughout: the fake
    command line can't run, so the proof fails and every move goes back."""
    root, marker, before = staged
    marker["window"] = False
    path = updater.write_marker(marker)
    done = subprocess.run([kit.PYTHON, os.path.join(PROJECT, "updater_helper.py"), "--marker", path],
                          capture_output=True, timeout=120, cwd=updater.update_dir())
    assert done.returncode == 2, done.stderr.decode("utf-8", "replace")
    with open(updater.result_path(), encoding="utf-8") as f:
        result = json.load(f)
    assert result["status"] == "failed" and "did not start" in result["reason"]
    assert kit.tree(root) == before


# --- a marker the app didn't write -----------------------------------------------------------------------------------

@pytest.mark.parametrize("change", ["staged outside", "previous outside", "install inside", "install missing",
                                    "owns User Files", "owns the uninstaller", "stage is previous",
                                    "previous inside the stage", "no version"])
def test_a_marker_reaching_outside_surasuras_folders_changes_nothing(staged, tmp_path, change):
    root, marker, before = staged
    elsewhere = str(tmp_path / "elsewhere")
    if change == "staged outside":
        marker["staged"] = elsewhere
    elif change == "previous outside":
        marker["previous"] = os.path.join(elsewhere, kit.OLD)
    elif change == "install inside":
        marker["install"] = os.path.join(updater.update_dir(), "x")
        os.makedirs(marker["install"])
    elif change == "install missing":
        marker["install"] = os.path.join(elsewhere, "nope")
    elif change == "owns User Files":
        marker["owned"] = marker["owned"] + ["User Files"]
    elif change == "owns the uninstaller":
        marker["owned"] = marker["owned"] + ["unins000.dat"]
    elif change == "stage is previous":
        marker["previous"] = marker["staged"]
    elif change == "previous inside the stage":
        # Inside the update folder, its parent too: only the overlap check refuses it. "stage is previous" is refused
        # earlier (its parent is the update folder itself), so with the overlap check gone (mutant H05) it still passed.
        marker["previous"] = os.path.join(marker["staged"], kit.OLD)
    else:
        marker["target_version"] = ""
    ops = kit.FakeOps()
    code, result = _run(marker, ops)
    assert result["status"] == "failed" and "were not Surasura's" in result["reason"]
    assert kit.tree(root) == before and ops.started == [], "nothing touched, nothing started"


def test_a_result_path_outside_the_update_folder_is_never_written(staged, tmp_path):
    """The result goes where the marker says only inside the update folder; elsewhere, beside the marker."""
    root, marker, _before = staged
    outside = tmp_path / "elsewhere" / "result.json"
    outside.parent.mkdir()
    marker["result_path"] = str(outside)
    path = updater.write_marker(marker)
    assert updater_helper.run(path, ops=kit.FakeOps()) == 0
    assert not outside.exists()
    with open(path + ".result", encoding="utf-8") as f:
        assert json.load(f)["status"] == "success"


# --- one previous version, and Go back -----------------------------------------------------------------------------------

def test_only_one_previous_version_is_kept(staged):
    root, marker, _before = staged
    kit.write_tree(updater.previous_root(), {"2.9.9/Surasura.exe": b"MZ older", "2.9.9.files.json": b"{}",
                                             f"{kit.OLD}/Surasura.exe": b"MZ a stale copy of the same version"})
    code, result = _run(marker, kit.FakeOps())
    assert result["status"] == "success"
    assert sorted(os.listdir(updater.previous_root())) == [kit.OLD, f"{kit.OLD}.files.json"]
    assert kit.tree(os.path.join(updater.previous_root(), kit.OLD)) == kit.digests(kit.old_program())


def test_a_failure_keeps_the_versions_that_were_kept(staged):
    root, marker, _before = staged
    kit.write_tree(updater.previous_root(), {"2.9.9/Surasura.exe": b"MZ older"})
    code, result = _run(marker, kit.FakeOps(version="2.9.9"))
    assert result["status"] == "failed" and os.listdir(updater.previous_root()) == ["2.9.9"]


def test_go_back_round_trip(staged, monkeypatch):
    """3.0.0 -> 3.0.1, then Go back to 3.0.0 (proven by its kept list), then Go back again to 3.0.1: each time the
    folder holds exactly that version, the foreign files untouched, and the other version kept."""
    root, marker, before = staged
    assert _run(marker, kit.FakeOps())[1]["status"] == "success"
    monkeypatch.setattr(updater, "__version__", kit.NEW)
    assert updater.previous_version() == kit.OLD

    back = updater.prepare_go_back()
    assert back["going_back"] and back["target_version"] == kit.OLD and back["from_version"] == kit.NEW
    assert back["swapper"] == str(root / "updater.exe"), "this version's own swapper goes back"
    assert back["files"] == kit.digests(kit.old_program())
    code, result = _run(back, kit.FakeOps())
    assert result["status"] == "success" and result["going_back"] is True
    assert kit.tree(root) == before, "exactly 3.0.0 again, stale files and all"
    assert sorted(os.listdir(updater.previous_root())) == [kit.NEW, f"{kit.NEW}.files.json"]

    monkeypatch.setattr(updater, "__version__", kit.OLD)
    assert updater.previous_version() == kit.NEW
    code, result = _run(updater.prepare_go_back(), kit.FakeOps())
    assert result["status"] == "success"
    assert _program_part(kit.tree(root)) == kit.digests(kit.program(kit.NEW))
    assert updater.previous_version() == kit.OLD


def test_go_back_with_a_damaged_kept_copy_is_put_back(staged, monkeypatch):
    root, marker, _before = staged
    assert _run(marker, kit.FakeOps())[1]["status"] == "success"
    monkeypatch.setattr(updater, "__version__", kit.NEW)
    with open(os.path.join(updater.previous_root(), kit.OLD, "_internal", "sqlite3.dll"), "ab") as f:
        f.write(b"bit rot")
    now = kit.tree(root)
    code, result = _run(updater.prepare_go_back(), kit.FakeOps())
    assert result["status"] == "failed" and "sqlite3.dll" in result["reason"]
    assert kit.tree(root) == now and updater.previous_version() == kit.OLD


def test_go_back_needs_a_kept_version_and_an_installed_program(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    with pytest.raises(updater.UpdateError, match="no earlier version"):
        updater.prepare_go_back()
    kit.write_tree(updater.previous_root(), {"2.9.9/Surasura.exe": b"MZ"})
    monkeypatch.setattr(path_utils, "installed_library", lambda: None)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(tmp_path / "Programs" / "スラスラ 本番"))
    os.remove(tmp_path / "Programs" / "スラスラ 本番" / "unins000.dat")
    with pytest.raises(updater.UpdateError, match="only an installed"):
        updater.prepare_go_back()


# --- the uninstall entry (D8) ------------------------------------------------------------------------------------------

def test_the_uninstall_entry_follows_a_proven_swap_under_its_own_key_only(staged, registry):
    root, marker, _before = staged
    mine = registry("{SURASURA-TEST-1}", root, DisplayVersion=kit.OLD, Inno_Setup_App_Path_Extra="kept")
    other = registry("{SURASURA-TEST-2}", root.parent / "elsewhere", DisplayVersion="1.0.0")
    assert updater.uninstall_app_id(str(root)) == "{SURASURA-TEST-1}"
    marker["app_id"] = "{SURASURA-TEST-1}"
    code, result = _run(marker, kit.FakeOps())
    assert result["status"] == "success"
    values = _values(mine)
    assert values["DisplayVersion"] == kit.NEW
    assert (values["MajorVersion"], values["MinorVersion"], values["VersionMajor"], values["VersionMinor"]) == \
        (3, 0, 3, 0)
    assert values["EstimatedSize"] >= 1
    assert values["Inno Setup: App Path"] == str(root) and values["Inno Setup App Path Extra"] == "kept"
    assert _values(other) == {"Inno Setup: App Path": str(root.parent / "elsewhere"), "DisplayVersion": "1.0.0"}


def test_the_uninstall_entry_is_never_written_for_another_folder_or_made(staged, registry):
    root, marker, _before = staged
    path = registry("{SURASURA-TEST-3}", root.parent / "another copy", DisplayVersion=kit.OLD)
    assert updater_helper.write_uninstall_version("{SURASURA-TEST-3}", str(root), kit.NEW) is False
    assert _values(path)["DisplayVersion"] == kit.OLD
    assert updater_helper.write_uninstall_version("{SURASURA-NOT-THERE}", str(root), kit.NEW) is False
    import winreg
    with pytest.raises(OSError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, path.replace("TEST-3", "NOT-THERE"))
    for bad in ("..\\..\\Run", "a/b", ""):
        assert updater_helper.write_uninstall_version(bad, str(root), kit.NEW) is False


def test_an_app_id_holding_a_path_never_reaches_a_key_below_another(tmp_path, registry):
    """The AppId comes from the marker. One holding a backslash would address a key below another entry: refused by
    its shape, even when that key exists and names this install. (The cases above fail only because no such key
    exists, so with the shape check gone — mutant H21 — they still passed.)"""
    root = tmp_path / "スラスラ 本番"
    root.mkdir()
    outer = registry("{SURASURA-TEST-6}", root, DisplayVersion=kit.OLD)
    nested = registry("{SURASURA-TEST-6}_is1\\{SURASURA-TEST-7}", root, DisplayVersion=kit.OLD)
    assert updater_helper.write_uninstall_version("{SURASURA-TEST-6}_is1\\{SURASURA-TEST-7}", str(root),
                                                  kit.NEW) is False
    assert _values(nested)["DisplayVersion"] == kit.OLD and _values(outer)["DisplayVersion"] == kit.OLD
    assert updater_helper.write_uninstall_version("{SURASURA-TEST-6}", str(root), kit.NEW) is True, \
        "the same install under a plain AppId is written: only the shape refused the other"


def test_a_failed_swap_leaves_the_uninstall_entry_alone(staged, registry):
    root, marker, _before = staged
    path = registry("{SURASURA-TEST-4}", root, DisplayVersion=kit.OLD)
    marker["app_id"] = "{SURASURA-TEST-4}"
    code, result = _run(marker, kit.FakeOps(version="2.9.9"))
    assert result["status"] == "failed" and _values(path)["DisplayVersion"] == kit.OLD


# --- installer mode (D7) -------------------------------------------------------------------------------------------

def _stub_setup(tmp_path, code):
    """A real program that ends with `code` — Setup's stand-in (cmd's exit /b), in an ASCII path cmd reads."""
    stub = tmp_path / f"stub-{code}.cmd"
    stub.write_text(f"@exit /b {code}\r\n", encoding="ascii")
    return str(stub)


@pytest.mark.skipif(sys.platform != "win32", reason="Setup runs on Windows")
def test_a_setup_past_its_time_is_ended_with_every_process_it_started(tmp_path, monkeypatch):
    """Inno's setup.exe runs its installer as a child: past SETUP_TIMEOUT the whole tree is ended, so nothing of it
    still writes into the program folder while the old program is put back (ending the parent alone left the child)."""
    pid_file = str(tmp_path / "child.pid")
    child = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(120)"
    parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}, {pid_file!r}]); " \
             "time.sleep(120)"
    monkeypatch.setattr(updater_helper, "SETUP_TIMEOUT", 8.0)
    started = time.monotonic()
    assert updater_helper.WinOps().run_setup([sys.executable, "-c", parent]) is None
    assert time.monotonic() - started < 60
    with open(pid_file, encoding="utf-8") as f:
        pid = int(f.read())
    deadline = time.monotonic() + 10
    while pid in updater_helper._process_images() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert pid not in updater_helper._process_images(), "Setup's own child is ended too"


@pytest.fixture
def installer_marker(tmp_path, monkeypatch):
    kit.isolate_registry(monkeypatch)
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch, installer=b"MZ\x90\x00stub Setup", needs_installer=True)
    return root, updater.prepare_installer(update_checker.get_update_info()), kit.tree(root)


@pytest.mark.parametrize("code", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, -1])
def test_installer_mode_maps_every_setup_exit_code(installer_marker, tmp_path, code):
    """Setup writes the new program into the emptied folder (as Inno does) and ends with `code`: 0 is proven like a
    swap; 1-8 are Setup's own failures, named; anything else is a failure too — and every failure takes Setup's
    files away and puts the old program back."""
    root, marker, before = installer_marker
    stub = _stub_setup(tmp_path, code)

    def setup(argv):
        kit.write_tree(root, kit.program(kit.NEW))
        return updater_helper.WinOps().run_setup([stub, *argv[1:]])
    ops = kit.FakeOps(setup=setup)
    rc, result = _run(marker, ops)

    assert ops.setup_argv[:5] == [marker["setup"], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                  "/NOCLOSEAPPLICATIONS"]
    assert f"/LIBRARY={path_utils.installed_library()}" in ops.setup_argv
    assert f"/LOG={os.path.join(updater.update_dir(), 'setup-' + kit.NEW + '.log')}" in ops.setup_argv
    if code == 0:
        assert result["status"] == "success"
        after = kit.tree(root)
        assert _program_part(after) == kit.digests(kit.program(kit.NEW)) and _foreign(after) == _foreign(before)
        assert "_internal/old_only.dll" not in after, "Setup wrote into an emptied folder: stale files gone"
        assert kit.tree(os.path.join(updater.previous_root(), kit.OLD)) == kit.digests(kit.old_program())
    else:
        assert result["status"] == "failed"
        expected = updater_helper.SETUP_EXIT.get(code, "Setup ended with code ")     # -1 reads as 4294967295
        assert result["reason"].startswith(expected)
        assert kit.tree(root) == before, "Setup's files gone, the old program back"
        assert [b for _e, b in ops.started] == [kit.old_program()["Surasura.exe"]]


def test_installer_mode_failing_its_proof_after_setup_is_put_back_and_the_entry_too(installer_marker, registry):
    root, marker, before = installer_marker
    path = registry("{SURASURA-TEST-5}", root, DisplayVersion=kit.OLD)
    marker["app_id"] = "{SURASURA-TEST-5}"

    def setup(argv):                                      # Inno rewrites the entry as it installs
        kit.write_tree(root, kit.program(kit.NEW))
        updater_helper.write_uninstall_version("{SURASURA-TEST-5}", str(root), kit.NEW)
        return 0
    rc, result = _run(marker, kit.FakeOps(setup=setup, window=None))
    assert result["status"] == "failed" and "did not open its window" in result["reason"]
    assert kit.tree(root) == before
    assert _values(path)["DisplayVersion"] == kit.OLD, "the entry names the version that is back"


def test_installer_mode_proves_what_setup_installed_by_the_releases_list(installer_marker):
    root, marker, before = installer_marker

    def setup(argv):                                      # Setup "succeeds" but lays down a file of another build
        files = kit.program(kit.NEW)
        files["_internal/jieba/dict.txt"] = "开心 3 a\n".encode("utf-8")
        kit.write_tree(root, files)
        return 0
    rc, result = _run(marker, kit.FakeOps(setup=setup))
    assert result["status"] == "failed" and "dict.txt" in result["reason"]
    assert kit.tree(root) == before


def test_installer_mode_with_a_setup_that_cant_start_changes_nothing_lasting(installer_marker):
    root, marker, before = installer_marker
    rc, result = _run(marker, kit.FakeOps(setup=lambda argv: None))
    assert result["status"] == "failed" and "could not be run" in result["reason"]
    assert kit.tree(root) == before


def test_installer_mode_with_its_installer_gone_touches_nothing(installer_marker):
    root, marker, before = installer_marker
    os.remove(marker["setup"])
    ops = kit.FakeOps()
    rc, result = _run(marker, ops)
    assert result["status"] == "failed" and result["touched"] is False and ops.setup_argv is None
    assert kit.tree(root) == before


# --- the hand-over: the new swapper, copied out -------------------------------------------------------------------------

def test_arm_and_launch_runs_the_new_releases_swapper_from_the_update_folder(staged, monkeypatch):
    root, marker, _before = staged
    seen = []

    class _Started:
        pid = 777

    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: seen.append((args, kw)) or _Started())
    started = updater.arm_and_launch(marker)
    [(args, kw)] = seen
    copy = os.path.join(updater.swapper_dir(), f"updater-{kit.NEW}.exe")
    assert args == [copy, "--marker", updater.marker_path()] and started.pid == 777
    assert open(copy, "rb").read() == kit.program(kit.NEW)["updater.exe"], "the NEW version's swapper"
    assert kw["cwd"] == updater.swapper_dir() and kw["creationflags"] & 0x00000008
    with open(updater.marker_path(), encoding="utf-8") as f:
        assert json.load(f)["target_version"] == kit.NEW


def test_arm_and_launch_arms_nothing_when_the_swapper_cant_start(staged, monkeypatch):
    root, marker, _before = staged

    def refused(args, **kw):
        raise OSError(1260, "This program is blocked by group policy")
    monkeypatch.setattr(updater.subprocess, "Popen", refused)
    with pytest.raises(OSError):
        updater.arm_and_launch(marker)
    assert not os.path.exists(updater.marker_path())
    os.remove(marker["swapper"])
    with pytest.raises(updater.UpdateError, match="missing"):
        updater.arm_and_launch(marker)
    assert not os.path.exists(updater.marker_path())


def test_a_running_swapper_copy_gets_a_name_of_its_own(staged, monkeypatch):
    root, marker, _before = staged
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: args)
    os.makedirs(updater.swapper_dir(), exist_ok=True)
    busy = os.path.join(updater.swapper_dir(), f"updater-{kit.NEW}.exe")
    with open(busy, "wb") as f:
        f.write(b"MZ an earlier copy")
    real_replace = os.replace

    def held(src, dst):
        if os.path.normcase(dst) == os.path.normcase(busy):
            raise PermissionError(32, "running", dst)
        return real_replace(src, dst)
    monkeypatch.setattr(updater.os, "replace", held)
    args = updater.arm_and_launch(marker)
    assert args[0] != busy and os.path.basename(args[0]).startswith(f"updater-{kit.NEW}-")


# --- the splash (D10) ----------------------------------------------------------------------------------------------

def test_the_splash_is_drawn_and_found_by_its_process():
    splash = updater_helper.show_splash(kit.NEW)
    try:
        assert splash.drawn.is_set()
        assert updater.splash_on_screen(os.getpid()) is True
        assert updater.wait_for_splash(os.getpid(), timeout=0.5) is True
        assert updater.splash_on_screen(os.getpid() + 1_000_000) is False, "another process's splash never counts"
    finally:
        splash.close()
    deadline = time.monotonic() + 3
    while updater.splash_on_screen(os.getpid()) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert updater.splash_on_screen(os.getpid()) is False


def test_a_splash_drawn_by_a_child_of_the_swapper_counts(tmp_path):
    """A onefile updater.exe runs its code in a child process: the splash belongs to the child, the Popen's pid is
    the parent's."""
    child = QUIET + "import time\ns = h.show_splash('3.0.1'); time.sleep(4); s.close()\n"
    parent = f"import subprocess, sys; subprocess.run([sys.executable, '-c', {child!r}])"
    proc = subprocess.Popen([kit.PYTHON, "-c", parent])
    try:
        assert updater.wait_for_splash(proc.pid, timeout=8) is True
    finally:
        proc.wait(timeout=20)


def test_an_undrawable_splash_never_stops_the_update(staged, monkeypatch):
    def broken():
        raise OSError("no desktop to draw on")
    monkeypatch.setattr(updater_helper, "_win32", broken)
    splash = updater_helper.show_splash(kit.NEW, wait=0.5)
    assert not splash.drawn.is_set()
    splash.close()
    root, marker, _before = staged
    code, result = _run(marker, kit.FakeOps())
    assert result["status"] == "success"


def test_the_splash_goes_at_the_first_sight_of_the_new_window(staged, monkeypatch):
    root, marker, _before = staged
    shown = []
    real = updater_helper.show_splash

    def spy(version, going_back=False, wait=3.0):
        splash = real(version, going_back, wait)
        shown.append((version, going_back, splash))
        return splash
    monkeypatch.setattr(updater_helper, "show_splash", spy)
    ops = kit.FakeOps(window=2)
    closed_at = []
    real_proven = updater_helper._proven

    def proven(m, process, ops_, clock, sleep, seen):
        return real_proven(m, process, ops_, clock, sleep, lambda: (closed_at.append(ops_.looks), seen()))
    monkeypatch.setattr(updater_helper, "_proven", proven)
    code, result = _run(marker, ops)
    assert result["status"] == "success" and shown[0][:2] == (kit.NEW, False)
    assert closed_at == [3] and shown[0][2].closing is not None


def test_the_selftest_draws_and_finds_its_splash(tmp_path):
    """`updater.exe --selftest out.json` (the frozen build's proof, row 3.1.4) — here through main(), in this process,
    so the card is drawn on the tests' desktop."""
    out = tmp_path / "selftest.json"
    assert updater_helper.main(["--selftest", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["splash"] == "SurasuraUpdateSplash" and report["drawn"] is True and report["found"] is True


def test_the_splash_colours_come_from_one_table():
    """Re-skinning (Sonic's 3.0 theme) is one table: today's palette, and no other colour in the swapper."""
    assert updater_helper.SPLASH_COLOURS["bg"] == (0x1E, 0x1E, 0x1E)
    assert updater_helper.SPLASH_COLOURS["surface"] == (0x2D, 0x2D, 0x2D)
    assert updater_helper.SPLASH_COLOURS["text"] == (0xE0, 0xE0, 0xE0)
    assert updater_helper.SPLASH_COLOURS["accent"] == (0xBB, 0x86, 0xFC)
    pixels, alphas = updater_helper.card_pixels(60, 30, 8)
    assert alphas[0] == 0 and alphas[30 * 15 + 30] == 255, "rounded: a corner clear, the middle solid"
    row = updater_helper.sweep_row(100, 0.5)
    assert len(row) == 400 and bytes((0xFC, 0x86, 0xBB, 255)) in row


def test_the_swapper_imports_nothing_from_the_app():
    import ast
    with open(os.path.join(PROJECT, "updater_helper.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"app", "modules", "PyQt6", "tkinter"}
    assert names <= set(sys.stdlib_module_names)


# --- an installer-mode swap cut off half-way (S3.1-5): the RunOnce entry and --recover --------------------------------

class _PowerLost(BaseException):
    """Power lost, or the swapper and Setup both ended: nothing after it runs, no `finally` of the swapper's either."""


def _entry(runonce, marker_path):
    """This install's recovery entry (the command Windows would run at sign-in), or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, runonce) as key:
            return winreg.QueryValueEx(key, updater_helper._recovery_value(os.path.dirname(marker_path)))[0]
    except OSError:
        return None


def _cut_off(marker, monkeypatch, setup_wrote=None, at_rename=None):
    """Installer mode run until it is cut off — while Setup runs (`setup_wrote()` is what Setup wrote first), or at
    the `at_rename`-th move — leaving exactly what a killed swapper leaves. -> the marker's path."""
    marker["window"] = False
    real_forget, real_rename = updater_helper.forget_recovery, updater_helper._rename
    monkeypatch.setattr(updater_helper, "forget_recovery", lambda root: None)     # a killed process runs no finally
    renames = []

    def rename(src, dst, sleep=None):
        renames.append(src)
        if len(renames) == at_rename:
            raise _PowerLost()
        return real_rename(src, dst)
    monkeypatch.setattr(updater_helper, "_rename", rename)

    def setup(argv):
        if setup_wrote is not None:
            setup_wrote()
        raise _PowerLost()
    path = updater.write_marker(marker)
    with pytest.raises(_PowerLost):
        updater_helper.run(path, ops=kit.FakeOps(setup=setup))
    monkeypatch.setattr(updater_helper, "forget_recovery", real_forget)
    monkeypatch.setattr(updater_helper, "_rename", real_rename)
    return _swapper_ended(path)


def _swapper_ended(path):
    """The swapper ran in this test's own process, so the marker names it as running: a killed swapper's is gone."""
    m = updater._read_marker(path)
    if not m.get("armed"):
        return path
    assert m["swapper_pid"] == os.getpid() and m["swapper_image"] == updater_helper._own_image(), "its swapper named"
    m["swapper_image"] = os.path.join(os.path.dirname(path), "swapper", "updater-ended.exe")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f)
    return path


def _half(root):
    """Setup cut off mid-way: the new command line and _internal are in, the window's program isn't."""
    return lambda: kit.write_tree(root, {p: d for p, d in kit.program(kit.NEW).items() if p != "Surasura.exe"})


def _whole(root):
    return lambda: kit.write_tree(root, kit.program(kit.NEW))


def _result():
    with open(updater.result_path(), encoding="utf-8") as f:
        return json.load(f)


def test_installer_mode_leaves_its_recovery_entry_before_the_first_move_and_takes_it_away_at_the_end(
        installer_marker, runonce, monkeypatch):
    root, marker, _before = installer_marker
    path = updater.marker_path()
    at_first_move = []
    real_rename = updater_helper._rename

    def rename(src, dst, sleep=None):
        if not at_first_move:
            with open(path, encoding="utf-8") as f:
                at_first_move.append((_entry(runonce, path), json.load(f).get("armed")))
        return real_rename(src, dst)
    monkeypatch.setattr(updater_helper, "_rename", rename)
    code, result = _run(marker, kit.FakeOps(setup=lambda argv: _whole(root)() or 0))
    assert result["status"] == "success"
    [(command, armed)] = at_first_move
    assert command.endswith(f' --recover "{path}"')
    assert os.path.normcase(f'"{os.path.join(PROJECT, "updater_helper.py")}"') in os.path.normcase(command)
    assert armed, "the marker on disk says it was armed: recovery acts on no other"
    assert _entry(runonce, path) is None, "gone the moment the swap ended"


@pytest.mark.parametrize("how", ["Setup fails", "Setup raises", "the swap raises"])
def test_the_recovery_entry_goes_whatever_the_outcome(installer_marker, runonce, monkeypatch, how):
    root, marker, before = installer_marker
    path = updater.marker_path()
    while_setup_ran = []

    def setup(argv):
        while_setup_ran.append(_entry(runonce, path))
        _whole(root)()
        if how == "Setup raises":
            raise RuntimeError("Setup's process could not be waited on")
        return 5
    if how == "the swap raises":
        real = updater_helper.apply_installer

        def apply(m, ops, clock, sleep, seen, arm=None):
            real(m, ops, clock, sleep, seen, arm=arm)
            raise RuntimeError("something no one foresaw")
        monkeypatch.setattr(updater_helper, "apply_installer", apply)
        with pytest.raises(RuntimeError):
            updater_helper.run(updater.write_marker(marker), ops=kit.FakeOps(setup=setup))
    else:
        rc, result = _run(marker, kit.FakeOps(setup=setup))
        assert result["status"] == "failed" and kit.tree(root) == before
    assert while_setup_ran and while_setup_ran[0], "it was there while Setup ran"
    assert _entry(runonce, path) is None


@pytest.mark.parametrize("refused", ["the registry", "the marker"])
def test_installer_mode_never_moves_without_its_recovery_entry(installer_marker, runonce, monkeypatch, refused):
    """The entry can't be left (the registry refuses), or the marker can't be stamped (held open: Windows won't
    replace it): the update stops before its first move."""
    root, marker, before = installer_marker
    path = updater.write_marker(marker)
    ops = kit.FakeOps()
    if refused == "the registry":
        import winreg

        def denied(*args):
            raise PermissionError(5, "Access is denied")
        monkeypatch.setattr(winreg, "SetValueEx", denied)
        updater_helper.run(path, ops=ops)
    else:
        with open(path, "rb"):
            updater_helper.run(path, ops=ops)
        with open(path, encoding="utf-8") as f:
            assert "armed" not in json.load(f), "never stamped, so no recovery would act on it"
        assert not [n for n in os.listdir(updater.update_dir()) if n.endswith(".tmp")], "no half-written copy left"
    result = _result()
    assert result["status"] == "failed" and result["touched"] is False
    assert "before changing anything" in result["reason"]
    assert ops.setup_argv is None and kit.tree(root) == before
    assert not os.path.exists(os.path.join(updater.previous_root(), kit.OLD))
    assert _entry(runonce, path) is None


def test_the_recovery_entry_is_the_users_runonce_and_never_a_tests(tmp_path, monkeypatch):
    monkeypatch.setenv(updater_helper.TEST_RUNONCE_ENV, r"Software\Microsoft\Windows\CurrentVersion\Run")
    with pytest.raises(OSError):
        updater_helper._runonce_root()            # under pytest, the user's own key is refused
    with pytest.raises(OSError):
        updater_helper.arm_recovery(str(tmp_path / "pending_update.json"), {})
    monkeypatch.delenv("PYTEST_CURRENT_TEST")      # (pure from here on: nothing below touches the registry)
    assert updater_helper._runonce_root() == r"Software\Microsoft\Windows\CurrentVersion\RunOnce", \
        "a variable naming any key but a test's is ignored"
    monkeypatch.delenv(updater_helper.TEST_RUNONCE_ENV)
    assert updater_helper._runonce_root() == updater_helper.RUNONCE_ROOT


def test_the_recovery_entry_is_one_per_install_and_runs_the_copied_out_swapper(tmp_path, monkeypatch):
    real = str(tmp_path / "Houseki" / "Surasura" / "update")
    test = str(tmp_path / "Houseki" / "Surasura-test" / "update")
    name = updater_helper._recovery_value(real)
    assert name.startswith("SurasuraUpdateRecovery-") and len(name) == len("SurasuraUpdateRecovery-") + 12
    assert name == updater_helper._recovery_value(real.upper()) and name != updater_helper._recovery_value(test)
    swapper = os.path.join(real, "swapper", "updater-3.0.1.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", swapper)
    marker = os.path.join(real, "pending_update.json")
    assert updater_helper.recovery_command(marker) == f'"{swapper}" --recover "{marker}"'


def test_recovery_puts_the_old_version_back_when_setup_never_finished(installer_marker, runonce, registry,
                                                                       monkeypatch):
    root, marker, before = installer_marker
    entry = registry("{SURASURA-TEST-8}", root, DisplayVersion=kit.OLD)
    marker["app_id"] = "{SURASURA-TEST-8}"

    def setup_wrote():                                    # Inno rewrites the entry as it installs
        _half(root)()
        updater_helper.write_uninstall_version("{SURASURA-TEST-8}", str(root), kit.NEW)
    path = _cut_off(marker, monkeypatch, setup_wrote)
    assert not os.path.exists(root / "Surasura.exe") and _entry(runonce, path), "cut off: no program, an entry left"
    assert _values(entry)["DisplayVersion"] == kit.NEW

    ops = kit.FakeOps()
    assert updater_helper.recover(path, ops=ops) == 2
    assert kit.tree(root) == before, "byte-identical: the old program back, Setup's files gone, foreign files kept"
    assert _values(entry)["DisplayVersion"] == kit.OLD, "the entry names the version that is back"
    assert ops.started == [] and ops.setup_argv is None, "nothing started: it runs at sign-in, without the program"
    result = _result()
    assert result["status"] == "failed" and "cut off" in result["reason"] and result["to"] == kit.NEW
    assert not os.path.exists(path) and _entry(runonce, path) is None
    assert not os.path.exists(os.path.join(updater.previous_root(), kit.OLD))
    assert updater.consume_result()["status"] == "failed", "the app reads it as a failed update"


def test_recovery_keeps_what_setup_finished_and_writes_the_success_the_app_knows(installer_marker, runonce,
                                                                                 monkeypatch):
    root, marker, before = installer_marker
    path = _cut_off(marker, monkeypatch, _whole(root))
    ops = kit.FakeOps()
    assert updater_helper.recover(path, ops=ops) == 0
    after = kit.tree(root)
    assert _program_part(after) == kit.digests(kit.program(kit.NEW)) and _foreign(after) == _foreign(before)
    assert ops.started == [] and ops.setup_argv is None
    assert kit.tree(os.path.join(updater.previous_root(), kit.OLD)) == kit.digests(kit.old_program())
    assert os.path.isfile(os.path.join(updater.previous_root(), f"{kit.OLD}.files.json")), "kept for Go back"
    assert not os.path.exists(path) and _entry(runonce, path) is None
    result = updater.consume_result()
    assert result["status"] == "success" and result["reason"] == "ok (the updater ended before reporting)"
    assert (result["from"], result["to"]) == (kit.OLD, kit.NEW)


def test_recovery_leaves_alone_an_install_something_runs_from(installer_marker, runonce, monkeypatch):
    root, marker, before = installer_marker
    path = _cut_off(marker, monkeypatch, _half(root))
    now, kept = kit.tree(root), kit.tree(updater.previous_root())
    forget = updater_helper.forget_recovery
    forget(os.path.dirname(path))                  # Windows removes the value before it runs it
    assert updater_helper.recover(path, ops=kit.FakeOps(running=[4242])) == 1
    assert kit.tree(root) == now and kit.tree(updater.previous_root()) == kept and os.path.exists(path)
    assert not os.path.exists(updater.result_path())
    assert _entry(runonce, path) == updater_helper.recovery_command(path), \
        "the entry is written again, so the next sign-in tries again (the app keeps saying so)"
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2, "once nothing runs there, a recovery puts it right"
    assert kit.tree(root) == before and _entry(runonce, path) is None


@pytest.mark.parametrize("started", ["the half-new program", "the old program (cut off at the first move)"])
def test_a_program_started_before_the_sign_in_leaves_the_cut_off_update_to_its_recovery(installer_marker, runonce,
                                                                                         monkeypatch, started):
    """Cut off, then a program started before the next sign-in reads the marker: it reports the cut-off and keeps the
    marker and the swapper's copy, which the RunOnce entry names, so the sign-in's recovery still puts it right
    (consuming them left the old version unused in previous\\ and the entry naming a deleted program)."""
    root, marker, before = installer_marker
    if started == "the half-new program":
        path = _cut_off(marker, monkeypatch, _half(root))
        monkeypatch.setattr(updater, "__version__", kit.NEW)
    else:
        path = _cut_off(marker, monkeypatch, at_rename=1)
        monkeypatch.setattr(updater, "__version__", kit.OLD)
    os.makedirs(updater.swapper_dir(), exist_ok=True)
    swapper = os.path.join(updater.swapper_dir(), f"updater-{kit.NEW}.exe")
    with open(swapper, "wb") as f:
        f.write(b"MZ the swapper's copy")
    result = updater.consume_result()
    assert result["status"] == "failed" and result["reason"] == updater.CUT_OFF
    assert (result["from"], result["to"]) == (kit.OLD, kit.NEW)
    assert os.path.exists(path) and os.path.isfile(swapper) and _entry(runonce, path), "all kept for the sign-in"
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert kit.tree(root) == before and _entry(runonce, path) is None
    assert updater.consume_result()["status"] == "failed" and not os.path.exists(path)


def test_a_cut_off_between_the_entry_and_the_stamp_moves_nothing_and_the_entry_goes(installer_marker, runonce,
                                                                                    monkeypatch):
    """Killed after the RunOnce value is written, before the marker is stamped: nothing moved and the marker is not
    armed, so the sign-in's recovery leaves everything and takes its entry away, and the program reads the marker as
    an update that did not complete (stamping first left an armed marker no entry would ever act on)."""
    root, marker, before = installer_marker
    path = updater.write_marker(marker)
    real_forget, real_write = updater_helper.forget_recovery, updater_helper._write_json_atomic
    monkeypatch.setattr(updater_helper, "forget_recovery", lambda root: None)     # a killed process runs no finally

    def write(target, data):
        if os.path.normcase(target) == os.path.normcase(path) and data.get("armed"):
            raise _PowerLost()
        return real_write(target, data)
    monkeypatch.setattr(updater_helper, "_write_json_atomic", write)
    with pytest.raises(_PowerLost):
        updater_helper.run(path, ops=kit.FakeOps())
    monkeypatch.setattr(updater_helper, "forget_recovery", real_forget)
    monkeypatch.setattr(updater_helper, "_write_json_atomic", real_write)
    assert _entry(runonce, path) and kit.tree(root) == before
    with open(path, encoding="utf-8") as f:
        assert "armed" not in json.load(f)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 1
    assert _entry(runonce, path) is None and kit.tree(root) == before
    monkeypatch.setattr(updater, "__version__", kit.OLD)
    assert updater.consume_result()["reason"] == "update did not complete" and not os.path.exists(path)


def test_a_result_that_cant_be_written_leaves_the_marker_for_the_program_to_judge(installer_marker, runonce,
                                                                                  monkeypatch):
    """The swap landed but its result file can't be written: the marker stays, no longer armed (nothing waits at the
    sign-in), so the new program still reads the update as landed instead of nothing at all."""
    root, marker, before = installer_marker
    real_write = updater_helper._write_json_atomic
    monkeypatch.setattr(updater_helper, "_write_json_atomic",
                        lambda target, data: False if os.path.normcase(target) == os.path.normcase(
                            updater.result_path()) else real_write(target, data))
    path = updater.write_marker(marker)
    assert updater_helper.run(path, ops=kit.FakeOps(setup=lambda argv: _whole(root)() or 0)) == 0
    assert not os.path.exists(updater.result_path()) and _entry(runonce, path) is None
    with open(path, encoding="utf-8") as f:
        assert "armed" not in json.load(f), "kept, unarmed"
    monkeypatch.setattr(updater, "__version__", kit.NEW)
    result = updater.consume_result()
    assert result["status"] == "success" and result["reason"] == "ok (the updater ended before reporting)"
    assert not os.path.exists(path)


def test_no_update_starts_over_an_update_cut_off_half_way(installer_marker, runonce, monkeypatch):
    """A new update, installer or Go back would write its own marker over the cut-off one and lose its recovery: each
    is refused with the cut-off's words until the sign-in has finished or undone it."""
    root, marker, before = installer_marker
    path = _cut_off(marker, monkeypatch, _half(root))
    monkeypatch.setattr(updater, "__version__", kit.NEW)
    info = update_checker.get_update_info()
    for start in (lambda: updater.prepare_update(info), lambda: updater.prepare_installer(info),
                  updater.prepare_go_back):
        with pytest.raises(updater.UpdateError) as refused:
            start()
        assert str(refused.value) == updater.CUT_OFF
    assert os.path.exists(path) and _entry(runonce, path)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2 and kit.tree(root) == before


def test_installer_mode_never_runs_an_unsigned_releases_installer(installer_marker, monkeypatch):
    """The installer and its file list are trusted only through the release's signature, as the one-click update's
    parts are: an unsigned release is refused before anything is downloaded."""
    info = update_checker.get_update_info()
    monkeypatch.setattr(info, "signed", False)
    before = sorted(os.listdir(updater.update_dir()))
    with pytest.raises(updater.UpdateError, match="isn't signed"):
        updater.prepare_installer(info)
    assert sorted(os.listdir(updater.update_dir())) == before


def test_an_installer_marker_never_armed_is_consumed_as_an_update_that_did_not_complete(installer_marker, runonce,
                                                                                        monkeypatch):
    """The swapper ended before its first move (no entry, nothing moved): nothing at the sign-in would act on the
    marker, so the program consumes it as it always has, once."""
    root, marker, before = installer_marker
    path = updater.write_marker(marker)
    monkeypatch.setattr(updater, "__version__", kit.OLD)
    result = updater.consume_result()
    assert result["status"] == "failed" and result["reason"] == "update did not complete"
    assert not os.path.exists(path) and updater.consume_result() is None and kit.tree(root) == before


def test_a_cut_off_update_that_landed_is_read_as_landed_by_the_new_program(installer_marker, runonce, monkeypatch):
    """Setup finished before the cut-off and the new program starts first: its files prove it, so it is a success
    (the entry left behind then finds no marker at the sign-in and goes)."""
    root, marker, before = installer_marker
    path = _cut_off(marker, monkeypatch, _whole(root))
    monkeypatch.setattr(updater, "__version__", kit.NEW)
    result = updater.consume_result()
    assert result["status"] == "success" and not os.path.exists(path)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 1 and _entry(runonce, path) is None


@pytest.mark.parametrize("kept", ["listed", "no list", "an empty list"])
@pytest.mark.parametrize("nth", [1, 3])
def test_recovery_after_a_cut_off_between_moves_puts_back_exactly_what_moved(installer_marker, runonce, monkeypatch,
                                                                             nth, kept):
    """Cut off at the first move (armed, nothing moved) or the third (two entries kept, the rest still in place): the
    entries never moved are the old program's and stay; the moved ones come back. Without the old program's list
    (a damaged marker), nothing unmoved is ever taken for Setup's."""
    root, marker, before = installer_marker
    if kept != "listed":
        marker["kept_files"] = None if kept == "no list" else {}
    path = _cut_off(marker, monkeypatch, at_rename=nth)
    assert _entry(runonce, path)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert kit.tree(root) == before and not os.path.exists(path) and _entry(runonce, path) is None


def test_recovery_takes_away_an_entry_setup_added_that_the_old_program_never_had(installer_marker, runonce,
                                                                                  monkeypatch):
    root, marker, before = installer_marker
    marker["owned"] = sorted(marker["owned"] + ["surasura-connect.exe"], key=str.lower)
    path = _cut_off(marker, monkeypatch,
                    lambda: kit.write_tree(root, {"surasura-connect.exe": b"MZ\x90\x00connect " + kit.NEW.encode()}))
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert kit.tree(root) == before


def test_recovery_without_the_releases_list_needs_the_new_command_line(installer_marker, runonce, monkeypatch):
    """An unsigned release has no file list: an emptied folder must not pass as Setup finished."""
    root, marker, before = installer_marker
    marker["files"] = None
    path = _cut_off(marker, monkeypatch, lambda: kit.write_tree(root, {"_internal/base_library.zip": b"PK half"}))
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert kit.tree(root) == before


def test_recovery_with_an_entry_held_tries_again_at_the_next_sign_in(installer_marker, runonce, monkeypatch):
    """Something holds a file Setup wrote (antivirus, the indexer): the recovery never gives up for good. The marker
    stays armed, no result is written, the entry is written again; once the hold is gone, the next sign-in finishes
    the put-back."""
    root, marker, before = installer_marker
    path = _cut_off(marker, monkeypatch, _half(root))
    with open(root / "_internal" / "base_library.zip", "rb"):         # Setup's file, held: _internal can't go
        assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert not os.path.exists(updater.result_path()), "no result while something is held"
    assert updater._read_marker(path).get("armed") and _entry(runonce, path) == updater_helper.recovery_command(path)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert _result()["status"] == "failed" and "could not be put back" not in _result()["reason"]
    assert kit.tree(root) == before and not os.path.exists(path) and _entry(runonce, path) is None


@pytest.mark.parametrize("finished", [False, True])
def test_recovery_twice_changes_nothing_more(installer_marker, runonce, monkeypatch, finished):
    root, marker, _before = installer_marker
    path = _cut_off(marker, monkeypatch, _whole(root) if finished else _half(root))
    assert updater_helper.recover(path, ops=kit.FakeOps()) == (0 if finished else 2)
    now, first = kit.tree(updater.update_dir()), kit.tree(root)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 1
    assert kit.tree(updater.update_dir()) == now and kit.tree(root) == first


@pytest.mark.parametrize("damage", ["missing", "not JSON", "a list", "2.x's", "a folder swap's", "never armed",
                                    "reaching outside"])
def test_recovery_with_a_marker_it_cant_trust_moves_nothing_and_takes_its_entry_away(
        installer_marker, runonce, monkeypatch, tmp_path, damage):
    root, marker, _before = installer_marker
    path = _cut_off(marker, monkeypatch, _half(root))
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    text = None
    if damage == "missing":
        os.remove(path)
    elif damage == "not JSON":
        text = '{"format": 3, "kind": "inst'
    elif damage == "a list":
        text = json.dumps([m])
    elif damage == "2.x's":
        m.pop("format")
    elif damage == "a folder swap's":                    # a folder swap's contract, without the plan its swap stamps
        m["kind"], m["staged"] = "folder", os.path.join(updater.update_dir(), f"stage-{kit.NEW}")
    elif damage == "never armed":
        m.pop("armed")
    else:
        m["previous"] = str(tmp_path / "elsewhere" / kit.OLD)
    if damage != "missing":
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if text is not None else json.dumps(m))
    now, install = kit.tree(updater.update_dir()), kit.tree(root)
    assert _entry(runonce, path)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 1
    assert kit.tree(updater.update_dir()) == now and kit.tree(root) == install, "nothing moved, nothing written"
    assert _entry(runonce, path) is None


@pytest.mark.parametrize("finished", [False, True])
def test_a_later_swapper_handed_an_armed_marker_recovers_it_and_never_swaps_twice(installer_marker, runonce,
                                                                                  monkeypatch, finished):
    """The marker an earlier swapper armed (before this one started: that swap was cut off) is recovered first."""
    root, marker, before = installer_marker
    path = _cut_off(marker, monkeypatch, _whole(root) if finished else _half(root))
    ops = kit.FakeOps()
    code = updater_helper.run(path, ops=ops)
    assert ops.setup_argv is None and ops.started == [], "Setup never runs a second time"
    if finished:
        assert code == 0 and _result()["reason"] == updater_helper.RECOVERED
        assert _program_part(kit.tree(root)) == kit.digests(kit.program(kit.NEW))
    else:
        assert code == 2 and _result()["status"] == "failed" and kit.tree(root) == before
    assert not os.path.exists(path) and _entry(runonce, path) is None


def test_a_cut_off_before_the_kept_copy_is_cleared_leaves_nothing_armed(installer_marker, runonce, monkeypatch):
    """A stale previous\\<from> (an earlier copy of this version) is cleared before the entry is left: cut off while it
    is cleared, nothing is armed, so no recovery brings the stale copy back over the program."""
    root, marker, before = installer_marker
    kit.write_tree(marker["previous"], {"Surasura.exe": b"MZ a stale copy", "_internal/base_library.zip": b"PK stale"})
    real_clear = updater_helper._clear_same
    kept = os.path.normcase(os.path.abspath(marker["previous"]))

    def clear(path):
        if os.path.normcase(os.path.abspath(path)) == kept:
            raise _PowerLost()
        return real_clear(path)
    monkeypatch.setattr(updater_helper, "_clear_same", clear)
    path = _cut_off(marker, monkeypatch)
    assert _entry(runonce, path) is None
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 1
    assert kit.tree(root) == before


def test_a_real_recover_process_puts_back_a_cut_off_swap(installer_marker, runonce, monkeypatch):
    """`python updater_helper.py --recover <marker>` — what the entry runs, here from source — with real Windows calls:
    nothing runs from the folder and Setup's files fail the release's list, so the old program comes back."""
    root, marker, before = installer_marker
    path = _cut_off(marker, monkeypatch, _half(root))
    assert _entry(runonce, path).endswith(f' --recover "{path}"')
    done = subprocess.run([kit.PYTHON, os.path.join(PROJECT, "updater_helper.py"), "--recover", path],
                          capture_output=True, timeout=120, cwd=updater.update_dir())
    assert done.returncode == 2, done.stderr.decode("utf-8", "replace")
    assert kit.tree(root) == before and not os.path.exists(path) and _entry(runonce, path) is None


# --- a folder swap cut off half-way (S3.1-6): the same RunOnce entry and --recover, for every update -------------------
# The kit's swap is 13 renames: the old program's 7 entries out to previous\3.0.0 (_internal, README.md,
# RELEASE_NOTES.md, surasura-cli.exe, Surasura.exe, UPDATE_INSTRUCTIONS.md, updater.exe), then the release's 6 in from
# the stage (README.md, RELEASE_NOTES.md, Surasura.exe, _internal, surasura-cli.exe, updater.exe).
OLD_ENTRIES = ["_internal", "README.md", "RELEASE_NOTES.md", "surasura-cli.exe", "Surasura.exe",
               "UPDATE_INSTRUCTIONS.md", "updater.exe"]
NEW_ENTRIES = ["README.md", "RELEASE_NOTES.md", "Surasura.exe", "_internal", "surasura-cli.exe", "updater.exe"]
PUT_BACK = "the update was cut off before it finished, so the old version was put back"


class _CutInProof(kit.FakeOps):
    """Every entry has moved; the swapper is cut off while it asks the new command line its version."""

    def version(self, cli):
        raise _PowerLost()


def _cut_off_folder(marker, monkeypatch, at_rename=None):
    """A folder swap run until it is cut off — at the `at_rename`-th move, or (None) once every entry has moved, during
    its proof — leaving exactly what a killed swapper leaves. -> the marker's path."""
    marker["window"] = False
    real_forget, real_rename = updater_helper.forget_recovery, updater_helper._rename
    monkeypatch.setattr(updater_helper, "forget_recovery", lambda root: None)     # a killed process runs no finally
    renames = []

    def rename(src, dst, sleep=None):
        renames.append(src)
        if len(renames) == at_rename:
            raise _PowerLost()
        return real_rename(src, dst)
    monkeypatch.setattr(updater_helper, "_rename", rename)
    path = updater.write_marker(marker)
    with pytest.raises(_PowerLost):
        updater_helper.run(path, ops=_CutInProof())
    monkeypatch.setattr(updater_helper, "forget_recovery", real_forget)
    monkeypatch.setattr(updater_helper, "_rename", real_rename)
    return _swapper_ended(path)


@pytest.mark.parametrize("outcome", ["proven", "its proof failed"])
def test_a_folder_swap_leaves_its_recovery_entry_before_the_first_move_and_takes_it_away_at_the_end(
        staged, runonce, monkeypatch, outcome):
    """Every update, the everyday one-click one too (Sonic, S3.1-6): the entry and the marker's stamp — with the plan
    the recovery reads, what leaves the install and what arrives from the stage — are on disk at the first rename, and
    gone once the swap ends, whatever it ends in."""
    root, marker, before = staged
    path = updater.marker_path()
    at_first_move = []
    real_rename = updater_helper._rename

    def rename(src, dst, sleep=None):
        if not at_first_move:
            with open(path, encoding="utf-8") as f:
                at_first_move.append((_entry(runonce, path), json.load(f)))
        return real_rename(src, dst)
    monkeypatch.setattr(updater_helper, "_rename", rename)
    code, result = _run(marker, kit.FakeOps(version=None if outcome == "proven" else "2.9.9"))
    assert result["status"] == ("success" if outcome == "proven" else "failed")
    [(command, stamped)] = at_first_move
    assert command == updater_helper.recovery_command(path)
    assert stamped.get("armed"), "the marker on disk says it was armed: recovery acts on no other"
    assert stamped["leaving"] == OLD_ENTRIES and stamped["arriving"] == NEW_ENTRIES
    assert _entry(runonce, path) is None, "gone the moment the swap ended"
    if outcome != "proven":
        assert kit.tree(root) == before


@pytest.mark.parametrize("refused", ["something still runs there", "the stage is incomplete", "the registry",
                                     "the marker"])
def test_a_folder_swap_refused_before_its_first_move_leaves_no_entry(staged, runonce, monkeypatch, refused):
    """Refused before anything moves: nothing needs finishing or undoing, so no entry stays (and none is ever written
    while the swap still waits or checks its stage); an entry or a stamp that can't be written stops it unchanged."""
    root, marker, before = staged
    path = updater.write_marker(marker)
    ops, written = kit.FakeOps(), []
    real_write = updater_helper._write_recovery
    monkeypatch.setattr(updater_helper, "_write_recovery", lambda p: written.append(p) or real_write(p))
    if refused == "something still runs there":
        marker["wait_timeout"] = 0.05
        path = updater.write_marker(marker)
        ops = kit.FakeOps(running=[4242])
    elif refused == "the stage is incomplete":
        os.remove(os.path.join(marker["staged"], "surasura-cli.exe"))
    elif refused == "the registry":
        import winreg

        def denied(*args):
            raise PermissionError(5, "Access is denied")
        monkeypatch.setattr(winreg, "SetValueEx", denied)
    if refused == "the marker":
        with open(path, "rb"):                            # held: Windows won't replace it, so it can't be stamped
            updater_helper.run(path, ops=ops)
        assert not [n for n in os.listdir(updater.update_dir()) if n.endswith(".tmp")]
    else:
        updater_helper.run(path, ops=ops)
    result = _result()
    assert result["status"] == "failed" and result["touched"] is False
    assert kit.tree(root) == before and not os.path.exists(os.path.join(updater.previous_root(), kit.OLD))
    assert _entry(runonce, path) is None
    if refused in ("something still runs there", "the stage is incomplete"):
        assert written == [], "never written while the swap waits or checks its stage"
    else:
        assert "before changing anything" in result["reason"]


@pytest.mark.parametrize("nth", [1, 4, 7, 8, 10, 13])
def test_folder_recovery_after_a_cut_off_at_any_move_puts_back_exactly_what_moved(staged, runonce, monkeypatch, nth):
    """Cut off at the first move (armed, nothing moved), part-way out (4, 7), with every old entry out (8), part-way in
    (10: README.md and RELEASE_NOTES.md, names the old program had too), or with all but updater.exe in (13): the
    sign-in's recovery puts the old program back byte for byte and the release back in its stage — an old entry never
    moved stays, a new one goes only where its old one had left — and starts nothing."""
    root, marker, before = staged
    path = _cut_off_folder(marker, monkeypatch, at_rename=nth)
    assert _entry(runonce, path) == updater_helper.recovery_command(path), "cut off: the entry left for the sign-in"
    ops = kit.FakeOps()
    assert updater_helper.recover(path, ops=ops) == 2
    assert kit.tree(root) == before, "byte-identical: the old program back, the foreign files untouched"
    assert kit.tree(marker["staged"]) == kit.digests(kit.program(kit.NEW)), "the release back in its stage"
    assert not os.path.exists(os.path.join(updater.previous_root(), kit.OLD))
    assert ops.started == [], "nothing started: it runs at sign-in, without the program"
    result = _result()
    assert (result["status"], result["reason"], result["kind"], result["going_back"]) == \
        ("failed", PUT_BACK, "folder", False)
    assert not os.path.exists(path) and _entry(runonce, path) is None
    assert updater.consume_result()["status"] == "failed", "the app reads it as a failed update"


def test_folder_recovery_finishes_a_swap_cut_off_once_every_entry_moved(staged, runonce, registry, monkeypatch):
    """Cut off during its proof, every entry moved: the release is in place (every file's sha256, and the command line
    says so), so it is kept — 3.0.0 kept for Go back with its list, the stage gone, the uninstall entry naming 3.0.1 —
    and the app reads the success it knows."""
    root, marker, before = staged
    entry = registry("{SURASURA-TEST-9}", root, DisplayVersion=kit.OLD)
    marker["app_id"] = "{SURASURA-TEST-9}"
    path = _cut_off_folder(marker, monkeypatch)
    assert _entry(runonce, path) and _values(entry)["DisplayVersion"] == kit.OLD
    ops = kit.FakeOps()
    assert updater_helper.recover(path, ops=ops) == 0
    after = kit.tree(root)
    assert _program_part(after) == kit.digests(kit.program(kit.NEW)) and _foreign(after) == _foreign(before)
    assert ops.started == []
    assert sorted(os.listdir(updater.previous_root())) == [kit.OLD, f"{kit.OLD}.files.json"]
    assert kit.tree(os.path.join(updater.previous_root(), kit.OLD)) == kit.digests(kit.old_program())
    assert not os.path.exists(marker["staged"])
    assert _values(entry)["DisplayVersion"] == kit.NEW, "Windows' installed-apps list follows (D8)"
    assert not os.path.exists(path) and _entry(runonce, path) is None
    result = updater.consume_result()
    assert (result["status"], result["reason"]) == ("success", "ok (the updater ended before reporting)")
    assert (result["from"], result["to"], result["kind"]) == (kit.OLD, kit.NEW, "folder")


def test_folder_recovery_takes_back_an_entry_the_old_program_never_had(staged, runonce, monkeypatch):
    """A release adding a top-level entry (here a Connect program): cut off once it has arrived, it goes back to the
    stage with the rest — it is the release's, since the old program had no such entry."""
    root, marker, before = staged
    kit.write_tree(marker["staged"], {"surasura-connect.exe": b"MZ\x90\x00connect " + kit.NEW.encode()})
    marker["files"] = dict(marker["files"], **kit.digests({"surasura-connect.exe": b"MZ\x90\x00connect " +
                                                           kit.NEW.encode()}))
    marker["owned"] = sorted(marker["owned"] + ["surasura-connect.exe"], key=str.lower)
    release = kit.tree(marker["staged"])
    path = _cut_off_folder(marker, monkeypatch, at_rename=14)           # 7 out, 6 in: all but updater.exe
    assert os.path.isfile(root / "surasura-connect.exe")
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert kit.tree(root) == before and kit.tree(marker["staged"]) == release


def test_folder_recovery_of_go_back_without_its_list_waits_for_every_entry(staged, runonce, monkeypatch):
    """Go back with its kept list lost has only its command line for a proof — and 3.0.0's command line answers as
    soon as it and _internal are in. Cut off before updater.exe came in, the swap isn't finished: put back (3.0.1 runs
    again, 3.0.0 is kept again), never kept half."""
    root, marker, _before = staged
    assert _run(marker, kit.FakeOps())[1]["status"] == "success"
    monkeypatch.setattr(updater, "__version__", kit.NEW)
    os.remove(os.path.join(updater.previous_root(), f"{kit.OLD}.files.json"))
    back = updater.prepare_go_back()
    assert back["files"] is None
    now, kept = kit.tree(root), kit.tree(os.path.join(updater.previous_root(), kit.OLD))
    path = _cut_off_folder(back, monkeypatch, at_rename=13)            # 6 out, 6 of 7 in: all but updater.exe
    assert kit.FakeOps().version(str(root / "surasura-cli.exe")) == kit.OLD, "its command line already answers"
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert kit.tree(root) == now and kit.tree(os.path.join(updater.previous_root(), kit.OLD)) == kept
    result = _result()
    assert result["status"] == "failed" and result["going_back"] is True and result["to"] == kit.OLD


@pytest.mark.parametrize("proof", ["proven", "its window closed"])
def test_the_new_version_the_proof_starts_leaves_the_marker_to_the_swap_still_running(staged, runonce, monkeypatch,
                                                                                      proof):
    """The swapper starts the new Surasura.exe to see its window, and that program reads the update folder as it
    opens. The swap is still running — and may yet be undone — so it leaves the marker and the entry alone and says
    nothing; the one result the swapper writes is read once, at the next start (never "Updated" twice)."""
    root, marker, before = staged
    marker["window"] = True
    seen = []

    class Opening(kit.FakeOps):
        def start(self, exe):
            monkeypatch.setattr(updater, "__version__", kit.NEW)
            path = updater.marker_path()
            seen.append((updater.consume_result(), os.path.exists(path), updater._read_marker(path).get("armed"),
                         _entry(runonce, path)))
            return super().start(exe)
    ops = Opening() if proof == "proven" else Opening(window=None, exits=1, code=1)
    path = updater.write_marker(marker)
    code = updater_helper.run(path, ops=ops)
    assert seen, "the proof started the new version"
    for read, kept, armed, entry in seen:                              # every start while the swap runs
        assert read is None and kept and armed and entry == updater_helper.recovery_command(path)
    first = updater.consume_result()
    assert first["status"] == ("success" if proof == "proven" else "failed") and code == (0 if proof == "proven" else 2)
    assert updater.consume_result() is None, "read once"
    if proof != "proven":
        assert kit.tree(root) == before


def test_a_swapper_is_running_only_while_its_own_program_holds_its_pid():
    """A pid Windows hands to something else after a cut-off is not the swapper: the program must match too."""
    me = {"armed": "2026-10-13T14:00:00", "swapper_pid": os.getpid(), "swapper_image": updater_helper._own_image()}
    assert updater._swapper_running(me) is (sys.platform == "win32")
    assert not updater._swapper_running(dict(me, swapper_image=os.path.join(os.path.dirname(sys.executable),
                                                                             "updater-3.0.1.exe")))
    assert not updater._swapper_running(dict(me, armed=None))
    assert not updater._swapper_running(dict(me, swapper_pid=str(os.getpid())))
    assert not updater._swapper_running({k: v for k, v in me.items() if k != "swapper_image"})


def test_a_later_swapper_that_finds_the_install_in_use_leaves_the_entry_for_the_next_sign_in(staged, runonce,
                                                                                             monkeypatch):
    """A second swapper handed an armed marker recovers it; with something running from the install, the recovery
    writes the entry again for the next sign-in — and the swapper's own end must not take it away."""
    root, marker, _before = staged
    path = _cut_off_folder(marker, monkeypatch, at_rename=10)
    now = kit.tree(root)
    assert updater_helper.run(path, ops=kit.FakeOps(running=[4242])) == 1
    assert kit.tree(root) == now and updater._read_marker(path).get("armed")
    assert _entry(runonce, path) == updater_helper.recovery_command(path)


def test_folder_recovery_asks_a_slow_first_start_twice_before_putting_back(staged, runonce, monkeypatch):
    """Just after sign-in antivirus can make the first `--version` miss its time: every file already matches its
    sha256, so the recovery asks once more before undoing a finished update."""
    root, marker, _before = staged
    path = _cut_off_folder(marker, monkeypatch)                         # every entry in, cut off in its proof

    class SlowFirst(kit.FakeOps):
        asked = 0

        def version(self, cli):
            self.asked += 1
            return None if self.asked == 1 else super().version(cli)
    ops = SlowFirst()
    assert updater_helper.recover(path, ops=ops) == 0 and ops.asked == 2
    assert _result()["reason"] == updater_helper.RECOVERED
    assert _program_part(kit.tree(root)) == kit.digests(kit.program(kit.NEW))


@pytest.mark.parametrize("cut", ["all but updater.exe in", "every entry in, cut off in its proof"])
def test_go_back_without_its_list_cut_off_half_in_is_never_read_as_landed_by_the_version_it_brings_back(
        staged, runonce, monkeypatch, cut):
    """Go back with its kept list lost, cut off once 3.0.0's Surasura.exe and _internal are in but before its
    updater.exe: 3.0.0 can start before the next sign-in, and its own version runs — yet the swap hasn't landed. It
    reports the cut-off and keeps the marker for the sign-in's recovery (never cleans it away, which would leave
    updater.exe in previous\\); cut off only in its proof, every entry in, it has landed."""
    root, marker, _before = staged
    assert _run(marker, kit.FakeOps())[1]["status"] == "success"
    monkeypatch.setattr(updater, "__version__", kit.NEW)
    os.remove(os.path.join(updater.previous_root(), f"{kit.OLD}.files.json"))
    back = updater.prepare_go_back()
    assert back["files"] is None
    path = _cut_off_folder(back, monkeypatch, at_rename=13 if cut == "all but updater.exe in" else None)
    monkeypatch.setattr(updater, "__version__", kit.OLD)              # the version it brings back starts first
    result = updater.consume_result()
    if cut == "all but updater.exe in":
        assert result["status"] == "failed" and result["reason"] == updater.CUT_OFF
        assert os.path.exists(path) and _entry(runonce, path), "kept for the sign-in"
        assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    else:
        assert result["status"] == "success" and result["reason"] == "ok (the updater ended before reporting)"
        assert not os.path.exists(path)


@pytest.mark.parametrize("damage", ["no plan", "a plan naming the library", "nothing arriving", "leaving not a list"])
def test_a_folder_marker_without_a_plan_it_can_trust_moves_nothing(staged, runonce, monkeypatch, damage):
    """A folder swap is recovered only from the plan its swapper stamped, naming the program's own plain entries:
    anything else (here, after a cut-off with two new entries in) moves nothing, and the entry goes."""
    root, marker, _before = staged
    path = _cut_off_folder(marker, monkeypatch, at_rename=10)
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    if damage == "no plan":
        del m["leaving"], m["arriving"]
    elif damage == "a plan naming the library":
        m["arriving"] = m["arriving"] + ["User Files"]
    elif damage == "nothing arriving":
        m["arriving"] = []
    else:
        m["leaving"] = "_internal"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f)
    now, install = kit.tree(updater.update_dir()), kit.tree(root)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 1
    assert kit.tree(updater.update_dir()) == now and kit.tree(root) == install, "nothing moved, nothing written"
    assert _entry(runonce, path) is None


def test_folder_recovery_with_an_entry_held_tries_again_at_the_next_sign_in(staged, runonce, monkeypatch):
    """The new _internal is in and one of its files is held: it can't go back to the stage, so the old _internal stays
    safe in previous\\3.0.0 while every other entry is put back — and the recovery doesn't give up for good: the
    marker stays armed, no result yet, the entry written again. The next sign-in, the hold gone, finishes it."""
    root, marker, before = staged
    path = _cut_off_folder(marker, monkeypatch, at_rename=13)
    with open(root / "_internal" / "base_library.zip", "rb"):
        assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert os.listdir(os.path.join(updater.previous_root(), kit.OLD)) == ["_internal"], "the old one kept safe"
    outside = {p: d for p, d in kit.tree(root).items() if not p.startswith("_internal/")}
    assert outside == {p: d for p, d in before.items() if not p.startswith("_internal/")}, "the rest put back"
    assert not os.path.exists(updater.result_path()), "no result while something is held"
    assert updater._read_marker(path).get("armed") and _entry(runonce, path) == updater_helper.recovery_command(path)
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert _result()["reason"] == PUT_BACK and kit.tree(root) == before
    assert not os.path.exists(path) and _entry(runonce, path) is None


def test_folder_recovery_leaves_alone_an_install_something_runs_from(staged, runonce, monkeypatch):
    root, marker, before = staged
    path = _cut_off_folder(marker, monkeypatch, at_rename=10)
    now = kit.tree(root)
    updater_helper.forget_recovery(os.path.dirname(path))           # Windows removes the value before it runs it
    assert updater_helper.recover(path, ops=kit.FakeOps(running=[4242])) == 1
    assert kit.tree(root) == now and os.path.exists(path) and not os.path.exists(updater.result_path())
    assert _entry(runonce, path) == updater_helper.recovery_command(path), "written again for the next sign-in"
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2 and kit.tree(root) == before


@pytest.mark.parametrize("started", ["the half-new program", "the old program (cut off at the first move)"])
def test_a_program_started_before_the_sign_in_leaves_a_cut_off_folder_swap_to_its_recovery(staged, runonce,
                                                                                            monkeypatch, started):
    """Cut off, then a program started before the next sign-in reads the marker: it reports the cut-off, keeps the
    marker and the swapper's copy the entry names, and starts no update or Go back over it (each would write its own
    marker over this one); the sign-in's recovery then puts it right."""
    root, marker, before = staged
    info = update_checker.get_update_info()
    if started == "the half-new program":
        path = _cut_off_folder(marker, monkeypatch, at_rename=13)
        monkeypatch.setattr(updater, "__version__", kit.NEW)
    else:
        path = _cut_off_folder(marker, monkeypatch, at_rename=1)
        monkeypatch.setattr(updater, "__version__", kit.OLD)
    os.makedirs(updater.swapper_dir(), exist_ok=True)
    swapper = os.path.join(updater.swapper_dir(), f"updater-{kit.NEW}.exe")
    with open(swapper, "wb") as f:
        f.write(b"MZ the swapper's copy")
    result = updater.consume_result()
    assert result["status"] == "failed" and result["reason"] == updater.CUT_OFF
    assert (result["from"], result["to"]) == (kit.OLD, kit.NEW)
    assert os.path.exists(path) and os.path.isfile(swapper) and _entry(runonce, path), "all kept for the sign-in"
    for start in (lambda: updater.prepare_update(info), updater.prepare_go_back):     # (installer mode: the same guard)
        with pytest.raises(updater.UpdateError) as refused:
            start()
        assert str(refused.value) == updater.CUT_OFF
    assert updater_helper.recover(path, ops=kit.FakeOps()) == 2
    assert kit.tree(root) == before and _entry(runonce, path) is None
    assert updater.consume_result()["status"] == "failed" and not os.path.exists(path)


@pytest.mark.parametrize("finished", [False, True])
def test_a_later_swapper_handed_an_armed_folder_marker_recovers_it_and_never_swaps_twice(staged, runonce,
                                                                                         monkeypatch, finished):
    root, marker, before = staged
    path = _cut_off_folder(marker, monkeypatch, at_rename=None if finished else 10)
    ops = kit.FakeOps()
    code = updater_helper.run(path, ops=ops)
    assert ops.started == [], "nothing started: a recovery, not a swap"
    if finished:
        assert code == 0 and _result()["reason"] == updater_helper.RECOVERED
        assert _program_part(kit.tree(root)) == kit.digests(kit.program(kit.NEW))
    else:
        assert code == 2 and _result()["status"] == "failed" and kit.tree(root) == before
    assert not os.path.exists(path) and _entry(runonce, path) is None


def test_a_real_recover_process_puts_back_a_cut_off_folder_swap(staged, runonce, monkeypatch):
    """`python updater_helper.py --recover <marker>` with real Windows calls on a folder swap cut off part-way in."""
    root, marker, before = staged
    path = _cut_off_folder(marker, monkeypatch, at_rename=10)
    done = subprocess.run([kit.PYTHON, os.path.join(PROJECT, "updater_helper.py"), "--recover", path],
                          capture_output=True, timeout=120, cwd=updater.update_dir())
    assert done.returncode == 2, done.stderr.decode("utf-8", "replace")
    assert kit.tree(root) == before and not os.path.exists(path) and _entry(runonce, path) is None
