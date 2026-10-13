"""Standalone update helper for Surasura — frozen into `updater.exe` (the swapper).

This runs AS A SEPARATE PROCESS, launched by the app just before it exits. Two hand-offs, told apart by the marker:

* **3.x's** (``"format": 3``, S3.1 D7–D10, `run_folder`): the NEW release's copy of this program runs, copied out of
  the staged folder to ``<Houseki local root>\\update\\swapper\\`` (so a fix to it ships with the release that needs
  it, and it never holds a file it moves). It waits up to 60 s for every process whose program lives in the install
  folder and never ends one; then moves each top-level entry the program owns to ``update\\previous\\<from>\\`` and
  each staged entry into the install folder — renames on one volume, retried while antivirus holds a handle — and
  proves the result: every file's sha256, ``surasura-cli.exe --version``, and (when the window started the update)
  Surasura's window visible within 20 s and alive 3 s. Any failure moves everything back, newest first, starts the
  old version and says why in the result. Entries the program doesn't own — Inno's ``unins000.*``, and the library's
  ``User Files``, ``data``, ``results``, ``settings.json`` should one sit there — are never touched. Installer mode
  (``"kind": "installer"``) runs the release's Setup silently in place of the staged folder, then the same proof;
  before its first move it leaves Windows a one-time RunOnce entry, ``updater.exe --recover <marker>``, that finishes
  or undoes a swap cut off half-way at the next sign-in (`recover`, S3.1-5), and takes it away when it ends.
  A splash (`show_splash`) shows meanwhile; a splash that can't be drawn never stops the update.
* **2.x's** (no format): the targets the marker lists, each a file or a folder — Surasura.exe, ``_internal/templates``,
  RELEASE_NOTES.md, and since 2.5 whatever the release's own file list names — swapped with a backup, then the app
  relaunched. Unchanged since 2.4.0 (`run`, `apply_update`).

Design constraints (why this is its own file / its own exe):
  * It imports NOTHING from ``app/`` — so it can never hold open the very files it must
    replace, and it works even while the payload it is installing is broken.
  * Every path it needs comes from the marker JSON, so it has no knowledge of the install
    layout and needs no ``path_utils``.
  * It is stdlib-only and Unicode-safe (users' install paths routinely contain Japanese /
    Chinese characters), and it is unit-tested as plain Python before it is ever frozen.

Invariants that make an auto-update un-botchable:
  * It only ever touches the targets named in the marker (the app allows only the programs,
    RELEASE_NOTES.md and ``_internal/``) plus the small marker / result JSONs. It never reads or
    writes User Files, data, results, or settings.json.
  * It waits only for the app's own process; the app waits for everything else of Surasura's
    first (2.5), and deletes a file a failed swap added (a rollback restores only what existed).
  * It backs up what it replaces first and rolls back on ANY failure, so a bad swap always
    leaves a working install.
  * It increments the marker's attempt counter BEFORE acting, so a crash mid-swap is visible
    to the app on next launch and is never retried automatically.
"""
import os
import re
import sys
import json
import math
import time
import shutil
import argparse
import threading
import subprocess


def _pid_alive(pid):
    """Best-effort 'is this process still running' check (same user)."""
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        if sys.platform == "win32":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                # No handle => process is gone (or we lack rights; treat as gone so we
                # don't hang forever — the timeout above still bounds us either way).
                return False
            try:
                code = ctypes.c_ulong()
                ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                if not ok:
                    return False
                return code.value == STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def wait_for_pid(pid, timeout=60.0, interval=0.25):
    """Block until process ``pid`` exits or ``timeout`` seconds elapse.

    Returns True if the process is gone. A falsy pid means 'nothing to wait for'.
    """
    if not pid:
        return True
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(interval)
    return not _pid_alive(pid)


def _result(status, from_version, to_version, reason):
    return {
        "status": status,
        "from": from_version,
        "to": to_version,
        "reason": reason,
    }


def _sha256_file(path, _bufsize=1 << 20):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def _staged_ok(t, payload_dir):
    staged = os.path.join(payload_dir, t["name"])
    return os.path.isfile(staged) if t.get("kind", "dir") == "file" else os.path.isdir(staged)


def _backup_one(t, backup_dir):
    dest = t["dest"]
    b = os.path.join(backup_dir, t["name"])
    if t.get("kind", "dir") == "file":
        if os.path.isfile(dest):
            shutil.copy2(dest, b)
    else:
        if os.path.isdir(dest):
            shutil.copytree(dest, b)


def _swap_one(t, payload_dir):
    """Install one staged target over its destination as atomically as the OS allows."""
    dest = t["dest"]
    staged = os.path.join(payload_dir, t["name"])
    if t.get("kind", "dir") == "file":
        # os.replace is atomic on the same volume — the exe is either the old or the new one,
        # never a truncated in-between.
        os.replace(staged, dest)
    else:
        # Copy first (dest untouched if this fails), then flip with a short rmtree+rename so the
        # window where dest is absent is minimal.
        tmp = dest + ".new"
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(staged, tmp)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.rename(tmp, dest)


def _restore_one(t, backup_dir):
    """Restore one target from its backup. Best-effort; never raises."""
    dest = t["dest"]
    b = os.path.join(backup_dir, t["name"])
    try:
        if t.get("kind", "dir") == "file":
            if os.path.isfile(b):
                shutil.copy2(b, dest)
        else:
            if os.path.isdir(b):
                if os.path.isdir(dest):
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(b, dest)
    except Exception:
        pass


def apply_update(marker):
    """Perform backup -> swap -> verify, rolling back on any failure.

    Targets are a mix of a file (Surasura.exe — the code lives in its embedded archive) and a
    dir (templates/). Pure filesystem work: no process waiting, no relaunch, so it is directly
    testable. Returns a result dict ({status, from, to, reason}); never raises.
    """
    try:
        targets = marker["targets"]
        payload_dir = marker["payload_dir"]
        backup_dir = marker["backup_dir"]
        target_version = marker["target_version"]
        from_version = marker.get("from_version", "")
    except (KeyError, TypeError) as e:
        return _result("failed", "", "", f"malformed marker: {e}")

    # 1. Every staged target must be present before we disturb anything on disk.
    for t in targets:
        if not _staged_ok(t, payload_dir):
            return _result("failed", from_version, target_version,
                           f"missing staged '{t['name']}'")

    # 2. Back up current program files so any failure is fully reversible.
    try:
        if os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)
        os.makedirs(backup_dir, exist_ok=True)
        for t in targets:
            _backup_one(t, backup_dir)
    except Exception as e:
        return _result("failed", from_version, target_version, f"backup failed: {e}")

    # 3. Swap the staged payload in. On ANY error, roll back EVERY target from its backup —
    #    including one that failed mid-swap (a dir whose dest was already removed before the
    #    rename). Every target was backed up in phase 2, so restoring all is safe and complete.
    try:
        for t in targets:
            _swap_one(t, payload_dir)
    except Exception as e:
        for t in targets:
            _restore_one(t, backup_dir)
        return _result("failed", from_version, target_version,
                       f"swap failed (rolled back): {e}")

    # 4. Verify each target whose expected sha256 was recorded (the exe). If the on-disk bytes
    #    don't match what we intended to install, roll everything back.
    for t in targets:
        want = t.get("sha256")
        if want:
            got = _sha256_file(t["dest"]) if os.path.isfile(t["dest"]) else None
            if got != want:
                for tt in targets:
                    _restore_one(tt, backup_dir)
                return _result("failed", from_version, target_version,
                               f"post-swap verification failed for '{t['name']}'; rolled back")

    return _result("success", from_version, target_version, "ok")


def _safe_write_json(path, data):
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _cleanup(marker):
    """Remove staging + backup dirs. Best-effort; leftovers are harmless."""
    for key in ("staging_dir", "backup_dir"):
        d = marker.get(key)
        if d and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)


def _relaunch(marker):
    exe = marker.get("relaunch_exe")
    if exe and os.path.exists(exe):
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe) or None)
        except Exception:
            pass


def run(marker_path, ops=None):
    """Full helper lifecycle around apply_update(): attempt-count, wait, apply, report. A 3.x marker goes to
    `run_folder`."""
    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            marker = json.load(f)
    except Exception:
        return 1
    if isinstance(marker, dict) and marker.get("format") == FORMAT:
        return run_folder(marker_path, marker, ops)

    # Record the attempt for diagnostics. (The real guard against retry loops is the app's
    # `failed_update_version`, set when it sees a failed/interrupted result — see app/updater.py.)
    marker["attempt"] = int(marker.get("attempt", 0)) + 1
    _safe_write_json(marker_path, marker)

    from_v = marker.get("from_version", "")
    to_v = marker.get("target_version", "")

    # Give the app a moment to release resources, then wait for it to fully exit. If it does
    # NOT exit, abort BEFORE touching any files — swapping under a live process risks locked
    # files and a partial swap. The unchanged app is simply relaunched.
    time.sleep(0.5)
    if not wait_for_pid(marker.get("app_pid"), timeout=marker.get("wait_timeout", 60)):
        result = _result("failed", from_v, to_v, "app did not exit in time; update aborted")
    else:
        try:
            result = apply_update(marker)
        except Exception as e:
            # Should never happen (apply_update catches its own phases) but never leave the
            # user without a result to reconcile.
            result = _result("failed", from_v, to_v, f"unexpected error: {e}")

    _safe_write_json(marker.get("result_path"), result)
    _cleanup(marker)
    try:
        os.remove(marker_path)
    except Exception:
        pass

    _relaunch(marker)
    return 0 if result.get("status") == "success" else 2


# =====================================================================================================================
# 3.x: the whole program, swapped by renames (S3.1 D7–D10). Every path comes from the marker (app/updater.py writes it,
# `_folder_marker`); this knows only Surasura's program names, the Inno flags and the uninstall entry's values.
# =====================================================================================================================
FORMAT = 3
WAIT_FOR_EXIT = 60.0        # every process running from the install folder has this long to end; never ended by us
WAIT_FOR_WINDOW = 20.0      # the new window must be on screen within this…
WINDOW_SETTLE = 3.0         # …and still running this long after (an exit code of 0 meanwhile: its user closed it)
WAIT_TO_UNDO = 15.0         # what the new version started has this long to end before the moves go back
POLL = 0.25
RENAME_TRIES = 20           # a rename refused (antivirus scanning a new file) is tried again, every RENAME_GAP s
RENAME_GAP = 0.25
SETUP_TIMEOUT = 900.0
VERSION_TIMEOUT = 60.0
APP_EXE, CLI_EXE = "Surasura.exe", "surasura-cli.exe"
UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"     # under HKEY_CURRENT_USER (D8)
RUNONCE_ROOT = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"         # under HKEY_CURRENT_USER (S3.1-5)
RECOVERY_NAME = "SurasuraUpdateRecovery"
TEST_RUNONCE_ENV = "SURASURA_TEST_RUNONCE"  # a test's own RunOnce key: honoured only under HKCU\Software\SurasuraTests\
RECOVERED = "ok (the updater ended before reporting)"       # app/updater.py's words for a swap that landed unreported
SUCCESS, FAILED = "success", "failed"
SETUP_FLAGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCLOSEAPPLICATIONS")
# Inno Setup's exit codes (jrsoftware.org/ishelp/topic_setupexitcodes.htm); any other code is a failure too.
SETUP_EXIT = {
    1: "Setup could not start",
    2: "Setup was cancelled before it installed anything",
    3: "Setup stopped on a fatal error before installing",
    4: "Setup stopped on a fatal error while installing",
    5: "Setup was cancelled while installing",
    6: "Setup was ended by a debugger",
    7: "Setup refused at its Preparing to Install step",
    8: "Setup refused and asked for a restart",
}
# The proof is a visible window with Surasura's title: a crash dialog is a visible window of that process too.
_TITLE = re.compile("Surasura(?:\\s[—–-]\\s|\\Z)")
_ENTRY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9 ._-]{0,63}\Z")      # a top-level entry: one plain name
# Never moved, whatever a marker says: the library's, should one sit in the program folder, and Inno's uninstaller.
_KEPT = {"user files", "data", "results", "settings.json"}


class SwapError(Exception):
    """A step failed after something moved; str() is a person's sentence."""


class WinOps:
    """What the swapper asks of Windows — which processes run from a folder, start one, is its window up, what
    version a program reports, run Setup — behind one object, so the steps are testable with a stand-in."""

    def processes_in(self, folder):
        """-> the pids (not this one) whose program file lives inside `folder`. A program started through a short
        (8.3) path reports its image that way, so an image holding ~ is resolved too."""
        if sys.platform != "win32":
            return []
        prefixes = {os.path.normcase(p).rstrip("\\/") + os.sep
                    for p in (os.path.abspath(folder), os.path.realpath(folder))}
        found = []
        for pid, image in _process_images().items():
            if pid == os.getpid() or not image:
                continue
            names = {os.path.normcase(image)}
            if "~" in image:
                names.add(os.path.normcase(os.path.realpath(image)))
            if any(n.startswith(p) for n in names for p in prefixes):
                found.append(pid)
        return found

    def start(self, exe):
        """-> the started program: its own group, its own folder as its working folder."""
        return subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True,
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    def window_visible(self, pid):
        """True when `pid` owns a visible top-level window titled as Surasura's window is."""
        return any(_TITLE.match(title) for title in _visible_titles(pid))

    def version(self, cli):
        """-> the "app" version `<cli> --version` reports, or None. No console window flashes."""
        try:
            done = subprocess.run([cli, "--version"], capture_output=True, timeout=VERSION_TIMEOUT,
                                  cwd=os.path.dirname(cli),
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        for line in done.stdout.decode("utf-8", "replace").splitlines():
            try:
                answer = json.loads(line)
            except ValueError:
                continue
            if isinstance(answer, dict) and answer.get("type") == "result" and isinstance(answer.get("app"), str):
                return answer["app"]
        return None

    def stop(self, process):
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(10)
        except Exception:
            pass

    def stop_pid(self, pid):
        """End a process running from the install folder while the moves go back: the folder was free when the swap
        began, so whatever runs there now is the new version's. Best effort."""
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = k32.OpenProcess(0x0001, False, int(pid))       # PROCESS_TERMINATE
            if handle:
                try:
                    k32.TerminateProcess(handle, 1)
                finally:
                    k32.CloseHandle(handle)
        except Exception:
            pass

    def run_setup(self, argv):
        """-> Setup's exit code, or None when it couldn't be started or ran past SETUP_TIMEOUT (then it is ended:
        it is this swap's own)."""
        try:
            return subprocess.run(argv, cwd=os.path.dirname(argv[0]), timeout=SETUP_TIMEOUT).returncode
        except (OSError, subprocess.SubprocessError):
            return None


def _process_images():
    """{pid: full program path} of every process this user may query (Windows; elsewhere {})."""
    if sys.platform != "win32":
        return {}
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ENTRY)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ENTRY)]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    pids = []
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)                  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    try:
        entry = ENTRY()
        entry.dwSize = ctypes.sizeof(ENTRY)
        more = k32.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            pids.append(int(entry.th32ProcessID))
            more = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    images = {}
    for pid in pids:
        handle = k32.OpenProcess(0x1000, False, pid)              # QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                images[pid] = buf.value
        finally:
            k32.CloseHandle(handle)
    return images


def _visible_titles(pid):
    """The titles of `pid`'s visible top-level windows (Windows; elsewhere [])."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    each = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u32.EnumWindows.argtypes = [each, wintypes.LPARAM]
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.IsWindowVisible.argtypes = [wintypes.HWND]
    u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    titles = []

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, buf, 512)
            titles.append(buf.value)
        return True

    u32.EnumWindows(each(visit), 0)
    return titles


def _quietly(call, *args):
    """-> call(*args), or None if it raised: for the steps of a way out, none of which may stop the next."""
    try:
        return call(*args)
    except Exception:
        return None


def _strictly_inside(root, path):
    root, path = os.path.normcase(os.path.abspath(root)), os.path.normcase(os.path.abspath(path))
    return path.startswith(root.rstrip("\\/") + os.sep)


def _overlap(a, b):
    a, b = os.path.normcase(os.path.abspath(a)), os.path.normcase(os.path.abspath(b))
    return a == b or _strictly_inside(a, b) or _strictly_inside(b, a)


def _plain_entry(name):
    return isinstance(name, str) and bool(_ENTRY.match(name)) and name.rstrip(" .") == name \
        and name.lower() not in _KEPT and not name.lower().startswith("unins")


def _file_path(install, path):
    """A marker's '/'-separated file path -> its place in `install`, or SwapError for anything but plain parts."""
    parts = path.split("/") if isinstance(path, str) else []
    if not parts or any(p in ("", ".", "..") or "\\" in p or ":" in p for p in parts):
        raise SwapError(f"the release names a file that isn't one ({path!r})")
    return os.path.join(install, *parts)


def _uncontained(m, root):
    """-> why this marker reaches outside what a swap may touch, or None: the install an existing absolute folder
    apart from the update folder; staged, previous, Setup and its log inside the update folder; every entry plain."""
    install = m.get("install")
    if not isinstance(install, str) or not os.path.isabs(install) or not os.path.isdir(install):
        return "its install folder isn't there"
    if _overlap(install, root):
        return "the install and the update folder overlap"
    keys = ("previous", "setup", "setup_log") if m.get("kind") == "installer" else ("staged", "previous")
    for key in keys:
        if not isinstance(m.get(key), str) or not _strictly_inside(root, m[key]):
            return f"its {key} isn't in the update folder"
    if not _strictly_inside(root, os.path.dirname(os.path.abspath(m["previous"]))):
        return "its previous folder isn't in the update folder"
    if m.get("kind") != "installer" and _overlap(m["staged"], m["previous"]):
        return "what it installs and what it keeps are one folder"
    owned = m.get("owned")
    if not isinstance(owned, list) or not owned or not all(_plain_entry(n) for n in owned):
        return "its list of the program's entries isn't one"
    if not isinstance(m.get("target_version"), str) or not m["target_version"]:
        return "it names no version"
    return None


def wait_gone(install, ops, timeout, clock=time.monotonic, sleep=time.sleep):
    """True once nothing runs from `install`; False when `timeout` passes first. Never ends a process."""
    deadline = clock() + timeout
    while True:
        if not ops.processes_in(install):
            return True
        if clock() >= deadline:
            return False
        sleep(POLL)


def _rename(src, dst, sleep=time.sleep):
    """os.rename, tried again while it is refused (a handle held by antivirus or an indexer); a missing source or a
    taken destination is never retried."""
    for attempt in range(RENAME_TRIES):
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if attempt == RENAME_TRIES - 1:
                raise
            sleep(RENAME_GAP)


def _move(names, src_dir, dst_dir, moves, sleep):
    """Each of `names` present in `src_dir` renamed into `dst_dir` (made if missing); every move recorded."""
    os.makedirs(dst_dir, exist_ok=True)
    for name in names:
        src = os.path.join(src_dir, name)
        if os.path.lexists(src):
            dst = os.path.join(dst_dir, name)
            _rename(src, dst, sleep)
            moves.append((src, dst))


def _undo(moves, sleep=time.sleep):
    """Every recorded move reversed, newest first. -> the entries that couldn't be put back."""
    stuck = []
    for src, dst in reversed(moves):
        try:
            _rename(dst, src, sleep)
        except OSError:
            stuck.append(dst)
    return stuck


def _remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _verify(install, files):
    """Every file the release names holds the bytes its sha256 names."""
    for path, want in sorted((files or {}).items()):
        full = _file_path(install, path)
        try:
            got = _sha256_file(full)
        except OSError:
            got = None
        if got != want:
            raise SwapError(f"{path} isn't the file the release names")


def _named(m):
    return m.get("target_version") if m.get("going_back") else "the new version"


def _reports(m, ops):
    """The new surasura-cli.exe runs and says it is the target: the one proof a headless update gets."""
    said = ops.version(os.path.join(m["install"], CLI_EXE))
    if said != m["target_version"]:
        raise SwapError(f"{_named(m)} did not start (its command line said {said or 'nothing'})")


def _proven(m, process, ops, clock, sleep, seen):
    """What a person would see: the window, titled, within WAIT_FOR_WINDOW, still running WINDOW_SETTLE later. ->
    None, or the reason not. `seen()` is called at its first sight (the splash goes then)."""
    deadline = clock() + WAIT_FOR_WINDOW
    while not ops.window_visible(process.pid):
        if process.poll() is not None:
            return f"{_named(m)} closed as it opened"
        if clock() >= deadline:
            return f"{_named(m)} did not open its window"
        sleep(POLL)
    if seen is not None:
        _quietly(seen)
    settle = clock() + WINDOW_SETTLE
    while clock() < settle:
        code = process.poll()
        if code is not None:
            return None if code == 0 else f"{_named(m)} closed as it opened"
        sleep(POLL)
    return None


def _restart(m, ops):
    """The old version again, on a way out — only when the window started the update. -> True when started."""
    if not m.get("window"):
        return True
    exe = os.path.join(m["install"], APP_EXE)
    return os.path.isfile(exe) and _quietly(ops.start, exe) is not None


def _stop_started(m, started, ops, clock, sleep):
    """Before the moves go back: end what this swap started, then whatever the new version started from the folder
    (it was free when the swap began), and wait for the folder to be free."""
    if started is not None:
        _quietly(ops.stop, started)
    for pid in _quietly(ops.processes_in, m["install"]) or ():
        _quietly(ops.stop_pid, pid)
    _quietly(wait_gone, m["install"], ops, WAIT_TO_UNDO, clock, sleep)


def _clear_same(previous):
    """An earlier copy of the version about to be kept goes first; refuses (OSError) if it can't."""
    if os.path.lexists(previous):
        shutil.rmtree(previous)


def apply_folder(m, ops, clock=time.monotonic, sleep=time.sleep, seen=None):
    """The staged folder's entries into the install, the program's old ones to `previous`, proven. -> the result's
    (status, reason, touched). Never raises."""
    install, staged, previous = m["install"], m["staged"], m["previous"]
    try:
        if not wait_gone(install, ops, float(m.get("wait_timeout") or WAIT_FOR_EXIT), clock, sleep):
            return FAILED, "Surasura was still running, so nothing was changed", False
        entries = sorted(os.listdir(staged))
        if not all(_plain_entry(n) for n in entries) or APP_EXE not in entries or CLI_EXE not in entries:
            return FAILED, f"{_named(m)} is incomplete, so nothing was changed", False
        _clear_same(previous)
    except Exception as e:
        return FAILED, f"the update stopped before changing anything ({type(e).__name__})", False
    owned = sorted(set(m["owned"]) | set(entries), key=str.lower)
    moves, started = [], None
    try:
        _move(owned, install, previous, moves, sleep)
        _move(entries, staged, install, moves, sleep)
        _verify(install, m.get("files"))
        _reports(m, ops)
        if m.get("window"):
            started = ops.start(os.path.join(install, APP_EXE))
            why = _proven(m, started, ops, clock, sleep, seen)
            if why:
                raise SwapError(why)
    except Exception as e:
        _stop_started(m, started, ops, clock, sleep)
        stuck = _undo(moves, sleep)
        _quietly(os.rmdir, previous)                         # only when empty again
        reason = str(e) if isinstance(e, SwapError) else f"a file could not be moved ({type(e).__name__})"
        if stuck:
            reason += f" -- and {len(stuck)} item(s) could not be put back"
        return FAILED, reason, True
    return SUCCESS, "ok", True


def _setup_argv(m):
    """Setup, silent: no wizard, no message boxes, no restart, never closing a program itself (Surasura closed
    itself); the library the app uses now (never Inno's remembered one); the log in the update folder."""
    argv = [m["setup"], *SETUP_FLAGS]
    if isinstance(m.get("library"), str) and m["library"]:
        argv.append(f"/LIBRARY={m['library']}")
    argv.append(f"/LOG={m['setup_log']}")
    return argv


def _setup_says(code):
    if code == 0:
        return None
    if code is None:
        return "Setup could not be run"
    return SETUP_EXIT.get(code, f"Setup ended with code {code}")


def _clear_setups(m, names, sleep):
    """What Setup wrote under `names` in the install goes (by way of update\\previous\\failed-<ver>), so the old
    entries can come back."""
    install = m["install"]
    failed = os.path.join(os.path.dirname(os.path.abspath(m["previous"])), f"failed-{m['target_version']}")
    _quietly(_clear_same, failed)
    for name in names:
        if os.path.lexists(os.path.join(install, name)):
            try:
                _move([name], install, failed, [], sleep)
            except OSError:
                _remove(os.path.join(install, name))
    _quietly(_clear_same, failed)


def apply_installer(m, ops, clock=time.monotonic, sleep=time.sleep, seen=None, arm=None):
    """Installer mode (D7): the program's entries to `previous`, Setup run silently into the emptied folder, the
    same proof; any failure takes what Setup wrote away and puts the old entries back. `arm()` runs just before the
    first move, once `previous` is empty (the recovery entry, S3.1-5); one that raises stops the update unchanged.
    -> (status, reason, touched). Never raises."""
    install, previous = m["install"], m["previous"]
    try:
        if not wait_gone(install, ops, float(m.get("wait_timeout") or WAIT_FOR_EXIT), clock, sleep):
            return FAILED, "Surasura was still running, so nothing was changed", False
        if not os.path.isfile(m["setup"]):
            return FAILED, "the new installer is missing, so nothing was changed", False
        _clear_same(previous)
        if arm is not None:
            arm()
    except Exception as e:
        return FAILED, f"the update stopped before changing anything ({type(e).__name__})", False
    owned = sorted(set(m["owned"]), key=str.lower)
    moves, started, ran = [], None, False
    try:
        _move(owned, install, previous, moves, sleep)
        ran = True
        why = _setup_says(ops.run_setup(_setup_argv(m)))
        if why:
            raise SwapError(why)
        _verify(install, m.get("files"))
        _reports(m, ops)
        if m.get("window"):
            started = ops.start(os.path.join(install, APP_EXE))
            why = _proven(m, started, ops, clock, sleep, seen)
            if why:
                raise SwapError(why)
    except Exception as e:
        _stop_started(m, started, ops, clock, sleep)
        if ran:
            # What Setup wrote under the program's names goes, so the old entries can come back.
            _clear_setups(m, owned, sleep)
        stuck = _undo(moves, sleep)
        _quietly(os.rmdir, previous)
        if ran and m.get("app_id"):
            # Setup rewrote the uninstall entry: it names the version that is back.
            _quietly(write_uninstall_version, m["app_id"], install, m.get("from_version", ""))
        reason = str(e) if isinstance(e, SwapError) else f"a file could not be moved ({type(e).__name__})"
        if stuck:
            reason += f" -- and {len(stuck)} item(s) could not be put back"
        return FAILED, reason, True
    return SUCCESS, "ok", True


def _version_numbers(version):
    numbers = re.findall(r"\d+", str(version))[:2]
    return [int(n) for n in numbers] + [0] * (2 - len(numbers))


def _folder_kb(folder):
    total = 0
    for root, _dirs, names in os.walk(folder):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return (total + 1023) // 1024


def write_uninstall_version(app_id, install, version, size_kb=None):
    """Windows' installed-apps list follows a one-click update (D8): DisplayVersion, MajorVersion / MinorVersion,
    VersionMajor / VersionMinor (and EstimatedSize, KB) under HKCU\\…\\Uninstall\\<app_id>_is1 — only when that key
    exists and its "Inno Setup: App Path" is `install`; no "Inno Setup: …" value is ever written, and no key is ever
    made. -> True when written. Never raises."""
    if sys.platform != "win32" or not isinstance(app_id, str) or not re.match(r"[^\\/\x00-\x1f]{1,200}\Z", app_id) \
            or not re.match(r"\d+(\.\d+)*\Z", str(version)):
        return False
    try:
        import winreg
        path = f"{UNINSTALL_ROOT}\\{app_id}_is1"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            app_path, _kind = winreg.QueryValueEx(key, "Inno Setup: App Path")
            if not isinstance(app_path, str) or not _overlap_exact(app_path, install):
                return False
            major, minor = _version_numbers(version)
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, str(version))
            for name, value in (("MajorVersion", major), ("MinorVersion", minor),
                                ("VersionMajor", major), ("VersionMinor", minor)):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            if size_kb is not None:
                winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, min(int(size_kb), 0xFFFFFFFF))
        return True
    except (OSError, ValueError, TypeError):
        return False


def _overlap_exact(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)).rstrip("\\/") == os.path.normcase(os.path.realpath(b)).rstrip("\\/")
    except (OSError, ValueError):
        return False


def _write_json_atomic(path, data):
    """-> True when written (a refused write leaves nothing behind)."""
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        _quietly(os.remove, tmp)
        return False


def _keep_one_previous(m):
    """After a proven swap: the version just kept stays in previous\\<from> with its file list beside it; every
    other kept version (and, going back, the emptied folder that was swapped in) goes."""
    previous = os.path.abspath(m["previous"])
    root, kept = os.path.dirname(previous), os.path.basename(previous)
    if isinstance(m.get("kept_files"), dict):
        _write_json_atomic(os.path.join(root, f"{kept}.files.json"), m["kept_files"])
    for name in os.listdir(root):
        if name not in (kept, f"{kept}.files.json"):
            _remove(os.path.join(root, name))


def _result_file(m, marker_path, root):
    result_path = m.get("result_path")
    if not isinstance(result_path, str) or not _strictly_inside(root, result_path):
        result_path = marker_path + ".result"
    return result_path


def run_folder(marker_path, m, ops=None, clock=time.monotonic, sleep=time.sleep):
    """A 3.x hand-off from start to end (`_hand_off`). A marker an earlier swapper armed — so armed before this one
    started: that swap was cut off — is recovered (`recover`), never swapped a second time. The recovery entry goes
    the moment this ends, whatever the outcome. -> 0 on success, 2 on failure (`recover`'s codes when it recovers)."""
    ops = WinOps() if ops is None else ops
    root = os.path.dirname(os.path.abspath(marker_path))
    try:
        if m.get("armed"):
            return recover(marker_path, ops, sleep)
        return _hand_off(marker_path, m, ops, clock, sleep)
    finally:
        forget_recovery(root)


def _hand_off(marker_path, m, ops, clock, sleep):
    """The splash, the swap (or Setup), the uninstall entry, the result (`last_update_result.json`, this swap's
    alone), one previous version kept, the staged leftovers and the marker removed. -> 0 on success, 2 on failure."""
    root = os.path.dirname(os.path.abspath(marker_path))
    result_path = _result_file(m, marker_path, root)
    _quietly(os.remove, result_path)                        # the result belongs to THIS swap
    base = {"from": m.get("from_version", ""), "to": m.get("target_version", ""),
            "going_back": bool(m.get("going_back")), "kind": m.get("kind", "folder"),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        outside = _uncontained(m, root)
    except Exception as e:
        outside = f"unreadable ({type(e).__name__})"
    splash = None
    if outside is None and m.get("window"):
        splash = show_splash(m["target_version"], bool(m.get("going_back")))
    try:
        if outside is not None:
            # Nothing touched and nothing started: a marker reaching outside Surasura's folders isn't one it wrote.
            status, reason, touched = FAILED, f"the update's instructions were not Surasura's ({outside}), so " \
                                              "nothing was changed", False
        elif m.get("kind") == "installer":
            status, reason, touched = apply_installer(m, ops, clock, sleep, None if splash is None else splash.close,
                                                      arm=lambda: arm_recovery(marker_path, m))
        else:
            status, reason, touched = apply_folder(m, ops, clock, sleep, None if splash is None else splash.close)
    finally:
        if splash is not None:
            splash.close()
    restarted = True
    if status == SUCCESS:
        if m.get("kind") != "installer" and m.get("app_id"):
            write_uninstall_version(m["app_id"], m["install"], m["target_version"], _folder_kb(m["install"]))
        _quietly(_keep_one_previous, m)
        if m.get("kind") != "installer":
            _quietly(os.rmdir, m["staged"])                 # emptied by the moves
    elif outside is None:
        restarted = _restart(m, ops)
    if not restarted:
        reason += " -- and Surasura could not be started again"
    _write_json_atomic(result_path, dict(base, status=status, reason=reason, touched=touched))
    _quietly(os.remove, marker_path)
    return 0 if status == SUCCESS else 2


# =====================================================================================================================
# An installer-mode swap cut off half-way (S3.1-5): power lost, or the swapper and Setup both ended, with the program's
# entries in previous\<from> and Setup's work unfinished — the program folder can't start anything. Before its first
# move the swapper leaves Windows one value under HKCU's RunOnce (its only registry write besides the uninstall entry);
# at the next sign-in Windows runs it: `recover` finishes or undoes the swap from the marker alone.
# =====================================================================================================================
def _runonce_root():
    """HKCU's RunOnce key — or, for a test, the throwaway key TEST_RUNONCE_ENV names (only under Software\\
    SurasuraTests\\: nothing else can be pointed at). Under pytest without one: refused (OSError)."""
    test = os.environ.get(TEST_RUNONCE_ENV, "")
    if test.startswith("Software\\SurasuraTests\\"):
        return test
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise OSError("a test reached for the user's own RunOnce key")
    return RUNONCE_ROOT


def _recovery_value(root):
    """This install's value name: one per update folder (`root`), so a test copy never meets the real one."""
    import hashlib
    return f"{RECOVERY_NAME}-{hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode('utf-8')).hexdigest()[:12]}"


def recovery_command(marker_path):
    """What Windows runs at the next sign-in: this swapper — frozen, its own exe, the copy in update\\swapper\\ outside
    the program folder; from source, Python and this file — `--recover <marker>`."""
    me = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(__file__)]
    return " ".join(f'"{p}"' for p in me) + f' --recover "{os.path.abspath(marker_path)}"'


def arm_recovery(marker_path, m):
    """Just before installer mode's first move: the marker stamped "armed" (`recover` acts on no other), then the
    RunOnce value. Raises when either can't be written: then nothing moves."""
    import winreg
    m["armed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if not _write_json_atomic(marker_path, m):
        raise OSError("the update's marker could not be written")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _runonce_root(), 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, _recovery_value(os.path.dirname(os.path.abspath(marker_path))), 0, winreg.REG_SZ,
                          recovery_command(marker_path))


def forget_recovery(root):
    """The RunOnce value gone (the swap or the recovery ended, whatever the outcome). Never raises."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _runonce_root(), 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _recovery_value(root))
    except Exception:
        pass


def recover(marker_path, ops=None, sleep=time.sleep):
    """`updater.exe --recover <marker>`: an installer-mode swap cut off half-way, finished or undone — run by Windows at
    the next sign-in, and by a later swapper handed a marker an earlier one armed. Never starts the program:
      * something runs from the install folder -> left as it is;
      * the install holds the release — every file's sha256 and `--version`, the headless proof (D9) -> Setup
        finished: kept, one previous version kept, and the success result the app knows written;
      * otherwise -> installer mode's own failure branch (`_put_back`), and a failed result written.
    The marker goes after either of the last two; one missing, damaged or never armed moves nothing. The RunOnce value
    goes whatever the outcome. -> 0 finished, 2 put back, 1 nothing done."""
    ops = WinOps() if ops is None else ops
    root = os.path.dirname(os.path.abspath(marker_path))
    try:
        return _recover(marker_path, root, ops, sleep)
    finally:
        forget_recovery(root)


def _recover(marker_path, root, ops, sleep):
    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or m.get("format") != FORMAT or m.get("kind") != "installer" \
                or not m.get("armed") or _uncontained(m, root) is not None:
            return 1
        if ops.processes_in(m["install"]):
            return 1
    except Exception:
        return 1
    try:
        _verify(m["install"], m.get("files"))
        _reports(m, ops)
        status, reason = SUCCESS, RECOVERED
    except Exception:
        status, reason = FAILED, "the update was cut off before it finished, so the old version was put back"
        stuck = _put_back(m, sleep)
        if stuck:
            reason += f" -- and {len(stuck)} item(s) could not be put back"
    if status == SUCCESS:
        _quietly(_keep_one_previous, m)
    _write_json_atomic(_result_file(m, marker_path, root), {
        "from": m.get("from_version", ""), "to": m["target_version"], "going_back": False, "kind": "installer",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": status, "reason": reason, "touched": True})
    _quietly(os.remove, marker_path)
    return 0 if status == SUCCESS else 2


def _put_back(m, sleep):
    """`apply_installer`'s failure branch from the marker alone, with no journal: what Setup wrote under a name
    previous\\<from> holds, or under a name the old program never had (`kept_files`), goes; every entry previous\\<from>
    holds comes back; the uninstall entry names <from>. An old entry the cut-off swap never moved stays where it is.
    -> the entries that couldn't be put back."""
    install, previous = m["install"], m["previous"]
    kept = m.get("kept_files")
    old = {path.split("/")[0].lower() for path in kept} if isinstance(kept, dict) and kept else None    # unknown: keep
    held = [name for name in m["owned"] if os.path.lexists(os.path.join(previous, name))]
    _clear_setups(m, [name for name in m["owned"] if name in held or (old is not None and name.lower() not in old)],
                  sleep)
    stuck = []
    for name in held:
        try:
            _move([name], previous, install, [], sleep)
        except OSError:
            stuck.append(name)
    _quietly(os.rmdir, previous)
    if m.get("app_id"):
        _quietly(write_uninstall_version, m["app_id"], install, m.get("from_version", ""))
    return stuck


# =====================================================================================================================
# The splash (S3.1 D10): hato's, in Surasura's theme — raw Win32 through ctypes, on its own thread: a translucent dark
# card, always on top, never focused, never catching a click; the mark, "Updating Surasura to X" ("Going back to X"),
# a sweeping accent line. It goes at the first sight of the new window. Nothing here ever raises.
# =====================================================================================================================
# The colours, (r, g, b). TO RE-SKIN for the 3.0 theme: today's palette (GUI_Design_Guidelines.md), in one table —
# nothing else in this file names a colour.
SPLASH_COLOURS = {
    "bg": (0x1E, 0x1E, 0x1E),           # BG: the card
    "surface": (0x2D, 0x2D, 0x2D),      # SURFACE: its edge, the sweep's track
    "text": (0xE0, 0xE0, 0xE0),         # TEXT: "Updating Surasura to"
    "dim": (0x9E, 0x9E, 0x9E),          # the line under it
    "accent": (0xBB, 0x86, 0xFC),       # ACCENT: the version, the sweep
}
SPLASH_CLASS = "SurasuraUpdateSplash"
SPLASH_OPACITY = 240                    # the card's translucency, 0-255
SPLASH_TITLE, SPLASH_TITLE_BACK = "Updating Surasura to ", "Going back to "
SPLASH_SUBTITLE = "Surasura opens again in a moment"
_SPLASH_W, _SPLASH_H, _SPLASH_R = 360, 92, 10            # the card, in 96-DPI pixels
_SWEEP_SECONDS, _SWEEP_WIDTH, _FRAME_MS, _FADE = 1.4, 0.38, 16, 0.12


def _mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def card_pixels(width, height, radius):
    """The card as premultiplied BGRA bytes, rounded and edged, anti-aliased at the corners -> (pixels, alphas)."""
    bg, edge = SPLASH_COLOURS["bg"], SPLASH_COLOURS["surface"]
    fill = bytes((bg[2], bg[1], bg[0], 255))
    rim = bytes((edge[2], edge[1], edge[0], 255))
    row = rim + fill * (width - 2) + rim
    px = bytearray(row * height)
    px[:width * 4] = rim * width
    px[-width * 4:] = rim * width
    for y in range(radius):
        for x in range(radius):
            d = math.hypot(radius - x - 0.5, radius - y - 0.5)
            outer = min(1.0, max(0.0, radius - d + 0.5))
            inner = min(1.0, max(0.0, radius - 1 - d + 0.5))
            colour, a = _mix(edge, bg, inner), int(round(255 * outer))
            for xx, yy in ((x, y), (width - 1 - x, y), (x, height - 1 - y), (width - 1 - x, height - 1 - y)):
                i = (yy * width + xx) * 4
                px[i:i + 4] = bytes((colour[2] * a // 255, colour[1] * a // 255, colour[0] * a // 255, a))
    return px, bytes(px[3::4])


def sweep_row(width, phase):
    """One row of the sweep: the track, with the accent's segment where `phase` (0..1) puts it -> BGRA bytes."""
    track, accent = SPLASH_COLOURS["surface"], SPLASH_COLOURS["accent"]
    eased = 1 - (1 - phase) ** 3
    left = int((-0.40 + 1.40 * eased) * width)
    lo, hi = max(0, left), min(width, left + int(_SWEEP_WIDTH * width))
    t, a = bytes((track[2], track[1], track[0], 255)), bytes((accent[2], accent[1], accent[0], 255))
    return t * lo + a * max(0, hi - lo) + t * (width - max(lo, hi))


class Splash:
    """The card; `close()` takes it away (idempotent, any thread, never raises). `drawn` is set once it is on
    screen."""

    def __init__(self, version, going_back):
        self.version, self.going_back = str(version or ""), bool(going_back)
        self.drawn = threading.Event()
        self.ready = threading.Event()
        self.closing = None
        self.thread = None

    def close(self, wait=1.0):
        try:
            if self.closing is None:
                self.closing = time.monotonic()
            if self.thread is not None and self.thread is not threading.current_thread():
                self.thread.join(wait)
        except Exception:
            pass


def show_splash(version, going_back=False, wait=3.0):
    """The splash up -> a `Splash`, drawn or not. Returns once it is on screen, has failed, or `wait` s passed."""
    splash = Splash(version, going_back)
    if sys.platform != "win32":
        return splash
    try:
        splash.thread = threading.Thread(target=_splash_thread, args=(splash,), name="surasura-splash", daemon=True)
        splash.thread.start()
        splash.ready.wait(wait)
    except Exception:
        pass
    return splash


def _splash_thread(splash):
    try:
        _SplashWindow(splash).run()
    except Exception:
        pass
    finally:
        splash.ready.set()


_WIN32 = {}


def _win32():
    """The Win32 calls the splash makes, each declared once -> a namespace."""
    if "api" in _WIN32:
        return _WIN32["api"]
    import ctypes
    from ctypes import wintypes as W

    class Api:
        pass

    api = Api()
    api.ct, api.W = ctypes, W
    api.WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", W.UINT), ("style", W.UINT), ("lpfnWndProc", api.WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", W.HINSTANCE),
                    ("hIcon", W.HICON), ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH),
                    ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR), ("hIconSm", W.HICON)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                    ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                    ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                    ("biClrImportant", W.DWORD)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]

    api.WNDCLASSEXW, api.BITMAPINFOHEADER, api.BLENDFUNCTION, api.MONITORINFO = \
        WNDCLASSEXW, BITMAPINFOHEADER, BLENDFUNCTION, MONITORINFO
    u = api.u = ctypes.WinDLL("user32", use_last_error=True)
    g = api.g = ctypes.WinDLL("gdi32", use_last_error=True)
    k = api.k = ctypes.WinDLL("kernel32", use_last_error=True)
    P, H = ctypes.c_void_p, W.HANDLE

    def declare(function, restype, argtypes):
        function.restype, function.argtypes = restype, argtypes

    declare(k.GetModuleHandleW, W.HMODULE, [W.LPCWSTR])
    declare(u.RegisterClassExW, W.ATOM, [ctypes.POINTER(WNDCLASSEXW)])
    declare(u.CreateWindowExW, W.HWND, [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID])
    declare(u.DefWindowProcW, ctypes.c_ssize_t, [W.HWND, W.UINT, W.WPARAM, W.LPARAM])
    declare(u.DestroyWindow, W.BOOL, [W.HWND])
    declare(u.IsWindow, W.BOOL, [W.HWND])
    declare(u.IsWindowVisible, W.BOOL, [W.HWND])
    declare(u.ShowWindow, W.BOOL, [W.HWND, ctypes.c_int])
    declare(u.FindWindowExW, W.HWND, [W.HWND, W.HWND, W.LPCWSTR, W.LPCWSTR])
    declare(u.GetWindowThreadProcessId, W.DWORD, [W.HWND, ctypes.POINTER(W.DWORD)])
    declare(u.SetTimer, ctypes.c_size_t, [W.HWND, ctypes.c_size_t, W.UINT, P])
    declare(u.KillTimer, W.BOOL, [W.HWND, ctypes.c_size_t])
    declare(u.GetMessageW, W.BOOL, [ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT])
    declare(u.TranslateMessage, W.BOOL, [ctypes.POINTER(W.MSG)])
    declare(u.DispatchMessageW, ctypes.c_ssize_t, [ctypes.POINTER(W.MSG)])
    declare(u.PostQuitMessage, None, [ctypes.c_int])
    declare(u.GetCursorPos, W.BOOL, [ctypes.POINTER(W.POINT)])
    declare(u.MonitorFromPoint, H, [W.POINT, W.DWORD])
    declare(u.GetMonitorInfoW, W.BOOL, [H, ctypes.POINTER(MONITORINFO)])
    declare(u.UpdateLayeredWindow, W.BOOL, [W.HWND, W.HDC, ctypes.POINTER(W.POINT), ctypes.POINTER(W.SIZE), W.HDC,
                                            ctypes.POINTER(W.POINT), W.COLORREF, ctypes.POINTER(BLENDFUNCTION),
                                            W.DWORD])
    declare(u.DrawIconEx, W.BOOL, [W.HDC, ctypes.c_int, ctypes.c_int, W.HICON, ctypes.c_int, ctypes.c_int, W.UINT,
                                   W.HBRUSH, W.UINT])
    declare(u.DestroyIcon, W.BOOL, [W.HICON])
    declare(u.PrivateExtractIconsW, W.UINT, [W.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                             ctypes.POINTER(W.HICON), ctypes.POINTER(W.UINT), W.UINT, W.UINT])
    declare(g.CreateCompatibleDC, W.HDC, [W.HDC])
    declare(g.DeleteDC, W.BOOL, [W.HDC])
    declare(g.CreateDIBSection, W.HBITMAP, [W.HDC, ctypes.POINTER(BITMAPINFOHEADER), W.UINT, ctypes.POINTER(P), H,
                                            W.DWORD])
    declare(g.SelectObject, H, [W.HDC, H])
    declare(g.DeleteObject, W.BOOL, [H])
    declare(g.CreateFontW, W.HFONT, [ctypes.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR])
    declare(g.SetBkMode, ctypes.c_int, [W.HDC, ctypes.c_int])
    declare(g.SetTextColor, W.COLORREF, [W.HDC, W.COLORREF])
    declare(g.TextOutW, W.BOOL, [W.HDC, ctypes.c_int, ctypes.c_int, W.LPCWSTR, ctypes.c_int])
    declare(g.GetTextExtentPoint32W, W.BOOL, [W.HDC, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.SIZE)])
    declare(g.GdiFlush, W.BOOL, [])
    api.set_dpi = api.monitor_dpi = None
    try:
        declare(u.SetThreadDpiAwarenessContext, P, [P])
        api.set_dpi = u.SetThreadDpiAwarenessContext
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        declare(shcore.GetDpiForMonitor, ctypes.c_long, [H, ctypes.c_int, ctypes.POINTER(W.UINT),
                                                         ctypes.POINTER(W.UINT)])
        api.monitor_dpi = shcore.GetDpiForMonitor
    except (OSError, AttributeError):
        pass
    _WIN32["api"] = api
    return api


_LIVE = {}          # hwnd -> its _SplashWindow, for the one window procedure


def _procedure(hwnd, message, wparam, lparam):
    """The splash's window procedure. Nothing may leave it: an exception crossing into Windows ends the process."""
    try:
        window = _LIVE.get(hwnd)
        if window is not None:
            answer = window.on_message(message)
            if answer is not None:
                return answer
        return _win32().u.DefWindowProcW(hwnd, message, wparam, lparam)
    except Exception:
        return 0


def _register(api):
    """The window class, once per process; its procedure held here for the life of the process (a callback only a
    local holds is freed, and Windows then calls into dead memory)."""
    if not _WIN32.get("atom"):
        _WIN32["proc"] = api.WNDPROC(_procedure)
        klass = api.WNDCLASSEXW()
        klass.cbSize = api.ct.sizeof(api.WNDCLASSEXW)
        klass.lpfnWndProc = _WIN32["proc"]
        klass.hInstance = api.k.GetModuleHandleW(None)
        klass.lpszClassName = SPLASH_CLASS
        _WIN32["atom"] = api.u.RegisterClassExW(api.ct.byref(klass))
    return bool(_WIN32.get("atom"))


def _colorref(rgb):
    return rgb[0] | (rgb[1] << 8) | (rgb[2] << 16)


class _SplashWindow:
    WM_DESTROY, WM_CLOSE, WM_TIMER = 0x0002, 0x0010, 0x0113
    # Layered, click-through, above everything, never on the taskbar, never activated.
    EX_STYLE = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000
    WS_POPUP = 0x80000000

    def __init__(self, splash):
        self.splash = splash
        self.api = None
        self.hwnd = self.dc = self.bitmap = self.old = self.bits = None
        self.shown = None

    def _place(self):
        """-> (scale, work area) of the monitor under the pointer, this thread made per-monitor aware first."""
        api = self.api
        if api.set_dpi is not None:
            api.set_dpi(api.ct.c_void_p(-4))                     # PER_MONITOR_AWARE_V2
        point = api.W.POINT()
        api.u.GetCursorPos(api.ct.byref(point))
        monitor = api.u.MonitorFromPoint(point, 2)              # NEAREST
        info = api.MONITORINFO()
        info.cbSize = api.ct.sizeof(api.MONITORINFO)
        if not api.u.GetMonitorInfoW(monitor, api.ct.byref(info)):
            return None
        dpi = 96
        if api.monitor_dpi is not None:
            x, y = api.W.UINT(), api.W.UINT()
            if api.monitor_dpi(monitor, 0, api.ct.byref(x), api.ct.byref(y)) == 0 and x.value:
                dpi = int(x.value)
        return dpi / 96.0, info.rcWork

    def _paint(self, scale):
        """The card, the mark and the words into the bitmap; the alpha GDI's text wipes put back."""
        api = self.api
        ct, g, u = api.ct, api.g, api.u
        w, h = self.size.cx, self.size.cy
        px, alphas = card_pixels(w, h, max(2, int(_SPLASH_R * scale)))
        ct.memmove(self.bits, bytes(px), len(px))
        pad, mark = int(20 * scale), int(40 * scale)
        icon_from = sys.executable if getattr(sys, "frozen", False) else None
        if icon_from:
            icon = api.W.HICON()
            if u.PrivateExtractIconsW(icon_from, 0, mark, mark, ct.byref(icon), None, 1, 0) == 1 and icon:
                u.DrawIconEx(self.dc, pad, int(18 * scale), icon, mark, mark, 0, None, 3)    # DI_NORMAL
                u.DestroyIcon(icon)
        x = pad + mark + int(14 * scale)
        fonts = []
        try:
            g.SetBkMode(self.dc, 1)                              # TRANSPARENT
            lead = SPLASH_TITLE_BACK if self.splash.going_back else SPLASH_TITLE
            fonts.append(g.CreateFontW(-int(14.5 * scale), 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"))
            g.SelectObject(self.dc, fonts[-1])
            g.SetTextColor(self.dc, _colorref(SPLASH_COLOURS["text"]))
            g.TextOutW(self.dc, x, int(20 * scale), lead, len(lead))
            extent = api.W.SIZE()
            g.GetTextExtentPoint32W(self.dc, lead, len(lead), ct.byref(extent))
            g.SetTextColor(self.dc, _colorref(SPLASH_COLOURS["accent"]))
            g.TextOutW(self.dc, x + extent.cx, int(20 * scale), self.splash.version, len(self.splash.version))
            fonts.append(g.CreateFontW(-int(11.5 * scale), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"))
            g.SelectObject(self.dc, fonts[-1])
            g.SetTextColor(self.dc, _colorref(SPLASH_COLOURS["dim"]))
            g.TextOutW(self.dc, x, int(43 * scale), SPLASH_SUBTITLE, len(SPLASH_SUBTITLE))
            g.GdiFlush()
        finally:
            g.SelectObject(self.dc, self.bitmap)                 # no font selected while it is deleted
            for font in fonts:
                if font:
                    g.DeleteObject(font)
        drawn = bytearray(ct.string_at(self.bits, len(px)))
        drawn[3::4] = alphas                                     # GDI writes 0 alpha where it draws
        ct.memmove(self.bits, bytes(drawn), len(drawn))
        self.sweep_at = (int(70 * scale) * w + pad) * 4
        self.sweep_w, self.sweep_h = w - 2 * pad, max(2, int(3 * scale))

    def run(self):
        api = self.api = _win32()
        ct, W, u, g = api.ct, api.W, api.u, api.g
        placed = self._place()
        if placed is None or not _register(api) or self.splash.closing is not None:
            return
        scale, work = placed
        self.size = W.SIZE(int(_SPLASH_W * scale), int(_SPLASH_H * scale))
        self.origin = W.POINT(work.left + (work.right - work.left - self.size.cx) // 2,
                              work.top + (work.bottom - work.top - self.size.cy) // 2)
        hwnd = u.CreateWindowExW(self.EX_STYLE, SPLASH_CLASS, "Updating Surasura", self.WS_POPUP, self.origin.x,
                                 self.origin.y, self.size.cx, self.size.cy, None, None, api.k.GetModuleHandleW(None),
                                 None)
        if not hwnd:
            return
        self.hwnd = hwnd
        _LIVE[hwnd] = self
        try:
            self.dc = g.CreateCompatibleDC(None)
            header = api.BITMAPINFOHEADER()
            header.biSize = ct.sizeof(api.BITMAPINFOHEADER)
            header.biWidth, header.biHeight, header.biPlanes, header.biBitCount = \
                self.size.cx, -self.size.cy, 1, 32
            bits = ct.c_void_p()
            self.bitmap = g.CreateDIBSection(self.dc, ct.byref(header), 0, ct.byref(bits), None, 0)
            if not self.dc or not self.bitmap or not bits.value:
                return
            self.bits = bits.value
            self.old = g.SelectObject(self.dc, self.bitmap)
            self._paint(scale)
            if self.splash.closing is not None:
                return
            self.shown = time.monotonic()
            self._present(0)
            u.ShowWindow(hwnd, 4)                                # SW_SHOWNOACTIVATE
            u.SetTimer(hwnd, 1, _FRAME_MS, None)
            self.splash.drawn.set()
            self.splash.ready.set()
            message = W.MSG()
            while u.GetMessageW(ct.byref(message), None, 0, 0) > 0:
                u.TranslateMessage(ct.byref(message))
                u.DispatchMessageW(ct.byref(message))
        finally:
            _LIVE.pop(hwnd, None)
            if u.IsWindow(hwnd):
                u.DestroyWindow(hwnd)
            if self.old:
                g.SelectObject(self.dc, self.old)
            if self.bitmap:
                g.DeleteObject(self.bitmap)
            if self.dc:
                g.DeleteDC(self.dc)

    def on_message(self, message):
        if message == self.WM_TIMER:
            self.frame()
            return 0
        if message == self.WM_CLOSE:
            self.api.u.DestroyWindow(self.hwnd)
            return 0
        if message == self.WM_DESTROY:
            self.api.u.KillTimer(self.hwnd, 1)
            self.api.u.PostQuitMessage(0)
            return 0
        return None

    def frame(self):
        """One frame: the sweep moved, the fade stepped; the window gone at the end of a fade out."""
        now = time.monotonic()
        opacity = min(1.0, (now - self.shown) / _FADE)
        if self.splash.closing is not None:
            opacity = min(opacity, 1.0 - (now - max(self.splash.closing, self.shown)) / _FADE)
            if opacity <= 0:
                self.api.u.DestroyWindow(self.hwnd)
                return
        row = sweep_row(self.sweep_w, ((now - self.shown) % _SWEEP_SECONDS) / _SWEEP_SECONDS)
        for line in range(self.sweep_h):
            self.api.ct.memmove(self.bits + self.sweep_at + line * self.size.cx * 4, row, len(row))
        self._present(int(SPLASH_OPACITY * opacity))

    def _present(self, alpha):
        api = self.api
        blend = api.BLENDFUNCTION(0, 0, max(0, min(255, alpha)), 1)          # AC_SRC_OVER, AC_SRC_ALPHA
        api.u.UpdateLayeredWindow(self.hwnd, None, api.ct.byref(self.origin), api.ct.byref(self.size), self.dc,
                                  api.ct.byref(api.W.POINT(0, 0)), 0, api.ct.byref(blend), 0x02)   # ULW_ALPHA


def splash_windows(pid=None):
    """The visible splash windows -> [(hwnd, owner pid)], only `pid`'s when given. Never raises."""
    if sys.platform != "win32":
        return []
    try:
        api, found, hwnd = _win32(), [], None
        while True:
            hwnd = api.u.FindWindowExW(None, hwnd, SPLASH_CLASS, None)
            if not hwnd:
                return found
            owner = api.W.DWORD()
            api.u.GetWindowThreadProcessId(hwnd, api.ct.byref(owner))
            if api.u.IsWindowVisible(hwnd) and (pid is None or owner.value == pid):
                found.append((hwnd, owner.value))
    except Exception:
        return []


def selftest(out):
    """`updater.exe --selftest out.json`: can this build draw the splash? Writes {splash, drawn, found, frozen,
    pid} into `out` (a windowless program has nowhere to print). -> 0"""
    splash = show_splash("0.0.0")
    found = bool(splash.drawn.is_set() and splash_windows(os.getpid()))
    splash.close()
    _write_json_atomic(out, {"splash": SPLASH_CLASS, "drawn": splash.drawn.is_set(), "found": found,
                             "frozen": bool(getattr(sys, "frozen", False)), "pid": os.getpid()})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Surasura update helper (internal).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--marker", help="Path to pending_update.json")
    group.add_argument("--selftest", help="Draw the splash once and write what was seen to this JSON file")
    group.add_argument("--recover", help="Finish or undo an installer-mode update cut off half-way (Windows runs this "
                                         "at the next sign-in)")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest(args.selftest)
    if args.recover:
        return recover(args.recover)
    return run(args.marker)


if __name__ == "__main__":
    sys.exit(main())
