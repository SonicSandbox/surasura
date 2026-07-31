"""Scroll-to-text deep links must land on the sentence, or not be offered at all.

The sentence in the report is NOT the sentence in the file. The tokenizer drops every space when it
rebuilds a sentence, so an anime subtitle line written as

    そうだ 女｡ お前に話がある｡

is stored as `そうだ女｡お前に話がある。`. The analyzer also appends `。` to cues without sentence
punctuation and strips Latin characters. Any anchor guessed from the stored text therefore spans
gaps the file doesn't have — and a short guess can land on the WRONG line.

So the generator verifies candidate snippets against the real file and only emits one that occurs
exactly once. These tests use real subtitle/prose text and drive the REAL analyzer, so they cover
the whole chain rather than the helper in isolation.
"""

import json
import os
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer
from app.static_html_generator import AnchorFinder

# Spacing and halfwidth '｡' copied from a real anime subtitle — this is the reported failing shape.
SRT = (
    "1\n00:19:50,000 --> 00:19:53,000\n"
    "そうだ 女｡ お前に話がある｡\n\n"
    "2\n00:20:00,724 --> 00:20:05,930\n"
    "逃げて 逃げてください！\nし しかし｡\n\n"
    "3\n00:20:05,930 --> 00:20:07,965\n"
    "そのために\n拘流と拘突が存在したんだ\n"
)
# Prose has no internal spacing, which is why plain .txt worked from the start.
TXT = "少年は静かに扉を開けた。廊下には誰もいなかった。秘密の部屋が待っていた。"


@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "ja"; uf.mkdir(parents=True)
    high = tmp_path / "data" / "ja" / "HighPriority"; high.mkdir(parents=True)
    results = tmp_path / "results"; results.mkdir()
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    (high / "ep01.srt").write_text(SRT, encoding="utf-8")
    (high / "book.txt").write_text(TXT, encoding="utf-8")

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"root": tmp_path, "results": results, "high": high, "guf": guf, "gdp": gdp, "gufp": gufp}


def _run(env):
    results = env["results"]
    csv = results / "priority_learning_list.csv"
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.analyzer.get_data_path", side_effect=env["gdp"]), \
         patch("app.analyzer.get_user_files_path", side_effect=env["gufp"]), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv)), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()
    return pd.read_csv(csv)


def _sentence_containing(df, needle):
    for ctx in df["Context 1"].dropna():
        if needle in str(ctx):
            return str(ctx)
    raise AssertionError(f"no example sentence containing {needle!r} was produced")


# --- the loss that makes guessing impossible ---------------------------------------------------- #
def test_spaces_inside_a_subtitle_line_do_not_survive(env):
    """Root cause. The file separates words with spaces; the stored sentence has none, and nothing
    records where they were."""
    df = _run(env)
    sentence = _sentence_containing(df, "お前に話")
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")

    assert "そうだ 女｡ お前に話がある｡" in raw, "the file keeps its spacing"
    assert " " not in sentence, f"no whitespace survives: {sentence!r}"


def _tokenized(env):
    """The sentences the analyzer actually produces for the fixture subtitle."""
    from app import analyzer as _a
    _a.SANITIZE_JA = True
    path = str(env["high"] / "ep01.srt")
    return [s for s, _t in _a.JapaneseTokenizer().tokenize_sentences(_a.extract_text(path, "ja"))]


def test_a_guessed_anchor_would_still_miss(env):
    """Verification stays necessary after the splitting fix. Sentences are much shorter now, so many
    ARE verbatim — but a line the file spaces internally still isn't, and neither is one whose cue
    was split across two lines. Guessing would quietly point at nothing."""
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")
    sentences = _tokenized(env)

    spaced = next(s for s in sentences if "女" in s)          # file: 'そうだ 女｡'
    assert spaced not in raw, f"{spaced!r} should not be verbatim — the file spaces it"

    wrapped = next(s for s in sentences if "拘流" in s)        # file: split across two lines
    assert wrapped.rstrip("。")[:10] not in raw, "a 10-char head still straddles the line break"


# --- verified anchors ---------------------------------------------------------------------------- #
def test_verified_anchor_is_found_for_a_spaced_subtitle_line(env):
    """The reported case now produces a real anchor — a run that survives inside one line."""
    sentence = next(s for s in _tokenized(env) if "女" in s)
    path = str(env["high"] / "ep01.srt")
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")

    anchor = AnchorFinder().anchor(path, sentence)
    assert anchor, f"no anchor found for {sentence!r}"
    assert anchor in raw, "the anchor must exist verbatim in the file"
    # The anchor may carry the file's spacing, which the sentence lost — compare without it.
    assert "".join(anchor.split()) in "".join(sentence.split()), \
        "the anchor must be a genuine piece of this sentence, not some other line"


def test_sentences_no_longer_span_multiple_cues(env):
    """Anchoring used to have to cope with 'sentences' covering a dozen cues, because the analyzer
    appended a terminator at every cue boundary and the splitter swallowed all of them. With the
    splitting fix each cue ends its own sentence, so this can be asserted rather than tolerated."""
    df = _run(env)
    subtitle_rows = df[df["Src 1"].astype(str).str.endswith("ep01.srt")]
    assert not subtitle_rows.empty, "the fixture should produce subtitle-sourced sentences"

    for sentence in subtitle_rows["Context 1"].dropna().astype(str):
        assert sentence.count("。") <= 1, f"still spans multiple cues: {sentence!r}"
        assert len(sentence) < 60, f"runaway sentence: {sentence!r}"


def test_anchor_is_unique_so_it_cannot_scroll_to_the_wrong_line(env):
    """A snippet occurring twice would send Chrome to the first one. Only unique anchors ship."""
    df = _run(env)
    finder = AnchorFinder()
    raw = (env["high"] / "ep01.srt").read_text(encoding="utf-8")
    path = str(env["high"] / "ep01.srt")

    checked = 0
    for _, row in df.iterrows():
        if str(row.get("Src 1", "")).endswith("ep01.srt") and pd.notna(row.get("Context 1")):
            anchor = finder.anchor(path, row["Context 1"])
            if anchor:
                assert raw.count(anchor) == 1, f"{anchor!r} is ambiguous"
                checked += 1
    assert checked, "no subtitle anchors were produced at all"


def test_plain_prose_still_anchors(env):
    """The case that already worked must keep working."""
    df = _run(env)
    path = str(env["high"] / "book.txt")
    raw = (env["high"] / "book.txt").read_text(encoding="utf-8")

    checked = 0
    for _, row in df.iterrows():
        if str(row.get("Src 1", "")).endswith("book.txt") and pd.notna(row.get("Context 1")):
            anchor = finder_anchor = AnchorFinder().anchor(path, row["Context 1"])
            assert anchor, f"prose should always anchor: {row['Context 1']!r}"
            assert finder_anchor in raw
            checked += 1
    assert checked, "no prose sentences were checked"


# --- AnchorFinder in isolation -------------------------------------------------------------------- #
def test_no_anchor_rather_than_a_wrong_one(tmp_path):
    """A sentence that simply isn't in the file yields nothing — the badge then offers no link
    instead of one that misses."""
    f = tmp_path / "a.txt"
    f.write_text("まったく関係のない文章がここにあります。", encoding="utf-8")
    assert AnchorFinder().anchor(str(f), "存在しない別の文です。") == ""


def test_ambiguous_text_is_rejected(tmp_path):
    """A repeated line can't produce a trustworthy anchor."""
    f = tmp_path / "b.txt"
    f.write_text("同じ文が続きます。\n" * 5, encoding="utf-8")
    assert AnchorFinder().anchor(str(f), "同じ文が続きます。") == ""


def test_missing_file_and_junk_input_are_safe(tmp_path):
    finder = AnchorFinder()
    assert finder.anchor(str(tmp_path / "gone.txt"), "何かの文です") == ""
    f = tmp_path / "c.txt"
    f.write_text("少年は静かに扉を開けた。", encoding="utf-8")
    for junk in ("", "   ", None, "短い"):
        assert finder.anchor(str(f), junk) == "", f"{junk!r} should yield no anchor"


# --- subtitle cue timestamps --------------------------------------------------------------------- #
def test_cue_time_locates_the_right_subtitle_cue(env):
    """The anchor is verbatim file text, so its offset falls inside exactly one cue. No guessing, and
    nothing about how the file was tokenized has to change."""
    df = _run(env)
    path = str(env["high"] / "ep01.srt")
    finder = AnchorFinder()

    sentence = _sentence_containing(df, "お前に話")          # cue 1: 00:19:50 --> 00:19:53
    assert finder.cue_time(path, finder.anchor(path, sentence)) == 19 * 60 + 50

    sentence = _sentence_containing(df, "拘流")              # cue 3: 00:20:05 --> 00:20:07
    assert finder.cue_time(path, finder.anchor(path, sentence)) == 20 * 60 + 5


def test_cue_time_handles_ass_subtitles(tmp_path):
    """ASS/SSA put their timing on the Dialogue line instead of a '-->' header."""
    f = tmp_path / "signs.ass"
    f.write_text(
        "[Events]\nFormat: Layer, Start, End, Style, Name, Text\n"
        "Dialogue: 0,0:00:12.30,0:00:15.00,Default,,少年は静かに扉を開けた\n"
        "Dialogue: 0,1:02:03.10,1:02:05.00,Default,,廊下には誰もいなかった\n",
        encoding="utf-8")
    finder = AnchorFinder()
    assert finder.cue_time(str(f), "少年は静かに扉を開けた") == 12
    assert finder.cue_time(str(f), "廊下には誰もいなかった") == 1 * 3600 + 2 * 60 + 3


def test_plain_text_has_no_cue_time(env):
    """Prose isn't timed — it must return None rather than inventing a position."""
    path = str(env["high"] / "book.txt")
    finder = AnchorFinder()
    anchor = finder.anchor(path, "少年は静かに扉を開けた。")
    assert anchor
    assert finder.cue_time(path, anchor) is None


def test_cue_time_is_safe_on_junk(env, tmp_path):
    finder = AnchorFinder()
    path = str(env["high"] / "ep01.srt")
    assert finder.cue_time(path, "") is None
    assert finder.cue_time(path, "この文は字幕に存在しません") is None, "text not in the file"
    assert finder.cue_time(str(tmp_path / "missing.srt"), "何か") is None


def test_cue_index_is_built_once_per_file(env):
    """Re-parsing the cue table per sentence would undo the point of caching the file."""
    path = str(env["high"] / "ep01.srt")
    finder = AnchorFinder()
    finder.cue_time(path, "そうだ")
    offsets, _seconds = finder._cue_index(path)
    assert offsets, "the .srt should have produced cues"
    with patch.object(AnchorFinder, "_raw", side_effect=AssertionError("re-read the file")):
        finder._cue_index(path)      # cached: must not touch the file again


# --- YouTube transcripts: cue times come from the sidecar ----------------------------------------- #
TRANSCRIPT = ("今日の話題\nチャンネル | 2026-01-01 | 12:03\n"
              "------------------------------------------------------------\n"
              "秘密の多い街を歩いてきました 答えはまだ見つかりません それでも探し続けるつもりです")

CUES = {"video_id": "dQw4w9WgXcQ", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "cues": [["秘密の多い街を歩いてきました", 2],
                 ["答えはまだ見つかりません", 65],
                 ["それでも探し続けるつもりです", 3723]]}


def _transcript(tmp_path, cues=CUES):
    """A transcript plus its cue sidecar, exactly as the downloader writes them."""
    from app.path_utils import SIDECAR_SUFFIX
    txt = tmp_path / "チャンネル - 今日の話題 [dQw4w9WgXcQ].txt"
    txt.write_text(TRANSCRIPT, encoding="utf-8")
    if cues is not None:
        side = tmp_path / ("チャンネル - 今日の話題 [dQw4w9WgXcQ]" + SIDECAR_SUFFIX)
        side.write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
    return str(txt)


def test_transcript_sentence_resolves_to_its_cue_time(tmp_path):
    """A transcript is plain prose — its timings live in the sidecar, so the cue texts are located
    in the file to give them positions."""
    path = _transcript(tmp_path)
    finder = AnchorFinder()
    assert finder.cue_time(path, "秘密の多い街を歩いてきました") == 2
    assert finder.cue_time(path, "答えはまだ見つかりません") == 65
    assert finder.cue_time(path, "それでも探し続けるつもりです") == 3723


def test_anchor_and_cue_time_agree_for_a_transcript(tmp_path):
    path = _transcript(tmp_path)
    finder = AnchorFinder()
    anchor = finder.anchor(path, "答えはまだ見つかりません。")
    assert anchor
    assert finder.cue_time(path, anchor) == 65


def test_transcript_without_a_sidecar_has_no_cue_time(tmp_path):
    """Transcripts pulled before sidecars existed still work — they just can't be timed."""
    path = _transcript(tmp_path, cues=None)
    finder = AnchorFinder()
    assert finder.sidecar(path) == {}
    assert finder.cue_time(path, "答えはまだ見つかりません") is None
    assert finder.anchor(path, "答えはまだ見つかりません。"), "the deep link must still work"


def test_a_cue_absent_from_the_file_is_skipped_not_guessed(tmp_path):
    """If the transcript was cleaned differently from the captions, the cue is dropped rather than
    given a wrong position."""
    cues = {"video_id": "x", "cues": [["この行は本文にありません", 10],
                                      ["答えはまだ見つかりません", 65]]}
    path = _transcript(tmp_path, cues=cues)
    finder = AnchorFinder()
    assert finder.cue_time(path, "答えはまだ見つかりません") == 65


def test_corrupt_or_malformed_sidecar_is_ignored(tmp_path):
    from app.path_utils import SIDECAR_SUFFIX
    path = _transcript(tmp_path, cues=None)
    side = os.path.splitext(path)[0] + SIDECAR_SUFFIX
    for junk in ("{ not json", "[]", '{"cues": "nope"}', '{"cues": [["a"], [1,2,3]]}'):
        with open(side, "w", encoding="utf-8") as f:
            f.write(junk)
        finder = AnchorFinder()
        assert finder.cue_time(path, "答えはまだ見つかりません") is None, junk


# --- the on-disk memo -------------------------------------------------------------------------- #
def test_resolve_memo_makes_a_second_render_a_lookup(tmp_path):
    """A re-render (theme, Zen limit, Words Per Day) re-resolves every sentence over unchanged
    files. The memo turns all of that into dictionary hits."""
    src = tmp_path / "book.txt"
    src.write_text(TXT, encoding="utf-8")
    cache = tmp_path / "anchor_cache.json"

    first = AnchorFinder(cache_path=str(cache))
    got = first.resolve(str(src), "少年は静かに扉を開けた。")
    assert got[0], "should have found an anchor"
    first.save_memo()
    assert cache.exists()

    second = AnchorFinder(cache_path=str(cache))
    with patch.object(AnchorFinder, "anchor", side_effect=AssertionError("recomputed!")):
        assert second.resolve(str(src), "少年は静かに扉を開けた。") == got


def test_memo_is_dropped_when_the_source_file_changes(tmp_path):
    """An edited file must never serve a stale anchor."""
    src = tmp_path / "book.txt"
    src.write_text(TXT, encoding="utf-8")
    cache = tmp_path / "anchor_cache.json"

    first = AnchorFinder(cache_path=str(cache))
    first.resolve(str(src), "少年は静かに扉を開けた。")
    first.save_memo()

    src.write_text("まったく違う文章になりました。ここには前の文はありません。", encoding="utf-8")
    second = AnchorFinder(cache_path=str(cache))
    anchor, _at = second.resolve(str(src), "少年は静かに扉を開けた。")
    assert anchor == "", "the old sentence is gone, so there is nothing to anchor"


def test_memo_remembers_misses_too(tmp_path):
    """A sentence with no usable anchor is the expensive case — don't redo that search either."""
    src = tmp_path / "b.txt"
    src.write_text("同じ文が続きます。\n" * 5, encoding="utf-8")
    cache = tmp_path / "anchor_cache.json"

    AnchorFinder(cache_path=str(cache)).resolve(str(src), "同じ文が続きます。")
    AnchorFinder(cache_path=str(cache)).save_memo()

    second = AnchorFinder(cache_path=str(cache))
    second.resolve(str(src), "同じ文が続きます。")
    with patch.object(AnchorFinder, "anchor", side_effect=AssertionError("recomputed a miss!")):
        assert second.resolve(str(src), "同じ文が続きます。") == ("", None)


def test_memo_forgets_files_that_left_the_library(tmp_path):
    """Content leaves constantly — graduated, removed, renamed by a tier move. Without pruning the
    memo would accumulate their entries forever."""
    cache = tmp_path / "anchor_cache.json"
    keep = tmp_path / "keep.txt"
    gone = tmp_path / "gone.txt"
    keep.write_text(TXT, encoding="utf-8")
    gone.write_text("雪原の果てに山が見えた。雪原は白く広い。", encoding="utf-8")

    first = AnchorFinder(cache_path=str(cache))
    first.resolve(str(keep), "少年は静かに扉を開けた。")
    first.resolve(str(gone), "雪原の果てに山が見えた。")
    first.save_memo()
    assert len(json.loads(cache.read_text(encoding="utf-8"))) == 2

    # Next render only touches the surviving file.
    second = AnchorFinder(cache_path=str(cache))
    second.resolve(str(keep), "少年は静かに扉を開けた。")
    second.save_memo()
    remaining = json.loads(cache.read_text(encoding="utf-8"))
    assert list(remaining) == [str(keep)], remaining


def test_a_corrupt_or_missing_memo_is_harmless(tmp_path):
    src = tmp_path / "book.txt"
    src.write_text(TXT, encoding="utf-8")
    cache = tmp_path / "anchor_cache.json"
    cache.write_text("{ this is not json", encoding="utf-8")

    finder = AnchorFinder(cache_path=str(cache))
    assert finder.resolve(str(src), "少年は静かに扉を開けた。")[0], "must fall back to computing"

    # And with no cache path at all (the standalone case) nothing is written.
    assert AnchorFinder().resolve(str(src), "少年は静かに扉を開けた。")[0]


def test_cue_time_reuses_the_position_anchor_already_found(tmp_path):
    """cue_time used to rescan the whole file to rediscover an offset anchor() had just computed —
    the single biggest cost in the pass."""
    path = _transcript(tmp_path)
    finder = AnchorFinder()
    anchor = finder.anchor(path, "答えはまだ見つかりません。")
    assert (path, anchor) in finder._pos, "anchor() must record where it found the anchor"

    finder._cue_index(path)          # warm the cue table (its own one-time file read)
    with patch.object(AnchorFinder, "_raw", side_effect=AssertionError("rescanned the file")):
        assert finder.cue_time(path, anchor) == 65


def test_files_are_read_once(tmp_path):
    """The pass runs over every sentence, so re-reading per sentence would be the whole cost."""
    f = tmp_path / "d.txt"
    f.write_text("少年は静かに扉を開けた。廊下には誰もいなかった。", encoding="utf-8")
    finder = AnchorFinder()

    real_open = open
    calls = {"n": 0}

    def counting_open(*a, **kw):
        calls["n"] += 1
        return real_open(*a, **kw)

    with patch("builtins.open", counting_open):
        for _ in range(5):
            finder.anchor(str(f), "少年は静かに扉を開けた。")
    assert calls["n"] == 1, f"file was read {calls['n']} times"
