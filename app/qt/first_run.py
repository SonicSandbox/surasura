"""The setup wizard over the window (W3.5 part 3; the window's spec 05 §5.8; the contract `w35wiz/contract.md`).

`host(shell)`: after the window's first frame, when `setup_wizard.should_open(settings)` says so (a clean profile: no
`onboarding_completed`; or, once, a profile set up in 2.x that never saw these pages), the wizard covers the window's central area — below Windows' own title bar, following every
resize — and the header, tabs, pages and bottom bar under it take no focus while it is up. `open_again(shell)`:
Settings' *Set up again* — the same wizard, preselected from the settings as they are now.

The wizard closes onto Current: after its Generate ends, after *Skip* on its last page, or by *Finish later* (which
keeps what was saved with *Next* and never writes `onboarding_completed`). The shell mounts it with one call in
`start_duties`; while it is up the shell's `setup_held(True)` holds the quiet Generates (AD-8), `setup_held(False)` at
its close asks again. `open_again(shell, page="cards")`: Settings' *Install Anki Miner…* — the wizard at its Anki Miner
page (the one place the install route, its confirm and its checks live).
"""
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, Qt

from app.qt import applog
from app.qt import wizard as wizard_module

ATTR = "_setup_wizard"                                  # the open wizard, on its main window


class _Cover(QObject):
    """Keeps the wizard over the whole central area as the window is resized."""

    def __init__(self, wiz, area):
        super().__init__(wiz)
        self.wiz, self.area = wiz, area
        area.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.area and event.type() == QEvent.Type.Resize and not sip.isdeleted(self.wiz):
            self.wiz.setGeometry(self.area.rect())
        return False


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


def open_again(shell, api=None, miner=None, page=None):
    """Settings' *Set up again*: the wizard, preselected from the settings now (finished or not); `page` (a page id,
    `wizard.PAGES`) shown first. -> the wizard, or None (never raises into Settings' click: a wizard that can't open
    leaves the window as it is, and says why in the log)."""
    try:
        wiz = _open(shell, api, miner)
        if page is not None and page in wizard_module.PAGES:
            wiz._go(wizard_module.PAGES.index(page))
        return wiz
    except Exception as e:
        applog.log("wizard", f"the setup wizard didn't open again: {e}")
        return None


def _open(shell, api, miner):
    wiz = opened(shell)
    if wiz is not None:
        wiz.raise_()
        return wiz
    area = shell.centralWidget()
    held = _hold(area)
    _say_held(shell, True)
    try:
        wiz = wizard_module.SetupWizard(shell, parent=area, api=api, miner=miner)
    except Exception:
        _release(held)
        _say_held(shell, False)
        raise
    wiz.setGeometry(area.rect())
    _Cover(wiz, area)
    shell.__dict__[ATTR] = wiz
    wiz.finished.connect(lambda how, w=wiz: _closed(shell, w, held, how))
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


def _closed(shell, wiz, held, how):
    """The wizard closed (`how`: later · done · generated): the window's parts back, Current shown."""
    _release(held)
    _say_held(shell, False)
    if shell.__dict__.get(ATTR) is wiz:
        shell.__dict__.pop(ATTR, None)
    if not sip.isdeleted(wiz):
        wiz.hide()
        wiz.deleteLater()
    try:
        shell.show_tab("current")
        rest = getattr(shell, "_rest", None)
        if rest is not None:
            rest.setFocus(Qt.FocusReason.OtherFocusReason)
    except RuntimeError:                                  # the window is going
        pass
