# SPDX-License-Identifier: GPL-3.0-or-later
"""Alpha 8 (Sonic, 2026-10-31: "it should still get the whole playlist right? just gets the first video and tells them
that it's the playlist with that video, so it can get it in the background and it doesn't make anything wait"): after
setup's first video, the rest of a playlist comes in in the background through the downloader's one path
(`core.extract`, `new_only`), its progress in the bottom bar, its files where the downloader's go (New arrivals), and
what a quit, an outage or a stall leaves goes on at the next start (the module's record, `view.rest_*`).
What a wrong answer would cost a learner: the playlist's first video read twice (two copies, or a duplicate kept out);
a quit mid-way that loses the videos already fetched (in Processed, never in the library) or the rest for good; an
offline start that drops the playlist; a Mix (an endless list of recommendations) read as a playlist; setup waiting.
yt-dlp is always faked (`_probe`, `_run_ytdlp`, `extract`); one call goes to the real `--download-archive` only in a
manual check, never here.
"""
import json
import os
import threading

import pytest

from modules.youtube_downloader import downloader as core
from modules.youtube_downloader import downloader_view as view

IN_LIST = "https://www.youtube.com/watch?v=podcast0001&list=PLsamplepodcast0000000000000000001"
PLAYLIST = "https://www.youtube.com/playlist?list=PLsamplepodcast0000000000000000001"
VIDEO = "https://www.youtube.com/watch?v=lecture0001"
IDS = ["podcast0001", "podcast0002", "podcast0003", "podcast0004"]
TITLES = ["【Japanese Podcast #43】撮った写真の話", "【Japanese Podcast #42】東京の朝", "【Japanese Podcast #41】雨の日",
          "【Japanese Podcast #40】好きな本"]


class Res:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


def _transcript(folder, i):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"hanashi radio - {TITLES[i]} [{IDS[i]}].txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{TITLES[i]}\nhanashi radio | 2026-10-14 | 12:34\n\n今日は写真の話をします。\n")
    return path


def _playlist_info(n=4):
    return {"_type": "playlist", "id": "PLsamplepodcast0000000000000000001", "title": "Everyday Japanese Podcast",
            "channel": "hanashi radio",
            "entries": [{"_type": "url", "id": IDS[i], "url": f"https://www.youtube.com/watch?v={IDS[i]}"}
                        for i in range(n)]}


# --- which links are playlists -------------------------------------------------------------------------------- #
@pytest.mark.parametrize("url, playlist", [
    (IN_LIST, PLAYLIST),                                             # Sonic's link: a video in its playlist
    (PLAYLIST, PLAYLIST),
    ("youtube.com/watch?v=podcast0001&list=PLsamplepodcast0000000000000000001&index=1", PLAYLIST),   # no https, index
    ("https://youtu.be/podcast0001?list=PLsamplepodcast0000000000000000001", PLAYLIST),
    ("https://m.youtube.com/watch?list=PLsamplepodcast0000000000000000001&v=podcast0001", PLAYLIST),
    (VIDEO, None),                                                   # a single video: nothing after it
    ("https://www.youtube.com/watch?v=lecture0001&list=RDlecture0001&start_radio=1", None),   # a Mix: endless
    ("https://www.youtube.com/playlist?list=WL", None),              # Watch later: no one else can read it
    ("https://www.youtube.com/playlist?list=LL", None),
    ("https://www.youtube.com/@hanashiradio/videos", None),          # a channel: its first video only (PROVISIONAL)
    ("https://www.bilibili.tv/en/play/2048?list=PLsamplepodcast0000000000000000001", None),   # not YouTube
    ("https://www.youtube.com/watch?v=podcast0001&list=", None),
    ("", None),
])
def test_playlist_link_names_a_playlist_never_a_mix_or_a_single_video(url, playlist):
    assert core.playlist_link(url) == playlist


def test_transient_problems_are_an_outage_a_refusal_for_now_or_a_stall_never_a_gone_video():
    assert core.transient(f"could not read {PLAYLIST}: " + core._PLAIN[0][1])
    assert core.transient("video podcast0002: " + core.RATE_LIMITED)
    assert core.transient(core.STALLED.format(minutes=2))
    assert not core.transient(f"could not read {PLAYLIST}: the video is private or no longer there")
    assert not core.transient("no Japanese captions: " + TITLES[1])
    assert view.rest_kept([], True)                                  # a stop: goes on next time
    assert view.rest_kept([view.NO_READER], False)
    assert not view.rest_kept(["no Japanese captions: " + TITLES[1]], False)


# --- the rest skips what is in --------------------------------------------------------------------------------- #
def test_ids_in_finds_the_videos_under_processed_at_any_depth(tmp_path):
    _transcript(str(tmp_path), 0)
    _transcript(str(tmp_path / "hanashi radio - Everyday Japanese Podcast (playlist)"), 2)
    (tmp_path / "日記.txt").write_text("今日は雨。", encoding="utf-8")       # no id: never a video
    assert core.ids_in(str(tmp_path)) == {IDS[0], IDS[2]}
    assert core.ids_in(str(tmp_path / "nothing here")) == set()


def test_the_rest_reads_only_the_videos_not_in_and_counts_those(tmp_path, monkeypatch):
    processed = tmp_path / "Processed"
    """`new_only`: the first video (setup's, loose in Processed) and one a stopped run fetched are handed to yt-dlp as
    its download archive — checked before it reads a video — and the progress counts the two still to read."""
    _transcript(str(processed), 0)
    _transcript(str(processed / "hanashi radio - Everyday Japanese Podcast (playlist)"), 1)
    monkeypatch.setattr(core, "_probe", lambda url, log: _playlist_info())
    calls = []

    def run(args, timeout=1800, tick=None):
        archive = args[args.index("--download-archive") + 1]
        with open(archive, encoding="utf-8") as f:
            calls.append((args, f.read().split("\n")))
        assert os.path.dirname(archive) != os.path.dirname(args[args.index("-o") + 1]), "never in the counted folder"
        return Res()
    monkeypatch.setattr(core, "_run_ytdlp", run)
    lines = []
    core.extract([PLAYLIST], str(processed), lang="Japanese", log=lines.append, new_only=True)
    [(args, archive)] = calls
    assert archive == [f"youtube {IDS[0]}", f"youtube {IDS[1]}", ""]
    assert "--no-write-playlist-metafiles" in args and args[-1] == PLAYLIST
    assert "--no-playlist" not in args                               # the whole playlist this time


def test_the_rests_progress_counts_only_the_videos_still_to_read(tmp_path, monkeypatch):
    processed = tmp_path / "Processed"
    """Two of four in: "… n of 2 videos read", never "of 4" (the bar would never reach its end)."""
    _transcript(str(processed), 0)
    _transcript(str(processed), 3)
    monkeypatch.setattr(core, "_probe", lambda url, log: _playlist_info())
    seen = []
    monkeypatch.setattr(core, "_download_bucket", lambda urls, target, *a, **kw: seen.append(kw))
    core.extract([PLAYLIST], str(processed), lang="Japanese", log=lambda _l: None, new_only=True)
    assert seen[0]["counts"] == {PLAYLIST: 2} and seen[0]["skip"] == {IDS[0], IDS[3]}


def test_a_rest_whose_every_video_is_in_reads_nothing(tmp_path, monkeypatch):
    processed = tmp_path / "Processed"
    for i in range(4):
        _transcript(str(processed), i)
    monkeypatch.setattr(core, "_probe", lambda url, log: _playlist_info())
    monkeypatch.setattr(core, "_run_ytdlp", lambda *a, **k: pytest.fail("yt-dlp asked for videos already in"))
    lines = []
    core.extract([PLAYLIST], str(processed), lang="Japanese", log=lines.append, new_only=True)
    assert any("every video is in already" in line for line in lines)


def test_the_windows_own_runs_never_skip_and_count_every_video(tmp_path, monkeypatch):
    processed = tmp_path / "Processed"
    """Without `new_only` (the downloader window's Download) nothing is skipped: no archive, every entry counted."""
    _transcript(str(processed), 0)
    monkeypatch.setattr(core, "_probe", lambda url, log: _playlist_info())
    seen = []
    monkeypatch.setattr(core, "_download_bucket", lambda urls, target, *a, **kw: seen.append(kw))
    core.extract([PLAYLIST], str(processed), lang="Japanese", log=lambda _l: None)
    assert seen[0]["skip"] == set() and seen[0]["counts"] == {PLAYLIST: 4}


def test_the_progress_counts_videos_never_the_playlists_own_file(tmp_path):
    """yt-dlp is asked for no playlist info.json (`--no-write-playlist-metafiles`); the tick counts each video's."""
    lines = []
    tick = core._watch(str(tmp_path), 3, lines.append, clock=lambda: 0.0)
    (tmp_path / f"{IDS[1]}.info.json").write_text("{}", encoding="utf-8")
    tick()
    assert lines == ["  … 1 of 3 videos read"]


# --- the record: what goes on at the next start ---------------------------------------------------------------- #
def test_the_record_adds_each_playlist_once_and_goes_when_nothing_is_left(tmp_path):
    a = view.rest_update("ja", add=[PLAYLIST])
    assert a == {"playlists": [PLAYLIST], "unrouted": [], "tries": {}} and os.path.exists(view.rest_path("ja"))
    view.rest_update("ja", add=[PLAYLIST], unrouted=[str(tmp_path / "a.txt")])
    assert view.rest_read("ja") == {"playlists": [PLAYLIST], "unrouted": [str(tmp_path / "a.txt")], "tries": {}}
    assert view.rest_read("zh") == {"playlists": [], "unrouted": [], "tries": {}}      # one record per language
    view.rest_update("ja", done=[PLAYLIST])
    view.rest_update("ja", routed=[str(tmp_path / "A.TXT")] if os.name == "nt" else [str(tmp_path / "a.txt")])
    assert not os.path.exists(view.rest_path("ja"))


def test_a_reader_holding_the_record_for_a_moment_never_drops_a_transcript(tmp_path):
    """(Flake-P, tests/FLAKES.md) A virus scanner or a cloud folder's client opens the record just replaced: on Windows
    its open file refuses the next replace (Access is denied), and the transcript written then dropped out of the
    record — a quit before the hand-over lost it. The write waits the reader out."""
    import threading
    view.rest_update("ja", add=[PLAYLIST])
    held, let_go = threading.Event(), threading.Event()

    def outside_reader():
        with open(view.rest_path("ja"), encoding="utf-8"):
            held.set()
            let_go.wait(5)
    reader = threading.Thread(target=outside_reader)
    reader.start()
    assert held.wait(5)
    threading.Timer(0.25, let_go.set).start()                  # (the reader's own moment, then it lets go)
    transcript = str(tmp_path / "ひとり旅の話.txt")
    state = view.rest_update("ja", unrouted=[transcript])
    reader.join()
    assert state["unrouted"] == [transcript] and view.rest_read("ja")["unrouted"] == [transcript]


def test_a_broken_record_reads_as_none_and_is_written_whole_again(tmp_path):
    path = view.rest_path("ja")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"playlists": ["https://www.youtube.com/playlist?list=PL')      # cut off mid-write by a crash
    assert view.rest_read("ja") == {"playlists": [], "unrouted": [], "tries": {}}
    view.rest_update("ja", add=[PLAYLIST])
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"playlists": [PLAYLIST], "unrouted": [], "tries": {}}
    assert not os.path.exists(path + ".tmp")


def test_two_threads_writing_the_record_lose_nothing():
    links = [f"https://www.youtube.com/playlist?list=PLjfPBTv1Zr1J8RTG9iCANlm2vzBhl7Q{i:02d}" for i in range(20)]
    threads = [threading.Thread(target=view.rest_update, args=("ja", [u])) for u in links]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(view.rest_read("ja")["playlists"]) == sorted(links)


# --- the review's round (A8P-1…15, IK-1…11) ------------------------------------------------------------------- #
def test_a_removed_video_and_one_in_a_tier_are_never_read_again(tmp_path, monkeypatch):
    """(A8P-3, IK-4) "Already in" is the language's whole data folder: a 2.x tier, Library, Graduated and the trash."""
    processed = tmp_path / "Processed"
    processed.mkdir()
    _transcript(str(tmp_path / "HighPriority" / "hanashi"), 0)
    _transcript(str(tmp_path / ".trash"), 1)
    _transcript(str(tmp_path / "Library" / "hanashi radio"), 2)
    monkeypatch.setattr(core, "_probe", lambda url, log: _playlist_info())
    seen = []
    monkeypatch.setattr(core, "_download_bucket", lambda urls, target, *a, **kw: seen.append(kw))
    core.extract([PLAYLIST], str(processed), lang="Japanese", log=lambda _l: None, new_only=True)
    assert seen[0]["skip"] == {IDS[0], IDS[1], IDS[2]} and seen[0]["counts"] == {PLAYLIST: 1}


def test_each_transcript_is_told_as_it_is_written(tmp_path, monkeypatch):
    """(A8P-2) `written(path)` for each transcript the moment it is on disk (a crash after it never loses it)."""
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n今日は写真の話をします。\n"

    def run(args, timeout=1800, tick=None):
        tmp = os.path.dirname(args[args.index("-o") + 1])
        for i in (1, 2):
            with open(os.path.join(tmp, f"{IDS[i]}.info.json"), "w", encoding="utf-8") as f:
                json.dump({"id": IDS[i], "title": TITLES[i], "channel": "hanashi radio",
                           "webpage_url": f"https://youtu.be/{IDS[i]}", "subtitles": {"ja": [{"ext": "vtt"}]},
                           "automatic_captions": {}}, f, ensure_ascii=False)
            with open(os.path.join(tmp, f"{IDS[i]}.ja.vtt"), "w", encoding="utf-8") as f:
                f.write(vtt)
        return Res()
    monkeypatch.setattr(core, "_probe", lambda url, log: _playlist_info(3))
    monkeypatch.setattr(core, "_run_ytdlp", run)
    told = []
    core.extract([PLAYLIST], str(tmp_path / "Processed"), lang="Japanese", log=lambda _l: None, new_only=True,
                 written=lambda path: told.append((path, os.path.exists(path))))
    assert len(told) == 2 and all(on_disk for _p, on_disk in told)
    assert all(p.endswith((f"[{IDS[1]}].txt", f"[{IDS[2]}].txt")) for p, _d in told)


def test_a_run_past_its_time_is_said_and_kept_for_a_later_try(tmp_path, monkeypatch):
    """(A8P-1) yt-dlp's 30 minutes ran out (a playlist of hundreds): said in plain words, a passing problem."""
    import subprocess

    def run(args, timeout=1800, tick=None):
        raise subprocess.TimeoutExpired(args, timeout)
    monkeypatch.setattr(core, "_probe", lambda url, log: _playlist_info())
    monkeypatch.setattr(core, "_run_ytdlp", run)
    lines = []
    core.extract([PLAYLIST], str(tmp_path / "Processed"), lang="Japanese", log=lines.append, new_only=True)
    [said] = view.problems(lines)
    assert said == core.TIMED_OUT.format(minutes=30) and core.transient(said)
    assert core.transient(f"could not read {PLAYLIST}: " + core.SLOW.format(seconds=core.PROBE_S))


def test_a_channels_play_all_list_is_no_playlist():
    """(A8P-12) `UU…` is a channel's uploads ("Play all"): its first video only, as a channel link."""
    assert core.playlist_link("https://www.youtube.com/watch?v=podcast0001&list=UULFhanashiradioChannel01") is None


def test_fruitless_tries_are_counted_and_one_that_brings_something_starts_again():
    view.rest_update("ja", add=[PLAYLIST])
    assert view.rest_update("ja", tried=[PLAYLIST])["tries"] == {PLAYLIST: 1}
    assert view.rest_update("ja", tried=[PLAYLIST])["tries"] == {PLAYLIST: 2}
    assert view.rest_update("ja", fruitful=[PLAYLIST])["tries"] == {}
    view.rest_update("ja", tried=[PLAYLIST])
    assert view.rest_update("ja", done=[PLAYLIST])["tries"] == {}       # gone with its playlist


def test_prune_drops_transcripts_no_longer_on_disk(tmp_path):
    """(A8P-4) a transcript the learner deleted never keeps the record (and a job at every start) alive."""
    kept = tmp_path / "a.txt"
    kept.write_text("今日は雨。", encoding="utf-8")
    view.rest_update("ja", unrouted=[str(kept), str(tmp_path / "gone.txt")])
    assert view.rest_update("ja", prune=True)["unrouted"] == [str(kept)]
    kept.unlink()
    view.rest_update("ja", prune=True)
    assert not os.path.exists(view.rest_path("ja"))
