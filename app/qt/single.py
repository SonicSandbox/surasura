"""One window per user session and install (W2.1; the window's spec 05 §5.11).

**Connect first, then listen.** A second start asks the first over a local named pipe (`QLocalSocket`: never a network
call) to come forward, waits for its acknowledgement, and exits. Who is first is decided by a lock file, not by
`listen()`: on Windows a second `listen()` beside the first succeeds (measured, W1.2 Phase 0), so two starts at once
would otherwise both stay. The lock is held for the first's whole life; the operating system frees it if it dies.

At close the first stops listening **before** its window hides, so a start during a close never hands over to a window
that is going away: that start can't connect and can't take the lock yet, waits for the lock, and becomes the first.

The name carries the user, the session and the install (D15: one library per install), so two people on one PC, or
two installs, never meet. Tests give each test its own name (`SURASURA_INSTANCE_NAME`) and lock (the test root).

The protocol, one line each way: the first sends `hello <pid>` as it accepts (so a Windows second start, which holds
the foreground, can let the first take it: `AllowSetForegroundWindow`); the second sends its arguments as JSON; the
first answers `ok` and comes forward.
"""
import getpass
import hashlib
import json
import os
import re
import sys
import time

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from app import path_utils
from app.qt import applog

CONNECT_MS = 300
ANSWER_MS = 2000
WAIT_FOR_FIRST_S = 10.0
MAX_LINE = 64 * 1024


def _log(msg):
    applog.log("single instance", msg)


def _session_id():
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            sid = wintypes.DWORD(0)
            if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
                return str(sid.value)
        except Exception:
            pass
        return "0"
    return os.environ.get("XDG_SESSION_ID") or str(getattr(os, "getsid", lambda _p: 0)(0))


def instance_name():
    """The pipe's name: the user, the session and the install (a test's own name when it sets one)."""
    override = os.environ.get("SURASURA_INSTANCE_NAME")
    if override:
        return override
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    install = hashlib.sha256(path_utils.get_local_data_path().encode("utf-8")).hexdigest()[:12]
    raw = f"surasura-window-{user}-{_session_id()}-{install}"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)


def lock_path():
    return os.path.join(path_utils.get_local_data_path(), "window.lock")


def _allow_foreground(pid):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(int(pid))
    except Exception:
        pass


class SingleInstance(QObject):
    """`claim(args)` → True: this start is the first (it listens); False: it handed over (or gave up), so exit 0.
    `activated(args)` fires on the GUI thread when a later start hands over. Make it after the QApplication."""

    activated = pyqtSignal(list)

    def __init__(self, name=None, lock=None, parent=None):
        super().__init__(parent)
        self.name = name or instance_name()
        self.lock_file = lock or lock_path()
        self._held = None
        self.server = None
        self.outcome = None                         # "first" · "handed-over" · "gave-up" (for the log and tests)
        self._clients = []                          # (socket, its bytes so far) for each start talking to us

    # --- a start ------------------------------------------------------------------------------------------------ #
    def claim(self, args=(), wait=WAIT_FOR_FIRST_S):
        deadline = time.monotonic() + wait
        while True:
            answer = self._hand_over(list(args))
            if answer is not None:
                self.outcome = "handed-over" if answer else "gave-up"
                _log(f"another window is open: {'handed over' if answer else 'it did not answer'}")
                return False
            self._held = path_utils.try_lock(self.lock_file)
            if self._held is not None:
                self._listen()
                self.outcome = "first"
                return True
            if time.monotonic() >= deadline:          # a holder that never listens nor quits
                self.outcome = "gave-up"
                _log("another start holds the window's lock and never answered: not opening a second window")
                return False
            time.sleep(0.1)

    def _hand_over(self, args):
        """None: nobody is listening. True: the first acknowledged. False: it accepted but never answered."""
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(CONNECT_MS):
            sock.abort()
            return None
        try:
            hello = self._read_line(sock)
            if hello and hello.startswith("hello "):
                _allow_foreground(hello.split(" ", 1)[1])
            sock.write((json.dumps(args) + "\n").encode("utf-8"))
            sock.flush()
            sock.waitForBytesWritten(ANSWER_MS)
            return self._read_line(sock) == "ok"
        finally:
            sock.disconnectFromServer()

    @staticmethod
    def _read_line(sock):
        data = b""
        deadline = time.monotonic() + ANSWER_MS / 1000
        while b"\n" not in data:
            left = int((deadline - time.monotonic()) * 1000)
            if left <= 0 or (not sock.bytesAvailable() and not sock.waitForReadyRead(left)):
                break
            data += bytes(sock.readAll())
        return data.split(b"\n", 1)[0].decode("utf-8", "replace").strip() if b"\n" in data else None

    # --- the first ---------------------------------------------------------------------------------------------- #
    def _listen(self):
        QLocalServer.removeServer(self.name)           # a dead first's socket file (not Windows: pipes go with it)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(self.name):
            _log(f"could not listen on {self.name}: {self.server.errorString()}")
            return
        self.server.newConnection.connect(self._accept)

    def _accept(self):
        while self.server is not None and self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            # Each client is kept here, its handler a method of this object: a closure held only by a Qt connection
            # can be collected by Python's GC (a cycle with the socket's wrapper), and the first then never answers
            # (W2.1: seen in the full window suite, the second start gave up).
            self._clients.append((sock, bytearray()))
            sock.readyRead.connect(self._ready)
            sock.disconnected.connect(self._gone)
            sock.write(f"hello {os.getpid()}\n".encode("ascii"))

    def _client(self, sock):
        for i, (s, buf) in enumerate(self._clients):
            if s is sock:
                return i, buf
        return None, None

    def _ready(self):
        sock = self.sender()
        i, buf = self._client(sock)
        if buf is None:
            return
        buf.extend(bytes(sock.readAll()))
        if b"\n" not in buf:
            if len(buf) > MAX_LINE:                     # a client that never ends its line gets nothing
                sock.abort()
            return
        line = bytes(buf).split(b"\n", 1)[0]
        try:
            args = json.loads(line.decode("utf-8"))
            args = [str(a) for a in args] if isinstance(args, list) else []
        except ValueError:
            args = []
        sock.write(b"ok\n")
        sock.flush()
        sock.disconnectFromServer()
        self.activated.emit(args)

    def _gone(self):
        sock = self.sender()
        i, _buf = self._client(sock)
        if i is not None:
            del self._clients[i]
        if sock is not None:
            sock.deleteLater()

    def stop_listening(self):
        """At close, before the window hides: a start from now on waits for the lock instead of handing over."""
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None

    def release(self):
        """At the very end: the lock goes, and a start waiting for it becomes the first."""
        self.stop_listening()
        if self._held is not None:
            path_utils.release_lock(self._held)
            self._held = None
