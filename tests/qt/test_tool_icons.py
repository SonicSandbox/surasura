"""The bottom bar's open windows and the minimise that goes into them (try a9 #5; `app/qt/tool_icons.py`,
`windows.SecondaryWindow`'s minimise).

What a wrong answer would cost: Sonic's report — a minimised Junban parked as a bare title bar in the desktop's corner,
a YouTube window minimised or closed with no way to tell whether it still runs; an icon left for a closed window (a
dead button), none for an open one, or one that doesn't bring its window back; the main window minimised and its
windows left behind; the bar repainting every icon on every line a window says (S19).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from app.qt import shell, strings, tool_icons, windows
from tests.qt.conftest import wait_until


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)
    assert services.settings.flush(10)


class Tool(windows.SecondaryWindow):
    def __init__(self, shell_window, name="Junban 順"):
        super().__init__(shell_window, name)


def _open(main, key="junban", name="Junban 順"):
    return windows.show(main, key, lambda s: Tool(s, name))


def _icons(main):
    return [(i.name, i.win) for i in main.tool_icons.icons.values()]


def test_no_window_open_shows_no_icon(main):
    assert main.tool_icons.isHidden() and main.tool_icons.icons == {}


def test_the_icons_sit_just_left_of_the_anki_mark(main):
    row = main.anki_mark.parentWidget().layout()
    at = [row.itemAt(i).widget() for i in range(row.count())]
    assert at.index(main.tool_icons) == at.index(main.anki_mark) - 1


def test_an_open_window_has_its_icon_with_its_mark_and_closing_takes_it_away(main):
    w = _open(main)
    assert _icons(main) == [("junban", w)] and not main.tool_icons.isHidden()
    icon = main.tool_icons.icons[id(w)]
    assert icon.mark == "順"
    assert icon.toolTip() == "Junban 順: Open\n• " + strings.TOOL_FRONT_TIP
    w.close()
    assert wait_until(lambda: main.tool_icons.icons == {} and main.tool_icons.isHidden())


def test_a_window_with_no_mark_of_its_own_shows_its_names_first_letter(main):
    w = _open(main, "probe-tool", "vocabulary export")
    assert main.tool_icons.icons[id(w)].mark == "V"
    assert tool_icons.mark_of("youtube-downloader", "Video Transcripts") == "▶"


def test_minimising_tucks_it_into_its_icon_and_a_click_brings_it_back(main):
    """Sonic's report: no bare title bar in the desktop's corner — the window hides into its icon, still open."""
    w = _open(main)
    w.showMinimized()
    assert wait_until(lambda: not w.isVisible())
    assert not w.gone and not w.isMinimized() and w.tucked()
    icon = main.tool_icons.icons[id(w)]
    assert icon.toolTip().endswith(strings.TOOL_BACK_TIP)
    QTest.mouseClick(icon, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: w.isVisible())
    assert not w.isMinimized() and not w.tucked()
    assert icon.toolTip().endswith(strings.TOOL_FRONT_TIP)


def test_its_door_brings_a_tucked_window_back_too(main):
    w = _open(main)
    w.showMinimized()
    assert wait_until(lambda: not w.isVisible())
    assert _open(main) is w and w.isVisible() and not w.isMinimized()


def test_the_main_window_minimised_takes_its_windows_with_it_untucked(main):
    """Windows hides an owned window with its owner and shows it again on restore: a window minimised while the main
    window is down (a platform that minimises both) is never tucked away from that restore."""
    w = _open(main)
    main.showMinimized()
    assert wait_until(main.isMinimized)
    w.showMinimized()
    QTest.qWait(30)
    assert w.isMinimized() and not w.tucked()
    main.showNormal()


def test_the_arc_turns_while_the_window_works_and_its_hover_says_what_it_is_doing(main):
    w = _open(main)
    icon = main.tool_icons.icons[id(w)]
    w.begin_write()
    w.say("Reordering 300 cards…")
    assert icon.look()[0] and icon._turn.running
    assert icon.toolTip().startswith("Junban 順: Reordering 300 cards…")
    w.end_write("Done: 300 cards in your list's order")
    w.say("")
    assert not icon.look()[0] and not icon._turn.running
    assert icon.toolTip().startswith("Junban 順: Open")


def test_a_live_press_of_the_window_counts_as_work(main):
    w = _open(main)
    p = w.presses.get("tool:probe")
    p.press()
    assert w.at_work() and main.tool_icons.icons[id(w)]._turn.running
    p.done()
    assert not w.at_work()


def test_a_line_said_repaints_nothing_unless_the_look_moved(main):
    """S19: a window that says a line per video repaints no icon (its hover's words move); work starting does."""
    w = _open(main)
    icon = main.tool_icons.icons[id(w)]
    assert wait_until(lambda: icon.paints > 0)
    QTest.qWait(30)
    before = icon.paints
    for n in range(20):
        w.say(f"{n} of 44 videos read")
        QTest.qWait(2)
    assert icon.paints == before and icon.toolTip().startswith("Junban 順: 19 of 44 videos read")
    w.begin_write()
    assert wait_until(lambda: icon.paints > before)
    w.end_write()


def test_enter_and_space_on_the_icon_bring_the_window_back(main):
    w = _open(main)
    icon = main.tool_icons.icons[id(w)]
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
        w.showMinimized()
        assert wait_until(lambda: not w.isVisible())
        QTest.keyClick(icon, key)
        assert wait_until(w.isVisible), key


def test_a_question_open_in_the_window_stays_through_the_tuck(main):
    """confirm.py keeps a question through a minimise; the tuck is one (hidden while still minimised)."""
    from app.qt import confirm
    w = _open(main)
    said = []
    card = confirm.ask(w, "Reorder 300 cards?", "Anki's new cards in your list's order.", "Reorder",
                       "Reorder them now", on_answer=said.append)
    w.showMinimized()
    assert wait_until(lambda: not w.isVisible())
    assert w.tucked() and card.answer is None and said == []
    windows.bring_back(w)
    assert wait_until(w.isVisible)
    assert card.answer is None and card.isVisible()


def test_a_maximised_window_comes_back_maximised(main):
    w = _open(main)
    w.showMaximized()
    w.showMinimized()
    assert wait_until(lambda: not w.isVisible())
    assert w.windowState() & Qt.WindowState.WindowMaximized and not w.isMinimized()
    windows.bring_back(w)
    assert wait_until(w.isVisible) and w.isMaximized()


def test_a_window_opened_by_another_follows_its_owner(main):
    owner = _open(main, "backfill", "Backfill")
    inner = windows.show(owner, "backfill-fields", lambda o: Tool(o, "Fields"))
    assert _icons(main) == [("backfill", owner), ("backfill-fields", inner)]
    assert windows.main_of(inner) is main
    inner.close()
    assert wait_until(lambda: _icons(main) == [("backfill", owner)])


def test_two_windows_keep_their_order_and_their_own_icons(main):
    a = _open(main, "junban", "Junban 順")
    b = _open(main, "youtube-downloader", "Video Transcripts")
    assert [n for n, _w in _icons(main)] == ["junban", "youtube-downloader"]
    a.close()
    assert wait_until(lambda: [n for n, _w in _icons(main)] == ["youtube-downloader"])
    assert main.tool_icons.icons[id(b)].mark == "▶"
