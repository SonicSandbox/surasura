"""Setup's load screen, its Qt-free half (Sonic 2026-10-30).

The steps after the library step, in order — the first scan (`setup_wizard.read_folders`), the token store's indexing
(the window's own `Chores.index`), the covers from disk (`covers.scan` through the window's `scan_covers`) and the
known-words sync page 2 started — are run by the services that already own them; this module only reads the
indexer's count back from its log (`read_count`), on a worker.
"""
import os
import re

from app.indexer import PROGRESS_LINE

TAIL = 4096                     # the log's last bytes read for its newest count
_COUNT = re.compile(re.escape(PROGRESS_LINE).replace(r"\{done\}", r"(\d+)").replace(r"\{total\}", r"(\d+)"))


def read_count(path, since=None):
    """(A worker.) The indexer's newest `PROGRESS_LINE` in its log `path` -> (done, total), or None (no log, no count
    yet, a log being rewritten). `since` (a time.time()): a log last written before it is an earlier run's — None."""
    if not path:
        return None
    try:
        if since is not None and os.path.getmtime(path) < since:
            return None
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    found = _COUNT.findall(tail)
    if not found:
        return None
    done, total = found[-1]
    return int(done), int(total)
