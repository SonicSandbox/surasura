"""Help cards, WP1 (spec §6.2, §13 *The ledger write, full*): a waiting job's *since* — the ledger's `reason_at`,
kept by one SQLite trigger over every writer of `reason`, with no SCHEMA bump.

What each test holds still, and what a wrong answer would cost a learner:
  * the column is added to an older ledger, keeps every row and SCHEMA stays 4 — a bump would make a 3.0.0 refuse
    the ledger (`TooNew`) and stop making cards;
  * through each writer (`drop`, the stop's wait, `set_state`, `reopen_skipped`, an insert with a reason) a new
    reason stamps `reason_at`, the same reason written again keeps it, a cleared reason clears it — else *since
    14:02* would move every look (a wait that seems to start again) or stay on a wait that has ended;
  * the status record carries `since` for a waiting job and none for an older row, read through `mode=ro`.

The ledger is a real SQLite file in a temp folder; no network, no sleeps (an old stamp is written by hand, so "kept"
and "new" are told apart without waiting a second).
"""
import sqlite3

from app.connect import ledger as book
from app.connect.ledger import Ledger
from tests.connect.test_ledger import _SCHEMA_2_JOBS, _write_ledger

OLD = "2026-01-02T03:04:05Z"


def _at(ledger, job_id):
    return ledger.conn.execute("SELECT reason, reason_at FROM jobs WHERE id = ?", (job_id,)).fetchone()


def _age(ledger, job_id):
    """The job's stamp set back by hand (the trigger fires only on a `reason` write: this one leaves it as written)."""
    ledger.conn.execute("UPDATE jobs SET reason_at = ? WHERE id = ?", (OLD, job_id))


def _queued(ledger, item_id=4):
    with ledger.transaction():
        return ledger.queue("ja", item_id, "user", None)


def test_an_older_ledger_gains_the_column_keeps_its_rows_and_stays_schema_4(tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    _write_ledger(path, "2", _SCHEMA_2_JOBS,
                  "INSERT INTO jobs (language, item_id, state, reason, source, created_at, updated_at) VALUES "
                  "('ja', 7, 'waiting', 'Waiting for Anki: it isn''t open', 'user', 'x', 'x')")
    with Ledger(path) as ledger:
        (job,) = ledger.jobs("ja")
        assert job["reason"] == "Waiting for Anki: it isn't open" and job["reason_at"] is None   # no *since* for it
        assert book.SCHEMA == 4
        assert ledger.conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == "4"
    with Ledger(path) as ledger:                            # opened again: the trigger made once, nothing doubled
        triggers = [r[0] for r in ledger.conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")]
        assert sorted(triggers) == ["reason_since", "reason_since_new"]


def test_set_state_stamps_a_new_reason_keeps_the_same_one_and_clears_a_cleared_one(tmp_path):
    with Ledger(str(tmp_path / "l.sqlite")) as ledger:
        job = _queued(ledger)
        ledger.set_state(job, "waiting", reason="Waiting for Anki: it isn't open")
        reason, at = _at(ledger, job)
        assert reason and at and at.endswith("Z") and at != OLD
        _age(ledger, job)
        ledger.set_state(job, "waiting", reason="Waiting for Anki: it isn't open")
        assert _at(ledger, job)[1] == OLD                   # the same reason again: its time kept
        ledger.set_state(job, "waiting", reason="Waiting while you review in Anki")
        assert _at(ledger, job)[1] not in (None, OLD)       # a new reason: a new time
        ledger.set_state(job, "queued")                      # an open state clears its reason …
        assert _at(ledger, job) == (None, None)              # … and its time


def test_drop_stamps_its_reason(tmp_path):
    with Ledger(str(tmp_path / "l.sqlite")) as ledger:
        job = _queued(ledger)
        with ledger.transaction():
            assert ledger.drop("ja", 4, "left the top 20")
        reason, at = _at(ledger, job)
        assert reason == "left the top 20" and at not in (None, OLD)


def test_the_stops_wait_stamps_its_reason(tmp_path):
    with Ledger(str(tmp_path / "l.sqlite")) as ledger:
        job = _queued(ledger)
        assert ledger.ask_stop(job)
        reason, at = _at(ledger, job)
        assert reason == book.STOPPED_REASON and at not in (None, OLD)


def test_reopen_skipped_clears_the_reason_and_its_time(tmp_path):
    with Ledger(str(tmp_path / "l.sqlite")) as ledger:
        job = _queued(ledger)
        ledger.set_state(job, "skipped", reason="Anki Miner isn't installed")
        assert _at(ledger, job)[1] is not None
        with ledger.transaction():
            assert ledger.reopen_skipped("ja", [4], "Anki Miner isn't installed") == 1
        assert _at(ledger, job) == (None, None)


def test_a_job_inserted_with_its_reason_is_stamped_and_one_without_is_not(tmp_path):
    with Ledger(str(tmp_path / "l.sqlite")) as ledger:
        with ledger.transaction():
            ledger.conn.execute("INSERT INTO jobs (language, item_id, state, reason, source, created_at, updated_at) "
                                "VALUES ('ja', 9, 'waiting', 'No video', 'user', 'x', 'x')")
        assert ledger.conn.execute("SELECT reason_at FROM jobs WHERE item_id = 9").fetchone()[0] is not None
        job = _queued(ledger, item_id=10)
        assert _at(ledger, job) == (None, None)


def test_the_status_record_carries_since_for_a_wait_and_none_for_an_old_row(tmp_path, monkeypatch):
    from app.connect import status
    path = str(tmp_path / "l.sqlite")
    with Ledger(path) as ledger:
        waiting = _queued(ledger, item_id=4)
        ledger.set_state(waiting, "waiting", reason="Waiting for Anki: it isn't open")
        old = _queued(ledger, item_id=5)
        ledger.set_state(old, "waiting", reason="Waiting for Anki: it isn't open")
        ledger.conn.execute("UPDATE jobs SET reason_at = NULL WHERE id = ?", (old,))     # a row from before
        stamp = _at(ledger, waiting)[1]
    monkeypatch.setattr(status, "_items", lambda lang, ids: {})
    rec = status.read(["ja"], path=path)
    jobs = {j["job"]: j for j in rec["languages"]["ja"]["jobs"]} if "languages" in rec else \
        {j["job"]: j for j in rec["ja"]["jobs"]}
    assert jobs[waiting]["since"] == stamp and jobs[old]["since"] is None
    con = sqlite3.connect(path)                               # the read left the file as it was: no write by status
    try:
        assert con.execute("SELECT reason_at FROM jobs WHERE id = ?", (old,)).fetchone()[0] is None
    finally:
        con.close()


def test_the_wait_line_says_since_in_the_one_time_rule():
    from app.services.view_rows import since_words
    assert since_words(None) == "" and since_words("not a time") == ""
    assert since_words("2026-11-06T22:02:00Z").startswith("since ")
