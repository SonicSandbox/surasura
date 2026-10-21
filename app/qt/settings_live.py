"""Settings' live rows (W3.3 P4; the RUNBOOK's P4 row; the register's S2, S4, S6, N6, N9, N12): the words and buttons
the page leaves to its slots (`SettingsPage.custom_row`) and the live parts of a few of its own rows.

`Live(page)` is made by the page. Every read runs on a worker (`bridge.run_in_worker`: the reads are the plain
functions at the top, Qt-free); the GUI thread only paints the answer, and repaints only what changed (S19).

- **Your setup:** five lines (`setup_lines`, Qt-free) from the settings and what the workers read — the known-words count,
  Anki's state, Connect's line from the status snapshot, the level and its readout, Junban / Backfill — each with
  *Change ›* (`page.reveal(section)`). A fact that can't be read leaves its part out: never a wrong number.
- **Level:** while *Automatic* is on, the slider shows `automation.level()`'s band (read on a worker, never written:
  S2); under it the readout (`readout`: ≈N words · N % *of your content* · about every N hours: S4) from
  `word_selection.band_previews` over the token store, read again when a level key, the library or the known words
  change; no store yet → no readout (the band names only).
- **Connection (Anki):** the emerald and its word (S6) — from the automation's last sync, or from *Check*'s look
  (`anki_connect.probe`, loopback) — and *Check* (also the status service's refresh). **Connections:** hato installed
  or not (its entry in the shared tools folder), jimaku *coming with hato*, AniList and More from Houseki *coming
  later*; no buttons (logos: package PL).
- **App:** *Text size*: the page saves it and *Restart now to apply?* is asked — *Restart now* closes the window the
  quit's way and the same program starts again on this tab (the shell's `restart`), *Later* says *Restart to apply*
  (`LIVE_TEXT_SIZE` on: the shell's `set_text_size` or `set_look` — it saves — then `page.restyle()`). *Motion* saved
  by the page and set on the motion clock at once.
  *Offer {version} again* beside *Update automatically* while `updates.skipped()` names a newer version. *Processing
  log* and *Data folder* open their folders; **Data credits** opens a layer-3 card (Esc, the mouse's Back, a click
  outside or *Done* close it; never modal: N6) with `credits.data_credits()` in read-only text, README's names it lacks
  (S11), and the licence line; the licence line also stands under the row (none → nothing).
- **Export:** each row asks what `exports.NEEDS` names — the format in a small layer-2 pop under its button, 2.4's
  warning through `confirm.ask`, the file with `QFileDialog` — then runs on a worker; the bar says the outcome in
  `exports`' words. One at a time; the row greyed while it runs.

What the bar says goes to the shell's bottom bar (`windows.say_in_bar`); a page with no shell shows it in the row's own
help line.
"""
import os

from PyQt6.QtCore import QObject, QPoint, QRectF, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from app import theme
from app.qt import applog, bridge, confirm, motion, shadow, strings, style, windows
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_strings as S
from app.services import settings as settings_service

SETUP = ("setup_known", "setup_anki", "setup_mining", "setup_level", "setup_cards")
EXPORTS = {"export_frequency_list": "frequency_list", "export_reading_words": "reading_words",
           "export_sentence_list": "sentence_list"}
COMING = {"jimaku": S.COMING_WITH_HATO, "anilist": S.COMING_LATER, "more_from_houseki": S.COMING_LATER}
PROBE_TIMEOUT = 3                    # s: *Check*'s look at AnkiConnect (a worker's)
# *Text size* applied live with the page alive took a median 813 ms (max 1056) on this desktop (P4, 2026-10-15): over
# G1.2-21's ~300 ms, so the row saves the size and says *Restart to apply* (the lead's ruling; M4.1 may bring it back).
# Laptop fixes row 15 (2026-10-21) kept it off — Current's, Finished's, Needs you's and the ported windows' cards set
# their sizes once, as they are built, and none has a restyle — and asks *Restart now to apply?* instead
LIVE_TEXT_SIZE = False


# --- the reads (each a worker's call; Qt-free) ----------------------------------------------------------------------- #
def read_known(automation, language):
    """(the known-words count or None, the automation's last sync state or None): the automation's own count for this
    language when it has one, else KnownWord.json counted (`anki_sync.count_known`)."""
    state = automation.state() if automation is not None else None
    sync = getattr(state, "sync", None)
    known = getattr(state, "known", None) if getattr(state, "language", None) == language else None
    if known is None:
        from app import anki_sync
        known = anki_sync.count_known(language)
    return known, sync


def read_status(status):
    """The status service's snapshot (its lock: a worker's)."""
    return status.snapshot()


def read_previews(settings, language):
    """Every band's numbers (`word_selection.band_previews`) over the token store, as the Rarity slider reads them; None
    while there is no store or nothing in it."""
    from app import token_index
    if not os.path.exists(token_index.store_path_for(language)):
        return None                                      # none yet: never one made by a look
    from app import analyzer, word_selection
    from app.path_utils import get_user_files_path
    from app.zh_script import effective
    logic = settings.get("logic") or {}
    sel = logic.get("selection") or {}
    for key in ("names_recurring", "names_kanji", "names_work_terms"):      # as the Tk refresh and `level` set them
        analyzer.LOGIC[key] = bool(logic.get(key, True))
    store = token_index.open_store(language)
    try:
        freqs = token_index.preview_frequencies(store, language, get_user_files_path(language),
                                                effective(language, settings.get("zh_script", "asis")))
        if freqs is None:
            return None
        return word_selection.band_previews(
            freqs, sel.get("bands_ppm"), sel.get("min_count", word_selection.DEFAULT_MIN_COUNT),
            freqs["total_tokens"] / (store.file_count() or 1),
            sel.get("minutes_per_file", word_selection.MINUTES_PER_FILE))
    finally:
        store.close()


def read_level(settings, language):
    """(the band `automation.level` shows, automatic, every band's numbers or None)."""
    from app.services import automation
    settings = settings_service.thaw(settings)
    band, auto = automation.level(settings, language)
    return band, auto, read_previews(settings, language)


def probe_anki(settings):
    """*Check*: AnkiConnect asked once at the one address every Anki caller reads (loopback only) -> `probe`'s dict."""
    from app import anki_connect
    return anki_connect.probe(anki_connect.address(settings_service.thaw(settings)), timeout=PROBE_TIMEOUT)


def read_hato():
    """hato's version from its entry in the shared tools folder ("" when it names none), or None: not installed."""
    from app import tools_entry
    entry = tools_entry.read("hato")
    if entry is None:
        return None
    version = entry.get("version")
    return str(version) if isinstance(version, (str, int, float)) and not isinstance(version, bool) else ""


def read_skipped(updates):
    return updates.skipped()


def read_licence():
    from app import credits
    return credits.licence_line()


def read_credits():
    """(DATA_CREDITS with JMdict's date — and the logos' credits, `all_credits`, where PL added them —, README's Data
    Credits names it lacks (S11), the licence line)."""
    from app import credits
    missing = []
    for folder in filter(None, credits._licence_folders()):
        try:
            with open(os.path.join(folder, "README.md"), encoding="utf-8-sig") as f:
                missing = credits.missing_from_credits(f.read())
            break
        except (OSError, UnicodeDecodeError):
            continue
    text = getattr(credits, "all_credits", credits.data_credits)()        # with the logos' credits once PL has them
    return text, missing, credits.licence_line()


def logs_folder():
    from app.connect import status
    return status.logs_folder()


def data_folder(language):
    """The language's data folder (2.4's *Data folder*), else the nearest one that exists."""
    from app.path_utils import get_data_path, get_user_file
    for path in (get_data_path(language), get_data_path(), get_user_file("")):
        if path and os.path.isdir(path):
            return path
    return None


def ready_to_export(export):
    from app import exports
    return exports.ready(export)


def run_export(export, language, fmt, dest):
    from app import exports
    if export == "sentence_list":
        return exports.sentence_list(language, dest)
    return getattr(exports, export)(language, fmt, dest)


# --- the words (Qt-free) ------------------------------------------------------------------------------------------- #
def connection(report=None, sync=None):
    """Anki's state -> (lit, a key of `S.ANKI_WORDS`): from *Check*'s look when given, else the automation's last sync."""
    if report is not None:
        if report.get("ok"):
            return True, "connected"
        if report.get("timed_out"):
            return False, "busy"
        if report.get("version") is not None:
            return False, "denied"                       # Anki answered, and kept Surasura out
        return False, "closed"
    return {"synced": (True, "connected"), "anki-closed": (False, "closed"), "failed": (False, "failed"),
            "syncing": (False, "syncing")}.get(sync, (False, "unknown"))


def _hours(hours):
    return f"{hours:.1f}".rstrip("0").rstrip(".") if hours < 10 else f"{round(hours):,}"


def readout(preview):
    """The level's readout for one band's numbers ("" for none): S4's words, *of your content*."""
    if not preview:
        return ""
    words, coverage = f"{preview['word_count']:,}", f"{preview['coverage_percent']:.1f}"
    hours = preview.get("hours_between")
    if hours and hours > 0:
        if hours < 1:
            return S.READOUT_MINUTES.format(words=words, coverage=coverage, minutes=max(1, round(hours * 60)))
        return S.READOUT_HOURS.format(words=words, coverage=coverage, hours=_hours(hours))
    return S.READOUT_NO_TIME.format(words=words, coverage=coverage)


def setup_lines(settings, language, facts):
    """Your setup's five lines. `facts`: "known" (a count or None), "anki" (a key of ANKI_WORDS or None), "connect"
    (Connect's line or None), "band" / "auto" (`automation.level`'s, None unread), "previews" (every band's numbers or
    None). A part with nothing behind it is left out."""
    from app import word_selection
    value = lambda key: catalog.value_of(settings, key)        # noqa: E731
    lines = {}
    decks = list(((settings.get("anki_sync_decks") or {}).get(language) or []))
    known = facts.get("known")
    parts = [S.SETUP_KNOWN.format(n=known)] if known is not None else []
    if decks:
        parts.append(S.SETUP_FROM_ANKI.format(decks=", ".join(decks)))
    elif known:
        parts.append(S.SETUP_IMPORTED)
    lines["setup_known"] = S.SEP.join(parts)
    anki = facts.get("anki")
    lines["setup_anki"] = S.ANKI_WORDS[anki] if anki else ""
    if not value("connect_enabled"):
        lines["setup_mining"] = S.SETUP_CONNECT_OFF
    else:
        mine = S.OPTIONS["connect_mine_words"].get(value("connect_mine_words"), "")
        lines["setup_mining"] = S.SEP.join(p for p in (mine, facts.get("connect") or "") if p)
    auto = bool(value("logic.selection.auto"))
    band = facts.get("band") if auto and facts.get("auto") else (None if auto else value("logic.selection.band"))
    parts = [S.SETUP_AUTOMATIC] if auto else []
    if band:
        parts.append(word_selection.band_label(band))
        preview = (facts.get("previews") or {}).get(band)
        if preview:
            parts.append(S.SETUP_WORDS.format(words=preview["word_count"]))
            parts.append(S.SETUP_COVERAGE.format(coverage=f"{preview['coverage_percent']:.1f}"))
    lines["setup_level"] = S.SEP.join(parts)
    if not value("enable_junban"):
        lines["setup_cards"] = S.SETUP_NOT_ORDERED
    else:
        fills = [S.OPTIONS["junban_backfill_fills"].get(f, f) for f in (value("junban_backfill_fills") or [])]
        filled = (S.SETUP_FILLED.format(fills=" + ".join(fills), how=S.SETUP_FILLED_AUTO if value(
            "junban_auto_backfill") else S.SETUP_FILLED_HAND) if fills else S.SETUP_NOTHING_FILLED)
        lines["setup_cards"] = S.SEP.join((S.SETUP_ORDER.get(value("junban_order"), ""), filled)).strip(" ·")
    return lines


def flat(text):
    """`exports`' box words on one line, for the bar."""
    return " ".join(str(text or "").split())


# --- the pops ------------------------------------------------------------------------------------------------------ #
class _Catcher(confirm.Scrim):
    """A click outside a pop closes it (the click goes no further); nothing painted."""

    def mousePressEvent(self, event):
        event.accept()
        self._on_click()

    def paintEvent(self, _event):
        pass


class _Backed(confirm.Scrim):
    """The credits card's dimmed room: a left click or the mouse's Back on it closes the card."""

    def mousePressEvent(self, event):
        event.accept()
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.BackButton):
            self._on_click()


class _Card(motion.Overlay):
    """What the two pops share: Esc and the mouse's Back close it (the window's router too, when it has one), its
    room's click closes it, `on_close` once."""
    focus = True

    def __init__(self, window, room, on_close=None):
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._window = window
        self._on_close = on_close
        self.room = room(window, self.close)
        self.room.hide()
        self.shadow = shadow.Follower(self, self.shadow_name)
        self.hide()

    def open(self):
        self.place()
        self.room.show()
        self.room.raise_()
        self.raise_()
        confirm._register(self._window, self)
        return super().open()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.BackButton:
            self.close()
            event.accept()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.room.hide()
        self.room.deleteLater()
        self.deleteLater()
        callback, self._on_close = self._on_close, None
        if callback is not None:
            callback()


class FormatPop(_Card):
    """A layer-2 pop under an Export button: which format (a `Choice`, 2.4's labels and tips) and *Save as…*."""
    how = "pop"
    shadow_name = "menu"

    def __init__(self, window, anchor, value, on_pick, on_close=None):
        from app import exports
        super().__init__(window, _Catcher, on_close)
        self.setObjectName("settingspop")
        self.setAccessibleName(exports.FORMAT_QUESTION)
        self._anchor = anchor
        self._on_pick = on_pick
        f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        pad = round(14 * f)
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(round(10 * f))
        question = QLabel(exports.FORMAT_QUESTION, self)
        question.setObjectName("confirmline")
        box.addWidget(question)
        self.choice = sc.Choice([(fmt, exports.FORMAT_LABELS[fmt], exports.FORMAT_TIPS[fmt]) for fmt in exports.FORMATS],
                                value if value in exports.FORMATS else exports.FORMATS[0],
                                tooltip=exports.FORMAT_QUESTION, name=S.EXPORT_FORMAT_NAME, parent=self)
        box.addWidget(self.choice)
        row = QHBoxLayout()
        row.addStretch(1)
        self.next = sc.Door(S.EXPORT_NEXT, tooltip=S.EXPORT_NEXT_TIP, parent=self)
        self.next.clicked.connect(lambda _c=False: self.pick())
        row.addWidget(self.next)
        box.addLayout(row)

    def place(self):
        self.ensurePolished()
        size = self.layout().totalSizeHint()
        w, h = size.width(), size.height()
        win = self._window
        at = self._anchor.mapTo(win, QPoint(self._anchor.width() - w, self._anchor.height() + 4))
        x = max(confirm.MARGIN // 2, min(at.x(), win.width() - w - confirm.MARGIN // 2))
        y = at.y() if at.y() + h <= win.height() else max(0, self._anchor.mapTo(win, QPoint(0, 0)).y() - h - 4)
        self.setGeometry(x, y, w, h)

    def pick(self):
        """The format chosen: closed without `on_close`, then `on_pick(format)`."""
        callback, self._on_pick = self._on_pick, None
        self._on_close = None
        fmt = self.choice.value()
        self.close()
        if callback is not None:
            callback(fmt)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.pick()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        style.paint_overlay(p, self.rect(), theme.RADII["menu"])
        p.end()


class CreditsCard(_Card):
    """Data credits (N6): a layer-3 card centred over the window — the credits in read-only text, the licence line, *Done*.
    Never modal."""
    how = "dialog"
    shadow_name = "dialog"

    def __init__(self, window, text, licence="", on_close=None):
        super().__init__(window, _Backed, on_close)
        self.setObjectName("settingscredits")
        self.setAccessibleName(S.CREDITS_NAME)
        f = theme.text_factor(style.current()[1])
        box = QVBoxLayout(self)
        pad = round(20 * f)
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(round(10 * f))
        title = QLabel(S.CREDITS_TITLE, self)
        title.setObjectName("confirmtitle")
        box.addWidget(title)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setPlainText(text)
        self.text.setAccessibleName(S.CREDITS_TITLE)
        self.text.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        box.addWidget(self.text, 1)
        self.licence = QLabel(licence, self)
        self.licence.setObjectName("confirmline")
        self.licence.setTextFormat(Qt.TextFormat.PlainText)
        self.licence.setVisible(bool(licence))
        box.addWidget(self.licence)
        row = QHBoxLayout()
        row.addStretch(1)
        self.done = sc.Door(S.CREDITS_DONE, tooltip=S.CREDITS_DONE_TIP, parent=self)
        self.done.clicked.connect(lambda _c=False: self.close())
        row.addWidget(self.done)
        box.addLayout(row)

    def place(self):
        w = self._window
        size = style.current()[1]
        width = min(round(theme.size("dialog", size)), max(1, w.width() - 2 * confirm.MARGIN))
        height = max(1, min(round(560 * theme.text_factor(size)), w.height() - 2 * confirm.MARGIN))
        self.setGeometry((w.width() - width) // 2, max(0, (w.height() - height) // 2), width, height)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(style.qcolor(style.colours()["surface"]))
        radius = theme.RADII["dialog"]
        p.drawRoundedRect(QRectF(self.rect()), radius, radius)
        p.end()


# --- the live rows ------------------------------------------------------------------------------------------------- #
class Live(QObject):
    """The page's live rows. Made by `SettingsPage`; fills each slot as its row is built (`page.row_built`)."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.shell = page.shell
        self.services = page.services
        self.store = page.store
        self.parts = {}                   # row id -> {name: the widget P4 put there}
        self.lines = {}                   # row id -> the help line P4 asked for (applied when the row is built)
        self.facts = {"known": None, "anki": None, "connect": None, "band": None, "auto": False, "previews": None}
        self.said = []                    # every line said (the bar's or the row's), for the record
        self.card = None                  # the credits card while it is open
        self.pop = None                   # an export's format pop while it is open
        self.asking = None                # *Restart now to apply?* while it is open (text size)
        self._exporting = None            # the export row running (one at a time)
        self._checking = False
        self._level = {"busy": False, "again": False, "asked": 0}
        self._format = None               # the format last chosen (the pop opens on it)
        page.row_built.connect(self._built)
        page.language_set.connect(self._language)
        b = page.bridge
        b.settings_written.connect(self._written)
        b.status_changed.connect(self._status)
        b.automation_changed.connect(self._automation)
        b.library_changed.connect(lambda _view: self._read_level())
        b.indexed.connect(lambda _language: self._read_level())
        b.update_changed.connect(lambda _state: self._read_skipped())
        page.takes["text_size"] = self._text_size
        page.takes["app_motion"] = self._motion
        self._read_known()
        self._read_level()
        self._run(read_hato, then=self._hato)
        self._run(read_licence, then=self._show_licence)
        self._read_skipped()
        status = getattr(self.services, "status", None)
        if status is not None and hasattr(status, "snapshot"):
            self._run(read_status, status, then=self._status)

    # --- plumbing -------------------------------------------------------------------------------------------------- #
    def _alive(self):
        from app.qt.settings_page import _alive
        return _alive(self.page)

    def _run(self, fn, *args, then=None, failed=None):
        """`fn(*args)` on a worker; `then(answer)` on the GUI thread while the page lives."""
        def done(answer):
            if then is not None and self._alive():
                then(answer)

        def fault(info):
            applog.log("settings", f"{getattr(fn, '__name__', 'a read')}: {info[1]}")
            if failed is not None and self._alive():
                failed(info)
        return bridge.run_in_worker(fn, *args, then=done, failed=fault)

    def _slot(self, row_id):
        """Where a row's live parts go: its own slot (a placeholder row) or its control's."""
        if row_id in self.page.slots:
            return self.page.custom_row(row_id)
        view = self.page.row(row_id)
        return view.slot if view is not None else None

    def _words(self, row_id, line, keep=True):
        """`row_id`'s help line set to `line` — only when it changed; `keep`: the page keeps what is in view in place."""
        self.lines[row_id] = line
        view = self.page.row(row_id)
        if view is None or view.help.text() == line:
            return
        if keep:
            with self.page._keeping(self.page._last):
                view.set_words(view.label.text(), line)
        else:
            view.set_words(view.label.text(), line)

    def say(self, text, row_id=None):
        """`text` in the bottom bar; a page with no shell bar shows it in `row_id`'s help line."""
        self.said.append(text)
        if self.shell is not None and hasattr(self.shell, "bar_line"):
            windows.say_in_bar(self.shell, text)
        elif row_id is not None:
            self._words(row_id, text)

    def _settings(self):
        return self.store.get()

    # --- a row built: its live parts ------------------------------------------------------------------------------- #
    def _built(self, row_id):
        row = catalog.ROW[row_id]
        if row_id in SETUP:
            door = sc.Door(S.CHANGE, tooltip=row.tip, name=f"{row.label}: {S.CHANGE}")
            door.clicked.connect(lambda _c=False, t=row.target: self.page.reveal(t))
            self._slot(row_id).layout().addWidget(door)
            self.parts[row_id] = {"change": door}
            self._paint_setup(keep=False)
        elif row_id == "anki_connection":
            lit, key = self._anki_now()
            mark = sc.StatusMark(lit, S.ANKI_WORDS[key], tooltip=S.ANKI_TIP, name=row.label)
            check = sc.Door(S.CHECK, tooltip=S.CHECK_LIVE_TIP)
            check.clicked.connect(lambda _c=False: self.check())
            slot = self._slot(row_id).layout()
            slot.addWidget(mark)
            slot.addWidget(check)
            self.parts[row_id] = {"mark": mark, "check": check}
        elif row_id == "connect_needs_miner":           # row 13: Anki Miner not found — the way to its card
            door = sc.Door(S.SET_UP_MINER, tooltip=S.SET_UP_MINER_TIP, name=f"{row.label}: {S.SET_UP_MINER}")
            door.clicked.connect(lambda _c=False: self.page.reveal("anki_miner"))
            self._slot(row_id).layout().addWidget(door)
            self.parts[row_id] = {"door": door}
        elif row_id == "hato":
            mark = sc.StatusMark(False, S.NOT_INSTALLED, tooltip=row.tip, name=row.label)
            self._slot(row_id).layout().addWidget(mark)
            self.parts[row_id] = {"mark": mark}
            if "hato" in self.facts:
                self._hato(self.facts["hato"])
        elif row_id in COMING:
            hint = QLabel(COMING[row_id])
            hint.setObjectName("settingshint")
            hint.setToolTip(row.tip)
            self._slot(row_id).layout().addWidget(hint)
            self.parts[row_id] = {"hint": hint}
        elif row_id == "level":
            self._paint_level(keep=False)
        elif row_id == "auto_update_enabled":
            offer = sc.Door(S.OFFER_AGAIN_NAME, tooltip=S.OFFER_AGAIN_TIP)
            offer.clicked.connect(lambda _c=False: self.offer_again())
            offer.setVisible(False)
            self._slot(row_id).layout().insertWidget(0, offer)
            self.parts[row_id] = {"offer": offer}
            self._paint_offer(self.facts.get("skipped", ""))
        elif row_id == "logs":
            door = sc.Door(S.LOGS_OPEN, tooltip=row.tip, name=row.label)
            door.clicked.connect(lambda _c=False: self.open_logs())
            self._slot(row_id).layout().addWidget(door)
            self.parts[row_id] = {"open": door}
        elif row_id == "version":
            door = sc.Door(S.DATA_FOLDER, tooltip=S.DATA_FOLDER_TIP)
            door.clicked.connect(lambda _c=False: self.open_data_folder())
            self._slot(row_id).layout().addWidget(door)
            self.parts[row_id] = {"open": door}
        elif row_id == "data_credits":
            door = sc.Door(S.CREDITS_VIEW, tooltip=row.tip, name=row.label)
            door.clicked.connect(lambda _c=False: self.open_credits())
            self._slot(row_id).layout().addWidget(door)
            view = self.page.row(row_id)
            licence = QLabel(view)
            licence.setObjectName("settingshelp")
            licence.setTextFormat(Qt.TextFormat.PlainText)
            licence.setWordWrap(True)
            licence.setVisible(False)
            view.layout().itemAt(0).layout().addWidget(licence)       # under the row's help: the words column
            self.parts[row_id] = {"open": door, "licence": licence}
            if self.facts.get("licence"):
                self._show_licence(self.facts["licence"])
        elif row_id in EXPORTS:
            door = sc.Door(S.EXPORT, tooltip=row.tip, name=row.label)
            door.clicked.connect(lambda _c=False, r=row_id: self.export(r))
            self._slot(row_id).layout().addWidget(door)
            self.parts[row_id] = {"export": door}
        elif row_id == "remove_downloaded_covers":                 # --- W3.2 L3
            door = sc.Door(S.COVERS_REMOVE, tooltip=row.tip, name=row.label)
            door.clicked.connect(lambda _c=False: self.remove_covers())
            self._slot(row_id).layout().addWidget(door)
            self.parts[row_id] = {"remove": door}                  # --- end W3.2 L3
        if row_id in self.lines and row_id not in SETUP and row_id != "level":
            self._words(row_id, self.lines[row_id], keep=False)

    # --- settings written, the language, the services' news ------------------------------------------------------ #
    def _written(self, keys):
        if not self._alive():
            return
        keys = set(keys)
        from app.services import automation
        if automation.moves_level(keys) or "exclude_single" in keys or "logic.phrase_rows" in keys:
            self._read_level()
        if "skipped_version" in keys:
            self._read_skipped()
        self._paint_level()                   # the page put the settings' band back: Automatic's shown again (S2)
        self._paint_setup()

    def _language(self, _language):
        self.facts.update(known=None, band=None, auto=False, previews=None)
        self._read_known()
        self._read_level()
        self._paint_setup()

    def _status(self, snap):
        connect = getattr(snap, "connect", None)
        if connect != self.facts["connect"]:
            self.facts["connect"] = connect
            self._paint_setup()

    def _automation(self, state):
        moved = False
        sync = getattr(state, "sync", None)
        if sync in ("synced", "anki-closed", "failed", "syncing") and self.facts.get("sync") != sync:
            self.facts["sync"] = sync
            self.facts["report"] = None                   # the newest word wins: this sync's over *Check*'s look
            moved = True
        known = getattr(state, "known", None)
        if known is not None and getattr(state, "language", None) == self.page.language and known != self.facts["known"]:
            self.facts["known"] = known
            self._read_level()                            # new known words: the readout's numbers move
            moved = True
        if moved:
            self._paint_anki()
            self._paint_setup()

    # --- Your setup ------------------------------------------------------------------------------------------------ #
    def _paint_setup(self, keep=True):
        facts = dict(self.facts, anki=self._anki_now()[1] if self._anki_known() else None)
        lines = setup_lines(self._settings(), self.page.language, facts)
        changed = [r for r in SETUP if self.page.row(r) is not None and self.page.row(r).help.text() != lines[r]]
        for r in SETUP:
            self.lines[r] = lines[r]
        if not changed:
            return
        if keep:
            with self.page._keeping(self.page._last):
                for r in changed:
                    self._words(r, lines[r], keep=False)
        else:
            for r in changed:
                self._words(r, lines[r], keep=False)

    def _read_known(self):
        language = self.page.language
        self._run(read_known, getattr(self.services, "automation", None), language,
                  then=lambda answer, lang=language: self._known(lang, answer))

    def _known(self, language, answer):
        if language != self.page.language:
            return
        known, sync = answer
        self.facts["known"] = known
        if sync is not None and self.facts.get("sync") is None and self.facts.get("report") is None:
            self.facts["sync"] = sync
            self._paint_anki()
        self._paint_setup()

    # --- the level ------------------------------------------------------------------------------------------------- #
    def _read_level(self):
        """The level (S2) and every band's numbers, read on a worker — one at a time, once more if asked meanwhile."""
        level = self._level
        if level["busy"]:
            level["again"] = True
            return
        level["busy"], level["again"] = True, False
        level["asked"] += 1
        asked, language = level["asked"], self.page.language
        self._run(read_level, self._settings(), language,
                  then=lambda answer: self._levelled(asked, language, answer),
                  failed=lambda _info: self._levelled(asked, language, None))

    def _levelled(self, asked, language, answer):
        level = self._level
        level["busy"] = False
        if level["again"]:
            self._read_level()
            return                                         # a newer read is on its way: only its numbers are shown
        if answer is None or language != self.page.language or asked != level["asked"]:
            return
        band, auto, previews = answer
        self.facts.update(band=band, auto=bool(auto), previews=previews)
        self._paint_level()
        self._paint_setup()

    def _paint_level(self, keep=True):
        view = self.page.row("level")
        if view is None or not view.controls:
            return
        slider = view.controls[0]
        settings = self._settings()
        if catalog.value_of(settings, "logic.selection.auto") and self.facts["auto"] and self.facts["band"]:
            band = self.facts["band"]
            if slider.value() != band:
                slider.blockSignals(True)                  # shown, never written (S2): no change goes out
                try:
                    slider.set_value(band)
                except (ValueError, TypeError) as e:
                    applog.log("settings", f"level: {e}")
                finally:
                    slider.blockSignals(False)
        self._words("level", readout((self.facts["previews"] or {}).get(slider.value())), keep=keep)

    # --- Anki, hato ------------------------------------------------------------------------------------------------ #
    def _anki_known(self):
        return self.facts.get("report") is not None or self.facts.get("sync") is not None or self._checking

    def _anki_now(self):
        if self._checking:
            return False, "checking"
        return connection(self.facts.get("report"), self.facts.get("sync"))

    def _paint_anki(self):
        mark = self.parts.get("anki_connection", {}).get("mark")
        if mark is None:
            return
        lit, key = self._anki_now()
        if mark.value() != lit or mark.words() != S.ANKI_WORDS[key]:
            mark.set_value(lit, S.ANKI_WORDS[key])

    def check(self):
        """*Check*: the status service refreshed, and AnkiConnect asked once on a worker (its word shown when it comes)."""
        status = getattr(self.services, "status", None)
        if status is not None and hasattr(status, "refresh_soon"):
            status.refresh_soon()
        if self._checking:
            return
        self._checking = True
        self._paint_anki()
        self._paint_setup()
        self._run(probe_anki, self._settings(), then=self._checked, failed=lambda _info: self._checked(None))

    def _checked(self, report):
        self._checking = False
        self.facts["report"] = report if report is not None else {"ok": False}
        self._paint_anki()
        self._paint_setup()

    def _hato(self, version):
        self.facts["hato"] = version
        mark = self.parts.get("hato", {}).get("mark")
        if mark is None:
            return
        words = S.NOT_INSTALLED if version is None else (S.INSTALLED.format(version=version) if version
                                                          else S.INSTALLED_PLAIN)
        if mark.value() != (version is not None) or mark.words() != words:
            mark.set_value(version is not None, words)

    # --- App ------------------------------------------------------------------------------------------------------- #
    def _text_size(self, size):
        """*Text size*: while `LIVE_TEXT_SIZE` is off (the signed ruling: a live switch with the page alive took ~0.8 s,
        over G1.2-21's ~300 ms) the page saves it and *Restart now to apply?* is asked (`_ask_restart`) -> False. On:
        the shell's own (it saves through the service and applies it), then the page restyled -> True; no such method:
        as off."""
        if not LIVE_TEXT_SIZE:
            self._ask_restart(size)
            return False
        apply = getattr(self.shell, "set_text_size", None)
        if apply is not None:
            apply(size)
        else:
            look = getattr(self.shell, "set_look", None)
            if look is None:
                self.say(strings.RESTART_TO_APPLY)        # the bar's (a page alone has none: the line never moves it)
                return False
            look(text_size=size)
        self.page.restyle()
        return True

    def _ask_restart(self, size):
        """Laptop fixes row 15 (Sonic: "having it ask and then if they select yes to restart it would auto restart"):
        *Restart now to apply?* over the window (`confirm.ask`: Esc, Back, a click outside are *Later*). *Restart now*:
        the shell's `restart` — the page's save is queued already and the quit writes it; the window state (size,
        place, the Settings tab) is saved by the close and read by the next start. *Later*, or a shell with no
        `restart` (a page alone): *Restart to apply* in the bar, as before. The size the window shows now chosen
        again: nothing to apply, nothing asked."""
        if size == style.current()[1]:
            return
        restart = getattr(self.shell, "restart", None)
        if restart is None:
            self.say(strings.RESTART_TO_APPLY)
            return

        def answered(yes):
            self.asking = None
            if yes:
                restart()
            else:
                self.say(strings.RESTART_TO_APPLY)
        label = S.OPTIONS["text_size"].get(size, size)
        self.asking = confirm.ask(self.page, S.TEXT_SIZE_RESTART_ASK, S.TEXT_SIZE_RESTART_BODY.format(size=label),
                                  S.TEXT_SIZE_RESTART_YES, S.TEXT_SIZE_RESTART_YES_TIP, no=S.TEXT_SIZE_RESTART_NO,
                                  no_tip=S.TEXT_SIZE_RESTART_NO_TIP, on_answer=answered)

    def _motion(self, value):
        """*Motion*: set on the motion clock at once (in the window: a page alone leaves the app's clock be); the page
        saves it -> False."""
        if self.shell is not None:
            motion.clock().mode.set_setting(value)
        return False

    def _read_skipped(self):
        updates = getattr(self.services, "updates", None)
        if updates is None or not hasattr(updates, "skipped"):
            return
        self._run(read_skipped, updates, then=self._paint_offer)

    def _paint_offer(self, version):
        self.facts["skipped"] = version or ""
        offer = self.parts.get("auto_update_enabled", {}).get("offer")
        if offer is None:
            return
        text = S.OFFER_AGAIN.format(version=version) if version else S.OFFER_AGAIN_NAME
        if offer.text() != text:
            offer.setText(text)
        if offer.isHidden() == bool(version):
            with self.page._keeping(self.page._last):
                offer.setVisible(bool(version))

    def offer_again(self):
        updates = getattr(self.services, "updates", None)
        if updates is None:
            return
        self._paint_offer("")
        self._run(updates.offer_again)

    def open_logs(self):
        self._run(logs_folder, then=lambda folder: folder and windows.open_url(folder))

    def open_data_folder(self):
        self._run(data_folder, self.page.language, then=lambda folder: folder and windows.open_url(folder))

    def _show_licence(self, line):
        self.facts["licence"] = line or ""
        label = self.parts.get("data_credits", {}).get("licence")
        if label is None or label.text() == (line or ""):
            return
        with self.page._keeping(self.page._last):
            label.setText(line or "")
            label.setVisible(bool(line))

    def open_credits(self):
        """Data credits: read on a worker (JMdict's date, README's names), then the card."""
        if self.card is not None:
            return
        self._run(read_credits, then=self._credits_read)

    def _credits_read(self, answer):
        if self.card is not None:
            return
        text, missing, licence = answer
        if missing:
            text = f"{text}\n\n{S.CREDITS_README_ALSO.format(names=', '.join(missing))}\n{S.README_POINTER}"
        self.card = CreditsCard(self.page.window(), text, licence, on_close=self._credits_closed)
        self.card.open()

    def _credits_closed(self):
        self.card = None

    # --- W3.2 L3: *Remove downloaded covers* — the shell's fetcher (Q7's `remove_downloaded`: the writer's
    # `forget_covers`, on a worker); the user's covers and the art beside the files stay
    def remove_covers(self):
        make = getattr(self.shell, "cover_fetcher", None)
        fetcher = make() if make is not None else None
        if fetcher is None:
            self.say(strings.COVERS_REMOVE_NONE, "remove_downloaded_covers")
            return None

        def done(number):
            from app.qt import covers as qcovers
            if number is None:
                self.say(strings.COVER_CANT, "remove_downloaded_covers")
                return
            qcovers.ask_again()
            self.say(strings.COVERS_REMOVED, "remove_downloaded_covers")
        return self._run(fetcher.remove_downloaded, then=done)
    # --- end W3.2 L3

    # --- Export ---------------------------------------------------------------------------------------------------- #
    def export(self, row_id):
        """An Export row's click: what its export needs asked for in turn, then the export on a worker."""
        if self._exporting is not None:
            self.say(S.EXPORT_BUSY, row_id)
            return
        self._grey(row_id)
        self._run(ready_to_export, EXPORTS[row_id], then=lambda not_ready: self._export_ready(row_id, not_ready),
                  failed=lambda info: self._exported(row_id, None, info))

    def _export_ready(self, row_id, not_ready):
        from app import exports
        if not_ready is not None:
            self.say(flat(not_ready.message), row_id)
            self._grey(None)
            return
        needs = exports.NEEDS[EXPORTS[row_id]]
        if "format" in needs:
            self.pop = FormatPop(self.page.window(), self.parts[row_id]["export"], self._format,
                                 on_pick=lambda fmt: self._export_to(row_id, fmt), on_close=self._export_dropped)
            self.pop.open()
        elif "confirm" in needs:
            confirm.ask(self.page, exports.SENTENCE_WARNING_TITLE, exports.SENTENCE_WARNING, exports.SENTENCE_CONFIRM,
                        S.EXPORT_CONFIRM_TIP, default_no=True,
                        on_answer=lambda yes: self._export_to(row_id, "anki") if yes else self._grey(None))
        else:
            self._export_to(row_id, None)

    def _export_dropped(self):
        self.pop = None
        self._grey(None)

    def _export_to(self, row_id, fmt):
        """The destination asked (2.4's Save-as: its name, title and file type), then the export on a worker."""
        from app import exports
        self.pop = None
        export = EXPORTS[row_id]
        if fmt != "anki":
            self._format = fmt
        ext, types, name, title = exports.save_as(fmt or "txt", exports.INITIAL_NAMES[export])
        path, _filter = QFileDialog.getSaveFileName(self.page, title, name,
                                                    ";;".join(f"{label} ({pattern})" for label, pattern in types))
        if not path:
            self._grey(None)
            return
        if not path.lower().endswith(ext):
            path += ext
        self.say(S.EXPORT_RUNNING.format(name=catalog.ROW[row_id].label), row_id)
        self._run(run_export, export, self.page.language, fmt, os.path.normpath(path),
                  then=lambda outcome: self._exported(row_id, outcome),
                  failed=lambda info: self._exported(row_id, None, info))

    def _exported(self, row_id, outcome, info=None):
        from app import exports
        if outcome is None:
            outcome = exports.Outcome("failed", None, 0, exports.FAILED.format(error=info[0] if info else ""))
        if outcome.message:
            self.say(flat(outcome.message), row_id)
        self._grey(None)

    def _grey(self, row_id):
        """`row_id` greyed while its export runs, every Export button with it (one at a time); None: all back."""
        self._exporting = row_id
        for other in EXPORTS:
            view = self.page.row(other)
            if view is not None:
                view.setEnabled(row_id is None)
