"""The PROGRESS reader (W1.3; the window's spec 04 §4.2, §4.4 gap 8): what Generate's child prints, read as it comes.

The analyzer, given `--progress-json`, prints P0.3's lines on stdout between its own text lines (P0.3 02 §2):
`{"type":"progress","step":…,"done":…,"total":…}` at each step (*Reading your files*, *Counting words*, *Picking
sentences*, *Writing your list*, *Writing the journey*), then one `{"type":"result",…}` or `{"type":"error",…}`, last.
The command line's `generate --progress` prints the same lines.

`parse(line)` tells them apart; `Coalescer` hands its listener at most one progress update per `interval` (100 ms) — a
first update at once, the newest of a burst once the interval is up (a timer, so a quiet stretch never hides the last
step), and the result or error at once, after any update still held. Text lines go to their own listener as they come
(the log). `read(stream, …)` runs it over a child's stdout on the calling thread (a reader thread's).
"""
import json
import threading
import time
from collections import namedtuple

Update = namedtuple("Update", "step done total")


def parse(line):
    """One line of the child's stdout -> ("progress", Update) · ("result", dict) · ("error", dict) · ("text", str)."""
    text = line.rstrip("\r\n")
    if text.startswith("{\"type\""):
        try:
            record = json.loads(text)
        except ValueError:
            return ("text", text)
        kind = record.get("type")
        if kind == "progress":
            return ("progress", Update(record.get("step"), record.get("done"), record.get("total")))
        if kind in ("result", "error"):
            return (kind, record)
    return ("text", text)


class Coalescer:
    """`feed(line)` each line; `on_update(Update)` at most once per `interval`, `on_final(kind, record)` once,
    `on_text(str)` per text line. Callbacks run on the feeding thread, or on the coalescer's timer for a held update."""

    def __init__(self, on_update, on_final=None, on_text=None, interval=0.1, clock=time.monotonic):
        self.on_update = on_update
        self.on_final = on_final
        self.on_text = on_text
        self.interval = interval
        self.clock = clock
        self._lock = threading.Lock()
        self._last_sent = None          # when the last update went out
        self._held = None               # the newest update not yet sent
        self._timer = None
        self._ended = False
        self.final = None               # (kind, record) once it came

    def feed(self, line):
        kind, value = parse(line)
        if kind == "text":
            if self.on_text is not None and value:
                self.on_text(value)
        elif kind == "progress":
            self._progress(value)
        else:
            self.end(kind, value)

    def _progress(self, update):
        send = None
        with self._lock:
            if self._ended:
                return
            now = self.clock()
            if self._last_sent is None or now - self._last_sent >= self.interval:
                self._last_sent, self._held, send = now, None, update
            else:
                self._held = update
                if self._timer is None:
                    self._timer = threading.Timer(self.interval - (now - self._last_sent), self._release)
                    self._timer.daemon = True
                    self._timer.start()
        if send is not None:
            self.on_update(send)

    def _release(self):
        with self._lock:
            self._timer = None
            held, self._held = self._held, None
            if held is None or self._ended:
                return
            self._last_sent = self.clock()
        self.on_update(held)

    def end(self, kind=None, record=None):
        """The stream's end (or its result / error line): any held update first, then the final line once."""
        with self._lock:
            if self._ended:
                return
            self._ended = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            held, self._held = self._held, None
            if kind is not None:
                self.final = (kind, record)
        if held is not None:
            self.on_update(held)
        if kind is not None and self.on_final is not None:
            self.on_final(kind, record)


def read(stream, coalescer):
    """Feed every line of `stream` (a child's text-mode stdout) to `coalescer`, then end it. Blocks: a reader
    thread's call."""
    try:
        for line in stream:
            coalescer.feed(line)
    finally:
        coalescer.end()
