"""Kyou-D: side by side's reach — only titles above the Soon line step in, and the line never pulls a long title into
NOW whole (the lead's lean, Sonic 2026-11-16; the edge cases: TheForge `tracks/logic/work/kyou-d/EDGES.md`, E1–E16).

Train 39's intent keeper found it: a two-video channel, a 100-part book and a third title, with the Soon line at 20,
left the whole book in NOW (the channel ran out, the third title stepped in from far below, and the line reached for
its files). The guard is in the one shared rule (`library_store.side_pair`: who can take turns; `side_reach`: how far
the line goes), so the store's readers, the window and Junban all agree.

What a wrong answer would cost a learner: a hundred parts of a book they're not reading yet counted as *Now* by
Generate (every one of its words weighed as studied now), the line jumping far down the list after a drag, a title
from Soon woven into Anki ahead of the titles they put above the line, the second season of a show mined before the
first — or an Undo that puts a dragged title at the top of the list instead of back where it was.

Every test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with real words
from tests/Test Resources/ (`library_store_support.names`).
"""
import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, entry, names, roots, touch, write_manifest

FOLDER = {"now": "HighPriority", "soon": "LowPriority", "goal": "GoalContent"}


def _library(language, spec, line, tiers=None, seasons=None, mine=20):
    """`spec`: [(letter, files)] in Current's order, every title a show folder named with a real word (each in NOW
    unless `tiers` says 'soon' / 'goal'; `seasons`: {letter: 'Season N'} — that title a season folder of one shared
    show folder). The Soon line at `line`, side by side on. -> (store, {letter: [ids in order]})."""
    data_dir, user_files_dir = roots(language)
    words = names(language)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    letter_of = {}
    for k, (letter, count) in enumerate(spec):
        tier = (tiers or {}).get(letter, "now")
        show = words[10 + k]
        folder = f"{words[9]}/{seasons[letter]}" if seasons and letter in seasons else show
        for e in range(1, count + 1):
            rel = f"{FOLDER[tier]}/{folder}/{show}_第{e:03d}話.srt"
            touch(data_dir, rel, f"{show} {e}\n")
            doc["schedule"][ls.TIERS[tier][0]].append(entry(rel))
            letter_of[rel] = letter
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    ids = {letter: [] for letter, _n in spec}
    for item_id, rel in store.conn.execute("SELECT id, rel_path FROM items ORDER BY id"):
        ids[letter_of[rel.replace("\\", "/")]].append(item_id)
    store.set_soon_line(line)
    store.set_library_options(mine_line=mine, side_by_side=True)
    return store, ids


def _count(store):
    """The store's kept count without its time (Kyou-E's `SIDE_AT`): {card key: 0 / 1}."""
    return {k: v for k, v in (store._side_cards() or {}).items() if k != ls.SIDE_AT}


def _letters(store, ids, seq):
    of = {i: letter for letter, group in ids.items() for i in group}
    return "".join(of[i] for i in seq)


def _groups(store, ids):
    return ["".join(sorted({_letters(store, ids, [i]) for i in g})) for g in store.side_by_side()]


def _now(store, ids):
    return _letters(store, ids, store.ids("now"))


# --- the rule, pure ------------------------------------------------------------------------------------------------ #

def test_above_the_line_is_the_lines_own_count_with_its_waiting_rows():
    """The first `line` rows with text, and the waiting rows right after (as `_keep_line` cuts)."""
    rows = [(1, "now", 10, "available", 0), (2, "now", 13, "waiting", 0), (3, "now", 11, "available", 0),
            (4, "now", 14, "waiting", 0), (5, "soon", 12, "available", 0), (6, "soon", None, "available", 0)]
    assert ls.above_line(rows, 1) == {("w", 10), ("w", 13)}, "the waiting row after the 1st stays with it"
    assert ls.above_line(rows, 2) == {("w", 10), ("w", 13), ("w", 11), ("w", 14)}
    assert ls.above_line(rows, 0) == set()
    assert ls.above_line(rows, 9) == {("w", 10), ("w", 13), ("w", 11), ("w", 14), ("w", 12), ("i", 6)}


def test_the_reach_takes_the_turns_files_but_never_more_than_the_count_it_doesnt_take():
    """A6 B3, line 3 (answer 5): the turns' 3rd file is B1, three untaken of A between — allowed (NOW 7). A long
    first title (8 untaken over a line of 3): the line stays at its count."""
    rows = [(i, "now", 1, "available", 0) for i in range(1, 7)] + [(i, "now", 2, "available", 0) for i in (7, 8, 9)]
    assert ls.side_reach(rows, 3, [1, 7, 2]) == 7
    rows = [(i, "now", 1, "available", 0) for i in range(1, 12)] + [(12, "now", 2, "available", 0)]
    assert ls.side_reach(rows, 3, [1, 12, 2]) == 3
    watched = [(i, "now", 1, "available", 1) for i in range(1, 12)] + [(12, "now", 2, "available", 0)]
    assert ls.side_reach(watched, 3, [12]) == 12, "a watched row is free (KA-7)"
    waiting = [(1, "now", 1, "available", 0), (2, "now", 1, "available", 0), (3, "now", 1, "available", 0)] +         [(i, "now", 3, "waiting", 0) for i in range(4, 10)] + [(10, "now", 2, "available", 0)]
    assert ls.side_reach(waiting, 2, [1, 10]) == 4, "a waiting row is no row the line counts, and costs nothing"


def test_two_seasons_of_one_show_folder_are_one_title_and_nothing_else_is():
    works = [(3, "frieren/season 2"), (2, "frieren/season 1"), (4, "frieren"), (5, "other/season 1"),
             (6, "solo/extras"), (7, None), (8, "frieren/movie"), (9, "frieren/specials")]
    assert ls.season_works(works) == {2: 2, 3: 2}, "one season alone, a show's own folder, specials: as they are"


# --- the library: the keeper's probe and the cases around it (EDGES.md E1–E8) --------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_keepers_probe_a_long_book_is_never_pulled_into_now_whole(language):
    """E1 (before: NOW 110). The channel (2) runs out; the third title is far below the line, so it doesn't step in:
    the book goes on alone, and NOW holds the line's count. No Junban count (Anki closed, E15): the same."""
    store, ids = _library(language, [("A", 2), ("B", 100), ("C", 12)], 20)
    assert store._side_cards() is None
    assert _groups(store, ids) == ["A", "B"]
    assert _letters(store, ids, store._mine_ids(20)) == "ABAB" + "B" * 16
    assert len(store.ids("now")) == 20 and _now(store, ids) == "AA" + "B" * 18
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_long_first_title_is_never_pulled_whole_to_reach_the_second(language):
    """E1b (before: NOW 102): the book first fills the line; the channel is still one of the first two (it takes its
    turns from below the line), but the line won't pull 80 untaken parts to reach it. E7b: a first title of 30 with the
    line at 20 is pulled 10 (within the count): NOW 40, as before."""
    store, ids = _library(language, [("B", 100), ("A", 2)], 20)
    assert _groups(store, ids) == ["B", "A"]
    assert _letters(store, ids, store._mine_ids(4)) == "BABA"
    assert _now(store, ids) == "B" * 20
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_first_title_a_little_longer_than_the_line_still_brings_the_second_above_it(language):
    """E7b: 30 then 10, the line at 20: 10 of A's untaken files are pulled (within the line's count), B's first ten
    turns stay above it — NOW 40, as before the guard."""
    store, ids = _library(language, [("A", 30), ("B", 10)], 20)
    assert _now(store, ids) == "A" * 30 + "B" * 10
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("tier", ["now", "soon"])
def test_a_300_episode_show_below_the_line_never_steps_in(language, tier):
    """E2 / E5 (before: its first files pulled up): A (2) runs out, B (10) goes on alone; the long show under the line
    (in NOW past the count, or in Soon) is mined after B in Current's order, never woven in."""
    store, ids = _library(language, [("A", 2), ("B", 10), ("C", 300)], 10, tiers={"C": tier})
    assert _groups(store, ids) == ["A", "B"]
    assert _letters(store, ids, store._mine_ids(20)) == "ABAB" + "B" * 8 + "C" * 8
    assert _now(store, ids) == "AA" + "B" * 8
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_above_the_line_steps_in_and_brings_only_its_turns(language):
    """E2b: the line at 14 holds C's first two: C steps in for A and the line takes 3 more of C's own turn files."""
    store, ids = _library(language, [("A", 2), ("B", 10), ("C", 300)], 14)
    assert _groups(store, ids) == ["A", "B", "C"]
    assert _letters(store, ids, store._mine_ids(8)) == "ABABBCBC"
    assert _now(store, ids) == "AA" + "B" * 10 + "C" * 5
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_with_one_file_left_hands_on_only_above_the_line(language):
    """E3 (before: NOW 12): A's one file, then B alone — C is below the line."""
    store, ids = _library(language, [("A", 1), ("B", 10), ("C", 10)], 5)
    assert _letters(store, ids, store._mine_ids(5)) == "ABBBB"
    assert _now(store, ids) == "ABBBB"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_titles_running_out_at_once_hand_on_to_nothing_below_the_line(language):
    """E4: A and B both run out after two; C and D below the line don't step in. Once A and B are watched, C and D are
    Current's first two titles to study: they take turns, and the line takes only C's turn files right under it."""
    store, ids = _library(language, [("A", 2), ("B", 2), ("C", 30), ("D", 30)], 4)
    assert _letters(store, ids, store._mine_ids(8)) == "ABABCCCC"
    assert _now(store, ids) == "AABB"
    store.set_watched(ids["A"] + ids["B"])
    assert _groups(store, ids) == ["C", "D"]
    assert _letters(store, ids, store._mine_ids(4)) == "CDCD"
    assert _now(store, ids) == "AABBCC", "D's turns are below 28 of C's: not reached"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_six_months_and_finished_titles_never_step_in(language):
    """E5b: a title in 6+ Months is not Current: never one of the turns."""
    store, ids = _library(language, [("A", 2), ("B", 5), ("C", 9)], 7, tiers={"C": "goal"})
    assert _groups(store, ids) == ["A", "B"]
    assert _letters(store, ids, store._mine_ids(20)) == "ABABBBB"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_title_running_out_ends_the_turns_and_the_line_is_its_count(language):
    """E6: two titles of two files, the line at 4: the turns end, nothing else to take, NOW is the line's 4."""
    store, ids = _library(language, [("A", 2), ("B", 2)], 4)
    assert _letters(store, ids, store._mine_ids(20)) == "ABAB"
    assert _now(store, ids) == "AABB"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_with_no_new_cards_hands_on_only_above_the_line(language):
    """E8 (Kyou-C's count): B counted no list word still new. Never mined, it keeps its turn (guard a): as E1. Its next
    file mined, it steps aside — and C, far below, doesn't step in (before: NOW 114): A, then B's files after it."""
    store, ids = _library(language, [("A", 2), ("B", 100), ("C", 12)], 20)
    store.set_side_cards([(ids["A"], 1), (ids["B"], 0), (ids["C"], 1)])
    assert len(store.ids("now")) == 20
    store.receipt(ids["B"][0], "2026-10-16T00:00:00")
    assert _letters(store, ids, store._mine_ids(20)) == "AA" + "B" * 18
    assert _now(store, ids) == "AA" + "B" * 18
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_first_title_with_no_new_cards_steps_aside_and_nothing_below_steps_in(language):
    """E8c (before: C stepped in, NOW 15): A counted none and mined — B goes alone, C waits below the line; A's files
    after B's."""
    store, ids = _library(language, [("A", 2), ("B", 10), ("C", 10)], 6)
    store.receipt(ids["A"][0], "2026-10-16T00:00:00")
    store.set_side_cards([(ids["A"], 0), (ids["B"], 1), (ids["C"], 1)])
    assert _letters(store, ids, store._mine_ids(12)) == "B" * 10 + "AA"
    assert _now(store, ids) == "AA" + "B" * 6
    store.close()


# --- a drag across the line, and its Undo (E10, E13) --------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_dragged_above_the_line_steps_in_and_its_undo_takes_it_back(language):
    """E10: C dragged under A (above the line) is a title above it: it takes B's place beside A. Its Undo puts C back
    under the book and the turns are A and B again."""
    store, ids = _library(language, [("A", 2), ("B", 30), ("C", 5)], 20)
    before = (store.ids("now"), store.ids("soon"))
    assert _groups(store, ids) == ["A", "B"]
    change = store.move(ids["C"], "now", after_id=ids["A"][-1])
    assert _groups(store, ids) == ["A", "C", "B"]
    assert _letters(store, ids, store._mine_ids(6)) == "ACACCB", "A runs out: B, still above the line, steps in"
    store.undo(change)
    assert (store.ids("now"), store.ids("soon")) == before
    assert _groups(store, ids) == ["A", "B"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("side", [True, False])
@pytest.mark.parametrize("spec, line, who, where", [
    ([("A", 6), ("B", 3), ("C", 4)], 3, "B", "top"),
    ([("A", 6), ("B", 3), ("C", 4)], 3, "C", "A"),
    ([("A", 6), ("B", 3), ("C", 4)], 3, "A", "end"),
    ([("A", 30), ("B", 10), ("C", 5)], 20, "C", "top")])
def test_undo_of_a_drop_across_a_reached_line_puts_rows_back(language, side, spec, line, who, where):
    """E13: the line moves with a drop (side by side's reach, or the count alone), so a row's old neighbour can sit on
    the other side of it at the Undo; Current is one order, so the Undo puts every row back where it stood (before:
    B at NOW's top; with it off, A back after B)."""
    store, ids = _library(language, spec, line)
    store.set_library_options(side_by_side=side)
    before = (store.ids("now"), store.ids("soon"))
    cur = before[0] + before[1]
    if where == "top":
        change = store.move(ids[who], "now", before_id=cur[0])
    elif where == "end":
        change = store.move(ids[who], "soon", after_id=cur[-1])
    else:
        change = store.move(ids[who], "now", after_id=ids[where][0])
    assert (store.ids("now"), store.ids("soon")) != before
    store.undo(change)
    assert (store.ids("now"), store.ids("soon")) == before
    store.close()


# --- seasons (E12) ------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_two_seasons_of_one_show_take_one_turn(language):
    """E12 (before: S1, S2, S1, S2 …): `Show/Season 1` and `Show/Season 2` are one title side by side — S1's
    episodes, then S2's, take turns with C. Junban's groups hold the show whole; its count names it once."""
    store, ids = _library(language, [("A", 12), ("B", 12), ("C", 12)], 20,
                          seasons={"A": "Season 1", "B": "Season 2"})
    assert _groups(store, ids) == ["AB", "C"]
    assert _letters(store, ids, store._mine_ids(6)) == "ACACAC"
    groups = store.side_by_side()
    assert store.set_side_cards([(groups[0], 0), (groups[1], 1)])
    assert sorted(_count(store)) == sorted({ls.card_key(("w", store._seasons()[store.conn.execute(
        "SELECT work_id FROM items WHERE id = ?", (ids["A"][0],)).fetchone()[0]])), ls.card_key(
        ("w", store.conn.execute("SELECT work_id FROM items WHERE id = ?", (ids["C"][0],)).fetchone()[0]))})
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_off_the_guard_never_runs(language):
    """E16: side by side off, the line and the order are today's (the guard lives only in the rule's readers)."""
    store, ids = _library(language, [("A", 2), ("B", 100), ("C", 12)], 20)
    store.set_library_options(side_by_side=False)
    assert store.side_by_side() == [] and store._side() is None
    assert _now(store, ids) == "AA" + "B" * 18
    assert _letters(store, ids, store._mine_ids(20)) == "AA" + "B" * 18
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_count_handed_from_the_second_season_is_the_shows(language):
    """Mutant D11 (2026-11-17): Junban's group for a two-season show may start with S2's item; the count is still kept
    under the show (its seasons' one key, the smallest work), so the store reads it for the title taking turns."""
    store, ids = _library(language, [("A", 3), ("B", 3), ("C", 3)], 20, seasons={"A": "Season 1", "B": "Season 2"})
    work = {letter: store.conn.execute("SELECT work_id FROM items WHERE id = ?", (ids[letter][0],)).fetchone()[0]
            for letter in "ABC"}
    show = min(work["A"], work["B"])
    assert store.set_side_cards([(ids["B"] + ids["A"], 1), (ids["C"], 0)])
    assert sorted(_count(store).items()) == sorted({ls.card_key(("w", show)): 1,
                                                          ls.card_key(("w", work["C"])): 0}.items())
    store.close()
