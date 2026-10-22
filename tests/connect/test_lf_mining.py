"""Laptop round 5 (rows 22, 24, 24b, 26, 27): what stalled, skipped and mislabelled Connect's mining on the laptop.

- **22:** the Anki profile Connect makes cards in is the first one Anki shows while Connect is on — recorded by the
  session's own look (`anki_session.waiting`) — never *Needs you* because setup's page never wrote it.
- **24 / 24b:** a wait that holds for every episode (on battery, Anki closed or busy, another profile, you reviewing)
  ends the pass: every episode keeps its place, and the next look starts from the top — never a later episode (or the
  next show) mined before the ones that waited.
- **26:** Connect calls Anki closed only when its port refuses (`anki_session.look`); a slow answer is *busy*.
- **27:** cards made → the Anki backlog read again at once (the footer's count follows within its 3 s look).

What a wrong answer would cost: Connect never mining after setup; episodes mined out of order, the skipped ones after
the next show; "Anki closed" while it is open; a count that lies for ten minutes. Against `FakeSteps` and stand-ins
for Anki; never a live Anki.
"""
import pytest

from app import anki_connect
from app.connect import anki_session, feed, power, runner, setup
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


class _PowerBlip(FakeSteps):
    """On battery from the moment `at` is picked until `clear` of the session's looks have answered so — then
    plugged in again (the laptop unplugged mid-run and plugged back in)."""

    def __init__(self, folder, plan, at, reason=runner.ON_BATTERY, clear=1):
        super().__init__(folder, plan)
        self.at, self.reason, self.left = at, reason, clear

    def blocked(self, lang):
        self.log.append(("blocked", lang))
        if any(e[:2] == ("pick", self.at) for e in self.log) and self.left > 0:
            self.left -= 1
            return self.reason
        return None


def _mined(steps):
    return [e[1] for e in steps.log if e[0] == "mine"]


@pytest.mark.parametrize("reason", [runner.ON_BATTERY, runner.ANKI_CLOSED, anki_session.BUSY, runner.REVIEWING,
                                    runner.WRITER_BUSY])
def test_a_wait_for_every_episode_mid_pass_keeps_the_list_order(tmp_path, ledger, reason):
    # why (row 24): unplugged as episode 2 came up, plugged back in at once — before the fix, 2 sat out the pass while
    # 3 was mined first; now the pass ends at 2 and the next look starts from the top: 1, 2, 3
    plan = {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}}
    steps = _PowerBlip(str(tmp_path), plan, at=2, reason=reason)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=5)
    assert _mined(steps) == [1, 2, 3]
    assert {j["item_id"]: j["state"] for j in ledger.jobs("ja")} == {1: "done", 2: "done", 3: "done"}


def test_the_next_show_waits_behind_the_episode_that_waited_on_battery(tmp_path, ledger):
    # why (row 24b): item 3 stands for the next show's first episode, later in the top 20; still on battery, it is
    # never picked in that pass — every episode left waits with the same reason, in its place
    plan = {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}}
    steps = _PowerBlip(str(tmp_path), plan, at=2, clear=99)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert _mined(steps) == [1]
    assert ("pick", 3) not in [e[:2] for e in steps.log], "the next show isn't started on battery"
    assert summary["languages"]["ja"]["waiting"] == {2: runner.ON_BATTERY, 3: runner.ON_BATTERY}


def test_an_episodes_own_wait_still_lets_the_next_one_go(tmp_path, ledger):
    # why: a wait that is one episode's own (its video not on this computer) never holds the others back
    plan = {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}, "videos": {"2": None}}
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert _mined(steps) == [1, 3]
    assert summary["languages"]["ja"]["waiting"] == {2: runner.NO_VIDEO}


def test_every_amber_wait_is_one_that_ends_the_pass():
    # why: one rule decides both what the row shows amber (on Anki, on battery) and what holds every episode
    for reason in (runner.ON_BATTERY, runner.ANKI_CLOSED, runner.REVIEWING, runner.WRITER_BUSY, anki_session.BUSY,
                   anki_session.UNUSABLE, anki_session.NO_PROFILE_YET, anki_session.OTHER_PROFILE.format("a", "b")):
        assert runner.holds_every(reason), reason
        rec = {"languages": {"ja": {"jobs": [{"item": 1, "job": 1, "state": "waiting", "reason": reason}]}}}
        assert feed.build(rec, "ja").items[1].kind in (feed.ANKI, feed.BATTERY), reason
    for reason in (runner.NO_VIDEO, runner.LIBRARY_BUSY, runner.ANKI_MINER_OPEN, "", None):
        assert not runner.holds_every(reason), reason


# --- 26: closed only when the port refuses ------------------------------------------------------------------------- #
def test_with_anki_switched_off_for_the_run_it_is_never_asked(monkeypatch):
    # why: the suites and a developer's run never reach Anki: no look, the old words
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    monkeypatch.setattr(anki_session, "look", lambda url: pytest.fail("Anki was asked"))
    assert runner._anki_wait("http://127.0.0.1:8765").reason == runner.ANKI_CLOSED


@pytest.mark.parametrize("state, reason", [("closed", runner.ANKI_CLOSED), ("busy", anki_session.BUSY),
                                           ("open", anki_session.BUSY), ("unusable", anki_session.UNUSABLE)])
def test_a_failed_anki_call_is_named_by_the_sessions_look(monkeypatch, state, reason):
    # why (row 26): a timeout under load (Anki's own sync, a laptop at full tilt) read as "it isn't open"
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_session, "look", lambda url: state)
    wait = runner._anki_wait("http://127.0.0.1:8765", "mining")
    assert (wait.reason, wait.resume) == (reason, "mining")


def test_anki_miners_unreachable_verdict_is_named_by_the_look(monkeypatch):
    # why: Anki Miner's own ANKI_UNREACHABLE (its check timed out) is a busy Anki while the port answers
    from app.connect import anki_miner
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_session, "look", lambda url: "busy")
    wait = runner._miner_wait_or_needs(anki_miner.AnkiMinerError("anki-closed", "Anki isn't open."), "http://x")
    assert wait.reason == anki_session.BUSY


def test_the_known_sync_probe_timing_out_is_busy_not_closed(monkeypatch, tmp_path):
    # why: `known_sync`'s 5 s probe failing says `anki-closed` whatever the cause; the run names it by the look
    from app.cli import verbs
    from app.cli.contract import CliError

    def known_sync(ns):
        raise CliError("anki-closed", "Anki isn't open (or AnkiConnect isn't installed).")
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(verbs, "known_sync", known_sync)
    monkeypatch.setattr(verbs, "_results_language", lambda: None)
    monkeypatch.setattr(anki_session, "begin", lambda url, settings: None)
    monkeypatch.setattr(anki_session, "look", lambda url: "busy")
    steps = runner.Steps({"connect_enabled": True})
    with pytest.raises(runner.Wait) as got:
        steps.prepare("ja", None)
    assert got.value.reason == anki_session.BUSY


# --- 22: the profile ------------------------------------------------------------------------------------------- #
def _anki(monkeypatch, open_now, calls=None):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: False)
    monkeypatch.setattr(anki_session, "look", lambda url: "open")
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: False)

    def invoke(action, url, timeout=30, **params):
        if calls is not None:
            calls.append(action)
        assert action == "getActiveProfile"
        if open_now is None:
            raise anki_connect.AnkiError("no answer", kind="offline")
        return open_now
    monkeypatch.setattr(anki_connect, "invoke", invoke)


def test_no_profile_recorded_takes_the_open_one_and_mines(monkeypatch, tmp_path):
    # why (row 22): setup's page never wrote the record; the first profile Anki shows while Connect is on is
    # Connect's — recorded, and the gate opens (no *Needs you*)
    monkeypatch.setattr(setup, "record_path", lambda: str(tmp_path / "setup.json"))
    _anki(monkeypatch, "日本語")
    steps = runner.Steps({"connect_enabled": True})
    assert steps.blocked("ja") is None
    assert setup.anki_profile() == "日本語"
    assert setup.read_record()["anki_profile_at"]


def test_the_recorded_profile_is_kept_and_another_open_one_waits(monkeypatch, tmp_path):
    # why: once recorded, another profile open is a wait (E3), and the record is never moved to it
    monkeypatch.setattr(setup, "record_path", lambda: str(tmp_path / "setup.json"))
    setup.write_record({"anki_profile": "日本語", "anki_profile_at": "2026-10-21T10:00:00"})
    _anki(monkeypatch, "DevTest")
    steps = runner.Steps({"connect_enabled": True})
    assert steps.blocked("ja") == anki_session.OTHER_PROFILE.format("日本語", "DevTest")
    assert setup.anki_profile() == "日本語"


def test_anki_not_saying_its_profile_is_a_wait_and_nothing_is_recorded(monkeypatch, tmp_path):
    # why: no record and Anki doesn't name its profile: nothing may be written (E3's guard can't hold) — a wait that
    # looks again, never *Needs you*
    monkeypatch.setattr(setup, "record_path", lambda: str(tmp_path / "setup.json"))
    _anki(monkeypatch, None)
    steps = runner.Steps({"connect_enabled": True})
    assert steps.blocked("ja") == anki_session.NO_PROFILE_YET
    assert setup.anki_profile() is None


def test_a_profile_another_program_recorded_meanwhile_wins(monkeypatch, tmp_path):
    # why: the record is written onto the file as it is: a profile recorded by the window a moment before is kept
    monkeypatch.setattr(setup, "record_path", lambda: str(tmp_path / "setup.json"))
    setup.write_record({"anki_miner": None})
    assert setup.keep_profile("日本語") == "日本語"
    assert setup.keep_profile("DevTest") == "日本語"
    assert setup.read_record()["anki_miner"] is None


# --- 27: the backlog after cards land ------------------------------------------------------------------------------- #
def test_cards_made_read_the_anki_backlog_again(monkeypatch):
    # why (row 27): the footer counts the backlog file; Connect's batch end now reads it again at once
    from app.cli import verbs
    read = []
    monkeypatch.setattr(verbs, "_backlog_read", lambda loaded, lang: read.append(lang))
    monkeypatch.setattr(anki_session, "after_write", lambda settings, front: None)
    runner.Steps({"connect_enabled": True}).after_write("ja")
    assert read == ["ja"]


def test_a_backlog_read_that_fails_never_stops_the_run(monkeypatch):
    from app.cli import verbs

    def boom(loaded, lang):
        raise RuntimeError("Anki went away")
    monkeypatch.setattr(verbs, "_backlog_read", boom)
    monkeypatch.setattr(anki_session, "after_write", lambda settings, front: None)
    runner.Steps({"connect_enabled": True}).after_write("ja")
