"""Standalone update helper for Surasura — frozen into `updater.exe`.

This runs AS A SEPARATE PROCESS, launched by the dashboard just before it exits. It swaps
the freshly-downloaded app-code payload (``app/`` + ``templates/``) into the frozen
``_internal/`` folder, then relaunches the app.

Design constraints (why this is its own file / its own exe):
  * It imports NOTHING from ``app/`` — so it can never hold open the very files it must
    replace, and it works even while the payload it is installing is broken.
  * Every path it needs comes from the marker JSON, so it has no knowledge of the install
    layout and needs no ``path_utils``.
  * It is stdlib-only and Unicode-safe (users' install paths routinely contain Japanese /
    Chinese characters), and it is unit-tested as plain Python before it is ever frozen.

Invariants that make an auto-update un-botchable:
  * It only ever touches program dirs named in the marker (``app`` / ``templates``) plus the
    small marker / result JSONs. It never reads or writes User Files, data, results, or
    settings.json.
  * It backs up what it replaces first and rolls back on ANY failure, so a bad swap always
    leaves a working install.
  * It increments the marker's attempt counter BEFORE acting, so a crash mid-swap is visible
    to the app on next launch and is never retried automatically.
"""
import os
import sys
import json
import time
import shutil
import argparse
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


def run(marker_path):
    """Full helper lifecycle around apply_update(): attempt-count, wait, apply, report."""
    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            marker = json.load(f)
    except Exception:
        return 1

    # Record the attempt for diagnostics. (The real guard against retry loops is the app's
    # `skipped_version`, set when it sees a failed/interrupted result — see app/updater.py.)
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Surasura update helper (internal).")
    parser.add_argument("--marker", required=True, help="Path to pending_update.json")
    args = parser.parse_args(argv)
    return run(args.marker)


if __name__ == "__main__":
    sys.exit(main())
