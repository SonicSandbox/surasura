"""WP-Z4: deep links still land when the report's sentences were converted to another script.

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md §5.5. A deep link hands the browser
a snippet to find in the SOURCE FILE, so it has to be the file's own wording. With a Chinese script
chosen, the report's sentence is converted text that doesn't occur in a file written in the other
script. AnchorFinder therefore searches a converted copy of the file and returns the original text
at the same offsets, which works because every conversion is length-preserving (zh_script I3). Cue
times are offsets into the same file, so they keep working unchanged.

As-is must stay exactly the old search: `_hay` IS the raw text, and the memo signature is unchanged
so nobody's anchor cache is discarded on upgrade.
"""

import json
import os
from unittest.mock import patch

import pandas as pd

from app import analyzer, zh_script
from app.static_html_generator import AnchorFinder

# A Traditional subtitle. Cue 2 starts at 1:10; the spaced cue 3 exercises the whitespace-tolerant
# path (the tokenizer drops those spaces, so the sentence never contains them).
TRAD_SRT = (
    "1\n00:00:05,000 --> 00:00:08,000\n經濟部官員表示，半導體需求仍然強勁。\n\n"
    "2\n00:01:10,500 --> 00:01:14,000\n許多學者認為，台灣必須持續學習新技術。\n\n"
    "3\n00:02:00,000 --> 00:02:03,000\n研究人員 後來發現 早餐很重要｡\n\n"
)


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_simplified_sentence_anchors_on_the_traditional_files_own_wording(tmp_path, zh_resources_dir):
    with open(os.path.join(zh_resources_dir, "traditional_news.txt"), encoding="utf-8") as f:
        raw = f.read()
    path = _write(tmp_path / "news.txt", raw)
    line = raw.splitlines()[3]                        # 許多學者認為，台灣必須持續學習新技術…
    sentence = zh_script.convert(line, "s")

    assert AnchorFinder().anchor(path, sentence) == "", "as-is can't find converted text: the problem"
    anchor = AnchorFinder(script="s").anchor(path, sentence)
    assert anchor and anchor in line and raw.count(anchor) == 1


def test_a_traditional_sentence_anchors_on_a_simplified_file(tmp_path, zh_resources_dir):
    with open(os.path.join(zh_resources_dir, "chinese_text_1.txt"), encoding="utf-8") as f:
        raw = f.read()
    path = _write(tmp_path / "bbc.txt", raw)
    line = next(l for l in raw.splitlines() if l.startswith("美国总统特朗普"))
    anchor = AnchorFinder(script="t").anchor(path, zh_script.convert(line, "t"))
    assert anchor and anchor in line and raw.count(anchor) == 1


def test_cue_time_survives_the_conversion(tmp_path):
    path = _write(tmp_path / "ep01.srt", TRAD_SRT)
    finder = AnchorFinder(script="s")
    anchor = finder.anchor(path, "许多学者认为，台湾必须持续学习新技术。")
    assert anchor and anchor in TRAD_SRT
    assert finder.cue_time(path, anchor) == 70


def test_the_whitespace_tolerant_path_maps_back_too(tmp_path):
    """The spaced cue can't match verbatim; the loose search runs on the converted copy and must still
    hand back a run of the ORIGINAL text."""
    path = _write(tmp_path / "ep01.srt", TRAD_SRT)
    finder = AnchorFinder(script="s")
    anchor = finder.anchor(path, "研究人员后来发现早餐很重要。")
    assert anchor and anchor in TRAD_SRT, anchor
    assert finder.cue_time(path, anchor) == 120


def test_as_is_searches_the_raw_text_and_keeps_its_memo_signature(tmp_path):
    path = _write(tmp_path / "ep01.srt", TRAD_SRT)
    st = os.stat(path)
    as_is = AnchorFinder()
    assert as_is._hay(path) is as_is._raw(path)
    assert as_is._file_sig(path) == [st.st_mtime, st.st_size]
    assert AnchorFinder(script="t")._file_sig(path) == [st.st_mtime, st.st_size, "t"]


def test_a_script_switch_does_not_reuse_the_other_scripts_answers(tmp_path):
    """The memo remembers misses. An as-is render records "no anchor" for the Simplified sentence; a
    later render reading as Simplified must search again, not serve that miss."""
    path = _write(tmp_path / "ep01.srt", TRAD_SRT)
    memo = str(tmp_path / "anchor_cache.json")
    sentence = "经济部官员表示，半导体需求仍然强劲。"

    first = AnchorFinder(cache_path=memo)
    assert first.resolve(path, sentence) == ("", None)
    first.save_memo()

    anchor, at = AnchorFinder(cache_path=memo, script="s").resolve(path, sentence)
    assert anchor and anchor in TRAD_SRT and at == 5


# ---- the whole chain: analyzer -> CSV -> report ------------------------------------------------ #

def test_report_links_point_at_the_original_wording(tmp_path):
    """Analyze a Traditional subtitle read as Simplified, render the report with the source badge on,
    and check the HTML carries the Simplified sentence AND a deep link in the file's own Traditional."""
    uf = tmp_path / "User Files" / "zh"; uf.mkdir(parents=True)
    high = tmp_path / "data" / "zh" / "HighPriority"; high.mkdir(parents=True)
    results = tmp_path / "results"; results.mkdir()
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    _write(high / "ep01.srt", TRAD_SRT)
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w",
              encoding="utf-8") as f:
        json.dump({"target_language": "zh", "zh_script": "s", "source_display": "icon"}, f)

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")

    csv = results / "priority_learning_list.csv"
    with patch("app.analyzer.get_user_file", side_effect=guf), \
         patch("app.analyzer.get_data_path", side_effect=gdp), \
         patch("app.analyzer.get_user_files_path", side_effect=gufp), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv)), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "zh", "--min-freq", "1", "--zh-script=s"]):
        analyzer.main()
    contexts = set(pd.read_csv(csv)["Context 1"].dropna())
    assert "许多学者认为，台湾必须持续学习新技术。" in contexts

    from app import static_html_generator
    out = results / "reading_list_static.html"
    with patch("app.static_html_generator.RESULTS_DIR", str(results)), \
         patch("app.static_html_generator.PRIORITY_CSV", str(csv)), \
         patch("app.static_html_generator.PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
         patch("app.static_html_generator.OUTPUT_FILE", str(out)), \
         patch("app.static_html_generator.open_report"):
        static_html_generator.generate_static_html()
    html = out.read_text(encoding="utf-8")

    def injected(text):   # the report's data is JSON with ensure_ascii, so CJK arrives \u-escaped
        return json.dumps(text)[1:-1] in html

    assert injected("许多学者认为")                   # the sentence, in the chosen script
    assert injected("許多學者認為")                   # the deep link, in the file's own script
