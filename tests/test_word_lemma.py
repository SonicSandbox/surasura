"""What a token counts as (analyzer.word_lemma).

UniDic's symbol classes are never words — 補助記号, 空白 and 記号, which the filter used to spell 记号 (Chinese), so a
character UniDic reads as a character (玖 キュウ in 玖渚, しゃ in うっしゃ) was counted as a word. A letter spelled out
by its name (記号,文字: デルタ, アルファ) is a word, counted under that name rather than the symbol UniDic makes its
lemma (δ, α). And a number is never a word (the user, 2026-09-27): UniDic's 数詞 — 二十, 百, 〇, ゼロ, digits, and
何 / 数 counting (何人, 数年). The sentence itself keeps every character. Real sentences throughout (constructed,
never the user's library), checked against the project's fugashi + unidic-lite.
"""

import pytest

from app import analyzer


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


@pytest.fixture
def sanitized(monkeypatch):
    """Every Japanese run sanitizes lemmas (α-alpha, プラス-plus)."""
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)


def _tokens(tokenizer, text):
    return [token for _sentence, tokens in tokenizer.tokenize_sentences(text) for token in tokens]


def _lemmas(tokenizer, text):
    return [lemma for lemma, _reading, _surface, _orth in _tokens(tokenizer, text)]


@pytest.mark.parametrize("line, symbol", [
    ("玖渚友に会いに行った。", "玖"),       # 記号,一般 キュウ: 680 uses of the name 玖渚 were the word キュウ
    ("うっしゃ！やるぞ。", "しゃ"),          # 記号,一般 シャ
    ("二乃が来た。", "乃"),                  # 記号,一般 ノ, inside the name 二乃
    ("崩玉の力が目覚めた。", "崩"),          # 崩 and 玉 both 記号 (the coined word 崩玉)
])
def test_a_character_read_as_a_character_is_no_word(tokenizer, sanitized, line, symbol):
    # The '记号' typo let every one of these through as a word (アア row #187, イー #641, ホウ #869).
    surfaces = [surface for _l, _r, surface, _o in _tokens(tokenizer, line)]
    assert symbol not in surfaces
    # ...but the sentence is shown exactly as written.
    assert [s for s, _ in tokenizer.tokenize_sentences(line)][0].startswith(line[:3])


def test_a_letter_spelled_out_by_its_name_is_a_word_under_that_name(tokenizer, sanitized):
    # UniDic files デルタ / アルファー as 記号,文字 with the lemma δ / α-alpha: counted, the lemma was one character
    # (never listable) and never met a card or a known word written デルタ.
    assert ("デルタ", "デルタ", "デルタ", "デルタ") in _tokens(tokenizer, "デルタが餌を撒いた。")
    # A spelling variant is the same word: the key is UniDic's lForm, the orth the text's own spelling. (Alone: in
    # プラスアルファー the whole run is one word — a katakana run no list spells, app/names.py.)
    assert ("アルファ", "アルファ", "アルファー", "アルファー") in _tokens(tokenizer, "黒板にアルファーと書いた。")
    assert "ガンマ" in _lemmas(tokenizer, "ガンマ線を浴びた。")


def test_a_letter_written_as_the_symbol_itself_is_no_word(tokenizer, sanitized):
    # ω in a kaomoji is 記号,文字 too — but its surface holds no Japanese: a symbol, never a word.
    lemmas = _lemmas(tokenizer, "今日も疲れた(´・ω・`)ショボーン")
    assert "ω" not in lemmas and "オメガ" not in lemmas
    assert "疲れる" in lemmas


@pytest.mark.parametrize("line, number", [
    ("エプロンをした二十代前半くらいの店員。", "二十"),   # list row #28 (341 uses)
    ("百人が餌を撒いた。", "百"),                          # 万 alone blocked 180 sentences
    ("二〇一九年七月一日発行", "零"),                      # 〇 is UniDic's 零
    ("ゼロから始める異世界生活。", "ゼロ"),
    ("だからこの仕事を3人で分けるのはどうですか。", "3"),
    ("昨日は何人来たの？", "何"),                         # 何 counting is a numeral (数詞, ナン)
    ("数年後に戻ってきた。", "数"),
])
def test_a_number_is_never_a_word(tokenizer, sanitized, line, number):
    assert number not in _lemmas(tokenizer, line)


def test_words_that_only_look_like_numbers_stay_words(tokenizer, sanitized):
    # Only UniDic's 数詞 is a number: 一人 and 一緒 are nouns, 一番 an adverb, 十分 a な-word, and 何 'what' a
    # pronoun — all still words. (一緒に, a JMdict adverb, is one word of its own: 一緒 stands alone here.)
    lemmas = _lemmas(tokenizer, "一人で来た。みんな一緒だ。これが一番好き。これで十分だ。何が起きたの？")
    for word in ("一人", "一緒", "一番", "十分", "何"):
        assert word in lemmas, word


def test_the_sentence_keeps_its_numbers_and_symbols(tokenizer, sanitized):
    # Only the tokens change: the example sentence, and so its source anchor, is the file's own text.
    line = "二〇一九年七月一日、デルタと玖渚が来た。"
    sentences = list(tokenizer.tokenize_sentences(line))
    assert [s for s, _ in sentences] == [line]
    assert [lemma for lemma, *_ in sentences[0][1] if lemma in ("デルタ", "キュウ", "二", "一")] == ["デルタ"]


def test_a_known_word_is_read_the_same_way(tokenizer, sanitized):
    # KnownWord entries go through the same tokenizer: a known アルファ is the word アルファ, a known 二十 is no
    # word at all (never needed: it is never an unknown either).
    assert _lemmas(tokenizer, "アルファ") == ["アルファ"]
    assert _lemmas(tokenizer, "二十") == []


def test_a_dash_is_no_word_though_the_tagger_reads_one(tokenizer, sanitized):
    # Between a heading's two parts UniDic reads the full-width hyphen-minus as the particle から — punctuation
    # (Unicode's dash punctuation), never a word the text says. The から of 心から is a word and stays.
    line = "「祈り－心からの願い」"
    nodes = {node.surface: node for node in analyzer.join_affixes(tokenizer.tagger(line))}
    assert nodes["－"].feature.pos1 not in ("補助記号", "記号")          # the tagger reads it as a word
    assert analyzer.word_lemma(nodes["－"]) is None
    assert _lemmas(tokenizer, line) == ["祈り", "心", "から", "の", "願い"]
    assert [s for s, _ in tokenizer.tokenize_sentences(line)] == [line]   # the sentence keeps its dash


def test_word_lemma_reads_a_node_as_every_caller_does(tokenizer):
    # One rule for every caller that reads words off the tagger (the tokenizer, 順's sentence words).
    nodes = {node.surface: node for node in analyzer.join_affixes(tokenizer.tagger("デルタと二十人で玖渚に行く。"))}
    assert analyzer.word_lemma(nodes["デルタ"]) == "デルタ"
    assert analyzer.word_lemma(nodes["二十"]) is None
    assert analyzer.word_lemma(nodes["玖"]) is None
    assert analyzer.word_lemma(nodes["。"]) is None
    assert analyzer.word_lemma(nodes["行く"]) == "行く"
