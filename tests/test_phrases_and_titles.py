"""Phrases and titles as one word (Settings -> Language & Parsing, logic.phrases_and_titles).

A dictionary compound that is a phrase pattern (予想通り, こと自体), 元 + a noun (元首相) or a title (もののけ姫) is one
word with the switch on (the default), its parts with it off. The switch is read as every file is tokenized, so it
must reach everything that decides how a file or a known word was read:

- settings.json's logic block (on by default; the dashboard rebuilds settings.json from scratch on every save, so a
  key it doesn't list would vanish);
- the token store's build signature — a suffix only when off, so a store built as shipped keeps its signature and
  flipping the switch re-reads every file;
- the known-words cache (a known 予想通り reads as one word or two);
- the analyzer, which reads the logic block when it starts (a run is its own process).

The joining itself is the tokenizer's (analyzer.join_affixes) and is tested with it; these tests are the plumbing.
"""
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from app import settings_manager
from app import token_index as ti

TOOLTIP = ("On: 予想通り, こと自体, 元首相 and もののけ姫 each count as one word. "
           "Off: they count as their parts (予想 + 通り).")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """A settings.json of the test's own, read fresh by every signature (as the dashboard and the indexer read it)."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_manager, "get_user_file", lambda name: str(path))
    return path


def test_the_switch_is_on_by_default_and_a_missing_key_reads_as_on(settings):
    """An older settings.json has no such key: the deep-merged default fills it in, on."""
    assert settings_manager.DEFAULT_SETTINGS["logic"]["phrases_and_titles"] is True
    settings.write_text('{"logic": {"names_katakana": true}}', encoding="utf-8")
    assert settings_manager.load_settings()["logic"]["phrases_and_titles"] is True
    settings.write_text('{"logic": {"phrases_and_titles": false}}', encoding="utf-8")
    assert settings_manager.load_settings()["logic"]["phrases_and_titles"] is False


def test_the_switch_is_in_the_store_build_signature_only_when_off(settings):
    """Flipping it re-reads every file (the cached tokens hold the joins); on, the default, adds nothing — a store
    built as shipped keeps its signature, and upgrading rebuilds no one's index for it. It sits beside the katakana
    names switch, each suffix only when that switch is off; a Chinese store never reads it."""
    assert ti.build_signature("ja") == "ja|reinforce=False"
    settings.write_text('{"logic": {"phrases_and_titles": false}}', encoding="utf-8")
    assert ti.build_signature("ja") == "ja|reinforce=False|phrases_and_titles=off"
    settings.write_text('{"logic": {"phrases_and_titles": false, "names_katakana": false}}', encoding="utf-8")
    assert ti.build_signature("ja") == "ja|reinforce=False|names_katakana=off|phrases_and_titles=off"
    assert ti.build_signature("zh") == "zh|reinforce=False", "a Chinese store never reads it"
    settings.write_text('{"logic": {"phrases_and_titles": true}}', encoding="utf-8")
    assert ti.build_signature("ja") == "ja|reinforce=False", "back on: the store's own signature again"


def test_the_known_words_cache_misses_when_the_switch_flips(settings, tmp_path):
    """A known 予想通り is one word with the switch on and two with it off: flipping it reads the known words again,
    and flipping it back finds the cache that was right for on. A Chinese store's cache never looks at it."""
    store = ti.open_store("ja", path=str(tmp_path / "ja.db"))
    try:
        sig = ti.known_signature(str(tmp_path / "KnownWord.json"))
        store.set_cached_known(sig, {("予想通り", "ヨソウドオリ")}, {"予想通り"})
        assert store.get_cached_known(sig) is not None
        settings.write_text('{"logic": {"phrases_and_titles": false}}', encoding="utf-8")
        assert store.get_cached_known(sig) is None, "the switch flipped: read the known words again"
        settings.write_text('{"logic": {"phrases_and_titles": true}}', encoding="utf-8")
        assert store.get_cached_known(sig) is not None
    finally:
        store.close()
    store = ti.open_store("zh", path=str(tmp_path / "zh.db"))
    try:
        store.set_cached_known(sig, {("学习", "xuexi")}, {"学习"})
        settings.write_text('{"logic": {"phrases_and_titles": false}}', encoding="utf-8")
        assert store.get_cached_known(sig) is not None
    finally:
        store.close()


def test_a_run_reads_the_switch_from_settings_json():
    """The analyzer runs as its own process and reads settings.json's logic block when it starts: the switch as the
    user left it is the one the tokenizer reads. (The test root is this test's own — conftest points
    SURASURA_TEST_ROOT at it, and the child process inherits it.)"""
    root = os.environ["SURASURA_TEST_ROOT"]
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"target_language": "ja", "logic": {"phrases_and_titles": False}}, handle)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=project_root + os.pathsep + os.environ.get("PYTHONPATH", ""),
               PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-c", "from app import analyzer; print(analyzer.LOGIC['phrases_and_titles'])"],
                         cwd=project_root, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "False"


def test_flipping_the_switch_means_a_new_analysis():
    """The switch changes what a run counts, so it is in the run signature (never a presentation-only setting):
    flipped, Generate analyzes again instead of reopening the last report. Saved as the dashboard saves it, into
    the sandbox's own settings.json."""
    from app import analyzer

    def save(on):
        settings = settings_manager.load_settings()
        settings_manager.save_settings(dict(settings, logic=dict(settings["logic"], phrases_and_titles=on)))

    save(True)
    args = analyzer.parse_analysis_args(["--language", "ja", "--static"])
    found = analyzer.resolve_found_files("ja", verbose=False)
    on = analyzer.compute_run_signature("ja", found, args)
    save(False)
    off = analyzer.compute_run_signature("ja", found, args)
    assert on and off and off != on
    save(True)
    assert analyzer.compute_run_signature("ja", found, args) == on


def test_the_checkbox_saves_loads_shows_for_japanese_only_and_re_indexes(monkeypatch):
    """Settings -> Language & Parsing: one checkbox below the names switches, on by default, with the tooltip that
    shows what it joins; shown for a Japanese library only. Ticking it saves it into settings.json's logic block
    (the rest of the block kept); it changes how every file reads, so the library is indexed again. The next start
    reads it back, and a settings.json without it reads as on."""
    import tkinter as tk
    from tkinter import ttk
    import app.main as main_module

    real_tooltip, tipped = main_module.ToolTip, {}

    def recording(widget, text, *args, **kwargs):
        tipped[str(widget)] = text
        return real_tooltip(widget, text, *args, **kwargs)

    monkeypatch.setattr(main_module, "ToolTip", recording)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    root.withdraw()
    monkeypatch.setattr(tk, "_default_root", root)      # the dashboard's Tk variables belong to the default root
    settings_file = os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")
    try:
        with patch.object(main_module.MasterDashboardApp, "check_updates_thread"):
            app = main_module.MasterDashboardApp(root)
        app.create_settings_window()
        box = app.chk_phrases_and_titles
        assert isinstance(box, ttk.Checkbutton) and box.cget("text") == "Phrases and titles as one word"
        assert tipped[str(box)] == TOOLTIP, "the toggle has its tooltip"
        assert box.master is app.lang_options_frame and "Language & Parsing" in box.master.master.cget("text")
        assert app.var_phrases_and_titles.get() is True

        app.var_language.set("ja")
        shown = app.lang_options_frame.pack_slaves()
        assert box in shown and shown.index(box) == shown.index(app.names_frame) + 1, "right below the names"
        app.var_language.set("zh")
        assert box.winfo_manager() == "", "Chinese has no such compounds"
        app.var_language.set("ja")
        assert box.winfo_manager() == "pack"

        # A store built as the settings stand, and a fresh known-words cache: only the choice can differ.
        store = ti.open_store("ja")
        try:
            store.reconcile([], lambda path: {"sentences": [], "counts": {}}, build_signature=ti.build_signature("ja"))
            known = os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "ja", "KnownWord.json")
            store.set_cached_known(ti.known_signature(known), set(), set())
        finally:
            store.close()

        def launches():
            app._indexer_busy = False
            with patch.dict(os.environ, {"SURASURA_NO_AUTOINDEX": ""}), patch.object(app, "run_command_async") as run:
                app._maybe_launch_indexer(force=True)
            return run.called

        assert not launches(), "nothing changed: no re-index"
        built = ti.build_signature("ja")
        box.invoke()
        with open(settings_file, encoding="utf-8") as handle:
            logic = json.load(handle)["logic"]
        assert logic["phrases_and_titles"] is False
        assert logic["names_katakana"] is True and settings_manager.load_settings()["logic"]["sentence_boundaries"], \
            "the rest of the logic block is kept (the dashboard writes only its own keys, W1.3: the rest read back as every run reads it)"
        assert ti.build_signature("ja") == built + "|phrases_and_titles=off"
        assert launches(), "every file reads differently: re-index"

        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {"phrases_and_titles": False}}, handle)
        app.load_settings()
        assert app.var_phrases_and_titles.get() is False
        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {}}, handle)
        app.load_settings()
        assert app.var_phrases_and_titles.get() is True, "a missing key reads as on"
    finally:
        root.destroy()
