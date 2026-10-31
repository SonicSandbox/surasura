"""The shell: Surasura 3.0's main window (W2.1; the window's spec 01 §1.5 item 1, 05 §5.1–5.5, §5.9, §5.11–5.12).

The window, edge to edge under Windows' own title bar (n1); the header (the mark, the wordmark, the subline); the tabs
(Current · Finished · Needs you · Settings) over one page each; the bottom bar (what runs, the newest command-line
failure, Connect's line when it exists). W3.1a's frame (`frame.py`): the header + tabs one band with the vein under the
current tab and the jobs' hairline along its foot, the level ▾ and its pop (Generate, *Open your journey*) with *Journey ↗* beside it, the edges
baked onto the content, the footer's emerald (the AnkiWeb mark's words in its hover) and known corner, and Current's
Goal dock (its wells for the drag). Given a library (`Services(library=…)`: W2.2's reader),
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

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPointF, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QFontMetrics, QFontMetricsF, QGuiApplication, QIcon, QKeySequence,
                         QLinearGradient, QPainter, QShortcut)
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
                             QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from app import path_utils, theme
from app.qt import applog, bridge, frame, hud, motion, strings, style, titlebar, toast, tooltip
from app.services import jobs as jobs_module
from app.services import press as press_service
from app.services import settings as settings_service
from app.services import status as status_service
from app.services import view_rows                         # the journey's episode for a row (JO-3)
from app.qt import screens                                # W2.2: the pages a library fills
from app.qt import press as qpress                        # round 8 row 45: a press reacts at once
from app.qt import standing as standing_qt                # round 8 row 54: every standing line's ✕
from app.qt import phase_strip                            # the phase strip: five circles at the bar's bottom left
from app.services import phase as phase_service
from app.services import standing as standing_service
from app.qt import covers as qcovers                      # --- W3.2 Q6: the titles' own pictures

TABS = ("current", "finished", "needs", "settings")
STATE_FILE = "window_state.json"
STATE_VERSION = 1
DEFAULT_SIZE = (1280, 800)
POLL_MS = 500
LOOK_TICK_MS = 5 * 60 * 1000    # SRC W1b: the source folders' tick (`sources.due` says when it's an hour: FOCUS_S apart)
JOURNEY_FILE = "reading_list_static.html"   # the report's file in `results` (`static_html_generator.OUTPUT_FILE`)
JOURNEY_LACKS = "lacks"     # `Services.open_journey`: opened, but the asked episode isn't in the journey yet (JO-1)
JOURNEY_OLD_LOOK = "old-look"   # ... opened as drawn before a Journey setting changed: a Generate is due (a6 #5)
GONE_GO = phase_service.Go("needs", ("folder-gone",))   # a7: 届 amber for a gone folder opens its card (`needs.FOLDER_GONE`,
#                                                         the services' needs module: not imported by the shell at load)
JOURNEY_DRAW_WAIT = 60.0    # a6 #5: how long *Journey ↗* waits for a re-render (seconds), then opens the journey as it is
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
# W3.2 P0 (AD0-1): at a language switch, the old writer's thread is waited for up to the store's lock wait and this
WRITER_JOIN_MARGIN = 1.0
# P-text (W2.1 row 9): a theme or text-size switch with the shell's widgets alive measured well under ~300 ms, so a
# change applies at once (G1.2-21). W3.3 measures it again with its Settings page alive; False = *Restart to apply*.
LIVE_LOOK = True
REFRESH_CAP_S = 120.0                  # round 8 row 45: Refresh's press at most this long (a look that failed tells nothing)
# W3.4: at exit, how long the quit waits for the thread pool's workers (`bridge.wait_for_workers`) after the window
# closed and the duties stopped, and for each of the ported 順 windows' own threads (`junban-*`): a worker still running
# Python as the process ends can crash it (row 6's find).
QUIT_WORKERS_MS = 3000
QUIT_THREAD_JOIN_S = 2.0


# --- the services the window calls ------------------------------------------------------------------------------- #
class Services:
    """The window's services, made once per window (the settings file is read here, before the first paint).

    W3.5: the dashboard's duties — the Generate controller, the update service, automatic sync / Generate / 順
    (`automation`) and the start-up chores — are given (a test's stand-ins) or made by `make_duties()` on a worker
    after the first paint (`ShellWindow.start_duties`, which `main` connects; their imports stay off the first paint),
    then started there (`start`). Qt-free: everything here runs on a worker or after the window is gone."""

    def __init__(self, settings=None, registry=None, status=None, library=None, controller=None, updates=None,
                 automation=None, chores=None, replan=None, writer=None, library_for=None):
        self.settings = settings if settings is not None else settings_service.SettingsService()
        self.registry = registry if registry is not None else jobs_module.JobRegistry()
        self.status = status if status is not None else status_service.StatusService(self.registry)
        self.library = library            # W2.2: a library reader (app/services/library_reader.py), or None
        # W3.1a: the window's writer (`app/services/moves.Writer`, on the reader's opener; its `numbers` the reader's),
        # or None — then nothing in the window writes. The window starts it (and its replay) and wires its callbacks;
        # the quit waits for its queue (`finish_moves`). The real `main()`'s: `open_services` (W3.2 P0).
        self.writer = writer
        self._wire_writer(writer)
        # --- W3.2 P0: `library_for(language)` -> (reader, writer): another language's library at a switch
        # (`_switch_library`); None (a test's library, or none) — the window keeps the library it was given
        self.library_for = library_for
        self.library_after_frame = False        # True (`open_services`): the window starts the reader after the first frame
        self.library_failed = None              # main's words when `open_services` failed (the pages say them)
        self._library_lock = threading.Lock()   # one switch at a time; the quit waits for one under way
        self._asked = None                      # the language the window asked for last (`ask_language`, its thread)
        # --- W3.5: the duties
        self.controller, self.updates, self.automation, self.chores = controller, updates, automation, chores
        # row 7: the journey keeper and the re-order host of the language open (`replan_host.Replan`), made with the
        # duties (given: a test's); never one of `has_duties`' four
        self.replan = replan
        self._replan_wired = False
        self._generate_wired = False            # a6: the controller's end heard once (`_generate_ended`)
        self.replan_heard = []                  # finish-pending: told each line the host says (its worker) — the
        #                                         window's drag controller's: a press waiting for its re-order ends
        #                                         with some
        self.language = self.settings.get().get("target_language") or "ja"
        self.closing = threading.Event()  # set at quit: a Generate still waiting for `results` starts nothing
        self.quit_hook = None             # the window's: the update hands over (called on a worker)
        self.say = None                   # the window's: a line for its bottom bar (any thread; Q4-16's session look)
        self.anki_look = None             # Q4-4 / Q4-16: the window's session look (default `anki_session.at_window`;
        #                                   a test's stand-in)
        self.anki_session_thread = None   # the look's thread at the window's start (`_look_at_anki`), once started
        self.restarted = False            # alpha 4 M6: this start is *Restart now*'s (`RESTARTED`): Anki isn't opened
        self._look_after_setup = False    # B-10: the start's look held while the setup wizard is up (AD-8)
        self._sync_owed = False           # the start's forced known-words sync, owed to the start's look (IK-2)
        self._session_lock = threading.Lock()
        self._session_running = False     # a session look under way (one at a time)
        self._session_looked = float("-inf")    # when the last one began (`time.monotonic`; the focus's throttle)
        self.started = False
        self._quit_lock = threading.Lock()
        self._quit_began = None           # when the quit began (`_stop_starting`): E20's wait counts from it
        self._held = False                # row 35: gated jobs held while the close's sheet asks (`hold_starting`)
        # W3.5 part 3 (AD-8 / IK2-7): set while the setup wizard is up — no quiet Generate (the automatic one, the
        # journey keeper's) before its last page sets the level; an upgrader's library has no journey yet
        self.setup_open = threading.Event()
        if self.has_duties():
            self._provide()

    # --- W3.5: the dashboard's duties --------------------------------------------------------------------------- #
    SESSION_LOOK_EVERY = 60.0     # seconds between two of the session's looks at a focus (the Tk CONNECT_LOOK_EVERY)

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
        on_end = getattr(self.controller, "on_end", None)
        if on_end is not None and not self._generate_wired:
            self._generate_wired = True
            on_end(self._generate_ended)
        self._wire_replan()

    def _generate_ended(self, _run, outcome):
        """(The run's thread.) a6: a Generate that finished wrote a new plan, and nothing else tells the numbers so —
        they re-read it only when the order moves (`moves.open_library`), and a Generate moves no order: Current's rows
        kept *not analysed yet* until the next move. Any Generate — the user's, the automatic one, the keeper's."""
        if outcome != "current" or self.closing.is_set():
            return
        resync = getattr(getattr(self.writer, "numbers", None), "resync", None)
        if resync is not None:
            try:
                resync()
            except Exception as e:
                applog.log("shell", f"the numbers after a Generate: {e!r}")

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
        """Worker B's providers (W3.5 row 7): the host's line, Connect's line, the AnkiWeb mark, the journey dot — and
        (W31A-2) the cards waiting in Anki — again on a language switch (Connect's line, the dot and the backlog are
        the language's)."""
        providers = getattr(self.status, "providers", None)
        if providers is None:
            return
        replan, get = self.replan, self.settings.get
        providers.update(replan=replan.line,
                         connect=status_service.connect_line(language, get, feed=connect_feed(language, self.settings),
                                                             registry=self.registry),       # row 40: in the line
                         # P4.1 L2 (row 4.1.13): the feed the library's stones are built from — one stamp a tick
                         ankiweb=status_service.ankiweb_line(get), journey=status_service.journey_pending(language),
                         backlog=status_service.anki_backlog(language))

    def _replan_line(self, line):
        """The host said a new line (its worker): the bar asks for it alone; the presses waiting for its re-order hear
        it (`replan_heard`)."""
        refresh = getattr(self.status, "refresh_soon", None)
        if refresh is not None:
            refresh("replan")
        for heard in list(self.replan_heard):
            try:
                heard(line)
            except Exception as e:
                print(f"Re-order: a listener failed: {e!r}")

    def _wire_writer(self, writer):
        """W-1 (K-W4): a mark that moved what counts (`Writer.on_counted`) asks the indexer, so the Rarity preview
        follows; and a mark that moved nothing that counts (`Writer.on_stone`, Keep studying on) asks the journey keeper,
        so the report shows its stone (JS-1)."""
        if writer is not None:
            writer.on_counted = self._counted
            writer.on_stone = lambda: self._stone_marked(writer.language)

    def _counted(self):
        """(The writer's thread.) The indexer asked, forced (`Chores.index`: one check and one indexer at a time, so a
        burst of marks is one run while it is under way); nothing before the duties are made or once the quit began."""
        chores = self.chores
        if chores is not None and not self.closing.is_set():
            chores.index(force=True)

    def _stone_marked(self, language):
        """(The writer's thread.) A watched mark, or its undo, that moved nothing that counts: the journey keeper's
        `marked("stone")` (it reads only the Generate's state; its timer asks whether the report is current, after any
        run in flight) — never once the quit began (the next start's look asks the report half). A mark that moved what
        counts moves `order_version`: `_store_moved` hears that one."""
        if self.closing.is_set() or self.replan is None:
            return
        stone_marked = getattr(self.replan, "stone_marked", None)
        if stone_marked is not None:
            stone_marked(language)

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
            self._hold_while_setup()
            try:
                self.controller.check(settings_service.thaw(self.settings.get()), self.language)
            except Exception as e:
                applog.log("shell", f"the journey check at start: {e}")
            self.updates.begin()
            session = self._session_settings()        # Connect on: the session look first (Q4-4), then known words
            if session is not None:
                self.automation.started(session=True)
            else:
                self.automation.started()
            self._sync_owed = session is not None     # the start's one forced known-words sync waits for the look
            self.chores.started()
            if self.replan is not None:
                self.replan.start()       # the catch-up once; the journey when the store says it is pending
            if self.setup_open.is_set():
                # B-10 (AD-8): no look at Anki while the setup wizard is up — Anki opened, synced and Connect kicked
                # once it closes, on the settings it wrote, whatever Connect was at the start (review F-2)
                self._look_after_setup = True
            elif session is not None:
                self._opening_look(session)
        return True

    def _opening_look(self, session):
        """The window's start look (`_look_at_anki`, opening): once a window. Alpha 4 M6: a start *Restart now* made
        never opens the Anki you closed (`restarted`: its look only, the setting left as it is)."""
        if self.restarted:
            session = dict(session, connect_open_anki=False)
        self.anki_session_thread = self._look_at_anki(session, opening=True)

    # --- Q4-4, Q4-16 (K102): a session's start, and *Open Anki for me* at the window's start only ------------------ #
    def _session_settings(self):
        """The settings when the window's session look may run — Connect on (`anki_session.on`: its switch, D29's
        automation, Anki not switched off for the run) — else None."""
        try:
            from app.connect import anki_session
            settings = settings_service.thaw(self.settings.get())
            return settings if anki_session.on(settings) else None
        except Exception as e:
            applog.log("shell", f"the session's look: {e!r}")
            return None

    def _look_at_anki(self, settings, opening):
        """The window's session look (P2.3 row 2.3.6; ✅ Q4-4: "sync once when a session starts (when Anki opens, or
        when Surasura starts with Anki open)") on its own thread — it may wait up to two minutes for an Anki it started:
        `anki_session.at_window`, at the window's start (`opening`, from `start`: once a window) and at a focus at most
        once every SESSION_LOOK_EVERY (`_focus_look`), one at a time. Anki closed is recorded (the next look starts a
        session); Anki open and a session starting: its one sync. Only at the window's start, with *Open Anki for me* on
        (`connect_open_anki`, off by default, ✅ Q4-16, P2.3-1 a), may a closed Anki be started for you — never at a
        focus, a language switch or after mining (BRIEF). -> the thread, or None (one already looking, or too soon)."""
        now = time.monotonic()
        with self._session_lock:
            if self._session_running or (not opening and now - self._session_looked < self.SESSION_LOOK_EVERY):
                return None
            self._session_running, self._session_looked = True, now
        thread = threading.Thread(target=self._session, args=(settings, opening), name="anki-session", daemon=True)
        thread.start()
        return thread

    def _focus_look(self):
        """(A worker.) A focus: the session look again, at most once every SESSION_LOOK_EVERY; it never opens Anki —
        nor looks at all while the setup wizard is up (review F-1: the wizard's close makes the window's look)."""
        if self.setup_open.is_set():
            return
        settings = self._session_settings()
        if settings is not None:
            self._look_at_anki(settings, opening=False)

    def _session_job(self, opening):
        """IK-6 (alpha 3 intent keeper): the window's start look listed in the registry while it runs (it may start
        Anki and wait up to two minutes for it), on the Anki circle — a focus's quick look is none (it would flicker
        each minute). No Cancel: the quit ends it (`closing`), so the quit never waits for it. -> the job, or None."""
        if not opening:
            return None
        try:
            return self.registry.record(SESSION_JOB, strings.SESSION_JOB_LABEL, on_quit="detach")
        except Exception as e:
            applog.log("shell", f"the session look's job: {e!r}")
            return None

    def _session(self, settings, opening):
        """(Its own thread.) The look (`at_window`), its line to the bar (`anki_session.told`, the 2.x dashboard's
        words), then the known-words sync — at the window's start the one start sync, forced, after the session's sync
        whatever it found (`Automation.started(session=True)` armed none, IK-2); at a focus with Anki open, forced only
        when the session's sync brought your phone's reviews in — and, synced, Connect kicked to see what waits, on the
        settings as they are now (IK-5; the Tk `_connect_session`'s order). A quit ends the wait for the Anki it
        started at its next look, never starts Anki or a sync after it (`cancel`), and nothing follows it."""
        job = self._session_job(opening)
        try:
            if self.closing.is_set():
                return
            from app.connect import anki_session
            look, done = self.anki_look or anki_session.at_window, None
            try:
                done = look(settings, opening=opening, say=self._say, sleep=self.closing.wait,     # a quit ends its wait
                            clock=lambda: float("inf") if self.closing.is_set() else time.time(), cancel=self.closing)
            except Exception as e:
                applog.log("shell", f"Connect's session look: {e!r}")
            if self.closing.is_set():
                return
            self._say(anki_session.told(done))
            sync = (done or {}).get("sync")
            if opening:     # the start's one forced sync — at its own pace when the start already made it (F-2)
                owed, self._sync_owed = self._sync_owed, False
                self.automation.session_began(owed)
            elif (done or {}).get("anki") == "open":
                self.automation.session_began(sync == "synced")
            if sync == "synced":
                now = self._session_settings()
                if now is not None:
                    from app.connect import kick
                    kick.kick(now)
        except Exception as e:
            applog.log("connect", f"after the session's look: {e!r}")
        finally:
            if job is not None:
                job.finish(ok=True)
            with self._session_lock:
                self._session_running = False

    def _say(self, line):
        say = self.say
        if line and say is not None:
            try:
                say(line)
            except Exception as e:
                applog.log("shell", f"a line for the bar: {e!r}")

    def _hold_while_setup(self):
        """The automatic Generate and the journey keeper hold while the setup wizard is up (`setup_open`)."""
        held = self.setup_open.is_set
        if hasattr(self.automation, "held"):
            self.automation.held = held
        if self.replan is not None and hasattr(self.replan, "held"):
            self.replan.held = held

    def setup_ended(self):
        """(A worker.) The setup wizard closed: what it held is asked again, as at a focus — first the start's look it
        held (B-10), once, on the settings the wizard wrote: Connect switched off there, no look, and the start's
        known-words sync it was waiting for goes now."""
        with self._quit_lock:                         # review F-4: never between `start`'s look and its hold
            self.setup_open.clear()
            held, self._look_after_setup = self._look_after_setup, False
        if held and self.started and not self.closing.is_set():
            session = self._session_settings()
            if session is not None:
                self._opening_look(session)
            elif self._sync_owed:
                self._sync_owed = False
                self.automation.session_began(True)
        self.activated()

    def activated(self):
        """(A worker.) The window came back into focus: the journey, the sync, 順, a waiting Generate, the indexer —
        nothing once the quit began (E20: the window may still be up while an Anki write ends)."""
        if self.started and not self.closing.is_set():
            self.automation.activated()
            self._focus_look()                        # Q4-4: a session's start seen at a focus too (never opens Anki)
            self.chores.activated()
            if self.replan is not None:
                self.replan.activated()               # the catch-up and the start's journey look (an outside placement)
                refresh = getattr(self.status, "refresh_soon", None)
                if refresh is not None:
                    refresh("journey")                # the dot, which that look may have found owed

    def ask_language(self, language):
        """(The window's thread, before it hands `language_changed` to a worker.) W3.2 P0 (AD0-4 / IK0-7): the language
        asked for last — two quick switches run on two workers in either order, and each follows the last one asked,
        never its own (ja → zh → ja ends on ja)."""
        self._asked = language or "ja"

    def language_changed(self, language):
        """(A worker.) Another language is open (D31: nothing assumes one) — the language the window asked for last
        (`ask_language`), else `language`. A step that fails is logged and the next runs: the library always follows
        (W3.2 P0, AD0-12). -> `_switch_library`'s answer."""
        self.language = self._asked or language or "ja"
        steps = [("the Generate failure", self._forget_failure)]
        if self.started and not self.closing.is_set():
            steps += [("automation", lambda: self.automation.language_changed(self.language)),
                      ("chores", lambda: self.chores.language_changed(self.language))]
        if self.replan is not None and not self.closing.is_set():
            steps.append(("the re-order host", self._replan_language))
        for name, step in steps:
            try:
                step()
            except Exception as e:
                applog.log("shell", f"{name} at the language switch: {e!r}")
        return self._switch_library(self.language)        # W3.2 P0: the window's library follows (the replan first)

    def _forget_failure(self):
        forget = getattr(self.controller, "forget_failure", None)
        if forget is not None:
            forget()                                      # the last language's Generate failure leaves the bar

    def _replan_language(self):
        self.replan.language_changed(self.language)       # the old keeper closed, the old host stopped, new ones
        self._provide_lines(self.language)
        refresh = getattr(self.status, "refresh_soon", None)
        if refresh is not None:
            # the new language's dot and line at once; and Connect's (P4.1 WF, review B1: the language's feed is kept
            # across switches, so one whose last look found Connect off ticks again only once it is asked by name)
            refresh("journey", "replan", "connect")

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

    def open_journey(self, file=None):
        """(A worker.) *Your journey ↗*: the report (`open_report`), drawn again first when only a setting it shows
        changed (`draw_journey`); `file` (the report's name for an episode's file): opened on it — or, when the journey
        doesn't list it yet (added since the last Generate), where it opens by itself, -> `JOURNEY_LACKS` (JO-1: the
        window says so); drawn before a Journey setting changed while a Generate is due, -> `JOURNEY_OLD_LOOK` (the
        window says its new look comes with that Generate). -> False with none."""
        from app import static_html_generator as generator
        later = self.draw_journey()
        if self.closing.is_set():
            return None                                  # the window is going: no browser opened behind it
        held = file is None or generator.report_holds(file)
        opened = generator.open_report(app_mode=bool(self.settings.get().get("open_app_mode")),
                                       file=file if held else None)
        if opened and not held:
            return JOURNEY_LACKS
        return JOURNEY_OLD_LOOK if opened and later else opened

    def draw_journey(self, wait=JOURNEY_DRAW_WAIT):
        """(A worker.) a6 #5: the journey drawn again before it opens when the report isn't current but its analysis
        is — a setting only the report reads changed (the theme, a Journey switch). A Generate already in flight (the
        keeper's re-render, the user's) is waited for first; then, still stale, the user's own Generate, which
        re-renders and re-analyses nothing (seconds) — asked once — until no Generate runs or waits. Never longer than
        `wait`, and never past the quit. A journey whose analysis is stale too is opened as it is: a full Generate is
        the user's to ask (the Generate button's mark says so) -> True then (its new look waits for that Generate); with
        the duties not made yet (the first moments) it opens as it is too, -> None."""
        from app.services import generate as generate_module
        busy = (generate_module.QUEUED, generate_module.RUNNING, generate_module.CANCELLING)
        deadline = time.monotonic() + wait
        asked = False
        while not self.closing.is_set() and self.controller is not None and time.monotonic() < deadline:
            if self.controller.state().state in busy:
                self.closing.wait(0.1)                   # a run in flight or waiting: its end, then look again
                continue
            try:
                from app import analyzer, run_args
                args = run_args.analyzer_args(settings_service.thaw(self.settings.get()), self.language)
                if analyzer.report_is_current(args, self.language):
                    return
                if analyzer.journey_is_current(args, self.language) is not True:
                    return True
            except Exception as e:
                applog.log("shell", f"journey before opening: {e}")
                return
            if asked or self.generate() is None:         # asked once: a run that ended and left it stale opens as is
                return
            asked = True

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
            if not self._held:                    # (row 35's sheet held them already)
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

    def hold_starting(self):
        """(Row 35: the close's sheet asks; every answer quits.) Once: every gated job held from now on (the registry's
        gate, the quit's own reason) and the chores' timers taken back — nothing is spawned that *Stop and quit* would
        miss. Not the quit's start (`_stop_starting`: E20's wait still counts from the answer). Returns at once."""
        with self._quit_lock:
            if self._held or self._quit_began is not None:
                return
            self._held = True
        self.registry.gate(self._closing_gate)
        if self.chores is not None:
            self.chores.halt()

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

    # --- W3.2 P0: the library main() opens, and a language switch ----------------------------------------------- #
    def load_numbers(self):
        """(After the first frame: main connects it.) The numbers' plan read and their engine built, on their own worker
        (*% known*, *N new*): never inside the first frame."""
        load = getattr(getattr(self.writer, "numbers", None), "load", None)
        if load is not None and not self.closing.is_set():
            load()

    def _switch_library(self, language):
        """(A worker: `language_changed`.) The old language's library let go — its moves still queued written first
        (`finish_moves`: up to `QUIT_FINISH_WAIT`; what is left stays in its own journal for its next open), its
        writer's thread waited for (AD0-1: a write still in hand when that wait ran out ends within the store's lock
        wait, so a switch straight back never puts a second writer on the same journal), its numbers closed, its reader
        stopped — then `language`'s opened and its numbers loaded; the window starts the reader and the writer
        (`ShellWindow._library_switched`, from this answer: never a read of `library` / `writer` on its thread while
        another switch runs). `language`: the one asked for last (`ask_language`), else the one given. Nothing without
        `library_for`, or once the quit began (the quit waits for a switch under way: never a library opened behind
        it). -> (reader, writer) as this switch leaves them (the language open already: the same; (None, None) when
        the new one couldn't be opened), or None."""
        if self.library_for is None:
            return None
        with self._library_lock:
            language = self._asked or language
            if self.closing.is_set():
                return None
            if getattr(self.library, "language", None) == language:
                return self.library, self.writer
            writer = self.writer
            if writer is not None:
                self.finish_moves(time.monotonic() + QUIT_FINISH_WAIT)
                self._join_writer(writer)
            if self.library is not None:
                try:
                    self.library.stop()
                except Exception as e:
                    applog.log("shell", f"library reader at the language switch: {e}")
            self.library, self.writer = None, None
            if self.closing.is_set():
                return None
            try:
                reader, writer = self.library_for(language)
            except Exception as e:                    # never a crash: the window keeps its last view, said in the log
                applog.log("shell", f"the {language} library couldn't be opened: {e!r}")
                return None, None
            if self._replan_wired:
                reader.subscribe_moves(self._store_moved)
            self._wire_writer(writer)
            self.library, self.writer = reader, writer
            self.load_numbers()
            return reader, writer

    @staticmethod
    def _join_writer(writer):
        """The writer's thread, ended: `finish` joins it only until its deadline, and a write already in hand waits up
        to the store's `LOCK_TIMEOUT` for the lock before it lands or is journalled (AD0-1)."""
        thread = getattr(writer, "_thread", None)
        if thread is None:
            return
        from app.library_store import LOCK_TIMEOUT
        thread.join(LOCK_TIMEOUT + WRITER_JOIN_MARGIN)
        if thread.is_alive():
            applog.log("shell", f"the {writer.language} writer still ran {LOCK_TIMEOUT + WRITER_JOIN_MARGIN} s after "
                                f"the language switch's wait")
    # --- end W3.2 P0 ------------------------------------------------------------------------------------------------ #

    def finish_moves(self, deadline):
        """(A worker, or the last call.) W3.1a, 04 §4.5: the window's moves still queued are written before the window
        goes, until `deadline` (monotonic; *Saving your moves…* meanwhile) — what is left stays in the writer's journal for
        the next start — then the numbers' worker closed. -> True when every move landed."""
        writer = self.writer
        if writer is None:
            return True
        try:
            done = writer.finish(deadline)
        except Exception as e:
            applog.log("shell", f"the window's moves at quit: {e}")
            done = False
        close = getattr(getattr(writer, "numbers", None), "close", None)
        if close is not None:
            try:
                close()
            except Exception as e:
                applog.log("shell", f"the numbers at quit: {e}")
        return done

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
        with self._library_lock:                          # W3.2 P0: after a language switch under way
            if self.writer is not None:                   # W3.1a: the moves still queued, then the numbers; the reader after
                self.finish_moves(time.monotonic() + self._finish_wait_left())
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


def _junban_here():
    """Whether the Junban module is installed (a file look: a worker's call) — 順's circle has settings only then."""
    from app.qt import settings_catalog
    return "modules.junban" in settings_catalog.installed_modules()


def journey_file(episode):
    """The journey's name for an episode's file (`path_utils.report_name`, as the report names it), or None (no
    episode, or one with no file)."""
    return path_utils.report_name(getattr(episode, "rel_path", None)) or None


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
        for pos, colour in theme.IRIS.get(style.current()[0], theme.IRIS[theme.DEFAULT_THEME]):
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
        self.drop_lit = False                             # G3.2: a drag's hand over it (a drag swallows hover)

    def set_drop_lit(self, on):
        """Lit as on a hover while a drag's drop would land on it (`DragController._follow`; `underMouse` never reads
        a running drag's hand)."""
        if on != self.drop_lit:
            self.drop_lit = on
            self.update()

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
        px, weight = theme.font("needs-stone" if self.badge else "tab-count", style.current()[1])   # W3.2 Q5
        font.setPointSizeF(px * style.PT_PER_PX)
        font.setWeight(weight)
        return font

    def _count_w(self):
        if not self.count:
            return 0
        _t, _side, _b, f = self._pads()
        if self.badge:                                    # --- W3.2 Q5: Needs you's cracked amber stone
            from app.qt import needs as needs_ui
            return needs_ui.stone_size(f)
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
        lit = self.isChecked() or self.underMouse() or self.hasFocus() or self.drop_lit
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
            if self.badge:                                # --- W3.2 Q5: the cracked amber stone, its number on it
                from app.qt import needs as needs_ui
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                needs_ui.paint_stone(p, x, line, self._count_w(), self.count, font)
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
        overlays = getattr(self, "overlays", None)      # the router may go first (its dict cleared by the collector)
        if overlays is not None:
            self.overlays = [o for o in overlays if o is not overlay]

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
        self.update_cross = None                                   # round 8 row 54: the chip's ✕
        self.journey_button = None                                 # the header's *Journey ↗*, beside the level ▾
        self.sheet = self.cards = self.journey_dot = self.pop = None
        self.level_text = self.level_tip = strings.LEVEL_WAITING   # W3.1a: the ▾'s words and the level's tip
        self.previews_busy = self.previews_again = False           # W3.1b: the pop's numbers, one read at a time,
        self.previews_dirty = True                                 # and only when what they read moved
        self.level_asked = 0                                       # the newest level read (older answers dropped)
        self.update_state = self.generate_state = self.auto_state = None
        self.notice = self.junban_said = self.updated_said = None      # the lines toasted once (IK-23)
        self.update_unseen = ()             # the update's failures not looked at yet (the bar's line: HR-23)
        self.update_applies = False         # W31A-1: the update chip has something to say (it then holds the slot)
        self.paints = {}                    # control -> how many times it was repainted (S19)


# --- the window ------------------------------------------------------------------------------------------------------ #
def needs_asked(state, before):
    """Does the automation's new `state` ask *Needs you* again? A sync that just ended (laptop round 7 #43: Known from
    Anki's question may have come or gone), or the shows behind the backlog worked out anew (Michi-C: `State.shows`)."""
    if getattr(state, "sync", None) == "synced" and getattr(before, "sync", None) != "synced":
        return True
    return getattr(state, "shows", None) != getattr(before, "shows", None)


class ShellWindow(QMainWindow):
    first_frame = pyqtSignal()
    closing = pyqtSignal()                                # before the window hides (single instance stops listening)
    sources_seen = pyqtSignal(object)                     # SRC W1b: a look's summary (Settings' *Library folders*)
    library_switched = pyqtSignal()                       # W-1: another language's library shown (its own bridge)

    def __init__(self, services, state_file=None, parent=None):
        super().__init__(parent)
        self.services = services
        self.state_file = state_file or state_path()
        settings = services.settings.get()
        self.language = settings.get("target_language") or "ja"
        self._first_painted = False
        from app.qt import stones                             # W3.1a S1: no stones' sheet built before the first frame
        self._stones_hold = object()
        stones.hold(self._stones_hold)
        self.destroyed.connect(lambda _obj=None, token=self._stones_hold: stones.release(token))
        qcovers.hold(self._stones_hold)                       # --- W3.2 Q6: no cover decoded before the first frame
        self.destroyed.connect(lambda _obj=None, token=self._stones_hold: qcovers.release(token))
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
        root.addWidget(self._build_header())                  # header and tabs: one frame band, no line between
        root.addWidget(self._build_tabs())
        self.edge_top = frame.EdgeStrip("top", central)       # W3.1a: the band's baked edge onto the content
        root.addWidget(self.edge_top)
        self.pages = QStackedWidget(central)
        self.pages.setObjectName("pages")
        self.page_widgets = {}
        self.standing = standing_service.Hidden()             # round 8 row 54: the run lines ✕ hid (this session)
        self.offline_hidden = set()                           # ... the offline line's (the seen file's, and ✕ since)
        self._failure_hidden = None                           # ... the bar's failure ✕ took off (until the service's
        for name in TABS:                                     # snapshot says so too)
            page = self._page(name)
            if isinstance(page, screens.Page):                # the read-only line's ✕ hides it on every page
                page.hidden = self.standing
                page.state_dismissed.connect(self._state_dismissed)
            self.page_widgets[name] = page
            self.pages.addWidget(page)
        root.addWidget(self.pages, 1)
        self.dock = self._build_bottom_band()                 # W3.1a: each page's bottom edge; Current's Goal dock
        # --- SRC W1b: the offline line, quiet, under the library: a source folder a look couldn't reach (SRC-3)
        # round 8 row 54: its ✕ and *Keep waiting* hide it until the folder is back and goes again (`_keep_waiting`)
        self.offline_line = standing_qt.StandingLine("sourcesline", central, margins=(16, 2, 16, 2))
        self.offline_line.label.setToolTip(strings.SOURCES_OFFLINE_TIP)
        # (a folder that is GONE, not away, is *Needs you*'s card instead — T6, `_show_offline` — never this line)
        self.offline_line.add_answer("keep", strings.SOURCES_KEEP_WAITING, strings.SOURCES_KEEP_WAITING_TIP)
        self.offline_line.dismissed.connect(self._keep_waiting)
        self.offline_line.answered.connect(self._offline_answered)
        root.addWidget(self.offline_line)
        # --- end SRC W1b
        root.addWidget(self._build_footer())
        self.setCentralWidget(central)
        self._apply_sizes()

        # the services, through the bridge
        self.bridge = bridge.Bridge(services.settings, services.registry, services.status, parent=self)
        self.bridge.status_changed.connect(self.show_status)
        self._jobs = ()                                   # the registry's newest snapshot (E20: what the close waits for)
        self._quit = None                                 # None · "waiting" (E20: an Anki write ends first) · "ready"
        self.restart_asked = False                        # *Restart now* (text size): main starts the program again
        self._quit_line = strings.QUIT_FINISHING          # the bar's one line while it waits
        self._quit_timer = None
        self._detached_card = None                        # row 35: the close's *Still finishing* sheet, while open
        self._detached_answered = False                   # ... answered (Quit or Stop and quit): asked once a close
        self.bridge.jobs_changed.connect(self._jobs_changed)
        self.bridge.jobs_changed.connect(self.phase.set_jobs)
        self.phase.set_jobs(services.registry.snapshot())
        self._library_needs = 0
        self._status_snap = None
        self._replan_waited = True                        # E20: the re-order host idle (or not waited for) at the close
        self._d29 = True                                  # D29 for the journey dot's tooltip, read on a worker
        self._d29_asked = 0                               # ... and the newest read asked (an older answer is dropped)
        self._refresh_press = None                        # round 8 row 45: Refresh's press, until a look's summary
        self.duties = None                                # W3.5: the duties' controls, once the duties are attached
        leave_out = getattr(services.status, "leave_out", None)     # (a test's stand-in service may have none)
        if leave_out is not None:
            leave_out(phase_service.placed)
        self.show_status(services.status.snapshot())
        self._epoch_shown = None                          # LM11b AD-5: the store's epoch of the view shown last
        # --- W2.2: the library (the reader's views, queued to this thread) ---------------------------------------- #
        if services.library is not None:
            self.library_bridge = bridge.Bridge(library=services.library, parent=self)
            self.library_bridge.library_changed.connect(self.show_library)
            for page in self.page_widgets.values():
                if hasattr(page, "message"):
                    page.message.connect(self.say)                     # a file ▶ couldn't open: said in the bar
                if hasattr(page, "not_found"):
                    page.not_found.connect(self._play_not_found)       # ... and its ▶ looked at again (row 55 A-7)
            current = self.page_widgets.get("current")
            if hasattr(current, "on_journey"):                         # W3.1a S5: Up Next's *N new words ↗*
                current.on_journey = lambda row, episode: self._open_journey(       # (its row's ↗ turns, IK-2)
                    asked=True, at=qpress.row_mark(current.list, [episode.id], "journey") if episode else None,
                    episode=view_rows.journey_episode(row) if episode else None)
            # --- P4.1 L2 (row 4.1.14): a click on the top-20 line opens its setting
            if hasattr(current, "on_line"):
                current.on_line = lambda kind: self.open_setting("mine_line") if kind == "top" else None
            # --- end P4.1 L2
            self.library_bridge.library_changed.connect(self.search.library_moved)     # --- W3.2 Q3
            if not getattr(services, "library_after_frame", False):
                services.library.start()                       # (W3.2 P0: main's starts after the first frame)
        self._reader_shown = services.library                 # W3.2 P0: the reader the pages follow (a switch: another)
        self._language_asked = self.language                   # W3.2 P0: the language asked for last (IK0-7)
        self._asks = 0                                         # ... how many switches were asked (the last one ends one)
        # --- end W2.2 ------------------------------------------------------------------------------------------------ #
        self.closing.connect(self.search.close_searcher)                             # --- W3.2 Q3
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
        self.phase.tooltips = self.tooltips
        for page in self.page_widgets.values():           # W2.2: painted parts' tooltips go through the bubble
            if hasattr(page, "list"):
                page.list.tooltips = self.tooltips
        # --- W3.1a: the drag, the moves, Done and Undo (`drag.py`), given a writer beside the library ---------------- #
        self.moves = None
        if services.library is not None and services.writer is not None:
            from app.qt import drag
            self.moves = drag.DragController(self, services.writer, services.library)
            if not getattr(services, "library_after_frame", False):
                self.moves.start()                             # (W3.2 P0: main's after the first frame, on a worker)
        # --- W3.2 Q5: Needs you's entries and their actions (`app/qt/needs.py`), given a library -------------------- #
        self.needs_you = None
        needs_page = self.page_widgets.get("needs")
        if services.library is not None and hasattr(needs_page, "cards"):
            from app.qt import needs as needs_ui
            self.needs_you = needs_ui.NeedsYou(self, needs_page, self.language)
            self.needs_you.changed.connect(self._paint_needs)
            # a7: a circle's *Needs you* place counts only while its card is on the page; looked at again as
            # the page's cards move (`changed`: a gather landed, a card put away)
            ny = self.needs_you
            self.phase.lands = lambda go: go.place != "needs" or ny.first_of(go.at) is not None
            self.needs_you.changed.connect(self.phase.refresh)
            self.needs_you.changed.connect(self._connect_fault)
            needs_page.controller = self.needs_you
            self.needs_you.failures_in(services.status.snapshot().needs_you)
            if needs_page.view_model is not None:
                self.needs_you.view_in(needs_page.view_model)
        # --- end W3.2 Q5
        # --- W3.2 Q2: Goal's sheet, opened (and closed) by a click on the dock's bar; Esc / Back close it ----------- #
        self.goal_sheet = None
        if self.dock is not None:
            from app.qt import goal_sheet
            self.goal_sheet = goal_sheet.GoalSheet(self, self.page_widgets["current"], self.dock)
            self.dock.sheet_requested.connect(self.goal_sheet.toggle)
            self.register_overlay(self.goal_sheet)
        # --- end W3.2 Q2
        # --- W3.2 Q4: Finished's actions (`finished.py`): Put back, ⋯, *What if I added it back?*, the importer and
        # Explorer's files on the Finished tab — given a writer, as the moves are
        self.finished = None
        if self.moves is not None and hasattr(self.page_widgets.get("finished"), "on_put_back"):
            from app.qt import finished
            self.finished = finished.FinishedActions(self)
        # --- end W3.2 Q4
        # --- W3.2 Q8: the rest of Current's ⋯ (`item_menu.py`), the ✂ seam and drop-to-join
        self.items = None
        if self.moves is not None:
            from app.qt import item_menu
            self.items = item_menu.ItemActions(self)
        # --- end W3.2 Q8
        # --- SRC W1b: the source folders Surasura reads where they are, looked at on focus, Refresh (its key) and the tick
        # (`sources.due`) on the looks' own worker, a local one watched (`app/services/source_looks.py`); made after
        # the first frame (`_start_looks`: the store's module stays off the first paint)
        self.looks = None
        self.sources = ()                                 # the last look's sources ({id, path, on, items, reachable})
        self.sources_listed = False                       # ... once a listing of this library landed (none is news)
        self._arrivals_view = None
        self._sources_relay = bridge.Relay(self)
        self._sources_relay.said.connect(self._sources_looked)
        self._ended_relay = bridge.Relay(self)            # round 8 row 45: a look ended (told or not): Refresh's press
        self._ended_relay.said.connect(self._look_ended)
        self._progress_relay = bridge.Relay(self)
        self._progress_relay.said.connect(self._sources_progress)
        self.look_key = QShortcut(QKeySequence(QKeySequence.StandardKey.Refresh), self)
        self.look_key.setContext(Qt.ShortcutContext.WindowShortcut)
        self.look_key.activated.connect(self.refresh_sources)
        self._look_tick = QTimer(self)
        self._look_tick.timeout.connect(self.look_at_sources)
        self._look_tick.start(LOOK_TICK_MS)
        # --- end SRC W1b
        # --- W3.2 Q1: the tray under the inset, and the arrivals' numbers (the warm worker, asked once per file). The
        # worker's client is the services' `arrivals` (a test's), else made for a real library (P0's `library_for`)
        self.arrivals_tray = self.arrival_numbers = None
        if services.library is not None:
            from app.qt import arrivals as arrivals_view
            self.arrivals_tray = arrivals_view.ArrivalsTray(central, self.arrivals_inset, self)
            self.register_overlay(self.arrivals_tray)
            if getattr(services, "arrivals", None) is not None or getattr(services, "library_for", None) is not None:
                # S2: asked again when the plan file moves (a Generate), never on a drop (`Numbers.version` does);
                # N3 / IK-L2-2: the client and the language read at each ask — the window's one warm worker. The
                # numbers go to the reader open as they come (W3.2 H: never the first reader's bound method — a
                # switch let that one go, and the new language's arrivals had no numbers)
                self.arrival_numbers = arrivals_view.ArrivalNumbers(
                    self.arrivals_worker, lambda: self.language, on_change=lambda estimates: _set_estimates(
                        services.library, estimates),
                    plan_token=lambda: _plan_key(getattr(services.library, "numbers", None)))
        # --- end W3.2 Q1
        # --- W3.2 Q6: the covers' library — its data folder (the opener's), its writer (Change cover…, the disk scan)
        if services.library is not None:
            qcovers.use_library(self.language, getattr(getattr(services.library, "opener", None), "data_dir", None),
                                services.writer, self, self.moves)
            qcovers.follow(services.library, self.language, services.writer)     # Hon a7: what arrives from now on
        # --- end W3.2 Q6
        # --- W3.2 L3: online covers — Q7's fetcher made with the library (`cover_fetcher`), asked for what shows
        self._fetcher = None
        self.cover_fetcher()
        # --- end W3.2 L3
        # --- P4.1 L2: Connect's actions — the stones' Mine now / Mine this / Link…, Finished's Mine and Mine
        # it too, the arrivals' Mine them too (`mine_actions.py`), given a writer
        self.mine = None
        if self.moves is not None:
            from app.qt import mine_actions
            self.mine = mine_actions.MineActions(self)
        # --- end P4.1 L2

        self._restore_state(read_state(self.state_file))

        # --- W3.5: the dashboard's duties: their controls arrive with them (given: now; else `start_duties`) ------- #
        self._duties_asked = False
        self.bridge.quit_asked.connect(self._quit_for_update)
        services.quit_hook = self.bridge.ask_quit
        self._session_lines = bridge.Relay(self)          # Q4-16: the session's look's lines (*Opening Anki…*), the bar
        self._session_lines.said.connect(self._session_said)
        services.say = self._session_lines.call
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
        # --- W3.2 Q3: the search cut after the name (shown with a library); + Add at the right, before ? (the level ▾
        # goes before it: `_attach_duties`)
        from app.qt import add_menu, search as search_ui
        self.search = search_ui.SearchCut(self, header)
        self.search.setVisible(self.services.library is not None)
        row.addWidget(self.search)
        # --- end W3.2 Q3
        row.addStretch(1)                                  # the header's controls arrive with their features (G-2):
        # --- W3.2 Q1: New arrivals, an inset in the band before the level ▾ (with a library; absent until something
        # arrives)
        self.arrivals_inset = None
        if self.services.library is not None:
            from app.qt import arrivals as arrivals_view
            self.arrivals_inset = arrivals_view.ArrivalsInset(header)
            self.arrivals_inset.clicked.connect(lambda _checked=False: self.open_arrivals())
            row.addWidget(self.arrivals_inset)
        # --- end W3.2 Q1
        # --- W3.2 Q3
        self.adder = add_menu.Adder(self)
        self.add_stone = add_menu.AddStone(self.adder, header)
        self.add_stone.setVisible(bool(self.adder.entries()))
        row.addWidget(self.add_stone)
        # --- end W3.2 Q3
        from app.qt import report as report_ui                 # Report a problem: the bug, the header's rightmost control
        self.report_button = report_ui.BugButton(self, header)
        row.addWidget(self.report_button)
        self.progress = frame.Progress(header)             # W3.1a: the jobs' hairline along its foot (no pulsing dot)
        self._busy, self._share = False, None              # ... the bar's lines running, Generate's share
        self.presses = press_service.Presses()             # round 8 row 45: a live press runs the hairline too,
        self._holds = {}                                   # ... and a menu's press holds the bar's slot (`say`)
        self.presses.subscribe(self._presses_changed)
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
        self.vein = frame.Vein(bar)                        # W3.1a: the iris vein under the current tab, on springs
        self.vein.track([self.tab_buttons[n] for n in TABS])
        self.vein.go(self.tab_buttons["current"], animate=False)
        return bar

    # --- W2.2: the pages a library fills ----------------------------------------------------------------------- #
    def _page(self, name):
        if name == "settings":
            return self._settings_holder()
        if self.services.library is None or name not in screens.PAGES:
            return self._waiting_page(name)
        return screens.make_page(name, language=self.language)

    # --- W3.3 P7: the Settings page, mounted the first time its tab shows (never on the first frame's path) ------- #
    def _settings_holder(self):
        page = QWidget()
        page.setObjectName("page-settings")
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.settings_page = None
        return page

    def mount_settings(self):
        """The Settings page in its tab (once): the page, then the rows other packages fill — Connect's three, the
        placing rules, the store's two lines and *Set up again* (`settings_store`). -> the page."""
        if self.settings_page is not None:
            return self.settings_page
        from app.qt import settings_connect, settings_page, settings_rules, settings_sources, settings_store
        from app.qt import settings_io
        holder = self.page_widgets["settings"]
        language = self.services.settings.get().get("target_language") or self.language
        page = settings_page.SettingsPage(self, language, parent=holder)
        holder.layout().insertWidget(0, page, 1)          # above the bottom edge every page carries
        self.settings_page = page
        for attach in (settings_connect.attach, settings_rules.attach, settings_store.attach,
                       settings_sources.attach,                        # --- SRC W1b: *Library folders*
                       settings_io.attach):                            # --- a6: *Your settings*
            try:
                attach(page)
            except Exception as e:                        # one package's rows never keep the page from opening
                applog.log("shell", f"settings rows not attached ({attach.__module__}): {e!r}")
        return page

    def open_setting(self, target):
        """The Settings tab, with `target` brought into view (`SettingsPage.reveal`: a row id or key, a section id,
        `known`, `mine_line`, `soon_line`). -> what `reveal` answered."""
        page = self.mount_settings()
        self.show_tab("settings")
        return page.reveal(target)
    # --- end W3.3 P7 --------------------------------------------------------------------------------------------- #

    def show_library(self, view):
        """The reader's newest view: the pages, the subline's counts, the tabs' counts. W3.1a: the drag's expectation
        asks first (`drag.DragController.view_in`) — held while a drag runs (E6), shown in the drop's order while the
        store catches up (no flash back)."""
        if getattr(view, "language", self.language) != self.language:
            return                                  # W3.2 P0: a view of the language left, queued before the switch
        moves = getattr(self, "moves", None)
        if moves is not None:
            view = moves.view_in(view)
            if view is None:
                return
        epoch = getattr(view, "epoch", None)
        if epoch is not None:                       # LM11b AD-5: the library rebuilt or reset in this language
            if self._epoch_shown is not None and epoch != self._epoch_shown:
                self._forget_picks()
            self._epoch_shown = epoch
        if screens.state_key(view) is None:         # round 8 (A-9): the read-only line's trouble ended — its ✕
            self.standing.only(standing_service.READ_ONLY, ())     # answers go, once, here (the pages only read them)
        moved = False
        for name in screens.PAGES:
            page = self.page_widgets.get(name)
            if hasattr(page, "set_view"):
                moved = page.set_view(view) not in ("same", "later") or page.list.looks_changed or moved   # a4
        self.subline.setText(view.subline)
        fin = self.tab_buttons["finished"]
        label = strings.TABS["finished"][0]
        if fin.count != view.counts.finished:      # repainted only when the count changed (S19)
            fin.set_name(label, view.counts.finished)
        if self._library_needs != len(view.needs):
            self._library_needs = len(view.needs)
            self.show_status(self.services.status.snapshot())
        if self.dock is not None:                   # W3.1a: Goal's bar (and the wells' covers) from the same view
            self._show_dock(view)
        if self.cover_fetcher() is not None:        # --- W3.2 L3: the arrivals' covers asked online as they arrive
            qcovers.ask([getattr(a, "cover", None) for a in getattr(view, "arrivals", ()) or ()])
        self._show_arrivals(view)                   # W3.2 Q1: the inset, the tray, the numbers asked
        sheet = getattr(self, "goal_sheet", None)   # --- W3.2 Q2: the sheet's tiles; a piece it moved, scrolled to
        if sheet is not None:
            if view.goal is not None:
                sheet.set_goal(view.goal)
            sheet.view_shown(view)                  # --- end W3.2 Q2
        if moved:                                   # a view that changed no list paints nothing ahead
            self._warm_hidden_pages()

    def _show_dock(self, view):
        """The Goal dock takes the reader's `view.goal`, repainted only when it changed; shown while there is a Goal and
        anything to show (Current only: it lives in the Current page)."""
        goal = view.goal
        if goal is not None:
            self.dock.set_goal(goal)
        self.dock.set_view(view)
        shown = goal is not None and (bool(view.rows) or bool(goal.files) or not view.loading)
        if self.dock.isHidden() == shown:
            self.dock.setVisible(shown)

    # --- W3.2 Q1: New arrivals (app/qt/arrivals.py) -------------------------------------------------------------- #
    def arrivals_worker(self):
        """IK-L2-2: the window's one warm arrivals worker (E2.2 D10), for its language as it stands — New arrivals'
        numbers and Finished's *What if* share it (`services.arrivals_worker`; a test's `services.arrivals` first).
        Made on first use; its process starts on its first ask."""
        services = self.services
        client = getattr(services, "arrivals", None)
        if client is not None:
            return client
        worker = getattr(services, "arrivals_worker", None)
        if worker is None or getattr(worker, "language", self.language) != self.language:
            if worker is not None and hasattr(worker, "stop"):
                worker.stop()                       # another language's: one warm worker at a time
            from app.services.arrivals import ArrivalsWorker
            worker = services.arrivals_worker = ArrivalsWorker(services.registry, self.language)
        return worker

    def _show_arrivals(self, view):
        """The view's arrivals: the inset (absent with none, unless files were kept out), the tray's rows (only what
        changed), each new file's estimate asked (on a worker); the tray closes once nothing is left in it (A2 #32)."""
        arrivals = getattr(view, "arrivals", ()) or ()
        if self.arrivals_inset is None:
            return
        self.arrivals_inset.set_arrivals(arrivals, (getattr(view, "badges", None) or {}).get("arrivals", 0))
        tray = getattr(self, "arrivals_tray", None)
        if tray is None:
            return
        self._arrivals_view = view                        # SRC W1b / A4B-8: each arrival names its folder — the
        tray.set_groups(getattr(view, "arrival_groups", ()) or ())     # reader's thread named it (`follow_folders`)
        sorting = self.__dict__.get("_sort_screen")       # --- Mado-O: the sort screen over the window follows them
        if sorting is not None and not sip.isdeleted(sorting):
            sorting.set_groups(getattr(view, "arrival_groups", ()) or ())
        if not arrivals and not tray.kept_out[0] and (tray.isVisible() or motion.opening_of(tray) is not None):
            tray.close()                                  # (alpha 4: its kept-out foot keeps it open)
        if self.arrival_numbers is not None and getattr(view, "language", self.language) == self.language:
            self.arrival_numbers.want(arrivals)

    def _show_kept_out(self):
        """Alpha 4 (Mattias #8, A4K-6): the files the looks kept out because they match files he removed (each source
        row's `kept_out` / `kept_out_ids`, `SourceLooks._notes`) — New arrivals' foot with *Bring back*, and the inset
        shown for it while no arrival waits. Nothing changed: nothing touched (S19)."""
        tray = getattr(self, "arrivals_tray", None)
        if self.arrivals_inset is None or tray is None:
            return
        rows = [r for r in self.sources if r.get("kept_out")]
        n = sum(int(r["kept_out"]) for r in rows)
        tray.kept_said(n, sorted({i for r in rows for i in r.get("kept_out_ids") or ()}), [r["id"] for r in rows])
        if not tray.kept_out[0] and not self.arrivals_inset.count and \
                (tray.isVisible() or motion.opening_of(tray) is not None):
            tray.close()

    def open_arrivals(self):
        """The inset's click (A2 #89: from any tab, Current first, then the tray), again to close it."""
        tray = getattr(self, "arrivals_tray", None)
        if tray is None:
            return
        if tray.isVisible() or motion.opening_of(tray) is not None:
            tray.close()
            return
        if self.current_tab() != "current":
            self.show_tab("current")
        tray.open()
        if self.arrival_numbers is not None:
            self.arrival_numbers.recheck()
    # --- end W3.2 Q1
    # --- W3.2 P0: a language switch: the pages follow that language's library ---------------------------------- #
    def _ask_language(self, language, then):
        """(This thread.) Settings › Language moved: the services follow on a worker (`Services.language_changed`),
        told first which language was asked last (two quick switches: each worker follows the last). From now until the
        last switch asked has answered, the drag refuses with *Switching to …* (AD0-5): no move is painted that the
        language left could no longer write."""
        if language == self._language_asked:
            return
        self._language_asked = language
        self._asks += 1
        asked = self._asks
        # round 8 row 45 (P5): *Switching to …* held in the bar with its arc until the last switch asked has answered
        words = strings.LANGUAGE_SWITCHING.format(name=strings.LANGUAGE_NAMES.get(language, language))
        if qpress.begin(None, "language", busy=words, win=self) is None:
            self.say(words, hold="language")             # a second switch while one goes: the newest named
        s = self.services
        ask = getattr(s, "ask_language", None)
        if ask is not None:
            ask(language)
        if getattr(s, "library_for", None) is not None and self.moves is not None:
            self.moves.switching(strings.SWITCHING.format(name=strings.LANGUAGE_NAMES.get(language, language)))
        bridge.run_in_worker(s.language_changed, language, then=lambda switched: then(switched, asked),
                             failed=lambda info: self._switch_failed(info, asked))

    def _switch_failed(self, info, asked):
        applog.log("shell", f"the language switch: {info[1]}")
        self._library_switched((None, None), asked)

    def _library_switched(self, switched=None, asked=None):
        """(This thread, after `Services.language_changed`.) `switched`: the switch's own answer (reader, writer) —
        never the services' attributes, which a later switch may be changing on its worker (AD0-4). A live reader of
        the language asked for last, not shown yet, is shown: the old reader's bridge let go (a view it queued is
        dropped: `show_library` asks its language), the drag let go and its Undo with it (an Undo of the language left
        can never reach the new language's writer), the list's *saving…* and landing marks cleared (AD0-6), the
        language's fonts (AD0-11), the new reader and writer started — a drag controller of their own whenever there
        is a writer. A reader a later switch stopped already is never started. The last switch asked ends the
        *Switching…* refusal. Nothing once the quit began."""
        if self._quit is not None:
            return
        last = asked is None or asked == self._asks
        if last:
            p = self.presses.find("language")
            if p is not None and p.live():
                qpress.end(p, self, failed=isinstance(switched, tuple) and switched[0] is None)
        reader, writer = switched if isinstance(switched, tuple) else (None, None)
        if reader is not None and reader is not self._reader_shown and not _stopped(reader) and \
                getattr(reader, "language", None) == self._language_asked:
            self._show_switched(reader, writer)
        if last and self.moves is not None:
            if isinstance(switched, tuple) and reader is None:      # the new language's library couldn't be opened
                self.moves.switching(strings.LIBRARY_NOT_OPENED)
                self.say(strings.LIBRARY_NOT_OPENED)
            else:
                self.moves.switching(None)

    def _forget_picks(self):
        """LM11b AD-5: the picks are keyed p<piece id> (an episode's by its item id), and a store numbers its pieces from
        1 — each language's, and one rebuilt or reset (a new epoch): none carried onto another library's rows. A4B-2:
        every list of this window that picks (Current, Finished, Goal's sheet, New arrivals' tray — `rows._PICKERS`)."""
        from PyQt6 import sip
        from app.qt import rows
        self._epoch_shown = None
        for picker in list(rows._PICKERS):
            if not sip.isdeleted(picker) and picker.window() is self:
                picker.clear_picks()

    def _show_switched(self, reader, writer):
        self._reader_shown = reader
        self.language = getattr(reader, "language", None) or self.services.language
        old = getattr(self, "library_bridge", None)
        if old is not None:
            old.stop()
            old.deleteLater()
        moves, self.moves = self.moves, None
        if moves is not None:
            moves.close()                           # a drag running is let go
            self.toasts.close()                     # a move's toast and its Undo: the language left's
            moves.undo_key.setEnabled(False)        # (the window's own Ctrl+Z goes to the new controller's)
            moves.undo_key.deleteLater()
            moves.unwire()                          # a write still in hand past the switch's wait tells no one
            moves.deleteLater()
        lst = getattr(self.page_widgets.get("current"), "list", None)
        if lst is not None and (lst.saving or lst.landing is not None):
            lst.saving, lst.landing = frozenset(), None     # AD0-6: never a mark of the language left on a row
            lst.viewport().update()
        self.moves_saving(False)                    # PS-A4: nor 届's wait (the writer let go never says it ended)
        if getattr(self, "mine", None) is not None:  # round 8 row 45: nor a pressed Mine now (its presses end)
            self.mine.settle_all()
        self._forget_picks()
        self._follow_language_look()
        for page in self.page_widgets.values():     # ▶ opens a file of this language's library
            set_language = getattr(page, "set_language", None)
            if set_language is not None:
                if getattr(page, "language", None) != self.language:
                    set_language(self.language)     # (Settings has followed already, through its own handler)
            elif hasattr(page, "language"):
                page.language = self.language
        self.library_bridge = bridge.Bridge(library=reader, parent=self)
        self.library_bridge.library_changed.connect(self.show_library)
        if writer is not None:
            from app.qt import drag
            self.moves = drag.DragController(self, writer, reader)
            self.moves.start(on_worker=True)        # its first look at the store and its replay off this thread
            if getattr(self, "mine", None) is None:     # P4.1 WF (adversary N7): a window opened with no writer gets
                from app.qt import mine_actions         # Connect's actions with its first; one made already follows
                self.mine = mine_actions.MineActions(self)     # `win.moves` and the language at each call
        self._follow_covers(reader, writer)
        reader.start()
        self._follow_looks(writer)                  # --- SRC W1b: that language's source folders
        self.library_switched.emit()                # W-1: Settings' store rows follow the new bridge (`settings_store`)

    def _follow_covers(self, reader, writer):
        """W3.2 L3: the covers follow the library shown — its data folder, its writer and its drag controller (never the
        language left's: held there, they kept its reader and writer alive past the switch), its own fetcher (the old
        one stopped), its disk scan (once the first frame is out: until then the frame's own scan runs) and the look
        at each title that arrives or changes from now on (Hon a7)."""
        qcovers.stop_scan()
        qcovers.use_library(self.language, getattr(getattr(reader, "opener", None), "data_dir", None), writer, self,
                            self.moves)
        qcovers.follow(reader, self.language, writer)                   # Hon a7: what arrives from now on
        if self._fetcher_for(reader, writer) is None and self._fetcher is not None:
            self._fetcher.stop(timeout=0)           # (no writer: nothing to record with, so no fetcher)
            if qcovers.fetcher() is self._fetcher:
                qcovers.use_fetcher(None)
            self._fetcher = None
        if self._first_painted and writer is not None:
            qcovers.start_scan(getattr(reader, "opener", None), self.language, writer)

    def _follow_language_look(self):
        """AD0-11: the application's font for the language open (the CJK face), the theme and size as they are."""
        theme_name, text_size, language = style.current()
        if language == self.language:
            return
        script = self.services.settings.get().get("zh_script") if self.language == "zh" else None
        try:
            style.apply(QApplication.instance(), theme_name, text_size, self.language, script)
        except Exception as e:
            applog.log("shell", f"the look at the language switch: {e!r}")

    def _language_followed(self, switched, asked=None):
        """`Services.language_changed`'s answer (the duties' path): the library, then the level read again."""
        self._library_switched(switched, asked)
        self._read_level()
        if self.duties is not None:
            self.duties.pop.set_previews(None)             # W3.1b: never the last language's numbers
            self._previews_moved()
    # --- end W3.2 P0 ------------------------------------------------------------------------------------------------ #

    # --- W3.2 L3: online covers ------------------------------------------------------------------------------------ #
    def cover_fetcher(self):
        """The library's online covers (Q7's `covers_online.Fetcher`) for the window's language and writer as they stand:
        made again when either moved (a library or language switch; the old one stopped), None without a library or a
        writer. It reads `covers_download` from the settings in memory before every request: off, nothing leaves."""
        return self._fetcher_for(self.services.library, getattr(self.services, "writer", None))

    def _fetcher_for(self, library, writer):
        if library is None or writer is None:
            return None
        services = self.services
        f = getattr(self, "_fetcher", None)
        if f is not None and f.language == self.language and f.writer is writer:
            return f
        if f is not None:
            f.stop(timeout=0)
        from app.services import covers_online
        make = getattr(services, "cover_fetcher_factory", None) or covers_online.Fetcher
        f = self._fetcher = make(self.language, writer, settings=services.settings.get)
        f.data_dir = getattr(getattr(library, "opener", None), "data_dir", None) or f.data_dir   # disk first
        qcovers.use_fetcher(f, qcovers.resolver(getattr(library, "opener", None)))
        return f

    def ask_shown_covers(self):
        """The titles on screen now (the rows in view of Current, Finished and Needs you — whichever page shows: the
        switch lives on Settings — New arrivals, Goal's hand) asked online — after the switch is turned on, since rows
        already painted aren't painted again by it. -> how many were asked."""
        if self.cover_fetcher() is None:
            return 0
        refs = []
        for name in ("current", "finished", "needs"):
            lst = getattr(self.page_widgets.get(name), "list", None)
            model = lst.model() if lst is not None else None
            entries = getattr(model, "entries", None)
            if entries:
                vp = lst.viewport().rect()
                top, bottom = lst.indexAt(vp.topLeft()).row(), lst.indexAt(vp.bottomLeft()).row()
                top = max(0, top)
                bottom = len(entries) - 1 if bottom < 0 else bottom
                refs += [getattr(entries[i][1], "cover", None) for i in range(top, bottom + 1)]
        view = getattr(self.page_widgets.get("current"), "view_model", None)
        if view is not None:
            refs += [getattr(a, "cover", None) for a in getattr(view, "arrivals", ()) or ()]
            refs += list(getattr(view.goal, "cover_refs", ()) or ()) if view.goal is not None else []
        return qcovers.ask(refs)
    # --- end W3.2 L3

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
        box.setContentsMargins(0, 0, 0, 0)                     # (W3.1a: its bottom edge spans the window)
        box.addStretch(1)
        title = QLabel(strings.TABS[name][0], page)
        title.setObjectName("pagetitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        failed = getattr(self.services, "library_failed", None)    # W3.2 P0: main couldn't open the library
        line = QLabel(failed if failed and name in screens.PAGES else strings.PAGE_WAITING, page)
        line.setObjectName("pagewaiting")
        line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(title)
        box.addWidget(line)
        box.addStretch(1)
        return page

    def _build_bottom_band(self):
        """W3.1a: the bottom band's edge onto the content, baked, at the foot of every page (in its layout: never over
        a list), and — given a library — the Goal dock under Current's (a page of its own: no tab switch lays the
        other pages out again). -> the dock, or None."""
        dock = None
        for name, page in self.page_widgets.items():
            page.layout().addWidget(frame.EdgeStrip("bottom", page))
            if name == "current" and self.services.library is not None:
                dock = frame.GoalDock(page)
                dock.setVisible(False)                         # until the reader's first view says Goal
                page.layout().addWidget(dock)
        return dock

    def _build_footer(self):
        footer = style.styled(QWidget(), "footer")
        self.footer = footer
        row = QHBoxLayout(footer)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)
        # The phase strip (Sonic, 2026-10-23): five circles first at the bottom left, lit by the work each stands for;
        # the status line beside it keeps only what no circle shows (Q5: `StatusService.leave_out`)
        self.phase = phase_strip.PhaseStrip(footer)
        self.phase.follow_presses(self.presses)
        # Alpha 3 (Sonic 2026-10-24, PROVISIONAL): a circle's press opens its settings — 順's only while Junban is here
        self.phase.opened.connect(self._circle_pressed)
        self.phase.set_opens(set(phase_strip.SETTINGS) - {phase_service.JUNBAN})
        bridge.run_in_worker(_junban_here, then=self._junban_found)
        row.addWidget(self.phase)
        # W3.1a: one slot at the left (W31A-1, `_paint_slot`) — the failure line with *Open the logs folder* while it
        # applies, else the update chip while it applies (`_attach_duties` puts it here), else the status line (the
        # pulsing dot gave way to the header's hairline: light never pulses)
        self.bar_line = ElidingLabel(footer)
        self.bar_line.setObjectName("barline")
        self.bar_line.setAccessibleName(strings.BAR_NAME)
        row.addWidget(self.bar_line, 1)
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
        qpress.room(self.logs_button)                      # round 8 row 45: its arc's room kept at rest
        self.logs_button.clicked.connect(lambda _c=False: self.open_logs(control=self.logs_button))
        self.logs_button.setVisible(False)
        row.addWidget(self.logs_button)
        self.bar_failure_cross = standing_qt.Cross(footer)       # round 8 row 54: the failure off the bar (still listed)
        self.bar_failure_cross.clicked.connect(self._failure_dismissed)
        self.bar_failure_cross.setVisible(False)
        row.addWidget(self.bar_failure_cross)
        self.bar_arc = qpress.BarArc(footer)              # round 8 row 45 (IK-2): a menu's press with nothing of its own
        row.addWidget(self.bar_arc)                       # ... on screen turns here, no words (hidden at rest)
        row.addStretch(0)                                # the room left of the marks while the chip holds the slot
        # (W31A-1's quiet marks ⇅ ⇄ went in alpha 3: the re-order's and Connect's lines are 順's and Anki Miner's hovers)
        # W3.1a: the corner — the emerald and *Anki · N waiting* (the AnkiWeb mark's words in its hover), then known
        self.anki_mark = frame.AnkiMark(footer)
        row.addWidget(self.anki_mark)
        self.known = frame.KnownCorner(footer)
        self.known.clicked.connect(self._known_clicked)    # Q30: a click syncs now
        self._known_relay = None
        self._known_press, self._known_answered = None, False     # round 8 row 45: the click's press, until its sync ends
        row.addWidget(self.known)
        self._logs_folder = None
        self.status_paints = {}             # row 7's statuses (the bar's lines, the journey dot) -> repaints (S19)
        return footer

    def _apply_sizes(self):
        """The fixed heights (the stylesheet carries the rest): the footer at the taskbar's height at every text size."""
        size = style.current()[1]
        self.footer.setFixedHeight(round(theme.size("footer", size)))
        self.wordmark.updateGeometry()
        self.search.restyle()                                  # --- W3.2 Q3: the cut and the stone × the text size
        self.add_stone.restyle()
        if self.dock is not None:                              # W3.1a: the dock's bar × the text size
            self.dock.apply_size()
        duties = getattr(self, "duties", None)                 # (none yet on the first call)
        for part in (self.anki_mark, self.known) + ((duties.level,) if duties is not None else ()):
            part.updateGeometry()

    # --- tabs ------------------------------------------------------------------------------------------------- #
    def show_tab(self, name):
        if name not in self.tab_buttons or self.tab_buttons[name].isHidden():
            name = "current"
        button = self.tab_buttons[name]
        if not button.isChecked():
            button.setChecked(True)
        if name == "settings":
            self.mount_settings()                              # W3.3 P7: made the first time it shows
        self.vein.go(button)                                   # W3.1a: the vein travels; the page is there at once
        self.pages.setCurrentWidget(self.page_widgets[name])
        if self.services.library is not None:                 # W2.2: the other tabs' first screens, ahead
            self._warm_hidden_pages()
        if name == "needs":                                    # looked at: its failures stop counting, stay listed
            bridge.run_in_worker(self.services.status.mark_seen)
            if getattr(self, "needs_you", None) is not None:  # W3.2 Q5: and its own entries (the seen file, Connect's)
                self.needs_you.opened()
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
        self._busy = bool(lines)
        self._paint_progress()
        bar = getattr(snap, "bar_lines", None)
        self._status_line = " · ".join(lines if self._quit == "waiting" or bar is None else bar)
        if not (self._saying() or self._holds) or self._quit == "waiting":     # (a line said keeps the slot: `say`)
            self.bar_line.set_full(self._status_line)
        failure = snap.failure or ""
        if failure and self._failure_key(snap) == self._failure_hidden:
            failure = ""                                  # round 8 row 54: ✕ took it off (the service's next snapshot too)
        self.bar_failure.set_full(strings.BAR_FAILURE_PREFIX + failure if failure else "")
        self.bar_failure.setToolTip(strings.BAR_FAILURE_TIP + ("\n\n" + failure if failure else ""))
        logs_before, self._logs_folder = self._logs_folder, snap.logs
        self._status_snap = snap
        self.phase.set_status(snap)
        self._paint_slot()
        if self.anki_mark.set_ankiweb(snap.ankiweb):           # W3.1a: the AnkiWeb mark's words, in the emerald's hover
            self.status_paints[self.anki_mark] = self.status_paints.get(self.anki_mark, 0) + 1
        if self.anki_mark.set_waiting(getattr(snap, "backlog", None)):     # W31A-2: *Anki · N waiting*
            self.status_paints[self.anki_mark] = self.status_paints.get(self.anki_mark, 0) + 1
        if self.duties is not None:
            self._paint_journey_dot()
        needs_page = self.page_widgets.get("needs")
        if hasattr(needs_page, "set_failures"):
            needs_page.set_failures(snap.needs_you)
        if getattr(self, "needs_you", None) is not None:          # W3.2 Q5: Connect's line moved: its entries may have
            self.needs_you.connect_in(snap.connect)
        if self.duties is not None and bool(logs_before) != bool(snap.logs):
            self._show_update(self.duties.update_state, force_cards=True)     # the cards' *Open the logs folder*
        self._paint_needs()

    def _presses_changed(self, press):
        from PyQt6 import sip
        if sip.isdeleted(self.progress):                # (an answer coming in after the window closed paints nothing)
            return
        if self._paint_progress() and press.state == press_service.QUEUED:
            self.progress.repaint()                     # R-2: a press's hairline in the frame of the press, before its
                                                        # work is handed over (not at the next frame)

    def _paint_progress(self):
        """W3.1a: the header's hairline — Generate's share while it has one, else whole and quiet while any job runs.
        -> True when it changed."""
        return self.progress.set(self._busy or self.presses.any_live(), self._share)

    def say(self, text, hold=None):
        """A line for the bar that answers what the user just did (a file ▶ couldn't open, the journey's absence, a
        move the store placed elsewhere): it takes the footer's slot for `DRAG["message-ms"]`, over the update chip and
        the failure line, then the slot is as it was (AD-7: said into a hidden line, it was never seen). `hold`: a live
        press's key (round 8 row 45) — the line keeps the slot until `unsay(hold)`."""
        self.bar_line.set_full(text)
        if hold is not None:
            self._holds[hold] = text
            self._paint_slot()
            return
        self._message_until = time.monotonic() + theme.DRAG["message-ms"] / 1000.0
        if getattr(self, "_message_timer", None) is None:
            self._message_timer = QTimer(self)
            self._message_timer.setSingleShot(True)
            self._message_timer.timeout.connect(self._paint_slot)
        self._message_timer.start(theme.DRAG["message-ms"] + 1)
        self._paint_slot()

    def unsay(self, key):
        """A press's held line let go: the newest line still held, else a line said meanwhile, else the slot as it was."""
        if self._holds.pop(key, None) is None:
            return
        if not self._saying():
            self.bar_line.set_full(self._held_or_status())
        self._paint_slot()

    def _held_or_status(self):
        held = list(self._holds.values())
        return held[-1] if held else getattr(self, "_status_line", "")

    def _saying(self):
        until = getattr(self, "_message_until", None)
        return until is not None and time.monotonic() < until

    def _paint_slot(self):
        """W31A-1: the footer's one slot — the failure line (with *Open the logs folder* when there is a folder) while
        it applies, else the update chip while it applies, else the status line (always the line while the close
        waits: E20's one line); each part shown or hidden only when that changed (S19). A line just said (`say`) holds
        the slot for a few seconds over both."""
        saying = self._saying()
        if not saying and getattr(self, "_message_until", None) is not None:
            self._message_until = None               # the line said has had its time: the status line is back (or a
            self.bar_line.set_full(self._held_or_status())       # live press's held line)
        saying = saying or bool(self._holds)
        failure = bool(self.bar_failure.full()) and self._quit != "waiting" and not saying
        d = self.duties
        update = d is not None and d.update_applies and not failure and self._quit != "waiting" and not saying
        parts = [(self.bar_failure, failure, self.status_paints), (self.logs_button, failure and bool(self._logs_folder),
                 self.status_paints), (self.bar_failure_cross, failure, self.status_paints),
                 (self.bar_line, not failure and not update, self.status_paints)]
        if d is not None:
            parts += [(d.update_mark, update, d.paints), (d.update_cross, update, d.paints)]
        for part, shown, paints in parts:
            if part.isHidden() == shown:
                part.setVisible(shown)
                paints[part] = paints.get(part, 0) + 1

    # --- round 8 row 54: the standing lines' ✕ (app/services/standing.py) -------------------------------------- #
    @staticmethod
    def _failure_key(snap):
        failure = snap.failure if snap is not None else None
        if not failure:
            return None
        return getattr(snap, "failure_key", None) or standing_service.failure_key(None, failure)

    def _failure_dismissed(self):
        """✕ on the bar's failure line: off the bar now, for this session, still listed in Needs you; a newer failure
        shows again (the status service's `dismiss_failure`, on a worker)."""
        key = self._failure_key(self._status_snap)
        if key is None:
            return
        self._failure_hidden = key
        self.bar_failure.set_full("")
        self._paint_slot()
        bridge.run_in_worker(self.services.status.dismiss_failure, key,
                             failed=lambda info: applog.log("shell", f"the failure's ✕: {info[0]!r}"))

    def _update_dismissed(self):
        """✕ on the update chip: hidden for this session (*Later* for this run) until its version or state changes."""
        d = self.duties
        if d is None or d.update_state is None:
            return
        self.standing.hide(d.module.update_mark_key(d.update_state))
        d.update_applies = False
        self._paint_slot()

    def _state_dismissed(self, key):
        """✕ on a page's read-only line: hidden on every page for this session, until its reason changes."""
        if key and self.standing.hide(key):
            for page in self.page_widgets.values():
                if isinstance(page, screens.Page):
                    page.paint_state()

    def _keep_waiting(self):
        """✕ or *Keep waiting* on the offline line: the folders it names hidden now, and kept in the seen file (a
        worker) — hidden across restarts until each is back, then asked again the next time it goes."""
        keys = tuple(k for k, _path, _n in self._offline_shown())
        if not keys:
            return
        self.offline_hidden.update(keys)
        self._show_offline()
        bridge.run_in_worker(standing_service.keep, self.language, keys,
                             failed=lambda info: applog.log("shell", f"the offline line's ✕: {info[0]!r}"))

    def _offline_answered(self, name):
        """The offline line's answers: *Keep waiting* (the ✕ in words) — its folders are only away (an unplugged
        drive, a NAS down). A folder that is GONE has *Needs you*'s card instead (T6: *Find its new folder…* · *Stop
        reading it* · *Keep waiting*; its episodes always stay, SRC-8), so this line offers no "they're gone"."""
        if name == "keep":
            self._keep_waiting()

    def keep_waiting_for(self, paths):
        """T6: *Keep waiting* on a gone folder's *Needs you* card — the offline line's own dismissal (its key in the
        seen file, on a worker): the card and 届's amber go now, until the folder is back; gone again later, it asks
        again."""
        keys = tuple(standing_service.offline_key(p) for p in paths or () if p)
        if not keys:
            return
        self.offline_hidden.update(keys)
        self._show_offline()
        bridge.run_in_worker(standing_service.keep, self.language, keys,
                             failed=lambda info: applog.log("shell", f"a gone folder's Keep waiting: {info[0]!r}"))

    def _circle_pressed(self, circle):
        """A phase circle pressed (alpha 3): its settings — or, while it is amber, where its decision is, that row
        highlighted (a7, Sonic 2026-10-29: "If yellow i would expect it to let me go somewhere to make a decision that
        is highlighted"; `PhaseStrip.go`): *Needs you* at the first card of its kinds (a gone folder, Anki Miner's
        episodes waiting on you, Anki asking for you), or 順's window at its control (a deck to pick, an unfinished
        reorder's Undo). Each shows at once (the press rule's one-frame case: no pending mark)."""
        go = self.phase.go(circle)
        if go is not None and go.place == "needs" and getattr(self, "needs_you", None) is not None:
            self.show_tab("needs")
            self.needs_you.reveal_first(go.at)            # (at its card, not only the page)
            return
        if go is not None and go.place == "junban":
            from app.qt import windows
            opener = next((op for op in windows.OPENERS if op.name == "junban"), None)
            if opener is not None:
                win = windows.launch(self, opener)
                if win is not None and hasattr(win, "highlight"):
                    win.highlight(go.at)
                return
        if circle in self.phase.opens:
            self.open_setting(phase_strip.SETTINGS[circle])

    def _junban_found(self, here):
        """Alpha 3: 順's circle opens Junban's settings once Junban is found (`_junban_here`, a worker's file look)."""
        from PyQt6 import sip
        if here and not sip.isdeleted(self.phase):
            self.phase.set_opens(self.phase.opens | {phase_service.JUNBAN})

    def _status_mark(self, label, text, tip):
        """One of row 7's statuses (the journey dot; the re-order's and Connect's lines are the phase strip's hovers
        since alpha 3): shown while it has a value, repainted only when its own value (or its tooltip) changed (S19) —
        another field's change leaves it as it is."""
        text = text or ""
        if label.text() == text and label.isHidden() != bool(text) and label.toolTip() == (tip if text else ""):
            return
        label.setText(text)
        label.setToolTip(tip if text else "")
        label.setVisible(bool(text))
        self.status_paints[label] = self.status_paints.get(label, 0) + 1

    def _connect_fault(self):
        """A7N-3 (Sonic 2026-10-30): Connect's own Generate failed — its *Needs you* card (`feed.FAULT_KINDS`) makes ス
        red with its words, as a Generate you start does: looked at, still said in the hover (no longer red); gone with
        the card (fixed at Connect's next run, dismissed, *Not now*). The part is the need's own, at its time: the
        same failure again (Connect reopens it, a new `at`) is news again, red, whatever its words."""
        from app.connect import feed as connect_feed
        fault = next((e for e in self.needs_you.shown_entries()
                      if (e.data or {}).get("connect") and e.kind in connect_feed.FAULT_KINDS), None)
        key = f"connect-fault:{fault.key}:{fault.data.get('at')}" if fault is not None else None
        before = getattr(self, "_connect_fault_key", None)
        if before is not None and before != key:
            self.phase.set_extra(phase_service.SURASURA, before)
        if key is not None:
            self.phase.set_extra(phase_service.SURASURA, key, "failed", fault.title)
        self._connect_fault_key = key

    def _paint_needs(self):
        """The Needs you tab: shown while anything is listed, its badge the unseen entries (the bar's failures, the
        library's, the update's cards)."""
        snap = self._status_snap
        entries = snap.needs_you if snap is not None else ()
        listed = len(entries) + self._library_needs          # W2.2: the library's entries count too
        unseen = sum(1 for e in entries if not e.seen) + self._library_needs
        if getattr(self, "needs_you", None) is not None:      # W3.2 Q5: the page's entries (the bar's failures among
            listed, unseen = self.needs_you.counts()          # them) are what it lists and counts
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
        if "covers_download" in keys:                   # --- W3.2 L3: turned on, what is on screen now is asked
            qcovers.ask_again()                         # (titles dropped while it was off too: N1)
            self.ask_shown_covers()
        if "connect_enabled" in keys or "logic.automation" in keys:     # Connect's tick is skipped while off (its
            # switch or D29's automation, `connect_on`: P4.1 WF, review B1): its line asked now
            refresh = getattr(self.services.status, "refresh_soon", None)
            if refresh is not None:
                refresh("connect")
        if self.duties is not None:
            self._duty_settings(keys)
            if "logic.automation" in keys:
                self._read_d29()                        # the dot's tooltip follows D29
        elif "target_language" in keys:                 # --- W3.2 P0: before the duties, the library follows alone
            self._ask_language(self.services.settings.get().get("target_language") or "ja", self._library_switched)

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
        self._paint_level()                                    # W3.1a: the dot is a mark on the ▾ too

    def open_logs(self, folder=None, control=None, key="open:logs"):
        """*Open the logs folder*: `folder`, else — while the bar's failure is an update's with a report — the report's
        folder (written beside the install, not in the logs folder), else the logs folder. Round 8 row 45: a press
        (`press.open`) — `control` turns its arc (none: the bar's), the folder opens on a worker (it can take a
        moment), a second press meanwhile does nothing (`key`: a card's own, so a card rebuilt meanwhile turns it
        again). -> the press, or None."""
        folder = folder or self._report_folder(getattr(self._status_snap, "failure", None)) or self._logs_folder
        if not folder:
            return None
        return qpress.open(self, folder, control=control, key=key)

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
        if self.current_tab() == "settings":
            self.mount_settings()                             # W3.3 P7: the window came back on its Settings tab
        from app.qt import first_run                          # W3.5 part 3: the setup wizard over the window, first run
        first_run.host(self)                                  # (never raises; nothing when setup is finished)

        def ready(_services=None):
            self._attach_duties()
            wiz = first_run.opened(self)
            if wiz is not None:
                wiz.raise_()                                  # above the update sheet the duties made
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
        # the header (W3.1a): the level ▾ — its pop (W3.1b, the Level menu) holds the slider, Automatic, the
        # readout, Generate and *Open your journey* — and ? (*Online guide* only until the tours, IK-15 / IK-24)
        d.level = frame.LevelButton(self.header)
        d.pop = frame.LevelPop(self.centralWidget(), d.level)
        d.level.clicked.connect(d.pop.toggle)
        d.pop.picked.connect(self._level_write)
        d.pop.automatic.connect(self._level_automatic)
        d.pop.settings_asked.connect(lambda: self.open_setting("level"))
        d.pop.shown.connect(self._read_previews)
        self.register_overlay(d.pop)
        d.generate = duties_module.GenerateControl(d.pop)
        d.generate.pressed.connect(self._generate_pressed)
        d.generate.log_asked.connect(self._open_generate_log)
        d.journey = QPushButton(strings.LEVEL_JOURNEY, d.pop)
        d.journey.setObjectName("popjourney")
        d.journey.setToolTip(strings.JOURNEY_NONE_TIP)
        d.journey.setAccessibleName(strings.LEVEL_JOURNEY)
        d.journey.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        d.journey.setCursor(Qt.CursorShape.PointingHandCursor)
        d.journey.setEnabled(False)                     # until a journey is found on disk: hidden meanwhile
        d.journey.setVisible(False)
        qpress.room(d.journey, end=True)                # round 8 row 45: a link — its arc's room at its right end
        d.journey.clicked.connect(lambda _c=False: self._open_journey(control=d.journey))
        # laptop fixes (Sonic: "the journey should never automatically pop up … a button by auto … to open the
        # journey"): *Journey ↗* beside the ▾, the header's own button look (as ?); shown while one is on disk
        d.journey_button = QToolButton(self.header)
        d.journey_button.setObjectName("headjourney")
        d.journey_button.setText(strings.HEADER_JOURNEY)
        d.journey_button.setToolTip(strings.JOURNEY_NONE_TIP)
        d.journey_button.setAccessibleName(strings.HEADER_JOURNEY_NAME)
        d.journey_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        d.journey_button.setCursor(Qt.CursorShape.PointingHandCursor)
        d.journey_button.setEnabled(False)
        d.journey_button.setVisible(False)
        qpress.room(d.journey_button)
        d.journey_button.clicked.connect(lambda _c=False: self._open_journey(control=d.journey_button))
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
        d.journey_dot = QLabel(d.pop)                     # row 7: the sentences catching up (02-state-model, G10)
        d.journey_dot.setObjectName("journeydot")
        d.journey_dot.setTextFormat(Qt.TextFormat.PlainText)
        d.journey_dot.setAccessibleName(strings.JOURNEY_DOT_NAME)
        d.journey_dot.setVisible(False)
        d.pop.add_action(d.generate)
        journey_row = QHBoxLayout()
        journey_row.setContentsMargins(0, 0, 0, 0)
        journey_row.addWidget(d.journey)
        journey_row.addWidget(d.journey_dot)
        journey_row.addStretch(1)
        d.pop.actions.addLayout(journey_row)
        # --- W3.2 Q3: the level ▾ before + Add, ? after it
        header_row = self.header.layout()
        header_row.insertWidget(header_row.indexOf(self.add_stone), d.level)
        header_row.insertWidget(header_row.indexOf(self.add_stone), d.journey_button)    # right of the ▾ (laptop fixes)
        header_row.insertWidget(header_row.indexOf(self.report_button), d.help)          # ? before the bug
        # --- end W3.2 Q3
        self._paint_level()
        # the bar (W3.1a): the known corner and the emerald are the footer's (statuses: W3.3 makes them open
        # Settings; the level chip gave way to the ▾); the update chip in the status line's slot while it applies
        # (W31A-1, `_paint_slot`)
        row = self.footer.layout()
        d.known, d.anki = self.known, self.anki_mark
        d.update_mark = QPushButton(strings.UPDATE_READY, self.footer)
        d.update_mark.setToolTip(strings.UPDATE_MARK_IDLE_TIP)
        d.update_mark.setAccessibleName(strings.UPDATE_READY)
        d.update_mark.setProperty("kind", "chip")
        d.update_mark.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        d.update_mark.clicked.connect(self.open_update_sheet)
        d.update_mark.setVisible(False)
        row.insertWidget(row.indexOf(self.bar_failure_cross) + 1, d.update_mark)
        d.update_cross = standing_qt.Cross(self.footer)      # round 8 row 54: the chip hidden for this session
        d.update_cross.clicked.connect(self._update_dismissed)
        d.update_cross.setVisible(False)
        row.insertWidget(row.indexOf(d.update_mark) + 1, d.update_cross)
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
        self.bridge.indexed.connect(lambda _language: self._previews_moved())
        self.bridge.attach(updates=s.updates, controller=s.controller, automation=s.automation, chores=s.chores)
        self._show_update(s.updates.state())
        self._show_generate(s.controller.state())
        self._show_automation(s.automation.state())
        if self._status_snap is not None:                   # the dot the bar's last snapshot asked for
            self._paint_journey_dot()
        self._read_d29()                                    # its tooltip's D29, read on a worker

    def setup_held(self, up):
        """(first_run.py) The setup wizard came up / went: while it is up the quiet Generates wait (AD-8); its close
        asks again, on a worker."""
        if up:
            self.services.setup_open.set()
        elif self.services.setup_open.is_set():
            bridge.run_in_worker(self.services.setup_ended)

    def _session_said(self, line):
        from app.qt import windows
        windows.say_in_bar(self, line)

    def _duties_started(self):
        """Started: what the bar and the header read from disk, read on workers."""
        self._check_journey()
        self._read_level()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowStateChange) and \
                getattr(self, "looks", None) is not None:                  # --- SRC W1b: a look on focus (throttled)
            if event.type() == QEvent.Type.ActivationChange and self.in_front():
                self.look_at_sources(focused=True)
            else:
                self.looks.set_shown(self.in_front())    # behind / minimized: nothing looked at, watches' reports held
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
        if "target_language" in keys and language != self._language_asked:
            self._ask_language(language, self._language_followed)                           # (W3.2 P0)
        elif s.level_moved(keys):                           # only what the level reads (IK-28, S19)
            self._read_level()
            if s.replan is not None:
                s.replan.level_changed()                    # W3.3 S3: the journey keeper hears a level key
        elif "strategy" in keys or "target_coverage" in keys:
            self._read_level()                              # W3.1b: the pop greys its slider in coverage mode
        read = set(keys) - {"logic.selection.band", "logic.selection.auto", "logic.selection.auto_max_words"}
        if read and (s.level_moved(read) or "exclude_single" in read or "logic.phrase_rows" in read):
            self._previews_moved()                          # W3.1b: a key the bands' numbers read (Settings' set)
        if "anki_sync_auto" in keys:
            self._show_automation(s.automation.state())
        elif "anki_sync_decks" in keys or "target_language" in keys:
            self._known_road()                              # the count's click line follows the road (IK-7)
        try:
            stale = s.settings.stales(keys, language)
        except Exception:
            stale = False
        if stale:
            bridge.run_in_worker(s.automation.recheck)      # the Generate button's mark asked again
            if s.replan is not None and any(s.settings.kind(k, language) == "report" for k in keys):
                s.replan.report_changed()                   # a6 #5: the journey drawn again (its mark leaves it out)

    # Generate
    def _show_generate(self, state):
        d = self.duties
        before, d.generate_state = d.generate_state, state
        d.generate.show_state(state)
        gen = d.module.gen                                 # W3.1a: its share on the header's hairline, its mark on ▾
        self._share = gen.percent(state) if state.state == gen.RUNNING else None
        self._paint_progress()
        self._paint_level()
        busy = ("queued", "running", "cancelling")
        ended = before is not None and before.state in busy and state.state not in busy
        if (state.state == "failed") != (before is not None and before.state == "failed") or ended:
            self.services.status.refresh_soon()            # its failure on, or off, the bar and Needs you (E10, HR-23)
        if ended:
            self._check_journey()                          # a run ended: a journey on disk now, the level again
            self._read_level()

    def _generate_pressed(self):
        """A click runs Generate — or, while one the user asked for is asked for or running, cancels it (before
        *Writing your list*). On an automatic run the click is the user's own run, which takes its place (IK-20).
        Round 8 row 45: the button's arc turns from the frame of the click — before the settings are flushed (up to
        10 s) and the run is asked for — until the controller has it (its queued look), or its cancel was asked."""
        d = self.duties
        state = d.generate_state
        s = self.services
        b = d.generate.button
        if state is not None and state.state in ("queued", "running", "cancelling") and not state.quiet:
            if d.module.gen.can_cancel(state):
                qpress.run(b, "generate", s.controller.cancel, win=self)
            return
        qpress.run(b, "generate", s.generate, failed=lambda info: self.say(str(info[0])), win=self)

    def _open_generate_log(self):
        path = getattr(self.duties.generate_state, "log_path", None)
        if path:
            qpress.open(self, path, control=self.duties.generate.log_button, key="open:generate-log")

    def _open_guide(self, _checked=False):
        """? › *Online guide*: its menu has closed, so the bar's arc turns until the browser was asked (a worker)."""
        qpress.run(None, "open:guide", self.services.open_guide, win=self)

    # Your journey
    def _check_journey(self):
        bridge.run_in_worker(self.services.journey_exists, then=self._show_journey,
                             failed=lambda info: self._show_journey(False))

    def _show_journey(self, exists):
        exists = bool(exists)
        for b in (self.duties.journey, self.duties.journey_button):
            if b.isEnabled() != exists:
                b.setEnabled(exists)
                b.setVisible(exists)                       # W3.1a: shown only while there is one to open
                b.setToolTip(strings.JOURNEY_TIP if exists else strings.JOURNEY_NONE_TIP)
        if self.duties.pop.isVisible():
            self.duties.pop.place()

    def _open_journey(self, *_checked, asked=False, control=None, at=None, episode=None):
        """*Journey ↗* in the header, *Open your journey ↗* in the pop — and (`asked`, W3.1a S5) Up Next's *N new
        words ↗*: with none on disk the entries go, and a click from Up Next says why in the bar. The only ways the
        journey opens: a Generate writes it and never opens it (laptop fixes). Round 8 row 45: one press for all four
        (`press.run`): `control`'s arc turns (or `at`: the row's ↗, ⋯; neither: the bar's) until the browser was
        asked, and a click meanwhile, from any of them, does nothing. `episode` (Up Next's ↗, a row's ⋯ *See it in your
        journey*; Sonic 2026-10-24): the report opens ON it, its panel shown (`journey_file`); every other way in opens
        where the report opens by itself. -> the press, or None."""
        def done(opened):
            if opened == JOURNEY_LACKS:             # JO-1: opened where it opens by itself; the bar says why
                self.say(strings.JOURNEY_NOT_YET.format(ep=episode.label))
                return
            if opened == JOURNEY_OLD_LOOK:          # a6 #5 (A6W-2): its new look waits for the Generate that's due
                self.say(strings.JOURNEY_LOOK_LATER)
                return
            if opened:
                return
            if self.duties is not None:
                self._show_journey(False)
            if asked:
                self.say(strings.JOURNEY_NONE_TIP)

        def failed(info):
            self.say(strings.JOURNEY_FAILED.format(why=info[0]))
        file = journey_file(episode)
        return qpress.run(control, "journey:open", self.services.open_journey, *((file,) if file else ()), then=done,
                          failed=failed, win=self, at=at)

    # the bar's marks
    def _show_automation(self, state):
        d = self.duties
        if needs_asked(state, d.auto_state) and getattr(self, "needs_you", None) is not None:
            self.needs_you.synced()
        known = getattr(state, "known", None)
        if known is not None and known != getattr(d.auto_state, "known", None):
            self._previews_moved()                         # W3.1b: new known words move the bands' numbers
        d.auto_state = state
        junban = getattr(state, "junban", None)
        if junban and junban != d.junban_said:             # 順's line, once (the Tk `_on_junban_auto`: IK-23)
            d.junban_said = junban
            self.toasts.show(junban)
        known = getattr(state, "known", None)
        self._known_road()
        if d.known.set_known(known, strings.BAR_KNOWN_TIP):     # W3.1a: the known corner (repainted on a change only)
            d.paints[d.known] = d.paints.get(d.known, 0) + 1
        if not self.services.settings.get().get("anki_sync_auto"):
            key = "off"
        else:
            key = state.sync if state.sync in strings.BAR_ANKI else None
        words = tip = ""
        if key is not None:
            words, tip = strings.BAR_ANKI[key], strings.BAR_ANKI_TIP[key]
            if key == "synced" and state.added:
                tip = strings.BAR_ANKI_TIP["synced-added"].format(n=state.added)
            elif key == "failed":
                tip = tip.format(message=state.message or "")
        # W3.1a: the emerald, lit while Anki answers, dark when closed / failed / off — the words say which, in its
        # hover. *N waiting* (W31A-2) comes from the status service's `backlog`, in `show_status`.
        if d.anki.show_state(key, words, tip):
            d.paints[d.anki] = d.paints.get(d.anki, 0) + 1

    def _known_clicked(self):
        """Q30: a click on the known-words count syncs now, through the automation's one sync path (`sync_now`: the
        automatic sync's own job, forced, and with the automatic sync off too — the user asked; it ends as every sync
        does). A click while one runs adds nothing. With no decks chosen yet, or the first sync not made (always the
        user's own, in the Anki window), the Anki window opens instead. Round 8 row 45: the press shows on the count's
        hairline from the frame of the click (`KnownCorner.press_look`), before the sync is asked for, until that sync
        (or the one already running) ends or the answer says why not; a click meanwhile asks nothing. Every ask is
        answered (A-2: a sync that couldn't be asked for says "failed", a closed automation "closed"), so the press
        always ends. Its job is followed by hand (`_known_followed`) until P3's `press.follow`."""
        automation = self.services.automation
        if automation is None:
            return
        if self._known_relay is None:
            self._known_relay = bridge.Relay(self)
            self._known_relay.said.connect(self._known_answer)
        p = qpress.begin(self.known, "known:sync", win=self)
        if p is None:
            return
        self._known_press, self._known_answered = p, False
        automation.sync_now(then=self._known_relay.call)

    def _known_answer(self, why):
        """The click's answer (AutoSync's own): no decks or no first sync opens the Anki window; a refusal is said in
        the bar (AD-6: an update staged, a sync already running), never nothing. A sync started, or one already
        running: its hairline shows it until its job ends (`_known_followed`)."""
        self._known_answered = True
        if why not in (None, "running"):
            self._known_followed(ended=True, failed=why == "failed")
        else:
            self._known_followed()
        if why in ("no-decks", "never-synced"):
            from app.qt import windows
            op = next((op for op in windows.OPENERS if op.name == "anki"), None)
            if op is not None:
                windows.launch(self, op)
        elif why in strings.FOOT_KNOWN_REFUSED:
            self.say(strings.FOOT_KNOWN_REFUSED[why])

    def _known_followed(self, ended=False, failed=False):
        """Round 8 row 45: the click's press ends once it was answered and no sync runs (the registry's views), or at
        once (`ended`: nothing was started; `failed`: it couldn't be asked for)."""
        p = self._known_press
        if p is None or not p.live() or not self._known_answered:
            return
        if ended or not self.known.syncing:
            self._known_press = None
            qpress.end(p, self, failed=failed, why=strings.FOOT_KNOWN_REFUSED.get("failed") if failed else None)

    def _known_road(self):
        """IK-7: the count's hover names what a click does — the page's known-words road, one rule
        (`settings_catalog.known_road`): this language's Anki decks chosen, a sync; none, the Anki window."""
        d = self.duties
        if d is None:
            return
        from app.qt import settings_catalog as catalog
        settings = self.services.settings.get()
        d.known.set_road(catalog.known_road(settings, settings.get("target_language") or "ja"))

    def _read_level(self):
        d = self.duties
        if d is not None:
            d.level_asked += 1                             # W3.1b: an older answer never moves the pop's slider
            asked, level = d.level_asked, self.services.level
            # a bound method (`_level_answer`) as the answer: Qt drops it with the window
            bridge.run_in_worker(lambda: (asked, level()), then=self._level_answer)

    def _level_answer(self, answer):
        asked, level = answer
        if self.duties is not None and asked == self.duties.level_asked:
            self._show_level(level)

    def _show_level(self, level):
        from app import word_selection
        band, automatic = level
        name = word_selection.band_label(band) if band else ""
        if automatic:
            text = strings.BAR_LEVEL_AUTO.format(band=name) if name else strings.BAR_LEVEL_AUTO_NONE
            tip = strings.BAR_LEVEL_AUTO_TIP.format(band=name) if name else strings.BAR_LEVEL_AUTO_NONE_TIP
        else:
            text, tip = name, strings.BAR_LEVEL_TIP.format(band=name)
        d = self.duties
        d.level_tip = tip if text else strings.LEVEL_WAITING
        d.level_text = text or strings.LEVEL_WAITING
        settings = self.services.settings.get()
        waiting = bool(automatic and not band)             # Automatic with no numbers yet: no band to show (S16)
        if waiting:
            band = (((settings.get("logic") or {}).get("selection") or {}).get("band"))
        coverage = settings.get("target_coverage") if settings.get("strategy") == "coverage" else None
        d.pop.set_level(band, automatic, waiting=waiting, coverage=coverage)
        self._paint_level()

    # W3.1b: the Level menu's slider, Automatic and readout
    def _level_write(self, value):
        """A band picked in the pop (its key: Automatic goes off with it, S2) or Automatic flipped
        ({"logic.selection.auto": bool}): written as Settings' level row writes it (`settings_catalog.change`, only what
        differs) through the settings service (queued: this thread never writes). The rest follows the write:
        `_duty_settings` reads the level again and the journey keeper hears it."""
        from app.qt import settings_catalog as catalog
        s = self.services
        try:
            changes, _update = catalog.change(catalog.ROW["level"], s.settings.get(), self.language, value)
        except (ValueError, TypeError) as e:
            applog.log("shell", f"level: {e}")
            return
        if changes:
            s.settings.set(changes)

    def _level_automatic(self, on):
        """Automatic flipped in the pop. Off, the band it was showing becomes yours, in the same write (2.x's D3: the
        list doesn't change the moment you switch it off) — only when that band was read (not while it waits)."""
        value = {"logic.selection.auto": bool(on)}
        pop = self.duties.pop
        if not on and pop.level is not None and pop.level[1] and not pop.waiting:
            value["logic.selection.band"] = pop.slider.value()
        self._level_write(value)

    def _previews_moved(self):
        """What the bands' numbers read moved (the library, the index, the known words, a key they read, the
        language): read again now while the pop is open, else at its next opening (S19: never on an opening alone)."""
        d = self.duties
        if d is None:
            return
        d.previews_dirty = True
        if d.pop.isVisible():
            self._read_previews()

    def _read_previews(self):
        """Every band's numbers for the pop's readout (`settings_live.read_previews`), on a worker — only when
        something they read moved since the last read, one at a time, once more if asked meanwhile."""
        d = self.duties
        if d is None or not d.previews_dirty or d.pop.coverage is not None:
            return                                         # nothing moved, or coverage mode: no numbers shown
        if d.previews_busy:
            d.previews_again = True
            return
        d.previews_busy, d.previews_again, d.previews_dirty = True, False, False
        language, settings = self.language, self.services.settings

        def read():
            from app.qt import settings_live
            return language, settings_live.read_previews(settings_service.thaw(settings.get()), language)
        # bound methods as the answers: Qt drops them with the window
        bridge.run_in_worker(read, then=self._previews_read, failed=self._previews_failed)

    def _previews_read(self, answer):
        language, previews = answer
        d = self.duties
        if d is None:
            return
        d.previews_busy = False
        if d.previews_again:
            self._read_previews()
            return
        if language == self.language:                      # a language left meanwhile: its numbers never shown
            d.pop.set_previews(previews)

    def _previews_failed(self, info):
        applog.log("shell", f"the level's numbers: {info[0]}")
        d = self.duties
        if d is not None:
            d.previews_dirty = True                        # asked again at the next opening
            self._previews_read((None, None))

    def _paint_level(self):
        """W3.1a: the level ▾ — its words, its tooltip (the level, then its mark's words) and its mark: Generate failed
        (amber), stale, or the journey's sentences catching up (`frame.level_mark`); repainted only on a change."""
        d = self.duties
        gen, state = d.module.gen, d.generate_state
        snap = self._status_snap
        mark = frame.level_mark(state is not None and state.state == gen.FAILED,
                                state is not None and state.state == gen.STALE,
                                bool(snap is not None and snap.journey))
        tip = (strings.LEVEL_TIP_MARK.format(level=d.level_tip, mark=strings.LEVEL_MARKS[mark]) if mark
               else strings.LEVEL_TIP.format(level=d.level_tip))
        changed = d.level.set_level(d.level_text, tip)
        if d.level.set_mark(mark) or changed:
            d.paints[d.level] = d.paints.get(d.level, 0) + 1

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
        d.update_applies = look is not None and self.standing.shows(d.module.update_mark_key(state),  # nothing to
                                                                   standing_service.UPDATE)   # say, or ✕: hidden
        if look is not None and (m.text() != look[0] or m.toolTip() != look[1]):
            m.setText(look[0])
            m.setToolTip(look[1])
            m.setAccessibleName(look[0])
            d.paints[m] = d.paints.get(m, 0) + 1
        self._paint_slot()                                 # W31A-1: it holds the slot unless a failure does
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
        """A click on the sheet or a Needs you card, sent to the update service on a worker. Round 8 row 45: a press —
        the clicked button's arc turns (`_update_control`) from the frame of the click until the service answered."""
        u = self.services.updates
        control = self._update_control(name, key)
        if name == "start":
            qpress.run(control, "update:start", u.start, win=self)
        elif name in ("download", "notes"):
            qpress.run(control, f"update:{name}", u.open_download, win=self)
        elif name == "skip":
            self.duties.sheet.hide()
            bridge.run_in_worker(u.skip, key)              # `skipped_version` written, nothing else
        elif name == "stop":
            qpress.run(control, ("update:stop", key), u.stop, key, win=self)
        elif name == "stop-all":
            qpress.run(control, "update:stop-all", u.stop, win=self)
        elif name == "cancel":
            self.duties.sheet.hide()
            self._cancel_update()
        elif name == "logs":
            self.open_logs(key, control=control)           # a failure's card: its report's folder, when it has one

    def _update_control(self, name, key):
        """The sheet's or the update card's button that sent `name` (a program's *Stop* by its `key`), or None."""
        sender = self.sender()
        if sender is None or not hasattr(sender, "findChildren"):
            return None
        return next((b for b in sender.findChildren(QPushButton) if b.property("action") == name and b.isVisible()
                     and (name != "stop" or b.property("program") == key)), None)

    def _sheet_dismissed(self):
        """Esc, Back or *Later* closed the sheet: an update downloading or waiting is cancelled (IK-2, as Tk)."""
        state = self.duties.update_state
        if state is not None and state.state in ("downloading", "waiting"):
            self._cancel_update()

    def _cancel_update(self):
        """The update cancelled (its sheet has closed: the bar's arc turns until the service answered)."""
        s = self.services
        qpress.run(None, "update:cancel", s.updates.cancel, win=self,
                   then=lambda cancelled: cancelled and bridge.run_in_worker(s.automation.update_cancelled))

    def _quit_for_update(self, _value=None):
        """The update hands over (its `on_quit`): the window closes, and the app with it — at once: the update waited
        for the Anki writers itself (its wait list), and the updater waits on this process."""
        self._quit = "ready"
        self.close()
        QApplication.quit()
    # --- end W3.5 ------------------------------------------------------------------------------------------------ #

    # --- the look ------------------------------------------------------------------------------------------- #
    def set_look(self, text_size=None):
        """Settings › App › Text size (W3.3 calls it): saved through the settings service, and applied at once
        (LIVE_LOOK) — else *Restart to apply* in the bar. One theme in 3.0 (RS-1): no theme to pick (themes, 3.1).
        -> the milliseconds the switch took, or None."""
        theme_name, current_size, language = style.current()
        text_size = text_size if text_size in theme.TEXT_SIZES else current_size
        self.services.settings.set({"text_size": text_size})
        if not LIVE_LOOK:
            self.say(strings.RESTART_TO_APPLY)
            return None
        ms = style.apply(QApplication.instance(), theme_name, text_size, language)
        titlebar.apply(self, theme_name)
        self._apply_sizes()
        self.update()
        return ms

    def restart(self):
        """*Restart now* (Settings › Text size; laptop fixes row 15): the window closes the quit's way — what can't
        stop part-way ends first (E20), the window state is saved (size, place, this tab), the settings written — and
        `main` starts the same program again once the quit is over, the store's close included (`relaunch`). Offered
        only while no Generate runs (`generating`)."""
        self.restart_asked = True
        self.close()

    def generating(self):
        """Whether a Generate waits or runs (the registry's newest snapshot): a quit now would stop it (B2-3)."""
        return jobs_module.generating(self._jobs)

    # --- overlays --------------------------------------------------------------------------------------------- #
    def register_overlay(self, overlay):
        """An in-window overlay (tray, sheet, panel, popover): Esc, Back and a click outside close it (05 §5.4)."""
        self.router.register(overlay)

    # --- SRC W1b: the source folders (app/services/source_looks.py; the RUNBOOK §1b S4, S10 / D5, S14 / D6) -------- #
    def _start_looks(self):
        """After the first frame: the looks made for the library open, and the first look after start (a full one)."""
        if self.looks is None:
            self._open_looks(self.services.writer)
        self.look_at_sources(focused=True)

    def _open_looks(self, writer):
        """The looks for `writer`'s library (its opener: a store handle of their own, on their own worker) — a test's
        `services.source_looks` first; the previous ones closed. None without an opener (no library)."""
        looks = getattr(self.services, "source_looks", None)
        if looks is None:
            opener = getattr(writer, "opener", None)
            if opener is not None:
                from app.services.source_looks import SourceLooks
                settings = self.services.settings
                looks = SourceLooks(opener, self.language, rules=lambda: settings.get().get("placing_rules"))
        old, self.looks = self.looks, looks
        if old is not None and old is not looks:
            old.close()
        if looks is not None:
            looks.on_result = self._looks_said
            looks.on_ended = lambda told, why: self._ended_relay.call((told, why))
            looks.on_progress = lambda path, found, shows: self._progress_relay.call((path, found, shows))
        self._follow_folders(looks)
        return looks

    def _follow_folders(self, looks):
        """SRC W1b / K7 / A4B-8: each arrival from a source folder names its folder (where its original sits, the
        looks' `folders(..., detail=True)`) — asked and named by the reader on its own thread, never this one's: a new
        view at 20,000 arrivals cost ~15 ms here. The reader shown asks these looks from now on (None: no looks)."""
        reader = self._reader_shown
        follow = getattr(reader, "follow_folders", None)
        if follow is None:
            return
        asks = getattr(looks, "folders", None)
        follow(None if asks is None else (lambda ids, then: asks(ids, then, detail=True)))

    def _looks_said(self, summary):
        """(The looks' worker.) A look's summary, with the offline lines hidden (round 8 row 54: the seen file, pruned
        by it first — `standing.looked`), to the window's thread."""
        self._sources_relay.call(standing_service.looked(self.language, summary))

    def _follow_looks(self, writer):
        """A language switch: that library's folders, looked at once (its own cadence); the last one's line goes."""
        self._open_looks(writer)
        self.sources = ()
        self.sources_listed = False
        self.offline_hidden = set()
        self._show_offline()
        self._show_kept_out()
        # Settings' lines: the language open's, its listing asked for (never "No folders yet" while it is on its way)
        self.sources_seen.emit({"language": self.language, "sources": [], "listing": self.looks is not None})
        if self.looks is not None:
            self.looks.listing()
        if self._first_painted:
            self.look_at_sources(focused=True)

    def in_front(self):
        """The window shown, not minimized and the active one (SRC-9: no look while it is behind or minimized)."""
        return self.isVisible() and self.isActiveWindow() and not self.isMinimized()

    def look_at_sources(self, focused=False, refreshed=False):
        """On focus (`focused`), Refresh (`refreshed`) or the tick: a look when `sources.due` says so, on the looks'
        worker (never this thread). -> True when one was asked."""
        if self.looks is None or self._quit is not None:
            return False
        return self.looks.asked(focused=bool(focused), refreshed=bool(refreshed), shown=self.in_front())

    def refresh_sources(self, control=None):
        """Refresh (the Refresh key; Settings' *Look again*): every folder looked at in full, now. Round 8 row 45: a
        press — `control`'s arc turns (none, the Refresh key's: the bar's) until the look ends (`_look_ended`: its
        summary, or a look that couldn't run, said in the bar; `REFRESH_CAP_S` at most, a backstop). Nothing to look
        with: nothing marked (it answers at once). A second press while one is live does nothing (A3)."""
        if self.looks is None or self._quit is not None:
            return False
        p = qpress.begin(control, "sources:refresh", win=self)
        if p is None:
            return False
        self._refresh_press = p
        QTimer.singleShot(int(REFRESH_CAP_S * 1000), lambda: self._refresh_ended(p))
        return self.look_at_sources(refreshed=True)

    def _refresh_ended(self, p=None, why=None):
        """Refresh's press ends: a look ended (`why`: it couldn't run — the press failed, said in the bar), or its
        cap passed (`p`, that press only)."""
        live = self._refresh_press
        if live is None or (p is not None and live is not p):
            return
        self._refresh_press = None
        if live.live():
            qpress.end(live, self, failed=why is not None, why=why)
            if why is not None:
                self.say(strings.REFRESH_FAILED.format(why=why))

    def _look_ended(self, answer):
        """A look ended (its summary, if any, came first: the same worker, the same order)."""
        told, why = answer
        self._refresh_ended(why=None if told else (why or strings.REFRESH_NOT_LOOKED))

    def _sources_looked(self, summary):
        """A look's (an add's, a stop's) summary: the offline line, and Settings' row (`sources_seen`)."""
        if not isinstance(summary, dict) or summary.get("language", self.language) != self.language:
            return                                        # B2: a language left never paints over the one open
        self.sources = tuple(summary.get("sources") or ())
        self.sources_listed = True
        self._refresh_ended()                             # round 8 row 45: Refresh's press, ended by its look
        self.offline_hidden = (self.offline_hidden | set(summary.get("kept_lines") or ())) & \
            standing_service.not_back(self.sources)       # round 8 row 54: a folder back lets its ✕ go
        self._show_offline()
        self._show_kept_out()                             # alpha 4 (Mattias #8): New arrivals' kept-out foot
        looks = getattr(self.services.library, "play", None)
        if looks is not None and summary.get("moved"):   # row 55: a video come beside an original: ▶ looked again
            looks.again()                                 # (IK-1: a look that changed nothing looks at nothing)
        if summary.get("moved"):                          # MV-2: Connect's episodes waiting on a video go on —
            self._kick_connect()                          # a *Find its folder…* answered (kicked on a worker)
        if summary.get("unfinished_reset"):              # LF-11: a fresh library a kill stopped, once a run
            from app.qt import settings_strings, windows
            windows.say_in_bar(self, settings_strings.FRESH_UNFINISHED.format(folder=summary["unfinished_reset"]))
        self.sources_seen.emit(summary)

    def _kick_connect(self):
        """MV-2: Connect kicked on a worker (`kick.kick`: started, or the one running woken; nothing while it's off):
        a look recorded videos for known episodes, and a job of theirs waiting on *No video* waits only for its next
        start (`runner._wait`'s parking) — the next start is now, as a *Link…* is (`window_link`). Only while Connect's
        last look (the feed, in memory) has an episode on *No video*: a look that found a new episode's video starts
        nothing (S19)."""
        from app.connect import feed as connect_feed_module
        from app.connect import kick
        try:
            latest = connect_feed(self.language, self.services.settings).latest()
            if not any(item.kind == connect_feed_module.NO_VIDEO for item in latest.items.values()):
                return
            settings = settings_service.thaw(self.services.settings.get())
        except Exception as e:
            applog.log("connect", f"Connect wasn't started after a look: {e!r}")
            return
        bridge.run_in_worker(lambda: kick.kick(settings, videos=True),
                             failed=lambda info: applog.log("connect", f"Connect's start: {info[0]}"))

    def _play_not_found(self, item_id):
        """A ▶ press found nothing to open (row 55 A-7): that episode's ▶ looked at again, on the looks' worker."""
        looks = getattr(self.services.library, "play", None)
        if looks is not None:
            looks.recheck([item_id])

    def _offline_shown(self):
        """[(key, path, items)] of the folders the offline line names: away, and not hidden by its ✕ — a GONE one is
        *Needs you*'s card (T6), on the line only in a window with no *Needs you* (no library)."""
        from app.services.source_looks import offline
        shown = ((standing_service.offline_key(path), path, n)
                 for path, n in offline(self.sources, gone=getattr(self, "needs_you", None) is None))
        return [s for s in shown if s[0] not in self.offline_hidden]

    def _gone_shown(self):
        """T6: the looks' rows of the folders that are GONE whose *Needs you* card stands (not hidden by *Keep
        waiting*); none in a window with no *Needs you*."""
        if getattr(self, "needs_you", None) is None:
            return []
        from app.services.source_looks import gone
        return [r for r in gone(self.sources) if standing_service.offline_key(r["path"]) not in self.offline_hidden]

    def offline_text(self):
        """The offline line's words for `sources` (empty: every folder reachable, not looked at yet, or hidden)."""
        lines = []
        for _key, path, n in self._offline_shown():
            if n == 1:
                lines.append(strings.SOURCES_OFFLINE_ONE.format(path=path))
            elif n:
                lines.append(strings.SOURCES_OFFLINE.format(path=path, n=n))
            else:
                lines.append(strings.SOURCES_OFFLINE_NONE.format(path=path))
        return " · ".join(lines)

    def _show_offline(self):
        """Repainted only when its words moved (S19); shown while there are any — and 届 amber while it is (the
        phase strip, Q1: a folder offline waits on you)."""
        text = self.offline_text() if self.sources else ""
        self.offline_line.show_line(text)
        # a7 (Sonic 2026-10-29: amber only with a decision): a folder offline waits for its drive — words in 届's hover
        self.phase.set_extra(phase_service.ARRIVALS, "offline", "info" if text else None, text)
        # T6: a folder that is GONE is a *Needs you* card — 届 amber while it stands, and its press opens it there
        gone = self._gone_shown()
        words = (strings.PHASE_FOLDER_GONE.format(name=os.path.basename(os.path.normpath(gone[0]["path"])))
                 if len(gone) == 1 else strings.PHASE_FOLDERS_GONE.format(n=len(gone)))
        if gone:
            self.phase.set_extra(phase_service.ARRIVALS, "gone", "needs", words, GONE_GO)
        else:
            self.phase.set_extra(phase_service.ARRIVALS, "gone")
        if getattr(self, "needs_you", None) is not None:      # (judged: every folder being read was looked at —
            judged = self.sources_listed and all(r.get("reachable") is not None   # none read, once listed: K1's
                                                 for r in self.sources if r.get("on", True))   # card waits on no look)
            self.needs_you.gone_in(gone, self.language, judged=judged)

    def moves_saving(self, on):
        """The drag's writer holds moves for a busy store (`moves.Writer.on_saving`): 届 waits while it does."""
        self.phase.set_extra(phase_service.ARRIVALS, "saving", "waiting" if on else None, strings.MOVE_WORDS["saving"])

    def _sources_progress(self, said):
        """A folder being read for the first time (+ Add): its count so far, in the bar."""
        path, found, shows = said
        name = os.path.basename(os.path.normpath(path)) or path
        self.say(strings.SOURCES_READING.format(name=name, found=found, shows=shows))

    # --- end SRC W1b

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
        # W3.1a S1: the stones' sheet asked for now — after the first frame, never inside it (rows painted before it
        # are painted again once, with their stones, when it lands)
        from app.qt import stones
        stones.release(self._stones_hold)
        if self.services.library is not None:                 # (no library: no row, no stone to draw)
            stones.get(self.devicePixelRatioF() or 1.0, style.current()[1])
        if getattr(self.services, "library_after_frame", False) and self._reader_shown is not None:
            self._reader_shown.start()                         # W3.2 P0: the first screen's cache read off the frame
            if self.moves is not None:
                self.moves.start(on_worker=True)               # ... and the writer's first look at the store, its replay
        # --- W3.2 Q6: the covers asked for meanwhile decode now; the disk scan once per open
        qcovers.release(self._stones_hold)
        self.scan_covers()
        self._start_looks()                                    # --- SRC W1b: the first look after start (full)

    def scan_covers(self, progress=None, then=None):
        """W3.2 Q6: the library's covers from disk (`covers.start_scan`), on a thread of its own — after the first
        frame, and again when another library opens (and from setup's load screen: `progress` / `then`, on the scan's
        thread). -> the scan's thread, or None (no library or no writer)."""
        library, writer = self.services.library, self.services.writer
        if library is None or writer is None:
            return None
        listen = {k: v for k, v in (("progress", progress), ("then", then)) if v is not None}
        return qcovers.start_scan(getattr(library, "opener", None), self.language, writer, **listen)
        # --- end W3.2 Q6

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
                self.vein.go(self.tab_buttons[tab], animate=False)     # W3.1a: there at once, not travelling
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
        if self._moves_pending():                         # W3.1a, 04 §4.5: the moves still queued go first
            if not waited:
                self._quit_line = strings.MOVE_WORDS["saving"]
            self._moves_waited = False
            began = time.monotonic()
            bridge.run_in_worker(lambda: self.services.finish_moves(began + QUIT_FINISH_WAIT), then=self._moves_idle,
                                 failed=self._moves_idle)
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

    def _moves_idle(self, _ended):
        self._moves_waited = True
        self._jobs_changed(self._jobs)

    def _replan_settling(self):
        settling = getattr(self.services, "replan_settling", None)
        return settling is not None and settling()

    def _jobs_changed(self, views):
        self._jobs = views
        # Q30: the count's hover says a sync is running — the automatic one, a click's or the Anki window's
        known = getattr(self, "known", None)
        if known is not None:
            sync = next((v for v in views if v.kind == "anki-sync" and v.state in jobs_module.LIVE), None)
            known.set_syncing(sync is not None)
            got = getattr(sync, "progress", None)           # round 8 row 45: the click's hairline fills as it goes
            if got is not None and got.total:
                known.set_work_share(100.0 * (got.done or 0) / got.total)
            self._known_followed()                          # ... until its sync ends
        if self._quit == "waiting" and self._replan_waited and getattr(self, "_moves_waited", True) and \
                not jobs_module.waits_at_quit(views):
            self._close_now()

    def _close_now(self):
        if self._quit != "waiting":
            return
        self._quit = "ready"
        self._quit_timer.stop()
        self.close()

    # --- row 35: closing while helpers go on without the window ------------------------------------------------- #
    def _ask_detached(self):
        """The close with jobs that outlive the window (`jobs.detached_at_quit`: the library's upkeep, Connect making
        cards — each keeps the program's folder in use until it ends): the window's sheet names them — *Quit* (the
        default, and Esc, Back, a click outside: today's close, they go on) or *Stop and quit* (offered only when one
        is of a kind it may stop, `jobs.STOPPABLE_AT_QUIT`: Connect alone → Quit is the one button). Asked once a close,
        first in it (before E20's wait); never for the update's hand-over, *Restart now* or the session ending (a
        logoff never waits on a sheet). Any other card open in the window is dropped first: the sheet never stacks on
        one. While it asks nothing new starts (every answer quits). A close while it is open is Quit. None under way →
        nothing asked, the close as before. -> True when the close waits for the answer."""
        card = self._detached_card
        if self._quit is not None or self.restart_asked or _session_ending():
            if card is not None:                          # the question no longer stands
                self._detached_card = None
                card.drop()
            return False
        if card is not None:                              # a second close (✕ again) while it asks: Quit
            card.close()
            return True
        if self._detached_answered:
            return False
        detached = jobs_module.detached_at_quit(self._jobs)
        if not detached:
            return False
        from app.qt import confirm
        for other in self.findChildren(confirm.Confirm):  # R35-1: a card already open is dropped, as a close drops it
            if other.answer is None:
                other.drop()
        self._hold_for_sheet()
        labels = strings.QUIT_DETACHED_JOIN.join(dict.fromkeys(j.label for j in detached))
        stoppable = any(j.kind in jobs_module.STOPPABLE_AT_QUIT for j in detached)   # Connect alone: Quit alone
        body = strings.QUIT_DETACHED_BODY if stoppable else ""
        if any(j.kind == jobs_module.CONNECT_KIND for j in detached):       # Connect is never stopped from here
            body = f"{body} {strings.QUIT_DETACHED_CONNECT}".strip()
        self._detached_card = confirm.ask(
            self, strings.QUIT_DETACHED_TITLE.format(labels=labels), body,
            strings.QUIT_DETACHED_STOP if stoppable else None, strings.QUIT_DETACHED_STOP_TIP,
            no=strings.QUIT_DETACHED_QUIT, no_tip=strings.QUIT_DETACHED_QUIT_TIP, default_no=True, danger=True,
            on_answer=self._detached_answer)
        return True

    def _hold_for_sheet(self):
        """While the sheet asks: nothing new starts — gated jobs held, the chores' timers taken back (no new upkeep
        helper the stop wouldn't know), the duties' controls held. Not the quit's start: E20's wait counts from the
        answer."""
        try:
            self.services.hold_starting()
        except Exception as e:
            applog.log("shell", f"holding at the close: {e}")
        if self.duties is not None:
            self.duties.generate.hold(strings.QUIT_CLOSING_TIP)
            self.duties.sheet.hold(strings.QUIT_CLOSING_TIP)
            self.duties.cards.hold(strings.QUIT_CLOSING_TIP)

    def _detached_answer(self, stop):
        self._detached_card = None
        self._detached_answered = True
        if stop:
            # Stop and quit: the registry's live upkeep cancelled — its owner ends its own child through the Popen it
            # holds (at once: no worker, so no close can pass it). Connect is never stopped (`jobs.CONNECT_KIND`).
            try:
                asked = jobs_module.stop_at_quit(self.services.registry)
                if asked:
                    applog.log("shell", f"stopped at the close: {len(asked)} helper(s)")
            except Exception as e:
                applog.log("shell", f"stopping at the close: {e}")
        QTimer.singleShot(0, self.close)                  # the close as before (never inside the card's close)
    # --- end row 35

    def _moves_pending(self):
        """W3.1a: moves the window gave that the store hasn't taken yet (04 §4.5: closing waits for them)."""
        writer = getattr(self.services, "writer", None)
        try:
            return writer is not None and getattr(self, "moves", None) is not None and writer.pending() > 0
        except Exception:
            return False

    def closeEvent(self, event):
        if self._ask_detached():                          # row 35: what outlives the window, named — first
            event.ignore()
            return
        moves = getattr(self, "moves", None)
        if moves is not None:
            moves.close()                                 # a drag running at the close is let go
        qcovers.stop_scan()                               # --- W3.2 Q6: the disk scan stops between titles
        if getattr(self, "_fetcher", None) is not None:  # --- W3.2 L3: the online covers stop (between requests)
            self._fetcher.stop(timeout=0)
            if qcovers.fetcher() is self._fetcher:
                qcovers.use_fetcher(None)
        if self._quit == "waiting" or (self._quit is None and (jobs_module.waits_at_quit(self._jobs)
                                                               or self._replan_settling() or self._moves_pending())):
            event.ignore()                                # E20: what can't stop part-way ends first
            self._finish_first()
            return
        if moves is not None:                             # round 8: a write landing after the window is gone (the quit's
            moves.unwire()                                # last moves) tells no one — never a deleted relay
        self.closing.emit()                               # single instance stops listening before the window hides
        from app.qt import windows
        windows.close_all(self)                           # W3.4 AD4-4: the ported windows' own closes run (their clean-up)
        self._poll.stop()
        self._look_tick.stop()                            # --- SRC W1b: a look under way stops between files
        if self.looks is not None:
            self.looks.close()
        self.bridge.stop()                                # the quit's service callbacks reach no slot from here
        bridge.drop_answers()                             # ... nor a worker's answer still on its way (row 55)
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


def _session_ending():
    """Row 35: Windows is logging off or shutting down (the session manager's close): no sheet waits on it."""
    app = QApplication.instance()
    try:
        return bool(app is not None and app.isSavingSession())
    except Exception:
        return False


# --- W3.2 B: how the window wakes (IK0-5, L3.1-4) ----------------------------------------------------------------- #
def _plan_key(numbers):
    """W3.2 S2: the plan file's key as the reader's numbers last read it (`moves.Numbers.plan_key`), else None."""
    key = getattr(numbers, "plan_key", None)
    try:
        return key() if callable(key) else None
    except Exception:
        return None


def library_lookout(store, wake):
    """The library reader's `watch` (`LibraryReader(watch=library_lookout)`, through `moves.open_library`'s reader
    keywords where the window builds its library): called on the reader's thread once the store can be used, never
    the window's. The tree watch on the language's tier folders (hato's drop folder is under NOW's) and the store's
    bell (any process's commit), both waking the reader's own `wake`; no copy watch (the helper keeps the copy) and
    no hourly round (the Content Manager's). Closed with the reader (its stop: the window's close, a library switch).
    -> an opened `library_watch.Lookout`."""
    from app import library_store, library_watch
    return library_watch.Lookout(store.data_dir, under=list(library_store.WALK_FOLDERS),   # + the content folder (SRC)
                                 db_path=store.db_path, wake=wake).open()
# --- end W3.2 B


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


# --- W3.2 P0: the library main() opens (W3.1a's R3-L7) -------------------------------------------------------------- #
def _set_estimates(reader, estimates):
    """New arrivals' numbers to the reader open now (any thread); none with no reader or one without them."""
    set_estimates = getattr(reader, "set_estimates", None)
    if set_estimates is not None:
        set_estimates(estimates)


def _stopped(reader):
    stopped = getattr(reader, "stopped", None)
    return bool(stopped()) if stopped is not None else False


def library_for(language, settings, freeze_gc=False):
    """`language`'s library as the window reads and writes it: the reader and its numbers on one opener
    (`moves.open_library`; the plan's staleness checked against the settings as they are at each check, the first
    screen from `window_cache_<lang>.json`), the writer on the same opener, its journal the language's. Nothing started
    and nothing read here — no store opened, no file read: the window starts the reader after its first frame
    (`library_after_frame`) and the writer with its drag (`start`, the journal's replay), main the numbers after the
    first frame too (`Services.load_numbers`).
    The opener's role is "window": it opens a store that is there and never builds, migrates or repairs one — no store
    yet (a fresh install, a 2.x library not migrated), one being migrated, read-only or damaged opens in the reader's
    mode for it, and the chores' helper (W3.5) builds or migrates it as 2.5 did. -> (reader, writer)."""
    from app.services import library_reader, moves, play
    feed = connect_feed(language, settings)                 # --- P4.1 L2: Connect's feed (row 4.1.10)
    _opener, numbers, reader = moves.open_library(
        language, check=moves.plan_check(language, lambda: settings_service.thaw(settings.get())),
        log=lambda line: applog.log("numbers", line),       # row 36: why *N new* waits, in the app's log
        cache_file=library_reader.cache_path(language), freeze_gc=freeze_gc,
        watch=library_lookout,                              # W3.2 B: woken by the bell + the tree watch (IK0-5)
        connect=feed.latest,                                # P4.1 L2: the stones from the status line's last look
        play=play.Looks(language),                          # row 55: ▶ only where its file is found
        coalesce=True)                                      # a4: a burst of commits is a few views a second
    _wake_on_feed(feed, reader)                             # P4.1 L2
    writer = moves.Writer(_opener, language, journal_file=moves.journal_path(language), numbers=numbers,
                          words=strings.MOVE_WORDS,
                          after_commit=connect_after_commit(language, settings))     # P4.1 L2 (W-A2)
    return reader, writer


# --- P4.1 L2: Connect in the window (W1: rows 4.1.10, 4.1.13; W-A1, W-A2, W-A5) ------------------------------------ #
_CONNECT_FEEDS = {}             # id(settings service) -> (a weak reference to it, {language: feed.Provider})
_CONNECT_FEEDS_LOCK = threading.Lock()      # P4.1 WF (adversary N5): two switch workers make one feed a language


def connect_feed(language, settings):
    """The window's one Connect feed for `language` (`app/connect/feed.Provider`): the status line's provider ticks it
    (`Services._provide_lines`: every 3 s while Connect is on, one stamp a look) and the library reader builds its
    stones from its last look (`latest`). One per settings service and language, so a language switch back finds the
    same one; it holds the settings service weakly (a test's windows let theirs go)."""
    import weakref
    from app.connect import feed as connect_feed_module
    with _CONNECT_FEEDS_LOCK:
        hit = _CONNECT_FEEDS.get(id(settings))
        if hit is None or hit[0]() is not settings:
            try:
                ref = weakref.ref(settings)
            except TypeError:                               # a stand-in that can't be held weakly: its own feed
                return connect_feed_module.Provider(language, settings.get)
            for k in [k for k, (r, _f) in _CONNECT_FEEDS.items() if r() is None]:
                del _CONNECT_FEEDS[k]                       # the windows gone
            hit = _CONNECT_FEEDS[id(settings)] = (ref, {})
        ref, feeds = hit
        if language not in feeds:
            def get():
                held = ref()
                return held.get() if held is not None else {}
            feeds[language] = connect_feed_module.Provider(language, get)
        return feeds[language]


def _wake_on_feed(feed, reader):
    """A new Feed wakes `reader` (the reader open now; held weakly: a reader a language switch let go is freed)."""
    import weakref
    ref = weakref.ref(reader)

    def wake():
        held = ref()
        if held is not None:
            held.refresh()
    feed.on_change = wake


def connect_after_commit(language, settings):
    """The window's writer's `after_commit(change, op)` (W-A2, row 4.1.6's rule): after every write the store
    committed — a move into the top 20, an ask (*Mine now*, *Mine this*, *Mine it too*), a line moved — one look on
    the writer's thread (`window_link.Link.after_change`: read-only), and Connect kicked when it has something unread.
    One `Link` per writer: it remembers what it kicked for."""
    from app.connect import window_link
    link = window_link.Link(language, lambda: settings_service.thaw(settings.get()))

    def after_commit(_change, _op):
        link.after_change()
    after_commit.link = link
    return after_commit
# --- end P4.1 L2


def open_services(settings=None, freeze_gc=False, **kw):
    """The window's services with settings.json's `target_language`'s library and writer (`library_for`), and the same
    for another language at a switch (`Services.library_for`). `freeze_gc`: the reader's (the window process's, never a
    test's). -> Services."""
    settings = settings if settings is not None else settings_service.SettingsService()
    language = settings.get().get("target_language") or "ja"
    reader, writer = library_for(language, settings, freeze_gc)
    services = Services(settings=settings, library=reader, writer=writer,
                        library_for=lambda other: library_for(other, settings, freeze_gc), **kw)
    services.library_after_frame = True      # its first-screen cache read and first feed read never in the first frame
    return services
# --- end W3.2 P0 ---------------------------------------------------------------------------------------------------- #


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
    from app.qt import start_gate
    if not start_gate.gate(app):                      # W3.5: the 2.x import, the refusals, the merge — before the store
        instance.release()
        return 0
    # W3.2 P0: the library and its writer (nothing read yet). A4 P-gil: the reader freezes Python's collector after each
    # view (a full collection walking the library held the window 40-75 ms at 20,000 files); its stop thaws it, so a
    # library a language switch let go is still freed (`library_reader`'s *Python's collector*)
    restarted = restart_mark()                        # alpha 4 M6: *Restart now*'s start (`relaunch`)
    try:
        services = open_services(freeze_gc=True)
        services.restarted = restarted
        failed = None
    except Exception as e:                            # (AD0-12) the window opens without its library, and says so
        applog.log("shell", f"the library couldn't be opened: {e!r}\n{traceback.format_exc()}")
        services = Services()
        services.restarted = restarted
        failed = services.library_failed = strings.LIBRARY_NOT_OPENED
    hud.mark("services")
    window = open_window(app, services)
    if failed:
        window.say(failed)
    connect_instance(window, instance)
    probe_file = os.environ.get("SURASURA_SHELL_PROBE")
    # (measuring, the HUD keeps its overlay off: the overlay's own first show would be timed as the window's)
    meter = hud.Hud(window, overlay=not probe_file).start() if hud.wanted(argv) else None
    if probe_file:                                    # tests/qt/measure_shell.py: shown without taking the keyboard
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        hud.Probe(window, probe_file, hud=meter)
    window.first_frame.connect(window.start_duties)  # W3.5: the duties after the first paint
    window.first_frame.connect(services.load_numbers)  # W3.2 P0: the plan's numbers after it too
    window.show_first()
    hud.mark("shown")
    try:
        code = app.exec()
    finally:
        try:
            services.shutdown(release=instance.release)   # the claim goes before the store's close trigger
        finally:
            instance.release()                            # (once: done already unless the quit failed before it)
            if window.restart_asked:                      # *Restart now* (`ShellWindow.restart`): the new start only
                relaunch(argv)                            # once the store's close has ended (or its wait ran out, B2-4)
            if meter is not None:                         # the HUD's native filter taken off here, on the GUI thread:
                try:                                      # left to the collector, it can go on a worker, where Qt's
                    meter.stop()                          # removal misses and the next message crashes (0xC0000005)
                except Exception as e:
                    applog.log("shell", f"the HUD at quit: {e!r}")
            quiet_exit(gone=(window,))                    # W3.4: nothing of Qt's or a worker's left for the teardown
    return code


SESSION_JOB = "anki-session"        # IK-6: the window's start look at Anki, a registry job (`jobs.RESOURCES`)


# alpha 4 M6: the mark `relaunch` hands the new start (its environment, never its logged arguments): that window's
# look at Anki never opens it — *Open Anki for me* is for a start you made, not a restart (you may have closed Anki)
RESTARTED = "SURASURA_RESTARTED"


def restart_mark():
    """Was this start *Restart now*'s (`relaunch`'s mark)? Read once and taken out of the environment, so nothing this
    process starts inherits it (review F-5)."""
    return os.environ.pop(RESTARTED, None) == "1"


def relaunch(argv):
    """The same program started again, detached (laptop fixes row 15: *Restart now*): the frozen program with its own
    arguments, or this Python with the script `argv` names (app_entry.py from source), from the same folder, marked
    `RESTARTED` (alpha 4 M6). -> the Popen, or None (logged: the window just doesn't come back)."""
    import subprocess
    if getattr(sys, "frozen", False):
        args = [sys.executable] + list(argv[1:])
    elif os.path.abspath(argv[0]) == os.path.abspath(__file__):        # `python -m app.qt.shell`
        args = [sys.executable, "-m", "app.qt.shell"] + list(argv[1:])
    else:
        args = [sys.executable, os.path.abspath(argv[0])] + list(argv[1:])
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(args, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=(sys.platform != "win32"), env=dict(os.environ, **{RESTARTED: "1"}))
    except (OSError, ValueError) as e:
        applog.log("shell", f"restart: the new start failed: {e!r}")
        return None


def quiet_exit(workers_ms=QUIT_WORKERS_MS, join_s=QUIT_THREAD_JOIN_S, gone=()):
    """(The quit's last step, after the window closed and the services stopped.) The closed windows' deferred deletes
    run now — never during Python's teardown, the exit crash row 2 measured — then the thread pool's workers and the
    ported 順 windows' own threads (`junban-*`) are waited for, each a bounded wait. The windows in `gone` (the main
    window: its Settings page and the ported windows with it) are deleted once the workers ended, never left for
    Python's teardown: there, after the QApplication, the mounted Settings page crashed the exit (0xC0000005, about
    1 run in 80 under load; GitHub's #97). -> True when everything ended."""
    from PyQt6.QtCore import QCoreApplication
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    ended = bridge.wait_for_workers(workers_ms)
    if gone and ended:                                    # (a worker still running: nothing deleted under it)
        for win in gone:
            try:
                win.deleteLater()
            except RuntimeError:                          # deleted already
                pass
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        ended = bridge.wait_for_workers(workers_ms)       # what a deletion started (a quit before the first frame:
                                                          # the stones' release can start their build)
    for thread in threading.enumerate():
        if thread.name.startswith("junban-") and thread is not threading.current_thread():
            thread.join(join_s)
            ended = ended and not thread.is_alive()
    return ended


if __name__ == "__main__":
    sys.exit(main())
