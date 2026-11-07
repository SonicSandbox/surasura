"""The window's one-time hints (the help cards' spec §6.7, WP6; HC-3, PROVISIONAL): one shared helper for every hint
shown once — W-1's `keep_watched` (the first mark), the star ask, and the three moments that confused most (HC-3):

- `first_card_wait` — the first time card making waits on Anki (*Cards wait: Anki isn't open*);
- `first_amber` — the first time a circle turns amber (*A decision waits for you: press the amber circle*);
- `first_auto_generate` — the first background Generate (*Your journey is catching up with your moves*).

**Once** — settings.json's `hints_seen` (outside the run signature: no new setting) holds each hint shown: per library
(the hint's name with the library store's id, W-1's rule) or, for the star ask, per install. A hand-edited value that
isn't a list reads as none seen. Recorded as it shows: shown is never again, whatever happens next.

**Never over anything** (star_ask's rule, review A-2): a hint never replaces a live toast (its Undo would be lost),
and never shows during a drag, setup, the sort screen or while the window is minimised — it is owed then and shown at
the moment's next coming (`again`); **never two in one minute** (`GAP_S`). Each HC-3 hint is a toast with *Why?* → its
help card.
"""
import time

from app.qt import strings
from app.services import causes

GAP_S = 60.0                        # never two hints within this many seconds
HC3 = ("first_card_wait", "first_amber", "first_auto_generate")
CARD = {"first_card_wait": "cards", "first_amber": "circles", "first_auto_generate": "generate"}


class Hints:
    """One per window (the shell's), on the window's thread. `clock`: a test's stand-in (`time.monotonic`)."""

    def __init__(self, win, clock=None):
        self.win = win
        self.clock = clock or time.monotonic
        self.last = None                # when the newest hint showed (the clock's)
        self.owed = {}                  # name -> the show it waits to run (blocked when its moment came)
        self.shown = []                 # names shown this session (tests)
        self.done = set()               # names found seen: never read again this session (each snapshot asks: S19)

    # --- the one record --------------------------------------------------------------------------------------- #
    def seen_list(self):
        value = self.win.services.settings.get().get("hints_seen")
        return [h for h in value if isinstance(h, str)] if isinstance(value, (list, tuple)) else []

    def hint_id(self, name, per_library=True):
        """`name`'s id: with the library store's id (W-1: never keyed by the language), or `name` alone per install;
        None while the library's id isn't read yet."""
        if not per_library:
            return name
        store_id = None
        try:
            reader = getattr(getattr(self.win, "moves", None), "reader", None)
            store_id = reader.store_id() if reader is not None else None
        except Exception:
            pass
        return f"{name}:{store_id}" if store_id else None

    def unseen(self, name, per_library=True):
        """`name`'s id when it hasn't shown yet, else None (also when the settings can't keep it: never every time)."""
        hint = self.hint_id(name, per_library)
        if hint is None:
            return None
        try:
            return None if hint in self.seen_list() else hint
        except Exception:
            return None

    def mark(self, hint):
        """`hint` recorded as shown (its key alone written: the settings service's rule)."""
        seen = self.seen_list()
        if hint not in seen:
            self.win.services.settings.set({"hints_seen": seen + [hint]})

    # --- when ------------------------------------------------------------------------------------------------- #
    def blocked(self, toast_ok=False):
        """Whether a hint would cover something now: a live toast (`toast_ok`: the hint *is* that toast — W-1's), a
        drag, setup, the sort screen, a minimised window."""
        win = self.win
        services = getattr(win, "services", None)
        setup = getattr(services, "setup_open", None)
        toasts = getattr(win, "toasts", None)
        sorting = win.__dict__.get("_sort_screen") if hasattr(win, "__dict__") else None
        minimized = getattr(win, "isMinimized", None)
        return (toasts is None or bool(getattr(toasts, "dragging", False))
                or (not toast_ok and bool(getattr(toasts, "alive", False)))
                or (setup is not None and setup.is_set()) or sorting is not None
                or (minimized is not None and minimized()))

    def too_soon(self):
        return self.last is not None and self.clock() - self.last < GAP_S

    def once(self, name, show, per_library=True, toast_ok=False):
        """Show hint `name` once (`show()` makes its toast): now if nothing holds it, else owed for its next moment
        (`again`). -> True when it showed."""
        if name in self.done:
            return False
        hint = self.hint_id(name, per_library)
        if hint is not None and self.unseen(name, per_library) is None:
            self.done.add(name)             # (seen, or nowhere to keep it: never asked again this session)
            hint = None
        if hint is None:
            self.owed.pop(name, None)
            return False
        if self.blocked(toast_ok) or self.too_soon():
            self.owed[name] = (show, per_library, toast_ok)
            return False
        self.owed.pop(name, None)
        try:
            self.mark(hint)                 # recorded first: shown is never again
        except Exception:
            return False
        self.last = self.clock()
        self.done.add(name)
        self.shown.append(name)
        show()
        return True

    def again(self):
        """A moment to show what's owed (the window's next view, a job's change): the oldest owed hint, if free."""
        for name, (show, per_library, toast_ok) in list(self.owed.items()):
            if self.once(name, show, per_library, toast_ok):
                return True
        return False

    # --- HC-3: the three moments ---------------------------------------------------------------------------------- #
    def toast(self, name, words):
        """An HC-3 hint's toast: its words, and *Why?* → its card."""
        cause = causes.Cause(strings.HINT_WHY[name], None, CARD[name])
        return lambda: self.win.toasts.show(words, why=cause)

    def jobs(self, views):
        """(Each registry snapshot.) The first card wait on Anki, the first background Generate."""
        live = [v for v in views if v.state in ("queued", "waiting", "running")]
        wait = next((v for v in live if v.kind == "mine-anki" and v.reason), None)
        if wait is not None:
            self.once("first_card_wait", self.toast("first_card_wait", strings.HINT_CARD_WAIT.format(
                reason=wait.reason)))
        if any(v.kind == "generate" and v.automatic and v.state == "running" for v in live):
            self.once("first_auto_generate", self.toast("first_auto_generate", strings.HINT_AUTO_GENERATE))
        if self.owed:
            self.again()

    def strip(self, states):
        """(The strip's states, each refresh.) The first amber circle."""
        if any(st.needs and st.go is not None for st in states.values()):
            self.once("first_amber", self.toast("first_amber", strings.HINT_AMBER))
