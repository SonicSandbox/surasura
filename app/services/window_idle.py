"""The window's idle, for the background threads of the window's process (Up next 2, Mado-UN 2026-11-07).

Python's lock changes hands every millisecond (`shell.prepare_process`): a worker thread that works while the window's
thread has events to handle takes turns with it, and the window's stretch — the press's paint, the save's view, a clock
frame — runs twice as long (Alt+↑ at 20,000 files: 7 ms of the window's own work stretched to 26 ms by the writer's
and the reader's threads). So the heavy background steps of the window's process start only while the window is idle:
the window says when it wakes and when it goes back to wait (the event dispatcher's *awake* / *aboutToBlock*, wired
by `app/qt/shell.py`), and a worker waits at the start of a step (`wait()`) while the window is awake — at most
`CAP_S`, so a window that never rests never stops the work. Without a window (the command line, the tests' services)
the window is always idle: nothing waits. Qt-free.

A save holds Python's lock at once too (F13's leftover, Kura-F13 2026-11-12): a store save gives the lock up at each of
its ~70 SQLite steps and waited for it back a whole switch interval each time a busy thread ran Python — a look's pass
over 20,000 origins made a ~3 ms move save in 0.1–0.5 s. While a save holds the store's write lock
(`library_store.Store._writing`: `save_began` / `save_ended`, in any process) the lock comes back to it at once; the
last save's end puts back the window's own hand-over, or what was set before. Only for the save's few milliseconds:
under 1 ms two busy threads take turns at every step (Mado-SP: 3.5× as long), so never for a whole look.
"""
import sys
import threading
import time

CAP_S = 0.05                    # a worker waits for the window's idle this long at most, each step
SPAN_S = 0.02                   # inside a step (`pause`): a window stretch younger than this is waited out, no older

_idle = threading.Event()
_idle.set()
_woke = [0.0]                   # when the window last woke from rest (perf_counter)
_switch = [None, None]          # Python's lock hand-over while the window is awake, and at rest (`set_switch`)
SAVE_SWITCH_S = 0.00025         # while a save holds the store's write lock: the lock comes back to it at once
_saves = {"n": 0, "was": None, "rested": False}   # saves under way here; the hand-over before the first, when it
                                                # was lowered; the window rested meanwhile (its rest's setting waits)
_SWITCH_LOCK = threading.Lock() # the hand-over is set by one at a time: the window's busy / rest, a save's start / end


def set_switch(awake, at_rest):
    """(The window's process, `shell.wire_idle`.) While the window is awake Python's lock changes hands every `awake`
    seconds, and every `at_rest` once it goes back to wait; (None, None): never changed here (Mado-SP)."""
    _switch[0], _switch[1] = awake, at_rest


def busy():
    """(The window's thread.) It woke: it has events to handle — and, in the window's process, the lock comes back to it
    at once from a busy worker (`set_switch`)."""
    if _idle.is_set():
        _woke[0] = time.perf_counter()
        with _SWITCH_LOCK:
            _idle.clear()
            if _switch[0] is not None:
                sys.setswitchinterval(_switch[0])


def rest():
    """(The window's thread.) It goes back to wait: the background may work, the lock handed over as before — once no
    save is under way (`save_ended` puts it back then)."""
    with _SWITCH_LOCK:
        was = _idle.is_set()
        _idle.set()
        if not was and _switch[1] is not None:
            if _saves["n"]:
                _saves["rested"] = True
            else:
                sys.setswitchinterval(_switch[1])


def save_began():
    """(Any thread: a store save taking the write lock, `Store._writing`.) Until the last save ends, Python's lock
    comes back to a save at once from a busy thread (`SAVE_SWITCH_S`); a finer hand-over already set stays."""
    with _SWITCH_LOCK:
        if not _saves["n"]:
            was = sys.getswitchinterval()
            if was > SAVE_SWITCH_S:
                sys.setswitchinterval(SAVE_SWITCH_S)
                _saves["was"] = was
        _saves["n"] += 1


def save_ended():
    """(The save's thread, its write lock let go.) The last one puts back what it lowered, or a rest it held back: in
    the window's process the window's own hand-over (awake or at rest, `set_switch`, as its busy / rest would), else
    the one before the first save, unless someone set their own since."""
    with _SWITCH_LOCK:
        if _saves["n"] <= 0:
            return
        _saves["n"] -= 1
        if _saves["n"]:
            return
        was, rested = _saves["was"], _saves["rested"]
        _saves["was"], _saves["rested"] = None, False
        own = _switch[1] if _idle.is_set() else _switch[0]
        if own is not None:
            if was is not None or rested:
                sys.setswitchinterval(own)
        elif was is not None and sys.getswitchinterval() == SAVE_SWITCH_S:
            sys.setswitchinterval(was)


def wait(cap=None):
    """(A worker, at the start of a step.) Until the window is idle, `cap` seconds (`CAP_S`) at most. -> whether it
    is."""
    return _idle.wait(CAP_S if cap is None else cap)


def pause():
    """(A worker, between two short pieces of a long step: a view's rows, Goal's tiles.) While the window's stretch is
    young, wait for it to rest — `SPAN_S` after it woke at most, so a window that stays awake never holds the step back
    longer than one stretch; a window at rest costs one look (Up next 3: the reader's 20,000-file build took turns at
    Python's lock with the clock frames and the save's view)."""
    if _idle.is_set() or threading.current_thread() is threading.main_thread():
        return                                      # (the window's own thread never waits for itself)
    left = _woke[0] + SPAN_S - time.perf_counter()
    if left > 0:
        _idle.wait(left)


def idle():
    return _idle.is_set()
