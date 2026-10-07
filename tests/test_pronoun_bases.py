"""Pronouns with a suffix as one word (Settings -> Language & Parsing, logic.pronoun_bases).

A pronoun + a suffix the lists carry as a word of its own (何様, 俺様, お前さん, それなり) is one word with the switch on
(the default), its parts with it off — as a noun + its suffixes always is (Part A). Never a plural: あなた方 is read by
the lists as アナタガタ, and the table's build keeps it out though the tagger reads its 方 カタ. A nominalizer after a
pronoun is never one (これさ is これ and the particle さ).

The switch is read as every file is tokenized, so it reaches everything that decides how a file or a known word was
read — settings.json's logic block (the dashboard rebuilds it from scratch on every save), the token store's build
signature and the known-words cache (a suffix only when off), and the analyzer, which reads the logic block when it
starts. Made-up sentences throughout, read by the project's fugashi + unidic-lite.
"""
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from app import analyzer, settings_manager
from app import token_index as ti

TOOLTIP = "On: 何様, 俺様, お前さん and それなり each count as one word. Off: they count as their parts (何 + 様)."
# A table as the build makes it: the pronoun words, and a noun + suffix (Part A's own) to show the switch leaves those.
JOINS = {"何様": ["何様", "ナニサマ"], "俺様": ["俺様", "オレサマ"], "お前さん": ["お前さん", "オマエサン"],
         "これさ": ["これさ", "コレサ"], "神様": ["神様", "カミサマ"]}


@pytest.fixture(scope="module")
def tagger():
    return analyzer.Tagger()


def _read(tagger, line, joins=JOINS):
    words = analyzer.join_affixes(tagger(line), joins, library=False, compounds={}, cut_words=({}, {}))
    return [(w.surface, isinstance(w, analyzer.JoinedWord)) for w in words]


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """A settings.json of the test's own, read fresh by every signature (as the dashboard and the indexer read it)."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_manager, "get_user_file", lambda name: str(path))
    return path


# --- The joins ------------------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("line, word", [
    ("お前、何様のつもりだ？", "何様"),
    ("ここは俺様に任せろ。", "俺様"),
    ("お前さんも来るかい？", "お前さん"),
])
def test_a_pronoun_carries_a_suffix_the_lists_make_a_word_of(tagger, monkeypatch, line, word):
    monkeypatch.setitem(analyzer.LOGIC, "pronoun_bases", True)
    assert (word, True) in _read(tagger, line)


def test_with_the_switch_off_a_pronoun_word_counts_as_its_parts_and_a_noun_keeps_its_suffix(tagger, monkeypatch):
    # Off: 何 + 様 — while 神 + 様, a noun's own suffix (Part A), stays one word either way.
    monkeypatch.setitem(analyzer.LOGIC, "pronoun_bases", False)
    words = _read(tagger, "何様のつもりだ。神様に祈る。")
    assert ("何", False) in words and ("様", False) in words and ("何様", True) not in words
    assert ("神様", True) in words
    monkeypatch.setitem(analyzer.LOGIC, "pronoun_bases", True)
    assert ("何様", True) in _read(tagger, "何様のつもりだ。神様に祈る。")


def test_a_nominalizer_after_a_pronoun_is_never_one(tagger, monkeypatch):
    # The tagger reads さ after これ as the nominalizer suffix; it is the particle さ (これさ、いいよね) — never a word,
    # even were a list to carry the string.
    monkeypatch.setitem(analyzer.LOGIC, "pronoun_bases", True)
    assert ("これさ", True) not in _read(tagger, "これさ、いいよね。")


def test_the_build_keeps_a_plural_by_the_lists_reading_out_of_the_table(tagger, monkeypatch):
    # あなた方 アナタガタ is a plural (the lists' reading), though the tagger reads its 方 alone as the suffix カタ, not
    # the plural ガタ: never a word of the table. 何様 and お前さん are.
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts",
                        "build_reference_data.py")
    spec = importlib.util.spec_from_file_location("build_reference_data", path)
    brd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(brd)
    headwords = {"何様": ("ナニサマ", 1), "お前さん": ("オマエサン", 2), "あなた方": ("アナタガタ", 3)}
    joins = brd.build_joins(tagger, headwords)
    assert set(joins) == {"何様", "お前さん"}
    monkeypatch.setattr(analyzer, "LOGIC", dict(analyzer.LOGIC, pronoun_bases=False))
    brd.pin_parsing_defaults()
    assert analyzer.LOGIC["pronoun_bases"] is True, "shared data never follows the builder's own switch"


# --- The plumbing --------------------------------------------------------------------------------------------------- #

def test_the_switch_is_on_by_default_and_a_missing_key_reads_as_on(settings):
    """An older settings.json has no such key: the deep-merged default fills it in, on."""
    assert settings_manager.DEFAULT_SETTINGS["logic"]["pronoun_bases"] is True
    settings.write_text('{"logic": {"names_katakana": true}}', encoding="utf-8")
    assert settings_manager.load_settings()["logic"]["pronoun_bases"] is True
    settings.write_text('{"logic": {"pronoun_bases": false}}', encoding="utf-8")
    assert settings_manager.load_settings()["logic"]["pronoun_bases"] is False


def test_the_switch_is_in_the_store_build_signature_only_when_off(settings):
    """Flipping it re-reads every file (the cached tokens hold the joins); on, the default, adds nothing — a store
    built as shipped keeps its signature. It sits beside the other reading switches, each suffix only when that one
    is off; a Chinese store never reads it."""
    assert ti.build_signature("ja") == "ja|reinforce=False"
    settings.write_text('{"logic": {"pronoun_bases": false}}', encoding="utf-8")
    assert ti.build_signature("ja") == "ja|reinforce=False|pronoun_bases=off"
    settings.write_text('{"logic": {"pronoun_bases": false, "phrases_and_titles": false}}', encoding="utf-8")
    assert ti.build_signature("ja") == "ja|reinforce=False|phrases_and_titles=off|pronoun_bases=off"
    assert ti.build_signature("zh") == "zh|reinforce=False", "a Chinese store never reads it"
    settings.write_text('{"logic": {"pronoun_bases": true}}', encoding="utf-8")
    assert ti.build_signature("ja") == "ja|reinforce=False", "back on: the store's own signature again"


def test_the_known_words_cache_misses_when_the_switch_flips(settings, tmp_path):
    """A known 何様 is one word with the switch on and two with it off: flipping it reads the known words again, and
    flipping it back finds the cache that was right for on. A Chinese store's cache never looks at it."""
    store = ti.open_store("ja", path=str(tmp_path / "ja.db"))
    try:
        sig = ti.known_signature(str(tmp_path / "KnownWord.json"))
        store.set_cached_known(sig, {("何様", "ナニサマ")}, {"何様"})
        assert store.get_cached_known(sig) is not None
        settings.write_text('{"logic": {"pronoun_bases": false}}', encoding="utf-8")
        assert store.get_cached_known(sig) is None, "the switch flipped: read the known words again"
        settings.write_text('{"logic": {"pronoun_bases": true}}', encoding="utf-8")
        assert store.get_cached_known(sig) is not None
    finally:
        store.close()
    store = ti.open_store("zh", path=str(tmp_path / "zh.db"))
    try:
        store.set_cached_known(sig, {("学习", "xuexi")}, {"学习"})
        settings.write_text('{"logic": {"pronoun_bases": false}}', encoding="utf-8")
        assert store.get_cached_known(sig) is not None
    finally:
        store.close()


def test_a_run_reads_the_switch_from_settings_json():
    """The analyzer runs as its own process and reads settings.json's logic block when it starts. (The test root is
    this test's own — conftest points SURASURA_TEST_ROOT at it, and the child process inherits it.)"""
    root = os.environ["SURASURA_TEST_ROOT"]
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"target_language": "ja", "logic": {"pronoun_bases": False}}, handle)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=project_root + os.pathsep + os.environ.get("PYTHONPATH", ""),
               PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-c", "from app import analyzer; print(analyzer.LOGIC['pronoun_bases'])"],
                         cwd=project_root, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "False"


def test_flipping_the_switch_means_a_new_analysis():
    """The switch changes what a run counts, so it is in the run signature (never a presentation-only setting)."""
    def save(on):
        current = settings_manager.load_settings()
        settings_manager.save_settings(dict(current, logic=dict(current["logic"], pronoun_bases=on)))

    save(True)
    args = analyzer.parse_analysis_args(["--language", "ja", "--static"])
    found = analyzer.resolve_found_files("ja", verbose=False)
    on = analyzer.compute_run_signature("ja", found, args)
    save(False)
    off = analyzer.compute_run_signature("ja", found, args)
    assert on and off and off != on
    save(True)
    assert analyzer.compute_run_signature("ja", found, args) == on


def test_the_checkbox_sits_below_phrases_and_titles_saves_loads_and_re_indexes(monkeypatch):
    """Settings -> Language & Parsing: one checkbox right below "Phrases and titles as one word", on by default, with
    the tooltip that shows what it joins; shown for a Japanese library only. Unticking it saves it into settings.json's
    logic block (the rest of the block kept); it changes how every file reads, so the library is indexed again. The
    next start reads it back, and a settings.json without it reads as on."""
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
        box = app.chk_pronoun_bases
        assert isinstance(box, ttk.Checkbutton) and box.cget("text") == "Pronouns with a suffix as one word"
        assert tipped[str(box)] == TOOLTIP, "the toggle has its tooltip"
        assert box.master is app.lang_options_frame and app.var_pronoun_bases.get() is True

        app.var_language.set("ja")
        shown = app.lang_options_frame.pack_slaves()
        assert shown.index(box) == shown.index(app.chk_phrases_and_titles) + 1, "right below phrases and titles"
        app.var_language.set("zh")
        assert box.winfo_manager() == "", "Chinese has no such words"
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
        assert logic["pronoun_bases"] is False
        assert logic["phrases_and_titles"] is True and settings_manager.load_settings()["logic"]["sentence_boundaries"], \
            "the rest of the block is kept (the dashboard writes only its own keys, W1.3: the rest read back as every run reads it)"
        assert ti.build_signature("ja") == built + "|pronoun_bases=off"
        assert launches(), "every file reads differently: re-index"

        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {"pronoun_bases": False}}, handle)
        app.load_settings()
        assert app.var_pronoun_bases.get() is False
        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {}}, handle)
        app.load_settings()
        assert app.var_pronoun_bases.get() is True, "a missing key reads as on"
    finally:
        root.destroy()
