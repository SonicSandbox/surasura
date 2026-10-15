"""Settings › New arrivals › *Where new arrivals go* (W3.3 PR; G1.2-12, D30; the RUNBOOK's New arrivals row, its N4;
the intent keeper's B2): the placing rules' row, drawn into the slot the page leaves for it (`custom_row`).

`attach(page)` -> `RulesRow`: called once by whoever mounts the page (P7), after the page is made, beside
`settings_connect.attach(page)` — never by the page itself.

- **One line per source:** hato's always (at *Wait here* while it has no rule), then each source `placing_rules` names
  (`<producer>` or `<producer>:<channel id>`, `app/connect/rules.py`), sorted. Each is a `Select` over `rules.TARGETS`
  in the catalog's words (Wait here · Top of Current · After its show · Soon · Goal · Finished). A target the file
  holds that is no place (hand-edited) shows as itself and stays until the user picks; a value that is not a
  {source: target} dict shows hato's line alone. Nothing is written by showing.
- **A pick** -> `catalog.change(row, settings, language, (source, target))` -> `services.settings.set(changes)`: the one
  key, only when it moved. *Wait here* takes the source out of the dict (empty = every arrival waits, RD-S16), and its
  line goes (hato's stays at Wait).
- ***+ rule*** reads, on a worker, the sources the language stores have seen (each pairing's `producer`, and
  `<producer>:<channel id>` where the record names its channel — the store's own rule, `library_store._rule_for`) and
  offers those without a line (hato's is always there), then *Another source…* (typed). A source picked adds a line at
  *Wait here*, saved only once a place is picked. Esc closes the menu, and the typed field without adding.
- Repaints only the line that changed (another window's write too: `bridge.settings_written`); every change in the
  page's `hold`, so the page never moves.

GUI_Design_Guidelines_Qt: the page's controls and label styles (no new rules), a tooltip on every button and field.
"""
from collections.abc import Mapping

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget

from app import theme
from app.qt import applog, bridge, style
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_strings as S

ROW_ID = "placing_rules"
HATO = "hato"
WAIT = "wait"


def _f():
    return theme.text_factor(style.current()[1])


def _alive(w):
    return w is not None and not sip.isdeleted(w)


def attach(page):
    """The placing rules' row filled into `page`'s slot -> its `RulesRow` (kept by the page as a child)."""
    return RulesRow(page)


# --- reading (pure, or a worker's) ------------------------------------------------------------------------------- #
def held_rules(settings):
    """{source: target} as the row shows it: a dict's non-empty string sources, a Wait left out (it is no line);
    anything else held there (a list, a number, nothing) -> {}."""
    held = catalog.value_of(settings, ROW_ID)
    if not isinstance(held, Mapping):
        return {}
    return {source: target for source, target in held.items()
            if isinstance(source, str) and source.strip() and target != WAIT}


def sources_of(records):
    """The sources a rule can name for these pairing records: the producer ("hato" when it names none) and, for a
    record naming its channel, `<producer>:<channel id>` (`library_store._rule_for`'s reading)."""
    found = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        producer = str(record.get("producer") or HATO).strip()
        if not producer:
            continue
        found.add(producer)
        channel = record.get("channel_id")
        if isinstance(channel, str) and channel.strip():
            found.add(f"{producer}:{channel.strip()}")
    return found


def sources_seen(languages=catalog.LANGUAGES):
    """(A worker.) The sources each language's library store has seen (its pairings), as a set; a store not there (none
    built yet, JSON mode, busy) adds nothing."""
    from app import library_store
    from app.connect import library
    from app.path_utils import get_data_path, get_user_files_path
    found = set()
    for language in languages:
        try:
            store = library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                             role="window", busy_wait=0.0)
        except Exception as e:                                   # noqa: BLE001 — a store unread offers hato alone
            applog.log("settings", f"placing rules: the {language} store unread: {e}")
            continue
        if store is None:
            continue
        with store:
            for records in library.pairings(store).values():
                found |= sources_of(records)
    return found


def _read_seen():
    """(A worker.) Looked up at call time, so a test can stand in for `sources_seen`."""
    return sources_seen()


def source_words(source):
    """A source as the line names it: `youtube:UC…` -> *youtube · channel UC…*."""
    producer, sep, channel = source.partition(":")
    return S.RULE_CHANNEL.format(producer=producer, channel=channel) if sep and channel else source


# --- the row ----------------------------------------------------------------------------------------------------- #
class RuleLine(QWidget):
    """One source's line: *From <source>* and its place (`select`); a pick calls `on_pick(source, target)`."""

    def __init__(self, source, target, on_pick, new=False, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsrule")
        self.source = source
        self.new = new                                  # added by + rule, not yet saved
        self.on_pick = on_pick
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(round(8 * _f()))
        self.words = QLabel(self)
        self.words.setObjectName("settingsaffix")
        self.words.setText(S.RULE_LINE_WORDS.format(source=source_words(source)))
        line.addWidget(self.words)
        line.addStretch(1)
        self.select = None
        self.show_target(target)

    @staticmethod
    def options(target):
        row = catalog.ROW[ROW_ID]
        opts = [(v, label) for v, label, _line in catalog.options(row, {}, "ja")]
        if target not in [v for v, _l in opts]:
            opts.append((target, S.RULE_HELD.format(value=target)))    # hand-edited: shown as itself, kept
        return opts

    def tip(self):
        words = source_words(self.source)
        return S.RULE_NEW_TIP.format(source=words) if self.new else S.RULE_LINE_TIP.format(source=words)

    def retip(self):
        tip = self.tip()
        self.select._own_tip = tip
        self.select.setToolTip(tip)

    def show_target(self, target):
        """Show `target` (no signal); a target outside the control's options makes the control again."""
        if self.select is not None:
            try:
                if self.select.value() != target:
                    self.select.set_value(target)
                self.retip()
                return
            except ValueError:
                pass
        old = self.select
        self.select = sc.Select(self.options(target), target, tooltip=self.tip(),
                                name=S.RULE_LINE_NAME.format(source=source_words(self.source)), parent=self)
        self.select.changed.connect(lambda v: self.on_pick(self.source, v))
        if old is None:
            self.layout().addWidget(self.select)
        else:
            self.layout().replaceWidget(old, self.select)
            old.hide()
            old.deleteLater()


class RulesRow(QObject):
    """The row's lines (`lines`: source -> RuleLine), *+ rule* (`add`), its menu (`menu`, while open) and the typed
    source's field (`typing`, while shown)."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.store = page.store
        self.row = catalog.ROW[ROW_ID]
        self.lines = {}
        self.menu = None
        self.typing = None
        self.reads = 0                                  # + rule's reads asked (the newest one's answer is shown)
        slot = page.custom_row(ROW_ID)
        self.box = QWidget(slot)
        self.box.setObjectName("settingsrules")
        column = QVBoxLayout(self.box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(round(6 * _f()))
        self.add = sc.Door(S.RULE_ADD, tooltip=S.RULE_ADD_TIP, parent=self.box)
        self.add.clicked.connect(lambda _c=False: self.ask_sources())
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addStretch(1)
        foot.addWidget(self.add)
        column.addLayout(foot)
        slot.layout().addWidget(self.box)
        self._sync(keep=False)
        page.bridge.settings_written.connect(self._written)
        if page.built:
            self._ready()
        else:
            page.ready.connect(self._ready)

    def alive(self):
        return _alive(self.page)

    def _ready(self):
        if self.alive():
            self.page._tab_order()

    # --- showing ------------------------------------------------------------------------------------------------- #
    def _wanted(self):
        """source -> target the lines should show: hato's, each rule's, and each new line still at Wait."""
        rules = held_rules(self.page._settings())
        wanted = {HATO: rules.get(HATO, WAIT)}
        for source in sorted(s for s in rules if s != HATO):
            wanted[source] = rules[source]
        for source, line in self.lines.items():
            if line.new and source not in wanted:
                wanted[source] = WAIT
        return wanted

    def _sync(self, keep=True, anchor=None):
        """The lines made to match the settings: only a line that changed is touched (added, removed or shown its new
        place); `keep`: inside the page's hold (the page never moves)."""
        if not self.alive():
            return
        wanted = self._wanted()
        gone = [s for s in self.lines if s not in wanted]
        moved = [s for s, t in wanted.items() if s in self.lines and self.lines[s].select.value() != t]
        added = [s for s in wanted if s not in self.lines]
        if not (gone or moved or added):
            return
        if keep:
            with self.page.hold(anchor if anchor is not None else self.page.row(ROW_ID)):
                self._apply(wanted, gone, moved, added)
        else:
            self._apply(wanted, gone, moved, added)
        if added and self.page.built:
            self.page._tab_order()

    def _apply(self, wanted, gone, moved, added):
        column = self.box.layout()
        for source in gone:
            line = self.lines.pop(source)
            column.removeWidget(line)
            line.hide()
            line.deleteLater()
        for source in moved:
            self.lines[source].show_target(wanted[source])
        for source in added:
            line = RuleLine(source, wanted[source], self.pick, parent=self.box)
            column.insertWidget(self._index_for(source, wanted), line)
            self.lines[source] = line
            if self.box.isVisible():                    # shown in this turn (a layout shows a new child a turn late)
                line.show()
        self._lay_out()

    def _lay_out(self):
        """The column's change laid out up to the page's body now, inside the page's hold: the box sits several
        layouts deep, more than the hold's own settling reaches in one turn (the page would grow a turn late, a
        wrapped row above squeezed for a frame)."""
        widget, top = self.box, self.page.scroll.viewport()
        while widget is not None and widget is not top:
            if widget.layout() is not None:
                widget.layout().activate()
            widget = widget.parentWidget()

    def _index_for(self, source, wanted):
        """Where `source`'s new line goes in the column: before the next shown line in `wanted`'s order, else after
        the last line (the lines stand first, then the typed field and *+ rule*)."""
        column, order = self.box.layout(), list(wanted)
        for later in order[order.index(source) + 1:]:
            line = self.lines.get(later)
            if line is not None and column.indexOf(line) >= 0:
                return column.indexOf(line)
        return sum(1 for line in self.lines.values() if column.indexOf(line) >= 0)

    def _written(self, keys):
        """Another window's write (or ours landing): the lines follow the settings."""
        if self.alive() and ROW_ID in set(keys):
            self._sync(anchor=self.page._last)

    # --- changing ------------------------------------------------------------------------------------------------ #
    def pick(self, source, target):
        """A line's place picked: the one key through the service, only when it moved; *Wait here* takes the source
        out (its line goes, hato's stays)."""
        if not self.alive():
            return
        line = self.lines.get(source)
        control = line.select if line is not None else None
        self.page._last = control
        self.page._let_go()
        try:
            changes, _update = catalog.change(self.row, self.page._settings(), self.page.language, (source, target))
        except (ValueError, TypeError) as e:
            applog.log("settings", f"{ROW_ID}: {e}")
            self._sync(anchor=control)
            return
        if line is not None and line.new:
            line.new = False                            # saved now (or, put back to Wait, it goes: nothing written)
            line.retip()
        if changes:
            self.store.set(changes)
        goes = target == WAIT and source != HATO          # its line leaves: the row's top is what stays put
        self._sync(anchor=self.page.row(ROW_ID) if goes else control)

    def ask_sources(self):
        """*+ rule*: the sources seen, read on a worker, then the menu at the button."""
        if not self.alive():
            return
        self.reads += 1
        n = self.reads
        self.add.setEnabled(False)

        def done(seen):
            if self.alive() and n == self.reads:
                self.add.setEnabled(True)
                self.offer(seen)

        def failed(info):
            applog.log("settings", f"placing rules: the sources unread: {info[1]}")
            done(set())
        bridge.run_in_worker(_read_seen, then=done, failed=failed)

    def offered(self, seen):
        """The sources + rule offers: hato and those seen, without a line, hato first."""
        sources = {HATO} | {s for s in (seen or ()) if isinstance(s, str) and s.strip()}
        return [s for s in [HATO] + sorted(sources - {HATO}) if s not in self.lines]

    def offer(self, seen):
        """The menu: each source seen without a line, then *Another source…*; Esc closes it, adding nothing."""
        if self.menu is not None and _alive(self.menu):
            self.menu.close()
            self.menu.deleteLater()
        self.menu = QMenu(self.add)
        self.menu.setToolTipsVisible(True)
        offered = self.offered(seen)
        for source in offered:
            action = self.menu.addAction(source_words(source))
            action.setToolTip(S.RULE_NEW_TIP.format(source=source_words(source)))
            action.triggered.connect(lambda _c=False, s=source: self._after_menu(self.add_line, s))
        if not offered:
            none = self.menu.addAction(S.RULE_SEEN_NONE)
            none.setEnabled(False)
        self.menu.addSeparator()
        other = self.menu.addAction(S.RULE_TYPE)
        other.setToolTip(S.RULE_TYPE_TIP)
        other.triggered.connect(lambda _c=False: self._after_menu(self.type_source))
        self.menu.popup(self.add.mapToGlobal(QPoint(0, self.add.height() + 2)))

    def _after_menu(self, fn, *args):
        """A menu's pick acted on once the menu has closed (its own turn): the line laid out with the page as it
        stands, the reader's place kept."""
        QTimer.singleShot(0, lambda: fn(*args) if self.alive() else None)

    def add_line(self, source):
        """A source picked or typed: its line at *Wait here*, nothing saved until a place is picked; a source that
        already has a line keeps it (focused)."""
        source = str(source or "").strip()
        if not source or not self.alive():
            return
        line = self.lines.get(source)
        if line is None:
            with self.page.hold(self.page.row(ROW_ID)):
                line = RuleLine(source, WAIT, self.pick, new=True, parent=self.box)
                self.box.layout().insertWidget(self._index_for(source, {**self._wanted(), source: WAIT}), line)
                self.lines[source] = line
                if self.box.isVisible():
                    line.show()
                self._lay_out()
            if self.page.built:
                self.page._tab_order()
        line.select.setFocus(Qt.FocusReason.OtherFocusReason)

    def type_source(self):
        """*Another source…*: a field under the lines; Enter adds its line, Esc closes it adding nothing."""
        if not self.alive():
            return
        if self.typing is None or not _alive(self.typing):
            with self.page.hold(self.page.row(ROW_ID)):
                self.typing = sc.TextField("", placeholder=S.RULE_TYPE_PLACEHOLDER, tooltip=S.RULE_TYPE_TIP,
                                           name=S.RULE_TYPE_NAME, parent=self.box)
                self.typing.changed.connect(self._typed)
                self.typing.edit.installEventFilter(self)
                self.box.layout().insertWidget(self.box.layout().count() - 1, self.typing)     # above + rule
                if self.box.isVisible():
                    self.typing.show()
                self._lay_out()
        self.typing.setFocus(Qt.FocusReason.OtherFocusReason)

    def _typed(self, text):
        if text.strip():
            self._close_typing()
            self.add_line(text)

    def _close_typing(self):
        field, self.typing = self.typing, None
        if field is not None and _alive(field):
            field.blockSignals(True)                    # its focus leaving commits nothing: Esc adds no line
            with self.page.hold(self.page.row(ROW_ID)):
                field.edit.removeEventFilter(self)
                self.box.layout().removeWidget(field)
                field.hide()
                field.deleteLater()
                self._lay_out()

    def eventFilter(self, obj, event):
        if (self.typing is not None and _alive(self.typing) and obj is self.typing.edit
                and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape):
            self._close_typing()
            return True
        return False
