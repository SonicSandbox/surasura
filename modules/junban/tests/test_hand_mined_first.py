# SPDX-License-Identifier: GPL-3.0-or-later
"""Your own cards first (P1.4 row 1.4.3; HC-N54: "Just don't want it to get buried").

With the Connect preview on, a new card without Connect's tag that you mined after Connect made its first card
(Yomitan, Anki Miner's window) goes ahead of every other new card, in the order you mined it, and is never tagged,
flagged or suspended as "not on your list". The backlog you had before Connect keeps Junban's order (🧭 P1.4-1's lean).
Off, or before Connect has made a card, nothing changes.

The scene (`connect_scene`): 冒険 and 眼鏡 are Connect's; 走る you mined after 冒険; 須藤 / 散歩 / 図書館 are your
backlog from before.
"""
from modules.junban import reposition
from modules.junban.tests.connect_scene import CONNECT_TAG, scene, settings
from modules.junban.tests.test_preview_gate import SCENE
from modules.junban.tests.test_reposition import _patched


def _order(fake, **over):
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(**over))
    return [(row.word, row.tier) for row in stats["order"]], stats


def test_a_card_you_mined_after_connects_first_goes_ahead_of_every_other(tmp_path):
    order, stats = _order(scene(tmp_path))
    assert order[0] == ("走る", "yours")
    assert [word for word, _tier in order].index("冒険") > 0
    # 老婆, parked earlier and back on the list, is untagged and newer than 冒険 too: yours, after 走る (mined first).
    fake = scene(tmp_path)
    assert stats["yours"] == [fake.card_of("走る")["cardId"], fake.card_of("老婆")["cardId"]]
    assert order[1] == ("老婆", "yours")
    # Your backlog from before Connect keeps the list's order among Connect's cards: 散歩 (list #2) right behind 冒険.
    words = [word for word, _tier in order]
    assert words.index("冒険") < words.index("散歩") < words.index("図書館")


def test_your_cards_go_in_the_order_you_mined_them_whatever_the_list_says(tmp_path):
    entries = [("冒険", "冒険が始まった。", 2000, [CONNECT_TAG], 0),
               ("図書館", "図書館で本を読んだ。", 6000, [], 0),        # mined second: not on the list
               ("散歩", "毎朝<b>散歩</b>に出かける。", 3000, [], 0),   # mined third: list #2
               ("須藤", "須藤さんが来た。", 9000, [], 0)]               # mined last
    order, _stats = _order(scene(tmp_path, entries))
    assert order[:3] == [("図書館", "yours"), ("散歩", "yours"), ("須藤", "yours")]
    assert order[3][0] == "冒険"


def test_your_cards_are_never_suspended_tagged_or_flagged_as_not_on_your_list(tmp_path):
    fake = scene(tmp_path)
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    hand = fake.card_of("走る")
    assert hand["queue"] == 0 and not hand.get("flags")
    assert "Surasura::later" not in (fake.notes[hand["note"]].get("tags") or [])
    # The backlog cards not on the list still get what the window is set to do with them.
    assert fake.card_of("須藤")["queue"] == -1
    assert fake.queue_order()[0] == "走る"


def test_before_connect_has_made_a_card_nothing_is_yours(tmp_path):
    entries = [(word, sentence, freqsort, [t for t in tags if t != CONNECT_TAG], queue)
               for word, sentence, freqsort, tags, queue in SCENE]
    on, stats = _order(scene(tmp_path, entries))
    off, _ = _order(scene(tmp_path, entries), preview=False)
    assert "yours" not in {tier for _word, tier in on} and stats["yours"] == []
    assert [word for word, _ in on if word != "老婆"] == [word for word, _ in off if word != "老婆"]


def test_a_test_runs_tag_and_any_casing_are_connects_too(tmp_path):
    """Connect's own test runs tag `surasura::connect::test-<run id>`; Anki's tags ignore case."""
    entries = [("冒険", "冒険が始まった。", 2000, ["Surasura::Connect::test-20261006"], 0),
               ("眼鏡", "新しい眼鏡を買った。", 5000, ["SURASURA::CONNECT::job-2"], 0),
               ("走る", "毎朝公園まで走った。", 4000, [], 0)]
    order, _stats = _order(scene(tmp_path, entries))
    assert [(w, t) for w, t in order if t == "yours"] == [("走る", "yours")]


def test_with_the_preview_off_your_card_waits_with_the_rest_and_is_suspended_as_in_2_5(tmp_path):
    order, stats = _order(scene(tmp_path), preview=False)
    assert "yours" not in stats and order[0][0] != "走る"
    fake = scene(tmp_path)
    with _patched(fake):
        reposition.run(settings(preview=False))
    assert fake.card_of("走る")["queue"] == -1
    assert "findNotes" not in fake.action_names, "off, Junban never asks Anki for Connect's notes"


# --- P1.4-1 (Sonic, 2026-10-06): "if they tag it with 'immersion' or whatever they choose, it would skip it. And
# still the option to order ALL." ----------------------------------------------------------------------------- #
OWN = [("須藤", "須藤さんが来た。", 9000, ["Immersion::YouTube"], 0),     # your tag, mined before Connect's first
       ("散歩", "毎朝<b>散歩</b>に出かける。", 3000, [], 0),
       ("冒険", "冒険が始まった。", 2000, [CONNECT_TAG], 0),
       ("図書館", "図書館で本を読んだ。", 6000, [], 0)]                   # untagged, mined after it


def test_a_card_carrying_your_own_tag_is_yours_whenever_you_mined_it(tmp_path):
    order, stats = _order(scene(tmp_path, OWN), junban_own_tag="immersion")
    assert order[:2] == [("須藤", "yours"), ("図書館", "yours")], "in the order you mined them"
    assert order[2][0] == "冒険"


def test_your_own_tag_works_before_connect_has_made_a_card(tmp_path):
    entries = [row for row in OWN if row[0] != "冒険"]
    order, _stats = _order(scene(tmp_path, entries), junban_own_tag="immersion")
    assert [(w, t) for w, t in order if t == "yours"] == [("須藤", "yours")]


def test_a_card_with_your_own_tag_is_never_suspended(tmp_path):
    fake = scene(tmp_path, OWN)
    with _patched(fake):
        reposition.run(settings(junban_own_tag="immersion"))
    assert fake.card_of("須藤")["queue"] == 0
    assert fake.card_of("散歩")["queue"] == 0


def test_order_all_puts_your_cards_in_the_lists_order_and_still_never_suspends_them(tmp_path):
    order, stats = _order(scene(tmp_path, OWN), junban_own_tag="immersion", junban_order_all=True)
    assert "yours" not in {tier for _word, tier in order}
    assert order[0][0] == "冒険" and stats["yours"], "the list's own order; your cards still known as yours"
    fake = scene(tmp_path, OWN)
    with _patched(fake):
        reposition.run(settings(junban_own_tag="immersion", junban_order_all=True))
    assert fake.card_of("須藤")["queue"] == 0 and fake.card_of("図書館")["queue"] == 0


def test_with_the_preview_off_your_own_tag_changes_nothing(tmp_path):
    on_off, _ = _order(scene(tmp_path, OWN), preview=False, junban_own_tag="immersion")
    plain, _ = _order(scene(tmp_path, OWN), preview=False)
    assert on_off == plain
