"""Anki Miner's update notice: the edges the mutant pass found untested (P3.2-AMN, 2026-10-13).

What a wrong answer would cost: a state file a stray tool rewrote as a list blocks the check for good; a notice
linking a download or another site from a hand-edited state; Anki Miner 3.10 read as older than 3.9 (a notice for an
update already installed); the state file rewritten when nothing changed (S19); Connect's exit waiting six seconds
more after a long run, or one second too little for a slow answer; an update-lock look at every exit with no check
running; the exit's wait inside Connect's lock (a Connect kicked meanwhile refused as running); a raise from the wait
replacing Connect's answer; the notice read before the stamp (a stale notice kept under a fresh stamp). The fetch is
always stood in for: no test here touches the network.
"""
import datetime
import json
import os
import threading
import time

import pytest

from app.connect import am_release, runner

ON = {"connect_enabled": True}
DAY = 24 * 3600
NOON = datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
PAGE = "https://github.com/0xzerolight/anki_miner/releases/tag/v3.8.0"


def release(tag="v3.8.0", url=PAGE):
    return {"tag_name": tag, "html_url": url, "assets": []}


def _write_state(state):
    os.makedirs(os.path.dirname(am_release.path()), exist_ok=True)
    with open(am_release.path(), "w", encoding="utf-8") as f:
        json.dump(state, f)


@pytest.fixture(autouse=True)
def never_the_real_fetch(monkeypatch):
    """The real `_fetch` (urllib to api.github.com) fails the test if anything reaches it; the thread slot empty."""
    def real(*_a, **_k):
        raise AssertionError("the real GitHub fetch was called")
    monkeypatch.setattr(am_release, "_fetch", real)
    monkeypatch.setattr(am_release, "_thread", None)


# --------------------------------------------------------------------------- #
# The state file
# --------------------------------------------------------------------------- #
def test_a_state_file_holding_a_json_list_is_due_and_rewritten():
    """Mutant B04: JSON that isn't an object (a list) is "never checked", never "held just now" — read as held, no
    check would ever run again."""
    _write_state(["not", "an", "object"])
    asked = []
    out = am_release.check(ON, now=NOON, fetch=lambda: asked.append(1) or release())
    assert asked == [1], "a state file holding a list must not block the check"
    assert out["latest"] == "3.8.0"
    with open(am_release.path(), encoding="utf-8") as f:
        assert json.load(f)["latest"] == "3.8.0", "the list is replaced by the state"


def test_a_failed_or_unchanged_answer_writes_nothing_after_the_claim(monkeypatch):
    """Mutants B22 / W14: the answer is written again only when it changed (RUNBOOK-AMN: written only when it changed)
    — a failed check, or the same release as kept, leaves the claim as the only write."""
    am_release.check(ON, now=NOON, fetch=lambda: release())
    writes = []
    real_write = am_release._write
    monkeypatch.setattr(am_release, "_write", lambda state: writes.append(dict(state)) or real_write(state))

    def offline():
        raise OSError("offline")
    am_release.check(ON, now=NOON + DAY, fetch=offline)
    assert writes == [{"checked_at": "2026-10-14T12:00:00Z", "latest": "3.8.0", "url": PAGE}], \
        "a failed check: only the claim is written"
    writes.clear()
    am_release.check(ON, now=NOON + 2 * DAY, fetch=lambda: release())
    assert len(writes) == 1, "the same release again: only the claim is written"


# --------------------------------------------------------------------------- #
# The notice: the link and the version compare
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", [
    "https://github.com/0xzerolight/anki_miner/releases/download/v3.8.0/AnkiMiner-Setup.exe",
    "https://example.com/anki_miner",
])
def test_a_hand_edited_state_url_never_reaches_the_notice(url):
    """Mutant B16: `notice` applies the releases-page rule again, so a state edited by hand (or by an older build)
    can't make the link a download or another site."""
    _write_state({"checked_at": "2026-10-13T12:00:00Z", "latest": "3.8.0", "url": url})
    assert am_release.notice("3.7.0") == {"version": "3.8.0", "url": am_release.RELEASES}


def test_installed_compares_versions_by_their_numbers(monkeypatch):
    """Mutant B17: the newer of the installer's and the setup record's versions is chosen by its numbers — 3.10.0 is
    newer than 3.9.0 (as text it sorts first)."""
    from app.connect import anki_miner, setup
    setup.write_record({"anki_miner": {"path": "C:/x/AnkiMiner.exe", "app": "3.9.0"}})
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.10.0")
    assert am_release.installed() == "3.10.0"
    _write_state({"checked_at": "2026-10-13T12:00:00Z", "latest": "3.10.0", "url": PAGE})
    assert am_release.notice(am_release.installed()) is None, "3.10.0 installed: no notice for 3.10.0"


@pytest.mark.parametrize("latest, installed", [("4.0", "4"), ("4", "4.0.0"), ("3.0", "3")])
def test_a_release_differing_only_by_trailing_zeros_is_no_notice(latest, installed):
    """Mutant B18: trailing zeros are dropped down to one number — 4 is 4.0 is 4.0.0."""
    _write_state({"checked_at": "2026-10-13T12:00:00Z", "latest": latest, "url": PAGE})
    assert am_release.notice(installed) is None


def test_a_version_with_a_prefix_counts_as_known():
    """Mutant B19: a version counts as known when it holds a digit anywhere — "v3.7.0" too."""
    assert am_release.known("v3.7.0") and am_release.known("AnkiMiner 3.7.0")
    _write_state({"checked_at": "2026-10-13T12:00:00Z", "latest": "3.8.0", "url": PAGE})
    assert am_release.notice("v3.7.0") == {"version": "3.8.0", "url": PAGE}


# --------------------------------------------------------------------------- #
# The check's thread and Connect's exit
# --------------------------------------------------------------------------- #
def test_a_check_that_ended_is_not_running(monkeypatch):
    """Mutant B26: `running()` is the thread being alive — a check that ended asks Connect's exit for nothing."""
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(am_release, "_fetch", lambda: release())
    thread = am_release.start(ON)
    assert thread is not None
    thread.join(5)
    assert am_release.running() is False


def test_finish_after_a_long_run_gives_a_check_past_its_bound_nothing(monkeypatch):
    """Mutant B27: the exit waits what is LEFT of TIMEOUT_S + 1 s from the check's start — a run that lasted longer
    than that leaves a hung check behind at once, never six seconds more."""
    gate = threading.Event()
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(am_release, "_fetch", lambda: gate.wait(20) and release())
    try:
        assert am_release.start(ON) is not None
        monkeypatch.setattr(am_release, "_started", time.monotonic() - 100)      # the run lasted 100 s
        started = time.monotonic()
        assert am_release.finish() is False
        assert time.monotonic() - started < 1.0, "a check past its bound must not be waited for"
    finally:
        gate.set()
    am_release._thread.join(5)


def test_finish_waits_the_extra_second_past_the_socket_timeout(monkeypatch):
    """Mutants B28 / W19: the bound is TIMEOUT_S + 1 s from the check's start — with TIMEOUT_S 0, an answer coming
    after half a second is still waited for."""
    monkeypatch.setattr(am_release, "TIMEOUT_S", 0)
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(am_release, "_fetch", lambda: time.sleep(0.5) or release())
    assert am_release.start(ON) is not None
    assert am_release.finish() is True, "an answer inside TIMEOUT_S + 1 s must be waited for"
    with open(am_release.path(), encoding="utf-8") as f:
        assert json.load(f)["latest"] == "3.8.0"


def _loop_with(monkeypatch, summary=None, raised=None, finish=None, staged=False, running=True):
    """`connect_verbs._loop` with the run, the staged look and the check stood in for -> (finished, looks)."""
    from app import library_store
    from app.cli import connect_verbs
    finished, looks = [], []

    def run(loaded, languages, looks=None):
        if raised is not None:
            raise raised
        return dict(summary or {})
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(connect_verbs, "_pending", lambda lang: False)
    monkeypatch.setattr(library_store, "update_staged", lambda *a, **k: looks.append(k.get("looks")) or staged)
    monkeypatch.setattr(am_release, "running", lambda: running)
    monkeypatch.setattr(am_release, "finish", finish or (lambda: finished.append(1) or True))
    return connect_verbs._loop, finished, looks


@pytest.mark.parametrize("stopped", [runner.SWITCHED_OFF, "cancelled"])
def test_connects_exit_waits_for_the_check_after_a_run_switched_off_or_cancelled(monkeypatch, stopped):
    """Mutant B30: only a run that stopped for an update skips the exit's wait (the updater waits on this exit); a run
    switched off or cancelled still lets the day's one check finish (its answer kept, not lost until tomorrow)."""
    loop, finished, _looks = _loop_with(monkeypatch, summary={"stopped": stopped})
    assert loop(ON, ["ja"]) == {"stopped": stopped}
    assert finished == [1]


def test_with_no_check_running_the_exit_looks_at_no_update_lock(monkeypatch):
    """Mutant B31: no check running → Connect's exit returns before the update-lock look (PROBE_LOOKS looks, ~0.1 s,
    at every exit otherwise)."""
    loop, finished, looks = _loop_with(monkeypatch, running=False)
    loop(ON, ["ja"])
    assert looks == [] and finished == []


def test_a_wait_that_raises_never_escapes_connects_exit(monkeypatch):
    """Mutant B32: the exit's wait is a courtesy — anything it raises (not only an OSError) never replaces Connect's
    answer."""
    def broken():
        raise RuntimeError("the check's thread is gone")
    loop, _finished, _looks = _loop_with(monkeypatch, summary={"languages": {}}, finish=broken)
    assert loop(ON, ["ja"]) == {"languages": {}}


def test_the_exit_wait_runs_outside_connects_lock(monkeypatch):
    """Mutant B33: the wait (up to 6 s) happens after Connect's lock is released, so a Connect kicked meanwhile is
    never refused as already running."""
    from app import locks
    from app.connect import kick
    seen = []
    loop, _finished, _looks = _loop_with(
        monkeypatch, finish=lambda: seen.append(locks.held_in_process(kick.LOCK)) or True)
    loop(ON, ["ja"])
    assert seen and all(holder is None for holder in seen), "Connect's lock was held during the exit's wait"


# --------------------------------------------------------------------------- #
# The status record: the stamp first
# --------------------------------------------------------------------------- #
def test_the_status_record_takes_its_stamp_before_it_reads_the_notice(monkeypatch):
    """Mutant B37: the stamp is taken before the notice is read, so a state written between the two moves the NEXT
    stamp and the row reads again; read the other way, a fresh stamp would carry a stale notice until the next day."""
    from app.connect import status
    order = []
    real_stamp, real_update = status.stamp, status.anki_miner_update
    monkeypatch.setattr(status, "stamp", lambda *a, **k: order.append("stamp") or real_stamp(*a, **k))
    monkeypatch.setattr(status, "anki_miner_update", lambda: order.append("notice") or real_update())
    status.read(["ja"])
    assert order == ["stamp", "notice"]
