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


class _Looks:
    """The looks' Removed list answered as told (`answer`: None = the store couldn't be read), each read counted."""

    def __init__(self, answer):
        self.answer, self.reads = answer, 0

    def removed(self, then, language=None):
        self.reads += 1
        then(self.answer)
        return True

    def close(self):
        pass

    def set_shown(self, _shown):
        pass

    def asked(self, **_kw):
        return False


def test_an_unreadable_store_is_said_never_shown_as_an_empty_trash(real):
    _store, win, _writer = real()
    real_looks, win.looks = win.looks, _Looks(None)
    try:
        w = _open_removed(win)
        assert w.lines == {} and w.none.text() == strings.REMOVED_UNREADABLE
        w.close()
        win.looks = None                                               # no library open at all: the same words
        w = _open_removed(win)
        assert w.none.text() == strings.REMOVED_UNREADABLE
    finally:
        win.looks = real_looks


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
    real_under = win.looks.removed_under
    win.looks.removed_under = lambda *a, **kw: calls.append(a) or real_under(*a, **kw)
    texts = []
    line.back.setText = lambda t, _s=line.back.setText: texts.append(t) or _s(t)
    win.looks.listing()                                                 # a look's summary, nothing new in it
    assert win.looks.idle(10)
    settle(200)
    assert calls == [] and texts == []
    assert line.back.text() == strings.REMOVED_BRING_BACK.format(n=1)
