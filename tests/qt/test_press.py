"""Every press reacts at once (round 8 row 45; the scope `row45-54-scope.md` §3, §3.7): `app/services/press.py`'s
states and `app/qt/press.py`'s paint — pending painted on the control before the work is handed to a worker.

What a wrong answer would cost a learner:
  * a button that does nothing visible until its work ends (Sonic's *Mark them known*), so it is pressed again;
  * a second press starting the work twice;
  * a failure that leaves the button greyed, or says nothing;
  * a menu's press (the menu closed) with no word anywhere until it ends.
"""
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject, QRectF
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
        arc, box = qpress.arc(b).geometry(), qpress.arc_box(b)
        words_end = (b.width() + b.fontMetrics().horizontalAdvance(b.text())) / 2
        assert b.rect().contains(arc), (scale_text, arc, b.rect())                # inside the button …
        assert box.left() > words_end, (scale_text, box, words_end)                # … right of its words
        assert box.width() == qpress.ARC
        handed[-1].then(None)
        assert (b.geometry(), leave.geometry()) == rest[:2]


def _render(host, dpr):
    """`host` drawn as a screen at `dpr` draws it (its painters' device transforms at that ratio)."""
    img = QImage(round(host.width() * dpr), round(host.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(0xFF000000)
    host.render(img)
    return img


def _rows_cols(img, idle):
    """The device pixels that differ between two drawings: (min x, max x, min y, max y), or None."""
    xs, ys = [], []
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixel(x, y) != idle.pixel(x, y):
                xs.append(x)
                ys.append(y)
    return (min(xs), max(xs), min(ys), max(ys)) if xs else None


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_the_arc_is_centred_on_the_button_as_the_screen_draws_it_at_every_scale(qapp, handed, dpr):
    # Sonic, round 2: "it's not centered. It MUST be centered." A box's edges land on whole device pixels (half up) and
    # an antialiased arc lands anywhere, so an arc centred in logical px sat half a device pixel high or low at 150 %
    # and 225 % wherever the button's top fell on a half pixel. Measured, not computed: the button's drawn rows and the
    # arc's drawn ink, at each ratio and four places of the button. Its middle is the button's (to the pixel), and it
    # sits midway between the words' end and the right border. Red first: off by half a device pixel.
    host = QWidget()
    b = QPushButton(MARK, host)
    b.setProperty("size", "sm")
    qpress.room(b)
    b.resize(b.sizeHint())
    host.resize(b.width() + 24, 70)
    host.show()
    QApplication.processEvents()
    for k, y in enumerate((7, 8, 9, 10)):
        b.move(5 + k, y)
        QApplication.processEvents()
        idle = _render(host, dpr)
        p = qpress.begin(b, f"needs:mark_known:centre:{k}")
        QApplication.processEvents()
        on = _render(host, dpr)
        x0, x1, y0, y1 = _rows_cols(on, idle)
        mid_x = round((x0 + x1) / 2)
        bg = idle.pixel(1, 1)
        drawn = [yy for yy in range(idle.height()) if idle.pixel(mid_x, yy) != bg]       # the button's rows there
        button_mid, arc_mid = (drawn[0] + drawn[-1] + 1) / 2, (y0 + y1 + 1) / 2
        assert abs(arc_mid - button_mid) < 0.5, (dpr, y, arc_mid, button_mid)
        row = round((y0 + y1) / 2)
        border = next(xx for xx in range(x1 + 1, idle.width()) if idle.pixel(xx, row) != idle.pixel(x1 + 1, row))
        words_end = (b.x() + (b.width() + b.fontMetrics().horizontalAdvance(b.text())) / 2) * dpr
        left, right = x0 - words_end, border - (x1 + 1)                     # its air: to the words, to the border
        assert abs(left - right) <= 1.0, (dpr, left, right)
        assert right >= 1                                                   # never on the border
        qpress.end(p)
    host.close()


def test_the_arcs_room_is_no_more_than_the_arc_and_a_little_air(stage, handed):
    # Sonic, round 2: "The one thing i dislike is the space it takes up." The room a button keeps at rest for its arc
    # is the arc and about 2 px of air each side, never more — and never scaled with the text, as the arc isn't. Red
    # first: 22 px × the text size each side (~6 px of air each side at the default size, ~8 at the largest).
    from app.qt import style
    b = stage.button
    for scale_text in ("S", "M", "L"):
        style.apply(QApplication.instance(), style.current()[0], scale_text)
        stage.host.layout().activate()
        QApplication.processEvents()
        box = qpress.arc_box(b)
        words_end = (b.width() + b.fontMetrics().horizontalAdvance(b.text())) / 2
        assert box.width() == qpress.ARC
        assert 1 <= box.left() - words_end <= 3.5, (scale_text, box.left() - words_end)       # to the words
        assert 1 <= (b.width() - 1) - box.right() <= 3.5, (scale_text, (b.width() - 1) - box.right())  # to the border


def test_a_press_changes_no_pixel_but_the_arcs_the_words_and_the_neighbour_stay_put(stage, handed):
    # Nothing moves, to the pixel: pressed, only the arc's own box is drawn anew — the words, the button's left of
    # them and *Leave them* beside it are the same pixels as at rest. (At 150 % too: a half pixel moved would show.)
    b, leave = stage.button, stage.leave
    QApplication.processEvents()
    for dpr in (1.0, 1.5):
        idle = _render(stage.host, dpr)
        p = qpress.begin(b, f"needs:mark_known:still:{dpr}")
        QApplication.processEvents()
        on = _render(stage.host, dpr)
        x0, x1, y0, y1 = _rows_cols(on, idle)
        words_end = (b.x() + (b.width() + b.fontMetrics().horizontalAdvance(b.text())) / 2) * dpr
        assert x0 > words_end and x1 < (b.x() + b.width() - 1) * dpr, (dpr, x0, x1, words_end)
        assert x1 < leave.x() * dpr
        qpress.end(p)


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


# --- round 8's reviews: one card, one answer (A-5); an arc that can't be painted (A-10); the hairline's frame (R-2) - #
def test_a_cards_two_answers_are_one_press_the_other_asks_nothing_and_a_rebuilt_card_turns_the_pressed_one(
        stage, handed):
    """A-5: *Mark them known* and *Leave them* were two keys, so pressing the other answer while one worked ran both
    and the bar said both lines (*2 words are known now*, then *Left them*). One card is one answer at a time: the
    other button asks nothing, and a card rebuilt meanwhile puts the arc back on the button that was pressed."""
    b, leave = stage.button, stage.leave
    b.setProperty("action", "mark_known")
    leave.setProperty("action", "leave_known")
    key = "needs:ja:answer:known-offer:1"                         # (as `NeedsYou._press_key` makes it)
    qpress.run(b, key, lambda: ["一緒に", "やがる"], goes=True)
    assert qpress.run(leave, key, lambda: None, goes=True) is None and len(handed) == 1
    assert arc_shown(b) and qpress.arc(leave) is None
    again_leave, again_mark = QPushButton("Leave them", stage.host), QPushButton(MARK, stage.host)
    again_leave.setProperty("action", "leave_known")
    again_mark.setProperty("action", "mark_known")
    assert qpress.adopt(again_leave, key) is False                # not the one pressed
    assert qpress.adopt(again_mark, key) is True and qpress.arc(again_mark) is not None
    handed[0].then(handed[0].fn())
    assert qpress.arc(again_mark) is None


def test_the_needs_cards_answers_share_one_key_of_its_language():
    from app.qt import needs
    ny = needs.NeedsYou.__new__(needs.NeedsYou)
    ny.language = "zh"
    entry = SimpleNamespace(key="known-offer:40")
    assert ny._press_key("mark_known", entry) == ny._press_key("leave_known", entry) == "needs:zh:answer:known-offer:40"
    assert ny._press_key("find_videos", entry) == "needs:zh:find_videos:known-offer:40"


def test_an_arc_that_cant_be_painted_never_holds_the_press_the_work_still_starts_and_ends_it(stage, handed,
                                                                                               monkeypatch):
    """A-10: the press went live (the hairline on) before its arc was painted; a paint error escaped with the press
    still live, so every later press of it asked nothing. Now the work starts all the same, and its end ends it."""
    def broken(_control):
        raise RuntimeError("the button's style isn't ready")
    monkeypatch.setattr(qpress, "arc_rect", broken)
    p = qpress.run(stage.button, "needs:ja:answer:known-offer:1", lambda: None)
    assert p is not None and len(handed) == 1 and p.live()
    handed[0].then(None)
    assert p.state == service.DONE and not p.live() and qpress.arc(stage.button) is None


def test_a_menu_press_paints_the_hairline_in_the_frame_of_the_press_before_the_work(window, handed):
    """R-2: a menu's press (its menu closed) showed itself by the header's hairline alone — painted at the next frame,
    after the work was handed over, and the test checked its state, not a paint. Now the hairline is painted before
    the hand-over."""
    win = window
    paints = Paints(win.progress)
    QApplication.processEvents()
    assert win.progress.busy is False
    before = paints.n
    handed.look = lambda: (win.progress.busy, paints.n - before)
    qpress.run(None, "menu:open-logs", lambda: None, win=win)
    busy, painted = handed[0].look
    assert busy is True and painted >= 1
    handed[0].then(None)


# --- P3: the shared helpers — what a menu's press marks (IK-2), its reports, a job followed, another program -------- #
def test_a_menu_press_with_nothing_on_screen_turns_the_bars_arc_no_words_painted_before_the_work(window, handed):
    """IK-2: a menu's press whose thing isn't on screen shows the same accent arc in the bottom bar's slot, no words,
    painted (not merely shown) before the hand-over; it goes when the work ends, and the bar's words never changed."""
    win = window
    arc = win.bar_arc
    paints = Paints(arc)
    QApplication.processEvents()
    line, before = win.bar_line.full(), paints.n
    assert not arc.isVisible()                                   # at rest: nothing, no room
    handed.look = lambda: (arc.isVisible(), arc.running, paints.n - before, win.bar_line.full())
    p = qpress.run(None, "menu:open-guide", lambda: None, win=win)
    shown, running, painted, words = handed[0].look
    assert shown and running and painted >= 1 and words == line
    q = qpress.run(None, "menu:other", lambda: None, win=win)    # two at once: one arc, kept until both end
    handed[0].then(None)
    assert p.state == service.DONE and arc.isVisible()
    handed[1].then(None)
    assert q.state == service.DONE and not arc.isVisible() and not arc.running


def test_a_menu_press_on_a_file_turns_the_arc_on_its_line_at_its_part_painted_before_the_work(window, handed,
                                                                                                 monkeypatch):
    """IK-2: a menu's press on a file of the list marks that file's line where it was pressed from (its ⋯), painted
    on the list before the work is handed over — and not the bar's arc as well; off when the work ends."""
    from app.qt import rows
    win = window
    lst = win.page_widgets["current"].list
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
    ep = lst.model().entries[i][1].episodes[0]
    drawn = []
    real = rows.paint_marked
    monkeypatch.setattr(rows, "paint_marked", lambda p, rect, turning, **kw: (drawn.append(QRectF(rect)),
                                                                             real(p, rect, turning, **kw)))
    handed.look = lambda: (dict(lst.marked), len(drawn), win.bar_arc.isVisible())
    p = qpress.run(None, ("open-folder", ep.id), lambda: None, win=win, at=qpress.row_mark(lst, [ep.id]))
    marked, painted, bar = handed[0].look
    assert marked == {ep.id: "more"} and painted >= 1 and bar is False
    more = next(r for name, r, *_rest in lst.itemDelegate().line_geometry(
        lst.model().entries[i][1], lst.itemDelegate().slab_of(lst.visualRect(lst.model().index(i, 0))))["hover"]
        if name == "more")
    assert QRectF(more) in drawn                                     # at its ⋯
    handed[0].then(None)
    assert p.state == service.DONE and lst.marked == {} and lst._turn is None


def test_a_widget_mark_turns_the_arc_over_the_widget_painted_before_the_work(stage, handed):
    host = stage.host
    paints = Paints(host)
    QApplication.processEvents()
    before = paints.n

    def spinners():
        from app.qt import motion
        return [s for s in host.findChildren(motion.Spinner) if s.isVisible() and s.running]
    handed.look = lambda: (len(spinners()), paints.n - before)
    qpress.run(None, "cover:fetch:1", lambda: None, at=qpress.widget_mark(host))
    count, painted = handed[0].look
    assert count == 1 and painted >= 1
    s = spinners()[0]
    assert abs(s.geometry().center().x() - host.rect().center().x()) <= 1      # over its middle
    handed[0].then(None)
    assert spinners() == []


def test_a_workers_report_moves_the_press_and_holds_a_named_wait_in_the_bar(window, handed):
    win = window
    p = qpress.run(None, "needs:ja:answer:x", lambda: None, busy="Marking…", win=win)
    r = qpress.relay(p, win)
    r.call(("wait", "Waiting for Anki…"))
    assert wait_until(lambda: p.state == service.WAITING, 5)
    assert win.bar_line.full() == "Waiting for Anki…"
    r.call(("run", "3 / 12"))
    assert wait_until(lambda: p.state == service.RUNNING, 5)
    assert win.bar_line.full() == "Marking… · 3 / 12"
    handed[0].then(None)
    assert p.state == service.DONE and win.bar_line.full() == getattr(win, "_status_line", "")
    r.call(("wait", "late"))                                   # after the end: nothing moves
    QApplication.processEvents()
    assert p.state == service.DONE


class _Registry:
    def __init__(self):
        self.views = ()

    def snapshot(self):
        return self.views


def _job(state, reason=None, message=None, progress=None, job_id=7):
    from app.services import jobs
    return jobs.JobView(job_id, "sync", "Syncing your known words", state, reason, message, progress, None, None,
                        False, "cancel", False, False, None)


def test_follow_maps_a_jobs_queued_waiting_running_cancelling_done_and_failed_onto_the_press(window):
    from app.services import jobs
    win, reg = window, _Registry()
    reg.views = (_job(jobs.QUEUED),)
    p = qpress.begin(None, "known:sync:test", win=win)
    qpress.follow(p, reg, 7, win=win)
    assert p.state == service.QUEUED
    for view, state in ((_job(jobs.WAITING, reason="waits for Generate"), service.WAITING),
                        (_job(jobs.RUNNING, progress=jobs.Progress("Reading", 3, 12)), service.RUNNING),
                        (_job(jobs.CANCELLING), service.CANCELLING)):
        win.bridge.jobs_changed.emit((view,))
        assert p.state == state
    assert p.words is None and win.bar_line.full() != "waits for Generate"
    win.bridge.jobs_changed.emit((_job(jobs.DONE),))
    assert p.state == service.DONE and not win.bar_arc.isVisible()
    q = qpress.begin(None, "known:sync:test2", win=win)
    reg.views = (_job(jobs.RUNNING, job_id=8),)
    qpress.follow(q, reg, 8, win=win)
    win.bridge.jobs_changed.emit((_job(jobs.WAITING, reason="waits for Generate", job_id=8),))
    assert q.state == service.WAITING and win.bar_line.full() == "waits for Generate"
    win.bridge.jobs_changed.emit((_job(jobs.FAILED, message="Anki isn't open", job_id=8),))
    assert (q.state, q.words) == (service.FAILED, "Anki isn't open")
    r = qpress.begin(None, "known:sync:test3", win=win)
    reg.views = (_job(jobs.RUNNING, job_id=9),)
    qpress.follow(r, reg, 9, win=win)
    win.bridge.jobs_changed.emit(())                          # let go between two snapshots: it ended
    assert r.state == service.DONE


def test_open_marks_first_and_opens_on_a_worker_never_on_the_windows_thread(window, monkeypatch):
    """The O and X classes: the press is painted (the bar's arc) before the open, and the open itself — a link
    through `windows.open_url`, a file through `screens.open_with_system` — runs on a worker thread."""
    import threading
    from app.qt import screens, windows
    win = window
    gui = threading.current_thread()
    seen = []
    monkeypatch.setattr(windows, "open_url", lambda url: seen.append(("url", url, threading.current_thread(),
                                                                       win.bar_arc.isVisible())) or True)
    monkeypatch.setattr(screens, "open_with_system", lambda path: seen.append(("file", path,
                                                                               threading.current_thread(), None)))
    opened = []
    p = qpress.open(win, "https://example.org/guide", then=opened.append)
    assert p is not None and win.bar_arc.isVisible()
    assert qpress.open(win, "https://example.org/guide") is None             # a second press while live: nothing
    assert wait_until(lambda: opened, 5)
    assert seen[0][:2] == ("url", "https://example.org/guide") and seen[0][2] is not gui and seen[0][3] is True
    assert p.state == service.DONE and not win.bar_arc.isVisible()
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "第01話.mkv")
    qpress.open(win, lambda: path, key="play:1", then=opened.append)
    assert wait_until(lambda: len(opened) == 2, 5)
    assert seen[1][:2] == ("file", path) and seen[1][2] is not gui


def test_open_that_fails_says_why_in_the_bar_and_nothing_to_open_ends_quietly(window, monkeypatch):
    from app.qt import screens
    win = window

    def refused(path):
        raise OSError("No application is associated with the specified file")
    monkeypatch.setattr(screens, "open_with_system", refused)
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "第02話.mkv")
    p = qpress.open(win, path)
    assert wait_until(lambda: p.state == service.FAILED, 5)
    assert win.bar_line.full() == strings.OPEN_FAILED.format(name="第02話.mkv", why=p.words)
    told = []
    q = qpress.open(win, lambda: None, key="open:none", then=told.append)
    assert wait_until(lambda: told, 5) and told == [None] and q.state == service.DONE


def test_open_url_on_a_worker_sets_up_com_around_the_systems_opener(qapp, monkeypatch):
    """`windows.open_url` from a pool thread (as `press.open` calls it): COM set up before QDesktopServices is asked
    and undone after, on that thread (the harness's open guard stands in for QDesktopServices: no test opens one)."""
    import threading
    from app.qt import windows
    calls = []

    class Ole32:
        def CoInitializeEx(self, _reserved, flags):
            calls.append(("init", flags, threading.current_thread()))
            return 0

        def CoUninitialize(self):
            calls.append(("uninit", threading.current_thread()))

    class Desktop:
        @staticmethod
        def openUrl(url):
            calls.append(("open", url.toString(), threading.current_thread()))
            return True
    monkeypatch.setattr(windows, "_ole32", lambda: Ole32())
    monkeypatch.setattr(windows, "QDesktopServices", Desktop)
    got = []
    t = threading.Thread(target=lambda: got.append(windows.open_url("https://example.org/guide")))
    t.start()
    t.join(10)
    assert got == [True]
    if os.name == "nt":
        assert [c[0] for c in calls] == ["init", "open", "uninit"] and calls[0][1] == 0x6
    assert all(c[-1] is t for c in calls) and calls[[c[0] for c in calls].index("open")][1] == \
        "https://example.org/guide"


def test_a_secondary_windows_status_line_is_its_bar_held_words_and_its_corner_arc(qapp, handed):
    from app.qt import windows
    shell_ = QWidget()
    w = windows.SecondaryWindow(shell_, "Frequency lists")
    w.resize(420, 200)
    w.show()
    QApplication.processEvents()
    w.say("3 lists")
    p = qpress.run(None, "lists:add", lambda: None, busy="Adding…", win=w)
    assert w.status.text() == "Adding…" and w.bar_arc.isVisible() and w.bar_arc.running
    assert p in [w.presses.find("lists:add")] and w.presses.any_live()
    arc = w.bar_arc.geometry()
    assert w.rect().contains(arc) and arc.right() > w.width() - 16 and arc.bottom() > w.height() - 16   # its corner
    w.say("Added 1 list")                                       # said meanwhile: shown, and the one left after
    handed[0].then(None)
    assert w.status.text() == "Added 1 list" and not w.bar_arc.isVisible()
    w.close()
    shell_.close()
