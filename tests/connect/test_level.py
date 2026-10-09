"""The level raise (P2.2 row 2.2.6; HC-N38 / N53; P1.5 06-edges E23).

Sonic (HC-N38): "If they increase the level that means all of the content that they have would now have more words.
So it would need to mine more things but exclude what they've already mined." What each test holds still:

  * only the newly listed words, only for episodes already mined, the top 20 first — never an episode not mined yet
    (its first mining reads the list as it is), never beyond the top 20 in 2.x (E23), never a word Connect already
    made for any episode (N15, G1.3-4); one card per word is the pick's at each job's turn, the top job first;
  * the first look and a lowered level mine nothing; a look at the same list does nothing; a batch in flight makes
    the look wait instead of losing the raise;
  * a level job's pick sends Anki Miner only its words.

The suite's real subtitles in a store built from folders; the words are real Japanese lemmas of those files' kind;
the list itself is handed in (no Generate), and the CLI test writes a last Generate's files by hand.
"""
import json
import os

import pytest

from app.connect import level, library
from app.connect.ledger import LEVEL, Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

# The list before and after a raise: (Word, Reading) — the pick's identity.
BEFORE = {("冒険", "ボウケン"), ("散歩", "サンポ"), ("図書館", "トショカン")}
RAISED = BEFORE | {("眼鏡", "メガネ"), ("老婆", "ロウバ"), ("駐車場", "チュウシャジョウ")}


def _line(n=3):
    """A library whose top `n` episodes are the mine line; returns the line's items (id, file name), in order."""
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": n}, copy_carries=True)
        line = library.mine_line(s)
        return [(i, os.path.basename(s.item(i)["rel_path"])) for i in line]


def _mine(*item_ids):
    with c.store() as s:
        for item_id in item_ids:
            s.receipt(item_id, "2026-10-07T09:00:00Z")


def _check(listed, signature, file_words, mode="list"):
    with c.store() as s:
        return level.check(s, "ja", listed, signature, file_words, mode=mode)


def _level_jobs():
    with Ledger() as ledger:
        return [ledger.job_by_id(j["id"]) for j in ledger.jobs("ja") if j["kind"] == LEVEL]


def test_a_raise_mines_only_the_new_words_of_mined_episodes_top_first():
    (a, fa), (b, fb), (d, fd) = _line()
    _mine(a, d)                                   # b is in the line but not mined yet: its own first job waits
    with Ledger() as ledger:
        ledger.queue("ja", b, "user", None)
    files = {fa: ["眼鏡", "散歩"], fb: ["老婆", "冒険"], fd: ["眼鏡", "駐車場", "老婆"]}
    assert _check(BEFORE, "run-1", files)["first"] is True          # the first look records, mines nothing
    assert _level_jobs() == []
    out = _check(RAISED, "run-2", files)
    assert out["new"] == 3 and out["queued"] == [a, d]                # the top first; b's first mining reads the list
    jobs = {j["item_id"]: j for j in _level_jobs()}
    assert [j["item_id"] for j in _level_jobs()] == [a, d]            # queued, so run, in the line's order
    assert jobs[a]["words"] == [("眼鏡", "メガネ")]                    # 散歩 was listed before: never again
    # d names all its new words: 眼鏡 too — a's job runs first, and d's pick skips a word with a card by then, so a
    # word is never held back from d by a job above it that ends up making no card
    assert jobs[d]["words"] == sorted([("眼鏡", "メガネ"), ("老婆", "ロウバ"), ("駐車場", "チュウシャジョウ")])
    assert all(j["state"] == "queued" and j["source"] == "level" for j in jobs.values())
    with Ledger() as ledger:
        assert ledger.resort_owed("ja"), "a moved list owes a re-sort"


def test_an_unmined_episode_with_no_job_takes_no_word_from_one_below():
    """An episode in the line that Connect will never mine as it stands (placed before Connect was on: no job) holds
    no word back: the mined one below it gets the word."""
    (a, fa), (b, fb), (d, fd) = _line()
    _mine(a, d)
    files = {fa: [], fb: ["老婆"], fd: ["老婆"]}
    _check(BEFORE, "run-1", files)
    assert _check(RAISED, "run-2", files)["queued"] == [d]
    assert [j["words"] for j in _level_jobs()] == [[("老婆", "ロウバ")]]


def test_the_same_list_again_does_nothing_and_a_lowered_level_mines_nothing():
    (a, fa), _b, _d = _line()
    _mine(a)
    files = {fa: ["眼鏡", "老婆"]}
    _check(RAISED, "run-1", files)
    assert _check(RAISED, "run-1", files) == {"queued": [], "new": 0, "first": False, "waiting": False}
    out = _check(BEFORE, "run-2", files)                            # the level lowered
    assert out["new"] == 0 and out["queued"] == [] and _level_jobs() == []
    with Ledger() as ledger:
        assert ledger.resort_owed("ja"), "words that left go to the back: a re-sort is owed"
    out = _check(RAISED, "run-3", files)                            # raised again: those words are new again
    assert out["queued"] == [a]


def test_beyond_the_top_20_nothing_in_2_x():
    items = _line(n=1)
    with c.store() as s:
        below = [i for i in s.ids("now") if i != items[0][0]]
        names = {i: os.path.basename(s.item(i)["rel_path"]) for i in below}
    _mine(*below)
    files = {name: ["眼鏡"] for name in names.values()}
    _check(BEFORE, "run-1", files)
    assert _check(RAISED, "run-2", files)["queued"] == [], "E23: the already-mined episodes below the line wait for 3.0"


def test_a_word_connect_already_made_for_any_episode_is_skipped():
    (a, fa), (b, _fb), _d = _line()
    _mine(a)
    with c.store() as s:
        from app import library_store
        with s._writing():                    # as Connect will write it (P2.4; Kura's N15 line: the table, then the row)
            for sql in library_store.ADDED_TABLES_SQL:
                s.conn.execute(sql)
            s.conn.execute("INSERT INTO made_words (item_id, word, note_ids, made_at, batch) VALUES (?, ?, ?, ?, ?)",
                           (b, "眼鏡", "[1789712000001]", "2026-10-06T10:00:00Z", "job-7"))   # made for b, card deleted
    _check(BEFORE, "run-1", {fa: ["眼鏡", "老婆"]})
    _check(RAISED, "run-2", {fa: ["眼鏡", "老婆"]})
    assert [j["words"] for j in _level_jobs()] == [[("老婆", "ロウバ")]], "G1.3-4: a word made once is never made again"


def test_switched_on_again_the_next_look_is_a_first_look():
    """✅ G1.1-2: what the list gained while Connect was off is never mined — the preview's switch forgets the list."""
    (a, fa), _b, _d = _line()
    _mine(a)
    _check(BEFORE, "run-1", {fa: ["眼鏡"]})
    level.forget("ja")
    out = _check(RAISED, "run-2", {fa: ["眼鏡"]})
    assert out["first"] is True and out["queued"] == [] and _level_jobs() == []


def test_a_batch_in_flight_makes_the_look_wait_and_the_raise_is_not_lost():
    (a, fa), (b, _fb), _d = _line()
    _mine(a)
    files = {fa: ["眼鏡"]}
    _check(BEFORE, "run-1", files)
    with Ledger() as ledger:
        job = ledger.queue("ja", b, "user", None)
        ledger.conn.execute("UPDATE jobs SET state = 'mining' WHERE id = ?", (job,))
    assert _check(RAISED, "run-2", files)["waiting"] is True
    assert _level_jobs() == []
    with Ledger() as ledger:
        ledger.conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job,))
    assert _check(RAISED, "run-2", files)["queued"] == [a]


def test_a_waiting_level_job_gains_the_next_raises_words():
    (a, fa), _b, _d = _line()
    _mine(a)
    files = {fa: ["眼鏡", "老婆"]}
    _check(BEFORE, "run-1", files)
    _check(BEFORE | {("眼鏡", "メガネ")}, "run-2", files)
    _check(RAISED, "run-3", files)
    jobs = _level_jobs()
    assert len(jobs) == 1 and jobs[0]["words"] == [("眼鏡", "メガネ"), ("老婆", "ロウバ")]


@pytest.mark.parametrize("mode", ["unknown", "i1"])
def test_the_other_word_modes_record_the_list_but_mine_nothing_new(mode):
    (a, fa), _b, _d = _line()
    _mine(a)
    _check(BEFORE, "run-1", {fa: ["眼鏡"]}, mode=mode)
    assert _check(RAISED, "run-2", {fa: ["眼鏡"]}, mode=mode)["queued"] == []
    with Ledger() as ledger:
        assert ledger.recorded_list("ja") == ("run-2", RAISED)


def test_no_list_of_this_language_is_no_look():
    _line()
    assert _check(None, "run-1", {}) == {"queued": [], "new": 0, "first": False, "waiting": False}
    assert _check(RAISED, None, {}) == {"queued": [], "new": 0, "first": False, "waiting": False}
    with Ledger() as ledger:
        assert ledger.recorded_list("ja") == (None, None)


def test_restrict_keeps_only_a_level_jobs_words():
    listed = {key: rank for rank, key in enumerate(sorted(RAISED))}
    job = {"kind": LEVEL, "words": [("眼鏡", "メガネ")]}
    assert level.restrict(listed, job) == {("眼鏡", "メガネ"): listed[("眼鏡", "メガネ")]}
    assert level.restrict(listed, {"kind": "mine", "words": None}) is listed
    assert level.restrict(listed, None) is listed
    assert level.restrict(listed, {"kind": LEVEL, "words": []}) == {}


def test_a_schema_1_ledger_is_upgraded_in_place_and_its_jobs_stay():
    """P2.1's ledgers (SCHEMA 1) gain `kind` and `words`; every job there is a first mining."""
    import sqlite3
    from app.connect import ledger as book
    os.makedirs(book.folder(), exist_ok=True)
    old = sqlite3.connect(book.path())
    old.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    old.execute("INSERT INTO meta VALUES ('schema', '1')")
    old.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, language TEXT NOT NULL, item_id INTEGER NOT "
                "NULL, state TEXT NOT NULL, reason TEXT, source TEXT, event_id INTEGER, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL)")
    old.execute("INSERT INTO jobs (language, item_id, state, source, created_at, updated_at) VALUES "
                "('ja', 4, 'queued', 'user', 'x', 'x')")
    old.commit()
    old.close()
    with Ledger() as ledger:
        (job,) = ledger.jobs("ja")
        assert job["kind"] == "mine" and job["words"] is None
        assert ledger.conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == str(book.SCHEMA)


# --------------------------------------------------------------------------- #
# Through the command line: `connect --consume-only` looks once a run; `pick --job <id>` sends only the job's words
# --------------------------------------------------------------------------- #
def _last_generate(words, signature, file_words):
    """A last Generate's files, written by hand: the list, its run stamp, the language it holds, file_words.json."""
    results = os.path.join(h.root(), "results")
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, "priority_learning_list.csv"), "w", encoding="utf-8-sig", newline="") as f:
        f.write("Word,Reading,Orth\n" + "".join(f"{w},{r},{w}\n" for w, r in sorted(words)))
    with open(os.path.join(results, "run_signature.txt"), "w", encoding="utf-8") as f:
        f.write(signature)
    with open(os.path.join(results, "library_frequency.json"), "w", encoding="utf-8") as f:
        json.dump({"settings": {"language": "ja"}}, f)
    with open(os.path.join(results, "file_words.json"), "w", encoding="utf-8") as f:
        json.dump(file_words, f, ensure_ascii=False)


def test_a_list_whose_language_cant_be_told_is_no_look():
    """No `library_frequency.json` (a results folder from before, or half written): the look waits for a list it can
    tell is this language's — never another language's list recorded as this one's."""
    (a, fa), _b, _d = _line()
    _mine(a)
    _last_generate(BEFORE, "run-1", {fa: ["眼鏡"]})
    os.remove(os.path.join(h.root(), "results", "library_frequency.json"))
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"] is None, line
    with Ledger() as ledger:
        assert ledger.recorded_list("ja") == (None, None)


def test_a_look_that_fails_never_stops_the_run(monkeypatch):
    (a, fa), _b, _d = _line()
    _last_generate(BEFORE, "run-1", {fa: ["眼鏡"]})

    def broken(*args, **kwargs):
        raise RuntimeError("the ledger is locked")
    monkeypatch.setattr(level, "check", broken)
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and "the ledger is locked" in line["languages"]["ja"]["level"]["error"], line


def test_connect_looks_once_a_run_and_queues_the_level_jobs():
    (a, fa), _b, _d = _line()
    _mine(a)
    _last_generate(BEFORE, "run-1", {fa: ["眼鏡"]})
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"]["first"] is True, line
    _last_generate(RAISED, "run-2", {fa: ["眼鏡"]})
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"]["queued"] == [a], line
    assert [j["words"] for j in _level_jobs()] == [[("眼鏡", "メガネ")]]
