"""The one stylesheet, Fusion and the dark palette (W2.1 row 3; the window's spec 05 §5.3, §5.5, §5.11, §5.12).

What a wrong answer would cost: a control the operating system paints (a Windows-blue check box in a dark theme — the
stack pack's most expensive trap, four times in one build); a colour spelled in the window instead of the theme module
(three themes drift apart); a stylesheet that doesn't follow the text size (Large text that only grows half the
window). Every colour check reads pixels from a grab, and every "none of" is paired with "at least N of".
"""
import os
import re

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFrame, QLabel, QRadioButton, QScrollBar, QStyle,
                             QStyleFactory)

from app import theme
from app.qt import style
from tests.qt.pixels import WINDOWS_BLUES, count, rgb_array

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _grab(widget, w, h):
    widget.resize(w, h)
    widget.show()
    return rgb_array(widget.grab())


def test_every_theme_and_text_size_generates_its_own_stylesheet(qapp):
    sheets = {}
    for t in theme.THEMES:
        for size in theme.TEXT_SIZES:
            sheets[(t, size)] = style.stylesheet(t, size)
            assert theme.colours(t)["line"] in sheets[(t, size)]
    assert len(set(sheets.values())) == 9
    # the text size reaches the type: a tab at Large is 1.3 / 1.15 of Medium's points
    m = float(re.search(r"QToolButton#tab \{[^}]*font-size: ([\d.]+)pt", sheets[("hb", "M")]).group(1))
    l_ = float(re.search(r"QToolButton#tab \{[^}]*font-size: ([\d.]+)pt", sheets[("hb", "L")]).group(1))
    assert l_ / m == pytest.approx(1.3 / 1.15, rel=0.01)


def test_generating_a_stylesheet_is_quick(qapp):
    style.stylesheet.cache_clear()
    style.stylesheet("sapphire", "L")
    assert style._state["generated_ms"] is not None and style._state["generated_ms"] <= 5.0


_COLOUR_LITERAL = re.compile(r"""["'][^"'\n]*?(#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d)""")
_QCOLOR_LITERAL = re.compile(r"QColor\(\s*(\d|[\"']#|Qt\.GlobalColor)")


def test_no_colour_is_spelled_under_app_qt(qapp):
    # Every colour comes from app/theme.py (05 §5.12): a literal here is a fourth theme nobody maintains.
    found = []
    for where, dirs, files in os.walk(os.path.join(ROOT, "app", "qt")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(where, name), encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        if _COLOUR_LITERAL.search(line) or _QCOLOR_LITERAL.search(line):
                            found.append(f"{name}:{n}: {line.strip()}")
    assert found == []


def test_the_colour_scan_sees_a_literal():
    # the scan's own witness
    assert _COLOUR_LITERAL.search('    sheet = "QLabel { color: #e9ecf1; }"')
    assert _COLOUR_LITERAL.search("    x = 'rgba(12, 15, 20, 245)'")
    assert _QCOLOR_LITERAL.search("    c = QColor(255, 0, 0)")
    assert not _COLOUR_LITERAL.search("    c = colours['ink']  # a token")


def test_fusion_is_pinned_under_the_surasura_style(qapp):
    ours = style._state["style"]
    assert isinstance(ours, style.SurasuraStyle)
    assert ours.baseStyle().name().lower() == "fusion"
    assert qapp.style().name().lower() in ("fusion", "")          # the stylesheet wrapper reports its base


def test_the_palette_is_the_themes_and_links_are_the_accent(qapp):
    for t in theme.THEMES:
        style.apply(qapp, t, "M", "ja")
        pal = qapp.palette()
        c = theme.colours(t)
        assert pal.color(QPalette.ColorRole.Window).name() == c["bg"]
        assert pal.color(QPalette.ColorRole.Base).name() == c["surface"]
        assert pal.color(QPalette.ColorRole.Text).name() == c["ink"]
        assert pal.color(QPalette.ColorRole.Link).name() == c["accent"]
        assert pal.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == c["ink-faint"]


@pytest.mark.parametrize("theme_name", theme.THEMES)
def test_a_checked_check_box_is_painted_in_the_themes_colours(qapp, theme_name):
    style.apply(qapp, theme_name, "M", "ja")
    box = QCheckBox()
    box.setChecked(True)
    arr = _grab(box, 40, 30)
    c = theme.colours(theme_name)
    assert count(arr, c["accent"], 3) >= 60                       # the filled square
    assert count(arr, theme.FIXED["on-accent"], 40) >= 4           # the check mark on it
    for blue in WINDOWS_BLUES:
        assert count(arr, blue, 6) == 0


def test_an_unchecked_check_box_and_a_radio_are_the_themes_too(qapp):
    c = theme.colours("hb")
    box = QCheckBox()
    arr = _grab(box, 40, 30)
    assert count(arr, c["surface"], 2) >= 60 and count(arr, c["accent"], 3) == 0
    radio = QRadioButton()
    radio.setChecked(True)
    arr = _grab(radio, 40, 30)
    assert count(arr, c["accent"], 3) >= 20                        # the ring and the dot
    for blue in WINDOWS_BLUES:
        assert count(arr, blue, 6) == 0


def test_the_indicators_are_ours_not_fusions(qapp):
    # The same check box under plain Fusion fills with the palette's highlight, not the accent: the proxy style is
    # what paints it (removing SurasuraStyle._check_box makes the check above fail).
    box = QCheckBox()
    box.setChecked(True)
    fusion = QStyleFactory.create("Fusion")
    fusion.setParent(box)                           # a widget never owns its style: this one lives exactly as long
    box.setStyle(fusion)
    arr = _grab(box, 40, 30)
    assert count(arr, theme.colours("hb")["accent"], 3) < 60


def test_a_scroll_bar_and_a_combo_are_themed(qapp):
    c = theme.colours("hb")
    bar = QScrollBar(Qt.Orientation.Vertical)
    bar.setRange(0, 100)
    bar.setPageStep(20)
    arr = _grab(bar, 10, 200)
    assert count(arr, c["line"], 2) >= 100                         # the handle
    combo = QComboBox()
    combo.addItems(["Blue", "Lighter blue", "Sapphire"])
    arr = _grab(combo, 160, 30)
    assert count(arr, c["raised"], 2) >= 1000 and count(arr, c["line-hi"], 3) >= 100
    for blue in WINDOWS_BLUES:
        assert count(arr, blue, 6) == 0


def test_a_link_takes_the_palettes_accent(qapp):
    label = QLabel('<a href="https://example.org">AniList</a>')
    label.setTextFormat(Qt.TextFormat.RichText)
    arr = _grab(label, 120, 24)
    assert count(arr, theme.colours("hb")["accent"], 3) >= 10      # offscreen draws a glyph box in the link's colour
    for purple in ("#0000ff", "#ff00ff", "#800080"):               # Qt's default link and visited colours
        assert count(arr, purple, 10) == 0


def test_a_separator_is_a_plain_frame_in_the_line_colour(qapp):
    sep = style.separator()
    assert sep.frameShape() == QFrame.Shape.NoFrame
    assert sep.height() == 1 or sep.maximumHeight() == 1
    arr = _grab(sep, 200, 1)
    assert count(arr, theme.colours("hb")["line"], 2) >= 190


def test_qt_itself_never_waits_before_a_tooltip(qapp):
    # The bubble owns the 380 / 60 ms (tooltip.py); Qt waiting too doubled the hover delay to ~780 ms (review A2).
    ours = style._state["style"]
    assert ours.styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay) == 0
    assert ours.styleHint(QStyle.StyleHint.SH_ToolTip_FallAsleepDelay) == 500


def test_every_apply_asks_for_the_dark_scheme_even_on_a_dark_system(qapp, monkeypatch):
    # Windows 10's caption follows the scheme (P-title); asked only when the system wasn't dark, a later switch of
    # Windows to Light would turn it white (review A4). Offscreen can't hold a scheme, so the ask itself is watched.
    from PyQt6.QtGui import QStyleHints
    asked = []
    monkeypatch.setattr(style, "ask_dark", lambda hints: asked.append(hints))
    monkeypatch.setattr(QStyleHints, "colorScheme", lambda self: Qt.ColorScheme.Dark)   # a system already dark
    style.apply(qapp, "sky", "M", "ja")
    style.apply(qapp, "sky", "M", "ja")
    assert len(asked) == 2 and asked[0] is qapp.styleHints()
    style._ask_dark(qapp.styleHints())                  # the real call runs on this Qt without error


def test_an_item_views_check_and_a_menus_check_are_ours(qapp):
    # Fusion would draw both in its own colours (review A10: S12): the accent fill / mark is SurasuraStyle's.
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QMenu
    c = theme.colours("hb")
    view = QListWidget()
    item = QListWidgetItem("Clips")
    item.setFlags(item.flags() | _Qt.ItemFlag.ItemIsUserCheckable)
    item.setCheckState(_Qt.CheckState.Checked)
    view.addItem(item)
    assert count(_grab(view, 200, 60), c["accent"], 3) >= 40
    menu = QMenu()
    act = menu.addAction("Covers")
    act.setCheckable(True)
    act.setChecked(True)
    act.triggered.connect(lambda: None)
    assert count(_grab(menu, 220, 40), c["accent"], 3) >= 6


def test_the_focus_ring_of_a_toggle_is_the_accent(qapp):
    # PE_FrameFocusRect is SurasuraStyle's 2 px accent ring (review A10: S13), not Fusion's.
    from PyQt6.QtCore import Qt as _Qt
    c = theme.colours("hb")
    box = QCheckBox("Clips")
    before = count(_grab(box, 120, 30), c["accent"], 3)
    box.setFocus(_Qt.FocusReason.TabFocusReason)
    qapp.processEvents()
    after = count(_grab(box, 120, 30), c["accent"], 3)
    assert after - before >= 40


def test_a_combos_open_list_is_themed(qapp):
    # The list a combo opens is a separate top-level window: themed through the application, never Windows' white.
    c = theme.colours("hb")
    combo = QComboBox()
    combo.addItems(["Blue", "Lighter blue", "Sapphire"])
    _grab(combo, 160, 30)
    combo.showPopup()
    qapp.processEvents()
    view = combo.view()
    arr = rgb_array(view.grab())
    assert count(arr, c["surface"], 2) + count(arr, c["raised"], 2) >= 0.5 * arr.shape[0] * arr.shape[1]
    assert count(arr, "#ffffff", 4) < 0.01 * arr.shape[0] * arr.shape[1]
    combo.hidePopup()
