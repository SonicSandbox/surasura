"""`surasura-cli undo --job N --confirm` with `SURASURA_NO_ANKI_SYNC` set (app/cli/connect_verbs.py `undo`).

The rule this pins: under the test switch, Anki is never reached, not even to delete. The command line answers
"skipped" and never builds an Anki client, so a test run (or a developer's run) cannot touch a learner's cards even
when it asks for the real undo. A wrong answer here would let a test delete notes in the user's Anki.

The words are real Japanese ones; no test reaches Anki (the client factory only records the URL it was given).
"""
import os

import pytest

from app.cli import connect_verbs  # noqa: F401  (the verb under test, loaded as the command line loads it)
from app.connect import undo
from app.connect.ledger import Ledger, path
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


@pytest.fixture
def switched_off(monkeypatch):
    """Preview on, the language set up, the test switch on; returns the list of URLs an Anki client was built for."""
    h.write_settings(connect_enabled=True)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    touched = []
    monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: touched.append(url))
    # A finished batch that made a card: without the switch, the verb would go on to build the Anki client for it
    with Ledger(path()) as ledger:
        job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
        ledger.end_batch(job_id, 1, "done", [{"word": "上層部", "reading": "", "outcome": "made", "note_id": 101}])
        ledger.set_state(job_id, "done")
    return touched, job_id


def test_undo_with_confirm_under_the_test_switch_is_skipped_and_builds_no_anki_client(switched_off):
    """A confirmed undo of a finished batch says it was skipped, and no Anki client was ever made: the switch keeps
    deletion away from Anki even when the caller asks for it."""
    touched, job_id = switched_off
    code, answer = h.call("undo", "--job", str(job_id), "--confirm")
    assert code == 0
    # Pin the switch's own reason, so a skip from another guard (the preview being off) cannot pass for it.
    assert "SURASURA_NO_ANKI_SYNC" in answer["skipped"]
    assert touched == []
