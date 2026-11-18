# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-A: *New cards come from: Current's top two, side by side* — `plan(weave=)`, the pure weave (SCOPE §2; Sonic's
answers 1–5, 2026-11-15; the lead's N5: any number of groups, Today's set reuses it with its pieces).

What a wrong answer would cost a learner: the second title's cards never coming (the tester's case), one title taking
the whole day while the other has cards, the same word studied twice in a day (once per title), a card whose sentence
became i+1 after the first title's picks still waiting behind harder ones, a pin no longer first, a card you clicked off
or know already pulled forward — or, switched off, an order that is not exactly today's.

Every card here is a real Japanese word (the scene's own words and Test Resources' kind), never a dummy; no Anki.
"""
import pytest

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


def test_a_word_in_both_titles_takes_one_slot_and_its_twin_waits_after_the_turns():
    """Conditioned picks, Kyou-B's rule 1: B's own 約束 card is no pick of its own and takes no turn — B's turn still
    goes to its next best word, 冒険 — and it waits after every turn (as a sibling card waits), so the day's slots go
    to five different words; title 3's 散歩 after it, as planned."""
    cards, groups = _scene()
    cards.append(_card(7, "約束", sort=(12,)))           # the same word, mined from title B's episode
    groups[1].append(7)
    _writes, stats = P.plan(cards, RANK, weave=groups)
    assert _words(stats) == ["約束", "冒険", "友達", "図書館", "魔法", "約束", "散歩"]
    assert [row.card_id for row in stats["order"][:2]] == [2, 4]
    assert stats["order"][5].card_id == 7 and stats["order"][5].weave[0] == 1 and stats["woven"] == 6


def test_a_titles_own_second_card_of_a_word_still_follows_its_pick():
    """Rule 1 is about the other title's twin only: A's own second 約束 card (another sentence) follows A's pick at once,
    as the plan clusters a word's cards without a weave."""
    cards, groups = _scene()
    cards.append(_card(7, "約束", sort=(2,)))             # a second 約束 card, mined from title A's episode
    groups[0].append(7)
    _writes, stats = P.plan(cards, RANK, weave=groups)
    assert _words(stats)[:3] == ["約束", "約束", "冒険"]
    assert [row.card_id for row in stats["order"][:2]] == [2, 7]


# Kyou-B in both languages: real words of each (the scene's kind; tests/Test Resources' ja / zh vocabulary).
WORDS = {"ja": ["約束", "冒険", "友達", "図書館", "世界", "時間", "未来", "散歩"],
         "zh": ["约定", "冒险", "朋友", "图书馆", "电影", "老师", "音乐", "散步"]}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_word_in_both_titles_takes_one_of_the_days_slots_in_either_language(language):
    """Rule 1: w0 is in both titles — A picks it first, B's turn goes on to w1, B's own w0 waits after the turns; the
    first four slots hold four words."""
    w = WORDS[language]
    rank = {w[1]: 1, w[0]: 2, w[2]: 5, w[3]: 7, w[7]: 0}
    cards = [_card(1, w[0], sort=(1,)), _card(2, w[2], sort=(2,)),
             _card(3, w[0], sort=(10,)), _card(4, w[1], sort=(11,)), _card(5, w[3], sort=(12,)),
             _card(6, w[7], sort=(20,))]
    _writes, stats = P.plan(cards, rank, weave=[[1, 2], [3, 4, 5]])
    assert _words(stats) == [w[0], w[1], w[2], w[3], w[0], w[7]]
    assert len(set(_words(stats)[:4])) == 4
    assert [row.card_id for row in stats["order"]][4] == 3


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_both_titles_list_words_come_before_either_titles_cards_off_the_list(language):
    """Rule 2: A has one list word (w0) and two cards off the list (i+1); B has two list words and one card with more
    unknowns. A's off-list cards wait while B still has a list word (without the rule A's 世界 / 电影 took A's second
    turn ahead of B's 図書館 / 图书馆). Kyou-D (choice 2): the off-list cards are never woven — once the list words are
    taken, the rest is Junban's planned order, never A and B in turns."""
    w = WORDS[language]
    rank = {w[0]: 2, w[1]: 1, w[3]: 7}
    cards = [_card(1, w[0], sort=(1,)), _card(2, w[4], tier="i+1", sort=(1, 100)),
             _card(3, w[6], tier="i+1", sort=(1, 300)),
             _card(4, w[1], sort=(10,)), _card(5, w[3], sort=(11,)), _card(6, w[5], tier="multi", sort=(1, 200))]
    plain = _words(P.plan([dict(c) for c in cards], rank)[1])
    _writes, stats = P.plan(cards, rank, weave=[[1, 2, 3], [4, 5, 6]])
    assert _words(stats)[:3] == [w[0], w[1], w[3]] and stats["woven"] == 3
    assert _words(stats)[3:] == [x for x in plain if x not in (w[0], w[1], w[3])]


def test_a_card_held_for_a_word_joins_the_list_turns_once_the_other_title_picks_that_word():
    """Rule 2 with "i+1 first": B's 老婆 (list #4) waits for 約束 in its sentence, so it is off the list until A picks
    約束 — then it is a list word again and takes B's turn (by its list place, ahead of B's 図書館 #8); A's card off the
    list still waits for B's 図書館."""
    cards = [_card(1, "約束", sort=(1,)), _card(2, "世界", tier="i+1", sort=(1, 100)),
             _card(3, "老婆", tier="multi", sort=(1, 7000), held=True, waits=(("約束",), 3)),
             _card(4, "図書館", sort=(10,))]
    _writes, stats = P.plan(cards, RANK, weave=[[1, 2], [3, 4]])
    assert _words(stats) == ["約束", "老婆", "図書館", "世界"]


def test_a_sentence_off_the_list_is_never_woven_even_once_its_other_word_is_picked():
    """Kyou-D (choice 2; before: Kyou-A's conditioning made B's 宇宙 i+1 once A picked 約束, and wove it ahead of B's
    老婆): B's two cards are off the list, so B takes no turn — after A's 約束 both keep Junban's planned order, with or
    without the sentence's `needs`."""
    cards = [_card(1, "約束", sort=(1,)),
             _card(2, "老婆", tier="multi", sort=(1, 7000), needs=("時計",)),
             _card(3, "宇宙", tier="multi", sort=(1, 8000), needs=("約束",))]
    rank = {"約束": 2}
    _writes, stats = P.plan([dict(c) for c in cards], rank, weave=[[1], [2, 3]])
    assert _words(stats) == ["約束", "老婆", "宇宙"] and stats["woven"] == 1
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
    beside the pin's word). Kyou-D (choice 2): B's 世界 and 時間 are off the list, so they are never woven — they keep
    Junban's planned order (before: 世界, i+1 from the start, went ahead of 時間)."""
    cards = [_card(1, "図書館", sort=(0,)), _card(2, "約束", sort=(1,)), _card(3, "図書館", sort=(10,)),
             _card(4, "時間", tier="multi", sort=(1, 7000), needs=("時計",)),
             _card(5, "世界", tier="multi", sort=(1, 8000), needs=("図書館",))]
    _writes, stats = P.plan(cards, RANK, pins=[[1]], weave=[[2], [3, 4, 5]])
    assert [row.card_id for row in stats["order"]] == [1, 3, 2, 4, 5]


# --- Kyou-B: a tester on 3.0.12 — a book of many parts (most *Target met*) and a two-video channel on top --------- #
def _his(language):
    """The book (its parts mostly *Target met*: two still-new cards left), the channel's two videos (four cards), a
    show behind them (four cards); every card a list word, real words of each language."""
    w = WORDS[language] + (["学校", "先生", "電車", "天気"] if language == "ja" else ["学校", "先生", "电车", "天气"])
    rank = {word: n for n, word in enumerate(w)}
    cards = [_card(n + 1, w[n], sort=(n,)) for n in range(len(w))]
    return cards, rank, [[1, 2], [3, 4, 5, 6], [7, 8, 9, 10]]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_two_titles_keep_taking_turns_when_one_runs_out_the_next_steps_in(language):
    """Side by side's width (2): book, channel, book, channel — the book is out of new cards, so the show steps into
    its place, never the channel alone; the show waits until then. A day of 10 is never one title's."""
    cards, rank, groups = _his(language)
    _writes, stats = P.plan(cards, rank, weave=groups, width=2)
    assert [row.weave[0] for row in stats["order"][:10]] == [0, 1, 0, 1, 1, 2, 1, 2, 2, 2]
    day = [row.weave[0] for row in stats["order"][:10]]
    assert max(day.count(g) for g in (0, 1, 2)) <= 5
    assert all(row.weave[5] == 2 for row in stats["order"][:10])


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_title_with_no_card_left_takes_no_place_at_all(language):
    """Every part of the book *Target met* (no card in scope): the channel and the show take turns from the first."""
    cards, rank, groups = _his(language)
    cards = [c for c in cards if c["card_id"] not in (1, 2)]
    _writes, stats = P.plan(cards, rank, weave=[[1, 2]] + groups[1:], width=2)
    assert [row.weave[0] for row in stats["order"][:8]] == [1, 2, 1, 2, 1, 2, 1, 2]


def test_a_click_in_the_preview_keeps_the_runs_width():
    """I5 with the width: `replan` takes it back from the rows, so a click weaves two at a time as the run does."""
    cards, rank, groups = _his("ja")
    _writes, stats = P.plan([dict(c) for c in cards], rank, weave=groups, width=2)
    for off in ([3], [1, 2], [7]):
        clicked = P.replan(stats["order"], exclude=off)
        run = P.plan([dict(c) for c in cards], rank, exclude=off, weave=groups, width=2)
        assert [(r.card_id, r.position) for r in clicked[1]["order"]] == [(r.card_id, r.position) for r in run[1]["order"]]


def test_without_a_width_every_group_takes_turns_at_once_as_before():
    """Today's set's N groups (the lead's N5): no width, all three in turns."""
    cards, rank, groups = _his("ja")
    _writes, stats = P.plan(cards, rank, weave=groups)
    assert [row.weave[0] for row in stats["order"][:6]] == [0, 1, 2, 0, 1, 2]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_title_whose_new_cards_are_pinned_or_yours_counts_them_for_the_store(language):
    """Kyou-C (train 40's intent keeper, note 1): the count the store's side by side follows (`side_picks`) holds a
    title's pinned and *yours* new cards beside its picks — the book's two cards both pinned (they go ahead of every
    turn) count 2, so the store never sets aside the title the learner pinned first; the channel's own card (*yours*)
    counts with its three picks. A card clicked off, taken out or known still counts for none."""
    cards, rank, groups = _his(language)
    cards[2]["tier"] = "yours"                            # the channel's first card: one you mined yourself
    cards[8]["tier"] = "known"                            # the show's third: known already
    _writes, stats = P.plan(cards, rank, pins=[[1, 2]], exclude=[7], out=[8], weave=groups, width=2)
    assert stats["side_picks"] == [2, 4, 1]
    assert [row.word for row in stats["order"][:2]] == [cards[0]["word"], cards[1]["word"]], "the pins stay first"
    _writes, plain = P.plan([dict(c) for c in cards], rank, weave=groups, width=2)
    assert plain["side_picks"] == [2, 4, 3], "nothing pinned, clicked off or out: every new card counts"


# --- Kyou-D: a turn only with a list word (Sonic, choice 2, 2026-11-16; TheForge kyou-d/EDGES.md E17–E24) ------------ #
# Side by side weaves only list words: a title takes its turn only when its next card is a list word; its cards off the
# list are never woven — they keep their place in Junban's planned order, ranked with every other new card. The count
# the store's pair rule follows (`side_picks`) is each title's list words still new.

def _keepers_scene(language):
    """Title A: list w0, two off the list (i+1); title B: list w1, one off the list (multi); a 6+ Months title's w7 —
    the list's best word, met last (file 40)."""
    w = WORDS[language]
    rank = {w[0]: 2, w[1]: 1, w[3]: 7, w[7]: 0}
    cards = [_card(1, w[0], sort=(1,)), _card(2, w[4], tier="i+1", sort=(1, 100)),
             _card(3, w[6], tier="i+1", sort=(1, 300)), _card(4, w[1], sort=(10,)),
             _card(5, w[5], tier="multi", sort=(1, 200)), _card(6, w[7], sort=(40,))]
    return w, rank, cards, [[1, 2, 3], [4, 5]]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_off_list_cards_of_current_never_go_ahead_of_a_list_word_from_six_months(language):
    """E17, the keeper's case: before, A's and B's off-list cards were woven in turns ahead of everything outside
    Current, the 6+ Months title's w7 (the best word on the list) after them all. Now the two list words take their
    turns, and the rest is Junban's planned order exactly: w7 first, then the off-list cards by their own rank."""
    w, rank, cards, groups = _keepers_scene(language)
    plain = _words(P.plan([dict(c) for c in cards], rank)[1])
    _writes, stats = P.plan([dict(c) for c in cards], rank, weave=groups, width=2)
    assert _words(stats)[:2] == [w[0], w[1]] and stats["woven"] == 2
    assert _words(stats)[2:] == [x for x in plain if x not in (w[0], w[1])]
    assert _words(stats)[2] == w[7]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_title_with_only_off_list_cards_takes_no_turn(language):
    """E18: B holds only cards off the list — it takes no turn, A's list words go alone, B's cards keep their planned
    places; the count says B has no list word left (the store's pair rule then steps it aside: E22)."""
    w = WORDS[language]
    rank = {w[0]: 2, w[2]: 5}
    cards = [_card(1, w[0], sort=(1,)), _card(2, w[2], sort=(2,)),
             _card(3, w[4], tier="i+1", sort=(1, 100)), _card(4, w[5], tier="multi", sort=(1, 200))]
    plain = _words(P.plan([dict(c) for c in cards], rank)[1])
    _writes, stats = P.plan([dict(c) for c in cards], rank, weave=[[1, 2], [3, 4]], width=2)
    assert _words(stats) == [w[0], w[2]] + [x for x in plain if x not in (w[0], w[2])]
    assert stats["side_picks"] == [2, 0]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_two_titles_with_no_list_word_weave_nothing_and_the_order_is_junbans(language):
    """E19: neither title has a list word — nothing is woven, and the order is the plan without a weave, row for row."""
    w = WORDS[language]
    cards = [_card(1, w[4], tier="i+1", sort=(1, 100)), _card(2, w[5], tier="multi", sort=(1, 200)),
             _card(3, w[6], tier="i+1", sort=(1, 300)), _card(4, w[7], sort=(40,))]
    rank = {w[7]: 0}
    plain = P.plan([dict(c) for c in cards], rank)
    writes, stats = P.plan([dict(c) for c in cards], rank, weave=[[1, 2], [3]], width=2)
    assert _words(stats) == _words(plain[1]) and writes == plain[0]
    assert stats["woven"] == 0 and stats["side_picks"] == [0, 0]


def test_a_held_card_whose_word_never_comes_is_not_woven():
    """E20: B's 老婆 is a list card held by *i+1 first* for 時計, which no title picks: it is never a list word here, so
    it takes no turn and keeps its planned place (before: woven in B's turn after the list rounds). It still counts as
    a list word still new for B."""
    cards = [_card(1, "約束", sort=(1,)), _card(2, "図書館", sort=(10,)),
             _card(3, "老婆", tier="multi", sort=(1, 7000), held=True, waits=(("時計",), 3))]
    plain = _words(P.plan([dict(c) for c in cards], RANK)[1])
    _writes, stats = P.plan([dict(c) for c in cards], RANK, weave=[[1], [2, 3]], width=2)
    assert _words(stats)[:2] == ["約束", "図書館"] and stats["woven"] == 2
    assert _words(stats)[2:] == [x for x in plain if x not in ("約束", "図書館")]
    assert stats["side_picks"] == [1, 2]


# --- Kyou-D: a stable phase (Sonic's ruling 3, 2026-11-17; the lead's call: anchor on Anki's first woven card) ------ #
# Every plan used to start the turns with the first title: once the learner studied an odd number of woven cards, the
# next re-plan swapped every pair still to come (A B A B → B A B A, rewritten). The turns now start with the title that
# owns the woven card Anki holds first, so a re-plan after any number of studied cards writes the same turns.

def _phase_scene(language):
    """A: w0..w3 (files 1–4), B: w4..w7 (files 10–13), every one a list word, ranked by its row."""
    w = WORDS[language]
    rank = {word: n for n, word in enumerate(w)}
    cards = [_card(n + 1, word, sort=(n + 1 if n < 4 else n + 6,)) for n, word in enumerate(w)]
    return cards, rank, [[1, 2, 3, 4], [5, 6, 7, 8]]


def _studied(stats, cards, n):
    """The cards still new once the first `n` of the planned order are studied, each at the place the plan gave it."""
    gone = {row.card_id for row in stats["order"][:n]}
    place = {row.card_id: row.position for row in stats["order"]}
    return [dict(c, due=place[c["card_id"]]) for c in cards if c["card_id"] not in gone]


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("studied", [1, 3])
def test_a_re_plan_after_an_odd_number_of_studied_cards_swaps_no_pair(language, studied):
    """The tester's 173 of 177 moves: A's first card studied, the re-plan starts with B (whose card Anki holds first)
    and the turns still to come stay as they were — no card rewritten; the same after three."""
    cards, rank, groups = _phase_scene(language)
    _writes, first = P.plan([dict(c) for c in cards], rank, weave=groups, width=2)
    assert [row.weave[0] for row in first["order"]] == [0, 1, 0, 1, 0, 1, 0, 1]
    left = _studied(first, cards, studied)
    writes, again = P.plan(left, rank, weave=groups, width=2)
    assert _words(again) == _words(first)[studied:]
    assert writes == [], "the turns kept their places: nothing to write"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_first_weave_starts_with_the_title_whose_card_anki_holds_first(language):
    """Before any weave, Anki's order is the journey's: A's words first, so A leads as before. When B's card is first
    in Anki (B was woven first last time), B leads; the turns still alternate one by one."""
    cards, rank, groups = _phase_scene(language)
    _writes, plain = P.plan([dict(c) for c in cards], rank, weave=groups, width=2)
    assert plain["order"][0].weave[0] == 0
    ahead = [dict(c, due=50) if c["card_id"] == 5 else dict(c) for c in cards]
    _writes, stats = P.plan(ahead, rank, weave=groups, width=2)
    assert [row.weave[0] for row in stats["order"]] == [1, 0, 1, 0, 1, 0, 1, 0]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_title_below_the_takers_never_leads_though_anki_holds_its_card_first(language):
    """Three titles, two at a time: C's card first in Anki does not pull C ahead of A and B — the anchor leads only
    while it is one of the round's takers; once A and B run out, C goes on."""
    w = WORDS[language]
    rank = {word: n for n, word in enumerate(w)}
    cards = [_card(1, w[0], sort=(1,)), _card(2, w[1], sort=(2,)), _card(3, w[2], sort=(10,)),
             _card(4, w[3], sort=(11,)), _card(5, w[4], sort=(20,), due=10)]
    _writes, stats = P.plan(cards, rank, weave=[[1, 2], [3, 4], [5]], width=2)
    assert [row.weave[0] for row in stats["order"]] == [0, 1, 0, 1, 2]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_without_a_width_the_rounds_turn_from_the_anchor(language):
    """Every group at once (no width): B's card first in Anki → each round B, C, A (a turn of the same cycle), never
    B, A, C."""
    w = WORDS[language]
    rank = {word: n for n, word in enumerate(w)}
    cards = [_card(1, w[0], sort=(1,)), _card(2, w[1], sort=(2,)), _card(3, w[2], sort=(10,), due=10),
             _card(4, w[3], sort=(11,)), _card(5, w[4], sort=(20,)), _card(6, w[5], sort=(21,))]
    _writes, stats = P.plan(cards, rank, weave=[[1, 2], [3, 4], [5, 6]])
    assert [row.weave[0] for row in stats["order"]] == [1, 2, 0, 1, 2, 0]
