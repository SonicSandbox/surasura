# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-A: every Junban run weaves Current's top two titles while *New cards come from* is *Top two, side by side* —
through `reposition` itself, on the fake collection Junban's suites share (`connect_scene`): the titles are read once
per run in `_plan_scope` beside the pins, so the 順 window's preview and Reorder and the fast re-plan's automatic job
(`spaced.Job`) all weave the same order. Off (no titles from the store), every request is the request it was.

Title A's cards (冒険, 散歩) and title B's (老婆, 眼鏡, 図書館) name their episode in Anki Miner's source; 須藤 names
none (title 3's, or a card made by hand). Real words; never Anki.
"""
import pytest

from modules.junban import connect, pins, reposition, spaced
from modules.junban.tests.connect_scene import scene, settings, without_connect
from modules.junban.tests.test_reposition import _patched

A_SOURCE = "星の旅人 — 星の旅人 - 05 @ 00:04:31"
B_SOURCE = "夜の図書館 — 夜の図書館 - 02 @ 00:11:02"
ENTRIES = without_connect([
    ("冒険", "冒険が始まった。", 2000, [], 0),
    ("散歩", "毎朝<b>散歩</b>に出かける。", 3000, [], 0),
    ("老婆", "老婆が笑った。", 7000, [], 0),
    ("眼鏡", "新しい眼鏡を買った。", 5000, [], 0),
    ("図書館", "図書館で本を読んだ。", 6000, [], 0),
    ("須藤", "須藤さんが来た。", 9000, [], 0),
])
SIDE = ([[1], [2]], {}, {1: {pins.source_of(A_SOURCE)}, 2: {pins.source_of(B_SOURCE)}})


def _fake(tmp_path):
    fake = scene(tmp_path, ENTRIES)
    for word, source in (("冒険", A_SOURCE), ("散歩", A_SOURCE), ("老婆", B_SOURCE), ("眼鏡", B_SOURCE),
                         ("図書館", B_SOURCE)):
        fake.notes[fake.card_of(word)["note"]]["fields"]["MiscInfo"]["value"] = source
    return fake


@pytest.fixture
def side(monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: SIDE)


def test_off_the_order_is_the_journeys(tmp_path, monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: ([], {}, {}))
    fake = _fake(tmp_path)
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
    assert [row.word for row in stats["order"]] == ["冒険", "散歩", "眼鏡", "老婆", "図書館", "須藤"]
    assert "woven" not in stats and all(row.weave is None for row in stats["order"])


def test_on_the_two_titles_take_turns_and_the_run_writes_what_it_previewed(tmp_path, side):
    """A's 冒険 (its best by Score), B's 老婆 (Score 30 beats 眼鏡's 10, though 眼鏡 is met first), A's 散歩, then B
    alone: 眼鏡 (placed with the list) before 図書館 (i+1); 須藤, no title's, after."""
    fake = _fake(tmp_path)
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
        report = reposition.run(settings(junban_unlisted="journey"))
    assert report["ok"], report["problems"]
    want = ["冒険", "老婆", "散歩", "眼鏡", "図書館", "須藤"]
    assert [row.word for row in stats["order"]] == want
    assert stats["woven"] == 5
    # the window's run also puts away the cards not on your list (図書館, 須藤: suspended, as without the weave)
    assert fake.queue_order() == [w for w in want if fake.card_of(w)["queue"] == 0] == want[:4]


def test_the_fast_re_plans_job_weaves_the_same_order_as_a_window_run(tmp_path, side):
    """The automatic job (the fast re-plan's, `spaced.Job`) reads the titles in the same `_plan_scope`: the same order,
    tomorrow's cards first."""
    fake = _fake(tmp_path)
    with _patched(fake):
        _writes, window = reposition.dry_run(settings(junban_unlisted="journey"))
    again = _fake(tmp_path / "job")
    with _patched(again):
        report = reposition.run(settings(junban_unlisted="journey"), refresh=False, job=spaced.Job(automatic=True))
    assert report["ok"], report["problems"]
    assert again.queue_order() == [row.word for row in window["order"]]


# --- Kyou-B: one slot a word, the list words first ---------------------------------------------------------------- #
def _fake_with(tmp_path, entries, sources):
    """The scene with `entries` (word, sentence, FreqSort); `sources[k]` the episode the k-th card names (None: none)."""
    fake = scene(tmp_path, without_connect([(w, s, f, [], 0) for w, s, f in entries]))
    for card, source in zip(sorted(fake.cards.values(), key=lambda c: c["cardId"]), sources):
        if source is not None:
            fake.notes[card["note"]]["fields"]["MiscInfo"]["value"] = source
    return fake


TWIN = ([("冒険", "冒険が始まった。", 2000), ("散歩", "毎朝<b>散歩</b>に出かける。", 3000),
         ("冒険", "冒険の話を聞いた。", 2000), ("老婆", "老婆が笑った。", 7000), ("眼鏡", "新しい眼鏡を買った。", 5000),
         ("須藤", "須藤さんが来た。", 9000)],
        [A_SOURCE, A_SOURCE, B_SOURCE, B_SOURCE, B_SOURCE, None])
OFF_LIST = ([("冒険", "冒険が始まった。", 2000), ("図書館", "図書館で本を読んだ。", 6000),
             ("老婆", "老婆が笑った。", 7000), ("眼鏡", "新しい眼鏡を買った。", 5000),
             ("散歩", "毎朝<b>散歩</b>に出かける。", 3000), ("須藤", "須藤さんが来た。", 9000)],
            [A_SOURCE, A_SOURCE, B_SOURCE, B_SOURCE, B_SOURCE, None])


def test_a_word_with_cards_in_both_titles_takes_one_slot_and_its_twin_waits_after_the_turns(tmp_path, side):
    """Rule 1 through a run: B's own 冒険 card (another sentence) takes no turn and no early slot — B's turns go to
    老婆 and 眼鏡, and the twin waits after the turns, ahead of 須藤 (no title's)."""
    fake = _fake_with(tmp_path, *TWIN)
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
    words = [row.word for row in stats["order"]]
    assert words == ["冒険", "老婆", "散歩", "眼鏡", "冒険", "須藤"]
    assert stats["order"][4].weave[0] == 1 and stats["woven"] == 5


def test_both_titles_list_words_come_before_a_titles_card_off_the_list(tmp_path, side):
    """Rule 2 through a run: A's 図書館 is off the list (i+1); it waits while B still has list words (老婆, 眼鏡, 散歩)."""
    fake = _fake_with(tmp_path, *OFF_LIST)
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
    words = [row.word for row in stats["order"]]
    assert words[:2] == ["冒険", "老婆"] and set(words[2:4]) == {"眼鏡", "散歩"}
    assert words[4:] == ["図書館", "須藤"]


@pytest.mark.parametrize("which", ["twin", "off_list"])
def test_the_window_its_reorder_and_the_fast_re_plan_give_the_kyou_b_order_alike(tmp_path, side, which):
    """The 順 window's preview, its Reorder and the automatic job (`spaced.Job`) all plan in `_plan_scope`: one order."""
    entries, sources = TWIN if which == "twin" else OFF_LIST
    fake = _fake_with(tmp_path, entries, sources)
    with _patched(fake):
        _writes, window = reposition.dry_run(settings(junban_unlisted="journey"))
        report = reposition.run(settings(junban_unlisted="journey"))
    assert report["ok"], report["problems"]
    want = [row.word for row in window["order"]]
    assert fake.queue_order() == [w for w in want if w in fake.queue_order()]
    again = _fake_with(tmp_path / "job", entries, sources)
    with _patched(again):
        report = reposition.run(settings(junban_unlisted="journey"), refresh=False, job=spaced.Job(automatic=True))
    assert report["ok"], report["problems"]
    assert again.queue_order() == want


C_SOURCE = "白銀の書庫番 — 白銀の書庫番 - 03 @ 00:02:10"
THREE = ([[1], [2], [3]], {}, {1: {pins.source_of(A_SOURCE)}, 2: {pins.source_of(B_SOURCE)},
                              3: {pins.source_of(C_SOURCE)}})
HIS = ([("冒険", "冒険が始まった。", 2000),                                   # the book: one card left
        ("老婆", "老婆が笑った。", 7000), ("眼鏡", "新しい眼鏡を買った。", 5000),       # the channel's two videos
        ("散歩", "毎朝<b>散歩</b>に出かける。", 3000), ("図書館", "図書館で本を読んだ。", 6000),   # a show
        ("須藤", "須藤さんが来た。", 9000)],                                         # no title's
       [A_SOURCE, B_SOURCE, B_SOURCE, C_SOURCE, C_SOURCE, None])


def test_when_a_title_runs_out_the_next_one_steps_in_through_every_run(tmp_path, monkeypatch):
    """Kyou-B, the tester's case through Junban itself: the store hands every title to study (the book, the channel,
    a show); the book has one card left, so after its one turn the show steps in beside the channel (two at a time,
    never three: before, the show took a turn from the first round) — in the 順 window's preview, its Reorder and the
    fast re-plan's job alike."""
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: THREE)
    fake = _fake_with(tmp_path, *HIS)
    with _patched(fake):
        _writes, window = reposition.dry_run(settings(junban_unlisted="journey"))
        report = reposition.run(settings(junban_unlisted="journey"))
    assert report["ok"], report["problems"]
    woven = [row for row in window["order"] if row.weave is not None]
    assert [row.weave[0] for row in woven] == [0, 1, 1, 2, 2]
    assert [row.word for row in woven][:2] == ["冒険", "老婆"] and window["order"][-1].word == "須藤"
    want = [row.word for row in window["order"]]
    assert fake.queue_order() == [w for w in want if w in fake.queue_order()]
    again = _fake_with(tmp_path / "job", *HIS)
    with _patched(again):
        report = reposition.run(settings(junban_unlisted="journey"), refresh=False, job=spaced.Job(automatic=True))
    assert report["ok"], report["problems"]
    assert again.queue_order() == want


def test_a_card_two_titles_claim_by_different_rules_is_in_both_groups_as_before():
    """`pins._matched` walks the cards once now (it is handed every Current title): a card the store's notes give to
    title A and whose Anki Miner source names title B's episode is still in both groups — the plan then gives it to
    the first, as it did when each group walked the cards itself."""
    notes_by_id = {500: {"fields": {"MiscInfo": B_SOURCE}}, 501: {"fields": {"MiscInfo": ""}}}   # as `_plan_scope` hands them
    cards = [{"card_id": 10, "note": 500}, {"card_id": 11, "note": 501}]
    got = pins._matched([[1], [2], [3]], cards, notes_by_id, {1: [500], 3: [501]},
                        {2: {pins.source_of(B_SOURCE)}})
    assert got == [[10], [10], [11]]


def test_each_turn_takes_the_word_with_the_most_impact_not_the_one_met_first(tmp_path, monkeypatch):
    """Decision 3 (the word's place on the whole list), with Junban in content order: title A holds 散歩 (met first,
    in file 1, Score 20) and 老婆 (file 3, Score 30) — A's turn takes 老婆 first; B's 冒険 between them."""
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: SIDE)
    fake = scene(tmp_path, without_connect([("散歩", "毎朝<b>散歩</b>に出かける。", 3000, [], 0),
                                            ("老婆", "老婆が笑った。", 7000, [], 0),
                                            ("冒険", "冒険が始まった。", 2000, [], 0)]))
    for word, source in (("散歩", A_SOURCE), ("老婆", A_SOURCE), ("冒険", B_SOURCE)):
        fake.notes[fake.card_of(word)["note"]]["fields"]["MiscInfo"]["value"] = source
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
    assert [row.word for row in stats["order"]] == ["老婆", "冒険", "散歩"]
