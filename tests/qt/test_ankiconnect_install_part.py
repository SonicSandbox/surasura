"""*Install AnkiConnect for me*, on screen (3.0.1, spec §10 `tests/qt/`): the button in Mado-A's shared part
(`app/qt/addon_steps.AddonSteps`) — shown only where the install's look says it can; the sheet's *Back* does nothing;
the waiting line and its *Cancel*; the done line's *Open Anki* (Anki on Connect's profile, never Connect's kick); one
install state for every part on screen; *Copy code* always there under it. And the work it costs (S19, Sonic
2026-11-05: redraw waste caught at build time): one view painted per change, nothing painted for a press that changes
nothing. The route itself is `tests/connect/test_ankiconnect_install.py`'s: here it is a stand-in."""
import threading

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
    """`confirm.ask`'s stand-in: the asks it was given; `answer(yes)` answers the last one."""

    def __init__(self):
        self.asked = []

    def __call__(self, window, title, body, yes, yes_tip, **kw):
        self.asked.append((title, body, yes, kw.get("no"), kw["on_answer"]))

    def answer(self, yes):
        self.asked[-1][4](yes)


class Route:
    """`install_as_job`'s stand-in, on the part's own thread: it reports its phases and ends when told."""

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
    """Paint and layout events on a widget and its children (S19's eye)."""

    def __init__(self, root):
        super().__init__()
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


@pytest.fixture
def part(qapp, monkeypatch):
    """A host with the part (the install offered: `can-install`), its look a stand-in, the sheet a stand-in."""
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
                                       timer=QTimer())
        host.layout().addWidget(steps)
        made.append(steps)
        return steps
    host.show()
    yield type("P", (), {"make": staticmethod(make), "looks": looks, "asked": asked, "sheet": sheet,
                         "route": route, "checked": checked, "host": host})
    route.go.set()
    host.close()
    host.deleteLater()


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
    # S19: each phase the learner sees is one view painted; the same look again, or the same phase reported twice,
    # paints and lays out nothing
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


def test_a_custom_address_is_said_on_the_done_line(part, monkeypatch):
    part.route.go.set()
    steps = addon_steps.AddonSteps(lambda text, tip: _button(text, tip, part.host), "wizsub", None, part.host,
                                   url=lambda: "http://127.0.0.1:9999", checked=lambda: None, timer=QTimer())
    part.host.layout().addWidget(steps)
    steps.want(True)
    assert wait_until(lambda: steps.install is not None and steps.install.isVisible())
    steps.install.click()
    part.sheet.answer(True)
    assert wait_until(lambda: steps.install_line.text() == I.DONE_ELSEWHERE.format(url="http://127.0.0.1:9999"))


# --- in the three places (AC-5) ------------------------------------------------------------------------------------- #
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
