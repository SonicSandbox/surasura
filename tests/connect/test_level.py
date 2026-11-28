"""The level raise (P2.2 row 2.2.6; HC-N38 / N53; P1.5 06-edges E23) — since TOP-UP (3.0.21, Sonic § 114) a raise
**tops up the episodes already mined**: each mined episode ahead gets a `level` job naming only its newly listed words
(`level.TOP_UP`), under the cap's window (Kantan-MO's F1, a move to Rare must not mine a lot at once, is the cap's
now: `test_top_up.py`). What each test holds:

  * a raise queues one job per mined episode ahead with only its new words, never one for an unmined episode; it
    counts its newly listed words and owes the deck a re-sort; a lowered level mines nothing;
  * the first look records the list and mines nothing; a look at the same list does nothing; a batch in flight makes
    the look wait instead of losing the list's record;
  * new files marked by their run go first, as `NEW_FILES`; a mark is taken once, by any look;
  * a level job keeps its pick's rule while under way: only its words (`restrict`).

The suite's real subtitles in a store built from folders; the words are real Japanese lemmas of those files' kind;
the list itself is handed in (no Generate), and the CLI test writes a last Generate's files by hand.
"""
import json
import os

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


def _check(listed, signature, file_words):
    with c.store() as s:
        return level.check(s, "ja", listed, signature, file_words)


def _level_jobs():
    with Ledger() as ledger:
        return [ledger.job_by_id(j["id"]) for j in ledger.jobs("ja") if j["kind"] == LEVEL]


def test_a_raise_tops_up_each_mined_episode_with_only_its_new_words():
    # why: TOP-UP (Sonic § 114) — from 3.0.18 to 3.0.20 a raise mined no episode again, so a word met only in mined
    # episodes was never carded. Each mined episode now gets its newly listed words, never one it was mined with (散歩),
    # and an episode not mined yet gets none (b: its first mining reads the list as it is)
    (a, fa), (b, fb), (d, fd) = _line()
    _mine(a, d)
    files = {fa: ["眼鏡", "散歩"], fb: ["老婆", "冒険"], fd: ["眼鏡", "駐車場", "老婆"]}
    assert _check(BEFORE, "run-1", files)["first"] is True          # the first look records, mines nothing
    assert _level_jobs() == []
    out = _check(RAISED, "run-2", files)
    assert out["new"] == 3 and out["queued"] == [a, d], "soonest first"
    jobs = {j["item_id"]: j for j in _level_jobs()}
    assert set(jobs) == {a, d} and {j["source"] for j in jobs.values()} == {level.TOP_UP}
    assert jobs[a]["words"] == [("眼鏡", "メガネ")]
    assert jobs[d]["words"] == sorted([("眼鏡", "メガネ"), ("駐車場", "チュウシャジョウ"), ("老婆", "ロウバ")])
    with Ledger() as ledger:
        assert ledger.recorded_list("ja") == ("run-2", RAISED)
        assert ledger.resort_owed("ja"), "a moved list owes a re-sort"


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
    assert out["new"] == 3 and out["queued"] == [a]
    assert [j["words"] for j in _level_jobs()] == [sorted([("眼鏡", "メガネ"), ("老婆", "ロウバ")])]


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
    out = _check(RAISED, "run-2", files)
    assert out["new"] == 3 and out["queued"] == [a], "the raise kept for the look after the batch"
    assert [j["words"] for j in _level_jobs()] == [[("眼鏡", "メガネ")]]


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


def test_connect_looks_once_a_run_and_tops_up_the_mined_episode():
    (a, fa), _b, _d = _line()
    _mine(a)
    _last_generate(BEFORE, "run-1", {fa: ["眼鏡"]})
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"]["first"] is True, line
    assert _level_jobs() == []
    _last_generate(RAISED, "run-2", {fa: ["眼鏡"]})
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"]["queued"] == [a], line
    assert line["languages"]["ja"]["level"]["new"] == 3
    assert [(j["source"], j["words"]) for j in _level_jobs()] == [(level.TOP_UP, [("眼鏡", "メガネ")])]
    code, line = h.call("connect", "--consume-only")                # the same run: looked at once
    assert code == 0 and not (line["languages"]["ja"]["level"] or {}).get("queued"), line
    assert len(_level_jobs()) == 1


def test_a_results_folder_without_its_list_is_no_look():
    """The run stamp and the language say a Japanese list, but the list file itself is gone (a Generate that wrote
    nothing yet, a file removed by hand): no look, nothing recorded. Recorded as an empty list, the next Generate
    would make every word on it "newly listed" and queue cards for all of them."""
    from app.cli import verbs
    (a, fa), _b, _d = _line()
    _mine(a)
    _last_generate(BEFORE, "run-1", {fa: ["眼鏡"]})
    os.remove(os.path.join(h.root(), "results", verbs.PRIORITY_CSV))
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"] is None, line
    with Ledger() as ledger:
        assert ledger.recorded_list("ja") == (None, None)


def test_new_files_mined_before_connects_own_generate_go_first_as_new_files_and_the_mark_is_taken_once():
    # why: P4.1 C5 — a new episode placed on top is mined before its Generate from the re-plan's list; the Generate
    # then lists words only it brought. Those episodes (mined since Connect's own Generate after new files marked the
    # run) get them first, as `NEW_FILES`; since TOP-UP an episode mined earlier gets its new words too, as a top-up
    (a, fa), (b, fb), (d, fd) = _line()
    _mine(a, d)
    files = {fa: ["眼鏡"], fb: ["老婆"], fd: ["眼鏡", "駐車場"]}
    _check(BEFORE, "run-1", files)
    with Ledger() as ledger, ledger.transaction():
        job = ledger.queue("ja", d, "user", None)
        ledger.conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job,))
        ledger.mark_new_files("ja", "2000-01-01T00:00:00Z")
    out = _check(RAISED, "run-2", files)
    assert out["queued"] == [d, a], "the episode this run mined first, then the one mined earlier"
    jobs = {j["item_id"]: j for j in _level_jobs()}
    assert jobs[d]["source"] == level.NEW_FILES and jobs[a]["source"] == level.TOP_UP
    assert jobs[d]["words"] == sorted([("眼鏡", "メガネ"), ("駐車場", "チュウシャジョウ")])
    assert jobs[a]["words"] == [("眼鏡", "メガネ")]
    with Ledger() as ledger, ledger.transaction():
        assert ledger.take_new_files("ja") is None, "the mark is taken once"


def _mined_this_run(*item_ids):
    """Each item's first mining done in this run, before Connect's own Generate after new files (the mark)."""
    with Ledger() as ledger, ledger.transaction():
        for item_id in item_ids:
            job = ledger.queue("ja", item_id, "user", None)
            ledger.conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job,))
        ledger.mark_new_files("ja", "2000-01-01T00:00:00Z")


def test_a_new_files_job_skips_a_word_connect_already_made_for_any_episode():
    # was test_a_word_connect_already_made_for_any_episode_is_skipped (a raise's job): G1.3-4 holds for the one level
    # job left — a word made once, its card deleted since, is never made again automatically
    (a, fa), (b, _fb), _d = _line()
    _mine(a)
    with c.store() as s:
        from app import library_store
        with s._writing():
            for sql in library_store.ADDED_TABLES_SQL:
                s.conn.execute(sql)
            s.conn.execute("INSERT INTO made_words (item_id, word, note_ids, made_at, batch) VALUES (?, ?, ?, ?, ?)",
                           (b, "眼鏡", "[1789712000001]", "2026-10-06T10:00:00Z", "job-7"))
    _check(BEFORE, "run-1", {fa: ["眼鏡", "老婆"]})
    _mined_this_run(a)
    _check(RAISED, "run-2", {fa: ["眼鏡", "老婆"]})
    assert [j["words"] for j in _level_jobs()] == [[("老婆", "ロウバ")]], "G1.3-4: a word made once is never made again"


def test_a_waiting_new_files_job_gains_the_next_looks_words_and_carries_the_stores_identity():
    # was test_a_waiting_level_job_gains_the_next_raises_words + test_every_level_job_is_queued_with_the_stores_identity
    (a, fa), _b, _d = _line()
    _mine(a)
    files = {fa: ["眼鏡", "老婆"]}
    _check(BEFORE, "run-1", files)
    _mined_this_run(a)
    _check(BEFORE | {("眼鏡", "メガネ")}, "run-2", files)
    _mined_this_run(a)
    _check(RAISED, "run-3", files)
    jobs = _level_jobs()
    assert len(jobs) == 1 and jobs[0]["words"] == [("眼鏡", "メガネ"), ("老婆", "ロウバ")]
    with c.store() as s:
        assert jobs[0]["store_id"] == library.store_id(s) and jobs[0]["store_id"]


def test_a_new_files_job_never_goes_to_a_watched_episode_or_one_taken_out_of_the_learning_order():
    # was test_p41_level_beyond's Finished / taken-out rows and test_mw1_counts' stone rows (D14, LF4-1): `wants`
    (a, fa), (b, fb), (d, fd) = _line()
    _mine(a, b, d)
    with c.store() as s:
        s.set_watched([a])
        with s._writing():
            s.conn.execute("UPDATE items SET in_learning_order = 0 WHERE id = ?", (b,))
    files = {fa: ["眼鏡"], fb: ["眼鏡"], fd: ["眼鏡"]}
    _check(BEFORE, "run-1", files)
    _mined_this_run(a, b, d)
    assert _check(RAISED, "run-2", files)["queued"] == [d]


def test_the_inbox_keeps_a_new_files_job_out_of_the_line_but_never_a_raises():
    # was test_p41_level_beyond's "kept out of the line; a finished / removed event drops one not started" (C4)
    from app.connect import inbox
    new = {"kind": LEVEL, "source": level.NEW_FILES}
    assert inbox.keeps(new) and inbox.keeps(new, "left_mine_line")
    assert not inbox.keeps(new, "finished") and not inbox.keeps(new, "removed")
    assert not inbox.keeps({"kind": LEVEL, "source": "level"}), "a raise's job from 3.0.17: never kept"


def test_a_new_files_mark_left_before_connect_was_switched_off_never_mines_after_it_is_switched_on_again():
    # why: train 56's keeper F1 — the mark a new-files run left was cleared only by an ordinary look; switched off and
    # on again, the next look is a first look and returned before taking it, so a later raise read the old mark and
    # queued a level job for every episode mined since that run (`mined_since`): the re-mine the model retired
    (a, fa), (b, fb), (d, fd) = _line()
    files = {fa: ["眼鏡"], fb: ["老婆"], fd: ["眼鏡", "駐車場"]}
    _check(BEFORE, "run-1", files)
    _mined_this_run(d)                                   # a new-files run: its mark is left
    level.forget("ja")                                   # Connect off -> on (the preview's switch)
    assert _check(BEFORE, "run-2", files)["first"] is True
    with Ledger() as ledger, ledger.transaction():       # later, ordinary mining (no mark of its own)
        for item_id in (a, b):
            job = ledger.queue("ja", item_id, "user", None)
            ledger.conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job,))
    out = _check(RAISED, "run-3", files)                 # then a raise: every mined episode's top-up, in the
    assert out["new"] == 3 and out["queued"] == [a, b, d]    # line's order; none a new-files job by the old mark
    assert {j["source"] for j in _level_jobs()} == {level.TOP_UP}


def test_a_new_files_mark_a_look_at_the_same_list_leaves_gives_only_that_runs_episodes():
    # why: the same F1 by its other path — a look at an unchanged list returns before taking the mark; the next new
    # list is then a raise, and the mark (a time) would hand it every episode mined since that run, each mined from a
    # list that already held its words. The mark names its run's episodes, so only those get their new words
    (a, fa), (b, fb), (d, fd) = _line()
    files = {fa: ["眼鏡"], fb: ["老婆"], fd: ["眼鏡", "駐車場"]}
    _check(BEFORE, "run-1", files)
    _mined_this_run(d)                                   # the new-files run, its Generate wrote no new list
    assert _check(BEFORE, "run-1", files)["queued"] == []    # the same list: the mark stays
    with Ledger() as ledger, ledger.transaction():       # later, ordinary mining (no mark of its own)
        for item_id in (a, b):
            job = ledger.queue("ja", item_id, "user", None)
            ledger.conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job,))
    out = _check(RAISED, "run-2", files)
    assert out["queued"] == [d, a, b], "the new-files run's own episode first, then the top-ups"
    assert {j["item_id"] for j in _level_jobs() if j["source"] == level.NEW_FILES} == {d}, \
        "only the new-files run's own episode is a new-files job"


def test_a_mark_left_by_an_older_ledger_is_dropped_never_read_as_every_episode_since():
    # why: a mark written as a bare time (before it named its episodes) can't tell its run's episodes from later
    # ones: it is dropped (the words join the study order) rather than mining every episode since
    (a, fa), (b, fb), (d, fd) = _line()
    files = {fa: ["眼鏡"], fb: ["老婆"], fd: ["眼鏡", "駐車場"]}
    _check(BEFORE, "run-1", files)
    _mined_this_run(a, b, d)
    with Ledger() as ledger, ledger.transaction():
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('new_files:ja', '2000-01-01T00:00:00Z')")
    out = _check(RAISED, "run-2", files)
    assert out["new"] == 3 and out["queued"] == [a, b, d], "the line's order: none put first by the old mark"
    assert {j["source"] for j in _level_jobs()} == {level.TOP_UP}
    with Ledger() as ledger, ledger.transaction():
        assert ledger.take_new_files("ja") is None, "taken"
        for old in ("2000-01-01T00:00:00Z", "7", '{"7": 1}'):
            ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('new_files:ja', ?)", (old,))
            assert ledger.take_new_files("ja") is None, old
            assert ledger.take_new_files("ja") is None, "dropped once read"


def test_two_new_files_runs_before_a_new_list_give_both_runs_episodes_their_words():
    # why: a mark not yet taken (its run's Generate wrote no new list) keeps its episodes when the next new-files run
    # marks its own: both runs' episodes were mined from a list without their words
    (a, fa), (b, fb), (d, fd) = _line()
    files = {fa: ["眼鏡"], fb: ["老婆"], fd: ["眼鏡", "駐車場"]}
    _check(BEFORE, "run-1", files)
    _mined_this_run(d)
    _check(BEFORE, "run-1", files)                       # the same list: the mark stays
    with Ledger() as ledger, ledger.transaction():
        ledger.conn.execute("UPDATE jobs SET updated_at = '1999-01-01T00:00:00Z'")   # run 1 ended long before
    with Ledger() as ledger, ledger.transaction():
        job = ledger.queue("ja", b, "user", None)
        ledger.conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job,))
        ledger.mark_new_files("ja", "2000-01-01T00:00:00Z")       # run 2's own mark
    assert sorted(_check(RAISED, "run-2", files)["queued"]) == sorted([b, d])


def test_a_new_files_mark_left_before_connects_first_look_is_taken_by_that_look():
    # why: a first look records every word as the list holds it, the new episodes' own words included: a mark left
    # before it (a new-files run before Connect had looked at any list) gives a later raise nothing
    (a, fa), (b, fb), (d, fd) = _line()
    files = {fa: ["眼鏡"], fb: ["老婆"], fd: ["眼鏡", "駐車場"]}
    _mined_this_run(d)
    assert _check(BEFORE, "run-1", files)["first"] is True
    out = _check(RAISED, "run-2", files)
    assert out["new"] == 3 and out["queued"] == [d]
    assert [(j["source"], j["words"]) for j in _level_jobs()] == [
        (level.TOP_UP, sorted([("眼鏡", "メガネ"), ("駐車場", "チュウシャジョウ")]))], "the mark taken by the first look"
