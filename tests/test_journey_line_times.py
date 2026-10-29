"""The journey's line times come from Connect's line reader (E5.1, ✅ D2 2026-10-07): the time a report sentence shows,
the line Anki Miner cuts a card from and the clip ▶ will cut name the same line.

Before E5.1 the report found a sentence's time by searching its text in the raw file and reading the cue header
before it: whole seconds, the start only, and no time at all when the text search missed — 41 % of the sentences of
twelve real broadcast episodes (.ass) and 24 % of a real anime .srt (`tracks/engine/work/E5.1/scope.md`). Now the
times are the cue reader's (`app/cues.py`), to the millisecond, start and end. One scenario per disagreement found:

- an .ass line with override tags and a forced break ({\\c&H…&}, \\N);
- one caption made of two events on screen together, a reading row the caption cleaner takes out;
- a sentence said across two lines (a ➡ runs on): its first line's start to its last line's end;
- a sentence under the text search's five characters (どうぞ。);
- a sentence said more than once: its first time;
- a short sentence also inside, or at the start of, a longer line said before it: its own line;
- whole seconds before, milliseconds now;
- a file read in its own encoding and line ends (a BOM, CRLF, CP932) gives the same lines.

Real data: `tests/Test Resources/ja/library_episode.ass`, `tv_captions.ass`, `placed_episode.srt`,
`phrases_sample.srt`, `zh/night_market.srt` and the 五等分の花嫁 sample `samples/ja/HighPriority/H_priority_sample_2.srt`.
"""
import os

import pytest

from app import analyzer, cues
from app.static_html_generator import AnchorFinder, _intern_sources

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(PROJECT_ROOT, "tests", "Test Resources")
EPISODE = os.path.join(RESOURCES, "ja", "library_episode.ass")
CAPTIONS = os.path.join(RESOURCES, "ja", "tv_captions.ass")
SAMPLE_SRT = os.path.join(PROJECT_ROOT, "samples", "ja", "HighPriority", "H_priority_sample_2.srt")
SUBTITLES = [(EPISODE, "ja"), (CAPTIONS, "ja"), (os.path.join(RESOURCES, "ja", "placed_episode.srt"), "ja"),
             (os.path.join(RESOURCES, "ja", "phrases_sample.srt"), "ja"), (SAMPLE_SRT, "ja"),
             (os.path.join(RESOURCES, "zh", "night_market.srt"), "zh")]


@pytest.fixture(autouse=True)
def _sanitized():
    analyzer.SANITIZE_JA = True         # as every Japanese run sets it (conftest restores the global)


def _tokenizer(language):
    return analyzer.ChineseTokenizer() if language == "zh" else analyzer.JapaneseTokenizer()


def _sentences(path, language):
    """The report's sentences for `path`, as a Generate yields them: extract_text, then the tokenizer."""
    text = analyzer.extract_text(path, language) or ""
    return [sentence for sentence, _tokens in _tokenizer(language).tokenize_sentences(text)]


def _readers_lines(path, language):
    """{sentence: (start, end) ms} as Connect reads the file: the cues `cues.tokens` puts each sentence's words in,
    the first time it is said."""
    read = cues.read(path, language)
    spans = {}
    for token in cues.tokens(read, language, tokenizer=_tokenizer(language)):
        spans.setdefault(id(token.sentence), (token.sentence, []))[1].append(token.cue)
    out = {}
    for sentence, at in sorted(spans.values(), key=lambda item: min(item[1])):
        if read[min(at)].counted:
            out.setdefault(sentence, (read[min(at)].start, read[max(at)].end))
    return out


def _seconds(span):
    return tuple(cues.seconds(ms) for ms in span)


def _old_cue_seconds(path, sentence):
    """What the report showed before E5.1 for `sentence`: the whole second of the cue header before its text-search
    anchor, or None when the search missed. Kept here only to show each scenario was a disagreement."""
    import bisect
    import re
    finder = AnchorFinder()
    anchor = finder.anchor(path, sentence)
    if not anchor:
        return None
    raw = finder._raw(path)
    pattern = (re.compile(r"^Dialogue:[^,]*,\s*(\d{1,2}):(\d{2}):(\d{2})[.:](\d{1,2})", re.M)
               if path.lower().endswith((".ass", ".ssa")) else re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->"))
    found = [(m.end(), int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) for m in pattern.finditer(raw)]
    i = bisect.bisect_right([offset for offset, _s in found], raw.find(anchor)) - 1
    return found[i][1] if i >= 0 else None


# --- the done condition: the journey's line times equal the cue reader's for the same line ----------------------- #
@pytest.mark.parametrize("path,language", SUBTITLES, ids=[os.path.basename(p) for p, _l in SUBTITLES])
def test_every_report_sentence_takes_the_line_connect_reads_it_on(path, language):
    """Every sentence a Generate reads from a real subtitle gets the start and end of the cues Connect's line reader
    puts its words in — never a time of its own."""
    readers = _readers_lines(path, language)
    finder = AnchorFinder(language=language)
    sentences = [s for s in dict.fromkeys(_sentences(path, language)) if s in readers]
    assert sentences, "the file should give sentences"
    for sentence in sentences:
        assert finder.line(path, sentence) == _seconds(readers[sentence]), sentence


# --- one scenario per disagreement --------------------------------------------------------------------------------- #
def test_an_ass_line_with_override_tags_gets_its_time():
    """それでしたら{\\c&H00FFFFFF&}こちらの用紙に + お名前と住所を書いてください。 (two events of one caption, a colour
    tag inside the first): the text search never found it, so it had no time."""
    sentence = "それでしたらこちらの用紙にお名前と住所を書いてください。"
    assert sentence in _sentences(EPISODE, "ja")
    assert _old_cue_seconds(EPISODE, sentence) is None, "before: no time"
    assert AnchorFinder().line(EPISODE, sentence) == (103.0, 106.5)


def test_a_forced_break_inside_a_line_is_the_same_line():
    """分かりました。\\Nペンを借りてもいいですか？ — the second sentence of an event with a forced break."""
    sentence = "ペンを借りてもいいですか？"
    assert sentence in _sentences(EPISODE, "ja")
    assert AnchorFinder().line(EPISODE, sentence) == (107.0, 109.3)


def test_a_caption_with_a_reading_row_taken_out_gets_its_time():
    """《門番は城への侵入者を / 厳しく取り調べた》 on screen together, with the reading row もんばん the caption cleaner
    takes out: the reader's line, where the search found nothing."""
    sentence = next(s for s in _sentences(CAPTIONS, "ja") if "門番" in s)
    assert _old_cue_seconds(CAPTIONS, sentence) is None, "before: no time"
    assert AnchorFinder().line(CAPTIONS, sentence) == (5.1, 8.4)


def test_a_sentence_said_across_two_lines_runs_from_the_first_start_to_the_last_end():
    """長老の話によれば➡ / この村には古い言い伝えがある。 — one sentence over two cues (a ➡ runs on): the clip is both."""
    sentence = next(s for s in _sentences(CAPTIONS, "ja") if "長老" in s)
    assert "言い伝え" in sentence, "one sentence over both lines"
    assert AnchorFinder().line(CAPTIONS, sentence) == (11.5, 16.8)
    sentence = next(s for s in _sentences(EPISODE, "ja") if s.startswith("じゃあ"))
    assert AnchorFinder().line(EPISODE, sentence) == (121.0, 127.5)


def test_a_sentence_under_five_characters_gets_its_time():
    """どうぞ。 — too short for the text search (MIN_LEN 5): no time before, its own line now (shared on screen with
    ありがとうございます。 in another colour)."""
    assert "どうぞ。" in _sentences(EPISODE, "ja")
    assert _old_cue_seconds(EPISODE, "どうぞ。") is None
    assert AnchorFinder().line(EPISODE, "どうぞ。") == (109.3, 112.1)


def _srt(tmp_path, cues_, name="ep.srt", encoding="utf-8", newline="\n"):
    blocks = [f"{n}\n{start} --> {end}\n{text}\n" for n, (start, end, text) in enumerate(cues_, 1)]
    path = tmp_path / name
    with open(path, "w", encoding=encoding, newline=newline) as f:
        f.write("\n".join(blocks))
    return str(path)


# Lines from the 五等分の花嫁 sample, the short ones said again later
REPEATED = [("00:02:40,243", "00:02:41,286", "よう…"),
            ("00:02:45,123", "00:02:46,124", "うっ… うわああっ！"),
            ("00:02:47,208", "00:02:50,795", "えっと その辺にないかな？"),
            ("00:03:10,500", "00:03:12,000", "上杉さんがいるから"),
            ("00:07:40,001", "00:07:40,835", "うっ…"),
            ("00:09:44,417", "00:09:45,251", "えっと その辺にないかな？")]


def test_a_sentence_said_twice_is_its_first_time(tmp_path):
    """えっと その辺にないかな？ is said at 2:47 and again at 9:44: the search found it twice, so it had no time; the
    line is its first time, as the pick takes the earliest of equal lines."""
    path = _srt(tmp_path, REPEATED)
    sentence = "えっとその辺にないかな？"
    assert sentence in _sentences(path, "ja")
    assert _old_cue_seconds(path, sentence) is None, "before: two places, no time"
    assert AnchorFinder().line(path, sentence) == (167.208, 170.795)


def test_a_short_sentence_is_its_own_line_not_the_start_of_a_longer_one(tmp_path):
    """うっ… also opens うっ… うわああっ！ at 2:45; said alone at 7:40, that is its line."""
    path = _srt(tmp_path, REPEATED)
    assert "うっ…" in _sentences(path, "ja")
    assert AnchorFinder().line(path, "うっ…") == (460.001, 460.835)


def test_a_short_sentence_is_its_own_line_not_inside_a_longer_one(tmp_path):
    """うん｡ stands inside そっか うん｡ said first: its own line is the later one."""
    path = _srt(tmp_path, [("00:01:02,780", "00:01:07,120", "そっか うん｡"),
                           ("00:05:01,000", "00:05:03,500", "明日も一緒に練習しようね！"),
                           ("00:20:07,120", "00:20:09,790", "うん｡")])
    assert "うん｡" in _sentences(path, "ja")
    assert AnchorFinder().line(path, "うん｡") == (1207.12, 1209.79)


def test_times_keep_their_milliseconds():
    """Whole seconds before (the header's seconds, 0.5 s early on average on real episodes); the cue's own now."""
    path = os.path.join(RESOURCES, "zh", "night_market.srt")
    sentence = next(s for s in _sentences(path, "zh") if "夜市" in s)
    assert _old_cue_seconds(path, sentence) == 4
    assert AnchorFinder(language="zh").line(path, sentence) == (4.1, 7.35)


@pytest.mark.parametrize("encoding,newline,bom", [("utf-8", "\r\n", True), ("cp932", "\n", False),
                                                  ("utf-16", "\r\n", False)])
def test_a_files_encoding_and_line_ends_give_the_same_lines(tmp_path, encoding, newline, bom):
    """The reader reads a file in its own encoding (path_utils.read_text): a BOM, CRLF, CP932, UTF-16 — the same
    lines as the UTF-8 / LF original."""
    with open(EPISODE, encoding="utf-8-sig") as f:
        text = f.read()
    path = tmp_path / "library_episode.ass"
    with open(path, "w", encoding=("utf-8-sig" if bom else encoding), newline=newline) as f:
        f.write(text)
    finder = AnchorFinder()
    for sentence in ("それでしたらこちらの用紙にお名前と住所を書いてください。", "どうぞ。"):
        assert finder.line(str(path), sentence) == AnchorFinder().line(EPISODE, sentence)


# --- the report ---------------------------------------------------------------------------------------------------- #
def test_the_report_gives_a_subtitle_sentence_its_line_even_without_an_anchor(tmp_path):
    """`At N` / `End N` come with or without a scroll-to-text anchor: どうぞ。 has no anchor, still a time."""
    rec = {"Word": "どうぞ", "Context 1": "どうぞ。", "Src 1": "HighPriority/library_episode.ass",
           "Context 2": "それでしたらこちらの用紙にお名前と住所を書いてください。",
           "Src 2": "HighPriority/library_episode.ass"}
    table, index = [], {}
    source_map = {"HighPriority/library_episode.ass": {"name": "library_episode.ass", "type": "subtitle",
                                                       "abs": EPISODE}}
    _intern_sources([rec], source_map, table, index, finder=AnchorFinder(language="ja"))
    assert "Frag 1" not in rec
    assert (rec["At 1"], rec["End 1"]) == (109.3, 112.1)
    assert (rec["At 2"], rec["End 2"]) == (103.0, 106.5)
    assert not any(key.startswith("Context ") for key in rec if key not in ("Context 1", "Context 2")), \
        "never a 'Context …' key: both templates read those as examples"


def test_prose_has_no_line(ja_resources_dir):
    """A book's sentence has no time: no `At` / `End`, as before."""
    path = os.path.join(ja_resources_dir, "context_test.txt")
    sentence = _sentences(path, "ja")[0]
    rec = {"Context 1": sentence, "Src 1": "HighPriority/context_test.txt"}
    _intern_sources([rec], {"HighPriority/context_test.txt": {"name": "context_test.txt", "type": "text",
                                                               "abs": path}},
                    [], {}, finder=AnchorFinder(language="ja"))
    assert "At 1" not in rec and "End 1" not in rec


def test_a_memo_from_before_the_line_reader_is_recomputed(tmp_path):
    """A memo written before E5.1 holds [anchor, whole seconds] under the file's old signature: never served."""
    import json
    cache = tmp_path / "anchor_cache.json"
    st = os.stat(EPISODE)
    cache.write_text(json.dumps({EPISODE: {"sig": [st.st_mtime, st.st_size],
                                           "a": {"どうぞ。": ["", None]}}}, ensure_ascii=False), encoding="utf-8")
    assert AnchorFinder(cache_path=str(cache)).resolve(EPISODE, "どうぞ。") == ("", 109.3, 112.1)
