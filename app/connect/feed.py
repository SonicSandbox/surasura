"""The window's Connect feed (P4.1 row 4.1.2): what the library's rows show of Connect — the *Mining* / *Waiting* /
*No video* stones and their hover — and Connect's line, from its status record (`app/connect/status.py`), in one read.

- `Feed`: `on` (Connect may run: `settings_manager.connect_on`; off, the line says why nothing runs — IK N4 — and the
  stones offer no action, IK S7), `mining` (the item ids whose cards are being made: `LibraryReader`'s `mining()`
  hook), `items` (`{item_id: Item}`: each item with an open job), `line` / `state` (U1's line: the quiet mark),
  `unseen` (*Needs you*'s badge) and `updating` (*Connect is updating your list*, F9: row 4.1.7's record flag).
- `Item(kind, words, tip, job, made, total)`: `kind` one of KINDS; `words` the status read out (hover, keyboard
  focus, a screen reader: `WORDS`); `tip` the job's own reason in plain words (a waiting stone's hover, C7); `job`
  its id (*Mine anyway*'s); `made` / `total` its cards so far of the words picked (*Mining 3 of 12*).
- Kinds are told by the runner's and the Anki session's named reasons (`runner.NO_VIDEO`, `anki_session.CLOSED`, …)
  and the job's own `kind` (`asked`, row 4.1.3), never by a wording a test can't see.
- `Provider(language, settings_get)`: one per window and language, a worker's call. Off → the off Feed, nothing read.
  Each look takes Connect's `stamp` (two stats and a look at its lock) and reads the record only when it moved —
  keyed on the stamp the read itself took — so an unchanged Connect is the same `Feed` object (S19).

The window's own strings stay Mado's: `WORDS` are the words for what Connect is doing. Light (02 §5): the standard
library, the status record and the runner's names; no Qt, no Tk.
"""
from collections import namedtuple

EVERY_S = 3                     # the window's tick while Connect is on (the Tk row's; `services.status.TICKS`)

Feed = namedtuple("Feed", "on mining items line state unseen updating")
Item = namedtuple("Item", "kind words tip job made total")

MINING, WAITING, ANKI, NO_VIDEO, NOT_TIMED, BATTERY, ASKED = (
    "mining", "waiting", "anki", "no_video", "not_timed", "battery", "asked")
KINDS = (MINING, WAITING, ANKI, NO_VIDEO, NOT_TIMED, BATTERY, ASKED)

# The status read out — the stone's words on hover and keyboard focus, and what a screen reader says (RS-6)
WORDS = {
    MINING: "Making its cards",
    WAITING: "Waiting to make its cards",
    ANKI: "Waiting for Anki",
    NO_VIDEO: "No video",
    NOT_TIMED: "Not timed to its video",
    BATTERY: "Waiting: on battery",
    ASKED: "Asked: its cards come next",
}
# *Mine anyway* on a pairing hato placed by its name only (`verdict: untimed`, 09-hato-layer v2 §1.2; hato's
# wrong-episode finding): the warning W3.2's *Needs you* entry carries (row 4.1.9)
UNTIMED_WARNING = ("hato matched this subtitle to its video by name only: it may be another episode's. Mine anyway "
                   "only once you've checked it plays in time.")
WORDS["untimed"] = UNTIMED_WARNING
# The line while Connect may not run (IK N4: it says why nothing runs)
OFF_CONNECT = "Make cards for me is off: Connect makes no cards."
OFF_AUTOMATION = "Automation is off: Connect makes no cards until you turn it back on."
UNREADABLE = "Connect's status can't be read just now."
# Before the window's first look (laptop fixes B2-8, Michi's call): Connect not known to be on — `on` False, so the rows
# show no top line and no *Waiting* until a look finds it on (no flash of them with Connect off). Its `line` None: the
# status line never shows it (that line is the look's own)
NOT_LOOKED = Feed(on=False, mining=frozenset(), items={}, line=None, state="unknown", unseen=0, updating=False)


def _off(settings):
    why = OFF_AUTOMATION if (settings or {}).get("connect_enabled") else OFF_CONNECT
    return Feed(on=False, mining=frozenset(), items={}, line=why, state="off", unseen=0, updating=False)


def _anki_waits():
    """The reasons that are a job waiting on Anki (closed, busy, not answering as it should, reviewing, another
    program writing to it) and the start of the other-profile one."""
    from app.connect import anki_session, runner
    return ({runner.ANKI_CLOSED, runner.REVIEWING, runner.WRITER_BUSY, anki_session.CLOSED, anki_session.BUSY,
             anki_session.UNUSABLE, anki_session.REVIEWING}, anki_session.OTHER_PROFILE.split("{")[0])


def build(record, language):
    """The Feed of one language's status record (`status.read`'s) -> Feed (on)."""
    from app.connect import ledger as book
    from app.connect import runner
    rec = ((record or {}).get("languages") or {}).get(language) or {}
    running = bool((record or {}).get("running"))
    waits, other_profile = _anki_waits()
    not_timed = {n.get("item") for n in rec.get("needs") or () if n.get("kind") == "not-timed"}
    items, mining = {}, set()
    for job in rec.get("jobs") or ():
        item_id = job.get("item")
        if item_id is None or item_id in items:
            continue                        # one stone an item: its first open job (the record's order)
        reason = job.get("reason") or ""
        if job.get("state") in book.IN_FLIGHT and running:
            kind = MINING
        elif reason == runner.NO_VIDEO:
            kind = NO_VIDEO
        elif item_id in not_timed:
            kind = NOT_TIMED
        elif reason == runner.ON_BATTERY:
            kind = BATTERY
        elif reason in waits or reason.startswith(other_profile):
            kind = ANKI
        elif job.get("kind") == "asked":
            kind = ASKED
        else:
            kind = WAITING
        if kind == MINING:
            mining.add(item_id)
        items[item_id] = Item(kind=kind, words=WORDS[kind], tip=reason or WORDS[kind], job=job.get("job"),
                              made=job.get("made") or 0, total=job.get("words") or 0)
    return Feed(on=True, mining=frozenset(mining), items=items, line=rec.get("line"), state=rec.get("state"),
                unseen=rec.get("unseen") or 0, updating=bool(rec.get("updating")))


class Provider:
    """Connect's feed for one window and language. `settings_get()`: the settings now (the settings service's `get`);
    `stamp` / `read`: `status.stamp` / `status.read` (a test's stand-ins). One look at a time (the window's worker)."""

    def __init__(self, language, settings_get, stamp=None, read=None):
        self.language, self.settings_get = language, settings_get
        self._stamp, self._read = stamp, read
        self._last = None           # (the stamp the read took, its Feed)
        self._on = True
        # P4.1 L2 (W1): the window's side. `latest()` the Feed the last look found (the library reader builds with it:
        # no second stamp a tick, row 4.1.13); `on_change()` called by a look that found another Feed (the reader's
        # `refresh`: the stones rebuilt) — one listener, the reader open now
        self._latest = None
        self.on_change = None

    def latest(self):
        """The Feed the last look found, or `NOT_LOOKED` before any (Connect not known on: `Feed.on` the one test).
        No read."""
        return self._latest if self._latest is not None else NOT_LOOKED

    def feed(self):
        """The Feed now (`_look`), kept as `latest()`: a Feed equal to the last is the last object (S19 — off, a
        record unreadable again, a stamp moved by nothing the window shows), and a new one tells `on_change`."""
        got = self._look()
        last = self._latest
        if last is not None and (got is last or got == last):
            return last
        self._latest = got
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception as e:                  # a listener's fault never stops the look
                print(f"Connect's feed listener failed: {e}")
        return got

    def _look(self):
        """The Feed now: off → the off Feed, nothing read; the stamp unchanged → the same Feed object (S19); a record
        that can't be read → its own line (Connect's record says why), never a raise."""
        from app import settings_manager
        try:
            settings = self.settings_get() or {}
        except Exception as e:                  # settings caught mid-save: the unreadable line, never a raise
            print(f"Connect's feed couldn't read the settings: {e}")
            return Feed(on=True, mining=frozenset(), items={}, line=UNREADABLE, state="waiting", unseen=0,
                        updating=False)
        if not settings_manager.connect_on(settings):
            self._on, self._last = False, None      # turned on again: its first look reads
            return _off(settings)
        self._on = True
        try:
            from app.connect import status
            now = (self._stamp or status.stamp)(languages=[self.language])
            if self._last is not None and self._last[0] == now:
                return self._last[1]
            record = (self._read or status.read)(languages=[self.language]) or {}
            feed = build(record, self.language)
            self._last = (record.get("stamp", now), feed)
            return feed
        except Exception as e:
            print(f"Connect's status wasn't read: {e}")      # the last good read stays keyed on its own stamp
            return Feed(on=True, mining=frozenset(), items={}, line=UNREADABLE, state="waiting", unseen=0,
                        updating=False)

    def mining(self):
        """`LibraryReader`'s hook: the item ids whose cards are being made."""
        return self.feed().mining

    def line(self):
        """The quiet mark's words."""
        return self.feed().line

    def every(self):
        """The tick: EVERY_S while Connect is on, none once a look found it off (the window asks again by name when
        a switch lands)."""
        return EVERY_S if self._on else None
