"""The window's idle, for the background threads of the window's process (Up next 2, Mado-UN 2026-11-07).

Python's lock changes hands every millisecond (`shell.prepare_process`): a worker thread that works while the window's
thread has events to handle takes turns with it, and the window's stretch — the press's paint, the save's view, a clock
frame — runs twice as long (Alt+↑ at 20,000 files: 7 ms of the window's own work stretched to 26 ms by the writer's
and the reader's threads). So the heavy background steps of the window's process start only while the window is idle:
the window says when it wakes and when it goes back to wait (the event dispatcher's *awake* / *aboutToBlock*, wired
by `app/qt/shell.py`), and a worker waits at the start of a step (`wait()`) while the window is awake — at most
`CAP_S`, so a window that never rests never stops the work. Without a window (the command line, the tests' services)
the window is always idle: nothing waits. Qt-free.

The hand-over has one owner, here: the window's own (awake / at rest), and finer ones held while something runs
(`hold` / `let_go`) — the finest in force wins, and the last one let go puts back the window's own, else what was set
before the first (someone's own setting since stays theirs). A save holds `SAVE_SWITCH_S` while it holds the store's
write lock (F13's leftover, Kura-F13 2026-11-12: a save gives the lock up at each of its ~70 SQLite steps and the
commit's ring, and waited for it back a whole interval each time a busy thread ran Python — a look's pass over 20,000
origins made a ~3 ms move save in 0.1–0.5 s); a re-order host in the window's own process holds 1 ms while it lives
(`replan_preview`). Under 1 ms two busy threads take turns at every step (Mado-SP: 3.5× as long), so a save holds it
only while it holds the write lock — never while it waits for it, nor for a whole look: a window's save lasts
milliseconds; the long writes under the lock (the store's reset, a migration's or Repair's rebuild, a checkpoint) run
in the helper or once, with no other busy thread to take turns with.
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
_holds = []                     # finer hand-overs held while something runs (`hold`): a save's, a re-order host's
_handed = {"before": None, "set": None}   # (no window wired) the hand-over under the holds, and the last one set here
_SWITCH_LOCK = threading.Lock() # the hand-over is set by one at a time: the window's busy / rest, a hold, a let-go
# The awake hand-over is for a stretch's few milliseconds (a press, a save's view: Mado-SP's 7–26 ms). A stretch that
# goes on while a page is built in slices with no rest between them (`slice_ran`: Settings, ~135 turns of the loop) keeps
# the at-rest one from LONG_S on until the window rests: under 1 ms every waiting thread spins on Windows, and with the
# start's ten busy workers Settings took 21 s to build instead of 1.3 s (a 2,500-file library; the window's own share of
# Python's lock fell to about 1 %). Only then (OPEN-GAP, 2026-11-25): the start's own first stretch (20,000 files: ~0.9 s
# of the rows' first paint, Goal's dock, the level's pop-up) handed over as at rest from 0.1 s on kept the window's
# input 0.6–0.7 s late instead of 0.2 s (each of its events waited for a busy worker's whole millisecond)
LONG_S = 0.1
_long = [False]                 # this stretch outlasted LONG_S and ran a slice: at rest till the window rests
_sliced = [None]                # when a page built in slices last ran one (`slice_ran`; perf_counter)


def set_switch(awake, at_rest):
    """(The window's process, `shell.wire_idle`.) While the window is awake Python's lock changes hands every `awake`
    seconds — a stretch that runs a page's slices (`slice_ran`) for `LONG_S` at most, any other till it rests —, and
    every `at_rest` once it goes back to wait or that stretch goes on; (None, None): never changed here (Mado-SP)."""
    _switch[0], _switch[1] = awake, at_rest


def busy():
    """(The window's thread, at every turn of its loop: the dispatcher's *awake*.) It woke: it has events to handle —
    and, in the window's process, the lock comes back to it at once from a busy worker (`set_switch`); a stretch older
    than `LONG_S` that has run a page's slices since it woke (`slice_ran`) hands the lock over as at rest again (one
    clock read a turn, only then)."""
    if _idle.is_set():
        _woke[0] = time.perf_counter()
        with _SWITCH_LOCK:
            _idle.clear()
            _long[0] = False
            if _switch[0] is not None:
                _hand_over()
    elif (not _long[0] and _sliced[0] is not None and _sliced[0] >= _woke[0] and _switch[0] is not None
          and time.perf_counter() - _woke[0] > LONG_S):
        with _SWITCH_LOCK:
            if not _idle.is_set():
                _long[0] = True
                _hand_over()


def slice_ran():
    """(The window's thread, at each slice of a page built in slices with no rest between them: Settings' build, B4.)
    A stretch that has run one since it woke hands the lock over as at rest once it is older than `LONG_S` (`busy`);
    one without keeps the fine hand-over till it rests (the start's own first stretch). Nothing to end: a build that
    stops, however it stops, runs no more slices, and the next stretch is a press's again."""
    _sliced[0] = time.perf_counter()


def rest():
    """(The window's thread.) It goes back to wait: the background may work, the lock handed over as before (a hold
    still in force keeps its finer one, `hold`)."""
    with _SWITCH_LOCK:
        was = _idle.is_set()
        _idle.set()
        _long[0] = False
        if not was and _switch[1] is not None:
            _hand_over()


def hold(interval):
    """(Any thread, while something runs: a save under the store's write lock, `Store._writing`.) Python's lock changes
    hands every `interval` at most until it is let go (`let_go`, once per hold); a finer one in force stays."""
    with _SWITCH_LOCK:
        _holds.append(interval)
        _hand_over()


def let_go(interval):
    """(The holder.) Its hold ends; the last one's end puts back the window's own hand-over (awake or at rest, as its
    busy / rest would), else the one before the first hold, or someone's own set since."""
    with _SWITCH_LOCK:
        if interval in _holds:
            _holds.remove(interval)
            _hand_over()


def _hand_over():
    """(Under `_SWITCH_LOCK`.) The finest of the window's own (else the one in force before the holds) and the holds."""
    now = sys.getswitchinterval()
    own = _switch[1] if _idle.is_set() or _long[0] else _switch[0]
    if own is not None:
        _handed["before"] = own                     # (the window unwired under a hold falls back to its last own)
    else:
        if _handed["before"] is None or _handed["set"] is None or now != _handed["set"]:
            _handed["before"] = now                 # (none of ours in force, or someone set their own since: theirs)
        own = _handed["before"]
    want = min([own, *_holds])
    if want != now:
        sys.setswitchinterval(want)
    _handed["set"] = want if _holds else None


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
