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
from tests.test_services_moves import (WORDS, Recorder, _engine_from_scratch, _in_order, big,  # noqa: F401
                                       lib, make_writer, write_plan)

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

        touched = numbers.after_move(hero, "goal", after_id=goal[3]["id"], order=order,   # watched ids in the block
                                     aside=_aside(seed))
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

        assert numbers.after_move(hero[:2], "goal", order=order, aside=_aside(seed)) == {}  # only watched: no number
        assert numbers.idle(10) and resyncs == []
        numbers.close()


def test_W1_without_the_stores_order_a_drop_beside_a_watched_episode_is_worked_out_again(tmp_path):
    """No `order` (a caller that can't read the tier): the anchor the engine doesn't hold can't be placed — a resync,
    as before, never a guess."""
    seed, plan_file = _small_plan(tmp_path, "ja")
    numbers, resyncs, _order = _loaded(seed, plan_file)
    hero = _hero(seed)
    goal = sorted((r for r in seed.library.items() if r["tier"] == "goal"), key=lambda r: (r["ord"], r["id"]))
    assert numbers.after_move([goal[-1]["id"]], "now", before_id=hero[0]) == {}
    assert numbers.idle(10) and resyncs == [1]
    numbers.close()


def test_W1_the_numbers_follow_a_drop_with_watched_episodes_within_50_ms_on_20000_files(big):
    """RP-6 with W-1: the hero show (two watched episodes) dragged around 20,000 files, and drops before its watched
    first episode — the numbers at the drop within 50 ms (median), never a resync. The bound is the timed run's
    (`SURASURA_STORE_BENCH=1`, under the `timed` lock); otherwise the same drops, checked for their answers alone."""
    seed, _analysed, plan_file, _per_file = big
    numbers, resyncs, order = _loaded(seed, plan_file)
    aside = _aside(seed)
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
        touched = numbers.after_move(*args[0], order=order, aside=aside, **args[1])
        times.append((time.perf_counter() - start) * 1000)
        assert touched and resyncs == []
        _store_move(seed, *args[0], **args[1])
    times.sort()
    print(f"after_move with watched files at 20,000 files: median {times[len(times) // 2]:.1f} ms, max {times[-1]:.1f} ms")
    _matches_referee(numbers, plan_file, seed)
    if BENCH:
        assert times[len(times) // 2] <= 50, times
    numbers.close()


# --- 3. an undo the store did is never reported refused ------------------------------------------------------------ #
def test_W1_undoing_a_drag_out_of_finished_that_cleared_its_stone_is_not_reported_refused(lib, make_writer):
    """A watched item in Finished, dragged back into NOW: the move clears its stone (Put back's rule) on the move's own
    change. Its Undo puts the item back in Finished, watched — the store undid it, so the writer must never answer
    *can't undo* (the learner would think the drag stuck)."""
    s = lib.store
    item = lib.ids("now")[-1]
    s.set_tier([item], "graduated")
    s.set_watched([item], True)
    s.set_learning_order([item], True)                  # only the stone changes on the way out
    change = s.move([item], "now", after_id=lib.ids("now")[0])
    assert s.item(item)["watched"] == 0 and change.status
    out = s.undo(change)
    assert s.item(item)["tier"] == "graduated" and s.item(item)["watched"] == 1
    assert not M._refused(change, out)
    w, heard, _numbers, _counted = _writer(make_writer)  # the writer's own Undo of the same drag
    w.move([item], "now", after_id=lib.ids("now")[0])
    assert h.until(lambda: len(heard.saved) == 1) and s.item(item)["tier"] == "now"
    w.undo()
    assert h.until(lambda: len(heard.undone) == 1 or heard.notes)
    assert s.item(item)["tier"] == "graduated" and s.item(item)["watched"] == 1
    assert WORDS["cant_undo"] not in heard.notes and len(heard.undone) == 1


def test_W1_undoing_a_drag_out_of_finished_changed_since_is_still_refused(lib):
    """The other side of the same rule: the dragged item moved again since (and its stone set again), so the undo
    restores nothing — that one is refused, as before."""
    s = lib.store
    item = lib.ids("now")[-1]
    s.set_tier([item], "graduated")
    s.set_watched([item], True)
    change = s.move([item], "now", after_id=lib.ids("now")[0])
    s.move([item], "soon")                              # another window moved it since
    s.set_watched([item], True)
    out = s.undo(change)
    assert s.item(item)["tier"] == "soon"
    assert M._refused(change, out)


# --- 4. after a drop, an item the plan doesn't hold resyncs unless the one rule sets it aside -------------------- #
def _aside(seed):
    store = seed.opener.handle()
    return lambda ids: M._set_aside(store, ids)


class _Counting:
    """The tier's order, counted: a drop that can't use it never reads it."""

    def __init__(self, order):
        self.order, self.reads = order, 0

    def __call__(self, tier):
        self.reads += 1
        return self.order(tier)


def test_W1_a_finished_item_or_a_file_added_since_generate_dragged_into_now_still_resyncs(tmp_path):
    """The plan holds neither a Finished item nor a file added since the last Generate: dragged into NOW (alone, or
    with a counted episode) they'll count, so the numbers are worked out again — only a watched episode of a studied
    tier (set aside) leaves the block quietly. New arrivals the same as Finished."""
    for language in ("ja", "zh"):
        seed, plan_file = _small_plan(tmp_path / language, language)
        numbers, resyncs, order = _loaded(seed, plan_file)
        aside = _aside(seed)
        rows = seed.library.items()
        fin = sorted((r for r in rows if r["tier"] == "graduated"), key=lambda r: (r["ord"], r["id"]))
        arr = [r for r in rows if r["tier"] == "arrivals"]
        now = [r["id"] for r in _in_order(rows) if r["tier"] == "now"]
        hero = _hero(seed)
        added = dict(next(r for r in rows if r["id"] == now[5]))    # a NOW file that came in after the Generate
        added.update(id=max(r["id"] for r in rows) + 1, rel_path=added["rel_path"] + ".new.srt", ord=added["ord"] + 1)
        seed.library.commit(items=[added], order=True)

        assert numbers.after_move([fin[0]["id"]], "now", after_id=now[2], order=order, aside=aside) == {}
        assert numbers.idle(10) and resyncs == [1]
        assert numbers.after_move([fin[1]["id"], now[0]], "now", after_id=now[3], order=order, aside=aside) == {}
        assert numbers.idle(10) and resyncs == [1, 1]
        assert numbers.after_move([arr[0]["id"]], "now", after_id=now[2], order=order, aside=aside) == {}
        assert numbers.idle(10) and resyncs == [1, 1, 1]
        assert numbers.after_move([added["id"]], "soon", order=order, aside=aside) == {}
        assert numbers.idle(10) and resyncs == [1, 1, 1, 1]
        assert numbers.after_move(hero[:2] + [added["id"]], "goal", order=order, aside=aside) == {}
        assert numbers.idle(10) and resyncs == [1, 1, 1, 1, 1]               # the watched ones alone are set aside; the new file isn't
        assert numbers.after_move(hero[:2], "goal", order=order, aside=aside) == {}
        assert numbers.idle(10) and resyncs == [1, 1, 1, 1, 1]               # only watched: nothing counts moved, no resync
        numbers.close()


def test_W1_after_a_drop_the_tiers_order_is_read_only_when_the_anchor_is_needed(tmp_path):
    """The store's order is read for an anchor the engine doesn't hold, and only when the drop will be followed: never
    for a drop into Finished, a block of watched episodes alone, or a block that resyncs anyway."""
    seed, plan_file = _small_plan(tmp_path, "ja")
    numbers, resyncs, order = _loaded(seed, plan_file)
    aside, counting = _aside(seed), _Counting(order)
    hero = _hero(seed)
    fin = sorted((r for r in seed.library.items() if r["tier"] == "graduated"), key=lambda r: (r["ord"], r["id"]))
    goal = sorted((r for r in seed.library.items() if r["tier"] == "goal"), key=lambda r: (r["ord"], r["id"]))
    assert numbers.after_move([goal[-1]["id"]], "graduated", after_id=fin[0]["id"], order=counting, aside=aside) == {}
    assert numbers.after_move(hero[:2], "now", before_id=hero[2], order=counting, aside=aside) == {}
    assert numbers.after_move([fin[0]["id"]], "now", after_id=hero[1], order=counting, aside=aside) == {}
    assert counting.reads == 0 and resyncs == [1, 1]
    touched = numbers.after_move([goal[-1]["id"]], "now", after_id=hero[1], order=counting, aside=aside)
    assert touched and counting.reads == 1 and resyncs == [1, 1]
    numbers.close()


def test_W1_the_numbers_verdict_signs_the_watched_episodes_as_the_host_does(lib, tmp_path, monkeypatch):
    """`plan_check` (the window's *N new* staleness) builds the run signature's parts as the replan host does: a watched
    episode is in the "reference" part while it is set aside, and the part is gone with none — so the window's numbers
    and the cards agree on when a Generate must come first."""
    from app import analyzer, plan_engine, settings_manager
    path = str(tmp_path / "plan.json.gz")
    rels = [e["physical_path"] for t in ("now", "soon", "goal") for _i, e, _a in lib.store.ordered(t)]
    write_plan(path, rels, ["now"] * len(rels), language=lib.language, n_words=50)
    plan = plan_engine.load(path)
    seen = []
    monkeypatch.setattr(plan_engine, "check", lambda plan_, language, engine, stamp, parts, epoch: seen.append(parts))
    check = M.plan_check(lib.language, settings_manager.load_settings())
    check(plan, lib.store)
    episode = lib.ids("now")[0]
    lib.store.set_watched([episode])
    check(plan, lib.store)
    want = analyzer.aside_files(lib.language, lib.store.schedule(with_aside=True))
    assert "reference" not in seen[0] and len(want) == 1
    assert seen[1]["reference"] == analyzer.run_signature_parts(lib.language, [], analyzer.parse_analysis_args(
        ["--language", lib.language]), want)["reference"]
