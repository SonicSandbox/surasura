"""A job's *Stop* reaches every program Connect waits on (laptop round 9 #56, row 56).

Sonic pressed the episode while Connect checked its timing and "it just sits there": the runner asked for a press only
between its steps, and tsubasa's check, Anki Miner's look-ups and its run were each waited for whole. One rule now:
**every program Connect waits on during a job is waited for in slices of a second, asking the job's Stop each slice.**

- `watching(check)`: the job's check (`runner._stop_pressed` on its ledger and id), installed once a job by the runner
  for this thread; `pressed()` asks it — True only with one installed that says so (a check that raises is no press,
  logged: the job goes on).
- `wait(proc, timeout, …)`: the one process wait. A look-up (`look_up`: tsubasa's dry run, Anki Miner's read-only
  `--api` verbs) is ended at a press (`end`: the program and every process it started) and `Stopped` raised: nothing
  of that step is written, and the job stops before it. Anki Miner's run is never ended here: it reads its cancel file
  (`anki_miner.cancel`, through `on_poll`), every card it made kept whole.
- `end(proc)`: the one process-ender for Connect's programs (a timeout, a press).

Standard library only; no Tk, no Qt.
"""
import contextlib
import logging
import subprocess
import sys
import threading
import time

log = logging.getLogger("surasura-cli")

POLL_S = 1.0                    # a look-up's slice: a press is acted on within about this long (row 56)
CREATE_NO_WINDOW = 0x08000000

_here = threading.local()


class Stopped(Exception):
    """The job's *Stop* reached a program Connect was waiting on: the program was ended, its step not done."""


@contextlib.contextmanager
def watching(check):
    """While inside, `pressed()` on this thread asks `check()` (the previous check back on the way out)."""
    before = getattr(_here, "check", None)
    _here.check = check
    try:
        yield
    finally:
        _here.check = before


def pressed():
    """Has *Stop* been pressed on the job this thread works for? False with no check installed, or one that fails
    (logged: the job goes on)."""
    check = getattr(_here, "check", None)
    if check is None:
        return False
    try:
        return bool(check())
    except Exception:
        log.warning("Connect couldn't look for a Stop", exc_info=True)
        return False


def end(proc):
    """End a program Connect started, with every process it started (Anki Miner's ffmpeg children too), and collect
    it."""
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                           creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
    proc.kill()
    proc.communicate()


_end = end                      # `wait`'s default (its own `end` names the caller's)


def wait(proc, timeout, on_poll=None, end=None, look_up=False, every=None):
    """`proc.communicate()`'s (stdout, stderr) once it ends, waiting at most `timeout` s (TimeoutExpired past it; the
    caller ends it). With `on_poll` or `look_up`, in slices of `every` s (default POLL_S): each slice calls `on_poll()`
    (its failure never stops the wait) and, for a look-up, asks `pressed()` — True: `end(proc)` (default: this
    module's `end`) and `Stopped`. Retrying `communicate` after its TimeoutExpired loses no output (the subprocess
    docs)."""
    if on_poll is None and not look_up:
        return proc.communicate(timeout=timeout)
    every = POLL_S if every is None else every
    deadline = time.monotonic() + timeout
    while True:
        try:
            return proc.communicate(timeout=max(0.0, min(every, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise
        if on_poll is not None:
            try:
                on_poll()
            except Exception:
                pass
        if look_up and pressed():
            (end or _end)(proc)
            raise Stopped()
