"""The Connect window's gaps the P3.1 mutant pass found (2026-10-11): each test pins one rule a planted bug got past.

What a wrong answer would cost: a window that waits on the wrong lock (an undo that waits while Connect merely runs, or
gives up while Anki Miner writes); a badge on the dashboard that keeps counting what the window just showed; a
question that names "other batches" of cards no episode made, or asks to remove cards when none can go; a put-back
question that counts the cards already back; an undo that gives up after a second while Anki Miner writes (the
batch stays in Anki); an undo begun while an update waits to install; a failed Dismiss whose button stays greyed.
Every Connect call is stood in for; real Japanese words."""
from tkinter import ttk

from app import updater
from app.connect import connect_window
from tests.connect.test_connect_window import (BUSY, PLAN, RECORD, Act, Clock, _bare, _press, _window,
                                               root)  # noqa: F401  (the fixture)
from tests.connect_tk_helpers import Pump, Tips, widgets


def test_the_writer_is_busy_only_while_ankis_write_lock_is_held(monkeypatch):
    # Connect running (its own lock) is not Anki being written to: only the anki-writer lock makes the undo wait
    from app import locks
    held = set()
    monkeypatch.setattr(locks, "in_use", lambda name, **k: name in held)
    monkeypatch.setattr(locks, "unopenable", lambda name: None)
    held.add("connect")
    assert connect_window.writer_busy() is False
    held.add("anki-writer")
    assert connect_window.writer_busy() is True


def test_what_the_window_marked_seen_makes_the_dashboards_badge_read_again(root):
    changes = []
    win, pump, _tips, _asked, seen, _d = _window(root, on_change=lambda: changes.append(1))
    assert pump.run(root, lambda: seen and changes)
    assert seen[0][0] == [11] and changes == [1], "marked seen, then the line and badge read again, once"


def test_batches_with_no_episode_are_never_called_one_episodes_batches(root):
    # Two batches whose item is unknown (None) are not "this episode's other batch"
    loose = dict(RECORD, undo=[
        {"job": 9, "item": None, "title": None, "kind": "mine", "made": 1, "at": "2026-10-11T08:00:00Z",
         "not_made": {}},
        {"job": 7, "item": None, "title": None, "kind": "mine", "made": 3, "at": "2026-10-09T08:00:00Z",
         "not_made": {}}])
    pump, asked = Pump(), []
    win = connect_window.show(root, "ja", Tips(), loose, act=Act(PLAN), settings=lambda: {"connect_enabled": True},
                              writer_busy=lambda: False, update_waits=lambda: False,
                              confirm=lambda t, x: (asked.append(x), False)[1], junban=True, post=pump.put)
    _press(win, "batch", 7, "Undo this batch")
    assert pump.run(root, lambda: asked)
    assert "other batch" not in asked[0] and connect_window.when("2026-10-11T08:00:00Z") not in asked[0]


def test_a_plan_with_nothing_to_delete_asks_nothing_and_says_why(root):
    act = Act(dict(PLAN, delete=0))
    win, pump, _tips, asked, _seen, _d = _window(root, act)
    _press(win, "batch", 7, "Undo this batch")
    note = win.notes[("batch", 7)]
    assert pump.run(root, lambda: note.cget("text").startswith("No card of this batch can go"))
    assert note.cget("text") == "No card of this batch can go: 一生懸命 (you've studied it)."
    assert asked == [], "no question: nothing would go"
    assert [c["confirm"] for c in act.calls] == [False], "the plan only: nothing written"
    assert str(win.buttons[("batch", 7, "Undo this batch")].cget("state")) == "normal"


def test_the_put_back_question_counts_only_the_cards_still_on_the_shelf(root):
    partly = dict(RECORD, shelf={"on_shelf": 2, "swap_ins": 0, "runs": [dict(RECORD["shelf"]["runs"][0], cards=3,
                                                                               back=1)]})
    pump, asked = Pump(), []
    win = connect_window.show(root, "ja", Tips(), partly, act=Act(), settings=lambda: {"connect_enabled": True},
                              writer_busy=lambda: False, update_waits=lambda: False,
                              confirm=lambda t, x: (asked.append(x), False)[1], junban=True, post=pump.put)
    _press(win, "shelf", "r-20261010", "Put back")
    assert asked and asked[0].startswith("Put 2 cards back"), "3 shelved, 1 already back: 2 to put back"
    texts = [w.cget("text") for w in widgets(win.tab_shelf, (ttk.Label,))]
    assert any("1 back" in t for t in texts)


def test_an_undo_refused_through_a_whole_anki_miner_batch_is_waited_out_and_returns_its_answer(monkeypatch):
    """A live program holds Anki's write lock for a whole Anki Miner batch (18–24 s; 30 s here): the act is refused
    30 times, a second apart, then answers. The undo waits through every refusal (well inside its 120 s wait) and
    returns the answer — never gives up early with the act's 'busy' words."""
    clock = Clock()
    monkeypatch.setattr(connect_window, "time", clock)
    calls = []

    def act(settings, language, **kw):
        calls.append(kw)
        if len(calls) <= 30:
            raise BUSY
        return {"say": "2 cards deleted."}

    w = _bare(act)
    assert w._write(None, job=7, confirm=True) == {"say": "2 cards deleted."}, "the wait returns the act's answer"
    assert len(calls) == 31, "thirty refusals, then the one call that answers"
    assert len(clock.sleeps) == 30 and all(s >= 1.0 for s in clock.sleeps), "a retry about a second apart"
    assert clock.now < connect_window.WAIT_FOR_WRITER_S, "the answer came well inside the whole wait"


def test_update_waits_follows_the_updater_when_an_update_is_held(monkeypatch):
    """An update that is holding its children makes the window wait: True is returned, not a truthy stand-in.
    The same call flips back to False as soon as the updater lets go, so the answer is live, not cached."""
    monkeypatch.setattr(updater, "children_held", lambda: True)
    assert connect_window.update_waits() is True

    monkeypatch.setattr(updater, "children_held", lambda: False)
    assert connect_window.update_waits() is False


def test_update_waits_is_false_when_the_updater_cannot_be_asked(monkeypatch):
    """If asking the updater raises, the window must not hang on a phantom update: False, never an exception."""
    def broken():
        raise RuntimeError("the updater's hold flag is unreadable")

    monkeypatch.setattr(updater, "children_held", broken)
    assert connect_window.update_waits() is False


def test_a_dismiss_that_fails_keeps_the_entry_listed_and_its_button_pressable(root):
    """The ledger refuses the dismiss: the entry stays, its note says "Couldn't dismiss it: …", and the Dismiss
    button is enabled again so it can be pressed a second time."""
    def refuse(need_id):
        raise OSError("the ledger is locked")

    pump = Pump()
    win = connect_window.show(root, "ja", Tips(), RECORD, act=Act(), settings=lambda: {"connect_enabled": True},
                              writer_busy=lambda: False, update_waits=lambda: False, confirm=lambda t, x: True,
                              junban=True, post=pump.put, mark_seen=lambda ids: None, dismiss=refuse)
    key = ("needs", 11, "Dismiss")
    win.buttons[key].invoke()

    # Wait for the failure to be drawn: the note is the last thing `dismiss`'s done() writes on the failure path.
    assert pump.run(root, lambda: win.notes[("needs", 11)].cget("text") == "Couldn't dismiss it: the ledger is locked")

    # Why: a disabled button after a failure is what the mutant leaves; the user can't press Dismiss again.
    assert str(win.buttons[key].cget("state")) != "disabled", "Dismiss is enabled again after a failed dismiss"

    # The entry is still on the list and the tab still counts it: the failure took nothing off.
    texts = [w.cget("text") for w in widgets(win.tab_needs, (ttk.Label,))]
    assert RECORD["needs"][0]["say"] in texts, "the entry stays listed"
    assert win.tabs.tab(0, "text") == "Needs you (1)", "the tab still counts the entry"
