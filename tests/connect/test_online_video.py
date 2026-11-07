"""Michi-YT: an online title's video fetched by Anki Miner's own `fetch` (Z-8, 3.11.0 `cli/api/fetch.py`) into
Connect's one folder for it, and gone after (`app/connect/online.py`); the window's half (no *No video* for an online
title, ▶ still its page) and the cards' Source (the transcript's names).

What a wrong answer costs: a video left on the learner's disk (or written into the library or their own folders), a
Stop that takes minutes, an Anki Miner message that sends the learner to Anki Miner's window ("Ever." — Sonic,
2026-10-27), or a private / removed / age-restricted video that crashes Connect instead of saying so.

Against the fake Anki Miner (`tests/connect/fake_anki_miner.py`'s `fetch`, as API.md documents it); real Japanese
captions; never the network, never a live Anki.
"""
import json
import os
import time
from types import SimpleNamespace

import pytest

from app.connect import anki_miner, feed, online, runfile, runner, status, stopping

LINK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
QUICK = 4.0                     # seconds from a press to the program ended (Michi-X's rule, with room)


@pytest.fixture
def ytdlp(tmp_path, monkeypatch):
    """The YouTube downloader's own yt-dlp, as its module keeps it (a stand-in file of that name)."""
    folder = tmp_path / "surasura-bin"
    folder.mkdir()
    exe = folder / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    exe.write_bytes(b"")
    if os.name != "nt":
        exe.chmod(0o755)
    monkeypatch.setattr(online, "ytdlp_folder", lambda: str(folder))
    return str(folder)


def _fetch(fake_miner, monkeypatch, **spec):
    monkeypatch.setattr(anki_miner, "POLL_S", 0.1)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch=spec)
    return online.fetch(fake_miner.path, "p-surasura", "ja", 7, LINK)


# --- the fetch itself ----------------------------------------------------------------------------------------------- #
def test_a_fetch_lands_in_connects_own_folder_with_the_downloaders_ytdlp_on_its_path(fake_miner, monkeypatch, ytdlp):
    # why: never the library or the learner's folders; the yt-dlp the YouTube module keeps up to date is the one used
    video, subtitle = _fetch(fake_miner, monkeypatch)
    here = online.place(7)
    assert os.path.commonpath([video, here]) == here and os.path.commonpath([subtitle, here]) == here
    assert os.path.isfile(video) and subtitle.endswith(".srt")
    call = next(c for c in fake_miner.calls() if "fetch_ytdlp" in c)
    assert call["fetch_ytdlp"] and os.path.dirname(call["fetch_ytdlp"]) == ytdlp, call
    episode = call["episodes"][0]
    assert episode == {"run_id": "v7", "youtube_url": LINK, "youtube_subtitle_source": "captions",
                       "youtube_align_captions": False}, "its own captions, as YouTube timed them to the video"
    assert call["profile"] == "p-surasura", "the profile Connect mines with"
    assert not [n for n in os.listdir(online.folder()) if n.endswith(".json")], "the fetch file is gone"
    assert online.drop(7) and not os.path.exists(here), "drop takes the whole job folder"


def test_webvtt_captions_become_subrip_the_cue_reader_reads(fake_miner, monkeypatch, ytdlp):
    # why: Anki Miner keeps a .vtt when YouTube serves no .srt; the pick reads .srt / .ass only
    vtt = ("WEBVTT\nKind: captions\nLanguage: ja\n\nNOTE made by YouTube\n\n"
           "00:00:01.000 --> 00:00:03.500 align:start position:0%\n<c>今日は</c>いい天気ですね\n\n"
           "00:03.600 --> 00:05.250\n一生懸命に走り出す\n")
    _video, subtitle = _fetch(fake_miner, monkeypatch, subtitle=vtt, vtt=True)
    from app import cues
    read = cues.read(subtitle, "ja")
    assert [(c.start, c.end, c.text) for c in read] == [(1000, 3500, "今日はいい天気ですね"),
                                                        (3600, 5250, "一生懸命に走り出す")]


@pytest.mark.parametrize("spec, words, standing", [
    ({"error": "YOUTUBE_REFUSED", "message": "Sign in to confirm your age. This video may be inappropriate for some "
                                             "users."}, online.AGE, False),
    ({"error": "FETCH_FAILED", "message": "ERROR: [youtube] dQw4w9WgXcQ: Private video. Sign in if you've been "
                                          "granted access to this video"}, online.PRIVATE, False),
    ({"error": "FETCH_FAILED", "message": "ERROR: [youtube] dQw4w9WgXcQ: Video unavailable. This video has been "
                                          "removed by the uploader"}, online.REMOVED, False),
    ({"error": "YOUTUBE_REFUSED", "message": "Live streams are not supported."}, online.LIVE, False),
    ({"error": "YOUTUBE_REFUSED", "message": "This video has no Japanese captions."}, online.NO_CAPTIONS, False),
    ({"error": "FETCH_FAILED", "message": "Sign in to confirm you're not a bot", "transient": True}, online.BOT,
     True),
    ({"error": "FETCH_FAILED", "message": "urlopen error [Errno 11001] getaddrinfo failed", "transient": True},
     online.OFFLINE, True),
    ({"error": "FETCH_FAILED", "message": "something new went wrong", "transient": True}, online.OFFLINE, True),
    ({"call": "SETUP_ERROR", "message": "yt-dlp is not installed. Open Anki Miner, go to Video -> YouTube and "
                                        "install it, then try again."}, online.NO_YTDLP, True),
    ({"error": "SETUP_ERROR", "message": "ffmpeg was not found. Install ffmpeg, or set its location in Anki Miner's "
                                         "settings."}, online.NO_FFMPEG, True),
], ids=["age", "private", "removed", "live", "no-captions", "bot", "offline", "transient-other", "no-ytdlp", "ffmpeg"])
def test_every_refusal_is_plain_words_never_anki_miners_window(fake_miner, monkeypatch, spec, words, standing):
    # why: the row and Needs you say it plainly; nothing sends the learner to Anki Miner's window
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch, **spec)
    assert raised.value.say == words and raised.value.standing is standing
    assert "Open Anki Miner" not in raised.value.say and "Anki Miner's settings" not in raised.value.say


def test_a_video_longer_than_anki_miner_takes_says_its_limit(fake_miner, monkeypatch):
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch, error="YOUTUBE_REFUSED", message="Video exceeds max duration (120 min).")
    assert "120 min" in raised.value.say and not raised.value.standing


def test_a_file_anki_miner_names_outside_the_jobs_folder_is_never_taken(fake_miner, monkeypatch):
    # why: the job mines (and later deletes) only what is inside its own folder
    with pytest.raises(online.Trouble):
        _fetch(fake_miner, monkeypatch, outside=True)


def test_no_room_on_the_disk_is_said_before_anything_downloads(fake_miner, monkeypatch):
    monkeypatch.setattr(online, "room", lambda path=None, need=online.FLOOR: False)
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch)
    assert raised.value.say == online.NO_ROOM and raised.value.standing
    assert "fetch" not in fake_miner.commands(), "Anki Miner never started"


def test_room_reads_the_disk_the_folder_is_on(tmp_path):
    assert online.room(str(tmp_path / "not" / "made" / "yet"), need=1)
    assert not online.room(str(tmp_path), need=10 ** 18)


def test_a_stop_ends_the_download_within_seconds(fake_miner, monkeypatch):
    # why: Michi-X's rule — Stop is quick; a fetch writes nothing to Anki, so it is ended like a look-up
    monkeypatch.setattr(anki_miner, "POLL_S", 0.1)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"hold": 30})
    pressed = []

    def check():
        if not pressed and "fetch" in fake_miner.commands():
            pressed.append(time.monotonic())
        return bool(pressed)
    with stopping.watching(check):
        with pytest.raises(stopping.Stopped):
            online.fetch(fake_miner.path, None, "ja", 8, LINK)
    assert time.monotonic() - pressed[0] < QUICK
    assert online.drop(8) and not os.path.exists(online.place(8))


def test_an_update_staged_ends_the_download(fake_miner, monkeypatch):
    # why: an update never waits minutes on a download (K99's rule for a step that writes nothing to Anki)
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"hold": 30})
    began = time.monotonic()
    with pytest.raises(stopping.Stopped):
        online.fetch(fake_miner.path, None, "ja", 9, LINK, should_end=lambda: True)
    assert time.monotonic() - began < 10


def test_the_download_percent_is_read_as_it_goes(fake_miner, monkeypatch):
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"hold": 1.0})
    seen = []
    online.fetch(fake_miner.path, None, "ja", 10, LINK, on_progress=seen.append)
    assert 40 in seen, seen


# --- drop and sweep ------------------------------------------------------------------------------------------------- #
def test_the_sweep_removes_every_leftover_and_nothing_outside_its_folder(tmp_path):
    # why: a Connect killed mid-job leaves a video; the next start takes it — and only what is in its own folder
    beside = os.path.join(os.path.dirname(online.folder()), "ledger-like.sqlite")
    os.makedirs(os.path.join(online.folder(), "v3", "fetch-1"))
    with open(os.path.join(online.folder(), "v3", "fetch-1", "x.mp4"), "w") as f:
        f.write("left")
    with open(beside, "w") as f:
        f.write("Connect's own")
    assert online.sweep() == 1
    assert os.listdir(online.folder()) == [] and os.path.isfile(beside)
    assert online.sweep() == 0


def test_drop_of_a_job_with_nothing_downloaded_is_no_error():
    assert online.drop(12345) is True


def test_a_held_file_is_tried_again_then_left_for_the_next_sweep(monkeypatch, tmp_path):
    # why: Windows lets go of a just-ended yt-dlp's file a moment later; a folder that stays is never an error
    os.makedirs(os.path.join(online.place(4), "fetch-1"))
    tries = []
    monkeypatch.setattr(online.shutil, "rmtree", lambda path, ignore_errors=False: tries.append(path))
    monkeypatch.setattr(online.time, "sleep", lambda s: None)
    assert online.drop(4) is False and len(tries) == 10


# --- Steps.download: the gate, the site, the feature --------------------------------------------------------------- #
@pytest.fixture
def steps(fake_miner, monkeypatch):
    from app.cli import verbs
    s = runner.Steps({"connect_anki_miner_path": fake_miner.path})
    settings = {"youtube_risk_acknowledged": True}
    monkeypatch.setattr(s, "_settings", lambda lang: dict(settings, target_language=lang))
    monkeypatch.setattr(s, "title", lambda lang, job: "ゆっくり日本語 - 第3話")
    info = {"app": "3.11.0", "features": ["fetch"]}
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir, held=None: (info, "p1", None))
    monkeypatch.setattr(anki_miner, "POLL_S", 0.1)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={})
    s.test_settings, s.test_info = settings, info
    return s


JOB = {"id": 21, "item_id": 5, "tag": "u-21"}
WEB = {"site": "youtube", "url": LINK, "names": ["ゆっくり日本語", "第3話 [dQw4w9WgXcQ]"]}


def test_steps_download_fetches_once_a_run_and_drop_forgets_it(steps, fake_miner):
    # why: a pick again after a profile change re-uses the video; once dropped, a re-mine downloads again
    first = steps.download("ja", JOB, WEB)
    again = steps.download("ja", JOB, WEB)
    assert first == again and fake_miner.commands().count("fetch") == 1
    steps.drop_online(JOB)
    assert not os.path.exists(online.place(21))
    steps.download("ja", JOB, WEB)
    assert fake_miner.commands().count("fetch") == 2


def test_without_the_risk_tick_nothing_downloads_and_it_is_said_once(steps, fake_miner):
    # why: the downloader's own "I understand the risks" is the yes for this download too (no new switch)
    steps.test_settings["youtube_risk_acknowledged"] = False
    with pytest.raises(runner.Needs) as raised:
        steps.download("ja", JOB, WEB)
    assert raised.value.say == online.NOT_TICKED and raised.value.standing
    assert "fetch" not in fake_miner.commands()


def test_a_bilibili_video_is_said_plainly_never_fetched(steps, fake_miner):
    with pytest.raises(runner.Needs) as raised:
        steps.download("ja", JOB, dict(WEB, site="bilibili", url="https://www.bilibili.tv/en/video/4789"))
    assert raised.value.say.endswith(online.BILIBILI) and not raised.value.standing
    assert "fetch" not in fake_miner.commands()


def test_an_anki_miner_without_fetch_is_said_once(steps, fake_miner):
    steps.test_info["features"] = []
    with pytest.raises(runner.Needs) as raised:
        steps.download("ja", JOB, WEB)
    assert raised.value.say == online.NO_FETCH and raised.value.standing


def test_a_videos_own_trouble_carries_its_title(steps, fake_miner):
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"error": "FETCH_FAILED", "message": "Private video"})
    with pytest.raises(runner.Needs) as raised:
        steps.download("ja", JOB, WEB)
    assert raised.value.say == f"ゆっくり日本語 - 第3話: {online.PRIVATE}" and not raised.value.standing
    assert raised.value.once, "counted once while it stands (review M2)"


def test_an_update_staged_mid_download_is_the_updates_wait(steps, fake_miner, monkeypatch):
    monkeypatch.setattr(online, "UPDATE_EVERY", 1)
    monkeypatch.setattr(steps, "update_staged", lambda: True)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"hold": 30})
    with pytest.raises(runner.Wait) as raised:
        steps.download("ja", JOB, WEB)
    assert raised.value.reason == runner.STOPPED_FOR_UPDATE


def test_no_anki_miner_is_none(steps, monkeypatch):
    monkeypatch.setattr(anki_miner, "find", lambda loaded: None)
    assert steps.download("ja", JOB, WEB) is None


# --- the cards' Source names the transcript ----------------------------------------------------------------------- #
def test_the_run_file_names_the_transcripts_folder_and_name():
    # why: 順's one source-name rule ties a card to the file it names: the transcript, never `fetch-1 — <id>`
    ep = runfile.episode("j-1", "/x/online/v1/fetch-1/dQw4w9WgXcQ.mp4", "/x/s.srt", [{"word": "天気"}],
                         names=["ゆっくり日本語 (playlist)", "第3話 天気の話 [dQw4w9WgXcQ]"])
    assert ep["series_name_override"] == "ゆっくり日本語 (playlist)"
    assert ep["episode_name_override"] == "第3話 天気の話 [dQw4w9WgXcQ]"
    plain = runfile.episode("j-1", "/x/Show/01.mkv", "/x/Show/01.srt", [{"word": "天気"}])
    assert "series_name_override" not in plain and "episode_name_override" not in plain
    source_names = pytest.importorskip("modules.junban.source_names")      # (the module is private: GitHub has none)
    card = "ゆっくり日本語 (playlist) — 第3話 天気の話 [dQw4w9WgXcQ] @ 0:01:02"
    assert source_names.card_key(card) in source_names.names_of(
        "Processed/ゆっくり日本語 (playlist)/第3話 天気の話 [dQw4w9WgXcQ].txt"), "the card names its transcript"


def test_online_of_reads_the_link_and_names_from_the_item(monkeypatch):
    from app.services import play
    monkeypatch.setattr(play, "online_link", lambda language, rel, record=None: (LINK, None))
    item = {"source_type": "youtube", "rel_path": "Processed/日本語の練習/会話 第1話 [dQw4w9WgXcQ].txt"}
    assert online.of("ja", item) == {"site": "youtube", "url": LINK,
                                     "names": ["日本語の練習", "会話 第1話 [dQw4w9WgXcQ]"]}
    assert online.of("ja", {"source_type": "subtitle", "rel_path": "Library/Show/01.srt"}) is None
    assert online.of("ja", {"source_type": "youtube", "rel_path": "会話 [dQw4w9WgXcQ].txt"})["names"] == \
        ["会話 [dQw4w9WgXcQ]", "会話 [dQw4w9WgXcQ]"]


# --- the window: its row's words while it downloads; never *No video* ------------------------------------------- #
def test_the_row_says_its_video_is_downloading_with_its_percent():
    job = {"state": "picking", "progress": json.dumps({"step": runner.DOWNLOADING, "percent": 45})}
    assert status._progress(job)["doing"] == "Downloading its video (45%)"
    assert status._progress({"state": "picking", "progress": None})["doing"] == "Choosing words"


def test_an_online_title_with_a_no_video_from_before_is_a_wait_never_no_video():
    # why: a Connect from before this lane left *No video* on every YouTube title; it now mines at its next start
    from app.services import view_rows as vr
    st = vr.Status("mine", "Mine", "", "ink")
    item = feed.Item(kind=feed.NO_VIDEO, words=feed.WORDS[feed.NO_VIDEO], tip=runner.NO_VIDEO, job=3, made=0, total=0)
    got = vr._connected(st, item, "video", online="youtube")
    assert got.kind == "waiting" and got.tip == feed.NEXT_START
    assert vr._connected(st, item, "video").kind == "no_media", "an episode on disk keeps its *No video*"


# --- review round 1 ------------------------------------------------------------------------------------------------ #
def test_the_sweep_removes_a_killed_fetchs_own_file_too():
    # why (review S2): a Connect killed mid-fetch leaves `fetch-v<job>.json` beside the folders
    os.makedirs(online.folder())
    with open(os.path.join(online.folder(), "fetch-v5.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    online.sweep()
    assert os.listdir(online.folder()) == []


def test_a_whole_call_refusal_is_the_languages_trouble(fake_miner, monkeypatch):
    # why (review S3): a profile Anki Miner can't read refuses every video alike: once for the language
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch, call="PROFILE_UNREADABLE", message="The profile can't be read.")
    assert raised.value.standing


def test_after_the_languages_trouble_no_other_video_is_fetched_this_run(steps, fake_miner):
    # why (review S4): offline once, every other online episode would wait out a fetch of its own
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"error": "FETCH_FAILED", "transient": True,
                                                               "message": "getaddrinfo failed"})
    for job in (JOB, dict(JOB, id=22, item_id=6)):
        with pytest.raises(runner.Needs) as raised:
            steps.download("ja", job, WEB)
        assert raised.value.say == online.OFFLINE and raised.value.standing
    assert fake_miner.commands().count("fetch") == 1


def test_webvtt_entities_are_read_as_text(tmp_path):
    vtt = tmp_path / "x.ja.vtt"
    vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n雨&amp;風&nbsp;です\n", encoding="utf-8")
    assert "雨&風\xa0です" in open(online.as_srt(str(vtt)), encoding="utf-8").read()


def test_one_videos_format_trouble_never_holds_the_others(steps, fake_miner):
    # why (review r2 S1): "requested format is not available" can be one video's alone (members' formats only)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"error": "FETCH_FAILED",
                                                               "message": "Requested format is not available"})
    for job in (JOB, dict(JOB, id=22, item_id=6)):
        with pytest.raises(runner.Needs) as raised:
            steps.download("ja", job, WEB)
        assert raised.value.say == online.STALE
    assert fake_miner.commands().count("fetch") == 2, "each video still tried"
