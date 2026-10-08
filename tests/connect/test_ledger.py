"""The Connect ledger's schema gate (P2.4 row 2.4.1; 02 §2 and the ledger's SCHEMA steps).

What each test holds still:

  * a ledger written by a newer Surasura (schema above this one's, here one step above) is refused with `TooNew`
    and its file is left exactly as it was: the same bytes, its jobs never read or written. A wrong answer would
    let an old Surasura rewrite a newer ledger's jobs and lose work the newer one was tracking;
  * a ledger one step older (schema 2, P2.2's) opens, keeps its jobs untouched, gains P2.4's columns and tables and
    records schema 3, so the next look does not refuse or re-mine anything;
  * `set_state` is saved at once: a second connection on the same file reads the new state straight away, so a
    crash after the call cannot leave a job that says less than what was done.

The ledger is a real SQLite file in a temp folder (`tmp_path`); no network, no sleeps.
"""
import sqlite3

from app.connect import ledger as book
from app.connect.ledger import Ledger

# The P2.2 jobs table (SCHEMA 2): the columns P2.4 adds (`store_id`, `resume`, ...) are not there yet.
_SCHEMA_2_JOBS = """CREATE TABLE jobs (
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
  words TEXT)"""


def _write_ledger(path, schema, jobs_sql, job_sql):
    """A ledger file made by hand at `schema`, with one job; WAL like the app's own connection, so opening it with
    the app does not change the file's header."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta VALUES ('schema', ?)", (schema,))
        con.execute(jobs_sql)
        con.execute(job_sql)
    finally:
        con.close()


def test_a_newer_ledger_is_refused_and_left_untouched(tmp_path):
    """Schema 4 is one step above this Surasura's 3: refused before any write, so the file keeps its exact bytes."""
    path = str(tmp_path / "ledger.sqlite")
    _write_ledger(path, "4", _SCHEMA_2_JOBS,
                  "INSERT INTO jobs (language, item_id, state, source, created_at, updated_at) VALUES "
                  "('ja', 4, 'queued', 'user', 'x', 'x')")
    with open(path, "rb") as f:
        before = f.read()
    try:
        Ledger(path)
    except book.TooNew as err:
        assert str(err.schema) == "4"
    else:
        raise AssertionError("a schema 4 ledger was opened; it must be refused")
    with open(path, "rb") as f:
        after = f.read()
    assert after == before, "the refused ledger's file changed"


def test_a_schema_2_ledger_is_upgraded_in_place_and_its_jobs_stay(tmp_path):
    """Schema 2 gains P2.4's columns and tables and records schema 3; its job keeps its kind and its words."""
    path = str(tmp_path / "ledger.sqlite")
    words = '[["上層部", "じょうそうぶ"]]'
    _write_ledger(path, "2", _SCHEMA_2_JOBS,
                  "INSERT INTO jobs (language, item_id, state, source, created_at, updated_at, kind, words) VALUES "
                  f"('ja', 7, 'queued', 'level', 'x', 'x', 'level', '{words}')")
    with Ledger(path) as ledger:
        (job,) = ledger.jobs("ja")
        assert job["state"] == "queued" and job["kind"] == "level" and job["words"] == words
        columns = {row[1] for row in ledger.conn.execute("PRAGMA table_info(jobs)")}
        assert {"store_id", "resume", "picked", "attempt", "failures", "skipped"} <= columns
        tables = {row[0] for row in ledger.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"batches", "outcomes", "needs"} <= tables
        assert ledger.conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == "3"


def test_set_state_is_saved_at_once_for_a_second_connection(tmp_path):
    """A state written by one connection is read by another at once: nothing waits for a close."""
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as writer, Ledger(path) as reader:
        job_id = writer.queue("ja", 4, "user", None)
        writer.set_state(job_id, "mining")
        assert reader.jobs("ja")[0]["state"] == "mining"
