"""The window's library reader during a drag, and the numbers at a drop (W3.1a; the
window's spec 06 E6): `app/services/library_reader.py`'s `hold()` / `release()` / `subscribe_gone`, and a numbers
version that rebuilds only the rows it changed.

What a wrong answer would cost a learner:
  * a row jumping under the hand mid-drag because a hato drop or a sync landed (E6), or that change lost at the drop;
  * a drag of an item another program removed meanwhile, dropped onto nothing;
  * every Current row rebuilt and repainted because one drop moved *N new* on three rows.

Headless on the window's seed through the stand-in store (Japanese titles).
"""
import threading

from app.services import library_reader
from tests.fixtures import window_seed
from tests.test_library_reader import _collect, _reader, _wait


def _started(seed, numbers=None):
    reader = _reader(seed) if numbers is None else library_reader.LibraryReader(
        seed.opener, language=seed.language, numbers=numbers, mining=seed.mining, poll=0.02)
    views, _got = _collect(reader)
    reader.start()
    assert _wait(lambda: views and views[-1][1].state == "full")
    return reader, views


def _quiet(reader, views, settle=0.15):
    """The reader has looked a few times since the last view: nothing more is coming on its own."""
    n = len(views)
    reads = reader.reads
    _wait(lambda: False, settle)
    return len(views) == n, reads


def test_E6_a_change_during_a_drag_is_merged_but_never_shown_until_the_drop(tmp_path):
    seed = window_seed.build()
    reader, views = _started(seed)
    try:
        before = len(views)
        row = views[-1][1].rows[3]
        reader.hold()
        seed.library.commit(items=[{"id": row.episodes[0].id, "watched": 1}])        # a sync lands mid-drag
        assert _wait(lambda: reader._held_dirty)                                     # read and merged …
        quiet, _ = _quiet(reader, views)
        assert quiet and len(views) == before                                        # … never built or shown
        assert reader._items[row.episodes[0].id]["watched"] == 1
        reader.release()                                                             # the drop
        assert _wait(lambda: len(views) == before + 1)
        new = views[-1][1].rows[3]
        assert new.key == row.key and new.episodes[0].watched
        quiet, _ = _quiet(reader, views)
        assert quiet and len(views) == before + 1                                    # built and shown once
    finally:
        reader.stop()


def test_AD1_a_quiet_look_later_in_a_long_drag_never_drops_what_came_in(monkeypatch):
    """A drag held past CARDS_ALL_S: a later held look that finds nothing new (every item's cards asked again, or a
    checkpoint moving data_version) must not forget the change that came in earlier — the drop builds it."""
    seed = window_seed.build()
    reader, views = _started(seed)
    try:
        before = len(views)
        row = views[-1][1].rows[3]
        reader.hold()
        seed.library.commit(items=[{"id": row.episodes[0].id, "watched": 1}])        # a sync lands mid-drag
        assert _wait(lambda: reader._held_dirty)
        reads = reader.reads
        monkeypatch.setattr(library_reader, "CARDS_ALL_S", 0.0)                      # 2 s later: every card asked
        with seed.library._lock:
            seed.library._data_version += 1                                         # and a checkpoint, nothing new
        reader.refresh()
        assert _wait(lambda: reader.reads > reads)                                   # a quiet held look …
        _wait(lambda: False, 0.1)
        assert len(views) == before                                                  # … found nothing new
        reader.release()                                                             # the drop
        assert _wait(lambda: len(views) == before + 1)
        new = views[-1][1].rows[3]
        assert new.key == row.key and new.episodes[0].watched
    finally:
        reader.stop()


def test_a_drag_with_nothing_coming_in_publishes_nothing_at_its_drop():
    seed = window_seed.build()
    reader, views = _started(seed)
    try:
        before = len(views)
        reader.hold()
        _wait(lambda: False, 0.1)
        reader.release()
        quiet, _ = _quiet(reader, views)
        assert quiet and len(views) == before
    finally:
        reader.stop()


def test_E6_a_numbers_change_during_a_drag_waits_for_the_drop_too():
    seed = window_seed.build()
    reader, views = _started(seed)
    try:
        before = len(views)
        row = views[-1][1].rows[2]
        reader.hold()
        seed.numbers.set(row.episodes[0].id, (1, 2, 99))
        reader.refresh()
        assert _wait(lambda: reader._held_dirty)
        assert len(views) == before
        reader.release()
        assert _wait(lambda: len(views) == before + 1)
        assert views[-1][1].rows[2].n_new >= 99
    finally:
        reader.stop()


def test_E6_an_item_removed_during_a_drag_is_told_at_once():
    """The drag controller lets go of a dragged item another program removed (*That item was removed*)."""
    seed = window_seed.build()
    reader, views = _started(seed)
    told = []
    reader.subscribe_gone(lambda ids: told.append((threading.get_ident(), list(ids))))
    try:
        row = views[-1][1].rows[4]
        gone = row.episodes[0].id
        seed.library.commit(gone=[("item", row.episodes[-1].id)])                   # not held: not told
        assert _wait(lambda: any(row.episodes[-1].id not in [e.id for e in r.episodes] for r in views[-1][1].rows
                                 if r.key == row.key))
        assert told == []
        reader.hold()
        seed.library.commit(gone=[("item", gone)])
        assert _wait(lambda: told)
        assert told[0][1] == [gone] and told[0][0] != threading.get_ident()
        reader.release()
    finally:
        reader.stop()


def test_E6_an_item_gone_in_a_rebuilt_library_during_a_drag_is_told_too():
    """A full read (the library rebuilt: a new epoch) carries no tombstones: what left is what the copy no longer has."""
    seed = window_seed.build()
    reader, views = _started(seed)
    told = []
    reader.subscribe_gone(told.append)
    try:
        gone = views[-1][1].rows[4].episodes[0].id
        reader.hold()
        seed.library.commit(gone=[("item", gone)], new_epoch=True)
        assert _wait(lambda: told)
        assert told == [[gone]]
        reader.release()
    finally:
        reader.stop()


def test_a_listener_that_raises_never_stops_the_reader_during_a_drag():
    seed = window_seed.build()
    reader, views = _started(seed)
    reader.subscribe_gone(lambda ids: 1 / 0)
    try:
        row = views[-1][1].rows[4]
        reader.hold()
        seed.library.commit(gone=[("item", row.episodes[0].id)])
        assert _wait(lambda: reader._held_dirty)
        before = len(views)
        reader.release()
        assert _wait(lambda: len(views) == before + 1)
    finally:
        reader.stop()


class _Changing:
    """A numbers provider that says which items each version changed (`moves.Numbers.changed`'s shape)."""

    def __init__(self, table):
        self.table, self.version, self._changed = dict(table), 1, {}
        self.asked = []

    def __call__(self):
        return self.version, self.table

    def set(self, item_id, value):
        self.table = dict(self.table)
        self.table[item_id] = value
        self.version += 1
        self._changed[self.version] = {item_id}

    def changed(self, since):
        self.asked.append(since)
        out = set()
        for v in range(since + 1, self.version + 1):
            out |= self._changed.get(v, set())
        return out


def test_a_numbers_version_rebuilds_only_the_rows_holding_what_it_changed():
    """A drop moves *N new* on a few rows; the rest are the same objects (the window repaints nothing for
    them). A provider that can't say (the seed's) rebuilds every row, as before."""
    seed = window_seed.build()
    numbers = _Changing(seed.numbers.table)
    reader, views = _started(seed, numbers=numbers)
    try:
        first = views[-1][1]
        target = first.rows[5]
        numbers.set(target.episodes[0].id, (1, 2, 77))
        reader.refresh()
        assert _wait(lambda: views[-1][1] is not first)
        second = views[-1][1]
        assert numbers.asked and numbers.asked[-1] == 1                              # since the version it last built
        changed = [i for i, (a, b) in enumerate(zip(first.rows, second.rows)) if a is not b]
        assert changed == [5] and second.rows[5].n_new != target.n_new
    finally:
        reader.stop()
    plain = window_seed.build()
    reader, views = _started(plain)
    try:
        first = views[-1][1]
        plain.numbers.set(first.rows[5].episodes[0].id, (1, 2, 77))
        reader.refresh()
        assert _wait(lambda: views[-1][1] is not first)
        assert all(a is not b for a, b in zip(first.rows, views[-1][1].rows))
    finally:
        reader.stop()


def test_numbers_that_change_during_a_drag_rebuild_only_their_rows_at_the_drop():
    seed = window_seed.build()
    numbers = _Changing(seed.numbers.table)
    reader, views = _started(seed, numbers=numbers)
    try:
        first = views[-1][1]
        reader.hold()
        numbers.set(first.rows[3].episodes[0].id, (1, 2, 70))
        reader.refresh()
        assert _wait(lambda: reader._held_dirty)
        numbers.set(first.rows[6].episodes[0].id, (1, 2, 71))
        reader.refresh()
        _wait(lambda: False, 0.1)
        reader.release()
        assert _wait(lambda: views[-1][1] is not first)
        changed = [i for i, (a, b) in enumerate(zip(first.rows, views[-1][1].rows)) if a is not b]
        assert changed == [3, 6] and numbers.asked[-1] == 1
    finally:
        reader.stop()


def test_a_provider_whose_changed_fails_rebuilds_every_row():
    seed = window_seed.build()
    numbers = _Changing(seed.numbers.table)
    numbers.changed = lambda since: 1 / 0
    reader, views = _started(seed, numbers=numbers)
    try:
        first = views[-1][1]
        numbers.set(first.rows[5].episodes[0].id, (1, 2, 77))
        reader.refresh()
        assert _wait(lambda: views[-1][1] is not first)
        assert all(a is not b for a, b in zip(first.rows, views[-1][1].rows))
    finally:
        reader.stop()


assert library_reader.LibraryReader.hold and library_reader.LibraryReader.subscribe_gone     # the hooks the drag wires


def test_AD2_4_republish_shows_the_stores_view_again_though_nothing_changed(tmp_path):
    """Round 2 (AD2-4): once every write landed, the window asks the reader for the store's own view again — where the
    store placed a row otherwise than the window drew it, the window's guess never outlives the settle."""
    seed = window_seed.build()
    reader, views = _started(seed)
    try:
        quiet, _ = _quiet(reader, views)
        assert quiet
        before = len(views)
        reader.republish()
        assert _wait(lambda: len(views) == before + 1)                               # built and shown once more
        assert [r.key for r in views[-1][1].rows] == [r.key for r in views[-2][1].rows]
        quiet, _ = _quiet(reader, views)
        assert quiet and len(views) == before + 1
    finally:
        reader.stop()


def test_M41_B1_republish_with_nothing_new_publishes_the_last_view_again_and_builds_nothing(tmp_path):
    """The settle's ask once the reader has built since the last write: the same rows built again held Python's lock
    under the window for 6–23 ms at 20,000 files. The last view, the same object, goes out once more (the window's
    diff of an unchanged page costs nothing); a change since is built, once."""
    seed = window_seed.build()
    reader, views = _started(seed)
    try:
        quiet, _ = _quiet(reader, views)
        assert quiet
        before, builds = len(views), reader.builds
        reader.republish()
        assert _wait(lambda: len(views) == before + 1)
        assert views[-1][1] is views[-2][1] and reader.builds == builds
        row = views[-1][1].rows[3]
        reader.hold()                                                                # a drag, and a sync meanwhile
        reader.republish()
        seed.library.commit(items=[{"id": row.episodes[0].id, "watched": 1}])
        assert _wait(lambda: reader._held_dirty)
        reader.release()
        assert _wait(lambda: len(views) == before + 2)
        assert views[-1][1].rows[3].episodes[0].watched and reader.builds == builds + 1
        quiet, _ = _quiet(reader, views)
        assert quiet and len(views) == before + 2                                    # once, not again for the ask
    finally:
        reader.stop()
