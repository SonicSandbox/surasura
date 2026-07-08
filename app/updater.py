"""In-app update stager.

Turns an available :class:`~app.update_checker.UpdateInfo` into an armed, verified update:
download the app-code package -> checksum it -> extract & validate it -> write the
``pending_update.json`` marker. The actual on-disk swap is performed AFTER the app exits by
the standalone ``updater.exe`` (see ``updater_helper.py``); this module only stages and hands
off, then reads back the result on the next launch.

Deliberately UI-free (no tkinter) so every step is unit-testable, and deliberately narrow in
what it touches: only program files under the frozen ``_internal/`` dir plus the small
marker / result JSONs next to the executable. It NEVER reads or writes User Files, data,
results, or settings.json — user data is entirely outside the blast radius.
"""
import os
import sys
import json
import hashlib
import zipfile
import shutil
import subprocess
import urllib.request

from app import __version__
from app import path_utils

_USER_AGENT = "Surasura-Readability-Analyzer"

STAGING_DIRNAME = ".update_staging"
BACKUP_DIRNAME = ".update_backup"
MARKER_NAME = "pending_update.json"
RESULT_NAME = "last_update_result.json"
UPDATER_EXE_NAME = "updater.exe"


class UpdateError(Exception):
    """Raised when staging an update fails. Nothing is armed when this is raised."""


# ---------------------------------------------------------------------------
# Locations. The install root (next to the exe) holds the marker/staging/updater.exe;
# the frozen _internal dir holds the program dirs (app/, templates/) we replace.
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


def can_auto_apply():
    """Auto-apply is only possible in a frozen build that shipped the bundled updater.exe."""
    return path_utils.is_frozen() and os.path.exists(updater_exe_path())


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


EXE_NAME = "Surasura.exe"


def extract_and_validate(zip_path, payload_dir):
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
    staged_exe = os.path.join(payload_dir, EXE_NAME)
    exe_sha = sha256_file(staged_exe) if os.path.isfile(staged_exe) else ""
    return {
        "target_version": info.version,
        "from_version": __version__,
        "app_pid": app_pid,
        "attempt": 0,
        "staging_dir": staging_dir(),
        "payload_dir": payload_dir,
        "base_dir": base,
        "backup_dir": backup_dir(),
        "targets": [
            {"name": EXE_NAME, "kind": "file", "dest": sys.executable, "sha256": exe_sha},
            {"name": "templates", "kind": "dir", "dest": os.path.join(base, "templates")},
        ],
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
    """Download -> verify checksum -> extract & validate -> write marker.

    Returns the marker path (update is armed). Raises UpdateError on any failure, having
    cleaned up the staging dir so nothing is left armed. Does NOT launch the helper or exit
    the app — the caller does that on the main thread after this returns.
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
        if not extract_and_validate(zip_path, payload_dir):
            raise UpdateError("update package failed validation")

        marker = build_marker(info, payload_dir, os.getpid())
        return write_marker(marker)
    except UpdateError:
        shutil.rmtree(sd, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(sd, ignore_errors=True)
        raise UpdateError(str(e))


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
    """Remove every trace of a pending/finished update: marker, result, staging, backup."""
    for path in (marker_path(), result_path()):
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
        _cleanup_all()
        return res

    mp = marker_path()
    if os.path.exists(mp):
        try:
            with open(mp, "r", encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            m = {}
        _cleanup_all()
        return {
            "status": "failed",
            "from": m.get("from_version", ""),
            "to": m.get("target_version", ""),
            "reason": "update did not complete",
        }

    return None


def effective_class(cls, info, skipped_version="", auto_enabled=True, can_apply=True):
    """Downgrade an 'APP' classification to 'FULL' (manual) when auto-apply must not happen.

    This is the loop/kill-switch guard, kept as a pure function so it is directly testable:
      * auto-updates disabled in settings, or no bundled updater.exe -> never auto-apply.
      * the target version already failed/was skipped once -> never auto-apply it again.
    'NONE' and 'FULL' pass through unchanged.
    """
    if cls != "APP":
        return cls
    if not auto_enabled or not can_apply:
        return "FULL"
    if info is not None and getattr(info, "version", "") and info.version == skipped_version:
        return "FULL"
    return "APP"
