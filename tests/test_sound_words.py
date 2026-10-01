"""Sounds the tagger cut or left unknown (analyzer.join_affixes).

In speech without punctuation the tagger can prefer a chain of one-kana fillers to the interjection it lists — まあ read
ま + あ (まー + あー), ああ～ read あ + あ～ — and it leaves a sound said three times or more as a katakana word it doesn't
know (ハァハァハァ), though it lists the sound said twice (はあはあ). Two fillers that read alone as one interjection or
adverb are that word; an unknown sound said over and over is the sound word said twice. Real sentences throughout
(constructed, never the user's library), checked against the project's fugashi + unidic-lite.
"""

import pytest

from app import analyzer, token_index


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


@pytest.fixture
def sanitized(monkeypatch):
    """Every Japanese run sanitizes lemmas."""
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)


def _tokens(tokenizer, text):
    return [token for _sentence, tokens in tokenizer.tokenize_sentences(text) for token in tokens]


def _keys(tokenizer, text):
    return [(lemma, surface) for lemma, _r, surface, _o in _tokens(tokenizer, text)]


@pytest.mark.parametrize("line, word", [
    ("旅行は大変だったんですけどまあやっぱり楽しかったです。", ("まあ", "まあ")),   # ま + あ: the adverb まあ
    ("ああ～その件ね、もう済んだよ。", ("ああ", "ああ～")),                       # あ + あ～: ああ, stretched
    ("ええ～本当に？信じられない。", ("ええ", "ええ～")),                         # え + え〜: UniDic spells it with 〜
])
def test_two_fillers_cut_out_of_one_interjection_are_that_word(tokenizer, sanitized, line, word):
    keys = _keys(tokenizer, line)
    assert word in keys
    assert not {"まー", "あー", "えー"} & {lemma for lemma, _s in keys}


def test_the_pair_is_one_word_of_the_interjections_row(tokenizer, sanitized):
    # One token, read as the interjection read alone is: its lemma and reading, the text's own spelling, its pieces.
    tokens = analyzer.join_affixes(tokenizer.tagger("ああ～その件ね、もう済んだよ。"))
    first = tokens[0]
    assert isinstance(first, analyzer.JoinedWord) and first.surface == "ああ～"
    assert (first.feature.lemma, first.feature.lForm, first.feature.pos1) == ("ああ", "アア", "感動詞")
    assert [surface for surface, _f in first.parts] == ["あ", "あ～"]


def test_fillers_that_read_otherwise_alone_stay_as_they_are(tokenizer, sanitized):
    # うえ～ん (crying): う + え〜 alone reads as 上 'above', え〜 + ん as no interjection — no word is made of them.
    lemmas = [lemma for lemma, _s in _keys(tokenizer, "うえ～ん、痛いよ。")]
    assert lemmas[:3] == ["うー", "えー", "んー"] and "上" not in lemmas


@pytest.mark.parametrize("line, surface", [
    ("ハァハァハァ…もう走れない。", "ハァハァハァ"),
    ("ﾊｧﾊｧﾊｧ…まだまだ。", "ﾊｧﾊｧﾊｧ"),                       # half-width, read as ハァハァハァ
])
def test_a_sound_said_three_times_is_the_sound_word_said_twice(tokenizer, sanitized, line, surface):
    lemma, reading, surface_, _orth = _tokens(tokenizer, line)[0]
    assert (lemma, reading, surface_) == ("はあはあ", "ハアハア", surface)


def test_a_sound_whose_double_is_no_sound_word_stays_as_it_was(tokenizer, sanitized):
    # ヘヘ read alone is two words (屁 + へ), so ヘヘヘ stays the word the tagger left it.
    assert _keys(tokenizer, "ヘヘヘ！やったぜ。")[0] == ("ヘヘヘ", "ヘヘヘ")


def test_the_token_store_counts_the_sound_words(tmp_path):
    # The store reads through the same joins: the words count, the fillers and the unknown sound don't.
    path = tmp_path / "trip.txt"
    path.write_text("旅行は大変だったんですけどまあやっぱり楽しかったです。\nハァハァハァ…もう走れない。\n",
                    encoding="utf-8")
    counts = token_index.make_tokenizer("ja")(str(path))["counts"]
    assert counts["まあ|マア"] == 1 and counts["はあはあ|ハアハア"] == 1
    assert not any(key.split("|")[0] in ("まー", "あー", "ハァハァハァ") for key in counts)
