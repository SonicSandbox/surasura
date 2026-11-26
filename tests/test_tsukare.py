"""A verb's stem + つかれ in kana is 疲れる (ENGINE 52, SCHEMA 32; app/analyzer.py § 〜つかれた).

UniDic knows the つく compounds as words of their own (抱きつく, 噛みつく, 住みつく), but where it doesn't know the stem +
つく it cuts the run as the stem + 突く 'poke' + れる: 歩きつかれた 'tired from walking' put 突く on the list. The tokenizer
reads that つか + れる as 疲れる — one word with the stem where the tagger reads the stem + 疲れる whole (歩き疲れる), else
two — and leaves the tagger's reading where the stem + つく said aloud is a verb (とりつく, いきつく), and wherever no stem
stands before it (不意をつかれる). Real Japanese, made-up sentences.
"""
import pytest

from app import analyzer


@pytest.fixture(scope="module")
def tokenizer():
    analyzer.SANITIZE_JA = True
    return analyzer.JapaneseTokenizer(library=False)


def _words(tokenizer, text):
    """[(surface, lemma)] of every word `text` is read as, after the joins (join_affixes, library-free)."""
    return [(w.surface, w.feature.lemma)
            for w in analyzer.join_affixes(tokenizer.tagger(text), analyzer.affix_joins(), library=False)]


def _counted(tokenizer, text):
    return [lemma for _s, tokens in tokenizer.tokenize_sentences(text) for lemma, *_rest in tokens]


@pytest.mark.parametrize("text, word", [
    ("一日中歩きつかれた。", ("歩きつかれ", "歩き疲れる")),           # written in kanji, UniDic's own word
    ("もう待ちつかれたよ。", ("待ちつかれ", "待ち疲れる")),
    ("あちこち探しつかれて、駅のベンチに座った。", ("探しつかれ", "探し疲れる")),
    ("しゃべりつかれたから少し歩こう。", ("しゃべりつかれ", "喋り疲れる")),   # a stem the tagger reads as a noun
    ("笑いつかれて、涙が出た。", ("笑いつかれ", "笑い疲れる")),
])
def test_a_stem_and_tsukare_the_tagger_knows_whole_is_one_word(tokenizer, text, word):
    words = _words(tokenizer, text)
    assert word in words
    assert "突く" not in {lemma for _s, lemma in words} and "付く" not in {lemma for _s, lemma in words}


@pytest.mark.parametrize("text, stem", [
    ("手紙を十通も書きつかれてしまった。", ("書き", "書く")),           # 書き疲れる is no dictionary word
    ("グラウンドを何周も走りつかれた。", None),
])
def test_a_stem_and_tsukare_no_dictionary_lists_is_the_stem_and_tsukareru(tokenizer, text, stem):
    words = _words(tokenizer, text)
    at = words.index(("つかれ", "疲れる"))
    assert stem is None or words[at - 1] == stem
    assert "突く" not in {lemma for _s, lemma in words}


def test_aruki_tsukareta_counts_tsukareru_never_tsuku(tokenizer):
    # Why: 歩きつかれた put a 突く 'poke' row on the list; the sentence says 疲れる 'tired'.
    counted = _counted(tokenizer, "手紙を十通も書きつかれてしまった。")
    assert "疲れる" in counted and "書く" in counted and "突く" not in counted


@pytest.mark.parametrize("text, word", [
    ("悪霊に執りつかれた男の話だ。", ("つか", "突く")),      # とりつく is 取り付く: 'possessed' is a reading too
    ("もう生きつかれたと彼は笑った。", ("つか", "突く")),    # いきつく is 行き着く: the letters say both
    ("彼女に抱きつかれた。", ("抱きつか", "抱き付く")),      # a つく compound UniDic knows: its passive
    ("いいアイデアを考えつかれましたね。", ("考えつか", "考え付く")),
    ("不意をつかれて、言葉が出なかった。", ("つか", "突く")),  # no stem before it: 突く's passive after を
    ("嘘をつかれた。", ("つか", "突く")),
])
def test_where_the_letters_also_say_a_tsuku_verb_the_taggers_reading_stands(tokenizer, text, word):
    words = _words(tokenizer, text)
    assert word in words and "疲れる" not in {lemma for _s, lemma in words}


def test_a_line_without_tsuka_is_the_same_list(tokenizer):
    # Why: the step looks only at a line holding a token written つか; any other line passes through untouched.
    nodes = analyzer.join_affixes(tokenizer.tagger("今日はとても疲れた。"), analyzer.affix_joins(), library=False)
    assert analyzer._tsukare(nodes) is nodes
    assert analyzer._tsukare([]) == []
