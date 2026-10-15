"""Connect's inbox (P2.1 row 2.1.4): the store's placement log, read as reader `connect`, turned into jobs.

- **The watermark** (✅ G1.1-2): the first time anything runs with Connect on, `register_reader("connect")` sets it to
  the log's last id; nothing logged before it is ever read, so nothing placed before Connect was switched on is mined.
  Switching Connect on again later moves it to the log's end (`library.switch_on`: the preview's switch, P3.1).
- **What makes a job:** an item that entered the top 20 (`entered_mine_line`: a person's drag, another program's
  `place`, a hato drop its rule places there, or — New arrivals off, 2.x's way — one landing at the top of NOW) and
  is still there, not mined (no receipt) and with no job yet → a `queued` job, recording who placed it (the event's
  `by`, ✅ G1.3-5). On 3.0 (New arrivals on, the default, D30) a hato drop waits in New arrivals until its rule or a
  person places it: landing there pushes nothing. A back-fill registration logs no event for the item it registers
  (`register --backfill`), so it never makes one; with New arrivals off, items it pushes out of the top 20 log
  `left_mine_line`.
- **What drops one:** an item that left the top 20 (or was removed or finished) before its mining started. A job
  carrying an ask is never dropped for leaving the top 20 or for being finished (*Mine it too* asks on a finished
  item) — only when its item is removed or its ask undone; a level job beyond the line (`level.BEYOND_LINE`, C4) is
  never dropped for leaving the line, still by a `finished` or `removed` event (`keeps`).
- **Asks** (P4.1 row 4.1.3, C2 / C3): every look reads the store's asks (`mine_asked`) no receipt answers
  (`library.asked`): one no job holds yet → a job of kind `asked` (by `user`), or the item's open job carries it and
  goes first (*Mine now*); an ask made before the asks watermark (`asks_from:<lang>`: Connect off) is never mined —
  a ledger without one sets it at this first look, so nothing asked before Connect read asks is mined (G1.1-2). An
  ask undone (the store's undo) before its job's mining started → the job it made dropped (*left: ask undone*), one
  it moved back in its place. Any ending uses an ask up (the ledger keeps the job's `asked_at`, IK S4).
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
from app.connect.ledger import ASKED, LEVEL, NOT_STARTED, Ledger, stamp, stamp_key

ENTERS = ("entered_mine_line",)
LEAVES = ("left_mine_line", "removed", "finished")


def keeps(job, event=None):
    """Does a job not started stay though its item is out of the top 20 (`event`: the item's latest leaving event, or
    None — the runner's look at the line)? A job carrying an ask — unless its item was removed — and, on the 3.0 line,
    a level job beyond the line — unless its item was finished or removed (C3, C4)."""
    if job.get("asked_at") or job.get("kind") == ASKED:
        return event != "removed"
    if job.get("kind") == LEVEL:
        from app.connect import level
        return level.BEYOND_LINE and event not in ("removed", "finished")
    return False


def _gone(store, ledger, language):
    """A gap's reconcile (no events to trust): {item id: "removed" / "finished"} for the jobs `keeps` would keep, as
    the store holds their items now."""
    out = {}
    for job in ledger.jobs(language, states=NOT_STARTED):
        if keeps(job):
            item = store.item(job["item_id"])
            if item is None or item.get("tier") == "graduated":
                out[job["item_id"]] = "removed" if item is None else "finished"
    return out


def _drop(ledger, language, item_id, event=None):
    """The item's job dropped as *left the top 20*, unless `keeps` says it stays -> dropped or not."""
    job = ledger.job(language, item_id)
    if job is not None and job["state"] in NOT_STARTED and keeps(job, event):
        return False
    return ledger.drop(language, item_id, "left the top 20")


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
            found = library.asks(store)
            gone = _gone(store, ledger, language) if gap else {}
        in_line = set(line)
        queued, dropped, asked = [], [], []
        missed = []
        with ledger.transaction():
            if gap:
                for job in ledger.jobs(language, states=("queued", "waiting")):     # `drop` keeps one mining
                    if job["item_id"] not in in_line and _drop(ledger, language, job["item_id"],
                                                                 gone.get(job["item_id"])):
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
                    elif _drop(ledger, language, item_id, kind):
                        dropped.append(item_id)
            _asks(store, language, ledger, found, queued, dropped, asked)
            if rows or gap or ledger.last_read(language) is None:   # an idle look writes nothing (charter S19)
                ledger.mark_read(language)
        last = max([r[0] for r in rows] + ([end] if gap else []), default=None)
        if last is not None:
            store.advance_reader(library.READER, last)
        return {"queued": queued, "dropped": dropped, "reconciled": bool(gap), "read": len(rows), "missed": missed,
                "asked": asked}
    finally:
        if own:
            ledger.close()


def _asks(store, language, ledger, found, queued, dropped, asked):
    """The store's asks into the ledger (inside the caller's transaction): a new ask → a job (`queued`, and `asked`)
    or the open job moved first (`asked`); an ask undone before mining → its job dropped (`dropped`) or put back."""
    watermark = ledger.asks_from(language)
    if watermark is None:                   # the first look that reads asks: nothing asked before it is mined
        watermark = stamp()
        ledger.set_asks_from(language, watermark)
    for item_id, asked_at in library.unanswered(found):
        if stamp_key(asked_at) < stamp_key(watermark):
            continue                        # asked while Connect was off: never mined (C1, IK B2)
        got = ledger.ask(language, item_id, asked_at, store_id=library.store_id(store))
        if got is not None:
            asked.append(item_id)
            if got[0] == "queued":
                queued.append(item_id)
    for job in ledger.jobs(language, states=NOT_STARTED):
        if not job.get("asked_at") or not ledger._not_started(job["id"]):
            continue                        # no ask, or past its start: it finishes (02 §2)
        now = (found.get(job["item_id"]) or (None, None))[0]
        if now is not None and stamp_key(now) >= stamp_key(job["asked_at"]):
            continue                        # the ask stands (a newer one moved it already)
        if ledger.unask(job["id"]) == "dropped":
            dropped.append(job["item_id"])


def pending(store):
    """Has the log anything Connect hasn't read, or the store an ask it hasn't (P4.1)? (a look, no write: the last
    check before Connect exits)"""
    if not library.has_reader(store):
        return False
    if library.log_seq(store) > int(store.meta().get(f"reader:{library.READER}", 0)):
        return True
    return newest_unread_ask(store.language, library.asks(store)) is not None


def newest_unread_ask(language, found, ledger_path=None):
    """The newest ask (its stamp) no receipt answers, made since the asks watermark and held by no job yet, or None —
    read on the ledger opened read-only (never made: no ledger, or no watermark yet, is nothing unread — the first
    look sets the watermark past every ask there is)."""
    import os
    import pathlib
    import sqlite3
    from app.connect import ledger as book
    path = ledger_path or book.path()
    todo = library.unanswered(found)
    if not todo or not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=1.0, isolation_level=None)
    except sqlite3.Error:
        return None
    try:
        watermark = book.asks_from_in(conn, language)
        if watermark is None:
            return None
        for item_id, asked_at in todo:      # the newest first
            if stamp_key(asked_at) < stamp_key(watermark):
                break
            if not book.ask_recorded_in(conn, language, item_id, asked_at):
                return asked_at
        return None
    finally:
        conn.close()
