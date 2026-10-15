"""The frequency lists window (W3.4 row 1; `app/qt/frequency_lists_window.py`, the Tk Frequency List Manager ported).

What a wrong answer would cost: a list removed by Enter or Esc on the question; a removed list gone for good; another
language's lists shown or removed from this one; a list added over a same-named one with no copy; the window's thread
waiting on the disk; a control of the Tk window lost (inv-importers §5.1: each one is walked here).
"""
import os
import shutil

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import frequency_lists, path_utils
from app.qt import confirm, shell, strings, windows
from app.qt.frequency_lists_window import FrequencyListsWindow
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


@pytest.fixture
def ja_list(ja_resources_dir):
    return os.path.join(ja_resources_dir, "frequency_list_novels.csv")


@pytest.fixture
def zh_list(zh_resources_dir):
    return os.path.join(zh_resources_dir, "frequency_list_subtitles.csv")


def _open(main):
    w = windows.show(main, "frequency-lists", FrequencyListsWindow)
    assert wait_until(lambda: w.names is not None)
    return w


def _items(w):
    """The list's rows as shown (each list's own name)."""
    return [w.list.item(i).text() for i in range(w.list.count())]


def _trash(language):
    folder = os.path.join(path_utils.get_user_files_path(language), ".trash")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def _select(w, *names):
    w.list.clearSelection()
    for i in range(w.list.count()):
        if w.list.item(i).text() in names:
            w.list.item(i).setSelected(True)


def _card(w):
    cards = [c for c in w.findChildren(confirm.Confirm) if c.isVisible()]
    return cards[0] if cards else None


# --- every control of the Tk window (inv-importers §5.1) ------------------------------------------------------- #
def test_every_control_is_here_wired_tipped_and_named(main):
    w = _open(main)
    assert w.windowTitle() == "Frequency lists — Surasura"
    assert w.add_button.text() == strings.FREQ_ADD                   # §5.1 #5 "+ Add Frequency List(s)"
    assert w.remove_button.text() == strings.FREQ_REMOVE             # #6 "- Remove Selected"
    assert w.get_button.text() == strings.FREQ_GET                   # #2–#4: the instructions and the link
    assert w.credit_button.text() == strings.FREQ_CREDIT             # #9 the credit link
    assert w.list.toolTip() == strings.FREQ_LIST_TIP                 # #8 the note, as the list's tooltip
    found, walked = problems(w)
    assert walked >= 4 and found == []


def test_an_empty_list_says_how_to_fill_it(main):
    w = _open(main)
    assert _items(w) == [] and w.status.text() == strings.FREQ_EMPTY
    assert not w.remove_button.isEnabled()


def test_it_shows_this_languages_lists_only(main, ja_list, zh_list):
    frequency_lists.add(ja_list, "ja")
    frequency_lists.add(zh_list, "zh")
    w = _open(main)
    assert _items(w) == ["novels"]                        # its own name, as the report names it (IK-21)
    assert w.list.item(0).toolTip() == "frequency_list_ja_novels.csv"


def test_get_lists_and_the_credit_open_in_the_browser(main, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    w = _open(main)
    w.get_button.click()
    w.credit_button.click()
    assert opened == [strings.FREQ_GET_URL, strings.FREQ_CREDIT_URL] == ["https://jiten.moe/other",
                                                                         "https://github.com/mattias"]


# --- adding ------------------------------------------------------------------------------------------------------ #
def test_add_picks_several_files_and_lists_them(main, ja_list, tmp_path, monkeypatch):
    other = tmp_path / "Anime.csv"
    other.write_text("Word,Rank\n仲間,640\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([ja_list, str(other)], strings.FREQ_PICK_FILTER)))
    w = _open(main)
    w.add_button.click()
    assert wait_until(lambda: _items(w) == ["Anime", "novels"])
    assert wait_until(lambda: w.status.text() == strings.FREQ_ADDED.format(n=2))


def test_a_picker_cancelled_adds_nothing(main, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], "")))
    w = _open(main)
    w.add_button.click()
    QApplication.processEvents()
    assert _items(w) == [] and not w.busy()


def test_a_list_added_over_a_same_named_one_says_the_old_one_is_kept(main, ja_list, tmp_path):
    frequency_lists.add(ja_list, "ja")
    newer = tmp_path / "novels.csv"
    newer.write_text("Word,Rank\n冒険,1499\n", encoding="utf-8")
    w = _open(main)
    w.add([str(newer)])
    line = strings.FREQ_ADDED.format(n=1) + " · " + strings.FREQ_KEPT.format(name="novels")
    assert wait_until(lambda: w.status.text() == line)
    assert len(_trash("ja")) == 1


def test_a_list_that_cant_be_added_says_why(main, tmp_path):
    w = _open(main)
    w.add([str(tmp_path / "gone.csv")])
    assert wait_until(lambda: w.status.text().startswith(strings.FREQ_ADD_FAILED.format(name="gone.csv", why="")))
    assert _items(w) == []


# --- removing: asked first, Cancel by default, into the trash ---------------------------------------------------- #
@pytest.fixture
def removes(monkeypatch):
    """Every remove the window hands its worker (AD1-2: the answer is proved, not raced against the disk)."""
    from app.qt import frequency_lists_window as flw
    calls = []
    real = flw._remove_all

    def record(names, language):
        calls.append((list(names), language))
        return real(names, language)
    monkeypatch.setattr(flw, "_remove_all", record)
    return calls


def test_remove_asks_first_and_enter_is_cancel(main, ja_list, removes):
    frequency_lists.add(ja_list, "ja")
    w = _open(main)
    _select(w, "novels")
    assert w.remove_button.isEnabled()
    w.remove_button.click()
    card = _card(w)
    assert card is not None and card.title.text() == strings.FREQ_REMOVE_ONE.format(name="novels")
    assert card.body.text() == strings.FREQ_REMOVE_BODY_ONE
    assert card.yes.property("kind") == "danger"
    assert QApplication.focusWidget() is card.no          # the default on a remove
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)
    assert card.answer is False and removes == [] and not w.busy()
    QTest.qWait(100)
    assert frequency_lists.listed("ja") == ["frequency_list_ja_novels.csv"] and _trash("ja") == []


def test_esc_on_the_question_removes_nothing_and_keeps_the_window(main, ja_list, removes):
    frequency_lists.add(ja_list, "ja")
    w = _open(main)
    _select(w, "novels")
    w.remove_button.click()
    card = _card(w)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    assert card.answer is False and removes == [] and w.isVisible()
    QTest.qWait(100)
    assert frequency_lists.listed("ja") == ["frequency_list_ja_novels.csv"]


def test_remove_confirmed_moves_the_lists_to_the_trash(main, ja_list, tmp_path, removes):
    other = tmp_path / "Anime.csv"
    other.write_text("Word,Rank\n仲間,640\n", encoding="utf-8")
    frequency_lists.add(ja_list, "ja")
    frequency_lists.add(str(other), "ja")
    w = _open(main)
    assert wait_until(lambda: len(_items(w)) == 2)
    _select(w, "novels", "Anime")
    w.remove_button.click()
    card = _card(w)
    assert card.title.text() == strings.FREQ_REMOVE_MANY.format(n=2)
    assert card.body.text() == strings.FREQ_REMOVE_BODY_MANY
    card.yes.click()
    assert wait_until(lambda: _items(w) == [] and w.status.text() == strings.FREQ_REMOVED.format(n=2))
    assert removes == [(["frequency_list_ja_Anime.csv", "frequency_list_ja_novels.csv"], "ja")]
    assert len(_trash("ja")) == 2 and frequency_lists.listed("ja") == []


def test_remove_needs_a_selection(main, ja_list):
    frequency_lists.add(ja_list, "ja")
    w = _open(main)
    assert not w.remove_button.isEnabled() and w.remove_button.toolTip() == strings.FREQ_REMOVE_NONE_TIP
    assert w.ask_remove() is None


def test_a_switch_with_the_question_open_drops_it_and_removes_nothing(main, ja_list, zh_list, removes):
    # IK-24 / AD1-12: the question named a ja list; once the window shows zh lists it is dropped, never answered.
    frequency_lists.add(ja_list, "ja")
    frequency_lists.add(zh_list, "zh")
    w = _open(main)
    _select(w, "novels")
    w.remove_button.click()
    card = _card(w)
    yes = card.yes
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: _items(w) == ["subtitles"])
    assert _card(w) is None
    try:
        yes.click()
    except RuntimeError:
        pass
    QTest.qWait(100)
    assert removes == [] and frequency_lists.listed("ja") == ["frequency_list_ja_novels.csv"]


def test_the_windows_guard_refuses_a_remove_for_a_language_it_left(main, ja_list, zh_list, removes):
    frequency_lists.add(ja_list, "ja")
    frequency_lists.add(zh_list, "zh")
    w = _open(main)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh")
    w.remove(["frequency_list_ja_novels.csv"], "ja")      # asked while on ja; the window is on zh now
    assert removes == []
    assert frequency_lists.listed("ja") == ["frequency_list_ja_novels.csv"] and _trash("ja") == []


def test_reading_the_same_lists_again_repaints_nothing(main, ja_list):
    # IK-25 (S19): a re-read that finds the same lists leaves the list alone.
    frequency_lists.add(ja_list, "ja")
    w = _open(main)
    before = w.list_paints
    w.read()
    QTest.qWait(200)
    assert w.list_paints == before


def test_a_write_answered_after_the_main_window_is_gone_raises_nothing(qapp, ja_list, monkeypatch, qt_errors):
    # AD1-3: an add finishing after the app's main window was deleted once wrote to its deleted bar.
    import threading
    from PyQt6.QtCore import QCoreApplication, QEvent
    from app.qt import frequency_lists_window as flw
    go_on = threading.Event()
    real = flw._add_all

    def slow(paths, language):
        go_on.wait(10)
        return real(paths, language)
    monkeypatch.setattr(flw, "_add_all", slow)
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    w = windows.show(win, "frequency-lists", FrequencyListsWindow)
    w.add([ja_list])
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    go_on.set()
    QTest.qWait(300)
    assert qt_errors == []
    services.shutdown(0.5)


# --- the language switch ------------------------------------------------------------------------------------------ #
def test_the_window_follows_the_main_windows_language(main, ja_list, zh_list):
    frequency_lists.add(ja_list, "ja")
    frequency_lists.add(zh_list, "zh")
    w = _open(main)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: _items(w) == ["subtitles"])
    assert w.language == "zh"


def test_a_write_the_window_closed_on_still_says_its_line_in_the_bar(main, ja_list):
    w = _open(main)
    w.add([ja_list])
    w.close()
    assert wait_until(lambda: main.bar_line.full() == strings.FREQ_ADDED.format(n=1))
    assert frequency_lists.listed("ja") == ["frequency_list_ja_novels.csv"]


def test_the_windows_thread_never_reads_the_folder(main, ja_list, monkeypatch):
    # Every read goes through a worker: the listing is called off the GUI thread.
    import threading
    gui = threading.current_thread()
    seen = []
    real = frequency_lists.listed

    def listed(language):
        seen.append(threading.current_thread() is gui)
        return real(language)
    monkeypatch.setattr(frequency_lists, "listed", listed)
    w = windows.show(main, "frequency-lists", FrequencyListsWindow)
    assert wait_until(lambda: w.names is not None)
    assert seen and not any(seen)
