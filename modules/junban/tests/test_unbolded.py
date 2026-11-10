# SPDX-License-Identifier: GPL-3.0-or-later
"""A sentence with no bold word (P1.4 row 1.4.5; K56: "Junban can't place a card whose sentence has no bold mark, so a
conjugated form stays in the last group forever. Bold is off by default in Anki Miner").

With the Connect preview on, Junban finds the card's word in its sentence by its forms when there is no `<b>` mark and
the word isn't there as written: 走る in 走った, 持つ in 持っています (with its endings, as a mark covers them), 感じる
in 感じます (UniDic's 感ずる), a Simplified card's word in a Traditional sentence. Two different words that could each be
it are never guessed between: the card stays where its sentence can't place it, and the preview names it.

The proof on real cards: `tests/Test Resources/ja/testAnki.apkg` holds 200 sentences marked the way Anki Miner marks
them. With each mark taken off, the word found by its forms must leave Junban the same count of unknown words beside
the card as the mark did — every sentence but the two whose mark sits on another word than the card's (a deck's own
slip: <b>未だ</b> on a 終わる card).

Backfill reads a card's word from its word field and compares whole sentences (例文), so no Backfill step looks for the
word inside a sentence: the fallback has no Backfill call site (as-built note, RUNBOOK P1.4).
"""
import os
import re
import sqlite3
import zipfile

import pytest

from app import anki_match
from modules.junban import connect, reposition
from modules.junban.tests.connect_scene import scene, settings, without_connect
from modules.junban.tests.test_reposition import _ROOT, _patched

_APKG = os.path.join(_ROOT, "tests", "Test Resources", "ja", "testAnki.apkg")
_ZH_NEWS = os.path.join(_ROOT, "tests", "Test Resources", "zh", "traditional_news.txt")


@pytest.fixture(scope="module")
def tokenizer():
    from app import analyzer
    analyzer.SANITIZE_JA = True
    return analyzer.JapaneseTokenizer()


@pytest.fixture(scope="module")
def marked_cards(tmp_path_factory):
    """(card word, its sentence with Anki Miner's <b> mark) for every marked sentence note in the real deck."""
    folder = tmp_path_factory.mktemp("apkg")
    with zipfile.ZipFile(_APKG) as package:
        package.extract("collection.anki2", str(folder))
    con = sqlite3.connect(str(folder / "collection.anki2"))
    try:
        rows = con.execute("SELECT flds FROM notes ORDER BY id").fetchall()
    finally:
        con.close()
    cards = []
    for (flds,) in rows:
        fields = flds.split("\x1f")
        if "<b>" in fields[0] and " -- " in fields[1]:
            cards.append((fields[1].split("<br />")[-1].split(" -- ")[0].strip(), fields[0]))
    assert len(cards) == 200, "the fixture deck's marked sentences"
    return cards


def test_on_200_real_cards_the_word_found_by_its_forms_counts_what_the_mark_counted(tokenizer, marked_cards):
    from modules.junban.reposition import _learning, _skip
    known = (set(), {"私", "彼", "彼女", "今", "家", "会社", "毎朝"}, set())
    word_unknown, units, _view = _learning("ja", known, None, tokenizer.tagger, True)
    skip = _skip("ja", True)

    def unknown(token):
        return word_unknown(token[0], token[1], token[2])

    found, differ = 0, []
    for word, raw in marked_cards:
        plain = re.sub(r"</?b>", "", raw)
        if anki_match.sentence_span(plain, word) is not None:
            continue                                    # there as written: nothing for the fallback to do
        got = connect.find_by_forms(plain, word, tokenizer.tokenize, "ja", tokenizer.tagger)
        assert got not in (None, connect.UNSURE), f"{word}: not found in {plain}"
        found += 1
        marked = anki_match.unknowns_beside(word, raw, tokenizer.tokenize, unknown, units, skip)
        ours = anki_match.unknowns_beside(word, connect.bolded(got), tokenizer.tokenize, unknown, units, skip)
        if marked != ours:
            differ.append((word, raw))
    assert found == 72
    # Only where the deck marked another word than the card's.
    assert differ == [("終わる", "宿題は<b>未だ</b>終わっていません。"), ("分かる", "この<b>言葉</b>の意味が分かりません。")]


@pytest.mark.parametrize("sentence, word, span", [
    ("毎朝公園まで走った。", "走る", "走った"),                          # conjugated: found with its ending
    ("私は車を持っています。", "持つ", "持っています"),                  # 〜ている + ます, as a mark covers them
    ("テストを始めてください。", "始める", "始めて"),                    # never 〜てください (the marks leave it out)
    ("膝に痛みを感じます。", "感じる", "感じます"),                      # UniDic's 感ずる
    ("お金をかけて、時間をかけた。", "かける", "かけて"),                # one word said twice: the first time
])
def test_a_conjugated_word_is_found_with_its_endings(tokenizer, sentence, word, span):
    text, start, end = connect.find_by_forms(sentence, word, tokenizer.tokenize, "ja", tokenizer.tagger)
    assert text[start:end] == span


def test_two_different_words_that_could_each_be_it_are_never_guessed_between(tokenizer):
    """A kana card かける in a sentence holding 欠ける and 掛ける: no guess."""
    assert connect.find_by_forms("皿が欠けて、壁に絵を掛けた。", "かける", tokenizer.tokenize, "ja",
                                 tokenizer.tagger) == connect.UNSURE


def test_a_mark_or_the_word_as_written_is_left_to_anki_match(tokenizer):
    assert connect.find_by_forms("毎朝<b>散歩</b>に出かける。", "散歩", tokenizer.tokenize, "ja") is None
    assert connect.find_by_forms("図書館で本を読んだ。", "図書館", tokenizer.tokenize, "ja") is None
    assert connect.find_by_forms("", "走る", tokenizer.tokenize, "ja") is None
    assert connect.find_by_forms("毎朝公園まで走った。", "走る", None, "ja") is None


def test_a_simplified_card_finds_its_word_in_a_traditional_sentence():
    """Chinese, from a real Traditional news text: a 学习 card (Simplified) in 持續學習新技術."""
    from app import analyzer
    with open(_ZH_NEWS, "r", encoding="utf-8") as handle:
        sentence = next(line.strip() for line in handle if "學習" in line)
    cut = analyzer.ChineseTokenizer(script="asis").tokenize
    text, start, end = connect.find_by_forms(sentence, "学习", cut, "zh")
    assert text[start:end] == "學習"
    assert connect.find_by_forms(sentence, "學習", cut, "zh") is None      # there as written


def test_with_the_preview_on_junban_places_the_unbolded_card_by_its_sentence(tmp_path):
    """The scene's 走る (毎朝公園まで走った。 — 毎朝 and 公園 known) waits with "the rest" without a mark; found by its
    forms, its sentence places it: one unknown beside it (まで), never its own 走っ or た. The note's field is never
    changed."""
    def tier_of(preview):
        fake = scene(tmp_path, without_connect())   # no card of Connect's: 走る isn't "yours", its sentence places it
        with _patched(fake):
            _writes, stats = reposition.dry_run(settings(preview=preview))
        return next(row for row in stats["order"] if row.word == "走る").why, fake

    off, _fake = tier_of(False)
    on, fake = tier_of(True)
    assert off.startswith("FreqSort") and on == "1 unknown"
    assert fake.notes[fake.card_of("走る")["note"]]["fields"]["Sentence"]["value"] == "毎朝公園まで走った。"


def test_an_unsure_card_stays_unplaced_and_the_preview_names_it(tmp_path):
    entries = [("冒険", "冒険が始まった。", 2000, [], 0),
               ("かける", "皿が欠けて、壁に絵を掛けた。", 4000, [], 0)]
    fake = scene(tmp_path, entries)
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings())
    row = next(row for row in stats["order"] if row.word == "かける")
    assert row.tier == "rest" and row.why == connect.UNSURE
    assert stats["unsure"] == ["かける"]
