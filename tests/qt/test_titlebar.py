"""Windows' title bar in the theme (W2.1 row 7; the window's spec 01 §1.2 n1, 05 §5.5, §5.11, 06 E24).

What a wrong answer would cost: a light caption over a dark window (the first thing anyone sees), a call Windows 10
refuses made on every theme change (and logged every time), or the theme's colours forced over a high-contrast
desktop. This PC is Windows 10 (build 17763): the Windows 11 path is proven here with the call replaced, and on a real
Windows 11 machine by P-title, with Sonic's go.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QWidget

from app import theme
from app.qt import titlebar


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(titlebar, "platform", "win32")
    monkeypatch.setattr(titlebar, "high_contrast", lambda: False)
    monkeypatch.setattr(titlebar, "set_attribute", lambda hwnd, attr, value: seen.append((attr, value)) or 0)
    return seen


def test_colorref_is_blue_green_red():
    assert titlebar.colorref("#191f27") == 0x00271F19
    assert titlebar.colorref("#e9ecf1") == 0x00F1ECE9


@pytest.mark.parametrize("theme_name", theme.THEMES)
def test_windows_11_gets_caption_border_and_text_from_the_theme(qapp, calls, monkeypatch, theme_name):
    monkeypatch.setattr(titlebar, "windows_build", lambda: 22631)
    assert titlebar.apply(QWidget(), theme_name) == "applied"
    bar = theme.TITLE_BAR[theme_name]
    assert calls == [(35, titlebar.colorref(bar["caption"])), (34, titlebar.colorref(bar["border"])),
                     (36, titlebar.colorref(bar["text"]))]


def test_windows_10_makes_no_call(qapp, calls, monkeypatch):
    monkeypatch.setattr(titlebar, "windows_build", lambda: 17763)
    assert titlebar.apply(QWidget(), "hb") == "windows10"
    assert calls == []


def test_high_contrast_keeps_windows_own_colours(qapp, calls, monkeypatch):
    monkeypatch.setattr(titlebar, "windows_build", lambda: 22631)
    monkeypatch.setattr(titlebar, "high_contrast", lambda: True)
    assert titlebar.apply(QWidget(), "hb") == "high-contrast"
    assert calls == []


def test_another_system_is_a_no_op(qapp, calls, monkeypatch):
    monkeypatch.setattr(titlebar, "platform", "darwin")
    assert titlebar.apply(QWidget(), "hb") == "not-windows"
    assert calls == []


def test_a_refused_call_is_reported_not_raised(qapp, monkeypatch):
    monkeypatch.setattr(titlebar, "platform", "win32")
    monkeypatch.setattr(titlebar, "windows_build", lambda: 22631)
    monkeypatch.setattr(titlebar, "high_contrast", lambda: False)
    monkeypatch.setattr(titlebar, "set_attribute", lambda *a: 0x80070057)
    assert titlebar.apply(QWidget(), "sky") == "failed"


def test_the_window_colours_its_bar_when_shown_and_when_the_theme_changes(qapp, calls, monkeypatch):
    from app.qt import shell
    monkeypatch.setattr(titlebar, "windows_build", lambda: 22631)
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    assert [a for a, _ in calls] == [35, 34, 36]
    win.set_look("sapphire", "M")
    assert calls[3] == (35, titlebar.colorref(theme.TITLE_BAR["sapphire"]["caption"]))
    win.close()
    services.shutdown(0.5)
