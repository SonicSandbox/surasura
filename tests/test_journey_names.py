"""Fresh-U 13 (Sonic 2026-11-13, "11. Sure": the journey's names and labels; words PROVISIONAL): the journey's left
column names each file as a show and its episode (*Hoshikuzu Station · Ep 1*), never its file name
(`Hoshikuzu Station S01E01.ja.srt`, `H_priority_sample_1.txt`); a word's *Score* is called *Worth*; the reference-list
tier badge (*G-1*: a list's first letter and its band, read by nobody) is gone.

The file name stays the report's key (`#file=`, the marks, Completed): only what is shown changes. The templates have no
JS engine here, so they are string contracts (test_modality_badge.py's convention); the name itself is the generator's
(`shown_name`), tested as data.
"""
import json
import os
import re
from unittest.mock import patch

import pandas as pd
import pytest

from app import static_html_generator as gen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _template(name):
    with open(os.path.join(ROOT, "templates", name), encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("filename, shown", [
    ("Hoshikuzu Station S01E01.ja.srt", "Hoshikuzu Station · Ep 1"),              # the walkthrough's own file
    ("[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].ja.srt", "Sousou no Frieren · Ep 5"),   # a release's tags off
    ("葬送のフリーレン 第5話.srt", "葬送のフリーレン · Ep 5"),                                  # Japanese episode marks
    ("Kino S02E03.zh.srt", "Kino S2 · Ep 3"),                                     # a second season keeps its S2
    ("H_priority_sample_1.txt", "H priority sample · Part 1"),                   # a text's part, never *Ep*
    ("book_07 (3-2) 第一章 出会い.txt", "book · 第一章 出会い · Part 2"),                    # a book's part named by its chapter
    ("My Video [dQw4w9WgXcQ].ja.vtt", "My Video"),                                 # a YouTube id and language tag off
    ("novel.txt", "novel"),                                                       # nothing to read: its stem
    ("01.srt", "Ep 1"),                                                           # a bare number: the episode alone
    ("Show - OVA 01.srt", "Show - OVA 01"),                                       # a special is never *Ep 1*
    # (the adversary's F4) a YouTube video's title is no episode, as on the window's rows; a release's 8-character
    # hash tag is no YouTube id
    ("Top 10 Japanese Phrases [dQw4w9WgXcQ].ja.vtt", "Top 10 Japanese Phrases"),
    ("Comprehensible Japanese 128 Lets talk about cats [abc_DEF-123].ja.vtt",
     "Comprehensible Japanese 128 Lets talk about cats"),
])
def test_fresh_u_a_file_is_shown_as_its_show_and_episode(filename, shown):
    assert gen.shown_name(filename) == shown


@pytest.mark.parametrize("filename", ["", None, ".srt", "   "])
def test_fresh_u_a_name_with_nothing_to_read_falls_back_to_the_file_name_and_never_raises(filename):
    """Why: the generator names every entry; a name it can't read must never stop the report being written."""
    assert gen.shown_name(filename) == (filename or "")


def _render(tmp_path, filenames):
    results = tmp_path / "results"
    results.mkdir()
    pd.DataFrame([{"Word": "冒険", "Reading": "ボウケン", "Tier": "global50k:1", "Score": 30, "Occurrences": 4,
                   "Count (High)": 1, "Count (Low)": 1, "Count (Goal)": 2, "Context 1": "冒険に出かけた。"}]
                 ).to_csv(results / "priority_learning_list.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"Sequence": i, "Source File": name, "Word": f"単語{i}", "Reading": "タンゴ", "Tier": "global50k:1",
                   "Score": 10, "Occurrences (Global)": 2, "Occurrences (File)": 2, "Count (High)": 0,
                   "Count (Low)": 0, "Count (Goal)": 2, "Context 1": "冒険に出かけた。"}
                  for i, name in enumerate(filenames, 1)]
                 ).to_csv(results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")
    out = results / "reading_list_static.html"
    with patch.object(gen, "RESULTS_DIR", str(results)), \
         patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")), \
         patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
         patch.object(gen, "OUTPUT_FILE", str(out)):
        gen.generate_static_html(theme="default", open_browser=False)
    payload = re.search(r"let globalData = (\{.*?\});\n", out.read_text(encoding="utf-8"), re.S)
    return json.loads(payload.group(1))


def test_fresh_u_every_journey_entry_carries_its_shown_name_and_keeps_its_file_name_as_key(tmp_path):
    """Why: the sidebar shows `name`; `filename` stays the key the window's `#file=`, the marks and Completed use."""
    data = _render(tmp_path, ["Hoshikuzu Station S01E01.ja.srt", "H_priority_sample_1.txt"])
    assert [(f["filename"], f["name"]) for f in data["progressive"]] == [
        ("Hoshikuzu Station S01E01.ja.srt", "Hoshikuzu Station · Ep 1"),
        ("H_priority_sample_1.txt", "H priority sample · Part 1")]


def test_fresh_u_a_file_already_met_is_named_too(tmp_path):
    """Why: *Target met* files (in the stats, not the list) are a sidebar row and a panel of their own."""
    results = tmp_path / "results"
    data_dir = results
    results.mkdir()
    pd.DataFrame([], columns=["Sequence", "Source File", "Word"]).to_csv(
        results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")
    with open(results / "file_statistics.json", "w", encoding="utf-8") as f:
        json.dump([{"File": "Hoshikuzu Station S01E02.ja.srt", "Total Words": 5, "Coverage (%)": 99}], f)
    out = results / "reading_list_static.html"
    with patch.object(gen, "RESULTS_DIR", str(data_dir)), \
         patch.object(gen, "PRIORITY_CSV", str(results / "none.csv")), \
         patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
         patch.object(gen, "OUTPUT_FILE", str(out)):
        gen.generate_static_html(theme="default", open_browser=False)
    data = json.loads(re.search(r"let globalData = (\{.*?\});\n", out.read_text(encoding="utf-8"), re.S).group(1))
    assert [(f["filename"], f["name"]) for f in data["completed_files"]] == [
        ("Hoshikuzu Station S01E02.ja.srt", "Hoshikuzu Station · Ep 2")]


def test_fresh_u_the_sidebar_and_panels_show_the_name_and_keep_the_file_name_in_the_hover():
    """Why: every place the journey wrote `fileData.filename` as words now writes its name (an old report's data has
    none: the file name, as before); the file name stays findable in the row's hover."""
    html = _template("web_app.html")
    assert "function shownName(fileData)" in html
    assert html.count('data-content="${safeName}"') == 3                 # counted · set aside · target met
    assert 'data-content="${safeFilename}"' not in html
    assert 'tab.title = item.data.filename' in html
    assert "<strong>${fileData.filename}</strong>" not in html            # the Target Met panel
    assert "<strong>${escapeHtml(shownName(fileData))}</strong>" in html
    zen = _template("zen_app.html")
    assert "fileData.filename.replace(/</g" not in zen and "escapeHtml(fileData.name || fileData.filename)" in zen


def test_fresh_u_score_is_called_worth_and_the_tier_badge_is_gone():
    html = _template("web_app.html")
    assert "<span>Score: ${data.Score}</span>" not in html
    assert "<span>Worth: ${data.Score}</span>" in html
    assert "${tierBadgesHtml}" not in html                                # G-1, A-2 …: never drawn
    assert "data.Score" in html                                           # the low-leverage tint still reads it
