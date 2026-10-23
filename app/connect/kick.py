"""Connect on demand (P2.1 row 2.1.5; P1.5 03-actors §5 Q4, 02 §2a): nothing runs Connect in the background by
itself; when work appears — a placement into the top 20, a hato drop — the caller kicks it, and `kick` starts
`surasura-cli connect` detached unless Connect is off, already running (its single-instance lock, `connect`), or an
update is staged (the updater swaps the files first; Connect refuses to start meanwhile). A Connect already running
reads the log again before it exits, so a kick it answered isn't lost — and a kick to it stamps its wake mark
(`wake`, `<local data>/connect/wake`), which ends the pause between its looks: a *Mine now* or a setting that lets
waiting episodes go is read within seconds, never at the 2-minute look (laptop round 7 #42).

The started Connect runs its loop (P2.4, `surasura-cli connect`): it reads every language's inbox, mines the jobs, and
exits when no job is left (P2.1 started `--consume-only`, the inbox read once).
The lock lives per install today (`get_local_data_path()/locks/`); one Connect per Windows user (`locks.SHARED`) is
asked of Haya at P2.4's build.

Under a test root nothing is started unless the test asks for it (`SURASURA_CONNECT_KICK=1`): a detached process
outliving its test would hold the test's folder.
"""
import itertools
import os
import subprocess
import sys

LOCK = "connect"
WAKE = "wake"
_STAMPS = itertools.count(1)    # this process's kicks: two in one tick of Windows' clock (~16 ms) still differ
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000      # outlives a caller's job object (hato closing its own children)


def running():
    """Is a Connect running for this install? (its lock held: the OS frees it when the process dies). A look that
    takes nothing and writes nothing."""
    from app import locks
    return locks.in_use(LOCK)


def wake_path():
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect", WAKE)


def wake_stamp():
    """The wake mark's stamp (the time `wake` wrote, ~20 bytes read), or None when there is none — never the file's
    modified time, which two kicks in one tick of the file system's clock share. A running Connect compares it between
    looks (`runner.Steps.kicked`)."""
    try:
        with open(wake_path(), encoding="utf-8") as f:
            return f.read(64)
    except OSError:
        return None


def wake():
    """Stamp the wake mark (the time, this process and its kick's number: unique a kick): a running Connect's pause ends at its next look at it. A mark
    that can't be written is no error — the 2-minute look still comes."""
    import time
    path = wake_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:     # a look that reads it half-written wakes once more: harmless
            f.write(f"{time.time_ns()}-{os.getpid()}-{next(_STAMPS)}")
    except OSError:
        pass


def command():
    """`surasura-cli connect`: the command-line program beside this one when frozen (`Surasura.exe` and
    `surasura-cli.exe` ship side by side), else `python -m app.cli`."""
    from app.path_utils import is_frozen, program_beside
    args = ["connect"]
    if is_frozen():
        return [program_beside("surasura-cli")] + args
    return [sys.executable, "-m", "app.cli"] + args


def kick(settings):
    """Start Connect if it should run -> the started process (a `subprocess.Popen`), or None. 3.0 (P3.3 C1): D29's
    switch (`logic.automation`) off starts nothing, as Connect's own switch off doesn't — the one gate,
    `settings_manager.connect_on` (P4.1 row 4.1.1)."""
    from app import settings_manager
    if not settings_manager.connect_on(settings):
        return None
    if os.environ.get("SURASURA_TEST_ROOT") and os.environ.get("SURASURA_CONNECT_KICK") != "1":
        return None
    from app import library_store
    if library_store.update_staged(looks=library_store.PROBE_LOOKS):
        return None
    if running():
        wake()                  # it reads the ask, the placement or the setting at its next look, within seconds
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
