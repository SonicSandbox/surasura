# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-A: *New cards come from: Current's top two, side by side* — `plan(weave=)`, the pure weave (SCOPE §2; Sonic's
answers 1–5, 2026-11-15; the lead's N5: any number of groups, Today's set reuses it with its pieces).

What a wrong answer would cost a learner: the second title's cards never coming (the tester's case), one title taking
the whole day while the other has cards, the same word studied twice in a day (once per title), a card whose sentence
became i+1 after the first title's picks still waiting behind harder ones, a pin no longer first, a card you clicked off
or know already pulled forward — or, switched off, an order that is not exactly today's.

Every card here is a real Japanese word (the scene's own words and Test Resources' kind), never a dummy; no Anki.
"""
from modules.junban import plan as P

# (card_id, word, tier, rank, sort) — the journey's sort is the file it is first met in (content order), so the planned
# order without a weave is title A's cards (files 1–3), then title B's (files 10–11), then title 3's (file 20).
RANK = {"散歩": 0, "冒険": 1, "約束": 2, "友達": 5, "図書館": 7, "魔法": 9, "眼鏡": 4, "老婆": 3, "宇宙": 8}


def _card(card_id, word, tier="list", sort=None, due=None, **extra):
    card = {"card_id": card_id, "due": due if due is not None else 100 + card_id, "type": 0, "queue": 0,
            "word": word, "deck": "日本語", "note": 5000 + card_id, "tier": tier}
    if tier == "list":
        card["sort"] = sort if sort is not None else (0,)
    elif sort is not None:
        card["sort"] = sort
    card.update(extra)
    return card


def _scene():
    """Title A: 魔法 (file 1), 約束 (file 2), 友達 (file 3). Title B: 冒険 (file 10), 図書館 (file 11). Title 3: 散歩
    (file 20) — the list's single best word, met last."""
    cards = [_card(1, "魔法", sort=(1,)), _card(2, "約束", sort=(2,)), _card(3, "友達", sort=(3,)),
             _card(4, "冒険", sort=(10,)), _card(5, "図書館", sort=(11,)), _card(6, "散歩", sort=(20,))]
    return cards, [[1, 2, 3], [4, 5]]


def _words(stats):
    return [row.word for row in stats["order"]]


def test_without_a_weave_the_order_is_todays_row_for_row():
    """Off (None, or no group): the very writes and rows of a plan that never heard of a weave — every Placement's
    `weave` None."""
    cards, _groups = _scene()
    plain = P.plan([dict(c) for c in cards], RANK)
    for weave in (None, [], [[], []]):
        got = P.plan([dict(c) for c in cards], RANK, weave=weave)
        assert got == plain
        assert "woven" not in got[1]
    assert all(row.weave is None for row in plain[1]["order"])
    assert _words(plain[1]) == ["魔法", "約束", "友達", "冒険", "図書館", "散歩"]


def test_two_titles_take_turns_their_most_useful_word_first_and_the_one_left_goes_on():
    """Equal split (answer 2) and impact = the word's place on the whole list (answer 3): A's 約束 (#3) before its 魔法
    (#10), turn and turn about with B; B runs out after two, A takes the rest; title 3's 散歩 — the best word of all —
    after the weave, as planned."""
    cards, groups = _scene()
    writes, stats = P.plan(cards, RANK, weave=groups)
    assert _words(stats) == ["約束", "冒険", "友達", "図書館", "魔法", "散歩"]
    assert stats["woven"] == 5
    assert [row.weave[0] for row in stats["order"][:5]] == [0, 1, 0, 1, 0]
    assert stats["order"][5].weave is None
    # the block keeps its span (positions from min(due)), and only cards that moved are written
    assert [row.position for row in stats["order"]] == list(range(101, 107))
    assert {card_id for card_id, _due in writes} == {row.card_id for row in stats["order"] if row.changed}


def test_ten_a_day_is_five_from_each_while_both_have_cards():
    """Anki shows N a day from the front: with 12 cards in each title, the first 10 hold 5 of each."""
    cards = [_card(i, w, sort=(i,)) for i, w in enumerate(
        ["魔法", "約束", "友達", "冒険", "図書館", "散歩", "眼鏡", "老婆", "宇宙", "時間", "世界", "未来"], start=1)]
    cards += [_card(20 + i, w, sort=(20 + i,)) for i, w in enumerate(
        ["学校", "先生", "電車", "天気", "季節", "記憶", "約定", "仲間", "勇気", "希望", "運命", "奇跡"], start=1)]
    rank = {c["word"]: n for n, c in enumerate(sorted(cards, key=lambda c: c["card_id"]))}
    _writes, stats = P.plan(cards, rank, weave=[[c["card_id"] for c in cards[:12]], [c["card_id"] for c in cards[12:]]])
    first_ten = [row.weave[0] for row in stats["order"][:10]]
    assert first_ten.count(0) == first_ten.count(1) == 5


def test_any_number_of_groups_take_turns_one_each():
    """The lead's N5: three groups (Today's set's pieces) — one each in turn, the shortest dropping out."""
    cards, _groups = _scene()
    _writes, stats = P.plan(cards, RANK, weave=[[1, 2, 3], [4], [5, 6]])
    assert [row.weave[0] for row in stats["order"]] == [0, 1, 2, 0, 2, 0]
    assert _words(stats) == ["約束", "冒険", "散歩", "友達", "図書館", "魔法"]


def test_an_empty_group_weaves_nothing_for_it_and_the_other_goes_alone():
    cards, _groups = _scene()
    _writes, stats = P.plan(cards, RANK, weave=[[1, 2, 3], []])
    assert _words(stats) == ["約束", "友達", "魔法", "冒険", "図書館", "散歩"]


def test_a_card_both_titles_claim_goes_with_the_first():
    cards, _groups = _scene()
    _writes, stats = P.plan(cards, RANK, weave=[[1, 2, 3, 5], [4, 5]])
    by = {row.word: row.weave for row in stats["order"]}
    assert by["図書館"][0] == 0


def test_a_word_in_both_titles_is_picked_once_and_its_twin_takes_no_turn():
    """Conditioned picks (Sonic's question): B's own 約束 card is no pick of its own — it follows A's 約束 at once and B's
    turn still goes to its next best word, 冒険; the day never spends two of B's slots on a word A already gave."""
    cards, groups = _scene()
    cards.append(_card(7, "約束", sort=(12,)))           # the same word, mined from title B's episode
    groups[1].append(7)
    _writes, stats = P.plan(cards, RANK, weave=groups)
    assert _words(stats)[:4] == ["約束", "約束", "冒険", "友達"]
    assert [row.card_id for row in stats["order"][:2]] == [2, 7]


def test_a_sentence_that_waits_only_for_a_word_already_picked_is_i_plus_1_from_there():
    """B's 宇宙 card (more unknowns: its sentence needs 約束) is planned behind B's 老婆 card (more unknowns, needs 時計).
    Once A has picked 約束, 宇宙's sentence is i+1 and goes first for B. Without the conditioning (no `needs`), B's first
    pick stays 老婆."""
    cards = [_card(1, "約束", sort=(1,)),
             _card(2, "老婆", tier="multi", sort=(1, 7000), needs=("時計",)),
             _card(3, "宇宙", tier="multi", sort=(1, 8000), needs=("約束",))]
    rank = {"約束": 2}
    _writes, stats = P.plan([dict(c) for c in cards], rank, weave=[[1], [2, 3]])
    assert _words(stats) == ["約束", "宇宙", "老婆"]
    plain = [{k: v for k, v in c.items() if k != "needs"} for c in cards]
    _writes, stats = P.plan(plain, rank, weave=[[1], [2, 3]])
    assert _words(stats) == ["約束", "老婆", "宇宙"]


def test_a_list_card_held_for_a_word_takes_its_list_place_once_that_word_is_picked():
    """"i+1 first" held B's 老婆 (list #4) for 約束 in its sentence; A picks 約束 first, so B's next pick is 老婆 by its
    list place, ahead of B's 図書館 (#8)."""
    cards = [_card(1, "約束", sort=(1,)), _card(2, "図書館", sort=(10,)),
             _card(3, "老婆", tier="multi", sort=(1, 7000), held=True, waits=(("約束",), 3))]
    _writes, stats = P.plan(cards, RANK, weave=[[1], [2, 3]])
    assert _words(stats) == ["約束", "老婆", "図書館"]


def test_pins_and_your_own_cards_stay_ahead_and_a_pinned_card_is_not_woven_again():
    cards, groups = _scene()
    cards.append(_card(8, "眼鏡", tier="yours", sort=(8,)))
    _writes, stats = P.plan(cards, RANK, pins=[[5]], weave=groups)
    assert _words(stats)[:2] == ["図書館", "眼鏡"]
    assert stats["order"][0].pinned == 0 and stats["order"][0].weave[0] == 1     # a member, lifted by its pin
    assert _words(stats)[2:] == ["約束", "冒険", "友達", "魔法", "散歩"]


def test_a_clicked_off_card_a_known_one_and_a_review_card_are_never_woven():
    cards, groups = _scene()
    cards.append(_card(9, "老婆", tier="known", sort=()))
    cards.append(dict(_card(10, "宇宙", sort=(2,)), type=2, queue=2, due=40))     # a review card: never touched
    groups[0] += [9, 10]
    _writes, stats = P.plan(cards, RANK, exclude=[2], weave=groups)
    words = _words(stats)
    assert words[:4] == ["友達", "冒険", "魔法", "図書館"]
    assert words.index("散歩") < words.index("老婆") < words.index("約束"), "known last; the clicked-off card at the back"
    assert 10 not in {row.card_id for row in stats["order"]}


def test_a_second_run_writes_nothing():
    cards, groups = _scene()
    writes, _stats = P.plan([dict(c) for c in cards], RANK, weave=groups)
    due = dict(writes)
    again = [dict(c, due=due.get(c["card_id"], c["due"])) for c in cards]
    writes, stats = P.plan(again, RANK, weave=groups)
    assert writes == [] and stats["to_write"] == 0


def test_a_click_in_the_preview_weaves_as_the_run_will():
    """I5: `replan` (a click) takes the groups, the words and the needs back from the rows and gives the plan the run
    makes with that card clicked off."""
    cards = [_card(1, "約束", sort=(1,)), _card(2, "友達", sort=(3,)), _card(4, "冒険", sort=(10,)),
             _card(5, "老婆", tier="multi", sort=(1, 7000), needs=("時計",)),
             _card(6, "宇宙", tier="multi", sort=(1, 8000), needs=("約束",)), _card(7, "散歩", sort=(20,))]
    weave = [[1, 2], [4, 5, 6]]
    _writes, stats = P.plan([dict(c) for c in cards], RANK, weave=weave)
    for off in ([4], [1], [6]):
        clicked = P.replan(stats["order"], exclude=off)
        run = P.plan([dict(c) for c in cards], RANK, exclude=off, weave=weave)
        assert [(r.card_id, r.position) for r in clicked[1]["order"]] == [(r.card_id, r.position) for r in run[1]["order"]]


def test_a_pinned_cards_word_counts_as_picked_for_the_weave():
    """KA-9: B's own 図書館 card shares its word with the pinned 図書館 — no pick of its own (it goes ahead of the turns,
    beside the pin's word); B's 世界 (off the list), whose sentence needs only 図書館, is i+1 from the start and goes
    ahead of B's 時間, planned before it."""
    cards = [_card(1, "図書館", sort=(0,)), _card(2, "約束", sort=(1,)), _card(3, "図書館", sort=(10,)),
             _card(4, "時間", tier="multi", sort=(1, 7000), needs=("時計",)),
             _card(5, "世界", tier="multi", sort=(1, 8000), needs=("図書館",))]
    _writes, stats = P.plan(cards, RANK, pins=[[1]], weave=[[2], [3, 4, 5]])
    assert [row.card_id for row in stats["order"]] == [1, 3, 2, 5, 4]
