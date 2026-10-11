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


@pytest.mark.parametrize("theme_name, text_size", [("sky", "L"), ("sapphire", "S"), ("hb", "M")])
def test_a_switch_repaints_the_window_in_the_new_theme_and_size(opened, theme_name, text_size):
    win, _services = opened
    other = "sapphire" if theme_name != "sapphire" else "sky"
    win.set_look(other, "M")
    ms = win.set_look(theme_name, text_size)
    assert ms is not None and ms < 300                         # P-text's bar for a live switch (G1.2-21)
    assert style.current()[:2] == (theme_name, text_size)
    QApplication.processEvents()
    header, footer = _regions(win)
    c, o = theme.colours(theme_name), theme.colours(other)
    assert count(footer, c["surface"], 2) >= footer.shape[0] * footer.shape[1] // 2
    assert count(footer, o["surface"], 2) == 0
    assert count(header, c["surface"], 3) + count(header, c["header-top-opaque"], 3) >= 1000
    assert count(header, o["surface"], 2) == 0
    assert win.footer.height() == round(theme.size("footer", text_size))
    expected_pt = theme.font("body", text_size)[0] * style.PT_PER_PX
    assert QApplication.font().pointSizeF() == pytest.approx(expected_pt, abs=0.01)


def test_a_switch_writes_its_two_keys_and_nothing_else(opened):
    win, services = opened
    path = path_utils.get_user_file("settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"target_language": "ja", "a_key_another_program_wrote": 7}, f)
    win.set_look("sapphire", "L")
    assert services.settings.flush(5)
    written = json.load(open(path, encoding="utf-8"))
    assert written == {"target_language": "ja", "a_key_another_program_wrote": 7, "app_theme": "sapphire",
                       "text_size": "L"}


def test_an_unknown_theme_or_size_keeps_the_current_one(opened):
    win, _services = opened
    win.set_look("sapphire", "L")
    win.set_look("amethyst", "XL")
    assert style.current()[:2] == ("sapphire", "L")


def test_without_a_live_switch_it_asks_for_a_restart(opened, monkeypatch):
    win, services = opened
    monkeypatch.setattr(shell, "LIVE_LOOK", False)
    assert win.set_look("sky", "L") is None
    assert style.current()[:2] == (theme.DEFAULT_THEME, "M")  # unchanged until the next start (no theme saved: the default)
    assert win.bar_line.full() == strings.RESTART_TO_APPLY
    assert services.settings.get()["app_theme"] == "sky"     # saved for that start
