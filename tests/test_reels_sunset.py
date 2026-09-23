"""Reels is SUNSET (2026-09-22): kept on disk, never offered.

The module stays in modules/reels/ with its own suite, and the rest of its dashboard wiring stays
dormant — enable_reels is off and every build excludes it — so nobody sees it. The one place a source
checkout still showed it was the "Enable Reels" checkbox in Settings, which is gone. How to bring it
back is recorded in docs/agent instructions/Reels_Module_Spec.md.

Real Tk root, built like tests/test_flag_ui.py, inside conftest's sandboxed data root.
"""

import importlib.util
import tkinter as tk
from tkinter import ttk


def _checkbox_labels(widget):
    labels = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Checkbutton):
            labels.append(child.cget("text"))
        labels.extend(_checkbox_labels(child))
    return labels


def test_settings_no_longer_offer_reels_even_when_the_module_is_on_disk():
    from app.main import MasterDashboardApp
    root = tk.Tk()
    root.withdraw()
    try:
        app = MasterDashboardApp(root)
        app.create_settings_window()
        labels = _checkbox_labels(app.settings_window)
    finally:
        root.destroy()

    assert "Enable Reels" not in labels
    # Guard against a vacuous pass: the optional-module toggles beside it still render.
    if importlib.util.find_spec("modules.junban") is not None:
        assert "Enable Anki reordering" in labels


def test_reels_stays_on_disk_and_dormant():
    """Sunset, not deleted: the module still imports, and its switch still defaults to off."""
    if importlib.util.find_spec("modules.reels") is None:
        return   # a checkout without the module has nothing to keep dormant
    import modules.reels as reels
    assert reels.SETTINGS_DEFAULTS["enable_reels"] is False
