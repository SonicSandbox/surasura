"""The journey's ▶ on a line only a cut plays (J-CLIP, the render's half; journey v3 SPEC §3.3 `clip/cut`).

The page cuts a line the browser can't play (an .mkv: most anime libraries) through `clip/cut`, but only for a line
whose source has a `play` and whose lines carry their times — and the render gave them only to a file a browser plays
(`play.PLAYABLE`). Now the journey's render asks for the one cutter's videos too (`runner.VIDEO_EXTENSIONS`, the kinds
Connect cuts its cards from): a source whose video sits beside its subtitle gets its `play` ("<dir>/<name>.mkv") and
its lines their times; the page, seeing a name no browser plays, cuts it. (The old page, which asked without the
cutter's kinds and shared the ▶'s memos, retired with Zen: J-RETIRE, 2026-11-23.)

What a wrong answer would cost a learner: no ▶ on any line of an .mkv library (the journey's whole point for anime), a
▶ on a line nothing can play,. Real Japanese and Chinese subtitles from
tests/Test Resources (placed_episode.srt, night_market.srt); video stand-ins (a few bytes, never played).
"""
import gzip
import json
import os
from unittest.mock import patch

import pytest

from app import journey_render as jr
from app import path_utils
from app import static_html_generator as gen
from app.connect import runner
from app.services import play
from tests.test_journey_render_times import _facts
from tests.test_report_line_player import LINE_JA, LINE_ZH, NIGHT, PLACED, _in_library, _stand_in
from tests.test_services_play import _video

SHOW = "放課後の約束"                                   # a made-up show
SOURCE = {"ja": PLACED, "zh": NIGHT}
LINE = {"ja": (LINE_JA, 1.0, 3.2), "zh": (LINE_ZH, 4.1, 7.35)}     # a line of each file, its cue's times
WORDS = {"ja": ["文化祭", "三日", "まで"], "zh": ["夜市", "台北", "今天"]}     # (each in its line)


def _episodes(language, videos):
    """`Library/<show>/` with one subtitle a video kind (".mkv", ".mp4", None: no video beside it) -> [rel path]."""
    rels = []
    for n, ext in enumerate(videos, 1):
        rel, folder = _in_library(language, SHOW, f"{SHOW} - {n:02d}.srt", SOURCE[language])
        if ext == ".mp4":
            _stand_in(os.path.join(folder, f"{SHOW} - {n:02d}.mp4"), b"\x00\x00\x00\x18ftypmp42")
        elif ext:
            _video(os.path.join(folder, f"{SHOW} - {n:02d}{ext}"))
        rels.append(rel)
    return rels


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_an_mkv_library_is_looked_up_for_the_journey_and_as_before_for_the_old_page(language):
    rels = _episodes(language, [".mkv", ".mkv", None])
    found = play.files(language, rels, cut_kinds=runner.VIDEO_EXTENSIONS)
    folder = os.path.dirname(found[rels[0]])
    assert found == {rels[0]: os.path.join(folder, f"{SHOW} - 01.mkv"), rels[1]: os.path.join(folder, f"{SHOW} - 02.mkv"),
                     rels[2]: None}                                     # no video beside it: no ▶, as today
    assert play.files(language, rels) == dict.fromkeys(rels)            # the old page's gate: nothing a browser plays
    media, dirs = gen._line_media(language, set(rels), cut_kinds=runner.VIDEO_EXTENSIONS)
    assert media == {rels[0]: [f"0/{SHOW} - 01.mkv", ""], rels[1]: [f"0/{SHOW} - 02.mkv", ""]} and len(dirs) == 1
    assert gen._line_media(language, set(rels)) == ({}, [])


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("ext", [".avi", ".ts", ".mov"])
def test_every_kind_the_cutter_cuts_gets_its_file_and_one_it_doesnt_none(language, ext):
    rels = _episodes(language, [ext])
    media, _dirs = gen._line_media(language, set(rels), cut_kinds=runner.VIDEO_EXTENSIONS)
    assert media == {rels[0]: [f"0/{SHOW} - 01{ext}", ""]}
    assert ".wmv" not in runner.VIDEO_EXTENSIONS                        # (a kind Connect never cuts: never found)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_video_the_browser_plays_is_the_same_answer_for_both_pages(language):
    rels = _episodes(language, [".mp4", ".mkv"])
    old = gen._line_media(language, set(rels))
    new = gen._line_media(language, set(rels), cut_kinds=runner.VIDEO_EXTENSIONS)
    assert old[0][rels[0]] == new[0][rels[0]] == [f"0/{SHOW} - 01.mp4", ""] and old[1] == new[1]
    assert old[0][rels[1]] == ["", ".mkv"]                              # the old page: its why, as before
    assert new[0][rels[1]] == [f"0/{SHOW} - 02.mkv", ""]


def _render_journey(tmp_path, language, rels):
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    source_map = {rel: {"name": rel.rsplit("/", 1)[-1], "type": "subtitle",
                        "abs": os.path.join(path_utils.get_data_path(language), *rel.split("/"))} for rel in rels}
    text, _start, _end = LINE[language]
    rows = [{"Sequence": n, "Source File": rel.rsplit("/", 1)[-1], "Word": WORDS[language][n - 1],
             "Orth": WORDS[language][n - 1], "Forms": WORDS[language][n - 1], "Reading": "", "Occurrences (File)": 2.0, "Count (High)": 1.0,
             "Count (Low)": 0.0, "Context 1": text, "Src 1": rel} for n, rel in enumerate(rels, 1)]
    stats = [{"File": rel.rsplit("/", 1)[-1]} for rel in rels]
    with patch.object(gen, "RESULTS_DIR", str(results)), patch.object(gen, "_load_source_map", lambda: source_map):
        return jr.render(language, rows, stats=stats, settings={}, facts=_facts({}), stamp="s")


def _sources_and_lines(out):
    """[(the line's text, its source row [label, kind, ep, play, link, item], start, end)] as the chunks carry them."""
    found = []
    for chunk in out.chunks:
        data = json.loads(gzip.decompress(chunk).decode("utf-8"))
        for word in data["w"]:
            for line in word[9] or ():
                line = line + [None] * (4 - len(line))          # (a line's trailing Nones are left out)
                found.append((line[0], data["src"][line[1]], line[2], line[3]))
    return found


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_journey_gives_an_mkv_line_its_play_and_its_times_and_a_line_with_no_video_neither(tmp_path, language):
    rels = _episodes(language, [".mkv", None])
    out = _render_journey(tmp_path, language, rels)
    text, start, end = LINE[language]
    lines = _sources_and_lines(out)
    by_play = {row[3]: (t, s, e) for t, row, s, e in lines}
    assert by_play[f"0/{SHOW} - 01.mkv"] == (text, start, end)          # the page cuts it: clip/cut, its line id
    assert by_play[""][1:] == (None, None)                              # no video beside it: no ▶, no times
    assert len(out.head["dirs"]) == 1 and out.head["dirs"][0].startswith("file:///")
