"""Connect's ledger (P1.5 02-data-model §1 N4, §3): `<local data>/connect/ledger.sqlite`, per install, never in the
library or a cloud folder (K58, RD-D15). It holds work in flight — the jobs, one per item mined — and nothing that
lasts: lose it and Connect rebuilds what it needs from the store and Anki's tags, and mines nothing twice.

P2.1 builds the jobs table the inbox fills (`queued`, `dropped`); the rest of a job's life (`waiting` → … → `done`,
word outcomes, undo records) is P2.4's, on the same table. Short transactions, standard library `sqlite3`, like the
store.

P2.2 (SCHEMA 2, a SCHEMA 1 ledger upgraded in place): a job's `kind` — `mine` (an item's first cards) or `level` (the
newly listed words of an item already mined, HC-N38) — and its `words` (a level job's `[[word, reading], …]`; None: the
whole list); the list Connect last looked at (`listed`, with its run signature), so a level raise is told from the
first look; and `resort_due`, a re-sort owed after the list moved (the runner's ordering step pays it, P2.4).

P2.4 (SCHEMA 3, a SCHEMA 2 ledger upgraded in place by added columns and tables; one newer than this Surasura reads is
refused, never used — `TooNew`, P2.2 adversary #12): the runner's whole job (02 §2): its states, each saved before and
after its step (`set_state`; a job waiting mid-way keeps the step it resumes at, `resume`); the store it was queued
from (`store_id`: a store set up again can't mine another item under the same id, P2.1 adversary #12); what its pick
chose (`picked`, with the pairing's version and the Anki Miner profile it picked for); its batches (N5: the run folder,
the attempt, the Anki Miner that ran it); each word's outcome (N6: word, spelling, reading, its line's start, end and
sentence, the predicted class, the outcome, the note id — ✅ D1: the line stays here); the undo record (N9: the note ids
a job made, `undo_record`); and what Connect needs you for (`needs`: each named once, P2.5 shows them).
"""
import datetime
import json
import os
import sqlite3

SCHEMA = 3
# A job's states (02 §2). Open = not finished one way or the other; not started = still droppable.
OPEN = ("queued", "waiting", "picking", "fit-check", "mining", "filling", "ordering")
NOT_STARTED = ("queued", "waiting")
IN_FLIGHT = tuple(s for s in OPEN if s not in NOT_STARTED)
DONE = "done"
DROPPED = "dropped"
FINISHED = (DONE, DROPPED, "failed", "undone", "skipped")
STATES = OPEN + FINISHED
# The steps a job waiting mid-way resumes at (`resume`): before mining it can still be dropped (02 §2: an item that
# leaves the top 20 before mining; once mining has started, it finishes).
BEFORE_MINING = (None, "picking", "fit-check")
# A job's kinds (P2.2): an item's first cards, or the newly listed words of one already mined.
MINE, LEVEL = "mine", "level"

_SCHEMA_SQL = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      language TEXT NOT NULL,
      item_id INTEGER NOT NULL,
      state TEXT NOT NULL,
      reason TEXT,
      source TEXT,
      event_id INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'mine',
      words TEXT)""",
    # One open job per item (N4): a re-read of the same events can never queue it twice
    "CREATE UNIQUE INDEX IF NOT EXISTS one_open_job ON jobs (language, item_id) WHERE state IN ({})".format(
        ", ".join(f"'{s}'" for s in OPEN)),
    # A gap in the placement log (✅ P2.1-3): the top-20 episodes with no cards when Connect lost track, from its last
    # read (`since`) to the gap's read (`until`) — never mined; named once (2.x: the start-up notice; 3.0: Needs you)
    """CREATE TABLE IF NOT EXISTS gaps (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      language TEXT NOT NULL,
      since TEXT,
      until TEXT NOT NULL,
      items TEXT NOT NULL,
      noticed INTEGER NOT NULL DEFAULT 0)""",
    # The list Connect last looked at (P2.2): its keys, the pick's identity (Word, Reading); its run signature is in
    # meta (`listed:<lang>`). A level raise is the words listed now and not then.
    """CREATE TABLE IF NOT EXISTS listed (
      language TEXT NOT NULL,
      word TEXT NOT NULL,
      reading TEXT NOT NULL,
      PRIMARY KEY (language, word, reading))""",
)
# SCHEMA 1 -> 2 -> 3: the columns P2.2 and P2.4 add to a ledger made before them (the table above has P2.2's).
_ADDED_COLUMNS = (("kind", "TEXT NOT NULL DEFAULT 'mine'"), ("words", "TEXT"),
                  ("store_id", "TEXT"), ("resume", "TEXT"), ("picked", "TEXT"),
                  ("attempt", "INTEGER NOT NULL DEFAULT 0"), ("failures", "INTEGER NOT NULL DEFAULT 0"),
                  ("skipped", "TEXT"))
# P2.4's tables (made IF NOT EXISTS, like the rest)
_RUNNER_SQL = (
    # N5, one Anki Miner call: `state` running · done · uncertain · failed
    """CREATE TABLE IF NOT EXISTS batches (
      job_id INTEGER NOT NULL,
      attempt INTEGER NOT NULL,
      run_dir TEXT NOT NULL,
      anki_miner TEXT,
      state TEXT NOT NULL,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      PRIMARY KEY (job_id, attempt))""",
    # N6, one word's outcome (made · duplicate · not_found · no_definition · uncertain · …), its line kept here (D1)
    """CREATE TABLE IF NOT EXISTS outcomes (
      job_id INTEGER NOT NULL,
      word TEXT NOT NULL,
      reading TEXT NOT NULL,
      orth TEXT,
      line_start REAL,
      line_end REAL,
      sentence TEXT,
      predicted TEXT,
      outcome TEXT NOT NULL,
      note_id INTEGER,
      attempt INTEGER NOT NULL,
      PRIMARY KEY (job_id, word, reading))""",
    # What Connect needs you for, each named once while unseen (P2.5 shows them: 2.x's start-up line, 3.0's Needs you)
    """CREATE TABLE IF NOT EXISTS needs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      language TEXT NOT NULL,
      item_id INTEGER,
      job_id INTEGER,
      kind TEXT NOT NULL,
      say TEXT NOT NULL,
      at TEXT NOT NULL,
      seen INTEGER NOT NULL DEFAULT 0)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS one_need ON needs (language, kind, COALESCE(item_id, -1)) WHERE seen = 0",
)
# The columns `set_state` may write beside the state
_STATE_COLUMNS = frozenset(("reason", "resume", "picked", "attempt", "failures", "skipped", "store_id"))


class TooNew(Exception):
    """The ledger was written by a newer Surasura (its schema above SCHEMA): refused, never read or written — Connect
    says so in *Needs you* (P2.2 adversary #12)."""

    def __init__(self, schema):
        self.schema = schema
        super().__init__(f"Connect's ledger (schema {schema}) is newer than this Surasura reads. Update Surasura.")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def folder():
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect")


def path():
    return os.path.join(folder(), "ledger.sqlite")


class Ledger:
    """One connection to the ledger; `with Ledger() as ledger:` closes it."""

    def __init__(self, db_path=None):
        db_path = db_path or path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        try:
            self._refuse_newer()
        except BaseException:
            self.conn.close()
            raise
        with self.transaction():
            for sql in _SCHEMA_SQL + _RUNNER_SQL:
                self.conn.execute(sql)
            have = {row[1] for row in self.conn.execute("PRAGMA table_info(jobs)")}
            for name, decl in _ADDED_COLUMNS:
                if name not in have:
                    self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {decl}")
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', ?)", (str(SCHEMA),))
            self.conn.execute("UPDATE meta SET value = ? WHERE key = 'schema' AND CAST(value AS INTEGER) < ?",
                              (str(SCHEMA), SCHEMA))

    def _refuse_newer(self):
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone():
            return
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        try:
            schema = int(row[0]) if row else 0
        except (TypeError, ValueError):
            schema = SCHEMA + 1             # a schema that can't be read is no schema this Surasura knows
        if schema > SCHEMA:
            raise TooNew(row[0] if row else None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.conn.close()

    def transaction(self):
        return _Transaction(self.conn)

    def job(self, language, item_id):
        """The item's latest job as a dict, or None."""
        cur = self.conn.execute("SELECT * FROM jobs WHERE language = ? AND item_id = ? ORDER BY id DESC LIMIT 1",
                                (language, item_id))
        row = cur.fetchone()
        return None if row is None else dict(zip([d[0] for d in cur.description], row))

    def jobs(self, language=None, states=None):
        sql, params = "SELECT * FROM jobs WHERE 1 = 1", []
        if language:
            sql += " AND language = ?"
            params.append(language)
        if states:
            sql += f" AND state IN ({','.join('?' * len(states))})"
            params += list(states)
        cur = self.conn.execute(sql + " ORDER BY id", params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def has_work(self, language, item_id):
        """An open job, or one already done (its receipt may not be written yet): never queue the item again."""
        marks = ",".join("?" * (len(OPEN) + 1))
        return self.conn.execute(f"SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND state IN ({marks}) "
                                 "LIMIT 1", (language, item_id) + OPEN + (DONE,)).fetchone() is not None

    def queue(self, language, item_id, source, event_id, store_id=None):
        """A `queued` job for the item -> its id, or None when it already has work. `store_id`: the store it was read
        from (the runner refuses a job of another store)."""
        if self.has_work(language, item_id):
            return None
        now = _now()
        cur = self.conn.execute("INSERT INTO jobs (language, item_id, state, source, event_id, created_at, updated_at, "
                                "store_id) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)",
                                (language, item_id, source, event_id, now, now, store_id))
        return cur.lastrowid

    def last_read(self, language):
        """When Connect last read the language's placement log, or None."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"last_read:{language}",)).fetchone()
        return row[0] if row else None

    def mark_read(self, language):
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"last_read:{language}", _now()))

    def add_gap(self, language, items):
        """A gap's record: the top-20 items with no cards, from the last read to now -> its id."""
        cur = self.conn.execute("INSERT INTO gaps (language, since, until, items) VALUES (?, ?, ?, ?)",
                                (language, self.last_read(language), _now(), json.dumps(list(items))))
        return cur.lastrowid

    def gaps(self, language, unnoticed=False):
        """Every gap recorded for the language (newest last), each {id, since, until, items, noticed}: what 3.0's
        *Needs you* offers (*Make their cards* · *Leave them*)."""
        cur = self.conn.execute("SELECT * FROM gaps WHERE language = ?" + (" AND noticed = 0" if unnoticed else "")
                                + " ORDER BY id", (language,))
        return [_gap_row(cur, r) for r in cur.fetchall()]

    def mark_noticed(self, ids):
        self.conn.executemany("UPDATE gaps SET noticed = 1 WHERE id = ?", [(i,) for i in ids])

    # --- P2.2: the level raise (HC-N38 / N53) ---------------------------------------------------------------- #

    def job_by_id(self, job_id):
        """One job as a dict (its `words` read back as a list of (word, reading)), or None."""
        cur = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if row is None:
            return None
        out = dict(zip([d[0] for d in cur.description], row))
        out["words"] = _words(out.get("words"))
        return out

    def in_flight(self, language):
        """Is a job of the language past its start (picking … ordering, or waiting mid-way)? Then the list it reads
        may be the one just replaced: the level raise waits for it."""
        marks = ",".join("?" * len(IN_FLIGHT))
        return self.conn.execute(f"SELECT 1 FROM jobs WHERE language = ? AND (state IN ({marks}) OR (state = 'waiting' "
                                 "AND resume IS NOT NULL)) LIMIT 1", (language,) + IN_FLIGHT).fetchone() is not None

    def _not_started(self, job_id):
        """Queued, or waiting with nothing picked yet: it can still gain words or be dropped."""
        row = self.conn.execute("SELECT state, resume FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row is not None and (row[0] == "queued" or (row[0] == "waiting" and row[1] is None))

    def mined(self, language, item_id):
        """Has Connect finished mining the item (a `done` job)? The store's receipt says so too, once written."""
        return self.conn.execute("SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND state = ? LIMIT 1",
                                 (language, item_id, DONE)).fetchone() is not None

    def queue_level(self, language, item_id, words, source="level", store_id=None):
        """A `queued` job of kind `level` for an item already mined, naming only `words` ((word, reading) pairs) ->
        its id. A level job still waiting gains the words (-> its id). Another open job of the item -> None: a first
        mining not started picks from the list as it is now, so the new words are its already."""
        words = sorted({(str(w), str(r)) for w, r in words or ()})
        if not words:
            return None
        marks = ",".join("?" * len(OPEN))
        row = self.conn.execute(f"SELECT id, kind, state, words FROM jobs WHERE language = ? AND item_id = ? AND "
                                f"state IN ({marks}) ORDER BY id DESC LIMIT 1", (language, item_id) + OPEN).fetchone()
        now = _now()
        if row is not None:
            job_id, kind, state, had = row
            if kind != LEVEL or not self._not_started(job_id):
                return None
            merged = sorted(set(_words(had)) | set(words))
            self.conn.execute("UPDATE jobs SET words = ?, updated_at = ? WHERE id = ?",
                              (json.dumps(merged, ensure_ascii=False), now, job_id))
            return job_id
        cur = self.conn.execute("INSERT INTO jobs (language, item_id, state, source, event_id, created_at, updated_at, "
                                "kind, words, store_id) VALUES (?, ?, 'queued', ?, NULL, ?, ?, ?, ?, ?)",
                                (language, item_id, source, now, now, LEVEL, json.dumps(words, ensure_ascii=False),
                                 store_id))
        return cur.lastrowid

    def recorded_list(self, language):
        """(the run signature of the list Connect last looked at, its keys as a set of (word, reading)), or
        (None, None) before the first look."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"listed:{language}",)).fetchone()
        if row is None:
            return None, None
        keys = {(w, r) for w, r in self.conn.execute("SELECT word, reading FROM listed WHERE language = ?",
                                                     (language,))}
        return row[0], keys

    def record_list(self, language, signature, keys):
        """The list as looked at now (inside the caller's transaction)."""
        self.conn.execute("DELETE FROM listed WHERE language = ?", (language,))
        self.conn.executemany("INSERT OR IGNORE INTO listed (language, word, reading) VALUES (?, ?, ?)",
                              [(language, str(w), str(r)) for w, r in keys])
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"listed:{language}", signature))

    def forget_list(self, language):
        """Connect switched on again: the next look records the list and mines nothing (inside the caller's
        transaction)."""
        self.conn.execute("DELETE FROM listed WHERE language = ?", (language,))
        self.conn.execute("DELETE FROM meta WHERE key = ?", (f"listed:{language}",))

    def owe_resort(self, language):
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"resort_due:{language}", _now()))

    def resort_owed(self, language):
        """When a re-sort became owed (the list moved), or None: the runner's ordering step pays it (P2.4)."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"resort_due:{language}",)).fetchone()
        return row[0] if row else None

    def resort_paid(self, language):
        self.conn.execute("DELETE FROM meta WHERE key = ?", (f"resort_due:{language}",))

    def drop(self, language, item_id, reason):
        """The item's job, if it hasn't started (an item that left the top 20 before mining) -> dropped or not. Once
        mining has started, it finishes (02 §2)."""
        marks = ",".join("?" * (len(BEFORE_MINING) - 1))
        cur = self.conn.execute(f"UPDATE jobs SET state = 'dropped', reason = ?, resume = NULL, updated_at = ? "
                                f"WHERE language = ? AND item_id = ? AND (state = 'queued' OR (state = 'waiting' AND "
                                f"(resume IS NULL OR resume IN ({marks}))))",
                                (reason, _now(), language, item_id) + BEFORE_MINING[1:])
        return cur.rowcount > 0

    # --- P2.4: the runner's job (02 §2, N5, N6, N9) ----------------------------------------------------------- #

    def set_state(self, job_id, state, **columns):
        """A job's state, saved now in its own short transaction (or the caller's), with any of `_STATE_COLUMNS`
        (`picked` and `skipped` as JSON). Leaving `waiting` clears its resume step, and an open state its reason,
        unless given."""
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        unknown = set(columns) - _STATE_COLUMNS
        if unknown:
            raise ValueError(f"unknown columns {sorted(unknown)}")
        if state != "waiting":
            columns.setdefault("resume", None)
            if state not in FINISHED:
                columns.setdefault("reason", None)
        for name in ("picked", "skipped"):
            if columns.get(name) is not None and not isinstance(columns[name], str):
                columns[name] = json.dumps(columns[name], ensure_ascii=False)
        sets = "".join(f", {name} = ?" for name in columns)
        sql = f"UPDATE jobs SET state = ?, updated_at = ?{sets} WHERE id = ?"
        params = (state, _now()) + tuple(columns.values()) + (job_id,)
        if self.conn.in_transaction:
            self.conn.execute(sql, params)
        else:
            with self.transaction():
                self.conn.execute(sql, params)

    def picked(self, job_id):
        """What the job's pick chose (a dict), or None."""
        row = self.conn.execute("SELECT picked FROM jobs WHERE id = ?", (job_id,)).fetchone()
        try:
            return json.loads(row[0]) if row and row[0] else None
        except ValueError:
            return None

    def open_jobs(self, language):
        """Every open job of the language (oldest first), each with its `words` read back."""
        out = self.jobs(language, states=OPEN)
        for job in out:
            job["words"] = _words(job.get("words"))
        return out

    def start_batch(self, job_id, attempt, run_dir):
        """A batch about to call Anki Miner (N5): `running` until `end_batch`. One left `running` after a kill is a
        batch in doubt — its notes are found by the job's tag before anything is tried again (E25)."""
        with self.transaction():
            self.conn.execute("INSERT OR REPLACE INTO batches (job_id, attempt, run_dir, state, started_at) "
                              "VALUES (?, ?, ?, 'running', ?)", (job_id, attempt, run_dir, _now()))
            self.conn.execute("UPDATE jobs SET attempt = ?, updated_at = ? WHERE id = ?", (attempt, _now(), job_id))

    def end_batch(self, job_id, attempt, state, outcomes=(), anki_miner=None):
        """The batch's end and its words' outcomes, in one transaction (a kill leaves the batch running, or both)."""
        with self.transaction():
            self.record_outcomes(job_id, attempt, outcomes)
            self.conn.execute("UPDATE batches SET state = ?, anki_miner = ?, ended_at = ? WHERE job_id = ? AND "
                              "attempt = ?", (state, anki_miner, _now(), job_id, attempt))

    def record_outcomes(self, job_id, attempt, outcomes):
        """N6 rows, inside the caller's transaction: a later attempt's row replaces an earlier one's, never a word
        already `made`."""
        for o in outcomes:
            had = self.conn.execute("SELECT outcome FROM outcomes WHERE job_id = ? AND word = ? AND reading = ?",
                                    (job_id, o["word"], o["reading"])).fetchone()
            if had and had[0] == "made" and o.get("outcome") != "made":
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO outcomes (job_id, word, reading, orth, line_start, line_end, sentence, "
                "predicted, outcome, note_id, attempt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, o["word"], o["reading"], o.get("orth"), o.get("line_start"), o.get("line_end"),
                 o.get("sentence"), o.get("predicted"), o["outcome"], o.get("note_id"), attempt))

    def batches(self, job_id):
        cur = self.conn.execute("SELECT * FROM batches WHERE job_id = ? ORDER BY attempt", (job_id,))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def outcomes(self, job_id):
        cur = self.conn.execute("SELECT * FROM outcomes WHERE job_id = ? ORDER BY rowid", (job_id,))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def undo_record(self, job_id):
        """N9: the note ids the job made (its `made` outcomes), for *Undo this batch* (P2.5)."""
        return [r[0] for r in self.conn.execute("SELECT note_id FROM outcomes WHERE job_id = ? AND outcome = 'made' "
                                                "AND note_id IS NOT NULL ORDER BY rowid", (job_id,))]

    def need(self, language, kind, say, item_id=None, job_id=None):
        """Something Connect needs you for, named once while unseen (`kind` + item) -> True when newly named."""
        cur = self.conn.execute("INSERT OR IGNORE INTO needs (language, item_id, job_id, kind, say, at) "
                                "VALUES (?, ?, ?, ?, ?, ?)", (language, item_id, job_id, kind, say, _now()))
        return cur.rowcount > 0

    def needs(self, language=None, unseen=True):
        sql, params = "SELECT * FROM needs WHERE 1 = 1", []
        if language:
            sql += " AND language = ?"
            params.append(language)
        if unseen:
            sql += " AND seen = 0"
        cur = self.conn.execute(sql + " ORDER BY id", params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


def _words(text):
    """A job's `words` column -> [(word, reading)], or None (the whole list)."""
    if text is None:
        return None
    try:
        return [(str(w), str(r)) for w, r in json.loads(text)]
    except (ValueError, TypeError):
        return []


def _gap_row(cur, row):
    out = dict(zip([d[0] for d in cur.description], row))
    out["items"] = json.loads(out["items"])
    return out


class _Transaction:
    """BEGIN IMMEDIATE … COMMIT, rolled back on any exception."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False
