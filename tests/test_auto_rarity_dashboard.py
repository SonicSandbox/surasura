"""Automatic rarity on the main window (Auto_Generate_And_Rarity_Scope §2.4-2.6: D2, D3, I2).

A real, withdrawn dashboard, built the way tests/test_flag_ui.py builds it. The lock has to be a real
tk.Scale: Tk ignores set() on a disabled Scale — the trap the lock has to get right, and a mock would
fake it. On screen Tk also calls the slider's command for a programmatic set(); a withdrawn Scale never
redraws, so it doesn't here, and test_the_slider_callback_does_nothing_while_it_is_locked calls it
directly instead. conftest's sandbox (SURASURA_TEST_ROOT) holds the settings.json each test starts
from, so nothing real is read or written.
"""
import json
import os
import sys
import threading
import unittest
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import settings_manager, word_selection


def _ladder(*counts):
    """Band previews holding these word counts, Core -> Native, as the preview worker hands them over."""
    return {b: {"band": b, "word_count": n, "coverage_percent": 50.0 + i * 7, "floor_ppm": 0.0,
                "hours_between": None}
            for i, (b, n) in enumerate(zip(word_selection.BANDS_ORDER, counts))}


# The user's Japanese library as measured on 2026-09-28: at 850 words the automatic band is Uncommon
# (756); the user's own pick is Very Rare (4,541 words).
MEASURED_LIBRARY = _ladder(0, 5, 193, 756, 2_474, 4_541, 9_978)
# A few weeks of learning later: Rare is down to 840, so the automatic band moves on to Rare.
AFTER_LEARNING = _ladder(0, 4, 150, 598, 840, 4_020, 9_310)
# A Chinese library of its own, in its own store: at 850 words its automatic band is Rare (830).
CHINESE_LIBRARY = _ladder(3, 40, 260, 610, 830, 2_950, 7_400)
INDEX = {band: i for i, band in enumerate(word_selection.BANDS_ORDER)}


class _Dashboard(unittest.TestCase):
    AUTO = True   # the settings.json each test starts from: automatic rarity on/off, your band Very Rare
    SELECTION = {}   # anything else in its selection block

    def setUp(self):
        from app.main import MasterDashboardApp
        self.settings_path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump({"logic": {"selection": {"band": "very_rare", "auto": self.AUTO, **self.SELECTION}}}, f)
        self._threads_before = set(threading.enumerate())
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = MasterDashboardApp(self.root)
        # Every write to your band, whatever makes it: the slider, a trace, a preview landing.
        self.band_writes = []
        self.app.var_band.trace_add("write", lambda *a: self.band_writes.append(self.app.var_band.get()))

    def tearDown(self):
        self.root.destroy()
        # The window starts its preview on worker threads, and they open the token store. Let them
        # finish while conftest's sandbox (and its store path) is still in place: a straggler reaching
        # for the store after the test would find the real one.
        for thread in set(threading.enumerate()) - self._threads_before:
            thread.join(timeout=10)

    def _preview_lands(self, previews=MEASURED_LIBRARY):
        """A preview refresh finishing, as the worker hands it over. A newer generation, so a refresh
        still in flight from the window's own startup can't land on top of it."""
        self.app._preview_gen += 1
        self.app._apply_preview_result(self.app._preview_gen, previews)
        self.root.update()   # the window's pending work and GUI queue, as after a real refresh

    def _saved_selection(self):
        with open(self.settings_path, encoding="utf-8") as f:
            return json.load(f)["logic"]["selection"]


class TestTheLockedSlider(_Dashboard):
    AUTO = True

    def test_before_any_preview_the_locked_slider_reads_auto(self):
        """No Generate yet, so no numbers: the band name reads "Auto" and the line keeps its hint —
        but the slider is locked already, so it can't be dragged in the meantime."""
        self.app._preview_gen += 1
        self.app._apply_preview_result(self.app._preview_gen, None)
        self.assertEqual(str(self.app.band_slider.cget("state")), "disabled")
        self.assertEqual(self.app.var_band_name.get(), "Auto")
        self.assertEqual(self.app.var_band_coverage.get(), "Generate a journey once to see live estimates.")
        self.assertEqual(self.app.lbl_rarity.cget("text"), "Rarity (auto):")

    def test_the_locked_slider_sits_on_the_automatic_band_and_the_label_shows_it(self):
        """D2: greyed and locked ON the band (Uncommon, 756 words under 850), so "where am I between
        Core and Native" stays visible; the line shows that band's numbers."""
        self._preview_lands()
        self.assertEqual(str(self.app.band_slider.cget("state")), "disabled")
        self.assertEqual(int(self.app.band_slider.get()), INDEX["uncommon"])
        self.assertEqual(self.app.var_band_name.get(), "Uncommon")
        self.assertEqual(self.app.lbl_rarity.cget("text"), "Rarity (auto):")
        self.assertIn("756 words", self.app.var_band_coverage.get())
        self.assertEqual(str(self.app.band_slider.cget("sliderrelief")), "flat")   # greyed, not raised

    def test_a_preview_refresh_never_writes_your_band_or_saves(self):
        """I2: settings.json is in the run signature. If the automatic band were saved, every
        Generate would change it and turn the Generate button blue behind your back. The slider
        moves on to Rare as you learn — on screen only."""
        saves = []
        self.app.save_settings = lambda *a, **k: saves.append(k)
        self._preview_lands()
        self._preview_lands(AFTER_LEARNING)
        self.assertEqual(int(self.app.band_slider.get()), INDEX["rare"])
        self.assertEqual(self.app.var_band_name.get(), "Rare")
        self.assertEqual(self.band_writes, [])
        self.assertEqual(saves, [])
        self.assertEqual(self.app.var_band.get(), "very_rare")
        self.assertIsNone(getattr(self.app, "_band_save_after", None))

    def test_the_slider_callback_does_nothing_while_it_is_locked(self):
        """On screen, Tk calls _on_band_slide for a programmatic set() as well as a drag — so placing
        the slider on the automatic band calls it. While locked it must leave your band, the band
        name and the line alone."""
        self._preview_lands()
        line = self.app.var_band_coverage.get()
        self.app._on_band_slide("0")
        self.assertEqual(self.app.var_band.get(), "very_rare")
        self.assertEqual(self.app.var_band_name.get(), "Uncommon")
        self.assertEqual(self.app.var_band_coverage.get(), line)
        self.assertEqual(self.band_writes, [])

    def test_turning_it_off_unlocks_the_slider_on_the_band_it_chose(self):
        """D3: switched off, the slider unlocks where automatic rarity left it, and that band becomes
        yours — the list doesn't change the moment you switch it off. One save, nothing left pending."""
        self._preview_lands()
        self.app.var_auto_band.set(False)
        self.assertEqual(str(self.app.band_slider.cget("state")), "normal")
        self.assertEqual(int(self.app.band_slider.get()), INDEX["uncommon"])
        self.assertEqual(self.app.var_band.get(), "uncommon")
        self.assertEqual(self.app.var_band_name.get(), "Uncommon")
        self.assertEqual(self.app.lbl_rarity.cget("text"), "Rarity:")
        saved = self._saved_selection()
        self.assertIs(saved["auto"], False)
        self.assertEqual(saved["band"], "uncommon")
        self.assertIsNone(self.app._band_save_after)


class TestTurningItOn(_Dashboard):
    AUTO = False

    def test_turning_it_on_locks_the_slider_and_saves_the_switch_but_keeps_your_band(self):
        """The checkbox is saved inside the selection block — save_settings rebuilds settings.json
        from scratch, so a key it doesn't write is lost on the next save (CLAUDE.md §6). Your own band
        stays yours, for the day you switch it off."""
        self._preview_lands()
        self.assertEqual(int(self.app.band_slider.get()), INDEX["very_rare"])   # your band, unlocked
        self.assertEqual(str(self.app.band_slider.cget("state")), "normal")

        self.app.var_auto_band.set(True)
        self.root.update()
        self.assertEqual(str(self.app.band_slider.cget("state")), "disabled")
        self.assertEqual(int(self.app.band_slider.get()), INDEX["uncommon"])
        self.assertEqual(self.app.var_band_name.get(), "Uncommon")
        saved = self._saved_selection()
        self.assertIs(saved["auto"], True)
        self.assertEqual(saved["band"], "very_rare")
        self.assertEqual(settings_manager.load_settings()["logic"]["selection"]["auto_max_words"], 850)   # kept: the dashboard writes only its own keys (W1.3)
        self.assertEqual(self.band_writes, [])


class TestALanguageSwitch(_Dashboard):
    """The preview is per language: its numbers, and the band Automatic rarity locks the slider on,
    come from that language's store. A switch never refreshed it — the indexer does only when the new
    store has work to do — so after Japanese -> Chinese the locked slider kept showing Japanese's
    automatic band (I3), and turning Automatic rarity off then saved that band as yours (D3)."""
    AUTO = True

    def _switch_language(self, lang):
        """The Settings radio: the language changes, and the preview refresh it starts finishes — its
        worker thread, then the GUI queue the numbers come back through."""
        before = set(threading.enumerate())
        self.app.var_language.set(lang)
        for thread in set(threading.enumerate()) - before:
            thread.join(timeout=10)
        while not self.app.gui_queue.empty():
            task = self.app.gui_queue.get_nowait()
            if callable(task):
                task()
        self.root.update()

    def test_a_switch_locks_the_slider_on_the_new_languages_automatic_band(self):
        """Japanese sits on Uncommon (756); the Chinese store's own numbers put it on Rare (830). And
        turned off there, the band that becomes yours is Chinese's, the one on screen."""
        stores = {"ja": MEASURED_LIBRARY, "zh": CHINESE_LIBRARY}
        asked = []

        def compute(lang, sel, script="asis"):      # the worker's read, of that language's store
            asked.append(lang)
            return stores.get(lang)
        self.app._compute_band_previews = compute
        self._preview_lands()
        self.assertEqual(self.app.var_band_name.get(), "Uncommon")

        self._switch_language("zh")
        self.assertEqual(asked, ["zh"], "a switch recomputes the preview, for the new language")
        self.assertEqual(str(self.app.band_slider.cget("state")), "disabled")
        self.assertEqual(int(self.app.band_slider.get()), INDEX["rare"])
        self.assertEqual(self.app.var_band_name.get(), "Rare")
        self.assertIn("830 words", self.app.var_band_coverage.get())
        self.assertEqual(self.band_writes, [])       # I2: the switch shows the band, never saves it

        self.app.var_auto_band.set(False)           # D3, on the numbers now on screen
        self.assertEqual(self.app.var_band.get(), "rare")
        self.assertEqual(self._saved_selection()["band"], "rare")

    def test_a_switch_to_a_language_with_no_store_yet_reads_auto(self):
        """No Chinese Generate yet (the sandbox holds no Chinese store), so there are no Chinese
        numbers: "Auto" and the line's hint — never Japanese's band standing in for Chinese's."""
        self._preview_lands()
        self.assertEqual(self.app.var_band_name.get(), "Uncommon")
        self._switch_language("zh")
        self.assertEqual(str(self.app.band_slider.cget("state")), "disabled")
        self.assertEqual(self.app.var_band_name.get(), "Auto")
        self.assertEqual(self.app.var_band_coverage.get(), "Generate a journey once to see live estimates.")
        self.assertEqual(self.band_writes, [])


class TestALineThatIsNotANumber(_Dashboard):
    """auto_max_words is edited in settings.json only, so it can be anything — "850" in quotes, say.
    The analyzer can't compare its counts with that: it keeps your band and says so in the log."""
    AUTO = True
    SELECTION = {"auto_max_words": "850"}

    def setUp(self):
        import app.main as main_module
        real_tooltip, self.tips = main_module.ToolTip, {}

        def recording(widget, text, *args, **kwargs):     # {widget path: tooltip text}
            self.tips[str(widget)] = text
            return real_tooltip(widget, text, *args, **kwargs)
        patcher = patch.object(main_module, "ToolTip", recording)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_the_locked_slider_shows_your_band_as_generate_keeps_it(self):
        """The dashboard read the same failure as "no preview yet": "Auto" and "Generate a journey
        once…", beside a journey that had been generated — while Generate kept your band. It shows
        your band now, locked, the band Generate uses (I3); and saves nothing (I2)."""
        self._preview_lands()
        self.assertEqual(str(self.app.band_slider.cget("state")), "disabled")
        self.assertEqual(int(self.app.band_slider.get()), INDEX["very_rare"])
        self.assertEqual(self.app.var_band_name.get(), "Very Rare")
        self.assertIn("4,541 words", self.app.var_band_coverage.get())
        self.assertEqual(self.app.lbl_rarity.cget("text"), "Rarity (auto):")
        self.assertEqual(self.band_writes, [])

    def test_both_tooltips_say_the_line_without_raising(self):
        """The slider's and the checkbox's tooltips wrote the line with `:,`, which raises on a string
        (ValueError: Cannot specify ',' with 's'), so hovering either showed nothing."""
        self._preview_lands()
        self.app.create_settings_window()                # built withdrawn, as the app builds it

        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        [checkbox] = [w for w in widgets(self.app.settings_window)
                      if isinstance(w, ttk.Checkbutton) and w.cget("text") == "Automatic rarity"]
        for widget in (self.app.band_slider, checkbox):
            with self.subTest(tooltip=widget.winfo_class()):     # each on its own: one raising hid the other
                self.assertIn("the rarest band with 850 words or fewer", self.tips[str(widget)]())


if __name__ == '__main__':
    unittest.main()
