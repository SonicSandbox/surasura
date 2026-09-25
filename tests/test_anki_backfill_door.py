"""The core's doors to Anki Backfill (git-tracked; the module itself is not).

Anki Backfill lives in the optional Junban module. The core reaches it through three thin hooks, and
this file pins each — they must hold with or without the module on disk (the Prime Invariant):

  * the dashboard's `backfill_available()` is True only while Junban is switched on AND importable
    (the user, 2026-09-24: "if it is turned off (junban) … they can't see the option in the anki tab");
  * the Anki window shows "Backfill cards…" only when its dashboard says so, re-checks when the Junban
    toggle changes, and never imports a module itself (Anki_Known_Sync_Spec I1);
  * a packaged build can run the library's パターン rebuild: `Surasura.exe junban_patterns`.
"""

import inspect
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    _ROOT = tk.Tk()
    _ROOT.withdraw()
except Exception:   # no display
    _ROOT = None


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class TestDashboardOffersBackfillOnlyWithJunban(unittest.TestCase):
    def _dashboard(self, junban_on):
        return SimpleNamespace(var_enable_junban=_Var(junban_on))

    def test_junban_switched_off_hides_it(self):
        from app.main import MasterDashboardApp
        self.assertFalse(MasterDashboardApp.backfill_available(self._dashboard(False)))

    def test_junban_missing_from_the_build_hides_it(self):
        from app.main import MasterDashboardApp
        with patch.dict(sys.modules, {"modules.junban": None}):      # forces ImportError
            self.assertFalse(MasterDashboardApp.backfill_available(self._dashboard(True)))

    def test_junban_on_and_installed_offers_it(self):
        from app.main import MasterDashboardApp
        stand_in = MagicMock()
        with patch.dict(sys.modules, {"modules.junban": stand_in}):
            self.assertTrue(MasterDashboardApp.backfill_available(self._dashboard(True)))

    def test_opening_it_with_junban_off_does_nothing(self):
        from app.main import MasterDashboardApp
        stand_in = MagicMock()
        with patch.dict(sys.modules, {"modules.junban": stand_in}):
            dashboard = self._dashboard(False)
            dashboard.backfill_available = lambda: MasterDashboardApp.backfill_available(dashboard)
            MasterDashboardApp.open_backfill(dashboard)
        stand_in.open_backfill.assert_not_called()

    def test_the_junban_toggle_tells_an_open_anki_window(self):
        from app.main import MasterDashboardApp
        window = MagicMock()
        dashboard = SimpleNamespace(var_enable_junban=_Var(False), btn_junban=MagicMock(),
                                    anki_sync_window=window,
                                    _module_slot=lambda button: None)
        MasterDashboardApp.update_junban_visibility(dashboard)
        window.sync_backfill_button.assert_called_once_with()


@unittest.skipIf(_ROOT is None, "no display")
class TestAnkiWindowButton(unittest.TestCase):
    def _window(self, offered):
        from app import anki_sync_gui
        host = MagicMock()
        host.var_anki_sync_auto = tk.BooleanVar(master=_ROOT, value=False)
        host.var_anki_auto_generate = tk.BooleanVar(master=_ROOT, value=False)
        host.backfill_available.return_value = offered
        window = anki_sync_gui.AnkiSyncGui(_ROOT, app=host, language="ja")
        window.withdraw()
        self.addCleanup(window.destroy)
        return window, host

    def test_hidden_when_the_dashboard_says_no(self):
        window, _host = self._window(offered=False)
        self.assertEqual(window.btn_backfill.winfo_manager(), "")

    def test_shown_when_offered_and_it_opens_through_the_dashboard(self):
        window, host = self._window(offered=True)
        self.assertEqual(window.btn_backfill.winfo_manager(), "pack")
        window.btn_backfill.invoke()
        host.open_backfill.assert_called_once_with()

    def test_it_follows_the_toggle_while_the_window_is_open(self):
        window, host = self._window(offered=True)
        host.backfill_available.return_value = False
        window.sync_backfill_button()
        self.assertEqual(window.btn_backfill.winfo_manager(), "")
        host.backfill_available.return_value = True
        window.sync_backfill_button()
        self.assertEqual(window.btn_backfill.winfo_manager(), "pack")

    def test_standalone_there_is_no_button(self):
        from app import anki_sync_gui
        window = anki_sync_gui.AnkiSyncGui(_ROOT, app=None, language="ja")
        window.withdraw()
        self.addCleanup(window.destroy)
        self.assertEqual(window.btn_backfill.winfo_manager(), "")

    def test_the_window_imports_no_module(self):
        import app.anki_sync_gui as source
        self.assertNotRegex(inspect.getsource(source), r"(?m)^\s*(from|import)\s+modules\b")


class TestPackagedRebuild(unittest.TestCase):
    def test_app_entry_dispatches_the_rebuild_and_passes_its_exit_code_on(self):
        # `patterns_build.main()` RETURNS 1 on failure; without sys.exit a failed build exits 0.
        import app_entry
        dispatch = inspect.getsource(app_entry.main)
        self.assertIn("command == 'junban_patterns'", dispatch)
        self.assertIn("sys.exit(patterns_build.main())", dispatch)


if __name__ == "__main__":
    unittest.main()
