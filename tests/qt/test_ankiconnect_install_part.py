import contextlib
import threading
import types

import pytest
from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from app import ankiconnect_addon as A
from app.connect import ankiconnect_install as I
from app.connect import open_anki
from app.qt import addon_steps, confirm
from tests.qt.conftest import wait_until
from tests.qt.test_wizard import make  # noqa: F401  (the wizard over a stand-in main window: a fixture)

URL = "http://127.0.0.1:8765"


def _button(text, tip, parent):
    b = QPushButton(text, parent)
    b.setToolTip(tip)
    return b


class Sheet:
    pass

    def __init__(self):
        self.asked = []

    def __call__(self, window, title, body, yes, yes_tip, **kw):
        self.asked.append((title, body, yes, kw.get("no"), kw["on_answer"]))

    def answer(self, yes):
        self.asked[-1][4](yes)


class Route:
    pass

    def __init__(self):
        self.calls, self.go, self.result = [], threading.Event(), I.INSTALLED
        self.cancel = self.on_phase = self.shown = None

    def __call__(self, registry, on_progress, cancel, on_end, confirm=None, shown=None, on_phase=None, **kw):
        self.calls.append((registry, threading.current_thread() is threading.main_thread(), confirm()))
        self.cancel, self.on_phase, self.shown = cancel, on_phase, shown
        while not self.go.wait(0.01):
            if cancel.is_set():
                self.result = I.CANCELLED
                break
        on_end(self.result)
        return self.result


class Counter(QObject):
    pass

    def __init__(self, root):
        super().__init__(root)                         # the root owns it: never a filter left dangling
        self.paints = self.layouts = 0
        self.where = []
        for w in [root] + root.findChildren(QWidget):
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.paints += 1
        elif event.type() == QEvent.Type.LayoutRequest and not isinstance(obj, QPushButton):
            self.layouts += 1                          # the part's own layouts (a pressed button's arc is the press's)
            self.where.append(type(obj).__name__ + ":" + obj.objectName())
        return False


def _install_threads():
    return [t for t in threading.enumerate() if t.name == "ankiconnect-install" and t.is_alive()]


@contextlib.contextmanager
def _part(monkeypatch, qt_timer):
    pass
    monkeypatch.setattr(addon_steps, "_STATE", None)     # a fresh install state per test
    looks = {"state": I.CAN_INSTALL, "disabled": False, "base": "B", "point": 260902}
    asked = []
    monkeypatch.setattr(I, "look", lambda: asked.append(1) or dict(looks))
    sheet = Sheet()
    monkeypatch.setattr(confirm, "ask", sheet)
    route = Route()
    monkeypatch.setattr(I, "install_as_job", route)
    checked = []
    host = QWidget()
    QVBoxLayout(host)
    host.resize(700, 200)
    made = []

    def make(url=True):
        steps = addon_steps.AddonSteps(lambda text, tip: _button(text, tip, host), "wizsub", None, host,
                                       url=(lambda: URL) if url else None, checked=lambda: checked.append(1),
                                       timer=qt_timer())
        host.layout().addWidget(steps)
        made.append(steps)
        return steps
    host.show()
    got = types.SimpleNamespace(make=make, looks=looks, asked=asked, sheet=sheet, route=route, checked=checked,
                                host=host)
    try:
        yield got
    finally:
        _let_go(got)


def _let_go(got):
    got.route.go.set()
    _end(got.host)


def _end(host):
    pass
    from PyQt6 import sip
    for thread in _install_threads():
        thread.join(5)
    st = addon_steps._STATE
    if st is not None and not sip.isdeleted(st):
        wait_until(lambda: sip.isdeleted(st) or (not st.looking and st.phase not in (addon_steps.RUNNING,
                                                                                     addon_steps.WAITING)))
    for _ in range(3):
        QApplication.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    if not sip.isdeleted(host):
        host.close()
        sip.delete(host)
    if st is not None and not sip.isdeleted(st):
        sip.delete(st)


@pytest.fixture
def part(qapp, monkeypatch, qt_timer):
    with _part(monkeypatch, qt_timer) as got:
        yield got


def _settle():
    for _ in range(5):
        QApplication.processEvents()


def test_the_button_shows_only_where_the_install_can_with_copy_code_always_under_it(part):
    steps = part.make()
    assert steps.isHidden() and steps.install is None             # not wanted: nothing, no look
    assert part.asked == []
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    assert steps.heading.isVisible() and steps.heading.text() == I.OR_YOURSELF
    assert steps.copy.isVisible() and steps.line.text() == A.steps_line()
    assert steps.install.toolTip() == I.BUTTON_TIP
    for state, line in ((I.THERE, I.THERE_LINE), (I.NO_BASE, None), (I.NO_VERSION, None), (I.OFF, None)):
        part.looks["state"] = state
        steps.want(False)
        steps.want(True)                                  # wanted anew: looked again
        assert wait_until(lambda: addon_steps.state().found["state"] == state)
        _settle()
        assert steps.install.isHidden() and steps.heading.isHidden() and steps.copy.isVisible()
        assert steps.install_line.isVisible() == (line is not None)
        if line:
            assert steps.install_line.text() == line
    part.looks.update(state=I.THERE, disabled=True)
    steps.want(False)
    steps.want(True)
    assert wait_until(lambda: steps.install_line.text() == I.TURNED_OFF_LINE)


def test_a_part_without_an_address_is_3_0s_copy_code_only(part):
    steps = part.make(url=False)
    steps.want(True)
    _settle()
    assert steps.isVisible() and steps.install is None and steps.heading.isHidden() and part.asked == []
    assert [b.text() for b in steps.findChildren(QPushButton)] == [A.COPY]


def test_the_sheets_back_does_nothing_and_paints_nothing(part):
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    _settle()
    count, paints = Counter(steps), steps.paints
    steps.install.click()
    title, body, yes, no, _ = part.sheet.asked[0]
    assert (title, body, yes, no) == (I.SHEET_TITLE, I.SHEET_BODY, I.SHEET_YES, I.SHEET_NO)
    assert addon_steps.state().phase == addon_steps.ASKING
    part.sheet.answer(False)
    _settle()
    assert part.route.calls == [] and addon_steps.state().phase is None      # nothing fetched, nothing started
    assert steps.paints == paints                         # the view never changed: never painted again
    assert count.layouts == 0, count.where                # nothing laid out again
    assert steps.install.isVisible()


def test_yes_runs_the_route_off_the_windows_thread_and_the_waiting_line_has_cancel(part):
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: part.route.calls)
    assert part.route.calls[0][1:] == (False, True)        # a thread of its own, the yes already given
    assert wait_until(lambda: steps.install_line.text() == I.RUNNING_LINE)
    assert steps.install.isHidden()
    part.route.on_phase(I.WAITING)                         # Anki is open
    assert wait_until(lambda: steps.install_line.text() == I.WAITING_LINE and steps.cancel_btn.isVisible())
    assert part.route.shown()                              # on screen: the route may look at the process list
    steps.hide()
    assert not part.route.shown()                          # off screen: it looks at nothing
    steps.show()
    assert part.route.shown()
    steps.cancel_btn.click()
    assert wait_until(lambda: addon_steps.state().phase is None)
    assert part.route.result == I.CANCELLED
    assert wait_until(lambda: steps.install.isVisible() and steps.install_line.isHidden())


def test_a_failure_says_why_and_offers_it_again(part):
    part.route.result = I.OFFLINE
    part.route.go.set()
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: addon_steps.state().phase == addon_steps.FAILED)
    _settle()
    assert steps.install_line.text() == "Couldn't install it for you: couldn't reach AnkiWeb."
    assert steps.install.isVisible() and steps.copy.isVisible() and steps.heading.isVisible()


def test_a_part_with_a_press_under_way_stays_on_screen_though_its_host_no_longer_wants_the_steps(part):
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: addon_steps.holding())
    steps.want(False)                                      # Anki closed to let it go: the host's steps go
    _settle()
    assert steps.isVisible() and steps.steps_row.isHidden() and steps.install_line.text() == I.RUNNING_LINE
    other = part.make()                                    # a part built meanwhile (Needs you's card, rebuilt)
    _settle()
    assert other.isVisible() and other.install_line.text() == I.RUNNING_LINE
    part.route.go.set()
    assert wait_until(lambda: steps.install_line.text() == I.DONE_LINE and other.install_line.text() == I.DONE_LINE)
    assert steps.open_btn.isVisible() and other.open_btn.isVisible()
    addon_steps.answered()                                 # a host's look: AnkiConnect answers
    _settle()
    assert steps.isHidden() and other.isHidden()


def test_the_done_lines_open_anki_starts_anki_on_connects_profile_and_never_connects_kick(part, monkeypatch):
    started, kicked = [], []
    from app.connect import kick, setup
    monkeypatch.setattr(open_anki, "running", lambda: False)
    monkeypatch.setattr(open_anki, "start", lambda profile=None: started.append(profile) or object())
    monkeypatch.setattr(setup, "anki_profile", lambda: "DevTest")
    monkeypatch.setattr(kick, "kick", lambda *a, **k: kicked.append(a))
    monkeypatch.setattr(open_anki, "kick_when_open", lambda *a, **k: kicked.append(a))
    part.route.go.set()
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: steps.open_btn is not None and steps.open_btn.isVisible())
    steps.open_btn.click()
    assert wait_until(lambda: started == ["DevTest"])
    for _ in range(20):
        _settle()
    assert kicked == []                                    # AC-4 A: the learner's press opens Anki, and only that


def test_the_done_lines_watch_checks_again_once_ankiconnect_answers(part, monkeypatch):
    monkeypatch.setattr(A, "EVERY", 0.0)
    monkeypatch.setattr(A, "answers", lambda url, seen=None: True)
    part.route.go.set()
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: addon_steps.state().phase == addon_steps.INSTALLED)
    assert steps.done_watch.armed
    steps.done_watch._timer.timeout.emit()
    assert wait_until(lambda: part.checked == [1])
    assert addon_steps.state().phase is None


def test_work_one_view_painted_per_change_and_none_for_an_answer_that_changes_nothing(part):
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    _settle()
    paints = steps.paints
    count = Counter(steps)
    addon_steps.state().set(found=dict(part.looks))        # the same look answered again
    steps.want(True)                                       # wanted again, still wanted: no new look
    _settle()
    assert steps.paints == paints and count.paints == 0 and count.layouts == 0
    assert len(part.asked) == 1
    steps.install.click()                                  # the press: its arc only (the view is the same)
    assert steps.paints == paints
    part.sheet.answer(True)
    assert wait_until(lambda: steps.install_line.text() == I.RUNNING_LINE)
    assert steps.paints == paints + 1
    part.route.on_phase(I.WAITING)
    part.route.on_phase(I.WAITING)                         # said twice: painted once
    assert wait_until(lambda: steps.install_line.text() == I.WAITING_LINE)
    _settle()
    assert steps.paints == paints + 2
    part.route.on_phase(I.RUNNING)
    part.route.go.set()
    assert wait_until(lambda: steps.install_line.text() == I.DONE_LINE)
    _settle()
    assert steps.paints == paints + 4                      # running, waiting, running, installed: four views


def test_a_custom_address_is_said_on_the_done_line(part, monkeypatch, qt_timer):
    part.route.go.set()
    steps = addon_steps.AddonSteps(lambda text, tip: _button(text, tip, part.host), "wizsub", None, part.host,
                                   url=lambda: "http://127.0.0.1:9999", checked=lambda: None, timer=qt_timer())
    part.host.layout().addWidget(steps)
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: steps.install_line.text() == I.DONE_ELSEWHERE.format(url="http://127.0.0.1:9999"))


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_setups_anki_step_offers_it_first_in_japanese_and_chinese(make, monkeypatch, language):
    from tests.qt.test_wizard import FakeApi
    monkeypatch.setattr(addon_steps, "_STATE", None)
    monkeypatch.setattr(I, "look", lambda: {"state": I.CAN_INSTALL, "disabled": False, "base": "B", "point": 1})
    api = FakeApi(anki={"open": False, "say": None, "decks": [], "preselected": [], "running": True})
    wiz, _shell, api, _settings, _m = make(api=api)
    wiz.page.channel.choose(language)
    wiz.next()
    steps = wiz.page.closed_steps
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    assert steps.copy.isVisible() and steps.heading.isVisible()
    assert wiz.language == language


def test_a_sheet_dropped_unanswered_puts_the_part_back(part, monkeypatch):
    cards = []

    def ask(window, *a, **kw):
        card = QObject()
        cards.append(card)
        return card
    monkeypatch.setattr(confirm, "ask", ask)
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    assert addon_steps.state().phase == addon_steps.ASKING
    from PyQt6.QtCore import QCoreApplication
    cards[0].deleteLater()                                 # the card's own end (`Confirm._answer(drop=True)`)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert wait_until(lambda: addon_steps.state().phase is None)
    assert part.route.calls == [] and steps.install.isVisible()


def test_a_look_that_cant_tell_whether_anki_runs_offers_no_button(part):
    steps = part.make()
    steps.set_unsure(True)
    steps.want(True)
    assert wait_until(lambda: addon_steps.state().found is not None)
    _settle()
    assert steps.install is None and steps.copy.isVisible() and steps.heading.isHidden()
    steps.set_unsure(False)
    assert steps.install is not None and steps.install.isVisible()


def test_needs_you_wakes_no_connect_when_anki_answers_after_the_done_lines_open_anki(part, monkeypatch):
    from app.connect import setup
    monkeypatch.setattr(open_anki, "running", lambda: True)              # already open: nothing started
    monkeypatch.setattr(setup, "anki_profile", lambda: None)
    assert addon_steps.quiet_open() is False
    part.route.go.set()
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: steps.open_btn is not None and steps.open_btn.isVisible())
    steps.open_btn.click()
    assert addon_steps.quiet_open() is True and addon_steps.quiet_open() is False      # once


def test_the_route_may_look_while_its_job_is_in_a_shown_windows_bar(part):
    import weakref
    st = addon_steps.state()
    steps = part.make()
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: part.route.shown is not None)
    st.bar = weakref.ref(part.host)
    steps.setParent(None)                                  # its line off screen (the host's tab changed)
    st.update_shown()
    assert part.route.shown()                              # the bar's window is shown
    part.host.showMinimized()
    assert wait_until(lambda: not part.route.shown(), 3)
    part.host.showNormal()
    assert wait_until(lambda: part.route.shown(), 3)
    steps.deleteLater()


def test_the_real_route_under_the_real_part_installs_once_anki_closes(qapp, tmp_path, monkeypatch):
    import json
    import os
    import types
    from tests.connect import test_ankiconnect_install as T
    monkeypatch.setattr(addon_steps, "_STATE", None)
    base = tmp_path / "Anki2"
    (base / "addons21").mkdir(parents=True)
    T._prefs(str(base), {"last_run_version": T.POINT})
    monkeypatch.setenv("ANKI_BASE", str(base))
    monkeypatch.setattr(I, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(I, "WAIT_EVERY", 0.05)
    net = T.Net()
    monkeypatch.setattr(I, "_fetch", net)
    anki_open = {"now": True}
    looks = []
    monkeypatch.setattr(open_anki, "running", lambda: looks.append(1) or anki_open["now"])
    sheet = Sheet()
    monkeypatch.setattr(confirm, "ask", sheet)
    host = QWidget()
    QVBoxLayout(host)
    steps = addon_steps.AddonSteps(lambda text, tip: _button(text, tip, host), "wizsub", None, host, url=lambda: URL,
                                   checked=lambda: None, timer=QTimer(host))
    host.layout().addWidget(steps)
    host.show()
    try:
        steps.want(True)
        assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
        steps.install.click()
        sheet.answer(True)
        assert wait_until(lambda: steps.install_line.text() == I.WAITING_LINE, 5)
        assert net.asked == [] and looks
        anki_open["now"] = False                           # the learner closes Anki
        assert wait_until(lambda: steps.install_line.text() == I.DONE_LINE, 10)
        assert net.asked == [T.URL]
        with open(os.path.join(str(base), "addons21", I.CODE, "meta.json"), encoding="utf-8") as f:
            assert json.load(f) == T.META
        assert not os.path.exists(os.path.join(str(base), I.ANKI_STAGING))
    finally:
        _end(host)
#xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
