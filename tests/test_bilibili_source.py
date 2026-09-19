"""bilibili.tv transcripts in the core: their source type, the report's ▶ badge, and the analysis.

The downloader (modules/youtube_downloader) names a bilibili.tv transcript "<Title> [bilibili-<id>]"
and writes the episode page URL into its cue sidecar. The core has to:

- type it "bilibili" from the filename, like "[<11-char id>]" is typed "youtube", and never mistake a
  bare bracketed number ("[20240101]", a fansub CRC) for one;
- give its badge the episode page. bilibili.tv has no verified start-time parameter, so the badge
  opens the episode and the hover names the moment, instead of building a youtu.be link;
- count it as SPOKEN material (the reading-vs-listening badge) and as audio for "Always include a
  sentence you can hear", exactly as subtitle files are.
"""
import json
import os
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer
from app.path_utils import infer_source_type
from app.static_html_generator import AnchorFinder, _intern_sources, _video_link

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EP_URL = "https://www.bilibili.tv/en/play/2410703/30646923"

# A transcript exactly as the downloader writes one: a light header, then one closed cue per sentence.
TRANSCRIPT = ("E7\nUnknown |  | 24:00\nCaptions: Chinese (manual)\n" + EP_URL + "\n\n" + "-" * 60 +
              "\n\n欢迎光临时光照相馆。我们今天要接一个新的委托。你确定要进入这张照片吗？放心吧 我会小心的。\n")
NOTES = "我今天在图书馆看书。图书馆里很安静。\n"


# ---- source type ------------------------------------------------------------------------------ #

@pytest.mark.parametrize("path, expected", [
    ("data/zh/HighPriority/LINK CLICK 3 (playlist)/E7 [bilibili-30646923].txt", "bilibili"),
    # Graduate/Demote append a timestamp on a name collision — sometimes twice.
    ("data/zh/Graduated/E7 [bilibili-30646923]_20260918120000_20260918130000.txt", "bilibili"),
    # 11 characters, so it would ALSO fit the YouTube pattern: bilibili is checked first.
    ("data/zh/HighPriority/E1 [bilibili-12].txt", "bilibili"),
    ("data/ja/HighPriority/チャンネル - 今日の話題 [dQw4w9WgXcQ].txt", "youtube"),
    ("data/zh/HighPriority/日记 [20240101].txt", "text"),          # a date, not an id
    ("data/zh/HighPriority/[bilibili] 字幕组 ep01.txt", "text"),    # a group tag, not an id
    ("data/zh/HighPriority/E7 [bilibili-30646923].srt", "subtitle"),  # the extension still wins
])
def test_bilibili_transcripts_are_typed_from_their_filename(path, expected):
    assert infer_source_type(path) == expected


# ---- the badge -------------------------------------------------------------------------------- #

def test_the_badge_opens_the_episode_page():
    side = {"video_id": "30646923", "url": EP_URL + "#__youtubedl_smuggle=%7B%7D"}
    assert _video_link("E7 [bilibili-30646923].txt", "bilibili", side) == EP_URL
    assert _video_link("E7 [bilibili-30646923].txt", "bilibili", None) == "", \
        "no sidecar, no known page: better no link than a wrong one"
    assert _video_link("E7 [bilibili-30646923].txt", "bilibili", {"url": "javascript:alert(1)"}) == ""
    # YouTube is untouched: the id, from which the template builds youtu.be/…?t=.
    assert _video_link("x [dQw4w9WgXcQ].txt", "youtube", None) == "dQw4w9WgXcQ"


def test_the_source_table_carries_the_type_and_the_page(tmp_path):
    transcript = tmp_path / "E7 [bilibili-30646923].txt"
    transcript.write_text(TRANSCRIPT, encoding="utf-8")
    (tmp_path / "E7 [bilibili-30646923].surasura.json").write_text(
        json.dumps({"video_id": "30646923", "url": EP_URL, "cues": []}), encoding="utf-8")
    rel = "HighPriority/E7 [bilibili-30646923].txt"
    records = [{"Context 1": "欢迎光临时光照相馆。", "Src 1": rel}]
    table = []
    _intern_sources(records, {rel: {"name": transcript.name, "type": "bilibili",
                                    "abs": str(transcript)}},
                    table, {}, finder=AnchorFinder())
    assert table[0][1] == "bilibili" and table[0][4] == EP_URL


@pytest.mark.parametrize("template", ["web_app.html", "zen_app.html"])
def test_both_reports_know_the_bilibili_badge(template):
    """The template treats row[4] as either a YouTube id or a page URL. A URL must be used as-is,
    without youtu.be in front and without a ?t= offset the site doesn't understand."""
    with open(os.path.join(PROJECT_ROOT, "templates", template), encoding="utf-8") as f:
        content = f.read()
    assert "bilibili: '📺'" in content
    assert "const pageUrl = videoId.startsWith('https://') || videoId.startsWith('http://');" in content
    assert "const secs = (!pageUrl &&" in content
    assert "const href = pageUrl ? videoId : 'https://youtu.be/'" in content


# ---- the analysis ----------------------------------------------------------------------------- #

@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "zh"; uf.mkdir(parents=True)
    high = tmp_path / "data" / "zh" / "HighPriority"; high.mkdir(parents=True)
    results = tmp_path / "results"; results.mkdir()
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    (high / "E7 [bilibili-30646923].txt").write_text(TRANSCRIPT, encoding="utf-8")
    (high / "notes.txt").write_text(NOTES, encoding="utf-8")

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"results": results, "guf": guf, "gdp": gdp, "gufp": gufp}


def test_a_bilibili_transcript_counts_as_something_you_can_hear(env):
    results = env["results"]
    csv = results / "priority_learning_list.csv"
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.analyzer.get_data_path", side_effect=env["gdp"]), \
         patch("app.analyzer.get_user_files_path", side_effect=env["gufp"]), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv)), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "zh", "--min-freq", "1"]):
        analyzer.main()

    with open(results / "sources.json", encoding="utf-8") as f:
        types = {os.path.basename(p): meta["type"] for p, meta in json.load(f).items()}
    assert types == {"E7 [bilibili-30646923].txt": "bilibili", "notes.txt": "text"}

    with open(results / "word_stats.json", encoding="utf-8") as f:
        stats = json.load(f)
    assert stats["照相馆|"]["spoken_count"] > 0, "a word heard in the episode is spoken evidence"
    assert stats["图书馆|"]["spoken_count"] == 0, "a word only in written notes is not"
    # Each closed cue is its own example sentence, not one run-on line.
    contexts = set(pd.read_csv(csv)["Context 1"].dropna())
    assert "欢迎光临时光照相馆。" in contexts
