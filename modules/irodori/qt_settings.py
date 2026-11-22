# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings › App › Beta · *AI audio for cards without audio* (README § What the learner sees, 1).

`attach(page)` -> `AiAudioRow`, filled into the catalog's `ai_audio` slot by the shell's `mount_settings` (guarded:
this module absent, the row isn't there). The switch writes `enable_irodori` only; ticking it shows two lines — what
it is, the download's size and speed on this PC — and *Install*; installed: its size and *Remove*. Every look, the
install and the removal run on a worker; the install's steps come back through a Relay; *Stop* cancels it.
"""
import threading

from PyQt6 import sip
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.qt import applog, bridge, windows
from app.qt import press as qpress
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from modules.irodori import qt_strings as S

ROW_ID = "ai_audio"


def attach(page):
    return AiAudioRow(page)


def _gb(n):
    return f"{(n or 0) / 1e9:.1f}"


def _look():
    """(A worker.) -> (status, the backend Install would choose, the GPU card or None)."""
    from modules.irodori import runtime
    card = runtime.gpu()
    return runtime.status(), runtime.backend(card), card


def _install(say, cancel):
    from modules.irodori import runtime
    return runtime.install(say=lambda step, of, what: say((step, of, what)), cancel=cancel)


def _remove():
    from modules.irodori import runtime
    return runtime.remove()


class AiAudioRow(QWidget):
    """The switch, the two lines, Install / Stop / Remove. `state`: the last look's (status, backend, card)."""

    def __init__(self, page):
        slot = page.custom_row(ROW_ID)
        super().__init__(slot)
        self.page, self.store = page, page.store
        row = catalog.ROW[ROW_ID]
        self.state = None
        self.installing = None                      # the install's cancel Event while it runs
        self.lines = bridge.Relay(self)
        self.lines.said.connect(self._step)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.toggle = sc.Toggle(bool(self.store.get().get("enable_irodori")), tooltip=row.tip, name=row.label,
                                parent=self)
        self.toggle.changed.connect(self._toggled)
        top.addWidget(self.toggle)
        top.addStretch(1)
        box.addLayout(top)
        self.about = QLabel(S.ABOUT, self)
        self.about.setWordWrap(True)
        self.line = QLabel(S.LOOKING, self)
        self.line.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        self.install = qpress.room(sc.Door(S.INSTALL, tooltip=S.INSTALL_TIP, name=f"{row.label}: {S.INSTALL}"))
        self.install.clicked.connect(lambda _c=False: self.start_install())
        self.stop = sc.Door(S.STOP, tooltip=S.STOP_TIP, name=f"{row.label}: {S.STOP}")
        self.stop.clicked.connect(lambda _c=False: self.stop_install())
        self.remove = qpress.room(sc.Door(S.REMOVE, tooltip=S.REMOVE_TIP, name=f"{row.label}: {S.REMOVE}"))
        self.remove.clicked.connect(lambda _c=False: self.start_remove())
        for b in (self.install, self.stop, self.remove):
            buttons.addWidget(b)
        buttons.addStretch(1)
        box.addWidget(self.about)
        box.addWidget(self.line)
        box.addLayout(buttons)
        slot.layout().addWidget(self)
        heard = getattr(page, "bridge", None)
        if heard is not None and hasattr(heard, "settings_written"):
            heard.settings_written.connect(self._written)
        self._show()
        self.look()

    # --- state ------------------------------------------------------------------------------------------------- #
    def alive(self):
        return self.page is not None and not sip.isdeleted(self.page) and not sip.isdeleted(self)

    def on(self):
        return bool(self.toggle.value())

    def say(self, text):
        applog.log("settings", text)
        windows.say_in_bar(getattr(self.page, "shell", None), text)

    def _show(self):
        """What shows follows the switch and the last look: off — the switch alone; on — the lines and the buttons."""
        on = self.on()
        status = (self.state or (None,))[0] or {}
        busy = self.installing is not None
        for w in (self.about, self.line):
            w.setVisible(on)
        self.install.setVisible(on and not busy and self.state is not None and not status.get("installed"))
        self.stop.setVisible(on and busy)
        self.remove.setVisible(on and not busy and bool(status.get("installed") or status.get("stale")))

    def _text(self):
        status, chosen, card = self.state
        if status.get("installed"):
            where = S.WHERE_CPU if status.get("backend") in (None, "cpu") else S.WHERE_GPU
            return S.INSTALLED.format(gb=_gb(status.get("size_bytes")), where=where)
        from modules.irodori import runtime
        text = S.NEEDS_INSTALL.format(gb=f"{runtime.SIZE_GB[chosen]:.0f}")
        return f"{S.OLDER} {text}" if status.get("stale") else text

    def _time(self):
        """The time a sentence takes on the backend in use (installed) or Install's choice — the line's hover only,
        never a visible line or a warning (PROVISIONAL words)."""
        status, chosen, card = self.state
        backend = (status.get("backend") or "cpu") if status.get("installed") else chosen
        return S.TIME_CPU if backend in (None, "cpu") else S.TIME_GPU.format(card=(card or {}).get("name", ""))

    def look(self):
        bridge.run_in_worker(_look, then=self._looked, failed=lambda info: applog.log("settings", f"AI audio: {info}"))

    def _looked(self, state):
        if not self.alive():
            return
        self.state = state
        if self.installing is None:
            self.line.setText(self._text())
            self.line.setToolTip(self._time())
        self._show()

    # --- the switch ------------------------------------------------------------------------------------------- #
    def _toggled(self, on):
        self.store.set({"enable_irodori": bool(on)})
        self._show()

    def _written(self, keys):
        if self.alive() and "enable_irodori" in set(keys or ()):
            self.toggle.set_value(bool(self.store.get().get("enable_irodori")))
            self._show()

    # --- install / remove ------------------------------------------------------------------------------------- #
    def start_install(self):
        if self.installing is not None:
            return
        self.installing = cancel = threading.Event()
        self.line.setText(S.INSTALLING.format(step=1, of=6, what="…"))
        self._show()
        qpress.run(self.install, "irodori:install", _install, self.lines.call, cancel, then=self._installed,
                   failed=self._install_failed, win=getattr(self.page, "shell", None))

    def _step(self, value):
        if self.alive() and self.installing is not None and value:
            step, of, what = value
            self.line.setText(S.INSTALLING.format(step=step, of=of, what=what))

    def stop_install(self):
        if self.installing is not None:
            self.installing.set()

    def _installed(self, _status):
        self.installing = None
        if self.alive():
            self.say(S.INSTALLED_DONE)
            self.look()

    def _install_failed(self, info):
        self.installing = None
        from modules.irodori import runtime
        error = info[0] if info else None
        text = S.INSTALL_STOPPED if isinstance(error, runtime.Cancelled) else S.INSTALL_FAILED.format(why=error)
        applog.log("settings", f"AI audio install: {info[1] if info and len(info) > 1 else info}")
        if self.alive():
            self.line.setText(text)
            self.say(text)
            self.look()

    def start_remove(self):
        qpress.run(self.remove, "irodori:remove", _remove, then=self._removed, failed=self._remove_failed,
                   win=getattr(self.page, "shell", None))

    def _removed(self, freed):
        if self.alive():
            self.say(S.REMOVED.format(gb=_gb(freed)))
            self.look()

    def _remove_failed(self, info):
        if self.alive():
            self.say(S.REMOVE_FAILED.format(why=info[0] if info else ""))
            self.look()
