# SPDX-License-Identifier: GPL-3.0-or-later
"""AnkiConnect Extended (add-on 1635024181, a replacement for AnkiConnect) refuses `setSpecificValueOfCard` for `due`
— "Use native scheduling commands for protected state." — and offers `repositionNewCards` (Anki's own `sort_cards`)
instead. A tester's 3.0.6 report: "Junban did not make any changes: Use native scheduling commands for protected
state." after every re-order, so he couldn't sort his cards. Based on the approach in #417 by Mattias.

Now a position refused with exactly that message is sent again as `repositionNewCards`: one card a sub-action, at
exactly its position, `step` 1, no shift — so nothing else moves, as `setSpecificValueOfCard` moves nothing else; the
address goes that way at once for the rest of the process. What a wrong answer would cost, most first:

  * **Undo that isn't exact** on Extended: a reorder and its Undo, and one of Connect's runs and its own Undo, must
    leave every card where it was — the same end state as plain AnkiConnect, request for request in effect.
  * **A move that moves other cards** (`shift`, or several cards in one call: Anki numbers them per note) or a write
    reported that never landed (a card no longer new is skipped by Anki: that is a failure, with its reason).
  * **Plain AnkiConnect slowed or changed**: it never sees the new action, and sends exactly the requests it always did.
  * **Another refusal read as this one**: only Extended's own message switches the address over.

Against the engine tests' FakeCollection (and Connect's scene), never a live Anki.
"""
import copy

import pytest

from modules.junban import ankiconnect, auto, reposition, undo
from modules.junban.tests.connect_scene import ConnectCollection, scene, settings
from modules.junban.tests.test_reposition import FakeCollection, _collection, _patched

URL = "http://127.0.0.1:8765"
REFUSAL = "Use native scheduling commands for protected state."


class Extended:
    """AnkiConnect Extended's answers (read from its own code, 2026-11-13: `legacy.py` `expert_card`, `extended.py`
    `repositionNewCards`), mixed into a fake collection: `setSpecificValueOfCard` refuses `due` with the message above
    (flags it still writes); `repositionNewCards` is Anki's `sort_cards` — new cards only, positions per note in the
    order given, `startPosition` from 1, `shift` moving every new card at or after the start — answering
    `repositioned` as a count, `skippedNotNew` / `skippedNotFound` as lists."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.native_calls = []
        self.refused = []

    def _multi(self, actions):
        replies = []
        for entry in actions:
            params = entry.get("params") or {}
            if entry.get("action") == "setSpecificValueOfCard" and params.get("keys") == ["due"]:
                self.refused.append(params.get("card"))
                replies.append({"result": None, "error": REFUSAL})
            elif entry.get("action") == "repositionNewCards":
                replies.append(self._reposition(**params))
            else:
                replies.extend(super()._multi([entry]))
        return replies

    def _reposition(self, orderedCardIds, startPosition=0, step=1, randomize=False, shift=False):
        self.native_calls.append((list(orderedCardIds), startPosition, step, shift))
        if not isinstance(startPosition, int) or startPosition < 1:
            return {"result": None, "error": f"startPosition should be an integer >= 1: {startPosition}"}
        if shift:
            for card in self.cards.values():
                if card["type"] == 0 and card["due"] >= startPosition and card["cardId"] not in orderedCardIds:
                    card["due"] += step * len(orderedCardIds)
        notes, moved, not_new, missing = [], [], [], []
        for card_id in orderedCardIds:
            card = self.cards.get(card_id)
            if card is None:
                missing.append(card_id)
            elif card["type"] != 0:
                not_new.append(card_id)
            else:
                if card["note"] not in notes:
                    notes.append(card["note"])
                card["due"] = startPosition + notes.index(card["note"]) * step
                self.writes.append((card_id, card["due"]))
                moved.append(card_id)
        return {"result": {"requested": len(orderedCardIds), "repositioned": len(moved),
                           "skippedNotNew": not_new, "skippedNotFound": missing}, "error": None}


class ExtendedCollection(Extended, FakeCollection):
    pass


class ExtendedConnect(Extended, ConnectCollection):
    pass


@pytest.fixture(autouse=True)
def _fresh():
    getattr(ankiconnect, "_REPOSITION_NATIVELY", set()).clear()     # which addresses refused: per process
    yield
    getattr(ankiconnect, "_REPOSITION_NATIVELY", set()).clear()


def _extended(words=("須藤", "散歩", "図書館", "冒険")):
    cards, notes, _ = _collection(list(words))
    return ExtendedCollection(cards, notes)


def _sent(fake, since=0):
    return [sub["action"] for request in fake.requests[since:]
            for sub in (request.get("params") or {}).get("actions", [])]


def _as_extended(fake):
    """The same collection behind AnkiConnect Extended."""
    return ExtendedConnect(copy.deepcopy(list(fake.cards.values())), copy.deepcopy(list(fake.notes.values())),
                           actions=fake.actions)


def _state(fake):
    return {card_id: (card["due"], card["queue"], card.get("flags", 0)) for card_id, card in fake.cards.items()}


# --------------------------------------------------------------------------- #
# The wire: set_due
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("anki_writer")
def test_a_position_refused_as_protected_state_is_written_the_native_way_one_card_a_call_no_shift():
    fake = _extended()
    ids = sorted(fake.cards)
    pairs = [(card_id, 100 + 10 * n) for n, card_id in enumerate(ids)]
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, pairs)
    assert failures == [] and sorted(written) == ids
    assert {card_id: fake.cards[card_id]["due"] for card_id in ids} == dict(pairs), "each at exactly its position"
    assert [cards for cards, _start, _step, _shift in fake.native_calls] == [[card_id] for card_id in ids]
    assert all(step == 1 and shift is False for _cards, _start, step, shift in fake.native_calls), "nothing else moves"


@pytest.mark.usefixtures("anki_writer")
def test_after_one_refusal_the_address_goes_the_native_way_at_once_and_flags_stay_as_they_are():
    fake = _extended()
    ids = sorted(fake.cards)
    with _patched(fake):
        ankiconnect.set_due(URL, [(ids[0], 50)])
        before = len(fake.requests)
        written, failures = ankiconnect.set_due(URL, [(ids[1], 60), (ids[2], 61)])
        assert _sent(fake, before) == ["repositionNewCards", "repositionNewCards"], "one request, no refused one first"
        assert len(fake.requests) - before == 1
        flagged, flag_failures = ankiconnect.set_flags(URL, [(ids[3], 7)])
    assert written == [ids[1], ids[2]] and failures == []
    assert flagged == [ids[3]] and not flag_failures and fake.cards[ids[3]]["flags"] == 7, "flags: still a value write"


@pytest.mark.usefixtures("anki_writer")
def test_a_card_no_longer_new_or_gone_is_a_failure_with_its_reason_never_a_write():
    fake = _extended()
    ids = sorted(fake.cards)
    fake.cards[ids[0]]["type"] = 2                      # studied on the phone meanwhile: Anki leaves it
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(ids[0], 70), (ids[1], 80), (1789712099999, 90)])
    assert written == [ids[1]]
    assert failures == [(ids[0], "It is no longer a new card."), (1789712099999, "Anki no longer has this card.")]


@pytest.mark.usefixtures("anki_writer")
def test_a_position_below_one_is_never_sent_the_native_way():
    """Anki's own reposition starts at 1: a 0 is named as a failure, never sent (an answer of an unknown shape)."""
    fake = _extended()
    ids = sorted(fake.cards)
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(ids[0], 0), (ids[1], 5)])
    assert written == [ids[1]] and [card_id for card_id, _why in failures] == [ids[0]]
    assert [cards for cards, *_rest in fake.native_calls] == [[ids[1]]]
    assert fake.cards[ids[0]]["due"] != 0


@pytest.mark.usefixtures("anki_writer")
def test_plain_ankiconnect_sends_exactly_what_it_always_did():
    cards, notes, _ = _collection(["須藤", "散歩", "図書館"])
    fake = FakeCollection(cards, notes)
    ids = sorted(fake.cards)
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(card_id, 5 + n) for n, card_id in enumerate(ids)], chunk=2)
    assert failures == [] and written == ids
    assert len(fake.requests) == 2 and _sent(fake) == ["setSpecificValueOfCard"] * 3, "one multi a chunk, as before"
    assert "repositionNewCards" not in str(fake.requests)


@pytest.mark.usefixtures("anki_writer")
@pytest.mark.parametrize("error", ["Card was not found", "use native scheduling commands", "Protected state."])
def test_another_refusal_is_a_failure_and_never_switches_the_address(error):
    """Only Extended's own message, whole, means "use repositionNewCards": anything else (a card gone, a half of it)
    is that card's failure, as before."""
    cards, notes, _ = _collection(["須藤", "散歩"])

    class Refusing(FakeCollection):
        def _multi(self, actions):
            return [{"result": None, "error": error} for _entry in actions]
    fake = Refusing(cards, notes)
    ids = sorted(fake.cards)
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(ids[0], 5)])
    assert written == [] and failures == [(ids[0], error)]
    assert "repositionNewCards" not in str(fake.requests) and URL not in ankiconnect._REPOSITION_NATIVELY


@pytest.mark.usefixtures("anki_writer")
def test_the_message_is_read_whatever_its_case_or_spacing():
    cards, notes, _ = _collection(["須藤"])

    class Shouting(ExtendedCollection):
        def _multi(self, actions):
            replies = super()._multi(actions)
            return [{"result": None, "error": "  USE NATIVE SCHEDULING COMMANDS FOR PROTECTED STATE  "}
                    if reply.get("error") == REFUSAL else reply for reply in replies]
    fake = Shouting(cards, notes)
    card_id = sorted(fake.cards)[0]
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(card_id, 9)])
    assert written == [card_id] and failures == [] and fake.cards[card_id]["due"] == 9


@pytest.mark.usefixtures("anki_writer")
def test_an_answer_that_isnt_one_card_moved_is_never_counted_as_a_write():
    """`repositioned` must be exactly 1 (never `true`, a list, or missing): a reply Junban can't read is not a write."""
    cards, notes, _ = _collection(["須藤", "散歩", "図書館", "冒険"])
    answers = iter([True, [1], None, 2])

    class Odd(ExtendedCollection):
        def _reposition(self, **params):
            reply = super()._reposition(**params)
            reply["result"]["repositioned"] = next(answers)
            return reply
    fake = Odd(cards, notes)
    ids = sorted(fake.cards)
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(card_id, 20 + n) for n, card_id in enumerate(ids)])
    assert written == [] and [card_id for card_id, _why in failures] == ids


@pytest.mark.usefixtures("anki_writer")
def test_plain_ankiconnect_back_at_a_remembered_address_is_written_the_plain_way():
    """The add-on swapped back while Surasura runs: `repositionNewCards` is unsupported there, so the address is
    forgotten and that batch written with `setSpecificValueOfCard` — never a run of failures."""
    cards, notes, _ = _collection(["須藤", "散歩"])

    class Plain(FakeCollection):
        def _multi(self, actions):
            if any(entry.get("action") == "repositionNewCards" for entry in actions):
                return [{"result": None, "error": "unsupported action"} for _entry in actions]
            return super()._multi(actions)
    fake = Plain(cards, notes)
    ids = sorted(fake.cards)
    ankiconnect._REPOSITION_NATIVELY.add(URL)
    with _patched(fake):
        written, failures = ankiconnect.set_due(URL, [(ids[0], 31), (ids[1], 32)])
    assert failures == [] and written == ids and fake.cards[ids[1]]["due"] == 32
    assert URL not in ankiconnect._REPOSITION_NATIVELY


# --------------------------------------------------------------------------- #
# Undo stays exact on Extended
# --------------------------------------------------------------------------- #
def _reordered(root, monkeypatch, extended):
    """The 順 window's Reorder on the scene under `root` -> (fake, its state before, the report)."""
    root.mkdir()
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))
    fake = scene(root)
    fake = _as_extended(fake) if extended else fake
    before = _state(fake)
    with _patched(fake):
        report = reposition.run(settings(), refresh=False)
    assert report["ok"], report["problems"]
    return fake, before, report


def test_a_reorder_on_extended_lands_as_on_plain_ankiconnect_and_one_undo_puts_every_card_back(tmp_path, monkeypatch):
    """The 順 window's Reorder (positions, the cards not on the list tagged, flagged, suspended), then Undo: on
    Extended the deck ends exactly as on plain AnkiConnect, and Undo leaves every card as it was — position, queue,
    flag."""
    plain, _before, _report = _reordered(tmp_path / "plain", monkeypatch, extended=False)
    fake, before, report = _reordered(tmp_path / "extended", monkeypatch, extended=True)
    assert fake.refused and fake.native_calls, "refused once, then the native way"
    assert len(fake.refused) == 1 or len(set(fake.refused)) == len(fake.refused), "never refused twice for a card"
    assert sorted(report["written"]) == sorted(c for c, _due in fake.writes)
    assert _state(fake) == _state(plain), "the same deck as plain AnkiConnect leaves"
    with _patched(fake):
        restored = reposition.restore(settings())
    assert restored["ok"], restored["problems"]
    assert _state(fake) == before


def test_a_connect_run_on_extended_and_its_own_undo_put_back_exactly_what_it_moved(tmp_path):
    fake = _as_extended(scene(tmp_path))
    before = _state(fake)
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(settings(), list_current=True, positions_only=True, run_id=run_id)
    assert done["outcome"] == "ran" and fake.native_calls, done
    saved = undo.load("ja", run_id=run_id)
    assert saved["complete"] is True
    assert {int(c): d for c, d in saved["after"].items()} == {c: fake.cards[c]["due"] for c in map(int, saved["after"])}
    with _patched(fake):
        put_back = reposition.restore_run(settings(), run_id)
    assert put_back["ok"], put_back["problems"]
    assert {c: due for c, (due, _q, _f) in _state(fake).items()} == {c: due for c, (due, _q, _f) in before.items()}
