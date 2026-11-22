"""The level raise (P2.2 row 2.2.6; HC-N38 / N53; P1.5 06-edges E23) — since the mining model (Kantan-MO, 3.0.18;
ADVERSARY.md F1) a raise **mines no episode again**: its newly listed words join the study order, and Connect cards
them as it meets them in the episodes ahead. Sonic: a move to Rare must not mine a lot again. What each test holds:

  * a raise queues no job, whatever was mined; it counts its newly listed words and owes the deck a re-sort;
  * the first look records the list and mines nothing; a look at the same list does nothing; a batch in flight makes
    the look wait instead of losing the list's record;
  * a level job queued before the update keeps its pick's rule while under way: only its words (`restrict`).

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


def test_a_raise_counts_its_new_words_and_mines_no_episode_again():
    # why: F1 — before 3.0.18 a raise queued one Anki Miner job per already-mined episode (the top 20, then the rest
    # of Current and Goal): hundreds on a big library for one move of the slider
    (a, fa), (b, fb), (d, fd) = _line()
    _mine(a, d)
    files = {fa: ["眼鏡", "散歩"], fb: ["老婆", "冒険"], fd: ["眼鏡", "駐車場", "老婆"]}
    assert _check(BEFORE, "run-1", files)["first"] is True          # the first look records, mines nothing
    out = _check(RAISED, "run-2", files)
    assert out["new"] == 3 and out["queued"] == [] and _level_jobs() == []
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
    assert out["new"] == 3 and out["queued"] == [] and _level_jobs() == []


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
    assert out["new"] == 3 and out["queued"] == [] and _level_jobs() == []


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


def test_connect_looks_once_a_run_and_queues_no_level_job():
    (a, fa), _b, _d = _line()
    _mine(a)
    _last_generate(BEFORE, "run-1", {fa: ["眼鏡"]})
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"]["first"] is True, line
    _last_generate(RAISED, "run-2", {fa: ["眼鏡"]})
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"]["queued"] == [], line
    assert line["languages"]["ja"]["level"]["new"] == 3 and _level_jobs() == []


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


def test_new_files_mined_before_connects_own_generate_get_their_new_words_and_nothing_else():
    # why: the one level job left (P4.1 C5, kept by Kantan-MO): a new episode placed on top is mined before its
    # Generate from the re-plan's list; the Generate then lists words only it brought. Those episodes alone — mined
    # since Connect's own Generate after new files marked the run — get them; an episode mined earlier gets nothing
    (a, fa), (b, fb), (d, fd) = _line()
    _mine(a, d)
    files = {fa: ["眼鏡"], fb: ["老婆"], fd: ["眼鏡", "駐車場"]}
    _check(BEFORE, "run-1", files)
    with Ledger() as ledger, ledger.transaction():
        job = ledger.queue("ja", d, "user", None)
        ledger.conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job,))
        ledger.mark_new_files("ja", "2000-01-01T00:00:00Z")
    out = _check(RAISED, "run-2", files)
    assert out["queued"] == [d], "only the episode this run mined"
    (made,) = _level_jobs()
    assert made["source"] == level.NEW_FILES
    assert made["words"] == sorted([("眼鏡", "メガネ"), ("駐車場", "チュウシャジョウ")])
    out = _check(RAISED | {("約束", "ヤクソク")}, "run-3", dict(files, **{fd: ["約束"]}))
    assert out["queued"] == [] and out["new"] == 1, "the mark is taken once: a later raise mines nothing"


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
    out = _check(RAISED, "run-3", files)                 # then a raise
    assert out["new"] == 3 and out["queued"] == [] and _level_jobs() == []


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
    assert out["queued"] == [d], "only the new-files run's own episode"


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
    assert out["new"] == 3 and out["queued"] == [] and _level_jobs() == []
    with Ledger() as ledger:
        assert ledger.take_new_files("ja") is None, "taken"
