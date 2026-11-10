# SPDX-License-Identifier: GPL-3.0-or-later
"""Japanese and Chinese side by side (Patterns_Chinese_Spec.md §12, §15.3) — one learner, one collection,
maybe one deck, and never a conflict.

What this file guards, most costly first:

  * **A note type is filled only from its own language's data.** Two in three kanji-only Japanese words
    are Chinese words too (問題 / 问题, 学生, 必要 — Z-F11), so the WORD can never tell: the note type's
    language does — the user's choice, else Japanese when its notes have kana, else not set, and a note
    type whose language is not set is never filled, by hand or automatically (D7, S3).
  * **Each language keeps its own databases, packages, snapshot and build** (S1, S6, S9, S10).
  * **The window follows the dashboard's language** — what it offers, its help, its data, its build —
    and a preview of the other language never confirms a fill (S5, S11).

Chinese is on for users since WP-Z9 (`FILLS` languages), so the matrix runs as users get it — no
monkeypatch. Real words on real field names; the fake collection of `test_backfill.py`.
"""
import hashlib
import json
import os
import re
import tkinter as tk
import unittest
from tkinter import ttk
from unittest import mock

import pytest

import modules.junban as junban
from app.path_utils import get_user_files_path
from modules.junban import backfill, backfill_gui, patterns, patterns_package as pp, reposition, undo
from modules.junban import patterns_build as pb
from modules.junban.patterns_store import open_store
from modules.junban.tests.test_backfill import FIRST_CARD, FIRST_NOTE, LAPIS, BackfillCollection, _lapis
from modules.junban.tests.test_backfill_gui import BackfillGuiTestCase, _Process, _result
from modules.junban.tests.test_reposition import _patched

URL = "http://127.0.0.1:8765"
CHINESE = ["Hanzi", "Pinyin", "Meaning", "Sentence", "Patterns", "ExampleSentences"]
LAPIS_IDS = {FIRST_NOTE, FIRST_NOTE + 1, FIRST_NOTE + 2}
CHINESE_IDS = {FIRST_NOTE + 700, FIRST_NOTE + 701, FIRST_NOTE + 702}


def _zh(index, word, pinyin, sentence, deck="TheBank"):
    """One note of a Chinese note type and its one card — no kana anywhere, as a real one has none."""
    note_id, card_id = FIRST_NOTE + 700 + index, FIRST_CARD + 700 + index
    values = {"Hanzi": word, "Pinyin": pinyin, "Meaning": "", "Sentence": sentence, "Patterns": "",
              "ExampleSentences": ""}
    note = {"noteId": note_id, "modelName": "Chinese Vocab", "tags": [], "cards": [card_id],
            "fields": {name: {"value": values[name], "order": i} for i, name in enumerate(CHINESE)}}
    return note, {"cardId": card_id, "note": note_id, "due": 3000 + index, "deckName": deck, "type": 0, "queue": 0}


def _fake(*pairs, **kwargs):
    notes, cards = [p[0] for p in pairs], [p[1] for p in pairs]
    return BackfillCollection(cards, notes, {"Lapis": LAPIS, "Chinese Vocab": CHINESE}, **kwargs)


def _both(deck="TheBank"):
    """Lapis and a Chinese note type in one collection, over words both languages have: 問題 and 问题,
    学生 and 學生 (a Traditional card), 必要 and 必要."""
    return _fake(_lapis(0, "探検", "たんけん", deck=deck), _lapis(1, "問題", "もんだい", deck=deck),
                 _lapis(2, "学生", "がくせい", deck=deck),
                 _zh(0, "问题", "wèntí", "这个问题很难。", deck), _zh(1, "學生", "xuéshēng", "他是一個學生。", deck),
                 _zh(2, "必要", "bìyào", "没有必要这样做。", deck))


class _Session:
    """A lookup with no databases: every word gets a line saying which language's data wrote it."""

    def __init__(self, language):
        self.language = language

    def is_known(self, word):
        return False

    def prepare(self, fill, notes, status=None, young=()):
        pass

    def value(self, fill, note, field):
        return f'<div class="pat-colloc">{self.language}: {note["word"]}</div>', None

    def close(self):
        pass


def _settings(language, **over):
    settings = {"target_language": language, "junban_url": URL, "junban_chunk_size": 150,
                "junban_backfill_fills": ["patterns"], "junban_backfill_note_languages": {"Chinese Vocab": "zh"}}
    settings.update(over)
    return settings


def _plan(fake, language, **over):
    settings = _settings(language, **over)
    with _patched(fake):
        scope = backfill.gather(URL, settings)
    return backfill.plan(scope, _Session(language), settings)


# --- S3, S4: which note type is which language -------------------------------------------------- #
def test_both_fills_are_offered_in_chinese_and_japanese():
    # WP-Z9, the switch: a Chinese session is offered パターン and 例文 — which note types each reaches is
    # S3's, below.
    assert [fill.languages for fill in backfill.FILLS] == [("ja", "zh"), ("ja", "zh")]


def test_a_collection_with_lapis_and_a_chinese_note_type_fills_each_from_its_own_language():
    # 問題 is on Lapis and 问题 on the Chinese type: each is filled from its own language's data only.
    fake = _both()
    ja, zh = _plan(fake, "ja"), _plan(fake, "zh")
    assert set(ja["edits"]) == LAPIS_IDS and set(zh["edits"]) == CHINESE_IDS
    assert all(e["Patterns"]["after"].startswith('<div class="pat-colloc">ja: ') for e in ja["edits"].values())
    assert all(e["Patterns"]["after"].startswith('<div class="pat-colloc">zh: ') for e in zh["edits"].values())


def test_a_note_type_with_kana_and_no_language_set_is_japanese_and_never_planned_by_a_chinese_session():
    # D7 rule 2: every Lapis note has kana, so Lapis is Japanese with nothing set — and a Chinese session
    # reads its notes only to learn that, then plans none of them. Japanese sees exactly what it did.
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "問題", "もんだい"))
    settings = _settings("zh", junban_backfill_note_languages={})
    with _patched(fake):
        scope = backfill.gather(URL, settings)
    assert scope["models"]["Lapis"]["language"] == "ja" and scope["notes"] == []
    assert backfill.plan(scope, _Session("zh"), settings)["rows"] == []
    assert set(_plan(fake, "ja", junban_backfill_note_languages={})["edits"]) == {FIRST_NOTE, FIRST_NOTE + 1}


def test_a_note_type_with_no_kana_and_no_language_set_is_never_filled(monkeypatch):
    # A new Chinese note type given a Patterns field before its language is set: "Language?" in either
    # session, and nothing written — by hand or by the automatic run.
    fake = _fake(_zh(0, "问题", "wèntí", "这个问题很难。"), _zh(1, "必要", "bìyào", "没有必要这样做。"))
    for language in ("ja", "zh"):
        result = _plan(fake, language, junban_backfill_note_languages={})
        assert result["edits"] == {} and result["counts"] == {"language not set": 2}, language
    assert backfill.reason("language not set") == "Language?"
    monkeypatch.setattr(backfill, "Session", lambda settings: _Session(settings["target_language"]))
    for language in ("ja", "zh"):
        with _patched(fake):
            backfill.run_auto(_settings(language, junban_backfill_note_languages={}))
    assert fake.note_writes == []


def _with_fields(*values):
    return [{"fields": {"Hanzi": "学习", "Sentence": value}} for value in values]


@pytest.mark.parametrize("sentences, language", [
    (["今天の晚餐超好吃", "我们一起学习中文。", "这个问题很重要。", "他是我的好朋友。"], None),   # one stray の in four
    (["上層部に報告する。", "毎日勉強する。", "確認した。"], "ja"),                              # kana in every note
    (["上層部に報告する。", "毎日勉強する。", "確認"], "ja"),                                     # two in three
    ([], None),
])
def test_a_note_type_is_japanese_when_most_of_its_notes_hold_kana(sentences, language):
    # D7, read by counting: a Chinese deck with one stray の or ツ stays Chinese; a Japanese one,
    # Lapis-like, has kana nearly everywhere. Few kana notes ask "Language?" — nothing is written wrong.
    assert backfill.note_language("Vocab", _with_fields(*sentences), {}) == language


def test_a_chinese_foreign_names_middle_dot_is_no_kana():
    # Chinese writes a foreign name with ・ (约翰・列侬) — U+30FB, inside the kana block but no kana letter.
    # Read as kana, one such note made an unset Chinese note type Japanese, and a Japanese session planned
    # Japanese lines onto Chinese cards (found by the 2.3 pre-build scan, 2026-09-25). It stays "Language?".
    fake = _fake(_zh(0, "歌手", "gēshǒu", "约翰・列侬是一位歌手。"), _zh(1, "必要", "bìyào", "没有必要这样做。"))
    for language in ("ja", "zh"):
        result = _plan(fake, language, junban_backfill_note_languages={})
        assert result["edits"] == {} and result["counts"] == {"language not set": 2}, language


def test_every_chinese_kana_test_reads_the_same_kana_letters():
    # Backfill's note-type and word guards (S3, S4), the パターン zh lookup and the ChineseTokenizer's filter tell
    # Japanese from Chinese by kana — one definition (app/unicode_ranges.KANA_LETTERS), so ・ can never be kana
    # to one and punctuation to another, as it was to patterns_zh after the 2.3 fix.
    from app import analyzer
    from modules.junban import patterns_zh
    for ch in "あアゝヽㇰ・ー゠":
        answers = {bool(backfill._KANA.search(ch)), bool(patterns_zh._KANA.search(ch)),
                   bool(analyzer._KANA_LETTER_RE.search(ch))}
        assert len(answers) == 1, ch
    assert backfill._KANA.search("ゝ") and not backfill._KANA.search("约翰・列侬")


def test_the_plan_checks_each_notes_language_again():
    # A second guard behind `gather`'s: a scope read for Japanese and planned by a Chinese session (a
    # language switched between the two) writes nothing on Lapis.
    fake = _both()
    settings = _settings("ja")
    with _patched(fake):
        scope = backfill.gather(URL, settings)
    result = backfill.plan(scope, _Session("zh"), _settings("zh"))
    assert result["edits"] == {} and result["counts"] == {"language": 3}


def test_a_word_with_kana_is_never_filled_from_chinese_data():
    # S4: a note type set to Chinese holding one Japanese card (勉強する): kana — never looked up in Chinese.
    fake = _fake(_zh(0, "问题", "wèntí", "这个问题很难。"), _zh(1, "勉強する", "", "毎日勉強する。"))
    result = _plan(fake, "zh")
    assert set(result["edits"]) == {FIRST_NOTE + 700}
    assert result["counts"] == {"fill": 1, "language": 1}


def test_one_deck_holding_both_languages_previews_only_the_session_language():
    fake = _both(deck="Mixed")
    with _patched(fake):
        zh = backfill.preview(_settings("zh", junban_backfill_deck="Mixed"), _Session("zh"))
        ja = backfill.preview(_settings("ja", junban_backfill_deck="Mixed"), _Session("ja"))
    assert {row[0] for row in zh["rows"]} == CHINESE_IDS and {row[0] for row in ja["rows"]} == LAPIS_IDS
    assert backfill.summary(zh) == "Fill 3 notes" and backfill.summary(ja) == "Fill 3 notes"


def test_a_traditional_card_meets_a_simplified_known_word():
    # S7: 學習 on a card, 学习 known, the user's script Simplified — the card's word is converted first.
    folder = get_user_files_path("zh")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": "学习", "knownStatus": "KNOWN"}]}, f, ensure_ascii=False)
    is_known = reposition.known_test("zh", {"target_language": "zh", "zh_script": "s"})
    assert is_known("學習") and is_known("学习") and not is_known("问题")


def test_a_chinese_card_gets_its_sentences_by_the_token_stores_own_key():
    # 例文 on a Traditional card (學習) in a library read as Simplified: the word is looked up as the token
    # store keys it — 学习 — the sentences come back with the word in bold, and a phrase card (打电话给朋友)
    # goes by its run of words, as Japanese does.
    found = {("学习", ""): [(0, "我每天都学习中文。", "学习", 0), (0, "学习是一件快乐的事。", "学习", 1)],
             "打电话给朋友": [(0, "我晚上打电话给朋友。", "打电话给朋友", 2)]}
    calls = []

    def best_for(language, wanted, progress=None, young=None, phrases=None, prefer=None):
        calls.append((language, set(wanted), dict(phrases or {})))
        return {key: found[key] for key in list(wanted) + list(phrases or {}) if key in found}
    fake = _fake(_zh(0, "學習", "xuéxí", "他在學校學習。"), _zh(1, "打电话给朋友", "", "周末你想做什么？"))
    settings = _settings("zh", zh_script="s", junban_backfill_fills=["sentence"])
    session = backfill.Session(settings)
    try:
        with _patched(fake), mock.patch("app.sentence_corpus.best_for", side_effect=best_for):
            result = backfill.plan(backfill.gather(URL, settings), session, settings)
    finally:
        session.close()
    assert calls == [("zh", {("学习", "")}, {"打电话给朋友": ("打电话", "给", "朋友")})]
    written = {row[1]: row[4] for row in result["rows"] if row[3] == "fill"}
    assert written == {"學習": "我每天都<b>学习</b>中文。<br><b>学习</b>是一件快乐的事。",
                       "打电话给朋友": "我晚上<b>打电话给朋友</b>。"}


# --- S1, S2: databases -------------------------------------------------------------------------- #
def _db(language, name=None, meta_language=None, folder=None):
    """A real, tiny パターン database — in the data folder unless `folder` says where."""
    path = pb.default_db_path(language, name) if folder is None else \
        os.path.join(folder, f"patterns_{language}{'_' + name if name else ''}.db")
    word = "问题" if language == "zh" else "問題"
    pb.write_rows(path, [(word, "", word, "n", 40)], [(word, word, "", 40)], [],
                  {"floor": 1, "tokens": 40, "language": meta_language or language})
    return path


def test_both_languages_databases_side_by_side_open_only_their_own():
    for language in ("ja", "zh"):
        for name in (None, "shared"):
            _db(language, name)
    for language in ("ja", "zh"):
        opened = patterns.open_sources(language)
        try:
            found = {name: store.meta()["language"] for name, store in opened if store is not None}
        finally:
            for _name, store in opened:
                if store is not None:
                    store.close()
        assert found == {"library": language, "shared": language}


def test_the_data_a_window_offers_is_the_languages_own():
    # Japanese data on this computer is no Chinese data: "Get data…" and "Build & preview" stay offered.
    _db("ja")
    _db("ja", "shared")
    assert backfill.data_ready("ja") and backfill.general_ready("ja")
    assert not backfill.data_ready("zh") and not backfill.general_ready("zh")
    _db("zh", "shared")
    assert backfill.general_ready("zh")


def test_a_database_whose_meta_names_another_language_is_refused():
    # A Chinese file name holding Japanese rows is never read for Chinese cards; a file whose meta names
    # no language is taken at its name, as every Japanese file before the key was.
    _db("zh", meta_language="ja")
    assert open_store(language="zh") is None
    assert dict(patterns.open_sources("zh"))["library"] is None
    store = open_store(language="ja", name=None)
    assert store is None                                # no Japanese library built here
    path = pb.default_db_path("zh", "shared")
    pb.write_rows(path, [("问题", "", "问题", "n", 40)], [], [], {"floor": 1, "tokens": 40})
    store = open_store(language="zh", name="shared")
    assert store is not None
    store.close()


# --- S6, S8: snapshots and the automatic run ---------------------------------------------------- #
def test_a_chinese_fill_and_a_japanese_fill_keep_separate_snapshots_and_restores():
    fake = _both()
    with _patched(fake):
        ja = backfill.run(_settings("ja"), _Session("ja"))
        zh = backfill.run(_settings("zh"), _Session("zh"))
    assert set(ja["written"]) == LAPIS_IDS and set(zh["written"]) == CHINESE_IDS
    assert set(undo.load("ja", kind="backfill")["fields"]) == {str(i) for i in LAPIS_IDS}
    assert set(undo.load("zh", kind="backfill")["fields"]) == {str(i) for i in CHINESE_IDS}
    with _patched(fake):
        report = backfill.restore(_settings("zh"))
    assert set(report["written"]) == CHINESE_IDS
    assert all(fake.notes[i]["fields"]["Patterns"]["value"] == "" for i in CHINESE_IDS)
    assert all(fake.notes[i]["fields"]["Patterns"]["value"].startswith('<div class="pat-colloc">ja: ')
               for i in LAPIS_IDS)


def test_the_automatic_run_fills_only_the_dashboards_language(monkeypatch):
    monkeypatch.setattr(backfill, "Session", lambda settings: _Session(settings["target_language"]))
    for language, ids in (("ja", LAPIS_IDS), ("zh", CHINESE_IDS)):
        fake = _both()
        with _patched(fake):
            report = backfill.run_auto(_settings(language))
        assert report["ok"] and {note for note, _fields in fake.note_writes} == ids, language


# --- S9: the build ------------------------------------------------------------------------------ #
def test_build_and_preview_builds_the_language_on_screen():
    argv, _env, _cwd = backfill.rebuild_command()
    assert argv[-1] == "modules.junban.patterns_build"          # Japanese: today's command line
    assert backfill.rebuild_command("ja", reinforce=True)[0] == argv
    assert backfill.rebuild_command("zh")[0][-2:] == ["--language", "zh"]
    assert backfill.rebuild_command("zh", reinforce=True)[0][-3:] == ["--language", "zh", "--reinforce"]


# --- S10: packages ------------------------------------------------------------------------------ #
def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _package(tmp_path, language, manifest_language=None):
    folder = tmp_path / f"src_{language}"
    folder.mkdir(exist_ok=True)
    source = _db(language, "shared", folder=str(folder))
    return pp.pack([source], str(tmp_path / f"patterns_{language}_shared.zip"), kind="shared",
                   language=manifest_language or language)


@pytest.mark.parametrize("installed, arriving", [("ja", "zh"), ("zh", "ja")])
def test_a_package_of_one_language_installs_beside_the_other_and_never_replaces_it(tmp_path, installed, arriving):
    there = _db(installed, "shared")
    before = _sha(there)
    assert pp.install(_package(tmp_path, arriving)) == [f"patterns_{arriving}_shared.db"]
    assert _sha(there) == before and os.path.exists(pb.default_db_path(arriving, "shared"))


def test_a_package_whose_files_name_another_language_than_its_manifest_is_refused(tmp_path):
    package = _package(tmp_path, "ja", manifest_language="zh")      # a Japanese file, a Chinese manifest
    with pytest.raises(pp.PackageError, match="mixes languages"):
        pp.install(package)
    assert not os.path.exists(pb.default_db_path("ja", "shared"))
    assert not [n for n in os.listdir(os.path.dirname(pb.default_db_path("ja"))) if n.endswith(".part")]


def test_the_japanese_shared_pins_are_unchanged():
    # §13: Chinese shared data is added beside Japanese's, never instead — v5 (builder 9, 2.4's word rules),
    # commit c923aa1, 32 MB.
    assert pp.shared_for("ja") == {
        "url": "https://raw.githubusercontent.com/SonicSandbox/surasura/c923aa14ff4fabd4adc8cb02349adc8e712fadfc"
               "/release_assets/patterns/patterns_ja_shared.zip",
        "sha256": "3013f1fe61e9c142f42d00e1300af73b6ab11a24b6804225c477772dd14509bd", "mb": 32,
        "credit": "RealPersonaChat, Aozora Bunko, Wikipedia and Leipzig Corpora Collection news (CC BY-SA 4.0)"}
    assert "ja" not in pp.SHARED


def test_the_chinese_shared_download_is_pinned_to_a_commit():
    # WP-Z8: the file at the commit that added it, checked by its sha256 — never a branch that moves. Pinned
    # exactly, as Japanese's is: v3 (builder 3, 2.4's Chinese cut), commit c923aa1, 10 MB — a test that took any
    # commit let a wrong pin through (the sweep, 2026-09-25).
    shared = pp.shared_for("zh")
    assert re.fullmatch(r"https://raw\.githubusercontent\.com/SonicSandbox/surasura/[0-9a-f]{40}"
                        r"/release_assets/patterns/patterns_zh_shared\.zip", shared["url"])
    assert shared == {
        "url": "https://raw.githubusercontent.com/SonicSandbox/surasura/c923aa14ff4fabd4adc8cb02349adc8e712fadfc"
               "/release_assets/patterns/patterns_zh_shared.zip",
        "sha256": "bf49ff3992cb8a79c800a782302e97b8495c935f0efdaeba43110e3d29784568", "mb": 10,
        "credit": "Tatoeba, KdConv, Wikipedia, Wikinews and Leipzig Corpora Collection news (CC BY-SA 4.0)"}


def test_the_shared_download_refuses_the_other_languages_package(tmp_path, monkeypatch):
    with mock.patch.object(pp, "SHARED", {}):
        with pytest.raises(pp.PackageError, match="no shared"):
            pp.get_shared(language="zh")
    package = _package(tmp_path, "ja")                              # published as Chinese by mistake
    monkeypatch.setitem(pp.SHARED, "zh", {"url": "https://example.invalid/patterns_zh_shared.zip",
                                          "sha256": pp._sha256(package), "mb": 1, "credit": "—"})

    def fake_download(url, dest, progress_cb=None, timeout=60):
        with open(package, "rb") as src, open(dest, "wb") as out:
            out.write(src.read())
        return dest
    with mock.patch("app.updater.download", side_effect=fake_download):
        with pytest.raises(pp.PackageError, match="another language"):
            pp.get_shared(language="zh")
    assert not os.path.exists(pb.default_db_path("ja", "shared"))


# --- S5, S11, S12: the window ------------------------------------------------------------------- #
class _StubSession:
    def close(self):
        pass


class TestTheWindowFollowsTheLanguage(BackfillGuiTestCase):
    def _host(self, language):
        host = mock.Mock(spec=["root", "backfill_window", "var_language"])
        host.root = self.root
        host.var_language = tk.StringVar(self.root, value=language)
        return host

    def test_switching_the_dashboard_language_rebuilds_the_session_and_the_window(self):
        host = self._host("ja")
        window = self._window(app=host)
        window._show_preview(_result(), window._key())
        self.assertEqual(str(window.btn_fill["state"]), tk.NORMAL)
        check, _tip = window._checks["patterns"]
        host.var_language.set("zh")
        window._on_focus()
        # The Japanese preview is gone and confirms nothing; the fill is Chinese's now — its "?" in
        # Chinese terms, its data Chinese's (and a language with none says so).
        self.assertEqual(window.tree.get_children(), ())
        self.assertEqual(str(window.btn_fill["state"]), tk.DISABLED)
        self.assertNotIn("disabled", check.state())
        self.assertEqual(window.help_tips["patterns"].content()[1][0][0], "Measure words")
        with mock.patch.object(backfill, "general_ready", return_value=False):
            window._sync_buttons()
            self.assertEqual(window.btn_get_data.winfo_manager(), "pack")
            window.on_get_data()
            self.assertIn("shared Chinese data: 10 MB", window._data_dialog.info.cget("text"))
            self.assertNotIn("disabled", window._data_dialog.btn_download.state())
            window._data_dialog.destroy()
            with mock.patch.object(pp, "SHARED", {}):
                window.on_get_data()
                self.assertIn("no shared Chinese data yet", window._data_dialog.info.cget("text"))
                self.assertIn("disabled", window._data_dialog.btn_download.state())
        # A fill one language lacks follows the language on screen, read afresh on every sync.
        sentence = backfill.FILLS[1]._replace(languages=("ja",))
        with mock.patch.object(backfill, "FILLS", (backfill.FILLS[0], sentence)):
            window._sync_buttons()
            box, box_tip = window._checks["sentence"]
            self.assertIn("disabled", box.state())
            self.assertEqual(box_tip.text, "Not for this language yet.")
            host.var_language.set("ja")
            window._sync_buttons()
            self.assertNotIn("disabled", box.state())
        made = []
        with mock.patch.object(backfill, "Session",
                               side_effect=lambda s: made.append(s["target_language"]) or _StubSession()):
            host.var_language.set("zh")
            window._session_for(window._settings())
            host.var_language.set("ja")
            window._session_for(window._settings())
            window._session_for(window._settings())
        self.assertEqual(made, ["zh", "ja"])
        self.assertEqual(window.help_tips["patterns"].content()[1][0][0], "Particles")

    def test_the_window_builds_the_language_on_screen(self):
        self.saved["target_language"] = "zh"
        self.ready = False
        with mock.patch.object(backfill, "start_rebuild", return_value=_Process([], code=0)) as start:
            window = self._window()
            self._inline(window)
            window.on_preview()
        start.assert_called_once_with("zh", False)

    def test_the_fields_window_sets_a_note_types_language(self):
        window = self._window()
        models = {"Lapis": {"fields": LAPIS, "count": 3, "mapped": {"patterns": "Patterns"}, "language": "ja"},
                  "Chinese Vocab": {"fields": CHINESE, "count": 2, "mapped": {"patterns": "Patterns"},
                                    "language": None}}
        window._show_preview(_result(models), window._key())
        window.on_fields(backfill.FILLS[0])
        dialog = window._fields_dialog
        self.assertEqual(dialog.language_vars["Lapis"].get(), "Japanese")
        self.assertEqual(dialog.language_vars["Chinese Vocab"].get(), backfill_gui.UNSET_LABEL)
        picks = {str(w.cget("textvariable")): w for w in self._walk(dialog) if isinstance(w, ttk.Combobox)}
        pick = picks[str(dialog.language_vars["Chinese Vocab"])]
        dialog.language_vars["Chinese Vocab"].set("Chinese")
        pick.event_generate("<<ComboboxSelected>>")
        self.assertEqual(self.saved["junban_backfill_note_languages"], {"Chinese Vocab": "zh"})
        self.assertIsNot(self.saved["junban_backfill_note_languages"],
                         junban.SETTINGS_DEFAULTS["junban_backfill_note_languages"])
        self.assertEqual(window._preview_key, None)            # a new language, a new preview
        dialog.language_vars["Chinese Vocab"].set(backfill_gui.UNSET_LABEL)
        pick.event_generate("<<ComboboxSelected>>")
        self.assertEqual(self.saved["junban_backfill_note_languages"], {})


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()
