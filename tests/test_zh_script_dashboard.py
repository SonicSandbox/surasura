"""WP-Z3: the dashboard side of the Chinese `zh_script` setting.

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md (§5.4, gotchas 1 and 4).

- The Script row lives beside "Reinforce Chinese Seg" and, like it, shows only for Chinese. Unlike
  it, switching to Japanese must NOT reset the value: the setting belongs to the Chinese library.
- save_settings rebuilds settings.json from scratch, so an unlisted key silently vanishes (gotcha 1).
- The analyzer gets `--zh-script` only when a script is chosen: an as-is run passes exactly the old
  arguments.
- A script switch changes nothing the stat-only re-index check can see, so the dashboard compares
  the store's build signature too (gotcha 4). Without it the band preview stays in the old script.

Real Tk root, built per test like tests/test_flag_ui.py, inside conftest's sandboxed data root.
"""

import json
import os
import unittest
import tkinter as tk
from unittest.mock import patch


def _settings_on_disk():
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), encoding="utf-8") as f:
        return json.load(f)


class TestZhScriptDashboard(unittest.TestCase):
    def setUp(self):
        from app.main import MasterDashboardApp
        self.root = tk.Tk()
        self.root.withdraw()
        # The dashboard checks GitHub for updates on a background thread; nothing here needs it.
        with patch.object(MasterDashboardApp, "check_updates_thread"):
            self.app = MasterDashboardApp(self.root)
        self.app.create_settings_window()

    def tearDown(self):
        self.root.destroy()

    def _row_shown(self):
        return self.app.zh_script_frame.winfo_manager() == "pack"

    def test_script_row_shows_only_for_chinese_and_keeps_its_value(self):
        self.app.var_language.set("ja")
        self.assertFalse(self._row_shown())

        self.app.var_language.set("zh")
        self.assertTrue(self._row_shown())
        self.assertEqual(self.app.zh_script_frame.master, self.app.lang_options_frame)

        self.app.var_zh_script.set("t")
        self.app.save_settings()
        self.app.var_language.set("ja")
        self.assertFalse(self._row_shown())
        self.assertEqual(self.app.var_zh_script.get(), "t", "a trip to Japanese must not reset it")
        self.assertEqual(_settings_on_disk()["zh_script"], "t")

    def test_choosing_from_the_combobox_saves_the_setting(self):
        self.app.var_language.set("zh")
        combo = [w for w in self.app.zh_script_frame.winfo_children()
                 if w.winfo_class() == "TCombobox"][0]
        combo.set(self.app.ZH_SCRIPT_LABELS["s"])
        combo.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(self.app.var_zh_script.get(), "s")
        self.assertEqual(_settings_on_disk()["zh_script"], "s")

    def test_an_unknown_saved_value_loads_as_as_is(self):
        """A hand-edited settings.json must not leave the combobox on a value it can't show."""
        with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"target_language": "zh", "zh_script": "tw"}, f)
        self.app.load_settings()
        self.assertEqual(self.app.var_zh_script.get(), "asis")

    def _analyzer_args(self):
        with patch.object(self.app, "_try_open_existing_report", return_value=False), \
             patch.object(self.app, "run_command_async") as run:
            self.app.run_analyzer()
        return run.call_args[0][0]

    def test_analyzer_gets_the_flag_only_when_a_script_is_chosen(self):
        self.app.var_language.set("zh")
        self.app.var_zh_script.set("asis")
        self.assertFalse(any(a.startswith("--zh-script") for a in self._analyzer_args()))
        self.app.var_zh_script.set("t")
        self.assertIn("--zh-script=t", self._analyzer_args())
        # The setting is Chinese-only: a Japanese run never carries it.
        self.app.var_language.set("ja")
        self.assertFalse(any(a.startswith("--zh-script") for a in self._analyzer_args()))

    def test_a_script_switch_alone_relaunches_the_indexer(self):
        """Nothing on disk changed, so needs_reconcile says no — only the build signature notices."""
        from app import token_index
        self.app.var_language.set("zh")
        store = token_index.open_store("zh")
        try:
            store.reconcile([], lambda path: {"sentences": [], "counts": {}},
                            build_signature=token_index.build_signature("zh", False, "asis"))
            # A fresh known cache too, so the ONLY difference is the script.
            known = os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "zh", "KnownWord.json")
            store.set_cached_known(token_index.known_signature(known), set(), set())
        finally:
            store.close()

        def launches():
            self.app._indexer_busy = False
            with patch.dict(os.environ, {"SURASURA_NO_AUTOINDEX": ""}), \
                 patch.object(self.app, "run_command_async") as run:
                self.app._maybe_launch_indexer(force=True)
            return run.called

        self.app.var_zh_script.set("asis")
        self.assertFalse(launches(), "nothing changed: no re-index")
        self.app.var_zh_script.set("t")
        self.assertTrue(launches(), "the script changed: the store must be rebuilt")


if __name__ == "__main__":
    unittest.main()
