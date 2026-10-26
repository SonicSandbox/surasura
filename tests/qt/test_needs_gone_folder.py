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
from app.qt import press as qpress
from app.qt import stones, strings
from app.services import needs as service
from app.services import phase as phase_service
from app.services import source_looks
from app.services import standing as standing_service
from tests.fixtures import window_seed
from tests.qt.conftest import logos_in, wait_until
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


ELSEWHERE = "D:\\Elsewhere"
NAME = names("ja")[71]


@pytest.mark.parametrize("answer, said", [
    # Sonic 2026-10-25 (decision B, option 1): every answer that joined nothing says the folder picked is read now
    ({"joined": 0, "stop": False}, strings.NEEDS_FIND_NONE.format(folder=ELSEWHERE, show=NAME)),
    ({"state": "reached"}, strings.NEEDS_FIND_BACK.format(folder=ELSEWHERE, name=NAME)),
    ({"state": "away"}, strings.NEEDS_FIND_AWAY.format(folder=ELSEWHERE, name=NAME)),
    ({"refused": "That folder can't be read", "root": None},
     strings.NEEDS_FIND_REFUSED.format(folder=ELSEWHERE, why="That folder can't be read")),
    ({"failed": "disk I/O error", "stop": False}, strings.NEEDS_FIND_FAILED.format(folder=ELSEWHERE, why="disk I/O error")),
    ({"later": True, "stop": False}, strings.NEEDS_FIND_LATER.format(folder=ELSEWHERE)),
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
    assert heard[-1] == said, heard
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


# --- the adversary's findings (reviews/T6-card-adversary.md), each held ----------------------------------------- #
class LateLooks(Looks):
    """`find_new_folder` held until `answer_now()` (a long look at the folder picked)."""

    def __init__(self, answer=None):
        super().__init__(answer)
        self.pending = []

    def find_new_folder(self, root_id, path, then=None, language=None):
        self.finds.append((root_id, path, language))
        out = {"old": root_id, "path": path, "root": 19, "refused": None, "failed": None, "result": {}, "state": "gone",
               "joined": 0, "stop": False, "language": language}
        out.update(self.answer)
        self.pending.append((then, out))
        return True

    def answer_now(self):
        for then, out in self.pending:
            threading.Thread(target=then, args=(out,), daemon=True).start()
        self.pending = []


def _stops(writer):
    return [c for c in writer.calls if c[0] == "stop_source"]


def _pump(n=10):
    for _ in range(n):
        QApplication.processEvents()


@pytest.mark.parametrize("language", LANGUAGES)
def test_review1_a_stop_undone_before_the_card_went_can_be_given_again(world, language):
    """Stop → Undo, both landing before a listing without the row came (the looks' worker busy with a look): the card
    still stands, so Stop must still write — never a press that silently does nothing for the rest of the run."""
    seed, win, writer, ny = world(language, looks=Looks())
    row = _gone_row(language)
    _told(win, language, row)
    card = _card_in(win, ny)
    _button(ny, card.key, "stop_reading").click()
    assert wait_until(lambda: writer.saved, 5)
    win.toasts.card.buttons[0].click()                                    # Undo
    assert wait_until(lambda: writer.undone, 5)
    _pump()
    _told(win, language, row)                                             # the listings: read after the Undo
    assert wait_until(lambda: _button(ny, card.key, "stop_reading") is not None, 5)
    _button(ny, card.key, "stop_reading").click()
    assert wait_until(lambda: len(_stops(writer)) == 2, 5)


def test_review1_a_stop_the_writer_took_then_let_go_unsaved_or_refused_can_be_given_again(world):
    """The writer took the command, then it landed as nothing (its ticket ends unsaved: no save, no listing); or the
    writer refused it at once — either way the card stands, and the next press writes again."""
    seed, win, writer, ny = world("ja", looks=Looks())
    row = _gone_row("ja")
    _told(win, "ja", row)
    card = _card_in(win, ny)
    writer.nothing.add("stop_source")                                     # taken, then let go unsaved
    _button(ny, card.key, "stop_reading").click()
    assert wait_until(lambda: len(_stops(writer)) == 1 and not ny._stopping, 5)
    writer.nothing.clear()
    writer.writable = False                                               # refused at once: nothing held
    heard = []
    win.say = lambda text, *a, **k: heard.append(text)
    _button(ny, card.key, "stop_reading").click()
    _pump()
    assert len(_stops(writer)) == 1 and not ny._stopping
    assert heard and heard[-1] == strings.DRAG_REFUSED.format(reason=strings.store_reason(writer.why))   # never silent
    writer.writable = True
    _button(ny, card.key, "stop_reading").click()
    assert wait_until(lambda: len(_stops(writer)) == 2 and writer.saved, 5)


def test_review2_find_pressed_again_while_its_find_runs_opens_no_second_picker(world):
    looks = LateLooks()
    seed, win, writer, ny = world("ja", looks=looks)
    _told(win, "ja", _gone_row("ja"))
    card = _card_in(win, ny)
    picked = []
    ny.pick_folder = lambda title, start: picked.append(start) or "D:\\Elsewhere"
    _button(ny, card.key, "find_folder").click()
    _pump()
    _button(ny, card.key, "find_folder").click()                          # its arc still turns
    _pump()
    assert len(picked) == 1 and len(looks.finds) == 1
    looks.answer_now()                                                    # answered: its press ends, Find asks again
    assert wait_until(lambda: not qpress.live(win, ny._press_key("find_folder", card)), 5)
    _button(ny, card.key, "find_folder").click()
    assert len(picked) == 2


def test_review3_stop_and_keep_waiting_do_nothing_while_its_find_runs_and_find_still_says_what_it_joined(world,
                                                                                                    monkeypatch):
    looks = LateLooks({"joined": 12, "stop": True})
    seed, win, writer, ny = world("ja", looks=looks)
    _told(win, "ja", _gone_row("ja"))
    card = _card_in(win, ny)
    ny.pick_folder = lambda title, start: "S:\\Video\\Anime\\X"
    _button(ny, card.key, "find_folder").click()
    _pump()
    _button(ny, card.key, "stop_reading").click()                         # A-5: the other answer meanwhile
    _button(ny, card.key, "keep_waiting").click()
    _pump()
    assert not _stops(writer) and not win.offline_hidden
    looks.answer_now()
    assert wait_until(lambda: len(_stops(writer)) == 1, 5)
    assert wait_until(lambda: win.toasts.card.isVisible() and "12 episodes joined" in win.toasts.card.base, 5)


def test_review4_a_summary_with_a_folder_not_looked_at_yet_never_prunes_a_gone_cards_seen_key(world):
    seed, win, writer, ny = world("ja", looks=Looks())
    row = _gone_row("ja")
    _told(win, "ja", row)
    card = _card_in(win, ny)                                              # shown: marked seen
    assert wait_until(lambda: card.key in service.read_seen("ja"), 5)
    win.show_tab("current")
    _told(win, "ja", dict(row, reachable=None, gone=False))               # a listing before any look
    assert wait_until(lambda: ny.gone_folders == () and not ny._running, 5)
    from tests.qt.test_needs_you import settle
    settle(ny)
    assert card.key in service.read_seen("ja")
    _told(win, "ja", dict(row, reachable=True, gone=False))               # looked at, and back: its key goes
    settle(ny)
    assert card.key not in service.read_seen("ja")


def test_review5_a_find_answer_for_the_library_left_stops_nothing_and_says_where_to_finish(world, monkeypatch):
    looks = Looks({"joined": 12, "stop": True, "language": "zh"})        # answered after a switch away from zh
    seed, win, writer, ny = world("ja", looks=looks)
    _told(win, "ja", _gone_row("ja"))
    card = _card_in(win, ny)
    heard = []
    monkeypatch.setattr(win, "say", lambda text, *a, **k: heard.append(text))
    ny.pick_folder = lambda title, start: "S:\\Video\\Anime\\X"
    _button(ny, card.key, "find_folder").click()
    assert wait_until(lambda: heard, 5)
    assert heard[-1] == strings.NEEDS_FIND_JOINED_LEFT.format(name=names("ja")[71], folder="S:\\Video\\Anime\\X")
    assert not _stops(writer)


# --- the intent keeper's findings (reviews/T6-card-intent-keeper.md 2, 4) ----------------------------------------- #
def test_S19_the_same_look_said_twice_works_nothing_out_builds_no_card_and_repaints_no_circle(world):
    """A look every few minutes says the same gone folder again: nothing is gathered, no card rebuilt, 届 untouched."""
    seed, win, writer, ny = world("ja", looks=Looks())
    assert logos_in(win.phase)                                            # the strip finished opening
    row, away = _gone_row("ja"), _away_row()
    _told(win, "ja", row, away)
    _card_in(win, ny)
    from tests.qt.test_needs_you import settle
    settle(ny)
    gathers, builds = ny.gathers, ny.cards.builds
    paints, text = dict(win.phase.paints), win.offline_line.text()
    asked = ny._asked
    _told(win, "ja", row, away)                                           # the same summary again
    _pump(20)
    assert (ny._asked, ny.gathers, ny.cards.builds) == (asked, gathers, builds)
    assert dict(win.phase.paints) == paints and win.offline_line.text() == text


def test_todokes_press_opens_needs_you_at_the_gone_card(world):
    """Finding 4: the gone card is listed after the shows' cards — 届's press shows it, not only the page's top."""
    from PyQt6.QtCore import QRect
    seed, win, writer, ny = world("ja", looks=Looks())
    _told(win, "ja", _gone_row("ja"))
    assert wait_until(lambda: _cards(ny), 10)
    win._circle_pressed(ARRIVALS)
    _pump(20)
    card = ny.cards.card(_cards(ny)[0].key)
    area = ny.cards.parentWidget().parentWidget()
    top = card.mapTo(area.viewport(), card.rect().topLeft())
    assert area.viewport().rect().intersects(QRect(top, card.size()))


@pytest.mark.parametrize("language", LANGUAGES)
def test_find_on_a_stopped_folder_finds_its_record_and_is_not_refused(language):
    """# why: a folder the learner stopped is still a record: Find on it reads the new place and never says the
    folder isn't being read any more (the record is looked up with stopped folders included)."""
    from tests.test_library_store_sources import _empty, _scanned_show
    from tests.test_sources_scan import _settle
    store, _data_dir = _empty(language)
    title = names(language)[71]
    old = os.path.join(_elsewhere("Downloads"), title)
    new = os.path.join(_elsewhere("Video", "Anime"), title)
    _scanned_show(language, os.path.dirname(old), title, 3)
    with store:
        root_a = store.add_source(old)
        assert store.stop_source(root_a) is not None                      # the learner stops the old folder
    shutil.copytree(old, new, copy_function=shutil.copy2)
    _settle(new)
    shutil.rmtree(old)                                                    # the folder moved: the old place is gone
    data_dir, user_files_dir = roots(language)
    looks = source_looks.SourceLooks(ls.StoreOpener(language, data_dir, user_files_dir), language,
                                     kind=lambda _p: "network")
    answers = []
    looks._find(root_a, new, answers.append)
    assert len(answers) == 1
    answer = answers[0]
    assert answer["refused"] is None                                      # not "isn't being read any more"
    assert answer["root"] is not None and answer["root"] != root_a
    assert answer["result"] is not None
    assert not answer["stop"]                                             # a stopped folder is never stopped again


# why: Find reads the picked folder into the gone card's own language's library, even after the window has moved on to
# another language; reading it into the window's current language would join the show to the wrong library.
def test_find_on_a_gone_card_reads_into_the_cards_own_language_not_the_windows_current_one(world):
    looks = Looks()
    seed, win, writer, ny = world("ja", looks=looks)
    _told(win, "ja", _gone_row("ja"))
    card = _card_in(win, ny)
    ny.language = "zh"                                    # the window has moved on to Chinese since the card was made
    ny.pick_folder = lambda title, start: "S:\\Video\\Anime\\X"
    _button(ny, card.key, "find_folder").click()
    assert wait_until(lambda: looks.finds, 5)
    assert looks.finds[-1][2] == "ja"
    # the answer comes back through the GUI thread's signal; wait for the press to end so the callback doesn't run after the test
    assert wait_until(lambda: not qpress.live(win, ny._press_key("find_folder", card)), 5)
