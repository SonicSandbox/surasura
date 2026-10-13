"""Anki Miner's update notice (P3.2-AMN rows AMN.1–AMN.2; `app/connect/am_release.py`, `runner.run`'s start).

What a wrong answer would cost: a check every run spends the user's anonymous GitHub quota (60 an hour, shared with
Surasura's own update check) and wakes the network on a laptop for nothing; a check with Connect off is a network
call the user never switched on (CLAUDE.md §1); a failure that raises or lands in *Needs you* turns a courtesy into
a nag; a lost `latest` after one failed try hides a real update for a day; a notice kept after Anki Miner was
updated by hand nags about an update already done; mining that waits on GitHub delays the user's cards. The fetch
is always stood in for: no test here touches the network.
"""
import datetime
import json
import os
import socket
import threading
import time
import urllib.error

import pytest

from app.connect import am_release, runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

ON = {"connect_enabled": True}
DAY = 24 * 3600
NOON = datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
PAGE = "https://github.com/0xzerolight/anki_miner/releases/tag/v3.8.0"
REAL_FETCH = am_release._fetch


class Fetch:
    """GitHub's answer stood in for: each call counted; `answers` in order (an exception is raised)."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self):
        self.calls += 1
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def release(tag="v3.8.0", url=PAGE):
    return {"tag_name": tag, "html_url": url, "assets": []}


def state():
    with open(am_release.path(), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def never_the_real_fetch(monkeypatch):
    """The real `_fetch` (urllib to api.github.com) fails the test if anything reaches it; the module's thread slot
    starts empty."""
    def real(*_a, **_k):
        raise AssertionError("the real GitHub fetch was called")
    monkeypatch.setattr(am_release, "_fetch", real)
    monkeypatch.setattr(am_release, "_thread", None)


# --------------------------------------------------------------------------- #
# AMN.1: once a day, kept, fail-silent
# --------------------------------------------------------------------------- #
def test_two_checks_in_a_day_fetch_once_and_the_next_day_fetches_again():
    fetch = Fetch(release())
    first = am_release.check(ON, now=NOON, fetch=fetch)
    assert first == {"checked_at": "2026-10-13T12:00:00Z", "latest": "3.8.0", "url": PAGE}
    assert am_release.check(ON, now=NOON + DAY - 60, fetch=fetch) == first
    assert fetch.calls == 1, "a second check inside 24 h must not ask GitHub"
    am_release.check(ON, now=NOON + DAY, fetch=fetch)
    assert fetch.calls == 2, "24 h later the check is due again"
    assert state()["checked_at"] == "2026-10-14T12:00:00Z"


def test_a_clock_gone_back_makes_the_check_due():
    fetch = Fetch(release())
    am_release.check(ON, now=NOON, fetch=fetch)
    am_release.check(ON, now=NOON - 3600, fetch=fetch)
    assert fetch.calls == 2, "a last check in the future (the clock went back) must not block checks for days"
    assert am_release.due({"checked_at": "not a time"}, NOON) and am_release.due({}, NOON)


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("offline"),
    socket.timeout("timed out"),
    urllib.error.HTTPError("https://api.github.com/", 404, "Not Found", {}, None),
    ValueError("Expecting value: line 1 column 1 (char 0)"),        # a torn answer: json.loads fails
    None,                                                            # _http_json's non-200: no answer
    {"message": "API rate limit exceeded"},                          # an answer with no release in it
    ["not", "an", "object"],
], ids=["offline", "timeout", "404", "torn", "none", "rate-limited", "not-an-object"])
def test_a_failed_check_raises_nothing_keeps_the_attempt_and_the_last_good_latest(failure):
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    failed = Fetch(failure)
    out = am_release.check(ON, now=NOON + DAY, fetch=failed)
    assert failed.calls == 1
    assert out == state() == {"checked_at": "2026-10-14T12:00:00Z", "latest": "3.8.0", "url": PAGE}, \
        "the attempt time is kept (one try a day) and the last good release stays"
    assert am_release.check(ON, now=NOON + DAY + 60, fetch=failed) == out and failed.calls == 1, \
        "a failure is not retried every run"


def test_a_failed_first_check_keeps_the_attempt_with_no_latest():
    out = am_release.check(ON, now=NOON, fetch=Fetch(urllib.error.URLError("offline")))
    assert out == state() == {"checked_at": "2026-10-13T12:00:00Z", "latest": None, "url": None}
    assert am_release.notice("3.7.0") is None


@pytest.mark.parametrize("tag, kept", [
    ("v3.8.0", "3.8.0"), ("3.8.0", "3.8.0"), ("V3.9", "3.9"), ("anki_miner-v4.0.1", "4.0.1"), ("release 3.10", "3.10"),
])
def test_v_prefixed_and_odd_tags_keep_their_version(tag, kept):
    assert am_release.check(ON, now=NOON, fetch=Fetch(release(tag)))["latest"] == kept


def test_a_tag_with_no_version_keeps_the_last_good_one():
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    am_release.check(ON, now=NOON + DAY, fetch=Fetch(release("nightly")))
    assert state()["latest"] == "3.8.0"


def test_the_link_is_a_releases_page_never_a_download_or_another_site():
    download = "https://github.com/0xzerolight/anki_miner/releases/download/v3.8.0/AnkiMiner-Setup.exe"
    for url, kept in ((PAGE, PAGE), (download, am_release.RELEASES), ("https://example.com/x", am_release.RELEASES),
                      (None, am_release.RELEASES)):
        if os.path.exists(am_release.path()):
            os.remove(am_release.path())
        assert am_release.check(ON, now=NOON, fetch=Fetch(release(url=url)))["url"] == kept, url


def test_preview_off_fetches_nothing_and_writes_nothing():
    fetch = Fetch(release())
    for settings in ({}, {"connect_enabled": False}, None):
        assert am_release.check(settings, now=NOON, fetch=fetch) is None
    assert fetch.calls == 0
    assert not os.path.exists(am_release.path())
    assert am_release.start({"connect_enabled": False}) is None and am_release._thread is None


def test_the_update_check_gate_keeps_the_real_fetch_off_and_writes_nothing(monkeypatch):
    """SURASURA_NO_UPDATE_CHECK (set for every test, honoured by Surasura's own check): no real fetch, no file. The
    autouse fixture's real-fetch stand-in raises if it is reached."""
    monkeypatch.setenv("SURASURA_NO_UPDATE_CHECK", "1")
    assert am_release.check(ON, now=NOON) is None
    assert not os.path.exists(am_release.path())


def test_the_real_fetch_asks_anki_miners_latest_release_with_a_five_second_bound(monkeypatch):
    """The HTTP helper is Surasura's own (`update_checker._http_json`), stood in for: the URL and the timeout."""
    from app import update_checker
    asked = []
    monkeypatch.setattr(update_checker, "_http_json", lambda url, timeout=10: asked.append((url, timeout)) or None)
    assert REAL_FETCH() is None
    assert asked == [("https://api.github.com/repos/0xzerolight/anki_miner/releases/latest", 5)]


def test_an_unchanged_state_is_never_written_again():
    fetch = Fetch(release())
    am_release.check(ON, now=NOON, fetch=fetch)
    before = os.stat(am_release.path()).st_mtime_ns
    time.sleep(0.02)
    am_release.check(ON, now=NOON + 60, fetch=fetch)
    assert os.stat(am_release.path()).st_mtime_ns == before, "not due: the file is left alone"


def test_a_state_file_that_cant_be_written_is_silent(monkeypatch):
    def refused(src, dst):
        raise PermissionError(13, "Access is denied", dst)
    monkeypatch.setattr(am_release.os, "replace", refused)
    out = am_release.check(ON, now=NOON, fetch=Fetch(release()))
    assert out["latest"] == "3.8.0", "the check itself still answers"
    folder = os.path.dirname(am_release.path())
    assert not os.path.exists(am_release.path())
    assert not [n for n in os.listdir(folder) if n.endswith(".tmp")], "no temp file left behind"


def test_an_unreadable_state_file_is_a_check_due():
    os.makedirs(os.path.dirname(am_release.path()), exist_ok=True)
    with open(am_release.path(), "w", encoding="utf-8") as f:
        f.write('{"checked_at": "2026-10-13T12:0')       # torn
    fetch = Fetch(release())
    assert am_release.check(ON, now=NOON, fetch=fetch)["latest"] == "3.8.0" and fetch.calls == 1


# --------------------------------------------------------------------------- #
# The notice: no fetch, cleared once Anki Miner catches up
# --------------------------------------------------------------------------- #
def test_a_newer_release_is_a_notice_and_catching_up_clears_it_with_no_fetch():
    fetch = Fetch(release("v3.8.0"))
    am_release.check(ON, now=NOON, fetch=fetch)
    assert am_release.notice("3.7.0") == {"version": "3.8.0", "url": PAGE}
    assert am_release.notice("3.8.0") is None, "Anki Miner updated by hand: the notice goes at once"
    assert am_release.notice("3.8") is None, "3.8 is 3.8.0"
    assert am_release.notice("3.9.1") is None
    assert am_release.notice(None) is None, "Anki Miner not known to be installed: no notice"
    assert fetch.calls == 1


def test_installed_is_what_connect_already_knows_the_newer_of_the_two(monkeypatch):
    from app.connect import anki_miner, setup
    assert am_release.installed() is None
    setup.write_record({"anki_miner": {"path": "C:/x/AnkiMiner.exe", "app": "3.7.0"}})
    assert am_release.installed() == "3.7.0"
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.8.0")
    assert am_release.installed() == "3.8.0", "the installer's version is newer: updated by hand"
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.6.2")
    assert am_release.installed() == "3.7.0"


# --------------------------------------------------------------------------- #
# AMN.2: started at the run's start on a daemon thread; mining never waits
# --------------------------------------------------------------------------- #
@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_a_run_with_the_fetch_hanging_mines_without_waiting(tmp_path, ledger, monkeypatch):
    gate, asked = threading.Event(), []

    def hanging():
        asked.append(threading.current_thread().name)
        gate.wait(10)
        return release()
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(am_release, "_fetch", hanging)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    try:
        started = time.monotonic()
        summary = runner.run(ON, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        took = time.monotonic() - started
        assert summary["languages"]["ja"]["done"] == [1], summary
        assert any(e[0] == "mine" for e in steps.log)
        assert took < 5, "the run must not wait on GitHub"
        thread = am_release._thread
        assert thread is not None and thread.daemon and thread.is_alive(), "the check is still out, on its own thread"
        assert asked == ["anki-miner-release"], "the fetch runs on the check's thread, never the run's"
    finally:
        gate.set()
    assert am_release.finish() is True
    assert state()["latest"] == "3.8.0"


def test_a_run_with_the_preview_off_starts_no_thread(tmp_path, ledger, monkeypatch):
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert am_release._thread is None
    assert not [t for t in threading.enumerate() if t.name == "anki-miner-release"]
    assert not os.path.exists(am_release.path())


def test_finish_gives_a_running_check_only_what_is_left_of_its_bound(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(am_release, "TIMEOUT_S", 0)
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(am_release, "_fetch", lambda: gate.wait(10) and release())
    try:
        am_release.start(ON)
        started = time.monotonic()
        assert am_release.finish() is False, "a check past its bound is left behind"
        assert time.monotonic() - started < 2.5
    finally:
        gate.set()
    am_release._thread.join(5)


def test_finish_waits_for_a_check_still_inside_its_bound(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(am_release, "_fetch", lambda: time.sleep(0.3) or release())
    am_release.start(ON)
    assert am_release.finish() is True
    assert state()["latest"] == "3.8.0", "a short Connect run doesn't end the check mid-fetch"


@pytest.mark.parametrize("stopped, waits", [(None, True), (runner.STOPPED_FOR_UPDATE, False)])
def test_connects_exit_waits_for_the_check_unless_an_update_is_staged(monkeypatch, stopped, waits):
    from app.cli import connect_verbs
    finished = []
    monkeypatch.setattr(runner, "run", lambda loaded, languages, looks=None: {"stopped": stopped} if stopped else {})
    monkeypatch.setattr(connect_verbs, "_pending", lambda lang: False)
    monkeypatch.setattr(am_release, "finish", lambda: finished.append(1) or True)
    connect_verbs._loop(ON, ["ja"])
    assert bool(finished) is waits


# --------------------------------------------------------------------------- #
# AMN.3: the status record carries the notice; its stamp covers the state file
# --------------------------------------------------------------------------- #
def _installed(version):
    from app.connect import setup
    setup.write_record({"anki_miner": {"path": "C:/x/AnkiMiner.exe", "app": version}})


def test_the_status_record_carries_the_notice_with_or_without_a_ledger():
    from app.connect import status
    assert status.read(["ja"])["anki_miner_update"] is None, "nothing checked yet: null"
    _installed("3.7.0")
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    record = status.read(["ja"])
    assert record["anki_miner_update"] == {"version": "3.8.0", "url": PAGE}
    assert status.language_record(record, "ja")["anki_miner_update"] == {"version": "3.8.0", "url": PAGE}
    assert status.language_record(record, "ja")["line"] == "Up to date"
    _installed("3.8.0")
    assert status.read(["ja"])["anki_miner_update"] is None, "Anki Miner caught up: gone, no fetch"


def test_the_stamp_moves_when_the_release_state_or_the_setup_record_changes():
    from app.connect import status
    first = status.stamp(languages=["ja"])
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    second = status.stamp(languages=["ja"])
    assert second != first, "a new release kept must reach the window (S19: it reads only on a moved stamp)"
    assert status.stamp(languages=["ja"]) == second, "nothing changed: the same stamp"
    _installed("3.8.0")
    assert status.stamp(languages=["ja"]) != second, "Anki Miner's version recorded again: the row looks again"
