"""What kind of build this is. `package_app.py --release` sets RELEASE_BUILD to True for the freeze (and puts the file
back after), so it is True only inside a release's Surasura.exe. A release build ignores every test-only override —
today the update check's local folder (`update_checker.UPDATE_SOURCE_ENV`).

Every freeze also appends BUILD_ID = "<id>" (the id `_internal/build_stamp.json` records), so a program can tell its own
build from its folder's (S3.1 D18): `stamp_skew()`. From source BUILD_ID stays None and nothing is compared. Light by
rule: the command line imports this at start (no tkinter, Qt or pandas)."""
import json
import os
import sys

RELEASE_BUILD = False
BUILD_ID = None
BUILD_COMMIT = None    # a freeze from a git tree appends BUILD_COMMIT = "<public>[/<private>]" (`package_app.source_commit`)

RUNNING_SUFFIX = ".Running"      # <data name>.Running: Inno Setup's AppMutex (packaging/surasura.iss)
_running = None                  # the mutex's handle, held for the process's life


def stamp_skew():
    """None when this program and `_internal/build_stamp.json` are the same build, or when running from source (no
    stamp to compare). Otherwise a dict saying how they differ: {"program": {version, build_id}, "folder": {version,
    build_id} or None (no stamp, or one that can't be read)}."""
    if not getattr(sys, "frozen", False):
        return None
    from app import __version__
    from app.path_utils import BUILD_STAMP, get_base_path
    program = {"version": __version__, "build_id": BUILD_ID}
    try:
        with open(os.path.join(get_base_path(), BUILD_STAMP), "r", encoding="utf-8-sig") as f:
            stamp = json.load(f)
        folder = {"version": stamp.get("version"), "build_id": stamp.get("build_id")}
    except (OSError, ValueError, AttributeError):
        folder = None
    if folder == program and BUILD_ID:
        return None
    return {"program": program, "folder": folder}


def skew_text(skew):
    """The plain words for a `stamp_skew()` answer."""
    folder = skew.get("folder")
    if folder is None:
        return ("Surasura's program files are incomplete: its _internal folder has no build stamp. "
                "Install Surasura again.")
    return (f"Surasura's program files are from two different builds (this program is {skew['program']['version']}, "
            f"its _internal folder is {folder.get('version')}). Install Surasura again, or finish its update.")


def hold_running_mutex():
    """The frozen program's `<data name>.Running` named mutex (Windows), held until the process ends: Inno Setup's
    AppMutex, so Setup and the uninstaller wait while any Surasura program runs. Never raises; a failure is only a
    missing mark. -> the handle, or None (from source, off Windows, or on failure)."""
    global _running
    if _running is None and getattr(sys, "frozen", False) and sys.platform == "win32":
        try:
            from app.path_utils import data_name
            _running = create_mutex(data_name() + RUNNING_SUFFIX)
        except Exception:
            _running = None
    return _running


def create_mutex(name):
    """CreateMutexW(NULL, FALSE, name) -> the handle (it opens the mutex when another process made it), or None."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    return kernel32.CreateMutexW(None, False, name) or None
