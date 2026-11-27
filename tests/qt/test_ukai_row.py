"""鵜 Ukai's row in Settings › Connections › Houseki tools (UKAI-S2, Ukai SPEC U9): whether Ukai is paired, and
*Forget Ukai* — shown only while the door's Ukai class is on (`door.EXTENSION_ON`, off until Ukai 1.0) and its module
is here.

What a wrong answer would cost a learner: a row for an extension that can't pair yet (off, it must not show at all); a
row that says *not paired* while Ukai sends into their library (or *paired* after they forgot it); a *Forget* that
leaves Ukai able to send; a forget whose file couldn't go said as done for good.
"""
import json
import threading
from types import SimpleNamespace

import pytest

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication

from app import door
from app.qt import settings_catalog as catalog
from app.qt import settings_page as sp
from app.qt import settings_strings as S
from app.qt.bridge import Bridge
from app.services import ukai_pairing as up
from tests.qt.conftest import wait_until
from tests.qt.test_settings_live import Shell, Status, Updates, fakes  # noqa: F401 (the fixture)
from tests.qt.test_settings_page import EVERYTHING, Recorder, _no_direct_save  # noqa: F401 (the autouse guard)

ORIGIN = "chrome-extension://kbmfpngjjgdllneeigpgjifpgocmfgmb"
TOKEN = "U" * 32
ON = EVERYTHING | {"ukai_on"}                   # the page's ctx with Ukai's class on and its module here


def _paired_file(tmp_path, version="1.0.0"):
    where = tmp_path / "roaming" / up.FILE
    where.parent.mkdir(parents=True, exist_ok=True)
    kept = {"origin": ORIGIN, "token": TOKEN, "at": 1.0}
    if version is not None:
        kept["version"] = version
    where.write_text(json.dumps(kept), encoding="utf-8")
    return where


def _make(fakes, tmp_path, pairing=None, found=ON):
    """The Settings page on a shell that holds Ukai's pairing (`ShellWindow.ukai_pairing`, built by the window only
    while the door's Ukai class is on) and the window's bridge (its `ukai_paired`)."""
    store = Recorder({"target_language": "ja"})
    services = SimpleNamespace(settings=store, status=Status(), automation=None)
    services.updates = Updates(store)
    shell = Shell(services)
    shell.bridge = Bridge()
    shell.ukai_pairing = pairing
    page = sp.SettingsPage(shell, "ja", found=found)
    page.resize(1100, 700)
    page.show()
    assert wait_until(lambda: page.built, 20)
    QApplication.processEvents()
    return page, shell


def _mark(page):
    return page.live.parts["ukai"]["mark"]


def _forget(page):
    return page.live.parts["ukai"]["forget"]


def test_while_off_the_row_never_shows_and_the_page_finds_no_ukai(qapp, monkeypatch):
    """Off (the default until Ukai 1.0): the page's own look finds no `ukai_on`, so the row's `when` hides it — and
    with the module gone, the same even while on."""
    assert door.EXTENSION_ON is False
    assert sp._ukai_on() == set()
    row = next(r for r in catalog.ROWS if r.id == "ukai")
    assert not catalog.visible(row, {}, "ja", frozenset(EVERYTHING) | sp._ukai_on())
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    assert sp._ukai_on() == {"ukai_on"} and catalog.visible(row, {}, "ja", ON)
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "modules.ukai" else real(name, *a))
    assert sp._ukai_on() == set(), "no module: no row (Surasura runs as before)"


def test_off_the_page_never_shows_ukais_row_and_reads_no_pairing(qapp, fakes, tmp_path):
    """Off, the window builds no pairing (`ShellWindow.ukai_pairing` None) and the page's ctx has no `ukai_on`: the
    row is hidden (every row is built, its `when` hides it) and says nothing paired."""
    page, _shell = _make(fakes, tmp_path, pairing=None, found=EVERYTHING)
    assert page.row("ukai") is not None and page.row("ukai").isHidden()
    hato = page.row("hato")
    assert not hato.isHidden(), "the section is shown: only Ukai's row is hidden"
    assert wait_until(lambda: _mark(page).words() == S.UKAI_NOT_PAIRED) and _forget(page).isHidden()
    page.close()


def test_on_the_row_shows_under_houseki_tools_with_its_tag(qapp, fakes, tmp_path):
    page, _shell = _make(fakes, tmp_path, pairing=None)
    assert not page.row("ukai").isHidden() and page.row("ukai").tag.text() == "鵜 Ukai"
    page.close()


def test_paired_says_so_with_its_version_and_offers_forget(qapp, fakes, tmp_path):
    pairing = up.Pairing(None, where=str(_paired_file(tmp_path)))
    page, _shell = _make(fakes, tmp_path, pairing)
    assert page.row("ukai") is not None
    assert wait_until(lambda: _mark(page).words() == S.UKAI_PAIRED.format(version="1.0.0")) and _mark(page).value()
    assert wait_until(lambda: not _forget(page).isHidden())
    page.close()


def test_paired_without_a_version_says_paired_plainly(qapp, fakes, tmp_path):
    pairing = up.Pairing(None, where=str(_paired_file(tmp_path, version=None)))
    page, _shell = _make(fakes, tmp_path, pairing)
    assert wait_until(lambda: _mark(page).words() == S.UKAI_PAIRED_PLAIN) and _mark(page).value()
    page.close()


@pytest.mark.parametrize("held", ["none", "no-file"])
def test_not_paired_says_so_and_hides_forget(qapp, fakes, tmp_path, held):
    """No pairing object (the window built none) or no pairing file: *not paired*, nothing to forget."""
    pairing = None if held == "none" else up.Pairing(None, where=str(tmp_path / "roaming" / up.FILE))
    page, _shell = _make(fakes, tmp_path, pairing)
    assert wait_until(lambda: _mark(page).words() == S.UKAI_NOT_PAIRED) and not _mark(page).value()
    assert _forget(page).isHidden()
    page.close()


def test_forget_unpairs_at_once_says_so_and_the_row_turns(qapp, fakes, tmp_path):
    where = _paired_file(tmp_path)
    pairing = up.Pairing(None, where=str(where))
    page, shell = _make(fakes, tmp_path, pairing)
    pairing._changed = shell.bridge.ukai_changed            # the window's wiring (`ShellWindow.ukai_extension`)
    assert wait_until(lambda: not _forget(page).isHidden())
    _forget(page).click()
    assert wait_until(lambda: S.UKAI_FORGOTTEN in shell.bar_line.lines)
    assert pairing.pairing() is None and not where.exists()
    assert wait_until(lambda: _mark(page).words() == S.UKAI_NOT_PAIRED and _forget(page).isHidden())
    page.close()


def test_a_forget_whose_file_cant_go_says_unpaired_until_surasura_closes(qapp, fakes, tmp_path, monkeypatch):
    where = _paired_file(tmp_path)
    pairing = up.Pairing(None, where=str(where))
    page, shell = _make(fakes, tmp_path, pairing)
    pairing._changed = shell.bridge.ukai_changed
    assert wait_until(lambda: not _forget(page).isHidden())
    real = up.os.remove

    def held(path):
        if path.endswith(up.FILE):
            raise PermissionError(13, "held by another program")
        return real(path)

    monkeypatch.setattr(up.os, "remove", held)
    _forget(page).click()
    assert wait_until(lambda: any(line.startswith(S.UKAI_FORGET_STUCK.split("{")[0]) for line in shell.bar_line.lines))
    assert S.UKAI_FORGOTTEN not in shell.bar_line.lines
    assert pairing.pairing() is None, "this session is unpaired all the same"
    assert wait_until(lambda: _mark(page).words() == S.UKAI_NOT_PAIRED)
    page.close()


def test_an_allow_while_settings_is_open_turns_the_row_to_paired(qapp, fakes, tmp_path):
    """Ukai paired from its menu while the page is open: the pairing's `changed` reaches the row through the bridge
    (any thread), which reads the pairing again."""
    where = tmp_path / "roaming" / up.FILE
    pairing = up.Pairing(None, where=str(where))
    page, shell = _make(fakes, tmp_path, pairing)
    assert wait_until(lambda: _mark(page).words() == S.UKAI_NOT_PAIRED)
    _paired_file(tmp_path, version="1.2.0")
    pairing._kept = up._UNREAD                              # (a claim keeps what it wrote: the same as read here)
    threading.Thread(target=shell.bridge.ukai_changed).start()     # the door's thread at a claim
    assert wait_until(lambda: _mark(page).words() == S.UKAI_PAIRED.format(version="1.2.0"))
    assert wait_until(lambda: not _forget(page).isHidden())
    page.close()


def test_a_closed_page_leaves_nothing_listening_on_the_bridge(qapp, fakes, tmp_path):
    """(Review.) Each page's row listens on the window's one bridge; a page gone must not keep its `Live` (and its
    widgets) alive, nor be painted at the next pairing."""
    from PyQt6 import sip
    pairing = up.Pairing(None, where=str(tmp_path / "roaming" / up.FILE))
    page, shell = _make(fakes, tmp_path, pairing)
    signal = shell.bridge.ukai_paired
    assert wait_until(lambda: _mark(page).words() == S.UKAI_NOT_PAIRED)
    assert shell.bridge.receivers(signal) == 1
    page.close()
    sip.delete(page)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)      # (PyQt's slot proxy goes later)
    QApplication.processEvents()
    assert shell.bridge.receivers(signal) == 0
    shell.bridge.ukai_changed()                                     # (nothing painted, nothing raised)
    QApplication.processEvents()


@pytest.mark.parametrize("lines, words", [(2, "paired · 1.0.0 · 2 lines to record"),
                                          (1, "paired · 1.0.0 · 1 line to record"), (0, "paired · 1.0.0")])
def test_the_row_says_how_many_lines_wait_for_ukai_to_record(qapp, fakes, tmp_path, lines, words):
    """UKAI-S4 (U9's *what waits to be recorded*): Connect's Netflix jobs' lines still missing a clip, counted on the
    row's worker (`connect.browser.waiting_lines`); none waiting says nothing more."""
    from app.connect import browser
    if lines:
        browser.hand_off(412, {"site": "netflix", "url": "https://www.netflix.com/watch/80000003"}, "第3話",
                         [{"n": n, "start": 1.0 + 3 * n, "end": 3.2 + 3 * n, "text": "文化祭まで、あと三日しかないよ。"}
                          for n in range(lines)])
    pairing = up.Pairing(None, where=str(_paired_file(tmp_path)))
    page, _shell = _make(fakes, tmp_path, pairing)
    assert wait_until(lambda: _mark(page).words() == words), _mark(page).words()
    page.close()
