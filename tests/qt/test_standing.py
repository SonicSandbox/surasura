"""Every standing line has a ✕ (round 8 row 54; `app/qt/standing.py` over `app/services/standing.py`): the offline line
(with *Keep waiting*), the bottom bar's failure line, the update chip and a page's read-only line. ✕ hides a line until
its state changes.

Sonic: "[PATH] isn't reachable; its 5 episodes are kept. Which is great. But, I can't remove that line. it just sits
there."

What a wrong answer would cost a learner: a line he can't clear, sitting under his library for good; one he cleared
that comes back at the next look or start; one cleared for good, so a folder that goes away again, a newer failure or
a new version never says so; a failure cleared off the bar and lost from *Needs you* too; a ✕ that moves the words
it sits beside.

Real paths in the test's own root, made-up show names; the windows are the existing harnesses' (test_window_sources,
test_jobs_bar, test_current).
"""
import json
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app.qt import standing as standing_qt
from app.qt import strings
from app.services import generate as G
from app.services import needs, standing
from app.services import updates as U
from tests.qt.conftest import wait_until
from tests.qt.test_current import seeded  # noqa: F401  (the seeded-library fixture)
from tests.qt.test_jobs_bar import _offer, _slot, world  # noqa: F401  (the duties' world fixture)
from tests.qt.test_window_sources import RecordingLooks, window  # noqa: F401  (the looks' window fixture)


def _folder():
    path = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "Anime", "月影の旅人")
    os.makedirs(path, exist_ok=True)
    return path


def _said(looks, path, reachable, items=5):
    looks.on_result({"language": "ja", "sources": [{"id": 1, "path": path, "on": True, "items": items,
                                                     "reachable": reachable}], "added": 0, "waiting": 0, "full": True})


def _kept_in_seen_file():
    try:
        with open(needs.seen_path("ja"), encoding="utf-8") as f:
            return [k for k in json.load(f)["answered"] if standing.kind_of(k) == standing.OFFLINE]
    except FileNotFoundError:
        return []


# --- the offline line ---------------------------------------------------------------------------------------------- #
def test_the_offline_lines_x_hides_it_until_the_folder_is_back_and_goes_again(window):
    looks = RecordingLooks()
    _seed, win = window(looks)
    line = win.offline_line
    path = _folder()
    want = strings.SOURCES_OFFLINE.format(path=ls.folder_path(path), n=5)
    _said(looks, path, False)
    assert wait_until(lambda: not line.isHidden() and line.text() == want, 10)
    assert line.cross.isVisibleTo(line) and line.answers["keep"].isVisibleTo(line)
    assert line.cross.toolTip() == strings.STANDING_HIDE_TIP and line.cross.accessibleName()
    at = line.label.geometry()
    line.cross.click()
    assert line.isHidden()                                     # at once, before the seen file is written
    assert line.label.geometry() == at                          # the words never moved
    assert wait_until(lambda: _kept_in_seen_file() == [standing.offline_key(path)], 10)
    _said(looks, path, False)                                   # the next look: still away, still hidden
    QApplication.processEvents()
    assert wait_until(lambda: win.offline_hidden == {standing.offline_key(path)}, 10) and line.isHidden()
    _said(looks, path, True)                                    # back: its answer goes
    assert wait_until(lambda: not win.offline_hidden and _kept_in_seen_file() == [], 10)
    _said(looks, path, False)                                   # away again: it says so again
    assert wait_until(lambda: not line.isHidden() and line.text() == want, 10)


def test_keep_waiting_is_the_same_answer_and_a_restart_keeps_the_line_hidden(window):
    looks = RecordingLooks()
    _seed, win = window(looks)
    path = _folder()
    _said(looks, path, False, items=1)
    assert wait_until(lambda: not win.offline_line.isHidden(), 10)
    win.offline_line.answers["keep"].click()
    assert win.offline_line.isHidden()
    assert wait_until(lambda: _kept_in_seen_file() == [standing.offline_key(path)], 10)
    again = RecordingLooks()                                    # the next start: a new window, nothing in memory
    _seed, later = window(again)
    _said(again, path, None, items=1)                           # its first listing, then its first look
    _said(again, path, False, items=1)
    assert wait_until(lambda: later.offline_hidden == {standing.offline_key(path)}, 10)
    assert later.offline_line.isHidden() and later.offline_line.text() == ""


# --- the bar's failure line ------------------------------------------------------------------------------------------ #
def test_the_failure_lines_x_clears_the_bar_keeps_it_in_needs_you_and_a_newer_one_shows(world):
    win = world.win
    world.controller.push(state=G.FAILED, message="Generate stopped (exit code 1).", log_path="gen.log")
    assert wait_until(lambda: _slot(world) == "failure")
    assert win.bar_failure_cross.isVisibleTo(win)
    win.bar_failure_cross.click()
    assert _slot(world) == "line" and not win.bar_failure_cross.isVisibleTo(win)     # at once
    assert wait_until(lambda: world.status.snapshot().failure is None, 10)
    assert [e.text for e in world.status.snapshot().needs_you] == ["Generate stopped (exit code 1)."]
    world.controller.push(state=G.CURRENT)                      # it ran cleanly, then failed again
    assert wait_until(lambda: world.status.snapshot().needs_you and world.status.snapshot().failure is None, 10)
    world.controller.push(state=G.FAILED, message="Generate stopped (exit code 1).", log_path="gen.log")
    assert wait_until(lambda: _slot(world) == "failure", 10)


# --- the update chip ------------------------------------------------------------------------------------------------- #
def test_the_update_chips_x_hides_it_for_the_session_until_its_version_or_state_changes(world):
    win, d = world.win, world.d
    _offer(world)
    assert wait_until(lambda: _slot(world) == "update")
    assert d.update_cross.isVisibleTo(win) and d.update_cross.toolTip() == strings.STANDING_HIDE_TIP
    d.update_cross.click()
    assert _slot(world) == "line" and not d.update_cross.isVisibleTo(win)
    _offer(world)                                               # the same offer again: still hidden
    QApplication.processEvents()
    assert _slot(world) == "line"
    world.updates.push(state=U.WAITING, programs=(U.Program(1, "Content Manager", True),))
    assert wait_until(lambda: _slot(world) == "update")         # another state: shown again
    d.update_cross.click()
    _offer(world, version="99.1")                               # another version: shown again
    assert wait_until(lambda: _slot(world) == "update" and "99.1" in d.update_mark.toolTip())
    assert world.updates.called("updates.skip") == []           # ✕ is never *Skip this version*


# --- the read-only line ---------------------------------------------------------------------------------------------- #
def test_the_read_only_lines_x_hides_it_on_every_page_until_the_reason_changes(seeded):
    _seed, win = seeded(mode="read-only", reason="damaged")
    pages = [win.page_widgets[n] for n in ("current", "finished", "needs")]
    page = pages[0]
    assert page.state_bar.isVisible() and page.state_bar.cross.isVisibleTo(page.state_bar)
    view = page.view_model
    page.state_bar.cross.click()
    assert all(p.state_bar.isHidden() for p in pages)
    for p in pages:
        p.set_view(view)                                        # the next view, the same reason: still hidden —
    assert all(p.state_bar.isHidden() for p in pages)           # Needs you's too (A-1 / IK-1: it skipped the rule)
    page.set_view(view._replace(reason="io:disk full"))         # another reason: back
    assert page.state_bar.isVisible() and page.state_bar.text()
    win.show_library(view._replace(state="ready", reason=None))     # its trouble ended ...
    win.show_library(view)                                          # ... and came back: it says so again
    assert all(not p.state_bar.isHidden() and "the library needs a repair" in p.state_bar.text() for p in pages)


def test_a_page_whose_view_lags_never_lets_the_read_only_lines_x_go_for_the_others(seeded):
    """Round 8 (A-9): reading whether a line is hidden let the kind's keys go when that page's view had no read-only
    line — one page with a view behind (or none) un-hid the line for every page after it. The window says when the
    trouble ended (`show_library`); a page only reads."""
    _seed, win = seeded(mode="read-only", reason="damaged")
    pages = [win.page_widgets[n] for n in ("current", "finished", "needs")]
    view = pages[0].view_model
    pages[0].state_bar.cross.click()
    pages[0].set_view(view._replace(state="ready", reason=None))    # one page's view behind (no line on it)
    for p in pages[1:]:
        p.set_view(view)
    assert all(p.state_bar.isHidden() for p in pages[1:])


def test_a_line_of_work_running_has_no_x(seeded):
    _seed, win = seeded(mode="json", reason="not ready")
    for name in ("current", "needs"):                           # Needs you's too (A-1: its ✕ there did nothing)
        bar = win.page_widgets[name].state_bar
        assert bar.text() == strings.STATE_LINES["getting-ready"] and bar.cross.isHidden(), name


def test_the_x_is_one_widget_every_line_shares(window):
    """One rule: the four lines' ✕ are the same small mark, with its hover and its name."""
    _seed, win = window(RecordingLooks())
    crosses = [win.offline_line.cross, win.bar_failure_cross,
               win.page_widgets["current"].state_bar.cross]
    assert all(isinstance(c, standing_qt.Cross) and c.text() == strings.STANDING_HIDE for c in crosses)
    assert {c.objectName() for c in crosses} == {"standingclose"}
