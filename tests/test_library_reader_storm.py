"""The window's reader while the library grows under it (alpha 4, A2 — Mattias #8: "the window drags while background
work runs"): a + Add, a source look or an import commits batch after batch, and every commit used to be a view built
on the reader's thread (holding Python's lock against the window) and diffed on every page. With `coalesce` (the
window's reader) a burst is a few views a second, the last change always in the last view, while a learner's own asks
and a lone change still show at once; and a move's numbers, worked out just before its write, ride in the move's one
view instead of a view of their own (C2's "two builds a move").

Headless, on the stand-in store, with real titles from the seed (Japanese and Chinese).
"""
import math
import threading
import time

import pytest

from app.services import library_reader
from tests.fixtures import standin_store, window_seed


def _reader(seed, **kw):
    kw.setdefault("coalesce", True)
    return library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                        mining=seed.mining, poll=0.02, **kw)


def _collect(reader):
    views = []
    reader.subscribe(lambda view: views.append((time.monotonic(), view)))
    return views


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


def _arrival(seed, n, title):
    """`n` episodes of a new show landing in New arrivals (a hato drop, a + Add's batch)."""
    items = seed.library.items()
    first = max(r["id"] for r in items) + 1
    piece = max(r.get("piece_id") or 0 for r in items) + 1
    top = max(r["ord"] for r in items)
    work = max(w["id"] for w in seed.works) + 1 + first
    rows = [{"id": first + k, "tier": "arrivals", "ord": top + 1024.0 * (k + 1), "work_id": work, "piece_id": piece,
             "rel_path": f"HighPriority/Hato/{title}/{title} - {k + 1:02d}.srt", "title": f"{title} - {k + 1:02d}.srt",
             "parent_folder": title, "source_type": "subtitle", "availability": "available", "watched": 0,
             "added_at": "2026-10-27T10:00:00Z"} for k in range(n)]
    works = [{"id": work, "title": title, "folder_key": f"HighPriority/Hato/{title}", "media_type": "anime"}]
    return rows, works


def _arrival_keys(view):
    return {a.key for a in view.arrivals}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_burst_of_commits_is_a_few_views_a_second_and_the_last_view_holds_the_last_commit(language):
    """Thirty batches 20 ms apart (a fast look's + Add): at most four views a second while they land — not one per
    batch — and the view after the burst holds every file, the last batch's too (the build waits, it is never
    skipped)."""
    seed = window_seed.build(language=language)
    reader = _reader(seed)
    views = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and not views[-1][1].loading)
        before = len(views)
        base = seed.vocabulary and sorted(seed.vocabulary)[0]
        t0 = time.monotonic()
        landed = []
        for k in range(30):
            rows, works = _arrival(seed, 3, f"{base} {k}")
            seed.library.commit(items=rows, works=works, order=True)
            landed.append(rows[-1]["id"])
            time.sleep(0.02)
        seconds = time.monotonic() - t0
        last_id = landed[-1]
        assert _wait(lambda: any(last_id in a.item_ids for a in views[-1][1].arrivals), 3.0)
        built = len(views) - before
        assert built <= math.ceil(seconds * 4) + 1, (built, seconds)
        assert built < 30 / 2                                       # far fewer than one a batch
        every = {i for _t, v in views[-1:] for a in v.arrivals for i in a.item_ids}
        assert set(landed) <= every                                 # nothing lost on the way
        assert reader.held_back > 0
    finally:
        reader.stop()


def test_a_lone_commit_after_a_quiet_spell_shows_at_once():
    """A hato drop (one commit) with nothing else going on is never held back: it shows at the next look."""
    seed = window_seed.build()
    reader = _reader(seed)
    views = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and not views[-1][1].loading)
        time.sleep(library_reader.COALESCE_S + 0.05)                # the last view is long past
        n, held = len(views), reader.held_back
        rows, works = _arrival(seed, 2, "雲の上の郵便屋さん 新章")
        t0 = time.monotonic()
        seed.library.commit(items=rows, works=works, order=True)
        assert _wait(lambda: len(views) > n, 2.0)
        assert views[-1][0] - t0 < library_reader.COALESCE_S / 2     # one poll and one build, no wait
        assert reader.held_back == held
    finally:
        reader.stop()


def test_the_windows_own_asks_build_at_once_inside_a_burst():
    """While a burst holds builds back, the window's own ask — its expectation of a command it is writing (a menu's
    *Move to Finished*) — is built at once: what the learner did never waits for the import's next view."""
    seed = window_seed.build()
    reader = _reader(seed)
    views = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and not views[-1][1].loading)
        rows, works = _arrival(seed, 2, "海辺の図書室 続")
        seed.library.commit(items=rows, works=works, order=True)
        assert _wait(lambda: any(rows[0]["id"] in a.item_ids for a in views[-1][1].arrivals))
        rows, works = _arrival(seed, 2, "海辺の図書室 続々")
        seed.library.commit(items=rows, works=works, order=True)     # held back: within COALESCE_S of the last view
        assert _wait(lambda: reader.held_back > 0, 1.0)
        n = len(views)
        hero = next(r for r in seed.items if r["tier"] == "now")
        t0 = time.monotonic()
        reader.expect({hero["id"]: "graduated"})
        assert _wait(lambda: len(views) > n, 1.0)
        assert views[n][0] - t0 < library_reader.COALESCE_S / 2
        assert any(hero["id"] in (e.id for e in r.episodes) for m in views[n][1].finished for r in m.rows)
    finally:
        reader.stop()


def test_a_learners_command_inside_a_burst_shows_at_once_and_is_still_one_view():
    """A move the learner makes while an import lands (the window calls `urgent` as it hands the writer the command):
    its numbers and its write build at once — never held back behind the import's next view — and still as one."""
    seed = window_seed.build(language="zh")
    reader = _reader(seed)
    views = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and not views[-1][1].loading)
        rows, works = _arrival(seed, 2, "第七扇门 新篇")
        seed.library.commit(items=rows, works=works, order=True)
        assert _wait(lambda: any(rows[0]["id"] in a.item_ids for a in views[-1][1].arrivals))
        n, builds = len(views), reader.builds                         # the burst's view: anything now is held back
        soon = next(r for r in seed.items if r["tier"] == "soon")
        top = min(r["ord"] for r in seed.items if r["tier"] == "now")
        reader.urgent()
        seed.numbers.set(soon["id"], (4000, 4100, 12))
        reader.refresh()
        time.sleep(0.01)
        t0 = time.monotonic()
        seed.library.commit(items=[{"id": soon["id"], "tier": "now", "ord": top - 100}], order=True)
        assert _wait(lambda: len(views) > n, 1.0)
        assert views[n][0] - t0 < library_reader.COALESCE_S / 2      # not held behind the burst
        time.sleep(library_reader.COALESCE_S + 0.1)
        assert reader.builds == builds + 1                            # one view: the numbers and the write
        assert views[-1][1].rows[0].n_new == 12
    finally:
        reader.stop()


def test_a_moves_numbers_and_its_write_are_one_view():
    """The window's writer works a move's numbers out, then writes the move a moment later: the reader waits a moment
    for the write the numbers come before, and builds the two as one view (C2: the reader built the view twice a
    move), the moved row's *N new* fresh in it."""
    seed = window_seed.build()
    reader = _reader(seed)
    views = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and not views[-1][1].loading)
        time.sleep(library_reader.COALESCE_S + 0.05)
        n, builds = len(views), reader.builds
        soon = next(r for r in seed.items if r["tier"] == "soon")
        top = min(r["ord"] for r in seed.items if r["tier"] == "now")
        seed.numbers.set(soon["id"], (4000, 4100, 31))               # the numbers first ...
        reader.refresh()
        time.sleep(0.01)
        seed.library.commit(items=[{"id": soon["id"], "tier": "now", "ord": top - 100}], order=True)   # ... the write
        assert _wait(lambda: len(views) > n, 2.0)
        time.sleep(library_reader.COALESCE_S + 0.1)                   # nothing else comes
        assert reader.builds == builds + 1 and len(views) == n + 1
        hero = views[-1][1].rows[0]
        assert soon["id"] in (e.id for e in hero.episodes) and hero.n_new == 31
    finally:
        reader.stop()


def test_numbers_that_no_write_follows_still_show_after_the_grace():
    """A Generate's or another program's numbers (no write of the window's after them) wait only the grace, then show."""
    seed = window_seed.build()
    reader = _reader(seed)
    views = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and not views[-1][1].loading)
        time.sleep(library_reader.COALESCE_S + 0.05)
        n = len(views)
        hero = views[-1][1].rows[0]
        first = hero.episodes[0].id
        seed.numbers.set(first, (100, 4000, 77))
        t0 = time.monotonic()
        reader.refresh()
        assert _wait(lambda: len(views) > n, 2.0)
        assert library_reader.NUMBERS_GRACE_S <= views[-1][0] - t0 + 0.01 < library_reader.COALESCE_S
        assert views[-1][1].rows[0].pct is not None
    finally:
        reader.stop()


def test_coalescing_is_off_unless_asked_so_each_look_builds():
    """A reader made without `coalesce` (the tests' and tools' own) builds on every look that found a change."""
    seed = window_seed.build()
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
    reader._look()
    builds = reader.builds
    for k in range(3):
        rows, works = _arrival(seed, 1, f"狐火と商店街 {k}")
        seed.library.commit(items=rows, works=works, order=True)
        reader._look()
    assert reader.builds == builds + 3 and reader.held_back == 0


def test_a_drag_holding_the_view_still_gets_the_held_back_change_at_its_drop():
    """A change held back by the burst rule, then a drag: nothing is built under the hand, and the drop builds it —
    nothing lost between the two rules."""
    seed = window_seed.build()
    reader = _reader(seed)
    views = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and not views[-1][1].loading)
        rows, works = _arrival(seed, 1, "星空キャンプ部 外伝")
        seed.library.commit(items=rows, works=works, order=True)
        assert _wait(lambda: any(rows[0]["id"] in a.item_ids for a in views[-1][1].arrivals))
        rows, works = _arrival(seed, 1, "星空キャンプ部 外伝二")
        seed.library.commit(items=rows, works=works, order=True)
        reader.hold()
        time.sleep(library_reader.COALESCE_S + 0.1)
        n = len(views)
        assert not any(rows[0]["id"] in a.item_ids for a in views[-1][1].arrivals)
        reader.release()
        assert _wait(lambda: len(views) > n, 1.0)
        assert any(rows[0]["id"] in a.item_ids for a in views[-1][1].arrivals)
    finally:
        reader.stop()


# --- fix round (A4A-2, IK-2) ------------------------------------------------------------------------------------------ #
class _Listening:
    """The window's bell, live, with nothing of its own due for an hour (the store's bell and the tree watch)."""
    deaf = False

    def timeout(self):
        return 3600.0


def _owed_view(seed, reader, views, title):
    """A view held back by the burst rule (a second commit right after a view built) -> the commit's first id."""
    rows, works = _arrival(seed, 1, title)
    seed.library.commit(items=rows, works=works, order=True)
    reader.refresh()
    assert _wait(lambda: any(rows[0]["id"] in a.item_ids for a in views[-1][1].arrivals))
    rows, works = _arrival(seed, 1, title + " 二")
    seed.library.commit(items=rows, works=works, order=True)       # within COALESCE_S of that view: held back
    reader.refresh()
    assert _wait(lambda: reader._view_owed, 1.0)
    return rows[0]["id"]


@pytest.mark.parametrize("bell", ["deaf", "listening"])
def test_a_drag_over_a_held_back_view_reads_the_store_no_faster_than_its_poll_and_the_drop_builds_it(bell):
    """A4A-2: a view held back by an import's burst, then the learner starts a drag. The reader kept looking back to
    back — 44,869 feed reads a second, Python's lock taken from the window just as the hand moves — because the owed
    view fell due while nothing could be built. Held for a second it reads the store a few times at most, looks no
    faster than its poll, and the drop still builds the change it held back."""
    seed = window_seed.build()
    reader = _reader(seed)
    if bell == "listening":
        reader._lookout = _Listening()
    views = _collect(reader)
    reader.start()
    try:
        reader.refresh()
        assert _wait(lambda: views and not views[-1][1].loading)
        owed_id = _owed_view(seed, reader, views, "星空キャンプ部 外伝")
        reader.hold()                                               # the drag starts
        time.sleep(library_reader.COALESCE_S + 0.05)                # the owed view falls due under the hand
        looks, reads, n = reader.looks, reader.reads, len(views)
        time.sleep(1.0)
        looks, reads = reader.looks - looks, reader.reads - reads
        assert reads <= 12, reads                                   # the store read a few times, not thousands
        assert looks <= 1.0 / reader.poll + 10, looks               # never faster than the poll
        assert len(views) == n                                      # nothing built under the hand
        reader.release()
        assert _wait(lambda: any(owed_id in a.item_ids for a in views[-1][1].arrivals), 1.0)
    finally:
        reader.stop()


@pytest.mark.parametrize("bell", ["deaf", "listening"])
def test_a_busy_store_with_a_held_back_view_is_tried_again_at_the_poll_and_the_view_lands_once_it_frees(bell,
                                                                                                    monkeypatch):
    """A4A-2: the store busy (another program's commit holds it) while a view is owed: every look raised and the next
    came at once, a loop on the reader's thread. It tries again once a poll, and the held-back change shows once the
    store frees."""
    seed = window_seed.build(language="zh")
    reader = _reader(seed)
    if bell == "listening":
        reader._lookout = _Listening()
    views = _collect(reader)
    reader.start()
    try:
        reader.refresh()
        assert _wait(lambda: views and not views[-1][1].loading)
        owed_id = _owed_view(seed, reader, views, "第七扇门 外传")
        real_read = standin_store.StandinStore.read_feed
        busy = [True]

        def read_feed(store, *a, **k):                              # another program's commit holds the store
            if busy[0]:
                raise standin_store.OperationalError("database is locked")
            return real_read(store, *a, **k)
        monkeypatch.setattr(standin_store.StandinStore, "read_feed", read_feed)
        time.sleep(library_reader.COALESCE_S + 0.05)
        looks = reader.looks
        time.sleep(0.5)
        looks = reader.looks - looks
        assert looks <= 0.5 / reader.poll + 10, looks
        busy[0] = False
        reader.refresh()
        assert _wait(lambda: any(owed_id in a.item_ids for a in views[-1][1].arrivals), 3.0)
    finally:
        reader.stop()


def test_numbers_for_a_lone_arrival_show_at_once_but_ride_with_a_burst_that_is_under_way():
    """IK-2: a lone arrival's *N new* (the window's numbers, handed on just after the arrival's own view) waited out the
    burst rule — the arrival had just built a view — so with the window's reader the number came ~500 ms after the
    file. With no burst under way the numbers build at once; while a burst's view is owed they ride in it (one view)."""
    seed = window_seed.build()
    reader = _reader(seed)
    views = _collect(reader)
    reader.start()
    try:
        assert _wait(lambda: views and not views[-1][1].loading)
        time.sleep(library_reader.COALESCE_S + 0.05)
        rows, works = _arrival(seed, 1, "雲の上の郵便屋さん 外伝")
        seed.library.commit(items=rows, works=works, order=True)     # a lone arrival: shown at once
        assert _wait(lambda: any(rows[0]["id"] in a.item_ids for a in views[-1][1].arrivals), 1.0)
        n, held = len(views), reader.held_back
        t0 = time.monotonic()
        reader.set_estimates({rows[0]["id"]: 9})                     # its number, a moment after its view
        assert _wait(lambda: len(views) > n, 1.0)
        assert views[n][0] - t0 < library_reader.COALESCE_S / 2      # at once, not behind the arrival's own view
        assert any(a.per_ep == 9 for a in views[n][1].arrivals if rows[0]["id"] in a.item_ids)
        assert reader.held_back == held
        # a burst under way: a commit held back, then numbers — they wait for the burst's view and come in it
        owed_id = _owed_view(seed, reader, views, "雲の上の郵便屋さん 続")
        n, builds = len(views), reader.builds
        reader.set_estimates({rows[0]["id"]: 9, owed_id: 4})
        assert _wait(lambda: len(views) > n and not reader._view_owed, 2.0)
        time.sleep(library_reader.COALESCE_S + 0.1)
        assert reader.builds == builds + 1                            # one view: the burst's change and the numbers
        assert any(a.per_ep == 4 for a in views[-1][1].arrivals if owed_id in a.item_ids)
    finally:
        reader.stop()
