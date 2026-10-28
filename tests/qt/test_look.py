"""The look, live (W2.1 row 9; the window's spec 05 §5.5, 08 G1.2-13 / -21, 02 §2.1).

What a wrong answer would cost: a theme switch that leaves half the window in the old theme (the header, the bar, the
title bar); Large text that grows the type but not the bar it sits in; a switch that writes more of settings.json
than its two keys (S16, the services' rule), or loses a key another program wrote; a switch that moves the run
signature (a full Generate for a colour: tests/test_settings_signatures.py proves it doesn't).
"""
import json

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app import path_utils, theme
from app.qt import shell, strings, style
from tests.qt.pixels import count, rgb_array


@pytest.fixture
def opened(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.resize(1280, 800)
    win.show()
    QApplication.processEvents()
    yield win, services
    win.close()
    services.shutdown(0.5)


def _regions(win):
    arr = rgb_array(win.grab())
    header = arr[: win.findChild(type(win.footer), "header").height() - 2, :, :]
    footer = arr[-win.footer.height() + 2:, :, :]
    return header, footer


@pytest.mark.parametrize("text_size", ["L", "S", "M"])
def test_a_switch_repaints_the_window_in_the_new_size_on_the_one_theme(opened, text_size):
    """One theme in 3.0 (RS-1): the frame is the night's frame colour at every size; the size reaches the bar."""
    win, _services = opened
    win.set_look("S" if text_size != "S" else "L")
    ms = win.set_look(text_size)
    assert ms is not None and ms < 300                         # P-text's bar for a live switch (G1.2-21)
    assert style.current()[:2] == ("night", text_size)
    QApplication.processEvents()
    header, footer = _regions(win)
    c = theme.colours()
    assert count(footer, c["frame"], 2) >= footer.shape[0] * footer.shape[1] // 2
    assert count(header, c["frame"], 2) >= header.shape[0] * header.shape[1] // 3
    assert win.footer.height() == round(theme.size("footer", text_size))
    expected_pt = theme.font("body", text_size)[0] * style.PT_PER_PX
    assert QApplication.font().pointSizeF() == pytest.approx(expected_pt, abs=0.01)


def test_a_switch_writes_its_one_key_and_nothing_else(opened):
    win, services = opened
    path = path_utils.get_user_file("settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"target_language": "ja", "a_key_another_program_wrote": 7}, f)
    win.set_look("L")
    assert services.settings.flush(5)
    written = json.load(open(path, encoding="utf-8"))
    assert written == {"target_language": "ja", "a_key_another_program_wrote": 7, "text_size": "L"}


def test_an_unknown_size_keeps_the_current_one(opened):
    win, _services = opened
    win.set_look("L")
    win.set_look("XL")
    assert style.current()[:2] == ("night", "L")


def test_without_a_live_switch_it_asks_for_a_restart(opened, monkeypatch):
    win, services = opened
    monkeypatch.setattr(shell, "LIVE_LOOK", False)
    assert win.set_look("L") is None
    assert style.current()[:2] == (theme.DEFAULT_THEME, "M")  # unchanged until the next start
    assert win.bar_line.full() == strings.RESTART_TO_APPLY
    assert services.settings.get()["text_size"] == "L"       # saved for that start


# --- laptop fixes row 15: *Restart now* closes the quit's way, then the same program starts again ------------------ #
def test_restart_closes_the_window_saving_its_place_and_the_settings_tab(qapp):
    """What a wrong answer would cost: a restart that loses the new size (unsaved), or comes back at another size, place
    or tab than it left."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QGuiApplication
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    screen = QGuiApplication.primaryScreen().availableGeometry()
    win.setGeometry(QRect(screen.left() + 30, screen.top() + 30, 1000, 700))     # (offscreen: test_shell's size)
    win.show_tab("settings")
    QApplication.processEvents()
    services.settings.set({"text_size": "L"})                  # the page's save, queued
    assert win.restart_asked is False
    win.restart()
    assert win.restart_asked is True and not win.isVisible()
    services.shutdown(0.5)                                     # main's quit: the settings written
    assert json.load(open(path_utils.get_user_file("settings.json"), encoding="utf-8"))["text_size"] == "L"
    saved = json.load(open(shell.state_path(), encoding="utf-8"))
    assert saved["tab"] == "settings" and saved["geometry"][2:] == [1000, 700]
    services = shell.Services()                                # the next start
    again = shell.open_window(qapp, services)
    assert again.current_tab() == "settings"
    assert (again.geometry().width(), again.geometry().height()) == (1000, 700)
    assert style.current()[1] == "L"                           # and at the new size
    again.close()
    services.shutdown(0.5)


class _OneInstance:
    """main()'s single-instance claim, recorded (never a real lock or pipe)."""

    def __init__(self, log):
        self.log = log

    def claim(self, _argv):
        return True

    def release(self):
        self.log.append("released")

    def stop_listening(self):
        pass

    class _Signal:
        def connect(self, _slot):
            pass
    activated = _Signal()


@pytest.mark.parametrize("restart", [True, False])
def test_main_starts_the_program_again_after_the_claim_goes_only_when_a_restart_was_asked(qapp, monkeypatch, restart):
    from app.qt import single as single_module, start_gate
    log, seen = [], {}
    real_window = shell.open_window

    def spy_window(app, services, state_file=None):
        win = seen["win"] = real_window(app, services, state_file)
        return win

    def fake_exec(*_a):
        win = seen["win"]
        win.first_frame.disconnect(win.start_duties)           # (the real duties stay unmade)
        if restart:
            win.restart()
        else:
            win.close()
        return 0

    class Chores:                                              # the store's close trigger, recorded (B2-4)
        def close(self, store=False):
            pass

        def close_store(self):
            log.append("store closed")

    def services(**_kw):
        made = shell.Services()
        made.chores, made.started = Chores(), True             # (as once the duties started: the close runs)
        return made
    monkeypatch.setattr(single_module, "SingleInstance", lambda: _OneInstance(log))
    monkeypatch.setattr(start_gate, "gate", lambda _app: True)
    monkeypatch.setattr(shell, "open_services", services)
    monkeypatch.setattr(shell, "open_window", spy_window)
    monkeypatch.setattr(QApplication, "exec", fake_exec)
    monkeypatch.setattr(shell, "prepare_process", lambda: None)
    monkeypatch.setattr(shell, "relaunch", lambda argv: log.append(("relaunch", list(argv))))   # never a real start
    from app.qt import hud
    meters, real_start = [], hud.Hud.start
    monkeypatch.setattr(hud.Hud, "start", lambda self: meters.append(self) or real_start(self))
    assert shell.main(["app_entry.py", "--hud"]) == 0
    # The HUD is stopped once main returns, its Windows-message filter off: left installed, the collector freed it on a
    # worker thread, where Qt's removal misses, and the next message crashed a later test (0xC0000005, row 35's runs)
    assert len(meters) == 1 and not meters[0].started and meters[0].messages.app is None
    assert log[0] == "released" and log[1] == "store closed"     # the claim goes before the store's close trigger
    if restart:
        # B2-4: the new start only once the store's close has ended — never beside the old process's 7–15 s close
        assert log[2:].count(("relaunch", ["app_entry.py", "--hud"])) == 1 and "relaunch" not in str(log[:2])
        assert log.index(("relaunch", ["app_entry.py", "--hud"])) > log.index("store closed")
    else:
        assert all(entry in ("released", "store closed") for entry in log)


def test_relaunch_starts_the_same_program_from_source_and_frozen(monkeypatch, tmp_path):
    import subprocess
    import sys
    started = []

    class FakePopen:
        def __init__(self, args, **kw):
            started.append((args, kw))
    monkeypatch.setattr(subprocess, "Popen", FakePopen)        # never a real start
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert isinstance(shell.relaunch(["app_entry.py", "--hud"]), FakePopen)
    import os
    assert started[-1][0] == [sys.executable, os.path.abspath("app_entry.py"), "--hud"]
    assert started[-1][1]["stdin"] == subprocess.DEVNULL
    shell.relaunch([shell.__file__])                           # `python -m app.qt.shell`
    assert started[-1][0] == [sys.executable, "-m", "app.qt.shell"]
    exe = str(tmp_path / "Surasura.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe)
    shell.relaunch([exe])
    assert started[-1][0] == [exe]
    # alpha 4 M6: every new start carries the mark (in its environment, never its logged arguments)
    assert all(kw["env"][shell.RESTARTED] == "1" and shell.RESTARTED not in " ".join(args) for args, kw in started)


def test_the_restart_mark_is_read_once_and_taken_out_of_the_environment(monkeypatch):
    """Review F-5: the new start reads *Restart now*'s mark (`restart_mark`, on both of main's branches) and takes it
    out of its environment, so nothing it starts — and no later start of yours — inherits it."""
    import os
    monkeypatch.setenv(shell.RESTARTED, "1")
    assert shell.restart_mark() is True and shell.RESTARTED not in os.environ
    assert shell.restart_mark() is False, "read once"


def test_a_failed_relaunch_is_logged_never_raised(monkeypatch):
    import subprocess

    def refused(*_a, **_k):
        raise OSError("not found")
    monkeypatch.setattr(subprocess, "Popen", refused)
    assert shell.relaunch(["app_entry.py"]) is None


def test_in_the_window_the_settings_row_asks_esc_is_later_and_restart_now_closes_it(qapp):
    """The real page in the real window: the row's question is over the window (its router: Esc is *Later*), and
    *Restart now* reaches the shell's `restart`."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from app.qt import settings_strings as S
    from tests.qt.conftest import wait_until
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.resize(1280, 800)
    win.show()
    win.open_setting("text_size")
    page = win.settings_page
    assert wait_until(lambda: page.built, 20)
    control = page.row("text_size").controls[0]
    control.changed.emit("L")
    card = page.live.asking
    assert card is not None and card.title.text() == S.TEXT_SIZE_RESTART_ASK and card.window() is win
    QTest.keyClick(card, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert page.live.asking is None and win.isVisible() and win.restart_asked is False
    assert win.bar_line.full() == strings.RESTART_TO_APPLY
    control.changed.emit("S")
    page.live.asking.yes.click()
    QApplication.processEvents()
    assert win.restart_asked is True and not win.isVisible()
    services.shutdown(0.5)
    assert json.load(open(path_utils.get_user_file("settings.json"), encoding="utf-8"))["text_size"] == "S"
    assert json.load(open(shell.state_path(), encoding="utf-8"))["tab"] == "settings"
