"""The fast re-plan's preview (E1.1 04, RP-7; 2.6, opt-in): a move in the Content Manager re-orders Anki's new cards
about a second later — tomorrow's cards first, then the rest — without a full Generate.

    replan_preview.is_on(settings, language)    # 順's option "Re-order Anki as I move content (preview)", for the
                                                # language it was switched on in, Junban on and present
    replan_preview.stands_aside(settings, language)   # 3.0: why the host does nothing now (D29, Junban, D7, the
    replan_preview.automation_on(settings, language)  # recorded deck), or None; what every job asks (W3.5 row 7)
    replan_preview.unavailable(settings)        # why the option can't be used now (D7), or None
    host = replan_preview.open_host(language, say=…, working=…, generate=…)   # one per window (a helper process)
    host.poke()                                 # a store change: the 0.8 s settle restarts; one job when it ends
    host.catch_up()                             # the dashboard's start / focus, the CM's open: the job, only if owed
    host.after_generate()                       # a full Generate finished: the re-order from its plan, shadow mode
    host.close()                                # the window closes: a pending settle and a pending sync run at once

**The job** (04 §2.3), on the host's one worker, never two at once (a poke during a job queues one more): the store's
versions and order (one read), the guards (Junban's window, an update, Anki closed, a review), the plan file checked
against the library as it stands (`plan_engine.check`, the signature's parts read here), `Engine.replan`, Junban's
spaced delta with the engine's rows (`reposition.run(job=spaced.Job(automatic=True, …))`, under the Anki-write lock,
one deck — 2.x-dev: positions only; 3.0: your 順 actions after them, `_write`), then `record_planned` with the versions read with the order. When the plan can't serve the
move the line says so, and the dashboard's host asks its window for an automatic Generate (04 §3–4; `generate`).

**Off** (the default), another language, or Junban removed: `is_on` is False, no window makes a host, and nothing
here imports Junban, the engine or the analyzer — 2.5, byte for byte (rule 1).

**The 3.0 line** (W3.5 row 7; Haya's G2–G4): inside the host every job asks `automation_on` instead — D29's one switch
(`logic.automation`), Junban on and present, D7, and the (language, deck) pair 順's deck save records — read fresh each
job, never the 2.x box; a window still asks `is_on` whether to make a host until W3.4.

Light by rule: no Tk. `say(line)`, `working(bool)` and `generate(reason)` are the window's, called from the worker:
each must only post to that window's own queue. Everything heavy (the store, the engine, the analyzer's signature,
Junban) is imported on the worker; the AnkiWeb indicator's words are worked out there too (`web`).

**The helper process** (E3.1-B1, Sonic's ⭐): a window makes its host with `open_host`, which runs the `Host` in a
process of its own (`Remote`; `helper_main` is the other side) — the same calls, a few bytes each over a local pipe.
A job's reads and parses (Anki's answers, Junban's tables, the plan) then never hold the window's interpreter: on
DevTest they held the Content Manager's window 16–63 ms a move, against a 4 ms budget. Nothing in it is the 2.x
window's: 3.0's window makes the same `open_host` call.
"""

import importlib.util
import json
import os
import sys
import threading
import time

if __name__ == "__main__" and __package__ is None:     # the helper from source: `python app/replan_preview.py …`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SWITCH = "junban_replan_preview"
LANGUAGE = "junban_replan_language"     # the language 順's switch was turned on in (its deck's): "" reads as "ja"
DECK = "junban_replan_deck"             # the deck it was turned on for: 順's deck changed since -> it stands aside
SETTLE_S = 0.8                  # 04 §2.2: the moves' settle
RETRY_S = 20.0                  # Anki in a review, 順's window open, cards left by the re-check: look again
DONE_S = 5.0                    # "tomorrow's cards placed" gives way to "up to date" after this
CHECK_ANKI_S = 60.0             # the catch-up's look for new cards in Anki, at most this often
EDITED_DAYS_MAX = 60            # drill A3 gap 3: how far back the look for edited notes reaches at most (days)
EDITED_CHUNK = 500              # notes a `notesModTime` asks at once
CLOSE_WAIT_S = 15.0             # "finishing…" waits at most this long (inside an update's 20 s grace: updater.STOP_GRACE)
SHADOW_LOG = "replan_shadow.log"
VERB = "re-ordering as you move"    # the Anki-write lock's holder line ("… is writing to Anki")
IN_PROCESS_ENV = "SURASURA_REPLAN_IN_PROCESS"   # "1": the host in the window's own process (the suites' fake Anki)
ADDRESS_ENV = "SURASURA_REPLAN_ADDRESS"         # the helper's way back to its window: the pipe's name …
KEY_ENV = "SURASURA_REPLAN_KEY"                 # … and its key (never on a command line: app_entry logs every argv)
HELPER_START_S = 30.0           # a helper that hasn't answered by then: the window's own process hosts the jobs
STATE_EVERY_S = 0.05            # the helper sends its state (busy, the indicator) when it changes, looked at this often
TIERS = ("now", "soon", "goal")
KINDS = ("warm", "generate", "move", "catch-up")

# The bar's lines (04 §2.4, §4).
CLOSED = "Anki is closed: your new order goes to Anki when it opens"     # alpha 3: one short line (IKA3-4)
REVIEWING = "Anki is in a review — re-ordering after it"
NOT_ANSWERING = "Anki isn't answering just now — trying again shortly"
BUSY = "順 is busy — re-ordering when it's done"
UPDATE = "An update is waiting — re-ordering after it"
UP_TO_DATE = "Anki's order is up to date"
# --- P4.1 L2 (TF fix 10, IK #6): a job that took a show's new cards out, or put them back, says so ---
CARDS_TAKEN_OUT = "{n:,} new card{s} taken out of your order (suspended in Anki, never deleted)"
CARDS_PUT_BACK = "{n:,} card{s} put back in your order"
# --- end P4.1 L2 ---
# A reorder you started (or one of Connect's) didn't finish: only its Restore goes on from there (I3) — in 順 until
# the new window has its own.
RESTORE_FIRST = "Anki not re-ordered: the last reorder didn't finish — undo it in 順"
NEW_CONTENT = "New content: press Generate once you've placed it"
GENERATE_FIRST = "New content or settings: Generate runs first, then Anki is re-ordered"
GENERATE_FIRST_CM = "New content or settings: Generate runs first (when you close the Content Manager), then Anki is re-ordered"
PRESS_GENERATE = "New content or settings: press Generate, then Anki is re-ordered"
REPLAN_THEN_GENERATE = "Anki re-ordered · refreshing your list (Generate)…"
REPLAN_THEN_GENERATE_CM = "Anki re-ordered · your list refreshes (Generate) when you close the Content Manager"
# 3.0's gate (`stands_aside`): why the host does nothing now.
AUTOMATION_OFF = "Automation is off — Anki is re-ordered only when you run 順 yourself"
JUNBAN_OFF = "順 is off — switch it on to re-order Anki as you move"
JUNBAN_ABSENT = "順 isn't installed — Anki isn't re-ordered as you move"
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}
STAND_ASIDE = {
    "shared-phrase": "This list holds a row two set phrases share — Generate re-orders Anki this time",
    "weights": "Your tier weights aren't whole numbers — Generate re-orders Anki",
}
STAND_ASIDE_ELSE = "Generate re-orders Anki this time"
# D7 (`unavailable`): why the preview can't run with these settings
ONE_DECK = "It needs one deck: choose it in 順's deck list (never All decks)."
NOT_COVERAGE = "Not with Coverage selection: there the list's words depend on the order, so only Generate can tell."
NOT_I_PLUS_ONE = "Not with 'Only i+1': there the list's words depend on the order, so only Generate can tell."
# a7 (Sonic 2026-10-29: yellow only with a decision): Only i+1 or Coverage standing the host aside is a fact, said as one
MODE_NAMES = {NOT_COVERAGE: "Coverage %", NOT_I_PLUS_ONE: "Only i+1 sentences"}
AFTER_GENERATE = ("Anki is re-ordered after each Generate, not as you move: with {mode} on, your list's words depend on "
                  "its order")
NOT_BY_ITSELF = ("Anki isn't re-ordered as you move: with {mode} on, your list's words depend on its order — 順 "
                 "re-orders it when you run it")


class GivesUp(str):
    """finish-pending (its fix round, FP-A2 / A5): a line the host says as it stops short of the re-order it owes and
    leaves it to the user — Anki closed, a Generate to press, 順's deck to pick, an unfinished run to undo, a refusal it
    never retries. Said as that kind where it is said (`Host._tell(line, gives_up=True)`), carried over the helper's
    pipe, never read back from its words: the window's press waiting for that re-order ends failed, with these words.
    Its retries ("Anki not re-ordered: …" when it tries again in RETRY_S), a stand-aside or Generate-first line (the
    Generate re-orders by itself), an update's hold and its progress are plain lines: the press keeps turning."""
    __slots__ = ()


class Fails(GivesUp):
    """a7 (Sonic 2026-10-29: yellow only with a decision): a line that gives up on a fault — the host's job stopped on
    an error, a refusal it never retries. A press waiting ends failed with it, as with any line that gives up; the phase
    strip shows it red, never amber (a fault is no decision). Said as that kind (`Host._tell(line, fails=True)`) and
    carried over the pipe the same way."""
    __slots__ = ()


class InJunban(GivesUp):
    """Alpha 3 (the lead's ruling on the intent keeper's IKA3-1): a line that gives up whose fix is in 順's own window —
    the unfinished reorder's Undo, a deck to pick. The phase strip's 順 press opens that window for it, the control
    highlighted (else Junban's settings). Said as that kind (`Host._tell(line, in_junban=True)`) and carried over the
    pipe the same way. a7: the one kind of line that makes 順 amber — every other line that gives up (Anki closed, a
    Generate to press, Only i+1 or Coverage) is said in the hover with nothing to decide, and a `Fails` is red."""
    __slots__ = ()


OFF = GivesUp("")      # no words: nothing re-orders now by the user's own choice (automation or 順 off, 順 absent) —
#                        `ReplanHost` tells it as it lets the host go so; a press waiting ends quietly


def ends_with(why):
    """`stands_aside`'s reason `why` as a waiting press ends with it: OFF for the user's own choices (D29 off, 順 off or
    absent), else the reason as a line that gives up (the deck to pick, D7's one deck)."""
    return OFF if why in (AUTOMATION_OFF, JUNBAN_OFF, JUNBAN_ABSENT) else GivesUp(why)


def junban_present():
    """Is Junban installed? Asked without importing it (core never imports `modules/` at load: Backlog spec I2)."""
    if sys.modules.get("modules.junban") is not None:       # load_settings imported it (its defaults)
        return True
    try:
        return importlib.util.find_spec("modules.junban") is not None
    except (ImportError, ValueError):
        return False


def preview_language(settings):
    """The language the preview runs for: the one 順's switch was turned on in (its deck's), "ja" when unsaid."""
    return str((settings or {}).get(LANGUAGE) or "ja").strip().lower() or "ja"


def is_on(settings, language=None):
    """The preview's switch: on, Junban switched on and present — and, given a `language`, that language's (a
    Chinese Generate never re-orders the Japanese deck: `junban_deck` is one key for both). 2.x's gate; on 3.0 the
    Tk windows still ask it whether to make a host (until W3.4), and the host itself asks `automation_on`."""
    settings = settings or {}
    if settings.get(SWITCH) is not True or settings.get("enable_junban") is not True:
        return False
    if language is not None and preview_language(settings) != str(language).strip().lower():
        return False
    return junban_present()


def unavailable(settings):
    """Why the preview can't run with these settings (D7; 01 §7), or None: one deck (never All decks), not
    Coverage selection, not "Only i+1" — there the list's words themselves depend on the order."""
    settings = settings or {}
    scope = str(settings.get("junban_scope") or "deck").strip().lower()
    if scope != "deck" or not str(settings.get("junban_deck") or "").strip():
        return ONE_DECK
    if settings.get("strategy") == "coverage":
        return NOT_COVERAGE
    if settings.get("only_i_plus_one"):
        return NOT_I_PLUS_ONE
    deck = deck_set_aside(settings)
    if deck:
        now = str(settings.get("junban_deck") or "").strip()
        # Both decks named, and the box left enabled (`deck_set_aside`): ticking it again records this deck (review 3
        # R4) — in the language of the deck it should re-order.
        return (f"順's deck changed since this was switched on for {deck}: pick {deck} again in 順, or switch this on "
                f"again for {now} — in {now}'s language.")
    return None


def deck_set_aside(settings):
    """The deck the preview was switched on for, when 順's deck is another one now (the preview then stands aside),
    else None. 順 never greys its box for it: ticking it again is how the preview moves to the deck shown."""
    deck = str((settings or {}).get(DECK) or "").strip()
    return deck if deck and deck != str((settings or {}).get("junban_deck") or "").strip() else None


def _language(code):
    return str(code or "").strip().lower()


def recorded_deck(settings, language):
    """3.0 (Haya's G3): the deck the host may re-order for `language` — when 順 recorded the pair, its language
    (`junban_replan_language`) this one and its deck (`junban_replan_deck`) 順's deck now — else None. Never
    `preview_language`'s "" → "ja": with nothing recorded, `junban_deck` can be a Chinese deck picked in a Chinese 順
    window. The one place the 3.0 gate reads the deck (W3.3's per-language deck, D31's profiles: change it here)."""
    settings = settings or {}
    deck = str(settings.get(DECK) or "").strip()
    if not deck or _language(settings.get(LANGUAGE)) != _language(language):
        return None
    return deck if deck == str(settings.get("junban_deck") or "").strip() else None


def _deck_line(settings, language):
    """The deck's reason (`recorded_deck` said None): 順's deck, and the language it is recorded for, if another."""
    deck = str(settings.get("junban_deck") or "").strip()
    name = LANGUAGE_NAMES.get(_language(language), language)
    recorded = _language(settings.get(LANGUAGE))
    if recorded and recorded != _language(language) and str(settings.get(DECK) or "").strip() == deck:
        return (f"順's deck {deck} is recorded for {LANGUAGE_NAMES.get(recorded, recorded)} — pick your {name} deck in "
                f"順's window in {name}")
    return f"順's deck {deck} isn't recorded for {name} — pick it in 順's window in {name}"


def _stand_aside(settings, language):
    """-> (why, the deck's reason?) — `stands_aside`, and whether its line is the deck's (the host says that one)."""
    from app import settings_manager
    settings = settings or {}
    if not settings_manager.automation(settings):
        return AUTOMATION_OFF, False
    if settings.get("enable_junban") is not True:
        return JUNBAN_OFF, False
    if not junban_present():
        return JUNBAN_ABSENT, False
    why = unavailable(dict(settings, **{DECK: ""}))     # D7; 2.x's deck record is the pair's, below, on 3.0
    if why is not None:
        return why, False
    if recorded_deck(settings, language) is None:
        return _deck_line(settings, language), True
    return None, False


def stands_aside(settings, language):
    """3.0 (W3.5 row 7; Haya's G2a): None when the re-order host may run for `language`, else one plain line saying
    why — D29 off, Junban off or absent, D7 (`unavailable`), the (language, deck) pair not recorded — in that order.
    `junban_replan_preview` (2.x's box) is never read: on 3.0, D29 is the one switch."""
    return _stand_aside(settings, language)[0]


def aside_line(settings, language):
    """a7 (Sonic 2026-10-29: "If yellow i would expect it to let me go somewhere to make a decision that is
    highlighted. If no decision it shouldn't be yellow but something else."): `stands_aside`'s reason as the bar and
    the phase strip say it, or None (the host may run). `OFF` for the user's own choices (D29 off, 順 off or absent);
    `InJunban` where the fix is a deck to pick in 順's window (D7's one deck, the deck not recorded); Only i+1 or
    Coverage a fact (a plain `GivesUp`): Generate's own 順 run re-orders Anki when it is switched on with a recorded
    deck (`automation.reorders`' rule) — else 順 does when the user runs it; with that switch on and no deck recorded,
    the deck to pick in 順 is the decision (Generate can't re-order without it). Asked on the host's worker."""
    settings = settings or {}
    why, deck = _stand_aside(settings, language)
    if why is None:
        return None
    if deck or why == ONE_DECK:
        return InJunban(why)
    mode = MODE_NAMES.get(why)
    if mode is None:
        return ends_with(why)
    if settings.get("junban_auto_reorder") is not True:
        return GivesUp(NOT_BY_ITSELF.format(mode=mode))
    if recorded_deck(settings, language) is None:
        return InJunban(_deck_line(settings, language))
    return GivesUp(AFTER_GENERATE.format(mode=mode))


def automation_on(settings, language):
    """3.0's predicate: may the host run for `language` now? Asked fresh on the host's worker every job."""
    return stands_aside(settings, language) is None


def plan_path():
    from app import analyzer
    from app.path_utils import get_user_file
    return os.path.join(get_user_file("results"), analyzer.PLAN_FILE)


def places(plan, ids, result):
    """RP-10: {the plan's file number (1-based, the run's order): its number in `result`'s order} — what
    `library_frequency.json` and the phrase places still carry, read through the new order. A file the order left
    (it left the counted tiers) goes after every other."""
    after = len(result.sequence) + 1
    return {number: result.sequence.get(item_id, after) if item_id is not None else after
            for number, item_id in enumerate(ids, 1)}


def anki_connect_reviewing(job):
    """Did the run stop for a review (`set_due_checked`'s `stop_if` said so)?"""
    return bool(getattr(job, "stopped_for_review", False))


def _snapshot(store):
    """The store's versions and its analysed tiers' order, read in one transaction: {path_key: (rank, place, tier)},
    rank the tier's place in NOW, Soon, 6+ Months — sorting the values gives the study order."""
    schedule, versions = store.schedule(with_versions=True)
    return versions, _order(schedule)


def _order(schedule):
    """`_snapshot`'s order from a schedule already read (`store.schedule()`): Connect's re-plan reads the schedule once
    for the order and the run signature's files (P3.3)."""
    from app import library_store
    order = {}
    for rank, tier in enumerate(TIERS):
        phase = library_store.TIERS[tier][0]
        for place, entry in enumerate(schedule.get(phase) or []):
            order[library_store.path_key(entry["physical_path"])] = (rank, place, tier)
    return order


class Host:
    """The preview in one window's process (the Content Manager's, the dashboard's): one worker, one engine, one
    warm card map, one bar line. See the module docstring."""

    def __init__(self, language, say=None, working=None, generate=None):
        self.language = language
        self._say = say or (lambda line: None)
        self._working = working or (lambda on: None)
        self._generate = generate                 # the dashboard's: start an automatic Generate (it applies its rules)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancel = threading.Event()          # a lock wait ends when the window closes
        self._lock = threading.Lock()
        self._thread = None
        self._due = None                          # monotonic: the settle's end
        self._want = set()                        # "move", "catch-up", "generate", "warm", "sync-now"
        self._retry_at = None                     # monotonic, and the kind to run again then
        self._retry_kind = None
        self._force = False                       # the next job runs owed or not (a newer order planned meanwhile)
        self._sync_at = None                      # wall time: S3's
        self._running = False
        self._closing = False
        self._anki_looked = -CHECK_ANKI_S
        self._done_at = None
        self._asked = None                        # the last automatic Generate asked for: (reason, the run stamp)
        self._aside = None                        # the stand-aside line last said (once per distinct reason)
        self._seen = None                         # the catch-up's last look with nothing owed (store, plan, run)
        self._plan = self._plan_key = self._engine = self._ids = None
        self._cards = None
        self._probe = None                        # `_may_write`'s probe, for this job's run
        self.last = ""                            # the last line said (tests; the window's line)
        self.web = ""                             # the AnkiWeb indicator's words, worked out on the worker

    # --- the window's calls (any thread; never block) --------------------------------------------------------- #

    def poke(self):
        """A store change in this window (a move, Undo, another program's change, a disk sync): the settle restarts."""
        with self._lock:
            if self._closing:
                return
            self._due = time.monotonic() + SETTLE_S
            self._want.add("move")
        self._start()

    def catch_up(self):
        self._ask("catch-up")

    def after_generate(self):
        self._ask("generate")

    def warm(self):
        """Load the plan and the engine now (the CM's open, 04 §2.1), so the first move pays nothing for them."""
        self._ask("warm")

    def _ask(self, kind):
        with self._lock:
            if self._closing:
                return
            self._want.add(kind)
        self._start()

    def busy(self):
        with self._lock:
            return self._running or bool(self._want) or self._due is not None

    def close(self):
        """The window closes (04 §2.5): a pending settle runs at once, a pending S3 sync runs at once; nothing new.
        Returns at once — the window waits on `busy()` (at most CLOSE_WAIT_S) before it goes."""
        with self._lock:
            self._closing = True
            self._retry_at = None
            self._want -= {"catch-up", "warm"}
            if self._due is not None:
                self._due = time.monotonic()
            self._want.add("sync-now")
        self._start()

    def stop(self):
        """The window is gone: the worker ends (a lock wait is let go)."""
        self._stop.set()
        self._cancel.set()
        self._wake.set()

    # --- the worker ------------------------------------------------------------------------------------------ #

    def _start(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="replan-preview", daemon=True)
                self._thread.start()
        self._wake.set()

    def _next_wait(self):
        now, wall = time.monotonic(), time.time()
        waits = [3600.0]
        with self._lock:
            if self._want - {"move"}:
                return 0.0
            if self._due is not None:
                waits.append(self._due - now)
            if self._retry_at is not None:
                waits.append(self._retry_at - now)
        if self._sync_at is not None:
            waits.append(min(1.0, self._sync_at - wall))      # the indicator's countdown, once a second
        if self._done_at is not None:
            waits.append(self._done_at - now)
        return max(0.0, min(waits))

    def _loop(self):
        while not self._stop.is_set():
            self._wake.wait(self._next_wait())
            self._wake.clear()
            if self._stop.is_set():
                break
            self.run_pending()
            with self._lock:
                if self._closing and not self._want and self._due is None:
                    self._running = False
                    break

    def run_pending(self):
        """Whatever is due now, in order — the worker's step (a test calls it directly). Each kind on its own: one
        that fails says so and never drops the others."""
        with self._lock:
            now = time.monotonic()
            if self._retry_at is not None and now >= self._retry_at:
                kind, self._retry_at = self._retry_kind or "move", None
                self._want.add(kind)
                if kind == "move":
                    self._due = now
            run = {kind for kind in ("warm", "generate", "catch-up", "sync-now") if kind in self._want}
            if "move" in self._want and self._due is not None and now >= self._due:
                run.add("move")
                self._due = None
            self._want -= run
            self._running = True
        try:
            for kind in KINDS:
                if kind in run:
                    try:
                        self._warm() if kind == "warm" else self._job(kind)
                    except Exception as e:          # a background job must never take the window down
                        self._tell(f"Re-ordering as you move stopped: {e}", fails=True)
            self._sync_step(force="sync-now" in run)
            if self._done_at is not None and time.monotonic() >= self._done_at:
                self._done_at = None
                self._tell(UP_TO_DATE)
            self._refresh_web()
        finally:
            with self._lock:
                self._running = False

    # --- pieces ---------------------------------------------------------------------------------------------- #

    def _tell(self, line, gives_up=False, in_junban=False, fails=False):
        """The bar's line; `gives_up`: one that leaves the re-order it owes to the user (`GivesUp`); `in_junban`: one
        of those whose fix is in 順's window (`InJunban`); `fails`: one of those on a fault (`Fails`)."""
        line = InJunban(line) if in_junban else Fails(line) if fails else GivesUp(line) if gives_up else line
        self.last = line
        try:
            self._say(line)
        except Exception:
            pass

    def _settings(self):
        from app import settings_manager
        settings = dict(settings_manager.load_settings() or {})
        settings["target_language"] = self.language
        return settings

    def _open_store(self):
        """A store handle for this job (closed after it: a long-lived handle would hold Repair's rename back)."""
        from app import library_store
        from app.path_utils import get_data_path, get_user_files_path
        return library_store.open_store(self.language, get_data_path(self.language),
                                        get_user_files_path(self.language), role="window")

    def _load_plan(self):
        """The plan file, loaded once per version of the file -> (plan, None) or (None, why)."""
        from app import plan_engine
        path = plan_path()
        try:
            st = os.stat(path)
        except OSError:
            self._plan = self._plan_key = self._engine = self._ids = None
            return None, "no-plan"
        key = (st.st_mtime_ns, st.st_size)
        if key != self._plan_key or self._plan is None:
            try:
                plan = plan_engine.load(path)
            except plan_engine.PlanError as e:
                self._plan = self._plan_key = self._engine = self._ids = None
                return None, f"plan: {e}"
            self._plan, self._plan_key, self._engine, self._ids = plan, key, None, None
        return self._plan, None

    def _engine_for(self, store):
        from app import plan_engine
        ids = [store.item_id(entry[0]) for entry in self._plan.files]
        if self._engine is None or ids != self._ids:
            self._engine, self._ids = plan_engine.Engine(self._plan, ids), ids
        return self._engine, ids

    def _parts(self, settings, store):
        """The run signature's parts for the library as it stands (stats every file: on this worker only). A missing
        item keeps its place, as Generate and the journey checks sign it (3.0, E2.2's K2: `missing=True`); the set-aside
        files are its "reference" part (W-1: a watched mark is a Generate first, both ways)."""
        from app import analyzer, run_args
        schedule = store.schedule(with_aside=True)
        found = analyzer.resolve_found_files(self.language, verbose=False, schedule=schedule, missing=True)
        args = analyzer.parse_analysis_args(run_args.analyzer_args(settings, self.language)[1:])
        return analyzer.run_signature_parts(self.language, found, args, analyzer.aside_files(self.language, schedule))

    def _verdict(self, plan, parts, store):
        from app import analyzer, plan_engine
        from app.path_utils import get_user_file
        return plan_engine.check(plan, self.language, analyzer.engine_id(),
                                 analyzer.read_run_stamp(get_user_file("results")), parts,
                                 store.versions().get("epoch"))

    def _warm(self):
        """04 §2.1: the plan and the engine (never for a plan the engine stands aside from); Junban warms on the
        first job (its tables build while Anki answers)."""
        settings = self._settings()
        if not automation_on(settings, self.language):      # 3.0's gate (W3.5 row 7), never 2.x's box
            return
        self._sync_at = self._due_sync(settings)
        plan, _why = self._load_plan()
        if plan is None:
            return
        from app import plan_engine
        if plan_engine.stands_aside(plan):
            return
        store = self._open_store()
        if store is None:
            return
        try:
            self._engine_for(store)
        finally:
            store.close()
        from modules.junban import reposition
        reposition.prepare(settings)                 # Junban's tables, the library map, the known words

    def _job(self, kind):
        """One job (04 §2.3): "move" (the CM's settle), "catch-up" (start, focus, the CM's open) or "generate"
        (after a full Generate)."""
        settings = self._settings()
        why, deck = _stand_aside(settings, self.language)    # 3.0's gate, read fresh every job (W3.5 row 7)
        if why is not None:
            if deck and why != self._aside:
                self._aside = why
                self._tell(why, in_junban=True)      # the deck's reason, once per reason: the user can fix it in 順
            return
        self._aside = None
        self._sync_at = self._due_sync(settings)      # a write elsewhere (順's own run, a closed window) armed one
        store = self._open_store()
        if store is None:
            return                                   # no library store (JSON mode): nothing to re-plan from
        try:
            self._run_job(kind, settings, store)
        finally:
            store.close()

    def _run_job(self, kind, settings, store):
        versions, order = _snapshot(store)
        force, self._force = self._force, False
        owed = (force or versions["order_version"] > versions["planned_order_version"]
                or versions["pins_version"] > versions["planned_pins_version"])
        if kind == "move" and not owed:
            return                                   # nothing moved since the last re-order: nothing read, nothing stat'd
        if kind == "catch-up" and not owed:
            owed = self._unplaced(settings)
            if not owed and self._generate is None:
                return
        previous = self._plan
        plan, why = self._load_plan()
        if kind == "catch-up" and not owed:
            # Focus comes often: with nothing owed, the library's files are stat'd again only when the store, the plan
            # or the run moved since the last look.
            from app import analyzer
            from app.path_utils import get_user_file
            seen = (tuple(sorted(versions.items())), self._plan_key, analyzer.read_run_stamp(get_user_file("results")))
            if seen == self._seen:
                return
            self._seen = seen
        if kind == "generate":
            # After a full Generate (04 §3): shadow mode against the plan it replaced (05 §3), then the re-order from
            # its plan in the store's order now — its own order, or a move made while it ran — whatever was recorded.
            if plan is not None:
                self._shadow(previous, plan)
            owed = True
        writable = owed and self._may_write(settings, kind)
        if owed and not writable:
            if kind == "generate" or force:
                # Anki closed at the Generate's end (or a newer order planned meanwhile): the next catch-up re-orders —
                # kept until a job can write, through every look while Anki stays closed (review 3 R1).
                self._force = True
            if kind != "catch-up" or self._generate is None:
                return                               # 順's window, an update, Anki closed or a review: said, retried
        if kind == "catch-up" and owed and not force:
            # An owed re-order the plan can't serve (new content, a stand-aside plan, Anki closed) is looked at again
            # only when the store, the plan or the run moved: focus comes often.
            from app import analyzer
            from app.path_utils import get_user_file
            seen = ("owed", writable, tuple(sorted(versions.items())), self._plan_key,
                    analyzer.read_run_stamp(get_user_file("results")))
            if seen == self._seen:
                return
            self._seen = seen
        # The library's files stat'd only where something reads them (review 3 R9): the plan's check, a Generate's
        # list path, the dashboard's journey.
        parts = (self._parts(settings, store) if plan is not None or kind == "generate" or self._generate is not None
                 else None)
        verdict = self._verdict(plan, parts, store) if plan is not None else ("generate-first", why)
        if writable:
            done = self._replan(settings, store, versions, order, verdict, kind, parts)
            if done:
                self._seen = None
            elif force and self._retry_at is not None:
                self._force = True                   # interrupted (a review, cards changed mid-write): still owed (pass 4 #2)
        elif verdict is not None and verdict[0] == "generate-first" and plan is not None and self._moved(store, order):
            self._ask_generate(f"generate-first: {verdict[1]}")      # Anki closed: the list refreshes all the same
        if kind == "catch-up" and self._generate is not None:
            self._journey(plan, parts, verdict, store)

    def _may_write(self, settings, kind):
        """The guards a write needs (04 §4), asked before the library is read: 順's window open (waited for), an
        update waiting, Anki closed (the next sight of it catches up), a review (waited for). The probe is the run's
        own (Junban's preflight, on the job's settings as `_write` decides them), kept for the job's run (E3.1-B2:
        asked once)."""
        from app import anki_connect, anki_sync_rule
        from modules.junban import auto, reposition
        self._probe = None
        blocked = auto.blocked(settings)
        if blocked:
            if blocked == "the 順 window is open":
                self._tell(BUSY)
                self._retry(kind)
            elif blocked == "an update is waiting":
                self._tell(UPDATE)
            return False
        if _update_staged():
            # "Update now" in another process (the dashboard's hold is its own: E3.1 pass 4 #1) — never a write then.
            self._tell(UPDATE)
            return False
        url = anki_connect.address(settings)
        probe = reposition.probe_anki(auto.decide_actions(dict(settings)))     # what the job's run will need
        if not probe.get("ok") and probe.get("timed_out"):
            self._tell(NOT_ANSWERING)                # open but busy: never "closed" (review 3 R6: S3 stays pending)
            self._retry(kind)
            return False
        if not probe.get("ok") and not probe.get("missing"):     # an old AnkiConnect: the run says what it lacks
            anki_sync_rule.closed_seen()
            self._tell(CLOSED, gives_up=True)
            return False
        if anki_connect.reviewing(url):
            self._tell(REVIEWING)
            self._retry(kind)
            return False
        self._probe = probe
        return True

    def _replan(self, settings, store, versions, order, verdict, kind="move", parts=None):
        """The re-order for `verdict` -> True when Anki now holds the order the store asks for."""
        from modules.junban import spaced
        if verdict is not None and verdict[0] in ("stand-aside", "generate-first") and kind == "generate":
            # After a Generate the list itself is current — when it is this library's latest run (a Generate that
            # failed leaves the last one's, maybe the other language's): then, when the engine can't replay the plan
            # (or none was written), the automatic step runs from the list, as 2.5's did (04 §1(b)).
            from app import analyzer, plan_rules
            from app.path_utils import get_user_file
            try:
                current = plan_rules.signature_digest(parts) == analyzer.read_run_stamp(get_user_file("results"))
            except Exception:
                current = False
            if not current:
                self._tell(PRESS_GENERATE, gives_up=True)   # the Generate just ran (and failed): none is asked for again (R10)
                return False
            report = self._write(settings, spaced.Job(automatic=True, cards=self._card_map()), kind)
            _record_cards_out(store, report)             # P4.1 L2
            if report is not None and report.get("ok") and not report.get("left") and not report.get("failures"):
                store.record_planned(versions["order_version"], versions["pins_version"])
                return True
            return False
        if verdict is not None and verdict[0] == "stand-aside":
            self._tell(STAND_ASIDE.get(verdict[1], STAND_ASIDE_ELSE))
            return False
        if verdict is not None and verdict[0] == "generate-first":
            if self._plan is not None and not self._moved(store, order):
                # Nothing the plan holds moved: the host asks for no Generate. Where the store's order or pins moved
                # since the plan (a placement), a Generate is coming on 3.0 — the window's hook makes it the journey
                # keeper's, then `after_generate` (Haya's G4) — and the line says so. Elsewhere (new or changed files
                # alone, a setting) none is: the keeper is never asked for those, so 2.x's words stand (pass 4 #13).
                if (versions["order_version"] > versions["planned_order_version"]
                        or versions["pins_version"] > versions["planned_pins_version"]):
                    self._tell(GENERATE_FIRST if self._generate is not None else GENERATE_FIRST_CM)
                else:
                    self._tell(NEW_CONTENT if verdict[1] == "files" else PRESS_GENERATE, gives_up=True)
                return False
            asked = self._ask_generate(f"generate-first: {verdict[1]}")
            self._tell((GENERATE_FIRST if self._generate is not None else GENERATE_FIRST_CM) if asked is not False
                       else PRESS_GENERATE, gives_up=asked is False)
            return False
        engine, ids = self._engine_for(store)
        ranked = sorted((order[key] + (item_id,) for key, item_id in self._plan_keys(ids) if key in order))
        result = engine.replan([(item_id, tier) for _rank, _place, tier, item_id in ranked])
        mode = str(settings.get("junban_order") or "content").strip().lower()
        rows = result.rows(mode if mode in ("content", "priority") else "content")
        job = spaced.Job(automatic=True, rows=rows, cards=self._card_map(), places=places(self._plan, ids, result))
        report = self._write(settings, job, kind)
        _record_cards_out(store, report)                 # P4.1 L2
        done = bool(report is not None and report.get("ok") and not report.get("left") and not report.get("failures"))
        if done:
            store.record_planned(versions["order_version"], versions["pins_version"])
            after = store.versions()
            if after["planned_order_version"] > versions["order_version"] or \
                    after["order_version"] > versions["order_version"]:
                # Another window planned (or the user moved) a newer order while this one was being written: this
                # write may have landed over it. One more job, owed or not.
                with self._lock:
                    self._force = True
                    if not self._closing:
                        self._want.add("move")
                        self._due = time.monotonic()
                self._wake.set()
        if verdict is not None and verdict[0] == "replan-now" and report is not None and report.get("ok"):
            if not report.get("empty_list"):        # M-W2-1: the empty list's own line stands
                self._tell(REPLAN_THEN_GENERATE if self._generate is not None else REPLAN_THEN_GENERATE_CM)
            self._done_at = None
            self._ask_generate("replan-now: " + ",".join(verdict[1]))
        return done

    def _plan_keys(self, ids):
        from app import library_store
        return [(library_store.path_key(entry[0]), item_id)
                for entry, item_id in zip(self._plan.files, ids) if item_id is not None]

    def _moved(self, store, order):
        """Did anything the plan holds move — its files' order or tiers in the store now, against the run's own?"""
        from app import library_store
        then, now = [], []
        for entry in self._plan.files:
            key = library_store.path_key(entry[0])
            then.append((key, entry[1]))
            if key in order:
                now.append(order[key] + (key,))
        now = [(key, tier) for _rank, _place, tier, key in sorted(now)]
        return now != then                         # a file that left the counted tiers (Finished) is a move too

    def _card_map(self):
        if self._cards is None:
            from modules.junban import reposition
            self._cards = reposition.CardMap()
        return self._cards

    def _write(self, settings, job, kind):
        """Junban's run for `job` and its bar lines -> the report, or None when nothing ran (the line said why;
        `kind` runs again later when it's worth it).

        2.x-dev keeps the host's job positions only (`auto._POSITIONS_ONLY` laid over the settings: E1.1 04 §1); 3.0
        (Sonic, 2026-10-13: "it just works"): your 順 settings, decided as 順's automatic step decides them
        (`auto.decide_actions`), ride every job — the positions first, then the touch-ups, tag, flag and suspend last,
        under the window's snapshot (`reposition._run`). The plan asks only what differs from Anki now (a note
        already tagged, a card already purple or suspended is no work), so a move with nothing new to act on sends
        exactly a positions-only job's requests, with no re-check read."""
        from app import anki_connect
        from modules.junban import auto, reposition
        auto.decide_actions(settings)
        job.actions = True
        job.cards_out = True        # P4.1 L2: the host records what *Take its new cards out* changes (`_replan`)
        job.probe, self._probe = self._probe, None    # `_may_write`'s, this job's: the run asks Anki nothing again
        self._working(True)
        try:
            report = reposition.run(settings, progress=self._progress(job), refresh=False, wait=None,
                                    cancel=self._cancel, verb=VERB, job=job,
                                    on_wait=lambda holder: self._tell(anki_connect.waiting_line(holder)))
        finally:
            self._working(False)
        self._sync_at = self._due_sync(settings)
        if report.get("stands_aside") or report.get("one_deck"):
            # FT C1: a put-back cleared this deck while the job waited for the lock — nothing written; the next job's
            # gate reads the file and stands aside too. Said, never retried: picking the deck in 順 is the user's. So
            # is All decks met by the job itself (`one_deck`: the scope changed after the gate was asked).
            self._tell((report.get("problems") or [""])[0], in_junban=True)
            return None
        if report.get("busy"):
            if not self._cancel.is_set():
                problem = (report.get("problems") or [""])[0]
                self._tell(REVIEWING if problem == anki_connect.REVIEWING else BUSY)
                self._retry(kind)
            return None
        if report.get("reviewing"):
            self._tell(REVIEWING)
            self._retry(kind)
            return report
        if report.get("restore_first"):
            self._tell(RESTORE_FIRST, in_junban=True)   # only you can clear it, in 順: said, not retried
            return report
        if not report.get("ok"):
            written = len(report.get("written") or [])
            problems = report.get("problems") or ["it could not finish"]
            again = bool(written or report.get("failures") or report.get("anki_error") == "offline")
            self._tell(f"Anki re-ordered {written:,} cards, then stopped: {problems[0]} — the rest at the next re-order"
                       if written else f"Anki not re-ordered: {problems[0]}", fails=not again)
            if again:
                self._retry(kind)                    # Anki went away mid-write: again soon. A refusal only the user
            return report                            # can clear (an unfinished run, a missing deck) waits for them
        self._said_done(report, job)
        if report.get("left"):
            self._retry(kind)                        # as itself: a Generate's re-order owes nothing to the store (#2)
        return report

    def _progress(self, job):
        def progress(done, total):
            from modules.junban import spaced
            n = job.front_size or 0
            if job.kind == spaced.FULL and total > 200:
                self._tell(f"Anki: spacing your new cards out once so later moves are quick — {done:,} of {total:,}…")
            elif done < len(job.front_ids):
                self._tell(f"Anki: placing tomorrow's {n} cards…")
            elif done < total and not job.front_ids:    # a move behind tomorrow's: they never had to wait (E3.3)
                self._tell(f"Anki: tomorrow's {n} already in place · moving {total - done:,} more…")
            elif done < total:
                self._tell(f"Anki: tomorrow's {n} cards placed · moving {total - done:,} more…")
        return progress

    def _said_done(self, report, job):
        from modules.junban import spaced
        if report.get("empty_list"):
            self._tell(report["message"])            # M-W2-1: nothing that counts, so nothing put away — said so
            return
        written = set(report.get("written") or [])
        n = job.front_size or 0
        front = len(written & set(job.front_ids))
        rest = len(written) - front
        if not written and report.get("left") and anki_connect_reviewing(job):
            self._tell(REVIEWING)                    # stopped for a review before anything landed (review 3 R10)
            return
        if not written:
            line = UP_TO_DATE
        elif job.kind == spaced.FULL and report.get("left"):
            line = f"Anki: {len(written):,} of your new cards spaced out so far — tomorrow's {n} first"
        elif job.kind == spaced.FULL:
            line = f"Anki: your {len(written):,} new cards are spaced out (once) — tomorrow's {n} first"
        elif front:
            line = f"Anki: tomorrow's {n} cards placed · {rest:,} more moved"
        else:
            line = f"Anki: {rest:,} cards moved · tomorrow's {n} already in place"
        if report.get("left") and anki_connect_reviewing(job):
            line += " · the rest after your review"
        elif report.get("left"):
            line += f" · {len(report['left'])} changed in Anki meanwhile, placed next"
        # --- P4.1 L2 (TF fix 10, IK #6): cards taken out or put back are named — never "up to date" alone ---
        cards = _cards_out_line(report)
        if cards:
            line = f"Anki: {cards}" if line == UP_TO_DATE else f"{line} · {cards}"
        # --- end P4.1 L2 ---
        self._tell(line)
        if written and not report.get("left"):      # cards still waiting: never "up to date" 5 s later (R10)
            self._done_at = time.monotonic() + DONE_S

    def _retry(self, kind):
        """Again in RETRY_S (a transient outcome: a review, a lock held, cards that changed mid-write) — a look of its
        own: the catch-up's memo of its last look (`_seen`) is let go, or the retry would return at once (review 3
        R2)."""
        with self._lock:
            if not self._closing:
                self._retry_at, self._retry_kind = time.monotonic() + RETRY_S, kind
                self._seen = None

    def _ask_generate(self, reason):
        """Ask the window for an automatic Generate — once per run (`results/`' stamp): the window keeps a request
        it can't start yet, and a Generate that ran and still left a reason (it couldn't write the plan) is not
        asked for again until another run."""
        if self._generate is None:
            return None
        from app import analyzer
        from app.path_utils import get_user_file
        asked = ("asked", analyzer.read_run_stamp(get_user_file("results")))
        if asked == self._asked:
            return False                             # asked once for this run already
        self._asked = asked
        try:
            self._generate(reason)
        except Exception:
            pass
        return True

    def _unplaced(self, settings):
        """New cards in the deck the last spaced run didn't place (03 §6: newly mined) — one `findCards`, at most
        every CHECK_ANKI_S, asking for exactly the cards a run places (not suspended, buried or in a filtered deck) —
        or a new card's note edited since the last run read it (drill A3 gap 3: its word changed, so may its place;
        `_edited`). Never raises."""
        now = time.monotonic()
        if now - self._anki_looked < CHECK_ANKI_S:
            return False
        self._anki_looked = now
        try:
            from app import anki_connect, anki_sync_rule
            from modules.junban import undo
            deck = str(settings.get("junban_deck") or "").strip()
            url = anki_connect.address(settings)
            probe = anki_connect.probe(url, timeout=3)
            if not probe.get("ok"):
                if not probe.get("timed_out"):       # a timeout is Anki busy, not closed (review 3 R6)
                    anki_sync_rule.closed_seen()
                return False
            ids = anki_connect.find_cards(url, f'deck:"{anki_connect.escape_query(deck)}" is:new -is:suspended '
                                               "-is:buried -deck:filtered")
            seen = undo.ladder(self.language, [deck]).get("seen")
            return (bool(ids) and (seen is None or max(ids) > seen)) or self._edited(url, deck)
        except Exception:
            return False

    def _edited(self, url, deck):
        """Drill A3 gap 3 (the lead, 2026-10-23): has a new card's note been edited since the last run read it? Anki's
        `edited:n` narrows it to the notes edited lately — n whole days back to the card map's last read plus two, as
        the Anki sync's delta reads edits (`anki_sync._ids_and_edits`) — one `findNotes`, and `notesModTime` only for
        those; each is held against the mod time the map read (`CardMap.note_mods`): one it never read, or read at
        another time (an edit here, or one a sync brought from your phone), is owed. No map yet (the app just
        started): any edit since Junban's last spaced run (its ladder file's time) is owed — one job, which fills the
        map. A job's own note writes (tags, Backfill) make the next look owe one more job, once."""
        from app import anki_connect
        known = getattr(self._cards, "note_mods", None) or {}
        since = getattr(self._cards, "read_at", 0) if known else self._last_run()
        if not since:
            return False
        days = min(EDITED_DAYS_MAX, int(max(0.0, time.time() - since) // 86400) + 2)
        notes = anki_connect.find_notes(url, f'deck:"{anki_connect.escape_query(deck)}" is:new -is:suspended '
                                             f"-is:buried -deck:filtered edited:{days}")
        if not notes:
            return False
        if not known:
            return True
        notes = list(notes)
        for at in range(0, len(notes), EDITED_CHUNK):
            mods = anki_connect.invoke("notesModTime", url, notes=notes[at:at + EDITED_CHUNK])
            if any(isinstance(m, dict) and known.get(m.get("noteId")) != m.get("mod") for m in mods or ()):
                return True
        return False

    def _last_run(self):
        """When Junban's last spaced run for this language recorded its ladder (its file's time), or 0."""
        try:
            from app.path_utils import get_user_files_path
            from modules.junban import undo
            return os.path.getmtime(os.path.join(get_user_files_path(self.language), undo.LADDER_FILENAME))
        except Exception:
            return 0

    def _journey(self, plan, parts, verdict, store):
        """The dashboard's automatic Generate beyond a re-order the plan can't serve (04 §3, ✅ G1.5-2 / G1.5-5): no
        plan at all (switched on, or lost), or the journey pending because of moves — moved since the last Generate
        (`journey_pending`) and the run no longer this library's — with nothing else changed, or only the known
        words or the lists (re-ordered from the plan already). New files alone start nothing (2.5's button)."""
        if plan is None:
            self._ask_generate("no-plan")
            return
        if verdict is not None and verdict[0] != "replan-now":
            return                                  # generate-first asks from the re-order itself; stand-aside: never
        from app import analyzer, plan_rules
        from app.path_utils import get_user_file
        try:
            full = plan_rules.signature_digest(parts)
            moved = store.journey_pending()
        except Exception:
            return
        if moved and full and full != analyzer.read_run_stamp(get_user_file("results")):
            self._ask_generate("moves")

    # --- S3 and the indicator --------------------------------------------------------------------------------- #

    @staticmethod
    def _due_sync(settings):
        try:
            from app import anki_sync_rule
            return anki_sync_rule.due_at(settings)
        except Exception:
            return None

    def _sync_step(self, force=False):
        """S3 (04 §3): the pending sync when it is due — at once when the window closes."""
        try:
            if self._sync_at is None and not force:
                return
            if not force and time.time() < self._sync_at:
                return
            from app import anki_connect, anki_sync_rule
            settings = self._settings()
            if not automation_on(settings, self.language):     # D29 off stops S3 too (Haya's G2a)
                self._sync_at = None
                return
            if _update_staged():
                if not force:                        # an update waits: no sync now (the pending one stays pending),
                    self._sync_at = time.time() + RETRY_S    # looked at again later, not on every turn (pass 5 #2)
                return
            _answer, self._sync_at = anki_sync_rule.sync_if_due(anki_connect.address(settings), settings,
                                                                 force=force, cancel=None if force else self._cancel)
        except Exception:
            self._sync_at = None

    def _refresh_web(self):
        """The indicator's words, read here (a small file) so the window's thread never reads it."""
        try:
            from app import anki_sync_rule, settings_manager
            self.web = anki_sync_rule.status(settings_manager.load_settings())
        except Exception:
            self.web = ""

    # --- shadow mode (05 §3) --------------------------------------------------------------------------------- #

    def _shadow(self, previous, plan):
        """Shadow mode (05 §3): the engine built from the previous plan, re-planned to this run's order, against
        this run's own lists. A difference writes one line to the log; the host goes on from the new plan."""
        if previous is None or previous is plan:
            return
        h0, h1 = previous.header, plan.header
        if h0.get("order_free_signature") != h1.get("order_free_signature") or \
                h0.get("run_signature") == h1.get("run_signature") or h0.get("language") != h1.get("language"):
            return
        try:
            from app import plan_engine
            if plan_engine.stands_aside(previous):
                return
            engine = plan_engine.Engine(previous, [entry[0] for entry in previous.files])
            result = engine.replan([(entry[0], entry[1]) for entry in plan.files])
            difference = _differs(result, _lists())
        except Exception as e:
            difference = f"the comparison failed: {e}"
        if difference:
            _log_shadow(f"{self.language} · {difference}")


# --- the helper process (E3.1-B1) -------------------------------------------------------------------------------- #

_HELPERS = []                   # every helper this process started (`helper_processes`: those still running)
_HELPERS_LOCK = threading.Lock()


# --- P4.1 L2: *Take its new cards out* (05 §5.7, D14) — the record Put back restores from ------------------------ #
def _record_cards_out(store, report):
    """A job's *Take its new cards out* changes into the store's `anki_changes`, and the records its Put back restored
    closed (`pins.record`), whatever the run's outcome (what landed is recorded). Never raises: logged."""
    if not (report or {}).get("cards_out") and not (report or {}).get("put_back"):
        return
    try:
        from modules.junban import pins
        pins.record(store, report, by="replan")      # TF fix 10 (IK #12): the host's own, never "connect"
    except Exception as e:
        _log_shadow(f"the cards Junban took out of the order weren't recorded: {e}")


def _cards_out_line(report):
    """The job's *Take its new cards out* in the bar's words (TF fix 10): how many it took out, how many it put back;
    "" when it did neither."""
    parts = []
    for key, words in (("cards_taken_out", CARDS_TAKEN_OUT), ("cards_put_back", CARDS_PUT_BACK)):
        n = (report or {}).get(key) or 0
        if n:
            parts.append(words.format(n=n, s="" if n == 1 else "s"))
    return " · ".join(parts)
# --- end P4.1 L2 ---


def helper_processes():
    """The helpers this process started that still run -> [Popen]. An update waits for them, wait-only
    (`updater.running_children`): the window stops its host first, and a helper ends after the job in hand."""
    with _HELPERS_LOCK:
        _HELPERS[:] = [p for p in _HELPERS if p.poll() is None]
        return list(_HELPERS)


def open_host(language, say=None, working=None, generate=None):
    """The window's host: `Remote` — the jobs in a helper process of its own — or, with IN_PROCESS_ENV ("1": the
    suites' fake Anki lives in their own process), the `Host` in the window's process. Same calls either way."""
    if os.environ.get(IN_PROCESS_ENV) == "1":
        return Host(language, say=say, working=working, generate=generate)
    return Remote(language, say=say, working=working, generate=generate)


class Remote:
    """`Host`'s calls, answered by a helper process that runs the `Host` (E3.1-B1): `python app/replan_preview.py`
    from source, `Surasura.exe replan_helper` frozen; `--language`, and `--generate` for the dashboard's (it may ask
    for a Generate). The two talk over a local pipe of their own (`multiprocessing.connection`, a random key in the
    helper's environment: no port, no console handles — Surasura.exe has none), one small JSON message a call each
    way; this side's thread only decodes them. Calls made before the helper answers wait for it, in order.

    The helper ends when this side goes (`stop`, or the window's process gone: the pipe breaks). A helper that can't
    start, or ends on its own, leaves the jobs to the window's own process from then on (`Host`, which then catches
    up: the store says what is owed) — the window works, with its pauses back."""

    def __init__(self, language, say=None, working=None, generate=None):
        self.language = language
        self._say = say or (lambda line: None)
        self._working = working or (lambda on: None)
        self._generate = generate
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._conn = None
        self._proc = None
        self._sent = 0                            # calls sent (numbered) …
        self._seen = 0                            # … and the last the helper has taken in
        self._busy = False                        # the helper's host, as it last said
        self._said_working = False                # the helper's last `working`: True while a write of its was under way
        self._waiting = []                        # calls made before the helper answered
        self._unseen = []                         # calls sent the helper hasn't said it took (a fallback replays them)
        self._local = None                        # the window's own Host, once the helper is out
        self._stopped = False
        self._last = ""
        self._web = ""
        threading.Thread(target=self._run, name="replan-remote", daemon=True).start()

    # --- Host's calls ---------------------------------------------------------------------------------------- #

    def poke(self):
        self._call("poke")

    def catch_up(self):
        self._call("catch_up")

    def after_generate(self):
        self._call("after_generate")

    def warm(self):
        self._call("warm")

    def close(self):
        self._call("close")

    def busy(self):
        with self._lock:
            local = self._local
            if local is None:
                return not self._stopped and (self._sent > self._seen or self._busy)
        return local.busy()

    def stop(self):
        """The window is gone: the helper ends (its job finishes the request it is in). Never waits."""
        with self._lock:
            self._stopped = True
            local, conn = self._local, self._conn
            self._waiting = []
        if local is not None:
            local.stop()
        if conn is not None:
            self._post(conn, {"do": "stop"})
            try:
                conn.close()
            except OSError:
                pass

    @property
    def last(self):
        local = self._local
        return local.last if local is not None else self._last

    @property
    def web(self):
        local = self._local
        return local.web if local is not None else self._web

    # --- the pipe ------------------------------------------------------------------------------------------- #

    def _call(self, do):
        with self._lock:
            local = self._local
            if local is None:
                if self._stopped:
                    return
                self._sent += 1
                message = {"n": self._sent, "do": do}
                conn = self._conn
                if conn is None:
                    self._waiting.append(message)
                    return
                self._unseen.append(message)
        if local is not None:
            getattr(local, do)()
            return
        self._post(conn, message)

    def _post(self, conn, message):
        try:
            with self._send_lock:
                conn.send_bytes(json.dumps(message).encode("utf-8"))
        except (OSError, ValueError):
            pass                                  # the reader finds the pipe broken and takes the jobs over

    def _run(self):
        try:
            conn = self._connect()
        except Exception as e:
            print(f"Re-order as you move: its helper didn't start ({e}) — this window's process runs the jobs")
            self._go_local()
            return
        with self._lock:
            stopped = self._stopped
            if not stopped:
                # Posted before the pipe is published, so no call made meanwhile overtakes them (pass 4 #5).
                for message in self._waiting:
                    self._post(conn, message)
                self._unseen, self._waiting = list(self._waiting), []
                self._conn = conn
        if stopped:
            self._post(conn, {"do": "stop"})
            conn.close()
            return
        while True:
            try:
                message = json.loads(conn.recv_bytes().decode("utf-8"))
            except Exception:                     # EOF, a broken or closed pipe, an aborted read (pass 4 #7)
                break
            if isinstance(message, dict):
                self._receive(message)
        try:
            conn.close()                          # a helper this side stopped reading ends too: never two hosts (pass 5 #4)
        except Exception:
            pass
        with self._lock:
            self._conn = None
            stopped = self._stopped
        if not stopped:
            print("Re-order as you move: its helper ended — this window's process runs the jobs")
            self._go_local()

    def _receive(self, message):
        if "say" in message:
            kind = (InJunban if message.get("in_junban") else Fails if message.get("fails")
                    else GivesUp if message.get("gives_up") else str)
            self._last = kind(message["say"])
            try:
                self._say(self._last)
            except Exception:
                pass
        if "working" in message:
            self._said_working = bool(message["working"])
            try:
                self._working(bool(message["working"]))
            except Exception:
                pass
        if "generate" in message and self._generate is not None:
            try:
                self._generate(str(message["generate"]))
            except Exception:
                pass
        if "web" in message:
            self._web = str(message["web"] or "")
        with self._lock:
            if isinstance(message.get("seen"), int):
                self._seen = max(self._seen, message["seen"])
                self._unseen = [sent for sent in self._unseen if sent["n"] > self._seen]
            if "busy" in message:
                self._busy = bool(message["busy"])

    def _connect(self):
        """Start the helper and take its call -> the connection. Raises when it can't start or doesn't answer within
        HELPER_START_S (or ends first)."""
        import secrets
        import subprocess
        from multiprocessing.connection import Client, Listener
        from app import library_store
        if library_store.update_staged():
            raise RuntimeError("an update is staged")
        key = secrets.token_bytes(32)
        listener = Listener(authkey=key)
        answered = threading.Event()
        try:
            flags = 0x08000000 if sys.platform == "win32" else 0            # CREATE_NO_WINDOW
            self._proc = subprocess.Popen(_helper_args(self.language, self._generate is not None),
                                          env=_helper_env(listener.address, key), creationflags=flags,
                                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
            with _HELPERS_LOCK:
                _HELPERS.append(self._proc)

            def watch():                          # a helper that ended or never calls: wake `accept` with a call
                deadline = time.monotonic() + HELPER_START_S
                while not answered.wait(0.2):
                    if self._proc.poll() is not None or time.monotonic() > deadline or self._stopped:
                        try:
                            Client(listener.address, authkey=key).close()
                        except Exception:
                            pass
                        return
            threading.Thread(target=watch, name="replan-remote-watch", daemon=True).start()
            conn = listener.accept()
            answered.set()
            try:
                hello = json.loads(conn.recv_bytes().decode("utf-8"))
            except (EOFError, OSError, ValueError):
                hello = {}
            if not isinstance(hello, dict) or "hello" not in hello:     # (the watch's own call says nothing)
                conn.close()
                raise RuntimeError("the helper ended before it answered" if self._proc.poll() is not None
                                   else "the helper didn't answer")
            return conn
        finally:
            answered.set()
            listener.close()

    def _go_local(self):
        """The window's own process hosts the jobs from now on: the calls that waited, then a catch-up."""
        with self._lock:
            if self._local is not None or self._stopped:
                return
            # The calls the helper never took (sent, or still waiting), each kind once (pass 4 #6).
            waiting = [message["do"] for message in self._unseen + self._waiting]
            self._waiting, self._unseen = [], []
            ended_busy, self._said_working = self._said_working, False
            self._local = Host(self.language, say=self._say, working=self._working, generate=self._generate)
            local = self._local
        if ended_busy:                            # the helper died mid-write: its job never says it ended — say so
            try:                                  # here; the window's own host says its own next write
                self._working(False)
            except Exception:
                pass
        local.warm()
        local.catch_up()
        for do in dict.fromkeys(waiting):        # each kind once, in the order first asked
            if do not in ("warm", "catch_up"):
                getattr(local, do)()


def _update_staged():
    """An update staged (its lock held from "Update now" until the hand-over), seen from any process. Never raises."""
    try:
        from app import library_store
        return library_store.update_staged()
    except Exception:
        return False


def _helper_args(language, generate):
    """The helper's command line, frozen (`Surasura.exe replan_helper …`, app_entry's branch) or from source."""
    extra = ["--language", language] + (["--generate"] if generate else [])
    if getattr(sys, "frozen", False):
        return [sys.executable, "replan_helper", *extra]
    return [sys.executable, os.path.abspath(__file__), *extra]


def _helper_env(address, key):
    from app.path_utils import build_subprocess_env
    env = build_subprocess_env()
    env[ADDRESS_ENV] = address
    env[KEY_ENV] = key.hex()
    env.pop(IN_PROCESS_ENV, None)
    return env


def helper_main(argv=None):
    """The helper process (`Remote`'s other side): one `Host`, driven by its window's calls; its lines, its state and
    a Generate's request go back the same way. Ends when the window says stop or its pipe breaks (the window's
    process gone), after the job in hand (at most CLOSE_WAIT_S). -> the exit code."""
    import argparse
    from multiprocessing.connection import Client
    parser = argparse.ArgumentParser(prog="replan_helper")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args(argv)
    try:
        conn = Client(os.environ[ADDRESS_ENV], authkey=bytes.fromhex(os.environ[KEY_ENV]))
    except (KeyError, ValueError, OSError, EOFError) as e:
        print(f"replan_helper: no window to answer ({e})", file=sys.stderr)
        return 2
    lock = threading.Lock()
    gone = threading.Event()
    state = {"seen": 0, "busy": None, "web": None}

    def send(message):                            # with `lock` held
        try:
            data = json.dumps(message).encode("utf-8")            # ASCII escapes: a lone surrogate still encodes
        except (TypeError, ValueError):
            return
        try:
            conn.send_bytes(data)
        except OSError:
            gone.set()

    def tell(**message):                          # the host's callbacks, from its worker
        with lock:
            send(dict(message, seen=state["seen"]))

    host = Host(args.language, say=lambda line: tell(say=line, gives_up=isinstance(line, GivesUp),
                                                     in_junban=isinstance(line, InJunban),
                                                     fails=isinstance(line, Fails)), working=lambda on: tell(working=bool(on)),
                generate=(lambda reason: tell(generate=reason)) if args.generate else None)

    def report(force=False):                      # with `lock` held
        busy, web = host.busy(), host.web
        if force or busy != state["busy"] or web != state["web"]:
            state["busy"], state["web"] = busy, web
            send({"seen": state["seen"], "busy": busy, "web": web})

    def watch():
        while not gone.wait(STATE_EVERY_S):
            with lock:
                report()
    with lock:
        send({"hello": os.getpid()})
    threading.Thread(target=watch, name="replan-helper-state", daemon=True).start()
    calls = {"poke": host.poke, "catch_up": host.catch_up, "after_generate": host.after_generate, "warm": host.warm,
             "close": host.close}
    while not gone.is_set():
        try:
            message = json.loads(conn.recv_bytes().decode("utf-8"))
        except (EOFError, OSError, ValueError):
            break
        if not isinstance(message, dict) or message.get("do") == "stop":
            break
        with lock:
            call = calls.get(message.get("do"))
            if call is not None:
                call()
            if isinstance(message.get("n"), int):
                state["seen"] = max(state["seen"], message["n"])
            report(force=True)
    gone.set()
    host.stop()
    worker = host._thread
    if worker is not None:
        worker.join(CLOSE_WAIT_S)
    try:
        conn.close()
    except OSError:
        pass
    return 0


# --- shadow mode's comparison ------------------------------------------------------------------------------------- #

PRIORITY_COLUMNS = ("Word", "Reading", "Score", "Occurrences", "Count (High)", "Count (Low)", "Count (Goal)", "Orth",
                    "Forms", "Tier")
PROGRESSIVE_COLUMNS = ("Sequence", "Source File", "Word", "Reading", "Score", "Occurrences (Global)",
                       "Occurrences (File)", "Count (High)", "Count (Low)", "Count (Goal)", "Known Count",
                       "Total Count", "Baseline %", "Current %", "New %", "Orth", "Forms", "Tier")


def _lists():
    import csv
    from app.path_utils import get_user_file
    out = {}
    for name, key in (("priority_learning_list.csv", "priority"), ("progressive_learning_list.csv", "progressive")):
        try:
            with open(os.path.join(get_user_file("results"), name), encoding="utf-8-sig", newline="") as f:
                out[key] = list(csv.DictReader(f))
        except OSError:
            out[key] = []
    return out


def _same_value(want, got):
    if isinstance(got, bool) or isinstance(got, str) or got is None:
        return (want or "") == (got or "")
    if isinstance(got, int):
        try:
            return int(want) == got
        except (TypeError, ValueError):
            return False
    if isinstance(got, float):
        try:
            return abs(float(want) - got) <= 1e-9
        except (TypeError, ValueError):
            return False
    return (want or "") == (got or "")


def _differs(result, lists):
    """The first difference between the engine's columns and a Generate's lists (05 §1's plan columns), or ""."""
    for name, rows, columns in (("priority", result.priority, PRIORITY_COLUMNS),
                                ("progressive", result.progressive, PROGRESSIVE_COLUMNS)):
        want = lists.get(name) or []
        if len(want) != len(rows):
            return f"{name}: {len(rows)} rows, the Generate wrote {len(want)}"
        for i, (w, r) in enumerate(zip(want, rows)):
            for column in columns:
                if not _same_value(w.get(column), r.get(column)):
                    return (f"{name} row {i + 1} ({w.get('Word')}): {column} {r.get(column)!r}, "
                            f"the Generate wrote {w.get(column)!r}")
    return ""


def _log_shadow(line):
    """One line to `replan_shadow.log` in the local data folder's logs (beside the command line's). Never raises."""
    try:
        from app.path_utils import get_local_data_path
        folder = os.path.join(get_local_data_path(), "logs")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, SHADOW_LOG), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " · " + line + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    from app import replan_preview as _module      # the helper runs in the module every import shares
    sys.exit(_module.helper_main())
