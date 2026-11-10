"""The shelf's suspend, un-suspend and tag writes happen only while Anki's writer is held (P2.4 row 2.4.11; mutant
P2.4-F18; `tidy` while you review is P2.5's `test_p25_mutant_gaps.py`).

What a wrong answer would cost: a suspend or a tag written while 順 or Backfill writes the same notes (Anki's one
writer, R-6).

The fake Anki fails any suspend / unsuspend / tag change made outside its writer, so the shelf's own call order is what
is checked, not what the shelf says it did. The ledger is a real SQLite file in a temp folder; Anki is never reached.
"""
import contextlib

from app.connect import shelf
from tests.connect.test_shelf_anki import FakeAnki, ledger  # noqa: F401  (fixture)


class LockedAnki(FakeAnki):
    """FakeAnki whose writes refuse to run unless its writer is held; `entered` lists each writer's verb."""

    def __init__(self, note_of):
        super().__init__(note_of)
        self.held = False
        self.entered = []

    @contextlib.contextmanager
    def writer(self, verb):
        assert not self.held, "the shelf never nests its writer"
        self.entered.append(verb)
        self.held = True
        try:
            yield
        finally:
            self.held = False

    def _write(self):
        assert self.held, "an Anki write outside Connect's writer"

    def suspend(self, ids):
        self._write()
        super().suspend(ids)

    def unsuspend(self, ids):
        self._write()
        super().unsuspend(ids)

    def add_tag(self, note_ids, tag):
        self._write()
        super().add_tag(note_ids, tag)

    def remove_tag(self, note_ids, tag):
        self._write()
        super().remove_tag(note_ids, tag)


def _three(ledger):
    anki = LockedAnki({11: 1, 12: 2, 13: 3})
    chosen = [shelf.Card(11, 1, "上層部", 7), shelf.Card(12, 2, "一生懸命", 7), shelf.Card(13, 3, "気配", 7)]
    assert shelf.shelve(anki, ledger, "ja", chosen, "a quarter of the cap", run="run-a") == "run-a"
    return anki


def test_shelve_tags_and_suspends_inside_one_writer(ledger):
    anki = _three(ledger)
    assert anki.entered == ["Connect's shelf"]
    assert anki.suspended == {11, 12, 13}
    assert all(anki.tags[n] == {shelf.SHELF_TAG} for n in (1, 2, 3))


def test_restore_unsuspends_and_untags_inside_its_own_writer(ledger):
    anki = _three(ledger)
    anki.entered.clear()
    assert shelf.restore(anki, ledger, "run-a") == 3
    assert anki.entered == ["Connect's shelf (restore)"]
    assert anki.suspended == set()
    assert all(anki.tags[n] == set() for n in (1, 2, 3))

