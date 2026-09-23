"""The dashboard's startup update check must never reach GitHub from the test suite.

Constructing MasterDashboardApp starts check_updates_thread, which calls the real GitHub API. Two test
files built the window without patching it, so every run made live requests. Nothing failed — a
daemon thread that gives up silently offline — which is exactly why nobody noticed. conftest's
_no_gui_update_check fixture sets SURASURA_NO_UPDATE_CHECK for every test; these tests prove the
dashboard honours it, and that the real app (no flag) still checks for updates.

Real Tk root, built per test like tests/test_flag_ui.py, inside conftest's sandboxed data root.
"""

import os
import threading
import tkinter as tk
from unittest.mock import patch


def _build_dashboard_recording_threads():
    """Construct the dashboard and return (root, names of every thread target it started).

    The spy hands back a REAL thread, so construction behaves exactly as normal — except that the
    update check's own target is swapped for a no-op. It is still recorded, but it can never go
    online, even in the test that proves the check starts without the flag."""
    from app.main import MasterDashboardApp
    started = []
    real_thread = threading.Thread

    def spy(*args, **kwargs):
        name = getattr(kwargs.get("target"), "__name__", "")
        started.append(name)
        if name == "check_updates_thread":
            kwargs["target"] = lambda: None
        return real_thread(*args, **kwargs)

    root = tk.Tk()
    root.withdraw()
    with patch.object(threading, "Thread", side_effect=spy):
        MasterDashboardApp(root)
    return root, started


def test_conftest_switches_the_update_check_off_for_every_test():
    assert os.environ.get("SURASURA_NO_UPDATE_CHECK") == "1"


def test_dashboard_does_not_start_the_update_check_under_the_flag():
    root, started = _build_dashboard_recording_threads()
    try:
        assert "check_updates_thread" not in started
    finally:
        root.destroy()


def test_dashboard_still_starts_the_update_check_without_the_flag(monkeypatch):
    """The gate must switch the check off ONLY under test — the shipped app still looks for updates."""
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK")
    root, started = _build_dashboard_recording_threads()
    try:
        assert "check_updates_thread" in started
    finally:
        root.destroy()
