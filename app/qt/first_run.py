"""The setup wizard over the window (W3.5 part 3; the window's spec 05 §5.8; the contract `w35wiz/contract.md`).

`host(shell)`: after the window's first frame, when `setup_wizard.should_open(settings)` says so (a clean profile: no
`onboarding_completed`; or, once, a profile set up in 2.x that never saw these pages), the wizard covers the window's central area — below Windows' own title bar, following every
resize — and the header, tabs, pages and bottom bar under it take no focus while it is up. `open_again(shell)`:
Settings' *Set up again* — the same wizard, preselected from the settings as they are now.

The wizard closes onto Current (opened again from Settings: back onto the tab it came from): after its Generate ends,
after *Skip* on its last page, or by *Finish later* (which keeps what was saved with *Next* and never writes
`onboarding_completed`). The shell mounts it with one call in `start_duties`; while it is up the shell's `setup_held(True)` holds the quiet Generates (AD-8), `setup_held(False)` at
its close asks again. `open_again(shell, page="cards")`: Settings' *Install Anki Miner…* — the wizard at its Anki Miner
page (the one place the install route, its confirm and its checks live).
"""
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QSize, Qt

from app.qt import applog
from app.qt import wizard as wizard_module

ATTR = "_setup_wizard"                                  # the open wizard, on its main window
OWN_MINIMUM, COVER_NEEDS = "_own_minimum", "_cover_needs"     # on the main window: its own minimum; each cover's need


class _Cover(QObject):
    """Keeps the wizard (or any cover: the sort screen, a load screen) over the whole central area as the window is
    resized — and the window's minimum size one where the cover fits (Mado-P, Sonic's alpha 9 try: "Text is cut off if
    my screen isn't fully expanded"). A cover is placed by its geometry, outside the window's layouts, so the window
    never learnt the room it needs and let itself be made smaller: buttons narrower than their words, a title's
    second line cut. While the cover is shown, the window's minimum is its own (`theme.WINDOW_MIN`) grown to the
    cover's minimum size hint plus the window's parts round the central area — never past the screen's room — asked
    again as the cover's layout changes; the window's own minimum comes back when the cover hides or goes."""

    def __init__(self, wiz, area):
        super().__init__(wiz)
        self.wiz, self.area = wiz, area
        self.win = area.window()
        self.win.__dict__.setdefault(OWN_MINIMUM, self.win.minimumSize())
        area.installEventFilter(self)
        wiz.installEventFilter(self)
        key, win = id(self), self.win
        wiz.destroyed.connect(lambda *_a: _needs(win, key, None))
        self._ask()

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj is self.area and kind == QEvent.Type.Resize and not sip.isdeleted(self.wiz):
            self.wiz.setGeometry(self.area.rect())
            self._ask()                                  # (its words wrap again at the new width: their height)
        if obj is self.wiz and kind in (QEvent.Type.LayoutRequest, QEvent.Type.Show):
            self._ask()
        elif obj is self.wiz and kind == QEvent.Type.Hide and not event.spontaneous():
            _needs(self.win, id(self), None)
        return False

    def _ask(self):
        if sip.isdeleted(self.wiz) or sip.isdeleted(self.win) or self.wiz.isHidden():
            return
        need = self.wiz.minimumSizeHint().expandedTo(self.wiz.minimumSize())
        if self.wiz.hasHeightForWidth():                  # wrapped words take their lines at the width it has
            need.setHeight(max(need.height(), self.wiz.heightForWidth(max(need.width(), self.area.width()))))
        around = self.win.size() - self.area.size() if self.area.isVisible() else QSize(0, 0)
        room = _room(self.win)
        _needs(self.win, id(self), need + around if room is None else (need + around).boundedTo(room))


def _room(win):
    """The most a window's inside can be on its screen (its frame taken off), or None: no window may need more (one
    bigger than its screen can't be used)."""
    screen = win.screen()
    if screen is None:
        return None
    return screen.availableGeometry().size() - (win.frameGeometry().size() - win.size())


def _needs(win, key, need):
    """Cover `key` needs `need` (None: nothing any more): the window's minimum is its own grown to every need."""
    if sip.isdeleted(win):
        return
    needs = win.__dict__.setdefault(COVER_NEEDS, {})
    if need is None:
        needs.pop(key, None)
    else:
        needs[key] = need
    want = win.__dict__.get(OWN_MINIMUM, win.minimumSize())
    for size in needs.values():
        want = want.expandedTo(size)
    if want != win.minimumSize():
        win.setMinimumSize(want)


def opened(shell):
    """The wizard open over `shell`, or None."""
    wiz = shell.__dict__.get(ATTR)
    return wiz if wiz is not None and not sip.isdeleted(wiz) else None


def host(shell, api=None, miner=None):
    """The first run: the wizard over the window while setup isn't finished. -> the wizard, or None (never raises:
    a wizard that can't open leaves the window as it is, and says why in the log)."""
    try:
        api = api if api is not None else wizard_module.services_api()
        if not api.should_open(wizard_module.thaw(shell.services.settings.get())):
            return None
        return _open(shell, api, miner)
    except Exception as e:
        applog.log("wizard", f"the setup wizard didn't open: {e}")
        return None


def open_again(shell, api=None, miner=None, page=None, resort=None):
    """Settings' *Set up again*: the wizard, preselected from the settings now (finished or not); `page` (a page id,
    `wizard.PAGES`) shown first. -> the wizard, or None (never raises into Settings' click: a wizard that can't open
    leaves the window as it is, and says why in the log). `resort(changes)` (Fresh library's *Change folders…*): the
    folders page alone, its *Next* handing back {"add", "stop", "skip"} — it never reads a folder itself (P11)."""
    try:
        back = shell.current_tab() if hasattr(shell, "current_tab") else "current"
        wiz = _open(shell, api, miner, back=back, resort=resort)
        if resort is not None:
            return wiz
    except Exception as e:
        applog.log("wizard", f"the setup wizard didn't open again: {e}")
        return None
    if page is not None and page in wizard_module.PAGES:
        try:
            wiz._go(wizard_module.PAGES.index(page))
        except Exception as e:                            # the wizard is up: it stays, on the page it shows
            applog.log("wizard", f"the setup wizard's {page} page: {e}")
    return wiz


def _open(shell, api, miner, back="current", resort=None):
    wiz = opened(shell)
    if wiz is not None:
        wiz.raise_()
        return wiz if resort is None else None            # (setup up: *Change folders…* waits for it)
    area = shell.centralWidget()
    held = _hold(area)
    _say_held(shell, True)
    wiz = None
    try:
        wiz = wizard_module.SetupWizard(shell, parent=area, api=api, miner=miner, resort=resort)
        wiz.setGeometry(area.rect())
        _Cover(wiz, area)
        wiz.finished.connect(lambda how, w=wiz: _closed(shell, w, held, how, back))
    except Exception:
        _release(held)                                    # never a window held under a wizard that isn't there
        _say_held(shell, False)
        if wiz is not None and not sip.isdeleted(wiz):
            from app.qt import press as qpress
            qpress.let_go(wiz)                            # (its `_Cover` filters the area until it goes)
        raise
    shell.__dict__[ATTR] = wiz
    wiz.show()
    wiz.raise_()
    wiz.start_focus()
    return wiz


def _hold(area):
    """The window's own parts under the wizard (header, tabs, pages, bar) take no focus while it is up: disabled, and
    given back as they were when it closes."""
    held = []
    layout = area.layout()
    for i in range(layout.count() if layout is not None else 0):
        w = layout.itemAt(i).widget()
        if w is not None and w.isEnabled():
            w.setEnabled(False)
            held.append(w)
    return held


def _say_held(shell, up):
    """The shell's `setup_held(up)` (the quiet Generates wait while the wizard is up), when it has one."""
    hold = getattr(shell, "setup_held", None)
    if hold is not None:
        try:
            hold(up)
        except Exception as e:
            applog.log("wizard", f"the window's hold: {e}")


def _release(held):
    for w in held:
        if not sip.isdeleted(w):
            w.setEnabled(True)


def _closed(shell, wiz, held, how, back="current"):
    """The wizard closed (`how`: later · done · generated): the window's parts back, `back` shown (Current at a first
    run, the tab *Set up again* came from)."""
    _release(held)
    _say_held(shell, False)
    if shell.__dict__.get(ATTR) is wiz:
        shell.__dict__.pop(ATTR, None)
    if not sip.isdeleted(wiz):
        from app.qt import press as qpress
        wiz.hide()
        qpress.let_go(wiz)                                # (its `_Cover` filters the area until it goes: Qt-C2)
    try:
        shell.show_tab(back)                              # first run: Current; *Set up again*: where it came from
        rest = getattr(shell, "_rest", None)
        if rest is not None:
            rest.setFocus(Qt.FocusReason.OtherFocusReason)
    except RuntimeError:                                  # the window is going
        pass
