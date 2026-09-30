"""Ignore names (Settings -> Language & Parsing; logic.ignore_names, off by default).

A learner learns the names of what they watch and read too, so a name counts like any other word — unless they turn
this on. Then the library's names are ignored words everywhere, as a line of the Ignore list is: off the list, never an
unknown in a sentence, not counted by the Rarity slider or 例文. What is a name (app/names.py): a word the tagger's
dictionary knows and tags as a person's name (須藤, 茂木), a katakana name made one word (ミロナイ) and a kanji name the
library's table joins (奏汰) — never a spelling UniDic also lists as a common word said the same way (ひかり 'light',
悪魔 'devil'), a name keyed as a common word is (麻衣, keyed マイ as マイ 'my' is), a place (東京), a single kana or a
word the dictionary doesn't know at all. The token store records each file's names as it indexes it; one reader,
token_index.ignored_names — part of ignored_entries, which every ignore set already calls — hands them out.

Made-up sentences throughout; the names are UniDic's own or made up.
"""
import json
import os
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, names, settings_manager
from app import token_index as ti

TOOLTIP = ("On: people's names (田中, ミロナイ) are treated as ignored words — off your list, and never counted as "
           "unknown in a sentence. Takes effect at the next Generate.")

# A made-up village: two people UniDic knows (須藤, 茂木), a katakana name no dictionary lists (ミロナイ), and words
# that look like names to the tagger but are not ignored as one: ひかり (also 光 'light'), 悪魔 (a common noun UniDic
# tags as a name), 麻衣 (keyed マイ, as マイ 'my' is) and a place, 東京.
VILLAGE = ("須藤は村に来た。\n須藤と冒険に行った。\n茂木さんが笑った。\n"
           "ミロナイが村に来た。\nミロナイは森に帰った。\n")
LOOKALIKES = "ひかりさんが笑った。\n悪魔が笑った。\n麻衣が笑った。\n東京に行った。\n"
# 奏汰 is a given name in JMnedict and no dictionary word; the tagger cuts it 奏 + 汰. Three uses: the library joins it.
SOTA = "奏汰が駅に来た。\n昨日は奏汰と話した。\n奏汰は笑った。\n"


def _names_of(text):
    """The names one file's record holds, as the token store records them while it indexes the file."""
    analyzer.SANITIZE_JA = True
    record = names.Record()
    for _sentence in analyzer.JapaneseTokenizer(library=False).tokenize_sentences(text, names=record):
        pass
    return dict(record.data()["n"])


def _switch(on):
    """Ignore names as the dashboard saves it: settings.json's logic block, in the test's own sandbox."""
    settings = settings_manager.load_settings()
    settings_manager.save_settings(dict(settings, logic=dict(settings["logic"], ignore_names=on)))


def _library(folder, files):
    """A made-up library — in nested folders, as a real one is — indexed into the language's store."""
    paths = []
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    ti.reconcile_language("ja", paths)
    return paths


# --- what is a name ------------------------------------------------------------------------------------------------- #
def test_the_names_a_file_holds_as_the_store_records_them():
    """UniDic's person names and a katakana name made one word are names, each by the lemma the list keys it by (the
    tagger writes a person's lemma in katakana: 須藤 is スドウ)."""
    assert _names_of(VILLAGE) == {"スドウ": 2, "シゲキ": 1, "ミロナイ": 2}


@pytest.mark.parametrize("text, why", [
    ("ひかりさんが笑った。", "UniDic also lists the common word ひかり (光 'light'), spelled and said the same"),
    ("悪魔が笑った。", "UniDic tags 悪魔 a name even here, but lists the common noun said the same"),
    ("麻衣が笑った。", "the name is keyed マイ, as マイ 'my' is: ignoring it would hide the common word"),
    ("東京に行った。", "a place is no person's name"),
    ("ぐ、ぐぬぬ", "a single kana the tagger tags as a name is a sound or a piece"),
    ("ヌピャルガが来た。", "a word the dictionary doesn't know at all: its tag is the tagger's guess"),
    ("ブシン祭が始まった。", "a word the lists carry (ブシン), one word only because its pieces are no words (ブ, read "
                        "as the prefix 無, + シン): as often a word as a name, never hidden"),
    ("コスパがいい。", "likewise a word the lists carry, cut into pieces that are no words (コ + スパ)"),
])
def test_what_is_not_a_name_here(text, why):
    assert _names_of(text) == {}, why


def test_a_kanji_name_the_library_joins_is_a_name(tmp_path):
    """奏汰 is no name the tagger knows (奏 + 汰), but the library holds it three times: its table joins it, and the
    library's names hold it — keyed as the table keys it."""
    store = ti.open_store("ja", path=str(tmp_path / "ja.db"))
    try:
        paths = []
        for n, line in enumerate(SOTA.splitlines()):
            path = tmp_path / "lib" / f"sota_{n}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(line + "\n", encoding="utf-8")
            paths.append(str(path))
        store.reconcile(paths, ti.make_tokenizer("ja"), build_signature=ti.build_signature("ja"))
        assert store.names_tables()["j"]["奏汰"][1] == "奏汰"
        assert "奏汰" in json.loads(store.get_meta("names_words"))
    finally:
        store.close()


# --- the store and the reader --------------------------------------------------------------------------------------- #
def test_the_reader_gives_the_library_names_only_when_the_switch_is_on(tmp_path):
    """The store keeps the library's names whatever the switch says (flipping it needs no re-index); the reader hands
    them out only with Ignore names on — and ignored_entries, which every ignore set reads, carries them after
    KnownWord.json's IGNORED entries."""
    _library(tmp_path / "data" / "ja" / "HighPriority" / "village" / "part 1", {"a.txt": VILLAGE, "b.txt": LOOKALIKES})
    uf = tmp_path / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(json.dumps({"words": [{"dictForm": "冒険", "knownStatus": "IGNORED"}]},
                                                  ensure_ascii=False), encoding="utf-8")
    assert settings_manager.DEFAULT_SETTINGS["logic"]["ignore_names"] is False
    assert ti.ignored_names("ja") == [], "off by default"
    assert ti.ignored_entries(str(uf), "ja") == ["冒険"]
    _switch(True)
    assert ti.ignored_names("ja") == ["シゲキ", "スドウ", "ミロナイ"]
    assert ti.ignored_entries(str(uf), "ja") == ["冒険", "シゲキ", "スドウ", "ミロナイ"]
    assert analyzer.load_ignored_entries(str(uf), "asis", "ja") >= {"冒険", "スドウ", "ミロナイ"}
    assert ti.ignored_names("zh") == [], "the names are Japanese only"
    _switch(False)
    assert ti.ignored_names("ja") == []


def test_no_store_a_damaged_one_or_an_empty_library_ignores_no_name(tmp_path):
    """Before the first index there are no names to ignore; a store that can't be read, or a value that isn't a list
    of names, ignores none either — and an empty library has none. Never an error."""
    _switch(True)
    assert ti.ignored_names("ja") == [], "no store yet"
    ti.reconcile_language("ja", [])
    assert ti.ignored_names("ja") == [], "an empty library"
    store = ti.open_store("ja")
    try:
        store.set_meta("names_words", '{"not": "a list"}')
    finally:
        store.close()
    assert ti.ignored_names("ja") == []
    with open(ti.store_path_for("ja"), "wb") as handle:
        handle.write(b"not a database")
    assert ti.ignored_names("ja") == []


def test_a_chinese_store_keeps_no_names(tmp_path):
    path = tmp_path / "zh.txt"
    path.write_text("我们今天去北京。\n", encoding="utf-8")
    store = ti.open_store("zh", path=str(tmp_path / "zh.db"))
    try:
        store.reconcile([str(path)], ti.make_tokenizer("zh"))
        assert store.get_meta("names_words") is None
    finally:
        store.close()


# --- a whole run --------------------------------------------------------------------------------------------------- #
def _generate(tmp_path, files):
    """One real run (Generate) over a HighPriority library of `files`, every word listed -> the priority list's bytes
    and its rows by Word."""
    uf = tmp_path / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    high = tmp_path / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    for name, body in files.items():
        (high / name).write_text(body, encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(tmp_path / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(tmp_path / "data" / l) if l else str(tmp_path / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(tmp_path / "User Files" / l) if l else str(tmp_path / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()
    path = results / "priority_learning_list.csv"
    rows = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
    return path.read_bytes(), set(rows["Word"])


def test_a_run_with_the_switch_off_is_unchanged_and_on_leaves_the_names_out(tmp_path):
    """Off — whether settings.json says so or holds no such key — a run lists exactly what it did: byte for byte.
    On, the people are off the list; the look-alikes, whose words the dictionary lists, and the place stay."""
    files = {"village.txt": VILLAGE, "lookalikes.txt": LOOKALIKES}
    absent, words = _generate(tmp_path / "absent", files)
    assert {"スドウ", "シゲキ", "ミロナイ", "ヒカリ", "アクマ", "マイ", "トウキョウ"} <= words
    _switch(False)
    off, _words = _generate(tmp_path / "off", files)
    assert off == absent, "off is today's list, byte for byte"
    _switch(True)
    _on, words = _generate(tmp_path / "on", files)
    assert not {"スドウ", "シゲキ", "ミロナイ"} & words, "the people are ignored words"
    assert {"ヒカリ", "アクマ", "マイ", "トウキョウ", "冒険"} <= words, "look-alikes, the place and the rest stay"


def test_flipping_the_switch_means_a_new_analysis_and_no_re_index():
    """The switch changes what a run counts, so it is in the run signature (never a presentation-only setting):
    flipped, Generate analyzes again. It changes nothing a file reads as — the store records names either way — so the
    store's build signature, and with it the index, stays."""
    _switch(False)
    args = analyzer.parse_analysis_args(["--language", "ja", "--static"])
    found = analyzer.resolve_found_files("ja", verbose=False)
    off = analyzer.compute_run_signature("ja", found, args)
    built = ti.build_signature("ja")
    _switch(True)
    on = analyzer.compute_run_signature("ja", found, args)
    assert on and off and on != off
    assert ti.build_signature("ja") == built


# --- the Rarity slider and 例文 -------------------------------------------------------------------------------------- #
def test_the_rarity_slider_and_example_sentences_count_no_name_when_on(tmp_path):
    """The slider's numbers (and automatic rarity, which decides from them) and 例文 / the sentence dictionary read the
    same ignore set as the list: a name is no unknown with the switch on, one like any other word with it off."""
    from app import sentence_corpus
    _library(tmp_path / "lib", {"village.txt": VILLAGE})
    uf = os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "ja")
    os.makedirs(uf, exist_ok=True)
    store = ti.open_store("ja")
    try:
        for on in (False, True):
            _switch(on)
            unknown = dict(ti.preview_frequencies(store, "ja", uf)["unknown"])
            assert ("スドウ|スドウ" in unknown) is not on and ("ミロナイ|" in unknown) is not on
            assert "冒険|ボウケン" in unknown
            ignore = sentence_corpus.known_sets("ja", store, settings_manager.load_settings())[2]
            assert {"スドウ", "ミロナイ"} & ignore == ({"スドウ", "ミロナイ"} if on else set())
    finally:
        store.close()


# --- the Settings window ------------------------------------------------------------------------------------------ #
def test_the_checkbox_saves_loads_shows_for_japanese_only_and_refreshes_the_slider(monkeypatch):
    """Settings -> Language & Parsing: one checkbox below the phrases switch, off by default, with its tooltip;
    shown for a Japanese library only. Ticking it saves it into settings.json's logic block (the dashboard rebuilds
    settings.json from scratch, so an unlisted key would vanish), re-reads no file, and refreshes the Rarity slider,
    whose cached numbers it invalidates. The next start reads it back; a settings.json without it reads as off."""
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
        box = app.chk_ignore_names
        assert isinstance(box, ttk.Checkbutton) and box.cget("text") == "Ignore names"
        assert tipped[str(box)] == TOOLTIP, "the toggle has its tooltip"
        assert box.master is app.lang_options_frame and "Language & Parsing" in box.master.master.cget("text")
        assert app.var_ignore_names.get() is False, "off by default"

        app.var_language.set("ja")
        shown = app.lang_options_frame.pack_slaves()
        assert box in shown and shown.index(box) == shown.index(app.chk_phrases_and_titles) + 1
        app.var_language.set("zh")
        assert box.winfo_manager() == "", "the names are Japanese only"
        app.var_language.set("ja")
        assert box.winfo_manager() == "pack"

        sel = {"band": "occasional"}
        before = app._preview_signature("ja", sel)
        built = ti.build_signature("ja")
        with patch.object(app, "_refresh_band_preview") as refresh:
            box.invoke()
        with open(settings_file, encoding="utf-8") as handle:
            logic = json.load(handle)["logic"]
        assert logic["ignore_names"] is True
        assert logic["names_katakana"] is True and logic["sentence_boundaries"], "the rest of the logic block is kept"
        assert refresh.called, "the slider's numbers follow at once"
        assert app._preview_signature("ja", sel) != before, "its cached numbers no longer stand"
        assert ti.build_signature("ja") == built, "no file reads differently: no re-index"

        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {"ignore_names": True}}, handle)
        app.load_settings()
        assert app.var_ignore_names.get() is True
        with open(settings_file, "w", encoding="utf-8") as handle:
            json.dump({"target_language": "ja", "logic": {}}, handle)
        app.load_settings()
        assert app.var_ignore_names.get() is False, "a missing key reads as off"
    finally:
        root.destroy()
