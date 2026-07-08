import pytest
import tkinter as tk

import app.main as main_module
from app.main import MasterDashboardApp


@pytest.fixture
def tk_root():
    """A hidden Tk root; skip cleanly on a headless machine with no display."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    # A prior GUI test may have imported app.main while tkinter was mocked, leaving app.main.tk
    # a MagicMock; restore the real module so _iv's `except tk.TclError` catches a real class.
    main_module.tk = tk
    root.withdraw()
    yield root
    root.destroy()


def test_iv_returns_value_when_field_is_valid(tk_root):
    var = tk.IntVar(master=tk_root, value=42)
    assert MasterDashboardApp._iv(var, 99) == 42


def test_iv_returns_fallback_when_field_is_empty(tk_root):
    """A numeric Entry/Spinbox is momentarily EMPTY while the user edits it (delete 3000 to
    type 500). IntVar.get() then raises TclError; the tolerant reader must return the last-saved
    value instead of letting the whole settings save silently abort (finding dashboard-05)."""
    var = tk.IntVar(master=tk_root, value=3000)
    # Simulate the mid-edit empty field: the underlying Tcl variable holds a non-int string.
    var.set("")
    with pytest.raises(tk.TclError):
        var.get()  # sanity check: an empty field really does raise
    assert MasterDashboardApp._iv(var, 3000) == 3000
