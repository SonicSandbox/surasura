"""Every press reacts at once, P4 (round 8 row 45; the scope `row45-54-scope.md` §3.5): a write's toast says it waits
wherever it shows, an Undo says *Undoing…* from the press, + Add's folder and paste and Finished's *Stop adding* mark
the window before their work starts. Paint only: the writer's order is the one `test_drag` / `test_services_moves`
prove.

What a wrong answer would cost a learner:
  * a move off Current (Goal, search, Needs you) that waits for a busy store with nothing saying so: pressed again;
  * a toast left saying *saving…* after the write landed, or one that never stood for a write saying it;
  * Ctrl+Z pressed with nothing visible until the undo lands — pressed again, undoing the change before it;
  * a folder chosen, a text pasted or *Stop adding* pressed, and the window looking as if nothing happened.
"""
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import add_menu, drag, strings
from app.qt import press as qpress
from tests.qt.conftest import wait_until
from tests.qt.test_add import world  # noqa: F401  (the window over test_drag's recording writer, its insert_at too)
from tests.qt.test_drag import _stones_sheet, settle  # noqa: F401  (the stones' sheet fixture)
from tests.qt.test_finished import fin  # noqa: F401  (Finished's window and writer)


class Paints(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.n = 0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.n += 1
        return False


def _toast_words(win):
    return win.toasts.card.message if win.toasts.alive else None


# --- a write's toast: *· saving…* while it waits, one rule wherever the toast shows --------------------------------- #
def test_a_writes_toast_off_current_reads_saving_while_it_waits_and_its_words_once_saved(world):
    # a write with no Current row (as Goal's ⋯, a search hit's ⤒, Needs you's answers give them): its toast is the only
    # mark — it says *saving…* once the write has waited 300 ms, and its own words again as it lands
    _seed, win, writer = world()
    text = strings.DRAG_UP_NEXT.format(title="星降る町の郵便屋")
    writer.stuck = True
    ticket = drag.Ticket(text, (), (101,))
    assert win.moves._give(ticket, lambda t: writer.move([101], "now", label=t)) is not None
    assert _toast_words(win) == text                                  # at the press, its own words
    settle(60)
    assert _toast_words(win) == text                                  # not before 300 ms: a quick save says nothing
    assert wait_until(lambda: _toast_words(win) == text + strings.TOAST_SAVING, 5)
    assert win.page_widgets["current"].list.saving == frozenset()     # (no Current row of its: the toast alone)
    writer.free()
    assert wait_until(lambda: _toast_words(win) == text, 5) and win.toasts.card.buttons
    assert not win.moves.tickets


def test_the_writer_saying_it_waits_marks_the_toast_at_once_and_a_toast_for_no_write_never(world):
    # the writer's own `on_saving` (a command already waiting: this one queues behind it) says it at once; a toast of
    # its own (a note, a later turn's) stands for no write and never says it
    _seed, win, writer = world()
    text = "雨の日の図書館 → Soon"
    writer.stuck = True
    win.moves._give(drag.Ticket(text, (), (102,)), lambda t: writer.move([102], "soon", label=t))
    win.moves._saving(True)
    assert _toast_words(win) == text + strings.TOAST_SAVING
    settle(30)                                                        # a later turn: this toast is no write's
    win.toasts.show(strings.NEEDS_KEPT)
    settle(400)
    assert _toast_words(win) == strings.NEEDS_KEPT
    writer.free()
    win.moves._saving(False)
    assert wait_until(lambda: not win.moves.tickets, 5)


def test_a_toast_shown_in_the_turn_writes_were_given_without_one_stands_for_them(world):
    # Needs you's *Link these · n*: n writes given without a toast, then one toast saying what they do — it waits with
    # them (the rule, not a copy of it in needs.py)
    _seed, win, writer = world()
    writer.stuck = True
    for i in (103, 104):
        win.moves._give(drag.Ticket("", (), (i,)), lambda t, i=i: writer.move([i], "now", label=t), toast=False)
    words = strings.NEEDS_LINKING.format(n=2)
    win.toasts.show(words)
    assert wait_until(lambda: _toast_words(win) == words + strings.TOAST_SAVING, 5)
    writer.free()
    assert wait_until(lambda: _toast_words(win) == words, 5)


def test_files_added_say_saving_while_they_copy(world, tmp_path):
    # + Add's *Files…* and Explorer's drop: the toast says *Added …* at once — and *saving…* while the copy runs
    _seed, win, writer = world()
    src = tmp_path / "第3話.ja.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nおはよう\n", encoding="utf-8")
    writer.stuck = True                                               # (the copy still running: nothing landed)
    assert win.adder.add_files([str(src)]) is not None
    text = win.moves.toasted.text
    assert _toast_words(win) == text
    assert wait_until(lambda: _toast_words(win) == text + strings.TOAST_SAVING, 5)
    writer.free()
    assert wait_until(lambda: _toast_words(win) == text, 5)


# --- Undo: *Undoing…* from the press until it lands ----------------------------------------------------------------- #
def _bar(win):
    paints = Paints(win.bar_line)
    QApplication.processEvents()
    return paints, paints.n


def test_ctrl_z_says_undoing_in_the_bar_painted_before_the_writer_is_asked_until_the_undo_lands(world):
    _seed, win, writer = world()
    win.moves._give(drag.Ticket("夜明けの港 → Soon", (), (105,)), lambda t: writer.move([105], "soon", label=t))
    assert wait_until(lambda: not win.moves.tickets and writer.saved, 5)
    paints, before = _bar(win)
    seen = []
    undo = writer.undo
    writer.undo = lambda change=None, label=None: (seen.append((win.bar_line.full(), paints.n - before,
                                                                win.bar_arc.isVisible())), undo(change, label))[1]
    win.moves.undo_key.activated.emit()                               # Ctrl+Z
    assert seen and seen[0][0] == strings.UNDOING and seen[0][1] >= 1 and seen[0][2]
    assert wait_until(lambda: not win.presses.any_live(), 5)          # the undo landed: the bar is its own again
    assert win.bar_line.full() != strings.UNDOING and not win.bar_arc.isVisible()


def test_an_undo_asked_before_its_change_is_saved_says_undoing_until_it_is_taken_back(world):
    # a busy store: the toast's Undo pressed while the move waits — the bar says so (never silent) until the change
    # lands and is taken back
    _seed, win, writer = world()
    writer.stuck = True
    ticket = drag.Ticket("風の通り道 → Goal", (), (106,))
    win.moves._give(ticket, lambda t: writer.move([106], "goal", label=t))
    win.toasts.card._press(0)                                         # its *Undo*
    assert ticket.undo_asked and writer.undone == []                  # (asked: undone as it lands, the order as was)
    assert win.bar_line.full() == strings.UNDOING and win.bar_arc.isVisible()
    settle(200)
    assert win.bar_line.full() == strings.UNDOING                     # still waiting, still said
    writer.free()
    assert wait_until(lambda: writer.undone and not win.presses.any_live(), 5)
    assert win.bar_line.full() != strings.UNDOING


def test_an_undo_whose_move_lands_as_nothing_stops_saying_undoing(world):
    _seed, win, writer = world()
    writer.stuck = True
    writer.nothing = {"move"}
    ticket = drag.Ticket("雪国の手紙 → Soon", (), (107,))
    win.moves._give(ticket, lambda t: writer.move([107], "soon", label=t))
    win.moves.undo_last()
    assert win.bar_line.full() == strings.UNDOING
    writer.free()
    assert wait_until(lambda: not win.presses.any_live(), 5) and writer.undone == []


# --- + Add: a folder and a paste mark the window from the press ------------------------------------------------------ #
class _Looks:
    """The looks' worker as + Add asks it (`add`, `busy`); whatever else the window tells it does nothing here."""

    def __init__(self, add):
        self.add = add

    def busy(self):
        return False

    def __getattr__(self, _name):
        return lambda *_a, **_k: None


def test_a_folder_read_where_it_is_turns_the_bars_arc_before_its_look_is_asked_until_it_answers(world, tmp_path,
                                                                                                 monkeypatch):
    _seed, win, _writer = world()
    folder = tmp_path / "夏祭りの夜"
    folder.mkdir()
    arc = win.bar_arc
    paints = Paints(arc)
    QApplication.processEvents()
    before, asked = paints.n, []

    def add(path, answer, first=False):
        asked.append((arc.isVisible(), arc.running, paints.n - before, answer))
        return True
    monkeypatch.setattr(win, "looks", _Looks(add), raising=False)
    assert win.adder.read_folder(str(folder)) is True
    shown, running, painted, answer = asked[0]
    assert shown and running and painted >= 1
    assert arc.isVisible()                                            # until its look answers …
    answer({"result": {"reachable": True, "added": 2}, "arrivals": True})
    assert wait_until(lambda: not arc.isVisible() and not win.presses.any_live(), 5)
    assert strings.SOURCES_READ_ARRIVALS.format(name="夏祭りの夜", added=2) == win.bar_line.full()


def test_a_folder_copied_in_turns_the_bars_arc_before_its_walk_starts(world, tmp_path, monkeypatch):
    _seed, win, _writer = world()
    folder = tmp_path / "海辺の町"
    folder.mkdir()
    monkeypatch.setattr(win, "looks", None, raising=False)            # no looks (a 2.x library): copied in
    handed = []
    monkeypatch.setattr(qpress.bridge, "run_in_worker", lambda fn, *a, then=None, failed=None, pool=None:
                        handed.append((fn, win.bar_arc.isVisible(), then)))
    win.adder.read_folder(str(folder))
    assert handed and handed[0][0] is add_menu.walk_folder and handed[0][1] is True
    handed[0][2]([])                                                  # nothing in it: said, the arc off
    assert not win.bar_arc.isVisible() and win.bar_line.full() == strings.ADD_NOTHING.format(name="海辺の町")


def test_the_paste_cards_add_says_adding_in_the_bar_before_its_file_is_written_until_its_toast(world, monkeypatch):
    _seed, win, writer = world()
    paints, before = _bar(win)
    handed = []
    monkeypatch.setattr(qpress.bridge, "run_in_worker", lambda fn, *a, then=None, failed=None, pool=None:
                        handed.append((fn, a, win.bar_line.full(), paints.n - before, then)))
    title, text = "台所の会話", "朝ごはんは何にする？\n昨日の味噌汁が残ってるよ。\n"
    win.adder._pasted(title, text)
    fn, args, words, painted, then = handed[0]
    assert fn is add_menu.write_pasted and words == strings.ADDING.format(name=title) and painted >= 1
    then(fn(*args))                                                   # written: added, its toast takes over
    assert win.bar_line.full() != strings.ADDING.format(name=title)
    assert win.moves.toasted.text == strings.DRAG_ADDED.format(name=title, n=1)


# --- Finished: *Stop adding* says *Stopping…* from the press until the import ends ---------------------------------- #
def test_stop_adding_turns_its_arc_and_says_stopping_before_the_job_is_asked_until_it_ends(fin):
    _seed, win, _writer, _estimator = fin()
    f = win.finished
    b = win.page_widgets["finished"].importer
    paints = Paints(b)
    QApplication.processEvents()
    before, cancels = paints.n, []
    job = SimpleNamespace(outcome="cancelled", ticket=drag.Ticket(""),
                          cancel=lambda: cancels.append((qpress.arc(b) is not None, win.bar_line.full(),
                                                         paints.n - before)))
    f.import_job = job
    f._show_importing(True)
    f.pick()                                                          # *Stop adding*
    has_arc, words, painted = cancels[0]
    assert has_arc and words == strings.FIN_IMPORT_STOPPING and painted >= 1
    f.pick()                                                          # again meanwhile: nothing more asked
    assert len(cancels) == 1
    f._imported(job)                                                  # the import ended
    assert qpress.arc(b) is None and not win.presses.any_live()
    assert win.bar_line.full() == strings.FIN_IMPORT_STOPPED and b.text() == strings.FIN_IMPORT


# --- the fix round: an undo answered with nothing, a switch, nothing moving ----------------------------------------- #
def _silent_undo(writer):
    """The real writer's answer to an undo that finds its stack empty: nothing (no undone, no note, no reread)."""
    def undo(change=None, label=None):
        writer.calls.append(("undo", [], {"change": change}))
        if change is None and not writer.saved:
            return len(writer.calls)
        if change is None:
            change = writer.saved.pop()
        writer.undone.append(change)
        import threading
        threading.Thread(target=writer.on_undone, args=(change, label), daemon=True).start()
        return len(writer.calls)
    writer.undo = undo
    writer.can_undo = lambda: bool(writer.saved)


def test_P4_A1_ctrl_z_answered_with_nothing_stops_saying_undoing_once_the_writer_is_idle(world):
    # a scan's command queued (no ticket of the window's), nothing to undo: Ctrl+Z goes to the writer, which answers
    # nothing — *Undoing…* ends once the writer is idle, never left turning
    _seed, win, writer = world()
    _silent_undo(writer)
    writer._waiting.append((None, None))                              # something of the writer's own, queued
    win.moves.undo_last()
    assert win.bar_line.full() == strings.UNDOING
    writer._waiting.clear()                                           # it landed (with no word for the window)
    assert wait_until(lambda: not win.presses.any_live(), 3)
    assert win.bar_line.full() != strings.UNDOING and not win.bar_arc.isVisible()


def test_P4_A1_ctrl_z_twice_on_one_change_stops_saying_undoing(world):
    _seed, win, writer = world()
    _silent_undo(writer)
    win.moves._give(drag.Ticket("夜明けの港 → Soon", (), (105,)), lambda t: writer.move([105], "soon", label=t))
    assert wait_until(lambda: not win.moves.tickets and writer.saved, 5)
    settle(theme.DRAG["settle-ms"] + 200)                              # the move's own settle has run out
    writer.can_undo = lambda: True                                    # (its stack read before the first undo ran)
    win.moves.undo_last()
    win.moves.undo_last()                                             # the second: its stack empty by then — no answer
    assert wait_until(lambda: not win.presses.any_live(), 3)
    assert win.bar_line.full() != strings.UNDOING


def test_P4_A2_stop_adding_ends_its_own_press_across_a_language_switch(fin, monkeypatch):
    _seed, win, _writer, _estimator = fin()
    f = win.finished
    cancels = []
    job = SimpleNamespace(outcome="cancelled", ticket=drag.Ticket(""), cancel=lambda: cancels.append(1))
    f.import_job = job
    f._show_importing(True)
    f.pick()
    monkeypatch.setattr(win, "language", "zh", raising=False)           # switched while it was stopping
    f._imported(job)
    assert not win.presses.any_live() and qpress.arc(win.page_widgets["finished"].importer) is None
    second = SimpleNamespace(outcome="cancelled", ticket=drag.Ticket(""), cancel=lambda: cancels.append(2))
    f.import_job = second                                              # the next import: Stop adding asks again
    f._show_importing(True)
    f.pick()
    assert cancels == [1, 2]
    f._imported(second)


def test_P4_A3_the_toasts_undo_never_moves_when_saving_shows_or_goes(world):
    _seed, win, writer = world()
    writer.stuck = True
    text = strings.DRAG_UP_NEXT.format(title="星降る町の郵便屋")
    win.moves._give(drag.Ticket(text, (), (101,)), lambda t: writer.move([101], "now", label=t))
    QApplication.processEvents()
    undo = win.toasts.card.buttons[0]
    at = lambda: (undo.mapTo(win, undo.rect().topLeft()), win.toasts.card.geometry())    # noqa: E731
    before = at()
    assert wait_until(lambda: win.toasts.saving, 5)
    QApplication.processEvents()
    assert at() == before, "the toast moved as *saving…* showed"
    writer.free()
    assert wait_until(lambda: not win.toasts.saving, 5)
    QApplication.processEvents()
    assert at() == before, "the toast moved as *saving…* went"


def test_P4_A5_a_long_message_keeps_its_saving_words_whole(world):
    _seed, win, writer = world()
    writer.stuck = True
    text = strings.DRAG_UP_NEXT.format(title="とても長い題名の物語" * 30)
    win.moves._give(drag.Ticket(text, (), (101,)), lambda t: writer.move([101], "now", label=t))
    assert wait_until(lambda: win.toasts.saving, 5)
    QApplication.processEvents()
    assert win.toasts.card.text.text().endswith(strings.TOAST_SAVING)
    writer.free()


def test_P4_A7_a_folder_pressed_again_while_its_look_runs_asks_nothing_more(world, tmp_path, monkeypatch):
    _seed, win, _writer = world()
    folder = tmp_path / "夏祭りの夜"
    folder.mkdir()
    asked = []
    monkeypatch.setattr(win, "looks", _Looks(lambda path, answer, first=False: asked.append(answer) or True),
                        raising=False)
    win.adder.read_folder(str(folder))
    win.adder.read_folder(str(folder))
    assert len(asked) == 1
    asked[0]({"result": {"reachable": True, "added": 0}})
    assert wait_until(lambda: not win.presses.any_live(), 5)
