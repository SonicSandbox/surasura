"""The Connect preview's switch in Settings (P3.1 row 3.1.1; P1.5 05-surface U4's head): *Make cards automatically
(preview)* in a third column, `connect_enabled` saved alone and only when touched; on, Connect's watermark set (✅
G1.1-2: nothing placed before is mined), its controls and the dashboard's line appear; off, they go.

What a wrong answer would cost: a Settings window that writes `connect_enabled: false` (or any default) into a 2.5
user's file the moment it opens; a switch-on that mines the user's whole history (every episode placed before it); a
Settings window that imports Connect with the preview off (2.5 byte for byte). The real dashboard on a hidden root,
the test's own root; real subtitles in the library."""
import sys
import time
import types
from unittest.mock import patch

import pytest
import tkinter as tk

from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect_tk_helpers import read_settings, settings_bytes


class Now:
    """A worker that runs at once."""

    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def _stand_in(on):
    """What `_connect_switch_toggled` / `_connect_switched` touch on the dashboard."""
    lines, queued = [], []
    window = types.SimpleNamespace(
        var_connect_enabled=types.SimpleNamespace(get=lambda: on), _current_settings={"target_language": "ja"},
        lines=lines, queued=queued, log_to_terminal=lines.append, gui_queue=types.SimpleNamespace(put=queued.append),
        _connect_panel_drop=lambda: lines.append("panel dropped"), _connect_row_stop=lambda: lines.append("row stopped"),
        _connect_switched_on="controls and line")
    return window


def test_switching_on_writes_only_connect_enabled(monkeypatch):
    from app import main
    h.write_settings(target_language="ja", theme="Dark Flow", placing_rules={"hato": "top"})
    before = read_settings()
    window = _stand_in(True)
    window._connect_switched = lambda on: window.lines.append(("switched", on))
    monkeypatch.setattr(main.threading, "Thread", Now)
    main.MasterDashboardApp._connect_switch_toggled(window)
    assert read_settings() == dict(before, connect_enabled=True), "its own key, every other as the file holds it"
    assert window._current_settings["connect_enabled"] is True
    assert ("switched", True) in window.lines


def test_switching_off_drops_the_controls_and_the_line_and_writes_only_the_switch(monkeypatch):
    from app import main
    h.write_settings(target_language="ja", connect_enabled=True)
    window = _stand_in(False)
    window._connect_switched = lambda on: None
    monkeypatch.setattr(main.threading, "Thread", Now)
    main.MasterDashboardApp._connect_switch_toggled(window)
    assert read_settings() == {"target_language": "ja", "anki_connect_url": h.CLOSED_PORT, "connect_enabled": False}
    assert window.lines == ["panel dropped", "row stopped"]


def test_a_dashboard_save_of_a_file_without_the_switch_never_gains_it():
    """The switch is never part of the dashboard's own save: a 2.5 file stays without it (carried only as written)."""
    from tests.test_settings_signatures import _dashboard_saved, _write
    _write({"target_language": "ja"})
    assert "connect_enabled" not in _dashboard_saved()
    _write({"target_language": "ja", "connect_enabled": True})
    assert _dashboard_saved()["connect_enabled"] is True


def test_switching_on_sets_the_watermark_so_an_item_placed_before_is_never_queued():
    from app import main
    from app.connect import inbox, library
    from app.connect.ledger import Ledger
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
    with c.store() as s, Ledger() as ledger:
        inbox.consume(s, "ja", ledger)                              # Connect ran once (its reader set), then off
    with c.store() as s:
        library.place(s, s.ids("now")[-1], "now", source="user")   # placed into the top 2 while the switch was off
    window = _stand_in(True)
    main.MasterDashboardApp._connect_switched(window, True)
    with c.store() as s, Ledger() as ledger:
        assert inbox.consume(s, "ja", ledger)["queued"] == [], "nothing placed before the switch-on is mined"
    assert any("back-fill is skipped" in line for line in window.lines if isinstance(line, str))
    assert window.queued == ["controls and line"], "then the controls and the line"


def _pump(root, until, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def dashboard(monkeypatch):
    from app.main import MasterDashboardApp
    made = []

    def make():
        try:
            root = tk.Tk()
        except tk.TclError:
            pytest.skip("Tk is not available in this environment")
        root.withdraw()
        monkeypatch.setattr(tk, "_default_root", root)
        made.append(root)
        with patch.object(MasterDashboardApp, "check_updates_thread"):
            return MasterDashboardApp(root)
    yield make
    for root in made:
        try:
            root.destroy()
        except Exception:
            pass


def test_with_the_switch_off_settings_shows_it_imports_nothing_of_connect_and_writes_nothing(dashboard, monkeypatch):
    h.write_settings(target_language="ja", theme="Dark Flow")
    app = dashboard()
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    before = settings_bytes()
    app.toggle_settings_window()
    app.root.update()
    assert app.chk_connect.cget("text") == "Make cards automatically (preview)"
    assert app.var_connect_enabled.get() is False
    assert app._connect_panel is None and app._connect_row is None
    assert not [m for m in sys.modules if m.startswith("app.connect")], "nothing of Connect imported"
    assert settings_bytes() == before, "nothing written"
    # Esc closes (hides) Settings
    app.settings_window.focus_force()
    app.root.update()
    app.settings_window.event_generate("<Escape>")
    app.root.update()
    assert app.settings_window.state() == "withdrawn"


def test_switched_on_in_settings_the_controls_and_the_line_appear_and_off_they_go(dashboard):
    c.library()
    app = dashboard()
    h.write_settings(target_language="ja", connect_enabled=False)
    app.load_settings()
    app.toggle_settings_window()
    app.var_connect_enabled.set(True)
    app._connect_switch_toggled()
    assert _pump(app.root, lambda: app._connect_panel is not None and app._connect_row is not None)
    assert read_settings()["connect_enabled"] is True
    with c.store() as s:
        from app.connect import library
        assert library.has_reader(s), "the watermark is set"
    row = app._connect_row.frame
    assert row.winfo_manager() == "pack" and row.pack_info()["side"] == "bottom"
    # Another language shows its own cap (each language's: SD4)
    from app import settings_manager
    settings_manager.save_keys({"connect_backlog_cap": {"ja": 200, "zh": 80}})
    app.var_language.set("zh")
    app.root.update()
    assert app._connect_panel.var_cap.get() == "80"
    app.var_connect_enabled.set(False)
    app._connect_switch_toggled()
    app.root.update()
    assert app._connect_panel is None and app._connect_row is None and not row.winfo_exists()
    assert read_settings()["connect_enabled"] is False
