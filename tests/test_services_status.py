"""The status service (`app/services/status.py`) — W1.3, the window's spec 04 §4.2.

What a wrong answer would cost:
  * a silent window — Sonic asked to see, subtly, that Surasura is updating known words, generating, re-ordering Anki
    (G1.5-2); a running job with no line is invisible work;
  * a command-line failure that freezes or hides — it must reach the bar in plain words, once, never as a box (G0.3-1),
    and stay listed in *Needs you* after it was looked at;
  * an empty bar because one part failed — a provider's fault must leave the rest;
  * a stutter — the window's poll must be a stat, never a read.
"""
import os
import threading

import pytest

from app.cli import contract
from app.services import jobs as J
from app.services.jobs import JobRegistry
from app.services.status import StatusService, job_line
from tests import services_helpers as h


def _failure(verb="status", message="Surasura's settings (settings.json) can't be read."):
    contract._record_event({"type": "error", "contract": 1, "ok": False, "code": "bad-data", "message": message,
                            "verb": verb, "exit": 1, "time": "2026-10-06T01:00:00"})


def test_running_jobs_show_in_the_users_words_with_their_step():
    registry = JobRegistry()
    status = StatusService(registry)
    sync = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None, automatic=True)
    gen = registry.submit("generate", "Generating", lambda j: None)
    gen.progress("Reading your files", 3, 12)
    assert status.snapshot().lines == ("Updating known words from Anki", "Generating · Reading your files 3 / 12")
    registry.submit("generate", "Generating (automatic)", lambda j: None, automatic=True)
    assert status.snapshot().lines[-1] == "Generating (automatic) · waits for Generating"
    sync.finish()
    gen.cancel()
    assert status.snapshot().lines[0] == "Generating · stopping"


def test_job_line_for_a_step_without_counts():
    view = J.JobView(1, "mine", "Mining 12 words", J.RUNNING, None, None, J.Progress("Asking Anki Miner", None, None),
                     0, None, True, "cancel", False, True)
    assert job_line(view) == "Mining 12 words · Asking Anki Miner"


def test_a_command_line_failure_reaches_the_bar_once_in_plain_words_and_stays_in_needs_you():
    status = StatusService(JobRegistry())
    status.refresh()                                       # the reader starts at the file's end: history isn't news
    _failure()
    assert status.poll() is not None
    assert h.until(lambda: status.snapshot().failure is not None, seconds=10)
    snap = status.snapshot()
    assert snap.failure.startswith("Command line (status): Surasura's settings (settings.json) can't be read")
    assert [e.seen for e in snap.needs_you] == [False]
    status.mark_seen()
    status.refresh()                                       # nothing new: no second entry
    assert [e.seen for e in status.snapshot().needs_you] == [True]
    assert status.snapshot().logs == contract.log_folder()


def test_poll_is_a_stat_within_4_ms():
    status = StatusService(JobRegistry())
    status.refresh()
    for _ in range(20):
        _, ms = h.timed(status.poll)
        assert ms <= h.AT_ONCE_MS, ms


def test_a_provider_that_fails_leaves_the_rest_of_the_snapshot():
    registry = JobRegistry()

    def broken():
        raise OSError("the sync state can't be read")
    status = StatusService(registry, providers={"ankiweb": broken, "connect": lambda: "Connect: 3 words to mine"})
    registry.submit("generate", "Generating", lambda j: None)
    status.refresh()
    snap = status.snapshot()
    assert snap.ankiweb is None and snap.connect == "Connect: 3 words to mine" and snap.lines == ("Generating",)


def test_subscribers_hear_each_new_snapshot_and_a_failing_one_is_harmless():
    registry = JobRegistry()
    status = StatusService(registry)
    heard = []

    def broken(_snap):
        raise RuntimeError("a listener's own fault")
    status.subscribe(broken)
    status.subscribe(heard.append)
    registry.submit("junban", "Re-ordering Anki", lambda j: None)
    assert heard and heard[-1].lines == ("Re-ordering Anki",)


def test_without_an_events_file_the_bar_is_quiet():
    """A first run: no logs folder yet. Nothing fails, nothing shows."""
    status = StatusService(JobRegistry())
    status.refresh()
    assert status.snapshot().failure is None and not os.path.exists(os.path.join(contract.log_folder(),
                                                                                 "cli-events.jsonl"))


def test_poll_never_reads_the_events_file_on_the_callers_thread():
    """The read (`new()`) is a worker's, even when the file changed: only the stat runs where the window calls."""
    import threading
    status = StatusService(JobRegistry())
    status.refresh()
    reads, real_new = [], status._reader.new

    def recording_new():
        reads.append(threading.current_thread())
        return real_new()
    status._reader.new = recording_new
    _failure()
    caller = threading.current_thread()
    status.poll()
    assert h.until(lambda: reads, seconds=10)
    assert caller not in reads


def test_the_duties_failures_reach_the_bar_once_and_generates_is_listed_in_needs_you():
    """W3.5 (E10, IK-7): Generate's failure and the update's are the bar's failure line, each new one once; Generate's
    is a Needs you entry, the update's is not (the window lists those with their own actions); a provider that goes
    quiet and fails again with the same words counts again."""
    lines = {"generate": None, "update": None}
    status = StatusService(JobRegistry(), providers={"generate": lambda: lines["generate"],
                                                     "update": lambda: lines["update"]})
    status.refresh()
    assert status.snapshot().failure is None and status.snapshot().needs_you == ()
    lines["generate"] = "Generate stopped (exit code 1)."
    status.refresh()
    status.refresh()                                      # asked again: the same failure, not a second entry
    snap = status.snapshot()
    assert snap.failure == "Generate stopped (exit code 1)."
    assert [e.text for e in snap.needs_you] == ["Generate stopped (exit code 1)."]
    lines["update"] = "The automatic update didn't finish."
    status.refresh()
    snap = status.snapshot()
    assert snap.failure == "The automatic update didn't finish."
    assert [e.text for e in snap.needs_you] == ["Generate stopped (exit code 1)."]
    assert snap.ankiweb is None and snap.connect is None   # the failure providers never become marks
    lines["generate"] = None
    status.refresh()
    lines["generate"] = "Generate stopped (exit code 1)."
    status.refresh()
    assert len(status.snapshot().needs_you) == 2


def test_a_duty_failure_leaves_the_bar_once_it_is_over_and_a_command_lines_stays():
    """HR-23 (E10: `failed` in the bar while it is): a duty's failure line is the bar's while its provider gives it —
    Generate failed until it runs cleanly again, the update's failure until it is looked at — then the bar's line goes
    (still listed in Needs you); a command line's failure stays the bar's until a newer one (W1.3), and a duty going
    quiet never takes away a command line's line that came after it."""
    lines = {"generate": None, "update": None}
    status = StatusService(JobRegistry(), providers={"generate": lambda: lines["generate"],
                                                     "update": lambda: lines["update"]})
    status.refresh()
    lines["generate"] = "Generate stopped (exit code 1)."
    status.refresh()
    assert status.snapshot().failure == "Generate stopped (exit code 1)."
    lines["generate"] = None                              # it ran again, cleanly
    status.refresh()
    assert status.snapshot().failure is None
    assert [e.text for e in status.snapshot().needs_you] == ["Generate stopped (exit code 1)."]
    lines["update"] = "The automatic update didn't finish."
    status.refresh()
    assert status.snapshot().failure == "The automatic update didn't finish."
    _failure()                                            # a command line's failure after it
    status.refresh()
    assert status.snapshot().failure.startswith("Command line (status)")
    lines["update"] = None                                # looked at: it stops counting
    status.refresh()
    assert status.snapshot().failure.startswith("Command line (status)")


def test_a_refresh_asked_for_while_one_runs_runs_once_more():
    """The window asks for one refresh per Generate transition; a request that comes while a refresh runs (one started
    by a command line's event, which already asked the `generate` provider) is not dropped: the refresh runs once more,
    so Generate's failure reaches the bar and Needs you."""
    asked, entered, release = [], threading.Event(), threading.Event()
    lines = {"generate": None}

    def generate():
        asked.append(lines["generate"])
        if len(asked) == 1:
            entered.set()
            assert release.wait(10)
        return lines["generate"]
    status = StatusService(JobRegistry(), providers={"generate": generate})
    status.refresh_soon()                                 # the first refresh, already past its provider
    assert entered.wait(5)
    lines["generate"] = "Generate stopped (exit code 1)."
    status.refresh_soon()                                 # Generate failed meanwhile
    release.set()
    assert h.until(lambda: status.snapshot().failure == "Generate stopped (exit code 1).", seconds=5)
    assert [e.text for e in status.snapshot().needs_you] == ["Generate stopped (exit code 1)."]
    assert len(asked) == 2



def test_a_refresh_asked_for_as_one_ends_never_runs_beside_the_next():
    """Two refreshes at once read the events file and the providers twice over (a failure could be listed twice): a
    request that comes as a refresh publishes, while the one asked for during it is still to run, waits its turn."""
    calls, running, overlap, entered, release = [], [0], [], threading.Event(), threading.Event()
    lock = threading.Lock()

    def generate():
        with lock:
            running[0] += 1
            overlap.append(running[0])
            calls.append(1)
        try:
            if len(calls) == 1:
                entered.set()
                assert release.wait(10)
            else:
                threading.Event().wait(0.2)        # long enough for a second refresh to meet this one
        finally:
            with lock:
                running[0] -= 1
        return None
    status = StatusService(JobRegistry(), providers={"generate": generate})
    publish, asked_once = status._publish, []

    def publish_and_ask():                          # a window's request landing just as the first refresh publishes
        if not asked_once:
            asked_once.append(1)
            status.refresh_soon()
        publish()
    status._publish = publish_and_ask
    status.refresh_soon()
    assert entered.wait(5)
    status.refresh_soon()                           # asked for during the first: it runs once more
    release.set()
    assert h.until(lambda: len(calls) >= 2 and running[0] == 0, seconds=5)
    threading.Event().wait(0.3)
    assert max(overlap) == 1
    assert len(calls) == 2                          # the late request is the one still to run, not a third

def test_marking_needs_you_seen_with_nothing_unseen_says_nothing():
    """S19: opening Needs you again with every entry looked at sends no new snapshot."""
    status = StatusService(JobRegistry(), providers={"generate": lambda: "Generate stopped (exit code 1)."})
    status.refresh()
    heard = []
    status.subscribe(heard.append)
    status.mark_seen()
    assert len(heard) == 1 and all(e.seen for e in heard[0].needs_you)
    status.mark_seen()
    assert len(heard) == 1


# --- W3.5 row 7 (R7b): the re-order host's line, the journey dot, and the providers' ticks (G5, G10, gaps 9, 10) -- #
import time                                                             # noqa: E402

from app.services import status as S                                   # noqa: E402


SENT = {"connect_enabled": True}         # something sends a pending AnkiWeb sync (Connect, on): its countdown shows


class _Clock:
    """The ticks' clock, moved by the test: a tick's period is waited for by a number, never by a sleep."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _QuietReader:
    """An events file that never changes: a poll's only work is the ticks."""

    def changed(self):
        return False

    def newest_to_show(self):
        return None


def _heard(status):
    heard = []
    status.subscribe(heard.append)
    return heard


def _settle(status):
    """The refresh a poll started has ended (its worker is gone)."""
    assert h.until(lambda: not status._refreshing, seconds=5)


def test_without_providers_the_replan_line_and_the_journey_dot_are_none_and_old_snapshots_still_build():
    """The two new slots are None until the window registers their providers; a snapshot made the old way (seven
    fields, as the window's tests make one) still builds, so no caller breaks."""
    status = StatusService(JobRegistry())
    status.refresh()
    snap = status.snapshot()
    assert snap.replan is None and snap.journey is None
    old = S.Snapshot((), None, (), None, None, None, 0.0)
    assert old.replan is None and old.journey is None


def test_the_replan_line_and_the_journey_dot_come_from_their_providers_asked_on_demand():
    """The re-order host says a new line (*Anki: placing tomorrow's 20 cards…* → *Anki's order is up to date*): the
    window asks `refresh_soon("replan")`, which asks that provider alone — not Connect's, not the events file. The
    journey dot is True while the store's `journey_pending()` says the sentences are owed."""
    asked = []
    lines = {"replan": "Anki: placing tomorrow's 20 cards…"}

    def replan():
        asked.append("replan")
        return lines["replan"]

    def connect():
        asked.append("connect")
        return "Connect: mining 12 words"
    status = StatusService(JobRegistry(), providers={"replan": replan, "connect": connect, "journey": lambda: True})
    status.refresh()
    snap = status.snapshot()
    assert (snap.replan, snap.journey, snap.connect) == ("Anki: placing tomorrow's 20 cards…", True,
                                                         "Connect: mining 12 words")
    asked.clear()
    heard = _heard(status)
    lines["replan"] = "Anki's order is up to date"
    status.refresh_soon("replan")
    assert h.until(lambda: heard and heard[-1].replan == "Anki's order is up to date", seconds=5)
    _settle(status)
    assert asked == ["replan"]
    assert status.snapshot().connect == "Connect: mining 12 words"      # the others' values kept, not emptied


def test_a_refresh_that_changes_nothing_delivers_nothing():
    """S19: a subscriber hears a snapshot only when something in it changed; the same answers again send nothing."""
    status = StatusService(JobRegistry(), providers={"replan": lambda: "Generate first"})
    status.refresh()
    heard = _heard(status)
    status.refresh()
    status.refresh()
    assert heard == []


def test_connects_line_ticks_every_3_s_and_is_read_only_when_its_stamp_moves():
    """Gap 9, the Tk `status_row.StatusRow` (EVERY_MS 3000): the window's poll starts a look every 3 s; each look is
    Connect's `stamp` (two stats and a look at its lock), and only a stamp that moved reads the record — and only a
    line that changed reaches the bar (S19). The language asked is the window's."""
    clock = _Clock()
    stamps, reads, looks = [["a"]], [], []

    def stamp(languages=None):
        assert languages == ["zh"]
        looks.append(1)
        return list(stamps[-1])

    def read(languages=None):
        reads.append(list(languages))
        return {"stamp": list(stamps[-1]),
                "languages": {"zh": {"line": f"Connect: 第{len(reads)}集 · choosing words"}}}
    provider = S.connect_line("zh", lambda: {"connect_enabled": True}, stamp=stamp, read=read)
    status = StatusService(JobRegistry(), reader=_QuietReader(), providers={"connect": provider}, clock=clock)
    heard = _heard(status)
    status.poll()
    _settle(status)
    assert reads == [["zh"]] and [s.connect for s in heard] == ["Connect: 第1集 · choosing words"]
    clock.now += 2.9
    status.poll()                                        # not yet 3 s: no look at all
    _settle(status)
    assert len(looks) == 1
    clock.now += 0.2
    status.poll()                                        # a look: the same stamp, no read, nothing delivered
    _settle(status)
    assert len(looks) == 2 and len(reads) == 1 and len(heard) == 1
    stamps.append(["b"])
    clock.now += 3
    status.poll()
    _settle(status)
    assert len(reads) == 2 and [s.connect for s in heard][-1] == "Connect: 第2集 · choosing words"


def test_connects_line_is_none_while_connect_is_off_and_asks_nothing_of_it():
    """Today's switch (`connect_enabled`, Michi's): off, the bar shows no Connect line and its files aren't looked at."""
    looked = []
    settings = {"connect_enabled": False}
    provider = S.connect_line("ja", lambda: settings, stamp=lambda languages=None: looked.append(1) or ["a"],
                              read=lambda languages=None: {"languages": {"ja": {"line": "Up to date"}}})
    assert provider() is None and looked == []
    settings["connect_enabled"] = True
    assert provider() == "Up to date"


def test_connects_real_record_with_no_ledger_reads_up_to_date():
    """The provider calls Connect's own `status.stamp` / `read` (not a copy): with Connect on and no ledger yet (a
    fresh install), its line is the record's *Up to date*."""
    provider = S.connect_line("ja", lambda: {"connect_enabled": True})
    assert provider() == "Up to date"


# --- P4.1 L2 (row 4.1.13, W-A5): Connect's line is the window's Connect feed's (`app/connect/feed.Provider`) ------ #
def _record(line, jobs=()):
    return {"stamp": None, "running": True, "languages": {"ja": {"line": line, "state": "mining", "jobs": list(jobs)}}}


def test_connects_line_and_the_stones_share_one_stamp_a_tick():
    """W-A5: the line and the stones come from one feed — each tick is one `stamp` (a spy), the reader's stones read
    the look's Feed (`latest()`, no stamp of their own), and only a new Feed wakes the reader (`on_change`). What a
    wrong answer would cost: two stamps (and two record reads) every 3 s for the same answer, or stones that lag the
    line by a tick."""
    from app.connect import feed as connect_feed
    clock = _Clock()
    stamps, looks, reads, woken = [["a"]], [], [], []

    def stamp(languages=None):
        looks.append(1)
        return list(stamps[-1])

    def read(languages=None):
        reads.append(1)
        rec = _record("Making cards 2 of 5 — ぼっち・ざ・ろっく！ 第3話 (audio)",
                      [{"item": 7, "state": "mining", "made": 2, "words": 5, "job": 1}])
        rec["stamp"] = list(stamps[-1])
        return rec
    feed = connect_feed.Provider("ja", lambda: {"connect_enabled": True}, stamp=stamp, read=read)
    feed.on_change = lambda: woken.append(feed.latest())
    provider = S.connect_line("ja", lambda: {"connect_enabled": True}, feed=feed)
    status = StatusService(JobRegistry(), reader=_QuietReader(), providers={"connect": provider}, clock=clock)
    status.poll()
    _settle(status)
    assert looks == [1] and reads == [1]
    got = feed.latest()
    assert status.snapshot().connect == got.line and got.items[7].made == 2 and got.mining == {7}
    assert woken == [got], "a new Feed wakes the reader once"
    for _ in range(3):                                   # three ticks, Connect unchanged
        clock.now += 3
        status.poll()
        _settle(status)
        assert feed.latest() is got                      # the stones read the same object: nothing rebuilt (S19)
    assert len(looks) == 4 and reads == [1] and woken == [got], "one stamp a tick, no read, no wake"
    stamps.append(["b"])                                 # the stamp moves with nothing the window shows changed
    clock.now += 3
    status.poll()
    _settle(status)
    assert len(looks) == 5 and reads == [1, 1] and feed.latest() is got and woken == [got]


def test_connects_line_with_automation_off_says_why_and_with_connect_unset_shows_nothing():
    """F-7 (`settings_manager.connect_on`, not `connect_enabled` alone): set up but D29's automation off, the mark
    says why nothing runs (IK N4) and Connect's files aren't looked at; not set up, no mark at all (as before)."""
    from app.connect import feed as connect_feed
    looked = []
    settings = {"connect_enabled": True, "logic": {"automation": False}}
    provider = S.connect_line("ja", lambda: settings, stamp=lambda languages=None: looked.append(1) or ["a"],
                              read=lambda languages=None: _record("Up to date"))
    assert provider() == connect_feed.OFF_AUTOMATION and looked == []
    assert provider.every() is None
    settings["connect_enabled"] = False
    assert provider() is None and looked == []
    settings.update(connect_enabled=True, logic={"automation": True})
    assert provider() == "Up to date" and looked == [1] and provider.every() == S.TICKS["connect"]


def test_the_ankiweb_countdown_ticks_every_second():
    """Gap 10: `anki_sync_rule.status` (the Tk-free rule) gives *AnkiWeb: syncing in N s* while a sync is pending; the
    window's poll asks it every second, so the count goes down one a tick, and the bar hears each new number once."""
    from app import anki_sync_rule
    clock = _Clock()
    start = time.time()
    anki_sync_rule.wrote(True, now=start)
    provider = S.ankiweb_line(lambda: SENT, now=lambda: start + (clock.now - 1000.0))
    status = StatusService(JobRegistry(), reader=_QuietReader(), providers={"ankiweb": provider}, clock=clock)
    heard = _heard(status)
    wait = int(anki_sync_rule.delay_s({}))
    for _ in range(3):
        status.poll()
        _settle(status)
        clock.now += 0.5
        status.poll()                                     # half a second on: not due
        _settle(status)
        clock.now += 0.5
    assert [s.ankiweb for s in heard] == [f"AnkiWeb: syncing in {wait - n} s" for n in range(3)]


def test_a_tick_that_changes_nothing_delivers_nothing():
    """S19 for the ticks: the AnkiWeb mark asked every second while it says *synced 18:42* sends one snapshot, once."""
    clock = _Clock()
    asked = []
    status = StatusService(JobRegistry(), reader=_QuietReader(), clock=clock,
                           providers={"ankiweb": lambda: asked.append(1) or "AnkiWeb: synced 18:42"})
    heard = _heard(status)
    for _ in range(4):
        status.poll()
        _settle(status)
        clock.now += 1
    assert len(asked) == 4 and len(heard) == 1


def test_a_ticking_provider_that_raises_leaves_the_rest():
    """One provider's fault (Connect's ledger locked, say) never empties the bar: AnkiWeb's mark and the host's line
    stay, and the faulty one reads None."""
    clock = _Clock()

    def broken():
        raise OSError("the ledger can't be read")
    status = StatusService(JobRegistry(), reader=_QuietReader(), clock=clock,
                           providers={"connect": broken, "ankiweb": lambda: "AnkiWeb: syncing in 45 s",
                                      "replan": lambda: "Anki's order is up to date"})
    status.refresh()
    status.poll()
    _settle(status)
    snap = status.snapshot()
    assert snap.connect is None and snap.ankiweb == "AnkiWeb: syncing in 45 s"
    assert snap.replan == "Anki's order is up to date"


def test_a_tick_runs_on_a_worker_never_on_the_pollers_thread():
    """`poll()` stays safe on a window's thread: a clock compare and a worker start, the provider called elsewhere."""
    clock = _Clock()
    where = []
    status = StatusService(JobRegistry(), reader=_QuietReader(), clock=clock,
                           providers={"connect": lambda: where.append(threading.current_thread()) or "Up to date"})
    status.poll()
    assert h.until(lambda: where, seconds=5)
    assert threading.current_thread() not in where
    for _ in range(20):
        clock.now += 3
        _, ms = h.timed(status.poll)
        assert ms <= h.AT_ONCE_MS, ms
        _settle(status)


def test_the_journey_dot_reads_the_stores_journey_pending(monkeypatch):
    """G10: the dot is the store's `journey_pending()` for the window's language, read on the worker through a handle
    opened and closed there (never kept: Repair's rename); no store yet → None (no dot)."""
    from app import library_store
    opened = []

    class Store:
        def __init__(self, pending):
            self.pending, self.closed = pending, False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.closed = True

        def journey_pending(self):
            return self.pending
    stores = [Store(True), Store(False), None]
    first = stores[0]

    def open_store(language, data_dir, user_files_dir, role="window", busy_wait=None):
        opened.append(language)
        return stores.pop(0)
    monkeypatch.setattr(library_store, "open_store", open_store)
    provider = S.journey_pending("zh")
    assert provider() is True and first.closed
    assert provider() is False
    assert provider() is None
    assert opened == ["zh", "zh", "zh"]


# --- W3.5 row 7: the review's fixes -------------------------------------------------------------- #
def test_with_no_events_file_to_watch_a_poll_takes_the_ticks_never_a_full_refresh_every_500_ms(monkeypatch):
    """The events file's path can't be worked out (no reader, ever) — the window's 500 ms poll used to read as
    "the file changed" and refresh everything every time, the journey dot opening the store twice a second. Now the
    poll asks only the ticking providers whose period is up, as with a reader whose file never changes."""
    from app.cli import events

    def no_path():
        raise OSError("no logs folder can be worked out")
    monkeypatch.setattr(events, "path", no_path)
    clock = _Clock()
    asked = {"journey": 0, "ankiweb": 0}

    def journey():
        asked["journey"] += 1
        return True

    def ankiweb():
        asked["ankiweb"] += 1
        return "AnkiWeb: synced 18:42"
    status = StatusService(JobRegistry(), clock=clock, providers={"journey": journey, "ankiweb": ankiweb})
    assert status._reader is None and status._events_path is None
    for _ in range(4):
        status.poll()
        _settle(status)
        clock.now += 0.5
    assert asked["journey"] == 0, "a full refresh on a poll with nothing to watch"
    assert asked["ankiweb"] == 2                          # its ticks only: at 0 s and 1 s
    status.refresh_soon("journey")                        # asked by name, the dot is still read
    _settle(status)
    assert asked["journey"] == 1 and status.snapshot().journey is True


def test_the_ankiweb_countdown_reads_its_file_only_when_it_changed_and_still_counts_down(monkeypatch):
    """The AnkiWeb mark is asked every second; its state file is read again only when its stamp (mtime, size)
    moved — between, the last read is worked out again for the time now, so the countdown still ticks."""
    from app import anki_sync_rule
    start = time.time()
    anki_sync_rule.wrote(True, now=start)
    reads, real_read = [], anki_sync_rule.read_state

    def counted():
        reads.append(1)
        return real_read()
    monkeypatch.setattr(anki_sync_rule, "read_state", counted)
    clock = [start]
    provider = S.ankiweb_line(lambda: SENT, now=lambda: clock[0])
    wait = int(anki_sync_rule.delay_s({}))
    said = []
    for n in range(3):
        clock[0] = start + n
        said.append(provider())
    assert said == [f"AnkiWeb: syncing in {wait - n} s" for n in range(3)]
    assert len(reads) == 1, "the state file read on every tick"
    anki_sync_rule._update(front_pending=False, sync="synced", synced_at=start)    # a sync landed: the file moved
    reads.clear()
    assert provider().startswith("AnkiWeb: synced ")
    assert len(reads) == 1
    provider()
    assert len(reads) == 1


# --- W3.5 row 7: the last review round's fixes ------------------------------------------------------------- #
def _countdowns(monkeypatch):
    """`anki_sync_rule.status` counted: one per look the AnkiWeb mark's provider takes."""
    from app import anki_sync_rule
    looks, real = [], anki_sync_rule.status
    monkeypatch.setattr(anki_sync_rule, "status", lambda *a, **k: looks.append(1) or real(*a, **k))
    return looks


def test_the_ankiweb_mark_looks_every_second_only_while_it_counts_down_else_every_3_s(monkeypatch):
    """S19: with no countdown (*synced 18:42*, or no file at all) a look every second starts a thread and stats a
    file for nothing. The mark is looked at every second only while its last state had a sync due; else at Connect's
    3 s cadence — the file's stamp still read at each look, so a new pending sync is seen within 3 s."""
    from app import anki_sync_rule
    looks = _countdowns(monkeypatch)
    clock = _Clock()
    start = time.time()
    anki_sync_rule.wrote(True, now=start)
    provider = S.ankiweb_line(lambda: SENT, now=lambda: start + (clock.now - 1000.0))
    status = StatusService(JobRegistry(), reader=_QuietReader(), providers={"ankiweb": provider}, clock=clock)
    for _ in range(3):                                   # counting down: a look every second
        status.poll()
        _settle(status)
        clock.now += 1
    assert len(looks) == 3 and status.snapshot().ankiweb.startswith("AnkiWeb: syncing in ")
    anki_sync_rule._update(front_pending=False, sync="synced", synced_at=start)     # the sync went
    status.poll()                                        # the look that sees it
    _settle(status)
    assert len(looks) == 4 and status.snapshot().ankiweb.startswith("AnkiWeb: synced ")
    for _ in range(2):                                   # no countdown: 1 s and 2 s on, no look
        clock.now += 1
        status.poll()
        _settle(status)
    assert len(looks) == 4, "the mark was looked at every second with nothing counting down"
    clock.now += 1
    status.poll()                                        # 3 s on: a look
    _settle(status)
    assert len(looks) == 5


def test_connects_tick_is_skipped_while_connect_is_off_and_comes_back_when_it_is_asked_for(monkeypatch):
    """Connect off (`connect_enabled`): its first look learns it, then the 3 s tick asks nothing of it — no settings
    read, no worker started. Switched on (the window asks `refresh_soon("connect")` when the setting lands), its
    ticks run again."""
    clock = _Clock()
    settings = {"connect_enabled": False}
    reads = []
    provider = S.connect_line("ja", lambda: reads.append(1) or settings, stamp=lambda languages=None: ["a"],
                              read=lambda languages=None: {"stamp": ["a"],
                                                           "languages": {"ja": {"line": "Connect: 第3話 · up to date"}}})
    status = StatusService(JobRegistry(), reader=_QuietReader(), providers={"connect": provider}, clock=clock)
    for _ in range(4):
        status.poll()
        _settle(status)
        clock.now += 3
    assert len(reads) == 1, "Connect's tick ran while it was off"
    assert status.snapshot().connect is None
    settings["connect_enabled"] = True
    status.refresh_soon("connect")                       # the window, as the switch lands
    _settle(status)
    assert status.snapshot().connect == "Connect: 第3話 · up to date"
    status.poll()
    _settle(status)
    assert len(reads) == 3                               # on: ticking again


def test_the_ankiweb_countdown_comes_back_once_something_will_send_the_sync(monkeypatch):
    """Nothing will send the sync (Connect off, no deck recorded): no countdown — said from a copy of the file's state,
    never by changing the read the mark keeps, so once Connect turns on, the same file (unchanged) counts down."""
    pytest.importorskip("modules.junban")
    from app import anki_sync_rule
    start = time.time()
    anki_sync_rule.wrote(True, now=start)
    settings = {"enable_junban": True, "junban_deck": "Mining"}
    line = S.ankiweb_line(lambda: settings, now=lambda: start)
    assert line() is None
    settings["connect_enabled"] = True
    said = line()
    assert said is not None and said.startswith("AnkiWeb: syncing in "), said


@pytest.mark.parametrize("case, settings, countdown", [
    ("Connect on", {"connect_enabled": True}, True),
    ("the re-order host may run (the deck recorded)", {"enable_junban": True, "junban_deck": "Mining",
                                                       "junban_replan_language": "ja",
                                                       "junban_replan_deck": "Mining"}, True),
    ("automation off, Connect off", {"logic": {"automation": False}, "enable_junban": True, "junban_deck": "Mining",
                                     "junban_replan_language": "ja", "junban_replan_deck": "Mining"}, False),
    ("no deck recorded, Connect off", {"enable_junban": True, "junban_deck": "Mining"}, False),
])
def test_the_ankiweb_mark_counts_down_only_when_something_will_send_the_sync(monkeypatch, case, settings, countdown):
    """A spaced 順 run arms the AnkiWeb sync; only the re-order host (its gate holding, any language) or Connect
    sends it. With neither, *syncing in N s* would count down to 0 and stay there for an hour: a promise nobody keeps.
    Then the mark says what it said before the write (here: nothing)."""
    pytest.importorskip("modules.junban")
    from app import anki_sync_rule
    start = time.time()
    anki_sync_rule.wrote(True, now=start)
    said = S.ankiweb_line(lambda: settings, now=lambda: start)()
    if countdown:
        assert said is not None and said.startswith("AnkiWeb: syncing in "), case
    else:
        assert said is None, case


# --- W31A-2: *Anki · N waiting* — the new cards waiting in Anki, from the sync's saved backlog --------------------- #
def _backlog(language, notes):
    """A backlog file shaped as `anki_sync.sync_backlog` saves it (its atomic write): `notes` {note id: entry}, or a
    whole stand-in body (`str`) written as it is."""
    from app import anki_sync
    path = anki_sync._backlog_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(notes, str):
        body = notes
    else:
        import json
        body = json.dumps({"version": anki_sync.BACKLOG_VERSION, "synced_at": "2026-10-14T21:05:00",
                           "decks": ["日本語::Mining"], "fields": ["Word"], "notes": notes}, ensure_ascii=False)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def _note(word, freq):
    return {"word": word, "keys": [word], "source": "日本語::Mining", "freqsort": freq}


JA_NOTES = {"1700000000001": _note("撒く", 4120), "1700000000002": _note("上層部", 9870),
            "1700000000003": _note("一生懸命", 2210)}


def _reads(monkeypatch):
    """`anki_sync.load_backlog` counted: one per time the provider reads the file."""
    from app import anki_sync
    reads, real = [], anki_sync.load_backlog
    monkeypatch.setattr(anki_sync, "load_backlog", lambda language: reads.append(language) or real(language))
    return reads


def test_the_backlog_says_nothing_until_a_backlog_has_been_saved():
    """Someone who never synced sees *Anki*, never *0 waiting*: no file, no count."""
    provider = S.anki_backlog("ja")
    assert provider() is None
    assert provider.every() == S.TICKS["backlog"]


@pytest.mark.parametrize("language, notes, n", [
    ("ja", JA_NOTES, 3),
    ("zh", {"1700000000101": _note("开心", 1500), "1700000000102": _note("学习", 320)}, 2),
    ("ja", {}, 0),                                       # a read file with no notes: *Anki · 0 waiting*
])
def test_the_backlog_counts_the_notes_the_sync_saved(language, notes, n):
    from app import anki_sync
    _backlog(language, notes)
    assert S.anki_backlog(language)() == n == anki_sync.count_backlog(language)


@pytest.mark.parametrize("body", ["{\"version\": 3, \"notes\": {\"170", "[1, 2, 3]", "{\"version\": 3}",
                                  "{\"notes\": [\"撒く\"]}"])
def test_an_unreadable_or_odd_backlog_says_no_count_never_a_false_zero(body):
    """Cut short, not a table, or with no notes table: no count to say (*Anki*), where `count_backlog`'s 0 would
    read as *0 waiting*."""
    _backlog("ja", body)
    assert S.anki_backlog("ja")() is None


def test_the_backlog_is_read_again_only_when_the_file_changed(monkeypatch):
    """Ticking every 3 s, the provider stats the file; it reads it only when its stamp (mtime, size) moved, and keeps
    the count between."""
    reads = _reads(monkeypatch)
    path = _backlog("ja", JA_NOTES)
    provider = S.anki_backlog("ja")
    assert provider() == 3 and len(reads) == 1
    for _ in range(3):
        assert provider() == 3
    assert len(reads) == 1, "the backlog read on every tick"
    more = dict(JA_NOTES, **{"1700000000004": _note("走り出す", 3050)})
    _backlog("ja", more)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))     # (a coarse clock: the stamp moves for sure)
    assert provider() == 4 and len(reads) == 2
    os.remove(path)                                      # the file went: no count again
    assert provider() is None


def test_AD8_a_backlog_read_that_fails_keeps_the_last_count_and_tries_again_at_the_next_tick(monkeypatch):
    """The sync has just replaced the file and a scanner holds it a moment: that read fails. The footer keeps
    *Anki · 3 waiting* (never plain *Anki* until the next sync), and the next tick reads the new count."""
    from app import anki_sync
    path = _backlog("ja", JA_NOTES)
    provider = S.anki_backlog("ja")
    assert provider() == 3
    _backlog("ja", dict(JA_NOTES, **{"1700000000004": _note("走り出す", 3050)}))
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    real = anki_sync.load_backlog
    monkeypatch.setattr(anki_sync, "load_backlog", lambda language: {})    # held: `load_backlog`'s OSError → {}
    assert provider() == 3 and provider() == 3
    monkeypatch.setattr(anki_sync, "load_backlog", real)
    assert provider() == 4                                                  # read again, not left for the next sync


def test_the_backlog_reaches_the_snapshot_through_its_tick():
    """The window's poll asks the backlog every 3 s (a stat, on a worker); the snapshot carries the count."""
    _backlog("ja", JA_NOTES)
    clock = _Clock()
    status = StatusService(JobRegistry(), reader=_QuietReader(), providers={"backlog": S.anki_backlog("ja")},
                           clock=clock)
    assert status.snapshot().backlog is None
    status.poll()
    _settle(status)
    assert status.snapshot().backlog == 3


def test_connects_mining_is_a_job_in_the_one_registry_so_the_bottom_line_names_it():
    """Laptop row 40: "I can't tell what my actions trigger". Connect mines in its own process, so its work was only a
    quiet mark. While the feed says an item is being mined, the window's registry lists it (recorded, detached at quit:
    Connect goes on), so the bottom-left line reads it with its step; a look that changes nothing tells no one (S19);
    a look between two batches keeps it (no blink), two end it; a new provider (a language switch) ends it at once."""
    from app.connect import feed
    registry = JobRegistry()
    status = StatusService(registry)
    heard = []
    registry.subscribe(heard.append)
    looks = []

    class Feed:
        def feed(self):
            return looks[-1]

        def every(self):
            return True

    def mining(doing, pct=None, made=0, total=0):
        item = feed.Item(feed.MINING, feed.WORDS[feed.MINING], "", 7, made, total, pct, doing)
        return feed.Feed(on=True, mining=frozenset({1}), items={1: item}, line="Mining", state="ok", unseen=0,
                         updating=False)

    waiting = feed.Feed(on=True, mining=frozenset(), items={2: feed.Item(feed.WAITING, feed.WORDS[feed.WAITING], "", 8,
                                                                         0, 0)},
                        line="Waiting", state="ok", unseen=0, updating=False)
    provider = S.connect_line("ja", lambda: {}, feed=Feed(), registry=registry)
    looks.append(mining("Cutting clips (3 of 40)", 40))
    provider()
    live = registry.live(S.CONNECT_JOB_KIND)
    assert len(live) == 1 and live[0].on_quit == "detach" and not live[0].gated
    assert job_line(live[0]) == "Making cards · Cutting clips (3 of 40) 40%"
    assert status.snapshot().lines == ("Making cards · Cutting clips (3 of 40) 40%",)
    told = len(heard)
    provider()                                                            # the same step again: nothing told
    assert len(heard) == told
    looks.append(mining(None, made=3, total=12))
    provider()
    assert [job_line(v) for v in registry.live(S.CONNECT_JOB_KIND)] == ["Making cards · 3 / 12"]
    looks.append(waiting)
    provider()                                                            # one look between batches: kept
    assert len(registry.live(S.CONNECT_JOB_KIND)) == 1
    provider()                                                            # two: over
    assert registry.live(S.CONNECT_JOB_KIND) == () and status.snapshot().lines == ()
    looks.append(mining("Cutting clips (9 of 40)", 10))
    provider()
    assert len(registry.live(S.CONNECT_JOB_KIND)) == 1
    S.connect_line("zh", lambda: {}, feed=Feed(), registry=registry)      # a language switch: the last one's ends
    assert registry.live(S.CONNECT_JOB_KIND) == ()
    S.mirror_connect(None, looks[-1])                                     # no registry: nothing to list
