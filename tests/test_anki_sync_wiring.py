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

import ast
import importlib
import inspect
import os
import sys
import textwrap
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class _RunsAtOnce:
    """threading.Thread whose start() runs the target right away — a child process's whole life
    inside one call, so run_command_async can be followed to its end without a real thread."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        self._target()


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
        self.app._last_anki_sync = float("-inf")   # "never", as the dashboard starts: 0.0 read as "just now" on a machine booted minutes ago
        self.app._current_settings = {}
        self.app.gui_queue = MagicMock()
        # "Generate when Anki adds known words" did not start a Generate — the default, option off.
        self.app._maybe_auto_generate.return_value = False
        self.app._generate_running = None               # no Generate running…
        self.app._open_report_when_generated = False    # …and no press waiting for one
        # conftest sets this for every test so nothing reaches a live Anki; these tests capture the
        # thread instead of running it, so they lift it explicitly.
        self.env = patch.dict(os.environ)
        self.env.start()
        os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
        # Generate's press asks whether the report still holds on a worker (`_report_reusable`; in place under
        # test, SURASURA_NO_UI_TIMERS) and goes on in `_generate_checked`. The stand-in's
        # `_try_open_existing_report` mock stays the one question the tests set and count: "reusable" when True.
        self._real("_run_on_worker", "_generate_checked", "_start_analyzer")
        self.app._report_reusable.side_effect = (
            lambda args: object() if self.app._try_open_existing_report(args) else None)
        self.app._open_existing_report.return_value = True

    def tearDown(self):
        self.env.stop()

    def _settings(self, decks=("TheBank",), lang="ja"):
        return {"anki_sync_decks": {lang: list(decks)}, "anki_sync_fields": {lang: []},
                "anki_sync_include_suspended": False}

    def _initial_value(self, name):
        """What the dashboard's __init__ sets `self.<name>` to — read from its source and evaluated,
        since building the window is exactly what this harness avoids."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(self.MasterDashboardApp.__init__)))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Attribute) and node.targets[0].attr == name):
                return eval(compile(ast.Expression(node.value), "__init__", "eval"), {"float": float})
        raise AssertionError(f"__init__ never sets self.{name}")

    def _real(self, *names):
        """The dashboard's own methods for these names on the stand-in — looked up when called; every
        other attribute stays a mock."""
        def bind(name):
            return lambda *args, **kwargs: getattr(self.MasterDashboardApp, name)(self.app, *args, **kwargs)
        for name in names:
            setattr(self.app, name, bind(name))

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

    def test_the_first_focus_after_the_computer_starts_syncs(self):
        """On Windows time.monotonic() counts from when the computer started, and the throttle began
        at 0.0 — "synced just now" — so no focus sync ran in the first 5 minutes after a boot. It
        begins as never."""
        self.app._last_anki_sync = self._initial_value("_last_anki_sync")
        with patch("time.monotonic", return_value=30.0):      # 30 s after the computer started
            self._call_sync(self._settings()).assert_called_once()

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

    def test_the_auto_generate_toggle_is_written_from_its_checkbox(self):
        """save_settings() rebuilds settings.json from scratch — a key it does not list is dropped on
        the next save (CLAUDE.md), and the checkbox would reset itself."""
        self.app.var_anki_auto_generate.get.return_value = True
        saved = self._save({}, {})
        self.assertIs(saved["anki_auto_generate"], True)


class TestAutoGenerate(_DashboardHarness):
    """"Generate when Anki adds known words" (Settings → Data & System). The user's choices,
    2026-09-23: only new known words from Anki trigger it (new episodes are theirs to order first);
    quiet — the report is written, not opened; at most every 10 minutes; never while a Generate, an
    import, the indexer or the Content Manager is running — each is a child process of the window."""

    def setUp(self):
        super().setUp()
        self.app.var_anki_auto_generate = MagicMock()
        self.app.var_anki_auto_generate.get.return_value = True
        self.app._auto_generate_pending = True
        self.app._last_auto_generate = float("-inf")   # "never", as the dashboard starts (see above)
        self.app.active_processes = []
        self.app._library_has_content.return_value = True

    def _try(self):
        return self.MasterDashboardApp._maybe_auto_generate(self.app)

    def test_it_runs_quietly_once_anki_has_brought_words_in(self):
        self.assertTrue(self._try())
        self.app.run_analyzer.assert_called_once_with(quiet=True)

    def test_nothing_without_new_words_from_anki_or_with_the_option_off(self):
        self.app._auto_generate_pending = False
        self.assertFalse(self._try())
        self.app._auto_generate_pending = True
        self.app.var_anki_auto_generate.get.return_value = False
        self.assertFalse(self._try())
        self.app.run_analyzer.assert_not_called()

    def test_never_while_anything_else_runs_and_it_waits_rather_than_forgets(self):
        """The Content Manager, an importer, the indexer or a Generate — all child processes. The
        words will not come in a second time, so the Generate stays pending for the next chance."""
        running = MagicMock()
        running.poll.return_value = None
        self.app.active_processes = [running]
        self.assertFalse(self._try())
        self.assertTrue(self.app._auto_generate_pending)
        running.poll.return_value = 0          # it finished
        self.assertTrue(self._try())

    def test_at_most_every_ten_minutes(self):
        self.assertTrue(self._try())
        self.app._auto_generate_pending = True
        self.assertFalse(self._try())
        self.assertEqual(self.app.run_analyzer.call_count, 1)

    def test_the_test_guard_blocks_it(self):
        os.environ["SURASURA_NO_ANKI_SYNC"] = "1"
        self.assertFalse(self._try())

    def test_the_first_automatic_generate_after_the_computer_starts_is_not_refused(self):
        """Measured on the user's machine: time.monotonic() read 615,137 against an uptime of
        615,136 s — it counts from the computer's start. The limit began at 0.0, so for the first 10
        minutes after a boot every automatic Generate was "too soon": the status bar said Anki brought
        words in, and the button stayed blue. The tests above pass only because a dev machine stays up
        for days."""
        self.app._last_auto_generate = self._initial_value("_last_auto_generate")
        with patch("time.monotonic", return_value=30.0):      # 30 s after the computer started
            self.assertTrue(self._try())
        self.app.run_analyzer.assert_called_once_with(quiet=True)

    def test_a_generate_held_back_by_the_ten_minute_limit_runs_when_the_limit_is_up(self):
        """The limit used to return False and nothing more: words from a second sync inside the 10
        minutes left the button blue, in plain sight, until the next click into the window. When the
        limit is all that holds a Generate back, ONE alarm is set for the moment it is up — a later try
        replaces it, never stacks a second — and the alarm asks everything again. Never scheduled
        under test (testing.md §5.4), and not for a Generate something else holds back: that one is
        asked again when the something ends."""
        self.app._last_auto_generate = 1000.0          # the last automatic Generate ran at t = 1,000 s
        self.app._auto_generate_job = None
        self.app.root.after.side_effect = ["after#1", "after#2"]
        with patch("time.monotonic", return_value=1100.0):     # 100 s later: 500 s to go
            self.assertFalse(self._try())
            self.app.root.after.assert_not_called()             # SURASURA_NO_UI_TIMERS (conftest)
            os.environ.pop("SURASURA_NO_UI_TIMERS", None)
            content_manager = MagicMock()
            content_manager.poll.return_value = None
            self.app.active_processes = [content_manager]
            self.assertFalse(self._try())
            self.app.root.after.assert_not_called()             # not the limit alone
            content_manager.poll.return_value = 0               # the Content Manager closed
            self.assertFalse(self._try())
        self.app.run_analyzer.assert_not_called()
        self.assertIsNotNone(self.app.root.after.call_args, "the limit alone holds it back: an alarm")
        delay, alarm = self.app.root.after.call_args.args
        self.assertEqual(delay, 500_000)
        self.assertIs(alarm, self.app._auto_generate_alarm)

        with patch("time.monotonic", return_value=1400.0):     # a click into the window, 300 s later
            self.assertFalse(self._try())
        self.app.root.after_cancel.assert_called_once_with("after#1")
        self.assertEqual(self.app.root.after.call_args.args[0], 200_000)
        self.assertEqual(self.app._auto_generate_job, "after#2")

        self.app._maybe_auto_generate = lambda: self.MasterDashboardApp._maybe_auto_generate(self.app)
        with patch("time.monotonic", return_value=1600.0):     # the alarm: the limit is up
            self.MasterDashboardApp._auto_generate_alarm(self.app)
        self.app.run_analyzer.assert_called_once_with(quiet=True)
        self.assertIsNone(self.app._auto_generate_job)
        self.assertEqual(self.app.root.after.call_count, 2)

    def test_a_generate_waiting_for_the_content_manager_runs_when_it_closes(self):
        """Every child process holds the automatic Generate back — by design (the user, 2026-09-23).
        But only the indexer's exit asked again, so one held back by the Content Manager (or an
        importer, or the frequency-list window) waited, the button blue, for the next click into the
        window. Any child's exit asks again now."""
        self.app._last_auto_generate = float("-inf")
        queued = []
        self.app.gui_queue.put.side_effect = queued.append
        self.app._maybe_auto_generate = lambda: self.MasterDashboardApp._maybe_auto_generate(self.app)
        content_manager = MagicMock()
        content_manager.poll.return_value = None
        content_manager.returncode = 0
        held_back = []

        def anki_words_arrive_then_the_user_closes_it():
            held_back.append(self._try())               # the sync's words, while it is open
            content_manager.poll.return_value = 0

        content_manager.wait.side_effect = anki_words_arrive_then_the_user_closes_it
        with patch.object(self.main.subprocess, "Popen", return_value=content_manager), \
             patch.object(self.main.threading, "Thread", _RunsAtOnce):
            self.MasterDashboardApp.run_command_async(
                self.app, ["content_importer_gui.py", "--language", "ja"], "Content Importer")
        self.assertEqual(held_back, [False])
        self.assertTrue(self.app._auto_generate_pending, "held back, not forgotten")
        self.app.run_analyzer.assert_not_called()
        for task in queued:                             # the GUI thread's queue, in order
            task()
        self.app.run_analyzer.assert_called_once_with(quiet=True)

    def test_a_late_up_to_date_answer_never_overwrites_a_newer_one(self):
        """Each check asks on a worker thread, and two can overlap: one asked during a Generate (the
        analyzer dropped its stamp — not up to date) and one asked when it finished (up to date).
        Nothing stopped the older answer landing last and leaving the button blue after a good run."""
        self.app._journey_gen = 0
        queued = []
        self.app.gui_queue.put.side_effect = queued.append
        with patch.object(self.main.threading, "Thread") as thread:
            self.MasterDashboardApp._refresh_journey_state(self.app)     # asked during the run
            self.MasterDashboardApp._refresh_journey_state(self.app)     # asked when it finished
        during, after = (call.kwargs["target"] for call in thread.call_args_list)
        with patch.object(self.main, "journey_is_current", return_value=True):
            after()
        with patch.object(self.main, "journey_is_current", return_value=False):
            during()                                    # the older answer lands last
        for task in queued:
            task()
        self.app._set_journey_state.assert_called_once_with(True)

    @staticmethod
    def _process(returncode):
        """A child process as Popen hands it back: the analyzer's log, then its exit code."""
        process = MagicMock()
        process.stdout = ["Final Count: Found 12 files to process.\n"]
        process.returncode = returncode
        return process

    def test_generate_pressed_during_an_automatic_generate_opens_the_report_when_it_finishes(self):
        """D7. During the automatic run the button is blue (the analyzer dropped its stamp) and
        nothing showed it running, so a press started a SECOND full analysis beside it — both writing
        results/ and the report, one able to read the other's half-written CSV. Now the press shows it
        is working and waits; when the automatic run ends, the normal Generate runs, and it reopens
        the report at once because the journey is up to date."""
        self._real("run_analyzer")
        self.app._last_auto_generate = float("-inf")
        self.app._analyzer_args.side_effect = lambda: ["analyzer.py", "--static", "--language=ja"]
        self.app._try_open_existing_report.return_value = False     # mid-run: never up to date
        self.assertTrue(self._try())                                  # Anki's words: it starts
        self.assertEqual(self.app.run_command_async.call_count, 1)

        self.MasterDashboardApp.run_analyzer(self.app)               # the user presses Generate
        self.assertEqual(self.app.run_command_async.call_count, 1, "never a second analysis")
        self.app._try_open_existing_report.assert_not_called()
        self.app.spinner.start.assert_called_once()                  # it shows it is working
        self.app.status_var.set.assert_called_with(
            "Already generating — the report opens when it's done.")

        self.assertIs(self.app.run_command_async.call_args.kwargs["on_exit"], self.app._on_generate_exit)
        self.app._try_open_existing_report.return_value = True       # the run left it up to date
        self.MasterDashboardApp._on_generate_exit(self.app)          # …and its process ended
        self.app._try_open_existing_report.assert_called_once()      # the report opens, at once
        self.assertEqual(self.app.run_command_async.call_count, 1)
        self.assertIsNone(self.app._generate_running)
        self.assertFalse(self.app._open_report_when_generated)

    def test_generate_pressed_during_a_generate_never_starts_a_second_analysis(self):
        """A double-click on Generate, or a press while its run is still going, started a second full
        analysis beside the first. Now nothing starts and the status bar says it is already
        generating — the running one opens the report itself. 順's "Generate & preview" asking for a
        quiet run meanwhile starts nothing either (the running one tells 順 when it's done). And a
        press that starts nothing leaves Anki's words pending: the running Generate may have begun
        before they came in."""
        self._real("run_analyzer")
        self.app._analyzer_args.side_effect = lambda: ["analyzer.py", "--static", "--language=ja"]
        self.app._try_open_existing_report.return_value = False     # something changed: a real run
        self.MasterDashboardApp.run_analyzer(self.app)               # the press
        self.assertEqual(self.app.run_command_async.call_count, 1)
        self.app._auto_generate_pending = True                       # Anki's words, mid-run
        self.MasterDashboardApp.run_analyzer(self.app)               # the double-click
        self.MasterDashboardApp.run_analyzer(self.app, quiet=True)   # 順's "Generate & preview"
        self.assertEqual(self.app.run_command_async.call_count, 1, "never a second analysis")
        self.app.status_var.set.assert_called_once_with(
            "Already generating — the report opens when it's done.")
        self.assertTrue(self.app._auto_generate_pending, "the running Generate may predate them")
        self.assertFalse(self.app._open_report_when_generated, "the running one opens it itself")

        self.MasterDashboardApp._on_generate_exit(self.app)          # it ended
        self.assertEqual(self.app._try_open_existing_report.call_count, 1, "nothing reopens after")
        self.MasterDashboardApp.run_analyzer(self.app)               # the next press starts one
        self.assertEqual(self.app.run_command_async.call_count, 2)

    def test_the_running_generate_is_forgotten_however_it_ends(self):
        """Finished, failed (exit code 1), or never started — Popen raised, a path that never called
        on_complete: every way, the next Generate may run. A flag that stuck would refuse every
        Generate until the app was restarted. While it runs, a press starts nothing."""
        self._real("run_analyzer", "run_command_async", "_on_generate_exit")
        self.app._analyzer_args.side_effect = lambda: ["analyzer.py", "--static", "--language=ja"]
        self.app._try_open_existing_report.return_value = False
        self.app.active_processes = []
        queued = []
        self.app.gui_queue.put.side_effect = queued.append
        endings = (("finished", {"return_value": self._process(0)}),
                   ("failed", {"return_value": self._process(1)}),
                   ("never started",
                    {"side_effect": FileNotFoundError(2, "The system cannot find the file specified")}))
        for ending, popen in endings:
            queued.clear()
            with patch.object(self.main.threading, "Thread") as thread, \
                 patch.object(self.main.subprocess, "Popen", **popen):
                self.MasterDashboardApp.run_analyzer(self.app)           # Generate starts
                self.MasterDashboardApp.run_analyzer(self.app)           # a press while it runs
                self.assertEqual(thread.call_count, 1, ending)
                thread.call_args.kwargs["target"]()                      # the run, to its end
            for task in queued:                                          # the GUI thread's queue
                task()
            self.assertIsNone(self.app._generate_running, ending)

    def test_words_anki_brought_in_during_a_generate_are_generated_when_it_ends(self):
        """A running Generate holds the automatic one back — even in the moment before its process
        is listed — and Anki's words that arrive meanwhile may be newer than what it read. When it
        ends, the automatic Generate runs: the ended Generate is forgotten first, then the waiting
        one is asked again (in the other order, the Generate that just ended would refuse it)."""
        self._real("run_analyzer", "run_command_async", "_on_generate_exit", "_maybe_auto_generate")
        self.app._last_auto_generate = float("-inf")
        self.app._auto_generate_pending = False
        self.app._analyzer_args.side_effect = lambda: ["analyzer.py", "--static", "--language=ja"]
        self.app._try_open_existing_report.return_value = False
        self.app.active_processes = []
        queued = []
        self.app.gui_queue.put.side_effect = queued.append
        with patch.object(self.main.threading, "Thread") as thread, \
             patch.object(self.main.subprocess, "Popen", return_value=self._process(0)):
            self.MasterDashboardApp.run_analyzer(self.app)           # the user's Generate
            self.app._auto_generate_pending = True                   # Anki's words, mid-run…
            self.assertFalse(self._try())                            # …held back, never beside it
            self.assertEqual(thread.call_count, 1)
            thread.call_args.kwargs["target"]()                      # the Generate, to its end
            for task in list(queued):                                # the GUI thread's queue
                task()
            self.assertEqual(thread.call_count, 2, "the automatic Generate starts as it ends")
        self.assertEqual(self.app._generate_running, "automatic")
        self.assertFalse(self.app._auto_generate_pending)

    def test_the_check_mark_spot_spins_while_generating_automatically(self):
        """D8. The automatic Generate is quiet — no spinner, the button blue — so nothing said it was
        running. The check mark's spot on the button now shows the Anki button's braille spinner, with
        a tooltip saying why; the button itself is never touched, so it never changes size. A check
        that lands meanwhile still sets the border but leaves the spot to the spinner. When the run
        ends, the spot empties until the up-to-date check answers: ✓, or the blue border if it
        failed."""
        self._real("run_analyzer", "_journey_spinner", "_set_journey_state", "_on_generate_exit")
        self.app._last_auto_generate = float("-inf")
        self.app._journey_spin_job = None
        self.app.root.after.return_value = "after#spin"
        self.app._analyzer_args.side_effect = lambda: ["analyzer.py", "--static", "--language=ja"]
        spot = self.app.lbl_journey_state
        self.assertTrue(self._try())                                   # Anki's words: it starts
        self.assertIsNotNone(spot.place.call_args, "the spinner takes the check mark's spot")
        placed = spot.place.call_args.kwargs
        self.assertIs(placed["in_"], self.app.btn_journey)
        self.assertEqual((placed["relx"], placed["anchor"]), (1.0, "e"))
        self.assertIn(spot.config.call_args.kwargs["text"], "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        self.assertEqual(self.MasterDashboardApp._journey_check_tip(self.app),
                         "Generating automatically — Anki brought in known words.")
        self.assertIn("ToolTip(self.lbl_journey_state, self._journey_check_tip)",
                      inspect.getsource(self.MasterDashboardApp.setup_ui))
        self.app._set_journey_state(False)                             # a check lands mid-run
        spot.place_forget.assert_not_called()
        self.app.journey_border.config.assert_called_with(
            highlightbackground=self.main.SURASURA_BLUE, highlightcolor=self.main.SURASURA_BLUE)
        self.app.btn_journey.config.assert_not_called()                # never resized or relabelled

        self.app.run_command_async.call_args.kwargs["on_exit"]()       # the run ended
        self.app.root.after_cancel.assert_called_with("after#spin")
        spot.config.assert_called_with(text="✓")
        spot.place_forget.assert_called_once()                         # empty until the check answers
        self.app._schedule_journey_state.assert_called()
        self.assertEqual(self.MasterDashboardApp._journey_check_tip(self.app),
                         "Up to date — nothing has changed since your last Generate.")
        self.app._set_journey_state(True)                              # it answers: up to date
        self.assertEqual(spot.place.call_count, 2)                     # the ✓ is back on the button

    # Anki's words belong to the language they came for. The alarm above and the child-exit retry can
    # fire with no one pressing anything, so a pending Generate that was simply True ran for whichever
    # language was open by then: Japanese words in, the alarm set, a switch to Chinese — and the alarm
    # ran a quiet CHINESE Generate, which cleared the flag. The Japanese words were never generated,
    # and Japanese stayed blue.
    _RESULT = SimpleNamespace(added=5, mode="delta", error=None, total_known=0, scanned=3)

    def test_japanese_words_wait_while_chinese_is_open_and_run_back_on_japanese(self):
        """The alarm going off on Chinese starts nothing and keeps the words; back on Japanese, the
        automatic Generate runs."""
        self.app._last_auto_generate = float("-inf")
        self.app._auto_generate_pending = "ja"
        self.app.var_language.get.return_value = "zh"                 # the user switched to Chinese
        self.app._maybe_auto_generate = lambda: self.MasterDashboardApp._maybe_auto_generate(self.app)
        self.MasterDashboardApp._auto_generate_alarm(self.app)        # the alarm goes off
        self.app.run_analyzer.assert_not_called()
        self.assertEqual(self.app._auto_generate_pending, "ja", "still waiting, for Japanese")
        self.app.var_language.get.return_value = "ja"                 # back on Japanese
        self.assertTrue(self._try())
        self.app.run_analyzer.assert_called_once_with(quiet=True)

    def test_a_chinese_generate_leaves_the_japanese_words_waiting(self):
        """Every Generate cleared the flag, whatever its language — a Chinese one too, which never
        read the Japanese words. A Generate uses up its own language's words only."""
        self.app._auto_generate_pending = "ja"
        self.app._try_open_existing_report.return_value = False
        self.app.var_language.get.return_value = "zh"
        self.app._analyzer_args.side_effect = lambda: ["analyzer.py", "--static", "--language=zh"]
        self.MasterDashboardApp.run_analyzer(self.app)                # the user's Chinese Generate
        self.assertEqual(self.app._auto_generate_pending, "ja")
        self.app._generate_running = None                             # it ended
        self.app.var_language.get.return_value = "ja"
        self.app._analyzer_args.side_effect = lambda: ["analyzer.py", "--static", "--language=ja"]
        self.MasterDashboardApp.run_analyzer(self.app)                # a Japanese one reads them
        self.assertFalse(self.app._auto_generate_pending)

    def test_a_sync_result_records_the_language_its_words_came_for(self):
        """The background sync and the Anki window say which language they read, whatever is open by
        the time the result lands; a caller that says none means the language open now."""
        self.app._auto_generate_pending = False
        self.app.var_language.get.return_value = "zh"                 # Chinese is open by now
        self.MasterDashboardApp._on_anki_sync_result(self.app, self._RESULT, auto=True, language="ja")
        self.assertEqual(self.app._auto_generate_pending, "ja")
        self.app._auto_generate_pending = False
        self.MasterDashboardApp._on_anki_sync_result(self.app, self._RESULT, auto=False)
        self.assertEqual(self.app._auto_generate_pending, "zh")

    def test_the_background_sync_hands_its_words_over_for_the_language_it_read(self):
        """It reads the language as it starts, on the GUI thread; its result comes back through the
        GUI queue, maybe after a switch — the words are still the language it read."""
        from app import anki_connect, anki_sync
        queued = []
        self.app.gui_queue.put.side_effect = queued.append
        thread = self._call_sync(self._settings())                    # a Japanese sync starts
        with patch.object(anki_connect, "probe", return_value={"ok": True}), \
             patch.object(anki_sync, "sync", return_value=self._RESULT), \
             patch.object(anki_sync, "sync_backlog", return_value=(0, None)):
            thread.call_args.kwargs["target"]()
        self.app.var_language.get.return_value = "zh"                 # a switch before it lands
        for task in queued:
            task()
        self.app._on_anki_sync_result.assert_called_once_with(self._RESULT, auto=True, language="ja")

    def test_a_sync_that_added_words_starts_it_instead_of_a_separate_reindex(self):
        """Generate re-reads the store itself; running the indexer beside it would only race it."""
        self.app._auto_generate_pending = False
        self.app._maybe_auto_generate.return_value = True
        result = SimpleNamespace(added=5, mode="delta", error=None, total_known=0, scanned=3)
        self.MasterDashboardApp._on_anki_sync_result(self.app, result, auto=True)
        self.assertTrue(self.app._auto_generate_pending)
        self.app._maybe_launch_indexer.assert_not_called()

    def test_the_quiet_generate_writes_without_opening_and_keeps_the_log(self):
        self.app._analyzer_args.return_value = ["analyzer.py", "--language=ja"]
        self.MasterDashboardApp.run_analyzer(self.app, quiet=True)
        args = self.app.run_command_async.call_args.args[0]
        kwargs = self.app.run_command_async.call_args.kwargs
        self.assertIn("--no-open", args)
        self.assertIs(kwargs["clear_log"], False)
        self.app._try_open_existing_report.assert_not_called()
        self.assertFalse(self.app._auto_generate_pending)

    def test_the_generate_button_shows_blue_when_it_has_work_and_a_check_when_not(self):
        self.MasterDashboardApp._set_journey_state(self.app, False)
        self.app.journey_border.config.assert_called_with(
            highlightbackground=self.main.SURASURA_BLUE, highlightcolor=self.main.SURASURA_BLUE)
        self.app.lbl_journey_state.place_forget.assert_called()
        self.MasterDashboardApp._set_journey_state(self.app, True)
        self.app.journey_border.config.assert_called_with(
            highlightbackground=self.main.BG_COLOR, highlightcolor=self.main.BG_COLOR)
        # ON the button, at its right edge — never a column of its own that shortens the button.
        placed = self.app.lbl_journey_state.place.call_args.kwargs
        self.assertIs(placed["in_"], self.app.btn_journey)
        self.assertEqual((placed["relx"], placed["anchor"]), (1.0, "e"))
        self.app.lbl_journey_state.pack.assert_not_called()

    def test_the_check_is_a_quiet_gray_and_goes_back_to_gray_after_a_hover(self):
        """The user, 2026-09-23: the teal check stood out too much. Gray at rest, dark on the lit
        button under the pointer, gray again when the pointer leaves."""
        self.MasterDashboardApp._light_journey_check(self.app, True)
        self.app.lbl_journey_state.config.assert_called_with(bg=self.main.ACCENT_COLOR, fg=self.main.BG_COLOR)
        self.MasterDashboardApp._light_journey_check(self.app, False)
        self.app.lbl_journey_state.config.assert_called_with(bg=self.main.SURFACE_COLOR, fg="#8a8a8a")


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
        self.app._last_junban_auto = float("-inf")   # "never", as the dashboard starts (see above)
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

    def test_the_first_focus_after_the_computer_starts_reorders(self):
        """The same clock that counts from the computer's start: 順's reorder on focus was refused for
        the first 5 minutes after a boot, like the Anki sync."""
        self.app._last_junban_auto = self._initial_value("_last_junban_auto")
        with patch("time.monotonic", return_value=30.0):
            self._call({"junban_auto_reorder": True}).assert_called_once()

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
        with patch.object(self.main, "journey_is_current", return_value=True):
            thread.call_args.kwargs["target"]()
        self.assertEqual(self.auto.run_quietly.call_args.args[0]["target_language"], "zh")

    def test_it_is_told_whether_the_list_is_up_to_date_by_the_generate_buttons_own_check(self):
        """Junban_Backlog_Spec §16.6: known words from Anki, a changed setting — not only a changed
        library — mean the list is behind, and the automatic reorder waits for a Generate. The
        arguments are read on the GUI thread; the check runs on the worker's."""
        self.app._analyzer_args.return_value = ["analyzer.py", "--static", "--language=ja"]
        thread = self._call({"junban_auto_reorder": True})
        with patch.object(self.main, "journey_is_current", return_value=False) as current:
            thread.call_args.kwargs["target"]()
        current.assert_called_once_with(["analyzer.py", "--static", "--language=ja"], "ja")
        self.assertIs(self.auto.run_quietly.call_args.kwargs["list_current"], False)

    def test_every_generate_tells_an_open_junban_window(self):
        """§16.9: the 順 window's "Generate & preview" waits for the dashboard's Generate — the
        analyzer's completion and the reopen-only fast path alike."""
        source = "".join(inspect.getsource(getattr(self.MasterDashboardApp, name))   # the press, its check's
                         for name in ("run_analyzer", "_generate_checked", "_start_analyzer"))  # answer, the run
        self.assertEqual(source.count("_tell_junban_list_changed()"), 2)
        window = MagicMock()
        window.winfo_exists.return_value = True
        self.app.junban_window = window
        self.MasterDashboardApp._tell_junban_list_changed(self.app)
        window.on_list_updated.assert_called_once_with()
        window.reset_mock()
        window.winfo_exists.return_value = False       # closed: nothing to tell
        self.MasterDashboardApp._tell_junban_list_changed(self.app)
        window.on_list_updated.assert_not_called()
        self.app.junban_window = None
        self.MasterDashboardApp._tell_junban_list_changed(self.app)   # never opened: no error

    def test_a_generate_triggers_it_whether_or_not_the_analysis_ran(self):
        """The analyzer's own completion AND the fast path that only reopens the report."""
        source = "".join(inspect.getsource(getattr(self.MasterDashboardApp, name))   # the press, its check's
                         for name in ("run_analyzer", "_generate_checked", "_start_analyzer"))  # answer, the run
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
        source = inspect.getsource(analyzer.run_signature_parts)     # what compute_run_signature hashes
        for key in ("anki_connect_url", "anki_sync_auto", "anki_sync_decks", "anki_sync_fields",
                    "anki_sync_include_suspended"):
            self.assertIn(f'"{key}"', source, f"{key} must be excluded from the run signature")


if __name__ == '__main__':
    unittest.main()
