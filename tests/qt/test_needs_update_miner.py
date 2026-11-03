"""*Needs you*'s Anki Miner line in the window (Michi-U, alpha 9.1 try; Sonic 2026-11-02: "if anki miner has an update,
it would show in needs you right?"): ONE card while titles wait only for the approved Anki Miner, its *Update* asking
first in the window, then Surasura's own install route on a worker (the approved release, its sha256), then the update
followed (the checks again, Connect kicked); the card goes once updated.

What a wrong answer would cost: a download (180 MB) and an installer started without a yes; the window frozen while the
installer is open (the route waits for it); an Update whose end never tells Connect (the books wait on); a card that
stays after the update, or a bar line that says "updated" when the installer was closed early. The route and the
follow are stood in for: nothing is downloaded or run.
"""
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from app.connect import am_release, setup
from app.qt import strings
from app.qt import wizard_strings as W
from app.services import anki_miner_setup as route
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, closed, entry_of, settle, world  # noqa: F401  (world: the fixture)

UPDATE = {"version": am_release.APPROVED, "kinds": ("books",)}


@pytest.fixture
def stood_in(monkeypatch):
    """The line on (the seed holds a book waiting), the install route and the follow stood in for, the bar's lines
    kept."""
    got = {"route": [], "follow": [], "said": [], "result": route.INSTALLER_CLOSED, "installed": am_release.APPROVED}
    main = threading.main_thread()
    monkeypatch.setattr(service, "miner_update", lambda view: UPDATE if not got.get("updated") else None)

    def install_as_job(registry, on_progress, cancel, on_end, confirm=None):
        got["route"].append((threading.current_thread() is not main, confirm()))
        got["updated"] = got["result"] == route.INSTALLER_CLOSED
        return got["result"]
    monkeypatch.setattr(route, "install_as_job", install_as_job)
    monkeypatch.setattr(setup, "follow_install", lambda settings, lang, installed=None, force=False, kick=True:
                        got["follow"].append((lang, force)) or True)
    monkeypatch.setattr(am_release, "installed", lambda: got["installed"])
    return got


def _said(win, got):
    real = win.say
    win.say = lambda text, hold=None: got["said"].append(text) or real(text, hold)


ON = {"jobs": [], "gaps": [], "needs": []}             # Connect on, nothing in its record


def test_the_card_offers_update_alone_with_its_tip_and_asks_before_any_byte(world, stood_in):
    seed, win, writer, ny = world(connect=ON)
    entry = entry_of(ny, service.MINER_UPDATE)
    assert entry.title == f"Update Anki Miner to {am_release.APPROVED} to make cards from your books and texts"
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"update_miner"}
    b = button(ny, entry.key, "update_miner")
    assert b.text() == "Update" and b.toolTip()
    b.click()
    card = ny.confirming
    assert card.isVisible() and card.title.text() == f"Update Anki Miner to {am_release.APPROVED}?"
    QTest.keyClick(card, Qt.Key.Key_Escape)
    assert wait_until(lambda: closed(card), 5)
    assert stood_in["route"] == [], "Esc: nothing downloaded, nothing opened"


def test_yes_runs_the_route_on_a_worker_follows_the_update_and_the_card_goes(world, stood_in):
    seed, win, writer, ny = world(connect=ON)
    _said(win, stood_in)
    entry = entry_of(ny, service.MINER_UPDATE)
    button(ny, entry.key, "update_miner").click()
    ny.confirming.yes.click()
    assert wait_until(lambda: stood_in["route"], 5)
    assert stood_in["route"] == [(True, True)], "off the window's thread, the yes already given (never asked twice)"
    assert wait_until(lambda: strings.NEEDS_MINER_UPDATED in stood_in["said"], 5)
    assert stood_in["follow"] == [("ja", True)], "the update followed: the checks again, Connect kicked"
    assert wait_until(lambda: not any(e.kind == service.MINER_UPDATE for e in ny.entries), 5)


@pytest.mark.parametrize("result, line", [(route.BUSY, strings.NEEDS_MINER_BUSY), (route.OPENED_RELEASES, W.INSTALL_OPENED),
                                          (route.CANCELLED, W.INSTALL_STOPPED),
                                          (route.INSTALLER_CLOSED, strings.NEEDS_MINER_NOT_UPDATED)])
def test_a_route_that_didnt_update_says_why_and_the_card_stays(world, stood_in, result, line):
    stood_in["result"] = result
    stood_in["installed"] = "3.10.1"                     # (the installer closed before it finished: still the old one)
    seed, win, writer, ny = world(connect=ON)
    _said(win, stood_in)
    entry = entry_of(ny, service.MINER_UPDATE)
    button(ny, entry.key, "update_miner").click()
    ny.confirming.yes.click()
    assert wait_until(lambda: line in stood_in["said"], 5)
    assert stood_in["follow"] == ([("ja", True)] if result == route.INSTALLER_CLOSED else [])
    stood_in["updated"] = False
    settle(ny)
    assert any(e.kind == service.MINER_UPDATE for e in ny.entries)


def test_the_card_has_no_not_now_and_is_absent_while_connect_is_off(world, stood_in):
    """Review r1 #2 / #3: Connect off, no card (nothing would be mined); on, no ⋯ (Not now / Stop asking would leave
    the rows' tip pointing at nothing)."""
    seed, win, writer, ny = world()                     # (the world's Connect: off)
    assert not any(e.kind == service.MINER_UPDATE for e in ny.entries)
    seed, win, writer, ny = world(connect={"jobs": [], "gaps": [], "needs": []})
    entry = entry_of(ny, service.MINER_UPDATE)
    assert not ny.cards.has_more(entry)


def test_an_anki_miner_followed_gathers_again_though_the_rows_read_the_same(world, stood_in):
    """Review r1 #1: a hand update followed moves the feed's `miner` — the view's rows read alike (its titles and
    files), yet the page gathers again and the line goes."""
    seed, win, writer, ny = world(connect={"jobs": [], "gaps": [], "needs": []})
    assert any(e.kind == service.MINER_UPDATE for e in ny.entries)
    stood_in["updated"] = True                          # Anki Miner updated by hand: the rule says no more
    n = ny.gathers
    ny.view_in(ny.view)                                 # the same rows: nothing to gather
    assert ny.gathers == n and not ny._running
    ny._miner_now = lambda: ((11, 140), am_release.APPROVED)
    ny.view_in(ny.view)
    assert wait_until(lambda: ny.gathers > n and not ny._running, 5)
    assert wait_until(lambda: not any(e.kind == service.MINER_UPDATE for e in ny.entries), 5)
