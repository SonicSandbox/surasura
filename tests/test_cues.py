"""The cue reader (app/cues.py, P1.3 row 1.3.1): a subtitle's lines with their start and end, each line's words keyed
as a Generate keys them.

Real subtitles from the repo: the 五等分の花嫁 sample (.srt, a BOM, CRLF, furigana in parentheses, speaker labels),
`ja/library_episode.ass` (a broadcast-style .ass: two speakers by colour, a karaoke OP, a sign, a drawing, a comment,
a forced line break, a BOM and CRLF) and `zh/night_market.srt` (Chinese, Traditional and Simplified mixed, SubRip
tags, an English-only line).
"""
import os

import pytest

from app import analyzer, cues

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_SRT = os.path.join(PROJECT_ROOT, "samples", "ja", "HighPriority", "H_priority_sample_2.srt")


@pytest.fixture(autouse=True)
def _sanitized():
    # A Japanese run reads sanitized lemmas (analyzer.main sets it; conftest restores the global).
    analyzer.SANITIZE_JA = True


def _write(tmp_path, name, text, encoding="utf-8", newline="\n"):
    path = tmp_path / name
    with open(path, "w", encoding=encoding, newline=newline) as f:
        f.write(text)
    return str(path)


# --------------------------------------------------------------------------- #
# Reading times and text
# --------------------------------------------------------------------------- #
def test_srt_cues_keep_start_and_end_in_ms_and_text_as_a_generate_cleans_it():
    read = cues.read(SAMPLE_SRT, "ja")
    first, second = read[0], read[1]
    # 00:00:02,419 --> 00:00:03,628 / （風太郎(ふうたろう)）くっ…  — the speaker label and its reading go
    assert (first.start, first.end, first.text) == (2419, 3628, "くっ…")
    # two lines of one cue are one line, joined as extract_text joins them
    assert (second.start, second.end, second.text) == (3962, 6923, "何だ これ センサー 反応しろ！")
    assert [c.index for c in read] == list(range(len(read)))
    assert all(c.caption == c.index for c in read)           # an .srt's cue is its own caption
    # the OP's ♪～ lines hold no Japanese: kept as lines (Anki Miner counts them) but never counted, and sung
    songs = [c for c in read if not c.counted]
    assert songs and all(c.sung and "♪" in c.text for c in songs)


def test_srt_text_is_the_text_a_generate_reads():
    # Every cue, closed as extract_text closes it, is the file's text: nothing a Generate counts is lost or added.
    joined = "".join(analyzer.close_cue(c.text) for c in cues.read(SAMPLE_SRT, "ja") if c.counted)
    assert joined == analyzer.extract_text(SAMPLE_SRT, "ja")


def test_ass_events_keep_their_times_speakers_and_songs(ja_resources_dir):
    read = cues.read(os.path.join(ja_resources_dir, "library_episode.ass"), "ja")
    by_text = {c.text: c for c in read}
    # karaoke timing: kept, cleaned of its \k tags, and sung; an OP style with no karaoke tags is sung too
    assert by_text["君の声が聞こえる"].sung and by_text["遠い空の向こうまで"].sung
    # hundredths: 0:01:33.10 --> 0:01:36.25
    line = by_text["すみません、この本を借りたいんですが。"]
    assert (line.start, line.end, line.sung) == (93100, 96250, False)
    # \N: one event, two lines
    assert "分かりました。 ペンを借りてもいいですか？" in by_text
    # a drawing ({\p1}…) and a Comment line hold no speech; the arrow stays in the cue's own text (it says "runs on")
    assert not any("m 0 0" in c.text or "訳者" in c.text for c in read)
    assert "じゃあ、この小説を読んでから→" in by_text


def test_ass_events_on_screen_together_are_one_caption_per_colour(ja_resources_dir):
    read = cues.read(os.path.join(ja_resources_dir, "library_episode.ass"), "ja")
    by_text = {c.text: c for c in read}
    # one timing, one colour (the \c after the first character doesn't change who speaks): one caption, read as one
    # line (the caption cleaner joins its rows: Anki Miner reads the same)
    assert "それでしたらこちらの用紙に お名前と住所を書いてください。" in by_text
    # one timing, two colours: two speakers, two captions
    yes, thanks = by_text["どうぞ。"], by_text["ありがとうございます。"]
    assert (yes.start, yes.end) == (thanks.start, thanks.end) and yes.caption != thanks.caption


def test_ass_read_through_the_files_own_encoding_and_line_ends(tmp_path):
    # CP932 with CRLF: a broadcast caption file saved by a Japanese tool
    text = ("[Events]\r\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\r\n"
            "Dialogue: 0,0:00:05.00,0:00:07.50,Default,,0,0,0,,今日はいい天気ですね。\r\n")
    path = tmp_path / "cp932.ass"
    path.write_bytes(text.encode("cp932"))
    assert [(c.start, c.end, c.text) for c in cues.read(str(path), "ja")] == [(5000, 7500, "今日はいい天気ですね。")]


def test_srt_timing_variants_and_overlapping_cues_stay_in_file_order(tmp_path):
    # a full stop for the comma, a three-digit hour, a player's coordinates, and two cues that overlap
    text = ("1\n00:00:10.500 --> 00:00:13.000 X1:100 X2:200\nそろそろ帰ろうか。\n\n"
            "2\n00:00:12,000 --> 00:00:14,000\nまだ雨が降ってるよ。\n\n"
            "3\n100:00:01,005 --> 100:00:02,000\n傘を持ってきた？\n")
    read = cues.read(_write(tmp_path, "overlap.srt", text), "ja")
    assert [(c.start, c.end) for c in read] == [(10500, 13000), (12000, 14000), (360001005, 360002000)]
    assert cues.seconds(read[0].start) == 10.5


@pytest.mark.parametrize("name, text", [
    ("empty.srt", ""),
    ("blank.ass", "\n\n"),
    ("notes.txt", "今日はいい天気ですね。"),          # not a subtitle: no cues
])
def test_files_with_no_lines_have_no_cues(tmp_path, name, text):
    assert cues.read(_write(tmp_path, name, text), "ja") == []


def test_a_line_in_another_script_is_a_line_with_no_words(tmp_path):
    # Review #2: Anki Miner counts every line, so the lines around a card are counted as it counts them
    text = ("1\n00:00:01,000 --> 00:00:02,000\n５０本、\n\n2\n00:00:02,100 --> 00:00:03,000\nI'll be back.\n\n"
            "3\n00:00:03,100 --> 00:00:04,000\n用意しておけ。\n")
    read = cues.read(_write(tmp_path, "mixed.srt", text), "ja")
    assert [(c.text, c.counted) for c in read] == [("５０本、", True), ("I'll be back.", False), ("用意しておけ。", True)]
    assert {t.cue for t in cues.tokens(read, "ja")} <= {0, 2}


def test_a_file_in_a_nested_folder_reads_like_any_other(tmp_path):
    nested = tmp_path / "番組" / "シーズン1" / "第01話"
    nested.mkdir(parents=True)
    path = _write(nested, "ep01.ja.srt", "1\n00:00:01,000 --> 00:00:02,500\n行ってきます！\n")
    assert [c.text for c in cues.read(path, "ja")] == ["行ってきます！"]


def test_chinese_cues_drop_markup_and_lines_without_hanzi(zh_resources_dir):
    read = cues.read(os.path.join(zh_resources_dir, "night_market.srt"), "zh")
    texts = [c.text for c in read]
    assert "老闆說他們的湯頭要熬十二個小時。" in texts       # <i>…</i> gone
    assert [c.counted for c in read if c.text == "OK"] == [False]      # no hanzi: a line, never read for words
    # a two-line cue reads as one line, no space between two wide characters (CSS Text 3)
    assert "這家店的牛肉麵非常有名，每天都有很多人排隊。" in texts


# --------------------------------------------------------------------------- #
# Words, cue by cue
# --------------------------------------------------------------------------- #
def _store_words(tmp_path, path, language):
    """The words the token store holds for `path`, indexed as the indexer and Generate index it — and its name tables
    applied in this process from now on, as a Generate applies the store's (names.use_library_tables)."""
    from app import names, token_index as ti
    store = ti.open_store(language, path=str(tmp_path / f"store_{language}.db"))
    try:
        store.reconcile([path], ti.make_tokenizer(language), build_signature=ti.build_signature(language))
        names.use_library_tables(store.names_tables())
        return [(t[0], t[1]) for _s, tokens in store.file_tokens(path) for t in tokens]
    finally:
        store.close()


@pytest.mark.parametrize("name", ["samples/ja/HighPriority/H_priority_sample_2.srt",
                                  "tests/Test Resources/ja/library_episode.ass",
                                  "tests/Test Resources/ja/phrases_sample.srt"])
def test_the_cue_readers_words_are_the_token_stores_for_the_same_file(tmp_path, name):
    # Intent review #12: the pick reads exactly the words the list counted — every word, in order, keyed the same.
    # (A karaoke event is the one thing a Generate never reads; the pick still sees it, marked sung.)
    path = os.path.join(PROJECT_ROOT, name)
    stored = _store_words(tmp_path, path, "ja")         # 三玖, said again and again, is one word: the store's table
    read = cues.read(path, "ja")
    found = cues.tokens(read, "ja")
    assert [(t.lemma, t.reading) for t in found if read[t.cue].counted] == stored


def test_each_word_is_placed_in_the_cue_it_was_said_in():
    read = cues.read(SAMPLE_SRT, "ja")
    found = cues.tokens(read, "ja")
    # every word's surface stands in its own cue's text, and each carries the node it was read from
    assert all(t.surface in read[t.cue].text for t in found)
    assert all(t.node is not None and t.node.surface == t.surface for t in found)
    reaction = next(t for t in found if t.lemma == "反応")
    assert reaction.cue == 1 and reaction.node.feature.pos1 == "名詞"
    assert [t.cue for t in found] == sorted(t.cue for t in found)


def test_a_joined_word_comes_whole_with_its_parts(ja_resources_dir):
    # 図書館 / 図書カード: words made of words come out as one token (join_affixes), its node a JoinedWord
    found = cues.tokens(cues.read(os.path.join(ja_resources_dir, "library_episode.ass"), "ja"), "ja")
    lemmas = [t.lemma for t in found]
    assert "図書館" in lemmas or "市立図書館" in lemmas
    joined = [t for t in found if isinstance(t.node, analyzer.JoinedWord)]
    assert joined and all(len(t.node.parts) > 1 for t in joined)


def test_chinese_tokens_are_cut_by_the_chinese_tokenizer(zh_resources_dir):
    read = cues.read(os.path.join(zh_resources_dir, "night_market.srt"), "zh")
    found = cues.tokens(read, "zh", script="s")
    # read in Simplified, as the library is read with zh_script "s"
    assert any(t.lemma == "频道" for t in found) and all(t.node is None for t in found)
    assert {t.cue for t in found} == {c.index for c in read if c.counted}
    # read in Simplified, each word still carries the file's own spelling (review #3: Anki Miner's card front)
    noodles = next(t for t in found if t.lemma == "牛肉面" and t.cue == 2)
    assert noodles.written == "牛肉麵"


def test_no_cues_no_tokens():
    assert cues.tokens([], "ja") == []
