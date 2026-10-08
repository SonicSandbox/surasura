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
    try:
        while True:
            summary["looks"] += 1
            outside = work = False
            for lang in languages:
                if steps.update_staged():
                    summary["stopped"] = STOPPED_FOR_UPDATE
                    return summary
                steps.consume(lang, ledger)
                jobs = ledger.open_jobs(lang)
                if not jobs:
                    continue
                work = True
                outside |= _language(steps, ledger, lang, jobs, prepared, summary["languages"][lang])
                if steps.update_staged():           # staged while its jobs ran: stop at this step boundary
                    summary["stopped"] = STOPPED_FOR_UPDATE
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


def _language(steps, ledger, lang, jobs, prepared, out):
    """Every open job of one language, once -> True when one waits on something outside Connect (look again)."""
    if lang != "ja":            # E24: Japanese first, until Anki Miner and Connect say Chinese works
        for job in jobs:
            _wait(ledger, job, Wait(CHINESE, look=False, resume=_resume_of(job)), out)
        return False
    wait = _blocked(steps, lang, None)
    line = store_now = None
    if wait is None:
        try:                                # the store answers first: never an empty top 20 for a busy one
            line, store_now = steps.mine_line(lang), steps.store_id(lang)
        except Wait as w:
            wait = w
        except Needs as n:
            if ledger.need(lang, n.kind, n.say):
                out["needs"].append(n.say)
            wait = Wait(n.say, look=False)
    if wait is None and lang not in prepared:
        try:
            steps.prepare(lang, ledger)
            prepared.add(lang)
        except Wait as w:
            wait = w
        except Needs as n:
            if ledger.need(lang, n.kind, n.say):
                out["needs"].append(n.say)
            wait = Wait(n.say, look=False)
    if wait is not None:
        for job in jobs:
            _wait(ledger, job, Wait(wait.reason, wait.look, _resume_of(job)), out)
        return wait.look
    outside = False
    for job in _ordered(jobs, line):
        try:
            _job(steps, ledger, lang, job, store_now, set(line), out)
        except Wait as w:
            _wait(ledger, job, w, out)
            outside |= w.look
        except Needs as n:
            if ledger.need(lang, n.kind, n.say, item_id=job["item_id"], job_id=job["id"]):
                out["needs"].append(n.say)
            _wait(ledger, job, Wait(n.say, look=False, resume=_resume_of(ledger.job_by_id(job["id"]))), out)
        except Exception as e:              # R15: a fault of one job never ends the run nor hides it
            log.exception("Connect's job %s stopped on an error", job["id"])
            say = f"Connect stopped on an error while making an episode's cards ({type(e).__name__}): {e}"
            if ledger.need(lang, "error", say, item_id=job["item_id"], job_id=job["id"]):
                out["needs"].append(say)
            _wait(ledger, job, Wait(say, look=False, resume=_resume_of(ledger.job_by_id(job["id"]))), out)
        if steps.update_staged():
            break
    return outside


def _blocked(steps, lang, resume):
    """`steps.blocked` as a Wait resuming at `resume` (it answers a reason, or a Wait of its own), or None."""
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


def _wait(ledger, job, wait, out):
    """The job waits with one reason. Before mining it keeps no step to resume at: it picks again from the list as it
    is then (so a parked job never holds the level raise's look, `ledger.in_flight`)."""
    resume = None if wait.resume in BEFORE_MINING else wait.resume
    ledger.set_state(job["id"], "waiting", reason=wait.reason, resume=resume)
    out["waiting"][job["item_id"]] = wait.reason


def _job(steps, ledger, lang, job, store_now, line, out):
    """One job from where it stands to `done` (or a finished state). Raises Wait / Needs."""
    jid, item_id = job["id"], job["item_id"]
    step = _resume_of(job)
    foreign = bool(job.get("store_id") and store_now and job["store_id"] != store_now)
    if foreign and step in BEFORE_MINING:
        ledger.set_state(jid, "dropped", reason="the library was set up again")
        out["dropped"].append(item_id)
        return
    if not job.get("store_id") and step in BEFORE_MINING:
        # queued before SCHEMA 3 (the 2.x preview's inbox): which library it came from isn't known, so it is never
        # mined into this one (P2.1 adversary #12) — named as a gap, as a read of the log Connect can't trust is
        ledger.set_state(jid, "dropped", reason="queued before Connect kept its library's identity")
        with ledger.transaction():
            ledger.add_gap(lang, [item_id])
        out["dropped"].append(item_id)
        return
    if step in BEFORE_MINING and item_id not in line:
        ledger.set_state(jid, "dropped", reason="left the top 20")
        out["dropped"].append(item_id)
        return
    try:
        for _ in range(3):          # a profile or pairing that changed since the pick: picked again (at most twice)
            try:
                if step in (None, "picking"):
                    if _pick(steps, ledger, lang, job) is None:
                        out["done"].append(item_id)
                        return
                    step = "fit-check"
                if step == "fit-check":
                    _fit(steps, ledger, lang, job)
                    step = "mining"
                if step == "mining":
                    _mine(steps, ledger, lang, job, record=not foreign)
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


def _pick(steps, ledger, lang, job):
    """The pick step -> what it picked, or None when it found no word (the job done with nothing to make)."""
    jid = job["id"]
    ledger.set_state(jid, "picking")
    video = steps.video(lang, job)
    if video is None:
        raise Wait(NO_VIDEO, look=False)
    pairing = steps.pairing(lang, job)
    got = steps.pick(lang, job, video)
    picked = {"words": got.get("words") or [], "file": got.get("file"), "subtitle": got.get("subtitle"),
              "video": video, "pairing": fit_check.version(pairing), "profile": got.get("profile"),
              "anki_miner": got.get("anki_miner")}
    if got.get("absent"):
        ledger.set_state(jid, "skipped", reason="Anki Miner isn't installed", picked=picked,
                         skipped={"mining": "Anki Miner isn't installed"})
        raise _Finished("skipped")
    if not picked["words"]:
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
    verdict, _who, why = steps.fit(lang, job, pairing, picked.get("video"), picked.get("file"))
    if verdict == fit_check.RETRY:
        raise Wait(why)                     # tsubasa couldn't answer this time: asked again at the next look
    if verdict != fit_check.TIMED:
        title = steps.title(lang, job)
        raise Needs("not-timed", f"{title}: {why}" if title else why)
    ledger.set_state(jid, "mining")


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
        last = (ledger.batches(jid) or [None])[-1]
        if last is not None and last["state"] == "running":
            # killed (or crashed) mid-batch: what reached Anki is found by the job's tag first, never mined twice
            found = steps.by_tag(lang, job, picked, [w for w in words if _outcome(ledger, jid, w) in UNSETTLED])
            ledger.end_batch(jid, last["attempt"], "uncertain", _enriched(found, by_key))
            _count_failure(ledger, jid)
        todo = [w for w in words if _outcome(ledger, jid, w) in UNSETTLED]
        if not todo:
            break
        doubt = any(_outcome(ledger, jid, w) == "uncertain" for w in todo)
        if doubt and _failures(ledger, jid) >= 2:
            _fail_mining(steps, ledger, lang, job)
        wait = _blocked(steps, lang, "mining")
        if wait is not None:
            raise wait
        attempt = (ledger.job_by_id(jid).get("attempt") or 0) + 1
        ledger.set_state(jid, "mining")
        ledger.start_batch(jid, attempt, steps.run_dir(job))
        try:
            got = steps.mine(lang, job, picked, todo, attempt)
        except Wait as w:
            ledger.end_batch(jid, attempt, "refused")
            w.resume = "mining"
            raise
        except Repick:
            ledger.end_batch(jid, attempt, "refused")
            raise
        except Needs:
            ledger.end_batch(jid, attempt, "refused")
            raise
        except Skip as s:
            ledger.end_batch(jid, attempt, "refused")
            ledger.set_state(jid, "skipped", reason=s.why, skipped={"mining": s.why})
            raise _Finished("skipped") from None
        if got.get("doubt") or any(o["outcome"] == "uncertain" for o in got["outcomes"]):
            # a word Anki Miner doesn't account for may be in Anki: found by the job's tag first, never sent twice
            found = steps.by_tag(lang, job, picked, [w for w in todo if _row(got, w) in UNSETTLED])
            got["outcomes"] = _merge(got["outcomes"], found)
        state = "uncertain" if any(o["outcome"] == "uncertain" for o in got["outcomes"]) else "done"
        ledger.end_batch(jid, attempt, state, _enriched(got["outcomes"], by_key), anki_miner=got.get("app"))
        if got.get("doubt"):
            _count_failure(ledger, jid)     # only a run that crashed or timed out: an unknown status is no crash
    left = [w for w in words if _outcome(ledger, jid, w) in UNSETTLED]
    if _failures(ledger, jid) >= 2 and any(_outcome(ledger, jid, w) == "uncertain" for w in left):
        _fail_mining(steps, ledger, lang, job)     # a second crash in the last try
    if left:                                # Anki Miner never accounted for them, three times: named, not mined
        never = f"{len(left)} words Anki Miner never made or turned down"
        ledger.set_state(jid, "mining", skipped=_skipped(ledger, jid, "mining", never))
    made = {}
    for o in ledger.outcomes(jid):
        if o["outcome"] == "made" and o["note_id"] is not None:
            made.setdefault(o["word"], []).append(o["note_id"])
    if record:
        try:
            steps.record(lang, job, made, _now() if job.get("kind") != "level" else None, f"{jid}")
        except Wait as w:
            w.resume = "mining"
            raise
    ledger.set_state(jid, "filling")


def _fail_mining(steps, ledger, lang, job):
    """A second failure (E11): the job `failed`, named once in Needs you; nothing is tried a third time."""
    ledger.set_state(job["id"], "failed", reason="Anki Miner stopped twice while making its cards")
    ledger.need(lang, "mine-failed", f"{steps.title(lang, job) or 'An episode'}: Anki Miner stopped twice while "
                "making its cards. Look in Anki for the cards it made.", item_id=job["item_id"], job_id=job["id"])
    raise _Finished("failed")


def _outcome(ledger, jid, word):
    row = ledger.conn.execute("SELECT outcome FROM outcomes WHERE job_id = ? AND word = ? AND reading = ?",
                              (jid, word["word"], word["reading"])).fetchone()
    return row[0] if row else None


def _row(got, word):
    key = (word["word"], word["reading"])
    return next((o["outcome"] for o in got["outcomes"] if (o["word"], o["reading"]) == key), None)


def _merge(outcomes, found):
    better = {(o["word"], o["reading"]): o for o in found if o["outcome"] == "made"}
    return [better.get((o["word"], o["reading"]), o) if o["outcome"] in UNSETTLED else o for o in outcomes]


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
    try:
        steps.fill(lang, job, ids)
    except Wait as w:
        w.resume = "filling"
        raise
    except Skip as s:
        ledger.set_state(jid, "ordering", skipped=_skipped(ledger, jid, "filling", s.why))
        return
    except Needs as n:
        ledger.need(lang, n.kind, n.say, item_id=job["item_id"], job_id=jid)
        ledger.set_state(jid, "ordering", skipped=_skipped(ledger, jid, "filling", n.say))
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
        w.resume = "ordering"
        raise
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
        from app.connect import library
        store = library.open_store(lang)
        if store is None:
            return None
        with store:
            item = store.item(job["item_id"]) or {}
        entry = item.get("entry") or {}
        return entry.get("title") or (os.path.basename(item.get("rel_path") or "") or None)

    def pairing(self, lang, job):
        from app.connect import library
        store = library.open_store(lang)
        if store is None:
            return None
        with store:
            return library.pairing_of(store, job["item_id"])

    def subtitle(self, lang, job):
        from app.connect import library
        from app.path_utils import get_data_path
        store = library.open_store(lang)
        if store is None:
            return None
        with store:
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
        return anki_session.waiting(self.url, self.loaded)

    def prepare(self, lang, ledger):
        """Once a run, per language: the session's sync, one known-sync, one Generate when the list isn't current."""
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import anki_session
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

    def run_dir(self, job):
        from app.cli.verbs import _connect_folder
        return os.path.join(_connect_folder(), "runs", str(job["id"]))

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
            raise _wait_or_needs(e, None) from None
        miner = out.get("anki_miner") or {}
        return {"words": out.get("words") or [], "file": subtitle, "subtitle": out.get("subtitle"),
                "profile": miner.get("profile"), "anki_miner": miner.get("app"),
                "absent": out.get("skipped") == "anki miner absent"}

    def fit(self, lang, job, pairing, video, subtitle):
        return fit_check.check(pairing, video, subtitle)

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
            done = anki_miner.mine_batch(miner, lang, str(job["id"]), picked["video"], picked["subtitle"], words,
                                         mapping, self.loaded.get("connect_anki_miner_profile") or "Surasura",
                                         run_dir, self.url, attempt=attempt, wait=WAIT_S,
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
        return {"outcomes": done.get("outcomes") or [], "app": done.get("app"), "doubt": doubt}

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
            return anki_miner.uncertain_by_tag(self.url, str(job["id"]), words, field)
        except anki_connect.AnkiError:
            raise Wait(ANKI_CLOSED, resume="mining") from None

    def fill(self, lang, job, note_ids):
        from app.cli import verbs
        from app.cli.contract import CliError
        ns = SimpleNamespace(lang=lang, wait=WAIT_S, notes=",".join(str(n) for n in note_ids), tag=None,
                             dry_run=False)
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
