# SPDX-License-Identifier: GPL-3.0-or-later
"""M-W2-1 (Sonic, 2026-10-23: "And your lean for empty list"): an empty list puts nothing away.

When nothing in the library counts any more — every file watched, or every file Finished — the list has no row, so
every card in scope would be "not on your list": tagged `Surasura::later` and suspended, all of them. Instead the run
leaves Anki's cards as they are and says so (`reposition.EMPTY_LIST`): no position, no tag, no suspend, no snapshot
(one of nothing would replace the route back from the last run). One rule for every caller: the 順 window, the
window's re-order host (an engine with no rows) and an unattended run. A list with one row still puts the rest away.

What a wrong answer would cost a learner: every new card in Anki hidden at once after finishing or watching the last
show of a library.
"""
import os

from modules.junban import auto, reposition, spaced, undo
from modules.junban.tests.connect_scene import runs_on_disk, scene, settings, without_connect
from modules.junban.tests.test_reposition import _JOURNEY, _LIBRARY, _patched, _results

WRITES = ("setSpecificValueOfCard", "multi", "suspend", "unsuspend", "addTags", "removeTags")


def _state(fake):
    return {c: (card["due"], card["queue"], tuple(fake.notes[card["note"]].get("tags") or []))
            for c, card in fake.cards.items()}


def _writes(fake, start=0):
    return [r for r in fake.requests[start:] if r.get("action") in WRITES]


def _host_job(fake, rows):
    """The window's re-order host's job: an automatic spaced job with its actions on and the engine's rows."""
    chosen = auto.decide_actions(settings(preview=False, junban_auto_actions=True))
    job = spaced.Job(automatic=True, rows=rows)
    job.actions = True
    with _patched(fake):
        return reposition.run(chosen, refresh=False, job=job)


def test_the_hosts_job_with_an_engine_of_no_rows_puts_nothing_away_and_says_so(tmp_path):
    fake = scene(tmp_path, without_connect())
    before, snapshot = _state(fake), undo.load("ja")
    report = _host_job(fake, rows=[])
    assert report["ok"] and report["message"] == reposition.EMPTY_LIST and report.get("empty_list")
    assert _writes(fake) == [] and _state(fake) == before, "no position, tag or suspend"
    assert undo.load("ja") == snapshot, "no snapshot: the route back from the last run stays"


def test_a_junban_run_on_an_empty_list_puts_nothing_away(tmp_path):
    fake = scene(tmp_path, without_connect())
    _results(tmp_path, progressive=[], library=_LIBRARY, floor=11)      # the list, header only
    before = _state(fake)
    with _patched(fake):
        preview_writes, stats = reposition.dry_run(settings(preview=False))
        report = reposition.run(settings(preview=False))
    assert preview_writes == [] and stats.get("empty_list") and stats["to_write"] == 0
    assert report["ok"] and report["message"] == reposition.EMPTY_LIST
    assert _writes(fake) == [] and _state(fake) == before
    assert runs_on_disk() == []


def test_a_list_of_one_row_still_puts_the_cards_not_on_it_away(tmp_path):
    # the guard is the empty list alone: one row left is a list, and the words that left it step back as ever
    fake = scene(tmp_path, without_connect())
    _results(tmp_path, progressive=_JOURNEY[:1], library=_LIBRARY, floor=11)
    with _patched(fake):
        report = reposition.run(settings(preview=False))
    assert report["ok"] and report["message"] != reposition.EMPTY_LIST
    assert [card for card in fake.cards.values() if card["queue"] == -1], "the cards off the list are put away"


def test_a_marker_pick_that_matches_no_word_is_not_an_empty_list(tmp_path):
    # *Only words marked* narrows the ranked words alone (`rank_of`); the list itself still has its rows, so the run is
    # the marker pick's, never "Your list is empty"
    fake = scene(tmp_path, without_connect())
    with _patched(fake):
        report = reposition.run(settings(preview=False, junban_only_markers=["star"]))
    assert report["message"] != reposition.EMPTY_LIST and not report.get("empty_list")


# --- after the review (reviews/M-W2-1-adversary.md) ------------------------------------------------------------- #
def test_on_an_empty_list_a_pinned_shows_parked_card_still_comes_back_and_nothing_is_put_away(tmp_path, monkeypatch):
    # adversary #1 (MUST): *Study its cards first* brings an item's parked card back whatever the list says — an empty
    # list too (every show Finished, then one pinned). The empty list still puts nothing away: the card not on it, never
    # parked, stays unsuspended and untagged.
    from modules.junban import pins as pin_feed
    entries = [("冒険", "冒険が始まった。", 2000, [], 0),
               ("須藤", "須藤さんが来た。", 9000, ["Surasura::later"], -1)]
    fake = scene(tmp_path, entries)
    _host_job(fake, rows=None)                     # Junban's own record of the card it parked
    parked, free = fake.card_of("須藤"), fake.card_of("冒険")
    assert parked["queue"] == -1 and free["queue"] == 0
    monkeypatch.setattr(pin_feed, "read", lambda language:
                        ([(7, "Library/x/ep1.srt", "2026-10-23T15:00:00Z")], {7: [parked["note"]]}, {}, set()))
    report = _host_job(fake, rows=[])
    assert report["ok"], report["problems"]
    assert fake.card_of("須藤")["queue"] == 0, "the pinned item's parked card comes back"
    assert fake.card_of("冒険")["queue"] == 0, "an empty list puts nothing away"
    assert "Surasura::later" not in (fake.notes[free["note"]].get("tags") or [])


def test_an_unreadable_list_is_refused_never_read_as_empty(tmp_path):
    # adversary #2: a list that can't be read (a broken file, half written) gives no rows, and must not pass for an
    # empty one — that answer is ok, so the window's re-order would count the order as written and never try again
    fake = scene(tmp_path, without_connect())
    with open(os.path.join(str(tmp_path), "results", "progressive_learning_list.csv"), "wb") as handle:
        handle.write(b"Sequence,Word,Orth\n1,\xff\xfe\xfa,x\n")         # not UTF-8
    before = _state(fake)
    with _patched(fake):
        report = reposition.run(settings(preview=False))
    assert not report["ok"] and not report.get("empty_list"), report["message"]
    assert report["message"] != reposition.EMPTY_LIST and report["problems"]
    assert _writes(fake) == [] and _state(fake) == before


def test_the_preview_of_an_empty_list_says_so(tmp_path):
    # adversary #3: the 順 preview said "There are no new cards in this scope." while the deck held new cards
    from modules.junban import junban_view
    fake = scene(tmp_path, without_connect())
    _results(tmp_path, progressive=[], library=_LIBRARY, floor=11)
    with _patched(fake):
        _writes_planned, stats = reposition.dry_run(settings(preview=False))
    shown = junban_view.preview_view(stats, {"warnings": [], "problems": []})
    assert (reposition.EMPTY_LIST, "good") in shown.lines, shown.lines


def test_the_automatic_step_says_the_list_is_empty(monkeypatch):
    # adversary #6: the automatic step's quiet rule ("" when nothing was written) hid the empty list's line
    monkeypatch.setattr(auto, "reorder", lambda settings, list_current=None, job=None: {
        "outcome": "ran", "report": {"ok": True, "empty_list": True, "message": reposition.EMPTY_LIST, "written": []}})
    assert auto._reorder_quietly(settings(preview=False)) == f"順 (automatic): {reposition.EMPTY_LIST}"
