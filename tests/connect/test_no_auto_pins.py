"""Nothing pins by itself (P2.2 row 2.2.7; G1.6-10, G1.5-4, Kura's L2.2 §5.6).

Sonic, G1.5-4: "I'd prefer it be closer to the automated version" — every card follows the new order; and G1.6-10:
the one pin is the user's own *Study its cards first*. So the only writers of `items.pinned` are the store's `pin` and
`unpin`. What would go wrong unseen: a move out of the top 20, a finish, Connect or a re-sort quietly pinning an item,
its cards then jumping the queue for weeks with nothing on screen to say why.

Two guards: the code (no source outside the store writes the column), and the behaviour — every path run for real
with the store's `pin` / `unpin` booby-trapped and the column compared before and after: Connect's verbs, your own
drag and another program's move out of the top 20, a 3.0 finish, the level raise, and a re-sort run end to end on
the fake collection with pins switched on.
"""
import glob
import os
import re

import pytest

from app import library_store
from app.connect import level, library
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A call of the store's pin / unpin, or SQL that writes the column (SET pinned = …, `pinned = ?` in a SET list).
WRITES_A_PIN = re.compile(r"\.(?:un)?pin\(|\bpinned\s*=\s*\?|SET\s+pinned\b", re.I)


def _sources():
    for pattern in ("app/**/*.py", "modules/**/*.py", "app_entry.py"):
        for path in glob.glob(os.path.join(PROJECT_ROOT, pattern), recursive=True):
            rel = os.path.relpath(path, PROJECT_ROOT).replace("\\", "/")
            if "/tests/" in rel or rel.startswith("tests/"):
                continue
            yield rel, path


def test_no_code_outside_the_store_writes_a_pin():
    offenders = []
    for rel, path in _sources():
        if rel == "app/library_store.py":
            continue                    # the store: checked by behaviour below (its commands run with a trap)
        with open(path, encoding="utf-8", errors="replace") as f:
            for number, line in enumerate(f, 1):
                if WRITES_A_PIN.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{rel}:{number}: {line.strip()}")
    assert offenders == [], "only the user's Study its cards first may pin: " + "; ".join(offenders)


@pytest.fixture
def trapped(monkeypatch):
    """The store's `pin` / `unpin` fail the test if anything calls them."""
    def trap(self, ids, *a, **k):
        pytest.fail(f"something pinned or unpinned {ids} by itself")
    monkeypatch.setattr(library_store.Store, "pin", trap)
    monkeypatch.setattr(library_store.Store, "unpin", trap)


def _pins():
    with c.store() as s:
        rows = s.conn.execute("SELECT id, pinned FROM items").fetchall()
        return int(s.meta().get("pins_version", 0)), {i: p for i, p in rows}


def test_connects_verbs_moves_out_of_the_top_20_and_the_level_raise_pin_nothing(trapped):
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
        first = library.mine_line(s)[0]
    before = _pins()
    assert all(p is None for p in before[1].values())
    assert h.call("connect", "--consume-only")[0] == 0
    code, line = h.call("place", "--file", str(first), "--to", "later", "--source", "my-script")  # another program
    assert code == 0, line
    with c.store() as s:
        second = library.mine_line(s)[0]
        library.place(s, second, "goal", source="user")              # your own drag out of the top 20 (explicit)
        s.receipt(first, "2026-10-07T09:00:00Z")
        level.check(s, "ja", {("冒険", "ボウケン")}, "run-1", {})
        level.check(s, "ja", {("冒険", "ボウケン"), ("眼鏡", "メガネ")}, "run-2", {})
    assert h.call("connect", "--consume-only")[0] == 0
    assert _pins() == before, "nothing but the user's own pin writes one"


def test_a_3_0_finish_pins_nothing(trapped):
    """L2.2 §5.6: Finish never pins (only the user's own pin, which survives it)."""
    c.library(arrivals=True)
    with c.store() as s:
        item = s.ids("now")[0]
    before = _pins()
    code, line = h.call("finish", "--file", str(item), "--source", "my-script")
    assert code == 0, line
    assert _pins() == before


def test_a_re_sort_run_end_to_end_with_pins_on_pins_nothing(trapped, monkeypatch):
    """`resort` on the fake collection, the 3.0 constant on: it reads the pins (none in a 2.x store), moves cards, and
    writes no pin."""
    rep = pytest.importorskip("modules.junban.tests.test_reposition")
    connect = pytest.importorskip("modules.junban.connect")
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    from app import analyzer
    monkeypatch.setattr(analyzer, "journey_is_current", lambda argv, lang: True)     # no Generate in this test
    c.library()
    before = _pins()
    rep._results(h.root(), progressive=rep._JOURNEY, library=rep._LIBRARY, floor=11)
    cards, notes, _ = rep._collection(["須藤", "散歩", "図書館", "冒険"])
    fake = rep.FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend"))
    saved = rep._settings(junban_order="content", enable_junban=True, connect_enabled=True)
    saved.pop("junban_url", None)
    h.write_settings(**{**saved, "anki_connect_url": "http://127.0.0.1:18765"})
    with rep._patched(fake):
        code, line = h.call("resort")
    assert code == 0 and not line.get("skipped") and line["moves"] > 0 and line["pinned_first"] == 0, line
    assert _pins() == before
