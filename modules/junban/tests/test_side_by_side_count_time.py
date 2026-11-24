# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-E (train 40's intent keeper, note 2): Junban's side-by-side count carries the time the run began reading Anki
(`stats["side_at"]`), and the host hands it to the store (`pins.record_side` -> `Store.set_side_cards(at=)`): a file
Connect mines after that time is one the count never saw, so the store never sets its title aside on that count.

What a wrong answer would cost a learner: Connect (its own process) mining a title's next file while the window's
re-plan reads Anki, the run then recording "no new card" for that title, and the store setting it aside on cards the
run never looked at — the title out of Connect's top 20 and the window's top until the next run brings it back.
Through `reposition` itself on the fake collection Junban's suites share; the store a real one, Japanese words.
"""
from modules.junban import connect, pins, reposition, spaced
from modules.junban.tests.connect_scene import settings
from modules.junban.tests.test_reposition import _patched
from modules.junban.tests.test_side_by_side_runs import (B_SOURCE, C_SOURCE, D_SOURCE, FOUR, HIS, STUDIED, _fake_with,
                                                         studied_list)


def _watch_gather(monkeypatch, during=None):
    """`reposition._gather` (the run's read of Anki) noting the store's time as it starts; `during`: run inside it."""
    from app import library_store as ls
    began = []
    real = reposition._gather

    def gather(*args, **kw):
        began.append(ls._now())
        if during is not None:
            during()
        return real(*args, **kw)
    monkeypatch.setattr(reposition, "_gather", gather)
    return began


def test_every_run_counts_with_the_time_it_began_reading_anki(tmp_path, monkeypatch):
    """The 順 window's preview, its Reorder and the fast re-plan's job: the count's time is before the read of Anki and
    after the run began, in the store's own shape (a receipt then is seen, one during the read is not)."""
    from app import library_store as ls
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: FOUR)
    began = _watch_gather(monkeypatch)
    for where, job in ((tmp_path, None), (tmp_path / "job", spaced.Job(automatic=True))):
        start = ls._now()
        with _patched(_fake_with(where, *HIS)):
            if job is None:
                _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
            else:
                stats = reposition.run(settings(junban_unlisted="journey"), refresh=False, job=job)["stats"]
        at = stats["side_at"]
        assert start <= at <= began[-1], (start, at, began[-1])
        count = {ls.SIDE_AT: at}
        assert ls.side_seen(count, start) and not ls.side_seen(count, ls._now()), "a receipt after it: never seen"


def test_the_counts_time_is_never_later_than_a_store_stamp_taken_after_it(monkeypatch):
    """FLAKES (GitHub, three times: the count's .927510 after the read's .927509): the count's time came from
    `time.time()`'s float, the store's from the clock's integer. At this instant the float rounds up past a
    microsecond the integer hasn't reached, so the count read 1 µs after a store stamp taken later — a file Connect
    mined in that microsecond counted as seen. The one clock now: the count's time is the store's own."""
    import time
    from app import library_store as ls
    instant = 1763894400927509889                        # (2025-11-23 UTC; the float reads .927510, the integer .927509)
    monkeypatch.setattr(time, "time_ns", lambda: instant)
    monkeypatch.setattr(time, "time", lambda: instant / 1e9)
    monkeypatch.setattr(ls, "_NOW_LAST", [0])            # (the store's last stamp is this process's: never left here)
    at = reposition._utc_now()
    after = ls._now()
    assert at.startswith("2025-11-23T10:40:00.92750") and at < after, (at, after)


def test_with_side_by_side_off_no_time_is_counted(tmp_path, monkeypatch):
    """Off (no titles from the store): no count, and no time either — the run's stats as before."""
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: ([], {}, {}))
    with _patched(_fake_with(tmp_path, *HIS)):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
    assert "side_cards" not in stats and "side_at" not in stats


def test_a_file_connect_mines_while_junban_reads_anki_never_sets_its_title_aside(tmp_path, monkeypatch):
    """End to end on a real store: A (Current's first title) has no new card in Anki yet; Connect mines A's next file
    while the run reads Anki (its new cards not in the read). The run counts A none, and the host records it — A keeps
    its turn, as the count never saw that file. The next run, the file before it, counts A none again: A steps aside."""
    from app import library_store as ls
    from tests.test_side_by_side import _library
    store, a, b, loose, d = _library("ja")
    store.set_library_options(mine_line=4, side_by_side=True)
    store.record_analysed(store.versions()["order_version"])    # (Kyou-D: the list is a Generate's of this order)
    titles = store.side_by_side()
    side = (titles, {}, {b[0]: {pins.source_of(B_SOURCE)}, loose: {pins.source_of(C_SOURCE)},
                         d[0]: {pins.source_of(D_SOURCE)}})
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: side)
    mined = []
    _watch_gather(monkeypatch, during=lambda: mined or mined.append(store.receipt(a[0], ls._now())))
    for where, stays in ((tmp_path, True), (tmp_path / "again", False)):
        fake = _fake_with(where, *STUDIED)
        studied_list(where, b, loose)                           # (Kyou-D: each word met in its own title's files)
        with _patched(fake):
            report = reposition.run(settings(junban_unlisted="journey"), refresh=False, job=spaced.Job(automatic=True))
        assert report["ok"], report["problems"]
        assert report["stats"]["side_cards"][0] == [a, 0]
        pins.record_side(store, report, by="replan")
        top = store._mine_ids(4)
        if stays:
            assert top == [a[0], b[0], a[1], b[1]], "the count never saw A's file: A keeps its turn"
        else:
            assert top[:2] == [b[0], loose] and not set(top) & set(a), "this count saw it: A aside"
    assert mined, "Connect's receipt landed during the first read"
    store.close()


def test_record_side_hands_the_counts_time_to_the_store_when_the_run_gave_one():
    seen = []

    class Store:
        def set_side_cards(self, groups, by, at=None):
            seen.append((groups, by, at))
            return True
    at = "2026-11-17T10:00:26.300000Z"
    assert pins.record_side(Store(), {"stats": {"side_cards": [[[1], 0]], "side_at": at}}, by="junban") is True
    assert pins.record_side(Store(), {"stats": {"side_cards": [[[1], 0]]}}) is True
    assert seen == [([([1], 0)], "junban", at), ([([1], 0)], "connect", None)]
