"""The shell: Surasura 3.0's main window (W2.1; the window's spec 01 §1.5 item 1, 05 §5.1–5.5, §5.9, §5.11–5.12).

The window, edge to edge under Windows' own title bar (n1); the header (the mark, the wordmark, the subline); the tabs
(Current · Finished · Needs you · Settings) over one page each; the bottom bar (what runs, the newest command-line
failure, the AnkiWeb mark and Connect's line when they exist). Each page shows its waiting state until its step builds
it (Current W2.2; Finished and Needs you W3.2; Settings W3.3), and the header's controls arrive with their features:
no control here does nothing (the wiring check, tests/qt/test_wiring.py).

What it holds is a view (02 §2.1): settings come from the settings service, jobs from the registry, the bar from the
status service, all through `bridge.py`; the window's size, place and tab live in `window_state.json` in this
install's local data folder, never in settings.json (S16). The look — theme and text size — is set on the
QApplication before the first paint (`open_window`), and changes live (`set_look`, P-text: W2.1 row 9).

App-wide: **Esc and the mouse's Back button** close every open overlay at once, else a secondary window, and **never
the main window** (✅ G1.2-2); Forward does nothing. Tooltips are the bubble (`tooltip.py`).

Run it: `python app_entry.py` on the 3.0 line (or `main()` here).
"""
import json
import os
import sys
import traceback

from PyQt6.QtCore import QEvent, QObject, QPointF, QRect, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFontMetrics, QGuiApplication, QIcon, QLinearGradient, QPainter
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                             QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from app import path_utils, theme
from app.qt import applog, bridge, hud, motion, strings, style, titlebar, toast, tooltip
from app.services import jobs as jobs_module
from app.services import settings as settings_service
from app.services import status as status_service

TABS = ("current", "finished", "needs", "settings")
STATE_FILE = "window_state.json"
STATE_VERSION = 1
DEFAULT_SIZE = (1280, 800)
POLL_MS = 500
# P-text (W2.1 row 9): a theme or text-size switch with the shell's widgets alive measured well under ~300 ms, so a
# change applies at once (G1.2-21). W3.3 measures it again with its Settings page alive; False = *Restart to apply*.
LIVE_LOOK = True


# --- the services the window calls ------------------------------------------------------------------------------- #
class Services:
    """The window's services, made once per window (the settings file is read here, before the first paint)."""

    def __init__(self, settings=None, registry=None, status=None):
        self.settings = settings if settings is not None else settings_service.SettingsService()
        self.registry = registry if registry is not None else jobs_module.JobRegistry()
        self.status = status if status is not None else status_service.StatusService(self.registry)

    def shutdown(self, timeout=2.0):
        """At quit, after the window is gone: pending settings written, jobs told (their `on_quit`)."""
        try:
            self.registry.quit(timeout)
        except Exception as e:
            applog.log("shell", f"jobs at quit: {e}")
        try:
            if not self.settings.flush(timeout):           # a held settings lock: the change is lost, so say so
                applog.log("shell", f"settings at quit: not written within {timeout} s (pending: "
                                    f"{self.settings.pending()})")
        except Exception as e:
            applog.log("shell", f"settings at quit: {e}")


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
        fm = QFontMetrics(self._font())
        return QSize(fm.horizontalAdvance("".join(strings.WORDMARK)) + 2, fm.height())

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
            page = self._waiting_page(name)
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
        self.show_status(services.status.snapshot())
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

        self._restore_state(read_state(self.state_file))

    # --- building ------------------------------------------------------------------------------------------- #
    def _build_header(self):
        header = style.styled(QWidget(), "header")
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
        row.addStretch(1)                                  # the header's controls arrive with their features (G-2)
        return header

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
            b = QToolButton(bar)
            b.setObjectName("tab")
            b.setText(label)
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
        row.addWidget(self.bar_dot)
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
        return footer

    def _apply_sizes(self):
        """The fixed heights that follow the text size (the stylesheet carries the rest)."""
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
        busy = bool(snap.lines)
        self.bar_dot.setProperty("busy", "true" if busy else "false")
        self.bar_dot.set_running(busy)
        self.bar_line.set_full(" · ".join(snap.lines))
        failure = snap.failure or ""
        self.bar_failure.set_full(strings.BAR_FAILURE_PREFIX + failure if failure else "")
        self.bar_failure.setVisible(bool(failure))
        self.bar_failure.setToolTip(strings.BAR_FAILURE_TIP + ("\n\n" + failure if failure else ""))
        self._logs_folder = snap.logs
        self.logs_button.setVisible(bool(failure) and bool(snap.logs))
        for label, value in ((self.bar_ankiweb, snap.ankiweb), (self.bar_connect, snap.connect)):
            label.setText(value or "")
            label.setVisible(bool(value))
        listed = len(snap.needs_you)
        unseen = sum(1 for e in snap.needs_you if not e.seen)
        needs = self.tab_buttons["needs"]
        name = strings.TABS["needs"][0]
        needs.setText(strings.TAB_WITH_COUNT.format(name=name, count=unseen) if unseen else name)
        needs.setVisible(listed > 0)
        if listed == 0 and needs.isChecked():
            self.show_tab("current")

    def _settings_written(self, keys):
        if "app_motion" in keys:
            motion.clock().mode.set_setting(self.services.settings.get().get("app_motion"))

    def open_logs(self):
        folder = self._logs_folder
        if not folder:
            return
        if sys.platform == "win32":
            bridge.run_in_worker(os.startfile, folder)    # the shell's open can take a moment: off the GUI thread
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

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

    def closeEvent(self, event):
        self.closing.emit()                               # single instance stops listening before the window hides
        self._poll.stop()
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
    window.show_first()
    hud.mark("shown")
    try:
        code = app.exec()
    finally:
        services.shutdown()
        instance.release()
    return code


if __name__ == "__main__":
    sys.exit(main())
