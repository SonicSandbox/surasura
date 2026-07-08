"""The Japanese tokenizer must treat newlines as hard sentence boundaries. Fugashi consumes
'\\n', so multi-line content — e.g. a YouTube transcript's title / URL / '----' header — used to
merge into the first real sentence, producing garbage example sentences like
"v=J0dSAhzWM6A------…AIを…". This regression test locks the line-by-line splitting fix.
"""
from app.analyzer import JapaneseTokenizer


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
