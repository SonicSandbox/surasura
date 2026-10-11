"""P2.5's first review, the fixes it asked for (register `reviews/P2.5-haiku.md` #1, #2, #4, #5, #6, #8).

What each test holds still, and what a wrong answer would cost:

  * a shelved card you un-suspended in Anki is recorded as yours even when its note keeps the shelf tag (another card
    of the note still shelved): otherwise Connect could shelve it again (✅ P2.5-2) and would take Anki's writer every
    run for nothing; once recorded, the next look takes no writer;
  * a dismissed *Needs you* entry stays dismissed when the same failure happens again before its fix: a dismissed
    problem popping back every run is the nagging *Dismiss* exists to stop;
  * a folder offline for a run keeps its listing in the video index (no rewrite, nothing listed again when it's back);
  * a video found by size uses the file's size as it is now (a copy that finished after the folder was listed);
  * a batch whose end time can't be read never has a note deleted as "unchanged": unknown → kept;
  * `surasura-cli undo --shelf RUN --confirm` puts the restore point back through the shelf's own Anki adapter.

Real Japanese words, fake Anki, real SQLite in temp folders; no network, no sleeps.
"""
import contextlib
import os

import pytest

from app.connect import shelf, undo, videos
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests.connect.test_shelf_anki import FakeAnki as ShelfAnki
from tests.connect.test_undo import FakeAnki as UndoAnki


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


class CountingShelfAnki(ShelfAnki):
    def __init__(self, note_of):
        super().__init__(note_of)
        self.writes = 0

    def writer(self, verb):
        self.writes += 1
        return contextlib.nullcontext()


def test_a_card_unsuspended_in_anki_beside_a_shelved_sibling_is_recorded_as_yours(ledger):
    # cards 11 and 12 are two cards of note 1 ("気配"): both shelved, the learner un-suspends 11 only
    anki = CountingShelfAnki({11: 1, 12: 1})
    shelf.shelve(anki, ledger, "ja", [shelf.Card(11, 1, "気配", 7), shelf.Card(12, 1, "気配", 7)], "the cap",
                 run="run-a")
    anki.suspended.discard(11)
    anki.writes = 0

    assert shelf.tidy(anki, ledger) == 0, "the note keeps its tag: card 12 is still on the shelf"
    assert shelf.SHELF_TAG in anki.tags[1]
    assert 11 in shelf.kept(ledger) and 12 not in shelf.kept(ledger)
    writes = anki.writes
    shelf.tidy(anki, ledger)
    assert anki.writes == writes, "a card already recorded as back takes no writer again"


def test_a_dismissed_failure_stays_dismissed_when_it_happens_again_before_its_fix(ledger):
    ledger.need("ja", "mine-failed", "上層部の回: Anki Miner stopped twice", item_id=3)
    (row,) = ledger.needs("ja")
    ledger.dismiss(row["id"])
    assert ledger.need("ja", "mine-failed", "上層部の回: Anki Miner stopped again", item_id=3) is False
    assert ledger.needs("ja") == [], "still dismissed"
    assert [n["id"] for n in ledger.needs("ja", listed=False)] == [row["id"]], "still open, one entry"


def test_an_offline_folder_keeps_its_listing_and_the_index_is_not_rewritten(tmp_path, monkeypatch):
    folder = tmp_path / "Bocchi"
    folder.mkdir()
    (folder / "Bocchi - 03.mkv").write_bytes(b"\x1aE\xdf\xa3" * 4)
    index = videos.Index("ja", path=str(tmp_path / "videos-ja.json"))
    index.refresh([], [str(folder)])
    saved = os.stat(index.path).st_mtime_ns
    real_stat = os.stat
    offline = os.path.normcase(os.path.abspath(str(folder)))

    def stat(path, *a, **k):            # the share is offline: its folder can't be looked at
        if os.path.normcase(os.path.abspath(str(path))) == offline:
            raise OSError("offline")
        return real_stat(path, *a, **k)
    monkeypatch.setattr(videos.os, "stat", stat)
    again = videos.Index("ja", path=index.path)
    assert again.refresh([], [str(folder)]) is False and again.listed == 0
    monkeypatch.setattr(videos.os, "stat", real_stat)
    assert os.stat(index.path).st_mtime_ns == saved, "nothing to save while it was offline"
    assert offline in again.data["dirs"], "its listing is kept"


def test_a_video_found_by_size_uses_its_size_now(tmp_path):
    folder = tmp_path / "Added"
    folder.mkdir()
    video = folder / "Bocchi - 04.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")                     # still copying when the folder was listed
    index = videos.Index("ja", path=str(tmp_path / "videos-ja.json"))
    index.refresh([], [str(folder)])
    listed = os.stat(folder).st_mtime_ns
    video.write_bytes(b"\x1aE\xdf\xa3" * 100)               # the copy finished: the folder's time doesn't move
    os.utime(folder, ns=(listed, listed))
    assert index.find(["Bocchi - 04.mkv"], size=400) == str(video)


def test_a_batch_whose_end_time_cant_be_read_deletes_nothing(ledger):
    job = ledger.queue("ja", 7, "user", None, store_id="s1")
    ledger.end_batch(job, 1, "done", [{"word": "一生懸命", "reading": "", "outcome": "made", "note_id": 101}])
    ledger.set_state(job, "done")
    ledger.conn.execute("UPDATE jobs SET updated_at = 'not a time' WHERE id = ?", (job,))
    anki = UndoAnki()
    anki.add(101, "surasura::connect::" + ledger.tag_id(job), "一生懸命", 1)
    plan = undo.plan(anki, ledger, job)
    assert plan["delete"] == [] and plan["keep"] == [[101, "一生懸命", undo.CHANGED]]


def test_undo_shelf_confirm_puts_the_restore_point_back_through_the_shelfs_adapter(monkeypatch):
    from app.connect import ledger as book
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    h.write_settings(connect_enabled=True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    anki = ShelfAnki({11: 1})
    with book.Ledger() as ledger:
        run = shelf.shelve(anki, ledger, "ja", [shelf.Card(11, 1, "勇気", 7)], "the cap", run="run-a")
    monkeypatch.setattr(shelf, "AnkiConnectAnki", lambda url: anki)
    monkeypatch.setattr("app.cli.connect_verbs._owe_sync", lambda loaded: None)
    code, result = h.call("undo", "--shelf", run, "--confirm")
    assert code == 0 and result["back"] == 1, result
    assert anki.suspended == set()
    with book.Ledger() as ledger:
        assert 11 in shelf.kept(ledger), "put back by you: never shelved again"
