"""Cards deleted in Anki are found in chunks of 500 (app/connect/shelf.py `gone_notes`, app/connect/library.py
`notes_gone`): the store holds note ids for the learner's own cards and Connect's; a note Anki no longer has must be
found, however many ids there are, and nothing is marked gone when Anki doesn't answer. What a wrong answer would
cost: a card the learner deleted stays "in Anki" forever (its word never freed), or a card still there is marked gone
(a made word offered again), or an Anki outage silently marks the whole store as deleted."""
import pytest

from app.anki_connect import AnkiError
from app.connect import library, shelf

BASE_NOTE_ID = 1_700_000_000_000  # Anki note ids are millisecond timestamps, so ids are big and sparse


class FakeAnki:
    """Only what gone_notes calls: find_notes("nid:a,b,...") answers the ids still in Anki. Counts the requests and
    records each chunk's size, so a test can see how the ids were split."""

    def __init__(self, still_there, offline=False):
        self.still_there = set(still_there)
        self.offline = offline
        self.calls = []

    def find_notes(self, query):
        if self.offline:
            raise AnkiError("Anki is closed", kind="offline")
        assert query.startswith("nid:"), query
        ids = [int(n) for n in query[len("nid:"):].split(",")]
        self.calls.append(len(ids))
        return [n for n in ids if n in self.still_there]


class StoreWithNotesGone:
    """A stand-in for the store once its half exists: it records what it was told."""

    def __init__(self):
        self.told = []

    def notes_gone(self, ids):
        self.told.append(ids)


def _ids(count):
    return [BASE_NOTE_ID + 7 * i for i in range(count)]


def test_1200_ids_take_three_requests_and_find_a_gone_note_in_the_last_chunk():
    # 1,200 ids = chunks of 500, 500, 200. The gone note sits in the last chunk (index 1199), so a loop that stops
    # after the first chunk would miss it and report only the earlier gone notes.
    ids = _ids(1200)
    gone = {ids[5], ids[700], ids[1199]}
    anki = FakeAnki(still_there=set(ids) - gone)

    found = shelf.gone_notes(anki, list(reversed(ids)))  # given out of order: the answer is still sorted

    assert found == sorted(gone)
    assert anki.calls == [500, 500, 200]
    assert shelf.GONE_CHUNK == 500


def test_nothing_is_gone_when_anki_still_has_every_note():
    ids = _ids(3)
    anki = FakeAnki(still_there=ids)

    assert shelf.gone_notes(anki, ids) == []
    assert anki.calls == [3]


def test_an_empty_store_asks_anki_nothing():
    anki = FakeAnki(still_there=[])

    assert shelf.gone_notes(anki, []) == []
    assert anki.calls == []  # why: no request for an empty store, not one with an empty "nid:" query


def test_an_offline_anki_raises_and_marks_nothing_gone():
    # Anki closed: the error must reach the caller. A swallowed error here would read as "every note is gone".
    anki = FakeAnki(still_there=[], offline=True)

    with pytest.raises(AnkiError) as caught:
        shelf.gone_notes(anki, _ids(10))

    assert caught.value.kind == "offline"


def test_a_store_without_notes_gone_is_a_no_op():
    # Until the store has its half, nothing is recorded and the answer says so (False).
    assert library.notes_gone(object(), [BASE_NOTE_ID]) is False


def test_notes_gone_passes_the_sorted_ids_to_a_store_that_has_the_method():
    store = StoreWithNotesGone()

    assert library.notes_gone(store, {BASE_NOTE_ID + 14, BASE_NOTE_ID}) is True
    assert store.told == [[BASE_NOTE_ID, BASE_NOTE_ID + 14]]


def test_notes_gone_with_nothing_gone_does_not_call_the_store():
    # Why: an empty answer is not a change, so the store is not asked to rewrite its links.
    store = StoreWithNotesGone()

    assert library.notes_gone(store, []) is False
    assert store.told == []
