"""W4.1 (the intake stutter, option A): the window's numbers read the order as ids alone, once an update.

What a wrong answer would cost a learner: after a Generate, every new file that comes in makes the numbers worker read
the library's order again. Read through every item's entry (20,000 JSON decodes, three times over), it held the
window's interpreter for about 3 s, and Current stuttered while it scrolled (p95 17-19 ms against a 3.2 ms bar). Read
any other way, the order must still be the store's one rule: a watched episode while *Keep studying watched episodes*
is off, or a video still waiting for its subtitle, never counts, or *N new* would be wrong on every row below it.

Runs on a real `library_store` (a small migrated library; Japanese and Chinese show names from tests/Test Resources),
with a plan file shaped like a Generate's.
"""
import os

import pytest

from app import library_store as ls
from app.services import moves as M
from tests.test_library_store_support import LANGUAGES, migrated, names, roots
from tests.test_library_store_waiting import _video
from tests.test_library_store_sources import _source_root
from tests.test_services_moves import write_plan


def _old_order(store):
    """The order as the numbers read it before W4.1 (the referee): every analysed tier's items through their entries,
    kept when the schedule lists their path."""
    schedule = store.schedule()
    out = []
    for tier in M.ANALYSED:
        counted = {ls.path_key(e["physical_path"]) for e in schedule[ls.TIERS[tier][0]]}
        out += [(i, tier) for i, entry, _a in store.ordered(tier) if ls.path_key(entry["physical_path"]) in counted]
    return out


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_scheduled_ids_are_the_schedules_rows_with_watched_and_waiting_items_left_out(language):
    """`Store.scheduled_ids` lists what `schedule` lists, in its order, and nothing else: a watched episode drops out
    while `keep_watched` is off and comes back when it's on; a video waiting for its subtitle, moved into 6+ Months,
    never counts. `item_keys` holds every item (New arrivals and Finished too) under its path's key."""
    store = migrated(language)
    src = _source_root()
    with store:
        now, goal = store.ids("now"), store.ids("goal")
        store.set_watched([now[1]])
        root = store.add_source(src)
        waiting = store.take_in(root, [_video(src, names(language)[71], "ep1.mkv", "v1-a")]).added
        store.move(waiting, "goal", after_id=goal[-1])
        store.move([goal[0]], "graduated")
        ids = store.scheduled_ids()
        assert ids == _old_order(store)
        assert now[1] not in {i for i, _t in ids} and waiting[0] not in {i for i, _t in ids}
        assert [t for _i, t in ids] == sorted((t for _i, t in ids), key=M.ANALYSED.index)
        store.set_library_options(keep_watched=1)
        ids = store.scheduled_ids()
        assert ids == _old_order(store) and now[1] in {i for i, _t in ids}

        keys = store.item_keys()
        rows = store.conn.execute("SELECT id, rel_path FROM items").fetchall()
        assert keys == {ls.path_key(rel): i for i, rel in rows}
        assert keys[ls.path_key(store.item(goal[0])["rel_path"])] == goal[0]           # Finished is held too


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_numbers_read_no_entry_and_the_order_once_a_load_and_once_a_resync(language, monkeypatch):
    """A load (a new plan: an arrival's own Generate) and a resync (an arrival, a move) never parse an item's entry
    (`Store.ordered`), and read the order once each — the staleness check and the engine share it. The figures are
    what the old reading gave: *N new* on every row follows the order the referee reads."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    with store:
        store.set_watched([store.ids("now")[1]])               # W-1: out of the order (keep_watched off)
        order = _old_order(store)
        rel = {i: store.item(i)["rel_path"] for i, _t in order}
    plan_file = os.path.join(user_files_dir, "plan.json.gz")
    write_plan(plan_file, [rel[i] for i, _t in order], [t for _i, t in order], language=language)

    calls = {"ordered": 0, "scheduled_ids": 0, "item_keys": 0}

    def counting(name):
        real = getattr(ls.Store, name)

        def call(self, *a, **kw):
            calls[name] += 1
            return real(self, *a, **kw)
        return call
    for name in calls:
        monkeypatch.setattr(ls.Store, name, counting(name))

    opener = ls.StoreOpener(language, data_dir, user_files_dir, role="window")
    numbers = M.Numbers(opener, language, plan_file=plan_file)
    try:
        numbers.load()
        assert numbers.idle(60) and numbers.why() is None, numbers.why()
        assert calls == {"ordered": 0, "scheduled_ids": 1, "item_keys": 1}
        eng = numbers._engine
        assert [(eng._ids[f], M.ANALYSED[eng._tier[f]]) for f in eng._order] == order

        outside = ls.open_store(language, data_dir, user_files_dir)   # another program's move: the order differs
        try:
            goal = outside.ids("goal")
            outside.move([goal[-1]], "goal", before_id=goal[0])
            moved = _old_order(outside)
            assert moved != order
        finally:
            outside.close()
        calls.update(ordered=0, scheduled_ids=0, item_keys=0)
        v = numbers.version
        numbers.resync()
        assert numbers.idle(60) and numbers.version == v + 1
        assert calls == {"ordered": 0, "scheduled_ids": 1, "item_keys": 0}
        assert [(eng._ids[f], M.ANALYSED[eng._tier[f]]) for f in eng._order] == moved
    finally:
        numbers.close()
