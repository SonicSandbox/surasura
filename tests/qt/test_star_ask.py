"""Surasura's star ask (`app/qt/star_ask.py`; Sonic, 2026-10-31): once, ever, when cards from the learner's own show
first land in Anki.

What a wrong answer would cost: an ask shown every start, or again after *Not now* — a nag in a free app; one shown
at the window's first view for cards that were already there, or for a show with old cards dragged back into Current
(no first win, just a box: review A-1); one over setup, the sort screen, another toast (its Undo taken) or under the
hand mid-drag; a call of the app's own to GitHub (the link is the browser's, CLAUDE.md §1).
"""
import threading

import pytest

from app.qt import settings_catalog, settings_strings, star_ask, strings
from tests.qt.conftest import wait_until
from tests.qt.test_drag import world  # noqa: F401 (a fixture)

VIEW = object()


class Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.sets = []

    def get(self):
        return dict(self.values)

    def set(self, changes):
        self.sets.append(dict(changes))
        self.values.update(changes)


class Toasts:
    def __init__(self):
        self.shown, self.dragging, self.alive = [], False, False

    def show(self, message, undo=None, buttons=(), long=False):
        self.shown.append((message, [b[0] for b in buttons], long, buttons))


class Win:
    def __init__(self, values=None):
        self.services = type("S", (), {})()
        self.services.settings = Settings(values)
        self.services.setup_open = threading.Event()
        self.toasts = Toasts()
        self.minimized = False

    def isMinimized(self):
        return self.minimized


class Reader:
    """`LibraryReader.cards_rose()`: how many times an item asked before came back with more cards."""

    def __init__(self, rose=0):
        self.rose = rose

    def cards_rose(self):
        return self.rose


def test_nothing_landed_never_asks_and_the_first_landing_asks_once():
    win, reader = Win(), Reader()
    ask = star_ask.StarAsk(win)
    ask.view_shown(VIEW, reader)
    ask.view_shown(VIEW, reader)
    assert win.toasts.shown == []
    reader.rose = 1                                          # Connect made an episode's cards
    ask.view_shown(VIEW, reader)
    assert [(m, b, long) for m, b, long, _ in win.toasts.shown] == [
        (strings.STAR_ASK, [strings.STAR_ASK_STAR, strings.STAR_ASK_NOT_NOW], True)]
    assert win.services.settings.sets == [{"hints_seen": [star_ask.SEEN]}]
    reader.rose = 2
    ask.view_shown(VIEW, reader)
    assert len(win.toasts.shown) == 1, "once, ever"


def test_a_later_window_with_it_seen_never_asks_and_other_hints_are_kept():
    win = Win({"hints_seen": ["keep_watched:lib-1", star_ask.SEEN]})
    ask = star_ask.StarAsk(win)
    ask.view_shown(VIEW, Reader(3))
    assert win.toasts.shown == [] and win.services.settings.sets == []
    fresh = Win({"hints_seen": ["keep_watched:lib-1"]})
    star_ask.StarAsk(fresh).view_shown(VIEW, Reader(1))
    assert fresh.services.settings.values["hints_seen"] == ["keep_watched:lib-1", star_ask.SEEN]


@pytest.mark.parametrize("blocker", ["setup", "drag", "toast", "sort", "minimized"])
def test_never_over_anything_owed_until_it_is_gone(blocker):
    """Setup, a drag, another toast (its Undo; or the next one would replace this: review A-2), the sort screen (A-5),
    a minimized window: owed, then asked at the first view after — no new cards needed."""
    win, reader = Win(), Reader(1)
    ask = star_ask.StarAsk(win)
    if blocker == "setup":
        win.services.setup_open.set()
    elif blocker == "drag":
        win.toasts.dragging = True
    elif blocker == "toast":
        win.toasts.alive = True
    elif blocker == "sort":
        win._sort_screen = object()
    else:
        win.minimized = True
    ask.view_shown(VIEW, reader)
    ask.view_shown(VIEW, reader)
    assert win.toasts.shown == [] and ask.owed and "hints_seen" not in win.services.settings.values
    win.services.setup_open.clear()
    win.toasts.dragging = win.toasts.alive = win.minimized = False
    win.__dict__.pop("_sort_screen", None)
    ask.view_shown(VIEW, reader)
    assert len(win.toasts.shown) == 1 and not ask.owed


def test_unreadable_settings_never_ask():
    win = Win()

    def held():
        raise OSError("held")
    win.services.settings.get = held
    star_ask.StarAsk(win).view_shown(VIEW, Reader(1))
    assert win.toasts.shown == []


def test_star_opens_the_repository_in_the_browser_and_not_now_does_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(star_ask.qpress, "open", lambda win, target, **kw: opened.append(target))
    win = Win()
    star_ask.StarAsk(win).view_shown(VIEW, Reader(1))
    (_m, _b, _l, buttons), = win.toasts.shown
    buttons[1][2]()
    assert opened == []
    buttons[0][2]()
    assert opened == [settings_strings.STAR_URL] == ["https://github.com/SonicSandbox/surasura"]
    assert all(len(tip) <= 50 for _label, tip, _cb in buttons)


def test_settings_app_keeps_a_quiet_star_row_beside_the_version():
    app = [r.id for r in settings_catalog.rows("app")]
    assert app.index("star_github") == app.index("version") - 1
    row = settings_catalog.ROW["star_github"]
    assert row.kind == "link" and settings_strings.LINK_URLS["star_github"] == settings_strings.STAR_URL


# --- the real window and reader ------------------------------------------------------------------------------------ #
def _settle():
    for _ in range(25):
        wait_until(lambda: False, 0.02)


def _asked(win):
    return win.toasts.alive and win.toasts.text == strings.STAR_ASK


def _no_cards(lib, tiers):
    return [r["id"] for r in sorted(lib._items.values(), key=lambda r: r["id"])
            if r["tier"] in tiers and not lib._cards.get(r["id"])]


def test_the_window_asks_once_when_its_first_cards_land(world):  # noqa: F811
    """No ask at the open (the seed's items hold cards already); Connect recording an episode's cards (the store's
    cards, the item's row touched) shows the ask once, recorded; more cards later ask nothing."""
    seed, win, _writer = world()
    lib = seed.library
    first, second = _no_cards(lib, ("now", "soon"))[:2]
    _settle()
    assert win.services.library.cards_rose() == 0 and not _asked(win)
    lib._cards[first] = [1, 2]
    lib.commit(items=[{"id": first, "watched": 0}])
    assert wait_until(lambda: _asked(win), 10)
    assert star_ask.SEEN in win.services.settings.get()["hints_seen"]
    win.toasts.close()
    lib._cards[second] = [3]
    lib.commit(items=[{"id": second, "watched": 0}])
    assert wait_until(lambda: win.services.library.cards_rose() == 2, 10)
    _settle()
    assert not _asked(win)


def test_a_show_with_old_cards_back_in_current_never_asks(world):  # noqa: F811
    """Review A-1: a 6+ Months item whose cards were made long ago, put back into Current, is asked for its cards for
    the first time there — its count is where it starts, never a landing. A later real landing still asks."""
    seed, win, _writer = world()
    lib = seed.library
    goal = _no_cards(lib, ("goal",))[0]
    fresh = _no_cards(lib, ("now", "soon"))[0]
    _settle()
    lib._cards[goal] = [7, 8, 9]                             # made long ago, while it sat in 6+ Months
    lib.commit(items=[{"id": goal, "tier": "now", "ord": -1.0}], order=True)
    assert wait_until(lambda: win.services.library._cards.get(goal) == 3, 10)
    _settle()
    assert win.services.library.cards_rose() == 0 and not _asked(win)
    lib._cards[fresh] = [10]
    lib.commit(items=[{"id": fresh, "watched": 0}])
    assert wait_until(lambda: _asked(win), 10)
