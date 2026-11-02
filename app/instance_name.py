"""The window's one-instance name (`app/qt/single.py`), Qt-free: the report's scrub (`app/scrub.py`) reads it too, so
the name, its user and its install part are written `<you>` / `<install key>` in a report without pulling Qt in."""
import getpass
import hashlib
import os
import re
import sys

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
