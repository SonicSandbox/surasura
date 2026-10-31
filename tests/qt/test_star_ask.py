"""Surasura's star ask (`app/qt/star_ask.py`; Sonic, 2026-10-31): once, ever, when cards from the learner's own show
first land in Anki.

What a wrong answer would cost: an ask shown every start, or again after *Not now* — a nag in a free app; one shown
at the window's first view for cards that were already there (no first win, just a box at start); one over setup or
under the hand mid-drag; a call of the app's own to GitHub (the link is the browser's, CLAUDE.md §1).
"""
import threading
from collections import namedtuple

import pytest

from app.qt import settings_catalog, settings_strings, star_ask, strings
from tests.qt.conftest import wait_until
from tests.qt.test_drag import world  # noqa: F401 (a fixture)

View = namedtuple("View", "mode cached loading")
WHOLE = View("store", False, False)


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
        self.shown, self.dragging = [], False

    def show(self, message, undo=None, buttons=(), long=False):
        self.shown.append((message, [b[0] for b in buttons], long, buttons))


class Win:
    def __init__(self, values=None):
        self.services = type("S", (), {})()
        self.services.settings = Settings(values)
        self.services.setup_open = threading.Event()
        self.toasts = Toasts()


class Reader:
    """`LibraryReader.cards()`'s contract: a new dict whenever a count moves, the same object until then."""

    def __init__(self, cards=None):
        self._cards = dict(cards or {})

    def cards(self):
        return self._cards

    def land(self, item, n):
        self._cards = {**self._cards, item: n}


def test_cards_already_there_at_open_never_ask_and_the_first_new_ones_ask_once():
    win, reader = Win(), Reader({7: 12})
    ask = star_ask.StarAsk(win)
    ask.view_shown(View("store", True, False), reader)       # the first screen's cache: no counts to start from
    ask.view_shown(View("store", False, True), reader)       # loading
    ask.view_shown(WHOLE, reader)
    ask.view_shown(WHOLE, reader)
    assert win.toasts.shown == []
    reader.land(9, 20)                                       # Connect made an episode's cards
    ask.view_shown(WHOLE, reader)
    assert [(m, b, long) for m, b, long, _ in win.toasts.shown] == [
        (strings.STAR_ASK, [strings.STAR_ASK_STAR, strings.STAR_ASK_NOT_NOW], True)]
    assert win.services.settings.sets == [{"hints_seen": [star_ask.SEEN]}]
    reader.land(11, 5)
    ask.view_shown(WHOLE, reader)
    assert len(win.toasts.shown) == 1, "once, ever"


def test_a_later_window_with_it_seen_never_asks_and_other_hints_are_kept():
    win = Win({"hints_seen": ["keep_watched:lib-1", star_ask.SEEN]})
    reader = Reader()
    ask = star_ask.StarAsk(win)
    ask.view_shown(WHOLE, reader)
    reader.land(3, 9)
    ask.view_shown(WHOLE, reader)
    assert win.toasts.shown == [] and win.services.settings.sets == []
    fresh = Win({"hints_seen": ["keep_watched:lib-1"]})
    ask = star_ask.StarAsk(fresh)
    reader = Reader()
    ask.view_shown(WHOLE, reader)
    reader.land(3, 9)
    ask.view_shown(WHOLE, reader)
    assert fresh.services.settings.values["hints_seen"] == ["keep_watched:lib-1", star_ask.SEEN]


def test_a_count_that_only_went_down_or_came_back_never_asks():
    win, reader = Win(), Reader({1: 10, 2: 4})
    ask = star_ask.StarAsk(win)
    ask.view_shown(WHOLE, reader)
    reader._cards = {1: 10}                                  # cards deleted in Anki
    ask.view_shown(WHOLE, reader)
    reader._cards = {1: 10, 2: 4}                            # back as it was at open: nothing new landed
    ask.view_shown(WHOLE, reader)
    assert win.toasts.shown == []


@pytest.mark.parametrize("blocker", ["setup", "drag"])
def test_never_over_setup_or_a_drag_owed_until_both_are_gone(blocker):
    win, reader = Win(), Reader()
    ask = star_ask.StarAsk(win)
    ask.view_shown(WHOLE, reader)
    if blocker == "setup":
        win.services.setup_open.set()
    else:
        win.toasts.dragging = True
    reader.land(4, 8)
    ask.view_shown(WHOLE, reader)
    ask.view_shown(WHOLE, reader)
    assert win.toasts.shown == [] and ask.owed and "hints_seen" not in win.services.settings.values
    win.services.setup_open.clear()
    win.toasts.dragging = False
    ask.view_shown(WHOLE, reader)                            # the next view after it: no new cards needed
    assert len(win.toasts.shown) == 1 and not ask.owed


def test_a_language_switch_starts_from_the_new_readers_first_view():
    win = Win()
    ask = star_ask.StarAsk(win)
    ask.view_shown(WHOLE, Reader())
    ask.view_shown(WHOLE, Reader({5: 30}))                   # Chinese's library, its cards there already
    assert win.toasts.shown == []


def test_unreadable_settings_never_ask():
    win, reader = Win(), Reader()

    def held():
        raise OSError("held")
    win.services.settings.get = held
    ask = star_ask.StarAsk(win)
    ask.view_shown(WHOLE, reader)
    reader.land(1, 1)
    ask.view_shown(WHOLE, reader)
    assert win.toasts.shown == []


def test_star_opens_the_repository_in_the_browser_and_not_now_does_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(star_ask.qpress, "open", lambda win, target, **kw: opened.append(target))
    win, reader = Win(), Reader()
    ask = star_ask.StarAsk(win)
    ask.view_shown(WHOLE, reader)
    reader.land(2, 3)
    ask.view_shown(WHOLE, reader)
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


def _settle():
    for _ in range(25):
        wait_until(lambda: False, 0.02)


def test_the_window_asks_once_when_its_first_cards_land(world):  # noqa: F811
    """The real window and reader: no ask at the open; Connect recording an episode's cards (the store's cards, the
    item's row touched) shows the ask once, recorded; more cards later ask nothing."""
    seed, win, _writer = world()
    lib = seed.library
    first, second = [r["id"] for r in sorted(lib._items.values(), key=lambda r: r["id"])
                     if r["tier"] in ("now", "soon") and not lib._cards.get(r["id"])][:2]    # (the seed's others have cards)
    _settle()
    assert win.star_ask._base is not None and not (win.toasts.alive and win.toasts.text == strings.STAR_ASK)
    lib._cards[first] = [1, 2]
    lib.commit(items=[{"id": first, "watched": 0}])
    assert wait_until(lambda: win.toasts.alive and win.toasts.text == strings.STAR_ASK, 10)
    assert star_ask.SEEN in win.services.settings.get()["hints_seen"]
    win.toasts.close()
    lib._cards[second] = [3]
    lib.commit(items=[{"id": second, "watched": 0}])
    assert wait_until(lambda: win.services.library.cards().get(second) == 1, 10)
    _settle()
    assert not (win.toasts.alive and win.toasts.text == strings.STAR_ASK)
