"""A show's episodes moved into Current one at a time keep their episode order (Kura-EO; adapted from Mattias's #482).

Why these matter: a show's episodes come into New arrivals one by one — the browser extension hands over each Netflix
episode as it is watched, an airing show brings one a week — and the learner moves each into Current: the tray's *Top*,
a drop on the show's row, a 6+ Months episode's *Up next*. *Top* put each at the top of NOW and a drop on the row's
upper half put it above the row's first episode, so episode 9 went above 8 and 10 above 9: the show read 10, 9, 8.
`after-show` already read the order (the records' season and episode); now a move of ONE title's items into Current
takes it too (`Store._into_show`) — unless the learner chose the spot (a drop away from the title's rows, or between two
of them). What must not change: another title's rows, an item whose order can't be read (a channel's video: still the
top), a move inside Current, *Soon* staying below the Soon line, *Put back*'s top, seasons apart, and Undo (the move's
own). Every test runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, with real words from
tests/Test Resources/.
"""

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, names, pieces_ok, roots, touch


def _episode(store, language, show, n, season=1, title=None):
    """One episode as the browser extension hands it over (`producer` browser; the show's title, season and episode in
    the record's `show`), registered into New arrivals. -> its item id."""
    data_dir, _u = roots(language)
    video = str(81903033 + 100 * season + n)
    rel = f"{ls.PROCESSED_FOLDER}/{show} S{season:02d}E{n:02d} {title or show} [netflix-{video}].txt"
    record = {"schema": 1, "producer": "browser", "language": language, "content_key": f"netflix:{video}",
              "video_id": video, "title": title or show, "show": {"title": show, "season": season, "episode": n}}
    item = store.register(touch(data_dir, rel, f"{show} {season} {n}\n"), record).added[0]
    assert store.item(item)["tier"] == "arrivals", "the setup: it waits in New arrivals"
    return item


def _current(store):
    return store.ids("now") + store.ids("soon")


def _others(store, eps):
    return [i for i in _current(store) if i not in eps]


@pytest.mark.parametrize("language", LANGUAGES)
def test_episodes_8_9_10_moved_in_one_at_a_time_read_8_9_10_in_one_row(language):
    """The report: 8 into Current, then 9, then 10 — *Top*, *Top*, a drop on the show's row's upper half (before 8) —
    read 8, 9, 10 in one row, never 10, 9, 8. No other title's row moves; the change says it went to the show's order
    (the window's writer follows the store then); each Undo puts its episode back in New arrivals."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[140]
    ep8 = _episode(store, language, show, 8, title=w[141])
    first = store.place([ep8], "top")
    assert store.ids("now")[0] == ep8 and first.show_order is False, "nothing of its show there yet: the top"
    others = _others(store, {ep8})

    ep9 = _episode(store, language, show, 9, title=w[142])
    before = _current(store)
    nine = store.place([ep9], "top")
    assert store.ids("now")[:2] == [ep8, ep9], "after episode 8, never above it"
    assert nine.show_order is True
    assert _others(store, {ep8, ep9}) == others

    ep10 = _episode(store, language, show, 10, title=w[143])
    ten = store.move([ep10], "now", before_id=ep8)         # the tray's drop on the show's row: its upper half
    assert store.ids("now")[:3] == [ep8, ep9, ep10]
    assert _others(store, {ep8, ep9, ep10}) == others, "another title's rows never move"
    assert pieces_ok(store) is None
    assert len({store.item(i)["piece_id"] for i in (ep8, ep9, ep10)}) == 1, "one row, in episode order"

    store.undo(ten)
    assert store.item(ep10)["tier"] == "arrivals" and store.ids("now")[:2] == [ep8, ep9]
    store.undo(nine)
    assert store.item(ep9)["tier"] == "arrivals" and _current(store) == before
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_drop_on_the_rows_lower_edge_takes_the_episode_order_too(language):
    """The lower half of the show's row (after its last episode): episode 7 dropped there goes before 8 — the row is the
    show drawn as one, so no order inside it is chosen by a drop at its edge."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[150]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep9 = _episode(store, language, show, 9)
    store.place([ep9], "top")
    ep7 = _episode(store, language, show, 7)
    store.move([ep7], "now", after_id=ep9)
    assert store.ids("now")[:3] == [ep7, ep8, ep9]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_earlier_episode_goes_before_and_soon_follows_its_show_in_soon(language):
    """Before the lowest higher episode when only later ones are there (7 before 8), in the show's tier: *Top* of 7
    while the show sits in Soon lands in Soon before 8; *Soon* of 9 lands after 8 there, not at Soon's top."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[144]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "soon")
    soon_top = store.ids("soon").index(ep8)
    ep7 = _episode(store, language, show, 7)
    store.place([ep7], "top")
    soon = store.ids("soon")
    assert store.item(ep7)["tier"] == "soon" and soon.index(ep7) + 1 == soon.index(ep8), "before episode 8"
    ep9 = _episode(store, language, show, 9)
    store.place([ep9], "soon")
    soon = store.ids("soon")
    assert soon[soon.index(ep8) + 1] == ep9 and soon.index(ep7) == soon_top
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_soon_never_lands_above_the_soon_line_for_its_show(language):
    """*Soon* is the learner's "not now": with the show in NOW, the next episode's *Soon* stays at Soon's top (its
    order's place would be in NOW, above the line) — as before."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[151]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep9 = _episode(store, language, show, 9)
    change = store.place([ep9], "soon")
    assert store.item(ep9)["tier"] == "soon" and store.ids("soon")[0] == ep9 and change.show_order is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_drop_on_the_soon_well_beside_its_show_stays_below_the_soon_line(language):
    """(The review's finding: an anchored move to Soon.) Episode 7 leads NOW and 9 leads Soon; episode 8 dropped at
    Soon's top, on 9's row's edge, is the learner's "Soon": it stays there, before 9 — never pulled up into NOW after
    7, where the episode order alone would put it."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[155]
    ep7 = _episode(store, language, show, 7)
    store.place([ep7], "top")
    ep9 = _episode(store, language, show, 9)
    store.place([ep9], "soon")
    assert store.ids("now")[0] == ep7 and store.ids("soon")[0] == ep9, "the setup"
    ep8 = _episode(store, language, show, 8)
    change = store.move([ep8], "soon", before_id=ep9)
    assert store.ids("soon")[:2] == [ep8, ep9] and store.ids("now")[0] == ep7 and change.show_order is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_programs_named_place_is_kept_and_its_rule_target_takes_the_order(language):
    """`surasura-cli place --position` names an exact place (Connect's `library.place` with an anchor): kept, even
    at the edge of the show's row. Without one (a placing rule's target, `--to current`), the episode order."""
    from app.connect import library
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[156]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep9 = _episode(store, language, show, 9)
    library.place(store, ep9, "now", before_id=ep8, source="hato")
    assert store.ids("now")[:2] == [ep9, ep8], "the program's own place"
    ep10 = _episode(store, language, show, 10)
    library.place(store, ep10, "now", source="hato")
    assert store.ids("now")[:3] == [ep9, ep10, ep8], "after its highest lower episode (9, where the program put it)"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unreadable_record_never_fails_the_move_it_goes_where_asked(language):
    """Every move into Current reads the moved item's record now: one that can't be read (a cut-off write, not JSON)
    is no episode — the move goes where it was asked (the top), never an error."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[157]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep9 = _episode(store, language, show, 9)
    with store._writing():
        store.conn.execute("UPDATE pairings SET pairing = ? WHERE item_id = ?", ('{"schema": 1, "show": {', ep9))
    assert store.place([ep9], "top") is not None
    assert store.ids("now")[:2] == [ep9, ep8]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_drop_at_a_chosen_spot_stays_where_it_was_dropped(language):
    """The learner's own spot is kept: a drop away from the show's rows (between two other titles) stays there, and so
    does a drop between two of the show's own episodes (11 dropped between 8 and 10). Undo puts it back."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[145]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep10 = _episode(store, language, show, 10)
    store.place([ep10], "top")
    assert store.ids("now")[:2] == [ep8, ep10]
    now = store.ids("now")
    away = now[3]                                    # another title's row, two rows below the show
    assert store.item(away)["work_id"] != store.item(ep8)["work_id"]
    assert store.item(now[4])["work_id"] != store.item(ep8)["work_id"]
    ep9 = _episode(store, language, show, 9)
    there = store.move([ep9], "now", after_id=away)
    now = store.ids("now")
    assert now[now.index(away) + 1] == ep9 and there.show_order is False, "away from its show: where it was dropped"
    store.undo(there)
    assert store.item(ep9)["tier"] == "arrivals" and store.ids("now")[:2] == [ep8, ep10]
    ep11 = _episode(store, language, show, 11)
    store.move([ep11], "now", before_id=ep10)        # between two of the show's own episodes
    assert store.ids("now")[:3] == [ep8, ep11, ep10]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_6_months_episode_moved_up_joins_its_show_and_a_put_back_keeps_the_top(language):
    """An airing show's next episode parked in 6+ Months, then *Up next* (a move to NOW, no anchor: search's, Goal's
    sheet) goes after its show's episode in Current. *Put back* from Finished keeps its promise (back at the top of
    Current, its own toast says so): never redirected."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[152]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep9 = _episode(store, language, show, 9)
    store.move([ep9], "goal")
    assert store.item(ep9)["tier"] == "goal", "the setup: it waits in 6+ Months"
    up = store.move([ep9], "now")
    assert store.ids("now")[:2] == [ep8, ep9] and up.show_order is True
    store.undo(up)
    assert store.item(ep9)["tier"] == "goal"
    ep7 = _episode(store, language, show, 7)
    store.finish([ep7])
    assert store.item(ep7)["tier"] == "graduated"
    store.put_back_finished([ep7])
    assert store.ids("now")[:2] == [ep7, ep8]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_seasons_episode_is_another_shows_and_goes_to_the_top(language):
    """Seasons stay apart (`after-show`'s own reading): season 2's first episode is no neighbour of season 1's 8 and
    9 — *Top* puts it at the top, and season 1 keeps its order below it."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[153]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep9 = _episode(store, language, show, 9)
    store.place([ep9], "top")
    s2 = _episode(store, language, show, 1, season=2)
    store.place([s2], "top")
    assert store.ids("now")[:3] == [s2, ep8, ep9]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_whose_order_cant_be_read_still_goes_to_the_top(language):
    """No episode number, no list place (a channel's single video): *Top* is still the top of Current, above its
    channel's video there — and a move inside Current is never redirected (episode 9 moved above 8 stays there)."""
    store = migrated(language, shows=2, episodes=3)
    data_dir, _u = roots(language)
    w = names(language)
    channel = w[146]

    def video(vid, word):
        record = {"schema": 1, "producer": "youtube", "language": language, "media_type": "youtube",
                  "content_key": f"youtube:{vid}", "video_id": vid, "title": word, "channel_id": channel,
                  "show": {"title": channel}}
        return store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{channel} - {word} [{vid}].txt"),
                              record).added[0]
    first = video("pitFobM6z80", w[147])
    store.place([first], "top")
    second = video("IIqUltT_x0c", w[148])
    store.place([second], "top")
    assert store.ids("now")[:2] == [second, first]
    show = w[149]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep9 = _episode(store, language, show, 9)
    store.place([ep9], "top")
    assert store.ids("now")[:2] == [ep8, ep9]
    store.move([ep9], "now", before_id=ep8)          # inside Current: the learner's own order
    assert store.ids("now")[:2] == [ep9, ep8]
    assert pieces_ok(store) is None
    store.close()


def test_is_any_of_the_title_in_current_goes_by_the_titles_index_never_a_walk_through_current():
    """Kura-PR2's B1 rule for every title read on a move's path: the check runs inside each move into Current (the
    write lock held), so it reads the title's index (items_work), never Current's order index — a 20k library's
    NOW is never walked for it."""
    from tests.test_library_store_support import big_store
    store = big_store("ja", 200)
    plan = " ".join(r[-1] for r in store.conn.execute("EXPLAIN QUERY PLAN " + ls.SHOW_IN_CURRENT_SQL, (1,)))
    assert "items_work" in plan and "items_order" not in plan, plan
    store.close()
