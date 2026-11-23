# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-AF: a card the learner asked for from the journey goes first (journey v3 D3; ROLES.md, Junban's row).

*Add now* on the journey page asks Swap's one maker for a card from the line the learner picked (`by` "add now");
Connect makes it; Junban's order then puts it first among the new cards. What these tests hold still:

- **first, in the order asked:** an asked card goes ahead of every other new card — the pins and your own mined cards
  included — and several go in the order they were asked, whatever their tier (a card off the list, one at the back);
- **nothing else moves:** the rest keep exactly the order they had without the ask (the same stable lift as a pin's,
  one step ahead of it: no second ordering pass); no ask at all is the plan it always was, row for row;
- **no longer special once studied or deleted:** such a card isn't a new card in the deck, so the order is the one
  without it; an ask undone, a ⇄ swap's new card and Connect's ordinary cards are not *Add now* and stay where Junban
  places them;
- **the same in every run:** the 順 window's run, an automatic re-order and a click in the preview (`replan`) keep it
  first; Connect's record missing or unreadable, or Connect off, places every card as before.

Real Japanese and Chinese words (the shipped export `tests/Test Resources/ja/expected_output.csv`, the P1.4 scene's
Lapis cards); the ledger is real (Swap's own `make_card` writes the asks); Anki is the fake collection.
"""
import csv
import os

import pytest

from app.connect import swap
from app.connect.ledger import Ledger
from modules.junban import reposition, spaced
from modules.junban.plan import plan, replan
from modules.junban.tests.connect_scene import scene, settings
from modules.junban.tests.test_reposition import FakeCollection, _collection, _patched, _settings

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_RESOURCE_CSV = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")
_SHOW_WORDS = ["須藤", "引きずる", "冒険", "鳥取", "美術館", "新幹線"]     # mined by hand, not on the export's list


# --------------------------------------------------------------------------------------------------------------- #
# The planner alone
# --------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def ranked():
    with open(_RESOURCE_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        words = [(row.get("Word") or "").strip() for row in csv.DictReader(handle)]
    words = [w for w in dict.fromkeys(words) if w]
    assert not set(_SHOW_WORDS) & set(words), "the fixture's show words must stay unranked"
    return words[:12]


def _card(card_id, due, word, card_type=0, queue=0, **extra):
    return dict({"card_id": card_id, "due": due, "type": card_type, "queue": queue, "word": word, "deck": "TheBank",
                 "note": card_id + 1000}, **extra)


@pytest.fixture
def deck(ranked):
    """Twelve ranked cards (ids 1–12, due in reverse of their rank) and six off the list (21–26); one of yours (40)."""
    cards = [_card(i + 1, 3000 + (12 - i), word) for i, word in enumerate(ranked)]
    cards += [_card(21 + i, 2000 + i, word) for i, word in enumerate(_SHOW_WORDS)]
    cards.append(_card(40, 1990, "散歩", tier="yours", sort=(40,), why="yours"))
    return cards, {word: rank for rank, word in enumerate(ranked)}


def _ids(stats):
    return [row.card_id for row in stats["order"]]


def test_no_asked_card_is_the_plan_it_always_was(deck):
    """None, [] and asks for cards not in the deck all give today's writes and rows exactly, no `asked` count."""
    cards, rank_of = deck
    before = plan(cards, rank_of)
    for asked in (None, [], [999, 1000]):
        writes, stats = plan(cards, rank_of, asked=asked)
        assert writes == before[0]
        assert stats == before[1]
        assert all(row.asked is None for row in stats["order"])


def test_an_asked_card_goes_first_ahead_of_yours_and_the_pins_and_nothing_else_moves(deck):
    """新幹線 (26), off the list and so near the back, asked: first — ahead of your own 散歩 and of a pinned show — and
    every other card keeps the order it had; the block keeps its span (it starts at min(due))."""
    cards, rank_of = deck
    pins = [[23, 21]]
    _w, plain = plan(cards, rank_of, pins=pins)
    writes, stats = plan(cards, rank_of, pins=pins, asked=[26])
    assert _ids(stats)[0] == 26
    assert _ids(stats)[1:] == [i for i in _ids(plain) if i != 26]
    assert stats["order"][0].asked == 0 and stats["asked"] == 1
    assert stats["order"][0].position == plain["base"] == min(c["due"] for c in cards)
    assert [row.position for row in stats["order"]] == [row.position for row in plain["order"]]


def test_several_asked_cards_go_in_the_order_they_were_asked(deck):
    """Asked 鳥取 (24), then a list word (5), then 須藤 (21): that order, whatever their tiers or dues."""
    cards, rank_of = deck
    _w, stats = plan(cards, rank_of, asked=[24, 5, 21])
    assert _ids(stats)[:3] == [24, 5, 21]
    assert [row.asked for row in stats["order"][:3]] == [0, 1, 2]


def test_a_studied_or_deleted_asked_card_is_no_longer_special(deck):
    """Once studied (a review card) or deleted (not in the deck), the ask lifts nothing: the order is the plain one."""
    cards, rank_of = deck
    studied = [dict(c, type=2, queue=2, due=140) if c["card_id"] == 26 else c for c in cards]
    deleted = [c for c in cards if c["card_id"] != 26]
    for scope in (studied, deleted):
        assert _ids(plan(scope, rank_of, asked=[26])[1]) == _ids(plan(scope, rank_of)[1])


def test_a_click_in_the_preview_keeps_the_asked_cards_first_and_a_clicked_off_one_stays_off(deck):
    """`replan` re-plans from the rows alone: the asked cards keep their place and order; one clicked off is not lifted."""
    cards, rank_of = deck
    _w, stats = plan(cards, rank_of, asked=[24, 21])
    _w, after = replan(stats["order"], exclude={3})
    assert _ids(after)[:2] == [24, 21]
    _w, off = replan(stats["order"], exclude={24})
    assert _ids(off)[0] == 21 and next(r for r in off["order"] if r.card_id == 24).asked is None
    # the preview says why it is first, and a card no longer asked gets its own reason back
    assert stats["order"][0].why.startswith("you asked for it")
    assert not next(r for r in off["order"] if r.card_id == 24).why
    _w, back = replan(after["order"])
    assert [row.why for row in back["order"]] == [row.why for row in after["order"]], "never stacked"


def test_an_asked_card_is_never_woven_nor_taken_out(deck):
    """Side by side's weave and *Take its new cards out* pass an asked card by: it stays first."""
    cards, rank_of = deck
    _w, stats = plan(cards, rank_of, weave=[[26, 1, 2], [3, 4]], width=2, out={25, 26}, asked=[26])
    assert _ids(stats)[0] == 26
    assert stats["order"][0].weave is not None and stats["order"][0].out is None
    assert _ids(stats)[-1] == 25, "the other taken-out card still goes last"


def test_the_fast_replans_numbers_keep_the_asked_card_first(deck):
    """On the spaced ladder (the fast re-plan's preview) the asked card is still numbered first."""
    cards, rank_of = deck
    _w, stats = plan(cards, rank_of, number=spaced.Numbering(floor=None), asked=[26])
    assert _ids(stats)[0] == 26
    assert stats["order"][0].position == min(row.position for row in stats["order"])


# --------------------------------------------------------------------------------------------------------------- #
# End to end: the ledger's asks, Junban's run
# --------------------------------------------------------------------------------------------------------------- #
def _ask(word, note_id, by=swap.BY_ADD_NOW, state=swap.MADE, language="ja"):
    """An ask through Swap's one maker (as the journey's `card/make` asks), then Connect's making of it."""
    with Ledger() as ledger:
        got = swap.make_card(language, word, line_id="7:12000", by=by, ledger=ledger, wake=False,
                             state_of=lambda _w, _r: None)
        swap._set(ledger, got["id"], state=state, new_note=note_id)


def _note_of(fake, word):
    return fake.card_of(word)["note"]


def _planned(fake, **over):
    """The order a run would write (the preview's own pass, nothing written: two scenes compare cleanly)."""
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(**over))
    return [row.word for row in stats["order"]]


def test_add_now_cards_go_first_in_the_order_asked_and_the_rest_keep_their_order(tmp_path):
    """The scene's 眼鏡 (Connect's, its word off the list: at the back) and 冒険 asked from the journey, 眼鏡 first:
    after the run Anki shows 眼鏡, then 冒険, then every other card in the order Junban gives it without the asks."""
    plain = _planned(scene(tmp_path))
    fake = scene(tmp_path)
    _ask("眼鏡", _note_of(fake, "眼鏡"))
    _ask("冒険", _note_of(fake, "冒険"))
    order = _planned(fake)
    assert order[:2] == ["眼鏡", "冒険"]
    assert order[2:] == [w for w in plain if w not in ("眼鏡", "冒険")]
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    assert fake.queue_order()[:2] == ["眼鏡", "冒険"], "what Anki shows next"


def test_an_undone_ask_a_swaps_new_card_and_an_unmade_ask_are_not_first(tmp_path):
    """Only a made *Add now* counts: an ask undone, one Connect hasn't made yet and a ⇄ swap's new card (the loop's
    green flag) leave the order as it was."""
    plain = _planned(scene(tmp_path))
    fake = scene(tmp_path)
    _ask("眼鏡", _note_of(fake, "眼鏡"), state=swap.UNDONE)
    _ask("冒険", _note_of(fake, "冒険"), by=swap.BY_SWAP)
    _ask("須藤", _note_of(fake, "須藤"), state=swap.ASKED)
    assert _planned(fake) == plain


def test_an_automatic_reorder_keeps_the_asked_card_first(tmp_path):
    """The automatic re-order (the known-words sync's and the fast re-plan's host) plans the same pass."""
    fake = scene(tmp_path)
    _ask("眼鏡", _note_of(fake, "眼鏡"))
    with _patched(fake):
        report = reposition.run(settings(), refresh=False, job=spaced.Job(automatic=True))
    assert report["ok"], report["problems"]
    assert fake.queue_order()[0] == "眼鏡"


def test_connect_off_or_its_record_unreadable_places_every_card_as_before(tmp_path):
    """Connect off (2.5's run, byte for byte): the ask isn't read. A ledger that isn't a database: the run still
    succeeds, every card placed as without the ask."""
    plain_off = _planned(scene(tmp_path), preview=False)
    plain = _planned(scene(tmp_path))
    fake = scene(tmp_path)
    _ask("眼鏡", _note_of(fake, "眼鏡"))
    assert _planned(fake, preview=False) == plain_off
    assert _planned(fake)[0] == "眼鏡"

    from app.connect import ledger as ledger_mod
    for name in os.listdir(ledger_mod.folder()):
        os.remove(os.path.join(ledger_mod.folder(), name))
    with open(ledger_mod.path(), "wb") as handle:
        handle.write("台帳ではない\r\n".encode("utf-8") * 64)       # not SQLite: Connect's record can't be read
    fake = scene(tmp_path)
    assert _planned(fake) == plain
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]


def test_a_chinese_add_now_card_goes_first(tmp_path):
    """Chinese, end to end: 頭髮 (Connect's, off the list) asked from the journey goes ahead of the list's 发展 / 关系."""
    path = tmp_path / "results" / "priority_learning_list.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Word,Orth,Reading,Tier\n发展,发展,,NOW\n关系,关系,,NOW\n", encoding="utf-8-sig")
    cards, notes, _ = _collection(["發展", "學習", "頭髮", "關係"], dues=[2800, 2801, 2802, 2803])
    by_word = {note["fields"]["Expression"]["value"]: note for note in notes}
    by_word["頭髮"]["tags"] = ["Surasura::Connect::1"]
    fake = FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend"))
    _ask("頭髮", by_word["頭髮"]["noteId"], language="zh")
    _ask("學習", by_word["學習"]["noteId"], language="ja")       # another language's ask: not this deck's
    with _patched(fake):
        report = reposition.run(_settings(target_language="zh", zh_script="s", connect_enabled=True))
    assert report["ok"], report["problems"]
    new = sorted((c for c in fake.cards.values() if c["type"] == 0 and c["queue"] == 0),
                 key=lambda c: (c["due"], c["cardId"]))
    words = [fake.notes[c["note"]]["fields"]["Expression"]["value"] for c in new]
    assert words[0] == "頭髮"
    assert words.index("發展") < words.index("關係")
