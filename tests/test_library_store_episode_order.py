"""A show's episodes moved into Current one at a time keep their episode order (Kura-EO; adapted from Mattias's #482).

Why these matter: a show's episodes come into New arrivals one by one — the browser extension hands over each Netflix
episode as it is watched, an airing show brings one a week — and the learner moves each into Current: the tray's *Top*,
a drop on the show's row, a 6+ Months episode's *Up next*. *Top* put each at the top of NOW and a drop on the row's
upper half put it above the row's first episode, so episode 9 went above 8 and 10 above 9: the show read 10, 9, 8.
`after-show` already read the order (the records' season and episode); now a move of ONE title's items into Current
takes it too (`Store._into_show`) — unless the learner chose the spot (a drop away from the title's rows). Since 3.0.16
(#492, the follow-up: after a morning's drags inside Current a show read 10, 8, 9) a move inside Current keeps it too:
one episode dropped beside its show's rows (above, below or between two of them) takes its place in the order, and a
block of the show's episodes (its whole row dragged) lands sorted. What must not change: another title's rows, an item
whose order can't be read (a channel's video: still the top), *Top* of what is in Current already, a drop away from the
show, *Soon* staying below the Soon line, *Put back*'s top, seasons apart, and Undo (the move's own). Every test runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, with real words from
tests/Test Resources/.
"""

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, names, pieces_ok, roots, touch


def _record(language, show, n, season=1, title=None):
    """(the file's path under the data folder, the browser extension's record) for one episode."""
    video = str(81903033 + 100 * season + n)
    rel = f"{ls.PROCESSED_FOLDER}/{show} S{season:02d}E{n:02d} {title or show} [netflix-{video}].txt"
    return rel, {"schema": 1, "producer": "browser", "language": language, "content_key": f"netflix:{video}",
                 "video_id": video, "title": title or show, "show": {"title": show, "season": season, "episode": n}}


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
    at the edge of the show's row. Without one (`--to current` with no position), the episode order. (A placing
    rule's target: `test_a_placing_rules_top_of_current_means_the_very_top_unless_an_earlier_episode_is_there`.)"""
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
    """The learner's own spot is kept: a drop away from the show's rows (between two other titles) stays there; Undo
    puts it back. A drop between two of the show's own episodes is beside the show (3.0.16): 11 dropped between 8 and
    10 goes after 10."""
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
    change = store.move([ep11], "now", before_id=ep10)   # between two of the show's own episodes: its order
    assert store.ids("now")[:3] == [ep8, ep10, ep11] and change.show_order is True
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
    ep10 = _episode(store, language, show, 10)
    store.finish([ep10])
    assert store.item(ep10)["tier"] == "graduated"
    store.put_back_finished([ep10])
    assert store.ids("now")[:2] == [ep10, ep8], "back at the top, not after its show's 8"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_drop_at_nows_end_just_above_its_show_in_soon_takes_the_order(language):
    """The Soon line is no gap: episode 8 leads Soon; episode 9 dropped at NOW's end (after NOW's last row, right
    above 8 across the line) is a drop on the show's row's edge — it goes after 8, never left above it."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[158]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "soon")
    assert store.ids("soon")[0] == ep8, "the setup: its show leads Soon"
    ep9 = _episode(store, language, show, 9)
    change = store.move([ep9], "now", after_id=store.ids("now")[-1])
    current = _current(store)
    assert current.index(ep9) == current.index(ep8) + 1 and change.show_order is True
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_whose_item_in_current_names_no_episode_cant_be_ordered_top_stays_the_top(language):
    """One of its show's items in Current names no episode (a file of the show without a number): the order can't be
    read, so *Top* stays the top — never "after the title's last item", `after-show`'s own fallback."""
    store = migrated(language, shows=2, episodes=3)
    data_dir, _u = roots(language)
    w = names(language)
    show = w[159]
    record = {"schema": 1, "producer": "browser", "language": language, "content_key": "netflix:81900001",
              "video_id": "81900001", "title": show, "show": {"title": show, "season": 1}}
    loose = store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{show} [netflix-81900001].txt", f"{show}\n"),
                           record).added[0]
    store.place([loose], "top")
    ep8 = _episode(store, language, show, 8)
    assert store.item(ep8)["work_id"] == store.item(loose)["work_id"], "the setup: one title"
    store.move([loose], "now", after_id=store.ids("now")[2])
    change = store.place([ep8], "top")
    assert store.ids("now")[0] == ep8 and change.show_order is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_move_of_two_titles_at_once_goes_where_asked(language):
    """A block of two titles (the tray's picks, a selection) has no one episode order: *Top* puts the block at the
    top, though both have their show in Current."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show, second = w[162], w[163]
    one = _episode(store, language, second, 1)
    store.place([one], "top")
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    assert store.ids("now")[:2] == [ep8, one], "the setup: both titles lead NOW"
    ep9 = _episode(store, language, show, 9)
    two = _episode(store, language, second, 2)
    change = store.place([ep9, two], "top")
    assert set(store.ids("now")[:2]) == {ep9, two} and change.show_order is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_seasons_episode_is_another_shows_and_goes_to_the_top(language):
    """Seasons stay apart (`after-show`'s own reading): season 2's episode 10 is no neighbour of season 1's 8 and 9
    (a reading blind to seasons would put it after 9) — *Top* puts it at the top, and season 1 keeps its order."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[153]
    ep8 = _episode(store, language, show, 8)
    store.place([ep8], "top")
    ep9 = _episode(store, language, show, 9)
    store.place([ep9], "top")
    s2 = _episode(store, language, show, 10, season=2)
    store.place([s2], "top")
    assert store.ids("now")[:3] == [s2, ep8, ep9]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_whose_order_cant_be_read_still_goes_to_the_top(language):
    """No episode number, no list place (a channel's single video): *Top* is still the top of Current, above its
    channel's video there. (3.0.16: episode 9 dragged above 8 inside Current is beside its show — it stays after 8,
    nothing to move.)"""
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
    assert store.move([ep9], "now", before_id=ep8) is None, "inside Current, beside its show: already in order"
    assert store.ids("now")[:2] == [ep8, ep9]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_is_any_of_the_title_in_current_goes_by_the_titles_index_never_a_walk_through_current(language):
    """Kura-PR2's B1 rule for every title read on a move's path: the check runs inside each move into Current (the
    write lock held), so it reads the title's index (items_work), never Current's order index — a 20k library's
    NOW is never walked for it."""
    from tests.test_library_store_support import big_store
    store = big_store(language, 200)
    plan = " ".join(r[-1] for r in store.conn.execute("EXPLAIN QUERY PLAN " + ls.SHOW_IN_CURRENT_SQL, (1, 1)))
    assert "items_work" in plan and "items_order" not in plan, plan
    store.close()


def _ten_eight_nine(store, language, word):
    """The follow-up's screenshot: a show's 8, 9, 10 in Current, then *Top* of 10 inside Current (the learner's own:
    it stays at the top) — the show reads 10, 8, 9. -> (ep8, ep9, ep10)."""
    ep8, ep9, ep10 = (_episode(store, language, word, n) for n in (8, 9, 10))
    for ep in (ep8, ep9, ep10):
        store.place([ep], "top")
    assert store.ids("now")[:3] == [ep8, ep9, ep10]
    top = store.move([ep10], "now")
    assert store.ids("now")[:3] == [ep10, ep8, ep9] and top.show_order is False, "Top inside Current: as asked"
    return ep8, ep9, ep10


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_episode_dragged_inside_current_beside_its_show_takes_its_place_in_the_order(language):
    """(#492, red at 3.0.15.) 10, 8, 9: episode 10 dragged onto the show's other rows (before 8) lands
    after 9 — 8, 9, 10; another title's rows never move; Undo puts 10 back on top."""
    store = migrated(language, shows=2, episodes=3)
    ep8, ep9, ep10 = _ten_eight_nine(store, language, names(language)[164])
    others = _others(store, {ep8, ep9, ep10})
    drag = store.move([ep10], "now", before_id=ep8)
    assert store.ids("now")[:3] == [ep8, ep9, ep10] and drag.show_order is True
    assert _others(store, {ep8, ep9, ep10}) == others
    assert pieces_ok(store) is None
    store.undo(drag)
    assert store.ids("now")[:3] == [ep10, ep8, ep9]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_shows_whole_row_dragged_inside_current_lands_sorted_and_undo_puts_it_back(language):
    """(#492, red at 3.0.15.) The row 10, 8, 9 dragged as one block below another title lands there
    8, 9, 10 — the block sorted by episode, where it was dropped (nothing else of the show is left in Current to sit
    beside); no other title's row changes order; Undo puts the show back 10, 8, 9 at the top."""
    store = migrated(language, shows=2, episodes=3)
    ep8, ep9, ep10 = _ten_eight_nine(store, language, names(language)[165])
    others = _others(store, {ep8, ep9, ep10})
    target = store.ids("now")[4]
    assert store.item(target)["work_id"] != store.item(ep8)["work_id"], "the setup: another title's row"
    drag = store.move([ep10, ep8, ep9], "now", after_id=target)
    now = store.ids("now")
    at = now.index(target)
    assert now[at + 1:at + 4] == [ep8, ep9, ep10] and drag.show_order is True
    assert _others(store, {ep8, ep9, ep10}) == others
    assert pieces_ok(store) is None
    store.undo(drag)
    assert store.ids("now")[:3] == [ep10, ep8, ep9]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_inside_current_a_drop_away_from_the_show_stays_and_so_does_a_whole_row_already_sorted(language):
    """The learner's own spot inside Current: episode 10 dragged away from its show (below another title) stays there;
    the show's row already in order dragged to the top is a plain move (nothing sorted, no redirect)."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    ep8, ep9, ep10 = (_episode(store, language, w[166], n) for n in (8, 9, 10))
    for ep in (ep8, ep9, ep10):
        store.place([ep], "top")
    target = store.ids("now")[5]
    away = store.move([ep10], "now", after_id=target)
    now = store.ids("now")
    assert now[now.index(target) + 1] == ep10 and away.show_order is False
    store.undo(away)
    row = store.move([ep8, ep9, ep10], "now", after_id=target)
    now = store.ids("now")
    assert now[now.index(target) + 1:now.index(target) + 4] == [ep8, ep9, ep10] and row.show_order is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_top_of_the_whole_row_inside_current_sorts_it_where_it_stands(language):
    """*Top* of the show's row 10, 8, 9 already at the top: the place is the learner's own (as asked), but the block
    still lands sorted — 8, 9, 10 — though it moves nowhere (never a no-op for an unsorted row). Undo: 10, 8, 9."""
    store = migrated(language, shows=2, episodes=3)
    ep8, ep9, ep10 = _ten_eight_nine(store, language, names(language)[169])
    top = store.move([ep10, ep8, ep9], "now")
    assert top is not None and store.ids("now")[:3] == [ep8, ep9, ep10] and top.show_order is True
    store.undo(top)
    assert store.ids("now")[:3] == [ep10, ep8, ep9]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_block_beside_its_show_goes_by_its_lowest_episode(language):
    """A pick of 12 and 9 (12 first) dragged onto its show's 8, 10: the block's place is read from its LOWEST episode,
    9 — after 8 — and the block lands sorted: 8, 9, 12, 10 (a block stays one block; 12 is no neighbour of 10's)."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[170]
    ep8, ep10 = (_episode(store, language, show, n) for n in (8, 10))
    for ep in (ep8, ep10):
        store.place([ep], "top")
    assert store.ids("now")[:2] == [ep8, ep10]
    ep12, ep9 = (_episode(store, language, show, n) for n in (12, 9))
    store.move([ep12, ep9], "goal")
    store.move([ep12, ep9], "now", before_id=ep8)
    assert store.ids("now")[:4] == [ep8, ep9, ep12, ep10]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_up_and_down_move_an_episode_one_exact_step_inside_its_show(language):
    """↑ ↓ (`nudge`) are one exact step, never the episode order: 10 ↑ in a show reading 8, 9, 10 gives 8, 10, 9 —
    a key press always moves (it was refused as "already in order", the window's swap snapping back)."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    ep8, ep9, ep10 = (_episode(store, language, w[172], n) for n in (8, 9, 10))
    for ep in (ep8, ep9, ep10):
        store.place([ep], "top")
    up = store.nudge([ep10], "up")
    assert up is not None and store.ids("now")[:3] == [ep8, ep10, ep9] and up.show_order is False
    store.undo(up)
    down = store.nudge([ep8], "down")                 # (its order would be where it is: never "nothing")
    assert down is not None and store.ids("now")[:3] == [ep9, ep8, ep10] and down.show_order is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_drop_inside_a_group_stays_in_the_group_where_it_was_dropped(language):
    """A group (LM11: the learner's own row of several titles) holding the show's 8, 9 and another title: episode 10
    dropped inside it after 8 (the opened group's episodes) stays there, in the group — `after-show` never lands inside
    a group, so the order would have pulled it out past the group while the toast says it joined."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    ep8, ep9 = (_episode(store, language, w[173], n) for n in (8, 9))
    for ep in (ep9, ep8):
        store.place([ep], "top")
    store.move([ep9], "now", after_id=ep8)
    now = store.ids("now")
    assert now[:2] == [ep8, ep9], "the setup"
    mine = store.item(ep8)["piece_id"]
    other = store.item(now[2])["piece_id"]
    assert other != mine and store.item(now[2])["work_id"] != store.item(ep8)["work_id"]
    assert store.join([mine, other], how="group") is not None
    group = store.item(ep8)["piece_id"]
    ep10 = _episode(store, language, w[173], 10)
    drop = store.move([ep10], "now", after_id=ep8)
    assert store.ids("now")[:3] == [ep8, ep10, ep9] and drop.show_order is False
    assert store.item(ep10)["piece_id"] == group, "in the group, where it was dropped"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_inside_current_seasons_stay_apart_a_block_of_two_seasons_keeps_its_order(language):
    """Seasons stay apart inside Current too: season 2's episode 1 dragged onto season 1's rows (before 8) stays where
    it was dropped (no order to read across seasons), and a block holding both seasons keeps its own order."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[167]
    ep8, ep9 = (_episode(store, language, show, n) for n in (8, 9))
    for ep in (ep8, ep9):
        store.place([ep], "top")
    s2 = _episode(store, language, show, 1, season=2)
    store.move([s2], "now", after_id=store.ids("now")[4])
    drop = store.move([s2], "now", before_id=ep8)
    assert store.ids("now")[:3] == [s2, ep8, ep9] and drop.show_order is False
    target = store.ids("now")[5]
    block = store.move([ep9, s2], "now", after_id=target)
    now = store.ids("now")
    assert now[now.index(target) + 1:now.index(target) + 3] == [s2, ep9] and block.show_order is False, \
        "as it stood (s2 above 9)"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_placing_rules_top_of_current_means_the_very_top_unless_an_earlier_episode_is_there(language):
    """(Train 40's intent keeper, D-1; Kura-SO, Sonic 2026-11-19) A placing rule set to *Top of Current* is the
    learner's standing choice of the very top — for an episode with nothing earlier of its show in Current (another
    title's row stays below it); never ahead of an earlier episode: the browser's 9 placed by it goes right after its
    show's 8, and 10 after 9 — the store's own rule at register and Connect's (`connect.rules.apply`) alike."""
    from app.connect import rules
    store = migrated(language, shows=2, episodes=3)
    data_dir, _u = roots(language)
    show = names(language)[175]
    top = store.ids("now")[0]
    rel8, record8 = _record(language, show, 8)
    ep8 = store.register(touch(data_dir, rel8, f"{show} 8\n"), record8, rules={"browser": "top"}).added[0]
    assert store.ids("now")[:2] == [ep8, top], "nothing of its show in Current: the very top"
    rel, record = _record(language, show, 9)
    ep9 = store.register(touch(data_dir, rel, f"{show} 9\n"), record, rules={"browser": "top"}).added[0]
    assert store.ids("now")[:3] == [ep8, ep9, top], "the store's rule: after its show's 8"
    ep10 = _episode(store, language, show, 10)
    _rel, record10 = _record(language, show, 10)
    assert rules.apply(store, ep10, record10, {"placing_rules": {"browser": "top"}}) == "top"
    assert store.ids("now")[:4] == [ep8, ep9, ep10, top], "Connect's rule: after 9"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_titles_first_row_dragged_inside_current_still_finds_its_shows_other_rows(language):
    """(Mutants, 3.0.16) "Is any other of the title in Current?" must look past the moved items themselves: 9, 10, 8 with
    episode 8 — the title's first row by the title's index — dragged between 9 and 10 joins the order (8, 9, 10). Read
    one row only and it would see 8 itself, find nothing else, and leave 8 between 9 and 10."""
    store = migrated(language, shows=2, episodes=3)
    ep8, ep9, ep10 = (_episode(store, language, names(language)[168], n) for n in (8, 9, 10))
    for ep in (ep8, ep9, ep10):
        store.place([ep], "top")
    store.move([ep8], "now", after_id=ep10, in_order=False)        # (the setup: an exact move) 9, 10, 8
    assert store.ids("now")[:3] == [ep9, ep10, ep8]
    drag = store.move([ep8], "now", before_id=ep10)
    assert store.ids("now")[:3] == [ep8, ep9, ep10] and drag.show_order is True
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_episode_set_apart_dropped_on_its_own_spot_moves_nothing(language):
    """(Mutants, 3.0.16) The gap a drop lands in is read without the moved item: episode 9, set apart below another
    title (8, X, 9, Y), dropped on its own spot (before Y, after X) is beside X and Y, not beside its show — nothing
    moves. Read with 9 still in the gap, 9 would count as "its show's row" and jump up to 8."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    ep8, ep9 = (_episode(store, language, w[169], n) for n in (8, 9))
    store.place([ep8], "top")
    x = store.ids("now")[1]
    store.move([ep9], "now", after_id=x, in_order=False)          # (the setup) 8, X, 9, Y
    now = store.ids("now")
    y = now[3]
    assert now[:3] == [ep8, x, ep9] and store.item(y)["work_id"] != store.item(ep8)["work_id"]
    assert store.move([ep9], "now", before_id=y) is None, "before Y: its own place"
    assert store.move([ep9], "now", after_id=x) is None, "after X: its own place"
    assert store.ids("now")[:4] == [ep8, x, ep9, y]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_block_of_two_seasons_of_one_merged_title_keeps_its_order(language):
    """(Mutants, 3.0.16) A title can hold two seasons (*Same show as…* merged season 2 into season 1's title): a block of
    S01E09 and S02E01 dragged together keeps its order — episode numbers of two seasons aren't one order (1 < 9 would
    put season 2's first episode above season 1's ninth)."""
    store = migrated(language, shows=2, episodes=3)
    show = names(language)[170]
    ep9 = _episode(store, language, show, 9)
    s2 = _episode(store, language, show, 1, season=2)
    keep, other = store.item(ep9)["work_id"], store.item(s2)["work_id"]
    if other != keep:
        assert store.merge_works(keep, [other]) is not None
    assert store.item(s2)["work_id"] == store.item(ep9)["work_id"], "the setup: one title, two seasons"
    store.place([ep9], "top")
    store.move([s2], "now", after_id=ep9, in_order=False)
    target = store.ids("now")[4]
    assert store.item(target)["work_id"] != keep
    block = store.move([ep9, s2], "now", after_id=target)
    now = store.ids("now")
    assert now[now.index(target) + 1:now.index(target) + 3] == [ep9, s2], "as it stood: season 1 above season 2"
    assert block.show_order is False
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_soons_first_episode_dropped_at_nows_end_away_from_its_show_stays_there(language):
    """(Mutants, 3.0.16) The gap at the Soon line is read without the moved item too: episode 9, Soon's first row, dropped
    after NOW's last row (another title's) is in its own gap — between that row and Soon's next, away from its show (8,
    at the top) — so it stays: still Soon's first (the Soon line is a count of files). Read with 9 still below the
    line, 9 would count as its show's row and jump up to 8."""
    store = migrated(language, shows=2, episodes=3)
    ep8, ep9 = (_episode(store, language, names(language)[171], n) for n in (8, 9))
    store.place([ep8], "top")
    store.place([ep9], "soon")
    assert store.ids("soon")[0] == ep9, "the setup: 9 is Soon's first row"
    last = store.ids("now")[-1]
    assert last != ep8 and store.item(last)["work_id"] != store.item(ep8)["work_id"]
    drop = store.move([ep9], "now", after_id=last)
    assert store.ids("now")[-1] == last and store.ids("soon")[0] == ep9, "where it was: after NOW's last row"
    assert drop is None or drop.show_order is False
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_block_whose_order_spot_is_beside_its_own_rows_moves_whole_or_not_at_all(language):
    """(Mutants, 3.0.16) The order's spot is never beside one of the moved block's own rows: a group (LM11) [X, 8, 9, 10]
    with 9 and 10 dragged together to just below the group — beside 8, so the order is read: after 8, past the group
    (its last row, 10: one of the block). Anchored there, the block would move without its anchor (9 alone after 10).
    It stays as dropped instead: here its own place, nothing moves."""
    store = migrated(language, shows=2, episodes=3)
    ep8, ep9, ep10 = (_episode(store, language, names(language)[177], n) for n in (8, 9, 10))
    for ep in (ep8, ep9, ep10):
        store.place([ep], "top")
    now = store.ids("now")
    assert now[:3] == [ep8, ep9, ep10]
    x = now[3]
    assert store.item(x)["work_id"] != store.item(ep8)["work_id"]
    pieces = list(dict.fromkeys(store.item(i)["piece_id"] for i in (x, ep8, ep9, ep10)))
    assert store.join(pieces, how="group") is not None
    now = store.ids("now")
    at = now.index(ep10)
    group = store.item(ep10)["piece_id"]
    assert now[at - 2:at + 1] == [ep8, ep9, ep10] and store.item(x)["piece_id"] == group, \
        "the setup: the group reads X…, 8, 9, 10"
    assert store.item(now[at + 1])["piece_id"] != group
    z = now[at + 1]
    assert store.move([ep9, ep10], "now", before_id=z) is None
    assert store.ids("now") == now, "the block whole, where it stood"
    assert pieces_ok(store) is None
    store.close()
