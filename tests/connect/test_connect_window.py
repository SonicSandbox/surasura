"""The Connect window (P3.1 row 3.1.6; P1.5 05-surface U3; RUNBOOK-P2.5 *The status contract*): *Needs you*, the
batches with *Undo this batch*, the shelf with *Put back*, and the Logs box.

What a wrong answer would cost: an undo sent without the question deletes cards the user meant to keep; a cancelled
question that still writes is worse; an undo on the screen's thread freezes the window for the 18–24 s Anki Miner holds
Anki's write lock — and one that gives up at once says "busy" where it should have waited; *Put back* shown without
Junban fails on click; *Dismiss* that doesn't reach the ledger brings the entry back; a window Esc doesn't close traps
the keyboard. Every Connect call is stood in for (`undo.act`, `status`'s two writes), each recording its thread;
real Japanese words, synthetic titles."""
import gc
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
        r = None
        # why: each test makes its own Tk root; one left to the cycle collector can be freed on the next test's worker
        # thread (a `job` that happens to start a collection), and Tcl aborts the whole run (Windows fatal 0x80000003).
        # The app has one root for its whole life, so this is the tests' own: free it here, on the Tk thread.
        gc.collect()


def _window(root, act=None, confirm=True, junban=True, **kw):
    pump, tips, asked, seen, dismissed = Pump(), Tips(), [], [], []
    win = connect_window.show(
        root, "ja", tips, RECORD, act=act or Act(), settings=lambda: {"connect_enabled": True},
        writer_busy=kw.pop("writer_busy", lambda: False), update_waits=kw.pop("update_waits", lambda: False),
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


# --- P3.2: *Ask hato again* (RUNBOOK-P3.2 row 3.2.4) -----------------------------------------------------------------

NO_PAIRING = {"id": 21, "kind": "no-pairing", "item": None, "title": None, "at": "2026-10-12T09:00:00Z",
              "seen_at": None, "say": "4 files in hato's folder have no pairing from hato, so Connect can't tell which "
                                      "video they belong to."}


def _summary(**more):
    from app.connect import hato
    out = {"language": "ja", "hato": hato.ASKED, "new": 2, "same": 61, "replaced": 0, "refused": [],
           "unpaired": ["a.srt", "b.srt"], "stopped": None, "skipped": None, "need": "raised"}
    out.update(more)
    return out


def test_ask_hato_again_back_fills_on_a_worker_and_says_its_words_in_the_entrys_note(root, monkeypatch):
    """The no-pairing entry's one action: hato asked again on a worker (it waits up to a minute for hato), the
    summary's words in the entry's note, the dashboard's line read again; the button back for another try while files
    are left, gone once none are (the entry fixed). Its tooltip says what it does; Esc still closes."""
    from app.connect import hato
    calls, answers = [], [_summary(), _summary(new=2, same=63, unpaired=[], need="fixed")]

    def backfill(lang, settings, wait=10, run=None):
        calls.append((lang, settings, on_main()))
        return answers.pop(0)
    monkeypatch.setattr(hato, "backfill", backfill)
    pump, tips, changes = Pump(), Tips(), []
    win = connect_window.show(root, "ja", tips, dict(RECORD, needs=[NO_PAIRING], unseen=1), act=Act(),
                              settings=lambda: {"connect_enabled": True}, writer_busy=lambda: False,
                              confirm=lambda t, x: True, junban=True, post=pump.put, mark_seen=lambda ids: 1,
                              on_change=lambda: changes.append(1))
    key = ("needs", 21, "Ask hato again")
    note = win.notes[("needs", 21)]
    assert tips.has(win.buttons[key]) and "pairings" in [t for w, t in tips if w is win.buttons[key]][0]
    pump.run(root, lambda: changes)                         # marked seen first
    changes.clear()
    _press(win, *key)
    assert pump.run(root, lambda: note.cget("text").startswith("hato's pairings (Japanese): 2 new, 61 already there."))
    assert note.cget("text").endswith(NO_PAIRING["say"].replace("4 files", "2 files"))
    assert calls == [("ja", {"connect_enabled": True}, False)], "hato.backfill on a worker, never the Tk thread"
    assert str(win.buttons[key].cget("state")) == "normal" and changes == [1], "files left: it can be asked again"
    _press(win, *key)
    assert pump.run(root, lambda: key not in win.buttons), "none left: the entry is fixed, its button goes"
    assert note.cget("text") == "hato's pairings (Japanese): 2 new, 63 already there."
    win.win.focus_force()
    root.update()
    win.win.event_generate("<Escape>")
    root.update()
    assert not win.win.winfo_exists()


def test_ask_hato_again_that_fails_says_why_and_keeps_its_button(root, monkeypatch):
    from app.connect import hato

    def backfill(lang, settings, wait=10, run=None):
        raise OSError("the ledger is locked")
    monkeypatch.setattr(hato, "backfill", backfill)
    pump = Pump()
    win = connect_window.show(root, "ja", Tips(), dict(RECORD, needs=[NO_PAIRING], unseen=1), act=Act(),
                              settings=lambda: {"connect_enabled": True}, writer_busy=lambda: False,
                              confirm=lambda t, x: True, junban=True, post=pump.put, mark_seen=lambda ids: 1)
    _press(win, "needs", 21, "Ask hato again")
    note = win.notes[("needs", 21)]
    assert pump.run(root, lambda: note.cget("text") == "hato's pairings weren't read: the ledger is locked")
    assert str(win.buttons[("needs", 21, "Ask hato again")].cget("state")) == "normal"


def test_ask_hato_again_with_settings_json_half_saved_says_try_again_and_asks_hato_nothing(root, monkeypatch):
    """settings.json read the moment another window is saving it: *Ask hato again* says it can't be read just now and
    keeps its button — hato isn't asked."""
    # why: read leniently (the window's own settings reader, as the dashboard opens it), a half-saved settings.json is
    # the defaults — the preview off — so the back-fill answered "Connect's preview is off" while it was on
    import os
    from app.connect import hato
    calls = []
    monkeypatch.setattr(hato, "backfill", lambda lang, settings, **k: (calls.append(settings), {})[1])
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w", encoding="utf-8") as f:
        f.write('{"target_language": "ja", "connect_enabled": tr')
    pump = Pump()
    win = connect_window.show(root, "ja", Tips(), dict(RECORD, needs=[NO_PAIRING], unseen=1), act=Act(),
                              writer_busy=lambda: False, confirm=lambda t, x: True, junban=True, post=pump.put,
                              mark_seen=lambda ids: 1)
    _press(win, "needs", 21, "Ask hato again")
    note = win.notes[("needs", 21)]
    assert pump.run(root, lambda: note.cget("text") == "hato's pairings weren't read: settings.json can't be read "
                                                       "just now; try again.")
    assert calls == [], "hato isn't asked on a guess at the switch"
    assert str(win.buttons[("needs", 21, "Ask hato again")].cget("state")) == "normal"


# --- the final adversary's rows (P3.1 W5) -----------------------------------------------------------------------------

class Clock:
    """`time` stood in for in the window's module: each look moves a millisecond, a sleep moves its length."""

    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def monotonic(self):
        self.now += 0.001
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def _bare(act, busy=True, update=False):
    """A window without Tk (the probe's way): `_write` alone, its posts counted."""
    w = connect_window.ConnectWindow.__new__(connect_window.ConnectWindow)
    w.language, w._act, w._settings = "ja", act, lambda: {"connect_enabled": True}
    w._writer_busy, w._update_waits = (lambda: busy), (lambda: update)
    w.posts = []
    w.post = w.posts.append
    return w


BUSY = CliError("busy", "Another program is writing to Anki. Try again in a moment.", lock="anki-writer", held_by=None)


def _refused(calls):
    def act(settings, language, **kw):
        calls.append(kw)
        raise BUSY
    return act


def test_a_writer_refused_at_once_is_tried_a_second_apart_a_handful_of_times_and_the_wait_said_once(monkeypatch):
    """Adversary #1: with Anki's write lock held by a live program and every try refused at once, the undo tries again
    at least a second apart until its wait runs out — a handful of calls, never thousands, and the waiting line
    posted once (never a flood on the dashboard's queue)."""
    clock = Clock()
    monkeypatch.setattr(connect_window, "time", clock)
    monkeypatch.setattr(connect_window, "WAIT_FOR_WRITER_S", 5)
    calls = []
    w = _bare(_refused(calls))
    with pytest.raises(CliError) as e:
        w._write(None, job=7, confirm=True)
    assert e.value is BUSY, "the wait ran out: the act's own words"
    assert 2 <= len(calls) <= 7, f"{len(calls)} tries in a 5 s wait"
    assert clock.sleeps and all(s >= 1.0 for s in clock.sleeps)
    assert len(w.posts) == 1, "the waiting line posted once"


def test_an_update_waiting_stops_the_undo_at_once_with_its_words(monkeypatch):
    """Adversary #1: the writer refused because an update waits to install — no program will let go, so the undo
    stops at its first refusal and says so."""
    clock = Clock()
    monkeypatch.setattr(connect_window, "time", clock)
    calls = []
    with pytest.raises(CliError) as e:
        _bare(_refused(calls), busy=False, update=True)._write(None, shelf_run="r-20261010", confirm=True)
    assert e.value.message == "Surasura is waiting to install an update; try again after it."
    assert len(calls) == 1 and clock.sleeps == []


def test_a_refusal_no_live_program_explains_stops_at_once(monkeypatch):
    """Adversary #1: refused with nobody holding the lock (a lock file that can't be opened): said at once, no wait."""
    clock = Clock()
    monkeypatch.setattr(connect_window, "time", clock)
    calls = []
    w = _bare(_refused(calls), busy=False)
    with pytest.raises(CliError) as e:
        w._write(None, job=7, confirm=True)
    assert e.value is BUSY and len(calls) == 1 and clock.sleeps == [] and w.posts == []


def test_writer_busy_is_no_live_program_when_the_lock_file_cant_be_opened(monkeypatch):
    """Adversary #1: `locks.in_use` reads a lock file it can't open as held (failing closed); the wait doesn't."""
    from app import locks
    monkeypatch.setattr(locks, "in_use", lambda name, **k: True)
    monkeypatch.setattr(locks, "unopenable", lambda name: "C:/locks/anki-writer.lock")
    assert connect_window.writer_busy() is False
    monkeypatch.setattr(locks, "unopenable", lambda name: None)
    assert connect_window.writer_busy() is True


TWO = dict(RECORD, undo=[
    {"job": 9, "item": 4, "title": "Example Show - 05", "kind": "mine", "made": 1, "at": "2026-10-11T08:00:00Z",
     "not_made": {}},
    {"job": 7, "item": 4, "title": "Example Show - 05", "kind": "mine", "made": 3, "at": "2026-10-09T08:00:00Z",
     "not_made": {}},
    {"job": 5, "item": 6, "title": "Example Show - 07", "kind": "mine", "made": 2, "at": "2026-10-08T08:00:00Z",
     "not_made": {}}])


def test_two_batches_of_one_episode_the_question_names_this_batch_and_says_the_other_stays(root):
    """Adversary #8: Sonic's words stay; with the episode's other batch in the list, the question names this batch's
    date and that the other stays (one batch goes, never both)."""
    act = Act(PLAN, DONE)
    pump, asked = Pump(), []
    win = connect_window.show(root, "ja", Tips(), TWO, act=act, settings=lambda: {"connect_enabled": True},
                              writer_busy=lambda: False, update_waits=lambda: False,
                              confirm=lambda t, x: (asked.append(x), True)[1], junban=True, post=pump.put)
    _press(win, "batch", 7, "Undo this batch")
    assert pump.run(root, lambda: asked)
    lines = asked[0].splitlines()
    assert lines[0] == "Remove all of this episode's Anki cards that aren't studied?"
    assert lines[1] == (f"This batch was made {connect_window.when('2026-10-09T08:00:00Z')}. Its other batch "
                        f"({connect_window.when('2026-10-11T08:00:00Z')}) stays.")
    assert connect_window.when("2026-10-08T08:00:00Z") not in asked[0], "another episode's batch isn't named"
    alone = connect_window.question(PLAN)
    assert alone.splitlines()[:3] == ["Remove all of this episode's Anki cards that aren't studied?", "", "2 cards go."]


def test_dismiss_takes_the_entry_off_and_the_tabs_count_follows_the_list(root):
    """D1 (the DevTest drill): after *Dismiss* the row goes and the tab no longer says "Needs you (1)"; the list
    emptied says so."""
    win, pump, _tips, _asked, _seen, dismissed = _window(root)
    assert win.tabs.tab(0, "text") == "Needs you (1)"
    _press(win, "needs", 11, "Dismiss")
    assert pump.run(root, lambda: win.tabs.tab(0, "text") == "Needs you")
    texts = [w.cget("text") for w in widgets(win.tab_needs, (ttk.Label,))]
    assert RECORD["needs"][0]["say"] not in texts and RECORD["needs"][1]["say"] in texts
    _press(win, "needs", 12, "Dismiss")
    assert pump.run(root, lambda: "Nothing needs you." in [w.cget("text")
                                                           for w in widgets(win.tab_needs, (ttk.Label,))])
    assert win.tabs.tab(0, "text") == "Needs you" and [i for i, _m in dismissed] == [11, 12]


def test_one_card_is_said_in_the_singular(root):
    """D2 (the DevTest drill): "1 card", never "1 cards" — the batch, the shelf, its run, the questions and the
    undo's answer."""
    one = dict(RECORD, undo=[dict(RECORD["undo"][0], made=1)],
               shelf={"on_shelf": 1, "swap_ins": 0, "runs": [dict(RECORD["shelf"]["runs"][0], cards=1)]})
    pump, asked = Pump(), []
    act = Act({"language": "ja", "shelf": "r-20261010", "back": 1, "confirm": True})
    win = connect_window.show(root, "ja", Tips(), one, act=act, settings=lambda: {"connect_enabled": True},
                              writer_busy=lambda: False, update_waits=lambda: False,
                              confirm=lambda t, x: (asked.append(x), True)[1], junban=True, post=pump.put)
    texts = " | ".join(w.cget("text") for w in widgets(win.win, (ttk.Label,)))
    assert "1 cards" not in texts
    assert "1 card made" in texts and "1 card on the shelf" in texts and "1 card · the cap" in texts
    _press(win, "shelf", "r-20261010", "Put back")
    note = win.notes[("shelf", "r-20261010")]
    assert pump.run(root, lambda: note.cget("text") == "1 card back in your new cards.")
    assert asked[0].startswith("Put 1 card back")
    assert "1 card goes." in connect_window.question(dict(PLAN, delete=1))
    from app.connect import undo
    assert undo.summary({"job": 7, "item": 4, "delete": [1], "gone": [], "keep": [], "deleted": [1],
                         "placed_again": True})["say"].startswith("1 card deleted.")


def test_a_done_undo_and_put_back_take_their_button_away_and_a_refused_one_keeps_it(root):
    """D3 (the DevTest drill): a button whose work is done goes — never left greyed; the result stays said. A refused
    one keeps its button, usable again."""
    act = Act(PLAN, DONE, {"language": "ja", "shelf": "r-20261010", "back": 2, "confirm": True})
    win, pump, _tips, _asked, _seen, _d = _window(root, act)
    undo_button = win.buttons[("batch", 7, "Undo this batch")]
    _press(win, "batch", 7, "Undo this batch")
    assert pump.run(root, lambda: win.notes[("batch", 7)].cget("text").startswith("2 cards deleted"))
    assert not undo_button.winfo_exists() and ("batch", 7, "Undo this batch") not in win.buttons
    put = win.buttons[("shelf", "r-20261010", "Put back")]
    _press(win, "shelf", "r-20261010", "Put back")
    assert pump.run(root, lambda: not put.winfo_exists())
    assert win.notes[("shelf", "r-20261010")].cget("text") == "2 cards back in your new cards."
    win.win.destroy()

    act = Act(PLAN, CliError("anki-busy", "You're reviewing in Anki. Undo once you've finished."))
    win, pump, _tips, _asked, _seen, _d = _window(root, act)
    _press(win, "batch", 7, "Undo this batch")
    assert pump.run(root, lambda: win.notes[("batch", 7)].cget("text").startswith("You're reviewing"))
    assert str(win.buttons[("batch", 7, "Undo this batch")].cget("state")) == "normal"


# --------------------------------------------------------------------------- #
# P3.2-AMN: Anki Miner's update notice above the tabs
# --------------------------------------------------------------------------- #
RELEASE_PAGE = "https://github.com/0xzerolight/anki_miner/releases/tag/v3.8.0"


def _window_with(root, update, opened):
    tips = Tips()
    win = connect_window.show(root, "ja", tips, dict(RECORD, anki_miner_update=update), act=Act(),
                              settings=lambda: {"connect_enabled": True}, junban=True, post=Pump().put,
                              mark_seen=lambda ids: None, open_url=opened.append)
    return win, tips


def test_anki_miners_notice_sits_above_the_tabs_and_opens_its_releases_page(root):
    opened = []
    win, tips = _window_with(root, {"version": "3.8.0", "url": RELEASE_PAGE}, opened)
    link = win.update_link
    assert link is not None and link.cget("text") == "Anki Miner 3.8.0 is out"
    assert ("Opens Anki Miner's releases page" in [t for w, t in tips if w is link])
    slaves = link.master.pack_slaves()
    assert slaves.index(link) < slaves.index(win.tabs), "above Needs you (the tabs)"
    link.event_generate("<Button-1>")
    assert opened == [RELEASE_PAGE]


def test_no_notice_no_line_in_the_window(root):
    win, _tips = _window_with(root, None, [])
    assert win.update_link is None
    labels = [w.cget("text") for w in widgets(win.win, (ttk.Label,))]
    assert not any("is out" in str(t) for t in labels)


def test_view_carries_the_notice_from_the_status_record(monkeypatch):
    from app.connect import status
    monkeypatch.setattr(status, "anki_miner_update", lambda: {"version": "3.8.0", "url": RELEASE_PAGE})
    assert connect_window.view("ja")["anki_miner_update"] == {"version": "3.8.0", "url": RELEASE_PAGE}


def test_a10_a_browser_that_fails_never_raises_into_tk(root, monkeypatch):
    """A10 (the first review): the window's link is guarded as the row's is — a `webbrowser.open` failure (no
    browser, a broken handler) is printed, never raised into Tk's callback."""
    reported = []
    monkeypatch.setattr(root, "report_callback_exception", lambda *exc: reported.append(exc))

    def broken(url):
        raise OSError("no browser")
    tips = Tips()
    win = connect_window.show(root, "ja", tips, dict(RECORD, anki_miner_update={"version": "3.8.0",
                                                                                "url": RELEASE_PAGE}),
                              act=Act(), settings=lambda: {"connect_enabled": True}, junban=True, post=Pump().put,
                              mark_seen=lambda ids: None, open_url=broken)
    win.update_link.event_generate("<Button-1>")
    root.update()
    assert reported == [], "the click raised into Tk"
