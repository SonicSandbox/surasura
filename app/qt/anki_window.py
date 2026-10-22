"""The Anki window (W3.4 row 3): known words read from the cards you've studied in Anki, over AnkiConnect.

    probe  ->  pick decks + a field  ->  Sync now        (or: Replace with Anki… / Restore previous…)

The port of the Tk `AnkiSyncGui` (`app/anki_sync_gui.py`, left as it is for the `dashboard` verb). **It decides
nothing:** the rules are `app/anki_window.py`'s and the engine's (`app/anki_sync.py`); this window reads on workers
(`bridge.run_in_worker`), paints the answers, and asks.

- **Every Sync / Replace / Restore is an `anki-sync` job** (`anki_window.submit`): the bottom bar shows it, the
  automatic sync never starts beside it, and none starts while an update holds Surasura's children. Its result reaches
  the automation service from the job's thread (`Automation.anki_synced`: the quiet Generate, the indexer).
- **Nothing is written by opening the window** (S16, IK-13): the first open's pick of decks is shown and saved on the
  user's first action — a Sync, a Replace, a deck or field changed, a switch flipped.
- **Replace:** a dry run on a worker → the in-window confirmation with its true numbers (what Anki brings, the past
  Graduates' words and the ignored words kept, the backup named; default Cancel) → the write, which carries those
  numbers: Anki changed meanwhile, nothing is written and the window asks again. **Restore previous** says what it
  puts back (its backup's time, both totals), default Cancel, and puts back only that backup.
- **The language:** the window follows the main window's language when idle; a job in flight finishes first (its
  result goes to the bottom bar too), then the window reads again (`SecondaryWindow`, 🧭 IK-12). Its doors —
  *Backfill cards…* and *Import an .apkg instead…* — are the openers named `backfill` (row 5) and `apkg_known` (row 2)
  when they are there, asked again by the base's rule (a module's switch, the modules' look: IK-20 / IK-45), and
  opening one never closes this window.
- **Each part repaints only what changed** (S19): the deck rows, the deck offer and the field boxes are rebuilt only
  when what they show changed (`deck_paints`, `add_paints`, `field_paints` count the rebuilds: IK-43).
"""
import os

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                             QToolButton, QWidget)

from app import anki_connect, anki_sync, theme
from app import anki_window as AW
from app.qt import applog, bridge, confirm, strings, style, windows
from app.services import jobs as jobs_module

NAME = "anki"
WAITS_FOR = "waits for "                                 # the registry's reason for a job held back by another
FLASH_MS = 5000                         # the "+N" beside the total, after a sync that added words
DOORS = (("btn_backfill", "backfill"), ("btn_apkg", "apkg_known"))      # row 5's opener, row 2's (IK-41)
SWITCHES = (("chk_auto", "anki_sync_auto"), ("chk_generate", "anki_auto_generate"))


class _Keys(QObject):
    """Shift held on *Sync now* (a click or a key) and Delete on the deck list."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        w = self.window
        if obj is w.btn_sync and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            w._shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        elif obj is w.deck_list and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Delete:
            item = w.deck_list.currentItem()
            if item is not None and item.data(Qt.ItemDataRole.UserRole):
                w.remove_deck(item.data(Qt.ItemDataRole.UserRole))
            return True
        return False


class AnkiWindow(windows.SecondaryWindow):
    def __init__(self, shell, language=None):
        super().__init__(shell, strings.ANKI_NAME, language)
        self.services = shell.services
        self._connected = False
        self._all_decks = []              # every deck Anki has
        self._counts = {}                 # chosen deck -> studied notes
        self._models = {}                 # note type -> its fields, in order
        self._unsaved_pick = False        # the first open's pick, shown and not saved yet (S16)
        self._probe_seq = 0               # the newest probe / scope read (an older answer is dropped)
        self._probing = False
        self._shift = False
        self._known = None
        self._automation_seq = None
        self._deck_key = self._add_key = self._field_key = None       # what each part shows now (S19)
        self.job = None                   # the window's job under way, and the line it shows while it runs
        self._job_line = None
        self._job_state = None
        self.deck_paints = self.add_paints = self.field_paints = 0
        self._load_choices()
        self._build()
        self._keys = _Keys(self)
        self.btn_sync.installEventFilter(self._keys)
        self.deck_list.installEventFilter(self._keys)
        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(lambda: self._set_label(self.delta, ""))
        self._render()
        self.refresh_known()
        b = getattr(shell, "bridge", None)
        if b is not None:
            b.settings_written.connect(self._settings_heard)
            b.automation_changed.connect(self._automation_state)
            b.jobs_changed.connect(self._follow)
        windows.follow_doors(self)                        # told when the modules were looked for (a door names one)
        if not os.environ.get("SURASURA_NO_UI_TIMERS"):     # never reach Anki from a test's window (testing.md §5.4)
            QTimer.singleShot(0, self.alive(self.refresh_connection))

    # --- the choices ------------------------------------------------------------------------------------------------ #
    def _settings(self):
        return self.services.settings.get()

    def _load_choices(self):
        self.decks, chosen, self.suspended = AW.saved(self._settings(), self.language)
        self.first = chosen[0] if chosen else None
        self.second = chosen[1] if len(chosen) > 1 else None
        self._saved_choices = (tuple(self.decks), tuple(self.chosen()))       # as the file holds them

    def chosen(self):
        return AW.fields(self.first, self.second)

    def _save_choices(self):
        """This language's decks and fields onto the file as it is (the settings service's worker writes it)."""
        self._unsaved_pick = False
        now = (tuple(self.decks), tuple(self.chosen()))
        if now == self._saved_choices:
            return                                        # unchanged: nothing written (IK-47, S19)
        self._saved_choices = now
        self.services.settings.set({}, update=AW.merge(self.language, self.decks, self.chosen()))

    def _first_action(self):
        """The user acted: the first open's pick, shown until now, is saved (S16, IK-13)."""
        if self._unsaved_pick:
            self._save_choices()

    def _snapshot(self):
        return {"language": self.language, "url": anki_connect.address(self._settings()), "decks": list(self.decks),
                "fields": self.chosen(), "suspended": bool(self.suspended)}

    # --- building ----------------------------------------------------------------------------------------------- #
    def _button(self, text, tip, slot, parent=None, kind=None, name=None):
        b = QPushButton(text, parent or self)
        b.setToolTip(tip)
        b.setAccessibleName(name or text)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if kind:
            b.setProperty("kind", kind)
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _toggle(self, text, tip, on, slot):
        c = QCheckBox(text, self)
        c.setProperty("kind", "toggle")
        c.setToolTip(tip)
        c.setAccessibleName(text)
        c.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        c.blockSignals(True)
        c.setChecked(bool(on))
        c.blockSignals(False)
        c.toggled.connect(slot)
        return c

    def _label(self, name, text="", parent=None):
        lab = QLabel(text, parent or self)
        lab.setObjectName(name)
        lab.setTextFormat(Qt.TextFormat.PlainText)
        return lab

    def _build(self):
        f = theme.text_factor(style.current()[1])
        settings = self._settings()
        # the head: the name, Anki's state, ⟳, the Backfill door
        head = QHBoxLayout()
        self.heading = self._label("windowheading", strings.ANKI_NAME)
        self.heading.setToolTip(strings.ANKI_HEADING_TIP.format(language=strings.ANKI_LANGUAGES.get(self.language)))
        head.addWidget(self.heading)
        head.addStretch(1)
        self.btn_backfill = self._button(strings.ANKI_BACKFILL, strings.ANKI_BACKFILL_TIP,
                                         lambda: self._open_door("backfill"))
        head.addWidget(self.btn_backfill)
        self.state = self._label("ankistate", strings.ANKI_STATE_UNCHECKED)
        self.state.setProperty("state", "unchecked")
        self.state.setAccessibleName(strings.ANKI_STATE_NAME)
        head.addWidget(self.state)
        self.btn_recheck = self._button(strings.ANKI_RECHECK, strings.ANKI_RECHECK_TIP, self.refresh_connection,
                                        name=strings.ANKI_RECHECK_NAME)
        head.addWidget(self.btn_recheck)
        self.body.addLayout(head)

        # the decks
        self.body.addWidget(self._label("windowline", strings.ANKI_DECKS))
        self.deck_list = QListWidget(self)
        self.deck_list.setObjectName("windowlist")
        self.deck_list.setToolTip(strings.ANKI_DECKS_TIP)
        self.deck_list.setAccessibleName(strings.ANKI_DECKS)
        self.deck_list.setMinimumHeight(round(110 * f))
        self.body.addWidget(self.deck_list, 1)
        self.no_decks = self._label("windowline", strings.ANKI_NO_DECKS)
        self.body.addWidget(self.no_decks)
        self.add_box = QComboBox(self)
        self.add_box.setToolTip(strings.ANKI_ADD_TIP)
        self.add_box.setAccessibleName(strings.ANKI_ADD)
        self.add_box.setPlaceholderText(strings.ANKI_ADD)
        self.add_box.activated.connect(self._add_chosen)
        self.body.addWidget(self.add_box)

        # the fields
        row = QHBoxLayout()
        row.addWidget(self._label("windowline", strings.ANKI_FIELD))
        self.box_field1 = QComboBox(self)
        self.box_field1.setToolTip(strings.ANKI_FIELD_TIP)
        self.box_field1.setAccessibleName(strings.ANKI_FIELD)
        self.box_field1.activated.connect(self._field1_chosen)
        row.addWidget(self.box_field1, 1)
        row.addWidget(self._label("windowline", strings.ANKI_ALSO))
        self.box_field2 = QComboBox(self)
        self.box_field2.setToolTip(strings.ANKI_ALSO_TIP)
        self.box_field2.setAccessibleName(strings.ANKI_ALSO)
        self.box_field2.activated.connect(self._field2_chosen)
        row.addWidget(self.box_field2, 1)
        self.body.addLayout(row)
        self.resolved = self._label("ankiresolved")
        self.resolved.setWordWrap(True)
        self.body.addWidget(self.resolved)
        self.skipped = self._label("ankiskipped")
        self.skipped.setWordWrap(True)
        self.body.addWidget(self.skipped)

        # the switches
        self.chk_suspended = self._toggle(strings.ANKI_SUSPENDED, strings.ANKI_SUSPENDED_TIP, self.suspended,
                                          self._suspended_changed)
        self.chk_auto = self._toggle(strings.ANKI_AUTO, strings.ANKI_AUTO_TIP, settings.get("anki_sync_auto"),
                                     lambda on: self._toggled("anki_sync_auto", on))
        self.chk_generate = self._toggle(strings.ANKI_GENERATE, strings.ANKI_GENERATE_TIP,
                                         settings.get("anki_auto_generate"),
                                         lambda on: self._toggled("anki_auto_generate", on))
        for c in (self.chk_suspended, self.chk_auto, self.chk_generate):
            self.body.addWidget(c)

        # the numbers
        stat = QHBoxLayout()
        self.total = self._label("ankitotal", "—")
        self.total.setToolTip(strings.ANKI_KNOWN_TIP)
        self.total.setAccessibleName(strings.ANKI_TOTAL_NAME)
        stat.addWidget(self.total)
        stat.addWidget(self._label("windowline", strings.ANKI_KNOWN))
        self.delta = self._label("ankidelta")
        stat.addWidget(self.delta)
        stat.addStretch(1)
        self.body.addLayout(stat)
        self.backlog = self._label("windowline")
        self.backlog.setToolTip(strings.ANKI_BACKLOG_TIP)
        self.backlog.setVisible(False)
        self.body.addWidget(self.backlog)

        # the actions
        self.body.addWidget(style.separator(self))
        actions = QHBoxLayout()
        self.btn_apkg = self._button(strings.ANKI_APKG, strings.ANKI_APKG_TIP, lambda: self._open_door("apkg_known"),
                                     kind="chip")
        actions.addWidget(self.btn_apkg)
        self.btn_restore = self._button(strings.ANKI_RESTORE, strings.ANKI_RESTORE_TIP, self.on_restore, kind="chip")
        self.btn_restore.setVisible(False)
        actions.addWidget(self.btn_restore)
        actions.addStretch(1)
        self.btn_replace = self._button(strings.ANKI_REPLACE, strings.ANKI_REPLACE_TIP, self.on_replace)
        actions.addWidget(self.btn_replace)
        self.btn_sync = self._button(strings.ANKI_SYNC, strings.ANKI_SYNC_TIP, self._sync_clicked, kind="primary")
        actions.addWidget(self.btn_sync)
        self.body.addLayout(actions)
        self._doors_again()

    # --- painting (each paints only what changed: S19) ---------------------------------------------------------- #
    @staticmethod
    def _set_label(label, text):
        if label.text() != text:
            label.setText(text)
        if label.isHidden() == bool(text):
            label.setVisible(bool(text))

    def _paint_state(self, kind, text):
        """Anki's state: its words, and its colour by the state's token (`#ankistate[state=…]`: ok / bad; IK-42)."""
        self._set_label(self.state, text)
        if self.state.property("state") != kind:
            self.state.setProperty("state", kind)
            self.state.style().unpolish(self.state)
            self.state.style().polish(self.state)

    @staticmethod
    def _enable(widget, on):
        if widget.isEnabled() != bool(on):
            widget.setEnabled(bool(on))

    def _render(self):
        self._render_decks()
        self._render_add()
        self._render_fields()
        self._paint_controls()

    def _render_decks(self):
        key = tuple((deck, self._counts.get(deck)) for deck in self.decks)
        if key == self._deck_key:
            return
        self._deck_key = key
        self.deck_paints += 1
        self.deck_list.clear()
        for deck in self.decks:
            item = QListWidgetItem(self.deck_list)
            item.setData(Qt.ItemDataRole.UserRole, deck)
            row = QWidget(self.deck_list)
            line = QHBoxLayout(row)
            line.setContentsMargins(6, 0, 0, 0)
            name = self._label("windowline", deck, row)
            line.addWidget(name, 1)
            n = self._counts.get(deck)
            line.addWidget(self._label("windowline", strings.ANKI_STUDIED.format(n=n) if isinstance(n, int) else "",
                                       row))
            remove = QToolButton(row)
            remove.setText(strings.ANKI_REMOVE)
            remove.setAccessibleName(strings.ANKI_REMOVE_NAME.format(deck=deck))
            remove.setToolTip(strings.ANKI_REMOVE_TIP.format(deck=deck))
            remove.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            remove.setEnabled(not self.busy())
            remove.clicked.connect(lambda _c=False, d=deck: self.remove_deck(d))
            line.addWidget(remove)
            item.setSizeHint(row.sizeHint())
            self.deck_list.setItemWidget(item, row)
        self.no_decks.setVisible(not self.decks)

    def _render_add(self):
        offer = [d for d in self._all_decks if d not in self.decks]
        # offline, Anki's decks aren't known yet: "No other decks" would be a false claim
        key = (tuple(offer), strings.ANKI_ADD if offer or not self._connected else strings.ANKI_ADD_NONE)
        if key == self._add_key:
            if self.add_box.currentIndex() != -1:         # a pick that added nothing: back to the placeholder
                self.add_box.blockSignals(True)
                self.add_box.setCurrentIndex(-1)
                self.add_box.blockSignals(False)
            return
        self._add_key = key
        self.add_paints += 1
        self.add_box.blockSignals(True)
        self.add_box.clear()
        self.add_box.addItems(offer)
        self.add_box.setCurrentIndex(-1)
        self.add_box.setPlaceholderText(key[1])
        self.add_box.blockSignals(False)

    def _render_fields(self):
        firsts, seconds = AW.field_choices(self._models, self.first)
        if self.second == self.first:
            self.second = None
        rebuild = (tuple(firsts), tuple(seconds)) != self._field_key
        if rebuild:
            self._field_key = (tuple(firsts), tuple(seconds))
            self.field_paints += 1
        for box, auto, names, now in ((self.box_field1, strings.ANKI_FIELD_AUTO, firsts, self.first),
                                      (self.box_field2, strings.ANKI_ALSO_NONE, seconds, self.second)):
            box.blockSignals(True)
            if rebuild:
                box.clear()
                box.addItem(auto, None)
                for n in names:
                    box.addItem(n, n)
            index = max(0, box.findData(now)) if now else 0
            if box.currentIndex() != index:
                box.setCurrentIndex(index)
            box.blockSignals(False)
        resolved, skipped = AW.field_lines(self._models, self.chosen())
        self._set_label(self.resolved, strings.ANKI_RESOLVED_JOIN.join(
            strings.ANKI_RESOLVED.format(model=m, fields=strings.ANKI_FIELDS_JOIN.join(r)) for m, r in resolved))
        self._set_label(self.skipped, strings.ANKI_RESOLVED_JOIN.join(
            strings.ANKI_SKIPPED.format(model=m) for m in skipped))

    def _paint_controls(self):
        on = AW.controls(self._connected, self.busy(), self.decks, self.chosen())
        on["recheck"] = on["recheck"] and not self._probing
        for widget, key in ((self.btn_sync, "sync"), (self.btn_replace, "replace"), (self.add_box, "add"),
                            (self.box_field1, "field1"), (self.box_field2, "field2"), (self.btn_recheck, "recheck"),
                            (self.chk_suspended, "suspended"), (self.btn_restore, "restore")):
            self._enable(widget, on[key])
        for remove in self.deck_list.findChildren(QToolButton):
            self._enable(remove, on["remove"])

    def _settings_heard(self, keys):
        """A settings write (this window's own, the Settings page's, another window's): the two automation switches
        follow theirs (AD3-5, signals blocked: nothing written back); the doors are asked again only when a module's
        switch moved (the base's rule, IK-20 / IK-45; the language is `language_changed`'s, once the window follows)."""
        if self.gone:
            return
        keys = keys or ()
        settings = None
        for attr, key in SWITCHES:
            if key in keys:
                settings = settings if settings is not None else self._settings()
                box = getattr(self, attr)
                if box.isChecked() != bool(settings.get(key)):
                    box.blockSignals(True)
                    box.setChecked(bool(settings.get(key)))
                    box.blockSignals(False)
        if any(str(k).startswith("enable_") for k in keys):
            self._doors_again()

    def refresh(self):
        """(`windows.follow_doors`) The modules were looked for: the doors asked again."""
        if not self.gone:
            self._doors_again()

    def _doors_again(self):
        """The two doors show while their openers are there and available (row 5's `backfill`, row 2's `apkg_known`)."""
        for attr, name in DOORS:
            button = getattr(self, attr)
            shown = self._door(name) is not None
            if button.isHidden() == shown:
                button.setVisible(shown)

    def _door(self, name):
        op = next((o for o in windows.OPENERS if o.name == name), None)
        if op is None or not windows.available(op, self._settings(), self.language):
            return None
        return op

    def _open_door(self, name):
        op = self._door(name)
        if op is not None:
            windows.launch(self.shell, op)          # this window stays open: a job in flight keeps its result

    # --- Anki's state ------------------------------------------------------------------------------------------- #
    def refresh_connection(self):
        if self.busy() or self._probing or self.gone:
            return
        self._probe_seq += 1
        seq, snap = self._probe_seq, self._snapshot()
        self._probing = seq                               # the probe under way (a newer read may outdate its answer)
        self._paint_state("checking", strings.ANKI_STATE_CHECKING)
        self._paint_controls()
        bridge.run_in_worker(AW.read_probe, snap["url"], snap["decks"], snap["suspended"],
                             then=self.alive(lambda probe: self._probed(probe, seq, snap["language"])),
                             failed=self.alive(lambda info: self._probed(
                                 AW.Probe({"ok": False, "error": str(info[0])}, [], None, {}, {}), seq,
                                 snap["language"])))

    def _probed(self, probe, seq, language):
        if self._probing == seq:
            self._probing = False                         # it ended, whether or not its answer is still the newest
        if seq != self._probe_seq or language != self.language:
            if not self._probing:                         # outdated: the state as it was known before it
                if self._connected:
                    self._paint_state("connected", strings.ANKI_STATE_CONNECTED)
                else:                                     # the first probe, outdated by a scope or language change
                    self._paint_state("unchecked", strings.ANKI_STATE_UNCHECKED)
                    self._paint_controls()
                    self.refresh_connection()             # asked again for the scope shown now (AD3-3)
                    return
            self._paint_controls()
            return
        kind, detail = AW.connection(probe.report)
        self._connected = kind == "connected"
        if self._connected:
            self._paint_state("connected", strings.ANKI_STATE_CONNECTED)
            self.state.setToolTip(strings.ANKI_STATE_TIP_VERSION.format(version=detail) if detail
                                  else strings.ANKI_STATE_TIP)
            self._all_decks = list(probe.decks)
            if probe.preselected is not None:
                self.decks = list(probe.preselected)
                self._unsaved_pick = bool(probe.preselected)
                if probe.preselected:
                    self.say(strings.ANKI_PICKED)
            self._counts, self._models = dict(probe.counts), dict(probe.models)
        else:
            self._paint_state("closed", strings.ANKI_STATE_CLOSED)
            self.state.setToolTip(detail or strings.ANKI_CLOSED_LINE)
            self.say(detail if kind == "problem" else strings.ANKI_CLOSED_LINE)
        self._render()

    def _scope_changed(self):
        """A deck added or removed, a field or *Include suspended* changed: saved, then Anki read for the new scope."""
        self._save_choices()
        self._render()
        self._probe_seq += 1                              # a probe under way was read for the old scope (AD3-3)
        if not self._connected or self.busy():
            return
        seq, snap = self._probe_seq, self._snapshot()
        bridge.run_in_worker(AW.read_scope, snap["url"], snap["decks"], snap["suspended"],
                             then=self.alive(lambda answer: self._scoped(answer, seq, snap["language"])),
                             failed=self.alive(lambda info: seq == self._probe_seq and self.say(
                                 strings.ANKI_SCOPE_FAILED.format(error=info[0]))))

    def _scoped(self, answer, seq, language):
        if seq != self._probe_seq or language != self.language:
            return
        self._counts, self._models = dict(answer[0]), dict(answer[1])
        self._render_decks()
        self._render_fields()
        self._paint_controls()

    # --- the user's edits --------------------------------------------------------------------------------------- #
    def remove_deck(self, deck):
        if self.busy() or deck not in self.decks:
            return
        self.decks = [d for d in self.decks if d != deck]
        self._scope_changed()

    def _add_chosen(self, index):
        deck = self.add_box.itemText(index) if index >= 0 else ""
        if deck and deck in self._all_decks and deck not in self.decks and not self.busy():
            self.decks = self.decks + [deck]
            self._scope_changed()
        else:
            self._render_add()

    def _field1_chosen(self, index):
        if self.box_field1.itemData(index) == self.first:
            return                                        # the same choice: nothing to write or read (IK-46)
        self.first = self.box_field1.itemData(index)
        self._scope_changed()

    def _field2_chosen(self, index):
        if self.box_field2.itemData(index) == self.second:
            return
        self.second = self.box_field2.itemData(index)
        self._scope_changed()

    def _suspended_changed(self, on):
        self.suspended = bool(on)
        self.services.settings.set({"anki_sync_include_suspended": self.suspended})
        self._scope_changed()

    def _toggled(self, key, on):
        self._first_action()
        self.services.settings.set({key: bool(on)})

    # --- the numbers -------------------------------------------------------------------------------------------- #
    def refresh_known(self):
        language = self.language
        bridge.run_in_worker(AW.known_view, language, then=self.alive(lambda known: self._show_known(known, language)),
                             failed=lambda info: applog.log("anki", f"the known words couldn't be read: {info[0]}"))

    def _show_known(self, known, language):
        if language != self.language:
            return
        self._known = known
        self._set_label(self.total, f"{known.total:,}")
        self._set_label(self.backlog, strings.ANKI_BACKLOG[1 if known.backlog == 1 else 0].format(n=known.backlog)
                        if known.backlog else "")
        if self.btn_restore.isHidden() == bool(known.backup):
            self.btn_restore.setVisible(bool(known.backup))
        when = AW.ago(known.last_sync)
        if when is not None and not self.status.text():
            unit, n = when
            ago = strings.ANKI_AGO["day" if unit == "days" and n == 1 else unit].format(n=n)
            self.say(strings.ANKI_LAST.format(ago=ago, n=known.last_added))

    def _automation_state(self, state):
        """The automatic sync wrote this language's known words: the numbers read again (the Tk `refresh_known`). A
        sync by hand ends there too (`Automation.anki_synced`, told before the window hears its result): while the
        window's own job has ended, its `_ended` — right behind — reads them, once (AD-6, S19)."""
        if getattr(state, "sync", None) == "synced" and getattr(state, "language", None) == self.language \
                and state.seq != self._automation_seq:
            self._automation_seq = state.seq
            if self.job is not None and self.job.state not in jobs_module.LIVE:
                return
            self.refresh_known()

    # --- the jobs ----------------------------------------------------------------------------------------------- #
    def _submit(self, label, work, then, on_quit="detach", moved=None):
        """`work` as the window's `anki-sync` job; `then(result)` on this thread when it ended — or, the window closed
        meanwhile, its line in the bottom bar (`_closed_line`): nothing is painted on a closed window (AD3-6). The relay
        lives on the main window and is freed after its one call; the automation service is found when the job ends
        (AD3-9). False when an update holds the children (nothing submitted: the line says so)."""
        relay = bridge.Relay(self.shell)
        services, shell = self.services, self.shell

        def ended(result):
            relay.deleteLater()
            if self.gone:
                line = self._closed_line(label, result)
                if line:
                    windows.say_in_bar(shell, line)
                return
            then(result)
        relay.said.connect(ended)
        job = AW.submit(services.registry, label, work, relay.call, lambda: getattr(services, "automation", None),
                        self.language, on_quit=on_quit, moved=moved)
        if job is None:
            relay.deleteLater()
            self.say(strings.ANKI_UPDATE_WAITS)
            return False
        self.job, self._job_line, self._job_state = job, self.status.text(), None
        self._follow(services.registry.snapshot())
        return True

    def _follow(self, views):
        """The registry's newest snapshot: while the window's job waits its turn (behind an import or the automatic
        sync), the line says what for; once it runs, what it does (the base's IK-22 way; IK-58). Repainted only when
        the job's state changed."""
        job = self.job
        if job is None or self.gone:
            return
        view = next((v for v in views if v.id == job.id), None)
        if view is None or view.state not in (jobs_module.WAITING, jobs_module.RUNNING):
            return
        if (view.state, view.reason) == self._job_state:
            return
        self._job_state = (view.state, view.reason)
        if view.state == jobs_module.WAITING:
            reason = view.reason or ""
            self.say(strings.ANKI_WAITING_FOR.format(what=reason[len(WAITS_FOR):]) if reason.startswith(WAITS_FOR)
                     else strings.ANKI_WAITING.format(reason=reason))
        else:
            self.say(self._job_line)

    def _begin(self, line):
        self.begin_write()
        self.say(line)
        self._paint_controls()

    def _done(self, line=None):
        """A write the window held (a job, a question) ended: the controls come back; a language switch that waited
        happens now (its result also to the bottom bar)."""
        self.end_write(line)
        self._paint_controls()

    def _result_line(self, result):
        kind, n = AW.result_view(result)
        if kind == "error":
            return n["text"]
        if kind == "replaced":
            return (strings.ANKI_REPLACED.format(**n)
                    + (strings.ANKI_REPLACED_GRADUATED.format(**n) if n["graduated"] else "")
                    + (strings.ANKI_REPLACED_IGNORED[1 if n["ignored"] == 1 else 0].format(**n) if n["ignored"]
                       else ""))
        if kind == "restored":
            return strings.ANKI_RESTORED.format(**n)
        if kind == "synced":
            return strings.ANKI_SYNCED.format(**n)
        return ""

    def _closed_line(self, label, result):
        """What the bottom bar says of a job that ended after the window closed: a write's outcome, a write that moved
        nothing because its numbers changed (the window can't ask again: IK-46); a dry run says nothing."""
        if label == strings.ANKI_JOB_DRY or result is None:
            return None
        if result.changed:
            return strings.ANKI_RESTORE_MOVED_CLOSED if label == strings.ANKI_JOB_RESTORE \
                else strings.ANKI_REPLACE_MOVED_CLOSED
        return self._result_line(result) or None

    def _ended(self, result, line=None):
        self.job = None
        line = line if line is not None else self._result_line(result)
        self.say(line)
        if result is not None and not result.error and result.mode in ("delta", "full") and result.added > 0:
            self._set_label(self.delta, strings.ANKI_DELTA.format(n=result.added))
            self._flash.start(FLASH_MS)
        if result is not None and result.total_known:
            self._set_label(self.total, f"{result.total_known:,}")
        self._done(line)
        self.refresh_known()

    def _sync_clicked(self):
        full, self._shift = self._shift, False
        self.on_sync(full=full)

    def on_sync(self, full=False):
        on = AW.controls(self._connected, self.busy(), self.decks, self.chosen())
        if not on["sync"]:
            return
        self._first_action()
        snap = self._snapshot()
        self._begin(strings.ANKI_REREADING if full else strings.ANKI_SYNCING)
        work = (lambda: AW.run_sync(snap["language"], snap["url"], snap["decks"], snap["fields"], snap["suspended"],
                                    full))
        if not self._submit(strings.ANKI_JOB_SYNC, work, self._ended):
            self._done()

    def on_replace(self):
        on = AW.controls(self._connected, self.busy(), self.decks, self.chosen())
        if not on["replace"]:
            return
        self._first_action()
        snap = self._snapshot()
        self._begin(strings.ANKI_READING)
        work = lambda: AW.run_dry(snap["language"], snap["url"], snap["decks"], snap["fields"], snap["suspended"])
        if not self._submit(strings.ANKI_JOB_DRY, work, lambda dry: self._ask_replace(dry, snap)):
            self._done()

    def _ask_replace(self, dry, snap, again=False):
        if dry is None or dry.error:
            self._ended(dry)
            return
        self.say("")
        self.question = confirm.ask(
            self, strings.ANKI_REPLACE_AGAIN_TITLE if again else strings.ANKI_REPLACE_TITLE, replace_body(dry),
            strings.ANKI_REPLACE_YES, strings.ANKI_REPLACE_YES_TIP, no_tip=strings.ANKI_KEEP_TIP, default_no=True,
            danger=True, on_answer=lambda yes: self._replace_answer(yes, dry, snap))

    def _replace_answer(self, yes, dry, snap):
        if not yes:
            self._done()
            return
        self.say(strings.ANKI_REPLACING)
        expect = anki_sync.confirmed(dry)
        work = lambda: AW.run_replace(snap["language"], snap["url"], snap["decks"], snap["fields"], snap["suspended"],
                                      expect)
        if not self._submit(strings.ANKI_JOB_REPLACE, work, lambda result: self._replaced(result, snap),
                            on_quit="wait", moved=strings.ANKI_REPLACE_MOVED_JOB):
            self._done()

    def _replaced(self, result, snap):
        if result is not None and result.changed:
            self._ask_replace(result, snap, again=True)       # the numbers moved: asked again, nothing written
            return
        self._ended(result)

    def on_restore(self):
        if self.busy():
            return
        self._begin(strings.ANKI_READING_BACKUP)          # reads no deck: the first open's pick stays unsaved (IK-46)
        self._read_restore_point(self.language)

    def _read_restore_point(self, language):
        bridge.run_in_worker(AW.restore_point, language,
                             then=self.alive(lambda point: self._ask_restore(point, language)),
                             failed=self.alive(lambda info: self._ended(None, str(info[0]))))

    def _ask_restore(self, point, language, again=False):
        if point is None:
            self._ended(None, strings.ANKI_NOTHING_TO_RESTORE)
            return
        self.say(strings.ANKI_RESTORE_CHANGED if again else "")
        title = (strings.ANKI_RESTORE_TITLE.format(when=point.when.strftime(strings.ANKI_WHEN)) if point.when
                 else strings.ANKI_RESTORE_TITLE_UNDATED)
        body = (strings.ANKI_RESTORE_BODY.format(now=point.now, then=point.then) if point.then is not None
                else strings.ANKI_RESTORE_BODY_UNREAD.format(now=point.now))
        self.question = confirm.ask(self, title, body, strings.ANKI_RESTORE_YES, strings.ANKI_RESTORE_YES_TIP,
                                    no_tip=strings.ANKI_KEEP_TIP, default_no=True, danger=True,
                                    on_answer=lambda yes: self._restore_answer(yes, point, language))

    def _restore_answer(self, yes, point, language):
        if not yes:
            self._done()
            return
        self.say(strings.ANKI_RESTORING)
        if not self._submit(strings.ANKI_JOB_RESTORE, lambda: AW.run_restore(language, point.name, point.now),
                            lambda result: self._restored(result, language), on_quit="wait",
                            moved=strings.ANKI_RESTORE_MOVED_JOB):
            self._done()

    def _restored(self, result, language):
        if result is not None and result.changed:            # another backup by now: read again, asked again
            bridge.run_in_worker(AW.restore_point, language,
                                 then=self.alive(lambda point: self._ask_restore(point, language, again=True)),
                                 failed=self.alive(lambda info: self._ended(None, str(info[0]))))
            return
        self._ended(result)

    # --- the language ------------------------------------------------------------------------------------------- #
    def language_changed(self, language):
        """Idle, the main window's language changed: this window reads again for it (its decks, fields, Anki's scope,
        the numbers); the old language's line goes."""
        self._probe_seq += 1
        self._probing = False
        self._counts, self._models = {}, {}
        self._unsaved_pick = False
        self._load_choices()
        self.chk_suspended.blockSignals(True)
        self.chk_suspended.setChecked(bool(self.suspended))
        self.chk_suspended.blockSignals(False)
        self.heading.setToolTip(strings.ANKI_HEADING_TIP.format(language=strings.ANKI_LANGUAGES.get(language)))
        self.say("")
        self._set_label(self.delta, "")
        self._render()
        self._doors_again()
        self.refresh_known()
        if self._connected:
            self.refresh_connection()                     # Anki's scope for this language (its first-open pick too)


def replace_body(dry):
    """The Replace confirmation's body: now → after, what Anki brings, a "kept" line only for what is kept (IK-44)."""
    lines = [strings.ANKI_REPLACE_HEAD.format(now=dry.total_known, after=dry.total_after),
             strings.ANKI_REPLACE_ANKI.format(n=dry.added)]
    for n, words in ((dry.kept_graduated, strings.ANKI_REPLACE_GRADUATED),
                     (dry.kept_ignored, strings.ANKI_REPLACE_IGNORED)):
        if n:
            lines.append(words[1 if n == 1 else 0].format(n=n))
    lines.append(strings.ANKI_REPLACE_TAIL)
    return "\n".join(lines)


def open_anki(shell):
    """The door: one Anki window per main window, raised when open."""
    return windows.show(shell, NAME, AnkiWindow)
