"""Sounds are no words (analyzer § Sounds are no words).

An interjection that is only a sound — a filler (えっと, あのー), one mora said alone or cut short (え？, ほっ, なっ), a
laugh (えへへ, ふふっ, あははは, くくっ) — is said, not learned: no use, no list row, no unknown in a sentence and no
card. Only where it stands on its own between marks, spaces or its line's edges; glued to a word it may be a piece of a
word or a set phrase the tagger cut (あっという間, 目ん玉) and stays. Real interjections (ありがとう, うん, ええ, はい,
ねえ, くそ) and the words a sound looks like (ほっと, なっちゃった's 成る) are words. Lines from tests/Test Resources/ja
(utterances_sample.srt, readings_sample.srt, phrase_reading_sample.srt, the 蜘蛛の糸 split), checked against the
project's fugashi + unidic-lite.
"""

import os

import pytest

from app import analyzer


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


@pytest.fixture
def sanitized(monkeypatch):
    """Every Japanese run sanitizes lemmas."""
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)


def _sentences(tokenizer, text):
    return [(sentence, [(lemma, surface) for lemma, _r, surface, _o in tokens])
            for sentence, tokens in tokenizer.tokenize_sentences(text)]


def _surfaces(tokenizer, text):
    return [surface for _s, tokens in _sentences(tokenizer, text) for _lemma, surface in tokens]


def _srt_lines(path):
    """The dialogue lines of an .srt, in order (no numbers, no times, no blank lines)."""
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle
                if line.strip() and not line.strip().isdigit() and "-->" not in line]


@pytest.fixture
def utterances(test_resources_dir):
    return _srt_lines(os.path.join(test_resources_dir, "ja", "utterances_sample.srt"))


@pytest.mark.parametrize("line, sound, words", [
    ("ほっ、よかった。間に合ったみたい。", "ほっ", ["良い", "間に合う"]),        # one mora cut short: a sigh
    ("なっ…なんでここにいるの！？", "なっ", ["なんで"]),                          # the tagger's なあ 'hey', stammered
    ("エヘヘ、ありがとう。", "エヘヘ", ["有り難う"]),                              # a laugh; ありがとう is a word
    ("ふふっ、それは内緒だよ。", "ふふっ", ["内緒"]),
    ("あははは！　そんなわけないじゃん。", "あははは", ["訳"]),
    ("えっと、あのー、その件なんですけど。", "えっと", ["件"]),                    # fillers, both of them
    ("え？　もう帰るの？", "え", ["もう"]),                                        # one mora said alone
])
def test_a_sound_standing_on_its_own_is_no_word(tokenizer, sanitized, utterances, line, sound, words):
    assert line in utterances                       # the sample's own line
    sentences = _sentences(tokenizer, line)
    lemmas = [lemma for _s, tokens in sentences for lemma, _surface in tokens]
    assert sound not in _surfaces(tokenizer, line)
    assert set(words) <= set(lemmas)                # the line's words still count
    assert any(sound in sentence for sentence, _t in sentences)     # and its text stays in the sentence


def test_both_fillers_of_a_hesitation_go(tokenizer, sanitized):
    surfaces = _surfaces(tokenizer, "えっと、あのー、その件なんですけど。")
    assert "えっと" not in surfaces and "あのー" not in surfaces and "件" in surfaces


@pytest.mark.parametrize("line, word", [
    ("うん、ええ、はい、わかりました。", ["うん", "ええ", "はい"]),     # yes, said three ways: words
    ("ねえ、こんにちは。今日もよろしくね。", ["ねえ", "今日は"]),          # ねえ 'hey', こんにちは
    ("くそっ、逃げられた！", ["くそ"]),                                     # 'damn': two morae, no laugh
    ("ほっとしたら、お腹が空いてきた。", ["ほっと"]),                      # the adverb ほっと, never the sigh ほっ
    ("そうなっちゃったら、もう遅いよ。", ["成る"]),                        # なっ is 成る here
])
def test_a_word_that_looks_like_a_sound_stays_a_word(tokenizer, sanitized, utterances, line, word):
    assert line in utterances
    lemmas = [lemma for _s, tokens in _sentences(tokenizer, line) for lemma, _surface in tokens]
    assert set(word) <= set(lemmas)


@pytest.mark.parametrize("line, pieces", [
    ("あっという間に夏休みが終わった。", ["あっ", "と", "いう", "間"]),   # glued to と: the set phrase あっという間
    ("目ん玉が飛び出るほど高かった。", ["目", "ん", "玉"]),               # ん, a filler to the tagger, inside 目ん玉
])
def test_a_sound_glued_to_a_word_stays_for_the_word_or_phrase_it_is_cut_from(tokenizer, sanitized, utterances,
                                                                              line, pieces):
    assert line in utterances
    surfaces = _surfaces(tokenizer, line)
    assert surfaces[:len(pieces)] == pieces


def test_a_real_lines_laugh_and_gasp_are_no_words(tokenizer, sanitized, test_resources_dir):
    # readings_sample.srt: くくっ (a laugh) and ウッ (a gasp the tagger reads as a foreign name) — the words after them
    # count; phrase_reading_sample.srt's うん is a word
    lines = _srt_lines(os.path.join(test_resources_dir, "ja", "readings_sample.srt"))
    assert "くくっ、面白くなってきた。" in lines and "ウッ、頭が痛い……" in lines
    assert _surfaces(tokenizer, "くくっ、面白くなってきた。")[0] != "くくっ"
    assert _surfaces(tokenizer, "ウッ、頭が痛い……")[:3] == ["頭", "が", "痛い"]
    assert _surfaces(tokenizer, "うん、いい感じだね。")[0] == "うん"


def test_a_novels_sounds_and_its_phrase(tokenizer, sanitized, ja_resources_dir):
    # 蜘蛛の糸: 「こら、罪人ども。」 — こら 'hey!' is a word; あっと云う間 keeps its あっ (glued to と)
    with open(os.path.join(ja_resources_dir, "books", "split_2x", "蜘蛛の糸_02.txt"), encoding="utf-8-sig") as f:
        text = f.read()
    surfaces = _surfaces(tokenizer, text)
    assert "こら" in surfaces and "あっ" in surfaces


@pytest.mark.parametrize("line", ["", "、、、", "えへへ。", "「えへへ」", "……あっ", "ほっ　"])
def test_a_line_that_is_only_a_sound_has_no_words(tokenizer, sanitized, line):
    # edge cases: nothing, marks only, a cue said alone (a subtitle cue gets its 。: analyzer.close_cue), in brackets,
    # after marks, before a space
    assert _surfaces(tokenizer, line) == []


@pytest.mark.parametrize("term, lemma", [("あっ", "あっ"), ("えへへ", "えへ"), ("えっと", "えーと"), ("ウッ", "ウッ")])
def test_a_word_read_alone_is_a_word_given(tokenizer, sanitized, term, lemma):
    # a card's word, a known entry, an Ignore line: read alone (no mark, no space) it is a word given, never an
    # utterance — a card for あっ still finds あっ's row (glued uses keep it: あっという間)
    assert [l for _s, tokens in _sentences(tokenizer, term) for l, _surface in tokens] == [lemma]


def test_a_sound_is_no_word_to_every_caller_of_word_lemma(sanitized):
    # the one test (analyzer.word_lemma): the パターン builder, 順 and the reference builds count what the list counts
    words = analyzer.join_affixes(analyzer.Tagger()("ほっ、よかった。"))
    assert isinstance(words[0], analyzer.SoundNode) and analyzer.word_lemma(words[0]) is None
    assert words[0].feature.pos1 == "感動詞"      # read as it was: only the count changes


@pytest.mark.parametrize("surface, kind, sound", [
    ("あ", "i", True), ("ほっ", "i", True), ("ちぇっ", "i", True), ("ホッ", "i", True),    # one mora
    ("はぁ", "i", False), ("ねー", "i", False), ("ねえ", "i", False),                     # a stretch is a mora
    ("えへへ", "i", True), ("あはは", "i", True), ("はっはっは", "i", True), ("ククク", "i", True),   # laughs
    ("ああ", "i", False), ("いいえ", "i", False), ("うん", "i", False), ("ふふん", "i", False),
    ("もしもし", "i", False), ("おっと", "i", False), ("嗚呼", "i", False),
    ("ウッ", "n", True), ("ナッ", "n", True), ("ハハ", "n", False), ("ア", "n", False),   # a gasp read as a name
    ("ー", "i", False), ("", "i", False),
])
def test_the_shape_of_a_sound(surface, kind, sound):
    assert analyzer._sound_shape(surface, kind) is sound


# --- Chinese: the same rule (analyzer.chinese_sounds, app/cedict_data.py's INTERJECTIONS) ------------------------- #
@pytest.fixture(scope="module")
def zh_tokenizer():
    return analyzer.ChineseTokenizer()


@pytest.fixture
def zh_utterances(test_resources_dir):
    return _srt_lines(os.path.join(test_resources_dir, "zh", "utterances_sample.srt"))


def _zh_words(tokenizer, text):
    return [word for _s, tokens in tokenizer.tokenize_sentences(text) for word, _r, _surface, _o in tokens]


@pytest.mark.parametrize("line, sound, words", [
    ("啊，好痛！", "啊", ["好", "痛"]),
    ("嗯，我知道了。", "嗯", ["知道"]),
    ("哈哈哈哈，太好笑了。", "哈哈", ["好笑"]),        # a laugh's run, read as 哈哈
    ("呃……我不太清楚。", "呃", ["清楚"]),
    ("哦，原来如此。", "哦", ["原来如此"]),
    ("唉，算了吧。", "唉", ["算了"]),
])
def test_a_chinese_sound_standing_on_its_own_is_no_word(zh_tokenizer, zh_utterances, line, sound, words):
    assert line in zh_utterances
    found = _zh_words(zh_tokenizer, line)
    assert sound not in found and set(words) <= set(found)
    sentences = [sentence for sentence, _t in zh_tokenizer.tokenize_sentences(line)]
    assert any(line[0] in sentence for sentence in sentences)       # its text stays in the sentence


@pytest.mark.parametrize("line, words", [
    ("好啊，我们走吧。", ["好", "啊", "走", "吧"]),     # glued to 好 / 走: 啊 and 吧 are the sentence's grammar
    ("喂，你在哪儿？", ["喂", "哪儿"]),                 # 喂 'hello' (on the phone) is a word
    ("对了，你明天有空吗？", ["明天", "吗"]),
    ("他听完哈哈大笑。", ["哈哈大笑"]),                 # a word with a laugh in it
    ("恭喜！谢谢！再见！", ["恭喜", "谢谢", "再见"]),    # exclamations that are words
])
def test_a_chinese_word_beside_or_like_a_sound_stays_a_word(zh_tokenizer, zh_utterances, line, words):
    assert line in zh_utterances
    assert set(words) <= set(_zh_words(zh_tokenizer, line))


def test_a_real_chinese_lines_particle_stays(zh_tokenizer, test_resources_dir):
    # repeated_lines.zh.srt: 好啊，几点见？ — the 啊 after 好 is grammar, never a sound
    lines = _srt_lines(os.path.join(test_resources_dir, "zh", "repeated_lines.zh.srt"))
    assert "好啊，几点见？" in lines
    assert _zh_words(zh_tokenizer, "好啊，几点见？")[:2] == ["好", "啊"]


@pytest.mark.parametrize("pieces, sounds", [
    ([], []), (["啊"], []), (["啊", "，", "好"], [0]), (["好", "啊"], []), (["嗯", "嗯", "。"], [0, 1]),
    (["嗯", "嗯"], []),
    (["好", "啊", "啊"], []), (["啊啊啊", "！"], [0]), (["哈哈哈", "！"], [0]), (["\n", "嗯", " "], [1]),
    (["喂", "，"], []),
])
def test_which_chinese_pieces_are_sounds(pieces, sounds):
    # edge cases: nothing, a word read alone (a card: 啊), before a mark, glued, two sounds in a row (standing
    # together), the same read alone, the same after a word, one interjection's character said over, a laugh's run,
    # between a line break and a space, a word that is said (喂 'hello')
    assert analyzer.chinese_sounds(pieces) == sounds


def test_the_chinese_table_is_dictionary_data():
    # app/cedict_data.py's INTERJECTIONS (scripts/build_cedict_data.py): interjections, laughs, a modal particle —
    # never a word that is also meant (喂 'to feed', 吧 'bar', 恭喜 'to congratulate', 对了 'that's right')
    from app import cedict_data
    table = cedict_data.interjections()
    assert {"啊", "嗯", "哦", "唉", "呃", "哈哈", "呵呵", "嘿嘿", "嘻嘻", "哎呀"} <= table
    assert not {"喂", "恭喜", "对了", "谢谢", "你好", "好", "哈"} & table


@pytest.mark.parametrize("line", ["啊啊，好痛！", "嗯嗯。", "啊啊啊！"])
def test_chinese_sounds_in_a_row_stand_together(zh_tokenizer, line):
    assert not {"啊", "嗯", "啊啊啊"} & set(_zh_words(zh_tokenizer, line))


@pytest.mark.parametrize("line, gone", [
    ("あっあっ！", ["あっ"]),                     # two gasps, glued to each other only
    ("うえ～ん、痛いよ。", ["うー", "えー", "んー"]),   # crying, three fillers in a row
])
def test_japanese_sounds_in_a_row_stand_together(tokenizer, sanitized, line, gone):
    lemmas = [lemma for _s, tokens in _sentences(tokenizer, line) for lemma, _surface in tokens]
    assert not set(gone) & set(lemmas)


def test_a_card_for_a_sound_still_makes_its_glued_word_known(tmp_path, sanitized):
    # KnownWord.json holds a card for えっと: alone it is a sound (no word), but its word えーと stays known where a
    # line glues it to the next word (えっとですね) — the card's word is known, as before
    import json
    path = tmp_path / "KnownWord.json"
    path.write_text(json.dumps([{"dictForm": "えっと", "knownStatus": "KNOWN", "hasCard": 1}], ensure_ascii=False),
                    encoding="utf-8")
    tuples, lemmas = analyzer.load_known_words(str(path), analyzer.JapaneseTokenizer())[:2]
    assert ("えーと", "エート") in tuples and "えーと" in lemmas


def test_connects_words_keep_their_own_nodes_past_a_sound(tmp_path):
    # app/cues.py pairs each word with its node by its text: a sound (は？) is no word and never the node of the
    # particle は after it (before the fix: the particle took the sound's node, an interjection)
    from app import cues
    path = tmp_path / "scene.ja.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:03,000\n来る。は？　は、大事だ。\n", encoding="utf-8")
    analyzer.SANITIZE_JA = True
    read = cues.read(str(path), "ja")
    tokens = cues.tokens(read, "ja")
    topic = [t for t in tokens if t.surface == "は"]
    assert topic and all(t.node.feature.pos1 == "助詞" for t in topic)

@pytest.mark.parametrize("line, words", [("ｱｯﾊﾊ！", []), ("ｳｯ、頭が痛い。", ["頭", "が", "痛い"])])
def test_a_half_width_sound_is_judged_as_the_tagger_reads_it(tokenizer, sanitized, line, words):
    # half-width katakana is read as full width (ｱｯ is アッ): the same laugh, the same gasp
    assert _surfaces(tokenizer, line) == words
