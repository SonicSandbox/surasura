"""Undo plans and deletes inside Anki's write lock.

Rule: `undo.run` takes Anki's write lock once, and the reads it plans from (`notes`, `cards`) and the
delete itself (`delete_notes`) all happen while that lock is held. Otherwise another Anki write could
land between the plan and the delete, and an undo could remove a card that was studied or edited a
moment before. What a wrong answer costs: a studied card deleted from the user's collection.
"""
import calendar
import contextlib
import json
import time

import pytest

from app.connect import undo
from app.connect.ledger import Ledger

TAG = "surasura::connect::"


class FakeAnki:
    """Undo's Anki: notes {id: {"tags", "mod", "cards", "fields"}}, cards {id: {"reps", "type", "queue", "note"}}.

    `writer` marks `held` while its block runs; every call the undo makes is logged with whether the lock was held.
    """

    def __init__(self):
        self.notes_ = {}
        self.cards_ = {}
        self.media = set()
        self.busy = False
        self.deleted, self.media_deleted = [], []
        self.held = False
        self.entries = 0
        self.log = []

    def add(self, note_id, tag, word, mod, cards=None, sound=None):
        cards = cards or [{"reps": 0, "type": 0, "queue": 0}]
        ids = []
        for n, card in enumerate(cards):
            cid = note_id * 10 + n
            self.cards_[cid] = dict(card, cardId=cid, note=note_id)
            ids.append(cid)
        fields = {"Word": {"value": word}, "SentenceAudio": {"value": f"[sound:{sound}]" if sound else ""}}
        self.notes_[note_id] = {"noteId": note_id, "tags": [tag], "mod": mod, "cards": ids, "fields": fields}
        if sound:
            self.media.add(sound)

    @contextlib.contextmanager
    def writer(self, verb):
        # The lock: entered once per undo run; `held` is True only inside the block.
        self.entries += 1
        self.held = True
        try:
            yield
        finally:
            self.held = False

    def notes(self, ids):
        self.log.append(("notes", self.held))
        return [self.notes_[i] for i in ids if i in self.notes_]

    def cards(self, ids):
        self.log.append(("cards", self.held))
        return [self.cards_[i] for i in ids if i in self.cards_]

    def reviewing(self):
        return self.busy

    def delete_notes(self, ids):
        self.log.append(("delete_notes", self.held))
        for i in ids:
            note = self.notes_.pop(i)
            for c in note["cards"]:
                self.cards_.pop(c, None)
            self.deleted.append(i)

    def users(self, name):
        return [n for n, note in self.notes_.items() if name in json.dumps(note["fields"], ensure_ascii=False)]

    def delete_media(self, name):
        self.media.discard(name)
        self.media_deleted.append(name)


WORDS = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")]


def _batch(ledger, item_id=7, state="done"):
    """A finished job of item 7 that made the five notes above (their outcomes `made`) -> (job id, its tag)."""
    job_id = ledger.queue("ja", item_id, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                         for n, w in WORDS])
    ledger.set_state(job_id, state)
    return job_id, TAG + ledger.tag_id(job_id)


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def _anki_for(tag, done_at):
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at - 60, sound="sl-aaaa.mp3")                       # untouched: goes
    anki.add(102, tag, "一生懸命", done_at - 60, cards=[{"reps": 3, "type": 2, "queue": 2}])  # studied: stays
    anki.add(103, tag, "走り出す", done_at + 3600)                                         # edited since: stays
    anki.add(104, tag, "気配", done_at - 60, cards=[{"reps": 0, "type": 0, "queue": -1}])  # you suspended it: stays
    anki.add(105, "my-own-tag", "溜め息", done_at - 60)                                    # not this batch's tag
    return anki


def _done_at(ledger, job_id):
    return calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))


def test_undo_reads_and_deletes_only_while_anki_write_lock_is_held(ledger):
    # Why: the plan's reads and the delete must share one lock, so no Anki write lands between them.
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag, _done_at(ledger, job_id))
    # open_store=None: no library store is opened, so the test never touches the user's data.
    undo.run(anki, ledger, job_id, open_store=None)

    assert anki.entries == 1, "the undo takes Anki's write lock once"
    names = [name for name, _held in anki.log]
    assert "notes" in names and "cards" in names and "delete_notes" in names
    # Every notes / cards read made before the delete (the plan's reads and the media check) is under the lock.
    # Reads after the delete belong to finish, which runs after the lock is released, by design, so they are not checked.
    idx = names.index("delete_notes")
    before_delete = [(name, held) for name, held in anki.log[:idx] if name in ("notes", "cards")]
    assert before_delete, "the undo reads notes and cards before it deletes"
    assert all(held for _name, held in before_delete), "every note and card read before the delete runs under the lock"
    delete_calls = [held for name, held in anki.log if name == "delete_notes"]
    assert delete_calls == [True], "the delete happens exactly once, while the lock is held"
