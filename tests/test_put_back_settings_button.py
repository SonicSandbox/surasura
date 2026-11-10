"""Settings → Data & System: "Put Anki back the way it was before Surasura…" shows only with Junban present.

The flow lives in Junban (`modules/junban/first_touch_gui.py`), imported lazily: an install without the module — the
public repo's checkout among them — shows no button rather than one that does nothing. Shown whether or not
reordering is switched on: the way back from what Surasura did stays.

Real Tk root, built like tests/test_reels_sunset.py, inside conftest's sandboxed data root.
"""

import importlib.util
import sys
import tkinter as tk
from tkinter import ttk

BUTTON = "Put Anki back the way it was before Surasura…"


def _installed(name):
    """find_spec on a dotted name imports its parent: a checkout without modules/ (the public repo) raises."""
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _buttons(widget):
    found = {}
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            found[child.cget("text")] = child
        found.update(_buttons(child))
    return found


def _settings_buttons():
    from app.main import MasterDashboardApp
    root = tk.Tk()
    root.withdraw()
    try:
        app = MasterDashboardApp(root)
        app.create_settings_window()
        buttons = _buttons(app.settings_window)
        return {text: bool(button.bind("<Enter>")) for text, button in buttons.items()}, \
            buttons.get(BUTTON) is not None and str(buttons[BUTTON].cget("command")) != ""
    finally:
        root.destroy()


def test_the_button_shows_with_junban_present_with_a_tooltip_and_a_command():
    if not _installed("modules.junban.first_touch_gui"):
        return   # a checkout without the module: the test below covers it
    tips, wired = _settings_buttons()
    assert tips.get(BUTTON) is True, "no button, or no tooltip on it"
    assert wired


def test_the_button_is_not_shown_without_junban(monkeypatch):
    """`None` in sys.modules makes the import fail, as a build without the module does (and the package's attribute
    goes too: `from package import name` reads it first)."""
    monkeypatch.setitem(sys.modules, "modules.junban.first_touch_gui", None)
    package = sys.modules.get("modules.junban")
    if package is not None:
        monkeypatch.delattr(package, "first_touch_gui", raising=False)
    tips, _wired = _settings_buttons()
    assert BUTTON not in tips
    # Guard against a vacuous pass: the column's other buttons still render.
    assert "Export Sentence Dictionary" in tips
