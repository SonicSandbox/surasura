"""No Junban, no shelf, said once (P2.4 Part B final-adversary fix): when the shelf's work fails to import (Junban, the
module that holds the shelf's reorder, isn't installed), `Steps.shelve` must skip the shelf quietly and name it to the
learner, not raise into the loop. The skip counts as the run's one try, so the shelf is not asked again this run.

What a wrong answer would cost: a missing optional module that crashes Connect's whole run (every Anki card waits
forever), or a skip that is never named (the learner sees the cap fill and no reason why), or a skip that is retried
on every look (the same message repeated and the shelf asked over and over).

Against a real `runner.Steps` whose `_shelve` is replaced on the instance with a fake that raises the import error the
way a missing module does; no Anki, no network, no sleeps.
"""
import pytest

from app.connect import runner


class MissingJunban:
    """Stands in for `Steps._shelve` when `modules.junban` is not installed: each call raises the error an import of a
    missing module raises. `calls` counts the tries, so the test can see whether the shelf was asked again."""

    def __init__(self):
        self.calls = 0

    def __call__(self, lang, ledger, todo, count, cap):
        self.calls += 1
        raise ModuleNotFoundError("No module named 'modules.junban'")


@pytest.fixture
def steps():
    return runner.Steps({"connect_enabled": True})


def test_a_missing_junban_skips_the_shelf_names_it_and_counts_as_the_run_s_one_try(steps):
    # why: a missing optional module must never crash the run; the skip is named once and spends the run's try
    missing = MissingJunban()
    steps._shelve = missing
    assert steps.shelve("ja", None, [], 300, 300) == 0, "no Junban means nothing shelved, and no exception"
    assert steps.said["ja"] == [runner.SHELF_NO_JUNBAN], "the learner is told the shelf is off and why"
    assert steps.shelf_tried("ja") is True, "the skipped try counts, so the shelf is marked as tried for this run"
    assert steps.shelve("ja", None, [], 300, 300) == 0
    assert missing.calls == 1, "a later look in the same run must not ask the missing shelf again"
    assert steps.said["ja"] == [runner.SHELF_NO_JUNBAN], "the message is named once, not on every look"


def test_a_plain_import_error_is_the_same_skip_as_a_missing_module(steps):
    # why: the rule is the import failure itself, not only the one message; a bare ImportError from a broken
    # optional install must degrade the same way
    def broken(lang, ledger, todo, count, cap):
        raise ImportError("cannot import name 'reorder' from 'modules.junban'")

    steps._shelve = broken
    assert steps.shelve("ja", None, [], 300, 300) == 0
    assert steps.said["ja"] == [runner.SHELF_NO_JUNBAN]
