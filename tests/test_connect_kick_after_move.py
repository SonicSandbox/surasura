"""A placement reaches Connect (P3.1 row 3.1.9). Measured first, by reading the code: a move into the top 20 in the
Content Manager writes the store's placement log, but nothing starts Connect for it — the dashboard's session look
(`_connect_session`) kicks only after a session's first sync (`anki_session.begin` answers only when a session starts),
so mid-session the episode waited for the next Surasura or Anki start. The fix: on the line's poll, when the stamp
moved and Connect isn't running, one read-only look at the log; an event Connect hasn't read → one kick.

What a wrong answer would cost: no kick, and a placed episode gets no cards until tomorrow; a kick at every 3 s poll
starts a process each time (one per new event); a kick with the preview off starts Connect in a 2.5 window. Real
subtitles in a real store under the test's root; the kick itself is stood in for."""
from tkinter import ttk

import pytest

from app.connect import status_row
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect_tk_helpers import Pump, Tips, tk_root


@pytest.fixture
def root():
    r = tk_root()
    try:
        yield r
    finally:
        r.destroy()


class Stage:
    def __init__(self):
        self.stamp_value = [1, 1, False, "2026-10-11"]
        self.newest = None
        self.on = True
        self.kicks = []

    def stamp(self, languages=None):
        return list(self.stamp_value)

    def read(self, languages=None):
        return {"languages": {languages[0]: {"line": "Up to date", "needs": [], "unseen": 0, "jobs": []}}}

    def moved(self, newest=None, running=False):
        """The library file moved (a placement), with the log's newest unread event."""
        self.stamp_value[0] += 1
        self.stamp_value[2] = running
        self.newest = newest


def _row(root, stage):
    pump = Pump()
    footer = ttk.Frame(root)
    footer.pack(side="bottom")
    row = status_row.StatusRow(root, lambda: "ja", Tips(), lambda: None, below=footer,
                               settings=lambda: {"connect_enabled": stage.on}, stamp=stage.stamp, read=stage.read,
                               kick=lambda s: stage.kicks.append(s.get("connect_enabled")),
                               unread=lambda lang: stage.newest, post=pump.put)

    def look():
        row.tick()
        assert pump.run(root, lambda: not row._looking and not pump.jobs)
    return look


def test_a_new_event_kicks_once(root):
    stage = Stage()
    look = _row(root, stage)
    look()
    assert stage.kicks == []
    stage.moved(newest=7)
    look()
    assert stage.kicks == [True]
    stage.moved(newest=7)           # something else moved the file; the same event still unread
    look()
    look()                          # and an unchanged stamp
    assert stage.kicks == [True], "one kick per new event"
    stage.moved(newest=8)
    look()
    assert stage.kicks == [True, True]


def test_no_kick_when_off_when_running_or_when_nothing_is_new(root):
    stage = Stage()
    look = _row(root, stage)
    stage.on = False
    stage.moved(newest=5)
    look()
    stage.on = True
    stage.moved(newest=6, running=True)       # Connect reads the log again before it exits
    look()
    stage.moved(newest=None)
    look()
    assert stage.kicks == []


def test_unread_reads_connects_watermark_in_the_real_store():
    """The look the kick rests on, against a real library: a placement after Connect's watermark is unread until
    Connect's inbox has read it; a library without Connect's reader (never switched on) is never unread."""
    from app.connect import inbox, library
    from app.connect.ledger import Ledger
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
    assert status_row.unread("ja") is None, "no reader yet: nothing for Connect"
    with c.store() as s:
        library.switch_on(s)
    assert status_row.unread("ja") is None
    with c.store() as s:
        library.place(s, s.ids("now")[-1], "now", source="user")      # the Content Manager's move into the top 2
    newest = status_row.unread("ja")
    assert isinstance(newest, int)
    with c.store() as s, Ledger() as ledger:
        inbox.consume(s, "ja", ledger)
    assert status_row.unread("ja") is None, "read by Connect: nothing new"
    assert status_row.unread("zh") is None, "no Chinese library"
