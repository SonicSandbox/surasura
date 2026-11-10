"""Stress (opt-in: `python run_tests.py --stress`): many writers on one library store at once — threads of this
process (the window, its workers) and child processes (the command line, Connect) — each moving its own items next to
its own anchors, many times. What must hold whatever the interleaving: nothing lost and nothing twice (each tier holds
exactly the items it held), no write undone by another's (each writer's own items and anchors, read in the final
order, stand exactly as its own moves alone, replayed one after another, put them — another writer only ever moves
its own items next to its own anchors, so it can never reorder these), and no writer ever errs. No timing is asserted.

Real Japanese and Chinese show names (tests/Test Resources), a migrated library under the test's own root."""
import json
import os
import random
import subprocess
import sys
import threading

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, roots, subprocess_env

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MOVES = 60                      # each writer's moves

_CHILD = r"""
import json, random, sys
from app import library_store as ls
lang, data, uf, plan, seed, n = sys.argv[1:7]
mine, anchors = json.loads(plan)
rnd = random.Random(int(seed))
made = []
s = ls.open_store(lang, data, uf)
for _ in range(int(n)):
    item, anchor, side = rnd.choice(mine), rnd.choice(anchors), rnd.choice(("before", "after"))
    s.move([item], "soon", **{side + "_id": anchor})
    made.append([item, anchor, side])
s.close()
print(json.dumps(made))
"""


def _moves(store, mine, anchors, rnd, n, made):
    for _ in range(n):
        item, anchor, side = rnd.choice(mine), rnd.choice(anchors), rnd.choice(("before", "after"))
        store.move([item], "soon", **{side + "_id": anchor})
        made.append([item, anchor, side])


def _replayed(order, made):
    """`order` (a writer's own ids, as the tier held them before) after its moves, one at a time, as `Store.move`
    places one item: taken out, then put right before or right after its anchor."""
    order = list(order)
    for item, anchor, side in made:
        order.remove(item)
        at = order.index(anchor)
        order.insert(at if side == "before" else at + 1, item)
    return order


@pytest.mark.parametrize("language", LANGUAGES)
def test_threads_and_programs_moving_at_once_lose_nothing_and_undo_no_one(language):
    store = migrated(language, shows=6, episodes=5)
    data_dir, user_files_dir = roots(language)
    before = {tier: sorted(store.ids(tier)) for tier in ("now", "soon", "goal")}
    soon = store.ids("soon")
    writers = 5                                         # three threads, two programs
    per = len(soon) // writers
    plans = [(soon[k * per:k * per + per - 2], soon[k * per + per - 2:k * per + per]) for k in range(writers)]
    seed = random.randrange(1 << 30)
    children = [subprocess.Popen([sys.executable, "-c", _CHILD, language, data_dir, user_files_dir,
                                  json.dumps(plans[k]), str(seed + k), str(MOVES)],
                                 cwd=REPO, env=subprocess_env(), stdout=subprocess.PIPE, text=True)
                for k in (3, 4)]
    made, errors = [[] for _ in range(3)], []

    def thread(k):
        try:
            s = ls.open_store(language, data_dir, user_files_dir)
            try:
                _moves(s, *plans[k], random.Random(seed + k), MOVES, made[k])
            finally:
                s.close()
        except Exception as exc:                        # a writer that erred: named below
            errors.append(repr(exc))
    threads = [threading.Thread(target=thread, args=(k,), name=f"writer-{k}") for k in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for child in children:
        out, _ = child.communicate(timeout=300)
        assert child.returncode == 0, f"a writing program failed (seed {seed})"
        made.append(json.loads(out.strip().splitlines()[-1]))
    assert errors == [], f"seed {seed}: {errors}"
    after = {tier: sorted(store.ids(tier)) for tier in ("now", "soon", "goal")}
    assert after == before, f"seed {seed}: an item lost, doubled or moved to another tier"
    order = store.ids("soon")
    assert len(order) == len(set(order))
    for k, (mine, anchors) in enumerate(plans):
        own = set(mine) | set(anchors)
        assert [i for i in order if i in own] == _replayed([i for i in soon if i in own], made[k]), \
            f"seed {seed}: writer {k}'s moves don't stand as it made them (one undone or reordered by another)"
    store.close()


def test_the_replay_is_the_stores_own_rule_for_one_writer_alone(language="ja"):
    """The model the stress test compares with, checked against the store itself with no other writer."""
    store = migrated(language, shows=3, episodes=5)
    soon = store.ids("soon")
    rnd = random.Random(7)
    made = []
    _moves(store, soon[:8], soon[8:11], rnd, 40, made)
    own = set(soon[:11])
    assert [i for i in store.ids("soon") if i in own] == _replayed([i for i in soon if i in own], made)
    store.close()
