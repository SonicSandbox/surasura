"""Kana つかれ read as 疲れる (app/analyzer.py § 〜つかれた): after a verb's stem (ENGINE 52, SCHEMA 32), and with no stem
before it where nothing there can be what a つく verb takes (ENGINE 53, SCHEMA 33).

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
    ("王が位につかれた。", ("つか", "突く")),                # after に: 就く's honorific, no stem before it
    ("誰が誰だか見分けつかないほど遠い。", ("つか", "付く")),  # つか + ない: 疲れる is つかれない, never つかない
])
def test_where_the_letters_also_say_a_tsuku_verb_the_taggers_reading_stands(tokenizer, text, word):
    words = _words(tokenizer, text)
    assert word in words and "疲れる" not in {lemma for _s, lemma in words}


def test_a_line_without_tsuka_is_the_same_list(tokenizer):
    # Why: the step looks only at a line holding a token written つか; any other line passes through untouched.
    nodes = analyzer.join_affixes(tokenizer.tagger("今日はとても疲れた。"), analyzer.affix_joins(), library=False)
    assert analyzer._tsukare(nodes) is nodes
    assert analyzer._tsukare([]) == []


def test_a_word_is_never_joined_across_the_lines_space(tokenizer):
    # Why: a space the line holds between the stem and つか sets them apart; one word 歩きつかれ would drop it.
    words = _words(tokenizer, "一日中歩き つかれた。")
    assert ("歩きつかれ", "歩き疲れる") not in words


def test_a_tsuka_at_the_end_of_the_words_is_left_alone(tokenizer):
    # Why: a line cut right after つか (歩き + つか, nothing after it) has no ending to read: the list comes back as it is.
    nodes = tokenizer.tagger("一日中歩きつかれた。")
    at = [w.surface for w in nodes].index("つか")
    assert analyzer._tsukare(nodes[:at + 1]) == nodes[:at + 1]


# --- no stem before it (ENGINE 53) ------------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "つかれたから、先に寝るね。",                       # the line's start
    "「つかれた！もう一歩も歩けない。」",                 # a mark
    "今日はもうつかれたから、先に寝るね。",               # an adverb, walked over to は
    "お前はつかれた顔をしているな。",                     # the topic は
    "君もつかれただろう、少し休もう。",                   # も
    "一日中歩いてつかれた。",                             # a clause's て
    "昨日は眠れなかったのでつかれた。",                   # ので
    "あんなにつかれていたのに、また走り出した。",         # an adverbial に
    "みんなつかれたから、今日はここまでにしよう。",       # a noun used as an adverb
    "五時頃つかれて家に帰った。",                         # 頃, a suffix used as an adverb
    "あーつかれた、やっと終わった。",                     # an interjection
    "そしてすっかりつかれてしまった。",                   # a conjunction and an adverb
    "今日は もう つかれた。",                             # a caption's spaces
    "見ているのさえ少しつかれた。",                       # さえ after の, not after a noun
])
def test_tsukare_with_nothing_before_it_a_tsuku_verb_takes_is_tsukareru(tokenizer, text):
    # Why: the tagger read every one of these as 突く 'poke' + れる and put 突く on the list; 'be tired' takes
    # nothing, and nothing before the letters here can be what is poked, told or got into.
    words = _words(tokenizer, text)
    lemmas = {lemma for _s, lemma in words}
    assert ("つかれ", "疲れる") in words
    assert "突く" not in lemmas and "付く" not in lemmas


def test_otsukare_is_one_word_as_written_in_kanji(tokenizer):
    # Why: お + つかれ is お疲れ 'good work' — the same word the app reads お疲れ as (お joined to 疲れ), never お + 突く.
    assert _words(tokenizer, "おつかれ、また明日ね。")[0] == ("おつかれ", "お疲れ")
    assert _words(tokenizer, "お疲れ、また明日ね。")[0] == ("お疲れ", "お疲れ")


@pytest.mark.parametrize("text", [
    "隙をまんまとつかれた。",                   # を, an adverb between: 突く's passive
    "肩をちょいとつかれて振り返った。",
    "嘘つかれたのが一番悲しかった。",           # a noun right before it: 嘘をつく with を dropped
    "水風呂つかれますか？",                     # 浸かる's potential, に dropped
    "二度つかれた傷がまだ痛む。",               # a count before it
    "狐につかれたような顔をしている。",         # に: 憑く
    "嘘ばかりつかれて、もう誰も信じられない。", # ばかり right after a noun keeps the noun the object
    "何者かに取ッつかれたようだった。",         # ッ is a letter the tagger left as a mark, no boundary
    "神経がつかれた。",                         # が: 気がつく's letters too — left as read
    "隙こそつかれた。",                         # こそ right after a noun: only は / も count as the topic
])
def test_tsukare_after_a_word_a_tsuku_verb_can_take_keeps_the_taggers_reading(tokenizer, text):
    # Why: every other つかれる is a つく verb made passive, honorific or potential, and keeps what it takes before it.
    assert "疲れる" not in {lemma for _s, lemma in _words(tokenizer, text)}


def test_mou_tsukareta_counts_tsukareru_never_tsuku(tokenizer):
    # Why: the list counted 突く 'poke' for もうつかれた, the commonest kana つかれ in general text.
    counted = _counted(tokenizer, "今日はもうつかれたから、先に寝るね。")
    assert "疲れる" in counted and "突く" not in counted


def test_the_tired_word_keeps_the_space_before_it(tokenizer):
    # Why: a caption's space before つかれ is the line's own; the word read from it keeps it, as the tagger's word did.
    nodes = analyzer.join_affixes(tokenizer.tagger("今日は もう つかれた。"), analyzer.affix_joins(), library=False)
    tired = next(w for w in nodes if w.feature.lemma == "疲れる")
    assert tired.white_space == " "


def test_otsuka_with_another_ending_is_left_alone(tokenizer):
    # Why: お + つか + れる (終止形) is no word: only おつかれ (れ) is お疲れ; the rest stays as the tagger read it.
    nodes = tokenizer.tagger("おつかれる。")         # the tagger: お + つか + れる
    words = [(w.surface, w.feature.lemma) for w in analyzer._tsukare(list(nodes))]
    assert "お疲れ" not in {lemma for _s, lemma in words}


def test_only_o_right_before_the_letters_makes_otsukare(tokenizer):
    # Why: お疲れ is お + つかれ written together. Another prefix (超, 'super') is no お, and an お with a word between it
    # and the letters is not their お: neither may become お疲れ (the word between would be swallowed into it).
    assert "お疲れ" not in {lemma for _s, lemma in _words(tokenizer, "超つかれた。")}
    o = list(tokenizer.tagger("お茶"))[0]                       # お as the tagger reads a prefix (御)
    rest = list(tokenizer.tagger("もうつかれた。"))             # もう + つか + れ + た + 。
    assert o.feature.pos1 == "接頭辞" and rest[1].surface == "つか"
    words = [(w.surface, w.feature.lemma) for w in analyzer._tsukare([o] + rest)]
    assert "お疲れ" not in {lemma for _s, lemma in words}
    assert words[1] == ("もう", "もう")


def test_letters_split_by_a_space_are_left_as_the_tagger_read_them(tokenizer):
    # Why: a space between つか and れ (a caption's line broken inside the word) is the line's own; the step joins
    # nothing across a space, as the stem step doesn't either.
    words = _words(tokenizer, "もう つか れた。")
    assert ("つかれ", "疲れる") not in words
    assert "つか" in {s for s, _l in words}
    # お and つかれ with a space between them are not joined into お疲れ either: the space would be lost.
    nodes = analyzer.join_affixes(tokenizer.tagger("お つかれ、また明日ね。"), analyzer.affix_joins(), library=False)
    assert "お疲れ" not in {w.feature.lemma for w in nodes}
    assert "".join(getattr(w, "white_space", "") + w.surface for w in nodes) == "お つかれ、また明日ね。"
