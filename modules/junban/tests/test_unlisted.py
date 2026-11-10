# SPDX-License-Identifier: GPL-3.0-or-later
"""The cards NOT on the list (Junban_Backlog_Spec §13) — the planner alone, no Anki in the room.

The user's answers (2026-09-23): any combination of Tag / Flag purple / Suspend; nothing ticked is
"No action", the default; no delete. What these tests hold still is WHICH cards are acted on — a
listed word suspended by mistake leaves the user's queue, and nothing in Anki would say so — and that
Junban only ever records what it can take back without touching anything of the user's.

Rows are the planner's own `Placement`s over real Japanese words, as `reposition` hands them over.
"""
from modules.junban import unlisted
from modules.junban.plan import Placement

# The list's every key, as `build_index` files them — the kana fold included (するり for スルリ).
MARKS = {"冒険": frozenset(), "散歩": frozenset(), "老婆": frozenset(), "するり": frozenset()}
ALL = {"tag": True, "flag": True, "suspend": True}


def _row(card_id, word, tier, note=None):
    return Placement(position=2800 + card_id % 1000, card_id=card_id, due=2800, word=word, rank=None,
                     deck="TheBank", changed=False,
                     note_id=note if note is not None else card_id + 1000, tier=tier, sort=(), why="")


def _plan(rows, opts=ALL, flags=None, notes=None, exclude=(), taken_off=()):
    return unlisted.plan(rows, MARKS, "ja", flags or {}, notes or {}, opts, parent="Surasura",
                         exclude=exclude, taken_off=taken_off)


def test_no_action_is_the_default_and_plans_nothing():
    """The user's default: nothing ticked means nothing planned, and garbled values are not a yes."""
    assert unlisted.options({}) == {"tag": False, "flag": False, "suspend": False}
    assert unlisted.options({"junban_later_tag": "yes", "junban_later_suspend": 1}) == \
        {"tag": False, "flag": False, "suspend": False}
    assert _plan([_row(1, "須藤", "rest")], opts=unlisted.options({})) == {}


def test_only_cards_placed_behind_the_list_and_on_it_in_no_form_are_acted_on():
    """The list's words, the phrases held to its bar and journey-placed library words are placed WITH
    the list; the rest — by sentence, known, or unplaced — are not. スルリ is on the list as するり
    (the kana fold), so it is left alone even with no tier: a marker filter leaves listed words
    unplaced, and they must never be suspended as if they were unlisted."""
    rows = [_row(1, "冒険", "list"), _row(2, "恩を売る", "phrase"), _row(3, "引きずる", "library"),
            _row(4, "須藤", "i+1"), _row(5, "図書館", "multi"), _row(6, "味噌汁", "rest"),
            _row(7, "終わり", "known"), _row(8, "眼鏡", None), _row(9, "スルリ", None)]

    later = _plan(rows)

    assert later["cards"] == [4, 5, 6, 7, 8]
    assert later["suspend"] == [4, 5, 6, 7, 8]
    assert later["counts"]["cards"] == 5


def test_a_word_taken_off_the_list_is_acted_on_and_a_card_left_alone_is_not():
    """The user (2026-09-23): a word clicked off the list is "treated as 'not-on-your-list'". Once
    re-planned it sits by its sentence (tier multi) but its word is still ON the list — so the planner
    is told, and acts on it. A card already not on the list, clicked, is left alone: never acted on.
    Two cards of one note, one left alone, still tag that note through the other."""
    rows = [_row(1, "冒険", "multi"), _row(4, "須藤", "rest", note=77), _row(5, "須藤", "rest", note=77),
            _row(6, "図書館", "rest")]

    later = _plan(rows, exclude={4, 6}, taken_off={1})

    assert later["cards"] == [1, 5]
    assert later["tag_notes"] == [77, 1001]
    assert _plan(rows)["cards"] == [4, 5, 6], "without being told, a listed word is never a target"


def test_suspend_always_tags_so_a_suspended_card_can_be_found():
    """Restore covers the last run only; the tag is how an earlier run's suspensions stay findable
    (`tag:Surasura::later is:suspended`)."""
    later = _plan([_row(4, "須藤", "rest")], opts={"tag": False, "flag": False, "suspend": True})

    assert later["tag"] == "Surasura::later" and later["tag_notes"] == [1004]


def test_a_note_already_carrying_the_tag_in_any_case_is_not_recorded():
    """So a Restore can never take away a tag the user put there themselves — Anki compares tags
    case-insensitively, and a child tag counts."""
    rows = [_row(4, "須藤", "rest"), _row(5, "図書館", "rest"), _row(6, "味噌汁", "rest")]
    notes = {1004: {"tags": ["surasura::LATER"]}, 1005: {"tags": ["Surasura::later::mine"]},
             1006: {"tags": ["Surasura"]}}

    assert _plan(rows, notes=notes)["tag_notes"] == [1006]


def test_a_users_own_flag_is_kept_and_counted_and_purple_needs_nothing():
    """Only unflagged cards are flagged. Red stays red (counted, for the preview to say); a card
    already purple needs no write, so a second run writes nothing."""
    rows = [_row(4, "須藤", "rest"), _row(5, "図書館", "rest"), _row(6, "味噌汁", "rest")]

    later = _plan(rows, flags={4: 0, 5: 1, 6: unlisted.FLAG_PURPLE})

    assert later["flags"] == {4: 0}
    assert later["counts"]["flag_kept"] == 1


def test_the_later_tag_hangs_under_the_junban_tag_or_under_surasura():
    """Under the tag the user named; with that tag switched off, the later tag is still its own
    choice and goes under Surasura rather than loose at the root."""
    assert unlisted.later_tag("SurasuraOrder") == "SurasuraOrder::later"
    assert unlisted.later_tag("") == "Surasura::later"


def test_suspending_asks_anki_for_its_undo_too():
    """Preflight asks AnkiConnect for `suspend` AND `unsuspend` when Suspend is ticked — the way back
    has to exist before the way there is taken — and for nothing extra otherwise."""
    assert unlisted.required_actions({"suspend": True}) == ("suspend", "unsuspend")
    assert unlisted.required_actions({"tag": True, "flag": True}) == ()
    assert not unlisted.has_work({}) and unlisted.has_work(_plan([_row(4, "須藤", "rest")]))
