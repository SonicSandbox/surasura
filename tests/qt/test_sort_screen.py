"""Setup's sort screen and load screen (Mado-O, Sonic 2026-10-30; `app/qt/sort_screen.py`): every title in New
arrivals large, the top one sorted by a key or its button — **Soon · Current · Goal · Finished · Ignore** (S → ↓ ↑ ←) —
*Put the rest in…*, *Undo* (Ctrl+Z), *Done*; opened by setup after its load screen and by the tray's *Sort them all…*
(one screen, both doors). Every placement is New arrivals' own call through the window's writer; the screen decides
nothing. The load screen's mark beats its wings slowly, repainting itself alone. And the wizard's load steps: the
scan, the words (the indexer's count), the covers, the Anki sync, each passed when there is nothing for it; *Stop*
keeps what was done and goes to the sorting.

What a wrong answer would cost a learner:
  * a key that sorts the wrong title, or two titles for one press (a held key), or a choice that silently never lands;
  * Undo that takes back some other change of his (a drag he made a minute ago) instead of the last sort;
  * *Ignore* that never reads a folder holding his other shows, or that still lands after he pressed Undo;
  * a library that can't be written, and keys that do nothing without a word why;
  * a load screen whose wingbeat repaints the whole window sixty times a second on a laptop, or moves under Reduced
    motion; a Stop that throws away what was read, or a setup stuck waiting for a sync that never runs.

The window's seed (Japanese and Chinese titles from tests/Test Resources/) through a recording writer that lands each
command as the store would and undoes it; the wizard over its stand-in window with the real store in a temp library.
"""
import os
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QImage, QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from app import theme
from app.qt import arrivals, freeze, motion, sort_screen, strings
from app.qt import wizard_strings as S
from app.services import view_rows
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_arrivals import open_tray, open_window, tray_arrivals, tray_of
from tests.qt.test_arrivals_skip import SkipWriter
from tests.qt.test_drag import calls, settle

KEY_OF = {"soon": Qt.Key.Key_S, "now": Qt.Key.Key_Right, "goal": Qt.Key.Key_Down, "finished": Qt.Key.Key_Up,
          "ignore": Qt.Key.Key_Left}
WHERE = {"soon": "soon", "now": "top", "goal": "goal", "finished": "finished"}


class SortWriter(SkipWriter):
    """The tray's recording writer (places, removes, skips land in the stand-in library as the store lands them), whose
    Undo also puts a place or a remove back as it was."""

    def __init__(self, library):
        super().__init__(library)
        self.before = {}

    def _write(self, change):
        if change.op == "start_over":
            return self._write_start_over(change)
        if change.op in ("place", "remove"):
            self.before[id(change)] = [dict(r) for r in self.library.items() if r["id"] in change.ids]
        super()._write(change)

    def undo(self, change=None, label=None):
        rows = self.before.pop(id(change), None)
        if rows:
            self.library.commit(items=rows, order=True)
        return super().undo(change, label)

    def start_over(self, changes, label=None):
        """Mado-O: `Writer.start_over` as the store lands it — each placement's rows back as they were before it."""
        changes = list(changes)
        return self._put("start_over", [i for c in changes for i in c.ids], label, changes=changes)

    def _write_start_over(self, change):
        self.before[id(change)] = [dict(r) for r in self.library.items() if r["id"] in change.ids]
        for c in reversed(change.kw["changes"]):
            rows = self.before.get(id(c))
            if rows:
                self.library.commit(items=rows, order=True)


class OwnLooks:
    """`SourceLooks.skippable` as the sort screen asks it (`own=True`), answered on a thread of its own; `hold`: the
    answer waits until `release()`."""

    def __init__(self, choices, hold=False):
        self.choices, self.asks = list(choices), []
        self.gate = threading.Event()
        if not hold:
            self.gate.set()

    def skippable(self, ids, then, own=False):
        self.asks.append((list(ids), own))

        def answer():
            self.gate.wait(10)
            then(list(self.choices))
        threading.Thread(target=answer, daemon=True).start()
        return True

    def release(self):
        self.gate.set()

    def folders(self, ids, then, detail=False):
        then(dict.fromkeys(ids))
        return True

    def listing(self):
        return True

    def close(self):
        pass

    def set_shown(self, _shown):
        pass

    def asked(self, **_kw):
        return False


@pytest.fixture
def world(qapp):
    made = []

    def make(language="ja"):
        seed = window_seed.build(language=language)
        writer = SortWriter(seed.library)
        win, services = open_window(qapp, seed, writer)
        made.append((win, services))
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def open_sort(win):
    """The tray's *Sort them all…*, pressed -> the screen over the window."""
    tray = open_tray(win)
    QTest.mouseClick(tray.sort_button, Qt.MouseButton.LeftButton)
    screen = win.__dict__.get("_sort_screen")
    assert screen is not None and screen.isVisible()
    return screen


def keys_shown(screen):
    return [a.key for _k, a in screen.visible_rows()]


def press(screen, key, mods=Qt.KeyboardModifier.NoModifier, repeat=False):
    QApplication.sendEvent(screen, QKeyEvent(QEvent.Type.KeyPress, key, mods, "", repeat))


def no_toast(win, text):
    card = getattr(win.toasts, "card", None)
    return card is None or not card.isVisible() or getattr(card, "base", None) != text


# --- opening -------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_sort_them_all_closes_the_tray_and_opens_one_screen_with_every_arrival_the_newest_on_top(world, language):
    _seed, win, _writer = world(language)
    expected = [a.key for a in tray_arrivals(win)]
    screen = open_sort(win)
    tray = tray_of(win)
    assert wait_until(lambda: not tray.isVisible(), 3)
    assert keys_shown(screen) == expected and screen.top_arrival().key == expected[0]
    assert screen.top_name.text() == screen.top_arrival().title
    assert screen.count.text() == S.SORT_COUNT.format(n=len(expected))
    assert screen.door == "arrivals" and screen.geometry() == win.centralWidget().rect()
    assert tray.sort_all() is screen, "one screen: the second door raises it"
    for b in screen.findChildren(QPushButton):                        # every control says what it does
        assert b.toolTip(), b.text()


def test_soon_is_on_the_left_of_the_choices_and_of_the_keys_strip(world):
    """Sonic 2026-10-30: Soon first — the one key that isn't an arrow — then the arrows' four."""
    _seed, win, _writer = world()
    screen = open_sort(win)
    settle()
    order = sorted(screen.choice_buttons, key=lambda n: screen.choice_buttons[n].mapTo(screen, screen.choice_buttons[n]
                                                                                       .rect().topLeft()).x())
    assert order == ["soon", "now", "goal", "finished", "ignore"]
    strip = sorted((w for w in screen.findChildren(sort_screen.QLabel) if w.objectName() == "sortkey"),
                   key=lambda w: w.mapTo(screen, w.rect().topLeft()).x())
    assert [w.text() for w in strip] == ["S", "→", "↓", "↑", "←", "Ctrl+Z"]


# --- a choice ------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["soon", "now", "goal", "finished"])
@pytest.mark.parametrize("by", ["key", "button"])
def test_a_choice_places_the_top_title_through_new_arrivals_call_and_the_next_comes_up_at_once(world, name, by):
    """The key (or the button) acts on the top title only: New arrivals' own place, through the writer; the title is
    off the screen at once — before the writer has saved it (a busy store) — the next one on top; no toast (the screen
    says it); once saved the view lets it go."""
    _seed, win, writer = world()
    screen = open_sort(win)
    top, second = screen.visible_rows()[0][1], screen.visible_rows()[1][1]
    writer.stuck = True
    if by == "key":
        press(screen, KEY_OF[name])
    else:
        QTest.mouseClick(screen.choice_buttons[name], Qt.MouseButton.LeftButton)
    assert calls(writer, "place") == [("place", list(top.item_ids), {"where": WHERE[name]})]
    assert screen.top_arrival().key == second.key and top.key not in keys_shown(screen)       # pending, at once
    assert screen.said.text() == S.SORT_PLACED[name].format(title=top.title)
    assert screen.btn_undo.isEnabled()
    writer.free()
    assert wait_until(lambda: top.key not in {a.key for _k, a in sort_screen._rows_of(screen.groups)}, 5)
    assert top.key not in screen.hidden, "landed: its pending mark goes with it"
    assert no_toast(win, S.SORT_PLACED[name].format(title=top.title))


def test_a_held_key_sorts_one_title_and_a_modified_key_none(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    press(screen, Qt.Key.Key_S, repeat=True)                          # a held key's repeats are none
    press(screen, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    press(screen, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
    assert writer.calls == []
    press(screen, Qt.Key.Key_S)
    press(screen, Qt.Key.Key_S, repeat=True)
    assert len(calls(writer, "place")) == 1


def test_the_window_hands_the_screen_each_view_so_a_title_placed_elsewhere_leaves_it(world):
    """The shell's one hook (`_show_arrivals`): a title placed by another door (the tray's own call) leaves the screen
    with the view, without a choice here."""
    _seed, win, writer = world()
    screen = open_sort(win)
    other = screen.visible_rows()[1][1]
    arrivals.give_place(win.moves, "elsewhere", list(other.item_ids), "goal")
    assert wait_until(lambda: other.key not in keys_shown(screen), 5)
    assert screen.history == []


# --- Undo ----------------------------------------------------------------------------------------------------------- #
def _saved(writer, n):
    return wait_until(lambda: len(writer.saved) >= n, 5)


def test_undo_brings_the_last_title_back_on_top_by_its_own_change_never_a_newer_one(world):
    """Ctrl+Z takes back the sort's own change — even when a newer change of the window's (another door's place) came
    after it — and the title is on top again."""
    _seed, win, writer = world()
    screen = open_sort(win)
    first, other = screen.visible_rows()[0][1], screen.visible_rows()[2][1]
    press(screen, Qt.Key.Key_Down)
    assert _saved(writer, 1)
    mine = writer.saved[0]
    arrivals.give_place(win.moves, "newer", list(other.item_ids), "soon")
    assert _saved(writer, 2)
    settle()
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert wait_until(lambda: calls(writer, "undo"), 5)
    assert calls(writer, "undo") == [("undo", [], {"change": mine})], "its own change, never the newer one"
    assert wait_until(lambda: screen.top_arrival() is not None and screen.top_arrival().key == first.key, 5)
    assert screen.history == [] and not screen.btn_undo.isEnabled() and screen.said.text() == ""


def test_undo_before_the_store_saved_takes_it_back_as_it_lands(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    first = screen.top_arrival()
    writer.stuck = True
    press(screen, Qt.Key.Key_S)
    QTest.mouseClick(screen.btn_undo, Qt.MouseButton.LeftButton)
    assert screen.top_arrival().key == first.key                      # back at once
    writer.free()
    assert wait_until(lambda: calls(writer, "undo"), 5)
    assert [c[0] for c in writer.calls] == ["place", "undo"] and writer.undone == [writer.saved[0]]


def test_undo_with_nothing_sorted_does_nothing(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert writer.calls == [] and not screen.btn_undo.isEnabled()


# --- Put the rest in… ------------------------------------------------------------------------------------------------ #
def test_put_the_rest_in_offers_the_four_places_and_is_one_command_with_one_undo(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    QTest.mouseClick(screen.btn_rest, Qt.MouseButton.LeftButton)
    menu = screen.last_menu
    assert [a.text() for a in menu.actions()] == ["Soon", "Current", "Goal", "Finished"]       # never Ignore
    assert all(a.toolTip() for a in menu.actions())
    menu.close()
    rows = screen.visible_rows()
    ids = [i for _k, a in rows for i in a.item_ids]
    screen.rest("goal")
    assert calls(writer, "place") == [("place", ids, {"where": "goal"})]
    assert keys_shown(screen) == [] and screen.said.text() == S.SORT_REST_PLACED.format(n=len(rows), place="Goal")
    assert wait_until(lambda: not screen.empty.isHidden(), 5)          # the view landed: "All sorted."
    assert _saved(writer, 1)
    settle()
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert wait_until(lambda: calls(writer, "undo"), 5) and len(calls(writer, "undo")) == 1
    assert wait_until(lambda: keys_shown(screen) == [a.key for _k, a in rows], 5)


def test_put_the_rest_in_with_one_title_left_is_greyed_and_with_none_does_nothing(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    while len(screen.visible_rows()) > 1:
        screen.choose("soon")
    assert not screen.btn_rest.isEnabled()
    screen.choose("soon")
    n = len(writer.calls)
    assert screen.rest("goal") is None and len(writer.calls) == n


# --- Ignore ---------------------------------------------------------------------------------------------------------- #
def test_ignore_never_reads_the_titles_own_folder_again_by_q7s_call(world):
    """← Ignore with the title in a folder of its own: *Never read this folder* (`skip_folder`) for that folder, asked
    `own` (never one holding other titles); its files leave; one Undo brings them back."""
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    folder = os.path.join(os.sep, "Media", top.title)
    win.looks = OwnLooks([folder, os.path.dirname(folder)])
    writer.under[folder] = list(top.item_ids)
    press(screen, Qt.Key.Key_Left)
    assert top.key not in keys_shown(screen)
    assert wait_until(lambda: calls(writer, "skip_folder"), 5)
    assert win.looks.asks == [(list(top.item_ids), True)]
    assert calls(writer, "skip_folder") == [("skip_folder", list(top.item_ids), {"path": folder})]
    assert calls(writer, "remove") == []
    assert no_toast(win, strings.ITEM_SKIPPED.format(name=top.title))
    assert _saved(writer, 1)
    settle()
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert wait_until(lambda: calls(writer, "undo"), 5)
    assert wait_until(lambda: top.key in keys_shown(screen), 5)


def test_ignore_with_no_folder_of_its_own_takes_the_title_out_of_the_library(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    win.looks = OwnLooks([])
    press(screen, Qt.Key.Key_Left)
    assert wait_until(lambda: calls(writer, "remove"), 5)
    assert calls(writer, "remove") == [("remove", list(top.item_ids), {})] and calls(writer, "skip_folder") == []


def test_ignore_undone_while_its_folder_is_looked_for_writes_nothing(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    win.looks = OwnLooks([os.path.join(os.sep, "Media", top.title)], hold=True)
    press(screen, Qt.Key.Key_Left)
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert screen.top_arrival().key == top.key
    win.looks.release()
    wait_until(lambda: False, 0.4)
    QApplication.processEvents()
    assert writer.calls == []


# --- refusals: never silent ------------------------------------------------------------------------------------------- #
def test_a_library_that_cant_be_written_sorts_nothing_and_says_why(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    writer.writable = False
    press(screen, Qt.Key.Key_S)
    assert writer.calls == [] and screen.top_arrival().key == top.key and screen.history == []
    assert screen.said.text() and screen.said.text() == win.moves.refused()


def test_a_choice_the_writer_refuses_comes_back_and_the_screen_says_it_wasnt_saved(world, monkeypatch):
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    monkeypatch.setattr(writer, "place", lambda *a, **kw: None)
    press(screen, Qt.Key.Key_Down)
    assert screen.top_arrival().key == top.key and screen.history == [] and top.key not in screen.hidden
    assert screen.said.text() == strings.MOVE_NOT_SAVED


def test_a_choice_that_ends_unsaved_comes_back(world):
    """The writer took the command but it landed as nothing (or was let go at a switch): the title is still in New
    arrivals, so it comes back on the screen with words — never hidden for good with a count that leaves it out."""
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    writer.nothing.add("place")
    press(screen, Qt.Key.Key_S)
    assert top.key not in keys_shown(screen)
    assert wait_until(lambda: top.key in keys_shown(screen), 5)
    assert screen.history == [] and screen.said.text() == strings.MOVE_NOT_SAVED


def test_ignore_when_the_folders_cant_be_looked_at_guesses_nothing(world):
    """The looks can't answer (the window closing): *Ignore* never turns into a removal; the title comes back."""
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    win.looks = OwnLooks([])
    win.looks.skippable = lambda ids, then, own=False: False
    press(screen, Qt.Key.Key_Left)
    assert screen.top_arrival().key == top.key and screen.said.text() == strings.MOVE_NOT_SAVED
    wait_until(lambda: False, 0.3)
    assert writer.calls == []


def test_an_ignore_pressed_just_before_done_still_lands(world):
    """*Ignore*, then *Done* before its folder answer came: the screen is gone, the Ignore is still given."""
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    folder = os.path.join(os.sep, "Media", top.title)
    win.looks = OwnLooks([folder], hold=True)
    writer.under[folder] = list(top.item_ids)
    press(screen, Qt.Key.Key_Left)
    QTest.mouseClick(screen.btn_done, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: sip.isdeleted(screen) or not screen.isVisible(), 3)
    from PyQt6.QtCore import QCoreApplication, QEvent as E
    QCoreApplication.sendPostedEvents(None, E.Type.DeferredDelete.value)       # the screen really gone
    assert sip.isdeleted(screen)
    win.looks.release()
    assert wait_until(lambda: calls(writer, "skip_folder"), 5)


# --- Start sorting over (Mado-O, alpha 8) ----------------------------------------------------------------------------- #
def _sort_some(screen, writer, names=("now", "soon", "finished")):
    """Each of `names` on the top title in turn, saved. -> the titles placed, in order."""
    placed = []
    for name in names:
        placed.append(screen.top_arrival())
        screen.choose(name)
    assert _saved(writer, len(names))
    settle()
    return placed


def _answer(screen, yes):
    card = screen.question
    assert card is not None and wait_until(card.isVisible, 3)
    (card.yes if yes else card.no).click()
    settle()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_start_over_asks_first_then_puts_every_sorted_title_back_in_one_command_from_the_top(world, language):
    """Sonic 2026-10-31: *Start sorting over* — asked first (No by default); Yes: every title this screen placed (a
    *Put the rest in…* too) back to sort in ONE writer command, the screen from the top as New arrivals has them."""
    _seed, win, writer = world(language)
    screen = open_sort(win)
    first = keys_shown(screen)
    assert not screen.btn_over.isEnabled(), "nothing sorted: nothing to start over"
    placed = _sort_some(screen, writer, ("now", "soon"))
    screen.rest("goal")
    assert _saved(writer, 3)
    settle()
    assert screen.btn_over.isEnabled() and screen.btn_over.toolTip()
    QTest.mouseClick(screen.btn_over, Qt.MouseButton.LeftButton)
    _answer(screen, False)
    assert calls(writer, "start_over") == [], "No: nothing written"
    QTest.mouseClick(screen.btn_over, Qt.MouseButton.LeftButton)
    _answer(screen, True)
    over = calls(writer, "start_over")
    assert len(over) == 1 and over[0][2]["changes"] == writer.saved[:3], "one command: the screen's three placements"
    assert wait_until(lambda: keys_shown(screen) == first, 5), "every title back, from the top"
    assert wait_until(lambda: screen.said.text() == S.SORT_OVER_SAID.format(n=len(first)), 5), "saved: said so"
    assert screen.top_arrival().key == placed[0].key
    assert [e["name"] for e in screen.history] == ["over"] and not screen.btn_over.isEnabled()


def test_undo_after_start_over_puts_the_sorting_back_and_then_each_choice_undoes_on_its_own(world):
    """One Undo (Ctrl+Z) takes the reset back — its own change, the titles off the screen at once; the next Undo is
    the last choice again, by its own change."""
    _seed, win, writer = world()
    screen = open_sort(win)
    placed = _sort_some(screen, writer)
    left = keys_shown(screen)
    screen.start_over()
    assert wait_until(lambda: len(writer.saved) == 4, 5)
    reset = writer.saved[-1]
    assert wait_until(lambda: keys_shown(screen)[:3] == [a.key for a in placed], 5)
    settle()
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert keys_shown(screen) == left, "the sorting back at once"
    assert wait_until(lambda: calls(writer, "undo"), 5)
    assert calls(writer, "undo") == [("undo", [], {"change": reset})]
    assert [e["name"] for e in screen.history] == ["now", "soon", "finished"]
    settle()
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert wait_until(lambda: len(calls(writer, "undo")) == 2, 5)
    assert calls(writer, "undo")[1][2]["change"] is writer.saved[2], "then the last choice, by its own change"
    assert wait_until(lambda: screen.top_arrival().key == placed[2].key, 5)


def test_an_ignored_title_stays_ignored_and_its_undo_still_works_after_start_over(world):
    """PROVISIONAL: Ignore isn't put back (its folder stays unread); after the reset, its own Undo is still on Undo."""
    _seed, win, writer = world()
    screen = open_sort(win)
    win.looks = OwnLooks([])
    ignored = screen.top_arrival()
    press(screen, Qt.Key.Key_Left)
    assert wait_until(lambda: calls(writer, "remove"), 5) and _saved(writer, 1)
    _sort_some(screen, writer, ("goal",))
    screen.start_over()
    assert wait_until(lambda: calls(writer, "start_over"), 5)
    assert [c.op for c in calls(writer, "start_over")[0][2]["changes"]] == ["place"], "never the Ignore"
    assert ignored.key not in keys_shown(screen)
    assert [e["name"] for e in screen.history] == ["ignore", "over"]


def test_start_over_waits_for_a_choice_still_being_saved_and_puts_it_back_too(world):
    """A busy store: the press shows at once (the titles back to sort), the one command waits for the choice's save —
    it is put back with the rest, never left in Current."""
    _seed, win, writer = world()
    screen = open_sort(win)
    first = keys_shown(screen)
    _sort_some(screen, writer, ("soon",))
    writer.stuck = True
    screen.choose("now")
    screen.start_over()
    assert calls(writer, "start_over") == [] and screen.said.text() == S.SORT_OVER_SAYING.format(n=2)
    later = screen.visible_rows()[-1][1]                          # (a title the reset isn't putting back)
    screen.choose("goal", arrival=later)                          # a choice while it is on its way …
    assert not screen.btn_over.isEnabled() and screen.start_over() is None, "one Start over at a time"
    writer.free()
    assert wait_until(lambda: calls(writer, "start_over"), 5)
    assert calls(writer, "start_over")[0][2]["changes"] == writer.saved[:2]
    assert wait_until(lambda: keys_shown(screen) == [k for k in first if k != later.key], 5)
    assert wait_until(screen.btn_over.isEnabled, 5), "… and once it is saved, that choice can be started over"


def test_start_over_is_pending_at_once_and_never_says_all_sorted_while_the_titles_come_back(world):
    """Intent #2 (a8): a busy store — the press shows *Putting N back…* at once, never "All sorted." beside it; saved,
    it says they're back."""
    _seed, win, writer = world()
    screen = open_sort(win)
    first = keys_shown(screen)
    screen.rest("soon")
    assert _saved(writer, 1) and wait_until(lambda: not screen.empty.isHidden(), 5)
    writer.stuck = True
    screen.start_over()
    assert screen.said.text() == S.SORT_OVER_SAYING.format(n=len(first)) and screen.empty.isHidden()
    writer.free()
    assert wait_until(lambda: keys_shown(screen) == first, 5)
    assert wait_until(lambda: screen.said.text() == S.SORT_OVER_SAID.format(n=len(first)), 5)


def test_an_undo_after_an_unsaved_start_over_waits_for_it_never_goes_ahead_of_it(world):
    """Adversary #2 (a8): Start over, then Ctrl+Z twice before the store saved it — the second press waits (says
    *Undoing…*): the writer gets the reset, its Undo, and only then the next choice's Undo."""
    _seed, win, writer = world()
    screen = open_sort(win)
    _sort_some(screen, writer, ("soon", "goal"))
    writer.stuck = True
    screen.start_over()
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    from app.qt import strings as qs
    assert screen.said.text() == qs.UNDOING and [e["name"] for e in screen.history] == ["soon", "goal"]
    writer.free()
    assert wait_until(lambda: calls(writer, "undo"), 5)
    settle()
    assert [c[0] for c in writer.calls] == ["place", "place", "start_over", "undo"]
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert wait_until(lambda: len(calls(writer, "undo")) == 2, 5)
    assert calls(writer, "undo")[1][2]["change"] is writer.saved[1]


def test_a_start_over_waiting_on_a_save_is_still_given_when_the_screen_closes(world):
    """Adversary #4 (a8): Start over waits for a choice still being saved, and *Done* closes the screen: it is still
    given (Done is no No)."""
    _seed, win, writer = world()
    screen = open_sort(win)
    writer.stuck = True
    screen.choose("soon")
    screen.start_over()
    QTest.mouseClick(screen.btn_done, Qt.MouseButton.LeftButton)
    from PyQt6.QtCore import QCoreApplication, QEvent as E
    QCoreApplication.sendPostedEvents(None, E.Type.DeferredDelete.value)
    writer.free()
    assert wait_until(lambda: calls(writer, "start_over"), 5)


def test_a_choice_that_ended_unsaved_while_start_over_waited_stays_shown_after_its_undo(world):
    """Adversary #8 (a8): a choice still saving lands as nothing while Start over waits for it — the title never left
    New arrivals, so undoing the Start over never hides it again."""
    _seed, win, writer = world()
    screen = open_sort(win)
    top = screen.top_arrival()
    writer.stuck = True
    writer.nothing.add("place")
    screen.choose("soon")
    screen.start_over()
    writer.free()
    assert wait_until(lambda: screen._over_flight is None, 5)
    settle()
    press(screen, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert top.key in keys_shown(screen) and top.key not in screen.hidden


def test_start_over_the_writer_refuses_keeps_the_sorting_and_says_so(world, monkeypatch):
    _seed, win, writer = world()
    screen = open_sort(win)
    _sort_some(screen, writer, ("soon", "goal"))
    left = keys_shown(screen)
    monkeypatch.setattr(writer, "start_over", lambda *a, **kw: None)
    screen.start_over()
    assert screen.said.text() == strings.MOVE_NOT_SAVED
    assert keys_shown(screen) == left and [e["name"] for e in screen.history] == ["soon", "goal"]


# --- closing --------------------------------------------------------------------------------------------------------- #
def test_esc_and_done_close_the_tray_door_and_leave_the_rest_in_new_arrivals(world):
    _seed, win, writer = world()
    screen = open_sort(win)
    QApplication.sendEvent(screen, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert wait_until(lambda: sip.isdeleted(screen) or not screen.isVisible(), 3)
    assert "_sort_screen" not in win.__dict__ and writer.calls == []
    screen = open_sort(win)
    QTest.mouseClick(screen.btn_done, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: sip.isdeleted(screen) or not screen.isVisible(), 3)
    assert tray_arrivals(win), "unsorted titles wait in New arrivals"


def test_esc_does_nothing_on_setups_door(qapp):
    win = SimpleNamespace(moves=None, looks=None, language="ja")
    screen = sort_screen.SortScreen(win, door="setup")
    heard = []
    screen.closed.connect(heard.append)
    QApplication.sendEvent(screen, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert heard == []
    QTest.mouseClick(screen.btn_done, Qt.MouseButton.LeftButton)
    assert heard == ["done"] and "_sort_screen" not in win.__dict__
    screen.deleteLater()


# --- a big library ---------------------------------------------------------------------------------------------------- #
def _arrival(i, n=3):
    fields = {f: None for f in view_rows.Arrival._fields}
    fields.update(key=f"k{i}", work_id=i, item_ids=tuple(range(i * 10, i * 10 + n)), rel_paths=(),
                  title=f"夜空の灯 第{i}期", media_word="episodes", group="new", cover_title=f"夜空の灯 {i}",
                  folder=f"Anime\\夜空の灯 {i}", line=f"Ep 1–{n}", parts=(), episodes=())
    return view_rows.Arrival(**fields)


class _Moves:
    """The drag controller as the screen calls it, recording: every command taken at once."""

    def __init__(self):
        self.given = []
        self.writer = SimpleNamespace(place=lambda ids, where, label=None: self.given.append((ids, where)) or 1)

    def refused(self):
        return None

    def _give(self, ticket, command, toast=True):
        return command(ticket)


def test_fifteen_thousand_titles_paint_a_few_rows_and_each_choice_stays_quick(qapp):
    """A 15,000-title library (the K5 warning's size): the screen builds the top and its next few only — never a widget
    per title — and a choice (with every pending title before it) stays well inside a frame's worth of work."""
    rows = tuple(_arrival(i) for i in range(15000))
    groups = (view_rows.ArrivalGroup("new", "New", rows, tuple(a.key for a in rows)),)
    moves = _Moves()
    win = SimpleNamespace(moves=moves, looks=None, language="ja")
    screen = sort_screen.SortScreen(win, door="setup")
    screen.resize(1280, 800)
    widgets = len(screen.findChildren(QObject))
    t = time.perf_counter()
    screen.set_groups(groups)
    first = time.perf_counter() - t
    assert len(screen.findChildren(QObject)) == widgets, "no widget per title"
    assert screen.more.text() == S.SORT_MORE.format(n=15000 - 1 - sort_screen.NEXT_SHOWN)
    spent = []
    for _ in range(200):
        t = time.perf_counter()
        screen.choose("soon")
        spent.append(time.perf_counter() - t)
    assert len(moves.given) == 200 and screen.top_arrival().key == "k200"
    # the window thread's budget is 4 ms a step on a laptop 2–3× slower than this machine: a press stays under 1 ms
    assert first < 0.5 and sorted(spent)[len(spent) // 2] < 0.001, (first, sorted(spent)[len(spent) // 2])
    assert screen.count.text() == S.SORT_COUNT.format(n=15000 - 200)
    screen.deleteLater()


# --- the load screen's mark ------------------------------------------------------------------------------------------ #
@pytest.fixture
def clock(qapp):
    c = motion.clock()
    for a in c.active:
        a.stop()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    before = c.mode.setting
    c.mode.set_setting("full")
    yield c
    for a in c.active:
        a.stop()
    c.use_real_time()
    c.mode.set_setting(before)
    freeze.set_frozen(None)


@pytest.fixture
def load(qapp):
    screen = sort_screen.LoadScreen()
    screen.resize(1280, 800)
    yield screen
    screen.close()
    screen.deleteLater()


class Paints(QObject):
    def __init__(self, widgets):
        super().__init__()
        self.n = {w: 0 for w in widgets}
        for w in widgets:
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint and obj in self.n:
            self.n[obj] += 1
        return False


def test_the_mark_beats_on_the_clock_only_while_shown_and_rests_in_its_own_pose(clock, load):
    mark = load.mark
    assert not mark.on_clock
    load.show()
    QApplication.processEvents()
    assert mark.on_clock and mark.period == "mark-flap"
    clock.advance(theme.MOTION["mark-flap"] / 4)                       # a quarter beat: the wings at their widest
    assert mark.angle == pytest.approx(1.0, abs=0.02)
    clock.advance(theme.MOTION["mark-flap"] / 2)
    assert mark.angle == pytest.approx(-1.0, abs=0.02)
    clock.advance(theme.MOTION["mark-flap"] / 4)                       # one whole beat: back where it started
    assert mark.angle == pytest.approx(0.0, abs=0.02)
    load.hide()
    assert not mark.on_clock and mark.angle == 0.0 and not clock.active


def test_reduced_motion_or_the_freeze_switch_hold_the_mark_still(clock, load):
    clock.mode.set_setting("reduced")
    load.show()
    QApplication.processEvents()
    mark = load.mark
    assert not mark.on_clock and mark.angle == 0.0
    clock.mode.set_setting("full")
    assert mark.on_clock                                               # the setting changed back: it beats again
    clock.advance(theme.MOTION["mark-flap"] / 4)
    assert mark.angle != 0.0
    clock.mode.set_setting("reduced")
    assert not mark.on_clock and mark.angle == 0.0                     # stopped: in its own pose, never mid-beat


def test_a_beat_repaints_the_mark_alone_within_a_small_budget(clock, load):
    """Sonic: the bird flaps "ONLY if it redraws nothing else and costs nothing measurable". Over two beats on the
    clock the mark repaints and nothing else on the screen does (it paints its own ground: no parent repaint); and a
    frame of it costs well under a millisecond."""
    load.set_task(S.LOAD_INDEX.format(done=412, total=1639))
    load.show()
    for _ in range(5):
        QApplication.processEvents()
    others = [load, load.task, load.line, load.btn_stop]
    seen = Paints(others + [load.mark])
    for _ in range(2 * theme.MOTION["mark-flap"] // motion.FRAME_MS):
        clock.advance(motion.FRAME_MS)
        QApplication.processEvents()
    assert seen.n[load.mark] > 20
    assert {w.objectName() or type(w).__name__: seen.n[w] for w in others} == \
        {w.objectName() or type(w).__name__: 0 for w in others}
    assert load.mark.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    spent = []
    for k in range(120):
        load.mark.angle = ((k % 40) - 20) / 20
        t = time.perf_counter()
        load.mark.repaint()
        spent.append(time.perf_counter() - t)
    assert sorted(spent)[len(spent) // 2] < 0.001, sorted(spent)[len(spent) // 2]


def test_the_wings_are_cut_from_the_mark_whole_nothing_lost_nothing_twice(qapp):
    """The body and the two wings put back together are the mark: every pixel's cover once (their alphas add up to
    the icon's), and each wing holds its feathers."""
    mark = sort_screen.Mark(96)
    body, upper, lower = (p.toImage().convertToFormat(QImage.Format.Format_ARGB32) for p in mark._cut())
    whole = mark._cut()[0].copy()
    from PyQt6.QtGui import QPainter, QPixmap
    icon = QPixmap(os.path.join(os.path.dirname(sort_screen.__file__), os.pardir, "assets", "images", "app_icon.png"))
    icon = icon.scaled(whole.width(), whole.height(), Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation).toImage().convertToFormat(
        QImage.Format.Format_ARGB32)
    del QPainter

    def alpha(img):
        return sum(img.pixelColor(x, y).alpha() for y in range(img.height()) for x in range(img.width()))
    parts = [alpha(body), alpha(upper), alpha(lower)]
    assert parts[1] > 0.15 * alpha(icon) and parts[2] > 0.1 * alpha(icon) and parts[0] > 0.3 * alpha(icon)
    assert sum(parts) == pytest.approx(alpha(icon), rel=0.01)
    mark.deleteLater()


# --- the load screen ------------------------------------------------------------------------------------------------- #
def test_stop_asks_once_and_says_it_is_stopping(load):
    heard = []
    load.stop.connect(lambda: heard.append(1))
    load.show()
    assert load.btn_stop.toolTip()
    QTest.mouseClick(load.btn_stop, Qt.MouseButton.LeftButton)
    QTest.mouseClick(load.btn_stop, Qt.MouseButton.LeftButton)
    load._stop()
    assert heard == [1] and not load.btn_stop.isEnabled() and load.btn_stop.text() == S.LOAD_STOPPING


def test_the_gentle_line_fades_by_its_own_paint_never_a_graphics_effect(load):
    """The do-not list's T6: no QGraphicsOpacityEffect anywhere on the screen; the line's fade is its own level."""
    from PyQt6.QtWidgets import QWidget
    assert all(w.graphicsEffect() is None for w in load.findChildren(QWidget))
    load.line.set_level(0.4)
    assert load.line.level == pytest.approx(0.4)


def test_the_gentle_line_goes_round_its_lines(load):
    load.show()
    seen = [load.line.text()]
    for _ in range(len(S.LOAD_LINES)):
        load.next_line()
        assert wait_until(lambda: load.line.text() != seen[-1], 3)
        seen.append(load.line.text())
    assert seen[:len(S.LOAD_LINES)] == list(S.LOAD_LINES) and seen[-1] == S.LOAD_LINES[0]
