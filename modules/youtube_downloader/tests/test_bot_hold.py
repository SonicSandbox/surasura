# SPDX-License-Identifier: GPL-3.0-or-later
"""Yt-B (Sonic 2026-11-12: "will this hit from my own network and then will I have issues in the future with too many
requests?"): the downloader asks YouTube one call at a time, with yt-dlp's own waits between a playlist's videos, and
the first "are you a bot" (or HTTP 429) holds every YouTube call for a day — said once, with when it tries again —
while bilibili.tv goes on.

What a wrong answer costs a learner: their own address asked again and again after YouTube turned it away (the block
lasts longer), a playlist read with no wait at all, or an age-restricted video taken for the bot check (a day of
nothing, for a video's own age check). yt-dlp is faked at `ytdlp_manager.run` with its own recorded words, so the real
`_run_ytdlp` (the turn, the hold) runs; never the network.
"""
import json
import os
import time

import pytest

from app import youtube_hold
from modules.youtube_downloader import downloader as core
from modules.youtube_downloader import ytdlp_manager

VIDEO = "https://www.youtube.com/watch?v=lecture0001"
OTHER = "https://www.youtube.com/watch?v=lecture0002"
PLAYLIST = "https://www.youtube.com/playlist?list=PLsamplepodcast0000000000000000001"
BILIBILI = "https://www.bilibili.tv/en/video/2041234567"
BOT = ("ERROR: [youtube] lecture0001: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies "
       "for the authentication.")
AGE = ("ERROR: [youtube] lecture0001: Sign in to confirm your age. This video may be inappropriate for some users. "
       "Use --cookies-from-browser or --cookies for the authentication.")
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n朝の散歩のすすめ\n\n00:00:03.000 --> 00:00:05.000\nまずは近所を歩いてみよう\n"


class Res:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


@pytest.fixture
def ytdlp(monkeypatch):
    """yt-dlp faked one level below `_run_ytdlp`: each call's args recorded, its answer from `box["answer"](args)`."""
    monkeypatch.setattr(youtube_hold, "GAP_S", 0.0)
    box = {"calls": [], "answer": lambda args: Res()}
    monkeypatch.setattr(ytdlp_manager, "get_ytdlp_path", lambda: "yt-dlp.exe")

    def run(cmd, timeout, should_stop=None, tick=None, stop_on=None):
        box["calls"].append(cmd[1:])
        box.setdefault("timeouts", []).append(timeout)
        box.setdefault("stop_on", []).append(stop_on)
        return box["answer"](cmd[1:])
    monkeypatch.setattr(ytdlp_manager, "run", run)
    return box


def _video(args, vid="lecture0001", title="朝の散歩のすすめ"):
    tmp = os.path.dirname(args[args.index("-o") + 1])
    with open(os.path.join(tmp, f"{vid}.info.json"), "w", encoding="utf-8") as f:
        json.dump({"id": vid, "title": title, "channel": "hanashi radio", "webpage_url": f"https://youtu.be/{vid}",
                   "subtitles": {"ja": [{"ext": "vtt"}]}, "automatic_captions": {}}, f, ensure_ascii=False)
    with open(os.path.join(tmp, f"{vid}.ja.vtt"), "w", encoding="utf-8") as f:
        f.write(VTT)
    return Res()


def _probe_answer(args):
    if "-J" in args:
        url = args[-1]
        return Res(stdout=json.dumps({"id": core.video_id(url) or "2041234567", "title": "朝の散歩のすすめ",
                                      "channel": "hanashi radio", "webpage_url": url}))
    return _video(args)


# --- the bug: an age check was the bot check ---------------------------------------------------------------------- #
def test_an_age_restricted_video_is_said_as_one_and_holds_nothing(ytdlp, tmp_path):
    # why: the marker "sign in to confirm" matched "Sign in to confirm your age": a day of nothing for one video
    assert core.plain_reason(AGE) == "the video is age-restricted: YouTube needs a sign-in"
    ytdlp["answer"] = lambda args: Res(stderr=AGE)
    log, summary = [], {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([VIDEO], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                          log.append, summary)
    assert log == ["  ! video lecture0001: the video is age-restricted: YouTube needs a sign-in"]
    assert youtube_hold.held() is None


# --- the hold -------------------------------------------------------------------------------------------------------- #
def test_a_refusal_holds_every_youtube_call_and_says_when_it_tries_again(ytdlp, tmp_path):
    """The first video's bot check: said with the hold's end; the next run asks YouTube nothing at all."""
    ytdlp["answer"] = lambda args: Res(stderr=BOT) if "-J" not in args else _probe_answer(args)
    out = tmp_path / "Processed"
    log = []
    core.extract([VIDEO], str(out), log=log.append)
    until = youtube_hold.held()
    assert until and abs(until - time.time() - youtube_hold.HOLD_S) < 60
    said = youtube_hold.words(until)
    assert f"  ! video lecture0001: {said}" in log and " at " in said
    assert sum(said in line for line in log) == 1, "said once"

    asked = len(ytdlp["calls"])
    log2 = []
    summary = core.extract([OTHER, PLAYLIST], str(out), log=log2.append)
    assert len(ytdlp["calls"]) == asked, "no YouTube call while the hold runs"
    assert log2.count(f"  ! {said}") == 1, "said once a run, never once per link"
    assert summary["held"] and not summary["errors"]


def test_a_bilibili_tv_link_is_never_held(ytdlp, tmp_path):
    # why: the hold is YouTube's answer to this computer; bilibili.tv is another site
    youtube_hold.hold()
    ytdlp["answer"] = _probe_answer
    log = []
    core.extract([VIDEO, BILIBILI], str(tmp_path / "Processed"), log=log.append)
    assert [c[-1] for c in ytdlp["calls"] if "-J" in c] == [BILIBILI]
    assert not any("--sleep-requests" in c for c in ytdlp["calls"]), "no YouTube pacing on bilibili.tv's calls"


def test_a_hold_begun_elsewhere_while_waiting_is_met_before_the_call(ytdlp, tmp_path, monkeypatch):
    """Connect's fetch refused while the window waited its turn: the window's call is never made."""
    real = youtube_hold.turn

    def turn(should_stop=None, verb="YouTube download", **kw):
        youtube_hold.hold()                     # (another program's refusal, just before this one's turn)
        return real(should_stop, verb, **kw)
    monkeypatch.setattr(youtube_hold, "turn", turn)
    log, summary = [], {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([VIDEO], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                          log.append, summary)
    assert ytdlp["calls"] == []
    assert log == [f"  ! {youtube_hold.words(youtube_hold.held())}"] and summary["errors"] == 0


def test_the_held_line_is_a_passing_problem_so_a_playlists_rest_is_kept():
    youtube_hold.hold()
    assert core.transient("could not read x: " + youtube_hold.words(youtube_hold.held()))


# --- pacing ---------------------------------------------------------------------------------------------------------- #
def test_a_playlist_waits_between_its_videos_and_a_single_video_only_between_requests(ytdlp, tmp_path):
    # why: yt-dlp's own advice (its `-t sleep` preset): ~5 s between videos keeps a guest under ~300 videos an hour
    ytdlp["answer"] = _video
    summary = {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([PLAYLIST], str(tmp_path / "a"), core.LANGS["Japanese"], "Japanese", False, True,
                          lambda _l: None, summary, counts={PLAYLIST: 12})
    core._download_bucket([VIDEO], str(tmp_path / "b"), core.LANGS["Japanese"], "Japanese", False, True,
                          lambda _l: None, summary)
    many, one = ytdlp["calls"]
    assert many[many.index("--sleep-subtitles") + 1] == "5" and many[many.index("--sleep-requests") + 1] == "0.75"
    assert "--sleep-subtitles" not in one and "--sleep-requests" in one, "setup's first video never waits 5 s"
    assert summary["written"] == 2


def test_a_stop_while_waiting_for_the_turn_is_a_stop_never_an_error(ytdlp, tmp_path):
    # why: another program's half-hour playlist never holds the window's Cancel
    from app import locks
    other = locks.take(youtube_hold.LOCK, "Connect's video", owner=object())    # (as another program)
    try:
        log, summary = [], {"written": 0, "no_transcript": 0, "errors": 0}
        with core.stopping(lambda: True):
            core._download_bucket([VIDEO], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                                  log.append, summary)
        assert log == ["Stopped."] and summary["errors"] == 0 and ytdlp["calls"] == []
    finally:
        other.release()
    ytdlp["answer"] = _video
    core._download_bucket([VIDEO], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                          log.append, summary)
    assert summary["written"] == 1, "the turn let go: the next call goes"


# --- the cue backfill ------------------------------------------------------------------------------------------------ #
def _transcripts(root, n):
    folder = os.path.join(root, "Processed")
    os.makedirs(folder, exist_ok=True)
    for i in range(n):
        with open(os.path.join(folder, f"hanashi radio - 朝の散歩 {i} [lecture000{i}].txt"), "w",
                  encoding="utf-8") as f:
            f.write("朝の散歩のすすめ\nhanashi radio | 2026-10-14 | 12:34\n\n今日は写真の話をします。\n")


def test_the_backfill_stops_at_a_refusal_and_never_starts_while_held(ytdlp, tmp_path):
    _transcripts(str(tmp_path), 3)
    ytdlp["answer"] = lambda args: Res(stderr=BOT)
    log = []
    summary = core.backfill_cues(str(tmp_path), log=log.append, sleep=lambda s: None)
    assert len(ytdlp["calls"]) == 1 and summary["stopped"] and summary["remaining"] == 3
    assert youtube_hold.words(youtube_hold.held()) in log[-1]
    log = []
    summary = core.backfill_cues(str(tmp_path), log=log.append, sleep=lambda s: None)
    assert len(ytdlp["calls"]) == 1, "nothing asked while the hold runs"
    assert summary["stopped"] and summary["remaining"] == 3


def test_a_bilibili_tv_rate_limit_is_never_said_as_youtubes_hold():
    # why (review 7): another site's refusal is its own
    youtube_hold.hold()
    message = "ERROR: [BiliIntl] 2041234567: HTTP Error 429: Too Many Requests"
    assert core.plain_reason(message, youtube=False) == core.RATE_LIMITED
    assert youtube_hold.is_words(core.plain_reason(message))


def test_the_stall_clock_starts_once_the_turn_came(tmp_path):
    # why (review 1): six minutes waiting behind Connect's video must not read as YouTube not answering
    now = [0.0]
    run = tmp_path / "run"                                  # (the call's own folder: empty, as yt-dlp's starts)
    run.mkdir()
    tick = core._watch(str(run), 3, lambda _l: None, clock=lambda: now[0])
    now[0] = core.FIRST_S + 60
    tick.restart()
    now[0] += core.FIRST_S - 1
    tick()                                                  # under FIRST_S since its own start: no stall
    now[0] += 1
    with pytest.raises(core.Stalled):
        tick()


def test_the_real_call_restarts_the_tick_inside_its_turn(ytdlp, tmp_path):
    restarted = []

    def tick():
        pass
    tick.restart = lambda: restarted.append(len(ytdlp["calls"]))
    core._run_ytdlp(["--skip-download", VIDEO], timeout=5, tick=tick)
    assert restarted == [0] and len(ytdlp["calls"]) == 1, "restarted once its turn came, before the call"


def test_a_refusal_ends_yt_dlp_at_once_instead_of_asking_for_every_video_left():
    # why (review 5): with --ignore-errors yt-dlp would ask YouTube for each video left after the bot check
    import subprocess
    import sys
    child = ("import sys, time; sys.stderr.write(%r + '\\n'); sys.stderr.flush(); time.sleep(60)" % BOT)
    started = time.monotonic()
    res = ytdlp_manager.run([sys.executable, "-c", child], 120, stop_on=youtube_hold.refused)
    assert time.monotonic() - started < 15, "ended at the refusal"
    assert youtube_hold.refused(res.stderr)
    done = ytdlp_manager.run([sys.executable, "-c", "import sys; print('ok'); sys.stderr.write('fine')"], 60,
                             stop_on=youtube_hold.refused)
    assert done.stdout.strip() == "ok" and done.stderr == "fine" and done.returncode == 0
    assert isinstance(done, subprocess.CompletedProcess)


def test_preview_says_the_hold_never_no_captions(tmp_path):
    # why (review 4): "No transcript found" would send the learner looking for captions that are there
    from modules.youtube_downloader import preview
    youtube_hold.hold()
    txts, why = preview.fetch_here(VIDEO, VIDEO, "ja", str(tmp_path), extract=lambda *a, **k: None,
                                   ensure=lambda log: True)
    assert txts == [] and why == youtube_hold.words(youtube_hold.held())


# --- round 2 ------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("args, youtube", [
    (["-J", VIDEO], True), (["-J", "https://youtu.be/lecture0001"], True),
    (["-J", "https://music.youtube.com/watch?v=lecture0001"], True),
    (["-J", "https://www.youtube-nocookie.com/embed/lecture0001"], True),
    (["-J", "https://www.youtube.com:443/watch?v=lecture0001"], True), (["-J", "ytsearch5:朝の散歩"], True),
    (["-J", BILIBILI], False),
    (["-o", "C:/Users/x/youtube.com/%(id)s.%(ext)s", "--sub-format", "vtt/best", BILIBILI], False),
], ids=["watch", "short", "music", "nocookie", "port", "search", "bilibili", "a-path-is-no-link"])
def test_a_youtube_call_is_told_by_its_own_links(args, youtube):
    assert bool(core._reaches_youtube(args)) is youtube


def test_a_wait_for_the_turn_is_said_with_who_holds_it(ytdlp, tmp_path):
    # why (review r2 #1): behind Connect's video the window would look hung, saying nothing
    import threading
    from app import locks
    ytdlp["answer"] = _video
    other = locks.take(youtube_hold.LOCK, "Connect's video", owner=object())    # (as another program)
    threading.Timer(0.8, other.release).start()
    log, summary = [], {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([VIDEO], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                          log.append, summary)
    assert log.count("  … waiting for Connect's video to finish first (one YouTube download at a time)") == 1
    assert summary["written"] == 1


def test_a_long_playlists_time_grows_with_yt_dlps_waits(ytdlp, tmp_path):
    # why (review r2 #4): ~8-13 s a video with the waits; 30 minutes would end a 200-video playlist half-way
    ytdlp["answer"] = _video
    summary = {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([PLAYLIST], str(tmp_path / "a"), core.LANGS["Japanese"], "Japanese", False, True,
                          lambda _l: None, summary, counts={PLAYLIST: 300})
    core._download_bucket([VIDEO], str(tmp_path / "b"), core.LANGS["Japanese"], "Japanese", False, True,
                          lambda _l: None, summary)
    assert ytdlp["timeouts"] == [600 + 15 * 300, 1800]


def test_a_character_split_between_two_looks_is_never_garbled():
    # why (review r2 #7): stderr read while the child writes it; a Japanese title's character can straddle two looks
    import sys
    child = ("import sys, time; e = sys.stderr.buffer; e.write('朝'.encode()[:2]); e.flush(); time.sleep(0.7); "
             "e.write('朝'.encode()[2:] + b'\\n'); e.flush()")
    res = ytdlp_manager.run([sys.executable, "-c", child], 60, stop_on=youtube_hold.refused)
    assert res.stderr == "朝\n"


def test_only_a_youtube_call_is_ended_at_its_first_refusal(ytdlp):
    # why (mutant D3): without stop_on, --ignore-errors asks YouTube for every video left after the bot check
    core._run_ytdlp(["--skip-download", VIDEO], timeout=5)
    core._run_ytdlp(["--skip-download", BILIBILI], timeout=5)
    assert ytdlp["stop_on"] == [youtube_hold.refused, None]


def test_a_held_run_never_waits_for_the_turn_just_to_learn_it_is_held(ytdlp, tmp_path, monkeypatch):
    # why (mutant D10): behind another program's half-hour call, a held run would wait all that time for nothing
    youtube_hold.hold()
    monkeypatch.setattr(youtube_hold, "turn", lambda *a, **k: pytest.fail("asked for the turn while held"))
    log, summary = [], {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([VIDEO], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                          log.append, summary)
    assert log == [f"  ! {youtube_hold.words(youtube_hold.held())}"] and ytdlp["calls"] == []


def test_a_held_backfill_never_waits_for_the_turn(ytdlp, tmp_path, monkeypatch):
    # why (mutant D15): as a held download — no turn asked for, nothing fetched, said once
    _transcripts(str(tmp_path), 2)
    youtube_hold.hold()
    monkeypatch.setattr(youtube_hold, "turn", lambda *a, **k: pytest.fail("asked for the turn while held"))
    log = []
    summary = core.backfill_cues(str(tmp_path), log=log.append, sleep=lambda s: None)
    assert summary["stopped"] and summary["remaining"] == 2 and ytdlp["calls"] == []
