# SPDX-License-Identifier: GPL-3.0-or-later
"""Source badges inside the YouTube Preview, and the filename cases real libraries actually contain.

The preview builds its own report instead of going through static_html_generator, so it has to inject
the same source table — otherwise the badge is silently inert there while working everywhere else.

It also covers the filename shape that broke first in the wild: Graduate/Demote append a
`_<timestamp>` when resolving a name collision, sometimes twice, which pushed the video id off the
end of the stem and stopped these files being recognised as YouTube sources at all.
"""

import json
import os
from unittest.mock import patch

import pytest

from app.path_utils import infer_source_type
from modules.youtube_downloader import downloader as core
from modules.youtube_downloader import preview

# A library's file names as they come — two collision stamps appended after the id.
RENAMED = ("hanashi radio - 【Japanese Podcast #10】春の話、新しいこと！ "
           "[podcast0035]_20260622001222_20260730163200.txt")
FRESH = "はなこ - 【雑談】週末の過ごし方 [talkshow001].txt"


# --- filenames renamed by a tier move ------------------------------------------------------------- #
@pytest.mark.parametrize("name", [RENAMED, FRESH,
                                  "chan - title [podcast0030]_20260622001241.txt",
                                  "chan - title [podcast0035] (2).txt"])
def test_renamed_transcripts_are_still_youtube(name):
    """A tier move must not cost a transcript its identity — that's what silently disabled the ▶
    badge and made the backfill skip it."""
    assert infer_source_type(name) == "youtube", name


@pytest.mark.parametrize("name", ["[HorribleSub] ep01.txt", "本 [A1B2C3D4].txt",
                                  "[SubsPlease]_x264.txt", "ふつうのメモ.txt"])
def test_release_tags_are_still_not_videos(name):
    """The relaxed pattern must not start matching fansub tags — '[HorribleSub]' is exactly 11."""
    assert infer_source_type(name) == "text", name


def test_backfill_finds_renamed_transcripts(tmp_path):
    (tmp_path / RENAMED).write_text("x", encoding="utf-8")
    found = core.find_transcripts_missing_cues(str(tmp_path))
    assert [vid for _p, vid in found] == ["podcast0035"]


def test_backfill_reaches_transcripts_that_live_in_a_tier(tmp_path):
    """A transcript is COPIED into a tier when added to the library, and it's that copy the analyzer
    reads — so it's the copy that needs the sidecar. Scanning Processed alone missed all of them."""
    processed = tmp_path / "Processed"; processed.mkdir()
    tier = tmp_path / "HighPriority" / "Hanashi Radio"; tier.mkdir(parents=True)
    (processed / FRESH).write_text("x", encoding="utf-8")
    (tier / RENAMED).write_text("x", encoding="utf-8")

    from_root = {vid for _p, vid in core.find_transcripts_missing_cues(str(tmp_path))}
    assert from_root == {"talkshow001", "podcast0035"}
    from_processed = {vid for _p, vid in core.find_transcripts_missing_cues(str(processed))}
    assert "podcast0035" not in from_processed, "the tier copy is exactly what used to be missed"


# --- preview report ------------------------------------------------------------------------------- #
def _words():
    return [{
        "Word": "秘密", "Reading": "ヒミツ", "Score": 30,
        "Context 1": "秘密の多い街を歩いてきました。", "Src 1": preview.VIDEO_SOURCE,
        "Context 2": "この街には、まだ秘密が残っている。", "Src 2": "HighPriority/ep01.srt",
    }]


def _render(tmp_path, files, settings, sources=None):
    out = tmp_path / "preview.html"
    with patch.object(preview.settings_manager, "load_settings", return_value=settings), \
         patch("app.static_html_generator._load_source_map", return_value=sources or {}):
        preview.generate_preview_html(files, "ja", str(out))
    return out.read_text(encoding="utf-8")


def _injected(html, name):
    payload = html.split(f"let {name} = ", 1)[1].split(";\n", 1)[0]
    return json.loads(payload) if payload.startswith(("[", "{")) else payload.strip("'")


def test_preview_injects_the_source_table(tmp_path):
    """Without this the badge is inert in the preview while working in the main report."""
    html = _render(tmp_path, [("chan - t [podcast0035]", _words())],
                   {"source_display": "full"},
                   sources={"HighPriority/ep01.srt": {"name": "ep01.srt", "type": "subtitle",
                                                      "abs": "C:/lib/ep01.srt"}})
    assert _injected(html, "globalSourceDisplay") == "full"
    table = _injected(html, "globalSources")
    assert len(table) == 2

    video, library = table
    assert video[1] == "youtube" and video[4] == "podcast0035", "the video row carries its id"
    assert library[1] == "subtitle" and library[0] == "ep01.srt"


def test_preview_display_mode_follows_the_setting(tmp_path):
    for mode, expected in (("off", "off"), ("icon", "icon"), ("nonsense", "off")):
        html = _render(tmp_path, [("chan - t [podcast0035]", _words())], {"source_display": mode})
        assert _injected(html, "globalSourceDisplay") == expected


def test_each_video_in_a_playlist_gets_its_own_source(tmp_path):
    """VIDEO_SOURCE means 'this entry's own video', so it must resolve per file — a playlist preview
    holds several, and they must not collapse onto one another."""
    files = [("a - one [podcast0035]", _words()), ("b - two [talkshow001]", _words())]
    html = _render(tmp_path, files, {"source_display": "icon"})
    ids = [row[4] for row in _injected(html, "globalSources") if row[1] == "youtube"]
    assert sorted(ids) == ["podcast0035", "talkshow001"]


def test_src_values_become_indices_into_the_table(tmp_path):
    html = _render(tmp_path, [("chan - t [podcast0035]", _words())], {"source_display": "full"})
    data = _injected(html, "globalData")
    keys = data["priority"]["keys"]
    row = data["priority"]["rows"][0]
    for col in ("Src 1", "Src 2"):
        assert isinstance(row[keys.index(col)], int), f"{col} must be interned to an index"


def test_preview_still_works_without_the_optional_path(tmp_path):
    """Older callers pass (name, words); the badge should still link to the video, just not to a
    specific moment."""
    html = _render(tmp_path, [("chan - t [podcast0035]", _words())], {"source_display": "icon"})
    assert _injected(html, "globalSources")[0][4] == "podcast0035"


def test_library_sentences_keep_their_own_source(tmp_path):
    """A borrowed library sentence must point at the library file, not at the video."""
    html = _render(tmp_path, [("chan - t [podcast0035]", _words())], {"source_display": "full"},
                   sources={"HighPriority/ep01.srt": {"name": "ep01.srt", "type": "subtitle"}})
    table = _injected(html, "globalSources")
    assert [r for r in table if r[1] == "subtitle"], "the library file must appear as its own source"


def test_library_contexts_carry_their_source_column(tmp_path):
    """load_library_contexts pairs each sentence with its Src N so the preview can badge it."""
    csv_path = tmp_path / "priority_learning_list.csv"
    csv_path.write_text(
        "Word,Reading,Context 1,Src 1,Context 2,Src 2\n"
        "秘密,ヒミツ,この街には秘密が残っている。,HighPriority/ep01.srt,秘密の部屋。,HighPriority/本.txt\n",
        encoding="utf-8-sig")
    with patch.object(preview, "library_contexts_path", return_value=str(csv_path)):
        by_lr, _by_lemma = preview.load_library_contexts()
    assert by_lr[("秘密", "ヒミツ")] == [
        ("この街には秘密が残っている。", "HighPriority/ep01.srt"),
        ("秘密の部屋。", "HighPriority/本.txt"),
    ]


def test_library_contexts_survive_results_without_src_columns(tmp_path):
    """Results generated before the Src columns existed must still supply sentences."""
    csv_path = tmp_path / "old.csv"
    csv_path.write_text("Word,Reading,Context 1\n秘密,ヒミツ,この街には秘密が残っている。\n",
                        encoding="utf-8-sig")
    with patch.object(preview, "library_contexts_path", return_value=str(csv_path)):
        by_lr, _ = preview.load_library_contexts()
    assert by_lr[("秘密", "ヒミツ")] == [("この街には秘密が残っている。", "")]
