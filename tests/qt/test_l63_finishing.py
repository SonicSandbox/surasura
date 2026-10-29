"""L6.3 for 3.0 (Sonic 2026-10-28): a title finishes by itself, and a split's parts join forward — ONE rule,
`drag.when_done`, asked when a Done leaves no file of a row unwatched (scope: the planning folder's
`tracks/logic/work/L6.3/scope.md`, rules R1–R8, PROVISIONAL).

What a wrong answer would cost a learner:
  * a show still airing (its newest episode came in on its own, last week) leaving Current the moment he catches up —
    caught up is not finished;
  * a title finished while a part of it still waits (a hole in its numbers, a file in New arrivals, a part in Goal),
    splitting it across Finished and the rest;
  * a split's first part left in Current with every file watched, or sent to Finished on its own;
  * the next part in Goal never coming up, or one that comes BEFORE the part he finished brought up after it;
  * anything moving by itself while he asked to keep studying watched episodes (their words would leave his list);
  * the toast's Undo taking back his own ✓ instead of what Surasura did by itself.

The rule is pure: rows, the view and episodes are built here as the reader builds them (the fields `when_done`
reads), titled with real shows. The window half runs on the window seed (tests/qt/test_drag.py's `world`).
"""
import time
from types import SimpleNamespace as NS

import pytest

from app.qt import drag, strings
from app.services import view_rows
from tests.qt.test_drag import _all_but_one, calls, rows_of, settle, wait_until, world  # noqa: F401 (the fixture)

NOW = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, 0))
DAY = 24 * 3600


def _stamp(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + ".000000Z"


def _eps(first, n, watched=True, added=None, start_id=1):
    """`n` episodes numbered from `first`, every one watched, all taken in together 40 days ago unless `added`."""
    added = added or [NOW - 40 * DAY] * n
    return tuple(NS(id=start_id + k, number=None if first is None else first + k, watched=watched,
                    added=None if added[k] is None else _stamp(added[k])) for k in range(n))


def _row(key, work, piece, episodes, index=0, title="葬送のフリーレン", **kw):
    base = dict(key=key, work_id=work, piece_id=piece, episodes=episodes, index=index, title=title, media="anime",
                source="disk", group=False, soon_from=None, soon_piece=None)
    base.update(kw)
    return NS(**base)


def _view(rows_, goal=(), arrivals=(), keep=False, cached=False):
    return NS(rows=tuple(rows_), goal=NS(works=tuple(goal)), arrivals=tuple(arrivals), keep_watched=keep,
              cached=cached)


def _goal(work, *pieces, group=False):
    return NS(work_id=work, group=group, pieces=tuple(pieces))


def _gp(piece, first, ids, line):
    return NS(piece_id=piece, first=first, item_ids=tuple(ids), line=line)


# --- R3: it finishes by itself ----------------------------------------------------------------------------------- #

def test_R3_a_title_whose_files_came_in_together_and_nothing_waits_finishes_by_itself():
    row = _row("p1", 1, 1, _eps(1, 12))
    assert drag.when_done(_view([row]), row, NOW) == ("finish",)


def test_R3_one_file_alone_a_film_or_a_one_off_video_finishes_by_itself():
    row = _row("p1", 1, 1, _eps(None, 1, added=[NOW - DAY]), title="君の名は。", media="film")
    assert drag.when_done(_view([row]), row, NOW) == ("finish",)


def test_R3_a_weekly_show_whose_last_episode_came_in_weeks_ago_finishes_and_a_later_one_brings_it_back():
    """Its newest file came alone, but 20 days ago (past `ARRIVING_RECENT_S`): it finishes; a new episode later leads
    Current (Q4-9, the store's test below)."""
    added = [NOW - 90 * DAY + k * 7 * DAY for k in range(9)] + [NOW - 20 * DAY]
    row = _row("p1", 1, 1, _eps(1, 10, added=added), title="ぼっち・ざ・ろっく！")
    assert drag.when_done(_view([row]), row, NOW) == ("finish",)


# --- R4: it may still be arriving -------------------------------------------------------------------------------- #

def test_R4_a_show_whose_newest_episode_came_in_on_its_own_last_week_is_offered_never_finished():
    added = [NOW - 40 * DAY] * 5 + [NOW - 5 * DAY]                     # five at setup, the sixth on its own since
    row = _row("p1", 1, 1, _eps(1, 6, added=added), title="薬屋のひとりごと")
    assert drag.when_done(_view([row]), row, NOW) == ("offer",)


def test_R4_files_a_few_minutes_apart_are_one_download_not_an_airing_show():
    added = [NOW - 3 * DAY + k * 60 for k in range(12)]                 # a season downloaded at once, three days ago
    row = _row("p1", 1, 1, _eps(1, 12, added=added))
    assert drag.when_done(_view([row]), row, NOW) == ("finish",)


def test_R4_a_file_with_no_arrival_time_a_cache_from_before_can_not_tell_so_it_asks():
    row = _row("p1", 1, 1, _eps(1, 3, added=[NOW - 40 * DAY, None, NOW - 40 * DAY]))
    assert view_rows.still_arriving(row.episodes, NOW) is True
    assert drag.when_done(_view([row]), row, NOW) == ("offer",)


def test_R4_still_arriving_reads_the_store_stamp_and_the_edges():
    """Exactly one day apart is a download (not alone); just over, alone; exactly 14 days old is no longer recent."""
    alone = view_rows.ARRIVING_ALONE_S
    recent = view_rows.ARRIVING_RECENT_S
    eps = lambda gap, age: _eps(1, 2, added=[NOW - age - gap, NOW - age])     # noqa: E731
    assert not view_rows.still_arriving(eps(alone, 0), NOW)
    assert view_rows.still_arriving(eps(alone + 1, 0), NOW)
    assert view_rows.still_arriving(eps(alone + 1, recent - 1), NOW)
    assert not view_rows.still_arriving(eps(alone + 1, recent), NOW)
    assert not view_rows.still_arriving(_eps(1, 1, added=[NOW]), NOW), "one file alone never is"
    assert view_rows._seconds("2026-10-28T12:00:00.123456Z") == view_rows._seconds("2026-10-28T12:00:00Z")
    assert view_rows._seconds("not a time") is None and view_rows._seconds(None) is None


# --- R5: a part still to come ------------------------------------------------------------------------------------ #

def test_R5_a_hole_in_the_numbers_is_offered_and_an_unnumbered_special_is_no_hole():
    holed = _row("p1", 1, 1, _eps(1, 4) + _eps(6, 1, start_id=9))
    assert view_rows.numbers_gap(holed.episodes)
    assert drag.when_done(_view([holed]), holed, NOW) == ("offer",)
    special = _row("p1", 1, 1, _eps(1, 4) + _eps(None, 1, start_id=9))
    assert not view_rows.numbers_gap(special.episodes)
    assert drag.when_done(_view([special]), special, NOW) == ("finish",)


def test_R5_a_file_of_it_still_in_new_arrivals_is_offered():
    row = _row("p1", 1, 1, _eps(1, 4))
    assert drag.when_done(_view([row], arrivals=[NS(work_id=1)]), row, NOW) == ("offer",)
    assert drag.when_done(_view([row], arrivals=[NS(work_id=2)]), row, NOW) == ("finish",), "another title's"


def test_R5_an_earlier_part_still_in_current_is_offered_never_finished_on_its_own():
    early = _row("p1", 1, 1, _eps(1, 4, watched=False), index=0)
    late = _row("p2", 1, 2, _eps(5, 4, start_id=5), index=1)
    assert not drag.split_first([early, late], late)
    assert drag.when_done(_view([early, late]), late, NOW) == ("offer",)


def test_R5_a_goal_part_that_comes_before_or_has_no_number_is_offered():
    row = _row("p2", 1, 2, _eps(5, 4, start_id=5))
    before = _goal(1, _gp(7, 1, (1, 2, 3, 4), "Ep 1–4"))
    assert drag.when_done(_view([row], goal=[before]), row, NOW) == ("offer",)
    unnumbered = _goal(1, _gp(7, None, (20,), "1 episode"))
    assert drag.when_done(_view([row], goal=[unnumbered]), row, NOW) == ("offer",)
    mixed = _goal(1, _gp(7, 9, (9, 10), "Ep 9–10"), _gp(8, None, (20,), "1 episode"))
    assert drag.when_done(_view([row], goal=[mixed]), row, NOW) == ("offer",), "any part it can't place asks"


# --- R1 / R2: a split's parts join forward ----------------------------------------------------------------------- #

def test_R1_a_splits_first_part_done_joins_the_next_part_in_current_just_before_it():
    first = _row("p1", 1, 1, _eps(1, 12), index=0)
    other = _row("p9", 2, 9, _eps(1, 3, watched=False, start_id=40), index=1, title="ダンジョン飯")
    second = _row("p2", 1, 2, _eps(13, 12, watched=False, start_id=13), index=2)
    verdict = drag.when_done(_view([first, other, second]), first, NOW)
    assert verdict[:4] == ("join", [2, 1], True, drag.ids_of(first) + drag.ids_of(second))
    assert verdict[4] == view_rows.range_text("anime", list(range(13, 25)), 12)


def test_R1_the_nearest_later_part_is_joined_and_a_soon_line_row_joins_with_both_its_pieces():
    first = _row("p1", 1, 1, _eps(1, 4), index=0, soon_from=2, soon_piece=5)
    third = _row("p3", 1, 3, _eps(9, 4, watched=False, start_id=9), index=1)
    second = _row("p2", 1, 2, _eps(5, 4, watched=False, start_id=5), index=2)
    verdict = drag.when_done(_view([first, third, second]), first, NOW)
    assert verdict[1] == [2, 1, 5] and verdict[2] is True


def test_R1_a_part_with_no_piece_never_joins_and_is_never_offered_finished():
    first = _row("p1", 1, None, _eps(1, 4), index=0)
    second = _row("p2", 1, 2, _eps(5, 4, watched=False, start_id=5), index=1)
    assert drag.when_done(_view([first, second]), first, NOW) is None


def test_R2_the_next_part_waiting_in_goal_comes_up_after_this_one():
    row = _row("p1", 1, 1, _eps(1, 12))
    goal = _goal(1, _gp(8, 25, (25, 26), "Ep 25–26"), _gp(7, 13, tuple(range(13, 25)), "Ep 13–24"))
    verdict = drag.when_done(_view([row], goal=[goal]), row, NOW)
    assert verdict == ("join", [1, 7], False, drag.ids_of(row) + list(range(13, 25)), "Ep 13–24")


def test_R2_a_group_tile_in_goal_or_another_titles_part_is_never_brought_up():
    row = _row("p1", 1, 1, _eps(1, 12))
    group = _goal(1, _gp(7, 13, (13,), "Ep 13"), group=True)
    other = _goal(2, _gp(8, 13, (30,), "Ep 13"))
    assert drag.when_done(_view([row], goal=[group, other]), row, NOW) == ("finish",)


# --- R6 / R7 and the first seconds ------------------------------------------------------------------------------- #

def test_R6_keep_studying_on_moves_nothing_by_itself():
    row = _row("p1", 1, 1, _eps(1, 12))
    assert drag.when_done(_view([row], keep=True), row, NOW) == ("offer",)
    second = _row("p2", 1, 2, _eps(13, 12, watched=False, start_id=13), index=1)
    assert drag.when_done(_view([row, second], keep=True), row, NOW) is None, "a first part: as today, no join"
    goal = _goal(1, _gp(7, 13, (13,), "Ep 13"))
    assert drag.when_done(_view([row], goal=[goal], keep=True), row, NOW) == ("offer",)


def test_R7_a_group_is_offered_and_hatos_mix_never_finishes():
    group = _row("p1", 1, 1, _eps(1, 4), group=True)
    assert drag.when_done(_view([group]), group, NOW) == ("offer",)
    mix = _row("p2", 3, 2, _eps(None, 4), source="hato", media="youtube")
    assert drag.when_done(_view([mix]), mix, NOW) is None


def test_the_first_screens_cache_or_no_view_asks_goal_and_arrivals_are_not_read_yet():
    row = _row("p1", 1, 1, _eps(1, 4))
    assert drag.when_done(_view([row], cached=True), row, NOW) == ("offer",)
    assert drag.when_done(None, row, NOW) == ("offer",)


# --- the window: one rule, the paths a hand takes ---------------------------------------------------------------- #

def test_window_a_title_still_arriving_keeps_todays_offer_and_writes_only_the_mark(world):
    seed, win, writer = world()
    row = _all_but_one(seed, win, 4)
    stamp = time.time()
    seed.library.commit(items=[{"id": e.id, "added_at": _stamp(stamp - 30 * DAY)} for e in row.episodes[:-1]] +
                        [{"id": row.episodes[-1].id, "added_at": _stamp(stamp - 2 * DAY)}])
    assert wait_until(lambda: rows_of(win)[4].episodes[-1].added is not None and
                      view_rows.still_arriving(rows_of(win)[4].episodes), 3)
    row = rows_of(win)[4]
    win.moves.done(row, row.episodes[-1])
    assert [c[0] for c in calls(writer)] == ["set_watched"]
    assert win.toasts.card.base == strings.DONE_ALL.format(n=len(row.episodes))


def test_window_the_finish_toasts_undo_takes_back_the_finish_and_the_mark_stays(world):
    """The toast's Undo takes back what Surasura did by itself (the finish); the learner's own ✓ stays saved."""
    seed, win, writer = world()
    row = _all_but_one(seed, win, 4)
    win.moves.done(row, row.episodes[-1])
    assert wait_until(lambda: [c.op for c in writer.saved] == ["set_watched", "set_tier"] and
                      win.moves.tickets == [], 3)
    settle()
    win.toasts.card.buttons[0].click()                                 # Undo
    assert [c.op for c in writer.undone] == ["set_tier"]


def test_a_goal_parts_first_number_is_its_lowest_and_none_when_one_of_its_files_has_none():
    """What R2 reads of Goal: each part's lowest episode number, as the tile's range reads its files' names."""
    def part(names, piece):
        return [{"id": 100 * piece + k, "work_id": 1, "piece_id": piece, "title": None, "source_type": "subtitle",
                 "rel_path": f"Library/葬送のフリーレン/{name}"} for k, name in enumerate(names)]
    works = {1: {"id": 1, "title": "葬送のフリーレン", "media_type": "anime"}}
    tile = view_rows._goal_work("w1", [part(["葬送のフリーレン 第14話.srt", "葬送のフリーレン 第13話.srt"], 7),
                                       part(["葬送のフリーレン 第15話.srt", "特典映像.srt"], 8)], works, None)
    assert [(p.piece_id, p.first) for p in tile.pieces] == [(7, 13), (8, None)]


def test_two_folders_of_one_name_are_two_titles_the_rule_never_joins_them():
    """The same title in two folders is two works (the store's test): neither is the other's part."""
    a = _row("p1", 1, 1, _eps(1, 4), index=0, title="ハリー・ポッターと賢者の石")
    b = _row("p2", 2, 2, _eps(1, 4, watched=False, start_id=5), index=1, title="ハリー・ポッターと賢者の石")
    assert drag.when_done(_view([a, b]), a, NOW) == ("finish",)
