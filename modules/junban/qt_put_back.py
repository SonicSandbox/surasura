# SPDX-License-Identifier: GPL-3.0-or-later
""""Put Anki back the way it was before Surasura…" in Qt (W3.4 row 6; FT-RUNBOOK D8): one flow, two doors.

    plan (a worker)  ->  the confirmation with its counts  ->  [the fields question]  ->  [the older question]
                     ->  put back (a `junban` job)  ->  its lines

`PutBackFlow` is the flow (the Tk `first_touch_gui.PutBack`, its decisions in `put_back_view`): the 順 window runs it
from its actions row, `PutBackWindow` from Settings' door (Data & System; W3.3 reuses the flow there). Every question is
the shared in-window confirmation (`app/qt/confirm.py`): Esc, Back, ✕ and a click outside are No; **Enter is No on
every one of them** (🧭 IK-10c: the Tk confirm took Enter as yes; the older question already defaulted to No) — the
main one says "This can't be undone" (ONE_WAY) in its lines. The plan reads only; the write is a `junban` job (one Anki
writer in this program: the automatic re-order waits for it), and `first_touch.put_back` holds the Anki-write lock,
saves the stand-aside settings strictly first and checks the profile the confirmation described. Closing the window
stops a wait for another writer; a write already going finishes on its thread.
"""
import queue
import sys
import threading
import traceback

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from app.qt import bridge, confirm, windows
from app.qt import press as qpress
from modules.junban import put_back_view
from modules.junban import qt_strings as qs

TONES = ("problem", "warning", "good")


# --- a read off the GUI thread --------------------------------------------------------------------------------------- #
def spawn(window, fn, *args, then=None, failed=None):
    """`fn(*args)` on a daemon thread of its own; `then(value)` / `failed((exception, traceback))` on the GUI thread
    after — never once `window` closed. A daemon thread, not the pool: an Anki read or a first import can outlast the
    window, and a pool thread still running Python as the process ends takes it down (seen at exit in a child)."""
    relay = bridge.Relay(window)

    def heard(answer):
        try:
            relay.deleteLater()
        except RuntimeError:                          # its window (its parent) is gone already
            return
        ok, value = answer
        if getattr(window, "gone", False):
            return
        if ok and then is not None:
            then(value)
        elif not ok:
            if failed is not None:
                failed(value)
            else:
                print(f"A background read failed: {value[1]}", file=sys.stderr)
    relay.said.connect(heard)

    def body():
        try:
            answer = (True, fn(*args))
        except BaseException as e:                    # the answer is the failure; the thread never dies of it
            answer = (False, (e, traceback.format_exc()))
        if not getattr(window, "gone", False):
            relay.call(answer)
    threading.Thread(target=body, name=f"junban-read-{getattr(fn, '__name__', 'work')}", daemon=True).start()
    return relay


class Worker:
    """One long-lived daemon thread for a window's quick work (a click's re-plan): handing it over is a `put` that
    returns at once. A thread started per click cost the GUI thread a whole GIL switch interval (~5 ms): `start()` waits
    for the new thread, which then holds the GIL in the work (AD6-2). Only the newest request still waiting runs (an
    older one's answer would be thrown away anyway); its answer reaches the GUI thread as `spawn`'s does. `stop()` (at
    close) ends the thread."""

    def __init__(self, window, name):
        self.window = window
        self.queue = queue.Queue()
        self.relay = bridge.Relay(window)
        self.relay.said.connect(self._heard)
        self.thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self.thread.start()

    def ask(self, fn, then=None, failed=None):
        self.queue.put((fn, then, failed))

    def stop(self):
        self.queue.put(None)

    def _loop(self):
        while True:
            item = self.queue.get()
            try:
                while item is not None:               # a newer request waiting: the older is dropped
                    item = self.queue.get_nowait()
            except queue.Empty:
                pass
            if item is None:
                return
            fn, then, failed = item
            try:
                answer = (True, fn())
            except BaseException as e:                # the answer is the failure; the thread never dies of it
                answer = (False, (e, traceback.format_exc()))
            if not getattr(self.window, "gone", False):
                self.relay.call((answer, then, failed))

    def _heard(self, said):
        (ok, value), then, failed = said
        if getattr(self.window, "gone", False):
            return
        if ok and then is not None:
            then(value)
        elif not ok and failed is not None:
            failed(value)


def _quietly(fn):
    try:
        fn()
    except Exception as e:                            # a failed re-read leaves the copy as it was: said in the log
        print(f"Junban: reading the settings again failed: {e}", file=sys.stderr)


def said_when_closed(window):
    """(The GUI thread, as a write starts.) -> `tell(report)`, for any thread: when `window` closed before the write
    ended, the report's message goes to the main window's bar (IK-90: the window's own relay went with it)."""
    shell = window.shell
    relay = bridge.Relay(shell)
    relay.said.connect(lambda text: windows.say_in_bar(shell, text))

    def tell(report):
        if getattr(window, "gone", False):
            relay.call((report or {}).get("message") or "")
        relay.deleteLater()                           # thread-safe: after the line it may have queued
    return tell


# --- a job of the window's registry -------------------------------------------------------------------------------- #
def run_job(registry, label, work, on_report, stop):
    """`work(job)` as a `junban` job (one Anki writer in this program; quitting waits for a write under way): started on
    a thread of its own when the registry allows; `on_report(report)` (any thread) once, when it ends — or, cancelled
    before it started, with a report saying nothing was written. Cancelling it sets `stop` (the engine's wait for
    another Anki writer ends; a write already going finishes). -> the Job."""
    state = {"started": False, "told": False}
    guard = threading.Lock()

    def tell(report):
        with guard:
            if state["told"]:
                return
            state["told"] = True
        on_report(report)

    def start(job):
        with guard:
            state["started"] = True

        def body():
            try:
                report = work(job) or {}
            except Exception as e:                    # never past a traceback: the job ends, the window hears it
                report = {"ok": False, "message": str(e), "problems": [], "warnings": []}
            if report.get("ok"):                      # a stop that came too late: it ran to its end (A13)
                job.finish(ok=True, completed=stop.is_set())
            elif _stopped_before_writing(report):
                job.finish(ok=True, cancelled=True)
            else:                                     # a failure stays one, stop or not (AD6-5)
                # refused until the unfinished reorder's Undo: it ends waiting on you, so the 順 circle's press opens
                # 順 at that Undo (`phase.FAILED_GO`)
                job.finish(ok=False, message=_failed_words(report), completed=stop.is_set(),
                           needs=_failed_words(report) if report.get("restore_first") else None)
            tell(report)
        threading.Thread(target=body, name=f"junban-job-{job.id}", daemon=True).start()

    def cancel(_job):
        stop.set()
        with guard:
            started = state["started"]
        if not started:
            tell({"ok": False, "message": qs.JUNBAN_CANCELLED,
                  "cancelled": True, "problems": [], "warnings": []})

    return registry.submit("junban", label, start, cancel=cancel, on_quit="wait")


def _failed_words(report):
    """A failed job's words (the 順 circle's hover: *failed 19:30: …*): the engine's first problem — why, and what to
    press — else its message. "Junban did not make any changes." alone never said why (Mattias, alpha 3: an unfinished
    reorder refused every Reorder, and the hover gave no reason). PROVISIONAL (ASK lead, Michi-MT)."""
    problems = [str(p) for p in report.get("problems") or () if p]
    return problems[0] if problems else (report.get("message") or None)


def _stopped_before_writing(report):
    """The engine's refusal when the stop was set as the Anki-write lock came free (`anki_connect.CLOSED`): nothing
    was written — the one end that is "cancelled"."""
    from app import anki_connect
    return bool(report.get("cancelled")) or anki_connect.CLOSED in (report.get("problems") or ())


# --- the lines a window shows -------------------------------------------------------------------------------------- #
class Lines(QWidget):
    """A window's message lines (the Tk message pane): each a word-wrapped label whose tone (problem · warning · good)
    the stylesheet colours by token; a line ending in a link carries a small button. Hidden while empty; repainted
    only when its lines change (S19)."""

    def __init__(self, parent, name):
        super().__init__(parent)
        self.setAccessibleName(name)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(2)
        self.lines = []
        self.paints = 0
        self.link_button = None                     # the line's link chip while there is one (its press's arc)
        self.setVisible(False)

    def set_lines(self, lines, link=None):
        """Replace every line: `lines` [(text, tone)]; `link` (text, button words, tip, callback) or None."""
        lines = [(str(text), tone or "") for text, tone in lines if text]
        key = (tuple(lines), link[:3] if link else None)
        if key == (tuple(self.lines), getattr(self, "_link_key", None)):
            return
        self._clear()
        for text, tone in lines:
            self._label(text, tone)
        self._link_key = link[:3] if link else None
        if link:
            row = QHBoxLayout()
            row.setSpacing(6)
            label = QLabel(link[0], self)
            label.setObjectName("windowline")
            label.setTextFormat(Qt.TextFormat.PlainText)
            row.addWidget(label)
            button = qpress.room(QPushButton(link[1], self))
            button.setProperty("kind", "chip")
            button.setToolTip(link[2])
            button.setAccessibleName(link[1])
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.clicked.connect(lambda _c=False, f=link[3]: f())
            row.addWidget(button)
            row.addStretch(1)
            self.box.addLayout(row)
            self.link_button = button
        self.lines = lines
        self.paints += 1
        self.setVisible(bool(lines) or bool(link))
        self._fit()

    def add(self, text, tone=""):
        if not text:
            return
        self._label(str(text), tone or "")
        self.lines.append((str(text), tone or ""))
        self.paints += 1
        self.setVisible(True)
        self._fit()

    def clear(self):
        if not self.lines and getattr(self, "_link_key", None) is None:
            return
        self._clear()
        self.lines = []
        self._link_key = None
        self.paints += 1
        self.setVisible(False)
        self._fit()

    def texts(self):
        return [text for text, _tone in self.lines]

    def _fit(self):
        """Its minimum height is its wrapped lines' height at its width (IK-83): a window's minimum ignores word-wrapped
        text, so at its smallest the lines were painted over the table above them. Only when it changes (S19)."""
        height = self.box.heightForWidth(self.width()) if self.lines and self.width() > 0 else 0
        if height != self.minimumHeight():
            self.setMinimumHeight(max(0, height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._fit()

    def event(self, event):
        done = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest:  # a line just shown (Qt shows a new child a moment later)
            self._fit()
        return done

    def _label(self, text, tone):
        label = QLabel(text, self)
        label.setObjectName("windowline")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if tone in TONES:
            label.setProperty("tone", tone)
        self.box.addWidget(label)
        return label

    def _clear(self):
        self.link_button = None
        while self.box.count():
            item = self.box.takeAt(0)
            widget = item.widget()
            layout = item.layout()
            if widget is not None:
                widget.hide()                         # gone at once: a deferred delete waits for the event loop
                widget.deleteLater()
            elif layout is not None:
                while layout.count():
                    inner = layout.takeAt(0).widget()
                    if inner is not None:
                        inner.hide()
                        inner.deleteLater()


# --- the flow ------------------------------------------------------------------------------------------------------ #
class PutBackFlow(QObject):
    """One press of *Put Anki back…*, from either door, on the GUI thread. `window`: the secondary window it asks in;
    `settings`: the engine settings its door read (None: the file's, read on the worker); `show(text, tone)`,
    `busy(bool)`, `progress(done, total)`, `done(report or None)`, `begin_write()` / `end_write(line)`: the window's.
    `stop`: an Event the window sets as it closes (a wait for another writer ends)."""

    def __init__(self, window, language, registry, settings=None, show=None, busy=None, progress=None, done=None,
                 begin_write=None, end_write=None, stop=None):
        super().__init__(window)
        self.window = window
        self.language = language
        self.registry = registry
        self.settings = settings
        self.show = show or (lambda _text, _tone="": None)
        self.busy = busy or (lambda _busy: None)
        self.progress = progress
        self.done = done
        self.begin_write = begin_write or (lambda: None)
        self.end_write = end_write or (lambda _line=None: None)
        self.stop = stop if stop is not None else threading.Event()
        self.job = None
        self.questions = []                 # each confirmation asked, in order (a test reads them)
        self._relay = bridge.Relay(self)
        self._relay.said.connect(self._heard)

    def _settings_service(self):
        services = getattr(getattr(self.window, "shell", None), "services", None)
        return getattr(services, "settings", None)

    def start(self):
        self.busy(True)
        self.show(qs.PUT_BACK_READING, "")
        service, settings = self._settings_service(), self.settings

        def plan(language):
            # The door's own read of the file (C29, strict): the changes still pending in the settings service are
            # written first, so the plan sees them (IK-87).
            if settings is None and service is not None:
                service.flush(10.0)
            return put_back_view.plan_work(language, settings)
        spawn(self.window, plan, self.language,
                             then=self.window.alive(self._planned),
                             failed=self.window.alive(lambda info: self._planned({"ok": False,
                                                                                  "problems": [str(info[0])]})))

    def _moved_on(self):
        """The window switched language since this flow began: it ends here, nothing written (AD6-4: a follow-up
        question the switch closed is no answer of the user's)."""
        return getattr(self.window, "language", self.language) != self.language

    def _planned(self, plan):
        if self._moved_on():
            return self._end(qs.PUT_BACK_NOTHING)       # the window switched language meanwhile: never asked here
        out = put_back_view.outcome(plan)
        for text, tone in out["lines"]:
            self.show(text, tone)
        if "end" in out:
            return self._end(*out["end"])
        question, details = out["ask"]
        self._ask(question, "\n".join(details), qs.PUT_BACK_YES, qs.PUT_BACK_YES_TIP, None, qs.JUNBAN_CONFIRM_NO_TIP,
                  lambda yes: self._main(yes, plan, out), danger=True)

    def _ask(self, title, body, yes, yes_tip, no, no_tip, then, danger=False):
        self.questions.append(title)
        return confirm.ask(self.window, title, body, yes, yes_tip, no=no, no_tip=no_tip, default_no=True,
                           danger=danger, on_answer=then)

    def _main(self, yes, plan, out):
        if not yes or self._moved_on():
            return self._end(qs.PUT_BACK_NOTHING)
        if out.get("fields"):
            return self._ask(out["fields"], "", qs.PUT_BACK_FIELDS_YES, qs.PUT_BACK_FIELDS_YES_TIP,
                             qs.PUT_BACK_FIELDS_NO, qs.PUT_BACK_FIELDS_NO_TIP,
                             lambda fields: self._fields(bool(fields), plan, out))
        self._fields(False, plan, out)

    def _fields(self, fields, plan, out):
        if self._moved_on():
            return self._end(qs.PUT_BACK_NOTHING)
        if out.get("older"):                # K4: default No — Enter keeps them
            return self._ask(out["older"], "", qs.PUT_BACK_OLDER_YES, qs.PUT_BACK_OLDER_YES_TIP, qs.PUT_BACK_OLDER_NO,
                             qs.PUT_BACK_OLDER_NO_TIP, lambda older: self._write(fields, bool(older), plan))
        self._write(fields, None, plan)

    def _write(self, fields, older, plan):
        if self._moved_on():
            return self._end(qs.PUT_BACK_NOTHING)
        self.show(qs.PUT_BACK_WRITING, "")
        settings = plan.get("_settings") or put_back_view.plan_settings(self.language, self.settings)[0]
        language, stop, relay = self.language, self.stop, self._relay

        def progress(done, total):
            relay.call(("progress", done, total))

        def on_wait(holder):
            from app import anki_connect
            relay.call(("line", anki_connect.waiting_line(holder), "warning"))

        def work(_job):
            return put_back_view.put_back_work(language, settings, fields, older, plan, progress=progress,
                                               cancel=stop, on_wait=on_wait)
        self.begin_write()
        tell = said_when_closed(self.window)
        self.job = run_job(self.registry, qs.JUNBAN_LABEL_PUT_BACK, work,
                           lambda report: (tell(report), relay.call(("report", report, plan))), stop)

    def _heard(self, said):
        kind = said[0]
        if kind == "progress" and self.progress is not None:
            self.progress(said[1], said[2])
        elif kind == "line":
            self.show(said[1], said[2])
        elif kind == "report":
            self._finished(said[1] or {}, said[2])

    def _finished(self, report, plan):
        service = self._settings_service()
        if report.get("settings_changed") and service is not None:
            # The engine saved its stand-aside beside the settings service (`save_keys`): read again, on a thread.
            threading.Thread(target=_quietly, args=(service.reload,), name="junban-read-reload", daemon=True).start()
        lines = put_back_view.finished_lines(report, plan)
        for text, tone in lines:
            self.show(text, tone)
        self.end_write(report.get("message"))
        self.busy(False)
        if self.done is not None:
            self.done(report)

    def _end(self, line, tone=""):
        self.show(line, tone)
        self.busy(False)
        if self.done is not None:
            self.done(None)


# --- Settings' door: its own small window -------------------------------------------------------------------------- #
class PutBackWindow(windows.SecondaryWindow):
    """Settings → Data & System's door (until W3.3 gives the flow its row): the flow's lines and progress, and Close.
    Esc, Back, ✕ or Close stop a wait for another Anki writer, as closing 順 does; a write already going finishes."""

    def __init__(self, shell, language=None):
        super().__init__(shell, put_back_view.TITLE, language)
        self.stop = threading.Event()
        self.working = False
        head = QLabel(put_back_view.BUTTON_TEXT, self)
        head.setObjectName("windowheading")
        head.setWordWrap(True)
        head.setToolTip(put_back_view.BUTTON_TIP)
        self.body.addWidget(head)
        self.lines = Lines(self, put_back_view.TITLE)
        self.body.addWidget(self.lines)
        self.progress = QProgressBar(self)
        self.progress.setAccessibleName(qs.JUNBAN_PROGRESS_NAME)
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        self.body.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch(1)
        self.close_button = QPushButton(qs.PUT_BACK_CLOSE, self)
        self.close_button.setToolTip(qs.PUT_BACK_CLOSE_TIP)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.close_button.clicked.connect(lambda _c=False: self.close())
        row.addWidget(self.close_button)
        self.body.addLayout(row)
        self._started = False
        self.flow = self._new_flow()
        stop = self.stop                    # destroyed with its parent or the app quitting: a waiting write stops (AD6-6)
        self.destroyed.connect(lambda *_: stop.set())
        closing = getattr(shell, "closing", None)
        if closing is not None:
            closing.connect(self._stop_writes)

    def _stop_writes(self):
        self.stop.set()

    def _new_flow(self):
        return PutBackFlow(self, self.language, self.shell.services.registry, show=self.lines.add,
                           busy=self._set_working, progress=self._show_progress, begin_write=self.begin_write,
                           end_write=self.end_write, stop=self.stop)

    def _set_working(self, working):
        """The flow started or ended: an open 順 window follows (it starts nothing while this one asks or writes)."""
        self.working = bool(working)
        junban = windows.opened(self.shell, "junban")
        if junban is not None and hasattr(junban, "elsewhere_changed"):
            junban.elsewhere_changed()

    def _show_progress(self, done, total):
        self.progress.setMaximum(max(1, int(total or 0)))
        self.progress.setValue(int(done or 0))

    def start(self):
        """The flow, from the start: pressed again after it ended (AD6-8: the Tk door made a new window each time),
        its old lines go and a new flow reads the plan again. Never while one is asking or writing."""
        if self.working or self.gone:
            return
        if self._started:
            self.lines.set_lines([])
            self.progress.setValue(0)
            self.flow = self._new_flow()
        self._started = True
        self.flow.start()

    def language_changed(self, language):
        """The main window switched language while this one asks (its writes hold the switch back): the open
        question was about the other language's cards — closed, and the flow ends with nothing written (AD6-4)."""
        for card in self.findChildren(confirm.Confirm):
            if card.answer is None:
                card.close()

    def closeEvent(self, event):
        self.stop.set()
        super().closeEvent(event)


def open(shell):
    """Settings' door: the window for the main window's language, its flow started — refused while the 順 window has
    a run of its own going or a Generate (its answer would describe cards that run is moving): the bar says so; pressed
    again on an open window whose flow ended, the flow starts again (AD6-8). -> the window, or
    None when refused."""
    junban = windows.opened(shell, "junban")
    if junban is not None and (junban.own_work() or junban.session.generating):
        bar = getattr(shell, "bar_line", None)
        if bar is not None:
            bar.set_full(qs.JUNBAN_PUT_BACK_REFUSED)
        return None
    opened = windows.opened(shell, "put-back")
    win = windows.show(shell, "put-back", PutBackWindow)
    if win is not opened or not win.working:
        QTimer.singleShot(0, win.alive(win.start))
    return win
