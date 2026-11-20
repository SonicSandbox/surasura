# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-KN (3.0.18): Junban's known test reads a card written in kana alone in its own sentence, as Generate does.

A tester's まく and まみれ cards went to the back of 順's queue as "known" while the journey still wanted the word their
sentences say: read alone, まく is 膜 'membrane' and まみれ 塗れる, and a known entry written in kana puts the bare
string on the known list too — but in 庭に水をまく the word is 撒く 'sprinkle', in 泥まみれ 泥塗れ, and Generate counts
those. Junban and Backfill now ask the sentence: the card is known when Generate would count the sentence's word known.
With no sentence, or one that doesn't hold the word, the letters and the lone reading still decide (D3: known first).

What a wrong answer costs: a card the learner still needs filed as known (never studied in its turn), or a card they
know put back in front of them. Real Japanese on Lapis fields, the analyzer's own tokenizer; never a live Anki.
"""
import os

from modules.junban import backfill, reposition
from modules.junban.tests.test_backfill import _fake, _lapis
from modules.junban.tests.test_backfill import _plan as _fill_plan
from modules.junban.tests.test_reposition import _known, _mined, _patched, _results, _settings

SPRINKLE = "庭に水を<b>まく</b>。"           # UniDic: 撒く マク (alone, まく is 膜)
SPRINKLED = "毎朝、庭に水をまいた。"          # no bold mark, conjugated: found by its forms (K56) — 撒い
MUDDY = "服が泥<b>まみれ</b>になった。"        # 泥塗れ, one word (alone, まみれ is 塗れる)


def _library(tmp_path):
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})


def test_a_kana_card_known_only_by_its_letters_is_not_known_in_a_sentence_that_says_another_word(tmp_path):
    # the tester's case: a known まく (its raw dictForm, and 膜 read alone) says nothing of the 撒く a sentence asks for
    _library(tmp_path)
    _known(tmp_path, ["まく", "まみれ"])
    is_known = reposition.known_test("ja", _settings())
    assert not is_known("まく", SPRINKLE)
    assert not is_known("まく", SPRINKLED), "no bold, conjugated: still read in the sentence"
    assert not is_known("まみれ", MUDDY)
    # …while the same cards with no sentence keep the letters' answer (the card's rule since 2026-09-27)
    assert is_known("まく") and is_known("まく", "") and is_known("まみれ", None)


def test_a_kana_card_whose_sentence_word_is_known_is_known(tmp_path):
    _library(tmp_path)
    _known(tmp_path, ["撒く"])
    is_known = reposition.known_test("ja", _settings())
    assert is_known("まく", SPRINKLE) and is_known("まく", SPRINKLED)
    assert not is_known("まく"), "alone it is 膜, which the learner never said they knew"


def test_a_sentence_that_does_not_hold_the_word_leaves_the_lone_reading(tmp_path):
    # a sentence about something else (a card's field filled by hand) places nothing: the letters decide, as before
    _library(tmp_path)
    _known(tmp_path, ["まく"])
    is_known = reposition.known_test("ja", _settings())
    assert is_known("まく", "今日はいい天気だ。")


def test_with_no_bold_mark_the_word_is_the_token_that_is_it_never_the_word_its_letters_start(tmp_path):
    # まくらを庭にまく: the first まく written is the start of 枕 'pillow' — the card's word is the 撒く said after it
    _library(tmp_path)
    _known(tmp_path, ["枕"])
    is_known = reposition.known_test("ja", _settings())
    assert not is_known("まく", "まくらを庭にまく。")
    _known(tmp_path, ["撒く"])
    assert reposition.known_test("ja", _settings())("まく", "まくらを庭にまく。")
    # …and a bold mark wider than the word still finds it inside (Yomitan marks a phrase now and then)
    assert reposition.known_test("ja", _settings())("まく", "<b>庭に水をまく</b>。")


def test_a_bold_mark_on_another_word_is_read_as_no_mark(tmp_path):
    # a mark the learner (or a miner) put on another word says nothing of where this card's word is: 庭 known, the
    # まく card in <b>庭</b>にまくらをまく is still the 撒く said there — and a second mark, on the word, still finds it
    _library(tmp_path)
    _known(tmp_path, ["庭", "水"])
    is_known = reposition.known_test("ja", _settings())
    assert not is_known("まく", "<b>庭</b>にまくらをまく。")
    assert not is_known("まく", "<b>水</b>をまく。")
    assert not is_known("まく", "<b>庭</b>に<b>まく</b>。")


def test_a_bold_mark_says_which_word_where_the_sentence_holds_two(tmp_path):
    # 鍵をかけて、皿が欠けた holds 掛ける and 欠ける: the mark on かけて says this card is 掛ける (known here)
    _library(tmp_path)
    _known(tmp_path, ["掛ける"])
    is_known = reposition.known_test("ja", _settings())
    assert is_known("かける", "鍵を<b>かけて</b>、皿が欠けた。")
    assert not is_known("かける", "鍵をかけて、皿が<b>欠けた</b>。"), "marked: 欠ける, not known"


def test_two_words_a_sentence_could_mean_are_never_guessed_between(tmp_path):
    # 鍵をかけて、皿が欠けた: 掛ける and 欠ける both read かける — the sentence can't say which the card is, so the
    # card is read as before (its letters: the learner's かける entry makes it known)
    _library(tmp_path)
    _known(tmp_path, ["かける"])
    assert reposition.known_test("ja", _settings())("かける", "鍵をかけて、皿が欠けた。")


def test_an_ignore_line_holding_the_cards_own_word_still_files_it_known(tmp_path):
    # the learner's own line for that very word (an ignore line is never a tokenizer's guess): known, in any sentence
    _library(tmp_path)
    _known(tmp_path, ["無関係"])
    with open(os.path.join(str(tmp_path), "User Files", "ja", "IgnoreList.txt"), "w", encoding="utf-8") as handle:
        handle.write("まみれ\n")
    assert reposition.known_test("ja", _settings())("まみれ", MUDDY)


def test_a_card_known_as_itself_stays_known_where_its_sentence_reads_another_word(tmp_path):
    # ことに 'especially' (殊に) known as itself: 今年はことに暑い reads 事 + に, a word the dictionary keeps apart — the
    # card is judged as itself, as with no sentence
    _library(tmp_path)
    _known(tmp_path, ["ことに"])
    assert reposition.known_test("ja", _settings())("ことに", "今年は<b>ことに</b>暑い。")


def test_a_kana_card_the_dictionary_keeps_apart_from_its_sentence_word_is_not_known_through_it(tmp_path):
    # in 今年はことに暑い the tagger reads こと + に, but ことに is 殊に 'especially', an entry of its own: knowing 事
    # says nothing of it (word_of_its_own, as for the word alone) — where the dictionary files the two together, the
    # sentence's word decides: knowing 泥塗れ, a まみれ card in 泥まみれ is known (Generate counts that word known)
    _library(tmp_path)
    _known(tmp_path, ["事", "泥塗れ"])
    is_known = reposition.known_test("ja", _settings())
    assert not is_known("ことに", "今年は<b>ことに</b>暑い。")
    assert is_known("まみれ", MUDDY)


def test_a_kanji_card_and_a_single_kana_card_are_read_as_before(tmp_path):
    # only a word written in kana alone, two kana or more, is read in its sentence; 撒く is its own lemma anyway
    _library(tmp_path)
    _known(tmp_path, ["撒く", "か"])
    is_known = reposition.known_test("ja", _settings())
    assert is_known("撒く", "庭に水を<b>撒く</b>。") and is_known("撒く")
    assert is_known("か", "<b>か</b>")              # the bare string, as before (a particle card is no list word)


def test_junbans_known_tier_reads_each_card_in_its_own_sentence(tmp_path):
    # D3 (known first, for every card) with the sentence: the まく card in 水をまく is placed, the one with no sentence
    # is known — and Backfill's skip gives the same answers
    _library(tmp_path)
    _known(tmp_path, ["まく"])
    fake = _mined([("まく", SPRINKLE, 1000, ""), ("まく", "", 1001, ""), ("まみれ", MUDDY, 1002, "")])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    tiers = [(row.word, row.tier == "known") for row in stats["order"]]
    assert sorted(tiers) == [("まく", False), ("まく", True), ("まみれ", False)], tiers


def test_a_jobs_memo_keeps_each_sentences_answer_apart(tmp_path):
    # the fast re-plan's job keeps each card's "known?" answer while the files are unchanged: two まく cards, one in
    # 水をまく (撒く, known here) and one with no sentence (膜 alone, not known), never share one answer
    _library(tmp_path)
    _known(tmp_path, ["撒く"])
    memo = reposition._known_memo("ja", _settings())
    cards = [{"card_id": 1, "note": 1, "word": "まく"}, {"card_id": 2, "note": 2, "word": "まく"}]
    notes = {1: {"fields": {"Sentence": SPRINKLE}}, 2: {"fields": {"Sentence": ""}}}
    reposition._place_the_rest(cards, notes, "ja", _settings(), known_memo=memo)
    assert [card.get("tier") == "known" for card in cards] == [True, False]
    again = [{"card_id": 3, "note": 2, "word": "まく"}, {"card_id": 4, "note": 1, "word": "まく"}]
    reposition._place_the_rest(again, notes, "ja", _settings(), known_memo=memo)
    assert [card.get("tier") == "known" for card in again] == [False, True], "the memo answered by the word alone"


def test_backfill_skips_a_new_kana_card_only_when_its_sentence_word_is_known(tmp_path):
    # Backfill's known skip is Junban's test (`known_test`): a new まく card in 水をまく is filled, not skipped as known
    _library(tmp_path)
    _known(tmp_path, ["まく"])
    session = backfill.Session.__new__(backfill.Session)
    session.language = "ja"
    session.is_known = reposition.known_test("ja", _settings())
    session.prepare = lambda fill, notes, status=None, young=(): None
    session.value = lambda fill, note, field: ("<div>撒く</div>", None)
    sprinkle, card = _lapis(0, "まく", "まく")
    sprinkle["fields"]["Sentence"]["value"] = SPRINKLE
    alone, card2 = _lapis(1, "まく", "まく")
    alone["fields"]["Sentence"]["value"] = ""
    result = _fill_plan(_fake((sprinkle, card), (alone, card2)), session=session)
    assert result["counts"].get("known") == 1, result["counts"]
    assert list(result["edits"]) == [sprinkle["noteId"]]


def test_chinese_cards_are_untouched(tmp_path):
    # Chinese has no kana: its known test reads the word as before, a sentence or not (zh: exact keys, v1)
    folder = os.path.join(str(tmp_path), "User Files", "zh")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as handle:
        handle.write('{"words": [{"dictForm": "学习", "knownStatus": "KNOWN"}]}')
    is_known = reposition.known_test("zh", {"target_language": "zh", "zh_script": "s"})
    assert is_known("学习") and is_known("学习", "我们一起<b>学习</b>中文。") and is_known("學習", "他在學習。")
    assert not is_known("中文", "我们一起学习<b>中文</b>。")
