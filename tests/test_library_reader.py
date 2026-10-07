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
        assert time.monotonic() - t0 < 0.5
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
