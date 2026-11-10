# SPDX-License-Identifier: GPL-3.0-or-later
"""Laptop round 8 #50: a card Junban brings back from its parked pile loses the `::later` tag.

Sonic found a card first in his queue still carrying `Surasura::later` — a card Junban had parked (its word off his
list), back because the word is on his list again (MR-R3), unsuspended and placed with the list (here: right before
the list card whose sentence needs it, "i+1 first"). The tag said "not on your list", which was no longer true. Now
the run takes the tag off the returning cards' notes; a Restore puts it back on the ones it sets aside again, BEFORE
it suspends them (Known from Anki reads a suspension without the tag as yours: a word marked known by mistake).

What a wrong answer costs: a stale tag (the bug), a suspended card without its tag (a false "I know this"), or the
tag taken off a note whose other card is still parked. Against the fake collection (real Japanese words; never Anki).
"""
from modules.junban import auto, reposition, undo
from modules.junban.tests.connect_scene import SCENE, scene
from modules.junban.tests.connect_scene import settings as connect_settings
from modules.junban.tests.test_reposition import _patched

LATER = "Surasura::later"
ON_THE_LIST = [row for row in SCENE if row[0] in ("散歩", "冒険", "走る", "老婆")]


def _tags(fake, word):
    return [str(t).lower() for t in fake.notes[fake.card_of(word)["note"]].get("tags") or ()]


def _run(tmp_path, entries=None):
    fake = scene(tmp_path, ON_THE_LIST if entries is None else entries)
    settings = connect_settings(junban_auto_reorder=True, junban_auto_actions=True)
    with _patched(fake):
        done = auto.reorder(settings, list_current=True)
    assert done["outcome"] == "ran", done
    return fake, settings


def test_a_returning_card_comes_back_without_its_later_tag_and_restore_puts_both_back(tmp_path):
    fake, settings = _run(tmp_path)
    card = fake.card_of("老婆")
    assert card["queue"] == 0, "the setup: 老婆 is on the list again and came back"
    assert LATER.lower() not in _tags(fake, "老婆"), "back on the list: no longer 'not on your list'"
    saved = undo.load("ja")
    assert saved["later_back"] == {LATER: [card["note"]]}
    with _patched(fake):
        done = reposition.restore(settings, confirmed=True)
    assert done["ok"], done
    assert fake.card_of("老婆")["queue"] == -1, "Restore sets it aside again"
    assert LATER.lower() in _tags(fake, "老婆"), "…with its tag: parked, never 'suspended by you'"


def test_a_note_whose_other_card_stays_parked_keeps_the_tag():
    cards = [{"card_id": 1, "note": 10, "parked": True}, {"card_id": 2, "note": 10, "parked": True},
             {"card_id": 3, "note": 11, "parked": True}]
    assert reposition._later_back(cards, [1, 3], LATER) == {LATER: [11]}, "card 2 of note 10 is still parked"
    assert reposition._later_back(cards, [], LATER) == {}
    assert reposition._later_back(cards, [1], None) == {}


def test_restore_never_suspends_a_card_whose_tag_could_not_go_back(tmp_path, monkeypatch):
    fake, settings = _run(tmp_path)
    from modules.junban import ankiconnect
    monkeypatch.setattr(ankiconnect, "add_tags", lambda url, notes, tag, chunk=150: ([], [(n, "Anki refused") for n in notes]))
    with _patched(fake):
        reposition.restore(settings, confirmed=True)
    assert fake.card_of("老婆")["queue"] == 0, "left in rather than suspended without its tag"


def test_restore_puts_the_tag_back_only_on_cards_it_sets_aside(tmp_path):
    fake, settings = _run(tmp_path)
    fake.card_of("老婆")["type"] = 2                 # studied since: Restore leaves it in, and leaves its note alone
    with _patched(fake):
        reposition.restore(settings, confirmed=True)
    assert LATER.lower() not in _tags(fake, "老婆")
