"""The update's download survives a flaky connection (a Send report, 2026-11-18: "Couldn't download the update: <urlopen
error [WinError 10060] A connection attempt failed …>" — one dropped connection to GitHub failed the whole update).

`updater.download` tries again after a pause, asks only for the rest of a file it half has (HTTP Range) — from the
start when the server sends the whole file instead — and ends a try that receives nothing for its timeout, so it never
hangs. Every try failing is a `DownloadError` (the window says it plainly and offers *Try again*); a 4xx is the
release's answer, never tried again. The server is a local one on 127.0.0.1 (nothing leaves the machine) serving real
Japanese and Chinese files from tests/Test Resources, bigger than one read, so a cut lands mid-file."""
import hashlib
import http.server
import os
import threading
import time

import pytest

from app import updater

HERE = os.path.dirname(os.path.abspath(__file__))
FAST = (0, 0, 0)                                    # the pauses between tries: not timed here


def _payload():
    """~200 KB of real text, ja then zh, so a download takes several 64 KB reads."""
    parts = []
    for rel in (("ja", "KnownWord.json"), ("zh", "chinese_text_1.txt"), ("zh", "context_test.txt")):
        with open(os.path.join(HERE, "Test Resources", *rel), "rb") as f:
            parts.append(f.read())
    blob = b"".join(parts)
    return (blob * (200_000 // max(1, len(blob)) + 1))[:200_000]


class Flaky:
    """What each request gets, in order: "drop" (headers for the whole rest, half of it, then the connection closes),
    "stall" (half, then nothing for `stall_s`), "whole" (200 with the whole file, Range or not), "range" (a 206 of what
    Range asks for; without Range, the whole file), "503", "404". Past the list: "range". Every request is logged
    with its Range header."""

    def __init__(self, plan, stall_s=2.0):
        self.plan, self.stall_s, self.seen = list(plan), stall_s, []
        self.body = _payload()
        self.done = threading.Event()
        flaky = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                flaky.serve(self)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/surasura_part_app_v3.0.16.zip"

    def serve(self, h):
        rng = h.headers.get("Range")
        self.seen.append(rng)
        what = self.plan.pop(0) if self.plan else "range"
        if what in ("503", "404"):
            h.send_response(int(what))
            h.send_header("Content-Length", "0")
            h.end_headers()
            return
        start = int(rng.split("=")[1].rstrip("-")) if rng and what == "range" else 0
        rest = self.body[start:]
        h.send_response(206 if start else 200)
        h.send_header("Content-Length", str(len(rest)))
        if start:
            h.send_header("Content-Range", f"bytes {start}-{len(self.body) - 1}/{len(self.body)}")
        h.end_headers()
        if what in ("drop", "stall"):
            h.wfile.write(rest[:len(rest) // 2])
            h.wfile.flush()
            if what == "stall":
                self.done.wait(self.stall_s)
            h.close_connection = True
            return
        h.wfile.write(rest)

    def close(self):
        self.done.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def flaky():
    made = []

    def make(plan, stall_s=2.0):
        made.append(Flaky(plan, stall_s))
        return made[-1]
    yield make
    for f in made:
        f.close()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def test_a_connection_dropped_mid_file_resumes_from_what_arrived(tmp_path, flaky):
    server = flaky(["drop", "range"])
    dest = tmp_path / "ダウンロード" / "part-0.zip"
    seen = []
    updater.download(server.url, str(dest), progress_cb=lambda done, total: seen.append((done, total)), pauses=FAST)
    assert _sha(dest.read_bytes()) == _sha(server.body), "the whole file, its two halves joined"
    half = len(server.body) // 2
    assert server.seen == [None, f"bytes={half}-"], "the second try asks only for the rest"
    assert seen[-1] == (len(server.body), len(server.body))
    assert [d for d, _t in seen] == sorted(d for d, _t in seen), "the progress never goes back on a resume"


def test_a_stalled_connection_ends_its_try_and_never_hangs(tmp_path, flaky):
    server = flaky(["stall", "range"], stall_s=10)
    dest = tmp_path / "part-0.zip"
    began = time.monotonic()
    updater.download(server.url, str(dest), timeout=0.5, pauses=FAST)
    assert time.monotonic() - began < 8, "the stall ended its try at the read timeout, not the server's 10 s"
    assert _sha(dest.read_bytes()) == _sha(server.body)
    assert server.seen[0] is None and server.seen[1] is not None and server.seen[1].startswith("bytes=")


def test_a_server_that_ignores_range_is_read_again_from_the_start(tmp_path, flaky):
    server = flaky(["drop", "whole"])
    dest = tmp_path / "part-0.zip"
    updater.download(server.url, str(dest), pauses=FAST)
    assert dest.read_bytes() == server.body, "written over from its start, never the whole file after the half"


def test_every_try_failing_is_a_download_error_after_four_tries(tmp_path, flaky):
    server = flaky(["503"] * 9)
    with pytest.raises(updater.DownloadError) as caught:
        updater.download(server.url, str(tmp_path / "part-0.zip"), pauses=FAST)
    assert len(server.seen) == len(FAST) + 1 == 4
    assert isinstance(caught.value, updater.UpdateError), "callers catching UpdateError still catch it"
    assert "WinError" not in str(caught.value) and "503" in str(caught.value.detail)


def test_no_server_at_all_is_a_download_error(tmp_path):
    # A port nothing listens on: refused at once, as an unplugged network or a firewall answers.
    import socket
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(updater.DownloadError):
        updater.download(f"http://127.0.0.1:{port}/x.zip", str(tmp_path / "x.zip"), timeout=2, pauses=FAST)


def test_the_pauses_grow_between_tries(tmp_path, flaky, monkeypatch):
    slept = []
    monkeypatch.setattr(updater.time, "sleep", slept.append)
    server = flaky(["503", "503", "drop", "range"])
    updater.download(server.url, str(tmp_path / "part-0.zip"))
    assert slept == list(updater.DOWNLOAD_PAUSES) and slept == sorted(slept) and len(set(slept)) == len(slept)


def test_a_404_is_the_releases_answer_never_tried_again(tmp_path, flaky):
    server = flaky(["404"])
    with pytest.raises(updater.UpdateError) as caught:
        updater.download(server.url, str(tmp_path / "part-0.zip"), pauses=FAST)
    assert not isinstance(caught.value, updater.DownloadError) and "404" in str(caught.value)
    assert server.seen == [None]


def test_a_disk_error_is_never_taken_for_the_connection(tmp_path, flaky, monkeypatch):
    # Writing the file fails (the disk is full, the folder denied): that is no connection to try again.
    server = flaky(["range"])
    real_open = open

    def full(path, mode="r", *a, **k):
        if "b" in mode and ("w" in mode or "a" in mode) and str(path).endswith("part-0.zip"):
            raise OSError(28, "No space left on device")
        return real_open(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", full)
    with pytest.raises(OSError) as caught:
        updater.download(server.url, str(tmp_path / "part-0.zip"), pauses=FAST)
    assert not isinstance(caught.value, updater.UpdateError) and len(server.seen) == 1


class _Response:
    """A response `urlopen` hands back: `status`, headers, and receives (`read1`) that follow `script` — bytes, or an
    exception."""

    def __init__(self, status, body, script):
        self.status, self.headers, self.script = status, {"Content-Length": str(len(body))}, list(script)

    def getcode(self):
        return self.status

    def read1(self, _n):
        step = self.script.pop(0) if self.script else b""
        if isinstance(step, BaseException):
            raise step
        return step

    def read(self, _n):
        raise AssertionError("a plain read waits for all 64 KB: a trickle inside it would never end (read1, one receive)")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_network_gone_mid_read_is_the_networks_and_tried_again(tmp_path, monkeypatch):
    # Wi-Fi dropping mid-file raises a plain OSError from the socket (WinError 10051, "unreachable network"), not a
    # ConnectionError: it is still the network's, so the download goes on from what arrived.
    body = _payload()
    half = len(body) // 2
    gone = OSError(10051, "A socket operation was attempted to an unreachable network")
    answers = [_Response(200, body, [body[:half], gone]), _Response(206, body[half:], [body[half:]])]
    asked = []

    def urlopen(request, timeout=None):
        asked.append(request.get_header("Range"))
        return answers.pop(0)
    monkeypatch.setattr(updater.urllib.request, "urlopen", urlopen)
    dest = tmp_path / "part-0.zip"
    updater.download("https://example.invalid/surasura_part_app.zip", str(dest), pauses=FAST)
    assert dest.read_bytes() == body and asked == [None, f"bytes={half}-"]


def test_a_trickle_ends_its_try_and_never_hangs(tmp_path, monkeypatch):
    # A connection that sends a few bytes just inside every read timeout never stalls a read, yet would take days:
    # under TRICKLE_BYTES in a timeout's time ends the try. The clock is the test's: each read "takes" 20 s.
    clock = [0.0]

    def tick():
        clock[0] += 20.0
        return clock[0]
    monkeypatch.setattr(updater.time, "monotonic", tick)
    body = _payload()
    trickle = _Response(200, body, [body[i:i + 100] for i in range(0, 5000, 100)])
    asked = []

    def urlopen(request, timeout=None):
        asked.append(request.get_header("Range"))
        if len(asked) == 1:
            return trickle
        start = int(asked[-1].split("=")[1].rstrip("-"))
        return _Response(206, body[start:], [body[start:]])
    monkeypatch.setattr(updater.urllib.request, "urlopen", urlopen)
    dest = tmp_path / "part-0.zip"
    updater.download("https://example.invalid/surasura_part_app.zip", str(dest), timeout=30, pauses=FAST)
    assert len(trickle.script) > 40, "the trickle ended after a few reads, not after all fifty"
    assert dest.read_bytes() == body and len(asked) == 2 and asked[1].startswith("bytes=")
