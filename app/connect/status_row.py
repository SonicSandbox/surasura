"""Connect's line and the *Needs you* badge in the 2.x dashboard (P3.1 row 3.1.4; P1.5 05-surface U1, U2;
RUNBOOK-P2.5 *The status contract*), and the kick after a placement (row 3.1.9).

- **Its own row above the bottom bar**, built only while the preview's switch is on (off: no frame at all, the
  dashboard 2.5's). The line is the status record's `line` for the dashboard's language; hovering it shows the current
  job's step and words; the badge at the row's right end is *Needs you (n)* filled while anything is unseen, outlined
  with no number once all are seen, gone when nothing is open. A click on either opens the Connect window.
- **Only what changed** (S19): every 3 s a worker takes `status.stamp()` (two stats and a look at Connect's lock);
  only a stamp that differs from the last one reads `status.read` and redraws. The Tk thread never calls either. No
  timer under `SURASURA_NO_UI_TIMERS` (the tests call `tick`).
- **A placement reaches Connect** (3.1.9): a Content Manager move into the top 20 doesn't start Connect by itself —
  the dashboard's session look kicks it only after a session's first sync — so when the stamp changed (the library
  file moved) and Connect isn't running, one read-only look at the placement log: an event Connect hasn't read →
  `kick.kick` (which refuses by itself when off or an update is staged), once per newest event.

GUI_Design_Guidelines: the dark palette, ttk where it styles (the badge is a plain tk Label: a filled or outlined
accent box), a tooltip on both. The tooltip is handed in, so this module never imports app.main.
"""
import os
import pathlib
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk

BG, SURFACE, TEXT, ACCENT, SECONDARY, ERROR = "#1e1e1e", "#2d2d2d", "#e0e0e0", "#bb86fc", "#03dac6", "#cf6679"
EVERY_MS = 3000


def unread(language, reader="connect"):
    """The newest placement-log event Connect's reader hasn't read, or None (no store, no reader yet, nothing new).
    Read-only (`mode=ro`): never makes or writes the library file."""
    from app.connect import status
    db = status._store_path(language)
    if not db or not os.path.exists(db):
        return None
    try:
        conn = sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True, timeout=1.0, isolation_level=None)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (f"reader:{reader}",)).fetchone()
        if row is None:
            return None
        newest = conn.execute("SELECT MAX(id) FROM placement_log WHERE id > ?", (int(row[0]),)).fetchone()[0]
        return newest
    except (sqlite3.Error, ValueError, TypeError):
        return None
    finally:
        conn.close()


def detail(rec):
    """The hover: the working job's title, step and words; else the line itself."""
    lines = []
    for job in (rec or {}).get("jobs") or ():
        title = job.get("title") or "An episode"
        step = job.get("step") or job.get("reason") or job.get("state")
        lines.append(f"{title}: {step} · {job.get('words', 0)} words")
    return "\n".join(lines) or (rec or {}).get("line") or ""


def drawn(rec):
    """What the row shows from a record (the line, the badge, the hover): the same → no redraw (S19)."""
    return (rec or {}).get("line"), badge_state(rec), detail(rec)


def badge_state(rec):
    """`filled` (n unseen), `outlined` (all seen), or None (nothing open)."""
    if not (rec or {}).get("needs"):
        return None, 0
    unseen = int((rec or {}).get("unseen") or 0)
    return ("filled", unseen) if unseen > 0 else ("outlined", 0)


class StatusRow:
    """U1 + U2. `parent`: the dashboard's root; `after`: the widget packed below it (the bottom bar);
    `language()`: the dashboard's language now; `on_open()`: opens the Connect window; `settings()`: the dashboard's
    settings now (the kick's); `post(job)`: runs `job` on the Tk thread (the dashboard's queue); `stamp` / `read` /
    `kick` / `unread`: Connect's, handed in by the tests."""

    def __init__(self, parent, language, tooltip, on_open, settings=None, below=None, stamp=None, read=None,
                 kick=None, unread=None, post=None):
        self.language, self.on_open = language, on_open
        self.settings = settings or (lambda: {})
        self._stamp, self._read, self._kick, self._unread = stamp, read, kick, unread
        self._post_to = post
        self._last = None               # (language, stamp) last drawn
        self._kicked = None             # the newest event a kick started Connect for
        self._kick_due = False          # the stamp moved and no kick has started yet
        self._shown = None              # what the last draw put on the row (`drawn`)
        self._looking = False
        self._timer = None
        self.stopped = False
        self.reads = self.redraws = 0
        self.record = None
        style = ttk.Style(parent)
        style.configure("CS.TFrame", background=BG)
        style.configure("CS.TLabel", background=BG, foreground=SECONDARY, font=("Segoe UI", 9))
        self.frame = ttk.Frame(parent, style="CS.TFrame", padding=(10, 2))
        if below is not None:
            self.frame.pack(side=tk.BOTTOM, fill=tk.X, after=below)
        else:
            self.frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.line = ttk.Label(self.frame, text="Connect: looking…", style="CS.TLabel", cursor="hand2")
        self.line.pack(side=tk.LEFT)
        self.line.bind("<Button-1>", lambda _e: self.on_open())
        self.badge = tk.Label(self.frame, text="", cursor="hand2", font=("Segoe UI", 9, "bold"), padx=8, pady=0)
        self.badge.bind("<Button-1>", lambda _e: self.on_open())
        tooltip(self.line, lambda: detail(self.record) + "\nClick: open Connect's window.")
        tooltip(self.badge, "Things only you can fix. Click to see them.")
        self.badge_shown = None

    # -- the poll ---------------------------------------------------------------------------------------------- #
    def start(self):
        """The first look now; then one every 3 s (none under SURASURA_NO_UI_TIMERS)."""
        self.tick()

    def _schedule(self):
        if self.stopped or os.environ.get("SURASURA_NO_UI_TIMERS"):
            return
        try:
            self._timer = self.frame.after(EVERY_MS, self.tick)
        except tk.TclError:
            self._timer = None

    def tick(self):
        """The timer's: a look, and the next one in 3 s."""
        if self.stopped:
            return
        try:
            self.look_now()
        finally:
            self._schedule()

    def look_now(self):
        """On the Tk thread: a worker looks, unless one still is."""
        if self.stopped or self._looking:
            return
        self._looking = True
        threading.Thread(target=self._look, args=(self.language(),), daemon=True).start()

    def _look(self, language):
        """On a worker: the stamp; only when it changed, the record — keyed on the stamp the read itself took, so a
        write between the two looks costs no second read — and a redraw only when what is drawn changed (S19). A
        failed read is printed once: the next read waits for the stamp to move. A kick still owed (refused: an update
        staged) is tried again at each look until one starts."""
        try:
            stamp = (self._stamp or _status().stamp)(languages=[language])
            key = (language, stamp)
            if key != self._last:
                self._last = key
                self._kick_due = True
                self.reads += 1
                try:
                    full = (self._read or _status().read)([language])
                except Exception as e:
                    print(f"Connect's status wasn't read: {e}")
                else:
                    stamp = full.get("stamp", stamp)
                    self._last = (language, stamp)
                    rec = full["languages"][language]
                    shown = drawn(rec)
                    if shown != self._shown:
                        self._shown = shown
                        self._post(lambda: self.draw(rec))
            if self._kick_due:
                self._maybe_kick(language, stamp)
        except Exception as e:
            print(f"Connect's status wasn't read: {e}")
        finally:
            self._looking = False

    def _maybe_kick(self, language, stamp):
        """3.1.9: an event Connect hasn't read, and Connect not running → one kick for it. The event counts as kicked
        only once a kick started Connect (a process); refused (an update staged, Connect starting), it is tried again
        at the next look."""
        try:
            if not (self.settings() or {}).get("connect_enabled"):
                self._kick_due = False
                return                  # off (switched off since the row was built): nothing
            if len(stamp) > 2 and stamp[2]:
                self._kick_due = False
                return                  # running: it reads the log again before it exits
            newest = (self._unread or unread)(language)
            if newest is None or newest == self._kicked:
                self._kick_due = False
                return
            if self._kick is not None:
                started = self._kick(self.settings())
            else:
                from app.connect import kick
                started = kick.kick(self.settings())
            if started:
                self._kicked, self._kick_due = newest, False
        except Exception as e:
            self._kick_due = False
            print(f"Connect wasn't started: {e}")

    def _post(self, job):
        """From the worker: `job` on the Tk thread — through the dashboard's queue (`post`), else `after`."""
        try:
            (self._post_to or (lambda j: self.frame.after(0, j)))(job)
        except (tk.TclError, RuntimeError):
            pass

    # -- drawing (the Tk thread) ------------------------------------------------------------------------------- #
    def draw(self, rec):
        if self.stopped:
            return
        self.redraws += 1
        self.record = rec
        self.line.config(text="Connect: " + (rec.get("line") or "Up to date"))
        state, unseen = badge_state(rec)
        if state is None:
            self.badge.pack_forget()
        elif state == "filled":
            self.badge.config(text=f"Needs you ({unseen})", bg=ACCENT, fg=BG, highlightthickness=0)
            self.badge.pack(side=tk.RIGHT)
        else:
            self.badge.config(text="Needs you", bg=BG, fg=ACCENT, highlightthickness=1, highlightbackground=ACCENT,
                              highlightcolor=ACCENT)
            self.badge.pack(side=tk.RIGHT)
        self.badge_shown = state

    def refresh(self):
        """Read again at the next look (after the window marked needs seen, dismissed one, undid a batch); redrawn
        only if what it shows changed."""
        self._last = None
        self.look_now()

    def stop(self):
        """The switch off: the poll stops and the row goes."""
        self.stopped = True
        if self._timer is not None:
            try:
                self.frame.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        try:
            self.frame.destroy()
        except tk.TclError:
            pass


def _status():
    from app.connect import status
    return status
