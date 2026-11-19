"""Mado-PZ (2026-11-18, a tester's ask: Connect's mining taxes the PC): Anki Miner's circle paused at the bar stops
Connect too — its loop at the next step boundary (`Steps.paused`, read again at every look and before each job, as
D29's switch is), `kick` starts nothing, and the `connect` verb answers `skipped`. Resumed, Connect runs as before. The
jobs it had are kept in the ledger: the next start mines them (nothing is lost).

What a wrong answer would cost: Connect going on making cards — the PC working hard — after the learner paused it to
use the PC for something else; or Connect never coming back after the click that resumes it.

The test's own root and settings.json; no Anki, no Anki Miner; `kick`'s process start replaced.
"""
import subprocess

import pytest

from app.connect import kick, runner
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


@pytest.mark.parametrize("paused, stop", [
    (["miner"], runner.PAUSED),
    (["junban", "arrivals"], None),               # another circle's pause: Connect goes on
    ([], None),
    ("miner", None),                              # a hand-edited value that isn't a list: nothing paused
])
def test_connects_loop_stops_at_its_next_boundary_only_while_anki_miner_is_paused(paused, stop):
    h.write_settings(connect_enabled=True, paused=paused)
    steps = runner.Steps({"connect_enabled": True})
    assert runner._stop(steps) == stop


def test_a_pause_pressed_mid_run_stops_it_at_the_next_look_and_a_resume_lets_the_next_start_run():
    h.write_settings(connect_enabled=True)
    steps = runner.Steps({"connect_enabled": True})
    assert runner._stop(steps) is None
    h.write_settings(connect_enabled=True, paused=["miner"])
    assert runner._stop(steps) == runner.PAUSED, "read again at each boundary, never kept from the run's start"
    h.write_settings(connect_enabled=True, paused=[])
    assert runner._stop(steps) is None


def test_a_stand_in_steps_without_the_pause_look_goes_on():
    class Steps:
        def update_staged(self):
            return False

        def enabled(self):
            return True
    assert runner._stop(Steps()) is None


@pytest.fixture
def starts(monkeypatch):
    """`kick` allowed to start under the test root, its process start recorded instead."""
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a) or "a process")
    monkeypatch.setattr(kick, "running", lambda: False)
    return started


def test_with_anki_miner_paused_kick_starts_nothing_and_resumed_it_starts(starts):
    assert kick.kick({"connect_enabled": True, "paused": ["miner"]}) is None
    assert starts == []
    assert kick.kick({"connect_enabled": True, "paused": ("surasura",)}) == "a process", "another circle's pause"
    assert kick.kick({"connect_enabled": True, "paused": []}) == "a process" and len(starts) == 2


def test_with_anki_miner_paused_a_running_connect_is_not_woken(monkeypatch):
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    monkeypatch.setattr(kick, "running", lambda: True)
    woken = []
    monkeypatch.setattr(kick, "wake", lambda videos=False: woken.append(videos))
    assert kick.kick({"connect_enabled": True, "paused": ["miner"]}) is None and woken == []
    kick.kick({"connect_enabled": True})
    assert woken == [False]


def test_the_connect_verb_answers_skipped_while_anki_miner_is_paused():
    h.write_settings(connect_enabled=True, paused=["miner"])
    code, line = h.call("connect")
    assert code == 0 and line["skipped"] == "paused", line
    h.write_settings(connect_enabled=True, paused=["miner"], logic={"automation": False})
    code, line = h.call("connect")
    assert line["skipped"] == "automation off", "the master switch is said first"


# --- train 45's intent keeper #1: a pause mid-episode is never your Stop ---------------------------------------- #
# What a wrong answer would cost: the episode Anki Miner was making cards for when the learner paused it never made
# again after the resume (it waited for a new *Mine now*, as a Stop does) — its remaining words never get their cards.
from app.connect.ledger import Ledger                                    # noqa: E402
from tests.connect.fake_steps import FakeSteps                           # noqa: E402

EPISODE_WORDS = {
    "ja": [("上層部", "ジョウソウブ"), ("一生懸命", "イッショウケンメイ"), ("走り出す", "ハシリダス")],
    "zh": [("认真", "ren4 zhen1"), ("约定", "yue1 ding4"), ("勇气", "yong3 qi4")],
}


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _queue(ledger, lang, item_id):
    with ledger.transaction():
        return ledger.queue(lang, item_id, "user", None, store_id="store-1")


def _steps(tmp_path, lang, plan_extra=None):
    plan = {"line": {lang: [1]}, "words": {"1": EPISODE_WORDS[lang]}}
    plan.update(plan_extra or {})
    return FakeSteps(str(tmp_path), plan)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_pause_mid_batch_keeps_the_cards_made_and_the_resume_finishes_the_episode(tmp_path, ledger, lang):
    job_id = _queue(ledger, lang, 1)
    paused = []

    def pause(n, _job):
        if n == 1:
            paused.append(True)                 # the click on 鉱, after the batch's first card
    steps = _steps(tmp_path, lang, {"on_word": pause})
    steps.paused = lambda: bool(paused)
    summary = runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job_id)
    first = EPISODE_WORDS[lang][0][0]
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.PAUSED, "mining")
    assert not ledger.is_stopped(job_id) and not ledger.held_by_stop(job), "a pause is no Stop: no stopped mark"
    assert steps.anki.words() == [first], "the cards made before the pause are kept"
    assert summary.get("stopped") == runner.PAUSED
    # the click again: resumed — the next start (the resume's kick) finishes the episode, no new ask
    after = _steps(tmp_path, lang)
    after.paused = lambda: False
    runner.run({}, [lang], steps=after, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert [e[3] for e in after.log if e[0] == "mine"] == [[w for w, _r in EPISODE_WORDS[lang][1:]]], \
        "only the words still unmade, each once"
    assert sorted(after.anki.words()) == sorted(w for w, _r in EPISODE_WORDS[lang])
    assert not ledger.is_stopped(job_id) and not ledger.stop_asked(job_id)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_pause_before_the_episodes_first_step_holds_it_and_the_resume_mines_it_whole(tmp_path, ledger, lang):
    job_id = _queue(ledger, lang, 1)
    steps = _steps(tmp_path, lang, {"switch_off_after": None})
    seen = []

    def paused_once_picking():
        seen.append(True)
        return len(seen) > 1                    # the run's own look passes, the step's watch sees the pause
    steps.paused = paused_once_picking
    runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job_id)
    assert job["state"] == "waiting" and job["reason"] == runner.PAUSED and not ledger.is_stopped(job_id)
    assert not any(e[0] == "mine" for e in steps.log), "nothing mined while paused"
    after = _steps(tmp_path, lang)
    after.paused = lambda: False
    runner.run({}, [lang], steps=after, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert sorted(after.anki.words()) == sorted(w for w, _r in EPISODE_WORDS[lang])


def test_your_stop_while_paused_is_still_your_stop(tmp_path, ledger):
    """A Stop you pressed (the row's) wins over a pause: it waits for your next ask, as before."""
    job_id = _queue(ledger, "ja", 1)

    def press(n, _job):
        if n == 1:
            ledger.ask_stop(job_id)
    steps = _steps(tmp_path, "ja", {"on_word": press})
    steps.paused = lambda: True if ledger.stop_asked(job_id) else False
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job_id)
    assert job["reason"] == runner.STOPPED_BY_YOU and ledger.held_by_stop(job)


def test_steps_reads_the_pause_again_only_when_settings_json_changed(monkeypatch):
    """S19 (train 45's keeper #5): the job's watch asks every second; the file is read again only once it changed."""
    from app.cli import verbs
    h.write_settings(connect_enabled=True, paused=["miner"])
    reads = []
    real = verbs.settings
    monkeypatch.setattr(verbs, "settings", lambda: reads.append(1) or real())
    steps = runner.Steps({"connect_enabled": True})
    assert steps.paused() and steps.paused() and steps.paused()
    assert len(reads) == 1
    import os
    import time
    time.sleep(0.02)
    h.write_settings(connect_enabled=True, paused=[])
    os.utime(os.path.join(h.root(), "settings.json"))
    assert steps.paused() is False and len(reads) == 2
