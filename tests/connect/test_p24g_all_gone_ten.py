"""The deleted-card check refuses when exactly ALL_GONE_MIN (10) notes all read as gone: nothing is marked gone and the
store keeps every id (P2.4 row 2.4.14, `Steps.notes_gone` in app/connect/runner.py). The threshold is inclusive: ten
notes all gone is the same signature of another collection answering as twelve. Mutant P2.4-E20 changes `>=` to `>`,
so exactly ten all gone would be marked gone and returned. What a wrong answer would cost: a library of ten made words
freed at once because Anki answered from the wrong collection (every word offered again, every card re-made)."""
import pytest

from app.connect import anki_session, library, runner
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

BASE_NOTE_ID = 1700000000100  # Anki note ids are millisecond timestamps; the ten below are 1700000000100 + n
WORDS = ["上層部", "一生懸命", "眼鏡", "老婆", "駐車場", "冒険", "散歩", "旅行", "冷蔵庫", "大学"]
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
    # Anki is open on this profile, so the reason check never answers by accident.
    monkeypatch.setattr(anki_session, "waiting", lambda url, settings: None)


def _library_with_ten_made_words():
    """The library, with Connect's ten made words (one card each) recorded on its first episode."""
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


def test_exactly_ten_notes_all_gone_is_refused_at_the_threshold_and_the_library_keeps_them_all():
    # Ten is the threshold itself (ALL_GONE_MIN = 10, inclusive): all ten reading as gone looks like another
    # collection answering, so nothing is marked gone and the store keeps all ten ids.
    _library_with_ten_made_words()
    assert _store_ids() == set(NOTE_IDS)

    assert _steps(still_there=set()).notes_gone("ja") == []
    assert _store_ids() == set(NOTE_IDS)
