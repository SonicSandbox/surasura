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

These run on the real store, writer and reader (`test_drag.real`); the re-order host is a stand-in. The store's own
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
    say_from_host(win, replan_preview.CLOSED)
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
