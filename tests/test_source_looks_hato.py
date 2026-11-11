"""hato's runs on a worker of their own (Minato-SM, 2026-11-12; Michi-SIGN's note on the hato contract §7.8): the
window's looks hand the videos still waiting for a subtitle to hato (`no_subs.find`), whose `--wait` queues behind
another hato run's lock for up to 3 hours, saying only that it waits. That run sat on the source looks' tracks worker, so for those
hours no next look's video got its own text track copied out (`tracks.fill`).

What a wrong answer would cost a learner: a video he drops in with its subtitles inside it stays *No subtitles yet* for
hours, only because hato's tray happens to be busy with another folder.

Here hato's run is a stand-in that waits as a queued `--wait` does (until it is let go, or the window closes), on the
real store and the real looks' workers; the library holds a real waiting video (no subtitle beside it) in each language.
"""
import os
import threading
import time

import pytest

from app import library_store as ls
from app.services import source_looks
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _video, _waiting  # noqa: F401

_SHOW = {"ja": "図書館の午後", "zh": "夜市小记"}
WAIT_S = 30.0                                       # a bound, never a pause: every wait below ends on its event
NOTHING = {"asked": 0, "found": 0, "not_found": 0, "failed": 0, "roots": {}}


class _Hato:
    """`no_subs.find`'s stand-in: each run says it started, then waits as a run queued behind another hato's lock —
    until the test lets it go (`free`) or the window closes (`stop()`, as `_hato_run` polls it)."""

    def __init__(self, answers=(), events=None):
        self.answers = list(answers)                 # the runs' answers in turn; then one that found nothing
        self.events = events
        self.runs, self.stopped, self.threads = 0, 0, []
        self.started = threading.Event()
        self.free = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, store, language, settings=None, stop=None, now=None, away=(), popen=None):
        with self._lock:
            self.runs += 1
            self.threads.append(threading.current_thread().name)
            if self.events is not None:
                self.events.append(("hato", self.runs))
            answer = self.answers.pop(0) if self.answers else dict(NOTHING)
        self.started.set()
        deadline = time.monotonic() + WAIT_S
        while not self.free.wait(0.05):
            if stop():
                with self._lock:
                    self.stopped += 1
                return {}
            if time.monotonic() > deadline:
                return {}
        return answer


class _Fills:
    """`tracks.fill`'s stand-in: counts the fills and lets the test wait for the n-th."""

    def __init__(self, events=None):
        self.n, self.events = 0, events
        self._cv = threading.Condition()

    def __call__(self, store, language, settings=None, stop=None, away=(), **_kw):
        with self._cv:
            self.n += 1
            if self.events is not None:
                self.events.append(("fill", self.n))
            self._cv.notify_all()
        return {}

    def reach(self, n, timeout=WAIT_S):
        with self._cv:
            return self._cv.wait_for(lambda: self.n >= n, timeout)


def _looks(language, monkeypatch, hato, fills):
    """A library with one real waiting video, and the window's looks over it with hato and the fill stood in."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _video(os.path.join(src, _SHOW[language], f"[Grp] {_SHOW[language]} - 03 (1080p).mkv"))
    with store:
        root = store.add_source(src)
    monkeypatch.setattr(source_looks.tracks, "fill", fills)
    monkeypatch.setattr(source_looks.no_subs, "find", hato)
    looks = source_looks.SourceLooks(ls.StoreOpener(language, data_dir, store.user_files_dir), language,
                                     kind=lambda _p: "network")
    return looks, store, data_dir, root


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_hato_run_waiting_behind_another_never_holds_the_next_track_fill(language, monkeypatch):
    """Why: the run queued behind hato's lock waits on hato's own worker — the next look's track fill runs meanwhile
    (red before: the fill waited on the same worker for the whole of hato's wait)."""
    hato, fills = _Hato(), _Fills()
    looks, store, data_dir, _root = _looks(language, monkeypatch, hato, fills)
    try:
        looks.asked(refreshed=True)
        assert hato.started.wait(WAIT_S), "hato was never asked after the first fill"
        with ls.open_store(language, data_dir, store.user_files_dir) as s:
            assert _waiting(s) == 1                  # the video waits: hato had something to look for
        looks.asked(refreshed=True)                  # a look while hato still waits
        assert fills.reach(2), "the next look's track fill waited for hato"
        assert hato.runs == 1 and not hato.free.is_set()
        assert hato.threads == [f"window-hato-{language}"]
        hato.free.set()
        assert looks.idle(WAIT_S)
    finally:
        hato.free.set()
        looks.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_asks_while_hato_waits_are_folded_into_one_run_after_it(language, monkeypatch):
    """Why: hato holds one run at a time anyway (its own lock); every fill meanwhile asks again, and those asks become
    one more run once the waiting one ends — never one run per look, never none (a video that came meanwhile is
    asked)."""
    hato, fills = _Hato(), _Fills()
    looks, _store, _data_dir, _root = _looks(language, monkeypatch, hato, fills)
    try:
        looks.asked(refreshed=True)
        assert hato.started.wait(WAIT_S)
        looks.asked(refreshed=True)
        assert fills.reach(2)
        looks.asked(refreshed=True)
        assert fills.reach(3)
        assert looks._worker.idle(WAIT_S) and looks._tracks.idle(WAIT_S)
        assert hato.runs == 1
        hato.free.set()
        assert looks.idle(WAIT_S)
        assert hato.runs == 2 and fills.n == 3
    finally:
        hato.free.set()
        looks.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_hato_is_asked_only_after_a_fill_has_had_its_turn(language, monkeypatch):
    """Why: a video's own text track goes first (Michi-ST) — hato is never asked about a video before the fill of the
    same look looked inside it."""
    events = []
    hato, fills = _Hato(events=events), _Fills(events)
    hato.free.set()
    looks, _store, _data_dir, _root = _looks(language, monkeypatch, hato, fills)
    try:
        looks.asked(refreshed=True)
        assert looks.idle(WAIT_S)
        assert events == [("fill", 1), ("hato", 1)]
    finally:
        looks.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_window_closing_stops_a_waiting_hato_run_and_lets_its_worker_go(language, monkeypatch):
    """Why: a run waiting for hours must end with the window (`stop`, the run killed: `_hato_run`), and its worker's
    thread and store handle go with it — never a thread left behind holding the library open."""
    hato, fills = _Hato(), _Fills()
    looks, _store, _data_dir, _root = _looks(language, monkeypatch, hato, fills)
    closed = []
    real_let_go = looks._let_go
    monkeypatch.setattr(looks, "_let_go", lambda *a: (closed.append(threading.current_thread().name),
                                                      real_let_go(*a)))
    try:
        looks.asked(refreshed=True)
        assert hato.started.wait(WAIT_S)
    finally:
        looks.close()
    thread = looks._hato._thread
    thread.join(WAIT_S)
    assert not thread.is_alive(), "hato's worker outlived the window"
    assert hato.stopped == 1 and not hato.free.is_set()
    assert f"window-hato-{language}" in closed       # its own store handle let go on its own thread


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_hato_wrote_into_is_looked_at_again(language, monkeypatch):
    """Why (K5): what hato wrote beside a video is taken in by that folder's next look — asked from hato's worker as
    it was from the fill's."""
    looks = None
    hato, fills = _Hato(), _Fills()
    hato.free.set()
    looked = []
    try:
        looks, _store, _data_dir, root = _looks(language, monkeypatch, hato, fills)
        hato.answers = [dict(NOTHING, asked=1, found=1, roots={root: _drive("driveA")})]
        real_look_at = looks.look_at
        monkeypatch.setattr(looks, "look_at", lambda r, language=None: (looked.append(r), real_look_at(r))[1])
        looks.asked(refreshed=True)
        assert hato.started.wait(WAIT_S)
        deadline = time.monotonic() + WAIT_S
        while hato.runs < 2 and time.monotonic() < deadline:      # the folder's look, its fill, hato again
            looks.idle(1.0)
        assert looks.idle(WAIT_S)
        assert looked == [root] and hato.runs == 2 and fills.n == 2
    finally:
        if looks is not None:
            looks.close()
