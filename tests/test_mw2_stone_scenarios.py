"""M-W2: what a stone (an episode marked watched) does to a learner's Anki cards, through the window's re-order host
and Junban, on real Generates (W-1 scope §4–§5; drill A2's steps 3–5 on fakes; the DevTest half is drill A3's step 5,
`tests/connect/live_order_drill.py`).

On RP-2's Japanese library (tests/plan_file_cases.py: twelve files of real text across NOW, Soon and 6+ Months), 順's
actions on (tag + suspend, as Sonic runs them) and a fake AnkiConnect holding a card for 40 listed words plus the words
one NOW episode holds alone. No new Junban code: a word the stone takes off the list goes to "Cards not on your list"
exactly as a Finished show's does. What these prove, Connect on and off:

  - mark → Generate → the episode's own words' cards are tagged `Surasura::later` and suspended, the rest in list order;
  - un-mark → Generate → those cards are unsuspended, the tag comes off, and every listed card is in list order;
  - *Undo the last reorder* right after the stone's re-order puts every card's due, suspended state and tag back;
  - a word the episode shares with a file still counted keeps its card on the list, unsuspended;
  - a pinned episode's cards (*Study its cards first*) stay, stone or not: the pin is the later click;
  - everything watched parks the same cards as everything Finished (one rule; today all of them).

What a wrong answer would cost a learner: cards suspended for good after a stone and its Undo, or a pinned show's cards
hidden by a watched mark.
"""
import os

import pytest

pytest.importorskip("modules.junban")

from modules.junban import reposition  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402
from tests.test_replan_preview import _generate, _host, _list_words, _settings_file, _word_cards, lib  # noqa: E402,F401
from tests.test_replan_preview_watched import ACTING, _acting, _job, _suspended  # noqa: E402

LATER = "Surasura::later"


def _tags(fake, card_id):
    return set(fake.notes[fake.cards[card_id]["note"]].get("tags") or [])


def _state(fake):
    """Every card's (due, queue) and its note's tags: what Undo must put back. The `Surasura::for::<show>` label is
    left out: it describes the order as it stands, and the next re-order sets it (`modules/junban/show_tags.py`, "Not
    an undo matter")."""
    return {card_id: (card["due"], card["queue"],
                      tuple(sorted(t for t in _tags(fake, card_id) if not t.startswith("Surasura::for::"))))
            for card_id, card in fake.cards.items()}


def _in_list_order(fake, root):
    """True when the listed, unsuspended new cards sorted (due, cardId) follow the list's own order (each word at the
    row where it is first met)."""
    rank = {word: i for i, word in enumerate(_list_words(root))}
    word_of = {cid: next(iter(fake.notes[c["note"]]["fields"].values()))["value"] for cid, c in fake.cards.items()}
    queue = sorted((c for c in fake.cards.values() if c["queue"] == 0 and word_of[c["cardId"]] in rank),
                   key=lambda c: (c["due"], c["cardId"]))
    ranks = [rank[word_of[c["cardId"]]] for c in queue]
    return ranks == sorted(ranks)


def _mark_and_generate(root, store, fake, host, episode, on=True):
    store.set_watched([episode], on)
    assert _job(fake, host) == [], "a mark writes to Anki only after its Generate"
    _generate(root)
    return _job(fake, host, "generate")


@pytest.mark.parametrize("connect_on", [True, False], ids=["connect-on", "connect-off"])
def test_a_stone_parks_its_own_words_cards_and_un_marking_brings_them_back_in_list_order(lib, monkeypatch,
                                                                                         connect_on):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    _settings_file(root, **dict(ACTING, connect_enabled=connect_on))
    host, _lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        assert _in_list_order(fake, root)
        _mark_and_generate(root, store, fake, host, episode)
        assert _suspended(fake, own) == set(own)
        assert all(LATER in _tags(fake, card_id) for card_id in own), "not on your list: the later tag on"
        assert _in_list_order(fake, root), "the cards still listed keep the list's order"
        _mark_and_generate(root, store, fake, host, episode, on=False)
    assert not _suspended(fake, own), "un-marked: the cards are back, Connect on or off"
    assert not [card_id for card_id in own if LATER in _tags(fake, card_id)], "and their later tag is off"
    assert _in_list_order(fake, root), "every listed card, the returned ones included, in the list's order"


def test_undo_the_last_reorder_puts_back_every_due_suspend_and_tag_the_stone_changed(lib, monkeypatch):
    # the audit's worry (Area 2 (d)3): an earlier suspend run left only 142 of ~287 cards restorable
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    host, _lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        store.set_watched([episode])
        _job(fake, host)
        _generate(root)
        before = _state(fake)
        _job(fake, host, "generate")
        assert _suspended(fake, own) == set(own)
        restored = reposition.restore(host._settings())
    assert restored["ok"], restored["problems"]
    assert _state(fake) == before, "every card's due, suspended state and tag as before the stone's re-order"


def test_a_word_the_episode_shares_with_a_counted_file_keeps_its_card_on_the_list(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    host, _lines = _host(generate=lambda reason: None)
    path = store.item(episode)["rel_path"]
    with open(os.path.join(root, "data", "ja", path), encoding="utf-8") as f:
        text = f.read()
    with _patched(fake):
        host._job("catch-up")
        _mark_and_generate(root, store, fake, host, episode)
    shared = [word for word in _list_words(root, 40) if word in text]
    assert shared, "RP-2's episode shares listed words with other files"
    cards = _word_cards(fake, shared)
    assert cards and not _suspended(fake, cards), "a word still counted elsewhere keeps its card"
    assert not [card_id for card_id in cards if LATER in _tags(fake, card_id)]
    assert _in_list_order(fake, root)


def test_a_word_below_the_lists_cut_off_in_a_counted_file_is_never_parked_by_a_stone(lib, monkeypatch):
    # With *List first* off ("journey"), a card the library map places (a word the list cut off, Junban's "library"
    # tier) is placed with the list, never "not on your list" (`unlisted.PLACED_WITH_LIST`): a stone on another
    # episode must leave it be. (With List first on, such a card is "not on your list" before any stone.)
    from modules.junban import connect
    from app import anki_match
    from tests.test_replan_preview_watched import ParkingCollection, _episode_with_its_own_words
    from tests.test_replan_preview import ACTIONS, DECK
    from modules.junban.tests.test_reposition import _collection
    root, store = lib
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", True)
    _settings_file(root, **dict(ACTING, junban_unlisted="journey"))
    episode, own = _episode_with_its_own_words(store)
    with open(os.path.join(root, "data", "ja", store.item(episode)["rel_path"]), encoding="utf-8") as f:
        text = f.read()
    listed = set(_list_words(root))
    library = anki_match.load_library(os.path.join(root, "results", "library_frequency.json"), "ja")
    below = next(k for k in sorted(library) if len(k) > 1 and k not in listed and k not in text)
    words = list(dict.fromkeys(_list_words(root, 40) + own + [below]))
    cards, notes, _ = _collection(words, dues=list(range(3000 + len(words) - 1, 2999, -1)), deck=DECK)
    fake = ParkingCollection(cards, notes, actions=ACTIONS)
    host, _lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        assert not _suspended(fake, _word_cards(fake, [below])), "List first off: the library map places it"
        _mark_and_generate(root, store, fake, host, episode)
    assert _suspended(fake, _word_cards(fake, own)) == set(_word_cards(fake, own)), "the stone parked its own words"
    card = _word_cards(fake, [below])
    assert card and not _suspended(fake, card), f"{below}: placed by the library map, never parked"
    assert LATER not in _tags(fake, card[0])


def test_a_pinned_episode_keeps_its_cards_when_it_is_marked_watched(lib, monkeypatch):
    # W-1 scope §4: a *Study its cards first* item's cards are never "not on your list" — pin, then watch: the pin wins
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    notes = sorted({fake.cards[card_id]["note"] for card_id in own})
    with store._writing():
        store.conn.executemany("INSERT INTO anki_links (item_id, note_id, source, linked_at) VALUES (?, ?, ?, ?)",
                               [(episode, note, "anki_miner", "2026-10-23T20:00:00Z") for note in notes])
    host, _lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        store.pin([episode])
        _job(fake, host)
        _mark_and_generate(root, store, fake, host, episode)
    assert not _suspended(fake, own), "the pinned episode's cards stay"
    assert not [card_id for card_id in own if LATER in _tags(fake, card_id)]


def test_everything_watched_steps_the_cards_back_exactly_as_everything_finished_does(lib, monkeypatch):
    # An empty list (nothing counts): a stone is "done" the way Finished is, so every file watched parks the same cards
    # as every file Finished (today: all of them, tagged and suspended; asked of Sonic 2026-10-23, M-W2-1). Whatever
    # the rule becomes, the two must stay one rule.
    root, store = lib
    _episode, _own, fake = _acting(root, store, monkeypatch)
    host, _lines = _host(generate=lambda reason: None)
    everything = [i for tier in ("now", "soon", "goal") for i in store.ids(tier)]
    with _patched(fake):
        host._job("catch-up")
        store.set_watched(everything)
        assert _job(fake, host) == [], "the marks write nothing before their Generate"
        _generate(root)
        _job(fake, host, "generate")
        watched = {card_id for card_id, card in fake.cards.items() if card["queue"] == -1}
        store.set_watched(everything, False)
        _generate(root)
        _job(fake, host, "generate")
        assert not [card_id for card_id, card in fake.cards.items() if card["queue"] == -1], "un-marked: all back"
        store.finish(everything)
        assert _job(fake, host) == [], "Finished writes nothing before its Generate (W-1b: Finished is set aside too)"
        _generate(root)
        _job(fake, host, "generate")
        finished = {card_id for card_id, card in fake.cards.items() if card["queue"] == -1}
    assert watched == finished and finished, "every file watched parks what every file Finished parks"
