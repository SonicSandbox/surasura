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
# Alpha 4 M5: what the notice offers is always the approved release, whatever newer one a check kept
OFFER = {"version": am_release.APPROVED, "url": am_release.approved_page()}
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


def test_check_for_updates_off_asks_github_nothing_and_writes_nothing(tmp_path, ledger, monkeypatch):
    """*Check for updates* off (Settings → App, `update_check_enabled`): Surasura asks GitHub nothing — Anki Miner's
    release included, a test's own fetch too — and a Connect run starts no thread. On again, the day's check runs."""
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    off = dict(ON, update_check_enabled=False)
    fetch = Fetch(release())
    assert am_release.check(off, now=NOON, fetch=fetch) is None and fetch.calls == 0
    assert am_release.start(off) is None and am_release._thread is None
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    runner.run(off, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert am_release._thread is None and not os.path.exists(am_release.path())
    assert am_release.check(dict(ON, update_check_enabled=True), now=NOON, fetch=fetch)["latest"] == "3.8.0"
    assert fetch.calls == 1


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
    approved = {"version": am_release.APPROVED, "url": am_release.approved_page()}
    assert am_release.notice("3.7.0") == approved, "alpha 4 M5: the approved version, never the kept 3.8.0 itself"
    assert am_release.notice(am_release.APPROVED) is None, "Anki Miner updated by hand: the notice goes at once"
    assert am_release.notice("3.10.1.0") is None, "3.10.1.0 is 3.10.1"
    assert am_release.notice("3.11.0") is None
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
    monkeypatch.setattr(am_release, "running", lambda: True)
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
    assert record["anki_miner_update"] == OFFER
    assert status.language_record(record, "ja")["anki_miner_update"] == OFFER
    assert status.language_record(record, "ja")["line"] == "Up to date"
    _installed(am_release.APPROVED)
    assert status.read(["ja"])["anki_miner_update"] is None, "Anki Miner caught up (the approved version): gone, no fetch"


def test_the_stamp_moves_when_the_release_state_or_the_setup_record_changes():
    from app.connect import status
    first = status.stamp(languages=["ja"])
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    second = status.stamp(languages=["ja"])
    assert second != first, "a new release kept must reach the window (S19: it reads only on a moved stamp)"
    assert status.stamp(languages=["ja"]) == second, "nothing changed: the same stamp"
    _installed("3.8.0")
    assert status.stamp(languages=["ja"]) != second, "Anki Miner's version recorded again: the row looks again"


# --------------------------------------------------------------------------- #
# The first review's rows (reviews/P3.2-AMN-haiku.md): A1, A2–A4, A7, A8
# --------------------------------------------------------------------------- #
def test_a1_the_stamp_moves_when_anki_miner_is_updated_by_hand(monkeypatch):
    """A1: the registry's installed version (what `installed()` reads first) is in the stamp, so a hand update — no
    setup record written, no state file touched — moves it and the row reads the record again at its next look: the
    notice goes at once, as the docstring says. Nothing moved → the same stamp (S19)."""
    from app.connect import anki_miner, status
    _installed("3.7.0")
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.7.0")
    before = status.stamp(languages=["ja"])
    assert status.read(["ja"])["anki_miner_update"] == OFFER
    assert status.stamp(languages=["ja"]) == before, "nothing changed: the same stamp"
    monkeypatch.setattr(anki_miner, "installed_version", lambda: am_release.APPROVED)
    assert status.stamp(languages=["ja"]) != before, "updated by hand: the stamp moves, the row reads again"
    assert status.read(["ja"])["anki_miner_update"] is None


def test_a4_the_attempt_is_saved_before_github_is_asked():
    """A4: a check cut off mid-fetch (the process killed, a hang left behind at exit) has already kept its attempt
    time — with the last good release — so the next run doesn't ask again that day."""
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    seen = []

    def killed():
        seen.append(state())
        raise KeyboardInterrupt         # stands in for the process ending mid-fetch (never caught by `check`)
    with pytest.raises(KeyboardInterrupt):
        am_release.check(ON, now=NOON + DAY, fetch=killed)
    assert seen == [{"checked_at": "2026-10-14T12:00:00Z", "latest": "3.8.0", "url": PAGE}], \
        "the attempt was on disk before GitHub was asked, the last good release kept"
    again = Fetch(release("v3.9.0"))
    am_release.check(ON, now=NOON + DAY + 60, fetch=again)
    assert again.calls == 0, "the cut-off check was the day's one try"


def test_a3_a_connect_started_while_a_check_is_out_finds_none_due(monkeypatch):
    """A3: `_kick` can start the next Connect before this one's `finish()`; its check must not ask GitHub again. The
    attempt is saved by `start` itself, before the thread asks."""
    gate = threading.Event()
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(am_release, "_fetch", lambda: gate.wait(10) and release())
    try:
        assert am_release.start(ON) is not None
        second = Fetch(release("v3.9.0"))
        am_release.check(ON, fetch=second)
        assert second.calls == 0, "GitHub asked twice in a day"
    finally:
        gate.set()
    assert am_release.finish() is True
    assert state()["latest"] == "3.8.0"


def test_a3_start_when_not_due_starts_no_thread(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    am_release.check(ON, fetch=Fetch(release()))
    monkeypatch.setattr(am_release, "_fetch", lambda: pytest.fail("asked twice in a day"))
    assert am_release.start(ON) is None
    assert not [t for t in threading.enumerate() if t.name == "anki-miner-release"]


def test_a4_an_attempt_that_cant_be_saved_asks_github_nothing(monkeypatch):
    """A state that can't be written can't keep the day's attempt: asking anyway would ask every run. Silent; no temp
    file left."""
    def refused(src, dst):
        raise PermissionError(13, "Access is denied", dst)
    monkeypatch.setattr(am_release.os, "replace", refused)
    fetch = Fetch(release())
    assert am_release.check(ON, now=NOON, fetch=fetch) == {}
    assert fetch.calls == 0
    folder = os.path.dirname(am_release.path())
    assert not os.path.exists(am_release.path())
    assert not [n for n in os.listdir(folder) if n.endswith(".tmp")], "no temp file left behind"
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(am_release, "_fetch", lambda: pytest.fail("asked with no attempt saved"))
    assert am_release.start(ON) is None


@pytest.mark.parametrize("raised", ["too-new", "other"])
@pytest.mark.parametrize("staged", [False, True])
def test_a2_connects_exit_waits_for_the_check_when_the_run_raises(monkeypatch, raised, staged):
    """A2: a raise from `runner.run` (TooNew, anything) still gives a check in flight the rest of its wait, outside
    the lock — unless an update is staged (the updater waits on this exit)."""
    from app import library_store
    from app.cli import connect_verbs
    from app.cli.contract import CliError
    from app.connect.ledger import TooNew
    finished = []

    def run(loaded, languages, looks=None):
        raise TooNew("made by a newer Surasura") if raised == "too-new" else RuntimeError("torn")
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(library_store, "update_staged", lambda *a, **k: staged)
    monkeypatch.setattr(am_release, "running", lambda: True)
    monkeypatch.setattr(am_release, "finish", lambda: finished.append(1) or True)
    with pytest.raises(CliError if raised == "too-new" else RuntimeError):
        connect_verbs._loop(ON, ["ja"])
    assert bool(finished) is (not staged)


def test_a7_an_installed_version_with_no_digits_is_unknown(monkeypatch):
    """A7: only a version with digits counts as known; neither known → no notice (never "3.8 is out" over an
    Anki Miner whose version is unknown)."""
    from app.connect import anki_miner
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    _installed("unknown")
    assert am_release.installed() is None
    assert am_release.notice(am_release.installed()) is None
    assert am_release.notice("unknown") is None and am_release.notice("  ") is None
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.7.0")
    assert am_release.installed() == "3.7.0", "the one known version counts"
    assert am_release.notice("3.7.0") == OFFER


@pytest.mark.parametrize("failure", [OSError(5, "no local data folder"), RuntimeError("ledger folder")])
def test_a8_write_never_raises_even_when_its_path_cant_be_named(monkeypatch, failure):
    def no_path():
        raise failure
    monkeypatch.setattr(am_release, "path", no_path)
    assert am_release._write({"checked_at": "2026-10-13T12:00:00Z", "latest": None, "url": None}) is False


@pytest.mark.parametrize("ended", ["done", "raised"])
def test_final_review_an_update_staged_after_the_runs_last_look_skips_the_exit_wait(monkeypatch, ended):
    """The final review (the exit wait): whether the run returned or raised, an update staged by the time Connect exits means no
    wait (the updater waits on this exit), and the staged check looks PROBE_LOOKS times, as the command line should."""
    from app import library_store
    from app.cli import connect_verbs
    finished, looks = [], []

    def run(loaded, languages, looks=None):
        if ended == "raised":
            raise RuntimeError("torn")
        return {"stopped": None}
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(library_store, "update_staged", lambda *a, **k: looks.append(k.get("looks")) or True)
    monkeypatch.setattr(am_release, "running", lambda: True)
    monkeypatch.setattr(am_release, "finish", lambda: finished.append(1) or True)
    try:
        connect_verbs._loop(ON, ["ja"])
    except RuntimeError:
        assert ended == "raised"
    assert not finished and looks == [library_store.PROBE_LOOKS]


def test_final_review_a_state_file_there_but_held_open_is_not_due(monkeypatch):
    """The final review (a held file): a state file that is there but can't be opened just now (a scanner holding it) is not "never
    checked": GitHub isn't asked a second time that day and the kept release stays; a torn file is rewritten."""
    am_release.check(ON, now=NOON, fetch=Fetch(release("v3.8.0")))
    kept = open(am_release.path(), encoding="utf-8").read()
    real_open = open

    def held(file, *a, **k):
        if os.path.abspath(str(file)) == os.path.abspath(am_release.path()):
            raise PermissionError(13, "held by another process")
        return real_open(file, *a, **k)
    fetch = Fetch(release("v3.9.0"))
    with monkeypatch.context() as m:
        m.setattr("builtins.open", held)
        assert am_release._claim(NOON + 2 * am_release.EVERY_S)[1] is None
        am_release.check(ON, now=NOON + 2 * am_release.EVERY_S, fetch=fetch)
    assert fetch.calls == 0
    assert open(am_release.path(), encoding="utf-8").read() == kept
    with open(am_release.path(), "w", encoding="utf-8") as f:
        f.write('{"checked_at": "2026-10')
    assert am_release._claim(NOON + 2 * am_release.EVERY_S)[1] is not None, "a torn file is due and rewritten"


def test_a_release_newer_than_the_approved_one_is_never_offered_the_approved_one_is():
    """Alpha 4 M5 (Sonic 2026-10-27: "approved versions that go out for each time"): GitHub's latest past
    `am_release.APPROVED` is no notice of its own — the notice offers the approved version, its own page, and only
    while the installed one is older; a newer one installed by hand is left alone."""
    fetch = Fetch(release("v99.0.0"))
    am_release.check(ON, now=NOON, fetch=fetch)
    approved = am_release.APPROVED
    assert am_release.notice("3.7.0") == {"version": approved, "url": f"{am_release.RELEASES}/tag/v{approved}"}
    assert am_release.notice(approved) is None, "up to the approved version: nothing to offer"
    assert am_release.notice("99.0.0") is None, "a newer one you installed yourself: no notice, never a downgrade"
