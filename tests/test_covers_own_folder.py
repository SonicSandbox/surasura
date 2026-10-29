"""Covers from the user's own folders (Hon a6, the lead's Inbox 2026-10-29): a folder Surasura reads where it is keeps
its books' EPUBs and its shows' art there — only the text is copied into the library — so the cover scan looks beside
the originals too (`app/services/covers.py`: `originals`, `works_from(..., own)`, `scan`), and so does the online
fetcher's disk-first look (`covers_online.wants_for`).

What a wrong answer would cost a learner:
  * every book read from their own shelf shown with a generated cover although its EPUB has one (the bug);
  * the poster beside their own episodes never shown, or AniList's picture shown in its place;
  * one picture in a folder of many shows' loose files painted on every one of them;
  * a folder they stopped reading, or a drive they unplugged, still read (or the scan stalling on it);
  * anything written, renamed or touched in their own folders;
  * the whole library read again at every open (each folder is looked at once, a recorded cover isn't handed on again).

Each runs a real source look (`sources.scan`) on a fresh store, under the test's own root, with real Japanese and
Chinese text from tests/Test Resources/ (there is no EPUB file there: each book is built with EbookLib, the shipped
dependency, from that text), made-up titles, nested folders with non-ASCII names, and real images written byte by byte.
"""
import os
import time

import pytest

from app import extract
from app import library_store as ls
from app.qt.strings import MOVE_WORDS as WORDS
from app.services import covers as C
from app.services import covers_online as O
from app.services import moves as M
from tests import services_helpers as h
from tests.test_covers_online import anilist, blocked, fetcher  # noqa: F401 (fixtures: the fake AniList, the guard)
from tests.test_library_store_support import RESOURCES, roots
from tests.test_services_covers import Heard, jpeg, png, write
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _text, _tree, _video  # noqa: F401

TITLES = {"ja": ("月影の旅人", "星降る喫茶店"), "zh": ("夜市小记", "青河灯影")}     # made-up titles
SHELF = {"ja": ("本棚", "ライトノベル"), "zh": ("书架", "轻小说")}               # nested, non-ASCII


def _prose(language, chars):
    with open(os.path.join(RESOURCES, language, "context_test.txt"), encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    out, n = [], 0
    while n < chars:
        out.append(lines[len(out) % len(lines)])
        n += len(out[-1])
    return "".join(f"<p>{ln}</p>" for ln in out)


def book(path, title, language, cover=None):
    """A small real book (EbookLib): three chapters of real text, `cover` (bytes) as its cover image when given, its
    time a minute back (a look waits for a file still being written)."""
    from ebooklib import epub as E
    b = E.EpubBook()
    b.set_identifier(f"surasura-own-folder-{title}")
    b.set_title(title)
    b.set_language(language)
    if cover is not None:
        b.set_cover("images/cover.jpg", cover)
    chapters = []
    for n in range(1, 4):
        ch = E.EpubHtml(title=f"第{n}章", file_name=f"c{n}.xhtml", lang=language)
        ch.content = f"<html><body><h2>第{n}章</h2><p>{title}</p>{_prose(language, 1200)}</body></html>"  # its own
        b.add_item(ch)
        chapters.append(ch)
    b.toc = chapters
    b.add_item(E.EpubNcx())
    b.add_item(E.EpubNav())
    b.spine = ["nav"] + chapters
    os.makedirs(os.path.dirname(path), exist_ok=True)
    E.write_epub(path, b)
    t = time.time() - 120
    os.utime(path, (t, t))
    return path


def episodes(folder, show, language, n=2):
    """A show's episodes as a user keeps them: a video and its subtitle side by side (real subtitle text)."""
    for e in range(1, n + 1):
        stem = os.path.join(folder, f"[Grp] {show} - {e:02d}")
        _video(stem + ".mkv", body=b"\x1a\x45\xdf\xa3 fake matroska %d %s" % (e, show.encode("utf-8")))
        path = stem + ".srt"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_text(language, 0, extra=f" {show} {e}"))
        t = time.time() - 120
        os.utime(path, (t, t))
    return folder


class Shelf:
    """A fresh 3.0 library (setup's start), the window's writer on it, and a "second drive" the user keeps things on."""

    def __init__(self, language):
        self.language = language
        self.store, self.data_dir = _empty(language)
        _data, self.user_files_dir = roots(language)
        self.heard = Heard()
        self.writer = M.Writer(ls.StoreOpener(language, self.data_dir, self.user_files_dir, role="window"), language,
                               journal_file=M.journal_path(language), retry=0.05, words=WORDS, **self.heard.kw())
        self.writer.start()
        self.drive = _drive("ユーザーの棚")

    def read(self, folder):
        """The user points Surasura at `folder`: a source, looked at once (nothing written under it: `_look`)."""
        root = self.store.add_source(folder)
        result = _look(self.store, self.language, root, first=True)
        assert result["added"], result
        return root

    def works(self, ids=None):
        feed = self.store.read_feed()
        return C.works_from(feed["items"], feed["works"], C.originals(self.store, ids))

    def work_titled(self, title):
        """The work named `title` (a season folder's: `<show>/Season 2`)."""
        return next(w for w in self.works() if self.store._work_row(w.id)["title"].split("/")[0] == title)

    def row(self, work_id):
        r = self.store._work_row(work_id)
        return r["cover_source"], r["cover_ref"], r["cover_path"], r["cover_locked"]

    def scan(self):
        """The open's scan, then every cover it handed on landed — proving nothing under the drive changed."""
        before_tree = _tree(self.drive)
        before = len(self.heard.saved) + self.heard.rereads
        n = C.scan(self.language, self.works(), self.writer, data_dir=self.data_dir)
        assert h.until(lambda: len(self.heard.saved) + self.heard.rereads >= before + n and not self.writer.pending())
        assert _tree(self.drive) == before_tree, "the cover scan wrote under the user's folder"
        return n

    def close(self):
        self.writer.finish(time.monotonic() + 5)
        self.store.close()


@pytest.fixture(params=["ja", "zh"])
def shelf(request):
    s = Shelf(request.param)
    yield s
    s.close()


def _cached_bytes(shelf, work_id):
    w = next(w for w in shelf.works() if w.id == work_id)
    with open(C.image_path(shelf.language, w, shelf.data_dir), "rb") as f:
        return f.read()


# --- books -------------------------------------------------------------------------------------------------------- #
def test_a_book_read_from_the_users_own_nested_folder_shows_its_epubs_cover(shelf):
    """The bug: the EPUB stays on the user's shelf (only its parts are copied in), and its cover is found there —
    copied once into the covers cache, recorded against the EPUB's own path; a second open hands nothing on again."""
    title = TITLES[shelf.language][0]
    cover = jpeg(20, 30)
    path = book(os.path.join(shelf.drive, *SHELF[shelf.language], title, f"{title} 第1巻.epub"), title,
                shelf.language, cover=cover)
    shelf.read(shelf.drive)
    work = shelf.work_titled(f"{title} 第1巻")
    assert work.own_books == (path,) and work.own_folders == (os.path.dirname(path),)
    assert shelf.scan() == 1
    source, ref, cache, locked = shelf.row(work.id)
    assert (source, ref, locked) == ("file", path, 0) and cache.startswith("cache:")
    assert _cached_bytes(shelf, work.id) == cover
    assert shelf.scan() == 0, "recorded: the next open hands nothing on"


def test_a_book_whose_epub_has_no_cover_keeps_the_generated_one(shelf):
    title = TITLES[shelf.language][1]
    book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language)
    shelf.read(shelf.drive)
    work = shelf.work_titled(title)
    assert work.own_books and shelf.scan() == 0
    assert shelf.row(work.id)[0] in (None, "generated")


def test_a_poster_beside_the_users_book_comes_before_the_epubs_cover_and_is_read_in_place(shelf):
    """Art the user put beside the book (Calibre writes cover.jpg there) is read where it is, never copied."""
    title = TITLES[shelf.language][0]
    folder = os.path.join(shelf.drive, *SHELF[shelf.language], title)
    book(os.path.join(folder, f"{title}.epub"), title, shelf.language, cover=jpeg())
    art = write(os.path.join(folder, "Cover.PNG"), png())
    shelf.read(shelf.drive)
    work = shelf.work_titled(title)
    assert shelf.scan() == 1
    assert shelf.row(work.id) == ("file", art, None, 0)
    assert C.image_path(shelf.language, shelf.works([work.id])[0], shelf.data_dir) == os.path.normpath(art)


def test_an_extracted_book_shows_its_epubs_cover_wherever_the_user_keeps_it_but_takes_no_art_from_there(
        shelf, monkeypatch):
    """Extract copies the parts in and records `<epub>#<n>` (no source): its own EPUB is the book's, but the folder
    it came from (Downloads…) is no work's — a stray cover.jpg there is never taken."""
    monkeypatch.setattr(extract, "_settings_by", lambda: "chapters")
    monkeypatch.setattr(ls, "spawn_maintain", lambda *a: None)
    title = TITLES[shelf.language][1]
    cover = jpeg(12, 18)
    folder = os.path.join(shelf.drive, "ダウンロード")
    path = book(os.path.join(folder, f"{title}.epub"), title, shelf.language, cover=cover)
    write(os.path.join(folder, "cover.jpg"), png(rgb=(10, 200, 10)))
    shelf.store.close()
    result = extract.extract(path, title, shelf.language, section="soon", spawn=False)
    assert result.code == extract.EXIT_DONE and result.in_library
    shelf.store = ls.open_store(shelf.language, shelf.data_dir, shelf.user_files_dir)
    work = shelf.work_titled(title)
    assert work.own_books == (path,) and work.own_folders == ()
    assert shelf.scan() == 1
    assert shelf.row(work.id)[:2] == ("file", path) and _cached_bytes(shelf, work.id) == cover


# --- shows -------------------------------------------------------------------------------------------------------- #
def test_a_poster_above_the_users_season_folder_is_the_shows_read_where_it_is(shelf):
    """Art saved beside the user's own videos (the same bug): `poster.jpg` in the show's folder, the episodes in its
    season folder — recorded by its absolute path, never copied; replaced in place, the record stays (it shows by
    itself)."""
    show = TITLES[shelf.language][0]
    show_dir = os.path.join(shelf.drive, "アニメ", show)
    episodes(os.path.join(show_dir, "Season 2"), show, shelf.language)
    poster = write(os.path.join(show_dir, "poster.jpg"), jpeg())
    shelf.read(os.path.join(shelf.drive, "アニメ"))
    work = shelf.work_titled(show)
    assert os.path.normpath(show_dir) in work.own_folders
    assert shelf.scan() == 1
    assert shelf.row(work.id) == ("file", poster, None, 0)
    write(poster, jpeg(32, 48))
    assert shelf.scan() == 0, "recorded: read where it is, a change shows by itself"


def test_art_in_a_folder_holding_two_shows_loose_episodes_is_no_ones(shelf):
    """A library folder of loose episodes of two shows has no one cover: its folder.jpg is never painted on both."""
    a, b = TITLES[shelf.language]
    loose = os.path.join(shelf.drive, "まとめ")
    episodes(loose, a, shelf.language, n=1)
    episodes(loose, b, shelf.language, n=1)
    write(os.path.join(loose, "folder.jpg"), jpeg())
    shelf.read(loose)
    assert all(w.own_folders == () for w in shelf.works())
    assert shelf.scan() == 0


def test_a_folder_the_user_stopped_reading_or_unplugged_is_never_looked_at(shelf):
    title = TITLES[shelf.language][0]
    show_dir = os.path.join(shelf.drive, "アニメ", title)
    episodes(show_dir, title, shelf.language, n=1)
    write(os.path.join(show_dir, "cover.jpg"), jpeg())
    book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language, cover=jpeg())
    root = shelf.read(shelf.drive)
    assert any(w.own_folders for w in shelf.works()) and any(w.own_books for w in shelf.works())
    assert shelf.store.stop_source(root) is not None
    assert all(w.own_folders == () and w.own_books == () for w in shelf.works()), "Stop reading: nothing read there"
    assert shelf.scan() == 0
    shelf.store.add_source(shelf.drive)                               # read again, then the drive goes
    assert any(w.own_folders for w in shelf.works())
    gone = shelf.drive + " (unplugged)"
    os.rename(shelf.drive, gone)
    try:
        assert all(w.own_folders == () and w.own_books == () for w in shelf.works())
    finally:
        os.rename(gone, shelf.drive)


def test_each_folder_is_looked_at_once_however_many_episodes_it_holds(shelf, monkeypatch):
    """Cheap on a big library: the records are read once, and each folder's neighbours once (its season folder and
    the show's above it), never once per episode."""
    show = TITLES[shelf.language][1]
    episodes(os.path.join(shelf.drive, show, "第2期"), show, shelf.language, n=12)
    shelf.read(shelf.drive)
    calls = []
    real = C._works_in
    monkeypatch.setattr(C, "_works_in", lambda store, key: calls.append(key) or real(store, key))
    work = shelf.work_titled(show)
    assert len(calls) == 2 and len(set(calls)) == 2, calls
    assert work.own_folders == (os.path.join(shelf.drive, show, "第2期"), os.path.join(shelf.drive, show))


def test_the_online_fetcher_looks_beside_the_originals_before_asking_anilist(shelf, anilist):  # noqa: F811
    """A title that arrived mid-session (the open's scan never saw it) with art beside the user's own episodes: the
    disk is looked at first and nothing leaves the machine."""
    show = TITLES[shelf.language][0]
    show_dir = os.path.join(shelf.drive, show)
    episodes(show_dir, show, shelf.language, n=1)
    art = write(os.path.join(show_dir, "folder.jpg"), jpeg())
    shelf.read(shelf.drive)
    work = shelf.work_titled(show)
    w = O.wants_for(shelf.store, [work.id])[0]._replace(anilist_id=900202)
    assert w.own_folders == (show_dir,)
    anilist.add(900202, "Tsukikage no Tabibito", w.title)
    f = fetcher(shelf.writer, anilist, language=shelf.language, data_dir=shelf.data_dir)
    before = shelf.heard.rereads
    assert f.want([w]) == 1 and f.run_once() == 0
    assert h.until(lambda: shelf.heard.rereads > before and not shelf.writer.pending())
    assert shelf.row(work.id) == ("file", art, None, 0)
    assert anilist.posts == [] and anilist.gets == []
