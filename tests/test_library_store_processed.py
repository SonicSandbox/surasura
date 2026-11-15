"""A video dropped straight into `Processed` is titled by its show, never "Processed" (Kura-PR, 3.0.11; based on
Mattias's #449).

Why these matter: the YouTube downloader writes a single video's transcript directly into `data/<lang>/Processed`
(a playlist's videos go in a folder of their own below it). The store read `Processed` as a show's folder, so the
first channel's video made a title named "Processed" — and every later channel's single video joined it (its folder
key), one title holding many channels. A file directly in `Processed` is a loose drop now, as one in hato's drop
folder: titled by its record's show (the channel), else by its own name. What must not change: a playlist's folder
below `Processed` (still a title by its folder); a user's own show folder named `Processed` inside a tier folder or
`Library` (a show's, as before); a title already called "Processed" (never regrouped or renamed: the learner renames
it); the commands on the new titles (a drag, a move, Finished, Undo); and nothing on disk moves (S-R-1). Every test runs
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
    items — through a new channel's video, the same video handed over again and a disk sync (Sonic's choice: no quiet
    fix). A channel never seen is a title of its own; a channel already inside it still joins it by its record (its id
    or its name among the title's others, `_work_by_record`) — the known limit, a lean for him (register). Renaming it
    is the learner's (`rename_work`)."""
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


def _arrival_rows(store):
    """New arrivals as its tray draws it: one row per piece, its items in the tier's order."""
    rows = {}
    for item_id, piece in store.conn.execute("SELECT id, piece_id FROM items WHERE tier = 'arrivals' ORDER BY ord, id"):
        rows.setdefault(piece, []).append(item_id)
    return list(rows.values())


def _arrivals_on(store):
    with store._writing():
        store._set_meta({"arrivals_on": 1})


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_channels_video_added_after_another_channels_joins_its_row_in_new_arrivals(language):
    """Mattias's report (3.0.10): two channels, two videos each, added one after another (A, B, B, A) — B's two were
    one row, A's second a row of its own, titled by its video. A new arrival lands right after its title's last one
    there and joins its row: two rows, one a channel. Current's order is never touched."""
    store = migrated(language)
    _arrivals_on(store)
    data_dir, _u = roots(language)
    w = names(language)
    current = list(store.conn.execute("SELECT id, ord FROM items WHERE tier IN ('now', 'soon') ORDER BY id"))
    a1 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[81]} - {w[82]} [yuhZP5BnWWI].txt"),
                        _youtube("yuhZP5BnWWI", w[81])).added[0]
    b1 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[83]} - {w[84]} [ub05E5rev7E].txt"),
                        _youtube("ub05E5rev7E", w[83])).added[0]
    b2 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[83]} - {w[85]} [MQzFMVzOEc4].txt"),
                        _youtube("MQzFMVzOEc4", w[83])).added[0]
    a2 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[81]} - {w[86]} [HZ8bb5k22po].txt"),
                        _youtube("HZ8bb5k22po", w[81])).added[0]
    assert {store.item(i)["tier"] for i in (a1, b1, b2, a2)} == {"arrivals"}
    assert _arrival_rows(store) == [[a1, a2], [b1, b2]], "a channel's videos one row, in the order they came"
    assert list(store.conn.execute("SELECT id, ord FROM items WHERE tier IN ('now', 'soon') ORDER BY id")) == \
        current, "Current's order is the learner's"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_arrival_with_no_earlier_one_of_its_title_stays_where_it_came(language):
    store = migrated(language)
    _arrivals_on(store)
    data_dir, _u = roots(language)
    w = names(language)
    a1 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[81]} - {w[82]} [yuhZP5BnWWI].txt"),
                        _youtube("yuhZP5BnWWI", w[81])).added[0]
    b1 = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[83]} - {w[84]} [ub05E5rev7E].txt"),
                        _youtube("ub05E5rev7E", w[83])).added[0]
    assert _arrival_rows(store) == [[a1], [b1]], "each its own row, in the order they came"
    assert pieces_ok(store) is None
    store.close()
