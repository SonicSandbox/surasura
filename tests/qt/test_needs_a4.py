"""Alpha 4's *Needs you* in the window (Mattias #4: "Needs you with 3,000+ items opens slowly and looks frozen"; Sonic
2026-10-27: a card can't be dismissed or deferred, "what do they do if they have a hundred of these?"): the page built
as it is read, the line for every missing file, every card's ⋯
(*Not now* · *Stop asking*, with Undo) and the line over many cards that share a reason — on the window's seed through
the stand-in store, real Japanese and Chinese titles from tests/Test Resources/.

What a wrong answer would cost a learner: a page frozen for seconds at its press (it was ~20 s at 3,000 cards); a card
built twice, or never, as the page is scrolled; a whole page rebuilt by a look that found the same cards; *Start fresh*
offered with nothing behind it; a card put away for good when he only said "not now", or one he can't get back.
"""
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import needs as needs_ui
from app.qt import stones, strings
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_gone_folder import Looks, world  # noqa: F401 — the window with its looks, ja and zh
from tests.test_library_store_support import LANGUAGES, names


@pytest.fixture(autouse=True)
def _stones_sheet(qapp):
    key = stones._key(1.0, "M")
    if key not in stones._SHEETS:
        stones._landed(key, stones.build(*key))


def many(language, n, missing=None):
    """A view of `n` shows with one episode each, `missing` of them gone (all by default) — real titles, each show in a
    folder of its own at the library's top (K3: shows gone together under one folder are that folder's one card)."""
    titles = names(language)
    rows = []
    for i in range(n):
        t = f"{titles[i % len(titles)]} 第{i // len(titles) + 1}期"
        ep = SimpleNamespace(id=900000 + i, label=f"第{(i % 12) + 1}話", number=(i % 12) + 1,
                             rel_path=f"{t}/{t} - {(i % 12) + 1:02d}.srt",
                             missing=i < (n if missing is None else missing))
        rows.append(SimpleNamespace(key=f"w{i}", work_id=900000 + i, title=t, media="anime", tier="now",
                                    episodes=(ep,)))
    return SimpleNamespace(mode="store", rows=tuple(rows), loading=False, needs=())


def hand_in(ny, entries):
    """The page given `entries` as a gather would, and no other gather after (the stand-in's own stay out)."""
    assert wait_until(lambda: not ny._running, 10)            # (a gather of the window's opening lands first)
    ny.refresh = lambda: None
    ny._asked += 1                                            # (and one still on its way is an old answer)
    ny._got((ny._asked, tuple(entries)))
    for _ in range(5):
        QApplication.processEvents()


def scroll_to_end(ny):
    bar = ny.page.area.verticalScrollBar()
    bar.setValue(bar.maximum())
    for _ in range(3):
        QApplication.processEvents()


# --- B: the page built as it is read ------------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", LANGUAGES)
def test_3000_cards_open_with_2_built_in_the_press_30_after_and_more_only_as_the_page_is_scrolled(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    entries = service.entries(many(language, 3000))
    hand_in(ny, entries)
    assert ny.cards.builds == 0                               # hidden: nothing built under the style sheet (C1)
    win.show_tab("needs")
    assert len(ny.cards.order) == needs_ui.FIRST_FRAME        # the page there in the press's frame
    assert wait_until(ny.cards.settled, 10)
    assert len(ny.cards.order) == needs_ui.BUILT_AT_ONCE      # the first ones on idle time, and no more by themselves
    for _ in range(20):
        QApplication.processEvents()
    assert len(ny.cards.order) == needs_ui.BUILT_AT_ONCE
    for _ in range(3):                                        # scrolled to its end: the next ones, each time
        before = len(ny.cards.order)
        scroll_to_end(ny)
        assert wait_until(lambda: len(ny.cards.order) > before and ny.cards.settled(), 10)
    built = ny.cards.order
    assert built == [e.key for e in entries[:len(built)]]     # the entries' first ones, in order
    assert len(set(built)) == len(built) == ny.cards.builds   # each built once, none twice
    assert len(built) <= 4 * needs_ui.BUILT_AT_ONCE


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_gather_that_found_the_same_3000_cards_builds_and_repaints_nothing(world, language):
    """S19: a look that found nothing new builds no card and tells the tab nothing."""
    seed, win, writer, ny = world(language, looks=Looks())
    entries = service.entries(many(language, 3000))
    hand_in(ny, entries)
    win.show_tab("needs")
    assert wait_until(ny.cards.settled, 10)
    builds, told = ny.cards.builds, []
    ny.changed.connect(lambda: told.append(True))
    ny._got((ny._asked, tuple(service.entries(many(language, 3000)))))      # the same cards, read again
    for _ in range(10):
        QApplication.processEvents()
    assert ny.cards.builds == builds and told == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_card_asked_for_far_down_is_built_with_those_before_it_and_the_rest_wait(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    entries = service.entries(many(language, 300))
    hand_in(ny, entries)
    win.show_tab("needs")
    assert wait_until(ny.cards.settled, 10)
    far = entries[120]
    assert ny.cards.card(far.key) is not None
    assert ny.cards.order == [e.key for e in entries[:121]] and ny.cards.builds == 121


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_gone_folder_card_is_on_top_so_todokes_press_opens_the_page_at_it_whatever_follows(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    folder = {"id": 13, "path": os.path.join("C:\\Users\\Michael\\Downloads", names(language)[71]), "items": 12,
              "shows": [names(language)[71]], "finished": False, "found_in": []}
    entries = service.entries(many(language, 3000), gone_folders=[folder])
    hand_in(ny, entries)
    win.show_tab("needs")
    ny.reveal_gone()
    assert ny.cards.builds <= needs_ui.BUILT_AT_ONCE          # never 3,000 cards built to get there


# --- B: the line for every missing file -------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_forget_every_missing_file_is_one_writer_command_one_toast_one_undo(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    writer.remove = lambda ids, label=None: writer._put("remove", ids, label)     # (the writer's own command)
    entries = service.entries(many(language, 40))
    hand_in(ny, entries)
    win.show_tab("needs")
    b = next(b for b in ny.cards.buttons("bulk") if b.property("action") == "remove_all")
    assert b.text() == "Forget every missing file (40)" and b.toolTip()
    b.click()
    assert ny.confirming.title.text() == "Forget 40 missing files?"
    ny.confirming.yes.click()
    assert wait_until(lambda: writer.saved, 5)
    removes = [c for c in writer.calls if c[0] == "remove"]
    assert len(removes) == 1 and sorted(removes[0][1]) == sorted(e.data["item_ids"][0] for e in entries[1:])
    assert win.toasts.card.base == strings.NEEDS_FORGOT.format(n=40)
    win.toasts.card.buttons[0].click()                         # one Undo for all of them
    assert wait_until(lambda: writer.undone and writer.undone[-1].op == "remove", 5)


# (K1 / K3's cards in the window: tests/qt/test_needs_seams.py)
def _settle_gather(ny, view):
    ny.view = view
    ny.find_offline = lambda _lang, _rels, _data: []          # the library folder is there (no drive offline)
    n = ny.gathers
    ny.refresh()
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    for _ in range(5):
        QApplication.processEvents()


# --- D2: every card's ⋯ — Not now, Stop asking ------------------------------------------------------------------- #
def _more(ny, key):
    card = ny.cards.card(key)
    return getattr(card, "more", None)


def _pick(ny, entry, name):
    """The ⋯ opened on `entry`'s card and `name` picked in it."""
    m = ny.more_menu(entry, _more(ny, entry.key))
    act = next(a for a in m.actions() if a.property("action") == name)
    assert act.toolTip()
    act.trigger()
    m.hide()


def _gather(ny, view):
    _settle_gather(ny, view)


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_card_has_a_more_square_holding_not_now_and_stop_asking_and_its_buttons_stay(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    _gather(ny, many(language, 2))
    win.show_tab("needs")
    gone = next(e for e in ny.entries if e.kind == service.GONE)
    more = _more(ny, gone.key)
    assert more is not None and more.toolTip() and more.accessibleName()
    m = ny.more_menu(gone, more)
    assert [a.property("action") for a in m.actions()] == ["later", "stop_asking"]
    assert [a.text() for a in m.actions()] == ["Not now", "Stop asking"] and all(a.toolTip() for a in m.actions())
    m.hide()
    acts = [b.property("action") for b in ny.cards.buttons(gone.key)]
    assert {"choose_folder", "keep_words", "remove"} <= set(acts)           # its own answers stay where they were


def test_the_cards_whose_two_answers_both_end_them_get_no_more_square(world):
    seed, win, writer, ny = world("ja", looks=Looks())
    first = service.Entry(key=service.FIRST_CARDS, kind=service.FIRST_CARDS, title="Make cards for your first 20 "
                          "episodes?", lines=(), actions=("first_cards", "not_now"), unseen=True)
    hand_in(ny, [first])
    win.show_tab("needs")
    assert _more(ny, first.key) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_not_now_takes_the_card_off_at_once_back_tomorrow_and_undo_brings_it_back(world, language, monkeypatch):
    seed, win, writer, ny = world(language, looks=Looks())
    _gather(ny, many(language, 1))
    win.show_tab("needs")
    [card] = [e for e in ny.entries if e.kind == service.GONE]
    _pick(ny, card, "later")
    assert card.key not in ny.cards.order                     # off the page in the press's own frame
    assert ny.counts() == (0, 0)
    assert win.toasts.card.base == strings.NEEDS_LATER_ONE
    assert wait_until(lambda: card.key in service.read_hidden(language), 5)
    _settle_gather(ny, many(language, 1))
    assert card.key not in [e.key for e in ny.entries]        # a look later today leaves it off too
    monkeypatch.setattr(service, "_today", lambda: "2999-01-01")
    ny._new_day()                                             # the next day: it still needs you, so it is back
    assert wait_until(lambda: card.key in [e.key for e in ny.entries], 5)
    assert writer.calls == []                                 # nothing in the library changed


@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_asking_keeps_the_card_off_and_the_toasts_undo_brings_it_back(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    _gather(ny, many(language, 1))
    win.show_tab("needs")
    [card] = [e for e in ny.entries if e.kind == service.GONE]
    _pick(ny, card, "stop_asking")
    assert card.key not in ny.cards.order
    assert win.toasts.card.base == strings.NEEDS_STOPPED_ONE
    assert wait_until(lambda: card.key in service.read_hidden(language), 5)
    assert wait_until(lambda: win.tab_buttons["needs"].isHidden(), 5)   # nothing left: the tab goes (A2 #70)
    win.toasts.card.buttons[0].click()                        # Undo
    assert wait_until(lambda: card.key not in service.read_hidden(language), 5)
    assert wait_until(lambda: card.key in [e.key for e in ny.shown_entries()], 5)
    assert wait_until(lambda: not win.tab_buttons["needs"].isHidden(), 5)
    assert service.read_answered(language) == frozenset() and writer.calls == []    # its item and words kept


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_seen_file_that_cant_be_written_puts_the_card_back_and_says_why(world, language, monkeypatch):
    seed, win, writer, ny = world(language, looks=Looks())
    _gather(ny, many(language, 1))
    win.show_tab("needs")
    [card] = [e for e in ny.entries if e.kind == service.GONE]

    def held(_lang, _keys):
        raise PermissionError("needs_seen is held")
    monkeypatch.setattr(service, "put_off", held)
    _pick(ny, card, "later")
    assert wait_until(lambda: card.key in [e.key for e in ny.shown_entries()], 5)
    assert wait_until(lambda: "needs_seen is held" in win.bar_line.full(), 5)


# --- D2: one line over many cards that share a reason ------------------------------------------------------------- #
def _folders(language, n):
    return [{"id": 10 + i, "path": os.path.join("C:\\Users\\Michael\\Downloads", names(language)[i]), "items": 3,
             "shows": [names(language)[i]], "finished": False, "found_in": []} for i in range(n)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_38_gone_folders_bring_one_line_on_top_not_now_for_all_hides_them_and_undo_brings_them_back(world,
                                                                                                    language):
    seed, win, writer, ny = world(language, looks=Looks())
    ny.find_offline = lambda _lang, _rels, _data: []          # the library folder is there (no drive offline)
    ny.view = many(language, 3, missing=0)                    # (no file gone: the folders alone)
    ny.gone_in(_folders(language, 38), language)
    assert wait_until(lambda: ny.entries and ny.entries[0].kind == service.BULK, 10)
    line = ny.entries[0]
    assert line.title == "38 source folders are gone"
    win.show_tab("needs")
    assert [b.property("action") for b in ny.cards.buttons(line.key)] == ["later_all"]
    m = ny.more_menu(line, _more(ny, line.key))
    assert [a.property("action") for a in m.actions()] == ["stop_all"]
    m.hide()
    next(b for b in ny.cards.buttons(line.key) if b.property("action") == "later_all").click()
    assert ny.cards.order == [] and ny.counts() == (0, 0)     # every one of them off at once, and the line
    assert win.toasts.card.base == strings.NEEDS_LATER_N.format(n=38)
    assert wait_until(lambda: len(service.read_hidden(language)) == 39, 5)
    win.toasts.card.buttons[0].click()                        # Undo: all of them back
    assert wait_until(lambda: len([e for e in ny.entries if e.kind == service.FOLDER_GONE]) == 38, 5)


@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_asking_for_all_on_the_missing_files_line_takes_every_show_off(world, language):
    seed, win, writer, ny = world(language, looks=Looks())
    _gather(ny, many(language, 5))
    win.show_tab("needs")
    bulk = ny.entries[0]
    assert bulk.key == "bulk" and len(bulk.data["keys"]) == 5
    m = ny.more_menu(bulk, _more(ny, bulk.key))
    assert [a.property("action") for a in m.actions()] == ["later_all", "stop_all"]
    next(a for a in m.actions() if a.property("action") == "stop_all").trigger()
    m.hide()
    assert ny.cards.order == []
    assert wait_until(lambda: set(bulk.data["keys"]) <= service.read_hidden(language), 5)
    _settle_gather(ny, many(language, 5))
    assert ny.entries == ()                                   # a later look asks about none of them
    assert writer.calls == []
