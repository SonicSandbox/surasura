"""An undo fixes its item's needs (P2.5 mutant M5; ✅ P2.5 undo flow: once the undo deletes a batch's notes, the
item's open needs are settled, so *Needs you* stops asking about a batch that is gone).

The rule: after `undo.run` deletes a note, the item's open needs are fixed (gone from `ledger.needs("ja",
listed=False)`), while another item's need stays open. What a wrong answer would cost: a learner who undid a batch
sees a stale "couldn't read the subtitles" alarm for an episode that no longer has any cards, or, worse, another
episode's real need gets cleared by mistake.

The words are real Japanese ones; Anki is a fake (its methods copied from the undo suite); the ledger is real SQLite
in a temp folder.
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
    """Undo's Anki: notes {id: {"tags", "mod", "cards", "fields"}}, cards {id: {"reps", "type", "queue", "note"}}."""

    def __init__(self):
        self.notes_ = {}
        self.cards_ = {}
        self.media = set()
        self.busy = False
        self.deleted, self.media_deleted = [], []

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
        self.media_deleted.append(name)


WORDS = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")]


def _batch(ledger, item_id=7, state="done"):
    """A finished job of item 7 that made the five notes above (their outcomes `made`) -> (job id, its tag)."""
    job_id = ledger.queue("ja", item_id, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                         for n, w in WORDS])
    ledger.set_state(job_id, state)
    return job_id, TAG + ledger.tag_id(job_id)


def _done_at(ledger, job_id):
    return calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))


def _anki_for(tag, done_at):
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at - 60)                                              # untouched: goes
    anki.add(102, tag, "一生懸命", done_at - 60, cards=[{"reps": 3, "type": 2, "queue": 2}])  # studied: stays
    anki.add(103, tag, "走り出す", done_at + 3600)                                         # edited since: stays
    anki.add(104, tag, "気配", done_at - 60, cards=[{"reps": 0, "type": 0, "queue": -1}])  # suspended: stays
    anki.add(105, "my-own-tag", "溜め息", done_at - 60)                                    # not this batch's tag
    return anki


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def test_an_undo_settles_the_needs_of_its_own_item_and_leaves_another_items_need_open(ledger):
    # Two items each have a standing failure. Undoing item 7's batch deletes its note, so item 7's need is settled;
    # item 8 has its own failure and must keep asking, or the learner would miss a real problem.
    job_id, tag = _batch(ledger)
    ledger.need("ja", "mine-failed", "上層部の字幕が読めませんでした", item_id=7)
    ledger.need("ja", "error", "上層部の字幕の取り込みでエラーが出ました", item_id=7)
    ledger.need("ja", "mine-failed", "気配の字幕が読めませんでした", item_id=8)
    anki = _anki_for(tag, _done_at(ledger, job_id))

    done = undo.run(anki, ledger, job_id)

    assert anki.deleted == [101], "the undo deleted the untouched note of item 7's batch"
    open_items = [n["item_id"] for n in ledger.needs("ja", listed=False)]
    assert [n for n in ledger.needs("ja", listed=False) if n["item_id"] == 7] == [], \
        "every need of item 7 is fixed: its batch's note is gone, whatever kind of trouble it was"
    assert open_items == [8], "item 8's need stays open: another item's trouble is not fixed by this undo"
