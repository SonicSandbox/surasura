"""Nothing pins by itself (P2.2 row 2.2.7; G1.6-10, G1.5-4, Kura's L2.2 §5.6).

Sonic, G1.5-4: "I'd prefer it be closer to the automated version" — every card follows the new order; and G1.6-10:
the one pin is the user's own *Study its cards first*. So the only writers of `items.pinned` are the store's `pin` and
`unpin`. What would go wrong unseen: a move out of the top 20, a finish, Connect or a re-sort quietly pinning an item,
its cards then jumping the queue for weeks with nothing on screen to say why.

Two guards: the code (no source but the store's own writes a pin), and the behaviour (Connect's verbs, a move out of
the top 20, the level raise and a re-sort leave every pin and `pins_version` as they were).
"""
import glob
import os
import re

from app.connect import level, library
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A call of the store's pin / unpin, or SQL that writes the column.
WRITES_A_PIN = re.compile(r"\.(?:un)?pin\(|SET\s+pinned\b|pins_version\"?\s*,\s*[^)]*\+\s*1", re.I)


def _sources():
    for pattern in ("app/**/*.py", "modules/**/*.py", "app_entry.py"):
        for path in glob.glob(os.path.join(PROJECT_ROOT, pattern), recursive=True):
            rel = os.path.relpath(path, PROJECT_ROOT).replace("\\", "/")
            if "/tests/" in rel or rel.startswith("tests/"):
                continue
            yield rel, path


def test_no_code_but_the_stores_own_writes_a_pin():
    offenders = []
    for rel, path in _sources():
        if rel == "app/library_store.py":
            continue                                    # `pin` / `unpin` themselves, the copy and the undo of them
        with open(path, encoding="utf-8", errors="replace") as f:
            for number, line in enumerate(f, 1):
                if WRITES_A_PIN.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{rel}:{number}: {line.strip()}")
    assert offenders == [], "only the user's Study its cards first may pin: " + "; ".join(offenders)


def _pins():
    with c.store() as s:
        rows = s.conn.execute("SELECT id, pinned FROM items").fetchall()
        return int(s.meta().get("pins_version", 0)), {i: p for i, p in rows}


def test_connects_verbs_a_move_out_of_the_top_20_the_level_raise_and_a_re_sort_pin_nothing():
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
        first = library.mine_line(s)[0]
    before = _pins()
    assert all(p is None for p in before[1].values())
    assert h.call("connect", "--consume-only")[0] == 0
    code, line = h.call("place", "--file", str(first), "--to", "later", "--source", "user")       # an explicit move out
    assert code == 0, line
    assert h.call("finish", "--file", str(first))[0] == 2                                          # 2.x: held to 3.0
    with c.store() as s:
        s.receipt(first, "2026-10-07T09:00:00Z")
        level.check(s, "ja", {("冒険", "ボウケン")}, "run-1", {})
        level.check(s, "ja", {("冒険", "ボウケン"), ("眼鏡", "メガネ")}, "run-2", {})
    assert h.call("connect", "--consume-only")[0] == 0
    assert h.call("resort")[1].get("skipped")                                                # Anki off for the suite
    assert _pins() == before, "nothing but the user's own pin writes one"
