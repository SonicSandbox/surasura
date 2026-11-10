"""LF56 mutant gaps (laptop round 9 #56: Stop reaches every step): the cases the change's own tests left open, each named
for what a wrong answer costs. Real child processes (a sleeping Python standing in for a program Connect waits on),
`FakeSteps` with real Japanese words and a real ledger where a job is needed; never a live Anki, tsubasa or Anki Miner.
"""
import json
import subprocess
import sys
import time

import pytest

from app.connect import anki_miner, feed, runner, status, stopping
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps, Killed
from tests.connect.test_lf4_stop import _queue, _run, ledger  # noqa: F401  (fixture)


def _sleeper(seconds):
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({float(seconds)!r})"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.mark.parametrize("look_up", [True, False])
def test_a_sliced_wait_gives_up_at_its_timeout_not_later(look_up):
    # tsubasa's check and Anki Miner's calls are waited for in slices: the sliced wait must still end at its own
    # timeout. A wait that overran it (twice the timeout, or seconds past it) holds the job that long after a program
    # stopped answering — the 120 s fit check would sit for minutes before *asked again*
    proc = _sleeper(30)
    try:
        began = time.monotonic()
        with stopping.watching(lambda: False), pytest.raises(subprocess.TimeoutExpired):
            stopping.wait(proc, 1.0, on_poll=None if look_up else (lambda: None), look_up=look_up, every=0.1)
        took = time.monotonic() - began
        assert took < 1.8, f"the wait gave up after {took:.2f} s, its timeout 1 s"
    finally:
        stopping.end(proc)


def test_an_export_anki_miner_answered_for_but_that_cant_be_read_leaves_the_last_whole_export(tmp_path, monkeypatch):
    # Anki Miner says ok but its export is cut (a disk full, a crash after its answer): the export is read before it is
    # put in place, so the run folder keeps the last whole one. Put in place first, a cut export would replace it, and
    # the mapping the next run reads after a kill would be {}
    out = tmp_path / "run" / "settings-export.json"
    out.parent.mkdir()
    out.write_text(json.dumps({"anki_miner_settings": 1, "settings": {"anki_deck_name": "前の設定"}},
                              ensure_ascii=False), encoding="utf-8")
    before = out.read_bytes()

    def api(path, args, timeout=anki_miner.QUICK_TIMEOUT, on_poll=None):
        written = args[args.index("--out") + 1]
        with open(written, "w", encoding="utf-8") as f:
            f.write('{"anki_miner_settings": 1, "settings": {"anki_deck_na')
        return {"schema": 1, "ok": True, "command": "settings-export", "result": {}}
    monkeypatch.setattr(anki_miner, "api", api)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.settings_export("anki_miner.exe", "ja", str(out))
    assert e.value.kind == "crashed"
    assert out.read_bytes() == before, "the last whole export stands"
    assert sorted(p.name for p in out.parent.iterdir()) == ["settings-export.json"], "no part left behind"


def test_a_job_waiting_to_order_its_made_cards_is_never_stopped_nor_offered_a_stop(tmp_path, monkeypatch):
    # its cards are made and filled; it waits only for Anki to put them in order. A Stop taken there would hold made
    # cards out of order until Mine now, and the stone would offer a press the job can't act on
    monkeypatch.setattr(status, "running", lambda: True)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as led:
        ordering = led.queue("ja", 501, "test", "ev-1")
        led.set_state(ordering, "waiting", reason=runner.ANKI_CLOSED, resume="ordering")
        assert not led.ask_stop(ordering), "a press on a job waiting to order is refused, nothing written"
        assert not led.stop_asked(ordering)
    record = status.read(["ja"], path=path)
    entry = next(j for j in record["languages"]["ja"]["jobs"] if j["item"] == 501)
    assert entry["resume"] == "ordering" and entry["stopping"] is False
    assert feed.build(record, "ja").items[501].stoppable is None


def _press_at_first_word(ledger, job_id):
    def press(n, _job):
        if n == 1:
            ledger.ask_stop(job_id)
    return press


def test_a_stop_while_the_library_is_busy_still_stops_the_job_and_names_its_clips(tmp_path, ledger):  # noqa: F811
    # Stop mid-batch while the library can't take the cards: the job stops all the same (the resumed job records them),
    # its clips named before Anki's next sync. Were the busy library's wait let through, the press would stay pending,
    # the stone would read the library's wait, not Stopped, and the made cards' clips would sync unnamed
    job_id = _queue(ledger, 1)
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "on_word": _press_at_first_word(ledger, job_id),
                                              "library_busy": True})
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.STOPPED_BY_YOU, "mining")
    assert ledger.held_by_stop(job) and not ledger.stop_asked(job_id), "the press used up: it waits for your ask"
    assert steps.records == [], "the library was busy: nothing recorded now"
    assert any(e[0] == "name_media" and e[1] == 1 for e in steps.log), "the made cards' clips named all the same"


def test_a_stop_on_a_job_of_a_library_set_up_again_writes_nothing_into_the_new_library(tmp_path, ledger):  # noqa: F811
    # a job that started mining for the old library (killed mid-batch), then stopped while it finishes in a library
    # set up again: the cards it made are the old library's — the new one never gets them (P2.4 D07's rule, at a stop)
    killed = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "queued_store": "old",
                                       "store_id": "old", "kill": "mid-batch:1"})
    with pytest.raises(Killed):
        runner.run({}, ["ja"], steps=killed, ledger=ledger, sleep=lambda s: None, looks=1)
    job_id = ledger.jobs("ja")[0]["id"]
    assert ledger.batches(job_id)[-1]["state"] == "running", "precondition: the job started mining"
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "store_id": "new",
                                              "on_word": _press_at_first_word(ledger, job_id)})
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.STOPPED_BY_YOU)
    assert steps.records == [], "a job from a library set up again writes nothing into the new one, stopped or not"


def test_a_press_that_outlived_the_stop_point_never_reads_stopping(tmp_path, monkeypatch):
    # pressed as the pick found nothing left to mine (the job goes straight to filling its made cards): the job is past
    # the stop point and finishes — its stone never reads *Stopping…* for a stop that will never come, nor offers one
    monkeypatch.setattr(status, "running", lambda: True)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as led:
        job_id = led.queue("ja", 601, "test", "ev-1")
        led.set_state(job_id, "picking")
        assert led.ask_stop(job_id)
        led.set_state(job_id, "filling")
        assert led.stop_asked(job_id), "precondition: the press outlived the stop point"
    record = status.read(["ja"], path=path)
    entry = next(j for j in record["languages"]["ja"]["jobs"] if j["item"] == 601)
    assert entry["stopping"] is False
    item = feed.build(record, "ja").items[601]
    assert (item.stopping, item.stoppable) == (None, None)
