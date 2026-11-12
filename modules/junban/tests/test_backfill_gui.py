# SPDX-License-Identifier: GPL-3.0-or-later
"""The Anki Backfill window (`backfill_gui.py`): the guidelines it must satisfy, and its promises.

  * **Fill cannot be pressed without a preview of the choices on screen**, and any choice throws the
    preview away — the preview is the only confirmation (as 順's I5). A preview that comes back after
    a choice changed is never shown; the one for the new choices follows.
  * **One window**: a second click, from either door, brings the same window forward (the user,
    2026-09-24: "if it's open, it just gets refocused") — and the same for its Fields window.
  * **Plain** (the user, 2026-09-24: "a bit too dense"): one line under the title, "All" / "New only",
    a "?" that explains each line of the field, a one-line summary with the reasons behind an ⓘ, the
    note-type pickers behind the fill's button, no library-data line.
  * **Build & preview** only while there is nothing to fill from — and never started by itself.
  * **Rebuild from my library** (the user, 2026-10-01): the set built again in the background, by the button or by
    itself once the library has grown by a quarter — a quiet line, nothing waiting for it, a failure said once.
  * **No redraw per action**: a preview changes the fill's button text and the table, nothing else.
  * GUI_Design_Guidelines: Esc closes, every button and toggle has a tooltip, and the window never
    switches the host's ttk theme.

Nothing here reaches Anki: the engine is never called with a live transport, the conftest keeps the
opening probe from being armed (`SURASURA_NO_UI_TIMERS`) and declines every dialog. One Tk root per
file (`testing.md` §5.4).
"""
import os
import tkinter as tk
import unittest
from tkinter import ttk
from unittest import mock

import modules.junban as junban
from modules.junban import backfill, backfill_gui
from modules.junban.gui import BG, MUTED

LAPIS = ["Expression", "ExpressionReading", "Sentence", "Patterns", "Glossary"]
MIGAKU = ["Sentence", "Target Word", "Definitions"]
FIELD = '<div class="pat-particle pat-src-conversational">〜に 34% · 〜を 24%</div>' \
        '<div class="pat-form pat-src-conversational">探検する 19%</div>'


def _models(**extra):
    models = {"Lapis": {"fields": LAPIS, "count": 3, "mapped": {"patterns": "Patterns"}},
              "Migaku Japanese": {"fields": MIGAKU, "count": 2, "mapped": {"patterns": None}}}
    models.update(extra)
    return models


def _result(models=None, skipped=True):
    """A preview as `backfill.preview` returns it — 探検 filled, 大切 already filled, 話が弾む a phrase."""
    rows = [(1789712000000, "探検", "Patterns", "fill", FIELD, "patterns")]
    counts = {"fill": 1}
    if skipped:
        rows += [(1789712000001, "大切", "Patterns", "filled", "", "patterns"),
                 (1789712000002, "話が弾む", "Patterns", "phrase", "", "patterns")]
        counts.update(filled=1, phrase=1)
    return {"scope": {"models": _models() if models is None else models, "notes": []},
            "edits": {1789712000000: {"Patterns": {"before": "", "after": FIELD}}},
            "rows": rows, "counts": dict(counts), "by_fill": {"patterns": dict(counts)}}


SENTENCES = "彼は毎日<b>探検</b>に出かけます。<br><b>探検</b>の話を聞かせて。"


def _both():
    """パターン and 例文 ticked: 探検 gets both, 大切 only its sentences, 話が弾む nothing."""
    rows = [(1789712000000, "探検", "Patterns", "fill", FIELD, "patterns"),
            (1789712000000, "探検", "ExampleSentences", "fill", SENTENCES, "sentence"),
            (1789712000001, "大切", "Patterns", "filled", "", "patterns"),
            (1789712000001, "大切", "ExampleSentences", "fill", "<b>大切</b>な人。", "sentence"),
            (1789712000002, "話が弾む", "Patterns", "phrase", "", "patterns"),
            (1789712000002, "話が弾む", "ExampleSentences", "not easy", "", "sentence")]
    edits = {1789712000000: {"Patterns": {"before": "", "after": FIELD},
                             "ExampleSentences": {"before": "", "after": SENTENCES}},
             1789712000001: {"ExampleSentences": {"before": "", "after": "<b>大切</b>な人。"}}}
    by_fill = {"patterns": {"fill": 1, "filled": 1, "phrase": 1}, "sentence": {"fill": 2, "not easy": 1}}
    return {"scope": {"models": _models(), "notes": []}, "edits": edits, "rows": rows,
            "counts": {"fill": 3, "filled": 1, "phrase": 1, "not easy": 1}, "by_fill": by_fill}


class _Process:
    """`start_rebuild`'s Popen: its output lines, and an exit code — `on_exit` runs as it ends."""

    def __init__(self, lines, code=0, on_exit=None):
        self.stdout, self.code, self.on_exit = iter(lines), code, on_exit

    def wait(self):
        if self.on_exit:
            self.on_exit()
        return self.code


class _Session:
    def close(self):
        pass


class BackfillGuiTestCase(unittest.TestCase):
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

    def setUp(self):
        # Settings live in a dict for the test: nothing reaches the sandboxed settings.json either.
        self.saved = dict(junban.SETTINGS_DEFAULTS, target_language="ja")
        patcher = mock.patch("app.settings_manager.load_settings", side_effect=lambda: dict(self.saved))
        patcher.start()
        self.addCleanup(patcher.stop)
        saver = mock.patch("app.settings_manager.save_settings",
                           side_effect=lambda s: self.saved.update(s))
        saver.start()
        self.addCleanup(saver.stop)
        # The library's data is there unless a test says otherwise (the sandbox has none).
        self.ready = True
        data = mock.patch.object(backfill, "data_ready", side_effect=lambda language="ja": self.ready)
        data.start()
        self.addCleanup(data.stop)
        # A background build lives for the app's session: none is left over from another test.
        backfill._PROCESS = None
        backfill._BACKGROUND.clear()
        backfill._FAILED.clear()

    def _window(self, **kwargs):
        window = backfill_gui.BackfillGui(self.root, **kwargs)
        self.addCleanup(self._destroy, window)
        self.root.update_idletasks()
        return window

    @staticmethod
    def _destroy(window):
        # The window's `backfill-window` hold is let go as its own close does (it outlives the window otherwise:
        # its owner is a token, and every later take in this process — the Qt window's tests — met it held).
        with window._window_lock_guard:
            window._closing = True
            held, window._window_lock = window._window_lock, None
        if held is not None:
            held.release()
        try:
            window.destroy()
        except tk.TclError:
            pass

    @staticmethod
    def _walk(widget):
        for child in widget.winfo_children():
            yield child
            yield from BackfillGuiTestCase._walk(child)

    @staticmethod
    def _texts(tip):
        """What a HelpTip popup says, top to bottom."""
        return [w.cget("text") for w in BackfillGuiTestCase._walk(tip.tip) if isinstance(w, tk.Label)]

    @staticmethod
    def _inline(window):
        """Run the window's jobs on this thread, so the queue holds everything a job said when it ends."""
        def start(worker):
            window._settings_snapshot = window._settings()
            window._set_busy(True)
            window._guarded(worker)()
        window._start = start


class TestGuidelines(BackfillGuiTestCase):
    def test_escape_closes_the_window(self):
        # Shown and focused first, as in 順's test: a withdrawn window never receives the key.
        window = self._window()
        self.assertTrue(window.bind("<Escape>"), "no Escape binding")
        window.deiconify()
        window.update()
        window.focus_force()
        window.event_generate("<Escape>", when="now")
        self.root.update()
        self.assertFalse(window.winfo_exists())

    def test_escape_closes_the_fields_window_and_leaves_the_backfill_window_open(self):
        window = self._window()
        window._show_preview(_result(), window._key())
        window.on_fields(backfill.FILLS[0])
        dialog = window._fields_dialog
        dialog.update()
        dialog.focus_force()
        dialog.event_generate("<Escape>", when="now")
        self.root.update()
        self.assertFalse(dialog.winfo_exists())
        self.assertTrue(window.winfo_exists())

    def test_every_button_toggle_picker_and_help_mark_explains_itself(self):
        window = self._window()
        window._show_preview(_result(), window._key())
        window.on_fields(backfill.FILLS[0])                 # its pickers count too
        self.root.update_idletasks()
        kinds = (ttk.Button, ttk.Checkbutton, ttk.Radiobutton, ttk.Combobox)
        widgets = list(self._walk(window))
        missing = [str(w) for w in widgets if isinstance(w, kinds) and not w.bind("<Enter>")]
        self.assertEqual(missing, [])
        marks = [w for w in widgets if isinstance(w, ttk.Label) and w.cget("style") == "JunHelp.TLabel"]
        self.assertEqual(sorted(str(w.cget("text")) for w in marks), ["?"] * len(backfill.FILLS) + ["ⓘ"])
        self.assertTrue(all(w.bind("<Enter>") for w in marks))

    def test_it_never_switches_the_hosts_theme(self):
        # ttk styles are process-global; a host on `clam` must still be on `clam` afterwards.
        style = ttk.Style(self.root)
        before = style.theme_use()
        style.theme_use("clam")
        try:
            self._window()
            self.assertEqual(style.theme_use(), "clam")
        finally:
            style.theme_use(before)


class TestOneWindow(BackfillGuiTestCase):
    def test_a_second_open_brings_the_same_window_forward(self):
        host = mock.Mock(spec=["root", "backfill_window", "var_language"])
        host.root = self.root
        host.backfill_window = None
        host.var_language.get.return_value = "ja"
        junban.open_backfill(host)
        first = host.backfill_window
        self.addCleanup(self._destroy, first)
        junban.open_backfill(host)
        self.assertIs(host.backfill_window, first)
        self.assertEqual(len([w for w in self.root.winfo_children()
                              if isinstance(w, backfill_gui.BackfillGui)]), 1)

    def test_the_fields_window_opens_once_too(self):
        window = self._window()
        window._show_preview(_result(), window._key())
        window.on_fields(backfill.FILLS[0])
        first = window._fields_dialog
        window.on_fields(backfill.FILLS[0])
        self.assertIs(window._fields_dialog, first)
        self.assertEqual(len([w for w in window.winfo_children()
                              if isinstance(w, backfill_gui.FieldsDialog)]), 1)


class TestPlain(BackfillGuiTestCase):
    def _labels(self, window):
        return [str(w.cget("text")) for w in self._walk(window) if isinstance(w, ttk.Label)]

    def test_one_line_under_the_title_and_no_library_data_line(self):
        # The user: the sub-header is "Fills fields from Surasura" "and that's it"; the library-data
        # line and its Rebuild link were "completely unnecessary". (A Rebuild button came back on
        # 2026-10-01, the user asking for one: its numbers are in its tooltip, never a line.)
        window = self._window()
        labels = self._labels(window)
        self.assertIn("Fills fields from Surasura.", labels)
        self.assertFalse([t for t in labels if "library" in t.lower() or "rebuild" in t.lower()])

    def test_the_cards_choice_reads_all_and_new_only_and_still_means_the_same(self):
        # "All but known" read as "all but your known cards". The label changed; the value did not.
        window = self._window()
        radios = [w for w in self._walk(window) if isinstance(w, ttk.Radiobutton)]
        self.assertEqual([(w.cget("text"), w.cget("value")) for w in radios],
                         [("All", "all"), ("New only", "new")])

    def test_the_summary_is_one_short_line_and_the_details_explain_it(self):
        window = self._window()
        window._show_preview(_result(), window._key())
        self.assertEqual(window.summary_var.get(), "Fill 1 note · 2 skipped")
        self.assertEqual(window.details.winfo_manager(), "pack")
        window.details_tip._show()
        try:
            texts = self._texts(window.details_tip)
        finally:
            window.details_tip._hide()
        self.assertIn("1 already filled", texts)
        self.assertIn("1 phrase", texts)                    # one phrase, not "1 phrases"
        self.assertIn(backfill.REASON_HELP["already filled"], texts)
        self.assertIsNone(window.details_tip.tip)

    def test_the_details_mark_is_there_only_when_it_has_something_to_say(self):
        window = self._window()
        window._show_preview(_result(skipped=False), window._key())
        self.assertEqual(window.summary_var.get(), "Fill 1 note")
        self.assertEqual(window.details.winfo_manager(), "")
        window.cards.set("new")
        window._on_choice()                                 # the preview goes, and its ⓘ with it
        self.assertEqual(window.details.winfo_manager(), "")

    def test_the_question_mark_explains_each_line_of_the_field(self):
        window = self._window()
        tip = window.help_tips["patterns"]
        tip._show()
        try:
            texts = self._texts(tip)
        finally:
            tip._hide()
        for header in ("Particles", "Forms", "Word pairs", "Frames", "書き言葉"):
            self.assertIn(header, texts)
        self.assertIn("囲む → 囲まれる 62%   (to be surrounded)", texts)

    def test_the_small_buttons_have_room_around_their_text(self):
        # "The copy card style needs padding on the text. Looks cramped."
        window = self._window()
        copy = [w for w in self._walk(window) if isinstance(w, ttk.Button)
                and w.cget("text") == "Copy card style"][0]
        self.assertEqual(str(copy.cget("style")), "JunSmall.TButton")
        value = ttk.Style(window).lookup("JunSmall.TButton", "padding")     # Tcl objects, or a string
        parts = value if isinstance(value, (tuple, list)) else str(value).split()
        self.assertGreaterEqual(int(float(str(parts[0]))), 10)


class TestFieldsWindow(BackfillGuiTestCase):
    def test_the_fill_button_says_where_it_goes(self):
        window = self._window()
        target = window._targets["patterns"]
        # Before a preview there are no note types to choose between.
        self.assertEqual((target.cget("text"), str(target["state"])), ("Fields…", tk.DISABLED))
        window._show_preview(_result(), window._key())
        self.assertEqual((target.cget("text"), str(target["state"])), ("Lapis → Patterns", tk.NORMAL))
        kiku = _models(Kiku={"fields": ["Word", "パターン"], "count": 1, "mapped": {"patterns": "パターン"}})
        window._show_preview(_result(kiku), window._key())
        self.assertEqual(target.cget("text"), "2 note types")
        none = {"Migaku Japanese": _models()["Migaku Japanese"]}
        window._show_preview(dict(_result(none), rows=[], counts={}, edits={}), window._key())
        self.assertEqual(target.cget("text"), "Choose a field…")
        self.assertEqual(window.summary_var.get(), "Choose a field for these cards.")

    def test_the_note_types_it_fills_come_first_and_each_choice_is_saved(self):
        window = self._window()
        window._show_preview(_result(), window._key())
        window.on_fields(backfill.FILLS[0])
        dialog = window._fields_dialog
        self.assertEqual(list(dialog.vars), ["Lapis", "Migaku Japanese"])
        self.assertEqual(dialog.vars["Migaku Japanese"].get(), backfill_gui.SKIP_LABEL)
        boxes = {str(w.cget("textvariable")): w for w in self._walk(dialog) if isinstance(w, ttk.Combobox)}
        box = boxes[str(dialog.vars["Migaku Japanese"])]
        dialog.vars["Migaku Japanese"].set("Definitions")
        box.event_generate("<<ComboboxSelected>>")
        self.assertEqual(self.saved["junban_backfill_fields"], {"patterns": {"Migaku Japanese": "Definitions"}})
        self.assertEqual(window._targets["patterns"].cget("text"), "2 note types")
        dialog.vars["Migaku Japanese"].set(backfill_gui.SKIP_LABEL)
        box.event_generate("<<ComboboxSelected>>")
        self.assertEqual(self.saved["junban_backfill_fields"]["patterns"]["Migaku Japanese"], backfill.SKIP)
        self.assertEqual(window._targets["patterns"].cget("text"), "Lapis → Patterns")


class TestPreviewIsTheConfirmation(BackfillGuiTestCase):
    def test_fill_waits_for_a_preview_of_the_current_choices(self):
        window = self._window()
        self.assertEqual(str(window.btn_fill["state"]), tk.DISABLED)
        window._show_preview(_result(), window._key())
        self.assertEqual(str(window.btn_fill["state"]), tk.NORMAL)
        # Any choice throws the preview away.
        window.cards.set("new")
        window._on_choice()
        self.assertEqual(str(window.btn_fill["state"]), tk.DISABLED)
        self.assertEqual(window.tree.get_children(), ())

    def test_the_preview_lists_the_writes_first_and_says_why_the_rest_wait(self):
        window = self._window()
        window._show_preview(_result(), window._key())
        rows = [window.tree.item(i, "values") for i in window.tree.get_children()]
        self.assertEqual(rows[0], ("探検", "パターン", "fill", "〜に 34% · 〜を 24% / 探検する 19%"))
        self.assertEqual({r[2] for r in rows[1:]}, {"already filled", "phrases"})

    def test_with_two_fills_each_row_names_its_fill_and_the_summary_counts_notes(self):
        # Two sentences read as two lines on the card; in the table, one row: "… / …".
        self.saved["junban_backfill_fills"] = ["patterns", "sentence"]
        window = self._window()
        window._show_preview(_both(), window._key())
        rows = [window.tree.item(i, "values") for i in window.tree.get_children()]
        self.assertIn(("探検", "例文", "fill", "彼は毎日探検に出かけます。 / 探検の話を聞かせて。"), rows)
        self.assertEqual(window.summary_var.get(), "Fill 2 notes · 1 skipped")
        window.details_tip._show()
        try:
            texts = self._texts(window.details_tip)
        finally:
            window.details_tip._hide()
        # Under each fill's name: its own count, then its reasons.
        self.assertEqual(texts[:2], ["パターン", "1 to fill · 2 skipped"])
        self.assertIn("例文", texts)
        self.assertIn("1 none easy", texts)

    def test_a_preview_that_comes_back_after_a_choice_changed_is_not_shown(self):
        # It describes other cards. Shown with Fill off it would still be a confirmation of the wrong
        # thing on screen; the preview of the new choices follows instead.
        window = self._window()
        key = window._key()
        window.cards.set("new")
        window._on_choice()
        window._show_preview(_result(), key)
        self.assertEqual(window.tree.get_children(), ())
        self.assertEqual(window.summary_var.get(), "")
        self.assertEqual(str(window.btn_fill["state"]), tk.DISABLED)

    def test_a_preview_of_the_other_language_is_not_a_confirmation(self):
        # The dashboard's language can change under an open window without any choice here — only
        # the preview's key tells Fill that what is on screen describes the other language's cards.
        window = self._window()
        window._show_preview(_result(), window._key())
        self.saved["target_language"] = "zh"
        window._sync_buttons()
        self.assertEqual(str(window.btn_fill["state"]), tk.DISABLED)

    def test_a_preview_with_nothing_to_write_keeps_fill_off(self):
        window = self._window()
        window._show_preview(dict(_result(), edits={}), window._key())
        self.assertEqual(str(window.btn_fill["state"]), tk.DISABLED)

    def test_choices_are_saved_as_fresh_containers(self):
        window = self._window()
        window.replace.set(True)
        window._on_choice()
        self.assertIs(self.saved["junban_backfill_replace"], True)
        self.assertIsNot(self.saved["junban_backfill_fills"], junban.SETTINGS_DEFAULTS["junban_backfill_fills"])
        self.assertIsNot(self.saved["junban_backfill_fields"], junban.SETTINGS_DEFAULTS["junban_backfill_fields"])
        self.assertEqual(junban.SETTINGS_DEFAULTS["junban_backfill_fields"], {})


class TestTheLatestChoicesWin(BackfillGuiTestCase):
    def _connected(self):
        window = self._window()
        window._connected = True
        window._start = mock.Mock()
        return window

    def test_a_choice_while_idle_previews_at_once(self):
        window = self._connected()
        window.cards.set("new")
        window._on_choice()
        window._start.assert_called_once()

    def test_a_choice_made_while_a_job_runs_is_previewed_when_it_ends(self):
        window = self._connected()
        window.busy = True
        window.cards.set("new")
        window._on_choice()
        window._start.assert_not_called()
        window.q.put(("__DONE__",))
        window._drain_once()
        window._start.assert_called_once()

    def test_nothing_is_previewed_by_itself_while_anki_is_not_connected(self):
        window = self._connected()
        window._connected = False
        window.cards.set("new")
        window._on_choice()
        window.q.put(("__DONE__",))
        window._drain_once()
        window._start.assert_not_called()

    def test_the_fill_report_stays_when_the_next_preview_starts(self):
        window = self._connected()
        window._show_report({"ok": True, "message": "Filled 97 notes.", "problems": []})
        window._preview_now()
        self.assertIn("Filled 97 notes.", window.messages.get("1.0", "end"))


class TestBuildAndPreview(BackfillGuiTestCase):
    def test_with_nothing_to_fill_from_the_button_offers_to_build(self):
        self.ready = False
        window = self._window()
        self.assertEqual(window.btn_preview.cget("text"), "Build & preview")
        self.assertIn("about a minute", window.preview_tip.text)
        self.ready = True
        window._sync_buttons()
        self.assertEqual(window.btn_preview.cget("text"), "Preview")

    def test_the_build_never_starts_by_itself(self):
        # A minute of a laptop's time: only on the button.
        self.ready = False
        window = self._window()
        window._connected = True
        window._start = mock.Mock()
        window.cards.set("new")
        window._on_choice()
        window._start.assert_not_called()

    def test_build_and_preview_builds_then_previews_by_itself(self):
        self.ready = False
        window = self._window()
        window._connected = True
        self._inline(window)
        built = _Process(["PROGRESS 1/2\n", "PROGRESS 2/2\n", "wrote patterns_ja.db\n"],
                         on_exit=lambda: setattr(self, "ready", True))
        with mock.patch.object(backfill, "start_rebuild", return_value=built), \
                mock.patch.object(backfill, "Session", return_value=_Session()), \
                mock.patch.object(backfill, "preview", return_value=_result()) as previewed:
            window.on_preview()
            window._drain_once()
        previewed.assert_called_once()
        self.assertEqual(window.summary_var.get(), "Fill 1 note · 2 skipped")
        self.assertEqual(window.btn_preview.cget("text"), "Preview")
        self.assertFalse(window.busy)

    def test_a_failed_build_says_why_and_previews_nothing(self):
        self.ready = False
        window = self._window()
        window._connected = True
        self._inline(window)
        failed = _Process(["PROGRESS 1/2\n", "RuntimeError: no content files\n"], code=1)
        with mock.patch.object(backfill, "start_rebuild", return_value=failed), \
                mock.patch.object(backfill, "preview") as previewed:
            window.on_preview()
            window._drain_once()
        previewed.assert_not_called()
        self.assertIn("RuntimeError: no content files", window.messages.get("1.0", "end"))
        self.assertEqual(window.btn_preview.cget("text"), "Build & preview")


class TestGetData(BackfillGuiTestCase):
    """"Get data…" — Surasura's shared パターン data (a download) or the user's own (a package from their
    other computer, Patterns_Spec §18). Nothing here goes online: the installer is replaced."""

    def setUp(self):
        super().setUp()
        self.general = False
        general = mock.patch.object(backfill, "general_ready", side_effect=lambda language="ja": self.general)
        general.start()
        self.addCleanup(general.stop)

    def test_it_is_offered_only_while_no_general_database_is_here(self):
        window = self._window()
        self.assertEqual(window.btn_get_data.winfo_manager(), "pack")
        self.general = True
        window._sync_buttons()
        self.assertEqual(window.btn_get_data.winfo_manager(), "")

    def test_its_window_opens_once_explains_itself_and_closes_on_escape(self):
        window = self._window()
        window.on_get_data()
        first = window._data_dialog
        window.on_get_data()
        self.assertIs(window._data_dialog, first)
        buttons = [w for w in self._walk(first) if isinstance(w, ttk.Button)]
        self.assertEqual([b.cget("text") for b in buttons], ["Download", "Import a file…", "Close"])
        self.assertTrue(all(b.bind("<Enter>") for b in buttons))
        first.update()
        first.focus_force()
        first.event_generate("<Escape>", when="now")
        self.root.update()
        self.assertFalse(first.winfo_exists())

    def test_importing_a_package_installs_it_and_the_preview_follows(self):
        window = self._window()
        self._inline(window)
        window._connected = True
        session = mock.Mock()
        window._session = session
        open_during_install = []

        def install(path, progress=None):
            open_during_install.append(window._session is not None or not session.close.called)
            return ["patterns_ja_conversational.db", "patterns_ja_balanced.db"]
        with mock.patch.object(backfill_gui.filedialog, "askopenfilename",
                               return_value="C:/Users/me/Desktop/Surasura-patterns-personal.zip"), \
                mock.patch("modules.junban.patterns_package.install", side_effect=install) as installed, \
                mock.patch.object(backfill, "Session", return_value=_Session()), \
                mock.patch.object(backfill, "preview", return_value=_result()) as previewed:
            window.on_import()
            window._drain_once()
        self.assertEqual(open_during_install, [False])   # closed first: Windows won't replace an open database
        self.assertEqual(installed.call_args[0][0], "C:/Users/me/Desktop/Surasura-patterns-personal.zip")
        self.assertIn("Installed: patterns_ja_conversational.db, patterns_ja_balanced.db.",
                      window.messages.get("1.0", "end"))
        previewed.assert_called_once()           # the preview it was for
        self.assertEqual(window.summary_var.get(), "Fill 1 note · 2 skipped")

    def test_a_failed_download_says_why_and_nothing_follows(self):
        from modules.junban.patterns_package import PackageError
        window = self._window()
        self._inline(window)
        window._connected = True
        with mock.patch("modules.junban.patterns_package.get_shared",
                        side_effect=PackageError("Could not download the パターン data (offline).")), \
                mock.patch.object(backfill, "preview") as previewed:
            window.on_download()
            window._drain_once()
        self.assertIn("Could not download the パターン data (offline).", window.messages.get("1.0", "end"))
        previewed.assert_not_called()
        self.assertFalse(window.busy)

    def test_an_import_cancelled_in_the_file_picker_does_nothing(self):
        window = self._window()
        window._start = mock.Mock()
        with mock.patch.object(backfill_gui.filedialog, "askopenfilename", return_value=""):
            window.on_import()
        window._start.assert_not_called()


class TestRebuildFromMyLibrary(BackfillGuiTestCase):
    """The library's パターン set built again in the background — by the button, or by itself on opening once the
    library has grown by a quarter (the user, 2026-10-01: "so it doesn't hold the generate or anything hostage").
    The engine is replaced: `self.running` is a build in progress, `self.progress` its files done / in all."""

    def setUp(self):
        super().setUp()
        self.running, self.progress, self.started = False, (0, 0), []

        def start(language, reinforce=False, when_grown=False):
            self.started.append((language, reinforce, when_grown))
            self.running = True
            return True
        for name, fake in (("rebuild_in_background", start), ("building", lambda: self.running),
                           ("background", lambda: ("ja", *self.progress) if self.running else None)):
            patcher = mock.patch.object(backfill, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_button_is_there_only_while_there_is_a_set_to_rebuild(self):
        self.ready = False
        window = self._window()
        self.assertEqual(window.btn_rebuild.winfo_manager(), "")       # "Build & preview" builds the first one
        self.ready = True
        window._sync_buttons()
        self.assertEqual((window.btn_rebuild.winfo_manager(), window.btn_rebuild.cget("text"),
                          str(window.btn_rebuild.cget("style"))), ("pack", "Rebuild from my library", "JunSmall.TButton"))

    def test_its_tooltip_reads_the_numbers_for_the_language_on_screen_on_each_hover(self):
        window = self._window()
        with mock.patch.object(backfill, "rebuild_tip",
                               side_effect=lambda language: f"Built 2026-09-30 ({language})") as tip:
            window.rebuild_tip._show()
            try:
                texts = [w.cget("text") for w in self._walk(window.rebuild_tip.tip) if isinstance(w, tk.Label)]
            finally:
                window.rebuild_tip._hide()
            self.saved["target_language"] = "zh"
            window.rebuild_tip._show()
            window.rebuild_tip._hide()
        self.assertEqual(texts, ["Built 2026-09-30 (ja)"])
        self.assertEqual([c.args[0] for c in tip.call_args_list], ["ja", "zh"])

    def test_pressing_it_builds_in_the_background_and_nothing_waits_for_it(self):
        window = self._window()
        window._show_preview(_result(), window._key())
        window.on_rebuild()
        self.assertEqual(self.started, [("ja", False, False)])
        self.assertEqual(window.build_var.get(), "Updating your library's パターン in the background…")
        self.progress = (120, 1987)
        window._drain_once()
        self.assertEqual(window.build_var.get(), "Updating your library's パターン in the background… 120 / 1,987 files")
        # Preview and Fill stay live — the preview on screen is still the confirmation — and the button is off.
        self.assertEqual((str(window.btn_preview["state"]), str(window.btn_fill["state"]),
                          str(window.btn_rebuild["state"])), (tk.NORMAL, tk.NORMAL, tk.DISABLED))
        window.on_rebuild()
        self.assertEqual(len(self.started), 1)                          # never two at once

    def test_opening_the_window_asks_for_one_only_while_patterns_are_filled(self):
        window = self._window()
        self.assertEqual(self.started, [])                              # scheduled, never under test (a timer)
        window._rebuild_if_grown()
        self.assertEqual(self.started, [("ja", False, True)])           # when_grown: the engine measures
        self.saved["junban_backfill_fills"] = ["sentence"]              # 例文 reads the library itself
        self.started.clear()
        self._window()._rebuild_if_grown()
        self.assertEqual(self.started, [])

    def test_when_it_ends_the_old_set_goes_at_the_first_idle_moment(self):
        # Windows will not replace a database a reader holds: the window's session lets the old set go, but never
        # under a preview that is reading it.
        window = self._window()
        session = mock.Mock()
        window._session = session
        window.on_rebuild()
        staged = backfill.staged_path("ja")
        self.assertTrue(staged.startswith(os.environ["SURASURA_TEST_ROOT"]), staged)    # the sandbox, never %APPDATA%
        with open(staged, "wb"):
            pass
        window.busy = True
        self.running = False
        with mock.patch.object(backfill, "promote") as promoted:
            window._drain_once()
            self.assertEqual(window.build_var.get(), "")
            session.close.assert_not_called()
            promoted.assert_not_called()
            window.q.put(("__DONE__",))
            window._drain_once()
        session.close.assert_called_once()
        promoted.assert_called_once_with("ja")
        self.assertIsNone(window._session)
        self.assertEqual(str(window.btn_rebuild["state"]), tk.NORMAL)

    def test_a_failed_build_is_said_once(self):
        window = self._window()
        backfill._FAILED["ja"] = "Error: the パターン build failed (disk full). The previous database is unchanged."
        window._drain_once()
        window._drain_once()
        text = window.messages.get("1.0", "end")
        self.assertEqual(text.count("could not be updated"), 1)
        self.assertIn("Backfill keeps using the one it has.", text)

    def test_build_and_preview_waits_for_a_build_already_running(self):
        self.ready = False
        window = self._window()
        window._connected = True
        self._inline(window)
        with mock.patch.object(backfill, "start_rebuild", return_value=None), \
                mock.patch.object(backfill, "preview") as previewed:
            window.on_preview()
            window._drain_once()
        previewed.assert_not_called()
        self.assertIn("being built in the background", window.messages.get("1.0", "end"))
        self.assertFalse(window.busy)

    def test_its_line_is_in_the_palette_and_escape_still_closes_while_it_builds(self):
        window = self._window()
        window.on_rebuild()
        line = [w for w in self._walk(window) if isinstance(w, ttk.Label)
                and str(w.cget("textvariable")) == str(window.build_var)][0]
        self.assertEqual(str(line.cget("style")), "JunMuted.TLabel")
        style = ttk.Style(window)
        self.assertEqual((style.lookup("JunMuted.TLabel", "background"), style.lookup("JunMuted.TLabel", "foreground")),
                         (BG, MUTED))
        window.deiconify()
        window.update()
        window.focus_force()
        window.event_generate("<Escape>", when="now")
        self.root.update()
        self.assertFalse(window.winfo_exists())
        self.assertTrue(self.running)                                   # the build goes on; the window is gone


class TestShowsItsWork(BackfillGuiTestCase):
    def test_the_bar_moves_while_busy_and_fills_once_a_job_counts(self):
        # The user, 2026-09-24: "some sort of visible 'thinking' while it runs" — the 例文 pass takes
        # seconds. Busy: the bar moves; a counted step fills it; done: empty and still.
        window = self._window()
        window._set_busy(True)
        self.assertEqual(str(window.progress["mode"]), "indeterminate")
        window._status("Reading your library: 900 / 1,987 files…")
        window._drain_once()
        self.assertEqual(window.summary_var.get(), "Reading your library: 900 / 1,987 files…")
        self.assertEqual((str(window.progress["mode"]), float(window.progress["value"]),
                          float(window.progress["maximum"])), ("determinate", 900.0, 1987.0))
        window.q.put(("__DONE__",))
        window._drain_once()
        self.assertEqual((str(window.progress["mode"]), float(window.progress["value"])), ("determinate", 0.0))


class TestNoRedrawPerAction(BackfillGuiTestCase):
    def test_a_preview_changes_the_fill_buttons_text_and_the_table_nothing_else(self):
        window = self._window()
        before = {str(w) for w in self._walk(window)}
        window._show_preview(_result(), window._key())
        kiku = _models(Kiku={"fields": ["Word", "パターン"], "count": 1, "mapped": {"patterns": "パターン"}})
        window._show_preview(_result(kiku), window._key())
        self.assertEqual({str(w) for w in self._walk(window)}, before)


class TestSmallThings(BackfillGuiTestCase):
    def test_copy_card_style_puts_the_css_on_the_clipboard(self):
        # The calls are recorded, never made: the clipboard is the user's (the tests' hidden desktop shares it), and
        # side-by-side runs would share it too.
        window = self._window()
        copied = []
        with mock.patch.object(window, "clipboard_clear", copied.clear), \
             mock.patch.object(window, "clipboard_append", copied.append):
            window.on_copy_style()
        self.assertEqual("".join(copied), backfill_gui.CARD_STYLE)
        self.assertIn(".pat-colloc", backfill_gui.CARD_STYLE)

    def test_the_fill_is_on_for_chinese_and_reaches_only_chinese_note_types(self):
        # WP-Z9 — JU-2's planned edit: Chinese is offered the fill (it was off until 2026-09-25); which
        # note types it reaches is test_side_by_side.py's matrix.
        self.saved["target_language"] = "zh"
        window = self._window()
        check = [w for w in self._walk(window) if isinstance(w, ttk.Checkbutton)
                 and w.cget("text") == backfill.FILLS[0].label][0]
        self.assertNotIn("disabled", check.state())
        window._show_preview(_result(), window._key())
        self.assertEqual(str(window._targets["patterns"]["state"]), tk.NORMAL)

    def test_restore_with_nothing_filled_says_so_and_asks_nothing(self):
        window = self._window()
        with mock.patch.object(backfill_gui.junban_gui, "ask") as asked:
            window.on_restore()
        asked.assert_not_called()
        self.assertIn("Nothing has been filled yet.", window.messages.get("1.0", "end"))


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()
