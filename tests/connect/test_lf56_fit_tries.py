"""LF56-1 (Sonic 2026-10-23, after row 56: "One thing about the 4%, unsure"): the likeliest cause of an episode that
went from *Checking the timing* back to the hourglass and never mined — tsubasa's timing check timing out on this PC
(TIMEOUT_S) at every look, each answer RETRY, so Connect waited and asked again for ever, saying only "asks again".

Now the hourglass's words name the cause and the try ("Checking its timing took longer than 2 minutes …, try 1 of
3"), and after FIT_TRIES looks running with no answer the episode is named once in *Needs you* as not timed, where
*Mine anyway* mines it at its subtitle's times. A check that answers forgets the count.

What a wrong answer would cost: an episode stuck at the hourglass with no reason (Sonic's laptop), or an episode
given up on after one slow look. Real fit-check code (`fit_check.fit`) with a tsubasa stand-in that times out; Anki
and Anki Miner are `FakeSteps`' — never a live Anki.
"""
import json
import subprocess

import pytest

from app.connect import actions, feed, fit_check, runner, status
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps
from tests.connect_helpers import tsubasa_answer

VIDEO = "C:/Video/上層部の話 01.mkv"
SUBTITLE = "C:/Subs/上層部の話 01.srt"


class SlowCheck(FakeSteps):
    """FakeSteps whose fit check is the real one, over a tsubasa that times out while `slow` is set."""

    slow = True

    def fit(self, lang, job, pairing, video, subtitle):
        self.log.append(("fit", job["item_id"]))

        def run(command, **kw):
            if self.slow:
                raise subprocess.TimeoutExpired(command, kw.get("timeout"))
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(tsubasa_answer()))
        return fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=run)


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _queue(ledger, item_id):
    with ledger.transaction():
        return ledger.queue("ja", item_id, "user", None, store_id="store-1")


def _look(steps, ledger):
    return runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)


def test_a_timing_check_that_keeps_timing_out_says_so_then_is_named_not_timed_after_three_looks(tmp_path, ledger,
                                                                                                monkeypatch):
    monkeypatch.setattr(status, "running", lambda: True)
    job_id = _queue(ledger, 1)
    steps = SlowCheck(str(tmp_path), {"line": {"ja": [1]}})
    for tries in (1, 2):
        _look(steps, ledger)
        job = ledger.job_by_id(job_id)
        assert job["state"] == "waiting", job
        assert "took longer than 2 minutes" in job["reason"] and f"(try {tries} of 3)" in job["reason"]
        item = feed.build(status.read(["ja"], path=str(tmp_path / "ledger.sqlite")), "ja").items[1]
        assert item.tip == job["reason"], "the hourglass's hover names the cause"
    _look(steps, ledger)
    needs = [n for n in ledger.needs("ja") if n["kind"] == "not-timed"]
    assert len(needs) == 1 and "3 looks running" in needs[0]["say"] and "Mine anyway" in needs[0]["say"], needs
    assert not any(e[0] == "mine" for e in steps.log), "nothing mined while the timing is unknown"
    # *Mine anyway* mines it at its subtitle's times, tsubasa not asked again
    assert actions.mine_anyway("ja", needs[0]["id"], path=str(tmp_path / "ledger.sqlite"))
    fits = len([e for e in steps.log if e[0] == "fit"])
    _look(steps, ledger)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert len([e for e in steps.log if e[0] == "fit"]) == fits


def test_a_check_that_answers_forgets_the_count(tmp_path, ledger):
    job_id = _queue(ledger, 1)
    steps = SlowCheck(str(tmp_path), {"line": {"ja": [1]}})
    _look(steps, ledger)
    _look(steps, ledger)
    assert "(try 2 of 3)" in ledger.job_by_id(job_id)["reason"]
    steps.slow = False
    _look(steps, ledger)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert ledger.conn.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'fit_try:%'").fetchone()[0] == 0


def test_a_tsubasa_that_wont_start_says_so_in_plain_words():
    def run(command, **kw):
        raise OSError("not a program")
    verdict, who, why, _offset = fit_check.fit(None, VIDEO, SUBTITLE, tsubasa="tsubasa", run=run)
    assert (verdict, who) == (fit_check.RETRY, "tsubasa")
    assert why.startswith("tsubasa couldn't check its timing this time (OSError)")
    assert fit_check._span(120) == "2 minutes" and fit_check._span(60) == "1 minute" and fit_check._span(90) == \
        "90 seconds"
