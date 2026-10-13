"""`surasura-cli undo --job N` refuses a batch of another language (app/cli/connect_verbs.py).

The rule this pins: a batch belongs to one language's library, so `undo --job N` for a Chinese batch, typed on the
Japanese command line, is an error that names the Japanese library, and nothing is deleted, even with `--confirm`.
A wrong answer here would delete a learner's Chinese cards on a Japanese command line.

The words are real Japanese ones; Anki is a fake (no test reaches Anki); the ledger is real SQLite in the test root.
"""
import calendar
import contextlib
import json
import os
import time

import pytest

from app.cli import connect_verbs
from app.connect import undo
from app.connect.ledger import Ledger, path
from tests import cli_helpers as h

TAG = "surasura::connect::"


class FakeAnki:
    """Undo's Anki: notes {id: {"tags", "mod", "cards", "fields"}}, cards {id: {"reps", "type", "queue", "note"}}."""

    def __init__(self):
        self.notes_ = {}
        self.cards_ = {}
        self.media = set()
        self.busy = False
        self.deleted = []

    def add(self, note_id, tag, word, mod, cards=None):
        cards = cards or [{"reps": 0, "type": 0, "queue": 0}]
        ids = []
        for n, card in enumerate(cards):
            cid = note_id * 10 + n
            self.cards_[cid] = dict(card, cardId=cid, note=note_id)
            ids.append(cid)
        fields = {"Word": {"value": word}, "SentenceAudio": {"value": ""}}
        self.notes_[note_id] = {"noteId": note_id, "tags": [tag], "mod": mod, "cards": ids, "fields": fields}

    def notes(self, ids):
        return [self.notes_[i] for i in ids if i in self.notes_]

    def cards(self, ids):
        return [self.cards_[i] for i in ids if i in self.cards_]

    def reviewing(self):
        return self.busy

    def writer(self, verb):
        return contextlib.nullcontext()

    def delete_notes(self, ids):
        for i in ids:
            note = self.notes_.pop(i)
            for c in note["cards"]:
                self.cards_.pop(c, None)
            self.deleted.append(i)

    def users(self, name):
        return [n for n, note in self.notes_.items() if name in json.dumps(note["fields"], ensure_ascii=False)]

    def delete_media(self, name):
        self.media.discard(name)


@pytest.fixture
def connected(monkeypatch):
    """Preview on, the Japanese language set up, no sync reaches Anki; returns the FakeAnki the command line uses."""
    h.write_settings(connect_enabled=True)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(connect_verbs, "_owe_sync", lambda loaded: None)
    anki = FakeAnki()
    monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: anki)
    return anki


def test_undo_of_a_chinese_batch_on_the_japanese_command_line_is_refused_and_deletes_nothing(connected):
    # A batch number from the Chinese library is not a batch of the ja command: refused, even with --confirm,
    # so the Chinese card survives and the Chinese batch stays as it was
    with Ledger(path()) as ledger:
        job_id = ledger.queue("zh", 7, "user", None, store_id="s1")
        ledger.end_batch(job_id, 1, "done", [{"word": "上层部", "reading": "", "outcome": "made", "note_id": 101}])
        ledger.set_state(job_id, "done")
        tag = TAG + ledger.tag_id(job_id)
        done_at = calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    connected.add(101, tag, "上层部", done_at - 60)

    code, answer = h.call("undo", "--job", str(job_id), "--confirm")
    assert code != 0, "a batch of another language is an error exit"
    assert answer["type"] == "error" and answer["ok"] is False
    # The command line's own refusal names the Japanese library; undo's generic "no cards" text would mean the
    # command line let the Chinese batch through to the undo layer
    assert answer["message"] == f"There's no batch {job_id} in the ja library.", "the Japanese command line refuses it"
    assert connected.deleted == [], "the Chinese batch's card is not deleted from the Japanese command line"
    assert 101 in connected.notes_, "the note is still in Anki"
    with Ledger(path()) as ledger:
        assert ledger.job_by_id(job_id)["state"] == "done", "the Chinese batch is not marked undone"
