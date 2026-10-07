"""The Anki sync rule (app/anki_sync_rule.py; E1.1-fast-replan/04-preview.md §3, 05 §5; ✅ Q4-4, G1.5-7).

With the fast re-plan's preview on, Surasura asks Anki to sync with AnkiWeb at a session's first write (S1) and about
a minute after the last write that changed tomorrow's cards (S3); Anki's own sync on close is S2; S4 is the minute.
Proven against a fake AnkiConnect (in this process, and over HTTP for a second process):

  - S1 once per session — across two programs too (the state file beside the Anki-write lock, decided holding it);
    a new session after another profile, Anki seen closed, or an hour without a write;
  - never during a review (and the session waits for the next write); a profile not signed in is skipped quietly
    and said ("AnkiWeb: not signed in"); a full-sync demand is never waited on;
  - S3: one sync after a burst (each write restarts the wait), none after a write lower down, none when "off";
    Anki closed by then: nothing sent (S2 carried it); a window closing runs it at once;
  - `sync` stays refused everywhere but `anki_connect.sync()`, which needs the lock.
"""
import json
import os
import subprocess
import sys
import threading
import time
import types
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest

from app import anki_connect, anki_sync_rule, locks

URL = "http://127.0.0.1:8765"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeAnki:
    """Just what the rule asks: the profile, a review, a sync (counted; refused as AnkiConnect refuses them)."""

    def __init__(self, profile="DevTest", reviewing=False, signed_in=True, full_sync=False):
        self.profile, self.reviewing, self.signed_in, self.full_sync = profile, reviewing, signed_in, full_sync
        self.offline = False
        self.syncs = 0
        self.actions = []

    def answer(self, action):
        self.actions.append(action)
        if action == "getActiveProfile":
            return self.profile, None
        if action == "guiReviewActive":
            return self.reviewing, None
        if action == "version":
            return 6, None
        if action == "requestPermission":
            return {"permission": "granted", "version": 6}, None
        if action == "sync":
            if not self.signed_in:
                return None, "sync: auth not configured"
            if getattr(self, "fail", False):
                return None, "network error: AnkiWeb could not be reached"
            if self.full_sync:
                return None, "Sync status 2 not one of [0, 1] - see SyncCollectionResponse.ChangesRequired"
            self.syncs += 1
            return None, None
        return None, f"unsupported action {action}"

    def __call__(self, request, timeout=None):
        if self.offline:
            raise urllib.error.URLError("[WinError 10061] No connection could be made")
        payload = json.loads(request.data.decode("utf-8"))
        result, error = self.answer(payload["action"])
        body = json.dumps({"result": result, "error": error}).encode("utf-8")
        response = mock.MagicMock()
        response.read.return_value = body
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response


@pytest.fixture
def anki():
    fake = FakeAnki()
    with mock.patch("urllib.request.urlopen", fake):
        yield fake


class Clock:
    def __init__(self, at=1_800_000_000.0):
        self.at = at

    def time(self):
        return self.at


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(anki_sync_rule, "time", types.SimpleNamespace(time=c.time, strftime=time.strftime,
                                                                      localtime=time.localtime))
    return c


SETTINGS = {"anki_sync_delay_min": 1}


# --------------------------------------------------------------------------------------------------------------- #
# S4: the minute
# --------------------------------------------------------------------------------------------------------------- #

def test_the_minute_reads_as_the_user_left_it():
    assert anki_sync_rule.delay_s({}) == 60.0                       # the default: about a minute
    assert anki_sync_rule.delay_s({"anki_sync_delay_min": 0}) == 0.0     # right away
    assert anki_sync_rule.delay_s({"anki_sync_delay_min": 5}) == 300.0
    assert anki_sync_rule.delay_s({"anki_sync_delay_min": "off"}) is None
    assert anki_sync_rule.delay_s({"anki_sync_delay_min": "OFF "}) is None
    for garbage in (-3, "soon", None, True, float("nan")):           # a hand edit gone wrong: the default
        assert anki_sync_rule.delay_s({"anki_sync_delay_min": garbage}) == 60.0, garbage


# --------------------------------------------------------------------------------------------------------------- #
# S1: a session's first write
# --------------------------------------------------------------------------------------------------------------- #

def test_a_sessions_first_write_syncs_once(anki, clock):
    assert anki_sync_rule.before_write(URL) == "synced"
    assert anki.syncs == 1
    clock.at += 60
    anki_sync_rule.wrote(False, SETTINGS)
    assert anki_sync_rule.before_write(URL) is None
    assert anki.syncs == 1
    assert anki_sync_rule.status(SETTINGS).startswith("AnkiWeb: synced ")


def test_a_new_session_after_another_profile_anki_closed_or_an_hour_without_a_write(anki, clock):
    anki_sync_rule.before_write(URL)
    anki.profile = "Other"
    assert anki_sync_rule.before_write(URL) == "synced"              # another profile: a session of its own
    clock.at += 10
    anki_sync_rule.closed_seen()
    clock.at += 10
    assert anki_sync_rule.before_write(URL) == "synced"              # Anki was closed since
    clock.at += anki_sync_rule.SESSION_GAP_S + 1
    assert anki_sync_rule.before_write(URL) == "synced"              # an hour without a write
    assert anki.syncs == 4


def test_never_during_a_review_and_the_session_waits_for_the_next_write(anki, clock):
    anki.reviewing = True
    assert anki_sync_rule.before_write(URL) is None
    assert anki.syncs == 0 and not anki_sync_rule.read_state().get("session_at")
    anki.reviewing = False
    assert anki_sync_rule.before_write(URL) == "synced"


def test_not_signed_in_is_skipped_quietly_and_said(anki, clock):
    anki.signed_in = False
    assert anki_sync_rule.before_write(URL) == "not-signed-in"
    assert anki_sync_rule.before_write(URL) is None                  # the session started: not asked again
    assert anki_sync_rule.status(SETTINGS) == "AnkiWeb: not signed in"


def test_a_full_sync_demand_is_never_waited_on(anki, clock):
    anki.full_sync = True
    assert anki_sync_rule.before_write(URL) == "full-sync"
    assert "full sync" in anki_sync_rule.status(SETTINGS)


def test_anki_closed_asks_nothing(anki, clock):
    anki.offline = True
    assert anki_sync_rule.before_write(URL) is None
    assert anki.syncs == 0


def test_the_lock_held_elsewhere_skips_the_sync_for_now(anki, clock):
    """Another writer holds Anki: the write that follows waits for it anyway; the sync is asked by a later write."""
    seen = threading.Event()
    done = threading.Event()

    def hold():
        with locks.take(anki_connect.WRITER_LOCK, "another writer"):
            seen.set()
            done.wait(5)
    worker = threading.Thread(target=hold)
    worker.start()
    seen.wait(5)
    try:
        assert anki_sync_rule.before_write(URL, wait=0.0) is None
    finally:
        done.set()
        worker.join()
    assert anki.syncs == 0
    assert anki_sync_rule.before_write(URL) == "synced"


# --------------------------------------------------------------------------------------------------------------- #
# S1 across two programs
# --------------------------------------------------------------------------------------------------------------- #

class _Handler(BaseHTTPRequestHandler):
    fake = None

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        result, error = self.fake.answer(payload["action"])
        body = json.dumps({"result": result, "error": error}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_two_programs_never_each_sync_a_session(tmp_path):
    """The second program finds the session the first one started (the state file beside the Anki-write lock)."""
    fake = FakeAnki()
    handler = type("Handler", (_Handler,), {"fake": fake})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    code = ("import sys; from app import anki_sync_rule; "
            "print('answer', anki_sync_rule.before_write(sys.argv[1]))")
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        first = subprocess.run([sys.executable, "-c", code, url], cwd=REPO, env=env, capture_output=True,
                               text=True, encoding="utf-8", timeout=60)
        assert "answer synced" in first.stdout, first.stdout + first.stderr
        assert anki_sync_rule.before_write(url) is None           # this program: the same session
    finally:
        server.shutdown()
    assert fake.syncs == 1


# --------------------------------------------------------------------------------------------------------------- #
# S3: about a minute after tomorrow's cards change
# --------------------------------------------------------------------------------------------------------------- #

def test_one_sync_a_minute_after_a_burst_of_moves(anki, clock):
    anki_sync_rule.before_write(URL)
    start = clock.at
    assert anki_sync_rule.wrote(True, SETTINGS) == start + 60
    clock.at += 30
    assert anki_sync_rule.wrote(True, SETTINGS) == start + 90        # each write restarts the wait
    assert anki_sync_rule.status(SETTINGS) == "AnkiWeb: syncing in 60 s"
    clock.at = start + 89
    assert anki_sync_rule.sync_if_due(URL, SETTINGS) == (None, start + 90)
    assert anki.syncs == 1
    clock.at = start + 90
    assert anki_sync_rule.sync_if_due(URL, SETTINGS) == ("synced", None)
    assert anki.syncs == 2
    assert anki_sync_rule.sync_if_due(URL, SETTINGS) == (None, None)       # one, not one per move


def test_writes_lower_down_never_sync(anki, clock):
    anki_sync_rule.before_write(URL)
    assert anki_sync_rule.wrote(False, SETTINGS) is None
    clock.at += 3600
    assert anki_sync_rule.sync_if_due(URL, SETTINGS) == (None, None)
    assert anki.syncs == 1


def test_off_syncs_only_at_a_sessions_start_and_zero_right_away(anki, clock):
    anki_sync_rule.before_write(URL)
    assert anki_sync_rule.wrote(True, {"anki_sync_delay_min": "off"}) is None
    assert anki_sync_rule.sync_if_due(URL, {"anki_sync_delay_min": "off"}) == (None, None)
    assert anki_sync_rule.wrote(True, {"anki_sync_delay_min": 0}) == clock.at
    assert anki_sync_rule.sync_if_due(URL, {"anki_sync_delay_min": 0})[0] == "synced"


def test_a_review_at_the_due_time_looks_again_later(anki, clock):
    anki_sync_rule.before_write(URL)
    anki_sync_rule.wrote(True, SETTINGS)
    clock.at += 61
    anki.reviewing = True
    answer, again = anki_sync_rule.sync_if_due(URL, SETTINGS)
    assert answer is None and again == clock.at + anki_sync_rule.REVIEW_RETRY_S
    anki.reviewing = False
    clock.at = again
    assert anki_sync_rule.sync_if_due(URL, SETTINGS)[0] == "synced"


def test_anki_closed_by_then_sends_nothing_s2_carried_it(anki, clock):
    anki_sync_rule.before_write(URL)
    anki_sync_rule.wrote(True, SETTINGS)
    clock.at += 61
    anki.offline = True
    assert anki_sync_rule.sync_if_due(URL, SETTINGS) == ("anki-closed", None)
    anki.offline = False
    assert anki_sync_rule.sync_if_due(URL, SETTINGS) == (None, None)       # settled: never sent later
    assert anki.syncs == 1


def test_a_window_closing_runs_the_pending_sync_at_once(anki, clock):
    anki_sync_rule.before_write(URL)
    anki_sync_rule.wrote(True, SETTINGS)
    assert anki_sync_rule.sync_if_due(URL, SETTINGS, force=True) == ("synced", None)
    assert anki.syncs == 2


# --------------------------------------------------------------------------------------------------------------- #
# `sync`: one named exception
# --------------------------------------------------------------------------------------------------------------- #

def test_sync_stays_refused_everywhere_but_the_rules_call(anki):
    with pytest.raises(anki_connect.AnkiError):
        anki_connect.invoke("sync", URL)
    with pytest.raises(anki_connect.AnkiError):
        anki_connect.multi([{"action": "sync"}], URL)
    with pytest.raises(anki_connect.AnkiError) as refused:
        anki_connect.sync(URL)                                    # without the Anki-write lock
    assert refused.value.kind == "refused"
    with anki_connect.writer("a test"):
        assert anki_connect.sync(URL) == "synced"
        with pytest.raises(anki_connect.AnkiError):
            anki_connect.sync("http://example.com:8765")          # loopback only
    assert anki.syncs == 1


def test_a_failed_session_sync_is_tried_again_but_never_holds_every_write_up(anki, clock):
    """Review #15: a sync that failed (AnkiWeb unreachable) starts no session — the next write tries again — but at
    most every S1_RETRY_S, so a write is never held up by a sync that keeps failing."""
    anki.fail = True
    assert anki_sync_rule.before_write(URL).startswith("failed")
    tries = anki.actions.count("sync")
    clock.at += 60
    assert anki_sync_rule.before_write(URL) is None                    # not again so soon
    assert anki.actions.count("sync") == tries
    anki.fail = False
    clock.at += anki_sync_rule.S1_RETRY_S
    assert anki_sync_rule.before_write(URL) == "synced"
    assert anki.syncs == 1


def test_inside_the_lock_the_session_sync_takes_no_lock_of_its_own(anki, clock):
    """Junban's run calls S1 holding the Anki-write lock, just before its first request (review #5)."""
    with anki_connect.writer("a run"):
        assert anki_sync_rule.before_write(URL, locked=True) == "synced"
    assert anki.syncs == 1


def test_switching_off_lets_a_pending_sync_go(anki, clock):
    anki_sync_rule.before_write(URL)
    anki_sync_rule.wrote(True, SETTINGS)
    assert anki_sync_rule.due_at(SETTINGS) is not None
    anki_sync_rule.drop_pending()
    assert anki_sync_rule.due_at(SETTINGS) is None
    assert not anki_sync_rule.status(SETTINGS).startswith("AnkiWeb: syncing in")


def test_a_new_days_session_sync_that_failed_is_tried_again_after_a_write(anki, clock):
    """Pass 2 S1: the usual new session is the hour gap; a failed sync keeps it due though the write's `wrote()`
    resets the gap — until a sync runs (at most every S1_RETRY_S)."""
    anki_sync_rule.before_write(URL)
    clock.at += anki_sync_rule.SESSION_GAP_S + 60                       # a new day
    anki.fail = True
    assert anki_sync_rule.before_write(URL).startswith("failed")
    anki_sync_rule.wrote(False, SETTINGS)                               # the write went on
    anki.fail = False
    clock.at += anki_sync_rule.S1_RETRY_S + 1
    assert anki_sync_rule.before_write(URL) == "synced"


def test_a_pending_sync_older_than_its_session_is_not_sent(anki, clock):
    """Pass 2 N8: Anki closed after the write (its own sync carried it), or long ago: not ours to send."""
    anki_sync_rule.before_write(URL)
    anki_sync_rule.wrote(True, SETTINGS)
    clock.at += 30
    anki_sync_rule.closed_seen()
    assert anki_sync_rule.due_at(SETTINGS) is None
