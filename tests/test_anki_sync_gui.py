"""The Anki Known Words window (Anki_Known_Sync_Spec.md §5.6, §5.9, §7.6).

One real Tk root for the whole file (testing.md §5.4), withdrawn; windows are built on it and torn
down per test. Workers are never started here — results are fed straight through the window's own
queue (`_drain_once`), exactly as a worker would deliver them, so nothing reaches a live Anki. The
autouse `SURASURA_NO_UI_TIMERS` keeps the opening probe and the pump from being scheduled at all.

Deck names and note types below are the real ones from the collection this was built against
(TheBank / The Accelerator / Migaku Reference; Lapis / Migaku Japanese).
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    from tkinter import ttk
    _ROOT = tk.Tk()
    _ROOT.withdraw()
except Exception:   # no display
    _ROOT = None

from app import settings_manager


def _result(**kw):
    base = dict(added=0, scanned=0, mode="delta", skipped_by_model={}, fields_by_model={},
                total_known=0, backup=None, error=None)
    base.update(kw)
    return SimpleNamespace(**base)


CONNECTED = {"ok": True, "version": 6, "missing": [], "error": None}
MODELS = {"Lapis": ["Expression", "ExpressionFurigana", "Sentence", "MainDefinition"],
          "Migaku Japanese": ["Sentence", "Target Word", "Translation"]}


@unittest.skipIf(_ROOT is None, "no display")
class TestAnkiSyncWindow(unittest.TestCase):
    def setUp(self):
        from app import anki_sync_gui
        self.gui = anki_sync_gui
        self.host = MagicMock()
        self.host.var_anki_sync_auto = tk.BooleanVar(master=_ROOT, value=False)
        self.win = anki_sync_gui.AnkiSyncGui(_ROOT, app=self.host, language="ja")
        self.win.withdraw()

    def tearDown(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    def _connect(self, decks=("TheBank", "The Accelerator", "Migaku Reference"),
                 preselected=None, counts=None, models=None):
        self.win.q.put(("__CONN__", dict(CONNECTED), list(decks), preselected,
                        counts or {}, models if models is not None else MODELS))
        self.win._drain_once()

    # ------------------------------------------------------------ guidelines
    def test_escape_closes_the_window(self):
        # A key event only reaches a window that is mapped and focused.
        self.win.deiconify()
        self.win.focus_force()
        self.win.update()
        self.win.event_generate("<Escape>", when="now")
        self.win.update()
        self.assertFalse(self.win.winfo_exists())

    def test_every_button_toggle_and_picker_has_a_tooltip(self):
        """GUI guidelines §6: tooltips on every button and toggle."""
        missing = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, (ttk.Button, ttk.Checkbutton, ttk.Combobox)):
                    if not child.bind("<Enter>"):
                        missing.append(child)
                walk(child)
        walk(self.win)
        self.assertEqual(missing, [])

    def test_the_window_never_switches_the_hosts_theme(self):
        """ttk styles are process-global; the dashboard owns the base theme (guidelines §2.1)."""
        style = ttk.Style(_ROOT)
        style.theme_use("clam")
        win = self.gui.AnkiSyncGui(_ROOT, app=self.host, language="ja")
        try:
            self.assertEqual(style.theme_use(), "clam")
        finally:
            win.destroy()

    # ------------------------------------------------------------ connection
    def test_not_connected_disables_everything_but_the_apkg_path(self):
        """Anki being closed is a state: the window says so and the offline import still works."""
        self.win.q.put(("__CONN__", {"ok": False, "error": "Anki isn't reachable."}, [], None, {}, {}))
        self.win._drain_once()
        self.assertEqual(str(self.win.btn_sync.cget("state")), "disabled")
        self.assertEqual(str(self.win.btn_replace.cget("state")), "disabled")
        self.assertEqual(str(self.win.add_box.cget("state")), "disabled")
        self.assertIn("not connected", self.win.conn_var.get())
        self.assertTrue(self.win.lnk_apkg.winfo_exists())

    def test_connected_is_short_and_the_version_is_in_the_tooltip(self):
        """The title row is narrow; a clipped status line reads as broken."""
        self._connect()
        self.assertEqual(self.win.conn_var.get(), "● connected")
        self.assertIn("AnkiConnect 6", self.win.conn_tip.text)

    def test_a_refused_connection_is_explained_in_plain_words(self):
        """Anki being closed is the common case; the socket error means nothing to a learner."""
        error = "Could not reach Anki (<urlopen error [WinError 10061] No connection could be made>)"
        self.win.q.put(("__CONN__", {"ok": False, "error": error}, [], None, {}, {}))
        self.win._drain_once()
        self.assertEqual(self.win.result_var.get(),
                         "Anki isn't running. Start it with your profile open, then press ⟳.")
        self.assertEqual(self.win.conn_tip.text, error)

    def test_an_actionable_error_is_shown_as_written(self):
        error = "Anki did not grant access (it may be showing a permission prompt — accept it and try again)."
        self.win.q.put(("__CONN__", {"ok": False, "error": error}, [], None, {}, {}))
        self.win._drain_once()
        self.assertEqual(self.win.result_var.get(), error)

    def test_first_open_preselects_the_studied_decks_and_saves_them(self):
        """D11: pick every deck with studied cards; the user removes what isn't vocabulary."""
        self._connect(preselected=["TheBank", "The Accelerator"], counts={"TheBank": 812, "The Accelerator": 240})
        self.assertEqual(self.win.decks, ["TheBank", "The Accelerator"])
        saved = settings_manager.load_settings()
        self.assertEqual(saved["anki_sync_decks"].get("ja"), ["TheBank", "The Accelerator"])
        rows = [self.win.tree.item(i, "values") for i in self.win.tree.get_children()]
        self.assertEqual(rows[0][1], "812 studied")

    def test_sync_is_enabled_only_with_a_connection_and_a_deck(self):
        self._connect(preselected=[])
        self.assertEqual(str(self.win.btn_sync.cget("state")), "disabled")
        self.win.decks = ["TheBank"]
        self.win._sync_controls()
        self.assertEqual(str(self.win.btn_sync.cget("state")), "normal")

    # ------------------------------------------------------------ decks
    def test_adding_a_deck_offers_only_decks_not_already_chosen(self):
        self._connect(preselected=["TheBank"])
        offered = list(self.win.add_box.cget("values"))
        self.assertNotIn("TheBank", offered)
        self.assertIn("Migaku Reference", offered)

    def test_add_and_remove_update_the_saved_decks_per_language(self):
        self._connect(preselected=["TheBank"])
        self.win.var_add.set("The Accelerator")
        with patch.object(self.win, "_start"):          # no scope worker; only the list is tested
            self.win._add_deck()
            self.assertEqual(self.win.decks, ["TheBank", "The Accelerator"])
            self.win._remove_deck("TheBank")
        self.assertEqual(self.win.decks, ["The Accelerator"])
        saved = settings_manager.load_settings()
        self.assertEqual(saved["anki_sync_decks"]["ja"], ["The Accelerator"])

    def test_the_delete_key_removes_the_selected_deck(self):
        self._connect(preselected=["TheBank", "The Accelerator"])
        self.win.tree.selection_set("deck::TheBank")
        with patch.object(self.win, "_start"):
            self.win._remove_selected()
        self.assertEqual(self.win.decks, ["The Accelerator"])

    def test_saving_never_mutates_the_default_settings_dict(self):
        """settings_manager merges defaults shallowly, so the loaded dict can BE the default."""
        self._connect(preselected=["TheBank"])
        self.assertEqual(settings_manager.DEFAULT_SETTINGS.get("anki_sync_decks"), {})

    # ------------------------------------------------------------ fields
    def test_auto_resolves_each_note_type_to_its_first_field(self):
        self._connect(preselected=["TheBank"])
        self.assertIn("Lapis → Expression", self.win.resolved_var.get())
        self.assertIn("Migaku Japanese → Sentence", self.win.resolved_var.get())

    def test_a_note_type_without_the_chosen_field_is_shown_as_skipped(self):
        """A wrong field choice must be visible, never silent."""
        self._connect(preselected=["TheBank"])
        self.win.var_field1.set("Expression")
        self.win._on_fields_changed()
        self.assertIn("Lapis → Expression", self.win.resolved_var.get())
        self.assertIn("Migaku Japanese", self.win.unresolved_var.get())

    def test_the_second_field_waits_for_a_named_first_one(self):
        """Auto is per note type, so 'Auto + one more' has no single meaning."""
        self._connect(preselected=["TheBank"])
        self.assertEqual(str(self.win.box_field2.cget("state")), "disabled")
        self.win.var_field1.set("Expression")
        self.win._on_fields_changed()
        self.assertEqual(str(self.win.box_field2.cget("state")), "readonly")
        self.win.var_field2.set("Sentence")
        self.assertEqual(self.win._fields(), ["Expression", "Sentence"])

    # ------------------------------------------------------------ results
    def test_the_known_total_is_shown_with_thousands_separators(self):
        self.win.q.put(("__KNOWN__", 4318, {}))
        self.win._drain_once()
        self.assertEqual(self.win.known_var.get(), "4,318")

    def test_a_sync_result_updates_the_total_and_tells_the_dashboard(self):
        result = _result(added=12, scanned=812, total_known=4330)
        self.win.q.put(("__RESULT__", result, {}))
        self.win._drain_once()
        self.assertEqual(self.win.known_var.get(), "4,330")
        self.assertIn("+12 words", self.win.result_var.get())
        self.assertEqual(self.win.delta_var.get(), "+12")
        self.host._on_anki_sync_result.assert_called_once_with(result, auto=False)

    def test_an_error_result_is_shown_verbatim(self):
        self.win.q.put(("__RESULT__", _result(error="KnownWord.json を読み込めません"), {}))
        self.win._drain_once()
        self.assertEqual(self.win.result_var.get(), "KnownWord.json を読み込めません")

    def test_restore_appears_only_when_there_is_a_backup(self):
        self.win.deiconify()
        self.win.update()
        self.win.q.put(("__KNOWN__", 812, {"last_backup": "KnownWord.20260918-150000.json"}))
        self.win._drain_once()
        self.win.update()
        self.assertTrue(self.win.lnk_restore.winfo_ismapped())
        self.win.q.put(("__KNOWN__", 812, {}))
        self.win._drain_once()
        self.win.update()
        self.assertFalse(self.win.lnk_restore.winfo_ismapped())

    # ------------------------------------------------------------ replace
    def test_replace_asks_with_the_real_numbers_and_does_nothing_on_cancel(self):
        dry = _result(mode="dry-run", added=812, total_known=4318)
        with patch.object(self.gui, "ask", return_value=False) as ask, \
             patch.object(self.win, "_start") as start:
            self.win._confirm_replace(dry)
        message = ask.call_args.args[1]
        self.assertIn("4,318", message)
        self.assertIn("812", message)
        start.assert_not_called()

    def test_replace_runs_only_after_a_yes(self):
        dry = _result(mode="dry-run", added=812, total_known=4318)
        self.win.decks = ["TheBank"]
        with patch.object(self.gui, "ask", return_value=True), \
             patch.object(self.win, "_start") as start, \
             patch.object(self.win, "_replace_worker") as worker:
            self.win._confirm_replace(dry)
            start.assert_called_once()
            start.call_args.args[0]()          # the job it queued is the replace, with a snapshot
        self.assertEqual(worker.call_args.args[0]["decks"], ["TheBank"])

    def test_the_window_stays_busy_for_the_whole_replace(self):
        """The dry run queues its result and then its own __DONE__. The confirm dialog opened while
        that __DONE__ was still queued; after "Replace" it arrived and marked the window idle
        mid-replace. A second Replace then backed up the already-replaced list, and "Restore
        previous" pointed at that copy instead of the user's original."""
        dry = _result(mode="dry-run", added=812, total_known=4318)
        self.win.decks = ["TheBank"]
        with patch.object(self.gui, "ask", return_value=True), \
             patch.object(self.gui.threading, "Thread"):          # the jobs never actually run
            self.win._start(lambda: None)                         # the dry run is job 1
            dry_run_job = self.win._job
            self.win.q.put(("__DRYRUN__", dry))
            self.win.q.put(("__DONE__", dry_run_job))             # its DONE, still queued
            self.win._drain_once()                                # confirm -> Replace starts
        self.assertGreater(self.win._job, dry_run_job, "the replace is a new job")
        self.assertTrue(self.win.busy, "a stale __DONE__ must not free the window mid-replace")

        self.win.q.put(("__DONE__", self.win._job))                # the replace's own DONE
        self.win._drain_once()
        self.assertFalse(self.win.busy)

    def test_enter_and_escape_both_mean_no_in_the_confirmation(self):
        """Replace removes entries; a stray keypress must never confirm it."""
        import inspect
        source = inspect.getsource(self.gui.ConfirmDialog.__init__)
        self.assertIn('self.bind("<Return>", lambda _e: self._done(False))', source)
        self.assertIn('self.bind("<Escape>", lambda _e: self._done(False))', source)
        self.assertIn("decline.focus_set()", source)


if __name__ == "__main__":
    unittest.main()
