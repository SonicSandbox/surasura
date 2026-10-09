"""Connect on demand (P2.1 row 2.1.5): `kick` starts `surasura-cli connect` (P2.4: its loop) detached when work appears,
unless Connect is off, already running (its single-instance lock) or an update is staged.

What a wrong answer would cost: two Connects at once would mine one episode twice; a Connect started while an update
is staged would hold files the updater must swap; one started with the preview off would be Connect running for a user
who never turned it on. Real subtitles, the test's own root; the started processes are waited for.
"""
import os
import threading

import pytest

from app import library_store, locks
from app.connect import kick, library
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


@pytest.fixture
def kicks(monkeypatch):
    """Let `kick` start real processes under this test's root, and wait for every one before the root goes."""
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    started = []
    yield started
    for proc in started:
        proc.wait(timeout=120)


def _work():
    """Connect on, its watermark set, then an item moved into the top 2: one job's worth of work."""
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
        library.ensure_reader(s)
        item = s.ids("now")[-1]
        library.place(s, item, "now", source="user")
    return item


def test_a_kick_starts_connects_loop_which_takes_the_work_and_exits(kicks):
    item = _work()
    proc = kick.kick({"connect_enabled": True})
    assert proc is not None
    kicks.append(proc)
    assert proc.wait(timeout=120) == 0
    # P2.4: the started Connect runs its loop; under a test root Anki is switched off, so the job waits for the next
    # start (never a look every 2 minutes for Anki that can't come)
    from app.connect import runner
    with Ledger() as ledger:
        assert [(j["item_id"], j["state"], j["reason"]) for j in ledger.jobs("ja")] ==             [(item, "waiting", runner.ANKI_OFF)]
    assert not kick.running(), "it exited: Connect runs only while there's work"


def test_two_kicks_make_one_job_and_never_two_connects_at_once(kicks):
    item = _work()
    for _ in range(2):
        proc = kick.kick({"connect_enabled": True})
        if proc is not None:
            kicks.append(proc)
    assert kicks and all(p.wait(timeout=120) == 0 for p in kicks)
    with Ledger() as ledger:
        assert [j["item_id"] for j in ledger.jobs("ja")] == [item]


def test_a_running_connect_is_not_started_again_and_a_second_one_steps_aside(kicks):
    _work()
    taken, done = threading.Event(), threading.Event()

    def running_connect():                  # another Connect: the lock held on a thread of its own
        with locks.take(kick.LOCK, "Connect (this test)"):
            taken.set()
            done.wait(60)
    holder = threading.Thread(target=running_connect)
    holder.start()
    try:
        assert taken.wait(10)
        assert kick.running() is True
        assert kick.kick({"connect_enabled": True}) is None
        code, lines = h.run_cli("connect", "--consume-only")
        assert code == 0 and h.answer(lines)["skipped"] == "already running", lines
    finally:
        done.set()
        holder.join()
    with Ledger() as ledger:
        assert ledger.jobs("ja") == []


def test_nothing_starts_with_the_preview_off_or_an_update_staged(kicks):
    _work()
    assert kick.kick({"connect_enabled": False}) is None
    marker = library_store.update_staged_path()
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as f:
        f.write("{}")
    try:
        assert kick.kick({"connect_enabled": True}) is None
        code, line = h.call("connect", "--consume-only")
        assert (code, line["code"]) == (3, "update-staged"), "Connect refuses to start while an update is staged"
    finally:
        os.remove(marker)


def test_under_a_test_root_kick_starts_nothing_unless_asked():
    _work()
    assert "SURASURA_CONNECT_KICK" not in os.environ
    assert kick.kick({"connect_enabled": True}) is None


def test_the_connect_verb_with_the_preview_off_or_without_consume_only():
    c.library(connect=False)
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["skipped"] == "connect preview off"
    code, line = h.call("connect")
    assert code == 0 and line["skipped"] == "connect preview off", "off: the loop never starts either"
    h.write_settings(connect_enabled=True)
    code, line = h.call("connect")
    assert code == 0 and line["looks"] == 1 and line["languages"]["ja"]["done"] == [], "P2.4: no job, it exits"


def test_register_kicks_connect_when_it_is_on(kicks, monkeypatch):
    c.library()
    seen = []
    monkeypatch.setattr(kick, "kick", lambda loaded: seen.append(loaded.get("connect_enabled")))
    path = c.drop("Example Show - 05.ja.srt")
    code, _line = h.call("register", "--pairing", c.write_record(c.record(path, "video-05")))
    assert code == 0 and seen == [True]
    code, _line = h.call("register", "--pairing", c.write_record(c.record(path, "video-05")))
    assert code == 0 and seen == [True, True], "a retry kicks too: a crash after the first commit never loses it"
