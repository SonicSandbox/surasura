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

from app import locks, youtube_hold
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
    ({"error": "FETCH_FAILED", "message": "urlopen error [Errno 11001] getaddrinfo failed", "transient": True},
     online.OFFLINE, True),
    ({"error": "FETCH_FAILED", "message": "something new went wrong", "transient": True}, online.OFFLINE, True),
    ({"call": "SETUP_ERROR", "message": "yt-dlp is not installed. Open Anki Miner, go to Video -> YouTube and "
                                        "install it, then try again."}, online.NO_YTDLP, True),
    ({"error": "SETUP_ERROR", "message": "ffmpeg was not found. Install ffmpeg, or set its location in Anki Miner's "
                                         "settings."}, online.NO_FFMPEG, True),
], ids=["age", "private", "removed", "live", "no-captions", "offline", "transient-other", "no-ytdlp", "ffmpeg"])
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
                                     "names": ["日本語の練習", "会話 第1話 [dQw4w9WgXcQ]"], "captions": None,
                                     "rel": "Processed/日本語の練習/会話 第1話 [dQw4w9WgXcQ].txt"}
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


# --- Yt-B: YouTube's bot check holds every YouTube call for a day -------------------------------------------------- #
# Sonic 2026-11-12: "will this hit from my own network and then will I have issues in the future with too many
# requests?" Connect's video is asked from the learner's own address, like the downloader's transcripts: one refusal
# holds both for a day, said with when it tries again; never asked again in that time.
@pytest.mark.parametrize("message", [
    "ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you\u2019re not a bot. Use --cookies-from-browser or --cookies",
    "ERROR: [youtube] dQw4w9WgXcQ: Unable to download webpage: HTTP Error 429: Too Many Requests",
], ids=["bot", "429"])
def test_a_refusal_holds_every_youtube_call_and_says_when(fake_miner, monkeypatch, message):
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch, error="FETCH_FAILED", message=message, transient=True)
    until = youtube_hold.held()
    assert until and raised.value.standing
    assert raised.value.say == youtube_hold.words(until) and youtube_hold.is_words(raised.value.say)
    with pytest.raises(online.Trouble) as again:
        online.fetch(fake_miner.path, "p-surasura", "ja", 8, LINK)
    assert again.value.say == raised.value.say and fake_miner.commands().count("fetch") == 1, \
        "nothing asked of YouTube while the hold runs"


def test_an_age_check_holds_nothing(fake_miner, monkeypatch):
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch, error="YOUTUBE_REFUSED",
               message="Sign in to confirm your age. This video may be inappropriate for some users.")
    assert raised.value.say == online.AGE and youtube_hold.held() is None


def test_a_hold_the_downloader_began_is_met_before_anki_miner_starts(fake_miner, monkeypatch):
    youtube_hold.hold()
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch)
    assert youtube_hold.is_words(raised.value.say) and raised.value.standing
    assert "fetch" not in fake_miner.commands()


def test_a_held_trouble_stops_every_other_fetch_this_run(steps, fake_miner):
    # why (review S4, as offline): every other online episode would only meet the same hold
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"error": "FETCH_FAILED", "transient": True,
                                                               "message": "Sign in to confirm you're not a bot"})
    for job in (JOB, dict(JOB, id=22, item_id=6)):
        with pytest.raises(runner.Needs) as raised:
            steps.download("ja", job, WEB)
        assert youtube_hold.is_words(raised.value.say) and raised.value.standing
    assert fake_miner.commands().count("fetch") == 1


def test_a_fetch_waits_its_turn_and_a_stop_ends_the_wait(fake_miner, monkeypatch):
    # why: never two YouTube calls at once from this computer; a Stop never waits behind the window's playlist
    other = locks.take(youtube_hold.LOCK, "the window's playlist", owner=object())     # (another program)
    try:
        monkeypatch.setattr(stopping, "pressed", lambda: True)
        started = time.monotonic()
        with pytest.raises(stopping.Stopped):
            _fetch(fake_miner, monkeypatch)
        assert time.monotonic() - started < QUICK and "fetch" not in fake_miner.commands()
    finally:
        other.release()


def test_a_held_fetch_never_waits_for_the_turn(fake_miner, monkeypatch):
    # why (mutant C4): behind the window's half-hour playlist, Connect would wait all that time to learn it is held
    youtube_hold.hold()
    monkeypatch.setattr(youtube_hold, "turn", lambda *a, **k: pytest.fail("asked for the turn while held"))
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch)
    assert youtube_hold.is_words(raised.value.say) and "fetch" not in fake_miner.commands()


# --- Michi-YT2 (based on Mattias's #455): captions no person wrote -> Anki Miner's speech model on the audio -------- #
# "I don't want YouTube's auto-generated subs. They are never good." The library's transcript names its captions'
# kind in its header (the downloader's `build_text`); a kind no person wrote has Anki Miner make the cards' subtitle
# from the video's audio — only with a speech model it has: never a download, else YouTube's captions, said once.
TRANSCRIPTS = {   # language -> (title, channel, the cues): real lines, as the downloader writes them after its header
    "ja": ("誰から何も言われずに1人で英語学習継続できるようになる方法", "ユートのチャンネル",
           "[00:00:00] 今から皆さんにめちゃくちゃ難しい質問します\n[00:00:04] 今日はいい天気ですね"),
    "zh": ("台北夜市美食之旅", "小明的頻道",
           "[00:00:00] 大家好，歡迎回到我的頻道。\n[00:00:03] 今天我们要去台北的夜市吃东西。"),
}
HAS_MODEL = {"installed": ["small"], "model": "small"}
NO_MODEL = {"installed": [], "model": "small"}


@pytest.fixture(autouse=True)
def _speech_asked_afresh(monkeypatch):
    # why: `speech_ready` keeps its answer for the run; each test is a run of its own
    monkeypatch.setattr(anki_miner, "_SPEECH", {})


def _transcript(tmp_path, monkeypatch, language, kind, crlf=False, bom=False):
    """The downloader's transcript of a video in the language's data folder (`build_text`, its own header) ->
    its item."""
    from app import path_utils
    from app.services import play
    from modules.youtube_downloader import downloader
    title, channel, body = TRANSCRIPTS[language]
    info = {"title": title, "channel": channel, "webpage_url": LINK, "upload_date": "20240501", "duration": 2472}
    text = downloader.build_text(info, body, language, kind)
    rel = f"Processed/{channel} - {title} [dQw4w9WgXcQ].txt"
    (tmp_path / "Processed").mkdir(exist_ok=True)
    data = text.replace("\n", "\r\n") if crlf else text
    (tmp_path / rel).write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))
    monkeypatch.setattr(path_utils, "get_data_path", lambda lang: str(tmp_path))
    monkeypatch.setattr(play, "online_link", lambda language, rel, record=None: (LINK, None))
    return {"source_type": "youtube", "rel_path": rel}


@pytest.mark.parametrize("language", ("ja", "zh"))
@pytest.mark.parametrize("kind, source", (("manual", online.CAPTIONS), ("native auto", online.TRANSCRIBE),
                                          ("auto-translated", online.CAPTIONS)))
def test_machine_captions_have_anki_miner_transcribe_and_a_persons_keep_youtubes(tmp_path, monkeypatch, language,
                                                                                 kind, source):
    # why: YouTube's speech recognition misspells words and cuts clips badly; a person's captions are the best
    # subtitle there is and stay as they were; a machine translation (review r1 M1) is of a video spoken in another
    # language — its audio heard by a ja / zh model would be nonsense, so Anki Miner's own rule stands as before
    web = online.of(language, _transcript(tmp_path, monkeypatch, language, kind))
    assert web["captions"] == kind
    assert online.subtitle_source(web) == source


@pytest.mark.parametrize("crlf, bom", ((True, False), (False, True)), ids=["crlf", "bom"])
def test_the_header_is_read_whatever_its_line_ends_or_bom(tmp_path, monkeypatch, crlf, bom):
    # why: a transcript copied between computers (or saved by an editor) keeps its header's meaning
    web = online.of("ja", _transcript(tmp_path, monkeypatch, "ja", "native auto", crlf=crlf, bom=bom))
    assert web["captions"] == "native auto" and online.subtitle_source(web) == online.TRANSCRIBE


def test_a_transcript_naming_no_kind_gone_or_unreadable_keeps_youtubes_captions(tmp_path, monkeypatch):
    # why: only a header that says "no person wrote these" changes anything; everything else works as before
    item = _transcript(tmp_path, monkeypatch, "ja", "manual")
    (tmp_path / item["rel_path"]).write_text("今日はいい天気ですね。\n明日も晴れるでしょう。\n", encoding="utf-8")
    assert online.of("ja", item)["captions"] is None, "a text with no header"
    (tmp_path / item["rel_path"]).write_bytes(b"")
    assert online.of("ja", item)["captions"] is None, "an empty file"
    os.remove(tmp_path / item["rel_path"])
    assert online.of("ja", item)["captions"] is None, "gone"
    for web in ({"captions": None}, {}, None):
        assert online.subtitle_source(web) == online.CAPTIONS


def test_a_long_transcript_is_read_for_its_header_alone(tmp_path, monkeypatch):
    # why: only the first HEAD bytes are read (a two-hour video's transcript is never read whole for six lines); a
    # title of a few hundred characters still leaves the header inside them
    item = _transcript(tmp_path, monkeypatch, "ja", "native auto")
    path = tmp_path / item["rel_path"]
    text = path.read_text(encoding="utf-8")
    path.write_text("長いタイトル" * 60 + text[text.index("\n"):] + "\n" + "[00:00:09] 一生懸命に走り出す\n" * 400,
                    encoding="utf-8")
    assert os.path.getsize(path) > online.HEAD
    assert online.of("ja", item)["captions"] == "native auto"


def _episode(fake_miner):
    return [c for c in fake_miner.calls() if c.get("episodes")][-1]["episodes"][0]


@pytest.mark.parametrize("language", ("ja", "zh"))
@pytest.mark.parametrize("kind, source", (("native auto", "transcribe"), ("auto-translated", "captions"),
                                          ("manual", "captions"), (None, "captions")))
def test_steps_download_asks_for_the_transcription_only_of_machine_captions(steps, fake_miner, language, kind,
                                                                            source):
    # why: the fetch file is the one thing Anki Miner reads; with a speech model it has, machine captions are skipped
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={}, speech=HAS_MODEL)
    _video, subtitle = steps.download(language, JOB, dict(WEB, captions=kind))
    assert _episode(fake_miner) == {"run_id": "v21", "youtube_url": LINK, "youtube_subtitle_source": source,
                                    "youtube_align_captions": False}
    assert steps.fetched_with == {"21": source}
    with open(subtitle, encoding="utf-8") as f:
        assert ("00:00:01,200" in f.read()) is (source == "transcribe"), "the subtitle made from the audio is used"
    assert "setup" not in fake_miner.commands(), "nothing installed"


@pytest.mark.parametrize("language", ("ja", "zh"))
def test_without_a_speech_model_youtubes_captions_are_taken_and_nothing_downloads_but_the_video(steps, fake_miner,
                                                                                               language):
    # why: the learner never said yes to the speech model; Anki Miner would refuse the transcription, so the cards
    # come from YouTube's captions as before — never a model downloaded, never `setup`
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={}, speech=NO_MODEL)
    video, _subtitle = steps.download(language, JOB, dict(WEB, captions="native auto"))
    assert os.path.isfile(video)
    assert _episode(fake_miner)["youtube_subtitle_source"] == "captions"
    assert steps.fetched_with == {"21": "captions"}, "for `_download`'s one note"
    assert fake_miner.commands().count("fetch") == 1
    assert set(fake_miner.commands()) <= {"version", "check", "settings-import", "fetch"}, fake_miner.commands()


def test_a_speech_model_gone_after_the_check_falls_back_to_captions_for_the_rest_of_the_run(steps, fake_miner):
    # why: Anki Miner's own refusal (before it downloads anything) must never become a stuck video or a message that
    # sends the learner to Anki Miner's window: YouTube's captions after all, and no second try at each video
    anki_miner._SPEECH[(fake_miner.path, "ja", "p1")] = (True, time.monotonic())   # (asked earlier this run)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={}, speech=NO_MODEL)
    steps.download("ja", JOB, dict(WEB, captions="native auto"))
    sources = [c["episodes"][0]["youtube_subtitle_source"] for c in fake_miner.calls() if c.get("episodes")]
    assert sources == ["transcribe", "captions"] and steps.fetched_with == {"21": "captions"}
    assert (fake_miner.path, "ja", "p1") not in anki_miner._SPEECH, "its yes forgotten: asked again next time"
    steps.download("ja", dict(JOB, id=22, item_id=6), dict(WEB, captions="native auto"))
    sources = [c["episodes"][0]["youtube_subtitle_source"] for c in fake_miner.calls() if c.get("episodes")]
    assert sources == ["transcribe", "captions", "captions"], "the next video asks for captions at once"


def test_anki_miners_speech_refusal_is_plain_words():
    # why: never "Install it with setup --speech-model, or in Anki Miner: Settings …" on the learner's screen
    say, standing = online.plain("The speech model small is not installed. Install it with setup --speech-model, or "
                                 "in Anki Miner: Settings -> Transcription & Alignment.")
    assert say == online.NO_SPEECH and standing and "Anki Miner:" not in say


def test_without_the_risk_tick_a_machine_captioned_video_asks_nothing_of_anki_miner(steps, fake_miner):
    # why: the YouTube risk tick gates the whole fetch, the speech model's question included
    steps.test_settings["youtube_risk_acknowledged"] = False
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={}, speech=HAS_MODEL)
    with pytest.raises(runner.Needs) as raised:
        steps.download("ja", JOB, dict(WEB, captions="native auto"))
    assert raised.value.say == online.NOT_TICKED and fake_miner.commands() == []


def test_the_row_says_its_subtitles_are_made_from_the_audio_while_anki_miner_transcribes(fake_miner, monkeypatch):
    # why: a 20-minute video takes minutes to transcribe on a CPU; the row never sits on "Downloading (99%)" meanwhile
    monkeypatch.setattr(anki_miner, "POLL_S", 0.1)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"transcribe_hold": 1.0})
    seen = []
    online.fetch(fake_miner.path, "p-surasura", "ja", 7, LINK, on_progress=lambda *a: seen.append(a),
                 source=online.TRANSCRIBE)
    assert (60, online.TRANSCRIBE) in seen, seen
    job = {"state": "picking", "progress": json.dumps({"step": runner.TRANSCRIBING, "percent": 60})}
    assert status._progress(job)["doing"] == "Making its subtitles from the audio (60%)"


# --- review round 1 (Michi-YT2) ------------------------------------------------------------------------------------ #
def test_a_video_it_heard_nothing_in_keeps_youtubes_captions(steps, fake_miner):
    # why (review r1 S4): Anki Miner's "recognised no speech" (music, a quiet video) must never cost the video its cards
    # nor say "couldn't be downloaded": YouTube's captions after all, for that video
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"heard_nothing": True}, speech=HAS_MODEL)
    _video, subtitle = steps.download("ja", JOB, dict(WEB, captions="native auto"))
    sources = [c["episodes"][0]["youtube_subtitle_source"] for c in fake_miner.calls() if c.get("episodes")]
    assert sources == ["transcribe", "captions"] and steps.fetched_with == {"21": "captions"}
    with open(subtitle, encoding="utf-8") as f:
        assert "00:00:01,000" in f.read(), "YouTube's captions"
    steps.drop_online(JOB)
    steps.download("ja", JOB, dict(WEB, captions="native auto"))
    sources = [c["episodes"][0]["youtube_subtitle_source"] for c in fake_miner.calls() if c.get("episodes")]
    assert sources[-1] == "captions", "that video isn't heard again this run"


def test_anki_miner_not_answering_the_speech_question_is_youtubes_captions_never_a_wait(steps, fake_miner,
                                                                                         monkeypatch):
    # why (review r1 S4): before this lane the video came down; a question about a model must never hold it back
    def busy(*a, **k):
        raise anki_miner.AnkiMinerError("timeout", "Anki Miner didn't answer in time.")
    monkeypatch.setattr(anki_miner, "speech_ready", busy)
    steps.download("ja", JOB, dict(WEB, captions="native auto"))
    assert _episode(fake_miner)["youtube_subtitle_source"] == "captions"


def test_a_video_kept_from_before_says_nothing_of_how_it_was_fetched(steps, fake_miner):
    # why (review r1 NIT 7): `_download` reads what THIS fetch asked for; a video kept for the job asks Anki Miner
    # nothing, so it must neither raise the note nor fix it
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={}, speech=HAS_MODEL)
    steps.download("ja", JOB, dict(WEB, captions="native auto"))
    assert steps.fetched_with.pop("21") == "transcribe"
    steps.download("ja", JOB, dict(WEB, captions="native auto"))
    assert steps.fetched_with == {} and fake_miner.commands().count("fetch") == 1


def test_a_transcribing_fetch_gets_the_time_its_audio_takes(fake_miner, monkeypatch):
    # why (review r1 S2): a two-hour video heard by large-v3 on a CPU outlasts the download's two hours
    seen = {}
    real = anki_miner.api

    def api(exe, args, **kw):
        seen[args[0]] = kw.get("timeout")
        return real(exe, args, **kw)
    monkeypatch.setattr(anki_miner, "api", api)
    monkeypatch.setattr(anki_miner, "POLL_S", 0.1)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={})
    online.fetch(fake_miner.path, "p-surasura", "ja", 7, LINK, source=online.TRANSCRIBE)
    assert seen["fetch"] == online.TRANSCRIBE_TIMEOUT > online.FETCH_TIMEOUT
    online.fetch(fake_miner.path, "p-surasura", "ja", 8, LINK)
    assert seen["fetch"] == online.FETCH_TIMEOUT


def test_a_character_cut_at_the_header_read_still_reads_its_kind(tmp_path, monkeypatch):
    # why (review r1 NIT 8): HEAD bytes end inside a 3-byte character (a Chinese body): the head is decoded as a head,
    # never a damaged file, and the header's kind stands
    item = _transcript(tmp_path, monkeypatch, "zh", "native auto")
    path = tmp_path / item["rel_path"]
    raw = path.read_bytes()
    body = "[00:00:09] 這家店的牛肉麵非常有名，每天都有很多人排隊。\n".encode("utf-8")
    pad = online.HEAD - len(raw) - 1
    raw += b"a" * (pad % 3) + body * (pad // len(body) + 2)
    cut = raw[:online.HEAD]
    assert cut.decode("utf-8", "ignore").encode("utf-8") != cut, "the read ends mid-character"
    path.write_bytes(raw)
    assert online.of("zh", item)["captions"] == "native auto"


# --- the transcription becomes the library's transcript (Mattias: "it wants words that aren't even in the video") -- #
WHISPER = ("1\n00:00:01,200 --> 00:00:03,900\n今から皆さんに難しい質問をします\n\n"
           "2\n00:01:05,000 --> 00:01:08,500\n<i>英語学習</i>を続ける方法です\n\n")


def _library_transcript(tmp_path, monkeypatch, kind, timed=True):
    from app import path_utils
    monkeypatch.setattr(path_utils, "get_data_path", lambda language: str(tmp_path / "data"))
    rel = "Processed/ユートのチャンネル - 誰から何も言われずに [pitFobM6z80].txt"
    full = tmp_path / "data" / rel
    full.parent.mkdir(parents=True)
    body = "[00:00:00] 今から皆さんにめちゃくちゃ難しい質問し\n[00:00:02] ます" if timed else "今から皆さんにめちゃくちゃ 難しい質問し"
    full.write_text("\n".join(["誰から何も言われずに1人で英語学習継続できるようになる方法", "ユートのチャンネル | 2024-05-01 | 41:12",
                               f"Captions: Japanese ({kind})", LINK, "", "-" * 60, body]) + "\n", encoding="utf-8")
    side = full.with_name(full.stem + ".surasura.json")
    side.write_text(json.dumps({"video_id": "pitFobM6z80", "url": LINK, "title": "誰から",
                                "cues": [["今から皆さんにめちゃくちゃ難しい質問し", 0]]}, ensure_ascii=False), encoding="utf-8")
    srt = tmp_path / "fetch" / "pitFobM6z80.srt"
    srt.parent.mkdir()
    srt.write_text(WHISPER, encoding="utf-8")
    return rel, full, side, str(srt)


@pytest.mark.parametrize("timed", (True, False))
def test_the_transcription_writes_over_a_transcript_youtubes_recognizer_made(tmp_path, monkeypatch, timed):
    """The words Generate counts, % known and *open its moment* come from what the video really says: the transcript
    takes the transcription's lines (in its own form), its header says so, its sidecar's times follow — and the old
    one is in the trash. A transcribed transcript is asked for a transcription again at its next mining."""
    from app import analyzer
    rel, full, side, srt = _library_transcript(tmp_path, monkeypatch, "native auto", timed)
    assert online.keep_transcript("ja", rel, srt) is True
    text = full.read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines[2] == "Captions: Japanese (transcribed)" and lines[0].startswith("誰から") and lines[3] == LINK
    assert analyzer.caption_kind(text) == analyzer.TRANSCRIBED
    body = analyzer.transcript_body(text)
    if timed:
        assert body == "[00:00:01] 今から皆さんに難しい質問をします\n[00:01:05] 英語学習を続ける方法です\n"
    else:
        assert body == "今から皆さんに難しい質問をします 英語学習を続ける方法です\n"
    assert "めちゃくちゃ" not in text, "YouTube's recognizer's words are gone"
    cues = json.loads(side.read_text(encoding="utf-8"))["cues"]
    assert [c[1] for c in cues] == [1, 65]
    assert os.listdir(tmp_path / "data" / ".trash"), "the old transcript kept in the trash"
    assert online.subtitle_source({"captions": analyzer.caption_kind(text)}) == "transcribe"
    assert online.keep_transcript("ja", rel, srt) is False, "never transcribed twice"


def test_a_persons_captions_or_a_path_outside_the_data_folder_are_never_written(tmp_path, monkeypatch):
    rel, full, _side, srt = _library_transcript(tmp_path, monkeypatch, "manual")
    before = full.read_bytes()
    assert online.keep_transcript("ja", rel, srt) is False and full.read_bytes() == before
    assert online.keep_transcript("ja", "../outside.txt", srt) is False
    assert online.keep_transcript("ja", rel, str(tmp_path / "no.srt")) is False and full.read_bytes() == before


def test_steps_download_writes_the_transcription_over_the_transcript_only_when_it_asked_for_one(steps, fake_miner,
                                                                                                monkeypatch):
    kept = []
    monkeypatch.setattr(online, "keep_transcript", lambda lang, rel, subtitle: kept.append((rel, subtitle)) or True)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={}, speech=HAS_MODEL)
    steps.download("ja", JOB, dict(WEB, captions="native auto", rel="Processed/x [dQw4w9WgXcQ].txt"))
    assert [r for r, _s in kept] == ["Processed/x [dQw4w9WgXcQ].txt"] and kept[0][1].endswith(".srt")
    steps.drop_online(JOB)
    steps.download("ja", JOB, dict(WEB, captions="manual", rel="Processed/x [dQw4w9WgXcQ].txt"))
    assert len(kept) == 1, "a person's captions: nothing written"
    steps.drop_online(JOB)
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={}, speech=NO_MODEL)
    steps.download("ja", JOB, dict(WEB, captions="native auto", rel="Processed/x [dQw4w9WgXcQ].txt"))
    assert len(kept) == 1, "no speech model: YouTube's captions, its transcript as it was"


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


# --- Yt-B: YouTube's bot check holds every YouTube call for a day -------------------------------------------------- #
# Sonic 2026-11-12: "will this hit from my own network and then will I have issues in the future with too many
# requests?" Connect's video is asked from the learner's own address, like the downloader's transcripts: one refusal
# holds both for a day, said with when it tries again; never asked again in that time.
@pytest.mark.parametrize("message", [
    "ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you\u2019re not a bot. Use --cookies-from-browser or --cookies",
    "ERROR: [youtube] dQw4w9WgXcQ: Unable to download webpage: HTTP Error 429: Too Many Requests",
], ids=["bot", "429"])
def test_a_refusal_holds_every_youtube_call_and_says_when(fake_miner, monkeypatch, message):
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch, error="FETCH_FAILED", message=message, transient=True)
    until = youtube_hold.held()
    assert until and raised.value.standing
    assert raised.value.say == youtube_hold.words(until) and youtube_hold.is_words(raised.value.say)
    with pytest.raises(online.Trouble) as again:
        online.fetch(fake_miner.path, "p-surasura", "ja", 8, LINK)
    assert again.value.say == raised.value.say and fake_miner.commands().count("fetch") == 1, \
        "nothing asked of YouTube while the hold runs"


def test_an_age_check_holds_nothing(fake_miner, monkeypatch):
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch, error="YOUTUBE_REFUSED",
               message="Sign in to confirm your age. This video may be inappropriate for some users.")
    assert raised.value.say == online.AGE and youtube_hold.held() is None


def test_a_hold_the_downloader_began_is_met_before_anki_miner_starts(fake_miner, monkeypatch):
    youtube_hold.hold()
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch)
    assert youtube_hold.is_words(raised.value.say) and raised.value.standing
    assert "fetch" not in fake_miner.commands()


def test_a_held_trouble_stops_every_other_fetch_this_run(steps, fake_miner):
    # why (review S4, as offline): every other online episode would only meet the same hold
    fake_miner.plan(app="3.11.0", features=["fetch"], fetch={"error": "FETCH_FAILED", "transient": True,
                                                               "message": "Sign in to confirm you're not a bot"})
    for job in (JOB, dict(JOB, id=22, item_id=6)):
        with pytest.raises(runner.Needs) as raised:
            steps.download("ja", job, WEB)
        assert youtube_hold.is_words(raised.value.say) and raised.value.standing
    assert fake_miner.commands().count("fetch") == 1


def test_a_fetch_waits_its_turn_and_a_stop_ends_the_wait(fake_miner, monkeypatch):
    # why: never two YouTube calls at once from this computer; a Stop never waits behind the window's playlist
    other = locks.take(youtube_hold.LOCK, "the window's playlist", owner=object())     # (another program)
    try:
        monkeypatch.setattr(stopping, "pressed", lambda: True)
        started = time.monotonic()
        with pytest.raises(stopping.Stopped):
            _fetch(fake_miner, monkeypatch)
        assert time.monotonic() - started < QUICK and "fetch" not in fake_miner.commands()
    finally:
        other.release()


def test_a_held_fetch_never_waits_for_the_turn(fake_miner, monkeypatch):
    # why (mutant C4): behind the window's half-hour playlist, Connect would wait all that time to learn it is held
    youtube_hold.hold()
    monkeypatch.setattr(youtube_hold, "turn", lambda *a, **k: pytest.fail("asked for the turn while held"))
    with pytest.raises(online.Trouble) as raised:
        _fetch(fake_miner, monkeypatch)
    assert youtube_hold.is_words(raised.value.say) and "fetch" not in fake_miner.commands()
