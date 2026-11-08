"""The window's idle, for the background threads of the window's process (Up next 2, Mado-UN 2026-11-07).

Python's lock changes hands every millisecond (`shell.prepare_process`): a worker thread that works while the window's
thread has events to handle takes turns with it, and the window's stretch — the press's paint, the save's view, a clock
frame — runs twice as long (Alt+↑ at 20,000 files: 7 ms of the window's own work stretched to 26 ms by the writer's
and the reader's threads). So the heavy background steps of the window's process start only while the window is idle:
the window says when it wakes and when it goes back to wait (the event dispatcher's *awake* / *aboutToBlock*, wired
by `app/qt/shell.py`), and a worker waits at the start of a step (`wait()`) while the window is awake — at most
`CAP_S`, so a window that never rests never stops the work. Without a window (the command line, the tests' services)
the window is always idle: nothing waits. Qt-free.
"""
import threading

CAP_S = 0.05                    # a worker waits for the window's idle this long at most, each step

_idle = threading.Event()
_idle.set()


def busy():
    """(The window's thread.) It woke: it has events to handle."""
    _idle.clear()


def rest():
    """(The window's thread.) It goes back to wait: the background may work."""
    _idle.set()


def wait(cap=None):
    """(A worker, at the start of a step.) Until the window is idle, `cap` seconds (`CAP_S`) at most. -> whether it
    is."""
    return _idle.wait(CAP_S if cap is None else cap)


def idle():
    return _idle.is_set()
