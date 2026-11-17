"""A video found timed is listened to before its cards are cut (audio quality, Tier 1: `fit_check.heard`,
`lineup.spot_check` for a video, `Steps._spot_video`).

tsubasa times a subtitle against the video's text track, its pictures or its speech, and hato and the video's own
track say the subtitle fits; none of them says what the audio says. A dub, or an audio track in another language,
passes all three, and every card of the episode then plays speech that isn't its sentence. So a timed video is heard
at a few of its lines, as an audiobook's own subtitle is (AB-Q5): Anki Miner cuts them at the shift the fit-check
found and its speech model hears them. Its lines not heard → not timed (*Mine anyway* stays yours).

It costs a speech model, so it runs only where Anki Miner already has one: a video never asks for one, never
downloads one and never waits for one; on battery, and with no answer now, the episode is mined as before.

What a wrong answer would cost: a dubbed episode's cards (the report: English speech under Japanese subtitles), or the
other way, a good episode held back. The fake Anki Miner (`tests/connect/fake_anki_miner.py`) hears a clip as its
line's text unless its plan says otherwise.
"""
import os

import pytest

from app.connect import anki_miner, fit_check, lineup, runner

LINES = ["今日は朝から雨が降っていました", "駅前の本屋で新しい小説を買いました", "帰りに友達と喫茶店に寄りました",
         "その店のケーキはとても美味しかった", "夜になってやっと雨が止みました", "明日は晴れるといいなと思いました",
         "週末は家族と海へ行く予定です"]


def _stamp(s):
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def _episode(tmp_path, lines=None, extra=()):
    """A video (any bytes: the fake never opens it) and its .srt, each line 4 s, 10 s apart; `extra` more cues."""
    cues = [(10.0 * n, 10.0 * n + 4.0, text) for n, text in enumerate(lines or LINES)] + list(extra)
    cues.sort()
    body = "\n".join(f"{n}\n{_stamp(a)} --> {_stamp(b)}\n{t}\n" for n, (a, b, t) in enumerate(cues, 1))
    sub = tmp_path / "episode.ja.srt"
    sub.write_text(body, encoding="utf-8")
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    return str(video), str(sub)


SPEECH = {"installed": ["small"], "model": "small"}


# --------------------------------------------------------------------------- #
# lineup.spot_check, for a video
def test_a_video_is_cut_as_a_video_at_its_offset_and_its_verdict_is_kept_for_that_offset(tmp_path, fake_miner):
    video, sub = _episode(tmp_path)
    fake_miner.plan(speech=SPEECH)
    assert lineup.spot_check(fake_miner.path, "ja", None, video, sub, offset=1.25) == lineup.MATCHED
    [asked] = [c for c in fake_miner.calls() if "media_lines" in c]
    assert asked["video_file"] == video and asked["audio_file"] is None
    assert asked["subtitle_offset"] == 1.25, "cut where its cards would be"
    assert len(asked["media_lines"]) == lineup.SAMPLES
    assert lineup.spot_kept(lineup.spot_key(video, sub, 1.25)) == lineup.MATCHED
    assert lineup.spot_kept(lineup.spot_key(video, sub)) is None, "another shift is another check"
    assert lineup.spot_check(fake_miner.path, "ja", None, video, sub, offset=1.25) == lineup.MATCHED
    assert fake_miner.commands().count("media") == 1, "kept: never heard twice"


def test_a_video_whose_speech_isnt_its_lines_is_not_matched(tmp_path, fake_miner):
    video, sub = _episode(tmp_path)
    places = lineup.samples(lineup.heard_lines(sub, "ja", video=True))
    english = "if you've been using it to chat you're getting a tiny fraction of what it can do"
    fake_miner.plan(speech=SPEECH, heard={p[2][:6]: english for p in places})
    assert lineup.spot_check(fake_miner.path, "ja", None, video, sub) == lineup.NOT_MATCHED


def test_no_offset_sends_none_and_keeps_the_audio_files_key_as_it_was(tmp_path, fake_miner):
    video, sub = _episode(tmp_path)
    fake_miner.plan(speech=SPEECH)
    lineup.spot_check(fake_miner.path, "ja", None, video, sub)
    [asked] = [c for c in fake_miner.calls() if "media_lines" in c]
    assert asked["subtitle_offset"] is None
    assert lineup.spot_key(video, sub) == lineup.spot_key(video, sub, 0.0)
    assert "-o" not in lineup.spot_key(video, sub), "an audiobook's kept verdicts keep their keys"


def test_a_video_is_never_heard_at_a_song_a_sign_or_a_line_shown_again(tmp_path):
    song = [(200.0, 205.0, "♪ 遠い空の向こうへ 飛んでいこう")]
    sign = [(300.0, 304.0, "CLOSED FOR THE WINTER SEASON")]
    again = [(30.0, 34.0, LINES[3])]                    # the same text at the same time: one line
    _video, sub = _episode(tmp_path, extra=song + sign + again)
    heard = lineup.heard_lines(sub, "ja", video=True)
    texts = [t for _s, _e, t in heard]
    assert not any("♪" in t or "空の向こう" in t for t in texts)
    assert not any("CLOSED" in t for t in texts)
    assert texts.count(LINES[3]) == 1
    assert len(lineup.heard_lines(sub, "ja", video=False)) == len(LINES) + 3, "an audio file's SRT as it was"


def test_an_ass_subtitle_is_read_too(tmp_path):
    ass = tmp_path / "episode.ja.ass"
    events = "\n".join(f"Dialogue: 0,0:00:{10 * n:02}.00,0:00:{10 * n + 4:02}.00,Default,,0,0,0,,{t}"
                       for n, t in enumerate(LINES[:5]))
    ass.write_text("[Script Info]\nScriptType: v4.00+\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
                   f"MarginR, MarginV, Effect, Text\n{events}\n", encoding="utf-8")
    heard = lineup.heard_lines(str(ass), "ja", video=True)
    assert [round(s) for s, _e, _t in heard] == [0, 10, 20, 30, 40]


# --------------------------------------------------------------------------- #
# fit_check.heard
TSUBASA = (fit_check.TIMED, "tsubasa", None, 2.5)


@pytest.mark.parametrize("said, out", [
    (fit_check.SPOT_MATCHED, TSUBASA),
    (None, TSUBASA),                                    # no answer now: as before
    (fit_check.SPOT_NOT_MATCHED, (fit_check.NOT_TIMED, "spot-check", fit_check.SPOT_NOT_SAID, 0.0)),
])
def test_a_timed_video_heard_or_not(said, out):
    asked = []
    assert fit_check.heard(TSUBASA, "episode.mkv", lambda offset: asked.append(offset) or said) == out
    assert asked == [2.5], "listened to at the offset found"


@pytest.mark.parametrize("answer, video", [
    ((fit_check.TIMED, "hato", None, 0.0), "episode.mkv"),
    ((fit_check.TIMED, "track", None, 0.0), "episode.mkv"),
])
def test_hato_and_the_videos_own_track_are_listened_to_too(answer, video):
    out = fit_check.heard(answer, video, lambda offset: fit_check.SPOT_NOT_MATCHED)
    assert out[:3] == (fit_check.NOT_TIMED, "spot-check", fit_check.SPOT_NOT_SAID)


@pytest.mark.parametrize("answer, video", [
    ((fit_check.TIMED, "audio", None, 0.0), "episode.mkv"),        # transcribed from the audio itself
    ((fit_check.TIMED, "you", None, 0.0), "episode.mkv"),          # *Trust my subtitles' timing*
    ((fit_check.TIMED, "spot-check", None, 0.0), "book.mp3"),      # an audio file: heard already
    ((fit_check.TIMED, "tsubasa", None, 1.0), "book.mp3"),
    ((fit_check.NOT_TIMED, "tsubasa", "no", 0.0), "episode.mkv"),
    ((fit_check.RETRY, "tsubasa", "later", 0.0), "episode.mkv"),
])
def test_anything_else_is_answered_as_it_was_and_never_listened_to(answer, video):
    def never(offset):
        raise AssertionError("listened to")
    assert fit_check.heard(answer, video, never) == answer
    assert fit_check.heard(answer, video, None) == answer


# --------------------------------------------------------------------------- #
# Steps: when the runner listens
@pytest.fixture
def steps(tmp_path, monkeypatch):
    s = runner.Steps({})
    monkeypatch.setattr(s, "run_dir", lambda job: str(tmp_path / "runs" / str(job["id"])))
    monkeypatch.setattr(s, "_miner_profile", lambda lang, job: ("AnkiMiner.exe", "surasura"))
    monkeypatch.setattr(s, "on_battery", lambda: False)
    monkeypatch.setattr(anki_miner, "speech_ready", lambda *a, **k: True)
    heard = []

    def spot_check(miner, lang, profile, video, subtitle, timeout=None, offset=0.0):
        heard.append((video, offset))
        return lineup.NOT_MATCHED
    monkeypatch.setattr(lineup, "spot_check", spot_check)
    s.heard = heard
    return s


def test_a_timed_video_with_a_model_on_this_pc_is_heard(tmp_path, steps):
    video, sub = _episode(tmp_path)
    assert steps._spot_video("ja", {"id": 1}, video, sub, 2.5) == lineup.NOT_MATCHED
    assert steps.heard == [(video, 2.5)]


def test_no_model_on_this_pc_is_never_asked_for_and_the_video_mines_as_before(tmp_path, steps, monkeypatch):
    video, sub = _episode(tmp_path)
    monkeypatch.setattr(anki_miner, "speech_ready", lambda *a, **k: False)
    assert steps._spot_video("ja", {"id": 1}, video, sub, 0.0) is None
    assert steps.heard == [] and lineup.look(lineup.SPEECH).get("status") is None, "nothing downloaded"


def test_not_now_or_a_download_running_or_battery_is_no_check_now(tmp_path, steps, monkeypatch):
    video, sub = _episode(tmp_path)
    monkeypatch.setattr(lineup, "answer", lambda: "no")
    assert steps._spot_video("ja", {"id": 1}, video, sub, 0.0) is None
    monkeypatch.setattr(lineup, "answer", lambda: None)
    monkeypatch.setattr(lineup, "look", lambda name: {"status": lineup.RUNNING})
    assert steps._spot_video("ja", {"id": 1}, video, sub, 0.0) is None
    monkeypatch.setattr(lineup, "look", lambda name: {})
    monkeypatch.setattr(steps, "on_battery", lambda: True)
    assert steps._spot_video("ja", {"id": 1}, video, sub, 0.0) is None, "checked once plugged in"
    assert steps._spot_video("ja", {"id": 1, "asked_at": 1.0}, video, sub, 0.0) == lineup.NOT_MATCHED, \
        "your *Mine now* listens on battery, as a line-up does"
    assert len(steps.heard) == 1


def test_a_kept_verdict_answers_without_anki_miner(tmp_path, steps, monkeypatch):
    video, sub = _episode(tmp_path)
    lineup._keep_spot(lineup.spot_key(video, sub, 2.5), lineup.MATCHED, [1.0] * 5)
    monkeypatch.setattr(steps, "_miner_profile", lambda lang, job: pytest.fail("Anki Miner asked"))
    assert steps._spot_video("ja", {"id": 1}, video, sub, 2.5) == lineup.MATCHED


def test_a_failed_call_is_no_answer_now(tmp_path, steps, monkeypatch):
    video, sub = _episode(tmp_path)

    def failed(*a, **k):
        raise anki_miner.AnkiMinerError("failed", "it crashed")
    monkeypatch.setattr(lineup, "spot_check", failed)
    assert steps._spot_video("ja", {"id": 1}, video, sub, 0.0) is None


def test_the_fit_step_listens_to_a_video_only_after_it_is_timed_and_never_when_you_trust_its_timing(
        tmp_path, steps, monkeypatch):
    video, sub = _episode(tmp_path)
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: TSUBASA)
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    assert steps.fit("ja", {"id": 1}, None, video, sub) == (
        fit_check.NOT_TIMED, "spot-check", fit_check.SPOT_NOT_SAID, 0.0)
    monkeypatch.setattr(steps, "_settings", lambda lang: {"connect_trust_timing": True})
    assert steps.fit("ja", {"id": 1}, None, video, sub) == TSUBASA
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: False)      # an Anki Miner too old to cut and hear
    assert steps.fit("ja", {"id": 1}, None, video, sub) == TSUBASA
    assert steps.heard == [(video, 2.5)]
