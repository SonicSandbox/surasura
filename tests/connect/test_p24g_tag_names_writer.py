"""The names' tag a batch left off goes on under Anki's write lock, and the lock is let go after, whatever happens
(P2.4 row 2.4.4; mutant P2.4-E02).

What a wrong answer would cost: a tag written while another program writes Anki, or a write lock Connect never lets
go, so every later writer (順, Backfill, the next batch) waits on it until Connect's process ends.

The real lock (`app.locks` under the suite's own root); Anki is never reached: `reviewing` and `invoke` are stubbed.
"""
import pytest

from app import anki_connect, locks
from app.connect import runner
from tests import cli_helpers as h


def _steps():
    return runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT})


def _free():
    """No thread of this process holds Anki's write lock, and a new writer gets it at once."""
    if locks.held_in_process(anki_connect.WRITER_LOCK) is not None:
        return False
    locks.take(anki_connect.WRITER_LOCK, "the test's own check").release()
    return True


def test_the_tag_goes_on_while_the_writer_is_held_and_the_writer_is_let_go_after(monkeypatch):
    sent = []

    def invoke(action, url, **params):
        sent.append((action, locks.held_in_process(anki_connect.WRITER_LOCK), params["notes"]))
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: False)
    monkeypatch.setattr(anki_connect, "invoke", invoke)
    _steps().tag_names("ja", [1700000000011, 1700000000012])
    assert sent == [("addTags", "Connect's name tags", [1700000000011, 1700000000012])], \
        "the tag is written once, inside the lock named for it"
    assert _free(), "the lock is let go once the tag is on"


def test_while_you_review_nothing_is_written_and_the_writer_is_let_go(monkeypatch):
    sent = []
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: True)
    monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **params: sent.append(action))
    with pytest.raises(runner.Wait) as e:
        _steps().tag_names("ja", [1700000000011])
    assert e.value.reason == runner.REVIEWING and e.value.resume == "filling"
    assert sent == []
    assert _free(), "a wait for your review never keeps the lock"


def test_anki_closing_mid_write_is_a_wait_and_the_writer_is_let_go(monkeypatch):
    def invoke(action, url, **params):
        raise anki_connect.AnkiError("Anki isn't open.", "offline")
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: False)
    monkeypatch.setattr(anki_connect, "invoke", invoke)
    with pytest.raises(runner.Wait) as e:
        _steps().tag_names("ja", [1700000000011])
    assert e.value.reason == runner.ANKI_CLOSED
    assert _free()
    # and the next batch's tag can take the lock again in this same thread (a lock kept would refuse a nested take)
    monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **params: None)
    _steps().tag_names("ja", [1700000000012])
    assert _free()
