"""Covers for what arrives while the window is open (Hon a7; the alpha 6 try, round 1: "are epubs supposed to have
their covers there? They don't seem to show up."). The cover scan ran once per window open and every book came after
it — book folders read during setup, a book extracted into 383 parts — while the per-title look that came later
skipped books and needed *Download covers* on. Now the library reader names the works whose files arrived or changed
(`LibraryReader.subscribe_arrived`) and the window's covers look at those titles only (`app/qt/covers.py`: `follow`,
`look` → `services.covers.works_for` → the open's own `scan`): one path for a folder read, Extract (+ Add's *EPUB…*)
and + Add's files, books as shows, whatever the download switch says.

What a wrong answer would cost a learner:
  * a book they add mid-session shown with a generated colour tile until the next restart, although its EPUB has a
    cover (the bug) — or never, for a book that arrived before the first frame;
  * the whole library looked at again for every drag, mark or arrival (S19), or a title looked at again and again;
  * a picture taken from a folder that isn't the title's (a Downloads folder Extract read from, + Add's elsewhere);
  * a look for a library already left (a language switch) writing into the one shown.

Each runs the window's real reader (polling a fresh store on its own thread) and writer, with no window and no network:
real Japanese and Chinese text from tests/Test Resources/, each book built with EbookLib (the shipped dependency) by
test_covers_own_folder's `book`, made-up titles, non-ASCII folders.
"""
import os
import time

import pytest

from app import extract
from app import library_store as ls
from app.qt import covers as qcovers
from app.services import covers as C
from app.services import library_reader
from tests import services_helpers as h
from tests.test_covers_own_folder import SHELF, TITLES, Shelf, _cached_bytes, book, episodes
from tests.test_services_covers import jpeg, png, write
from tests.test_sources_scan import _drive, _fresh_module_state  # noqa: F401 (autouse: a new run of the app)

pytest.importorskip("PyQt6")


class Session:
    """A window's session without the window: the reader on the store (its first read done, as at the open), the
    covers following it, the first frame out (no hold). `looked`: each batch of works the covers read."""

    def __init__(self, shelf, monkeypatch, opener=None, first_read=True):
        self.shelf = shelf
        self.looked = []
        real = C.works_for
        monkeypatch.setattr(C, "works_for", lambda store, ids: self.looked.append(sorted(ids)) or real(store, ids))
        qcovers.clear()
        self.opener = opener or ls.StoreOpener(shelf.language, shelf.data_dir, shelf.user_files_dir, role="window")
        self.reader = library_reader.LibraryReader(self.opener, shelf.language, poll=0.02)
        self.views = []
        self.reader.subscribe(self.views.append)
        qcovers.follow(self.reader, shelf.language, shelf.writer)
        self.reader.start()
        if first_read:
            assert h.until(lambda: self.views and self.reader._seen is not None)

    def idle(self):
        """The reader has read the store as it is, and the covers' look and the writer are done."""
        version = self.shelf.store.read_feed()["version"]
        assert h.until(lambda: self.reader._seen == version)
        assert h.until(lambda: qcovers._look["thread"] is None and not qcovers._look["pending"]
                       and not self.shelf.writer.pending())

    def cover(self, work_id):
        assert h.until(lambda: self.shelf.row(work_id)[0] == "file", 15), self.shelf.row(work_id)
        self.idle()
        return self.shelf.row(work_id)

    def close(self):
        qcovers.stop_scan()
        self.reader.stop()
        qcovers.follow(None, self.shelf.language, None)
        qcovers.clear()


@pytest.fixture(params=["ja", "zh"])
def shelf(request):
    s = Shelf(request.param)
    yield s
    s.close()


@pytest.fixture
def session(shelf, monkeypatch):
    s = Session(shelf, monkeypatch)
    yield s
    s.close()


def _mine(session, work_id):
    return [ids for ids in session.looked if work_id in ids]


# --- the three doors ------------------------------------------------------------------------------------------------ #
def test_a_book_folder_read_mid_session_shows_its_epubs_cover_at_once(session, shelf):
    """The bug: the user points Surasura at their book folder after the window opened (setup's page, Settings, + Add ›
    A folder… all read it the same way) — the cover comes at once, from the EPUB on their own drive, no restart and no
    *Download covers*."""
    title = TITLES[shelf.language][0]
    cover = jpeg(20, 30)
    path = book(os.path.join(shelf.drive, *SHELF[shelf.language], title, f"{title}.epub"), title, shelf.language,
                cover=cover)
    shelf.read(shelf.drive)
    work = shelf.work_titled(title)
    source, ref, cache, locked = session.cover(work.id)
    assert (source, ref, locked) == ("file", path, 0) and cache.startswith("cache:")
    assert _cached_bytes(shelf, work.id) == cover
    assert _mine(session, work.id) == [[work.id]], "looked at once, alone"


def test_an_extracted_book_shows_its_cover_wherever_the_epub_is_kept(session, shelf, monkeypatch):
    """Extract (and + Add › EPUB…, its door): the parts come in from another process's commits; the EPUB's own cover
    is recorded against the EPUB where the user keeps it — never the stray picture in the folder it came from."""
    monkeypatch.setattr(extract, "_settings_by", lambda: "chapters")
    monkeypatch.setattr(ls, "spawn_maintain", lambda *a: None)
    title = TITLES[shelf.language][1]
    cover = jpeg(12, 18)
    folder = os.path.join(shelf.drive, "ダウンロード")
    path = book(os.path.join(folder, f"{title}.epub"), title, shelf.language, cover=cover)
    write(os.path.join(folder, "cover.jpg"), png(rgb=(10, 200, 10)))
    result = extract.extract(path, title, shelf.language, section="now", spawn=False)
    assert result.code == extract.EXIT_DONE and result.in_library and result.parts > 1
    work = shelf.work_titled(title)
    assert session.cover(work.id)[:2] == ("file", path)
    assert _cached_bytes(shelf, work.id) == cover
    assert len(_mine(session, work.id)) == 1, "a book of many parts is looked at once"


def test_add_files_looks_at_the_show_they_join_and_a_poster_saved_there_later_comes_with_its_next_episode(
        session, shelf):
    """+ Add's files (and a drop): copied into the library's own folder. Nothing is taken from the folder they came
    from (no one's title lives there); a poster the user then saves in the show's library folder comes with the next
    episode added — a title that changed is looked at again, only that title."""
    show = TITLES[shelf.language][0]
    elsewhere = episodes(os.path.join(_drive("ダウンロード"), show), show, shelf.language, n=2)
    write(os.path.join(elsewhere, "poster.jpg"), jpeg())
    subs = sorted(os.path.join(elsewhere, n) for n in os.listdir(elsewhere) if n.endswith(".srt"))
    before = len(shelf.heard.saved)
    shelf.writer.insert_at(subs[:1], "now", label="added")
    assert h.until(lambda: len(shelf.heard.saved) > before)
    session.idle()
    work = shelf.work_titled(show)
    assert _mine(session, work.id) == [[work.id]]
    assert shelf.row(work.id)[0] in (None, "generated"), "nothing taken from the Downloads folder"
    folder = work.rel_paths[0].rsplit("/", 1)[0]                     # its copy's folder: Library/<show>
    write(os.path.join(shelf.data_dir, *folder.split("/"), "poster.jpg"), jpeg(30, 45))
    shelf.writer.insert_at(subs[1:], "now", label="added", into=folder)
    assert session.cover(work.id) == ("file", f"{folder}/poster.jpg", None, 0)
    assert len(_mine(session, work.id)) == 2
    assert len(shelf.store.read_feed()["items"]) == 2, "the second episode joined its show"


# --- what isn't looked at, and when ------------------------------------------------------------------------------- #
def test_a_book_with_no_cover_keeps_its_generated_one_and_is_looked_at_once(session, shelf):
    title = TITLES[shelf.language][1]
    book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language)
    shelf.read(shelf.drive)
    session.idle()
    work = shelf.work_titled(title)
    assert _mine(session, work.id) == [[work.id]]
    assert shelf.row(work.id)[0] in (None, "generated")


def test_moves_marks_and_the_covers_own_records_look_at_nothing_again(session, shelf):
    """S19: only what arrived or changed is looked at — never a drag, a watched mark, nor the cover the look itself
    recorded (no loop)."""
    title = TITLES[shelf.language][0]
    book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language, cover=jpeg())
    shelf.read(shelf.drive)
    work = shelf.work_titled(title)
    session.cover(work.id)
    looked = list(session.looked)
    ids = [r["id"] for r in shelf.store.read_feed()["items"] if r["work_id"] == work.id]
    before = len(shelf.heard.saved)
    shelf.writer.set_watched(ids[:1], True, label="watched")
    shelf.writer.move(ids[-1:], "soon", label="moved")
    assert h.until(lambda: len(shelf.heard.saved) >= before + 2), shelf.heard.notes
    session.idle()
    assert session.looked == looked
    other = TITLES[shelf.language][1]                                   # still listening: the next arrival is looked at
    book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{other}.epub"), other, shelf.language, cover=jpeg())
    shelf.read(shelf.drive)
    assert session.cover(shelf.work_titled(other).id)[0] == "file"
    assert len(session.looked) == len(looked) + 1


def test_the_first_read_tells_nothing_the_opens_own_scan_looks_at_the_library(shelf, monkeypatch):
    """What was there at the open is the open's scan's (once per open); the reader's first read hands nothing on."""
    title = TITLES[shelf.language][0]
    book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language, cover=jpeg())
    shelf.read(shelf.drive)
    s = Session(shelf, monkeypatch)
    try:
        s.idle()
        work = shelf.work_titled(title)
        assert s.looked == [] and shelf.row(work.id)[0] in (None, "generated")
        qcovers.start_scan(s.opener, shelf.language, shelf.writer).join(15)     # the first frame's scan
        assert s.cover(work.id)[0] == "file" and s.looked == []
    finally:
        s.close()


class NotYet(ls.StoreOpener):
    """A library whose store isn't there at the open (a 2.x library the helper migrates, setup's first library): the
    window's reads get no handle until `ready`."""
    ready = False

    def check(self):
        if not self.ready:
            self.mode, self.reason = "json", "not migrated"
            return "json"
        return super().check()


def test_a_library_whose_store_isnt_there_at_the_open_is_scanned_at_the_readers_first_read(shelf, monkeypatch):
    """Review #1: the open's scan finds no store (tried again, then left); once the store is there, the reader's first
    read hands the library to the look — every title's cover, the book read meanwhile's too."""
    monkeypatch.setattr(qcovers, "LOOK_RETRY_S", 0.01)
    title = TITLES[shelf.language][0]
    path = book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language,
                cover=jpeg())
    shelf.read(shelf.drive)
    opener = NotYet(shelf.language, shelf.data_dir, shelf.user_files_dir, role="window")
    s = Session(shelf, monkeypatch, opener=opener, first_read=False)
    try:
        qcovers.start_scan(opener, shelf.language, shelf.writer).join(15)
        assert qcovers._look["missed"] is opener and s.reader._seen is None
        work = shelf.work_titled(title)
        assert shelf.row(work.id)[0] in (None, "generated")
        opener.ready = True
        assert s.cover(work.id)[:2] == ("file", path)
        assert qcovers._look["missed"] is None and s.looked == [], "the whole library, as the open scans it"
    finally:
        s.close()


def test_a_batch_the_store_couldnt_take_is_tried_again_not_dropped(session, shelf, monkeypatch):
    """Review #2: a look that hit a busy store (a big folder read commits hardest just then) is put back and tried
    again, so the book still gets its cover this session."""
    import sqlite3
    monkeypatch.setattr(qcovers, "LOOK_RETRY_S", 0.01)
    real, failed = qcovers._scan_works, []

    def busy_once(h, *a, **k):
        if not failed:
            failed.append(1)
            raise sqlite3.OperationalError("database is locked")
        return real(h, *a, **k)
    monkeypatch.setattr(qcovers, "_scan_works", busy_once)
    title = TITLES[shelf.language][1]
    book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language, cover=jpeg())
    shelf.read(shelf.drive)
    assert session.cover(shelf.work_titled(title).id)[0] == "file" and failed == [1]


class BusyOnce(ls.StoreOpener):
    """A store the open's scan finds busy once (a folder read committing just then), then free."""
    refused = 0

    def handle(self):
        if not self.refused:
            self.refused = 1
            return None
        return super().handle()


def test_the_opens_scan_tries_a_busy_store_again_and_covers_the_library_itself(shelf, monkeypatch):
    """The open's own scan tries again after a busy store, so the library's covers come from the open, not from a
    later read of the reader (nothing is left `missed`)."""
    monkeypatch.setattr(qcovers, "LOOK_RETRY_S", 0.01)
    title = TITLES[shelf.language][0]
    path = book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language,
                cover=jpeg())
    shelf.read(shelf.drive)
    qcovers.clear()
    opener = BusyOnce(shelf.language, shelf.data_dir, shelf.user_files_dir, role="window")
    opener.check()
    try:
        qcovers.start_scan(opener, shelf.language, shelf.writer).join(15)
        assert opener.refused == 1 and qcovers._look["missed"] is None
        work = shelf.work_titled(title)
        assert h.until(lambda: shelf.row(work.id)[:2] == ("file", path), 15), shelf.row(work.id)
    finally:
        qcovers.stop_scan()
        qcovers.clear()


def test_a_cancelled_worker_and_one_whose_library_was_left_look_at_nothing(session, shelf, monkeypatch):
    """The looks' worker checks both before each batch: the window's close (its cancel) and the library it serves (a
    language switch landing between the two checks). Either way the titles told stay for the library shown, unread
    through the wrong store and writer."""
    import threading
    seen = []
    monkeypatch.setattr(qcovers, "_scan_works", lambda h, lang, writer, cancel, d, ids=None: seen.append(ids) or 0)
    qcovers._look["pending"][7] = None
    closed = threading.Event()
    closed.set()
    qcovers._looking(session.opener, shelf.language, shelf.writer, closed)
    left = ls.StoreOpener(shelf.language, shelf.data_dir, shelf.user_files_dir, role="window")
    left.check()
    qcovers._looking(left, shelf.language, object(), threading.Event())
    assert seen == [] and list(qcovers._look["pending"]) == [7]
    qcovers._look["pending"].clear()


def test_the_read_by_id_gives_a_title_every_one_of_its_files(session, shelf):
    """`works_for` reads each title's items whole: a poster beside a later episode's folder is found as at the open."""
    show = TITLES[shelf.language][1]
    episodes(os.path.join(shelf.drive, *SHELF[shelf.language], show), show, shelf.language, n=3)
    shelf.read(shelf.drive)
    session.idle()
    items = [r for r in shelf.store.read_feed()["items"] if r["rel_path"].endswith(".srt")]
    (work_id,) = {r["work_id"] for r in items}                          # the show is one title
    (got,) = C.works_for(shelf.store, [work_id])
    assert len(items) == 3 and sorted(got.rel_paths) == sorted(r["rel_path"] for r in items)


def test_titles_that_arrive_before_the_first_frame_are_looked_at_once_it_is_out(session, shelf):
    """G1: no look starts while a window's first frame is held; what arrived meanwhile is looked at at the release."""
    qcovers.hold("first-frame")
    try:
        title = TITLES[shelf.language][0]
        book(os.path.join(shelf.drive, *SHELF[shelf.language], f"{title}.epub"), title, shelf.language, cover=jpeg())
        shelf.read(shelf.drive)
        work = shelf.work_titled(title)
        assert h.until(lambda: work.id in qcovers._look["pending"])
        time.sleep(0.2)
        assert session.looked == [] and qcovers._look["thread"] is None
    finally:
        qcovers.release("first-frame")
    assert session.cover(work.id)[0] == "file"


def test_a_switch_mid_look_lets_the_library_left_go_and_looks_only_at_the_one_shown(session, shelf, monkeypatch):
    """A language switch while a look runs (`_follow_covers`: `stop_scan`, then `follow`): the old worker ends after
    its batch and takes nothing more; the old reader's last word is refused; the new library's titles are looked at by
    a worker of its own, with its own writer."""
    import threading
    from types import SimpleNamespace
    gate, seen = threading.Event(), []

    def slow(h, language, writer, cancel, data_dir, work_ids=None):
        if 7 in (work_ids or ()):
            gate.wait(5)
        seen.append((list(work_ids), writer))
        return 0
    monkeypatch.setattr(qcovers, "_scan_works", slow)
    old = qcovers.look(session.opener, [7])
    assert old is not None and h.until(lambda: not qcovers._look["pending"])
    qcovers.look(session.opener, [8])                                   # waits behind 7
    qcovers.stop_scan()
    new_writer = object()
    shown = SimpleNamespace(opener=ls.StoreOpener(shelf.language, shelf.data_dir, shelf.user_files_dir,
                                                  role="window"), subscribe_arrived=lambda cb: None)
    shown.opener.check()
    qcovers.follow(shown, shelf.language, new_writer)
    assert qcovers.look(session.opener, [9]) is None, "the library left's word"
    new = qcovers.look(shown.opener, [10])
    assert new is not None and new is not old
    new.join(5)
    gate.set()
    old.join(5)
    assert seen == [([10], new_writer), ([7], shelf.writer)], seen
    assert qcovers._look["thread"] is None


def test_many_titles_told_while_one_look_runs_are_each_looked_at_once_by_one_worker(session, shelf, monkeypatch):
    """A folder of many books committed batch after batch: one worker, each title once however often it was told."""
    seen, started = [], []
    gate = __import__("threading").Event()

    def slow(h, language, writer, cancel, data_dir, work_ids=None):
        started.append(1)
        gate.wait(5)
        seen.extend(work_ids)
        return 0
    monkeypatch.setattr(qcovers, "_scan_works", slow)
    first = qcovers.look(session.opener, [7])
    assert first is not None and h.until(lambda: started)
    for _ in range(3):
        assert qcovers.look(session.opener, [8, 9, 8]) is None          # the running worker takes them next
    gate.set()
    first.join(5)
    assert sorted(seen) == [7, 8, 9] and len(started) == 2
    assert qcovers._look["thread"] is None
    qcovers.stop_scan()                                                 # the window's close: nothing more starts
    assert qcovers.look(session.opener, [11]) is None and qcovers._look["thread"] is None


def test_the_readers_word_names_new_items_moved_files_and_regrouped_items_only():
    """`LibraryReader._arrived`, row by row: a new item, a file moved (a rename, maintain's move) and an item that
    joined another work name their works; a move, a mark or no work at all names none; the first read names the whole
    library (None); no listener, no work."""
    from types import SimpleNamespace
    r = library_reader.LibraryReader(SimpleNamespace(), "ja")
    row = {"id": 1, "work_id": 5, "rel_path": "Library/a/1.txt", "tier": "now", "ord": 1, "watched": 0}
    assert r._arrived({"items": [row]}) == [], "no listener"
    r.subscribe_arrived(lambda ids: None)
    assert r._arrived({"items": [row]}) is None, "the first read"
    r._seen, r._items = 3, {1: dict(row)}
    assert r._arrived({"items": [dict(row, tier="soon", ord=9, watched=1)]}) == [], "a move, a mark"
    assert r._arrived({"items": [dict(row, rel_path="Library/a/1 (2).txt")]}) == [5], "its file moved"
    assert r._arrived({"items": [dict(row, work_id=6)]}) == [6], "it joined another work"
    assert r._arrived({"items": [dict(row, id=2, work_id=None)]}) == [], "no work yet"
    assert r._arrived({"items": [dict(row, id=3, work_id=7), dict(row, id=4, work_id=7), row]}) == [7]
