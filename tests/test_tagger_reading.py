"""What the tagger reads (analyzer.tagger_text, analyzer.Tagger).

A compatibility character is the same text in another form (Unicode NFKC): ｽﾏﾎ is スマホ, ５０ is 50, ⽅ (the Kangxi
radical PDF extraction emits) is 方. unidic-lite and jieba know one form only, so every tagger call reads a word
character in its NFKC form, drops invisible format characters (a zero-width space), and reads punctuation, symbols
and spaces as written. Each token keeps the text's own spelling as its surface, so a sentence is shown — and its
source anchor found — exactly as the file says it. Real sentences throughout (constructed, never the user's
library), checked against the project's fugashi + unidic-lite and jieba.
"""

import json
import sys

import pytest

from app import analyzer, token_index


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


@pytest.fixture
def sanitized(monkeypatch):
    """Every Japanese run sanitizes lemmas (glossed loanwords: スマホ, ナイフ-knife)."""
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)


def _tokens(tokenizer, text):
    return [token for _sentence, tokens in tokenizer.tokenize_sentences(text) for token in tokens]


def _read_back(read, at, text):
    """Every character of `read` maps into `text`, in order, and the parts tile it."""
    assert len(at) == len(read) + 1 and at[-1] == len(text)
    assert at == sorted(at)


@pytest.mark.parametrize("line", [
    "「本当に行くの？」　彼女は小さく笑った……。",   # full-width punctuation and space, an ellipsis
    "えっ！？そんなの聞いてない!",
    "10時に駅前で待ち合わせね。",                  # ASCII digits are already what NFKC gives
    "",
])
def test_ordinary_text_is_read_exactly_as_written(line):
    # The fast path, and constraint 3: punctuation and spaces are never read in another form, so the boundary
    # test and the sentence never see a different character than the file holds.
    assert analyzer.tagger_text(line) == (line, None)


# --- which lines take the slow path ------------------------------------------------------------------------------ #
# A line with no character read in another form goes to the tagger as it is; one such character anywhere sends the
# whole line through the read-through. The quick test deciding that keeps the characters above U+FFFF (about 6,000)
# in a set: as ranges in its pattern they made it several times slower on every line. So it is checked here on lines
# of each kind and on every code point, the astral ones included.

@pytest.mark.parametrize("line, read", [
    ("ﾏｸﾞﾛの刺身を食べた。", "マグロの刺身を食べた。"),          # half-width katakana, a voiced mark included
    ("会議は１４時からです。", "会議は14時からです。"),            # full-width digits
    ("𩸽の塩焼きを食べた。", None),                                # 𩸽 (U+29E3D) is a kanji of its own: as written
    ("𠮷野さんと待ち合わせた。", None),                            # 𠮷 (U+20BB7) likewise
    ("𩸽とﾏｸﾞﾛを買った。", "𩸽とマグロを買った。"),                # the kanji as it is, the katakana read
    ("本日🈚料で配布中。", "本日無料で配布中。"),                   # 🈚 (U+1F21A) is 無 in another form
    ("葛\U000E0100城市に住んでいる。", "葛城市に住んでいる。"),       # a variation selector (U+E0100) is not read
    ("今日は晴れです。", None),                                    # plain text
])
def test_a_line_is_read_differently_exactly_when_one_of_its_characters_is(line, read):
    got, at = analyzer.tagger_text(line)
    if read is None:
        assert (got, at) == (line, None)
    else:
        assert got == read
        _read_back(got, at, line)


def test_the_quick_test_flags_exactly_the_characters_read_differently():
    # Every code point, one at a time: a character sends its line down the slow path exactly when tagger_text reads
    # it in another form, or it composes with the one before it.
    analyzer.tagger_text("ｱ")                            # the tables are made on first use
    named = set(analyzer._READ_AS) | analyzer._COMBINES
    wrong = [f"U+{point:04X}" for point in range(sys.maxunicode + 1)
             if (analyzer.tagger_text(chr(point))[1] is not None) != (chr(point) in named)]
    assert not wrong, wrong[:10]


def test_half_width_katakana_is_read_full_width_and_keeps_its_own_spelling(tokenizer, sanitized):
    # ｽﾏﾎ / ﾊﾞｯﾃﾘｰ: JIS X 0201 katakana, voiced marks included (ﾊ + ﾞ is バ).
    line = "ｽﾏﾎのﾊﾞｯﾃﾘｰが切れた。"
    read, at = analyzer.tagger_text(line)
    assert read == "スマホのバッテリーが切れた。"
    _read_back(read, at, line)
    assert line[at[0]:at[3]] == "ｽﾏﾎ" and line[at[4]:at[9]] == "ﾊﾞｯﾃﾘｰ"
    sentences = list(tokenizer.tokenize_sentences(line))
    assert [s for s, _ in sentences] == [line]               # shown exactly as the file says it
    keys = {(lemma, surface) for lemma, _r, surface, _o in sentences[0][1]}
    assert ("スマホ", "ｽﾏﾎ") in keys and ("バッテリー", "ﾊﾞｯﾃﾘｰ") in keys


def test_an_unknown_word_is_named_by_its_text_as_read(tokenizer, sanitized):
    # unidic-lite knows スマホ in neither width: both spellings must still be ONE word, or the list gets two rows.
    half = [(lemma, reading) for lemma, reading, _s, _o in _tokens(tokenizer, "ｽﾏﾎを見る。")]
    full = [(lemma, reading) for lemma, reading, _s, _o in _tokens(tokenizer, "スマホを見る。")]
    assert half == full and half[0][0] == "スマホ"


def test_a_zero_width_space_is_not_read_and_the_word_keeps_it(tokenizer, sanitized):
    # A zero-width space pasted from the web cut 新幹線 in two (新 | \u200b | 幹線); it is invisible and no text.
    line = "新\u200b幹線に乗った。"
    assert analyzer.tagger_text(line)[0] == "新幹線に乗った。"
    first = _tokens(tokenizer, line)[0]
    assert first[0] == "新幹線" and first[2] == "新\u200b幹線"
    assert [s for s, _ in tokenizer.tokenize_sentences(line)] == [line]


def test_decomposed_kana_are_read_composed(tokenizer, sanitized):
    # NFD text (a macOS file name, some web pages) writes が as か + U+3099; read so, the tagger cut ありか + \u3099とう.
    line = "ありか\u3099とう。"
    assert analyzer.tagger_text(line)[0] == "ありがとう。"
    assert _tokens(tokenizer, line)[0][:1] == ("有り難う",)


def test_full_width_digits_are_read_as_digits(tokenizer, sanitized):
    # unidic-lite reads １０ as the loanword テン and so 分 as ブン 'portion'; 10 is a number and 分 the minute.
    tokens = _tokens(tokenizer, "あと１０分待って。")
    assert ("分", "フン") in [(lemma, reading) for lemma, reading, _s, _o in tokens]
    assert not any(lemma == "テン" for lemma, _r, _s, _o in tokens)


def test_a_half_width_word_takes_its_suffix_as_the_full_width_word_does(tokenizer, sanitized):
    # The join table is written as the dictionaries write: it must meet the text as the tagger read it.
    assert _tokens(tokenizer, "ｱﾒﾘｶ人の友達。")[0][:3] == ("アメリカ人", "アメリカジン", "ｱﾒﾘｶ人")


def test_a_kangxi_radical_is_read_as_its_ideograph(tokenizer, sanitized):
    tokens = _tokens(tokenizer, "⽅法を考える。")
    assert tokens[0][:3] == ("方法", "ホウホウ", "⽅法")


def test_a_character_read_as_several_words_gives_its_spelling_to_the_first(tokenizer, sanitized):
    # ㍿ is 株式会社, which unidic-lite reads as 株式 + 会社: the sentence must still show ㍿ exactly once.
    line = "㍿山田の社員です。"
    sentences = list(tokenizer.tokenize_sentences(line))
    assert [s for s, _ in sentences] == [line]
    surfaces = {lemma: surface for lemma, _r, surface, _o in sentences[0][1]}
    assert surfaces["株式"] == "㍿" and surfaces["会社"] == ""


def test_every_node_keeps_the_texts_own_spelling():
    # Surfaces tile the line (MeCab skips only ASCII spaces, as it always did) — what a source anchor relies on.
    line = "ｷﾐの⽅がﾏｼだって、新\u200b幹線で言われた。"
    nodes = analyzer.Tagger()(line)
    assert "".join(node.surface for node in nodes) == line
    assert all(isinstance(node, analyzer.ReadNode) for node in nodes)


def test_plain_text_gets_the_taggers_own_nodes():
    # Nothing is copied or wrapped when there is nothing to read differently (most lines of a library).
    nodes = analyzer.Tagger()("今日は晴れです。")
    assert not any(isinstance(node, analyzer.ReadNode) for node in nodes)
    assert "".join(node.surface for node in nodes) == "今日は晴れです。"


def test_text_that_is_only_invisible_characters_is_empty():
    assert analyzer.tagger_text("\u200b\ufeff") == ("", [2])
    assert list(analyzer.JapaneseTokenizer().tokenize_sentences("\u200b\ufeff")) == []
    assert list(analyzer.ChineseTokenizer().tokenize_sentences("\u200b")) == []


@pytest.mark.parametrize("text, language, holds", [
    ("ﾏｼﾞｶﾖ｡", "ja", True),        # all half-width: still Japanese (no range widened — the text is read as NFKC)
    ("⽅", "zh", True),             # a Kangxi radical is its ideograph
    ("１０", "ja", False),          # a number is no language
    ("①", "ja", False),
    ("OK!?", "ja", False),
    ("", "ja", False),
])
def test_the_language_in_another_form_is_still_the_language(text, language, holds):
    assert analyzer.has_target_language(text, language) is holds


def test_a_subtitle_cue_in_half_width_katakana_is_read(tokenizer, sanitized, tmp_path):
    # The subtitle reader drops a line with no Japanese in it; a cue written wholly in half-width katakana is
    # Japanese, and its words count like any other.
    path = tmp_path / "episode.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\nﾁｬﾝｽ\n\n2\n00:00:03,000 --> 00:00:04,000\n本当に？\n",
                    encoding="utf-8")
    text = analyzer.extract_text(str(path), "ja")
    assert "ﾁｬﾝｽ" in text
    assert "チャンス" in [lemma for lemma, _r, _s, _o in _tokens(tokenizer, text)]


def test_known_words_are_read_the_same_way(tokenizer, sanitized, tmp_path):
    # One parse everywhere: a half-width KnownWord entry knows the word the library's full-width text holds.
    path = tmp_path / "KnownWord.json"
    path.write_text(json.dumps({"words": [{"dictForm": "ﾅｲﾌ", "knownStatus": "KNOWN"}]}, ensure_ascii=False),
                    encoding="utf-8")
    known_tuples, known_lemmas = analyzer.load_known_words(str(path), tokenizer)
    assert ("ナイフ", "ナイフ") in known_tuples and "ナイフ" in known_lemmas


def test_the_token_store_counts_half_width_words(tmp_path):
    # The store tokenizes with the analyzer's own tokenizer: a half-width subtitle line counts its words.
    path = tmp_path / "episode.txt"
    path.write_text("ﾅｲﾌを置け。\nｽﾌﾟｰﾝならいい。\n", encoding="utf-8")
    counts = token_index.make_tokenizer("ja")(str(path))["counts"]
    assert counts["ナイフ|ナイフ"] == 1 and counts["スプーン|スプーン"] == 1


@pytest.mark.parametrize("script, word", [("asis", "方法"), ("s", "方法"), ("t", "方法")])
def test_chinese_reads_a_kangxi_radical_as_the_word(script, word):
    tokenizer = analyzer.ChineseTokenizer(script=script)
    [(sentence, tokens)] = list(tokenizer.tokenize_sentences("这个⽅法很好。"))
    assert (word, "⽅法") in [(lemma, surface) for lemma, _r, surface, _o in tokens]
    assert "⽅法" in sentence                                   # the sentence keeps the text's own spelling


def test_chinese_zero_width_space_no_longer_cuts_a_word():
    tokens = [token[0] for token in analyzer.ChineseTokenizer().tokenize("学\u200b习很重要。")]
    assert "学习" in tokens and "学" not in tokens and "习" not in tokens


def test_chinese_full_width_latin_is_read_as_the_letter():
    # Ｔ恤 is T恤 'T-shirt' (CC-CEDICT), one word in jieba's dictionary.
    tokens = [(token[0], token[2]) for token in analyzer.ChineseTokenizer().tokenize("你要这件Ｔ恤吗？")]
    assert ("T恤", "Ｔ恤") in tokens
