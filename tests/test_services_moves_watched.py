"""W-1 (K-W4): the window's numbers after a watched mark — `app/services/moves.py` (and the window's wiring to the
indexer, `app/qt/shell.Services`).

What a wrong answer would cost a learner:
  * a stone that takes an episode's words off the list while every row's *N new* still counts them, until some
    unrelated move asks the numbers again — or a stone in Finished (or with *Keep studying watched episodes* on) that
    makes the whole window work its numbers out again for nothing (S19: update only what changed);
  * the Rarity preview counting the watched episode's words until the next focus, because nobody asked the indexer;
  * a drag of a show holding watched episodes (or a drop beside one) that loses its numbers at the drop: the engine
    holds no watched file, so the drop fell back to a full resync — the rows waited instead of following at once.

The writes run on a real `library_store` (`test_services_moves`' migrated library, Japanese and Chinese), the numbers
on the window's seed (its hero show has two watched episodes at the top of NOW) with a plan shaped like a Generate's,
which since W-1 holds no watched file.
"""
import os
import random
import time

from app.services import moves as M
from tests import services_helpers as h
from tests.fixtures import window_seed
from tests.test_services_chores import _make as _make_chores, indexing_on  # noqa: F401 (a fixture)
from tests.test_services_moves import (Recorder, _engine_from_scratch, _in_order, big, lib,  # noqa: F401 (fixtures)
                                       make_writer, write_plan)

BENCH = os.environ.get("SURASURA_STORE_BENCH") == "1"


def _writer(make_writer):
    numbers, counted = Recorder(), []
    w, heard = make_writer(numbers=numbers, on_counted=lambda: counted.append(1))
    return w, heard, numbers, counted


def _finished_unwatched(lib):
    """An item of Finished that isn't watched (a status-only mark's place): NOW's last, sent there by another window."""
    item = lib.ids("now")[-1]
    lib.store.set_tier([item], "graduated")
    if lib.store.item(item)["watched"]:
        lib.store.set_watched([item], False)
    return item


# --- 1. a counting mark asks the numbers again, a status-only mark never ------------------------------------------ #
def test_W1_a_watched_mark_that_counts_asks_the_numbers_and_the_indexer_a_status_only_mark_neither(lib, make_writer):
    """A stone on a NOW episode (the option off) moves `order_version`: the numbers resync and the indexer is asked,
    once. A stone on a Finished item, or on any item with *Keep studying watched episodes* on, is a status write: today's
    path — saved, nothing asked again."""
    w, heard, numbers, counted = _writer(make_writer)
    finished = _finished_unwatched(lib)
    now = lib.ids("now")
    w.set_watched([now[0]], True)
    assert h.until(lambda: len(heard.saved) == 1)
    assert numbers.resyncs == 1 and counted == [1]
    w.set_watched([finished], True)                     # Finished: never counted, watched or not
    assert h.until(lambda: len(heard.saved) == 2)
    lib.store.set_library_options(keep_watched=True)    # the option on: a stone moves nothing that counts
    w.set_watched([now[1]], True)
    assert h.until(lambda: len(heard.saved) == 3)
    assert lib.store.item(finished)["watched"] == 1 and lib.store.item(now[1])["watched"] == 1
    assert numbers.resyncs == 1 and counted == [1]


def test_W1_undoing_a_mark_asks_the_numbers_again_only_when_it_counted(lib, make_writer):
    """Undo the same: the undo of a status-only mark (Finished) asks nothing; the undo of a counting mark puts the
    episode back on the list, so the numbers and the indexer follow."""
    w, heard, numbers, counted = _writer(make_writer)
    finished = _finished_unwatched(lib)
    now = lib.ids("now")
    w.set_watched([now[0]], True)                       # counts
    w.set_watched([finished], True)                     # status only
    assert h.until(lambda: len(heard.saved) == 2)
    assert numbers.resyncs == 1 and counted == [1]
    w.undo()                                            # the Finished stone
    assert h.until(lambda: len(heard.undone) == 1)
    assert lib.store.item(finished)["watched"] == 0
    assert numbers.resyncs == 1 and counted == [1]
    w.undo()                                            # the NOW stone
    assert h.until(lambda: len(heard.undone) == 2)
    assert lib.store.item(now[0])["watched"] == 0
    assert numbers.resyncs == 2 and counted == [1, 1]


def test_W1_the_keep_watched_option_asks_again_only_when_a_watched_item_counts_by_it(lib, make_writer):
    """`set_options(keep_watched=)` writes the library's option; flipped with nothing watched in Current or Goal it
    moves nothing (no resync, no indexer); flipped with a watched NOW episode it brings the episode back: both asked."""
    w, heard, numbers, counted = _writer(make_writer)
    assert not any(lib.store.item(i)["watched"] for t in M.ANALYSED for i in lib.ids(t))
    w.set_options(keep_watched=True)                    # nothing watched yet: a status write
    assert h.until(lambda: lib.store.meta().get("keep_watched") == 1)
    assert w.idle(5) and numbers.resyncs == 0 and counted == []
    lib.store.set_watched([lib.ids("now")[0]], True)    # another window's stone, while the option is on
    w.set_options(keep_watched=False)                   # the episode leaves the list
    assert h.until(lambda: counted == [1])
    assert lib.store.meta().get("keep_watched") == 0 and numbers.resyncs == 1


def test_W1_a_burst_of_counting_marks_asks_the_indexer_once_while_it_runs(lib, make_writer, indexing_on):
    """Each counting mark asks the indexer (forced); the chores' own rule makes a burst one run: one check and one
    indexer at a time, the next asks answered *busy* until it ends."""
    chores, registry, popen = _make_chores(lang=lib.language)
    asked = []

    def ask():
        asked.append(chores.index(force=True))
    w, heard = make_writer(numbers=Recorder(), on_counted=ask)
    now = lib.ids("now")
    for item in now[:3]:
        w.set_watched([item], True)
    assert h.until(lambda: len(asked) == 3)
    assert h.until(lambda: len(popen) == 1, seconds=5) and chores.worker.idle(5)
    assert asked[0] is None and asked[1:] == ["busy", "busy"]
    assert len(popen) == 1 and len(registry.live("indexer")) == 1
    popen[0].end(0)
    chores.close(store=False)


# --- 2. a drag of a row holding watched files keeps its numbers at the drop ---------------------------------------- #
def _hero(seed):
    """The seed's hero show (NOW's top row): its episodes in order, the first two watched."""
    rows = sorted((r for r in seed.library.items() if r["work_id"] == seed.hero_work and r["tier"] == "now"),
                  key=lambda r: (r["ord"], r["id"]))
    assert [r["watched"] for r in rows[:3]] == [1, 1, 0]
    return [r["id"] for r in rows]


def _store_move(seed, ids, tier, before_id=None, after_id=None):
    """The store follows, as the writer's write would (`Store.move`): the block, in its order, before / after the anchor
    (neither: the top of the tier), every one of its items — watched ones too."""
    rows = sorted((r for r in seed.library.items() if r["tier"] == tier and r["id"] not in ids),
                  key=lambda r: (r["ord"], r["id"]))
    block = sorted((r for r in seed.library.items() if r["id"] in ids),
                   key=lambda r: (M.ANALYSED.index(r["tier"]) if r["tier"] in M.ANALYSED else 9, r["ord"], r["id"]))
    at = 0
    anchor = before_id if before_id is not None else after_id
    if anchor is not None:
        at = [r["id"] for r in rows].index(anchor) + (1 if before_id is None else 0)
    lo = rows[at - 1]["ord"] if at else (rows[0]["ord"] if rows else 0) - 1024
    hi = rows[at]["ord"] if at < len(rows) else lo + 1024 * (len(block) + 1)
    step = (hi - lo) / (len(block) + 1)
    seed.library.commit(items=[{"id": r["id"], "tier": tier, "ord": lo + step * (k + 1)} for k, r in enumerate(block)],
                        order=True)


def _loaded(seed, plan_file):
    numbers = M.Numbers(seed.opener, seed.language, plan_file=plan_file)
    numbers.load()
    assert numbers.idle(60) and numbers.why() is None, numbers.why()
    resyncs = []
    numbers._resync = lambda: resyncs.append(1)         # a fallback to a resync would land here
    seed.opener.check()
    return numbers, resyncs, seed.opener.handle().ids


def _matches_referee(numbers, plan_file, seed):
    referee = _engine_from_scratch(plan_file, seed)
    _v, table = numbers()
    for item, (_k, _c, n_new) in table.items():
        f = referee._f_of.get(item)
        if f is not None and referee._pos[f] is not None:
            assert n_new == referee._n_new[f], item


def _small_plan(tmp_path, language):
    tmp_path.mkdir(parents=True, exist_ok=True)
    seed = window_seed.build(root=str(tmp_path), language=language)
    analysed = _in_order(seed.items)                    # as a Generate since W-1: no watched episode
    plan_file = str(tmp_path / "plan.json.gz")
    write_plan(plan_file, [r["rel_path"] for r in analysed], [r["tier"] for r in analysed], n_words=400,
               language=language)
    return seed, plan_file


def test_W1_a_drag_holding_watched_episodes_and_a_drop_beside_one_keep_their_numbers(tmp_path):
    """The hero show (two watched episodes) dragged under a Goal row: its counted episodes move, its watched ones are
    left out of the block. A Goal row dropped at the very top (before the hero's first episode, watched) lands before
    its first counted episode. A drop after a watched episode lands where the store puts it among what counts. Each
    one: numbers at the drop, no resync, equal to an engine built from scratch over the store's order after it."""
    for language in ("ja", "zh"):
        seed, plan_file = _small_plan(tmp_path / language, language)
        numbers, resyncs, order = _loaded(seed, plan_file)
        hero = _hero(seed)
        goal = sorted((r for r in seed.library.items() if r["tier"] == "goal"), key=lambda r: (r["ord"], r["id"]))

        touched = numbers.after_move(hero, "goal", after_id=goal[3]["id"], order=order)   # watched ids in the block
        assert touched and hero[2] in touched and hero[0] not in touched and resyncs == []
        _store_move(seed, hero, "goal", after_id=goal[3]["id"])
        _matches_referee(numbers, plan_file, seed)

        _store_move(seed, hero, "now")                  # the hero back at NOW's top (another program's move)
        del numbers._resync                             # (the real one, once)
        numbers.resync()
        assert numbers.idle(30) and numbers.why() is None
        numbers._resync = lambda: resyncs.append(1)

        mover = goal[-1]["id"]
        touched = numbers.after_move([mover], "now", before_id=hero[0], order=order)       # anchor watched: before
        assert touched and mover in touched and resyncs == []
        _store_move(seed, [mover], "now", before_id=hero[0])
        _matches_referee(numbers, plan_file, seed)

        mover = goal[-2]["id"]
        touched = numbers.after_move([mover], "now", after_id=hero[1], order=order)        # anchor watched: after
        assert touched and mover in touched and resyncs == []
        _store_move(seed, [mover], "now", after_id=hero[1])
        _matches_referee(numbers, plan_file, seed)

        assert numbers.after_move(hero[:2], "goal", order=order) == {} and resyncs == []   # only watched: no number
        numbers.close()


def test_W1_without_the_stores_order_a_drop_beside_a_watched_episode_is_worked_out_again(tmp_path):
    """No `order` (a caller that can't read the tier): the anchor the engine doesn't hold can't be placed — a resync,
    as before, never a guess."""
    seed, plan_file = _small_plan(tmp_path, "ja")
    numbers, resyncs, _order = _loaded(seed, plan_file)
    hero = _hero(seed)
    goal = sorted((r for r in seed.library.items() if r["tier"] == "goal"), key=lambda r: (r["ord"], r["id"]))
    assert numbers.after_move([goal[-1]["id"]], "now", before_id=hero[0]) == {}
    assert resyncs == [1]
    numbers.close()


def test_W1_the_numbers_follow_a_drop_with_watched_episodes_within_50_ms_on_20000_files(big):
    """RP-6 with W-1: the hero show (two watched episodes) dragged around 20,000 files, and drops before its watched
    first episode — the numbers at the drop within 50 ms (median), never a resync. The bound is the timed run's
    (`SURASURA_STORE_BENCH=1`, under the `timed` lock); otherwise the same drops, checked for their answers alone."""
    seed, _analysed, plan_file, _per_file = big
    numbers, resyncs, order = _loaded(seed, plan_file)
    hero = _hero(seed)
    rnd = random.Random(5)
    times = []
    for k in range(9):
        rows = {t: sorted((r for r in seed.library.items() if r["tier"] == t), key=lambda r: (r["ord"], r["id"]))
                for t in M.ANALYSED}
        if k % 3 == 0:                                  # the hero show into Goal, its watched episodes with it
            args = (hero, "goal"), {"after_id": rnd.choice([r for r in rows["goal"] if r["id"] not in hero])["id"]}
        elif k % 3 == 1:                                # ... and back to the top of NOW
            args = (hero, "now"), {"before_id": rows["now"][0]["id"]}
        else:                                           # a Goal row to the very top: before the watched first episode
            mover = rnd.choice([r for r in rows["goal"] if r["id"] not in hero])["id"]
            args = ([mover], "now"), {"before_id": hero[0]}
        start = time.perf_counter()
        touched = numbers.after_move(*args[0], order=order, **args[1])
        times.append((time.perf_counter() - start) * 1000)
        assert touched and resyncs == []
        _store_move(seed, *args[0], **args[1])
    times.sort()
    print(f"after_move with watched files at 20,000 files: median {times[len(times) // 2]:.1f} ms, max {times[-1]:.1f} ms")
    _matches_referee(numbers, plan_file, seed)
    if BENCH:
        assert times[len(times) // 2] <= 50, times
    numbers.close()
