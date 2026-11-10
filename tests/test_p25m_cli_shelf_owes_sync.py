"""`surasura-cli undo --shelf RUN --confirm` (app/cli/connect_verbs.py): putting a shelf back owes Anki's sync.

The rule this pins: a shelf restore point put back with --confirm changes tomorrow's cards, so the command line
asks for the session's sync exactly once, after the restore; the plan (no --confirm) changes nothing and owes no
sync. A wrong answer would leave the restored cards out of tomorrow's sync until the next run, or sync on a call
that only asked to look.

The words are real Japanese ones; the restore itself is patched (it is tested elsewhere), so no test reaches Anki;
the ledger is real SQLite in the test root.
"""
import types

import pytest

from app.cli import connect_verbs
from app.connect import shelf, undo
from app.connect.ledger import Ledger, path
from tests import cli_helpers as h

RUN = "shelf-20261010-120000-000000"


@pytest.fixture
def shelved(monkeypatch):
    """Preview on, the language set up, one shelf restore point of 上層部 not yet put back.

    Returns one ordered list of events: "restore" when the put-back runs, "sync" when the session's sync is owed.
    """
    import os
    h.write_settings(connect_enabled=True)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    events = []
    monkeypatch.setattr(connect_verbs, "_owe_sync", lambda loaded: events.append("sync"))
    monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: types.SimpleNamespace(url="http://127.0.0.1:8765"))
    monkeypatch.setattr(undo, "restore_shelf", lambda *a, **k: (events.append("restore") or 1))
    monkeypatch.setattr(shelf, "AnkiConnectAnki", lambda url: object())
    with Ledger(path()) as ledger:
        shelf.ensure(ledger)
        # Why: a restore point is a shelf row not yet put back (back_at NULL); the command line lists it by its run name
        ledger.conn.execute("INSERT INTO shelf (card_id, note_id, language, item_id, word, run, why, shelved_at, back_at) "
                            "VALUES (1010, 101, 'ja', 7, '上層部', ?, 'a quarter of the cap', "
                            "'2026-10-10T12:00:00Z', NULL)", (RUN,))
        assert [r["run"] for r in shelf.runs(ledger, "ja")] == [RUN]
    return events


def test_putting_a_shelf_back_with_confirm_owes_one_sync_after_the_restore(shelved):
    # --confirm is the write: the restore happens and the session's sync is owed once, after it, not per card or not at all
    code, answer = h.call("undo", "--shelf", RUN, "--confirm")
    assert code == 0 and answer["confirm"] is True
    assert answer["back"] == 1, "the restore's count is what the command line reports"
    assert shelved == ["restore", "sync"], "a put-back owes Anki's sync exactly once, after the restore"


def test_putting_a_shelf_back_without_confirm_owes_no_sync(shelved):
    # The plan is the default: without --confirm nothing is put back and no sync is asked for
    code, answer = h.call("undo", "--shelf", RUN)
    assert code == 0 and answer["confirm"] is False
    assert shelved == [], "a plan changes nothing, so it owes no sync"
