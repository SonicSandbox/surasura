"""A word the tagger doesn't know, cut at a kanji it does (analyzer.join_affixes, § Words the tagger doesn't know).

UniDic reads a rare name's kanji it doesn't know two at a time as an unknown word, and the kanji after them as a word
it knows: 犍陀多 (蜘蛛の糸's Kandata, in the Japanese sample) was 犍陀 + 多, and 犍陀 topped the sample's list. The
unknown word and the one-kanji nouns / な-words touching it are one word. Sentences written for these tests (the name
is the public-domain sample's), checked against the project's fugashi + unidic-lite.
"""

import pytest

from app import analyzer


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


@pytest.fixture
def sanitized(monkeypatch):
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)


def _surfaces(tokenizer, text):
    return [w.surface for w in analyzer.join_affixes(tokenizer.tagger(text))]


@pytest.mark.parametrize("line", [
    "犍陀多が蜘蛛の糸をつかんだ。",          # 多 read as a noun
    "この犍陀多には悪い所もあった。",        # 多 read as a な-word (多に)
    "犍陀多《かんだた》と云う男がいた。",    # 多 read as a name, before the book's ruby
])
def test_an_unknown_name_cut_at_a_kanji_the_tagger_knows_is_one_word(tokenizer, sanitized, line):
    surfaces = _surfaces(tokenizer, line)
    assert "犍陀多" in surfaces and "犍陀" not in surfaces and "多" not in surfaces


def test_the_joined_name_is_one_unknown_word_on_the_list(tokenizer, sanitized):
    # Counted once a use, under its own spelling (no dictionary reading to borrow), never as 犍陀 or 多.
    keys = [(lemma, surface) for _s, tokens in tokenizer.tokenize_sentences("犍陀多が蜘蛛の糸をつかんだ。")
            for lemma, _r, surface, _o in tokens]
    assert ("犍陀多", "犍陀多") in keys
    assert not {"犍陀", "多"} & {lemma for lemma, _s in keys}
    word = analyzer.join_affixes(tokenizer.tagger("犍陀多が来た。"))[0]
    assert isinstance(word, analyzer.JoinedWord) and word.is_unk
    assert [surface for surface, _f in word.parts] == ["犍陀", "多"]


def test_a_kanji_word_after_an_unknown_one_joins_too(tokenizer, sanitized):
    # 瑯玕 (unknown) + 山: a place the tagger doesn't know, cut before the kanji it does.
    assert "瑯玕山" in _surfaces(tokenizer, "彼は瑯玕山へ向かった。")


def test_a_space_a_number_a_suffix_or_a_longer_word_keeps_the_pieces_apart(tokenizer, sanitized):
    # The space is the text's own break; a number before it counts (三 + 犍陀); a suffix, an honorific or a plural is
    # a word of its own (犍陀 + 達); a word of two kanji or more after it is a word the tagger knows (犍陀 + 多く).
    assert _surfaces(tokenizer, "犍陀 多くの人が集まった。")[:2] == ["犍陀", "多く"]
    assert _surfaces(tokenizer, "三犍陀")[-1] == "犍陀"
    assert _surfaces(tokenizer, "犍陀達が来た。")[:2] == ["犍陀", "達"]
    assert _surfaces(tokenizer, "犍陀 王が来た。")[:2] == ["犍陀", "王"]         # one kanji, but after a space
    assert _surfaces(tokenizer, "犍陀前に立つ。")[:2] == ["犍陀", "前"]          # a position word last
    assert _surfaces(tokenizer, "犍陀三人")[:2] == ["犍陀", "三"]                # a number after it
    assert _surfaces(tokenizer, "犍陀王が来た。")[0] == "犍陀王"                # …where 王 alone joins


def test_a_known_kanji_before_the_unknown_word_stays_its_own_word(tokenizer, sanitized):
    # 今 / 父 / 王 before a name are words of their own: only unknown kanji join on that side.
    assert _surfaces(tokenizer, "今犍陀多が来た。")[:2] == ["今", "犍陀多"]
    assert _surfaces(tokenizer, "父犍陀多は笑った。")[:2] == ["父", "犍陀多"]


def test_the_joined_word_is_no_name_to_ignore(tokenizer, sanitized):
    # Nothing tags it as a person's name (the word it was cut into had none): Ignore names leaves it on the list.
    from app import names
    word = analyzer.join_affixes(tokenizer.tagger("犍陀多が来た。"))[0]
    assert word.surface == "犍陀多" and names.name_lemma(word) is None


def test_a_line_with_no_unknown_word_is_left_as_it_is(tokenizer, sanitized):
    words = analyzer.join_affixes(tokenizer.tagger("鬮引きで決めよう。"))
    assert [w.surface for w in words][:2] == ["鬮", "引き"]


def test_a_lone_unknown_kanji_is_the_librarys_to_judge(tokenizer, sanitized):
    # 奏 + 汰 (汰 alone unknown): a run of one-kanji pieces, which the library's name tables judge (app/names.py);
    # this rule starts only at an unknown word of two kanji or more, which those tables never see.
    words = analyzer.join_affixes(tokenizer.tagger("奏汰が駅に来た。"), library=False)
    assert [w.surface for w in words][:2] == ["奏", "汰"]
