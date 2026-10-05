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

Deliberately UI-free (no tkinter) so every step is unit-testable, and deliberately narrow in
what it touches: only the program files the list names, plus the small marker / result JSONs
next to the executable, and a failure report under ``debug/``. It NEVER reads or writes User
Files, data, results, or settings.json — user data is entirely outside the blast radius.
"""
import os
import sys
import json
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

STAGING_DIRNAME = ".update_staging"
BACKUP_DIRNAME = ".update_backup"
MARKER_NAME = "pending_update.json"
ADDED_NAME = "pending_update_added.json"    # what the swap creates: the helper deletes the marker, so it is kept here
RESULT_NAME = "last_update_result.json"
REPORT_NAME = "update_report.txt"
UPDATER_EXE_NAME = "updater.exe"


class UpdateError(Exception):
    """Raised when staging an update fails. Nothing is armed when this is raised."""


# ---------------------------------------------------------------------------
# Locations. The install root (next to the exe) holds the marker/staging/updater.exe and the
# programs (Surasura.exe, surasura-cli.exe); the frozen _internal dir holds templates/ and the
# runtime. (The app code is inside Surasura.exe, not loose under _internal.)
# ---------------------------------------------------------------------------
def _user_dir():
    return path_utils.get_user_data_path()


def _internal_dir():
    return path_utils.get_base_path()


def marker_path():
    return os.path.join(_user_dir(), MARKER_NAME)


def result_path():
    return os.path.join(_user_dir(), RESULT_NAME)


def staging_dir():
    return os.path.join(_user_dir(), STAGING_DIRNAME)


def backup_dir():
    return os.path.join(_user_dir(), BACKUP_DIRNAME)


def updater_exe_path():
    return os.path.join(_user_dir(), UPDATER_EXE_NAME)


def added_path():
    return os.path.join(_user_dir(), ADDED_NAME)


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
    return os.path.join(_user_dir(), "debug", REPORT_NAME)


def can_auto_apply(info=None):
    """Auto-apply is only possible in a frozen build that shipped the bundled updater.exe — and, for a release that
    lists its files, only when every destination is one the in-place update may write (`resolve_files`)."""
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
#           or something under _internal/ (case-folded, no absolute path, no "..", resolved
#           through junctions and kept inside the install folder) — anything else: FULL
#   kind    "file" or "dir"
#   sha256  a file's sha256, or a dir's `tree_sha256`
# ---------------------------------------------------------------------------
_ROOT_FILES = {"surasura.exe", "surasura-cli.exe", "release_notes.md"}
_HEX = set("0123456789abcdef")


def _install_dir():
    return _user_dir()          # frozen: the folder holding Surasura.exe


def _inside(path, folder):
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    return a != b and a.startswith(b.rstrip(os.sep) + os.sep)


def resolve_destination(dest, install_dir=None):
    """`dest` (relative, from a release's list) -> the absolute path it names, or UpdateError when the in-place
    update may not write there."""
    install_dir = install_dir or _install_dir()
    if not isinstance(dest, str) or not dest.strip():
        raise UpdateError(f"destination {dest!r} is empty")
    text = dest.replace("\\", "/")
    if text.startswith("/") or os.path.isabs(dest) or (len(text) > 1 and text[1] == ":"):
        raise UpdateError(f"destination {dest!r} is absolute")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise UpdateError(f"destination {dest!r} leaves the install folder")
    if any(":" in p or p != p.rstrip(" .") for p in parts):
        raise UpdateError(f"destination {dest!r} is not a plain path")
    folded = [p.casefold() for p in parts]
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


def release_children():
    """The update was cancelled: children may start again, and those asked for meanwhile start now (on the
    caller's thread). Never raises."""
    with _DEFERRED_LOCK:
        _HOLD.clear()
        waiting = list(_DEFERRED)
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


def _processes_running(images):
    """{pid: image path} of every running process whose program is one of `images` (Windows; elsewhere {} — the
    in-place updater is Windows-only). One snapshot of the process list, then the full path asked only of
    processes whose exe NAME matches."""
    if sys.platform != "win32" or not images:
        return {}
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
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    wanted = {os.path.normcase(os.path.abspath(i)) for i in images}
    names = {os.path.basename(i).lower() for i in wanted}
    found = {}
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)              # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() in names:
                handle = k32.OpenProcess(0x1000, False, entry.th32ProcessID)   # QUERY_LIMITED_INFORMATION
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buf))
                        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                            if os.path.normcase(os.path.abspath(buf.value)) in wanted:
                                found[int(entry.th32ProcessID)] = buf.value
                    finally:
                        k32.CloseHandle(handle)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return found


def stop_pid(pid):
    """End a process by its id (one this app didn't start: no Popen to ask). Never raises."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = k32.OpenProcess(0x0001, False, int(pid))        # PROCESS_TERMINATE
            if handle:
                try:
                    k32.TerminateProcess(handle, 1)
                finally:
                    k32.CloseHandle(handle)
        else:
            import signal
            os.kill(int(pid), signal.SIGTERM)
    except Exception:
        pass


def _stopper(process):
    def stop():
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass
    return stop


def running_children(active_processes=(), images=None):
    """Everything of Surasura's that runs now besides this window, each `{"pid", "name", "stop"}` — what an update
    waits for: the dashboard's own children (`active_processes`, named by their `surasura_desc`), Backfill's
    パターン build, and any process running this install's Surasura.exe or surasura-cli.exe other than this one (the
    splicer and the importers' children, a command line hato started). `images` overrides which programs count
    (a test, a source checkout). The auto-Generate guard does NOT ask this (Backfill's build goes behind a Generate)."""
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
    try:
        others = _processes_running(_install_images() if images is None else images)
    except Exception as e:
        print(f"Update: could not list running programs ({e})")
        others = {}
    for pid, image in sorted(others.items()):
        if pid in seen:
            continue
        cli = os.path.basename(image).lower() == CLI_EXE_NAME.lower()
        found.append({"pid": pid, "name": "Surasura's command line" if cli else "Another Surasura window",
                      "stop": (lambda p=pid: stop_pid(p))})
    return found


def can_update_now(active_processes=(), images=None):
    """The one "may the update start now?" seam: nothing of Surasura's holds this install's programs. (L2.1 adds the
    library store's lock here.)"""
    return not running_children(active_processes, images)


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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)
    return path


def prepare_update(info, progress_cb=None):
    """Download -> verify checksum -> extract & validate -> the marker, NOT written.

    Returns the marker (a dict). Nothing is armed: `pending_update.json` is written only by
    `arm_and_launch`, in the window's final callback right before the helper starts, so a cancel,
    a close, a crash or a sleep while the update waits (K75) leaves no marker and the next start
    reports nothing. Raises UpdateError on any failure, having cleaned up the staging dir. Does
    NOT launch the helper or exit the app.
    """
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


def arm_and_launch(marker):
    """The hand-over, in the window's one final callback (after its last `can_update_now`): write the marker, then
    start updater.exe; the caller exits next. If the helper can't start, the marker is removed again (nothing stays
    armed) and the error raised."""
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


def _remove_added():
    """After a failed swap: delete what the release would have added (the helper's rollback only restores what
    existed), then the folders made for it if they are empty again."""
    try:
        with open(added_path(), "r", encoding="utf-8") as f:
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
    """A cancelled update: its download goes. Never raises."""
    shutil.rmtree(staging_dir(), ignore_errors=True)


# "An update is happening": one OS lock, held from "Update now" until the app exits for the helper (the OS
# releases it if the app dies). The command line answers `update-staged` while it is held.
def update_lock_path():
    return os.path.join(path_utils.get_local_data_path(), "locks", "update.lock")


def take_update_lock():
    """-> the held lock, or None when another update holds it."""
    try:
        return path_utils.try_lock(update_lock_path())
    except Exception:
        return None


def drop_update_lock(handle):
    path_utils.release_lock(handle)


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
def _cleanup_all():
    """Remove every trace of a pending/finished update: marker, result, added record, staging, backup."""
    for path in (marker_path(), result_path(), added_path()):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    for d in (staging_dir(), backup_dir()):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)


def consume_result():
    """Return the outcome of a just-applied update (and clear its files), or None.

    Precedence:
      1. A ``last_update_result.json`` written by the helper -> return it.
      2. A leftover ``pending_update.json`` with no result -> the helper started but never
         finished (crash / kill / power loss). Synthesize a 'failed' outcome so the app
         surfaces it and never auto-retries that version.
      3. Nothing pending -> None.
    """
    rp = result_path()
    if os.path.exists(rp):
        try:
            with open(rp, "r", encoding="utf-8") as f:
                res = json.load(f)
        except Exception:
            res = {"status": "failed", "from": "", "to": "", "reason": "unreadable result"}
        if res.get("status") != "success":
            _remove_added()
        _cleanup_all()
        return res

    mp = marker_path()
    if os.path.exists(mp):
        try:
            with open(mp, "r", encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            m = {}
        _remove_added()
        _cleanup_all()
        return {
            "status": "failed",
            "from": m.get("from_version", ""),
            "to": m.get("target_version", ""),
            "reason": "update did not complete",
        }

    return None


def write_report(stage, reason, to_version="", from_version=""):
    """Append a plain-text account of a failed update to ``debug/update_report.txt``.

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
            f"Install folder: {_user_dir()}",
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
    'FULL' otherwise passes through unchanged, and 'NONE' always does.
    """
    version = getattr(info, "version", "") if info is not None else ""
    if cls == "NONE" or (version and version == skipped_version):
        return "NONE"
    if cls != "APP":
        return cls
    if not auto_enabled or not can_apply:
        return "FULL"
    if version and version == failed_version:
        return "FULL"
    return "APP"
