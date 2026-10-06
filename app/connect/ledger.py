"""Connect's ledger (P1.5 02-data-model §1 N4, §3): `<local data>/connect/ledger.sqlite`, per install, never in the
library or a cloud folder (K58, RD-D15). It holds work in flight — the jobs, one per item mined — and nothing that
lasts: lose it and Connect rebuilds what it needs from the store and Anki's tags, and mines nothing twice.

P2.1 builds the jobs table the inbox fills (`queued`, `dropped`); the rest of a job's life (`waiting` → … → `done`,
word outcomes, undo records) is P2.4's, on the same table. Short transactions, standard library `sqlite3`, like the
store.
"""
import datetime
import json
import os
import sqlite3

SCHEMA = 1
# A job's states (02 §2). Open = not finished one way or the other; not started = still droppable.
OPEN = ("queued", "waiting", "picking", "fit-check", "mining", "filling", "ordering")
NOT_STARTED = ("queued", "waiting")
DONE = "done"
DROPPED = "dropped"

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
      updated_at TEXT NOT NULL)""",
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
)


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
        with self.transaction():
            for sql in _SCHEMA_SQL:
                self.conn.execute(sql)
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', ?)", (str(SCHEMA),))

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

    def queue(self, language, item_id, source, event_id):
        """A `queued` job for the item -> its id, or None when it already has work."""
        if self.has_work(language, item_id):
            return None
        now = _now()
        cur = self.conn.execute("INSERT INTO jobs (language, item_id, state, source, event_id, created_at, updated_at) "
                                "VALUES (?, ?, 'queued', ?, ?, ?, ?)", (language, item_id, source, event_id, now, now))
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

    def drop(self, language, item_id, reason):
        """The item's job, if it hasn't started (an item that left the top 20 before mining) -> dropped or not. Once
        mining has started, it finishes (02 §2)."""
        marks = ",".join("?" * len(NOT_STARTED))
        cur = self.conn.execute(f"UPDATE jobs SET state = 'dropped', reason = ?, updated_at = ? WHERE language = ? "
                                f"AND item_id = ? AND state IN ({marks})",
                                (reason, _now(), language, item_id) + NOT_STARTED)
        return cur.rowcount > 0


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
