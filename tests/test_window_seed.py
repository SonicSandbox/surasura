"""The window's synthetic seed and the stand-in store (W2.2; the window's spec 07 §7.2, 04 §4.3).

The seed: invented titles only (a leak check at every scale and in both languages), exactly the files asked for, every
state the mock shows. The stand-in: the store's read API with its rules — a handle bound to its thread, the change feed
returning only what changed, tombstones, a new epoch read in full — so the window's reads are right before W3.1 swaps in
the real store.
"""
import threading

import pytest

from tests.fixtures import standin_store, window_seed


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("files", [window_seed.SMALL, 2000, 20000])
def test_the_seed_is_invented_at_every_scale_and_has_exactly_the_files_asked(files, language):
    seed = window_seed.build(files=files, language=language)
    assert window_seed.leak_check(seed) == []
    if files:
        assert seed.files == files == len(seed.items)
    assert len({r["id"] for r in seed.items}) == len(seed.items)


def test_the_leak_check_catches_a_title_that_isnt_invented():
    seed = window_seed.build()
    seed.works[0]["title"] = "A Real Show Someone Owns"
    assert any("not invented" in p for p in window_seed.leak_check(seed))


def test_the_small_seed_holds_every_state_the_screens_draw():
    seed = window_seed.build()
    by_tier = {}
    for r in seed.items:
        by_tier.setdefault(r["tier"], []).append(r)
    assert set(by_tier) == {"now", "soon", "goal", "graduated", "arrivals"}
    now = by_tier["now"]
    assert any(r["availability"] == "missing" and r["mined_at"] for r in now)        # mined, then removed
    assert any(r["availability"] == "missing" and not r["mined_at"] for r in now)    # waiting on a video
    assert seed.mining()                                                             # being mined now
    assert any(r["pinned"] for r in by_tier["graduated"])                            # studying its cards first
    assert any(r["graduated_at"] is None for r in by_tier["graduated"])              # finished before Surasura
    split = [w for w in seed.works if len({r["piece_id"] for r in now if r["work_id"] == w["id"]}) > 1]
    assert split                                                                     # a show in two parts


def test_a_handle_is_bound_to_the_thread_that_opened_it():
    """A store handle is a sqlite3 connection: read from another thread, it raises. The window that reads on the wrong
    thread fails here, not first at W3.1."""
    seed = window_seed.build()
    h = seed.opener.wait() and seed.opener.handle()
    assert h.data_version() >= 1
    errors = []

    def other():
        try:
            h.read_feed()
        except standin_store.ProgrammingError as e:
            errors.append(e)
    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert errors


def test_the_feed_returns_only_what_changed_and_tombstones_remove():
    seed = window_seed.build()
    seed.opener.check()
    h = seed.opener.handle()
    full = h.read_feed()
    assert full["full"] and len(full["items"]) == len(seed.items)
    dv = h.data_version()
    first = seed.items[0]["id"]
    seed.library.commit(items=[{"id": first, "watched": 1}])
    assert h.data_version() != dv
    part = h.read_feed(full["version"], full["epoch"])
    assert not part["full"] and [r["id"] for r in part["items"]] == [first] and part["items"][0]["watched"] == 1
    seed.library.commit(gone=[("item", first)], order=True)
    gone = h.read_feed(part["version"], part["epoch"])
    assert gone["gone"] == [("item", first)] and not gone["items"]
    seed.library.commit(new_epoch=True)
    assert h.read_feed(gone["version"], gone["epoch"])["full"]


def test_the_stand_in_mirrors_the_stores_reads():
    seed = window_seed.build()
    seed.opener.check()
    h = seed.opener.handle()
    now = h.ordered("now")
    assert now and isinstance(now[0][1], dict) and now[0][2] in ("available", "missing")
    assert h.ids("now") == [i for i, _e, _a in now]
    item = h.item(now[0][0])
    assert set(standin_store.FEED_ITEM_FIELDS) <= set(item) and "entry" in item
    v = h.versions()
    assert {"epoch", "order_version", "availability_version", "pins_version"} <= set(v)
    tok = h.token()
    assert not h.changed_since(tok)
    seed.library.commit(items=[{"id": now[0][0], "watched": 1}])        # a status write: not a change a view redraws
    assert not h.changed_since(tok)
    seed.library.commit(items=[{"id": now[0][0], "ord": -1.0}], order=True)
    assert h.changed_since(tok)
    pinned = h.pinned()                                   # the seed's one Finished show studying its cards first
    assert pinned and all(p[2] == "graduated" for p in pinned)
    assert [p[3] for p in pinned] == sorted(p[3] for p in pinned)
    cards = h.cards_of([r["id"] for r in seed.items])
    assert cards and all(isinstance(v, list) and v for v in cards.values())
    with pytest.raises(ValueError):
        h.ordered("HighPriority")


def test_a_mode_other_than_store_gives_no_handle_but_the_last_copy():
    seed = window_seed.build(mode="json", reason="not ready")
    assert seed.opener.check() == "json" and seed.opener.reason == "not ready"
    assert seed.opener.handle() is None
    assert seed.opener.fallback_handle().read_feed()["items"]


def test_write_files_puts_real_lines_under_the_seeds_root(tmp_path):
    seed = window_seed.build(root=str(tmp_path))
    first = seed.items[0]["id"]
    paths = window_seed.write_files(seed, [first])
    text = open(paths[first], encoding="utf-8").read()
    assert paths[first].startswith(str(tmp_path)) and any("぀" <= ch <= "ヿ" for ch in text)
