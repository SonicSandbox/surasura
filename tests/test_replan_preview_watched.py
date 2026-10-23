"""W-1: a watched mark moves cards the same way both ways — after the Generate the mark starts, never on the window's
fast re-order (app/replan_preview.py: the set-aside files are the run signature's "reference" part, so
`plan_engine.check` asks for a Generate first whichever way a mark moves them).

On RP-2's Japanese library (tests/plan_file_cases.py: twelve files of real text across NOW, Soon and 6+ Months), with
your 順 actions on (tag + suspend, as Sonic runs them) and a fake AnkiConnect holding a card for every listed word.
What these prove:

  - a stone on an episode whose words live nowhere else: the host's job writes nothing to Anki — no position, no tag,
    no suspend — and asks for the Generate; the Generate's own re-order then steps those cards back;
  - its un-marking: the same — nothing written until the Generate, which brings the cards back;
  - a stone and a Finished drag in one settle: the stricter wins (nothing until the Generate);
  - a Finished drag alone: today's fast re-order, at once (its cards step back before any Generate).

What a wrong answer would cost a learner: a mis-clicked stone suspends cards within seconds while its Undo waits for a
whole Generate to bring them back.
"""
import pytest

pytest.importorskip("modules.junban")

from app import library_store, plan_engine, replan_preview  # noqa: E402
from modules.junban.tests.test_reposition import _collection, _patched  # noqa: E402
from tests.test_replan_preview import (ACTIONS, DECK, MarkingCollection, _generate, _host, _kinds,  # noqa: E402,F401
                                       _list_words, _settings_file, _word_cards, lib)

# Connect on: an unattended run brings a returning word's card back only then (`connect.unsuspends`)
ACTING = dict(junban_auto_actions=True, junban_later_tag=True, junban_later_suspend=True, connect_enabled=True)
WRITES = ("position", "addTags", "suspend", "unsuspend", "flag", "re-check")


class ParkingCollection(MarkingCollection):
    """The fake collection, also answering the search for the cards Junban parked (`connect.parked_query`: new,
    suspended, its `::later` tag on), so a returning word's card is found as Anki finds it."""

    def _find(self, query):
        if "-is:suspended" in query or '"tag:' not in query:
            return super()._find(query)
        deck, tag = query.split('"')[1], query.split('"tag:')[1].split('"')[0]
        return sorted(card["cardId"] for card in self.cards.values()
                      if card["deckName"] == deck and card["type"] == 0 and card["queue"] == -1
                      and tag in (self.notes[card["note"]].get("tags") or []))


def _card_word(row):
    """The word a card carries for a list row, as `_list_words` reads it."""
    word, orth = (row.get("Word") or "").strip(), (row.get("Orth") or "").strip()
    key = orth or word
    return word if len(key) == 1 and key != word else key


def _replan_without(store, plan, ids, leave=()):
    order = replan_preview._snapshot(store)[1]
    ranked = sorted(order[key] + (item_id,) for key, item_id in
                    ((library_store.path_key(entry[0]), item_id) for entry, item_id in zip(plan.files, ids))
                    if key in order and item_id not in leave)
    return plan_engine.Engine(plan, ids).replan([(item_id, tier) for _r, _p, tier, item_id in ranked])


def _episode_with_its_own_words(store):
    """A NOW episode some listed words are met only in, and those words (as cards carry them)."""
    plan = plan_engine.load(replan_preview.plan_path())
    ids = [store.item_id(entry[0]) for entry in plan.files]
    full = {_card_word(row) for row in _replan_without(store, plan, ids).progressive}
    for item in store.ids("now"):
        gone = full - {_card_word(row) for row in _replan_without(store, plan, ids, (item,)).progressive}
        if gone:
            return item, sorted(gone)
    raise AssertionError("no NOW episode holds a word of its own (RP-2 should)")


def _acting(root, store, monkeypatch):
    from modules.junban import connect
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", True)
    _settings_file(root, **ACTING)
    episode, own = _episode_with_its_own_words(store)
    words = list(dict.fromkeys(_list_words(root, 40) + own))
    cards, notes, _ = _collection(words, dues=list(range(3000 + len(words) - 1, 2999, -1)), deck=DECK)
    fake = ParkingCollection(cards, notes, actions=ACTIONS)
    return episode, _word_cards(fake, own), fake


def _job(fake, host, kind="move"):
    start = len(fake.requests)
    host._job(kind)
    return [kind for kind in _kinds(fake.requests[start:]) if kind in WRITES]


def _suspended(fake, card_ids):
    return {card_id for card_id in card_ids if fake.cards[card_id]["queue"] == -1}


def test_a_stone_and_its_un_marking_each_wait_for_the_generate_before_any_card_moves(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    asked = []
    host, _lines = _host(generate=asked.append)
    with _patched(fake):
        host._job("catch-up")                          # the ladder laid, the plan recorded: nothing owed
        assert not _suspended(fake, own)
        asked.clear()

        store.set_watched([episode])
        assert _job(fake, host) == [], "a stone wrote to Anki before the Generate"
        assert not _suspended(fake, own), "a stone suspended its words' cards before the Generate"
        assert asked == ["generate-first: reference"], asked
        _generate(root)                                # the Generate the mark started (the journey keeper's)
        _job(fake, host, "generate")
        assert _suspended(fake, own) == set(own), "after the Generate the stone's words step back"

        asked.clear()
        store.set_watched([episode], False)
        assert _job(fake, host) == [], "un-marking wrote to Anki before the Generate"
        assert _suspended(fake, own) == set(own), "nothing moves back before the Generate either"
        _generate(root)
        _job(fake, host, "generate")
    assert not _suspended(fake, own), "after the Generate the words and their cards are back"


def test_a_stone_and_a_finished_drag_in_one_settle_wait_for_the_generate(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    host, _lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        store.set_watched([episode])
        store.finish([store.ids("goal")[0]])
        assert _job(fake, host) == [], "the stricter wins: a stone with a tier move waits for the Generate"
    assert not _suspended(fake, own)


def test_a_finished_drag_alone_still_re_orders_at_once(lib, monkeypatch):
    # why: tier moves keep today's fast re-order exactly — only a mark waits
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    host, _lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        store.finish([episode])
        plan = plan_engine.load(replan_preview.plan_path())
        verdict = host._verdict(plan, host._parts(host._settings(), store), store)
        assert verdict == ("replan-now", ("files-removed",)), verdict
        assert "suspend" in _job(fake, host)
    assert _suspended(fake, own) == set(own), "Finished steps the show's words back at once, as before"
