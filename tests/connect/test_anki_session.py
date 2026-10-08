"""Connect's Anki session (P2.3 row 2.3.4; ✅ Q4-1, Q4-4, Q4-16; K102, K105) on the one sync rule
(`app/anki_sync_rule.py`, E3.1; E1.1 04 §3):

  - S1 eagerly, once per session, before Connect reads what you studied or writes Anki — and one session whoever
    starts it (the window's look, a verb, Connect); a new one after Anki was seen closed; never during a review;
  - your phone's reviews come in before the day's first re-order: a card you studied there is never written;
  - S3 after a write that changed tomorrow's cards, sent by `settle` before a headless process exits — never once Anki
    has closed (its own sync on close carried the order);
  - *Open Anki for me*: only at the window's start, on Connect's profile, never twice, and the window waits for it;
  - Connect's preview off, or Anki switched off for the run: nothing asked at all.

Anki is a fake AnkiConnect behind `urllib.request.urlopen` (in this process); the clock is a fake one.
"""
import json
import socket
import types
import urllib.error
from unittest import mock

import pytest

anki_sync_rule = pytest.importorskip("app.anki_sync_rule")      # E3.1's: until it is in 2.x-dev
from app.connect import anki_session, open_anki, setup

URL = "http://127.0.0.1:8765"
ON = {"connect_enabled": True, "anki_connect_url": URL, "anki_sync_delay_min": 1}


class FakeAnki:
    """What Connect's session asks of Anki: whether it's there, its profile, a review, a sync, a deck's options — and
    a few new cards, one of which you studied on your phone (AnkiWeb holds it until Anki syncs)."""

    def __init__(self):
        self.profile, self.reviewing, self.signed_in, self.fail = "日本語", False, True, False
        self.offline = self.slow = False
        self.actions, self.syncs, self.writes = [], 0, []
        # new cards (type 0) on this desktop; the phone studied 1002 this morning, not yet synced down
        self.cards = {1001: {"due": 1, "type": 0, "word": "散歩"}, 1002: {"due": 2, "type": 0, "word": "図書館"},
                      1003: {"due": 3, "type": 0, "word": "冒険"}}
        self.on_ankiweb = {1002: {"type": 1}}

    def answer(self, action, params):
        self.actions.append(action)
        if action == "requestPermission":
            return {"permission": "granted", "version": 6}, None
        if action == "version":
            return 6, None
        if action == "getActiveProfile":
            return self.profile, None
        if action == "guiReviewActive":
            return self.reviewing, None
        if action == "getDeckConfig":
            return {"new": {"perDay": 30}}, None
        if action == "sync":
            if not self.signed_in:
                return None, "sync: auth not configured"
            if self.fail:
                return None, "network error: AnkiWeb could not be reached"
            self.syncs += 1
            for card_id, change in self.on_ankiweb.items():      # the phone's reviews arrive
                self.cards[card_id].update(change)
            self.on_ankiweb = {}
            return None, None
        if action == "cardsInfo":
            return [dict(self.cards[i], cardId=i) for i in params["cards"]], None
        if action == "setSpecificValueOfCard":
            self.writes.append(params["card"])
            self.cards[params["card"]]["due"] = int(params["values"][0])
            return [True], None
        return None, f"unsupported action {action}"

    def __call__(self, request, timeout=None):
        if self.offline:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "No connection could be made"))
        if self.slow:
            raise urllib.error.URLError(socket.timeout("timed out"))
        payload = json.loads(request.data.decode("utf-8"))
        result, error = self.answer(payload["action"], payload.get("params") or {})
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"result": result, "error": error}).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response


class Clock:
    def __init__(self, at=1_800_000_000.0):
        self.at = at

    def time(self):
        return self.at

    def sleep(self, seconds):
        self.at += seconds


@pytest.fixture
def anki(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    fake = FakeAnki()
    with mock.patch("urllib.request.urlopen", fake):
        yield fake


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(anki_sync_rule, "time", types.SimpleNamespace(time=c.time, strftime=__import__("time").strftime,
                                                                      localtime=__import__("time").localtime))
    return c


def _reorder(fake, settings):
    """A stand-in for any writer with Connect on (Junban's own run is P2.3 row 2.3.5's): the session first, then
    positions written only for cards still new — as Junban writes."""
    from app import anki_connect
    anki_session.begin(URL, settings)
    with anki_connect.writer("a test re-order"):
        cards = anki_connect.invoke("cardsInfo", URL, cards=sorted(fake.cards))
        for position, card in enumerate(reversed(cards), start=1):
            if card["type"] == 0:
                anki_connect.invoke("setSpecificValueOfCard", URL, card=card["cardId"], keys=["due"],
                                    newValues=[str(position)], values=[str(position)])


# --------------------------------------------------------------------------- #
# S1: a session's start
# --------------------------------------------------------------------------- #
def test_a_session_syncs_once_whoever_starts_it(anki, clock):
    assert anki_session.begin(URL, ON) == "synced" and anki.syncs == 1
    assert anki_session.begin(URL, ON) is None, "inside a session nothing re-syncs (Q4-4)"
    assert anki_session.at_window(ON)["sync"] is None, "the window's look is the same session"
    assert anki.syncs == 1


def test_your_phones_reviews_come_in_before_the_days_first_reorder(anki, clock):
    # The ORDER proof: a card studied on the phone is no longer new once the session's sync ran, so no position is
    # written over it (a desktop write to it would win the next sync and lose the review)
    _reorder(anki, ON)
    assert anki.syncs == 1 and 1002 not in anki.writes and anki.writes, anki.writes
    assert anki.actions.index("sync") < anki.actions.index("cardsInfo"), "synced before Anki was read"


def test_without_connect_the_phones_card_would_be_written_over(anki, clock):
    # The control: with Connect's preview off nothing syncs, and 2.5's writer lands on the studied card
    _reorder(anki, dict(ON, connect_enabled=False))
    assert anki.syncs == 0 and 1002 in anki.writes


def test_a_new_session_after_anki_was_seen_closed(anki, clock):
    anki_session.begin(URL, ON)
    clock.at += 30
    anki.offline = True
    assert anki_session.look(URL) == "closed"
    anki.offline = False
    clock.at += 60
    assert anki_session.begin(URL, ON) == "synced" and anki.syncs == 2


def test_a_new_session_after_an_hour_without_a_surasura_write(anki, clock):
    anki_session.begin(URL, ON)
    clock.at += anki_sync_rule.SESSION_GAP_S + 1
    assert anki_session.begin(URL, ON) == "synced" and anki.syncs == 2


def test_busy_is_never_taken_for_closed(anki, clock):
    anki_session.begin(URL, ON)
    anki.slow = True
    assert anki_session.look(URL) == "busy"
    anki.slow = False
    assert anki_session.begin(URL, ON) is None and anki.syncs == 1, "no session restarted by a slow answer"


def test_never_during_a_review_and_the_session_waits_for_the_next_look(anki, clock):
    anki.reviewing = True
    assert anki_session.begin(URL, ON) is None and anki.syncs == 0
    anki.reviewing = False
    assert anki_session.begin(URL, ON) == "synced"


def test_not_signed_in_is_said_and_the_setup_check_names_it(anki, clock, monkeypatch):
    anki.signed_in = False
    assert anki_session.begin(URL, ON) == "not-signed-in" and anki.syncs == 0
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")            # the check reads the state, it doesn't ask Anki
    check = next(c for c in setup.checks(ON, "ja")["checks"] if c["id"] == "ankiweb")
    assert check["state"] == "needs-you" and not check["blocks"] and "sign in" in check["do"]


def test_a_failed_sync_is_tried_again_at_the_next_look_after_a_while(anki, clock):
    anki.fail = True
    assert anki_session.begin(URL, ON).startswith("failed")
    anki.fail = False
    assert anki_session.begin(URL, ON) is None, "not again at once (S1_RETRY_S)"
    clock.at += anki_sync_rule.S1_RETRY_S + 1
    assert anki_session.begin(URL, ON) == "synced"


def test_a_permission_prompt_or_a_strange_reply_is_never_taken_for_closed(anki, clock, monkeypatch):
    anki_session.begin(URL, ON)
    clock.at += 30
    real = anki.answer
    monkeypatch.setattr(anki, "answer", lambda action, params: ({"permission": "denied"}, None)
                        if action == "requestPermission" else real(action, params))
    assert anki_session.look(URL) == "unusable"
    assert anki_session.at_window(dict(ON, connect_open_anki=True), opening=True)["opened"] is False
    monkeypatch.setattr(anki, "answer", real)
    assert anki_session.begin(URL, ON) is None, "no new session: Anki was never seen closed"


def test_a_writer_holding_anki_leaves_the_session_due_for_the_next_look(anki, clock):
    from tests.test_cli_locks import Holder
    with Holder("anki-writer", "the 順 window"):
        assert anki_session.begin(URL, ON, wait=0.0) is None and anki.syncs == 0
    assert anki_session.begin(URL, ON) == "synced"


def test_a_delay_of_hours_never_keeps_a_process_alive(anki, clock):
    long = dict(ON, anki_sync_delay_min=24 * 60)
    anki_session.begin(URL, long)
    anki_session.after_write(long, True)
    start = clock.at
    assert anki_session.settle(URL, long, sleep=clock.sleep, clock=clock.time) is None and clock.at == start


@pytest.mark.parametrize("settings, env", [(dict(ON, connect_enabled=False), None), (ON, "1")])
def test_off_nothing_is_asked_at_all(anki, clock, monkeypatch, settings, env):
    if env:
        monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", env)
    assert anki_session.begin(URL, settings) is None
    assert anki_session.at_window(settings, opening=True) is None
    assert anki_session.after_write(settings, True) is None and anki_session.settle(URL, settings) is None
    assert anki_session.waiting(URL, settings) is None
    assert anki.actions == []


# --------------------------------------------------------------------------- #
# Waiting reasons (E1–E3)
# --------------------------------------------------------------------------- #
def test_waiting_names_the_one_reason(anki, clock):
    assert anki_session.waiting(URL, ON) is None
    anki.reviewing = True
    assert anki_session.waiting(URL, ON) == "Waiting while you review in Anki."
    anki.reviewing = False
    setup.write_record({"anki_profile": "日本語"})
    anki.profile = "DevTest"
    assert anki_session.waiting(URL, ON) == 'Waiting for Anki\'s profile "日本語": "DevTest" is open.'
    anki.slow = True
    assert anki_session.waiting(URL, ON) == "Waiting for Anki: it's busy."
    anki.slow, anki.offline = False, True
    assert anki_session.waiting(URL, ON) == "Waiting for Anki: it isn't open."


# --------------------------------------------------------------------------- #
# S3: after a write, and before a headless process exits
# --------------------------------------------------------------------------- #
def test_a_write_that_changed_tomorrows_cards_is_synced_before_the_process_exits(anki, clock):
    anki_session.begin(URL, ON)
    due = anki_session.after_write(ON, True)
    assert due == pytest.approx(clock.at + 60)
    assert anki_session.settle(URL, ON, sleep=clock.sleep, clock=clock.time) == "synced"
    assert anki.syncs == 2 and clock.at >= due


def test_a_write_lower_down_never_syncs(anki, clock):
    anki_session.begin(URL, ON)
    assert anki_session.after_write(ON, False) is None
    assert anki_session.settle(URL, ON, sleep=clock.sleep, clock=clock.time) is None and anki.syncs == 1


def test_anki_closed_before_the_sync_was_due_sends_nothing(anki, clock):
    anki_session.begin(URL, ON)
    anki_session.after_write(ON, True)

    def closes(seconds):
        clock.sleep(seconds)
        anki.offline = True                      # you closed Anki: its own sync on close carried the order (S2)
    assert anki_session.settle(URL, ON, sleep=closes, clock=clock.time) == "anki-closed" and anki.syncs == 1


def test_settle_never_waits_past_the_delay_and_its_margin(anki, clock, monkeypatch):
    anki_session.begin(URL, ON)
    anki_session.after_write(ON, True)
    start = clock.at
    monkeypatch.setattr(anki_sync_rule, "sync_if_due", lambda url, settings, cancel=None: (None, clock.at + 30))
    assert anki_session.settle(URL, ON, sleep=clock.sleep, clock=clock.time) is None
    assert clock.at - start <= 60 + anki_session.SETTLE_MARGIN_S + 5


def test_with_the_minute_off_only_the_sessions_sync_is_asked(anki, clock):
    off = dict(ON, anki_sync_delay_min="off")
    anki_session.begin(URL, off)
    assert anki_session.after_write(off, True) is None
    assert anki_session.settle(URL, off, sleep=clock.sleep, clock=clock.time) is None and anki.syncs == 1


def test_front_changed_reads_a_junban_runs_rows_as_the_replan_does():
    plan = pytest.importorskip("modules.junban.plan")

    def rows(order):
        """A dense run's rows, in its planned order: (card, its due before) -> new numbers from 100 up."""
        return [plan.Placement(position=100 + i, card_id=card, due=old, word="散歩", rank=i, deck="日本語",
                               changed=100 + i != old, note_id=None) for i, (card, old) in enumerate(order)]
    before = [(card, 100 + card) for card in range(20)] + [(50, 120), (51, 121)]
    # two cards past tomorrow's 20 swap places: lower down, no sync
    swapped = before[:20] + [(51, 121), (50, 120)]
    assert not anki_session.front_changed({"written": [50, 51], "stats": {"order": rows(swapped)}})
    # card 50 goes first: tomorrow's cards changed (and card 19 is pushed out of them)
    first = [(50, 120)] + before[:20] + [(51, 121)]
    assert anki_session.front_changed({"written": [50] + list(range(20)), "stats": {"order": rows(first)}})
    assert anki_session.front_changed({"written": [19], "stats": {"order": rows(first)}}), "pushed out counts"
    assert not anki_session.front_changed({"written": [], "stats": {"order": rows(first)}}), "nothing written"
    # the deck's New cards/day widens tomorrow: places 25 and 26 are tomorrow's with 30 a day
    wide = [(card, 100 + card) for card in range(30)]
    wide[24], wide[25] = wide[25], wide[24]
    assert not anki_session.front_changed({"written": [24, 25], "stats": {"order": rows(wide)}})
    assert anki_session.front_changed({"written": [24, 25], "stats": {"order": rows(wide)}}, per_day=30)


def test_per_day_is_read_from_the_decks_own_options(anki):
    assert anki_session.per_day(URL, "日本語::Mining") == 30
    anki.offline = True
    assert anki_session.per_day(URL, "日本語::Mining") is None


# --------------------------------------------------------------------------- #
# Open Anki for me: only at the window's start
# --------------------------------------------------------------------------- #
@pytest.fixture
def starts(monkeypatch):
    seen = []

    def start(profile=None):
        seen.append(profile)
        return "started"
    monkeypatch.setattr(open_anki, "start", start)
    monkeypatch.setattr(open_anki, "running", lambda: False)
    return seen


def test_open_anki_for_me_opens_anki_at_the_windows_start_on_connects_profile(anki, clock, starts):
    setup.write_record({"anki_profile": "日本語"})
    anki.offline = True
    lines = []
    sleeps = iter([False, False, True])           # Anki answers on the third look

    def sleep(seconds):
        clock.sleep(seconds)
        anki.offline = not next(sleeps)
    done = anki_session.at_window(dict(ON, connect_open_anki=True), opening=True, say=lines.append, sleep=sleep,
                                  clock=clock.time)
    assert starts == ["日本語"] and done == {"anki": "open", "opened": True, "sync": "synced"}
    assert lines == ["Opening Anki for you (Open Anki for me)…"] and anki.syncs == 1


def test_open_anki_for_me_never_opens_anki_on_a_focus_or_when_off(anki, clock, starts):
    anki.offline = True
    assert anki_session.at_window(dict(ON, connect_open_anki=True), opening=False)["opened"] is False
    assert anki_session.at_window(ON, opening=True)["opened"] is False
    assert starts == []


def test_open_anki_for_me_never_starts_a_second_anki(anki, clock, starts, monkeypatch):
    anki.offline = True                                       # Anki starting, or open without AnkiConnect
    monkeypatch.setattr(open_anki, "running", lambda: True)
    done = anki_session.at_window(dict(ON, connect_open_anki=True), opening=True)
    assert starts == [] and done["opened"] is False and done["anki"] == "closed"


def test_anki_that_never_answers_is_waited_for_two_minutes_then_left(anki, clock, starts):
    anki.offline = True
    start = clock.at
    done = anki_session.at_window(dict(ON, connect_open_anki=True), opening=True, sleep=clock.sleep,
                                  clock=clock.time)
    assert done == {"anki": "closed", "opened": True, "sync": None}
    assert anki_session.OPENING_WAIT_S <= clock.at - start <= anki_session.OPENING_WAIT_S + anki_session.OPENING_EVERY_S
