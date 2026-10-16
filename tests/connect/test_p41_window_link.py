"""The window's link to Connect (P4.1 row 4.1.6, `app/connect/window_link.py`): after the window's change — a move into
the top 20, an ask for mining — one look, and one kick for what Connect hasn't read (the Tk row's P3.1 rule, moved
here; `status_row._maybe_kick` calls it).

What a wrong answer would cost: no kick, and an episode placed in the top 20 or a *Mine now* gets no cards until the
next start; a kick at every change starts a process each time; a kick while Connect is off or the automation is off
starts unattended Anki work the user turned off (D29); a refused kick used up leaves the change unread. Real
subtitles in a real store and a real ledger under the test's root; the kick itself is stood in for (no process).
"""
import subprocess
import sys

from app.connect import inbox, library, window_link
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

ON = {"connect_enabled": True}


class Kicks:
    def __init__(self):
        self.calls, self.refuse = [], False

    def __call__(self, settings):
        self.calls.append(dict(settings))
        return None if self.refuse else object()      # a started kick is its process


def _library():
    """The suite's real files, a top 2, Connect's first look made (its placement reader and asks watermark)."""
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
    with c.store() as s, Ledger() as ledger:
        inbox.consume(s, "ja", ledger)


def _link(kicks, settings=ON, running=False, **kw):
    return window_link.Link("ja", lambda: dict(settings), kick=kicks, running=lambda: running, **kw)


def _move_to_top():
    with c.store() as s:
        ids = s.ids("now")
        library.place(s, ids[-1], "now", before_id=ids[0], source="user")


def test_a_move_into_the_top_20_kicks_once_and_the_same_event_again_none():
    _library()
    kicks = Kicks()
    link = _link(kicks)
    assert link.after_change() == window_link.NOTHING and kicks.calls == []
    _move_to_top()
    assert link.after_change() == window_link.KICKED
    assert link.after_change() == window_link.NOTHING, "the same event: no second process"
    assert len(kicks.calls) == 1
    _move_to_top()
    assert link.after_change() == window_link.KICKED, "a newer event: one more"
    assert len(kicks.calls) == 2


def test_connect_running_is_never_kicked():
    """Running, Connect reads the log and the asks again before it exits."""
    _library()
    kicks = Kicks()
    _move_to_top()
    assert _link(kicks, running=True).after_change() == window_link.RUNNING
    assert _link(kicks).after_change(running=True) == window_link.RUNNING      # the Tk row's stamp says so
    assert kicks.calls == []


def test_an_ask_kicks_once_against_the_real_store():
    _library()
    kicks = Kicks()
    link = _link(kicks)
    with c.store() as s:
        below = s.ids("now")[-1]
        s.ask_mining([below])                          # *Mine this*
    newest = window_link.unread("ja")
    assert newest is not None and newest[0] is None and newest[1], "an ask, no placement"
    assert link.after_change() == window_link.KICKED
    assert link.after_change() == window_link.NOTHING
    with c.store() as s, Ledger() as ledger:
        assert inbox.consume(s, "ja", ledger)["asked"] == [below]
    assert window_link.unread("ja") is None, "taken by the inbox: nothing unread"
    assert len(kicks.calls) == 1


def test_off_or_automation_off_kicks_nothing():
    _library()
    kicks = Kicks()
    _move_to_top()
    with c.store() as s:
        s.ask_mining([s.ids("now")[-1]])
    assert _link(kicks, settings={"connect_enabled": False}).after_change() == window_link.OFF
    assert _link(kicks, settings={"connect_enabled": True, "logic": {"automation": False}}).after_change() \
        == window_link.OFF, "D29: the automation off starts nothing"
    assert kicks.calls == []


def test_a_refused_kick_is_tried_again_at_the_next_change():
    """A kick refused (an update staged, Connect starting) uses nothing up."""
    _library()
    kicks = Kicks()
    link = _link(kicks)
    _move_to_top()
    kicks.refuse = True
    assert link.after_change() == window_link.REFUSED
    kicks.refuse = False
    assert link.after_change() == window_link.KICKED
    assert link.after_change() == window_link.NOTHING
    assert len(kicks.calls) == 2


def test_no_library_or_no_reader_is_nothing_unread():
    assert window_link.unread("ja") is None, "no store at all"
    c.library()
    assert window_link.unread("ja") is None, "Connect never switched on for this library"
    with c.store() as s:
        s.ask_mining([s.ids("now")[-1]])
    assert window_link.unread("ja") is None, "no ledger yet: its first look sets the watermark past every ask"


def test_the_language_is_read_when_the_change_is_looked_at():
    """The Tk row's rule (adversary P3.1 #6): each language numbers its own log — Japanese's event 7 and Chinese's
    event 7 are two placements."""
    kicks = Kicks()
    language = ["ja"]
    link = window_link.Link(lambda: language[0], lambda: dict(ON), kick=kicks, unread=lambda lang: 7,
                            running=lambda: False)
    assert link.after_change() == window_link.KICKED
    language[0] = "zh"
    assert link.after_change() == window_link.KICKED
    assert link.after_change() == window_link.NOTHING
    assert len(kicks.calls) == 2


def test_the_link_imports_neither_tk_nor_qt():
    """Qt- and Tk-free (the Qt window and the Tk row both hold one; `app/connect/` stays light)."""
    code = ("import sys; import app.connect.window_link; "
            "bad = [m for m in ('tkinter', 'PyQt6', 'pandas') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=h.PROJECT_ROOT, env=h.child_env(), capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
