"""A cancelled update's stage that Windows won't let go never blocks the next update (a Send report, 2026-11-18).

The stage hard-links the installed program's unchanged files (no second copy of ~500 MB). Windows refuses to delete
any link of a program file that is loaded — the window's own DLLs — so while Surasura runs, a cancel's
`discard_staged` (rmtree, errors ignored) leaves update\\stage-<ver> behind, and the next *Update now* stopped on
`os.makedirs(stage)`: "[WinError 183] Cannot create a file when that file already exists". Every retry of that version
failed until nothing of Surasura ran. What must hold now: a leftover is tried again, else the update stages beside it
under a fresh name; the leftovers go at a start once nothing holds them — never an armed update's, never one under way,
never Go back's kept version; and a disk error while staging is said in words, never a bare WinError.

The install is the update kit's (a Japanese-named program folder beside a Japanese and Chinese library); the held file
is a real DLL loaded into this process, the way the running window holds its own."""
import ctypes
import errno
import os
import shutil
import sys

import pytest

from app import updater
from tests import update_kit as kit
from tests.test_updater_assemble import _info, _update_folder_names


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    kit.isolate_registry(monkeypatch)
    monkeypatch.setattr(updater, "STAGE_RETRIES", (0, 0, 0), raising=False)       # the pauses are an antivirus's; not timed here


@pytest.fixture
def loaded(tmp_path):
    """-> load(path): a real DLL copied to `path` and loaded into this process (as the window loads its own); unloaded
    at the end, so the temp folder can go."""
    source = os.path.join(sys.base_prefix, "DLLs", "sqlite3.dll")
    if sys.platform != "win32" or not os.path.isfile(source):
        pytest.skip("Windows' rule for loaded program files (the real DLL this needs is Python's own sqlite3.dll)")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryW.restype = ctypes.c_void_p
    k32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
    k32.FreeLibrary.argtypes = [ctypes.c_void_p]
    handles = []

    def load(path):
        shutil.copyfile(source, path)
        handle = k32.LoadLibraryW(str(path))
        assert handle, f"LoadLibraryW failed ({ctypes.get_last_error()})"
        handles.append(handle)
        return handle

    def unload():
        while handles:
            k32.FreeLibrary(handles.pop())
    load.unload = unload
    yield load
    unload()


def _stage_names():
    return [n for n in _update_folder_names() if n.startswith(updater.STAGE_PREFIX)]


def test_a_stage_holding_a_running_programs_file_never_blocks_the_next_update(tmp_path, monkeypatch, loaded):
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    first = updater.prepare_update(_info())["staged"]
    # The window runs: one of its program's files is loaded, and the stage holds a hard link of it — as every
    # unchanged DLL of the real program is linked.
    held = root / "_internal" / "held.dll"
    loaded(held)
    os.link(held, os.path.join(first, "_internal", "held.dll"))
    kit.write_tree(updater.update_dir(), {f"previous/{kit.OLD}/Surasura.exe": b"MZ old",
                                          f"previous/{kit.OLD}.files.json": b"{}"})
    updater.discard_staged()                                       # the cancel
    # Windows 10 1809 (the learners' LTSC laptops) keeps a link of a loaded program file, so the cancel leaves the
    # stage; a newer Windows (GitHub's runners) lets it go. Either way the next update goes through.
    kept = os.path.isdir(first)

    marker = updater.prepare_update(_info())                       # *Update now* again: was WinError 183

    stage = marker["staged"]
    assert stage == updater.stage_dir(kit.NEW) + ("-1" if kept else "")
    assert os.path.dirname(stage) == updater.update_dir()
    assert kit.tree(stage) == kit.digests(kit.program(kit.NEW)), "the complete program, nothing of the leftover"
    assert marker["swapper"] == os.path.join(stage, "updater.exe")
    assert not os.path.exists(updater.marker_path()), "nothing armed"
    assert sorted(os.listdir(updater.previous_root())) == [kit.OLD, f"{kit.OLD}.files.json"], "Go back's, untouched"
    # A third try (another cancel, another *Update now*) finds a name too.
    updater.discard_staged()
    assert updater.prepare_update(_info())["staged"] in (updater.stage_dir(kit.NEW), updater.stage_dir(kit.NEW) + "-1")

    # Surasura closed and opened again: nothing holds the links now, so the start clears every leftover.
    loaded.unload()
    assert updater.clean_leftovers() is True
    assert _stage_names() == [] and "previous" in _update_folder_names()
    assert sorted(os.listdir(updater.previous_root())) == [kit.OLD, f"{kit.OLD}.files.json"]


def test_a_leftover_an_antivirus_lets_go_of_is_retried_and_the_stage_keeps_its_name(tmp_path, monkeypatch):
    # A scan holds the new files for a moment: the first removals fail, a later try takes it — no fresh name needed.
    kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {f"stage-{kit.NEW}/Surasura.exe": b"MZ scanned"})
    real, refusals = shutil.rmtree, [2]

    def scanned(path, ignore_errors=False, onerror=None, **kw):
        if os.path.basename(str(path)) == f"stage-{kit.NEW}" and refusals[0]:
            refusals[0] -= 1
            return                                                 # ignore_errors: it just stays
        return real(path, ignore_errors=ignore_errors, onerror=onerror, **kw)
    monkeypatch.setattr(updater.shutil, "rmtree", scanned)
    marker = updater.prepare_update(_info())
    assert marker["staged"] == updater.stage_dir(kit.NEW) and refusals == [0]
    assert kit.tree(marker["staged"]) == kit.digests(kit.program(kit.NEW))
    assert _stage_names() == [f"stage-{kit.NEW}"]


def test_names_run_out_only_in_words(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "STAGE_NAMES", 2)
    kit.write_tree(updater.update_dir(), {f"stage-{kit.NEW}/a": b"x", f"stage-{kit.NEW}-1/a": b"x"})
    real = shutil.rmtree
    monkeypatch.setattr(updater.shutil, "rmtree", lambda path, ignore_errors=False, **kw: (
        None if os.path.basename(str(path)).startswith("stage-") else real(path, ignore_errors=ignore_errors, **kw)))
    with pytest.raises(updater.UpdateError) as caught:
        updater.prepare_update(_info())
    assert "WinError" not in str(caught.value) and "close Surasura and open it again" in str(caught.value)
    assert sorted(_stage_names()) == [f"stage-{kit.NEW}", f"stage-{kit.NEW}-1"], "the leftovers are never emptied"


def test_a_disk_error_while_staging_is_said_in_words_never_a_winerror(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    denied = OSError(errno.EACCES, "Access is denied", "スラスラ.exe")
    denied.winerror = 5

    def refused(*args, **kwargs):
        raise denied
    monkeypatch.setattr(updater, "_extract", refused)
    with pytest.raises(updater.UpdateError) as caught:
        updater.prepare_update(_info())
    said = str(caught.value)
    assert "WinError" not in said and "Errno" not in said and "Access is denied" in said
    assert "couldn't be prepared on this PC" in said
    assert _stage_names() == [], "any failure leaves nothing staged"


def test_the_start_clears_leftovers_and_keeps_go_back_and_the_swapper(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {
        f"stage-{kit.NEW}/Surasura.exe": b"MZ", f"stage-{kit.NEW}-1/_internal/語彙.txt": "上層部\n".encode("utf-8"),
        f"download-{kit.NEW}/part-0.zip": b"PK", f"installer-{kit.NEW}/setup.exe": b"MZ",
        f"previous/{kit.OLD}/Surasura.exe": b"MZ old", f"previous/{kit.OLD}.files.json": b"{}",
        "swapper/updater-3.0.1.exe": b"MZ swapper"})
    assert updater.clean_leftovers() is True
    assert _update_folder_names() == ["previous", "swapper"]
    held = updater.take_update_lock(looks=1)
    assert held is not None, "the update lock was let go"
    updater.drop_update_lock(held)


def test_the_start_never_clears_an_armed_update(tmp_path, monkeypatch):
    # A swap cut off half-way keeps its marker for the recovery Windows runs at the next sign-in: its stage stays.
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {f"stage-{kit.NEW}/Surasura.exe": b"MZ", updater.MARKER_NAME: b"{}"})
    assert updater.clean_leftovers() is False
    assert f"stage-{kit.NEW}" in _update_folder_names()


def test_the_start_never_clears_an_update_under_way(tmp_path, monkeypatch):
    # Another window's or a command line's *Update now* holds the lock while it downloads into its stage.
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {f"stage-{kit.NEW}/Surasura.exe": b"MZ", f"download-{kit.NEW}/p.zip": b"PK"})
    held = updater.take_update_lock(looks=1)
    try:
        assert updater.clean_leftovers() is False
        assert _update_folder_names() == [f"download-{kit.NEW}", f"stage-{kit.NEW}"]
    finally:
        updater.drop_update_lock(held)


def test_with_nothing_left_the_start_never_touches_the_update_lock(tmp_path, monkeypatch):
    # The lock is every process's "an update is staged" signal (the re-order, the command line look at it): a start
    # with nothing to clear never takes it, even for a moment.
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {f"previous/{kit.OLD}/Surasura.exe": b"MZ old"})
    taken = []
    monkeypatch.setattr(updater, "take_update_lock", lambda *a, **k: taken.append(1))
    assert updater.clean_leftovers() is False
    assert taken == [] and _update_folder_names() == ["previous"]


def test_a_clear_that_fails_never_raises(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {f"stage-{kit.NEW}/Surasura.exe": b"MZ"})

    def broken():
        raise PermissionError(errno.EACCES, "Access is denied")
    monkeypatch.setattr(updater, "discard_staged", broken)
    assert updater.clean_leftovers() is False
    held = updater.take_update_lock(looks=1)
    assert held is not None, "the lock is let go even when the clear fails"
    updater.drop_update_lock(held)


def test_the_lock_is_free_while_the_start_clears(tmp_path, monkeypatch):
    # The clear may take seconds (a stage of hundreds of MB): the lock — another process's "an update is staged" — is
    # only looked at, and let go before the folders go, so nothing else reads an update that isn't there meanwhile.
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {f"stage-{kit.NEW}/Surasura.exe": b"MZ"})
    real, seen = updater.discard_staged, []

    def clearing():
        held = updater.take_update_lock(looks=1)
        seen.append(held is not None)
        if held is not None:
            updater.drop_update_lock(held)
        real()
    monkeypatch.setattr(updater, "discard_staged", clearing)
    assert updater.clean_leftovers() is True
    assert seen == [True], "the lock was free while the folders went"
    assert _stage_names() == []
