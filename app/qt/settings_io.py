"""Settings › App › *Your settings* (alpha 6, Mattias's note 8; leans SI-1…SI-5, PROVISIONAL): ***Export settings…***
and ***Import settings…***, drawn into the slot the page leaves for the row (`custom_row`). The window decides nothing:
what goes in the file, what an import keeps, the words it asks with and the write are `app/services/settings_io.py`'s.

`attach(page)` -> `SettingsFileRow`: called once by whoever mounts the page (the shell's `mount_settings`), beside the
other rows' packages — never by the page itself.

- **Export:** Save-as (the file named for today), then `settings_io.export` on a worker; the bar says where it went or
  why not. The pressed button's arc turns while it writes (round 8 row 45).
- **Import:** the file picked, then read and judged on a worker (`settings_io.read`): refused — empty, not a settings
  file, from a newer Surasura — the bar says why and nothing is asked. Else asked ONCE before anything is replaced
  (`confirm.ask`, No by default; Esc, Back or a click outside is No) in the service's words (`question`); yes →
  `settings_io.apply` on a worker (a dated copy first, the file replaced whole), then the window restarts the quit's
  way (`shell.restart`: every reader starts from the new file). Never while a Generate runs: a restart would stop it
  (B2-3), so the bar says to import once it ends — asked before the file is picked and again at the answer.

GUI_Design_Guidelines_Qt: the page's controls (no new rules), a tooltip on each button.
"""
import os

from PyQt6 import sip
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog

from app.qt import applog, confirm, strings, windows
from app.qt import press as qpress
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_strings as S
from app.services import settings_io

ROW_ID = "settings_file"


def attach(page):
    """*Export settings…* and *Import settings…* filled into `page`'s slot -> their `SettingsFileRow`."""
    return SettingsFileRow(page)


class SettingsFileRow(QObject):
    """`export` / `import_`: the row's two buttons; `asking`: the import's question while it is open."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.shell = page.shell
        self.services = page.services
        self.asking = None
        self.said = []
        row = catalog.ROW[ROW_ID]
        self.export = qpress.room(sc.Door(S.SETTINGS_EXPORT, tooltip=S.SETTINGS_EXPORT_TIP,
                                          name=f"{row.label}: {S.SETTINGS_EXPORT}"))
        self.export.clicked.connect(lambda _c=False: self.export_settings())
        self.import_ = qpress.room(sc.Door(S.SETTINGS_IMPORT, tooltip=S.SETTINGS_IMPORT_TIP,
                                           name=f"{row.label}: {S.SETTINGS_IMPORT}"))
        self.import_.clicked.connect(lambda _c=False: self.import_settings())
        slot = page.custom_row(ROW_ID).layout()
        slot.addWidget(self.export)
        slot.addWidget(self.import_)
        # the dialogs, replaceable by a test: (title, name) -> a path or "", and (title) -> a path or ""
        self.save_as = lambda title, name: QFileDialog.getSaveFileName(page, title, name, S.SETTINGS_FILES)[0]
        self.open_file = lambda title: QFileDialog.getOpenFileName(page, title, "", S.SETTINGS_FILES)[0]

    def alive(self):
        return self.page is not None and not sip.isdeleted(self.page)

    def say(self, text):
        self.said.append(text)
        if self.shell is not None and hasattr(self.shell, "bar_line"):
            windows.say_in_bar(self.shell, text)

    def _failed(self, info):
        applog.log("settings", f"settings file: {info[1] if info and len(info) > 1 else info}")
        if self.alive():
            self.say(S.SETTINGS_FAILED.format(why=info[0] if info else ""))

    def _generating(self):
        return bool(getattr(self.shell, "generating", lambda: False)())

    # --- export ---------------------------------------------------------------------------------------------------- #
    def export_settings(self):
        path = self.save_as(S.SETTINGS_EXPORT_TITLE, settings_io.default_name())
        if not path:
            return None
        if not path.lower().endswith(".json"):
            path += ".json"
        return qpress.run(self.export, f"settings:{ROW_ID}:export", settings_io.export, os.path.normpath(path),
                          then=self._outcome, failed=self._failed, win=self.shell)

    def _outcome(self, outcome):
        if self.alive():
            self.say(outcome.message)

    # --- import ---------------------------------------------------------------------------------------------------- #
    def import_settings(self):
        if self._generating():
            self.say(S.SETTINGS_IMPORT_AFTER_GENERATE)
            return None
        path = self.open_file(S.SETTINGS_IMPORT_TITLE)
        if not path:
            return None
        return qpress.run(self.import_, f"settings:{ROW_ID}:import", settings_io.read, os.path.normpath(path),
                          then=self._read, failed=self._failed, win=self.shell)

    def _read(self, plan):
        if not self.alive():
            return
        if plan.refused is not None:
            self.say(plan.refused)
            return
        title, body, yes = settings_io.question(plan)
        self.asking = confirm.ask(self.page, title, body, yes, S.SETTINGS_IMPORT_YES_TIP, no=S.SETTINGS_IMPORT_NO,
                                  no_tip=S.SETTINGS_IMPORT_NO_TIP, default_no=True,
                                  on_answer=lambda answer: self._answered(plan, answer))

    def _answered(self, plan, yes):
        self.asking = None
        if not yes or not self.alive():
            return
        if self._generating():
            self.say(S.SETTINGS_IMPORT_AFTER_GENERATE)
            return
        qpress.run(self.import_, f"settings:{ROW_ID}:import", settings_io.apply, plan,
                   getattr(self.services, "settings", None), then=self._applied, failed=self._failed, win=self.shell)

    def _applied(self, outcome):
        if not self.alive():
            return
        self.say(outcome.message)
        if not outcome.ok:
            return
        restart = getattr(self.shell, "restart", None)
        if restart is None or self._generating():
            self.say(strings.RESTART_TO_APPLY)
            return
        restart()
