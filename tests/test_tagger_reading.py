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


def test_a_character_read_as_several_words_gives_its_spelling_to_the_first(tokenizer, sanitized, monkeypatch):
    # ㍿ is 株式会社, which unidic-lite reads as 株式 + 会社: the sentence must still show ㍿ exactly once.
    line = "㍿山田の社員です。"
    sentences = list(tokenizer.tokenize_sentences(line))
    assert [s for s, _ in sentences] == [line]
    # The two pieces spell the dictionary compound 株式会社, one word — shown as the ㍿ it was read from.
    surfaces = {lemma: surface for lemma, _r, surface, _o in sentences[0][1]}
    assert surfaces["株式会社"] == "㍿"
    # Left in pieces (no compound table), the first piece carries the character and the second nothing.
    monkeypatch.setattr(analyzer, "compound_joins", dict)
    surfaces = {lemma: surface for lemma, _r, surface, _o in list(tokenizer.tokenize_sentences(line))[0][1]}
    assert surfaces["株式"] == "㍿" and surfaces["会社"] == ""


def test_every_node_keeps_the_texts_own_spelling():
    # Surfaces tile the line (MeCab skips only ASCII spaces, as it always did) — what a source anchor relies on.
    line = "ｷﾐの⽅がﾏｼだって、新\u200b幹線で言われた。"
    nodes = analyzer.Tagger()(line)
    assert "".join(node.surface for node in nodes) == line
    assert all(isinstance(node, analyzer.ReadNode) for node in nodes)


def test_plain_text_nodes_are_copies_sharing_each_dictionary_entrys_feature():
    # Every node is a copy (ReadNode) carrying fugashi's own reading of it. fugashi splits a node's 26 feature fields
    # anew for every token — a fifth of a full re-read, where a library's millions of tokens are a few tens of
    # thousands of dictionary entries — so the same entry met again shares the one reading already made.
    tagger = analyzer.Tagger()
    line = "今日は晴れです。今日は雨です。"
    nodes = tagger(line)
    assert all(isinstance(node, analyzer.ReadNode) for node in nodes)
    assert "".join(node.surface for node in nodes) == line
    fresh = tagger._tagger(line)                     # fugashi's own nodes (valid until its next call): the same
    assert [(n.surface, n.feature, n.is_unk, n.white_space) for n in nodes] == \
        [(n.surface, n.feature, n.is_unk, n.white_space) for n in fresh]
    kyou = [node for node in nodes if node.surface == "今日"]
    assert kyou[0].feature is kyou[1].feature


def test_the_shared_readings_are_bounded_and_start_again_when_full(monkeypatch):
    # A process that tags a whole library keeps only the entries met lately (about 7 MB): full, it starts again —
    # and every node still carries fugashi's reading, an unknown word's included (its text names it: word_lemma).
    monkeypatch.setattr(analyzer, "_FEATURES", {})
    monkeypatch.setattr(analyzer, "_FEATURES_KEPT", 3)
    tagger = analyzer.Tagger()
    line = "図書館でグリムジョーという名前の本を読んだ。"
    nodes = tagger(line)
    assert len(analyzer._FEATURES) <= 3
    fresh = tagger._tagger(line)
    assert [(n.surface, n.feature, n.is_unk) for n in nodes] == [(n.surface, n.feature, n.is_unk) for n in fresh]


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


# --- one character, two code points; a stretched vowel ------------------------------------------------------------ #
# ～ (U+FF5E) is the JIS wave dash as Windows decodes it, 〜 (U+301C) as UniDic writes it; the 常用漢字表 allows 叱 for 𠮟,
# which unidic-lite doesn't know. Inside a word a wave dash, or a run of marks, is one prolonged sound mark (ー); a mark
# the tagger still leaves alone after hiragana or a kanji only lengthens the vowel, and the word is read without it.

def test_a_wave_dash_after_a_word_is_no_particle(tokenizer, sanitized):
    # UniDic's one entry for ～ reads it から: every such line counted a particle that was never said.
    lemmas = [lemma for lemma, _r, _s, _o in _tokens(tokenizer, "それってなに～？")]
    assert "何" in lemmas and "から" not in lemmas


@pytest.mark.parametrize("line, lemma, surface", [
    ("今日はすご～い日だ。", "凄い", "すご～い"),          # a wave dash inside a word is UniDic's すごーい
    ("今日はすご〜〜い日だ。", "凄い", "すご〜〜い"),       # a run of marks is one
    ("ようこそ、いらっしゃ～い！", "いらっしゃる", "いらっしゃ～い"),
    ("外は暗～い。", "暗い", "暗～い"),                    # after a kanji
    ("ほら、す〜ぐ終わるよ。", "直ぐ", "す〜ぐ"),           # no stretched spelling listed: read without the mark
])
def test_a_stretched_word_is_the_word_and_keeps_its_spelling(tokenizer, sanitized, line, lemma, surface):
    keys = {(lemma_, surface_) for lemma_, _r, surface_, _o in _tokens(tokenizer, line)}
    assert (lemma, surface) in keys
    assert not {"から", "イ", "ー", "〜", "～"} & {lemma_ for lemma_, _s in keys}


def test_a_long_vowel_in_katakana_is_part_of_the_word(tokenizer, sanitized):
    # Katakana writes a long vowel with ー (オットー): read without it, the name would be 夫.
    keys = {(lemma, surface) for lemma, _r, surface, _o in _tokens(tokenizer, "オットーが来た。")}
    assert ("オットー", "オットー") in keys


def test_a_wave_dash_between_kanji_is_a_range_not_a_stretch(tokenizer, sanitized):
    read, at = analyzer.tagger_text("受付は月曜～金曜です。")
    assert read == "受付は月曜〜金曜です。"
    lemmas = [lemma for lemma, _r, _s, _o in _tokens(tokenizer, "受付は月曜～金曜です。")]
    assert "月曜" in lemmas and "金曜" in lemmas


def test_a_stretched_line_maps_back_onto_its_text():
    line = "もうすご〜〜い、す〜ぐだよ！"
    read, at = analyzer.tagger_text(line)
    assert read == "もうすごーい、すーぐだよ！"               # each stretch read as one ー
    _read_back(read, at, line)
    unread = {line.index("〜", line.index("す〜ぐ"))}
    read, at = analyzer.tagger_text(line, unread)
    assert read == "もうすごーい、すぐだよ！"
    _read_back(read, at, line)


# A dash drawn out (─ ━ ― —) is far more often the dash between two words than a stretch, so it is read as one ー only
# where it can't be that dash: before a ん that ends the word, or between katakana where the word goes on after a ッ,
# a small kana or ン — none of which begins a word.

@pytest.mark.parametrize("line, lemma, surface", [
    ("観客が「ザ─────ック！」と叫んだ。", "ザーック", "ザ─────ック"),       # one word, as ザ～ック is: no ザ + ック
    ("お母さ───ん！ご飯まだ？", "さん", "さ───ん"),                         # no さ + ん read as an interjection
    ("ド────ン！と音がした。", "どーん", "ド────ン"),                       # no ン read as the auxiliary ず
])
def test_a_dash_drawn_out_inside_a_word_is_a_stretch(tokenizer, sanitized, line, lemma, surface):
    keys = {(lemma_, surface_) for lemma_, _r, surface_, _o in _tokens(tokenizer, line)}
    assert (lemma, surface) in keys
    assert not {"ザ", "ック", "んっ", "ず"} & {lemma_ for lemma_, _s in keys}
    read, at = analyzer.tagger_text(line)
    assert not set("─━―—") & set(read)
    _read_back(read, at, line)


@pytest.mark.parametrize("line, words", [
    ("それは──あなたのせいだ。", ["其れ", "は", "貴方", "の", "所為", "だ"]),   # the dash between two words
    ("店員──ミカが答えた。", ["店員", "ミカ", "が", "答える", "た"]),           # katakana after it can begin a word
    ("無理かも──って思った。", ["無理", "か", "も", "って", "思う", "た"]),     # a hiragana っ that goes on: って
    ("待て──ッ！", ["待つ"]),                                                 # a ッ that ends it: a shout's catch
])
def test_a_dash_between_words_stays_a_dash(tokenizer, sanitized, line, words):
    assert analyzer.tagger_text(line) == (line, None)
    assert [lemma for lemma, _r, _s, _o in _tokens(tokenizer, line)] == words


def test_katakana_words_with_a_long_vowel_take_the_fast_path():
    # One ー between kana is how it is written — nothing to read differently.
    assert analyzer.tagger_text("コーヒーとラーメンを頼んだ。") == ("コーヒーとラーメンを頼んだ。", None)


def test_the_allowed_form_of_a_joyo_kanji_is_read_as_its_word(tokenizer, sanitized):
    keys = {(lemma, surface) for lemma, _r, surface, _o in _tokens(tokenizer, "先生に𠮟られた。𠮟責を受けた。")}
    assert ("叱る", "𠮟ら") in keys and ("叱責", "𠮟責") in keys
