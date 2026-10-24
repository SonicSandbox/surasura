"""Settings' live rows (W3.3 P4; `app/qt/settings_live.py`; the RUNBOOK's P4 row, the register's S2, S4, S6, N6).

What a wrong answer would cost: a read on the window's thread (a file, SQLite, Anki: the window freezes); a number in
Your setup that isn't true (a count from another language, a band from a stale read); the level written while only
*Automatic* moved it (a full Generate for nothing, S2); a readout that says *% known* (S4); a *Check* that refreshes
nothing; an *Offer again* for a version that is no newer; a credits card that traps the window (modal) or won't close
on Esc / Back / a click outside (N6); a text size written twice or never applied; an export that runs twice at once,
writes without a destination, or fails without saying why.

Every read is a fake (`Fakes`) that records the thread it ran on; the settings service is P3's `Recorder`.
"""
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import exports
from app.qt import motion, strings, style, windows
from app.qt import press as qpress
from app.qt import settings_controls as sc
from app.qt import settings_live as live
from app.qt import settings_page as sp
from app.qt import settings_strings as S
from app.services import automation as automation_module
from app.services import updates as updates_module
from tests.qt.conftest import wait_until
from tests.qt.test_settings_page import ALL_ON, EVERYTHING, Recorder, _no_direct_save  # noqa: F401 (the autouse guard)

PREVIEWS = {
    "common": {"word_count": 1234, "coverage_percent": 91.26, "hours_between": 3.44},
    "rare": {"word_count": 850, "coverage_percent": 96.04, "hours_between": 0.4},
    "native": {"word_count": 40, "coverage_percent": 99.1, "hours_between": None},
}


class Fakes:
    """Every read `settings_live` makes, faked: each call kept with whether it ran on the GUI thread."""

    def __init__(self, monkeypatch):
        self.calls = []
        self.known = (2468, None)
        self.level = ("common", False, PREVIEWS)
        self.hato = "1.0.9"
        self.licence = "MIT License · Copyright (c) 2026 SonicSandbox"
        self.credits = ("Data credits — what Surasura ships or is built from\nJMdict (EDRDG) · CC BY-SA 4.0", [],
                        self.licence)
        self.probe = {"ok": True, "version": 6, "missing": [], "error": ""}
        self.ready = None
        self.outcome = exports.Outcome("done", "D:\\out.json", 12, "List generated successfully!\n\nSaved to: D:\\out.json")
        self.export_gate = None                      # an Event the export waits on (a running export, held)
        self.logs = "C:\\logs"
        self.data = "C:\\data\\ja"
        for name in ("read_known", "read_level", "read_hato", "read_licence", "read_credits", "probe_anki",
                     "read_skipped", "read_status", "logs_folder", "data_folder", "ready_to_export", "run_export"):
            monkeypatch.setattr(live, name, self._fake(name))

    def _fake(self, name):
        def fake(*args):
            self.calls.append((name, threading.current_thread() is threading.main_thread(), args))
            if name == "read_known":
                if isinstance(self.known, Exception):
                    raise self.known
                return self.known
            if name == "read_level":
                return self.level
            if name == "read_hato":
                return self.hato
            if name == "read_licence":
                return self.licence
            if name == "read_credits":
                return self.credits
            if name == "probe_anki":
                return self.probe
            if name == "read_skipped":
                return args[0].skipped()
            if name == "read_status":
                return args[0].snapshot()
            if name == "logs_folder":
                return self.logs
            if name == "data_folder":
                return self.data
            if name == "ready_to_export":
                return self.ready
            if name == "run_export":
                if self.export_gate is not None:
                    self.export_gate.wait(5)
                if isinstance(self.outcome, Exception):
                    raise self.outcome
                return self.outcome
        fake.__name__ = name
        return fake

    def names(self):
        return [name for name, _gui, _args in self.calls]

    def on_gui(self):
        return [name for name, gui, _args in self.calls if gui]


@pytest.fixture
def fakes(monkeypatch):
    return Fakes(monkeypatch)


class Bar:
    def __init__(self):
        self.lines = []

    def set_full(self, text):
        self.lines.append(text)


class Status:
    def __init__(self, connect=None):
        self.refreshes = 0
        self.connect = connect

    def snapshot(self):
        return SimpleNamespace(connect=self.connect)

    def refresh_soon(self, *names):
        self.refreshes += 1


class Updates:
    """The update service's `skipped` (its own rule, run on this stand-in) and `offer_again`, recorded."""

    def __init__(self, store):
        self.settings = store
        self.offered = []

    def skipped(self):
        return updates_module.UpdateService.skipped(self)

    def offer_again(self):
        self.offered.append(threading.current_thread() is threading.main_thread())


class Shell:
    """The shell's parts the page reaches: its services, the bottom bar, and (when given) its text-size method."""

    def __init__(self, services, text_size=True):
        self.services = services
        self.bar_line = Bar()
        self.sizes = []
        if text_size:
            self.set_text_size = self.sizes.append

    def say(self, text, hold=None):
        """The shell's line, held for a live press (round 8 row 45: an export's *Exporting …*) — kept as said."""
        self.bar_line.set_full(text)

    def unsay(self, key):
        pass


def make(fakes, data=None, language="ja", connect=None, text_size=True, skipped=None, size=(1100, 700)):
    store = Recorder(dict({"target_language": language}, **(data or {})))
    if skipped is not None:
        store.file["skipped_version"] = skipped
    services = SimpleNamespace(settings=store, status=Status(connect), automation=None)
    services.updates = Updates(store)
    shell = Shell(services, text_size)
    page = sp.SettingsPage(shell, language, found=EVERYTHING)
    page.resize(*size)
    page.show()
    assert wait_until(lambda: page.built, 20)
    assert wait_until(lambda: {"read_known", "read_level", "read_hato", "read_licence"} <= set(fakes.names()), 5)
    QApplication.processEvents()
    return page, store, shell


def help_of(page, row_id):
    return page.row(row_id).help.text()


def settle(predicate=lambda: False, timeout=0.3):
    wait_until(predicate, timeout)


# --- the workers ------------------------------------------------------------------------------------------------- #
def test_every_read_runs_on_a_worker_never_the_window_thread(qapp, fakes, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("D:\\out.json", "")))
    monkeypatch.setattr(windows, "open_url", lambda url: True)
    monkeypatch.setattr(qpress, "open_now", lambda target: None)     # a folder opens through the press's opener
    page, store, shell = make(fakes, dict(ALL_ON), skipped="99.0.0")
    page.live.check()
    page.live.open_credits()
    page.live.open_logs()
    page.live.open_data_folder()
    page.live.offer_again()
    assert wait_until(lambda: {"probe_anki", "read_credits", "logs_folder", "data_folder"} <= set(fakes.names()))
    page.live.export("export_frequency_list")
    assert wait_until(lambda: page.live.pop is not None)
    page.live.pop.pick()
    assert wait_until(lambda: "run_export" in fakes.names())
    assert wait_until(lambda: shell.services.updates.offered)
    assert fakes.on_gui() == [] and shell.services.updates.offered == [False]
    assert {"read_known", "read_level", "read_hato", "read_licence", "read_skipped", "read_status", "probe_anki",
            "read_credits", "logs_folder", "data_folder", "ready_to_export", "run_export"} <= set(fakes.names())
    assert store.calls == []                              # nothing written by a read, a look or an export


# --- Your setup -------------------------------------------------------------------------------------------------- #
SEEDED = dict(ALL_ON, connect_mine_words="i1", junban_order="content", junban_backfill_fills=["patterns", "sentence"],
              junban_auto_backfill=True, anki_sync_decks={"ja": ["日本語::コア2k", "アニメ"], "zh": ["中文::HSK"]},
              logic={"selection": {"band": "common"}})


def test_your_setup_says_what_the_settings_and_the_reads_say(qapp, fakes):
    fakes.known = (2468, "synced")
    page, store, shell = make(fakes, SEEDED, connect="Mining 3 words from ひとり・で・ぽっぷ！")
    assert wait_until(lambda: help_of(page, "setup_mining").endswith("ひとり・で・ぽっぷ！"))
    assert help_of(page, "setup_known") == "2,468 known · from Anki (日本語::コア2k, アニメ)"
    assert help_of(page, "setup_anki") == "connected"
    assert help_of(page, "setup_mining") == "Only i+1 · Mining 3 words from ひとり・で・ぽっぷ！"
    assert help_of(page, "setup_level") == "Common · ≈1,234 words · 91.3% of your content"
    assert help_of(page, "setup_cards") == "ordered as you’ll meet them · パターン + 例文 filled automatically"
    # each Change › goes to its section
    revealed = []
    page.reveal = revealed.append
    for row_id in live.SETUP:
        page.live.parts[row_id]["change"].click()
    assert revealed == ["known", "anki", "anki", "level", "junban"]


def test_your_setup_says_less_when_a_fact_cant_be_read(qapp, fakes):
    fakes.known = OSError("KnownWord.json is locked")
    fakes.level = (None, True, None)                      # Automatic, and no store to read yet
    page, store, shell = make(fakes, dict(SEEDED, logic={"selection": {"auto": True, "band": "rare"}},
                                          connect_enabled=False, enable_junban=False))
    settle()
    assert help_of(page, "setup_known") == "from Anki (日本語::コア2k, アニメ)"   # no number: never a wrong one
    assert help_of(page, "setup_anki") == ""                                  # not looked at yet: nothing said
    assert help_of(page, "setup_mining") == S.SETUP_CONNECT_OFF
    assert help_of(page, "setup_level") == "Automatic"                       # not the saved band: Automatic moves it
    assert help_of(page, "setup_cards") == S.SETUP_NOT_ORDERED
    assert help_of(page, "level") == ""                                       # no readout: the band names only


def test_setup_lines_count_only_this_languages_words_and_leave_out_unread_parts():
    settings = {"anki_sync_decks": {"zh": ["中文::HSK"]}, "connect_enabled": True}
    lines = live.setup_lines(settings, "ja", {"known": None})
    assert lines["setup_known"] == "" and lines["setup_anki"] == ""
    assert lines["setup_mining"] == "Your list"
    lines = live.setup_lines(settings, "ja", {"known": 30})
    assert lines["setup_known"] == "30 known · from an imported list"
    assert live.setup_lines(settings, "zh", {"known": 0})["setup_known"] == "0 known · from Anki (中文::HSK)"


def test_a_count_for_another_language_never_shows(qapp, fakes):
    page, store, shell = make(fakes, SEEDED)
    state = automation_module.State("synced", "zh", 0, 999, None, None, 1)
    page.bridge.automation_changed.emit(state)
    settle()
    assert help_of(page, "setup_known").startswith("2,468 known")
    page.bridge.automation_changed.emit(state._replace(language="ja", known=2500, seq=2))
    assert wait_until(lambda: help_of(page, "setup_known").startswith("2,500 known"))


# --- the level (S2, S4) ------------------------------------------------------------------------------------------ #
def test_automatic_shows_the_levels_band_and_writes_nothing(qapp, fakes):
    fakes.level = ("rare", True, PREVIEWS)
    page, store, shell = make(fakes, {"logic": {"selection": {"auto": True, "band": "common"}}})
    slider = page.row("level").controls[0]
    assert wait_until(lambda: slider.value() == "rare")
    assert store.calls == []
    assert help_of(page, "level") == "≈850 words · 96.0% of your content · about every 24 minutes"
    assert help_of(page, "setup_level") == "Automatic · Rare · ≈850 words · 96.0% of your content"
    # another level key written: the page puts the saved band back, the automatic one is shown again at once
    store.outside({"logic.selection.auto_max_words": 900})
    assert slider.value() == "rare" and store.calls == []


def test_a_hand_pick_writes_the_band_and_automatic_off_in_one_set(qapp, fakes):
    fakes.level = ("rare", True, PREVIEWS)
    page, store, shell = make(fakes, {"logic": {"selection": {"auto": True, "band": "common"}}})
    slider = page.row("level").controls[0]
    assert wait_until(lambda: slider.value() == "rare")
    slider.changed.emit("native")
    assert store.calls == [({"logic.selection.band": "native", "logic.selection.auto": False}, None)]
    fakes.level = ("native", False, PREVIEWS)
    store.land()
    assert wait_until(lambda: help_of(page, "level") == "≈40 words · 99.1% of your content")
    assert slider.value() == "native"


def test_turning_automatic_off_keeps_the_band_it_was_showing(qapp, fakes):
    # W3.1b B1 (2.x's D3): Automatic showed Rare over a written Common; switched off, Rare becomes the hand pick in the
    # same write — the list doesn't change the moment it goes off
    fakes.level = ("rare", True, PREVIEWS)
    page, store, shell = make(fakes, {"logic": {"selection": {"auto": True, "band": "common"}}})
    slider, auto = page.row("level").controls[:2]
    assert wait_until(lambda: slider.value() == "rare")
    auto.changed.emit(False)
    assert store.calls == [({"logic.selection.auto": False, "logic.selection.band": "rare"}, None)]


def test_the_readout_says_of_your_content_never_known():
    assert live.readout(PREVIEWS["common"]) == "≈1,234 words · 91.3% of your content · about every 3.4 hours"
    assert live.readout(dict(PREVIEWS["common"], hours_between=26.6)).endswith("about every 27 hours")
    assert live.readout(dict(PREVIEWS["common"], hours_between=2.0)).endswith("about every 2 hours")
    assert live.readout(PREVIEWS["rare"]).endswith("about every 24 minutes")
    assert live.readout(None) == ""
    for text in (S.READOUT_HOURS, S.READOUT_MINUTES, S.READOUT_NO_TIME, S.SETUP_COVERAGE):
        assert "of your content" in text and "known" not in text


def test_the_readout_is_read_again_when_a_level_key_or_the_library_changes(qapp, fakes):
    page, store, shell = make(fakes)
    reads = lambda: fakes.names().count("read_level")      # noqa: E731
    assert wait_until(lambda: reads() == 1)
    store.outside({"logic.selection.min_count": 3})
    assert wait_until(lambda: reads() == 2)
    store.outside({"telemetry_enabled": False})              # not a level key: no read
    settle()
    assert reads() == 2
    page.bridge.library_changed.emit(object())
    assert wait_until(lambda: reads() == 3)
    page.bridge.indexed.emit("ja")
    assert wait_until(lambda: reads() == 4)


# --- Connection (S6), the Connections rows ------------------------------------------------------------------------ #
def test_check_refreshes_the_status_and_shows_ankis_word_beside_the_emerald(qapp, fakes):
    page, store, shell = make(fakes)
    mark = page.live.parts["anki_connection"]["mark"]
    assert not mark.value() and mark.words() == S.ANKI_WORDS["unknown"]
    fakes.probe = {"ok": False, "version": None, "missing": [], "error": "Anki is not running"}
    page.live.parts["anki_connection"]["check"].click()
    assert shell.services.status.refreshes == 1
    assert wait_until(lambda: mark.words() == S.ANKI_WORDS["closed"]) and not mark.value()
    assert help_of(page, "setup_anki") == "Anki is closed"
    fakes.probe = {"ok": True, "version": 6, "missing": [], "error": ""}
    page.live.check()
    assert wait_until(lambda: mark.value()) and mark.words() == "connected"
    # the automation's newer sync wins over the last look
    page.bridge.automation_changed.emit(automation_module.State("anki-closed", "ja", 0, None, "Anki is closed", None, 3))
    assert wait_until(lambda: not mark.value()) and mark.words() == S.ANKI_WORDS["closed"]


def test_ankis_words_from_a_look():
    assert live.connection({"ok": False, "timed_out": True}) == (False, "busy")
    assert live.connection({"ok": False, "version": 6, "error": "Anki did not grant access"}) == (False, "denied")
    assert live.connection(None, "synced") == (True, "connected")
    assert live.connection(None, "idle") == (False, "unknown")


def test_connections_say_hato_installed_and_the_rest_coming_without_buttons(qapp, fakes):
    page, store, shell = make(fakes)
    hato = page.live.parts["hato"]["mark"]
    assert wait_until(lambda: hato.words() == "installed · 1.0.9") and hato.value()
    assert page.live.parts["jimaku"]["hint"].text() == S.COMING_WITH_HATO
    assert page.live.parts["anilist"]["hint"].text() == S.COMING_LATER
    assert page.live.parts["more_from_houseki"]["hint"].text() == S.COMING_LATER
    for row_id in ("hato", "jimaku", "anilist", "more_from_houseki"):
        assert page.custom_row(row_id).findChildren(sc.Door) == []
    fakes.hato = None
    page2, _store, _shell = make(fakes)
    assert wait_until(lambda: page2.live.parts["hato"]["mark"].words() == S.NOT_INSTALLED)
    assert not page2.live.parts["hato"]["mark"].value()


# --- App: the update offer, the folders, the version ---------------------------------------------------------------- #
def test_offer_again_shows_only_for_a_newer_skipped_version_and_calls_offer_again(qapp, fakes):
    page, store, shell = make(fakes, skipped="99.0.0")
    offer = page.live.parts["auto_update_enabled"]["offer"]
    assert wait_until(lambda: offer.isVisibleTo(page))
    assert offer.text() == "Offer 99.0.0 again"
    offer.click()
    assert wait_until(lambda: shell.services.updates.offered == [False])
    assert not offer.isVisibleTo(page)
    for old in ("0.1.0", ""):
        other, _store, _shell = make(fakes, skipped=old)
        settle()
        assert not other.live.parts["auto_update_enabled"]["offer"].isVisibleTo(other), old


def test_logs_and_the_data_folder_open_their_folders(qapp, fakes, monkeypatch):
    opened, threads = [], []

    def open_now(target):                                   # round 8 row 45: the press's one opener, on a worker
        threads.append(threading.current_thread() is threading.main_thread())
        opened.append(target)
    monkeypatch.setattr(qpress, "open_now", open_now)
    page, store, shell = make(fakes)
    page.live.parts["logs"]["open"].click()
    assert wait_until(lambda: opened == ["C:\\logs"])
    page.live.parts["version"]["open"].click()
    assert wait_until(lambda: opened == ["C:\\logs", "C:\\data\\ja"])
    assert threads == [False, False]                        # never the window's thread
    from app import __version__
    assert page.row("version").label.text() == f"Version {__version__}"


# --- Data credits (N6) --------------------------------------------------------------------------------------------- #
def test_the_credits_card_holds_the_credits_and_the_licence_and_closes_on_esc_back_and_outside(qapp, fakes):
    page, store, shell = make(fakes)
    licence = page.live.parts["data_credits"]["licence"]
    assert wait_until(lambda: licence.text() == fakes.licence) and licence.isVisibleTo(page)

    def opened():
        page.live.parts["data_credits"]["open"].click()
        assert wait_until(lambda: page.live.card is not None and page.live.card.isVisible())
        return page.live.card

    card = opened()
    assert "JMdict (EDRDG)" in card.text.toPlainText() and card.text.isReadOnly()
    assert card.licence.text() == fakes.licence
    assert page.isEnabled() and not QApplication.activeModalWidget()        # never modal
    QTest.keyClick(card, Qt.Key.Key_Escape)
    assert wait_until(lambda: page.live.card is None)
    card = opened()
    QTest.mouseClick(card.room, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(3, 3))
    assert wait_until(lambda: page.live.card is None)                       # a click outside
    card = opened()
    QTest.mousePress(card, Qt.MouseButton.BackButton)
    assert wait_until(lambda: page.live.card is None)                       # the mouse's Back
    QTest.mouseRelease(page, Qt.MouseButton.BackButton)                     # QTest's pressed state never outlives the test
    card = opened()
    card.done.click()
    assert wait_until(lambda: page.live.card is None)


def test_the_credits_card_names_what_readme_lists_and_the_credits_lack(qapp, fakes):
    fakes.credits = ("JMdict", ["TMDB"], "")
    page, store, shell = make(fakes)
    page.live.open_credits()
    assert wait_until(lambda: page.live.card is not None)
    text = page.live.card.text.toPlainText()
    assert "README's Data Credits also names: TMDB" in text and S.README_POINTER in text
    assert not page.live.card.licence.isVisibleTo(page.live.card)           # no licence line: nothing said
    page.live.card.close()


def test_no_licence_file_leaves_the_row_saying_nothing(qapp, fakes):
    fakes.licence = ""
    page, store, shell = make(fakes)
    settle()
    assert not page.live.parts["data_credits"]["licence"].isVisibleTo(page)


# --- text size, motion --------------------------------------------------------------------------------------------- #
def test_text_size_goes_through_the_shell_once_then_the_page_restyles(qapp, fakes, monkeypatch):
    monkeypatch.setattr(live, "LIVE_TEXT_SIZE", True)     # the live path, kept for M4.1 (off by the ruling: FXP S5)
    page, store, shell = make(fakes)
    restyled = []
    monkeypatch.setattr(page, "restyle", lambda: restyled.append(True))
    page.row("text_size").controls[0].changed.emit("L")
    assert shell.sizes == ["L"] and restyled == [True]
    assert store.calls == []                              # the shell's method saved it, not the page


def test_a_shell_with_set_look_is_called_with_the_size(qapp, fakes, monkeypatch):
    monkeypatch.setattr(live, "LIVE_TEXT_SIZE", True)
    page, store, shell = make(fakes, text_size=False)
    looks = []
    shell.set_look = lambda text_size=None: looks.append(text_size)
    monkeypatch.setattr(page, "restyle", lambda: None)
    page.row("text_size").controls[0].changed.emit("S")
    assert looks == ["S"] and store.calls == []


def test_without_a_shell_method_the_page_saves_and_says_restart(qapp, fakes):
    page, store, shell = make(fakes, text_size=False)
    page.row("text_size").controls[0].changed.emit("L")
    assert store.calls == [({"text_size": "L"}, None)]
    assert shell.bar_line.lines == [strings.RESTART_TO_APPLY]


# --- laptop fixes row 15: *Restart now to apply?* ------------------------------------------------------------------ #
def _with_restart(shell):
    shell.restarts = []
    shell.restart = lambda: shell.restarts.append(True)
    return shell


def test_text_size_asks_restart_now_and_yes_restarts_once_after_the_page_saved(qapp, fakes):
    # Sonic: "having it ask and then if they select yes to restart it would auto restart". Before: only the bar's
    # *Restart Surasura to apply*, and the user had to quit and start Surasura again by hand.
    page, store, shell = make(fakes)
    _with_restart(shell)
    page.row("text_size").controls[0].changed.emit("L")
    assert store.calls == [({"text_size": "L"}, None)]          # saved first: the quit writes it before the new start
    card = page.live.asking
    assert card is not None and card.isVisible()
    assert card.title.text() == S.TEXT_SIZE_RESTART_ASK
    assert "Large" in card.body.text()
    assert card.yes.text() == S.TEXT_SIZE_RESTART_YES and card.no.text() == S.TEXT_SIZE_RESTART_NO
    assert card.yes.toolTip() and card.no.toolTip()
    assert shell.restarts == []                                 # nothing before the answer
    card.yes.click()
    assert shell.restarts == [True] and page.live.asking is None
    assert shell.bar_line.lines == []                           # no *Restart to apply*: it is restarting
    assert store.calls == [({"text_size": "L"}, None)]          # written once


@pytest.mark.parametrize("how", ["later", "esc"])
def test_later_or_esc_keeps_working_and_says_restart_to_apply(qapp, fakes, how):
    page, store, shell = make(fakes)
    _with_restart(shell)
    page.row("text_size").controls[0].changed.emit("S")
    card = page.live.asking
    if how == "later":
        card.no.click()
    else:
        card.close()                                            # Esc / Back / a click outside close the card: No
    QApplication.processEvents()
    assert shell.restarts == [] and page.live.asking is None
    assert shell.bar_line.lines == [strings.RESTART_TO_APPLY]
    assert store.calls == [({"text_size": "S"}, None)]          # still saved for the next start


def test_choosing_the_size_already_shown_asks_nothing(qapp, fakes):
    page, store, shell = make(fakes)
    _with_restart(shell)
    shown = style.current()[1]
    other = "L" if shown != "L" else "S"
    page.row("text_size").controls[0].changed.emit(other)
    page.live.asking.no.click()
    shell.bar_line.lines.clear()
    page.row("text_size").controls[0].changed.emit(shown)      # back to the size on screen: nothing to apply
    assert page.live.asking is None and shell.restarts == [] and shell.bar_line.lines == []
    assert store.calls[-1] == ({"text_size": shown}, None)


def test_B2_3_while_a_generate_runs_nothing_restarts_and_the_bar_says_after_it_finishes(qapp, fakes):
    """B2-3: a quit cancels a Generate that can still stop, and nothing starts it again — so *Restart now* is never
    offered while one waits or runs (the bar says to restart once it ends), and one starting before the answer keeps
    *Restart now* from restarting. The size is saved either way. The ask's words promise nothing the quit won't do."""
    page, store, shell = make(fakes)
    _with_restart(shell)
    running = [True]
    shell.generating = lambda: running[0]
    page.row("text_size").controls[0].changed.emit("L")
    assert page.live.asking is None and shell.restarts == []
    assert shell.bar_line.lines == [S.TEXT_SIZE_AFTER_GENERATE] and store.calls == [({"text_size": "L"}, None)]
    running[0] = False
    shell.bar_line.lines.clear()
    page.row("text_size").controls[0].changed.emit("S")
    card = page.live.asking
    assert card is not None and "finishes first" not in card.body.text()
    running[0] = True                                            # a Generate started while the card was open
    card.yes.click()
    assert shell.restarts == [] and shell.bar_line.lines == [S.TEXT_SIZE_AFTER_GENERATE]


def test_B2_3_the_window_says_whether_a_generate_waits_or_runs_by_the_registrys_snapshot(qapp):
    from app.services import jobs
    view = jobs.JobView

    def job(kind, state):
        return view(1, kind, "", state, None, None, None, None, None, False, "cancel", False, False)
    assert not jobs.generating(()) and not jobs.generating([job("generate", jobs.DONE), job("mine", jobs.RUNNING)])
    for state in (jobs.QUEUED, jobs.WAITING, jobs.RUNNING, jobs.CANCELLING):
        assert jobs.generating([job("generate", state)])


def test_motion_is_saved_and_set_on_the_clock(qapp, fakes, monkeypatch):
    page, store, shell = make(fakes)
    mode = motion.clock().mode
    set_to = []
    monkeypatch.setattr(mode, "set_setting", set_to.append)
    page.row("app_motion").controls[0].changed.emit("reduced")
    assert set_to == ["reduced"] and store.calls == [({"app_motion": "reduced"}, None)]


# --- Export -------------------------------------------------------------------------------------------------------- #
@pytest.fixture
def save_as(monkeypatch):
    asked = []

    def dialog(parent, title, name, filters):
        asked.append((title, name, filters))
        return (asked.answer, "") if hasattr(asked, "answer") else ("D:\\書き出し\\list", "")
    asked = type("Asked", (list,), {})()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(dialog))
    return asked


@pytest.mark.parametrize("row_id, fmt, ext", [("export_frequency_list", "yomitan", ".zip"),
                                              ("export_reading_words", "txt", ".txt")])
def test_a_format_export_asks_the_format_then_the_file_then_runs_and_says_so(qapp, fakes, save_as, row_id, fmt, ext):
    page, store, shell = make(fakes)
    page.live.parts[row_id]["export"].click()
    assert wait_until(lambda: page.live.pop is not None and page.live.pop.isVisible())
    pop = page.live.pop
    assert pop.choice.values() == list(exports.FORMATS)
    assert page.row(row_id).isEnabled() and page.live._exporting == row_id   # under way from the click on, never
    #                                                                         greyed (round 8 row 45)
    pop.choice.set_value(fmt)
    pop.pick()
    title, name, filters = save_as[0]
    assert name == exports.save_as(fmt, exports.INITIAL_NAMES[live.EXPORTS[row_id]])[2] and ext in filters
    assert wait_until(lambda: shell.bar_line.lines[-1:] == [live.flat(fakes.outcome.message)])
    export_call = next(args for name_, _gui, args in fakes.calls if name_ == "run_export")
    assert export_call == (live.EXPORTS[row_id], "ja", fmt, "D:\\書き出し\\list" + ext)
    assert shell.bar_line.lines[-2] == S.EXPORT_RUNNING.format(name=page.row(row_id).row.label)
    assert page.row(row_id).isEnabled()


def test_the_sentence_list_asks_through_the_warning_first(qapp, fakes, save_as, monkeypatch):
    asked = []

    def ask(window, title, body, yes, yes_tip, **kw):
        asked.append((title, body, yes, kw.get("default_no")))
        kw["on_answer"](asked.answer)
    asked = type("Asked", (list,), {"answer": False})()
    monkeypatch.setattr(live.confirm, "ask", ask)
    page, store, shell = make(fakes)
    page.live.export("export_sentence_list")
    assert wait_until(lambda: asked)
    assert asked[0] == (exports.SENTENCE_WARNING_TITLE, exports.SENTENCE_WARNING, exports.SENTENCE_CONFIRM, True)
    assert save_as == [] and "run_export" not in fakes.names()          # No: nothing asked, nothing written
    assert page.row("export_sentence_list").isEnabled()
    asked.answer = True
    page.live.export("export_sentence_list")
    assert wait_until(lambda: "run_export" in fakes.names())
    assert save_as[0][1] == "Anki_Sentence_List.csv"
    assert next(args for n, _g, args in fakes.calls if n == "run_export")[2] == "anki"


def test_a_failing_export_says_why(qapp, fakes, save_as):
    fakes.outcome = exports.Outcome("failed", None, 0, "Failed to export:\n[Errno 13] Permission denied: 'D:\\x.zip'")
    page, store, shell = make(fakes)
    page.live.export("export_frequency_list")
    assert wait_until(lambda: page.live.pop is not None)
    page.live.pop.pick()
    assert wait_until(lambda: shell.bar_line.lines[-1] == "Failed to export: [Errno 13] Permission denied: 'D:\\x.zip'")
    fakes.outcome = OSError("the disk is full")             # a fault in the worker: said too
    page.live.export("export_frequency_list")
    assert wait_until(lambda: page.live.pop is not None)
    page.live.pop.pick()
    assert wait_until(lambda: shell.bar_line.lines[-1] == "Failed to export: the disk is full")
    assert page.row("export_frequency_list").isEnabled()


def test_no_data_says_generate_first_and_asks_nothing(qapp, fakes, save_as):
    fakes.ready = exports.Outcome("no data", None, 0, exports.EMPTY["frequency_list"])
    page, store, shell = make(fakes)
    page.live.export("export_frequency_list")
    assert wait_until(lambda: shell.bar_line.lines[-1:] == [exports.EMPTY["frequency_list"]])
    assert page.live.pop is None and save_as == [] and page.row("export_frequency_list").isEnabled()


def test_one_export_at_a_time_its_arc_turning_while_it_runs(qapp, fakes, save_as):
    fakes.export_gate = threading.Event()
    page, store, shell = make(fakes)
    page.live.export("export_reading_words")
    assert wait_until(lambda: page.live.pop is not None)
    page.live.pop.pick()
    assert wait_until(lambda: "run_export" in fakes.names())
    # round 8 row 45: never greyed — the pressed row's arc turns while it writes, and no other row's
    arcs = {r: qpress.arc(page.live.parts[r]["export"]) is not None for r in live.EXPORTS}
    assert all(page.row(r).isEnabled() for r in live.EXPORTS) and arcs == {r: r == "export_reading_words"
                                                                          for r in live.EXPORTS}
    page.live.export("export_frequency_list")
    assert shell.bar_line.lines[-1] == S.EXPORT_BUSY and fakes.names().count("ready_to_export") == 1
    fakes.export_gate.set()
    assert wait_until(lambda: page.live._exporting is None and qpress.arc(page.live.parts["export_reading_words"]
                                                                          ["export"]) is None)


def test_closing_the_format_pop_or_the_file_dialog_writes_nothing(qapp, fakes, save_as):
    page, store, shell = make(fakes)
    page.live.export("export_frequency_list")
    assert wait_until(lambda: page.live.pop is not None and page.live.pop.isVisible())
    QTest.keyClick(page.live.pop, Qt.Key.Key_Escape)
    assert wait_until(lambda: page.live.pop is None) and page.row("export_frequency_list").isEnabled()
    page.live.export("export_frequency_list")
    assert wait_until(lambda: page.live.pop is not None and page.live.pop.isVisible())
    QTest.mouseClick(page.live.pop.room, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(2, 2))
    assert wait_until(lambda: page.live.pop is None)                        # a click outside
    save_as.answer = ""                                                      # the file dialog cancelled
    page.live.export("export_frequency_list")
    assert wait_until(lambda: page.live.pop is not None)
    page.live.pop.pick()
    settle()
    assert "run_export" not in fakes.names() and page.row("export_frequency_list").isEnabled()


# --- every new button tipped and wired ---------------------------------------------------------------------------- #
def test_every_new_button_has_a_tooltip_and_the_page_is_wired(qapp, fakes):
    from tests.qt.test_wiring import problems
    page, store, shell = make(fakes, dict(ALL_ON), skipped="99.0.0")
    found, n = problems(page)
    assert found == [] and n > 25
    buttons = [w for parts in page.live.parts.values() for w in parts.values() if isinstance(w, sc.Door)]
    assert len(buttons) >= 12 and all(b.toolTip() for b in buttons)
    page.live.export("export_frequency_list")
    assert wait_until(lambda: page.live.pop is not None)
    found, _n = problems(page.live.pop)
    assert found == []
    page.live.pop.close()
    page.live.open_credits()
    assert wait_until(lambda: page.live.card is not None)
    found, _n = problems(page.live.card)
    assert found == []
    page.live.card.close()


# --- the real reads (no window) -------------------------------------------------------------------------------------- #
def test_the_real_credits_read_holds_the_credits_and_finds_readmes_sources_in_them():
    from app import credits
    text, missing, licence = live.read_credits()
    assert credits.data_credits() in text and "JMdict" in text
    assert missing == []                                   # README's Data Credits are all named (S11)
    assert licence == credits.licence_line()


def test_no_token_store_yet_reads_no_numbers_and_makes_no_store():
    from app import token_index
    path = token_index.store_path_for("zh")
    assert not live.os.path.exists(path)
    assert live.read_previews({"logic": {}}, "zh") is None
    assert not live.os.path.exists(path)                   # a look never makes one
