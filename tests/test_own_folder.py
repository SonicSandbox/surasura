"""The folder a press opens for the library's items (a7, DIAGNOSIS 7; Sonic: "should be opening the location of the
content itself unless it doesn't exist") — `app/services/own_folder.py`, the one rule behind every *Open its folder*
and the pickers that look for a video or a book.

What a wrong answer would cost a learner:
  * *Open its folder* showing Surasura's own copy of the text (no video, no art, not where they keep the show) — the bug;
  * a gone show folder, or an unplugged drive, opening nothing, or an error, instead of the nearest folder there is;
  * a book's part opening nowhere, because its original is `<book>.epub#<n>`, not a file;
  * the picker for a gone copy starting outside the library, where the store refuses every file;
  * a stall on the window's thread (it runs on a worker; the read is one store call).

The real-store tests run a real source look (`sources.scan`) on a fresh store under the test's own root, with real
Japanese and Chinese subtitle text and EPUBs built from it (`tests/test_covers_own_folder.py`'s helpers), in nested
folders with non-ASCII names.
"""
import os
import shutil
import string

import pytest

from app import library_store as ls
from app.services import own_folder as F
from tests.test_covers_own_folder import SHELF, TITLES, Shelf, book, episodes
from tests.test_sources_scan import _fresh_module_state  # noqa: F401 (fixture: a fresh run of the app each test)


@pytest.fixture(params=["ja", "zh"])
def shelf(request):
    s = Shelf(request.param)
    yield s
    s.close()


def _ids_rels(shelf, title):
    rows = shelf.store.conn.execute("SELECT i.id, i.rel_path FROM items i JOIN works w ON w.id = i.work_id WHERE "
                                    "w.title LIKE ? ORDER BY i.id", (f"%{title}%",)).fetchall()
    assert rows, title
    return [r[0] for r in rows], [r[1] for r in rows]


# --- a real store -------------------------------------------------------------------------------------------------- #
def test_a_show_read_where_it_is_opens_its_own_folder_never_surasuras_copy(shelf):
    title = TITLES[shelf.language][0]
    folder = episodes(os.path.join(shelf.drive, *SHELF[shelf.language], title), title, shelf.language)
    shelf.read(shelf.drive)
    ids, rels = _ids_rels(shelf, title)
    copy = os.path.dirname(os.path.join(shelf.data_dir, *rels[0].split("/")))
    assert os.path.isdir(copy)                                   # the copy is there: the rule still passes it over
    assert os.path.normcase(F.find(shelf.store, shelf.data_dir, ids, rels)) == os.path.normcase(folder)


def test_a_gone_show_folder_opens_the_nearest_folder_above_it_that_is_there(shelf):
    title = TITLES[shelf.language][1]
    folder = episodes(os.path.join(shelf.drive, *SHELF[shelf.language], title), title, shelf.language)
    shelf.read(shelf.drive)
    ids, rels = _ids_rels(shelf, title)
    shutil.rmtree(folder)                                        # the user moved the show away
    above = os.path.join(shelf.drive, *SHELF[shelf.language])
    assert os.path.normcase(F.find(shelf.store, shelf.data_dir, ids, rels)) == os.path.normcase(above)


def test_a_books_part_opens_the_folder_its_epub_is_in(shelf):
    title = TITLES[shelf.language][0]
    path = book(os.path.join(shelf.drive, *SHELF[shelf.language], title, f"{title} 第1巻.epub"), title,
                shelf.language)
    shelf.read(shelf.drive)
    ids, rels = _ids_rels(shelf, f"{title} 第1巻")
    assert all("#" in o.origin for o in F.originals(shelf.store, ids))      # `<book>.epub#<n>`: never a folder
    assert os.path.normcase(F.find(shelf.store, shelf.data_dir, ids, rels)) == os.path.normcase(os.path.dirname(path))


def test_read_opens_its_own_handle_and_closes_it(shelf):
    title = TITLES[shelf.language][0]
    folder = episodes(os.path.join(shelf.drive, title), title, shelf.language)
    shelf.read(shelf.drive)
    ids, rels = _ids_rels(shelf, title)
    opener = Opener(shelf.store)
    assert os.path.normcase(F.read(opener, shelf.data_dir, ids, rels)) == os.path.normcase(folder)
    assert opener.calls == ["handle", "close"]


# --- the rule, on a store's records --------------------------------------------------------------------------------- #
class Store:
    def __init__(self, *origins, fails=False):
        self.found = {f"k{n}": o for n, o in enumerate(origins)}
        self.fails = fails
        self.asked = []

    def origins(self, items=None):
        self.asked.append(list(items))
        if self.fails:
            raise RuntimeError("database is locked")
        return {k: o for k, o in self.found.items() if o.item_id in items}


class Opener:
    mode = "store"

    def __init__(self, store):
        self.store, self.calls = store, []

    def handle(self):
        self.calls.append("handle")
        return self.store

    def close(self):
        self.calls.append("close")


def _origin(item_id, origin, video_path=None, version=None, moved_to=None):
    return ls.Origin(item_id, 1, origin, None, None, None, None, "available", None, version=version,
                     video_path=video_path, moved_to=moved_to)


def _library(tmp_path, rel):
    data = tmp_path / "データ"
    copy = data / os.path.dirname(rel)
    copy.mkdir(parents=True)
    return str(data), str(copy)


def test_a_gone_subtitle_folder_with_its_video_still_there_opens_the_videos_folder(tmp_path):
    data, _copy = _library(tmp_path, "Library/夜市小记/ep01.srt")
    videos = tmp_path / "動画" / "夜市小记"
    videos.mkdir(parents=True)
    store = Store(_origin(7, str(tmp_path / "字幕" / "夜市小记" / "ep01.srt"), video_path=str(videos / "ep01.mkv")))
    assert F.find(store, data, [7], ["Library/夜市小记/ep01.srt"]) == str(videos)


def test_an_unplugged_drive_falls_back_to_the_stored_copy(tmp_path):
    free = next((c for c in reversed(string.ascii_uppercase) if not os.path.exists(f"{c}:\\")), None)
    if os.name != "nt" or free is None:
        pytest.skip("needs a drive letter nothing is mounted on (Windows)")
    data, copy = _library(tmp_path, "Library/月影の旅人/第01話.srt")
    store = Store(_origin(3, f"{free}:\\アニメ\\月影の旅人\\第01話.srt"))
    assert F.find(store, data, [3], ["Library/月影の旅人/第01話.srt"]) == copy


def test_an_item_with_no_original_is_its_stored_copy_and_a_gone_copy_never_climbs_out_of_the_library(tmp_path):
    data, copy = _library(tmp_path, "Library/星降る喫茶店/01.txt")
    assert F.find(Store(), data, [1], ["Library/星降る喫茶店/01.txt"]) == copy        # Surasura 2's, a sample
    shutil.rmtree(copy)
    assert F.find(Store(), data, [1], ["Library/星降る喫茶店/01.txt"]) == os.path.join(data, "Library")
    shutil.rmtree(os.path.join(data, "Library"))
    assert F.find(Store(), data, [1], ["Library/星降る喫茶店/01.txt"]) == data          # never above it
    assert F.library_side(data, (), ("Library/星降る喫茶店",)) == data


def test_another_version_and_a_moved_original_are_never_opened(tmp_path):
    data, copy = _library(tmp_path, "Library/青河灯影/01.srt")
    other = tmp_path / "別版"
    moved = tmp_path / "移動前"
    other.mkdir()
    moved.mkdir()
    store = Store(_origin(5, str(other / "01.srt"), version=1), _origin(5, str(moved / "01.srt"), moved_to="x"))
    assert F.find(store, data, [5], ["Library/青河灯影/01.srt"]) == copy


def test_the_first_item_with_an_original_there_wins_in_the_order_asked(tmp_path):
    data, _copy = _library(tmp_path, "Library/x/01.srt")
    one, two = tmp_path / "一", tmp_path / "二"
    one.mkdir()
    two.mkdir()
    store = Store(_origin(2, str(two / "02.srt")), _origin(1, str(one / "01.srt")))
    assert F.find(store, data, [1, 2], []) == str(one)
    assert F.find(store, data, [2, 1], []) == str(two)


def test_an_unreadable_store_or_no_store_opens_the_librarys_side(tmp_path, capsys):
    data, copy = _library(tmp_path, "Library/月影/01.srt")
    assert F.find(Store(fails=True), data, [1], ["Library/月影/01.srt"]) == copy
    assert "couldn't be read" in capsys.readouterr().out
    assert F.find(None, data, [1], ["Library/月影/01.srt"]) == copy
    assert F.read(None, data, [1], ["Library/月影/01.srt"]) == copy
    no_store = Opener(None)
    no_store.mode = "manifest"                                   # Surasura 2's manifest: no store to read
    assert F.read(no_store, data, [1], ["Library/月影/01.srt"]) == copy and no_store.calls == []
