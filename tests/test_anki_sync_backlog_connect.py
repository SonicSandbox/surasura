"""Connect's waiting cards in the *In Anki* backlog (`app/anki_sync.py`: `backlog_query`, `sync_backlog`).

**The rule this pins:** with Connect's preview on, the backlog asks Anki for Connect's own waiting cards
(tagged `surasura::connect::*`) in any deck, so the report's *In Anki* mark and Junban see what Connect made;
with it off the query is exactly as before. The backlog file records which scope it was read in, and a
scope change (preview switched on or off) reads every note again, because the notes it holds were found by
the other query.

**What a wrong answer would cost:** with the tag term missing, a card Connect made waits in an unknown deck
and the report shows it as not in Anki, so Junban would place a second copy of the word. With the scope not
recorded, or not re-read on a change, a backlog read with the preview off would keep serving notes the new
scope never checked, and turning the preview on would leave Connect's cards out until a deck changed.

Anki is always a fake: `find_notes`, `notes_info` and `multi` are patched on `app.anki_connect`, and the
preview switch on `anki_sync._connect_on`. Nothing reaches the network.
"""
import os

import pytest

from app import anki_connect, anki_sync
from app.path_utils import get_user_files_path

_SOURCE = "[SubsPlease] Tetsunabe no Jan! - 04 (1080p)"
_CONNECT_TERM = '"tag:surasura::connect::*"'


def _note(note_id, word, freqsort="30265"):
    """A note shaped as Anki's notesInfo gives it: named fields with their order (Lapis, as anki_miner fills it)."""
    return {"noteId": note_id, "fields": {
        "Expression": {"value": word, "order": 0},
        "Sentence": {"value": f"こいつは最低の{word}だよ。", "order": 1},
        "MiscInfo": {"value": f"{_SOURCE} @ 00:01:36", "order": 2},
        "FreqSort": {"value": freqsort, "order": 3},
    }}


class FakeAnki:
    """The three AnkiConnect calls the backlog makes, over a small in-memory set of notes."""

    def __init__(self, notes):
        self.notes = notes              # {note_id: note dict}
        self.queries = []               # every findNotes query, in order
        self.asked = []                 # every id asked for with notesInfo, in order

    def find_notes(self, url, query):
        self.queries.append(query)
        return list(self.notes)

    def notes_info(self, url, ids, chunk=250):
        self.asked.extend(ids)
        return [self.notes[n] for n in ids if n in self.notes]

    def multi(self, actions, url, timeout=60):
        # The delta path asks the note ids and, in the same request, the edited ones: none were edited here.
        self.queries.append(actions[0]["params"]["query"])
        return [{"result": list(self.notes), "error": None}, {"result": [], "error": None}]


@pytest.fixture
def fake(monkeypatch):
    anki = FakeAnki({101: _note(101, "上層部"), 102: _note(102, "気配")})
    monkeypatch.setattr(anki_connect, "find_notes", anki.find_notes)
    monkeypatch.setattr(anki_connect, "notes_info", anki.notes_info)
    monkeypatch.setattr(anki_connect, "multi", anki.multi)
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    return anki


def test_the_connect_term_joins_the_deck_query_only_with_the_preview_on():
    """Rule (a): the deck terms and Connect's tag term are OR-ed inside the parentheses, and new,
    unsuspended cards are kept either way. Without the preview the tag term is not asked at all."""
    assert anki_sync.backlog_query(["TheBank"], connect=True) == (
        '(deck:"TheBank" OR "tag:surasura::connect::*") is:new -is:suspended')
    assert anki_sync.backlog_query(["TheBank"]) == '(deck:"TheBank") is:new -is:suspended'
    assert _CONNECT_TERM not in anki_sync.backlog_query(["TheBank"], connect=False)


def test_a_backlog_read_with_the_preview_on_asks_anki_with_the_connect_query_and_records_it(fake, monkeypatch):
    """Rule (b): the read with the preview on sends the connect query to Anki and saves `"connect": true`
    in the backlog file, so the next read knows which scope the notes belong to."""
    monkeypatch.setattr(anki_sync, "_connect_on", lambda: True)

    count, error = anki_sync.sync_backlog("ja", None, ["TheBank"], [])

    assert (count, error) == (2, None)
    assert fake.queries == [anki_sync.backlog_query(["TheBank"], connect=True)]
    assert anki_sync.load_backlog("ja").get("connect") is True
    assert anki_sync.backlog_keys("ja") == {"上層部", "気配"}


def test_a_backlog_saved_with_the_preview_off_is_read_in_full_when_the_preview_turns_on(fake, monkeypatch):
    """Rule (c): a backlog read with the preview off, read again with it on, asks Anki about every note,
    not only the ones it has not seen: the scope changed, so the saved notes are not trusted."""
    monkeypatch.setattr(anki_sync, "_connect_on", lambda: False)
    anki_sync.sync_backlog("ja", None, ["TheBank"], [])
    assert anki_sync.load_backlog("ja").get("connect") is None, "a backlog read with the preview off records no scope"
    assert sorted(fake.asked) == [101, 102]

    fake.asked.clear()
    monkeypatch.setattr(anki_sync, "_connect_on", lambda: True)
    count, error = anki_sync.sync_backlog("ja", None, ["TheBank"], [])

    assert (count, error) == (2, None)
    # Why: with the mutant the saved notes still match, so only the notes Anki added since would be asked.
    assert sorted(fake.asked) == [101, 102], "a scope change reads every note again, not only new ones"
