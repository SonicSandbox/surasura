"""A subtitle line loses its format's markup, never its letters.

The cleaner used to delete every ASCII letter and digit from a cue, which is how 30階の中野さんの (the repo's own
sample subtitle) became 階の中野さんの, 我有2个苹果 became 我有个苹果, T恤 became 恤, and SubRip's <b>…</b> left
<>…</> behind. Latin letters and digits are part of what a line says; what is not text is the format's own
markup — SubRip's HTML-style tags, ASS's override blocks, its \\N / \\n / \\h escapes and its drawings. A line
with no Japanese (Chinese) at all is still dropped, as before, so an English translation line never reaches a
sentence, and a Latin token that does is never counted (analyzer.main's target-language test).

The sample subtitle's lines are real (samples/ja/HighPriority/H_priority_sample_2.srt); the others are made up in
the shapes streaming subtitles (<b> on every line) and broadcast .ass captions write, and ordinary Chinese.
"""
from app import analyzer


def _clean(text, language="ja"):
    return analyzer.clean_subtitle_text(text, language)


def _sentences(path, language="ja"):
    tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    return list(tokenizer.tokenize_sentences(analyzer.extract_text(str(path), language)))


# --- letters and digits are content ---------------------------------------------------------------- #
def test_digits_and_latin_words_stay_in_the_line():
    """30階 'the 30th floor', No.６, iPhone, Tシャツ: stripping the Latin changed what each line says."""
    assert _clean("30階の中野(なかの)さんの") == "30階の中野さんの"
    assert _clean("(ﾀﾅｶ)部屋は No.６｡") == "部屋は No.６｡"
    assert _clean("iPhoneを買った") == "iPhoneを買った"
    assert _clean("Tシャツを着る") == "Tシャツを着る"


def test_chinese_digits_and_latin_stay_too():
    """我有2个苹果 'I have 2 apples' and T恤 'T-shirt' (CC-CEDICT) lost their meaning with the letters."""
    assert _clean("我有2个苹果。", "zh") == "我有2个苹果。"
    assert _clean("我买了一件T恤", "zh") == "我买了一件T恤"


# --- SubRip's markup -------------------------------------------------------------------------------- #
def test_subrip_tags_go_whole():
    """<b>, <i> and <font color="…"> are formatting; before, their letters went and <>…</> stayed."""
    assert _clean("<b>てか ﾍﾟﾝ貸してよ</b>") == "てか ﾍﾟﾝ貸してよ"
    assert _clean("<i>我らは北の砦を守り抜くため</i>") == "我らは北の砦を守り抜くため"
    assert _clean('<font color="#ffff00">行くぞ</font>') == "行くぞ"
    assert _clean("<B><I>行くぞ</I></B>") == "行くぞ", "tag names in capitals are the same tags"


def test_a_line_that_is_only_markup_is_empty():
    """Nothing left once the markup goes: an empty line, which the cue assembly drops."""
    assert _clean("<i></i>") == ""
    assert _clean("{\\an8}") == ""
    assert _clean("  ") == ""


def test_japanese_brackets_are_not_tags():
    """Only an ASCII < + a Latin letter opens a tag; 〈…〉 (U+3008/9) around a remote voice is text."""
    assert _clean("〈もしもし 聞こえる？〉") == "〈もしもし 聞こえる？〉"


def test_a_leading_dialogue_dash_goes_in_chinese_as_in_japanese():
    """'- ' opening a line marks a speaker change in either language — one format rule, not a language's."""
    assert _clean("- 行こう") == "行こう"
    assert _clean("- 你好", "zh") == "你好"


# --- ASS: escapes and drawings ---------------------------------------------------------------------- #
def test_ass_line_breaks_join_like_an_srt_cues_lines():
    """\\N (forced) and \\n (soft) break a line, \\h is a hard space — the ASS spec's escapes. Before, the N
    went and a lone backslash stayed in the example (そうだ\\お前に話がある。)."""
    assert analyzer.ass_dialogue_text("そうだ\\Nお前に話がある") == "そうだ お前に話がある"
    assert analyzer.ass_dialogue_text("そうだ\\nお前に話がある") == "そうだ お前に話がある"
    assert analyzer.ass_dialogue_text("えっと\\hその") == "えっと その"
    assert "\\" not in analyzer.ass_dialogue_text("我觉得\\N他不会来", "zh")


def test_an_english_line_of_a_bilingual_event_is_dropped_like_an_srt_line():
    """Each line of an event is kept only if it holds Japanese, as an .srt cue's lines are: the English
    translation line under the Japanese one never reaches the sentence."""
    assert analyzer.ass_dialogue_text("こんにちは\\NHello") == "こんにちは"
    assert analyzer.ass_dialogue_text("Hello\\Nこんにちは") == "こんにちは"
    assert analyzer.ass_dialogue_text("Only English here") == ""


def test_override_blocks_go_even_inside_a_label():
    """The broadcast captions' style blocks sit even inside a speaker label's brackets."""
    raw = "{\\pos(232,497)\\fscx50}（{\\fscx100}父{\\fscx50}）{\\fscx100}古い井戸の話は本当だな{\\fscx50}。"
    assert analyzer.ass_dialogue_text(raw) == "古い井戸の話は本当だな。"


def test_an_ass_drawing_is_not_text():
    """With \\p1 the text after the block is a vector drawing until \\p0 (the spec's drawing mode): its
    commands are no words, and a sign's text after the drawing stays."""
    assert analyzer.ass_dialogue_text("{\\p1}m 0 0 l 100 0 100 100 0 100{\\p0}看板を見ろ") == "看板を見ろ"
    assert analyzer.ass_dialogue_text("{\\an7\\pos(10,10)\\p2}m 0 0 l 300 0 300 80 0 80") == ""
    assert analyzer.ass_dialogue_text("{\\pos(10,10)}位置の指定は描画ではない") == "位置の指定は描画ではない", \
        "\\pos is no \\p: only \\p + a number switches drawing on"


# --- end to end: the file as the app reads it ------------------------------------------------------- #
def test_a_windows_srt_with_tags_and_digits_reads_as_speech(tmp_path):
    """BOM, CRLF, <b> on every line and digits, through extract_text and the tokenizer — the token store's
    path. The number stays, so the number guard sees it: 回目 is no word after 398 (三回目 = 三 + 回 + 目)."""
    path = tmp_path / "ep02.srt"
    path.write_bytes(("﻿1\r\n00:00:02,419 --> 00:00:03,628\r\n<b>30階の中野(なかの)さんの</b>\r\n"
                      "<b>家庭教師をしている</b>\r\n\r\n"
                      "2\r\n00:00:04,000 --> 00:00:06,000\r\n<i>398回目の挑戦だ</i>\r\n").encode("utf-8"))
    sentences = _sentences(path)
    texts = [s for s, _t in sentences]
    assert "30階の中野さんの家庭教師をしている。" in texts, texts
    assert "398回目の挑戦だ。" in texts, texts
    assert not any("<" in s or ">" in s for s in texts), texts
    lemmas = {lemma for _s, tokens in sentences for lemma, _r, _surface, _o in tokens}
    assert "回目" not in lemmas, "the number guard keeps 回目 apart after a number"


def test_an_ass_event_with_a_break_and_a_bilingual_line(tmp_path):
    """An .ass file end to end: \\N inside the Japanese, an English line after it, a drawing event."""
    path = tmp_path / "ep13.ja.ass"
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an8}そうだ\\Nお前に話がある\\NThere's something\n"
        "Dialogue: 0,0:00:03.00,0:00:05.00,Sign,,0,0,0,,{\\p1}m 0 0 l 100 0 100 100{\\p0}\n",
        encoding="utf-8")
    texts = [s for s, _t in _sentences(path)]
    assert texts == ["そうだお前に話がある。"], texts


def test_chinese_subtitle_keeps_its_digits_end_to_end(tmp_path):
    path = tmp_path / "ep01.zh.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:03,000\n我有2个苹果。\n\n"
                    "2\n00:00:03,000 --> 00:00:05,000\n<i>我买了一件T恤</i>\n", encoding="utf-8")
    sentences = _sentences(path, "zh")
    texts = [s for s, _t in sentences]
    assert "我有2个苹果。" in texts and "我买了一件T恤。" in texts, texts
    words = {word for _s, tokens in sentences for word, _r, _surface, _o in tokens}
    assert "T恤" in words and "恤" not in words, words
