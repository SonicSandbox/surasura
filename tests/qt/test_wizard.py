"""The setup wizard's pages (W3.5 part 3; the signed draft `wizard-draft/WIZARD-DRAFT.md`, WZ-1…WZ-7; the contract
`w35wiz/contract.md`). Tier: looks — behaviour tests, no mutants.

What a wrong answer would cost: a page that writes on *Skip* (a choice the user never made, saved — the covers yes
sends show names out), a *Next* that writes another page's keys or a key twice, a *Back* that loses what was chosen, an
Esc that closes the window mid-setup, a *Generate* that leaves the wizard up or never finishes setup, Anki Miner's
switch offered while Anki Miner can't make cards.

The wizard calls the contract's Qt-free API (`app/services/setup_wizard.py`, `app/services/anki_miner_setup.py`); these
tests drive it through stand-ins with the contract's names and shapes (`FakeApi`, `FakeMiner`), so a page's own rules
are proven here and the services' rules in their own suites. Real words throughout (decks, shows, folders as a learner
has them).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from app.qt import windows
from app.qt import wizard as W
from app.qt import wizard_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems

BANDS = ["core", "common", "occasional", "uncommon", "rare", "very_rare", "native"]
DECKS = [("日本語::Mining", 2140), ("Core 2k", 1980), ("Kanji Practice", 610)]


# --- stand-ins with the contract's names --------------------------------------------------------------------------------- #
class FakeSettings:
    """The settings service's shape: `get()` and `set(changes)`; every `set` recorded."""

    def __init__(self, data=None):
        self.data = dict(data or {})
        self.calls = []

    def get(self):
        return dict(self.data)

    def set(self, changes, update=None, now=False):
        if not changes:
            return
        self.calls.append(dict(changes))
        self.data.update(changes)


class FakeApi:
    """`setup_wizard`'s contract: `should_open`, `preselect`, `writes`, `save`, `finish`, `anki_look`, `first_sync`,
    `library_rows`, `open_content_manager`, `level_numbers`, `generate`. `writes` follows the contract's table."""
    LATER = {"leave": (False, False, False), "mark": (True, True, False), "aside": (True, False, True)}

    def __init__(self, anki=None, rows=(), numbers=None, accepted=True, preselect=None):
        self.anki = anki if anki is not None else {"open": True, "say": None, "decks": list(DECKS),
                                                   "preselected": ["日本語::Mining", "Core 2k"]}
        self.rows = list(rows)
        self.numbers = numbers
        self.accepted = accepted
        self.pre = preselect
        self.calls = []
        self.synced = []
        self.content_ends = []

    def should_open(self, settings):
        return settings.get("onboarding_completed") is not True

    def preselect(self, settings, language):
        if self.pre is not None:
            return self.pre
        return {"language": {"language": settings.get("target_language") or "ja"},
                "known": {"how": "anki", "decks": []}, "shows": {"covers": True},
                "order": {"keep_in_order": True, "deck": None, "later": "leave", "open_anki": False},
                "cards": {"make_cards": True}, "level": {"automatic": True, "band": None}}

    def writes(self, page, answers, settings, language):
        if page == "language":
            return {"target_language": answers["language"]}
        if page == "known":
            return {"anki_sync_decks": {language: list(answers["decks"])}} if answers["how"] == "anki" else {}
        if page == "shows":
            return {"covers_download": bool(answers["covers"])}
        if page == "order":
            tag, flag, suspend = self.LATER[answers["later"]]
            return {"junban_auto_actions": answers["keep_in_order"], "junban_deck": answers["deck"],
                    "junban_later_tag": tag, "junban_later_flag": flag, "junban_later_suspend": suspend,
                    "connect_open_anki": answers["open_anki"]}
        if page == "cards":
            return {} if answers["make_cards"] is None else {"connect_enabled": bool(answers["make_cards"])}
        if page == "level":
            if answers["automatic"]:
                return {"logic.selection.auto": True}
            return {"logic.selection.auto": False, "logic.selection.band": answers["band"]}
        raise KeyError(page)

    def save(self, settings_service, page, answers, language):
        self.calls.append(("save", page, dict(answers), language))
        changes = self.writes(page, answers, settings_service.get(), language)
        settings_service.set(changes)
        return changes

    def finish(self, settings_service):
        self.calls.append(("finish",))
        settings_service.set({"onboarding_completed": True})
        return {"onboarding_completed": True}

    def anki_look(self, settings, language):
        self.calls.append(("anki_look", language))
        return dict(self.anki)

    def first_sync(self, registry, settings, language, decks, on_end, automation=None):
        self.synced.append((language, list(decks), callable(automation)))
        on_end(None)                                       # (the job's end; a None result is "nothing to say")
        return object()

    def library_rows(self, settings, language):
        self.calls.append(("library_rows", language))
        return list(self.rows)

    def open_content_manager(self, registry, language, on_end):
        self.calls.append(("content", language))
        self.content_ends.append(on_end)
        return object()

    def level_numbers(self, settings, language):
        self.calls.append(("level_numbers", language))
        return self.numbers

    def generate(self, services):
        self.calls.append(("generate",))
        return self.accepted


class FakeMiner:
    """`anki_miner_setup` as built: `look`, `install` (blocking, on a worker; `confirm()` asked before any byte; then
    the progress in bytes, the cancel Event, `on_end` once), `STAR_URL`, `RELEASES`."""
    STAR_URL = "https://github.com/0xzerolight/anki_miner"
    RELEASES = "https://github.com/0xzerolight/anki_miner/releases"
    SIZE = 188_000_000

    def __init__(self, look, route="installer-closed", gate=None):
        self.answer = look
        self.route = route                 # what the install ends with once the user said yes
        self.gate = gate                   # a threading.Event the download waits on (to see it mid-way)
        self.looks = 0
        self.installs = 0
        self.asked = []
        self.progress = []

    def look(self, settings, language):
        self.looks += 1
        return self.answer

    def install(self, on_progress, cancel, on_end, confirm=None):
        self.installs += 1
        yes = bool(confirm()) if confirm is not None else False
        self.asked.append(yes)
        if not yes:
            result = "declined" if confirm is not None else "opened-releases"
        elif self.route == "busy":
            result = "busy"
        else:
            result = self.route
            for done in (0, self.SIZE // 2):
                on_progress(done, self.SIZE)
                self.progress.append(done)
            if self.gate is not None:
                self.gate.wait(5)
            if cancel.is_set():
                result = "opened-releases"
            else:
                on_progress(self.SIZE, self.SIZE)
        on_end(result)
        return result


def miner_look(state, version=None, fix=None):
    states = {"missing": ("ok", "ok", "off", "off"), "ready": ("ok", "ok", "ok", "ok"),
              "needs-setup": ("ok", "ok", "ok", "warn"), "too-old": ("ok", "ok", "warn", "off")}[state]
    return {"state": state, "version": version, "fix": fix,
            "dots": [(name, st, f"{name}: {st}") for name, st in zip(S.DOTS, states)]}


class FakeBridge(QObject):
    generate_changed = pyqtSignal(object)
    settings_written = pyqtSignal(object)


class FakeServices:
    def __init__(self, settings):
        self.settings = settings
        self.registry = object()
        self.automation = None


class FakeShell(QMainWindow):
    """What the wizard reads of the main window: its services, its bridge, its bar."""

    def __init__(self, settings):
        super().__init__()
        self.services = FakeServices(settings)
        self.bridge = FakeBridge(self)
        self.bar = []
        self.bar_line = type("Bar", (), {"set_full": lambda _self, text: self.bar.append(text)})()
        self.tabs = []
        central = QWidget(self)
        QVBoxLayout(central)
        self.setCentralWidget(central)
        self.resize(1200, 800)

    def show_tab(self, name):
        self.tabs.append(name)


class GenState:
    def __init__(self, state, step=None, done=None, total=None):
        self.state, self.step, self.done, self.total = state, step, done, total
        self.quiet, self.message, self.log_path = False, None, None


@pytest.fixture
def make(qapp, monkeypatch):
    """A wizard over a stand-in main window: (wizard, shell, api, settings, miner)."""
    made = []
    launched = []
    monkeypatch.setattr(windows, "launch", lambda shell, op: launched.append(op.name))
    monkeypatch.setattr(windows, "open_url", lambda url: launched.append(url))

    def build(api=None, miner=None, data=None):
        settings = FakeSettings(data if data is not None else {})
        shell = FakeShell(settings)
        api = api or FakeApi()
        miner = miner or FakeMiner(miner_look("missing"))
        wiz = W.SetupWizard(shell, parent=shell.centralWidget(), api=api, miner=miner)
        shell.centralWidget().layout().addWidget(wiz)
        shell.show()
        wiz.launched = launched
        made.append(shell)
        QApplication.processEvents()
        return wiz, shell, api, settings, miner
    yield build
    for shell in made:
        shell.close()


def go_to(wiz, page_id):
    """Next through the pages before `page_id` (each with its preselects)."""
    while W.PAGES[wiz.index] != page_id:
        before = wiz.index
        wiz.page.entered()
        wait_until(lambda: not wiz._anki_looking, 2.0)
        if wiz.page.id == "cards":
            wait_until(lambda: wiz.page.look is not None, 2.0)
        if wiz.page.next_offered():
            wiz.next()
        else:
            wiz.skip()
        assert wiz.index == before + 1


# --- the frame ------------------------------------------------------------------------------------------------------------ #
def test_page_one_preselects_japanese_with_no_back_or_skip_and_enter_goes_on(make):
    wiz, _shell, api, settings, _m = make()
    page = wiz.page
    assert page.id == "language" and page.channel.value() == "ja"
    assert wiz.btn_back.isHidden() and wiz.btn_skip.isHidden() and not wiz.btn_next.isHidden()
    assert wiz.btn_next.text() == S.NEXT
    QTest.keyClick(wiz.focusWidget() or wiz, Qt.Key.Key_Return)
    assert wiz.index == 1
    assert settings.calls == [{"target_language": "ja"}]           # exactly the page's key, once
    assert wiz.steps.passed == frozenset({0}) and wiz.steps.current == 1


def test_arrows_choose_chinese_and_next_saves_it_and_the_later_pages_follow(make):
    wiz, _shell, api, settings, _m = make()
    first = wiz.page.channel.choice("ja")
    first.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(first, Qt.Key.Key_Right)
    assert wiz.page.channel.value() == "zh"
    assert wiz.page.channel.choice("zh").hasFocus() or wiz.page.channel.choice("zh").focusPolicy() == \
        Qt.FocusPolicy.TabFocus                                    # the channel is one Tab stop: the chosen one
    assert wiz.page.channel.choice("ja").focusPolicy() == Qt.FocusPolicy.NoFocus
    wiz.next()
    assert settings.calls == [{"target_language": "zh"}]
    assert wiz.language == "zh" and wiz.pages[1].sentence.language == "zh"
    assert wait_until(lambda: ("anki_look", "zh") in api.calls)                       # page 2 reads Anki for the language picked


def test_skip_writes_nothing_on_any_page(make):
    wiz, _shell, api, settings, _m = make()
    wiz.next()                                                     # page 1 has no Skip
    settings.calls.clear()
    saves = len([c for c in api.calls if c[0] == "save"])
    for _page in W.PAGES[1:-1]:
        wiz.skip()
    assert W.PAGES[wiz.index] == "level"
    assert settings.calls == [] and len([c for c in api.calls if c[0] == "save"]) == saves
    assert wiz.steps.passed == frozenset(range(5))                 # skipped steps are passed too (✓)


def test_back_keeps_the_choices_and_writes_nothing(make):
    wiz, *_ , settings, _m = make()
    go_to(wiz, "shows")
    page = wiz.page
    QTest.mouseClick(page.covers.switch, Qt.MouseButton.LeftButton)
    assert page.covers.switch.isChecked() is False
    wiz.skip()
    calls = len(settings.calls)
    wiz.back()
    assert wiz.page is page and page.covers.switch.isChecked() is False
    assert len(settings.calls) == calls
    wiz.next()
    assert settings.calls[-1] == {"covers_download": False}        # the off, chosen before Back, is what Next saves


def test_finish_later_closes_and_writes_nothing_more(make):
    wiz, _shell, api, settings, _m = make()
    seen = []
    wiz.finished.connect(seen.append)
    QTest.mouseClick(wiz.btn_later, Qt.MouseButton.LeftButton)
    assert seen == ["later"]
    assert settings.calls == [] and ("finish",) not in api.calls    # never onboarding_completed


def test_esc_and_the_back_button_do_nothing_on_the_wizard(make):
    wiz, shell, _api, settings, _m = make()
    go_to(wiz, "shows")
    seen = []
    wiz.finished.connect(seen.append)
    for target in (wiz, wiz.page.covers.switch, wiz.btn_next):
        QTest.keyClick(target, Qt.Key.Key_Escape)
    back = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), Qt.MouseButton.BackButton,
                       Qt.MouseButton.BackButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(wiz, back)
    QApplication.processEvents()
    assert seen == [] and wiz.isVisible() and shell.isVisible() and W.PAGES[wiz.index] == "shows"


def test_every_control_is_wired_tipped_and_named(make):
    wiz, *_ = make(miner=FakeMiner(miner_look("ready", "3.7")))
    for page in W.PAGES[1:]:
        go_to(wiz, page)
    wait_until(lambda: wiz.pages[4].look is not None, 2.0)
    found, walked = problems(wiz)
    assert walked >= 20                                            # every page's buttons, switches and choices
    assert found == []


def test_no_colour_or_inline_string_in_the_wizards_files():
    # (the window's own scans cover app/qt/; this names the wizard's files so a regression points here)
    import os
    import re
    from tests.qt.test_bridge import user_string_literals
    from tests.qt.test_style import _COLOUR_LITERAL, _QCOLOR_LITERAL
    root = os.path.dirname(W.__file__)
    for name in ("wizard.py", "wizard_strings.py", "first_run.py"):
        text = open(os.path.join(root, name), encoding="utf-8").read()
        assert user_string_literals(text) == [], name
        assert not [ln for ln in text.splitlines() if _COLOUR_LITERAL.search(ln) or _QCOLOR_LITERAL.search(ln)], name
        assert not re.search(r"animate\(\s*\d", text), name


# --- 2 · what you know ---------------------------------------------------------------------------------------------------- #
def test_from_anki_is_recommended_with_its_decks_ticked_and_next_saves_them_and_starts_the_first_sync(make):
    wiz, shell, api, settings, _m = make()
    wiz.next()
    page = wiz.page
    assert wait_until(lambda: wiz.anki is not None)
    assert page.channel.value() == "anki" and page.anki.recommended and page.anki.dot == "ok"
    assert set(page.chips) == {d for d, _n in DECKS}
    assert page.chosen_decks() == ["日本語::Mining", "Core 2k"]     # Anki's own preselect, ticked
    QTest.mouseClick(page.chips["Kanji Practice"], Qt.MouseButton.LeftButton)
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [{"anki_sync_decks": {"ja": ["日本語::Mining", "Core 2k", "Kanji Practice"]}}]
    assert wait_until(lambda: api.synced)
    assert api.synced == [("ja", ["日本語::Mining", "Core 2k", "Kanji Practice"], True)]
    assert W.PAGES[wiz.index] == "shows"                           # the sync never holds the page


def test_with_every_deck_unticked_from_anki_cant_go_on(make):
    wiz, *_ = make()
    wiz.next()
    page = wiz.page
    assert wait_until(lambda: wiz.anki is not None)
    for chip in page.chips.values():
        if chip.isChecked():
            QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert not page.next_offered() and wiz.btn_next.isHidden()


def test_anki_closed_preselects_import_a_list_and_check_again_looks_again(make):
    api = FakeApi(anki={"open": False, "say": None, "decks": [], "preselected": []})
    wiz, _shell, api, settings, _m = make(api=api)
    wiz.next()
    page = wiz.page
    assert wait_until(lambda: wiz.anki is not None)
    assert page.channel.value() == "import" and not page.anki.recommended and page.anki.dot == "off"
    assert not page.import_part.isHidden() and page.closed_part.isHidden()
    page.channel.choose("anki", user=True)                         # From Anki picked anyway: Anki isn't open
    assert not page.closed_part.isHidden() and wiz.btn_next.isHidden()
    looks = len([c for c in api.calls if c[0] == "anki_look"])
    QTest.mouseClick(page.btn_check, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: len([c for c in api.calls if c[0] == "anki_look"]) == looks + 1)


def test_import_a_list_opens_the_importers_doors_and_saves_only_what_the_rules_say(make):
    api = FakeApi(anki={"open": False, "say": None, "decks": [], "preselected": []})
    wiz, _shell, api, settings, _m = make(api=api)
    wiz.next()
    page = wiz.page
    assert wait_until(lambda: wiz.anki is not None)
    QTest.mouseClick(page.doors["migaku"], Qt.MouseButton.LeftButton)
    QTest.mouseClick(page.doors["apkg_known"], Qt.MouseButton.LeftButton)
    assert wiz.launched == ["migaku", "apkg_known"]
    settings.calls.clear()
    wiz.next()
    assert settings.calls == []                                    # Import: the importer's own writes, none here
    assert api.calls[-2:] != [] and ("save", "known", {"how": "import", "decks": []}, "ja") in api.calls
    assert api.synced == []


def test_start_fresh_saves_nothing_and_starts_no_sync(make):
    wiz, _shell, api, settings, _m = make()
    wiz.next()
    page = wiz.page
    assert wait_until(lambda: wiz.anki is not None)
    QTest.mouseClick(page.channel.choice("fresh"), Qt.MouseButton.LeftButton)
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [] and api.synced == []


# --- 3 · your shows --------------------------------------------------------------------------------------------------------- #
def test_shows_lists_the_library_with_paths_in_a_backslash_font_and_covers_on_by_default(make):
    rows = [{"name": "星空ダイナー", "count": 12, "folder": r"E:\Shows\Hoshizora Diner", "kind": "shows"},
            {"name": "風の旅人", "count": 24, "folder": r"E:\Shows\Kaze no Tabibito", "kind": "shows"},
            {"name": "夜の図書館", "count": 1, "folder": r"E:\Books\yoru-no-toshokan.epub", "kind": "reading"}]
    wiz, _shell, api, settings, _m = make(api=FakeApi(rows=rows))
    go_to(wiz, "shows")
    page = wiz.page
    assert wait_until(lambda: page.row_paints == 1)
    texts = [w.text() for w in page.rows_part.findChildren(W.QLabel)]
    assert "星空ダイナー" in texts and "12 episodes · E:\\Shows\\Hoshizora Diner" in texts and \
        "a book · E:\\Books\\yoru-no-toshokan.epub" in texts
    line = next(w for w in page.rows_part.findChildren(W.QLabel) if w.text().startswith("24 episodes"))
    assert line.font().families()[0] == "Segoe UI"                 # never Yu Gothic first: no E:¥Shows¥
    assert page.covers.switch.isChecked() and not page.covers.rec.isHidden()
    page.show_rows(rows)
    assert page.row_paints == 1                                    # the same rows repaint nothing (S19)
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [{"covers_download": True}]


def test_add_content_opens_the_content_manager_and_its_end_reads_the_rows_again(make):
    wiz, _shell, api, *_ = make()
    go_to(wiz, "shows")
    page = wiz.page
    assert wait_until(lambda: ("library_rows", "ja") in api.calls)
    reads = api.calls.count(("library_rows", "ja"))
    QTest.mouseClick(page.btn_add, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: api.content_ends)
    api.rows = [{"name": "ゆるキャン△", "count": 12, "folder": r"D:\Anime\Yuru Camp", "kind": "shows"}]
    api.content_ends[0](0)                                         # the Content Manager's job ended (its thread)
    assert wait_until(lambda: api.calls.count(("library_rows", "ja")) == reads + 1)
    assert wait_until(lambda: page.row_paints >= 1 and not page.rows_part.isHidden())
    QTest.mouseClick(page.btn_samples, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: len(api.content_ends) == 2)          # the samples live in the Content Manager


def test_an_empty_library_shows_no_rows(make):
    wiz, *_ = make(api=FakeApi(rows=[]))
    go_to(wiz, "shows")
    QApplication.processEvents()
    assert wait_until(lambda: wiz.page.rows_part.isHidden())


# --- 4 · card order --------------------------------------------------------------------------------------------------------- #
def test_card_order_preselects_keep_in_order_page_twos_deck_and_leave_and_saves_them(make):
    wiz, _shell, api, settings, _m = make()
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: not page.controls.isHidden())
    assert page.keep.switch.isChecked() and not page.keep.rec.isHidden()
    assert page.deck_box.currentText() == "日本語::Mining"          # from page 2's decks
    assert page.later.value() == "leave" and not page.open_anki.switch.isChecked()
    QTest.mouseClick(page.later.choice("aside"), Qt.MouseButton.LeftButton)
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [{"junban_auto_actions": True, "junban_deck": "日本語::Mining", "junban_later_tag": True,
                               "junban_later_flag": False, "junban_later_suspend": True, "connect_open_anki": False}]


def test_card_order_with_anki_closed_shows_check_again_and_enter_is_skip(make):
    api = FakeApi(anki={"open": False, "say": None, "decks": [], "preselected": []})
    wiz, _shell, api, settings, _m = make(api=api)
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: not page.closed_part.isHidden() and not wiz._anki_looking)
    assert page.controls.isHidden() and wiz.btn_next.isHidden() and not wiz.btn_skip.isHidden()
    settings.calls.clear()
    wiz.enter()
    assert W.PAGES[wiz.index] == "cards" and settings.calls == []


# --- 5 · cards made for you -------------------------------------------------------------------------------------------------- #
def _question(wiz):
    """The install's question in the window (a card answered before may not be deleted yet: the open one)."""
    from app.qt import confirm

    def open_cards():
        return [c for c in wiz.window().findChildren(confirm.Confirm) if c.answer is None]
    assert wait_until(open_cards)
    return open_cards()[-1]


def test_anki_miner_missing_offers_install_and_the_star_and_no_switch(make):
    miner = FakeMiner(miner_look("missing"))
    wiz, _shell, api, settings, miner = make(miner=miner)
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert page.make.isHidden() and not page.btn_install.isHidden() and not page.btn_star.isHidden()
    assert page.name.text() == S.MINER_MISSING and page.btn_check.isHidden()
    assert [d.state for d in page.dots] == ["ok", "ok", "off", "off"]
    assert page.dots[2].accessibleName() == "Anki Miner: not yet"  # status never colour alone
    QTest.mouseClick(page.btn_star, Qt.MouseButton.LeftButton)
    assert wiz.launched == [FakeMiner.STAR_URL]
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [] and W.PAGES[wiz.index] == "level"  # nothing to switch on: Next writes nothing
    assert ("save", "cards", {"make_cards": None}, "ja") in api.calls       # None, never False (Set up again)


def test_install_asks_in_the_window_first_shows_its_progress_and_looks_again_when_the_installer_closes(make):
    import threading
    gate = threading.Event()
    miner = FakeMiner(miner_look("missing"), route="installer-closed", gate=gate)
    wiz, *_ = make(miner=miner)
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    looks = miner.looks
    QTest.mouseClick(page.btn_install, Qt.MouseButton.LeftButton)
    card = _question(wiz)                                          # asked before any byte, in the window
    assert miner.progress == [] and card.yes.text() == S.INSTALL_ASK_YES
    card.yes.click()
    assert wait_until(lambda: not page.loading.isHidden() and page.progress.value() == 500)
    assert not page.btn_install.isEnabled() and not page.btn_cancel.isHidden()
    gate.set()
    assert wait_until(lambda: wiz.installing is None and miner.looks >= looks + 1)
    assert miner.asked == [True] and page.loading.isHidden() and page.busy_line.isHidden()


def test_install_not_now_downloads_nothing(make):
    miner = FakeMiner(miner_look("missing"))
    wiz, *_ = make(miner=miner)
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    looks = miner.looks
    QTest.mouseClick(page.btn_install, Qt.MouseButton.LeftButton)
    _question(wiz).no.click()
    assert wait_until(lambda: wiz.installing is None)
    assert miner.asked == [False] and miner.progress == [] and miner.looks == looks


def test_install_cancel_stops_the_download_and_busy_says_why(make):
    import threading
    gate = threading.Event()
    miner = FakeMiner(miner_look("missing"), gate=gate)
    wiz, *_ = make(miner=miner)
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    QTest.mouseClick(page.btn_install, Qt.MouseButton.LeftButton)
    _question(wiz).yes.click()
    assert wait_until(lambda: not page.loading.isHidden())
    QTest.mouseClick(page.btn_cancel, Qt.MouseButton.LeftButton)
    gate.set()
    assert wait_until(lambda: wiz.installing is None)
    assert wait_until(lambda: page.loading.isHidden() and not page.btn_check.isHidden())   # releases: Check again
    miner.route = "busy"
    QTest.mouseClick(page.btn_install, Qt.MouseButton.LeftButton)
    _question(wiz).yes.click()
    assert wait_until(lambda: wiz.installing is None and not page.busy_line.isHidden())


def test_finish_later_while_the_install_asks_answers_no(make):
    miner = FakeMiner(miner_look("missing"))
    wiz, *_ = make(miner=miner)
    go_to(wiz, "cards")
    assert wait_until(lambda: wiz.page.look is not None)
    QTest.mouseClick(wiz.page.btn_install, Qt.MouseButton.LeftButton)
    _question(wiz)
    wiz.finish_later()
    assert wait_until(lambda: miner.asked == [False])              # the worker isn't left waiting


def test_anki_miner_ready_shows_the_switch_on_and_next_saves_connect_enabled(make):
    wiz, _shell, api, settings, _m = make(miner=FakeMiner(miner_look("ready", "3.7")))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert not page.make.isHidden() and page.make.isChecked() and not page.rec.isHidden()
    assert page.sub.text() == "Anki Miner 3.7 · ready for Surasura"
    assert page.btn_install.isHidden() and page.btn_star.isHidden() and not page.star_quiet.isHidden()
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [{"connect_enabled": True}]


def test_anki_miner_needing_a_fix_shows_its_amber_dot_its_sentence_and_check_again(make):
    fix = {"say": "Anki Miner's own setup isn't finished (its note type).",
           "do": "In Anki Miner: Settings → finish the setup"}
    wiz, *_ = make(miner=FakeMiner(miner_look("needs-setup", "3.7", fix)))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert page.dot.state == "warn" and page.name.text() == fix["say"] and page.sub.text() == fix["do"]
    assert page.dots[3].state == "warn" and page.make.isHidden() and not page.btn_check.isHidden()
    assert page.btn_install.isHidden()


# --- 6 · your list ----------------------------------------------------------------------------------------------------------- #
_PER_BAND = {"core": (120, 81.0, 0.5), "common": (380, 90.2, 1.4), "occasional": (812, 96.1, 3.2),
             "uncommon": (1430, 97.4, 5.5), "rare": (2210, 98.2, 8.0), "very_rare": (3300, 98.9, None),
             "native": (5120, 99.4, 20.0)}
# `level_numbers` as built: the chosen band's figures on top, every band's in `numbers`, `auto_band` Automatic's
NUMBERS = dict({"bands": BANDS, "chosen": "occasional", "automatic": True, "auto_band": "occasional",
                "numbers": {b: {"words": w, "coverage": c, "every_hours": h} for b, (w, c, h) in _PER_BAND.items()}},
               words=812, coverage=96.1, every_hours=3.2)


def test_your_list_says_counting_until_numbers_then_shows_the_automatic_bands(make):
    api = FakeApi(numbers=None)
    wiz, *_ = make(api=api)
    go_to(wiz, "level")
    page = wiz.page
    assert wait_until(lambda: ("level_numbers", "ja") in api.calls)
    assert not page.counting.isHidden() and page.numbers_part.isHidden()
    assert wiz.btn_next.text() == S.GENERATE and not wiz.btn_skip.isHidden()
    page.show_numbers(NUMBERS)
    assert page.counting.isHidden() and not page.numbers_part.isHidden()
    assert page.auto.isChecked() and page.slider.bands[page.slider.index] == "occasional"
    assert [page.big[k].text() for k in ("words", "coverage", "every")] == ["812", "96%", "3 h"]
    page.slider.set_index(BANDS.index("very_rare"), user=True)
    assert page.big["every"].text() == S.NONE_YET                  # every_hours None: an em dash


def test_moving_the_slider_turns_automatic_off_and_generate_saves_the_band(make):
    api = FakeApi(numbers=NUMBERS)
    wiz, shell, api, settings, _m = make(api=api)
    go_to(wiz, "level")
    page = wiz.page
    assert wait_until(lambda: page.numbers is not None)
    page.slider.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(page.slider, Qt.Key.Key_Right)
    assert not page.auto.isChecked() and page.slider.bands[page.slider.index] == "uncommon"
    assert page.big["words"].text() == "1,430" and page.big["coverage"].property("tone") == "ok"
    settings.calls.clear()
    wiz.next()
    assert settings.calls[:2] == [{"logic.selection.auto": False, "logic.selection.band": "uncommon"},
                                  {"onboarding_completed": True}]


def test_generate_finishes_setup_runs_generate_and_closes_onto_current_when_it_ends(make):
    api = FakeApi(numbers=NUMBERS)
    wiz, shell, api, settings, _m = make(api=api)
    seen = []
    wiz.finished.connect(seen.append)
    go_to(wiz, "level")
    settings.calls.clear()
    QTest.keyClick(wiz, Qt.Key.Key_Return)                         # Enter = Generate
    assert settings.calls == [{"logic.selection.auto": True}, {"onboarding_completed": True}]
    assert wait_until(lambda: ("generate",) in api.calls)
    assert wiz.generating and wiz.say_line.text() == S.MAKING and not wiz.btn_next.isEnabled()
    assert wiz.hairline.value == 0.0
    shell.bridge.generate_changed.emit(GenState("running", "Counting words", 3, 10))
    assert wiz.say_line.text().startswith(S.MAKING) and seen == []
    wiz.back()
    wiz.skip()
    assert W.PAGES[wiz.index] == "level" and seen == []           # nothing moves while the list is made
    shell.bridge.generate_changed.emit(GenState("current"))
    assert seen == ["generated"]


def test_a_generate_that_cant_start_says_so_in_the_bar_and_closes(make):
    api = FakeApi(numbers=NUMBERS, accepted=False)
    wiz, shell, api, settings, _m = make(api=api)
    seen = []
    wiz.finished.connect(seen.append)
    go_to(wiz, "level")
    wiz.next()
    assert wait_until(lambda: seen == ["done"])
    assert shell.bar == [S.NOT_STARTED] and ("finish",) in api.calls


def test_skip_on_your_list_finishes_setup_without_generate(make):
    api = FakeApi(numbers=NUMBERS)
    wiz, _shell, api, settings, _m = make(api=api)
    seen = []
    wiz.finished.connect(seen.append)
    go_to(wiz, "level")
    settings.calls.clear()
    wiz.skip()
    assert seen == ["done"] and settings.calls == [{"onboarding_completed": True}]
    assert ("generate",) not in api.calls


def test_a_late_answer_after_the_wizard_closed_paints_nothing(make):
    wiz, *_ = make()
    go_to(wiz, "cards")
    wiz.finish_later()
    page = wiz.pages[4]
    wiz.alive(page.show_look)(miner_look("ready", "3.7"))
    assert page.look is None or page.look.get("state") != "ready"


def test_set_up_again_preselects_what_the_settings_say(make):
    pre = {"language": {"language": "zh"}, "known": {"how": "fresh", "decks": []}, "shows": {"covers": False},
           "order": {"keep_in_order": False, "deck": "中文::Mining", "later": "mark", "open_anki": True},
           "cards": {"make_cards": False}, "level": {"automatic": False, "band": "rare"}}
    anki = {"open": True, "say": None, "decks": [("中文::Mining", 820), ("HSK 3", 600)], "preselected": []}
    wiz, *_ = make(api=FakeApi(preselect=pre, anki=anki), data={"target_language": "zh"})
    assert wiz.pages[0].channel.value() == "zh"
    assert wiz.pages[2].covers.switch.isChecked() is False
    order = wiz.pages[3]
    assert order.later.value() == "mark" and order.open_anki.switch.isChecked() and not order.keep.switch.isChecked()
    go_to(wiz, "order")
    assert wait_until(lambda: not order.controls.isHidden())
    assert order.deck_box.currentText() == "中文::Mining"
    assert wiz.pages[5].answers() == {"automatic": False, "band": "rare"}


def test_the_real_rules_take_every_pages_answers_as_the_contract_says(make):
    # The wizard's answers through `setup_wizard.writes` as built (worker S): each page's keys and nothing else.
    real = pytest.importorskip("app.services.setup_wizard")

    class Real(FakeApi):
        def writes(self, page, answers, settings, language):
            return real.writes(page, answers, settings, language)
    wiz, _shell, api, settings, _m = make(api=Real(numbers=NUMBERS), miner=FakeMiner(miner_look("ready", "3.7")))
    for page in W.PAGES[:-1]:
        go_to(wiz, W.PAGES[W.PAGES.index(page) + 1])
    keys = [set(c) for c in settings.calls]
    assert keys[0] == {"target_language"}
    assert keys[1] == {"anki_sync_decks"} and settings.calls[1]["anki_sync_decks"]["ja"] == ["日本語::Mining", "Core 2k"]
    assert keys[2] == {"covers_download"}
    assert {"junban_auto_actions", "junban_deck", "junban_later_tag", "junban_later_flag", "junban_later_suspend",
            "connect_open_anki"} <= keys[3] and "logic.automation" not in keys[3]
    assert keys[4] == {"connect_enabled"}
    wiz.next()
    assert set(settings.calls[5]) == {"logic.selection.auto"} and settings.calls[6] == {"onboarding_completed": True}
