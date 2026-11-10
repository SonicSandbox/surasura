# SPDX-License-Identifier: GPL-3.0-or-later
"""Cue sidecars — the timings that let the report jump to a moment in a video.

Written beside every transcript, and deliberately SEPARATE from the transcript text: the timestamped
display format puts one cue per line, and a line break is a hard sentence boundary in Japanese, so
writing times inline would visibly degrade the example sentences the analyzer produces.
"""

import json
import os
from unittest.mock import patch

import pytest

from modules.youtube_downloader import downloader as core

# A real-shaped WebVTT: header, cue timings, and the roll-up duplication auto-captions produce.
VTT = """WEBVTT
Kind: captions
Language: ja

00:00:02.480 --> 00:00:05.120
秘密の多い街を歩いてきました

00:00:05.120 --> 00:00:09.400
秘密の多い街を歩いてきました
答えはまだ見つかりません

00:01:02.000 --> 00:01:05.000
それでも探し続けるつもりです
"""

INFO = {"id": "dQw4w9WgXcQ", "title": "今日の話題",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}


# --- cue extraction ------------------------------------------------------------------------------ #
def test_cues_carry_start_times_in_seconds():
    cues = core.clean_vtt_cues(VTT)
    assert [text for text, _ in cues] == [
        "秘密の多い街を歩いてきました",
        "答えはまだ見つかりません",
        "それでも探し続けるつもりです",
    ], "roll-up duplicates must still be collapsed"
    assert [sec for _, sec in cues] == [2, 5, 62]


def test_clean_vtt_still_returns_plain_lines():
    """The original helper is unchanged — the transcript body must not shift."""
    assert core.clean_vtt(VTT) == [t for t, _ in core.clean_vtt_cues(VTT)]


def test_timestamps_mode_is_unaffected():
    lines = core.clean_vtt(VTT, keep_timestamps=True)
    assert lines[0].startswith("[00:00:02] ")


@pytest.mark.parametrize("stamp,expected", [
    ("00:00:02", 2), ("00:01:05", 65), ("01:02:03", 3723),
    ("12:03", 723), ("00:00:09.400", 9), ("nonsense", None), ("", None),
])
def test_timestamp_parsing(stamp, expected):
    assert core.ts_seconds(stamp) == expected


# --- the sidecar file ----------------------------------------------------------------------------- #
def test_sidecar_sits_beside_the_transcript(tmp_path):
    txt = tmp_path / "チャンネル - 今日の話題 [dQw4w9WgXcQ].txt"
    assert core.sidecar_path(str(txt)).endswith(".surasura.json")
    assert os.path.dirname(core.sidecar_path(str(txt))) == str(tmp_path)


def test_sidecar_payload(tmp_path):
    txt = tmp_path / "vid [dQw4w9WgXcQ].txt"
    txt.write_text("秘密の多い街を歩いてきました 答えはまだ見つかりません", encoding="utf-8")
    assert core.write_sidecar(str(txt), INFO, core.clean_vtt_cues(VTT))

    with open(core.sidecar_path(str(txt)), encoding="utf-8") as f:
        data = json.load(f)
    assert data["video_id"] == "dQw4w9WgXcQ"
    assert data["url"].endswith("dQw4w9WgXcQ")
    assert data["cues"][0] == ["秘密の多い街を歩いてきました", 2]


def test_untimed_cues_are_dropped(tmp_path):
    """A line with no cue header can't be jumped to, so it must not pretend to have a time."""
    txt = tmp_path / "v [dQw4w9WgXcQ].txt"
    txt.write_text("x", encoding="utf-8")
    core.write_sidecar(str(txt), INFO, [("timed", 5), ("untimed", None)])
    with open(core.sidecar_path(str(txt)), encoding="utf-8") as f:
        assert json.load(f)["cues"] == [["timed", 5]]


def test_sidecar_write_never_raises(tmp_path):
    """The transcript is what the user asked for — a sidecar failure must never cost them that."""
    assert core.write_sidecar(str(tmp_path / "nope" / "deep" / "a.txt"), INFO, [("a", 1)]) is False


def test_sidecar_skipped_when_there_is_nothing_to_record(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("x", encoding="utf-8")
    assert core.write_sidecar(str(txt), {}, []) is False
    assert not os.path.exists(core.sidecar_path(str(txt)))


# --- backfill -------------------------------------------------------------------------------------- #
def test_backfill_targets_only_transcripts_missing_cues(tmp_path):
    (tmp_path / "有る [dQw4w9WgXcQ].txt").write_text("x", encoding="utf-8")
    (tmp_path / "有る [dQw4w9WgXcQ].surasura.json").write_text("{}", encoding="utf-8")
    (tmp_path / "無い [aBcDeFgHiJk].txt").write_text("x", encoding="utf-8")
    (tmp_path / "手書きのメモ.txt").write_text("x", encoding="utf-8")     # no video id
    sub = tmp_path / "playlist"; sub.mkdir()
    (sub / "入れ子 [kLmNoPqRsTu].txt").write_text("x", encoding="utf-8")

    found = core.find_transcripts_missing_cues(str(tmp_path))
    ids = sorted(vid for _p, vid in found)
    assert ids == ["aBcDeFgHiJk", "kLmNoPqRsTu"], "only un-sidecar'd transcripts, nested included"


def test_backfill_is_a_no_op_when_everything_has_cues(tmp_path):
    (tmp_path / "a [dQw4w9WgXcQ].txt").write_text("x", encoding="utf-8")
    (tmp_path / "a [dQw4w9WgXcQ].surasura.json").write_text("{}", encoding="utf-8")
    logs = []
    summary = core.backfill_cues(str(tmp_path), log=logs.append)
    assert (summary["written"], summary["no_transcript"], summary["errors"]) == (0, 0, 0)
    assert any("nothing to backfill" in m for m in logs)


def test_backfill_writes_cues_without_touching_the_transcript(tmp_path):
    body = "秘密の多い街を歩いてきました 答えはまだ見つかりません"
    txt = tmp_path / "動画 [dQw4w9WgXcQ].txt"
    txt.write_text(body, encoding="utf-8")

    def fake_run(args, timeout=None, **_kw):
        out = args[args.index("-o") + 1].replace("%(id)s.%(ext)s", "")
        with open(os.path.join(out, "dQw4w9WgXcQ.ja.vtt"), "w", encoding="utf-8") as f:
            f.write(VTT)
        with open(os.path.join(out, "dQw4w9WgXcQ.info.json"), "w", encoding="utf-8") as f:
            json.dump(INFO, f)
        return None

    with patch.object(core, "_run_ytdlp", side_effect=fake_run):
        summary = core.backfill_cues(str(tmp_path), log=lambda *_: None)

    assert summary["written"] == 1
    assert txt.read_text(encoding="utf-8") == body, "the transcript must never be rewritten"
    with open(core.sidecar_path(str(txt)), encoding="utf-8") as f:
        data = json.load(f)
    assert data["video_id"] == "dQw4w9WgXcQ"
    assert data["cues"][0] == ["秘密の多い街を歩いてきました", 2]


def test_backfill_paces_itself_in_batches(tmp_path):
    """Back-to-back requests earn a 429. Pauses between videos, and a longer rest each batch."""
    for i in range(core.BATCH_SIZE + 3):
        (tmp_path / f"v{i} [{'a' * 10}{i % 10}].txt").write_text("x", encoding="utf-8")

    slept = []
    with patch.object(core, "_run_ytdlp", side_effect=lambda *a, **k: None):
        core.backfill_cues(str(tmp_path), log=lambda *_: None,
                           sleep=slept.append)

    assert slept.count(core.BATCH_PAUSE) == 1, "one long rest after a full batch"
    assert slept.count(core.REQUEST_PAUSE) == core.BATCH_SIZE + 1, "a short pause between videos"
    assert slept[0] == core.REQUEST_PAUSE, "no pause before the very first request"


def test_backfill_stops_when_youtube_throttles(tmp_path):
    """Being rate-limited means every remaining request fails too — stop instead of digging in."""
    for i in range(6):
        (tmp_path / f"v{i} [{'b' * 10}{i}].txt").write_text("x", encoding="utf-8")

    class Res:
        stderr = "ERROR: HTTP Error 429: Too Many Requests"

    logs = []
    with patch.object(core, "_run_ytdlp", return_value=Res()):
        summary = core.backfill_cues(str(tmp_path), log=logs.append, sleep=lambda _s: None)

    assert summary["stopped"] is True
    assert summary["remaining"] == 6, "nothing was written, so all of them still need doing"
    assert any("rate-limiting" in m for m in logs)


def test_backfill_gives_up_after_repeated_failures(tmp_path):
    for i in range(10):
        (tmp_path / f"v{i} [{'c' * 10}{i}].txt").write_text("x", encoding="utf-8")
    with patch.object(core, "_run_ytdlp", side_effect=OSError("network down")):
        summary = core.backfill_cues(str(tmp_path), log=lambda *_: None, sleep=lambda _s: None)
    assert summary["stopped"] is True
    assert summary["errors"] == core.MAX_CONSECUTIVE_ERRORS


def test_backfill_can_be_stopped_and_resumes_next_time(tmp_path):
    """Closing the window stops the run; finished sidecars stay, so a re-run does the rest."""
    for i in range(5):
        (tmp_path / f"v{i} [{'d' * 10}{i}].txt").write_text("x", encoding="utf-8")

    calls = {"n": 0}

    def stop_after_two():
        calls["n"] += 1
        return calls["n"] > 2

    with patch.object(core, "_run_ytdlp", side_effect=lambda *a, **k: None):
        summary = core.backfill_cues(str(tmp_path), log=lambda *_: None,
                                     sleep=lambda _s: None, should_stop=stop_after_two)
    assert summary["stopped"] is True
    assert summary["remaining"] > 0
    # A later run still sees everything that was never written.
    assert len(core.find_transcripts_missing_cues(str(tmp_path))) == 5


def test_backfill_reports_a_video_with_no_captions(tmp_path):
    (tmp_path / "動画 [dQw4w9WgXcQ].txt").write_text("x", encoding="utf-8")
    with patch.object(core, "_run_ytdlp", side_effect=lambda *a, **k: None):
        summary = core.backfill_cues(str(tmp_path), log=lambda *_: None)
    assert (summary["written"], summary["no_transcript"], summary["errors"]) == (0, 1, 0)


def test_backfill_survives_a_network_error(tmp_path):
    (tmp_path / "動画 [dQw4w9WgXcQ].txt").write_text("x", encoding="utf-8")
    with patch.object(core, "_run_ytdlp", side_effect=OSError("network down")):
        summary = core.backfill_cues(str(tmp_path), log=lambda *_: None)
    assert summary["errors"] == 1
