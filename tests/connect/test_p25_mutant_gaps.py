"""P2.5's planted-bug pass: lines no test ran (the runner's map), each now pinned.

What each test holds still, and what a wrong answer would cost:

  * a note one of whose cards Anki doesn't describe is kept (never deleted unread);
  * an undone note that sat on the shelf leaves the shelf, recorded as undone (not as yours): the record would
    otherwise count a deleted card as shelved, and a wrong `back_by` would read as your choice;
  * Connect's shelf never picks a card you took off it (✅ P2.5-2), through `Steps._shelve` itself;
  * `tidy` never writes while you review; a shelf write whose note mods Anki can't give still goes (recorded unknown);
  * Anki not answering while a half-done undo is finished never stops the run;
  * `surasura-cli logs --save` answers with the zip and how many files it holds.

Real Japanese words, fake Anki, real SQLite in temp folders; no network, no sleeps.
"""
import contextlib
import os
import time

import pytest

from app.connect import runner, shelf, undo
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests.connect.fake_steps import FakeSteps
from tests.connect.test_shelf_anki import FakeAnki as ShelfAnki
from tests.connect.test_undo import FakeAnki, _batch, _done_at


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield led
    finally:
        led.close()


def test_a_note_with_a_card_anki_doesnt_describe_is_kept(ledger):
    job_id, tag = _batch(ledger)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", _done_at(ledger, job_id) - 60)
    anki.notes_[101]["cards"].append(99999)                 # a card id Anki answers nothing for
    plan = undo.plan(anki, ledger, job_id)
    assert plan["delete"] == [] and plan["keep"][0][2] == undo.STUDIED


def test_an_undone_note_on_the_shelf_leaves_it_recorded_as_undone(ledger):
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at - 60, cards=[{"reps": 0, "type": 0, "queue": -1}])   # the shelf's suspend
    with ledger.transaction():
        shelf.ensure(ledger)
        ledger.conn.execute("INSERT INTO shelf (card_id, note_id, language, item_id, word, run, why, shelved_at, "
                            "mod_shelved) VALUES (1010, 101, 'ja', 7, '上層部', 'shelf-1', 'the cap', ?, ?)",
                            (ledger.job_by_id(job_id)["updated_at"], done_at - 60))
    done = undo.run(anki, ledger, job_id, open_store=None)
    assert done["deleted"] == [101]
    back_at, back_by = ledger.conn.execute("SELECT back_at, back_by FROM shelf WHERE card_id = 1010").fetchone()
    assert back_at is not None and back_by == "undone"
    assert 1010 not in shelf.kept(ledger)


def test_the_shelf_never_picks_a_card_you_took_off_it(ledger, monkeypatch):
    steps = runner.Steps({"connect_enabled": True})
    anki = ShelfAnki({11: 1, 12: 2})
    shelf.shelve(anki, ledger, "ja", [shelf.Card(11, 1, "気配", 7)], "the cap", run="run-a")
    shelf.restore(anki, ledger, "run-a")                    # you put it back: never shelved again
    steps._list_order = lambda lang: {}
    steps._open = lambda lang: contextlib.nullcontext(object())
    steps._top_words = lambda lang, store: {}
    steps._anki = lambda: anki
    monkeypatch.setattr(shelf, "made_notes", lambda store: {1: (7, "気配"), 2: (7, "溜め息")})
    monkeypatch.setattr(shelf, "pinned_items", lambda store: set())
    monkeypatch.setattr(shelf, "finished_items", lambda store, made: set())
    monkeypatch.setattr(shelf, "cards", lambda a, q, made: [shelf.Card(11, 1, "気配", 7), shelf.Card(12, 2, "溜め息", 7)])
    offered = []

    def plan(waiting, *a, **k):
        offered.extend(c.card_id for c in waiting)
        return []
    monkeypatch.setattr(shelf, "plan", plan)
    assert steps._shelve("ja", ledger, [], 300, 300) == 0
    assert offered == [12], "the card you put back is never offered to the shelf"


def test_tidy_never_writes_while_you_review(ledger):
    anki = ShelfAnki({11: 1})
    shelf.shelve(anki, ledger, "ja", [shelf.Card(11, 1, "勇気", 7)], "the cap", run="run-a")
    anki.suspended.discard(11)
    anki.busy = True
    with pytest.raises(shelf.Reviewing):
        shelf.tidy(anki, ledger)
    assert shelf.SHELF_TAG in anki.tags[1]
    assert 11 not in shelf.kept(ledger)


def test_a_shelf_write_goes_when_anki_cant_give_the_notes_mods(ledger):
    anki = ShelfAnki({11: 1})

    def broken(note_ids):
        raise OSError("Anki stopped answering")
    anki.note_mods = broken
    run = shelf.shelve(anki, ledger, "ja", [shelf.Card(11, 1, "約束", 7)], "the cap", run="run-a")
    assert run == "run-a" and 11 in anki.suspended
    mod = ledger.conn.execute("SELECT mod_shelved FROM shelf WHERE card_id = 11").fetchone()[0]
    assert mod is None, "unknown: an undo then keeps the note"


def test_anki_not_answering_while_finishing_an_undo_never_stops_the_run(ledger, tmp_path):
    job_id, _tag = _batch(ledger)
    ledger.start_undo(job_id, "ja", [101], [])
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]},
                                      "words": {"1": [["上層部", "じょうそうぶ"]]}})

    def finish(lang, led):
        raise OSError("Anki isn't open")
    steps.finish_undos = finish
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert len(ledger.pending_undos("ja")) == 1, "left for the next run"
    assert any(e[0] == "pick" for e in steps.log), "the run went on to make the episode's cards"


def test_logs_save_answers_with_the_zip_and_its_file_count(tmp_path, monkeypatch):
    from app.connect import status
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "cli.log").write_text("上層部 made", encoding="utf-8")
    monkeypatch.setattr(status, "logs_folder", lambda: str(logs))
    dest = str(tmp_path / "saved.zip")
    code, answer = h.call("logs", "--save", dest)
    assert code == 0 and answer["saved"] == dest and answer["files"] == 1, answer
    assert os.path.exists(dest)
