"""The Connect window (P3.1 row 3.1.6; P1.5 05-surface U3; RUNBOOK-P2.5 *The status contract*): *Needs you*, the
batches with *Undo this batch*, the shelf with *Put back*, and the Logs box.

What a wrong answer would cost: an undo sent without the question deletes cards the user meant to keep; a cancelled
question that still writes is worse; an undo on the screen's thread freezes the window for the 18–24 s Anki Miner holds
Anki's write lock — and one that gives up at once says "busy" where it should have waited; *Put back* shown without
Junban fails on click; *Dismiss* that doesn't reach the ledger brings the entry back; a window Esc doesn't close traps
the keyboard. Every Connect call is stood in for (`undo.act`, `status`'s two writes), each recording its thread;
real Japanese words, synthetic titles."""
import threading
import tkinter as tk
from tkinter import ttk

import pytest

from app.cli.contract import CliError
from app.connect import connect_window
from tests.connect_tk_helpers import Pump, Tips, on_main, tk_root, widgets

RECORD = {
    "line": "Up to date · 3 cards made today", "state": "idle", "jobs": [], "unseen": 1, "made_today": 3,
    "needs": [
        {"id": 11, "kind": "error", "say": "Example Show - 05: Anki Miner stopped twice while making its cards.",
         "item": 4, "title": "Example Show - 05", "at": "2026-10-11T09:00:00Z", "seen_at": None},
        {"id": 12, "kind": "not-timed", "say": "Example Show - 06: its subtitle isn't timed to its video.",
         "item": 5, "title": "Example Show - 06", "at": "2026-10-10T09:00:00Z", "seen_at": "2026-10-10T10:00:00Z"}],
    "undo": [{"job": 7, "item": 4, "title": "Example Show - 05", "kind": "mine", "made": 3,
              "at": "2026-10-11T08:00:00Z", "not_made": {"not_found": 2, "no_definition": 1}}],
    "shelf": {"on_shelf": 2, "swap_ins": 1, "runs": [{"run": "r-20261010", "cards": 2, "back": 0,
                                                      "why": "the cap: 300 cards waiting", "at": "2026-10-10T07:00:00Z",
                                                      "words": ["一生懸命", "上層部"]}]},
}
PLAN = {"job": 7, "item": 4, "delete": 2, "gone": 1, "language": "ja", "confirm": False,
        "keep": [{"note": 31, "word": "一生懸命", "why": "you've studied it"}]}
DONE = dict(PLAN, confirm=True, deleted=2, freed=["上層部", "見切り発車"], placed_again=True, pending=False,
            say="2 cards deleted. Place the episode in your top 20 again to make its cards again. 1 you had deleted "
                "yourself stay deleted, and their words aren't made again.")


class Act:
    """`undo.act` stood in for: every call with its thread; answers in order (an exception is raised)."""

    def __init__(self, *answers, gate=None):
        self.answers, self.calls, self.gate = list(answers), [], gate

    def __call__(self, settings, language, job=None, shelf_run=None, confirm=False):
        self.calls.append({"language": language, "job": job, "shelf_run": shelf_run, "confirm": confirm,
                           "main": on_main()})
        if self.gate is not None and confirm:
            self.gate.wait(5)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def root():
    r = tk_root()
    try:
        yield r
    finally:
        r.destroy()


def _window(root, act=None, confirm=True, junban=True, **kw):
    pump, tips, asked, seen, dismissed = Pump(), Tips(), [], [], []
    win = connect_window.show(
        root, "ja", tips, RECORD, act=act or Act(), settings=lambda: {"connect_enabled": True},
        writer_busy=kw.pop("writer_busy", lambda: False),
        confirm=lambda title, text: (asked.append(text), confirm)[1], junban=junban, post=pump.put,
        mark_seen=lambda ids: seen.append((ids, on_main())), dismiss=lambda i: (dismissed.append((i, on_main())),
                                                                                  True)[1], **kw)
    return win, pump, tips, asked, seen, dismissed


def _press(win, *key):
    win.buttons[key].invoke()


def test_undo_asks_sonics_question_then_undoes_on_a_worker(root):
    act = Act(PLAN, DONE)
    win, pump, _tips, asked, _seen, _d = _window(root, act)
    _press(win, "batch", 7, "Undo this batch")
    note = win.notes[("batch", 7)]
    assert pump.run(root, lambda: note.cget("text").startswith("2 cards deleted"))
    assert [(c["job"], c["language"], c["confirm"], c["main"]) for c in act.calls] == \
        [(7, "ja", False, False), (7, "ja", True, False)], "the plan, then the undo — never on the Tk thread"
    text = asked[0]
    assert text.startswith("Remove all of this episode's Anki cards that aren't studied?")
    assert "2 cards go." in text and "一生懸命: you've studied it" in text
    assert "1 you had deleted yourself stay deleted." in text


def test_cancel_on_the_question_writes_nothing(root):
    act = Act(PLAN)
    win, pump, _tips, asked, _seen, _d = _window(root, act, confirm=False)
    _press(win, "batch", 7, "Undo this batch")
    assert pump.run(root, lambda: asked and str(win.buttons[("batch", 7, "Undo this batch")].cget("state")) == "normal")
    pump.run(root, timeout=0.2)
    assert [c["confirm"] for c in act.calls] == [False], "only the plan: nothing written"


def test_a_busy_anki_writer_shows_the_wait_then_the_result(root):
    gate = threading.Event()
    busy = CliError("busy", "Another program is writing to Anki. Try again in a moment.", lock="anki-writer")
    act = Act(PLAN, busy, DONE, gate=gate)
    win, pump, _tips, _asked, _seen, _d = _window(root, act, writer_busy=lambda: True)
    _press(win, "batch", 7, "Undo this batch")
    note = win.notes[("batch", 7)]
    assert pump.run(root, lambda: note.cget("text") == connect_window.WAITING), "the waiting state"
    gate.set()
    assert pump.run(root, lambda: note.cget("text").startswith("2 cards deleted")), "then the result"
    assert [c["confirm"] for c in act.calls] == [False, True, True], "it waited and tried again"


def test_an_error_is_said_in_its_plain_words(root):
    act = Act(CliError("anki-busy", "You're reviewing in Anki. Undo once you've finished."))
    win, pump, _tips, _asked, _seen, _d = _window(root, act)
    _press(win, "batch", 7, "Undo this batch")
    note = win.notes[("batch", 7)]
    assert pump.run(root, lambda: note.cget("text") == "You're reviewing in Anki. Undo once you've finished.")
    assert str(win.buttons[("batch", 7, "Undo this batch")].cget("state")) == "normal"


def test_put_back_calls_the_shelf_run_and_junban_absent_hides_it(root):
    act = Act({"language": "ja", "shelf": "r-20261010", "back": 2, "confirm": True})
    win, pump, _tips, asked, _seen, _d = _window(root, act)
    _press(win, "shelf", "r-20261010", "Put back")
    note = win.notes[("shelf", "r-20261010")]
    assert pump.run(root, lambda: note.cget("text") == "2 cards back in your new cards.")
    assert act.calls == [{"language": "ja", "job": None, "shelf_run": "r-20261010", "confirm": True, "main": False}]
    assert asked and asked[0].startswith("Put 2 cards back")
    win.win.destroy()

    win, _pump, _tips, _asked, _seen, _d = _window(root, Act(), junban=False)
    assert ("shelf", "r-20261010", "Put back") not in win.buttons
    texts = [w.cget("text") for w in widgets(win.tab_shelf, (ttk.Label,))]
    assert "Putting the shelf back needs Junban (順), which isn't installed." in texts
    assert any("一生懸命、上層部" in t for t in texts), "the run's words are still listed"


def test_needs_you_marks_whats_shown_seen_and_dismiss_reaches_status(root):
    win, pump, _tips, _asked, seen, dismissed = _window(root)
    assert pump.run(root, lambda: seen)
    assert seen == [([11], False)], "only the unseen one, on a worker"
    labels = {w.cget("text"): str(w.cget("style")) for w in widgets(win.tab_needs, (ttk.Label,))}
    assert labels[RECORD["needs"][1]["say"]] == "CW.Dim.TLabel", "a seen entry is dimmed"
    assert any(t.endswith("· SEEN") for t in labels)
    assert ("needs", 12, "Dismiss") in win.buttons and not [k for k in win.buttons if k[:2] == ("needs", 12)
                                                             and k[2] != "Dismiss"], "an untimed drop: no action"
    assert ("needs", 11, "How to check") in win.buttons
    _press(win, "needs", 11, "Dismiss")
    assert pump.run(root, lambda: dismissed)
    assert dismissed == [(11, False)]


def test_logs_buttons_run_on_a_worker(root, tmp_path):
    dest = str(tmp_path / "logs.zip")
    calls = []
    win, pump, _tips, _asked, _seen, _d = _window(
        root, logs_folder=lambda: calls.append(("open", on_main())),
        save_logs=lambda d: (calls.append(("save", d, on_main())), ["logs/cli.log"])[1], ask_save=lambda: dest)
    _press(win, "logs", "Open logs folder")
    _press(win, "logs", "Save logs to a file…")
    assert pump.run(root, lambda: win.logs_note.cget("text").startswith("Saved 1 files"))
    assert sorted(calls) == [("open", False), ("save", dest, False)]


def test_every_button_has_a_tooltip_and_esc_closes(root):
    win, _pump, tips, _asked, _seen, _d = _window(root)
    buttons = widgets(win.win, (ttk.Button,))
    assert len(buttons) >= 6 and all(tips.has(b) for b in buttons)
    assert [win.tabs.tab(i, "text") for i in range(3)] == ["Needs you (1)", "Batches", "Shelf"]
    root.update()
    win.win.focus_force()
    root.update()
    win.win.event_generate("<Escape>")
    root.update()
    assert not win.win.winfo_exists()


def test_view_reads_the_record_for_one_language():
    record = connect_window.view("ja")
    assert record["line"] == "Up to date" and record["needs"] == [], "no ledger: the empty record (never made)"
    from app.connect import ledger
    import os
    assert not os.path.exists(ledger.path())


def test_a_failed_mark_seen_is_said_and_reads_nothing_again(root):
    """H6: the ledger refusing `mark_seen` is said in the window (the badge keeps counting: true), never silent."""
    changes = []

    def refused(ids):
        raise OSError("the ledger is locked")
    pump2 = Pump()
    win = connect_window.show(root, "ja", Tips(), RECORD, act=Act(), settings=lambda: {"connect_enabled": True},
                              writer_busy=lambda: False, confirm=lambda t, x: True, junban=True, post=pump2.put,
                              mark_seen=refused, on_change=lambda: changes.append(1))
    assert pump2.run(root, lambda: "Couldn't mark these as seen" in win.logs_note.cget("text"))
    assert "the ledger is locked" in win.logs_note.cget("text")
    assert changes == [], "nothing read again on a failure"


def test_the_wheel_scrolls_over_the_rows_and_leaves_other_wheel_bindings_alone(root):
    """H7: Tk sends the tab a <Leave> as the pointer enters a row, so the wheel must still scroll over the rows; and
    no other window's wheel binding (bind_all) is removed."""
    many = dict(RECORD, needs=[dict(RECORD["needs"][0], id=100 + i, seen_at="2026-10-11T09:00:00Z")
                               for i in range(30)], unseen=0)
    other = []
    root.bind_all("<MouseWheel>", lambda e: other.append(1))
    win = connect_window.show(root, "ja", Tips(), many, act=Act(), settings=lambda: {"connect_enabled": True},
                              writer_busy=lambda: False, confirm=lambda t, x: True, junban=True, post=Pump().put)
    root.update()
    outer = win.tab_needs.master.master             # the tab's frame: its canvas holds the rows
    canvas = win.tab_needs.master
    outer.event_generate("<Enter>")
    outer.event_generate("<Leave>")                 # the pointer went on into a row
    label = widgets(win.tab_needs, (ttk.Label,))[5]
    assert canvas.yview()[0] == 0.0
    label.event_generate("<MouseWheel>", delta=-120)
    root.update()
    assert canvas.yview()[0] > 0.0, "the wheel over a row scrolls the list"
    assert root.bind_all("<MouseWheel>"), "the app's other wheel binding is still there"
    root.unbind_all("<MouseWheel>")
