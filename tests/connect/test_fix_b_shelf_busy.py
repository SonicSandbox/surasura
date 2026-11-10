"""The shelf's wait for a busy writer (P2.4 Part B review fix: `Steps.shelve` turns `locks.Busy` into a Wait).

When another program holds Anki's writer lock while the shelf is working, the shelf must pause the job with
`runner.WRITER_BUSY` and resume from mining. The raw `locks.Busy` must never escape: the loop would park it as an
error. An Anki that is closed (`AnkiError` kind 'offline') keeps its own wait, `runner.ANKI_CLOSED`.

What a wrong answer would cost: a job that dies with an error while the user is simply in the middle of a write
elsewhere, or a shelf that never says why it stopped.

Against a Steps instance with its shelf work replaced by a function that raises; never a live Anki, no sleeps.
"""
import pytest

from app import anki_connect, locks
from app.connect import runner


def _steps_whose_shelf_raises(error):
    steps = runner.Steps({"connect_enabled": True})

    def _shelve(lang, ledger, todo, count, cap):
        raise error

    # the instance attribute overrides the method, so `shelve` calls this fake and nothing else
    steps._shelve = _shelve
    return steps


def test_a_busy_writer_waits_the_shelf_instead_of_failing_the_job():
    # why: Busy is what the lock raises when another program holds Anki's writer; it is a pause, not a failure
    steps = _steps_whose_shelf_raises(locks.Busy("anki-writer"))

    with pytest.raises(runner.Wait) as caught:
        steps.shelve("ja", None, [], 300, 300)

    assert caught.value.reason == runner.WRITER_BUSY, "the wait says another program is writing to Anki"
    assert caught.value.resume == "mining", "the job goes on from mining once the writer is free"


def test_an_anki_that_is_closed_still_waits_with_its_own_reason():
    # the busy-writer rule must not swallow the closed-Anki case: the two waits say different things to the user
    steps = _steps_whose_shelf_raises(anki_connect.AnkiError("x", kind="offline"))

    with pytest.raises(runner.Wait) as caught:
        steps.shelve("ja", None, [], 300, 300)

    assert caught.value.reason == runner.ANKI_CLOSED
    assert caught.value.resume == "mining"
