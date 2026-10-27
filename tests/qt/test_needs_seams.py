"""Alpha 4's seams with Kura's library half in the window (P-seams: K1, K3, B14, K9, T6 option 2): the card for a
library mostly gone (*Start fresh* with Settings' own sheet, *Choose a folder…*), the card for a folder whose files are
mostly gone (*Choose a folder…* as ONE relink with ONE Undo, *and N more* lines), *Stop reading* from a gone folder's
card and from Settings' *Library folders* through the writer (a toast with Undo, the looks letting the folder go and
reading it again on Undo), and *Find its new folder…*'s answers for a folder that held none of the show's episodes.

What a wrong answer would cost a learner: a reinstalled Surasura showing 3,000 gone files and no way to start again; a
library card shown while a look was still to put the files back; a folder of 3,000 copies matched back file by file
(3,000 toasts' worth of saving, 3,000 Ctrl+Z); files the store couldn't take back said nowhere; a folder stopped from
Settings with no Undo, or one a look keeps reading after it was stopped, or never reads again after its Undo; a wrong
folder picked in *Find its new folder…* read for ever with nothing said.

The window's seed through the stand-in store, real Japanese and Chinese titles (tests/Test Resources/); where it
writes, a real store in the test's own root: the start-fresh backup, the relinked rows and their Undo, the folder
stopped and read again.
"""
import os
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from app import library_store as ls
from app.qt import needs as needs_ui
from app.qt import press as qpress
from app.qt import settings_sources, strings
from app.qt import settings_strings as S
from app.services import needs as service
from app.services import source_looks
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import open_window
from tests.qt.test_needs_a4 import hand_in, many
from tests.qt.test_needs_gone_folder import (GoneWriter, Looks, _button, _card_in, _cards, _gone_row,  # noqa: F401
                                             _told, world)
from tests.qt.test_settings_folders import ANIME, DRAMA, ActingLooks, _open, _src
from tests.qt.test_window_sources import _added, _folders_window, _library, _read_store, _source, window  # noqa: F401
from tests.test_library_store_support import LANGUAGES, names


class SeamLooks(Looks):
    """The looks with Kura's alpha 4 calls: `let_go` recorded (with the writer's calls made before it, so the order
    shows), `fresh` / `fresh_counts` answered on a thread of their own, as the looks' worker answers."""

    def __init__(self, answer=None, fresh_answer=None, counts=None, writer=None):
        super().__init__(answer)
        self.let_gos, self.fresh_calls, self.counted = [], [], 0
        self.fresh_answer = fresh_answer or {"done": True, "known": "kept"}
        self.counts = counts
        self.writer = writer

    def let_go(self, root_id, on=True, language=None):
        writes = len([c for c in self.writer.calls if c[0] == "stop_source"]) if self.writer is not None else None
        self.let_gos.append((root_id, on, language, writes))
        return True

    def fresh(self, forget_known=False, then=None):
        self.fresh_calls.append(forget_known)
        threading.Thread(target=then, args=(dict(self.fresh_answer),), daemon=True).start()
        return True

    def fresh_counts(self, then):
        self.counted += 1
        threading.Thread(target=then, args=(self.counts,), daemon=True).start()
        return True


def _pump(n=5):
    for _ in range(n):
        QApplication.processEvents()


def _gathered(ny, before):
    assert wait_until(lambda: ny.gathers > before and not ny._running, 10)
    _pump()


def _of(ny, kind):
    return [e for e in ny.entries if e.kind == kind]


def _in_folder(language, n, folder="アニメ"):
    """`n` shows of one episode each, every one gone, all under one library folder (K3's folder card)."""
    titles = names(language)
    rows = []
    for i in range(n):
        t = f"{titles[i % len(titles)]} {i + 1}"
        ep = SimpleNamespace(id=700000 + i, label="第1話", number=1, rel_path=f"{folder}/{t}/{t} - 01.srt", missing=True)
        rows.append(SimpleNamespace(key=f"w{i}", work_id=700000 + i, title=t, media="anime", tier="now", episodes=(ep,)))
    return SimpleNamespace(mode="store", rows=tuple(rows), loading=False, needs=())


def _relinks_recorded(writer, left=()):
    """The writer's `relink_many` (Kura's: ONE command, one Undo), recorded; once saved its change names `left`."""
    def relink_many(pairs, label=None):
        pairs = [(getattr(a, "item_id", a), os.fspath(p)) for a, p in pairs]
        return writer._put("relink_many", [i for i, _p in pairs], label, pairs=pairs)
    land = writer._land

    def landed(change, label):
        if change.op == "relink_many":
            change.left = list(left)
        land(change, label)
    writer.relink_many = relink_many
    writer._land = landed


# --- K1: the library mostly gone ------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_library_card_waits_for_every_folders_look_then_comes_first_with_start_fresh_and_choose_a_folder(world,
                                                                                                     language):
    """Kura's K1: never while a look may still put the copies back — the folders listed, one not looked at yet, is no
    card; once each had its look it is the first card, *Start fresh* · *Choose a folder…*, a tip on each."""
    seed, win, writer, ny = world(language, looks=SeamLooks())
    ny.find_offline = lambda _lang, _rels, _data: []
    ny.view = many(language, 40)
    _told(win, language, {"id": 3, "path": "D:\\アニメ", "on": True, "items": 40, "reachable": None})
    n = ny.gathers
    ny.refresh()
    _gathered(ny, n)
    assert not _of(ny, service.LIBRARY_GONE)                              # a look still to come
    n = ny.gathers
    _told(win, language, {"id": 3, "path": "D:\\アニメ", "on": True, "items": 40, "reachable": True})
    _gathered(ny, n)
    assert ny.entries[0].kind == service.LIBRARY_GONE
    win.show_tab("needs")
    buttons = [b for b in ny.cards.buttons(ny.entries[0].key) if b.property("line") is None]    # (not a file's own)
    assert [b.property("action") for b in buttons] == ["start_fresh", "choose_folder"]
    assert all(b.toolTip() for b in buttons)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_with_no_folder_to_read_shows_its_card_once_listed(world, language):
    """A library whose files are all in its own folder (no source folder): no look will put anything back, so the card
    shows once the listing said so — never before the listing landed."""
    seed, win, writer, ny = world(language, looks=SeamLooks())
    ny.find_offline = lambda _lang, _rels, _data: []
    ny.view = many(language, 40)
    n = ny.gathers
    ny.refresh()
    _gathered(ny, n)
    assert not _of(ny, service.LIBRARY_GONE)                              # not listed yet
    n = ny.gathers
    _told(win, language)                                                  # listed: no folder
    _gathered(ny, n)
    assert ny.entries[0].kind == service.LIBRARY_GONE


@pytest.mark.parametrize("language", LANGUAGES)
def test_start_fresh_asks_with_settings_own_sheet_then_the_looks_start_it_keeping_known_words(world, language):
    looks = SeamLooks(counts={"added": 2, "suspended": 3})
    seed, win, writer, ny = world(language, looks=looks)
    entries = service.entries(many(language, 40), settled=True)
    hand_in(ny, entries)
    win.show_tab("needs")
    card = entries[0]
    fresh = _button(ny, card.key, "start_fresh")
    fresh.click()
    assert qpress.live(win, ny._press_key("start_fresh", card))          # its arc at the press, while it counts
    assert wait_until(lambda: getattr(ny, "confirming", None) is not None, 5)
    sheet = ny.confirming
    assert sheet.title.text() == S.FRESH_ASK and sheet.body.text() == settings_sources.fresh_body(looks.counts)
    assert sheet.default is sheet.no and not sheet.check.isChecked()      # Enter is No; known words kept
    sheet.no.click()
    _pump()
    assert looks.fresh_calls == [] and writer.calls == []
    _button(ny, card.key, "start_fresh").click()
    assert wait_until(lambda: getattr(ny, "confirming", None) is not None and ny.confirming is not sheet, 5)
    ny.confirming.yes.click()
    assert wait_until(lambda: looks.fresh_calls == [False], 5)
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_DONE, 5)
    assert writer.calls == []                                             # the looks wrote it, never the window


@pytest.mark.parametrize("language", LANGUAGES)
def test_start_fresh_refused_keeps_the_card_says_why_and_can_be_pressed_again(world, language):
    looks = SeamLooks(fresh_answer={"refused": "busy"})
    seed, win, writer, ny = world(language, looks=looks)
    entries = service.entries(many(language, 40), settled=True)
    hand_in(ny, entries)
    win.show_tab("needs")
    card = entries[0]
    _button(ny, card.key, "start_fresh").click()
    assert wait_until(lambda: getattr(ny, "confirming", None) is not None, 5)
    ny.confirming.yes.click()
    assert wait_until(lambda: win.bar_line.full() == settings_sources.fresh_said({"refused": "busy"}), 5)
    assert wait_until(lambda: not qpress.live(win, ny._press_key("start_fresh", card)), 5)
    _button(ny, card.key, "start_fresh").click()                          # pressed again: it asks again
    assert wait_until(lambda: looks.counted == 2, 5)


def test_start_fresh_on_a_real_library_sets_it_aside_in_one_backup_and_the_card_goes(world):
    """The real looks on a real store: Yes backs the old library up in User Files › .trash › library-reset-…, never
    deleted, and the bar says the folders are read; the next view (the fresh library's: nothing gone) takes the card."""
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed, win, writer, ny = world("ja", looks=looks)
    _added(looks, _source())
    entries = service.entries(many("ja", 40), settled=True)
    hand_in(ny, entries)
    win.show_tab("needs")
    _button(ny, entries[0].key, "start_fresh").click()
    assert wait_until(lambda: getattr(ny, "confirming", None) is not None, 10)
    ny.confirming.yes.click()
    trash = os.path.join(user_files_dir, ".trash")
    assert wait_until(lambda: os.path.isdir(trash) and [n for n in os.listdir(trash) if n.startswith(ls.RESET_PREFIX)],
                      30)
    assert wait_until(lambda: win.bar_line.full() == S.FRESH_DONE, 10)
    assert looks.idle(30)
    del ny.refresh                                                        # (hand_in held the gathers: let them run)
    ny.find_offline = lambda _lang, _rels, _data: []
    n = ny.gathers
    ny.view_in(many("ja", 40, missing=0))                                 # the fresh library: nothing gone
    _gathered(ny, n)
    assert not _of(ny, service.LIBRARY_GONE)


# --- K3: a folder whose files are mostly gone -------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_choose_a_folder_on_a_folders_card_relinks_every_match_in_one_command_and_says_what_it_couldnt(world,
                                                                                                      language,
                                                                                                      tmp_path):
    """Each file at its own place under the folder picked (the folders inside it too), ONE `relink_many` — one
    ticket, one toast, one Undo, never one relink a file — and what the store couldn't take said in the bar."""
    seed, win, writer, ny = world(language, looks=SeamLooks())
    entries = service.entries(_in_folder(language, 12))
    card = entries[0]
    assert card.kind == service.FILES_FOLDER and len(card.lines) == 12
    picked = tmp_path / "移動先"
    for ln in card.lines[:10]:                                            # 10 of 12 moved there, keeping their places
        there = picked.joinpath(*ln.rel_path.split("/")[1:])
        there.parent.mkdir(parents=True, exist_ok=True)
        there.write_text("1\n00:00:01,000 --> 00:00:02,000\n海辺で本を読む\n", encoding="utf-8")
    left = [(card.lines[0].item_id, "another item's file"), (card.lines[1].item_id, "not in the library"),
            (card.lines[2].item_id, "not in the library")]
    _relinks_recorded(writer, left)
    hand_in(ny, entries)
    win.show_tab("needs")
    ny.pick_folder = lambda title, start: str(picked)
    _button(ny, card.key, "choose_folder").click()
    assert wait_until(lambda: writer.saved, 5)
    many_calls = [c for c in writer.calls if c[0] == "relink_many"]
    assert len(many_calls) == 1 and not [c for c in writer.calls if c[0] == "relink"]
    assert sorted(many_calls[0][1]) == sorted(ln.item_id for ln in card.lines[:10])
    assert wait_until(lambda: win.toasts.card.base == strings.NEEDS_RELINKED_N.format(k=10, n=12), 5)
    want = strings.NEEDS_RELINK_LEFT.format(n=3, why=" · ".join((
        strings.NEEDS_RELINK_WHY.format(why="another item's file", n=1),
        strings.NEEDS_RELINK_WHY.format(why="not in the library", n=2))))
    assert wait_until(lambda: win.bar_line.full() == want, 5)
    win.toasts.card.buttons[0].click()                                    # ONE Undo for all of them
    assert wait_until(lambda: writer.undone and writer.undone[-1].op == "relink_many", 5)


@pytest.mark.parametrize("language", LANGUAGES)
def test_choose_a_folder_holding_none_of_the_files_writes_nothing_and_says_so(world, language, tmp_path):
    seed, win, writer, ny = world(language, looks=SeamLooks())
    entries = service.entries(_in_folder(language, 12))
    _relinks_recorded(writer)
    hand_in(ny, entries)
    win.show_tab("needs")
    ny.pick_folder = lambda title, start: str(tmp_path)
    heard = []
    win.say = lambda text, *a, **k: heard.append(text)
    _button(ny, entries[0].key, "choose_folder").click()
    assert wait_until(lambda: heard, 5)
    assert heard[-1] == strings.NEEDS_RELINKED_NONE_TREE and writer.calls == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folders_card_of_3000_files_draws_a_few_lines_and_and_n_more(world, language):
    seed, win, writer, ny = world(language, looks=SeamLooks())
    entries = service.entries(_in_folder(language, 3000))
    card = entries[0]
    assert card.kind == service.FILES_FOLDER and len(card.lines) == 3000
    hand_in(ny, entries)
    win.show_tab("needs")
    built = ny.cards.card(card.key)
    lines = [b for b in built.findChildren(QPushButton) if b.property("line")]
    assert len({b.property("line") for b in lines}) == needs_ui.LINES_SHOWN
    words = [lab.text() for lab in built.findChildren(QLabel)]
    assert strings.NEEDS_MORE_LINES.format(n=f"{3000 - needs_ui.LINES_SHOWN:,}") in words


@pytest.mark.parametrize("language", LANGUAGES)
def test_choose_a_folder_on_a_real_library_points_every_file_back_in_one_change_and_one_undo(world, language):
    """A real migrated library (its shows' files moved into `moved/` inside the data folder, as a learner's move would):
    the folder's card matched against the moved folder, the writer's ONE `relink_many` on the real store — every row
    available at its new place — and the toast's one Undo marks every one missing again."""
    from tests.test_relink_many import _move_away, _rel
    from tests.test_services_moves import Library
    lib = Library(language)
    try:
        ids = lib.current()[:6]
        rels = {i: _rel(lib, i)[0] for i in ids}
        _move_away(lib, ids)
        eps = [SimpleNamespace(id=i, label=os.path.basename(rels[i]), number=None, rel_path=rels[i]) for i in ids]
        lines = tuple(service._line(e) for e in eps)
        base = service._common_folder(list(rels.values()))
        entry = service.Entry(key="files:real", kind=service.FILES_FOLDER, title="6 files are gone", lines=lines,
                              actions=("choose_folder", "remove"), unseen=False, say="",
                              data={"folder": base, "item_ids": tuple(ids), "shows": (), "n": 6, "files": 6})
        seed, win, writer, ny = world(language, looks=SeamLooks())
        real = {}

        def relink_many(pairs, label=None):
            pairs = [(getattr(a, "item_id", a), os.fspath(p)) for a, p in pairs]
            real["change"] = lib.store.relink_many(pairs)
            return writer._put("relink_many", [i for i, _p in pairs], label)
        undo = writer.undo

        def undone(change=None, label=None):
            if change is not None and change.op == "relink_many":
                lib.store.undo(real.pop("change"))
            return undo(change, label)
        writer.relink_many, writer.undo = relink_many, undone
        hand_in(ny, [entry])
        win.show_tab("needs")
        ny.pick_folder = lambda title, start: os.path.join(lib.data_dir, "moved", *[p for p in base.split("/") if p])
        _button(ny, entry.key, "choose_folder").click()
        assert wait_until(lambda: writer.saved, 10)
        assert len([c for c in writer.calls if c[0] == "relink_many"]) == 1
        assert all(_rel(lib, i) == ("moved/" + rels[i], "available") for i in ids)
        assert wait_until(lambda: win.toasts.card.base == strings.NEEDS_RELINKED_N.format(k=6, n=6), 5)
        win.toasts.card.buttons[0].click()
        assert wait_until(lambda: writer.undone, 10)
        assert all(_rel(lib, i) == (rels[i], "missing") for i in ids)
    finally:
        lib.close()


# --- B14: a gone folder's *Stop reading it* lets the looks go first ----------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_reading_it_lets_the_looks_go_before_the_writer_stops_it_and_its_undo_reads_it_again(world, language):
    seed, win, writer, ny = world(language)
    looks = SeamLooks(writer=writer)
    win.services.source_looks = looks
    win._open_looks(None)
    _told(win, language, _gone_row(language))
    card = _card_in(win, ny)
    _button(ny, card.key, "stop_reading").click()
    assert wait_until(lambda: writer.saved, 5)
    assert looks.let_gos[0] == (13, True, language, 0)                    # let go first, no stop written yet
    assert len([c for c in writer.calls if c[0] == "stop_source"]) == 1
    win.toasts.card.buttons[0].click()                                    # its Undo: read again
    assert wait_until(lambda: writer.undone and looks.let_gos[-1][:2] == (13, False), 5)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_stop_the_writer_refuses_lets_the_looks_read_the_folder_again(world, language):
    seed, win, writer, ny = world(language)
    looks = SeamLooks(writer=writer)
    win.services.source_looks = looks
    win._open_looks(None)
    _told(win, language, _gone_row(language))
    card = _card_in(win, ny)
    writer.lang = "zh" if language == "ja" else "ja"                     # another library's: the writer refuses it
    _button(ny, card.key, "stop_reading").click()
    assert wait_until(lambda: len(looks.let_gos) == 2, 5)
    assert [g[:3] for g in looks.let_gos] == [(13, True, language), (13, False, language)]
    assert not [c for c in writer.calls if c[0] == "stop_source"]


# --- K9: Settings' *Stop reading* through the writer -------------------------------------------------------------- #
class StoppingLooks(ActingLooks):
    """Settings' looks with `let_go`; the folders a stop the writer saved took out of the listing (as the store's
    `stop_source` does), put back by its Undo."""

    def __init__(self, sources):
        super().__init__(sources)
        self.let_gos, self.off = [], set()

    def let_go(self, root_id, on=True, language=None):
        self.let_gos.append((root_id, on, language))
        return True

    def publish(self):
        self.on_result({"language": self.language, "sources": [dict(s) for s in self.sources
                                                               if s["id"] not in self.off],
                        "skipped": [dict(f) for f in self.skipped_folders]})


def _stops_into(writer, looks):
    stop, undo = writer.stop_reading, writer.undo

    def stop_reading(root_id, label=None, language=None):
        looks.off.add(root_id)
        return stop(root_id, label, language)

    def undone(change=None, label=None):
        if change is None:                            # Ctrl+Z: the newest change, as the real writer reports it
            change = next((c for c in reversed(writer.saved) if c not in writer.undone), None)
        if change is not None and change.op == "stop_source":
            looks.off.discard(change.kw["root"])
        return undo(change, label)
    writer.stop_reading, writer.undo = stop_reading, undone


def test_settings_stop_reading_lets_the_looks_go_writes_one_change_with_a_toast_and_its_undo_reads_it_again(window):
    looks = StoppingLooks([_src(1, ANIME, 412), _src(2, DRAMA, 30)])
    win, page, row, folders = _open(window, looks)
    writer = win.services.writer
    _stops_into(writer, looks)
    assert wait_until(lambda: len(folders.lines) == 2, 10)
    folders.lines[2].stop.click()
    assert qpress.arc(folders.lines[2].stop) is not None                  # its arc from the press
    assert looks.let_gos == [(2, True, "ja")]
    assert [c for c in writer.calls if c[0] == "stop_source"] == [("stop_source", [], {"root": 2, "language": "ja"})]
    assert looks.stops == []                                              # never the looks' own unjournalled stop
    assert wait_until(lambda: 2 not in folders.lines and row.summary.text() == "1 folder", 10)
    assert win.toasts.card.base == S.SOURCES_STOPPED.format(path=DRAMA, n=30)
    assert wait_until(lambda: not win.presses.any_live(), 5)
    win.toasts.card.buttons[0].click()                                    # Undo: the folder read again
    assert wait_until(lambda: 2 in folders.lines and row.summary.text() == "2 folders", 10)
    assert looks.let_gos[-1][:2] == (2, False)


def test_settings_stop_undone_with_ctrl_z_reads_the_folder_again_too(window):
    looks = StoppingLooks([_src(1, ANIME, 412), _src(2, DRAMA, 30)])
    win, page, row, folders = _open(window, looks)
    _stops_into(win.services.writer, looks)
    assert wait_until(lambda: len(folders.lines) == 2, 10)
    folders.lines[1].stop.click()
    assert wait_until(lambda: 1 not in folders.lines and win.services.writer.saved, 10)
    win.moves.undo_last()                                                 # Ctrl+Z
    assert wait_until(lambda: 1 in folders.lines, 10)
    assert looks.let_gos[-1][:2] == (1, False)


def test_settings_stop_refused_by_the_writer_gives_nothing_and_never_lets_the_looks_go(window):
    looks = StoppingLooks([_src(1, ANIME, 412)])
    win, page, row, folders = _open(window, looks)
    assert wait_until(lambda: len(folders.lines) == 1, 10)
    win.moves.refused = lambda: "busy"                                    # (E4 meanwhile: the writer takes nothing)
    assert folders.stop(1) is False
    assert looks.let_gos == [] and win.services.writer.calls == []
    assert not win.presses.any_live() and 1 in folders.lines


def test_settings_stop_on_a_real_store_keeps_every_episode_and_its_undo_reads_the_folder_again(qapp):
    """The real looks and a real store: the stop is one change with Undo — the folder's row off, every episode kept —
    and the Undo turns it back on; the looks read it again (`let_go(on=False)`: nothing left held)."""
    opener, data_dir, user_files_dir = _library()
    looks = source_looks.SourceLooks(opener, "ja", kind=lambda _p: "network")
    seed = window_seed.build()

    def store_of():
        return ls.open_store("ja", data_dir, user_files_dir)
    writer = GoneWriter(seed.library, store_of=store_of)
    writer.lang = "ja"
    win, services = open_window(qapp, seed, writer)
    try:
        services.source_looks = looks
        win._open_looks(None)
        folder = _source()
        answer = _added(looks, folder)
        page, row, folders = _folders_window(win)
        assert wait_until(lambda: answer["root"] in folders.lines, 10)
        folders.lines[answer["root"]].stop.click()
        assert wait_until(lambda: not folders.lines, 10)
        assert win.toasts.card.base == S.SOURCES_STOPPED.format(path=ls.folder_path(folder), n=2)
        store = _read_store(data_dir, user_files_dir)
        try:
            assert store.sources() == [] and store.sources(all=True)[0]["on"] is False
            assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2     # every episode kept
        finally:
            store.close()
        assert answer["root"] in looks._stopping                         # no look reads it while it is stopped
        win.toasts.card.buttons[0].click()
        assert wait_until(lambda: answer["root"] in folders.lines, 10)
        store = _read_store(data_dir, user_files_dir)
        try:
            assert store.sources(all=True)[0]["on"] is True
        finally:
            store.close()
        assert answer["root"] not in looks._stopping
    finally:
        win.close()
        services.shutdown(0.5)


# --- T6 option 2: *Find its new folder…* on a folder holding none of them ------------------------------------------ #
ELSEWHERE = "D:\\Elsewhere"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("answer, said", [
    ({"refused": source_looks.FIND_NONE.format(folder=ELSEWHERE), "root": None},
     source_looks.FIND_NONE.format(folder=ELSEWHERE)),
    ({"joined": 0, "stop": False, "dropped": True}, "dropped"),
])
def test_find_its_new_folder_holding_none_of_its_episodes_says_that_folder_isnt_read(world, language, answer, said):
    looks = Looks(answer)
    seed, win, writer, ny = world(language, looks=looks)
    _told(win, language, _gone_row(language))
    card = _card_in(win, ny)
    heard = []
    win.say = lambda text, *a, **k: heard.append(text)
    ny.pick_folder = lambda title, start: ELSEWHERE
    _button(ny, card.key, "find_folder").click()
    assert wait_until(lambda: heard, 5)
    if said == "dropped":
        said = strings.NEEDS_FIND_DROPPED.format(show=names(language)[71], folder=ELSEWHERE)
    assert heard[-1] == said
    assert not [c for c in writer.calls if c[0] == "stop_source"]         # the old folder is still read
    assert _cards(ny)                                                      # ... and its card stays
