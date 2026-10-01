"""The Japanese tokenizer must treat newlines as hard sentence boundaries. Fugashi consumes
'\\n', so multi-line content — e.g. a YouTube transcript's title / URL / '----' header — used to
merge into the first real sentence, producing garbage example sentences like
"v=J0dSAhzWM6A------…AIを…". This regression test locks the line-by-line splitting fix.

Within a line, a sentence ends where Unicode UAX #29 says (2026-09-27): what closes a sentence
stays with it (!?, 「行くぞ。」, “是黑车吗？”), a full stop inside a number or an abbreviation ends
nothing (３．１４), a quoted question runs on to its verb (本当に？と聞いた), a quotation followed by
a particle or a verb is one sentence with it, and … is a pause (both the user's call).
"""
import pytest

from app import analyzer
from app.analyzer import ChineseTokenizer, JapaneseTokenizer


@pytest.fixture(scope="module")
def ja():
    tokenizer = JapaneseTokenizer()
    return lambda text: [s for s, _toks in tokenizer.tokenize_sentences(text)]


@pytest.fixture(scope="module")
def zh():
    tokenizer = ChineseTokenizer()
    return lambda text: [s for s, _toks in tokenizer.tokenize_sentences(text)]


def test_transcript_header_does_not_merge_into_body_sentence():
    header = "\n".join([
        "動画タイトル",
        "チャンネル | 2024 | 10:00",
        "Captions: ja (auto)",
        "https://www.youtube.com/watch?v=J0dSAhzWM6A",
        "",
        "-" * 60,
        "",
    ])
    body = "AIを賢く使う人が増えている。"

    sentences = [s for s, _toks in JapaneseTokenizer().tokenize_sentences(header + body + "\n")]

    # The body is its own clean sentence...
    assert "AIを賢く使う人が増えている。" in sentences
    # ...and nothing smuggles the URL / video id / dash header into a body sentence.
    leaked = [s for s in sentences if "賢く使う" in s and ("v=" in s or "----" in s or "http" in s)]
    assert not leaked, f"header leaked into a body sentence: {leaked}"


def test_plain_newlines_split_lines_into_separate_sentences():
    # Two caption lines with no punctuation must not become one giant sentence.
    text = "猫が寝ている\n犬が走っている\n"
    sentences = [s for s, _toks in JapaneseTokenizer().tokenize_sentences(text)]
    assert "猫が寝ている" in sentences
    assert "犬が走っている" in sentences


# --- UAX #29: what closes a sentence stays with it ------------------------------------------------ #
def test_a_run_of_terminators_ends_the_sentence_together(ja):
    # SB8a: the ? of !? was cut off as debris, so the question read 反応は! (1,561 library cues hold one).
    assert ja("反応は!? 何色だ？") == ["反応は!?", "何色だ？"]
    assert ja("えっ！？　傘を忘れてきたの？") == ["えっ！？", "傘を忘れてきたの？"], "full-width, and the space goes"


def test_a_closing_bracket_stays_with_the_sentence_it_closes(ja):
    # SB9: the 」 opened the next sentence, where the tokenizer threw it away (「行くぞ。 left open).
    assert ja("「行くぞ。」次だ。") == ["「行くぞ。」", "次だ。"]
    assert ja("そうです。」「うーん、任せるよ」") == ["そうです。」", "「うーん、任せるよ」"], \
        "an opening bracket after it starts the next sentence"


def test_an_opening_bracket_glued_to_a_full_stop_opens_the_next_sentence(ja):
    # The tagger reads a full stop and the next line's opening bracket as one symbol when it knows neither as written
    # — half-width ｡｢ (JIS X 0201), ｡(( , 。〝 — and the bracket went with the sentence before it.
    assert ja("今日は帰るね｡｢またね｣") == ["今日は帰るね｡", "｢またね｣"]
    assert ja("もう寝る｡((眠い…))") == ["もう寝る｡", "((眠い…))"]
    assert ja("そう言った〞。〝次だ〞") == ["そう言った〞。", "〝次だ〞"]
    assert ja("帰るね。｢") == ["帰るね。"], "a bracket alone at the end of the line opens no sentence"


def test_a_full_width_full_stop_ends_a_sentence_but_not_a_number_or_an_abbreviation(ja):
    # ． is the full stop of horizontal official writing; UAX #29 SB6–SB8: a digit or a Latin letter right
    # after it makes it a decimal point or an abbreviation's.
    assert ja("これはペンである．あれは本である．") == ["これはペンである．", "あれは本である．"]
    assert ja("３．１４は円周率。") == ["３．１４は円周率。"]
    assert ja("Ｍｒ．Ｓｍｉｔｈが来た。") == ["Ｍｒ．Ｓｍｉｔｈが来た。"]
    assert ja("１．") == [], "a list number alone is punctuation debris, not a sentence"


def test_an_ellipsis_inside_a_line_is_a_pause(ja):
    # The user's call: … is as often a pause as an end — あの…すみません is one sentence.
    assert ja("そうか…じゃあ行くか。") == ["そうか…じゃあ行くか。"]
    assert ja("あの…すみません") == ["あの…すみません"]


# --- Japanese quotations ------------------------------------------------------------------------- #
def test_a_quoted_question_runs_on_to_its_verb(ja):
    # The quotative と / って cannot begin a sentence; a quoted question keeps its ？ before it.
    assert ja("本当に？と聞いた。") == ["本当に？と聞いた。"]
    assert ja("えっ!?って感じだった。") == ["えっ!?って感じだった。"]


def test_a_full_stop_before_to_is_the_conjunction_and_ends_the_sentence(ja):
    # UniDic tags this と 格助詞 as well; the full stop is what tells 'and then' from a quotative.
    assert ja("ドアを開けた。と、そこには誰もいなかった。") == ["ドアを開けた。", "と、そこには誰もいなかった。"]


def test_a_quotation_taken_by_to_or_a_verb_is_one_sentence(ja):
    # The user's call: kept whole when と / って or a verb follows the closing bracket.
    assert ja("「今日は晴れ。明日は雨」と言った。") == ["「今日は晴れ。明日は雨」と言った。"]
    assert ja("「今日は晴れ」って言った。") == ["「今日は晴れ」って言った。"]
    assert ja("「まあ！」と、うばは　びっくりしました。") == ["「まあ！」と、うばは　びっくりしました。"]
    assert ja("「行くぞ。」走り出した。") == ["「行くぞ。」走り出した。"], "と left out, as fiction writes it"
    assert ja("「彼は『行く。』と言った。」") == ["「彼は『行く。』と言った。」"], "nested quotations"


def test_a_quotation_followed_by_any_particle_is_one_sentence(ja):
    # The user's call (2026-09-27): a particle can't begin a sentence, so the quotation is part of the one it
    # stands in — it read 『吾輩は猫である。 / 名前はまだ無い。』 / で始まる小説を読んだ。
    assert ja("『吾輩は猫である。名前はまだ無い。』で始まる小説を読んだ。") == \
        ["『吾輩は猫である。名前はまだ無い。』で始まる小説を読んだ。"]
    assert ja("「今日は晴れ。明日は雨。」が彼の口癖だ。") == ["「今日は晴れ。明日は雨。」が彼の口癖だ。"], "が"
    assert ja("「行くぞ。」の一言で、皆が走り出した。") == ["「行くぞ。」の一言で、皆が走り出した。"], "の"
    assert ja("「待て。行くな。」なんて、言えなかった。") == ["「待て。行くな。」なんて、言えなかった。"], "副助詞"
    assert ja("「はい。」は便利な言葉だ。") == ["「はい。」は便利な言葉だ。"], "係助詞"


def test_a_quotation_nothing_takes_leaves_its_sentences_apart(ja):
    # Any other follower — a new subject, nothing at all — is no quotative: the inner 。 still ends a sentence.
    assert ja("「はい。」彼女は頷いた。") == ["「はい。」", "彼女は頷いた。"]
    assert ja("「今日は晴れ。明日は雨。」") == ["「今日は晴れ。", "明日は雨。」"]
    assert ja("「好き。」だって。") == ["「好き。」", "だって。"], "a copula is no particle: not decided, as before"


def test_a_quotation_opened_on_an_earlier_line_closes_on_this_one(ja):
    # A novel's speech over two lines: the line break still ends the first sentence, as every line break does,
    # and the closer with no opener on its line closes the quotation that began before it.
    assert ja("「今日は晴れ。\n明日は雨。」と彼は言った。") == ["「今日は晴れ。", "明日は雨。」と彼は言った。"]


def test_unbalanced_and_empty_input(ja):
    assert ja("") == []
    assert ja("「…………」") == [], "a silent reply holds no word"
    assert ja("「まだ終わってない。") == ["「まだ終わってない。"], "an opener that never closes changes nothing"
    assert ja("」と言った。") == ["と言った。"], "a leading closer is still trimmed"


def test_the_boundary_rules_follow_the_saved_boundary_set(monkeypatch):
    # The set stays the user's (logic.sentence_boundaries): without ． a line of them is one sentence.
    monkeypatch.setitem(analyzer.LOGIC, "sentence_boundaries", {"ja": "。！？!?\n"})
    out = [s for s, _t in JapaneseTokenizer().tokenize_sentences("これはペンである．あれは本である．")]
    assert out == ["これはペンである．あれは本である．"]


def test_quotations_in_a_row_are_taken_together_by_what_follows_the_last(ja):
    # Both quotations are what と挨拶を交わした takes: one sentence. With nothing after them they are two lines.
    assert ja("「おはよう。」「おはよう。」と挨拶を交わした。") == ["「おはよう。」「おはよう。」と挨拶を交わした。"]
    assert ja("「おはよう。」「おはよう。」") == ["「おはよう。」", "「おはよう。」"]
    assert ja("「行くぞ。」「うん。」次の日になった。") == ["「行くぞ。」", "「うん。」", "次の日になった。"]


def test_a_comma_after_a_closing_bracket_continues_the_sentence(ja):
    # UAX #29 SB8a: a comma (SContinue) after a terminator and its closing marks continues the sentence.
    assert ja("「わかった。」、と彼女は答えた。") == ["「わかった。」、と彼女は答えた。"]
    assert ja("「わかった。」と彼女は答えた。次の日。") == ["「わかった。」と彼女は答えた。", "次の日。"]


# --- Chinese ------------------------------------------------------------------------------------- #
def test_chinese_closing_marks_stay_with_their_sentence(zh):
    # GB/T 15834-2011: a closing quotation mark belongs to the sentence it closes (it opened the next one).
    assert zh("“是黑车吗？”我问他。") == ["“是黑车吗？”", "我问他。"]
    assert zh("这部电影出品时间是不是很久了？？") == ["这部电影出品时间是不是很久了？？"], "the second ？ is kept"
    assert zh("真的吗？！太好了！") == ["真的吗？！", "太好了！"]


def test_chinese_line_end_ends_the_sentence_where_it_stands(zh):
    # A closing mark at the start of the next line is not pulled back across the line break.
    assert zh("你好！\n”我问他。") == ["你好！", "”我问他。"]
    assert zh("第一句。\r\n第二句。") == ["第一句。", "第二句。"], "Windows line ends"
    assert zh("") == []


def test_a_chinese_ellipsis_and_semicolon_are_pauses_inside_a_sentence(zh):
    # GB/T 15834-2011: 省略号 marks a pause or an omission, 分号 joins the clauses of one sentence — whole examples,
    # not two broken halves.
    assert zh("「唔……也对，你会误解也是应该的。」") == ["「唔……也对，你会误解也是应该的。」"]
    assert zh("《红楼梦》是一本书；我很喜欢。") == ["《红楼梦》是一本书；我很喜欢。"]
    assert zh("我买了书;他买了笔。") == ["我买了书;他买了笔。"], "the half-width semicolon too"
    assert zh("他走了……我们也走吧。") == ["他走了……我们也走吧。"], "the price: a novel's …… runs on"


def test_a_chinese_line_end_and_full_stop_still_end_a_sentence(zh):
    # A line end ends a sentence (a wrapped line stays cut, as in Japanese); ． is a name's dot, never an end.
    assert zh("我今天\n很高兴。") == ["我今天", "很高兴。"]
    assert zh("英國作家達爾文．庫克出版了新書。") == ["英國作家達爾文．庫克出版了新書。"]
    assert zh("你好！我叫小明。") == ["你好！", "我叫小明。"]


def test_the_chinese_sample_reads_its_semicolon_line_as_one_sentence(zh):
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "zh", "patterns_zh_sample.txt")
    text = analyzer.extract_text(path, "zh")
    assert "《红楼梦》是一本书；我很喜欢。" in zh(text)
