"""The shelf's once-a-run gate (P2.4 Part B review fix): `Steps.shelve` asks the shelf once per language per run, but a
look that ended in a Wait (you were reviewing, another program held Anki's writer, Anki was gone) spends no try. The
next look asks the shelf again; a look that finished does count, and the look after it answers 0 without asking.

What a wrong answer would cost: a shelf that waited on you once and then never runs again this run (the cap fills
with cards the shelf should have freed), or a shelf that is asked again after it already finished (cards shelved
twice, a second suspend pass over the same learner's pile).

Against a real `runner.Steps` whose `_shelve` is replaced on the instance with a counting fake; no Anki, no sleeps.
"""
import pytest

from app.connect import runner, shelf


class CountingShelve:
    """Stands in for `Steps._shelve`: the first call finds you reviewing, the second shelves two cards, and any
    later call would be a third try. `calls` records each call so the test can see how many tries were spent."""

    def __init__(self):
        self.calls = 0

    def __call__(self, lang, ledger, todo, count, cap):
        self.calls += 1
        if self.calls == 1:
            raise shelf.Reviewing()
        return 2


@pytest.fixture
def steps():
    return runner.Steps({"connect_enabled": True})


def test_a_look_that_waits_for_a_review_spends_no_try_and_the_next_look_shelves(steps):
    # why: the learner was reviewing on the first look; that look must not count, or the shelf is never asked again
    # this run and the cap stays full
    counting = CountingShelve()
    steps._shelve = counting
    with pytest.raises(runner.Wait) as waited:
        steps.shelve("ja", None, [], 300, 300)
    assert waited.value.reason == runner.REVIEWING
    assert steps.shelve("ja", None, [], 300, 300) == 2, "the second look finds you not reviewing and shelves"
    assert counting.calls == 2


def test_a_finished_try_counts_and_a_later_look_answers_zero_without_asking_the_shelf_again(steps):
    # why: once the shelf has run for the language this run, it must never shelve twice (a second pass would
    # suspend cards the first pass already chose)
    counting = CountingShelve()
    steps._shelve = counting
    with pytest.raises(runner.Wait):
        steps.shelve("ja", None, [], 300, 300)
    assert steps.shelve("ja", None, [], 300, 300) == 2
    assert steps.shelve("ja", None, [], 300, 300) == 0
    assert counting.calls == 2, "the third look must not call the shelf at all"
