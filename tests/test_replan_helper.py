"""The fast re-plan preview's helper process (app/replan_preview.py: `open_host`, `Remote`, `helper_main`; E3.1-B1).

The window's side (`Remote`) starts a real helper process (`python app/replan_preview.py`) that runs the `Host`, on
test_replan_preview.py's generated library (real Japanese text, the preview on), against a fake AnkiConnect this
process serves on a loopback port (the Junban suite's `ModCollection` behind a small HTTP server: real state, every
write checked under the ceiling). What these prove:

  - a move in the store → the helper's job → Anki re-ordered; the window's side hears the lines, and is busy from the
    moment it asks (before the helper has even answered) until the job is done;
  - stop ends the helper; the window's process gone (its end of the pipe broken, nothing said) ends it too;
  - a helper that can't start, or ends on its own, leaves the jobs to the window's own process, which catches up;
  - the suites' own switch keeps every other window test's host in-process (`open_host` with IN_PROCESS_ENV).
"""
import http.server
import sys
import threading
import time
import types

import pytest

pytest.importorskip("modules.junban")

from app import replan_preview  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402
from tests.test_replan_preview import _deck, _move_later_to_top, _settings_file, lib  # noqa: E402,F401


class _Served:
    """A fake collection on 127.0.0.1 (a free port): AnkiConnect's one POST, answered by the fake itself."""

    def __init__(self, fake):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                reply = fake(types.SimpleNamespace(data=body)).read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, name="fake-anki", daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def served(lib, monkeypatch):
    """The library, its deck served on a loopback port, settings.json pointing there; helpers allowed."""
    root, store = lib
    fake = _deck(root)
    anki = _Served(fake)
    _settings_file(root, anki_connect_url=anki.url)
    monkeypatch.delenv(replan_preview.IN_PROCESS_ENV, raising=False)
    hosts = []
    yield root, store, fake, hosts
    for host in hosts:
        host.stop()
        if host._proc is not None:
            try:
                host._proc.wait(30)
            except Exception:
                host._proc.kill()
    anki.close()


def _wait(condition, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def _open(hosts, **kwargs):
    host = replan_preview.open_host("ja", **kwargs)
    hosts.append(host)
    return host


def test_the_suites_switch_keeps_the_host_in_process(monkeypatch):
    monkeypatch.setenv(replan_preview.IN_PROCESS_ENV, "1")
    host = replan_preview.open_host("ja")
    assert isinstance(host, replan_preview.Host)


def test_a_move_reorders_anki_through_the_helper_process(served):
    root, store, fake, hosts = served
    lines = []
    host = _open(hosts, say=lines.append)
    assert isinstance(host, replan_preview.Remote)
    host.warm()
    host.catch_up()
    assert host.busy(), "busy from the moment it asks, before the helper answered"
    assert _wait(lambda: not host.busy(), 180), "the first job never finished"
    assert host._proc.poll() is None and fake.write_requests, "the switch-on catch-up laid nothing"
    fake.write_requests.clear()
    _move_later_to_top(store)
    host.poke()
    assert host.busy()
    assert _wait(lambda: not host.busy(), 60) and fake.write_requests, "the move re-ordered nothing"
    assert lines and lines[-1].startswith("Anki: ") and host.last == lines[-1]
    versions = store.versions()
    assert versions["planned_order_version"] == versions["order_version"]
    assert host.web.startswith("AnkiWeb") or host.web == ""


def test_the_helper_ends_with_its_window(served):
    _root, _store, _fake, hosts = served
    host = _open(hosts)
    assert _wait(lambda: host._conn is not None, 60), "the helper never answered"
    host.stop()
    assert host._proc.wait(30) == 0
    # The window's process gone: nothing said, its end of the pipe just breaks.
    host = _open(hosts)
    assert _wait(lambda: host._conn is not None, 60)
    with host._lock:
        host._stopped = True                     # (this side gone: nothing takes the jobs over here)
    host._conn.close()
    assert host._proc.wait(30) == 0


def test_a_helper_that_cant_start_leaves_the_jobs_to_the_windows_process(served, monkeypatch):
    root, store, fake, hosts = served
    monkeypatch.setattr(replan_preview, "_helper_args", lambda language, generate: [sys.executable, "-c", "pass"])
    host = _open(hosts)
    host.warm()
    host.catch_up()
    assert _wait(lambda: host._local is not None, 60), "no fallback"
    assert _wait(lambda: not host.busy(), 180) and fake.write_requests, "the window's own host laid nothing"
    fake.write_requests.clear()
    _move_later_to_top(store)
    host.poke()
    assert _wait(lambda: not host.busy(), 60) and fake.write_requests


def test_a_helper_that_ends_on_its_own_hands_the_jobs_back_and_they_catch_up(served):
    root, store, fake, hosts = served
    host = _open(hosts)
    host.warm()
    host.catch_up()
    assert _wait(lambda: not host.busy(), 180)
    host._proc.kill()
    assert _wait(lambda: host._local is not None, 30), "no fallback after the helper ended"
    fake.write_requests.clear()
    _move_later_to_top(store)
    host.poke()
    assert _wait(lambda: not host.busy(), 60) and fake.write_requests, "the move wasn't re-ordered"


def test_calls_after_stop_send_nothing_and_a_stopped_side_never_takes_jobs_over(served):
    _root, _store, _fake, hosts = served
    host = _open(hosts)
    host.stop()                                  # before the helper has even answered
    host.poke()
    assert not host.busy()
    time.sleep(1.0)
    assert host._local is None
    if host._proc is not None:
        assert host._proc.wait(30) in (0, 2)     # it ended: told to, or nobody left to answer


def test_the_in_process_fake_still_serves_a_local_host(lib, monkeypatch):
    # The fallback's own path, without a helper at all: `_go_local` replays what waited, once each.
    root, store = lib
    fake = _deck(root)
    monkeypatch.delenv(replan_preview.IN_PROCESS_ENV, raising=False)
    monkeypatch.setattr(replan_preview.Remote, "_connect", lambda self: (_ for _ in ()).throw(RuntimeError("no")))
    with _patched(fake):
        host = replan_preview.open_host("ja")
        assert _wait(lambda: host._local is not None, 30)
        host.warm()
        host.catch_up()
        assert _wait(lambda: not host.busy(), 180) and fake.write_requests
        host.stop()
