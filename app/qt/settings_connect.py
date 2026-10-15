"""Settings' writing rows of Connect and Anki (W3.3 P8; the RUNBOOK's P5 / P8 / P9 rows, its resolutions (c), (e), N1,
N11): the three rows the page leaves an empty slot for (`SettingsPage.custom_row`), filled here.

`attach(page)` -> `ConnectRows`: called once by whoever mounts the page (P7), after the page is made — never by the page
itself, so a page made without the window (P3's tests) never talks to Anki. Nothing of Connect or Anki is imported when
Settings opens (H11's spirit; only the pure `settings_values` the catalog already reads): every Connect / Anki call
imports its module on the worker that runs it, and the reads start when the page is built (`ready`).

- **Connect's switch** (`connect_enabled`, *Make cards for me*): a `Toggle`. A change greys it and runs the switch on a
  worker — `app/connect/switch.py`, P3.1's own sequence beside the settings service (N11: `save_keys(strict)` there, so
  this page writes nothing itself). **On:** `turn_on` (the watermarks, then the save, then surasura.json); not ok → back
  off, the reason in the bar; ok → `backfill` (hato's pairings), then `services.settings.reload()` on that same worker
  (the service learns the file), the toggle given back and the write told (`bridge.settings_written`): the page shows
  Connect's rows, the shell asks Connect's line. **Off:** `shelved` on a worker; cards on the shelf → asked (2.x's
  words; Esc / No = not put back, Connect still turns off), then `put_back` (its waiting line in the bar); one not put
  back → *Turn Connect off anyway?* (No: it stays on); then `turn_off`; a failure → back on, the reason in the bar. One
  run at a time. The page going while it runs never cuts a worker's step; nothing is painted after it is gone, and a
  question open as the window closes answers nothing (`confirm`'s rule): the switch stays as the file says.
- **The Anki Miner card** (Connections' *Anki Miner* row; U5): `setup.checks` on a worker → *Not installed* ·
  *Installed <v> — needs setup* (the missing pieces, the two guided steps with *Copy path*) · *Ready*; *Install Anki
  Miner…* (`install_anki_miner`: Anki Miner's releases page in the browser — W3.5 part 3 swaps in its in-Surasura route
  there) with **AM★** beside it, *Like Anki Miner? Star it on GitHub ★*; *Browse…* (`connect_anki_miner_path`, through
  the settings service); *Open Anki Miner*; *Check again*; *Anki Miner X is out* while `status.anki_miner_update` says
  so. U6: installed, the bigger ⭐ suggestion until one click or *Not now* (kept in local data `star.json`, never
  settings.json), then the small link.
- ***New cards a day*** (G1.2-5; `app/anki_deck_options.py`): Anki's value for Junban's deck read on a worker → the
  number, *from Anki (deck: X)* and *Change in Anki…*; the click → the confirmation naming the deck (default No) → the
  write on a worker (its waiting line while the Anki-writing lock is held elsewhere; cancelled when the page goes) →
  the outcome in the bar, and `words_per_day` saved through the service as `words_per_day_after` says. Anki unreadable →
  the row is `words_per_day`, an editable number (saved through the service), with why on hover.

GUI_Design_Guidelines_Qt: the page's own controls and label styles (no new rules), a tooltip on every button.
"""
import os
import threading
from contextlib import contextmanager

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from app import theme
from app.connect import settings_values
from app.qt import applog, bridge, confirm, style, windows
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_strings as S
from app.services import settings as settings_service

CARD_W = 380                    # the Anki Miner card's widest (px at text size M): its lines wrap inside it
MAX_PER_DAY = 9999              # Anki's own ceiling for New cards a day (`anki_deck_options.MAX_PER_DAY`)
PACE_MAX = 10 ** 6              # `words_per_day`'s, where the catalog names none (the page's `BIG`)


def _f():
    return theme.text_factor(style.current()[1])


def _alive(w):
    return w is not None and not sip.isdeleted(w)


def attach(page):
    """The three rows filled into `page`'s slots -> their `ConnectRows` (kept by the page as a child)."""
    return ConnectRows(page)


# --- the workers' steps (no widget touched; each imports what it calls) ------------------------------------------- #
def _switch():
    from app.connect import switch
    return switch


def _switch_on(store, log):
    """(A worker.) `turn_on`, then — ok — hato's back-fill and the service's reload -> (ok, why). The file read first:
    Connect already on there (another window switched it) → no `turn_on` (no watermark moved), only the reload."""
    switch = _switch()
    if store.fresh().get("connect_enabled"):
        store.reload()
        log(S.SWITCH_ALREADY_ON)
        return True, None
    ok, saved, why = switch.turn_on(switch.CONNECT_LANGUAGES, log=log)
    if not ok:
        return False, why
    switch.backfill(switch.CONNECT_LANGUAGES, saved, log=log)
    store.reload()
    return True, None


def _switch_off_start(was_on, store, log):
    """(A worker.) The shelf looked at (a switch that was on); with cards on it -> ("ask", shelved) for the question;
    else the switch saved off here -> ("off", ok, why)."""
    switch = _switch()
    shelved = switch.shelved(switch.CONNECT_LANGUAGES) if was_on else {}
    if shelved:
        return ("ask", shelved)
    return _turn_off(switch, was_on, store, log)


def _switch_off(put_back, store, log, waiting):
    """(A worker.) The shelf put back when asked: one not put back -> ("failed", the reasons); then the switch saved
    off -> ("off", ok, why)."""
    switch = _switch()
    if put_back:
        failed = switch.put_back(put_back, log=log, waiting=waiting)
        if failed:
            return ("failed", failed)
    return _turn_off(switch, True, store, log)


def _turn_off(switch, was_on, store, log):
    ok, _saved, why = switch.turn_off(was_on=was_on, log=log, languages=switch.CONNECT_LANGUAGES)
    if ok:
        store.reload()
    return ("off", ok, why)


def _saved_off(answer):
    """An off step's answer: the switch saved the file off."""
    return answer[0] == "off" and answer[1]


def _miner_look(settings, language):
    """(A worker.) -> (`setup.checks`, the star answered, the whitelist file's path, the update notice or None)."""
    from app.connect import anki_miner, setup, status
    path = anki_miner.whitelist_path(language)
    return setup.checks(settings, language), settings_values.star_answered(), path, status.anki_miner_update()


def _read_new_cards(settings):
    """(A worker.) -> (the deck, Anki's `Reading` or None, why it can't be read or None, the number the row shows)."""
    from app import anki_deck_options as ado
    deck = ado.deck_for(settings)
    reading = ado.read_new_per_day(settings, deck)
    if isinstance(reading, ado.Reading):
        return deck, reading, None, reading.value
    return deck, None, str(reading), ado.row_number(settings, reading)


def _write_new_cards(settings, deck, value, expect, cancel, say):
    """(A worker.) The confirmed write, waiting for the Anki-writing lock (its line said) -> `Outcome`."""
    from app import anki_connect
    from app import anki_deck_options as ado
    return ado.write_new_per_day(settings, deck, value, expect, wait=None, cancel=cancel,
                                 on_wait=lambda holder: say(anki_connect.waiting_line(holder)))


def install_anki_miner():
    """*Install Anki Miner…*: its releases page in the browser, as 2.x does. W3.5 part 3 replaces this one call with its
    in-Surasura route (G1.3-2)."""
    from app.connect import setup
    return windows.open_url(setup.RELEASES)


def ask_miner_file(parent):
    """*Browse…*'s file dialog -> the program chosen, or ""."""
    path, _filter = QFileDialog.getOpenFileName(parent, S.BROWSE_MINER_TITLE, "", S.BROWSE_MINER_FILTER)
    return path or ""


def _button(text, tip, on_click, parent, kind=None):
    b = sc.Door(text, tooltip=tip, parent=parent)
    if kind:
        b.setObjectName(kind)
    b.clicked.connect(lambda _c=False: on_click())
    return b


def _label(text, name, parent):
    w = QLabel(text, parent)
    w.setObjectName(name)
    w.setWordWrap(True)
    w.setTextFormat(Qt.TextFormat.PlainText)
    return w


class ConnectRows(QObject):
    """The three rows: `switch` (SwitchRow), `miner` (MinerCard), `new_cards` (NewCardsRow); the bar's lines through
    `say` (the shell's bottom bar; nothing without a shell)."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.store = page.store
        self.cancel = threading.Event()             # set when the page goes: a write waiting for Anki's lock stops
        cancel = self.cancel
        page.destroyed.connect(lambda *_: cancel.set())
        self.lines = bridge.Relay(self)             # a worker's lines (the switch's log, a waiting line) -> the bar
        self.lines.said.connect(self.say)
        self.switch = SwitchRow(self, page.custom_row("connect_enabled"))
        self.miner = MinerCard(self, page.custom_row("anki_miner"))
        self.new_cards = NewCardsRow(self, page.custom_row("new_cards_a_day"))
        page.bridge.settings_written.connect(self._written)
        switched = getattr(page, "language_set", None)        # P4's signal: Anki Miner's checks are per language
        if switched is not None:
            switched.connect(lambda _language: self.miner.check() if self.alive() else None)
        if page.built:
            self._ready()
        else:
            page.ready.connect(self._ready)

    def alive(self):
        return _alive(self.page)

    def settings(self):
        """The service's settings now, as a plain dict (a worker's input)."""
        return settings_service.thaw(self.store.get())

    def say(self, text):
        if text and self.alive():
            applog.log("settings", text)
            windows.say_in_bar(self.page.shell, text)

    @contextmanager
    def holding(self):
        """A late answer that resizes a row (the card's state, the deck's help line, the field shown) keeps the
        reader's place (`SettingsPage.hold`: the control last changed, else the first row in view, keeps its y). The
        layouts settled once more inside: a re-wrapped help line re-flows deeper than the hold's own settle reaches."""
        with self.page.hold(self.page._last):
            yield
            if self.alive():
                self.page._settle()

    def _ready(self):
        if not self.alive():
            return
        self.page._tab_order()                    # the three rows' widgets are made after the build: Tab in place
        self.miner.check()
        self.new_cards.read()

    def _written(self, keys):
        """A write landed (the service's, or the switch's told): the rows showing its keys follow it."""
        if not self.alive():
            return
        keys = set(keys)
        if "connect_enabled" in keys:
            self.switch.follow()
        if "connect_anki_miner_path" in keys:
            self.miner.check()
        if keys & {"junban_deck", "junban_scope", "anki_connect_url"}:
            self.new_cards.read()
        elif "words_per_day" in keys:
            self.new_cards.follow()


# --- Connect's switch --------------------------------------------------------------------------------------------- #
class SwitchRow(QWidget):
    """The toggle; `running` while its worker goes (the toggle greyed, one run at a time)."""

    def __init__(self, rows, slot):
        super().__init__(slot)
        self.rows, self.page = rows, rows.page
        row = catalog.ROW["connect_enabled"]
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        self.toggle = sc.Toggle(bool(rows.store.get().get("connect_enabled")), tooltip=row.tip, name=row.label,
                                parent=self)
        self.toggle.changed.connect(self._toggled)
        line.addWidget(self.toggle)
        slot.layout().addWidget(self)
        self.running = False
        self.asking = None                        # the question open now (a `confirm.Confirm`), if any

    def _saved(self):
        return bool(self.rows.store.get().get("connect_enabled"))

    def follow(self):
        """Another write named the switch: shown as saved (never while the switch's own run goes)."""
        if not self.running:
            self.toggle.set_value(self._saved())

    def _toggled(self, on):
        if self.running:                          # one run at a time (greyed: only a programmatic change gets here)
            self.toggle.set_value(not on)
            return
        was_on = self._saved()
        self.running = True
        self.toggle.setEnabled(False)
        store, log = self.rows.store, self.rows.lines.call
        if on:
            bridge.run_in_worker(_switch_on, store, log, then=self._later(self._on_done, lambda a: a[0]),
                                 failed=self._broke)
        else:
            bridge.run_in_worker(_switch_off_start, was_on, store, log, then=self._later(self._off_step, _saved_off),
                                 failed=self._broke)

    def _later(self, step, saved):
        """A worker's answer -> `step` while the page is there; the page gone, only the write still told on the
        shell's bridge when `saved(answer)` (the switch saved the file: the shell's Connect line follows). A plain
        function, not this row's method: Qt drops a dead widget's slots, and the tell needs no page."""
        rows, heard = self.rows, self.page.bridge

        def then(answer):
            if rows.alive():
                step(answer)
            # the page gone: an off that would ask first is a question nobody saw — as one dropped with its window it
            # answers nothing (confirm's rule): Connect stays on, as saved
            elif saved(answer) and _alive(heard):
                heard.settings_written.emit(("connect_enabled",))
        return then

    def _on_done(self, answer):
        ok, why = answer
        if not ok:
            self.rows.say(S.SWITCH_NOT_ON.format(why))
        self._finish(ok, told=ok)

    def _off_step(self, answer):
        if not self.rows.alive():
            return
        if answer[0] == "ask":
            self._ask_put_back(answer[1])
        elif answer[0] == "failed":
            self._ask_off_anyway(answer[1])
        else:
            _off, ok, why = answer
            if not ok:
                self.rows.say(S.SWITCH_NOT_OFF.format(why))
            self._finish(not ok, told=ok)

    def _ask_put_back(self, shelved):
        """IK-D1 (S16, gate (b)): switched off with cards on the shelf, asked once; Connect turns off either way."""
        n = sum(cards for cards, _runs in shelved.values())
        self._ask(S.PUT_BACK_ASK.format(n=n, cards="card" if n == 1 else "cards"), S.PUT_BACK_BODY, S.PUT_BACK_YES,
                  S.PUT_BACK_YES_TIP, S.PUT_BACK_NO, S.PUT_BACK_NO_TIP,
                  lambda yes: self._off(shelved if yes else None))

    def _ask_off_anyway(self, failed):
        """Shelved cards weren't put back: Connect stays on unless you turn it off anyway."""
        def answered(yes):
            if yes:
                self._off(None)
                return
            self.rows.say(S.STAYS_ON)
            self._finish(True)
        self._ask(S.OFF_ANYWAY_ASK, S.OFF_ANYWAY_BODY.format(failed="\n".join(failed)), S.OFF_ANYWAY_YES,
                  S.OFF_ANYWAY_YES_TIP, S.OFF_ANYWAY_NO, S.OFF_ANYWAY_NO_TIP, answered)

    def _ask(self, title, body, yes, yes_tip, no, no_tip, then):
        def answered(value):
            self.asking = None
            then(value)
        self.asking = card = confirm.ask(self.page, title, body, yes, yes_tip, no=no, no_tip=no_tip, default_no=True,
                                         on_answer=answered)
        card.destroyed.connect(self._ask_gone)    # (a slot of this row: never called once the row is gone)

    def _ask_gone(self, *_):
        """A question that went unanswered (its window closed or hid): nothing more is done; the switch shows what is
        saved (still on)."""
        if self.asking is not None and sip.isdeleted(self.asking):
            self.asking = None
            if self.rows.alive():
                self._finish(self._saved())

    def _off(self, put_back):
        store, log = self.rows.store, self.rows.lines.call
        waiting = lambda: log(self._waiting_line())          # noqa: E731
        bridge.run_in_worker(_switch_off, put_back, store, log, waiting, then=self._later(self._off_step, _saved_off),
                             failed=self._broke)

    @staticmethod
    def _waiting_line():
        return _switch().PUT_BACK_WAITING

    def _broke(self, info):
        """The worker itself failed (not a `why`): the switch shows what is saved."""
        applog.log("settings", f"Connect's switch: {info[1]}")
        self.rows.say(S.SWITCH_BROKE.format(info[0]))
        self._finish(self._saved())

    def _finish(self, on, told=False):
        """The run ended: the toggle shows `on` and is given back; `told`: the switch saved the file (the service
        reloaded it) — the page and the shell hear the write."""
        if not self.rows.alive():
            return
        self.running = False
        self.toggle.set_value(on)
        self.toggle.setEnabled(True)
        if told:
            self.page.bridge.settings_written.emit(("connect_enabled",))


# --- the Anki Miner card ------------------------------------------------------------------------------------------ #
class MinerCard(QWidget):
    """U5 / U6 / AM★ in the *Anki Miner* row's slot. `state`: `card_state`'s answer (None: unchecked or failed)."""

    def __init__(self, rows, slot):
        super().__init__(slot)
        self.rows, self.page = rows, rows.page
        self.state = None
        self.path = ""
        self.update_url = None
        self.checking = self.again = False
        self.setMaximumWidth(round(CARD_W * _f()))
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(round(6 * _f()))
        self.words = _label(S.MINER_CHECKING, "settingsvalue", self)
        box.addWidget(self.words)
        self.update_note = _button("", S.MINER_UPDATE_TIP, self._open_update, self, kind="settingsmore")
        self.update_note.hide()
        box.addWidget(self.update_note, 0, Qt.AlignmentFlag.AlignLeft)
        # U6: the bigger suggestion, once installed, until one click or Not now
        self.star_box = QWidget(self)
        star = QVBoxLayout(self.star_box)
        star.setContentsMargins(0, 0, 0, 0)
        star.addWidget(_label(S.STAR_ASK, "settingshelp", self.star_box))
        star_row = QHBoxLayout()
        self.star_button = _button(S.STAR_BUTTON, S.STAR_BUTTON_TIP, self._starred, self.star_box)
        self.not_now = _button(S.NOT_NOW, S.NOT_NOW_TIP, self._not_now, self.star_box)
        star_row.addWidget(self.star_button)
        star_row.addWidget(self.not_now)
        star_row.addStretch(1)
        star.addLayout(star_row)
        self.star_box.hide()
        box.addWidget(self.star_box)
        self.missing = QVBoxLayout()                # the missing pieces' sentences, drawn again on each check
        self.missing.setSpacing(round(2 * _f()))
        box.addLayout(self.missing)
        self.steps = self._build_steps()
        self.steps.hide()
        box.addWidget(self.steps)
        buttons = QHBoxLayout()
        buttons.setSpacing(round(8 * _f()))
        self.install = _button(S.INSTALL_MINER, S.INSTALL_MINER_TIP, self._install, self)
        self.star_line = _button(S.STAR_LINE, S.STAR_LINE_TIP, self._starred, self, kind="settingsmore")   # AM★
        self.browse = _button(S.BROWSE_MINER, S.BROWSE_MINER_TIP, self._browse, self)
        self.open_miner = _button(S.OPEN_MINER, S.OPEN_MINER_TIP, self._open, self)
        self.check_again = _button(S.CHECK_AGAIN, S.CHECK_AGAIN_TIP, self.check, self)
        for b in (self.install, self.star_line, self.browse, self.open_miner, self.check_again):
            buttons.addWidget(b)
        buttons.addStretch(1)
        box.addLayout(buttons)
        self.star_link = _button(S.STAR_LINK, S.STAR_LINK_TIP, self._open_star, self, kind="settingsmore")
        box.addWidget(self.star_link, 0, Qt.AlignmentFlag.AlignLeft)
        self._buttons(None, answered=True)
        slot.layout().addWidget(self)

    def _build_steps(self):
        steps = QWidget(self)
        box = QVBoxLayout(steps)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(round(4 * _f()))
        box.addWidget(_label(S.MINER_STEP_1, "settingshelp", steps))
        box.addWidget(_label(S.MINER_STEP_2, "settingshelp", steps))
        line = QHBoxLayout()
        self.path_field = QLineEdit(steps)
        self.path_field.setObjectName("settingsfield")
        self.path_field.setReadOnly(True)
        self.path_field.setAccessibleName(S.MINER_PATH_NAME)
        self.path_field.setToolTip(S.MINER_PATH_NAME)
        self.copy = _button(S.COPY_PATH, S.COPY_PATH_TIP, self._copy, steps)
        line.addWidget(self.path_field, 1)
        line.addWidget(self.copy)
        box.addLayout(line)
        box.addWidget(_label(S.MINER_STEP_BOLD, "settingslabel", steps))
        return steps

    def check(self):
        """`setup.checks` (and the star's answer, the whitelist path, the update notice) on a worker; then drawn. Asked
        while one runs (a Browse, a language switch): once more when it ends, so the card never shows an older path."""
        if not self.rows.alive():
            return
        if self.checking:
            self.again = True
            return
        self.checking, self.again = True, False
        with self.rows.holding():
            self.words.setText(S.MINER_CHECKING)
        self.check_again.setEnabled(False)
        bridge.run_in_worker(_miner_look, self.rows.settings(), self.page.language, then=self._show,
                             failed=self._broke)

    def _show(self, answer):
        if not self.rows.alive():
            return
        self.checking = False
        self.check_again.setEnabled(True)
        if self.again:
            return self.check()
        result, answered, path, update = answer
        state = settings_values.card_state(result)
        self.state, self.path = state, path or ""
        with self.rows.holding():
            self.words.setText(state["say"])
            self._missing(state["missing"])
            self.path_field.setText(self.path)
            self.steps.setVisible(bool(state["steps"]))
            self.update_url = update.get("url") if update else None
            self.update_note.setText(S.MINER_UPDATE.format(version=update["version"]) if update else "")
            self.update_note.setVisible(bool(update))
            self._buttons(state["state"], answered)

    def _broke(self, info):
        if not self.rows.alive():
            return
        self.checking = False
        self.check_again.setEnabled(True)
        if self.again:
            return self.check()
        self.state = None
        with self.rows.holding():
            self.words.setText(S.MINER_NOT_CHECKED.format(info[0]))
            self._missing([])
            self.steps.hide()
            self.update_note.hide()
            self._buttons(None, answered=True)

    def _missing(self, lines):
        while self.missing.count():
            w = self.missing.takeAt(0).widget()
            if w is not None:
                w.hide()                          # gone from the layout now, not when the loop deletes it
                w.deleteLater()
        for line in lines:
            w = _label(line, "settingshelp", self)
            self.missing.addWidget(w)
            w.show()                              # shown now (the layout would show it a turn later: the page moves)

    def _buttons(self, state, answered):
        """Not installed (or not checked): Install with the star line beside it, Browse…; installed: Open Anki Miner,
        and the ⭐ suggestion until answered, then the small link. Check again always."""
        missing = state in (None, "missing")
        self.install.setVisible(missing)
        self.star_line.setVisible(missing)
        self.browse.setVisible(missing)
        self.open_miner.setVisible(not missing)
        self.star_box.setVisible(not missing and not answered)
        self.star_link.setVisible(not missing and answered)

    # the clicks
    def _install(self):
        install_anki_miner()

    def _open_update(self):
        if self.update_url:
            windows.open_url(self.update_url)
        else:
            install_anki_miner()

    def _open_star(self):
        windows.open_url(settings_values.STAR_URL)

    def _starred(self):
        self._open_star()
        self._answer("starred")

    def _not_now(self):
        self._answer("not-now")

    def _answer(self, answer):
        """U6: kept in local data (`star.json`) on a worker, never settings.json; the suggestion gives way to the
        link."""
        if self.state is not None and self.state["state"] != "missing":
            self.star_box.hide()
            self.star_link.show()
        bridge.run_in_worker(settings_values.answer_star, answer,
                             failed=lambda info: applog.log("settings", f"the star's answer: {info[1]}"))

    def _copy(self):
        QApplication.clipboard().setText(self.path)
        self.rows.say(S.PATH_COPIED)

    def _browse(self):
        path = ask_miner_file(self.page)
        if not path:
            return
        row = catalog.ROW["anki_miner"]
        changes, _update = catalog.change(row, self.rows.settings(), self.page.language, os.path.normpath(path))
        if changes:
            self.rows.store.set(changes)
        self.check()

    def _open(self):
        path = (self.state or {}).get("path")
        if path and not windows.open_url(path):
            self.rows.say(S.MINER_NOT_OPENED.format(path))


# --- New cards a day ------------------------------------------------------------------------------------------------ #
class NewCardsRow(QWidget):
    """The number, its *from Anki (deck: X)* and *Change in Anki…*. `reading`: Anki's `Reading` (None: not read, or
    Anki unreadable — then the number is `words_per_day`, saved through the service)."""

    def __init__(self, rows, slot):
        super().__init__(slot)
        self.rows, self.page = rows, rows.page
        self.row = catalog.ROW["new_cards_a_day"]
        self.reading = None
        self.unread = False                       # Anki answered it can't be read: the field is words_per_day
        self.busy = False                         # a confirmed write on its way
        self.stale = False                        # a read asked (or dropped) while it went: read once it ends
        self.reads = 0                            # the read the answer belongs to (a later read wins)
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(round(8 * _f()))
        self.field = sc.NumberField(0, MAX_PER_DAY, 0, tooltip=S.NEW_CARDS_FIELD_TIP, name=self.row.label, parent=self)
        self.field.changed.connect(self._typed)
        self.field.hide()
        self.words = _label(S.NEW_CARDS_READING, "settingsaffix", self)
        self.words.setWordWrap(False)
        self.change = _button(S.CHANGE_IN_ANKI, S.CHANGE_IN_ANKI_TIP, self._change, self)
        self.change.hide()
        line.addWidget(self.field)
        line.addWidget(self.words)
        line.addWidget(self.change)
        slot.layout().addWidget(self)
        self.waits = bridge.Relay(self)           # the write's waiting line (from its worker)
        self.waits.said.connect(self._waiting)

    def read(self):
        """Anki's value for the deck, on a worker (no lock: one read). Asked while a write goes (a deck or address
        changed meanwhile): read when it ends."""
        if not self.rows.alive():
            return
        if self.busy:
            self.stale = True
            return
        self.reads += 1
        n = self.reads
        bridge.run_in_worker(_read_new_cards, self.rows.settings(), then=lambda answer: self._shown(n, answer),
                             failed=lambda info: self._shown(n, ("", None, str(info[0]), None)))

    def _shown(self, n, answer):
        if not self.rows.alive() or n != self.reads:
            return
        if self.busy:                             # the newest read, landed while a write goes: read again after it
            self.stale = True
            return
        with self.rows.holding():
            self._show(*answer)

    def _show(self, deck, reading, why, number):
        view = self.page.row(self.row.id)
        if view is not None:
            view.set_words(self.row.label, self.row.help.format(
                deck=S.NEW_CARDS_DECK.format(deck=deck) if deck else S.NEW_CARDS_NO_DECK))
        if reading is not None:
            self.reading, self.unread = reading, False
            self.field.maximum = MAX_PER_DAY
            self.field.set_value(reading.value)
            self.field.setToolTip(S.NEW_CARDS_FIELD_TIP)
            self.field.edit.setToolTip(S.NEW_CARDS_FIELD_TIP)
            self.words.setText(S.NEW_CARDS_FROM_ANKI.format(deck=reading.deck))
            self.words.show()
            self.change.show()
        else:
            self.reading, self.unread = None, True
            tip = S.NEW_CARDS_UNREAD_TIP.format(why=why or "")
            self.field.maximum = PACE_MAX
            if number is None:                                            # a read that broke: the pace as saved
                number = catalog.value_of(self.rows.store.get(), "words_per_day")
            self.field.set_value(number or 0)
            self.field.setToolTip(tip)
            self.field.edit.setToolTip(tip)
            self.words.hide()
            self.change.hide()
        self.field.show()
        self.field.setEnabled(True)

    def follow(self):
        """`words_per_day` written elsewhere: shown while it is the row's number (Anki unreadable)."""
        if self.unread and not self.busy:
            self.field.set_value(catalog.value_of(self.rows.store.get(), "words_per_day") or 0)

    def _typed(self, n):
        """A number committed: Anki's is held until *Change in Anki…*; the pace (Anki unreadable) is saved at once."""
        if not self.unread:
            return
        changes, _update = catalog.change(self.row, self.rows.settings(), self.page.language, n)
        if changes:
            self.rows.store.set(changes)

    def _change(self):
        if self.busy or self.reading is None:
            return
        if self.field.edit.hasFocus():
            self.field.edit.clearFocus()          # the typed number committed first (the button takes no focus)
        from app import anki_deck_options as ado
        reading, value = self.reading, self.field.value()
        if value == reading.value:
            self.rows.say(S.NEW_CARDS_SAME.format(deck=reading.deck, n=value))
            return
        confirm.ask(self.page, S.NEW_CARDS_ASK, ado.confirmation(reading, value), S.NEW_CARDS_YES.format(n=value),
                    S.NEW_CARDS_YES_TIP, default_no=True,
                    on_answer=lambda yes: self._answered(yes, reading, value))

    def _answered(self, yes, reading, value):
        """The question's answer. Anki read again while it was open: a Yes goes on only when the deck and the number
        are still the ones asked about; else refused, and the bar says why."""
        if not self.rows.alive() or self.busy:
            return
        now = self.reading
        same = now is not None and (now.deck, now.value) == (reading.deck, reading.value)
        if not yes or not same:
            if now is not None:
                self.field.set_value(now.value)
            if yes:
                self.rows.say(_reread_line(reading, now))
            return
        self.busy = True
        self.field.setEnabled(False)
        self.change.setEnabled(False)
        rows, store = self.rows, self.rows.store

        def written(outcome):                     # a plain function: the pace saved though the page went (S1)
            _save_pace(store, outcome)            # first: no painting can stop it
            if rows.alive():
                self._written(outcome)
        bridge.run_in_worker(_write_new_cards, self.rows.settings(), reading.deck, value, reading.value,
                             self.rows.cancel, self.waits.call, then=written, failed=self._broke)

    def _waiting(self, line):
        if self.rows.alive() and self.busy:
            self.change.setText(S.NEW_CARDS_WAITING)
            self.rows.say(line)

    def _written(self, outcome):
        """The write's end painted (the pace is saved beside it, page or not: `_save_pace`)."""
        self.rows.say(outcome.message)
        if outcome.value is not None and self.reading is not None:
            self.reading = self.reading._replace(value=outcome.value)     # Anki's number now (a moved one too)
        self.field.set_value(self.reading.value)
        self._done()

    def _broke(self, info):
        if not self.rows.alive():
            return
        self._done()
        self.rows.say(S.NEW_CARDS_BROKE.format(info[0]))
        if self.reading is not None:
            self.field.set_value(self.reading.value)

    def _done(self):
        self.busy = False
        self.field.setEnabled(True)
        self.change.setEnabled(True)
        self.change.setText(S.CHANGE_IN_ANKI)
        if self.stale:                            # a deck or address changed while the write went: read it now
            self.stale = False
            self.read()


def _save_pace(store, outcome):
    """A confirmed write's end: `words_per_day` saved as `words_per_day_after` says — Anki took the number (`ok`, or
    `took` with other options of the group back different) — through the service, whether or not the page is there."""
    if not (outcome.ok or outcome.took):
        return
    from app import anki_deck_options as ado
    changes = ado.words_per_day_after(settings_service.thaw(store.get()), outcome)
    if changes:
        store.set(changes)


def _reread_line(asked, now):
    """Why a Yes wrote nothing: Anki was read again while the question was open (`now`: the new reading, or None)."""
    if now is None:
        return S.NEW_CARDS_UNREAD_NOW
    if now.deck != asked.deck:
        return S.NEW_CARDS_DECK_MOVED.format(asked=asked.deck, deck=now.deck)
    return S.NEW_CARDS_VALUE_MOVED.format(deck=now.deck, n=now.value)
