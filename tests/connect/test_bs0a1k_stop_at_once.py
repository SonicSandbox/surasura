"""Sonic's report #BS0A1K (alpha 9.1, 2026-11-02): *Stop* on a book's part read *Stopping…* for minutes.

"Taking forever to stop." His ledger: job 170 (a part of a book) ran in Anki Miner's first stage for 11 minutes; the
Stop was pressed at 03:02:06 and still read *Stopping…* at 03:03:27. Anki Miner 3.11.0 reads its cancel file between
its steps, never inside one, and a reading source's first step parses the whole book; Connect only ever wrote the
cancel file, so the Stop waited the whole parse.

One rule now (`anki_miner.before_anki`, `stopping.END`): Anki Miner writes to Anki (notes and their media) only in its
fifth stage, announced in its progress file before the first write, and it looks at the cancel right before that
stage — so a Stop it hasn't acted on STOP_GRACE_S after its cancel file, its progress still before that stage, ends
the program: nothing reached Anki, the batch is the cancelled one (`cancelled`, `stopped`) the runner already reads
back by the job's tag. In its fifth stage it is never ended: it adds the cards it has ready (the hover says so). Read
in Anki Miner 3.11.0's source: an earlier one is waited for, as before.
The wait for another writer (Junban's reorder) ends at the press too.

What a wrong answer costs: a Stop that does nothing for minutes (the app looks broken), or a card half-made by a
program ended while it wrote to Anki.

The fake Anki Miner (`--api` as API.md documents it) with a step that never reads its cancel file; real Japanese words
(`test_anki_miner.words`); never a live Anki.
"""
import json
import os
import threading
import time

import pytest

from app.connect import anki_miner, feed, runner, status, stopping
from app.connect.ledger import Ledger
from app.services import view_rows
from tests.connect.test_anki_miner import batch, words  # noqa: F401  (fixtures)

QUICK = 4.0                 # seconds from the press: the grace (1.5 s), a poll and the program's end, with room to spare


def _deaf_run(fake_miner, monkeypatch, progress, deaf=30, app="3.11.0", **plan):
    monkeypatch.setattr(anki_miner, "POLL_S", 0.1)
    fake_miner.plan(app=app, progress=progress, progress_every=0.05, deaf=deaf, **plan)


def _run_dir(fake_miner):
    return fake_miner.run_files()[0]["run_dir"]


def _press_once_under_way(fake_miner):
    """(should_stop, pressed): Stop pressed once the mine call is under way, `pressed` its time. A Stop is timed
    from its press: the program's starts before it (a slow runner's seconds) are no part of it (flakes-2026-11-05 #2)."""
    pressed = []

    def should_stop():
        if not pressed and "mine" in fake_miner.commands():
            pressed.append(time.monotonic())
        return bool(pressed)
    return should_stop, pressed


# --- before its card stage: ended within seconds, nothing reached Anki --------------------------------------------- #
@pytest.mark.parametrize("progress, media", [([[1, 5, 0, 0]], True), ([[3, 5, 2, 6], [4, 5, 0, 0]], True),
                                             ([], False)],
                         ids=["parsing-a-whole-book", "media-and-definitions", "still-setting-up"])
def test_a_stop_anki_miner_cant_hear_before_its_card_stage_ends_it_within_seconds(batch, fake_miner, words,  # noqa: F811
                                                                                 monkeypatch, progress, media):
    _deaf_run(fake_miner, monkeypatch, progress, media=media)
    should_stop, pressed = _press_once_under_way(fake_miner)
    with pytest.raises(anki_miner.AnkiMinerError) as raised:
        batch(should_stop=should_stop)
    took = time.monotonic() - pressed[0]
    assert took < QUICK, f"Stop took {took:.1f} s"
    assert raised.value.kind == "cancelled" and raised.value.stopped is True, \
        "the batch the runner reads back by its tag: never a crash, never counted as Anki Miner failing"
    assert raised.value.code == "CANCELLED"
    assert not any("heard" in c for c in fake_miner.calls()), "the program was ended, not waited for"
    folder = os.path.join(_run_dir(fake_miner), "job-1-1")
    assert not os.path.exists(os.path.join(folder, "cancel")), "no cancel file left for the next call"
    assert not os.path.exists(os.path.join(folder, "media")), "the clips it cut go, as its own clean-up takes them"


def test_a_stop_it_hears_in_time_is_never_ended(batch, fake_miner, words, monkeypatch):  # noqa: F811
    # a step that reads the cancel file (no deaf step): it stops by itself and keeps what it made, as before
    monkeypatch.setattr(anki_miner, "POLL_S", 0.1)
    fake_miner.plan(progress=[[5, 5, 0, 6]], progress_every=0.05, cancel_at=2)
    done = batch(should_stop=lambda: "mine" in fake_miner.commands())
    assert done["stopped"] is True
    assert [o["outcome"] for o in done["outcomes"]][:2] == ["made", "made"]


# --- in its card stage, or not sure: never ended ------------------------------------------------------------------- #
def test_a_stop_in_the_card_stage_is_never_ended_and_keeps_the_cards_made(batch, fake_miner, words,  # noqa: F811
                                                                           monkeypatch):
    _deaf_run(fake_miner, monkeypatch, [[4, 5, 0, 0], [5, 5, 0, 6]], deaf=3, cancel_at=1)
    began = time.monotonic()
    done = batch(should_stop=lambda: "mine" in fake_miner.commands())
    assert time.monotonic() - began >= 3, "waited for it to finish its card"
    assert any("heard" in c for c in fake_miner.calls())
    assert done["stopped"] is True
    outcomes = [o["outcome"] for o in done["outcomes"]]
    assert outcomes[0] == "made" and all(o in runner.UNSETTLED for o in outcomes[1:]), \
        "the card it made is kept whole; the rest wait for your next Mine now"


@pytest.mark.parametrize("app", ["3.10.1", "3.5.0", None])
def test_an_anki_miner_before_3_11_is_waited_for_as_before(batch, fake_miner, words, monkeypatch, app):  # noqa: F811
    # its progress was read in 3.11.0's source only: an earlier one may not announce its card stage first
    _deaf_run(fake_miner, monkeypatch, [[1, 5, 0, 0]], deaf=2.5, app=app, cancel_at=0)
    began = time.monotonic()
    with pytest.raises(anki_miner.AnkiMinerError) as raised:
        batch(should_stop=lambda: "mine" in fake_miner.commands())
    assert time.monotonic() - began >= 2.5 and any("heard" in c for c in fake_miner.calls()), "never ended"
    assert raised.value.kind == "cancelled" and raised.value.stopped is True, "it stopped by itself, as before"


@pytest.mark.parametrize("text, media, before", [
    (None, False, True),                                                # nothing yet: still setting up
    (None, True, False),                                                # under way, its progress never written
    ({"stage": 0, "stages": 0, "done": 0, "total": 0}, True, True),
    ({"stage": 1, "stages": 5, "done": 0, "total": 0}, True, True),
    ({"stage": 4, "stages": 5, "done": 3, "total": 6}, True, True),
    ({"stage": 5, "stages": 5, "done": 0, "total": 6}, True, False),    # writing to Anki: never ended
    ("{half a writ", True, False),                                      # can't be read now: not sure, not ended
    ({"stage": True, "stages": 5, "done": 0, "total": 0}, True, False),
], ids=["absent", "never-written", "stage-0", "parsing", "definitions", "cards", "unreadable", "not-a-number"])
def test_before_anki_is_sure_only_before_the_card_stage(tmp_path, text, media, before):
    folder = tmp_path / "job-1-1"
    folder.mkdir()
    if media:
        (folder / "media").mkdir()
    if text is not None:
        (folder / anki_miner.PROGRESS).write_text(text if isinstance(text, str) else json.dumps(text),
                                                  encoding="utf-8")
    progress = anki_miner.read_progress(str(tmp_path), "job-1-1")
    assert anki_miner.before_anki(str(tmp_path), "job-1-1", progress) is before


# --- the wait for another writer ----------------------------------------------------------------------------------- #
def test_a_stop_while_another_writer_holds_anki_ends_the_wait_at_once(batch, fake_miner):  # noqa: F811
    # Junban's reorder holds Anki's write lock; Connect's batch waits for it (10 s) — a Stop ends that wait
    from app import anki_connect, locks
    got = {}
    with locks.take(anki_connect.WRITER_LOCK, "順 reorder"):
        pressed = threading.Event()

        def other():
            began = time.monotonic()
            try:
                batch(wait=10.0, should_stop=pressed.is_set)
            except Exception as e:      # noqa: BLE001 — the test reads what it was
                got["e"], got["took"] = e, time.monotonic() - began
        t = threading.Thread(target=other)
        t.start()
        time.sleep(0.3)
        pressed.set()
        t.join(10)
    assert isinstance(got.get("e"), stopping.Stopped), got
    assert got["took"] < 2.0, "the press ended the wait, not its 10 s"
    assert "mine" not in fake_miner.commands(), "nothing sent to Anki Miner"


def test_no_stop_another_writer_is_waited_for_as_before(batch, fake_miner):  # noqa: F811
    from app import anki_connect, locks
    got = {}
    with locks.take(anki_connect.WRITER_LOCK, "順 reorder"):
        def other():
            try:
                batch(wait=0.3, should_stop=lambda: False)
            except anki_miner.AnkiMinerError as e:
                got["e"] = e
        t = threading.Thread(target=other)
        t.start()
        t.join(10)
    assert got["e"].kind == "writer-busy" and "順 reorder" in got["e"].message


# --- the runner: a stop ended this way is the stop it already knew ------------------------------------------------- #
def test_the_runner_stops_the_job_and_keeps_no_failure(tmp_path, monkeypatch):
    from tests.connect.fake_steps import FakeSteps
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        with led.transaction():
            job_id = led.queue("ja", 1, "user", None, store_id="store-1")
        steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}})

        def ended_before_anki(lang, job, picked, words, attempt):
            # what Steps.mine answers for an AnkiMinerError `cancelled` marked stopped (runner.Steps.mine)
            led.ask_stop(job_id)
            return {"outcomes": [dict(runner._unsure(w)) for w in words], "app": None, "doubt": True,
                    "stopped": True}
        steps.mine = ended_before_anki
        runner.run({}, ["ja"], steps=steps, ledger=led, sleep=lambda s: None, looks=1)
        job = led.job_by_id(job_id)
        assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.STOPPED_BY_YOU, "mining")
        assert (job["failures"] or 0) == 0, "your Stop is no failure of Anki Miner's"
        assert ("by_tag", 1) in steps.log, "read back by the job's tag: anything that did reach Anki is recorded"


# --- what the row says --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("stage, writing", [(1, None), (4, None), (5, True)])
def test_a_stopping_row_says_it_adds_its_cards_only_in_the_card_stage(tmp_path, monkeypatch, stage, writing):
    monkeypatch.setattr(status, "running", lambda: True)
    path = str(tmp_path / "status-ledger.sqlite")
    with Ledger(path) as led:
        job_id = led.queue("ja", 101, "test", "ev-1")
        led.set_state(job_id, "mining", progress={"stage": stage, "stages": 5, "done": 0, "total": 6})
        assert led.ask_stop(job_id)
    record = status.read(["ja"], path=path)
    item = feed.build(record, "ja").items[101]
    assert (item.stopping, item.writing_cards) == (True, writing)
    st = view_rows._connected(view_rows.Status("mining", "", "", "accent"), item, "video")
    assert st.label == view_rows.STRINGS["stopping"], "the pill keeps its one word (no second Stop)"
    assert st.tip == view_rows.STRINGS["tip_stopping_cards" if writing else "tip_stopping"]
