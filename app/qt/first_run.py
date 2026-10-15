"""The setup wizard over the window (W3.5 part 3; the window's spec 05 §5.8; the contract `w35wiz/contract.md`).

`host(shell)`: after the window's first frame, when `setup_wizard.should_open(settings)` says so (a clean profile: no
`onboarding_completed`), the wizard covers the window's central area — below Windows' own title bar, following every
resize — and the header, tabs, pages and bottom bar under it take no focus while it is up. `open_again(shell)`:
Settings' *Set up again* — the same wizard, preselected from the settings as they are now.

The wizard closes onto Current: after its Generate ends, after *Skip* on its last page, or by *Finish later* (which
keeps what was saved with *Next* and never writes `onboarding_completed`). The shell mounts it with one call in
`start_duties` (the patch in the W3.5 part 3 notes): this module never edits the shell.
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


def open_again(shell, api=None, miner=None):
    """Settings' *Set up again*: the wizard, preselected from the settings now (finished or not). -> the wizard, or
    None (never raises into Settings' click: a wizard that can't open leaves the window as it is, and says why in the
    log)."""
    try:
        return _open(shell, api, miner)
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
    try:
        wiz = wizard_module.SetupWizard(shell, parent=area, api=api, miner=miner)
    except Exception:
        _release(held)
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


def _release(held):
    for w in held:
        if not sip.isdeleted(w):
            w.setEnabled(True)


def _closed(shell, wiz, held, how):
    """The wizard closed (`how`: later · done · generated): the window's parts back, Current shown."""
    _release(held)
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
