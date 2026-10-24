"""One press's life (round 8 row 45; the scope `row45-54-scope.md` §3): every control that starts work reacts in the
frame of the press, then shows it waiting or running, then done or why it failed. Qt-free; `app/qt/press.py` paints
it on the control.

- **The states** are the job registry's words (`jobs.QUEUED` · `WAITING` · `RUNNING` · `CANCELLING` · `DONE` ·
  `FAILED`) and `IDLE`, so a press and a job say the same thing. `press()` takes idle to queued; a second press while
  one is live does nothing (the first stays painted). `words` is what the state says: the reason it waits, the step it
  runs, the line it ended with, why it failed.
- **Done goes back to idle** after `LINGER_S`; **failed stays** until the next press.
- **`Presses`**: a window's presses by key (an action's name with what it acts on), so the bar knows whether any is
  live. Used on the window's thread only: a worker's report reaches a press through the window's queue.
"""
import time

from app.services.jobs import CANCELLING, DONE, FAILED, LIVE, QUEUED, RUNNING, WAITING

IDLE = "idle"
LINGER_S = 2.0              # done, then idle again (PROVISIONAL)


class Press:
    def __init__(self, key, clock=time.monotonic):
        self.key = key
        self._clock = clock
        self._state, self.words, self._ended = IDLE, None, None
        self._subscribers = []

    @property
    def state(self):
        if self._state == DONE and self._clock() - self._ended >= LINGER_S:
            self._state, self.words = IDLE, None
        return self._state

    def live(self):
        return self.state in LIVE

    def press(self):
        """Idle (or ended) -> queued: True. Live already: False, and nothing changes."""
        if self.live():
            return False
        self._set(QUEUED)
        return True

    def wait(self, why):
        self._move(WAITING, why)

    def run(self, step=None):
        self._move(RUNNING, step)

    def stopping(self):
        self._move(CANCELLING, None)

    def done(self, line=None):
        self._move(DONE, line)

    def failed(self, why):
        self._move(FAILED, why)

    def release(self):
        """Done, and its control stays (a card's "couldn't" answer): idle now, so a press at once asks again."""
        if self._state == DONE:
            self._set(IDLE)

    def subscribe(self, callback):
        """`callback(press)` after every change."""
        self._subscribers.append(callback)

    def _move(self, state, words):
        if self.live():                     # an answer after the end (or before any press) moves nothing
            self._set(state, words)

    def _set(self, state, words=None):
        self._state, self.words = state, words
        self._ended = self._clock() if state in (DONE, FAILED) else None
        for callback in list(self._subscribers):
            callback(self)


class Presses:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._by_key = {}
        self._subscribers = []

    def get(self, key):
        """The press for `key`, made the first time it is asked for."""
        p = self._by_key.get(key)
        if p is None:
            p = self._by_key[key] = Press(key, self._clock)
            p.subscribe(self._changed)
        return p

    def find(self, key):
        """The press for `key`, or None when none was ever asked for (nothing made)."""
        return self._by_key.get(key)

    def forget(self, key):
        """`key`'s press, ended, out of the table (finish-pending FP-A7: a key made once per command, never asked
        again). A live one stays."""
        p = self._by_key.get(key)
        if p is not None and not p.live():
            del self._by_key[key]

    def any_live(self):
        return any(p.live() for p in self._by_key.values())

    def showing(self):
        """The presses live now and those that failed (the phase strip lights their circles before any job exists, and
        shows a failed one as its circle's failure: PS-A1)."""
        return tuple(p for p in self._by_key.values() if p.state in LIVE or p.state == FAILED)

    def subscribe(self, callback):
        """`callback(press)` after any press changed."""
        self._subscribers.append(callback)

    def _changed(self, press):
        for callback in list(self._subscribers):
            callback(press)
