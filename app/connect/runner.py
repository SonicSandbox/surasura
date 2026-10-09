"""Connect's loop (P2.4 Part A; ORDER P2.4; P1.5 02-data-model §2, §2a, §4; 06-edges E1–E32): `surasura-cli connect`
without `--consume-only`. For every job the inbox queued (P2.1) and every level job (P2.2), in top-20 order, the next
day's words first:

    sync → known-sync → generate → pick → fit check → mine → backfill → junban → sync

- **Once a run, never per episode** (02 §4): the session's sync (`anki_session.begin`, P2.3: before Connect reads
  what you studied), one known-sync, one Generate when the list isn't current (`generate`'s own "nothing changed";
  a failed one → *Needs you* with its log, E29, and mining waits for a current list). Prepared per language, the
  first time a language has work.
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
  store (the library set up again: a new `store_id`) is dropped before mining (P2.1 adversary #12).
- **A missing tool** (🧭 Q4-2, RD-S10): Anki Miner absent → the job `skipped`, named; Backfill or Junban absent → that
  step skipped and named on the job (`skipped`), the loop goes on.
- **An update staged** (E26): the run stops at the next step boundary (the command line refuses to start one).
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

from app.connect import fit_check
from app.connect.ledger import BEFORE_MINING, IN_FLIGHT, Ledger

log = logging.getLogger("surasura-cli")

LOOK_EVERY_S = 120              # 02 §2a: while every job waits on something outside Connect
WAIT_S = 10.0                   # a verb's --wait inside the run (another Surasura writer, a Generate)

# The plain lines a waiting job shows (the status line's, never Needs you)
ON_BATTERY = "On battery: cards are made once this computer is plugged in."
ANKI_MINER_OPEN = "Anki Miner is open: close it to make cards."
WRITER_BUSY = "Another program is writing to Anki."
REVIEWING = "Waiting while you review in Anki."
ANKI_CLOSED = "Waiting for Anki: it isn't open."
NO_VIDEO = "No video: its video isn't on this computer (or isn't downloaded yet)."
CHINESE = "Chinese cards come later."
NO_LIST = "Waiting for a current list: Generate didn't finish."
LIBRARY_BUSY = "Surasura's library is busy: tried again shortly."
STOPPED_FOR_UPDATE = "Surasura is installing an update."
ANKI_OFF = "Anki is switched off for this run (SURASURA_NO_ANKI_SYNC)."
NO_WORDS = "no words to make cards from"
SWITCHED_OFF = "Connect was switched off."
MINER_ABSENT = "Anki Miner isn't installed"
NO_PROFILE = ("Connect doesn't know which Anki profile to make cards in, so it makes none. Set Connect up again in "
              "Surasura.")
# ASK-SONIC P2.4-8 ⭐ (a): with your list in another language, Connect waits rather than replace it with its own
# Generate (False: it goes ahead, as before)
WAIT_FOR_OTHER_LIST = True
OTHER_LIST = "Waiting: your list is in {}. Cards are made once a Japanese list is current again."
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}

# Anki Miner's settled outcomes: a word with one of these is never sent again for the job
UNSETTLED = (None, "uncertain", "not_attempted")
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".webm", ".avi", ".m4v", ".mov", ".ts")
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


def run(loaded, languages, steps=None, ledger=None, sleep=time.sleep, cancel=None, looks=None):
    """The loop, until no job is left (or every job left waits for the next start) -> a summary per language:
    {"done", "dropped", "skipped", "failed": [item ids], "waiting": {item id: reason}, "needs": [say, …]}, plus
    "looks" and, when it stopped early, "stopped". `looks`: at most this many looks (tests); `cancel`: an Event."""
    steps = steps or Steps(loaded)
    steps.lower_priority()
    own = ledger is None
    ledger = ledger or Ledger()
    summary = {"languages": {lang: _empty() for lang in languages}, "looks": 0}
    prepared = set()            # the languages whose sync, known-sync and Generate ran this run (02 §4: once)
    parked = set()              # jobs waiting for the next start: never tried again this run (adversary P2.4-A #11)
    try:
        while True:
            summary["looks"] += 1
            outside = work = False
            for lang in languages:
                stop = _stop(steps)
                if stop:
                    summary["stopped"] = stop
                    return summary
                if _consume(steps, ledger, lang):
                    outside = work = True       # the inbox couldn't be read: looked at again, never lost
                if not _open_jobs(ledger, lang, parked):
                    continue
                work = True
                outside |= _language(steps, ledger, lang, prepared, parked, summary["languages"][lang])
                stop = _stop(steps)                 # staged or switched off while its jobs ran: this step boundary
                if stop:
                    summary["stopped"] = stop
                    return summary
            if summary.get("stopped") or not work or not outside:
                break
            if looks is not None and summary["looks"] >= looks:
                break
            if not _pause(LOOK_EVERY_S, sleep, cancel):
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
    return [j for j in ledger.open_jobs(lang) if j["id"] not in parked and j["id"] not in tried]


def _empty():
    return {"done": [], "dropped": [], "skipped": [], "failed": [], "waiting": {}, "needs": []}


def _pause(seconds, sleep, cancel):
    if cancel is not None:
        return not cancel.wait(seconds)
    sleep(seconds)
    return True


def _ordered(jobs, line):
    """The open jobs, the top 20's order first (the next day's words first), then the rest oldest first."""
    place = {item_id: n for n, item_id in enumerate(line)}
    return sorted(jobs, key=lambda j: (place.get(j["item_id"], len(place)), j["id"]))


def _waiting_all(ledger, lang, parked, out, reason, look):
    for job in _open_jobs(ledger, lang, parked):
        _wait(ledger, job, Wait(reason, look, _resume_of(job)), out, parked)
    return look


def _language(steps, ledger, lang, prepared, parked, out):
    """Every open job of one language, once -> True when one waits on something outside Connect (look again). The top
    20 and the inbox are read again before each job (adversary P2.4-A #2): an episode moved out mid-burst is dropped,
    a new first one goes next."""
    if lang != "ja":            # E24: Japanese first, until Anki Miner and Connect say Chinese works
        return _waiting_all(ledger, lang, parked, out, CHINESE, False)
    wait = store_now = None
    try:
        wait = _blocked(steps, lang, None)
        if wait is None:
            steps.mine_line(lang)           # the store answers first: never an empty top 20 for a busy one
            store_now = steps.store_id(lang)
            if lang not in prepared:
                steps.prepare(lang, ledger)
                prepared.add(lang)
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
    while True:
        if tried and _consume(steps, ledger, lang):
            outside = True
        jobs = _open_jobs(ledger, lang, parked, tried)
        if not jobs:
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
            return _waiting_all(ledger, lang, parked, out, failed[0], failed[1]) or outside
        job = _ordered(jobs, line)[0]
        tried.add(job["id"])
        try:
            _job(steps, ledger, lang, job, store_now, set(line), out)
        except Wait as w:
            _wait(ledger, job, w, out, parked)
            outside |= w.look
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


def _blocked(steps, lang, resume):
    """`steps.blocked` as a Wait resuming at `resume` (it answers a reason, or a Wait of its own), or None. Raises
    Needs (no Anki profile recorded)."""
    why = steps.blocked(lang)
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
        parked.add(job["id"])


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
    if droppable and item_id not in line:
        ledger.set_state(jid, "dropped", reason="left the top 20")
        out["dropped"].append(item_id)
        return
    record = not foreign
    if droppable:
        full = _full(steps, lang)       # at the cap, the shelf tried: one count, no pick and no write (S19, review B adv #2)
        if full is not None:
            raise full
    try:
        for _ in range(3):          # a profile or pairing that changed since the pick: picked again (at most twice)
            try:
                if step in (None, "picking"):
                    got = _pick(steps, ledger, lang, job, record)
                    if got is None:
                        out["done"].append(item_id)
                        return
                    step = "filling" if got == "filling" else "fit-check"
                if step == "fit-check":
                    _fit(steps, ledger, lang, job)
                    step = "mining"
                if step == "mining":
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
    out["done"].append(item_id)


def _pick(steps, ledger, lang, job, record=True):
    """The pick step -> what it picked; None when it found no word (the job done with nothing to make); "filling"
    when it found none after an earlier batch made some (those recorded, then filled and ordered: adversary #6)."""
    jid = job["id"]
    ledger.set_state(jid, "picking")
    video = steps.video(lang, job)
    if video is None:
        raise Wait(NO_VIDEO, look=False)
    pairing = steps.pairing(lang, job)
    got = steps.pick(lang, job, video)
    declined = ledger.declined(lang, job["item_id"])     # Anki Miner turned them down once: never sent again (#19)
    words = [w for w in got.get("words") or [] if (w.get("word"), w.get("reading")) not in declined]
    picked = {"words": words, "file": got.get("file"), "subtitle": got.get("subtitle"),
              "video": video, "pairing": fit_check.version(pairing), "profile": got.get("profile"),
              "anki_miner": got.get("anki_miner")}
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
    verdict, _who, why, offset = steps.fit(lang, job, pairing, picked.get("video"), picked.get("file"))
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
        wait = _blocked(steps, lang, "mining")
        if wait is not None:
            raise wait
        if not _started(ledger, jid):       # P2.4 Part B: the cap before a job's first batch, never mid-episode
            wait = _at_cap(steps, ledger, lang, todo)
            if wait is not None:
                raise wait
        had = ledger.job_by_id(jid).get("attempt") or 0
        refused = bool(batches) and batches[-1]["state"] == "refused" and batches[-1]["attempt"] == had
        attempt = had if refused else had + 1      # a call Anki Miner refused never ran: its number reused (#20)
        in_doubt = any(b["state"] == "uncertain" for b in batches)
        ledger.set_state(jid, "mining")
        ledger.start_batch(jid, attempt, steps.run_dir(job))
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
        if got.get("tag_pending"):          # the names' tag Anki didn't take: added before filling (adversary #7)
            pending = sorted(set(_pending(ledger, jid)) | set(got["tag_pending"]))
            ledger.set_state(jid, "mining", tag_pending=json.dumps(pending))
        try:
            if got.get("doubt") or any(o["outcome"] == "uncertain" for o in got["outcomes"]):
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
            if got.get("doubt"):
                _count_failure(ledger, jid)
            raise Wait(w.reason, w.look, "mining") from None
        state = "uncertain" if any(o["outcome"] == "uncertain" for o in got["outcomes"]) else "done"
        ledger.end_batch(jid, attempt, state, _enriched(got["outcomes"], by_key), anki_miner=got.get("app"))
        if got.get("doubt"):
            _count_failure(ledger, jid)     # only a run that crashed or timed out: an unknown status is no crash
        if any(o["outcome"] == "made" for o in got["outcomes"]):
            steps.after_write(lang)         # new cards: the session's sync clock (S3), Junban or not (adversary #12)
    left = [w for w in words if _outcome(ledger, jid, w) in UNSETTLED]
    if _failures(ledger, jid) >= 2 and any(_outcome(ledger, jid, w) == "uncertain" for w in left):
        _fail_mining(steps, ledger, lang, job, record)     # a second crash in the last try
    if left:                                # Anki Miner never accounted for them, three times: named, not mined
        never = f"{len(left)} words Anki Miner never made or turned down"
        ledger.set_state(jid, "mining", skipped=_skipped(ledger, jid, "mining", never))
    _record_made(steps, ledger, lang, job, record)
    try:
        _name_media(steps, ledger, lang, job, picked)   # P2.4-4: one file a line, before Anki's next sync
    except Wait as w:
        raise Wait(w.reason, w.look, "mining") from None
    ledger.set_state(jid, "filling")


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


def _full(steps, lang):
    """Before a job's pick: a Wait when Connect's waiting cards are at the cap and this run's shelf has had its try (it
    can free nothing more until you study), else None — one request, so a job waiting at the cap is never picked
    again at every look."""
    if not getattr(steps, "shelf_tried", lambda _lang: False)(lang):
        return None
    cap = steps.cap()
    if not cap:
        return None
    count = steps.waiting_count(lang)
    if count is None or count < cap:
        return None
    return Wait(f"Your {count} cards are waiting: Connect makes more as you study them.", resume="mining")


def _at_cap(steps, ledger, lang, todo):
    """P2.4 Part B (the cap, the shelf): a Wait when Connect's waiting cards are at the learner's cap, else None. At the
    cap the shelf is asked first (once a run, only on a big gap); what it frees may let this batch go."""
    cap = steps.cap()
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
    wait = _blocked(steps, lang, "filling")
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
    wait = _blocked(steps, lang, "ordering")
    if wait is not None:
        raise wait
    try:
        steps.order(lang, job)
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
        ledger.resort_paid(lang)


# --------------------------------------------------------------------------- #
# The real steps: the command line's own verbs, in this process
# --------------------------------------------------------------------------- #
class Steps:
    """What the loop asks of Anki, Anki Miner, the store and the list. Each method raises Wait / Needs / Skip /
    Repick as the loop reads them; a test hands its own (`tests/connect/test_runner.py`)."""

    def __init__(self, loaded):
        self.loaded = loaded
        from app import anki_connect
        self.url = anki_connect.address(loaded)

    # --- the run ------------------------------------------------------------------------------------------- #
    def lower_priority(self):
        from app.connect import power
        power.lower_priority()

    def update_staged(self):
        from app import library_store
        return library_store.update_staged(looks=library_store.PROBE_LOOKS)

    def enabled(self):
        """Connect's switch as settings.json holds it now (read again at every look and before each job): off, or
        a file that can't be read, stops the run."""
        from app.cli import verbs
        try:
            return bool(verbs.settings().get("connect_enabled"))
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
        name. None when there's none, or it's a cloud placeholder (never opened, RD-S1)."""
        pairing = self.pairing(lang, job) or {}
        named = pairing.get("video_path")
        if isinstance(named, str) and named:
            return named if _on_disk(named) else None
        subtitle = self.subtitle(lang, job)
        return beside(subtitle) if subtitle else None

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
        busy, another profile, you reviewing)."""
        from app.connect import anki_session, power
        if os.environ.get("SURASURA_NO_ANKI_SYNC"):     # the test suites, a developer's run: Anki is never reached
            return Wait(ANKI_OFF, look=False)
        if power.on_battery():
            return ON_BATTERY
        from app.connect import setup
        if anki_session.on(self.loaded) and not setup.anki_profile():
            # no profile recorded: the "another profile open" guard (E3) can't hold, so nothing is written
            # (adversary P2.4-A #9, intent keeper #4)
            raise Needs("no-profile", NO_PROFILE)
        return anki_session.waiting(self.url, self.loaded)

    def after_write(self, lang):
        """New cards made: the session's sync clock (S3; P2.3's rule) — never fatal."""
        from app.connect import anki_session
        try:
            anki_session.after_write(self.loaded, True)
        except Exception:
            log.exception("Connect couldn't note its write for Anki's sync")

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
            except anki_connect.AnkiError:
                raise Wait(ANKI_CLOSED, resume="filling") from None

    def prepare(self, lang, ledger):
        """Once a run, per language: the session's sync, one known-sync, one Generate when the list isn't current."""
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
            if e.code in ("anki-closed", "anki-busy", "busy"):
                raise Wait(ANKI_CLOSED if e.code == "anki-closed" else e.message) from None
            raise Needs("known-sync", e.message) from None
        try:
            verbs.generate(ns)
        except CliError as e:
            if e.code == "busy":
                raise Wait(e.message) from None
            raise Needs("generate", f"Generate didn't finish, so Connect waits for a current list. {e.message}") \
                from None
        self._shelved = set()
        try:
            self.notes_gone(lang)
            self.shelf_session(lang, ledger)
        except Exception:                   # never a reason not to mine: looked at again next run
            log.exception("Connect's shelf look or deleted-notes check didn't finish")

    # --- P2.4 Part B: the cap, the shelf, media names, deleted cards ------------------------------------------- #
    def _anki(self):
        from app.connect import shelf
        return shelf.AnkiConnectAnki(self.url)

    def cap(self):
        """`connect_backlog_cap` (default 300); 0: no cap; not a number: the default (review B #1)."""
        try:
            return max(0, int(self.loaded.get("connect_backlog_cap", 300)))
        except (TypeError, ValueError):
            return 300

    def waiting_count(self, lang):
        from app import anki_connect
        from app.connect import shelf
        try:
            return shelf.waiting_count(self._anki())
        except anki_connect.AnkiError:
            raise Wait(ANKI_CLOSED, resume="mining") from None

    def _list_order(self, lang):
        """{(Word, Reading): place} in the list's own order (Junban's), or None."""
        from app.cli import verbs
        from app.cli.contract import CliError
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
        except shelf.Reviewing:
            raise Wait(REVIEWING, resume="mining") from None
        except locks.Busy:
            raise Wait(WRITER_BUSY, resume="mining") from None
        except anki_connect.AnkiError:
            raise Wait(ANKI_CLOSED, resume="mining") from None
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
            pinned = shelf.pinned_items(store)
        anki = self._anki()
        waiting = shelf.cards(anki, shelf.WAITING_QUERY, made)
        for card in waiting:
            card.rank = ranks.get(card.word, shelf.NOT_LISTED)
        needed = [ranks.get(w["word"], shelf.NOT_LISTED) for w in todo]
        chosen = shelf.plan(waiting, needed, cap, count, pinned)
        if not chosen:
            return 0
        shelf.shelve(anki, ledger, lang, chosen, "the cap: less relevant than the top 20's next words")
        return len(chosen)

    def shelf_session(self, lang, ledger):
        """Once a run: a shelved card you un-suspended loses its tag; a shelved word the top 20 needs comes back."""
        from app.connect import library, shelf
        anki = self._anki()
        shelf.tidy(anki, ledger)
        with self._open(lang) as store:
            made = shelf.made_notes(store)
            finished = shelf.finished_items(store, made)
            line = library.mine_line(store)
            names = {i: os.path.basename((store.item(i) or {}).get("rel_path") or "") for i in line}
        from app.cli import connect_verbs
        read = connect_verbs._read_list(lang)
        file_words = (read[2] if read else {}) or {}
        holder = {}
        for item in line:
            for word in file_words.get(names.get(item), ()) or ():
                holder.setdefault(word, item)
        shelved = shelf.cards(anki, f"{shelf.SHELVED_QUERY} is:suspended", made)
        back = [c for c in shelved if c.word in holder]
        if back:
            shelf.bring_back(anki, ledger, lang, back, finished, holder.get)

    def notes_gone(self, lang):
        """Row 2.4.14: the store's note ids (yours and Connect's) checked against Anki once a run; the gone ones
        told to the store (a no-op until the store has `notes_gone`). Nothing when Anki doesn't answer."""
        from app.connect import library, shelf
        with self._open(lang) as store:
            if getattr(store, "notes_gone", None) is None:
                return []
            ids = library.note_ids(store)
        gone = shelf.gone_notes(self._anki(), ids)
        if gone:
            with self._open(lang) as store:
                library.notes_gone(store, gone)
        return gone

    def name_media(self, lang, job, picked, lines):
        """P2.4-4: the batch's clip and picture renamed by the line (`media_names.rename`). The field mapping is this
        run's, else the job's own settings export (a run after a kill: review B #4); Anki busy or gone -> a Wait
        (review B #2)."""
        from app import anki_connect, locks
        from app.connect import media_names
        fields = getattr(getattr(self, "_mapping", None), "fields", None) or self._export_fields(lang, job)
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
        except anki_connect.AnkiError:
            raise Wait(ANKI_CLOSED, resume="mining") from None

    def _export_fields(self, lang, job):
        """{role: field} from the settings export Anki Miner wrote in the job's run folder, or {}."""
        from app.connect import fields
        try:
            with open(os.path.join(self.run_dir(job), "settings-export.json"), encoding="utf-8") as f:
                return dict(fields.from_export(json.load(f), lang).fields)
        except Exception:
            return {}

    def run_dir(self, job):
        from app.cli.verbs import _connect_folder
        return os.path.join(_connect_folder(), "runs", _tag(job))

    def pick(self, lang, job, video):
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import library
        subtitle = self.subtitle(lang, job)
        if subtitle is None or not os.path.isfile(subtitle):
            raise Needs("no-subtitle", "An episode's subtitle isn't in Surasura's library any more.")
        with self._open(lang) as store:          # every word Connect ever made, or no pick at all
            made = library.made_words_all(store)
        ns = SimpleNamespace(lang=lang, file=subtitle, video=video, words=None, job=str(job["id"]), wait=WAIT_S,
                             made=made)
        try:
            out = verbs.pick(ns)
        except CliError as e:
            holds = verbs._results_language() if e.code == "not-set-up" else None
            if WAIT_FOR_OTHER_LIST and holds and holds != lang:     # you Generated another language meanwhile
                raise Wait(OTHER_LIST.format(LANGUAGE_NAMES.get(holds, holds))) from None
            raise _wait_or_needs(e, None) from None
        miner = out.get("anki_miner") or {}
        return {"words": out.get("words") or [], "file": subtitle, "subtitle": out.get("subtitle"),
                "profile": miner.get("profile"), "anki_miner": miner.get("app"),
                "absent": out.get("skipped") == "anki miner absent"}

    def fit(self, lang, job, pairing, video, subtitle):
        """-> (verdict, who, why, offset): `subtitle` is the library's copy (hato's sha256 is checked on it)."""
        return fit_check.fit(pairing, video, subtitle)

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
        try:
            setup = verbs._anki_miner_setup(self.loaded, lang, run_dir)
        except CliError as e:
            raise _wait_or_needs(e, "mining") from None
        if setup is None:
            raise Skip("Anki Miner isn't installed")
        mapping = self._mapping = setup[2]
        try:
            done = anki_miner.mine_batch(miner, lang, _tag(job), picked["video"], picked["subtitle"], words,
                                         mapping, self.loaded.get("connect_anki_miner_profile") or "Surasura",
                                         run_dir, self.url, attempt=attempt, wait=WAIT_S,
                                         subtitle_offset=float(picked.get("offset") or 0.0),
                                         expect_profile=picked.get("profile"))
        except anki_miner.AnkiMinerError as e:
            if e.kind == "profile-changed":
                raise Repick() from None
            if e.kind in ("crashed", "timeout"):
                return {"outcomes": [dict(_unsure(w)) for w in words], "app": None, "doubt": True}
            raise _miner_wait_or_needs(e) from None
        # in doubt: a crash or a timeout after the run (`error`), or a run Anki Miner itself says failed
        run = done.get("run") or {}
        doubt = bool(done.get("error")) or (bool(run) and not run.get("ok"))
        return {"outcomes": done.get("outcomes") or [], "app": done.get("app"), "doubt": doubt,
                "tag_pending": done.get("tag_pending") or []}

    def by_tag(self, lang, job, picked, words):
        """Which of `words` reached Anki, found by the job's tag (read-only) -> outcomes (made / uncertain)."""
        from app import anki_connect
        from app.connect import anki_miner, fields
        mapping = getattr(self, "_mapping", None)
        field = getattr(mapping, "word", None)
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
        except anki_connect.AnkiError:
            raise Wait(ANKI_CLOSED, resume="mining") from None

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
            raise _wait_or_needs(e, "filling") from None
        if isinstance(out.get("skipped"), str):         # absent, the preview off, Anki switched off: named
            raise Skip(out["skipped"])

    def order(self, lang, job):
        from app.cli import verbs
        from app.cli.contract import CliError
        ns = SimpleNamespace(lang=lang, wait=WAIT_S, auto=True, dry_run=False)
        try:
            out = verbs.junban(ns)
        except CliError as e:
            raise _wait_or_needs(e, "ordering") from None
        if out.get("skipped") == "junban absent":
            raise Skip("Junban isn't installed")
        if out.get("skipped"):              # 順 off, an update waiting, the list out of date: named, the re-sort owed
            raise Skip(str(out["skipped"]))


def _tag(job):
    """The job's name in its tag and run folder (the ledger's `tag`: unique past a lost ledger)."""
    return job.get("tag") or str(job["id"])


def _unsure(word):
    return {"word": word["word"], "reading": word["reading"], "outcome": "uncertain", "note_id": None,
            "line_start": word.get("line_start")}


def _wait_or_needs(error, resume):
    """A verb's CliError as the loop reads it: Anki or another writer busy → Wait (look again), else → Needs."""
    if error.code in ("anki-closed", "anki-busy", "busy", "anki-miner-busy"):
        say = {"anki-closed": ANKI_CLOSED, "anki-busy": REVIEWING, "anki-miner-busy": ANKI_MINER_OPEN}.get(
            error.code, error.message)
        return Wait(say, resume=resume)
    return Needs(error.code, error.message)


def _miner_wait_or_needs(error):
    if error.kind == "busy":
        return Wait(ANKI_MINER_OPEN, resume="mining")
    if error.kind == "writer-busy":
        return Wait(WRITER_BUSY, resume="mining")
    if error.kind == "reviewing":
        return Wait(REVIEWING, resume="mining")
    if error.kind == "anki-closed":
        return Wait(ANKI_CLOSED, resume="mining")
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


def beside(subtitle):
    """A video next to the subtitle with its name (`Show - 05.mkv` for `Show - 05.ja.srt`), on disk -> its path."""
    folder, name = os.path.split(subtitle)
    stem = os.path.splitext(name)[0]
    stems = [stem]
    base, tag = os.path.splitext(stem)
    if base and 1 < len(tag) <= 4:
        stems.append(base)                  # the language tag: .ja, .jpn, .zh
    try:
        names = {n.lower(): n for n in os.listdir(folder or ".")}
    except OSError:
        return None
    for s in stems:
        for ext in VIDEO_EXTENSIONS:
            found = names.get((s + ext).lower())
            if found and _on_disk(os.path.join(folder, found)):
                return os.path.join(folder, found)
    return None
