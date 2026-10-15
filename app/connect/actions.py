"""The window's short writes to Connect's ledger that start work (P4.1), beside `status.mark_seen` and `status.dismiss`.

- `mine_anyway(language, need_id)` (row 4.1.9; G1.3-6, 06-edges E16): *Mine anyway* on a *Needs you* entry that says
  an episode isn't timed to its video — the entry fixed, the item's job queued again with `picked.forced`, so its next
  pick mines it untimed (`runner._fit`: tsubasa isn't asked, no shift; logged *mined anyway: not timed*). The choice
  holds for the pairing it was made on: a pairing changed since (hato re-timed it, a new subtitle) is picked again and
  checked again, as any. On hato's name-only pairings (`verdict: untimed`) the entry carries `feed.UNTIMED_WARNING`.

Each runs on the window's worker, one short ledger transaction; the caller kicks Connect after (`kick.kick`). No
ledger → nothing written (the window never makes one). Light: the standard library and the ledger.
"""
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
