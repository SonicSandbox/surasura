"""Michi-YT (Sonic 2026-11-07: "Obviously it needs to download the video … Once extracted the video is deleted."): an
online title's episode in the top 20 is mined like an episode — its video and captions downloaded for the job, the
words picked from those captions, the cards cut from that video — and the video is gone as soon as its clips and
pictures are made, and whenever the job ends short of that: your Stop, a failure, a wait, an update, an error, and
whatever a killed Connect left (the sweep at a run's start and end).

What a wrong answer costs: a learner's disk filling with videos nobody asked to keep (a top 20 of YouTube videos is
gigabytes), a video left behind in a folder the learner never sees, or an online title that never makes a card.

Against `FakeSteps` (real Japanese words, the store and Anki stood in for) with the download's own steps added; the
downloaded "video" is a small real file in the test's folder. Never a live Anki, never the network.
"""
import os
import shutil

import pytest

from app.connect import online, runner, stopping
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

LINK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
NAMES = ["ゆっくり日本語 - 毎日の会話 (playlist)", "ゆっくり日本語 - 第3話 天気の話 [dQw4w9WgXcQ]"]
CAPTIONS = "1\n00:00:01,000 --> 00:00:03,500\n今日は一生懸命に走り出す\n"


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


class OnlineSteps(FakeSteps):
    """FakeSteps whose items in the plan's `online` are online titles: `download` writes a real video and captions
    into `<folder>/online/v<job>/fetch-1/` (or raises the plan's `download_fails` {item: ("standing" | "own" |
    "stop" | "update", words)}), `drop_online` / `sweep_online` remove them, and every step notes whether the video
    is on disk then (`seen`: (step, item, there))."""

    def __init__(self, folder, plan=None, child=False):
        super().__init__(folder, plan, child)
        self.seen = []

    def _place(self, job):
        return os.path.join(self.folder, "online", f"v{job['id']}")

    def _there(self, job):
        return os.path.isdir(self._place(job))

    def online(self, lang, job):
        if job["item_id"] not in (self.plan.get("online") or ()):
            return None
        return {"site": "youtube", "url": LINK, "names": list(NAMES)}

    def download(self, lang, job, web, on_progress=None):
        out = os.path.join(self._place(job), "fetch-1")
        kept = os.path.join(out, "dQw4w9WgXcQ.mp4")
        if os.path.isfile(kept) and not (self.plan.get("download_fails") or {}).get(str(job["item_id"])):
            return kept, os.path.join(out, "dQw4w9WgXcQ.ja.srt")       # as Steps.download: kept for this run
        self.log.append(("download", job["item_id"]))
        os.makedirs(out, exist_ok=True)
        video, subtitle = os.path.join(out, "dQw4w9WgXcQ.mp4"), os.path.join(out, "dQw4w9WgXcQ.ja.srt")
        with open(video, "w", encoding="utf-8") as f:
            f.write("a fetched video")
        with open(subtitle, "w", encoding="utf-8") as f:
            f.write(CAPTIONS)
        if on_progress is not None:
            on_progress(40)
        fails = (self.plan.get("download_fails") or {}).get(str(job["item_id"]))
        if fails is not None:
            kind, words = fails
            if kind == "stop":
                raise stopping.Stopped()
            if kind == "update":
                raise runner.Wait(runner.STOPPED_FOR_UPDATE, look=False)
            raise runner.Needs(online.KIND, words, standing=kind == "standing", once=kind == "own")
        return video, subtitle

    def drop_online(self, job):
        self.log.append(("drop", job["item_id"]))
        shutil.rmtree(self._place(job), ignore_errors=True)

    def sweep_online(self):
        self.log.append(("sweep",))
        shutil.rmtree(os.path.join(self.folder, "online"), ignore_errors=True)

    def pick(self, lang, job, video, subtitle=None):
        self.log.append(("pick-from", job["item_id"], subtitle))
        self.seen.append(("pick", job["item_id"], self._there(job)))
        return super().pick(lang, job, video)

    def mine(self, lang, job, picked, words, attempt):
        self.seen.append(("mine", job["item_id"], os.path.isfile(picked.get("video") or "")))
        self.log.append(("names", job["item_id"], picked.get("names")))
        return super().mine(lang, job, picked, words, attempt)

    def fill(self, lang, job, note_ids):
        self.seen.append(("fill", job["item_id"], self._there(job)))
        return super().fill(lang, job, note_ids)


def _run(tmp_path, ledger, plan, looks=1, steps=None):
    steps = steps or OnlineSteps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}, "online": [1]},
                                                     **plan))
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=looks)
    return steps, summary


def _online_left(tmp_path):
    here = os.path.join(str(tmp_path), "online")
    return sorted(os.listdir(here)) if os.path.isdir(here) else []


# --- the success path ---------------------------------------------------------------------------------------------- #
def test_an_online_episode_is_downloaded_mined_from_its_own_captions_and_its_video_gone_before_filling(tmp_path,
                                                                                                    ledger):
    # why: the one path Sonic asked for — the video there while Anki Miner cuts the cards, gone right after
    steps, summary = _run(tmp_path, ledger, {})
    assert summary["languages"]["ja"]["done"] == [1], summary
    order = [e[0] for e in steps.log if e[0] in ("download", "pick-from", "mine", "drop", "fill")]
    assert order[:3] == ["download", "pick-from", "mine"], order
    assert order.index("drop") < order.index("fill"), "the video goes as soon as the cards are made, before filling"
    picked_from = next(e[2] for e in steps.log if e[0] == "pick-from")
    assert picked_from and picked_from.endswith(".ja.srt"), "the words are picked from the captions it came with"
    assert ("mine", 1, True) in steps.seen, "the video is on disk while Anki Miner cuts the clips and pictures"
    assert ("fill", 1, False) in steps.seen, "and gone by the time Backfill fills the cards"
    assert _online_left(tmp_path) == [], "no video left behind"
    assert ("names", 1, NAMES) in steps.log, "its cards' Source names the transcript, never the fetched file"
    assert not ledger.needs("ja"), "nothing for you to do"


def test_an_online_episode_is_never_no_video_nor_fit_checked_by_tsubasa(tmp_path, ledger):
    # why: before this lane every YouTube title waited on *No video* for ever; its captions are its video's own
    steps, summary = _run(tmp_path, ledger, {"videos": {"1": None}, "verdict": "not-timed"})
    assert summary["languages"]["ja"]["done"] == [1], summary
    assert not any(e[0] == "fit" for e in steps.log), "the fetched captions are timed to that video: no check"
    assert runner.NO_VIDEO not in summary["languages"]["ja"]["waiting"].values()


def test_a_video_that_is_no_online_title_is_mined_as_before(tmp_path, ledger):
    # why: the online path is only an online title's; an ordinary episode never downloads anything
    steps, summary = _run(tmp_path, ledger, {"online": []})
    assert summary["languages"]["ja"]["done"] == [1]
    assert not any(e[0] == "download" for e in steps.log)
    assert ("fit", 1) in steps.log


# --- every way a job ends short: the video goes ------------------------------------------------------------------- #
def test_a_stop_while_its_video_downloads_leaves_no_video_and_waits_for_your_ask(tmp_path, ledger):
    # why: Stop is quick and leaves nothing behind (Michi-X's rule: the download is ended within a second)
    steps, summary = _run(tmp_path, ledger, {"download_fails": {"1": ("stop", None)}})
    job = ledger.jobs("ja")[0]
    assert job["state"] == "waiting" and job["reason"] == runner.STOPPED_BY_YOU, job
    assert ("drop", 1) in steps.log and _online_left(tmp_path) == []
    assert not any(e[0] == "mine" for e in steps.log), "nothing mined from a download you stopped"


def test_an_update_staged_mid_download_drops_the_video(tmp_path, ledger):
    # why: an update never waits on a download, and never leaves its video behind
    steps, summary = _run(tmp_path, ledger, {"download_fails": {"1": ("update", None)}})
    job = ledger.jobs("ja")[0]
    assert job["state"] == "waiting" and job["reason"] == runner.STOPPED_FOR_UPDATE, job
    assert _online_left(tmp_path) == []


def test_a_wait_while_mining_drops_the_video_and_the_next_run_downloads_it_again(tmp_path, ledger):
    # why: a video is kept only while its job is worked on; a re-mine downloads again (Sonic's rule)
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "online": [1], "miner_busy": True}
    steps = OnlineSteps(str(tmp_path), plan)
    _run(tmp_path, ledger, plan, steps=steps)
    assert ledger.jobs("ja")[0]["reason"] == runner.ANKI_MINER_OPEN
    assert _online_left(tmp_path) == [], "the wait leaves no video"
    steps.plan["miner_busy"] = False
    _run(tmp_path, ledger, plan, steps=steps)
    assert [e for e in steps.log if e[0] == "download"] == [("download", 1), ("download", 1)], "downloaded again"
    assert ledger.jobs("ja")[0]["state"] == "done"
    assert _online_left(tmp_path) == []


def test_a_job_that_ends_on_an_error_drops_its_video(tmp_path, ledger):
    # why: R15's fault path (an error nobody planned for) leaves no video either
    steps, summary = _run(tmp_path, ledger, {"pick_error": [1]})
    assert ("drop", 1) in steps.log and _online_left(tmp_path) == []
    assert any(n["kind"] == "error" for n in ledger.needs("ja"))


def test_a_job_that_fails_mining_drops_its_video(tmp_path, ledger):
    # why: Anki Miner crashing twice ends the job failed — and its video goes with it
    steps, summary = _run(tmp_path, ledger, {"crash_mid_batch": 0, "crash_always": True})
    assert summary["languages"]["ja"]["failed"] == [1], summary
    assert _online_left(tmp_path) == []


def test_a_run_sweeps_what_a_killed_connect_left_at_its_start_and_its_end(tmp_path, ledger):
    # why: a Connect killed mid-download (app exit, a crash) can't run its finally: the next run's start takes it
    left = os.path.join(str(tmp_path), "online", "v77", "fetch-1")
    os.makedirs(left)
    with open(os.path.join(left, "old.mp4"), "w", encoding="utf-8") as f:
        f.write("left by a killed run")
    steps, summary = _run(tmp_path, ledger, {"online": [], "queue": {"ja": []}})
    sweeps = [n for n, e in enumerate(steps.log) if e == ("sweep",)]
    assert len(sweeps) == 2 and sweeps[0] == 1, steps.log[:3]     # right after `lower`, and again at the end
    assert _online_left(tmp_path) == []


# --- troubles: said once, never a crash --------------------------------------------------------------------------- #
def test_the_languages_own_trouble_is_one_needs_you_line_and_other_episodes_go_on(tmp_path, ledger):
    # why: yt-dlp missing is said once for the language, not once per video — and the ordinary episode still mines
    say = online.NO_YTDLP
    plan = {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}, "online": [1, 2],
            "download_fails": {"1": ("standing", say), "2": ("standing", say)}}
    steps, summary = _run(tmp_path, ledger, plan, steps=OnlineSteps(str(tmp_path), plan))
    needs = [n for n in ledger.needs("ja") if n["kind"] == online.KIND]
    assert len(needs) == 1 and needs[0]["item_id"] is None and needs[0]["say"] == say, needs
    assert summary["languages"]["ja"]["done"] == [3], "the episode with a video of its own goes on"
    assert {j["item_id"]: j["reason"] for j in ledger.jobs("ja") if j["state"] == "waiting"} == {1: say, 2: say}
    assert _online_left(tmp_path) == []


def test_a_videos_own_trouble_is_said_once_for_its_episode_however_many_runs(tmp_path, ledger):
    # why: a private video is said in plain words on its row and once in Needs you — not again at every start
    say = f"Example Show - 01: {online.PRIVATE}"
    plan = {"download_fails": {"1": ("own", say)}}
    steps = OnlineSteps(str(tmp_path), dict({"line": {"ja": [1]}, "queue": {"ja": [1]}, "online": [1]}, **plan))
    for _ in range(2):
        _run(tmp_path, ledger, plan, steps=steps)
    needs = [n for n in ledger.needs("ja") if n["kind"] == online.KIND]
    assert [(n["item_id"], n["say"]) for n in needs] == [(1, say)], needs
    assert ledger.jobs("ja")[0]["reason"] == say
    assert _online_left(tmp_path) == []


def test_a_trouble_that_went_away_is_fixed_by_itself(tmp_path, ledger):
    # why: once a video comes down, the language's download trouble (no yt-dlp, offline) leaves Needs you
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "online": [1],
            "download_fails": {"1": ("standing", online.OFFLINE)}}
    steps = OnlineSteps(str(tmp_path), plan)
    _run(tmp_path, ledger, plan, steps=steps)
    assert [n["say"] for n in ledger.needs("ja")] == [online.OFFLINE]
    steps.plan["download_fails"] = {}
    _run(tmp_path, ledger, plan, steps=steps)
    assert ledger.jobs("ja")[0]["state"] == "done"
    assert not ledger.needs("ja"), "fixed by itself once a video came down"


def test_on_battery_nothing_is_downloaded(tmp_path, ledger):
    # why: mains power only, as any mining (power.py): a download is no exception
    steps, summary = _run(tmp_path, ledger, {"blocked": runner.ON_BATTERY})
    assert not any(e[0] == "download" for e in steps.log)
    assert ledger.jobs("ja")[0]["reason"] == runner.ON_BATTERY


class UnpluggedSteps(OnlineSteps):
    """Plugged in when the language's pass starts, on battery from the next look at it (the job's own)."""

    def blocked(self, lang):
        looks = sum(1 for e in self.log if e[0] == "blocked")
        self.log.append(("blocked", lang))
        return runner.ON_BATTERY if looks >= 1 else None


def test_unplugged_after_the_pass_began_nothing_is_downloaded(tmp_path, ledger):
    # why: the battery is asked again right before a download (gigabytes on a laptop's battery), as before each batch
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "online": [1]}
    steps, summary = _run(tmp_path, ledger, plan, steps=UnpluggedSteps(str(tmp_path), plan))
    assert not any(e[0] == "download" for e in steps.log)
    assert ledger.jobs("ja")[0]["reason"] == runner.ON_BATTERY


# --- a job resumed in a later run, its video dropped: fetched again, never mined from a missing file ------------- #
def test_a_job_resumed_at_mining_whose_video_was_dropped_is_picked_and_downloaded_again(tmp_path, ledger):
    # why: the ledger keeps the old video's path; mining from it would be a crash, so the job picks again
    gone = os.path.join(str(tmp_path), "online", "v1", "fetch-1", "dQw4w9WgXcQ.mp4")
    with ledger.transaction():
        ledger.queue("ja", 1, "user", None, store_id="store-1")
    job = ledger.jobs("ja")[0]
    ledger.set_state(job["id"], "mining", picked={"words": [{"word": "天気", "reading": "テンキ", "line_start": 1.0}],
                                                  "video": gone, "subtitle": gone, "online": "youtube",
                                                  "names": NAMES, "pairing": None, "profile": "p1"})
    with pytest.raises(runner.Repick):
        runner._mine(OnlineSteps(str(tmp_path), {}), ledger, "ja", ledger.job_by_id(job["id"]))
    ledger.set_state(job["id"], "fit-check")
    with pytest.raises(runner.Repick):
        runner._fit(OnlineSteps(str(tmp_path), {}), ledger, "ja", ledger.job_by_id(job["id"]))
    ledger.set_state(job["id"], "waiting", reason=runner.ANKI_CLOSED, resume="mining")
    steps, summary = _run(tmp_path, ledger, {"queue": {"ja": []}})
    assert ("download", 1) in steps.log and ledger.jobs("ja")[0]["state"] == "done"
    assert _online_left(tmp_path) == []


# --- review round 1 ------------------------------------------------------------------------------------------------ #
class BusyOnceSteps(OnlineSteps):
    """Anki Miner's window open at the first mine call (a wait Connect looks at again), closed by the next look."""

    def mine(self, lang, job, picked, words, attempt):
        if not self.plan.pop("busy_done", False) and not getattr(self, "_was_busy", False):
            self._was_busy = True
            raise runner.Wait(runner.ANKI_MINER_OPEN)
        return super().mine(lang, job, picked, words, attempt)


def test_a_wait_looked_at_again_keeps_the_video_for_that_look_never_downloads_it_again(tmp_path, ledger):
    # why (review M1): a 2-minute wait (Anki Miner's window open) must not fetch the whole video again at each look
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "online": [1]}
    steps = BusyOnceSteps(str(tmp_path), plan)
    _run(tmp_path, ledger, plan, looks=2, steps=steps)
    assert [e for e in steps.log if e[0] == "download"] == [("download", 1)], "one download for the two looks"
    assert ledger.jobs("ja")[0]["state"] == "done"
    assert _online_left(tmp_path) == [], "gone once mined, and the run's end sweeps anything left"


def test_a_videos_own_trouble_once_seen_never_counts_again_at_the_next_start(tmp_path, ledger):
    # why (review M2): a private video in the top 20 would light the badge at every start after you looked at it
    say = f"Example Show - 01: {online.PRIVATE}"
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "online": [1], "download_fails": {"1": ("own", say)}}
    steps = OnlineSteps(str(tmp_path), plan)
    _run(tmp_path, ledger, plan, steps=steps)
    ledger.mark_seen([n["id"] for n in ledger.needs("ja")])
    _run(tmp_path, ledger, plan, steps=steps)
    assert not ledger.needs("ja", unseen=True), "seen once: not counted again while it stands"
    assert [n["say"] for n in ledger.needs("ja")] == [say], "still listed"
