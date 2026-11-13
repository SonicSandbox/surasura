"""A Python Qt object deleted later is kept until it goes (`app/qt/press.py`'s `let_go`; Qt-C2, after Qt-C's install-press
crash, tests/FLAKES.md).

PyQt6's `deleteLater()` lets go of the parent's hold on a Python object's wrapper. One in reference cycles (any
`connect(lambda: self…)`) is then freed by the next collection while its C++ object lives on until the loop deletes it —
and C++ may still call into its Python half meanwhile: an event filter on something that outlives it, its own `event()`
(it hears the DeferredDelete itself). A collection that starts inside such a call frees the object sip is calling into:
the process dies (0xC0000005). Each place the window deletes one later goes through `let_go`.

What a wrong answer would cost a learner: the app gone in the middle of a press — closing setup, sorting New arrivals,
typing a search, switching the language — with nothing said; and every confirmation or pasted text leaving its shadow and
its card's Python half on the window for good.

The crash is made on demand, as Qt-C's test_press does it: a fresh object let go, then a collection armed to start at
each of the next allocations while an event goes into its Python half (the old code died there, every run).
"""
import gc
import weakref

import pytest

pytest.importorskip("PyQt6")
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget

from app.qt import add_menu, confirm, first_run, shadow, sort_screen
from tests.qt.test_first_run import _host, window  # noqa: F401  (the real main window, the wizard's stand-in api)
from tests.qt.test_search import ask, world  # noqa: F401  (a window on the seed with its search and a writer)
from tests.qt.test_drag import _stones_sheet  # noqa: F401  (autouse: the stones drawn before the window opens)


def _deleted_later():
    """The loop's deletes, as its next passes make them: a delete can post another (a card's shadow goes after it), and
    PyQt lets go of a deleted button's connections (their lambdas hold the card) through a posted event of its own."""
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QCoreApplication.sendPostedEvents()


def _alive(refs):
    return [name for name, r in refs.items() if r() is not None]


def _kept_then_let_go(refs):
    """Every wrapper in `refs` (name -> weak reference) kept through a collection until the loop deletes its C++
    object, then let go with it."""
    gc.collect()
    assert _alive(refs) == list(refs)                      # kept while C++ may still call into it
    _deleted_later()
    gc.collect()
    assert _alive(refs) == []                              # gone with it: nothing held for good


def _collections_inside(make, poke, n=10):
    """The crash on demand: `n` times, `make()` a fresh object let go (young: no collection since), then a collection
    armed to start at the k-th allocation inside `poke()` — a call from C++ into its Python half (`n` past the
    allocations of the live Python filters called before it: the new controller's, the area's own)."""
    was = gc.get_threshold()
    gc.disable()
    try:
        gc.collect()
        for k in range(n):
            make()
            gc.set_threshold(gc.get_count()[0] + k, 1000, 1000)
            gc.enable()
            poke()
            gc.disable()
    finally:
        gc.set_threshold(*was)
        gc.enable()
    _deleted_later()


@pytest.fixture
def room(qapp):
    win = QWidget()
    win.resize(900, 600)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()
    win.deleteLater()
    _deleted_later()


# --- the cards over a window: a confirmation, the paste card ---------------------------------------------------- #
def test_a_confirmation_answered_is_kept_until_it_goes_then_its_card_scrim_and_shadow_all_go(room):
    # its scrim and the card filter the window until the loop deletes them; the card's shadow (`shadow.Follower`, a
    # child of the window) was never deleted: it stayed on the window for good, holding the card's Python half
    before = len(room.findChildren(shadow.Follower))
    card = confirm.ask(room, "Remove 2 frequency lists?", "They move to the trash folder, never deleted.", "Remove",
                       "Move the lists to the trash folder", default_no=True, on_answer=lambda yes: None)
    QApplication.processEvents()
    refs = {"card": weakref.ref(card), "scrim": weakref.ref(card.scrim), "shadow": weakref.ref(card.shadow)}
    card.close()                                           # No
    del card
    _kept_then_let_go(refs)
    assert len(room.findChildren(shadow.Follower)) == before


def test_the_paste_card_closed_is_kept_until_it_goes_then_its_card_scrim_and_shadow_all_go(room):
    before = len(room.findChildren(shadow.Follower))
    card = add_menu.PasteCard(room, lambda title, text: None)
    card.open()
    QApplication.processEvents()
    refs = {"card": weakref.ref(card), "scrim": weakref.ref(card.scrim), "shadow": weakref.ref(card.shadow)}
    card.close()                                           # Cancel
    del card
    _kept_then_let_go(refs)
    assert len(room.findChildren(shadow.Follower)) == before


def test_a_shadow_goes_with_its_overlay_whichever_way_the_overlay_goes(room):
    # the Follower's own rule, not only the two cards': its target deleted at once (not later) takes it too
    target = QWidget(room)
    follower = shadow.Follower(target, "dialog")
    ref = weakref.ref(follower)
    del follower
    sip.delete(target)
    _deleted_later()
    gc.collect()
    assert ref() is None and room.findChildren(shadow.Follower) == []


# --- a cover over the central area (Sort my library again's load screen, the sort screen) ------------------------- #
class _Screen(QWidget):
    """A cover as the load and sort screens are: a connection of its own to itself (a reference cycle)."""
    stop = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.stops = 0
        self.stop.connect(lambda: setattr(self, "stops", self.stops + 1))


@pytest.fixture
def shell_like(qapp):
    win = QMainWindow()
    area = QWidget()
    QVBoxLayout(area).addWidget(QPushButton("Generate", area))
    win.setCentralWidget(area)
    win.resize(900, 600)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()
    win.deleteLater()
    _deleted_later()


def test_a_cover_taken_off_is_kept_until_it_goes_while_its_follower_still_filters_the_area(shell_like):
    # `cover_window`'s cover goes with `first_run._Cover` under it, which filters the central area (outliving it)
    cover = sort_screen.cover_window(shell_like)
    w = _Screen()
    cover(w)
    QApplication.processEvents()
    refs = {"cover": weakref.ref(w), "follow": weakref.ref(w.findChild(first_run._Cover))}
    del w
    cover(None)
    _kept_then_let_go(refs)


def test_a_collection_inside_the_area_s_event_after_a_cover_went_is_harmless(shell_like):
    # the crash on demand: the old code died here (the cover's _Cover freed inside sip's call into its eventFilter)
    cover = sort_screen.cover_window(shell_like)
    area = shell_like.centralWidget()
    _collections_inside(lambda: (cover(_Screen()), cover(None)),
                        lambda: QCoreApplication.sendEvent(area, QEvent(QEvent.Type.PolishRequest)))
    assert cover.covered() is None and area.findChildren(first_run._Cover) == []


# --- setup's wizard: closed (*Finish later*), and its own cover taken off ------------------------------------------ #
def _answered():
    """The workers' answers in (a wizard's pending look holds it until its answer comes: then nothing does) — the
    queued calls only, never the loop's deletes."""
    QThreadPool.globalInstance().waitForDone(5000)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall.value)


def test_the_wizard_closed_is_kept_until_it_goes(window):  # noqa: F811
    # its `_Cover` (a child) filters the central area until the loop deletes the wizard
    wiz = _host(window)
    QApplication.processEvents()
    wiz.finished.emit("later")                             # *Finish later*
    _answered()
    refs = {"wizard": weakref.ref(wiz), "follow": weakref.ref(wiz.findChild(first_run._Cover))}
    del wiz
    assert first_run.opened(window) is None
    _kept_then_let_go(refs)


def test_the_wizards_own_cover_taken_off_is_kept_until_it_goes(window):  # noqa: F811
    # the load screen, then the sort screen, over the wizard (`_cover`): the sort screen hears its own DeferredDelete
    wiz = _host(window)
    QApplication.processEvents()
    w = _Screen()
    wiz._cover(w)
    refs = {"cover": weakref.ref(w)}
    del w
    wiz._cover(None)
    _kept_then_let_go(refs)


def test_the_sort_screen_over_the_window_closed_is_kept_until_it_goes(window):  # noqa: F811
    # New arrivals' *Sort them all…*: the screen's `_Cover` filters the central area, and the screen hears its own
    # DeferredDelete
    screen = sort_screen.open_over(window)
    QApplication.processEvents()
    refs = {"screen": weakref.ref(screen), "follow": weakref.ref(screen.findChild(first_run._Cover))}
    screen.finish("closed")                                # Esc / ✕
    del screen
    _answered()
    _kept_then_let_go(refs)


# --- a search's results refilled with fewer hits ------------------------------------------------------------------ #
def test_a_hit_row_a_refill_drops_is_kept_until_it_goes(world):  # noqa: F811
    # a HitRow has an `event()` of its own: the loop's DeferredDelete goes into its Python half
    from app.qt.search import HitRow
    _seed, win, _writer = world()
    results = ask(win, "星")
    groups = results.groups
    assert sum(len(g.hits) for g in groups) >= 2, "setup: the seed's search shows fewer than two hits"
    fewer = tuple(g._replace(hits=g.hits[:1]) for g in groups)
    refs = {f"row {i}": weakref.ref(r) for i, r in enumerate(results.hits) if r.hit not in
            {h for g in fewer for h in g.hits}}
    assert refs and all(isinstance(r(), HitRow) for r in refs.values())
    results.show_groups(results.query, fewer)
    _kept_then_let_go(refs)


# --- a language switch: the drags' controller remade ------------------------------------------------------------- #
def test_the_drags_controller_a_language_switch_leaves_is_kept_until_it_goes(world):  # noqa: F811
    # its `_Resting` (under its timer) filters the list's viewport until the loop deletes the controller
    from app.qt import drag
    _seed, win, writer = world()
    old = win.moves
    resting = [c for c in old.findChildren(QObject) if isinstance(c, drag._Resting)]
    refs = {"controller": weakref.ref(old), "resting": weakref.ref(resting[0])}
    del old, resting
    win._show_switched(win._reader_shown, writer)
    assert refs["controller"]() is not win.moves
    _kept_then_let_go(refs)
