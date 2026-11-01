"""A show still airing never finishes by itself (3.0.1 item 5): AniList's kept answer (`View.airing`, from
`app/services/airing.py`) into L6.3's one rule, `drag.when_done` — spec: the planning folder's
`tracks/books/work/airing/SPEC.md` §3, §7.4–7.5, §11 (A5, AA-3 PROVISIONAL).

What a wrong answer would cost a learner:
  * a season downloaded at once, still airing, leaving Current the moment they catch up (Tempal's case, by the dates);
  * AniList's "finished" finishing a show SOONER than 3.0 — a weekly show the dates still hold, or a two-season folder
    under season 1's id (F1: AniList only ever holds back, never releases);
  * an ended show with episodes still to come (AniList lists 28; they have up to 24) finishing by itself;
  * the offer with no word of why, read as a bug (AA-3); a film or a show with no AniList answer acting otherwise than
    in 3.0.

The rule is pure (the views as `test_l63_finishing` builds them). The scenarios run on a real store set up by a first
look at a source folder, its files the subtitle samples in tests/Test Resources/ja/airing/ (`第N話`, `SxxEyy`, a film,
a two-season folder), each dated as it came in; AniList's answers are hand-written in the API's shape.
"""
import os
import time
from types import SimpleNamespace as NS

import pytest

from app.qt import drag, strings
from app.services import airing as A
from app.services import view_rows
from tests.test_sources_scan import RESOURCES
from tests.qt.test_a7_finish_mark import _first_look, _row as _row_named, _view as _store_view
from tests.qt.test_drag import _all_but_one, real, rows_of, settle, wait_until, world  # noqa: F401
from tests.qt.test_l63_finishing import DAY, NOW, _eps, _row, _view
from tests.test_sources_scan import _write

SAMPLES = os.path.join(RESOURCES, "ja", "airing")
WEEKLY = "夜明けの旅団 第01話.srt"
SEASON = "Hoshikuzu Station S01E01.ja.srt"
FILM = "劇場版 夜明けの旅団 遥かなる海へ.srt"


def _aired(view, work, entry):
    view.airing = {work: entry}
    return view


def _at_once(n):
    return _eps(1, n, added=[NOW - 3 * DAY + k * 60 for k in range(n)])          # a season downloaded at once


def _weekly(n, last_days=5):
    return _eps(1, n, added=[NOW - 40 * DAY] * (n - 1) + [NOW - last_days * DAY])  # the newest on its own lately


RELEASING = {"status": "RELEASING", "episodes": 12, "next_at": None, "asked_at": NOW}


# --- the rule: AniList only holds back -------------------------------------------------------------------------- #
def test_releasing_holds_a_season_downloaded_at_once_with_its_reason():
    row = _row("p1", 1, 1, _at_once(8), title="夜明けの旅団")
    assert drag.when_done(_view([row]), row, NOW) == ("finish",), "3.0: the dates let it go"
    assert drag.when_done(_aired(_view([row]), 1, RELEASING), row, NOW) == ("offer", strings.DONE_WHY_AIRING)


@pytest.mark.parametrize("status", ["RELEASING", "NOT_YET_RELEASED", "HIATUS"])     # AniList's own names
def test_every_airing_status_holds(status):
    row = _row("p1", 1, 1, _at_once(4))
    assert drag.when_done(_aired(_view([row]), 1, {"status": status}), row, NOW)[0] == "offer"


def test_finished_never_releases_a_show_the_dates_hold():
    """F1: a weekly show whose newest episode came on its own lately asks in 3.0 — AniList's "finished" changes
    nothing (no reason given: the dates asked, not AniList)."""
    row = _row("p1", 1, 1, _weekly(12))
    done = {"status": "FINISHED", "episodes": 12, "next_at": None, "asked_at": NOW}
    assert drag.when_done(_view([row]), row, NOW) == ("offer",)
    assert drag.when_done(_aired(_view([row]), 1, done), row, NOW) == ("offer",)


def test_finished_with_every_episode_that_came_together_still_finishes_as_in_3_0():
    row = _row("p1", 1, 1, _at_once(12))
    done = {"status": "FINISHED", "episodes": 12, "next_at": None, "asked_at": NOW}
    assert drag.when_done(_aired(_view([row]), 1, done), row, NOW) == ("finish",)


def test_fewer_files_than_anilist_lists_asks_with_the_counts():
    row = _row("p1", 1, 1, _at_once(24))
    done = {"status": "FINISHED", "episodes": 28, "next_at": None, "asked_at": NOW}
    verdict = drag.when_done(_aired(_view([row]), 1, done), row, NOW)
    assert verdict == ("offer", strings.DONE_WHY_MORE.format(n=28, m=24))
    assert drag.offer_text(verdict, row) == strings.DONE_ALL_WHY.format(n=24, why="AniList lists 28 episodes; you "
                                                                                   "have up to 24")


def test_another_work_s_answer_or_none_leaves_the_dates_to_decide():
    row = _row("p1", 1, 1, _at_once(6))
    assert drag.when_done(_aired(_view([row]), 2, RELEASING), row, NOW) == ("finish",)
    assert drag.when_done(_aired(_view([row]), 1, None), row, NOW) == ("finish",)
    assert not hasattr(_view([row]), "airing")
    assert drag.when_done(_view([row]), row, NOW) == ("finish",), "a view with no airing field: as 3.0"


def test_a_film_finishes_unless_anilist_says_it_is_still_to_air():
    row = _row("p1", 1, 1, _eps(None, 1, added=[NOW - DAY]), title="劇場版 夜明けの旅団", media="film")
    film = {"status": "FINISHED", "episodes": 1, "next_at": None, "asked_at": NOW}
    assert drag.when_done(_aired(_view([row]), 1, film), row, NOW) == ("finish",), "no numbered file: never short"


@pytest.mark.parametrize("other", ["keep", "pending", "arrivals", "finished", "gap", "waiting"])
def test_today_s_other_holds_still_offer_and_say_anilist_s_why_alongside(other):
    eps = _at_once(6)
    if other == "gap":
        eps = eps[:3] + eps[4:]
    if other == "waiting":
        eps = eps[:-1] + (NS(**{**vars(eps[-1]), "waiting": True}),)
    row = _row("p1", 1, 1, eps)
    view = _view([row], keep=other == "keep", arrivals=[NS(work_id=1)] if other == "arrivals" else (),
                 finished=[NS(work_id=1)] if other == "finished" else ())
    assert drag.when_done(view, row, NOW, pending=other == "pending") == ("offer",)
    assert drag.when_done(_aired(view, 1, RELEASING), row, NOW, pending=other == "pending") == \
        ("offer", strings.DONE_WHY_AIRING)


def test_a_join_or_a_cached_view_is_never_touched_by_anilist():
    first = _row("p1", 1, 1, _eps(1, 6), index=0)
    second = _row("p2", 1, 2, _eps(7, 6, watched=False, start_id=7), index=1)
    view = _aired(_view([first, second]), 1, RELEASING)
    assert drag.when_done(view, first, NOW)[0] == "join"
    row = _row("p1", 1, 1, _at_once(4))
    assert drag.when_done(_aired(_view([row], cached=True), 1, RELEASING), row, NOW) == ("offer",)


def test_the_offer_text_without_a_reason_is_today_s():
    row = _row("p1", 1, 1, _at_once(4))
    assert drag.offer_text(("offer",), row) == strings.DONE_ALL.format(n=4)
    assert drag.offer_text(("offer", strings.DONE_WHY_AIRING), row) == \
        "✓ All 4 watched · Still airing (AniList) — finished with it?"


# --- the scenarios: a real store, set up by a first look ------------------------------------------------------- #
def _from_sample(src, folder, sample, names, ages):
    """`names` episodes of `folder` in the source, each the subtitle sample `sample`'s text (its number added: one
    file each), episode k's original dated `ages[k]` days back."""
    with open(os.path.join(SAMPLES, sample), encoding="utf-8") as f:
        text = f.read()
    for name, age in zip(names, ages):
        path = _write(os.path.join(src, *folder.split("/"), name), text + f"\n{name}\n", age=age * DAY)
        os.utime(path, ns=(time.time_ns(), os.stat(path).st_mtime_ns))


def _id(store, row, anilist_id):
    """The work gets its AniList id as an import gives it (`works.anilist_id`)."""
    with store._command("test_ids", "sync") as cmd:
        store.conn.execute("UPDATE works SET anilist_id = ? WHERE id = ?", (anilist_id, row.work_id))
        cmd.touch()


def _all_watched(view, row):
    return view_rows.Row._make(row)._replace(episodes=tuple(e._replace(watched=True) for e in row.episodes))


def _with(store, row, entry):
    """The view as the reader builds it with the kept answers (`airing.of_rows`)."""
    view = _store_view(store, "ja")
    works = {w["id"]: w for w in store.read_feed()["works"]}
    return view._replace(airing=A.of_rows(view.rows, works, {str(k): v for k, v in entry.items()}))


def test_scenario_a_season_downloaded_at_once_and_still_airing_stays_in_current():
    names = [f"夜明けの旅団 第{k:02d}話.srt" for k in range(1, 5)]
    store, _src = _first_look("ja", lambda s: _from_sample(s, "夜明けの旅団", WEEKLY, names, [2] * 4))
    with store:
        row = _row_named(_store_view(store, "ja"), "夜明けの旅団")
        _id(store, row, 171018)
        now = time.time()
        view = _with(store, row, {171018: {"status": "RELEASING", "episodes": 12, "next_at": now + 3 * DAY,
                                           "asked_at": now}})
        row = _all_watched(view, _row_named(view, "夜明けの旅団"))
        assert drag.when_done(_store_view(store, "ja"), row, now) == ("finish",), "3.0 finished it (Tempal)"
        assert drag.when_done(view, row, now) == ("offer", strings.DONE_WHY_AIRING)


def test_scenario_an_ended_show_with_episodes_still_to_come_asks():
    names = [f"Hoshikuzu Station S01E{k:02d}.ja.srt" for k in range(1, 25)]
    store, _src = _first_look("ja", lambda s: _from_sample(s, "Hoshikuzu Station", SEASON, names, [2] * 24))
    with store:
        row = _row_named(_store_view(store, "ja"), "Hoshikuzu Station")
        assert max(e.number for e in row.episodes) == 24
        store.set_cover(row.work_id, "anilist", ref="98765", path="cache:ja-anilist-98765.jpg")   # A8: a found cover
        now = time.time()
        view = _with(store, row, {98765: {"status": "FINISHED", "episodes": 28, "next_at": None, "asked_at": now}})
        row = _all_watched(view, _row_named(view, "Hoshikuzu Station"))
        assert drag.when_done(view, row, now) == ("offer", strings.DONE_WHY_MORE.format(n=28, m=24))


def test_scenario_a_two_season_folder_under_season_one_s_id_behaves_as_in_3_0():
    """§8: the search gave season 1's id (FINISHED, 12 episodes); the folder holds S1 and S2 numbered 1–24 — not short,
    not airing: the dates decide, exactly as 3.0 (here: a weekly S2, so it asks; never sooner)."""
    s1 = [f"Season 1/Hoshikuzu Station S01E{k:02d}.ja.srt" for k in range(1, 13)]
    s2 = [f"Season 2/Hoshikuzu Station S02E{k:02d}.ja.srt" for k in range(13, 25)]
    ages = [200] * 12 + [90 - 7 * k for k in range(11)] + [3]
    store, _src = _first_look("ja", lambda s: _from_sample(s, "Hoshikuzu Station", SEASON, s1 + s2, ages))
    with store:
        view = _store_view(store, "ja")
        rows_ = [r for r in view.rows if r.title and "Hoshikuzu" in r.title]
        assert rows_
        now = time.time()
        _id(store, rows_[0], 55555)
        view = _with(store, rows_[0], {55555: {"status": "FINISHED", "episodes": 12, "next_at": None,
                                               "asked_at": now}})
        for row in [r for r in view.rows if r.title and "Hoshikuzu" in r.title]:
            row = _all_watched(view, row)
            assert A.holds(view.airing.get(row.work_id), row.episodes) is None
            assert drag.when_done(view, row, now) == drag.when_done(view._replace(airing={}), row, now), \
                "AniList's season-1 answer changes nothing"


def test_scenario_no_id_or_no_answer_behaves_as_today():
    names = [f"夜明けの旅団 第{k:02d}話.srt" for k in range(1, 5)]
    store, _src = _first_look("ja", lambda s: _from_sample(s, "夜明けの旅団", WEEKLY, names, [2] * 4))
    with store:
        view = _with(store, None, {171018: RELEASING})       # an answer for an id no work has
        row = _all_watched(view, _row_named(view, "夜明けの旅団"))
        assert view.airing == {}
        assert drag.when_done(view, row, time.time()) == ("finish",)


def test_scenario_a_film_finishes_by_itself_as_today():
    store, _src = _first_look("ja", lambda s: _from_sample(s, "劇場版 夜明けの旅団", FILM, [FILM], [1]))
    with store:
        row = _row_named(_store_view(store, "ja"), "劇場版 夜明けの旅団")
        _id(store, row, 171019)
        now = time.time()
        view = _with(store, row, {171019: {"status": "FINISHED", "episodes": 1, "next_at": None, "asked_at": now}})
        row = _all_watched(view, _row_named(view, "劇場版 夜明けの旅団"))
        assert drag.when_done(view, row, now) == ("finish",)


# --- the window: the toast says why ----------------------------------------------------------------------------- #
def test_window_the_last_done_of_a_show_anilist_holds_offers_with_its_reason_and_writes_only_the_mark(world):
    from tests.qt.test_drag import calls
    seed, win, writer = world()
    row = _all_but_one(seed, win, 4)
    seed.library.commit(works=[{"id": row.work_id, "anilist_id": 424242}])
    reader = win.services.library
    reader._airing_kept.shows()                     # (its path, under the test's local folder)
    A._write(reader._airing_kept.path,
             {"424242": {"status": "RELEASING", "episodes": 24, "next_at": None, "asked_at": time.time()}})
    reader.airing_moved()
    assert wait_until(lambda: win.page_widgets["current"].view_model.airing.get(row.work_id), 3)
    row = rows_of(win)[4]
    win.moves.done(row, row.episodes[-1])
    assert [c[0] for c in calls(writer)] == ["set_watched"]
    assert win.toasts.card.base == strings.DONE_ALL_WHY.format(n=len(row.episodes), why=strings.DONE_WHY_AIRING)
