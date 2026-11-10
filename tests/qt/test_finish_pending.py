"""Finish, Put back and *Leave its new cards out*: pending from the click until Anki moves (Mado's finish-pending card,
2026-10-23; the rule is Kura's W-1b, PROVISIONAL: "Finish acts after its Generate; pending shown at once").

Since W-1b a Finish — a drop on Finished or ⋯'s *Move to Finished* —, the Finish toast's *Leave its new cards out of
your order*, a Finished row's *Put back* and its *Leave its new cards out* / *Put them back in the order*, and their
Undo write the store at once, but Anki moves only when the re-order host has re-ordered for that write, after the
Generate it starts. Sonic's doctrine is that every press reacts at once: the press is painted before the writer has
the command (the bar's arc when the row has left the list, the row's ⋯ when it stays), and it stays live until the
store records that re-order (`planned_order_version` / `planned_pins_version` reach the change's `landed` versions).
It also ends when the host leaves the re-order to the user, saying the host's own words (Anki closed), when the
Generate fails, or when no re-order is owed (no host, automation off). A language switch lets it go.

These run on the real store, writer and reader (`test_drag.real`); the re-order host is a stand-in, except in the
fix round's last two tests (the real `ReplanHost` over the real `replan_preview.Host`, Anki refused). The store's own
handle, `store.record_planned`, plays the host's record. The stand-in's lines come in on a thread of their own, as
the host's worker sends them.

What a wrong answer would cost a learner:
  * nothing happening between the click and Anki moving, tens of seconds while a Generate runs: they press again, or
    think it didn't take;
  * a mark that never stops turning, because Anki is closed or the Generate failed, with nothing saying why;
  * a mark from the language left behind still turning after a switch.
"""
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication

from app import replan_preview
from app.qt import drag, strings
from app.services import press as press_service
from tests.qt.conftest import wait_until
from tests.qt.test_drag import real, settle  # noqa: F401 (real: a fixture)
from tests.qt.test_finished import _fin_row, _finish_outside


class Paints(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.n = 0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.n += 1
        return False


class Host:
    """The window's re-order host as these presses see it: present (the press waits for its re-order). The quit's and
    the focus's calls do nothing."""
    held = None

    def __getattr__(self, name):
        return lambda *a, **k: True if name == "finish" else None

    def busy(self):
        return False

    def settling(self):
        return False


@pytest.fixture
def window(real, monkeypatch):
    """The real window with a re-order host present and running (`stands_aside` None)."""
    monkeypatch.setattr(drag, "_aside", lambda settings, language: None, raising=False)

    def make(host=True):
        store, win, writer = real()
        win.services.replan = Host() if host else None
        return store, win, writer
    return make


def anki_presses(win):
    """The presses waiting on Anki (their keys are ("anki", n))."""
    return [p for k, p in win.presses._by_key.items() if isinstance(k, tuple) and k[0] == "anki"]


def live(win):
    return [p for p in anki_presses(win) if p.live()]


def owed(win):
    return wait_until(lambda: win.moves._owed and not win.moves._landing and not win.moves._asking, 10)


def plan(store):
    """The host's re-order recorded for the store as it stands (`Store.record_planned`)."""
    v = store.versions()
    store.record_planned(v["order_version"], v["pins_version"])


def say_from_host(win, line):
    t = threading.Thread(target=win.services._replan_line, args=(line,))
    t.start()
    t.join(5)


def hand_over_looks(monkeypatch, writer, op, look):
    """`writer.<op>` records `look()` as it is called: the window's state at the hand-over."""
    seen = []
    real_op = getattr(writer, op)

    def spy(*a, **k):
        seen.append(look())
        return real_op(*a, **k)
    monkeypatch.setattr(writer, op, spy)
    return seen


# --- the press painted before the hand-over ------------------------------------------------------------------------ #
def test_a_finish_turns_the_bars_arc_painted_before_the_writer_has_it(window, monkeypatch):
    """Before: the row left Current and the toast came, then nothing was pending until Anki moved. Now the bar's arc
    turns, no words, painted before the writer is handed the command (the row has left the list on screen)."""
    store, win, writer = window()
    arc = win.bar_arc
    paints = Paints(arc)
    QApplication.processEvents()
    before = paints.n
    seen = hand_over_looks(monkeypatch, writer, "set_tier",
                           lambda: (arc.isVisible(), arc.running, paints.n - before, len(live(win))))
    line = win.bar_line.full()
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    shown, running, painted, n = seen[0]
    assert shown and running and painted >= 1 and n == 1
    assert win.bar_line.full() == line                          # no words of its own (the toast keeps its own)


def test_the_toasts_take_out_is_a_press_of_its_own_painted_before_its_hand_over(window, monkeypatch):
    store, win, writer = window()
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    assert wait_until(lambda: not win.moves.tickets, 5)
    seen = hand_over_looks(monkeypatch, writer, "set_finished", lambda: (win.bar_arc.isVisible(), len(live(win))))
    win.toasts.card.buttons[2].click()                          # Leave its new cards out of your order
    assert seen == [(True, 2)]                                  # the drop's still waiting, and this one's own


def test_put_back_turns_the_bars_arc_before_its_hand_over(window, monkeypatch):
    store, win, writer = window()
    row = win.page_widgets["current"].view_model.rows[2]
    ids = _finish_outside(store, win, row, keep_cards=False)
    seen = hand_over_looks(monkeypatch, writer, "put_back", lambda: (win.bar_arc.isVisible(), len(live(win))))
    win.finished.put_back(_fin_row(win, ids))
    assert seen == [(True, 1)]


def test_leave_its_cards_out_marks_the_finished_rows_more_not_the_bar(window, monkeypatch):
    """The row stays in Finished: its ⋯ turns (`press.row_mark`), painted before the hand-over, and the bar's arc
    doesn't."""
    store, win, writer = window()
    win.show_tab("finished")
    row = win.page_widgets["current"].view_model.rows[3]
    ids = _finish_outside(store, win, row, keep_cards=True)
    lst = win.page_widgets["finished"].list
    settle()
    fin_row = _fin_row(win, ids)
    first = fin_row.episodes[0].id
    seen = hand_over_looks(monkeypatch, writer, "keep_cards",
                           lambda: ({k: list(v) for k, v in lst.marked.items()}, win.bar_arc.isVisible()))
    win.finished.keep_cards(fin_row, False)
    assert seen == [({first: ["more"]}, False)]


# --- held until the store records the re-order -------------------------------------------------------------------- #
def test_held_while_the_reorder_hasnt_landed_and_done_once_the_store_records_it(window):
    store, win, writer = window()
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    assert owed(win)
    p = live(win)[0]
    v = store.versions()
    store.record_planned(v["order_version"] - 1, v["pins_version"])     # an older order's re-order: not this one
    settle(300)
    assert p.live() and win.bar_arc.isVisible()
    plan(store)
    assert wait_until(lambda: not p.live(), 5)
    assert p.state in (press_service.DONE, press_service.IDLE) and not win.bar_arc.isVisible()


def test_the_cards_choice_waits_for_the_pins_reorder_too(window):
    """*Leave its new cards out* on a Finished row moves the pins alone: its press waits for `planned_pins_version`."""
    store, win, writer = window()
    row = win.page_widgets["current"].view_model.rows[3]
    ids = _finish_outside(store, win, row, keep_cards=True)
    plan(store)
    win.finished.keep_cards(_fin_row(win, ids), False)
    assert owed(win)
    p = live(win)[0]
    v = store.versions()
    store.record_planned(v["order_version"], v["pins_version"] - 1)
    settle(300)
    assert p.live()
    plan(store)
    assert wait_until(lambda: not p.live(), 5)
    assert not win.page_widgets["finished"].list.marked


def test_its_undo_lets_its_press_go_and_waits_for_its_own_reorder(window):
    store, win, writer = window()
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    assert owed(win)
    first = live(win)[0]
    drop = win.moves.toasted
    win.moves.undo(drop)
    assert not first.live()                                     # let go at the Undo's click
    assert len(live(win)) == 1 and win.bar_arc.isVisible()      # the Undo's own, at once
    assert wait_until(lambda: all(store.item(i)["tier"] == "now" for i in drag.ids_of(row)), 5)
    assert owed(win)
    back = live(win)[0]
    plan(store)
    assert wait_until(lambda: not back.live(), 5) and not win.bar_arc.isVisible()


# --- ended when nothing more comes by itself ---------------------------------------------------------------------- #
def test_anki_closed_ends_it_failed_with_the_hosts_words_and_a_retry_doesnt(window):
    store, win, writer = window()
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    assert owed(win)
    p = live(win)[0]
    say_from_host(win, replan_preview.REVIEWING)                 # retried by the host: still coming
    say_from_host(win, replan_preview.GENERATE_FIRST)
    settle(200)
    assert p.live()
    say_from_host(win, gives_up(replan_preview.CLOSED))
    assert wait_until(lambda: p.state == press_service.FAILED, 5)
    assert p.words == replan_preview.CLOSED and win.bar_line.full() == replan_preview.CLOSED
    assert not win.bar_arc.isVisible()


def test_a_generate_that_fails_ends_it_failed_with_generates_words(window):
    store, win, writer = window()
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    assert owed(win)
    p = live(win)[0]
    job = win.services.registry.record("generate", "Generating", automatic=True)
    settle(200)
    job.finish(ok=False, message="the disk is full")
    assert wait_until(lambda: p.state == press_service.FAILED, 5)
    words = strings.ANKI_WAIT_GENERATE_FAILED.format(message="the disk is full")
    assert p.words == words and win.bar_line.full() == words and not win.bar_arc.isVisible()


@pytest.mark.parametrize("aside, failed", [(replan_preview.AUTOMATION_OFF, False), (replan_preview.JUNBAN_OFF, False),
                                           ("順's deck 日本語 isn't recorded for Japanese — pick it in 順's window in "
                                            "Japanese", True)])
def test_a_host_standing_aside_ends_it_as_the_write_lands(window, monkeypatch, aside, failed):
    """Automation or 順 off is the learner's own choice: nothing is owed, done quietly. A deck to pick in 順 is theirs
    to fix: failed, the host's own words in the bar. Never left turning."""
    store, win, writer = window()
    monkeypatch.setattr(drag, "_aside", lambda settings, language: aside)
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    p = anki_presses(win)[0]
    assert wait_until(lambda: not p.live(), 5)
    assert (p.state == press_service.FAILED) is failed
    if failed:
        assert p.words == aside and win.bar_line.full() == aside
    assert not win.moves._owed and not win.bar_arc.isVisible()


def test_no_host_owes_nothing_the_press_ends_as_the_write_lands(window):
    store, win, writer = window(host=False)
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    p = anki_presses(win)[0]
    assert wait_until(lambda: not p.live(), 5)
    assert p.state != press_service.FAILED and not win.bar_arc.isVisible()


def test_a_language_switch_lets_it_go(window):
    """The switch lets the window's drag controller go (`DragController.close`, as `_switch_library` does): nothing
    of the language left turns."""
    store, win, writer = window()
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    assert owed(win)
    p = live(win)[0]
    win.moves.close()
    assert not p.live() and not win.bar_arc.isVisible()


# --- the writer's stamp and the reader's versions --------------------------------------------------------------- #
def test_the_writer_stamps_each_change_and_its_undo_with_the_versions_it_landed_at(window):
    store, win, writer = window(host=False)
    row = win.page_widgets["current"].view_model.rows[2]
    seen = []
    win.moves.to_finished(row)
    drop = win.moves.toasted
    assert wait_until(lambda: drop.change is not None, 5)
    v = store.versions()
    seen.append(drop.change.landed)
    assert drop.change.landed == {"epoch": v["epoch"], "order_version": v["order_version"],
                                  "pins_version": v["pins_version"]}
    win.moves.undo(drop)
    assert wait_until(lambda: drop.change.landed != seen[0], 5)
    assert drop.change.landed["order_version"] == store.versions()["order_version"] > seen[0]["order_version"]


def test_the_reader_tells_a_recorded_reorder_alone_to_its_version_watchers(window):
    store, win, writer = window(host=False)
    told = []
    win.services.library.subscribe_versions(told.append)
    settle(100)
    plan(store)
    assert wait_until(lambda: told and told[-1]["planned_order_version"] == store.versions()["order_version"], 5)


# --- fix round (registers finish-pending-adversary FP-A1…A8, finish-pending-intent-keeper FP-1…FP-4, findings 2–4) -- #
def gives_up(line):
    """The host's line as it says one that leaves the re-order to the user (`Host._tell(…, gives_up=True)`)."""
    return replan_preview.GivesUp(line)


def finish_one(win, n=2):
    row = win.page_widgets["current"].view_model.rows[n]
    win.moves.to_finished(row)
    return row


def test_fp_a1_an_earlier_commands_reread_never_ends_the_finishs_press_before_its_reorder(window):
    """FP-A1: the writer takes the Finish off its queue before it tells `on_saved`. A reread an earlier command left
    (one that changed nothing: a background cover, a no-op) reached the window first, found nothing pending and ended
    every press still waiting for its write, the Finish's too: its mark stopped while Anki was still owed. Only a
    press whose own command landed as nothing ends there."""
    store, win, writer = window()
    other = win.page_widgets["current"].view_model.rows[4]
    writer.pin(drag.ids_of(other), False)                       # unpinned already: lands as nothing, a reread
    finish_one(win)
    assert writer.idle(5)                                       # both landed; their calls wait for this thread
    assert owed(win)
    p = live(win)
    assert len(p) == 1 and store.versions()["planned_order_version"] < store.versions()["order_version"]
    plan(store)
    assert wait_until(lambda: not p[0].live(), 5)


def test_fp_a1_an_undo_the_store_refuses_ends_its_own_press(window):
    """The other side of FP-A1: an Undo refused (another program put it back meanwhile) writes nothing, so its press
    ends (the writer names its label among the commands that landed as nothing)."""
    store, win, writer = window()
    row = finish_one(win)
    assert owed(win)
    drop = win.moves.toasted
    store.set_tier(drag.ids_of(row), "soon")                    # another program moves it on
    win.moves.undo(drop)
    assert wait_until(lambda: not live(win), 5)


def test_fp_a2_a_line_the_host_retries_keeps_it_turning_and_one_it_gives_up_on_ends_it(window):
    """FP-A2 / A5 / intent 4: "Anki not re-ordered: …" is said both when the host tries again in 20 s (Anki went away
    mid-write) and when it never will; its words alone can't tell. The host says which (`GivesUp`), and only that kind
    ends the press. A stand-aside line ("Generate re-orders Anki this time") and an update's hold keep it turning:
    Anki moves after them by itself."""
    store, win, writer = window()
    finish_one(win)
    assert owed(win)
    p = live(win)[0]
    for line in ("Anki not re-ordered: Anki went offline", replan_preview.STAND_ASIDE_ELSE,
                 replan_preview.STAND_ASIDE["weights"], replan_preview.UPDATE, replan_preview.GENERATE_FIRST):
        say_from_host(win, line)
    settle(200)
    assert p.live()
    words = "Anki not re-ordered: the deck TheBank isn't in Anki"
    say_from_host(win, gives_up(words))
    assert wait_until(lambda: p.state == press_service.FAILED, 5)
    assert p.words == words and win.bar_line.full() == words


def test_fp_a3_a_generate_the_learner_stops_ends_it_failed_with_words_and_one_withdrawn_keeps_it(window, monkeypatch):
    """FP-A3 / FP-3: a Generate stopped from the bar ends cancelled, and the host never asks for it again: the press
    ends failed, saying so as a failed Generate's would. One the journey keeper withdrew (a move came; it asks again
    after the settle) or one the learner's own Generate joined keeps it turning."""
    store, win, writer = window()
    finish_one(win)
    assert owed(win)
    p = live(win)[0]
    registry = win.services.registry
    withdrawn = registry.record("generate", "Generating (automatic)", automatic=True)
    monkeypatch.setattr(win.services, "controller", type("Keeper", (), {"withdrawn": lambda self, job_id: job_id == withdrawn.id})())
    settle(100)
    withdrawn.finish(ok=True, cancelled=True)                   # the keeper's, taken back
    joined = registry.record("generate", "Generating (automatic)", automatic=True)
    settle(100)
    mine = registry.record("generate", "Generating")
    joined.finish(ok=True, cancelled=True)                      # the learner's own runs instead
    settle(200)
    assert p.live()
    mine.finish(ok=True, cancelled=True)                        # stopped from the bar
    assert wait_until(lambda: p.state == press_service.FAILED, 5)
    assert p.words == strings.ANKI_WAIT_GENERATE_STOPPED and win.bar_line.full() == strings.ANKI_WAIT_GENERATE_STOPPED


def test_fp_a4_automation_or_jun_switched_off_while_it_waits_ends_it_quietly(window):
    """FP-A4 / FP-4: the host lets go with no line when the learner turns automation or 順 off (their own choice), so
    nothing ended the press. It now hears `OFF` and ends quietly — the same rule as when it is off at the write."""
    store, win, writer = window()
    finish_one(win)
    assert owed(win)
    p = live(win)[0]
    line = win.bar_line.full()
    say_from_host(win, replan_preview.OFF)
    assert wait_until(lambda: not p.live(), 5)
    assert p.state != press_service.FAILED and win.bar_line.full() == line and not win.bar_arc.isVisible()


def test_fp_a6_a_line_said_while_the_gate_is_asked_still_ends_it(window, monkeypatch):
    """FP-A6: a give-up line said while the press was between its write landing and the gate's answer was dropped."""
    store, win, writer = window()
    asked = threading.Event()
    answer = threading.Event()

    def aside(settings, language):
        asked.set()
        answer.wait(5)
    monkeypatch.setattr(drag, "_aside", aside)
    finish_one(win)
    assert wait_until(lambda: asked.is_set(), 5)
    p = live(win)[0]
    say_from_host(win, gives_up(replan_preview.CLOSED))
    settle(100)
    answer.set()
    assert wait_until(lambda: p.state == press_service.FAILED, 5)
    assert p.words == replan_preview.CLOSED


def test_fp_a7_an_ended_press_leaves_no_key_behind(window):
    """FP-A7: each Finish made a key in the window's press table that nothing took out."""
    store, win, writer = window()
    finish_one(win)
    assert owed(win)
    plan(store)
    assert wait_until(lambda: not live(win), 5)
    assert anki_presses(win) == []


def test_f2_ctrl_z_of_a_finish_waits_for_its_undos_reorder(window):
    """Intent finding 2: Ctrl+Z of a Finish took it back in the store at once, but nothing showed that Anki would only
    follow after the Generate. Now the undo's own press waits, as the toast's Undo does; the Finish's is let go."""
    store, win, writer = window()
    row = finish_one(win)
    assert owed(win)
    first = live(win)[0]
    assert wait_until(lambda: not win.moves.tickets, 5)
    win.moves.undo_last()
    assert wait_until(lambda: all(store.item(i)["tier"] == "now" for i in drag.ids_of(row)), 5)
    assert owed(win)
    back = live(win)
    assert not first.live() and len(back) == 1 and win.bar_arc.isVisible()
    plan(store)
    assert wait_until(lambda: not back[0].live(), 5)


def test_f2_an_undo_pressed_before_its_finish_was_saved_keeps_the_mark_until_the_undos_reorder(window):
    """Intent finding 2: with the store busy, an Undo asked before the Finish was saved let the press go, and the
    undo ran as the write landed with nothing pending. The mark now stays from the click through the undo's re-order."""
    store, win, writer = window()
    writer.hold()
    row = finish_one(win)
    drop = win.moves.toasted
    win.moves.undo(drop)
    assert len(live(win)) == 1                                  # still turning: the undo's Anki half is owed too
    writer.release()
    assert wait_until(lambda: all(store.item(i)["tier"] == "now" for i in drag.ids_of(row)), 5)
    assert owed(win)
    p = live(win)
    assert len(p) == 1
    plan(store)
    assert wait_until(lambda: not p[0].live(), 5)


def test_fp1_the_bars_arc_says_on_hover_that_anki_moves_after_the_generate(window):
    """FP-1 lean (b), PROVISIONAL: no words in the bar while it waits; a hover on the arc says what it waits for."""
    store, win, writer = window()
    finish_one(win)
    assert owed(win)
    assert win.bar_arc.toolTip() == strings.ANKI_WAIT_TIP
    plan(store)
    assert wait_until(lambda: not live(win), 5)
    assert win.bar_arc.toolTip() == ""


# --- the adversary's test gaps (Mado, 2026-10-23): every end path pinned -------------------------------------------- #
def test_a_finish_that_lands_as_nothing_ends_its_press(window):
    """Gap 1: another program finished it first, so the writer finds nothing to change: its press ends, never turns on."""
    store, win, writer = window()
    writer.hold()
    row = finish_one(win)
    store.set_tier(drag.ids_of(row), "graduated")              # finished elsewhere meanwhile
    assert len(live(win)) == 1
    writer.release()
    assert wait_until(lambda: not live(win), 5)
    assert not win.moves._owed and not win.bar_arc.isVisible()


def test_a_finish_the_store_refuses_as_it_lands_ends_its_press(window, monkeypatch):
    """Gap 2: the store turned read-only between the press and the write: the writer refuses it, says why, and its
    press ends (the writer names its label among those that landed as nothing)."""
    store, win, writer = window()
    writer.hold()
    finish_one(win)
    assert len(live(win)) == 1
    monkeypatch.setattr(writer, "_store", lambda: (None, False))
    writer.release()
    assert wait_until(lambda: not live(win), 5)
    assert not win.moves._owed


def test_a_finish_refused_at_the_press_turns_nothing(window, monkeypatch):
    store, win, writer = window()
    monkeypatch.setattr(writer, "set_tier", lambda *a, **k: None)
    finish_one(win)
    settle(200)
    assert not live(win) and not win.bar_arc.isVisible()


def test_put_them_back_in_the_order_marks_the_rows_more_and_waits_for_the_pins_reorder(window, monkeypatch):
    """Gap 3 (FP-2, kept): *Put them back in the order* is the same `keep_cards` path, the same press on the row's ⋯."""
    store, win, writer = window()
    win.show_tab("finished")
    row = win.page_widgets["current"].view_model.rows[3]
    ids = _finish_outside(store, win, row, keep_cards=False)
    plan(store)
    settle()
    fin_row = _fin_row(win, ids)
    lst = win.page_widgets["finished"].list
    seen = hand_over_looks(monkeypatch, writer, "keep_cards", lambda: {k: list(v) for k, v in lst.marked.items()})
    win.finished.keep_cards(fin_row, True)
    assert seen == [{fin_row.episodes[0].id: ["more"]}]
    assert owed(win)
    p = live(win)[0]
    plan(store)
    assert wait_until(lambda: not p.live(), 5) and not lst.marked


def test_the_finish_toasts_keep_starts_no_press_of_its_own(window):
    """Gap 3: *Keep* writes the flag it already has: the drop's press alone, nothing more."""
    store, win, writer = window()
    finish_one(win)
    assert wait_until(lambda: not win.moves.tickets, 5)
    assert owed(win)
    win.toasts.card.buttons[1].click()                          # Keep
    settle(200)
    assert len(anki_presses(win)) == 1


def test_the_shells_language_switch_lets_it_go(qapp, monkeypatch):
    """Gap 4: the shell's own switch (Settings › Language), not `close()` called by hand: the ja press stops turning."""
    from app.qt import shell
    from tests.test_library_store_support import migrated
    from tests.qt.test_shell_library import _ask, _switched_to
    ja, zh = migrated("ja"), migrated("zh")
    services = shell.open_services()
    win = shell.open_window(qapp, services)
    try:
        win.resize(1280, 900)
        win.show()
        assert wait_until(lambda: win.page_widgets["current"].view_model is not None
                          and win.page_widgets["current"].view_model.state == "full", 15)
        services.replan = Host()
        monkeypatch.setattr(drag, "_aside", lambda settings, language: None)
        finish_one(win)
        assert wait_until(lambda: win.moves._owed, 10)
        p = live(win)[0]
        _ask(services, win, "zh")
        assert _switched_to(win, services, "zh", 30)
        assert not p.live() and not win.bar_arc.isVisible()
    finally:
        win.close()
        services.shutdown(2.0)
        ja.close()
        zh.close()


# --- the real re-order host on the Finish path ---------------------------------------------------------------------- #
@pytest.fixture
def real_host(real, monkeypatch):
    """The window with the real `ReplanHost` over the real `replan_preview.Host` in this process: 順 on with its deck
    recorded, the gate the real one (`stands_aside`), Anki answering nothing (urlopen refused: closed)."""
    import urllib.error
    from unittest import mock
    pytest.importorskip("modules.junban")
    from app import settings_manager
    from app.services import replan_host
    settings_manager.save_keys({"enable_junban": True, "junban_deck": "TheBank", "junban_scope": "deck",
                                "junban_replan_language": "ja", "junban_replan_deck": "TheBank",
                                "anki_connect_url": "http://127.0.0.1:18765"})
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)     # Anki "reached": urlopen answers refused, never Anki
    closed = mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("[WinError 10061] refused"))
    closed.start()
    made = []

    def make():
        store, win, writer = real()
        services = win.services
        host = replan_host.ReplanHost(services.registry, settings_manager.load_settings, "ja",
                                      on_line=services._replan_line,
                                      opener=lambda language, **kw: replan_preview.Host(language, **kw))
        services.replan = host
        made.append(host)
        return store, win, writer, host
    yield make
    for host in made:
        host.stop()
    closed.stop()


def test_the_real_host_finding_anki_closed_ends_it_failed_with_its_words(real_host):
    store, win, writer, host = real_host()
    finish_one(win)
    assert owed(win)
    p = live(win)[0]
    host.poke()                                                 # the reader's store move, as the window tells it
    assert wait_until(lambda: p.state == press_service.FAILED, 15)
    assert p.words == replan_preview.CLOSED and win.bar_line.full() == replan_preview.CLOSED


def test_the_real_host_switched_off_while_it_waits_ends_it_quietly(real_host):
    from app import settings_manager
    store, win, writer, host = real_host()
    host.poke()
    assert host.worker.idle(10)                                 # its gate open: a host made
    finish_one(win)
    assert owed(win)
    p = live(win)[0]
    settings_manager.save_keys({"enable_junban": False})        # 順 switched off meanwhile
    host.poke()
    assert wait_until(lambda: not p.live(), 10)
    assert p.state != press_service.FAILED and not win.bar_arc.isVisible()


def test_a7_a_press_ended_by_only_i_plus_one_says_the_strips_words(window, monkeypatch):
    """a7: the gate's stand-aside ends a waiting press with the same words the strip says (`aside_line`), never
    the old "Not with 'Only i+1'" line beside the new one."""
    from app import replan_preview as rp
    store, win, writer = window()
    line = rp.GivesUp(rp.AFTER_GENERATE.format(mode="Only i+1 sentences"))
    monkeypatch.setattr(drag, "_aside", lambda settings, language: line)
    row = win.page_widgets["current"].view_model.rows[2]
    win.moves.to_finished(row)
    p = anki_presses(win)[0]
    assert wait_until(lambda: not p.live(), 5)
    assert p.words == line and win.bar_line.full() == line
