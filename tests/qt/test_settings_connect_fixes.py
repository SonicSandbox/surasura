"""Settings' writing rows of Connect and Anki — the review's fixes (W3.3 FX-connect; registers W3.3-writes-r2 S1–S4,
N1, N2 and W3.3-page-adversary B3, S4).

What a wrong answer would cost: Anki holding a confirmed New cards a day while the report's pace stays at the old one
(the page closed during the write); the next *Change in Anki…* written to a deck Junban no longer uses; a Yes that
writes nothing and says nothing; every language's watermark moved again by a switch-on Connect was already in (cards
never mined for what was placed meanwhile); the shell's Connect line not told the file changed; a page that jumps under
the reader as Anki's answers land; Tab skipping Connect's switch. All with fakes: never a real Anki, AnkiConnect, Anki
Miner or the network — `_send` is refused outright (the `world` fixture).
"""
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from app import anki_deck_options as ado
from app.qt import bridge
from app.qt import settings_connect as scn
from app.qt import settings_page as sp
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_settings_connect import DECK, FakeSwitch, Store, gone, make, miner_result, names, settled, world  # noqa: F401
from tests.qt.test_settings_page import EVERYTHING

HSK = "中文::HSK 3"
LONG_DECK = ("日本語::アニメ::葬送のフリーレン::第一期::字幕から作ったカード::未学習の語彙::あとで見直す言葉::"
             "二回目に観るときに覚えたい言葉::その他")


def make_heard(world, monkeypatch, data=None):
    """As `make`, with a shell that has its own bridge (the window's): what the shell hears outlives the page."""
    store = Store(dict({"target_language": "ja", "junban_deck": DECK, "words_per_day": 5}, **(data or {})),
                  events=world.events)
    heard = bridge.Bridge()
    shell = SimpleNamespace(services=SimpleNamespace(settings=store), bar_line=world.bar, bridge=heard)
    page = sp.SettingsPage(shell, "ja", found=EVERYTHING)
    page.resize(1100, 700)
    page.show()
    assert wait_until(lambda: page.built, 20)
    rows = scn.attach(page)
    fake = FakeSwitch(store)
    monkeypatch.setattr(scn, "_switch", lambda: fake)
    assert wait_until(lambda: not rows.miner.checking and rows.new_cards.field.isVisibleTo(page), 10)
    return page, store, rows, fake, heard


def confirm_change(world, rows, value=30):
    rows.new_cards.field.set_value(value)
    QTest.mouseClick(rows.new_cards.change, Qt.MouseButton.LeftButton)
    assert world.asked, "Change in Anki… asked nothing"
    return world.asked[-1]


# --- writes S1: the pace saved though the page went ---------------------------------------------------------------- #
@pytest.mark.parametrize("took", [False, True])
def test_a_confirmed_write_that_ends_after_the_page_went_still_saves_the_pace(world, qt_errors, took):
    """The write had Anki's lock when the page closed (cancel no longer stops it): Anki ends at 30, so does
    `words_per_day` — through the service, nothing painted. `took`: Anki took 30 though other options moved."""
    page, store, rows, _fake = make(world)
    holding = threading.Event()
    release = threading.Event()

    def held(cancel):
        holding.set()
        assert release.wait(10)
    world.write_gate = held
    if took:
        world.outcome = ado.Outcome(False, "Anki took 30 New cards a day, but other options came back different: "
                                           "new.delays. Check the options group in Anki.", 30, False, True)
    confirm_change(world, rows).answer(True)
    assert holding.wait(5)
    page.close()
    gone(page)
    release.set()
    assert wait_until(lambda: store.calls, 5), "the pace wasn't saved once the page went"
    assert store.calls == [({"words_per_day": 30}, None)]
    QApplication.processEvents()
    assert qt_errors == []


def test_a_write_that_ends_refused_after_the_page_went_saves_nothing(world, qt_errors):
    page, store, rows, _fake = make(world)
    release = threading.Event()
    world.write_gate = lambda cancel: release.wait(10)
    world.outcome = ado.Outcome(False, "Anki refused the change: deck missing", 20, False)
    confirm_change(world, rows).answer(True)
    assert wait_until(lambda: world.writes, 5)
    page.close()
    gone(page)
    release.set()
    for _ in range(20):
        QApplication.processEvents()
    assert store.calls == [] and qt_errors == []


# --- writes S2: a deck changed during a write is read when it ends ------------------------------------------------- #
def test_a_deck_change_while_a_write_goes_is_read_once_the_write_ends(world):
    """Junban's deck set to another while the write waits for Anki's lock: once it ends the row reads that deck, so the
    next Change goes to the deck Junban uses."""
    page, store, rows, _fake = make(world)
    release = threading.Event()
    world.write_gate = lambda cancel: release.wait(10)
    confirm_change(world, rows).answer(True)
    assert wait_until(lambda: world.writes and rows.new_cards.busy, 5)
    world.reading = ado.Reading(15, HSK, "HSK", None)
    store.outside({"junban_deck": HSK})
    QApplication.processEvents()
    assert [deck for _gui, deck in world.reads] == [DECK], "read while the write still went"
    release.set()
    assert wait_until(lambda: [deck for _gui, deck in world.reads] == [DECK, HSK] and rows.new_cards.reading
                      and rows.new_cards.reading.deck == HSK, 5)
    assert rows.new_cards.field.value() == 15
    assert HSK in rows.new_cards.words.text()


def test_an_address_change_while_a_write_goes_is_read_once_the_write_ends(world):
    page, store, rows, _fake = make(world)
    release = threading.Event()
    world.write_gate = lambda cancel: release.wait(10)
    confirm_change(world, rows).answer(True)
    assert wait_until(lambda: rows.new_cards.busy, 5)
    store.outside({"anki_connect_url": "http://127.0.0.1:8766"})
    release.set()
    assert wait_until(lambda: len(world.reads) == 2 and not rows.new_cards.busy, 5)


def test_a_write_with_nothing_changed_meanwhile_reads_nothing_more(world):
    page, store, rows, _fake = make(world)
    confirm_change(world, rows).answer(True)
    assert wait_until(lambda: world.writes and not rows.new_cards.busy and store.calls, 5)
    for _ in range(10):
        QApplication.processEvents()
    assert len(world.reads) == 1


# --- writes S3: a Yes after Anki was read again --------------------------------------------------------------------- #
def reread_during(world, rows, reading):
    """The question open, Anki read again (as a landed `anki_connect_url` write would) with `reading`."""
    asked = confirm_change(world, rows)
    world.reading = reading
    rows.new_cards.read()
    assert wait_until(lambda: rows.new_cards.reading is reading, 5), "the re-read never landed"
    return asked


def test_a_yes_after_a_reread_with_the_same_deck_and_number_still_writes(world):
    """A re-read that found what was asked about (a new object, the same deck and value): the Yes goes on."""
    page, store, rows, _fake = make(world)
    asked = reread_during(world, rows, ado.Reading(20, DECK, "Default", None))
    asked.answer(True)
    assert wait_until(lambda: world.writes and store.calls, 5)
    assert (world.writes[0]["deck"], world.writes[0]["value"], world.writes[0]["expect"]) == (DECK, 30, 20)


def test_a_yes_after_anki_s_number_moved_meanwhile_writes_nothing_and_says_why(world):
    page, store, rows, _fake = make(world)
    asked = reread_during(world, rows, ado.Reading(25, DECK, "Default", None))
    asked.answer(True)
    QApplication.processEvents()
    assert world.writes == [] and store.calls == []
    assert world.bar.lines[-1] == S.NEW_CARDS_VALUE_MOVED.format(deck=DECK, n=25)
    assert rows.new_cards.field.value() == 25


def test_a_yes_after_junbans_deck_moved_meanwhile_writes_nothing_and_says_why(world):
    page, store, rows, _fake = make(world)
    asked = reread_during(world, rows, ado.Reading(20, HSK, "HSK", None))
    asked.answer(True)
    QApplication.processEvents()
    assert world.writes == [] and store.calls == []
    assert world.bar.lines[-1] == S.NEW_CARDS_DECK_MOVED.format(asked=DECK, deck=HSK)


def test_a_yes_after_anki_became_unreadable_writes_nothing_and_keeps_the_pace_shown(world):
    page, store, rows, _fake = make(world, {"words_per_day": 12})
    asked = confirm_change(world, rows)
    world.reading = "Anki isn't open, or AnkiConnect isn't installed."
    rows.new_cards.read()
    assert wait_until(lambda: rows.new_cards.unread, 5)
    asked.answer(True)
    QApplication.processEvents()
    assert world.writes == [] and store.calls == []
    assert world.bar.lines[-1] == S.NEW_CARDS_UNREAD_NOW
    assert rows.new_cards.field.value() == 12, "the pace, never Anki's old number"


def test_a_no_after_a_reread_says_nothing(world):
    page, store, rows, _fake = make(world)
    asked = reread_during(world, rows, ado.Reading(25, DECK, "Default", None))
    lines = list(world.bar.lines)
    asked.answer(False)
    QApplication.processEvents()
    assert world.writes == [] and world.bar.lines == lines


# --- writes S4: switching on when the file already says on --------------------------------------------------------- #
def test_switching_on_when_the_file_already_says_on_moves_no_watermark(world, monkeypatch):
    """Another window switched Connect on (the toggle never heard): on → the file read first, no turn_on / back-fill,
    only the reload; the toggle shows on and Connect's rows show."""
    page, store, rows, fake = make(world, monkeypatch=monkeypatch)
    store.file["connect_enabled"] = True                 # saved elsewhere, never announced
    assert rows.switch.toggle.value() is False
    rows.switch.toggle.changed.emit(True)
    assert settled(rows)
    assert names(world.events) == ["reload"]
    assert world.events[0][1] is False, "the reload ran on the GUI thread"
    assert rows.switch.toggle.value() is True and rows.switch.toggle.isEnabled()
    assert S.SWITCH_ALREADY_ON in world.bar.lines
    assert page.rows["connect_mine_words"].isVisibleTo(page)
    assert store.calls == []


def test_switching_on_reads_the_file_not_the_copy_in_memory(world, monkeypatch):
    """The copy in memory says on but the file says off (switched off elsewhere): turn_on runs as usual."""
    page, store, rows, fake = make(world, monkeypatch=monkeypatch)
    store.fresh = lambda: {"connect_enabled": False}
    rows.switch.toggle.changed.emit(True)
    assert settled(rows)
    assert names(world.events) == ["turn_on", "backfill", "reload"]


# --- writes N2: the switch's write told on the shell's bridge though the page went --------------------------------- #
def test_a_switch_on_that_ends_after_the_page_went_is_still_told_to_the_shell(world, monkeypatch, qt_errors):
    page, store, rows, fake, heard = make_heard(world, monkeypatch)
    told = []
    heard.settings_written.connect(told.append)
    fake.gate = threading.Event()
    rows.switch.toggle.changed.emit(True)
    assert wait_until(lambda: names(world.events) == ["turn_on"], 5)
    page.close()
    gone(page)
    fake.gate.set()
    assert wait_until(lambda: told, 10), "the shell never heard the switch's write"
    assert told == [("connect_enabled",)]
    QApplication.processEvents()
    assert qt_errors == []


def test_a_switch_on_that_failed_after_the_page_went_tells_nothing(world, monkeypatch, qt_errors):
    page, store, rows, fake, heard = make_heard(world, monkeypatch)
    told = []
    heard.settings_written.connect(told.append)
    fake.gate = threading.Event()
    fake.on = (False, "Japanese: the library is busy")
    rows.switch.toggle.changed.emit(True)
    assert wait_until(lambda: names(world.events) == ["turn_on"], 5)
    page.close()
    gone(page)
    fake.gate.set()
    for _ in range(20):
        QApplication.processEvents()
    assert told == []


def test_a_switch_off_that_ends_after_the_page_went_is_still_told_to_the_shell(world, monkeypatch, qt_errors):
    page, store, rows, fake, heard = make_heard(world, monkeypatch, {"connect_enabled": True})
    told = []
    heard.settings_written.connect(told.append)
    gate = threading.Event()
    shelved = fake.shelved

    def slow_shelf(languages):
        assert gate.wait(10)
        return shelved(languages)
    fake.shelved = slow_shelf
    rows.switch.toggle.changed.emit(False)
    assert wait_until(lambda: rows.switch.running, 5)
    page.close()
    gone(page)
    gate.set()
    assert wait_until(lambda: told, 10)
    assert told == [("connect_enabled",)] and names(world.events)[-2:] == ["turn_off", "reload"]


# --- writes N1: the put-back question says Connect turns off either way ------------------------------------------- #
def test_the_put_back_question_says_no_and_esc_still_turn_connect_off(world, monkeypatch):
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    fake.shelf = {"ja": (3, ["run-2026-10-14"])}
    rows.switch.toggle.changed.emit(False)
    assert wait_until(lambda: world.asked, 5)
    body = world.asked[0].body
    assert body == S.PUT_BACK_BODY
    assert "either way" in body and "Esc" in body and S.PUT_BACK_NO in body and "shelf" in body


# --- page B3: late answers never move the page --------------------------------------------------------------------- #
def scrolled_below(page, row_id):
    """The page scrolled so `row_id`'s row sits just above the viewport -> the first row in view (what must stay)."""
    view = page.rows[row_id]
    page._settle()
    bar = page.scroll.verticalScrollBar()
    body = page.scroll.widget()
    bar.setValue(view.mapTo(body, QPoint(0, 0)).y() + view.height() + 30)
    page._settle()
    QApplication.processEvents()
    anchor = page._top_widget()
    assert anchor is not None and anchor is not view
    return anchor


def y_in_view(page, widget):
    return widget.mapTo(page.scroll.viewport(), QPoint(0, 0)).y()


def test_the_anki_miner_answer_landing_above_the_reader_never_moves_the_page(world):
    page, store, rows, _fake = make(world)
    anchor = scrolled_below(page, "anki_miner")
    y0, h0 = y_in_view(page, anchor), page.rows["anki_miner"].height()
    world.miner = miner_result("setup")                       # the card grows: missing pieces, the guided steps
    world.update = {"version": "3.8.0", "url": "https://github.com/anki-miner/releases"}
    rows.miner.check()
    assert wait_until(lambda: not rows.miner.checking, 5)
    for _ in range(5):
        QApplication.processEvents()
    page._settle()
    assert page.rows["anki_miner"].height() > h0 + 40, "the card didn't grow: this test proves nothing"
    assert y_in_view(page, anchor) == y0


def test_the_new_cards_answer_landing_above_the_reader_never_moves_the_page(world):
    page, store, rows, _fake = make(world)
    anchor = scrolled_below(page, "new_cards_a_day")
    y0, h0 = y_in_view(page, anchor), page.rows["new_cards_a_day"].height()
    world.reading = ado.Reading(20, LONG_DECK, "Default", None)
    store.file["junban_deck"] = LONG_DECK                     # the help line names the deck: a longer one wraps
    rows.new_cards.read()
    assert wait_until(lambda: rows.new_cards.reading.deck == LONG_DECK, 5)
    for _ in range(5):
        QApplication.processEvents()
    page._settle()
    assert page.rows["new_cards_a_day"].height() > h0, "the row didn't grow: this test proves nothing"
    assert y_in_view(page, anchor) == y0


# --- page S4: Tab reaches Connect's rows in their place ------------------------------------------------------------ #
def focus_chain(page):
    chain, w = [], page.nextInFocusChain()
    while w is not page and len(chain) < 3000:
        if w.focusPolicy() & Qt.FocusPolicy.TabFocus:
            chain.append(w)
        w = w.nextInFocusChain()
    return chain


def first_focusable(view):
    return next(w for w in view.slot.findChildren(QWidget) if w.focusPolicy() & Qt.FocusPolicy.TabFocus)


def test_tab_reaches_connects_switch_and_the_anki_miner_card_where_they_stand(world):
    """After `attach` fills the slots, the chain runs New cards a day → Connect's switch → Mine words…, and the card's
    buttons come before the rows below it, never after the last App row."""
    page, store, rows, _fake = make(world)
    chain = focus_chain(page)
    at = {w: i for i, w in enumerate(chain)}
    switch = first_focusable(page.rows["connect_enabled"])
    assert at[rows.new_cards.field.edit] < at[switch] < at[first_focusable(page.rows["connect_mine_words"])]
    miner = first_focusable(page.rows["anki_miner"])
    assert at[first_focusable(page.rows["enable_youtube_transcripts"])] < at[miner]
    assert at[miner] < at[first_focusable(page.rows["theme"])] < at[first_focusable(page.rows["text_size"])]
