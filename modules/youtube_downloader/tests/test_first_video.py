# SPDX-License-Identifier: GPL-3.0-or-later
"""Alpha 8 (Sonic's try, 2026-10-31): setup's *YouTube* brings in each line's first video, and a download never looks
hung — every video read is said, a download that writes nothing for STALL_S seconds is ended and said, and a video
yt-dlp refuses (YouTube's bot check, a private video) is said instead of vanishing. All hermetic: yt-dlp is faked at
`_run_ytdlp`, except where a real child proves the tick's stop."""
import json
import os
import subprocess
import sys

import pytest

from modules.youtube_downloader import downloader as core
from modules.youtube_downloader import downloader_view as view
from modules.youtube_downloader import ytdlp_manager

VIDEO = "https://www.youtube.com/watch?v=lecture0001"
IN_LIST = "https://www.youtube.com/watch?v=podcast0001&list=PLsamplepodcast0000000000000000001"
PLAYLIST = "https://www.youtube.com/playlist?list=PLsamplepodcast0000000000000000001"
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n朝の散歩のすすめ\n\n00:00:03.000 --> 00:00:05.000\nまずは近所を歩いてみよう\n"
BOT = ("ERROR: [youtube] lecture0001: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies "
       "for the authentication.")


class Res:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


def _write_video(tmp, vid, title):
    with open(os.path.join(tmp, f"{vid}.info.json"), "w", encoding="utf-8") as f:
        json.dump({"id": vid, "title": title, "channel": "hanashi radio", "webpage_url": f"https://youtu.be/{vid}",
                   "subtitles": {"ja": [{"ext": "vtt"}]}, "automatic_captions": {}}, f, ensure_ascii=False)
    with open(os.path.join(tmp, f"{vid}.ja.vtt"), "w", encoding="utf-8") as f:
        f.write(VTT)


def _tmp_of(args):
    return os.path.dirname(args[args.index("-o") + 1])


# --- the tick: a real child ended when it raises ------------------------------------------------------------------ #
def test_a_tick_that_raises_ends_the_child_and_is_raised(monkeypatch):
    """`ytdlp_manager.run`'s tick raises (a stall): the child is ended — never left running — and the error raised.
    (Raised inside the poll's own except: the sibling handler never sees it, so the tick's own guard must end it.)"""
    made = []
    real = subprocess.Popen

    def popen(*a, **kw):
        made.append(real(*a, **kw))
        return made[-1]
    monkeypatch.setattr(subprocess, "Popen", popen)
    ticks = []

    def tick():
        ticks.append(1)
        if len(ticks) >= 3:
            raise core.Stalled()
    with pytest.raises(core.Stalled):
        ytdlp_manager.run([sys.executable, "-c", "import time; time.sleep(60)"], 120, tick=tick)
    assert made and made[0].poll() is not None, "the child was ended"


# --- the progress and the stall ----------------------------------------------------------------------------------- #
def test_each_video_read_is_said_and_nothing_new_for_stall_s_stalls(tmp_path):
    now = [0.0]
    lines = []
    tick = core._watch(str(tmp_path), 3, lines.append, clock=lambda: now[0])
    tick()
    assert lines == []                                             # nothing read yet: nothing said
    _write_video(str(tmp_path), "podcast0001", "【Japanese Podcast #43】")
    now[0] = 5.0
    tick()
    assert lines == ["  … 1 of 3 videos read"]
    now[0] = 5.0 + core.STALL_S - 1
    tick()                                                         # quiet, but not for long enough
    now[0] = 5.0 + core.STALL_S
    with pytest.raises(core.Stalled):
        tick()


def test_one_video_says_no_count(tmp_path):
    lines = []
    tick = core._watch(str(tmp_path), 1, lines.append, clock=lambda: 0.0)
    _write_video(str(tmp_path), "lecture0001", "朝の散歩のすすめ")
    tick()
    assert lines == []


def test_a_stalled_download_is_said_and_what_came_in_is_kept(tmp_path, monkeypatch):
    """The playlist's call writes one video, then stalls: the run says it stopped and why, in plain words, and the
    video that came in is written."""
    def fake(args, timeout=None, tick=None, **_kw):
        _write_video(_tmp_of(args), "podcast0001", "【Japanese Podcast #43】日本語リスニング")
        raise core.Stalled()
    monkeypatch.setattr(core, "_run_ytdlp", fake)
    log, summary = [], {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([PLAYLIST], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                          log.append, summary, counts={PLAYLIST: 44})
    assert f"  ! {core.STALLED.format(minutes=core.STALL_S // 60)}" in log
    assert summary["written"] == 1 and summary["errors"] == 1
    assert [n for n in os.listdir(tmp_path / "out") if n.endswith(".txt")]


def test_a_video_youtube_refuses_is_said_never_dropped(tmp_path, monkeypatch):
    """Sonic's single video came back from YouTube's bot check with nothing written: the run said 0 errors. Now its
    refusal is said, in plain words, and counted."""
    monkeypatch.setattr(core, "_run_ytdlp", lambda args, timeout=None, tick=None, **_k: Res(stderr=BOT))
    log, summary = [], {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([VIDEO], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                          log.append, summary)
    assert summary == {"written": 0, "no_transcript": 0, "errors": 1}
    assert log == [f"  ! video lecture0001: {core.RATE_LIMITED}"]


# --- setup's first video ------------------------------------------------------------------------------------------ #
def test_first_only_reads_each_links_own_video_or_its_playlists_first_and_turns_others_away(tmp_path, monkeypatch):
    probed = []
    infos = {VIDEO: {"id": "lecture0001", "title": "朝の散歩のすすめ", "channel": "Ch A"},
             IN_LIST: {"id": "podcast0001", "title": "【Japanese Podcast #43】", "channel": "hanashi radio"},
             PLAYLIST: {"_type": "playlist", "title": "Everyday Japanese Podcast", "channel": "hanashi radio",
                        "entries": [{"_type": "url", "id": "podcast0001", "url": "https://www.youtube.com/watch?v=podcast0001",
                                     "channel": "hanashi radio"},
                                    {"_type": "url", "id": "podcast0002", "url": "https://www.youtube.com/watch?v=podcast0002"}]}}

    def probe(url, log, single=False, **_kw):
        probed.append((url, single))
        return infos[PLAYLIST] if url == IN_LIST and not single else infos[url]
    buckets = []
    monkeypatch.setattr(core, "_probe", probe)
    monkeypatch.setattr(core, "_download_bucket", lambda urls, target, *a, **kw: buckets.append((urls, target)))
    log = []
    summary = core.extract([VIDEO, "https://example.com/video/1", IN_LIST, PLAYLIST], str(tmp_path), lang="Japanese",
                           log=log.append, first_only=True)
    # Mado-Q: a video's link in a playlist is read as its list (its place known), once, when the list holds it
    assert probed == [(VIDEO, True), (IN_LIST, False), (PLAYLIST, True)], "a video's own link: one read each"
    assert "  ! not a YouTube or bilibili.tv link: https://example.com/video/1" in log and summary["errors"] == 1
    got = sorted(u for urls, _t in buckets for u in urls)
    assert got == sorted([VIDEO] + ["https://www.youtube.com/watch?v=podcast0001"] * 2)   # one video each (X)
    assert not any("(playlist)" in t for _u, t in buckets), "no playlist folder: each is one video"


def test_the_smallest_download_goes_first(tmp_path, monkeypatch):
    """The window's run (not first-only): a single video never waits behind a 44-video playlist."""
    infos = {VIDEO: {"id": "lecture0001", "channel": "Ch A"},
             PLAYLIST: {"_type": "playlist", "title": "Everyday Japanese Podcast", "channel": "hanashi radio",
                        "entries": [{"id": f"v{i:010d}"} for i in range(44)]}}
    monkeypatch.setattr(core, "_probe", lambda url, log: infos[url])
    order = []
    monkeypatch.setattr(core, "_download_bucket", lambda urls, *a, **kw: order.append((urls, kw.get("counts"))))
    core.extract([PLAYLIST, VIDEO], str(tmp_path), log=lambda _l: None)
    assert [urls for urls, _c in order] == [[VIDEO], [PLAYLIST]]
    assert order[0][1] == {PLAYLIST: 44, VIDEO: 1}


def test_first_video_of_an_empty_playlist_is_none():
    assert core.first_video(PLAYLIST, {"_type": "playlist", "entries": []}) is None
    assert core.first_video(VIDEO, None) is None
    assert core.first_video(VIDEO, {"id": "lecture0001"}) == (VIDEO, {"id": "lecture0001"})
    link, entry = core.first_video(PLAYLIST, {"_type": "playlist", "entries": [None, {"id": "podcast0001"}]})
    assert link == "https://www.youtube.com/watch?v=podcast0001" and entry["_type"] == "url"


# --- plain words ---------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("message, plain", [
    ("ERROR: [youtube] x: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>",
     "YouTube couldn't be reached: check your internet connection"),
    ("ERROR: [youtube] x: HTTP Error 429: Too Many Requests", core.RATE_LIMITED),
    # (A8B-6) yt-dlp's 429 comes inside "Unable to download webpage": a refusal, never "offline"
    ("ERROR: [youtube] x: Unable to download webpage: HTTP Error 429: Too Many Requests", core.RATE_LIMITED),
    (BOT, core.RATE_LIMITED),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "the video is private or no longer there"),
    ("ERROR: Unsupported URL: https://example.com/", "that isn't a YouTube or bilibili.tv link"),
    ("ERROR: [youtube] x: 動画の字幕がありません", "動画の字幕がありません"),
    ("", "nothing readable"),
])
def test_plain_reason(message, plain):
    assert core.plain_reason(message) == plain


def test_is_supported():
    assert core.is_supported(VIDEO) and core.is_supported(IN_LIST) and core.is_supported("https://youtu.be/lecture0001")
    assert core.is_supported("https://www.bilibili.tv/en/video/2009506988")
    assert not core.is_supported("https://www.bilibili.com/video/BV1xx411c7mD")
    assert not core.is_supported("https://example.com/watch?v=lecture0001") and not core.is_supported("")


def test_problems_are_the_runs_plain_lines_each_once():
    lines = ["Looking up 2 item(s) — language: Japanese …", "",
             f"  ! could not read {VIDEO}: YouTube couldn't be reached: check your internet connection",
             "  – no Japanese captions: 【Japanese Podcast #43】", "  [ok] (manual) x.txt",
             f"  ! could not read {VIDEO}: YouTube couldn't be reached: check your internet connection",
             "Could not download yt-dlp: <urlopen error timed out>", "Done — 0 written"]
    assert view.problems(lines) == [
        f"could not read {VIDEO}: YouTube couldn't be reached: check your internet connection",
        "no Japanese captions: 【Japanese Podcast #43】", view.NO_READER]


# --- the review's round (A8B-1, 8, 9, 11, 14) --------------------------------------------------------------------- #
def test_setups_download_asks_for_the_links_one_video_never_its_playlist(tmp_path, monkeypatch):
    """A8B-1: Sonic's exact try — a video and a `watch?v=…&list=…` link. The download call carries `--no-playlist`
    (yt-dlp's default for such a link is the whole list); the window's own runs never do."""
    infos = {VIDEO: {"id": "lecture0001", "channel": "Ch A"}, IN_LIST: {"id": "podcast0001", "channel": "hanashi"}}
    monkeypatch.setattr(core, "_probe", lambda url, log, single=False, **_kw: infos[url])
    calls = []
    monkeypatch.setattr(core, "_run_ytdlp", lambda args, timeout=None, tick=None, **_k: calls.append(args) or Res())
    core.extract([VIDEO, IN_LIST], str(tmp_path), lang="Japanese", log=lambda _l: None, first_only=True)
    assert calls and all("--no-playlist" in args for args in calls)
    assert sorted(u for args in calls for u in args if u.startswith("https://")) == sorted([VIDEO, IN_LIST])
    calls.clear()
    monkeypatch.setattr(core, "_probe", lambda url, log: infos[url])
    core.extract([VIDEO, IN_LIST], str(tmp_path), lang="Japanese", log=lambda _l: None)
    assert calls and not any("--no-playlist" in args for args in calls)


def test_a_gone_first_entry_is_passed_over():
    """A8B-8: a playlist whose first entry is private or deleted brings in the next one."""
    link, _e = core.first_video(PLAYLIST, {"_type": "playlist", "entries": [
        {"id": "aaaaaaaaaaa", "title": "[Private video]"}, {"id": "bbbbbbbbbbb", "title": "[Deleted video]"},
        {"id": "podcast0002", "title": "【Japanese Podcast #42】"}]})
    assert link == "https://www.youtube.com/watch?v=podcast0002"


def test_a_link_pasted_without_https_is_still_read(tmp_path, monkeypatch):
    """A8B-9: `youtube.com/watch?v=…` (yt-dlp takes it) is read, never turned away as not YouTube."""
    probed = []
    monkeypatch.setattr(core, "_probe", lambda url, log, single=False, **_kw: probed.append(url) or None)
    log = []
    core.extract(["www.youtube.com/watch?v=lecture0001"], str(tmp_path), log=log.append, first_only=True)
    assert probed == ["https://www.youtube.com/watch?v=lecture0001"] and not [l for l in log if "not a YouTube" in l]


def test_a_stop_mid_download_is_said_as_a_stop_never_an_error(tmp_path, monkeypatch):
    """A8B-11: a cancel ends the child (Stopped): the run says "Stopped." and counts no error."""
    def stopped(args, timeout=None, tick=None, **_k):
        raise ytdlp_manager.Stopped()
    monkeypatch.setattr(core, "_run_ytdlp", stopped)
    log, summary = [], {"written": 0, "no_transcript": 0, "errors": 0}
    core._download_bucket([VIDEO], str(tmp_path / "out"), core.LANGS["Japanese"], "Japanese", False, True,
                          log.append, summary)
    assert log == ["Stopped."] and summary["errors"] == 0


def test_a_call_gets_first_s_before_its_first_file(tmp_path):
    """A8B-14: a long listing before anything is written (a channel) isn't a stall until FIRST_S; after the first file,
    STALL_S of nothing is."""
    now = [0.0]
    tick = core._watch(str(tmp_path), 50, lambda _l: None, clock=lambda: now[0])
    now[0] = core.STALL_S + 1
    tick()                                                         # no file yet: still waiting
    now[0] = core.FIRST_S
    with pytest.raises(core.Stalled):
        tick()
