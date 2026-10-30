"""a7 (Sonic's alpha 6 try): a title never finishes by itself while it may still be airing (DIAGNOSIS 9), and ⋯ marks
many parts watched at once (DIAGNOSIS 11) — scope: the planning folder's `tracks/logic/work/a7-finish-mark/scope.md`.

What a wrong answer would cost a learner:
  * a show still airing, set up by a first look (every file taken in at one time), leaving Current the moment he
    catches up — Sonic's Tempal, finished with 4 episodes ("keep going until the season is done");
  * a finished season — downloaded at once, or weekly long ago — never finishing by itself any more;
  * the copies' dates moving the source's own files (the look never writes there);
  * a book with 30 chapters read needing 30 presses, or a mark of many needing many Undos;
  * *Mark watched up to here* marking a chapter after the one he chose, or one already watched again;
  * marking every file of a title skipping L6.3's one rule (finish by itself, or the offer).

Every scenario runs for Japanese and Chinese on a real store: a library set up by its first look at a source folder
(`sources.scan(..., first=True)`), files written from tests/Test Resources/, each original dated as it came in.
"""
import os
import time

import pytest

from app import library_store as ls
from app.qt import drag, strings
from app.services import view_rows
from tests.qt import test_drag
from tests.qt.test_drag import real, rows_of, settle, wait_until  # noqa: F401 (real: the real stack's fixture)
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _book_text, _drive, _empty, _fresh_module_state, _look, _text, _write  # noqa: F401

DAY = 24 * 3600
_SHOW = {"ja": "月影の旅人", "zh": "夜市小记"}                  # made-up titles, as test_sources_scan's
_BOOK = {"ja": "星降る町の図書館", "zh": "灯塔下的书店"}
_CHAPTER = {"ja": "第{n}章", "zh": "第{n}章"}


def _show(language, src, ages):
    """A show folder in the source: one subtitle per episode, episode k's original dated `ages[k]` days back."""
    show = _SHOW[language]
    for k, age in enumerate(ages):
        _write(os.path.join(src, show, f"{show} - {k + 1:02d}.srt"), _text(language, k + 1), age=age * DAY)
    return show


def _book(language, src, n=30):
    """A book folder in the source: `n` chapters, each a real text worth reading, all saved a month ago."""
    book, text = _BOOK[language], _book_text(language)
    for k in range(n):
        name = f"{book} {_CHAPTER[language].format(n=k + 1)}.txt"
        _write(os.path.join(src, book, name), text + f"\n{k + 1}\n", age=30 * DAY)
    return book


def _first_look(language, build):
    """Setup's first look at a source folder `build(src)` fills -> (the open store, the source folder); the source's
    root id is `store.a7_root` (a later look's)."""
    store, _data_dir = _empty(language)
    src = _drive("media")
    build(src)
    root = store.add_source(src)
    result = _look(store, language, root, first=True)
    assert result["reachable"] is True and result["added"] > 0
    store.a7_root = root
    return store, src


def _view(store, language):
    """The window's view of the store, built as the reader builds it (`read_feed` → `view_rows.build`)."""
    feed = store.read_feed()
    return view_rows.build({r["id"]: r for r in feed["items"]}, {w["id"]: w for w in feed["works"]}, feed["options"],
                           language=language, pieces={p["id"]: p for p in feed["pieces"]})


def _row(view, title):
    rows_ = [r for r in view.rows if any(f"/{title}/" in (e.rel_path or "") for e in r.episodes)]
    assert len(rows_) == 1, [r.title for r in view.rows]
    return rows_[0]


def _one_look(store, row):
    """Every file of `row` taken in by the same look (its take-in times within a minute)."""
    times = [view_rows._seconds(store.item(e.id)["added_at"]) for e in row.episodes]
    return max(times) - min(times) < 60


# --- DIAGNOSIS 9: the airing clock ---------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_weekly_show_set_up_by_the_first_look_is_still_airing_and_its_last_done_only_offers(language):
    """Tempal's case: four episodes downloaded a week apart, the newest yesterday; setup's first look takes all four in
    at ONE time. By the store's clock they came together (the bug: it finished); by the files' own dates — the copies
    keep the originals' — the newest came on its own a week after the one before: it may still be airing, so the last
    Done offers instead of finishing."""
    store, src = _first_look(language, lambda s: _show(language, s, [22, 15, 8, 1]))
    show = _SHOW[language]
    with store:
        row = _row(_view(store, language), show)
        assert len(row.episodes) == 4 and _one_look(store, row), "one take-in: a first look"
        for e in row.episodes:                       # each copy keeps its original's date (the source never touched)
            original = os.path.join(src, show, os.path.basename(e.rel_path))
            assert e.disk == os.stat(original).st_mtime_ns == store.item(e.id)["mtime_ns"]
        now = time.time()
        assert not view_rows.still_arriving([e._replace(disk=None) for e in row.episodes], now), \
            "the take-in clock alone reads it as one batch (alpha 6's finish)"
        assert view_rows.still_arriving(row.episodes, now)
        assert drag.when_done(_view(store, language), row, now) == ("offer",)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("ages", [[2] * 12, [100 - 7 * k for k in range(11)] + [23]],
                         ids=["season-downloaded-at-once", "weekly-season-ended-weeks-ago"])
def test_a_finished_season_set_up_by_the_first_look_still_finishes_by_itself(language, ages):
    """A season downloaded at once two days ago (one date by both clocks), and a weekly season whose last episode came
    23 days ago (past `ARRIVING_RECENT_S`): nothing says it may still be airing, so its last Done finishes it (L6.3 R3
    unchanged)."""
    store, _src = _first_look(language, lambda s: _show(language, s, ages))
    with store:
        view = _view(store, language)
        row = _row(view, _SHOW[language])
        assert len(row.episodes) == 12
        assert not view_rows.still_arriving(row.episodes, time.time())
        assert drag.when_done(view, row, time.time()) == ("finish",)


def test_the_airing_seam_an_airing_source_overrides_the_files_times_both_ways():
    """What AniList's status would answer (not asked in 3.0: a network use waiting on Sonic's word): still airing holds
    a season that came at once; done airing lets a weekly show finish; unknown leaves it to the files' times."""
    now = time.time()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime(now - 30 * DAY))
    blank = view_rows.Episode._make([None] * len(view_rows.Episode._fields))
    together = [blank._replace(id=k, added=stamp, disk=int((now - 2 * DAY) * 1e9)) for k in range(3)]
    weekly = [e._replace(disk=int((now - (15 - 7 * k) * DAY) * 1e9)) for k, e in enumerate(together)]
    assert not view_rows.still_arriving(together, now) and view_rows.still_arriving(weekly, now)
    assert view_rows.still_arriving(together, now, airing=True)
    assert not view_rows.still_arriving(weekly, now, airing=False)


# --- DIAGNOSIS 11: many parts marked watched at once, on the real stack ------------------------------------------- #
def _open(real, monkeypatch, language, build):
    """The real window (reader, writer, toasts) on a library set up by its first look at `build`'s source."""
    built, _src = _first_look(language, build)
    monkeypatch.setattr(test_drag, "migrated", lambda _language: built)
    return real(language)


def _watched(store, ids):
    return [i for i in ids if store.item(i)["watched"]]


def _changes(store):
    return store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_30_chapter_book_marked_up_to_chapter_20_in_one_command_and_one_undo_takes_them_all_back(real, monkeypatch,
                                                                                                 language):
    store, win, writer = _open(real, monkeypatch, language, lambda s: _book(language, s))
    row = _row(win.page_widgets["current"].view_model, _BOOK[language])
    assert len(row.episodes) == 30
    ep = row.episodes[19]
    upto = next(e for e in win.items.episode_entries(row, ep) if e.name == "ep-upto")
    assert upto.ok and [e.id for e in upto.payload] == [e.id for e in row.episodes[:20]], "chapters 1–20, in order"
    assert upto.label == strings.ITEM_EP_UPTO[0] and "20" in upto.tip
    v = store.versions()["state_version"]
    win.items.episode_pick(row, ep, "ep-upto", upto.payload)
    ids = [e.id for e in row.episodes]
    assert wait_until(lambda: _watched(store, ids) == ids[:20], 10)
    assert store.versions()["state_version"] == v + 1, "ONE command for the twenty"
    assert win.toasts.card.base == strings.DONE_MANY.format(title=row.title, n=20)
    win.toasts.card.buttons[0].click()                                 # its Undo
    assert wait_until(lambda: _watched(store, ids) == [], 10), "one Undo takes all twenty back"
    settle()
    row = _row(win.page_widgets["current"].view_model, _BOOK[language])
    assert {e.id for e in row.episodes} == set(ids) and row.tier in ("now", "soon")


@pytest.mark.parametrize("language", LANGUAGES)
def test_up_to_here_skips_a_chapter_already_watched_and_is_not_offered_where_it_would_mark_one(real, monkeypatch,
                                                                                               language):
    """Chapter 2 already watched: *up to chapter 4* marks 1, 3 and 4; on chapter 1 (nothing before it) the entry isn't
    there — the plain *Mark watched* is that one press."""
    store, win, writer = _open(real, monkeypatch, language, lambda s: _book(language, s, n=6))
    row = _row(win.page_widgets["current"].view_model, _BOOK[language])
    ids = [e.id for e in row.episodes]
    assert store.set_watched([ids[1]]) is not None
    assert wait_until(lambda: _row(win.page_widgets["current"].view_model, _BOOK[language]).episodes[1].watched, 10)
    row = _row(win.page_widgets["current"].view_model, _BOOK[language])
    assert "ep-upto" not in [e.name for e in win.items.episode_entries(row, row.episodes[0])]
    upto = next(e for e in win.items.episode_entries(row, row.episodes[3]) if e.name == "ep-upto")
    assert [e.id for e in upto.payload] == [ids[0], ids[2], ids[3]]
    win.items.episode_pick(row, row.episodes[3], "ep-upto", upto.payload)
    assert wait_until(lambda: _watched(store, ids) == ids[:4], 10)
    assert _watched(store, ids[4:]) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_mark_all_watched_on_a_book_read_in_one_go_finishes_it_by_itself_and_undo_keeps_the_marks(real, monkeypatch,
                                                                                                language):
    """Every chapter marked from the row's ⋯ is the last Done of each: L6.3's one rule — chapters that came in together
    finish the book by itself (its toast's Undo takes back the finish; the marks stay, as after a Done)."""
    store, win, writer = _open(real, monkeypatch, language, lambda s: _book(language, s))
    row = _row(win.page_widgets["current"].view_model, _BOOK[language])
    every = next(e for e in win.items.entries(row) if e.name == "watched-all")
    assert every.ok and len(every.payload) == 30 and "30" in every.tip
    win.items.menu_pick(row, "watched-all", every.payload)
    ids = [e.id for e in row.episodes]
    assert wait_until(lambda: {store.item(i)["tier"] for i in ids} == {"graduated"}, 15)
    assert _watched(store, ids) == ids
    assert win.toasts.card.base == strings.DONE_FINISHED.format(title=row.title)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: {store.item(i)["tier"] for i in ids} <= set(ls.CURRENT), 15)
    assert _watched(store, ids) == ids, "the marks stay"


@pytest.mark.parametrize("language", LANGUAGES)
def test_mark_all_watched_on_a_weekly_show_from_the_first_look_marks_them_and_only_offers_the_finish(real, monkeypatch,
                                                                                                   language):
    """Item 9 through the window: the show still airing stays in Current, every episode marked, the finish offered."""
    store, win, writer = _open(real, monkeypatch, language, lambda s: _show(language, s, [22, 15, 8, 1]))
    row = _row(win.page_widgets["current"].view_model, _SHOW[language])
    every = next(e for e in win.items.entries(row) if e.name == "watched-all")
    win.items.menu_pick(row, "watched-all", every.payload)
    ids = [e.id for e in row.episodes]
    assert wait_until(lambda: _watched(store, ids) == ids, 10)
    settle(300)
    assert {store.item(i)["tier"] for i in ids} <= set(ls.CURRENT), "never finished while it may still be airing"
    assert win.toasts.card.base == strings.DONE_ALL.format(n=4)
    assert win.toasts.card.buttons[1].text() == strings.DONE_MOVE_FINISHED


def test_mark_all_watched_is_not_offered_on_a_title_of_one_file_nor_once_every_file_is_watched(real, monkeypatch):
    store, win, writer = _open(real, monkeypatch, "ja", lambda s: _show("ja", s, [3, 2]))
    row = _row(win.page_widgets["current"].view_model, _SHOW["ja"])
    ids = [e.id for e in row.episodes]
    assert "watched-all" in [e.name for e in win.items.entries(row)]
    assert store.set_watched(ids) is not None
    assert wait_until(lambda: all(e.watched for e in _row(win.page_widgets["current"].view_model,
                                                             _SHOW["ja"]).episodes), 10)
    row = _row(win.page_widgets["current"].view_model, _SHOW["ja"])
    assert "watched-all" not in [e.name for e in win.items.entries(row)]
    one = row._replace(episodes=row.episodes[:1])
    assert "watched-all" not in [e.name for e in win.items.entries(one._replace(
        episodes=(one.episodes[0]._replace(watched=False),)))]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_corrected_original_copied_again_dates_the_copy_by_the_new_original(language):
    """S5's re-copy keeps the original's date too (`_checked_copy`): the corrected episode's copy is dated by the
    corrected original (newer than the copy it replaced, so the disk sync still sees it changed); the source folder
    untouched (`_look` proves it)."""
    store, src = _first_look(language, lambda s: _show(language, s, [9, 2]))
    show = _SHOW[language]
    with store:
        row = _row(_view(store, language), show)
        first = row.episodes[0]
        original = os.path.join(src, show, os.path.basename(first.rel_path))
        _write(original, _text(language, 1, extra="、修正版"), age=DAY)                  # corrected yesterday
        assert _look(store, language, store.a7_root, full=True)["recopied"] == 1
        copy = os.path.join(store.data_dir, first.rel_path)
        assert os.stat(copy).st_mtime_ns == os.stat(original).st_mtime_ns != first.disk


def test_one_files_own_date_known_among_several_reads_by_the_store_clock_alone():
    """A video still waiting for its subtitle has no date of its own: one date is no evidence (never a crash)."""
    now = time.time()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime(now - 30 * DAY))
    blank = view_rows.Episode._make([None] * len(view_rows.Episode._fields))
    eps = [blank._replace(id=1, added=stamp, disk=int((now - DAY) * 1e9)), blank._replace(id=2, added=stamp)]
    assert not view_rows.still_arriving(eps, now)


# --- done_many on the window seed (the fake writer: what is handed over) -------------------------------------------- #
from tests.qt.test_drag import SHOW_A, _all_but_one, _show_group, _shown_buttons, calls, world  # noqa: E402,F401


def test_done_many_hands_over_only_the_files_not_watched_yet_in_one_command_and_offers_nothing_while_some_are_left(
        world):
    seed, win, writer = world()
    i = next(n for n, r in enumerate(rows_of(win)) if len(r.episodes) >= 6 and not any(e.watched for e in r.episodes))
    row = rows_of(win)[i]
    seed.library.commit(items=[{"id": row.episodes[1].id, "watched": 1}])
    assert wait_until(lambda: rows_of(win)[i].episodes[1].watched, 3)
    row = rows_of(win)[i]
    win.moves.done_many(row, row.episodes[:4])                          # a menu's payload, one already watched
    assert calls(writer, "set_watched") == [("set_watched", [row.episodes[k].id for k in (0, 2, 3)], {"on": True})]
    assert win.toasts.card.base == strings.DONE_MANY.format(title=row.title, n=3)


def test_done_many_of_one_file_is_the_one_done_with_its_own_words(world):
    seed, win, writer = world()
    row = rows_of(win)[4]
    win.moves.done_many(row, row.episodes[:1])
    assert calls(writer, "set_watched") == [("set_watched", [row.episodes[0].id], {"on": True})]
    assert win.toasts.card.base != strings.DONE_MANY.format(title=row.title, n=1)
    assert row.episodes[0].label in win.toasts.card.base


def test_done_many_while_another_write_is_on_its_way_only_offers_the_finish(world):
    """The one Done's rule, `pending` included: a write still waiting (the store busy) — the view may not hold it."""
    seed, win, writer = world()
    row = _all_but_one(seed, win, 4)
    seed.library.commit(items=[{"id": e.id, "watched": 0} for e in row.episodes[:2]])
    assert wait_until(lambda: sum(e.watched for e in rows_of(win)[4].episodes) == len(row.episodes) - 3, 3)
    row = rows_of(win)[4]
    other = rows_of(win)[2]
    writer.stuck = True
    win.moves.done(other, other.episodes[other.next_index])
    assert win.moves.tickets
    win.moves.done_many(row, row.episodes)
    assert [c[0] for c in calls(writer)] == ["set_watched", "set_watched"]
    assert win.toasts.card.base == strings.DONE_ALL.format(n=len(row.episodes))
    writer.free()


def test_done_many_finishing_one_show_of_a_group_offers_that_shows_finish(world):
    """LM11b G5 through the mark-many: SHOW_A's three episodes marked at once, SHOW_B still waiting — *Move SHOW_A to
    Finished*, as the last of them done alone would offer."""
    seed, win, writer = world(apply=False)
    row = _show_group(win, a_watched=0, b_watched=0)
    a = [e for e in row.episodes if e.show == SHOW_A]
    assert len(a) == 3
    win.moves.done_many(row, a)
    assert calls(writer, "set_watched") == [("set_watched", [e.id for e in a], {"on": True})]
    card = win.toasts.card
    assert card.base == strings.DONE_SHOW_IN_GROUP.format(show=SHOW_A, n=3)
    assert _shown_buttons(card)[-1] == strings.DONE_MOVE_SHOW_FINISHED.format(show=SHOW_A)
