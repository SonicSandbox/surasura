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
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget

from app.qt import press as qpress
from app.qt import strings
from app.qt import windows
from app.qt import wizard as W
from app.qt import wizard_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems

REAL_LAUNCH = windows.launch                     # (the fixture stands in for it; a door's failure needs the real one)
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
        self.samples = 4

    def should_open(self, settings):
        return settings.get("onboarding_completed") is not True

    def preselect(self, settings, language):
        if self.pre is not None:
            return self.pre
        return {"language": {"language": settings.get("target_language") or "ja"},
                "known": {"how": "anki", "decks": []}, "shows": {"covers": True},
                "order": {"keep_in_order": True, "deck": None, "later": "leave"},
                "cards": {"make_cards": True, "open_anki": False}, "level": {"automatic": True, "band": None}}

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
                    "junban_later_tag": tag, "junban_later_flag": flag, "junban_later_suspend": suspend}
        if page == "cards":
            if answers["make_cards"] is None:
                return {}
            out = {"connect_enabled": bool(answers["make_cards"])}
            if answers["make_cards"] and answers.get("open_anki") is not None:
                out["connect_open_anki"] = bool(answers["open_anki"])
            return out
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

    def add_samples(self, language):                       # (W3.2 Q3: page 3's samples, without the Content Manager)
        self.calls.append(("samples", language))
        return self.samples

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

    def __init__(self, look, route="installer-closed", gate=None, on_cancel="opened-releases"):
        self.answer = look
        self.route = route                 # what the install ends with once the user said yes
        self.gate = gate                   # a threading.Event the download waits on (to see it mid-way)
        self.on_cancel = on_cancel         # what a cancelled download ends with (M's route as built: the releases page)
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
                result = self.on_cancel
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
    indexed = pyqtSignal(object)


class FakeServices:
    def __init__(self, settings):
        self.settings = settings
        self.registry = object()
        self.automation = None


class FakeShell(QMainWindow):
    """What the wizard reads of the main window: its services, its bridge, its bar, its `closing`."""
    closing = pyqtSignal()

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
    # 順 present, as in the app (GitHub's checkout has no private modules/; the absent case has its own test)
    monkeypatch.setattr(windows, "module_present", lambda name: True)
    monkeypatch.setattr(windows, "_FOUND", {})                     # looked for again: an earlier test may have found none
    monkeypatch.setattr(windows, "_LOOKING", set())

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


def settle(wiz):
    """Until the page shown takes a press (painted, and its settle time gone: AD-3)."""
    assert wait_until(wiz.settled, 3.0)


# --- the frame ------------------------------------------------------------------------------------------------------------ #
def test_page_one_preselects_japanese_with_no_back_or_skip_and_enter_goes_on(make):
    wiz, _shell, api, settings, _m = make()
    page = wiz.page
    assert page.id == "language" and page.channel.value() == "ja"
    assert wiz.btn_back.isHidden() and wiz.btn_skip.isHidden() and not wiz.btn_next.isHidden()
    assert wiz.btn_next.text() == S.NEXT
    settle(wiz)
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
    assert not page.import_part.isHidden() and not page.closed_part.isHidden()   # Check again stays (IK-17)
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
    texts = [w.text().replace("​", "") for w in page.rows_part.findChildren(W.QLabel)]   # (a path may break)
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


class FakeAdder(QObject):
    """+ Add's actions as the window holds them (`shell.adder`, app/qt/add_menu.py): what can act, each run recorded."""
    given = pyqtSignal(str)

    def __init__(self, names=("files", "folder", "paste")):
        super().__init__()
        self.names = names
        self.ran = []
        self.added = []

    def entries(self, names=()):
        return [(n, n, n) for n in names if n in self.names]

    def run(self, name, first=False):
        self.ran.append(f"{name}:first" if first else name)        # first: setup's own first look (Current, SRC-1)
        self.given.emit("Added 嵐壁の巨兵 at #1 · analysed on the next Generate")

    def add_files(self, paths, **_kw):
        self.added.append(list(paths))                             # alpha 8: page 3's files, the drop's path
        return 1


def test_page_three_offers_a_file_a_folder_and_youtube_and_nothing_else_to_bring_in(make):
    """Alpha 8 (Sonic: "You just pick the file or you pick the folder"; "it asks to pick a folder twice"): page 3 has
    one *Choose a file…*, one *Choose a folder…* and *YouTube…* (while its door is on) — no EPUB button, no second
    folder button, nothing that opens the 2.x Content Manager. Each is tipped."""
    wiz, shell, api, *_ = make(data={"enable_youtube_transcripts": True})
    shell.adder = FakeAdder()
    go_to(wiz, "shows")
    page = wiz.page
    page.entered()
    assert wait_until(lambda: not page.btn_youtube.isHidden())
    shown = [b.text() for b in page.findChildren(QPushButton) if b.isVisibleTo(page) and b.text()]
    assert [t for t in shown if t in (S.PICK_FILE, S.PICK_FOLDER, S.YOUTUBE)] == [S.PICK_FILE, S.PICK_FOLDER, S.YOUTUBE]
    assert not [t for t in shown if "EPUB" in t or t == strings.ADD_ITEMS["folder"][0]], shown
    assert sum(1 for t in shown if "folder" in t.lower()) == 1, "one folder button, never two"
    assert all(b.toolTip() for b in (page.btn_file, page.btn_pick, page.btn_youtube))
    assert ("content", "ja") not in api.calls


def test_page_three_without_a_library_open_hides_what_cant_act(make):
    """No writer in the window (no library open yet) and no folder reading: *Choose a file…* and *Choose a folder…*
    aren't shown (a button that can't act is never offered); *YouTube…* still is, its door on."""
    wiz, *_ = make(data={"enable_youtube_transcripts": True}, api=NoFoldersApi())
    go_to(wiz, "shows")
    page = wiz.page
    page.entered()
    assert wait_until(lambda: not page.btn_youtube.isHidden())
    assert page.btn_file.isHidden() and page.btn_pick.isHidden()


class NoFoldersApi(FakeApi):
    read_folders = None                                           # (`can_read_folders`: not callable)


def test_choose_a_file_lists_what_the_library_reads_and_says_what_it_doesnt(make, tmp_path):
    """*Choose a file…*: each file picked is read by the one rule (`path_utils.file_kind`) — a subtitle, a text and an
    EPUB are listed (each with *Remove*), a video is said, never listed; nothing is brought in before *Next*."""
    wiz, shell, *_ = make()
    adder = shell.adder = FakeAdder()
    go_to(wiz, "shows")
    page = wiz.page
    picked = [str(tmp_path / n) for n in ("ぼっち・ざ・ろっく！ 第01話.ja.srt", "夜の図書館.epub", "日記.txt",
                                          "ぼっち・ざ・ろっく！ 第01話.mkv")]
    wiz.pick_files_dialog = lambda _title, _start: picked
    QTest.mouseClick(page.btn_file, Qt.MouseButton.LeftButton)
    assert page.files == [os.path.normpath(p) for p in picked[:3]]
    assert not page.refused_line.isHidden() and "第01話.mkv" in page.refused_line.text()
    assert S.FILE_NOT_READ.format(name="ぼっち・ざ・ろっく！ 第01話.mkv") in page.refused_line.text()
    QApplication.processEvents()                                   # (a new row is shown by the next turn of the loop)
    removes = [b for b in page.folders_part.findChildren(QPushButton)
               if b.text() == S.FOLDER_REMOVE and b.isVisibleTo(page)]
    assert len(removes) == 3
    QTest.mouseClick(removes[2], Qt.MouseButton.LeftButton)        # 日記.txt left out
    assert page.files == [os.path.normpath(p) for p in picked[:2]]
    assert adder.added == []


def test_next_brings_the_texts_in_at_once_and_each_book_through_extract_then_goes_on(make, tmp_path, monkeypatch):
    """*Next* with files: the subtitles and texts are given to + Add's writer (the top of Current, the drop's path),
    each EPUB goes to Extract's own child, and setup goes on to page 4 — nothing waits for them."""
    wiz, shell, *_ = make()
    adder = shell.adder = FakeAdder()
    books = []
    monkeypatch.setattr(wiz, "_extract_book", books.append)
    go_to(wiz, "shows")
    page = wiz.page
    picked = [str(tmp_path / "ぼっち・ざ・ろっく！ 第01話.ja.srt"), str(tmp_path / "夜の図書館.epub")]
    wiz.pick_files_dialog = lambda _title, _start: picked
    page.btn_file.click()
    wiz.next()
    assert adder.added == [[os.path.normpath(picked[0])]] and books == [os.path.normpath(picked[1])]
    assert wiz.say_line.text() == S.FILES_ADDED.format(what="1 file")
    assert W.PAGES[wiz.index] == "order" and page.files == []


class FakeFetch:
    """The YouTube module's `fetch_first(shell, links, language, said, ended)`: each call recorded; `end(...)` answers
    the last one as the module would, on the window's thread."""

    def __init__(self):
        self.calls = []

    def __call__(self, shell, links, language, said, ended):
        self.calls.append((list(links), language))
        self.ended = ended
        return object()


def test_youtube_opens_its_links_at_once_and_next_asks_for_the_risk_tick_first(make, monkeypatch):
    """*YouTube…* opens the links box at once, focused; *Next* with links and the downloader's risk unticked says so
    and stays (nothing fetched); ticked — saved as the downloader's own key — *Next* fetches each line."""
    wiz, _shell, _api, settings, _m = make(data={"enable_youtube_transcripts": True})
    fetch = FakeFetch()
    monkeypatch.setattr(W, "_youtube_fetcher", lambda: fetch)
    go_to(wiz, "shows")
    page = wiz.page
    page.entered()
    assert wait_until(lambda: not page.btn_youtube.isHidden())
    assert page.links_part.isHidden()
    QTest.mouseClick(page.btn_youtube, Qt.MouseButton.LeftButton)
    assert not page.links_part.isHidden() and page.links.hasFocus()
    page.links.setPlainText("https://www.youtube.com/watch?v=eFwn9e8IYsI\n\n  "
                            "https://www.youtube.com/watch?v=7nlUSMQKRKQ&list=PLjfPBTv1Zr1J8RTG9iCANlm2vzBhl7QZn  \n")
    wiz.next()
    assert fetch.calls == [] and page.refused_line.text() == S.YOUTUBE_NEEDS_RISK.format(risk=page.yt_risk.name.text()) and W.PAGES[wiz.index] == "shows"
    page.yt_risk.switch.click()
    assert settings.calls[-1] == {"youtube_risk_acknowledged": True}
    wiz.next()
    assert fetch.calls == [(["https://www.youtube.com/watch?v=eFwn9e8IYsI",
                             "https://www.youtube.com/watch?v=7nlUSMQKRKQ&list=PLjfPBTv1Zr1J8RTG9iCANlm2vzBhl7QZn"], "ja")]
    assert wiz.covered is not None, "YouTube alone: the load screen covers while its videos come"
    assert wiz.covered.side.text() == S.YOUTUBE_FETCHING.format(what="2 videos")
    assert wiz.covered.task.text() == S.LOAD_YOUTUBE


def test_a_youtube_fetch_that_brings_nothing_says_why_on_the_page_and_setup_goes_on(make, monkeypatch):
    """The fetch's end with nothing (offline, a private video): its plain words on the page and in the bar, the load
    screen gone (nothing to sort), *Next* free again."""
    wiz, shell, *_ = make(data={"enable_youtube_transcripts": True, "youtube_risk_acknowledged": True})
    fetch = FakeFetch()
    monkeypatch.setattr(W, "_youtube_fetcher", lambda: fetch)
    go_to(wiz, "shows")
    page = wiz.page
    page.entered()
    assert wait_until(lambda: not page.btn_youtube.isHidden())
    page.btn_youtube.click()
    page.links.setPlainText("https://www.youtube.com/watch?v=eFwn9e8IYsI")
    wiz.next()
    assert wiz.covered is not None and wiz.fetching is not None
    fetch.ended([], ["could not read https://www.youtube.com/watch?v=eFwn9e8IYsI: YouTube couldn't be reached: check "
                     "your internet connection"])
    line = S.YOUTUBE_FAILED.format(why="could not read https://www.youtube.com/watch?v=eFwn9e8IYsI: YouTube couldn't "
                                       "be reached: check your internet connection")
    assert wiz.covered is None and wiz.fetching is None and wiz.say_line.text() == line
    assert W.PAGES[wiz.index] == "shows" and page.links.toPlainText() == ""


def test_youtube_videos_that_came_go_to_new_arrivals_then_the_sort_screen(make, monkeypatch):
    """The fetch's transcripts go through the downloader's own seam (`windows.youtube_arrivals`: New arrivals); once
    they landed, the load screen says so beside its task and the sorting comes up."""
    wiz, shell, *_ = make(data={"enable_youtube_transcripts": True, "youtube_risk_acknowledged": True})
    fetch = FakeFetch()
    monkeypatch.setattr(W, "_youtube_fetcher", lambda: fetch)
    handed = []

    def arrivals(_shell, then=None):
        def complete(paths):
            handed.append(paths)
            then(len(paths), 0, 0)
        return complete
    monkeypatch.setattr(windows, "youtube_arrivals", arrivals)
    sorted_ = []
    monkeypatch.setattr(wiz, "_load_sort", lambda: sorted_.append(wiz.covered.side.text()))
    go_to(wiz, "shows")
    page = wiz.page
    page.entered()
    assert wait_until(lambda: not page.btn_youtube.isHidden())
    page.btn_youtube.click()
    page.links.setPlainText("https://www.youtube.com/watch?v=7nlUSMQKRKQ&list=PLjfPBTv1Zr1J8RTG9iCANlm2vzBhl7QZn")
    wiz.next()
    path = os.path.join("Processed", "peko peko vlog - 【Japanese Podcast #43】 [7nlUSMQKRKQ].txt")
    fetch.ended([path], [])
    assert handed == [[path]]
    assert sorted_ == [S.YOUTUBE_DONE.format(what="1 video")]


def test_youtube_line_says_what_came_and_what_didnt():
    assert W.youtube_line(2, 0, "") == "YouTube · 2 videos in New arrivals"
    assert W.youtube_line(0, 1, "") == "YouTube · 1 video in your library"
    assert W.youtube_line(1, 0, "the video is private or no longer there") == \
        "YouTube · 1 video in New arrivals · the video is private or no longer there"
    assert W.youtube_line(0, 0, "") == S.YOUTUBE_FAILED.format(why=S.YOUTUBE_NONE)


def test_samples_are_copied_in_said_and_the_rows_read_again_and_the_line_leaves_with_its_page(make):
    wiz, _shell, api, *_ = make()
    go_to(wiz, "shows")
    page = wiz.page
    assert wait_until(lambda: ("library_rows", "ja") in api.calls)
    reads = api.calls.count(("library_rows", "ja"))
    QTest.mouseClick(page.btn_samples, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: wiz.say_line.text() == S.SAMPLES_ADDED_LINE.format(n=4))
    assert ("samples", "ja") in api.calls and ("content", "ja") not in api.calls
    assert wait_until(lambda: api.calls.count(("library_rows", "ja")) == reads + 1)
    wiz.skip()
    assert wiz.say_line.isHidden()                                 # page 3's line is page 3's (AD-12)


def test_samples_into_a_library_with_files_say_so(make):
    api = FakeApi()
    api.samples = 0
    wiz, *_ = make(api=api)
    go_to(wiz, "shows")
    QTest.mouseClick(wiz.page.btn_samples, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: wiz.say_line.text() == S.SAMPLES_NONE)


def test_a_rows_kind_names_its_count_a_book_in_parts_and_files_without_a_title(make):
    rows = [{"name": "夜の図書館", "count": 12, "folder": r"E:\Books\Yoru", "kind": "reading"},
            {"name": "VTuber 切り抜き", "count": 3, "folder": r"E:\Videos\Clips", "kind": "videos"},
            {"name": "Downloads", "count": 2, "folder": r"E:\Downloads", "kind": None}]
    wiz, *_ = make(api=FakeApi(rows=rows))
    go_to(wiz, "shows")
    page = wiz.page
    assert wait_until(lambda: page.row_paints == 1)
    texts = [w.text().replace("​", "") for w in page.rows_part.findChildren(W.QLabel)]   # (a path may break)
    assert r"a book · 12 parts · E:\Books\Yoru" in texts
    assert r"3 videos · E:\Videos\Clips" in texts and r"2 files · E:\Downloads" in texts


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
    assert page.later.value() == "leave" and not hasattr(page, "open_anki"), "Open Anki is the Cards page's (IK-4)"
    QTest.mouseClick(page.later.choice("aside"), Qt.MouseButton.LeftButton)
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [{"junban_auto_actions": True, "junban_deck": "日本語::Mining", "junban_later_tag": True,
                               "junban_later_flag": False, "junban_later_suspend": True}]


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


@pytest.mark.parametrize("running, words, how, card", [
    (True, S.ANKI_NO_CONNECT, S.ANKI_NO_CONNECT_HOW, S.ANKI_NO_CONNECT_CARD),
    (None, S.ANKI_UNSURE, S.ANKI_UNSURE_HOW, S.ANKI_UNSURE_CARD),
    (False, S.ANKI_CLOSED, "", S.ANKI_CLOSED),
], ids=["open-no-ankiconnect", "cant-tell", "closed"])
def test_C11_setup_says_anki_is_open_without_ankiconnect_and_what_to_do_on_both_anki_pages(make, running, words, how,
                                                                                            card):
    # §C11: Anki open but AnkiConnect not answering said so, with what to do (the add-on, its code, a restart) — never
    # "Anki isn't open"; a look that can't tell the two apart says both; a closed Anki keeps its one line
    api = FakeApi(anki={"open": False, "say": None, "decks": [], "preselected": [], "running": running})
    wiz, _shell, api, _settings, _m = make(api=api)
    wiz.next()
    known = wiz.page
    assert wait_until(lambda: wiz.anki is not None and not known.closed_part.isHidden())
    assert known.closed_line.text() == words and known.anki.line == card
    assert known.closed_how.text() == how and known.closed_how.isHidden() == (not how)
    if how:
        assert "AnkiConnect" in how and "2055492159" in how and "restart Anki" in how
    go_to(wiz, "order")
    order = wiz.page
    assert wait_until(lambda: not order.closed_part.isHidden() and not wiz._anki_looking)
    assert order.closed_line.text() == words
    assert order.closed_how.text() == how and order.closed_how.isHidden() == (not how)


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
    assert wait_until(lambda: wiz.launched == [FakeMiner.STAR_URL])            # on a worker (round 8 row 45)
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [] and W.PAGES[wiz.index] == "level"  # nothing to switch on: Next writes nothing
    assert ("save", "cards", {"make_cards": None, "open_anki": None}, "ja") in api.calls     # None, never False


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
    # round 8 row 45: never greyed while it installs — its arc turns, and a press meanwhile starts nothing
    assert page.btn_install.isEnabled() and qpress.arc(page.btn_install) is not None
    assert not page.btn_cancel.isHidden()
    QTest.mouseClick(page.btn_install, Qt.MouseButton.LeftButton)
    assert miner.asked == [True]
    gate.set()
    assert wait_until(lambda: wiz.installing is None and miner.looks >= looks + 1)
    assert qpress.arc(page.btn_install) is None
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
    assert not page.open_anki.isHidden() and not page.open_anki.switch.isChecked(), "off by default (Q4-16)"
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [{"connect_enabled": True, "connect_open_anki": False}]


def test_open_anki_when_surasura_opens_is_shown_and_saved_only_with_make_cards_on(make):
    """IK-4 (P4.1 row 4.1.1): *Open Anki for me* is Connect's — Settings shows it only with Connect on, and the setup
    shows it under *Make cards for me*, only while that is on: turned off, the row goes and nothing of it is saved."""
    wiz, _shell, api, settings, _m = make(miner=FakeMiner(miner_look("ready", "3.7")))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    page.open_anki.switch.click()
    assert page.answers() == {"make_cards": True, "open_anki": True}
    page.make.click()
    assert page.open_anki.isHidden() and page.answers() == {"make_cards": False, "open_anki": None}
    settings.calls.clear()
    wiz.next()
    assert settings.calls == [{"connect_enabled": False}], "Make cards off: Open Anki for me is never written"


def test_anki_miner_needing_a_fix_shows_its_amber_dot_its_sentence_and_check_again(make):
    fix = {"say": "Anki Miner's own setup isn't finished (its note type).",
           "do": "In Anki Miner: Settings → finish the setup"}
    wiz, *_ = make(miner=FakeMiner(miner_look("needs-setup", "3.7", fix)))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert page.dot.state == "warn" and page.name.text() == fix["say"] and page.sub.text() == fix["do"]
    assert page.dots[3].state == "warn" and not page.btn_check.isHidden()
    assert page.btn_install.isHidden()
    # WZ-4 (Sonic's answer): installed but not ready, *Make cards for me* stays hidden and nothing turns Connect on —
    # the shared rule's *ready* answer (`services.tools_found`), never the *installed* one Settings asks
    assert page.make.isHidden() and not page.offered() and page.answers() == {"make_cards": None, "open_anki": None}
    assert page.open_anki.isHidden()
    assert page.btn_setup.isHidden(), "a setup Surasura can't finish itself offers no Finish its setup"


def test_A4M1_2_finish_its_setup_runs_anki_miners_own_setup_as_a_job_then_says_so_and_looks_again(make):
    """A4M1-2 (lean taken, PROVISIONAL; Sonic: "I honestly don't want to ever have to open anki miner. Ever."): a
    setup only Anki Miner's own `setup` lacks (its dictionaries) offers *Finish its setup*, never "open Anki Miner";
    the press runs it on a worker as a job (the bar lists it), its arc turning, a second press meanwhile starting
    nothing; then the bar says it's finished and the page looks again."""
    import threading
    from app.connect import setup as connect_setup
    gate = threading.Event()
    fix = {"say": "Anki Miner still needs its dictionaries (dictionary: No dictionary is installed.).",
           "do": connect_setup.SETUP_DO, "update": False, "setup": True}
    miner = FakeMiner(miner_look("needs-setup", "3.10.1", fix))
    runs = []

    def finish_setup_as_job(registry, settings, language, on_progress=None, chosen=None, save=None):
        runs.append(language)
        gate.wait(5)
        return ("set-up", None)
    miner.finish_setup_as_job = finish_setup_as_job
    wiz, *_ = make(miner=miner)
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert not page.btn_setup.isHidden() and page.btn_install.isHidden()
    assert "Open Anki Miner" not in page.sub.text() and page.btn_setup.toolTip() == S.FINISH_SETUP_TIP
    looks = miner.looks
    QTest.mouseClick(page.btn_setup, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: runs == ["ja"]) and qpress.arc(page.btn_setup) is not None
    QTest.mouseClick(page.btn_setup, Qt.MouseButton.LeftButton)          # while it runs: nothing more
    gate.set()
    assert wait_until(lambda: not wiz.setting_up and miner.looks >= looks + 1)
    assert runs == ["ja"] and qpress.arc(page.btn_setup) is None


def test_A4M1_2_a_setup_that_didnt_finish_is_said_and_not_offered_again(make):
    """Review A2-3 / A2-5: a setup that ran but didn't finish says why in the bar, and the page no longer offers it
    this session (pressed again it would only run and fail again)."""
    from app.connect import setup as connect_setup
    fix = {"say": "Anki Miner still needs its dictionaries.", "do": connect_setup.SETUP_DO, "update": False,
           "setup": True}
    miner = FakeMiner(miner_look("needs-setup", "3.10.1", fix))
    miner.finish_setup_as_job = lambda registry, settings, language, on_progress=None, chosen=None, save=None: (
        "failed", "no space left")
    wiz, *_ = make(miner=miner)
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None and not page.btn_setup.isHidden())
    looks = miner.looks
    QTest.mouseClick(page.btn_setup, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: wiz.setup_failed and miner.looks >= looks + 1)
    assert wait_until(lambda: page.btn_setup.isHidden())


def test_A4M1_2b_a_deck_surasura_cant_tell_is_asked_on_the_page_and_the_choice_goes_with_the_next_press(make):
    """A4M1-2b (lean taken, PROVISIONAL; Sonic: "I honestly don't want to ever have to open anki miner. Ever."): when
    Surasura's own settings can't tell which deck Anki Miner's cards go in, *Finish its setup* answers "ask": the page
    shows the choice — this language's known decks first, the first chosen — never "open Anki Miner"; the next press
    hands the choice to the setup; once the look says ready, the choice leaves the page."""
    import threading
    from app.connect import setup as connect_setup
    fix = {"say": "Anki Miner doesn't know where your Japanese cards go yet (deck: not found).",
           "do": connect_setup.SETTINGS_DO, "update": False, "setup": True}
    miner = FakeMiner(miner_look("needs-setup", "3.10.1", fix))
    pressed = []
    answers = [("ask", {"deck": ["日本語::Mining", "日本語::Kaishi 1.5k", "Default"], "note_type": None, "why": None}),
               ("set-up", None)]
    done = threading.Event()

    def finish_setup_as_job(registry, settings, language, on_progress=None, chosen=None, save=None):
        pressed.append(chosen)
        answer = answers[len(pressed) - 1]
        done.set()
        return answer
    miner.finish_setup_as_job = finish_setup_as_job
    wiz, *_ = make(miner=miner)
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None and not page.btn_setup.isHidden())
    assert page.ask_part.isHidden() and "Open Anki Miner" not in page.sub.text()
    QTest.mouseClick(page.btn_setup, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: not page.ask_part.isHidden() and not wiz.setting_up)
    assert pressed == [None], "the first press chose nothing"
    assert not page.deck_row.isHidden() and page.note_row.isHidden()
    assert [page.ask_deck.itemText(i) for i in range(page.ask_deck.count())][:2] == ["日本語::Mining",
                                                                                     "日本語::Kaishi 1.5k"]
    assert page.ask_deck.currentText() == "日本語::Mining" and page.ask_line.text() == S.MINER_ASK_DECK
    assert page.ask_deck.toolTip() == S.MINER_DECK_TIP
    page.ask_deck.setCurrentIndex(1)
    QTest.mouseClick(page.btn_setup, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: len(pressed) == 2 and not wiz.setting_up)
    assert pressed[1] == {"deck": "日本語::Kaishi 1.5k", "note_type": None}
    assert wait_until(lambda: page.ask_part.isHidden()), "set up: nothing left to choose"
    miner.answer = miner_look("ready", "3.10.1")
    page.show_ask({"deck": ["日本語::Mining"], "note_type": None})
    page.show_look(miner.answer)
    assert page.ask_part.isHidden(), "a ready Anki Miner shows no choice"


def test_A4M1_2b_a_choice_asked_for_one_language_never_shows_after_a_switch_to_the_other(make):
    """A4M1-2b review (alpha 5): the setup runs on its own thread; a language switched while it ran never gets the
    other language's decks to choose from (the answer was asked for Japanese). The setup is handed the window's own
    settings writer, so the profile Surasura makes for itself is saved through it."""
    import threading
    from app.connect import setup as connect_setup
    fix = {"say": "Anki Miner doesn't know where your Japanese cards go yet (deck: not found).",
           "do": connect_setup.SETTINGS_DO, "update": False, "setup": True}
    miner = FakeMiner(miner_look("needs-setup", "3.10.1", fix))
    gate, calls = threading.Event(), []

    def finish_setup_as_job(registry, settings, language, on_progress=None, chosen=None, save=None):
        calls.append((language, save))
        gate.wait(5)
        return ("ask", {"deck": ["日本語::Mining", "Default"], "note_type": None, "why": None})
    miner.finish_setup_as_job = finish_setup_as_job
    wiz, *_ = make(miner=miner)
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None and not page.btn_setup.isHidden())
    QTest.mouseClick(page.btn_setup, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: len(calls) == 1)
    assert calls[0][0] == "ja" and calls[0][1] == wiz.services.settings.set, "the window's own settings writer"
    wiz.language = "zh"                 # switched on page 1 while the setup ran
    gate.set()
    assert wait_until(lambda: not wiz.setting_up)
    assert page.ask_part.isHidden(), "Japanese decks are never offered for Chinese"


def test_A4M1_2b_a_busy_answer_keeps_the_choice_and_an_ask_says_what_was_set(make):
    """Intent keeper (alpha 5): a press answered "busy" (Connect was running) keeps the deck the learner chose on the
    page for the next press; an "ask" says, in the bar, what that press already set."""
    import threading
    from app.connect import setup as connect_setup
    fix = {"say": "Anki Miner doesn't know where your Japanese cards go yet (deck: not found).",
           "do": connect_setup.SETTINGS_DO, "update": False, "setup": True}
    miner = FakeMiner(miner_look("needs-setup", "3.10.1", fix))
    made = " Surasura made its own Anki Miner profile, “Surasura”, a copy of yours, and makes cards with it."
    answers = [("ask", {"deck": ["日本語::Mining", "Default"], "note_type": None, "why": None, "said": made.strip()}),
               ("busy", None)]
    calls = []

    def finish_setup_as_job(registry, settings, language, on_progress=None, chosen=None, save=None):
        calls.append(chosen)
        return answers[len(calls) - 1]
    miner.finish_setup_as_job = finish_setup_as_job
    wiz, *_ = make(miner=miner)
    said = []
    wiz.say = said.append
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None and not page.btn_setup.isHidden())
    QTest.mouseClick(page.btn_setup, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: not page.ask_part.isHidden() and not wiz.setting_up)
    assert said[-1] == S.SETUP_SAID["ask"].format(detail=made)
    page.ask_deck.setCurrentIndex(1)
    QTest.mouseClick(page.btn_setup, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: len(calls) == 2 and not wiz.setting_up)
    assert not page.ask_part.isHidden() and page.ask_deck.currentText() == "Default", "busy: the choice stays"


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
    settle(wiz)
    QTest.keyClick(wiz, Qt.Key.Key_Return)                         # Enter = Generate
    assert settings.calls == [{"logic.selection.auto": True}, {"onboarding_completed": True}]
    assert wait_until(lambda: ("generate",) in api.calls)
    assert wiz.generating and wiz.say_line.text() == S.MAKING and not wiz.btn_next.isEnabled()
    assert wiz.hairline.value == 0.0
    shell.bridge.generate_changed.emit(GenState("running", "Counting words", 3, 10))
    assert wiz.say_line.text().startswith(S.MAKING_PCT.split("{")[0]) and seen == []
    assert "first time" in wiz.say_line.text()          # a7 (DIAGNOSIS 1): the wait is said where it is watched
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
           "order": {"keep_in_order": False, "deck": "中文::Mining", "later": "mark"},
           "cards": {"make_cards": False, "open_anki": True}, "level": {"automatic": False, "band": "rare"}}
    anki = {"open": True, "say": None, "decks": [("中文::Mining", 820), ("HSK 3", 600)], "preselected": []}
    wiz, *_ = make(api=FakeApi(preselect=pre, anki=anki), data={"target_language": "zh"})
    assert wiz.pages[0].channel.value() == "zh"
    assert wiz.pages[2].covers.switch.isChecked() is False
    order = wiz.pages[3]
    assert order.later.value() == "mark" and not order.keep.switch.isChecked()
    assert wiz.pages[4].open_anki.switch.isChecked()
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
    assert keys[1] == {"anki_sync_decks", "anki_sync_auto"} and settings.calls[1]["anki_sync_auto"] is True
    assert settings.calls[1]["anki_sync_decks"]["ja"] == ["日本語::Mining", "Core 2k"]
    assert keys[2] == {"covers_download"}
    assert {"junban_auto_actions", "junban_deck", "junban_later_tag", "junban_later_flag",
            "junban_later_suspend"} <= keys[3] and "logic.automation" not in keys[3] and "connect_open_anki" not in keys[3]
    assert keys[4] == {"connect_enabled", "connect_open_anki"}, "Open Anki saved with Make cards on (IK-4)"
    wiz.next()
    assert set(settings.calls[5]) == {"logic.selection.auto"} and settings.calls[6] == {"onboarding_completed": True}


# --- one action per press (the adversary's AD-1 … AD-3) ---------------------------------------------------------------- #
# What a wrong answer would cost: a page saved that the learner never saw — page 4's consent to re-order, tag and
# suspend their cards among them — by a held key, a double click, or an Enter meant for *Skip*.
def test_no_button_in_the_wizard_is_a_default_one(make):
    # Enter is Next only through the wizard's own key handling: no button takes it as a default would
    wiz, *_ = make(miner=FakeMiner(miner_look("missing")))
    for page in W.PAGES[1:]:
        go_to(wiz, page)
    buttons = wiz.findChildren(QPushButton)
    assert len(buttons) >= 10
    assert [b.text() for b in buttons if b.autoDefault() or b.isDefault()] == []


def test_enter_on_skip_back_or_finish_later_saves_nothing_and_moves_nothing(make):
    wiz, _shell, api, settings, _m = make()
    go_to(wiz, "shows")
    settle(wiz)
    settings.calls.clear()
    seen = []
    wiz.finished.connect(seen.append)
    for b in (wiz.btn_skip, wiz.btn_back, wiz.btn_later, wiz.page.btn_samples):
        b.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(b, Qt.Key.Key_Return)
        QTest.keyClick(b, Qt.Key.Key_Enter)
    assert W.PAGES[wiz.index] == "shows" and settings.calls == [] and seen == []
    assert ("samples", "ja") not in api.calls                     # Enter isn't a click on another button either
    wiz.btn_next.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(wiz.btn_next, Qt.Key.Key_Return)                # on Next itself, Enter is Next
    assert W.PAGES[wiz.index] == "order" and settings.calls == [{"covers_download": True}]


def test_enter_on_skip_on_your_list_never_generates(make):
    wiz, _shell, api, settings, _m = make(api=FakeApi(numbers=NUMBERS))
    go_to(wiz, "level")
    settle(wiz)
    settings.calls.clear()
    wiz.btn_skip.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(wiz.btn_skip, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert ("generate",) not in api.calls and ("finish",) not in api.calls and settings.calls == []


def test_holding_enter_down_never_walks_the_pages(make):
    wiz, _shell, api, settings, _m = make()
    settle(wiz)
    target = wiz.focusWidget() or wiz
    QApplication.sendEvent(target, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier,
                                             "\r", False))         # the press itself: Next
    assert wiz.index == 1
    settle(wiz)
    for _ in range(12):                                            # the key held: the repeats Windows sends
        QApplication.sendEvent(wiz.focusWidget() or wiz, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                                                   Qt.KeyboardModifier.NoModifier, "\r", True))
        QApplication.processEvents()
    assert wiz.index == 1 and settings.calls == [{"target_language": "ja"}]


def test_a_double_click_on_next_never_saves_the_page_it_brings_up(make):
    wiz, _shell, api, settings, _m = make()
    go_to(wiz, "shows")                                            # Anki already read: card order could go on
    settle(wiz)
    settings.calls.clear()
    QTest.mouseClick(wiz.btn_next, Qt.MouseButton.LeftButton)      # the first click: Your shows saved
    assert W.PAGES[wiz.index] == "order"
    QTest.mouseClick(wiz.btn_next, Qt.MouseButton.LeftButton)      # the second, at once
    QTest.mouseDClick(wiz.btn_next, Qt.MouseButton.LeftButton)     # and a double click as Qt sends one
    QApplication.processEvents()
    assert W.PAGES[wiz.index] == "order" and settings.calls == [{"covers_download": True}]   # no consent unseen
    settle(wiz)
    QTest.mouseClick(wiz.btn_next, Qt.MouseButton.LeftButton)      # a fresh press once the page was seen
    assert W.PAGES[wiz.index] == "cards" and "junban_auto_actions" in settings.calls[-1]


def test_a_page_not_painted_yet_takes_no_press_however_long_ago_it_changed(make):
    wiz, _shell, api, settings, _m = make()
    go_to(wiz, "shows")                                            # no event loop since: never painted
    wiz._shown_at -= 10.0
    assert not wiz.settled()
    settings.calls.clear()
    wiz.btn_next.click()
    assert W.PAGES[wiz.index] == "shows" and settings.calls == []
    settle(wiz)                                                    # painted: it takes the next press
    wiz.btn_next.click()
    assert W.PAGES[wiz.index] == "order"


def test_a_double_click_on_skip_never_skips_the_page_after_it(make):
    wiz, _shell, api, settings, _m = make()
    go_to(wiz, "cards")
    settle(wiz)
    QTest.mouseClick(wiz.btn_skip, Qt.MouseButton.LeftButton)
    QTest.mouseClick(wiz.btn_skip, Qt.MouseButton.LeftButton)      # on Your list, Skip would finish setup
    QApplication.processEvents()
    assert W.PAGES[wiz.index] == "level" and ("finish",) not in api.calls


# --- the install question at quit (AD-4) ----------------------------------------------------------------------------------- #
def _release_asks(wiz):
    for ask in wiz.findChildren(W._AskFromWorker):                 # (a failing run leaves no worker waiting)
        ask._event.set()


def test_the_window_closing_while_the_install_asks_answers_no_at_once(make):
    miner = FakeMiner(miner_look("missing"))
    wiz, shell, *_ = make(miner=miner)
    try:
        go_to(wiz, "cards")
        assert wait_until(lambda: wiz.page.look is not None)
        QTest.mouseClick(wiz.page.btn_install, Qt.MouseButton.LeftButton)
        _question(wiz)
        shell.closing.emit()                                       # the quit began (the window's close)
        assert wait_until(lambda: miner.asked == [False], 2.0)
    finally:
        _release_asks(wiz)


def test_a_question_dropped_with_its_window_answers_the_worker_no(make):
    miner = FakeMiner(miner_look("missing"))
    wiz, *_ = make(miner=miner)
    try:
        go_to(wiz, "cards")
        assert wait_until(lambda: wiz.page.look is not None)
        QTest.mouseClick(wiz.page.btn_install, Qt.MouseButton.LeftButton)
        _question(wiz).drop()                                      # the window hid with it open: no callback
        # its deletion is the No (a deferred delete: the app's loop runs it; processEvents alone never does)
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        assert wait_until(lambda: miner.asked == [False], 2.0)
    finally:
        _release_asks(wiz)


def test_the_install_question_keeps_its_first_answer(make):
    # *Download*, then the card's deletion: the worker reads yes, never the No its card's end would add
    wiz, *_ = make()
    ask = W._AskFromWorker(wiz)
    ask.answer_now(True)
    ask.answer_now(False)
    assert ask._answer is True


# --- the install's shoulds (AD-5, AD-6) ------------------------------------------------------------------------------------ #
def test_cancel_leaves_once_the_download_is_done(make):
    wiz, *_ = make()
    go_to(wiz, "cards")
    page = wiz.page
    wiz.installing = object()
    page.show_progress(FakeMiner.SIZE // 2, FakeMiner.SIZE)
    assert not page.btn_cancel.isHidden()
    page.show_progress(FakeMiner.SIZE, FakeMiner.SIZE)             # his installer opens now: nothing to cancel
    assert page.btn_cancel.isHidden() and not page.loading.isHidden()
    wiz.installing = None


def test_a_cancelled_download_says_it_stopped_and_offers_install_again(make):
    import threading
    gate = threading.Event()
    miner = FakeMiner(miner_look("missing"), gate=gate, on_cancel="cancelled")
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
    assert wiz.say_line.text() == S.INSTALL_STOPPED and not wiz.install_opened
    assert wait_until(lambda: page.btn_install.isEnabled() and not page.btn_install.isHidden())


# --- Generate's end is the learner's run (AD-7) ---------------------------------------------------------------------------- #
def test_an_automatic_generate_never_closes_the_wizard(make):
    wiz, shell, api, *_ = make(api=FakeApi(numbers=NUMBERS))
    seen = []
    wiz.finished.connect(seen.append)
    go_to(wiz, "level")
    wiz.next()
    assert wait_until(lambda: ("generate",) in api.calls)
    quiet = GenState("running", "Counting words", 3, 10)
    quiet.quiet = True
    shell.bridge.generate_changed.emit(quiet)                      # the journey keeper's run, already under way
    ended = GenState("current")
    ended.quiet = True
    shell.bridge.generate_changed.emit(ended)
    assert seen == [] and wiz.generating
    shell.bridge.generate_changed.emit(GenState("running", "Counting words", 1, 10))
    shell.bridge.generate_changed.emit(GenState("current"))
    assert seen == ["generated"]


# --- a language switch, a second pass (AD-9, AD-10) ----------------------------------------------------------------------- #
def test_a_language_switch_keeps_the_choices_that_dont_depend_on_it(make):
    wiz, _shell, api, settings, _m = make(miner=FakeMiner(miner_look("ready", "3.7")))
    go_to(wiz, "shows")
    QTest.mouseClick(wiz.page.covers.switch, Qt.MouseButton.LeftButton)          # covers off
    go_to(wiz, "cards")
    assert wait_until(lambda: wiz.page.look is not None)
    QTest.mouseClick(wiz.page.make, Qt.MouseButton.LeftButton)                   # card making off
    while wiz.index:
        wiz.back()
    wiz.pages[0].channel.choose("zh", user=True)
    wiz.next()
    assert wiz.language == "zh"
    assert wiz.pages[2].covers.switch.isChecked() is False
    assert wiz.pages[4].make.isChecked() is False
    assert wiz.passed == {0, 2}                                    # What you know and Card order: for zh, not yet


def test_a_second_pass_through_what_you_know_syncs_again_only_for_other_decks(make):
    wiz, _shell, api, *_ = make()
    wiz.next()
    assert wait_until(lambda: wiz.anki is not None)
    wiz.next()
    assert wait_until(lambda: len(api.synced) == 1)
    wiz.back()
    wiz.next()                                                     # the same decks: no second sync
    QApplication.processEvents()
    assert len(api.synced) == 1
    wiz.back()
    QTest.mouseClick(wiz.page.chips["Kanji Practice"], Qt.MouseButton.LeftButton)
    wiz.next()
    assert wait_until(lambda: len(api.synced) == 2)


# --- what the bar alone said (AD-11) -------------------------------------------------------------------------------------- #
def test_a_failed_save_is_said_in_the_wizard_too(make):
    class Failing(FakeApi):
        def save(self, settings_service, page, answers, language):
            raise OSError("settings.json is held by another program")
    wiz, shell, *_ = make(api=Failing())
    wiz.next()
    assert wiz.say_line.text() == "settings.json is held by another program" and not wiz.say_line.isHidden()
    assert shell.bar == ["settings.json is held by another program"]


def test_a_first_sync_that_cant_start_is_said_in_the_wizard(make):
    class NoSync(FakeApi):
        def first_sync(self, registry, settings, language, decks, on_end, automation=None):
            raise RuntimeError("Anki's add-on didn't answer")
    wiz, *_ = make(api=NoSync())
    wiz.next()
    assert wait_until(lambda: wiz.anki is not None)
    wiz.next()
    assert wait_until(lambda: wiz.say_line.text() == "Anki's add-on didn't answer")


def test_the_first_syncs_result_is_said_even_after_another_line(make, monkeypatch):
    held = []

    class Later(FakeApi):
        def first_sync(self, registry, settings, language, decks, on_end, automation=None):
            held.append(on_end)
            return object()
    monkeypatch.setattr(W, "sync_line", lambda result: "Anki: 214 words you know added")
    wiz, *_ = make(api=Later())
    wiz.next()
    assert wait_until(lambda: wiz.anki is not None)
    wiz.next()
    assert wait_until(lambda: held)
    wiz.say(S.SAMPLES_NONE)                                        # another line came since
    held[0]("the sync's result")
    assert wait_until(lambda: wiz.say_line.text() == "Anki: 214 words you know added")


def test_a_door_that_cant_open_is_said_in_the_wizard(make, monkeypatch):
    from app.qt import strings

    def broken(_shell):
        raise OSError("the importer's window couldn't be made")
    door = windows.Opener("migaku", "Migaku", "Import from Migaku", lambda _s, _l: True, broken)
    api = FakeApi(anki={"open": False, "say": None, "decks": [], "preselected": []})
    wiz, shell, *_ = make(api=api)
    monkeypatch.setattr(windows, "launch", REAL_LAUNCH)
    monkeypatch.setattr(wiz, "door", lambda name: door)
    wiz.open_door("migaku")
    said = strings.OPEN_FAILED.format(name="Migaku", why="the importer's window couldn't be made")
    assert wiz.say_line.text() == said and shell.bar == [said]


# --- the samples' second press (AD-13) --------------------------------------------------------------------------------- #
def test_a_second_press_on_samples_waits_for_the_first(make):
    held = []

    class Slow(FakeApi):
        def add_samples(self, language):
            self.calls.append(("samples", language))
            import time
            while not held:
                time.sleep(0.01)
            return 2
    api = Slow()
    wiz, *_ = make(api=api)
    go_to(wiz, "shows")
    page = wiz.page
    QTest.mouseClick(page.btn_samples, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: ("samples", "ja") in api.calls)
    # one copy at a time: never greyed (round 8 row 45) — its arc turns, and a press meanwhile copies nothing more
    assert page.btn_samples.isEnabled() and qpress.arc(page.btn_samples) is not None
    QTest.mouseClick(page.btn_samples, Qt.MouseButton.LeftButton)
    held.append(True)
    assert wait_until(lambda: qpress.arc(page.btn_samples) is None)
    assert api.calls.count(("samples", "ja")) == 1


# --- page 6's counting (AD-14, the intent keeper's IK-18) ------------------------------------------------------------------ #
def test_counting_asks_again_less_and_less_often_and_never_while_minimised(make, monkeypatch):
    waits = []
    api = FakeApi(numbers=None)
    wiz, shell, *_ = make(api=api)
    monkeypatch.setattr(wiz, "later", lambda ms, fn: waits.append((ms, fn)))       # the wizard's own timer
    go_to(wiz, "level")
    assert wait_until(lambda: len(waits) == 1)
    for _ in range(5):
        _ms, fn = waits[-1]
        fn()
        assert wait_until(lambda n=len(waits): len(waits) == n + 1)
    assert [ms for ms, _fn in waits] == [3000, 6000, 12000, 24000, 30000, 30000]
    asked = api.calls.count(("level_numbers", "ja"))
    monkeypatch.setattr(shell, "isMinimized", lambda: True)
    waits[-1][1]()
    QApplication.processEvents()
    assert api.calls.count(("level_numbers", "ja")) == asked and len(waits) == 7      # minimised: not asked


def test_counting_asks_again_when_the_indexer_ran(make, monkeypatch):
    api = FakeApi(numbers=None)
    wiz, shell, *_ = make(api=api)
    monkeypatch.setattr(wiz, "later", lambda ms, fn: None)
    go_to(wiz, "level")
    assert wait_until(lambda: ("level_numbers", "ja") in api.calls)
    asked = api.calls.count(("level_numbers", "ja"))
    api.numbers = NUMBERS
    shell.bridge.indexed.emit("zh")                                 # another language's: nothing
    shell.bridge.indexed.emit("ja")
    assert wait_until(lambda: wiz.page.numbers is not None)
    assert api.calls.count(("level_numbers", "ja")) == asked + 1


# --- S19 on page 5 (AD-15) -------------------------------------------------------------------------------------------------- #
def test_the_same_look_sets_no_tooltip_again(make):
    wiz, *_ = make()
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    tips = []
    page.btn_install.setToolTip = lambda tip: tips.append(tip)
    page.show_look(miner_look("missing"))
    page.show_look(miner_look("missing"))
    assert tips == []
    page.show_look(miner_look("too-old", "3.2"))
    assert tips == [S.UPDATE_MINER_TIP]


# --- the intent keeper's page rows (IK-14, IK-20) ---------------------------------------------------------------------------- #
def test_card_order_without_junban_offers_no_control_and_enter_is_skip(make):
    wiz, _shell, api, settings, _m = make(data={"enable_junban": False})
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: not wiz._anki_looking)
    assert page.controls.isHidden() and not page.off_line.isHidden() and wiz.btn_next.isHidden()
    assert page.off_line.text() == S.ORDER_OFF
    settings.calls.clear()
    wiz.enter()
    assert W.PAGES[wiz.index] == "cards" and settings.calls == []


def test_card_order_when_junbans_module_is_absent_offers_no_control(make, monkeypatch):
    monkeypatch.setattr(windows, "module_present", lambda name: name != "junban")
    wiz, *_ = make()
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: not page.off_line.isHidden())
    assert page.controls.isHidden() and not page.next_offered()


def test_card_order_says_when_automatic_actions_are_off(make):
    wiz, *_ = make(data={"logic": {"automation": False}})
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: not page.controls.isHidden())
    assert not page.automation_line.isHidden() and page.automation_line.text() == S.ORDER_AUTOMATION_OFF
    other, *_ = make()
    go_to(other, "order")
    assert wait_until(lambda: not other.page.controls.isHidden())
    assert other.page.automation_line.isHidden()


# --- upgrading from 2.x (WZ-8 / P4.1-3, Sonic 2026-10-15) ------------------------------------------------------------- #
class UpgradeApi(FakeApi):
    """The real rules for who is upgrading and where each page starts; the pages-seen write recorded."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.real = pytest.importorskip("app.services.setup_wizard")

    def upgrading(self, settings):
        return self.real.upgrading(settings)

    def preselect(self, settings, language):
        return self.real.preselect(settings, language)

    def seen(self, settings_service):
        self.calls.append(("seen",))
        return self.real.seen(settings_service)


# Surasura 2.5's settings as the import brings them over: set up there, Chinese, its own decks and later choice.
FROM_2X = {"onboarding_completed": True, "target_language": "zh", "anki_sync_decks": {"zh": ["中文::新词"]},
           "junban_deck": "中文::新词", "junban_later_tag": True, "junban_later_suspend": True,
           "logic": {"selection": {"auto": False, "band": "rare"}}}


def test_a_2x_profile_sees_every_page_with_its_choices_and_what_came_over_in_one_line(make):
    wiz, _shell, _api, _settings, _m = make(api=UpgradeApi(), data=FROM_2X)
    assert wiz.upgrading and wiz.language == "zh"
    assert wiz.pages[0].line.text() == S.UPGRADE_LINE and not wiz.pages[0].line.isHidden()
    assert wiz.pages[0].answers() == {"language": "zh"}
    known = wiz.pages[1]
    assert known.line.text() == S.UPGRADE_KNOWN_LINE
    assert known.channel.choice("fresh").title == S.KEEP_CAME_OVER, "nothing to start fresh from: the words came over"
    assert wiz.pages[2].line.text() == S.UPGRADE_SHOWS_LINE and not wiz.pages[2].line.isHidden()
    assert wiz.pages[3].answers()["later"] == "aside" and wiz.pages[3].answers()["keep_in_order"] is True
    assert wiz.pages[5].answers()["automatic"] is False


def test_a_new_profile_keeps_the_new_users_words(make):
    wiz, *_ = make(api=UpgradeApi(), data={})
    assert not wiz.upgrading
    assert wiz.pages[0].line.text() == S.LANGUAGE_LINE and wiz.pages[1].line.text() == S.KNOWN_LINE
    assert wiz.pages[1].channel.choice("fresh").title == S.START_FRESH
    assert wiz.pages[2].line.isHidden()


def test_finish_later_on_an_upgrade_records_the_pages_seen_and_nothing_else(make):
    # Why: shown once — closing keeps 2.x's settings as they are, and the wizard never comes back by itself
    wiz, _shell, api, settings, _m = make(api=UpgradeApi(), data=FROM_2X)
    QTest.mouseClick(wiz.btn_later, Qt.MouseButton.LeftButton)
    assert settings.calls == [{"setup_seen": "3.0"}]
    assert api.calls.count(("seen",)) == 1 and ("finish",) not in api.calls


def test_the_window_quitting_under_an_upgrades_wizard_records_the_pages_seen_once(make):
    wiz, shell, api, settings, _m = make(api=UpgradeApi(), data=FROM_2X)
    shell.closing.emit()
    shell.closing.emit()
    assert settings.calls == [{"setup_seen": "3.0"}]
    wiz.finish_later()
    assert api.calls.count(("seen",)) == 1


def test_finishing_an_upgrade_writes_finish_not_a_second_seen(make):
    wiz, _shell, api, settings, _m = make(api=UpgradeApi(numbers=NUMBERS), data=FROM_2X)
    go_to(wiz, "level")
    wiz.skip()                                                     # *Skip* on the last page finishes setup
    assert ("finish",) in api.calls and ("seen",) not in api.calls


def test_finish_later_on_a_new_profile_records_nothing(make):
    wiz, _shell, api, settings, _m = make(api=UpgradeApi(), data={})
    wiz.finish_later()
    assert settings.calls == [] and ("seen",) not in api.calls


# --- review round 2 (R2-1, R2-3) ------------------------------------------------------------------------------------------ #
OPEN_LOOK = {"open": True, "say": None, "decks": list(DECKS), "preselected": ["日本語::Mining"]}


def test_card_order_coming_up_when_anki_answers_takes_no_press_aimed_before_it(make):
    # Why: the consent switch appears with Anki's late answer; a press landing then would save it unseen (R2-1)
    api = FakeApi(anki={"open": False, "say": None, "decks": [], "preselected": []})
    wiz, _shell, api, settings, _m = make(api=api)
    go_to(wiz, "order")
    settle(wiz)
    assert wiz.btn_next.isHidden()
    settings.calls.clear()
    wiz._anki_looked(dict(OPEN_LOOK), wiz._anki_seq, wiz.language)       # Anki answers: the controls come up
    assert not wiz.btn_next.isHidden()
    QTest.mouseClick(wiz.btn_next, Qt.MouseButton.LeftButton)
    QTest.keyClick(wiz, Qt.Key.Key_Return)
    assert W.PAGES[wiz.index] == "order" and settings.calls == [], "nothing saved before the page was seen"
    settle(wiz)
    QTest.mouseClick(wiz.btn_next, Qt.MouseButton.LeftButton)
    assert W.PAGES[wiz.index] == "cards" and "junban_auto_actions" in settings.calls[-1]


def test_saved_decks_the_open_anki_lacks_are_kept_by_next(make):
    # Why: another Anki profile open (or a deck renamed) must not rewrite the saved decks or 順's deck (R2-3)
    pre = {"language": {"language": "ja"}, "known": {"how": "anki", "decks": ["日本語::Mining", "旧デッキ::文"]},
           "shows": {"covers": True},
           "order": {"keep_in_order": False, "deck": "旧デッキ::文", "later": "leave"},
           "cards": {"make_cards": True, "open_anki": False}, "level": {"automatic": True, "band": None}}
    wiz, *_ = make(api=FakeApi(anki=dict(OPEN_LOOK), preselect=pre))
    go_to(wiz, "known")
    wiz.page.entered()
    assert wait_until(lambda: not wiz._anki_looking, 2.0)
    assert wiz.page.answers()["decks"] == ["日本語::Mining", "旧デッキ::文"]
    go_to(wiz, "order")
    assert wiz.page.answers()["deck"] == "旧デッキ::文"


def test_an_upgrader_with_anki_closed_is_offered_to_keep_what_came_over(make):
    # IK2-3: the import already brought the words; with Anki closed the stand-in is never an importer
    api = UpgradeApi(anki={"open": False, "say": None, "decks": [], "preselected": []})
    wiz, *_ = make(api=api, data=FROM_2X)
    go_to(wiz, "known")
    wiz.page.entered()
    assert wait_until(lambda: not wiz._anki_looking, 2.0)
    assert wiz.page.answers() == {"how": "fresh", "decks": []}


# --- round 8 row 45: every press reacts at once ------------------------------------------------------------------- #
def test_check_again_paints_its_arc_before_anki_is_looked_at_until_the_answer(make, monkeypatch):
    # *Check again* kept the last look (`self.anki`), so *Checking…* never painted: nothing showed until Anki
    # answered. Its arc now turns from the press, painted before the look is handed over, until the look lands.
    from tests.qt.press_handover import HandOver, arc_turning
    api = FakeApi(anki={"open": False, "say": None, "decks": [], "preselected": []})
    wiz, *_ = make(api=api)
    wiz.next()
    page = wiz.page
    assert wait_until(lambda: wiz.anki is not None and not page.closed_part.isHidden() and wiz.settled())
    assert wait_until(lambda: not page.btn_check.visibleRegion().isEmpty())
    handed = HandOver(monkeypatch, page.btn_check, lambda: arc_turning(page.btn_check))
    QTest.mouseClick(page.btn_check, Qt.MouseButton.LeftButton)
    look = handed.at("anki_look")
    assert look.shown and look.painted >= 1 and page.btn_check.isEnabled()
    assert wait_until(lambda: not wiz._anki_looking and not arc_turning(page.btn_check))


# --- Michi-C (A7B-1…A7B-3): the shows behind the deck's new cards, on the Card order page ----------------------------- #
class BehindApi(FakeApi):
    def __init__(self, record, **kw):
        super().__init__(**kw)
        self.record, self.asked = record, []

    def backlog_shows(self, language, settings, deck):
        self.asked.append((language, deck))
        return self.record


class GiveMoves:
    def __init__(self):
        self.given = []

    def refused(self):
        return None

    def _give(self, ticket, command, toast=True):
        self.given.append((ticket.text, command("label")))
        return len(self.given)


class PlaceWriter:
    def place(self, ids, where, label=None):
        return ("place", list(ids), where)


BEHIND = {"cards": 2300, "all": 2300, "id": "x", "shows": [
    {"title": "月影の旅人", "cards": 2000, "ids": [41, 42], "state": "waiting"},
    {"title": "夜市の灯", "cards": 260, "ids": [], "state": "in"},
    {"title": "海辺の約束", "cards": 40, "ids": [], "state": "away"}]}


def test_michi_c_card_order_says_where_the_new_cards_came_from_and_add_them_places_the_waiting_ones(make):
    """Setup's Card order (A7B-3): once Anki is open and a deck chosen, the page reads where the deck's new cards came
    from (on a worker, the page's own deck) and says it in one line; *Add them* places the shows waiting in New arrivals
    through the window's writer (New arrivals' own *Soon*, one Undo) — the one path *Needs you* uses."""
    api = BehindApi(BEHIND)
    wiz, shell, api, settings, _m = make(api=api)
    shell.moves, shell.services.writer = GiveMoves(), PlaceWriter()
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: page.btn_behind.isVisible())
    assert api.asked[-1] == ("ja", "日本語::Mining")
    assert page.behind_line.text() == ("Your 2,300 new cards come from 3 shows; 2 are on this PC. "
                                       "1 of them waits in New arrivals.")
    assert page.btn_behind.toolTip() == S.BEHIND_ADD_TIP
    asked = len(api.asked)
    page.anki_changed()                                            # Anki looked at again: the same deck, no new read
    page._show()
    assert not wait_until(lambda: len(api.asked) > asked, 0.5)
    QTest.mouseClick(page.btn_behind, Qt.MouseButton.LeftButton)
    assert shell.moves.given == [(strings.NEEDS_SHOWS_ADDED_ONE, ("place", [41, 42], "soon"))]
    assert page.behind_line.text() == S.BEHIND_ADDED and page.btn_behind.isHidden()


def test_michi_c_card_order_with_nothing_waiting_says_so_without_a_button_and_with_no_source_says_nothing(make):
    record = {**BEHIND, "shows": [dict(s, ids=[], state="in" if s["state"] == "waiting" else s["state"])
                                  for s in BEHIND["shows"]]}
    wiz, shell, api, settings, _m = make(api=BehindApi(record))
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: page.behind_line.isVisible() and page.behind_line.text() != S.BEHIND_LOOKING)
    assert page.behind_line.text().endswith(S.BEHIND_IN) and page.btn_behind.isHidden()
    wiz2, _shell2, _api2, _s2, _m2 = make(api=BehindApi(None))       # no Anki Miner card / Anki closed: no line
    go_to(wiz2, "order")
    assert wait_until(lambda: wiz2.page.behind_line.isHidden() and _api2.asked)
    assert wiz2.page.btn_behind.isHidden()


def test_michi_c_add_them_with_no_writer_or_another_languages_library_adds_nothing_and_says_so(make):
    """The review's SHOULD 10: the window's bar is under the page, so the page itself says when nothing was added; ids
    of one language's library are never placed in another's."""
    from app.qt import needs as qneeds
    wiz, shell, api, settings, _m = make(api=BehindApi(BEHIND))
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: page.btn_behind.isVisible())
    QTest.mouseClick(page.btn_behind, Qt.MouseButton.LeftButton)          # the stand-in window has no writer
    assert page.behind_line.text() == S.BEHIND_NOT_ADDED and page.btn_behind.isVisible()
    shell.moves, shell.services.writer = GiveMoves(), PlaceWriter()
    shell.language = "zh"
    assert qneeds.give_shows(shell, [41], 1, "ja") is None and shell.moves.given == []
    assert qneeds.give_shows(shell, [41], 1, "zh") is not None


def test_michi_c_a_look_that_found_anki_closed_is_asked_again_when_anki_answers(make):
    """The review's NIT 13: Anki closed between the deck list and the read — no line; once Anki answers again the page
    asks again (never stuck on the failed look until the page is entered again)."""
    api = BehindApi(None)
    wiz, shell, api, settings, _m = make(api=api)
    go_to(wiz, "order")
    page = wiz.page
    assert wait_until(lambda: api.asked and page.behind_line.isHidden())
    api.record = BEHIND
    page.anki_changed()
    assert wait_until(lambda: page.btn_behind.isVisible())


def test_the_last_page_offers_the_discord_in_one_tipped_line_opened_in_the_browser(make):
    """3.0: *Questions? Join us on Discord* — one link on the last page, hover-tipped, the invite opened on a worker
    (a link the browser opens, never a call of the app's); nothing written."""
    from app.qt import settings_strings
    wiz, _shell, _api, settings, _miner = make()
    go_to(wiz, "level")
    page = wiz.page
    assert page.discord.text() == S.DISCORD and page.discord.toolTip() == S.DISCORD_TIP
    assert page.discord.objectName() == "wizlink" and page.discord.isVisibleTo(page)
    settings.calls.clear()
    QTest.mouseClick(page.discord, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: wiz.launched == [settings_strings.DISCORD_URL])
    assert settings.calls == []


# --- the review's round (A8B-3, 4, 5, 10) ------------------------------------------------------------------------- #
def _youtube_page(make, monkeypatch, **data):
    wiz, shell, *_ = make(data=dict({"enable_youtube_transcripts": True, "youtube_risk_acknowledged": True}, **data))
    fetch = FakeFetch()
    monkeypatch.setattr(W, "_youtube_fetcher", lambda: fetch)
    go_to(wiz, "shows")
    page = wiz.page
    page.entered()
    assert wait_until(lambda: not page.btn_youtube.isHidden())
    page.btn_youtube.click()
    return wiz, shell, page, fetch


def test_a_video_already_in_the_library_says_so_never_paste_a_link(make, monkeypatch):
    """A8B-3: the fetch wrote nothing new and said nothing (the video was brought in before): the line says it was
    already in the library — never "Paste a YouTube link first"."""
    wiz, _shell, page, fetch = _youtube_page(make, monkeypatch)
    page.links.setPlainText("https://www.youtube.com/watch?v=eFwn9e8IYsI")
    wiz.next()
    fetch.ended([], [])
    assert wiz.say_line.text() == S.YOUTUBE_FAILED.format(why=S.YOUTUBE_HAD)


def test_links_pasted_while_the_last_ones_still_come_stay_and_are_said(make, monkeypatch):
    """A8B-4: Next with new links while the last fetch still runs: nothing fetched twice, the links stay in the box,
    the page says why."""
    wiz, _shell, page, fetch = _youtube_page(make, monkeypatch)
    page.links.setPlainText("https://www.youtube.com/watch?v=eFwn9e8IYsI")
    wiz.next()
    wiz._load_stop()                                               # Stop: on to the sorting, the fetch still running
    wiz._load, wiz.covered = None, None                            # (the sorting done: page 3 again)
    page.links.setPlainText("https://www.youtube.com/watch?v=7nlUSMQKRKQ")
    wiz.next()
    assert len(fetch.calls) == 1 and page.refused_line.text() == S.YOUTUBE_BUSY
    assert page.links.toPlainText() == "https://www.youtube.com/watch?v=7nlUSMQKRKQ"


def test_files_the_writer_refuses_stay_listed_and_the_page_says_why(make, tmp_path):
    """A8B-5: the library can't be saved now (+ Add's writer refuses): the picked files stay listed, the page says
    why, and setup stays on page 3 — nothing is dropped unsaid."""
    wiz, shell, *_ = make()
    adder = shell.adder = FakeAdder()
    adder.add_files = lambda paths, **_kw: None
    go_to(wiz, "shows")
    page = wiz.page
    picked = [str(tmp_path / "ぼっち・ざ・ろっく！ 第01話.ja.srt")]
    wiz.pick_files_dialog = lambda _title, _start: picked
    page.btn_file.click()
    wiz.next()
    assert page.files == [os.path.normpath(picked[0])] and page.refused_line.text() == S.FILES_NOT_ADDED
    assert W.PAGES[wiz.index] == "shows"


def test_videos_that_landed_during_the_scan_are_sorted_though_the_scan_found_nothing(make, monkeypatch):
    """A8B-10: the fetch landed while the folders were still read, and the folders held nothing: the sorting still
    comes up for the videos (never the page with them unsorted)."""
    wiz, _shell, page, fetch = _youtube_page(make, monkeypatch)
    wiz.youtube_came = 1
    sorted_ = []
    monkeypatch.setattr(wiz, "_load_sort", lambda: sorted_.append(True))
    wiz._load_begin()
    wiz._load_scanned({"ids": []})
    assert sorted_ == [True]


def test_a_scan_that_found_nothing_waits_for_the_youtube_videos_still_coming(make, monkeypatch):
    """Mutant M14: folders read and empty while YouTube's videos are still coming — the load screen stays, at its
    YouTube step (never the page with the videos about to land unsorted)."""
    wiz, *_ = make(data={"enable_youtube_transcripts": True, "youtube_risk_acknowledged": True})
    go_to(wiz, "shows")
    wiz.fetching = {"links": 1}
    wiz._load_begin()
    wiz._load_scanned({"ids": []})
    assert wiz.covered is not None and wiz._load["step"] == "youtube"
    assert wiz.covered.task.text() == S.LOAD_YOUTUBE
