"""The shell (W2.1 row 5; the window's spec 01 §1.5 item 1, 02 §2.1, 05 §5.2, §5.4, §5.9, 08 §8.4 G1.2-2 / -17).

What a wrong answer would cost:
  * Esc or the mouse's Back button closing the main window — Sonic's rule is the opposite (✅ G1.2-2: they close the
    topmost overlays, then a secondary window, never the main one);
  * a failure from the command line raising a dialog (✅ G0.3-1: the bar, never a box), or not showing at all;
  * Needs you vanishing after he has looked at it (P1.2-1: seen entries stop counting, and stay listed);
  * the window's place or tab written into settings.json (S16: nothing automatic writes it), lost, or restored off
    every screen;
  * a Blue frame before Sapphire (the look must be on the QApplication before the first paint);
  * tabs a keyboard can't reach, or a focus ring that isn't the accent (05 §5.9).
"""
import json
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PyQt6.QtGui import QGuiApplication, QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QWidget

from app import path_utils, theme
from app.cli import contract
from app.qt import shell, strings, style
from app.services import status as status_service
from tests.qt.conftest import wait_until
from tests.qt.pixels import count, rgb_array


@pytest.fixture
def services(qapp):
    s = shell.Services()
    yield s
    s.shutdown(0.5)


@pytest.fixture
def window(qapp, services):
    win = shell.open_window(qapp, services)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()


def _snap(**kw):
    base = status_service.Snapshot((), None, (), None, None, None, 0.0)
    return base._replace(**kw)


# --- the window ---------------------------------------------------------------------------------------------------- #
def test_the_window_opens_with_its_title_edge_to_edge(window):
    assert window.windowTitle() == "Surasura — The Immersion Architect"
    assert window.minimumSize().width() == theme.WINDOW_MIN[0]
    assert window.centralWidget().layout().contentsMargins().left() == 0
    assert window.isVisible()


def test_the_header_holds_the_mark_the_wordmark_and_the_language_and_no_dead_buttons(window):
    from PyQt6.QtWidgets import QAbstractButton
    header = window.findChild(QWidget, "header")
    assert header.findChildren(QAbstractButton) == []           # its controls arrive with their features (G-2)
    assert window.subline.text() == "日本語"
    assert window.wordmark.sizeHint().width() > 0


def test_the_tabs_switch_pages_and_needs_you_is_hidden_while_nothing_waits(window):
    assert window.current_tab() == "current"
    assert window.tab_buttons["needs"].isHidden()
    window.tab_buttons["finished"].click()
    assert window.current_tab() == "finished"
    assert window.pages.currentWidget() is window.page_widgets["finished"]


def test_the_keyboard_reaches_every_tab_and_space_opens_its_page(window):
    # A tab bar is one stop for Tab (the selected tab, as a web tablist); the arrows move between tabs and Space opens
    # one (05 §5.9: every action reachable without a mouse).
    window.activateWindow()
    window._rest.setFocus()
    QTest.keyClick(window._rest, Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is window.tab_buttons["current"]
    reached = [QApplication.focusWidget()]
    for _ in range(2):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Right)
        reached.append(QApplication.focusWidget())
    assert reached == [window.tab_buttons["current"], window.tab_buttons["finished"], window.tab_buttons["settings"]]
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Space)
    assert window.current_tab() == "settings"
    assert window.pages.currentWidget() is window.page_widgets["settings"]


def test_the_focus_ring_is_the_accent(window):
    b = window.tab_buttons["finished"]
    before = count(rgb_array(b.grab()), theme.colours("hb")["accent"], 3)
    b.setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    after = count(rgb_array(b.grab()), theme.colours("hb")["accent"], 3)
    assert before == 0 and after >= 2 * (b.width() + b.height())


# --- Needs you and the bar ------------------------------------------------------------------------------------------ #
def test_needs_you_shows_while_anything_is_listed_and_counts_only_unseen(window):
    unseen = status_service.Entry("Command line (status): it failed", "t", False)
    window.show_status(_snap(needs_you=(unseen,)))
    assert not window.tab_buttons["needs"].isHidden()
    assert window.tab_buttons["needs"].text() == strings.TAB_WITH_COUNT.format(name="Needs you", count=1)
    window.show_tab("needs")
    window.show_status(_snap(needs_you=(unseen._replace(seen=True),)))
    assert not window.tab_buttons["needs"].isHidden()          # looked at: still listed (P1.2-1)
    assert window.tab_buttons["needs"].text() == "Needs you"   # and no longer counted
    window.show_status(_snap())
    assert window.tab_buttons["needs"].isHidden()
    assert window.current_tab() == "current"                   # its page closed with it


def test_running_jobs_light_the_bar(window):
    window.show_status(_snap(lines=("Updating known words from Anki", "Generating · Reading your files 3 / 12")))
    assert window.bar_line.full() == "Updating known words from Anki · Generating · Reading your files 3 / 12"
    assert window.bar_dot.property("busy") == "true"
    window.show_status(_snap())
    assert window.bar_line.full() == "" and window.bar_dot.property("busy") == "false"


def test_a_command_line_failure_shows_in_the_bar_within_a_poll_and_never_as_a_dialog(window, services, monkeypatch):
    opened = []
    monkeypatch.setattr(QDialog, "exec", lambda self: opened.append(self))
    # the reader starts at the file's end once the window first looks (a failure from before isn't news)
    assert wait_until(lambda: services.status._reader is not None, 5)
    contract._record_event({"type": "error", "contract": 1, "ok": False, "code": "bad-data", "exit": 1,
                            "message": "Surasura's settings (settings.json) can't be read.", "verb": "status",
                            "time": "2026-10-06T19:00:00"})
    assert wait_until(lambda: window.bar_failure.isVisibleTo(window), 5)
    assert window.bar_failure.full().startswith("⚠ Command line (status): Surasura's settings")
    assert window.logs_button.isVisibleTo(window)
    assert not window.tab_buttons["needs"].isHidden()
    assert opened == [] and [w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog)] == []


def test_the_ankiweb_mark_and_connects_line_show_only_when_they_exist(window):
    window.show_status(_snap())
    assert window.bar_ankiweb.isHidden() and window.bar_connect.isHidden()
    window.show_status(_snap(ankiweb="AnkiWeb synced", connect="Connect: 3 waiting"))
    assert window.bar_ankiweb.text() == "AnkiWeb synced" and not window.bar_connect.isHidden()


def test_open_the_logs_folder_goes_to_a_worker(window, monkeypatch):
    calls = []
    monkeypatch.setattr(shell.bridge, "run_in_worker", lambda fn, *a, **k: calls.append((fn, a)))
    monkeypatch.setattr(shell.sys, "platform", "win32")
    window.show_status(_snap(failure="Command line (x): it failed", logs="C:/logs"))
    window.logs_button.click()
    assert calls and calls[0][1] == ("C:/logs",)


# --- the look before the first paint ---------------------------------------------------------------------------------- #
class _FirstPaint(QObject):
    def __init__(self):
        super().__init__()
        self.window_colour = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint and self.window_colour is None:
            self.window_colour = QApplication.palette().window().color().name()
        return False


def test_with_sapphire_saved_the_first_paint_is_sapphire(qapp):
    services = shell.Services()
    services.settings.set({"app_theme": "sapphire", "text_size": "L"}, now=True)
    services = shell.Services()                                    # a fresh start reads it
    win = shell.open_window(qapp, services)
    spy = _FirstPaint()
    win.installEventFilter(spy)
    win.show()
    assert wait_until(lambda: spy.window_colour is not None)
    assert spy.window_colour == theme.colours("sapphire")["bg"]
    assert style.current()[:2] == ("sapphire", "L")
    win.close()
    services.shutdown(0.5)


# --- window_state.json ------------------------------------------------------------------------------------------------ #
def test_the_windows_place_and_tab_round_trip_and_never_touch_settings(qapp):
    settings_file = path_utils.get_user_file("settings.json")
    before = os.path.exists(settings_file) and open(settings_file, "rb").read()
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    screen = QGuiApplication.primaryScreen().availableGeometry()
    win.setGeometry(QRect(screen.left() + 40, screen.top() + 30, 1100, 700))
    win.show_tab("finished")
    win.close()
    services.shutdown(0.5)
    saved = json.load(open(shell.state_path(), encoding="utf-8"))
    assert saved["tab"] == "finished" and saved["geometry"][2:] == [1100, 700]
    assert (os.path.exists(settings_file) and open(settings_file, "rb").read()) == before
    services = shell.Services()
    again = shell.open_window(qapp, services)
    assert again.current_tab() == "finished"
    assert (again.geometry().width(), again.geometry().height()) == (1100, 700)
    again.close()
    services.shutdown(0.5)


def test_a_place_off_every_screen_comes_back_on_one(qapp):
    with open(shell.state_path(), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "geometry": [-30000, -30000, 1200, 760], "maximized": False, "tab": "current"}, f)
    services = shell.Services()
    win = shell.open_window(qapp, services)
    screens = [s.availableGeometry() for s in QGuiApplication.screens()]
    assert any(win.geometry().intersected(s).width() >= 200 for s in screens)
    win.close()
    services.shutdown(0.5)


def test_a_corrupt_state_file_gives_the_defaults(qapp):
    with open(shell.state_path(), "w", encoding="utf-8") as f:
        f.write("{not json")
    services = shell.Services()
    win = shell.open_window(qapp, services)
    assert win.current_tab() == "current"
    assert win.geometry().width() >= theme.WINDOW_MIN[0]
    win.close()
    services.shutdown(0.5)


def test_fit_on_screens_keeps_a_visible_place_and_centres_a_lost_one():
    screens = [QRect(0, 0, 1920, 1040)]
    assert shell.fit_on_screens(QRect(100, 100, 1280, 800), screens) == QRect(100, 100, 1280, 800)
    lost = shell.fit_on_screens(QRect(5000, 100, 1280, 800), screens)
    assert abs(lost.center().x() - 960) <= 2 and abs(lost.center().y() - 520) <= 2


# --- Esc and Back (✅ G1.2-2) ---------------------------------------------------------------------------------------- #
def _overlay(window):
    o = QWidget(window.centralWidget())
    o.setGeometry(100, 100, 300, 200)
    window.register_overlay(o)
    o.show()
    return o


def test_esc_closes_every_open_overlay_at_once_and_never_the_main_window(window):
    a, b = _overlay(window), _overlay(window)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not a.isVisible() and not b.isVisible()
    assert window.isVisible()
    QTest.keyClick(window, Qt.Key.Key_Escape)                  # nothing open: Esc again leaves the window alone
    assert window.isVisible()


def test_the_mouse_back_button_does_what_esc_does(window):
    a = _overlay(window)
    QTest.mouseClick(window.centralWidget(), Qt.MouseButton.BackButton)
    assert not a.isVisible() and window.isVisible()
    QTest.mouseClick(window.centralWidget(), Qt.MouseButton.BackButton)
    assert window.isVisible()


def test_forward_does_nothing(window):
    a = _overlay(window)
    QTest.mouseClick(window.centralWidget(), Qt.MouseButton.ForwardButton)
    assert a.isVisible() and window.isVisible()


def test_esc_and_back_close_a_secondary_window(window):
    second = QWidget()
    second.setWindowTitle("a module window")
    second.show()
    QTest.keyClick(second, Qt.Key.Key_Escape)
    assert not second.isVisible() and window.isVisible()
    dialog = QDialog(window)
    dialog.show()
    QTest.mouseClick(dialog, Qt.MouseButton.BackButton)
    assert not dialog.isVisible() and dialog.result() == QDialog.DialogCode.Rejected and window.isVisible()


def test_esc_in_the_main_window_still_reaches_the_focused_field(window):
    from PyQt6.QtWidgets import QLineEdit
    seen = []

    class Field(QLineEdit):
        def keyPressEvent(self, e):
            seen.append(e.key())
            super().keyPressEvent(e)
    field = Field(window.centralWidget())
    field.show()
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_Escape)
    assert seen == [Qt.Key.Key_Escape] and window.isVisible()


# --- the tooltip bubble -------------------------------------------------------------------------------------------- #
def _hover(widget):
    pos = QPoint(widget.width() // 2, widget.height() // 2)
    QApplication.sendEvent(widget, QHelpEvent(QEvent.Type.ToolTip, pos, widget.mapToGlobal(pos)))


def test_the_bubble_shows_the_tooltip_above_its_control_and_hides_on_a_press(window):
    tab = window.tab_buttons["finished"]
    _hover(tab)
    assert wait_until(lambda: window.tooltips.showing() is not None)
    assert window.tooltips.showing() == strings.TABS["finished"][1]
    bubble = window.tooltips.bubble.geometry()
    top = tab.mapToGlobal(QPoint(0, 0)).y()
    assert bubble.bottom() < top or bubble.top() > top + tab.height()        # beside it, never over it
    QTest.mouseClick(window.centralWidget(), Qt.MouseButton.LeftButton)
    assert window.tooltips.showing() is None


def test_keyboard_focus_shows_the_bubble(window):
    tab = window.tab_buttons["settings"]
    tab.setFocus(Qt.FocusReason.TabFocusReason)
    assert wait_until(lambda: window.tooltips.showing() == strings.TABS["settings"][1])


def test_the_bubble_waits_380_ms_then_60_within_half_a_second(window):
    from app.qt import freeze
    freeze.set_frozen(False)
    t = window.tooltips
    assert t.delay() == 380
    t._last_hidden = __import__("time").monotonic()
    assert t.delay() == 60


def test_the_bubble_is_placed_inside_the_screen():
    from PyQt6.QtCore import QSize
    from app.qt.tooltip import place
    screen = QRect(0, 0, 1000, 800)
    p = place(QSize(200, 40), QRect(900, 400, 80, 30), screen)          # near the right edge: pulled in
    assert p.x() + 200 <= 1000 and p.y() + 40 <= 400
    p = place(QSize(200, 40), QRect(100, 5, 80, 30), screen)            # at the top: flipped below
    assert p.y() >= 35
