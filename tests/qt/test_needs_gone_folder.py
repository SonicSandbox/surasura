"""T6 in the window (Sonic 2026-10-24, alpha 2's first try: "Yes your lean is exactly what i'd do"): a source folder
that is GONE (moved or deleted while its drive is there) is a *Needs you* card — *Find its new folder…* · *Stop
reading it* · *Keep waiting* — never the offline line; a folder that is only AWAY (an unplugged drive, a NAS down)
keeps the offline line as before. 届 is amber while a gone card stands, and its press opens *Needs you* then (else
Sources, as every circle opens its settings). The card goes by itself when the folder comes back.

What a wrong answer would cost a learner (his real case: `Downloads\\Yomi no Tsugai` moved to `S:\\Video\\Anime\\…`,
already read): 届 amber with *Needs you* empty (alpha 2: nothing to do but wait for ever); *Find its new folder…* that
adds the show a second time, or stops reading the old folder when none of its episodes were found; *Stop reading it*
with no Undo, or one that moves or removes anything; an unplugged drive offered *Stop reading it*.

The window's seed (invented titles) through the stand-in store; Japanese and Chinese; the real case on a real store
and the real looks, with real subtitles from tests/Test Resources/ in the test's own root.
"""
import os
import shutil
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import settings_manager
from app.qt import stones, strings
from app.services import needs as service
from app.services import phase as phase_service
from app.services import source_looks
from app.services import standing as standing_service
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, open_window
from tests.test_library_store_support import LANGUAGES, names, roots

ARRIVALS = phase_service.ARRIVALS


class GoneWriter(FakeWriter):
    """The writer's `stop_reading` (T6), recorded and saved at once; with `store_of`, also written to that real store
    (the real case), and its Undo put back there."""

    def __init__(self, library=None, store_of=None):
        super().__init__(library, apply=False)
        self.store_of = store_of
        self.real = {}

    def stop_reading(self, root_id, label=None, language=None):
        if language is not None and language != getattr(self, "lang", language):
            return None
        if self.store_of is not None:
            store = self.store_of()
            try:
                self.real[root_id] = store.stop_source(root_id)
            finally:
                store.close()
        return self._put("stop_source", [], label, root=root_id, language=language)

    def undo(self, change=None, label=None):
        if self.store_of is not None and change is not None and change.op == "stop_source":
            store = self.store_of()
            try:
                store.undo(self.real.pop(change.kw["root"]))
            finally:
                store.close()
        return super().undo(change, label)


class Looks:
    """The looks as the card calls them: `find_new_folder` answered as asked (`answer`), listings counted."""

    def __init__(self, answer=None):
        self.answer = answer or {}
        self.finds, self.listings = [], 0
        self.on_result = self.on_progress = self.on_ended = None

    def find_new_folder(self, root_id, path, then=None, language=None):
        self.finds.append((root_id, path, language))
        out = {"old": root_id, "path": path, "root": 19, "refused": None, "failed": None, "result": {}, "state": "gone",
               "joined": 0, "stop": False, "language": language}
        out.update(self.answer)
        threading.Thread(target=then, args=(out,), daemon=True).start()
        return True

    def listing(self):
        self.listings += 1
        return True

    def folders(self, ids, then):
        then(dict.fromkeys(ids))
        return True

    def asked(self, **_kw):
        return False

    def set_shown(self, _shown):
        pass

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _stones_sheet(qapp):
    key = stones._key(1.0, "M")
    if key not in stones._SHEETS:
        stones._landed(key, stones.build(*key))


@pytest.fixture
def world(qapp):
    made = []

    def make(language="ja", looks=None, store_of=None):
        seed = window_seed.build(language=language)
        writer = GoneWriter(seed.library, store_of=store_of)
        writer.lang = language
        settings_manager.save_keys({"target_language": language})      # the window's language is its library's (P0)
        win, services = open_window(qapp, seed, writer)
        made.append((win, services))
        if looks is not None:
            services.source_looks = looks
            win._open_looks(None)
        return seed, win, writer, win.needs_you
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def _gone_row(language, root=13, items=12, finished=False, found_in=()):
    title = names(language)[71]
    return {"id": root, "path": os.path.join("C:\\Users\\Michael\\Downloads", title), "items": items, "on": True,
            "reachable": False, "gone": True, "shows": [title], "finished": finished, "found_in": list(found_in)}


def _away_row(root=7):
    return {"id": root, "path": "N:\\Media", "items": 412, "on": True, "reachable": False, "gone": False}


def _told(win, language, *rows):
    win._sources_looked({"language": language, "sources": [dict(r) for r in rows]})
    for _ in range(5):
        QApplication.processEvents()


def _cards(ny):
    return [e for e in ny.entries if e.kind == service.FOLDER_GONE]


def _button(ny, key, action):
    return next((b for b in ny.cards.buttons(key) if b.property("action") == action), None)


def _card_in(win, ny):
    assert wait_until(lambda: _cards(ny), 10)
    card = _cards(ny)[0]
    win.show_tab("needs")
    assert wait_until(lambda: _button(ny, card.key, "find_folder") is not None, 5)
    return card


# --- the card, the line, 届 -------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_gone_folder_is_a_needs_you_card_and_never_the_offline_line_an_away_drive_keeps_its_line(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    _told(win, language, _gone_row(language), _away_row())
    card = _card_in(win, ny)
    assert names(language)[71] in card.title and names(language)[71] in card.say
    assert [b.property("action") for b in ny.cards.buttons(card.key)] == ["find_folder", "stop_reading",
                                                                          "keep_waiting"]
    assert all(b.toolTip() for b in ny.cards.buttons(card.key))           # a tooltip on every button
    assert win.offline_line.text() == strings.SOURCES_OFFLINE.format(path="N:\\Media", n=412)    # the away one only
    assert len(_cards(ny)) == 1                                           # never a card for the away drive


@pytest.mark.parametrize("language", LANGUAGES)
def test_todoke_is_amber_while_a_gone_card_stands_and_its_press_opens_needs_you_else_sources(world, language,
                                                                                         monkeypatch):
    seed, win, writer, ny = world(language, looks=Looks())
    opened = []
    monkeypatch.setattr(win, "open_setting", lambda target, *a, **k: opened.append(target))
    _told(win, language, _gone_row(language))
    assert wait_until(lambda: _cards(ny), 10)
    assert win.phase.states[ARRIVALS].needs                               # amber
    assert win.phase.asks_in_window(ARRIVALS)
    assert strings.PHASE_PRESS_NEEDS in win.phase.hover_text(ARRIVALS)
    win._circle_pressed(ARRIVALS)
    assert win.current_tab() == "needs" and opened == []
    _told(win, language, _away_row())                                     # only away now: the line's amber, Sources
    assert not win.phase.asks_in_window(ARRIVALS)
    win.show_tab("current")
    win._circle_pressed(ARRIVALS)
    assert opened == ["library_folders"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_folder_coming_back_takes_its_card_and_the_amber_away_by_itself(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    row = _gone_row(language)
    _told(win, language, row)
    assert wait_until(lambda: _cards(ny), 10)
    _told(win, language, dict(row, reachable=True, gone=False))
    assert wait_until(lambda: not _cards(ny), 10)
    assert not win.phase.states[ARRIVALS].needs and win.offline_line.isHidden()


@pytest.mark.parametrize("language", LANGUAGES)
def test_keep_waiting_hides_the_card_until_the_folder_is_back_kept_across_restarts(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    row = _gone_row(language)
    _told(win, language, row)
    card = _card_in(win, ny)
    _button(ny, card.key, "keep_waiting").click()
    assert wait_until(lambda: not _cards(ny), 10)
    assert not win.phase.states[ARRIVALS].needs
    key = standing_service.offline_key(row["path"])
    assert wait_until(lambda: key in service.read_answered(language), 5)   # the seen file: kept across restarts
    assert writer.calls == []                                             # nothing written to the library


@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_reading_it_goes_through_the_writer_with_one_undo_and_the_folders_are_listed_again(world, language):
    looks = Looks()
    seed, win, writer, ny = world(language, looks=looks)
    _told(win, language, _gone_row(language))
    card = _card_in(win, ny)
    listed = looks.listings
    _button(ny, card.key, "stop_reading").click()
    assert wait_until(lambda: writer.saved, 5)
    assert [c for c in writer.calls if c[0] == "stop_source"] == [("stop_source", [], {"root": 13,
                                                                                      "language": language})]
    assert wait_until(lambda: looks.listings > listed, 5)                 # the card goes with the next listing
    assert win.toasts.card.isVisible() and names(language)[71] in win.toasts.card.base
    _button(ny, card.key, "stop_reading") and _button(ny, card.key, "stop_reading").click()   # a second press: none
    assert len([c for c in writer.calls if c[0] == "stop_source"]) == 1
    listed = looks.listings
    win.toasts.card.buttons[0].click()                                    # its Undo
    assert wait_until(lambda: writer.undone and writer.undone[-1].op == "stop_source", 5)
    assert wait_until(lambda: looks.listings > listed, 5)                 # ... and the card comes back with the listing


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_its_new_folder_starts_where_its_episodes_are_read_and_stops_the_old_folder_once_it_joined(world,
                                                                                                    language):
    new = os.path.join("S:\\Video\\Anime", names(language)[71])
    looks = Looks({"joined": 12, "stop": True})
    seed, win, writer, ny = world(language, looks=looks)
    _told(win, language, _gone_row(language, found_in=[new]))
    card = _card_in(win, ny)
    started = []
    ny.pick_folder = lambda title, start: started.append(start) or new
    _button(ny, card.key, "find_folder").click()
    assert started == [new]
    assert wait_until(lambda: [c for c in writer.calls if c[0] == "stop_source"], 5)
    assert looks.finds == [(13, new, language)]
    assert [c for c in writer.calls if c[0] == "stop_source"][0][2] == {"root": 13, "language": language}
    assert wait_until(lambda: win.toasts.card.isVisible() and new in win.toasts.card.base, 5)


@pytest.mark.parametrize("answer, said", [
    ({"joined": 0, "stop": False}, "NEEDS_FIND_NONE"),
    ({"refused": "That folder can't be read", "root": None}, "NEEDS_FIND_REFUSED"),
    ({"failed": "disk I/O error", "stop": False}, "NEEDS_FIND_FAILED"),
    ({"later": True, "stop": False}, "NEEDS_FIND_LATER"),
])
def test_find_its_new_folder_that_joins_nothing_stops_nothing_and_says_why(world, answer, said, monkeypatch):
    looks = Looks(answer)
    seed, win, writer, ny = world("ja", looks=looks)
    _told(win, "ja", _gone_row("ja"))
    card = _card_in(win, ny)
    heard = []
    monkeypatch.setattr(win, "say", lambda text, *a, **k: heard.append(text))
    ny.pick_folder = lambda title, start: "D:\\Elsewhere"
    _button(ny, card.key, "find_folder").click()
    assert wait_until(lambda: heard, 5)
    first = getattr(strings, said).split("{")[0]
    assert heard[-1].startswith(first), heard
    assert not [c for c in writer.calls if c[0] == "stop_source"]         # the old folder is still read


def test_find_its_new_folder_cancelled_asks_nothing(world):
    looks = Looks()
    seed, win, writer, ny = world("ja", looks=looks)
    _told(win, "ja", _gone_row("ja"))
    card = _card_in(win, ny)
    ny.pick_folder = lambda title, start: ""
    _button(ny, card.key, "find_folder").click()
    assert looks.finds == [] and writer.calls == []


# --- Sonic's real case, on a real store and the real looks --------------------------------------------------------- #
def _elsewhere(*parts):
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", *parts)
    os.makedirs(path, exist_ok=True)
    return path


@pytest.mark.parametrize("language", LANGUAGES)
def test_sonics_case_find_its_new_folder_joins_the_show_read_already_with_no_second_copy(world, language):
    """`Downloads\\<show>` gone; its new place `Video\\Anime\\<show>` already read (its look attached the episodes while
    the old folder was still there). The card names the folder and the show; *Find its new folder…* on the new place
    joins the episodes there — no item made, every row as it was — then stops reading the old folder (Undo reads it
    again, and the card comes back)."""
    from tests.test_library_store_sources import _empty, _scanned_show
    from tests.test_sources_scan import _look, _settle
    store, _data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    new = os.path.join(_elsewhere("Video", "Anime"), title)
    _scanned_show(language, os.path.dirname(old), title, 3)
    with store:
        root_a = store.add_source(old)
        _look(store, language, root_a, first=True)
        shutil.copytree(old, new, copy_function=shutil.copy2)
        _settle(new)
        root_b = store.add_source(new)
        assert _look(store, language, root_b)["attached"] == 3
        shutil.rmtree(old)
        before = store.conn.execute("SELECT id, tier, ord, rel_path, availability, work_id FROM items "
                                    "ORDER BY id").fetchall()
    data_dir, user_files_dir = roots(language)

    def store_of():
        return ls.open_store(language, data_dir, user_files_dir)
    looks = source_looks.SourceLooks(ls.StoreOpener(language, data_dir, user_files_dir), language,
                                     kind=lambda _p: "network")
    seed, win, writer, ny = world(language, looks=looks, store_of=store_of)
    win.refresh_sources()
    assert wait_until(lambda: any(r.get("gone") for r in win.sources), 30)
    card = _card_in(win, ny)
    assert title in card.title and title in card.say and "Downloads" in card.title
    assert win.phase.states[ARRIVALS].needs and win.offline_line.isHidden()
    ny.pick_folder = lambda _title, _start: new
    _button(ny, card.key, "find_folder").click()
    assert wait_until(lambda: [c for c in writer.calls if c[0] == "stop_source"], 30)
    assert wait_until(lambda: not _cards(ny), 30)                         # read from its new place: the card goes
    assert wait_until(lambda: not win.phase.states[ARRIVALS].needs, 10)
    store = store_of()
    try:
        after = store.conn.execute("SELECT id, tier, ord, rel_path, availability, work_id FROM items "
                                   "ORDER BY id").fetchall()
        assert after == before                                             # no second copy, nothing moved
        counts = {s["path"]: (s["items"], s["on"]) for s in store.sources(all=True)}
        assert counts[old] == (0, False) and counts[new] == (3, True)
    finally:
        store.close()
    win.toasts.card.buttons[0].click()                                    # Undo: the old folder read again
    assert wait_until(lambda: _cards(ny), 30)                             # ... gone still: its card is back
    store = store_of()
    try:
        assert {s["path"]: s["on"] for s in store.sources(all=True)}[old] is True
    finally:
        store.close()
