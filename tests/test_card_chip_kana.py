"""The ✓ chip counts a card written in kana alone as the word its own sentence says (Kyou-KN, 2026-11-20).

Sonic asked why a kana card for a kanji word never counted on the chip: the chip took a card's word as a lemma exactly,
and a word written in kana is no lemma (UniDic files てつだう under 手伝う; read alone, まく is 膜). Junban's known
test now reads such a card in its own sentence (`anki_match.card_word_in_sentence`), and the chip reads it the same
way — one rule, never a second test: a てつだう card whose sentence says 手伝ってくれない counts for 手伝う. With no
sentence that places it, it counts by its letters, as before. Each card and sentence is read once and kept on disk,
so a window opened with Anki closed keeps the count and loads no tagger for cards it has read.

What a wrong answer costs: an episode that looks barely carded though its words have cards (the report), or a card
counted for a word it isn't. On the real Japanese test episode, tokenized into a real token store.
"""
import json
import os

import pytest

from app import anki_sync, anki_words
from app.services import card_chip
from tests.test_card_chip import Lib, _settle, _tokenized

HELP = "てつだう"
HELP_SAID = "文化祭の準備、<b>てつだって</b>くれない？"      # placed_episode.srt's line 4, the word in kana


@pytest.fixture(scope="module")
def _ja(tmp_path_factory):
    made = []

    def get():          # built inside a test, once its own data root is set (conftest's autouse root)
        if not made:
            made.append(_tokenized(str(tmp_path_factory.mktemp("chip-kana")), "ja"))
        return made[0]
    return get


@pytest.fixture
def lib(tmp_path, _ja):
    lib = Lib(str(tmp_path), "ja", _ja())
    assert "手伝う" in lib.words[1] and HELP not in lib.words[1], "the episode says 手伝う, never the kana as a lemma"
    return lib


def _count(lib, chips, step=1):
    """One ask of the four episodes (`step`: a new ask, as the reader's next build makes one) -> the answers."""
    chips.want(lib.ask([1, 2, 3, 4], cards=step))
    _settle(chips)
    return chips.answers()


def test_a_kana_cards_word_counts_as_the_word_its_sentence_says(lib):
    # the backlog's new てつだう card: by its letters alone it counts nowhere; with its sentence it is 手伝う, a word
    # of episode 1
    chips = lib.chips()
    try:
        lib.backlog = {HELP}
        alone = _count(lib, chips)
        lib.backlog, lib.stamp[0] = {HELP, (HELP, HELP_SAID)}, 1
        said = _count(lib, chips, 2)
    finally:
        chips.close()
    assert said[1] == alone[1] + 1
    assert all(said[i] == alone[i] + ("手伝う" in lib.words[i]) for i in (1, 2, 3, 4))


def test_a_studied_kana_card_counts_by_its_sentence_too(lib):
    # the word card's read hands on {word: Standing}; a kana card's Standing carries its sentence
    chips = lib.chips()
    try:
        before = _count(lib, chips)
        chips.studied({HELP: anki_words.Standing(1, sentence=HELP_SAID), "走る": anki_words.Standing(2)})
        after = _count(lib, chips)
    finally:
        chips.close()
    assert after[1] == before[1] + 1 + ("走る" in lib.words[1])


def test_a_kana_card_with_no_sentence_that_places_it_counts_by_its_letters_alone(lib):
    chips = lib.chips()
    try:
        before = _count(lib, chips)
        lib.backlog, lib.stamp[0] = {HELP, (HELP, "今日はいい天気だ。")}, 1
        after = _count(lib, chips, 2)
    finally:
        chips.close()
    assert after == before, "the sentence doesn't hold the word: no guess"


def test_a_window_opened_with_anki_closed_keeps_the_count_and_reads_no_card_again(lib):
    # the studied cards' read words are kept on disk, and every card read once: the next open makes no tagger for it
    chips = lib.chips()
    try:
        chips.studied({HELP: anki_words.Standing(1, sentence=HELP_SAID)})
        first = _count(lib, chips)
    finally:
        chips.close()
    assert chips.idle(10), "its last save done before the next open reads it (as the chip's own Anki-closed test)"
    with open(lib.cache, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["studied_read"] == ["手伝う"] and [HELP, HELP_SAID, "手伝う"] in saved["reads"]

    def no_tagger(_text):
        raise AssertionError("a card read before was read again")
    again = card_chip.Chips("ja", open_tokens=chips._open_tokens, data_dir=lib.data, read_made=lambda _l, ids: {},
                            read_backlog=lambda _l: set(), backlog_stamp=lambda _l: 0, cache_file=lib.cache,
                            tokenize=no_tagger)
    try:
        assert _count(lib, again)[1] == first[1], "Anki closed: the kana card still counts"
        again.studied({HELP: anki_words.Standing(1, sentence=HELP_SAID)})
        assert _count(lib, again)[1] == first[1]
    finally:
        again.close()


def test_the_sync_keeps_a_kana_cards_sentence_and_nothing_for_any_other(tmp_path):
    # anki_backlog.json's entry and the studied read's Standing carry the sentence the chip reads the card in
    def note(word, sentence):
        return {"noteId": 1, "fields": {"Expression": {"value": word, "order": 0},
                                        "Sentence": {"value": sentence, "order": 1}}}
    kana = anki_sync._backlog_entry(note(HELP, HELP_SAID), ["Expression"], "ja")
    kanji = anki_sync._backlog_entry(note("手伝う", "準備を<b>手伝う</b>。"), ["Expression"], "ja")
    assert kana["sentence"] == HELP_SAID and "sentence" not in kanji
    assert "sentence" not in anki_sync._backlog_entry(note(HELP, "  "), ["Expression"], "ja")
    assert anki_sync._note_sentence(note("学习", "我们一起学习。"), "学习", "zh") == ""
    assert anki_sync.BACKLOG_VERSION == 4, "a backlog saved before is read again once, its kana cards' sentences in"


def test_with_no_tagger_a_kana_card_counts_by_its_letters_and_the_chip_still_counts(lib):
    # the tagger can't be made (fugashi missing, a broken dictionary): never a chip that stops counting
    def broken(_text):
        raise OSError("no dictionary")
    from app import token_index as ti
    chips = card_chip.Chips("ja", open_tokens=lambda: ti.open_reader("ja", lib.db), data_dir=lib.data,
                            read_made=lambda _l, ids: {}, read_backlog=lambda _l: {"走る", (HELP, HELP_SAID)},
                            backlog_stamp=lambda _l: 0, cache_file=lib.cache, tokenize=broken)
    try:
        got = _count(lib, chips)
    finally:
        chips.close()
    assert chips.idle(10)
    assert got[1] == ("走る" in lib.words[1]), "the rest counted; the kana card by its letters"
    with open(lib.cache, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["reads"] == [], "nothing kept for a card not read: read again once a tagger is there"
