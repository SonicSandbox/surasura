"""Which of a subtitle's words become cards, and the line each is cut from (app/connect/pick.py, P1.3 row 1.3.3).

Real subtitles: the 五等分の花嫁 sample (.srt), the library episode (.ass, with a karaoke OP and two speakers), the
phrases sample (set phrases) and a Chinese night-market vlog. The learner's known words and list are made per test
from the words the files hold, so each rule is seen on its own.
"""
import os

import pytest

from app import analyzer, cues, phrases
from app.connect import pick

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(PROJECT_ROOT, "samples", "ja", "HighPriority", "H_priority_sample_2.srt")
RESOURCES = os.path.join(PROJECT_ROOT, "tests", "Test Resources")
EPISODE = os.path.join(RESOURCES, "ja", "library_episode.ass")
PHRASES = os.path.join(RESOURCES, "ja", "phrases_sample.srt")
NIGHT_MARKET = os.path.join(RESOURCES, "zh", "night_market.srt")


@pytest.fixture(autouse=True)
def _a_japanese_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


def _read(path, language="ja"):
    read = cues.read(path, language)
    return read, cues.tokens(read, language)


def _known(*lemmas):
    return lambda key: key[0] in lemmas


def _srt(tmp_path, lines, name="episode.ja.srt"):
    """An .srt of `lines` [(start s, end s, text)]."""
    def stamp(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    body = "\n".join(f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n" for n, (a, b, text) in enumerate(lines, 1))
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def _by_word(chosen):
    return {w["word"]: w for w in chosen["words"]}


# --------------------------------------------------------------------------- #
# Which words
# --------------------------------------------------------------------------- #
def test_list_mode_sends_only_the_lists_words_in_the_lists_order():
    read, tokens = _read(EPISODE)
    listed = {("延長", "エンチョウ"): 0, ("用紙", "ヨウシ"): 1, ("図書カード", "トショカード"): 2,
              ("雨宿り", "アマヤドリ"): 3}                                   # not said in this episode
    chosen = pick.pick(read, tokens, "ja", _known(), mode="list", listed=listed)
    assert [w["word"] for w in chosen["words"]] == ["延長", "用紙", "図書カード"]
    assert chosen["not_offered"] == []


def test_unknown_mode_sends_every_word_not_known_and_never_a_known_one():
    read, tokens = _read(EPISODE)
    chosen = pick.pick(read, tokens, "ja", _known("用紙", "延長", "です"), mode="unknown")
    words = _by_word(chosen)
    assert "図書カード" in words and "小説" in words
    assert not {"用紙", "延長", "です"} & set(words)


def test_i1_mode_sends_only_words_with_a_line_whose_other_words_are_known(tmp_path):
    path = _srt(tmp_path, [(1, 3, "この小説は面白い。"), (4, 6, "延長して小説を読む。")])
    read, tokens = _read(path)
    known = _known("此の", "は", "面白い", "て", "を", "読む", "為る")
    chosen = pick.pick(read, tokens, "ja", known, mode="i1")
    words = _by_word(chosen)
    # 小説 has a line where it's the only new word; 延長's only line also holds 小説
    assert set(words) == {"小説"} and words["小説"]["line_start"] == 1.0 and words["小説"]["other_new"] == 0


def test_a_word_with_a_card_is_never_sent_and_says_where_the_card_was_seen():
    read, tokens = _read(EPISODE)
    chosen = pick.pick(read, tokens, "ja", _known(), mode="unknown", carded={"用紙", "えんちょう"},
                       carded_source="backlog")
    left = {n["word"]: n for n in chosen["not_offered"]}
    assert "用紙" not in _by_word(chosen) and left["用紙"]["reason"] == "in-backlog"
    # a card written as the episode writes the word is its card, whatever its Word (いろいろ is 色々's)
    read, tokens = _read(SAMPLE)
    chosen = pick.pick(read, tokens, "ja", _known(), mode="unknown", carded={"いろいろ"}, carded_source="anki")
    assert {n["word"]: n["reason"] for n in chosen["not_offered"]}["色々"] == "has-card"


@pytest.mark.parametrize("mode", ["unknown", "i1"])
def test_names_follow_ignore_names_and_grammar_words_their_own_switch(mode):
    # G1.3 (Sonic: "based on their setting in surasura"): a name goes unless Ignore names is on; grammar words go
    # unless Send grammar words is off
    read, tokens = _read(SAMPLE)
    known = _known() if mode == "unknown" else (lambda key: key[0] not in ("ウエスギ", "から", "家庭教師"))
    sent = _by_word(pick.pick(read, tokens, "ja", known, mode=mode))
    assert "ウエスギ" in sent and "から" in sent
    assert sent["ウエスギ"]["name"] is True and sent["家庭教師"]["name"] is False
    off = pick.pick(read, tokens, "ja", known, mode=mode, ignore_names=True, send_grammar=False)
    reasons = {n["word"]: n["reason"] for n in off["not_offered"]}
    assert reasons["ウエスギ"] == "name" and reasons["から"] == "grammar"
    assert "ウエスギ" not in _by_word(off) and "家庭教師" in _by_word(off)
    names_only = pick.pick(read, tokens, "ja", known, mode=mode, ignore_names=True)
    assert "から" in _by_word(names_only) and "ウエスギ" not in _by_word(names_only)


def test_a_name_is_what_surasura_calls_a_name_on_the_list_too():
    read, tokens = _read(SAMPLE)
    listed = {("ウエスギ", "ウエスギ"): 0, ("家庭教師", "カテイキョウシ"): 1}
    chosen = pick.pick(read, tokens, "ja", _known(), mode="list", listed=listed, ignore_names=True)
    assert [w["word"] for w in chosen["words"]] == ["家庭教師"]
    assert [n["reason"] for n in chosen["not_offered"]] == ["name"]


def test_a_word_said_only_in_a_song_is_never_sent():
    read, tokens = _read(EPISODE)
    chosen = pick.pick(read, tokens, "ja", _known(), mode="unknown")
    reasons = {n["word"]: n["reason"] for n in chosen["not_offered"]}
    assert reasons["声"] == "sung" and reasons["聞こえる"] == "sung"      # karaoke OP
    assert "声" not in _by_word(chosen)


def test_a_one_kanji_piece_is_never_offered():
    # ５人: 人 after a number is a piece of the count, not the word 人 (analyzer.unoffered)
    read, tokens = _read(SAMPLE)
    chosen = pick.pick(read, tokens, "ja", _known(), mode="unknown")
    five = next(c.index for c in read if "５人" in c.text)
    assert not any(w["word"] == "人" and w["line_start"] == cues.seconds(read[five].start) for w in chosen["words"])


def test_chinese_words_go_as_written_with_no_second_entry():
    read = cues.read(NIGHT_MARKET, "zh")
    tokens = cues.tokens(read, "zh", script="s")
    chosen = pick.pick(read, tokens, "zh", _known("我", "的", "是"), mode="unknown")
    words = _by_word(chosen)
    assert "夜市" in words and words["夜市"]["sent"] == ["夜市"] and words["夜市"]["predicted_class"] is None


def test_no_cues_no_words():
    assert pick.pick([], [], "ja", _known(), mode="unknown") == {"words": [], "not_offered": []}
    with pytest.raises(ValueError):
        pick.pick([], [], "ja", _known(), mode="all")


# --------------------------------------------------------------------------- #
# The card front, and Surasura's Word
# --------------------------------------------------------------------------- #
def test_a_verb_goes_by_its_dictionary_form_as_written_anything_else_exactly_as_written():
    read, tokens = _read(EPISODE)
    words = _by_word(pick.pick(read, tokens, "ja", _known(), mode="unknown"))
    assert words["借りる"]["sent"] == ["借りる"]                   # 借り(たい) -> its dictionary form
    assert words["下さる"]["sent"] == ["くださる", "下さる"]        # written in kana: its Word goes too
    assert words["図書カード"]["sent"] == ["図書カード"]           # a joined word, whole (IS-R2)


def test_the_card_fronts_reading_is_said_as_its_line_says_it_in_hiragana():
    # P1.3-AM37: Anki Miner 3.7 takes a word's `reading` as the card's own (it picks the dictionary entry), so it is
    # the occurrence's dictionary-form kana as Anki Miner reads a front itself, never the row's lemma reading
    read, tokens = _read(SAMPLE)
    words = _by_word(pick.pick(read, tokens, "ja", _known(), mode="unknown"))
    said = words["矢張り"]                                               # the file says やっぱ
    assert said["reading"] == "ヤハリ" and said["front_reading"] == said["surface"] != "やはり"
    assert words["反応"]["front_reading"] == "はんのう"
    assert words["家庭教師"]["front_reading"] == "かていきょうし"         # a joined word: the join's reading
    read, tokens = _read(EPISODE)
    words = _by_word(pick.pick(read, tokens, "ja", _known(), mode="unknown"))
    assert words["借りる"]["front_reading"] == "かりる"                   # 借り(たい): its dictionary form's
    assert words["下さる"]["front_reading"] == "くださる" and words["下さる"]["surface"].startswith("くださ")


def test_a_form_anki_miner_folds_goes_by_its_lemma(tmp_path):
    # Review #3 (P1.3-AM37): UniDic reads a potential, ra-nuki or classical form as its lemma's word; its own
    # dictionary form (行ける) is a word of no one's, and Anki Miner folds it to the lemma too. One entry, the lemma.
    path = _srt(tmp_path, [(1, 3, "明日は行けるよ。"), (4, 6, "やっと辿り着けた。"), (7, 9, "ここから海が見れる。"),
                           (10, 12, "美しき花よ。")])
    read, tokens = _read(path)
    words = _by_word(pick.pick(read, tokens, "ja", _known("明日", "は", "よ", "やっと", "た", "此処", "から", "海", "が",
                                                          "花"), mode="unknown"))
    for word, reading in (("行く", "いく"), ("辿り着く", "たどりつく"), ("見る", "みる"), ("美しい", "うつくしい")):
        assert words[word]["sent"] == [word] and words[word]["front_reading"] == reading, words[word]
    assert words["行く"]["surface"] == "行ける"                     # the line's own spelling, for Anki Miner's search


def test_a_chinese_word_carries_no_reading():
    read = cues.read(NIGHT_MARKET, "zh")
    chosen = pick.pick(read, cues.tokens(read, "zh", script="s"), "zh", _known("我", "的", "是"), mode="unknown")
    assert chosen["words"] and all(w["front_reading"] is None for w in chosen["words"])


def test_a_set_phrase_reads_as_the_dictionary_reads_it():
    loaded = phrases.load()
    if loaded is None:
        pytest.skip("no phrase data in this build")
    read, tokens = _read(PHRASES)
    phrase = loaded.entry(loaded.of_word("腑に落ちる"))
    (word,) = pick.pick(read, tokens, "ja", _known(), mode="list", listed={(phrase.word, phrase.reading): 0},
                        phrase_set=loaded)["words"]
    assert word["front_reading"] == "ふにおちる" and word["surface"].startswith("腑に落ち")


def test_the_homograph_guard_keeps_word_out_when_the_episode_writes_it(tmp_path):
    # いい's Word is 良い; with 良い written in the episode, sending 良い could make that line's card instead
    path = _srt(tmp_path, [(1, 3, "それはいいね。"), (4, 6, "天気が良い日は散歩する。")])
    read, tokens = _read(path)
    words = _by_word(pick.pick(read, tokens, "ja", _known("其れ", "は", "ね", "が", "日", "為る"), mode="unknown"))
    assert words["良い"]["sent"] in (["良い"], ["いい"])           # never both: the episode spells 良い


def test_a_written_out_line_is_chosen_over_a_kana_only_one(tmp_path):
    path = _srt(tmp_path, [(1, 3, "やくそくしたよね。"), (4, 6, "約束は守るよ。")])
    read, tokens = _read(path)
    words = _by_word(pick.pick(read, tokens, "ja", _known("為る", "た", "よ", "ね", "は", "守る"), mode="unknown"))
    assert words["約束"]["line_start"] == 4.0 and words["約束"]["surface"] == "約束"


# --------------------------------------------------------------------------- #
# The line
# --------------------------------------------------------------------------- #
def test_a_line_no_other_word_took_comes_first_unless_there_is_no_other(tmp_path):
    path = _srt(tmp_path, [(1, 3, "延長と貸し出し。"), (4, 6, "延長します。")])
    read, tokens = _read(path)
    listed = {("貸し出し", "カシダシ"): 0, ("延長", "エンチョウ"): 1}
    words = _by_word(pick.pick(read, tokens, "ja", _known("と", "為る", "ます"), mode="list", listed=listed))
    assert words["貸し出し"]["line_start"] == 1.0           # its only line
    assert words["延長"]["line_start"] == 4.0               # not the line 貸し出し took
    path = _srt(tmp_path, [(1, 3, "延長と貸し出し。")], "one-line.srt")
    read, tokens = _read(path)
    words = _by_word(pick.pick(read, tokens, "ja", _known("と"), mode="list", listed=listed))
    assert words["貸し出し"]["line_start"] == words["延長"]["line_start"] == 1.0     # no other: they share


def test_a_lines_other_new_words_are_counted_over_what_its_card_holds(tmp_path):
    # Intent review #2: 小説's first line runs into a line holding 延長, so its card would hold two new words
    path = _srt(tmp_path, [(1, 2, "この小説を"), (2, 3, "延長して読む。"), (10, 12, "小説は面白い。")])
    read, tokens = _read(path)
    known = _known("此の", "を", "為る", "て", "読む", "は", "面白い")
    words = _by_word(pick.pick(read, tokens, "ja", known, mode="unknown"))
    assert words["小説"]["line_start"] == 10.0 and words["小説"]["other_new"] == 0
    assert set(_by_word(pick.pick(read, tokens, "ja", known, mode="i1"))) == {"小説"}


def test_a_word_read_through_known_words_and_an_ignored_name_are_no_new_words(tmp_path):
    # Intent review #3: the one learning rule (LearningView) and Ignore names decide what's new in a line
    path = _srt(tmp_path, [(1, 3, "上杉さんの図書館。")])
    read, tokens = _read(path)
    known = _known("さん", "の")
    plain = _by_word(pick.pick(read, tokens, "ja", known, mode="unknown"))
    assert plain["図書館"]["other_new"] >= 1                     # the name is a new word in the line
    names_off = _by_word(pick.pick(read, tokens, "ja", known, mode="unknown", ignore_names=True,
                                   readable=lambda key: key[0] == "図書館"))
    assert names_off["図書館"]["other_new"] == 0


def test_line_expansion_takes_the_lines_a_sentence_runs_across():
    read, tokens = _read(EPISODE)
    words = _by_word(pick.pick(read, tokens, "ja", _known(), mode="unknown"))
    assert words["小説"]["line_expansion"] == [0, 1]        # …読んでから→ runs into また返しに来ます。
    assert words["返し"]["line_expansion"] == [1, 0]
    assert words["延長"]["line_expansion"] == [0, 0]        # a finished line on its own


def test_line_expansion_stops_at_two_lines_and_at_a_gap(tmp_path):
    path = _srt(tmp_path, [(1, 2, "昨日は"), (2, 3, "駅前の"), (3, 4, "本屋で"), (4, 5, "小説を"), (5, 6, "買った。"),
                           (20, 21, "それから"), (25, 26, "帰った。")])
    read = cues.read(path, "ja")
    assert pick.line_expansion(read, 2) == [2, 2]           # at most 2 each side
    assert pick.line_expansion(read, 0) == [0, 2]
    assert pick.line_expansion(read, 5) == [0, 0]           # 「それから」 runs on, but 4 s later: no
    assert pick.line_expansion(read, 4) == [2, 0]


@pytest.mark.parametrize("text, done", [("行くぞ。", True), ("本当？", True), ("待って…", True), ("「行くぞ」", True),
                                        ("読んでから→", False), ("それでしたら", False), ("我觉得，", False), ("", False)])
def test_a_line_is_finished_by_its_last_mark(text, done):
    assert pick.finished(text) is done


def test_each_word_says_its_lines_start_and_end_in_seconds():
    read, tokens = _read(EPISODE)
    words = _by_word(pick.pick(read, tokens, "ja", _known(), mode="unknown"))
    assert (words["延長"]["line_start"], words["延長"]["line_end"]) == (116.4, 120.8)


# --------------------------------------------------------------------------- #
# Set phrases and the predicted classes
# --------------------------------------------------------------------------- #
def test_a_set_phrase_on_the_list_goes_by_its_own_words_never_its_lemmas():
    loaded = phrases.load()
    if loaded is None:
        pytest.skip("no phrase data in this build")
    read, tokens = _read(PHRASES)
    index = loaded.of_word("腑に落ちる")
    phrase = loaded.entry(index)
    listed = {(phrase.word, phrase.reading): 0}
    chosen = pick.pick(read, tokens, "ja", _known(), mode="list", listed=listed, phrase_set=loaded)
    (word,) = chosen["words"]
    assert word["kind"] == "phrase" and word["predicted_class"] == "IS-P5"
    assert len(word["sent"]) == 1 and word["sent"][0].startswith("腑に落ち")


def test_the_predicted_class_says_why_anki_miner_may_miss_a_word():
    read, tokens = _read(SAMPLE)
    words = _by_word(pick.pick(read, tokens, "ja", _known(), mode="unknown"))
    assert words["から"]["predicted_class"] == "IS-P9"               # grammar (a one-character one, だ, is never offered)
    assert words["ウエスギ"]["predicted_class"] == "IS-P2"           # a name
    assert words["家庭教師"]["predicted_class"] == "IS-P5"           # a word only Surasura joins
    assert words["色々"]["predicted_class"] == "IS-P1"               # a kana-only noun or adverb
    assert words["反応"]["predicted_class"] is None


def test_word_never_goes_when_another_words_card_front_is_word(tmp_path):
    # Review #1: 帰る's Word is 返る; 返って on another line has 返る as its card front, so naming 返る would cut a
    # second card from that line
    path = _srt(tmp_path, [(1, 3, "早く帰って！"), (4, 6, "返事が返ってこない。")])
    read, tokens = _read(path)
    words = _by_word(pick.pick(read, tokens, "ja", _known("早い", "て", "が", "来る", "ない", "返事"), mode="unknown"))
    for word in words.values():
        assert "返る" not in word["sent"][1:], word


def test_with_anki_up_a_card_deleted_since_the_last_sync_no_longer_blocks_its_word(monkeypatch):
    # Intent review #1: the backlog's keys count only while their notes are still in Anki; a new note is read
    from app import anki_connect, anki_sync
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_sync, "load_backlog", lambda lang: {"notes": {
        "5": {"word": "用紙", "keys": ["用紙"]}, "6": {"word": "延長", "keys": ["延長"]}}})
    monkeypatch.setattr(anki_sync, "backlog_keys", lambda lang: {"用紙", "延長"})
    monkeypatch.setattr(anki_sync, "_read_known_file", lambda lang: (None, None))
    monkeypatch.setattr(anki_connect, "probe", lambda url, timeout=5, required=(): {"ok": True})
    monkeypatch.setattr(anki_connect, "find_notes", lambda url, query: [6, 9])      # 5 deleted, 9 new
    monkeypatch.setattr(anki_connect, "notes_info", lambda url, ids: [
        {"noteId": 9, "fields": {"Expression": {"value": "図書カード", "order": 0}}}])
    settings = {"anki_sync_decks": {"ja": ["日本語"]}, "anki_sync_fields": {"ja": []},
                "anki_connect_url": "http://127.0.0.1:8765"}
    keys, source = pick.carded("ja", settings)
    assert source == "anki" and {"延長", "図書カード"} <= keys and "用紙" not in keys     # (and its kana fold)
    # Anki closed: the backlog as the last sync saved it
    monkeypatch.setattr(anki_connect, "probe", lambda url, timeout=5, required=(): {"ok": False})
    assert pick.carded("ja", settings) == ({"用紙", "延長"}, "backlog")
