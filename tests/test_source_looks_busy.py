"""P-1 (found by the alpha 2 cut's red run, 2026-10-24): the looks' worker opens its own store handle with no wait, so
a store only busy that moment — another connection opening, closing or committing — came back as no handle, and the
add answered "no-library". The window reads "no-library" as a 2.x library with no store and copies the folder in:
the wrong action, and a second copy of a show the store may read later (MV-1: never a duplicate).

Now a busy open is asked again on the looks' worker for the store's own busy-at-open wait (`BUSY_AT_OPEN`), and a
store still busy after it, or read-only, answers its reason; "no-library" is only a library with no 3.0 store. What a
wrong answer costs a learner: his folder copied into Surasura's own when he asked for it to be read where it is.
Show names are made up; the subtitles are real Japanese / Chinese from tests/Test Resources/.
"""
import os
import threading
import time

import pytest

from app import library_store as ls
from app.services import source_looks
from tests import services_helpers as h
from tests.test_library_store_support import LANGUAGES, library, write_manifest
from tests.test_sources_scan import _OURS, _SHOWS, _drive, _fresh_module_state, _text, _write  # noqa: F401


def _library(language):
    """An empty 3.0 store (setup's start) and a window's opener on it, checked as the window checks it."""
    data_dir, user_files_dir, doc = library(language, shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    assert opener.check() == "store"
    return opener, data_dir, user_files_dir


def _folder(language):
    """A folder on the second "drive" holding one show's two episodes."""
    src = _drive("Anime")
    show = _SHOWS[language][0]
    for n in (1, 2):
        _write(os.path.join(src, show, f"{show} - {n:02d}.{_OURS[language]}.srt"), _text(language, n))
    return src


def _busy_on_the_worker(monkeypatch, times=None, settle=False, settle_s=0.0):
    """The looks' worker's no-wait opens meet a busy store (`times` of them; None: every one); anyone else's open, and
    a wait, read the store as it is — or, with `settle`, the opener's own retry too (a store busy past its wait;
    `settle_s`: each of its looks that long, so it outlasts the looks' wait).
    -> the busy answers given."""
    real = ls._probe
    given = []

    def probe(db_path, busy_wait):
        worker = threading.current_thread().name.startswith("window-sources")
        settling = settle and threading.current_thread() is not threading.main_thread()
        if ((busy_wait == 0.0 and worker) or settling) and (times is None or len(given) < times):
            given.append(1)
            if settling and not worker and settle_s:
                time.sleep(settle_s)
            return "read-only", "busy"
        return real(db_path, busy_wait)
    monkeypatch.setattr(ls, "_probe", probe)
    return given


def _added(looks, path):
    answers = []
    assert looks.add(path, answers.append)
    assert h.until(lambda: answers, seconds=10) and looks.idle(10)
    return answers[0]


def _sources(language, data_dir, user_files_dir):
    store = ls.open_store(language, data_dir, user_files_dir)
    try:
        return [s["path"] for s in store.sources()]
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_busy_at_the_first_open_is_asked_again_and_the_folder_is_read_where_it_is(language, monkeypatch):
    # why: a busy moment passes in milliseconds; the folder he asked to be read where it is is read there — never
    # "no-library", never copied in
    opener, data_dir, user_files_dir = _library(language)
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    busy = _busy_on_the_worker(monkeypatch, times=5)
    src = _folder(language)
    try:
        answer = _added(looks, src)
    finally:
        looks.close()
    assert len(busy) == 5, "the worker met the busy store"
    assert answer["refused"] is None and answer["root"] is not None, answer
    assert answer["result"]["added"] == 2
    assert [os.path.normcase(p) for p in _sources(language, data_dir, user_files_dir)] == [os.path.normcase(src)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_still_busy_after_the_wait_answers_busy_and_nothing_is_written(language, monkeypatch):
    # why: still busy after the store's own wait, the press says the library is busy (the window's words) — never
    # "no-library", which copies the folder in
    opener, data_dir, user_files_dir = _library(language)
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    with monkeypatch.context() as patched:
        busy = _busy_on_the_worker(patched, settle=True)
        started = time.monotonic()
        try:
            answer = _added(looks, _folder(language))
        finally:
            looks.close()
        took = time.monotonic() - started
    assert len(busy) > 2 and took >= ls.BUSY_AT_OPEN * 0.9, ("asked again for the whole wait", len(busy), took)
    assert answer["refused"] == "busy" and answer["root"] is None, answer
    assert _sources(language, data_dir, user_files_dir) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_opener_that_last_saw_no_store_waits_for_its_busy_look_and_reads_the_folder_where_it_is(language,
                                                                                                    monkeypatch):
    # why (the review round): the window last looked before the store was made (its opener says "no store"); the store is
    # there now but busy at the add. The opener's own retry of that busy look answers "store" — read, never the mode
    # it cached before (which says no store: a copy-in, a duplicate)
    data_dir, user_files_dir, doc = library(language, shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    assert opener.check() == "json" and opener.reason == "no store"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE          # the store made since
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    busy = _busy_on_the_worker(monkeypatch, times=1)                                  # the worker's look: busy
    src = _folder(language)
    try:
        answer = _added(looks, src)
    finally:
        looks.close()
    assert busy == [1]
    assert answer["refused"] is None and answer["result"]["added"] == 2, answer
    assert [os.path.normcase(p) for p in _sources(language, data_dir, user_files_dir)] == [os.path.normcase(src)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_opener_that_last_saw_no_store_and_a_store_busy_past_the_wait_answers_busy_never_no_library(language,
                                                                                                       monkeypatch):
    # why: the same window, the store busy for longer than the wait: the opener's retry is still running when the
    # wait ends, so the mode it holds is the one cached before ("no store") — no answer. Said as busy; never the
    # copy-in, never a source written
    data_dir, user_files_dir, doc = library(language, shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    assert opener.check() == "json" and opener.reason == "no store"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    with monkeypatch.context() as patched:
        _busy_on_the_worker(patched, settle=True, settle_s=2.0)       # every look but the test's own: busy
        try:
            answer = _added(looks, _folder(language))
        finally:
            looks.close()
        opener.wait(5)                                                # the opener's retry ends (busy) before undo
    assert answer["refused"] == "busy" and answer["root"] is None, answer
    assert _sources(language, data_dir, user_files_dir) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_closing_the_looks_ends_a_busy_wait_at_once(language, monkeypatch):
    # why: the window closing (or another language opening) never waits out a busy store's wait on the looks' worker:
    # the add answers, nothing written. The wait is made 30 s here, so only the close can end it
    opener, data_dir, user_files_dir = _library(language)
    monkeypatch.setattr(ls, "BUSY_AT_OPEN", 30.0)
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    with monkeypatch.context() as patched:
        busy = _busy_on_the_worker(patched)                           # the worker's own opens: busy, every one
        answers = []
        assert looks.add(_folder(language), answers.append)
        assert h.until(lambda: len(busy) >= 3, seconds=10), "the worker is asking again"
        closed = time.monotonic()
        looks.close()
        assert h.until(lambda: answers, seconds=10), "the close ended the wait"
        took = time.monotonic() - closed
    assert took < 10 and answers[0]["refused"] == "busy" and answers[0]["root"] is None, (took, answers)
    assert _sources(language, data_dir, user_files_dir) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_start_fresh_on_a_store_still_busy_answers_busy_never_no_library(language, monkeypatch):
    # why: Settings' *Start a fresh library* reads "no-library" as "your library isn't open"; a busy store is busy
    opener, _data_dir, _user_files_dir = _library(language)
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    _busy_on_the_worker(monkeypatch)
    answers = []
    try:
        assert looks.fresh(False, answers.append)
        assert h.until(lambda: answers, seconds=10)
    finally:
        looks.close()
    assert answers[0]["refused"] == "busy" and not answers[0]["done"], answers[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_damaged_store_answers_its_reason_at_once_never_no_library(language):
    # why: a store marked for repair is read-only — said, nothing copied in, and no wait for a busy moment to pass
    opener, data_dir, _user_files_dir = _library(language)
    ls.mark_damaged(ls.library_db_path(language, data_dir), "test: marked")
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    try:
        answer = _added(looks, _folder(language))
    finally:
        looks.close()
    assert answer["refused"] == "damaged", answer


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_with_no_store_still_answers_no_library(language):
    # why (S3, kept): a 2.x library with no 3.0 store is the one case + Add copies the folder in, as before
    data_dir, user_files_dir, doc = library(language, shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    assert opener.check() == "json"
    looks = source_looks.SourceLooks(opener, language, kind=lambda _p: "network")
    try:
        answer = _added(looks, _folder(language))
    finally:
        looks.close()
    assert answer["refused"] == "no-library", answer
