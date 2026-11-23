"""The headless Edge harness's start (tests/journey_page_edge.py), with a stand-in Edge: no browser is needed.

Why: test_journey_page went red on GitHub three times on 2026-11-22 (PermissionError on the profile's
DevToolsActivePort, at the harness's read of it) and each red left Edge running to the end of the shard. The harness
read the file as soon as it existed with a size, while Edge still held it; and a start that failed never stopped Edge.
The stand-in writes the file the way that red met it (held with no sharing for a moment, as Windows refuses a reader
then) and answers the DevTools calls on 127.0.0.1, so the harness's own start and clean-up run as with Edge.
"""
import json
import os
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journey_page_edge as jpe  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the refused read is Windows' sharing rule")


def _hold_and_write(path, text, hold_s):
    """Writes `text` to `path` through a handle that shares nothing, kept open `hold_s` seconds after the write."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    h = k32.CreateFileW(path, 0x40000000, 0, None, 2, 0x80, None)    # GENERIC_WRITE, no sharing, CREATE_ALWAYS
    assert h not in (None, wintypes.HANDLE(-1).value), ctypes.get_last_error()
    data = text.encode("ascii")
    written = wintypes.DWORD()
    k32.WriteFile(h, data, len(data), ctypes.byref(written), None)
    time.sleep(hold_s)
    k32.CloseHandle(h)


class _FakeDevTools:
    """127.0.0.1: GET /json lists one page; its WebSocket answers every call with an empty result."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.calls = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn):
        with conn:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            if b"Upgrade: websocket" not in head:
                body = json.dumps([{"type": "page", "webSocketDebuggerUrl":
                                    f"ws://127.0.0.1:{self.port}/devtools/page/stand-in"}]).encode()
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
                return
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            buf = b""
            while True:
                while len(buf) < 2 or len(buf) < self._frame_len(buf):
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buf += chunk
                n, start = buf[1] & 0x7F, 2
                if n == 126:
                    n, start = int.from_bytes(buf[2:4], "big"), 4
                mask, payload = buf[start:start + 4], buf[start + 4:start + 4 + n]
                buf = buf[start + 4 + n:]
                msg = json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
                self.calls.append(msg["method"])
                out = json.dumps({"id": msg["id"], "result": {}}).encode()
                conn.sendall(bytes([0x81, len(out)]) + out)

    @staticmethod
    def _frame_len(buf):
        n = buf[1] & 0x7F
        if n == 126:
            return 4 + 4 + (int.from_bytes(buf[2:4], "big") if len(buf) >= 4 else 0)
        return 2 + 4 + n

    def close(self):
        self.srv.close()


class _StandInEdge:
    """Popen's stand-in: writes the profile's DevToolsActivePort as `write` says, in a thread; records kill()."""

    def __init__(self, write):
        self.killed = False
        self.ended = False
        self.write = write

    def poll(self):
        return 0 if self.ended else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def stand_in(monkeypatch, tmp_path):
    """Edge() runs the stand-in: the profile under tmp_path, the found Edge any path, Popen the stand-in."""
    made = {}

    def popen(args, **kw):
        profile = [a for a in args if a.startswith("--user-data-dir=")][0].split("=", 1)[1]
        made["proc"] = proc = _StandInEdge(made["write"])
        made["profile"] = profile
        threading.Thread(target=proc.write, args=(proc, profile), daemon=True).start()
        return proc

    monkeypatch.setattr(jpe, "find_edge", lambda: sys.executable)
    monkeypatch.setattr(jpe.subprocess, "Popen", popen)
    monkeypatch.setattr(jpe.tempfile, "tempdir", str(tmp_path))
    yield made


def test_a_port_file_still_held_by_edge_is_read_once_edge_lets_go(stand_in):
    # The GitHub red: the file exists with its bytes, but Edge's handle is still open; the read must wait for it.
    tools = _FakeDevTools()
    try:
        def write(proc, profile):
            time.sleep(0.05)
            _hold_and_write(os.path.join(profile, "DevToolsActivePort"),
                            f"{tools.port}\n/devtools/browser/stand-in", hold_s=0.6)
        stand_in["write"] = write
        with jpe.Edge() as e:
            assert e.evaluate("1") is None                     # the stand-in's empty result: the socket works
        assert tools.calls[:2] == ["Page.enable", "Runtime.enable"]
        assert stand_in["proc"].killed
        assert not os.path.exists(stand_in["profile"])
    finally:
        tools.close()


def test_a_half_written_port_file_is_never_taken_for_the_port(stand_in):
    # Edge writes "<port>\n<browser path>"; a read between the two must not return a port that is only partly there.
    tools = _FakeDevTools()
    try:
        def write(proc, profile):
            path = os.path.join(profile, "DevToolsActivePort")
            with open(path, "w", newline="\n") as f:
                f.write(str(tools.port)[:2])
            time.sleep(0.4)
            with open(path, "w", newline="\n") as f:
                f.write(f"{tools.port}\n/devtools/browser/stand-in")
        stand_in["write"] = write
        with jpe.Edge() as e:
            e.call("Page.enable")
        assert "Page.enable" in tools.calls
    finally:
        tools.close()


def test_an_edge_that_ends_before_its_port_is_stopped_and_its_profile_removed(stand_in):
    # A start that fails (here: Edge ends without a port file) says so at once and leaves no Edge and no profile
    # behind — the red's Edge ran on to the end of the shard, flagged there as a leaked child process.
    def write(proc, profile):
        proc.ended = True
    stand_in["write"] = write
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="ended before"):
        jpe.Edge()
    assert time.monotonic() - t0 < 5
    assert stand_in["proc"].killed
    assert not os.path.exists(stand_in["profile"])


def test_an_edge_whose_page_never_answers_is_stopped_and_its_profile_removed(stand_in, monkeypatch):
    # Any failure after the start (no page to drive): Edge is stopped and the profile goes, the error is the cause's.
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    srv.close()                                                # nothing listens there now: every connect is refused

    def write(proc, profile):
        with open(os.path.join(profile, "DevToolsActivePort"), "w", newline="\n") as f:
            f.write(f"{port}\n/devtools/browser/stand-in")
    stand_in["write"] = write
    monkeypatch.setattr(jpe, "PAGE_WAIT_S", 0.5)
    with pytest.raises(RuntimeError, match="no page"):
        jpe.Edge()
    assert stand_in["proc"].killed
    assert not os.path.exists(stand_in["profile"])

