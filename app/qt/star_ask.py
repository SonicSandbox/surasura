"""Surasura's star ask (Sonic, 2026-10-31: "first time star as appear, for when show lands"; pulled into 3.0 the same
day): once, ever — the first time the window sees cards from the learner's own show land in Anki — a toast says
Surasura is free and made by one person, with **⭐ Star Surasura on GitHub** (the repository in the browser: a link
opened, the app makes no call of its own) and **Not now**. Shown is never again, a click or not (settings.json's
`hints_seen` holds `SEEN`, the window's one-time hints' list; once per install, never per library: a fresh library
never asks again). Settings › App keeps a quiet *Star Surasura on GitHub* row, never prompted.

- **Landed** (`view_shown`): an item's card count above the one it had in the first whole view this reader built (a
  store read, not the first screen's cache, not loading: `LibraryReader.cards()` — the counts the rows show, the same
  dict until one moves, so a view with no new cards costs one identity check). Cards already there when the window
  opened never ask; a language switch (another reader) starts again from its own first view.
- **Never while setup or a drag is on screen**: owed then, asked at the first view after both are gone.
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
        self._reader = self._base = self._cards = None

    def view_shown(self, view, reader):
        """(Each view the window shows.) Cards landed since this reader's first whole view: the ask, once."""
        if self.done is None:
            self.done = self._seen()        # asked once a window: settings.json read at its first view
        if self.done:
            return
        if not self.owed:
            cards = getattr(reader, "cards", None)
            cards = cards() if cards is not None else None
            if cards is None or cards is self._cards and reader is self._reader:
                return
            if reader is not self._reader:
                self._reader, self._base = reader, None
            if self._base is None:
                if getattr(view, "cached", False) or getattr(view, "loading", False) or view.mode != "store":
                    return                  # (the first screen's cache, a loading view: no counts to start from)
                self._base = cards
            self._cards = cards
            base = self._base
            if not any(n > base.get(item, 0) for item, n in cards.items()):
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
        return toasts is None or bool(getattr(toasts, "dragging", False)) or (setup is not None and setup.is_set())

    def _list(self):
        value = self.win.services.settings.get().get("hints_seen")
        return [h for h in value if isinstance(h, str)] if isinstance(value, (list, tuple)) else []

    def _seen(self):
        try:
            return SEEN in self._list()
        except Exception:
            return True                     # unreadable: never asked (it could never be kept)
