# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog onboarding (Sonic 2026-10-29): *Try it on my cards*, its one-click undo, and the backlog's picture.

What a wrong answer would cost, most first:

  * **Try it is a real reorder with the one undo there is.** Its snapshot (`junban_undo.json`) is on disk before the
    first write, and *Undo the last reorder* puts exactly those cards back — after Anki was closed and opened again
    too. Never a second undo file.
  * **Try it, then a real Reorder, then Undo puts back the order from before Try it** (`undo.carry_forward_tried`):
    the Reorder's snapshot would otherwise record Try it's positions as "how your cards were".
  * **Only the next cards move**, to the front, in the plan's order — the others keep their places when there is
    room, and at most twice as many move when the deck is numbered from 1. Positions only: nothing tagged, flagged,
    suspended or filled, whatever the window's other switches say.
  * **Anki closed, an empty deck, fewer than five cards**: refused / nothing / all of them, and no snapshot when
    nothing moves (one of nothing would replace the way back from the last reorder).
  * **The picture shows only before this language's first reorder**, its numbers the preview's own.

Against the fake collection (`connect_scene`, real words on real Lapis fields) — never Anki.
"""
import os
import time

import pytest

from modules.junban import junban_view as view
from modules.junban import first_touch, plan, reposition, undo
from modules.junban.tests.connect_scene import ConnectCollection, scene, settings, without_connect
from modules.junban.tests.test_reposition import AnkiRefusal, _patched


def _settings(**over):
    """The window's settings with Connect off, and every "not on your list" action ON: Try it must still move
    positions only."""
    return settings(preview=False, **over)


class Browsing(ConnectCollection):
    """The fake collection, answering the browser's two calls as AnkiConnect does — or, `old`, as an AnkiConnect from
    before `reorderCards` / `guiSelectCard` does (it refuses the unknown argument)."""

    def __init__(self, *args, old=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.old = old
        self.browsed = []

    def _dispatch(self, action, params):
        if action == "guiBrowse":
            if self.old and "reorderCards" in params:
                return AnkiRefusal("guiBrowse() got an unexpected keyword argument 'reorderCards'")
            self.browsed.append(dict(params))
            return []
        if action == "guiSelectCard":
            if self.old:
                return AnkiRefusal("unsupported action")
            self.browsed.append({"select": params.get("card")})
            return True
        return super()._dispatch(action, params)


def _browsing(tmp_path, entries=None, old=False, **kwargs):
    """The scene (nothing of Connect's in it), as a collection that answers the browser."""
    fake = scene(tmp_path, entries=without_connect(entries), **kwargs)
    fake.__class__ = Browsing
    fake.old, fake.browsed = old, []
    return fake


def _dues(fake):
    """{card id: due} for every new, unsuspended card."""
    return {card_id: card["due"] for card_id, card in fake.cards.items() if card["type"] == 0 and card["queue"] == 0}


def _queue(fake):
    """The new, unsuspended cards' ids in the order Anki shows them."""
    return [card_id for card_id, _due in sorted(_dues(fake).items(), key=lambda pair: (pair[1], pair[0]))]


def _planned(fake, s):
    """The preview's order (the window's job), read without writing anything."""
    with _patched(fake):
        _writes, stats = reposition.dry_run(s, job=view.window_job(s))
    return [row.card_id for row in stats["order"]]


def _try(fake, s, count=None):
    with _patched(fake):
        return reposition.try_front(s, count=count, job=view.window_job(s))


# --------------------------------------------------------------------------- #
# plan.try_front: pure numbers
# --------------------------------------------------------------------------- #
def test_with_room_below_only_the_next_cards_move_and_take_the_numbers_just_under_the_rest():
    order = [(11, 2805), (12, 2801), (13, 2800), (14, 2803), (15, 2802), (16, 2804), (17, 2806)]
    writes, front = plan.try_front(order, 2)
    assert front == [11, 12]
    assert writes == [(11, 2798), (12, 2799)]           # below 2800, the lowest of the others; nothing else moves


def test_room_for_exactly_the_next_cards_is_used_and_nothing_else_moves():
    # 1 and 2 are free below the others (3, 4): the next two take them; no card is displaced.
    assert plan.try_front([(1, 300), (2, 301), (3, 3), (4, 4)], 2) == ([(1, 1), (2, 2)], [1, 2])


def test_already_first_in_order_writes_nothing():
    order = [(1, 5), (2, 9), (3, 30), (4, 20)]
    assert plan.try_front(order, 2) == ([], [1, 2])


def test_already_ahead_of_the_rest_but_out_of_order_they_swap_among_themselves_only():
    order = [(1, 9), (2, 5), (3, 30), (4, 20)]
    assert plan.try_front(order, 2) == ([(1, 5), (2, 9)], [1, 2])


def test_a_deck_numbered_from_one_hands_the_lowest_numbers_over_and_the_holders_take_the_old_places():
    # A fresh Anki Miner deck: 1, 2, 3 … and the plan's next two are at 300 and 301.
    order = [(1, 300), (2, 301), (3, 1), (4, 2), (5, 3)]
    writes, front = plan.try_front(order, 2)
    assert dict(writes) == {1: 1, 2: 2, 3: 300, 4: 301}     # at most 2 × count cards move
    final = dict(order)
    final.update(writes)
    assert sorted(final, key=final.get)[:2] == [1, 2]
    assert len(set(final.values())) == len(final)


def test_fewer_cards_than_asked_takes_them_all_in_the_plans_order():
    writes, front = plan.try_front([(7, 40), (8, 12), (9, 33)], 5)
    assert front == [7, 8, 9] and dict(writes) == {7: 12, 8: 33, 9: 40}


def test_no_cards_moves_nothing():
    assert plan.try_front([], 5) == ([], [])
    assert plan.try_front([(1, 3)], 0) == ([], [])


def test_siblings_sharing_a_number_at_the_boundary_are_refused_rather_than_left_level():
    # Card 3 shares number 1 with the one taken first: no layout puts both next cards strictly ahead.
    order = [(1, 1), (2, 50), (3, 1), (4, 2)]
    with pytest.raises(ValueError):
        plan.try_front(order, 2)


def test_a_number_below_one_is_never_written():
    # A deck holding a 0 (below Anki's own first position): swapping would write it onto the plan's first card.
    with pytest.raises(ValueError):
        plan.try_front([(1, 5), (2, 0), (3, 9)], 2)


def test_a_tie_at_the_ceiling_is_laid_just_below_it_never_at_a_million():
    # Check Database folds 1,000,000 and up: two cards sharing 999,999 go to 999,998 and 999,999.
    writes, _front = plan.try_front([(1, 999_999), (2, 999_999)], 2)
    assert dict(writes) == {1: 999_998}
    assert all(1 <= due <= 999_999 for _card, due in writes)


# --------------------------------------------------------------------------- #
# undo: the carried numbers, the picture's rule
# --------------------------------------------------------------------------- #
def test_carry_forward_tried_keeps_a_cards_number_from_before_try_only_while_it_is_where_try_put_it():
    previous = {"cards": {"1": 300, "2": 301}, "tried": {"1": 1, "2": 2}}
    pairs = [(1, 1), (2, 7), (3, 5)]                    # card 2 moved since (you, or a review): left as it is
    assert undo.carry_forward_tried(previous, pairs) == [(1, 300), (2, 7), (3, 5)]
    assert undo.carry_forward_tried({"cards": {"1": 300}}, pairs) == pairs      # an ordinary snapshot carries nothing
    assert undo.carry_forward_tried(None, pairs) == pairs


def test_has_reordered_counts_an_automatic_reorder_and_never_moves_a_file_aside():
    from app.path_utils import get_user_files_path
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    undo.save([(1, 300)], ["TheBank"], language="ja", tried=[(1, 1)])
    assert undo.has_reordered("ja") is False
    undo.save_baseline([(1, 300)], ["TheBank"], language="ja")          # the automatic re-order ran
    assert undo.has_reordered("ja") is True
    os.remove(undo.snapshot_path("ja", "baseline"))
    undo.record_ladder("ja", ["TheBank"], floor=1)                     # any spaced run (Connect's too)
    assert undo.has_reordered("ja") is True
    os.remove(os.path.join(folder, undo.LADDER_FILENAME))
    with open(undo.snapshot_path("ja"), "w", encoding="utf-8") as handle:
        handle.write("{half")                                          # another writer mid-replace
    assert undo.has_reordered("ja") is True
    assert os.path.exists(undo.snapshot_path("ja")), "a preview never moves the undo file aside"


def test_has_reordered_is_false_with_nothing_or_only_a_try_and_true_for_a_real_reorder_or_a_broken_file():
    assert undo.has_reordered("ja") is False
    undo.save([(1, 300)], ["TheBank"], language="ja", tried=[(1, 1)])
    assert undo.has_reordered("ja") is False
    undo.save([(1, 300)], ["TheBank"], language="ja")
    assert undo.has_reordered("ja") is True
    os.makedirs(os.path.dirname(undo.snapshot_path("zh")), exist_ok=True)
    with open(undo.snapshot_path("zh"), "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert undo.has_reordered("zh") is True             # a picture shown again is worse than one missed


# --------------------------------------------------------------------------- #
# reposition.try_front against the fake collection
# --------------------------------------------------------------------------- #
def test_try_moves_the_previews_next_five_cards_to_the_front_and_opens_the_browser_on_them(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings()
    planned = _planned(fake, s)
    seen = {}
    fake.on_write = lambda: seen.setdefault("at_first_write", undo.load("ja"))
    others_before = {card_id: due for card_id, due in _dues(fake).items() if card_id not in planned[:5]}

    report = _try(fake, s)

    assert report["ok"], report["problems"]
    assert report["front"] == planned[:5]
    assert _queue(fake)[:5] == planned[:5]              # the next cards you'll meet are Anki's first five
    assert {c: d for c, d in _dues(fake).items() if c not in planned[:5]} == others_before    # room: no other moved
    assert seen["at_first_write"]["complete"] is False and seen["at_first_write"]["tried"]    # I3
    saved = undo.load("ja")
    assert saved["complete"] is True
    assert set(saved["cards"]) == {str(c) for c, _d in fake.writes}
    # Positions only: none of the window's "not on your list" actions ran.
    assert not fake.tag_calls and not fake.flag_writes and not fake.suspend_calls and not fake.note_writes
    assert fake.browsed[0]["reorderCards"] == {"order": "ascending", "columnId": "cardDue"}
    assert fake.browsed[1] == {"select": planned[0]}
    assert report["browsed"] == "sorted"


def test_undo_after_try_puts_exactly_those_cards_back_even_after_anki_was_closed_and_opened(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings()
    before = _dues(fake)
    assert _try(fake, s)["ok"]
    assert _dues(fake) != before

    fake.offline = True                                 # Anki closed: Restore says so and changes nothing
    with _patched(fake):
        refused = reposition.restore(s)
    assert not refused["ok"]
    fake.offline = False                                # opened again: the snapshot is still on disk
    with _patched(fake):
        restored = reposition.restore(s)
    assert restored["ok"], restored["problems"]
    assert _dues(fake) == before


def test_try_then_a_real_reorder_then_undo_puts_back_the_order_from_before_try(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings(junban_later_tag=False, junban_later_flag=False, junban_later_suspend=False)
    before = _dues(fake)
    assert _try(fake, s)["ok"]
    with _patched(fake):
        run = reposition.run(s, job=view.window_job(s))
    assert run["ok"], run["problems"]
    saved = undo.load("ja")
    assert "tried" not in saved                         # a real reorder's snapshot: the picture's rule reads it
    assert {int(c): d for c, d in saved["cards"].items()} == before
    with _patched(fake):
        assert reposition.restore(s)["ok"]
    assert _dues(fake) == before


def test_try_then_an_automatic_reorder_then_undo_puts_back_the_order_from_before_try(tmp_path):
    # The automatic re-order keeps today's baseline instead of the window's snapshot; Undo puts back the newer one.
    from modules.junban import spaced
    fake = _browsing(tmp_path)
    s = _settings(junban_later_tag=False, junban_later_flag=False, junban_later_suspend=False)
    before = _dues(fake)
    assert _try(fake, s)["ok"]
    time.sleep(1.05)        # snapshots are stamped to the second; on a tie `undo.restorable` prefers the window's
    with _patched(fake):
        auto = reposition.run(s, job=spaced.Job(automatic=True))
    assert auto["ok"], auto["problems"]
    baseline = undo.load("ja", "baseline")
    assert {int(c): d for c, d in baseline["cards"].items()} == before
    with _patched(fake):
        assert reposition.restore(s)["ok"]
    assert _dues(fake) == before


def test_a_deck_numbered_from_one_is_tried_and_undone_exactly(tmp_path):
    fake = _browsing(tmp_path)
    for i, card_id in enumerate(sorted(fake.cards)):
        fake.cards[card_id]["due"] = i + 1              # a fresh deck: 1, 2, 3 …
    s = _settings()
    planned = _planned(fake, s)
    before = _dues(fake)
    report = _try(fake, s)
    assert report["ok"], report["problems"]
    assert _queue(fake)[:5] == planned[:5]
    with _patched(fake):
        assert reposition.restore(s)["ok"]
    assert _dues(fake) == before


def test_a_card_reviewed_on_the_phone_and_synced_in_before_the_write_is_never_given_a_new_cards_number(
        tmp_path, monkeypatch):
    # S1 syncs AnkiWeb right before the first write: a review made on the phone arrives then. That card is a review
    # card now (its due a day number): writing a position onto it would reschedule it to a garbage date (I1).
    from app import anki_sync_rule
    fake = _browsing(tmp_path)
    s = _settings()
    planned = _planned(fake, s)

    def synced(url, **kwargs):
        fake.cards[planned[0]].update(type=2, queue=2, due=21000)
        return "synced"
    monkeypatch.setattr(anki_sync_rule, "before_write", synced)
    monkeypatch.setattr(first_touch, "open_profile", lambda url: "DevTest")    # Anki names its profile: S1 runs
    report = _try(fake, s)
    assert fake.cards[planned[0]]["due"] == 21000 and planned[0] not in report["written"]
    assert report["left"] == [planned[0]] and "left where it is" in report["message"]
    assert report["written"] and set(report["written"]) <= set(planned[:5])


def test_undo_of_a_try_leaves_a_card_moved_since_where_it_is(tmp_path):
    # A Try's snapshot holds only the cards it moved: one moved since (another run, you) isn't sent back blind.
    fake = _browsing(tmp_path)
    s = _settings()
    before = _dues(fake)
    report = _try(fake, s)
    moved = report["front"][1]
    fake.cards[moved]["due"] = 999_000                  # moved since Try it put it
    with _patched(fake):
        restored = reposition.restore(s)
    assert restored["ok"] and "1 card had moved on" in restored["message"]
    assert fake.cards[moved]["due"] == 999_000
    assert {c: d for c, d in _dues(fake).items() if c != moved} == {c: d for c, d in before.items() if c != moved}


def test_try_then_an_automatic_reorder_then_a_reorder_then_undo_puts_back_the_order_before_that_reorder(tmp_path):
    # After an automatic write, today's baseline is the way back from Try: a later Reorder carries nothing.
    from modules.junban import spaced
    fake = _browsing(tmp_path)
    s = _settings(junban_later_tag=False, junban_later_flag=False, junban_later_suspend=False)
    assert _try(fake, s)["ok"]
    time.sleep(1.05)
    with _patched(fake):
        assert reposition.run(s, job=spaced.Job(automatic=True))["ok"]
    first, last = _queue(fake)[0], _queue(fake)[-1]     # you swapped two cards in Anki since
    fake.cards[first]["due"], fake.cards[last]["due"] = fake.cards[last]["due"], fake.cards[first]["due"]
    before_reorder = _dues(fake)
    assert undo.newer_baseline("ja", undo.load("ja"))
    with _patched(fake):
        reordered = reposition.run(s, job=view.window_job(s))
        assert reordered["ok"] and reordered["written"]
        assert reposition.restore(s)["ok"]
    assert _dues(fake) == before_reorder


def test_a_second_try_on_other_cards_keeps_the_first_ones_way_back(tmp_path):
    # The first Try's cards, no longer next (their words learned since: known words go last), stay where it put
    # them; the second Try moves two others — and its snapshot still holds the first one's cards.
    fake = _browsing(tmp_path)
    s = _settings()
    before = _dues(fake)
    first = _try(fake, s, count=2)["front"]
    for card_id in first:
        fake.notes[fake.cards[card_id]["note"]]["fields"]["Expression"]["value"] = "毎朝"     # a known word
    second = _try(fake, s, count=2)
    assert second["ok"] and not set(second["front"]) & set(first)
    assert not set(first) & set(second["written"])
    with _patched(fake):
        assert reposition.restore(s)["ok"]
    assert _dues(fake) == before


def test_try_ends_todays_baseline_as_a_reorder_does(tmp_path):
    from modules.junban import spaced
    fake = _browsing(tmp_path)
    s = _settings(junban_later_tag=False, junban_later_flag=False, junban_later_suspend=False)
    with _patched(fake):
        assert reposition.run(s, job=spaced.Job(automatic=True))["ok"]
    assert not undo.load("ja", "baseline").get("ended_at")
    for i, card_id in enumerate(_planned(fake, s)[:5]):
        fake.cards[card_id]["due"] = 999_990 + i         # the next cards sent to the back meanwhile: Try writes
    assert _try(fake, s)["written"]
    assert undo.load("ja", "baseline").get("ended_at")


def test_an_empty_list_moves_nothing(tmp_path):
    from modules.junban.tests.test_reposition import _LIBRARY, _results
    fake = _browsing(tmp_path)
    _results(tmp_path, progressive=[], library=_LIBRARY, floor=11)      # every file watched: the list has no row
    report = _try(fake, _settings())
    assert report["ok"] and report["message"] == reposition.EMPTY_LIST
    assert fake.writes == [] and not os.path.exists(undo.snapshot_path("ja"))


def test_two_tries_in_a_row_keep_the_first_ones_way_back(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings()
    before = _dues(fake)
    assert _try(fake, s, count=2)["ok"]
    assert _try(fake, s, count=4)["ok"]                 # moves two more; the first two stay in its snapshot
    with _patched(fake):
        assert reposition.restore(s)["ok"]
    assert _dues(fake) == before


def test_a_second_try_with_the_cards_already_first_writes_nothing_and_keeps_the_snapshot(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings()
    assert _try(fake, s)["ok"]
    saved = undo.load("ja")
    fake.writes.clear()
    again = _try(fake, s)
    assert again["ok"] and "already first" in again["message"] and fake.writes == []
    assert undo.load("ja") == saved


def test_anki_closed_refuses_try_and_saves_nothing(tmp_path):
    fake = _browsing(tmp_path, offline=True)
    report = _try(fake, _settings())
    assert not report["ok"] and report["problems"]
    assert not os.path.exists(undo.snapshot_path("ja"))
    assert fake.browsed == []


def test_an_empty_deck_moves_nothing_and_saves_nothing(tmp_path):
    fake = _browsing(tmp_path, entries=[])
    report = _try(fake, _settings())
    assert not os.path.exists(undo.snapshot_path("ja")) and fake.writes == []
    assert not report.get("front")


def test_fewer_than_five_cards_tries_them_all(tmp_path):
    from modules.junban.tests.test_preview_gate import SCENE
    fake = _browsing(tmp_path, entries=SCENE[:3])
    s = _settings()
    planned = _planned(fake, s)
    report = _try(fake, s)
    assert report["ok"] and report["front"] == planned and len(planned) == 3
    assert _queue(fake) == planned


def test_an_older_ankiconnect_gets_the_plain_search_of_the_moved_cards(tmp_path):
    fake = _browsing(tmp_path)
    fake.old = True
    report = _try(fake, _settings())
    assert report["ok"] and report["browsed"] == "plain"
    assert fake.browsed == [{"query": "cid:" + ",".join(str(c) for c in report["front"])}]


def test_an_unfinished_reorder_refuses_try_until_it_is_put_back(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings()
    undo.save(list(_dues(fake).items()), ["TheBank"], language="ja")      # a run that died before "complete"
    report = _try(fake, s)
    assert not report["ok"] and report.get("restore_first") and fake.writes == []


def test_a_card_studied_between_try_and_undo_is_left_alone_and_counted(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings()
    report = _try(fake, s)
    studied = report["front"][0]
    fake.cards[studied].update(type=2, queue=2, due=20)  # reviewed since: its due is a day number now
    with _patched(fake):
        restored = reposition.restore(s)
    assert restored["ok"] and "left alone" in restored["message"]
    assert fake.cards[studied]["due"] == 20


# --------------------------------------------------------------------------- #
# The picture's numbers and rule (junban_view)
# --------------------------------------------------------------------------- #
def _stats(fake, s):
    with _patched(fake):
        _writes, stats = reposition.dry_run(s, job=view.window_job(s))
    return dict(stats, reordered_before=False)


def test_the_picture_groups_the_previews_own_numbers_and_they_add_up(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings(junban_unlisted="journey")
    stats = _stats(fake, s)
    picture = view.backlog_picture(stats, s)
    tiers = stats["tiers"]
    assert picture.title == f"Your backlog: {stats['considered']} new cards"
    numbers = [int(line.split(" ")[0].replace(",", "")) for line in picture.lines]
    assert sum(numbers) + tiers.get("known", 0) == stats["considered"]
    assert picture.try_count == min(5, stats["considered"])
    assert picture.known == tuple(row.card_id for row in stats["order"] if row.tier == "known")


def test_the_picture_says_where_the_rarer_cards_go_by_the_users_own_setting():
    stats = {"considered": 10, "tiers": {"list": 4, "library": 2, "i+1": 1, "rest": 1, "known": 2}, "order": []}
    journey = view.backlog_picture(dict(stats, unlisted="journey"), {})
    assert any("too rare for your list: mixed in" in line for line in journey.lines)
    assert any("2 aren't in your shows: after the ones that are, by their own sentence" == line
               for line in journey.lines)
    back = view.backlog_picture(dict(stats, unlisted="back", tiers=dict(stats["tiers"], library=0)), {})
    assert any("at the back, in their order" in line for line in back.lines)
    first = view.backlog_picture(dict(stats, unlisted="list_first"), {"junban_order": "priority"})
    assert any("placed first, by leverage" in line for line in first.lines)
    assert journey.known_line.startswith("2 are words you already know")
    mine = view.backlog_picture(dict(stats, considered=12, unlisted="journey",
                                     tiers=dict(stats["tiers"], yours=2)), {})
    assert mine.lines[0] == "2 are cards you made yourself: they go first"
    assert "2 aren't in your shows: after the ones that are, by their own sentence" in mine.lines
    one = view.backlog_picture(dict(stats, considered=9, unlisted="list_first", tiers=dict(stats["tiers"], rest=0)), {})
    assert "1 isn't on your list: after it, by its own sentence" in one.lines
    assert view.backlog_picture({"considered": 0}, {}) is None


def test_cards_you_clicked_off_are_said_apart_never_as_not_on_your_list():
    stats = {"considered": 10, "deselected": 4, "taken_off": 1,
             "tiers": {"list": 3, "i+1": 1, "rest": 1, "known": 2}, "order": []}
    picture = view.backlog_picture(dict(stats, unlisted="list_first"), {})
    assert "3 are cards you clicked off: left where they are" in picture.lines
    assert "2 aren't on your list: after it, by their own sentence" in picture.lines


def test_the_picture_says_what_try_would_write_before_the_press(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings()
    picture = view.backlog_picture(_stats(fake, s), s)
    assert picture.try_moves > 0 and picture.try_line.startswith("Moves only the next 5 cards")
    for i, card_id in enumerate(sorted(fake.cards)):
        fake.cards[card_id]["due"] = i + 1              # a deck from 1: the cards at the front take the old places
    picture = view.backlog_picture(_stats(fake, s), s)
    assert picture.try_moves > 0 and " there now take" in picture.try_line
    assert _try(fake, s)["ok"]
    picture = view.backlog_picture(_stats(fake, s), s)  # a second press would do nothing: said, and Try is off
    assert picture.try_moves == 0 and picture.try_line == "Your next 5 cards are already first."


def test_the_picture_shows_only_before_the_first_reorder():
    fresh = {"reordered_before": False}
    assert view.picture_due(fresh, [], "ja")
    assert view.picture_due(fresh, "not a list", "ja")              # a hand-edited value reads as none seen
    assert not view.picture_due(fresh, ["backlog_picture:ja"], "ja")
    assert view.picture_due(fresh, ["backlog_picture:zh"], "ja")    # each language its own first
    assert not view.picture_due({"reordered_before": True}, [], "ja")
    assert not view.picture_due({}, [], "ja") and not view.picture_due(None, [], "ja")
    assert not view.picture_due({"considered": 3}, [], "ja")      # not read (an older preview): never shown


def test_preview_work_says_whether_this_language_was_reordered_before(tmp_path):
    fake = _browsing(tmp_path)
    s = _settings()
    with _patched(fake):
        stats, _checks = view.preview_work(s)
    assert stats["reordered_before"] is False
    with _patched(fake):
        reposition.run(s, job=view.window_job(s))
        stats, _checks = view.preview_work(s)
    assert stats["reordered_before"] is True


def test_show_work_opens_the_browser_on_exactly_the_known_cards_and_writes_nothing(tmp_path):
    fake = _browsing(tmp_path)
    with _patched(fake):
        how = view.show_work(_settings(), [1789712080301, 1789712080302])
    assert how == "sorted" and fake.writes == []
    assert fake.browsed == [{"query": "cid:1789712080301,1789712080302",
                             "reorderCards": {"order": "ascending", "columnId": "cardDue"}}]


def test_the_report_lines_say_where_the_browser_is(tmp_path):
    lines = view.report_lines({"ok": True, "message": "Moved your next 5 cards to the front.", "browsed": "sorted"})
    assert any("moved ones are on top" in text for text, _tone in lines)
    lines = view.report_lines({"ok": True, "message": "m", "browsed": None, "browse_problem": "Anki closed"})
    assert any("couldn't be opened (Anki closed)" in text for text, _tone in lines)
