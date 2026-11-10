"""`surasura-cli undo --job N` (app/cli/connect_verbs.py): the command line's *Undo this batch*.

The rule this pins: undo deletes Anki cards, so the command line only shows its plan until `--confirm` is given;
with Connect's preview off it does nothing at all, and a batch number that is not in the library is an error, not
an empty undo. A wrong answer here would delete a learner's cards on a call that only asked to look.

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
WORDS = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")]


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
    """Preview on, the language set up, no sync reaches Anki; returns the FakeAnki the command line will use."""
    h.write_settings(connect_enabled=True)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(connect_verbs, "_owe_sync", lambda loaded: None)
    anki = FakeAnki()
    monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: anki)
    return anki


def _finished_batch(anki):
    """A finished job of item 7 that made the five notes, with note 101 untouched since before the batch ended.
    Returns the job id; `anki` holds the batch's cards."""
    with Ledger(path()) as ledger:
        job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
        ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                             for n, w in WORDS])
        ledger.set_state(job_id, "done")
        tag = TAG + ledger.tag_id(job_id)
        done_at = calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki.add(101, tag, "上層部", done_at - 60)
    return job_id


def test_undo_without_preview_is_skipped_and_builds_no_anki_client(monkeypatch):
    # Connect's preview is off: the command line says so and never builds an Anki client
    h.write_settings()
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    touched = []
    monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: touched.append(url))
    code, answer = h.call("undo", "--job", "1")
    assert "skipped" in answer, "with the preview off, undo is only skipped"
    assert touched == [], "no Anki client is made with the preview off"


def test_undo_without_confirm_plans_and_deletes_nothing(connected):
    # The plan is the default: without --confirm the learner sees the cards and nothing is deleted
    job_id = _finished_batch(connected)
    code, answer = h.call("undo", "--job", str(job_id))
    assert code == 0 and answer["confirm"] is False
    assert answer["delete"] == 1, "the untouched made card is what the plan would delete"
    assert connected.deleted == [], "the plan writes nothing to Anki"
    with Ledger(path()) as ledger:
        assert ledger.job_by_id(job_id)["state"] == "done", "the batch stays as it was"


def test_undo_with_confirm_deletes_the_plan_and_marks_the_batch_undone(connected):
    # --confirm is the one switch that makes the deletion: the same card goes and the batch is marked undone
    job_id = _finished_batch(connected)
    code, answer = h.call("undo", "--job", str(job_id), "--confirm")
    assert code == 0 and answer["confirm"] is True
    assert connected.deleted == [101], "with --confirm the untouched card is deleted"
    with Ledger(path()) as ledger:
        assert ledger.job_by_id(job_id)["state"] == "undone"


def test_undo_of_a_batch_number_that_is_not_there_is_an_error(connected):
    # A typo'd batch number must not read as "nothing to undo": it is an error line
    _finished_batch(connected)
    code, answer = h.call("undo", "--job", "999")
    assert code != 0, "an unknown batch is an error exit"
    assert answer["type"] == "error" and answer["ok"] is False
