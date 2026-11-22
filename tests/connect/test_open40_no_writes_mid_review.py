"""OPEN 40 (Sonic, 2026-11-21: yes): a review in Anki ends Connect's running Anki Miner batch at its next card.

Measured first (Haya-LD2's review bench, DevTest): every card Anki Miner writes while you review redraws the card you're
looking at back to its question side — 46 re-shows in 12 cards — and its clip cuts slow each card (+150 ms). E2 already
held every NEW batch while you review; a batch already running when the review began kept writing until its end. Now
the mine call looks at the review every PAUSE_LOOK_S and, once one is on, writes the run's cancel file as *Stop* does:
Anki Miner ends at its next card, every card it made whole and recorded, none sent twice. Unlike *Stop*, the job only
waits: *Waiting while you review in Anki.*, resumed at mining once the review is over — never a stop, never a failure.

What a wrong answer costs: the card under review flipping back while you answer; a review counted as Anki Miner failing
(two of those fail the episode); the episode stopped until a *Mine now* instead of going on by itself; the same card made
twice when it goes on; a learner's *Stop* turned into a wait.

Against the fake Anki Miner (`--api` as API.md documents it), `FakeSteps` (real Japanese words) and a real ledger.
Never a live Anki.
"""
import os

import pytest

from app.connect import anki_miner, runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps
from tests.connect.test_anki_miner import batch, words  # noqa: F401  (fixtures)


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _queue(ledger, item_id):
    with ledger.transaction():
        return ledger.queue("ja", item_id, "user", None, store_id="store-1")


def _cancel_file(done_or_dir):
    return os.path.join(done_or_dir, "job-1-1", "cancel")


# --- the Anki Miner call ------------------------------------------------------------------------------------------- #
def test_a_review_beginning_during_the_call_ends_it_at_the_next_card_and_keeps_what_was_made(
        batch, fake_miner, words, monkeypatch):  # noqa: F811
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    monkeypatch.setattr(anki_miner, "PAUSE_LOOK_S", 0.0)
    fake_miner.plan(cancel_at=2)                    # the fake reads its cancel file before its third card
    done = batch(should_stop=lambda: False, should_pause=lambda: True)
    assert done["paused"] is True, "a review ended the batch"
    assert done["stopped"] is False, "a review is never your Stop"
    outcomes = [o["outcome"] for o in done["outcomes"]]
    assert outcomes[:2] == ["made", "made"], "the cards written before the review stay, whole"
    assert all(o in runner.UNSETTLED for o in outcomes[2:]), "the rest wait: never counted as turned down"
    assert not os.path.exists(_cancel_file(os.path.dirname(done["run_file"]))), "the call over: no cancel file left"


def test_a_review_before_anything_reached_anki_is_a_cancelled_refusal_marked_paused(batch, fake_miner, monkeypatch):  # noqa: F811
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    monkeypatch.setattr(anki_miner, "PAUSE_LOOK_S", 0.0)
    fake_miner.plan(cancel_at=0)
    with pytest.raises(anki_miner.AnkiMinerError) as raised:
        batch(should_pause=lambda: True)
    assert raised.value.kind == "cancelled"
    assert raised.value.paused is True and raised.value.stopped is False


def test_your_stop_wins_over_a_review(batch, fake_miner, words, monkeypatch):  # noqa: F811
    # both at once: the episode stops (it waits for a newer *Mine now*), never only waits for the review's end
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    monkeypatch.setattr(anki_miner, "PAUSE_LOOK_S", 0.0)
    fake_miner.plan(cancel_at=2)
    done = batch(should_stop=lambda: True, should_pause=lambda: True)
    assert done["stopped"] is True and done["paused"] is False


def test_no_review_is_the_call_as_before(batch, fake_miner, words, monkeypatch):  # noqa: F811
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    monkeypatch.setattr(anki_miner, "PAUSE_LOOK_S", 0.0)
    looks = []
    done = batch(should_stop=lambda: False, should_pause=lambda: looks.append(1) or False)
    assert looks, "the review was looked at while the call ran"
    assert done["paused"] is False and done["stopped"] is False
    assert all(o["outcome"] == "made" for o in done["outcomes"])


def test_the_review_is_looked_at_once_per_pause_look_not_at_every_poll(batch, fake_miner, words, monkeypatch):  # noqa: F811
    # each look is a call to AnkiConnect on Anki's own thread: at most one every PAUSE_LOOK_S, however fast the poll
    monkeypatch.setattr(anki_miner, "POLL_S", 0.02)
    monkeypatch.setattr(anki_miner, "PAUSE_LOOK_S", 30.0)
    fake_miner.plan(slow={"mine": 0.4})            # a call long enough for ~20 polls
    looks = []
    batch(should_pause=lambda: looks.append(1) or False)
    assert len(looks) == 1


# --- Connect's run ------------------------------------------------------------------------------------------------- #
def test_a_review_mid_batch_keeps_the_cards_made_waits_and_then_makes_only_the_rest(tmp_path, ledger):
    job_id = _queue(ledger, 1)
    plan = {"line": {"ja": [1]}, "review_at": 1}    # the review begins as the batch's second card comes up
    steps = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.REVIEWING, "mining")
    first = WORDS[1][0][0]
    outcomes = {o["word"]: o["outcome"] for o in ledger.outcomes(job_id)}
    assert outcomes[first] == "made" and steps.anki.words() == [first]
    assert ("by_tag", 1) in steps.log, "a batch a review ended is read back by the job's tag"
    assert (job["failures"] or 0) == 0, "a review is no failure of Anki Miner's"
    # the review over: the next run sends only the words still unmade, by itself (no *Mine now*); one card a word
    plan.pop("review_at")
    steps2 = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps2, ledger=ledger, sleep=lambda s: None, looks=1)
    assert [e[3] for e in steps2.log if e[0] == "mine"] == [[w for w, _r in WORDS[1][1:]]]
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert sorted(steps2.anki.words()) == sorted(w for w, _r in WORDS[1])


def test_a_review_at_the_last_card_lets_the_job_finish(tmp_path, ledger):
    # the cancel came after every word was made: the episode is finished, never held at mining with nothing left
    job_id = _queue(ledger, 1)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}})
    real = steps.mine
    steps.mine = lambda *a: dict(real(*a), paused=True)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["state"] == "done"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_connects_mine_step_asks_anki_whether_you_review(monkeypatch, lang):
    # the real step's look: AnkiConnect's guiReviewActive at Connect's own address (E2's look), handed to the call
    from app import anki_connect
    from tests.connect.test_light_mining_load import _mine_step
    seen = _mine_step(monkeypatch, {}, lang=lang)
    asked = []
    monkeypatch.setattr(anki_connect, "reviewing", lambda url, cancel=None: asked.append(url) or True)
    assert seen["should_pause"]() is True
    assert asked == [runner.Steps({}).url]
