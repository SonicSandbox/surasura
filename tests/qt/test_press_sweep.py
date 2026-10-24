"""Every press in the main window reacts at once (round 8 row 45, package P3: the scope `row45-54-scope.md` §2.1–§2.6,
the W and O classes): one paint-before-work proof per class of site — the press's mark painted (a paint counted, the
arc running) at the moment its work is handed to a worker, never after it.

What a wrong answer would cost a learner:
  * Generate pressed and nothing visible for up to 10 s while the settings flush (then pressed again);
  * *Update now*, *Choose a folder…*, *Keep its words* answering only when their work ends;
  * ▶, a folder, the journey or the guide opening seconds later with nothing said meanwhile — or the window stalled
    while a folder opened on its own thread;
  * Refresh doing nothing visible while every folder is looked at again.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import press as qpress
from app.qt import rows
from app.services import needs as service
from app.services import press as press_service
from tests.qt.conftest import wait_until
from tests.qt.test_jobs_bar import World, _offer
from tests.qt.test_needs_you import button, world  # noqa: F401 — Needs you's own world (a fixture)
from tests.qt.test_press import Paints, _Calls, arc_shown
from tests.qt.test_press import window as shown_window  # noqa: F401 — a window over a seeded library (a fixture)
from tests.qt.test_press import stage  # noqa: F401,E402 — a button row (a fixture)


@pytest.fixture
def duties(qapp, tmp_path):
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    yield w
    w.close()


@pytest.fixture
def handed(monkeypatch):
    """`bridge.run_in_worker` replaced from here on: each hand-over recorded with what showed at that moment."""
    calls = _Calls()

    def stub(fn, *args, then=None, failed=None, pool=None):
        calls.append(type("Handed", (), dict(fn=fn, args=args, then=then, failed=failed,
                                             look=calls.look() if calls.look is not None else None)))
    monkeypatch.setattr(qpress.bridge, "run_in_worker", stub)
    return calls


def _settle():
    for _ in range(5):
        QApplication.processEvents()


def test_generate_turns_its_arc_before_the_settings_flush_is_handed_over(duties, handed):
    """§2.1 Generate (GAP W): the click's arc on the button, painted, before `Services.generate` (its flush of up to
    10 s, then the request) goes to the worker; a second click meanwhile asks nothing; done, the arc goes."""
    duties.d.level.click()                                         # (Generate lives in the level ▾'s pop)
    assert wait_until(lambda: duties.d.pop.isVisible(), 5)
    b = duties.d.generate.button
    paints = Paints(b)
    _settle()
    before = paints.n
    handed.look = lambda: (arc_shown(b), paints.n - before, b.text())
    duties.win._generate_pressed()
    gens = [h for h in handed if h.fn == duties.win.services.generate]
    assert len(gens) == 1
    arc, painted, words = gens[0].look
    assert arc and painted >= 1 and words == duties.d.generate.button.text()      # its words stay (Q1)
    duties.win._generate_pressed()
    assert len([h for h in handed if h.fn == duties.win.services.generate]) == 1   # live: nothing asked twice
    gens[0].then(None)
    assert qpress.arc(b) is None


def test_update_now_turns_the_clicked_buttons_arc_before_the_service_is_asked(duties, handed):
    """§2.1 the update sheet (GAP W): *Update now*'s arc on that button, painted before `updates.start` is handed
    over (the sheet's signal names no button: the shell finds the one that sent it)."""
    _offer(duties)
    assert wait_until(lambda: not duties.d.update_mark.isHidden())
    duties.win.open_update_sheet()
    b = duties.d.sheet.buttons["start"]
    _settle()
    paints = Paints(b)
    before = paints.n
    handed.look = lambda: (arc_shown(b), paints.n - before)
    b.click()
    starts = [h for h in handed if h.fn == duties.win.services.updates.start]
    assert len(starts) == 1 and starts[0].look[0] and starts[0].look[1] >= 1
    starts[0].then(None)
    assert qpress.arc(b) is None


def test_the_journey_is_one_press_for_its_four_doors_marked_before_the_open(duties, handed):
    """§2.1 *Journey ↗* / *Open your journey* (GAP O): the clicked button's arc, then the open on a worker; a click on
    another door meanwhile does nothing (it was dropped silently), and the press ends with the open."""
    d, win = duties.d, duties.win
    win._show_journey(True)
    b = d.journey_button
    _settle()
    handed.look = lambda: arc_shown(b)
    win._open_journey(control=b)
    assert len(handed) == 1 and handed[0].fn == win.services.open_journey and handed[0].look is True
    assert win._open_journey(control=d.journey) is None and len(handed) == 1
    handed[0].then(True)
    assert not win.presses.find("journey:open").live() and qpress.arc(b) is None


def test_a_menu_press_with_nothing_on_screen_the_online_guide_turns_the_bars_arc_first(duties, handed):
    """§2.1 ? › *Online guide* (GAP O): its menu has closed — the bar's arc, no words, painted before the browser is
    asked on a worker."""
    win = duties.win
    paints = Paints(win.bar_arc)
    _settle()
    words, before = win.bar_line.full(), paints.n
    handed.look = lambda: (win.bar_arc.isVisible(), paints.n - before, win.bar_line.full())
    win._open_guide()
    shown, painted, now = handed[-1].look
    assert shown and painted >= 1 and now == words
    handed[-1].then(None)
    assert not win.bar_arc.isVisible()


def test_refresh_turns_the_bars_arc_until_a_looks_summary_comes_back(duties):
    """§2.1 Refresh (GAP W): the bar's arc from the key until the look's summary; with nothing to look with, at once."""
    win = duties.win
    win.looks = type("Looks", (), {"asked": lambda self, **_kw: True, "close": lambda self: None})()
    win.refresh_sources()
    assert win.bar_arc.isVisible() and win.presses.find("sources:refresh").live()
    win._sources_looked({"language": win.language, "sources": []})
    assert not win.bar_arc.isVisible() and not win.presses.find("sources:refresh").live()
    win.looks = None
    win.refresh_sources()
    assert not win.presses.find("sources:refresh").live() and not win.bar_arc.isVisible()


def test_play_marks_the_files_play_on_its_line_before_its_lookup_is_handed_over(shown_window, handed,  # noqa: F811
                                                                                   monkeypatch):
    """§2.3 ▶ (GAP O): row 55's one lookup and the open stay on a worker; the file's ▶ on its line turns first."""
    page = shown_window.page_widgets["current"]
    lst = page.list
    ep = page.view_model.rows[0].episodes[0]
    drawn = []
    real = rows.paint_marked
    monkeypatch.setattr(rows, "paint_marked", lambda p, rect, turning, **kw: (drawn.append(kw), real(p, rect, turning,
                                                                                                       **kw)))
    handed.look = lambda: ({k: list(v) for k, v in lst.marked.items()}, len(drawn))
    page._play(ep)
    marked, painted = handed[-1].look
    assert marked == {ep.id: ["play"]} and painted >= 1
    assert page._play(ep) is None                                     # a second ▶ meanwhile does nothing
    handed[-1].then(None)
    assert lst.marked == {}


def test_choose_a_folder_turns_before_the_drive_is_looked_at_and_again_after_picking(world, tmp_path):  # noqa: F811
    """§2.6 *Choose a folder…* (GAP W ×2): one press from the click — the arc painted before the `isdir` worker (an
    offline drive's stat can take a while), still turning while the picked folder's files are matched — ended once
    they are."""
    seed, win, writer, ny = world()
    win.show_tab("needs")
    _settle()
    gone = next(e for e in ny.entries if e.kind == service.GONE and len(e.lines) == 3)
    b = button(ny, gone.key, "choose_folder")
    seen = []
    ny.pick_folder = lambda title, start: seen.append(arc_shown(button(ny, gone.key, "choose_folder"))) or \
        str(tmp_path)
    b.click()
    key = ny._press_key("choose_folder", gone)
    assert arc_shown(b) and qpress.presses_of(win).get(key).live()          # at once, before any worker answered
    assert wait_until(lambda: not qpress.presses_of(win).get(key).live(), 10)
    assert seen == [True]                                                    # still turning while it was picked


def test_keep_its_words_on_a_line_turns_that_lines_button_until_it_is_kept(world):  # noqa: F811
    """§2.6 *Keep its words* (GAP W): the line's own button turns (its card's other lines keep theirs still) from the
    click until the answer is kept."""
    seed, win, writer, ny = world()
    win.show_tab("needs")
    _settle()
    gone = next(e for e in ny.entries if e.kind == service.GONE and len(e.lines) == 3)
    line = gone.lines[1]
    b = button(ny, gone.key, "keep_words", line)
    other = button(ny, gone.key, "keep_words", gone.lines[0])
    b.click()
    assert arc_shown(b) and qpress.arc(other) is None
    p = qpress.presses_of(win).get(ny._press_key("keep_words", gone, line.key))      # (its line's own, P3-A1)
    assert p.live()
    assert wait_until(lambda: p.state in (press_service.DONE, press_service.IDLE), 10)


# --- the review's fixes (round8-p3-adversary.md) ------------------------------------------------------------------- #
def test_p3_a1_each_lines_keep_its_words_is_its_own_press_two_lines_turn_together(world):  # noqa: F811
    """P3-A1: every line's *Keep its words* shared one key, so line B pressed while line A's ran was dropped: no arc,
    no answer. Each line is its own press now: both turn, both are asked."""
    seed, win, writer, ny = world()
    win.show_tab("needs")
    _settle()
    gone = next(e for e in ny.entries if e.kind == service.GONE and len(e.lines) == 3)
    a, b = (button(ny, gone.key, "keep_words", ln) for ln in gone.lines[:2])
    a.click()
    b.click()
    keys = [ny._press_key("keep_words", gone, ln.key) for ln in gone.lines[:2]]
    assert keys[0] != keys[1]
    assert arc_shown(a) and arc_shown(b)
    assert all(qpress.presses_of(win).get(k).state != press_service.IDLE for k in keys)


def test_p3_a2_a_look_that_couldnt_run_ends_refresh_and_says_why(qapp, duties):
    """P3-A2: Refresh's arc ended only at a summary; a look with no store (or one that failed) sends none, so the arc
    turned for two minutes with no word. The looks now say every look's end; a look with no store ends the press,
    failed, with its reason in the bar."""
    from app.services.source_looks import SourceLooks

    class NoStore:
        mode = "store"

        def handle(self):
            return None
    looks = SourceLooks(NoStore(), "ja")
    ended = []
    looks.on_ended = lambda told, why: ended.append((told, why))
    try:
        looks._look(True, None)
    finally:
        looks.close()
    assert ended == [(False, "the library isn't open")]
    win = duties.win
    win.looks = type("Looks", (), {"asked": lambda self, **_kw: True, "close": lambda self: None})()
    win.refresh_sources()
    p = win.presses.find("sources:refresh")
    assert p.live()
    win._look_ended(ended[0])
    assert p.state == press_service.FAILED and not win.bar_arc.isVisible()
    from app.qt import strings
    assert win.bar_line.full() == strings.REFRESH_FAILED.format(why="the library isn't open")
    win.looks = None


def test_p3_a3_a_second_refresh_while_one_is_live_looks_at_nothing(duties):
    """P3-A3: a second Refresh while one ran asked for one more full look of every folder; with nothing to look with
    it flashed the arc for a frame. Neither now."""
    win, asked = duties.win, []
    win.looks = type("Looks", (), {"asked": lambda self, **kw: asked.append(kw) or True,
                                   "close": lambda self: None})()
    win.refresh_sources()
    win.refresh_sources()
    assert len(asked) == 1
    win._look_ended((True, None))
    win.looks = None
    assert win.refresh_sources() is False and not win.presses.find("sources:refresh").live()


def test_p3_a4_two_presses_on_one_file_keep_a_mark_each(shown_window):  # noqa: F811
    """P3-A4: ▶ then ⋯ *Open its folder* on one file — the second mark overwrote the first, and the first press to
    end took both off. Each press keeps its own: the newest shows, and the other stays when one ends."""
    lst = shown_window.page_widgets["current"].list
    ep = shown_window.page_widgets["current"].view_model.rows[0].episodes[0]
    play, more = qpress.row_mark(lst, [ep.id], "play"), qpress.row_mark(lst, [ep.id], "more")
    play.on()
    more.on()
    assert lst.marked_part([ep]) == "more"
    more.off()
    assert lst.marked_part([ep]) == "play"                       # ▶'s press still marked
    more.on()
    play.off()
    assert lst.marked_part([ep]) == "more"
    more.off()
    assert lst.marked == {} and lst.marked_part([ep]) is None


def test_p3_a5_a_window_whose_say_holds_nothing_never_holds_the_press(qapp, handed):
    """P3-A5: `say(text)` with no `hold` (the wizard's, the drag controller's) raised after the press went live: live
    for ever, every later press of it nothing. Now the work starts and ends it."""
    class Plain:
        def say(self, text):
            pass
    win = Plain()
    p = qpress.run(None, "wizard:check", lambda: None, busy="Checking…", win=win)
    assert p is not None and len(handed) == 1
    handed[0].then(None)
    assert p.state == press_service.DONE and qpress.run(None, "wizard:check", lambda: None, win=win) is not None


def test_p3_a6_an_answer_that_leaves_its_card_can_be_pressed_again_at_once(world):  # noqa: F811
    """P3-A6: *Mine anyway* answered "couldn't" left its card, but the card's press lingered DONE as "going": pressed
    again at once, nothing. It asks again now."""
    calls = []

    def mine(*args):
        calls.append(args)
        return False
    connect = {"jobs": [], "gaps": [], "needs": [{"id": 11, "kind": "not-timed", "say": "Ep 3 isn't timed to its video",
                                                  "item": 3, "seen_at": None, "at": "2026-10-15T09:00:00Z"}]}
    seed, win, writer, ny = world(connect=connect, connect_calls={"mine_anyway": mine, "kick": lambda *_a: None})
    entry = next(e for e in ny.entries if (e.data or {}).get("need_id") == 11)
    button(ny, entry.key, "mine_anyway").click()
    assert wait_until(lambda: len(calls) == 1 and not qpress.presses_of(win).any_live(), 5)
    button(ny, entry.key, "mine_anyway").click()
    assert wait_until(lambda: len(calls) == 2, 5)


def test_p3_a7_an_arc_over_an_icon_has_the_ground_a_rows_mark_has(stage):
    """P3-A7: `widget_mark` drew the bare arc over a ⋯'s dots; a row's marked ⋯ has a raised ground. One look: the
    widget's mark covers the icon with that ground, the arc in its middle."""
    m = qpress.widget_mark(stage.leave)
    m.on()
    s = m.spinner
    assert isinstance(s, qpress._Grounded) and s.isVisible()
    assert s.width() == min(stage.leave.width(), stage.leave.height())
    m.off()


def test_p3_a8_mine_texts_path_is_on_the_clipboard_before_anki_miner_starts(shown_window, monkeypatch):  # noqa: F811
    from app.connect import anki_miner
    from app.qt import screens
    win = shown_window
    if getattr(win, "mine", None) is None:
        pytest.skip("no mining actions in this window")
    seen = []
    monkeypatch.setattr(anki_miner, "find", lambda _s: r"C:\AnkiMiner.exe")
    monkeypatch.setattr(screens, "open_with_system", lambda _p: seen.append(QApplication.clipboard().text()))
    QApplication.clipboard().setText("before")
    win.mine.mine_text("第3話", "HighPriority/葬送のフリーレン/葬送のフリーレン 第3話.srt")
    assert wait_until(lambda: seen, 5)
    assert seen[0].endswith("葬送のフリーレン 第3話.srt")


def test_p3_a9_off_windows_the_open_itself_stays_on_the_windows_thread(shown_window, monkeypatch):  # noqa: F811
    import threading
    from app.qt import screens
    monkeypatch.setattr(qpress, "OFF_THREAD", False)
    where, done = [], []
    monkeypatch.setattr(screens, "open_with_system", lambda _p: where.append(threading.current_thread()))
    qpress.open(shown_window, lambda: r"C:\a.mkv", key="open:a9", then=done.append)
    assert wait_until(lambda: done, 5)
    assert where == [threading.main_thread()]
