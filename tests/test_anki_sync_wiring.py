"""Dashboard wiring for the live Anki → Known Words sync (Anki_Known_Sync_Spec.md §5.7).

The engine is covered by test_anki_sync.py and the window by test_anki_sync_gui.py; this file pins
the dashboard's side of the contract:

* the background auto-sync only runs when the user turned it on, has decks chosen for THIS language,
  and no sync is already running — and it is throttled, because FocusIn fires for every child widget;
* a sync that added words refreshes the commonness preview straight away (otherwise it waits for the
  next FocusIn to notice the known words changed);
* the auto path can never Replace — replacing is a button, never a side effect;
* settings that another window writes are carried through from DISK on every dashboard save. They
  used to be carried from the dashboard's own snapshot, which silently reverted (or dropped) the deck
  a user had just picked in the Junban or Anki window the next time any dashboard setting changed.

Same harness as tests/test_junban_toggle.py: tkinter is mocked and methods are called unbound on a
MagicMock standing in for the dashboard, so no window is ever built.
"""

import importlib
import inspect
import os
import sys
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class _DashboardHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_modules = set(sys.modules.keys())
        cls.patcher = patch.dict(sys.modules, {
            'tkinter': MagicMock(),
            'tkinter.ttk': MagicMock(),
            'tkinter.messagebox': MagicMock(),
            'app.path_utils': MagicMock(),
            'app.update_checker': MagicMock(),
            'app.onboarding_gui': MagicMock(),
        })
        cls.patcher.start()
        try:
            import app.main
            importlib.reload(app.main)
            cls.main = app.main
            cls.MasterDashboardApp = app.main.MasterDashboardApp
        except ImportError:
            cls.MasterDashboardApp = None

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        for mod in set(sys.modules.keys()) - cls._original_modules:
            sys.modules.pop(mod, None)
        sys.modules.pop('app.main', None)

    def setUp(self):
        if self.MasterDashboardApp is None:
            self.skipTest("app.main could not be imported")
        # Not spec'd: these methods read instance attributes (status_var, the settings vars…)
        # that a class spec doesn't list. Every attribute a test asserts on is set explicitly.
        self.app = MagicMock()
        self.app.status_var = MagicMock()
        self.app.var_anki_sync_auto = MagicMock()
        self.app.var_anki_sync_auto.get.return_value = True
        self.app.var_language = MagicMock()
        self.app.var_language.get.return_value = "ja"
        self.app._anki_sync_lock = threading.Lock()
        self.app._last_anki_sync = 0.0
        self.app._current_settings = {}
        self.app.gui_queue = MagicMock()
        # conftest sets this for every test so nothing reaches a live Anki; these tests capture the
        # thread instead of running it, so they lift it explicitly.
        self.env = patch.dict(os.environ)
        self.env.start()
        os.environ.pop("SURASURA_NO_ANKI_SYNC", None)

    def tearDown(self):
        self.env.stop()

    def _settings(self, decks=("TheBank",), lang="ja"):
        return {"anki_sync_decks": {lang: list(decks)}, "anki_sync_fields": {lang: []},
                "anki_sync_include_suspended": False}

    def _call_sync(self, settings, force=False, synced_before=True):
        """Run _maybe_anki_sync with a captured Thread; returns the Thread mock. `synced_before`
        is whether the user has pressed Sync now at least once for this language."""
        from app import anki_sync
        state = {"last_sync": "2026-09-18T12:00:00"} if synced_before else {}
        with patch.object(self.main.settings_manager, "load_settings", return_value=settings), \
             patch.object(anki_sync, "load_state", return_value=state), \
             patch.object(self.main.threading, "Thread") as thread:
            self.MasterDashboardApp._maybe_anki_sync(self.app, force=force)
        return thread


class TestAutoSyncGate(_DashboardHarness):
    def test_nothing_happens_when_auto_sync_is_off(self):
        """Opt-in (spec I8): the toggle defaults off and a closed toggle means no probe at all."""
        self.app.var_anki_sync_auto.get.return_value = False
        self._call_sync(self._settings()).assert_not_called()

    def test_nothing_happens_without_decks_for_this_language(self):
        """Decks are per language (D8): Japanese decks must not be synced into Chinese known words."""
        self.app.var_language.get.return_value = "zh"
        self._call_sync(self._settings(lang="ja")).assert_not_called()

    def test_a_sync_starts_when_on_and_decks_are_chosen(self):
        thread = self._call_sync(self._settings())
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs.get("daemon"))

    def test_the_first_sync_is_always_the_users_own(self):
        """Spec §5.6. The Anki window pre-picks every studied deck the moment it opens; if the user
        closes it without pressing Sync now, that unreviewed pick (sentence decks, kanji decks) must
        not be appended to their known words by a focus event — appends can't be taken back."""
        self._call_sync(self._settings(), force=True, synced_before=False).assert_not_called()

    def test_focus_in_is_throttled_to_one_sync_per_five_minutes(self):
        """FocusIn fires for every child widget; without a throttle, every click would sync."""
        self._call_sync(self._settings()).assert_called_once()
        self.app._anki_sync_lock.release()          # the captured thread never ran to release it
        self._call_sync(self._settings()).assert_not_called()

    def test_force_bypasses_the_throttle(self):
        """Startup and a language switch sync immediately."""
        self._call_sync(self._settings()).assert_called_once()
        self.app._anki_sync_lock.release()
        self._call_sync(self._settings(), force=True).assert_called_once()

    def test_a_running_sync_blocks_another(self):
        """The window's Sync now and the auto-sync append to the same file; never both at once."""
        self.app._anki_sync_lock.acquire()
        self._call_sync(self._settings(), force=True).assert_not_called()

    def test_the_test_guard_blocks_it(self):
        os.environ["SURASURA_NO_ANKI_SYNC"] = "1"
        self._call_sync(self._settings(), force=True).assert_not_called()

    def test_auto_sync_can_never_replace(self):
        """Replace rebuilds the known words from Anki alone. It is a button with a confirmation,
        never something a background task may do."""
        source = inspect.getsource(self.MasterDashboardApp._maybe_anki_sync)
        self.assertIn("anki_sync.sync(", source)
        self.assertNotIn(".replace(", source)
        self.assertNotIn("restore_previous", source)


class TestBacklogOnGenerate(_DashboardHarness):
    """Junban_Backlog_Spec WP-B7: Generate reads the Anki backlog in the background — only with the
    option on and decks chosen for this language (D5: a user without Anki pays nothing), never waited
    for, and without the "first sync is the user's own" gate: it writes the backlog file, never the
    known words."""

    def _call(self, settings, on=True):
        self.app.var_anki_backlog_on_generate = MagicMock()
        self.app.var_anki_backlog_on_generate.get.return_value = on
        with patch.object(self.main.settings_manager, "load_settings", return_value=settings),              patch.object(self.main.threading, "Thread") as thread:
            self.MasterDashboardApp._maybe_backlog_sync(self.app)
        return thread

    def test_nothing_happens_without_decks_or_with_the_option_off(self):
        self._call({"anki_sync_decks": {}}).assert_not_called()
        self._call(self._settings(), on=False).assert_not_called()

    def test_a_background_read_starts_with_decks_chosen(self):
        from app import anki_connect, anki_sync
        thread = self._call(self._settings())
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs.get("daemon"))
        with patch.object(anki_connect, "probe", return_value={"ok": True}),              patch.object(anki_sync, "sync_backlog", return_value=(3, None)) as read:
            thread.call_args.kwargs["target"]()
        read.assert_called_once_with("ja", anki_connect.DEFAULT_URL, ["TheBank"], [])


class TestAfterASync(_DashboardHarness):
    def _result(self, added=0, mode="delta", error=None):
        return SimpleNamespace(added=added, mode=mode, error=error, total_known=0, scanned=3)

    def test_new_words_refresh_the_commonness_preview_at_once(self):
        self.MasterDashboardApp._on_anki_sync_result(self.app, self._result(added=12), auto=False)
        self.app._maybe_launch_indexer.assert_called_once_with(force=True)

    def test_nothing_new_means_no_reindex(self):
        self.MasterDashboardApp._on_anki_sync_result(self.app, self._result(added=0), auto=False)
        self.app._maybe_launch_indexer.assert_not_called()

    def test_an_error_changes_nothing(self):
        self.MasterDashboardApp._on_anki_sync_result(self.app, self._result(error="オフライン"), auto=True)
        self.app._maybe_launch_indexer.assert_not_called()
        self.app.status_var.set.assert_not_called()

    def test_a_replace_or_restore_always_reindexes(self):
        """Both can SHRINK the known words, which also changes the preview."""
        for mode in ("replace", "restore"):
            self.app._maybe_launch_indexer.reset_mock()
            self.MasterDashboardApp._on_anki_sync_result(self.app, self._result(mode=mode), auto=False)
            self.app._maybe_launch_indexer.assert_called_once_with(force=True)

    def test_a_quiet_auto_sync_says_so_on_the_status_bar(self):
        self.MasterDashboardApp._on_anki_sync_result(self.app, self._result(added=3), auto=True)
        self.app.status_var.set.assert_called_with("✓ Anki: +3 known words")


class TestSettingsCarryThrough(_DashboardHarness):
    def _save(self, on_disk, snapshot):
        self.app._current_settings = snapshot
        self.app.logic_settings = {}
        self.app._iv.side_effect = lambda var, default: default
        self.app.combo_theme.get.return_value = "Dark Flow"
        saved = {}
        with patch.object(self.main.settings_manager, "load_settings", return_value=on_disk), \
             patch.object(self.main.settings_manager, "save_settings",
                          side_effect=lambda s: saved.update(s)):
            self.MasterDashboardApp.save_settings(self.app, skip_ui=True)
        return saved

    def test_the_anki_windows_choices_survive_a_dashboard_save(self):
        """The Anki window saves decks/fields itself. The dashboard's snapshot predates that save;
        carrying from the snapshot threw the user's choice away on the next toggle."""
        disk = {"anki_sync_decks": {"ja": ["TheBank", "The Accelerator"]},
                "anki_sync_fields": {"ja": ["Expression"]},
                "anki_sync_include_suspended": True,
                "anki_connect_url": "http://127.0.0.1:8765"}
        stale = {"anki_sync_decks": {}, "anki_sync_fields": {}}
        saved = self._save(disk, stale)
        self.assertEqual(saved["anki_sync_decks"], {"ja": ["TheBank", "The Accelerator"]})
        self.assertEqual(saved["anki_sync_fields"], {"ja": ["Expression"]})
        self.assertTrue(saved["anki_sync_include_suspended"])

    def test_the_junban_deck_survives_a_dashboard_save(self):
        """The same bug, found while building this: pick a deck in 順, change any dashboard
        setting, and junban_deck reverted to whatever the dashboard loaded at startup."""
        disk = {"junban_deck": "TheBank", "junban_scope": "deck"}
        stale = {"junban_deck": "Default", "junban_scope": "all"}
        with patch.dict(sys.modules):
            fake = MagicMock()
            fake.SETTINGS_DEFAULTS = {"enable_junban": True, "junban_deck": "", "junban_scope": "deck"}
            parent = MagicMock()
            parent.junban = fake
            sys.modules['modules'] = parent
            sys.modules['modules.junban'] = fake
            saved = self._save(disk, stale)
        self.assertEqual(saved.get("junban_deck"), "TheBank")
        self.assertEqual(saved.get("junban_scope"), "deck")

    def test_the_auto_toggle_is_written_from_its_checkbox(self):
        self.app.var_anki_sync_auto.get.return_value = True
        saved = self._save({}, {})
        self.assertIs(saved["anki_sync_auto"], True)


class TestJunbanAutoReorder(_DashboardHarness):
    """The dashboard's side of Junban's automatic reorder — a test option (`junban_auto_reorder`
    in settings.json). The dashboard only SCHEDULES it, after a Generate and when focus returns, the
    way it schedules the Anki sync; every decision to write is the module's (`auto.run_quietly`),
    which has its own suite. The module is stood in here, so this file never needs `modules/`."""

    def setUp(self):
        super().setUp()
        self.app.var_enable_junban = MagicMock()
        self.app.var_enable_junban.get.return_value = True
        self.app._junban_auto_lock = threading.Lock()
        self.app._last_junban_auto = 0.0
        self.app.junban_window = None
        self.auto = types.ModuleType("modules.junban.auto")
        self.auto.enabled = lambda settings: settings.get("junban_auto_reorder") is True
        self.auto.run_quietly = MagicMock(return_value="")

    def _modules(self):
        parent, junban = types.ModuleType("modules"), types.ModuleType("modules.junban")
        parent.junban, junban.auto = junban, self.auto
        return {"modules": parent, "modules.junban": junban, "modules.junban.auto": self.auto}

    def _call(self, settings, force=False, modules=None):
        with patch.dict(sys.modules, self._modules() if modules is None else modules), \
             patch.object(self.main.settings_manager, "load_settings", return_value=settings), \
             patch.object(self.main.threading, "Thread") as thread:
            self.MasterDashboardApp._maybe_junban_auto(self.app, force=force)
        return thread

    def test_nothing_happens_unless_switched_on_in_settings(self):
        self._call({}).assert_not_called()
        self._call({"junban_auto_reorder": False}, force=True).assert_not_called()

    def test_it_runs_in_the_background_with_the_spinner_on(self):
        thread = self._call({"junban_auto_reorder": True})
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs.get("daemon"))
        self.app._junban_spinner.assert_called_with(True)

    def test_focus_is_throttled_but_a_generate_is_not(self):
        """When focus returns: at most every five minutes, like the Anki sync. After a Generate the
        list has just changed, so it runs at once."""
        self._call({"junban_auto_reorder": True}).assert_called_once()
        self.app._junban_auto_lock.release()          # the captured thread never ran to release it
        self._call({"junban_auto_reorder": True}).assert_not_called()
        self._call({"junban_auto_reorder": True}, force=True).assert_called_once()

    def test_never_while_the_junban_window_is_open(self):
        """The user is ordering by hand there; a write underneath would leave their preview
        describing a queue that has moved."""
        self.app.junban_window = MagicMock()
        self.app.junban_window.winfo_exists.return_value = True
        self._call({"junban_auto_reorder": True}, force=True).assert_not_called()

    def test_a_build_without_the_module_is_untouched(self):
        """The Prime Invariant: no `modules/junban`, nothing scheduled and nothing raised."""
        self._call({"junban_auto_reorder": True}, force=True,
                   modules={"modules.junban": None}).assert_not_called()

    def test_the_test_guard_blocks_it(self):
        os.environ["SURASURA_NO_ANKI_SYNC"] = "1"
        self._call({"junban_auto_reorder": True}, force=True).assert_not_called()

    def test_the_run_reads_the_dashboards_live_language(self):
        self.app.var_language.get.return_value = "zh"
        thread = self._call({"junban_auto_reorder": True, "target_language": "ja"})
        thread.call_args.kwargs["target"]()
        self.assertEqual(self.auto.run_quietly.call_args.args[0]["target_language"], "zh")

    def test_a_generate_triggers_it_whether_or_not_the_analysis_ran(self):
        """The analyzer's own completion AND the fast path that only reopens the report."""
        source = inspect.getsource(self.MasterDashboardApp.run_analyzer)
        self.assertEqual(source.count("_maybe_junban_auto(force=True)"), 2)

    def test_a_reason_to_wait_is_said_once_not_every_five_minutes(self):
        self.app._last_junban_auto_message = ""
        for _ in range(3):
            self.MasterDashboardApp._on_junban_auto(self.app, "順 automatic reorder waits: one deck")
        self.app.log_to_terminal.assert_called_once()


class TestSyncSettingsAreNotAnalysis(unittest.TestCase):
    def test_changing_decks_does_not_force_a_reanalysis(self):
        """Spec I9: every deck click re-analysing the whole library would be absurd."""
        from app import analyzer
        source = inspect.getsource(analyzer.compute_run_signature)
        for key in ("anki_connect_url", "anki_sync_auto", "anki_sync_decks", "anki_sync_fields",
                    "anki_sync_include_suspended"):
            self.assertIn(f'"{key}"', source, f"{key} must be excluded from the run signature")


if __name__ == '__main__':
    unittest.main()
