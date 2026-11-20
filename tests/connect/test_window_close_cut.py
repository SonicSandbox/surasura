"""Haya-CL 3.0.17 (Sonic's laptop, 3.0.16, report #8158GX: Connect still mining 48 s after the window closed; the lead:
every child the window starts ends with it; PROVISIONAL): a Connect that worked beside a window stops when it closes.
The job under way is cut as a pause cuts it (Mado-PZ) — its cards so far kept, never your Stop — and waits
WINDOW_CLOSED, going on from its step at the next start (the window's start kicks Connect). A Connect started with no
window open (hato's hand-over) never saw one: it does the work it can do now, then ends (3.0.3's lean, kept).

What a wrong answer would cost: Anki Miner and its ffmpeg cuts working on the learner's PC after he closed Surasura
(the laptop's lag); or the other way, an episode cut by the close that never goes on (waiting for a new *Mine now*, as
a Stop does), or a hato drop never mined because no window was open.

Against `FakeSteps` (real words, ja and zh); the window's presence is the test's own answer. Never a live Anki.
"""
import pytest

from app.cli import connect_verbs
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WINDOW_CLOSED = getattr(runner, "WINDOW_CLOSED", "(no WINDOW_CLOSED before Haya-CL 3.0.17)")     # red-first collects
EPISODE_WORDS = {
    "ja": [("上層部", "ジョウソウブ"), ("一生懸命", "イッショウケンメイ"), ("走り出す", "ハシリダス")],
    "zh": [("认真", "ren4 zhen1"), ("约定", "yue1 ding4"), ("勇气", "yong3 qi4")],
}


class Steps(FakeSteps):
    """FakeSteps with the window's look: `self.window` is the answer (the test closes it mid-run)."""

    window = True

    def window_open(self):
        return self.window


@pytest.fixture(autouse=True)
def every_look_fresh(monkeypatch):
    monkeypatch.setattr(runner, "WINDOW_LOOK_S", 0, raising=False)       # the close is seen at the very next look


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _queue(ledger, lang, item_id):
    with ledger.transaction():
        return ledger.queue(lang, item_id, "user", None, store_id="store-1")


def _steps(tmp_path, lang, items=(1,), **plan):
    words = {str(i): EPISODE_WORDS[lang] for i in items}
    return Steps(str(tmp_path), dict({"line": {lang: list(items)}, "words": words}, **plan))


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_window_closing_mid_batch_cuts_the_job_keeps_its_cards_and_the_next_start_finishes_it(
        tmp_path, ledger, lang):
    job_id = _queue(ledger, lang, 1)
    steps = _steps(tmp_path, lang)

    def close(n, _job):
        if n == 1:
            steps.window = False                # the window closed after the batch's first card
    steps.plan["on_word"] = close
    summary = runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", WINDOW_CLOSED, "mining")
    assert not ledger.is_stopped(job_id) and not ledger.held_by_stop(job), "the close is no Stop of yours"
    assert steps.anki.words() == [EPISODE_WORDS[lang][0][0]], "the card made before the close is kept"
    assert summary.get("stopped") == WINDOW_CLOSED
    # the window opens again: its start's kick finishes the episode, only the words still unmade, each once
    after = _steps(tmp_path, lang)
    runner.run({}, [lang], steps=after, ledger=ledger, sleep=lambda s: None, looks=1)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert [e[3] for e in after.log if e[0] == "mine"] == [[w for w, _r in EPISODE_WORDS[lang][1:]]]


def test_the_window_closing_between_jobs_starts_no_other_job(tmp_path, ledger):
    first, second = _queue(ledger, "ja", 1), _queue(ledger, "ja", 2)

    class ClosedAfterTheBatch(Steps):
        def mine(self, lang, job, picked, words, attempt):
            got = super().mine(lang, job, picked, words, attempt)
            self.window = False                 # closed once the first episode's cards were all made
            return got
    steps = ClosedAfterTheBatch(str(tmp_path), {"line": {"ja": [1, 2]},
                                                "words": {"1": EPISODE_WORDS["ja"], "2": EPISODE_WORDS["ja"]}})
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert summary.get("stopped") == WINDOW_CLOSED
    assert ledger.job_by_id(first)["state"] == "done", "its cards were all made: it finishes (filled, ordered)"
    assert [e[1] for e in steps.log if e[0] == "mine"] == [1], "the second episode never started"
    assert ledger.job_by_id(second)["state"] in ("queued", "waiting")


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_connect_started_with_no_window_open_still_does_the_work_it_can(tmp_path, ledger, lang):
    # 3.0.3's lean kept: hato's hand-over with Surasura closed is mined, then Connect ends
    job_id = _queue(ledger, lang, 1)
    steps = _steps(tmp_path, lang)
    steps.window = False
    summary = runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert ledger.job_by_id(job_id)["state"] == "done" and "stopped" not in summary
    assert steps.anki.words() == [w for w, _r in EPISODE_WORDS[lang]]


def test_a_window_open_throughout_changes_nothing(tmp_path, ledger):
    job_id = _queue(ledger, "zh", 1)
    steps = _steps(tmp_path, "zh")
    summary = runner.run({}, ["zh"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert ledger.job_by_id(job_id)["state"] == "done" and "stopped" not in summary


def test_a_run_stopped_by_the_close_starts_no_connect_again(monkeypatch):
    # `_loop` restarts Connect for a kick or a pending inbox only when the run wasn't stopped: never a start after
    # the window closed (a start would see no window and mine on)
    kicked = []
    monkeypatch.setattr(connect_verbs, "_kick", lambda loaded: kicked.append(loaded))
    monkeypatch.setattr(connect_verbs, "_woken_since", lambda summary: True)
    monkeypatch.setattr(runner, "run", lambda loaded, languages, looks=None: {"stopped": WINDOW_CLOSED})
    from app import locks
    from app.connect import kick
    if locks.in_use(kick.LOCK):
        pytest.skip("another Connect holds this test root's lock")
    connect_verbs._loop({}, ["ja"])
    assert kicked == []


def test_the_window_look_is_no_window_for_a_stand_in_without_it_or_a_look_that_fails():
    class Bare:
        pass

    class Failing:
        def window_open(self):
            raise OSError("the running marks can't be listed")
    assert runner._window_gone(Bare()) is False
    failing = Failing()
    failing.window_seen = True
    assert runner._window_gone(failing) is False, "a failed look waits as before, never a cut"


def test_a_failed_first_look_is_no_window_seen(tmp_path, ledger):
    # the state lens: a look that fails answered "open" (waiting's safe side) and was kept as a window seen — a
    # Connect started with no window (hato's) whose first look failed was then cut by the next look's "no window"
    job_id = _queue(ledger, "ja", 1)
    answers = iter([OSError("the running marks can't be listed")])

    class FirstLookFails(Steps):
        window = False

        def window_open(self):
            failure = next(answers, None)
            if failure is not None:
                raise failure
            return self.window
    steps = FirstLookFails(str(tmp_path), {"line": {"ja": [1]}, "words": {"1": EPISODE_WORDS["ja"]}})
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert ledger.job_by_id(job_id)["state"] == "done" and "stopped" not in summary
