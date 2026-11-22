"""Connect's inbox (P2.1 row 2.1.4): the store's placement log, read as reader `connect`, turned into jobs.

- **The watermark** (✅ G1.1-2): the first time anything runs with Connect on, `register_reader("connect")` sets it to
  the log's last id; nothing logged before it is ever read, so nothing placed before Connect was switched on is mined.
  Switching Connect on again later moves it to the log's end (`library.switch_on`: the preview's switch, P3.1).
- **What makes a job:** an item that entered the top 20 (`entered_mine_line`: a person's drag, another program's
  `place`, a hato drop its rule places there, or — New arrivals off, 2.x's way — one landing at the top of NOW) and
  is still there, not mined (no receipt) and with no job yet → a `queued` job, recording who placed it (the event's
  `by`, ✅ G1.3-5). On 3.0 (New arrivals on, the default, D30) a hato drop waits in New arrivals until its rule or a
  person places it: landing there pushes nothing. **A first run waits for your yes** (Kantan-B2, a new tester
  2026-11-18: cards were made while setup's *Make cards for your first 20 episodes?* still asked): while that line
  is offered and unanswered and Connect never finished an episode from the log here (`first_run_waits`), an entry
  makes no job and no gap, and the loop mines none of the log's jobs (Kantan-B2b: an older version's, queued before
  the update) — the line's *Make cards* logs the top 20 itself; *Not now* is no yes (Sonic, 2026-11-19): it sets
  the log's jobs not started aside and the line stays until a yes. A back-fill registration logs no event for the item it registers
  (`register --backfill`), so it never makes one; with New arrivals off, items it pushes out of the top 20 log
  `left_mine_line`.
- **What drops one:** an item that left the top 20 (or was removed or finished) before its mining started. A job
  carrying an ask is never dropped for leaving the top 20 or for being finished (*Mine it too* asks on a finished
  item) — only when its item is removed or its ask undone; a level job is no longer kept anywhere (Kantan-MO: a raise
  mines nothing again; the runner drops one not started, `runner.LEVEL_DROPPED`).
- **Asks** (P4.1 row 4.1.3, C2 / C3): every look reads the store's asks (`mine_asked`) no receipt answers
  (`library.asked`): one no job holds yet → a job of kind `asked` (by `user`), or the item's open job carries it and
  goes first (*Mine now*); an ask made before the asks watermark (`asks_from:<lang>`, set at every off → on by
  `resume.turned_on`: Connect off) is never mined (G1.1-2). A ledger without one (Connect never turned on through a
  writer that sets it) counts every unanswered ask, and the look sets none (F-2, ⭐ P4.1-4: an ask the window made
  before Connect's first look is kicked for and mined, never passed). An
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
- **A show is one unit** (Michi-EO, Sonic 2026-11-17): when a part of a show gets a job (it entered the top 20, or
  you asked for it), every earlier part of that show in Current (`library.parts_before`: by season and episode — an
  earlier season is an earlier part) that isn't mined and never had a job is queued with it, kind `show`, by the same
  person and event, and mined ahead of it (`runner._ordered`; an ask still first): a show split by the switch-on —
  its first episodes in the top 20 before Connect was on, never logged — is mined from its first episode. A title
  with no episode numbers keeps Current's order; a part that had a job once (dropped, done) is never queued by it
  again; the cap holds them as any. Kept below the top 20 while in Current; one placed out of it is dropped.
"""
from app.connect import library
from app.connect.ledger import ASKED, LEVEL, NOT_STARTED, SHOW, Ledger, stamp_key

ENTERS = ("entered_mine_line",)
LEAVES = ("left_mine_line", "removed", "finished")


def keeps(job, event=None, current=None):
    """Does a job not started stay though its item is out of the top 20 (`event`: the item's latest leaving event, or
    None — the runner's look at the line)? A job carrying an ask — unless its item was removed (C3); a show's earlier
    part (Michi-EO) unless its item was finished or removed or left Current (`current`: False once it is elsewhere;
    None: not read). A level job only for new files, unless its item was finished or removed (Kantan-MO, F1: a
    raise mines no episode again)."""
    if job.get("asked_at") or job.get("kind") == ASKED:
        return event != "removed"
    if job.get("kind") == LEVEL:
        from app.connect import level
        if job.get("source") == level.BEST:
            return event != "removed"       # Kantan-SD: a Best word's episode, finished or not (its context)
        return job.get("source") == level.NEW_FILES and event not in ("removed", "finished")
    if job.get("kind") == SHOW:
        return event not in ("removed", "finished") and current is not False
    return False


def in_current(store, item_id):
    """Michi-EO: is the item in Current (NOW or Soon) now? False when gone or anywhere else."""
    return (store.item(item_id) or {}).get("tier") in ("now", "soon")


def _catch_up(store, ledger, language, item_id, by, event_id, queued, cache):
    """Michi-EO: the earlier parts of `item_id`'s show (`library.parts_before`) that never had a job, queued — kind
    `show`, by `by`, with its event — the first part first (into `queued`)."""
    for part in library.parts_before(store, item_id, cache):
        if not ledger.ever_had_job(language, part) and ledger.queue(
                language, part, by, event_id, store_id=library.store_id(store), kind=SHOW) is not None:
            queued.append(part)


def _waits_for_books(store, item_id):
    """Alpha 4 M1: a book or a text while Connect mines none (`library.waits_for`, `anki_miner.mines_now`): no gap
    names it, as no job is made of it (`runner._books_aside`). An audio title's episode is named as any: whether it
    waits is its video's to say, at the job's set-aside step (round 2 of the A4M1-3 review)."""
    from app.connect import anki_miner
    return library.waits_for(store.item(item_id) or {}) == "books" and not anki_miner.mines_now("books")


def _gone(store, ledger, language):
    """A gap's reconcile (no events to trust): {item id: "removed" / "finished"} for the jobs `keeps` would keep, as
    the store holds their items now. An item that no longer counts (W-1's rule, `library.counts`: Finished, or a
    stone's episode while *Keep studying watched episodes* is off) reads as finished: its level job is dropped as a
    finished one's, an ask kept."""
    out = {}
    for job in ledger.jobs(language, states=NOT_STARTED):
        if keeps(job):
            item = store.item(job["item_id"])
            if item is None or not library.counts(store, item):
                out[job["item_id"]] = "removed" if item is None else "finished"
            elif job.get("kind") == SHOW and item.get("tier") not in ("now", "soon"):
                out[job["item_id"]] = "finished"        # Michi-EO: a show's part is kept only while in Current
    return out


def _drop(ledger, language, item_id, event=None, store=None):
    """The item's job dropped as *left the top 20*, unless `keeps` says it stays -> dropped or not. `store`: a show's
    part's item is read for whether it is still in Current (Michi-EO)."""
    job = ledger.job(language, item_id)
    current = in_current(store, item_id) if store is not None and job is not None and job.get("kind") == SHOW else None
    if job is not None and job["state"] in NOT_STARTED and keeps(job, event, current):
        return False
    return ledger.drop(language, item_id, "left the top 20")


def first_run_waits(language, ledger):
    """Kantan-B2 (a new tester, 2026-11-18): is a first run still waiting for the learner's yes? Setup's line *Make
    cards for your first 20 episodes?* (`needs.FIRST_CARDS`) offered and not answered with a yes — its *Not now* is no
    yes (Kantan-B2b; Sonic 2026-11-19: "Nothing mines until the yes") — and Connect never finished an episode from the
    placement log in this language with cards (`Ledger.mined_from_log`: an install that already mined is never held
    by an old unanswered line; one whose jobs were only queued, or part-way, is). Then an episode entering the top 20
    (the learner arranging Current, a changed line) makes no job, and the loop mines no job the log queued
    (`runner._open_jobs`, `first_run_held`): the line's *Make cards* logs the top 20 itself. An ask (*Mine now*) is
    a yes of its own and is never held. The seen file held by a write: read again, and still unreadable the look fails
    (its transaction rolls back, the reader stays: the runner looks again), never read as no line."""
    from app.services import needs
    if not needs.first_cards_waiting(language):
        return False
    return not ledger.mined_from_log(language)


def first_run_held(job):
    """Kantan-B2b: is `job` one the first run's hold keeps from mining (`first_run_waits`)? One the placement log
    queued (its event) that carries no ask — an older version's, queued before the update. Your *Mine now* (an ask),
    a gap's *Make their cards* and a level raise carry no event, or an ask: never held."""
    return job.get("event_id") is not None and not job.get("asked_at") and job.get("kind") != ASKED


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
        shows = {}                              # Michi-EO: each title's parts, read once a look (`parts_before`)
        with ledger.transaction():
            if gap:
                for job in ledger.jobs(language, states=("queued", "waiting")):     # `drop` keeps one mining
                    if job["item_id"] not in in_line and _drop(ledger, language, job["item_id"],
                                                                 gone.get(job["item_id"])):
                        dropped.append(job["item_id"])
                missed = [i for i in line if library.mined_at(store, i) is None and not ledger.has_work(language, i)
                          and not _waits_for_books(store, i)]       # alpha 4 M1: never in the gap's card
                if missed and first_run_waits(language, ledger):
                    missed = []                 # Kantan-B2: setup's own line asks about them already
                waiting = ledger.gaps(language, unnoticed=True)
                if missed and not (waiting and waiting[-1]["items"] == missed):   # a re-read after a kill: once
                    ledger.add_gap(language, missed)
            else:
                latest = {}         # item -> (event id, kind, by), its last event in this read
                named = set()       # Michi-EO: every item an event names (a show's part placed out of Current)
                for event_id, item_id, kind, by, _explicit, _version, _at in rows:
                    named.add(item_id)
                    if kind in ENTERS or kind in LEAVES:
                        latest[item_id] = (event_id, kind, by)
                entered = []
                hold = None                     # Kantan-B2: read once, only when an entry could queue
                for item_id, (event_id, kind, by) in latest.items():
                    if item_id in in_line:
                        if kind in ENTERS and library.mined_at(store, item_id) is None:
                            if hold is None:
                                hold = first_run_waits(language, ledger)
                            if not hold and ledger.queue(language, item_id, by, event_id,
                                                         store_id=library.store_id(store)) is not None:
                                queued.append(item_id)
                                entered.append((item_id, by, event_id))
                    elif _drop(ledger, language, item_id, kind, store):
                        dropped.append(item_id)
                for item_id, by, event_id in entered:   # Michi-EO: then their shows' earlier parts no event queued
                    _catch_up(store, ledger, language, item_id, by, event_id, queued, shows)
                for job in ledger.jobs(language, states=NOT_STARTED) if named else ():
                    # Michi-EO: a show's part placed with no line crossed (below it: out of Current) goes as one left
                    item_id = job["item_id"]
                    if job.get("kind") == SHOW and item_id in named and item_id not in latest \
                            and item_id not in in_line and _drop(ledger, language, item_id, None, store):
                        dropped.append(item_id)
            _asks(store, language, ledger, found, queued, dropped, asked, shows)
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


def _asks(store, language, ledger, found, queued, dropped, asked, shows=None):
    """The store's asks into the ledger (inside the caller's transaction): a new ask → a job (`queued`, and `asked`)
    or the open job moved first (`asked`); an ask undone before mining → its job dropped (`dropped`) or put back. A
    new ask's job brings its show's earlier parts (Michi-EO, `_catch_up`: mined after it — the ask goes first).
    `found` None (the asks couldn't be read): nothing changes this look (AD-6)."""
    if found is None:
        return
    watermark = ledger.asks_from(language)  # None: every unanswered ask counts, and none is set here (F-2)
    for item_id, asked_at in library.unanswered(found):
        if watermark is not None and stamp_key(asked_at) < stamp_key(watermark):
            continue                        # asked while Connect was off: never mined (C1, IK B2)
        got = ledger.ask(language, item_id, asked_at, store_id=library.store_id(store))
        if got is not None:
            asked.append(item_id)
            if got[0] == "queued":
                queued.append(item_id)
                _catch_up(store, ledger, language, item_id, "user", None, queued, {} if shows is None else shows)
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
    read on the ledger opened read-only (never made). No watermark yet (or no ledger at all) is no line to fall
    before: the newest ask the ledger doesn't hold is unread, so the window's change kicks for it (F-2, as `consume`
    counts it)."""
    import os
    import pathlib
    import sqlite3
    from app.connect import ledger as book
    path = ledger_path or book.path()
    todo = library.unanswered(found)
    if not todo:
        return None
    if not os.path.exists(path):
        return todo[0][1]                   # no ledger: nothing recorded, no watermark (F-2)
    try:
        conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=1.0, isolation_level=None)
    except sqlite3.Error:
        return None
    try:
        watermark = book.asks_from_in(conn, language)
        for item_id, asked_at in todo:      # the newest first
            if watermark is not None and stamp_key(asked_at) < stamp_key(watermark):
                break
            if not book.ask_recorded_in(conn, language, item_id, asked_at):
                return asked_at
        return None
    finally:
        conn.close()
