"""Kantan-B2b: an upgraded install's episodes, queued before the update, wait for the first run's yes too.

The reporter's install (3.0.15, before Kantan-B2's hold): setup's *Make cards for your first 20 episodes?* still
unanswered, his own arranging of Current had queued episodes from the placement log — job 1 part-way (its first
cards made, then stopped), the others never reached. Kantan-B2's hold stopped only NEW jobs, and any log job lifted it
for good, so after the update those were mined while the question still asked. Sonic, 2026-11-19: "Nothing mines
until the yes" — and *Not now* is not a yes: after it nothing mines by itself, the old queued episodes are set aside,
the question stays, and the learner's own *Mine now* always works. An install that already finished an episode from
the log, with cards, is never held by an old unanswered line.

What a wrong answer would cost: cards in the learner's Anki he never agreed to (the report), or — the other way — a
learner who said yes and never gets cards, or an install that mined for weeks suddenly holding everything. Against
`FakeSteps` (real Japanese words, never a live Anki) for the loop, and the suite's real library (tests/Test
Resources, ja + zh) for the inbox.
"""
import pytest

from app.connect import actions, inbox, library, runner
from app.connect.ledger import FIRST_RUN_ASIDE, Ledger
from app.services import needs
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps, Killed


# --- the loop: 3.0.15's ledger, updated ---------------------------------------------------------------------------- #
@pytest.fixture
def upgraded(tmp_path):
    """3.0.15's ledger, as the report's: item 1's job part-way (its first card made, then the run was cut), items 2
    and 3 queued from the log and never reached (attempt 0); setup's line offered and never answered. -> (ledger
    path, ledger)."""
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        steps = FakeSteps(str(tmp_path), {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1]}, "kill": "mid-batch:1"})
        with pytest.raises(Killed):
            runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda _s: None, looks=1)
        with ledger.transaction():
            for item in (2, 3):
                ledger.queue("ja", item, "user", None, store_id="store-1")
            # the log's own jobs carry their placement event (FakeSteps queues as an ask-less, event-less job)
            ledger.conn.execute("UPDATE jobs SET event_id = 100 + id")
        part = ledger.job("ja", 1)
        assert part["state"] == "mining" and len(steps.anki.notes()) == 1, "job 1 part-way, one card made"
        needs.offer("ja", needs.FIRST_CARDS)
        yield path, ledger


def _run(tmp_path, ledger, looks=1, **plan):
    steps = FakeSteps(str(tmp_path), dict({"line": {"ja": [1, 2, 3]}}, **plan))
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda _s: None, looks=looks)
    return steps, summary


def _mined(steps):
    return [e for e in steps.log if e[0] in ("pick", "fit", "mine", "by_tag", "fill", "order")]


def _states(ledger):
    return {j["item_id"]: j["state"] for j in ledger.jobs("ja")}


def test_after_the_update_nothing_queued_before_it_is_mined_while_the_question_asks(tmp_path, upgraded):
    # why: the report's path — the old version's queued and part-way episodes must wait for the yes like new ones
    _path, ledger = upgraded
    before = _states(ledger)
    steps, _summary = _run(tmp_path, ledger, looks=2)
    assert _mined(steps) == [], "no pick, no batch, no card while the question asks"
    assert _states(ledger) == before
    assert len(steps.anki.notes()) == 1, "only the card the old version made"


def test_a_queued_job_never_lifts_the_hold_only_a_finished_episode_with_cards_does(tmp_path, upgraded):
    # why: Kantan-B2 counted any log job (any state) as "already mined"; the map and the tests always meant a mined one
    _path, ledger = upgraded
    assert inbox.first_run_waits("ja", ledger) is True
    assert not ledger.mined_from_log("ja")


def test_not_now_sets_the_queued_ones_aside_and_leaves_the_part_way_one_where_it_stopped(tmp_path, upgraded):
    # why: the bar says "No cards for them": the old queued episodes go aside (their rows the learner's *Mine*),
    # the half-mined one keeps its cards and its place; and still nothing mines afterwards (Not now is no yes)
    path, ledger = upgraded
    assert actions.first_run_aside("ja", path) == 2
    needs.answer("ja", [needs.FIRST_CARDS_NOT_NOW])
    jobs = {j["item_id"]: j for j in ledger.jobs("ja")}
    assert [(jobs[i]["state"], jobs[i]["reason"]) for i in (2, 3)] == [("skipped", FIRST_RUN_ASIDE)] * 2
    assert jobs[1]["state"] == "mining"
    assert needs.first_cards_waiting("ja") is True, "the line itself is still unanswered"
    steps, _summary = _run(tmp_path, ledger, looks=2)
    assert _mined(steps) == []
    assert actions.first_run_aside("ja", path) == 0, "a second press sets nothing more aside"


def test_not_now_leaves_an_episode_the_learner_stopped_stopped(tmp_path, upgraded):
    # why: the review (KB2B-6) — a job the learner pressed *Stop* on must keep its stop and its reason, never come
    # back after the yes as a plain queued job that waits for no reason it says
    from app.connect.ledger import STOPPED_REASON
    path, ledger = upgraded
    job = ledger.job("ja", 2)
    assert ledger.ask_stop(job["id"])
    assert actions.first_run_aside("ja", path) == 1, "only job 3"
    assert (ledger.job_by_id(job["id"])["state"], ledger.job_by_id(job["id"])["reason"]) == ("waiting", STOPPED_REASON)
    assert actions.first_run_back("ja", path) == 1


def test_the_yes_mines_them_all_in_their_order(tmp_path, upgraded):
    # why: the learner's yes covers what was waiting: the part-way episode finishes first, then the queued ones
    _path, ledger = upgraded
    needs.answer("ja", [needs.FIRST_CARDS])
    steps, _summary = _run(tmp_path, ledger, looks=1)
    assert _states(ledger) == {1: "done", 2: "done", 3: "done"}
    assert [e[1] for e in steps.log if e[0] == "pick"] == [2, 3], "job 1 resumed from its batch, then 2, then 3"


def test_the_yes_after_not_now_brings_the_set_aside_ones_back_in_their_order(tmp_path, upgraded):
    # why: *Not now* then *Make cards* must end where a straight yes does — nothing lost to the set-aside
    path, ledger = upgraded
    actions.first_run_aside("ja", path)
    needs.answer("ja", [needs.FIRST_CARDS_NOT_NOW])
    needs.answer("ja", [needs.FIRST_CARDS])                 # *Make cards* (setup_wizard.first_cards): first …
    assert actions.first_run_back("ja", path) == 2          # … the set-aside ones queued again
    steps, _summary = _run(tmp_path, ledger, looks=1)
    assert _states(ledger) == {1: "done", 2: "done", 3: "done"}
    assert [e[1] for e in steps.log if e[0] == "pick"] == [2, 3]


def test_mine_now_always_works_while_the_question_asks(tmp_path, upgraded):
    # why: the learner's own press is a yes for that episode — held or set aside, it mines; the rest still wait
    path, ledger = upgraded
    actions.first_run_aside("ja", path)
    needs.answer("ja", [needs.FIRST_CARDS_NOT_NOW])
    with ledger.transaction():
        assert ledger.ask("ja", 3, "2026-11-19T10:00:00.000Z", store_id="store-1") is not None
    steps, _summary = _run(tmp_path, ledger, looks=1)
    assert [e[1] for e in steps.log if e[0] == "pick"] == [3]
    assert ledger.job("ja", 3)["state"] == "done" and ledger.job("ja", 1)["state"] == "mining"
    assert not ledger.mined_from_log("ja"), "an asked episode is no yes to the whole line"
    assert inbox.first_run_waits("ja", ledger) is True


def test_an_old_queued_job_the_learner_asked_for_and_that_finished_never_lifts_the_hold(tmp_path, upgraded):
    # why: *Mine now* on a log-queued job keeps its event; finished, it must not read as "the install already mined"
    _path, ledger = upgraded
    with ledger.transaction():
        ledger.ask("ja", 2, "2026-11-19T10:00:00.000Z", store_id="store-1")       # the open job carries the ask
    _run(tmp_path, ledger, looks=1)
    assert ledger.job("ja", 2)["state"] == "done" and ledger.job("ja", 2)["event_id"] is not None
    assert not ledger.mined_from_log("ja") and inbox.first_run_waits("ja", ledger) is True


def test_an_install_that_already_mined_from_the_log_mines_as_before(tmp_path):
    # why: a 3.0 learner whose Connect finished episodes from the log, the line left unanswered, keeps getting cards
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _run(tmp_path, ledger, looks=1, queue={"ja": [1]})
        with ledger.transaction():
            ledger.conn.execute("UPDATE jobs SET event_id = 100 + id")
            ledger.queue("ja", 2, "user", 102, store_id="store-1")
        assert ledger.mined_from_log("ja")
        needs.offer("ja", needs.FIRST_CARDS)
        assert inbox.first_run_waits("ja", ledger) is False
        steps, _summary = _run(tmp_path, ledger, looks=1)
        assert [e[1] for e in steps.log if e[0] == "pick"] == [2]


def test_a_seen_file_still_held_past_its_tries_holds_the_logs_jobs(tmp_path, upgraded, monkeypatch):
    # why: the window replacing the seen file while Connect reads it must never read as "no line": the jobs wait
    _path, ledger = upgraded

    def held(language, strict=False):
        raise PermissionError("the file is being replaced")
    monkeypatch.setattr(needs, "_load", held)
    monkeypatch.setattr(needs.time, "sleep", lambda _s: None)
    assert runner._open_jobs(ledger, "ja", {}) == []


def test_no_line_offered_mines_the_logs_jobs_as_before(tmp_path):
    # why: a library set up with nothing in the line (no question) is the rule as it always was
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            ledger.queue("ja", 1, "user", 101, store_id="store-1")
        steps, _summary = _run(tmp_path, ledger, looks=1)
        assert ledger.job("ja", 1)["state"] == "done"


def test_the_loop_reads_the_seen_file_again_only_once_the_window_wrote_it(tmp_path, monkeypatch):
    # why: S19 (the review's waste lens) — `_open_jobs` runs many times a pass; an answered install's every call must
    # not re-read the seen file; yet a line offered meanwhile (the window's write) must hold at once
    reads = []
    real = needs._load

    def counted(language, strict=False):
        reads.append(language)
        return real(language, strict)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            ledger.queue("ja", 1, "user", 101, store_id="store-1")
        needs.answer("ja", ["item:1"])                      # a seen file, no line offered
        monkeypatch.setattr(needs, "_load", counted)
        for _ in range(5):
            assert [j["item_id"] for j in runner._open_jobs(ledger, "ja", {})] == [1]
        assert len(reads) == 1, "read once while unchanged"
        monkeypatch.setattr(needs, "_load", real)
        needs.offer("ja", needs.FIRST_CARDS)               # the window writes: the line offered
        assert runner._open_jobs(ledger, "ja", {}) == [], "read again at once: held"


def test_a_ledger_read_that_fails_holds_the_logs_jobs(tmp_path, upgraded, monkeypatch):
    # why: the hold's own query failing (a locked or damaged ledger) is no yes either
    import sqlite3
    _path, ledger = upgraded

    def broken(self, language):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(Ledger, "mined_from_log", broken)
    assert runner._open_jobs(ledger, "ja", {}) == []


def test_no_ledger_sets_nothing_aside(tmp_path):
    # why: the window never makes Connect's ledger — *Not now* before Connect's first look writes nothing
    path = str(tmp_path / "none.sqlite")
    assert actions.first_run_aside("ja", path) == 0 and actions.first_run_back("ja", path) == 0
    assert not (tmp_path / "none.sqlite").exists()


# --- the inbox: Not now is no yes (the suite's real library) ------------------------------------------------------- #
def _library(lang, line=2):
    c.library(lang)
    with c.store(lang) as s:
        s.bookkeeping({"mine_line": line}, copy_carries=True)


def _consume(lang):
    with c.store(lang) as s, Ledger() as ledger:
        return inbox.consume(s, lang, ledger)


def _enter_one(lang):
    with c.store(lang) as s:
        moved = s.ids("now")[-1]
        library.place(s, moved, "now", before_id=s.ids("now")[0], source="user")
    return moved


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_after_not_now_a_new_episode_entering_the_top_is_never_mined_by_itself(lang):
    # why: Sonic's ruling — after *Not now* nothing mines automatically: an episode the learner moves into the top 20
    # gets no job (its row says *Mine*: his own press)
    _library(lang)
    needs.offer(lang, needs.FIRST_CARDS)
    _consume(lang)
    actions.first_run_aside(lang)
    needs.answer(lang, [needs.FIRST_CARDS_NOT_NOW])
    _enter_one(lang)
    assert _consume(lang)["queued"] == []
    with Ledger() as ledger:
        assert ledger.jobs(lang) == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_part_not_now_set_aside_counts_as_never_queued_for_a_shows_catch_up(lang):
    # why: a show is one unit (Michi-EO): a part *Not now* set aside counts as never queued for the ask's catch-up
    _library(lang)
    with c.store(lang) as s:
        first, later = s.ids("now")[0], s.ids("now")[1]
    with Ledger() as ledger, ledger.transaction():
        ledger.queue(lang, first, "user", 7, store_id="store-1")
        assert ledger.set_aside_first_run(lang) == 1
        assert not ledger.ever_had_job(lang, first)
        ledger.queue(lang, later, "user", None, store_id="store-1")
        assert ledger.ever_had_job(lang, later)
