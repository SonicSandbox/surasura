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
    QTest.qWait(300)                                       # the write lands on the writer's worker
    assert wait_until(lambda: main.services.settings.get().get("target_language") == "zh")
    QTest.qWait(100)
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
def test_the_settings_tab_lists_every_door_wired_tipped_and_named(main):
    row = main.launchers
    assert set(row.buttons) == {op.name for op in windows.OPENERS}
    assert row.parentWidget() is main.page_widgets["settings"]
    for op in windows.OPENERS:
        b = row.buttons[op.name]
        assert b.text() == op.label and b.toolTip() == op.tip
    found, _walked = problems(main)
    assert found == []


def test_a_door_shows_only_while_its_rule_and_its_module_say_so(main, monkeypatch):
    switch = {"on": False}
    probe = windows.Opener("probe", "Probe", "Opens the probe", lambda s, lang: switch["on"] and lang == "ja",
                           lambda s: windows.show(s, "probe", Probe))
    absent = windows.Opener("ghost", "Ghost", "A module that isn't there", lambda s, lang: True,
                            lambda s: None, "no_such_module_w34")
    present = windows.Opener("koe", "Koe", "A module that is there", lambda s, lang: True, lambda s: None, "junban")
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + [probe, absent, present])
    page = main.page_widgets["settings"]
    row = windows.launchers(main, page)
    assert row.buttons["probe"].isHidden() and row.buttons["ghost"].isHidden()
    assert not row.buttons["koe"].isHidden() or not windows.module_present("junban")
    switch["on"] = True
    main.show_tab("current")
    main.show_tab("settings")                              # asked again each time the page shows
    assert not row.buttons["probe"].isHidden() and row.buttons["ghost"].isHidden()


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
