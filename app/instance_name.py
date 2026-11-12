"""The window's one-instance name (`app/qt/single.py`), Qt-free: the report's scrub (`app/scrub.py`) reads it too, so
the name, its user and its install part are written `<you>` / `<install key>` in a report without pulling Qt in.

`ask_window` speaks the same one-line protocol as a second start (`single.SingleInstance._hand_over`), without Qt:
Piyo's *Send report* (app/cli/mcp_server.py) hands the open window its words this way. A local named pipe (Windows)
or socket file: never a network call, and only this user's session reaches it.
"""
import getpass
import hashlib
import json
import os
import re
import sys
import time

from app import path_utils


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


def install_part():
    """The name's 12 hex characters for the install (its local data folder)."""
    return hashlib.sha256(path_utils.get_local_data_path().encode("utf-8")).hexdigest()[:12]


def instance_name():
    """The pipe's name: the user, the session and the install (a test's own name when it sets one)."""
    override = os.environ.get("SURASURA_INSTANCE_NAME")
    if override:
        return override
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    raw = f"surasura-window-{user}-{_session_id()}-{install_part()}"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)


CONNECT_S = 0.3                 # as single.CONNECT_MS: the window takes a start at once, or isn't there
ANSWER_S = 2.0                  # as single.ANSWER_MS


def ask_window(args, name=None, answer_s=ANSWER_S):
    """Hand the open window `args` (strings, JSON in one line), as a second start would. -> True when it answered ok,
    None when no window is listening, False when one took the line and never answered."""
    name = name or instance_name()
    line = (json.dumps([str(a) for a in args]) + "\n").encode("utf-8")
    if sys.platform == "win32":
        return _ask_pipe("\\\\.\\pipe\\" + name, line, answer_s)            # QLocalServer's pipe on Windows
    return _ask_socket(name, line, answer_s)


def _ask_pipe(path, line, answer_s):
    import ctypes
    import msvcrt
    deadline = time.monotonic() + CONNECT_S
    while True:
        try:
            f = open(path, "r+b", buffering=0)
            break
        except FileNotFoundError:
            return None                                      # no window
        except OSError:                                      # every instance busy for a moment: try again
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.02)
    from ctypes import wintypes
    peek = ctypes.windll.kernel32.PeekNamedPipe
    peek.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                     ctypes.c_void_p)
    peek.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(f.fileno())

    def read_line():
        data, until = b"", time.monotonic() + answer_s
        while b"\n" not in data:
            ready = wintypes.DWORD(0)
            if not peek(handle, None, 0, None, ctypes.byref(ready), None):
                return None                                  # the window let go
            if ready.value:
                data += f.read(ready.value)
            elif time.monotonic() >= until:
                return None
            else:
                time.sleep(0.01)
        return data.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    try:
        if not (read_line() or "").startswith("hello "):
            return False
        f.write(line)
        return read_line() == "ok"
    except OSError:
        return False
    finally:
        f.close()


def _ask_socket(name, line, answer_s):
    import socket
    import tempfile
    path = name if os.path.isabs(name) else os.path.join(tempfile.gettempdir(), name)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(CONNECT_S)
        try:
            s.connect(path)
        except OSError:
            return None
        s.settimeout(answer_s)
        f = s.makefile("rwb")
        if not f.readline().startswith(b"hello "):
            return False
        f.write(line)
        f.flush()
        return f.readline().strip() == b"ok"
    except OSError:
        return False
    finally:
        s.close()
