"""A show's episodes moved into Current one at a time keep their episode order (Mattias, 2026-11-15).

Why these matter: episodes of one show arrive in New arrivals one by one (the browser extension hands over each episode
as it is watched) and the learner moves each into Current — the tray's *Top* or a drop of the row in the list. *Top*
put each one at the top of NOW and a drop on the show's row put it above the row (the tray's drop lands by halves), so
episode 9 went above 8 and 10 above 9: the show read 10, 9, 8. `after-show` already knew the order (the records' season
and episode); now a move of a title's items into Current takes it too (`Store._into_show`) — unless the learner chose
the spot: a drop away from the title's rows, or between two of them, stays where it was dropped. What must not change:
another title's rows, an item whose order can't be read (a channel's video: still the top), and Undo (the move's own).
Every test runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, with real words from tests/Test
Resources/.
"""

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, names, pieces_ok, roots, touch


def _episode(store, language, show, n, title=None):
    """One episode as the browser extension hands it over (`producer` browser, the show's title, season and episode in
    the record's `show`), registered into New arrivals. -> its item id."""
    data_dir, _u = roots(language)
    video = str(81903033 + n)
    rel = f"{ls.PROCESSED_FOLDER}/{show} S01E{n:02d} {title or show} [netflix-{video}].txt"
    record = {"schema": 1, "producer": "browser", "language": language, "content_key": f"netflix:{video}",
              "video_id": video, "title": title or show, "show": {"title": show, "season": 1, "episode": n}}
    item = store.register(touch(data_dir, rel, f"{show} {n}\n"), record).added[0]
    assert store.item(item)["tier"] == "arrivals", "the setup: it waits in New arrivals"
    return item


def _current(store):
    return store.ids("now") + store.ids("soon")


def _others(store, eps):
    return [i for i in _current(store) if i not in eps]


@pytest.mark.parametrize("language", LANGUAGES)
def test_episodes_moved_in_one_at_a_time_keep_their_order(language):
    """Mattias's report: episode 8 into Current, then 9, then 10 — by the tray's *Top*, by *Soon*, by a drop on the
    show's row (its upper half: before episode 8) — read 8, 9, 10, never 10, 9, 8. No other title's row moves; each
    Undo puts the episode back in New arrivals and Current as it was."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[140]
    ep8 = _episode(store, language, show, 8, w[141])
    store.place([ep8], "top")
    assert store.ids("now")[0] == ep8
    others = _others(store, {ep8})

    ep9 = _episode(store, language, show, 9, w[142])
    before = _current(store)
    nine = store.place([ep9], "top")
    assert store.ids("now")[:2] == [ep8, ep9], "after episode 8, never above it"
    assert _others(store, {ep8, ep9}) == others

    ep10 = _episode(store, language, show, 10, w[143])
    ten = store.move([ep10], "now", before_id=ep8)         # the tray's drop on the show's row: its upper half
    assert store.ids("now")[:3] == [ep8, ep9, ep10]
    assert _others(store, {ep8, ep9, ep10}) == others, "another title's rows never move"
    assert pieces_ok(store) is None
    assert len({store.item(i)["piece_id"] for i in (ep8, ep9, ep10)}) == 1, "one row, in episode order"

    store.undo(ten)
    assert store.item(ep10)["tier"] == "arrivals" and store.ids("now")[:2] == [ep8, ep9]
    store.undo(nine)
    assert store.item(ep9)["tier"] == "arrivals" and _current(store) == [i for i in before]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_earlier_episode_goes_before_and_soon_follows_its_show(language):
    """Before the lowest higher episode when only later ones are there (7 before 8), and in the show's tier: *Soon*
    of the next episode while the show sits in Soon lands after its episode there, not at Soon's top."""
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
    assert now[now.index(away) + 1] == ep9, "dropped away from its show: where it was dropped"
    store.undo(there)
    assert store.item(ep9)["tier"] == "arrivals" and store.ids("now")[:2] == [ep8, ep10]
    ep11 = _episode(store, language, show, 11)
    store.move([ep11], "now", before_id=ep10)        # between two of the show's own episodes
    assert store.ids("now")[:3] == [ep8, ep11, ep10]
    assert pieces_ok(store) is None
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
