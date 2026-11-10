"""A busy library is a wait, never "no pairing" (P2.4-A #10; runner `Steps._open` and `Steps.pairing`): when the
language's library store is held by another writer, reading the item's pairing raises a Wait with the library-busy
reason, so the job is looked at again. Read as "no pairing", the job would go on without its video and mine nothing
for that episode.

What a wrong answer would cost: a busy library read as "no pairing" makes Connect pass over an episode you paired,
and the cards for it are never made; a Needs instead tells you to fix something that is not broken.

Stubs only the store's open and its mode probe (the busy state); the real `Steps` and its error types run. No Anki,
no network, no real sleep.
"""
import pytest

from app import library_store
from app.connect import library, runner


def test_a_busy_library_store_makes_the_pairing_a_wait_not_a_missing_pairing(monkeypatch):
    # The store is held by another writer: open_store gives no store and the mode probe reports "busy".
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": None)
    monkeypatch.setattr(library_store, "check_mode", lambda lang, data_dir, busy_wait=0.0: ("store", "busy"))

    with pytest.raises(runner.Wait) as got:
        runner.Steps({}).pairing("ja", {"id": 1, "item_id": 5})
    assert got.value.reason == runner.LIBRARY_BUSY, "a busy store is a wait with its own reason, never a missing pairing"
