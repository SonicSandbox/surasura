"""A shelf write Anki didn't take raises, and records nothing (review B #8; the shelf's Anki writes in
`app/connect/shelf.py`: `_taken` and the adapter's suspend / tag calls).

What each test holds still:

  * `_taken` raises `AnkiError` when Junban's answer names a failure, and returns quietly when it names none. A wrong
    answer would let a suspend Anki refused be counted as done and written to the restore point;
  * through the real adapter, a suspend Anki doesn't take makes `shelve` raise, and the ledger's `shelf` table holds
    no row afterwards. A wrong answer would leave a card the shelf thinks it owns, with no restore point to bring it
    back.

Why the fake: the suspend call is Junban's AnkiConnect helper, monkeypatched to answer "busy" for one card; the
adapter's other methods are faked on the instance. No test reaches Anki, no sleeps, no network. The ledger is a real
SQLite file in a temp folder.
"""
import contextlib

import pytest

from app import anki_connect
from app.connect import shelf
from app.connect.ledger import Ledger
from app.connect.shelf import AnkiConnectAnki


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def test_a_write_anki_did_not_take_raises_and_a_taken_one_passes():
    # Why: "failures" is Anki's refusal list; a non-empty list must never be counted as a write that went through.
    with pytest.raises(anki_connect.AnkiError):
        shelf._taken(([], [(5, "busy")]), "suspend")

    assert shelf._taken(([5], []), "suspend") is None


def test_shelve_refused_by_anki_raises_and_records_no_restore_point(ledger, monkeypatch):
    # Why: a suspend Anki refused must leave no ledger row, or the shelf would claim a card it never suspended.
    ankiconnect = pytest.importorskip("modules.junban.ankiconnect")    # the public repo has no modules/
    monkeypatch.setattr(ankiconnect, "suspend", lambda url, card_ids, chunk=150: ([], [(5, "busy")]))
    adapter = AnkiConnectAnki("http://127.0.0.1:8765")
    adapter.writer = lambda verb: contextlib.nullcontext()
    adapter.reviewing = lambda: False
    adapter.add_tag = lambda note_ids, tag: None
    chosen = [shelf.Card(5, 1, "勇気", 7)]

    with pytest.raises(anki_connect.AnkiError):
        shelf.shelve(adapter, ledger, "ja", chosen, "a quarter of the cap", run="run-refused")

    assert shelf.runs(ledger) == []
