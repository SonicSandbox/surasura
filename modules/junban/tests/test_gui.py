# SPDX-License-Identifier: GPL-3.0-or-later
"""The Junban panel: the guidelines it must satisfy, and the promises it makes before a write.

Three things this file exists to hold still, in order of how much damage their absence does:

1. **Reorder cannot be pressed without a preview of the scope on screen** (invariant I5).
   AnkiConnect's `setSpecificValueOfCard` writes no Anki undo entry and the change syncs to
   AnkiWeb and mobile, so the preview is the only confirmation there is — and a preview of a
   *different* deck is not one, which is why changing the scope throws it away.
2. **The panel never mutates the settings dict it was handed.** `junban_word_fields` in loaded
   settings IS the dict inside `SETTINGS_DEFAULTS` (spec §13 #12); editing it in place poisons the
   default for the whole process and leaks between tests.
3. **`ttk` styles are process-global**, so a window opened in-process by a host on another base
   theme must not switch it — the mandatory test named by the module SOP.

Nothing here reaches Anki. Every engine call is patched, the conftest's `SURASURA_NO_UI_TIMERS`
keeps the opening connection probe from ever being armed, and its `_no_real_modals` neuters the
confirmation — a modal with no one to click it hangs the suite rather than failing it, and a hang
names no test. One Tk root per FILE (`testing.md` §5.4); words and ranks come from a real Surasura
export rather than ASCII placeholders (§1).
"""
import csv
import os
import tkinter as tk
import unittest
from tkinter import ttk
from unittest import mock

import modules.junban as _junban
from modules.junban import gui as junban_gui
from modules.junban.plan import plan

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_RESOURCE_CSV = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")

# Real Japanese words a learner mines but that this export does not rank — the unmatched block.
_UNRANKED_WORDS = ["須藤", "鳥取", "美術館", "新幹線", "味噌汁"]


def _priority_rows():
    with open(_RESOURCE_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        return [((row.get("Word") or "").strip(), (row.get("Orth") or "").strip())
                for row in csv.DictReader(handle)]


def _rank_index():
    """`{word: rank}` the way WP-D builds it: Orth first, then Word, never overwriting a better rank."""
    index = {}
    for rank, (word, orth) in enumerate(_priority_rows()):
        for key in (orth, word):
            if key and key not in index:
                index[key] = rank
    return index


_RANK_OF = _rank_index()
_RANKED_WORDS = [word for word, _rank in sorted(_RANK_OF.items(), key=lambda pair: pair[1])][:6]


def _card(card_id, due, word, deck="TheBank"):
    # With a note id, as the engine's cards always have: without one, `replan` could drop it and no
    # test here would notice.
    return {"card_id": card_id, "due": due, "type": 0, "queue": 0, "word": word, "deck": deck,
            "note": card_id + 1000}


def _real_stats():
    """A genuine dry-run result: the planner's own output over real words, mined out of order.

    Built by calling `plan` rather than by hand, so the preview test exercises the same rows the
    writer would — a preview assembled independently is a second implementation of the ordering.
    """
    cards = [_card(1700 + i, 2830 + i, word)
             for i, word in enumerate(reversed(_RANKED_WORDS))]
    cards += [_card(1800 + i, 2840 + i, word, deck="The Accelerator")
              for i, word in enumerate(_UNRANKED_WORDS)]
    # A suspended card and a review card, so the scope line has something to report as untouched.
    cards.append({"card_id": 1901, "due": 2999, "type": 0, "queue": -1,
                  "word": _RANKED_WORDS[0], "deck": "TheBank"})
    cards.append({"card_id": 1902, "due": 40, "type": 2, "queue": 2,
                  "word": _RANKED_WORDS[1], "deck": "TheBank"})
    _writes, stats = plan(cards, _RANK_OF)
    stats["decks"] = ["TheBank"]
    stats["fields"] = {"Lapis": "Expression", "Migaku Japanese": "Target Word"}
    stats["ranked"] = len(_RANK_OF)
    return stats


# The shipped module defaults, so the panel tests assert against the SAME dict the contract
# test pins rather than a copy of it that could drift.
_DEFAULTS = dict(_junban.SETTINGS_DEFAULTS)

_OK_CHECKS = {"ok": True, "problems": [], "warnings": [], "decks": ["TheBank"], "probe": {"ok": True}}


class JunbanGuiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:                      # pragma: no cover - headless machine
            raise unittest.SkipTest(f"no display: {exc}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def _panel(self, **kwargs):
        panel = junban_gui.JunbanGui(self.root, **kwargs)
        self.addCleanup(self._destroy, panel)
        self.root.update_idletasks()
        return panel

    @staticmethod
    def _destroy(panel):
        """Closed as the user closes it (`_close`): it lets go of its `junban-window` lock, so the next window's lock
        thread takes it at once instead of waiting out its 2 s past the end of its test."""
        try:
            panel._close()
        except tk.TclError:
            pass

    @staticmethod
    def _state(widget):
        return str(widget.cget("state"))

    @staticmethod
    def _messages(panel):
        return panel.messages.get("1.0", "end")

    def _previewed(self, panel, stats=None, checks=None):
        """Put the panel in the state a successful preview leaves it in."""
        panel.q.put(("__PREVIEW__", stats if stats is not None else _real_stats(),
                     checks or _OK_CHECKS))
        panel._drain_once()
        return panel


class TestTheming(JunbanGuiTestCase):
    def test_the_embedded_window_inherits_the_host_theme_and_does_not_switch_it(self):
        """MANDATORY per the module SOP. The Content Manager runs `clam` and the dashboard runs
        `default`; a module calling `theme_use` unconditionally leaves whichever opened it
        unreadable — which is exactly how the Content Manager once went white."""
        ttk.Style(self.root).theme_use("clam")          # simulate a host
        panel = self._panel()
        self.root.update()
        self.assertEqual(ttk.Style(self.root).theme_use(), "clam",
                         "the module must inherit the host theme, not switch it")
        # Its own namespaced styles are registered regardless of the inherited theme.
        self.assertEqual(panel.tk.call("ttk::style", "lookup", "Jun.TButton", "-background"),
                         junban_gui.SURFACE)

    def test_it_paints_itself_under_the_dashboards_theme_too(self):
        ttk.Style(self.root).theme_use("default")
        panel = self._panel()
        self.root.update()
        self.assertEqual(ttk.Style(self.root).theme_use(), "default")
        self.assertEqual(panel.tk.call("ttk::style", "lookup", "Jun.Treeview", "-background"),
                         junban_gui.SURFACE)

    def test_the_palette_matches_the_guidelines(self):
        self.assertEqual(junban_gui.BG, "#1e1e1e")
        self.assertEqual(junban_gui.SURFACE, "#2d2d2d")
        self.assertEqual(junban_gui.TEXT, "#e0e0e0")
        self.assertEqual(junban_gui.ACCENT, "#bb86fc")
        self.assertEqual(junban_gui.SECONDARY, "#03dac6")
        self.assertEqual(junban_gui.ERROR, "#cf6679")


class TestWindowBehaviour(JunbanGuiTestCase):
    def test_escape_closes_the_window(self):
        """Required of every window in this app. The panel has to be mapped and focused first — a
        withdrawn Toplevel never receives the synthesised key event."""
        panel = self._panel()
        self.assertTrue(panel.bind("<Escape>"), "no Escape binding")
        panel.deiconify()
        panel.update()
        panel.focus_force()
        panel.event_generate("<Escape>", when="now")
        self.root.update()
        self.assertFalse(panel.winfo_exists())

    def test_the_close_button_is_handled(self):
        self.assertTrue(self._panel().protocol("WM_DELETE_WINDOW"))

    def test_no_timer_or_connection_probe_is_armed_under_the_test_flag(self):
        """Two reasons, and the second is the serious one: a pending `after` outliving the window
        fires into a dead interpreter for the rest of the session, and the opening probe would
        reach the developer's REAL collection (spec §18.0 rule 6)."""
        self.assertEqual(os.environ.get("SURASURA_NO_UI_TIMERS"), "1")
        panel = self._panel()
        self.assertFalse(panel.tk.call("after", "info"), "a timer was armed despite the flag")

    def test_every_button_and_toggle_has_a_tooltip(self):
        """Mandatory in the GUI guidelines: a control whose purpose is not obvious on hover is a
        control the user will not press — and here the wrong press writes to their collection."""
        panel = self._panel()
        controls = _widgets(panel, (ttk.Button, ttk.Checkbutton, ttk.Radiobutton, ttk.Combobox))
        self.assertTrue(controls, "expected some controls")
        missing = [str(c) for c in controls if not c.bind("<Enter>")]
        self.assertEqual(missing, [], f"controls with no tooltip: {missing}")

    def test_long_tooltips_wrap(self):
        """Over 50 characters the guidelines require wrapping, so a tooltip stays roughly square
        rather than becoming a line across the screen."""
        panel = self._panel()
        tip = junban_gui.ToolTip(ttk.Button(panel, text="x"), "あ" * 80)
        tip._show()
        self.assertGreater(tip.tip.winfo_children()[0].cget("wraplength"), 0)
        tip._hide()

    def test_short_tooltips_do_not_wrap(self):
        panel = self._panel()
        tip = junban_gui.ToolTip(ttk.Button(panel, text="x"), "Reorder")
        tip._show()
        self.assertEqual(tip.tip.winfo_children()[0].cget("wraplength"), 0)
        tip._hide()


def _widgets(parent, kinds):
    found = []
    for child in parent.winfo_children():
        if isinstance(child, kinds):
            found.append(child)
        found.extend(_widgets(child, kinds))
    return found


class TestDegradedWithoutAnki(JunbanGuiTestCase):
    def test_the_panel_opens_with_anki_closed(self):
        """Opening must not depend on a live collection: Anki being shut is the normal state of the
        machine when the user goes looking for this window."""
        panel = self._panel()
        self.assertTrue(panel.winfo_exists())
        self.assertFalse(panel._connected)
        self.assertEqual(self._state(panel.btn_preview), "normal")

    def test_a_failed_probe_explains_that_anki_must_be_running(self):
        """The connection row is a state, not an exception — the panel says what to do about it."""
        panel = self._panel()
        panel.q.put(("__CONN__", {"ok": False, "version": None, "missing": [],
                                  "error": "Could not reach Anki at http://127.0.0.1:8765."}, []))
        panel._drain_once()
        self.assertIn("not connected", panel.conn_var.get())
        self.assertEqual(str(panel.conn_lbl.cget("foreground")), junban_gui.ERROR)
        text = self._messages(panel)
        self.assertIn("Could not reach Anki", text)
        self.assertIn("Anki must be running", text)

    def test_preview_with_anki_closed_reports_it_instead_of_failing(self):
        """The button press must not raise: preflight's problem is the answer, shown in the panel."""
        problems = ["Could not reach Anki at http://127.0.0.1:8765. Is Anki running?"]
        checks = {"ok": False, "problems": problems, "warnings": [], "decks": [],
                  "probe": {"ok": False}}
        with mock.patch.object(junban_gui.reposition, "preflight", return_value=checks), \
             mock.patch.object(junban_gui.reposition, "dry_run") as dry:
            panel = self._panel()
            panel._preview_worker(panel._settings(), panel._scope_key())
            panel._drain_once()
        dry.assert_not_called()              # nothing is read from a collection that is not there
        self.assertIn("Is Anki running?", self._messages(panel))
        self.assertIsNone(panel._preview_scope)

    def test_a_successful_probe_offers_the_decks_that_have_new_cards(self):
        panel = self._panel()
        panel.q.put(("__CONN__", {"ok": True, "version": 6, "missing": [], "error": ""},
                     ["TheBank", "The Accelerator"]))
        panel._drain_once()
        self.assertIn("AnkiConnect 6", panel.conn_var.get())
        self.assertEqual(str(panel.conn_lbl.cget("foreground")), junban_gui.SECONDARY)
        self.assertIn("TheBank", panel.deck_box.cget("values"))


class TestPreviewIsTheConfirmation(JunbanGuiTestCase):
    def test_a_preview_in_one_language_confirms_no_run_in_the_other(self):
        """The run reads the list, the known words and the snapshot of whichever language the
        dashboard shows when Reorder is pressed. Switched after a Japanese preview, the press must
        write nothing (found by review, 2026-09-23)."""
        from types import SimpleNamespace
        language = tk.StringVar(master=self.root, value="ja")
        panel = self._panel(app=SimpleNamespace(var_language=language))
        self._previewed(panel)
        self.assertEqual(self._state(panel.btn_reorder), "normal")

        language.set("zh")
        with mock.patch("modules.junban.reposition.run") as run:
            panel.on_reorder()
        run.assert_not_called()
        panel._sync_buttons()
        self.assertEqual(self._state(panel.btn_reorder), "disabled")

    def test_reorder_is_disabled_until_a_preview_exists(self):
        panel = self._panel()
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self._previewed(panel)
        self.assertEqual(self._state(panel.btn_reorder), "normal")

    def test_changing_the_scope_throws_the_preview_away(self):
        """A preview of one deck is not a confirmation for another — the table and the button both
        have to go back to 'no answer yet'."""
        panel = self._panel()
        panel.scope.set("deck")
        panel.deck.set("TheBank")
        self._previewed(panel)
        self.assertEqual(self._state(panel.btn_reorder), "normal")

        panel.deck.set("The Accelerator")
        panel._on_scope_changed()
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertIsNone(panel._preview_scope)
        self.assertFalse(panel.tree.get_children(), "the old deck's order is still on screen")

    def test_pressing_reorder_without_a_preview_writes_nothing(self):
        """Belt and braces for the disabled button: a keyboard or a stale callback must not get in."""
        with mock.patch.object(junban_gui.reposition, "run") as run:
            panel = self._panel()
            panel.on_reorder()
        run.assert_not_called()

    def test_a_preview_reads_anki_but_writes_nothing(self):
        with mock.patch.object(junban_gui.reposition, "preflight", return_value=_OK_CHECKS), \
             mock.patch.object(junban_gui.reposition, "dry_run",
                               return_value=([], _real_stats())) as dry, \
             mock.patch.object(junban_gui.reposition, "run") as run:
            panel = self._panel()
            with mock.patch.object(panel, "_context_counts", return_value={}):   # its two searches are Anki's
                panel._preview_worker(panel._settings(), panel._scope_key())
            panel._drain_once()
        dry.assert_called_once()
        run.assert_not_called()
        self.assertEqual(panel._preview_scope, panel._scope_key())

    def test_a_preview_that_lands_after_a_change_does_not_unlock_reorder(self):
        """The deck, order and touch-up controls stay live while a preview runs. A result arriving
        after the user ticked "overwrite FreqSort" describes the OLD settings; it used to be stamped
        with the new ones, unlocking Reorder — and a FreqSort overwrite — nobody previewed."""
        with mock.patch.object(junban_gui.reposition, "preflight", return_value=_OK_CHECKS), \
             mock.patch.object(junban_gui.reposition, "dry_run", return_value=([], _real_stats())):
            panel = self._panel()
            settings, requested = panel._settings(), panel._scope_key()    # Preview pressed
            panel.freqsort_on.set(not panel.freqsort_on.get())             # changed while it runs
            with mock.patch.object(panel, "_context_counts", return_value={}):   # its two searches are Anki's
                panel._preview_worker(settings, requested)
            panel._drain_once()
        self.assertEqual(panel._preview_scope, requested)
        self.assertNotEqual(panel._preview_scope, panel._scope_key())
        self.assertEqual(self._state(panel.btn_reorder), "disabled")

    def test_preflight_problems_block_the_run_and_are_shown(self):
        """A deck that inserts new cards randomly ignores positions — the whole run would be a
        silent, syncing no-op, so it is refused and said out loud."""
        problem = ("'TheBank' inserts new cards in RANDOM order, so Anki ignores card positions "
                   "and reordering it would do nothing.")
        checks = {"ok": False, "problems": [problem], "warnings": [], "decks": ["TheBank"],
                  "probe": {"ok": True}}
        with mock.patch.object(junban_gui.reposition, "preflight", return_value=checks), \
             mock.patch.object(junban_gui.reposition, "dry_run") as dry:
            panel = self._panel()
            panel._preview_worker(panel._settings(), panel._scope_key())
            panel._drain_once()
        dry.assert_not_called()
        self.assertIn("RANDOM order", self._messages(panel))
        self.assertEqual(self._state(panel.btn_reorder), "disabled")

    def test_warnings_are_shown_but_do_not_block(self):
        """A stale priority list makes the result worse, not impossible — spec §15 #5 says warn."""
        checks = dict(_OK_CHECKS, warnings=["Your library has changed since the last analysis."])
        panel = self._panel()
        self._previewed(panel, checks=checks)
        self.assertIn("library has changed", self._messages(panel))
        self.assertEqual(self._state(panel.btn_reorder), "normal")

    def test_a_finished_run_requires_a_fresh_preview(self):
        """The collection has moved on, so the table on screen is last minute's answer."""
        panel = self._panel()
        self._previewed(panel)
        panel.q.put(("__REPORT__", {"ok": True, "message": "Reordered 5 cards.", "problems": [],
                                    "warnings": [], "written": [1, 2, 3, 4, 5], "failures": []}))
        panel._drain_once()
        self.assertIn("Reordered 5 cards.", self._messages(panel))
        self.assertIsNone(panel._preview_scope)
        self.assertEqual(self._state(panel.btn_reorder), "disabled")


class TestPreviewTable(JunbanGuiTestCase):
    def test_the_table_lists_the_order_with_the_unmatched_greyed_below(self):
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)

        rows = [panel.tree.item(item) for item in panel.tree.get_children()]
        self.assertEqual(len(rows), len(stats["order"]))
        # Matched first, in rank order, then the unmatched block — greyed, and with no rank to show.
        ranks = [row["values"][4] for row in rows]      # #, new pos, word, marks, rank, deck
        matched = [r for r in ranks if r != "—"]
        self.assertEqual(matched, sorted(matched), "matched cards must be in rank order")
        self.assertEqual(ranks[len(matched):], ["—"] * stats["unmatched"])
        for row in rows[len(matched):]:
            self.assertIn("unmatched", row["tags"])
        # The words are the real ones, not a placeholder or an id.
        self.assertIn(_RANKED_WORDS[0], [row["values"][2] for row in rows])

    def test_a_word_the_list_cut_off_is_shown_placed_and_named_library(self):
        """Junban_Backlog_Spec §11.1: a library card is placed, so it is NOT greyed like the
        unmatched block; its rank column says where the place came from, and the match line counts
        it apart from the list's matches."""
        top = _RANKED_WORDS[0]
        cards = [_card(1, 2802, top) | {"sort": (1, -50, -5, 0, _RANK_OF[top])},
                 _card(2, 2801, "引きずる") | {"tier": "library", "sort": (1, -30, -1, 1, 0)},
                 _card(3, 2800, "須藤")]
        _writes, stats = plan(cards, _RANK_OF)
        stats.update({"decks": ["TheBank"], "fields": {}})
        panel = self._previewed(self._panel(), stats)

        rows = {panel.tree.item(item)["values"][2]: panel.tree.item(item)
                for item in panel.tree.get_children()}
        self.assertEqual(rows["引きずる"]["values"][4], "library")
        self.assertNotIn("unmatched", rows["引きずる"]["tags"])
        self.assertIn("unmatched", rows["須藤"]["tags"])
        self.assertIn("1 more from your library", panel.match_var.get())

    def test_the_rest_are_counted_by_tier_and_known_words_and_missing_episodes_are_named(self):
        """§5.4 / §5.5 in the panel: what the sentences said about the cards the library could not
        place, the known words with the hint the count is for, and the source the library lacks."""
        cards = [_card(1, 2802, "冒険") | {"tier": "i+1", "sort": (9000,), "why": "i+1"},
                 _card(2, 2801, "眼鏡") | {"tier": "multi", "sort": (2, 4000), "why": "2 unknown"},
                 _card(3, 2800, "終わり") | {"tier": "known", "sort": (), "why": "known"}]
        _writes, stats = plan(cards, _RANK_OF)
        stats.update({"decks": ["TheBank"], "fields": {},
                      "banner": [{"source": "[SubsPlease] Tetsunabe no Jan! - 04 (1080p)", "cards": 22}]})
        panel = self._previewed(self._panel(), stats)

        messages = self._messages(panel)
        self.assertIn("Then, by their own sentence: 1 i+1 · 1 with more new words.", messages)
        self.assertIn("1 card is a word you already know — they go last.", messages)
        self.assertIn("22 cards come from [SubsPlease] Tetsunabe no Jan! - 04 (1080p), which isn't in "
                      "your library.", messages)
        whys = [panel.tree.item(item)["values"][4] for item in panel.tree.get_children()]
        self.assertEqual(whys, ["i+1", "2 unknown", "known"])
        self.assertNotIn("unmatched", messages, "no unmatched card, so no sentence about them")

    def test_a_library_map_without_the_journey_says_to_generate_once(self):
        stats = _real_stats()
        stats.update({"library_missing": True, "unlisted": "journey"})
        panel = self._previewed(self._panel(), stats)

        self.assertIn("press Generate in Surasura once", self._messages(panel))
        self.assertIn("where your journey meets them", self._messages(panel))

    def test_list_first_counts_the_phrases_with_the_list_and_says_why_they_would_wait(self):
        """With "List first" the phrases met as often as the list's words are counted beside the
        list's matches, each row says why, and a missing library map says what it costs — the phrases
        wait until the next Generate — rather than the journey's message, about another placement."""
        top = _RANKED_WORDS[0]
        cards = [_card(1, 2802, top) | {"sort": (1, -50, -5, 0, _RANK_OF[top])},
                 _card(2, 2801, "恩を売る") | {"tier": "phrase", "sort": (1, -20, -2, 1, 0),
                                              "why": "phrase · 2× · Honzuki no Gekokujou - 21"},
                 _card(3, 2800, "須藤") | {"tier": "multi", "sort": (1, 9000), "why": "1 unknown"}]
        _writes, stats = plan(cards, _RANK_OF)
        stats.update({"decks": ["TheBank"], "fields": {}, "unlisted": "list_first"})
        panel = self._previewed(self._panel(), stats)

        self.assertIn("1 frequent phrase with them", panel.match_var.get())
        whys = [panel.tree.item(item)["values"][4] for item in panel.tree.get_children()]
        self.assertEqual(whys, ["list #1", "phrase · 2× · Honzuki no Gekokujou - 21", "1 unknown"])
        # Clicked off, the phrase leaves the count with it: the line re-plans with the table (WP-O).
        panel._toggle_row(panel.tree.get_children()[1])
        self.assertNotIn("phrase", panel.match_var.get())

        stats["library_missing"] = True
        panel = self._previewed(self._panel(), stats)
        self.assertIn("Phrases wait with the rarer cards for now", self._messages(panel))
        self.assertNotIn("where your journey meets them", self._messages(panel))

    def test_the_counts_are_stated_plainly(self):
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        counts = panel.counts_var.get()
        self.assertIn(f"{stats['considered']} new card", counts)
        self.assertIn(f"{stats['matched']} of {stats['considered']} new cards matched",
                      panel.match_var.get())
        self.assertIn(f"move {stats['to_write']} of", self._messages(panel))

    def test_untouched_cards_are_counted_rather_than_assumed_to_be_zero(self):
        """The planner's `skipped_review` is 0 here and always will be: the search is `is:new`, so
        review cards never reach it to be skipped. Printing that as "0 review cards (untouched)" to
        someone whose deck holds 17 reads as "it cannot see them" — the opposite of the reassurance
        the line exists to give. The panel counts them separately and only says what it counted."""
        panel = self._panel()
        stats = dict(_real_stats())
        stats.update({"context_review": 17, "context_suspended": 3})
        self._previewed(panel, stats)
        counts = panel.counts_var.get()
        self.assertIn("17 in review or learning (untouched)", counts)
        self.assertIn("3 suspended (untouched)", counts)

    def test_a_count_that_could_not_be_read_is_omitted_not_guessed(self):
        """`_context_counts` is best-effort — if the extra searches fail, the clause disappears
        rather than claiming a confident zero."""
        panel = self._panel()
        self._previewed(panel, _real_stats())          # no context_* keys at all
        counts = panel.counts_var.get()
        self.assertIn("new card", counts)
        self.assertNotIn("review", counts)
        self.assertNotIn("suspended", counts)

    def test_the_resolved_word_field_is_shown_per_note_type(self):
        """Field 0 is an anki_miner invariant, not an Anki one: Migaku puts `Sentence` there. A
        wrong guess has to be visible BEFORE the write, or the feature just looks broken."""
        panel = self._panel()
        self._previewed(panel)
        self.assertIn('Lapis → "Expression"', panel.fields_var.get())
        self.assertIn('Migaku Japanese → "Target Word"', panel.fields_var.get())

    def test_an_empty_scope_says_so_rather_than_showing_an_empty_table(self):
        """Empty state: a deck with nothing new in it. 'Nothing to do' must be readable as such."""
        _writes, stats = plan([], _RANK_OF)
        stats.update({"decks": ["Default"], "fields": {}, "ranked": len(_RANK_OF)})
        panel = self._panel()
        self._previewed(panel, stats)
        self.assertFalse(panel.tree.get_children())
        self.assertIn("no new cards", self._messages(panel))
        self.assertEqual(panel.fields_var.get(), "")

    def test_a_scope_already_in_order_offers_nothing_to_write(self):
        """Idempotence, and the common answer on a second press."""
        cards = [_card(1700 + i, 2830 + i, word) for i, word in enumerate(_RANKED_WORDS)]
        writes, stats = plan(cards, _RANK_OF)
        stats.update({"decks": ["TheBank"], "fields": {"Lapis": "Expression"}})
        self.assertEqual(writes, [], "the fixture should already be in rank order")
        panel = self._panel()
        self._previewed(panel, stats)
        self.assertIn("already in the right place", self._messages(panel))


class TestProgressAndThreading(JunbanGuiTestCase):
    def test_the_progress_bar_is_determinate_over_chunks(self):
        """The count is known up front, so the bar is a real fraction rather than a barber's pole."""
        panel = self._panel()
        self.assertEqual(str(panel.progress.cget("mode")), "determinate")
        panel.q.put(("__PROGRESS__", 150, 450))
        panel._drain_once()
        self.assertEqual(int(panel.progress["maximum"]), 450)
        self.assertEqual(int(panel.progress["value"]), 150)

    def test_the_writers_progress_callback_only_touches_the_queue(self):
        """It runs on the worker thread — a widget call from there is the bug this rules out."""
        panel = self._panel()
        panel._progress(3, 7)
        self.assertEqual(panel.q.get_nowait(), ("__PROGRESS__", 3, 7))

    def test_a_failing_worker_releases_the_panel(self):
        """A crash on the worker must not leave every button greyed with no way back."""
        panel = self._panel()
        panel._set_busy(True)

        def boom():
            raise RuntimeError("AnkiConnect went away")

        panel._guarded(boom)()              # run the wrapper inline; no thread, no timer
        panel._drain_once()
        self.assertFalse(panel.busy)
        self.assertIn("AnkiConnect went away", self._messages(panel))
        self.assertEqual(self._state(panel.btn_preview), "normal")

    def test_the_pump_writes_plain_messages_through(self):
        panel = self._panel()
        panel.q.put("走り出した")
        panel._drain_once()
        self.assertIn("走り出した", self._messages(panel))


class TestRestore(JunbanGuiTestCase):
    def test_restore_with_no_snapshot_says_so_and_touches_nothing(self):
        with mock.patch.object(junban_gui.undo, "load", return_value=None), \
             mock.patch.object(junban_gui.reposition, "restore") as restore:
            panel = self._panel()
            panel.on_restore()
        restore.assert_not_called()
        self.assertIn("No saved order", self._messages(panel))

    def test_restore_asks_first_and_declining_writes_nothing(self):
        """`ask` is neutered to 'no' by the conftest, which is also the safe default: a confirmation
        nobody answered must stop, not go on and write to a collection."""
        snapshot = {"schema": 1, "written_at": "2026-09-17T22:00:00", "scope": ["TheBank"],
                    "cards": {"1789711432547": 2832}}
        with mock.patch.object(junban_gui.undo, "load", return_value=snapshot), \
             mock.patch.object(junban_gui.reposition, "restore") as restore:
            panel = self._panel()
            panel.on_restore()
        restore.assert_not_called()

    def test_a_refused_restore_is_shown_verbatim(self):
        """`RestoreRefused`'s message names both scopes; paraphrasing it leaves the user guessing
        at the one moment something has already gone wrong."""
        refusal = ("That saved order was taken for TheBank, but this run covers TheBank, "
                   "The Accelerator.")
        report = {"ok": False, "message": "Nothing was restored.", "problems": [refusal],
                  "warnings": [], "written": [], "failures": []}
        snapshot = {"schema": 1, "written_at": "2026-09-17T22:00:00", "scope": ["TheBank"],
                    "cards": {"1789711432547": 2832}}
        with mock.patch.object(junban_gui.undo, "load", return_value=snapshot), \
             mock.patch.object(junban_gui, "ask", return_value=True), \
             mock.patch.object(junban_gui.reposition, "restore", return_value=report) as restore:
            panel = self._panel()
            panel.on_restore()
            panel._restore_worker(panel._settings())
            panel._drain_once()
        self.assertTrue(restore.called)
        self.assertIn(refusal, self._messages(panel))


class TestSettings(JunbanGuiTestCase):
    def test_the_word_field_overrides_are_copied_never_mutated(self):
        """`junban_word_fields` in loaded settings IS the dict inside SETTINGS_DEFAULTS — a shallow
        merge, so editing it in place poisons the default process-wide and leaks between tests
        (spec §13 #12)."""
        import modules.junban as junban
        default = junban.SETTINGS_DEFAULTS["junban_word_fields"]
        loaded = {"junban_word_fields": default, "junban_scope": "deck", "junban_deck": "TheBank"}
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: loaded)):
            panel = self._panel()
            settings = panel._settings()
            # What a caller would do next must not reach back into the default.
            settings["junban_word_fields"]["Migaku Japanese"] = "Target Word"

        self.assertEqual(default, {}, "the module default was mutated in place")
        self.assertEqual(junban.SETTINGS_DEFAULTS["junban_word_fields"], {})
        self.assertIsNot(settings["junban_word_fields"], default)
        self.assertIsNot(settings, loaded)

    def test_the_engine_is_handed_the_scope_the_widgets_show(self):
        panel = self._panel()
        panel.scope.set("deck")
        panel.deck.set("  TheBank  ")
        settings = panel._settings()
        self.assertEqual(settings["junban_scope"], "deck")
        self.assertEqual(settings["junban_deck"], "TheBank")     # trimmed, as the engine compares it
        self.assertTrue(settings.get("target_language"))

    def test_the_panel_persists_only_the_two_scope_keys(self):
        """It owns the scope and nothing else: every other setting has to survive a scope change."""
        saved = {}
        with mock.patch("app.settings_manager.load_settings",
                        return_value={"junban_scope": "deck", "junban_deck": "",
                                      "junban_chunk_size": 150, "target_language": "ja"}), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            panel.scope.set("all")
            panel._on_scope_changed()
        self.assertEqual(saved["junban_scope"], "all")
        self.assertEqual(saved["junban_chunk_size"], 150)


class TestConfirmationDialog(JunbanGuiTestCase):
    def test_the_dialog_defaults_to_no(self):
        """`wait_window` is STUBBED: a real modal in a test hangs the suite and names no test.
        Dismissal must mean no — this only ever stands in front of a write."""
        with mock.patch.object(tk.Toplevel, "wait_window", lambda *_a, **_k: None):
            dialog = junban_gui.JunbanDialog(self.root, "Restore the previous order?",
                                             details=["3 cards saved from TheBank"])
            self.assertFalse(dialog.answer)
            self.assertTrue(dialog.bind("<Escape>"), "Esc must close the dialog as 'no'")
            dialog._done(True)
        self.assertTrue(dialog.answer)


class TestCardsNotOnTheList(JunbanGuiTestCase):
    """Junban_Backlog_Spec §13 in the panel: "Cards not on your list: [ ] Tag [ ] Flag purple
    [ ] Suspend" — checkboxes, so any combination; none ticked reads "No action", the default."""

    def _stats(self):
        """A real dry run's shape: one listed word, two cards placed behind the list, and the §13 plan
        built by the engine's own planner over those rows."""
        from modules.junban import unlisted
        top = _RANKED_WORDS[0]
        cards = [_card(1, 2802, top) | {"sort": (1, -50, -5, 0, _RANK_OF[top])},
                 _card(2, 2801, "須藤") | {"tier": "rest", "sort": (9000,), "why": "FreqSort 9,000"},
                 _card(3, 2800, "美術館") | {"tier": "multi", "sort": (1, 6000), "why": "1 unknown"}]
        _writes, stats = plan(cards, _RANK_OF)
        stats.update({"decks": ["TheBank"], "fields": {}})
        stats["later"] = unlisted.plan(stats["order"], {}, "ja", {}, {},
                                       {"tag": True, "flag": True, "suspend": True}, parent="Surasura")
        return stats

    def test_no_action_is_the_default(self):
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS))):
            panel = self._panel()
        self.assertEqual({key: var.get() for key, var in panel.later_on.items()},
                         {"tag": False, "flag": False, "suspend": False})
        self.assertEqual(panel.later_state.get(), "No action")
        settings = panel._settings()
        self.assertEqual([settings[f"junban_later_{key}"] for key in ("tag", "flag", "suspend")],
                         [False, False, False])

    def test_any_combination_reaches_the_engine_the_file_and_the_preview_key(self):
        """Ticked together — tag and suspend — both are sent, both are saved, the header says so, and
        the preview on screen stops being a confirmation (I5)."""
        saved = {}
        loaded = dict(_DEFAULTS, junban_chunk_size=150, target_language="ja")
        with mock.patch("app.settings_manager.load_settings", return_value=loaded), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            self._previewed(panel)
            before = panel._scope_key()
            panel.later_on["tag"].set(True)
            panel.later_on["suspend"].set(True)
            panel._on_touchup_changed()
            settings = panel._settings()

        self.assertEqual((settings["junban_later_tag"], settings["junban_later_flag"],
                          settings["junban_later_suspend"]), (True, False, True))
        self.assertEqual((saved["junban_later_tag"], saved["junban_later_suspend"]), (True, True))
        self.assertNotEqual(panel._scope_key(), before)
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertIn("not on your list: tag + suspend", panel.touch_var.get())
        self.assertEqual(panel.later_state.get(), "")

    def test_the_cards_not_on_the_list_are_greyed_and_each_says_what_will_happen_to_it(self):
        """The user (2026-09-23): the rows used to be greyed when not on the list, and should be again
        — they are the ones the actions reach. Each says which, so a card about to be suspended can
        be seen (and clicked off) before Reorder. A clicked-off row loses its action at once."""
        panel = self._previewed(self._ticked(), self._stats())
        rows = {panel.tree.item(item)["values"][2]: panel.tree.item(item)
                for item in panel.tree.get_children()}

        for word in ("須藤", "美術館"):
            self.assertIn("unmatched", rows[word]["tags"])
            self.assertTrue(str(rows[word]["values"][4]).endswith("→ tag + flag + suspend"))
        self.assertNotIn("unmatched", rows[_RANKED_WORDS[0]]["tags"])
        self.assertNotIn("→", str(rows[_RANKED_WORDS[0]]["values"][4]))

        panel._toggle_row(next(item for item in panel.tree.get_children()
                               if panel.tree.item(item)["values"][2] == "須藤"))
        rows = {panel.tree.item(item)["values"][2]: panel.tree.item(item)
                for item in panel.tree.get_children()}
        self.assertNotIn("→", str(rows["須藤"]["values"][4]))
        self.assertIn("→ tag + flag + suspend", str(rows["美術館"]["values"][4]))

    def _ticked(self):
        panel = self._panel()
        for variable in panel.later_on.values():
            variable.set(True)
        return panel

    def test_a_word_clicked_off_the_list_joins_them_and_the_promise_grows(self):
        """The user (2026-09-23): clicked off, a word on the list is treated as not on it — the row
        says so, and the sentence now counts it among the cards the actions reach."""
        stats = self._stats()
        top = _RANKED_WORDS[0]
        stats["marks"] = {top: frozenset()}          # it IS on the list, so only the click can do it
        stats["order"] = [row._replace(fallback=("multi", (1, 5000), "1 unknown"))
                          if row.word == top else row for row in stats["order"]]
        panel = self._previewed(self._ticked(), stats)

        panel._toggle_row(next(item for item in panel.tree.get_children()
                               if panel.tree.item(item)["values"][2] == top))

        row = next(panel.tree.item(item) for item in panel.tree.get_children()
                   if panel.tree.item(item)["values"][2] == top)
        self.assertEqual(row["values"][4], "list #1  → off your list, tag + flag + suspend")
        messages = self._messages(panel)
        self.assertIn("1 you took off your list goes with the cards not on it.", messages)
        self.assertIn("Not on your list: tag 3 notes, flag 3 cards purple, and suspend 3 cards.",
                      messages)

    def test_the_preview_states_what_happens_to_them_and_a_deselection_shrinks_it(self):
        panel = self._previewed(self._ticked(), self._stats())
        self.assertIn("Not on your list: tag 2 notes, flag 2 cards purple, and suspend 2 cards.",
                      self._messages(panel))

        rows = {panel.tree.item(item)["values"][2]: item for item in panel.tree.get_children()}
        panel._toggle_row(rows["須藤"])
        self.assertIn("Not on your list: tag 1 note, flag 1 card purple, and suspend 1 card.",
                      self._messages(panel))


class TestTouchupPanel(JunbanGuiTestCase):
    """WP-L's "Also update the cards" group — the only part of this window that writes the user's
    own words rather than a queue position.

    Everything here is about the panel telling the truth before a write, because the preview is the
    only confirmation there is (I5) and a note field, unlike a `due`, cannot be recomputed.
    """

    def test_the_group_starts_collapsed(self):
        """It is not the first thing a hand should fall on: below it are the two switches that
        overwrite what the user wrote."""
        panel = self._panel()
        self.assertFalse(panel.touch_open)
        self.assertEqual(str(panel.touch_box.winfo_manager()), "",
                         "the group must not be laid out until it is opened")
        self.assertIn("Also update the cards", panel.touch_var.get())

        panel._toggle_touchups()
        self.root.update_idletasks()
        self.assertTrue(panel.touch_open)
        self.assertEqual(str(panel.touch_box.winfo_manager()), "pack")

    def test_nothing_that_overwrites_a_field_starts_switched_on(self):
        """The shipped defaults, as the widgets read them. The tag is additive and may start on;
        the frequency and the sort key may not."""
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS))):
            panel = self._panel()
        self.assertTrue(panel.tag_on.get(), "the tag is additive and is allowed to start on")
        self.assertFalse(panel.freq_on.get())
        self.assertFalse(panel.freqsort_on.get())
        # The extra example sentence moved to Anki Backfill's 例文 (2026-09-24): no trace of it here.
        self.assertFalse(hasattr(panel, "sentence_field"))
        self.assertNotIn("junban_sentence_field", panel._settings())

    def test_the_widgets_are_what_the_engine_is_handed(self):
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS))):
            panel = self._panel()
            panel.freq_on.set(True)
            panel.freq_field.set("  Frequency  ")
            settings = panel._settings()

        self.assertIs(settings["junban_write_frequency"], True)
        self.assertEqual(settings["junban_frequency_field"], "Frequency")     # trimmed
        self.assertIs(settings["junban_write_freqsort"], False)

    def test_unticking_the_tag_sends_the_disabling_value_not_the_saved_one(self):
        """An unticked box must mean "off" to the engine, not "keep whatever settings.json says" —
        otherwise the panel shows one thing and the run does another."""
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS))):
            panel = self._panel()
            panel.tag_on.set(False)
            self.assertEqual(panel._settings()["junban_tag"], "")

    def test_changing_a_touch_up_throws_the_preview_away(self):
        """The preview says "will move 47 cards and tag 47 notes". A preview taken with the tag off
        is not a confirmation of a run with it on, so `Reorder` greys out again (I5)."""
        with mock.patch("app.settings_manager.load_settings", return_value=dict(_DEFAULTS)), \
             mock.patch("app.settings_manager.save_settings"):
            panel = self._panel()
            self._previewed(panel)
            self.assertEqual(self._state(panel.btn_reorder), "normal")

            panel.freq_on.set(True)
            panel._on_touchup_changed()

        self.assertIsNone(panel._preview_scope)
        self.assertEqual(self._state(panel.btn_reorder), "disabled")

    def test_the_preview_states_the_touch_ups_in_the_same_sentence_as_the_move(self):
        """One sentence, deliberately: splitting "it will reorder your cards" from "it will also
        edit your notes" onto two lines lets a user read one of them and act on it."""
        stats = _real_stats()
        stats["touchups"] = {"counts": {"notes": 6, "tag": 6, "frequency": 6, "freqsort": 4}}
        panel = self._previewed(self._panel(), stats=stats)
        line = next(part for part in self._messages(panel).splitlines()
                    if part.startswith("Reorder will move"))

        self.assertIn("tag 6 notes", line)
        self.assertIn("add the frequency number to 6 notes", line)
        self.assertIn("OVERWRITE the sort number on 4 notes", line)

    def test_the_preview_says_nothing_extra_when_every_touch_up_is_off(self):
        stats = _real_stats()
        stats["touchups"] = {"counts": {"notes": 0, "tag": 0, "frequency": 0, "freqsort": 0}}
        panel = self._previewed(self._panel(), stats=stats)
        line = next(part for part in self._messages(panel).splitlines()
                    if part.startswith("Reorder will move"))
        self.assertNotIn("tag", line)
        self.assertNotIn("note", line.split("unmatched")[0])

    def test_overwriting_the_sort_key_is_announced_in_capitals(self):
        """It is the one touch-up that genuinely replaces a value the user's browser ordering
        depends on. The confirmation should not read like the harmless append beside it."""
        stats = _real_stats()
        stats["touchups"] = {"counts": {"notes": 3, "tag": 0, "frequency": 3, "freqsort": 3}}
        panel = self._previewed(self._panel(), stats=stats)
        self.assertIn("OVERWRITE the sort number on 3 notes", self._messages(panel))

    def test_the_field_picker_offers_the_users_real_fields_after_a_preview(self):
        """Filled from the note fields the preview actually found — never a guessed name, which is
        exactly what WP-L forbids."""
        stats = _real_stats()
        stats["field_names"] = ["Expression", "Frequency", "FreqSort", "Glossary", "Hint",
                                "MiscInfo", "SelectionText", "Sentence"]
        panel = self._previewed(self._panel(), stats=stats)

        self.assertIn("Frequency", panel.freq_box.cget("values"))
        self.assertIn("SelectionText", panel.freq_box.cget("values"))

    def test_a_field_the_user_typed_survives_a_preview_that_does_not_list_it(self):
        """It may belong to a note type outside this scope. Dropping it silently would look like
        the setting had been forgotten."""
        panel = self._panel()
        panel.freq_field.set("MyOwnField")
        stats = _real_stats()
        stats["field_names"] = ["Expression", "Sentence"]
        self._previewed(panel, stats=stats)

        self.assertIn("MyOwnField", panel.freq_box.cget("values"))
        self.assertEqual(panel.freq_field.get(), "MyOwnField")

    def test_the_panel_persists_the_touch_ups_without_disturbing_anything_else(self):
        saved = {}
        loaded = dict(_DEFAULTS, junban_chunk_size=150, target_language="ja")
        with mock.patch("app.settings_manager.load_settings", return_value=loaded), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            panel.freqsort_on.set(True)
            panel.freq_field.set("Frequency")
            panel._on_touchup_changed()

        self.assertIs(saved["junban_write_freqsort"], True)
        self.assertEqual(saved["junban_frequency_field"], "Frequency")
        self.assertEqual(saved["junban_chunk_size"], 150, "an unrelated setting was disturbed")

    def test_the_header_names_what_is_switched_on_while_collapsed(self):
        """Collapsed is the normal state, so the group has to be honest about itself from outside:
        a user must not have to open it to find out their notes are about to be edited."""
        with mock.patch("app.settings_manager.load_settings", return_value=dict(_DEFAULTS)), \
             mock.patch("app.settings_manager.save_settings"):
            panel = self._panel()
            self.assertIn("(tag)", panel.touch_var.get())

            panel.freq_on.set(True)
            panel.freqsort_on.set(True)
            panel._on_touchup_changed()

        self.assertIn("frequency", panel.touch_var.get())
        self.assertIn("sort number", panel.touch_var.get())

    def test_a_report_names_note_failures_apart_from_card_failures(self):
        """They are different id spaces. "3 failed" over both would give the user a number they
        cannot look up in Anki's browser."""
        panel = self._panel()
        panel.q.put(("__REPORT__", {"ok": False, "message": "Reordered 6 cards.",
                                    "problems": [], "warnings": [], "written": [1, 2],
                                    "failures": [], "note_failures": [(1789712000000, "no such note")]}))
        panel._drain_once()
        text = self._messages(panel)
        self.assertIn("1 note(s) could not be updated", text)
        self.assertIn("1789712000000", text)


class TestOrderAndMarkers(JunbanGuiTestCase):
    """WP-M and WP-N in the panel: two compact rows, and a marker column in the preview.

    Both controls change the ORDER about to be written, not a detail of it, so both belong in the
    preview-invalidation key exactly as the deck does. A preview of the leverage order is not a
    confirmation of a run in content order — on the live library they do not even share a first
    card (invariant I5).
    """

    def test_the_order_defaults_to_the_order_the_words_will_be_met_in(self):
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS))):
            panel = self._panel()
        self.assertEqual(panel.order.get(), "content")
        self.assertEqual(panel._order_value(), "content")

    def test_a_saved_order_is_what_the_panel_opens_on(self):
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS, junban_order="priority"))):
            panel = self._panel()
        self.assertEqual(panel.order.get(), "priority")

    def test_no_marker_is_ticked_by_default(self):
        """Empty means everything. Star alone covers 55% of the live library, so a filter that
        arrived switched on would quietly leave 45% of the backlog where it was."""
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS))):
            panel = self._panel()
        self.assertEqual(panel._only_marker_values(), ())

    def test_a_saved_filter_is_restored_and_normalised(self):
        saved = dict(_DEFAULTS, junban_only_markers=["reading", "star", "sparkle"])
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: saved)):
            panel = self._panel()
        self.assertEqual(panel._only_marker_values(), ("star", "reading"))

    def test_changing_the_order_throws_the_preview_away(self):
        """The one that matters most: the table on screen is the leverage order, and the button
        would have written the content order."""
        panel = self._panel()
        self._previewed(panel)
        self.assertEqual(self._state(panel.btn_reorder), "normal")

        panel.order.set("priority")
        panel._on_scope_changed()
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertIsNone(panel._preview_scope)
        self.assertFalse(panel.tree.get_children(), "the other order is still on screen")

    def test_changing_the_marker_filter_throws_the_preview_away(self):
        panel = self._panel()
        self._previewed(panel)
        self.assertEqual(self._state(panel.btn_reorder), "normal")

        panel.only_markers["star"].set(True)
        panel._on_scope_changed()
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertIsNone(panel._preview_scope)

    def test_the_marker_switch_in_the_touch_up_group_throws_the_preview_away(self):
        panel = self._panel()
        self._previewed(panel)
        panel.markers_on.set(True)
        panel._on_touchup_changed()
        self.assertEqual(self._state(panel.btn_reorder), "disabled")

    def test_both_controls_are_part_of_the_preview_key(self):
        """Asserted on the key itself, not only on the button, so the reason survives a refactor."""
        panel = self._panel()
        before = panel._scope_key()
        panel.order.set("priority")
        self.assertNotEqual(panel._scope_key(), before)
        middle = panel._scope_key()
        panel.only_markers["reading"].set(True)
        self.assertNotEqual(panel._scope_key(), middle)

    def test_the_engine_is_handed_the_order_and_filter_the_widgets_show(self):
        panel = self._panel()
        panel.order.set("priority")
        panel.only_markers["star"].set(True)
        panel.markers_on.set(True)
        settings = panel._settings()
        self.assertEqual(settings["junban_order"], "priority")
        self.assertEqual(settings["junban_only_markers"], ["star"])
        self.assertIs(settings["junban_tag_markers"], True)

    def test_the_marker_list_handed_out_is_a_fresh_one(self):
        """A container in loaded settings can BE the object inside SETTINGS_DEFAULTS after the
        shallow merge (spec §13 #12), so the panel must never hand its own list around."""
        default = _junban.SETTINGS_DEFAULTS["junban_only_markers"]
        loaded = {"junban_only_markers": default, "junban_scope": "deck", "junban_deck": "TheBank"}
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: loaded)):
            panel = self._panel()
            settings = panel._settings()
            settings["junban_only_markers"].append("star")

        self.assertEqual(default, [], "the module default was mutated in place")
        self.assertIsNot(settings["junban_only_markers"], default)

    def test_the_panel_persists_the_order_and_the_filter(self):
        saved = {}
        loaded = dict(_DEFAULTS, junban_chunk_size=150, target_language="ja")
        with mock.patch("app.settings_manager.load_settings", return_value=loaded), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            panel.order.set("priority")
            panel.only_markers["reading"].set(True)
            panel._on_scope_changed()

        self.assertEqual(saved["junban_order"], "priority")
        self.assertEqual(saved["junban_only_markers"], ["reading"])
        self.assertEqual(saved["junban_chunk_size"], 150, "an unrelated setting was disturbed")

    def test_list_first_is_ticked_unless_the_journey_was_chosen(self):
        """The user's rule is the default: the list's words ahead of everything it cut off. A saved
        "journey" opens unticked; a hand-set "back" (v1, no control of its own) reads as ticked and
        is kept rather than quietly replaced."""
        for saved, ticked, value in ((None, True, "list_first"), ("journey", False, "journey"),
                                     ("back", True, "back")):
            loaded = dict(_DEFAULTS, junban_unlisted=saved)
            with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                                   staticmethod(lambda loaded=loaded: loaded)):
                panel = self._panel()
            self.assertIs(panel.list_first.get(), ticked, saved)
            self.assertEqual(panel._unlisted_value(), value, saved)

    def test_phrases_are_on_unless_switched_off_and_the_choice_is_kept(self):
        """The user's choice (2026-09-23): phrases included by default, with the ability to leave them
        out. A saved "off" opens unticked; the box reaches the engine, the preview key and the file."""
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS))):
            panel = self._panel()
        self.assertIs(panel.phrases.get(), True)
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS, junban_phrases=False))):
            panel = self._panel()
        self.assertIs(panel.phrases.get(), False)

        saved = {}
        loaded = dict(_DEFAULTS, junban_chunk_size=150, target_language="ja")
        with mock.patch("app.settings_manager.load_settings", return_value=loaded), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            self._previewed(panel)
            before = panel._scope_key()
            panel.phrases.set(False)
            # Read BEFORE the save: the mocked save writes into the very dict the panel loads.
            self.assertIs(panel._settings()["junban_phrases"], False)
            panel._on_scope_changed()
        self.assertNotEqual(panel._scope_key(), before)
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertIs(saved["junban_phrases"], False)

    def test_list_first_throws_the_preview_away_and_reaches_the_engine_and_the_file(self):
        """It changes the order itself, not a detail of it: ticked, the words the list cut off go
        behind it; unticked, among it. A preview of one is no confirmation of the other (I5)."""
        saved = {}
        loaded = dict(_DEFAULTS, junban_chunk_size=150, target_language="ja")
        with mock.patch("app.settings_manager.load_settings", return_value=loaded), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            self._previewed(panel)
            self.assertEqual(self._state(panel.btn_reorder), "normal")
            before = panel._scope_key()
            panel.list_first.set(False)
            # Read BEFORE the save: the mocked save writes into the very dict the panel loads.
            self.assertEqual(panel._settings()["junban_unlisted"], "journey")
            panel._on_scope_changed()

        self.assertNotEqual(panel._scope_key(), before)
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertEqual(saved["junban_unlisted"], "journey")
        self.assertEqual(saved["junban_chunk_size"], 150, "an unrelated setting was disturbed")

    def test_the_preview_shows_a_marker_per_row(self):
        """The preview is the confirmation, so the markers have to be on screen before a single
        tag or position is written.

        Asserted against MARKER_GLYPHS rather than against literal characters: the glyphs are a
        deliberate choice (text, never emoji, because Anki's renderer has no colour font) and a
        test that hardcodes them just has to be edited every time that choice is revisited."""
        panel = self._panel()
        stats = _real_stats()
        first = stats["order"][0].word
        stats["marks"] = {first: frozenset({"star", "reading"})}
        self._previewed(panel, stats)

        rows = [panel.tree.item(item)["values"] for item in panel.tree.get_children()]
        self.assertEqual(rows[0][3], junban_gui.MARKER_GLYPHS["star"] + junban_gui.MARKER_GLYPHS["reading"],
                         "the glyphs belong beside the word")
        self.assertEqual(rows[1][3], "", "a word with no markers shows nothing, not a placeholder")

    def test_a_word_the_filter_excluded_still_shows_its_own_marker(self):
        """That IS the explanation for why it is sitting at the back — going blank there would make
        the filter look like a bug."""
        panel = self._panel()
        stats = _real_stats()
        excluded = [row for row in stats["order"] if row.rank is None][0]
        stats["marks"] = {excluded.word: frozenset({"lopsided"})}
        stats["only_markers"] = ["star"]
        self._previewed(panel, stats)

        rows = [panel.tree.item(item)["values"] for item in panel.tree.get_children()]
        self.assertIn(junban_gui.MARKER_GLYPHS["lopsided"], [row[3] for row in rows])

    def test_the_filter_is_named_beside_the_match_count(self):
        """"12 of 152 matched" with no explanation reads as a disappointing result rather than as
        the user's own choice."""
        panel = self._panel()
        stats = _real_stats()
        stats["only_markers"] = ["star", "reading"]
        self._previewed(panel, stats)
        self.assertIn(f'only {junban_gui.MARKER_GLYPHS["star"]} {junban_gui.MARKER_GLYPHS["reading"]}', panel.match_var.get())

    def test_nothing_extra_is_said_when_no_filter_is_set(self):
        panel = self._panel()
        self._previewed(panel, _real_stats())
        self.assertNotIn("only", panel.match_var.get())

    def test_the_preview_promises_the_marker_tags_in_the_same_sentence_as_the_move(self):
        panel = self._panel()
        stats = _real_stats()
        stats["touchups"] = {"counts": {"tag": 6, "markers": 4}}
        self._previewed(panel, stats)
        text = self._messages(panel)
        self.assertIn("tag 6 notes", text)
        self.assertIn("add marker tags to 4 notes", text)

    def test_a_preview_with_no_marker_map_renders_rather_than_failing(self):
        """Empty state: a results folder too old to carry the columns, or an engine that answered
        before the map was built. The column simply stays blank."""
        panel = self._panel()
        stats = _real_stats()
        stats.pop("marks", None)
        self._previewed(panel, stats)
        rows = [panel.tree.item(item)["values"] for item in panel.tree.get_children()]
        self.assertTrue(rows)
        self.assertEqual({row[3] for row in rows}, {""})



class TestDeselectingARow(JunbanGuiTestCase):
    """WP-O. The `#` column doubles as the checkbox `ttk.Treeview` does not have.

    Everything here is about one promise: whatever the table shows after a click is the order that
    would actually be written (I5). A deselected card is planned as **unmatched** — the mechanism
    that already existed for a filtered word or one the list has never heard of — so it keeps its
    existing relative order at the back, and nothing is ever left unpositioned.
    """

    def _rows(self, panel):
        return [panel.tree.item(item)["values"] for item in panel.tree.get_children()]

    def _items_by_card(self, panel):
        return {card_id: item for item, card_id in panel._row_cards.items()}

    def _click(self, panel, item):
        """The real click path, minus the geometry a withdrawn window cannot answer for.

        `identify_row` needs a mapped widget with a real height; patching the two identify calls
        keeps the test on `_on_row_clicked` itself — the region guard, the focus, the toggle — rather
        than on Tk's ability to hit-test an invisible table.
        """
        with mock.patch.object(panel.tree, "identify_region", return_value="cell"), \
             mock.patch.object(panel.tree, "identify_row", return_value=item):
            return panel._on_row_clicked(mock.Mock(x=40, y=30))

    def test_every_row_starts_selected(self):
        """The normal case, and the one the user never has to think about: a fresh preview is the
        whole scope, numbered 1..N, with nothing excluded and nothing said about exclusions."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)

        rows = self._rows(panel)
        self.assertEqual([row[0] for row in rows], list(range(1, len(rows) + 1)))
        self.assertNotIn(junban_gui.DESELECTED_GLYPH, [row[0] for row in rows])
        self.assertEqual(panel._settings()["junban_exclude_cards"], [])
        self.assertNotIn("deselected", self._messages(panel))

    def test_the_table_is_the_plan_it_was_handed(self):
        """Nothing is deselected, so the rows must still be the planner's own rows in the planner's
        own order — WP-O may not disturb the answer it is layered on top of."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)

        self.assertEqual([panel._row_cards[item] for item in panel.tree.get_children()],
                         [row.card_id for row in stats["order"]])

    def test_a_deselected_row_stays_where_it_was_clicked(self):
        """The card leaves the run, but the ROW does not move.

        It used to be redrawn at the back, where the plan puts it — which meant an accidental click
        threw the row hundreds of places down a long list and undoing it meant going to look for it.
        Deselection is shown in place instead: `✗`, no number, greyed, right where the pointer is,
        so clicking again is the obvious undo.

        Nothing is misrepresented by that. The number in the `#` column is the claim "this card is
        in the run"; a deselected row carries none, and the numbered rows still read 1..N in the
        order they will be written.
        """
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        before = [panel._row_cards[item] for item in panel.tree.get_children()]
        victim = stats["order"][1].card_id

        self._click(panel, self._items_by_card(panel)[victim])

        after = [panel._row_cards[item] for item in panel.tree.get_children()]
        self.assertEqual(after, before, "no row may change places when one is deselected")
        rows = self._rows(panel)
        numbers = [row[0] for row in rows if row[0] != junban_gui.DESELECTED_GLYPH]
        self.assertEqual(numbers, list(range(1, len(rows))), "the numbering must close up")
        self.assertEqual(rows[before.index(victim)][0], junban_gui.DESELECTED_GLYPH)
        self.assertEqual(rows[before.index(victim)][1], "", "a deselected row claims no position")

    def test_the_same_row_is_still_under_the_pointer_after_a_click(self):
        """The undo for a mis-click is clicking again, which only works if the row has not moved —
        so the item under that screen position must still be the card that was just deselected.
        (`test_clicking_it_again_restores_the_original_table` covers the round trip itself.)"""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        victim = stats["order"][1].card_id
        position = panel.tree.get_children().index(self._items_by_card(panel)[victim])

        self._click(panel, self._items_by_card(panel)[victim])

        still_there = panel.tree.get_children()[position]
        self.assertEqual(panel._row_cards[still_there], victim,
                         "the deselected card must stay at the same place in the table")

    def test_the_numbered_rows_are_the_order_that_would_be_written(self):
        """Invariant I5, which is the whole reason the preview is re-planned rather than patched.

        Rows are DRAWN where the user last saw them (so a mis-click is undone where it happened),
        but the run they describe still has to be the run `plan` would produce. So the check is on
        the numbered rows in their written sequence, not on the raw row order.
        """
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        victims = [stats["order"][0].card_id, stats["order"][4].card_id]
        for card_id in victims:
            self._click(panel, self._items_by_card(panel)[card_id])

        from modules.junban.plan import replan
        _writes, expected = replan(stats["order"], set(victims))

        # What the panel says the run is: the rows carrying a number, in position order.
        drawn = [(panel._row_cards[item], panel.tree.item(item)["values"])
                 for item in panel.tree.get_children()]
        included = [card_id for card_id, values in drawn
                    if values[0] != junban_gui.DESELECTED_GLYPH]
        included.sort(key=lambda cid: dict((c, v[1]) for c, v in drawn)[cid])

        self.assertEqual(included,
                         [row.card_id for row in expected["order"]
                          if row.card_id not in set(victims)])
        self.assertEqual(sorted(panel._settings()["junban_exclude_cards"]), sorted(victims))

    def test_clicking_it_again_restores_the_original_table(self):
        """Not a one-way door, and it leaves nothing behind: every cell must come back as it was."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        before = self._rows(panel)
        victim = stats["order"][2].card_id

        self._click(panel, self._items_by_card(panel)[victim])
        self.assertNotEqual(self._rows(panel), before, "the click must actually change something")
        self._click(panel, self._items_by_card(panel)[victim])

        self.assertEqual(self._rows(panel), before)
        self.assertEqual(panel._settings()["junban_exclude_cards"], [])

    def test_a_deselected_row_shows_a_cross_no_position_and_the_muted_colour(self):
        """What the user sees instead of a checkbox: the number is where "in this run" is stated,
        so a row that is out of it says so there — and it has no position, because it is no longer
        being placed by the list."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        victim = stats["order"][0].card_id

        self._click(panel, self._items_by_card(panel)[victim])

        item = self._items_by_card(panel)[victim]
        row = panel.tree.item(item)
        self.assertEqual(row["values"][0], junban_gui.DESELECTED_GLYPH)
        self.assertEqual(row["values"][1], "", "a card out of the run has no new position")
        self.assertIn("unmatched", row["tags"], "it takes the grey the unmatched block already has")
        self.assertEqual(str(panel.tree.tag_configure("unmatched", "foreground")),
                         junban_gui.DISABLED)

    def test_a_deselected_row_still_says_what_it_was(self):
        """It is greyed, not blanked: the word, its markers and why it was placed ("list #1", the
        rank the list gave it) are the answer to "what am I taking out?", which is exactly the
        question at that moment."""
        panel = self._panel()
        stats = _real_stats()
        first = stats["order"][0]
        stats["marks"] = {first.word: frozenset({"star"})}
        self._previewed(panel, stats)

        self._click(panel, self._items_by_card(panel)[first.card_id])

        row = panel.tree.item(self._items_by_card(panel)[first.card_id])["values"]
        self.assertEqual(row[2], first.word)
        self.assertEqual(row[3], junban_gui.MARKER_GLYPHS["star"])
        self.assertEqual(row[4], f"list #{first.rank + 1}  · left alone",
                         "the rank it was given is still worth seeing, and what the click did")

    def test_deselecting_every_matched_row_is_legal_and_orders_nothing(self):
        """The extreme case, and it must not be a special one — no crash, no empty table, and the
        unmatched block simply keeps the queue it already had."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        matched = [row.card_id for row in stats["order"] if row.rank is not None]

        for card_id in matched:
            self._click(panel, self._items_by_card(panel)[card_id])

        rows = self._rows(panel)
        self.assertEqual(len(rows), len(stats["order"]), "every card is still on screen")
        crosses = [row for row in rows if row[0] == junban_gui.DESELECTED_GLYPH]
        self.assertEqual(len(crosses), len(matched))
        self.assertIn(f"{len(matched)} you left alone keep their current order",
                      self._messages(panel))

    def test_the_sentence_gains_a_clause_only_when_something_is_deselected(self):
        """Silence at zero, which is the normal case — and the count named plainly when it is not,
        in the same sentence as the move, because that sentence is the whole confirmation (I5)."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        self.assertNotIn("you left alone", self._messages(panel))

        for row in stats["order"][:3]:
            self._click(panel, self._items_by_card(panel)[row.card_id])

        self.assertIn("3 you left alone keep their current order.", self._messages(panel))
        self.assertEqual(self._messages(panel).count("you left alone"), 1,
                         "one sentence, stated once — not a line per click")

    def test_one_deselected_row_is_said_in_the_singular(self):
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)

        self._click(panel, self._items_by_card(panel)[stats["order"][0].card_id])

        self.assertIn("1 you left alone keeps its current order.", self._messages(panel))

    def test_space_toggles_the_focused_row(self):
        """The keyboard route to the same act. The binding returns "break" so ttk's own space
        binding — which toggles the selection — never also runs."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        victim = stats["order"][0].card_id
        panel.tree.focus(self._items_by_card(panel)[victim])

        self.assertEqual(panel._on_row_space(), "break")

        self.assertEqual(panel._settings()["junban_exclude_cards"], [victim])
        self.assertTrue(panel.tree.bind("<space>"), "Space must be bound on the table itself")
        panel._on_row_space()
        self.assertEqual(panel._settings()["junban_exclude_cards"], [], "Space toggles both ways")

    def test_the_toggled_row_keeps_the_keyboard_focus_after_the_redraw(self):
        """The whole table is rebuilt on every toggle, so the focus has to be put back on the card
        it was on — otherwise a second Space would land on whatever row Tk happened to focus."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        victim = stats["order"][1].card_id

        self._click(panel, self._items_by_card(panel)[victim])

        self.assertEqual(panel._row_cards.get(panel.tree.focus()), victim)

    def test_a_click_on_the_heading_toggles_nothing(self):
        """The heading row and the column separators belong to ttk — a drag to resize a column must
        not silently drop a card out of the run."""
        panel = self._panel()
        self._previewed(panel, _real_stats())

        with mock.patch.object(panel.tree, "identify_region", return_value="heading"), \
             mock.patch.object(panel.tree, "identify_row", return_value=""):
            self.assertIsNone(panel._on_row_clicked(mock.Mock(x=40, y=2)))

        self.assertEqual(panel._settings()["junban_exclude_cards"], [])

    def test_nothing_is_toggled_while_the_panel_is_busy(self):
        """Mid-write the settings have already been read; a click that changed them then would edit
        a run in flight, and the table would stop describing what is being written."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        item = self._items_by_card(panel)[stats["order"][0].card_id]
        panel.busy = True

        self._click(panel, item)
        panel.tree.focus(item)
        panel._on_row_space()

        self.assertEqual(panel._settings()["junban_exclude_cards"], [])

    def test_a_scope_change_clears_the_deselections(self):
        """They name rows that no longer exist. Keeping them would leave the next run quietly
        missing cards for a reason that is nowhere on screen."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        self._click(panel, self._items_by_card(panel)[stats["order"][0].card_id])

        panel.scope.set("all")
        panel._on_scope_changed()

        self.assertEqual(panel._deselected, set())
        self.assertEqual(panel._settings()["junban_exclude_cards"], [])

    def test_an_order_change_and_a_filter_change_clear_them_too(self):
        """Both re-plan the whole scope, so both replace the rows the deselection pointed at."""
        for change in ("order", "filter", "touchup"):
            panel = self._panel()
            stats = _real_stats()
            self._previewed(panel, stats)
            self._click(panel, self._items_by_card(panel)[stats["order"][0].card_id])
            self.assertTrue(panel._deselected, change)

            if change == "order":
                panel.order.set("priority")
                panel._on_scope_changed()
            elif change == "filter":
                panel.only_markers["star"].set(True)
                panel._on_scope_changed()
            else:
                panel.markers_on.set(True)
                panel._on_touchup_changed()

            self.assertEqual(panel._deselected, set(), change)
            self.assertFalse(panel.tree.get_children(), change)

    def test_a_fresh_preview_starts_with_everything_selected_again(self):
        """`Preview order` re-reads Anki, so it is a new set of rows — and a new set of rows starts
        the way every set of rows starts."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        self._click(panel, self._items_by_card(panel)[stats["order"][0].card_id])

        # `_start` is stubbed rather than run: the worker would reach `_context_counts`, and no test
        # in this suite may open a socket to the developer's own collection (spec §18.0 rule 6).
        with mock.patch.object(panel, "_start"):
            panel.on_preview()
        self.assertEqual(panel._deselected, set())

        self._previewed(panel, _real_stats())
        self.assertEqual(panel._deselected, set())
        self.assertNotIn(junban_gui.DESELECTED_GLYPH,
                         [row[0] for row in self._rows(panel)])

    def test_nothing_about_deselection_is_ever_persisted(self):
        """It is a decision about one run, not a setting. A remembered exclusion the user cannot see
        would quietly leave cards out of every run from then on — so it has no default, and the
        panel's own save names the keys it writes."""
        import modules.junban as junban
        self.assertNotIn("junban_exclude_cards", junban.SETTINGS_DEFAULTS)

        saved = {}
        with mock.patch("app.settings_manager.load_settings",
                        return_value={"junban_scope": "deck", "junban_deck": "TheBank",
                                      "junban_chunk_size": 150, "target_language": "ja"}), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            stats = _real_stats()
            self._previewed(panel, stats)
            self._click(panel, self._items_by_card(panel)[stats["order"][0].card_id])
            panel._save_scope()

        self.assertTrue(panel._deselected, "the fixture must have something deselected")
        self.assertNotIn("junban_exclude_cards", saved)

    def test_reorder_stays_available_because_the_table_kept_up(self):
        """A deselection does NOT throw the preview away, unlike a scope or order change — and it
        must not, because the table redrew with it. The preview is the confirmation only while it
        describes the run about to happen, and after a click it still does."""
        panel = self._panel()
        stats = _real_stats()
        self._previewed(panel, stats)
        self.assertEqual(self._state(panel.btn_reorder), "normal")

        self._click(panel, self._items_by_card(panel)[stats["order"][0].card_id])

        self.assertEqual(self._state(panel.btn_reorder), "normal")
        self.assertEqual(panel._preview_scope, panel._scope_key())

    def test_the_table_carries_its_own_tooltip(self):
        """Mandatory in the GUI guidelines, and doubly so here: the toggle has no widget of its own
        to advertise it, so the table is where it has to be explained."""
        panel = self._panel()
        self.assertTrue(panel.tree.bind("<Enter>"))
        self.assertTrue(panel.tree.bind("<Button-1>"))

if __name__ == "__main__":          # pragma: no cover
    unittest.main()


class TestMarkerGlyphsAreText(JunbanGuiTestCase):
    """The marks have to render wherever the user looks at them, and that rules out emoji.

    An emoji is drawn from a colour font. Anki's card renderer and several UI fonts do not carry
    one, so the mark lands as a blank box — worse than no mark, because a blank box reads as a bug.
    """

    #: Ranges that Windows/Anki draw from the colour emoji font.
    #: The astral planes, which exist ONLY as colour emoji \u2014 there is no text form to fall back on.
    #: This is the band \uD83D\uDCD6 (U+1F4D6) came from. BMP dingbats like \u2606 and \u2696 are ordinary text glyphs
    #: and are fine; a few of those merely *prefer* emoji, which U+FE0E settles.
    EMOJI_PLANES = ((0x1F000, 0x1FAFF),)

    def test_no_marker_glyph_needs_a_colour_font(self):
        for name, glyph in junban_gui.MARKER_GLYPHS.items():
            point = ord(glyph[0])
            self.assertFalse(
                any(lo <= point <= hi for lo, hi in self.EMOJI_PLANES),
                f"{name} uses U+{point:04X}, which exists only as colour emoji \u2014 Anki's renderer "
                f"draws it as a blank box. Pick a BMP text glyph.")

    def test_a_glyph_that_prefers_emoji_carries_the_text_selector(self):
        """U+2696 is text by default on most platforms and emoji on some. U+FE0E settles it, and
        costs nothing where it was already text."""
        assert "\u2696" in junban_gui.MARKER_GLYPHS["lopsided"]
        assert "\uFE0E" in junban_gui.MARKER_GLYPHS["lopsided"]

    def test_the_reading_mark_matches_the_report(self):
        """It was 📖, which is wrong twice: an emoji, AND in the report 📖 is the *epub source*
        icon. The reading marker there is 文 (`templates/web_app.html:321`) — the glyph the user
        has already learned to read."""
        self.assertEqual(junban_gui.MARKER_GLYPHS["reading"], "文")

    def test_every_marker_has_a_glyph(self):
        from modules.junban import match
        self.assertEqual(set(junban_gui.MARKER_GLYPHS), set(match.MARKERS))

    def test_the_tag_carries_the_mark_itself(self):
        """The user asked for the mark rather than the word, so the tag tree reads
        `Surasura ▸ ☆ / ⚖ / 文` and is recognisable at a glance in Anki's sidebar. You click it
        there rather than typing it, which is what made spelling it out unnecessary."""
        from modules.junban import touchup
        for name in junban_gui.MARKER_GLYPHS:
            tag = touchup.marker_tag("Surasura", name)
            self.assertTrue(tag.startswith("Surasura::"))
            self.assertEqual(tag.split("::", 1)[1], touchup.MARKER_TAG_LEAF[name])

    def test_no_tag_leaf_carries_an_invisible_selector(self):
        """Verified against the live collection: `Surasura::⚖` and `Surasura::⚖︎` round-trip as TWO
        SEPARATE TAGS, because U+FE0E is a real character that simply cannot be seen. Two tags
        nobody can tell apart is the worst outcome available here — so the panel keeps the selector
        for rendering and the tag never does."""
        from modules.junban import touchup
        for name, leaf in touchup.MARKER_TAG_LEAF.items():
            self.assertNotIn("︎", leaf, f"{name}'s tag leaf carries a text selector")
            self.assertNotIn("️", leaf, f"{name}'s tag leaf carries an emoji selector")
        self.assertEqual(len(set(touchup.MARKER_TAG_LEAF.values())),
                         len(touchup.MARKER_TAG_LEAF), "two markers share a tag leaf")


class TestNoGlyphIsHardcoded(JunbanGuiTestCase):
    def test_the_marker_column_header_matches_the_glyphs_in_its_rows(self):
        """The header was spelled out as a literal and silently kept showing 📖 after the marks
        moved to 文 — a header disagreeing with the column under it is worse than no header."""
        from modules.junban import match
        panel = self._panel()
        header = panel.tree.heading("marks")["text"]
        self.assertEqual(header,
                         "".join(junban_gui.MARKER_GLYPHS[m] for m in match.MARKERS))
        for glyph in junban_gui.MARKER_GLYPHS.values():
            self.assertIn(glyph, header)


class TestVisualBehaviour(JunbanGuiTestCase):
    """Three things reported from real use. Each was invisible to every other test in this file,
    because they are about what the window LOOKS like rather than what it decides."""

    def test_every_interactive_style_pins_its_hover_state(self):
        """A `configure` with no `map` lets ttk paint ACTIVE and PRESSED from the base theme, whose
        active fill is near-white — the column headings flashed stark white on hover against the
        dark panel. Anything a pointer can touch has to say what it looks like when touched."""
        panel = self._panel()
        for style_name in ("Jun.TButton", "JunIcon.TButton", "Jun.TCheckbutton",
                           "Jun.TRadiobutton", "Jun.Treeview.Heading"):
            active = panel.tk.call("ttk::style", "map", style_name, "-background")
            self.assertTrue(active, f"{style_name} has no background map — hover is unstyled")
            self.assertNotIn("white", str(active).lower())
            self.assertNotIn("#ffffff", str(active).lower())

    def test_the_group_caption_is_not_clipped_to_a_fixed_width(self):
        """Its text grows as extras are switched on — "… (tag + markers)" — and a fixed width cut
        it off mid-word."""
        panel = self._panel()
        self.assertIn(panel.btn_touch.cget("width"), (0, ""),
                      "a fixed width truncates the caption once extras are on")

    def test_a_row_can_be_seen_to_be_selected(self):
        """With selectmode="none" a click left no mark at all, so there was no telling which row
        had just been acted on."""
        panel = self._panel()
        self.assertEqual(str(panel.tree.cget("selectmode")), "browse")

    def test_toggling_a_row_does_not_scroll_the_table(self):
        """Deselecting sends that row to the back of a list hundreds long. Following it there
        yanked the whole table out from under the user on every single click."""
        panel = self._panel()
        self._previewed(panel)
        items = panel.tree.get_children()
        if len(items) < 2:
            self.skipTest("needs more than one row to have a scroll position")
        before = panel.tree.yview()
        panel._toggle_row(items[0])
        self.assertAlmostEqual(panel.tree.yview()[0], before[0], places=3,
                               msg="the view moved when a row was toggled")



# --------------------------------------------------------------------------- #
# §16 — "Same word as one on your list?": just ticks, re-planned at once, recorded by Reorder
# --------------------------------------------------------------------------- #
_MITORERU = ("見惚れる", 957, (957,), "list #958 · you matched it")
_DOUKOU = ("同行", 1343, (1343,), "list #1,344 · you matched it")


def _check_stats(answered=False):
    """The real backlog's spelling variants (§12). 冒険 is on the list; 見とれる may be 見惚れる and
    同行する may be 同行, both placed by their sentence until ticked. `answered`: 見とれる was
    ticked before (placed with the list, "you matched it"), 同行する was answered no."""
    mitoreru = dict(_card(1701, 2801, "見とれる"), tier="i+1", sort=(12000,), why="i+1",
                    suggestion=_MITORERU)
    if answered:
        mitoreru = dict(_card(1701, 2801, "見とれる"), key="見惚れる", sort=(957,), why=_MITORERU[3],
                        fallback=("i+1", (12000,), "i+1"), suggestion=_MITORERU)
    cards = [dict(_card(1700, 2802, "美術館"), tier="multi", sort=(1, 6000), why="1 unknown"),
             mitoreru,
             # Before 見とれる by its sentence, so a tick on 見とれる has to move it past this row.
             dict(_card(1702, 2803, "同行する"), tier="i+1", sort=(9000,), why="i+1", suggestion=_DOUKOU),
             _card(1703, 2800, "冒険")]
    _writes, stats = plan(cards, {"冒険": 0, "見惚れる": 957})
    stats["decks"] = ["TheBank"]
    stats["suggestions"] = [
        {"word": "見とれる", "key": "見惚れる", "rank": 957, "reading": "みとれる",
         "evidence": "same word, other spelling", "via": "L6", "excerpt": "思わず【見とれて】しまった。",
         "answer": "yes" if answered else None, "card_ids": [1701]},
        {"word": "同行する", "key": "同行", "rank": 1343, "reading": "どうこう", "evidence": "+ する",
         "via": "L7", "excerpt": "私も【同行する】よ", "answer": "no" if answered else None,
         "card_ids": [1702]}]
    return stats


class TestCheckMatches(JunbanGuiTestCase):
    def _checks(self, panel):
        return [panel.check_tree.item(item)["values"] for item in panel.check_tree.get_children()]

    def _item(self, panel, word):
        return next(item for item, name in panel._check_rows.items() if name == word)

    def _click(self, panel, word):
        with mock.patch.object(panel.check_tree, "identify_row", return_value=self._item(panel, word)):
            return panel._on_check_clicked(mock.Mock(x=40, y=10))

    def _row_of(self, panel, word):
        return next(panel.tree.item(item)["values"] for item in panel.tree.get_children()
                    if panel.tree.item(item)["values"][2] == word)

    def test_with_nothing_to_check_the_list_takes_no_room(self):
        panel = self._previewed(self._panel())
        self.assertEqual(panel._checks_box.winfo_manager(), "")

    def test_every_word_to_check_is_shown_unticked_with_what_a_glance_needs(self):
        """The user reversed I6: nothing is pre-ticked, and nothing moves until it is."""
        panel = self._previewed(self._panel(), _check_stats())
        self.assertEqual(panel._checks_box.winfo_manager(), "pack")
        self.assertEqual(self._checks(panel), [
            [junban_gui.CHECK_OFF, "見とれる", "→ 見惚れる   #958", "みとれる", "思わず【見とれて】しまった。"],
            [junban_gui.CHECK_OFF, "同行する", "→ 同行   #1,344", "どうこう", "私も【同行する】よ"]])
        self.assertEqual(panel.checks_count_var.get(), "2 to check")
        self.assertEqual(self._row_of(panel, "見とれる")[4], "i+1 · 見惚れる?", "the table names it too")
        self.assertIn("1 of 4", panel.match_var.get())

    def test_a_click_ticks_the_word_and_the_preview_places_it_with_the_list_at_once(self):
        panel = self._previewed(self._panel(), _check_stats())
        self.assertEqual(self._click(panel, "見とれる"), "break")
        self.assertEqual(self._checks(panel)[0][0], junban_gui.CHECK_ON)
        row = self._row_of(panel, "見とれる")
        self.assertEqual((row[0], row[4]), (2, "list #958 · you matched it"))
        self.assertIn("2 of 4", panel.match_var.get())
        self.assertEqual(self._state(panel.btn_reorder), "normal", "the preview kept up: Reorder stays")
        # The numbered rows are still the order that would be written: 冒険, 見とれる, then the rest.
        drawn = [panel.tree.item(item)["values"][2] for item in panel.tree.get_children()]
        self.assertEqual(drawn[:2], ["冒険", "見とれる"])

    def test_space_ticks_the_focused_word_and_a_second_tick_takes_it_back(self):
        panel = self._previewed(self._panel(), _check_stats())
        panel.check_tree.focus(self._item(panel, "同行する"))
        panel._on_check_space()
        self.assertEqual(self._row_of(panel, "同行する")[4], "list #1,344 · you matched it")
        self._click(panel, "同行する")
        self.assertEqual(self._row_of(panel, "同行する")[4], "i+1 · 同行?")

    def test_reorder_records_ticked_as_the_same_word_and_unticked_as_not_then_runs(self):
        """No Done button: the answers are what the user left on screen when they pressed Reorder."""
        panel = self._previewed(self._panel(), _check_stats())
        self._click(panel, "見とれる")
        with mock.patch.object(junban_gui.pairs, "record") as record, \
             mock.patch.object(panel, "_start") as start:
            panel.on_reorder()
        record.assert_called_once_with("ja", [("見とれる", "見惚れる", True, "L6"),
                                              ("同行する", "同行", False, "L7")])
        start.assert_called_once()

    def test_answers_that_cannot_be_saved_stop_the_reorder(self):
        """The run reads them: running as if they were saved would write an order nobody previewed."""
        panel = self._previewed(self._panel(), _check_stats())
        with mock.patch.object(junban_gui.pairs, "record", side_effect=OSError("disk full")), \
             mock.patch.object(panel, "_start") as start:
            panel.on_reorder()
        start.assert_not_called()
        self.assertIn("nothing was reordered", self._messages(panel))

    def test_ticks_not_yet_recorded_go_with_the_preview(self):
        panel = self._previewed(self._panel(), _check_stats())
        self._click(panel, "見とれる")
        with mock.patch.object(junban_gui.pairs, "record") as record:
            panel._on_scope_changed()
        self.assertIsNone(panel._ticked)
        self.assertEqual(panel._checks_box.winfo_manager(), "")
        record.assert_not_called()

    def test_earlier_answers_wait_behind_a_link_and_are_changed_the_same_way(self):
        """All answered: the list takes no room, a message line leads to it. Unticking the earlier yes
        sends the card back to its sentence's place, and Reorder records only what changed."""
        panel = self._previewed(self._panel(), _check_stats(answered=True))
        self.assertEqual(panel._checks_box.winfo_manager(), "")
        self.assertIn("see or change them", self._messages(panel))
        panel._toggle_earlier()
        self.assertEqual(panel._checks_box.winfo_manager(), "pack")
        self.assertEqual([values[0] for values in self._checks(panel)],
                         [junban_gui.CHECK_ON, junban_gui.CHECK_OFF])
        self.assertEqual(panel.earlier_var.get(), "hide earlier answers")
        self._click(panel, "見とれる")
        self.assertEqual(self._row_of(panel, "見とれる")[4], "i+1 · 見惚れる?")
        with mock.patch.object(junban_gui.pairs, "record") as record, \
             mock.patch.object(panel, "_start"):
            panel.on_reorder()
        record.assert_called_once_with("ja", [("見とれる", "見惚れる", False, "L6")])

    def test_the_check_list_and_its_link_carry_tooltips(self):
        panel = self._panel()
        for widget in (panel.check_tree, panel.lnk_earlier):
            self.assertTrue(widget.bind("<Enter>"), widget)
            self.assertTrue(widget.bind("<Button-1>"), widget)


# --------------------------------------------------------------------------- #
# §16.9 — the list out of date: Preview order becomes "Generate & preview", Reorder waits
# --------------------------------------------------------------------------- #
class TestGenerateAndPreview(JunbanGuiTestCase):
    def _host(self):
        host = mock.MagicMock()
        host.var_language.get.return_value = "ja"
        host._analyzer_args.return_value = ["analyzer.py", "--static", "--language=ja"]
        return host

    def test_standalone_nothing_changes(self):
        """No dashboard, no Generate to offer: Preview order and Reorder as ever."""
        panel = self._previewed(self._panel())
        self.assertEqual(str(panel.btn_preview.cget("text")), "Preview order")
        self.assertEqual(self._state(panel.btn_reorder), "normal")

    def test_an_out_of_date_list_turns_preview_into_generate_and_keeps_reorder_shut(self):
        host = self._host()
        panel = self._previewed(self._panel(app=host), checks=dict(_OK_CHECKS, list_current=False))
        self.assertEqual(str(panel.btn_preview.cget("text")), "Generate & preview")
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertIn("Your list is out of date", self._messages(panel))
        self.assertTrue(panel.tree.get_children(), "the old list's order still shows (R6)")
        with mock.patch.object(panel, "_start") as start:
            panel.on_reorder()
        start.assert_not_called()

    def test_one_press_generates_quietly_and_never_twice(self):
        host = self._host()
        panel = self._previewed(self._panel(app=host), checks=dict(_OK_CHECKS, list_current=False))
        panel.on_preview()
        host.run_analyzer.assert_called_once_with(quiet=True)
        self.assertEqual(str(panel.btn_preview.cget("text")), "Generating…")
        self.assertEqual(self._state(panel.btn_preview), "disabled")
        panel.on_preview()
        host.run_analyzer.assert_called_once()

    def test_when_the_generate_finishes_the_preview_runs_by_itself_and_reorder_comes_back(self):
        host = self._host()
        panel = self._previewed(self._panel(app=host), checks=dict(_OK_CHECKS, list_current=False))
        panel.on_preview()
        with mock.patch.object(panel, "_start") as start:
            panel.on_list_updated()
        start.assert_called_once()
        self._previewed(panel, checks=dict(_OK_CHECKS, list_current=True))
        self.assertEqual(str(panel.btn_preview.cget("text")), "Preview order")
        self.assertEqual(self._state(panel.btn_reorder), "normal")

    def test_a_generate_that_did_not_help_says_so(self):
        host = self._host()
        panel = self._previewed(self._panel(app=host), checks=dict(_OK_CHECKS, list_current=False))
        panel.on_preview()
        with mock.patch.object(panel, "_start"):
            panel.on_list_updated()
        self._previewed(panel, checks=dict(_OK_CHECKS, list_current=False))
        self.assertIn("bring the list up to date — see", self._messages(panel))

    def test_a_preview_the_user_is_working_in_is_left_alone_by_someone_elses_generate(self):
        host = self._host()
        panel = self._previewed(self._panel(app=host), checks=dict(_OK_CHECKS, list_current=True))
        with mock.patch.object(panel, "_start") as start:
            panel.on_list_updated()
        start.assert_not_called()

    def test_the_worker_asks_the_generate_buttons_question_and_drops_the_half_answer(self):
        """The dashboard's answer covers library, known words and settings; preflight's library-only
        warning would say half of it again."""
        panel = self._panel(app=self._host())
        checks = {"ok": True, "problems": [], "warnings": [junban_gui.reposition.STALE_WARNING, "Other."],
                  "decks": ["TheBank"]}
        with mock.patch.object(junban_gui.reposition, "preflight", return_value=checks), \
             mock.patch.object(junban_gui.reposition, "dry_run", return_value=([], _real_stats())), \
             mock.patch.object(panel, "_is_list_current", return_value=False) as asked, \
             mock.patch.object(panel, "_context_counts", return_value={}):
            panel._preview_worker(panel._settings(), panel._scope_key(), ["analyzer.py", "--language=ja"])
        asked.assert_called_once_with(["analyzer.py", "--language=ja"], "ja")
        _tag, _stats, sent, _key = panel.q.get_nowait()
        self.assertIs(sent["list_current"], False)
        self.assertEqual(sent["warnings"], ["Other."])

    def test_the_preview_button_keeps_one_width_whatever_it_says(self):
        host = self._host()
        panel = self._panel(app=host)
        widths = {str(panel.btn_preview.cget("width"))}
        self._previewed(panel, checks=dict(_OK_CHECKS, list_current=False))
        widths.add(str(panel.btn_preview.cget("width")))
        panel.on_preview()
        widths.add(str(panel.btn_preview.cget("width")))
        self.assertEqual(len(widths), 1)


# --------------------------------------------------------------------------- #
# §17 — "i+1 first": a box on the Order row, off by default, part of what the preview confirms
# --------------------------------------------------------------------------- #
class TestReadyFirst(JunbanGuiTestCase):
    def test_it_starts_off_and_a_saved_choice_is_what_the_panel_opens_on(self):
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS))):
            panel = self._panel()
        self.assertIs(panel.ready_first.get(), False)
        with mock.patch.object(junban_gui.JunbanGui, "_saved_settings",
                               staticmethod(lambda: dict(_DEFAULTS, junban_ready_first=True))):
            panel = self._panel()
        self.assertIs(panel.ready_first.get(), True)

    def test_it_changes_the_order_so_it_throws_the_preview_away_and_reaches_the_engine_and_the_file(self):
        saved = {}
        loaded = dict(_DEFAULTS, junban_chunk_size=150, target_language="ja")
        with mock.patch("app.settings_manager.load_settings", return_value=loaded), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            self._previewed(panel)
            before = panel._scope_key()
            panel.ready_first.set(True)
            # Read BEFORE the save: the mocked save writes into the very dict the panel loads.
            self.assertIs(panel._settings()["junban_ready_first"], True, "the engine is handed the box")
            panel._on_scope_changed()
        self.assertNotEqual(panel._scope_key(), before)
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertIs(saved["junban_ready_first"], True)

    def test_the_preview_says_what_it_moved(self):
        """So a card that jumped ahead, or one that waits, is expected rather than surprising."""
        stats = dict(_real_stats(), ready_first={"pulled": 2, "held": 13})
        panel = self._previewed(self._panel(), stats)
        self.assertIn("i+1 first: 2 brought right before the card that needs them · 13 wait for a word "
                      "their sentence needs.", self._messages(panel))
        quiet = self._previewed(self._panel(), dict(_real_stats(), ready_first={"pulled": 0, "held": 0}))
        self.assertNotIn("i+1 first", self._messages(quiet))


class TestYourCards(JunbanGuiTestCase):
    """P1.4-1 (Sonic, 2026-10-06: "give them the option to adjust the setting themselves"): with the Connect preview
    on, the window offers "My own cards have this tag" and "Order all cards by the list"; off, neither is there, and
    nothing of them is handed to the engine or saved."""

    def test_with_the_preview_off_the_row_is_not_there_and_nothing_of_it_is_saved(self):
        loaded = dict(_DEFAULTS, target_language="ja", junban_own_tag="immersion")
        with mock.patch("app.settings_manager.load_settings", return_value=loaded), \
             mock.patch("app.settings_manager.save_keys") as save_keys:
            panel = self._panel()
            panel._save_scope()
        self.assertIsNone(panel.own_tag)
        changes = save_keys.call_args[0][0]
        self.assertFalse({"junban_own_tag", "junban_order_all"} & set(changes), "the window never writes them")
        self.assertEqual(panel._own_values(), {})

    def test_with_the_preview_on_both_reach_the_engine_the_file_and_throw_the_preview_away(self):
        saved = {}
        loaded = dict(_DEFAULTS, target_language="ja", connect_enabled=True, junban_chunk_size=150)
        with mock.patch("app.settings_manager.load_settings", return_value=loaded), \
             mock.patch("app.settings_manager.save_settings", side_effect=saved.update):
            panel = self._panel()
            self.assertEqual((panel.own_tag.get(), panel.order_all.get()), ("", False))
            self._previewed(panel)
            before = panel._scope_key()
            panel.own_tag.set("  immersion ")
            panel.order_all.set(True)
            handed = panel._settings()
            self.assertEqual((handed["junban_own_tag"], handed["junban_order_all"]), ("immersion", True))
            panel._on_scope_changed()
        self.assertNotEqual(panel._scope_key(), before)
        self.assertEqual(self._state(panel.btn_reorder), "disabled")
        self.assertEqual((saved["junban_own_tag"], saved["junban_order_all"]), ("immersion", True))

    def test_the_preview_says_when_cards_come_back_from_being_set_aside(self):
        self.assertEqual(junban_gui.returning_clause({"returning": [1, 2]}),
                         " Back on your list: unsuspend 2 cards Junban had set aside.")
        self.assertEqual(junban_gui.JunbanGui._later_clause({"returning": [1]}),
                         " Back on your list: unsuspend 1 card Junban had set aside.")
        self.assertEqual(junban_gui.returning_clause({}), "")
