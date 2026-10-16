"""The window's look, set on the QApplication before the first paint (W2.1; the window's spec 05 §5.3, §5.5, §5.11,
§5.12; the python-desktop stack pack's window layer).

- **One stylesheet per theme × text size**, generated here from `app/theme.py` (Qt stylesheets have no variables): every
  size × the text size, fonts in fractional points. Cached: a theme or text size is worked out once.
- **Fusion, pinned**, under a `QProxyStyle` (`SurasuraStyle`) that paints every indicator the stylesheet leaves to the
  style — a check box, a radio, a menu's check, an item view's check, the focus ring — in the theme's colours, so no
  control is ever painted by Windows (the stack pack's first trap: a Windows-blue radio in a themed window).
- **The dark `QPalette`** from `theme.palette()`, as well as the stylesheet: links take their colour from it, and
  Fusion draws the arrows with it. **The dark colour scheme**, asked for on every apply: Windows 10's caption follows
  the scheme, not the palette (P-title, W2.1 row 0: the same dark palette under Light drew a white bar).
- Set on the **QApplication**, never on a window: a dialog or a menu made later is themed too.

No colour is spelled here (tests/qt/test_style.py reads this folder): every one comes from `app/theme.py`.
"""
import time
from functools import lru_cache

from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QFrame, QProxyStyle, QStyle, QStyleFactory

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
    iris = theme.IRIS.get(theme_name, theme.IRIS[theme.DEFAULT_THEME])
    stops = ", ".join(f"stop:{pos} {colour}" for pos, colour in iris)
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
QWidget#header {{ background: {c['frame']}; }}
QLabel#wordsub {{ color: {c['ink-dim']}; {font('status-pill')} font-weight: 400; }}
QWidget#tabbar {{ background: {c['frame']}; }}
QToolButton#tab {{ background: transparent; border: 0; border-bottom: 2px solid transparent; color: {c['ink-dim']};
  padding: 10px 14px 9px 14px; {font('tab')} }}
QToolButton#tab:hover {{ color: {c['ink']}; }}
QToolButton#tab:checked {{ color: {c['ink']}; }}
QToolButton#tab:focus {{ color: {c['ink']}; border: 2px solid {c['accent']}; border-radius: 6px;
  padding: 8px 12px 9px 12px; }}
QWidget#footer {{ background: {c['frame']}; }}
QLabel#barline {{ color: {c['ink-dim']}; {font('footer')} font-weight: 400; }}
QLabel#barfailure {{ color: {c['warn']}; {font('footer')} font-weight: 400; }}
QLabel#barmark {{ color: {c['ink-dim']}; {font('footer')} font-weight: 400; }}
QLabel#journeydot {{ color: {c['accent']}; {font('badge')} }}
QLabel#pagewaiting {{ color: {c['ink-dim']}; {font('body')} font-weight: 400; }}
QLabel#pagetitle {{ color: {c['ink']}; {font('page-heading')} }}
QFrame#separator {{ background: {c['frame-edge']}; border: 0; }}

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
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ background: {c['cut']}; color: {c['ink']};
  border: 1px solid {c['line']}; border-radius: 9px; padding: {px(4)} {px(8)}; {font('input')}
  selection-background-color: {c['accent-deep']}; selection-color: {c['ink']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled {{ color: {c['ink-faint']}; }}
QComboBox {{ background: {c['raised']}; color: {c['ink']}; border: 1px solid {c['line-hi']}; border-radius: 7px;
  padding: {px(3)} {px(8)}; {font('select')} }}
QComboBox:hover, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: 0; width: {px(22)}; }}
QComboBox QAbstractItemView {{ background: {c['overlay']}; color: {c['ink']}; border: 0;
  border-top: 1px solid {c['overlay-edge-top']}; border-bottom: 1px solid {c['overlay-edge-bottom']};
  selection-background-color: {c['overlay-hover']}; selection-color: {c['ink']}; outline: 0; }}

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

/* --- W2.2: the first screens (screens.py); their rows are painted by rows.py --- */
QLabel#currentheading {{ color: {c['ink']}; {font('current-heading')} }}
QLabel#pageheading {{ color: {c['ink']}; {font('page-heading')} font-weight: 700; }}
QLabel#helpmark {{ color: {c['ink-faint']}; border: 1px solid {c['line-hi']}; border-radius: {px(8)};
  min-width: {px(16)}; max-width: {px(16)}; min-height: {px(16)}; max-height: {px(16)}; {font('key-hint')} }}
QLabel#helpmark:hover {{ color: {c['ink']}; border-color: {c['accent']}; }}
QLabel#statebar {{ color: {c['ink-dim']}; background: {c['raised']}; border-radius: 7px; padding: {px(5)} {px(10)};
  {font('row-sub')} }}
QListView#rows {{ background: {c['bg']}; border: 0; }}
QListView#rows:focus {{ border: 0; }}
/* --- end W2.2 --- */

/* menus, tabs a later screen may use, Qt's own tooltip (the shell shows its own bubble: tooltip.py) */
QMenu {{ background: {c['overlay']}; color: {c['ink']}; border: 0; border-top: 1px solid {c['overlay-edge-top']};
  border-bottom: 1px solid {c['overlay-edge-bottom']}; padding: 6px; {font('menu-item')} }}
QMenu::item {{ padding: {px(7)} {px(12)}; border-radius: 7px; }}
QMenu::item:selected {{ background: {c['overlay-hover']}; }}
QMenu::item:disabled {{ color: {c['overlay-ink-faint']}; }}
QMenu::separator {{ height: 2px; margin: 4px 8px; background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
  stop:0 {c['groove']}, stop:0.5 {c['groove']}, stop:0.51 {c['groove-lip']}, stop:1 {c['groove-lip']}); }}
QMenu::indicator {{ width: {px(14)}; height: {px(14)}; }}
QTabWidget::pane {{ border: 0; }}
/* --- W3.2 Q2: Goal's sheet (goal_sheet.py: its face, heading and tiles are painted) --- */
QScrollArea#goalsheetscroll {{ background: transparent; border: 0; }}
QWidget#goalsheetbody {{ background: transparent; }}
QToolButton#goalsheetclose, QToolButton#goaltilemore {{ color: {c['overlay-ink-dim']}; }}
/* --- end W3.2 Q2 --- */
QTabBar::tab {{ background: transparent; color: {c['ink-dim']}; border: 0; border-bottom: 2px solid transparent;
  padding: {px(10)} {px(14)} {px(9)} {px(14)}; {font('tab')} }}
QTabBar::tab:selected {{ color: {c['ink']}; border-bottom: 2px solid {iris}; }}
QToolTip {{ background: {tip}; color: {c['ink']}; border: 0; border-top: 1px solid {c['overlay-edge-top']};
  border-bottom: 1px solid {c['overlay-edge-bottom']}; border-radius: 8px;
  padding: 7px 10px; {font('tooltip')} }}
"""
    # --- M2.1: the toast's text and the small button (`.btn.sm`); the toast card paints itself (toast.py)
    rules += f"""
QLabel#toasttext {{ color: {c['ink']}; {font('body')} }}
QPushButton[size="sm"] {{ min-height: {px(24)}; padding: 0 {px(10)}; border-radius: 7px; {font('button-sm')} }}
QPushButton[size="sm"]:focus {{ padding: 0 {round(10 * f) - 1}px; }}
"""
    # --- W3.5: Generate's states, the update sheet's text, Needs you's update cards (looks to re-skin: duties.py)
    rules += f"""
QPushButton#generate[look="stale"] {{ border: 1px solid {c['generate-stale-glow']}; background: {c['generate-hover']}; }}
QPushButton#generate[look="failed"] {{ border: 1px solid {c['warn']}; }}
QPushButton#generate:focus {{ border: 2px solid {c['accent']}; }}
QLabel#sheetheading {{ color: {c['ink']}; {font('sheet-heading')} }}
QLabel#sheetline {{ color: {c['ink-dim']}; {font('body')} font-weight: 400; }}
QWidget#needscard {{ background: {c['slab']}; border: 0; border-top: 1px solid {c['line-hi']};
  border-bottom: 1px solid {c['groove']}; border-radius: {theme.RADII['r']}px; }}
QLabel#needstitle {{ color: {c['ink']}; {font('needs-title')} }}
"""
    # --- W3.2 Q5: Needs you's cards (needs.py): a line's find result — found ok, nothing amber
    rules += f"""
QLabel#needswhy {{ color: {c['warn']}; {font('body')} font-weight: 400; }}
QLabel#needswhy[found="true"] {{ color: {c['ok']}; }}
"""
    # --- end W3.2 Q5
    # --- W3.1a: the frame (frame.py) — the current tab's line is the vein (painted); the level ▾'s pop: its words,
    # Generate quiet (its stale and failed looks kept), *Open your journey* as a link
    rules += f"""
QLabel#popeyebrow {{ color: {c['overlay-ink-dim']}; {font('eyebrow')} letter-spacing: 1px; }}
QLabel#popband {{ color: {c['ink']}; {font('sheet-heading')} }}
QLabel#popline {{ color: {c['overlay-ink-dim']}; {font('body')} font-weight: 400; }}
QWidget#levelpop QPushButton#generate {{ background: transparent; color: {c['ink']};
  border: 1px solid {c['overlay-edge-top']}; }}
QWidget#levelpop QPushButton#generate:hover {{ background: {c['overlay-hover']}; border-color: {c['accent']}; }}
QWidget#levelpop QPushButton#generate[look="stale"] {{ border: 1px solid {c['generate-stale-glow']}; }}
QWidget#levelpop QPushButton#generate[look="failed"] {{ border: 1px solid {c['warn']}; color: {c['warn']}; }}
QWidget#levelpop QPushButton#generate:disabled {{ color: {c['overlay-ink-faint']}; }}
QWidget#levelpop QPushButton#generate:focus {{ border: 2px solid {c['accent']}; }}
QWidget#levelpop QPushButton#popjourney {{ background: transparent; color: {c['accent']}; border: 0; padding: 0;
  text-align: left; }}
QWidget#levelpop QPushButton#popjourney:hover {{ color: {c['ink']}; }}
QWidget#levelpop QPushButton#popjourney:focus {{ border: 2px solid {c['accent']}; padding: 0 {px(4)}; }}
"""
    # --- W3.4: the ported windows (windows.py, confirm.py, row 1's windows; looks to re-skin with W3.3's surfaces)
    rules += f"""
QLabel#windowstatus {{ color: {c['ink-dim']}; {font('footer')} font-weight: 400; }}
QLabel#windowheading {{ color: {c['ink']}; {font('dialog-title')} }}
QLabel#windowline {{ color: {c['ink-dim']}; {font('body')} font-weight: 400; }}
QLabel#confirmtitle {{ color: {c['ink']}; {font('dialog-title')} }}
QLabel#confirmline {{ color: {c['ink-dim']}; {font('body')} font-weight: 400; }}
QPushButton[kind="danger"] {{ background: {c['bad']}; color: {c['bad-type']}; border: 0; }}
QPushButton[kind="danger"]:focus {{ border: 2px solid {c['ink']}; }}
QListWidget#windowlist {{ background: {c['bg']}; border-radius: {theme.RADII['button']}px; padding: {px(4)}; }}
QLabel#ankistate {{ color: {c['ink-dim']}; {font('body')} font-weight: 600; }}
QLabel#ankistate[state="connected"] {{ color: {c['ok']}; }}
QLabel#ankistate[state="closed"] {{ color: {c['bad']}; }}
QLabel#ankiresolved {{ color: {c['accent']}; {font('footer')} font-weight: 600; }}
QLabel#ankiskipped {{ color: {c['bad']}; {font('footer')} font-weight: 600; }}
QLabel#ankitotal {{ color: {c['ink']}; {font('dialog-title')} }}
QLabel#ankidelta {{ color: {c['ok']}; {font('body')} font-weight: 600; }}
QPushButton[kind="primary"]:disabled {{ background: {c['raised']}; color: {c['ink-faint']}; }}
"""
    # W3.4 row 6 (順, Put Anki back): a window line's tone — a problem, a heads-up, a good answer — and a box that
    # overwrites the user's own field (danger), by token.
    rules += f"""
QLabel#windowline[tone="problem"] {{ color: {c['bad']}; }}
QLabel#windowline[tone="warning"] {{ color: {c['warn']}; }}
QLabel#windowline[tone="good"] {{ color: {c['ok']}; }}
QCheckBox[tone="danger"] {{ color: {c['bad']}; }}
"""
    # --- W3.4 row 5: Backfill's connection mark: its words carry the state, the colour repeats it (Tk: teal / red)
    rules += f"""
QLabel#backfillconnection[state="ok"] {{ color: {c['ok']}; }}
QLabel#backfillconnection[state="bad"] {{ color: {c['bad']}; }}
"""
    # --- W3.3 (Settings): the fields inside the controls (settings_controls.py paints the rest): a cut — the floor
    # darker than the slab, the top wall dark, the lower wall lit, no side edges — right-aligned figures in a number
    rules += f"""
QLineEdit#settingsfield {{ background: {c['cut']}; color: {c['ink']}; border: 0; border-top: 1px solid {c['cut-wall-top']};
  border-bottom: 1px solid {c['cut-wall-low']}; border-radius: {theme.RADII['r-sm']}px; padding: 0 {px(8)};
  min-height: {px(theme.SIZES['settings-num-h'])}; max-height: {px(theme.SIZES['settings-num-h'])}; {font('number-field')} }}
QLineEdit#settingsfield:focus {{ border: 2px solid {c['accent']}; padding: 0 {round(8 * f) - 2}px; }}
QLineEdit#settingsfield:disabled {{ color: {c['settings-ink-greyed']}; }}
QLabel#settingsaffix {{ color: {c['ink-dim']}; {font('number-field')} }}
QLabel#settingsaffix:disabled {{ color: {c['settings-ink-greyed']}; }}
"""
    # the page (settings_page.py; mock.html :585–645): the page on the ground (layer 0), the nav, the big search (a
    # cut), the section slabs (layer 0: the top hairline lit, the lower edge darker, no side edges; every other one
    # tinted), each text in its proven role (theme.SETTINGS_TEXT)
    t = {role: c[name] for role, name in theme.SETTINGS_TEXT.items()}
    sp = theme.SPACING
    rules += f"""
QWidget#settingspage {{ background: {c['content']}; }}
QWidget#settingsnav {{ background: {c['settings-nav']}; }}
QScrollArea#settingsscroll {{ background: {c['content']}; border: 0; }}
QWidget#settingsbody {{ background: {c['content']}; }}
QPushButton#settingsnavitem {{ background: transparent; color: {t['nav-unlit']}; border: 0; border-radius: 7px;
  text-align: left; min-height: 0; padding: {px(6)} {px(9)}; {font('settings-nav')} }}
QPushButton#settingsnavitem:hover {{ color: {t['nav-lit']}; border: 0; }}
QPushButton#settingsnavitem:checked {{ background: {c['settings-nav-lit']}; color: {t['nav-lit']}; }}
QPushButton#settingsnavitem:focus {{ border: 2px solid {c['accent']}; padding: {round(6 * f) - 2}px {round(9 * f) - 2}px; }}
QWidget#settingsfind {{ background: {c['cut']}; border: 0; border-top: 1px solid {c['cut-wall-top']};
  border-bottom: 1px solid {c['cut-wall-low']}; border-radius: {theme.RADII['button']}px; }}
QLineEdit#settingssearch {{ background: transparent; color: {t['search']}; border: 0; padding: 0;
  {font('settings-search')} }}
QLabel#settingskbd {{ color: {t['kbd']}; border: 1px solid {c['line-hi']}; border-radius: 4px; padding: 1px 5px;
  {font('key-hint')} }}
QWidget#settingsslab {{ background: {c['slab']}; border: 0; border-top: 1px solid {c['line-hi']};
  border-bottom: 1px solid {c['groove']}; border-radius: {theme.RADII['r']}px; }}
QWidget#settingsslab[tint="true"] {{ background: {c['settings-slab-tint']}; }}
QLabel#settingshead {{ color: {t['label']}; {font('settings-head')} }}
QLabel#settingslabel {{ color: {t['label']}; {font('settings-label')} }}
QLabel#settingssublabel {{ color: {t['sub-label']}; {font('settings-label')} font-weight: 500; }}
QLabel#settingslabel:disabled, QLabel#settingssublabel:disabled, QLabel#settingshelp:disabled {{
  color: {t['greyed']}; }}
QLabel#settingshelp {{ color: {t['help']}; {font('settings-help')} }}
QLabel#settingsvalue {{ color: {t['value']}; {font('body')} font-weight: 400; }}
QLabel#settingsgroup {{ color: {t['group']}; {font('group-label')}
  padding: {px(sp['settings-group'][0])} {px(sp['settings-group'][1])} {px(sp['settings-group'][2])} {px(sp['settings-group'][1])}; }}
QLabel#settingshint {{ color: {t['hint']}; {font('body')} font-weight: 400; }}
QPushButton#settingsmore {{ background: transparent; color: {t['more']}; border: 0; border-radius: 4px; min-height: 0;
  padding: 0; text-align: left; {font('settings-more')} }}
QPushButton#settingsmore:hover {{ border: 0; }}
QPushButton#settingsmore:focus {{ border: 2px solid {c['accent']}; padding: 0 2px; }}
"""
    # --- end W3.3
    # --- W3.2 Q1: New arrivals' tray (arrivals.py): its scroll and body on the tray's own face; its heading, ✕ and
    # *✓ All to Finished* in the overlay's ink
    rules += f"""
QScrollArea#trayscroll, QWidget#traybody {{ background: transparent; border: 0; }}
QLabel#trayheading {{ color: {c['ink']}; {font('tray-heading')} }}
QWidget#arrivalstray QToolButton {{ color: {c['overlay-ink-dim']}; border: 1px solid transparent; }}
QWidget#arrivalstray QToolButton:hover {{ background: {c['overlay-hover']}; color: {c['ink']}; }}
"""
    # --- end W3.2 Q1
    # --- W3.2 Q3: search your library (search.py: the cut and its results paint themselves) and + Add's paste card
    rules += f"""
QLineEdit#librarysearch {{ background: transparent; color: {c['ink']}; border: 0; padding: 0; {font('input')} }}
QLabel#searchkbd {{ color: {c['ink-faint']}; border: 1px solid {c['line']}; border-radius: 4px; padding: 1px 5px;
  {font('key-hint')} }}
QScrollArea#searchscroll, QWidget#searchbody {{ background: transparent; border: 0; }}
QLabel#searchgroup {{ color: {c['overlay-ink-faint']}; {font('eyebrow')} letter-spacing: 1px; }}
QLabel#searchnone {{ color: {c['overlay-ink-dim']}; {font('body')} font-weight: 400; }}
QLabel#searchmore {{ color: {c['overlay-ink-faint']}; {font('row-sub')} }}
QToolButton#searchact {{ color: {c['overlay-ink-dim']}; min-width: {px(24)}; min-height: {px(24)}; }}
QToolButton#searchact:hover {{ background: {c['overlay-hover']}; border-color: {c['overlay-edge-top']};
  color: {c['ink']}; }}
QToolButton#addstone, QToolButton#addstone:hover, QToolButton#addstone:pressed {{ background: transparent; border: 0;
  padding: 0; }}
QLabel#pasteheading {{ color: {c['ink']}; {font('dialog-title')} }}
QWidget#pastecard QLineEdit, QWidget#pastecard QPlainTextEdit {{ background: {c['overlay-cut']}; }}
"""
    # --- end W3.2 Q3
    _state["generated_ms"] = (time.perf_counter() - t0) * 1000
    return rules


class SurasuraStyle(QProxyStyle):
    """Fusion, with every indicator painted in the theme's colours (the bubble owns the tooltip's timing)."""

    def __init__(self, theme_name=theme.DEFAULT_THEME):
        super().__init__(QStyleFactory.create("Fusion"))
        self.set_theme(theme_name)

    def set_theme(self, theme_name):
        self.colours = {k: qcolor(v) for k, v in theme.colours(theme_name).items()}
        self.on_accent = qcolor(theme.FIXED["on-accent"])

    # --- hints ---------------------------------------------------------------------------------------------- #
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            # Qt's own wait before it asks for a tooltip: none — the bubble (tooltip.py) owns the 380 / 60 ms. Both
            # waiting doubled it to ~780 ms (W2.1 review A2).
            return 0
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


def _ask_dark(hints):
    if hasattr(hints, "setColorScheme"):                 # Qt 6.8+
        hints.setColorScheme(Qt.ColorScheme.Dark)


ask_dark = _ask_dark                                     # a seam: offscreen can't hold a scheme, so tests watch the ask


def apply(app, theme_name=None, text_size=None, language=None, script=None):
    """Set the look on the QApplication: Fusion under SurasuraStyle, the dark palette, the font and the stylesheet.
    Call it before the first window is shown (and again for a live switch). -> milliseconds it took."""
    t0 = time.perf_counter()
    theme_name = theme_name if theme_name in theme.THEMES else theme.DEFAULT_THEME
    text_size = text_size if text_size in theme.TEXT_SIZES else theme.DEFAULT_TEXT_SIZE
    language = language or _state["language"]
    # The colour scheme, asked for on purpose: Windows 10's caption follows it, not the palette (P-title, W2.1 row 0:
    # the same dark palette under Light drew a white bar). Every theme is dark (01 §1.2 th).
    # Asked every time, even when the system is dark already: an explicit ask holds when Windows later turns Light
    # (only following the system, the caption would turn white then: W2.1 review A4).
    ask_dark(app.styleHints())
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


def paint_overlay(p, rect, radius):
    """An overlay's card, flat (brief §4, layer 2): the slate-navy face, its top edge lit and its bottom edge darkest,
    never a side (rule 3). The stone's veins and light come in 3.1."""
    c = theme.colours(_state["theme"])
    r = QRectF(rect)
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qcolor(c["overlay"]))
    p.drawPath(path)
    # The two edges on whole device rows, never antialiased: at 125 / 150 / 175 % a 1 px logical edge would blend over
    # two rows (or never reach its colour), the smear the separators avoid (review L1-1).
    dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    edge = max(1, round(dpr)) / dpr
    bottom = round((r.top() + r.height()) * dpr) / dpr - edge
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setClipPath(path)
    p.fillRect(QRectF(r.left(), r.top(), r.width(), edge), qcolor(c["overlay-edge-top"]))
    p.fillRect(QRectF(r.left(), bottom, r.width(), edge), qcolor(c["overlay-edge-bottom"]))
    p.restore()


def separator(parent=None, vertical=False):
    """A plain separator (the stack pack: a QFrame with a frameShape paints its own palette frame over the stylesheet's
    background): no frameShape, a fixed 1 px, the frame's edge colour (`frame-edge`) from the stylesheet."""
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
