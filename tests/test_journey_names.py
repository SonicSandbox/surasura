"""Fresh-U 13 (Sonic 2026-11-13, "11. Sure": the journey's names and labels; words PROVISIONAL): the journey's left
column names each file as a show and its episode (*Hoshikuzu Station · Ep 1*), never its file name
(`Hoshikuzu Station S01E01.ja.srt`, `H_priority_sample_1.txt`); a word's *Score* is called *Worth*; the reference-list
tier badge (*G-1*: a list's first letter and its band, read by nobody) is gone.

The file name stays the report's key (`#file=`, the marks, Completed): only what is shown changes. The templates have no
JS engine here, so they are string contracts (test_modality_badge.py's convention); the name itself is the generator's
(`shown_name`), tested as data.
"""
import os
from unittest.mock import patch

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
    # (R2-1) a release's 11-character tag is no YouTube id: a strong episode mark still names the episode
    ("Show - 05 [HEVC-Main10].srt", "Show · Ep 5"),
    ("Show S01E05 [WEBRip-1080].srt", "Show · Ep 5"),
    ("葬送のフリーレン 第05話 [1080p-WEBDL].srt", "葬送のフリーレン · Ep 5"),
    ("[Lilith-Raws] Show - 05 [Lilith-Raws].srt", "Show · Ep 5"),
])
def test_fresh_u_a_file_is_shown_as_its_show_and_episode(filename, shown):
    assert gen.shown_name(filename) == shown


@pytest.mark.parametrize("filename", ["", None, ".srt", "   "])
def test_fresh_u_a_name_with_nothing_to_read_falls_back_to_the_file_name_and_never_raises(filename):
    """Why: the generator names every entry; a name it can't read must never stop the report being written."""
    assert gen.shown_name(filename) == (filename or "")


def _episodes(tmp_path, filenames, stats=()):
    """The journey page's episodes (`journey_render.render`'s head `eps`: [id, file name, shown name, …]) for a list
    whose words are met in `filenames` and a stats file of `stats` (the files already met)."""
    from app import journey_render as jr
    rows = [{"Sequence": i, "Source File": name, "Word": f"単語{i}", "Reading": "タンゴ", "Score": 10,
             "Occurrences (Global)": 2, "Occurrences (File)": 2, "Count (High)": 0, "Count (Low)": 0,
             "Context 1": "冒険に出かけた。"} for i, name in enumerate(filenames, 1)]
    with patch.object(gen, "RESULTS_DIR", str(tmp_path)),          patch.object(gen, "PRIORITY_CSV", str(tmp_path / "none.csv")):
        out = jr.render("ja", rows=rows, priority=[], stats=list(stats), settings={})
    return [(e[1], e[2]) for e in out.head["eps"]]


def test_fresh_u_every_journey_entry_carries_its_shown_name_and_keeps_its_file_name_as_key(tmp_path):
    """Why: the journey shows the episode's name; its file name stays the key the window's `#file=` and the marks use
    (the library's episodes: test_journey_cutover's test_every_episode_carries_its_shown_name_…)."""
    assert _episodes(tmp_path, ["Hoshikuzu Station S01E01.ja.srt", "H_priority_sample_1.txt"]) == [
        ("Hoshikuzu Station S01E01.ja.srt", "Hoshikuzu Station · Ep 1"),
        ("H_priority_sample_1.txt", "H priority sample · Part 1")]


def test_fresh_u_a_file_already_met_is_named_too(tmp_path):
    """Why: a *Target met* file (in the stats, not the list) is an episode of its own, named as the others."""
    assert _episodes(tmp_path, [], [{"File": "Hoshikuzu Station S01E02.ja.srt", "Total Words": 5,
                                     "Coverage (%)": 99}]) == [
        ("Hoshikuzu Station S01E02.ja.srt", "Hoshikuzu Station · Ep 2")]


def test_fresh_u_the_sidebar_and_panels_show_the_name_and_keep_the_file_name_in_the_hover():
    """Why: every place the YouTube preview's page (web_app.html, `modules/youtube_downloader/preview.py`) wrote
    `fileData.filename` as words now writes its name (an old report's data has none: the file name, as before); the
    file name stays findable in the row's hover. (Zen's page retired with the old journey, J-RETIRE.)"""
    html = _template("web_app.html")
    assert "function shownName(fileData)" in html
    assert html.count('data-content="${safeName}"') == 3                 # counted · set aside · target met
    assert 'data-content="${safeFilename}"' not in html
    assert 'tab.title = item.data.filename' in html
    assert "<strong>${fileData.filename}</strong>" not in html            # the Target Met panel
    assert "<strong>${escapeHtml(shownName(fileData))}</strong>" in html


def test_fresh_u_score_is_called_worth_and_the_tier_badge_is_gone():
    html = _template("web_app.html")
    assert "<span>Score: ${data.Score}</span>" not in html
    assert "<span>Worth: ${data.Score}</span>" in html
    assert "${tierBadgesHtml}" not in html                                # G-1, A-2 …: never drawn
    assert "data.Score" in html                                           # the low-leverage tint still reads it
