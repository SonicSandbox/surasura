"""A title 3.0.10 named "Processed" becomes one title per channel, once (Kura-PR2, 3.0.12; Sonic 2026-11-15: the
longer-term fix beside Kura-PR's new-videos one).

Why these matter: until 3.0.11 the store read the downloader's `Processed` folder as a show's, so every single video
dropped there, of any channel, joined ONE title called "Processed" (its folder key `processed`, the first channel's
id, every channel's name among its other titles). 3.0.11 titled new videos by their channel but left that title as it
was — and the channels inside it kept joining it. The helper's one-time pass (`Store.split_processed`) splits it: one
title per channel by each video's record, the old title's id to the first channel in the order, a video with no
channel its own name's title. What a wrong answer would cost: a learner's own title touched (one he renamed; his own
show folder named `Processed`); an item's place, tier, mark, pin, journey or Anki state changed, or Connect's records
for those items no longer matching (it would mine them again); a file moved on disk (S-R-1); a split that can't be
undone in one Undo, or that runs twice. Every test runs for Japanese and Chinese under the per-test
SURASURA_TEST_ROOT, with real words from tests/Test Resources/.
"""

import json
import os

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, names, pieces_ok, roots, touch


def _youtube(video, channel=None):
    """The record `app.qt.windows.youtube_record` makes for one transcript (a channel: its id and its show's name)."""
    record = {"schema": 1, "producer": "youtube", "language": "ja", "media_type": "youtube",
              "content_key": f"youtube:{video}", "video_id": video, "title": video}
    if channel:
        record["channel_id"] = f"UC{channel}"
        record["show"] = {"title": channel}
    return record


def _old_rule(store, data_dir, videos, monkeypatch):
    """The 3.0.10 library: each `(rel below Processed, video id, channel or None)` registered by the old rule (the
    downloader's folder read as a show's, every video one title "Processed"), New arrivals sent to Current, and the
    first helper run's mark taken off (the test's empty library's run set it). -> the item ids, in order."""
    ids = []
    with monkeypatch.context() as patched:
        patched.setattr(ls, "PROCESSED_FOLDER", "\0no folder")
        for rel, video, channel in videos:
            path = touch(data_dir, f"Processed/{rel}")
            ids.append(store.register(path, _youtube(video, channel)).added[0] if video else
                       store.insert([path], "now").added[0])
    waiting = [i for i in ids if store.item(i)["tier"] == "arrivals"]
    if waiting:
        store.move(waiting, "now")
    with store._writing():
        store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.PROCESSED_SPLIT,))
    return ids


def _work(store, item_id):
    return store.item(item_id)["work_id"]


def _works(store):
    return {w: (t, json.loads(ts), fk, ch) for w, t, ts, fk, ch in
            store.conn.execute("SELECT id, title, titles, folder_key, youtube_channel FROM works")}


def _place(store):
    """Everything the split must leave as it was, item by item: every column but its title and piece (its tier, order,
    marks, pins, journey and Anki state — `mined_at`, the stones), and every pairing (Connect's records)."""
    cols = [r[1] for r in store.conn.execute("PRAGMA table_info(items)") if r[1] not in ("work_id", "piece_id",
                                                                                          "feed_in")]
    items = store.conn.execute(f"SELECT {', '.join(cols)} FROM items ORDER BY id").fetchall()
    return items, store.conn.execute("SELECT * FROM pairings ORDER BY content_key").fetchall()


def _disk(data_dir):
    out = {}
    for top, _dirs, files in os.walk(data_dir):
        for f in files:
            p = os.path.join(top, f)
            out[os.path.relpath(p, data_dir).replace("\\", "/")] = os.path.getsize(p)
    return out


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_channels_split_in_place_and_their_next_videos_follow_their_channels(language, monkeypatch):
    """Two channels' videos, interleaved in Current, one title "Processed": two titles by channel — the old id to the
    first channel in the order — every item where it was; no title keyed `processed`; each channel's next video joins
    its own title (its id), never the old one by a name left behind."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a1, b1, a2 = _old_rule(store, data_dir, [(f"{w[81]} - {w[82]} [pitFobM6z80].txt", "pitFobM6z80", w[81]),
                                             (f"{w[83]} - {w[84]} [IIqUltT_x0c].txt", "IIqUltT_x0c", w[83]),
                                             (f"{w[81]} - {w[85]} [Qm3vR8LwZ1o].txt", "Qm3vR8LwZ1o", w[81])],
                           monkeypatch)
    old = _work(store, a1)
    assert {_work(store, i) for i in (a1, b1, a2)} == {old} and _works(store)[old][0] == "Processed"
    before, order, disk = _place(store), store.ids("now"), _disk(data_dir)
    change = store.split_processed()
    assert change is not None
    works = _works(store)
    assert _work(store, a1) == _work(store, a2) == old, "the first channel keeps the old title's id"
    assert works[old] == (w[81], [], None, f"UC{w[81]}")
    assert works[_work(store, b1)] == (w[83], [], None, f"UC{w[83]}")
    assert ls.path_key(ls.PROCESSED_FOLDER) not in {v[2] for v in works.values()}
    assert _place(store) == before and store.ids("now") == order, "every item where it was, its records untouched"
    assert _disk(data_dir) == disk, "nothing on disk moved"
    assert pieces_ok(store) is None
    nxt_b = store.register(touch(data_dir, f"Processed/{w[83]} - {w[86]} [Zx9pQ2mN4rT].txt"),
                           _youtube("Zx9pQ2mN4rT", w[83])).added[0]
    nxt_a = store.register(touch(data_dir, f"Processed/{w[81]} - {w[87]} [Kd7sLw2Pq0A].txt"),
                           _youtube("Kd7sLw2Pq0A", w[81])).added[0]
    assert _work(store, nxt_b) == _work(store, b1) and _work(store, nxt_a) == old
    assert store.split_processed() is None, "once a store"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_three_channels_across_tiers_keep_every_mark_pin_and_anki_state(language, monkeypatch):
    """Three channels, their videos in Current, Goal and Finished, one watched, one pinned, one mined (Connect's
    `mined_at`), a youtube cover of the second channel's video on the old title: three titles, in the order their
    first videos stand (Current first); every item's columns and every pairing byte-equal (Connect mines none of them
    again: its records still match); the cover of another channel's video leaves the first channel's title."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    vids = [("aaaaaaaaa01", w[90]), ("bbbbbbbbb01", w[91]), ("ccccccccc01", w[92]), ("aaaaaaaaa02", w[90]),
            ("bbbbbbbbb02", w[91]), ("ccccccccc02", w[92])]
    ids = _old_rule(store, data_dir, [(f"{ch} - {vid} [{vid}].txt", vid, ch) for vid, ch in vids], monkeypatch)
    old = _work(store, ids[0])
    store.move([ids[2], ids[5]], "goal")                     # the third channel: Goal only
    store.finish([ids[4]])
    store.set_watched([ids[1]], True)
    store.pin([ids[3]])
    with store._writing():                                   # Connect mined one; the title shows a video's cover
        store.conn.execute("UPDATE items SET mined_at = '2026-11-14T10:00:00Z' WHERE id = ?", (ids[0],))
        store.conn.execute("UPDATE works SET cover_source = 'youtube', cover_ref = 'bbbbbbbbb01', "
                           "cover_path = 'cache:bbbbbbbbb01.jpg' WHERE id = ?", (old,))
    from app.connect import library as connect_library
    records, before = connect_library.pairings(store), _place(store)
    change = store.split_processed()
    assert change is not None
    works = _works(store)
    by = {ch: {_work(store, ids[n]) for n, (_v, c) in enumerate(vids) if c == ch} for ch in (w[90], w[91], w[92])}
    assert all(len(v) == 1 for v in by.values()) and len({next(iter(v)) for v in by.values()}) == 3
    assert by[w[90]] == {old}, "the first channel in the order (Current's first row)"
    assert [works[next(iter(by[ch]))][0] for ch in (w[90], w[91], w[92])] == [w[90], w[91], w[92]]
    assert _place(store) == before and connect_library.pairings(store) == records
    assert store.item(ids[0])["mined_at"] and store.item(ids[1])["watched"] and store.item(ids[3])["pinned"]
    assert store.conn.execute("SELECT cover_source, cover_ref FROM works WHERE id = ?", (old,)).fetchone() == \
        (None, None), "another channel's video is no cover of the first channel's title"
    assert connect_library.show_title(store, ids[4]) == w[91], "Connect's show tag: the channel"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_renamed_title_and_a_library_without_one_are_left_alone(language, monkeypatch):
    """A "Processed" title the learner renamed is his (`title_by_user`): untouched, byte for byte. A library with no
    such title: nothing changes. Either way the store is marked, and the next run finds nothing."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a, _b = _old_rule(store, data_dir, [(f"{w[81]} - {w[82]} [pitFobM6z80].txt", "pitFobM6z80", w[81]),
                                        (f"{w[83]} - {w[84]} [IIqUltT_x0c].txt", "IIqUltT_x0c", w[83])], monkeypatch)
    store.rename_work(_work(store, a), w[95])
    rows = store.conn.execute("SELECT * FROM works ORDER BY id").fetchall()
    assert store.split_processed() is None
    assert store.conn.execute("SELECT * FROM works ORDER BY id").fetchall() == rows
    assert store.meta()[ls.PROCESSED_SPLIT] == 1
    store.close()

    other = migrated(language)                               # (a fresh library: its helper run marked it already)
    store_rows = other.conn.execute("SELECT * FROM works ORDER BY id").fetchall()
    assert other.meta()[ls.PROCESSED_SPLIT] == 1 and other.split_processed() is None
    with other._writing():
        other.conn.execute("DELETE FROM meta WHERE key = ?", (ls.PROCESSED_SPLIT,))
    assert other.split_processed() is None and other.meta()[ls.PROCESSED_SPLIT] == 1
    assert other.conn.execute("SELECT * FROM works ORDER BY id").fetchall() == store_rows
    other.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_videos_without_a_channel_get_their_own_names_and_a_users_processed_show_keeps_the_title(language,
                                                                                                monkeypatch):
    """In the old title: a channel's video, a bilibili.tv video (a record, no channel), a file added with no record,
    and the learner's own show folder `HighPriority/Processed/` (the old rule joined it too). The channel gets its own
    title; the two without a channel each a title by their names (`_stranded_work`); the learner's show keeps the old
    title — its name "Processed" and its key — but the channel's id and name leave it, so the channel's next video
    joins the channel's title, never his show."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    ch, bili, added = _old_rule(store, data_dir, [(f"{w[81]} - {w[82]} [pitFobM6z80].txt", "pitFobM6z80", w[81]),
                                                  (f"{w[86]} [bilibili-2410703].txt", "2410703", None),
                                                  (f"{w[87]}.txt", None, None)], monkeypatch)
    with monkeypatch.context() as patched:
        patched.setattr(ls, "PROCESSED_FOLDER", "\0no folder")
        own = store.insert([touch(data_dir, f"HighPriority/Processed/{w[88]}_第01話.srt")], "now").added[0]
    old = _work(store, ch)
    assert {_work(store, i) for i in (ch, bili, added, own)} == {old}
    before = _place(store)
    assert store.split_processed() is not None
    works = _works(store)
    assert works[old][0] == "Processed" and works[old][2] == ls.path_key("Processed") and works[old][3] is None
    assert w[81] not in works[old][1], "the channel's name left the learner's title"
    assert _work(store, own) == old
    assert works[_work(store, ch)][:1] == (w[81],) and _work(store, ch) != old
    assert works[_work(store, bili)][0] == w[86] and works[_work(store, added)][0] == w[87]
    assert len({_work(store, i) for i in (ch, bili, added, own)}) == 4
    assert _place(store) == before and pieces_ok(store) is None
    nxt = store.register(touch(data_dir, f"Processed/{w[81]} - {w[89]} [Zx9pQ2mN4rT].txt"),
                         _youtube("Zx9pQ2mN4rT", w[81])).added[0]
    assert _work(store, nxt) == _work(store, ch)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_undo_restores_the_single_title_and_the_split_never_runs_again(language, monkeypatch):
    """The split is one command: its one Undo gives the single title back as it was (its id, name, key, channel id
    and names) with every item in it and one piece where there was one; the titles it made go. The store stays
    marked, so neither the next helper run nor a later call splits it again."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    w = names(language)
    ids = _old_rule(store, data_dir, [(f"{w[81]} - {w[82]} [pitFobM6z80].txt", "pitFobM6z80", w[81]),
                                      (f"{w[83]} - {w[84]} [IIqUltT_x0c].txt", "IIqUltT_x0c", w[83]),
                                      (f"{w[85]} - {w[86]} [Qm3vR8LwZ1o].txt", "Qm3vR8LwZ1o", w[85]),
                                      (f"{w[87]} [bilibili-2410703].txt", "2410703", None)], monkeypatch)
    works, pieces = _works(store), {store.item(i)["piece_id"] for i in ids}
    before, disk = _place(store), _disk(data_dir)
    change = store.split_processed()
    assert len({_work(store, i) for i in ids}) == 4 and len({store.item(i)["piece_id"] for i in ids}) == 4
    store.undo(change)
    assert _works(store) == works, "the single title back, and the titles the split made gone"
    assert {store.item(i)["piece_id"] for i in ids} == pieces and pieces_ok(store) is None
    assert _place(store) == before and _disk(data_dir) == disk
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert _works(again) == works and again.split_processed() is None
    finally:
        again.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_helpers_run_splits_it_and_the_window_reads_the_titles(language, monkeypatch):
    """The split is the helper's (`maintain`, after the joins), so his library gets it at the first helper run after
    the update; the titles it changed and made carry the run's feed version (the window reads them again)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    w = names(language)
    a, b = _old_rule(store, data_dir, [(f"{w[81]} - {w[82]} [pitFobM6z80].txt", "pitFobM6z80", w[81]),
                                       (f"{w[83]} - {w[84]} [IIqUltT_x0c].txt", "IIqUltT_x0c", w[83])], monkeypatch)
    old, fed = _work(store, a), dict(store.conn.execute("SELECT id, feed_in FROM works"))
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    again = ls.open_store(language, data_dir, user_files_dir)
    try:
        assert _works(again)[old][0] == w[81] and _works(again)[_work(again, b)][0] == w[83]
        assert again.conn.execute("SELECT feed_in FROM works WHERE id = ?", (old,)).fetchone()[0] > fed[old]
        assert _work(again, b) not in fed
        assert again.conn.execute("SELECT feed_in FROM items WHERE id = ?", (b,)).fetchone()[0] > fed[old]
        assert again.meta()[ls.PROCESSED_SPLIT] == 1
    finally:
        again.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_first_channel_is_the_first_in_the_order_never_the_first_registered(language, monkeypatch):
    """"First" is where the learner sees it, not which came in first: the second channel's video dragged to the top of
    Current takes the old id. The old title's own cover (that channel's video) stays."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a, b = _old_rule(store, data_dir, [(f"{w[81]} - {w[82]} [pitFobM6z80].txt", "pitFobM6z80", w[81]),
                                       (f"{w[83]} - {w[84]} [IIqUltT_x0c].txt", "IIqUltT_x0c", w[83])], monkeypatch)
    old = _work(store, a)
    store.move([b], "now", before_id=a)
    with store._writing():
        store.conn.execute("UPDATE works SET cover_source = 'youtube', cover_ref = 'IIqUltT_x0c' WHERE id = ?", (old,))
    assert store.split_processed() is not None
    assert _work(store, b) == old and _works(store)[old][0] == w[83] and _work(store, a) != old
    assert store.conn.execute("SELECT cover_ref FROM works WHERE id = ?", (old,)).fetchone()[0] == "IIqUltT_x0c"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_still_in_new_arrivals_comes_first(language, monkeypatch):
    """New arrivals is the order's first section: a channel whose video waits there takes the old id, before one in
    Current."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    with monkeypatch.context() as patched:
        patched.setattr(ls, "PROCESSED_FOLDER", "\0no folder")
        a = store.register(touch(data_dir, f"Processed/{w[85]} - {w[86]} [Qm3vR8LwZ1o].txt"),
                           _youtube("Qm3vR8LwZ1o", w[85])).added[0]
        store.move([a], "now")
        b = store.register(touch(data_dir, f"Processed/{w[87]} - {w[88]} [Zx9pQ2mN4rT].txt"),
                           _youtube("Zx9pQ2mN4rT", w[87])).added[0]
    assert store.item(b)["tier"] == "arrivals" and _work(store, a) == _work(store, b)
    old = _work(store, a)
    with store._writing():
        store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.PROCESSED_SPLIT,))
    assert store.split_processed() is not None
    assert _work(store, b) == old and _works(store)[old][0] == w[87]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_channel_another_title_holds_joins_it_and_the_old_id_goes_to_the_next(language, monkeypatch):
    """One title a channel: when another title already holds a channel's id (a hato title, a merge), that channel's
    videos join it — even the first channel in the order — and the old id goes to the next channel no title holds,
    so no two titles ever hold one channel id."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a, b = _old_rule(store, data_dir, [(f"{w[81]} - {w[82]} [pitFobM6z80].txt", "pitFobM6z80", w[81]),
                                       (f"{w[83]} - {w[84]} [IIqUltT_x0c].txt", "IIqUltT_x0c", w[83])], monkeypatch)
    old = _work(store, a)
    own = store.insert([touch(data_dir, f"{ls.CONTENT_FOLDER}/{w[90]}/{w[90]} 01.srt")], "now").added[0]
    holder = _work(store, own)
    with store._writing():
        store.conn.execute("UPDATE works SET youtube_channel = NULL WHERE id = ?", (old,))
        store.conn.execute("UPDATE works SET youtube_channel = ? WHERE id = ?", (f"UC{w[81]}", holder))
    assert store.split_processed() is not None
    assert _work(store, a) == holder, "the first channel's videos join the title holding its id"
    assert _work(store, b) == old and _works(store)[old][3] == f"UC{w[83]}"
    held = [c for (c,) in store.conn.execute("SELECT youtube_channel FROM works WHERE youtube_channel IS NOT NULL")]
    assert len(held) == len(set(held)), "one title a channel id"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_of_videos_without_channels_empties_and_its_undo_brings_it_back_after_the_tidy(language, monkeypatch):
    """Only videos with no channel (bilibili.tv's): each gets its own name's title — two of one show one title — and the
    old one is left empty; the helper's tidy takes an empty title, yet the split's Undo still gives it back whole."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    ids = _old_rule(store, data_dir, [(f"{w[86]} - 01 [bilibili-2410701].txt", "2410701", None),
                                      (f"{w[86]} - 02 [bilibili-2410702].txt", "2410702", None),
                                      (f"{w[87]} [bilibili-2410703].txt", "2410703", None)], monkeypatch)
    old, works = _work(store, ids[0]), _works(store)
    change = store.split_processed()
    assert change is not None and old not in {_work(store, i) for i in ids}
    assert _work(store, ids[0]) == _work(store, ids[1]) != _work(store, ids[2])
    assert old in store.tidy_works(), "left empty: the helper's tidy takes it"
    store.undo(change)
    assert _works(store) == works and {_work(store, i) for i in ids} == {old}
    assert pieces_ok(store) is None
    store.close()
