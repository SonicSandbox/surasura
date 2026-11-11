"""Stress (opt-in: `python run_tests.py --stress`): the window's writer (`app/services/moves.Writer`) given many drags
while another save holds the store on and off — each drag lands at once, or waits in the move journal and lands when
the store frees. What must hold whatever the timing: every drag lands exactly once and in the order it was given (the
final order is the one the drags make, one after another, on the order before them), nothing is left in the journal,
and the writer says *saved* once per drag. No timing is asserted: every wait is for a condition.

Real Japanese and Chinese show names (tests/Test Resources), a migrated library under the test's own root."""
import random
import threading
import time

import pytest

from app import library_store as ls
from app.qt.strings import MOVE_WORDS as WORDS
from app.services import moves as M
from tests import services_helpers as h
from tests.test_library_store_support import LANGUAGES, migrated, roots
from tests.test_services_moves import Heard, LockHolder, journal, short_lock_wait  # noqa: F401  (a fixture)

DRAGS = 120


def _apply(order, item, anchor):
    """The order after `item` is dragged right before `anchor` (the store's rule for one item)."""
    order = [i for i in order if i != item]
    order.insert(order.index(anchor), item)
    return order


@pytest.mark.parametrize("language", LANGUAGES)
def test_drags_given_while_the_store_comes_and_goes_land_once_each_in_order(language, short_lock_wait):  # noqa: F811
    store = migrated(language, shows=5, episodes=5)
    data_dir, user_files_dir = roots(language)
    heard = Heard()
    writer = M.Writer(ls.StoreOpener(language, data_dir, user_files_dir, role="window"), language,
                      journal_file=M.journal_path(language), retry=0.02, words=WORDS, **heard.kw())
    writer.start()
    seed = random.randrange(1 << 30)
    rnd = random.Random(seed)
    goal = store.ids("goal")
    expected, given = list(goal), []
    stop = threading.Event()

    def busy():                                         # another save, holding the store on and off
        pace = random.Random(seed + 1)
        while not stop.is_set():
            holder = LockHolder(store.db_path)
            stop.wait(pace.uniform(0, 0.15))
            holder.release()
            stop.wait(pace.uniform(0, 0.1))
    other = threading.Thread(target=busy, name="other-save")
    other.start()
    try:
        for n in range(DRAGS):
            item, anchor = rnd.sample(goal, 2)
            if expected[expected.index(anchor) - 1:expected.index(anchor)] == [item]:
                continue                                # already right before it: the store commits nothing
            writer.move([item], "goal", before_id=anchor, label=f"drag {n}")
            given.append(f"drag {n}")
            expected = _apply(expected, item, anchor)
            if rnd.random() < 0.1:
                stop.wait(rnd.uniform(0, 0.05))
    finally:
        stop.set()
        other.join()
    try:
        assert h.until(lambda: writer.pending() == 0 and len(heard.saved) >= len(given) and journal(language) is None,
                       seconds=120), f"seed {seed}: {writer.pending()} still pending"
        labels = [label for _c, label in heard.saved]
        assert labels == given, f"seed {seed}: a drag lost, saved twice or out of order"
        assert store.ids("goal") == expected, f"seed {seed}: the order isn't the one the drags make"
    finally:
        writer.finish(time.monotonic() + 10)
        store.close()
