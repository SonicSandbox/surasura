# SPDX-License-Identifier: GPL-3.0-or-later
"""Junban's side of the mining model (Kyou-MO, 3.0.18; MODEL.md § Build plan 4, ADVERSARY F4 / F16 / F21 / F24).

Junban only orders (ROLES.md). Four rules, each held still here against the fake collection — never Anki:

1. **Junban never tags, flags or suspends a card Surasura made** (any Connect card): its *set aside* applies only to
   your own cards and your older backlog. A Connect card whose word left the list goes to the back, untouched; one
   Junban parked before this rule comes back.
2. **The unlocking word first, always** (*i+1 first* is no longer a switch): a card whose other new word can't come
   first (a chain, a loop, no card yet) **keeps its place** — never sent behind the list (F16).
3. **`junban_unlisted` folded** (F24): Surasura's cards past your level follow *Cards for every new word* (on: mixed
   in where you meet them; off: at the back); your own cards not on the list keep one switch — *Leave* (after your
   list, by their own sentence; the default) · *At the back* · *Set aside* (at the back, tagged; flag / suspend as
   ticked) — `junban_off_list`, read from 3.0.17's keys while it is unset.
4. **Your own cards first** (P1.4-1): untouched — they still go ahead of Surasura's.

The scene (`connect_scene`): 冒険 and 眼鏡 are Connect's (眼鏡's word the list cut off; the library meets it in file
2); 走る you mined after 冒険; 須藤 / 散歩 / 図書館 are your backlog from before; 老婆 Junban parked.
"""
from modules.junban import auto, reposition, unlisted
from modules.junban.plan import Placement
from modules.junban.tests.connect_scene import CONNECT_TAG, scene, settings
from modules.junban.tests.test_preview_gate import SCENE
from modules.junban.tests.test_reposition import (FakeCollection, _collection, _known, _mined_sentences, _patched,
                                                  _sentence_list, _settings)

LATER = "Surasura::later"
PURPLE = unlisted.FLAG_PURPLE


def _order(fake, **over):
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(**over))
    return stats


def _row_of(stats, word):
    return next(row for row in stats["order"] if row.word == word)


# --- 1 · never a card Surasura made --------------------------------------------------------------------------- #
def test_set_aside_never_reaches_a_card_surasura_made_only_your_own(tmp_path):
    """A tester's 308 (ADVERSARY F4): with all three marks ticked, 眼鏡 — Connect's card, its word off the list — is
    neither tagged, flagged nor suspended; 須藤, a card of your own backlog off the list, still is."""
    fake = scene(tmp_path)
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    glasses = fake.card_of("眼鏡")
    assert glasses["queue"] == 0 and not glasses.get("flags")
    assert LATER not in (fake.notes[glasses["note"]].get("tags") or [])
    assert fake.card_of("須藤")["queue"] == -1, "your own older card is still set aside as you ticked"
    # ...and it goes to the back: after every card Junban places, in the order it had.
    assert fake.queue_order()[-1] == "眼鏡"


def test_a_connect_card_off_the_list_goes_to_the_back_untouched_while_yours_go_by_their_sentence(tmp_path):
    """*Leave* (the default for your own cards): 須藤 and 図書館 go after the list by their own sentence; 眼鏡, Connect's
    and off the list, goes to the back (tier `back`, behind them all) and nothing is planned for it."""
    stats = _order(scene(tmp_path), junban_off_list="leave")
    words = [row.word for row in stats["order"]]
    assert words[-1] == "眼鏡" and _row_of(stats, "眼鏡").tier == "back"
    assert _row_of(stats, "須藤").tier in ("i+1", "multi", "rest")
    assert _row_of(stats, "図書館").tier in ("i+1", "multi", "rest")
    assert stats["later"] == {}


def test_cards_for_every_new_word_on_mixes_surasuras_past_level_card_in_where_you_meet_it(tmp_path):
    """F24: with *Cards for every new word* on, 眼鏡 (file 2 in the library) is placed with the list, where the journey
    meets it — your own card 走る still goes first (rule 4), and your off-list 図書館 still after the list."""
    stats = _order(scene(tmp_path), junban_off_list="leave", connect_every_word=True)
    words = [row.word for row in stats["order"]]
    assert _row_of(stats, "眼鏡").tier == "library"
    assert words[0] == "走る" and _row_of(stats, "走る").tier == "yours"
    assert words.index("眼鏡") < words.index("図書館")
    # the old setting carries over: *Every new word* is *Cards for every new word* (Kantan-MO's reader)
    stats = _order(scene(tmp_path), junban_off_list="leave", connect_mine_words="unknown")
    assert _row_of(stats, "眼鏡").tier == "library"
    # ...and it mixes in Surasura's cards only: your own older card of a word the library meets (引きずる) still goes
    # by its sentence after the list
    stats = _order(scene(tmp_path, [("引きずる", "彼は足を引きずる。", 8000, [], 0)] + SCENE), junban_off_list="leave",
                   connect_every_word=True)
    assert _row_of(stats, "眼鏡").tier == "library" and _row_of(stats, "引きずる").tier in ("i+1", "multi", "rest")


def test_a_card_surasura_made_that_junban_parked_comes_back_untouched(tmp_path):
    """Before this rule Junban suspended Connect's cards with the rest (a tester's 308): one it parked — suspended, its
    `::later` tag on — comes back, unsuspended, its tag off, at the back, though its word is still off the list."""
    entries = [row if row[0] != "眼鏡" else ("眼鏡", row[1], row[2], [CONNECT_TAG, LATER], -1) for row in SCENE]
    fake = scene(tmp_path, entries)
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    glasses = fake.card_of("眼鏡")
    assert glasses["queue"] == 0
    assert LATER not in (fake.notes[glasses["note"]].get("tags") or [])
    assert fake.queue_order()[-1] == "眼鏡"


def test_the_marks_junban_put_on_a_card_surasura_made_come_off():
    """Kyou-PF's clean-up takes Junban's purple flag and `::later` tag off a Connect card whatever the list says now."""
    rows = [Placement(position=2800, card_id=11, due=2800, word="眼鏡", rank=None, deck="TheBank", changed=False,
                      note_id=21, tier=None, sort=None, why=""),
            Placement(position=2801, card_id=12, due=2801, word="須藤", rank=None, deck="TheBank", changed=False,
                      note_id=22, tier=None, sort=None, why="")]
    notes = {21: {"tags": [CONNECT_TAG, LATER]}, 22: {"tags": [LATER]}}
    clear = unlisted.plan_clear(rows, {"冒険": frozenset()}, "ja", {11: PURPLE, 12: PURPLE}, notes,
                                lambda card_id, carries: 0, parent="Surasura")
    assert clear["cards"] == [11] and clear["flags"] == {11: 0} and clear["tag_notes"] == [21]


def test_unlisted_plan_passes_over_surasuras_cards_in_japanese_and_chinese():
    """The pure planner: a Connect note is never a target, in either language; your own card is."""
    opts = {"tag": True, "flag": True, "suspend": True}
    for language, theirs, mine in (("ja", "眼鏡", "須藤"), ("zh", "眼镜", "邮局")):
        rows = [Placement(position=1, card_id=1, due=1, word=theirs, rank=None, deck="D", changed=False, note_id=10,
                          tier="rest", sort=(), why=""),
                Placement(position=2, card_id=2, due=2, word=mine, rank=None, deck="D", changed=False, note_id=20,
                          tier="rest", sort=(), why="")]
        later = unlisted.plan(rows, {}, language, {}, {10: {"tags": [CONNECT_TAG]}, 20: {"tags": []}}, opts,
                              parent="Surasura")
        assert later["cards"] == [2] and later["suspend"] == [2] and later["tag_notes"] == [20], language


def test_a_chinese_run_never_sets_aside_a_card_surasura_made(tmp_path):
    """Chinese: the same rule, end to end — 頭髮 Connect's and off the list, never suspended; 學習 yours, suspended."""
    path = tmp_path / "results" / "priority_learning_list.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Word,Orth,Reading,Tier\n发展,发展,,NOW\n关系,关系,,NOW\n", encoding="utf-8-sig")
    cards, notes, _ = _collection(["發展", "學習", "頭髮", "關係"], dues=[2803, 2802, 2801, 2800])
    for note in notes:
        if note["fields"]["Expression"]["value"] == "頭髮":
            note["tags"] = [CONNECT_TAG]
    fake = FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend"))
    with _patched(fake):
        report = reposition.run(_settings(target_language="zh", zh_script="s", junban_off_list="aside",
                                          junban_later_suspend=True))
    assert report["ok"], report["problems"]
    state = {fake.notes[c["note"]]["fields"]["Expression"]["value"]: c["queue"] for c in fake.cards.values()}
    assert state == {"發展": 0, "學習": -1, "頭髮": 0, "關係": 0}


# --- 2 · the unlocking word first, always; a card that can't keeps its place --------------------------------------- #
def test_the_unlocking_word_comes_first_always_and_a_card_that_cant_keeps_its_place(tmp_path):
    """No switch any more (`junban_ready_first` retired): 眼鏡 is brought right before 散歩, whose sentence needs it;
    冒険 needs 財布, which has no card — it keeps its list place (rank 1, first), never sent behind the list (F16)."""
    _known(tmp_path, ["持つ", "行く", "毎日"])
    _sentence_list(tmp_path, [("冒険", 100, []), ("散歩", 90, []), ("手紙", 85, []), ("眼鏡", 80, []),
                              ("財布", 70, [])])
    fake = _mined_sentences([("冒険", "冒険で財布を落とした。"), ("散歩", "散歩に眼鏡を持って行く。"),
                             ("手紙", "手紙に眼鏡の絵を描く。"), ("眼鏡", "眼鏡を毎日かける。")])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert [(row.word, row.why) for row in stats["order"]] == [
        ("冒険", "needs 財布 too · list #1"), ("眼鏡", "first, for 散歩 · list #4"), ("散歩", "after 眼鏡 · list #2"),
        ("手紙", "list #3")]
    assert stats["order"][0].tier == "list" and stats["order"][0].rank == 0
    assert stats["ready_first"] == {"pulled": 1, "kept": 1}


def test_a_loop_or_a_chain_keeps_both_cards_in_their_list_places(tmp_path):
    """散歩 ⇄ 眼鏡 (a loop): neither can come first, so both keep their list places — 散歩 first, as the list says."""
    _known(tmp_path, ["持つ", "行く"])
    _sentence_list(tmp_path, [("散歩", 90, []), ("眼鏡", 80, [])])
    fake = _mined_sentences([("散歩", "散歩に眼鏡を持って行く。"), ("眼鏡", "眼鏡をかけて散歩に行く。")])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert [(row.word, row.tier) for row in stats["order"]] == [("散歩", "list"), ("眼鏡", "list")]
    assert stats["ready_first"] == {"pulled": 0, "kept": 1}


def test_an_old_i_plus_1_first_off_no_longer_changes_anything(tmp_path):
    """A settings.json from 3.0.17 holding `junban_ready_first: false` (the old default) still brings the word first."""
    _known(tmp_path, ["持つ", "行く", "毎日"])
    _sentence_list(tmp_path, [("散歩", 90, []), ("眼鏡", 80, [])])
    fake = _mined_sentences([("散歩", "散歩に眼鏡を持って行く。"), ("眼鏡", "眼鏡を毎日かける。")])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_ready_first=False))
    assert [row.word for row in stats["order"]] == ["眼鏡", "散歩"]


# --- 3 · the one switch for your own cards not on the list -------------------------------------------------------- #
def test_the_one_switch_reads_3_0_17s_keys_until_it_is_set():
    """`junban_off_list` unset (""): any of the three old ticks → *Set aside*; *At the back* → back; anything else
    (*After it*, *Mixed in*) → *Leave*. Set, it decides, and old ticks left in the file no longer set anything aside."""
    choice = unlisted.choice
    assert choice({}) == "leave"
    assert choice({"junban_unlisted": "journey"}) == "leave"
    assert choice({"junban_unlisted": "back"}) == "back"
    assert choice({"junban_unlisted": "list_first", "junban_later_flag": True}) == "aside"
    assert choice({"junban_unlisted": "back", "junban_later_suspend": True}) == "aside"
    assert choice({"junban_off_list": "leave", "junban_later_tag": True}) == "leave"
    assert choice({"junban_off_list": "back", "junban_later_suspend": True}) == "back"
    assert choice({"junban_off_list": " Aside "}) == "aside"
    assert choice({"junban_off_list": "garbled", "junban_unlisted": "back"}) == "back"


def test_set_aside_always_tags_and_flags_or_suspends_as_ticked_and_nothing_else_marks():
    """*Set aside* tags `Surasura::later` (how a set-aside card is found), plus the flag / suspend ticks; *Leave* and
    *At the back* mark nothing, whatever the ticks say."""
    assert unlisted.options({"junban_off_list": "aside"}) == {"tag": True, "flag": False, "suspend": False}
    assert unlisted.options({"junban_off_list": "aside", "junban_later_flag": True, "junban_later_suspend": True}) \
        == {"tag": True, "flag": True, "suspend": True}
    for value in ("leave", "back"):
        assert unlisted.options({"junban_off_list": value, "junban_later_tag": True, "junban_later_flag": True,
                                 "junban_later_suspend": True}) == {"tag": False, "flag": False, "suspend": False}


def test_at_the_back_puts_your_off_list_cards_behind_the_list_and_still_brings_words_first(tmp_path):
    """*At the back*: 須藤 / 図書館 keep their order behind every placed card (no tier) — and, unlike 3.0.17's *At the
    back*, the list's own cards are still ordered by tiers (known last, the unlocking word first)."""
    stats = _order(scene(tmp_path, [("公園", "公園に行った。", 100, [], 0)] + SCENE), junban_off_list="back",
                   junban_later_tag=False, junban_later_flag=False, junban_later_suspend=False)
    assert _row_of(stats, "須藤").tier == "back" and _row_of(stats, "図書館").tier == "back"
    words = [row.word for row in stats["order"]]
    # ...still ahead of the words you already know (公園): known last (D3), in the order they had among themselves
    assert _row_of(stats, "公園").tier == "known" and words.index("須藤") < words.index("図書館") < words.index("公園")
    assert stats["ready_first"] is not None
    assert stats["later"] == {}


def test_a_positions_only_reorder_keeps_set_asides_place_and_marks_nothing():
    """`auto.decide_actions` (positions only): *Set aside*'s cards keep their place at the back, and nothing is
    tagged — so a positions-only move and the run you start in 順 put every card in the same place."""
    decided = auto.decide_actions({"junban_off_list": "aside", "junban_later_suspend": True}, positions_only=True)
    assert unlisted.choice(decided) == "back"
    assert unlisted.options(decided) == {"tag": False, "flag": False, "suspend": False}
    decided = auto.decide_actions({"junban_unlisted": "list_first", "junban_later_tag": True}, positions_only=True)
    assert unlisted.choice(decided) == "back", "an old file's set aside keeps its place too"
    decided = auto.decide_actions({"junban_off_list": "leave"}, positions_only=True)
    assert unlisted.choice(decided) == "leave"
