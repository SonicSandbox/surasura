"""Every press reacts at once (round 8 row 45; the scope `row45-54-scope.md` §3, §3.7): `app/services/press.py`'s
states and `app/qt/press.py`'s paint — pending painted on the control before the work is handed to a worker.

What a wrong answer would cost a learner:
  * a button that does nothing visible until its work ends (Sonic's *Mark them known*), so it is pressed again;
  * a second press starting the work twice;
  * a failure that leaves the button greyed, or says nothing;
  * a menu's press (the menu closed) with no word anywhere until it ends.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from app.qt import press as qpress
from app.qt import strings
from app.services import press as service
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, open_window

MARK, MARK_TIP = strings.NEEDS_ACTIONS["mark_known"]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


# --- the states (Qt-free) ------------------------------------------------------------------------------------------ #
def test_a_press_goes_queued_waiting_running_stopping_and_done_then_idle_after_the_linger():
    clock = Clock()
    p = service.Press("needs:mark_known:known-offer:1", clock)
    seen = []
    p.subscribe(lambda q: seen.append((q.state, q.words)))
    assert p.state == service.IDLE and not p.live()
    assert p.press() is True and p.state == service.QUEUED and p.live()
    p.wait("Waiting for Anki…")
    assert (p.state, p.words) == (service.WAITING, "Waiting for Anki…")
    p.run("3/12")
    assert (p.state, p.words) == (service.RUNNING, "3/12")
    p.stopping()
    assert p.state == service.CANCELLING and p.live()
    p.done("2 words are known now")
    assert (p.state, p.words) == (service.DONE, "2 words are known now") and not p.live()
    clock.now += service.LINGER_S - 0.01
    assert p.state == service.DONE                      # the line lingers…
    clock.now += 0.02
    assert (p.state, p.words) == (service.IDLE, None)   # … then the press is idle again
    assert [s for s, _w in seen] == [service.QUEUED, service.WAITING, service.RUNNING, service.CANCELLING, service.DONE]


def test_a_second_press_while_live_is_ignored_and_the_first_stays():
    p = service.Press("k", Clock())
    assert p.press() is True
    p.run("1/40")
    assert p.press() is False
    assert (p.state, p.words) == (service.RUNNING, "1/40")


def test_a_failure_stays_until_the_next_press_and_an_answer_after_the_end_moves_nothing():
    clock = Clock()
    p = service.Press("k", clock)
    p.done("too early")                                  # no press yet: nothing moves
    assert p.state == service.IDLE
    p.press()
    p.failed("Your known words are being updated by Anki known-words sync.")
    clock.now += 60 * service.LINGER_S
    assert p.state == service.FAILED and p.words.startswith("Your known words")
    p.done("late")                                       # a late answer after the failure: still failed
    assert p.state == service.FAILED
    assert p.press() is True and p.state == service.QUEUED and p.words is None


def test_presses_by_key_say_whether_any_is_live_and_tell_every_change():
    presses = service.Presses(Clock())
    told = []
    presses.subscribe(lambda p: told.append((p.key, p.state)))
    a, b = presses.get("needs:mark_known:x"), presses.get("needs:leave_known:x")
    assert presses.get("needs:mark_known:x") is a and a is not b
    assert not presses.any_live()
    a.press()
    assert presses.any_live()
    a.done()
    assert not presses.any_live()
    assert told == [("needs:mark_known:x", service.QUEUED), ("needs:mark_known:x", service.DONE)]


# --- painted before the worker -------------------------------------------------------------------------------------- #
class Paints(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.n = 0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.n += 1
        return False


@pytest.fixture
def stage(qapp):
    host = QWidget()
    host.resize(520, 80)
    row = QHBoxLayout(host)
    b = QPushButton(MARK, host)
    b.setToolTip(MARK_TIP)
    b.setProperty("size", "sm")                         # as Needs you's card makes its answers
    qpress.room(b)
    row.addWidget(b)
    leave = QPushButton(strings.NEEDS_ACTIONS["leave_known"][0], host)
    leave.setToolTip(strings.NEEDS_ACTIONS["leave_known"][1])
    leave.setProperty("size", "sm")
    qpress.room(leave)
    row.addWidget(leave)
    row.addStretch(1)
    host.show()
    assert wait_until(lambda: b.isVisible() and b.width() > 10, 5)
    yield SimpleNamespace(host=host, button=b, leave=leave, paints=Paints(b))
    host.close()


@pytest.fixture(autouse=True)
def _own_presses(monkeypatch):
    """Each test's presses its own (a control with no window keeps them in the module)."""
    monkeypatch.setattr(qpress, "_loose", service.Presses())
    monkeypatch.setattr(qpress, "_painted", {})


@pytest.fixture
def handed(monkeypatch):
    """`bridge.run_in_worker` replaced: each hand-over recorded with what the control showed at that moment."""
    calls = _Calls()

    def stub(fn, *args, then=None, failed=None, pool=None):
        look = calls.look() if calls.look is not None else None
        calls.append(SimpleNamespace(fn=fn, args=args, then=then, failed=failed, look=look))
    monkeypatch.setattr(qpress.bridge, "run_in_worker", stub)
    return calls


class _Calls(list):
    look = None


def arc_shown(control):
    spinner = qpress.arc(control)
    return spinner is not None and spinner.isVisible() and spinner.running


def test_pending_is_the_arc_painted_on_the_button_before_the_work_is_handed_to_the_worker(stage, handed):
    # Sonic's Q1: never greyed, no words — a subtle accent arc on the control, there in the frame of the press.
    b, paints = stage.button, stage.paints
    QApplication.processEvents()
    before, left = paints.n, b.geometry().left()
    handed.look = lambda: (b.text(), b.isEnabled(), paints.n - before, arc_shown(b))
    answers = []
    p = qpress.run(b, "needs:mark_known:known-offer:1", lambda: ["一緒に", "やがる"], then=answers.append)
    assert len(handed) == 1
    text, enabled, painted, arc = handed[0].look
    assert text == MARK and enabled is True                # its words and its colours stay
    assert arc is True and painted >= 1                    # the arc, painted before the worker had it
    assert p.state == service.QUEUED and p.live()
    spinner = qpress.arc(b)
    assert spinner.geometry().right() < b.width() and spinner.geometry().left() > b.width() // 2   # its right edge
    assert b.geometry().left() == left                     # the button keeps its place
    # a second press while it works starts nothing, though the button is still enabled
    b.click()
    assert qpress.run(b, "needs:mark_known:known-offer:1", lambda: None) is None
    assert len(handed) == 1
    handed[0].then(handed[0].fn())
    assert answers == [["一緒に", "やがる"]] and p.state == service.DONE
    assert qpress.arc(b) is None and not spinner.isVisible() and b.text() == MARK and b.isEnabled()


def test_nothing_moves_while_the_arc_turns_not_the_button_its_words_or_its_neighbour(stage, handed):
    # The round 8 trial: P1's arc widened the button's right padding while it turned, so *Leave them* beside it slid
    # about 17 px. The button now keeps the arc's room at rest (`room`) and the arc turns in it, taking no space of the
    # layout's: the button, its neighbour and the words stay exactly where they were.
    b, leave = stage.button, stage.leave
    for scale_text in ("M", "L"):
        from app.qt import style
        style.apply(QApplication.instance(), style.current()[0], scale_text)
        stage.host.layout().activate()
        QApplication.processEvents()
        rest = (b.geometry(), leave.geometry(), b.sizeHint())
        handed.look = lambda: (b.geometry(), leave.geometry(), b.sizeHint())
        key = f"needs:mark_known:known-offer:{scale_text}"
        qpress.run(b, key, lambda: None)
        QApplication.processEvents()
        assert handed[-1].look == rest and (b.geometry(), leave.geometry(), b.sizeHint()) == rest, scale_text
        arc = qpress.arc(b).geometry()
        words_end = (b.width() + b.fontMetrics().horizontalAdvance(b.text())) / 2
        assert b.rect().contains(arc), (scale_text, arc, b.rect())                # inside the button …
        assert arc.left() > words_end, (scale_text, arc, words_end)                # … right of its words
        assert arc.width() == qpress.ARC
        handed[-1].then(None)
        assert (b.geometry(), leave.geometry()) == rest[:2]


def test_the_sheen_look_sets_the_button_in_and_sweeps_its_sheen_painted_before_the_worker_and_nothing_moves(
        stage, handed, monkeypatch):
    # Round 2 (Sonic: "the button acted as set or indented on click, and has the surasura sheen … that slowly moves
    # across like it's thinking"): `BUTTON_LOOK` "sheen" — the button set in (colours only) and the sheen over it, both
    # painted before the work is handed over; its words, its colours' kind (never greyed) and every place kept; all of
    # it gone when the work ends. Red first: the trial had only the arc.
    monkeypatch.setattr(qpress, "BUTTON_LOOK", "sheen")
    b, leave = stage.button, stage.leave
    QApplication.processEvents()
    rest = (b.geometry(), leave.geometry(), b.sizeHint())
    before = stage.paints.n
    handed.look = lambda: (qpress.mark(b), stage.paints.n - before, b.text(), b.isEnabled(), b.styleSheet())
    qpress.run(b, "needs:mark_known:known-offer:1", lambda: None)
    sheen, painted, text, enabled, own_style = handed[0].look
    assert sheen is not None and sheen.isVisible() and sheen.geometry() == b.rect() and qpress.arc(b) is None
    assert painted >= 1 and text == MARK and enabled and own_style == ""      # painted over it: never restyled
    img = QImage(sheen.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    sheen.render(img)
    assert sum(1 for x in range(0, img.width(), 3) if img.pixelColor(x, 3).alpha() > 0) > 10     # its top edge set in
    assert (b.geometry(), leave.geometry(), b.sizeHint()) == rest
    handed[0].then(None)
    assert qpress.mark(b) is None and not sheen.isVisible()
    assert (b.geometry(), leave.geometry()) == rest[:2]


def test_a_failure_takes_the_arc_off_and_keeps_the_reason(stage, handed):
    b = stage.button
    why = RuntimeError("Your known words are being updated by Anki known-words sync. Nothing was changed: try again "
                       "in a moment.")
    told = []
    p = qpress.run(b, "needs:mark_known:known-offer:1", lambda: None, failed=told.append, goes=True)
    assert arc_shown(b)
    handed[0].failed((why, "Traceback …"))
    assert told and told[0][0] is why
    assert p.state == service.FAILED and p.words is why
    assert qpress.arc(b) is None and b.isEnabled()
    assert qpress.run(b, "needs:mark_known:known-offer:1", lambda: None, goes=True) is not None   # pressed again


def test_a_button_whose_card_goes_ignores_a_press_in_the_moment_before_it_goes(stage, handed):
    b = stage.button
    key = "needs:leave_known:known-offer:1"
    qpress.run(b, key, lambda: None, goes=True)
    handed[0].then(None)
    assert qpress.arc(b) is None and b.isEnabled()
    assert qpress.run(b, key, lambda: None, goes=True) is None      # its card is going: not asked twice
    assert len(handed) == 1


def test_a_button_made_again_while_its_press_is_live_takes_the_arc(stage, handed):
    b = stage.button
    key = "needs:mark_known:known-offer:1"
    qpress.run(b, key, lambda: None, goes=True)
    again = QPushButton(MARK, stage.host)                # the card rebuilt (a sync ended meanwhile)
    again.setToolTip(MARK_TIP)
    stage.host.layout().insertWidget(0, again)
    again.show()
    b.setParent(None)
    b.deleteLater()
    assert qpress.adopt(again, key) is True
    assert arc_shown(again)
    assert qpress.adopt(QPushButton(MARK), "needs:leave_known:known-offer:1") is False     # no live press: untouched
    handed[0].failed((RuntimeError("Anki isn't open"), ""))
    assert qpress.arc(again) is None and again.isEnabled()


# --- a menu's press: the bar holds its words (the shell) ---------------------------------------------------------- #
@pytest.fixture
def window(qapp):
    seed = window_seed.build()
    win, services = open_window(qapp, seed, FakeWriter(seed.library))
    yield win
    win.close()
    services.shutdown(0.5)


def test_a_menu_press_holds_its_words_in_the_bar_and_runs_the_hairline_until_it_ends(window, handed):
    # A menu has closed as it was clicked: the hairline runs, and words given on purpose (a wait's reason) hold the bar.
    win = window
    paints = Paints(win.bar_line)
    QApplication.processEvents()
    before = paints.n
    handed.look = lambda: (win.bar_line.full(), win.bar_line.isVisible(), paints.n - before, win.progress.busy)
    p = qpress.run(None, "menu:find-videos", lambda: None, busy=strings.NEEDS_LOOKING, win=win)
    text, shown, painted, hairline = handed[0].look
    assert text == strings.NEEDS_LOOKING and shown and painted >= 1 and hairline is True
    win.say(strings.NEEDS_KNOWN_LEFT)                    # a line said meanwhile has its moment, then the held one is back
    assert win.bar_line.full() == strings.NEEDS_KNOWN_LEFT
    win._message_until = 0.0
    win._paint_slot()
    assert win.bar_line.full() == strings.NEEDS_LOOKING
    handed[0].then(None)
    assert p.state == service.DONE and not win.presses.any_live()
    assert win.bar_line.full() == getattr(win, "_status_line", "") and win.progress.busy is False


def test_a_menu_press_without_words_says_nothing_in_the_bar_but_runs_the_hairline(window, handed):
    win = window
    line = win.bar_line.full()
    qpress.run(None, "menu:open-logs", lambda: None, win=win)
    assert win.progress.busy is True and win.bar_line.full() == line
    handed[0].then(None)
    assert win.progress.busy is False
