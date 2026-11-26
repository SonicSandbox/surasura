"""ONB-3, setup's *What are you watching right now?* (Sonic ~13:4x: "maybe by date"): its Qt-free rules in
`setup_wizard` — `watching_rows` (New arrivals' shows newest first by their own files' dates, the first eight),
`watching_search` (the store's own search over New arrivals) and `watching_place` (the pick to Current's top through
New arrivals' call; *I'm on* marks the episodes before it watched).

What a wrong answer would cost a learner:
  * the show he watches now buried among older ones — a first look stamps every file's `added_at` alike, so only the
    files' own dates tell them apart;
  * a show he can't find because it isn't among the first eight, or a search that offers a title already watched;
  * cards made for episodes he has already seen, or episodes marked watched when the pick never landed.

The real store in a temp library, filled by setup's own first look over a folder of real ja / zh subtitles from
tests/Test Resources/ (made-up show names); the writer's two calls are recorded stand-ins.
"""
import os
from types import SimpleNamespace

import pytest

from app import library_store as ls
from app import path_utils
from app.services import setup_wizard
from tests.test_library_store_support import library, write_manifest
from tests.test_sources_scan import _drive, _text, _write

SHOWS = {"ja": {"月影の旅人": 3, "星降る街の小さな工房": 2, "風鈴の街": 2},
         "zh": {"夜市小记": 3, "星夜小工坊": 2, "风铃街": 2}}
NEWEST_LAST = {"ja": ("風鈴の街", "月影の旅人", "星降る街の小さな工房"),       # (read in name order: the dates disagree)
               "zh": ("风铃街", "夜市小记", "星夜小工坊")}


@pytest.fixture(params=["ja", "zh"])
def language(request):
    data_dir, user_files_dir, doc = library(request.param, shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(request.param, data_dir, user_files_dir) == ls.EXIT_DONE
    return request.param


def _read(language, ages):
    """Each show's files written `ages[show]` seconds back (its later episodes newer), read by setup's first look ->
    the view's rows as New arrivals hands them: one per show, in the store's order, each with its episodes."""
    root = _drive(f"watching-{language}")
    n = 0
    for show, episodes in SHOWS[language].items():
        for e in range(1, episodes + 1):
            _write(os.path.join(root, show, f"{show} - {e:02d}.{language}.srt"), _text(language, n),
                   age=ages[show] + (episodes - e) * 10)
            n += 1
    got = setup_wizard.read_folders(language, [root])
    assert got.get("ids"), got
    store = ls.open_store(language, path_utils.get_data_path(language), path_utils.get_user_files_path(language))
    with store:
        items = store.conn.execute("SELECT id, rel_path, work_id FROM items WHERE tier = 'arrivals' "
                                   "ORDER BY ord, id").fetchall()
    rows = {}
    for i, rel, work in items:
        show = next(s for s in SHOWS[language] if s in rel)
        rows.setdefault(show, []).append((i, work))
    return [SimpleNamespace(key=f"w{ids[0][1]}", work_id=ids[0][1], item_ids=tuple(i for i, _w in ids), title=show,
                            group="new", episodes=tuple(SimpleNamespace(id=i, label=f"Ep {k}")
                                                        for k, (i, _w) in enumerate(ids, start=1)))
            for show, ids in rows.items()]


def _ages(language, newest_first):
    return {show: 100 + 1000 * n for n, show in enumerate(newest_first)}


def test_the_newest_show_by_its_files_comes_first_whatever_order_setup_read_them(language):
    newest_first = NEWEST_LAST[language]
    rows = _read(language, _ages(language, newest_first))
    assert [r.title for r in rows] != list(newest_first), "the store's order must disagree, or this proves nothing"
    got = setup_wizard.watching_rows(language, rows)
    assert [r.title for r in got] == list(newest_first)
    assert all(any(g is r for r in rows) for g in got)                  # the view's own rows, handed back


def test_only_the_first_eight_and_never_a_title_already_watched(language):
    rows = _read(language, _ages(language, NEWEST_LAST[language]))
    watched = rows[0]._replace(group="watched") if hasattr(rows[0], "_replace") else SimpleNamespace(
        **dict(vars(rows[0]), group="watched"))
    got = setup_wizard.watching_rows(language, [watched] + rows[1:], limit=1)
    assert len(got) == 1 and got[0].group == "new" and got[0].key != watched.key


def test_equal_dates_keep_the_trays_order_and_a_missing_store_still_gives_the_shows(language, monkeypatch):
    rows = _read(language, _ages(language, NEWEST_LAST[language]))
    monkeypatch.setattr(ls.Store, "file_times", lambda self, tier="arrivals": {i: 7 for r in rows for i in r.item_ids})
    assert [r.key for r in setup_wizard.watching_rows(language, rows)] == [r.key for r in rows]   # one date: as is
    monkeypatch.setattr(setup_wizard, "_window_store", lambda *_a, **_k: None)
    assert [r.key for r in setup_wizard.watching_rows(language, rows)] == [r.key for r in rows]


def test_no_shows_at_all_is_an_empty_page_never_an_error(language):
    assert setup_wizard.watching_rows(language, []) == []
    assert setup_wizard.watching_rows(language, None) == []
    assert setup_wizard.watching_search(language, [], "") == []


def test_the_search_finds_a_show_by_part_of_its_title_in_new_arrivals_only(language):
    rows = _read(language, _ages(language, NEWEST_LAST[language]))
    target = rows[-1]
    part = target.title[:2]
    got = setup_wizard.watching_search(language, rows, part)
    assert target in got and all(r.group == "new" for r in got)
    assert setup_wizard.watching_search(language, rows, "   ") == []
    assert setup_wizard.watching_search(language, rows, "まったく無関係なタイトルzzz") == []
    hidden = [SimpleNamespace(**dict(vars(r), group="watched")) if r is target else r for r in rows]
    assert all(r.key != target.key for r in setup_wizard.watching_search(language, hidden, part))


def test_the_pick_goes_to_the_top_and_only_the_episodes_before_his_are_marked_watched(language):
    rows = _read(language, _ages(language, NEWEST_LAST[language]))
    show = max(rows, key=lambda r: len(r.item_ids))                    # the show of three
    placed, watched = [], []
    last = setup_wizard.watching_place(lambda ids, where: placed.append((list(ids), where)) or 1,
                                       lambda ids: watched.append(list(ids)), show, episode=2)
    assert placed == [(list(show.item_ids), "top")]
    assert watched == [[ep.id for ep in show.episodes[:2]]]             # Ep 1 and 2 seen; he is on Ep 3
    assert last == show.item_ids[-1]                                    # the sort's Current picks go in under it
    placed.clear(), watched.clear()
    setup_wizard.watching_place(lambda ids, where: placed.append(where) or 1, watched.append, show, episode=0)
    assert placed == ["top"] and watched == [], "on episode 1: nothing marked"


def test_a_pick_the_writer_refused_marks_nothing_watched(language):
    rows = _read(language, _ages(language, NEWEST_LAST[language]))
    watched = []
    assert setup_wizard.watching_place(lambda ids, where: None, watched.append, rows[0], episode=1) is None
    assert watched == []
    assert setup_wizard.watching_place(lambda ids, where: 1, watched.append, SimpleNamespace(item_ids=()), 1) is None
