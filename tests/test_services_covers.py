"""Covers from disk (W3.2 S5): `app/services/covers.py`.

What a wrong answer would cost a learner:
  * the cover they chose themselves replaced by a poster the scan found (their choice is locked: never written over), or
    a better cover (AniList's) replaced by a lesser one;
  * a OneDrive / iCloud online-only file downloaded just to look at it (N4), on a laptop's metered connection;
  * a broken image shown as a title's cover instead of the generated one;
  * one loose file's art painted on every loose file of the tier;
  * a book's cover copied into the cache again at every scan, or never coming back after *Remove downloaded covers* (N5);
  * the image they picked lost when they pick another (no dated backup), or an Undo that shows nothing.

Each runs on a real migrated store (Japanese and Chinese show names from tests/Test Resources) through the window's
writer, under the test's own root; the images are real (a baseline JPEG and a PNG written byte by byte), the EPUBs built
with EbookLib (the shipped dependency) in the test's folder.
"""
import os
import struct
import threading
import time
import zlib

import pytest

from app import library_store as ls
from app import path_utils
from app.qt.strings import MOVE_WORDS as WORDS
from app.services import covers as C
from app.services import moves as M
from tests import services_helpers as h
from tests.test_library_store_support import migrated, names, roots


# --- real images, byte by byte ------------------------------------------------------------------------------------ #
def jpeg(width=16, height=24):
    """A baseline JPEG of mid grey (any decoder reads it: one Huffman code each for DC 0 and end-of-block)."""
    def seg(marker, body):
        return b"\xff" + bytes([marker]) + struct.pack(">H", len(body) + 2) + body
    one = bytes([1] + [0] * 15)
    out = (b"\xff\xd8" + seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00") + seg(0xDB, b"\x00" + bytes([1] * 64))
           + seg(0xC0, b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00")
           + seg(0xC4, b"\x00" + one + b"\x00") + seg(0xC4, b"\x10" + one + b"\x00") + seg(0xDA, b"\x01\x01\x00\x00\x3f\x00"))
    bits = "00" * (-(-width // 8) * -(-height // 8))
    bits += "1" * (-len(bits) % 8)
    return out + bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)) + b"\xff\xd9"


def png(width=4, height=6, rgb=(200, 60, 90)):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def epub(path, title, cover=None, language="ja"):
    """A small real book (EbookLib), with `cover` (bytes) as its cover image when given."""
    from ebooklib import epub as E
    book = E.EpubBook()
    book.set_identifier(f"surasura-covers-{title}")
    book.set_title(title)
    book.set_language(language)
    if cover is not None:
        book.set_cover("images/cover.jpg", cover)
    ch = E.EpubHtml(title=title, file_name="c1.xhtml", lang=language)
    ch.content = f"<html><body><p>{title}</p></body></html>"
    book.add_item(ch)
    book.add_item(E.EpubNcx())
    book.add_item(E.EpubNav())
    book.spine = ["nav", ch]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    E.write_epub(path, book)
    return path


# --- the library and its writer ---------------------------------------------------------------------------------- #
class Heard:
    def __init__(self):
        self.saved, self.notes, self.undone = [], [], []
        self.rereads = 0

    def kw(self):
        def reread():
            self.rereads += 1
        return dict(on_saved=lambda c, label: self.saved.append(c), on_note=self.notes.append, on_reread=reread,
                    on_undone=lambda c, label: self.undone.append(c))


class Library:
    def __init__(self, language):
        self.language = language
        self.store = migrated(language)
        self.data_dir, self.user_files_dir = roots(language)
        self.heard = Heard()
        self.writer = M.Writer(ls.StoreOpener(language, self.data_dir, self.user_files_dir, role="window"), language,
                               journal_file=M.journal_path(language), retry=0.05, words=WORDS, **self.heard.kw())
        self.writer.start()

    def works(self):
        feed = self.store.read_feed()
        return C.works_from(feed["items"], feed["works"])

    def work_of(self, item_id):
        return self.store.item(item_id)["work_id"]

    def one(self, work_id):
        return next(w for w in self.works() if w.id == work_id)

    def row(self, work_id):
        r = self.store._work_row(work_id)
        return r["cover_source"], r["cover_ref"], r["cover_path"], r["cover_locked"]

    def folder_of(self, item_id):
        return os.path.dirname(os.path.join(self.data_dir, *self.store.item(item_id)["rel_path"].split("/")))

    def rel(self, path):
        return os.path.relpath(path, self.data_dir).replace("\\", "/")

    def scan(self, works=None, **kw):
        """A scan, then every cover it handed on landed (the writer's thread is idle)."""
        before = len(self.heard.saved) + self.heard.rereads
        n = C.scan(self.language, self.works() if works is None else works, self.writer, data_dir=self.data_dir, **kw)
        assert h.until(lambda: len(self.heard.saved) + self.heard.rereads >= before + n and not self.writer.pending())
        return n

    def close(self):
        self.writer.finish(time.monotonic() + 5)
        self.store.close()


@pytest.fixture(params=["ja", "zh"])
def lib(request):
    library = Library(request.param)
    yield library
    library.close()


def _cache_files():
    folder = path_utils.get_covers_cache_path()
    return sorted(n for n in os.listdir(folder) if not n.endswith(".part"))


# --- art beside the files ---------------------------------------------------------------------------------------- #
def test_a_poster_beside_a_shows_episodes_is_its_cover_read_where_it_is_and_a_second_scan_adds_nothing(lib):
    show = lib.store.ids("now")[0]
    poster = write(os.path.join(lib.folder_of(show), "poster.jpg"), jpeg())
    work = lib.work_of(show)
    assert lib.scan() == 1
    assert lib.row(work) == ("file", lib.rel(poster), None, 0), "read in place: no copy, nothing in the cache"
    assert os.path.normcase(C.image_path(lib.language, lib.one(work), lib.data_dir)) == os.path.normcase(poster)
    assert _cache_files() == []
    assert lib.scan() == 0, "recorded already: not handed on again"
    others = [w for w in lib.works() if w.id != work]
    assert all(w.cover_source is None for w in others), "another show's folder holds no art: the generated cover"


def test_cover_beats_poster_beats_folder_whatever_the_case_of_the_name(lib):
    show = lib.store.ids("soon")[0]
    folder = lib.folder_of(show)
    write(os.path.join(folder, "folder.jpg"), jpeg())
    write(os.path.join(folder, "POSTER.PNG"), png())
    best = write(os.path.join(folder, "Cover.JPG"), jpeg(40, 60))
    lib.scan()
    assert lib.row(lib.work_of(show))[:2] == ("file", lib.rel(best))


def test_a_season_folder_takes_the_shows_art_one_level_up_and_a_tier_folders_art_is_no_loose_files(lib):
    title = names(lib.language)[40]
    season = os.path.join(lib.data_dir, ls.FOLDER_OF_TIER["now"], title, "Season 2")
    eps = [write(os.path.join(season, f"[Group] {title} - {n:02d}.ja.srt"), f"{title} {n}\n".encode("utf-8"))
           for n in (1, 2)]
    lib.store.insert(eps, "now")
    art = write(os.path.join(lib.data_dir, ls.FOLDER_OF_TIER["now"], title, "folder.jpg"), jpeg())
    tier_art = write(os.path.join(lib.data_dir, ls.FOLDER_OF_TIER["now"], "cover.jpg"), jpeg())
    lib.scan()
    work = lib.work_of(lib.store.item_id(lib.rel(eps[0])))
    assert lib.row(work)[:2] == ("file", lib.rel(art))
    loose = [i for i in lib.store.ids("now") + lib.store.ids("soon")
             if "/" not in lib.store.item(i)["rel_path"].split("/", 1)[1]]
    assert loose, "the migrated library has loose files in its tiers' own folders"
    assert all(lib.row(lib.work_of(i))[0] is None for i in loose), f"{tier_art} is no loose file's cover"


def test_a_broken_or_renamed_file_is_passed_over_and_with_nothing_else_the_generated_cover_stays(lib):
    show = lib.store.ids("now")[0]
    folder = lib.folder_of(show)
    write(os.path.join(folder, "cover.jpg"), "これは画像ではない\n".encode("utf-8"))      # a text file renamed
    write(os.path.join(folder, "poster.jpg"), jpeg()[:60])                                # a download cut short
    assert lib.scan() == 0
    assert lib.row(lib.work_of(show))[0] is None
    good = write(os.path.join(folder, "folder.png"), png())
    assert lib.scan() == 1
    assert lib.row(lib.work_of(show))[:2] == ("file", lib.rel(good))


def test_N4_a_cloud_placeholder_is_never_opened_so_nothing_downloads(lib, monkeypatch):
    """The OneDrive / iCloud attribute (RECALL_ON_DATA_ACCESS) faked on the poster and on a book: neither is opened."""
    show = lib.store.ids("now")[0]
    folder = lib.folder_of(show)
    poster = write(os.path.join(folder, "poster.jpg"), jpeg())
    book = epub(os.path.join(lib.folder_of(lib.store.ids("soon")[0]), "本.epub"), "本", cover=jpeg())
    real_stat = os.stat
    clouded = {os.path.normcase(poster), os.path.normcase(book)}

    class Stat:
        def __init__(self, st):
            self._st = st
            self.st_file_attributes = 0x400000

        def __getattr__(self, name):
            return getattr(self._st, name)

    def stat(path, *a, **k):
        st = real_stat(path, *a, **k)
        return Stat(st) if os.path.normcase(os.fspath(path)) in clouded else st
    opened = []
    real_open = open
    monkeypatch.setattr(C.os, "stat", stat)
    monkeypatch.setattr(C, "open", lambda p, *a, **k: (opened.append(p), real_open(p, *a, **k))[1], raising=False)
    monkeypatch.setattr(C.zipfile, "ZipFile", lambda *a, **k: opened.append(a[0]) or pytest.fail("a book was opened"))
    assert lib.scan() == 0
    assert opened == [] and lib.row(lib.work_of(show))[0] is None


# --- an EPUB's own cover ------------------------------------------------------------------------------------------ #
def test_an_epubs_cover_is_copied_into_the_cache_once_and_comes_back_after_remove_downloaded_covers(lib):
    item = lib.store.ids("soon")[0]
    work = lib.work_of(item)
    title = names(lib.language)[1]
    picture = jpeg(30, 45)
    book = epub(os.path.join(lib.folder_of(item), f"{title}.epub"), title, cover=picture, language=lib.language)
    assert lib.scan() == 1
    source, ref, path, locked = lib.row(work)
    assert (source, ref, locked) == ("file", lib.rel(book), 0) and path.startswith("cache:")
    name = path[len("cache:"):]
    assert title not in name and os.sep not in name, "named by a hash, never the user's path"
    cached = os.path.join(path_utils.get_covers_cache_path(), name)
    with open(cached, "rb") as f:
        assert f.read() == picture
    stamp = os.stat(cached).st_mtime_ns
    assert lib.scan() == 0 and _cache_files() == [name] and os.stat(cached).st_mtime_ns == stamp, "copied ONCE"
    assert lib.store.forget_downloaded_covers() == [work]           # *Remove downloaded covers*
    os.remove(cached)                                               # (the window empties the cache folder)
    assert lib.row(work)[2] is None
    assert lib.scan() == 1, "a disk cover comes back by itself (N5)"
    assert lib.row(work)[2] == path and os.path.isfile(cached)


def test_a_changed_book_is_this_same_disk_source_and_its_new_cover_replaces_the_old(lib):
    item = lib.store.ids("goal")[0]
    work = lib.work_of(item)
    path = os.path.join(lib.folder_of(item), "巻一.epub")
    epub(path, "巻一", cover=jpeg())
    lib.scan()
    first = lib.row(work)[2]
    time.sleep(0.01)
    epub(path, "巻一", cover=png())
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
    assert lib.scan() == 1
    second = lib.row(work)[2]
    assert second != first and second.endswith(".png")


def test_an_epub_without_a_cover_leaves_the_generated_cover(lib):
    item = lib.store.ids("now")[4]
    epub(os.path.join(lib.folder_of(item), "表紙なし.epub"), "表紙なし")
    assert lib.scan() == 0 and lib.row(lib.work_of(item))[0] is None and _cache_files() == []


def test_a_book_at_its_import_keeps_its_cover_from_wherever_the_user_keeps_it(lib, tmp_path):
    work = lib.work_of(lib.store.ids("now")[0])
    book = epub(str(tmp_path / "Downloads" / "進撃の巨人 1.epub"), "進撃の巨人", cover=png())
    assert C.keep_epub_cover(lib.language, work, book, lib.writer, data_dir=lib.data_dir)
    assert h.until(lambda: lib.heard.rereads and not lib.writer.pending())
    assert lib.heard.saved == [] and not lib.writer.can_undo(), "B1: a book's cover is nobody's to undo"
    source, ref, path, _locked = lib.row(work)
    assert (source, ref) == ("file", "進撃の巨人 1.epub") and path.startswith("cache:"), "its name, never its path"
    assert os.path.isfile(C.image_path(lib.language, lib.one(work), lib.data_dir))


# --- never over a better or the user's cover --------------------------------------------------------------------- #
def test_a_locked_user_cover_and_a_fetched_anilist_cover_are_never_written_over_by_disk_art(lib, tmp_path):
    mine, fetched = lib.work_of(lib.store.ids("now")[0]), lib.work_of(lib.store.ids("soon")[0])
    picked = write(str(tmp_path / "Pictures" / "お気に入り.png"), png())
    kept = C.keep_user_image(lib.language, mine, picked, lib.writer)
    lib.writer.set_cover(fetched, "anilist", ref="16498", path="cache:anilist_16498.jpg")
    assert h.until(lambda: len(lib.heard.saved) == 2)
    for item in (lib.store.ids("now")[0], lib.store.ids("soon")[0]):
        write(os.path.join(lib.folder_of(item), "poster.jpg"), jpeg())
    assert lib.scan() == 0
    assert lib.row(mine) == ("user", None, kept, 1)
    assert lib.row(fetched) == ("anilist", "16498", "cache:anilist_16498.jpg", 0)


def test_use_a_generated_cover_is_the_users_choice_too_and_no_poster_replaces_it(lib):
    item = lib.store.ids("goal")[0]
    work = lib.work_of(item)
    lib.writer.set_cover(work, "generated", locked=True)             # *Use a generated cover*
    assert h.until(lambda: lib.heard.saved)
    write(os.path.join(lib.folder_of(item), "cover.jpg"), jpeg())
    assert lib.scan() == 0, "never even handed on"
    assert lib.row(work) == ("generated", None, None, 1)


def test_another_disk_cover_stays_until_its_file_is_gone(lib):
    item = lib.store.ids("now")[0]
    work = lib.work_of(item)
    folder = lib.folder_of(item)
    poster = write(os.path.join(folder, "poster.jpg"), jpeg())
    lib.scan()
    sub = write(os.path.join(folder, "extras", "cover.jpg"), jpeg())             # not beside the files: never seen
    assert lib.scan() == 0 and lib.row(work)[1] == lib.rel(poster)
    os.remove(poster)                                                          # (the test's own file)
    os.remove(sub)
    best = write(os.path.join(folder, "folder.jpg"), jpeg())
    assert lib.scan() == 1 and lib.row(work)[1] == lib.rel(best)


# --- the user's own image (IK-7) --------------------------------------------------------------------------------- #
def test_the_users_image_is_kept_as_user_data_the_one_it_replaces_backed_up_dated_and_undo_shows_it_again(lib,
                                                                                                         tmp_path):
    work = lib.work_of(lib.store.ids("now")[0])
    first = C.keep_user_image(lib.language, work, write(str(tmp_path / "一枚目.jpg"), jpeg()), lib.writer)
    assert h.until(lambda: len(lib.heard.saved) == 1)
    folder = os.path.join(path_utils.get_user_files_path(lib.language), "covers")
    assert first.startswith("user:") and os.path.isfile(os.path.join(folder, first[5:]))
    second = C.keep_user_image(lib.language, work, write(str(tmp_path / "二枚目.png"), png()), lib.writer,
                               current=lib.row(work)[2])
    assert h.until(lambda: len(lib.heard.saved) == 2)
    assert lib.row(work) == ("user", None, second, 1) and second != first
    backups = os.listdir(os.path.join(folder, ".trash"))
    stem = os.path.splitext(first[5:])[0]
    assert len(backups) == 1 and backups[0].startswith(stem + "."), "a dated backup of the one it replaced"
    with open(os.path.join(folder, ".trash", backups[0]), "rb") as f:
        assert f.read() == jpeg()
    lib.writer.undo()
    assert h.until(lambda: lib.heard.undone)
    assert lib.row(work)[2] == first and os.path.isfile(C.image_path(lib.language, lib.one(work)))


def test_a_chosen_file_that_isnt_an_image_records_nothing(lib, tmp_path):
    work = lib.work_of(lib.store.ids("now")[0])
    text = write(str(tmp_path / "メモ.png"), "画像ではありません\n".encode("utf-8"))
    assert C.keep_user_image(lib.language, work, text, lib.writer) is None
    assert C.keep_user_image(lib.language, work, str(tmp_path / "無い.png"), lib.writer) is None
    assert lib.row(work)[0] is None and not lib.writer.pending()


# --- the scan's own rules ---------------------------------------------------------------------------------------- #
class Refusing:
    """A writer on a store that can't be written (E4)."""
    def __init__(self):
        self.calls = []

    def can_write(self):
        return False

    def set_cover(self, *a, **k):
        self.calls.append(a)


def test_E4_a_store_that_cant_be_written_gets_nothing_and_nothing_is_read(lib, monkeypatch):
    write(os.path.join(lib.folder_of(lib.store.ids("now")[0]), "poster.jpg"), jpeg())
    monkeypatch.setattr(C, "art_beside", lambda *a: pytest.fail("read for a store that can't take it"))
    refusing = Refusing()
    assert C.scan(lib.language, lib.works(), refusing, data_dir=lib.data_dir) == 0 and refusing.calls == []
    assert C.keep_user_image(lib.language, 1, __file__, refusing) is None


def test_the_scan_stops_between_works_when_cancelled(lib):
    for tier in ("now", "soon", "goal"):
        write(os.path.join(lib.folder_of(lib.store.ids(tier)[0]), "poster.jpg"), jpeg())
    asked = []

    def cancel():
        asked.append(1)
        return len(asked) > 1
    assert lib.scan(cancel=cancel) == 1, "the first work only"


def test_one_works_trouble_never_stops_the_rest(lib, monkeypatch):
    for tier in ("now", "soon"):
        write(os.path.join(lib.folder_of(lib.store.ids(tier)[0]), "poster.jpg"), jpeg())
    works = lib.works()
    broken = C.Work(works[0].id, None, None, None, None, False)      # no file list: raises inside its own turn
    assert lib.scan([broken] + works) == 2


# --- the scan and the user's own moves (B1, S4) ---------------------------------------------------------------- #
def test_B1_a_scan_never_reaches_the_users_undo_so_ctrl_z_after_it_still_takes_back_their_move(lib):
    """B1: every cover the scan recorded went on the Undo stack (40 deep) and through `on_saved` — Ctrl+Z then took back
    a cover nobody chose, and the user's own move fell off the stack. A scan's covers are background: a reread only."""
    goal = lib.store.ids("goal")
    lib.writer.move([goal[5]], "goal", before_id=goal[0], label="moved up")
    assert h.until(lambda: lib.heard.saved and not lib.writer.pending())
    for tier in ("now", "soon", "goal"):
        write(os.path.join(lib.folder_of(lib.store.ids(tier)[0]), "poster.jpg"), jpeg())
    rereads = lib.heard.rereads
    assert lib.scan() == 3
    assert lib.heard.rereads == rereads + 3 and len(lib.heard.saved) == 1, "a reread each, no toast"
    assert len(lib.writer._undo) == 1 and not os.path.exists(M.journal_path(lib.language)), "never journalled"
    lib.writer.undo()
    assert h.until(lambda: lib.heard.undone)
    assert lib.store.ids("goal") == goal, "Ctrl+Z took back the user's move"
    assert all(lib.row(lib.work_of(lib.store.ids(t)[0]))[0] == "file" for t in ("now", "soon")), "the covers stay"


def test_S4_a_drop_given_during_a_200_title_scan_lands_before_the_scan_ends(lib):
    """S4 (G1): the scan handed its 200 covers on at once — the user's drop waited behind all of them (and a held or
    busy queue rewrote the journal at each). Paced, the scan hands on its next cover only once nothing is queued: a
    drop given meanwhile lands next. Held first (a drag): the scan waits with one cover queued."""
    name = names(lib.language)
    folder = ls.FOLDER_OF_TIER["goal"]
    files = []
    for k in range(200):
        show = os.path.join(lib.data_dir, folder, f"{name[k % len(name)]} {k:03d}")
        files.append(write(os.path.join(show, f"{name[k % len(name)]} 第01話.srt"),
                           f"{name[k % len(name)]}\n".encode("utf-8")))
        write(os.path.join(show, "poster.jpg"), jpeg())
    had = {w.id for w in lib.works()}
    lib.store.insert(files, "goal", "top")
    works = [w for w in lib.works() if w.id not in had]
    assert len(works) == 200
    order = []
    lib.writer.after_commit = lambda change, op: order.append(op)
    lib.writer.hold()                                   # a drag: nothing lands until it ends
    found = []
    scan = threading.Thread(target=lambda: found.append(C.scan(lib.language, works, lib.writer,
                                                                data_dir=lib.data_dir)), daemon=True)
    scan.start()
    assert h.until(lambda: lib.writer.pending() >= 1)
    scan.join(2)                                        # the old scan queued all 200 meanwhile; the paced one waits
    assert lib.writer.pending() == 1, "one cover queued at a time"
    goal = lib.store.ids("goal")
    lib.writer.move([goal[-1]], "goal", before_id=goal[0], label="the drop")
    lib.writer.release()
    scan.join(120)
    assert not scan.is_alive() and found == [200]
    assert h.until(lambda: not lib.writer.pending() and len(order) == 201)
    assert order.index("move") == 1, "the drop landed right after the cover in hand, before the other 199"
    assert lib.store.ids("goal")[0] == goal[-1]


def test_a_record_naming_a_path_outside_its_folder_resolves_to_nothing():
    for path in ("cache:../../KnownWord.json", "user:..\\x.png", "cache:", "user:a/b.png"):
        assert C.image_path("ja", C.Work(1, (), "user", None, path, True), data_dir="/") is None


@pytest.mark.parametrize("data, ext", [(jpeg(), ".jpg"), (png(), ".png"), (jpeg()[:-30], None),
                                       (png()[:-12], None), ("サムネイル".encode("utf-8") * 10, None), (b"", None)])
def test_an_image_is_known_by_its_bytes_whole_never_by_its_name(data, ext):
    assert C.image_ext(data) == ext
