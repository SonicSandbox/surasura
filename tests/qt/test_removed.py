"""The 🗑 *Removed* list and Settings' *Bring back N removed* (alpha 4, D3; Mattias's note 6 — `app/qt/removed.py`,
`settings_sources.SourceLine` / `FoldersWindow`), on a real store where they write.

What a wrong answer would cost a learner:
  * a show he removed by mistake that he can't find again, or a list that shows what he put back already;
  * *Put back* that lands it somewhere else than it stood, or gives no Undo; an Undo that leaves it out of the list;
  * a folder whose removed files a look keeps out for good with nothing on its line to bring them back
    (Mattias: "the other stuff never showed up again");
  * a store that can't be read shown as *Nothing removed* (he'd think his trash was emptied);
  * a list read again and again while nothing moved, or read at all while it is closed (S19).

Real Japanese / Chinese titles: the migrated library's own (`tests/test_library_store_support`), and real subtitles from
tests/Test Resources/ in a source folder beside the test's data folder.
"""
import os
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import settings_manager
from app.qt import drag, removed, settings_sources, shell, strings, windows
from app.services import library_reader
from app.services import moves as moves_module
from tests.qt.conftest import wait_until
from tests.qt.test_drag import rows_of, settle
from tests.test_library_store_support import migrated
from tests.test_sources_scan import _drive, _fresh_module_state, _look, _text, _write  # noqa: F401

LANGUAGES = ["ja", "zh"]
FOLDER_TITLE = {"ja": "月影の旅人", "zh": "夜市小记"}


# --- a real store, its window, its writer and its looks ------------------------------------------------------------ #
@pytest.fixture
def real(qapp):
    made = []

    def make(language="ja", before=None):
        """A migrated library (`before(store)`: written into it before the window opens — a source folder read) and
        the window on it: the real writer, reader and looks (the writer's opener) -> (store, win, writer)."""
        store = migrated(language)
        if before is not None:
            before(store)
        settings_manager.save_keys({"target_language": language})
        opener = moves_module.store_opener(language)
        reader = library_reader.LibraryReader(opener, language, poll=0.02)
        writer = moves_module.Writer(opener, language, journal_file=moves_module.journal_path(language),
                                     words=strings.MOVE_WORDS, retry=0.05)
        services = shell.Services(library=reader, writer=writer)
        win = shell.open_window(qapp, services)
        win.resize(1280, 900)
        win.show()
        page = win.page_widgets["current"]
        assert wait_until(lambda: page.view_model is not None and page.view_model.state == "full", 15)
        assert wait_until(lambda: win.looks is not None, 10)
        made.append((win, services, store))
        return store, win, writer
    yield make
    for win, services, store in made:
        windows.close_all(win)
        win.close()
        services.shutdown(2.0)
        store.close()


def _saved(win, writer):
    assert wait_until(lambda: not win.moves.tickets, 10)
    settle()


def _undo(win):
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()


def _remove_row(win, writer, k=1):
    """⋯ *Remove…* on Current's row `k` (the confirmation's yes is ItemActions.remove) -> (its title, its ids)."""
    row = rows_of(win)[k]
    ids = [e.id for e in row.episodes]
    win.items.remove(row)
    _saved(win, writer)
    return row.title, ids


def _open_removed(win):
    w = removed.open_window(win)
    assert wait_until(lambda: not w._reading, 10)
    settle()
    return w


# --- the 🗑 list ----------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_title_is_listed_with_its_days_put_back_lands_where_it_was_and_undo_removes_it_again(real,
                                                                                                         language):
    store, win, writer = real(language)
    row = rows_of(win)[1]
    places = {e.id: store.place_of(e.id) for e in row.episodes}
    title, ids = _remove_row(win, writer)
    assert all(store.item(i) is None for i in ids)
    w = _open_removed(win)
    assert list(w.lines) and w.none.isHidden()
    line = next(iter(w.lines.values()))                                # newest first: the one just removed
    assert line.title.text() == title
    n = len(ids)
    files = strings.REMOVED_FILES_ONE if n == 1 else strings.REMOVED_FILES.format(n=n)
    assert line.detail.text() == f"{files} · {strings.REMOVED_DAYS.format(n=ls.REMOVED_DAYS)}"
    assert line.put.toolTip() == strings.REMOVED_PUT_BACK_TIP.format(title=title)
    line.put.click()
    assert line.key not in w.lines                                      # it leaves the list at the press
    assert wait_until(lambda: all(store.item(i) is not None for i in ids), 10)
    assert {i: store.place_of(i) for i in ids} == places                # back exactly where it stood
    _saved(win, writer)
    assert wait_until(lambda: not w._reading and line.key not in w.lines, 10)
    assert win.toasts.card.base == strings.REMOVED_BACK.format(title=title)
    _undo(win)                                                          # the toast's one Undo: removed again
    assert wait_until(lambda: all(store.item(i) is None for i in ids), 10)
    assert wait_until(lambda: any(l.title.text() == title for l in w.lines.values()), 10)


def test_nothing_removed_says_so_in_one_line(real):
    _store, win, _writer = real()
    w = _open_removed(win)
    assert w.lines == {} and w.none.text() == strings.REMOVED_NONE and not w.none.isHidden()


class _Store:
    """The trash as told (`answer`), each read counted — what `removed.read_store` hands its `ask`."""

    def __init__(self, answer):
        self.answer, self.reads = answer, 0

    def removed(self):
        self.reads += 1
        return self.answer


def _answer(monkeypatch, answer):
    """The Removed list's read answered at once from `answer` (None: the store couldn't be read) -> the fake store."""
    store = _Store(answer)
    monkeypatch.setattr(removed, "read_store", lambda _shell, _language, ask, then: then(
        None if store.answer is None else ask(store)) or True)
    return store


def test_an_unreadable_store_is_said_never_shown_as_an_empty_trash(real, monkeypatch):
    _store, win, _writer = real()
    _answer(monkeypatch, None)
    w = _open_removed(win)
    assert w.lines == {} and w.none.text() == strings.REMOVED_UNREADABLE
    w.close()
    monkeypatch.setattr(removed, "read_store", lambda *_a: False)       # no library open at all: the same words
    w = _open_removed(win)
    assert w.none.text() == strings.REMOVED_UNREADABLE


def test_S19_the_list_reads_once_as_it_opens_again_only_when_the_trash_moved_and_never_once_closed(real):
    store, win, writer = real()
    w = _open_removed(win)
    assert w.reads == 1
    row = rows_of(win)[2]
    moved = [e.id for e in row.episodes]
    win.moves._give(drag.Ticket("moved", (row.key,), moved), lambda t: writer.place(moved, "goal", label=t))
    _saved(win, writer)                                                # a move: the trash didn't move
    assert w.reads == 1
    _remove_row(win, writer)                                           # a Remove: read again, once
    assert wait_until(lambda: w.reads == 2 and not w._reading, 10)
    w.close()
    settle()
    _remove_row(win, writer)                                           # closed: nothing reads
    settle(200)
    assert w.reads == 2
    assert len(store.removed()) == 2


# --- Settings' *Bring back N removed* (Mattias's note 6) --------------------------------------------------------- #
def _source_with(language, n=4):
    """A source folder holding `n` episodes of one show (real subtitles) -> (its path, before(store) that reads it into
    the store and puts its items in Current, the ids it read)."""
    src = _drive("本棚" if language == "ja" else "书架")
    title = FOLDER_TITLE[language]
    for k in range(1, n + 1):
        _write(os.path.join(src, title, f"{title} - {k:02d}.srt"), _text(language, k, extra=str(k)))
    got = {}

    def before(store):
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        got.update(root=root, ids=list(result["ids"]))
    return src, before, got


def _folders(win):
    folders = settings_sources.open_window(win)
    assert wait_until(lambda: folders.lines, 10)
    return folders


@pytest.mark.parametrize("language", LANGUAGES)
def test_bring_back_n_removed_on_a_folders_line_puts_them_back_and_its_next_look_takes_none_in_twice(real, language):
    src, before, got = _source_with(language)
    store, win, writer = real(language, before=before)
    ids = got["ids"]
    assert len(ids) == 4
    win.moves._give(drag.Ticket("removed", (), ids),
                    lambda t: writer.remove(ids, label=t))
    _saved(win, writer)
    assert all(store.item(i) is None for i in ids)
    again = _look(store, language, got["root"])                         # Mattias: a look keeps them out for good
    assert again.get("added", 0) == 0 and all(store.item(i) is None for i in ids)
    folders = _folders(win)
    line = folders.lines[got["root"]]
    assert wait_until(lambda: not line.back.isHidden(), 10)
    assert line.back.text() == strings.REMOVED_BRING_BACK.format(n=4)
    assert line.back.toolTip() == strings.REMOVED_BRING_BACK_TIP.format(n=4, path=line.source["path"])
    line.back.click()
    assert line.back.isHidden()                                         # the press's answer, in the frame
    assert wait_until(lambda: all(store.item(i) is not None for i in ids), 10)
    _saved(win, writer)
    assert store.removed_under(got["root"]) == []
    n_items = len(list(store.conn.execute("SELECT id FROM items")))
    look = _look(store, language, got["root"], full=True)               # its next look: them, never a second copy
    assert look.get("added", 0) == 0
    assert len(list(store.conn.execute("SELECT id FROM items"))) == n_items
    assert all(store.item(i)["availability"] == "available" for i in ids)
    _undo(win)                                                          # one Undo: back in the trash, the button back
    assert wait_until(lambda: all(store.item(i) is None for i in ids), 10)
    assert wait_until(lambda: line.back.text() == strings.REMOVED_BRING_BACK.format(n=4) and not line.back.isHidden(),
                      10)


def test_a_folder_with_nothing_removed_shows_no_button_and_the_trash_button_opens_the_list(real):
    src, before, got = _source_with("ja", n=2)
    _store, win, _writer = real(before=before)
    folders = _folders(win)
    line = folders.lines[got["root"]]
    assert wait_until(lambda: got["root"] not in folders._removed_reading, 10)
    assert line.back.isHidden() and line.removed == ()
    assert not folders.removed.isHidden() and folders.removed.text() == strings.REMOVED_OPEN
    assert folders.removed.toolTip() == strings.REMOVED_OPEN_TIP
    folders.removed.click()
    assert wait_until(lambda: windows.opened(win, removed.WINDOW) is not None, 5)


def test_S19_a_looks_summary_with_nothing_new_reads_no_removed_files_and_repaints_no_button(real):
    src, before, got = _source_with("ja", n=2)
    store, win, writer = real(before=before)
    ids = got["ids"][:1]
    win.moves._give(drag.Ticket("removed", (), ids),
                    lambda t: writer.remove(ids, label=t))
    _saved(win, writer)
    folders = _folders(win)
    line = folders.lines[got["root"]]
    assert wait_until(lambda: not line.back.isHidden(), 10)
    calls = []
    real_read = removed.read_store
    removed.read_store = lambda *a, **kw: calls.append(a) or real_read(*a, **kw)
    texts = []
    line.back.setText = lambda t, _s=line.back.setText: texts.append(t) or _s(t)
    try:
        win.looks.listing()                                             # a look's summary, nothing new in it
        assert win.looks.idle(10)
        settle(200)
    finally:
        removed.read_store = real_read
    assert calls == [] and texts == []
    assert line.back.text() == strings.REMOVED_BRING_BACK.format(n=1)


# --- fix2-b: a mass Remove's list, the new controller after a switch, one read for the folder lines --------------- #
TITLES = {"ja": "進撃の巨人", "zh": "甄嬛传"}


def _entries(language, n):
    return [{"trash_ids": [i], "title": f"{TITLES[language]} 第{i}話", "removed_at": "2026-10-27T10:00:00",
             "days_left": 30, "count": 1, "can_return": True, "roots": []} for i in range(1, n + 1)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_A4B3_a_mass_removes_2500_entries_open_in_one_frame_and_build_on_as_the_list_is_scrolled(real, language):
    # A4B-3: one Remove of 2,500 picked titles is 2,500 entries; every line built in one slot froze the window 2.4 s
    # (laptop ~6 s). Now the answer's own turn builds a couple, the first 30 follow in slices, the next ones as the
    # list nears its end; a re-read with one entry fewer touches only that line (S19).
    _store, win, _writer = real(language)
    w = _open_removed(win)
    entries = _entries(language, 2500)
    t = time.perf_counter()
    w._show(entries)
    took = (time.perf_counter() - t) * 1000
    assert len(w.lines) <= removed.FIRST_FRAME and took < 16, took
    assert wait_until(w.settled, 5)
    assert len(w.lines) == removed.BUILT_AT_ONCE
    titles = [w.lines[k].title.text() for k in w.order]
    assert titles == [e["title"] for e in entries[:removed.BUILT_AT_ONCE]]          # newest first, in order
    built = w.builds
    kept = {k: w.lines[k] for k in w.order[1:]}
    t = time.perf_counter()
    w._show(entries[1:])                                               # a re-read: the newest one put back
    took = (time.perf_counter() - t) * 1000
    assert took < 16, took
    assert w.builds <= built + 1                                       # (at most the one more line at the end)
    assert all(w.lines[k] is line for k, line in kept.items())          # the same widgets, nothing rebuilt
    bar = w.scroll.verticalScrollBar()
    bar.setValue(bar.maximum())                                         # scrolled to the end: the next ones
    assert wait_until(lambda: len(w.lines) >= 2 * removed.BUILT_AT_ONCE and w.settled(), 5)
    assert [w.lines[k].title.text() for k in w.order] == [e["title"] for e in entries[1:len(w.order) + 1]]


def test_A4B7_the_list_is_read_while_a_long_look_holds_the_looks_worker(real):
    # A4B-7: the 🗑 list was read on the looks' one worker: behind setup's first look of 15,000 files it said
    # *Looking in the trash…* until the look ended. It reads on a thread of its own now.
    import threading
    store, win, writer = real()
    title, _ids = _remove_row(win, writer)
    gate = threading.Event()
    win.looks._worker.put(gate.wait, 10)                               # a long look holds the looks' worker
    try:
        w = _open_removed(win)
        assert any(line.title.text() == title for line in w.lines.values())
    finally:
        gate.set()


def test_A4B7_bring_back_on_every_folder_line_is_one_read_and_each_line_counts_its_own(real):
    # A4B-7: one trash scan per folder line, again on every trash move anywhere. Now one read for every line; each
    # line still counts only the files whose original is in its own folder.
    src_a, before_a, got_a = _source_with("ja", n=3)
    src_b = _drive("映画")
    for k in (1, 2):
        _write(os.path.join(src_b, "千と千尋", f"千と千尋 - {k:02d}.srt"), _text("ja", 10 + k, extra=str(k)))
    got_b = {}

    def before(store):
        before_a(store)
        root = store.add_source(src_b)
        got_b.update(root=root, ids=list(_look(store, "ja", root, first=True)["ids"]))
    store, win, writer = real(before=before)
    gone = got_a["ids"][:2] + got_b["ids"][:1]
    win.moves._give(drag.Ticket("removed", (), gone), lambda t: writer.remove(gone, label=t))
    _saved(win, writer)
    reads = []
    real_read = removed.read_store
    removed.read_store = lambda *a, **kw: reads.append(a[1]) or real_read(*a, **kw)
    try:
        folders = _folders(win)
        a, b = folders.lines[got_a["root"]], folders.lines[got_b["root"]]
        assert wait_until(lambda: not a.back.isHidden() and not b.back.isHidden(), 10)
        assert len(reads) == 1                                          # both lines, one read
        assert a.back.text() == strings.REMOVED_BRING_BACK.format(n=2)
        assert b.back.text() == strings.REMOVED_BRING_BACK.format(n=1)
        del reads[:]
        _remove_row(win, writer)                                        # a Remove elsewhere: one read again
        assert wait_until(lambda: len(reads) == 1 and not folders._removed_job, 10)
        settle(100)
        assert len(reads) == 1
    finally:
        removed.read_store = real_read


@pytest.mark.parametrize("language", LANGUAGES)
def test_A4B11_a_put_back_reads_the_list_once_and_A4B10_one_that_fails_reads_it_again(real, language):
    # A4B-11: the ticket's "saved" and the controller's both read: two reads per Put back. A4B-10: a Put back that
    # can't be done (its files put back from elsewhere meanwhile) showed its stale line again, every press failing.
    store, win, writer = real(language)
    _remove_row(win, writer, 1)
    _remove_row(win, writer, 1)
    w = _open_removed(win)
    first, second = [w.lines[k] for k in w.order[:2]]
    reads = w.reads
    first.put.click()
    assert wait_until(lambda: not w._reading and first.key not in w.lines and w.reads > reads, 10)
    _saved(win, writer)
    settle(100)
    assert w.reads == reads + 1                                         # once
    store.restore(list(second.key))                                     # another program put it back meanwhile
    reads = w.reads
    second.put.click()
    assert wait_until(lambda: not w._reading and w.reads > reads and second.key not in w.lines, 10)
    assert w.none.text() == strings.REMOVED_NONE


def test_IK2_10_put_back_is_greyed_with_the_stores_reason_while_it_cant_be_written(real, monkeypatch):
    store, win, writer = real()
    title, ids = _remove_row(win, writer)
    monkeypatch.setattr(writer, "can_write", lambda: False)
    monkeypatch.setattr(writer, "reason", lambda: "newer")
    w = _open_removed(win)
    line = next(iter(w.lines.values()))
    why = settings_sources.why_not(win)
    assert why and not line.put.isEnabled() and line.put.toolTip() == why
    line.put.click()
    settle(100)
    assert all(store.item(i) is None for i in ids)                     # nothing written


def test_A4B6_after_a_language_switch_the_open_list_follows_the_new_librarys_removes(qapp):
    # A4B-6: the list followed the controller it was opened under; a language switch makes a new one, so a Remove in
    # the new library was never heard. It is told by the window's current controller now, and reads the new library.
    from tests.qt.test_shell_library import _ask, _state, _switched_to
    ja, zh = migrated("ja"), migrated("zh")
    services = shell.open_services()
    win = shell.open_window(qapp, services)
    win.resize(1280, 900)
    win.show()
    try:
        assert wait_until(lambda: _state(win) == "full" and services.writer is not None, 15)
        w = _open_removed(win)
        assert w.none.text() == strings.REMOVED_NONE
        _ask(services, win, "zh")
        assert _switched_to(win, services, "zh", 30)
        assert wait_until(lambda: w.language == "zh" and not w._reading, 10)
        reads = w.reads
        title, _ids = _remove_row(win, services.writer)                  # a Remove in the new library
        assert wait_until(lambda: w.reads > reads and not w._reading and
                          any(line.title.text() == title for line in w.lines.values()), 10)
    finally:
        windows.close_all(win)
        win.close()
        services.shutdown(2.0)
        ja.close()
        zh.close()
