"""A busy library store is a wait for the library, never a "no pairing" and never a "fix this" (P2.4-E07, P2.4-E08;
runner `Steps._open` and `Steps.title`). The mode probe reports ("read-only", "busy") for a store another writer
holds, so `_open` must raise a Wait with the library-busy reason, so the job is looked at again. And a title only
names the episode in a message, so on a busy or unwritable store it is None and never raises.

What a wrong answer would cost: a busy store read as Needs tells you to fix something that is not broken and stops
the job; a title that raises breaks a message that only needed a name. Either way an episode you paired gets no cards.

Stubs only the store's open and its mode probe (the busy state); the real `Steps` and its error types run. No Anki,
no network, no real sleep.
"""
import pytest

from app import library_store
from app.connect import library, runner


def test_a_read_only_store_held_as_busy_is_a_wait_for_the_library(monkeypatch):
    # The real probe reports ("read-only", "busy") when another writer holds the store: the mode alone says
    # read-only, but the reason says busy, and a busy store is a wait (try again), never a Needs (fix it).
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": None)
    monkeypatch.setattr(library_store, "check_mode", lambda lang, data_dir, busy_wait=0.0: ("read-only", "busy"))

    with pytest.raises(runner.Wait) as got:
        runner.Steps({}).pairing("ja", {"id": 1, "item_id": 5})
    assert got.value.reason == runner.LIBRARY_BUSY, "a busy store is a wait with its own reason, whatever the mode"


def test_an_episode_title_on_a_busy_store_is_none_and_never_raises(monkeypatch):
    # A title only names the episode in a message, so a busy store gives None rather than stopping the job.
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": None)
    monkeypatch.setattr(library_store, "check_mode", lambda lang, data_dir, busy_wait=0.0: ("store", "busy"))

    assert runner.Steps({}).title("ja", {"id": 1, "item_id": 5}) is None


def test_an_episode_title_on_a_store_that_cannot_be_written_is_none(monkeypatch):
    # JSON mode or a damaged store has no store to write to: the title is still only a name, so None, not a Needs.
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": None)
    monkeypatch.setattr(library_store, "check_mode", lambda lang, data_dir, busy_wait=0.0: ("json", "no store"))

    assert runner.Steps({}).title("ja", {"id": 1, "item_id": 5}) is None
