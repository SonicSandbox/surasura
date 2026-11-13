# SPDX-License-Identifier: GPL-3.0-or-later
"""AnkiConnect Extended (add-on 1635024181, a replacement for AnkiConnect): it refuses `setSpecificValueOfCard` for
`due` — "Use native scheduling commands for protected state." — and offers `repositionNewCards` (Anki's own
`sort_cards`) instead. Mattias's field report (3.0.6): "Junban did not make any changes: Use native scheduling
commands for protected state." on every re-order.

Now a position refused that way is written again with `repositionNewCards`, one card a call at exactly its position,
no shift; the address is remembered for the run, so later batches go that way at once. What a wrong answer would
cost: a re-order that never lands (the field report), or one that moves other cards (`shift`) or misreports what it
wrote. Against the engine tests' FakeCollection, never a live Anki.
"""
import pytest

from modules.junban import ankiconnect
from modules.junban.tests.test_reposition import AnkiRefusal, FakeCollection, _collection, _patched

URL = "http://127.0.0.1:8765"
pytestmark = pytest.mark.usefixtures("anki_writer")     # every write holds the Anki-write lock
REFUSAL = "Use native scheduling commands for protected state."


class ExtendedCollection(FakeCollection):
    """AnkiConnect Extended's answers: `due` refused through `setSpecificValueOfCard`, `repositionNewCards` served."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.native_calls = []

    def _multi(self, actions):
        replies = []
        for entry in actions:
            params = entry.get("params") or {}
            if entry.get("action") == "setSpecificValueOfCard" and params.get("keys") == ["due"]:
                replies.append({"result": None, "error": REFUSAL})
            elif entry.get("action") == "repositionNewCards":
                replies.append({"result": self._reposition(**params), "error": None})
            else:
                replies.extend(super()._multi([entry]))
        return replies

    def _reposition(self, orderedCardIds, startPosition, step, shift):
        self.native_calls.append((list(orderedCardIds), startPosition, step, shift))
        moved, not_new = [], []
        for n, card_id in enumerate(orderedCardIds):
            card = self.cards.get(card_id)
            if card is None:
                continue
            if card.get("type") != 0:
                not_new.append(card_id)
                continue
            card["due"] = startPosition + n * step
            self.writes.append((card_id, card["due"]))
            moved.append(card_id)
        return {"requested": len(orderedCardIds), "repositioned": len(moved), "skippedNotNew": not_new,
                "skippedNotFound": [c for c in orderedCardIds if c not in self.cards]}


@pytest.fixture(autouse=True)
def _fresh():
    ankiconnect._NATIVE.clear()
    yield
    ankiconnect._NATIVE.clear()


def _extended(words=("須藤", "散歩", "図書館", "冒険")):
    cards, notes, _ = _collection(list(words))
    return ExtendedCollection(cards, notes)


def test_a_position_refused_as_protected_state_is_written_the_native_way(tmp_path):
    fake = _extended()
    ids = sorted(fake.cards)
    pairs = [(card_id, 100 + 10 * n) for n, card_id in enumerate(ids)]
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, pairs)
    assert failures == [] and sorted(written) == ids
    assert {card_id: fake.cards[card_id]["due"] for card_id in ids} == dict(pairs), "each at exactly its position"
    assert all(len(cards) == 1 and step == 1 and shift is False for cards, _start, step, shift in fake.native_calls), \
        "one card a call, no shift: nothing else moves"


def test_after_one_refusal_the_address_goes_the_native_way_at_once(tmp_path):
    fake = _extended()
    ids = sorted(fake.cards)
    with _patched(fake):
        ankiconnect.set_due(URL, [(ids[0], 50)])
        before = len(fake.requests)
        ankiconnect.set_due(URL, [(ids[1], 60)])
    later = fake.requests[before:]
    sent = [sub["action"] for request in later for sub in (request.get("params") or {}).get("actions", [])]
    assert sent == ["repositionNewCards"], sent


def test_a_card_no_longer_new_is_a_failure_with_its_reason(tmp_path):
    fake = _extended()
    ids = sorted(fake.cards)
    fake.cards[ids[0]]["type"] = 2
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(ids[0], 70), (ids[1], 80)])
    assert written == [ids[1]]
    assert failures == [(ids[0], "It is no longer a new card.")]


def test_plain_ankiconnect_never_sends_reposition_new_cards(tmp_path):
    cards, notes, _ = _collection(["須藤", "散歩"])
    fake = FakeCollection(cards, notes)
    ids = sorted(fake.cards)
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(ids[0], 5), (ids[1], 6)])
    assert failures == [] and sorted(written) == ids
    assert "repositionNewCards" not in str(fake.requests)
