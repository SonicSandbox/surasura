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


def test_a_show_anilist_has_not_answered_for_yet_waits_with_its_reason():
    """Alpha 9 #JNFJ8Q (Chii Fuyo, still airing, every episode marked at once before AniList had answered): no answer
    yet for a show AniList can be asked about is never "nothing known" — it asks, and says why."""
    row = _row("p1", 1, 1, _at_once(3), title="夜明けの旅団")
    assert drag.when_done(_aired(_view([row]), 1, {"status": A.PENDING}), row, NOW) == \
        ("offer", strings.DONE_WHY_ASKING)
    assert drag.offer_text(("offer", strings.DONE_WHY_ASKING), row) == \
        "✓ All 3 watched · Still asking AniList whether it's airing — finished with it?"


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


def test_the_count_said_is_the_highest_numbered_file_never_the_number_of_files():
    """A special with no number beside Ep 1–12 (13 files): "you have up to 12"."""
    eps = _at_once(12) + _eps(None, 1, added=[NOW - 3 * DAY], start_id=50)
    row = _row("p1", 1, 1, eps)
    done = {"status": "FINISHED", "episodes": 24, "next_at": None, "asked_at": NOW}
    assert drag.when_done(_aired(_view([row]), 1, done), row, NOW) == ("offer", strings.DONE_WHY_MORE.format(n=24,
                                                                                                               m=12))


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
def test_today_s_other_holds_offer_as_today_with_no_anilist_reason(other):
    """AA-3: the reason is AniList's only when AniList alone held the show (the intent keeper's decision 2): kept
    studying, a write on its way, a file in New arrivals or Finished, a hole or a waiting video each asks as 3.0."""
    eps = _at_once(6)
    if other == "gap":
        eps = eps[:3] + eps[4:]
    if other == "waiting":
        eps = eps[:-1] + (NS(**{**vars(eps[-1]), "waiting": True}),)
    row = _row("p1", 1, 1, eps)
    view = _view([row], keep=other == "keep", arrivals=[NS(work_id=1)] if other == "arrivals" else (),
                 finished=[NS(work_id=1)] if other == "finished" else ())
    assert drag.when_done(view, row, NOW, pending=other == "pending") == ("offer",)
    assert drag.when_done(_aired(view, 1, RELEASING), row, NOW, pending=other == "pending") == ("offer",)
    assert drag.when_done(_aired(view, 1, {"status": "FINISHED", "episodes": 28}), row, NOW,
                          pending=other == "pending") == ("offer",)


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


def test_scenario_every_episode_marked_before_anilist_answered_stays_in_current():
    """Alpha 9 #JNFJ8Q: a show downloaded at once with its AniList id, the switch on, no answer kept yet (the ask goes
    out when a show is near its end, its answer a moment later behind the covers on one AniList budget): marking it all
    watched asks; with the switch off it finishes by itself as in 3.0."""
    names = [f"夜明けの旅団 第{k:02d}話.srt" for k in range(1, 4)]
    store, _src = _first_look("ja", lambda s: _from_sample(s, "夜明けの旅団", WEEKLY, names, [2] * 3))
    with store:
        row = _row_named(_store_view(store, "ja"), "夜明けの旅団")
        _id(store, row, 171018)
        view = _store_view(store, "ja")
        works = {w["id"]: w for w in store.read_feed()["works"]}
        now = time.time()
        asking = view._replace(airing=A.of_rows(view.rows, works, {}, asking=True))
        off = view._replace(airing=A.of_rows(view.rows, works, {}, asking=False))
        row = _all_watched(asking, _row_named(asking, "夜明けの旅団"))
        assert drag.when_done(asking, row, now) == ("offer", strings.DONE_WHY_ASKING)
        assert drag.when_done(off, row, now) == ("finish",)


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


class _Asker:
    on_change = None

    def want(self, ids):
        return 0

    def on(self):
        return True


def _marked_all_before_the_answer(world, aid):
    """⋯ *Mark all watched* on a show with AniList id `aid` whose answer hasn't come (the asker switched on)."""
    seed, win, writer = world()
    row = rows_of(win)[4]
    seed.library.commit(works=[{"id": row.work_id, "anilist_id": aid}])
    reader = win.services.library
    reader._airing_kept.shows()                     # (its path, under the test's local folder: nothing kept)
    reader.follow_airing(_Asker())
    reader.airing_moved()
    assert wait_until(lambda: win.page_widgets["current"].view_model.airing.get(row.work_id) == {"status": A.PENDING},
                      3)
    row = rows_of(win)[4]
    win.moves.done_many(row, list(row.episodes))
    return seed, win, writer, row


def test_window_mark_all_watched_before_anilist_answered_offers_and_writes_only_the_marks(world):
    """Alpha 9 #JNFJ8Q, the window's own path (⋯ *Mark all watched*, `done_many`): a show with an id whose answer
    hasn't come yet (the asker switched on) is marked watched and asked about — never moved to Finished."""
    from tests.qt.test_drag import calls
    _seed, win, writer, row = _marked_all_before_the_answer(world, 424243)
    assert [c[0] for c in calls(writer)] == ["set_watched"]
    assert win.toasts.card.base == strings.DONE_ALL_WHY.format(n=len(row.episodes), why=strings.DONE_WHY_ASKING)
    assert row.key in [r.key for r in rows_of(win)]


@pytest.mark.parametrize("answer, finishes", [("FINISHED", True), ("RELEASING", False)])
def test_window_a_show_offered_still_asking_is_asked_again_when_anilist_answers(world, answer, finishes):
    """Alpha 9 (review M1): the offer *Still asking AniList* waits for the answer, then L6.3's one rule runs again — an
    ended show (a whole season marked at once, which 3.0's dates finish) finishes by itself once AniList says so, as
    it would have without AniList; one still airing stays in Current with its offer. Never sooner, never twice."""
    from tests.qt.test_drag import calls
    _seed, win, writer, row = _marked_all_before_the_answer(world, 424244)
    assert wait_until(lambda: not win.moves.tickets, 3)
    reader = win.services.library
    A._write(reader._airing_kept.path, {"424244": {"status": answer, "episodes": len(row.episodes), "next_at": None,
                                                   "asked_at": time.time()}})
    reader.airing_moved()
    if finishes:
        assert wait_until(lambda: (settle() or True) and calls(writer, "set_tier"), 3)
        assert win.toasts.card.base == strings.DONE_FINISHED.format(title=row.title)
        assert len(calls(writer, "set_tier")) == 1
    else:
        assert wait_until(lambda: (settle() or True) and
                          (win.page_widgets["current"].view_model.airing.get(row.work_id) or {}).get("status") == answer,
                          3)
        settle(30)
        assert calls(writer, "set_tier") == [] and row.key in [r.key for r in rows_of(win)]
    assert not win.moves._airing_asking
    reader.airing_moved()                           # another view: nothing is asked again
    settle(30)
    assert len(calls(writer, "set_tier")) == (1 if finishes else 0)


@pytest.mark.parametrize("busy", ["store", "write", "drag"])
def test_window_an_answer_that_comes_while_the_window_is_busy_is_acted_on_at_a_later_view(world, busy):
    """Alpha 9 (review round 2, L-a / L-b / L-d): the answer lands while the store can't take a move, a write is on its
    way or a drag runs — nothing finishes then and nothing is said on the bar; the show stays asked about, and the next
    view (the busy spell over) finishes it by itself."""
    from tests.qt.test_drag import calls
    _seed, win, writer, row = _marked_all_before_the_answer(world, 424246)
    assert wait_until(lambda: not win.moves.tickets, 3)
    said = []
    win.moves.say = said.append
    ticket = drag.Ticket("…")
    if busy == "store":
        writer.writable = False
    elif busy == "write":
        win.moves.tickets.append(ticket)
    else:
        win.moves.running = object()
    reader = win.services.library
    A._write(reader._airing_kept.path, {"424246": {"status": "FINISHED", "episodes": len(row.episodes),
                                                   "next_at": None, "asked_at": time.time()}})
    reader.airing_moved()
    if busy == "drag":                              # a drag holds every view: the answer is read, never shown
        assert wait_until(lambda: (settle() or True) and win.moves._airing_again is False and
                          (getattr(win.moves.held, "airing", None) or {}).get(row.work_id, {}).get("status") ==
                          "FINISHED", 3)
    else:                                           # shown: the window's view carries the answer
        assert wait_until(lambda: (settle() or True) and
                          (win.page_widgets["current"].view_model.airing.get(row.work_id) or {}).get("status") ==
                          "FINISHED", 3)
    settle(30)
    assert calls(writer, "set_tier") == [] and said == [] and row.work_id in win.moves._airing_asking
    writer.writable = True
    if ticket in win.moves.tickets:
        win.moves.tickets.remove(ticket)
    win.moves.running = None
    reader.airing_moved()                           # the next view
    assert wait_until(lambda: (settle() or True) and calls(writer, "set_tier"), 3)
    assert not win.moves._airing_asking


def test_window_two_shows_still_asking_each_waits_for_its_own_answer(world):
    """Review round 2 (mutant D6): one show's answer coming never lets go another still being asked about — it finishes
    by itself only at its own answer."""
    from tests.qt.test_drag import calls
    seed, win, writer, row = _marked_all_before_the_answer(world, 424249)
    others = [r for r in rows_of(win) if r.key != row.key and r.work_id not in (None, row.work_id) and not r.group]
    seed.library.commit(works=[{"id": row.work_id, "anilist_id": 424249}] +
                        [{"id": r.work_id, "anilist_id": 424250 + n} for n, r in enumerate(others)])
    win.services.library.airing_moved()
    assert wait_until(lambda: (settle() or True) and all(
        win.page_widgets["current"].view_model.airing.get(r.work_id) == {"status": A.PENDING} for r in others), 3)
    view = win.page_widgets["current"].view_model
    n, other = next((n, r) for n, r in enumerate(others)       # one the dates would finish: AniList alone holds it
                    if drag.when_done(view, r._replace(episodes=tuple(e._replace(watched=True) for e in r.episodes)))
                    == ("offer", strings.DONE_WHY_ASKING))
    other = next(r for r in rows_of(win) if r.key == other.key)
    assert wait_until(lambda: not win.moves.tickets, 3)
    win.moves.done_many(other, list(other.episodes))
    assert set(win.moves._airing_asking) == {row.work_id, other.work_id}
    assert wait_until(lambda: not win.moves.tickets, 3)
    reader = win.services.library
    entry = {"status": "FINISHED", "next_at": None, "asked_at": time.time()}
    A._write(reader._airing_kept.path, {"424249": dict(entry, episodes=len(row.episodes))})
    reader.airing_moved()
    assert wait_until(lambda: (settle() or True) and len(calls(writer, "set_tier")) == 1, 3)
    assert set(win.moves._airing_asking) == {other.work_id}
    A._write(reader._airing_kept.path, {"424249": dict(entry, episodes=len(row.episodes)),
                                        str(424250 + n): dict(entry, episodes=len(other.episodes))})
    reader.airing_moved()
    assert wait_until(lambda: (settle() or True) and len(calls(writer, "set_tier")) == 2, 3)
    assert not win.moves._airing_asking


def test_window_a_held_view_shown_later_as_the_window_s_own_still_brings_its_answer(world):
    """Review round 2 (L-a): a reader's view held while the window's order was ahead is shown later as the window's own
    (`view_in`'s first return) — its answer is still read, so the show waits for no further view."""
    _seed, win, _writer, row = _marked_all_before_the_answer(world, 424248)
    view = win.moves.page.view_model._replace(airing={row.work_id: {"status": "FINISHED"}})
    win.moves._own = True
    try:
        assert win.moves.view_in(view) is view
    finally:
        win.moves._own = False
    assert win.moves._airing_again


def test_window_move_to_finished_pressed_on_the_offer_is_never_asked_again(world):
    """Review round 2 (L-c): *Move to Finished* on the *Still asking* offer ends the asking — an Undo of that move,
    then the answer, never finishes the show by itself against the learner's Undo."""
    _seed, win, _writer, row = _marked_all_before_the_answer(world, 424247)
    assert row.work_id in win.moves._airing_asking
    win.moves.to_finished(row)
    assert row.work_id not in win.moves._airing_asking


def test_window_a_show_sent_to_finished_by_a_pick_is_never_asked_again(world):
    """Review round 3 (M): every way to Finished ends the asking — the picks' / a drag's Finished (`_finish`) too, so an
    Undo of it, then the answer, never finishes the show by itself."""
    _seed, win, _writer, row = _marked_all_before_the_answer(world, 424251)
    assert wait_until(lambda: not win.moves.tickets, 3)
    win.moves.send_picks("finished", drag.ids_of(row), 1, keys=(row.key,))
    assert row.work_id not in win.moves._airing_asking


def test_window_the_mark_undone_then_the_answer_finishes_nothing(world):
    """Review round 3 (H): *Mark all watched* undone after the *Still asking* offer — AniList's "ended" answer then
    never finishes a show with files to watch (`when_done` reads every file watched: the caller checks)."""
    from tests.qt.test_drag import calls
    _seed, win, writer, row = _marked_all_before_the_answer(world, 424252)
    assert wait_until(lambda: not win.moves.tickets, 3)
    win.moves.undo(win.moves.toasted)
    assert wait_until(lambda: (settle() or True) and not win.moves.tickets and
                      not all(e.watched for e in next(r for r in rows_of(win) if r.key == row.key).episodes), 3)
    reader = win.services.library
    A._write(reader._airing_kept.path, {"424252": {"status": "FINISHED", "episodes": len(row.episodes),
                                                   "next_at": None, "asked_at": time.time()}})
    reader.airing_moved()
    assert wait_until(lambda: (settle() or True) and
                      (win.page_widgets["current"].view_model.airing.get(row.work_id) or {}).get("status") ==
                      "FINISHED", 3)
    settle(30)
    assert calls(writer, "set_tier") == [] and not win.moves._airing_asking


def test_window_closed_nothing_is_asked_again(world):
    """Review round 3 (L): the controller let go (a close, a language switch) asks nothing again — no finish past it."""
    _seed, win, _writer, row = _marked_all_before_the_answer(world, 424253)
    win.moves.close()
    assert not win.moves._airing_asking
    win.moves._airing_asking[-1] = "gone"           # (one left over, its show gone: `_again` still touches nothing)
    win.moves._again()
    assert win.moves._airing_asking == {-1: "gone"}


def test_window_download_covers_switched_builds_the_airing_answers_again(world):
    """Review L1: AniList's *Still asking* follows the covers switch — a write of `covers_download` asks the reader for
    a view with the airing answers read again (switched off: no show waits for an answer that will never come)."""
    _seed, win, _writer = world()
    reader = win.services.library
    moved = []
    reader.airing_moved = lambda: moved.append(1)
    win._settings_written(["app_motion"])
    assert moved == []
    win._settings_written(["covers_download"])
    assert moved == [1]


def test_window_with_the_switch_turned_off_before_the_answer_nothing_finishes_by_itself(world):
    """Alpha 9 (review M1): no answer will come (Download covers turned off) — the offer stands, AniList's absence
    never finishes a show; the show is let go."""
    from tests.qt.test_drag import calls
    _seed, win, writer, row = _marked_all_before_the_answer(world, 424245)
    reader = win.services.library
    reader.follow_airing(None)                      # no asker: `asking` False, the PENDING entry goes
    reader.airing_moved()
    assert wait_until(lambda: (settle() or True) and
                      row.work_id not in (win.page_widgets["current"].view_model.airing or {}), 3)
    settle(30)
    assert calls(writer, "set_tier") == [] and not win.moves._airing_asking
