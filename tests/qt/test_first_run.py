"""The first run (W3.5 part 3; the W3.5 RUNBOOK's proof `tests/qt/test_first_run.py`; the window's spec 05 §5.8).

What a wrong answer would cost: a clean profile that opens on an empty window with no way to set up; a finished setup
that opens the wizard at every start; *Finish later* that marks setup done (the wizard never offered again); *Set up
again* that forgets the user's own choices; a wizard that leaves the window's tabs taking the keyboard under it, or that
Esc (or the mouse's Back button) closes — or that closes the main window.

On the real main window (`shell.open_window` on a temp test root), the wizard's rules through the contract's stand-in
(`tests/qt/test_wizard.py`'s `FakeApi`); `should_open` on a clean profile also through the real
`app/services/setup_wizard.py` when it is there.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.qt import first_run, shell
from app.qt import wizard as W
from tests.qt.conftest import wait_until
from tests.qt.test_wizard import FakeApi, FakeMiner, miner_look


@pytest.fixture
def window(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.resize(1280, 800)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()
    services.shutdown(0.5)


def _host(win, api=None):
    return first_run.host(win, api=api or FakeApi(), miner=FakeMiner(miner_look("missing")))


def test_a_clean_profile_opens_the_wizard_over_the_whole_central_area(window):
    assert "onboarding_completed" not in window.services.settings.get() or \
        window.services.settings.get().get("onboarding_completed") is not True
    wiz = _host(window)
    assert isinstance(wiz, W.SetupWizard) and wiz.isVisible()
    assert wiz.geometry() == window.centralWidget().rect()
    assert first_run.opened(window) is wiz
    for part in (window.header, window.pages, window.footer):
        assert not part.isEnabled()                              # nothing under it takes the keyboard
    window.resize(1100, 700)
    QApplication.processEvents()
    assert wiz.geometry() == window.centralWidget().rect()       # it follows the window's size


def test_a_clean_profile_opens_it_by_the_real_rule_too(window):
    real = pytest.importorskip("app.services.setup_wizard")
    assert real.should_open(dict(window.services.settings.get())) is True


def test_with_setup_finished_no_wizard_opens(window):
    window.services.settings.set({"onboarding_completed": True})
    assert _host(window) is None
    assert first_run.opened(window) is None and window.header.isEnabled()


def test_a_wizard_that_cant_open_leaves_the_window_as_it_is(window):
    class Broken(FakeApi):
        def should_open(self, settings):
            raise OSError("settings.json is held")
    assert _host(window, Broken()) is None
    assert window.header.isEnabled() and window.pages.isEnabled()


def test_finish_later_closes_onto_current_and_never_finishes_setup(window):
    wiz = _host(window)
    wiz.next()                                                   # page 1 saved
    QTest.mouseClick(wiz.btn_later, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert first_run.opened(window) is None
    assert window.current_tab() == "current"
    assert window.header.isEnabled() and window.pages.isEnabled() and window.footer.isEnabled()
    settings = window.services.settings.get()
    assert settings.get("target_language") == "ja"               # what Next saved is kept
    assert settings.get("onboarding_completed") is not True      # Finish later never writes it


def test_set_up_again_opens_it_preselected_from_the_settings_even_when_finished(window):
    window.services.settings.set({"onboarding_completed": True, "target_language": "zh"})
    wiz = first_run.open_again(window, api=FakeApi(), miner=FakeMiner(miner_look("missing")))
    assert wiz is not None and wiz.isVisible()
    assert wiz.pages[0].channel.value() == "zh"
    assert first_run.open_again(window, api=FakeApi()) is wiz    # one at a time


def test_esc_and_the_mouse_back_button_never_close_the_wizard_or_the_window(window):
    wiz = _host(window)
    wiz.next()
    page = wiz.index
    target = wiz.focusWidget() or wiz
    QTest.keyClick(target, Qt.Key.Key_Escape)
    back = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10), Qt.MouseButton.BackButton,
                       Qt.MouseButton.BackButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(wiz.btn_next, back)                   # through the shell's EscapeRouter (an app filter)
    QApplication.processEvents()
    assert window.isVisible() and wiz.isVisible() and wiz.index == page
    assert first_run.opened(window) is wiz


def test_generate_closes_onto_current_when_the_windows_generate_ends(window):
    from tests.qt.test_wizard import NUMBERS, GenState
    api = FakeApi(numbers=NUMBERS)
    wiz = _host(window, api)
    window.show_tab("settings")
    while W.PAGES[wiz.index] != "level":
        wiz.skip() if wiz.index else wiz.next()
    wiz.next()
    assert wait_until(lambda: ("generate",) in api.calls)
    window.bridge.generate_changed.emit(GenState("queued"))
    window.bridge.generate_changed.emit(GenState("current"))
    QApplication.processEvents()
    assert first_run.opened(window) is None and window.current_tab() == "current"
    assert window.services.settings.get().get("onboarding_completed") is True
