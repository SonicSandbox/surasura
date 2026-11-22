# SPDX-License-Identifier: GPL-3.0-or-later
"""Anki Backfill's *AI sentence audio (beta)…* (README § What the learner sees, 3): add only, never over audio a
card already has.

`attach(window, row)` adds the button to Backfill's actions row (guarded in `modules/junban/qt_backfill.py`: this
module absent, nothing). It shows only while the beta is on, the voice installed and the shared writer there (read on
a worker). A press:

    count (Backfill's deck; only notes with an empty SentenceAudio and a sentence)  ->  "N cards have no sentence
    audio." + *Make it*  ->  the run on a worker (its progress in Backfill's job line; the window's close stops it
    between two sentences)  ->  *Undo AI audio*

Add only: the shared writer fills an empty field and nothing else, and reads each note again first.
"""
import threading

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

from app.qt import bridge, confirm
from app.qt import press as qpress
from modules.irodori import qt_strings as S


def attach(window, row):
    return BackfillAiAudio(window, row)


def _settings(window):
    from app.services.settings import thaw
    return thaw(window.services.settings.get())


def _language(settings):
    from modules.junban import reposition
    return reposition._language(settings)


def _shown(settings):
    """(A worker.) -> (the beta on, installed, the writer there, a Japanese library; the last Backfill run that can
    still be undone, or None)."""
    try:
        from modules import irodori
        from modules.irodori import writer
        language = _language(settings)
        # the last run of any door (Connect's book cards too): its Undo needs only the shared writer, never the voice
        last = irodori.last_run(language) if writer.available() else None
        return bool(irodori.on(settings, language)), last
    except Exception:
        return False, None


def _count(settings):
    """(A worker.) Backfill's deck's notes with an empty SentenceAudio -> (note ids, the dry run's report)."""
    from modules import irodori
    from modules.junban import backfill
    ids = irodori.find_empty(settings, backfill._deck(settings) or None)
    return ids, irodori.make_for_notes(settings, _language(settings), ids, dry_run=True)


def _make(settings, ids, say, cancel):
    from modules import irodori
    return irodori.make_for_notes(settings, _language(settings), ids, say=lambda d, n, _t: say((d, n)),
                                  cancel=cancel, verb="AI sentence audio (Backfill)", source="backfill")


def _undo(settings, run_id):
    from modules import irodori
    return irodori.undo(settings, _language(settings), run_id)


class BackfillAiAudio:
    """The button (`button`), then *Undo AI audio* for the last run (`undo_button`); `run` the last run's id."""

    def __init__(self, window, row):
        self.window = window
        self.run = None
        self.busy = False
        self.cancel = getattr(window, "stop", None) or threading.Event()      # the window's: set at its close
        self.lines = bridge.Relay(window)
        self.lines.said.connect(self._progress)
        self.button = qpress.room(self._button(S.BACKFILL, S.BACKFILL_TIP, self.press))
        self.undo_button = qpress.room(self._button(S.UNDO, S.UNDO_TIP, self.press_undo))
        row.insertWidget(1, self.button)
        row.insertWidget(2, self.undo_button)
        self.button.setVisible(False)
        self.undo_button.setVisible(False)
        bridge.run_in_worker(_shown, _settings(window), then=self._show)

    def _button(self, text, tip, slot):
        b = QPushButton(text, self.window)
        b.setToolTip(tip)
        b.setAccessibleName(text)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _alive(self):
        return not getattr(self.window, "gone", False) and not sip.isdeleted(self.window)

    def _say(self, text):
        if text and self._alive():
            self.window._write(text)

    def _show(self, got):
        on, last = got
        if self._alive():
            self.button.setVisible(bool(on))
            if last and not self.run:               # a run of an earlier window or of Connect: its Undo stays offered
                self.run = last["run"]
                self.undo_button.setVisible(True)

    def press(self):
        if self.busy:
            return
        self.busy = True
        self._say(S.COUNTING)
        qpress.run(self.button, "irodori:count", _count, _settings(self.window), then=self._counted,
                   failed=self._failed, win=self.window)

    def _counted(self, got):
        self.busy = False
        ids, report = got
        if not self._alive():
            return
        from modules.irodori import make
        line = make.count_line(report)
        for problem in report.get("problems") or ():
            self._say(problem)
        if not report.get("todo"):
            self._say(line)
            return

        def answered(yes):
            if yes:
                self._start(ids)
        confirm.ask(self.window, S.BACKFILL.rstrip("…"), line, S.MAKE, S.MAKE_TIP, on_answer=answered)

    def _start(self, ids):
        self.busy = True
        self._say(S.MAKING.format(done=0, of="…"))
        qpress.run(self.button, "irodori:make", _make, _settings(self.window), ids, self.lines.call, self.cancel,
                   then=self._made, failed=self._failed, win=self.window)

    def _progress(self, value):
        if value and self._alive():
            done, of = value
            self.window._set_job_line(S.MAKING.format(done=done, of=of))

    def _made(self, report):
        self.busy = False
        if not self._alive():
            return
        self.window._set_job_line(None)
        for problem in report.get("problems") or ():
            self._say(problem)
        self._say(report.get("message") or "")
        if report.get("run"):                       # a run that wrote nothing keeps the earlier run's Undo
            self.run = report["run"]
        self.undo_button.setVisible(bool(self.run))

    def press_undo(self):
        if self.busy or not self.run:
            return
        self.busy = True
        qpress.run(self.undo_button, "irodori:undo", _undo, _settings(self.window), self.run, then=self._undone,
                   failed=self._failed, win=self.window)

    def _undone(self, report):
        self.busy = False
        if not self._alive():
            return
        for problem in report.get("problems") or ():
            self._say(problem)
        self._say(report.get("message") or "")
        if report.get("ok"):
            self.run = None
            self.undo_button.setVisible(False)
            bridge.run_in_worker(_shown, _settings(self.window), then=self._show)     # an older run's Undo next

    def _failed(self, info):
        self.busy = False
        if self._alive():
            self.window._set_job_line(None)
            self._say(str(info[0]) if info else "")
