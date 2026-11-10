# SPDX-License-Identifier: GPL-3.0-or-later
"""
Manages the yt-dlp executable for the YouTube Downloader module.

Strategy (chosen for robustness): we do NOT freeze yt-dlp into the Surasura build.
Instead we manage the official standalone yt-dlp binary in a user-writable folder
(%APPDATA%/Houseki/Surasura/bin/) and drive it via the CLI. yt-dlp breaks
periodically when YouTube changes, so the GUI exposes a one-click update that runs
yt-dlp's built-in self-update (`yt-dlp -U`). This way a YouTube breakage is fixed
without rebuilding/reshipping the whole app.
"""

import os
import sys
import shutil
import subprocess
import stat
import time
import urllib.request

from app.path_utils import persistent_root

# Official latest-release assets.
_URLS = {
    "win32": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "darwin": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos",
    "linux": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp",
}


def no_window_flag():
    """Avoid flashing a console window when shelling out on Windows."""
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _bin_dir():
    """The managed binary's folder, never made here: asking where yt-dlp is, or whether it is there, makes no folder in
    the user's profile (a `get_ytdlp_path()` run by hand made the real, empty %APPDATA%\\Houseki\\Surasura\\bin,
    2026-10-31). `download` makes it."""
    return os.path.join(persistent_root(), "bin")


def _exe_name():
    return "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"


def get_ytdlp_path():
    """Absolute path to the managed yt-dlp binary (may not exist yet)."""
    return os.path.join(_bin_dir(), _exe_name())


def is_available():
    return os.path.isfile(get_ytdlp_path())


def _download_url():
    return _URLS.get(sys.platform, _URLS["linux"])


def download(log=print):
    """Download the latest yt-dlp into the managed bin dir. Returns the path."""
    url = _download_url()
    dest = get_ytdlp_path()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    log(f"Downloading yt-dlp from {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "Surasura"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)
    if sys.platform != "win32":
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    log("yt-dlp ready.")
    return dest


def ensure_available(log=print):
    """Return a usable yt-dlp path, downloading it on first use. None on failure."""
    if is_available():
        return get_ytdlp_path()
    try:
        return download(log)
    except Exception as e:
        log(f"Could not download yt-dlp: {e}")
        log("Check your internet connection and try 'Update yt-dlp' again.")
        return None


class Stopped(Exception):
    """The run that started yt-dlp was asked to stop (a cancelled job, a closed window, the app's quit): its child was
    ended."""

    def __init__(self):
        super().__init__("stopped")


POLL = 0.2              # how often a running child's owner is asked whether to stop


def run(cmd, timeout, should_stop=None, tick=None):
    """`cmd` (yt-dlp) as a child, answered as `subprocess.run(capture_output=True, text=True)` answered — but asked
    every POLL s whether to stop: `should_stop()` true ends the child (terminate, then kill) and raises Stopped; past
    `timeout` it is ended and TimeoutExpired raised, as `subprocess.run` did. `tick()` is asked every POLL s too
    (alpha 8: a download's progress and its stall check): what it raises ends the child and is raised. Never a child
    left running."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                            encoding="utf-8", errors="replace", creationflags=no_window_flag())
    deadline = time.monotonic() + timeout
    while True:
        try:
            out, err = proc.communicate(timeout=POLL)
            return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            if should_stop is not None and should_stop():
                _end(proc)
                raise Stopped()
            if time.monotonic() >= deadline:
                _end(proc)
                raise subprocess.TimeoutExpired(cmd, timeout)
            if tick is not None:
                try:
                    tick()
                except BaseException:                   # (raised in this handler: the one below never sees it)
                    _end(proc)
                    raise
        except BaseException:
            _end(proc)
            raise


def _end(proc):
    for stop in (proc.terminate, proc.kill):
        try:
            stop()
            proc.communicate(timeout=5)
            return
        except Exception:
            continue


def current_version(log=print):
    """Return the installed yt-dlp version string, or None if unavailable."""
    if not is_available():
        return None
    try:
        res = subprocess.run(
            [get_ytdlp_path(), "--version"],
            capture_output=True, text=True, timeout=30,
            creationflags=no_window_flag(),
        )
        return (res.stdout or "").strip() or None
    except Exception:
        return None


def update(log=print, should_stop=None):
    """Self-update via `yt-dlp -U`; fall back to re-downloading the latest. `should_stop()` true (3.0: the job
    cancelled, the app quitting) ends the self-update's child; nothing is re-downloaded then."""
    if not is_available():
        log("yt-dlp not installed yet — fetching the latest version ...")
        return ensure_available(log)
    try:
        log("Updating yt-dlp (self-update) ...")
        res = run([get_ytdlp_path(), "-U"], 180, should_stop=should_stop)
        out = ((res.stdout or "") + (res.stderr or "")).strip()
        log(out or "yt-dlp is up to date.")
        return get_ytdlp_path()
    except Stopped:
        log("Stopped.")
        return None
    except Exception as e:
        log(f"Self-update failed ({e}); re-downloading the latest build ...")
        try:
            return download(log)
        except Exception as e2:
            log(f"Re-download failed: {e2}")
            return None
