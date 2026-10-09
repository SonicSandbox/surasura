"""The window's library reader (W2.2; the window's spec 04 §4.1, 02 §2.1, §2.4): `app/services/library_reader.py` reads
the store on a thread of its own, follows the change feed, and builds the view there — the window's thread never reads.

Tested headless on the stand-in store: it publishes once per change and never when nothing moved; an outside commit (a
hato drop) shows within a fraction of a second; the first screen's cache is used only when its key matches; the
store's modes give their states; a failed read keeps the last view, marked busy, then recovers.
"""
import json
import os
import threading
import time

from app.services import library_reader, view_rows
from tests.fixtures import window_seed


def _collect(reader):
    views = []
    got = threading.Event()

    def cb(view):
        views.append((threading.get_ident(), view))
        got.set()
    reader.subscribe(cb)
    return views, got


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def _reader(seed, **kw):
    return library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                        mining=seed.mining, poll=0.02, **kw)


def test_the_reader_reads_on_its_own_thread_and_builds_the_view_there():
    seed = window_seed.build()
    reader = _reader(seed)
    views, _got = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "full")
        tid, view = views[-1]
        assert tid != threading.get_ident()
        assert view.rows and view.rows[0].work_id == seed.hero_work
    finally:
        reader.stop()


def test_nothing_moved_means_no_new_read_and_no_new_view():
    """The poll is one `data_version()` (~5 µs); the feed is read and the view built only when it moved (a window idle
    for hours costs nothing)."""
    seed = window_seed.build()
    reader = _reader(seed)
    views, _got = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: len(views) >= 1)
        time.sleep(0.1)
        reads, builds, n = reader.reads, reader.builds, len(views)
        time.sleep(0.5)                                   # ~25 polls
        assert (reader.reads, reader.builds, len(views)) == (reads, builds, n)
    finally:
        reader.stop()


def test_an_outside_commit_shows_within_a_fraction_of_a_second():
    """RD-G5's spirit for the window: a hato drop (another program's commit) reaches the view at the next poll."""
    seed = window_seed.build()
    reader = library_reader.LibraryReader(seed.opener, numbers=seed.numbers, poll=library_reader.POLL_S)
    views, _got = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views)
        new_id = max(r["id"] for r in seed.items) + 1
        hero = next(r for r in seed.items if r["tier"] == "now")
        t0 = time.monotonic()
        seed.library.commit(items=[dict(hero, id=new_id, ord=hero["ord"] - 512, rel_path="HighPriority/Hato/new.srt",
                                        title="new.srt", piece_id=9999)], order=True)
        assert _wait(lambda: any(r.key == "p9999" for r in views[-1][1].rows), timeout=2.0)
        # half a second is the promise; on a loaded machine (the suite's shards) only the timed run holds it tight
        assert time.monotonic() - t0 < (0.5 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 2.0)
        assert views[-1][1].rows[0].key == "p9999"
    finally:
        reader.stop()


def test_the_feed_is_applied_by_id_and_a_tombstone_removes_the_row():
    seed = window_seed.build()
    reader = _reader(seed)
    views, _got = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views)
        drama = next(r for r in seed.items if r["tier"] == "now" and r["title"].endswith("01.srt") and
                     r["availability"] == "missing")
        ids = [r["id"] for r in seed.items if r["piece_id"] == drama["piece_id"]]
        seed.library.commit(gone=[("item", i) for i in ids], order=True)
        assert _wait(lambda: not any(r.key == f"p{drama['piece_id']}" for r in views[-1][1].rows))
    finally:
        reader.stop()


def test_the_cache_is_used_only_when_its_key_matches(tmp_path):
    seed = window_seed.build()
    cache = str(tmp_path / "window_cache_ja.json")
    reader = _reader(seed, cache_file=cache)
    views, _got = _collect(reader)
    reader.start()
    assert _wait(lambda: os.path.exists(cache))
    reader.stop()
    data = json.load(open(cache, encoding="utf-8"))
    assert data["version"] == library_reader.CACHE_VERSION and len(data["view"]["rows"]) <= view_rows.CACHE_ROWS
    # the same store: the cache is the first view, then the live one replaces it
    again = _reader(seed, cache_file=cache)
    views2, _ = _collect(again)
    again.start()
    try:
        assert _wait(lambda: len(views2) >= 2)
        assert views2[0][1].cached and not views2[-1][1].cached
    finally:
        again.stop()
    # the order moved meanwhile: the cache is not shown
    seed.library.commit(order=True)
    third = _reader(seed, cache_file=cache)
    views3, _ = _collect(third)
    third.start()
    try:
        assert _wait(lambda: views3)
        assert not views3[0][1].cached
    finally:
        third.stop()


def test_a_damaged_cache_is_no_cache(tmp_path):
    seed = window_seed.build()
    cache = tmp_path / "window_cache_ja.json"
    cache.write_text("{not json", encoding="utf-8")
    reader = _reader(seed, cache_file=str(cache))
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views)
        assert not views[0][1].cached
    finally:
        reader.stop()


def test_getting_ready_and_read_only_give_their_states_with_rows():
    seed = window_seed.build(mode="json", reason="not ready")
    reader = _reader(seed)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "getting-ready")
        assert views[-1][1].rows                           # read-only, from the last copy
        seed.library.set_mode("read-only", "damaged")
        assert _wait(lambda: views[-1][1].state == "read-only" and views[-1][1].reason == "damaged")
        seed.library.set_mode("store")
        assert _wait(lambda: views[-1][1].state == "full")
    finally:
        reader.stop()


def test_a_read_that_fails_keeps_the_last_view_busy_then_recovers():
    seed = window_seed.build()
    reader = _reader(seed)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "full")
        good = views[-1][1]
        real = seed.opener.handle

        class Locked:
            def data_version(self):
                raise RuntimeError("database is locked")
        seed.opener.handle = lambda: Locked()
        assert _wait(lambda: views[-1][1].busy)
        assert views[-1][1].rows == good.rows
        seed.opener.handle = real
        seed.library.commit(items=[{"id": seed.items[0]["id"], "watched": 1}])
        assert _wait(lambda: not views[-1][1].busy)
    finally:
        reader.stop()


def test_a_listener_that_raises_never_stops_the_reader():
    seed = window_seed.build()
    reader = _reader(seed)
    reader.subscribe(lambda v: 1 / 0)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views)
        seed.library.commit(items=[{"id": seed.items[0]["id"], "watched": 1}])
        n = len(views)
        assert _wait(lambda: len(views) > n)
    finally:
        reader.stop()



def test_a_data_version_move_that_changes_nothing_builds_nothing():
    """A-7: SQLite moves `data_version` on a checkpoint too; a read that brings nothing the window shows publishes no
    new view."""
    seed = window_seed.build()
    reader = _reader(seed)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "full")
        time.sleep(0.1)
        n, builds = len(views), reader.builds
        with seed.library._lock:
            seed.library._data_version += 1               # another connection's checkpoint: no row changed
        assert _wait(lambda: reader.skipped >= 1)
        assert len(views) == n and reader.builds == builds
    finally:
        reader.stop()


def test_cards_made_without_a_feed_row_still_show():
    """A-8: L3.1's `record_made` doesn't put the item in the feed; the reader asks every change for the cards."""
    seed = window_seed.build()
    reader = _reader(seed)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "full")
        row = next(r for r in views[-1][1].rows if r.status.kind == "waiting")
        item = row.episodes[0].id
        with seed.library._lock:
            seed.library._cards[item] = [1, 2, 3]
            seed.library._data_version += 1
        assert _wait(lambda: any(e.cards == 3 for r in views[-1][1].rows for e in r.episodes if e.id == item))
    finally:
        reader.stop()


def test_the_stores_mode_is_asked_at_the_start_not_every_poll():
    """A-5: the real opener's `check()` probes the file; while the store is in use it's asked once."""
    seed = window_seed.build()
    calls = []
    real = seed.opener.check
    seed.opener.check = lambda: (calls.append(1), real())[1]
    reader = _reader(seed)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views)
        time.sleep(0.5)                                  # ~25 polls
        assert len(calls) <= 2
    finally:
        reader.stop()


def test_a_store_that_turns_busy_keeps_its_rows_under_the_bar():
    """A-6: with no handle to read (busy, damaged, newer) the last rows stay, the bar says why."""
    from tests.fixtures import standin_store

    class NoCopy(standin_store.StandinOpener):
        fallback_handle = None
    seed = window_seed.build()
    opener = NoCopy(seed.library)
    reader = library_reader.LibraryReader(opener, numbers=seed.numbers, poll=0.02)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "full")
        rows = views[-1][1].rows
        seed.library.set_mode("read-only", "busy")
        assert _wait(lambda: views[-1][1].state == "read-only", timeout=6.0)
        assert views[-1][1].rows == rows and views[-1][1].reason == "busy"
    finally:
        reader.stop()


def test_a_status_write_keeps_a_stale_cache_out(tmp_path):
    """A-9: the cache key is the store's (id, epoch, state version): a watched tick since it was written keeps it out."""
    seed = window_seed.build()
    cache = str(tmp_path / "window_cache_ja.json")
    first = _reader(seed, cache_file=cache)
    first.start()
    assert _wait(lambda: os.path.exists(cache))
    first.stop()
    seed.library.commit(items=[{"id": seed.items[0]["id"], "watched": 1}])
    again = _reader(seed, cache_file=cache)
    views, _ = _collect(again)
    again.start()
    try:
        assert _wait(lambda: views)
        assert not views[0][1].cached
    finally:
        again.stop()


def test_the_tiers_stay_in_order_through_moves_and_status_writes():
    """The reader keeps each tier sorted between changes: a status write swaps a row in place; a move (a new `ord`)
    sorts its tier again — the view's order is always the store's."""
    seed = window_seed.build()
    reader = _reader(seed)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "full")
        keys = [r.key for r in views[-1][1].rows]
        third = views[-1][1].rows[2]
        seed.library.commit(items=[{"id": third.episodes[0].id, "watched": 1}])     # a status write
        assert _wait(lambda: views[-1][1].rows[2].episodes[0].watched)
        assert [r.key for r in views[-1][1].rows] == keys
        moved = [e.id for e in third.episodes]                                       # the third row to the top
        top = min(r["ord"] for r in seed.items if r["tier"] == "now")
        seed.library.commit(items=[{"id": i, "ord": top - 1000 + k} for k, i in enumerate(moved)], order=True)
        assert _wait(lambda: views[-1][1].rows[0].key == third.key)
        assert [r.key for r in views[-1][1].rows][1:3] == keys[:2]
    finally:
        reader.stop()


def test_a_card_deleted_in_anki_takes_its_mark_away(monkeypatch):
    """Sonic (2026-10-07): a card the learner deleted shows nothing. When the store records the deletion (`data_version`
    moves, no feed row), the reader asks every item's cards again within CARDS_ALL_S and the ✓ goes."""
    monkeypatch.setattr(library_reader, "CARDS_ALL_S", 0.2)
    seed = window_seed.build()
    reader = _reader(seed)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "full")
        item = next(e.id for r in views[-1][1].rows for e in r.episodes if e.cards > 0)
        with seed.library._lock:
            seed.library._cards.pop(item, None)
            seed.library._data_version += 1             # one move: the cards go stale, all re-asked past CARDS_ALL_S
        assert _wait(lambda: all(e.cards == 0 and e.status.kind != "in_anki"
                                 for r in views[-1][1].rows for e in r.episodes if e.id == item))
    finally:
        reader.stop()


def test_with_no_handle_a_new_numbers_version_builds_and_the_same_version_builds_nothing():
    """W12: with no store handle (read-only, no copy to fall back on) the last rows stay, but the plan's numbers still
    belong to the view: a new numbers version publishes a new view; the same version builds nothing more."""
    from tests.fixtures import standin_store

    class NoCopy(standin_store.StandinOpener):
        fallback_handle = None
    seed = window_seed.build()
    seed.library.set_mode("read-only", "busy")
    reader = library_reader.LibraryReader(NoCopy(seed.library), language=seed.language, numbers=seed.numbers,
                                          poll=0.02)
    views, _ = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and views[-1][1].state == "read-only", timeout=6.0)
        builds = reader.builds
        time.sleep(0.5)                                  # ~25 polls with the same numbers version: no build
        assert reader.builds == builds
        item = next(iter(seed.numbers.table))
        n = len(views)
        seed.numbers.set(item, (1, 2, 3))                # a new numbers version, no handle to read
        assert _wait(lambda: len(views) > n)
        assert reader.builds > builds
    finally:
        reader.stop()


def test_the_first_screens_cache_is_written_at_the_next_quiet_look_not_in_the_look_that_built_it(tmp_path, monkeypatch):
    """Speed round 5: the cache's JSON used to be written in the same look that published the view, holding Python's
    lock while the window took that view in. Now the view's cache waits for the next look that finds the store
    unchanged, and a reader stopped after one view still leaves its cache written (the stop's flush)."""
    seed = window_seed.build()
    cache = tmp_path / "window_cache_ja.json"
    reader = _reader(seed, cache_file=str(cache))
    writes = []
    real_write = reader._write_cache

    def spy(view, key):
        writes.append(key)
        real_write(view, key)
    monkeypatch.setattr(reader, "_write_cache", spy)
    views, _ = _collect(reader)
    reader._look()                                       # the look that builds the view
    assert len(views) == 1 and writes == [] and not cache.exists()
    reader._look()                                       # a quiet look: the store is unchanged
    assert len(writes) == 1 and cache.exists()
    reader._look()                                       # nothing due any more
    assert len(writes) == 1

    # the stop's flush, isolated: a long poll means no quiet look runs before the reader is stopped
    stopper_cache = tmp_path / "window_cache_stop_ja.json"
    stopper = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                           poll=5.0, cache_file=str(stopper_cache))
    views2, _ = _collect(stopper)
    stopper.start()
    try:
        assert _wait(lambda: views2)
        time.sleep(0.5)                                  # the poll is 5 s: no second look has run yet
        assert not stopper_cache.exists()
    finally:
        stopper.stop()
    assert stopper_cache.exists()


def test_a_tier_re_sorted_from_its_own_items_stays_in_the_stores_order_through_every_change():
    """Speed round 5: a tier that moved is sorted again from its own items and the items that came into it, never from
    every item. Whatever the change — an arrival in Now, an item moved from Soon into Now, a new place inside Goal, an
    item removed — every tier must still list its items in the store's order, or the learner sees the wrong next word.
    No thread here: the reader's look is run by hand, so each change is checked the moment it lands."""
    seed = window_seed.build()
    reader = _reader(seed)
    reader._look()

    def assert_store_order(why):
        tiers = reader._sorted_tiers()
        ref = view_rows._by_tier(reader._items)
        for t in set(tiers) | set(ref):
            got = [r["id"] for r in tiers.get(t, [])]
            want = [r["id"] for r in ref.get(t, [])]
            assert got == want, f"{why}: tier {t} is out of the store's order"

    assert_store_order("the first view")
    now = [r for r in seed.items if r["tier"] == "now"]
    top = min(r["ord"] for r in now)

    newcomer = dict(now[0], id=10 ** 6, piece_id=10 ** 6, ord=now[0]["ord"] - 0.5,
                    rel_path="HighPriority/新着/新着 - 01.srt", title="新着 - 01.srt")
    seed.library.commit(items=[newcomer], order=True)                 # an arrival in Now
    reader._look()
    assert 10 ** 6 in [r["id"] for r in reader._sorted_tiers()["now"]]
    assert_store_order("an arrival in Now")

    mover = next(r["id"] for r in seed.items if r["tier"] == "soon")
    seed.library.commit(items=[{"id": mover, "tier": "now", "ord": top - 100}], order=True)   # Soon -> Now
    reader._look()
    assert mover in [r["id"] for r in reader._sorted_tiers()["now"]]
    assert_store_order("an item moved from Soon into Now")

    goal = [r for r in seed.items if r["tier"] == "goal"]
    last = max(r["ord"] for r in goal)
    first_goal = min(goal, key=lambda r: r["ord"])
    seed.library.commit(items=[{"id": first_goal["id"], "ord": last + 1}], order=True)       # to the end of Goal
    reader._look()
    assert_store_order("an ord change within Goal")

    seed.library.commit(gone=[("item", now[-1]["id"])], order=True)  # a removal from Now
    reader._look()
    assert now[-1]["id"] not in [r["id"] for r in reader._sorted_tiers()["now"]]
    assert_store_order("a removal from Now")


def test_a_full_cards_re_ask_that_finds_the_same_counts_builds_and_publishes_nothing(monkeypatch):
    """The ✓ counts on Current and Finished rows are asked again for every item every CARDS_ALL_S, because a card can
    be made in Anki without moving its row. When the store answers with the same counts, the reader must keep the same
    dict and build and publish nothing: a re-ask that changes nothing costs the learner no redraw."""
    seed = window_seed.build()
    reader = _reader(seed)
    views, _ = _collect(reader)
    reader._look()                                       # the first look: the full read and the first view
    assert len(views) == 1
    before, builds = reader._cards, reader.builds

    handle = seed.opener.handle()                        # the reader's own handle (this thread's), so the spy sees its asks
    asked = []
    real_cards_of = handle.cards_of

    def spy(item_ids):
        asked.append(list(item_ids))
        return real_cards_of(item_ids)
    monkeypatch.setattr(handle, "cards_of", spy)
    monkeypatch.setattr(library_reader, "CARDS_ALL_S", 0.0)  # every item is due again at once
    reader._cards_stale = True

    reader._look()                                       # the forced full re-ask, with the same answers

    assert asked, "the full re-ask must really run, or the test proves nothing"
    assert reader.builds == builds and len(views) == 1
    assert reader._cards is before


def _busy_commit(seed, n):
    """One more episode for the store to report: another program writing to the library all the time."""
    hero = next(r for r in seed.items if r["tier"] == "now")
    new_id = max(r["id"] for r in seed.items) + 1 + n
    seed.library.commit(items=[dict(hero, id=new_id, piece_id=9000 + n, ord=hero["ord"] - 512 - n,
                                    rel_path="HighPriority/Busy/busy - %d.srt" % n, title="busy - %d.srt" % n)],
                        order=True)


def test_a_store_that_never_rests_still_gets_its_first_screen_cache_written_within_cache_latest_s(tmp_path, monkeypatch):
    """A window keeps its first screen for the next start. A store that another program writes to all the time never
    gives a quiet look, so without the time limit the cache would never be written; past CACHE_LATEST_S it is written
    in a busy look too, and a restart still opens on the last screen."""
    seed = window_seed.build()
    cache = tmp_path / "window_cache_ja.json"
    monkeypatch.setattr(library_reader, "CACHE_LATEST_S", 0.0)     # the time is already up at the first look
    reader = _reader(seed, cache_file=str(cache))
    views, _ = _collect(reader)
    reader._look()                                       # the look that builds the view: nothing quiet has run
    assert len(views) == 1 and cache.exists()
    with open(cache, encoding="utf-8") as f:
        assert json.load(f)["version"] == library_reader.CACHE_VERSION
    for n in range(3):
        _busy_commit(seed, n)
        reader._look()                                   # every look finds a change: no quiet look ever runs
        assert len(views) == n + 2                       # each look really was busy (a view was published)


def test_busy_looks_inside_cache_latest_s_write_no_cache_while_the_window_takes_views_in(tmp_path, monkeypatch):
    """The other side of the same rule: a store busy for less than CACHE_LATEST_S still waits for a quiet look, so no
    cache JSON is written while the window is taking views in (speed round 5's hold on the window)."""
    seed = window_seed.build()
    cache = tmp_path / "window_cache_ja.json"
    monkeypatch.setattr(library_reader, "CACHE_LATEST_S", 3600.0)
    reader = _reader(seed, cache_file=str(cache))
    views, _ = _collect(reader)
    reader._look()
    for n in range(3):
        _busy_commit(seed, n)
        reader._look()
    assert len(views) == 4 and not cache.exists()
