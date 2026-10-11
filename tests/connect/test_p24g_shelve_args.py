"""The shelf's plan gets the cap and the waiting count in their own places (P2.4-E17; `Steps._shelve`).

`shelf.plan(waiting, needed_ranks, cap, count, ...)` takes the cap third and the waiting count fourth. This test
records the positional arguments the plan is handed on a 305-waiting, cap-300 run and asserts the cap arrives as the
third and the count as the fourth. The mutant swaps the two in `Steps._shelve`, so the plan would hold back 305 cards
when the cap is 300.

What a wrong answer would cost: with the two swapped, the shelf decides against the wrong limit, so Connect either
shelves too few waiting cards (the list floods past the cap) or too many (new cards stall behind a shelf that is too
full). Against a Steps whose Anki, store and list readers are fakes; the ledger is a real SQLite file in a temp folder.
"""
import contextlib

import pytest

from app.connect import runner, shelf
from app.connect.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def test_shelve_hands_the_plan_the_cap_third_and_the_waiting_count_fourth(monkeypatch, ledger):
    # the shelf's readers are fakes: an empty store, no made notes, no pinned or finished items, no waiting cards
    monkeypatch.setattr(shelf, "made_notes", lambda store: {})
    monkeypatch.setattr(shelf, "pinned_items", lambda store: set())
    monkeypatch.setattr(shelf, "finished_items", lambda store, made: set())
    monkeypatch.setattr(shelf, "cards", lambda anki, query, made: [])

    # the plan records what it is handed and chooses nothing, so the shelve step is never reached
    seen = []

    def recording_plan(*args, **kwargs):
        seen.append(args)
        return []

    monkeypatch.setattr(shelf, "plan", recording_plan)

    steps = runner.Steps({"connect_enabled": True})
    steps._list_order = lambda lang: {}
    steps._top_words = lambda lang, store: {}
    steps._anki = lambda: object()

    @contextlib.contextmanager
    def _open(lang):
        yield object()

    steps._open = _open

    # 305 cards are waiting and the cap is 300: the cap is the limit, the count is the waiting number
    shelved = steps._shelve("ja", ledger, [{"word": "勇気"}], 305, 300)

    assert shelved == 0
    assert len(seen) == 1
    args = seen[0]
    assert args[2] == 300, "the third argument must be the cap (300), not the waiting count"
    assert args[3] == 305, "the fourth argument must be the waiting count (305), not the cap"
