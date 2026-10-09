"""The deleted-card check refuses to clear the library when Anki says every note is gone (P2.4 row 2.4.14, L3.3 wiring:
`Steps.notes_gone` in app/connect/runner.py). Twelve notes all reading as gone is the signature of another collection
answering, not of a learner deleting twelve cards in one go: nothing is marked gone and the store keeps every id. A
smaller number gone (3 of 12) is still named and removed, and Anki open on another profile clears nothing at all.
What a wrong answer would cost: a whole library of made words freed at once because Anki answered from the wrong
collection (every word offered again, every card re-made), or, the other way, a real partial deletion ignored."""
import pytest

from app.connect import anki_session, library, runner
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

BASE_NOTE_ID = 1700000000100  # Anki note ids are millisecond timestamps; the twelve below are 1700000000100 + n
WORDS = ["上層部", "一生懸命", "眼鏡", "老婆", "駐車場", "冒険", "散歩", "旅行", "冷蔵庫", "大学", "新幹線", "相談"]
NOTE_IDS = [BASE_NOTE_ID + n for n in range(len(WORDS))]


class FakeAnki:
    """Only what Steps.notes_gone calls through shelf.gone_notes: find_notes("nid:a,b,...") answers the ids still in
    Anki."""

    def __init__(self, still_there):
        self.still_there = set(still_there)

    def find_notes(self, query):
        assert query.startswith("nid:"), query
        ids = [int(n) for n in query[len("nid:"):].split(",")]
        return [n for n in ids if n in self.still_there]


@pytest.fixture(autouse=True)
def _anki_open_here(monkeypatch):
    # Anki is open on this profile unless a test says otherwise, so the reason check never answers by accident.
    monkeypatch.setattr(anki_session, "waiting", lambda url, settings: None)


def _library_with_twelve_made_words():
    """The library, with Connect's twelve made words (one card each) recorded on its first episode."""
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        library.record_batch(s, item, {w: [i] for w, i in zip(WORDS, NOTE_IDS)}, "2026-10-07T09:00:00Z", batch="1")


def _steps(still_there):
    steps = runner.Steps({"connect_enabled": True})
    steps._anki = lambda: FakeAnki(still_there=still_there)
    return steps


def _store_ids():
    with c.store() as s:
        return library.note_ids(s)


def test_all_twelve_notes_gone_at_once_is_refused_and_the_library_keeps_them_all():
    # Anki has none of the twelve: looks like another collection answering, so nothing is marked gone (a learner
    # deleting every card in one go is not a case the check acts on).
    _library_with_twelve_made_words()
    assert _store_ids() == set(NOTE_IDS)

    assert _steps(still_there=set()).notes_gone("ja") == []
    assert _store_ids() == set(NOTE_IDS)


def test_three_of_twelve_gone_are_named_and_removed_from_the_store_and_no_others():
    # A partial deletion is real: the three gone are named, the other nine stay in the store.
    _library_with_twelve_made_words()
    gone_expected = sorted(NOTE_IDS[:3])
    still = set(NOTE_IDS[3:])

    assert sorted(_steps(still_there=still).notes_gone("ja")) == gone_expected
    assert _store_ids() == set(NOTE_IDS[3:])


def test_a_waiting_anki_clears_nothing_even_when_some_notes_read_gone(monkeypatch):
    # Anki open on another profile answers a reason: the check stops before it touches the store, so its answer
    # (3 of 12 gone here) is not believed and every id stays.
    _library_with_twelve_made_words()
    monkeypatch.setattr(anki_session, "waiting",
                        lambda url, settings: 'Waiting for Anki\'s profile "DevTest": "User 1" is open.')
    still = set(NOTE_IDS[3:])

    assert _steps(still_there=still).notes_gone("ja") == []
    assert _store_ids() == set(NOTE_IDS)
