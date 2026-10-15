"""The window's link to Connect (P4.1 row 4.1.6): after a change the window made — a move into the top 20, an ask for
mining (*Mine now*, *Mine this*, *Mine it too*) — one look, and Connect kicked when it has something to read.

- **The rule** (moved here from the Tk row's `status_row._maybe_kick`, P3.1 row 3.1.9, which now calls it): an event
  of the placement log Connect hasn't read, or an ask it hasn't taken (`inbox.newest_unread_ask`), Connect not
  running and switched on → one `kick.kick`, **once per newest event or ask**. A kick refused (an update staged,
  Connect starting) uses nothing up: the next change tries again. Running, Connect reads the log and the asks again
  before it exits, so nothing is kicked for.
- **A worker's call**, never the window's thread: two read-only looks (the library file and the ledger, `mode=ro`,
  never made) and at most one process started. Qt- and Tk-free: the Qt window (W-A2's after-commit hook) and the Tk
  row both hold one.

Light: the standard library and Connect's own modules.
"""
import os
import pathlib
import sqlite3

# What `after_change` answers: Connect started, or why not
KICKED, OFF, RUNNING, NOTHING, REFUSED = "kicked", "off", "running", "nothing", "refused"


def unread(language, reader="connect"):
    """What Connect hasn't read for `language`, or None: (the newest unread placement event or None, the newest
    unread ask's stamp or None). Read-only (the store and the ledger `mode=ro`): never makes or writes either."""
    from app.connect import inbox, library
    conn = _store_ro(language)
    if conn is None:
        return None
    try:
        event = _unread_event(conn, reader)
        found = library.asks_in(conn)
    finally:
        conn.close()
    ask = inbox.newest_unread_ask(language, found) if found else None
    if event is None and ask is None:
        return None
    return event, ask


def unread_event(language, reader="connect"):
    """The newest placement-log event Connect's reader hasn't read, or None (no store, no reader yet, nothing new).
    Read-only (`mode=ro`): never makes or writes the library file (P3.1 row 3.1.9's look, `status_row.unread`)."""
    conn = _store_ro(language)
    if conn is None:
        return None
    try:
        return _unread_event(conn, reader)
    finally:
        conn.close()


def _store_ro(language):
    from app.connect import status
    db = status._store_path(language)
    if not db or not os.path.exists(db):
        return None
    try:
        return sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True, timeout=1.0, isolation_level=None)
    except sqlite3.Error:
        return None


def _unread_event(conn, reader):
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (f"reader:{reader}",)).fetchone()
        if row is None:
            return None             # Connect never switched on for this library: nothing for it
        return conn.execute("SELECT MAX(id) FROM placement_log WHERE id > ?", (int(row[0]),)).fetchone()[0]
    except (sqlite3.Error, ValueError, TypeError):
        return None


def _on(settings):
    """Connect may start: its switch and D29's automation (P3.3 C1; 4.1.1's `connect_on` is the one predicate)."""
    from app import settings_manager
    predicate = getattr(settings_manager, "connect_on", None)
    if predicate is not None:
        return bool(predicate(settings))
    return bool(settings.get("connect_enabled")) and settings_manager.automation(settings)


class Link:
    """`language`: the window's language (a code, or a callable answering it now); `settings_get()`: the window's
    settings now; `kick(settings)` / `unread(language)` / `running()`: Connect's, handed in by the tests."""

    def __init__(self, language, settings_get, kick=None, unread=None, running=None):
        self.language = language
        self.settings_get = settings_get or (lambda: {})
        self._kick, self._unread, self._running = kick, unread, running
        self.kicked = None              # (language, the newest unread) a kick started Connect for

    def _language(self):
        return self.language() if callable(self.language) else self.language

    def after_change(self, running=None, language=None):
        """On a worker, after the window's change committed -> KICKED, OFF, RUNNING, NOTHING or REFUSED (a kick that
        didn't start: tried again at the next change). `running`: whether Connect runs, when the caller already
        looked (the Tk row's stamp); else its lock is looked at. `language`: the one the caller looked at, else the
        window's now."""
        settings = self.settings_get() or {}
        if not _on(settings):
            return OFF
        if running is None:
            from app.connect import kick
            running = (self._running or kick.running)()
        if running:
            return RUNNING              # it reads the log and the asks again before it exits
        language = language or self._language()
        newest = (self._unread or unread)(language)
        if newest is None or (language, newest) == self.kicked:
            return NOTHING
        if self._kick is not None:
            started = self._kick(settings)
        else:
            from app.connect import kick
            started = kick.kick(settings)
        if not started:
            return REFUSED
        self.kicked = (language, newest)
        return KICKED
