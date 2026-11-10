"""Job tags are unique across ledgers (P2.4 Part A review fixes; ledger.tag_id): a job's name in its Anki tag and
its run folder is `<ledger uid>-<job id>`, and the uid is random per ledger file. Job ids restart at 1 in every
ledger, so without the uid two ledgers would give the same tag and an old job's notes would count as a new one's.

What a wrong answer would cost: Anki notes from a lost or copied ledger counted as this job's (the tag collides),
and a job's run folder reused by another job. Reopening one ledger must give the same tag every time, or the
tag written to Anki would no longer match the job's own.

Real Japanese words in the queued items; `tmp_path` ledgers, no Anki, no network.
"""
import re

from app.connect.ledger import Ledger


def _queue_one(path):
    # one job in a fresh ledger file: both files number their first job 1
    with Ledger(str(path)) as ledger:
        with ledger.transaction():
            ledger.queue("ja", 1, "user", None, store_id="s")
        return ledger.jobs("ja")[0]


def test_two_ledgers_give_their_first_job_different_tags(tmp_path):
    # why: both ledgers' first job has id 1, so only the ledger's uid tells the two jobs apart
    first = _queue_one(tmp_path / "上層部.sqlite")
    second = _queue_one(tmp_path / "一生懸命.sqlite")
    assert first["id"] == second["id"] == 1
    assert first["tag"] != second["tag"]


def test_each_tag_is_eight_hex_digits_then_the_job_id(tmp_path):
    # why: the uid is the 8-hex-digit token the ledger writes once; the tag is that, a dash, then the job id
    job = _queue_one(tmp_path / "気配.sqlite")
    assert re.fullmatch(r"[0-9a-f]{8}-1", job["tag"]), job["tag"]


def test_reopening_the_same_ledger_gives_the_same_tag(tmp_path):
    # why: the tag is written to Anki and to the run folder; a different tag on reopen would orphan both
    path = tmp_path / "ledger.sqlite"
    first = _queue_one(path)
    with Ledger(str(path)) as ledger:
        again = ledger.jobs("ja")[0]
    assert again["tag"] == first["tag"]
