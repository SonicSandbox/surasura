"""*Which words get a card?* — the picker (Mado-EZC; SPEC-r2 §0.3, EZ2-9's clicks; `app/qt/card_picker.py`).

What a wrong answer would cost: a setting saved by a look (Esc, Cancel, a click outside, Back) that the learner meant to
leave; two writes where the spec promises one (a settings write and a store write that Undo can't put back together);
a *Your list* that isn't first and recommended; a second step that asks about 順 where 順 isn't (Chinese, 順 off); a
picture that never shows a sample when there is no episode (an empty picker).

The settings service is P3's `Recorder`; the library's writer and reader are fakes that keep each call.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from app.connect import settings_values
from app.qt import card_picker, strings
from app.services import card_sample
from tests.qt.conftest import wait_until
from tests.qt.test_settings_page import EVERYTHING, Recorder, _no_direct_save  # noqa: F401 (the autouse guard)


class Writer:
    def __init__(self, refuse=False):
        self.calls = []
        self.refuse = refuse

    def set_options(self, **options):
        self.calls.append(options)
        return None if self.refuse else len(self.calls)


class Reader:
    def __init__(self, line=20):
        self.line = line

    def options(self):
        return {"mine_line": self.line} if self.line is not None else {}


class Toasts:
    def __init__(self):
        self.shown = []

    def show(self, message, undo=None, **_more):
        self.shown.append((message, undo))


class Worker:
    """The warm arrivals worker's `sample`: answers with `picture` (None: a library with no list yet)."""

    def __init__(self, picture=None):
        self.picture, self.asked = picture, 0

    def sample(self, paths=None, callback=None):
        self.asked += 1
        callback({"op": "sample", "picture": self.picture})


class Host(QWidget):
    """The main window as the picker reaches it: its services, its toasts, its warm worker, its language."""

    def __init__(self, data=None, language="ja", line=20, picture=None, refuse=False):
        super().__init__()
        self.language = language
        self.store = Recorder(dict({"target_language": language}, **(data or {})))
        self.writer = Writer(refuse)
        self.services = SimpleNamespace(settings=self.store, writer=self.writer, library=Reader(line))
        self.toasts = Toasts()
        self.worker = Worker(picture)
        self.overlays = []
        self.resize(1200, 760)
        self.show()

    def arrivals_worker(self):
        return self.worker

    def register_overlay(self, widget):
        self.overlays.append(widget)


JUNBAN_ON = {"enable_junban": True, "junban_unlisted": "list_first", "connect_enabled": True,
             "logic": {"automation": True}}


def _open(host, found=EVERYTHING):
    picker = card_picker.open_card_picker(host, found=found)
    QApplication.processEvents()
    return picker


def _pick(picker, mode):
    """Press the choice card of `mode` (by its value, never its place)."""
    picker.words._choose(picker.words.values().index(mode))
    QApplication.processEvents()


def _esc(picker):
    QApplication.sendEvent(picker, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))


@pytest.mark.parametrize("leave", ["cancel", "outside", "close"])
def test_leaving_without_done_writes_nothing_whatever_was_picked(qapp, leave):
    # Why: EZ2-9 — nothing is saved until Done; Cancel, Esc / Back (the window's router closes it: `close`) or a click
    # outside leave every setting and the library's line as they were.
    host = Host(JUNBAN_ON)
    picker = _open(host)
    _pick(picker, "i1")
    picker.go(3)
    picker.ahead._choose(picker.ahead.values().index(40))
    picker.wait._choose(picker.wait.values().index(600))
    assert picker.changes() == 3 and picker.summary.text() == strings.PICK_CHANGES_MORE.format(n=3)
    if leave == "cancel":
        picker.cancel.click()
    elif leave == "outside":
        QTest.mouseClick(picker.scrim, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    else:
        picker.close()
    QApplication.processEvents()
    assert not picker.isVisible() and not picker.scrim.isVisible()
    assert host.store.calls == [] and host.writer.calls == [] and host.toasts.shown == []
    assert picker in host.overlays                           # Esc and the mouse's Back reach it through the router


def test_done_is_one_settings_write_and_one_store_command_and_undo_puts_both_back(qapp):
    # Why: EZ2-9 / the lane's risk — Done makes ONE settings write (only the keys that moved) and ONE store command
    # (the mine line lives in the library), and one Undo covers both.
    host = Host(dict(JUNBAN_ON, connect_backlog_cap={"ja": 300, "zh": 150}))
    picker = _open(host)
    assert picker.steps == (1, 2, 3)                          # 順 there and on, Japanese: the second word's step
    _pick(picker, "i1")
    picker.go(2)
    picker.ready._choose(0)                                   # Learn the other word first
    picker.go(3)
    picker.ahead._choose(picker.ahead.values().index(10))
    picker.wait._choose(picker.wait.values().index(600))
    assert picker.done.isVisible() and not picker.next.isVisible()
    picker.done.click()
    QApplication.processEvents()
    assert not picker.isVisible()
    assert host.store.calls == [({"connect_mine_words": "i1", "junban_ready_first": True,
                                  "connect_backlog_cap": {"ja": 600, "zh": 150}}, None)]
    assert host.writer.calls == [{"mine_line": 10}]
    (message, undo), = host.toasts.shown
    assert message == strings.PICK_SAVED.format(name="Only i+1 sentences")
    host.services.library.line = 10                            # the library's view of Done's line landed
    undo()
    assert host.store.calls[-1] == ({"connect_mine_words": "list", "junban_ready_first": False,
                                     "connect_backlog_cap": {"ja": 300, "zh": 150}}, None)
    assert host.writer.calls[-1] == {"mine_line": 20}
    # nothing moved: Done closes and writes nothing
    picker = _open(host)
    picker.go(3)
    picker.done.click()
    assert len(host.store.calls) == 2 and len(host.writer.calls) == 2 and len(host.toasts.shown) == 1


def test_only_the_line_moved_is_the_store_command_alone_and_a_refused_one_still_saves_the_settings(qapp):
    host = Host(JUNBAN_ON)
    picker = _open(host)
    picker.go(3)
    picker.ahead._choose(picker.ahead.values().index(5))
    picker.done.click()
    assert host.store.calls == [] and host.writer.calls == [{"mine_line": 5}]
    refused = Host(JUNBAN_ON, refuse=True)                    # a read-only library: the line isn't kept
    said = []
    refused.bar_line = SimpleNamespace(set_full=said.append)
    picker = _open(refused)
    _pick(picker, "unknown")
    picker.go(3)
    picker.ahead._choose(picker.ahead.values().index(40))
    picker.done.click()
    assert refused.store.calls == [({"connect_mine_words": "unknown"}, None)]
    assert picker.written == ({"connect_mine_words": "unknown"}, None)
    assert len(said) == 1 and said[0]                          # the bar says the line wasn't kept, and why


def test_undo_leaves_a_mine_line_moved_since_done_as_it_is(qapp):
    # Why: the line has Undo's value check too — one moved in Fine-tune while the toast showed stays.
    host = Host(JUNBAN_ON)
    picker = _open(host)
    picker.go(3)
    picker.ahead._choose(picker.ahead.values().index(10))
    picker.done.click()
    host.services.library.line = 10                            # the library holds Done's line: Undo puts 20 back
    (_m, undo), = host.toasts.shown
    undo()
    assert host.writer.calls == [{"mine_line": 10}, {"mine_line": 20}]
    picker = _open(host)
    picker.go(3)
    picker.ahead._choose(picker.ahead.values().index(5))
    picker.done.click()
    host.services.library.line = 40                            # moved elsewhere since: left as it is
    undo = host.toasts.shown[-1][1]
    undo()
    assert host.writer.calls[-1] == {"mine_line": 5}


@pytest.mark.parametrize("language, data, found, steps", [
    ("ja", JUNBAN_ON, EVERYTHING, (1, 2, 3)),
    ("zh", JUNBAN_ON, EVERYTHING, (1, 3)),                                  # 順's i+1 first is Japanese only
    ("ja", dict(JUNBAN_ON, enable_junban=False), EVERYTHING, (1, 3)),       # 順 off
    ("ja", JUNBAN_ON, EVERYTHING - {"modules.junban"}, (1, 3)),             # 順 absent (S10)
])
def test_the_second_word_step_shows_only_with_junban_there_and_on_in_japanese(qapp, language, data, found, steps):
    host = Host(data, language=language)
    picker = _open(host, found=found)
    assert picker.steps == steps
    picker.go(2)                                              # asked for a step it hasn't: the next it has
    assert picker.step == (2 if 2 in steps else 3)
    picker.close()


def test_your_list_is_first_and_recommended_then_only_i_plus_one_and_each_line_is_a_state(qapp):
    # Why: SPEC-r2 §0.3 (Sonic: "Your list should be recommended and the standard") — first, marked, the default; round
    # 2: *Only i+1 sentences* next, *Every new word* last; one table of names for the picker and Fine-tune
    # (`settings_values.WORDS`); each card's line a state (the cards it gives), never an explanation (criteria rule 7).
    host = Host({})
    picker = _open(host)
    options = picker.words._options
    assert [v for v, _l, _t in options] == list(card_picker.PICK_MODES) == ["list", "i1", "unknown"]
    assert picker.words.value() == "list"
    assert strings.PICK_RECOMMENDED in options[0][1] and strings.PICK_IN_USE in options[0][1]
    assert all(strings.PICK_RECOMMENDED not in label for _v, label, _t in options[1:])
    names = {value: label for value, label, _line in settings_values.WORDS}
    assert names["i1"] == "Only i+1 sentences"
    for value, shown, _t in options:
        assert shown.startswith(names[value])
    assert picker.words._lines == ["4 cards · 1 skipped", "3 cards · 2 later", "5 cards"]
    assert picker.where.text() == strings.PICK_WHERE                           # it says which setting it is
    picker.close()


def test_with_no_episode_the_bundled_sample_is_drawn_and_named_a_sample_and_a_real_one_replaces_it(qapp):
    # Why: an empty library still shows what each choice gives (the bundled 喫茶店の朝); the worker's real picture
    # replaces it as soon as it answers, its counts the picker's.
    host = Host(JUNBAN_ON)                                    # the worker answers no picture (no list yet)
    picker = _open(host)
    assert host.worker.asked == 1
    assert picker.result.source.text() == strings.PICK_SAMPLE.format(name="喫茶店の朝")
    assert picker.result.heading.text() == strings.PICK_GET_MORE.format(n=4)
    _pick(picker, "i1")
    assert picker.result.heading.text() == strings.PICK_GET_AWAY_UP_TO.format(get=strings.PICK_GET_MORE.format(n=3),
                                                                               m=2)
    picker.close()
    real = card_sample.fallback("ja")
    real = dict(real, sample=False, source="ぼっち・ざ・ろっく！ 01", elsewhere_exact=True,
                counts=dict(real["counts"], i1={"here": 3, "elsewhere": 1}))
    host.worker.picture = real
    picker = _open(host)
    assert wait_until(lambda: picker.result.source.text() == strings.PICK_SOURCE.format(name="ぼっち・ざ・ろっく！ 01"))
    _pick(picker, "i1")
    assert picker.result.heading.text().startswith(strings.PICK_GET_AWAY.format(get=strings.PICK_GET_MORE.format(n=3),
                                                                                m=1))
    picker.close()


def test_each_choice_is_drawn_as_the_cards_it_gives_and_what_it_skips(qapp):
    # Why: Sonic's glance test (round 2) — the picture is the result, drawn as cards: Your list gives 急に, 出てくる,
    # 調べる (each tagged *2 new words*, the other word underlined amber) and 香り, and skips モカブレンド (rarer than
    # your Level); Only i+1 sentences gives the one-new-word cards and draws 出てくる / 調べる as from a later episode;
    # Every new word gives モカブレンド too. Its trade-off is behind the heading's ?.
    host = Host(JUNBAN_ON)
    picker = _open(host)
    result = picker.result

    def tile(word):
        return next(t for t in result.tiles if t.card["surface"] == word)
    assert result.card_words() == ["急に", "出てくる", "調べる", "香り"]
    assert tile("出てくる").tag is not None and tile("出てくる").tag.text() == strings.PICK_TWO_NEW
    assert "調べる" in tile("出てくる").sentence.text() and tile("急に").tag is None
    assert result.skipped.text() == strings.PICK_SKIPPED.format(
        words=strings.PICK_SKIP_WHY["rare"].format(word="モカブレンド"))
    assert result.about.toolTip() == strings.PICK_TRADEOFF["list"]
    _pick(picker, "i1")
    assert result.card_words() == ["急に", "出てくる", "調べる", "香り", "モカブレンド"]
    assert tile("出てくる").card["outcome"] == "other" and tile("出てくる").sentence.text() == strings.PICK_LATER
    assert tile("出てくる").tag is None and not result.skipped.isVisibleTo(picker)
    assert "skipped" in result.about.toolTip() and "important" in result.about.toolTip()
    _pick(picker, "unknown")
    assert result.card_words() == ["急に", "出てくる", "調べる", "香り", "モカブレンド"]
    assert tile("モカブレンド").card["outcome"] == "card"
    assert not card_picker.SWAP and all("⇄" not in t.word.text() for t in result.tiles)
    picker.close()


def test_every_button_and_control_in_the_picker_is_tipped_and_named(qapp):
    from PyQt6.QtWidgets import QAbstractButton
    host = Host(JUNBAN_ON)
    picker = _open(host)
    for b in picker.findChildren(QAbstractButton):
        assert b.toolTip() and b.accessibleName(), b.text()
    for control in (picker.words, picker.ready, picker.ahead, picker.wait):
        assert control.toolTip() and control.accessibleName()
    picker.close()


def test_done_tells_its_caller_and_leaving_never_does(qapp):
    # Why: Your path's step ④ (Mado-EZP's `pick_your_cards`) ticks when the learner picks — a Done, even one that
    # keeps every choice — and never on Cancel, Esc or a click outside.
    host = Host(JUNBAN_ON)
    told = []
    picker = card_picker.open_card_picker(host, found=EVERYTHING, on_done=lambda: told.append("yours"))
    picker.cancel.click()
    picker = card_picker.open_card_picker(host, found=EVERYTHING, on_done=lambda: told.append("yours"))
    QTest.mouseClick(picker.scrim, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    assert told == []
    picker = card_picker.open_card_picker(host, found=EVERYTHING, on_done=lambda: told.append("yours"))
    picker.go(3)
    picker.done.click()
    assert told == ["yours"] and host.store.calls == []


def test_undo_leaves_a_setting_changed_since_done_as_it_is(qapp):
    # Why: Undo puts back only what Done wrote — a choice changed since (in Fine-tune, another window) stays (the
    # store's own value check, §6.11).
    host = Host(dict(JUNBAN_ON, connect_backlog_cap={"ja": 300, "zh": 150}))
    picker = _open(host)
    _pick(picker, "i1")
    picker.go(3)
    picker.wait._choose(picker.wait.values().index(600))
    picker.done.click()
    host.store.set({"connect_mine_words": "unknown"})          # changed in Fine-tune since
    (_message, undo), = host.toasts.shown
    undo()
    assert host.store.calls[-1] == ({"connect_backlog_cap": {"ja": 300, "zh": 150}}, None)
    assert host.store.get()["connect_mine_words"] == "unknown"


def test_essentials_showing_never_starts_the_worker_but_asks_one_already_running(qapp):
    # Why: opening Settings must stay light — the warm worker's process starts only on the picker's open (the press);
    # a worker already running is asked, so the card shows the learner's own episode as soon as it can.
    host = Host(JUNBAN_ON)
    sampler = card_picker.sampler(host, "ja", host)
    host.worker.running = False
    assert sampler.ask(start=False) is False and host.worker.asked == 0
    host.worker.running = True
    assert sampler.ask(start=False) is True and host.worker.asked == 1
    assert sampler.ask() is True and host.worker.asked == 2                   # the picker's open: asked either way
