"""In-app update stager.

Turns an available :class:`~app.update_checker.UpdateInfo` into an armed, verified update:
download the app-code package -> checksum it -> extract & validate it -> (once nothing else of
Surasura's runs, K75) write the ``pending_update.json`` marker and start the helper. The actual
on-disk swap is performed AFTER the app exits by the standalone ``updater.exe`` (see
``updater_helper.py``); this module only stages and hands off, then reads back the result on the
next launch.

What is swapped comes from the release: since 2.5 its update.json lists every file with its
sha256 (``files``: Surasura.exe, surasura-cli.exe, RELEASE_NOTES.md, anything under ``_internal/``
— an allow-list, `resolve_destination`); a release without the list gets the three targets 2.4.0
swapped (the exe, ``_internal/templates``, RELEASE_NOTES.md). A file the release adds is created
by the swap; if the swap fails, the relaunched app deletes it (`consume_result`), since the
helper's rollback only restores what existed.

A 3.x release (``format: 2``, S3.1 D4, D9) is the whole program, downloaded by part: `prepare_update` hashes the
installed program, downloads only the parts holding a changed or missing file (each checked by its sha256), assembles
the complete new program in ``<Houseki local root>\\update\\stage-<ver>`` (unchanged files hard-linked from the
install, else copied), checks every file against the release, and returns the swapper's marker. `arm_and_launch`
copies the NEW release's ``updater.exe`` out to ``update\\swapper\\`` and starts it: it swaps the program's entries
by renames, proves the result and keeps one previous version for `prepare_go_back`. Only an INSTALLED program
updates itself (`is_installed`); a portable one is updated by hand.

Deliberately UI-free (no tkinter) so every step is unit-testable, and deliberately narrow in
what it touches: only the program's own files, plus its state in ``<Houseki local root>\\update\\`` (the marker,
the result, the failure report, the staging, the previous version: S3.1 D9 — a whole-program swap would take
anything kept in the program folder along). It NEVER reads or writes User Files, data, results, or settings.json —
user data is entirely outside the blast radius, and the swap never moves them should they sit in the program folder.
"""
import os
import sys
import json
import re
import time
import hashlib
import zipfile
import shutil
import platform
import threading
import subprocess
import urllib.request

from app import __version__
from app import path_utils

_USER_AGENT = "Surasura-Readability-Analyzer"

STAGING_DIRNAME = ".update_staging"       # 2.x's, beside the exe: `consume_result` reads 2.x's state there once
BACKUP_DIRNAME = ".update_backup"
MARKER_NAME = "pending_update.json"
ADDED_NAME = "pending_update_added.json"    # what the swap creates: the helper deletes the marker, so it is kept here
RESULT_NAME = "last_update_result.json"
REPORT_NAME = "update_report.txt"
UPDATER_EXE_NAME = "updater.exe"
UPDATE_DIRNAME = "update"                   # <Houseki local root>\update (S3.1 D9)
STAGE_PREFIX, DOWNLOAD_PREFIX, INSTALLER_PREFIX = "stage-", "download-", "installer-"
PREVIOUS_DIRNAME, SWAPPER_DIRNAME = "previous", "swapper"
FOLDER_FORMAT = 3                           # the 3.x swapper's marker (updater_helper.run_folder)
WAIT_TIMEOUT = 60                           # what the swapper gives every process of the program to end


class UpdateError(Exception):
    """Raised when staging an update fails. Nothing is armed when this is raised."""


# ---------------------------------------------------------------------------
# Locations. The update's state lives in <Houseki local root>\update\ (S3.1 D9): the marker, the result, the report,
# 2.x-shaped staging (`staging_dir`), a 3.x release's assembled program (`stage_dir`), the previous version kept for
# Go back (`previous_root`) and the copied-out swapper (`swapper_dir`). The program folder holds the programs
# (Surasura.exe, surasura-cli.exe, updater.exe) and _internal (templates/ and the runtime; the app code is inside the
# exes, not loose under _internal).
# ---------------------------------------------------------------------------
def _user_dir():
    return path_utils.get_user_data_path()


def _internal_dir():
    return path_utils.get_base_path()


def update_dir():
    """<Houseki local root>\\update — made when missing (a test root's: <test root>/local_root/update)."""
    path = os.path.join(path_utils.local_data_root(), UPDATE_DIRNAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def _state(folder=None):
    """The update's own files: in the update folder — or, given 2.x's state `folder` (the exe's), where 2.x kept them."""
    if folder is None:
        d = update_dir()
        dirs = [os.path.join(d, "staging"), os.path.join(d, "backup")]
        return {"marker": os.path.join(d, MARKER_NAME), "result": os.path.join(d, RESULT_NAME),
                "added": os.path.join(d, ADDED_NAME), "dirs": dirs, "update_dir": d}
    return {"marker": os.path.join(folder, MARKER_NAME), "result": os.path.join(folder, RESULT_NAME),
            "added": os.path.join(folder, ADDED_NAME),
            "dirs": [os.path.join(folder, STAGING_DIRNAME), os.path.join(folder, BACKUP_DIRNAME)]}


def marker_path():
    return _state()["marker"]


def result_path():
    return _state()["result"]


def staging_dir():
    return _state()["dirs"][0]


def backup_dir():
    return _state()["dirs"][1]


def added_path():
    return _state()["added"]


def stage_dir(version):
    """Where a 3.x release's complete program is assembled: update\\stage-<version>."""
    return os.path.join(update_dir(), STAGE_PREFIX + _version_name(version))


def previous_root():
    """update\\previous: the one version kept for Go back, as previous\\<version>\\ + <version>.files.json."""
    return os.path.join(update_dir(), PREVIOUS_DIRNAME)


def swapper_dir():
    return os.path.join(update_dir(), SWAPPER_DIRNAME)


def updater_exe_path():
    return os.path.join(_install_dir(), UPDATER_EXE_NAME)


def update_state_path():
    """This install's update state (S1.1-2): in the per-install local folder, never settings.json."""
    return os.path.join(path_utils.get_local_data_path(), "update_state.json")


def _read_state():
    try:
        with open(update_state_path(), "r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError, RuntimeError):
        return {}


def record_failed_version(version):
    """A version whose in-app update failed: never tried in place again (the loop-breaker). Written atomically to
    update_state.json — nothing automatic writes settings.json. -> True when written; never raises."""
    try:
        path = update_state_path()
        state = _read_state()
        state["failed_update_version"] = version
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"Update: could not record the failed version ({e})")
        return False


def failed_version(settings=None):
    """The version whose in-app update failed: update_state.json's — else one 2.4.0 left in settings.json, read there
    (never written back; the dashboard's next save drops the key) and kept in update_state.json from then on."""
    version = str(_read_state().get("failed_update_version", "") or "")
    if version:
        return version
    legacy = str((settings or {}).get("failed_update_version", "") or "") if isinstance(settings, dict) else ""
    if legacy:
        record_failed_version(legacy)
    return legacy


def report_path():
    return os.path.join(update_dir(), REPORT_NAME)


def is_installed():
    """An INSTALLED program (S3.1 D3, D9): frozen, and library.json names this program's folder — or, should that
    note be unreadable, its folder holds Inno's unins000.dat. Anything else (a source run, dist\\Surasura, a test
    build, an unzipped copy) is portable, and is updated by hand."""
    if not path_utils.is_frozen():
        return False
    if path_utils.installed_library():
        return True
    return os.path.isfile(os.path.join(_install_dir(), "unins000.dat"))


def can_auto_apply(info=None):
    """Auto-apply is only possible in a frozen build that shipped the bundled updater.exe — and, for a release that
    lists its files, only when every destination is one the in-place update may write (`resolve_files`). A 3.x
    release (format 2): an installed program, and a package whose every path the assembler accepts."""
    if getattr(info, "format", 1) == 2:
        if not is_installed():
            return False
        package = getattr(info, "package", None)
        if isinstance(package, dict):
            try:
                package_files(package)
            except UpdateError:
                return False
        return True
    if not (path_utils.is_frozen() and os.path.exists(updater_exe_path())):
        return False
    if info is not None and getattr(info, "files", None) is not None:
        try:
            resolve_files(info.files)
        except UpdateError:
            return False
    return True


# ---------------------------------------------------------------------------
# The release's file list (K99): {name, dest, kind, sha256} per entry.
#   name    a flat staging key: the entry's path at the top of the app package zip
#   dest    relative to the install folder; only Surasura.exe, surasura-cli.exe, RELEASE_NOTES.md
#           or something under _internal/ (ASCII case ignored, no absolute path, no "..", no name
#           Windows reserves or reads as another, resolved through junctions and kept inside the
#           install folder) — anything else: FULL. The list must name Surasura.exe.
#   kind    "file" or "dir"
#   sha256  a file's sha256, or a dir's `tree_sha256`
# ---------------------------------------------------------------------------
_ROOT_FILES = {"surasura.exe", "surasura-cli.exe", "release_notes.md"}
_HEX = set("0123456789abcdef")
_RESERVED = {"con", "prn", "aux", "nul"} | {f"{d}{i}" for d in ("com", "lpt") for i in range(1, 10)}


def _install_dir():
    """The program folder: an installed program's is the exe's (its user data is the library, elsewhere); otherwise
    2.x's rule, the user data folder — the exe's folder in a portable build."""
    if path_utils.is_frozen() and path_utils.installed_library():
        return os.path.dirname(sys.executable)
    return _user_dir()


def _inside(path, folder):
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    return a != b and a.startswith(b.rstrip(os.sep) + os.sep)


def _plain_parts(dest):
    """A relative path from a release -> its parts, or UpdateError: no absolute path, no "..", no name Windows
    reserves or reads as another (a device, an 8.3 short name, a stream, a trailing dot or space)."""
    if not isinstance(dest, str) or not dest.strip():
        raise UpdateError(f"destination {dest!r} is empty")
    text = dest.replace("\\", "/")
    if text.startswith("/") or os.path.isabs(dest) or (len(text) > 1 and text[1] == ":"):
        raise UpdateError(f"destination {dest!r} is absolute")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise UpdateError(f"destination {dest!r} leaves the install folder")
    if any(":" in p or p != p.rstrip(" .") or any(ord(c) < 32 or c in '<>"|?*' for c in p) for p in parts):
        raise UpdateError(f"destination {dest!r} is not a plain path")
    # .lower(), never .casefold(): Windows ignores ASCII case only (casefold reads ſurasura.exe as surasura.exe).
    if any(p.lower().split(".")[0] in _RESERVED or re.search(r"~[0-9]", p) for p in parts):
        raise UpdateError(f"destination {dest!r} names a device or a short (8.3) name")
    return parts


def resolve_destination(dest, install_dir=None):
    """`dest` (relative, from a release's list) -> the absolute path it names, or UpdateError when the in-place
    update may not write there."""
    install_dir = install_dir or _install_dir()
    parts = _plain_parts(dest)
    folded = [p.lower() for p in parts]
    if not ((len(folded) == 1 and folded[0] in _ROOT_FILES) or (len(folded) >= 2 and folded[0] == "_internal")):
        raise UpdateError(f"destination {dest!r} is not one an in-place update may write")
    path = os.path.join(install_dir, *parts)
    if not _inside(path, install_dir):
        raise UpdateError(f"destination {dest!r} resolves outside the install folder")
    if len(folded) >= 2 and not _inside(path, os.path.join(install_dir, parts[0])):
        raise UpdateError(f"destination {dest!r} resolves outside _internal")
    return path


def resolve_files(files, install_dir=None):
    """A release's `files` list -> the targets it names, each {name, kind, dest (absolute), sha256}; UpdateError
    when any entry is malformed or not allowed (the update is then a manual one)."""
    if not isinstance(files, list) or not files:
        raise UpdateError("the release's file list is empty or not a list")
    targets, names, dests = [], set(), set()
    for entry in files:
        if not isinstance(entry, dict):
            raise UpdateError("a file list entry is not an object")
        name, kind, sha = entry.get("name"), entry.get("kind", "file"), str(entry.get("sha256") or "").lower()
        if (not isinstance(name, str) or not name or name in (".", "..") or any(c in name for c in "/\\:")
                or name.casefold() in names):
            raise UpdateError(f"file list name {name!r} is not a unique flat name")
        if kind not in ("file", "dir"):
            raise UpdateError(f"file list kind {kind!r} for {name!r}")
        if len(sha) != 64 or not set(sha) <= _HEX:
            raise UpdateError(f"{name!r} has no sha256")
        dest = resolve_destination(entry.get("dest"), install_dir)
        if os.path.normcase(dest) in dests:
            raise UpdateError(f"{entry.get('dest')!r} is named twice")
        names.add(name.casefold())
        dests.add(os.path.normcase(dest))
        targets.append({"name": name, "kind": kind, "dest": dest, "sha256": sha})
    root = install_dir or _install_dir()
    if not any(t["kind"] == "file" and os.path.relpath(t["dest"], root).lower() == EXE_NAME.lower() for t in targets):
        raise UpdateError("the release's file list doesn't name Surasura.exe")
    return targets


def tree_sha256(folder):
    """A folder's sha256 for the file list: every file's relative path (with /) and its sha256, sorted."""
    lines = []
    for root, dirs, files in os.walk(folder):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            lines.append(f"{rel}\0{sha256_file(full)}\n")
    h = hashlib.sha256()
    for line in sorted(lines):
        h.update(line.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# What holds this install's programs (K75). updater.exe waits only on the app's own PID, so everything else of
# Surasura's that runs this install's exe is waited for HERE, before the helper is launched.
# ---------------------------------------------------------------------------
EXE_NAME = "Surasura.exe"
CLI_EXE_NAME = "surasura-cli.exe"

_HOLD = threading.Event()       # set from "Update now" until the update is cancelled (or the app exits for it)
_DEFERRED = []                  # children asked for meanwhile: started when the update is cancelled
_DEFERRED_LOCK = threading.Lock()


def hold_children():
    """"Update now" was pressed: no new child process of Surasura's starts until `release_children`."""
    _HOLD.set()


def children_held():
    return _HOLD.is_set()


def defer_child(start):
    """While children are held, keep `start` (a zero-arg callable that starts one) for `release_children` -> True;
    otherwise False, and the caller starts it now."""
    with _DEFERRED_LOCK:
        if not _HOLD.is_set():
            return False
        _DEFERRED.append(start)
        return True


def release_children(start=True):
    """The update was cancelled: children may start again, and those asked for meanwhile start now (on the
    caller's thread) — or, with `start=False` (the dashboard is closing), are dropped: they would outlive it, and an
    automatic one asks again on the next start. Never raises."""
    with _DEFERRED_LOCK:
        _HOLD.clear()
        waiting = list(_DEFERRED) if start else []
        _DEFERRED.clear()
    for start in waiting:
        try:
            start()
        except Exception as e:
            print(f"Update: a deferred task could not start ({e})")


def _install_images():
    """This install's programs: the paths a process must run to hold its files. A source checkout has none."""
    if not path_utils.is_frozen():
        return []
    folder = os.path.dirname(sys.executable)
    return [os.path.join(folder, EXE_NAME), os.path.join(folder, CLI_EXE_NAME)]


def _snapshot():
    """Every process now: [(pid, parent pid, exe name)] (Windows; elsewhere [])."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)   # our own prototypes, never windll's shared ones

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    found = []
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)              # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            found.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return found


def _image_of(pid):
    """The full path of `pid`'s program, or None (gone, or not this user's to ask)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(0x1000, False, pid)             # QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        return buf.value if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else None
    finally:
        k32.CloseHandle(handle)


def _processes_running(images):
    """{pid: image path} of every running process whose program is one of `images` (Windows; elsewhere {} — the
    in-place updater is Windows-only). One snapshot of the process list, then the full path asked only of
    processes whose exe NAME matches."""
    if sys.platform != "win32" or not images:
        return {}
    wanted = {os.path.normcase(os.path.abspath(i)) for i in images}
    names = {os.path.basename(i).lower() for i in wanted}
    found = {}
    for pid, _parent, exe in _snapshot():
        if exe.lower() in names:
            image = _image_of(pid)
            if image and os.path.normcase(os.path.abspath(image)) in wanted:
                found[pid] = image
    return found


def _processes_in(folder):
    """{pid: image path} of every running process whose program lives inside `folder` — any program, the K75 wait
    widened as the swapper's own wait is (S3.1 D9). An image holding ~ (a short 8.3 path) is resolved too."""
    if sys.platform != "win32" or not folder:
        return {}
    prefixes = {os.path.normcase(p).rstrip("\\/") + os.sep for p in (os.path.abspath(folder),
                                                                    os.path.realpath(folder))}
    found = {}
    for pid, _parent, _exe in _snapshot():
        image = _image_of(pid) if pid else None
        if not image:
            continue
        names = {os.path.normcase(image)}
        if "~" in image:
            names.add(os.path.normcase(os.path.realpath(image)))
        if any(n.startswith(p) for n in names for p in prefixes):
            found[pid] = image
    return found


STOP_GRACE = 20.0       # seconds a program asked to close its windows has, before it is ended


def _close_windows(pid):
    """Ask each visible top-level window of `pid` to close (WM_CLOSE: the program's own close, as its user's click
    on X — run after whatever it is doing). -> how many were asked. Windows only."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    each_window = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u32.EnumWindows.argtypes = [each_window, wintypes.LPARAM]
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.IsWindowVisible.argtypes = [wintypes.HWND]
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    windows = []

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u32.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True

    u32.EnumWindows(each_window(visit), 0)
    for hwnd in windows:
        u32.PostMessageW(hwnd, 0x0010, 0, 0)                     # WM_CLOSE
    return len(windows)


def stop_pid(pid, grace=None):
    """*Stop it*: a program with a window is asked to close it, as its user would — a Content Manager mid-Graduate
    finishes the move and saves before it closes; one with no window (Generate, the パターン build), or still running
    `STOP_GRACE` seconds later, is ended. Returns at once (the grace runs on a thread). Never raises."""
    try:
        if sys.platform != "win32":
            import signal
            os.kill(int(pid), signal.SIGTERM)
            return
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x00100001, False, int(pid))      # SYNCHRONIZE | PROCESS_TERMINATE
        if not handle:
            return
        asked = _close_windows(int(pid))

        def end():
            try:
                wait_ms = int((STOP_GRACE if grace is None else grace) * 1000)
                if not asked or k32.WaitForSingleObject(handle, wait_ms) != 0:     # 0: it closed itself
                    k32.TerminateProcess(handle, 1)
            finally:
                k32.CloseHandle(handle)

        if asked:
            threading.Thread(target=end, daemon=True).start()
        else:
            end()
    except Exception:
        pass


def _stopper(process):
    def stop():
        try:
            if process.poll() is None:
                stop_pid(process.pid)       # the Popen's handle keeps its id from being reused meanwhile
        except Exception:
            pass
    return stop


def running_children(active_processes=(), images=None):
    """Everything of Surasura's that runs now besides this window, each `{"pid", "name", "stop"}` — what an update
    waits for: the dashboard's own children (`active_processes`, named by their `surasura_desc`), Backfill's
    パターン build, and any process running this install's Surasura.exe or surasura-cli.exe other than this one (the
    splicer and the importers' children, a command line hato started). Any other program running from this
    install's folder (an uninstaller, a helper a later version adds) is listed too, wait-only (`stop` None: never
    ended from here). `images` overrides which programs count (a test, a source checkout; exactly those, no
    folder). The auto-Generate guard does NOT ask this (Backfill's build goes behind a Generate)."""
    found, seen = [], {os.getpid()}
    for process in list(active_processes or ()):
        try:
            if process.poll() is None and process.pid not in seen:
                seen.add(process.pid)
                found.append({"pid": process.pid, "name": getattr(process, "surasura_desc", "") or "A Surasura task",
                              "stop": _stopper(process)})
        except Exception:
            pass
    backfill = sys.modules.get("modules.junban.backfill")     # only when it was ever used: never imported here
    process = getattr(backfill, "rebuild_process", lambda: None)() if backfill else None
    if process is not None and process.pid not in seen:
        seen.add(process.pid)
        found.append({"pid": process.pid, "name": "Building パターン data", "stop": _stopper(process)})
    folder = {}
    try:
        mine = _install_images() if images is None else images
        others = _processes_running(mine)
        folders = {os.path.normcase(os.path.dirname(i)) for i in mine} if images is None else set()
        if len(folders) == 1:
            folder = _processes_in(os.path.dirname(mine[0]))
    except Exception as e:
        print(f"Update: could not list running programs ({e})")
        others = {}
    for pid, image in sorted(others.items()):
        if pid in seen:
            continue
        seen.add(pid)
        cli = os.path.basename(image).lower() == CLI_EXE_NAME.lower()
        found.append({"pid": pid, "name": "Surasura's command line" if cli else "Another Surasura window",
                      "stop": (lambda p=pid: stop_pid(p))})
    for pid, image in sorted(folder.items()):
        if pid not in seen:
            seen.add(pid)
            found.append({"pid": pid, "name": os.path.basename(image), "stop": None})
    return found


def can_update_now(active_processes=(), images=None):
    """The one "may the update start now?" seam: nothing of Surasura's holds this install's programs. The library
    store's helper is the one exception that isn't a child: `hold_library_locks` waits for it at the hand-over."""
    return not running_children(active_processes, images)


def hold_library_locks(languages=("ja", "zh")):
    """The library store's maintenance lock for every language (Library_Store_Spec §7), each taken without
    waiting and held until this process exits — the swap happens after it — so no helper runs from the old exe
    while it is replaced. A new helper never starts meanwhile: the update lock, held since "Update now", is the
    store's "update staged" signal (S1.1). -> the held locks, or None while a helper holds one (the wait goes
    on, as for a running child)."""
    try:
        from app import library_store
    except Exception:
        return []                                  # no store in this build: nothing to wait for
    held = []
    for language in languages:
        try:
            db_path = library_store.library_db_path(language, path_utils.get_data_path(language))
        except Exception:
            continue
        if not os.path.exists(os.path.dirname(db_path)):
            continue                               # no store was ever made here
        lock = library_store.MaintenanceLock(db_path)
        try:
            taken = lock.try_acquire()
        except OSError:
            taken = True                           # its lock file can't be opened: nothing can hold it either
            lock = None
        if not taken:
            lock.close()
            release_library_locks(held)
            return None
        if lock is not None:
            held.append(lock)
    return held


def release_library_locks(locks):
    for lock in locks or ():
        try:
            lock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Download / verify / extract
# ---------------------------------------------------------------------------
def sha256_file(path, _bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, progress_cb=None, timeout=60):
    """Stream ``url`` to ``dest`` (creating parent dirs). Calls progress_cb(done,total)."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as out:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress_cb:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        pass
    return dest


def extract_and_validate(zip_path, payload_dir, files=None):
    """Extract the app package and confirm its structure.

    The package carries the code-bearing executable plus the report templates (the only two
    things a minor release changes): a top-level ``Surasura.exe`` and a ``templates/`` dir
    with at least one HTML file. Version identity is guaranteed separately by the download's
    sha256 matching the release's update.json, so no version is re-parsed here. Guards against
    path traversal. Returns True/False for a merely-invalid payload; raises only on a
    hostile/corrupt archive.
    """
    if os.path.isdir(payload_dir):
        shutil.rmtree(payload_dir, ignore_errors=True)
    os.makedirs(payload_dir, exist_ok=True)

    root = os.path.abspath(payload_dir)
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            target = os.path.abspath(os.path.join(payload_dir, name))
            if target != root and not target.startswith(root + os.sep):
                raise UpdateError(f"unsafe path in archive: {name}")
        z.extractall(payload_dir)

    if files is not None:
        # The release's list: every entry staged under its name, with the bytes its sha256 names.
        for t in resolve_files(files):
            staged = os.path.join(payload_dir, t["name"])
            if t["kind"] == "file":
                if not os.path.isfile(staged) or sha256_file(staged) != t["sha256"]:
                    return False
            elif not os.path.isdir(staged) or tree_sha256(staged) != t["sha256"]:
                return False
        return True

    exe = os.path.join(payload_dir, EXE_NAME)
    templates = os.path.join(payload_dir, "templates")
    if not os.path.isfile(exe):
        return False
    if not os.path.isdir(templates):
        return False
    if not any(n.lower().endswith(".html") for n in os.listdir(templates)):
        return False
    return True


# ---------------------------------------------------------------------------
# Marker (the hand-off contract with updater.exe)
# ---------------------------------------------------------------------------
def build_marker(info, payload_dir, app_pid, wait_timeout=60):
    """Assemble the hand-off contract for updater.exe.

    Targets are the two things a minor update replaces: the code-bearing executable
    (``sys.executable`` — its embedded archive holds all the app code) and the loose
    ``_internal/templates`` dir. The exe carries an expected sha256 so the helper can verify
    the swapped-in bytes; templates are non-critical and verified only by structure.
    """
    base = _internal_dir()
    files = getattr(info, "files", None)
    if files is not None:
        # The release's list. A file gets its sha256 checked by the helper after the swap; a dir was checked when
        # it was staged (the helper can't hash a dir). `added`: the swap creates it — see arm_and_launch.
        targets = []
        for t in resolve_files(files):
            target = {"name": t["name"], "kind": t["kind"], "dest": t["dest"]}
            if t["kind"] == "file":
                target["sha256"] = t["sha256"]
            if not os.path.exists(t["dest"]):
                target["added"] = True
            targets.append(target)
        return _marker(info, payload_dir, app_pid, wait_timeout, base, targets)
    staged_exe = os.path.join(payload_dir, EXE_NAME)
    exe_sha = sha256_file(staged_exe) if os.path.isfile(staged_exe) else ""
    targets = [
        {"name": EXE_NAME, "kind": "file", "dest": sys.executable, "sha256": exe_sha},
        {"name": "templates", "kind": "dir", "dest": os.path.join(base, "templates")},
    ]
    # Optional: refresh the bundled release notes next to the exe so RELEASE_NOTES.md isn't stale
    # after an app update. Only added when the package actually carries it (older packages don't),
    # so this stays backward-compatible; non-critical, so no sha256 (swapped, rolled back with the rest).
    if os.path.isfile(os.path.join(payload_dir, "RELEASE_NOTES.md")):
        targets.append({"name": "RELEASE_NOTES.md", "kind": "file",
                        "dest": os.path.join(os.path.dirname(sys.executable), "RELEASE_NOTES.md")})
    return _marker(info, payload_dir, app_pid, wait_timeout, base, targets)


def _marker(info, payload_dir, app_pid, wait_timeout, base, targets):
    return {
        "target_version": info.version,
        "from_version": __version__,
        "app_pid": app_pid,
        "attempt": 0,
        "staging_dir": staging_dir(),
        "payload_dir": payload_dir,
        "base_dir": base,
        "backup_dir": backup_dir(),
        "targets": targets,
        "relaunch_exe": sys.executable,
        "result_path": result_path(),
        "wait_timeout": wait_timeout,
    }


def write_marker(marker):
    path = marker_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def prepare_update(info, progress_cb=None, window=True):
    """Download -> verify checksum -> extract & validate -> the marker, NOT written.

    Returns the marker (a dict). Nothing is armed: `pending_update.json` is written only by
    `arm_and_launch`, in the window's final callback right before the helper starts, so a cancel,
    a close, a crash or a sleep while the update waits (K75) leaves no marker and the next start
    reports nothing. Raises UpdateError on any failure, having cleaned up the staging dir. Does
    NOT launch the helper or exit the app.

    A 3.x release (format 2) is assembled (`_prepare_package`, S3.1 D4): run this on a worker thread — it hashes the
    installed program. `window`: the window started it, so the swapper shows its splash and proves the new window
    (False: a headless update, proven by its files and its command line alone).
    """
    if getattr(info, "format", 1) == 2:
        return _prepare_package(info, progress_cb, window)
    # Defense in depth: staging targets the frozen executable + _internal; refuse to run in a
    # source checkout, where those paths would point at the live repo. The GUI already gates
    # this behind can_auto_apply(); this is the backstop.
    if not path_utils.is_frozen():
        raise UpdateError("auto-update is only available in a packaged (frozen) build")

    if not info.app_package_url or not info.sha256:
        raise UpdateError("release has no app package or checksum")

    sd = staging_dir()
    if os.path.isdir(sd):
        shutil.rmtree(sd, ignore_errors=True)
    os.makedirs(sd, exist_ok=True)

    try:
        zip_path = os.path.join(sd, "app_package.zip")
        download(info.app_package_url, zip_path, progress_cb=progress_cb)

        if sha256_file(zip_path).lower() != info.sha256.lower():
            raise UpdateError("checksum mismatch — download corrupted or tampered")

        payload_dir = os.path.join(sd, "payload")
        if not extract_and_validate(zip_path, payload_dir, getattr(info, "files", None)):
            raise UpdateError("update package failed validation")

        return build_marker(info, payload_dir, os.getpid())
    except UpdateError:
        shutil.rmtree(sd, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(sd, ignore_errors=True)
        raise UpdateError(str(e))


def prepare_installer(info, progress_cb=None, window=True):
    """The 2.x -> 3.0 hand-off (S1.3-6): download the release's installer into staging and check its sha256. ->
    the staged installer {kind, path, args, ...} for `arm_and_launch`; nothing is launched here. Refuses anything
    but a frozen build and a release `update_checker.installer_ready` accepts (3.0 or later). A 3.x release (format
    2): the swapper's marker in installer mode (`_prepare_setup`, S3.1 D7)."""
    from app.update_checker import installer_ready
    if not path_utils.is_frozen():
        raise UpdateError("the installer hand-off runs only in a packaged (frozen) build")
    if not installer_ready(__version__, info):
        raise UpdateError("this release has no installer 2.x may hand over to")
    if getattr(info, "format", 1) == 2:
        return _prepare_setup(info, progress_cb, window)
    sd = staging_dir()
    shutil.rmtree(sd, ignore_errors=True)
    folder = os.path.join(sd, "installer")
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(str(info.installer.get("asset")).replace("\\", "/")) or "setup.exe"
    path = os.path.join(folder, name)
    try:
        download(info.installer_url, path, progress_cb=progress_cb)
        if sha256_file(path).lower() != str(info.installer["sha256"]).lower():
            raise UpdateError("checksum mismatch — the installer download is corrupted or tampered")
    except UpdateError:
        shutil.rmtree(sd, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(sd, ignore_errors=True)
        raise UpdateError(str(e))
    return {"kind": "installer", "path": path, "args": list(info.installer.get("args") or []),
            "target_version": info.version, "from_version": __version__}


def launch_installer(staged):
    """Start the installer detached (not through updater.exe: it replaces the whole install), so it outlives us."""
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    return subprocess.Popen([staged["path"]] + list(staged.get("args") or []), creationflags=flags, close_fds=True,
                            cwd=os.path.dirname(staged["path"]))


# ---------------------------------------------------------------------------
# 3.x: the whole program, downloaded by part and assembled (S3.1 D4, D9)
# ---------------------------------------------------------------------------
# Every top-level entry the program has shipped: a swap moves these (and whatever the new release names at the top) to
# previous\<from>\. Anything else in the program folder is someone else's and never moves: Inno's unins000.*, and the
# library's folders and settings should they sit there (an installed copy whose library.json can't be read runs
# portable) — KEPT_ENTRIES, which a release may never name either.
OWNED_ENTRIES = ("_internal", EXE_NAME, CLI_EXE_NAME, UPDATER_EXE_NAME, "README.md", "RELEASE_NOTES.md",
                 "UPDATE_INSTRUCTIONS.md")
KEPT_ENTRIES = ("User Files", "data", "results", "settings.json")
_VERSION_RE = re.compile(r"\d{1,6}(\.\d{1,6}){0,3}\Z")


def _version_name(version):
    """A version as a folder name (stage-<v>, previous\\<v>): digits and dots only, else UpdateError."""
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise UpdateError(f"{version!r} is not a version")
    return version


def _foreign_top(name):
    low = name.lower()
    return low in {k.lower() for k in KEPT_ENTRIES} or low.startswith("unins")


def package_files(package):
    """A 3.x release's file list -> [{path, parts, sha256, size, part}], or UpdateError: every path plain
    (`_plain_parts`), none of them the library's or the uninstaller's, none twice (ASCII case ignored, as Windows
    does), no file where another needs a folder, and the three programs named."""
    files = package.get("files") if isinstance(package, dict) else None
    if not isinstance(files, list) or not files:
        raise UpdateError("the release lists no files")
    out, seen, folders = [], set(), set()
    for entry in files:
        if not isinstance(entry, dict):
            raise UpdateError("a file list entry is not an object")
        parts = _plain_parts(entry.get("path"))
        if _foreign_top(parts[0]):
            raise UpdateError(f"{entry.get('path')!r} is not the program's to replace")
        key = "/".join(parts).lower()
        if key in seen:
            raise UpdateError(f"{entry.get('path')!r} is named twice")
        seen.add(key)
        folders.update("/".join(parts[:i]).lower() for i in range(1, len(parts)))
        sha, size = str(entry.get("sha256") or "").lower(), entry.get("size")
        if len(sha) != 64 or not set(sha) <= _HEX or not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise UpdateError(f"{entry.get('path')!r} has no sha256 or size")
        out.append({"path": "/".join(parts), "parts": parts, "sha256": sha, "size": size, "part": entry.get("part")})
    if seen & folders:
        raise UpdateError("the release names a file where another of its files needs a folder")
    for need in (EXE_NAME, CLI_EXE_NAME, UPDATER_EXE_NAME):
        if need.lower() not in seen:
            raise UpdateError(f"the release doesn't carry {need}")
    return out


def _package_parts(package):
    """A 3.x release's parts -> the list, each {name, asset, sha256, size}, or UpdateError."""
    parts = package.get("parts")
    if not isinstance(parts, list) or not parts or not all(
            isinstance(p, dict) and isinstance(p.get("name"), str) and isinstance(p.get("asset"), str)
            and isinstance(p.get("size"), int) and not isinstance(p.get("size"), bool) and p["size"] >= 0
            and len(str(p.get("sha256") or "")) == 64 and set(str(p["sha256"])) <= _HEX for p in parts):
        raise UpdateError("the release's parts aren't whole")
    return parts


class _Progress:
    """One progress for the whole staging — hashing the install, the downloads, the final check — reported through
    the caller's `progress_cb(done, total)` against one total fixed at the start (a part not needed counts as done)."""

    def __init__(self, cb, total):
        self.cb, self.total, self.done = cb, max(1, int(total)), 0

    def add(self, n):
        self.done = min(self.total, self.done + max(0, int(n)))
        if self.cb:
            try:
                self.cb(self.done, self.total)
            except Exception:
                pass

    def download(self):
        """A `download` progress_cb adding each chunk's bytes."""
        last = [0]

        def cb(done, _total):
            self.add(done - last[0])
            last[0] = done
        return cb


def _program_files(install, owned):
    """Every file under the program's own entries in `install` -> [(relative '/' path, full path, size)]. A folder
    that is a reparse point (a junction) is never walked into."""
    owned = {n.lower() for n in owned}
    found = []
    for name in sorted(os.listdir(install)):
        if name.lower() not in owned:
            continue
        full = os.path.join(install, name)
        if os.path.isfile(full):
            found.append((name, full, os.path.getsize(full)))
            continue
        for root, dirs, names in os.walk(full):
            dirs[:] = [d for d in sorted(dirs) if not _reparse(os.path.join(root, d))]
            for n in sorted(names):
                path = os.path.join(root, n)
                found.append((os.path.relpath(path, install).replace(os.sep, "/"), path, os.path.getsize(path)))
    return found


def _reparse(path):
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400) or os.path.islink(path)
    except OSError:
        return True


def _hash_program(listing, progress):
    """{lower-cased path: (path, size, sha256)} of `_program_files`' listing, each counted into `progress`."""
    hashed = {}
    for rel, full, size in listing:
        hashed[rel.lower()] = (rel, size, sha256_file(full))
        progress.add(size)
    return hashed


def _require_installed():
    """-> the program folder of an installed program, or UpdateError (a portable copy is updated by hand)."""
    if not path_utils.is_frozen():
        raise UpdateError("auto-update is only available in a packaged (frozen) build")
    if not is_installed():
        raise UpdateError("only an installed Surasura updates itself: download the new version to update this copy")
    return _install_dir()


def _same_volume(install):
    """The renames need the program and its update folder on one drive."""
    try:
        same = os.stat(install).st_dev == os.stat(update_dir()).st_dev
    except OSError:
        same = False
    if not same:
        raise UpdateError("the program and its update folder are on different drives, so it can't update in place")


def _owned_names(files):
    return sorted({*OWNED_ENTRIES, *(f["parts"][0] for f in files)}, key=str.lower)


def _extract(zf, f, dest):
    """One file from its part's zip into `dest`, read no further than its size, checked by its sha256."""
    try:
        member = zf.getinfo(f["path"])
    except KeyError:
        raise UpdateError(f"the {f['part']} part doesn't hold {f['path']}")
    if member.file_size != f["size"]:
        raise UpdateError(f"{f['path']} in the {f['part']} part isn't the file the release names")
    h, n = hashlib.sha256(), 0
    with zf.open(member) as src, open(dest, "wb") as out:
        for chunk in iter(lambda: src.read(1 << 20), b""):
            n += len(chunk)
            if n > f["size"]:
                break
            h.update(chunk)
            out.write(chunk)
    if n != f["size"] or h.hexdigest() != f["sha256"]:
        raise UpdateError(f"{f['path']} in the {f['part']} part isn't the file the release names")


def _verify_stage(stage, files, progress):
    """The assembled program is exactly the release: every file it names, with its sha256 — and nothing else."""
    want = {f["path"].lower(): f for f in files}
    for root, _dirs, names in os.walk(stage):
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), stage).replace(os.sep, "/").lower()
            if rel not in want:
                raise UpdateError(f"the assembled program holds a file the release doesn't name ({rel})")
    for f in files:
        path = os.path.join(stage, *f["parts"])
        if not os.path.isfile(path) or sha256_file(path) != f["sha256"]:
            raise UpdateError(f"{f['path']} isn't the file the release names")
        progress.add(f["size"])


def _prepare_package(info, progress_cb=None, window=True):
    """A 3.x release, assembled (S3.1 D4): hash the installed program, download only the parts holding a changed or
    missing file (each its sha256 and size checked), put together the complete new program in update\\stage-<ver>
    (unchanged files hard-linked from the install, else copied; the rest from the parts), check every file — then
    the swapper's marker, NOT written. Any failure leaves nothing staged."""
    install = _require_installed()
    package = getattr(info, "package", None)
    if not getattr(info, "signed", False) or not isinstance(package, dict):
        raise UpdateError("the release's package isn't signed and whole")
    files = package_files(package)
    version = _version_name(info.version)
    _version_name(__version__)
    _same_volume(install)
    discard_staged()                                         # earlier stages and downloads go first
    stage = stage_dir(version)
    downloads = os.path.join(update_dir(), DOWNLOAD_PREFIX + version)
    zips = {}
    try:
        owned = _owned_names(files)
        listing = _program_files(install, owned)
        parts = _package_parts(package)
        progress = _Progress(progress_cb, sum(s for _r, _f, s in listing) + sum(p["size"] for p in parts)
                             + sum(f["size"] for f in files))
        installed = _hash_program(listing, progress)
        same = {f["path"].lower() for f in files
                if installed.get(f["path"].lower(), (None, None, None))[1:] == (f["size"], f["sha256"])}
        needed = {f["part"] for f in files if f["path"].lower() not in same}
        os.makedirs(downloads, exist_ok=True)
        for part in parts:
            if part["name"] not in needed:
                progress.add(part["size"])
                continue
            url = (getattr(info, "assets", None) or {}).get(str(part.get("asset") or "").lower())
            if not url:
                raise UpdateError(f"the release has no {part['name']} part")
            path = os.path.join(downloads, f"part-{len(zips)}.zip")
            download(url, path, progress_cb=progress.download())
            if os.path.getsize(path) != part["size"] or sha256_file(path) != part["sha256"]:
                raise UpdateError(f"checksum mismatch — the {part['name']} part is corrupted or tampered")
            zips[part["name"]] = zipfile.ZipFile(path)
        missing = needed - set(zips)
        if missing:
            raise UpdateError(f"the release has no {sorted(missing)[0]} part")
        os.makedirs(stage)
        for f in files:
            dest = os.path.join(stage, *f["parts"])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if f["path"].lower() in same:
                src = os.path.join(install, *installed[f["path"].lower()][0].split("/"))
                try:
                    os.link(src, dest)
                except OSError:
                    shutil.copy2(src, dest)
            else:
                _extract(zips[f["part"]], f, dest)
        _verify_stage(stage, files, progress)
    except Exception as e:
        shutil.rmtree(stage, ignore_errors=True)
        if isinstance(e, UpdateError):
            raise
        raise UpdateError(str(e)) from e
    finally:
        for z in zips.values():
            z.close()
        shutil.rmtree(downloads, ignore_errors=True)
    marker = _folder_marker(version, install, owned, {f["path"]: f["sha256"] for f in files},
                            {v[0]: v[2] for v in installed.values()}, window)
    marker.update(staged=stage, swapper=os.path.join(stage, UPDATER_EXE_NAME), parts=sorted(needed))
    return marker


def _folder_marker(version, install, owned, files, kept_files, window, going_back=False, kind="folder"):
    """The swapper's whole contract (updater_helper.run_folder): every path it touches, inside the update folder
    but the install itself."""
    return {
        "format": FOLDER_FORMAT, "kind": kind, "going_back": bool(going_back),
        "target_version": version, "from_version": __version__,
        "install": install, "previous": os.path.join(previous_root(), _version_name(__version__)),
        "owned": list(owned), "files": files, "kept_files": kept_files,
        "app_pid": os.getpid(), "wait_timeout": WAIT_TIMEOUT, "window": bool(window),
        "result_path": result_path(), "app_id": uninstall_app_id(install),
    }


def _prepare_setup(info, progress_cb=None, window=True):
    """Installer mode (S3.1 D7): the release's installer downloaded and checked — the swapper runs it silently, then
    proves the result as it proves a swap. -> the marker, NOT written; its `path` / `args` are 2.x's keys."""
    install = _require_installed()
    if not os.path.isfile(updater_exe_path()):
        raise UpdateError("this install has no updater.exe to run the installer")
    version = _version_name(info.version)
    _version_name(__version__)
    discard_staged()
    folder = os.path.join(update_dir(), INSTALLER_PREFIX + version)
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(str(info.installer.get("asset")).replace("\\", "/"))
    path = os.path.join(folder, name if re.match(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,100}\.exe\Z", name or "")
                        else "setup.exe")
    try:
        download(info.installer_url, path, progress_cb=progress_cb)
        if sha256_file(path).lower() != str(info.installer["sha256"]).lower():
            raise UpdateError("checksum mismatch — the installer download is corrupted or tampered")
        package = getattr(info, "package", None)
        files = package_files(package) if getattr(info, "signed", False) and isinstance(package, dict) else []
        owned = _owned_names(files) if files else list(OWNED_ENTRIES)
        listing = _program_files(install, owned)
        kept = {v[0]: v[2] for v in _hash_program(listing, _Progress(None, 1)).values()}
    except UpdateError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError(str(e))
    marker = _folder_marker(version, install, owned, {f["path"]: f["sha256"] for f in files} or None, kept, window,
                            kind="installer")
    marker.update(setup=path, setup_log=os.path.join(update_dir(), f"setup-{version}.log"),
                  library=path_utils.installed_library(), swapper=updater_exe_path(),
                  path=path, args=[])
    return marker


def previous_version():
    """The version kept for Go back (update\\previous\\<version>, holding Surasura.exe), or None."""
    try:
        names = os.listdir(previous_root())
    except OSError:
        return None
    kept = [n for n in names if _VERSION_RE.match(n) and os.path.isfile(os.path.join(previous_root(), n, EXE_NAME))]
    if not kept:
        return None
    from app.update_checker import parse_version
    return max(kept, key=parse_version)


def prepare_go_back(progress_cb=None, window=True):
    """Go back to the kept version (W12-5): the same swapper — this version's own copy, the one that wrote the
    marker — and the same proof, in reverse; this version is kept in its place, so Go back can itself be undone. ->
    the marker for `arm_and_launch`, NOT written. Run on a worker thread: it hashes the installed program."""
    install = _require_installed()
    version = previous_version()
    if version is None:
        raise UpdateError("there is no earlier version to go back to")
    if version == __version__:
        raise UpdateError("the kept version is this one")
    if not os.path.isfile(updater_exe_path()):
        raise UpdateError("this install has no updater.exe to go back with")
    _same_volume(install)
    staged = os.path.join(previous_root(), version)
    try:
        with open(os.path.join(previous_root(), f"{version}.files.json"), "r", encoding="utf-8") as f:
            files = json.load(f)
        if not isinstance(files, dict):
            files = None
    except (OSError, ValueError):
        files = None                                 # proven by its command line and its window alone
    owned = sorted({*OWNED_ENTRIES, *os.listdir(staged)}, key=str.lower)
    owned = [n for n in owned if not _foreign_top(n)]
    listing = _program_files(install, owned)
    installed = _hash_program(listing, _Progress(progress_cb, sum(s for _r, _f, s in listing)))
    marker = _folder_marker(version, install, owned, files, {v[0]: v[2] for v in installed.values()}, window,
                            going_back=True)
    marker.update(staged=staged, swapper=updater_exe_path())
    return marker


def _launch_swapper(marker):
    """3.x's hand-over: the swapper the marker names (the new release's, or this version's for Go back and
    installer mode) copied out to update\\swapper\\updater-<to>.exe — never run from the folder it empties — the
    marker written, the copy started detached with its working folder there. Any failure: nothing stays armed."""
    source = marker.get("swapper")
    if not isinstance(source, str) or not os.path.isfile(source):
        raise UpdateError("the updater that runs the update is missing")
    folder = swapper_dir()
    os.makedirs(folder, exist_ok=True)
    copy = os.path.join(folder, f"updater-{_version_name(marker.get('target_version'))}.exe")
    part = copy + ".part"
    shutil.copyfile(source, part)
    try:
        os.replace(part, copy)
    except OSError:                                  # that name still runs: a copy of its own
        copy = os.path.join(folder, f"updater-{marker['target_version']}-{os.getpid()}.exe")
        os.replace(part, copy)
    path = write_marker(marker)
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    try:
        return subprocess.Popen([copy, "--marker", path], creationflags=flags, close_fds=True, cwd=folder)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise


UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"   # under HKEY_CURRENT_USER


def uninstall_app_id(install=None):
    """The Inno AppId whose per-user uninstall entry (<AppId>_is1) names this program folder as its
    "Inno Setup: App Path" — the entry the swapper keeps current (D8) — or None. Read only; never raises."""
    if sys.platform != "win32":
        return None
    install = install or _install_dir()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_ROOT) as root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    return None
                index += 1
                if not name.lower().endswith("_is1"):
                    continue
                try:
                    with winreg.OpenKey(root, name) as key:
                        app_path, _kind = winreg.QueryValueEx(key, "Inno Setup: App Path")
                except OSError:
                    continue
                if isinstance(app_path, str) and \
                        os.path.normcase(os.path.realpath(app_path)).rstrip("\\/") == \
                        os.path.normcase(os.path.realpath(install)).rstrip("\\/"):
                    return name[:-len("_is1")]
    except OSError:
        return None


SPLASH_CLASS = "SurasuraUpdateSplash"     # updater_helper.SPLASH_CLASS
SPLASH_WAIT = 8.0                         # the window keeps showing Installing… at most this long (D10)


def _parent_of(pid):
    for p, parent, _exe in _snapshot():
        if p == pid:
            return parent
    return None


def splash_on_screen(pid):
    """True once the swapper started as `pid` — or a process it started: a onefile program runs its code in a child
    — has its splash on screen. The window keeps showing Installing… until this is true, for at most SPLASH_WAIT
    seconds, so there is never a moment with nothing on screen (D10). Never raises."""
    if sys.platform != "win32" or not pid:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.FindWindowExW.restype = wintypes.HWND
        u32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u32.IsWindowVisible.argtypes = [wintypes.HWND]
        hwnd = None
        while True:
            hwnd = u32.FindWindowExW(None, hwnd, SPLASH_CLASS, None)
            if not hwnd:
                return False
            owner = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if u32.IsWindowVisible(hwnd) and (owner.value == pid or _parent_of(owner.value) == pid):
                return True
    except Exception:
        return False


def wait_for_splash(pid, timeout=SPLASH_WAIT, poll=0.05):
    """`splash_on_screen(pid)`, looked at until true or `timeout` s pass -> bool. For a caller's worker thread."""
    deadline = time.monotonic() + timeout
    while True:
        if splash_on_screen(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


def arm_and_launch(marker):
    """The hand-over, in the window's one final callback (after its last `can_update_now`): write the marker, then
    start updater.exe; the caller exits next. If the helper can't start, the marker is removed again (nothing stays
    armed) and the error raised. A staged installer (S1.3-6) is launched instead: no marker, no helper. A 3.x marker
    (format 3: an update, Go back, installer mode): `_launch_swapper` — its Popen's pid is the one to give
    `splash_on_screen`."""
    if marker.get("format") == FOLDER_FORMAT:
        return _launch_swapper(marker)
    if marker.get("kind") == "installer":
        return launch_installer(marker)
    added = [t["dest"] for t in marker.get("targets", []) if t.get("added")]
    made = []
    for dest in added:                     # updater.exe's os.replace needs the folder to exist
        folder = os.path.dirname(dest)
        missing = []
        while folder and not os.path.isdir(folder):
            missing.append(folder)
            folder = os.path.dirname(folder)
        for d in reversed(missing):
            os.makedirs(d, exist_ok=True)
            made.append(d)
    if added:
        with open(added_path(), "w", encoding="utf-8") as f:
            json.dump({"target_version": marker.get("target_version", ""), "added": added, "dirs": made}, f,
                      ensure_ascii=False, indent=2)
    else:
        try:
            os.remove(added_path())        # an older update's record: this one's failure must not delete what it named
        except OSError:
            pass
    path = write_marker(marker)
    try:
        return launch_helper(path)
    except Exception:
        for p in (path, added_path()):
            try:
                os.remove(p)
            except OSError:
                pass
        _remove_dirs(made)
        raise


def _remove_dirs(dirs):
    for d in sorted(dirs, key=len, reverse=True):
        try:
            os.rmdir(d)                    # only if empty
        except OSError:
            pass


def _remove_added(path=None):
    """After a failed swap: delete what the release would have added (the helper's rollback only restores what
    existed), then the folders made for it if they are empty again."""
    try:
        with open(path or added_path(), "r", encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return
    install = _install_dir()
    for dest in record.get("added") or []:
        try:
            if not isinstance(dest, str) or not _inside(dest, install):
                continue                   # never anything outside this install
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            elif os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
    _remove_dirs([d for d in record.get("dirs") or [] if isinstance(d, str) and _inside(d, install)])


def discard_staged():
    """A cancelled update: its download goes — 2.x-shaped staging, a 3.x release's assembled program, its part
    downloads, a downloaded installer. Never the previous version kept for Go back. Never raises."""
    shutil.rmtree(staging_dir(), ignore_errors=True)
    try:
        names = os.listdir(update_dir())
    except OSError:
        return
    for name in names:
        if name.startswith((STAGE_PREFIX, DOWNLOAD_PREFIX, INSTALLER_PREFIX)):
            shutil.rmtree(os.path.join(update_dir(), name), ignore_errors=True)


# "An update is happening": one OS lock, held from "Update now" until the app exits for the helper (the OS
# releases it if the app dies). The command line answers `update-staged` while it is held.
def update_lock_path():
    return os.path.join(path_utils.get_local_data_path(), "locks", "update.lock")


def take_update_lock(looks=6, gap=0.02):
    """-> the held lock, or None when another update holds it. Looked at a few times over ~0.1 s: a command
    line's check (`library_store.update_staged`) holds it for a moment, and "Update now" landing in that moment
    must not read it as another update."""
    try:
        for look in range(looks):
            held = path_utils.try_lock(update_lock_path())
            if held is not None or look == looks - 1:
                return held
            time.sleep(gap)
    except Exception:
        return None


def drop_update_lock(handle):
    """Never raises — a handle already let go included (`release_lock` raises ValueError on a closed file)."""
    try:
        path_utils.release_lock(handle)
    except ValueError:
        pass


def launch_helper(marker_path_=None):
    """Spawn updater.exe detached so it survives this process exiting."""
    if marker_path_ is None:
        marker_path_ = marker_path()
    exe = updater_exe_path()
    flags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — survive the parent, no shared console.
        flags = 0x00000008 | 0x00000200
    return subprocess.Popen([exe, "--marker", marker_path_], creationflags=flags, close_fds=True)


# ---------------------------------------------------------------------------
# Reconciliation (read side, next launch)
# ---------------------------------------------------------------------------
def _cleanup_all(state=None):
    """Remove every trace of a pending/finished update: marker, result, added record, staging, backup — and in the
    update folder a 3.x release's leftovers (`discard_staged`) and the spent swappers. Never the previous version."""
    state = state or _state()
    for path in (state["marker"], state["result"], state["added"]):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    for d in state["dirs"]:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    if "update_dir" in state:
        discard_staged()
        shutil.rmtree(swapper_dir(), ignore_errors=True)     # a copy still running stays: removed next time


def _legacy_folders():
    """Where 2.x kept the update's state: the user data folder (the exe's, frozen) and the program folder."""
    seen, folders = set(), []
    for folder in (_user_dir(), _install_dir()):
        key = os.path.normcase(os.path.abspath(folder))
        if key not in seen:
            seen.add(key)
            folders.append(folder)
    return folders


def consume_result():
    """Return the outcome of a just-applied update (and clear its files), or None.

    Precedence:
      1. A ``last_update_result.json`` written by the helper -> return it.
      2. A leftover ``pending_update.json`` with no result -> the helper started but never
         finished (crash / kill / power loss). Synthesize a 'failed' outcome so the app
         surfaces it and never auto-retries that version.
      3. Nothing pending -> None.

    The update folder's state is read first; then, once, 2.x's beside the exe (`_legacy_folders`), which is
    removed as it is read.
    """
    found = _consume(_state())
    for folder in _legacy_folders():
        legacy = _consume(_state(folder))
        found = found or legacy
    return found


def _consume(state):
    rp = state["result"]
    if os.path.exists(rp):
        try:
            with open(rp, "r", encoding="utf-8") as f:
                res = json.load(f)
            if not isinstance(res, dict):
                raise ValueError("not an object")
        except Exception:
            res = {"status": "failed", "from": "", "to": "", "reason": "unreadable result"}
        if res.get("status") != "success":
            _remove_added(state["added"])
        _cleanup_all(state)
        return res

    mp = state["marker"]
    if os.path.exists(mp):
        try:
            with open(mp, "r", encoding="utf-8") as f:
                m = json.load(f)
            if not isinstance(m, dict):
                m = {}
        except Exception:
            m = {}
        if _is_this_version(m.get("target_version")):
            # This IS the version it installed: the swap ran and its helper ended before reporting. Never delete
            # what it added (this version runs on it); a success when every target holds the bytes it names.
            landed = _swap_landed(m)
            _cleanup_all(state)
            return {"status": "success" if landed else "failed", "from": m.get("from_version", ""),
                    "to": m.get("target_version", ""),
                    "reason": "ok (the updater ended before reporting)" if landed else "update did not complete"}
        _remove_added(state["added"])
        _cleanup_all(state)
        return {
            "status": "failed",
            "from": m.get("from_version", ""),
            "to": m.get("target_version", ""),
            "reason": "update did not complete",
        }

    return None


def _is_this_version(version):
    return bool(version) and version == __version__


def _swap_landed(marker):
    """A leftover marker's targets all in place, each file with the sha256 it names (the helper's own last check).
    A 3.x marker: every file of the release in the install with its sha256 (Go back with no list: this version runs,
    so it landed)."""
    if marker.get("format") == FOLDER_FORMAT:
        install, files = marker.get("install"), marker.get("files")
        if not isinstance(install, str) or not os.path.isdir(install):
            return False
        if files is None and marker.get("going_back"):
            return True
        if not isinstance(files, dict) or not files:
            return False
        try:
            return all(sha256_file(os.path.join(install, *_plain_parts(path))) == want for path, want in files.items())
        except (OSError, UpdateError):
            return False
    targets = marker.get("targets") or []
    for t in targets:
        dest = t.get("dest") if isinstance(t, dict) else None
        if not isinstance(dest, str) or not os.path.exists(dest):
            return False
        want = t.get("sha256")
        try:
            if want and (not os.path.isfile(dest) or sha256_file(dest) != want):
                return False
        except OSError:
            return False
    return bool(targets)


def write_report(stage, reason, to_version="", from_version=""):
    """Append a plain-text account of a failed update to ``update_report.txt`` in the update folder.

    The frozen app has no console, so without this the reason is gone the moment its dialog
    closes. The user can attach the file to a bug report. Appended, never overwritten, so an
    earlier failure isn't lost to a later one (a helper that never started is reported again, as
    "did not complete", on the next launch). Holds versions, the reason and the system — nothing
    from User Files. Best-effort: returns the file's path, or None if it couldn't be written.
    """
    try:
        path = report_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = [
            f"--- Surasura update report, {time.strftime('%Y-%m-%d %H:%M:%S')} ---",
            f"Stage: {stage}",
            f"From version: {from_version or __version__}",
            f"To version: {to_version or 'unknown'}",
            f"Reason: {reason}",
            f"System: {platform.platform()}, Python {platform.python_version()}",
            f"Packaged build: {'yes' if path_utils.is_frozen() else 'no'}; "
            f"updater.exe present: {'yes' if os.path.exists(updater_exe_path()) else 'no'}",
            f"Install folder: {_install_dir()}",
        ]
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
        return path
    except Exception:
        return None


def effective_class(cls, info, skipped_version="", auto_enabled=True, can_apply=True, failed_version=""):
    """Decide what the footer offers, from the checker's class and the user's settings.

    This is the skip, loop and kill-switch guard, kept as a pure function so it is directly testable:
      * the user chose "Skip this version" -> 'NONE': that version is never offered again (a newer one
        is, and Settings -> Data & System can bring it back).
      * auto-updates disabled in settings, or no bundled updater.exe -> 'APP' becomes 'FULL' (manual).
      * the in-app update of that version already failed once -> 'FULL', never retried in place (the
        loop-breaker). A skip and a failure are kept apart: the user pressing Skip by accident once
        left only the manual download (2026-09-25).
    'INSTALLER' (3.0's hand-off, S1.3-6) is guarded exactly like 'APP'. 'FULL' otherwise passes through
    unchanged, and 'NONE' always does.
    """
    version = getattr(info, "version", "") if info is not None else ""
    if cls == "NONE" or (version and version == skipped_version):
        return "NONE"
    if cls not in ("APP", "INSTALLER"):
        return cls
    if not auto_enabled or not can_apply:
        return "FULL"
    if version and version == failed_version:
        return "FULL"
    return cls
