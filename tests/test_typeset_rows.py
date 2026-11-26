"""A line typeset one character an event (analyzer._join_lines, ENGINE_REVISION 51).

An effect draws a line one character at a time: one .ass event per character, every event with one timing. A
Generate reads one timing's events as one caption, and Japanese joins a caption's rows with a space — the subtitler's
line break, which the tagger reads as a word boundary. Read so, よろしくお願いします typeset a character an event became
よ ろ し く お 願 い し ま す: the tagger made 御 + 願 (がん, 'a prayer') of お願い, and Connect handed 願 to Anki Miner.
No subtitler breaks a line after one character, so two rows of one character each join with nothing between them;
every other row keeps its space, and Chinese is unchanged.

Constructed lines in real Japanese (the effect's override tags as an effect writes them); the app's own readers.
"""
import pytest

from app import analyzer, cues

_HEAD = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sign,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1
Style: DialogJP,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


@pytest.fixture(autouse=True)
def _sanitized():
    analyzer.SANITIZE_JA = True     # a Japanese run reads sanitized lemmas (analyzer.main sets it; conftest restores)


def _typeset(line, start="0:00:10.00", end="0:00:13.50"):
    """One Dialogue event per character of `line`, one timing, each placed by its own override (as an effect does)."""
    return "".join(f"Dialogue: 0,{start},{end},Sign,,0,0,0,fx,{{\\an5\\blur2\\move({700 + 40 * n},1035,"
                   f"{690 + 40 * n},1035,0,500)}}{ch}\n" for n, ch in enumerate(line))


def _write(tmp_path, body, name="ep03.ja.ass"):
    path = tmp_path / name
    path.write_text(_HEAD + body, encoding="utf-8-sig", newline="\r\n")      # a BOM and CRLF, as such files come
    return str(path)


def _words(text):
    tokenizer = analyzer.JapaneseTokenizer(library=False)
    return [token[0] for _sentence, tokens in tokenizer.tokenize_sentences(text) for token in tokens]


def test_one_character_rows_join_with_nothing_between_them():
    """The rule itself: two rows of one character each join with nothing; a row of more keeps the space, on either
    side of a one-character row (え / 何でそうなるの: え is said alone); one row or none is itself; Chinese as before."""
    join = analyzer._join_lines
    assert join(list("お願いします")) == "お願いします"
    assert join(["門番は城への侵入者を", "厳しく取り調べた"]) == "門番は城への侵入者を 厳しく取り調べた"
    assert join(["え", "何でそうなるの"]) == "え 何でそうなるの"
    assert join(["本当に", "う", "そ"]) == "本当に うそ"
    assert join(["はい"]) == "はい" and join([]) == ""
    assert join(["我", "觉", "得"], "zh") == "我觉得" and join(["我买了", "T恤"], "zh") == "我买了 T恤"


def test_a_generate_reads_a_line_typeset_a_character_an_event_as_its_words(tmp_path):
    """parse_ass (a Generate, the token store): the caption is one line, お願い its word — never 御 + 願 — and a
    dialogue line beside it reads as before."""
    body = (_typeset("よろしくお願いします")
            + "Dialogue: 0,0:00:15.00,0:00:18.00,DialogJP,,0,0,0,,門番は城への侵入者を\n"
            + "Dialogue: 0,0:00:15.00,0:00:18.00,DialogJP,,0,0,0,,厳しく取り調べた\n")
    read = analyzer.parse_ass(_write(tmp_path, body), "ja")
    assert "よろしくお願いします。" in read
    words = _words(read)
    assert "お願い" in words and "願" not in words and "御" not in words
    assert {"門番", "侵入者", "取り調べる"} <= set(words)


def test_connects_cue_reader_hands_on_the_lines_word_not_a_character(tmp_path):
    """cues.read takes one timing's events as one cue, joined as a Generate joins them, and cues.tokens reads it so:
    the word a card is made for is お願い, and the line a card shows reads whole (no space after each character)."""
    read = cues.read(_write(tmp_path, _typeset("よろしくお願いします")), "ja")
    assert [cue.text for cue in read] == ["よろしくお願いします"]
    lemmas = [token.lemma for token in cues.tokens(read, "ja")]
    assert "お願い" in lemmas and "願" not in lemmas
    text, _starts = cues._text(read, "ja")
    assert text == "よろしくお願いします。"


def test_an_empty_or_one_event_caption_is_unchanged(tmp_path):
    """Edge cases: a file of no events reads as nothing; a one-character caption alone (え) is itself."""
    assert analyzer.parse_ass(_write(tmp_path, ""), "ja").strip() == ""
    read = analyzer.parse_ass(_write(tmp_path, "Dialogue: 0,0:00:01.00,0:00:02.00,DialogJP,,0,0,0,,え\n", "e.ass"), "ja")
    assert read.strip() == "え。"
