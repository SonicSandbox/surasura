"""The mining's store write (`runner.Steps.record`): a busy library is a wait that is looked at again, and a library
that can't be written at all is Needs you — never a quiet go-on.

What a wrong answer would cost: a job that goes on after its cards were made, with no receipt of them in the library
(G1.3-4 reads that receipt, so the same words would be made again); or a busy library reported as "no pairing", which
would drop the episode for good instead of waiting for the library to free up.

The store is a stand-in (an object that enters and exits); the library's write is replaced by one that raises the
store's own exception. Nothing touches disk, Anki or the network.
"""
import pytest

from app import library_store
from app.connect import library, runner


class _StoreStandIn:
    """Enters as itself and records that it was closed, so the test can check the `with` block always exits."""

    def __init__(self):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


def _job():
    return {"id": 1, "item_id": 3, "tag": "ab-1"}


def test_a_busy_library_at_the_mining_write_is_a_wait_for_the_library_not_a_go_on(monkeypatch):
    # why: the job's cards exist in Anki already; the write is the only record of them, so the job must wait here
    store = _StoreStandIn()
    monkeypatch.setattr(runner.Steps, "_open", lambda self, lang: store)

    def busy(*args, **kwargs):
        raise library_store.StoreBusy("the write lock was held for 5 s")
    monkeypatch.setattr(library, "record_batch", busy)

    with pytest.raises(runner.Wait) as caught:
        runner.Steps({}).record("ja", _job(), {}, None, "ab-1")
    assert caught.value.reason == runner.LIBRARY_BUSY, "a busy library waits; it is never read as no pairing"
    assert store.closed, "the store is closed even when the write is refused"


def test_a_library_that_cannot_be_written_is_needs_you_with_the_no_store_kind(monkeypatch):
    # why: a read-only library can't be fixed by waiting, so the user is told once in Needs you and the job stays
    store = _StoreStandIn()
    monkeypatch.setattr(runner.Steps, "_open", lambda self, lang: store)

    def read_only(*args, **kwargs):
        raise library_store.StoreReadOnly("damage found at open")
    monkeypatch.setattr(library, "record_batch", read_only)

    with pytest.raises(runner.Needs) as caught:
        runner.Steps({}).record("ja", _job(), {}, None, "ab-1")
    assert caught.value.kind == "no-store", "a store that can't be written is Needs you, never a wait"
    assert store.closed, "the store is closed even when the write is refused"
