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

from app.qt import drag, strings
from app.services import view_rows
from tests.qt.test_drag import _all_but_one, _keep_on, calls, real, rows_of, settle, wait_until, world  # noqa: F401
from tests.qt.test_finish_pending import live, owed, plan, window  # noqa: F401 (window: the real stack's fixture)

NOW = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, 0))
DAY = 24 * 3600


def _stamp(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + ".000000Z"


def _eps(first, n, watched=True, added=None, start_id=1):
    """`n` episodes numbered from `first`, every one watched, all taken in together 40 days ago unless `added`."""
    added = added or [NOW - 40 * DAY] * n
    return tuple(NS(id=start_id + k, number=None if first is None else first + k, watched=watched, waiting=False,
                    added=None if added[k] is None else _stamp(added[k])) for k in range(n))


def _row(key, work, piece, episodes, index=0, title="葬送のフリーレン", **kw):
    base = dict(key=key, work_id=work, piece_id=piece, episodes=episodes, index=index, title=title, media="anime",
                source="disk", group=False, soon_from=None, soon_piece=None, works=(work,) if work else ())
    base.update(kw)
    return NS(**base)


def _view(rows_, goal=(), arrivals=(), keep=False, cached=False, finished=()):
    return NS(rows=tuple(rows_), goal=NS(works=tuple(goal)), arrivals=tuple(arrivals), keep_watched=keep,
              cached=cached, finished=(NS(label="October 2026", rows=tuple(finished)),) if finished else ())


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


def test_R3_a_weekly_show_whose_last_episode_came_in_weeks_ago_finishes():
    """Its newest file came alone, but 20 days ago (past `ARRIVING_RECENT_S`): it finishes; a new episode later leads
    Current (Q4-9, the store's test) and is asked (below)."""
    added = [NOW - 90 * DAY + k * 7 * DAY for k in range(9)] + [NOW - 20 * DAY]
    row = _row("p1", 1, 1, _eps(1, 10, added=added), title="ぼっち・ざ・ろっく！")
    assert drag.when_done(_view([row]), row, NOW) == ("finish",)


def test_R4_a_later_episode_of_a_title_already_in_finished_is_asked_never_finished_by_itself():
    """A title with files in Finished whose new episode came in (Q4-9: it leads Current, a row of one file): a show
    still airing — every week's episode would finish it again. Asked; another title's Finished files don't count."""
    row = _row("p2", 1, 2, _eps(6, 1, added=[NOW - 40 * DAY], start_id=6), title="薬屋のひとりごと")
    assert drag.when_done(_view([row], finished=[NS(work_id=1)]), row, NOW) == ("offer",)
    assert drag.when_done(_view([row], finished=[NS(work_id=2)]), row, NOW) == ("finish",)


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


def test_R5_a_video_still_waiting_for_its_subtitle_is_offered():
    eps = _eps(1, 4)
    row = _row("p1", 1, 1, eps[:3] + (NS(**dict(vars(eps[3]), waiting=True)),))
    assert drag.when_done(_view([row]), row, NOW) == ("offer",)


def test_R5_a_file_of_it_still_in_new_arrivals_is_offered():
    row = _row("p1", 1, 1, _eps(1, 4))
    assert drag.when_done(_view([row], arrivals=[NS(work_id=1)]), row, NOW) == ("offer",)
    assert drag.when_done(_view([row], arrivals=[NS(work_id=2)]), row, NOW) == ("finish",), "another title's"


def test_R5_a_part_whose_earlier_part_waits_in_current_or_inside_a_group_is_never_offered_finished():
    """A split part never enters Finished (70 Q11: the last part waits for the earlier one): a plain ✓, no offer."""
    early = _row("p1", 1, 1, _eps(1, 4, watched=False), index=0)
    late = _row("p2", 1, 2, _eps(5, 4, start_id=5), index=1)
    assert not drag.split_first([early, late], late)
    assert drag.when_done(_view([early, late]), late, NOW) is None
    group = _row("g1", 2, 3, _eps(1, 4, watched=False, start_id=20), index=0, group=True, works=(2, 1),
                 title="ダンジョン飯 + 1 more")
    assert drag.when_done(_view([group, late]), late, NOW) is None, "its earlier episodes in a group"


def test_R5_a_goal_part_that_comes_before_has_no_number_or_lives_in_a_group_is_never_offered_finished():
    row = _row("p2", 1, 2, _eps(5, 4, start_id=5))
    before = _goal(1, _gp(7, 1, (1, 2, 3, 4), "Ep 1–4"))
    assert drag.when_done(_view([row], goal=[before]), row, NOW) is None
    same = _goal(1, _gp(7, 8, (30,), "Ep 8"))
    assert drag.when_done(_view([row], goal=[same]), row, NOW) is None, "its first is this part's last: not after"
    unnumbered = _goal(1, _gp(7, None, (20,), "1 episode"))
    assert drag.when_done(_view([row], goal=[unnumbered]), row, NOW) is None
    mixed = _goal(1, _gp(7, 9, (9, 10), "Ep 9–10"), _gp(8, None, (20,), "1 episode"))
    assert drag.when_done(_view([row], goal=[mixed]), row, NOW) is None, "any part it can't place: a plain ✓"
    no_piece = _goal(1, _gp(None, 9, (9, 10), "Ep 9–10"))
    assert drag.when_done(_view([row], goal=[no_piece]), row, NOW) is None
    grouped = _goal(1, _gp(7, 9, (9,), "Ep 9"), group=True)
    assert drag.when_done(_view([row], goal=[grouped]), row, NOW) is None


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


def test_R2_a_group_tile_in_goal_is_never_brought_up_and_another_titles_part_is_not_this_ones():
    row = _row("p1", 1, 1, _eps(1, 12))
    group = _goal(1, _gp(7, 13, (13,), "Ep 13"), group=True)
    assert drag.when_done(_view([row], goal=[group]), row, NOW) is None
    other = _goal(2, _gp(8, 13, (30,), "Ep 13"))
    assert drag.when_done(_view([row], goal=[other]), row, NOW) == ("finish",)


# --- R6 / R7 and the first seconds ------------------------------------------------------------------------------- #

def test_R6_keep_studying_on_moves_nothing_by_itself():
    row = _row("p1", 1, 1, _eps(1, 12))
    assert drag.when_done(_view([row], keep=True), row, NOW) == ("offer",)
    second = _row("p2", 1, 2, _eps(13, 12, watched=False, start_id=13), index=1)
    assert drag.when_done(_view([row, second], keep=True), row, NOW) is None, "a first part: as today, no join"
    goal = _goal(1, _gp(7, 13, (13,), "Ep 13"))
    assert drag.when_done(_view([row], goal=[goal], keep=True), row, NOW) is None, "a part: no join, no offer"


def test_a_write_still_on_its_way_moves_nothing_by_itself():
    """The view may not hold it yet (a part just dragged to Goal, painted ahead): offered, never finished or joined."""
    row = _row("p1", 1, 1, _eps(1, 12))
    assert drag.when_done(_view([row]), row, NOW, pending=True) == ("offer",)
    second = _row("p2", 1, 2, _eps(13, 12, watched=False, start_id=13), index=1)
    assert drag.when_done(_view([row, second]), row, NOW, pending=True) is None
    goal = _goal(1, _gp(7, 13, (13,), "Ep 13"))
    assert drag.when_done(_view([row], goal=[goal]), row, NOW, pending=True) is None


def test_a_row_of_no_title_is_asked_never_matched_to_another_untitled_part():
    loose = _row("i5", None, None, _eps(None, 1), title="インタビュー")
    other = _row("i6", None, None, _eps(None, 1, watched=False, start_id=9), index=1, title="対談")
    assert drag.when_done(_view([loose, other], goal=[_goal(None, _gp(7, 2, (20,), "Ep 2"))]), loose, NOW) == \
        ("offer",)


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


def test_window_a_write_still_waiting_in_a_busy_store_keeps_the_offer(world):
    """Another Done still on its way (the store busy): the last file's Done asks, as the view may not hold it."""
    seed, win, writer = world()
    row = _all_but_one(seed, win, 4)
    other = rows_of(win)[2]
    writer.stuck = True
    win.moves.done(other, other.episodes[other.next_index])
    assert win.moves.tickets
    win.moves.done(row, row.episodes[-1])
    assert [c[0] for c in calls(writer)] == ["set_watched", "set_watched"]
    assert win.toasts.card.base == strings.DONE_ALL.format(n=len(row.episodes))
    writer.free()


def test_window_keep_studying_on_writes_only_the_mark_and_offers(world):
    seed, win, writer = world()
    _keep_on(seed, win)
    row = _all_but_one(seed, win, 4)
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


def test_end_to_end_the_last_done_finishes_on_the_real_store_its_anki_half_waits_and_undo_keeps_the_mark(window):
    """On the real store, writer and reader: the last file's Done writes the mark, then the Finish path — the title in
    Finished with every file watched, its press turning until the re-order for it lands (Finish acts after its
    Generate, FP-1…4) — and the toast's Undo puts the title back in Current with the mark kept (one Undo for what
    Surasura did by itself)."""
    store, win, writer = window()
    page = win.page_widgets["current"]
    row = next(r for r in page.view_model.rows[1:] if len(r.episodes) >= 2 and not drag.split_first(
        page.view_model.rows, r) and drag.finishes(r))
    ids = drag.ids_of(row)
    assert store.set_watched(ids[:-1]) is not None                  # another program marked the rest first
    assert wait_until(lambda: all(e.watched for r in page.view_model.rows if r.key == row.key
                                  for e in r.episodes[:-1]), 5)
    row = next(r for r in page.view_model.rows if r.key == row.key)
    assert drag.when_done(page.view_model, row._replace(episodes=tuple(e._replace(watched=True)
                                                                       for e in row.episodes))) == ("finish",)
    win.moves.done(row, row.episodes[-1])
    assert win.toasts.card.base == strings.DONE_FINISHED.format(title=row.title)
    assert owed(win) and live(win)
    assert wait_until(lambda: {store.item(i)["tier"] for i in ids} == {"graduated"}, 5)
    assert {store.item(i)["watched"] for i in ids} == {1}
    plan(store)
    assert wait_until(lambda: not live(win), 5)
    settle()
    win.toasts.card.buttons[0].click()                                 # the Finished toast's Undo
    assert wait_until(lambda: {store.item(i)["tier"] for i in ids} <= {"now", "soon"}, 5)
    assert {store.item(i)["watched"] for i in ids} == {1}, "the learner's own ✓ stays"

def test_window_a_later_part_whose_earlier_part_waits_gets_the_plain_mark_never_finished_with_it(world):
    """Haiku H1: the rule's None (a split's part) was falling through to today's offer. The later part's last Done
    writes the mark alone and shows no *finished with it?*; done again from Up Next, the bar says why."""
    seed, win, writer = world()
    rs = rows_of(win)
    first = next(r for r in rs if drag.split_first(rs, r))
    i = next(n for n, r in enumerate(rs) if r.key != first.key and r.work_id == first.work_id)
    row = _all_but_one(seed, win, i)
    every = row._replace(episodes=tuple(e._replace(watched=True) for e in row.episodes))
    assert drag.when_done(win.page_widgets["current"].view_model, every) is None
    win.moves.done(row, row.episodes[-1])
    assert [c[0] for c in calls(writer)] == ["set_watched"]
    assert win.toasts.card is None or win.toasts.card.base != strings.DONE_ALL.format(n=len(row.episodes))
    settle()
    assert wait_until(lambda: all(e.watched for e in rows_of(win)[i].episodes), 3)
    writer.calls.clear()
    win.moves.done(rows_of(win)[i], None)
    assert calls(writer) == [] and win.bar_line.full() == strings.WELL_UNLIT_SPLIT


def test_R1_a_part_starting_on_this_parts_own_last_number_is_not_its_next_part():
    """`split_first`'s "later" is strictly after: a part whose first episode is this part's last (a second version
    of Ep 12 kept apart) is never the one joined; the part from Ep 13 is."""
    first = _row("p1", 1, 1, _eps(1, 12), index=0)
    again = _row("p3", 1, 3, _eps(12, 1, watched=False, start_id=40), index=1)
    second = _row("p2", 1, 2, _eps(13, 12, watched=False, start_id=13), index=2)
    assert drag.when_done(_view([first, again, second]), first, NOW)[1] == [2, 1]
