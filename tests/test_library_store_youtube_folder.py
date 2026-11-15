"""A channel is a folder: the YouTube downloader's `YouTube/<channel>/…` is one title per channel (Kura-PR2, 3.0.12;
the lead's lean, PROVISIONAL).

Why these matter: "Processed" is a 2.x name from before the downloads came in by themselves; a video dropped loose
there had no folder to be titled by, so the store read its channel from its record. Since 3.0.12 YouTube's downloads
go into their own folder, a folder a channel (a playlist's in a folder inside its channel's), read as the content
folder `Library` is: the channel's folder is the title. What a wrong answer would cost: a channel split into a title
per playlist (or one named by a path, `Channel/Playlist`), two channels in one title, a learner's own show folder
named `YouTube` read as the downloader's, or `Processed`'s old files (Extract's books, bilibili.tv's, a 3.0.11
library's loose videos) titled differently than before. Every test runs for Japanese and Chinese under the per-test
SURASURA_TEST_ROOT, with real words from tests/Test Resources/.
"""

import sys

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, names, pieces_ok, roots, touch


def _youtube(video, channel, playlist=None):
    """`app.qt.windows.youtube_record`'s record for one transcript (its channel: id and show; a list's place)."""
    record = {"schema": 1, "producer": "youtube", "language": "ja", "media_type": "youtube",
              "content_key": f"youtube:{video}", "video_id": video, "title": video,
              "channel_id": f"UC{channel}", "show": {"title": channel}}
    if playlist:
        record["playlist"] = playlist
    return record


def _titles(store):
    return dict(store.conn.execute("SELECT id, title FROM works"))


def _work(store, item_id):
    return store.item(item_id)["work_id"]


def test_the_channel_folder_alone_is_the_title_and_a_users_youtube_show_folder_stays_his():
    """`YouTube/<channel>/x` and `YouTube/<channel>/<playlist>/x` are one folder key, the channel's — the same key as
    `Library/<channel>` (one rule: a show's folder is its title wherever Surasura keeps it; `sources._is_shown` reads
    a channel's videos so). A file directly in `YouTube` is loose (titled by its record). `YouTube` inside a tier
    folder is a learner's own show folder. Compared as the file system reads it (NTFS / APFS: any case)."""
    ch = names("ja")[81]
    key = ls.path_key(ch)
    assert ls.folder_key_of(f"{ls.YOUTUBE_FOLDER}/{ch}/{ch} - x [pitFobM6z80].txt") == key
    assert ls.folder_key_of(f"{ls.YOUTUBE_FOLDER}/{ch}/リスト/x [pitFobM6z80].txt") == key
    assert ls.folder_key_of(f"{ls.YOUTUBE_FOLDER}/{ch}/リスト/S01/x.txt") == key
    assert ls.folder_key_of(f"{ls.CONTENT_FOLDER}/{ch}/x.srt") == key
    assert ls.folder_key_of(f"{ls.YOUTUBE_FOLDER}/x [pitFobM6z80].txt") is None
    assert ls.folder_key_of(f"./{ls.YOUTUBE_FOLDER}/{ch}/x.txt") == key
    assert ls.folder_key_of(f"HighPriority/{ls.YOUTUBE_FOLDER}/x.srt") == ls.path_key(ls.YOUTUBE_FOLDER)
    folded = ls.folder_key_of(f"youtube/{ch}/x.txt")
    assert (folded == key) == (sys.platform in ("win32", "darwin"))
    assert ls.YOUTUBE_FOLDER not in ls.WALK_FOLDERS, "the downloader hands its files over; never walked"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("playlist_first", (False, True))
def test_a_channels_videos_and_its_playlist_are_one_title_named_by_the_channel(language, playlist_first):
    """A channel's single video and a playlist's video (in its folder inside the channel's), in either order, are one
    title named by the channel; another channel's video is another title; a third video of the first channel joins
    its title. No title named by a path or after the downloader's folder."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    a, b = w[81], w[83]
    single = (f"{ls.YOUTUBE_FOLDER}/{a}/{a} - {w[82]} [pitFobM6z80].txt", _youtube("pitFobM6z80", a))
    listed = (f"{ls.YOUTUBE_FOLDER}/{a}/{w[84]}/{a} - {w[85]} [IIqUltT_x0c].txt",
              _youtube("IIqUltT_x0c", a, {"id": "PLx", "index": 1}))
    first, second = (listed, single) if playlist_first else (single, listed)
    one = store.register(touch(data_dir, first[0]), first[1]).added[0]
    two = store.register(touch(data_dir, second[0]), second[1]).added[0]
    other = store.register(touch(data_dir, f"{ls.YOUTUBE_FOLDER}/{b}/{b} - {w[86]} [Qm3vR8LwZ1o].txt"),
                           _youtube("Qm3vR8LwZ1o", b)).added[0]
    third = store.register(touch(data_dir, f"{ls.YOUTUBE_FOLDER}/{a}/{a} - {w[87]} [Zx9pQ2mN4rT].txt"),
                           _youtube("Zx9pQ2mN4rT", a)).added[0]
    titles = _titles(store)
    assert _work(store, one) == _work(store, two) == _work(store, third) != _work(store, other)
    assert titles[_work(store, one)] == a and titles[_work(store, other)] == b
    assert not [t for t in titles.values() if "/" in t or t in (ls.YOUTUBE_FOLDER, ls.PROCESSED_FOLDER)]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_processed_reads_as_before_for_extracts_books_and_old_loose_videos(language):
    """Nothing about `Processed` changes: a file directly in it is still a loose drop titled by its record's show
    (3.0.11's rule, for bilibili.tv's and a library's older videos), a folder below it still a title of its own
    (Extract's `Processed/<book>/`, a 3.0.11 playlist's)."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    loose = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[81]} - {w[82]} [pitFobM6z80].txt"),
                           _youtube("pitFobM6z80", w[81])).added[0]
    book = store.insert([touch(data_dir, f"{ls.PROCESSED_FOLDER}/{w[88]}/{w[88]}_01.txt")], "now").added[0]
    assert _titles(store)[_work(store, loose)] == w[81]
    assert ls.folder_key_of(f"{ls.PROCESSED_FOLDER}/{w[88]}/{w[88]}_01.txt") == ls.path_key(f"Processed/{w[88]}")
    assert _titles(store)[_work(store, book)] != _titles(store)[_work(store, loose)]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_channel_folders_title_is_the_channels_own_name_never_its_folders(language):
    """A channel's name a folder can't hold (`ハチ: 公式 | Music` → the folder `ハチ 公式  Music`): its first video's new
    title is the channel's name from its record, the folder's among its other titles (search finds both); the next
    video of the channel, and one of its playlist, join it."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    name, folder = f"{w[81]}: {w[82]} | Music", f"{w[81]} {w[82]}  Music"
    one = store.register(touch(data_dir, f"{ls.YOUTUBE_FOLDER}/{folder}/{folder} - {w[83]} [pitFobM6z80].txt"),
                         _youtube("pitFobM6z80", name)).added[0]
    two = store.register(touch(data_dir, f"{ls.YOUTUBE_FOLDER}/{folder}/{w[84]}/{folder} - {w[85]} [IIqUltT_x0c].txt"),
                         _youtube("IIqUltT_x0c", name, {"id": "PLx", "index": 1})).added[0]
    work = _work(store, one)
    assert _work(store, two) == work and _titles(store)[work] == name
    assert work in store.search(folder)[0] and work in store.search(name)[0]
    store.close()
