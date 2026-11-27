"""The whole first run, driven the way a learner drives it (ONB-FIX, 3.0.20: the cut's C14 found three bugs every
page-level test had passed, because no test walked the real setup from a fresh profile).

The real main window on a fresh test root (`shell.open_window`), the real setup wizard over it (`first_run.host`) and
the real services behind it (`setup_wizard`: the store, the first look, New arrivals, the sort, D1's first-cards line,
*Your start*), the window's real indexer (a child process, as in the app), on a library of three made-up shows of real
subtitles (tests/Test Resources/, ja and zh). It presses what a learner presses — the language, *Start fresh*,
*Choose a folder…*, covers off, *Next* on each page, the newest show, *Soon* for the rest and *Done*, *Generate*, then
*Start* — and waits the way a learner waits: for *Next* to be there, never by calling a page's method.

What a wrong answer costs a new learner: a page with tiles and no *Next* (only Back and Skip: he thinks setup is
stuck), *How would you like to start?* skipped (his first cards decided without him), *Your list* stuck on
*Counting your shows…* over an empty chart.

Fakes, and why (each where the real thing would reach outside the test, or take minutes):
  * the folder dialog answers with the test's folder (the system's own dialog can't be pressed offscreen);
  * Anki Miner's look answers *ready* (`FakeMiner`), and Anki is a dead loopback port: the real Anki is never reached;
  * the window's Generate is accepted and left running (`api.generate` recorded, no analyzer child): with *Your start*
    offered the wizard goes on at once, so the list's end is never waited for — the real Generate is
    `test_services_generate.py`'s; without it the wizard waits on *Your list* (the bug this test would see);
  * *Start*'s answer is recorded (`api.start_cards`), never Connect's own start (it would start Anki Miner).
"""
import os
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.qt import first_run, shell, windows
from app.qt import wizard as W
from tests.qt.conftest import wait_until
from tests.qt.test_wizard import FakeMiner, miner_look
from tests.test_sources_scan import RESOURCES, _drive, _write

DEAD_ANKI = "http://127.0.0.1:9"          # the discard port: AnkiConnect never answers (the real Anki is never asked)
# made-up shows, newest first by their files' dates (the order *What are you watching right now?* must show)
SHOWS = {"ja": (("星祭りの夜", 2), ("星屑ステーション", 2), ("夜明けの旅団", 2)),
         "zh": (("夜市的灯", 2), ("星光车站", 2), ("黎明旅团", 2))}
PRESS_WAIT = 20.0                        # s a learner waits for *Next* on a page before he thinks setup is stuck
READ_WAIT = 90.0                         # s for the real read (the scan, the indexer child) on six files
COUNT_WAIT = 60.0                        # s *Your list* may say *Counting your shows…* (its asks: 3, 6, 12, 24 s on)


class RealApi:
    """The real setup services (`setup_wizard`), but for the two calls that would leave the test (see the module's
    docstring): `generate` and `start_cards` are recorded."""

    def __init__(self):
        self.real = W.services_api()
        self.generated = []
        self.started = []

    def __getattr__(self, name):
        return getattr(self.real, name)

    def generate(self, services):
        self.generated.append(time.monotonic())
        return True

    def start_cards(self, *args, **kwargs):
        self.started.append((args, kwargs))
        return []


SUBTITLES = {"ja": ("placed_episode.srt", "phrases_sample.srt", "readings_sample.srt", "utterances_sample.srt",
                     "verses_sample.srt", "repeated_lines.ja.srt"),
             "zh": ("night_market.srt",)}


def _episode(language, n, show):
    """An episode's real subtitles (Test Resources), its last cue naming the show and the episode: no two files are
    the same bytes (the same bytes twice are one episode, SRC-7)."""
    with open(os.path.join(RESOURCES, language, SUBTITLES[language][n % len(SUBTITLES[language])]),
              encoding="utf-8-sig") as f:
        text = f.read().rstrip()
    return f"{text}\n\n{900 + n}\n00:59:{n:02d},000 --> 00:59:{n:02d},800\n{show} {n + 1}\n"


def _library(language):
    """Three shows of real subtitles, two episodes each, a show's files a day older than the show before it."""
    root = _drive(f"first-run-{language}")
    n = 0
    for rank, (show, episodes) in enumerate(SHOWS[language]):
        for e in range(1, episodes + 1):
            _write(os.path.join(root, show, f"{show} - {e:02d}.{language}.srt"), _episode(language, n, show),
                   age=60 + rank * 86400 + (episodes - e) * 60)
            n += 1
    return root


@pytest.fixture
def window(qapp, monkeypatch, real_store_helper):
    """The real main window on the test's fresh root, Anki a dead port; its indexer on and its store built by its own
    helper, as the app's start does 1.5 s in (`Chores.started`: under the suites' no-timers switch, asked here)."""
    monkeypatch.delenv("SURASURA_NO_AUTOINDEX", raising=False)          # the window's real indexer reads the words
    monkeypatch.setattr(windows, "open_url", lambda url: None)          # (the ⭐ link: never a browser)
    services = shell.open_services()                                   # (as `main` makes them: the library, the writer)
    services.settings.set({"anki_connect_url": DEAD_ANKI}, now=True)
    win = shell.open_window(qapp, services)
    win.resize(1280, 800)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()
    services.shutdown(2.0)


def _open_as_the_app_does(win):
    """The window's first frame (`main` → `start_duties`: the duties made and started, setup's wizard kept), then its
    store's helper as the start asks it 1.5 s in — a fresh profile's store built from nothing (`Chores.started`: under
    the suites' no-timers switch, asked here)."""
    services = win.services
    win.start_duties()
    assert wait_until(lambda: services.chores is not None and services.started, READ_WAIT), "the duties never started"
    _store_built(win, "ja")


def _store_built(win, language):
    """The store's helper for `language` (the window's start, or its switch to another language, asks it 2 s on:
    `Chores._schedule_maintain`, off under the suites' no-timers switch), and its writer ready to take the first look."""
    services = win.services
    assert wait_until(lambda: services.language == language and services.chores.language == language, PRESS_WAIT)
    services.chores.worker.put(services.chores._maintain)
    assert wait_until(lambda: services.writer is not None and services.writer.language == language
                      and services.writer.can_write(), READ_WAIT), f"the window's {language} store was never built"


def _next(wiz, page_id, wait=PRESS_WAIT, problems=None):
    """The learner's *Next* on `page_id`: he waits until *Next* is there (shown, live, the page settled), then clicks
    it. A *Next* that never comes is a problem (`problems`, else it fails here), naming the page and what the footer
    shows instead — then he does what C14's learner did to go on: *Back*, then *Next* again."""
    assert wiz.page.id == page_id, f"expected {page_id}, setup shows {wiz.page.id}"
    if not wait_until(lambda: _next_there(wiz), wait):
        footer = [b.text() for b in (wiz.btn_back, wiz.btn_skip, wiz.btn_next) if b.isVisible()]
        assert problems is not None, f"no Next on {page_id}: the footer shows {footer}"
        problems.append(f"no Next on {page_id}: the footer shows {footer}")
        _click(wiz, wiz.btn_back)
        _next(wiz, wiz.page.id, wait)
        _on(wiz, page_id)
        assert wait_until(lambda: _next_there(wiz), wait), f"no Next on {page_id} even after Back and Next"
    _click(wiz, wiz.btn_next)


def _next_there(wiz):
    return wiz.btn_next.isVisible() and wiz.btn_next.isEnabled() and wiz.settled()


def _click(wiz, button):
    assert wait_until(wiz.settled, PRESS_WAIT)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def _on(wiz, page_id, wait=PRESS_WAIT):
    assert wait_until(lambda: wiz.page.id == page_id and wiz.waits() is None and wiz.covered is None, wait), \
        f"expected {page_id}, setup shows {wiz.page.id} (waiting: {wiz.waits()})"


def _sort_the_rest(wiz, wait=READ_WAIT):
    """The sort screen: every show left goes to *Soon*, then *Done* (as C14's learner did)."""
    from app.qt import sort_screen
    assert wait_until(lambda: isinstance(wiz.covered, sort_screen.SortScreen), wait), "the sort never opened"
    screen = wiz.covered
    for _ in range(10):
        if screen.top_arrival() is None:
            break
        before = screen.top_arrival().key
        QTest.mouseClick(screen.choice_buttons["soon"], Qt.MouseButton.LeftButton)
        wait_until(lambda: screen.top_arrival() is None or screen.top_arrival().key != before, 5.0)
    QTest.mouseClick(screen.btn_done, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: wiz.covered is None, wait), "the sort's Done never closed it"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_whole_first_run_shows_next_your_start_and_your_lists_numbers(window, language):
    problems = []                         # what a learner would see as broken (all of them said at the end)
    api = RealApi()
    wiz = first_run.host(window, api=api, miner=FakeMiner(miner_look("ready", version="3.9.0")))
    assert isinstance(wiz, W.SetupWizard)
    _open_as_the_app_does(window)
    folder = _library(language)

    # Language: the glyph tiles, then Next
    _on(wiz, "language")
    wiz.pages[0].channel.choose(language, user=True)
    _next(wiz, "language", problems=problems)
    if language != "ja":
        _store_built(window, language)                             # (the window follows the language picked)
    # What you know (Anki isn't answering): *Start fresh*
    _on(wiz, "known")
    wiz.by_id["known"].channel.choose("fresh", user=True)
    _next(wiz, "known", problems=problems)
    # Your shows: the folder, covers off (no AniList), Next — the read starts behind the pages
    _on(wiz, "shows")
    page = wiz.by_id["shows"]
    wiz.pick_dialog = lambda _title, _start: folder
    _click(wiz, page.btn_pick)
    assert wait_until(lambda: page.folders, PRESS_WAIT), "the folder was never listed"
    if page.covers.switch.isChecked():
        _click(wiz, page.covers.switch)
    assert not page.covers.switch.isChecked()
    _next(wiz, "shows", READ_WAIT)                                 # (the first look: a few seconds on six files)
    # Card order, then *Cards that make themselves* (Anki Miner ready: *Cards made for you as you watch* on). He
    # reads this page for a while (C14: ~8 s): on a small library the read behind ends meanwhile
    _on(wiz, "order")
    _next(wiz, "order", problems=problems)
    _on(wiz, "cards")
    assert wait_until(lambda: wiz.by_id["cards"].ready(), PRESS_WAIT)
    assert wiz.by_id["cards"].make.isChecked()
    assert wait_until(lambda: wiz._read_done, READ_WAIT), "the read behind the pages never ended"
    _next(wiz, "cards", problems=problems)

    # 1. *What are you watching right now?*: the tiles, newest first, and *Next* there once they are
    _on(wiz, "watching", READ_WAIT)
    watching = wiz.by_id["watching"]
    assert wait_until(lambda: any(t.isVisible() for t in watching.tiles), READ_WAIT), "no show tiles came"
    assert [t.title for t in watching.tiles if t.isVisible()] == [s for s, _n in SHOWS[language]]
    _next(wiz, "watching", problems=problems)                      # (bug 1: only Back and Skip were there)
    _sort_the_rest(wiz)

    # 3. *Your list*: its numbers come (never *Counting your shows…* for good over an empty chart)
    _on(wiz, "level", READ_WAIT)
    level = wiz.by_id["level"]
    if not wait_until(level.counted, COUNT_WAIT):
        problems.append(f"Your list still says {level.counting.text()!r} after {COUNT_WAIT:.0f} s, its chart empty")
    else:
        assert level.numbers_part.isVisible() and not level.counting.isVisible()

    # 2. *How would you like to start?* straight through: Generate goes on to it
    _next(wiz, "level", problems=problems)
    assert wait_until(lambda: api.generated, PRESS_WAIT)
    if not wait_until(lambda: wiz.page.id == "start", PRESS_WAIT):
        problems.append(f"How would you like to start? was skipped: setup stays on {wiz.page.id}, "
                        f"saying {wiz.say_line.accessibleName()!r}")
    else:
        start = wiz.by_id["start"]
        assert wait_until(lambda: any(c.isVisible() for c in start.cards.values()), PRESS_WAIT)
        _next(wiz, "start", problems=problems)
        assert wait_until(lambda: api.started, PRESS_WAIT), "Start never answered the first cards"
        assert wait_until(lambda: first_run.opened(window) is None, PRESS_WAIT)
    assert not problems, "\n".join(problems)
