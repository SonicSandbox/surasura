"""AnkiConnect missing, on screen (alpha 8, Mado-A): the one part setup's Anki step, Settings' *Connection* row and
*Needs you*'s Anki line (Mado-N) show when AnkiConnect may be missing (`ankiconnect_addon.needs_addon`), and the one
watch that runs *Check again* by itself.

- **`AddonSteps`**: *Copy code* (2055492159 on the clipboard; its press says *Copied* at once, its name again
  `COPIED_MS` later, the button never narrower meanwhile) beside the three steps on one line. The host hands its own
  button maker, so the part wears the host's look (the wizard's buttons, Settings' doors).
- **`Watch`**: while armed and its widget is on screen and live (not under the setup wizard, which disables the
  window's parts), every `EVERY` s on the shell's status poll (the window's one existing timer, `ShellWindow._poll`;
  none, no watch) it takes the light look (`ankiconnect_addon.answers`, on a worker, one at a time) and, the first
  time it has news (AnkiConnect answers; an Anki seen running is gone; an Anki opened where the last look saw none,
  once it has gone `SETTLE` s unanswered — a starting Anki loads AnkiConnect first), calls the host's *Check again*;
  the news it called on stays in `news`.
  Nothing loops: a tick off screen, unarmed or with a look out is a flag read; it stops with its widget.
- **Install AnkiConnect for me** (3.0.1, Sonic's AC-1…AC-5; `app/connect/ankiconnect_install.py`): a host that hands
  its AnkiConnect address, its *Check again* and its tick (`url=`, `checked=`, `timer=`) gets the button first, above
  *Or add it in Anki yourself:* and the steps — only where the install's look (`ankiconnect_install.look`, a few file
  checks on a worker, taken each time the host wants the steps anew) says it can (`can-install`); `there` names
  AnkiConnect in Anki but not answering (restart Anki, or turn it on). The press: the sheet (*Install* · *Back*), then
  the route on a thread of its own (it may wait 10 minutes for Anki to close; the bottom bar lists it): *Close Anki and
  Surasura installs AnkiConnect right away* + *Cancel* while Anki is open, *Installing AnkiConnect…*, then *AnkiConnect
  is installed* + *Open Anki* (the learner's own press: Anki on Connect's profile, never Connect's kick — AC-4) or the
  reason in a few words. ONE install state for the process (`state()`): every part on screen — setup's, Settings',
  *Needs you*'s, one rebuilt — shows the same press, and a part with a press under way stays on screen though its host
  no longer wants the steps (`want`: the host's wish; Anki closed to let the install go). The done line's own watch
  runs the host's *Check again* once AnkiConnect answers (or an Anki opened without it: then `there` says restart).
  The route looks at the process list only while a waiting line is on screen (`state().shown`).
  Update only what changed (S19): the part's view is one tuple, painted only when it differs (`paints` counts them).
"""
import threading
import time
import weakref

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app import ankiconnect_addon as A
from app import theme
from app.connect import ankiconnect_install as I
from app.qt import bridge, confirm, strings, style
from app.qt import press as qpress

ASKING, WAITING, RUNNING, INSTALLED, FAILED = "asking", "waiting", "running", "installed", "failed"
SEEN_MS = 1000                      # while the route runs: how often "is any of it on screen?" is asked again
QUIET_S = 300                       # the done line's *Open Anki*: Connect isn't woken when Anki answers this soon after
HOLDING = (ASKING, WAITING, RUNNING, INSTALLED)     # a part with one of these stays on screen (`want`)


class _State(QObject):
    """The install's one state in the process: its `phase` (None, or one of the five), the failure's `line`, the
    route's `cancel`, the last look (`found`, None until one came), whether a waiting line is on screen (`shown`, an
    Event the route reads from its thread). `changed` tells every part."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.phase, self.line, self.found, self.cancel = None, None, None, None
        self.looking = False
        self.shown = threading.Event()
        self.parts = weakref.WeakSet()
        self.bar = None                    # the window whose bottom bar lists the route's job (a weak reference)
        self.opened_at = None              # when the done line's *Open Anki* was pressed (`quiet_open`)
        self._seen = QTimer(self)          # while the route runs: is any of it on screen? (`update_shown`)
        self._seen.setInterval(SEEN_MS)
        self._seen.timeout.connect(self.update_shown)
        self.changed.connect(self._timer)

    def _timer(self):
        live = self.phase in (RUNNING, WAITING)
        if live != self._seen.isActive():
            (self._seen.start if live else self._seen.stop)()

    def set(self, **values):
        if any(getattr(self, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(self, k, v)
            self.changed.emit()

    def look(self):
        """The install's look on a worker (one out at a time); its answer to every part."""
        if self.looking:
            return
        self.looking = True

        def came(found):
            self.looking = False
            self.set(found=found)

        def failed(_info):
            self.looking = False
        bridge.run_in_worker(I.look, then=came, failed=failed)

    def update_shown(self):
        """The route may look at the process list (`shown`): it runs, and its line is on screen in a part, or its job
        in the bottom bar of a window shown and not minimised (the bar's *Waiting for Anki to close*)."""
        bar = self.bar() if self.bar is not None else None
        on = self.phase in (RUNNING, WAITING) and (
            any(not sip.isdeleted(p) and p.isVisible() for p in list(self.parts))
            or (bar is not None and not sip.isdeleted(bar) and bar.isVisible() and not bar.isMinimized()))
        if on != self.shown.is_set():
            (self.shown.set if on else self.shown.clear)()


_STATE = None


def state():
    """The process's install state (made on the window's thread, the application its parent)."""
    global _STATE
    if _STATE is None or sip.isdeleted(_STATE):
        _STATE = _State(QApplication.instance())
    return _STATE


def holding():
    """Is an install press under way (or its done line not yet answered)? Its parts stay on screen."""
    return _STATE is not None and not sip.isdeleted(_STATE) and _STATE.phase in HOLDING


def answered():
    """A host's look found AnkiConnect answering: an install's done line goes (it held its part on screen)."""
    if _STATE is not None and not sip.isdeleted(_STATE) and _STATE.phase == INSTALLED:
        _STATE.set(phase=None)


def quiet_open():
    """Was Anki just opened from an install's done line (AC-4 A: that press never wakes Connect)? Asked once: *Needs
    you*'s line, when AnkiConnect answers, skips its own wake-up then."""
    if _STATE is None or sip.isdeleted(_STATE) or _STATE.opened_at is None:
        return False
    recent = time.monotonic() - _STATE.opened_at < QUIET_S
    _STATE.opened_at = None
    return recent


def _quiet_after(_settings):
    """*Open Anki* from the done line: nothing after the start — never Connect's kick (AC-4 A; `open_anki.for_you`'s
    default is `kick_when_open`). The part's own watch runs the host's *Check again* once AnkiConnect answers."""


class AddonSteps(QWidget):
    """*Copy code* + the steps; with `url` (and `checked`, `timer`), *Install AnkiConnect for me* above them.
    `button(text, tip)` -> a button in the host's look; `say(text)`: the host's bar line (the press's words for where to
    paste it); `name`: the labels' object name (their style); `url()`: the AnkiConnect address now; `checked()`: the
    host's *Check again*; `timer`: the tick the done line's watch rides (`ticker`). The host shows it with `want`."""

    def __init__(self, button, name, say=None, parent=None, url=None, checked=None, timer=None):
        super().__init__(parent)
        self.say = say
        self._copies = 0
        self._want = False
        self._unsure = False
        self._view = None
        self._url, self._checked = url, checked
        self.paints = 0                                  # S19: views painted (only when what it shows changed)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(_px(6))
        # the install row: the button, a line, Cancel / Open Anki
        self.install_row = QWidget(self)
        inst = QHBoxLayout(self.install_row)
        inst.setContentsMargins(0, 0, 0, 0)
        inst.setSpacing(_px(10))
        self.install = self.cancel_btn = self.open_btn = None   # made the first time one shows (`_buttons`)
        self._make, self._inst = button, inst
        self.install_line = _line(name, "", self.install_row)
        inst.addWidget(self.install_line, 1)
        self.install_line.setVisible(False)
        self.install_row.setVisible(False)
        col.addWidget(self.install_row)
        self.heading = _line(name, I.OR_YOURSELF, self)
        self.heading.setVisible(False)
        col.addWidget(self.heading)
        # the steps row (Mado-A's part as it was)
        self.steps_row = QWidget(self)
        row = QHBoxLayout(self.steps_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.copy = button(A.COPY, A.COPY_TIP)
        self.copy.setAccessibleName(A.COPY)
        self.copy.clicked.connect(lambda _c=False: self.copy_code())
        row.addWidget(self.copy, 0, Qt.AlignmentFlag.AlignVCenter)
        self.line = _line(name, A.steps_line(), self.steps_row)
        self.line.setWordWrap(True)
        row.addWidget(self.line, 1)
        col.addWidget(self.steps_row)
        self.done_watch = None
        if url is not None:
            st = state()
            st.parts.add(self)
            st.changed.connect(self._paint)
            self.destroyed.connect(lambda _o=None, s=st, f=self._paint: _disconnect_signal(s.changed, f))
            self.done_watch = Watch(self, timer, url, self._answered)
        self._paint()

    def _button(self, text, tip, press, action):
        b = self._make(text, tip)
        b.setAccessibleName(text)
        b.setProperty("action", action)
        b.clicked.connect(lambda _c=False: press())
        b.setVisible(False)
        return b

    def _buttons(self):
        """The install row's three buttons, made once — the first time the install can be offered (a host where it
        never can holds none)."""
        if self.install is None:
            self.install = self._button(I.BUTTON, I.BUTTON_TIP, self.press_install, "install_ankiconnect")
            self.cancel_btn = self._button(I.CANCEL, I.CANCEL_TIP, self.press_cancel, "cancel_ankiconnect")
            self.open_btn = self._button(I.OPEN, I.OPEN_TIP, self.press_open, "open_anki_installed")
            self._inst.insertWidget(0, self.install, 0, Qt.AlignmentFlag.AlignVCenter)
            self._inst.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self._inst.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    # --- the host's wish ------------------------------------------------------------------------------------------ #
    def want(self, on):
        """The host wants the steps on screen (AnkiConnect may be missing) or not. The part shows while it is wanted
        or while an install press is under way; wanted anew, the install looks again (a few file checks)."""
        on = bool(on)
        fresh = on and not self._want
        self._want = on
        if fresh and self._url is not None:
            state().look()
        self._paint()

    def set_unsure(self, unsure):
        """*Open Anki* first when the look couldn't tell a closed Anki from AnkiConnect missing."""
        text = A.steps_line(unsure=bool(unsure))
        if self.line.text() != text:
            self.line.setText(text)
        if bool(unsure) != self._unsure:
            self._unsure = bool(unsure)    # a look that can't tell whether Anki runs: no button (spec 5.4 step 2)
            self._paint()

    # --- the view ------------------------------------------------------------------------------------------------- #
    def view(self):
        """What the part shows now -> (visible, install row, its line or None, the button, Cancel, Open Anki, the
        heading, the steps): one tuple, painted only when it changes."""
        st = _STATE if self._url is not None and _STATE is not None and not sip.isdeleted(_STATE) else None
        phase = st.phase if st is not None else None
        found = (st.found or {}) if st is not None else {}
        line, button, cancel, opened = None, False, False, False
        if phase == WAITING:
            line, cancel = I.WAITING_LINE, True
        elif phase == RUNNING:
            line = I.RUNNING_LINE
        elif phase == INSTALLED:
            line, opened = self._done_line(), True
        else:
            if phase == FAILED and st.line:
                line = st.line
            if (found.get("state") == I.CAN_INSTALL and not self._unsure) or phase == ASKING:
                button = True
            elif found.get("state") == I.THERE and line is None:
                line = I.TURNED_OFF_LINE if found.get("disabled") else I.THERE_LINE
        visible = self._want or phase in HOLDING
        steps = self._want
        heading = steps and (button or phase in HOLDING or phase == FAILED)
        row = line is not None or button or cancel or opened
        return (visible, row, line, button, cancel, opened, heading, steps)

    def _done_line(self):
        from app import anki_connect
        try:
            url = str(self._url() or "") if self._url is not None else ""
        except Exception:
            url = ""
        if url and url.rstrip("/") != anki_connect.DEFAULT_URL.rstrip("/"):
            return I.DONE_ELSEWHERE.format(url=url)
        return I.DONE_LINE

    def _paint(self):
        if sip.isdeleted(self):
            return
        view = self.view()
        if view != self._view:
            self._view = view
            self.paints += 1
            visible, row, line, button, cancel, opened, heading, steps = view
            if button or cancel or opened:
                self._buttons()
            if line is not None and self.install_line.text() != line:
                self.install_line.setText(line)
            _show(self.install_line, line is not None)
            for b, on in ((self.install, button), (self.cancel_btn, cancel), (self.open_btn, opened)):
                if b is not None:
                    _show(b, on)
            _show(self.install_row, row)
            _show(self.heading, heading)
            _show(self.steps_row, steps)
            _show(self, visible)
        if self.done_watch is not None and self.done_watch.armed != view[5]:
            self.done_watch.arm(view[5], False)           # the done line: Check again once AnkiConnect answers
        if self._url is not None:
            state().update_shown()

    def showEvent(self, event):
        super().showEvent(event)
        if self._url is not None:
            state().update_shown()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._url is not None:
            state().update_shown()

    # --- the presses ---------------------------------------------------------------------------------------------- #
    def press_install(self):
        """The button: the sheet first (nothing fetched before its *Install*); then the route on its own thread."""
        st = state()
        if st.phase in HOLDING:
            return
        win = self.window()
        p = qpress.begin(self.install, "addon:install", win=win)
        st.set(phase=ASKING, line=None)
        once = []

        def answered(yes):
            if once:
                return
            once.append(yes)
            if p is not None:
                qpress.end(p, win)
            if sip.isdeleted(st) or st.phase != ASKING:
                return
            if not yes:
                st.set(phase=None)                       # *Back* (or the sheet dropped): nothing fetched
                return
            _start(st, _registry(self), win)
        card = confirm.ask(win, I.SHEET_TITLE, I.SHEET_BODY, I.SHEET_YES, I.SHEET_YES_TIP, no=I.SHEET_NO,
                           no_tip=I.SHEET_NO_TIP, on_answer=answered)
        if isinstance(card, QObject):                    # dropped unanswered (the window hid, the wizard closed)
            card.destroyed.connect(lambda _o=None: answered(False))

    def press_cancel(self):
        st = state()
        if st.cancel is not None:
            st.cancel.set()

    def press_open(self):
        """The done line's *Open Anki* (AC-4 A, PROVISIONAL): Anki on Connect's profile, the learner's press; never
        Connect's kick. The part's watch runs the host's *Check again* once AnkiConnect answers."""
        from app.connect import open_anki

        state().opened_at = time.monotonic()

        def started(answer):
            if answer is False and self.say is not None and not sip.isdeleted(self):
                self.say(strings.NEEDS_ANKI_NOT_STARTED)
        qpress.run(self.open_btn, "addon:open-anki", open_anki.for_you, None, _quiet_after, then=started,
                   win=self.window())

    def _answered(self):
        """The done line's watch: AnkiConnect answers (or an Anki opened without it): the done line goes, the host
        checks again."""
        st = state()
        if st.phase == INSTALLED:
            st.set(phase=None)
            st.look()
        if self._checked is not None:
            self._checked()

    def copy_code(self):
        QApplication.clipboard().setText(A.CODE)
        self.copy.setMinimumWidth(self.copy.width())      # *Copied* is shorter: the button keeps its width
        self.copy.setText(A.COPIED)
        self._copies = press = self._copies + 1           # a second press restarts the wait

        def back():
            if not sip.isdeleted(self.copy) and self._copies == press:
                self.copy.setText(A.COPY)
        QTimer.singleShot(A.COPIED_MS, back)
        if self.say is not None:
            self.say(A.COPIED_LINE)


def _start(st, registry, window=None):
    """The route after the sheet's *Install*: on a daemon thread of its own (never the window's pool: it may wait for
    Anki to close), listed in `registry`; its phases and its end come back to the window's thread."""
    cancel = threading.Event()
    phases, ended = bridge.Relay(st), bridge.Relay(st)
    phases.said.connect(lambda now: st.set(phase=now) if st.phase in (WAITING, RUNNING) else None)

    def end(result):
        phases.deleteLater()
        ended.deleteLater()
        if result == I.INSTALLED:
            st.set(phase=INSTALLED, line=None, cancel=None)
        elif result in (I.DECLINED, I.CANCELLED):
            st.set(phase=None, line=None, cancel=None)
        else:
            st.set(phase=FAILED, line=I.said(result), cancel=None)
        st.look()                                         # what's in Anki's folder now
    ended.said.connect(end)
    st.bar = weakref.ref(window) if window is not None and registry is not None else None
    st.set(phase=RUNNING, line=None, cancel=cancel)
    st.update_shown()

    def run():
        I.install_as_job(registry, None, cancel, ended.call, confirm=lambda: True, shown=st.shown.is_set,
                         on_phase=phases.call)
    threading.Thread(target=run, name="ankiconnect-install", daemon=True).start()


def _px(n):
    """A gap at the window's text size (the wizard's own rule)."""
    return round(n * theme.text_factor(style.current()[1]))


def _line(name, text, parent):
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _show(widget, on):
    if widget.isHidden() == bool(on):
        widget.setVisible(bool(on))


def _registry(widget):
    """The window's job registry (the bottom bar lists the install), or None."""
    w = widget.window() if not sip.isdeleted(widget) else None
    while w is not None:
        for owner in (w, getattr(w, "shell", None)):
            registry = getattr(getattr(owner, "services", None), "registry", None)
            if registry is not None:
                return registry
        w = w.parentWidget()
    return None


def _disconnect_signal(signal, slot):
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        pass


def ticker(shell):
    """The shell's status poll (`POLL_MS`), the timer the watch rides; None for a shell without one."""
    timer = getattr(shell, "_poll", None)
    return timer if isinstance(timer, QTimer) else None


class Watch(QObject):
    """*Check again* by itself. `widget`: the part whose being on screen keeps it looking; `timer`: the tick (`ticker`);
    `url()`: the AnkiConnect address now; `answered()`: the host's *Check again*. `arm(on)` as the part shows."""

    def __init__(self, widget, timer, url, answered):
        super().__init__(widget)
        self.widget, self.url, self.answered = widget, url, answered
        self.armed = False
        self.seen = None                  # the host's last look: an Anki process seen True, none False, can't tell None
        self.looking = False
        self.news = None                  # the light look's news the host was last called on (`answers`' answer)
        self._opened = None               # when the looks began seeing an Anki opened, unanswered (`SETTLE`)
        self._last = 0.0
        self._timer = timer
        if timer is not None:
            timer.timeout.connect(self._tick)
            self.destroyed.connect(lambda _o=None, t=timer: _disconnect(t, self._tick))

    def arm(self, on, seen=None):
        """On: the first light look `EVERY` s from now (the host has just looked); off: none. `seen`: the host's look's
        `running` (False: the light look watches for an Anki opened too)."""
        on = bool(on)
        if on and not self.armed:
            self._last = time.monotonic()
        if not on or seen is not False:
            self._opened = None
        self.armed, self.seen = on, seen

    def _tick(self):
        if not self.armed or self.looking or not self._live():
            return
        now = time.monotonic()
        if now - self._last < A.EVERY:
            return
        self._last = now
        self.looking = True
        bridge.run_in_worker(A.answers, self.url(), self.seen, then=self._looked,
                             failed=lambda _info: self._looked(False))

    def _looked(self, news):
        if sip.isdeleted(self):
            return
        self.looking = False
        self._last = now = time.monotonic()
        if news == A.OPENED:                              # A8N-1: AnkiConnect missing only once Anki has had time to
            if self._opened is None:                      # load it (else *Open Anki* flashes the steps)
                self._opened = now
            if now - self._opened < A.SETTLE:
                return
        else:
            self._opened = None
        if news and self.armed and self._live():
            self.armed = False                            # once: the host's look arms it again if Anki still isn't in
            self.news = news
            self.answered()


    def _live(self):
        """Its part on screen and taking input (the setup wizard over the window disables the parts under it)."""
        return not sip.isdeleted(self.widget) and self.widget.isVisible() and self.widget.isEnabled()


def _disconnect(timer, slot):
    try:
        if not sip.isdeleted(timer):
            timer.timeout.disconnect(slot)
    except (TypeError, RuntimeError):
        pass
