"""WP-Z4: deep links still land when the report's sentences were converted to another script.

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md §5.5. A deep link hands the browser
a snippet to find in the SOURCE FILE, so it has to be the file's own wording. With a Chinese script
chosen, the report's sentence is converted text that doesn't occur in a file written in the other
script. AnchorFinder therefore searches a converted copy of the file and returns the original text
at the same offsets, which works because every conversion is length-preserving (zh_script I3). Line
times come from Connect's line reader (app/cues.py, E5.1), whose text is searched converted the same way.

As-is must stay exactly the old search: `_hay` IS the raw text.
"""

import os

from app import zh_script
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
    path = _write(tmp_path / "news.txt", raw)
    line = next(l for l in raw.splitlines() if l.startswith("城南孙中山纪念馆"))
    anchor = AnchorFinder(script="t").anchor(path, zh_script.convert(line, "t"))
    assert anchor and anchor in line and raw.count(anchor) == 1


def test_line_times_survive_the_conversion(tmp_path):
    """The line reader's text is searched converted too (length-preserving), so a Simplified report's sentence
    finds its Traditional cue: 00:01:10,500 --> 00:01:14,000."""
    path = _write(tmp_path / "ep01.srt", TRAD_SRT)
    finder = AnchorFinder(script="s")
    anchor = finder.anchor(path, "许多学者认为，台湾必须持续学习新技术。")
    assert anchor and anchor in TRAD_SRT
    assert finder.line(path, "许多学者认为，台湾必须持续学习新技术。") == (70.5, 74.0)
    assert AnchorFinder().line(path, "许多学者认为，台湾必须持续学习新技术。") == (None, None), \
        "as-is can't find converted text"


def test_the_whitespace_tolerant_path_maps_back_too(tmp_path):
    """The spaced cue can't match verbatim; the loose search runs on the converted copy and must still
    hand back a run of the ORIGINAL text. Its line is found without the spaces, as the tokenizer yields it."""
    path = _write(tmp_path / "ep01.srt", TRAD_SRT)
    finder = AnchorFinder(script="s")
    anchor = finder.anchor(path, "研究人员后来发现早餐很重要。")
    assert anchor and anchor in TRAD_SRT, anchor
    assert finder.line(path, "研究人员后来发现早餐很重要｡") == (120, 123)


def test_as_is_searches_the_raw_text_and_signs_its_memo_with_the_line_reader(tmp_path):
    """A memo from before E5.1 ([anchor, whole seconds]) is recomputed once: every signature names the line reader (and the engine)."""
    path = _write(tmp_path / "ep01.srt", TRAD_SRT)
    st = os.stat(path)
    as_is = AnchorFinder()
    assert as_is._hay(path) is as_is._raw(path)
    assert as_is._file_sig(path) == (st.st_mtime, st.st_size, as_is._lines())   # (the memo writes it as a list)
    assert AnchorFinder(script="t")._file_sig(path) == (st.st_mtime, st.st_size, "t", as_is._lines())


def test_a_script_switch_does_not_reuse_the_other_scripts_answers(tmp_path):
    """The memo remembers misses. An as-is render records "no anchor" for the Simplified sentence; a
    later render reading as Simplified must search again, not serve that miss."""
    path = _write(tmp_path / "ep01.srt", TRAD_SRT)
    memo = str(tmp_path / "anchor_cache.json")
    sentence = "经济部官员表示，半导体需求仍然强劲。"

    first = AnchorFinder(cache_path=memo)
    assert first.resolve(path, sentence) == ("", None, None)
    first.save_memo()

    anchor, at, end = AnchorFinder(cache_path=memo, script="s").resolve(path, sentence)
    assert anchor and anchor in TRAD_SRT and (at, end) == (5, 8)


# The whole chain (analyzer -> CSV -> report: the deep link in the file's own wording) retired with the old page
# (J-RETIRE): the journey page draws no deep link; its ▶ times are AnchorFinder's with the chosen script
# (journey_render.render), the fact test_line_times_survive_the_conversion holds.
