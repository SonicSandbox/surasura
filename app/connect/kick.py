"""Connect on demand (P2.1 row 2.1.5; P1.5 03-actors §5 Q4, 02 §2a): nothing runs Connect in the background by
itself; when work appears — a placement into the top 20, a hato drop — the caller kicks it, and `kick` starts
`surasura-cli connect` detached unless Connect is off, already running (its single-instance lock, `connect`), or an
update is staged (the updater swaps the files first; Connect refuses to start meanwhile). A Connect already running
reads the log again before it exits, so a kick it answered isn't lost.

The started Connect runs its loop (P2.4, `surasura-cli connect`): it reads every language's inbox, mines the jobs, and
exits when no job is left (P2.1 started `--consume-only`, the inbox read once).
The lock lives per install today (`get_local_data_path()/locks/`); one Connect per Windows user (`locks.SHARED`) is
asked of Haya at P2.4's build.

Under a test root nothing is started unless the test asks for it (`SURASURA_CONNECT_KICK=1`): a detached process
outliving its test would hold the test's folder.
"""
import os
import subprocess
import sys

LOCK = "connect"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000      # outlives a caller's job object (hato closing its own children)


def running():
    """Is a Connect running for this install? (its lock held: the OS frees it when the process dies). A look that
    takes nothing and writes nothing."""
    from app import locks
    return locks.in_use(LOCK)


def command():
    """`surasura-cli connect`: the command-line program beside this one when frozen (`Surasura.exe` and
    `surasura-cli.exe` ship side by side), else `python -m app.cli`."""
    from app.path_utils import is_frozen
    args = ["connect"]
    if is_frozen():
        name = "surasura-cli.exe" if sys.platform == "win32" else "surasura-cli"
        return [os.path.join(os.path.dirname(sys.executable), name)] + args
    return [sys.executable, "-m", "app.cli"] + args


def kick(settings):
    """Start Connect if it should run -> the started process (a `subprocess.Popen`), or None."""
    if not settings.get("connect_enabled"):
        return None
    if os.environ.get("SURASURA_TEST_ROOT") and os.environ.get("SURASURA_CONNECT_KICK") != "1":
        return None
    from app import library_store
    if library_store.update_staged(looks=library_store.PROBE_LOOKS) or running():
        return None
    from app.path_utils import build_subprocess_env, get_local_data_path, is_frozen
    where = get_local_data_path()             # never a folder the updater swaps
    os.makedirs(where, exist_ok=True)
    options = dict(cwd=where, env=build_subprocess_env(is_frozen()), stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if sys.platform != "win32":
        return subprocess.Popen(command(), start_new_session=True, **options)
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP          # no console, no Ctrl+C from the caller's
    try:
        return subprocess.Popen(command(), creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **options)
    except OSError:             # a job that forbids breaking away: Connect lives as long as its caller's job
        return subprocess.Popen(command(), creationflags=flags, **options)
