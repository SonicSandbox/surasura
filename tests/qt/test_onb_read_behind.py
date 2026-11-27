"""ONB-2 + ONB-3 (Sonic § 102, ~13:4x): setup goes on while the library is read behind its pages, a loading page only
inside a step that needs the read, and *What are you watching right now?* before the sort.

  * *Your shows*' Next with folders starts the read (`LoadRun(behind=True)`: the scan, the covers, the words, Anki's
    and YouTube's waits) and goes straight on to *Card order*: no cover over setup.
  * Only *Watching now* (the scan's shows) and *Your list* (every word) wait — inside their page, the load screen in
    the page's place: the steps, *Back* and *Finish later* stay live; its *Stop* keeps what was read and goes on.
  * A folder that can't be read: *Your shows* gets the amber dot in the steps, the rest goes on. Nothing found:
    *Watching now* is passed by. Setup closed mid-read: the look stops between files. Page 1's language switched
    mid-read: that read is let go.
  * *Watching now*: the newest show pre-picked; *Next* puts it at the top of Current through New arrivals' call, marks
    the episodes before *I'm on* watched, then the sort opens with its Current picks in under the show.

What a wrong answer would cost a learner: a setup that sits on a loading screen it no longer needs, a dead Back, a
read that never ends its wait, a show placed below the ones he sorts after it, or cards for episodes he has seen.

The wizard over its stand-in window (test_wizard's `make`), the real store and first look on real Japanese subtitles
(tests/Test Resources/, made-up show names); the window's chores, covers and writer are recording stand-ins.
"""
import os
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.qt import arrivals as qarrivals
from app.qt import windows
from app.qt import sort_screen
from app.qt import wizard as W
from app.qt import wizard_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_wizard import FakeFetch, make, rest  # noqa: F401
from tests.qt.test_wizard_load import Chores, _covers, _shows
from tests.qt.test_wizard_sources import (SHOWS, SourcesApi, _fresh_look_state, _folder, _items,  # noqa: F401
                                          _pick, empty_library)
from tests.test_sources_scan import _drive


class HeldApi(SourcesApi):
    """The real first look, held at its start until `gate` is set (a slow read); `failed` added to what it says."""

    def __init__(self, failed=(), **kw):
        super().__init__(**kw)
        self.gate = threading.Event()
        self.gate.set()
        self.failed = list(failed)
        self.rows_asked, self.searched = [], []
        self.newest = None
        self.furthest = None                                           # `reopen_at`'s answer (the page saved last)

    def reopen_at(self, settings):
        return self.furthest

    def read_folders(self, language, paths, progress=None, stop=None, **kw):
        self.gate.wait(20)
        got = super().read_folders(language, paths, progress, stop, **kw)
        if self.failed:
            got = dict(got, failed=list(got.get("failed") or ()) + self.failed)
        return got

    def watching_rows(self, language, rows):
        self.rows_asked.append(list(rows))
        return list(self.newest if self.newest is not None else rows)

    def watching_search(self, language, rows, query):
        self.searched.append(query)
        return [r for r in rows if query in r.title]


def _start(make, tmp_path, api=None, chores=True, runs=False):
    wiz, shell, api, settings, _m = make(api=api or HeldApi())
    if chores:
        shell.services.chores = Chores(str(tmp_path / "indexer-window.log"), runs=runs)
    _covers(shell, counts=())
    _walk(wiz, "shows")
    _pick(wiz, _folder("anime", SHOWS))
    return wiz, shell, api


def _walk(wiz, page_id):
    """Next (or Skip) until `page_id` shows (setup's own presses, each page's preselects)."""
    for _ in range(12):
        if wiz.page.id == page_id:
            return
        wiz.page.entered()
        wait_until(lambda: not wiz._anki_looking, 2.0)
        if wiz.page.id == "cards":
            wait_until(lambda: wiz.page.look is not None, 2.0)
        (wiz.next if wiz.page.next_offered() else wiz.skip)()
    assert wiz.page.id == page_id


def _waiting(wiz):
    return wiz.waiting is not None and wiz.stack.currentWidget() is wiz.waiting


# --- ONB-2: the read behind ------------------------------------------------------------------------------------ #
def test_your_shows_next_goes_straight_on_while_the_library_is_read_behind(make, empty_library, tmp_path):
    wiz, shell, api = _start(make, tmp_path)
    api.gate.clear()                                                   # the read is slow: it can't be done yet
    wiz.next()
    assert wiz.page.id == "order" and wiz.covered is None, "never a cover over setup"
    assert wiz.reading is not None and isinstance(wiz.waiting, sort_screen.LoadScreen)
    assert not _waiting(wiz) and not wiz.held(), "Card order needs nothing of the library"
    assert wiz.btn_next.isEnabled() and wiz.btn_back.isVisible()
    _walk(wiz, "cards")
    api.gate.set()
    assert wait_until(lambda: wiz.reading is None and wiz._read_done, 30)
    assert len(_items()) == sum(SHOWS.values())                        # every episode read, behind the pages


def test_watching_now_waits_for_the_shows_inside_its_page_with_back_live(make, empty_library, tmp_path):
    wiz, shell, api = _start(make, tmp_path)
    api.gate.clear()
    wiz.next()
    _walk(wiz, "watching")
    assert _waiting(wiz) and wiz.waits() == "scan"
    assert wiz.steps.isVisible() and wiz.btn_back.isVisible() and not wiz.btn_next.isVisible()
    assert not wiz.btn_skip.isVisible(), "the load screen's own Stop is the way on"
    wiz.enter()
    assert wiz.page.id == "watching", "Enter takes nothing while it waits"
    wiz.back()
    assert wiz.page.id == "cards" and not _waiting(wiz)
    wiz.next()
    assert wiz.page.id == "watching" and _waiting(wiz)
    api.gate.set()
    assert wait_until(lambda: not _waiting(wiz), 30)                   # the scan ended: the page itself
    assert wiz.stack.currentWidget() is wiz.stack.widget(wiz.index)


def test_your_list_waits_for_every_word_and_its_stop_keeps_what_was_read(make, empty_library, tmp_path):
    wiz, shell, api = _start(make, tmp_path, runs=True)                # the indexer runs and doesn't end
    wiz.next()
    assert wait_until(lambda: wiz.reading is None, 30)
    assert wait_until(lambda: (wiz._load or {}).get("step") == "index", 10), "the covers first, then the words"
    wiz._go(wiz.pages.index(wiz.by_id["watching"]))
    assert wiz.waits() is None and not _waiting(wiz), "Watching now waits on the scan alone, never on the words"
    wiz._go(wiz.pages.index(wiz.by_id["level"]))
    assert wiz.waits() == "index" and _waiting(wiz)
    assert wiz.waiting.task.text() == S.LOAD_INDEX_START
    QTest.mouseClick(wiz.waiting.btn_stop, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: not _waiting(wiz), 5) and wiz._read_done and wiz.waiting is None
    assert wiz.page.id == "level" and len(_items()) == sum(SHOWS.values())
    wiz.back()
    assert wiz.page.id != "level", "Back works from the page it waited on"


def test_a_folder_that_cant_be_read_puts_the_amber_dot_on_your_shows_and_the_rest_goes_on(make, empty_library,
                                                                                           tmp_path):
    wiz, shell, api = _start(make, tmp_path, api=HeldApi(failed=[(r"Z:\gone", "not there")]))
    wiz.next()
    assert wiz.page.id == "order"
    assert wait_until(lambda: "shows" in wiz.steps.warned, 30)
    assert S.STEP_WARN_NAME.format(name=S.STEPS["shows"]) in wiz.steps.accessibleDescription()
    assert len(_items()) == sum(SHOWS.values()), "the folder that could be read was read"
    wiz._go(2)
    assert wiz.page.id == "shows" and not wiz.page.refused_line.isHidden() or not wiz.page.reading_line.isHidden()


def test_nothing_found_passes_watching_now_by_and_your_list_waits_for_nothing(make, empty_library, tmp_path):
    wiz, shell, _api, _settings, _m = make(api=HeldApi())
    _walk(wiz, "shows")
    _pick(wiz, _drive("nothing-here"))
    wiz.next()
    assert wiz.page.id == "order"
    assert wait_until(lambda: wiz.reading is None and wiz._read_done, 30)
    _walk(wiz, "cards")
    _walk(wiz, "level")                                                # (one press from Cards made for you)
    assert wiz.pages.index(wiz.by_id["watching"]) in wiz.passed and wiz.waits() is None and not _waiting(wiz)
    assert _items() == []
    wiz.back()
    assert wiz.page.id == "cards", "passed by going back too"
    wiz.next()
    assert wiz.page.id == "level", "nothing to pick from: Watching now never shows"


def test_finish_later_mid_read_stops_the_look_between_files(make, empty_library, tmp_path):
    wiz, shell, api = _start(make, tmp_path)
    api.gate.clear()
    wiz.next()
    stop = wiz.reading
    finished = []
    wiz.finished.connect(finished.append)
    wiz.finish_later()
    assert finished == ["later"] and stop.is_set(), "the look stops between files; what it took in is kept"
    assert wiz._run is None and wiz.waiting is None, "the run let go: nothing of it lands on a closed setup"
    api.gate.set()


def test_another_language_picked_mid_read_lets_that_read_go(make, empty_library, tmp_path):
    wiz, shell, api = _start(make, tmp_path)
    api.gate.clear()
    wiz.next()
    stop = wiz.reading
    wiz._go(0)
    wiz._language_changed("zh")
    assert stop.is_set() and wiz._run is None and wiz.waiting is None and wiz.waits() is None
    api.gate.set()


# --- ONB-3: *What are you watching right now?* ------------------------------------------------------------------- #
@pytest.fixture
def placed(monkeypatch):
    """New arrivals' call and the writer's Watched record, recorded."""
    got = {"place": [], "watched": []}
    monkeypatch.setattr(qarrivals, "give_place", lambda moves, text, ids, where, keys=(), toast=True, ticket=None,
                        after=None: got["place"].append((list(ids), where)) or 7)
    return got


def _with_shows(wiz, shell, placed, titles=("月影の旅人", "風鈴の街", "星降る街の小さな工房")):
    groups = _shows(*titles)
    rows = list(groups[0].rows)
    rows = [r._replace(episodes=tuple(SimpleNamespace(id=i, label=f"第{k}話") for k, i in enumerate(r.item_ids, 1)))
            for r in rows]
    groups = (groups[0]._replace(rows=tuple(rows)),)
    shell._arrivals_view = SimpleNamespace(arrivals=tuple(rows), arrival_groups=groups)
    shell.moves = SimpleNamespace(refused=lambda: None)
    shell.services.writer = SimpleNamespace(set_watched=lambda ids, label=None: placed["watched"].append(list(ids)),
                                            pending=lambda: 0)
    return rows


def test_watching_now_pre_picks_the_newest_and_puts_it_on_top_then_the_sort_goes_in_under_it(make, placed):
    wiz, shell, api, _s, _m = make(api=HeldApi())
    rows = _with_shows(wiz, shell, placed)
    api.newest = [rows[2], rows[0], rows[1]]                           # by the files' dates, not the tray's order
    _walk(wiz, "watching")
    page = wiz.page
    assert wait_until(lambda: page.rows is not None, 5)
    assert page.channel.value() == rows[2].key, "the newest show pre-picked"
    assert [t.title for t in page.tiles if t.isVisible()] == [rows[2].title, rows[0].title, rows[1].title]
    assert page.none.isVisible() and page.episode.isVisible()
    page.episode.set_value(1)                                          # on 第2話: 第1話 seen
    wiz.next()
    assert placed["place"] == [(list(rows[2].item_ids), "top")]
    assert placed["watched"] == [[rows[2].item_ids[0]]]
    assert isinstance(wiz.covered, sort_screen.SortScreen) and wiz.covered.after == rows[2].item_ids[-1]
    assert wiz.covered._current_end() == rows[2].item_ids[-1], "the sort's first Current pick goes in under it"
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    assert wiz.covered is None and wiz.page.id == "level"
    wiz.back()
    assert wiz.page.id == "watching" and page.channel.value() == rows[2].key, "the pick kept"
    wiz.next()
    assert len(placed["place"]) == 1, "the same pick again places nothing twice"
    assert wiz.covered.after == rows[2].item_ids[-1]
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)


def test_next_comes_with_the_tiles_when_they_land_after_the_page_opened(make, placed):
    # why (ONB-FIX, the 3.0.20 cut's C14): on a small library the read had ended before *Watching now* opened, so no
    # tick repainted the footer once its shows were read: the tiles came with only Back and Skip under them
    wiz, shell, api, _s, _m = make(api=HeldApi())
    rows = _with_shows(wiz, shell, placed)
    _walk(wiz, "watching")
    page = wiz.page
    assert wait_until(lambda: page.rows is not None, 5)
    page.rows = None                                               # (as the page opens, before its rows are read)
    wiz.paint_footer()
    assert not wiz.btn_next.isVisible() and wiz.btn_skip.isVisible()
    page.show_newest(rows)                                         # the newest shows' answer, and nothing else
    assert wiz.btn_next.isVisible() and any(t.isVisible() for t in page.tiles)


def test_none_of_these_places_nothing_and_the_sort_comes_as_before(make, placed):
    wiz, shell, api, _s, _m = make(api=HeldApi())
    _with_shows(wiz, shell, placed)
    _walk(wiz, "watching")
    page = wiz.page
    assert wait_until(lambda: page.rows is not None, 5)
    page.channel.choose(page.NONE, user=True)
    assert not page.episode.isVisible()
    wiz.next()
    assert placed["place"] == [] and placed["watched"] == []
    assert isinstance(wiz.covered, sort_screen.SortScreen) and wiz.covered.after is None


def _type(edit, text):
    """Typed into the box (QTest can't type kana: its key table is ASCII): the text and its `textEdited`."""
    edit.setText(text)
    edit.textEdited.emit(text)


def test_the_search_finds_a_show_that_isnt_shown_and_says_when_none_matches(make, placed):
    wiz, shell, api, _s, _m = make(api=HeldApi())
    rows = _with_shows(wiz, shell, placed)
    _walk(wiz, "watching")
    page = wiz.page
    assert wait_until(lambda: page.rows is not None, 5)
    _type(page.search.edit, "風鈴")
    assert wait_until(lambda: api.searched == ["風鈴"], 3), "one ask once typing pauses"
    assert wait_until(lambda: [t.title for t in page.tiles if t.isVisible()] == [rows[1].title], 3)
    assert page.channel.value() == rows[1].key
    _type(page.search.edit, "ないもの")
    assert wait_until(lambda: page.said.isVisible() and page.said.text() == S.WATCH_NO_HIT, 3)
    assert page.channel.value() == page.NONE


def test_a_single_title_picked_goes_on_without_an_empty_sort(make, placed):
    wiz, shell, api, _s, _m = make(api=HeldApi())
    _with_shows(wiz, shell, placed, titles=("月影の旅人",))
    _walk(wiz, "watching")
    assert wait_until(lambda: wiz.page.rows is not None, 5)
    wiz.next()
    assert wiz.covered is None and wiz.page.id == "level", "nothing left to sort: straight to Your list"


def test_the_step_list_shows_watching_now_between_cards_and_your_list(make):
    wiz, *_ = make()
    assert wiz.steps.ids[:7] == W.ORDER and W.ORDER.index("watching") == W.ORDER.index("level") - 1
    assert S.STEPS["watching"]


# --- session 2: the tiles as the design draws them, the view that comes late, YouTube alone, reopening ---------- #
def test_the_shows_are_poster_tiles_in_one_row_as_many_as_the_width_holds(make, placed):
    """Why (the approved design, step 6): the shows are covers in a row, each with its title and line under it, the
    rest said as *N more in the next step* — never a list of words one above another. A narrow window shows fewer
    tiles (never a second row or a cut one); the search still finds the rest."""
    wiz, shell, api, _s, _m = make(api=HeldApi())
    rows = _with_shows(wiz, shell, placed)
    _walk(wiz, "watching")
    page = wiz.page
    assert wait_until(lambda: page.rows is not None, 5)
    shown = [t for t in page.tiles if t.isVisible()]
    assert all(isinstance(t, W.ShowTile) for t in page.tiles) and len(shown) == 3
    assert [t.cover for t in shown] == [r.cover for r in rows] and shown[0].line == rows[0].line
    assert len({t.y() for t in shown}) == 1, "one row"
    assert page.more.isVisible() and page.more.text() == S.WATCH_MORE.format(n=2), "the sort's: all but the pick"
    page.channel.choose(page.NONE, user=True)
    page._show_more()
    assert page.more.text() == S.WATCH_MORE.format(n=3)
    page._fits = lambda: 2                                             # the window made narrow
    QApplication.sendEvent(page, QResizeEvent(page.size(), page.size()))
    assert [t.title for t in page.tiles if t.isVisible()] == [rows[0].title, rows[1].title]
    del page._fits                                                     # wide again: all three
    QApplication.sendEvent(page, QResizeEvent(page.size(), page.size()))
    assert len([t for t in page.tiles if t.isVisible()]) == 3


def test_shows_that_reach_new_arrivals_after_the_scan_fill_the_page_then(make, placed):
    """Why (the race found in session 2): the scan ends before the window's view holds its shows — *Watching now* was
    passed by (nothing to pick yet) or showed no tiles for good. The scan's own count keeps the step, and the view's
    arrival (`library_changed`) reads the shows again."""
    wiz, shell, api, _s, _m = make(api=HeldApi())
    wiz._read_ids = [11, 12]                                           # the scan took files in; the view has none yet
    _walk(wiz, "watching")
    page = wiz.page
    assert wiz.page.id == "watching", "never passed by while the shows are on their way"
    assert wait_until(lambda: page.rows == [], 5) and not any(t.isVisible() for t in page.tiles)
    asked = len(api.rows_asked)
    wiz._library_moved(None)
    assert len(api.rows_asked) == asked, "the same view: nothing read again"
    rows = _with_shows(wiz, shell, placed)
    wiz._library_moved(shell._arrivals_view)
    assert wait_until(lambda: [t.title for t in page.tiles if t.isVisible()] == [r.title for r in rows], 5)
    assert page.channel.value() == rows[0].key


def test_youtube_alone_goes_on_and_watching_now_waits_for_its_videos(make, monkeypatch, placed, rest):
    """Why (ONB-2; the lead: YouTube-only setup moves behind if it is the same code): links alone went under the full
    cover. Now setup goes on as with folders; *Watching now* waits for the videos (they are the shows), Back live."""
    wiz, shell, api, _s, _m = make(api=HeldApi(), data={"enable_youtube_transcripts": True,
                                                         "youtube_risk_acknowledged": True})
    fetch = FakeFetch()
    monkeypatch.setattr(W, "_youtube_fetcher", lambda: fetch)
    monkeypatch.setattr(windows, "youtube_arrivals", lambda _shell, then=None: lambda paths: then(len(paths), 0, 0))
    _walk(wiz, "shows")
    page = wiz.page
    page.entered()
    assert wait_until(lambda: not page.btn_youtube.isHidden())
    page.btn_youtube.click()
    page.links.setPlainText("https://www.youtube.com/watch?v=eFwn9e8IYsI")
    wiz.next()
    assert wiz.covered is None and wiz.page.id == "order" and fetch.calls
    _walk(wiz, "watching")
    assert _waiting(wiz) and wiz.waits() == "youtube" and wiz.waiting.task.text() == S.LOAD_YOUTUBE
    assert wiz.btn_back.isVisible()
    rows = _with_shows(wiz, shell, placed, titles=("peko peko vlog",))
    fetch.ended([os.path.join("Processed", "peko peko vlog [eFwn9e8IYsI].txt")], [])
    assert wait_until(lambda: not _waiting(wiz) and wiz._read_done, 5)
    assert wait_until(lambda: wiz.page.channel.value() == rows[0].key, 5)


def test_videos_still_coming_dont_hold_watching_now_when_the_folders_brought_shows(make, monkeypatch, placed, rest,
                                                                                    empty_library, tmp_path):
    """Why (ONB-2): *Watching now* waits for YouTube's videos only when they are the only shows; with a folder's shows
    already in, the page shows them while the videos are still fetched behind it."""
    wiz, shell, api, _s, _m = make(api=HeldApi(), data={"enable_youtube_transcripts": True,
                                                         "youtube_risk_acknowledged": True})
    shell.services.chores = Chores(str(tmp_path / "indexer-window.log"), runs=False)
    _covers(shell, counts=())
    fetch = FakeFetch()
    monkeypatch.setattr(W, "_youtube_fetcher", lambda: fetch)
    monkeypatch.setattr(windows, "youtube_arrivals", lambda _shell, then=None: lambda paths: then(len(paths), 0, 0))
    _walk(wiz, "shows")
    _pick(wiz, _folder("anime", SHOWS))
    page = wiz.page
    page.entered()
    assert wait_until(lambda: not page.btn_youtube.isHidden())
    page.btn_youtube.click()
    page.links.setPlainText("https://www.youtube.com/watch?v=eFwn9e8IYsI")
    wiz.next()
    assert wait_until(lambda: (wiz._load or {}).get("step") == "youtube", 30), "the folder read, the videos to come"
    assert wiz._read_ids and wiz.fetching is not None
    _with_shows(wiz, shell, placed)
    _walk(wiz, "watching")
    assert wiz.waits() is None and not _waiting(wiz), "the folder's shows are there to pick from"
    fetch.ended([os.path.join("Processed", "peko peko vlog [eFwn9e8IYsI].txt")], [])
    assert wait_until(lambda: wiz._read_done, 5)


@pytest.mark.parametrize("furthest, opens, passed", [
    (None, "language", set()),
    ("shows", "order", {"language", "known", "shows"}),
    ("cards", "watching", {"language", "known", "shows", "order", "cards"}),   # (shown: the view may come later)
    ("level", "level", {"language", "known", "shows", "order", "cards", "watching"}),   # never past *Your list*
])
def test_setup_reopens_at_the_step_it_was_closed_on(make, furthest, opens, passed):
    """Why (design §3): closed mid-setup, setup came back on page 1. It opens after the furthest page saved with
    *Next*, the steps before it ticked."""
    api = HeldApi()
    api.furthest = furthest
    wiz, *_ = make(api=api)
    assert wiz.page.id == opens
    assert {wiz.pages[i].id for i in wiz.passed} == passed


# --- the review's fixes (session 2) --------------------------------------------------------------------------- #
def _three_episodes(wiz, shell, placed):
    rows = _with_shows(wiz, shell, placed)
    ids = (10, 11, 12)
    first = rows[0]._replace(item_ids=ids, episodes=tuple(SimpleNamespace(id=i, label=f"第{k}話")
                                                          for k, i in enumerate(ids, 1)))
    rows = [first] + rows[1:]
    shell._arrivals_view = SimpleNamespace(arrivals=tuple(rows), arrival_groups=shell._arrivals_view.arrival_groups)
    return rows


def test_a_changed_im_on_after_back_marks_the_episodes_before_it_watched(make, placed):
    """Why (review, state lens): the same show picked again after Back placed nothing, so a later *I'm on* never
    reached the store and cards were made for episodes he had marked as seen."""
    wiz, shell, api, _s, _m = make(api=HeldApi())
    rows = _three_episodes(wiz, shell, placed)
    _walk(wiz, "watching")
    page = wiz.page
    assert wait_until(lambda: page.rows is not None and page.channel.value() == rows[0].key, 5)
    page.episode.set_value(1)
    wiz.next()
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    wiz.back()
    assert wiz.page.id == "watching" and page.episode.value() == 1
    page.episode.set_value(2)
    wiz.next()
    assert placed["watched"] == [[10], [10, 11]]
    assert wiz.covered.after == 12
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)


def test_a_pick_that_cant_be_written_still_opens_the_sort(make, placed, monkeypatch):
    """Why (review, state lens): a raise in New arrivals' call left *Next* doing nothing on the page."""
    wiz, shell, api, _s, _m = make(api=HeldApi())
    _with_shows(wiz, shell, placed)

    def refused(*_a, **_kw):
        raise OSError("the library is read-only")
    monkeypatch.setattr(qarrivals, "give_place", refused)
    _walk(wiz, "watching")
    assert wait_until(lambda: wiz.page.rows is not None, 5)
    wiz.next()
    assert isinstance(wiz.covered, sort_screen.SortScreen) and wiz.covered.after is None
    assert placed["watched"] == [] and wiz._watch_placed is None
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)


def test_none_of_these_after_a_pick_keeps_the_sort_under_the_show_already_placed(make, placed):
    """Why (review, contract lens): the show placed by an earlier Next stays at Current's top; the sort's Current
    picks go in under it, never above it."""
    wiz, shell, api, _s, _m = make(api=HeldApi())
    rows = _with_shows(wiz, shell, placed)
    _walk(wiz, "watching")
    page = wiz.page
    assert wait_until(lambda: page.rows is not None, 5)
    wiz.next()
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
    wiz.back()
    page.channel.choose(page.NONE, user=True)
    wiz.next()
    assert wiz.covered.after == rows[0].item_ids[-1] and len(placed["place"]) == 1
    QTest.mouseClick(wiz.covered.btn_done, Qt.MouseButton.LeftButton)
