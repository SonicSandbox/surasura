"""The ported windows' base (W3.4 row 1; `app/qt/windows.py`): the secondary window, one of a kind, the language
switch (🧭 IK-12), the openers' registry and the Settings tab's list of doors (until W3.3 / W3.2: IK-16).

What a wrong answer would cost: two windows of one kind writing the same files; a window still writing the old
language's files once the main window switched (inv: the Anki window's defect 3), or a write cut by the switch; a door
shown for a module that isn't there (a dead button) or a door hidden for one that is; a door that fails silently; a
window whose Esc closes the main window.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.qt import shell, strings, windows
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)
    # Every settings write lands while the test root is still set: a writer finishing after the test would take the
    # settings lock in the REAL local data folder (it made %LOCALAPPDATA%\Houseki\Surasura\<key> once).
    assert services.settings.flush(10)


class Probe(windows.SecondaryWindow):
    """A window that records its re-reads."""

    def __init__(self, shell_window, language=None):
        super().__init__(shell_window, "Probe", language)
        self.reads = []

    def language_changed(self, language):
        self.reads.append(language)


def _switch(main, language):
    main.services.settings.set({"target_language": language})


# --- the secondary window ------------------------------------------------------------------------------------------ #
def test_a_secondary_window_is_its_own_window_over_the_main_one(main):
    w = windows.show(main, "probe", Probe)
    assert w.parentWidget() is main and w.isWindow() and w.isVisible()
    assert w.windowTitle() == strings.SECONDARY_TITLE.format(name="Probe") == "Probe — Surasura"
    assert w.language == "ja"


def test_esc_and_back_close_it_and_never_the_main_window(main):
    w = windows.show(main, "probe", Probe)
    closed = []
    w.closed.connect(lambda: closed.append(True))
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert closed == [True] and main.isVisible()
    w = windows.show(main, "probe", Probe)
    QTest.mouseClick(w, Qt.MouseButton.BackButton)
    assert windows.opened(main, "probe") is None and main.isVisible()


def test_one_window_of_a_kind_kept_and_raised(main):
    made = []

    def make(s):
        made.append(1)
        return Probe(s)
    a = windows.show(main, "probe", make)
    b = windows.show(main, "probe", make)
    assert a is b and made == [1]
    a.close()
    QApplication.processEvents()
    c = windows.show(main, "probe", make)
    assert c is not a and made == [1, 1] and windows.opened(main, "probe") is c
    other = windows.show(main, "other", make)              # another kind is its own window
    assert other is not c


def test_the_status_line_repaints_only_when_its_words_change(main):
    w = windows.show(main, "probe", Probe)
    assert not w.status.isVisibleTo(w)
    w.say("Added: 2")
    w.say("Added: 2")
    assert w.status.text() == "Added: 2" and w.status.isVisibleTo(w) and w.status_paints == 1
    w.say("")
    assert not w.status.isVisibleTo(w) and w.status_paints == 2


# --- the language switch (🧭 IK-12) --------------------------------------------------------------------------------- #
def test_an_idle_window_follows_the_main_windows_language(main):
    w = windows.show(main, "probe", Probe)
    _switch(main, "zh")
    assert wait_until(lambda: w.reads == ["zh"])
    assert w.language == "zh"


def test_a_switch_during_a_write_waits_for_it_and_its_result_goes_to_the_bar(main):
    w = windows.show(main, "probe", Probe)
    w.begin_write()
    _switch(main, "zh")
    assert wait_until(lambda: w._language_waiting == "zh")    # the write landed (the writer's worker) and was heard
    assert w.reads == [] and w.language == "ja"            # never cut: still the language it writes for
    w.end_write("Removed: 1, kept in the trash folder")
    assert w.reads == ["zh"] and w.language == "zh"
    assert main.bar_line.full() == "Removed: 1, kept in the trash folder"


def test_a_write_with_no_switch_waiting_leaves_the_bar_alone(main):
    w = windows.show(main, "probe", Probe)
    before = main.bar_line.full()
    w.begin_write()
    w.end_write("Added: 1")
    assert main.bar_line.full() == before and w.reads == []


def test_a_closed_window_hears_no_switch(main):
    w = windows.show(main, "probe", Probe)
    reads = w.reads
    w.close()
    QApplication.processEvents()
    _switch(main, "zh")
    QTest.qWait(300)
    assert reads == []


# --- the openers and the Settings tab's list (IK-16) ---------------------------------------------------------------- #
def _settings_row(main):
    # The Settings tab's list of doors. Until the shell's own hook lands (its owner's step), the test builds the row on
    # the tab's page itself, as `ShellWindow._page("settings")` will.
    return windows.launchers(main, main.page_widgets["settings"])


def test_the_settings_tab_lists_every_door_wired_tipped_and_named(main):
    row = _settings_row(main)
    assert set(row.buttons) == {op.name for op in windows.OPENERS}
    assert row.parentWidget() is main.page_widgets["settings"]
    for op in windows.OPENERS:
        b = row.buttons[op.name]
        assert b.text() == op.label and b.toolTip() == op.tip
    found, _walked = problems(main)
    assert found == []


def test_row_ones_doors_open_their_windows_once(main):
    row = _settings_row(main)
    main.show_tab("settings")
    for name in ("frequency-lists", "sentence-dictionary"):
        row.buttons[name].click()
        first = windows.opened(main, name)
        assert first is not None and first.isVisible()
        row.buttons[name].click()
        assert windows.opened(main, name) is first


def test_a_door_shows_only_while_its_rule_and_its_module_say_so(main, monkeypatch):
    switch = {"on": False}
    probe = windows.Opener("probe", "Probe", "Opens the probe", lambda s, lang: switch["on"] and lang == "ja",
                           lambda s: windows.show(s, "probe", Probe))
    absent = windows.Opener("ghost", "Ghost", "A module that isn't there", lambda s, lang: True,
                            lambda s: None, "no_such_module_w34")
    present = windows.Opener("koe", "Koe", "A module that is there", lambda s, lang: True, lambda s: None, "junban")
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + [probe, absent, present])
    # Looked for afresh: an earlier test's look may still be in `_LOOKING` (its window closed before the worker
    # answered), and this one would then never ask for its modules (GitHub's core shard, 2026-10-20).
    monkeypatch.setattr(windows, "_FOUND", {})
    monkeypatch.setattr(windows, "_LOOKING", set())
    page = main.page_widgets["settings"]
    row = windows.launchers(main, page)
    assert row.buttons["probe"].isHidden() and row.buttons["ghost"].isHidden()
    assert wait_until(lambda: {"no_such_module_w34", "junban"} <= set(windows._FOUND))
    assert row.buttons["ghost"].isHidden()
    assert row.buttons["koe"].isHidden() != windows.module_present("junban")
    switch["on"] = True
    main.show_tab("current")
    main.show_tab("settings")                              # asked again each time the page shows
    assert not row.buttons["probe"].isHidden() and row.buttons["ghost"].isHidden()


# --- the fix round: the doors follow the settings (IK-20, IK-25), a refused close (AD1-11), the bar (AD1-3) -------- #
def _doors(monkeypatch, main, extra):
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + extra)
    return windows.launchers(main, main.page_widgets["settings"])


def test_with_the_settings_tab_open_a_door_follows_the_language_and_a_switch(main, monkeypatch):
    jiten = windows.Opener("jiten", "Jiten", "Japanese only", lambda s, lang: lang == "ja", lambda s: None)
    koe = windows.Opener("koe", "Koe", "Only when revealed", lambda s, lang: "enable_koe" in s, lambda s: None)
    main.show_tab("settings")
    row = _doors(monkeypatch, main, [jiten, koe])
    assert not row.buttons["jiten"].isHidden() and row.buttons["koe"].isHidden()
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: row.buttons["jiten"].isHidden())          # no tab switch needed
    main.services.settings.set({"enable_koe": True})
    assert wait_until(lambda: not row.buttons["koe"].isHidden())


def test_a_settings_write_that_changes_no_door_repaints_none(main, monkeypatch):
    jiten = windows.Opener("jiten", "Jiten", "Japanese only", lambda s, lang: lang == "ja", lambda s: None)
    main.show_tab("settings")
    row = _doors(monkeypatch, main, [jiten])
    before = row.paints
    main.services.settings.set({"enable_no_door_w34": True})           # an enable_ key no door changes with
    QTest.qWait(400)
    main.show_tab("current")
    main.show_tab("settings")                                          # the page shown again: nothing changed
    assert row.paints == before


def test_the_modules_are_looked_for_once_and_never_on_the_windows_thread(main, monkeypatch):
    import threading
    gui = threading.current_thread()
    looks = []
    real = windows.module_present

    def present(name):
        looks.append((name, threading.current_thread() is gui))
        return real(name)
    monkeypatch.setattr(windows, "module_present", present)
    monkeypatch.setattr(windows, "_FOUND", {})
    monkeypatch.setattr(windows, "_LOOKING", set())
    ghost = windows.Opener("ghost", "Ghost", "x", lambda s, lang: True, lambda s: None, "no_such_module_w34")
    row = _doors(monkeypatch, main, [ghost])
    assert row.buttons["ghost"].isHidden()                             # hidden until the look says it's there
    assert wait_until(lambda: "no_such_module_w34" in windows._FOUND)
    for _ in range(3):
        main.show_tab("current")
        main.show_tab("settings")
    # each module a door names looked for once, on a worker (the rows' own doors name modules too)
    assert sorted(looks) == sorted({(op.module, False) for op in windows.OPENERS if op.module})
    assert row.buttons["ghost"].isHidden()
    seen = len(looks)
    again = windows.launchers(main, main.page_widgets["settings"])     # a row made after the look ended: no new look
    assert not wait_until(lambda: len(looks) > seen, timeout=1.0)          # (a second look would run on a worker)
    assert again.buttons["ghost"].isHidden()


def test_a_close_the_window_refuses_leaves_it_open_and_the_only_one_of_its_kind(main):
    class Busy(Probe):
        def closeEvent(self, event):
            event.ignore()                                             # refused before super(): the documented way
            super().closeEvent(event)
    w = windows.show(main, "busy", Busy)
    w.close()
    assert w.isVisible() and not w.gone
    assert windows.show(main, "busy", Busy) is w


def test_a_window_whose_main_window_is_gone_counts_as_gone(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    w = windows.show(win, "probe", Probe)
    win.close()
    win.deleteLater()
    from PyQt6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert w.gone
    w.end_write("Added: 1")                                            # a worker's late answer: no error
    windows.say_in_bar(win, "Added: 1")
    services.shutdown(0.5)
    # Every settings write lands while the test root is still set: a writer finishing after the test would take the
    # settings lock in the REAL local data folder (it made %LOCALAPPDATA%\Houseki\Surasura\<key> once).
    assert services.settings.flush(10)


def test_a_door_whose_rule_fails_stays_hidden(main, monkeypatch):
    def broken(_s, _lang):
        raise KeyError("enable_koe")
    op = windows.Opener("broken", "Broken", "x", broken, lambda s: None)
    assert windows.available(op, {}, "ja") is False


def test_a_door_that_cant_open_says_so_in_the_bar_never_a_box(main):
    def fail(_s):
        raise ImportError("No module named 'modules.koe.qt_window'")
    op = windows.Opener("koe", "Speech (Koe)", "x", lambda s, lang: True, fail)
    assert windows.launch(main, op) is None
    assert main.bar_line.full() == strings.OPEN_FAILED.format(name="Speech (Koe)",
                                                             why="No module named 'modules.koe.qt_window'")
    assert QApplication.activeModalWidget() is None


def test_a_link_or_a_folder_opens_in_the_users_own_program(monkeypatch, tmp_path):
    from PyQt6.QtGui import QDesktopServices
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    windows.open_url("https://jiten.moe/other")
    windows.open_url(str(tmp_path))
    assert opened[0].toString() == "https://jiten.moe/other"
    assert opened[1].isLocalFile() and opened[1].toLocalFile().rstrip("/\\").lower() == \
        str(tmp_path).replace("\\", "/").rstrip("/").lower()


# --- Fresh-U row 3 (2026-11-10): a scrolled body, never past the screen -------------------------------------------- #
class Tall(windows.SecondaryWindow):
    """A scrolled window of `n` real lines of text (a report's paragraphs), and a menu among them (順's deck)."""

    def __init__(self, shell_window, n=8):
        super().__init__(shell_window, "Tall", scroll=True)
        from PyQt6.QtWidgets import QComboBox, QLabel
        self.lines = []
        for k in range(n):
            self.add_line(k)
        self.deck = QComboBox(self)
        self.deck.addItems(["日本語::Mining", "Core 2k", "Kanji Practice"])
        self.deck.setToolTip("The deck")
        self.body.insertWidget(2, self.deck)
        self.QLabel = QLabel

    def add_line(self, k):
        from PyQt6.QtWidgets import QLabel
        line = QLabel(f"第{k + 1}話：Finishedに入れた「葬送のフリーレン」がCurrentに戻ってしまった", self)
        line.setMinimumHeight(40)
        self.body.addWidget(line)
        self.lines.append(line)


def _room(monkeypatch, height):
    from PyQt6.QtCore import QRect
    monkeypatch.setattr(windows, "screen_area", lambda win: QRect(0, 0, 1600, height))


def test_fresh_u_a_scrolled_window_with_room_opens_at_its_contents_height_with_no_bar(main, monkeypatch):
    # The adversary's S2: Qt caps a window at two-thirds of the screen when its least height is small — a body that
    # fits opened shorter with a bar beside free room. Its least height is its content's: it opens as a plain one does
    _room(monkeypatch, 2000)
    w = windows.show(main, "tall", Tall)
    QApplication.processEvents()
    assert w.body_scroll.verticalScrollBar().maximum() == 0
    assert w.body_scroll.height() >= w.body_scroll.widget().minimumSizeHint().height()


def test_fresh_u_a_scrolled_window_grows_as_its_content_lands_up_to_the_room_then_scrolls(main, monkeypatch):
    # S3: content that lands after the window shows (順's checks, Report's pages) grew a plain window; the scrolled one
    # grows the same, and only past the screen's room does its body scroll
    _room(monkeypatch, 1000)
    w = windows.show(main, "tall", lambda s: Tall(s, n=3))
    QApplication.processEvents()
    before = w.height()
    for k in range(3, 8):
        w.add_line(k)
    assert wait_until(lambda: w.height() > before, 2)
    assert w.body_scroll.verticalScrollBar().maximum() == 0
    for k in range(8, 40):
        w.add_line(k)
    assert wait_until(lambda: w.body_scroll.verticalScrollBar().maximum() > 0, 2)
    assert w.height() <= 1000


def test_fresh_u_the_wheel_over_an_unfocused_menu_scrolls_the_body_and_never_changes_the_deck(main, monkeypatch):
    # B1: once 順's body scrolled, a wheel over its deck menu changed the deck (and saved it); the menu takes the wheel
    # only once focused, and the body scrolls instead
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtGui import QWheelEvent
    _room(monkeypatch, 300)
    w = windows.show(main, "tall", lambda s: Tall(s, n=30))
    QApplication.processEvents()
    bar = w.body_scroll.verticalScrollBar()
    assert bar.maximum() > 0 and w.deck.property("wheelguard")
    picked = []
    w.deck.activated.connect(picked.append)
    w.deck.clearFocus()                                            # (a window's first focus may land on it)
    QApplication.processEvents()
    assert not w.deck.hasFocus()

    def wheel(target):
        e = QWheelEvent(QPointF(5, 5), QPointF(target.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(target, e)
    wheel(w.deck)
    assert w.deck.currentIndex() == 0 and picked == [] and bar.value() > 0
    w.deck.setFocus()
    QApplication.processEvents()
    if w.deck.hasFocus():                                          # (offscreen gives focus only to an active window)
        wheel(w.deck)
        assert w.deck.currentIndex() == 1


def test_fresh_u_a_plain_window_has_no_scrolled_body(main):
    w = windows.show(main, "probe", Probe)
    assert w.body_scroll is None and w.body.parentWidget() is w


def test_fresh_u_a_scrolled_body_is_never_wider_than_its_window_and_cut_at_the_right(main, monkeypatch):
    # Found by the work-count test: a window with an explicit least width (Report's) narrower than a row of its
    # buttons held the scrolled content at the row's width — the right of it (Save) off the window. The content takes
    # the viewport's width, its rows squeezed into it as an unscrolled body's were
    from PyQt6.QtWidgets import QHBoxLayout, QPushButton
    _room(monkeypatch, 900)

    def make(s):
        w = Tall(s, n=4)
        row = QHBoxLayout()
        for label in ("Leave the picture out", "Show me what's in it", "Make a zip instead", "Send report"):
            b = QPushButton(label, w)
            b.setToolTip(label)
            b.setMinimumWidth(260)
            row.addWidget(b)
        w.body.addLayout(row)
        w.setMinimumWidth(500)
        return w
    w = windows.show(main, "tall", make)
    QApplication.processEvents()
    assert w.body_scroll.widget().width() <= w.body_scroll.viewport().width()
