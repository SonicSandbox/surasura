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
