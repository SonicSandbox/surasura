"""The wiring check (W2.1 row 5; the window's spec 07 §7.1; the stack pack's harness layer: "the one to build first").

What a wrong answer would cost: a control built, styled, laid out and connected to nothing — the defect a demo can't
show and a person finds in ten seconds (hato: three reported, five found once the walk widened from QPushButton to
QAbstractButton). So the walk takes every QAbstractButton and every QAction in the window, shown or not, and asks
of each: is it connected, does it carry a tooltip (D17: every button and toggle), and if it has no words, does it name
itself first and to a screen reader (R4-1, 05 §5.9)? Later steps' screens join the walk by living in the window.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QAbstractButton, QCheckBox, QPushButton, QToolButton

from app.qt import shell


def _connected(obj):
    if isinstance(obj, QAbstractButton):
        if isinstance(obj, QToolButton) and (obj.menu() is not None or obj.defaultAction() is not None):
            return True
        signals = (obj.clicked, obj.toggled, obj.pressed, obj.released)
    else:
        if obj.menu() is not None:
            return True
        signals = (obj.triggered, obj.toggled)
    return any(obj.receivers(sig) > 0 for sig in signals)


def problems(window):
    """Every control in `window` that is unwired, untipped or unnamed, in words."""
    found = []
    controls = window.findChildren(QAbstractButton) + window.findChildren(QAction)
    for c in controls:
        label = c.text().strip() or c.objectName() or type(c).__name__
        if not _connected(c):
            found.append(f"{label}: connected to nothing")
        tip = " ".join((c.toolTip() or "").split())                 # whitespace collapsed (the stack pack)
        if isinstance(c, QAbstractButton):                          # (an action's tooltip is its text, a menu's line)
            if not tip:
                found.append(f"{label}: no tooltip")
            name = c.accessibleName().strip()
            if not c.text().strip():
                if not name:
                    found.append(f"{label}: no words and no accessible name")
                elif not tip.lower().startswith(name.lower()):
                    found.append(f"{label}: an icon-only control's tooltip must name it first")
    return found, len(controls)


@pytest.fixture
def window(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


def test_every_button_and_action_in_the_window_is_wired_tipped_and_named(window):
    found, walked = problems(window)
    assert walked >= 5                                   # the tabs and the bar's chip, hidden ones included
    assert found == []


def test_the_walk_finds_a_dead_button_a_toggle_without_a_tip_and_a_nameless_icon(window):
    # The check's own witnesses — each a different class, so a narrow walk (QPushButton only) would miss two.
    dead = QPushButton("Generate", window.centralWidget())
    dead.setToolTip("Build your list")
    toggle = QCheckBox("Clips", window.centralWidget())
    toggle.toggled.connect(lambda _on: None)
    icon_only = QToolButton(window.centralWidget())
    icon_only.clicked.connect(lambda: None)
    icon_only.setToolTip("Opens the menu")
    action = QAction("Move to top", window)
    window.addAction(action)
    found, _ = problems(window)
    assert "Generate: connected to nothing" in found
    assert "Clips: no tooltip" in found
    assert any("no words and no accessible name" in f for f in found)
    assert "Move to top: connected to nothing" in found
    icon_only.setAccessibleName("More")
    found, _ = problems(window)
    assert any("must name it first" in f for f in found)
    icon_only.setToolTip("More: what else you can do with this item")
    found, _ = problems(window)
    assert not any("must name it first" in f or "no words" in f for f in found)
