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
    """A learner-sized KnownWord.json (the fixture's 11,582 entries): read once; when a sync adds a word, the next check knows
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


def test_a_chinese_checker_in_the_same_process_never_changes_how_japanese_reads():
    """The analyzer's language flag is the process's: a Japanese loanword known as ナイフ stays known after a Chinese
    Checker is made and used (the MCP server holds one of each)."""
    text = "ナイフを見た。"
    ja = _checker("ja", [text])
    assert ja.check(text)["pass"]
    zh = _checker("zh", [ZH])
    assert zh.check(ZH)["pass"]
    assert ja.check(text)["pass"], "a Chinese check turned Japanese lemma cleaning off"
    assert zh.check(ZH)["pass"]


def test_a_word_on_the_ignore_list_is_no_new_word_and_an_ignore_mid_session_is_picked_up():
    """The Ignore list counts as the list counts it; adding a line while the server runs is read on the next check."""
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    known_text = "会議の資料を見ましたか。"
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in ("会議", "の", "資料", "を", "見る",
                                                                               "ます", "た", "か")]}, f,
                  ensure_ascii=False)
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    text = "会議の議事録を見ましたか。"
    assert "議事録" in _new(checker.check(text))
    ignore = os.path.join(folder, "IgnoreList.txt")
    with open(ignore, "w", encoding="utf-8") as f:
        f.write("議事録\n")
    checker.refresh()
    assert "議事録" not in _new(checker.check(text))
    assert checker.check(known_text)["pass"]


def test_only_one_word_terms_are_newly_learned_words():
    """An Anki "Also read" sentence is known, but its particles aren't newly learned words."""
    checker = _checker("ja", [TALK], recent=["駅の前で待ってる", "駅", "映画"])
    assert checker.recent_words() == ["駅", "映画"]
    assert checker.check(TALK)["recent_used"] == ["駅", "映画"]


# --- the words a round practises first: Anki's young cards, then the newest known (A6P-3, 2026-10-29) ----------- #
def _learner(language, known, dated=(), young=None):
    """The learner's real files in User Files/<language>: KnownWord.json knowing `known` (undated) and `dated`
    ((word, ISO time)), and the young cards the last Anki sync recorded (`young`: [(word, interval)]; None: no sync)."""
    folder = get_user_files_path(language)
    os.makedirs(folder, exist_ok=True)
    words = [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]
    words += [{"dictForm": w, "knownStatus": "KNOWN", "hasCard": 1, "created": when} for w, when in dated]
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": words}, f, ensure_ascii=False)
    if young is not None:
        _young_record(language, young)
    return folder


def _young_record(language, young):
    """anki_young.json as `anki_sync.sync_young` writes it (note ids: the newest note last)."""
    from app import anki_sync
    notes = {str(1789712080047 + n): {"word": word, "interval": ivl} for n, (word, ivl) in enumerate(young)}
    os.makedirs(get_user_files_path(language), exist_ok=True)
    path = os.path.join(get_user_files_path(language), anki_sync.YOUNG_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": anki_sync.YOUNG_VERSION, "synced_at": "2026-10-29T09:00:00", "decks": ["TheBank"],
                   "fields": [], "notes": notes}, f, ensure_ascii=False)


TALK_WORDS = ("今日", "は", "天気", "が", "いい", "から", "映画", "を", "見る", "に", "行く", "う", "駅", "の", "前", "で",
              "待つ", "て", "てる", "ね", "行こう", "待ってる")


def test_practise_terms_put_ankis_young_cards_first_the_least_settled_first_then_the_newest_known_each_once():
    folder = _learner("ja", TALK_WORDS, dated=[("駅", "2026-10-28T09:00:00"), ("映画", "2026-10-27T10:00:00")],
                      young=[("天気", 6), ("映画", 1), ("前", 3)])
    known = os.path.join(folder, "KnownWord.json")
    # 映画 is young and newly known: once, in its young place
    assert practice.practise_terms(known, "ja") == ["映画", "前", "天気", "駅"]
    assert practice.practise_terms(known, "ja", limit=2) == ["映画", "前"]


def test_with_no_anki_sync_or_no_young_cards_the_newest_known_words_alone_are_practised():
    folder = _learner("ja", TALK_WORDS, dated=[("駅", "2026-10-28T09:00:00"), ("映画", "2026-10-27T10:00:00")])
    known = os.path.join(folder, "KnownWord.json")
    assert practice.practise_terms(known, "ja") == ["駅", "映画"]            # never synced: no record
    _young_record("ja", [])
    assert practice.practise_terms(known, "ja") == ["駅", "映画"]            # every card grown mature
    with open(os.path.join(folder, "anki_young.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert practice.practise_terms(known, "ja") == ["駅", "映画"]            # a record that can't be read


def test_a_round_reads_the_young_cards_from_the_file_with_anki_closed_and_never_calls_anki(monkeypatch):
    """No live Anki call in a round, no wait at its start: the checker reads the record the last sync wrote."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("a round reached Anki"))
    _learner("ja", TALK_WORDS, dated=[("駅", "2026-10-28T09:00:00")], young=[("天気", 2), ("映画", 0)])
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    assert checker.recent_words() == ["映画", "天気", "駅"]
    assert checker.check(TALK)["recent_used"] == ["映画", "天気", "駅"]


def test_a_young_word_the_list_doesnt_count_as_known_is_never_offered_as_known():
    """The brief tells the AI these words are known; the checker must agree, or it would fail the AI's own draft."""
    _learner("ja", TALK_WORDS, young=[("議事録", 1), ("天気", 2)])
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    assert checker.recent_words() == ["天気"]


def test_a_sync_mid_session_that_changes_the_young_cards_is_picked_up_on_the_next_check():
    _learner("ja", TALK_WORDS, young=[("天気", 2)])
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    assert checker.recent_words() == ["天気"]
    _young_record("ja", [("天気", 9), ("駅", 1), ("前", 4)])
    checker.refresh()
    assert checker.recent_words() == ["駅", "前", "天気"]


def test_chinese_young_cards_are_practised_first_too():
    _learner("zh", ["我们", "明天", "去", "看", "电影", "吧", "夜市"], dated=[("夜市", "2026-10-28T09:00:00")],
             young=[("电影", 5), ("明天", 1)])
    checker = practice.Checker("zh", settings={}, library=(None, 0))
    assert checker.recent_words() == ["明天", "电影", "夜市"]
    assert checker.check("我们明天去看电影吧。")["recent_used"] == ["明天", "电影"]


def test_practise_terms_read_the_young_cards_beside_the_known_words_file_they_are_given(tmp_path):
    """The record that counts is the one in the same User Files folder as the KnownWord.json being read."""
    from app import anki_sync
    known = tmp_path / "KnownWord.json"
    known.write_text(json.dumps({"words": [{"dictForm": "駅", "knownStatus": "KNOWN", "created": "2026-10-28T09:00:00"}]},
                                ensure_ascii=False), encoding="utf-8")
    (tmp_path / anki_sync.YOUNG_FILE).write_text(json.dumps({"notes": {"1": {"word": "天気", "interval": 2}}},
                                                            ensure_ascii=False), encoding="utf-8")
    _young_record("ja", [("映画", 1)])                  # another folder's record: not this learner's
    assert practice.practise_terms(str(known), "ja") == ["天気", "駅"]


def test_a_sync_that_changes_only_the_young_cards_never_reads_the_known_words_again(monkeypatch):
    """A sync after reviews alone moves intervals: the next round reads its practise words again, not every known word
    (KnownWord.json tokenized whole) — no wait at a round's start."""
    _learner("ja", TALK_WORDS, young=[("天気", 2)])
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    monkeypatch.setattr(analyzer, "load_known_words", lambda *a, **k: pytest.fail("the known words read again"))
    _young_record("ja", [("天気", 9), ("駅", 1)])
    checker.refresh()
    assert checker.recent_words() == ["駅", "天気"]


def test_the_practise_words_are_capped_after_the_words_that_cant_be_practised_are_left_out(ja_resources_dir):
    """120 young cards the list doesn't count as known must not crowd out the newest known words."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        real = [w["dictForm"] for w in json.load(f)["words"] if w.get("dictForm")]
    young = [(w, 1) for w in dict.fromkeys(w for w in real if w not in TALK_WORDS)][:120]
    assert len(young) == 120
    _learner("ja", TALK_WORDS, dated=[("駅", "2026-10-28T09:00:00")], young=young)
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    assert checker.recent_words()[-1] == "駅" and len(checker.recent_words()) < 5   # いく is 行く, known


def test_one_word_on_a_young_card_and_among_the_newest_known_in_two_spellings_is_practised_once():
    _learner("ja", TALK_WORDS + ("分かる",), dated=[("分かる", "2026-10-28T09:00:00")], young=[("わかる", 1)])
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    assert checker.recent_words() == ["わかる"]


def test_a_learner_with_more_young_cards_than_a_round_can_use_gets_the_first_hundred(ja_resources_dir):
    """120 young cards, every one a known word: the least settled 100, never more (the brief carries them)."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        real = [w["dictForm"] for w in json.load(f)["words"] if w.get("dictForm")]
    tokenizer = _tokenizer("ja")
    words = [w for w in dict.fromkeys(real) if len(tokenizer.tokenize(w)) == 1][:120]
    assert len(words) == 120
    _learner("ja", words, young=[(w, n % 21) for n, w in enumerate(words)])
    checker = practice.Checker("ja", settings={}, library=(None, 0))
    assert len(checker.recent_words()) == practice.RECENT == 100
    # and no more are read: a KnownWord.json of thousands of dated words would otherwise be tokenized at every load
    assert len(checker.recent) == len(checker.recent_terms) == 100


# --- a produce round's words in a text (Piyo's output drills, 2026-11-19): what the learner's own answer holds -------- #
def _answer(text, targets=(), avoid=(), resolve=None, language="ja", known=(TALK,)):
    return _checker(language, list(known)).check(text, practice.ANSWER, targets=targets, avoid=avoid, resolve=resolve)


def _target(result):
    (found,) = result["targets"]
    return found


def test_an_answer_says_where_its_target_is_which_banned_words_it_holds_and_what_the_tokenizer_read():
    """No verdict on the learner's own text: no pass, no reasons. The target found by its lemma in its inflected form,
    a crutch word present, the other absent, the text exactly as checked, the lemmas the tokenizer read."""
    text = "サイコロを振ったら、有名人が来た。"
    result = _answer(text, targets=["振る"], avoid=["有名人", "投げる"])
    assert "pass" not in result and "reasons" not in result and result["mode"] == "answer"
    assert result["text"] == text
    assert _target(result) == {"word": "振る", "found": True, "how": "lemma", "form": "振っ", "spelling": "same"}
    assert result["avoid"] == [{"word": "有名人", "present": True, "form": "有名人", "how": "lemma"},
                               {"word": "投げる", "present": False}]
    assert {"surface": "振っ", "lemma": "振る", "reading": "フル"} in result["lemmas"]


def test_a_target_missing_from_an_answer_is_not_found():
    """跳躍 asked, ジャンプ said: a retrieval miss for the judge; the crutch word is present."""
    result = _answer("ジャンプに成功した。", targets=["跳躍"], avoid=["ジャンプ"])
    assert _target(result) == {"word": "跳躍", "found": False}
    assert result["avoid"][0]["present"] is True


def test_a_target_written_in_kana_alone_is_found_by_its_reading():
    """はいゆう: the tokenizer reads はい + ゆうに, so no lemma 俳優 — the reading finds it, a reading_error candidate."""
    found = _target(_answer("はいゆうになりたい。", targets=["俳優"]))
    assert found["found"] and found["how"] == "reading" and found["form"].startswith("はいゆう")
    assert "reading_error" in found["note"]


def test_an_inflected_target_in_kana_is_found_by_its_lemma_and_said_to_be_kana():
    found = _target(_answer("サイコロをふった。", targets=["振る"]))
    assert (found["how"], found["form"], found["spelling"]) == ("lemma", "ふっ", "kana")


def test_a_misread_target_is_found_near_its_reading():
    """ちょうちゃく for 跳躍 (ちょうやく): the trial's reading error, two kana off on a five-kana reading."""
    found = _target(_answer("ちょうちゃくに成功した。", targets=["跳躍"]))
    assert (found["how"], found["form"]) == ("near_reading", "ちょうちゃく")


def test_a_short_reading_is_matched_on_whole_words_only():
    """橋 (はし) is no part of はしる; はしを渡る is the reading of a whole word, written in kana."""
    assert _target(_answer("はしる", targets=["橋"]))["found"] is False
    assert _target(_answer("はしを渡る。", targets=["橋"]))["how"] == "reading"


@pytest.mark.parametrize("target, text", [("政治", "誠実な人です。"), ("今日", "教育が大事だ。")])
def test_a_reading_is_never_found_inside_a_kanji_word(target, text):
    """せいじ starts せいじつ (誠実), きょう starts きょういく (教育): neither word is there, as a target or a banned word."""
    result = _answer(text, targets=[target], avoid=[target])
    assert _target(result) == {"word": target, "found": False}
    assert result["avoid"] == [{"word": target, "present": False}]


def test_another_kanji_with_the_targets_reading_is_found_by_reading_when_its_reading_is_given():
    """臭い (におい in the round) answered 匂い: the same reading in other kanji. The bare 臭い reads くさい, so the
    round's reading decides (the MCP server passes it)."""
    def resolve(tokenizer, language, word):
        return practice._own_tokens(tokenizer, language, word)[:3] + ("ニオイ",)
    found = _target(_answer("変な匂いがする。", targets=["臭い"], resolve=resolve))
    assert (found["how"], found["form"]) == ("reading", "匂い")
    assert _target(_answer("変な臭いがする。", targets=["臭い"], resolve=resolve))["how"] == "lemma"


def test_a_draft_that_gives_the_target_away_fails_and_one_without_targets_reads_as_before():
    checker = _checker("ja", [TALK, "昨日、有名な俳優に会ったよ。", "有名な人"])
    plain = checker.check("昨日、有名な俳優に会ったよ。")
    assert plain["pass"] and set(plain) == {"pass", "reasons", "mode", "sentences", "new_words", "new_share", "words",
                                           "known_used", "recent_used"}
    leak = checker.check("昨日、有名な俳優に会ったよ。", "chat", targets=["俳優"])
    assert leak["pass"] is False and "gives away the target word 俳優" in leak["reasons"][-1]
    hidden = checker.check("昨日、有名な人に会ったよ。", "chat", targets=["俳優"])
    assert hidden["pass"] and hidden["targets"] == [{"word": "俳優", "found": False}]


def test_too_many_or_too_long_target_words_say_what_to_send():
    checker = _checker("ja", [TALK])
    with pytest.raises(ValueError, match="At most"):
        checker.check(TALK, practice.ANSWER, targets=[f"語{n}" for n in range(practice.WORDS_MOST + 1)])
    with pytest.raises(ValueError, match="one word"):
        checker.check(TALK, practice.ANSWER, targets=["冒険" * 20])


def test_chinese_a_target_is_found_by_its_word_and_no_reading_is_looked_for():
    result = _answer("我们明天去看电影吧。", targets=["电影", "冒险"], avoid=["片子"], language="zh", known=(ZH,))
    assert result["targets"][0] == {"word": "电影", "found": True, "how": "lemma", "form": "电影", "spelling": "same"}
    assert result["targets"][1] == {"word": "冒险", "found": False}
    assert result["avoid"] == [{"word": "片子", "present": False}]


# --- live testing, 2026-11-20 --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("target, text", [("俳優", "話の内容は自由です。"), ("橋", "これはしないでね。")])
def test_a_reading_never_starts_on_a_particle_or_joins_pieces_of_other_words(target, text):
    """話の内容は自由です made 俳優 near_reading as は自由 (はじゆう, one kana off はいゆう): は is a particle and 自由
    another word. これはしない holds no はし for 橋 either."""
    assert _target(_answer(text, targets=[target])) == {"word": target, "found": False}


def test_a_draft_showing_one_of_the_targets_kanji_fails_and_says_to_write_that_word_in_kana():
    """跳ぶ banned while the word was 跳躍: the crutch word showed 跳. Written とぶ, the draft passes."""
    checker = _checker("ja", [TALK, "跳ぶのは禁止です。", "とぶのは禁止です。"])
    shown = checker.check("跳ぶのは禁止です。", "chat", targets=["跳躍"])
    assert shown["pass"] is False and shown["targets"] == [{"word": "跳躍", "found": False}]
    assert any("shows 跳, a kanji of the target word 跳躍 that gives it away" in r and "in kana" in r
               for r in shown["reasons"])
    assert checker.check("とぶのは禁止です。", "chat", targets=["跳躍"])["pass"] is True
    # the learner's own answer is never judged for it
    assert "reasons" not in checker.check("跳ぶのは禁止です。", practice.ANSWER, targets=["跳躍"])


# --- Piyo-PA (our adapt): the kanji that gives a word away, and the near-reading scan's cost ----------------------- #
@pytest.mark.parametrize("target, text", [("時間", "その時は、本当に驚いた。"), ("人生", "大人になったら、わかるよ。"),
                                          ("毎日", "今日は天気がいいね。")])
def test_a_common_kanji_of_the_target_gives_nothing_away_and_the_draft_passes(target, text):
    """時 of 時間 in その時, 人 of 人生 in 大人, 日 of 毎日 in 今日: among the commonest kanji of everyday speech, they
    narrow the word down to nothing, so the draft stays natural (the PR's rule failed all three)."""
    result = _checker("ja", [TALK, text]).check(text, "chat", targets=[target])
    assert result["pass"] is True, result["reasons"]


@pytest.mark.parametrize("target, text, kanji", [("跳躍", "とても高く跳ぶ。", "跳"), ("手", "手紙を書く。", "手"),
                                                 ("宝石", "宝物を見つけた。", "宝")])
def test_a_rare_kanji_or_the_words_only_kanji_still_fails_the_draft(target, text, kanji):
    """跳 (跳躍 in 跳ぶ) and 宝 (宝石 in 宝物) are rare: seeing one narrows the word to a handful. 手 is 手's whole
    spelling (手紙 shows it, read て)."""
    result = _checker("ja", [TALK, text]).check(text, "chat", targets=[target])
    assert result["pass"] is False
    assert any(f"shows {kanji}, a kanji of the target word {target} that gives it away" in r for r in result["reasons"])


def test_the_common_kanji_are_read_from_the_spoken_ranks_weighted_by_rank(monkeypatch):
    """The boundary: the COMMON_KANJI-th kanji by weight is common, the next is not; a word with one kanji keeps it
    banned however common; a word past COMMON_KANJI_FROM counts for nothing."""
    from app import reference_data
    ranks = {"時間": 1, "時代": 2, "人生": 3, "跳躍": 4, "毎日": 30001}
    monkeypatch.setattr(reference_data, "spoken_ranks", lambda: ranks)
    monkeypatch.setattr(practice, "COMMON_KANJI", 4)
    monkeypatch.setattr(practice, "_COMMON", {})
    # weights: 時 1 + 1/2, 間 1, 代 1/2, 人 生 1/3, 跳 躍 1/4; 毎 日 past the band: the top four are 時 間 代 and 人 or 生
    assert {"時", "間", "代"} <= practice.common_kanji() and len(practice.common_kanji()) == 4
    assert not practice.gives_away("時間", "時") and practice.gives_away("跳躍", "跳")
    assert practice.gives_away("毎日", "日")                 # 日 here only past COMMON_KANJI_FROM
    assert practice.gives_away("時", "時")                   # a word's only kanji, however common


def test_the_real_common_kanji_hold_the_everyday_ones_and_not_the_rare(monkeypatch):
    monkeypatch.setattr(practice, "_COMMON", {})
    common = practice.common_kanji()
    assert len(common) == practice.COMMON_KANJI
    assert {"時", "間", "人", "生", "日", "今", "大", "事"} <= common
    assert not {"跳", "躍", "俳", "宝"} & common


def _long_text(ja_resources_dir, chars=3000):
    """About `chars` characters of real Japanese: the sample subtitles' lines, in order."""
    import glob
    import re
    lines = []
    for path in sorted(glob.glob(os.path.join(ja_resources_dir, "*.srt"))):
        with open(path, encoding="utf-8-sig") as f:
            lines += [l.strip() for l in f if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", l)]
    text = "".join(dict.fromkeys(lines))
    while len(text) < chars:
        text += text
    return text[:chars]


ABSENT = ["跳躍", "俳優", "冒険", "議事録", "誠実", "教育", "練習", "冷蔵庫", "掃除機", "郵便局"]


def test_a_long_text_with_absent_targets_looks_at_a_few_spans_a_word_not_every_one(ja_resources_dir, monkeypatch):
    """R4: the near-reading scan took every word start against every word end, slicing each before its length test
    (3,000 characters, 10 absent targets: 3.95 s). Now only the ends one kana either side of the reading's length are
    looked at: counted, not timed — at most three a word start, per target."""
    text = _long_text(ja_resources_dir)
    assert not [w for w in ABSENT if w in text]
    seen = []
    real = practice._near_ends

    def counted(ends, start, length):
        found = real(ends, start, length)
        seen.append(len(found))
        return found
    monkeypatch.setattr(practice, "_near_ends", counted)
    checker = _checker("ja", [TALK])
    result = checker.check(text, "reading", targets=ABSENT)
    starts = len(checker._kana_nodes(text))
    assert all(not t["found"] or t["how"] == "near_reading" for t in result["targets"])
    assert seen and max(seen) <= 3 and sum(seen) <= 3 * starts * len(ABSENT)


def test_a_near_reading_is_still_found_one_kana_either_side_of_its_length():
    """The windows by position keep what the old scan found: ちょうちゃく (one kana longer) for 跳躍; the exact
    reading is the reading arm's, never near."""
    assert _target(_answer("ちょうちゃくに成功した。", targets=["跳躍"]))["how"] == "near_reading"
    assert _target(_answer("ちょうやくに成功した。", targets=["跳躍"]))["how"] == "reading"


def test_a_text_past_the_cap_with_targets_says_what_to_check_and_reads_as_before_without(ja_resources_dir):
    text = _long_text(ja_resources_dir, practice.LOOK_CHARS + 1)
    checker = _checker("ja", [TALK])
    for mode, targets, avoid in (("reading", ["跳躍"], ()), ("chat", (), ["ジャンプ"]), (practice.ANSWER, (), ())):
        with pytest.raises(ValueError, match=f"at most {practice.LOOK_CHARS:,} characters"):
            checker.check(text, mode, targets=targets, avoid=avoid)
    assert "targets" not in checker.check(text, "reading")       # no targets: the old check, uncapped
    assert "targets" in checker.check(text[:practice.LOOK_CHARS], "reading", targets=["跳躍"])
