# SPDX-License-Identifier: GPL-3.0-or-later
"""順's row for the fast re-plan's preview (E1.1 04 §1; RUNBOOK E3.1.1): "Re-order Anki as I move content (preview)"
and its "Sync AnkiWeb" choice (04 §3, S4).

  - off by default; nothing saved until the user touches the row (a window that opens writes no default into
    settings.json), then both keys onto the file as it is (`save_keys`);
  - on, the window's own preview and run number spaced (`spaced.Job`, not automatic: the window keeps 2.5's
    snapshot) — and the switch is in the scope key, so a preview of the other numbering is no confirmation (I5);
  - greyed, the reason in its tooltip, where it can't run (All decks; Coverage; "Only i+1"); the sync choice only
    while it's on; the dashboard is told (it starts its own part: a Generate first when there is no plan);
  - Esc still closes, every control has a tooltip (the GUI guidelines).
"""
import unittest
from unittest import mock

from modules.junban import gui as junban_gui
from modules.junban import spaced
from modules.junban.tests.test_gui import JunbanGuiTestCase


class ReplanRowTests(JunbanGuiTestCase):

    def test_the_row_is_off_saves_nothing_until_touched_and_runs_2_5s_numbering(self):
        panel = self._panel()
        self.assertEqual(panel.replan_box.cget("text"), "Re-order Anki as I move content (preview)")
        self.assertFalse(panel._replan_value())
        self.assertEqual(panel._replan_values(), {})          # untouched, no deck yet: nothing written
        self.assertEqual(self._state(panel.sync_box), "disabled")
        # 2.x-dev keeps `panel._job(...)` None here (off: 2.5's run, request for request); 3.0 (Haya's G2b): the
        # window's own run numbers spaced whatever the box says — still not automatic (2.5's snapshot).
        job = panel._job(panel._settings())
        self.assertIsInstance(job, spaced.Job)
        self.assertFalse(job.automatic)
        for widget in (panel.replan_box, panel.sync_box):     # a tooltip on every control (GUI guidelines)
            self.assertTrue(widget.bind("<Enter>"))

    def test_switching_it_on_saves_both_keys_tells_the_dashboard_and_numbers_the_windows_runs_spaced(self):
        app = mock.MagicMock()
        app.var_language.get.return_value = "ja"
        panel = self._panel(app=app)
        panel.deck.set("TheBank")
        before = panel._scope_key()
        with mock.patch("app.settings_manager.save_keys") as save:
            panel.replan_on.set(True)
            panel._on_replan_changed()
        saved = save.call_args[0][0]
        self.assertIs(saved["junban_replan_preview"], True)
        self.assertEqual(saved["anki_sync_delay_min"], 1)     # the default: about a minute after
        app.replan_preview_changed.assert_called_once_with()
        self.assertNotEqual(panel._scope_key(), before)       # a preview of the other numbering is thrown away (I5)
        self.assertEqual(self._state(panel.sync_box), "readonly")
        settings = dict(panel._settings(), enable_junban=True)
        job = panel._job(settings)
        self.assertIsInstance(job, spaced.Job)
        self.assertFalse(job.automatic)                       # the window's own run: 2.5's snapshot, not the baseline

    def test_the_sync_choice_saves_its_value(self):
        panel = self._panel()
        panel.replan_on.set(True)
        for label, value in junban_gui.JunbanGui.SYNC_CHOICES:
            with mock.patch("app.settings_manager.save_keys") as save:
                panel.sync_choice.set(label)
                panel._on_replan_changed()
            self.assertEqual(save.call_args[0][0]["anki_sync_delay_min"], value, label)

    def test_greyed_with_the_reason_where_it_cant_run(self):
        panel = self._panel()
        panel.scope.set("all")
        panel._sync_replan_row()
        self.assertIn("disabled", str(panel.replan_box.state()))
        self.assertIn("one deck", panel._replan_tip())
        panel.scope.set("deck")
        panel.deck.set("TheBank")
        panel._sync_replan_row()
        self.assertNotIn("disabled", str(panel.replan_box.state()))
        self.assertNotIn("one deck", panel._replan_tip())

    def test_a_language_switched_on_the_dashboard_since_this_window_opened_records_nothing(self):
        # Review 3 R3: 順 opened in ja with the preview on for TheBank; the dashboard switches to zh; any click in this
        # window must not record zh with this window's deck (zh's list would be written onto TheBank).
        app = mock.MagicMock()
        app.var_language.get.return_value = "ja"
        saved = {"junban_replan_preview": True, "junban_replan_language": "ja", "junban_replan_deck": "TheBank",
                 "junban_deck": "TheBank", "junban_scope": "deck"}
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings", lambda self: dict(saved)):
            panel = self._panel(app=app)
            panel.deck.set("TheBank")
            self.assertTrue(panel._replan_value())
            panel._replan_touched = True
            # 2.x-dev records the pair from the box ticked here; 3.0: only the user's deck pick records it.
            with mock.patch("app.settings_manager.save_keys") as save:
                panel._on_deck_picked()
            self.assertEqual(save.call_args[0][0]["junban_replan_language"], "ja")
            app.var_language.get.return_value = "zh"            # the dashboard's language, switched
            self.assertEqual(panel._replan_values(), {})
            with mock.patch("app.settings_manager.save_keys") as save:
                panel._on_deck_picked()                         # even the user's pick: this window is ja's
            self.assertNotIn("junban_replan_language", save.call_args[0][0])
            panel._replan_touched = False                       # untouched: the deck never follows either
            panel.deck.set("中文")
            self.assertEqual(panel._replan_values(), {})
            app.var_language.get.return_value = "ja"            # back in its own language
            # 2.x-dev keeps {"junban_replan_deck": "中文"} here; 3.0: a deck the user didn't pick records nothing
            # — the user's pick records the pair (Haya's G3).
            self.assertEqual(panel._replan_values(), {})
            with mock.patch("app.settings_manager.save_keys") as save:
                panel._on_deck_picked()
            self.assertEqual(save.call_args[0][0]["junban_replan_language"], "ja")
            self.assertEqual(save.call_args[0][0]["junban_replan_deck"], "中文")

    def test_the_deck_changed_reason_names_both_decks_and_leaves_the_box_to_tick(self):
        # Review 3 R4: in the other language's window, the preview stands aside for "the deck changed" — the box stays
        # enabled (ticking it records this deck), and the reason names both decks.
        app = mock.MagicMock()
        app.var_language.get.return_value = "zh"
        saved = {"junban_replan_preview": True, "junban_replan_language": "ja", "junban_replan_deck": "TheBank",
                 "junban_deck": "中文", "junban_scope": "deck", "enable_junban": True}
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings", lambda self: dict(saved)):
            panel = self._panel(app=app)
            panel.scope.set("deck")
            panel.deck.set("中文")
            settings = dict(panel._settings(), junban_replan_deck="TheBank")
            with mock.patch.object(panel, "_settings", lambda: settings):
                panel._sync_replan_row()
                self.assertFalse(panel._replan_value())          # zh's window: the ja preview isn't on here
                self.assertNotIn("disabled", str(panel.replan_box.state()))
                tip = panel._replan_tip()
                self.assertIn("TheBank", tip)
                self.assertIn("中文", tip)
                panel.scope.set("all")                           # a reason of its own still greys it
                all_decks = dict(settings, junban_scope="all")
                with mock.patch.object(panel, "_settings", lambda: all_decks):
                    panel._sync_replan_row()
                    self.assertIn("disabled", str(panel.replan_box.state()))


    def test_on_3_0_saving_the_deck_records_the_pair_in_the_windows_language_box_untouched(self):
        # Haya's G3: the 3.0 host stands aside unless (junban_replan_language, junban_replan_deck) holds; a user who
        # never ticked 2.x's box must not be stuck — picking the deck in 順 records the pair, in this window's language
        # (only the user's pick).
        for language, deck in (("ja", "TheBank"), ("zh", "中文")):
            app = mock.MagicMock()
            app.var_language.get.return_value = language
            panel = self._panel(app=app)
            self.assertFalse(panel._replan_value())
            panel.scope.set("deck")
            panel.deck.set(deck)
            with mock.patch("app.settings_manager.save_keys") as save:
                panel.deck_box.event_generate("<<ComboboxSelected>>")      # the user picks it in the list
            saved = save.call_args[0][0]
            self.assertEqual(saved["junban_deck"], deck)
            self.assertEqual(saved["junban_replan_language"], language)
            self.assertEqual(saved["junban_replan_deck"], deck)
            self.assertNotIn("junban_replan_preview", saved)    # the box untouched: its key never written

    def test_on_3_0_only_the_users_own_deck_pick_records_the_pair_never_a_tweak_or_the_automatic_pick(self):
        # A Chinese 順 window still showing the Japanese deck (`junban_deck` is one key for both) must never
        # record that deck for Chinese because of an unrelated tweak — a checkbox, a FocusOut save — or 順's own
        # first-deck pick; that would undo the deck guard (Haya's G3) and re-order a Japanese deck by the Chinese list.
        # Only the user's pick in the deck list records the pair.
        app = mock.MagicMock()
        app.var_language.get.return_value = "zh"
        saved = {"junban_deck": "TheBank", "junban_scope": "deck", "junban_replan_language": "ja",
                 "junban_replan_deck": "TheBank"}
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings", lambda self: dict(saved)):
            panel = self._panel(app=app)
            self.assertEqual(panel.deck.get(), "TheBank")
            with mock.patch("app.settings_manager.save_keys") as save:
                panel.list_first.set(not panel.list_first.get())
                panel._on_scope_changed()                      # "List first" (and every scope checkbox) saves so
                panel._on_touchup_changed()                    # a touch-up's checkbox
                panel.freq_box.event_generate("<FocusOut>")    # a FocusOut save
                panel.replan_on.set(False)
                panel._on_replan_changed()                     # 2.x's preview box itself
            self.assertTrue(save.call_args_list)
            for call in save.call_args_list:
                self.assertNotIn("junban_replan_language", call[0][0])
                self.assertNotIn("junban_replan_deck", call[0][0])
            with mock.patch("app.settings_manager.save_keys") as save:
                panel.deck_box.event_generate("<<ComboboxSelected>>")      # the user picks the deck
            self.assertEqual(save.call_args[0][0]["junban_replan_language"], "zh")
            self.assertEqual(save.call_args[0][0]["junban_replan_deck"], "TheBank")

    def test_on_3_0_juns_own_first_deck_pick_records_nothing(self):
        # No deck chosen yet; 順 offers the first deck that has new cards (`_set_connection`) and saves it —
        # its pick, not the user's: no pair recorded (the host stands aside and the bar says to pick it).
        app = mock.MagicMock()
        app.var_language.get.return_value = "zh"
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings", lambda self: {"junban_scope": "deck"}):
            panel = self._panel(app=app)
            self.assertEqual(panel.deck.get(), "")
            with mock.patch("app.settings_manager.save_keys") as save:
                panel._set_connection({"ok": True, "version": 6}, decks=["TheBank", "中文"])
            self.assertEqual(panel.deck.get(), "TheBank")
            self.assertEqual(save.call_args[0][0]["junban_deck"], "TheBank")
            self.assertNotIn("junban_replan_language", save.call_args[0][0])
            self.assertNotIn("junban_replan_deck", save.call_args[0][0])

    def test_on_3_0_the_windows_own_run_numbers_spaced_whatever_the_switches(self):
        # 2.x-dev: `window_job` is a Job only while the preview is on for this language; 3.0 (Haya's G2b): always,
        # and never automatic (the window keeps 2.5's snapshot).
        for settings in ({"target_language": "ja"},
                         {"target_language": "ja", "junban_replan_preview": False, "logic": {"automation": False}},
                         {"target_language": "zh", "junban_replan_preview": True, "junban_replan_language": "ja"},
                         {"target_language": "ja", "enable_junban": False}):
            job = junban_gui.window_job(settings)
            self.assertIsInstance(job, spaced.Job, settings)
            self.assertFalse(job.automatic, settings)


if __name__ == "__main__":
    unittest.main()
