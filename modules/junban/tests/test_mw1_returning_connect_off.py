# SPDX-License-Identifier: GPL-3.0-or-later
"""M-W1 (the lead's W-1 rule, carried over 2026-10-23: "with Connect off, a stone suspends cards that never come back").

On 3.0 the window's re-order host applies Junban's 順 actions after every Generate, Connect on or off
(`auto.decide_actions` keeps Junban's suspend setting while `junban_auto_actions` is on). So a stone — its episode's
only-words leaving the list — parks their cards with Connect off too; before this, only a run with Connect's preview on
brought a returning word's card back (`connect.unsuspends`), so un-marking the stone left them suspended for good.
Now an automatic job that applies the actions (`job.actions`) brings back what it parked, Connect on or off; a run you
start in 順 with Connect off stays 2.5's, byte for byte (`test_preview_gate.py`).

What a wrong answer would cost: a learner's cards suspended in Anki for ever after one mis-click and its Undo.

The scene (`connect_scene`): 老婆 is parked (suspended, `Surasura::later`) and on the list again.
"""
from modules.junban import auto, reposition, spaced, undo
from modules.junban.tests.connect_scene import ConnectCollection, scene, settings, without_connect
from modules.junban.tests.test_spaced_runs import ModCollection
from modules.junban.tests.test_reposition import _patched

RETURNING = "老婆"


def _host_job(fake, **over):
    """The window's re-order host's job with Connect off (`replan_preview.Host._write`): the settings decided as 順's
    automatic step decides them, an automatic spaced job applying them."""
    chosen = auto.decide_actions(settings(preview=False, **dict({"junban_auto_actions": True}, **over)))
    job = spaced.Job(automatic=True)
    job.actions = True
    with _patched(fake):
        return reposition.run(chosen, refresh=False, job=job)


def test_with_connect_off_the_hosts_job_brings_back_a_card_it_parked_and_restore_parks_it_again(tmp_path):
    fake = scene(tmp_path, without_connect())
    before = {c: (card["due"], card["queue"]) for c, card in fake.cards.items()}
    report = _host_job(fake)
    assert report["ok"], report["problems"]
    card = fake.card_of(RETURNING)
    assert card["queue"] == 0, "its word is back on the list: unsuspended, Connect off"
    assert ("unsuspend", [card["cardId"]]) in fake.suspend_calls
    assert "Back on your list: unsuspended 1 card" in report["message"]
    assert "Surasura::later" not in (fake.notes[card["note"]].get("tags") or []), "#50: the later tag comes off too"
    parked = sorted(c for c, cd in fake.cards.items() if cd["queue"] == -1)
    assert parked, "the same job still parks the cards whose words left the list: both directions, one rule"
    saved = undo.load("ja")
    assert saved["unsuspended"] == [card["cardId"]] and saved["suspended"] == parked
    with _patched(fake):
        restored = reposition.restore(settings(preview=False))
    assert restored["ok"], restored["problems"]
    assert {c: (cd["due"], cd["queue"]) for c, cd in fake.cards.items()} == before


def test_with_connect_off_and_the_suspend_setting_off_nothing_is_unsuspended(tmp_path):
    fake = scene(tmp_path, without_connect())
    _host_job(fake, junban_later_suspend=False)
    assert fake.card_of(RETURNING)["queue"] == -1
    assert not [call for call in fake.suspend_calls if call[0] == "unsuspend"]


def test_with_connect_off_a_positions_only_job_neither_parks_nor_brings_back(tmp_path):
    # `junban_auto_actions` off: the host writes positions only (`decide_actions`), so nothing it parks — and nothing
    # comes back on its own (a run you start in 順 decides)
    fake = scene(tmp_path, without_connect())
    _host_job(fake, junban_auto_actions=False)
    assert fake.suspend_calls == [] and fake.card_of(RETURNING)["queue"] == -1


def test_with_connect_off_a_run_you_start_in_junban_is_still_2_5s(tmp_path):
    fake = scene(tmp_path, without_connect())
    with _patched(fake):
        reposition.run(settings(preview=False))
    assert fake.card_of(RETURNING)["queue"] == -1


class _MapCollection(ConnectCollection, ModCollection):
    """The scene's collection with the mod-time reads a card map asks (`ModCollection`) and Connect's parked query."""


def test_with_connect_off_the_hosts_card_map_reads_the_parked_cards_beside_it_once_per_list(tmp_path):
    # the host keeps a card map between jobs (`reposition.CardMap`): the parked cards are read beside it, not by a
    # whole fresh read, and only by the first job of a list — a second job with the same list asks for none
    plain = scene(tmp_path, without_connect())
    fake = _MapCollection(list(plain.cards.values()), list(plain.notes.values()), actions=plain.actions)
    chosen = auto.decide_actions(settings(preview=False, junban_auto_actions=True))
    cards = reposition.CardMap()
    sent = []
    for _ in range(2):
        job = spaced.Job(automatic=True, actions=True, cards=cards)
        with _patched(fake):
            before = len(fake.requests)
            report = reposition.run(chosen, refresh=False, job=job)
        assert report["ok"], report["problems"]
        sent.append([r for r in fake.requests[before:] if r.get("action") == "findCards"
                     and " is:suspended " in f" {(r.get('params') or {}).get('query') or ''} "])
    assert [len(s) for s in sent] == [1, 0]
    assert fake.card_of(RETURNING)["queue"] == 0


# --- after review (M-W1 adversary #1–#3) -------------------------------------------------------------------------- #
import pytest  # noqa: E402

from modules.junban.tests.test_reposition import AnkiRefusal  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_parked_memo():
    reposition._PARKED_READ.clear()                 # the once-per-list look is process-wide
    yield
    reposition._PARKED_READ.clear()


def test_an_unsuspend_that_failed_is_tried_again_by_the_next_job_and_the_card_stays_junbans(tmp_path):
    # adversary #1 / #3: Anki closed mid-unsuspend. The look must not count as done, and Junban's record must still
    # call the card its own — else it stayed suspended for good
    fake = scene(tmp_path, without_connect())
    real = fake._suspend
    refused = []

    def once(action, card_ids):
        if action == "unsuspend" and not refused:
            refused.append(list(card_ids))
            return AnkiRefusal("Anki closed")
        return real(action, card_ids)
    fake._suspend = once
    _host_job(fake)
    assert refused and fake.card_of(RETURNING)["queue"] == -1
    report = _host_job(fake)
    assert report["ok"], report["problems"]
    assert fake.card_of(RETURNING)["queue"] == 0, (report["message"], fake.suspend_calls)


def test_a_pin_brings_a_parked_card_back_without_a_generate(tmp_path, monkeypatch):
    # adversary #2: *Study its cards first* returns an item's parked card whatever the list says; a pin re-plans with
    # no Generate (the list file unchanged), so the look follows the pins too
    from modules.junban import pins as pin_feed
    entries = [("冒険", "冒険が始まった。", 2000, [], 0),
               ("須藤", "須藤さんが来た。", 9000, ["Surasura::later"], -1)]
    fake = scene(tmp_path, entries)
    _host_job(fake)
    parked = fake.card_of("須藤")
    assert parked["queue"] == -1
    looks = []
    real_read = pin_feed.read
    monkeypatch.setattr(pin_feed, "read", lambda language: looks.append(language) or
                        ([(7, "Library/x/ep1.srt", "2026-10-23T15:00:00Z")], {7: [parked["note"]]}, {}, set()))
    report = _host_job(fake)
    assert report["ok"], report["problems"]
    assert looks and fake.card_of("須藤")["queue"] == 0, "the pinned item's parked card comes back"
    monkeypatch.setattr(pin_feed, "read", real_read)


def test_a_second_cut_adds_its_later_back_ids_to_the_first_cuts_for_the_same_tag(tmp_path):
    # a second cut's later-back ids for a tag the first cut already holds are merged with them, never replace
    # them — else the first cut's parked cards lose their way back and stay suspended for good
    payload = {"cards": {}, "later_back": {"Surasura::later": [11, 12]}}
    cut = {"cards": {}, "later_back": {"Surasura::later": [13]}}
    undo._take_over(payload, cut)
    assert payload["later_back"] == {"Surasura::later": [11, 12, 13]}


def test_a_second_cut_whose_later_back_ids_overlap_the_first_cuts_adds_each_id_once_in_order(tmp_path):
    # the merge is a union, not a concatenation — an id both cuts hold appears once, and the result is sorted
    # whatever order the second cut gives its ids in (a duplicate would be parked and restored twice)
    payload = {"cards": {}, "later_back": {"Surasura::later": [11, 12]}}
    cut = {"cards": {}, "later_back": {"Surasura::later": [13, 12]}}
    undo._take_over(payload, cut)
    assert payload["later_back"] == {"Surasura::later": [11, 12, 13]}


def test_a_parked_card_two_decks_both_find_is_listed_once(monkeypatch):
    # why: a parked card found in two decks is listed once: the second deck's find adds nothing new, so cardsInfo asks
    # for the card once and the rows hold it once
    calls = []
    monkeypatch.setattr(reposition.ankiconnect, "find_cards", lambda url, query: [1719000000001, 1719000000002])
    monkeypatch.setattr(reposition.ankiconnect, "cards_info",
                        lambda url, ids: calls.append(list(ids)) or [{"cardId": c, "queue": -1} for c in ids])
    rows = reposition._parked_rows("http://127.0.0.1:8765", ["Surasura", "Surasura::Book"], "Surasura::later", set())
    assert calls == [[1719000000001, 1719000000002]], "the card both decks find is asked for once"
    assert [row["cardId"] for row in rows] == [1719000000001, 1719000000002]
    assert all(row["parked"] for row in rows)
