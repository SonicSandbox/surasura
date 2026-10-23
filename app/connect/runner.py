"""Connect's loop (P2.4 Part A; ORDER P2.4; P1.5 02-data-model §2, §2a, §4; 06-edges E1–E32): `surasura-cli connect`
without `--consume-only`. For every job the inbox queued (P2.1) and every level job (P2.2), in top-20 order, the next
day's words first:

    sync → known-sync → re-plan (generate first only when the plan can't serve) → pick → fit check → mine →
    backfill → junban → [generate after mining → junban] → sync

- **Once a run, never per episode** (02 §4): the session's sync (`anki_session.begin`, P2.3: before Connect reads
  what you studied), one known-sync, then the plan's verdict (P3.3, K78: `replan.current`). A move or a placement of
  counted items is **re-planned** — mined and ordered from the engine's re-plan, no Generate in the loop; known words
  moved, new files placed (P4.1 C5) or the level raised alone → mined first (from the provisional re-plan, or the
  list as it is), then **one Generate after mining** and a follow-up re-order from its plan, the level look on the
  new run (F11, `_after_mining`); a changed file, a lowered level, no plan, another engine → one Generate first, as
  before (`generate`'s own "nothing changed"; a failed one → *Needs you* with its log, E29, and mining waits for a
  current list). Prepared per language, the first time a language has work.
- **One Anki Miner batch at a time** (E19), each job's words in one batch. **The carded set is read again for every
  pick** (P2.2 adversary #3: a word a higher job just carded is skipped — `pick.carded` asks Anki itself), together
  with every word Connect has ever made (the store's `made_words`, G1.3-4: a card you deleted is never made again).
  **The profile is pinned from pick to mine** (P1.3-AM37 #5): Anki Miner's active profile looked at again at mine
  time; another one → picked again.
- **Every step saved before and after** (02 §2; the ledger's `set_state`): a killed Connect resumes from the last
  saved step. A batch left `running` is in doubt: its notes are found by the job's tag first (E25, E14), recorded,
  and only the words still in doubt are tried again — once; a second failure → *Needs you*. Nothing is mined twice.
- **Waiting** (02 §2, one reason at a time): Anki closed (E1), you reviewing (E2, asked before each write), another
  profile (E3) — the session's `waiting` —, on battery (E32), Anki Miner open (E8), another program writing Anki: each
  may end while Connect runs, so it **stays running and looks again every 2 minutes** at below-normal priority (02
  §2a). No video (E15: a cloud placeholder is never opened), not timed (E16, named once in *Needs you*), Chinese (E24)
  and a setup Anki Miner lacks wait for the next start. **It exits when no job is left**, or when every job left waits
  for the next start. **It never opens Anki** (Q4-16: only the window's *Open Anki for me*).
- **An item that left the top 20** before mining → dropped; once mining started → it finishes (E18). A job of another
  store (the library set up again: a new `store_id`) is dropped before mining (P2.1 adversary #12). Never one carrying
  an ask, nor a level job beyond the line on 3.0 (P4.1 C3, C4: `inbox.keeps`).
- **Asks first** (P4.1 C3): a job carrying an ask (*Mine now*, *Mine this*, *Mine it too*) goes before the top 20,
  the newest ask first; only a job an ask made (kind `asked`) makes again a word whose card you deleted (N15, IK S1);
  one for a book or a text ends skipped with K67's line (IK S3).
- **A missing tool** (🧭 Q4-2, RD-S10): Anki Miner absent → the job `skipped`, named; Backfill or Junban absent → that
  step skipped and named on the job (`skipped`), the loop goes on.
- **An update staged** (E26): the run stops at the next step boundary (the command line refuses to start one) —
  between two Anki Miner batches of a job too, and within UPDATE_LOOK_S of its 2-minute pause (P3.1 row 3.1.8, K99:
  the update waits for Connect, never kills it; the ledger resumes the job where it stopped).
- **The store:** one short write a batch (`library.record_batch`: the receipt + the made words, role `connect`); a
  write the window holds past the store's 5 s waits for the next look.

Every Anki call runs through `Steps` (the command line's own verbs, in this process); a test hands its own. Wrapped by
`app/batch_gc.py` (CLAUDE.md §6): nothing here keeps a reference cycle per job.
"""
import datetime
import json
import logging
import os
import time
from types import SimpleNamespace

from app.connect import fit_check, inbox
from app.connect.ledger import ASKED, BEFORE_MINING, IN_FLIGHT, LEVEL, PREPARE_KINDS, STOPPED_REASON, Ledger

log = logging.getLogger("surasura-cli")

LOOK_EVERY_S = 120              # 02 §2a: while every job waits on something outside Connect
UPDATE_LOOK_S = 5               # K99: inside that pause, an update staged is looked for this often
WAIT_S = 10.0                   # a verb's --wait inside the run (another Surasura writer, a Generate)
ALL_GONE_MIN = 10               # the deleted-card check: this many notes or more, all gone at once -> nothing marked

# The plain lines a waiting job shows (the status line's, never Needs you)
ON_BATTERY = "On battery: cards are made once this computer is plugged in."
ANKI_MINER_OPEN = "Anki Miner is open: close it to make cards."
WRITER_BUSY = "Another program is writing to Anki."
SHELF_NO_JUNBAN = "The shelf is off: it needs Junban (順), which isn't installed. Connect waits at the cap."
REVIEWING = "Waiting while you review in Anki."
ANKI_CLOSED = "Waiting for Anki: it isn't open."
# A call to Anki that failed while Anki answers (one slow or refused request: laptop round 5 review A1) — that
# episode's own wait, amber as a wait on Anki, but never one that holds every episode
ANKI_SLOW = "Waiting for Anki: it didn't answer in time."
NO_VIDEO = "No video: its video isn't on this computer (or isn't downloaded yet)."
CHINESE = "Chinese cards come later."
# Laptop round 8 #47 (LF4-5 ⭐ A): a job you stopped waits for your next ask; the cards it made are kept
STOPPED_BY_YOU = STOPPED_REASON
# Laptop round 8 #49 (LF4-1 ⭐ A, PROVISIONAL): a level raise's job for an episode you've watched, or whose video is gone
WATCHED = "you've watched it: its new words go to the episodes ahead of you"
LEVEL_NO_VIDEO = "its video isn't on this computer: its new words go to the other episodes"
# K67 (IK S3): Anki Miner's API mines video only — an asked job for a book or a text ends skipped with this line
TEXT_ONLY = ("Anki Miner makes cards from videos only: open Anki Miner's own window to mine this one by hand "
             "(Mine text).")
NO_LIST = "Waiting for a current list: Generate didn't finish."
LIBRARY_BUSY = "Surasura's library is busy: tried again shortly."
STOPPED_FOR_UPDATE = "Surasura is installing an update."
ANKI_OFF = "Anki is switched off for this run (SURASURA_NO_ANKI_SYNC)."
NO_WORDS = "no words to make cards from"
SWITCHED_OFF = "Connect was switched off."
MINER_ABSENT = "Anki Miner isn't installed"
# ASK-SONIC P2.4-8 ⭐ (a): with your list in another language, Connect waits rather than replace it with its own
# Generate (False: it goes ahead, as before)
WAIT_FOR_OTHER_LIST = True
OTHER_LIST = "Waiting: your list is in {}. Cards are made once a Japanese list is current again."
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}

# `Steps.order`'s answer when the plan can't serve the re-order now and the Generate after mining will (P3.3, F11)
DEFERRED = "deferred"

# Anki Miner's settled outcomes: a word with one of these is never sent again for the job
UNSETTLED = (None, "uncertain", "not_attempted")
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".webm", ".avi", ".m4v", ".mov", ".ts")
TS_MIN = 1 << 20                # a `.ts` under this size is TypeScript, not a video (K6, S9: by the listing's stat)


def mac_copy(name):
    """Is this a Mac's `._` copy (AppleDouble, on a NAS or exFAT drive: metadata, never a video or a text)? The one dot
    rule — Connect's video index and the library's look (`sources._listing`) both ask it; any other leading dot is a
    name (`.hack SIGN - 01.mkv`, a `.hack` folder). The folders a Mac makes are `library_store.SKIP_DIRS`'."""
    return name.startswith("._")


def video_name(name):
    """Can a file of this name be a video? One of VIDEO_EXTENSIONS, and never a Mac's `._` copy (`mac_copy`). The
    name's half of `video_file`, for a listing before its stat."""
    return not mac_copy(name) and name.lower().endswith(VIDEO_EXTENSIONS)


def video_file(name, size):
    """Is a listed file a video? `video_name`, and never a `.ts` under TS_MIN (TypeScript). `size`: the listing's stat,
    nothing read. Connect's video index (`videos._list`) reads it; the library's look and Needs you's video listing are
    to call it too (asked of their owners), so that what counts as a video file is one rule."""
    return video_name(name) and not (name.lower().endswith(".ts") and size < TS_MIN)
_PLACEHOLDER = 0x1000 | 0x40000 | 0x400000      # OFFLINE · RECALL_ON_OPEN · RECALL_ON_DATA_ACCESS (a cloud file)


class Wait(Exception):
    """A job waits: `reason` (plain words), `look` (True: it may end while Connect runs — look again in 2 minutes),
    `resume` (the step it goes on from; None: from the start)."""

    def __init__(self, reason, look=True, resume=None):
        super().__init__(reason)
        self.reason, self.look, self.resume = reason, look, resume


class Needs(Exception):
    """Something only you can fix: named once in *Needs you* (`kind`, `say`); the job waits for the next start."""

    def __init__(self, kind, say):
        super().__init__(say)
        self.kind, self.say = kind, say


class Skip(Exception):
    """A step's tool isn't installed (`why`): the step is skipped and named."""

    def __init__(self, why):
        super().__init__(why)
        self.why = why


class Repick(Exception):
    """What the words were picked for changed (Anki Miner's profile, the pairing): pick again."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(loaded, languages, steps=None, ledger=None, sleep=None, cancel=None, looks=None):
    """The loop, until no job is left (or every job left waits for the next start) -> a summary per language:
    {"done", "dropped", "skipped", "failed": [item ids], "waiting": {item id: reason}, "needs": [say, …]}, plus
    "looks" and, when it stopped early, "stopped". `looks`: at most this many looks (tests); `cancel`: an Event;
    `sleep`: a test's own pause, called once with the whole of it (default: `time.sleep` in UPDATE_LOOK_S steps,
    ended early by an update staged)."""
    steps = steps or Steps(loaded, live=True)
    steps.lower_priority()
    _release_check(loaded)
    own = ledger is None
    ledger = ledger or Ledger()
    summary = {"languages": {lang: _empty() for lang in languages}, "looks": 0}
    for lang in languages:                  # F9: a crash's *updating your list* mark is cleared by the next run
        _updating(ledger, lang, False)
    prepared = set()            # the languages whose sync, known-sync and Generate ran this run (02 §4: once)
    begun = set()               # the languages this run has worked on (the status line's *i of n* counts from then)
    undos_looked = set()        # the languages whose half-done undos this run has finished (once a run)
    parked = {}                 # jobs waiting for the next start: never tried again this run (adversary P2.4-A #11)
                                # — {job id: its ask when parked}; a newer ask tries it again (#42, review r42 #3)
    try:
        while True:
            summary["looks"] += 1
            _kicked(steps)                  # a kick before this look is answered by it: no extra look after (S19)
            outside = work = battery = False
            for lang in languages:
                stop = _stop(steps)
                if stop:
                    summary["stopped"] = stop
                    return summary
                if _consume(steps, ledger, lang):
                    outside = work = True       # the inbox couldn't be read: looked at again, never lost
                if lang not in undos_looked:    # an undo a kill left half-way: finished whatever else runs (#5)
                    undos_looked.add(lang)
                    _finish_undos(steps, ledger, lang)
                if not _open_jobs(ledger, lang, parked):
                    continue
                work = True
                if lang not in begun:
                    ledger.mark_run(lang)
                    begun.add(lang)
                out = summary["languages"][lang]
                earlier, out["waiting"] = out["waiting"], {}    # this pass's waits alone, then added to the run's
                outside |= _language(steps, ledger, lang, prepared, parked, out)
                battery |= ON_BATTERY in out["waiting"].values()
                out["waiting"] = {**earlier, **out["waiting"]}
                _said(steps, lang, out)
                stop = _stop(steps)                 # staged or switched off while its jobs ran: this step boundary
                if stop:
                    summary["stopped"] = stop
                    return summary
            if summary.get("stopped") or not work or not outside:
                break
            if looks is not None and summary["looks"] >= looks:
                break
            if not _pause(LOOK_EVERY_S, sleep, cancel,
                          lambda: steps.update_staged() or _plugged_in(steps, battery) or _kicked(steps)):
                summary["stopped"] = "cancelled"
                break
        return summary
    finally:
        if own:
            ledger.close()
        try:
            steps.settle()                  # a pending sync is sent before Connect exits (P2.3)
        except Exception:
            log.exception("Connect's pending sync wasn't sent")


def _release_check(loaded):
    """P3.2-AMN: Anki Miner's once-a-day release check (`am_release`): its attempt saved here, then GitHub asked on a
    daemon thread: mining never waits on it (Connect's exit gives it what is left of 5 s + 1 s, `connect_verbs._loop`).
    Preview off, not due → no thread. -> the thread or None."""
    try:
        from app.connect import am_release
        return am_release.start(loaded)
    except Exception:
        log.exception("Anki Miner's release check wasn't started")
        return None


def _said(steps, lang, out):
    """What the shelf did this run, in the run's summary (intent keeper P2.4-B #1, S16: an automation is seen)."""
    said = (getattr(steps, "said", None) or {}).get(lang)
    if said:
        out["shelf"] = list(said)
    aside = (getattr(steps, "stood_aside", None) or {}).get(lang)
    if aside:                               # P4.1 C8: the order step stood aside for a deck you put back
        out["stood_aside"] = aside


def _stop(steps):
    """Why the run stops at this step boundary, or None: an update staged (E26), Connect switched off (S16, D29: read
    again at every look and before each job, adversary P2.4-A #3)."""
    if steps.update_staged():
        return STOPPED_FOR_UPDATE
    if not steps.enabled():
        return SWITCHED_OFF
    return None


def _consume(steps, ledger, lang):
    """The inbox and the level raise's look, and the jobs skipped for want of Anki Miner queued again once it's there
    (intent keeper P2.4-A #11) -> True when it failed (a busy or read-only store, a ledger error: looked at again;
    adversary P2.4-A #5)."""
    try:
        steps.consume(lang, ledger)
        if ledger.skipped_for(lang, MINER_ABSENT) and steps.miner_found():
            line = steps.mine_line(lang)
            with ledger.transaction():
                ledger.reopen_skipped(lang, line, MINER_ABSENT)
    except Exception:
        log.exception("Connect couldn't read its inbox (%s); it looks again", lang)
        return True
    return False


def _open_jobs(ledger, lang, parked, tried=()):
    """The open jobs this pass may try: never one `tried`, nor one parked for the next start — unless you asked for it
    since it was parked (a *Mine now* on it: your press tries it again in this run, laptop round 7 #42)."""
    return [j for j in ledger.open_jobs(lang)
            if not (j["id"] in parked and parked[j["id"]] == j.get("asked_at")) and j["id"] not in tried
            and not ledger.held_by_stop(j)]     # laptop round 8 #47: one you stopped waits for your next ask


def _empty():
    return {"done": [], "dropped": [], "skipped": [], "failed": [], "waiting": {}, "needs": []}


def _pause(seconds, sleep, cancel, staged):
    """The pause between looks -> False when cancelled. Looks for an update staged every UPDATE_LOOK_S and ends at
    once when one is (the loop's next `_stop` names it): the update waits seconds for a sleeping Connect, never 2
    minutes (K99). A test's own `sleep` (no `cancel`) is called once, with the whole pause."""
    if cancel is None and sleep is not None:
        sleep(seconds)
        return True
    wait = cancel.wait if cancel is not None else time.sleep
    waited = 0
    while waited < seconds:
        step = min(UPDATE_LOOK_S, seconds - waited)
        if wait(step):
            return False                # the Event set (time.sleep answers None)
        waited += step
        if staged():
            break
    return True


def _plugged_in(steps, battery):
    """Episodes wait on battery and the plug is back: the pause ends now, so the next look mines them first, in order,
    within seconds (laptop round 5 #34; `_pause` asks every UPDATE_LOOK_S), never after the 2-minute look. `battery`:
    the pass that just ended left one waiting on battery (its own summary: no ledger read in the pause, S19,
    IK-r2-8). A power look that fails is no wake (logged): the run goes on (R2-10)."""
    on_battery = getattr(steps, "on_battery", None)
    if not battery or on_battery is None:
        return False
    try:
        return not on_battery()
    except Exception:
        log.warning("Connect couldn't look at the power; the pause goes on", exc_info=True)
        return False


def _kicked(steps):
    """Was Connect kicked during the pause (a *Mine now*, a placement, a setting that lets waiting episodes go:
    `kick.kick` stamps its wake mark when Connect already runs)? The pause ends, so the next look reads the ask within
    seconds, never at the 2-minute look (laptop round 7 #42). A look that fails is no wake (logged)."""
    kicked = getattr(steps, "kicked", None)
    if kicked is None:
        return False
    try:
        return kicked()
    except Exception:
        log.warning("Connect couldn't look at its wake mark; the pause goes on", exc_info=True)
        return False


def _ordered(jobs, line):
    """The open jobs: those carrying an ask first, the newest ask first (*Mine now*, *Mine this*, *Mine it too*: P4.1
    C3); then the top 20's order (the next day's words first); then the rest oldest first (a level raise's beyond the
    line — the rest of Current, then Goal — in the order it queued them, C4)."""
    from app.connect.ledger import stamp_key
    place = {item_id: n for n, item_id in enumerate(line)}
    asked = sorted((j for j in jobs if j.get("asked_at")), key=lambda j: (stamp_key(j["asked_at"]), -j["id"]),
                   reverse=True)
    rest = sorted((j for j in jobs if not j.get("asked_at")), key=lambda j: (place.get(j["item_id"], len(place)),
                                                                              j["id"]))
    return asked + rest


def _waiting_all(ledger, lang, parked, out, reason, look, tried=()):
    """Every open job waits with `reason` — but one waiting for its video keeps that, its own wait (review IK #5), and
    one `tried` this pass keeps the wait it was given (an asked job's ANKI_SLOW on battery: R2-4, IK-r2-7)."""
    for job in _open_jobs(ledger, lang, parked, tried):
        if job["state"] == "waiting" and job.get("reason") == NO_VIDEO:
            out["waiting"][job["item_id"]] = NO_VIDEO
            continue
        _wait(ledger, job, Wait(reason, look, _resume_of(job)), out, parked)
    return look


def _language(steps, ledger, lang, prepared, parked, out):
    """Every open job of one language, once -> True when one waits on something outside Connect (look again). The top
    20 and the inbox are read again before each job (adversary P2.4-A #2): an episode moved out mid-burst is dropped,
    a new first one goes next."""
    if lang != "ja":            # E24: Japanese first, until Anki Miner and Connect say Chinese works
        return _waiting_all(ledger, lang, parked, out, CHINESE, False)
    wait = store_now = None
    only_asked = False          # on battery with a *Mine now* waiting: this pass mines the asked ones alone (M-3)
    try:
        wait = _blocked(steps, lang, None)
        if wait is not None and wait.reason == ON_BATTERY and any(j.get("asked_at") for j in
                                                                  _open_jobs(ledger, lang, parked)):
            only_asked = True
            wait = _blocked(steps, lang, None, asked=True)
        if wait is None:
            with _held():                   # two store reads, one open
                steps.mine_line(lang)       # the store answers first: never an empty top 20 for a busy one
                store_now = steps.store_id(lang)
            if lang not in prepared:
                steps.prepare(lang, ledger)
                prepared.add(lang)
                _fixed(ledger, lang, kinds=PREPARE_KINDS)     # the sync, known-sync and Generate went through
    except Wait as w:
        wait = Wait(w.reason, w.look)       # its fields only: never the caught exception's frame (#17)
    except Needs as n:
        if ledger.need(lang, n.kind, n.say):
            out["needs"].append(n.say)
        wait = Wait(n.say, look=False)
    if wait is not None:
        return _waiting_all(ledger, lang, parked, out, wait.reason, wait.look)
    outside = False
    tried = set()
    look = False                # the inbox and the level looked at again before the next job (after a job, or F11)
    while True:
        if look and _consume(steps, ledger, lang):
            outside = True
        jobs = _open_jobs(ledger, lang, parked, tried)
        if not jobs:
            if _after_mining(steps, ledger, lang, out, on_battery=only_asked):
                look = True     # the level look on the new run: the jobs it queued run in this run (no second prepare)
                continue
            break
        failed = None
        try:
            line = steps.mine_line(lang)
        except Wait as w:
            failed = (w.reason, w.look)
        except Needs as n:
            if ledger.need(lang, n.kind, n.say):
                out["needs"].append(n.say)
            failed = (n.say, False)
        if failed is not None:
            return _waiting_all(ledger, lang, parked, out, failed[0], failed[1], tried) or outside
        job = _ordered(jobs, line)[0]
        if only_asked and not job.get("asked_at"):     # the asked ones are mined: the rest still wait for the plug
            return _waiting_all(ledger, lang, parked, out, ON_BATTERY, True, tried) or outside
        tried.add(job["id"])
        look = True
        try:
            _job(steps, ledger, lang, job, store_now, set(line), out)
            ended = ledger.job_by_id(job["id"]) or {}
            if ended.get("state") in ENDED:     # its troubles went, but a step it ended without (Backfill…) stands
                _fixed(ledger, lang, item_id=job["item_id"], keep=_skipped_says(ended))
        except Wait as w:
            _wait(ledger, job, w, out, parked)
            outside |= w.look
            if holds_every(w.reason):
                # on battery, or a wait on Anki: every episode keeps its place and the next look starts from the top
                # (laptop round 5 #24) — never a later one (or the next show) before the one that waited
                return _waiting_all(ledger, lang, parked, out, w.reason, w.look, tried) or outside
        except Needs as n:
            if ledger.need(lang, n.kind, n.say, item_id=job["item_id"], job_id=job["id"]):
                out["needs"].append(n.say)
            _wait(ledger, job, Wait(n.say, look=False, resume=_resume_of(ledger.job_by_id(job["id"]))), out, parked)
        except Exception as e:              # R15: a fault of one job never ends the run nor hides it
            log.exception("Connect's job %s stopped on an error", job["id"])
            say = f"Connect stopped on an error while making an episode's cards ({type(e).__name__}): {e}"
            if ledger.need(lang, "error", say, item_id=job["item_id"], job_id=job["id"]):
                out["needs"].append(say)
            _wait(ledger, job, Wait(say, look=False, resume=_resume_of(ledger.job_by_id(job["id"]))), out, parked)
        if _stop(steps):
            break
    return outside


def _after_mining(steps, ledger, lang, out, on_battery=False):
    """F11 (P3.3): this run mined from a plan that waits for a Generate (known words moved, or the level raised
    alone) — once the language's jobs have run this pass (done, or waiting): the Generate, the plan read again, one
    follow-up re-order from it (the re-sort owed until it lands) -> True when the Generate went through (the loop's
    next look is the level look on the new run). Never while stopped (an update staged, switched off — looked at
    again after the Generate, before the follow-up writes Anki); once a run (the mark is the steps'). A Generate that
    waits or fails leaves the re-sort owed; mining is already done. `on_battery`: the pass mined the asked jobs alone
    (M-3) — a *Mine now* press is the yes for its episode's cards, never for the Generate (D-r2-1 a, Sonic's lean):
    not started, it stays owed — the steps' mark, for a later pass of this run with jobs to run once plugged in; the
    next run's plan (`replan.current`) marks it again until a Generate lands — and its follow-up re-order with it, as
    that re-order waits for the plug."""
    after = getattr(steps, "generate_after", None)
    if after is None or on_battery or _stop(steps):
        return False
    try:
        ran = after(lang, ledger)
    except Wait as w:
        log.info("Connect: the Generate after mining waits (%s): %s", lang, w.reason)
        ran = None
    except Needs as n:
        if ledger.need(lang, n.kind, n.say):
            out["needs"].append(n.say)
        ran = None
    except Exception:                       # mining is done: a fault here never ends the run (R15)
        log.exception("Connect's Generate after mining stopped on an error (%s)", lang)
        ran = None
    if ran is False:
        return False
    try:
        with ledger.transaction():
            ledger.owe_resort(lang)         # the follow-up re-order: owed until it lands (the next job's step pays it)
    except Exception:                       # R15: a ledger fault here never ends the run (final adversary #3)
        log.exception("Connect couldn't mark the re-sort owed after its Generate (%s)", lang)
    if ran is None:
        return False
    if _stop(steps):                        # switched off or an update staged during the Generate: no Anki write
        return False                        # (S16, D29, E26) — the re-sort stays owed
    _follow_up(steps, lang, ledger)
    return True


def _follow_up(steps, lang, ledger):
    """F11's one re-order from the Generate's new plan (a move made meanwhile is served at its time). Anki closed, a
    review, a skip or a failure: the re-sort stays owed."""
    try:
        if _blocked(steps, lang, None) is not None:
            return
        deferred = steps.order(lang, None) == DEFERRED
    except (Wait, Needs, Skip) as e:
        log.info("Connect: the follow-up re-order waits (%s): %s", lang, e)
        return
    except Exception:
        log.exception("Connect's follow-up re-order stopped on an error; the re-sort stays owed")
        return
    if not deferred:
        try:
            with ledger.transaction():
                ledger.resort_paid(lang)
        except Exception:                   # R15: logged, the run goes on; the re-sort stays owed (#3)
            log.exception("Connect couldn't mark the re-sort paid (%s); it stays owed", lang)


# A job that ended one of these ways took its item's needs with it (03 §4: fixed by itself); `failed` just named one
ENDED = ("done", "dropped", "skipped", "undone")


def _fixed(ledger, lang, kinds=None, item_id=None, keep=()):
    """Needs whose cause went away (03 §4), each named once in the log -> how many."""
    rows = ledger.fix(lang, kinds=kinds, item_id=item_id, keep=keep)
    for row in rows:
        log.info("Connect: fixed by itself (%s, %s): %s", lang, row["kind"], row["say"])
    return len(rows)


def _skipped_says(job):
    """The words of the steps a job ended without (its `skipped` column): their needs stay open (03 §4)."""
    try:
        return set((json.loads(job.get("skipped") or "{}") or {}).values())
    except (ValueError, AttributeError):
        return set()


def _finish_undos(steps, ledger, lang):
    """`steps.finish_undos` once a run per language, before anything else; Anki not answering leaves them for the
    next run (logged, never a reason not to go on)."""
    finish = getattr(steps, "finish_undos", None)
    if finish is None or not ledger.pending_undos(lang):
        return
    try:
        finish(lang, ledger)
    except Exception:
        log.exception("Connect couldn't finish an undo left half-way; it tries again next run")


def _blocked(steps, lang, resume, asked=False):
    """`steps.blocked` as a Wait resuming at `resume` (it answers a reason, or a Wait of its own), or None. `asked`:
    for a job carrying an ask, on battery is no reason (Sonic 2026-10-22, M-3 A: a *Mine now* press is the yes for
    that one episode) — Anki's own state still is (`steps.session_blocked`)."""
    why = steps.blocked(lang)
    if asked and why == ON_BATTERY:
        session = getattr(steps, "session_blocked", None)
        why = session(lang) if session is not None else None
    if why is None:
        return None
    if isinstance(why, Wait):
        return Wait(why.reason, why.look, resume)
    return Wait(why, resume=resume)


def _resume_of(job):
    if job["state"] in IN_FLIGHT:
        return job["state"]
    return job.get("resume") if job["state"] == "waiting" else None


def _started(ledger, jid):
    """Has a batch of the job reached Anki Miner (anything but a call it refused)? Until then the job can still be
    dropped, picked again and checked again (adversary P2.4-A #1)."""
    return any(b["state"] != "refused" for b in ledger.batches(jid))


def _wait(ledger, job, wait, out, parked=None):
    """The job waits with one reason. Until a batch has reached Anki Miner it keeps no step to resume at: it picks
    again from the list as it is then (so it can be dropped, its pairing is checked again, and it never holds the
    level raise's look, `ledger.in_flight`; adversary P2.4-A #1); once one has, it resumes at mining at the earliest
    (it finishes, E18). A wait for the next start parks it for this run."""
    resume = wait.resume
    if resume in BEFORE_MINING or resume == "mining":
        resume = "mining" if _started(ledger, job["id"]) else None
    now = ledger.job_by_id(job["id"]) or {}
    if (now.get("state"), now.get("reason"), now.get("resume")) != ("waiting", wait.reason, resume):
        ledger.set_state(job["id"], "waiting", reason=wait.reason, resume=resume)   # the same wait: nothing written (S19)
    out["waiting"][job["item_id"]] = wait.reason
    if parked is not None and not wait.look:
        parked[job["id"]] = now.get("asked_at")


def _held():
    """One store handle for store reads back to back (L3.3's `library_store.held()`, §6.12): each `open_store` inside
    it returns the span's handle. Only around store reads: never around Anki or AnkiConnect, Anki Miner, a lock's
    wait, the tokenizer or tsubasa (seconds to minutes: a store marked damaged meanwhile couldn't be set aside by
    Repair while the handle stays open; adversary L3.3 wiring #1-#3)."""
    from app import library_store
    return library_store.held()


def _updating(ledger, lang, on):
    """F9 (P4.1 row 4.1.7): Connect's own Generate marked (`on`) or cleared in the ledger's meta, each in its own short
    transaction; nothing written when the mark already reads so (S19). A ledger fault is logged, never a reason not to
    Generate (R15). `ledger` None: nothing to mark."""
    if ledger is None:
        return
    try:
        if not on and ledger.updating(lang) is None:
            return
        with ledger.transaction():
            if on:
                ledger.mark_updating(lang)
            else:
                ledger.updated(lang)
    except Exception:
        log.exception("Connect couldn't %s its *updating your list* mark (%s)", "set" if on else "clear", lang)


def _job(steps, ledger, lang, job, store_now, line, out):
    """One job from where it stands to `done` (or a finished state). Raises Wait / Needs."""
    jid, item_id = job["id"], job["item_id"]
    step = _resume_of(job)
    droppable = step in BEFORE_MINING and not _started(ledger, jid)
    foreign = bool(job.get("store_id") and store_now and job["store_id"] != store_now)
    if foreign and droppable:
        ledger.set_state(jid, "dropped", reason="the library was set up again")
        out["dropped"].append(item_id)
        return
    if not job.get("store_id") and droppable:
        # queued before SCHEMA 3 (the 2.x preview's inbox): which library it came from isn't known, so it is never
        # mined into this one (P2.1 adversary #12) — named as a gap, as a read of the log Connect can't trust is
        ledger.set_state(jid, "dropped", reason="queued before Connect kept its library's identity")
        with ledger.transaction():
            ledger.add_gap(lang, [item_id])
        out["dropped"].append(item_id)
        return
    if droppable and item_id not in line and not inbox.keeps(job):     # an ask, a level raise beyond the line (P4.1)
        ledger.set_state(jid, "dropped", reason="left the top 20")
        out["dropped"].append(item_id)
        return
    if droppable and job.get("kind") == LEVEL and getattr(steps, "watched", lambda _l, _j: False)(lang, job):
        # laptop round 8 #49 (LF4-1 ⭐ A, PROVISIONAL): a level raise never mines an episode you've watched — one marked
        # watched since its job was queued ends here, its words left for the episodes that hold them (`level.wants`)
        ledger.set_state(jid, "dropped", reason=WATCHED)
        out["dropped"].append(item_id)
        return
    if droppable and job.get("kind") == ASKED and getattr(steps, "text_only", lambda _l, _j: False)(lang, job):
        # K67 (IK S3, defensive: the window sends *Mine this* on a book to Anki Miner's own window, no ask): ended,
        # the ask used up with it
        ledger.set_state(jid, "skipped", reason=TEXT_ONLY, skipped={"mining": TEXT_ONLY})
        out["skipped"].append(item_id)
        return
    record = not foreign
    _stop_here(ledger, job, step)
    if droppable:
        # at the cap, the shelf tried: one count, no pick and no write (S19, review B adv #2); never an ask (#42)
        full = _full(steps, lang, asked=bool(job.get("asked_at")))
        if full is not None:
            raise full
    try:
        for _ in range(3):          # a profile or pairing that changed since the pick: picked again (at most twice)
            try:
                if step in (None, "picking"):
                    _stop_here(ledger, job, step)
                    got = _pick(steps, ledger, lang, job, record)
                    if got is None:
                        out["done"].append(item_id)
                        return
                    step = "filling" if got == "filling" else "fit-check"
                if step == "fit-check":
                    _stop_here(ledger, job, step)
                    _fit(steps, ledger, lang, job)
                    step = "mining"
                if step == "mining":
                    _stop_here(ledger, job, step)
                    _mine(steps, ledger, lang, job, record=record)
                    step = "filling"
                break
            except Repick:
                step = "picking"
        else:
            raise Needs("repick", "Anki Miner's profile or the episode's pairing keeps changing; nothing was mined.")
    except _Finished as f:
        out["skipped" if f.state == "skipped" else "failed"].append(item_id)
        return
    if step == "filling":
        _fill(steps, ledger, lang, job)
        step = "ordering"
    if step == "ordering":
        _order(steps, ledger, lang, job)
    ledger.set_state(jid, "done", reason=None)
    ledger.forget_stop(jid)                 # a *Stop* pressed while its cards were filled and ordered: nothing left
    out["done"].append(item_id)


def _stop_here(ledger, job, step):
    """Laptop round 8 #47: *Stop* pressed on this job -> it stops here, before `step` (nothing of the step done): the
    press used up, the job waits for your next ask (`Ledger.held_by_stop`), resuming at `step`."""
    if step in ("filling", "ordering") or not ledger.stop_asked(job["id"]):
        return                              # its cards are made: it finishes (seconds), the press forgotten at its end
    now = ledger.job_by_id(job["id"]) or {}
    ledger.mark_stopped(job["id"], now.get("asked_at"))
    log.info("Connect: job %s stopped by you before %s", job["id"], step or "its pick")
    raise Wait(STOPPED_BY_YOU, look=False, resume=step)


def _pick(steps, ledger, lang, job, record=True):
    """The pick step -> what it picked; None when it found no word (the job done with nothing to make); "filling"
    when it found none after an earlier batch made some (those recorded, then filled and ordered: adversary #6)."""
    jid = job["id"]
    ledger.set_state(jid, "picking")
    video = steps.video(lang, job)
    if video is None and job.get("kind") == LEVEL:
        # laptop round 8 #49 (LF4-1 ⭐ A): a level raise never waits for, nor asks for, a video — an episode already
        # mined whose video is gone is passed over quietly (never *Needs you*), its words left for the other jobs
        ledger.set_state(jid, "skipped", reason=LEVEL_NO_VIDEO, skipped={"mining": LEVEL_NO_VIDEO})
        raise _Finished("skipped")
    if video is None:
        raise Wait(NO_VIDEO, look=False)
    pairing = steps.pairing(lang, job)
    got = steps.pick(lang, job, video)
    declined = ledger.declined(lang, job["item_id"])     # Anki Miner turned them down once: never sent again (#19)
    if got.get("anki_miner"):
        # laptop round 8 #52 (LF4-4 ⭐ A): a word this Anki Miner has no definition for, in any episode, is no card here
        # either (a name: sent once a version, never again with every episode)
        declined |= ledger.uncardable(lang, got["anki_miner"])
    words = [w for w in got.get("words") or [] if (w.get("word"), w.get("reading")) not in declined]
    picked = {"words": words, "file": got.get("file"), "subtitle": got.get("subtitle"),
              "video": video, "pairing": fit_check.version(pairing), "profile": got.get("profile"),
              "anki_miner": got.get("anki_miner")}
    before = ledger.picked(jid) or {}
    if before.get("forced") and before.get("pairing") == picked["pairing"]:
        picked["forced"] = True     # *Mine anyway* (row 4.1.9) holds for the pairing you said it for; a new one clears it
    if got.get("absent"):
        _record_made(steps, ledger, lang, job, record)
        ledger.set_state(jid, "skipped", reason=MINER_ABSENT, picked=picked, skipped={"mining": MINER_ABSENT})
        raise _Finished("skipped")
    if not picked["words"]:
        if _made(ledger, jid):
            ledger.set_state(jid, "mining", picked=picked)
            _record_made(steps, ledger, lang, job, record)
            ledger.set_state(jid, "filling")
            return "filling"
        # an episode with nothing to make: its receipt (Mado's W2.2 ask: a finished zero-card job writes mined_at)
        steps.record(lang, job, {}, _now() if job.get("kind") != "level" else None, None)
        ledger.set_state(jid, "done", reason=NO_WORDS, picked=picked, skipped={"mining": NO_WORDS})
        return None
    ledger.set_state(jid, "fit-check", picked=picked)
    return picked


class _Finished(Exception):
    """The job ended here in a finished state other than done (its state already saved)."""

    def __init__(self, state):
        super().__init__(state)
        self.state = state


def _fit(steps, ledger, lang, job):
    jid = job["id"]
    picked = ledger.picked(jid) or {}
    ledger.set_state(jid, "fit-check")
    pairing = steps.pairing(lang, job)
    if fit_check.version(pairing) != picked.get("pairing"):
        raise Repick()                      # E17: hato re-timed it, or a new subtitle
    if picked.get("forced"):
        # *Mine anyway* (G1.3-6, E16; P4.1 row 4.1.9): you chose to mine it not timed — tsubasa isn't asked, and the
        # lines are cut where the subtitle puts them (no shift)
        log.info("Connect: job %s mined anyway: not timed", jid)
        picked["offset"] = 0.0
        ledger.set_state(jid, "mining", picked=picked)
        return
    verdict, who, why, offset = steps.fit(lang, job, pairing, picked.get("video"), picked.get("file"))
    if verdict == fit_check.TIMED and who == "you":
        log.info("Connect: job %s mined at its subtitle's own times: you trust your subtitles' timing", jid)
    if verdict == fit_check.RETRY:
        raise Wait(why)                     # tsubasa couldn't answer this time: asked again at the next look
    if verdict != fit_check.TIMED:
        title = steps.title(lang, job)
        raise Needs("not-timed", f"{title}: {why}" if title else why)
    picked["offset"] = offset               # the shift Anki Miner cuts the lines by (intent keeper P2.4-A #1)
    ledger.set_state(jid, "mining", picked=picked)


def _mine(steps, ledger, lang, job, record=True):
    """The mine step: the words not settled yet, in one batch (tried again after a batch in doubt; a second crash
    ends it), then the mining's one store write — every batch's made words and the receipt together (`record`: False
    for a job of a store set up again since). Raises Wait, Needs, Repick, and _Finished when the job ends here
    (skipped, failed)."""
    jid = job["id"]
    picked = ledger.picked(jid) or {}
    words = picked.get("words") or []
    by_key = {(w["word"], w["reading"]): w for w in words}
    ran = False                     # a batch ran in this call: the next one waits for an update staged meanwhile
    for _ in range(3):              # a batch in doubt is tried once more; a second failure ends it
        batches = ledger.batches(jid)
        last = batches[-1] if batches else None
        if last is not None and last["state"] == "running":
            # Connect was stopped mid-batch (its Anki Miner ended with it): what reached Anki is found by the job's
            # tag first, never mined twice; Connect's own stop is no failure of Anki Miner's (adversary #18)
            found = steps.by_tag(lang, job, picked, [w for w in words if _outcome(ledger, jid, w) in UNSETTLED])
            ledger.end_batch(jid, last["attempt"], "uncertain", _enriched(found, by_key))
            batches = ledger.batches(jid)
        todo = [w for w in words if _outcome(ledger, jid, w) in UNSETTLED]
        if not todo:
            break
        doubt = any(_outcome(ledger, jid, w) == "uncertain" for w in todo)
        if doubt and _failures(ledger, jid) >= 2:
            _fail_mining(steps, ledger, lang, job, record)
        if fit_check.version(steps.pairing(lang, job)) != picked.get("pairing"):
            raise Repick()                  # E17 before every batch (intent keeper #7): hato re-timed it meanwhile
        wait = _blocked(steps, lang, "mining", asked=bool(job.get("asked_at")))
        if wait is not None:
            raise wait
        if not _started(ledger, jid):       # P2.4 Part B: the cap before a job's first batch, never mid-episode
            wait = _at_cap(steps, ledger, lang, todo, asked=bool(job.get("asked_at")))
            if wait is not None:
                raise wait
        _stop_here(ledger, job, "mining")   # #47: between two batches too
        if ran and steps.update_staged():
            # between two Anki Miner batches (K99): stopped here, every outcome saved; the next run resumes at mining
            # and sends only the words still unsettled
            raise Wait(STOPPED_FOR_UPDATE, look=False, resume="mining")
        had = ledger.job_by_id(jid).get("attempt") or 0
        refused = bool(batches) and batches[-1]["state"] == "refused" and batches[-1]["attempt"] == had
        attempt = had if refused else had + 1      # a call Anki Miner refused never ran: its number reused (#20)
        in_doubt = any(b["state"] == "uncertain" for b in batches)
        ledger.set_state(jid, "mining", progress=None)      # a new batch: no progress yet (laptop round 5 #23)
        ledger.start_batch(jid, attempt, steps.run_dir(job))
        ran = True
        steps.on_progress = _Progress(ledger, jid)
        steps.should_stop = lambda: _stop_pressed(ledger, jid)      # #47: Anki Miner's batch cancelled at a press
        try:
            got = steps.mine(lang, job, picked, todo, attempt)
        except Wait as w:
            ledger.end_batch(jid, attempt, "refused")
            raise Wait(w.reason, w.look, "mining") from None
        except (Repick, Needs):
            ledger.end_batch(jid, attempt, "refused")
            raise
        except Skip as s:
            ledger.end_batch(jid, attempt, "refused")
            _record_made(steps, ledger, lang, job, record)
            _name_media_at_end(steps, ledger, lang, job)
            ledger.set_state(jid, "skipped", reason=s.why, skipped=_skipped(ledger, jid, "mining", s.why))
            raise _Finished("skipped") from None
        finally:
            steps.on_progress = steps.should_stop = None
        stopped = bool(got.get("stopped"))
        if got.get("tag_pending"):          # the names' tag Anki didn't take: added before filling (adversary #7)
            pending = sorted(set(_pending(ledger, jid)) | set(got["tag_pending"]))
            ledger.set_state(jid, "mining", tag_pending=json.dumps(pending))
        try:
            if stopped or got.get("doubt") or any(o["outcome"] == "uncertain" for o in got["outcomes"]):
                # #47: a batch you stopped is read back by the job's tag like one in doubt: every card that reached
                # Anki recorded, none sent twice
                # a word Anki Miner doesn't account for may be in Anki: found by the job's tag first, never sent twice
                found = steps.by_tag(lang, job, picked, [w for w in todo if _row(got, w) in UNSETTLED])
                got["outcomes"] = _merge(got["outcomes"], found)
            elif in_doubt:
                # tried again after a batch in doubt: a word it calls a duplicate may be this job's own card (#4)
                dup = [w for w in todo if _row(got, w) == "duplicate"]
                if dup:
                    got["outcomes"] = _merge(got["outcomes"], steps.by_tag(lang, job, picked, dup), ("duplicate",))
        except Wait as w:
            # Anki went away before the tag check: Anki Miner's own outcomes kept, the rest in doubt (adversary #16)
            ledger.end_batch(jid, attempt, "uncertain", _enriched(got["outcomes"], by_key), anki_miner=got.get("app"))
            if got.get("doubt") and not stopped:
                _count_failure(ledger, jid)
            raise Wait(w.reason, w.look, "mining") from None
        state = "uncertain" if any(o["outcome"] == "uncertain" for o in got["outcomes"]) else "done"
        ledger.end_batch(jid, attempt, state, _enriched(got["outcomes"], by_key), anki_miner=got.get("app"))
        if got.get("doubt") and not stopped:
            _count_failure(ledger, jid)     # only a run that crashed or timed out: an unknown status is no crash
        if any(o["outcome"] == "made" for o in got["outcomes"]):
            steps.after_write(lang)         # new cards: the session's sync clock (S3), Junban or not (adversary #12)
        if stopped:
            _stopped_mid_batch(steps, ledger, lang, job, record)
    left = [w for w in words if _outcome(ledger, jid, w) in UNSETTLED]
    if _failures(ledger, jid) >= 2 and any(_outcome(ledger, jid, w) == "uncertain" for w in left):
        _fail_mining(steps, ledger, lang, job, record)     # a second crash in the last try
    if left:                                # Anki Miner never accounted for them, three times: named, not mined
        never = f"{len(left)} words Anki Miner never made or turned down"
        ledger.set_state(jid, "mining", skipped=_skipped(ledger, jid, "mining", never))
    try:
        ledger.set_state(jid, "mining", progress={"step": "naming"})     # the row's step (laptop round 5 #23)
        _name_media(steps, ledger, lang, job, picked)   # P2.4-4: one file a line, before Anki's next sync
    except Wait as w:
        raise Wait(w.reason, w.look, "mining") from None
    # the store write after the rename: a rename that waits (you review) leaves nothing written to do again at every
    # look (adversary B #6, S19)
    _record_made(steps, ledger, lang, job, record)
    ledger.set_state(jid, "filling")


def _stop_pressed(ledger, jid):
    """(Anki Miner's poll, on the runner's thread, every POLL_S.) Has *Stop* been pressed on the job? A read that
    fails is no press (logged): the batch goes on."""
    try:
        return ledger.stop_asked(jid)
    except Exception:
        log.warning("Connect couldn't look for a Stop on job %s", jid, exc_info=True)
        return False


def _stopped_mid_batch(steps, ledger, lang, job, record):
    """#47: the batch Anki Miner ended at your *Stop*: its cards recorded in the store (made words, no receipt: the
    episode isn't mined yet) and renamed, then the job waits for your next ask at mining (the words still unmade).
    A store busy now is no matter: the resumed job records them all."""
    now = ledger.job_by_id(job["id"]) or {}
    ledger.mark_stopped(job["id"], now.get("asked_at"))
    made = _made(ledger, job["id"])
    if made and record:
        try:
            steps.record(lang, job, made, None, _tag(job))
        except Wait:
            log.info("Connect: the store was busy; job %s's cards are recorded when it goes on", job["id"])
        _name_media_at_end(steps, ledger, lang, job)
    log.info("Connect: job %s stopped by you mid-batch (%d words made)", job["id"], len(made))
    raise Wait(STOPPED_BY_YOU, look=False, resume="mining")


PROGRESS_STEP = 5               # percent: the job's progress is saved when it moves this far, or its stage changes


class _Progress:
    """Where Anki Miner's run stands, saved in the job while it mines (laptop round 5 #23: the row moves, never *0/57*
    to the end) — only when its stage changes or its percent (`anki_miner.percent`) moves PROGRESS_STEP (S19: a few
    writes a run). Called on the runner's own thread, between its waits on Anki Miner; a write that fails is logged,
    never a reason to stop the batch."""

    def __init__(self, ledger, jid):
        self.ledger, self.jid, self.last = ledger, jid, None

    def __call__(self, progress):
        from app.connect import anki_miner
        key = (progress["stage"], anki_miner.percent(progress) // PROGRESS_STEP)
        if key == self.last:
            return
        self.last = key
        try:
            self.ledger.set_state(self.jid, "mining", progress=progress)
        except Exception:
            log.warning("Connect couldn't save the batch's progress", exc_info=True)


def _name_media(steps, ledger, lang, job, picked=None):
    """The job's made notes' clip and picture renamed by the line (every batch's: a rename a Wait put off is done
    by the next look)."""
    lines = [(o["note_id"], o["line_start"], o["line_end"], o["sentence"]) for o in ledger.outcomes(job["id"])
             if o["outcome"] == "made" and o["note_id"] is not None]
    if lines:
        steps.name_media(lang, job, picked if picked is not None else (ledger.picked(job["id"]) or {}), lines)


def _name_media_at_end(steps, ledger, lang, job):
    """A job that ends here (skipped, failed) still renames the cards it made; one that can't now is left (logged):
    the names are tidiness, never a reason to keep the job (review B #4)."""
    try:
        _name_media(steps, ledger, lang, job)
    except Exception:
        log.warning("Connect couldn't rename the media of a job that ended", exc_info=True)


def _made(ledger, jid):
    """{word: [note id, …]} of the job's made outcomes."""
    made = {}
    for o in ledger.outcomes(jid):
        if o["outcome"] == "made" and o["note_id"] is not None:
            made.setdefault(o["word"], []).append(o["note_id"])
    return made


def _record_made(steps, ledger, lang, job, record):
    """The mining's one store write: every card the job made (G1.3-4 reads it) and the receipt — before any finished
    state too (adversary #6). A busy store → the job waits at mining (`record`: False for a store set up again)."""
    if not record:
        return
    try:
        steps.record(lang, job, _made(ledger, job["id"]), _now() if job.get("kind") != "level" else None, _tag(job))
    except Wait as w:
        raise Wait(w.reason, w.look, "mining") from None


def _pending(ledger, jid):
    try:
        return json.loads((ledger.job_by_id(jid) or {}).get("tag_pending") or "[]")
    except ValueError:
        return []


def _fail_mining(steps, ledger, lang, job, record=True):
    """A second failure (E11): the cards it did make recorded (and their order owed), the job `failed`, named once in
    Needs you; nothing is tried a third time."""
    _record_made(steps, ledger, lang, job, record)
    _name_media_at_end(steps, ledger, lang, job)
    if _made(ledger, job["id"]):
        with ledger.transaction():
            ledger.owe_resort(lang)
    ledger.set_state(job["id"], "failed", reason="Anki Miner stopped twice while making its cards")
    ledger.need(lang, "mine-failed", f"{steps.title(lang, job) or 'An episode'}: Anki Miner stopped twice while "
                "making its cards. Look in Anki for the cards it made.", item_id=job["item_id"], job_id=job["id"])
    raise _Finished("failed")


def held_by_cap(asked):
    """Does the cap hold this job? Never one carrying an ask (*Mine now*, *Mine this*, *Mine it too*): your press is the
    yes for that episode's cards, past the cap as past the battery (Sonic's M-3 A, laptop round 7 #42). The one rule
    `_full` and `_at_cap` read."""
    return not asked


def _full(steps, lang, asked=False):
    """Before a job's pick: a Wait when Connect's waiting cards are at the cap and this run's shelf has had its try (it
    can free nothing more until you study), else None — one request, so a job waiting at the cap is never picked
    again at every look. `asked`: the job carries an ask (`held_by_cap`)."""
    if not held_by_cap(asked) or not getattr(steps, "shelf_tried", lambda _lang: False)(lang):
        return None
    cap = steps.cap(lang)
    if not cap:
        return None
    count = steps.waiting_count(lang)
    if count is None or count < cap:
        return None
    return Wait(f"Your {count} cards are waiting: Connect makes more as you study them.", resume="mining")


def _at_cap(steps, ledger, lang, todo, asked=False):
    """P2.4 Part B (the cap, the shelf): a Wait when Connect's waiting cards are at the learner's cap, else None. At the
    cap the shelf is asked first (once a run, only on a big gap); what it frees may let this batch go. `asked`: the
    job carries an ask — never held, nothing shelved for it (`held_by_cap`)."""
    if not held_by_cap(asked):
        return None
    cap = steps.cap(lang)
    if not cap:
        return None
    count = steps.waiting_count(lang)
    if count is None or count < cap:
        return None
    if steps.shelve(lang, ledger, todo, count, cap):
        count = steps.waiting_count(lang)
        if count is not None and count < cap:
            return None
    return Wait(f"Your {count} cards are waiting: Connect makes more as you study them.", resume="mining")


def _outcome(ledger, jid, word):
    row = ledger.conn.execute("SELECT outcome FROM outcomes WHERE job_id = ? AND word = ? AND reading = ?",
                              (jid, word["word"], word["reading"])).fetchone()
    return row[0] if row else None


def _row(got, word):
    key = (word["word"], word["reading"])
    return next((o["outcome"] for o in got["outcomes"] if (o["word"], o["reading"]) == key), None)


def _merge(outcomes, found, also=()):
    """Anki Miner's outcomes, a word it left unsettled (or one of `also`) replaced by its card found by tag."""
    better = {(o["word"], o["reading"]): o for o in found if o["outcome"] == "made"}
    return [better.get((o["word"], o["reading"]), o) if o["outcome"] in UNSETTLED or o["outcome"] in also else o
            for o in outcomes]


def _enriched(outcomes, by_key):
    """Anki Miner's outcomes with the pick's line (start, end, sentence) and predicted class (N6, D1)."""
    out = []
    for o in outcomes:
        w = by_key.get((o["word"], o["reading"]), {})
        out.append(dict(o, orth=w.get("orth"), line_start=w.get("line_start", o.get("line_start")),
                        line_end=w.get("line_end"), sentence=w.get("line_text"), predicted=w.get("predicted_class")))
    return out


def _failures(ledger, jid):
    return int(ledger.job_by_id(jid).get("failures") or 0)


def _count_failure(ledger, jid):
    with ledger.transaction():
        ledger.conn.execute("UPDATE jobs SET failures = failures + 1 WHERE id = ?", (jid,))


def _skipped(ledger, jid, step, why):
    """The job's skipped steps, with `step` named (its `skipped` column, read and added to)."""
    row = ledger.job_by_id(jid) or {}
    try:
        had = json.loads(row.get("skipped") or "{}")
    except ValueError:
        had = {}
    had[step] = why
    return had


def _fill(steps, ledger, lang, job):
    jid = job["id"]
    ledger.set_state(jid, "filling")
    ids = ledger.undo_record(jid)
    if not ids:
        ledger.set_state(jid, "ordering")
        return
    wait = _blocked(steps, lang, "filling", asked=bool(job.get("asked_at")))
    if wait is not None:
        raise wait
    pending = _pending(ledger, jid)
    if pending:                             # the names' tag, before anything else touches the notes (adversary #7)
        steps.tag_names(lang, pending)
        ledger.set_state(jid, "filling", tag_pending=None)
    try:
        steps.fill(lang, job, ids)
    except Wait as w:
        raise Wait(w.reason, w.look, "filling") from None
    except Skip as s:
        ledger.set_state(jid, "ordering", skipped=_skipped(ledger, jid, "filling", s.why))
        return
    except Needs as n:
        ledger.need(lang, n.kind, n.say, item_id=job["item_id"], job_id=jid)
        had = json.loads((ledger.job_by_id(jid) or {}).get("skipped") or "{}").get("filling")
        ledger.set_state(jid, "filling", skipped=_skipped(ledger, jid, "filling", n.say))
        if had is None:                     # Backfill failed: tried again at the next start, once (adversary #13)
            raise Wait(n.say, look=False, resume="filling") from None
        ledger.set_state(jid, "ordering")
        return
    skipped = json.loads((ledger.job_by_id(jid) or {}).get("skipped") or "{}")
    if skipped.pop("filling", None) is not None:        # filled at its second try: nothing left to name
        ledger.set_state(jid, "ordering", skipped=skipped or None)
        return
    ledger.set_state(jid, "ordering")


def _order(steps, ledger, lang, job):
    jid = job["id"]
    ledger.set_state(jid, "ordering")
    if not ledger.undo_record(jid) and not ledger.resort_owed(lang):
        return
    wait = _blocked(steps, lang, "ordering", asked=bool(job.get("asked_at")))
    if wait is not None:
        raise wait
    try:
        deferred = steps.order(lang, job) == DEFERRED
    except Wait as w:
        raise Wait(w.reason, w.look, "ordering") from None
    except Skip as s:
        ledger.set_state(jid, "ordering", skipped=_skipped(ledger, jid, "ordering", s.why))
        return
    except Needs as n:
        ledger.need(lang, n.kind, n.say, item_id=job["item_id"], job_id=jid)
        ledger.set_state(jid, "ordering", skipped=_skipped(ledger, jid, "ordering", n.say))
        return
    with ledger.transaction():
        if deferred:
            ledger.owe_resort(lang)         # the Generate after mining orders Anki from its new list (F11)
        else:
            ledger.resort_paid(lang)


# --------------------------------------------------------------------------- #
# The real steps: the command line's own verbs, in this process
# --------------------------------------------------------------------------- #
class Steps:
    """What the loop asks of Anki, Anki Miner, the store and the list. Each method raises Wait / Needs / Skip /
    Repick as the loop reads them; a test hands its own (`tests/connect/test_runner.py`)."""

    def __init__(self, loaded, live=False):
        self.loaded = loaded
        self.live = live            # the run's own steps: what may change while it runs (the cap) read from the file
        from app.connect import kick
        self._woken = kick.wake_stamp()     # the wake mark as the run found it: a kick since ends a pause (#42)
        self._began = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())     # the ledger's stamps' form
        from app import anki_connect
        self.url = anki_connect.address(loaded)
        self._current = {}          # {lang: replan.Current}: the plan this run mines and orders from (P3.3)
        self._after = {}            # {lang: why}: a Generate owed once this run's mining is done (F11)
        self._served = set()        # the languages whose run plan the engine serves (prepare's, the Generate after
                                    # mining's): a plan read since that it can't serve defers the re-order (#4)
        self._anki_miner_sets = {}  # {lang: the set}: this run's Anki Miner look-ups, read once (LF-mining row 25)

    # --- the run ------------------------------------------------------------------------------------------- #
    def lower_priority(self):
        from app.connect import power
        power.lower_priority()

    def update_staged(self):
        from app import library_store
        return library_store.update_staged(looks=library_store.PROBE_LOOKS)

    def kicked(self):
        """Has a kick stamped the wake mark since the last look at it (`kick.wake_stamp`)? Then the mark is taken as
        seen: one wake a kick."""
        from app.connect import kick
        now = kick.wake_stamp()
        if now == self._woken:
            return False
        self._woken = now
        return True

    def enabled(self):
        """Connect's switch as settings.json holds it now (read again at every look and before each job): off, or
        a file that can't be read, stops the run. 3.0 (P3.3 C1): D29's switch (`logic.automation`) off stops it too —
        no automatic mining with the automation off (the one gate, `settings_manager.connect_on`: P4.1 row 4.1.1)."""
        from app import settings_manager
        from app.cli import verbs
        try:
            return settings_manager.connect_on(verbs.settings())
        except Exception:
            return False

    def settle(self):
        from app.cli.verbs import _session
        session = _session(self.loaded)
        if session is not None:
            session.settle(self.url, self.loaded)

    # --- the library --------------------------------------------------------------------------------------- #
    def _store(self, lang):
        from app.connect import library
        store = library.open_store(lang)
        if store is None:
            raise Needs("no-store", "Surasura's library isn't ready for Connect: open Surasura once.")
        return store

    def consume(self, lang, ledger):
        """The inbox and the level raise's look (P2.1, P2.2), as `connect --consume-only` reads them."""
        from app.cli import connect_verbs
        from app.connect import inbox, library
        store = library.open_store(lang)
        if store is None:
            return
        with store:
            connect_verbs._store_write(lambda: inbox.consume(store, lang, ledger), WAIT_S)
            connect_verbs._level(store, lang, self.loaded)

    def _open(self, lang):
        """The language's store for a read or write the loop can't do without -> the store; a store busy past the
        store's own wait → Wait (looked at again); none to write (JSON mode, read-only, damaged) → Needs."""
        from app import library_store
        from app.connect import library
        from app.path_utils import get_data_path
        store = library.open_store(lang)
        if store is not None:
            return store
        mode, reason = library_store.check_mode(lang, get_data_path(lang), busy_wait=0.0)
        if mode == "store" or reason == "busy":
            raise Wait(LIBRARY_BUSY)
        raise Needs("no-store", "Surasura's library can't be written just now, so Connect can't make cards. Open "
                                "Surasura to see why.")

    def mine_line(self, lang):
        from app.connect import library
        with self._open(lang) as store:
            return library.mine_line(store)

    def store_id(self, lang):
        from app.connect import library
        with self._open(lang) as store:
            return library.store_id(store)

    def text_only(self, lang, job):
        """P4.1 (K67): is the job's item a book or a text (no video to mine from)? Its file's type as the window
        reads it (`infer_source_type`); a busy store → False (the pick looks at it as for any job)."""
        from app.path_utils import infer_source_type
        try:
            store = self._open(lang)
        except (Wait, Needs):
            return False
        with store:
            item = store.item(job["item_id"]) or {}
        if not item:
            return False
        return infer_source_type(item.get("rel_path") or "", declared=item.get("source_type")) in ("epub", "text")

    def watched(self, lang, job):
        """Laptop round 8 #49: is the job's episode marked watched (the store's `watched`)? A busy store -> False (the
        job goes on as before)."""
        try:
            store = self._open(lang)
        except (Wait, Needs):
            return False
        with store:
            item = store.item(job["item_id"]) or {}
        return bool(item.get("watched"))

    def title(self, lang, job):
        try:
            store = self._open(lang)
        except (Wait, Needs):
            return None                     # a title only names the episode in a message
        with store:
            item = store.item(job["item_id"]) or {}
        entry = item.get("entry") or {}
        return entry.get("title") or (os.path.basename(item.get("rel_path") or "") or None)

    def pairing(self, lang, job):
        """The item's pairing; a busy store is a Wait, never "no pairing" (adversary P2.4-A #10)."""
        from app.connect import library
        with self._open(lang) as store:
            return library.pairing_of(store, job["item_id"])

    def subtitle(self, lang, job):
        from app.path_utils import get_data_path
        with self._open(lang) as store:
            item = store.item(job["item_id"])
        if item is None:
            return None
        return os.path.join(get_data_path(lang), *str(item["rel_path"]).replace("\\", "/").split("/"))

    def video(self, lang, job):
        """The episode's video on this computer: hato's pairing names it; else a video beside the subtitle with its
        name; else one beside the original it was copied from (K21: a folder's or + Add's origin, `beside_origin`);
        else the video index (P2.5 row 2.5.8, G1.3-12: the paired videos' folders and the ones you added — by
        name, and size when the pairing gives one). None when there's none, or only a cloud placeholder (never
        opened, RD-S1)."""
        with _held():                       # the store's two reads, one open; the disk is looked at after
            pairing = self.pairing(lang, job) or {}
            named = pairing.get("video_path")
            paired = isinstance(named, str) and bool(named)
            subtitle = None if paired else self.subtitle(lang, job)
        from app.connect import videos
        if paired:                          # the index is made (and listed) only once the named path isn't on disk
            return paired_video(pairing, lambda names, size: self._videos(lang).find(names, size))
        if not subtitle:
            return None
        names = videos.names_for(subtitle)
        origin = origin_of(pairing)
        if origin:
            names += videos.names_for(origin)   # a copy renamed `name (2)` in Library/: the original's name finds it
        return beside(subtitle) or beside_origin(pairing) or self._videos(lang).find(names)

    def _videos(self, lang):
        """The language's video index, refreshed once a run, the first time a video is missing (S19: only folders
        whose time moved are listed again). The folders the store reads as sources (SRC M1: the ones on) are indexed
        as the folders you added are, as deep: a subtitle in `Show/Subs/` finds `Show/ep.mkv`, and a video that came
        after its subtitle is found by name. A source offline keeps what it last listed (the index's own rule)."""
        from app.connect import library, videos
        made = getattr(self, "_video_index", {})
        if lang not in made:
            with self._open(lang) as store:
                shallow = sorted({os.path.dirname(r["video_path"]) for records in library.pairings(store).values()
                                  for r in records if isinstance(r, dict) and isinstance(r.get("video_path"), str)
                                  and r["video_path"]})
                sources = [s["path"] for s in store.sources(counts=False)]
            index = videos.Index(lang)
            index.refresh(shallow, videos.configured(self.loaded, lang), sources=sources)
            made[lang] = index
            self._video_index = made
        return made[lang]

    def record(self, lang, job, made, mined_at, batch):
        """The mining's one store write (receipt + made words): a busy store is looked at again, one that can't be
        written is Needs you — the job never goes on without its record (G1.3-4 reads it)."""
        from app import library_store
        from app.connect import library
        with self._open(lang) as store:
            try:
                library.record_batch(store, job["item_id"], made, mined_at, batch)
            except library_store.StoreBusy:
                raise Wait(LIBRARY_BUSY) from None
            except library_store.StoreReadOnly:
                raise Needs("no-store", "Surasura's library can't be written just now, so Connect can't record the "
                                        "cards it made. Open Surasura to see why.") from None

    # --- Anki and its tools -------------------------------------------------------------------------------- #
    def blocked(self, lang):
        """The one reason Connect can't touch Anki now, or None: on battery first, then the session's (Anki closed,
        busy, another profile, no profile named yet, you reviewing — the session records the first one Anki names
        as Connect's, laptop round 5 #22)."""
        from app.connect import power
        if os.environ.get("SURASURA_NO_ANKI_SYNC"):     # the test suites, a developer's run: Anki is never reached
            return Wait(ANKI_OFF, look=False)
        if power.on_battery():
            return ON_BATTERY
        return self.session_blocked(lang)

    def session_blocked(self, lang):
        """The session's reason alone (Anki closed, busy, another profile, none named yet, you reviewing), or None —
        what still holds a job carrying an ask on battery (M-3)."""
        from app.connect import anki_session
        if os.environ.get("SURASURA_NO_ANKI_SYNC"):
            return Wait(ANKI_OFF, look=False)
        return anki_session.waiting(self.url, self.loaded)

    def on_battery(self):
        from app.connect import power
        return power.on_battery()

    def after_write(self, lang):
        """New cards made: the session's sync clock (S3; P2.3's rule), then the Anki backlog read again, so the
        window's count of new cards follows within its 3 s look (laptop round 5 #27: whoever adds cards reads the
        backlog after) — never fatal."""
        from app.cli import verbs
        from app.connect import anki_session
        try:
            anki_session.after_write(self.loaded, True)
        except Exception:
            log.exception("Connect couldn't note its write for Anki's sync")
        try:
            verbs._backlog_read(self.loaded, lang, after_cards=True)
        except Exception:
            log.exception("Connect couldn't read Anki's new cards again")

    def miner_found(self):
        from app.connect import anki_miner
        return anki_miner.find(self.loaded) is not None

    def tag_names(self, lang, note_ids):
        """The names' tag Anki didn't take after a batch, added now under Anki's write lock (never while you
        review)."""
        from app import anki_connect, locks
        from app.connect import runfile
        try:
            held = anki_connect.writer("Connect's name tags", wait=WAIT_S)
        except locks.Busy:
            raise Wait(WRITER_BUSY, resume="filling") from None
        with held:
            try:
                if anki_connect.reviewing(self.url):
                    raise Wait(REVIEWING, resume="filling")
                anki_connect.invoke("addTags", self.url, notes=list(note_ids), tags=runfile.NAME_TAG)
            except anki_connect.AnkiError as e:
                raise _anki_wait(self.url, "filling", e) from None

    def prepare(self, lang, ledger):
        """Once a run, per language: the session's sync, one known-sync, then the plan's verdict (P3.3,
        `replan.current`): a Generate first only when the plan can't serve the library as it stands (a changed file,
        no plan, another engine, a lowered level: "first"); known words, new files alone (P4.1 C5) or a level raise
        ("after"): marked, the Generate runs once mining is done (`generate_after`, F11); only the order moved
        ("no"): no Generate at all."""
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import anki_session
        holds = verbs._results_language()
        if WAIT_FOR_OTHER_LIST and holds and holds != lang:
            raise Wait(OTHER_LIST.format(LANGUAGE_NAMES.get(holds, holds)))
        anki_session.begin(self.url, self.loaded)
        ns = SimpleNamespace(lang=lang, wait=WAIT_S, full=False, force=False)
        try:
            verbs.known_sync(ns)
        except CliError as e:
            if e.code in ("anki-closed", "anki-busy", "busy", "settings-unreadable"):
                raise (_anki_wait(self.url) if e.code == "anki-closed" else Wait(e.message)) from None
            raise Needs("known-sync", e.message) from None
        got = self.current(lang, fresh=True)        # after the known-sync: its new words are part of the verdict
        if got.generate == "first":
            self._generate(ns, "Generate didn't finish, so Connect waits for a current list.", ledger)
            got = self.current(lang, fresh=True)
        if got.generate == "after":
            self._after[lang] = got.reason
        else:
            self._after.pop(lang, None)
        self._serves(lang, got)
        self._shelved = set()
        try:
            self.notes_gone(lang)
            self.shelf_session(lang, ledger)
        except ImportError:                 # Junban isn't installed: no shelf, named (S10)
            self._say(lang, SHELF_NO_JUNBAN)
        except Exception:                   # never a reason not to mine: looked at again next run
            log.exception("Connect's shelf look or deleted-notes check didn't finish")

    def _generate(self, ns, say, ledger=None):
        """`surasura-cli generate` in this process: a moment's state (another Generate, settings.json caught
        mid-save) is a Wait, anything else *Needs you* with its log (E29). P4.1 row 4.1.7 (F9): `ledger`'s
        `generating:<lang>` mark is set while it runs and cleared however it ends — the status line's *Connect is
        updating your list*."""
        from app.cli import verbs
        from app.cli.contract import CliError
        _updating(ledger, ns.lang, True)
        try:
            return verbs.generate(ns)
        except CliError as e:
            if e.code in ("busy", "settings-unreadable"):     # exit 3: a moment's state, looked at again
                raise Wait(e.message) from None
            raise Needs("generate", f"{say} {e.message}") from None
        finally:
            _updating(ledger, ns.lang, False)

    def _settings(self, lang):
        """settings.json as it is now, for `lang` (the analyzer's argv is built from it), else this run's."""
        from app.cli import verbs
        try:
            loaded = verbs.settings()
        except Exception:
            loaded = self.loaded
        return dict(loaded, target_language=lang)

    def current(self, lang, fresh=False):
        """P3.3: the plan this run mines and orders from (`replan.current`), kept for the run and read again when
        the store's order or pins, the plan file or the run stamp moved since (`replan.key`: a move mid-run is
        re-planned before the next pick or re-order), or the settings the verdict reads (`replan.settings_key`: the
        band lowered with the window closed is read again, never ordered from the old plan: #4, H10). A busy store is
        a Wait; none to read is Needs (`_open`). A key that can't be read counts as moved: `replan.current`'s guarded
        read answers (review H9)."""
        from app.connect import replan
        kept = self._current.get(lang)
        settings = self._settings(lang)
        with self._open(lang) as store:
            if kept is not None and not fresh:
                try:
                    same = (replan.key(store) == kept.key
                            and replan.settings_key(settings, lang) == kept.settings_key)
                except Exception:
                    same = False
                if same:
                    return kept
            got = replan.current(lang, settings, store, previous=kept)
        self._current[lang] = got
        return got

    def _plan_now(self, lang):
        """`current`; a busy store is a Wait (the pick, the shelf and the re-order wait and look again, as every
        busy-store read does: review H8); None only when there is no store to read (Needs: they read the list as
        today, never worse)."""
        try:
            return self.current(lang)
        except Needs:
            return None

    def generate_after(self, lang, ledger):
        """F11: the Generate a plan marked "after" owes, once this run's mining is done -> True when it ran (the
        plan read again from its new list), False when none was owed. Raises Wait / Needs from the Generate (mining
        already done: only the list's refresh waits). The Generate going through is what counts: a plan that can't
        be read again just now (a busy store) is the follow-up's to read (review H5)."""
        why = self._after.pop(lang, None)
        if why is None:
            return False
        log.info("Connect: Generate after mining (%s): %s", lang, why)
        self._generate(SimpleNamespace(lang=lang, wait=WAIT_S, full=False, force=False),
                       "Generate didn't finish after Connect made its cards: your list catches up at the next one.",
                       ledger)
        try:
            self._serves(lang, self.current(lang, fresh=True))
        except (Wait, Needs) as e:
            log.info("Connect: the plan after the Generate is read at the follow-up (%s): %s", lang, e)
        return True

    def _serves(self, lang, got):
        """The run's plan, read fresh (prepare's, the Generate after mining's): does the engine serve it (`_served`;
        #4)? None of it -> the re-order reads the list as today (stand-aside, coverage)."""
        if got is not None and got.result is not None:
            self._served.add(lang)
        else:
            self._served.discard(lang)

    # --- P2.4 Part B: the cap, the shelf, media names, deleted cards ------------------------------------------- #
    def _anki(self):
        from app.connect import shelf
        return shelf.AnkiConnectAnki(self.url)

    def cap(self, lang=None):
        """`connect_backlog_cap` for `lang` — one cap per language (Sonic 2026-10-08, P2.4-B-SD4 changed; charter D31):
        a number is every language's cap, `{lang: n}` each its own (300 for one it doesn't name); 0: no cap; not a
        number: the default (review B #1) — `settings_values.cap_of`, Settings' own reading. The run's steps (`live`)
        read settings.json as it is now (`_settings`), so a cap raised in Settings reaches a Connect already waiting
        at the old one (laptop round 7 #42); a test's steps read the dict they were handed."""
        from app.connect.settings_values import cap_of
        loaded = self._settings(lang) if self.live else self.loaded
        return cap_of(loaded.get("connect_backlog_cap", 300), lang)

    def waiting_count(self, lang):
        """The cards waiting in Anki for `lang` — one count everywhere (laptop round 7 #41, Sonic's B3-2 A, 2026-10-22):
        every new, unsuspended note in the decks you chose for it plus Connect's own, wherever they are
        (`anki_sync.backlog_query(decks, connect=True)`: the bottom bar's *Anki · N waiting* is that search's saved
        answer, `anki_backlog.json`). A suspended card isn't waiting: your suspend says "known", Surasura's sets it
        aside. Your own new cards count toward the cap too. One cap per language (D31): Connect's notes count only
        those this language's store made (the tag spans every language; review r2 #2). Decks read as settings.json
        holds them now (`live`). Notes, as the bottom bar counts them."""
        from app import anki_connect, anki_sync
        from app.connect import shelf
        loaded = self._settings(lang) if self.live else self.loaded
        decks = list((loaded.get("anki_sync_decks") or {}).get(lang) or [])
        with self._open(lang) as store:
            made = shelf.made_notes(store)
        try:
            notes = set(anki_connect.find_notes(self.url, anki_sync.backlog_query(decks))) if decks else set()
            notes |= set(anki_connect.find_notes(self.url, anki_sync.backlog_query([], connect=True))) & set(made)
        except anki_connect.AnkiError as e:
            raise _anki_wait(self.url, "mining", e) from None
        return len(notes)

    def _list_order(self, lang):
        """{(Word, Reading): place} in the list's own order (Junban's), or None: the re-plan's (P3.3) when the plan
        serves the library as it stands, else the last Generate's list."""
        from app.cli import verbs
        from app.cli.contract import CliError
        got = self._plan_now(lang)
        if got is not None and got.listed is not None:
            return got.listed
        try:
            return verbs._listed(SimpleNamespace(wait=WAIT_S), lang)
        except CliError:
            return None

    def shelve(self, lang, ledger, todo, count, cap):
        """At the cap, once a run per language: the shelf's plan (a big gap only), shelved -> how many. A look that
        waits (you review, another writer, Anki gone) spends no try (review B #2, #3)."""
        from app import anki_connect, locks
        from app.connect import shelf
        if lang in getattr(self, "_shelved", set()):
            return 0
        try:
            shelved = self._shelve(lang, ledger, todo, count, cap)
        except ImportError:                 # Junban isn't installed: the shelf is skipped and named (S10)
            self._shelved = getattr(self, "_shelved", set()) | {lang}
            self._say(lang, SHELF_NO_JUNBAN)
            return 0
        except shelf.Reviewing:
            raise Wait(REVIEWING, resume="mining") from None
        except locks.Busy:
            raise Wait(WRITER_BUSY, resume="mining") from None
        except anki_connect.AnkiError as e:
            raise _anki_wait(self.url, "mining", e) from None
        self._shelved = getattr(self, "_shelved", set()) | {lang}
        return shelved

    def shelf_tried(self, lang):
        """Has this run's shelf had its one try for `lang`?"""
        return lang in getattr(self, "_shelved", set())

    def _shelve(self, lang, ledger, todo, count, cap):
        from app.connect import shelf
        order = self._list_order(lang) or {}
        ranks = shelf.ranks(order)
        with self._open(lang) as store:
            made = shelf.made_notes(store)
            # never the cards of an episode you asked for (*Mine now*: mined past the cap, `held_by_cap`) — the shelf
            # taking them would undo your press (laptop round 7 #42, review r42 #2); the ledger keeps every ask
            pinned = shelf.pinned_items(store) | {j["item_id"] for j in ledger.jobs(lang)       # this run's asks
                                                  if j.get("asked_at") and (j["state"] not in ENDED
                                                                            or (j.get("updated_at") or "") >= self._began)}
            finished = shelf.finished_items(store, made)
            holder = self._top_words(lang, store)
        anki = self._anki()
        kept = shelf.kept(ledger)               # taken off the shelf by you: never shelved again (✅ P2.5-2)
        waiting = [c for c in shelf.cards(anki, shelf.WAITING_QUERY, made) if c.card_id not in kept]
        for card in waiting:
            card.rank = ranks.get(card.word, shelf.NOT_LISTED)
        needed = [ranks.get(w["word"], shelf.NOT_LISTED) for w in todo]
        chosen = shelf.plan(waiting, needed, cap, count, pinned, holder, finished)
        if not chosen:
            return 0
        if len(chosen) < count + len(needed) - cap:
            # the count holds your own new cards too (B3-2 A), the shelf takes only Connect's: shelving that can't
            # bring the batch under the cap suspends cards for nothing (review r2 #3) — nothing is shelved
            self._say(lang, f"the shelf can't make room: {count} cards wait, {len(chosen)} of Connect's could go.")
            return 0
        run = shelf.shelve(anki, ledger, lang, chosen, "the cap: less relevant than the top 20's next words")
        self._say(lang, f"{len(chosen)} of Connect's waiting cards went to the shelf (suspended in Anki, tagged "
                        f"{shelf.SHELF_TAG}; restore point {run}).")
        return len(chosen)

    def _say(self, lang, line):
        log.info("Connect's shelf (%s): %s", lang, line)
        self.said = getattr(self, "said", {})
        self.said.setdefault(lang, []).append(line)

    def shelf_session(self, lang, ledger):
        """Once a run: a shelved card you un-suspended loses its tag; a shelved word the top 20 needs comes back."""
        from app.connect import shelf
        anki = self._anki()
        shelf.tidy(anki, ledger)
        with self._open(lang) as store:
            made = shelf.made_notes(store)
            finished = shelf.finished_items(store, made)
            holder = self._top_words(lang, store)
        shelved = shelf.cards(anki, f"{shelf.SHELVED_QUERY} is:suspended", made)
        back = [c for c in shelved if c.word in holder]
        if back:
            done = shelf.bring_back(anki, ledger, lang, back, finished, holder.get)
            self._say(lang, f"{done['back']} shelved cards came back: the top 20 needs their words again.")

    def _top_words(self, lang, store):
        """{word: the top-20 item that holds it} — the swap-in brings these back and the shelf never takes them
        (adversary B #5): the list's words per file (`file_words.json`), by each line item's file name."""
        from app.cli import connect_verbs
        from app.connect import library
        line = library.mine_line(store)
        names = {i: os.path.basename((store.item(i) or {}).get("rel_path") or "") for i in line}
        read = connect_verbs._read_list(lang)
        file_words = (read[2] if read else {}) or {}
        holder = {}
        for item in line:
            for word in file_words.get(names.get(item), ()) or ():
                holder.setdefault(word, item)
        return holder

    def finish_undos(self, lang, ledger):
        """An *Undo this batch* a kill left half-way (recorded before Anki was written) finished now (P2.5, intent
        keeper #4): its gone notes' words freed, the job `undone`."""
        if not ledger.pending_undos(lang):
            return 0
        from app.connect import library, undo
        return undo.finish_pending(undo.AnkiConnectUndo(self.url), ledger, lang, lambda: library.open_store(lang))

    def notes_gone(self, lang):
        """Row 2.4.14: the store's note ids (yours and Connect's) checked against Anki once a run; the gone ones
        told to the store (`Store.notes_gone`, L3.3). Nothing when Anki doesn't answer, when it is open on another
        profile now (known-sync and Generate ran since the run's first look), or when every one of 10 or more notes
        reads as gone (another collection answering, never a learner's day: logged, looked at again next run;
        adversary L3.3 wiring #4)."""
        from app.connect import anki_session, library, shelf
        with self._open(lang) as store:
            ids = library.note_ids(store)
        gone = shelf.gone_notes(self._anki(), ids)
        if gone and anki_session.waiting(self.url, self.loaded) is not None:
            return []
        if gone and len(gone) == len(ids) >= ALL_GONE_MIN:
            log.warning("Connect's deleted-card check: Anki has none of the %d notes the library holds; nothing "
                        "marked gone", len(ids))
            return []
        if gone:
            with self._open(lang) as store:
                library.notes_gone(store, gone)
        return gone

    def name_media(self, lang, job, picked, lines):
        """P2.4-4: the batch's clip and picture renamed by the line (`media_names.rename`). The field mapping is this
        run's, else the job's own settings export (a run after a kill: review B #4); Anki busy or gone -> a Wait
        (review B #2); some of its actions failed -> that episode's own wait (R2-1)."""
        from app import anki_connect, locks
        from app.connect import media_names
        fields = getattr(self._job_mapping(job), "fields", None) or self._export_fields(lang, job)
        if not lines or not fields:
            return None
        pairing = self.pairing(lang, job) or {}
        key = pairing.get("content_key")
        if not key:
            with self._open(lang) as store:
                key = (store.item(job["item_id"]) or {}).get("rel_key") or f"item-{job['item_id']}"
        try:
            return media_names.rename(media_names.AnkiConnectMedia(self.url), lines, key, fields.get("audio"),
                                      fields.get("picture"))
        except media_names.Reviewing:
            raise Wait(REVIEWING, resume="mining") from None
        except locks.Busy:
            raise Wait(WRITER_BUSY, resume="mining") from None
        except media_names.Partial:         # the rest is done: that episode's own wait, finished at the next look (R2-1)
            raise Wait(ANKI_SLOW, resume="mining") from None
        except anki_connect.AnkiError as e:
            raise _anki_wait(self.url, "mining", e) from None

    def _job_mapping(self, job):
        """The field mapping this run's `mine` set — only for the job it mined; another job (resumed with nothing left
        to mine) reads its own settings export (adversary B #16)."""
        if getattr(self, "_mapping_job", None) != job.get("id"):
            return None
        return getattr(self, "_mapping", None)

    def _export_fields(self, lang, job):
        """{role: field} from the settings export Anki Miner wrote in the job's run folder, or {}."""
        from app.connect import fields
        try:
            with open(os.path.join(self.run_dir(job), "settings-export.json"), encoding="utf-8") as f:
                return dict(fields.from_export(json.load(f), lang).fields)
        except Exception:
            return {}

    def _anki_miner_held(self, lang):
        """This run's set of Anki Miner look-ups for `lang` (version answer, profile id, field mapping, export: filled
        by `verbs._anki_miner_setup`), handed to the pick and the mine step so an episode starts Anki Miner for `check`
        and `mine` alone (row 25). Emptied by any failure of Anki Miner or of the look-ups, and read again once 15
        minutes old (`verbs.SETUP_FOR_S`)."""
        return self._anki_miner_sets.setdefault(lang, {})

    def run_dir(self, job):
        from app.cli.verbs import _connect_folder
        return os.path.join(_connect_folder(), "runs", _tag(job))

    def pick(self, lang, job, video):
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import library
        with _held():                       # the store's reads, one open; never around `verbs.pick` (Anki Miner)
            subtitle = self.subtitle(lang, job)
            with self._open(lang) as store:      # every word Connect ever made, or no pick at all
                made = library.made_words_for(store, job)   # P4.1: an asked job makes a deleted card again (N15)
            # P3.3: the re-plan's ranks (a move served), else the list's (None) — its look at the store's versions in
            # the same open; a re-plan when something moved is the engine's (sub-second, no tokenizer, no Anki)
            got = self._plan_now(lang)
        if subtitle is None or not os.path.isfile(subtitle):
            raise Needs("no-subtitle", "An episode's subtitle isn't in Surasura's library any more.")
        ns = SimpleNamespace(lang=lang, file=subtitle, video=video, words=None, job=str(job["id"]), wait=WAIT_S,
                             made=made, listed=got.listed if got is not None else None,
                             held=self._anki_miner_held(lang))
        try:
            out = verbs.pick(ns)
        except CliError as e:
            ns.held.clear()                 # row 25: read again after any failure
            holds = verbs._results_language() if e.code == "not-set-up" else None
            if WAIT_FOR_OTHER_LIST and holds and holds != lang:     # you Generated another language meanwhile
                raise Wait(OTHER_LIST.format(LANGUAGE_NAMES.get(holds, holds))) from None
            raise _wait_or_needs(e, None, self.url) from None
        miner = out.get("anki_miner") or {}
        return {"words": out.get("words") or [], "file": subtitle, "subtitle": out.get("subtitle"),
                "profile": miner.get("profile"), "anki_miner": miner.get("app"),
                "absent": out.get("skipped") == "anki miner absent"}

    def fit(self, lang, job, pairing, video, subtitle):
        """-> (verdict, who, why, offset): `subtitle` is the library's copy (hato's sha256 is checked on it);
        `connect_trust_timing` (off by default; read from settings.json as it is now, so a switch turned mid-run counts
        for the next episode) mines an episode nothing here can check at its own times."""
        trust = self._settings(lang).get("connect_trust_timing") is True
        return fit_check.fit(pairing, video, subtitle, trust=trust)

    def mine(self, lang, job, picked, words, attempt):
        """One Anki Miner batch -> {"outcomes", "app", "doubt"} (doubt: the run crashed or timed out — the words it
        doesn't account for are found by tag)."""
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import anki_miner
        miner = anki_miner.find(self.loaded)
        if miner is None:
            raise Skip("Anki Miner isn't installed")
        run_dir = self.run_dir(job)
        held = self._anki_miner_held(lang)      # row 25: the pick's look-ups, kept (the setup empties it on a failure)
        try:
            setup = verbs._anki_miner_setup(self.loaded, lang, run_dir, held=held)
        except CliError as e:
            raise _wait_or_needs(e, "mining", self.url) from None
        if setup is None:
            raise Skip("Anki Miner isn't installed")
        mapping = self._mapping = setup[2]
        self._mapping_job = job.get("id")
        try:
            done = anki_miner.mine_batch(miner, lang, _tag(job), picked["video"], picked["subtitle"], words,
                                         mapping, self.loaded.get("connect_anki_miner_profile") or "Surasura",
                                         run_dir, self.url, attempt=attempt, wait=WAIT_S,
                                         subtitle_offset=float(picked.get("offset") or 0.0),
                                         expect_profile=picked.get("profile"),
                                         on_progress=getattr(self, "on_progress", None), known=setup[:2],
                                         should_stop=getattr(self, "should_stop", None))
        except anki_miner.AnkiMinerError as e:
            held.clear()                        # any Anki Miner failure (a profile changed too): read again next time
            if e.kind == "profile-changed":
                raise Repick() from None
            if e.kind == "cancelled" and getattr(e, "stopped", False):
                # #47: you stopped it before its result was written: what reached Anki is found by the job's tag
                return {"outcomes": [dict(_unsure(w)) for w in words], "app": None, "doubt": True, "stopped": True}
            if e.kind in ("crashed", "timeout"):
                return {"outcomes": [dict(_unsure(w)) for w in words], "app": None, "doubt": True}
            raise _miner_wait_or_needs(e, self.url) from None
        # in doubt: a crash or a timeout after the run (`error`), or a run Anki Miner itself says failed
        run = done.get("run") or {}
        doubt = bool(done.get("error")) or (bool(run) and not run.get("ok"))
        return {"outcomes": done.get("outcomes") or [], "app": done.get("app"), "doubt": doubt,
                "tag_pending": done.get("tag_pending") or [], "stopped": bool(done.get("stopped"))}

    def by_tag(self, lang, job, picked, words):
        """Which of `words` reached Anki, found by the job's tag (read-only) -> outcomes (made / uncertain)."""
        from app import anki_connect
        from app.connect import anki_miner, fields
        field = getattr(self._job_mapping(job), "word", None)
        if field is None:
            try:
                with open(os.path.join(self.run_dir(job), "settings-export.json"), encoding="utf-8") as f:
                    field = fields.from_export(json.load(f), lang).word
            except Exception:
                field = None
        if field is None:
            return [_unsure(w) for w in words]
        for w in words:
            w.setdefault("sent", [w["word"]])
        try:
            return anki_miner.uncertain_by_tag(self.url, _tag(job), words, field)
        except anki_connect.AnkiError as e:
            raise _anki_wait(self.url, "mining", e) from None

    def fill(self, lang, job, note_ids):
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import runfile
        # the job's tag beside its notes: the source field (K40) is read from its run folder (adversary P2.4-A #8)
        ns = SimpleNamespace(lang=lang, wait=WAIT_S, notes=",".join(str(n) for n in note_ids),
                             tag=runfile.job_tag(_tag(job)), dry_run=False)
        try:
            out = verbs.backfill(ns)
        except CliError as e:
            raise _wait_or_needs(e, "filling", self.url) from None
        if isinstance(out.get("skipped"), str):         # absent, the preview off, Anki switched off: named
            raise Skip(out["skipped"])

    def order(self, lang, job):
        """Junban's automatic re-order (`junban --auto`'s body) — P3.3: from the engine's rows when the plan serves
        the library as it stands (`record_planned` after a clean run), with your 順 actions as every automatic
        re-order applies them on 3.0 (HY-6, C2: `positions_only` False). A plan that waits for the Generate after
        mining with no re-plan to order from (the level raised) -> DEFERRED: that Generate's follow-up orders. `job`:
        None for the follow-up.

        A newer order planned or made while this one was written (the window's host wrote one while Connect waited
        for `anki-writer`, or you moved), or a Generate that landed meanwhile without a move (known words, the band:
        `_junban_auto` tells it, review M1 and the final adversary's #2) -> re-planned and, when the re-plan's
        verdict is "no", ordered once more — once, never a loop (`Host._replan`'s own rule); any other verdict, or a
        newer one again after that second write -> DEFERRED (the re-sort stays owed: the next look re-orders, #1).
        Here, not in `_junban_auto`: the step holds the run's plan (`current`, read fresh).

        A plan read since the run's own that the engine can't serve (the settings, or a file, moved mid-run: `current`
        reads it again) -> DEFERRED: never the old plan's rows written and recorded planned (#4, H10)."""
        from app.cli import verbs
        from app.cli.contract import CliError
        got = self._plan_now(lang)
        if lang in self._after and (got is None or got.result is None):
            return DEFERRED
        if lang in self._served and got is not None and got.result is None:
            return DEFERRED
        for again in (False, True):
            ns = SimpleNamespace(lang=lang, wait=WAIT_S, auto=True, dry_run=False, current=got, positions_only=False)
            try:
                out = verbs.junban(ns)
            except CliError as e:
                raise _wait_or_needs(e, "ordering", self.url) from None
            if out.get("skipped") == "junban absent":
                raise Skip("Junban isn't installed")
            if out.get("skipped"):          # 順 off, an update waiting, the list out of date: named, the re-sort owed
                raise Skip(str(out["skipped"]))
            if out.get("stood_aside"):
                # P4.1 C8 (FT-1): you put this deck back while the step waited for `anki-writer` — nothing written, a
                # plain line in the run's summary, no job error and no re-sort owed (the deck isn't Surasura's to
                # re-order until you pick it in 順 again)
                log.info("Connect: the re-order stood aside (%s): %s", lang, out["stood_aside"])
                self.stood_aside = dict(getattr(self, "stood_aside", None) or {}, **{lang: str(out["stood_aside"])})
                return None
            if not getattr(ns, "newer", False):
                return None
            if again:                       # newer again during the second write: owed, never a third (#1)
                log.info("Connect: a newer order again while it wrote Anki's (%s): the re-sort stays owed", lang)
                return DEFERRED
            log.info("Connect: a newer order was planned while it wrote Anki's (%s): ordering once more", lang)
            got = self.current(lang, fresh=True)
            if got.generate != "no":        # the re-plan's verdict decides (#2): only one the engine serves as is
                return DEFERRED


def _tag(job):
    """The job's name in its tag and run folder (the ledger's `tag`: unique past a lost ledger)."""
    return job.get("tag") or str(job["id"])


def _unsure(word):
    return {"word": word["word"], "reading": word["reading"], "outcome": "uncertain", "note_id": None,
            "line_start": word.get("line_start")}


def anki_wait(reason):
    """Is `reason` a wait on Anki — closed, busy, not answering as it should, another profile or none named yet, you
    reviewing, another program writing to it? (The window's feed shows these as *Waiting for Anki*.)"""
    from app.connect import anki_session
    return isinstance(reason, str) and (
        reason in (ANKI_CLOSED, ANKI_SLOW, REVIEWING, WRITER_BUSY, anki_session.CLOSED, anki_session.BUSY,
                   anki_session.UNUSABLE, anki_session.REVIEWING, anki_session.NO_PROFILE_YET,
                   anki_session.NO_PROFILE_DECKS)
        or reason.startswith(anki_session.OTHER_PROFILE.split("{")[0]))


def holds_every(reason):
    """Does a wait with `reason` hold every episode, not only the one it stopped (laptop round 5 #24)? On battery, a
    wait on Anki (never ANKI_SLOW: Anki answers, one request of that episode's failed), Anki Miner's window open, or
    your list in another language: the pass ends there, every episode keeps its place, and the next look starts from
    the top — a later episode (or the next show) is never mined before the ones that waited."""
    if not isinstance(reason, str) or reason == ANKI_SLOW:
        return False
    return (reason in (ON_BATTERY, ANKI_MINER_OPEN) or reason.startswith(OTHER_LIST.split("{")[0])
            or anki_wait(reason))


# AnkiConnect's answers that name a refusal lasting until you act (IK-r2-2, PROVISIONAL): a deck, note type (model),
# note or field not found, or a note it can't create — matched in its message, ignoring case (`lasting_refusal`)
LASTING_REFUSALS = ("deck was not found", "deck not found", "model was not found", "model not found",
                    "note type not found", "note was not found", "note not found", "field was not found",
                    "field not found", "field is missing", "cannot create note")


def lasting_refusal(error):
    """Does AnkiConnect's answer name a refusal that lasts (LASTING_REFUSALS)? The one rule `_anki_wait` reads for
    every caller: *Needs you* for these, the episode's own wait for every other answer."""
    text = str(error).casefold()
    return any(part in text for part in LASTING_REFUSALS)


def _anki_wait(url, resume=None, error=None):
    """A call to Anki that failed, as the wait it is (laptop round 5 #26): Anki is called closed only when its port
    refuses (`anki_session.look`); one that doesn't answer in time — its own sync, a laptop under load — is *busy*;
    one that answers now (that one request failed) is ANKI_SLOW, the episode's own wait. With Anki switched off for
    the run (SURASURA_NO_ANKI_SYNC: the suites, a developer's run) it is never asked: *it isn't open*. `error`: the
    AnkiError caught — Anki answered (`action`, `protocol`): a refusal that lasts (`lasting_refusal`: a deck or note
    type gone) is no wait but *Needs you* (review IK #3: never retried every 2 minutes in silence); any other answer
    (a profile switching, a sync, Anki closing: "collection is not available") is ANKI_SLOW (IK-r2-2)."""
    from app.connect import anki_session
    if error is not None and getattr(error, "kind", None) in ("action", "protocol"):
        if lasting_refusal(error):
            return Needs("anki-refused", f"Anki turned down Connect's request: {error}")
        return Wait(ANKI_SLOW, resume=resume)
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return Wait(ANKI_CLOSED, resume=resume)
    state = anki_session.look(url)
    return Wait({"closed": ANKI_CLOSED, "unusable": anki_session.UNUSABLE, "open": ANKI_SLOW}.get(
        state, anki_session.BUSY), resume=resume)


def _wait_or_needs(error, resume, url=None):
    """A verb's CliError as the loop reads it: Anki or another writer busy → Wait (look again), else → Needs. Its
    `anki-closed` (any failed probe) is named by the session's look (`_anki_wait`)."""
    if error.code == "anki-closed":
        return _anki_wait(url, resume)
    if error.code in ("anki-busy", "busy", "anki-miner-busy", "settings-unreadable"):
        say = {"anki-busy": REVIEWING, "anki-miner-busy": ANKI_MINER_OPEN}.get(error.code, error.message)
        return Wait(say, resume=resume)
    return Needs(error.code, error.message)


def _miner_wait_or_needs(error, url=None):
    if error.kind == "busy":
        return Wait(ANKI_MINER_OPEN, resume="mining")
    if error.kind == "writer-busy":
        return Wait(WRITER_BUSY, resume="mining")
    if error.kind == "reviewing":
        return Wait(REVIEWING, resume="mining")
    if error.kind == "anki-closed":
        return _anki_wait(url, "mining")
    if error.kind == "absent":
        return Skip("Anki Miner isn't installed")
    return Needs(f"anki-miner-{error.kind}", error.message)


def _on_disk(path):
    """A file really on this computer: there, and not a cloud placeholder (whose read would download it, RD-S1)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return not (getattr(st, "st_file_attributes", 0) & _PLACEHOLDER)


def paired_video(pairing, find):
    """The video a pairing names (`video_path`), on this computer -> its path; else, moved, the one `find(names, size)`
    (a video index's lookup) gives by its name and size, when its bytes say it is the paired video; else None. One
    rule for Connect (`Runner.video`) and the window's ▶ (`app/services/play.py`): the two never disagree."""
    from app.connect import videos
    named = pairing.get("video_path")
    if _on_disk(named):
        return named                        # the named path is trusted as it is: never read (a stat only)
    size = pairing.get("video_size")
    found = find([os.path.basename(named)], size if isinstance(size, int) and size > 0 else None)
    # away from its named path, a file of that name and size is the paired video only when its bytes say so
    # (09-hato-layer v2 §1.1): another episode under the same name is never mined as this one. A source
    # folder's record keeps the video's key as `video_key` (its row is keyed by the origin: SRC B1), and one
    # with no key takes no moved video; every other record is judged as before Sources (review H14)
    if pairing.get("producer") == "source":
        key = pairing.get("video_key")
        refused = found is not None and (key is None or videos.content_key(found) != key)
    else:
        refused = found is not None and videos.content_key(found) != pairing.get("content_key")
    if refused:
        log.info("Connect: %s has the paired video's name and size but not its content; not used", found)
        return None
    return found


def origin_of(pairing):
    """The original an item's text was copied from, as its origin record names it (`producer` "source": a folder's
    look, or + Add's / a drop's, `via` "add") -> its path; else None. One rule for Connect and the window's ▶."""
    origin = (pairing or {}).get("origin") if (pairing or {}).get("producer") == "source" else None
    return origin if isinstance(origin, str) and origin else None


def beside_origin(pairing, exts=None, unlisted=None):
    """K21 (laptop fixes): the video beside the original an item's text was copied from (`origin_of`), with its name,
    on disk -> its path; else None (no record, another producer's, none there, a placeholder). A listing and a stat,
    never a read. Qt-free: Connect's `video()` asks it after `beside(subtitle)`; ▶ asks it too, with `exts` and
    `unlisted` as `beside` takes them (an audio item's ▶; a share offline)."""
    origin = origin_of(pairing)
    return beside(origin, exts, unlisted) if origin else None


def beside(subtitle, exts=None, unlisted=None, listings=None):
    """A video next to the subtitle with its name (`Show - 05.mkv` for `Show - 05.ja.srt`), on disk -> its path; None
    when there's none, `unlisted` when its folder can't be listed (a share offline: the window's ▶ says so). `exts`:
    what is looked for, the video extensions unless given (an audio item's ▶ looks for audio). `listings` ({folder: its
    names}, a caller's own — + Add's many files): each folder listed once across calls (H6)."""
    from app.episode_names import video_stems
    folder, name = os.path.split(subtitle)
    stems = video_stems(name)               # LM1a: its stem, without the marks the one rule reads, NFC and NFD
    names = listings.get(folder) if listings is not None else None
    if names is None:
        try:
            names = {n.lower(): n for n in os.listdir(folder or ".")}
        except OSError:
            return unlisted
        if listings is not None:
            listings[folder] = names
    for s in stems:
        for ext in exts or VIDEO_EXTENSIONS:
            found = names.get((s + ext).lower())
            if found and _on_disk(os.path.join(folder, found)):
                return os.path.join(folder, found)
    return None
