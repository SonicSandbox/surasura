# SPDX-License-Identifier: GPL-3.0-or-later
"""Every Junban run puts a pinned item's cards first — on the 3.0 line only (P2.2 row 2.2.4; E1.1 03 §8, ✅ E1.3-2/-3).

Through `reposition` itself, on the fake collection Junban's suites share (`connect_scene`): the pin is read once per
run in `_plan_scope`, so the 順 window's preview and Reorder, the automatic reorder and Connect's step all see it.
In 2.x (`connect.PINS` False) nothing is read and the run is the run it was. A pinned card is never tagged, flagged or
suspended as "not on your list"; one Junban itself parked comes back first (E1.3-2). Real words; never Anki.
"""
import pytest

from modules.junban import connect, pins, reposition
from modules.junban.tests.connect_scene import scene, settings, without_connect
from modules.junban.tests.test_reposition import _patched

VIDEO = "D:\\動画\\星の旅人\\星の旅人 - 05.mkv"
SOURCE = "星の旅人 — 星の旅人 - 05 @ 00:04:31"
PINNED = ([(7, "Hato/星の旅人 - 05.ja.ass", "2026-10-07T10:00:00Z")], {7: []}, {7: VIDEO})


def _mined_from_the_show(fake, *words):
    """The cards Anki Miner made by hand from the pinned episode: their `MiscInfo` names it."""
    for word in words:
        fake.notes[fake.card_of(word)["note"]]["fields"]["MiscInfo"]["value"] = SOURCE


@pytest.fixture
def three_oh(monkeypatch):
    """The 3.0 line: pins are read, and the store holds one (item 7, its video paired)."""
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: PINNED)


def test_a_pinned_shows_cards_go_first_and_are_never_not_on_your_list(tmp_path, three_oh):
    """須藤 and 図書館 aren't on the list: unpinned, the window's run would tag, flag and suspend them; pinned, they go
    first (in Junban's own order) and are left alone by every "not on your list" action."""
    fake = scene(tmp_path, without_connect())
    _mined_from_the_show(fake, "須藤", "図書館")
    with _patched(fake):
        writes, stats = reposition.dry_run(settings())
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    assert stats["pinned"] == 2
    assert {row.word for row in stats["order"][:2]} == {"須藤", "図書館"}
    assert [row.pinned for row in stats["order"][:3]] == [0, 0, None]
    assert fake.queue_order()[:2] == [row.word for row in stats["order"][:2]]     # the run wrote what it previewed
    pinned_ids = {fake.card_of("須藤")["cardId"], fake.card_of("図書館")["cardId"]}
    suspended = {c for action, ids in fake.suspend_calls if action == "suspend" for c in ids}
    assert not suspended & pinned_ids
    assert not {c for c, _flag in fake.flag_writes} & pinned_ids
    tagged = {n for _action, notes, _tag in fake.tag_calls for n in notes}
    assert not tagged & {fake.card_of("須藤")["note"], fake.card_of("図書館")["note"]}


def test_a_card_junban_itself_parked_comes_back_first(tmp_path, three_oh):
    """✅ E1.3-2: 須藤 was parked by Junban (suspended, its `::later` tag) and isn't on the list again — pinned, it is
    unsuspended and placed first; a parked card of another show stays parked."""
    entries = [("冒険", "冒険が始まった。", 2000, [], 0),
               ("須藤", "須藤さんが来た。", 9000, ["Surasura::later"], -1),
               ("図書館", "図書館で本を読んだ。", 6000, ["Surasura::later"], -1)]
    fake = scene(tmp_path, entries)
    _mined_from_the_show(fake, "須藤")
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    assert fake.card_of("須藤")["queue"] == 0
    assert fake.queue_order()[0] == "須藤"
    assert fake.card_of("図書館")["queue"] == -1


def test_a_card_you_suspended_yourself_stays_suspended_even_pinned(tmp_path, three_oh):
    """No `::later` tag: you suspended it ("All suspended cards are intentional", K39) — a pin never undoes that."""
    entries = [("冒険", "冒険が始まった。", 2000, [], 0), ("須藤", "須藤さんが来た。", 9000, [], -1)]
    fake = scene(tmp_path, entries)
    _mined_from_the_show(fake, "須藤")
    with _patched(fake):
        reposition.run(settings())
    assert fake.card_of("須藤")["queue"] == -1
    assert not [call for call in fake.suspend_calls if call[0] == "unsuspend"]


def test_in_2_x_no_run_reads_a_pin_and_every_request_is_as_before(tmp_path, monkeypatch):
    """✅ E1.3-3: with `PINS` off, the same scene (its cards naming a pinned show) runs exactly as with no pin at all —
    the feed is never asked."""
    monkeypatch.setattr(connect, "PINS", False)     # P4.2.1: the 3.0 line sets it True; 2.x's behaviour held here
    def record(fake_scene):
        with _patched(fake_scene):
            reposition.run(settings())
        return fake_scene.requests, fake_scene.queue_order()

    plain = scene(tmp_path / "a", without_connect())
    _mined_from_the_show(plain, "須藤", "図書館")
    monkeypatch.setattr(pins, "read", lambda language: pytest.fail("2.x read a pin"))
    monkeypatch.setattr(pins, "groups", lambda *a, **k: pytest.fail("2.x asked for pin groups"))
    first = record(plain)
    again = scene(tmp_path / "b", without_connect())
    _mined_from_the_show(again, "須藤", "図書館")
    assert record(again) == first
    assert set(first[1][:2]) != {"須藤", "図書館"}      # the list's order: the show's cards aren't lifted


def test_a_parked_pinned_card_you_clicked_off_in_the_preview_stays_parked(tmp_path, three_oh):
    """✅ E1.3-2 brings a parked card of a pinned show back — unless you clicked it off in the preview
    (`junban_exclude_cards`): then the run leaves it exactly as it is, still suspended, never unsuspended for a run that
    then doesn't place it. 図書館, pinned and parked too but not clicked off, still comes back."""
    entries = [("冒険", "冒険が始まった。", 2000, [], 0),
               ("須藤", "須藤さんが来た。", 9000, ["Surasura::later"], -1),
               ("図書館", "図書館で本を読んだ。", 6000, ["Surasura::later"], -1)]
    fake = scene(tmp_path, entries)
    _mined_from_the_show(fake, "須藤", "図書館")
    off = fake.card_of("須藤")["cardId"]
    with _patched(fake):
        report = reposition.run(settings(junban_exclude_cards=[off]))
    assert report["ok"], report["problems"]
    assert off not in report["stats"].get("returning", [])
    assert fake.card_of("須藤")["queue"] == -1
    assert off not in {c for action, ids in fake.suspend_calls if action == "unsuspend" for c in ids}
    assert fake.card_of("図書館")["queue"] == 0


def test_on_3_0_the_pins_flag_is_set():
    """P4.2 row P4.2.1: the 3.0 line reads the user's own pins (only theirs: P2.2's 2.2.7 guard). 2.x-dev keeps it
    False."""
    assert connect.PINS is True
