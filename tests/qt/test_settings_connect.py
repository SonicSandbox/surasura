"""Settings' writing rows of Connect and Anki (W3.3 P8): Connect's switch, the Anki Miner card, *New cards a day*.

What a wrong answer would cost: Connect switched on without its watermarks or with the service's copy stale (cards
made from what was placed while it was off; the page showing Connect's rows for a switch the file says is off); a
switch-off that skips the shelf's question, puts cards back after a No, or saves off after the second No (2.x's order:
a No to "put them back?" still turns Connect off; a No to "off anyway?" keeps it on); a second run started while one
goes; anything painted after the page is gone; a Browse that writes another key, or a star answer in settings.json; a
deck option written without the question naming the deck, after a No, or with `words_per_day` saved for a write Anki
refused. All with fakes: never a real Anki, AnkiConnect, Anki Miner or the network — `_send` is refused outright.
"""
import ast
import json
import os
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import anki_connect, anki_deck_options as ado, settings_manager
from app.connect import anki_miner, settings_values, setup, status
from app.connect import switch as real_switch
from app.qt import confirm, settings_connect as scn, windows
from app.qt import press as qpress
from app.qt import settings_catalog as catalog
from app.qt import settings_page as sp
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_settings_page import EVERYTHING, Recorder

DECK = "日本語::コア2k"
MINER = "C:\\Program Files\\Anki Miner\\AnkiMiner.exe"


def on_gui():
    return threading.current_thread() is threading.main_thread()


class Store(Recorder):
    """The page's recorder with the service's `reload` (the switch's sequence: the file read again on its worker)."""

    def __init__(self, data=None, events=None):
        super().__init__(data)
        self.events = events if events is not None else []

    def reload(self):
        self.events.append(("reload", on_gui(), threading.get_ident(), {}))
        return self.get()

    def fresh(self):
        """The file read now (the switch-on's first look: Connect already on there?)."""
        return scn.settings_service.thaw(self.get())


class Bar:
    def __init__(self):
        self.lines = []
        self.held = {}                                  # round 8 row 45: a live press's words (`say(…, hold=)`)

    def set_full(self, text):
        self.lines.append(text)

    def say(self, text, hold=None):
        """The shell's `say`: the line as said; held for a live press until `unsay`."""
        if hold is not None:
            self.held[hold] = text
        self.lines.append(text)

    def unsay(self, key):
        self.held.pop(key, None)


class FakeSwitch:
    """`app/connect/switch.py`'s five steps, recorded (name, on the GUI thread, the thread, its arguments); a save
    changes the recorder's file as `save_keys` would change settings.json."""
    CONNECT_LANGUAGES = real_switch.CONNECT_LANGUAGES
    PUT_BACK_WAITING = real_switch.PUT_BACK_WAITING

    def __init__(self, store):
        self.store, self.events = store, store.events
        self.on = (True, None)                    # turn_on's (ok, why)
        self.off = (True, None)                   # turn_off's
        self.shelf = {}
        self.not_put_back = []
        self.gate = None                          # an Event turn_on waits for (a run held open)
        self.wait_once = False                    # put_back waits for Anki's lock once

    def _note(self, name, **kw):
        self.events.append((name, on_gui(), threading.get_ident(), kw))

    def turn_on(self, languages, log):
        self._note("turn_on", languages=languages)
        if self.gate is not None:
            assert self.gate.wait(10)
        ok, why = self.on
        if not ok:
            log(real_switch.NOT_ON.format(why))
            return False, None, why
        self.store.file["connect_enabled"] = True
        log(real_switch.ON)
        return True, dict(self.store.file), None

    def backfill(self, languages, saved, log):
        self._note("backfill", saved=saved)

    def shelved(self, languages):
        self._note("shelved")
        return dict(self.shelf)

    def put_back(self, shelved, log, waiting):
        self._note("put_back", shelved=shelved)
        if self.wait_once:
            waiting()
        return list(self.not_put_back)

    def turn_off(self, was_on, log, languages):
        self._note("turn_off", was_on=was_on)
        ok, why = self.off
        if not ok:
            return False, None, why
        self.store.file["connect_enabled"] = False
        log(real_switch.OFF)
        return True, dict(self.store.file), None


class Asked(QObject):
    """A question `confirm.ask` was asked (the fake's card): its words, and `answer(yes)` as the user."""

    def __init__(self, title, body, yes, default_no, on_answer):
        super().__init__()
        self.title, self.body, self.yes, self.default_no, self._on_answer = title, body, yes, default_no, on_answer

    def answer(self, yes):
        callback, self._on_answer = self._on_answer, None
        callback(yes)
        self.deleteLater()


def miner_result(state="missing"):
    """`setup.checks`'s answer for each of the card's three states (its checks as `setup` words them)."""
    if state == "missing":
        return {"checks": [{"id": "anki_miner", "state": "needs-you", "say": "Anki Miner isn't installed."}],
                "anki_miner": {}}
    checks = [{"id": "anki_miner", "state": "ok", "say": "Anki Miner is installed."},
              {"id": "anki_miner_version", "state": "ok", "say": "Anki Miner 3.7.0."}]
    if state == "setup":
        checks.append({"id": "anki_miner_profile", "state": "needs-you",
                       "say": "Anki Miner has no profile named Surasura yet."})
    else:
        checks.append({"id": "anki_miner_profile", "state": "ok", "say": "Mining with the Surasura profile."})
    checks.append({"id": "anki_miner_setup", "state": "ok", "say": "Anki Miner's own setup is done."})
    return {"checks": checks, "anki_miner": {"app": "3.7.0", "path": MINER}}


@pytest.fixture
def world(monkeypatch, tmp_path):
    """The fakes every row reads: Anki Miner's checks, the update notice, Anki's deck option, the browser, the file
    dialog, the question. No request ever leaves (`anki_connect._send` refused); the page never saves itself."""
    def refused(*_a, **_k):
        raise AssertionError("a request to Anki: these tests never talk to a real Anki")
    monkeypatch.setattr(anki_connect, "_send", refused)

    def no_save(*_a, **_k):
        raise AssertionError("settings.json written directly: only the switch (faked here) or the service may")
    monkeypatch.setattr(settings_manager, "save_settings", no_save)
    monkeypatch.setattr(settings_manager, "save_keys", no_save)
    w = SimpleNamespace(miner=miner_result("missing"), update=None, checked=[], reading=ado.Reading(20, DECK, "Default",
                        None), reads=[], writes=[], outcome=None, write_gate=None, opened=[], asked=[], file="",
                        bar=Bar(), events=[])

    def checks(settings, language):
        w.checked.append((on_gui(), dict(settings), language))
        return w.miner
    monkeypatch.setattr(setup, "checks", checks)
    monkeypatch.setattr(status, "anki_miner_update", lambda: w.update)

    def read(settings, deck):
        w.reads.append((on_gui(), deck))
        return w.reading
    monkeypatch.setattr(ado, "read_new_per_day", read)

    def write(settings, deck, value, expect, wait=0.0, cancel=None, on_wait=None):
        w.events.append(("write", on_gui(), threading.get_ident(), {"deck": deck, "value": value, "expect": expect}))
        w.writes.append(dict(on_gui=on_gui(), deck=deck, value=value, expect=expect, wait=wait, cancel=cancel))
        if w.write_gate is not None:
            on_wait({"verb": "Backfill"})
            w.write_gate(cancel)
        return w.outcome or ado.Outcome(True, f"New cards a day for “{deck}” is {value} in Anki now.", value, False)
    monkeypatch.setattr(ado, "write_new_per_day", write)
    monkeypatch.setattr(windows, "open_url", lambda url: w.opened.append(url) or True)
    monkeypatch.setattr(scn, "ask_miner_file", lambda parent: w.file)

    def ask(window, title, body, yes, yes_tip, *, no=None, no_tip=None, default_no=False, danger=False,
            on_answer=None):
        assert yes_tip and (no is None or no_tip), "every button of a question has its tooltip"
        card = Asked(title, body, yes, default_no, on_answer)
        w.asked.append(card)
        return card
    monkeypatch.setattr(confirm, "ask", ask)
    return w


def make(world, data=None, monkeypatch=None):
    """The page with a shell-like owner (its services and its bottom bar), built, and the three rows attached."""
    store = Store(dict({"target_language": "ja", "junban_deck": DECK, "words_per_day": 5}, **(data or {})),
                  events=world.events)
    shell = SimpleNamespace(services=SimpleNamespace(settings=store), bar_line=world.bar, say=world.bar.say,
                            unsay=world.bar.unsay)
    page = sp.SettingsPage(shell, "ja", found=EVERYTHING)
    page.resize(1100, 700)
    page.show()
    assert wait_until(lambda: page.built, 20)
    rows = scn.attach(page)
    fake = FakeSwitch(store)
    if monkeypatch is not None:
        monkeypatch.setattr(scn, "_switch", lambda: fake)
    assert wait_until(lambda: not rows.miner.checking and rows.new_cards.field.isVisibleTo(page), 10)
    return page, store, rows, fake


def gone(obj):
    """`obj` deleted now, as the event loop would delete it."""
    obj.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(obj)


def names(events):
    return [e[0] for e in events]


def settled(rows):
    return wait_until(lambda: not rows.switch.running, 10)


# --- Connect's switch ---------------------------------------------------------------------------------------------- #
def test_switching_on_runs_the_watermarks_then_the_backfill_then_the_reload_on_one_worker(world, monkeypatch):
    """P3.1's sequence: turn_on, then hato's back-fill, then the service reloads the file — every step on the same
    worker, never the GUI thread, and the page writes nothing itself (N11). The toggle is given back and Connect's rows
    show (the write told through the bridge)."""
    page, store, rows, fake = make(world, monkeypatch=monkeypatch)
    assert not page.rows["connect_mine_words"].isVisibleTo(page)
    rows.switch.toggle.changed.emit(True)
    assert settled(rows)
    assert names(world.events) == ["turn_on", "backfill", "reload"]
    assert not any(e[1] for e in world.events), "a switch step ran on the GUI thread"
    assert len({e[2] for e in world.events}) == 1, "the back-fill and the reload run on turn_on's worker"
    assert store.calls == [], "the page wrote a setting itself"
    assert rows.switch.toggle.value() is True and rows.switch.toggle.isEnabled()
    assert page.rows["connect_mine_words"].isVisibleTo(page), "Connect's rows show once it is on"
    assert real_switch.ON in world.bar.lines


def test_a_switch_on_that_fails_goes_back_off_says_why_and_does_nothing_more(world, monkeypatch):
    """No back-fill, no reload, no rows after a failed turn_on; the reason is in the bar."""
    page, store, rows, fake = make(world, monkeypatch=monkeypatch)
    fake.on = (False, "Japanese: the library is busy; try again in a moment")
    rows.switch.toggle.changed.emit(True)
    assert settled(rows)
    assert names(world.events) == ["turn_on"]
    assert rows.switch.toggle.value() is False and rows.switch.toggle.isEnabled()
    assert any("the library is busy" in line for line in world.bar.lines)
    assert world.bar.lines[-1] == S.SWITCH_NOT_ON.format(fake.on[1])
    assert not page.rows["connect_mine_words"].isVisibleTo(page)
    assert store.calls == []


def test_the_toggle_says_turning_on_while_its_run_goes_and_a_second_change_starts_nothing(world, monkeypatch):
    """One run at a time: while turn_on is held, *Turning on…* is held in the bar (round 8 row 45: the toggle never
    greyed); another change meanwhile is put back and runs nothing."""
    page, store, rows, fake = make(world, monkeypatch=monkeypatch)
    fake.gate = threading.Event()
    rows.switch.toggle.changed.emit(True)
    assert world.bar.held == {"settings:connect_switch": S.SWITCH_TURNING_ON}     # in the frame of the change
    assert wait_until(lambda: names(world.events) == ["turn_on"], 5)
    assert rows.switch.toggle.isEnabled() and rows.switch.running and rows.switch.press.live()
    rows.switch.toggle.changed.emit(False)                # a change meanwhile: put back, nothing runs
    QApplication.processEvents()
    assert names(world.events) == ["turn_on"] and rows.switch.toggle.value() is True
    fake.gate.set()
    assert settled(rows)
    assert names(world.events) == ["turn_on", "backfill", "reload"]
    assert rows.switch.toggle.value() is True and rows.switch.toggle.isEnabled()
    assert world.bar.held == {} and rows.switch.press is None


def test_switching_off_with_nothing_on_the_shelf_turns_off_on_the_same_worker_without_asking(world, monkeypatch):
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    assert page.rows["connect_mine_words"].isVisibleTo(page)
    rows.switch.toggle.changed.emit(False)
    assert settled(rows)
    assert names(world.events) == ["shelved", "turn_off", "reload"]
    assert world.events[1][3] == {"was_on": True}
    assert len({e[2] for e in world.events}) == 1 and not any(e[1] for e in world.events)
    assert world.asked == []
    assert rows.switch.toggle.value() is False and rows.switch.toggle.isEnabled()
    assert not page.rows["connect_mine_words"].isVisibleTo(page), "Connect's rows go once it is off"
    assert store.calls == []


def test_a_no_to_putting_the_shelf_back_still_turns_connect_off_and_puts_nothing_back(world, monkeypatch):
    """2.x's order: asked once (its words, the count named, No the default); No → not put back, still saved off."""
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    fake.shelf = {"ja": (3, ["run-2026-10-14"])}
    rows.switch.toggle.changed.emit(False)
    assert wait_until(lambda: world.asked, 5)
    asked = world.asked[0]
    assert asked.title == "Put the 3 shelved cards back into your new cards?"
    assert asked.default_no
    assert names(world.events) == ["shelved"] and rows.switch.running and rows.switch.press is None
    assert world.bar.held == {}                                 # the question is what the change shows now
    asked.answer(False)
    assert world.bar.held == {"settings:connect_switch": S.SWITCH_TURNING_OFF}
    assert settled(rows)
    assert names(world.events) == ["shelved", "turn_off", "reload"]
    assert rows.switch.toggle.value() is False


def test_one_shelved_card_is_named_in_the_singular(world, monkeypatch):
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    fake.shelf = {"zh": (1, ["run-1"])}
    rows.switch.toggle.changed.emit(False)
    assert wait_until(lambda: world.asked, 5)
    assert world.asked[0].title == "Put the 1 shelved card back into your new cards?"


def test_a_yes_puts_the_shelf_back_first_its_waiting_line_in_the_bar_then_turns_off(world, monkeypatch):
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    fake.shelf = {"ja": (3, ["run-a", "run-b"])}
    fake.wait_once = True
    rows.switch.toggle.changed.emit(False)
    assert wait_until(lambda: world.asked, 5)
    world.asked[0].answer(True)
    assert settled(rows)
    assert names(world.events) == ["shelved", "put_back", "turn_off", "reload"]
    assert world.events[1][3]["shelved"] == fake.shelf
    assert not any(e[1] for e in world.events)
    assert real_switch.PUT_BACK_WAITING in world.bar.lines
    assert rows.switch.toggle.value() is False


def test_a_put_back_that_failed_asks_off_anyway_and_no_keeps_connect_on(world, monkeypatch):
    """One restore point not put back: *Turn Connect off anyway?* naming why; No → never saved off, still on."""
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    fake.shelf = {"ja": (2, ["run-a"])}
    fake.not_put_back = ["Not done: Anki is closed."]
    rows.switch.toggle.changed.emit(False)
    assert wait_until(lambda: world.asked, 5)
    world.asked[0].answer(True)
    assert wait_until(lambda: len(world.asked) == 2, 5)
    second = world.asked[1]
    assert second.title == S.OFF_ANYWAY_ASK and "Not done: Anki is closed." in second.body and second.default_no
    assert names(world.events) == ["shelved", "put_back"]
    second.answer(False)
    assert settled(rows)
    assert names(world.events) == ["shelved", "put_back"], "a No to 'off anyway' saved the switch off"
    assert rows.switch.toggle.value() is True and rows.switch.toggle.isEnabled()
    assert world.bar.lines[-1] == S.STAYS_ON
    assert page.rows["connect_mine_words"].isVisibleTo(page)


def test_a_yes_to_off_anyway_turns_connect_off_without_putting_back_again(world, monkeypatch):
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    fake.shelf = {"ja": (2, ["run-a"])}
    fake.not_put_back = ["Not done: Anki is closed."]
    rows.switch.toggle.changed.emit(False)
    assert wait_until(lambda: world.asked, 5)
    world.asked[0].answer(True)
    assert wait_until(lambda: len(world.asked) == 2, 5)
    world.asked[1].answer(True)
    assert settled(rows)
    assert names(world.events) == ["shelved", "put_back", "turn_off", "reload"]
    assert rows.switch.toggle.value() is False


def test_a_switch_off_that_fails_goes_back_on_and_says_why(world, monkeypatch):
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    fake.off = (False, "the switch wasn't saved: settings.json is locked")
    rows.switch.toggle.changed.emit(False)
    assert settled(rows)
    assert names(world.events) == ["shelved", "turn_off"], "nothing after a failed save (no reload)"
    assert rows.switch.toggle.value() is True and rows.switch.toggle.isEnabled()
    assert world.bar.lines[-1] == S.SWITCH_NOT_OFF.format(fake.off[1])


def test_a_question_left_unanswered_as_its_window_goes_does_nothing_more(world, monkeypatch):
    """confirm's rule: a question dropped with its window answers nothing — never saved off, the switch shown as
    saved (on) and given back."""
    page, store, rows, fake = make(world, {"connect_enabled": True}, monkeypatch=monkeypatch)
    fake.shelf = {"ja": (3, ["run-a"])}
    rows.switch.toggle.changed.emit(False)
    assert wait_until(lambda: world.asked, 5)
    gone(world.asked[0])                                  # dropped, never answered
    assert settled(rows)
    assert names(world.events) == ["shelved"]
    assert rows.switch.toggle.value() is True and rows.switch.toggle.isEnabled()


def test_the_page_gone_while_the_switch_runs_never_cuts_the_run_and_paints_nothing(world, monkeypatch, qt_errors):
    page, store, rows, fake = make(world, monkeypatch=monkeypatch)
    fake.gate = threading.Event()
    rows.switch.toggle.changed.emit(True)
    assert wait_until(lambda: names(world.events) == ["turn_on"], 5)
    page.close()
    gone(page)
    fake.gate.set()
    assert wait_until(lambda: names(world.events) == ["turn_on", "backfill", "reload"], 10)
    QApplication.processEvents()
    assert qt_errors == []


def test_a_switch_worker_that_breaks_shows_what_is_saved(world, monkeypatch):
    page, store, rows, fake = make(world, monkeypatch=monkeypatch)

    def broken():
        raise ImportError("app.connect is missing")
    monkeypatch.setattr(scn, "_switch", broken)
    rows.switch.toggle.changed.emit(True)
    assert settled(rows)
    assert rows.switch.toggle.value() is False and rows.switch.toggle.isEnabled()
    assert "app.connect is missing" in world.bar.lines[-1]


def test_another_windows_write_of_the_switch_is_followed(world, monkeypatch):
    page, store, rows, fake = make(world, monkeypatch=monkeypatch)
    store.outside({"connect_enabled": True})
    assert wait_until(lambda: rows.switch.toggle.value() is True, 5)


def test_opening_settings_imports_nothing_of_connect_or_anki_at_the_top_of_the_module():
    """H11's spirit: `settings_connect` imports Connect's switch, its checks and Anki's deck option only inside the
    workers' steps (the one module-level Connect import is the pure `settings_values` the catalog already reads)."""
    tree = ast.parse(open(scn.__file__, encoding="utf-8").read())
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names_ = {(getattr(n, "module", None) or "") + ":" + a.name for n in top for a in n.names}
    assert {m for m in names_ if m.startswith("app.connect")} == {"app.connect:settings_values"}
    assert not any("anki" in m for m in names_)


# --- the Anki Miner card ------------------------------------------------------------------------------------------- #
def test_not_installed_offers_install_with_the_star_line_right_beside_it(world):
    page, store, rows, _fake = make(world)
    card = rows.miner
    assert world.checked and not world.checked[0][0], "setup.checks ran on the GUI thread"
    assert card.words.text() == "Not installed"
    lines = [card.missing.itemAt(i).widget().text() for i in range(card.missing.count())]
    assert lines == ["Anki Miner isn't installed."]
    shown = [b for b in (card.install, card.star_line, card.browse, card.open_miner, card.check_again)
             if b.isVisibleTo(page)]
    assert shown == [card.install, card.star_line, card.browse, card.check_again]
    # the star line comes right after Install: beside it when both fit the card, else first on the next line (the
    # buttons wrap inside the card, never cut: the wizard-text fix)
    install, star = card.install.geometry(), card.star_line.geometry()
    if card.install.sizeHint().width() + card.star_line.sizeHint().width() + 30 <= card.width():
        assert abs(install.right() - star.left()) < 30, "the star line beside Install"
    else:
        assert star.left() == install.left() and star.top() > install.top(), "the star line under Install"
    assert star.right() < card.width() and install.right() < card.width()
    assert S.STAR_LINE.endswith("★") and not card.star_box.isVisibleTo(page) and not card.star_link.isVisibleTo(page)


def test_install_opens_anki_miners_releases_page_and_the_star_line_its_github_page(world):
    page, store, rows, _fake = make(world)
    QTest.mouseClick(rows.miner.install, Qt.MouseButton.LeftButton)
    assert world.opened == [setup.RELEASES]
    QTest.mouseClick(rows.miner.star_line, Qt.MouseButton.LeftButton)
    assert world.opened[-1] == settings_values.STAR_URL
    assert wait_until(settings_values.star_answered, 5), "a star click is kept as answered"
    assert store.calls == []


def test_needs_setup_names_the_missing_piece_and_the_two_steps_with_copy_path(world):
    world.miner = miner_result("setup")
    page, store, rows, _fake = make(world)
    card = rows.miner
    assert card.words.text() == "Installed 3.7.0 — needs setup"
    assert [card.missing.itemAt(i).widget().text() for i in range(card.missing.count())] == [
        "Anki Miner has no profile named Surasura yet."]
    assert card.steps.isVisibleTo(page)
    assert card.path_field.text() == anki_miner.whitelist_path("ja") and card.path_field.isReadOnly()
    QTest.mouseClick(card.copy, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == anki_miner.whitelist_path("ja")
    assert world.bar.lines[-1] == S.PATH_COPIED
    assert card.open_miner.isVisibleTo(page) and not card.install.isVisibleTo(page)
    assert not card.star_line.isVisibleTo(page)


def test_ready_offers_the_star_until_not_now_which_is_kept_in_local_data_never_settings(world):
    """U6: installed and not yet answered, the bigger suggestion; *Not now* writes star.json under the test root (the
    local data folder) and never settings.json; the small link stays, and a check again doesn't bring it back."""
    world.miner = miner_result("ready")
    page, store, rows, _fake = make(world)
    card = rows.miner
    assert card.words.text() == "Ready — Anki Miner 3.7.0"
    assert card.star_box.isVisibleTo(page) and not card.star_link.isVisibleTo(page)
    QTest.mouseClick(card.not_now, Qt.MouseButton.LeftButton)
    assert not card.star_box.isVisibleTo(page) and card.star_link.isVisibleTo(page)
    path = settings_values.star_path()
    assert wait_until(lambda: os.path.exists(path), 5)
    assert path.startswith(os.environ["SURASURA_TEST_ROOT"])
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["answer"] == "not-now"
    assert store.calls == [] and "star" not in json.dumps(store.file)
    QTest.mouseClick(card.check_again, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: not card.checking and len(world.checked) == 2, 5)
    assert not card.star_box.isVisibleTo(page) and card.star_link.isVisibleTo(page)
    QTest.mouseClick(card.open_miner, Qt.MouseButton.LeftButton)
    assert world.opened[-1] == MINER


def test_browse_writes_only_the_programs_path_through_the_service_and_checks_again(world):
    page, store, rows, _fake = make(world)
    world.file = "C:/Program Files/Anki Miner/AnkiMiner.exe"
    QTest.mouseClick(rows.miner.browse, Qt.MouseButton.LeftButton)
    assert store.calls == [({"connect_anki_miner_path": os.path.normpath(world.file)}, None)]
    assert wait_until(lambda: len(world.checked) == 2 and not rows.miner.checking, 5)
    assert world.checked[1][1]["connect_anki_miner_path"] == os.path.normpath(world.file)


def test_a_browse_while_a_check_runs_checks_once_more_with_the_new_path(world, monkeypatch):
    # The first check is still running when the user picks the program: the card must not end on the old path's state.
    page, store, rows, _fake = make(world)
    assert wait_until(lambda: not rows.miner.checking, 5)
    gate = threading.Event()
    seen = []

    def slow(settings, language):
        seen.append(settings.get("connect_anki_miner_path"))
        if len(seen) == 1:
            gate.wait(5)
        return world.miner
    monkeypatch.setattr(setup, "checks", slow)
    rows.miner.check()
    assert wait_until(lambda: seen, 5)
    world.file = "C:/Program Files/Anki Miner/AnkiMiner.exe"
    QTest.mouseClick(rows.miner.browse, Qt.MouseButton.LeftButton)
    gate.set()
    assert wait_until(lambda: len(seen) == 2 and not rows.miner.checking, 5)
    assert seen[1] == os.path.normpath(world.file)


def test_browse_cancelled_writes_nothing(world):
    page, store, rows, _fake = make(world)
    world.file = ""
    QTest.mouseClick(rows.miner.browse, Qt.MouseButton.LeftButton)
    assert store.calls == [] and len(world.checked) == 1


def test_the_anki_miner_is_out_notice_shows_while_the_status_names_one(world):
    world.miner = miner_result("ready")
    world.update = {"version": "3.8.0", "url": "https://github.com/0xzerolight/anki_miner/releases/tag/v3.8.0"}
    page, store, rows, _fake = make(world)
    note = rows.miner.update_note
    assert note.isVisibleTo(page) and note.text() == "Anki Miner 3.8.0 is out"
    QTest.mouseClick(note, Qt.MouseButton.LeftButton)
    assert world.opened == [world.update["url"]]
    world.update = None
    rows.miner.check()
    assert wait_until(lambda: not rows.miner.checking, 5)
    assert not note.isVisibleTo(page)


def test_a_check_that_fails_says_so_and_still_offers_install(world, monkeypatch):
    def broken(settings, language):
        raise OSError("Anki Miner's --api didn't answer")
    monkeypatch.setattr(setup, "checks", broken)
    page, store, rows, _fake = make(world)
    assert rows.miner.words.text() == S.MINER_NOT_CHECKED.format("Anki Miner's --api didn't answer")
    assert rows.miner.install.isVisibleTo(page) and rows.miner.check_again.isEnabled()


def test_every_button_of_the_three_rows_has_a_tooltip(world):
    world.miner = miner_result("setup")
    page, store, rows, _fake = make(world)
    from PyQt6.QtWidgets import QAbstractButton
    buttons = [b for w in (rows.switch, rows.miner, rows.new_cards) for b in w.findChildren(QAbstractButton)]
    assert buttons and all(b.toolTip() for b in buttons)
    assert rows.switch.toggle.toolTip()


# --- New cards a day ----------------------------------------------------------------------------------------------- #
def test_ankis_number_is_read_on_a_worker_and_shown_with_its_deck(world):
    page, store, rows, _fake = make(world)
    row = rows.new_cards
    assert world.reads == [(False, DECK)]
    assert row.field.value() == 20 and row.field.isEnabled()
    assert DECK in row.words.text() and row.change.isVisibleTo(page)
    assert DECK in page.row("new_cards_a_day").help.text()
    assert store.calls == [], "a read wrote a setting"


def test_change_asks_naming_the_deck_and_a_no_writes_nothing(world):
    page, store, rows, _fake = make(world)
    row = rows.new_cards
    row.field.set_value(30)
    QTest.mouseClick(row.change, Qt.MouseButton.LeftButton)
    assert len(world.asked) == 1
    asked = world.asked[0]
    assert DECK in asked.body and asked.default_no and "30" in asked.yes
    asked.answer(False)
    QApplication.processEvents()
    assert world.writes == [] and store.calls == []
    assert row.field.value() == 20


def test_a_typed_number_counts_when_change_is_clicked_without_enter(world):
    page, store, rows, _fake = make(world)
    row = rows.new_cards
    page.activateWindow()
    row.field.edit.setFocus()
    assert wait_until(row.field.edit.hasFocus, 2)
    row.field.edit.selectAll()
    QTest.keyClicks(row.field.edit, "35")
    QTest.mouseClick(row.change, Qt.MouseButton.LeftButton)
    assert world.asked and "35" in world.asked[0].yes


def test_a_yes_writes_in_anki_on_a_worker_then_saves_the_pace_through_the_service(world):
    page, store, rows, _fake = make(world)
    row = rows.new_cards
    row.field.set_value(30)
    QTest.mouseClick(row.change, Qt.MouseButton.LeftButton)
    world.asked[0].answer(True)
    assert wait_until(lambda: not row.busy and store.calls, 5)
    w = world.writes[0]
    assert (w["on_gui"], w["deck"], w["value"], w["expect"], w["wait"]) == (False, DECK, 30, 20, None)
    assert w["cancel"] is rows.cancel
    assert store.calls == [({"words_per_day": 30}, None)]
    assert world.bar.lines[-1] == f"New cards a day for “{DECK}” is 30 in Anki now."
    assert row.reading.value == 30 and row.field.value() == 30


def test_a_write_anki_refused_because_the_value_moved_is_said_and_saves_nothing(world):
    page, store, rows, _fake = make(world)
    row = rows.new_cards
    world.outcome = ado.Outcome(False, "Anki's New cards a day changed to 25 meanwhile. Nothing was written.", 25, False)
    row.field.set_value(30)
    QTest.mouseClick(row.change, Qt.MouseButton.LeftButton)
    world.asked[0].answer(True)
    assert wait_until(lambda: world.writes and not row.busy, 5)
    QApplication.processEvents()
    assert store.calls == []
    assert world.bar.lines[-1] == world.outcome.message
    assert row.field.value() == 25 and row.reading.value == 25, "the number Anki holds now"


def test_a_number_anki_took_while_other_options_moved_is_said_and_the_pace_follows_it(world):
    # Anki holds the confirmed 30 but the read-back saw another option of the group move: the warning is said, and the
    # report's pace follows the number the row now shows (what the deck gives each day).
    page, store, rows, _fake = make(world)
    row = rows.new_cards
    world.outcome = ado.Outcome(False, "Anki took 30 New cards a day, but other options came back different: "
                                       "new.delays. Check the options group in Anki.", 30, False, True)
    row.field.set_value(30)
    QTest.mouseClick(row.change, Qt.MouseButton.LeftButton)
    world.asked[0].answer(True)
    assert wait_until(lambda: not row.busy and store.calls, 5)
    assert store.calls == [({"words_per_day": 30}, None)]
    assert world.bar.lines[-1] == world.outcome.message
    assert row.field.value() == 30


def test_a_confirmed_number_equal_to_the_saved_pace_saves_nothing(world):
    # Anki read 20, the pace already 5: a confirmed 5 changes Anki only — `words_per_day_after` finds the pace already
    # there, so nothing is written to settings.json (S19)
    page, store, rows, _fake = make(world)
    row = rows.new_cards
    row.field.set_value(5)
    QTest.mouseClick(row.change, Qt.MouseButton.LeftButton)
    world.asked[0].answer(True)
    assert wait_until(lambda: world.writes and not row.busy, 5)
    QApplication.processEvents()
    assert world.writes[0]["value"] == 5
    assert store.calls == []
    assert row.field.value() == 5


def test_a_switch_that_was_off_turns_off_without_reading_the_shelf(world, monkeypatch):
    # cards still on the shelf from an earlier run: an off switch saved off again asks nothing and puts nothing back
    store = Store({"target_language": "ja"}, events=world.events)
    fake = FakeSwitch(store)
    fake.shelf = {"ja": (3, ["run-2026-10-14"])}
    monkeypatch.setattr(scn, "_switch", lambda: fake)
    assert scn._switch_off_start(False, store, lambda line: None) == ("off", True, None)
    assert names(world.events) == ["turn_off", "reload"]
    assert world.events[0][3] == {"was_on": False}


def test_the_same_number_asks_nothing_and_writes_nothing(world):
    page, store, rows, _fake = make(world)
    QTest.mouseClick(rows.new_cards.change, Qt.MouseButton.LeftButton)
    assert world.asked == [] and world.writes == []
    assert world.bar.lines[-1] == S.NEW_CARDS_SAME.format(deck=DECK, n=20)


def test_waiting_for_the_anki_lock_shows_its_line_and_the_page_going_cancels_the_wait(world, qt_errors):
    page, store, rows, _fake = make(world)
    row = rows.new_cards
    released = threading.Event()

    def held(cancel):
        assert cancel.wait(10), "the page went but the wait wasn't cancelled"
        released.set()
    world.write_gate = held
    world.outcome = ado.Outcome(False, "Stopped before writing anything.", None, True)
    row.field.set_value(30)
    QTest.mouseClick(row.change, Qt.MouseButton.LeftButton)
    world.asked[0].answer(True)
    # round 8 row 45: the button keeps its words and look (its arc turns); the wait's line is held in the bar
    line = anki_connect.waiting_line({"verb": "Backfill"})
    assert wait_until(lambda: world.bar.held == {"settings:new_cards": line}, 5)
    assert row.press.state == "waiting" and qpress.arc(row.change) is not None
    assert row.change.text() == S.CHANGE_IN_ANKI and row.change.isEnabled() and not row.field.isEnabled()
    page.close()
    gone(page)
    assert released.wait(5)
    QApplication.processEvents()
    assert store.calls == [] and qt_errors == []


def test_anki_unreadable_shows_the_pace_as_an_editable_number_with_why_on_hover(world):
    world.reading = "Anki isn't open, or AnkiConnect isn't installed."
    page, store, rows, _fake = make(world, {"words_per_day": 12})
    row = rows.new_cards
    assert row.field.value() == 12 and row.field.isEnabled()
    assert world.reading in row.field.toolTip()
    assert not row.change.isVisibleTo(page) and not row.words.isVisibleTo(page)
    row.field.set_value(15)
    row.field.changed.emit(15)
    assert store.calls == [({"words_per_day": 15}, None)]
    assert world.writes == []


def test_a_read_that_breaks_shows_the_saved_pace_never_zero(world, monkeypatch):
    # The read itself raises (not Anki's own "unreadable" answer): the field still shows the pace as saved, so an
    # Enter on it can never write 0 over the user's 12.
    def broke(settings, deck):
        raise RuntimeError("AnkiConnect answered something unexpected")
    monkeypatch.setattr(ado, "read_new_per_day", broke)
    page, store, rows, _fake = make(world, {"words_per_day": 12})
    row = rows.new_cards
    assert wait_until(lambda: row.unread and row.field.isEnabled(), 5)
    assert row.field.value() == 12
    assert store.calls == []


def test_a_change_of_junbans_deck_reads_anki_again(world):
    page, store, rows, _fake = make(world)
    store.outside({"junban_deck": "中文::HSK"})
    assert wait_until(lambda: len(world.reads) == 2 and world.reads[1][1] == "中文::HSK", 5)


def test_a_number_typed_while_anki_is_read_writes_nothing_until_change(world):
    """Anki's number is held in the field until *Change in Anki…* and a yes: never `words_per_day` on a commit."""
    page, store, rows, _fake = make(world)
    rows.new_cards.field.set_value(30)
    rows.new_cards.field.changed.emit(30)
    QApplication.processEvents()
    assert store.calls == [] and world.writes == [] and world.asked == []


def test_a_language_switch_checks_anki_miner_again_for_that_language(world):
    page, store, rows, _fake = make(world)
    if not hasattr(page, "language_set"):
        pytest.skip("the page's language_set signal (P4) isn't here")
    page.set_language("zh")
    assert wait_until(lambda: len(world.checked) == 2 and not rows.miner.checking, 5)
    assert world.checked[1][2] == "zh"


# --- row 13 (laptop fixes): the card's check opens *Make cards for me* ------------------------------------------- #
@pytest.mark.parametrize("state", ["missing", "setup", "ready"])
def test_the_anki_miner_cards_check_opens_the_switch_only_once_anki_miner_is_installed(world, state):
    """Row 13: the page's look found no Anki Miner, so *Make cards for me* waits as one line. The card's own check
    (`setup.checks`, stood in for) then finds it installed — needing setup or ready — and the switch shows in the line's
    place; still missing, the line stays. Nothing is saved by it (the page's store records no write)."""
    world.miner = miner_result(state)
    store = Store({"target_language": "ja", "junban_deck": DECK, "words_per_day": 5}, events=world.events)
    shell = SimpleNamespace(services=SimpleNamespace(settings=store), bar_line=world.bar)
    page = sp.SettingsPage(shell, "ja", found=EVERYTHING - {"miner_found"})
    page.resize(1100, 700)
    page.show()
    assert wait_until(lambda: page.built, 20)
    rows = scn.attach(page)
    assert wait_until(lambda: world.checked and not rows.miner.checking, 10)
    QApplication.processEvents()
    shows = lambda row_id: catalog.visible(catalog.ROW[row_id], page._settings(), "ja", page._ctx())  # noqa: E731
    assert shows("connect_enabled") is (state != "missing")
    assert shows("connect_needs_miner") is (state == "missing")
    assert store.calls == [], "the gate saved something"
