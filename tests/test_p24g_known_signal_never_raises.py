"""Known from Anki never raises (P2.4 row 2.4.15, mutant P2.4-A25): with Connect's preview on, a known-signal read that
fails returns None from `read_known_signal`; it never lets the error out to the sync that called it.

What a wrong answer would cost: the sync runs this read beside its own Anki pass. If the read raised, the whole Anki
sync would stop for one failed signal read (a word list that did not refresh, a dashboard error on every Generate),
when the contract is that a failed read is simply tried again at the next sync.
"""
import pytest

from app import anki_sync
from app.connect import known_signal


URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True, "known_from_anki": ["suspended"]}


@pytest.mark.parametrize("error", [
    RuntimeError("Your known words are being updated by 順."),   # the store is busy: the usual failure
    OSError("AnkiConnect did not answer on 127.0.0.1"),         # Anki closed mid-read
], ids=["store-busy", "anki-closed"])
def test_failed_known_signal_read_returns_none_and_never_raises(error, monkeypatch):
    # Why: the read is fake-failed here, so the only thing under test is the except branch in read_known_signal.
    # Why: record the call, so a None that came from an early return (Connect off) or an earlier error
    # swallowed by the same except cannot pass for "the read failed and was contained".
    reached = []

    def failing_read(*args, **kwargs):
        reached.append((args, kwargs))
        raise error

    monkeypatch.setattr(known_signal, "read", failing_read)

    result = anki_sync.read_known_signal("ja", URL, ["DevTest"], ["Expression"], SETTINGS)

    assert len(reached) == 1, "the known-signal read was never reached, so the except branch was not exercised"
    assert result is None
