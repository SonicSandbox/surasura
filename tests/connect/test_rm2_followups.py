"""Michi-RM2 (3.0.2), the follow-ups of Mattias #5's fix (`test_rm_failed_part_again.py`):

- A book row whose earlier part failed (*Try again*) and a later part that waits on the learner — *Not timed*, *No
  video*, Anki closed (a warn status): the row says the later one, as it says a part mining; a plain wait still
  gives way to *Try again*. What a wrong answer would cost: the learner fixes the failed part and never learns the
  next one waits for a video or a timing check.
- The `alone:<job>` record (what Anki said, the words it refused alone) leaves the ledger once the part has gone
  through — any job of the item ending done, dropped, skipped or undone, never a level raise, which tries none of
  those words. A failed part keeps its record (the problem report names its words, SPEC send-report §2.7). What a
  wrong answer would cost: a ledger that grows a row for every refusal forever; or a report that loses a failed
  part's words.

Against `FakeSteps` and a real ledger; real Japanese words. Never a live Anki, no sleeps.
"""
from types import SimpleNamespace

from app.connect import feed, runner
from app.connect.ledger import Ledger, _now
from app.services import view_rows
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("一生懸命", "いっしょうけんめい"), ("気配", "けはい")]
FAILED = feed.Item(kind=feed.FAILED, words=feed.WORDS[feed.FAILED], tip=runner.MINE_FAILED, job=4, made=0, total=3)


def _item(kind, tip=""):
    return feed.Item(kind=kind, words=feed.WORDS[kind], tip=tip, job=5, made=0, total=2)


def _row(connect):
    eps = [SimpleNamespace(id=n, cards=0, deleted=n == 1, online=None) for n in (1, 2)]
    return view_rows._row_connected(view_rows.Status("mine", "Mine", "", "ink"), eps, connect, "book")


def test_a_later_part_waiting_on_you_shows_over_an_earlier_try_again():
    assert _row({1: FAILED, 2: _item(feed.NOT_TIMED, "Not timed to its video")}).label == \
        view_rows.STRINGS["not_timed"]
    assert _row({1: FAILED, 2: _item(feed.NO_VIDEO, runner.NO_VIDEO)}).kind == "no_media"
    assert _row({1: FAILED, 2: _item(feed.ANKI, runner.ANKI_CLOSED)}).tone == "warn"


def test_a_later_plain_wait_still_gives_way_to_try_again():
    assert _row({1: FAILED, 2: _item(feed.WAITING)}).kind == "retry"
    assert _row({1: FAILED, 2: _item(feed.BATTERY, runner.ON_BATTERY)}).kind == "retry"
    assert _row({1: FAILED}).kind == "retry"


def _refused_part(tmp_path):
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "refuse_words": [WORDS[1][0]]}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed"]
        assert runner._alone(ledger, ledger.jobs("ja")[0]["id"])["words"] == [WORDS[1][0]]
    return steps, path


def _alone_keys(ledger):
    return [k for (k,) in ledger.conn.execute("SELECT key FROM meta WHERE key LIKE 'alone:%'")]


def test_the_alone_record_goes_once_the_part_has_gone_through(tmp_path):
    steps, path = _refused_part(tmp_path)
    steps.plan.update(refuse_words=[], queue={})          # Anki takes it now: *Try again*
    with Ledger(path) as ledger:
        with ledger.transaction():
            ledger.ask("ja", 1, _now(), store_id="store-1")
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed", "done"]
        assert _alone_keys(ledger) == [], "the failed job's record and any other of the item's: gone"


def test_a_failed_part_keeps_its_record_through_a_level_raise_and_a_new_failure(tmp_path):
    steps, path = _refused_part(tmp_path)
    steps.plan.update(queue={}, level=[("ja", 1, [["溜め息", "ためいき"]])])
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [(j["kind"], j["state"]) for j in ledger.jobs("ja")] == [("mine", "failed"), ("level", "done")]
        assert len(_alone_keys(ledger)) == 1, "a level raise tries none of its words: the record stays"
        with ledger.transaction():
            ledger.ask("ja", 1, _now(), store_id="store-1")
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")][-1] == "failed"
        assert len(_alone_keys(ledger)) == 2, "each failed try keeps its own: the report names their words"


def test_a_skipped_part_keeps_its_record_for_when_it_is_queued_again(tmp_path):
    """Review B1: a part set aside mid-way (Anki Miner no longer reads books: skipped) is queued again later under the
    same job, its failures kept — so it keeps its record, and goes on a word at a time, never the whole batch again."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "refuse_words": [WORDS[1][0]]}
    steps = FakeSteps(str(tmp_path), plan)
    original = steps.mine

    def books_wait_on_the_retry(lang, job, picked, words, attempt):
        if attempt == 2:
            raise runner.Skip(runner.BOOKS_WAIT)
        return original(lang, job, picked, words, attempt)
    steps.mine = books_wait_on_the_retry
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["skipped"]
        assert len(_alone_keys(ledger)) == 1


def test_two_failed_parts_the_row_names_the_first():
    """Review N6: a second failed part never replaces the first's *Try again* (its own counts in the tip)."""
    second = FAILED._replace(job=6, made=1, total=4)
    eps = [SimpleNamespace(id=n, cards=0, deleted=False, online=None) for n in (1, 2)]
    st = view_rows._row_connected(view_rows.Status("mine", "Mine", "", "ink"), eps, {1: FAILED, 2: second}, "book")
    assert st.tip == view_rows.STRINGS["tip_retry_none"].format(tip=runner.MINE_FAILED)
