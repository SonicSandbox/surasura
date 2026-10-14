"""Anki Miner's update notice on the dashboard's row and in Connect's window: what a click does, as the mutant pass
found it untested (P3.2-AMN, 2026-10-13).

What a wrong answer would cost: the dashboard hands no browser in, so a row or window that only works with a test's
`open_url` opens nothing for the user; a browser failing with `webbrowser.Error` (not an OSError) raises into Tk's
callback instead of being printed. The browser is always stood in for: nothing opens.
"""
import webbrowser

import pytest

from app.connect import connect_window, status_row
from tests.connect_tk_helpers import Pump, Tips, tk_root

PAGE = "https://github.com/0xzerolight/anki_miner/releases/tag/v3.8.0"
NOTICE = {"version": "3.8.0", "url": PAGE}
RECORD = {"line": "Up to date · 3 cards made today", "state": "idle", "jobs": [], "needs": [], "unseen": 0,
          "undo": [], "shelf": {"on_shelf": 0, "runs": [], "swap_ins": 0}, "made_today": 3,
          "anki_miner_update": NOTICE}


@pytest.fixture
def root():
    r = tk_root()
    try:
        yield r
    finally:
        r.destroy()


def _row(root, **kw):
    return status_row.StatusRow(root, lambda: "ja", Tips(), lambda: None, settings=lambda: {"connect_enabled": True},
                                stamp=lambda languages=None: [1], read=lambda languages=None: {}, post=Pump().put,
                                unread=lambda lang: None, **kw)


def _window(root, **kw):
    return connect_window.show(root, "ja", Tips(), dict(RECORD), settings=lambda: {"connect_enabled": True},
                               junban=True, post=Pump().put, mark_seen=lambda ids: None, **kw)


def _no_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    return opened


def test_the_rows_notice_opens_the_page_with_the_systems_browser_when_none_is_handed_in(root, monkeypatch):
    """Mutant B39: the dashboard builds the row with no `open_url`; the click must still open the releases page
    (`webbrowser.open`)."""
    opened = _no_browser(monkeypatch)
    row = _row(root)
    row.draw(dict(RECORD))
    row._open_update()
    assert opened == [PAGE]


def test_a_browser_failing_with_webbrowser_error_never_raises_from_the_rows_click(root):
    """Mutant B38: `webbrowser.Error` isn't an OSError: the row's click prints it, never raises it into Tk."""
    def broken(url):
        raise webbrowser.Error("could not locate runnable browser")
    row = _row(root, open_url=broken)
    row.draw(dict(RECORD))
    row._open_update()


def test_the_windows_notice_opens_the_page_with_the_systems_browser_when_none_is_handed_in(root, monkeypatch):
    """Mutant B40: the dashboard opens Connect's window with no `open_url`; the click must still open the releases
    page (`webbrowser.open`)."""
    opened = _no_browser(monkeypatch)
    win = _window(root)
    assert win.update_link is not None
    win._open_update(PAGE)
    assert opened == [PAGE]


def test_a_browser_failing_with_webbrowser_error_never_raises_from_the_windows_click(root):
    """Mutant B41: `webbrowser.Error` isn't an OSError: the window's click prints it, never raises it into Tk."""
    def broken(url):
        raise webbrowser.Error("could not locate runnable browser")
    win = _window(root, open_url=broken)
    win._open_update(PAGE)
