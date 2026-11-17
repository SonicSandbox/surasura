"""A video found timed is listened to before its cards are cut (audio quality, Tier 1: `fit_check.heard`,
`lineup.spot_check` for a video, `Steps._spot_video`).

tsubasa times a subtitle against the video's text track, its pictures or its speech, and hato and the video's own
track say the subtitle fits; none of them says what the audio says. A dub, or an audio track in another language,
passes all three, and every card of the episode then plays speech that isn't its sentence. So a timed video is heard
at a few of its lines, as an audiobook's own subtitle is (AB-Q5): Anki Miner cuts them at the shift the fit-check
found and its speech model hears them. Its lines not heard → not timed (*Mine anyway* stays yours).

It costs a speech model, so it runs only where Anki Miner already has one: a video never asks for one, never
downloads one and never waits for one; on battery, and with no answer now, the episode is mined as before.

Michi-T1 (Sonic 2026-11-17: it is too slow in line, mining must run extremely quickly): the episodes of one release
share their audio track, so one episode of a release is heard, beside the mining (`runner._Ahead`), and its verdict
answers for the rest (`lineup.release_key`); the releases next in line are heard ahead (`Steps.listen_ahead`). No
answer yet → mined as before, never a wait. *Check every episode's audio first* (`runner.EVERY_EPISODE`, off by
default) keeps #498's way: every episode heard before its mining.

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


@pytest.mark.parametrize("raised", [runner.Wait("Anki Miner is busy"), runner.Needs("anki-miner", "Set it up")])
def test_anki_miners_setup_waiting_is_no_check_now_never_a_wait_or_a_question(tmp_path, steps, monkeypatch, raised):
    # the mine step that follows meets the same setup and says so itself; the check never waits or asks
    video, sub = _episode(tmp_path)

    def setup(lang, job):
        raise raised
    monkeypatch.setattr(steps, "_miner_profile", setup)
    assert steps._spot_video("ja", {"id": 1}, video, sub, 0.0) is None
    assert steps.heard == []


def test_a_spot_folder_it_cannot_write_is_no_answer_now(tmp_path, steps, monkeypatch):
    video, sub = _episode(tmp_path)

    def unwritable(*a, **k):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(lineup, "spot_check", unwritable)
    assert steps._spot_video("ja", {"id": 1}, video, sub, 0.0) is None


def test_every_episode_first_listens_before_its_mining_as_498_did_and_never_when_you_trust_its_timing(
        tmp_path, steps, monkeypatch):
    # *Check every episode's audio first* (off by default): the per-episode check, in line, before the cards are cut
    video, sub = _episode(tmp_path)
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: TSUBASA)
    monkeypatch.setattr(steps, "_settings", lambda lang: {runner.EVERY_EPISODE: True})
    assert steps.fit("ja", {"id": 1}, None, video, sub) == (
        fit_check.NOT_TIMED, "spot-check", fit_check.SPOT_NOT_SAID, 0.0)
    assert lineup.release_kept(lineup.release_key(video)) == lineup.NOT_MATCHED, "its release's verdict kept too"
    monkeypatch.setattr(steps, "_settings", lambda lang: {"connect_trust_timing": True, runner.EVERY_EPISODE: True})
    assert steps.fit("ja", {"id": 1}, None, video, sub) == TSUBASA
    monkeypatch.setattr(steps, "_settings", lambda lang: {runner.EVERY_EPISODE: True})
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: False)      # an Anki Miner too old to cut and hear
    assert steps.fit("ja", {"id": 1}, None, video, sub) == TSUBASA
    assert steps.heard == [(video, 2.5)]
    assert not steps._ahead.busy(), "nothing heard beside the mining in this mode"


# --------------------------------------------------------------------------- #
# Michi-T1: once a release, beside the mining (Sonic 2026-11-17: mining runs extremely quickly)
ZH_LINES = ["今天早上开始一直在下雨", "我在车站前的书店买了一本新小说", "回家的路上和朋友去了咖啡店",
            "那家店的蛋糕非常好吃", "到了晚上雨终于停了", "希望明天会是晴天", "周末打算和家人去海边"]


def _season(tmp_path, folder, names, lines=None):
    """Episodes of one release: each its video (any bytes) and its .srt, in `folder`."""
    where = tmp_path / folder
    where.mkdir(parents=True, exist_ok=True)
    out = []
    for name in names:
        video, sub = _episode(where, lines)
        stem = os.path.splitext(name)[0]
        os.replace(video, str(where / name))
        os.replace(sub, str(where / f"{stem}.srt"))
        out.append((str(where / name), str(where / f"{stem}.srt")))
    return out


def _settled(steps, timeout=10.0):
    import time
    end = time.monotonic() + timeout
    while steps._ahead.busy():
        assert time.monotonic() < end, "the check beside the mining never ended"
        time.sleep(0.01)


@pytest.mark.parametrize("names, other", [
    # a fansub release: episodes 1, 2 and 12 one release; its batch in another folder, a dub, another season, an .mp4
    (["[SubsPlease] 薬屋のひとりごと - 01 (1080p) [A1B2C3D4].mkv", "[SubsPlease] 薬屋のひとりごと - 02 (1080p) [99AA0B1C].mkv",
      "[SubsPlease] 薬屋のひとりごと - 12v2 (1080p) [0F0F0F0F].mkv"],
     ["[Erai-raws] 薬屋のひとりごと - 03 [1080p].mkv", "[SubsPlease] 薬屋のひとりごと - 04 (1080p) [Dual Audio].mkv",
      "[SubsPlease] 薬屋のひとりごと S2 - 01 (1080p).mkv", "[SubsPlease] 薬屋のひとりごと - 05 (1080p).mp4"]),
    # a Chinese library's names
    (["[桜都字幕组] 葬送的芙莉莲 - 01 [1080p][简日双语].mp4", "[桜都字幕组] 葬送的芙莉莲 - 02 [1080p][简日双语].mp4"],
     ["[喵萌奶茶屋] 葬送的芙莉莲 - 03 [1080p][简日双语].mp4", "[桜都字幕组] 葬送的芙莉莲 第2期 - 01 [1080p][简日双语].mp4"]),
])
def test_one_release_is_one_key_and_another_group_season_dub_or_layout_is_another(tmp_path, names, other):
    keys = {lineup.release_key(str(tmp_path / "show" / n)) for n in names}
    assert len(keys) == 1 and None not in keys
    [key] = keys
    for name in other:
        assert lineup.release_key(str(tmp_path / "show" / name)) != key, name
    assert lineup.release_key(str(tmp_path / "batch" / names[0])) != key, "another folder is checked again"


@pytest.fixture
def held(monkeypatch):
    """The check beside the mining held until the test lets it go; who was heard, in order."""
    import threading
    gate, heard = threading.Event(), []

    def spot_check(miner, lang, profile, video, subtitle, timeout=None, offset=0.0):
        heard.append(os.path.basename(video))
        assert gate.wait(10)
        return held.verdict
    held = type("Held", (), {"gate": gate, "heard": heard, "verdict": lineup.NOT_MATCHED})
    monkeypatch.setattr(lineup, "spot_check", spot_check)
    return held


@pytest.mark.parametrize("lang, lines", [("ja", None), ("zh", ZH_LINES)])
def test_the_first_episode_mines_at_once_and_the_rest_of_its_release_has_the_answer(
        tmp_path, steps, monkeypatch, held, lang, lines):
    import time
    season = _season(tmp_path, "show", [f"Show - {n:02}.mkv" for n in (1, 2, 3)], lines)
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: (fit_check.TIMED, "hato", None, 0.0))
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    at = time.monotonic()
    assert steps.fit(lang, {"id": 1}, None, *season[0]) == (fit_check.TIMED, "hato", None, 0.0), "no answer yet"
    assert time.monotonic() - at < 1.0, "never waits for the check (it is held)"
    held.gate.set()
    _settled(steps)
    assert held.heard == ["Show - 01.mkv"]
    for job, (video, sub) in enumerate(season[1:], 2):
        assert steps.fit(lang, {"id": job}, None, video, sub) == (
            fit_check.NOT_TIMED, "spot-check", fit_check.SPOT_RELEASE_NOT_SAID, 0.0), \
            "the release held, said as another episode's, Mine anyway yours"
    assert held.heard == ["Show - 01.mkv"], "once a release"
    other = _season(tmp_path, "other show", ["Other - 01.mkv"], lines)[0]
    assert steps.fit(lang, {"id": 9}, None, *other)[0] == fit_check.TIMED, "another release: asked again"
    _settled(steps)
    assert held.heard[-1] == "Other - 01.mkv"


def test_a_heard_release_mines_as_before_and_no_answer_is_asked_again_at_the_next_episode(
        tmp_path, steps, monkeypatch, held):
    season = _season(tmp_path, "show", [f"Show - {n:02}.mkv" for n in (1, 2, 3)])
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: TSUBASA)
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    held.gate.set()
    held.verdict = None                         # no model, a failed call: nothing kept
    assert steps.fit("ja", {"id": 1}, None, *season[0]) == TSUBASA
    _settled(steps)
    held.verdict = lineup.MATCHED
    assert steps.fit("ja", {"id": 2}, None, *season[1]) == TSUBASA
    _settled(steps)
    assert held.heard == ["Show - 01.mkv", "Show - 02.mkv"], "heard again: the first gave no answer"
    assert steps.fit("ja", {"id": 3}, None, *season[2]) == TSUBASA
    _settled(steps)
    assert len(held.heard) == 2, "heard: its release mines as before, never heard again"


def test_an_episodes_own_kept_verdict_is_read_before_its_releases(tmp_path, steps, monkeypatch, held):
    (video, sub), = _season(tmp_path, "show", ["Show - 01.mkv"])
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: TSUBASA)
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    lineup._keep_spot(lineup.spot_key(video, sub, 2.5), lineup.NOT_MATCHED, [0.1] * 5)
    lineup.keep_release(lineup.release_key(video), lineup.MATCHED, video, sub)
    assert steps.fit("ja", {"id": 1}, None, video, sub)[2] == fit_check.SPOT_NOT_SAID, "its own, said as its own"
    assert held.heard == [] and not steps._ahead.busy()


def test_a_release_replaced_under_the_same_names_is_heard_again(tmp_path, steps, monkeypatch, held):
    # the learner swaps a dubbed release for the right one in the same folder: the verdict was the old files'
    season = _season(tmp_path, "show", ["Show - 01.mkv", "Show - 02.mkv"])
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: (fit_check.TIMED, "hato", None, 0.0))
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    key = lineup.release_key(season[0][0])
    lineup.keep_release(key, lineup.NOT_MATCHED, *season[0])
    assert steps.fit("ja", {"id": 2}, None, *season[1])[0] == fit_check.NOT_TIMED
    with open(season[0][0], "ab") as f:
        f.write(b"the right audio track")
    assert lineup.release_kept(key) is None
    assert steps.fit("ja", {"id": 2}, None, *season[1])[0] == fit_check.TIMED, "no answer: mined as before"
    held.gate.set()
    _settled(steps)
    assert held.heard == ["Show - 02.mkv"]
    os.remove(season[0][0])
    assert lineup.release_kept(key) == lineup.NOT_MATCHED, "kept from episode 2 now (held.verdict)"


def test_no_anki_miner_for_the_fit_is_nothing_heard(tmp_path, steps, monkeypatch, held):
    (video, sub), = _season(tmp_path, "show", ["Show - 01.mkv"])
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: TSUBASA)
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    for answer in (lambda lang, job: None, lambda lang, job: (_ for _ in ()).throw(runner.Wait("busy"))):
        monkeypatch.setattr(steps, "_miner_profile", answer)
        assert steps.fit("ja", {"id": 1}, None, video, sub) == TSUBASA
    assert held.heard == [] and not steps._ahead.busy()


def _hato(video, sub):
    import hashlib
    with open(sub, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return {"schema": 1, "verdict": "timed", "timing": {"segments": 1, "reference": "text-track"},
            "subtitle_sha256": sha, "video_path": video}


def test_the_next_releases_in_line_are_heard_beside_the_mining_in_their_order(tmp_path, steps, monkeypatch, held):
    a = _season(tmp_path, "a", ["A - 01.mkv", "A - 02.mkv"])
    b = _season(tmp_path, "b", ["B - 01.mkv"])
    c = _season(tmp_path, "c", ["C - 01.mkv"])
    t = _season(tmp_path, "t", ["T - 01.mkv"])         # timed by tsubasa only: its shift unknown before its fit
    k = _season(tmp_path, "k", ["K - 01.mkv"])         # its release already heard
    lineup.keep_release(lineup.release_key(k[0][0]), lineup.MATCHED, *k[0])
    by_id = {1: a[0], 2: a[1], 3: t[0], 4: b[0], 5: k[0], 6: c[0]}
    pairings = {i: (_hato(*ep) if i != 3 else {}) for i, ep in by_id.items()}
    monkeypatch.setattr(steps, "pairing", lambda lang, job: pairings[job["id"]])
    monkeypatch.setattr(steps, "subtitle", lambda lang, job: by_id[job["id"]][1])
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: (fit_check.TIMED, "hato", None, 0.0))
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    jobs = [{"id": i} for i in sorted(by_id)]
    steps.listen_ahead("ja", jobs)
    assert not steps._ahead.busy(), "before the first fit: no Anki Miner known to hear with"
    steps.fit("ja", jobs[0], None, *a[0])                # A's first: heard first, then the next in line
    steps.listen_ahead("ja", jobs[1:])
    held.gate.set()
    _settled(steps)
    assert held.heard == ["A - 01.mkv", "B - 01.mkv", "C - 01.mkv"]
    steps.listen_ahead("ja", jobs[1:])
    _settled(steps)
    assert len(held.heard) == 3, "each job looked at once a run"


@pytest.mark.parametrize("said", [{"connect_trust_timing": True}, {runner.EVERY_EPISODE: True}])
def test_nothing_is_heard_ahead_when_you_trust_the_timing_or_every_episode_is_heard_first(
        tmp_path, steps, monkeypatch, held, said):
    (video, sub), = _season(tmp_path, "a", ["A - 01.mkv"])
    monkeypatch.setattr(steps, "pairing", lambda lang, job: _hato(video, sub))
    monkeypatch.setattr(steps, "subtitle", lambda lang, job: sub)
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    steps._heard_with["ja"] = ("AnkiMiner.exe", "surasura")
    monkeypatch.setattr(steps, "_settings", lambda lang: said)
    steps.listen_ahead("ja", [{"id": 1}])
    assert not steps._ahead.busy() and held.heard == []


def test_the_runs_end_ends_the_check_beside_it_and_drops_the_rest():
    import threading
    import time
    from app.connect import stopping
    ahead, ran, started = runner._Ahead(), [], threading.Event()

    def long_look_up():                     # as `anki_miner.api` waits on a look-up: a slice at a time
        started.set()
        while not stopping.pressed():
            time.sleep(0.01)
        raise stopping.Stopped()
    assert ahead.want("a", long_look_up)
    assert not ahead.want("a", long_look_up), "queued or running: once"
    ahead.want("b", lambda: ran.append("b"))
    assert started.wait(5)
    at = time.monotonic()
    ahead.close(5)
    assert time.monotonic() - at < 2 and not ahead.busy()
    assert ran == [] and not ahead.want("c", lambda: ran.append("c")), "nothing after the end"


def test_a_check_that_fails_is_logged_and_the_next_one_runs_the_fits_own_first(caplog):
    import threading
    ahead, ran, gate, done = runner._Ahead(), [], threading.Event(), threading.Event()

    def broken():
        assert gate.wait(5)
        raise RuntimeError("a bug")
    ahead.want("a", broken)
    ahead.want("b", lambda: ran.append("b") or done.set())
    ahead.want("first", lambda: ran.append("first"), first=True)
    gate.set()
    assert done.wait(5)
    assert ran == ["first", "b"] and "stopped on an error" in caplog.text
    ahead.close(5)


def test_the_run_ends_the_check_beside_the_mining_whatever_else_it_did(monkeypatch):
    from types import SimpleNamespace
    ended = []
    monkeypatch.setattr(runner, "_release_check", lambda loaded: None)
    steps = SimpleNamespace(lower_priority=lambda: None, settle=lambda: None, end_listening=lambda: ended.append(1))
    runner.run({}, [], steps=steps, ledger=SimpleNamespace(close=lambda: None))
    assert ended == [1]


SEASON = 4


@pytest.mark.parametrize("every, slowest", [(False, 0.5), (True, None)])
def test_a_season_on_the_fake_anki_miner_never_waits_and_a_dub_holds_the_rest_of_its_release(
        tmp_path, fake_miner, monkeypatch, every, slowest):
    # the structure of a season's mining (the fake Anki Miner hears as the plan says: every line in English, a dub),
    # its check held 0.6 s a call: before (every episode first, #498) the fit waits for it each episode; after, never
    import time
    season = _season(tmp_path, "show", [f"[Group] Show - {n:02} (1080p).mkv" for n in range(1, SEASON + 1)])
    places = lineup.samples(lineup.heard_lines(season[0][1], "ja", video=True))
    fake_miner.plan(speech=SPEECH, heard={p[2][:6]: "you're getting a tiny fraction of what it can do" for p in places},
                    slow={"transcribe": 0.6})
    s = runner.Steps({})
    monkeypatch.setattr(anki_miner, "_SPEECH", {})
    monkeypatch.setattr(s, "_miner_profile", lambda lang, job: (fake_miner.path, None))
    monkeypatch.setattr(s, "on_battery", lambda: False)
    monkeypatch.setattr(s, "_settings", lambda lang: {runner.EVERY_EPISODE: every})
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: (fit_check.TIMED, "hato", None, 0.0))
    waited, answers = [], []
    try:
        for job, (video, sub) in enumerate(season, 1):
            at = time.monotonic()
            answers.append(s.fit("ja", {"id": job}, None, video, sub)[0])
            waited.append(time.monotonic() - at)
            _settled(s, 30)                         # its mining: the check beside it ends meanwhile
    finally:
        s.end_listening()
    if every:
        assert answers == [fit_check.NOT_TIMED] * SEASON and min(waited) >= 0.6
    else:
        assert answers == [fit_check.TIMED] + [fit_check.NOT_TIMED] * (SEASON - 1), "the first mines; the rest held"
        assert max(waited) < slowest, waited
    assert fake_miner.commands().count("media") == (SEASON if every else 1)


# --------------------------------------------------------------------------- #
# Michi-T1's review (register R1–R8): what the first pass found
def test_verdicts_kept_beside_the_mining_while_the_fit_reads_them_are_never_lost(tmp_path):
    # R1: Windows refuses `os.replace` onto a file another thread has open: the reads and writes take turns
    import threading
    season = _season(tmp_path, "show", [f"Show - {n:02}.mkv" for n in range(1, 41)])
    keys = [lineup.release_key(str(tmp_path / f"r{n}" / "Show - 01.mkv")) for n in range(40)]
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            lineup.release_kept(keys[0])
            lineup.spot_kept(keys[1])
    t = threading.Thread(target=reader)
    t.start()
    try:
        for key, (video, sub) in zip(keys, season):
            lineup.keep_release(key, lineup.MATCHED, video, sub)
    finally:
        stop.set()
        t.join()
    assert all(lineup.release_kept(k) == lineup.MATCHED for k in keys), "every verdict written"
    assert not [n for n in os.listdir(lineup.root()) if n.endswith(".tmp")], "no write left half-done"


def test_odd_names_and_a_damaged_record_never_fail_a_fit(tmp_path):
    # R5–R7: a name NTFS holds but UTF-8 can't (a lone surrogate), no video at all, a record that isn't one
    odd = str(tmp_path / "show" / "Show - 01 \udc80.mkv")
    assert lineup.release_key(odd) and lineup.release_key(None) is None and lineup.release_key("") is None
    lineup.keep_release(lineup.release_key(odd), lineup.MATCHED, odd, str(tmp_path / "none.srt"))   # never raises
    lineup._keep_spot("k", lineup.MATCHED, [])
    import json
    path = os.path.join(lineup.root(), lineup.SPOT)
    with open(path, encoding="utf-8") as f:
        kept = json.load(f)
    kept.update(junk="not a record", stampless={"verdict": lineup.NOT_MATCHED, "video": "x\0y", "stamp": [1, 2]})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kept, f)
    assert lineup.spot_kept("junk") is None and lineup.release_kept("junk") is None
    assert lineup.release_kept("stampless") is None


def test_not_now_asks_anki_miner_nothing_for_a_release(tmp_path, steps, monkeypatch, held):
    # R2: *Not now* (or the model's download running): no look-up in line, nothing queued
    (video, sub), = _season(tmp_path, "show", ["Show - 01.mkv"])
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: TSUBASA)
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    monkeypatch.setattr(steps, "_miner_profile", lambda lang, job: pytest.fail("Anki Miner asked"))
    monkeypatch.setattr(lineup, "answer", lambda: "no")
    assert steps.fit("ja", {"id": 1}, None, video, sub) == TSUBASA
    assert not steps._ahead.busy()


def test_your_mine_now_on_battery_is_heard_though_its_release_was_queued_ahead_unasked(
        tmp_path, steps, monkeypatch, held):
    # R3: the look-ahead queued the release with no job; your asked episode's fit puts its own in its place
    import threading
    (video, sub), = _season(tmp_path, "show", ["Show - 01.mkv"])
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: (fit_check.TIMED, "hato", None, 0.0))
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    monkeypatch.setattr(steps, "on_battery", lambda: True)
    gate = threading.Event()
    steps._ahead.want("busy", lambda: gate.wait(10))            # something else heard first
    steps._heard_with["ja"] = ("AnkiMiner.exe", "surasura")
    steps._hear_release("ja", None, video, sub, 0.0)              # as `_peek` queues it
    assert steps.fit("ja", {"id": 1, "asked_at": "2026-11-17T10:00:00Z"}, None, video, sub)[0] == fit_check.TIMED
    gate.set()
    held.gate.set()
    _settled(steps)
    assert held.heard == ["Show - 01.mkv"], "heard on battery: you asked for it"


def test_nothing_is_looked_ahead_on_battery_and_a_busy_store_is_looked_at_again(tmp_path, steps, monkeypatch, held):
    # R4: jobs the look-ahead couldn't read (the store busy), or skipped on battery, are looked at next time
    (video, sub), = _season(tmp_path, "a", ["A - 01.mkv"])
    monkeypatch.setattr(steps, "subtitle", lambda lang, job: sub)
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    steps._heard_with["ja"] = ("AnkiMiner.exe", "surasura")
    monkeypatch.setattr(steps, "on_battery", lambda: True)
    steps.listen_ahead("ja", [{"id": 1}])
    _settled(steps)
    assert held.heard == [] and 1 not in steps._peeked
    monkeypatch.setattr(steps, "on_battery", lambda: False)

    def busy(lang, job):
        raise runner.Wait(runner.LIBRARY_BUSY)
    monkeypatch.setattr(steps, "pairing", busy)
    steps.listen_ahead("ja", [{"id": 1}])
    _settled(steps)
    assert held.heard == [] and 1 not in steps._peeked
    monkeypatch.setattr(steps, "pairing", lambda lang, job: _hato(video, sub))
    held.gate.set()
    steps.listen_ahead("ja", [{"id": 1}])
    _settled(steps)
    assert held.heard == ["A - 01.mkv"]


def test_a_no_model_said_only_because_anki_miner_was_busy_is_asked_again_within_a_minute(monkeypatch):
    # R8: beside a mine, setting the other model size is refused BUSY: that no is never kept for 15 minutes
    clock, asked = [1000.0], []
    monkeypatch.setattr(anki_miner, "_SPEECH", {})
    monkeypatch.setattr(anki_miner.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(anki_miner, "check", lambda *a, **k: asked.append("check") or {"items": []})

    def busy(*a, **k):
        raise anki_miner.AnkiMinerError("busy", "Anki Miner is mining")
    monkeypatch.setattr(anki_miner, "settings_import", busy)
    assert anki_miner.speech_ready("AnkiMiner.exe", "ja", "surasura", "f") is False
    clock[0] += 30
    anki_miner.speech_ready("AnkiMiner.exe", "ja", "surasura", "f")
    assert asked == ["check"], "kept a little while"
    clock[0] += anki_miner.SPEECH_BUSY_S
    anki_miner.speech_ready("AnkiMiner.exe", "ja", "surasura", "f")
    assert asked == ["check", "check"], "asked again within a minute, not 15"

    def refused(*a, **k):
        raise anki_miner.AnkiMinerError("refused", "the window's profile")
    monkeypatch.setattr(anki_miner, "settings_import", refused)
    monkeypatch.setattr(anki_miner, "_SPEECH", {})
    anki_miner.speech_ready("AnkiMiner.exe", "ja", "surasura", "f")
    clock[0] += anki_miner.SPEECH_BUSY_S + 1
    anki_miner.speech_ready("AnkiMiner.exe", "ja", "surasura", "f")
    assert asked.count("check") == 3, "any other no is kept 15 minutes, as before"


def test_the_videos_own_track_is_heard_ahead_too_and_a_transcript_of_its_own_audio_never(
        tmp_path, steps, monkeypatch, held):
    # the track Surasura copied out of the video (Michi-ST) is timed to it: shift 0.0, heard ahead; one Anki Miner made
    # from the video's own audio (Michi-NS) is never heard (#498: `audio`)
    import hashlib
    first, = _season(tmp_path, "f", ["F - 01.mkv"])
    track, = _season(tmp_path, "t", ["T - 01.mkv"])
    made, = _season(tmp_path, "m", ["M - 01.mkv"])

    def own(sub, verdict):
        with open(sub, "rb") as f:
            return {"producer": fit_check.SOURCE, "verdict": verdict, "subtitle_sha256": hashlib.sha256(f.read())
                    .hexdigest()}
    by_id = {1: first, 2: track, 3: made}
    pairings = {1: _hato(*first), 2: own(track[1], "extracted"), 3: own(made[1], "transcribed")}
    monkeypatch.setattr(steps, "pairing", lambda lang, job: pairings[job["id"]])
    monkeypatch.setattr(steps, "subtitle", lambda lang, job: by_id[job["id"]][1])
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: True)
    monkeypatch.setattr(fit_check, "fit", lambda *a, **k: (fit_check.TIMED, "hato", None, 0.0))
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    steps.fit("ja", {"id": 1}, None, *first)
    steps.listen_ahead("ja", [{"id": 2}, {"id": 3}])
    held.gate.set()
    _settled(steps)
    assert held.heard == ["F - 01.mkv", "T - 01.mkv"]


def test_the_loop_hands_the_next_in_line_to_the_look_ahead_before_each_job_and_ends_it_after(tmp_path):
    from app.connect.ledger import Ledger
    from tests.connect.fake_steps import FakeSteps

    class Steps(FakeSteps):
        def listen_ahead(self, lang, jobs):
            self.log.append(("ahead", [j["item_id"] for j in jobs]))

        def end_listening(self):
            self.log.append(("ended",))
    line = [101, 102, 103]
    words = {str(i): [(f"単語{i}", f"タンゴ{i}")] for i in line}
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        steps = Steps(str(tmp_path), {"line": {"ja": line}, "queue": {"ja": line}, "words": words})
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    seen = [e[:2] for e in steps.log if e[0] in ("ahead", "mine", "ended")]
    assert seen == [("ahead", [101, 102, 103]), ("mine", 101), ("ahead", [102, 103]), ("mine", 102),
                    ("ahead", [103]), ("mine", 103), ("ended",)], seen
