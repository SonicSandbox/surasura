"""Connect's inbox (P2.1 row 2.1.4): the store's placement log, read as reader `connect`, turned into jobs.

- **The watermark** (✅ G1.1-2): the first time anything runs with Connect on, `register_reader("connect")` sets it to
  the log's last id; nothing logged before it is ever read, so nothing placed before Connect was switched on is mined.
  Switching Connect on again later moves it to the log's end (`library.switch_on`: the preview's switch, P3.1).
- **What makes a job:** an item that entered the top 20 (`entered_mine_line`: a person's drag, another program's
  `place`, a hato drop landing at the top of NOW) and is still there, not mined (no receipt) and with no job yet →
  a `queued` job, recording who placed it (the event's `by`, ✅ G1.3-5). A back-fill registration logs no event
  (`register --backfill`), so it never makes one.
- **What drops one:** an item that left the top 20 (or was removed or finished) before its mining started.
- **Crash-safe:** the jobs are committed first, then the reader advanced. A kill between the two re-reads the same
  events, and a re-read decides from the store as it is now: one open job per item, never two.
- **A gap** (the log pruned past the watermark, or a rebuild's new epoch): the events can't be trusted, so it
  reconciles instead — every job not started whose item isn't in the top 20 now is dropped — and queues nothing:
  never a mine of history (✅ P2.1-3). The top-20 episodes with no cards and no job are kept in the ledger's `gaps`
  (from Connect's last read to now), named once: the 2.x start-up notice, 3.0's *Needs you* (*Make their cards* ·
  *Leave them*). The reader then moves to the log's end as it was read, in the same read as the events, so nothing
  logged meanwhile is passed unread.
"""
from app.connect import library
from app.connect.ledger import Ledger

ENTERS = ("entered_mine_line",)
LEAVES = ("left_mine_line", "removed", "finished")


def consume(store, language, ledger=None):
    """Read the placement log once -> {"queued": [item ids], "dropped": [item ids], "reconciled": bool, "read": n}."""
    library.ensure_reader(store)
    own = ledger is None
    ledger = ledger or Ledger()
    try:
        with store._reading():                  # one snapshot: the events, the log's end and the top 20 agree
            rows, gap = store.read_events(library.READER)
            end = library.log_seq(store)
            line = library.mine_line(store)
        in_line = set(line)
        queued, dropped = [], []
        missed = []
        with ledger.transaction():
            if gap:
                for job in ledger.jobs(language, states=("queued", "waiting")):     # `drop` keeps one mining
                    if job["item_id"] not in in_line and ledger.drop(language, job["item_id"], "left the top 20"):
                        dropped.append(job["item_id"])
                missed = [i for i in line if library.mined_at(store, i) is None and not ledger.has_work(language, i)]
                waiting = ledger.gaps(language, unnoticed=True)
                if missed and not (waiting and waiting[-1]["items"] == missed):   # a re-read after a kill: once
                    ledger.add_gap(language, missed)
            else:
                latest = {}         # item -> (event id, kind, by), its last event in this read
                for event_id, item_id, kind, by, _explicit, _version, _at in rows:
                    if kind in ENTERS or kind in LEAVES:
                        latest[item_id] = (event_id, kind, by)
                for item_id, (event_id, kind, by) in latest.items():
                    if item_id in in_line:
                        if kind in ENTERS and library.mined_at(store, item_id) is None \
                                and ledger.queue(language, item_id, by, event_id,
                                                 store_id=library.store_id(store)) is not None:
                            queued.append(item_id)
                    elif ledger.drop(language, item_id, "left the top 20"):
                        dropped.append(item_id)
            if rows or gap or ledger.last_read(language) is None:   # an idle look writes nothing (charter S19)
                ledger.mark_read(language)
        last = max([r[0] for r in rows] + ([end] if gap else []), default=None)
        if last is not None:
            store.advance_reader(library.READER, last)
        return {"queued": queued, "dropped": dropped, "reconciled": bool(gap), "read": len(rows), "missed": missed}
    finally:
        if own:
            ledger.close()


def pending(store):
    """Has the log anything Connect hasn't read? (a look, no write: the last check before Connect exits)"""
    if not library.has_reader(store):
        return False
    return library.log_seq(store) > int(store.meta().get(f"reader:{library.READER}", 0))
