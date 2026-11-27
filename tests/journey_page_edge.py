"""Headless Edge for the journey page's self-checks, through the DevTools protocol, with the standard library only
(a small WebSocket client: no package is added). Edge picks its own debugging port (`--remote-debugging-port=0`, read
back from `DevToolsActivePort`), so side-by-side runs never share one. Missing Edge: `find_edge()` is None and the
tests that need it skip.
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.parse

# Edge's start waits on Edge itself — alive, then its DevTools port, then a page listed — and a dead Edge fails at
# once. A warm PC starts it in ~1 s; a cold GitHub runner's first Edge took ~14 s to its port and listed no page in
# the 10 s after (2026-11-27, core 1/8 on #768: the fixed 15 s + 10 s before), and the next one's first answer took
# over 60 s, while the shard's other tests ran at their usual speed. The budgets only stop an Edge that hangs.
START_WAIT_S = 180    # the start to a page listed (its port and its page, one budget)
CALL_WAIT_S = 180     # one DevTools answer (a socket that closes — Edge gone — fails at once)

CANDIDATES = (
    os.environ.get("SURASURA_EDGE") or "",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_edge():
    for path in CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


class _Socket:
    """One WebSocket connection (client side: masked text frames out, any frames in)."""

    def __init__(self, url, timeout=CALL_WAIT_S):
        u = urllib.parse.urlsplit(url)
        self.sock = socket.create_connection(("127.0.0.1", u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("no WebSocket answer")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head[:200])
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def send(self, text):
        data = text.encode("utf-8")
        n = len(data)
        hdr = bytes([0x81])
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        parts = []
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            op = b1 & 0x0F
            if op == 9:                                  # a ping: answered, not returned
                continue
            if op == 8:
                raise ConnectionError("closed by Edge")
            parts.append(payload)
            if b1 & 0x80:
                return b"".join(parts).decode("utf-8")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Edge:
    """A headless Edge with one page, driven by `call` / `evaluate`."""

    def __init__(self, width=1280, height=800, scale=1.0):
        self.path = find_edge()
        if not self.path:
            raise RuntimeError("Edge isn't installed")
        self.profile = tempfile.mkdtemp(prefix="j-page-edge-")
        self.proc = None
        try:
            self._launch(width, height, scale)
            self._start(width, height, scale)
        except BaseException:
            self.close()                                 # a failed start leaves no Edge and no profile behind
            raise

    def _launch(self, width, height, scale):
        self.proc = subprocess.Popen(
            [self.path, "--headless=new", "--remote-debugging-port=0", "--user-data-dir=" + self.profile,
             f"--window-size={width},{height}", f"--force-device-scale-factor={scale}", "--no-first-run",
             "--disable-extensions", "--disable-background-networking", "--disable-component-update", "--disable-sync",
             "--enable-precise-memory-info", "--js-flags=--expose-gc", "--allow-file-access-from-files", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _port(self, end):
        """Edge's DevTools port, from the profile's DevToolsActivePort ("<port>\\n<browser path>") once Edge has
        written it whole. Edge still holds the file a moment after its bytes are there, and Windows refuses a reader
        then (PermissionError: GitHub, 2026-11-22, three reds); a read before its newline would take part of the port.
        So it waits for the file to open with both lines, as it waits for the file to be there."""
        port_file = os.path.join(self.profile, "DevToolsActivePort")
        while time.monotonic() < end:
            try:
                with open(port_file, encoding="ascii") as f:
                    lines = f.read().split("\n")
                if len(lines) >= 2 and lines[0].strip().isdigit() and lines[1].strip():
                    return int(lines[0])
            except (FileNotFoundError, PermissionError):
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"Edge ended before it wrote its DevTools port (exit {self.proc.poll()})")
            time.sleep(0.05)
        raise RuntimeError(f"Edge wrote no DevTools port in {START_WAIT_S} s")

    def _start(self, width, height, scale):
        end = time.monotonic() + START_WAIT_S
        port = self._port(end)
        tabs = []
        while time.monotonic() < end:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
                    s.sendall(f"GET /json HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode("ascii"))
                    raw = b""
                    while True:
                        c = s.recv(65536)
                        if not c:
                            break
                        raw += c
                        if b"\r\n\r\n" in raw:
                            head, body = raw.split(b"\r\n\r\n", 1)
                            length = [ln for ln in head.split(b"\r\n") if ln.lower().startswith(b"content-length")]
                            if length and len(body) >= int(length[0].split(b":")[1]):
                                break
                tabs = json.loads(raw.split(b"\r\n\r\n", 1)[1])
                if any(t.get("type") == "page" for t in tabs):
                    break
            except (OSError, ValueError, IndexError):       # (closed before its header: Edge still starting)
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"Edge ended before it listed a page (exit {self.proc.poll()})")
            time.sleep(0.1)
        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            raise RuntimeError(f"Edge listed no page in {START_WAIT_S} s")
        self.ws = _Socket(pages[0]["webSocketDebuggerUrl"])
        self.n = 0
        self.events = []
        self.call("Page.enable")
        self.call("Runtime.enable")
        # the page's own width, exactly (a headless window's size is its outer size, and has a floor of its own)
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale, mobile=False)

    def call(self, method, **params):
        self.n += 1
        my = self.n
        self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def evaluate(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=await_promise)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text"))
        return r.get("result", {}).get("value")

    def open(self, url, until="window.__J && window.__J.TIMES.firstWord", seconds=CALL_WAIT_S):
        """Navigates to `url` and waits for `until` (by default as long as for one answer: a cold Edge's first file
        page is slow to answer at all, then ready at once)."""
        self.events.clear()
        self.call("Page.navigate", url=url)
        end = time.time() + seconds
        while time.time() < end:
            try:
                if self.evaluate(f"!!({until})"):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.05)
        return False

    def open_wait(self, until, seconds=10):
        """Waits for `until` on the page already open (no navigation)."""
        end = time.time() + seconds
        while time.time() < end:
            try:
                if self.evaluate(f"!!({until})"):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.05)
        return False

    def errors(self):
        out = []
        for m in self.events:
            if m.get("method") == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                out.append((d.get("exception") or {}).get("description") or d.get("text"))
            elif m.get("method") == "Runtime.consoleAPICalled" and m["params"].get("type") == "error":
                out.append(" ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"]))
        return out

    def screenshot(self, path):
        data = self.call("Page.captureScreenshot", format="png")["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def close(self):
        try:
            if getattr(self, "ws", None):                # (a start that failed before its socket has none)
                self.ws.close()
        finally:
            if self.proc is not None:                    # (a launch that failed has no process)
                self.proc.kill()
                try:
                    self.proc.wait(10)
                except subprocess.TimeoutExpired:
                    pass
            shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
