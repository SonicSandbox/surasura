"""Kura-GS (3.0.18; Sonic 2026-11-21, the journey's round 8): a real Generate keeps each file's growth snapshot.

Two shows in NOW, three episodes each, cut from the bundled samples' real text, one real line with a word met nowhere
else seeded into Show A's first episode (test_generate_watched's library). Generate runs as the dashboard starts it
(`analyzer.py`, its own process). Then:

  - every file it counted has its 'added' and its 'last' in the library store — the very count the window's *% known*
    shows (the plan file's per-file `prog`: the tokens known before any file over the tokens counted) and the words
    in it not known (each once: more than none, never more than its unknown tokens);
  - that word put on the Ignore list → Generate: the episode's 'last' knows its every use and has one word fewer to
    learn, its 'added' what it was; every other file as it was;
  - the episode marked ✓ Done: its 'done' is that 'last'; the next Generate (the episode set aside, no longer
    counted) leaves all of it as it was.

What a wrong answer would cost a learner: a growth figure that was never his (another file's, or a later Generate's
shown as *when you added it*), or a number that disagrees with the % he sees on the row. Japanese and Chinese alike,
under the per-test SURASURA_TEST_ROOT.
"""
import os
import time

import pytest

from app import library_store as ls, plan_engine
from app.services import moves as M, view_rows
from tests.test_generate_watched import SEEDS, _generate, _library
from tests.test_library_store_support import LANGUAGES, roots


def _plan_counts(root, store):
    """{item id: (known before any file, counted)} as the plan file holds them — what the window's rows show."""
    plan = plan_engine.load(os.path.join(root, "results", "plan.json.gz"), pools=False)
    by_key = store.item_keys()
    return {by_key[ls.path_key(entry[0])]: (plan.per_file[f]["prog"][1], plan.per_file[f]["prog"][0])
            for f, entry in enumerate(plan.files)}


def _snaps(store, kind):
    return {i: (s[kind]["known"], s[kind]["counted"], s[kind]["unknown"])
            for i, s in store.growth_of(kinds=(kind,)).items()}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_generate_keeps_each_files_figures_as_the_window_counts_them_and_a_done_keeps_them_then(language):
    root = os.environ["SURASURA_TEST_ROOT"]
    store, paths, ids = _library(language)
    (only, _line), _later = SEEDS[language]
    _generate(root, language)
    counts = _plan_counts(root, store)
    added, last = _snaps(store, "added"), _snaps(store, "last")
    assert set(counts) == set(ids.values()) == set(added) == set(last), "every counted file, nothing else"
    for item, (known, counted) in counts.items():
        assert added[item][:2] == (known, counted), "the window's own count"
        assert 0 < added[item][2] <= counted - known, "words not known: some, never more than the unknown tokens"
    assert last == added
    assert all(s["added"]["prior"] for s in store.growth_of().values()), "the library came with the store's build"
    # The window's numbers read them after the plan (`Numbers.growth`): the % hover's line says the row's own number
    numbers = M.Numbers(M.store_opener(language), language)
    try:
        numbers._load()
        deadline = time.monotonic() + 20
        while numbers.growth(ids["A1"]) is None and time.monotonic() < deadline:
            time.sleep(0.02)
        _v, table = numbers()
        for item in ids.values():
            known, counted, _n = table[item]
            line = view_rows.growth_line(numbers.growth(item))
            assert line == view_rows.STRINGS["growth_since"].format(
                day=view_rows.day_label(store.growth_of([item])[item]["added"]["at"]),
                pct=round(view_rows.pct_of(known, counted))), line
    finally:
        numbers.close()

    _d, user_files_dir = roots(language)
    with open(os.path.join(user_files_dir, "IgnoreList.txt"), "a", encoding="utf-8") as f:
        f.write(f"\n{only}\n")                                  # (the seed: in Show A's first episode alone)
    _generate(root, language)
    now = _snaps(store, "last")
    a1 = ids["A1"]
    assert _snaps(store, "added") == added, "'added' is what it was then"
    assert now[a1][1] == added[a1][1] and now[a1][0] > added[a1][0], "its every use now known, nothing else counted"
    assert now[a1][2] == added[a1][2] - 1, "one word fewer to learn"
    assert {i: v for i, v in now.items() if i != a1} == {i: v for i, v in added.items() if i != a1}
    assert {i: v[:2] for i, v in now.items()} == _plan_counts(root, store)

    store.set_watched([a1])
    assert _snaps(store, "done") == {a1: now[a1]}
    _generate(root, language)
    assert a1 not in _plan_counts(root, store), "set aside: no longer counted"
    assert _snaps(store, "last") == now and _snaps(store, "done") == {a1: now[a1]}
    assert _snaps(store, "added") == added
    store.close()
