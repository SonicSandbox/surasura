"""Setup's first look for the sort screen (Mado-O, Sonic 2026-10-30): `sources.scan(first=library_store.SORT)` lands
every show in New arrivals — each show's episodes together, in order, quietly (no placing rule takes them, nothing is
logged, no card is made: S1) — for the sort screen to place; a 2.x library's tier folder keeps K8's tier; *Start
fresh*'s `first=True` is unchanged. And the sort screen's *Ignore* asks `skip_choices(..., own=True)`: only a folder
holding no other title's files.

What a wrong answer would cost a learner:
  * his whole library dumped into Current before he said where anything goes (the old SRC-1), or a show's episodes
    scattered through New arrivals so the sort screen shows one show as many titles;
  * a sort that quietly logs moves or starts cards for shows he never chose;
  * his 2.x Goal folder (2,500 items) back in a pile to sort again;
  * *Ignore* on one show that never reads a folder holding his other shows too (a folder named with `_` or `%` read
    as a pattern).

Real Japanese / Chinese texts from tests/Test Resources in temp folders beside the test's data folder; made-up shows.
"""
import os

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES
from tests.test_setup_2x_tiers import SHOWS as OLD_SHOWS
from tests.test_setup_2x_tiers import _old_library, _tiers
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _text, _write  # noqa: F401

SHOWS = {"ja": ("月影の旅人", "星空喫茶"), "zh": ("夜市小记", "清河灯笼")}


def _source(language, shows, start=0, name="anime"):
    """A source folder holding `shows` {show: episodes}, real text each (told apart by `start` on)."""
    root = _drive(name)
    n = start
    for show, episodes in shows.items():
        for e in range(1, episodes + 1):
            _write(os.path.join(root, show, f"{show} - {e:02d}.srt"), _text(language, n, extra=f"「{show}{e}」"))
            n += 1
    return root


def _rows(store):
    return store.conn.execute("SELECT id, tier, ord, rel_path FROM items ORDER BY id").fetchall()


def _logged(store):
    return store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_setups_look_for_sorting_lands_every_show_in_new_arrivals_together_and_in_order_quietly(language):
    store, _data = _empty(language)
    a, b = SHOWS[language]
    src = _source(language, {a: 3, b: 2})
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=ls.SORT)
        rows = _rows(store)
        assert len(got["ids"]) == 5 and sorted(got["ids"]) == sorted(i for i, *_r in rows)
        assert {tier for _i, tier, _o, _r in rows} == {"arrivals"}, "New arrivals, never Current"
        in_order = [rel for _i, _t, _o, rel in sorted(rows, key=lambda r: r[2])]
        shows = [rel.split("/")[1] for rel in in_order]
        runs = [s for i, s in enumerate(shows) if i == 0 or shows[i - 1] != s]
        assert sorted(runs) == sorted((a, b)), "each show's episodes together: one run each"
        for show in (a, b):                                                  # … in episode order
            eps = [rel for rel in in_order if rel.split("/")[1] == show]
            assert eps == sorted(eps)
        assert _logged(store) == 0, "quiet: no placing rule, nothing logged (S1)"
        assert store._mine_ids(store.meta().get("mine_line", ls.MINE_LINE_DEFAULT)) == []     # nothing to mine


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_second_folder_of_the_same_show_joins_its_run_in_new_arrivals(language):
    """Two picked folders holding the same show (a season split over two drives): its episodes from the second land
    in its run in New arrivals — one title on the sort screen, not two."""
    store, _data = _empty(language)
    a, b = SHOWS[language]
    first = _source(language, {a: 2, b: 1}, name="anime")
    second = _drive("more")
    _write(os.path.join(second, a, f"{a} - 03.srt"), _text(language, 40, extra=f"「{a}3」"))
    with store:
        _look(store, language, store.add_source(first), first=ls.SORT)
        _look(store, language, store.add_source(second), first=ls.SORT)
        rows = sorted(_rows(store), key=lambda r: r[2])
        assert {t for _i, t, _o, _r in rows} == {"arrivals"}
        shows = [rel.split("/")[1] for *_x, rel in rows]
        runs = [s for i, s in enumerate(shows) if i == 0 or shows[i - 1] != s]
        assert sorted(runs) == sorted((a, b)) and shows.count(a) == 3


@pytest.mark.parametrize("language", LANGUAGES)
def test_start_fresh_still_lands_in_current(language):
    """`first=True` (*Start fresh*, 2.x's own scan) is unchanged: Current, by show."""
    store, _data = _empty(language)
    with store:
        root = store.add_source(_source(language, {SHOWS[language][0]: 3}))
        _look(store, language, root, first=True)
        assert {t for _i, t, _o, _r in _rows(store)} <= {"now", "soon"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_k8_a_2x_goal_folder_keeps_goal_and_its_now_folder_current_when_read_for_sorting(language):
    """A 2.x library's tier folders read by setup's look for sorting keep K8's tiers: Goal in Goal, HighPriority in
    Current — never back in a pile to sort again."""
    store, _data = _empty(language)
    data = _old_library(language)
    goal_show, now_show = OLD_SHOWS[language]
    with store:
        for tier_folder in ("GoalContent", "HighPriority"):
            _look(store, language, store.add_source(os.path.join(data, tier_folder)), first=ls.SORT)
        tiers = _tiers(store)
    assert len(tiers["goal"]) == 3 and all(goal_show in t for t in tiers["goal"])
    assert len([t for t in tiers["now"] + tiers["soon"] if now_show in t]) == 3
    assert tiers["arrivals"] == []


def test_ignore_offers_only_a_folder_that_holds_no_other_titles_files():
    """*Ignore* on a show (`own=True`): its own folder, and never one above it that also holds another title — a
    show's Extras inside it is another title, so the show's episodes alone get no folder (*Ignore* takes them out of
    the library instead), the episodes with their Extras get the show's folder, the Extras alone their own folder.
    ⋯'s *Never read this folder* (`own` off) still offers every folder up to the source."""
    language = "ja"
    store, _data = _empty(language)
    a, b = SHOWS[language]
    src = _source(language, {a: 2, b: 2})
    extras = _write(os.path.join(src, a, "Extras", "Making of.srt"), _text(language, 30, extra="「特典」"))
    with store:
        _look(store, language, store.add_source(src), first=ls.SORT)
        origins = store.origins()
        extra_id = origins[ls.origin_key(extras)[4:]].item_id
        rows = _rows(store)
        a_eps = [i for i, _t, _o, rel in rows if rel.split("/")[1] == a and i != extra_id]
        b_eps = [i for i, _t, _o, rel in rows if rel.split("/")[1] == b]
        show_a, show_b = ls.folder_path(os.path.join(src, a)), ls.folder_path(os.path.join(src, b))
        assert store.skip_choices(a_eps) == [show_a]                         # ⋯'s rule: every folder up to the source
        assert store.skip_choices(a_eps, own=True) == []                     # … but it holds the Extras too
        assert store.skip_choices(a_eps + [extra_id], own=True) == [show_a]
        assert store.skip_choices([extra_id], own=True) == [ls.folder_path(os.path.join(src, a, "Extras"))]
        assert store.skip_choices(b_eps, own=True) == [show_b]


@pytest.mark.parametrize("wild", ["_", "%"])
def test_ignore_reads_a_folder_name_as_written_never_as_a_pattern(wild):
    """A show folder named with `_` or `%` (`月_1`): a sibling it would match as a pattern (`月A1`) holds other titles'
    files, never this folder's — so the show's own folder is still offered."""
    language = "ja"
    store, _data = _empty(language)
    named, sibling = f"月{wild}1", "月A1"
    src = _source(language, {named: 2, sibling: 2})
    with store:
        _look(store, language, store.add_source(src), first=ls.SORT)
        mine = [i for i, _t, _o, rel in _rows(store) if rel.split("/")[1] == named]
        assert len(mine) == 2
        assert store.skip_choices(mine, own=True) == [ls.folder_path(os.path.join(src, named))]
