"""Settings' store rows and *Set up again* (W3.3 P6, after W3.1a's writer landed; W3.5 part 3's *Set up again*): drawn
into the slots the page leaves for them (`custom_row`).

`attach(page)` -> `StoreRows`: called once by whoever mounts the page (the shell's `mount_settings`), beside
`settings_connect.attach(page)` — never by the page itself.

- ***Soon starts after N files*** (`soon_line`, Content) and ***Mine automatically: the top N files*** (`mine_line`,
  Anki & mining, with Connect on): a number each. They are the library's own values, not settings.json's: shown from
  the library reader's options (`LibraryReader.options()`, repainted when its view lands — another window's write too),
  written through the window's writer (`moves.Writer.set_options`, queued with the window's moves on its own thread:
  the page's thread never touches the store). A library with no Soon line yet shows how many files NOW holds (nothing
  written by showing it); a mine line not set shows the store's default (`MINE_LINE_DEFAULT`, 20). No library, no
  writer, or the library not read yet: the field is greyed and says why; a change the writer refuses (read-only)
  goes back to the library's value, the reason in the bar.
- ***Keep studying watched episodes*** (`keep_watched`, Content; W-1): the library's own option too, a toggle — shown
  from the reader's options (absent: off), written through `Writer.set_options(keep_watched=)` (one command). It flips in
  the frame of the press; a refused write flips it back, the reason in the bar. Greyed with no library (as the lines)
  and with a library that can't be saved (its tip the store's reason).
- ***Set up again*** (App): the setup wizard over the window, preselected from the settings now
  (`first_run.open_again`).
- **`resume_connect(before, changes)`** (Michi's W-A7 / the intent keeper's B2, G1.1-2): a write through the settings
  service that can turn Connect on — `connect_enabled` (the wizard's *Make cards for me*) or `logic.automation`
  (Settings' automation row) — then calls `app/connect/resume.turned_on(before, after)` on a worker: off → on moves
  Connect's watermarks, so nothing that arrived while it was off is mined; anything else does nothing there. Connect's
  own switch (`settings_connect`) needs none: `switch.turn_on` sets the watermarks before its save.
- **`kick_on_release(before, changes)`** (laptop try rows 9 and 42): a setting that lets waiting episodes go —
  *Trust my subtitles' timing* turned on (P-LF-9), or *Keep up to N cards waiting* changed — kicks Connect (`kick.kick`,
  on a worker): started if it isn't running, woken if it is (its wake mark), so the episodes waiting as *Not timed* or
  at the cap are tried again now, never at its next start or its 2-minute look.

GUI_Design_Guidelines_Qt: the page's controls (no new rules), a tooltip on every field and button.
"""
from PyQt6 import sip
from PyQt6.QtCore import QObject

from app.qt import applog, bridge, strings, windows
from app.qt import press as qpress
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_strings as S
from app.services.view_rows import keep_watched          # W-1: the feed's option, read one way

LINES = ("soon_line", "mine_line")
CONNECT_KEYS = ("connect_enabled", "logic.automation")      # the two keys `settings_manager.connect_on` reads
MINE_LINE_DEFAULT = 20          # the store's (`library_store.MINE_LINE_DEFAULT`; not imported: the store is heavy here)
CEILING = 100000                # a line further down than any library: the field's top


def _alive(w):
    return w is not None and not sip.isdeleted(w)


def resume_connect(before, changes):
    """After a settings write of `changes` onto `before` (the settings as they were): when it holds a key Connect's
    gate reads, `resume.turned_on(before, after)` on a worker (it does nothing unless Connect went off -> on). -> True
    when it was asked."""
    if not any(key in changes for key in CONNECT_KEYS):
        return False
    from app.services import settings as settings_service
    before = settings_service.thaw(before) if before is not None else {}
    after = settings_service.thaw(before)
    for key, value in changes.items():
        settings_service.put(after, key, value)
    bridge.run_in_worker(_turned_on, before, after,
                         failed=lambda info: applog.log("settings", f"Connect's watermarks: {info[0]}"))
    return True


RELEASE_KEYS = ("connect_backlog_cap",)      # changed at all: Connect looks again (a cap read live, laptop round 7 #42)


def releases(before, changes):
    """Does this write let episodes Connect holds go? `connect_trust_timing` off -> on, or a RELEASE_KEYS value changed."""
    before = before or {}
    if changes.get("connect_trust_timing") is True and before.get("connect_trust_timing") is not True:
        return True
    return any(key in changes and changes[key] != before.get(key) for key in RELEASE_KEYS)


def kick_on_release(before, changes, store=None, win=None):
    """After a settings write of `changes` onto `before` that `releases` episodes: Connect kicked on a worker, once
    `store`'s queued write has landed (Connect reads settings.json from disk). `kick.kick` starts it, or wakes the one
    running (it reads the trust switch at its next episode and the cap at its next look); nothing while Connect is
    off. The ones a running Connect set aside this run as *Not timed* still mine at its next start (the same gap as
    *Mine anyway*'s, P4.1 follow-up F-3). `win` (the main window): its bar's arc turns, no words, until the kick has
    been handed over (round 8 row 45: the release is light — a mark at most). -> True when it was asked."""
    if not releases(before, changes):
        return False
    from app.services import settings as settings_service
    after = settings_service.thaw(before) if before is not None else {}
    for key, value in changes.items():
        settings_service.put(after, key, value)
    def failed(info):
        applog.log("settings", f"Connect's start: {info[0]}")
    if win is None or qpress.run(None, "settings:connect_release", _kick, after, store, failed=failed, win=win) is None:
        bridge.run_in_worker(_kick, after, store, failed=failed)     # (one already turning: this one kicks too)
    return True


FLUSH_S = 10            # the longest the start waits for the switch's write (another program holding the lock)


def _kick(settings, store=None):
    """(A worker.) Connect kicked for the episodes the write releases, after the write landed."""
    from app.connect import kick
    flush = getattr(store, "flush", None)
    if flush is not None and not flush(FLUSH_S):
        applog.log("settings", "A setting for Connect: its write hadn't landed; Connect is kicked anyway")
    return kick.kick(settings)


def _turned_on(before, after):
    """(A worker.) `resume.turned_on`, its failures in the log. A mark that failed stays as it was until Connect is
    turned on again (P4.1 WF, adversary N3: since F-2 no look sets the asks watermark)."""
    from app.connect import resume
    failed = resume.turned_on(before, after)
    if failed:
        applog.log("settings", f"Connect turned on; not every watermark was set: {failed}")
    return failed


def attach(page):
    """The store's two lines and *Set up again* filled into `page`'s slots -> their `StoreRows` (a child of the page)."""
    return StoreRows(page)


def now_files(view):
    """How many files NOW holds in `view` (the reader's): what *Soon starts after* shows before a line is set."""
    if view is None:
        return 0
    return sum(len(row.episodes) for row in getattr(view, "rows", ()) if row.tier == "now")


def shown(options, view, row_id):
    """What the `row_id` field shows from the store's options (and the view, for a Soon line not set yet)."""
    if row_id == "mine_line":
        value = options.get("mine_line")
        return MINE_LINE_DEFAULT if value is None else int(value)
    value = options.get("soon_line")
    return now_files(view) if value is None else int(value)


class StoreRows(QObject):
    """`fields`: row id -> its NumberField; `again`: *Set up again*'s button."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.shell = page.shell
        self.services = page.services
        self.fields = {}
        for row_id in LINES:
            row = catalog.ROW[row_id]
            field = sc.NumberField(0, CEILING, 0, suffix=S.STORE_FILES, tooltip=row.tip, name=row.label)
            field.changed.connect(lambda n, r=row_id: self._changed(r, n))
            page.custom_row(row_id).layout().addWidget(field)
            self.fields[row_id] = field
        row = catalog.ROW["keep_watched"]                   # --- W-1
        self.keep = sc.Toggle(False, tooltip=row.tip, name=row.label)
        self.keep.changed.connect(self._keep_changed)
        page.custom_row("keep_watched").layout().addWidget(self.keep)
        self._keep_asked = None                             # the value pressed, until the library holds it
        row = catalog.ROW["set_up_again"]
        self.again = sc.Door(S.SET_UP_AGAIN_OPEN, tooltip=row.tip, name=row.label)
        self.again.clicked.connect(lambda _c=False: self.set_up_again())
        page.custom_row("set_up_again").layout().addWidget(self.again)
        self._heard = None
        self._hear()
        switched = getattr(self.shell, "library_switched", None)
        if switched is not None:                            # W-1 (review W-1): a language switch's new bridge
            switched.connect(self._switched)
        self.follow()

    def _hear(self):
        """One rule for the three store fields: follow the views of the library the window shows now (its bridge — a
        language switch makes another; the old one goes silent)."""
        heard = getattr(self.shell, "library_bridge", None)
        if heard is self._heard:
            return
        old, self._heard = self._heard, heard
        if old is not None:
            try:
                old.library_changed.disconnect(self.follow)
            except (TypeError, RuntimeError):               # already gone (deleteLater) or never connected
                pass
        if heard is not None:
            heard.library_changed.connect(self.follow)

    def _switched(self):
        """Another language's library shown: its bridge heard, its values shown now (a press of the language left is
        never held over the new one's value)."""
        self._keep_asked = None
        self._hear()
        self.follow()

    def alive(self):
        return _alive(self.page)

    def _reader(self):
        return getattr(self.services, "library", None)

    def _writer(self):
        return getattr(self.services, "writer", None)

    def follow(self, view=None):
        """The library's values shown (the reader's newest view landed, or at attach): each field repainted only when
        its value moved (S19); greyed while there is no library to write to."""
        if not self.alive():
            return
        reader = self._reader()
        options = reader.options() if reader is not None else {}
        writable = bool(options) and self._writer() is not None       # (no options: the library not read yet)
        if view is None and reader is not None:
            view = reader.view()
        for row_id, field in self.fields.items():
            turned = field.isEnabled() != writable
            if turned:
                field.setEnabled(writable)
                field.setToolTip(catalog.ROW[row_id].tip if writable else S.STORE_NO_LIBRARY_TIP)
            if not writable:
                if field.edit.text():
                    field.edit.setText("")              # no number the library doesn't hold
                continue
            value = shown(options, view, row_id)
            if (turned or field.value() != value) and not field.edit.hasFocus():
                field.set_value(value)
        self._follow_keep(options, writable)

    def _follow_keep(self, options, writable):
        """W-1's toggle: greyed with why (no library; a library that can't be saved: the store's reason), else the
        library's value — repainted only when it moved (S19), never back over a press still on its way to the store."""
        why = None if writable else S.STORE_NO_LIBRARY_TIP
        if why is None:
            raw = self._writer().reason() or ""               # (None while it can be written, busy too: it queues)
            if raw:
                why = strings.MENU_REFUSED_TIP.format(reason=strings.READ_ONLY_REASONS.get(raw) or raw)
        tip = why or catalog.ROW["keep_watched"].tip
        if self.keep.isEnabled() != (why is None):
            self.keep.setEnabled(why is None)
        if self.keep.toolTip() != tip:
            self.keep.setToolTip(tip)
        if not options:
            return
        value = keep_watched(options)
        if self._keep_asked is not None:
            if value != self._keep_asked and self._pending():
                return                                         # the press not in the store yet: shown as pressed
            self._keep_asked = None
        if self.keep.value() != value:
            self.keep.set_value(value)

    def _pending(self):
        writer = self._writer()
        try:
            return bool(writer.pending()) if writer is not None else False
        except Exception:
            return False

    def _keep_changed(self, on):
        """The toggle pressed (already shown flipped) -> one command on the writer's queue; refused: back as it was,
        the reason in the bar."""
        writer = self._writer()
        seq = None
        if writer is not None:
            try:
                seq = writer.set_options(keep_watched=bool(on))
            except (ValueError, TypeError) as e:
                applog.log("settings", f"keep_watched: {e}")
        if seq is not None:
            self._keep_asked = bool(on)
            return
        self._say_refused(writer)
        self.keep.set_value(not on)

    def _say_refused(self, writer):
        """A refused write's line in the bar: the store's reason in the words the greyed tips and the menus use
        (`READ_ONLY_REASONS`), or that there is no library."""
        raw = ""
        try:
            raw = (writer.reason() if writer is not None else "") or ""
        except Exception:
            pass
        reason = (strings.READ_ONLY_REASONS.get(raw) or raw) if raw else S.STORE_NO_LIBRARY_TIP
        windows.say_in_bar(self.shell, S.STORE_NOT_SAVED.format(reason=reason))

    def _changed(self, row_id, n):
        """A typed value (on Enter, leaving the field, a step: never while typing) -> the writer's queue."""
        writer = self._writer()
        seq = None
        if writer is not None:
            try:
                seq = writer.set_options(**{row_id: int(n)})
            except (ValueError, TypeError) as e:
                applog.log("settings", f"{row_id}: {e}")
        if seq is None:                                   # refused (read-only, no library): the library's value back
            self._say_refused(writer)
            reader = self._reader()
            if reader is not None:
                self.fields[row_id].set_value(shown(reader.options(), reader.view(), row_id))

    def set_up_again(self):
        """*Set up again*: the wizard over the window (nothing without a shell: a page alone)."""
        if self.shell is None:
            return None
        from app.qt import first_run
        return first_run.open_again(self.shell)
