"""Reading the command line's events file (`<local data>/logs/cli-events.jsonl`, P0.3 02 §4) — for a window.

Every `error` a surasura-cli call answers is also appended there (`contract._record_event`, under the `cli-events`
lock; the newest 200 kept). A window, while open, shows the newest failure it hasn't shown yet in its bottom bar
(✅ G0.3-1: "if the GUI is up it should not force quit the GUI, just should show the error down below and write to
logs"). This module only reads: `Reader.new()` returns the events appended since its last look. Tk-free, so today's
dashboard and 3.0's window (W1.3) read it alike; call it off the window's thread, or after a cheap `changed()`.
"""
import json
import os

# What a window shows: a failure (exit 1), a question for the user (exit 4), and the two exit-2 answers only a person
# can fix (another version's word index; a language not set up). A wrong command, busy or an update staged are the
# caller's to handle: Connect retries them, and showing each would flood the bar.
SHOWN_EXITS = frozenset({1, 4})
SHOWN_CODES = frozenset({"version-skew", "not-set-up"})


def path():
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "logs", "cli-events.jsonl")


def plain(event):
    """One line for the bottom bar."""
    verb = event.get("verb") or "?"
    return f"Command line ({verb}): {event.get('message') or event.get('code') or 'it failed'} — details in its log."


class Reader:
    """The events appended since the last look. Starts at the file's end (`from_start=False`): a window shows what
    fails while it is open, not the history. The file is cut back to its newest lines now and then; a cut is seen
    by the size going down, and only events newer than the last one returned come back."""

    def __init__(self, from_start=False, events_path=None):
        self.path = events_path or path()
        self.offset = 0
        self.last = None            # the time of the newest event returned (read again after a cut)
        self.stat = None
        if not from_start:
            try:
                self.offset = os.path.getsize(self.path)
            except OSError:
                pass
            self.stat = self._stat()

    def _stat(self):
        try:
            st = os.stat(self.path)
            return st.st_size, st.st_mtime_ns
        except OSError:
            return None

    def changed(self):
        """A stat: has the file changed since the last look? Microseconds; safe on a window's thread."""
        return self._stat() != self.stat

    def new(self):
        """The events appended since the last look, oldest first (a half-written last line waits for the next)."""
        self.stat = self._stat()
        size = self.stat[0] if self.stat else 0
        rewound = size < self.offset
        if rewound:
            self.offset = 0                         # cut back to its newest lines: read it again, keep only newer
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except OSError:
            return []
        complete = chunk[:chunk.rfind(b"\n") + 1]
        self.offset += len(complete)
        out = []
        for line in complete.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if rewound and self.last is not None and str(event.get("time")) <= self.last:
                continue
            out.append(event)
        if out:
            self.last = max(str(e.get("time")) for e in out)
        return out

    def newest_to_show(self):
        """The newest new event a window shows (`SHOWN_EXITS`, `SHOWN_CODES`), or None."""
        shown = [e for e in self.new() if e.get("exit") in SHOWN_EXITS or e.get("code") in SHOWN_CODES]
        return shown[-1] if shown else None
