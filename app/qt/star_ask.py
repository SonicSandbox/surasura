"""Surasura's star ask (Sonic, 2026-10-31: "first time star as appear, for when show lands"; pulled into 3.0 the same
day): once, ever — the first time the window sees cards from the learner's own show land in Anki — a toast says
Surasura is free and made by one person, with **⭐ Star Surasura on GitHub** (the repository in the browser: a link
opened, the app makes no call of its own) and **Not now**. Shown is never again, a click or not (settings.json's
`hints_seen` holds `SEEN`, the window's one-time hints' list; once per install, never per library: a fresh library
never asks again). Settings › App keeps a quiet *Star Surasura on GitHub* row, never prompted.

- **Landed** (`view_shown`): the reader counts an item that came back with more cards than when it last asked
  (`LibraryReader.cards_rose`, Current, Soon and Finished) — never an item's first count, so cards already there at the
  open never ask, nor does a show with old cards that comes back into Current (from 6+ Months, New arrivals, a Put
  back: review A-1). One number read per view. A language switch (another reader) starts from its own.
- **Never over anything**: setup, the sort screen, a drag, another toast (it would take that one's Undo, or be
  replaced by the next: review A-2) or a minimized window — owed then, asked at the first view after.
"""
from app.qt import press as qpress
from app.qt import settings_strings
from app.qt import strings

SEEN = "star_ask"


class StarAsk:
    """One per window (the shell's), on the window's thread."""

    def __init__(self, win):
        self.win = win
        self.done = None                    # None: settings.json not asked yet; True: seen (or can't be kept)
        self.owed = False

    def view_shown(self, view, reader):
        """(Each view the window shows.) Cards landed while this window looked: the ask, once."""
        if self.done is None:
            self.done = self._seen()        # asked once a window: settings.json read at its first view
        if self.done:
            return
        if not self.owed:
            rose = getattr(reader, "cards_rose", None)
            if rose is None or not rose():
                return
            self.owed = True
        self.ask()

    def ask(self):
        """The toast, when nothing it would cover is on screen; else owed (the next view asks again)."""
        if self.done or self._blocked():
            return False
        self.done, self.owed = True, False
        try:                                # recorded first: shown is never again, whatever happens next
            seen = self._list()
            self.win.services.settings.set({"hints_seen": seen + [SEEN]})
        except Exception:
            return False                    # no settings to keep it in: never an ask shown every time
        self.win.toasts.show(strings.STAR_ASK, buttons=[(strings.STAR_ASK_STAR, strings.STAR_ASK_STAR_TIP, self._star),
                                                        (strings.STAR_ASK_NOT_NOW, strings.STAR_ASK_NOT_NOW_TIP,
                                                         lambda: None)], long=True)
        return True

    def _star(self):
        qpress.open(self.win, settings_strings.STAR_URL, key="star:github")

    def _blocked(self):
        services = getattr(self.win, "services", None)
        setup = getattr(services, "setup_open", None)
        toasts = getattr(self.win, "toasts", None)
        sorting = self.win.__dict__.get("_sort_screen") if hasattr(self.win, "__dict__") else None
        minimized = getattr(self.win, "isMinimized", None)
        return (toasts is None or bool(getattr(toasts, "dragging", False)) or bool(getattr(toasts, "alive", False))
                or (setup is not None and setup.is_set()) or sorting is not None
                or (minimized is not None and minimized()))

    def _list(self):
        value = self.win.services.settings.get().get("hints_seen")
        return [h for h in value if isinstance(h, str)] if isinstance(value, (list, tuple)) else []

    def _seen(self):
        try:
            return SEEN in self._list()
        except Exception:
            return True                     # unreadable: never asked (it could never be kept)
