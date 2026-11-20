"""A child's stdout and stderr when the program that started it has gone (Haya-CL, 3.0.17).

The window reads its children's lines through a pipe — Generate's progress, a tool's log, the arrivals worker's
answers. When the window closes first, that pipe is closed: the child's next write fails (Windows: `OSError` 22, the
pipe's ERROR_NO_DATA; elsewhere `BrokenPipeError`; a closed stream: `ValueError`). Before 3.0.17 that error ended a
cancelled Generate with a traceback and Surasura.exe's Critical Error box (Sonic's laptop, 3.0.16). Now a write to a
parent that has gone goes nowhere, quietly: the child's own code decides what to do (`parent_gone`), and its exit
can't fail on the last flush either (Python turns a failed flush at exit into exit code 120).

`guard_std_streams()` once, at a child's start (app_entry.py for every Surasura.exe command; each script a window starts
from source; surasura-cli). Idempotent.
"""
import os
import sys

PARENT_GONE = (OSError, ValueError)        # BrokenPipeError is an OSError
_state = {"gone": False}


def parent_gone():
    """Has a write to this process's stdout failed: the program reading it has gone? (stderr's failing only goes
    quiet: it may be a log file, never the parent's channel.)"""
    return _state["gone"]


class _ToParent:
    """A stream to the parent that never raises for a parent that has gone: from the first failed write or flush on,
    everything goes to os.devnull (the old stream closed quietly, its unsent bytes dropped)."""

    def __init__(self, stream, tells=True):
        self._stream = stream
        self._tells = tells                 # a failure here is the parent gone (stdout's, the channel), or only quiet

    def write(self, text):
        try:
            return self._stream.write(text)
        except UnicodeError:                # a ValueError, but text this stream can't hold: no parent gone
            raise
        except PARENT_GONE:
            self._left()
            return len(text)

    def flush(self):
        try:
            self._stream.flush()
        except PARENT_GONE:
            self._left()

    def _left(self):
        if self._tells:
            _state["gone"] = True
        old, self._stream = self._stream, open(os.devnull, "w", encoding="utf-8")
        try:
            old.close()                     # its buffer's flush fails once more here, never at the process's exit
        except PARENT_GONE:
            pass

    def __getattr__(self, name):            # encoding, buffer, fileno, isatty, reconfigure …: the stream's own
        return getattr(self._stream, name)


def guarded(stream, tells=True):
    """`stream` as a `_ToParent` (None and an already guarded stream as they are); `tells`: its failure is
    `parent_gone()`'s."""
    if stream is None or isinstance(stream, _ToParent):
        return stream
    return _ToParent(stream, tells)


def guard_std_streams():
    """sys.stdout and sys.stderr guarded (`guarded`) for the rest of this process."""
    sys.stdout = guarded(sys.stdout)
    sys.stderr = guarded(sys.stderr, tells=False)
