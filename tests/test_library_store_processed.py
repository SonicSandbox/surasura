"""A video dropped straight into `Processed` is titled by its show, never "Processed" (Kura-PR, 3.0.11; based on
Mattias's #449).

Why these matter: the YouTube downloader writes a single video's transcript directly into `data/<lang>/Processed`
(a playlist's videos go in a folder of their own below it). The store read `Processed` as a show's folder, so the
first channel's video made a title named "Processed" — and every later channel's single video joined it (its folder
key), one title holding many channels. A file directly in `Processed` is a loose drop now, as one in hato's drop
folder: titled by its record's show (the channel), else by its own name. What must not change: a playlist's folder
below `Processed` (still a title by its folder); a user's own show folder named `Processed` inside a tier folder or
`Library` (a show's, as before); a title already called "Processed" (never regrouped or renamed by a hand-over or a
sync: the helper's one-time split does that, test_library_store_processed_split.py); the commands on the new
titles (a drag, a move, Finished, Undo); and nothing on disk moves (S-R-1). Every test runs
for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, with real words from tests/Test Resources/.
"""

import json
import os
import sys

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, names, pieces_ok, roots, touch


def _youtube(video, channel=None, playlist=None):
    """The record `app.qt.windows.youtube_record` makes for one transcript: the channel as the show (and the
    placing rules' id) when the header names one; bilibili.tv's name none."""
    record = {"schema": 1, "producer": "youtube", "language": "ja", "media_type": "youtube",
              "content_key": f"youtube:{video}", "video_id": video, "title": video}
    if channel:
        record["channel_id"] = channel
        record["show"] = {"title": channel}
    if playlist:
        record["playlist"] = playlist
    return record


def _titles(store):
    return dict(store.conn.execute("SELECT id, title FROM works"))


def _work(store, item_id):
    return store.item(item_id)["work_id"]


def _disk(data_dir):
    """Every file under the data folder, with its size: what S-R-1 holds (the store never moves a file)."""
    out = {}
    for top, _dirs, files in os.walk(data_dir):
        for f in files:
            p = os.path.join(top, f)
            out[os.path.relpath(p, data_dir).replace("\\", "/")] = os.path.getsize(p)
    return out


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_channels_single_videos_in_processed_are_two_titles_by_their_channels(language):
    """Mattias's report: `Processed/<channel> - <video> [id].txt` became a title "Processed". Two channels' videos
    dropped straight into `Processed` are two titles, each named by its channel; a second video of a channel joins its
    channel's title (the record's id); no title is called "Processed"."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a1 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[81]} - {w[82]} [pitFobM6z80].txt"),
                        _youtube("pitFobM6z80", w[81])).added[0]
    b1 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[83]} - {w[84]} [IIqUltT_x0c].txt"),
                        _youtube("IIqUltT_x0c", w[83])).added[0]
    a2 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[81]} - {w[85]} [Qm3vR8LwZ1o].txt"),
                        _youtube("Qm3vR8LwZ1o", w[81])).added[0]
    titles = _titles(store)
    assert titles[_work(store, a1)] == w[81] and titles[_work(store, b1)] == w[83]
    assert _work(store, a1) != _work(store, b1), "two channels: two titles"
    assert _work(store, a2) == _work(store, a1), "a channel's next video: its channel's title"
    assert ls.PROCESSED_FOLDER not in titles.values()
    folder_keys = {fk for (fk,) in store.conn.execute("SELECT folder_key FROM works")}
    assert ls.path_key(ls.PROCESSED_FOLDER) not in folder_keys, "no title keyed by the downloader's folder"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_in_processed_without_a_channel_is_titled_by_its_name(language):
    """No show in the record (bilibili.tv names no channel), or no record at all (an Add of the file): a loose file's
    title by its name (`_stranded_work`) — two such files two titles, never one "Processed"."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    no_show = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[86]} [BV1xx411c7mD].txt"),
                             _youtube("BV1xx411c7mD")).added[0]
    added = store.insert([touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[87]}.txt")], "now").added[0]
    titles = _titles(store)
    assert titles[_work(store, no_show)] == w[86]
    assert titles[_work(store, added)] == w[87]
    assert _work(store, no_show) != _work(store, added)
    assert ls.PROCESSED_FOLDER not in titles.values()
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_playlist_folder_below_processed_and_a_users_processed_show_folder_are_unchanged(language):
    """Only a file DIRECTLY in `data/<lang>/Processed` is a loose drop. A playlist's folder below it is still a title by
    its folder (its key `Processed/<playlist>`, as before); a show folder the user named `Processed` inside a tier
    folder or the content folder is a show's folder, its title "Processed" — the rule compares the whole folder."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    playlist = f"{w[88]} (playlist)"
    p1 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{playlist}/{w[89]} [aaaaaaaaaa1].txt"),
                        _youtube("aaaaaaaaaa1", playlist={"id": "PLx", "index": 1})).added[0]
    p2 = store.insert([touch(data_dir, f"{ls.PROCESSED_FOLDER}/{playlist}/{w[90]}.txt")], "now").added[0]
    assert _work(store, p1) == _work(store, p2)
    row = store.conn.execute("SELECT folder_key FROM works WHERE id = ?", (_work(store, p1),)).fetchone()
    assert row[0] == ls.path_key(f"{ls.PROCESSED_FOLDER}/{playlist}")
    assert ls.folder_key_of(f"{ls.PROCESSED_FOLDER}/{playlist}/x.txt") == ls.path_key(f"{ls.PROCESSED_FOLDER}/{playlist}")
    own = store.insert([touch(data_dir, f"HighPriority/{ls.PROCESSED_FOLDER}/{w[91]}_第01話.srt")], "now").added[0]
    lib = store.insert([touch(data_dir, f"{ls.CONTENT_FOLDER}/{ls.PROCESSED_FOLDER}/{w[91]}_第02話.srt")],
                       "now").added[0]
    titles = _titles(store)
    assert titles[_work(store, own)] == ls.PROCESSED_FOLDER, "the user's own show folder keeps its name"
    assert _work(store, lib) == _work(store, own), "`Library/Processed` is the same show as `HighPriority/Processed`"
    assert pieces_ok(store) is None
    store.close()


def test_the_folder_is_matched_as_the_file_system_reads_it():
    """`Processed` is compared by `path_key`, as the content folder and hato's drop folder are: on Windows (NTFS ignores
    case) `processed/x.txt` is the same folder; on Linux only the exact name is. `./` and a nested `Processed` below
    it are read as before."""
    assert ls.folder_key_of(f"{ls.PROCESSED_FOLDER}/x.txt") is None
    assert ls.folder_key_of(f"./{ls.PROCESSED_FOLDER}/x.txt") is None
    assert ls._below_tier(f"{ls.PROCESSED_FOLDER}/x.txt") == ""
    folded = ls.folder_key_of("processed/x.txt")
    assert (folded is None) == (sys.platform in ("win32", "darwin"))
    assert ls.folder_key_of(f"{ls.PROCESSED_FOLDER}/{ls.PROCESSED_FOLDER}/x.txt") == \
        ls.path_key(f"{ls.PROCESSED_FOLDER}/{ls.PROCESSED_FOLDER}")
    assert ls.folder_key_of(f"HighPriority/{ls.PROCESSED_FOLDER}/x.srt") == ls.path_key(ls.PROCESSED_FOLDER)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_existing_processed_title_is_never_regrouped_or_renamed(language, monkeypatch):
    """A library 3.0.10 titled already holds a title "Processed" (the old rule: its folder key `processed`, the first
    channel's id, every joined channel's name among its other titles). It stays as it is — its name, key, ids and
    items — through a new channel's video, the same video handed over again and a disk sync. A channel never seen is a
    title of its own; a channel already inside it still joins it by its record (its id or its name among the title's
    others, `_work_by_record`) until the helper's one-time split (Kura-PR2, 3.0.12: `Store.split_processed`, its own
    tests) makes it one title per channel. Renaming it is the learner's (`rename_work`)."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    # the old rule, exactly: `Processed` read as a show's folder (no folder matches this one)
    with monkeypatch.context() as patched:
        patched.setattr(ls, "PROCESSED_FOLDER", "\0no folder")
        old_a = touch(data_dir, f"Processed/{w[81]} - {w[82]} [pitFobM6z80].txt")
        old_b = touch(data_dir, f"Processed/{w[83]} - {w[84]} [IIqUltT_x0c].txt")
        a = store.register(old_a, _youtube("pitFobM6z80", w[81])).added[0]
        b = store.register(old_b, _youtube("IIqUltT_x0c", w[83])).added[0]
    old = _work(store, a)
    assert _work(store, b) == old and _titles(store)[old] == "Processed", "the bug, as 3.0.10 made it"
    before = store.conn.execute("SELECT * FROM works WHERE id = ?", (old,)).fetchone()

    new = store.register(touch(data_dir, f"Processed/{w[86]} - {w[87]} [Qm3vR8LwZ1o].txt"),
                         _youtube("Qm3vR8LwZ1o", w[86])).added[0]
    assert _work(store, new) != old and _titles(store)[_work(store, new)] == w[86], "a new channel: its own title"
    store.register(old_a, _youtube("pitFobM6z80", w[81]))          # the same video handed over again
    store.sync_disk()
    assert store.conn.execute("SELECT * FROM works WHERE id = ?", (old,)).fetchone() == before, "never renamed"
    assert {_work(store, a), _work(store, b)} == {old}, "never regrouped"
    again = store.register(touch(data_dir, f"Processed/{w[83]} - {w[88]} [Zx9pQ2mN4rT].txt"),
                           _youtube("Zx9pQ2mN4rT", w[83])).added[0]
    assert _work(store, again) == old, "the known limit: a channel already inside it joins it by its name"
    assert pieces_ok(store) is None
    store.rename_work(old, w[81])
    assert _titles(store)[old] == w[81]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_drag_move_finish_and_undo_work_on_the_new_titles_and_nothing_on_disk_moves(language):
    """The new titles are ordinary titles: a drag within Current, a move to Goal, Finished and their Undo keep every
    piece one run of one title (05 §5.2) and the items in their titles; no file under the data folder moves (S-R-1)."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[81]} - {w[82]} [pitFobM6z80].txt"),
                       _youtube("pitFobM6z80", w[81])).added[0]
    b = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[83]} - {w[84]} [IIqUltT_x0c].txt"),
                       _youtube("IIqUltT_x0c", w[83])).added[0]
    assert {store.item(a)["tier"], store.item(b)["tier"]} == {"arrivals"}, "New arrivals is on: they wait there"
    store.move([a, b], "now")                                     # the learner sends them to Current
    works = {a: _work(store, a), b: _work(store, b)}
    disk = _disk(data_dir)
    dragged = store.move([b], "now", before_id=a)
    assert store.ids("now").index(b) < store.ids("now").index(a)
    moved = store.move([a], "goal")
    assert a in store.ids("goal")
    finished = store.finish([b])
    assert b in store.ids("graduated")
    assert pieces_ok(store) is None
    for change in (finished, moved, dragged):
        if change is not None:
            store.undo(change)
            assert pieces_ok(store) is None
    assert a in store.ids("now") and b in store.ids("now")
    assert {i: _work(store, i) for i in (a, b)} == works, "every item stays in its title"
    assert _disk(data_dir) == disk, "nothing on disk moved"
    assert json.dumps(_titles(store), ensure_ascii=False).count(ls.PROCESSED_FOLDER) == 0
    store.close()


# --- New arrivals: a title's new video joins its row (Kura-PR2, 3.0.12; based on Mattias's #466) ----------------- #
# His library: two channels, two videos each, came in one after another (A, B, B, A). Each was titled by its channel,
# but the tray draws a row per piece, and a new item joined only the piece of its title it landed directly after:
# A's second video came in after B's, a row of its own, shown by its video's name — it looked like another title. An
# item a command brings into New arrivals now lands right after its title's last item there and joins its row. Never
# an item moved there or put back by an Undo (where it stands is what the learner did), and never Current or Soon.

def _tray(store):
    """The tray's rows as the window builds them from the store's feed (`view_rows.build`): each row's item ids, newest
    row first by `added_at` — and every row's stamp, to hold that order."""
    from app.services import view_rows
    feed = store.read_feed()
    view = view_rows.build({r["id"]: r for r in feed["items"]}, {w["id"]: w for w in feed["works"]}, feed["options"],
                           language=store.language, pieces={p["id"]: p for p in feed.get("pieces") or ()})
    return [tuple(a.item_ids) for a in view.arrivals], [a.added_at for a in view.arrivals]


def _placed(store):
    """Every row outside New arrivals, as it stands: (id, tier, ord) — what the gathering may never touch."""
    return store.conn.execute("SELECT id, tier, ord FROM items WHERE tier != 'arrivals' ORDER BY id").fetchall()


def _hato(show, episode):
    return {"schema": 1, "producer": "hato", "content_key": f"hato:{show}:{episode}",
            "show": {"title": show, "episode": episode}}


def _video(store, data_dir, channel, video, words):
    return store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{channel} - {words} [{video}].txt"),
                          _youtube(video, channel)).added[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_channels_video_after_another_channels_joins_its_row_in_new_arrivals(language):
    """His A, B, B, A: two rows, one a channel, each in the order its videos came, the rows newest first by
    `added_at` (A's, its newest the last to come). A's video placed in Current before stays where it is: only New
    arrivals is gathered, and nothing outside it moves."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a0 = _video(store, data_dir, w[81], "yuhZP5BnWW0", w[80])
    store.move([a0], "now")                                   # the learner sent A's first video to Current
    before = _placed(store)
    a1 = _video(store, data_dir, w[81], "yuhZP5BnWWI", w[82])
    b1 = _video(store, data_dir, w[83], "ub05E5rev7E", w[84])
    b2 = _video(store, data_dir, w[83], "MQzFMVzOEc4", w[85])
    a2 = _video(store, data_dir, w[81], "HZ8bb5k22po", w[86])
    assert {store.item(i)["tier"] for i in (a1, b1, b2, a2)} == {"arrivals"}
    assert _work(store, a2) == _work(store, a1) == _work(store, a0) != _work(store, b1)
    rows, stamps = _tray(store)
    assert rows == [(a1, a2), (b1, b2)], "a channel's videos one row, in the order they came"
    assert stamps == sorted(stamps, reverse=True), "the rows newest first by added_at"
    assert _placed(store) == before, "Current, Soon and Goal never touched"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_arrival_whose_title_has_nothing_earlier_there_stays_where_it_came(language):
    """A, then B: each its own row where it came (B's the newest, first); a third channel's too."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a1 = _video(store, data_dir, w[81], "yuhZP5BnWWI", w[82])
    b1 = _video(store, data_dir, w[83], "ub05E5rev7E", w[84])
    c1 = _video(store, data_dir, w[87], "Kd7sLw2Pq0A", w[88])
    assert store.ids("arrivals") == [a1, b1, c1]
    assert _tray(store)[0] == [(c1,), (b1,), (a1,)]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_moved_into_new_arrivals_or_put_back_by_undo_stays_where_it_was_put(language):
    """A's second video goes to Current, B's comes in, then the learner moves A's back into New arrivals (its end):
    it stays after B's — a row of its own, as he put it. Removed, then its Remove undone (or *Put back* from Removed),
    it comes back there too.
    A video of A that comes in later joins the row it lands beside (A's last there)."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a1 = _video(store, data_dir, w[81], "yuhZP5BnWWI", w[82])
    a2 = _video(store, data_dir, w[81], "HZ8bb5k22po", w[86])
    store.move([a2], "now")
    b1 = _video(store, data_dir, w[83], "ub05E5rev7E", w[84])
    store.move([a2], "arrivals", after_id=b1)
    assert store.ids("arrivals") == [a1, b1, a2], "moved there by the learner: where he put it"
    removed = store.remove([a2])
    assert store.ids("arrivals") == [a1, b1]
    store.undo(removed)
    assert store.ids("arrivals") == [a1, b1, a2], "put back by its Undo: where it was"
    removed = store.remove([a2])
    store.restore(removed.trash_ids)
    assert store.ids("arrivals") == [a1, b1, a2], "*Put back* from Removed: where it was"
    a3 = _video(store, data_dir, w[81], "Zx9pQ2mN4rT", w[88])
    assert store.ids("arrivals") == [a1, b1, a2, a3], "a new one lands after its title's last: here, already"
    assert sorted(_tray(store)[0]) == sorted([(a1,), (b1,), (a2, a3)])
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_look_bringing_several_of_a_title_keeps_their_order_inside_its_row(language):
    """A guard: a look's take-in brings two shows' first episodes (in its shows' name order); the next look brings the
    first show's next two (one command, two items). The look places a show's new files after its last already (§6.10
    rule 3); the gathering keeps that — both in its row, in their order, right after its first episode, the other
    show's row untouched."""
    from tests.test_library_store_sources import _empty, _found, _source_root
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    show, other = w[90], w[91]
    with store:
        root = store.add_source(src)
        firsts = [_found(language, data_dir, src, show, f"{show} 第01話.srt", 1),
                  _found(language, data_dir, src, other, f"{other} 第01話.srt", 2)]
        store.take_in(root, firsts)
        first, elsewhere = (store.item_id(f["rel"]) for f in firsts)
        assert sorted(store.ids("arrivals")) == sorted([first, elsewhere])
        later = [_found(language, data_dir, src, show, f"{show} 第02話.srt", 3),
                 _found(language, data_dir, src, show, f"{show} 第03話.srt", 4)]
        store.take_in(root, later)
        two, three = (store.item_id(f["rel"]) for f in later)
        ids = store.ids("arrivals")
        assert ids[ids.index(first):ids.index(first) + 3] == [first, two, three] and elsewhere in ids
        assert sorted(_tray(store)[0]) == sorted([(first, two, three), (elsewhere,)])
        assert pieces_ok(store) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_several_new_videos_of_a_title_in_one_command_join_its_row_in_their_order(language):
    """One command bringing two of A's videos after B's (a batch: one settling for both): both land after A's first,
    in the order they came — A1, A2, A3, then B1."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a1 = _video(store, data_dir, w[81], "yuhZP5BnWWI", w[82])
    b1 = _video(store, data_dir, w[83], "ub05E5rev7E", w[84])
    with store._command("register_batch", "sync"):          # (the store's commands nest: one settle at the end)
        a2 = _video(store, data_dir, w[81], "HZ8bb5k22po", w[86])
        a3 = _video(store, data_dir, w[81], "Zx9pQ2mN4rT", w[88])
    assert store.ids("arrivals") == [a1, a2, a3, b1]
    assert sorted(_tray(store)[0]) == sorted([(a1, a2, a3), (b1,)])
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_episode_placed_before_its_titles_row_stays_in_that_row(language):
    """The review's case: New arrivals holds S's first episode, another show's, then S's third (the learner moved it
    there). A look brings S's second: the look places it before the third (episode order), in that row — beside its
    own title already, so it stays, never pulled up to the first."""
    from tests.test_library_store_sources import _empty, _found, _source_root
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    show, other = w[90], w[91]
    with store:
        root = store.add_source(src)
        e1, x, e3 = (_found(language, data_dir, src, s, f"{s} 第{n:02d}話.srt", k) for k, (s, n) in
                     enumerate(((show, 1), (other, 1), (show, 3)), 1))
        store.take_in(root, [e1, x, e3])
        e1, x, e3 = (store.item_id(f["rel"]) for f in (e1, x, e3))
        store.move([e1], "arrivals")                          # (the look's order is its shows' names: set it)
        store.move([x], "arrivals", after_id=e1)
        store.move([e3], "arrivals", after_id=x)
        assert store.ids("arrivals") == [e1, x, e3]
        e2 = _found(language, data_dir, src, show, f"{show} 第02話.srt", 4)
        store.take_in(root, [e2])
        e2 = store.item_id(e2["rel"])
        assert store.ids("arrivals") == [e1, x, e2, e3], "in its row before the third, where the look put it"
        assert sorted(_tray(store)[0]) == sorted([(e1,), (x,), (e2, e3)])
        assert pieces_ok(store) is None


def test_the_anchor_read_goes_by_the_titles_index_never_a_walk_through_the_tier():
    """The review's B1: a title's last item before a new one is read by the title's index (items_work). Through the
    tier's order index it walks back over every earlier row for a title with none there — on a big take-in of one-file
    titles (setup's scan, a folder of films), one walk per file under the write lock (3,000: 3.3 s → 7.6 s)."""
    from tests.test_library_store_support import big_store
    store = big_store("ja", 200)
    plan = " ".join(r[-1] for r in store.conn.execute("EXPLAIN QUERY PLAN " + ls.ARRIVAL_ANCHOR_SQL, (1, 5.0, 5)))
    assert "items_work" in plan and "items_order" not in plan, plan
    store.close()

