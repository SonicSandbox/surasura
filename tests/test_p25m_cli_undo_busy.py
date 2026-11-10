"""`surasura-cli undo --job N --confirm` when Anki's write lock is held elsewhere (app/cli/connect_verbs.py).

The rule this pins: when the undo cannot take Anki's write lock, the command line answers with the contract's busy
error (exit 3, code "busy", lock "anki-writer") and names the program holding the lock in `held_by`, so the learner
knows what to wait for. A wrong answer here would leave the learner guessing whether their batch was undone.

Anki is a fake (no test reaches Anki); the ledger is real SQLite in the test root.
"""
import contextlib
import json
import os
import subprocess
import sys

import pytest

from app import locks
from app.cli import connect_verbs
from app.connect import undo
from app.connect.ledger import Ledger, path
from tests import cli_helpers as h

TAG = "surasura::connect::"
WORDS = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")]


class FakeAnki:
    """Undo's Anki with the write lock held elsewhere: `writer` raises `locks.Busy` for every verb."""

    def __init__(self, holder):
        self.notes_ = {}
        self.cards_ = {}
        self.media = set()
        self.busy = False
        self.deleted = []
        self.holder = holder

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
        # Another program holds Anki's write lock: the undo must not delete anything
        raise locks.Busy("anki-writer", self.holder)

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
    """Preview on, the language set up, no sync reaches Anki; the write lock is held by a live child process
    (a sleeping Python, killed after the test), so the holder record is kept as alive."""
    h.write_settings(connect_enabled=True)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(connect_verbs, "_owe_sync", lambda loaded: None)
    # The holder is a real child process that stays alive for the test, so the busy answer keeps it as alive
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        holder = {"program": "Anki Miner", "pid": proc.pid, "started": "2026-10-11T00:00:00Z", "verb": "mine"}
        anki = FakeAnki(holder)
        monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: anki)
        yield anki
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _finished_batch(anki):
    """A finished batch of item 7 that made the five notes; returns the job id."""
    import calendar
    import time
    with Ledger(path()) as ledger:
        job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
        ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                             for n, w in WORDS])
        ledger.set_state(job_id, "done")
        tag = TAG + ledger.tag_id(job_id)
        done_at = calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki.add(101, tag, "上層部", done_at - 60)
    return job_id


def test_undo_with_anki_write_lock_busy_answers_busy_and_names_the_holder(connected):
    # A busy Anki write lock is a plain "busy" answer (exit 3) naming the lock and its holder; it is not a crash
    job_id = _finished_batch(connected)
    code, answer = h.call("undo", "--job", str(job_id), "--confirm")
    assert code == 3, "a busy write lock exits 3, the contract's busy code"
    assert answer["code"] == "busy" and answer["lock"] == "anki-writer"
    assert answer["held_by"]["program"] == "Anki Miner" and answer["held_by"]["pid"] == connected.holder["pid"], \
        "the answer names the program holding the write lock"
    assert answer["held_by"]["pid"] != os.getpid(), "the holder is the other program, not this caller"
    assert connected.deleted == [], "a busy lock deletes nothing"
    with Ledger(path()) as ledger:
        assert ledger.job_by_id(job_id)["state"] == "done", "the batch stays as it was"
