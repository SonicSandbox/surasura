"""The shell: Surasura 3.0's main window (W2.1; the window's spec 01 §1.5 item 1, 05 §5.1–5.5, §5.9, §5.11–5.12).

The window, edge to edge under Windows' own title bar (n1); the header (the mark, the wordmark, the subline); the tabs
(Current · Finished · Needs you · Settings) over one page each; the bottom bar (what runs, the newest command-line
failure, the AnkiWeb mark and Connect's line when they exist). Given a library (`Services(library=…)`: W2.2's reader),
Current, Finished and Needs you show it (`screens.py`, display only until W3.1 / W3.2); without one, and Settings until
W3.3, a page shows its waiting state. The header's controls arrive with their features: no control here does nothing
(the wiring check, tests/qt/test_wiring.py).

What it holds is a view (02 §2.1): settings come from the settings service, jobs from the registry, the bar from the
status service, all through `bridge.py`; the window's size, place and tab live in `window_state.json` in this
install's local data folder, never in settings.json (S16). The look — theme and text size — is set on the
QApplication before the first paint (`open_window`), and changes live (`set_look`, P-text: W2.1 row 9).

App-wide: **Esc and the mouse's Back button** close every open overlay at once, else a secondary window, and **never
the main window** (✅ G1.2-2); Forward does nothing. Tooltips are the bubble (`tooltip.py`).

Run it: `python app_entry.py` on the 3.0 line (or `main()` here).
"""
import json
import math
import os
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFontMetrics, QFontMetricsF, QGuiApplication, QIcon, QLinearGradient, QPainter
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
                             QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from app import path_utils, theme
from app.qt import applog, bridge, hud, motion, strings, style, titlebar, toast, tooltip
from app.services import jobs as jobs_module
from app.services import settings as settings_service
from app.services import status as status_service
from app.qt import screens                                # W2.2: the pages a library fills

TABS = ("current", "finished", "needs", "settings")
STATE_FILE = "window_state.json"
STATE_VERSION = 1
DEFAULT_SIZE = (1280, 800)
POLL_MS = 500
JOURNEY_FILE = "reading_list_static.html"   # the report's file in `results` (`static_html_generator.OUTPUT_FILE`)
# E20 (IK-22): at quit, what can't stop part-way — an Anki write the window started (finishing its batch: Anki
# finishes a request it received), Generate writing your list — is waited for up to this long ("≤ a few seconds"), with
# the window up and its bar saying so (`ShellWindow._finish_first`), then whatever is left of it at `shutdown`. Under
# the next start's `single.WAIT_FOR_FIRST_S` (10 s), so a start during the wait still finds the claim free in time.
QUIT_FINISH_WAIT = 8.0
# No unbounded wait at exit. The duties' close — Koe's stop (two 2 s joins at most), Connect's `at_close` (the
# store opened with its 1 s busy wait, one write) — goes on for at most this long before the single-instance claim is
# let go; then the store's close trigger (`maintain_at_close` for both languages, as the Tk `on_closing` runs it: an
# export of the copy measured 6.7–14.5 s at 100k items, L3.1) for at most QUIT_STORE_WAIT. Past a cap the process ends
# without it: the store stays the truth, the copy is exported at the next trigger (a temp file left is cleared, §6.7).
QUIT_CLOSE_WAIT = 6.0
QUIT_STORE_WAIT = 60.0
# W3.5 row 7: the re-order host is stopped this long before the duties' close cap, so `stop()` is sent before the quit
# gives the close up. Its `CLOSE_WAIT_S` (15 s, the Tk wait) is not waited here: a write running at the close is waited
# for with the window up (E20's `QUIT_FINISH_WAIT`: its `replan` job is a `wait` job), then what is left — a pending
# settle, the S3 sync — inside `QUIT_CLOSE_WAIT`: ≤ 14 s in all, under `CLOSE_WAIT_S` and the update's 20 s grace; past
# it the helper finishes a write in hand by itself.
REPLAN_MARGIN = 0.25
# P-text (W2.1 row 9): a theme or text-size switch with the shell's widgets alive measured well under ~300 ms, so a
# change applies at once (G1.2-21). W3.3 measures it again with its Settings page alive; False = *Restart to apply*.
LIVE_LOOK = True


# --- the services the window calls ------------------------------------------------------------------------------- #
class Services:
    """The window's services, made once per window (the settings file is read here, before the first paint).

    W3.5: the dashboard's duties — the Generate controller, the update service, automatic sync / Generate / 順
    (`automation`) and the start-up chores — are given (a test's stand-ins) or made by `make_duties()` on a worker
    after the first paint (`ShellWindow.start_duties`, which `main` connects; their imports stay off the first paint),
    then started there (`start`). Qt-free: everything here runs on a worker or after the window is gone."""

    def __init__(self, settings=None, registry=None, status=None, library=None, controller=None, updates=None,
                 automation=None, chores=None, replan=None):
        self.settings = settings if settings is not None else settings_service.SettingsService()
        self.registry = registry if registry is not None else jobs_module.JobRegistry()
        self.status = status if status is not None else status_service.StatusService(self.registry)
        self.library = library            # W2.2: a library reader (app/services/library_reader.py), or None
        # --- W3.5: the duties
        self.controller, self.updates, self.automation, self.chores = controller, updates, automation, chores
        # row 7: the journey keeper and the re-order host of the language open (`replan_host.Replan`), made with the
        # duties (given: a test's); never one of `has_duties`' four
        self.replan = replan
        self._replan_wired = False
        self.language = self.settings.get().get("target_language") or "ja"
        self.closing = threading.Event()  # set at quit: a Generate still waiting for `results` starts nothing
        self.quit_hook = None             # the window's: the update hands over (called on a worker)
        self.started = False
        self._quit_lock = threading.Lock()
        self._quit_began = None           # when the quit began (`_stop_starting`): E20's wait counts from it
        if self.has_duties():
            self._provide()

    # --- W3.5: the dashboard's duties --------------------------------------------------------------------------- #
    def has_duties(self):
        return None not in (self.controller, self.updates, self.automation, self.chores)

    def make_duties(self):
        """(A worker.) The duties not given, made as the Tk dashboard runs them (A.md's recipe). -> self."""
        from app.services import automation as automation_module
        from app.services import chores as chores_module
        from app.services import generate as generate_module
        from app.services import updates as updates_module
        if self.controller is None:
            self.controller = generate_module.GenerateController(self.registry, closing=self.closing, settle=0)
        if self.updates is None:
            self.updates = updates_module.UpdateService(self.settings, self.registry, on_quit=self._ask_quit)
        if self.chores is None:
            self.chores = chores_module.Chores(self.registry, self.settings, self.language)
        if self.automation is None:
            chores = self.chores
            self.automation = automation_module.Automation(self.registry, self.controller, self.settings,
                                                           self.language, index=lambda: chores.index(force=True))
            chores.on_indexed(lambda _language: self.automation.recheck())     # IK-10: asked again after the indexer
        if self.replan is None:
            from app.services import replan_host as replan_module
            self.replan = replan_module.Replan(self.registry, self.controller, self.settings, self.language,
                                               on_line=self._replan_line)
        self._provide()
        return self

    def _provide(self):
        """The duties' failures to the bar and Needs you (E10, IK-7): `StatusService` providers; row 7's wiring."""
        providers = getattr(self.status, "providers", None)
        if providers is not None:
            controller, updates = self.controller, self.updates

            def generate_failure():
                failure = getattr(controller, "failure", None)
                if failure is not None:     # kept while another run starts at once (A12): never the state's `queued`
                    return failure(self.language)           # the language open's: never another's
                from app.services import generate as generate_module
                state = controller.state()
                return state.message if state.state == generate_module.FAILED else None
            providers.update(update=updates.failure, generate=generate_failure)
        self._wire_replan()

    # --- W3.5 row 7: the re-order host and the journey keeper (`app/services/replan_host.py`) -------------------- #
    def _wire_replan(self):
        """Once: the bar's row-7 providers, the update's hold (its states) and the library reader's moves."""
        if self.replan is None or self._replan_wired:
            return
        self._replan_wired = True
        self._provide_lines(self.language)
        subscribe = getattr(self.updates, "subscribe", None)
        if subscribe is not None:
            subscribe(self._update_state)
        moves = getattr(self.library, "subscribe_moves", None)
        if moves is not None:
            moves(self._store_moved)

    def _provide_lines(self, language):
        """Worker B's providers (W3.5 row 7): the host's line, Connect's line, the AnkiWeb mark, the journey dot —
        again on a language switch (Connect's line and the dot are the language's)."""
        providers = getattr(self.status, "providers", None)
        if providers is None:
            return
        replan, get = self.replan, self.settings.get
        providers.update(replan=replan.line, connect=status_service.connect_line(language, get),
                         ankiweb=status_service.ankiweb_line(get), journey=status_service.journey_pending(language))

    def _replan_line(self, _line):
        """The host said a new line (its worker): the bar asks for it alone."""
        refresh = getattr(self.status, "refresh_soon", None)
        if refresh is not None:
            refresh("replan")

    def _store_moved(self, language, versions):
        """(The library reader's thread.) The order or the pins moved, whoever moved them: one poke, one `changed`;
        the journey dot asked again."""
        if self.closing.is_set() or self.replan is None:
            return
        self.replan.store_moved(language, versions)
        refresh = getattr(self.status, "refresh_soon", None)
        if refresh is not None:
            refresh("journey")

    def _update_state(self, state):
        """(The update service's worker.) *Update now* holds the children: the host goes; the hold's end makes it
        again (the map's G6) — never once the quit began (the quit's own cancel is no hold's end)."""
        if not self.closing.is_set() and self.replan is not None:
            self.replan.update_state(state.state)

    def _ask_quit(self):
        hook = self.quit_hook
        if hook is not None:
            hook()

    def start(self):
        """(A worker, once.) The duties started: the journey asked (the Generate button's mark), the update's outcome
        and check, the sync 2 s on, the chores. Each obeys its test switch. Nothing once the quit began — a close
        while the duties were being made: the last update's outcome stays unread, no timer is armed. Under the quit's
        lock (each call returns at once), so the quit sees the duties either started or never."""
        with self._quit_lock:
            if self.started or not self.has_duties() or self.closing.is_set():
                return False
            self.started = True
            try:
                self.controller.check(settings_service.thaw(self.settings.get()), self.language)
            except Exception as e:
                applog.log("shell", f"the journey check at start: {e}")
            self.updates.begin()
            self.automation.started()
            self.chores.started()
            if self.replan is not None:
                self.replan.start()       # the catch-up once; the journey when the store says it is pending
        return True

    def activated(self):
        """(A worker.) The window came back into focus: the journey, the sync, 順, a waiting Generate, the indexer —
        nothing once the quit began (E20: the window may still be up while an Anki write ends)."""
        if self.started and not self.closing.is_set():
            self.automation.activated()
            self.chores.activated()
            if self.replan is not None:
                self.replan.activated()               # the catch-up and the start's journey look (an outside placement)
                refresh = getattr(self.status, "refresh_soon", None)
                if refresh is not None:
                    refresh("journey")                # the dot, which that look may have found owed

    def language_changed(self, language):
        """(A worker.) Another language is open (D31: nothing assumes one)."""
        self.language = language or "ja"
        forget = getattr(self.controller, "forget_failure", None)
        if forget is not None:
            forget()                                      # the last language's Generate failure leaves the bar
        if self.started and not self.closing.is_set():
            self.automation.language_changed(self.language)
            self.chores.language_changed(self.language)
        if self.replan is not None and not self.closing.is_set():
            self.replan.language_changed(self.language)   # the old keeper closed, the old host stopped, new ones
            self._provide_lines(self.language)
            refresh = getattr(self.status, "refresh_soon", None)
            if refresh is not None:
                refresh("journey", "replan")              # the new language's dot and line at once

    def generate(self):
        """(A worker.) The header's Generate: the newest settings written first (the analyzer reads settings.json), the
        language's folders and word lists set up (the Tk `run_analyzer`'s `ensure_data_setup`, IK-21), the Anki backlog
        read beside it, then the controller's run — the user's, which an automatic one makes way for. Nothing once the
        quit began (E20)."""
        if self.closing.is_set():
            return None
        try:
            self.settings.flush(10.0)
        except Exception as e:
            applog.log("shell", f"settings before Generate: {e}")
        try:
            path_utils.ensure_data_setup(self.language)
        except Exception as e:
            applog.log("shell", f"folders before Generate: {e}")
        self.automation.before_generate()
        return self.controller.request(self.language, settings=settings_service.thaw(self.settings.get()))

    @staticmethod
    def open_guide():
        """(A worker.) ? › *Online guide*: the browser (IK-24; the Tk dashboard's Help › Tutorial opens the same)."""
        import webbrowser
        webbrowser.open(path_utils.GUIDE_URL)

    @staticmethod
    def level_moved(keys):
        """Whether a settings write of `keys` can move the level chip (`automation.moves_level`, IK-28)."""
        from app.services import automation as automation_module
        return automation_module.moves_level(keys)

    def journey_exists(self):
        """(A worker.) Whether a journey (the report) is on disk to open: `static_html_generator.OUTPUT_FILE`, named
        without importing the generator (its pandas → numpy cost ~0.6 s and OpenBLAS's buffers, a few hundred MB, at
        every start; the start-light fix)."""
        return os.path.exists(os.path.join(path_utils.get_user_file("results"), JOURNEY_FILE))

    def open_journey(self):
        """(A worker.) *Your journey ↗*: the report as it is, never re-rendered (`open_report`). -> False with none."""
        from app import static_html_generator
        return static_html_generator.open_report(app_mode=bool(self.settings.get().get("open_app_mode")))

    def level(self):
        """(A worker.) The level chip's (band, automatic) (`automation.level`)."""
        from app.services import automation as automation_module
        return automation_module.level(settings_service.thaw(self.settings.get()), self.language)

    def _close_duties(self):
        """The duties' close but the store's trigger (`_close_store`): their timers and workers, Koe, Connect's
        `at_close` — then the re-order host's finish (row 7: its close was sent at the quit's start; `busy()` waited
        for until `REPLAN_MARGIN` before this thread's cap, then `stop()`: the helper finishes a write in hand by
        itself)."""
        began = time.monotonic()
        for name in ("automation", "chores"):
            duty = getattr(self, name)
            if duty is None or (name == "chores" and not self.started):
                continue                  # (the chores' close stops Koe and tells Connect: only once started)
            try:
                if name == "chores":
                    duty.close(store=False)
                else:
                    duty.close()
            except Exception as e:
                applog.log("shell", f"{name} at quit: {e}")
        if self.replan is not None:
            try:
                if not self.replan.finish(began + QUIT_CLOSE_WAIT - REPLAN_MARGIN):
                    applog.log("shell", "the re-order in Anki still ran at quit: its helper finishes it")
            except Exception as e:
                applog.log("shell", f"the re-order host at quit: {e}")

    def _close_store(self):
        try:
            self.chores.close_store()
        except Exception as e:
            applog.log("shell", f"the store's close at quit: {e}")

    # --- E20: the quit begins (the window may stay up while an Anki write ends) --------------------------------- #
    def begin_quit(self):
        """(A worker; the window's close while an Anki write runs, E20.) At once, nothing waited for: nothing new
        starts (`_stop_starting`), Generate and every `cancel` job are cancelled, a `wait` job not started yet is
        dropped, `detach` ones (Connect, the sync) go on. A running `wait` job (an Anki write finishing its batch,
        Generate writing your list) ends first: the window closes when it ends or at `QUIT_FINISH_WAIT`, and
        `shutdown` waits only what is left of that. -> False when the quit began already."""
        if not self._stop_starting():
            return False
        try:
            self.registry.quit(0.0, wait_timeout=0.0)
        except Exception as e:
            applog.log("shell", f"jobs at quit: {e}")
        return True

    def _stop_starting(self):
        """Once: `closing` set (a Generate waiting for `results` starts nothing), every gated job held from now on
        (the registry's gate), an update under way cancelled first — before the registry's quit (U.md): the jobs it
        held are dropped, not started — and the chores' timers taken back. -> False when it was done already."""
        with self._quit_lock:                 # (a worker's or the last call: never the window's thread)
            if self._quit_began is not None:
                return False
            self._quit_began = time.monotonic()
            self.closing.set()
            self.registry.gate(self._closing_gate)
            if self.updates is not None:
                try:
                    self.updates.quit()
                except Exception as e:
                    applog.log("shell", f"update at quit: {e}")
            if self.chores is not None:
                try:
                    self.chores.halt()            # its start-up timers taken back: nothing spawned for a closing one
                except Exception as e:
                    applog.log("shell", f"chores at quit: {e}")
            if self.replan is not None:
                try:
                    self.replan.closing()         # the keeper closed; the host's close sent (a pending settle runs now)
                except Exception as e:
                    applog.log("shell", f"the re-order host at quit: {e}")
        return True

    @staticmethod
    def _closing_gate(_kind):
        return strings.QUIT_HELD

    def replan_settling(self):
        """(Any thread: no lock, no wait.) A move's re-order may still be settling: the close then waits like E20's."""
        settling = getattr(self.replan, "settling", None)
        try:
            return bool(settling()) if settling is not None else False
        except Exception:
            return False

    def replan_wait(self):
        """(A worker; E20.) While the re-order host still works — the settle its close ran at once, the AnkiWeb sync —
        wait, for what is left of `QUIT_FINISH_WAIT`. -> True when it ended."""
        busy = getattr(self.replan, "busy", None)
        if busy is None:
            return True
        from app.services.replan_host import BUSY_LOOK
        deadline = time.monotonic() + self._finish_wait_left()
        try:
            while busy() and time.monotonic() < deadline:
                time.sleep(BUSY_LOOK)
            return not busy()
        except Exception as e:
            applog.log("shell", f"the re-order host at the close: {e}")
            return True

    def _finish_wait_left(self):
        """What is left of `QUIT_FINISH_WAIT` since the quit began (the window's wait counts: never the cap twice)."""
        began = self._quit_began
        return QUIT_FINISH_WAIT if began is None else max(0.0, QUIT_FINISH_WAIT - (time.monotonic() - began))
    # --- end W3.5 ------------------------------------------------------------------------------------------------ #

    def shutdown(self, timeout=2.0, release=None):
        """At quit, after the window is gone: nothing new starts and an update under way is cancelled first (nothing it
        held starts), the duties closed on a thread of their own (Koe's stop may wait; at most `QUIT_CLOSE_WAIT`),
        the library's reader stopped, jobs told (their `on_quit`: an Anki write finishes its batch within what is left
        of `QUIT_FINISH_WAIT` — E20, IK-22), pending settings written. Then `release()` — the single-instance claim: a
        new start opens its window from now on — and only then the store's close trigger, as the Tk `on_closing` runs
        it (seconds at 100k items), for at most `QUIT_STORE_WAIT`: no hung chore keeps a windowless process holding
        the claim."""
        self._stop_starting()
        began = time.monotonic()
        closer = threading.Thread(target=self._close_duties, name="duties-close", daemon=True)
        closer.start()
        if self.library is not None:
            try:
                self.library.stop(timeout)
            except Exception as e:
                applog.log("shell", f"library reader at quit: {e}")
        try:
            self.registry.quit(timeout, wait_timeout=self._finish_wait_left())
        except Exception as e:
            applog.log("shell", f"jobs at quit: {e}")
        closer.join(max(0.0, began + QUIT_CLOSE_WAIT - time.monotonic()))
        if closer.is_alive():
            applog.log("shell", f"the duties' close still runs after {QUIT_CLOSE_WAIT} s: quitting without it")
        try:
            if not self.settings.flush(timeout):           # a held settings lock: the change is lost, so say so
                applog.log("shell", f"settings at quit: not written within {timeout} s (pending: "
                                    f"{self.settings.pending()})")
        except Exception as e:
            applog.log("shell", f"settings at quit: {e}")
        if release is not None:
            try:
                release()
            except Exception as e:
                applog.log("shell", f"the window's claim at quit: {e}")
        if self.chores is not None and self.started:
            store = threading.Thread(target=self._close_store, name="store-close", daemon=True)
            store.start()
            store.join(QUIT_STORE_WAIT)
            if store.is_alive():
                applog.log("shell", f"the store's close still runs after {QUIT_STORE_WAIT} s: quitting without it "
                                    f"(the store stays the truth; its copy is written at the next trigger)")


# --- window_state.json (02 §2.1) ---------------------------------------------------------------------------------- #
def state_path():
    return os.path.join(path_utils.get_local_data_path(), STATE_FILE)


def read_state(path):
    """The saved state, or {} when it's missing, unreadable or not ours."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("version") == STATE_VERSION else {}


def write_state(path, data):
    """Atomically (a crash mid-write leaves the old file, never half of one)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())                            # on disk before it replaces the old one
    os.replace(tmp, path)


CAPTION = 32          # logical px above the client area Windows draws its title bar in: kept on screen to grab


def valid_geometry(geo):
    """A saved [x, y, w, h] as a QRect, or None when it isn't four sane integers (a hand-edited or damaged file: an
    out-of-range number once stopped the window from ever opening, review A5)."""
    if not (isinstance(geo, list) and len(geo) == 4 and all(type(v) is int for v in geo)):
        return None
    x, y, w, h = geo
    if abs(x) > 1_000_000 or abs(y) > 1_000_000 or not (1 <= w <= 100_000) or not (1 <= h <= 100_000):
        return None
    return QRect(x, y, w, h)


def fit_on_screens(rect, screens, default=DEFAULT_SIZE):
    """`rect` (a saved QRect, the client area) put where it can be used: on the screen most of its title strip is on
    — no larger than that screen, moved inside it, its title bar on it; with no title strip on any screen, the
    default size (never larger than the first screen) centred on the first screen."""
    strip = QRect(rect.left(), rect.top() - CAPTION, rect.width(), CAPTION)
    best, seen_w = None, 0
    for s in screens:
        seen = strip.intersected(s)
        if seen.width() >= 200 and seen.height() >= CAPTION // 2 and seen.width() > seen_w:
            best, seen_w = s, seen.width()
    if best is None:
        first = screens[0] if screens else QRect(0, 0, *default)
        w, h = min(default[0], first.width()), min(default[1], first.height() - CAPTION)
        return QRect(first.center().x() - w // 2, first.center().y() - h // 2 + CAPTION // 2, w, h)
    w, h = min(rect.width(), best.width()), min(rect.height(), best.height() - CAPTION)
    x = max(best.left(), min(rect.left(), best.right() - w + 1))
    y = max(best.top() + CAPTION, min(rect.top(), best.bottom() - h + 1))
    return QRect(x, y, w, h)


# --- small parts ---------------------------------------------------------------------------------------------------- #
class Wordmark(QWidget):
    """*Surasura*, the second half in the iris (painted: a stylesheet has no gradient text)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName(strings.WORDMARK_NAME)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _font(self):
        f = self.font()
        px, weight = theme.font("wordmark", style.current()[1])
        f.setPointSizeF(px * style.PT_PER_PX)
        f.setWeight(weight)
        return f

    def sizeHint(self):
        """As wide as the name, as tall as the mock's line (`line-height: 1.05`, not the font's own ~1.33: V-4)."""
        fm = QFontMetrics(self._font())
        px, _weight = theme.font("wordmark", style.current()[1])
        return QSize(fm.horizontalAdvance("".join(strings.WORDMARK)) + 2, math.ceil(px * 1.05))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setFont(self._font())
        fm = p.fontMetrics()
        first, second = strings.WORDMARK
        base = (self.height() + fm.ascent() - fm.descent()) / 2
        p.setPen(style.qcolor(style.colours()["ink"]))
        p.drawText(QPointF(0, base), first)
        x = fm.horizontalAdvance(first)
        w = fm.horizontalAdvance(second)
        grad = QLinearGradient(QPointF(x, 0), QPointF(x + w, 0))
        for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS["hb"]):
            grad.setColorAt(pos, style.qcolor(colour))
        pen = p.pen()
        pen.setBrush(grad)
        p.setPen(pen)
        p.drawText(QPointF(x, base), second)
        p.end()


class Mark(QWidget):
    """The mark, 34 px, painted from the icon at the device-pixel ratio of the screen it is on now (a pixmap scaled
    once blurs when the window moves to a sharper monitor). Hidden when the icon isn't there."""

    SIDE = 34

    def __init__(self, icon_path, parent=None):
        super().__init__(parent)
        self.setObjectName("mark")
        self.setAccessibleName(strings.WORDMARK_NAME)
        self.setFixedSize(self.SIDE, self.SIDE)
        self._icon = QIcon(icon_path) if os.path.exists(icon_path) else None
        self.setVisible(self._icon is not None)

    def paintEvent(self, _event):
        if self._icon is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        dpr = self.devicePixelRatioF() or 1.0
        pix = self._icon.pixmap(QSize(self.SIDE, self.SIDE), dpr)
        p.drawPixmap(self.rect(), pix)
        p.end()


class ElidingLabel(QLabel):
    """One line, cut with … to the room it has (never wrapped, never pushing the layout); the whole text in its
    accessible description."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setTextFormat(Qt.TextFormat.PlainText)

    def set_full(self, text):
        self._full = text or ""
        self.setAccessibleDescription(self._full)
        self._fit()

    def full(self):
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, self.width()))
        if shown != self.text():
            self.setText(shown)


class TabButton(QToolButton):
    """A tab: its name, then its count drawn as a count — Finished's small and faint, Needs you's on a heads-up badge
    (G2.3 R4, R5; mock `.tab .n`, `.badge.warn`) — so the number never reads as part of the word. The stylesheet draws
    the ground and the underline; the name and the count are painted here. `text()` stays the whole line, for screen
    readers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.name, self.count, self.badge = "", 0, False

    def set_name(self, name, count=0, badge=False):
        self.name, self.count, self.badge = name, count, badge
        self.setText(strings.TAB_COUNT.format(name=name, count=count) if count else name)
        self.updateGeometry()
        self.update()

    def _pads(self):
        f = theme.text_factor(style.current()[1])
        return 10, 14, 9, f        # the stylesheet's padding (`QToolButton#tab`): the mock's, whatever the text size (V-4)

    def _count_font(self):
        font = self.font()
        px, weight = theme.font("badge" if self.badge else "tab-count", style.current()[1])
        font.setPointSizeF(px * style.PT_PER_PX)
        font.setWeight(weight)
        return font

    def _count_w(self):
        if not self.count:
            return 0
        _t, _side, _b, f = self._pads()
        w = QFontMetrics(self._count_font()).horizontalAdvance(str(self.count))
        return round(max(18 * f, w + 10)) if self.badge else w

    def sizeHint(self):
        top, side, bottom, f = self._pads()
        fm = QFontMetrics(self.font())
        w = side + fm.horizontalAdvance(self.name) + side + ((round(7 * f) + self._count_w()) if self.count else 0)
        return QSize(w, top + fm.height() + bottom + 2)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        from PyQt6.QtWidgets import QStyle, QStyleOptionToolButton, QStylePainter
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text = ""
        p = QStylePainter(self)
        p.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt)
        top, side, bottom, f = self._pads()
        c = style.colours()
        lit = self.isChecked() or self.underMouse() or self.hasFocus()
        fm = QFontMetricsF(self.font())
        mid = (top + self.height() - bottom - 2) / 2
        dpr = self.devicePixelRatioF()
        base = round((mid + (fm.ascent() - fm.descent()) / 2) * dpr) / dpr     # baselines on whole device pixels
        p.setFont(self.font())
        p.setPen(style.qcolor(c["ink" if lit else "ink-dim"]))
        p.drawText(QPointF(side, base), self.name)
        if self.count:
            # The count is centred on the name's midline — half its capital height above its baseline — not on the
            # tab's box: digits are capital-high, so a box-centred count or badge sat taller than the word (G2.3 note,
            # 2026-10-09). The badge's figures are placed the same way, never by the badge box's own centre.
            line = base - fm.capHeight() / 2
            x = side + fm.horizontalAdvance(self.name) + round(7 * f)
            font = self._count_font()
            cm = QFontMetricsF(font)
            text = str(self.count)
            figures = round((line + cm.capHeight() / 2) * dpr) / dpr
            p.setFont(font)
            if self.badge:
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                w, h = self._count_w(), round(18 * f)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(style.qcolor(c["warn"]))
                p.drawRoundedRect(QRectF(x, round((line - h / 2) * dpr) / dpr, w, h), h / 2, h / 2)   # crisp edges
                p.setPen(style.qcolor(theme.FIXED["on-accent"]))
                p.drawText(QPointF(x + (w - cm.horizontalAdvance(text)) / 2, figures), text)
            else:
                p.setPen(style.qcolor(c["ink-faint"]))
                p.drawText(QPointF(x, figures), text)
        p.end()


def _repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# --- Esc and Back (✅ G1.2-2) ---------------------------------------------------------------------------------------- #
class EscapeRouter(QObject):
    """App-wide: Esc and the mouse's Back button close every open overlay of the window they happen in, at once; with
    none open, they close that window if it's a secondary one; the main window is never closed. Forward does nothing.
    A menu (a popup) closes itself on Esc; Back closes it too."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        self.overlays = []

    def register(self, overlay):
        if overlay not in self.overlays:
            self.overlays.append(overlay)
            overlay.destroyed.connect(lambda *_a, o=overlay: self._forget(o))

    def _forget(self, overlay):
        self.overlays = [o for o in self.overlays if o is not overlay]

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            return self.escape(obj, back=False)
        if et == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.BackButton:
                return self.escape(obj, back=True)
            if event.button() == Qt.MouseButton.ForwardButton:
                return True                               # does nothing, and nothing else sees it
        return False

    def escape(self, obj, back=False):
        """-> True when the press was used (and goes no further)."""
        win = obj.window() if isinstance(obj, QWidget) else QApplication.activeWindow()
        if win is None:
            return False
        if win.windowType() == Qt.WindowType.Popup:
            if back:
                win.close()
                return True
            return False                                  # a menu closes itself on Esc
        open_now = [o for o in self.overlays if (o.isVisible() or motion.opening_of(o) is not None)
                    and o.window() is win]                # an overlay still opening is open (M2.1 review A3)
        if open_now:
            for overlay in open_now:
                overlay.close()
            return True
        if win is self.main:
            return back                                   # never the main window: Esc goes on to the focused widget
        if isinstance(win, QDialog):
            win.reject()
        else:
            win.close()
        return True


class _Duties:
    """W3.5: the duties' controls, and the newest state each showed (the window's view of them)."""

    def __init__(self):
        self.module = None
        self.generate = self.journey = self.help = self.known = self.anki = self.level = self.update_mark = None
        self.sheet = self.cards = self.journey_dot = None
        self.update_state = self.generate_state = self.auto_state = None
        self.notice = self.junban_said = self.updated_said = None      # the lines toasted once (IK-23)
        self.update_unseen = ()             # the update's failures not looked at yet (the bar's line: HR-23)
        self.paints = {}                    # control -> how many times it was repainted (S19)


# --- the window ------------------------------------------------------------------------------------------------------ #
class ShellWindow(QMainWindow):
    first_frame = pyqtSignal()
    closing = pyqtSignal()                                # before the window hides (single instance stops listening)

    def __init__(self, services, state_file=None, parent=None):
        super().__init__(parent)
        self.services = services
        self.state_file = state_file or state_path()
        settings = services.settings.get()
        self.language = settings.get("target_language") or "ja"
        self._first_painted = False
        self.setWindowTitle(strings.WINDOW_TITLE)
        icon = path_utils.get_icon_path()
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.setMinimumSize(*theme.WINDOW_MIN)

        central = QWidget(self)
        central.setObjectName("central")
        central.setFocusPolicy(Qt.FocusPolicy.ClickFocus)     # where focus rests at start: no ring until Tab is used
        self._rest = central
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(style.separator(central))
        root.addWidget(self._build_tabs())
        root.addWidget(style.separator(central))
        self.pages = QStackedWidget(central)
        self.pages.setObjectName("pages")
        self.page_widgets = {}
        for name in TABS:
            page = self._page(name)
            self.page_widgets[name] = page
            self.pages.addWidget(page)
        root.addWidget(self.pages, 1)
        root.addWidget(style.separator(central))
        root.addWidget(self._build_footer())
        self.setCentralWidget(central)
        self._apply_sizes()

        # the services, through the bridge
        self.bridge = bridge.Bridge(services.settings, services.registry, services.status, parent=self)
        self.bridge.status_changed.connect(self.show_status)
        self._jobs = ()                                   # the registry's newest snapshot (E20: what the close waits for)
        self._quit = None                                 # None · "waiting" (E20: an Anki write ends first) · "ready"
        self._quit_line = strings.QUIT_FINISHING          # the bar's one line while it waits
        self._quit_timer = None
        self.bridge.jobs_changed.connect(self._jobs_changed)
        self._library_needs = 0
        self._status_snap = None
        self._replan_waited = True                        # E20: the re-order host idle (or not waited for) at the close
        self._d29 = True                                  # D29 for the journey dot's tooltip, read on a worker
        self._d29_asked = 0                               # ... and the newest read asked (an older answer is dropped)
        self.duties = None                                # W3.5: the duties' controls, once the duties are attached
        self.show_status(services.status.snapshot())
        # --- W2.2: the library (the reader's views, queued to this thread) ---------------------------------------- #
        if services.library is not None:
            self.library_bridge = bridge.Bridge(library=services.library, parent=self)
            self.library_bridge.library_changed.connect(self.show_library)
            for page in self.page_widgets.values():
                if hasattr(page, "message"):
                    page.message.connect(self.bar_line.set_full)       # a file ▶ couldn't open: said in the bar
            services.library.start()
        # --- end W2.2 ------------------------------------------------------------------------------------------------ #
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_status)
        self._poll.start(POLL_MS)

        # --- M2.1: the motion's mode (`app_motion`; Follow Windows hears its switch) and the toasts
        motion.clock().mode.set_setting(settings.get("app_motion"))
        motion.install_mode_filter(QApplication.instance())
        self.bridge.settings_written.connect(self._settings_written)
        self.toasts = toast.ToastHost(central)

        # app-wide behaviour
        app = QApplication.instance()
        self.router = EscapeRouter(self, parent=self)
        app.installEventFilter(self.router)
        self.tooltips = tooltip.Tooltips(parent=self).install(app)
        for page in self.page_widgets.values():           # W2.2: painted parts' tooltips go through the bubble
            if hasattr(page, "list"):
                page.list.tooltips = self.tooltips

        self._restore_state(read_state(self.state_file))

        # --- W3.5: the dashboard's duties: their controls arrive with them (given: now; else `start_duties`) ------- #
        self._duties_asked = False
        self.bridge.quit_asked.connect(self._quit_for_update)
        services.quit_hook = self.bridge.ask_quit
        if services.has_duties():
            self._attach_duties()

    # --- building ------------------------------------------------------------------------------------------- #
    def _build_header(self):
        header = style.styled(QWidget(), "header")
        self.header = header
        row = QHBoxLayout(header)
        top, side, bottom = theme.SPACING["header"]
        row.setContentsMargins(side, top, side, bottom)
        row.setSpacing(12)
        self.mark = Mark(path_utils.get_icon_path(), header)
        row.addWidget(self.mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.setContentsMargins(0, 0, 0, 0)
        self.wordmark = Wordmark(header)
        names.addWidget(self.wordmark)
        self.subline = QLabel(strings.LANGUAGE_NAMES.get(self.language, ""), header)
        self.subline.setObjectName("wordsub")
        names.addWidget(self.subline)
        row.addLayout(names)
        row.addStretch(1)                                  # the header's controls arrive with their features (G-2):
        return header                                      # W3.5's with the duties (`_attach_duties`)

    def _build_tabs(self):
        bar = style.styled(QWidget(), "tabbar")
        bar.setAccessibleName(strings.TABS_NAME)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(2)
        self.tab_group = QButtonGroup(bar)
        self.tab_group.setExclusive(True)
        self.tab_buttons = {}
        for name in TABS:
            label, tip = strings.TABS[name]
            b = TabButton(bar)
            b.setObjectName("tab")
            b.set_name(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setAccessibleName(label)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, n=name: self.show_tab(n))
            self.tab_group.addButton(b)
            self.tab_buttons[name] = b
            row.addWidget(b)
        self.tab_buttons["needs"].setVisible(False)       # shown while Needs you lists anything
        row.addStretch(1)
        self.tab_buttons["current"].setChecked(True)
        return bar

    # --- W2.2: the pages a library fills ----------------------------------------------------------------------- #
    def _page(self, name):
        if self.services.library is None or name not in screens.PAGES:
            return self._waiting_page(name)
        return screens.make_page(name, language=self.language)

    def show_library(self, view):
        """The reader's newest view: the pages, the subline's counts, the tabs' counts."""
        moved = False
        for name in screens.PAGES:
            page = self.page_widgets.get(name)
            if hasattr(page, "set_view"):
                moved = page.set_view(view) != "same" or page.list.looks_changed or moved
        self.subline.setText(view.subline)
        fin = self.tab_buttons["finished"]
        label = strings.TABS["finished"][0]
        if fin.count != view.counts.finished:      # repainted only when the count changed (S19)
            fin.set_name(label, view.counts.finished)
        if self._library_needs != len(view.needs):
            self._library_needs = len(view.needs)
            self.show_status(self.services.status.snapshot())
        if moved:                                   # a view that changed no list paints nothing ahead
            self._warm_hidden_pages()

    def _warm_hidden_pages(self):
        """The hidden tabs' lists paint their first screen ahead, laid out as the shown list (`RowsView.warm_like`)."""
        shown = self.pages.currentWidget()
        like = getattr(shown, "list", None)
        for page in self.page_widgets.values():
            lst = getattr(page, "list", None)
            if lst is not None and page is not shown:
                lst.warm_like = like
                lst._rest()
    # --- end W2.2 ---------------------------------------------------------------------------------------------- #

    def _waiting_page(self, name):
        page = QWidget()
        page.setObjectName(f"page-{name}")
        box = QVBoxLayout(page)
        box.addStretch(1)
        title = QLabel(strings.TABS[name][0], page)
        title.setObjectName("pagetitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        line = QLabel(strings.PAGE_WAITING, page)
        line.setObjectName("pagewaiting")
        line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(title)
        box.addWidget(line)
        box.addStretch(1)
        return page

    def _build_footer(self):
        footer = style.styled(QWidget(), "footer")
        self.footer = footer
        row = QHBoxLayout(footer)
        row.setContentsMargins(16 - motion.GLOW, 0, 16, 0)   # the dot at 16 px, as the mock: its glow needs room
        row.setSpacing(10)
        self.bar_dot = motion.Spinner("pulse", footer)    # M2.1: the mock's pulsing dot while a job runs (G1.5-2)
        self.bar_dot.setObjectName("bardot")
        self.bar_dot.setProperty("busy", "false")
        self.bar_dot.setAccessibleName(strings.BAR_NAME)
        # the line close to its dot (G2.3 N2): the dot's widget holds its glow's room on both sides (GLOW), so the two
        # sit with no gap of their own — the line starts GLOW (10 px) past the dot, the mock's gap — not glow + gap
        lead = QHBoxLayout()
        lead.setSpacing(0)
        lead.addWidget(self.bar_dot)
        self.bar_line = ElidingLabel(footer)
        self.bar_line.setObjectName("barline")
        self.bar_line.setAccessibleName(strings.BAR_NAME)
        lead.addWidget(self.bar_line, 1)
        row.addLayout(lead, 1)
        self.bar_replan = ElidingLabel(footer)            # W3.5 row 7: the re-order host's line, while it gives one
        self.bar_replan.setObjectName("barline")
        self.bar_replan.setVisible(False)
        row.addWidget(self.bar_replan, 1)
        self.bar_failure = ElidingLabel(footer)
        self.bar_failure.setObjectName("barfailure")
        self.bar_failure.setToolTip(strings.BAR_FAILURE_TIP)
        self.bar_failure.setVisible(False)
        row.addWidget(self.bar_failure, 1)
        self.logs_button = QPushButton(strings.BAR_LOGS, footer)
        self.logs_button.setProperty("kind", "chip")
        self.logs_button.setToolTip(strings.BAR_LOGS_TIP)
        self.logs_button.setAccessibleName(strings.BAR_LOGS)
        self.logs_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.logs_button.clicked.connect(self.open_logs)
        self.logs_button.setVisible(False)
        row.addWidget(self.logs_button)
        self.bar_ankiweb = QLabel(footer)
        self.bar_ankiweb.setObjectName("barmark")
        self.bar_ankiweb.setTextFormat(Qt.TextFormat.PlainText)       # a provider's words, never markup
        self.bar_ankiweb.setVisible(False)
        row.addWidget(self.bar_ankiweb)
        self.bar_connect = QLabel(footer)
        self.bar_connect.setObjectName("barmark")
        self.bar_connect.setTextFormat(Qt.TextFormat.PlainText)
        self.bar_connect.setVisible(False)
        row.addWidget(self.bar_connect)
        self._logs_folder = None
        self.status_paints = {}             # row 7's statuses (the bar's lines, the journey dot) -> repaints (S19)
        return footer

    def _apply_sizes(self):
        """The fixed heights (the stylesheet carries the rest): the footer at the taskbar's height at every text size."""
        size = style.current()[1]
        self.footer.setFixedHeight(round(theme.size("footer", size)))
        self.wordmark.updateGeometry()

    # --- tabs ------------------------------------------------------------------------------------------------- #
    def show_tab(self, name):
        if name not in self.tab_buttons or self.tab_buttons[name].isHidden():
            name = "current"
        button = self.tab_buttons[name]
        if not button.isChecked():
            button.setChecked(True)
        self.pages.setCurrentWidget(self.page_widgets[name])
        if self.services.library is not None:                 # W2.2: the other tabs' first screens, ahead
            self._warm_hidden_pages()
        if name == "needs":                                    # looked at: its failures stop counting, stay listed
            bridge.run_in_worker(self.services.status.mark_seen)
            if self.duties is not None:                       # W3.5: the update's own
                bridge.run_in_worker(self.services.updates.mark_seen)

    def current_tab(self):
        for name, b in self.tab_buttons.items():
            if b.isChecked():
                return name
        return "current"

    # --- the bottom bar --------------------------------------------------------------------------------------- #
    def _poll_status(self):
        try:
            self.services.status.poll()                    # a stat; a refresh, when due, runs on a worker
        except Exception as e:
            applog.log("shell", f"status poll: {e}")

    def show_status(self, snap):
        lines = (self._quit_line,) if self._quit == "waiting" else snap.lines     # E20: one line says so
        busy = bool(lines)
        self.bar_dot.setProperty("busy", "true" if busy else "false")
        self.bar_dot.set_running(busy)
        self.bar_line.set_full(" · ".join(lines))
        failure = snap.failure or ""
        self.bar_failure.set_full(strings.BAR_FAILURE_PREFIX + failure if failure else "")
        self.bar_failure.setVisible(bool(failure))
        self.bar_failure.setToolTip(strings.BAR_FAILURE_TIP + ("\n\n" + failure if failure else ""))
        logs_before, self._logs_folder = self._logs_folder, snap.logs
        self._status_snap = snap
        self.logs_button.setVisible(bool(failure) and bool(snap.logs))
        self._status_mark(self.bar_replan, snap.replan, strings.BAR_REPLAN_TIP.format(line=snap.replan or ""))
        self._status_mark(self.bar_ankiweb, snap.ankiweb, strings.BAR_ANKIWEB_TIP)
        self._status_mark(self.bar_connect, snap.connect, strings.BAR_CONNECT_TIP)
        if self.duties is not None:
            self._paint_journey_dot()
        needs_page = self.page_widgets.get("needs")
        if hasattr(needs_page, "set_failures"):
            needs_page.set_failures(snap.needs_you)
        if self.duties is not None and bool(logs_before) != bool(snap.logs):
            self._show_update(self.duties.update_state, force_cards=True)     # the cards' *Open the logs folder*
        self._paint_needs()

    def _status_mark(self, label, text, tip):
        """One of row 7's statuses (the re-order's line, Connect's, AnkiWeb's, the journey dot): shown while it has a
        value, repainted only when its own value (or its tooltip) changed (S19) — another field's change leaves it as it
        is."""
        text = text or ""
        eliding = isinstance(label, ElidingLabel)
        if ((label.full() if eliding else label.text()) == text and label.isHidden() != bool(text)
                and label.toolTip() == (tip if text else "")):
            return
        if eliding:
            label.set_full(text)
        else:
            label.setText(text)
        label.setToolTip(tip if text else "")
        label.setVisible(bool(text))
        self.status_paints[label] = self.status_paints.get(label, 0) + 1

    def _paint_needs(self):
        """The Needs you tab: shown while anything is listed, its badge the unseen entries (the bar's failures, the
        library's, the update's cards)."""
        snap = self._status_snap
        entries = snap.needs_you if snap is not None else ()
        listed = len(entries) + self._library_needs          # W2.2: the library's entries count too
        unseen = sum(1 for e in entries if not e.seen) + self._library_needs
        if self.duties is not None:                           # W3.5: the update's cards
            more, more_unseen = self.duties.cards.counts()
            listed, unseen = listed + more, unseen + more_unseen
        needs = self.tab_buttons["needs"]
        name = strings.TABS["needs"][0]
        if needs.count != unseen:
            needs.set_name(name, unseen, badge=True)
        needs.setVisible(listed > 0)
        if listed == 0 and needs.isChecked():
            self.show_tab("current")

    def _settings_written(self, keys):
        if "app_motion" in keys:
            motion.clock().mode.set_setting(self.services.settings.get().get("app_motion"))
        if "connect_enabled" in keys:                   # Connect's tick is skipped while off: its line asked now
            refresh = getattr(self.services.status, "refresh_soon", None)
            if refresh is not None:
                refresh("connect")
        if self.duties is not None:
            self._duty_settings(keys)
            if "logic.automation" in keys:
                self._read_d29()                        # the dot's tooltip follows D29

    def _read_d29(self):
        """D29 for the dot, read on a worker (the settings service's lock and copy stay off this thread); the dot
        repaints from it when it comes."""
        self._d29_asked += 1
        asked = self._d29_asked
        settings = self.services.settings
        read = settings.automation if hasattr(settings, "automation") else (lambda: True)
        bridge.run_in_worker(lambda: (asked, read()), then=self._d29_read,       # (a slot: none once the window is gone)
                             failed=lambda info: applog.log("shell", f"the automation switch: {info[1]}"))

    def _d29_read(self, answer):
        asked, on = answer
        if asked != self._d29_asked:
            return                                      # a newer read is on its way
        self._d29 = bool(on)
        if self.duties is not None and self._status_snap is not None:
            self._paint_journey_dot()

    def _paint_journey_dot(self):
        """The journey dot from the bar's last snapshot; its tooltip promises a Generate by itself only while D29 is on
        (the keeper runs one), else says to press Generate — D29 as last read on a worker (`_read_d29`)."""
        self._status_mark(self.duties.journey_dot, strings.JOURNEY_DOT if self._status_snap.journey else "",
                          strings.JOURNEY_DOT_TIP if self._d29 else strings.JOURNEY_DOT_TIP_PRESS)

    def open_logs(self, folder=None):
        """*Open the logs folder*: `folder`, else — while the bar's failure is an update's with a report — the report's
        folder (written beside the install, not in the logs folder), else the logs folder."""
        folder = folder or self._report_folder(getattr(self._status_snap, "failure", None)) or self._logs_folder
        if not folder:
            return
        if sys.platform == "win32":
            bridge.run_in_worker(os.startfile, folder)    # the shell's open can take a moment: off the GUI thread
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _report_folder(self, text):
        """The folder of the update report behind the update failure reading `text`, or None."""
        d = self.duties
        if not text or d is None or d.update_state is None:
            return None
        report = next((f.report for f in d.update_state.needs_you if f.text == text), None)
        return os.path.dirname(report) if report else None

    # --- W3.5: the dashboard's duties (rows 2, 4, 5) ----------------------------------------------------------- #
    def start_duties(self):
        """After the first paint (`main` connects it to `first_frame`): the duties made on a worker unless given, their
        controls attached, then started on a worker. Once."""
        if self._duties_asked:
            return
        self._duties_asked = True

        def ready(_services=None):
            self._attach_duties()
            bridge.run_in_worker(self.services.start, then=lambda started: started and self._duties_started(),
                                 failed=lambda info: applog.log("shell", f"duties at start: {info[1]}"))
        if self.services.has_duties():
            ready()
        else:
            bridge.run_in_worker(self.services.make_duties, then=ready,
                                 failed=lambda info: applog.log("shell", f"duties not made: {info[1]}"))

    def _attach_duties(self):
        """The duties' controls (the header's Generate and journey, the bar's marks, the update sheet, Needs you's
        update cards) and their signals. Imported here: none of it is on the first paint's path."""
        if self.duties is not None:
            return
        from app.qt import duties as duties_module
        s = self.services
        d = self.duties = _Duties()
        d.module = duties_module
        # the header: Generate, Your journey ↗, ? (no ▾ yet: the RUNBOOK's *Waits for Sonic's pages*; ? holds *Online
        # guide* only until the tours, IK-15 / IK-24)
        d.generate = duties_module.GenerateControl(self.header)
        d.generate.pressed.connect(self._generate_pressed)
        d.generate.log_asked.connect(self._open_generate_log)
        d.journey = QPushButton(strings.JOURNEY, self.header)
        d.journey.setToolTip(strings.JOURNEY_NONE_TIP)
        d.journey.setAccessibleName(strings.JOURNEY)
        d.journey.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        d.journey.setCursor(Qt.CursorShape.PointingHandCursor)
        d.journey.setEnabled(False)                     # until a journey is found on disk
        d.journey.clicked.connect(self._open_journey)
        d.help = QToolButton(self.header)
        d.help.setText(strings.HELP)
        d.help.setToolTip(strings.HELP_TIP)
        d.help.setAccessibleName(strings.HELP_NAME)
        d.help.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        d.help.setCursor(Qt.CursorShape.PointingHandCursor)
        d.help.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(d.help)
        menu.addAction(strings.HELP_GUIDE).triggered.connect(self._open_guide)
        d.help.setMenu(menu)
        d.journey_dot = QLabel(self.header)               # row 7: the sentences catching up (02-state-model, G10)
        d.journey_dot.setObjectName("journeydot")
        d.journey_dot.setTextFormat(Qt.TextFormat.PlainText)
        d.journey_dot.setAccessibleName(strings.JOURNEY_DOT_NAME)
        d.journey_dot.setVisible(False)
        self.header.layout().addWidget(d.generate)
        d.generate.add_beside(d.journey)
        d.generate.add_beside(d.journey_dot)
        d.generate.add_beside(d.help)
        # the bar: N known, the Anki mark, the level chip (statuses: W3.3 makes them open Settings), the update mark
        row = self.footer.layout()
        for name in ("known", "anki", "level"):
            label = QLabel(self.footer)
            label.setObjectName("barmark")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setVisible(False)
            row.addWidget(label)
            setattr(d, name, label)
        d.update_mark = QPushButton(strings.UPDATE_READY, self.footer)
        d.update_mark.setToolTip(strings.UPDATE_MARK_IDLE_TIP)
        d.update_mark.setAccessibleName(strings.UPDATE_READY)
        d.update_mark.setProperty("kind", "chip")
        d.update_mark.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        d.update_mark.clicked.connect(self.open_update_sheet)
        d.update_mark.setVisible(False)
        row.addWidget(d.update_mark)
        # the update sheet (an overlay: Esc and Back close it — and cancel an update under way, IK-2)
        d.sheet = duties_module.UpdateSheet(self.centralWidget())
        d.sheet.action.connect(self._update_action)
        d.sheet.dismissed.connect(self._sheet_dismissed)
        self.register_overlay(d.sheet)
        # Needs you: the update's cards, above the page's list
        page = self.page_widgets["needs"]
        d.cards = duties_module.UpdateCards(page)
        d.cards.action.connect(self._update_action)
        lst = getattr(page, "list", None)
        if lst is not None:
            box = page.layout().itemAt(0).layout()
            box.insertWidget(box.indexOf(lst), d.cards)
        else:
            page.layout().insertWidget(0, d.cards)
        # the services, through the bridge
        self.bridge.update_changed.connect(self._show_update)
        self.bridge.generate_changed.connect(self._show_generate)
        self.bridge.automation_changed.connect(self._show_automation)
        self.bridge.chores_changed.connect(self._show_chores)
        self.bridge.indexed.connect(lambda _language: self._read_level())
        self.bridge.attach(updates=s.updates, controller=s.controller, automation=s.automation, chores=s.chores)
        self._show_update(s.updates.state())
        self._show_generate(s.controller.state())
        self._show_automation(s.automation.state())
        if self._status_snap is not None:                   # the dot the bar's last snapshot asked for
            self._paint_journey_dot()
        self._read_d29()                                    # its tooltip's D29, read on a worker

    def _duties_started(self):
        """Started: what the bar and the header read from disk, read on workers."""
        self._check_journey()
        self._read_level()

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and self.duties is not None
                and self.services.started):
            bridge.run_in_worker(self.services.activated)   # the Tk <FocusIn>: the services keep their throttles

    def _duty_settings(self, keys):
        """A write landed: Koe's switch, a language switch, a change that makes the journey stale, the level."""
        s = self.services
        settings = s.settings.get()
        if any(k == "enable_koe" or k.startswith("koe") for k in keys):
            bridge.run_in_worker(s.chores.koe_changed)
        language = settings.get("target_language") or "ja"
        if "target_language" in keys and language != s.language:
            bridge.run_in_worker(s.language_changed, language, then=lambda _r: self._read_level())
        elif s.level_moved(keys):                           # only what the level reads (IK-28, S19)
            self._read_level()
        if "anki_sync_auto" in keys:
            self._show_automation(s.automation.state())
        try:
            stale = s.settings.stales(keys, language)
        except Exception:
            stale = False
        if stale:
            bridge.run_in_worker(s.automation.recheck)      # the Generate button's mark asked again

    # Generate
    def _show_generate(self, state):
        d = self.duties
        before, d.generate_state = d.generate_state, state
        d.generate.show_state(state)
        busy = ("queued", "running", "cancelling")
        ended = before is not None and before.state in busy and state.state not in busy
        if (state.state == "failed") != (before is not None and before.state == "failed") or ended:
            self.services.status.refresh_soon()            # its failure on, or off, the bar and Needs you (E10, HR-23)
        if ended:
            self._check_journey()                          # a run ended: a journey on disk now, the level again
            self._read_level()

    def _generate_pressed(self):
        """A click runs Generate — or, while one the user asked for is asked for or running, cancels it (before
        *Writing your list*). On an automatic run the click is the user's own run, which takes its place (IK-20)."""
        d = self.duties
        state = d.generate_state
        s = self.services
        if state is not None and state.state in ("queued", "running", "cancelling") and not state.quiet:
            if d.module.gen.can_cancel(state):
                bridge.run_in_worker(s.controller.cancel)
            return
        bridge.run_in_worker(s.generate, failed=lambda info: self.bar_line.set_full(str(info[0])))

    def _open_generate_log(self):
        path = getattr(self.duties.generate_state, "log_path", None)
        if path:
            self._open_path(path)

    def _open_guide(self, _checked=False):
        bridge.run_in_worker(self.services.open_guide)     # the browser can take a moment: off the GUI thread

    def _open_path(self, path):
        if sys.platform == "win32":
            bridge.run_in_worker(os.startfile, path)      # the shell's open can take a moment: off the GUI thread
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # Your journey
    def _check_journey(self):
        bridge.run_in_worker(self.services.journey_exists, then=self._show_journey,
                             failed=lambda info: self._show_journey(False))

    def _show_journey(self, exists):
        b = self.duties.journey
        exists = bool(exists)
        if b.isEnabled() != exists:
            b.setEnabled(exists)
            b.setToolTip(strings.JOURNEY_TIP if exists else strings.JOURNEY_NONE_TIP)

    def _open_journey(self):
        bridge.run_in_worker(self.services.open_journey, then=lambda opened: opened or self._show_journey(False),
                             failed=lambda info: self.bar_line.set_full(strings.JOURNEY_FAILED.format(why=info[0])))

    # the bar's marks
    def _mark(self, label, text, tip=""):
        """A status mark set — repainted only when its words changed (S19). -> True when it changed."""
        if label.text() == text and label.toolTip() == tip and label.isHidden() != bool(text):
            return False
        if label.text() != text:
            label.setText(text)
            label.setAccessibleName(text)
        label.setToolTip(tip)
        label.setVisible(bool(text))
        self.duties.paints[label] = self.duties.paints.get(label, 0) + 1
        return True

    def _show_automation(self, state):
        d = self.duties
        d.auto_state = state
        junban = getattr(state, "junban", None)
        if junban and junban != d.junban_said:             # 順's line, once (the Tk `_on_junban_auto`: IK-23)
            d.junban_said = junban
            self.toasts.show(junban)
        known = getattr(state, "known", None)
        self._mark(d.known, strings.BAR_KNOWN.format(n=known) if known is not None else "",
                   strings.BAR_KNOWN_TIP if known is not None else "")
        if not self.services.settings.get().get("anki_sync_auto"):
            key = "off"
        else:
            key = state.sync if state.sync in strings.BAR_ANKI else None
        if key is None:
            self._mark(d.anki, "")
            return
        tip = strings.BAR_ANKI_TIP[key]
        if key == "synced" and state.added:
            tip = strings.BAR_ANKI_TIP["synced-added"].format(n=state.added)
        elif key == "failed":
            tip = tip.format(message=state.message or "")
        self._mark(d.anki, strings.BAR_ANKI[key], tip)

    def _read_level(self):
        if self.duties is not None:
            bridge.run_in_worker(self.services.level, then=self._show_level)

    def _show_level(self, level):
        from app import word_selection
        band, automatic = level
        name = word_selection.band_label(band) if band else ""
        if automatic:
            text = strings.BAR_LEVEL_AUTO.format(band=name) if name else strings.BAR_LEVEL_AUTO_NONE
            tip = strings.BAR_LEVEL_AUTO_TIP.format(band=name) if name else strings.BAR_LEVEL_AUTO_NONE_TIP
        else:
            text, tip = name, strings.BAR_LEVEL_TIP.format(band=name)
        self._mark(self.duties.level, text, tip if text else "")

    def _show_chores(self, state):
        notice = getattr(state, "notice", None)
        if notice and notice != self.duties.notice:        # Connect's line, once: a toast
            self.duties.notice = notice
            self.toasts.show(notice)

    # the update
    def _show_update(self, state, force_cards=False):
        d = self.duties
        d.update_state = state
        look = d.module.update_mark_look(state)
        m = d.update_mark
        if look is None:
            if not m.isHidden():                           # nothing to say: hidden, its last words kept
                m.setVisible(False)
                d.paints[m] = d.paints.get(m, 0) + 1
        elif m.text() != look[0] or m.toolTip() != look[1] or m.isHidden():
            m.setText(look[0])
            m.setToolTip(look[1])
            m.setAccessibleName(look[0])
            m.setVisible(True)
            d.paints[m] = d.paints.get(m, 0) + 1
        d.sheet.show_state(state)
        if state.state in ("none", "failed") and d.sheet.isVisible():
            d.sheet.hide()                                 # nothing on offer: the sheet goes (hidden: no cancel)
        if state.open_now:
            self.open_update_sheet()                       # a critical release, once (the service says when)
        if state.updated and state.updated != d.updated_said:
            d.updated_said = state.updated                 # *Updated to v… ✓*, once (the Tk reconcile: IK-23)
            self.toasts.show(strings.UPDATED.format(version=state.updated))
        unseen = tuple(f.text for f in state.needs_you if not f.seen)
        if unseen != d.update_unseen:
            d.update_unseen = unseen
            self.services.status.refresh_soon()            # its newest unseen failure on, or off, the bar (HR-23)
        if d.cards.show_state(state, logs=bool(self._logs_folder)) or force_cards:
            self._paint_needs()

    def open_update_sheet(self):
        d = self.duties
        if d is None or d.update_state is None or d.update_state.state in ("none", "failed"):
            return
        d.sheet.show_state(d.update_state)
        d.sheet.open()
        d.sheet.raise_()

    def _update_action(self, name, key):
        """A click on the sheet or a Needs you card, sent to the update service on a worker."""
        u = self.services.updates
        if name == "start":
            bridge.run_in_worker(u.start)
        elif name in ("download", "notes"):
            bridge.run_in_worker(u.open_download)
        elif name == "skip":
            self.duties.sheet.hide()
            bridge.run_in_worker(u.skip, key)              # `skipped_version` written, nothing else
        elif name == "stop":
            bridge.run_in_worker(u.stop, key)
        elif name == "stop-all":
            bridge.run_in_worker(u.stop)
        elif name == "cancel":
            self.duties.sheet.hide()
            self._cancel_update()
        elif name == "logs":
            self.open_logs(key)                            # a failure's card: its report's folder, when it has one

    def _sheet_dismissed(self):
        """Esc, Back or *Later* closed the sheet: an update downloading or waiting is cancelled (IK-2, as Tk)."""
        state = self.duties.update_state
        if state is not None and state.state in ("downloading", "waiting"):
            self._cancel_update()

    def _cancel_update(self):
        s = self.services
        bridge.run_in_worker(s.updates.cancel,
                             then=lambda cancelled: cancelled and bridge.run_in_worker(s.automation.update_cancelled))

    def _quit_for_update(self, _value=None):
        """The update hands over (its `on_quit`): the window closes, and the app with it — at once: the update waited
        for the Anki writers itself (its wait list), and the updater waits on this process."""
        self._quit = "ready"
        self.close()
        QApplication.quit()
    # --- end W3.5 ------------------------------------------------------------------------------------------------ #

    # --- the look ------------------------------------------------------------------------------------------- #
    def set_look(self, theme_name=None, text_size=None):
        """Settings › App › Theme / Text size (W3.3 calls it): saved through the settings service, and applied at
        once (LIVE_LOOK) — else *Restart to apply* in the bar. -> the milliseconds the switch took, or None."""
        current_theme, current_size, language = style.current()
        theme_name = theme_name if theme_name in theme.THEMES else current_theme
        text_size = text_size if text_size in theme.TEXT_SIZES else current_size
        self.services.settings.set({"app_theme": theme_name, "text_size": text_size})
        if not LIVE_LOOK:
            self.bar_line.set_full(strings.RESTART_TO_APPLY)
            return None
        ms = style.apply(QApplication.instance(), theme_name, text_size, language)
        titlebar.apply(self, theme_name)
        self._apply_sizes()
        self.update()
        return ms

    # --- overlays --------------------------------------------------------------------------------------------- #
    def register_overlay(self, overlay):
        """An in-window overlay (tray, sheet, panel, popover): Esc, Back and a click outside close it (05 §5.4)."""
        self.router.register(overlay)

    # --- showing, closing, remembering -------------------------------------------------------------------- #
    def bring_to_front(self, _args=None):
        """A second start handed over: show this window, un-minimised (still maximised if it was), in front."""
        state = self.windowState()
        if state & Qt.WindowState.WindowMinimized:
            self.setWindowState(state & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._first_painted:
            self._first_painted = True
            hud.mark("painted")
            QTimer.singleShot(0, self._frame_flushed)         # after this frame is flushed

    def _frame_flushed(self):
        self.first_frame.emit()

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_bar_coloured", False):
            self._bar_coloured = True
            titlebar.apply(self, style.current()[0])
            self._rest.setFocus(Qt.FocusReason.OtherFocusReason)

    def _restore_state(self, state):
        """Size, place and tab, before the first paint, with the tabs' signals blocked (a restored tab is not a
        click)."""
        screens = [s.availableGeometry() for s in QGuiApplication.screens()]
        rect = valid_geometry(state.get("geometry"))
        if rect is None:
            rect = QRect(-100000, -100000, *DEFAULT_SIZE)  # nothing usable saved: off every screen, so the default
        rect = fit_on_screens(rect, screens)
        rect.setWidth(max(rect.width(), theme.WINDOW_MIN[0]))
        rect.setHeight(max(rect.height(), theme.WINDOW_MIN[1]))
        self.setGeometry(rect)
        self._start_maximized = bool(state.get("maximized"))
        tab = state.get("tab")
        if tab in TABS and tab != "needs":
            self.tab_group.blockSignals(True)
            for b in self.tab_buttons.values():
                b.blockSignals(True)
            try:
                self.tab_buttons[tab].setChecked(True)
                self.pages.setCurrentWidget(self.page_widgets[tab])
            finally:
                for b in self.tab_buttons.values():
                    b.blockSignals(False)
                self.tab_group.blockSignals(False)

    def state_now(self):
        g = self.normalGeometry() if self.isMaximized() else self.geometry()
        return {"version": STATE_VERSION, "geometry": [g.x(), g.y(), g.width(), g.height()],
                "maximized": self.isMaximized(), "tab": self.current_tab()}

    def show_first(self):
        """Show the window as it was left (maximised or not)."""
        if getattr(self, "_start_maximized", False):
            self.showMaximized()
        else:
            self.show()

    # --- E20: closing while an Anki write runs -------------------------------------------------------------- #
    def _finish_first(self):
        """The close while a `wait` job runs (an Anki write mid-batch, the Tk `_replan_finishing`; Generate writing
        your list): the window stays, the bar's one line says why, Generate and the update sheet's actions are off
        (nothing new starts; a Generate before its cancel point is cancelled at once: `Services.begin_quit`, on a
        worker), and the window closes by itself when no such job runs any more — the registry's own signal
        (`_jobs_changed`) — or at `QUIT_FINISH_WAIT`. A second close, or Esc, changes nothing. Once."""
        if self._quit == "waiting":
            return
        self._quit = "waiting"
        waited = jobs_module.waits_at_quit(self._jobs)
        self._quit_line = (strings.QUIT_FINISHING_LIST if waited and all(j.kind == "generate" for j in waited)
                           else strings.QUIT_FINISHING)
        self.closing.emit()                               # a start from now on waits for the claim (single.py)
        if self.duties is not None:                       # no control that does nothing: nothing new starts now
            self.duties.generate.hold(strings.QUIT_CLOSING_TIP)
            self.duties.sheet.hold(strings.QUIT_CLOSING_TIP)
            self.duties.cards.hold(strings.QUIT_CLOSING_TIP)
        self._quit_timer = QTimer(self)
        self._quit_timer.setSingleShot(True)
        self._quit_timer.timeout.connect(self._close_now)
        self._quit_timer.start(int(QUIT_FINISH_WAIT * 1000))
        if self._status_snap is not None:
            self.show_status(self._status_snap)
        bridge.run_in_worker(self.services.begin_quit,
                             failed=lambda info: applog.log("shell", f"the quit's start: {info[1]}"))
        wait = getattr(self.services, "replan_wait", None)
        if wait is not None:                              # a move's settle, run at once by the host's close (row 7)
            self._replan_waited = False
            bridge.run_in_worker(wait, then=self._replan_idle, failed=self._replan_idle)

    def _replan_idle(self, _ended):
        self._replan_waited = True
        self._jobs_changed(self._jobs)

    def _replan_settling(self):
        settling = getattr(self.services, "replan_settling", None)
        return settling is not None and settling()

    def _jobs_changed(self, views):
        self._jobs = views
        if self._quit == "waiting" and self._replan_waited and not jobs_module.waits_at_quit(views):
            self._close_now()

    def _close_now(self):
        if self._quit != "waiting":
            return
        self._quit = "ready"
        self._quit_timer.stop()
        self.close()

    def closeEvent(self, event):
        if self._quit == "waiting" or (self._quit is None and (jobs_module.waits_at_quit(self._jobs)
                                                               or self._replan_settling())):
            event.ignore()                                # E20: what can't stop part-way ends first
            self._finish_first()
            return
        self.closing.emit()                               # single instance stops listening before the window hides
        self._poll.stop()
        self.bridge.stop()                                # the quit's service callbacks reach no slot from here
        state = self.state_now()
        self.hide()
        try:
            write_state(self.state_file, state)
        except OSError as e:
            applog.log("shell", f"window state not saved: {e}")
        app = QApplication.instance()
        app.removeEventFilter(self.router)
        self.tooltips.uninstall(app)
        super().closeEvent(event)


# --- opening ------------------------------------------------------------------------------------------------------ #
def open_window(app, services, state_file=None):
    """The look from settings on the QApplication, then the window (not shown yet): theme before the first paint."""
    s = services.settings.get()
    language = s.get("target_language") or "ja"
    script = s.get("zh_script") if language == "zh" else None
    style.apply(app, s.get("app_theme"), s.get("text_size"), language, script)
    icon = path_utils.get_icon_path()
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    hud.mark("look")
    window = ShellWindow(services, state_file=state_file)
    hud.mark("window")
    return window


def _log_unhandled(kind, value, tb):
    # PyQt6 aborts the process on an exception escaping a slot unless a hook is set: the window logs it and goes on.
    text = "".join(traceback.format_exception(kind, value, tb))
    applog.log("unhandled", text)
    sys.__stderr__ and sys.__stderr__.write(text)


# Python's lock is handed between threads every 5 ms by default: a busy worker (a service's thread, a pool task) could
# hold the GUI thread off for that long — over the 4 ms step. 1 ms keeps a step's wait under the budget (W2.1 review A3).
SWITCH_INTERVAL_S = 0.001


def prepare_process():
    """The window process's own settings: an exception escaping a slot is logged, never fatal (PyQt6 aborts
    otherwise); Python's lock changes hands every millisecond."""
    sys.excepthook = _log_unhandled
    sys.setswitchinterval(SWITCH_INTERVAL_S)


def connect_instance(window, instance):
    """A later start brings this window forward; closing stops listening before the window hides (single.py)."""
    instance.activated.connect(window.bring_to_front)
    window.closing.connect(instance.stop_listening)


def main(argv=None):
    """The window's start: one per session (`single.py`), the look before the first paint, the HUD when asked."""
    argv = list(sys.argv if argv is None else argv)
    hud.mark("main")                                  # the probe's phases (M2.1 row D); nothing when it is off
    from app.qt import single as single_module
    app = QApplication.instance() or QApplication(argv[:1])
    hud.mark("qapp")
    prepare_process()
    instance = single_module.SingleInstance()
    if not instance.claim(argv[1:]):
        return 0
    hud.mark("claimed")
    services = Services()
    hud.mark("services")
    window = open_window(app, services)
    connect_instance(window, instance)
    probe_file = os.environ.get("SURASURA_SHELL_PROBE")
    # (measuring, the HUD keeps its overlay off: the overlay's own first show would be timed as the window's)
    meter = hud.Hud(window, overlay=not probe_file).start() if hud.wanted(argv) else None
    if probe_file:                                    # tests/qt/measure_shell.py: shown without taking the keyboard
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        hud.Probe(window, probe_file, hud=meter)
    window.first_frame.connect(window.start_duties)  # W3.5: the duties after the first paint
    window.show_first()
    hud.mark("shown")
    try:
        code = app.exec()
    finally:
        try:
            services.shutdown(release=instance.release)   # the claim goes before the store's close trigger
        finally:
            instance.release()                            # (once: done already unless the quit failed before it)
    return code


if __name__ == "__main__":
    sys.exit(main())
