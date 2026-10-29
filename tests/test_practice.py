"""The practice checker (app/practice.py, H9): what the learner's AI writes is read as the list reads a library, and a
reply passes only by the rules Sonic set for its mode (P-1, 2026-10-28) — a chat reply brings in at most one new word,
in a sentence where every other word is known; a reading keeps new words under 3 %; a new word is one of the learner's
upcoming words or an easy common noun. Real Japanese and Chinese, the learner's known words built from real sentences
by the same tokenizer (or the real KnownWord.json in tests/Test Resources).
"""
import json
import os
import shutil

import pytest

from app import analyzer, practice
from app.path_utils import get_user_files_path

_TOKENIZERS = {}


def _tokenizer(language, script="asis"):
    if (language, script) not in _TOKENIZERS:
        analyzer.SANITIZE_JA = language == "ja"
        _TOKENIZERS[(language, script)] = (analyzer.JapaneseTokenizer() if language == "ja"
                                           else analyzer.ChineseTokenizer(script=script))
    analyzer.SANITIZE_JA = language == "ja"
    return _TOKENIZERS[(language, script)]


def _keys(language, *texts, script="asis"):
    return {(lemma, reading) for text in texts for lemma, reading, _s, _o in _tokenizer(language, script).tokenize(text)}


def _checker(language, known_texts, unknown=(), upcoming=(), recent=(), settings=None, script="asis"):
    """A Checker whose learner knows every word of `known_texts` except the lemmas in `unknown`."""
    keys = {key for key in _keys(language, *known_texts, script=script) if key[0] not in set(unknown)}
    return practice.Checker(language, upcoming=upcoming, settings=settings or {}, recent=list(recent),
                            known=(keys, {lemma for lemma, _r in keys}, set()), library=(None, 0))


def _new(result):
    return [w["word"] for w in result["new_words"]]


# --- Japanese -------------------------------------------------------------------------------------------------- #
TALK = "今日は天気がいいから、映画を見に行こう。駅の前で待ってるね。"


def test_a_chat_reply_in_known_words_passes_and_counts_the_words_used():
    result = _checker("ja", [TALK]).check(TALK)
    assert result["pass"] and result["reasons"] == []
    assert result["new_words"] == [] and result["new_share"] == 0.0
    assert len(result["sentences"]) == 2 and result["words"] > 10 and result["known_used"] > 5


def test_one_upcoming_word_in_an_otherwise_known_sentence_passes_a_chat_reply():
    """i+1 with one of the learner's next words: what a chat round is for."""
    checker = _checker("ja", [TALK], unknown={"映画"}, upcoming=_keys("ja", "映画"))
    result = checker.check(TALK)
    assert result["pass"], result["reasons"]
    assert _new(result) == ["映画"] and result["new_words"][0]["why"] == "upcoming"
    assert result["sentences"][0]["new"][0]["word"] == "映画" and result["sentences"][1]["new"] == []


def test_a_new_word_that_is_neither_upcoming_nor_an_easy_noun_fails_by_name():
    """議事録 'minutes' is no everyday noun: the reason names it so the AI can replace it."""
    text = "先輩、会議の議事録を見ましたか。"
    checker = _checker("ja", [text], unknown={"議事録"})
    result = checker.check(text)
    assert not result["pass"]
    assert _new(result) == ["議事録"] and result["new_words"][0]["allowed"] is False
    assert any("議事録" in reason and "Replace it" in reason for reason in result["reasons"])


def test_an_easy_common_noun_may_come_in_though_it_isnt_upcoming():
    """映画 ranks 770 in spoken Japanese, a common noun: an easy word a reply may bring in."""
    result = _checker("ja", [TALK], unknown={"映画"}).check(TALK)
    assert result["pass"], result["reasons"]
    assert result["new_words"][0]["why"] == "easy noun"


def test_an_everyday_verb_is_no_easy_noun():
    """待つ is common, but only nouns come in uninvited (P-1): a verb must be an upcoming word."""
    result = _checker("ja", [TALK], unknown={"待つ"}).check(TALK)
    assert not result["pass"] and _new(result) == ["待つ"]


def test_two_new_words_in_one_sentence_fail_in_either_mode():
    checker = _checker("ja", [TALK], unknown={"映画", "天気"}, upcoming=_keys("ja", "映画 天気"))
    for mode in practice.MODES:
        result = checker.check(TALK, mode)
        assert not result["pass"]
        assert result["reasons"][0].startswith("Sentence 1 has 2 words the learner doesn't know")


def test_a_chat_reply_brings_in_one_new_word_even_across_sentences():
    """映画 in the first sentence, 駅 in the second: each sentence is i+1, but a chat reply carries one new word."""
    checker = _checker("ja", [TALK], unknown={"映画", "駅"}, upcoming=_keys("ja", "映画 駅"))
    chat = checker.check(TALK, "chat")
    assert not chat["pass"] and any("one new word" in reason for reason in chat["reasons"])


def test_a_reading_keeps_its_new_words_under_three_percent():
    """A longer reading may hold several new words, each alone in its sentence, under 3 % of its words (counted as
    uses: the share of the text the learner can't read yet)."""
    sentences = ["今日は天気がいいから、映画を見に行こう。", "駅の前で友達と待っている。", "公園で少し散歩してから帰った。",
                 "夜はみんなで晩ご飯を食べた。", "明日も早く起きて学校に行く。"]
    long_reading = sentences[0] + "".join(sentences[1:] * 4)          # 映画 once in about 90 words
    checker = _checker("ja", sentences, unknown={"映画"}, upcoming=_keys("ja", "映画"))
    result = checker.check(long_reading, "reading")
    assert result["pass"], result["reasons"]
    assert 0 < result["new_share"] < practice.READING_SHARE
    short = checker.check(sentences[0], "reading")                    # one new word in ten: 10 %
    assert not short["pass"] and any("under 3%" in reason for reason in short["reasons"])


def test_a_word_read_through_its_known_word_is_no_new_word():
    """利用者 with 利用 known reads as the list reads it (LearningView): no new word."""
    text = "公園の利用者が増えた。"
    known = _keys("ja", text, "利用") - _keys("ja", "利用者")
    checker = practice.Checker("ja", settings={}, recent=[], library=(None, 0),
                               known=(known, {lemma for lemma, _r in known}, set()))
    result = checker.check(text)
    assert result["pass"] and result["new_words"] == []


def test_grammar_the_list_never_offers_is_never_a_new_word():
    """The one-character rule as the list counts it: の, は, が unknown to the known set still aren't new words."""
    checker = _checker("ja", [TALK], unknown={"の", "は", "が", "に", "を", "で", "ね"})
    assert checker.check(TALK)["pass"]


def test_an_empty_or_symbols_only_reply_fails_with_an_instruction():
    checker = _checker("ja", [TALK])
    for text in ("", "   ", "123 !!! ---", "(*^_^*)"):
        result = checker.check(text)
        assert not result["pass"] and result["words"] == 0
        assert "no Japanese or Chinese text" in result["reasons"][0]


def test_crlf_lines_are_sentences_of_their_own():
    result = _checker("ja", [TALK]).check("今日は天気がいい\r\n映画を見に行こう")
    assert [s["text"] for s in result["sentences"]] == ["今日は天気がいい", "映画を見に行こう"]


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        _checker("ja", [TALK]).check(TALK, "essay")


def test_the_newly_learned_words_used_come_newest_first():
    checker = _checker("ja", [TALK], recent=["駅", "映画", "天気"])
    assert checker.check(TALK)["recent_used"] == ["駅", "映画", "天気"]


def test_recent_terms_read_iso_and_millisecond_dates_and_skip_undated(tmp_path):
    """Surasura's Anki sync writes an ISO time, Migaku's export milliseconds, 0 when it has none."""
    path = tmp_path / "KnownWord.json"
    words = [{"dictForm": "映画", "knownStatus": "KNOWN", "created": "2026-10-27T10:00:00"},
             {"dictForm": "天気", "knownStatus": "KNOWN", "created": 1793000000000},       # 2026-10-26
             {"dictForm": "駅", "knownStatus": "KNOWN", "created": "2026-10-28T09:00:00"},
             {"dictForm": "番", "knownStatus": "KNOWN", "created": 0},
             {"dictForm": "猫", "knownStatus": "UNKNOWN", "created": "2026-10-28T12:00:00"}]
    path.write_text(json.dumps({"words": words}, ensure_ascii=False), encoding="utf-8")
    assert practice.recent_terms(str(path), "ja") == ["駅", "映画", "天気"]
    assert practice.recent_terms(str(path), "ja", limit=1) == ["駅"]
    assert practice.recent_terms(str(tmp_path / "missing.json"), "ja") == []


def test_the_real_known_words_are_read_and_a_sync_mid_session_is_picked_up(ja_resources_dir):
    """The learner's real KnownWord.json (11,176 entries): read once; when a sync adds a word, the next check knows
    it without a new Checker."""
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, "KnownWord.json")
    shutil.copy(os.path.join(ja_resources_dir, "KnownWord.json"), target)
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    text = "会議の議事録を見ましたか。"
    assert "議事録" in _new(checker.check(text))
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    data["words"].append({"dictForm": "議事録", "knownStatus": "KNOWN", "created": "2026-10-28T20:00:00"})
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.utime(target, ns=(os.stat(target).st_atime_ns, os.stat(target).st_mtime_ns + 10 ** 9))
    checker.refresh()
    result = checker.check(text)
    assert "議事録" not in _new(result) and "議事録" in result["recent_used"]


def test_a_library_without_known_words_still_checks():
    """No KnownWord.json yet: every word is new, nothing raises."""
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    result = checker.check(TALK)
    assert not result["pass"] and len(result["new_words"]) > 3


# --- Chinese --------------------------------------------------------------------------------------------------- #
ZH = "我们明天去看电影吧。你想几点出发？"


def test_chinese_a_known_reply_passes_and_an_easy_noun_may_come_in():
    assert _checker("zh", [ZH]).check(ZH)["pass"]
    result = _checker("zh", [ZH], unknown={"电影"}).check(ZH)
    assert result["pass"], result["reasons"]
    assert _new(result) == ["电影"] and result["new_words"][0]["why"] == "easy noun"


def test_chinese_a_rare_noun_must_be_upcoming():
    text = "我们明天讨论会议的议程。"
    checker = _checker("zh", [text], unknown={"议程"})
    assert not checker.check(text)["pass"]
    assert _checker("zh", [text], unknown={"议程"}, upcoming=_keys("zh", "议程")).check(text)["pass"]


def test_chinese_traditional_text_in_a_simplified_library_reads_as_its_words():
    """A library read in Simplified (zh_script "s"): the AI's Traditional reply is the same words."""
    checker = _checker("zh", ["我们明天去夜市吧。"], settings={"zh_script": "s"}, script="s")
    result = checker.check("我們明天去夜市吧。")
    assert result["pass"], result["reasons"]


def test_chinese_two_new_words_in_one_sentence_fail():
    checker = _checker("zh", [ZH], unknown={"电影", "看"}, upcoming=_keys("zh", "电影 看"))
    result = checker.check(ZH, "reading")
    assert not result["pass"] and result["reasons"][0].startswith("Sentence 1 has 2 words")


def test_check_text_keeps_one_checker_per_language(monkeypatch):
    made = []
    real = practice.Checker

    def counting(*args, **kwargs):
        made.append(args[0])
        return real(*args, settings={}, library=(None, 0), **{k: v for k, v in kwargs.items() if k != "settings"})
    monkeypatch.setattr(practice, "Checker", counting)
    monkeypatch.setattr(practice, "_CHECKERS", {})
    practice.check_text(ZH, "zh")
    practice.check_text(ZH, "zh", upcoming=_keys("zh", "电影"))
    assert made == ["zh"] and practice._CHECKERS["zh"].upcoming == _keys("zh", "电影")
