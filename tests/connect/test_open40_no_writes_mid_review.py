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
import time

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
    monkeypatch.setattr(anki_connect, "reviewing", lambda url, cancel=None: asked.append((url, cancel.is_set())) or True)
    assert seen["should_pause"]() is True
    assert asked == [(runner.Steps({}).url, True)], "asked once, never waiting out a busy Anki"


# --- edge cases (Sonic's yes, 2026-11-21: "just double check edge cases"; Haya-LD's register §11 lists each) ------ #
class _Anki:
    """AnkiConnect's two review reads as `anki_connect.invoke` sees them: the reviewer open or not, its card."""

    def __init__(self):
        self.active, self.card, self.busy, self.asked = False, 1001, False, []

    def invoke(self, action, url, timeout=30, **params):
        from app import anki_connect
        self.asked.append(action)
        if self.busy:
            e = anki_connect.AnkiError("A collection operation is active.")
            e.busy = True
            raise e
        if action == "guiReviewActive":
            return self.active
        if action == "guiCurrentCard":
            return {"cardId": self.card} if self.active and self.card is not None else None
        raise AssertionError(action)


@pytest.fixture
def anki(monkeypatch):
    from app import anki_connect
    fake, now, real = _Anki(), [0.0], time.monotonic
    monkeypatch.setattr(anki_connect, "invoke", fake.invoke)
    monkeypatch.setattr(anki_connect.time, "monotonic", lambda: real() + now[0])     # real time, moved on by a test
    monkeypatch.setattr(anki_connect, "_review_card", {})
    fake.now = now
    return fake


URL = "http://127.0.0.1:8765"


def test_2_a_card_left_open_stops_counting_as_a_review_after_the_idle_rule(anki):
    # a reviewer left on one card overnight must not hold card making forever (REVIEW_IDLE_S, PROVISIONAL 10 min)
    from app import anki_connect
    anki.active = True
    assert anki_connect.reviewing(URL) is True
    anki.now[0] += anki_connect.REVIEW_IDLE_S - 1
    assert anki_connect.reviewing(URL) is True, "still inside the idle rule"
    anki.now[0] += 2
    assert anki_connect.reviewing(URL) is False, "the same card past the rule: no review"
    anki.card = 1002                                # you answer it: the next card is a review again, its own clock
    assert anki_connect.reviewing(URL) is True
    anki.now[0] += anki_connect.REVIEW_IDLE_S - 1
    assert anki_connect.reviewing(URL) is True


def test_2_a_review_that_ended_starts_its_own_clock_next_time(anki):
    from app import anki_connect
    anki.active = True
    anki_connect.reviewing(URL)
    anki.now[0] += anki_connect.REVIEW_IDLE_S + 5
    anki.active = False
    assert anki_connect.reviewing(URL) is False
    anki.active = True                              # the same card opened again later: a fresh review
    assert anki_connect.reviewing(URL) is True


def test_2_a_card_anki_doesnt_name_keeps_the_review_as_before(anki):
    from app import anki_connect
    anki.active, anki.card = True, None
    anki_connect.reviewing(URL)
    anki.now[0] += anki_connect.REVIEW_IDLE_S * 3
    assert anki_connect.reviewing(URL) is True, "never idle on a guess"


def test_2_no_review_asks_nothing_more_than_before(anki):
    # the idle rule's read only while the reviewer is open: one request when nobody reviews, as before
    from app import anki_connect
    assert anki_connect.reviewing(URL) is False
    assert anki.asked == ["guiReviewActive"]


def test_3_anki_closed_mid_review_is_no_review_and_the_batch_goes_on(batch, fake_miner, words, monkeypatch):  # noqa: F811
    # Anki gone (closed, crashed): the one check says no review at once; Anki Miner's own write then fails the way it
    # always has (anki-closed: the job waits for Anki), never a pause that waits for a review that can't end
    from app import anki_connect
    began = time.monotonic()
    assert anki_connect.reviewing("http://127.0.0.1:9") is False
    assert time.monotonic() - began < 5
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    monkeypatch.setattr(anki_miner, "PAUSE_LOOK_S", 0.0)

    def boom():
        raise OSError("Anki went away")
    done = batch(should_pause=boom)                 # a look that fails never stops the call (stopping.wait's rule)
    assert done["paused"] is False and all(o["outcome"] == "made" for o in done["outcomes"])


def test_5_anki_busy_with_its_sync_is_no_review_and_the_mine_calls_look_never_waits(anki, monkeypatch):
    # Anki's own sync (a collection operation): no reviewer is open; Connect's look in the mine call asks once and
    # goes on (a Stop pressed meanwhile is read at the next poll, never 20 s later); Anki refuses the write itself
    # while it syncs (Anki Miner's `anki-busy`: the job waits, runner._miner_wait_or_needs)
    from app import anki_connect
    anki.busy = True
    began = time.monotonic()
    assert runner.Steps({})._reviewing() is False
    assert anki.asked == ["guiReviewActive"], "asked once, never waited out"
    monkeypatch.setattr(anki_connect, "BUSY_WAIT_S", 0.3)
    monkeypatch.setattr(anki_connect, "BUSY_POLL_S", 0.1)
    assert anki_connect.reviewing(URL) is False, "the other writers' look waits it out, then no review"
    del began


def test_8_two_quick_reviews_lose_nothing_and_make_every_card_once(tmp_path, ledger):
    job_id = _queue(ledger, 1)
    plan = {"line": {"ja": [1]}, "review_at": 1}
    runner.run({}, ["ja"], steps=FakeSteps(str(tmp_path), plan), ledger=ledger, sleep=lambda s: None, looks=1)
    plan["review_at"] = 0                           # a second review at once, before any card of the rest
    steps2 = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps2, ledger=ledger, sleep=lambda s: None, looks=1)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.REVIEWING)
    assert (job["failures"] or 0) == 0
    plan.pop("review_at")
    steps3 = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps3, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["state"] == "done"
    made = [o["word"] for o in ledger.outcomes(job_id) if o["outcome"] == "made"]
    assert sorted(made) == sorted(w for w, _r in WORDS[1]), "every word made, none lost"
    assert sorted(steps3.anki.words()) == sorted(set(steps3.anki.words())), "none made twice"


def test_10_undo_of_a_batch_a_review_paused_is_refused_until_its_cards_are_made(tmp_path, ledger):
    # the job waits (open): *Undo this batch* says it's still being made and deletes nothing
    from app.connect import undo
    job_id = _queue(ledger, 1)
    runner.run({}, ["ja"], steps=FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "review_at": 1}), ledger=ledger,
               sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["reason"] == runner.REVIEWING
    with pytest.raises(undo.Refused) as err:
        undo.plan(None, ledger, job_id)
    assert err.value.say == undo.STILL_RUNNING
    assert [o["outcome"] for o in ledger.outcomes(job_id)].count("made") == 1, "its card stays recorded"


def test_3_a_hung_review_look_never_delays_your_stop(batch, fake_miner, words, monkeypatch):  # noqa: F811
    # review (Haiku contract #2): Anki hung answers a look in seconds; the look runs beside the poll, so a Stop
    # pressed meanwhile is written at the next poll as before
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    monkeypatch.setattr(anki_miner, "PAUSE_LOOK_S", 0.0)
    fake_miner.plan(cancel_at=2)
    began = time.monotonic()

    def hung():
        time.sleep(4)
        return False
    done = batch(should_stop=lambda: time.monotonic() - began > 0.2, should_pause=hung)
    assert done["stopped"] is True and done["paused"] is False
    assert time.monotonic() - began < 3.5, "the Stop wasn't held behind the hung look"


def test_2_a_card_no_look_saw_for_the_rule_starts_its_clock_again(anki):
    # review (Haiku state #1): a review closed while nobody looked, opened again on the same card hours later, is a
    # fresh review — never idle at its first look
    from app import anki_connect
    anki.active = True
    anki_connect.reviewing(URL)
    anki.now[0] += anki_connect.REVIEW_IDLE_S * 4
    assert anki_connect.reviewing(URL) is True


def test_2_anki_gone_forgets_the_card(anki, monkeypatch):
    from app import anki_connect
    anki.active = True
    anki_connect.reviewing(URL)
    assert URL in anki_connect._review_card
    monkeypatch.setattr(anki_connect, "invoke", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    assert anki_connect.reviewing(URL) is False and URL not in anki_connect._review_card
