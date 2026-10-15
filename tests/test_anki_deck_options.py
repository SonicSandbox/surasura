"""Settings' *New cards a day* (G1.2-5; K84): `app/anki_deck_options.py` — Anki's value read, and written only on the
user's confirmed click — against a patched `urlopen`, never a live Anki.

What a wrong answer would cost, in order:
  * a deck option changed that the user never confirmed: anything of the options group beside `new.perDay`, a value
    that moved in Anki since the user saw it, a write sent without the Anki-write lock or from anywhere but this one
    function (`saveDeckConfig` is refused everywhere else, `multi` included);
  * a write that races another writer: the lock is taken before the read the write is planned from, and let go after
    the read-back, on every path;
  * a row that lies: a failed or unconfirmed write reported as done, Anki closed or a missing deck shown as a number.
"""
import copy
import json
import os
import re
import threading
import urllib.error
from unittest import mock

import pytest

from app import anki_connect, anki_deck_options as options, locks
from app.anki_deck_options import Outcome, Reading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = anki_connect.DEFAULT_URL

# A real options group as AnkiConnect's getDeckConfig sends it (Anki 2.1.66; the reference collection's "Default"),
# nested keys and all: the write must send every one of them back unchanged.
GROUP = {
    "id": 1, "mod": 1789711432, "name": "Default", "usn": -1, "maxTaken": 60, "autoplay": True, "timer": 0,
    "replayq": True, "dyn": False, "newMix": 0, "newPerDayMinimum": 0, "interdayLearningMix": 0,
    "reviewOrder": 0, "newSortOrder": 0, "newGatherPriority": 0, "buryInterdayLearning": False,
    "fsrsWeights": [0.4, 0.6, 2.4, 5.8, 4.93, 0.94, 0.86, 0.01, 1.49, 0.14, 0.94, 2.18, 0.05, 0.34, 1.26, 0.29, 2.61],
    "desiredRetention": 0.9, "ignoreRevlogsBeforeDate": "", "stopTimerOnAnswer": False, "secondsToShowQuestion": 0.0,
    "secondsToShowAnswer": 0.0, "answerAction": 0, "waitForAudio": True, "sm2Retention": 0.9, "weightSearch": "",
    "new": {"bury": False, "delays": [1.0, 10.0], "initialFactor": 2500, "ints": [1, 4, 0], "order": 1,
            "perDay": 20},
    "rev": {"bury": False, "ease4": 1.3, "ivlFct": 1.0, "maxIvl": 36500, "perDay": 200, "hardFactor": 1.2},
    "lapse": {"delays": [10.0], "leechAction": 1, "leechFails": 8, "minInt": 1, "mult": 0.0},
}

DECK = "TheBank"
JA_DECK = "日本語::アニメ「ぼっち・ざ・ろっく！」"     # a real-shaped nested deck name: ::, kana, kanji, brackets


class FakeAnki:
    """A patched `urlopen` holding one options group per deck. Records each request with whether the calling thread
    held the Anki-write lock then. `getDeckConfig` answers the group (False for a deck it lacks); `saveDeckConfig`
    stores what it was sent unless `ignore_save`; `save_reply` overrides its answer; `per_day_moves_to` changes the
    value in Anki just before the second read (the user editing Anki meanwhile)."""

    def __init__(self, decks=(DECK,), group=None, offline=False):
        self.groups = {deck: copy.deepcopy(group or GROUP) for deck in decks}
        self.requests = []
        self.offline = offline
        self.offline_on = None
        self.ignore_save = False
        self.save_reply = None

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        action, params = payload["action"], payload.get("params") or {}
        self.requests.append((action, params, locks.held_here(anki_connect.WRITER_LOCK)))
        if self.offline or action == self.offline_on:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        if action == "getDeckConfig":
            result = copy.deepcopy(self.groups.get(params.get("deck"), False))
        elif action == "saveDeckConfig":
            result = True if self.save_reply is None else self.save_reply
            if result is True and not self.ignore_save:
                for deck, group in self.groups.items():
                    if group["id"] == params["config"]["id"]:
                        self.groups[deck] = copy.deepcopy(params["config"])
        elif action == "guiReviewActive":
            result = False
        else:
            result = None
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"result": result, "error": None}, ensure_ascii=False).encode("utf-8")
        return response

    @property
    def actions(self):
        return [action for action, _params, _held in self.requests]

    def saved(self):
        return [params["config"] for action, params, _held in self.requests if action == "saveDeckConfig"]


@pytest.fixture
def anki():
    fake = FakeAnki()
    with mock.patch("urllib.request.urlopen", fake):
        yield fake


def _holder(verb="Backfill"):
    """Another thread holding the Anki-write lock until the returned Event is set."""
    taken, done = threading.Event(), threading.Event()

    def hold():
        with anki_connect.writer(verb):
            taken.set()
            done.wait(10)
    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert taken.wait(5)
    return done, thread


# --- which deck --------------------------------------------------------------------------------------- #
def test_the_row_means_junbans_deck_only_while_its_scope_is_one_deck():
    assert options.deck_for({"junban_deck": f"  {JA_DECK} ", "junban_scope": "deck"}) == JA_DECK
    assert options.deck_for({"junban_deck": DECK}) == DECK                     # the scope's default is one deck
    assert options.deck_for({"junban_deck": DECK, "junban_scope": "all"}) == ""   # every deck: no one value
    assert options.deck_for({}) == "" and options.deck_for(None) == ""


# --- the read ----------------------------------------------------------------------------------------- #
def test_a_read_is_one_getdeckconfig_and_names_the_value_the_deck_and_its_group(anki):
    reading = options.read_new_per_day({}, DECK)
    assert reading == Reading(20, DECK, "Default", None)
    assert anki.requests == [("getDeckConfig", {"deck": DECK}, False)], "one read, no lock: it changes nothing"


def test_a_japanese_deck_name_reaches_anki_as_written():
    anki = FakeAnki(decks=(JA_DECK,))
    with mock.patch("urllib.request.urlopen", anki):
        assert options.read_new_per_day({}, JA_DECK).deck == JA_DECK
    assert anki.requests[0][1] == {"deck": JA_DECK}


def test_anki_closed_reads_as_a_plain_reason_not_a_number():
    with mock.patch("urllib.request.urlopen", FakeAnki(offline=True)):
        reading = options.read_new_per_day({}, DECK)
    assert isinstance(reading, str) and "Anki isn't open" in reading
    assert options.row_number({"words_per_day": 12}, reading) == 12, "the row falls back to the report's pace"


def test_a_deck_anki_does_not_have_is_named(anki):
    reading = options.read_new_per_day({}, "Migaku Reference")
    assert reading == "Anki has no deck named “Migaku Reference”."


def test_no_deck_asks_nothing(anki):
    assert "Choose Junban's deck" in options.read_new_per_day({}, "  ")
    assert anki.requests == []


def test_an_address_off_this_computer_is_never_asked(anki):
    reading = options.read_new_per_day({"anki_connect_url": "http://192.168.1.20:8765"}, DECK)
    assert isinstance(reading, str) and "isn't on this computer" in reading
    assert anki.requests == []


@pytest.mark.parametrize("per_day", [None, "20", True, -1, 10000])
def test_a_group_without_a_usable_value_is_a_reason(per_day):
    group = copy.deepcopy(GROUP)
    group["new"]["perDay"] = per_day
    with mock.patch("urllib.request.urlopen", FakeAnki(group=group)):
        reading = options.read_new_per_day({}, DECK)
    assert reading == f"Anki's options for “{DECK}” have no New cards a day."


# --- the confirmation and words_per_day -------------------------------------------------------------- #
def test_the_confirmation_names_the_deck_the_change_and_that_the_group_changes_for_every_deck():
    text = options.confirmation(Reading(20, JA_DECK, "Default", None), 30)
    assert f"“{JA_DECK}”" in text and "from 20 to 30" in text
    assert "“Default”" in text and "every deck using that group changes too" in text
    assert "3 decks use the options group “Default”: all of them change." in \
        options.confirmation(Reading(20, DECK, "Default", 3), 30)
    assert "group" not in options.confirmation(Reading(20, DECK, "Default", 1), 30), "its own group: nothing to say"


def test_the_row_shows_ankis_number_when_read_else_words_per_day():
    assert options.row_number({"words_per_day": 12}, Reading(25, DECK, "Default", None)) == 25
    assert options.row_number({"words_per_day": 12}, "Anki isn't open") == 12
    assert options.row_number({}, "Anki isn't open") == 5                      # settings_manager's default
    assert options.row_number({"words_per_day": True}, "x") == 5               # a hand edit that isn't a number


def test_words_per_day_follows_only_a_confirmed_change_to_a_number_the_report_can_use():
    assert options.words_per_day_after({"words_per_day": 5}, Outcome(True, "", 30, False)) == {"words_per_day": 30}
    assert options.words_per_day_after({"words_per_day": 30}, Outcome(True, "", 30, False)) == {}
    assert options.words_per_day_after({"words_per_day": 5}, Outcome(False, "", 30, False)) == {}
    assert options.words_per_day_after({"words_per_day": 5}, Outcome(True, "", 0, False)) == {}, \
        "0 (Anki paused) would read as the report's default 5"
    assert options.words_per_day_after({"words_per_day": 5}, Outcome(True, "", None, False)) == {}
    assert options.words_per_day_after({"words_per_day": 5}, "Anki isn't open") == {}


# --- the write ---------------------------------------------------------------------------------------- #
def test_the_write_holds_the_lock_from_its_read_to_its_read_back_and_lets_go_after(anki):
    outcome = options.write_new_per_day({}, DECK, 30, 20)
    assert outcome == Outcome(True, f"New cards a day for “{DECK}” is now 30 in Anki.", 30, False)
    assert anki.actions == ["getDeckConfig", "saveDeckConfig", "getDeckConfig"]
    assert all(held for _action, _params, held in anki.requests), "every request sent holding the lock"
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None, "let go after"
    assert anki.groups[DECK]["new"]["perDay"] == 30


def test_the_write_changes_new_per_day_and_nothing_else_of_the_group(anki):
    options.write_new_per_day({}, DECK, 35, 20)
    wanted = copy.deepcopy(GROUP)
    wanted["new"]["perDay"] = 35
    assert anki.saved() == [wanted], "the whole group compared: one key moved"


def test_a_value_that_moved_in_anki_since_it_was_read_is_never_written_over(anki):
    anki.groups[DECK]["new"]["perDay"] = 25                    # the user changed it in Anki after the row read 20
    outcome = options.write_new_per_day({}, DECK, 30, 20)
    assert not outcome.ok and outcome.value == 25 and "changed since it was read" in outcome.message
    assert "saveDeckConfig" not in anki.actions
    assert anki.requests[0][2] is True, "the read the refusal is decided from was made holding the lock"
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None


def test_the_value_anki_already_holds_is_not_written_again(anki):
    outcome = options.write_new_per_day({}, DECK, 20, 20)
    assert outcome.ok and outcome.value == 20 and "already 20" in outcome.message
    assert anki.actions == ["getDeckConfig"]


@pytest.mark.parametrize("value", [-1, 10000, True, "30", 30.0, None])
def test_a_value_anki_would_not_take_is_refused_before_the_lock_or_a_request(anki, value):
    with mock.patch.object(anki_connect, "take_writer") as take:
        outcome = options.write_new_per_day({}, DECK, value, 20)
    assert not outcome.ok and "whole number from 0 to 9999" in outcome.message
    take.assert_not_called()
    assert anki.requests == []


def test_the_bounds_anki_takes_are_written(anki):
    assert options.write_new_per_day({}, DECK, 0, 20).ok
    assert options.write_new_per_day({}, DECK, 9999, 0).ok
    assert anki.groups[DECK]["new"]["perDay"] == 9999


def test_no_deck_writes_nothing(anki):
    outcome = options.write_new_per_day({}, "", 30, 20)
    assert not outcome.ok and anki.requests == []


def test_a_deck_gone_by_the_write_is_refused(anki):
    outcome = options.write_new_per_day({}, "Default", 30, 20)
    assert not outcome.ok and "no deck named “Default”" in outcome.message
    assert anki.actions == ["getDeckConfig"]


def test_a_save_anki_refuses_is_not_reported_as_done(anki):
    anki.save_reply = False                                   # AnkiConnect's bare false: no group with that id
    outcome = options.write_new_per_day({}, DECK, 30, 20)
    assert not outcome.ok and "didn't save" in outcome.message and outcome.value == 20
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None


def test_a_read_back_that_disagrees_is_not_reported_as_done(anki):
    anki.ignore_save = True                                   # Anki answered true but kept 20
    outcome = options.write_new_per_day({}, DECK, 30, 20)
    assert not outcome.ok and outcome.value == 20 and "now says 20" in outcome.message
    assert anki.actions == ["getDeckConfig", "saveDeckConfig", "getDeckConfig"]


def test_anki_closing_mid_write_says_to_look_and_lets_go_of_the_lock(anki):
    anki.offline_on = "saveDeckConfig"
    outcome = options.write_new_per_day({}, DECK, 30, 20)
    assert not outcome.ok and outcome.value is None and "stopped answering" in outcome.message
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None


def test_anki_closed_before_the_write_changes_nothing():
    anki = FakeAnki(offline=True)
    with mock.patch("urllib.request.urlopen", anki):
        outcome = options.write_new_per_day({}, DECK, 30, 20)
    assert not outcome.ok and "Anki isn't open" in outcome.message and "Nothing was changed" in outcome.message
    assert "saveDeckConfig" not in anki.actions


# --- the lock held elsewhere -------------------------------------------------------------------------- #
def test_a_held_lock_with_no_wait_names_the_writer_and_writes_nothing(anki):
    done, thread = _holder("Backfill")
    try:
        outcome = options.write_new_per_day({}, DECK, 30, 20)
    finally:
        done.set()
        thread.join(5)
    assert outcome.busy and not outcome.ok and outcome.message.startswith("Backfill is writing to Anki")
    assert anki.requests == []


def test_a_waiting_write_says_so_and_a_cancel_stops_it_before_anything_is_sent(anki):
    done, thread = _holder("順 reorder")
    cancel, waiting, lines, result = threading.Event(), threading.Event(), [], []

    def on_wait(holder):
        lines.append(anki_connect.waiting_line(holder))
        waiting.set()

    worker = threading.Thread(target=lambda: result.append(
        options.write_new_per_day({}, DECK, 30, 20, wait=None, cancel=cancel, on_wait=on_wait)), daemon=True)
    worker.start()
    try:
        assert waiting.wait(5), "on_wait is called once waiting starts"
        cancel.set()
        worker.join(5)
    finally:
        done.set()
        thread.join(5)
    assert lines == ["Waiting for 順 reorder to finish writing to Anki…"]
    assert result == [Outcome(False, "Stopped before writing anything.", None, True)]
    assert anki.requests == []


def test_a_waiting_write_goes_on_once_the_other_writer_lets_go(anki):
    done, thread = _holder("Backfill")
    waiting, result = threading.Event(), []
    worker = threading.Thread(target=lambda: result.append(options.write_new_per_day(
        {}, DECK, 30, 20, wait=None, cancel=threading.Event(), on_wait=lambda _h: waiting.set())), daemon=True)
    worker.start()
    assert waiting.wait(5)
    done.set()
    thread.join(5)
    worker.join(10)
    assert result and result[0].ok and result[0].value == 30
    assert anki.actions == ["guiReviewActive", "getDeckConfig", "saveDeckConfig", "getDeckConfig"], \
        "after a wait it checks the user isn't reviewing, then reads again"


# --- the one door ------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("action", sorted(anki_connect.DECK_OPTION_ACTIONS))
def test_invoke_refuses_every_deck_options_write_even_holding_the_lock(anki, action):
    with anki_connect.writer("test"):
        with pytest.raises(anki_connect.AnkiError) as caught:
            anki_connect.invoke(action, URL, config=GROUP)
        assert caught.value.kind == "refused"
        with pytest.raises(anki_connect.AnkiError) as caught:
            anki_connect.multi([{"action": "getDeckConfig", "params": {"deck": DECK}},
                                {"action": action, "params": {"config": GROUP}}], URL)
        assert caught.value.kind == "refused"
    assert anki.requests == []


def test_save_deck_config_without_the_lock_is_refused_before_a_socket_opens(anki):
    with pytest.raises(anki_connect.AnkiError) as caught:
        anki_connect.save_deck_config(URL, GROUP)
    assert caught.value.kind == "refused"
    with anki_connect.writer("test"):
        with pytest.raises(anki_connect.AnkiError) as caught:
            anki_connect.save_deck_config("http://192.168.1.20:8765", GROUP)
    assert caught.value.kind == "refused"
    assert anki.requests == []


def test_the_other_writes_still_need_the_lock_and_reads_still_go(anki):
    with pytest.raises(anki_connect.AnkiError) as caught:
        anki_connect.invoke("setSpecificValueOfCard", URL, card=1789712080047, keys=["due"], newValues=[2944])
    assert caught.value.kind == "refused"
    assert anki_connect.invoke("getDeckConfig", URL, deck=DECK)["new"]["perDay"] == 20
    assert "getDeckConfig" in anki_connect.READ_ACTIONS and "saveDeckConfig" not in anki_connect.READ_ACTIONS


def _sources():
    """Every Python file of the app and its modules, tests left out."""
    for top in ("app", "modules", "app_entry.py"):
        path = os.path.join(PROJECT_ROOT, top)
        if os.path.isfile(path):
            yield path
            continue
        for dirpath, dirs, names in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in names:
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def test_savedeckconfig_is_sent_only_through_the_one_door_by_the_one_caller():
    """G1.2-5's one caller: the action's name is spelled only in anki_connect, and its door is called only here."""
    named, callers = [], []
    for path in _sources():
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        rel = os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")
        if '"saveDeckConfig"' in text or "'saveDeckConfig'" in text:
            named.append(rel)
        if re.search(r"(?<![\w`])save_deck_config\(", text.replace("def save_deck_config(", "")):
            callers.append(rel)
    assert named == ["app/anki_connect.py"]
    assert callers == ["app/anki_deck_options.py"]
