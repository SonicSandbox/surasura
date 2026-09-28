"""Kana in parentheses right after kanji in a Japanese book — 山田太郎(やまだ・たろう), 東京（とうきょう） — is that
kanji's reading, the typographic stand-in for ruby, not more words: read as text, it counts the word again
(トウキョウ twice), often in pieces that are no word at all (やまだ・たろう → 山 + だ + 太郎).

How it is read is the learner's choice — settings.json `logic.paren_readings`, Settings → Language & Parsing →
"Readings in ( ) in books" (Japanese only):

- "hiragana" — "Hiragana only (recommended)", the default: a hiragana group (with ・ ー) goes, as an Aozora
  《ruby》 does. A katakana group stays: after kanji it is as often a note or a loanword's gloss (規則（ルール）) as
  a reading.
- "any" — "Any kana": a katakana or mixed group goes too.
- "off" — "Keep as text": every group is text, as before.

One function reads it for every reader of a book (analyzer.strip_text_conventions: a run, the token store, the
sentence dictionary, パターン). It changes what a run counts, so it is part of the run signature and — when it
isn't the default — of the token store's build signature; the report's source link still finds a sentence whichever
option. Made-up sentences and general Japanese (窮鼠猫を噛む) throughout.
"""
import json
import os
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import analyzer, settings_manager
from app import token_index as ti
from app.static_html_generator import AnchorFinder

BOOK = ("山田太郎(やまだ・たろう)は東京（とうきょう）の大学に通っている。\n"
        "窮鼠（きゅうそ）猫を噛むと言うが、彼（ケン）は規則（ルール）を守った。\n"
        "駅に着いた（やっと着いた）ので、家に電話した。\n")
OPTIONS = ("hiragana", "any", "off")


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


def _choose(monkeypatch, option):
    """The option as a run reads it: settings.json's logic block, loaded into LOGIC when the analyzer starts."""
    monkeypatch.setitem(analyzer.LOGIC, "paren_readings", option)


def _read(tmp_path, text=BOOK, name="book.txt", language="ja"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return analyzer.extract_text(str(path), language)


def _lemmas(tokenizer, text):
    return Counter(lemma for _s, tokens in tokenizer.tokenize_sentences(text) for lemma, _r, _surface, _o in tokens)


def _settings_file():
    return os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")


def _write_settings(settings):
    with open(_settings_file(), "w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False)


# --- the rule, per option --------------------------------------------------------------------------------- #
def test_by_default_a_hiragana_reading_goes_and_a_katakana_group_stays(tmp_path, monkeypatch):
    """The default (no key at all, as in a settings.json from before the setting): hiragana only."""
    monkeypatch.delitem(analyzer.LOGIC, "paren_readings", raising=False)
    assert settings_manager.DEFAULT_SETTINGS["logic"]["paren_readings"] == "hiragana"
    assert analyzer.paren_readings() == "hiragana"
    assert _read(tmp_path) == ("山田太郎は東京の大学に通っている。\n"
                               "窮鼠猫を噛むと言うが、彼（ケン）は規則（ルール）を守った。\n"
                               "駅に着いた（やっと着いた）ので、家に電話した。\n")


def test_the_reading_is_no_longer_counted_again(tmp_path, monkeypatch, tokenizer):
    """What the learner saw once is counted once: the default reads the book as if printed with ruby."""
    _choose(monkeypatch, "hiragana")
    assert _lemmas(tokenizer, _read(tmp_path)) == _lemmas(tokenizer, _read(tmp_path, (
        "山田太郎は東京の大学に通っている。\n"
        "窮鼠猫を噛むと言うが、彼（ケン）は規則（ルール）を守った。\n"
        "駅に着いた（やっと着いた）ので、家に電話した。\n"), name="ruby.txt"))
    _choose(monkeypatch, "off")
    kept = _lemmas(tokenizer, _read(tmp_path, name="kept.txt"))
    assert kept["トウキョウ"] == 2, "kept as text, とうきょう is 東京 counted a second time"


def test_any_kana_drops_a_katakana_group_too(tmp_path, monkeypatch):
    _choose(monkeypatch, "any")
    assert _read(tmp_path) == ("山田太郎は東京の大学に通っている。\n"
                               "窮鼠猫を噛むと言うが、彼は規則を守った。\n"
                               "駅に着いた（やっと着いた）ので、家に電話した。\n")


def test_keep_as_text_reads_the_book_as_written(tmp_path, monkeypatch):
    _choose(monkeypatch, "off")
    assert _read(tmp_path) == BOOK


def test_an_unknown_value_reads_as_the_default(tmp_path, monkeypatch):
    """A hand-edited settings.json ("katakana", a typo) must neither crash a run nor switch the rule off."""
    _choose(monkeypatch, "katakana")
    assert analyzer.paren_readings() == "hiragana"
    assert analyzer.paren_readings({"paren_readings": None}) == "hiragana"
    assert _read(tmp_path).startswith("山田太郎は東京の大学に")


@pytest.mark.parametrize("option", OPTIONS)
def test_only_a_group_right_after_kanji_is_a_reading(tmp_path, monkeypatch, option):
    """An aside after a verb, empty brackets, a number's note: no kanji before them, or no kana in them — text in
    every option."""
    _choose(monkeypatch, option)
    text = "駅に着いた（やっと着いた）ので電話した。\n漢字（）の練習。\n第3章（２）を読む。\n"
    assert _read(tmp_path, text) == text


def test_half_width_and_full_width_brackets_and_windows_line_ends(tmp_path, monkeypatch):
    """( ) and （ ）, even mixed, in a file saved with CRLF: the reading goes and the line ends stay."""
    _choose(monkeypatch, "hiragana")
    path = tmp_path / "crlf.txt"
    path.write_bytes("大阪(おおさか)に行く。\r\n京都（きょうと)に行く。\r\n".encode("utf-8"))
    text = analyzer.extract_text(str(path), "ja")
    assert "おおさか" not in text and "きょうと" not in text
    assert text.replace("\r", "") == "大阪に行く。\n京都に行く。\n"


def test_a_markdown_book_too_but_never_a_transcript_or_a_chinese_file(tmp_path, monkeypatch):
    """A .md book is a book. The downloader's transcript is captions, not a book: its text is kept as spoken. And
    the rule is Japanese: a Chinese file's brackets are its own."""
    _choose(monkeypatch, "any")
    assert _read(tmp_path, "# 第一章\n東京（とうきょう）に着いた。\n", name="book.md") == "第一章\n東京に着いた。\n"
    transcript = ("東京散歩\n散歩チャンネル | 2025-05-01 | 3:10\nCaptions: Japanese (manual)\n"
                  "https://www.youtube.com/watch?v=abcdefghijk\n\n" + "-" * 60 + "\n東京（とうきょう）に着きました\n")
    assert "（とうきょう）" in _read(tmp_path, transcript, name="walk [abcdefghijk].txt")
    assert _read(tmp_path, "我到了东京（とうきょう）。\n", name="zh.txt", language="zh") == "我到了东京（とうきょう）。\n"


# --- the report's source link --------------------------------------------------------------------------------- #
@pytest.mark.parametrize("option", OPTIONS)
def test_the_source_link_finds_every_sentence_whichever_option(tmp_path, monkeypatch, tokenizer, option):
    """The report's sentence no longer holds a reading the reader dropped, but the file does: the anchor lets it sit
    between the sentence's characters and hands back the file's own wording, found once."""
    _choose(monkeypatch, option)
    path = tmp_path / "book.txt"
    path.write_text(BOOK, encoding="utf-8")
    sentences = [s for s, _t in tokenizer.tokenize_sentences(analyzer.extract_text(str(path), "ja"))]
    finder = AnchorFinder()
    for sentence in sentences:
        anchor = finder.anchor(str(path), sentence)
        assert anchor and BOOK.count(anchor) == 1, (option, sentence, anchor)


# --- the setting ------------------------------------------------------------------------------------------------ #
def test_a_saved_choice_loads_back_and_keeps_the_rest_of_the_logic_block():
    """Deep-merged like the rest of `logic`: a settings.json naming only this key keeps every other default."""
    _write_settings({"logic": {"paren_readings": "off"}})
    loaded = settings_manager.load_settings()
    assert loaded["logic"]["paren_readings"] == "off"
    assert loaded["logic"]["sentence_boundaries"]["ja"], "the other logic defaults are still there"
    loaded["logic"]["paren_readings"] = "any"
    settings_manager.save_settings(loaded)
    assert settings_manager.load_settings()["logic"]["paren_readings"] == "any"
    assert analyzer.paren_readings(settings_manager.load_settings()["logic"]) == "any"


def test_the_choice_is_part_of_the_run_signature():
    """It changes what a run counts: Generate must re-analyse after a change, and only then."""
    args = SimpleNamespace(language="ja", min_freq=2, target_coverage=90, only_i_plus_one=False,
                           ensure_audio_example=False, include_single_chars=False, exclude_freq_one=False,
                           reinforce=False, context_min=10, context_max=50, max_contexts=3)
    signatures = {}
    for option in OPTIONS:
        _write_settings({"target_language": "ja", "logic": {"paren_readings": option}})
        signatures[option] = analyzer.compute_run_signature("ja", [], args)
    assert None not in signatures.values() and len(set(signatures.values())) == 3
    _write_settings({"target_language": "ja", "logic": {"paren_readings": "any"}})
    assert analyzer.compute_run_signature("ja", [], args) == signatures["any"], "the same choice: no new run"


def test_the_token_store_signature_names_the_choice_only_when_it_is_not_the_default():
    """A store built as shipped keeps its old signature (no re-index on upgrade); another choice re-indexes."""
    assert ti.build_signature("ja") == "ja|reinforce=False"                  # no settings.json at all
    _write_settings({"logic": {"paren_readings": "hiragana"}})
    assert ti.build_signature("ja") == "ja|reinforce=False"
    _write_settings({"logic": {"paren_readings": "any"}})
    assert ti.build_signature("ja") == "ja|reinforce=False|paren_readings=any"
    assert ti.build_signature("zh", False, "s") == "zh|reinforce=False|script=s", "a Japanese book's rule"
    _write_settings({"logic": {"paren_readings": "off", "sentence_boundaries": {"ja": "。！？!?\n｡…"}}})
    assert ti.build_signature("ja").startswith("ja|reinforce=False|boundaries=")
    assert ti.build_signature("ja").endswith("|paren_readings=off")
    _write_settings({"logic": {"paren_readings": "katakana"}})
    assert ti.build_signature("ja") == "ja|reinforce=False", "an unknown value reads as the default"


def test_a_new_choice_re_reads_every_book_once(tmp_path, monkeypatch):
    """The files are unchanged on disk, so only the build signature sees the change: every file is read again —
    as the indexer would read it, with the new option — once."""
    books = [tmp_path / "a.txt", tmp_path / "b.txt"]
    books[0].write_text(BOOK, encoding="utf-8")
    books[1].write_text("東京（とうきょう）の夜は長い。\n", encoding="utf-8")
    files = [str(book) for book in books]
    store = ti.open_store("ja", path=str(tmp_path / "store.db"))
    try:
        store.reconcile(files, ti.make_tokenizer("ja"), build_signature=ti.build_signature("ja"))
        inner, calls = ti.make_tokenizer("ja"), []

        def counting(path):
            calls.append(path)
            return inner(path)

        _write_settings({"logic": {"paren_readings": "off"}})
        _choose(monkeypatch, "off")
        store.reconcile(files, counting, build_signature=ti.build_signature("ja"))
        assert len(calls) == 2, "a new choice re-reads every book"
        store.reconcile(files, counting, build_signature=ti.build_signature("ja"))
        assert len(calls) == 2, "the same choice, unchanged files: nothing to do"
    finally:
        store.close()


# --- the Settings window -------------------------------------------------------------------------------------- #
def test_the_settings_row_saves_loads_and_shows_for_japanese_only(monkeypatch):
    """Settings → Language & Parsing: one read-only combobox, labelled plainly, with a tooltip that gives an example;
    shown for a Japanese library only (like Chinese's Script row), its value kept across a trip to Chinese. Choosing
    saves it into settings.json's logic block — the dashboard rebuilds settings.json from scratch on every save, so an
    unlisted key would vanish — and re-indexes the library; the next start reads it back. One dashboard for all of it
    (one root per file)."""
    import tkinter as tk
    from tkinter import ttk
    import app.main as main_module
    from app import token_index

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
    # The dashboard's Tk variables have no master: they belong to the default root, which must be this one.
    monkeypatch.setattr(tk, "_default_root", root)
    try:
        with patch.object(main_module.MasterDashboardApp, "check_updates_thread"):
            app = main_module.MasterDashboardApp(root)
        app.create_settings_window()
        frame = app.paren_readings_frame
        [label] = [w for w in frame.winfo_children() if isinstance(w, ttk.Label)]
        [combo] = [w for w in frame.winfo_children() if isinstance(w, ttk.Combobox)]
        assert label.cget("text") == "Readings in ( ) in books:"
        assert list(combo.cget("values")) == ["Hiragana only (recommended)", "Any kana", "Keep as text"]
        assert str(combo.cget("state")) == "readonly"
        assert combo.get() == "Hiragana only (recommended)"
        assert "山田太郎(やまだ・たろう) → 山田太郎" in tipped[str(combo)]
        assert frame.master is app.lang_options_frame and "Language & Parsing" in frame.master.master.cget("text")

        app.var_language.set("ja")
        assert frame.winfo_manager() == "pack"
        app.var_language.set("zh")
        assert frame.winfo_manager() == "", "a Chinese library has no such books"
        app.var_language.set("ja")
        assert frame.winfo_manager() == "pack"

        # A store built with the default, and a fresh known-words cache: only the choice can differ.
        store = token_index.open_store("ja")
        try:
            store.reconcile([], lambda path: {"sentences": [], "counts": {}},
                            build_signature=token_index.build_signature("ja"))
            known = os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "ja", "KnownWord.json")
            store.set_cached_known(token_index.known_signature(known), set(), set())
        finally:
            store.close()

        def launches():
            app._indexer_busy = False
            with patch.dict(os.environ, {"SURASURA_NO_AUTOINDEX": ""}), \
                    patch.object(app, "run_command_async") as run:
                app._maybe_launch_indexer(force=True)
            return run.called

        assert not launches(), "nothing changed: no re-index"
        combo.set("Any kana")
        combo.event_generate("<<ComboboxSelected>>")
        root.update()
        assert app.var_paren_readings.get() == "any"
        with open(_settings_file(), encoding="utf-8") as handle:
            saved = json.load(handle)
        assert saved["logic"]["paren_readings"] == "any"
        assert saved["logic"]["sentence_boundaries"], "the rest of the logic block is kept"
        assert launches(), "the choice changed what every book reads: re-index"

        app.var_language.set("zh")
        app.var_language.set("ja")
        assert app.var_paren_readings.get() == "any", "a trip to Chinese must not reset it"

        _write_settings({"target_language": "ja", "logic": {"paren_readings": "off"}})
        app.load_settings()
        assert app.var_paren_readings.get() == "off"
        _write_settings({"target_language": "ja", "logic": {"paren_readings": "katakana"}})
        app.load_settings()
        assert app.var_paren_readings.get() == "hiragana", "an unknown saved value shows as the default"
    finally:
        root.destroy()
