"""The library reader's move hook (`LibraryReader.subscribe_moves`, `_moved`): what counts as a move of the order or the
pins, at the edges its end-to-end test leaves open — a store made again (a Repair, a restore) whose version numbers
happen to match, and a version read that fails.

What a wrong answer would cost a learner: after a Repair their Anki order is never brought back in line with the
library (the re-order host never hears of it), or a busy store read makes the host and the journey keeper start work
for a move nobody made. The handle is a stand-in giving the store's `versions()`.
"""
import sqlite3

from app.services.library_reader import LibraryReader
from tests.fixtures import window_seed


class _Handle:
    def __init__(self, epoch, order, pins):
        self.now = {"epoch": epoch, "order_version": order, "pins_version": pins}
        self.fails = False

    def versions(self):
        if self.fails:
            raise sqlite3.OperationalError("database is locked")
        return dict(self.now)


def _reader():
    seed = window_seed.build()
    reader = LibraryReader(seed.opener, language="ja", numbers=seed.numbers, mining=seed.mining, poll=0.02)
    heard = []
    reader.subscribe_moves(lambda language, versions: heard.append((language, versions.get("epoch"))))
    return reader, heard


def test_a_store_made_again_with_the_same_version_numbers_is_a_move():
    """A Repair makes the store again (a new epoch): its order and pins versions may start over at the very numbers
    the window last saw — that is still a new order, told once."""
    reader, heard = _reader()
    h = _Handle("epoch-1", 7, 2)
    reader._moved(h)
    assert heard == []                                   # the first look only learns the versions
    h.now["epoch"] = "epoch-2"
    reader._moved(h)
    reader._moved(h)
    assert heard == [("ja", "epoch-2")]


def test_a_version_read_that_fails_tells_nothing_and_the_next_read_tells_only_a_real_move():
    """A busy store (another program writing) makes `versions()` fail: nothing is told, and when the read works again
    with the versions unchanged nothing is told either; a real move after it is told once."""
    reader, heard = _reader()
    h = _Handle("epoch-1", 7, 2)
    reader._moved(h)
    h.fails = True
    reader._moved(h)
    h.fails = False
    reader._moved(h)
    assert heard == [], "a failed read was told as a move"
    h.now["order_version"] = 8
    reader._moved(h)
    assert heard == [("ja", "epoch-1")]


# --- M4.1 B3: a few moved ids put in place, never a full sort ------------------------------------------------------ #
def test_M41_B3_tiers_kept_in_place_over_random_moves_equal_a_full_sort_at_20000_files():
    """A menu's move into Goal (~16,000 items at 20,000 files) sorted the whole tier again: the few ids are now taken
    out and put back in place. Wrong, a row would sit in a tier it left, twice, or out of the store's `(ord, id)` order —
    or a row's kept place (`_pos`, where a change in place is swapped in) would point at another row. Random moves,
    changes in place, removals, arrivals and a big batch (the full sort), each checked against `_by_tier`."""
    import random
    from app.services import view_rows
    rng = random.Random(41)
    tiers = ("arrivals", "now", "soon", "goal", "graduated")
    weights = (1, 1, 3, 16, 3)
    items = {i: {"id": i, "tier": rng.choices(tiers, weights)[0], "ord": rng.choice([None, float(rng.randrange(5000))]),
                 "watched": 0} for i in range(1, 20001)}
    reader = LibraryReader(None, language="ja")
    reader._merge({"full": True, "items": list(items.values()), "works": [], "gone": [], "version": 1, "epoch": "e"})
    reader._sorted_tiers()
    next_id, version = 20001, 1
    for step in range(120):
        changes, gone = [], []
        for _ in range(200 if step % 40 == 39 else rng.randint(1, 6)):
            i = rng.choice(list(reader._items))
            kind = rng.random()
            if kind < 0.5:                                   # a move: another tier, or another place in its own
                changes.append(dict(reader._items[i], tier=rng.choices(tiers, weights)[0],
                                    ord=float(rng.randrange(5000)) + rng.random()))
            elif kind < 0.75:                                # a change in place (watched): swapped in, no sort
                changes.append(dict(reader._items[i], watched=1))
            elif kind < 0.9:
                gone.append(("item", i))
            else:                                            # an arrival
                changes.append({"id": next_id, "tier": rng.choice(tiers), "ord": float(rng.randrange(5000)),
                                "watched": 0})
                next_id += 1
        gone_ids = {g[1] for g in gone}
        changes = [c for c in changes if c["id"] not in gone_ids]
        version += 1
        reader._merge({"full": False, "items": changes, "works": [], "gone": gone, "version": version, "epoch": "e"})
        got = reader._sorted_tiers()
        want = view_rows._by_tier(reader._items)
        for t in tiers:
            assert [r["id"] for r in got.get(t, [])] == [r["id"] for r in want[t]], (step, t)
            assert all(a is b for a, b in zip(got.get(t, []), want[t])), (step, t)    # the newest dicts, never stale
            assert all(reader._pos[r["id"]] == (t, k) for k, r in enumerate(got.get(t, []))), (step, t)


def test_M41_B3_a_few_ids_put_in_place_match_a_full_sort_over_small_random_libraries_with_ties_and_skipped_sorts():
    """The 20,000-file test above rarely meets what a small library meets: ties (`None` and 0.0 sort as one `ord`, the
    id decides), the same id moved twice before the next sort, a tier emptied and filled again, and several feeds merged
    between two sorts (the reader builds only when it looks). 300 libraries of 1–120 items, each sort checked against
    `_by_tier`: the ids, the newest objects and `_pos`."""
    import random
    from app.services import view_rows
    tiers = ("now", "soon", "goal", "graduated", "arrivals")
    rng = random.Random(41)
    for trial in range(300):
        reader = LibraryReader(None, language="ja")
        n = rng.randint(1, 120)
        items = [{"id": i, "tier": rng.choice(tiers), "ord": rng.choice([None, 0.0, float(rng.randint(0, 50))])}
                 for i in range(n)]
        reader._merge({"full": True, "items": items, "works": [], "gone": [], "options": {}, "version": 0,
                       "epoch": 1})
        reader._sorted_tiers()
        next_id = n
        for step in range(rng.randint(1, 8)):
            changes, gone = [], []
            for _ in range(rng.randint(0, 70)):
                kind, ids = rng.random(), list(reader._items)
                if kind < 0.55 and ids:                      # a move: its tier and / or its place
                    x = dict(reader._items[rng.choice(ids)])
                    if rng.random() < 0.5:
                        x["tier"] = rng.choice(tiers)
                    x["ord"] = rng.choice([None, 0.0, float(rng.randint(0, 50)), x.get("ord")])
                    changes.append(x)
                elif kind < 0.75 and ids:                    # the same place, a new object
                    changes.append(dict(reader._items[rng.choice(ids)]))
                elif kind < 0.9:                             # an arrival
                    changes.append({"id": next_id, "tier": rng.choice(tiers), "ord": float(rng.randint(0, 50))})
                    next_id += 1
                elif ids:
                    gone.append(("item", rng.choice(ids)))
            last = {x["id"]: x for x in changes}             # a feed holds one record per id, the last (the store's)
            reader._merge({"full": False, "items": list(last.values()), "works": [], "gone": gone, "options": {},
                           "version": step + 1, "epoch": 1})
            if rng.random() < 0.7:                           # else the next feed merges before any sort
                got = reader._sorted_tiers()
                want = view_rows._by_tier(reader._items)
                for t in tiers:
                    assert [r["id"] for r in got.get(t, ())] == [r["id"] for r in want.get(t, ())], (trial, step, t)
                    for k, r in enumerate(got.get(t, ())):
                        assert r is reader._items[r["id"]], (trial, step, t, "stale object")
                        assert reader._pos[r["id"]] == (t, k), (trial, step, t, "pos")
