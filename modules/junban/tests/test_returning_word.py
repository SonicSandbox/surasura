# SPDX-License-Identifier: GPL-3.0-or-later
"""A returning word's card is unsuspended (P1.4 row 1.4.4; MR-R3: "When a level change lists a word again, unsuspend its
parked card" — "Yes").

A card Junban parked (suspended, with its `Surasura::later` tag) whose word is on the list again comes back: it is
unsuspended and placed with the list. G1.3-8 (Sonic: "just reorder for this version but for 3.0 it should suspend if
you have that in settings for junban"):

  * 2.6 / 2.7: only in a run you start in 順, while the Connect preview is on. An unattended run (Connect's step,
    `junban --auto`) neither suspends nor unsuspends anything;
  * 3.0 (`connect.UNATTENDED_SUSPEND`): unattended too, when Junban's suspend setting is on — recorded in that run's
    own snapshot, and put back by its restore.

The scene (`connect_scene`): 老婆 is parked and on the list again (file 3 of the journey).
"""
import pytest

from modules.junban import auto, connect, reposition, spaced, undo
from modules.junban.tests.connect_scene import scene, settings, without_connect
from modules.junban.tests.test_reposition import _patched

RETURNING = "老婆"


def test_a_run_you_start_in_junban_unsuspends_it_and_places_it_with_the_list(tmp_path):
    fake = scene(tmp_path, without_connect())       # no card of Connect's yet: nothing is "yours", the list decides
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    card = fake.card_of(RETURNING)
    assert card["queue"] == 0
    assert ("unsuspend", [card["cardId"]]) in fake.suspend_calls
    assert "Back on your list: unsuspended 1 card" in report["message"]
    # With the list: behind 冒険 and 散歩 (file 1), ahead of every card placed by its sentence.
    assert fake.queue_order()[:3] == ["冒険", "散歩", RETURNING]
    # The window's Restore sets it aside again — and puts every position back.
    with _patched(fake):
        restored = reposition.restore(settings())
    assert restored["ok"], restored["problems"]
    assert fake.card_of(RETURNING)["queue"] == -1
    assert "aside again" in restored["message"]


def test_a_parked_card_still_not_on_the_list_stays_parked(tmp_path):
    entries = [("冒険", "冒険が始まった。", 2000, [], 0),
               ("須藤", "須藤さんが来た。", 9000, ["Surasura::later"], -1)]
    fake = scene(tmp_path, entries)
    with _patched(fake):
        reposition.run(settings())
    assert fake.card_of("須藤")["queue"] == -1
    assert not [call for call in fake.suspend_calls if call[0] == "unsuspend"]


def test_a_card_you_suspended_yourself_is_never_unsuspended(tmp_path):
    """Junban parks only with its tag on; a suspended card without it is yours to keep suspended ("All suspended cards
    are intentional", K39)."""
    entries = [("冒険", "冒険が始まった。", 2000, [], 0), (RETURNING, "老婆が笑った。", 7000, [], -1)]
    fake = scene(tmp_path, entries)
    with _patched(fake):
        reposition.run(settings())
    assert fake.card_of(RETURNING)["queue"] == -1


def test_with_only_the_tag_on_a_tagged_card_you_suspended_yourself_stays_suspended(tmp_path):
    """With Junban's suspend setting off, its `::later` tag marks cards it only tagged: one you then suspended by hand
    is yours to keep suspended, even with its word back on the list (review P1.4-adversary #3)."""
    entries = [("冒険", "冒険が始まった。", 2000, [], 0),
               (RETURNING, "老婆が笑った。", 7000, ["Surasura::later"], -1)]
    fake = scene(tmp_path, entries)
    with _patched(fake):
        reposition.run(settings(junban_later_suspend=False))
    assert fake.card_of(RETURNING)["queue"] == -1
    assert not [call for call in fake.suspend_calls if call[0] == "unsuspend"]


def test_unattended_in_2_x_it_neither_suspends_nor_unsuspends(tmp_path, monkeypatch):
    """G1.3-8: Connect's step and `junban --auto` only reorder in 2.6 / 2.7 — even with Junban's suspend setting on,
    and not even the question is asked of Anki. (Held here with the 3.0 line's flag off.)"""
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", False)
    fake = scene(tmp_path)
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(settings(), list_current=True, positions_only=True, run_id=run_id)
    assert done["outcome"] == "ran"
    assert fake.suspend_calls == [] and fake.card_of(RETURNING)["queue"] == -1
    assert not any("is:suspended" in r.get("params", {}).get("query", "") and "-is:suspended" not in
                   r.get("params", {}).get("query", "") for r in fake.requests)
    assert fake.tag_calls == [] and fake.flag_writes == []


@pytest.fixture
def three_oh(monkeypatch):
    """The 3.0 line: an unattended run follows Junban's suspend setting (G1.3-8)."""
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", True)


def test_from_3_0_an_unattended_spaced_run_suspends_and_unsuspends_as_the_setting_says_and_its_restore_undoes_both(
        tmp_path, three_oh):
    # 2.x-dev keeps this with `job=None` (2.5's dense run:
    #   test_from_3_0_an_unattended_run_suspends_and_unsuspends_as_the_setting_says_and_its_restore_undoes_both);
    # 3.0 (W3.5 row 7, Haya's G2b): the unattended run — `junban --auto`, Connect's step — is a spaced job, and the one
    # `auto.reorder` hands in carries the actions it decided: Junban's suspend setting followed, the returning word's
    # card unsuspended, both in the run's own snapshot and undone by its restore
    fake = scene(tmp_path)
    before = {c: (card["due"], card["queue"]) for c, card in fake.cards.items()}
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(settings(), list_current=True, positions_only=True, run_id=run_id,
                            job=spaced.Job(automatic=True))
    assert done["outcome"] == "ran", done
    assert done["report"]["numbering"]["kind"] == spaced.FULL
    assert fake.card_of(RETURNING)["queue"] == 0
    parked_now = sorted(c for c, card in fake.cards.items() if card["queue"] == -1)
    # Every card not on the list in any form — Connect's 眼鏡 too — but never yours (走る).
    assert [fake.notes[fake.cards[c]["note"]]["fields"]["Expression"]["value"] for c in parked_now] == \
        ["須藤", "図書館", "眼鏡"]
    assert fake.card_of("走る")["queue"] == 0, "your own card is never suspended"
    assert fake.flag_writes == [], "positions and the suspend setting only: no flag"
    saved = undo.load("ja", run_id=run_id)
    assert saved["suspended"] == parked_now and saved["unsuspended"] == [fake.card_of(RETURNING)["cardId"]]

    with _patched(fake):
        report = reposition.restore_run(settings(), run_id)
    assert report["ok"], report["problems"]
    assert {c: (card["due"], card["queue"]) for c, card in fake.cards.items()} == before
    assert all("Surasura::later" not in (fake.notes[fake.cards[c]["note"]].get("tags") or []) for c in parked_now)


def test_from_3_0_with_the_suspend_setting_off_an_unattended_run_still_only_reorders(tmp_path, three_oh):
    fake = scene(tmp_path)
    with _patched(fake):
        auto.reorder(settings(junban_later_suspend=False), list_current=True, positions_only=True,
                     run_id=undo.new_run_id("reorder"))
    assert fake.suspend_calls == [] and fake.card_of(RETURNING)["queue"] == -1


def test_with_the_preview_off_a_parked_card_is_left_as_in_2_5(tmp_path):
    fake = scene(tmp_path)
    with _patched(fake):
        reposition.run(settings(preview=False))
    assert fake.card_of(RETURNING)["queue"] == -1
    assert not [call for call in fake.suspend_calls if call[0] == "unsuspend"]
