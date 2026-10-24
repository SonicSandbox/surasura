"""The window's short writes to Connect's ledger that start work (P4.1), beside `status.mark_seen` and `status.dismiss`.

- `mine_anyway(language, need_id)` (row 4.1.9; G1.3-6, 06-edges E16): *Mine anyway* on a *Needs you* entry that says
  an episode isn't timed to its video — the entry fixed, the item's job queued again with `picked.forced`, so its next
  pick mines it untimed (`runner._fit`: tsubasa isn't asked, no shift; logged *mined anyway: not timed*). The choice
  holds for the pairing it was made on: a pairing changed since (hato re-timed it, a new subtitle) is picked again and
  checked again, as any. On hato's name-only pairings (`verdict: untimed`) the entry carries `feed.UNTIMED_WARNING`.
- `make_cards(language, gap_id)` (P4.1 WF; IK D-1 lean (a), P2.1-3): *Make their cards* on a *Needs you* gap — the
  gap's episodes queued as Connect's ordinary jobs (kind `mine`, by `user`), never an ask: a word Connect ever made,
  a deleted card's included, is never made again (`library.made_words_for`, N15 / G1.3-4); the gap marked noticed.

- `stop(language, job_id)` (laptop round 8 #47): *Stop* on the episode Connect is making cards for: the press
  recorded at once (`Ledger.ask_stop`) and Connect woken (`kick.wake`). Connect stops the job at its next safe
  point: before its next step, or Anki Miner's batch cancelled within a second, every card it made kept, whole and
  recorded (what reached Anki is found by the job's tag: never half-written, never made twice). The episode then waits
  (`runner.STOPPED_BY_YOU`) until you press *Mine now*; Connect goes on with the next one. Once its cards are being
  filled and ordered (seconds) the job finishes (`stoppable`).

Each runs on the window's worker, one short ledger transaction; the caller kicks Connect after (`kick.kick`). No
ledger → nothing written (the window never makes one). Light: the standard library and the ledger.
"""
import json
import os

from app.connect import ledger as book


def mine_anyway(language, need_id, path=None):
    """*Mine anyway* -> True when the job was queued again; False (nothing written) when there's no ledger, the entry
    isn't an open *not timed* one of this language, or its item has no open job any more (dropped, finished)."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    with book.Ledger(path) as ledger, ledger.transaction():
        row = ledger.conn.execute("SELECT item_id, job_id FROM needs WHERE id = ? AND language = ? AND kind = "
                                  "'not-timed' AND fixed_at IS NULL", (need_id, language)).fetchone()
        if row is None or row[0] is None:
            return False
        item_id, job_id = row
        job = ledger.job_by_id(job_id) if job_id is not None else None
        if job is None or job.get("item_id") != item_id or job.get("state") not in book.OPEN:
            job = ledger.job(language, item_id)
        if job is None or job.get("state") not in book.NOT_STARTED:
            return False                # dropped, finished, or past its pick already: nothing of it to force
        picked = ledger.picked(job["id"]) or {}
        picked["forced"] = True
        ledger.set_state(job["id"], "queued", picked=picked)        # its reason and resume step cleared: picks anew
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE id = ?", (book._now(), need_id))
    return True


def make_cards(language, gap_id, path=None, store_id=None):
    """*Make their cards* -> how many of the gap's episodes were queued (0: none left to queue — each has an open job
    or was mined); False (nothing written) when there's no ledger, no such gap of this language, or the library's
    identity can't be read. Each episode with no open job and never mined (`ledger.mined`) gets an ordinary `mine` job
    stamped with the library's identity (`store_id`: read from the library, read-only, unless given — a job without
    one is never mined into this library, `runner._job`); the gap marked noticed."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    store_id = store_id or _store_id(language)
    if not store_id:
        return False
    queued = 0
    with book.Ledger(path) as ledger, ledger.transaction():
        row = ledger.conn.execute("SELECT items FROM gaps WHERE id = ? AND language = ?", (gap_id, language)).fetchone()
        if row is None:
            return False
        for item_id in dict.fromkeys(json.loads(row[0] or "[]")):
            job = ledger.job(language, item_id)
            if (job is not None and job.get("state") in book.OPEN) or ledger.mined(language, item_id):
                continue
            if ledger.queue(language, item_id, "user", None, store_id) is not None:
                queued += 1
        ledger.mark_noticed([gap_id])
    return queued


def stoppable(state, resume=None, progress=None):
    """Can a job in `state` (waiting at `resume`; mining at `progress`) still be stopped (the window offers *Stop* only
    then)? The ledger's one rule (`ledger.stoppable`): until its cards are made — never once their clips are named."""
    return book.stoppable(state, resume, progress)


def stop(language, job_id, path=None):
    """*Stop* -> True when the press was recorded (the job is open, of this language, not yet past mining); False
    (nothing written) otherwise. Wakes a running Connect so it acts within a second or two, not at its next look: a
    program the job waits on is ended within a second (tsubasa's check, Anki Miner's look-ups; laptop round 9 #56) or
    cancelled (Anki Miner's run, its cards so far kept)."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    with book.Ledger(path) as ledger:
        job = ledger.job_by_id(job_id)
        if job is None or job.get("language") != language or not stoppable(job.get("state"), job.get("resume"),
                                                                           job.get("progress")):
            return False
        if not ledger.ask_stop(job_id):
            return False
    from app.connect import kick
    kick.wake()
    return True


def _store_id(language):
    """The library's identity (`library.store_id`), read-only (`mode=ro`: never made or written), or None."""
    from app.connect import window_link
    conn = window_link._store_ro(language)
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'store_id'").fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()
