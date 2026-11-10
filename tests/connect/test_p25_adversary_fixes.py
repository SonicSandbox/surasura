"""P2.5's final review, the fixes it asked for (registers `reviews/P2.5-adversary.md`, `P2.5-intent-keeper.md`).

What each test holds still, and what a wrong answer would cost:

  * an edit you made before the shelf touched the note keeps the card: the shelf's own tag write moves the note's
    `mod`, so without the mod read just before that write *Undo this batch* would delete your edited card;
  * a note whose `mod` Anki doesn't give, a card you flagged and a card you buried are kept (never deleted unread);
  * a card brought back by the swap-in, shelved again, then un-suspended by you is recorded as yours (P2.5-2);
  * an undo a kill left half-way is finished at the start of every run, even with no episode to make;
  * a batch or restore point of another language is refused in-process (D31), and `run` answers with the finish it
    did when a half-done undo was the whole undo;
  * a job dropped from the top 20 takes its item's *Needs you* with it;
  * a card you deleted by hand stays deleted and its word stays blocked after an undo (⭐ lean, ASK-SONIC P2.5-3);
  * the status line points at *Needs you* instead of repeating its words; an undone batch's cards don't count as
    made today; `--words` lists a finished batch's not-made words;
  * the logs zip keeps 7 days of Surasura's logs too, and never zips itself.

Real Japanese words, fake Anki, real SQLite in temp folders; no network, no sleeps.
"""
import contextlib
import json
import os
import time
import zipfile

import pytest

from app.connect import runner, shelf, status, undo
from app.connect import ledger as book
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps
from tests.connect.test_shelf_anki import FakeAnki as ShelfAnki
from tests.connect.test_undo import TAG, FakeAnki, FakeStore, _batch, _done_at


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield led
    finally:
        led.close()


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _shelf_row(ledger, card, note, shelved, mod_shelved, back=None, mod_back=None, run="shelf-1", by=None):
    with ledger.transaction():
        shelf.ensure(ledger)
        ledger.conn.execute("INSERT INTO shelf (card_id, note_id, language, item_id, word, run, why, shelved_at, "
                            "mod_shelved, back_at, mod_back, back_by) VALUES (?, ?, 'ja', 7, '気配', ?, 'the cap', ?, "
                            "?, ?, ?, ?)", (card, note, run, _iso(shelved), mod_shelved,
                                            _iso(back) if back else None, mod_back, by))


def test_an_edit_made_before_the_shelf_touched_the_note_keeps_the_card(ledger):
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = FakeAnki()
    # Tuesday you edit the note (mod done_at + 3600); Wednesday the swap-in brings it back: its tag write moves the
    # note's mod to Wednesday, which alone reads as "the shelf's own write"
    anki.add(101, tag, "上層部", done_at + 7200)
    _shelf_row(ledger, 1010, 101, done_at + 60, done_at - 60, back=done_at + 7200, mod_back=done_at + 3600)
    plan = undo.plan(anki, ledger, job_id)
    assert plan["delete"] == [] and plan["keep"][0][2] == undo.CHANGED


def test_a_note_only_the_shelf_touched_still_goes(ledger):
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at + 7200)
    _shelf_row(ledger, 1010, 101, done_at + 60, done_at - 60, back=done_at + 7200, mod_back=done_at + 61)
    assert undo.plan(anki, ledger, job_id)["delete"] == [101]


def test_a_shelf_write_whose_mod_wasnt_read_keeps_the_card(ledger):
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at + 120)
    _shelf_row(ledger, 1010, 101, done_at + 120, None)
    assert undo.plan(anki, ledger, job_id)["keep"][0][2] == undo.CHANGED


@pytest.mark.parametrize("mod", [None, "x"])
def test_a_note_anki_gives_no_mod_for_is_kept(ledger, mod):
    job_id, tag = _batch(ledger)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", mod)
    assert undo.plan(anki, ledger, job_id)["keep"][0][2] == undo.CHANGED


@pytest.mark.parametrize("card, why", [({"reps": 0, "type": 0, "queue": 0, "flags": 1}, undo.FLAGGED),
                                       ({"reps": 0, "type": 0, "queue": -3}, undo.BURIED)])
def test_a_card_you_flagged_or_buried_is_kept(ledger, card, why):
    job_id, tag = _batch(ledger)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", _done_at(ledger, job_id) - 60, cards=[card])
    assert undo.plan(anki, ledger, job_id)["keep"][0][2] == why


def test_a_card_shelved_again_then_unsuspended_by_you_is_recorded_as_yours(ledger):
    anki = ShelfAnki({11: 1})
    shelf.shelve(anki, ledger, "ja", [shelf.Card(11, 1, "気配", 7)], "the cap", run="run-a")
    shelf.bring_back(anki, ledger, "ja", [shelf.Card(11, 1, "気配", 7)])            # the swap-in
    shelf.shelve(anki, ledger, "ja", [shelf.Card(11, 1, "気配", 7)], "the cap", run="run-b")
    anki.suspended.discard(11)                                                   # you un-suspend it in Anki
    shelf.tidy(anki, ledger)
    assert 11 in shelf.kept(ledger)
    assert shelf.SHELF_TAG not in anki.tags[1]


def test_a_half_done_undo_is_finished_at_the_start_of_a_run_with_nothing_to_make(ledger, tmp_path):
    job_id, _tag = _batch(ledger)
    ledger.start_undo(job_id, "ja", [101], [])
    steps = FakeSteps(str(tmp_path), {})
    calls = []
    steps.finish_undos = lambda lang, led: calls.append(lang)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert calls == ["ja"]


def test_a_batch_or_restore_point_of_another_language_is_refused(ledger):
    job_id, tag = _batch(ledger)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", _done_at(ledger, job_id) - 60)
    with pytest.raises(undo.Refused):
        undo.plan(anki, ledger, job_id, language="zh")
    with pytest.raises(undo.Refused):
        undo.run(anki, ledger, job_id, open_store=None, language="zh")
    assert anki.notes([101])
    sanki = ShelfAnki({11: 1})
    run = shelf.shelve(sanki, ledger, "ja", [shelf.Card(11, 1, "気配", 7)], "the cap")
    with pytest.raises(undo.Refused):
        undo.restore_shelf(sanki, ledger, run, language="zh")
    assert 11 in sanki.suspended


def test_run_answers_with_the_finish_it_did_when_that_was_the_whole_undo(ledger):
    job_id, tag = _batch(ledger)
    anki = FakeAnki()
    for n, w in ((101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")):
        anki.add(n, tag, w, _done_at(ledger, job_id) - 60)
    ledger.start_undo(job_id, "ja", [101, 102, 103, 104, 105], [])
    anki.delete_notes([101, 102, 103, 104, 105])                 # Anki deleted them, then the kill
    done = undo.run(anki, ledger, job_id, open_store=None)
    assert sorted(done["deleted"]) == [101, 102, 103, 104, 105]
    assert undo.summary(done)["deleted"] == 5


def test_a_job_dropped_from_the_top_20_takes_its_items_needs(ledger):
    job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
    ledger.need("ja", "not-timed", "上層部の回: not timed, so no cards", item_id=7, job_id=job_id)
    with ledger.transaction():
        assert ledger.drop("ja", 7, "left the top 20")
    assert ledger.needs("ja", listed=False) == []


def test_a_card_you_deleted_by_hand_stays_blocked_after_an_undo(ledger, tmp_path):
    store = FakeStore(str(tmp_path / "store.sqlite"))
    store.conn.execute("INSERT INTO made_words VALUES (7, '上層部', '[101]', 'x', 'b')")
    store.conn.execute("INSERT INTO made_words VALUES (7, '一生懸命', '[]', 'x', 'b')")   # deleted by you, seen
    job_id, tag = _batch(ledger)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", _done_at(ledger, job_id) - 60)                       # 102 is gone: deleted by you
    done = undo.run(anki, ledger, job_id, open_store=lambda: store)
    assert done["deleted"] == [101] and 102 in done["gone"]
    words = {r[0]: r[1] for r in store.conn.execute("SELECT word, note_ids FROM made_words")}
    assert words == {"一生懸命": "[]"}, "the word you deleted keeps its empty row: never made again"
    assert store.receipts == [(7, None)], "nothing of the item is left in Anki: the receipt goes"
    assert "stay deleted" in undo.summary(done)["say"]


def _status(path):
    return status.read(["ja"], path=path, words=True)["languages"]["ja"]


def test_the_line_points_at_needs_you_and_undone_cards_dont_count_today(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "running", lambda: False)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as led:
        waiting = led.queue("ja", 8, "user", None, store_id="s1")
        say = "勇気の回: its subtitle isn't timed, so no cards"
        led.need("ja", "not-timed", say, item_id=8, job_id=waiting)
        led.set_state(waiting, "waiting", reason=say)
        done = led.queue("ja", 9, "user", None, store_id="s1")
        led.start_batch(done, 1, "run-dir")
        led.end_batch(done, 1, "done", [{"word": "約束", "reading": "", "outcome": "made", "note_id": 9001},
                                        {"word": "溜め息", "reading": "", "outcome": "no_definition",
                                         "note_id": None}])
        led.set_state(done, "undone")
        kept = led.queue("ja", 10, "user", None, store_id="s1")
        led.start_batch(kept, 1, "run-dir")
        led.end_batch(kept, 1, "done", [{"word": "気配", "reading": "", "outcome": "made", "note_id": 9002},
                                        {"word": "走り出す", "reading": "", "outcome": "no_definition",
                                         "note_id": None}])
        led.set_state(kept, "done")
    rec = _status(path)
    assert rec["line"] == status.NEEDS_YOU_LINE
    assert rec["made_today"] == 1, "the undone batch's card is not counted"
    (entry,) = rec["undo"]
    assert entry["not_made_words"] == [{"word": "走り出す", "reading": "", "outcome": "no_definition"}]


def test_the_logs_zip_keeps_seven_days_and_never_zips_itself(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "cli.log").write_text("today", encoding="utf-8")
    old = logs / "cli.log.1"
    old.write_text("last month", encoding="utf-8")
    then = time.time() - 30 * 86400
    os.utime(old, (then, then))
    monkeypatch.setattr(status, "logs_folder", lambda: str(logs))
    dest = logs / "saved.zip"
    status.save_logs(str(dest))
    with zipfile.ZipFile(dest) as z:
        names = [os.path.basename(n) for n in z.namelist()]
    assert names == ["cli.log"]
