"""Settings -> Language & Parsing -> "Idioms and set phrases on your list" (logic.phrase_rows), and Settings -> Data &
System -> Data credits.

The switch is on by default; the dashboard rebuilds settings.json from scratch on every save, so the key must be in
its list or a save would drop it. It changes what a run lists, so it is in the run signature (never a
presentation-only setting); it reads no file differently, so it is not in the token store's build signature. The
credits hover lists every data source the app ships or is built from — the licences ask for it wherever the data goes,
and an in-place update carries only the app, never README.
"""

import json
import os
from unittest.mock import patch

import pytest

from app import analyzer, settings_manager
from app import token_index as ti

TOOLTIP = ("Adds dictionary phrases your library uses often — 気がする, 腑に落ちる, もしかしたら — as rows of their own, "
           "each ready once you know the words in it. Their words keep their own rows.")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_manager, "get_user_file", lambda name: str(path))
    return path


def test_on_by_default_and_a_missing_key_reads_as_on(settings):
    assert settings_manager.DEFAULT_SETTINGS["logic"]["phrase_rows"] is True
    settings.write_text('{"logic": {"names_katakana": true}}', encoding="utf-8")
    assert settings_manager.load_settings()["logic"]["phrase_rows"] is True
    settings.write_text('{"logic": {"phrase_rows": false}}', encoding="utf-8")
    assert settings_manager.load_settings()["logic"]["phrase_rows"] is False
    assert ti.phrase_rows_on("ja") is False and ti.phrase_rows_on("zh") is False


def test_flipping_it_is_a_new_analysis_but_no_new_index(settings):
    """In the run signature (a flip analyzes again); never in the build signature — every file reads the same."""
    assert ti.build_signature("ja") == "ja|reinforce=False"
    settings.write_text('{"logic": {"phrase_rows": false}}', encoding="utf-8")
    assert ti.build_signature("ja") == "ja|reinforce=False"


def test_it_is_in_the_run_signature():
    """Saved as the dashboard saves it, into the sandbox's own settings.json: flipped, Generate analyzes again."""
    def save(on):
        current = settings_manager.load_settings()
        settings_manager.save_settings(dict(current, logic=dict(current["logic"], phrase_rows=on)))

    save(True)
    args = analyzer.parse_analysis_args(["--language", "ja", "--static"])
    found = analyzer.resolve_found_files("ja", verbose=False)
    on = analyzer.compute_run_signature("ja", found, args)
    save(False)
    off = analyzer.compute_run_signature("ja", found, args)
    assert on and off and on != off


def _dashboard(monkeypatch):
    import tkinter as tk
    import app.main as main_module
    real_tooltip, tipped = main_module.ToolTip, {}

    def recording(widget, text, *args, **kwargs):
        tipped[str(widget)] = (text, kwargs)
        return real_tooltip(widget, text, *args, **kwargs)

    monkeypatch.setattr(main_module, "ToolTip", recording)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    root.withdraw()
    monkeypatch.setattr(tk, "_default_root", root)
    with patch.object(main_module.MasterDashboardApp, "check_updates_thread"):
        app = main_module.MasterDashboardApp(root)
    app.create_settings_window()
    return root, app, tipped


def test_the_checkbox_saves_loads_and_shows_for_japanese_only(monkeypatch):
    """One checkbox right below "Phrases and titles as one word", on by default, with its tooltip; Japanese only.
    Unticking saves it into settings.json's logic block (the rest of the block kept); the next start reads it back,
    and a settings.json without it reads as on."""
    from tkinter import ttk
    root, app, tipped = _dashboard(monkeypatch)
    settings_file = os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")
    try:
        box = app.chk_phrase_rows
        assert isinstance(box, ttk.Checkbutton) and box.cget("text") == "Idioms and set phrases on your list"
        assert tipped[str(box)][0] == TOOLTIP, "the toggle has its tooltip"
        assert box.master is app.lang_options_frame and app.var_phrase_rows.get() is True
        app.var_language.set("ja")
        shown = app.lang_options_frame.pack_slaves()
        assert shown.index(box) == shown.index(app.chk_phrases_and_titles) + 1, "right below phrases and titles"
        app.var_language.set("zh")
        assert box.winfo_manager() == "", "Chinese has no such rows"
        app.var_language.set("ja")
        assert box.winfo_manager() == "pack"

        box.invoke()
        with open(settings_file, encoding="utf-8") as handle:
            logic = json.load(handle)["logic"]
        assert logic["phrase_rows"] is False and logic["phrases_and_titles"] is True, "the rest of the block kept"

        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {"phrase_rows": False}}, handle)
        app.load_settings()
        assert app.var_phrase_rows.get() is False
        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {}}, handle)
        app.load_settings()
        assert app.var_phrase_rows.get() is True, "a missing key reads as on"
    finally:
        root.destroy()


def test_the_credits_hover_lists_every_data_source(monkeypatch):
    """Settings -> Data & System -> "ⓘ Data credits": a label whose tooltip — wider than a toggle's, kept on the
    screen — names every data source the app ships or is built from, JMdict first with its date, and each licence."""
    import app.main as main_module
    root, app, tipped = _dashboard(monkeypatch)
    try:
        label = app.lbl_credits
        assert label.cget("text") == "ⓘ Data credits"
        assert "Data & System" in label.master.cget("text")
        text, options = tipped[str(label)]
        assert options.get("wrap", 300) > 300
        credits = text() if callable(text) else text
    finally:
        root.destroy()
    from app import dictionary_data
    assert f"JMdict created {dictionary_data.JMDICT_CREATED}" in credits
    for source in ("JMdict", "JMnedict", "EDRDG", "CC BY-SA 4.0", "UniDic", "unidic-lite", "MeCab", "fugashi", "jieba",
                   "OpenCC", "Apache License 2.0", "CC-CEDICT", "JPDB 2024", "Jiten", "TMW", "RealPersonaChat",
                   "Aozora Bunko", "Wikipedia", "Leipzig Corpora Collection", "CC BY 4.0", "Tatoeba", "CC BY 2.0 FR",
                   "KdConv", "Wikinews"):
        assert source in credits, source
    assert credits.index("JMdict") < credits.index("UniDic") < credits.index("JPDB 2024")
    assert main_module.data_credits() == credits


def test_a_tall_tip_stays_on_the_screen():
    """The credits tip is tall: shown near the bottom of the screen it moves up instead of running off it."""
    import tkinter as tk
    import app.main as main_module
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    try:
        label = tk.Label(root, text="ⓘ")
        label.pack()
        root.update_idletasks()
        tip = main_module.ToolTip(label, main_module.data_credits(), wrap=520)
        with patch.object(label, "winfo_rooty", return_value=root.winfo_screenheight() - 30):
            tip.show_tip()
        tip.tip_window.update_idletasks()
        bottom = tip.tip_window.winfo_y() + tip.tip_window.winfo_height()
        assert bottom <= root.winfo_screenheight()
        tip.hide_tip()
    finally:
        root.destroy()
