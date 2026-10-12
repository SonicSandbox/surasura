"""`undo.act` (P3.1 row 3.1.5): *Undo this batch* and the shelf put back, one sequence for the command line and the
window — the checks before Anki, every error in plain words, and Anki's sync owed after a done write.

What a wrong answer would cost:
  * the window saying nothing (or a traceback) where the command line says "you're reviewing" or "another program is
    writing to Anki": the learner can't tell whether the batch was undone;
  * a ledger made by a look: `Ledger()` creates the file, and a made ledger reads as "Connect has run here";
  * a sync owed after a plan or a refusal (a needless sync on the phone) — or none after cards were deleted (the
    phone keeps tomorrow's cards that are gone here).

Anki is a fake (no test reaches Anki); the ledger is real SQLite under the test's own root. The words are real
Japanese ones; the shelf run's name is synthetic.
"""
import calendar
import contextlib
import json
import os
import time

import pytest

from app import anki_connect
from app.cli.contract import CliError
from app.connect import ledger as ledger_module
from app.connect import shelf, undo
from app.connect.ledger import Ledger, path

TAG = "surasura::connect::"
WORDS = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")]
ON = {"connect_enabled": True, "target_language": "ja", "anki_connect_url": "http://127.0.0.1:9"}
RUN = "shelf-2026-10-11-a"


class FakeAnki:
    """Undo's Anki: notes {id: {"tags", "mod", "cards", "fields"}}, cards {id: {"reps", "type", "queue"}};
    `busy` (you review), `held` (the write lock's holder elsewhere), `closed` (Anki doesn't answer)."""

    def __init__(self):
        self.notes_, self.cards_, self.deleted = {}, {}, []
        self.busy, self.held, self.closed = False, None, False
        self.url = ON["anki_connect_url"]

    def add(self, note_id, tag, word, mod):
        cid = note_id * 10
        self.cards_[cid] = {"cardId": cid, "note": note_id, "reps": 0, "type": 0, "queue": 0}
        self.notes_[note_id] = {"noteId": note_id, "tags": [tag], "mod": mod, "cards": [cid],
                                "fields": {"Word": {"value": word}}}

    def notes(self, ids):
        if self.closed:
            raise anki_connect.AnkiError("Anki isn't answering", kind="offline")
        return [self.notes_[i] for i in ids if i in self.notes_]

    def cards(self, ids):
        return [self.cards_[i] for i in ids if i in self.cards_]

    def reviewing(self):
        return self.busy

    def writer(self, verb):
        if self.held is not None:
            from app import locks
            raise locks.Busy("anki-writer", self.held)
        return contextlib.nullcontext()

    def delete_notes(self, ids):
        for i in ids:
            self.notes_.pop(i)
            self.deleted.append(i)

    def users(self, name):
        return [n for n, note in self.notes_.items() if name in json.dumps(note["fields"], ensure_ascii=False)]

    def delete_media(self, name):
        pass


@pytest.fixture
def anki(monkeypatch):
    """Japanese set up, Anki reachable (the fake), no real sync: each owed sync is counted in `anki.synced`."""
    os.makedirs(os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "ja"), exist_ok=True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    fake = FakeAnki()
    fake.synced = []
    monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: fake)
    monkeypatch.setattr(undo, "owe_sync", lambda settings: fake.synced.append(settings))
    return fake


def _batch(anki, state="done", language="ja"):
    """A batch of item 7 that made the five notes; note 101 untouched since before it ended. -> the job id."""
    with Ledger(path()) as ledger:
        job_id = ledger.queue(language, 7, "user", None, store_id="s1")
        ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                             for n, w in WORDS])
        ledger.set_state(job_id, state)
        tag = TAG + ledger.tag_id(job_id)
        done_at = calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki.add(101, tag, "上層部", done_at - 60)
    return job_id


def _shelf(monkeypatch, restore=lambda *a, **k: 3):
    """One shelf restore point listed; putting it back is `restore` (the adapter is never built for real)."""
    with Ledger(path()):
        pass
    monkeypatch.setattr(shelf, "runs", lambda ledger, language=None: [
        {"run": RUN, "cards": 3, "why": "the cap", "at": "2026-10-11T09:00:00Z", "back": 0}])
    monkeypatch.setattr(shelf, "AnkiConnectAnki", lambda url: object())
    monkeypatch.setattr(undo, "restore_shelf", restore)


def _error(call):
    with pytest.raises(CliError) as caught:
        call()
    return caught.value


# --- before Anki ---------------------------------------------------------------------------------------------------

def test_with_the_preview_off_or_anki_switched_off_it_is_skipped_and_nothing_is_made(anki, monkeypatch):
    assert undo.act(dict(ON, connect_enabled=False), "ja", job=1, confirm=True) == {"skipped": undo.PREVIEW_OFF}
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    assert undo.act(ON, "ja", job=1, confirm=True) == {"skipped": undo.NO_ANKI}
    assert not os.path.exists(path()), "a skipped undo makes no ledger"
    assert anki.synced == []


def test_with_no_ledger_it_says_nothing_was_made_and_makes_no_file(anki):
    # Ledger() creates the file: a look before any card was made must never leave one behind
    for kwargs in ({"job": 1}, {"job": 1, "confirm": True}, {"shelf_run": RUN, "confirm": True}):
        e = _error(lambda: undo.act(ON, "ja", **kwargs))
        assert (e.code, e.message) == ("bad-data", undo.NO_LEDGER)
    assert not os.path.exists(path()), "no ledger file was made"
    assert anki.synced == []


def test_a_language_never_set_up_is_said_so(anki):
    e = _error(lambda: undo.act(ON, "zh", job=1))
    assert e.code == "not-set-up" and "isn't set up for this language" in e.message
    assert not os.path.exists(path())


def test_a_batch_not_in_this_language_is_named_by_its_number(anki):
    zh_job = _batch(anki, language="zh")
    e = _error(lambda: undo.act(ON, "ja", job=zh_job, confirm=True))
    assert (e.code, e.message) == ("bad-data", f"There's no batch {zh_job} in the ja library.")
    e = _error(lambda: undo.act(ON, "ja", job=999))
    assert (e.code, e.message) == ("bad-data", "There's no batch 999 in the ja library.")
    assert anki.deleted == [] and anki.synced == []


# --- each error's words --------------------------------------------------------------------------------------------

def test_a_batch_still_running_is_refused_in_plain_words(anki):
    job_id = _batch(anki, state="mining")
    e = _error(lambda: undo.act(ON, "ja", job=job_id, confirm=True))
    assert (e.code, e.message) == ("bad-data", undo.STILL_RUNNING)
    assert anki.deleted == [] and anki.synced == [], "a refusal deletes nothing and owes no sync"


def test_while_you_review_nothing_is_deleted_and_it_says_why(anki):
    job_id = _batch(anki)
    anki.busy = True
    e = _error(lambda: undo.act(ON, "ja", job=job_id, confirm=True))
    assert (e.code, e.message) == ("anki-busy", undo.REVIEWING)
    assert anki.deleted == [] and anki.synced == []


def test_another_program_writing_to_anki_is_named(anki):
    job_id = _batch(anki)
    anki.held = {"program": "Anki Miner", "pid": os.getpid(), "started": "2026-10-11T09:00:00", "verb": "mine"}
    e = _error(lambda: undo.act(ON, "ja", job=job_id, confirm=True))
    assert (e.code, e.message) == ("busy", undo.WRITER_BUSY)
    assert e.context["lock"] == "anki-writer" and e.context["held_by"]["program"] == "Anki Miner"
    assert anki.deleted == [] and anki.synced == []


def test_anki_closed_is_said_so(anki):
    job_id = _batch(anki)
    anki.closed = True
    e = _error(lambda: undo.act(ON, "ja", job=job_id))
    assert e.code == "anki-closed" and e.message.startswith("Anki isn't open (or stopped answering):")
    assert anki.synced == []


def test_a_newer_ledger_asks_for_an_update(anki, monkeypatch):
    with Ledger(path()):
        pass

    def too_new(*_a, **_k):
        raise ledger_module.TooNew(99)
    monkeypatch.setattr(ledger_module, "Ledger", too_new)
    e = _error(lambda: undo.act(ON, "ja", job=1, confirm=True))
    assert e.code == "needs-you" and "newer than this Surasura reads" in e.message
    assert e.context["ask"] == "Update Surasura"


def test_the_shelf_without_junban_is_said_so(anki, monkeypatch):
    def no_junban(*_a, **_k):
        raise ImportError("modules.junban")
    _shelf(monkeypatch, restore=no_junban)
    e = _error(lambda: undo.act(ON, "ja", shelf_run=RUN, confirm=True))
    assert (e.code, e.message) == ("skipped", undo.NEEDS_JUNBAN)
    assert anki.synced == []


def test_the_shelf_while_you_review_and_an_unknown_restore_point(anki, monkeypatch):
    def reviewing(*_a, **_k):
        raise shelf.Reviewing()
    _shelf(monkeypatch, restore=reviewing)
    e = _error(lambda: undo.act(ON, "ja", shelf_run=RUN, confirm=True))
    assert (e.code, e.message) == ("anki-busy", undo.REVIEWING)
    e = _error(lambda: undo.act(ON, "ja", shelf_run="shelf-1999-01-01-z", confirm=True))
    assert (e.code, e.message) == ("bad-data", undo.NO_SHELF_RUN)
    assert anki.synced == []


# --- the sync owed -------------------------------------------------------------------------------------------------

def test_a_plan_writes_nothing_and_owes_no_sync(anki, monkeypatch):
    job_id = _batch(anki)
    answer = undo.act(ON, "ja", job=job_id)
    assert answer["confirm"] is False and answer["delete"] == 1 and answer["language"] == "ja"
    _shelf(monkeypatch, restore=lambda *a, **k: pytest.fail("a plan never puts the shelf back"))
    answer = undo.act(ON, "ja", shelf_run=RUN)
    assert answer == {"run": RUN, "cards": 3, "why": "the cap", "at": "2026-10-11T09:00:00Z", "back": 0,
                      "language": "ja", "confirm": False}
    assert anki.deleted == [] and anki.synced == [], "a plan deletes nothing and owes no sync"


def test_a_done_undo_owes_the_sync_once(anki):
    job_id = _batch(anki)
    answer = undo.act(ON, "ja", job=job_id, confirm=True)
    assert answer["confirm"] is True and answer["deleted"] == 1 and answer["say"].startswith("1 cards deleted.")
    assert anki.deleted == [101]
    assert anki.synced == [ON], "tomorrow's cards changed: Anki's sync is owed, once"


def test_a_done_restore_owes_the_sync_once(anki, monkeypatch):
    _shelf(monkeypatch)
    answer = undo.act(ON, "ja", shelf_run=RUN, confirm=True)
    assert answer == {"language": "ja", "shelf": RUN, "back": 3, "confirm": True}
    assert anki.synced == [ON]


def test_the_caller_can_hand_its_own_sync(anki):
    # the command line hands its `_owe_sync`, which its suites patch: the one handed is the one called
    job_id = _batch(anki)
    handed = []
    undo.act(ON, "ja", job=job_id, confirm=True, sync=handed.append)
    assert handed == [ON] and anki.synced == []
