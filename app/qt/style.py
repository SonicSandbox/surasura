"""The window's look, set on the QApplication before the first paint (W2.1; the window's spec 05 §5.3, §5.5, §5.11,
§5.12; the python-desktop stack pack's window layer).

- **One stylesheet per theme × text size**, generated here from `app/theme.py` (Qt stylesheets have no variables): every
  size × the text size, fonts in fractional points. Cached: a theme or text size is worked out once.
- **Fusion, pinned**, under a `QProxyStyle` (`SurasuraStyle`) that paints every indicator the stylesheet leaves to the
  style — a check box, a radio, a menu's check, an item view's check, the focus ring — in the theme's colours, so no
  control is ever painted by Windows (the stack pack's first trap: a Windows-blue radio in a themed window).
- **The dark `QPalette`** from `theme.palette()`, as well as the stylesheet: Windows 10's dark title bar follows the
  palette (measured), links take their colour from it, and Fusion draws the arrows with it.
- Set on the **QApplication**, never on a window: a dialog or a menu made later is themed too.

No colour is spelled here (tests/qt/test_style.py reads this folder): every one comes from `app/theme.py`.
"""
import time
from functools import lru_cache

from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QApplication, QFrame, QProxyStyle, QStyle, QStyleFactory, QWidget

from app import theme

PT_PER_PX = 0.75                       # Qt's logical 96 dpi: 13 px = 9.75 pt (the device-pixel ratio scales both)

_state = {"theme": theme.DEFAULT_THEME, "text_size": theme.DEFAULT_TEXT_SIZE, "language": "ja",
          "generated_ms": None, "style": None, "app": None}


def qss_colour(value):
    """A theme colour for a stylesheet: `#rrggbb` as it is; CSS's `#rrggbbaa` as `rgba(…)` (Qt reads 8 hex digits
    alpha first)."""
    r, g, b, a = theme.parse(value)
    if a >= 1.0:
        return value
    return f"rgba({int(r)}, {int(g)}, {int(b)}, {round(a * 255)})"


def qcolor(value):
    r, g, b, a = theme.parse(value)
    return QColor(int(r), int(g), int(b), round(a * 255))


def iris_gradient(theme_name, vertical=False):
    stops = ", ".join(f"stop:{pos} {colour}" for pos, colour in theme.IRIS.get(theme_name, theme.IRIS["hb"]))
    end = "x2:0, y2:1" if vertical else "x2:1, y2:0"
    return f"qlineargradient(x1:0, y1:0, {end}, {stops})"


def point_size(role, text_size):
    px, _weight = theme.font(role, text_size)
    return round(px * PT_PER_PX, 3)


@lru_cache(maxsize=None)
def stylesheet(theme_name=theme.DEFAULT_THEME, text_size=theme.DEFAULT_TEXT_SIZE):
    """The one stylesheet for a theme at a text size (cached; ~0.1 ms the first time)."""
    t0 = time.perf_counter()
    c = {k: qss_colour(v) for k, v in theme.colours(theme_name).items()}
    fixed = {k: qss_colour(v) for k, v in theme.FIXED.items()}
    tip = theme.over(theme.FIXED["tooltip"], theme.colours(theme_name)["bg"])
    f = theme.text_factor(text_size)

    def px(n):
        return f"{round(n * f)}px"

    def font(role):
        size, weight = theme.font(role, text_size)
        return f"font-size: {round(size * PT_PER_PX, 3)}pt; font-weight: {weight};"

    iris = iris_gradient(theme_name)
    rules = f"""
/* the window's own parts (shell.py names them). Their dividing lines are separators, never borders: a border lands
   between device pixels at 125 / 175 % and smears over two rows; a separator's fill stays one crisp row */
QWidget#header {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {c['header-top-opaque']}, stop:1 {c['surface']}); }}
QLabel#wordsub {{ color: {c['ink-faint']}; {font('status-pill')} font-weight: 400; }}
QWidget#tabbar {{ background: {c['tab-bar']}; }}
QToolButton#tab {{ background: transparent; border: 0; border-bottom: 2px solid transparent; color: {c['ink-dim']};
  padding: {px(10)} {px(14)} {px(9)} {px(14)}; {font('tab')} }}
QToolButton#tab:hover {{ color: {c['ink']}; }}
QToolButton#tab:checked {{ color: {c['ink']}; border-bottom: 2px solid {iris}; }}
QToolButton#tab:focus {{ color: {c['ink']}; border: 2px solid {c['accent']}; border-radius: 6px;
  padding: {round(10 * f) - 2}px {round(14 * f) - 2}px {round(9 * f)}px {round(14 * f) - 2}px; }}
QWidget#footer {{ background: {c['surface']}; }}
QLabel#barline {{ color: {c['ink-dim']}; {font('footer')} font-weight: 400; }}
QLabel#bardot {{ color: {c['accent']}; {font('footer')} }}
QLabel#bardot[busy="false"] {{ color: {c['ink-faint']}; }}
QLabel#barfailure {{ color: {c['warn']}; {font('footer')} font-weight: 400; }}
QLabel#barmark {{ color: {c['ink-dim']}; {font('footer')} font-weight: 400; }}
QLabel#pagewaiting {{ color: {c['ink-faint']}; {font('body')} font-weight: 400; }}
QLabel#pagetitle {{ color: {c['ink']}; {font('page-heading')} }}
QFrame#separator {{ background: {c['line']}; border: 0; }}

/* buttons: .btn, .btn.primary, .btn.sm, .ib, the bar's chips */
QPushButton {{ background: {c['raised']}; color: {c['ink']}; border: 1px solid {c['line-hi']}; border-radius: 9px;
  min-height: {px(30)}; padding: 0 {px(13)}; {font('button')} }}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['generate-hover']}; }}
QPushButton:focus {{ border: 2px solid {c['accent']}; padding: 0 {round(13 * f) - 1}px; }}
QPushButton:disabled {{ color: {c['ink-faint']}; border-color: {c['line']}; }}
QPushButton[kind="primary"] {{ background: {iris}; color: {fixed['on-accent']}; border: 0; }}
QPushButton[kind="primary"]:focus {{ border: 2px solid {c['ink']}; }}
QPushButton[kind="chip"] {{ background: {c['bg']}; color: {c['ink-dim']}; border: 1px solid {c['line']}; border-radius: 7px;
  min-height: {px(22)}; padding: 0 {px(9)}; {font('status-pill')} }}
QPushButton[kind="chip"]:hover {{ color: {c['ink']}; border-color: {c['accent']}; }}
QToolButton {{ background: transparent; color: {c['ink-dim']}; border: 1px solid transparent; border-radius: 7px;
  padding: {px(4)}; }}
QToolButton:hover {{ background: {c['raised']}; border-color: {c['line-hi']}; color: {c['ink']}; }}
QToolButton:focus {{ border: 2px solid {c['accent']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* fields */
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ background: {c['bg']}; color: {c['ink']};
  border: 1px solid {c['line']}; border-radius: 9px; padding: {px(4)} {px(8)}; {font('input')}
  selection-background-color: {c['accent-deep']}; selection-color: {c['ink']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled {{ color: {c['ink-faint']}; }}
QComboBox {{ background: {c['raised']}; color: {c['ink']}; border: 1px solid {c['line-hi']}; border-radius: 7px;
  padding: {px(3)} {px(8)}; {font('select')} }}
QComboBox:hover, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: 0; width: {px(22)}; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['ink']}; border: 1px solid {c['line-hi']};
  selection-background-color: {c['raised']}; selection-color: {c['ink']}; outline: 0; }}

/* toggles: the indicators themselves are SurasuraStyle's (painted in the theme's colours) */
QCheckBox, QRadioButton {{ color: {c['ink']}; spacing: {px(8)}; {font('body')} font-weight: 400; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {c['ink-faint']}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: {px(16)}; height: {px(16)}; }}
QGroupBox {{ border: 1px solid {c['line']}; border-radius: 8px; margin-top: {px(14)}; padding-top: {px(6)}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: {px(10)}; color: {c['ink-dim']}; }}

/* scrolling, ranges, progress */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {c['line']}; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:vertical {{ min-height: 24px; }}
QScrollBar::handle:horizontal {{ min-width: 24px; }}
QScrollBar::handle:hover {{ background: {c['line-hi']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: 0; background: transparent; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSlider::groove:horizontal {{ background: {c['line']}; height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent-deep']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['accent']}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QProgressBar {{ background: {c['raised']}; border: 0; border-radius: 3px; max-height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: {iris}; border-radius: 3px; }}

/* lists and tables: rows are painted by their delegates (W2.2); these are the frames around them */
QAbstractItemView {{ background: transparent; color: {c['ink']}; border: 0; outline: 0;
  selection-background-color: {c['accent-wash']}; selection-color: {c['ink']}; }}
QHeaderView::section {{ background: {c['surface']}; color: {c['ink-dim']}; border: 0; border-bottom: 1px solid {c['line']};
  padding: {px(4)} {px(8)}; }}
QSplitter::handle {{ background: {c['line']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* menus, tabs a later screen may use, Qt's own tooltip (the shell shows its own bubble: tooltip.py) */
QMenu {{ background: {c['surface']}; color: {c['ink']}; border: 1px solid {c['line-hi']}; padding: 6px; {font('menu-item')} }}
QMenu::item {{ padding: {px(7)} {px(12)}; border-radius: 7px; }}
QMenu::item:selected {{ background: {c['raised']}; }}
QMenu::item:disabled {{ color: {c['ink-faint']}; }}
QMenu::separator {{ height: 1px; background: {c['line']}; margin: 4px 8px; }}
QMenu::indicator {{ width: {px(14)}; height: {px(14)}; }}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ background: transparent; color: {c['ink-dim']}; border: 0; border-bottom: 2px solid transparent;
  padding: {px(10)} {px(14)} {px(9)} {px(14)}; {font('tab')} }}
QTabBar::tab:selected {{ color: {c['ink']}; border-bottom: 2px solid {iris}; }}
QToolTip {{ background: {tip}; color: {c['ink']}; border: 1px solid {c['line-hi']}; border-radius: 8px;
  padding: 7px 10px; {font('tooltip')} }}
"""
    _state["generated_ms"] = (time.perf_counter() - t0) * 1000
    return rules


class SurasuraStyle(QProxyStyle):
    """Fusion, with every indicator painted in the theme's colours and the tooltip's timing (05 §5.4)."""

    def __init__(self, theme_name=theme.DEFAULT_THEME):
        super().__init__(QStyleFactory.create("Fusion"))
        self.set_theme(theme_name)

    def set_theme(self, theme_name):
        self.colours = {k: qcolor(v) for k, v in theme.colours(theme_name).items()}
        self.on_accent = qcolor(theme.FIXED["on-accent"])

    # --- hints ---------------------------------------------------------------------------------------------- #
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return theme.MOTION["tooltip-delay"]
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return theme.MOTION["tooltip-again-within"]
        return super().styleHint(hint, option, widget, returnData)

    # --- indicators ----------------------------------------------------------------------------------------- #
    def drawPrimitive(self, element, option, painter, widget=None):
        PE = QStyle.PrimitiveElement
        if element in (PE.PE_IndicatorCheckBox, PE.PE_IndicatorItemViewItemCheck):
            self._check_box(option, painter)
            return
        if element == PE.PE_IndicatorRadioButton:
            self._radio(option, painter)
            return
        if element == PE.PE_IndicatorMenuCheckMark:
            self._menu_check(option, painter)
            return
        if element == PE.PE_FrameFocusRect:
            self._focus_ring(option, painter)
            return
        super().drawPrimitive(element, option, painter, widget)

    def _state(self, option):
        S = QStyle.StateFlag
        st = option.state
        return (bool(st & S.State_Enabled), bool(st & S.State_On), bool(st & S.State_NoChange),
                bool(st & S.State_MouseOver))

    def _check_box(self, option, painter):
        enabled, on, partial, hover = self._state(option)
        c = self.colours
        r = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        side = min(r.width(), r.height())
        r = QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        filled = (on or partial) and enabled
        border = c["accent"] if (filled or (hover and enabled)) else (c["line-hi"] if enabled else c["line"])
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(c["accent"] if filled else (c["surface"] if enabled else c["bg"]))
        painter.drawRoundedRect(r, side * 0.25, side * 0.25)
        mark = self.on_accent if filled else c["ink-faint"]
        pen = QPen(mark, max(1.6, side / 8.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if partial:
            painter.drawLine(QPointF(r.left() + side * 0.28, r.center().y()), QPointF(r.right() - side * 0.28, r.center().y()))
        elif on:
            path = QPainterPath(QPointF(r.left() + side * 0.25, r.top() + side * 0.53))
            path.lineTo(QPointF(r.left() + side * 0.43, r.top() + side * 0.71))
            path.lineTo(QPointF(r.left() + side * 0.76, r.top() + side * 0.32))
            painter.drawPath(path)
        painter.restore()

    def _radio(self, option, painter):
        enabled, on, _partial, hover = self._state(option)
        c = self.colours
        r = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        side = min(r.width(), r.height())
        r = QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ring = c["accent"] if ((on or hover) and enabled) else (c["line-hi"] if enabled else c["line"])
        painter.setPen(QPen(ring, 1.0 if not on else max(1.5, side / 10.0)))
        painter.setBrush(c["surface"] if enabled else c["bg"])
        painter.drawEllipse(r)
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(c["accent"] if enabled else c["ink-faint"])
            dot = side * 0.5
            painter.drawEllipse(QRectF(r.center().x() - dot / 2, r.center().y() - dot / 2, dot, dot))
        painter.restore()

    def _menu_check(self, option, painter):
        enabled, on, _p, _h = self._state(option)
        if not on:
            return
        r = QRectF(option.rect)
        side = min(r.width(), r.height())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self.colours["accent"] if enabled else self.colours["ink-faint"], max(1.6, side / 8.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        x, y = r.center().x() - side / 2, r.center().y() - side / 2
        path = QPainterPath(QPointF(x + side * 0.2, y + side * 0.53))
        path.lineTo(QPointF(x + side * 0.42, y + side * 0.74))
        path.lineTo(QPointF(x + side * 0.8, y + side * 0.3))
        painter.drawPath(path)
        painter.restore()

    def _focus_ring(self, option, painter):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(self.colours["accent"], 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(option.rect).adjusted(1, 1, -1, -1), 4, 4)
        painter.restore()


def make_palette(theme_name):
    """The dark QPalette (05 §5.11) from theme.palette(): every group, the disabled one dimmed."""
    pal = QPalette()
    roles = dict(theme.palette(theme_name))
    disabled = roles.pop("DisabledText")
    for role, value in roles.items():
        pal.setColor(getattr(QPalette.ColorRole, role), qcolor(value))
    if hasattr(QPalette.ColorRole, "Accent"):                       # Qt 6.6+: what Fusion fills a checked control with
        pal.setColor(QPalette.ColorRole.Accent, qcolor(theme.colours(theme_name)["accent"]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, qcolor(disabled))
    return pal


def app_font(text_size, language="ja", script=None):
    """The application's font: Segoe UI, then the language's own family (Han characters take its shapes), at the body
    size × the text size, in fractional points."""
    f = QFont()
    f.setFamilies(list(theme.font_families(language, script)))
    f.setPointSizeF(point_size("body", text_size))
    return f


def apply(app, theme_name=None, text_size=None, language=None, script=None):
    """Set the look on the QApplication: Fusion under SurasuraStyle, the dark palette, the font and the stylesheet.
    Call it before the first window is shown (and again for a live switch). -> milliseconds it took."""
    t0 = time.perf_counter()
    theme_name = theme_name if theme_name in theme.THEMES else theme.DEFAULT_THEME
    text_size = text_size if text_size in theme.TEXT_SIZES else theme.DEFAULT_TEXT_SIZE
    language = language or _state["language"]
    # The colour scheme, asked for on purpose: Windows 10's caption follows it, not the palette (P-title, W2.1 row 0:
    # the same dark palette under Light drew a white bar). Every theme is dark (01 §1.2 th).
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme") and hints.colorScheme() != Qt.ColorScheme.Dark:
        hints.setColorScheme(Qt.ColorScheme.Dark)
        _state["asked_dark"] = True                  # (offscreen keeps answering Unknown: the ask is what's recorded)
    # One SurasuraStyle per application, kept here: under a stylesheet `app.style()` answers Qt's stylesheet wrapper,
    # not the style beneath it, and replacing the style a live stylesheet wraps brings the process down.
    ours = _state.get("style")
    if ours is not None and not sip.isdeleted(ours) and _state.get("app") is app:
        ours.set_theme(theme_name)
    else:
        ours = SurasuraStyle(theme_name)
        _state.update(style=ours, app=app)
        app.setStyle(ours)
    app.setPalette(make_palette(theme_name))
    app.setFont(app_font(text_size, language, script))
    app.setStyleSheet(stylesheet(theme_name, text_size))
    _state.update(theme=theme_name, text_size=text_size, language=language)
    return (time.perf_counter() - t0) * 1000


def current():
    """(theme, text size, language) as last applied."""
    return _state["theme"], _state["text_size"], _state["language"]


def colours():
    """The applied theme's colours by name (theme.colours)."""
    return theme.colours(_state["theme"])


def separator(parent=None, vertical=False):
    """A plain separator (the stack pack: a QFrame with a frameShape paints its own palette frame over the stylesheet's
    background): no frameShape, a fixed 1 px, the `line` colour from the stylesheet."""
    sep = QFrame(parent)
    sep.setObjectName("separator")
    if vertical:
        sep.setFixedWidth(1)
    else:
        sep.setFixedHeight(1)
    return sep


def styled(widget, name):
    """Name a plain QWidget for the stylesheet and let it paint its own background (QWidget needs the attribute)."""
    widget.setObjectName(name)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return widget
