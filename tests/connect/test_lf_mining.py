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
                                    runner.WRITER_BUSY, runner.ANKI_MINER_OPEN])
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
    # review A2: Anki Miner's window open, or the list in another language, hold every episode too
    for reason in (runner.ANKI_MINER_OPEN, runner.OTHER_LIST.format("Chinese")):
        assert runner.holds_every(reason), reason
    # review A1: one request failing while Anki answers is that episode's own wait (amber), never everyone's
    assert not runner.holds_every(runner.ANKI_SLOW)
    rec = {"languages": {"ja": {"jobs": [{"item": 1, "job": 1, "state": "waiting", "reason": runner.ANKI_SLOW}]}}}
    assert feed.build(rec, "ja").items[1].kind == feed.ANKI
    for reason in (runner.NO_VIDEO, runner.LIBRARY_BUSY, "", None):
        assert not runner.holds_every(reason), reason


# --- 26: closed only when the port refuses ------------------------------------------------------------------------- #
def test_with_anki_switched_off_for_the_run_it_is_never_asked(monkeypatch):
    # why: the suites and a developer's run never reach Anki: no look, the old words
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    monkeypatch.setattr(anki_session, "look", lambda url: pytest.fail("Anki was asked"))
    assert runner._anki_wait("http://127.0.0.1:8765").reason == runner.ANKI_CLOSED


@pytest.mark.parametrize("state, reason", [("closed", runner.ANKI_CLOSED), ("busy", anki_session.BUSY),
                                           ("open", runner.ANKI_SLOW), ("unusable", anki_session.UNUSABLE)])
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
def _anki(monkeypatch, open_now, calls=None, decks=()):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(power, "on_battery", lambda *a, **k: False)
    monkeypatch.setattr(anki_session, "look", lambda url: "open")
    monkeypatch.setattr(anki_connect, "reviewing", lambda url: False)

    def invoke(action, url, timeout=30, **params):
        if calls is not None:
            calls.append(action)
        if action == "deckNames":
            return list(decks)
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
    monkeypatch.setattr(verbs, "_backlog_read", lambda loaded, lang, after_cards=False: read.append((lang, after_cards)))
    monkeypatch.setattr(anki_session, "after_write", lambda settings, front: None)
    runner.Steps({"connect_enabled": True}).after_write("ja")
    assert read == [("ja", True)]


def test_the_read_after_cards_ignores_generates_switch(monkeypatch):
    # why (review A4): the footer's count is the window's, whatever "read the backlog on Generate" says
    from app import anki_connect, anki_sync
    from app.cli import verbs
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_connect, "probe", lambda url, **k: {"ok": True})
    synced = []
    monkeypatch.setattr(anki_sync, "sync_backlog", lambda lang, url, decks, fields: synced.append((lang, decks)))
    loaded = {"anki_backlog_on_generate": False, "anki_sync_decks": {"ja": ["日本語::アニメ"]}}
    verbs._backlog_read(loaded, "ja")
    assert synced == []
    verbs._backlog_read(loaded, "ja", after_cards=True)
    assert synced == [("ja", ["日本語::アニメ"])]


def test_a_backlog_read_that_fails_never_stops_the_run(monkeypatch):
    from app.cli import verbs

    def boom(loaded, lang):
        raise RuntimeError("Anki went away")
    monkeypatch.setattr(verbs, "_backlog_read", boom)
    monkeypatch.setattr(anki_session, "after_write", lambda settings, front: None)
    runner.Steps({"connect_enabled": True}).after_write("ja")


# --- 23b: a half-width katakana word is named as the tagger reads it ------------------------------------------- #
def test_a_half_width_katakana_word_is_named_full_width_and_keeps_its_line_spelling(tmp_path, monkeypatch):
    # why (found while timing, laptop round 5): a subtitle writing ﾗｲﾌﾞﾊｳｽ sent Anki Miner the half-width name; it
    # found the line by its own fold but asked the dictionary for ﾗｲﾌﾞﾊｳｽ: no definition, no card (12 of 50 words in
    # one episode). The front is the word as the tagger reads it (`analyzer.tagger_text`); `surface` the file's
    from app import cues
    from app.connect import pick, runfile
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path / "root"))
    sub = tmp_path / "ep01.ja.srt"
    sub.write_text("1\n00:00:01,000 --> 00:00:03,000\nﾗｲﾌﾞﾊｳｽ もうちょいだから｡\n\n"
                   "2\n00:00:04,000 --> 00:00:06,000\n結束ﾊﾞﾝﾄﾞだよ｡\n", encoding="utf-8")
    read = cues.read(str(sub), "ja")
    by_written = {t.written: t for t in cues.tokens(read, "ja")}
    assert pick.card_front(by_written["ﾗｲﾌﾞﾊｳｽ"]) == "ライブハウス"
    chosen = pick.pick(read, cues.tokens(read, "ja"), "ja", lambda key: False, mode="unknown")
    word = next(w for w in chosen["words"] if w["word"] == "ライブハウス")
    assert word["sent"][0] == "ライブハウス" and word["surface"] == "ﾗｲﾌﾞﾊｳｽ"
    entry = next(e for e in runfile.word_requests([word], [runfile.WORD_FROM_LINE]) if e["word"] == "ライブハウス")
    assert entry["surface"] == "ﾗｲﾌﾞﾊｳｽ", "the line's own spelling still goes with it"


def test_a_full_width_word_is_named_as_written():
    # why: the rule changes only what the tagger reads otherwise; a word written as the dictionary writes it is as was
    from app.connect import pick
    from types import SimpleNamespace
    token = SimpleNamespace(node=None, written="伯父さん", lemma="伯父さん", orth="伯父さん")
    assert pick.card_front(token) == "伯父さん"


class _OneRefused(FakeSteps):
    """Anki open, but episode 1's ordering request keeps failing (a heavy call timing out; review A1)."""

    def order(self, lang, job):
        if job is not None and job["item_id"] == 1:
            raise runner.Wait(runner.ANKI_SLOW, resume="ordering")
        return super().order(lang, job)


def test_one_episodes_failing_request_never_holds_the_others(tmp_path, ledger):
    # why (review A1): Anki answers, one request of episode 1 fails each time — 2 and 3 still mine
    plan = {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}}
    steps = _OneRefused(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert _mined(steps) == [1, 2, 3]
    states = {j["item_id"]: (j["state"], j["reason"]) for j in ledger.jobs("ja")}
    assert states[1] == ("waiting", runner.ANKI_SLOW) and states[2][0] == states[3][0] == "done"


def test_a_profile_without_your_decks_is_never_taken_as_connects(monkeypatch, tmp_path):
    # why (review A3): DevTest open by chance at Connect's first look would have been Connect's profile for good;
    # the profile setup read your decks from holds them — that one is recorded
    monkeypatch.setattr(setup, "record_path", lambda: str(tmp_path / "setup.json"))
    loaded = {"connect_enabled": True, "anki_sync_decks": {"ja": ["日本語::アニメ", "日本語::文"]}}
    _anki(monkeypatch, "DevTest", decks=["Default", "DevTest"])
    assert runner.Steps(loaded).blocked("ja") == anki_session.NO_PROFILE_DECKS
    assert setup.anki_profile() is None
    assert runner.holds_every(anki_session.NO_PROFILE_DECKS)
    _anki(monkeypatch, "日本語", decks=["Default", "日本語::アニメ", "日本語::文"])
    assert runner.Steps(loaded).blocked("ja") is None
    assert setup.anki_profile() == "日本語"


# --- 24b / M-3 (Sonic 2026-10-22, A): *Mine now* on battery is the yes for that one episode --------------------- #
def _asked(ledger, item):
    from app.connect.ledger import stamp
    with ledger.transaction():
        ledger.ask("ja", item, stamp(), store_id="store-1")


def test_on_battery_an_asked_episode_mines_and_the_rest_wait_for_the_plug(tmp_path, ledger):
    # why: the press is the learner's yes for that episode alone; the others never start unplugged
    plan = {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}, "blocked": runner.ON_BATTERY}
    steps = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)   # all wait, unasked
    _asked(ledger, 3)
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert _mined(steps) == [3]
    assert [e[1] for e in steps.log if e[0] == "pick"] == [3], "the unasked ones are never picked on battery"
    assert summary["languages"]["ja"]["waiting"] == {1: runner.ON_BATTERY, 2: runner.ON_BATTERY}


class _AnkiClosedToo(FakeSteps):
    def session_blocked(self, lang):
        return runner.ANKI_CLOSED


def test_an_asked_episode_on_battery_still_waits_for_anki(tmp_path, ledger):
    # why: the press overrides the battery, never Anki's own state: it goes first once Anki answers
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "blocked": runner.ON_BATTERY}
    runner.run({}, ["ja"], steps=FakeSteps(str(tmp_path), plan), ledger=ledger, sleep=lambda s: None, looks=1)
    _asked(ledger, 2)
    steps = _AnkiClosedToo(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert _mined(steps) == []
    assert summary["languages"]["ja"]["waiting"][2] == runner.ANKI_CLOSED


# --- 34: the plug back ends the pause at once ----------------------------------------------------------------- #
def test_the_plug_back_ends_the_pause_while_episodes_wait_on_battery(tmp_path, ledger):
    # why (row 34): the skipped episodes came back only at the next 2-minute look (or a restart); now within seconds
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "blocked": runner.ON_BATTERY}
    steps = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    steps.on_battery = lambda: False
    assert runner._plugged_in(steps, ledger, ["ja"]) is True
    steps.on_battery = lambda: True
    assert runner._plugged_in(steps, ledger, ["ja"]) is False


def test_no_battery_wait_never_ends_the_pause_early(tmp_path, ledger):
    # why: a wait on Anki keeps its 2-minute look: no early wake (no look every 5 s at a closed Anki)
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "blocked": runner.ANKI_CLOSED}
    steps = FakeSteps(str(tmp_path), plan)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    steps.on_battery = lambda: False
    assert runner._plugged_in(steps, ledger, ["ja"]) is False
    assert runner._plugged_in(FakeSteps(str(tmp_path), plan), ledger, ["ja"]) is False, "no power look: no wake"


def test_the_pause_ends_within_its_look_step_once_plugged_in(monkeypatch):
    # why: `_pause` asks every UPDATE_LOOK_S; the wake ends it at the first ask that finds the plug back
    import threading
    monkeypatch.setattr(runner, "UPDATE_LOOK_S", 0.01)
    asks = []
    woke = lambda: asks.append(1) or len(asks) >= 3  # noqa: E731
    assert runner._pause(120, None, threading.Event(), woke) is True
    assert len(asks) == 3


def test_a_request_anki_turns_down_is_needs_you_not_a_wait(monkeypatch):
    # why (review IK #3): a deck or note type gone answers `action`; retried every 2 minutes in silence before
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_session, "look", lambda url: pytest.fail("Anki answered: no look"))
    got = runner._anki_wait("http://127.0.0.1:8765", "mining", anki_connect.AnkiError("deck not found", kind="action"))
    assert isinstance(got, runner.Needs) and got.kind == "anki-refused"
    monkeypatch.setattr(anki_session, "look", lambda url: "closed")
    got = runner._anki_wait("http://127.0.0.1:8765", "mining", anki_connect.AnkiError("refused", kind="offline"))
    assert isinstance(got, runner.Wait) and got.reason == runner.ANKI_CLOSED


def test_an_episode_waiting_for_its_video_keeps_its_own_wait_when_all_wait(tmp_path, ledger):
    # why (review IK #5): unplugged, the episode with no video was relabelled "On battery"
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "videos": {"1": None}}
    runner.run({}, ["ja"], steps=FakeSteps(str(tmp_path), plan), ledger=ledger, sleep=lambda s: None, looks=1)
    plan = dict(plan, blocked=runner.ON_BATTERY)
    summary = runner.run({}, ["ja"], steps=FakeSteps(str(tmp_path), plan), ledger=ledger, sleep=lambda s: None,
                         looks=1)
    assert summary["languages"]["ja"]["waiting"][1] == runner.NO_VIDEO
    assert {j["item_id"]: j["reason"] for j in ledger.jobs("ja")}[1] == runner.NO_VIDEO
