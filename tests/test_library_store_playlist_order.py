"""Mado-Q (alpha 8, Sonic 2026-10-31: "I'd fix it now, i want it in the order. Ideally their first video"): a YouTube
playlist's videos land in the library in the list's learning order — whatever order they come in — through the store's
own order (`register`, one command each), never by renaming files.

What a wrong answer would cost a learner: a podcast's episode 43 (setup's first video, from his `watch?v=…&list=…`
link) sitting above episodes 1–42, so the series starts at its end; a stalled run's second half landing out of place;
an older download of the channel, or another playlist of the same channel, shuffled by a new list's videos.

Each record is shaped as `windows.youtube_record` makes it from the downloader's sidecar (`playlist` {"id", "index"}:
the index in the list's learning order, `downloader.series_places`). Real Japanese / Chinese names; per-test
SURASURA_TEST_ROOT.
"""
import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, arrivals_off, migrated, names, roots, touch

LIST_A = "PLjfPBTv1Zr1J8RTG9iCANlm2vzBhl7QZn"      # a real playlist (Real Japanese Podcast)
LIST_B = "PLxQ7m2vB0aRealJapanesePodcastShorts"


def _video(n):
    return f"vid{n:08d}"[:11]


def _record(language, channel, n, index=None, list_id=LIST_A):
    record = {"schema": 1, "producer": "youtube", "language": language, "media_type": "youtube",
              "content_key": f"youtube:{_video(n)}", "video_id": _video(n), "channel_id": channel,
              "show": {"title": channel}}
    if index is not None:
        record["playlist"] = {"id": list_id, "index": index}
    return record


def _download(store, data_dir, language, channel, n, index=None, list_id=LIST_A, folder=None, rules=None):
    """One transcript the downloader wrote, handed to `register` -> its item id."""
    w = names(language)
    folder = folder or f"Processed/{channel} - {w[60]} (playlist)"
    path = touch(data_dir, f"{folder}/{channel} - {w[61 + n]} [{_video(n)}].txt",
                 f"{w[61 + n]} {' '.join(w[:12])} {n}\n")
    store.register(path, _record(language, channel, n, index, list_id), rules=rules)
    return store.item_id(ls.library_rel(data_dir, path))


def _arrivals_on(language):
    store = migrated(language)
    store.set_library_options(arrivals_on=True)
    return store, roots(language)[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_setups_first_video_then_the_rest_in_any_order_land_in_the_lists_order(language):
    """Sonic's try: his link names episode 43 (the list's last in learning order: YouTube shows it at the top), setup
    brings it in first, loose in Processed; the rest come later, in file-name order (not the list's). Each lands in its
    place: 1, 2, 3, 4, 5 … 43 — another channel's video that arrived meanwhile keeps its own place after them."""
    store, data_dir = _arrivals_on(language)
    w = names(language)
    channel, other = w[50], w[51]
    first = _download(store, data_dir, language, channel, 43, index=43, folder="Processed")
    elsewhere = _download(store, data_dir, language, other, 90, folder="Processed")
    rest = {index: _download(store, data_dir, language, channel, index, index=index) for index in (3, 1, 5, 2, 4)}
    assert store.ids("arrivals")[-7:] == [rest[1], rest[2], rest[3], rest[4], rest[5], first, elsewhere]
    assert len({store.item(i)["work_id"] for i in [first, *rest.values()]}) == 1      # one title: the channel's
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_added_later_takes_its_place_and_older_downloads_and_other_lists_are_untouched(language):
    """A run stopped half-way and resumed, or a video the maker put into the list later, lands between its neighbours.
    The channel's older download (no place: fetched before this rule) is never moved and never an anchor; a second
    playlist of the same channel (one title) orders only among its own."""
    store, data_dir = _arrivals_on(language)
    channel = names(language)[52]
    older = _download(store, data_dir, language, channel, 70, folder="Processed")
    one = _download(store, data_dir, language, channel, 1, index=1)
    three = _download(store, data_dir, language, channel, 3, index=3)
    two = _download(store, data_dir, language, channel, 2, index=2)
    shorts = _download(store, data_dir, language, channel, 80, index=1, list_id=LIST_B, folder="Processed/shorts")
    assert store.ids("arrivals")[-5:] == [older, one, two, three, shorts]
    assert len({store.item(i)["work_id"] for i in (older, one, two, three, shorts)}) == 1
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_new_arrivals_off_the_lists_order_holds_in_current(language):
    """New arrivals switched off (the library's option): the videos go to Current, in the list's order there too."""
    store = migrated(language)
    arrivals_off(store)
    data_dir = roots(language)[0]
    channel = names(language)[53]
    two = _download(store, data_dir, language, channel, 2, index=2)
    one = _download(store, data_dir, language, channel, 1, index=1)
    three = _download(store, data_dir, language, channel, 3, index=3)
    tier = store.item(one)["tier"]
    assert tier in ls.CURRENT and {store.item(i)["tier"] for i in (two, three)} == {tier}
    order = [i for i in store.ids(tier) if i in (one, two, three)]
    assert order == [one, two, three]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_youtube_after_show_rule_puts_a_later_video_between_its_list_neighbours_in_current(language):
    """The learner placed the title in Current; the list's episode 2 comes later and his rule for YouTube is
    `after-show`: it goes between 1 and 3 (by its place), not after the title's last row."""
    store, data_dir = _arrivals_on(language)
    channel = names(language)[54]
    one = _download(store, data_dir, language, channel, 1, index=1)
    three = _download(store, data_dir, language, channel, 3, index=3)
    four = _download(store, data_dir, language, channel, 4, index=4)
    store.place([one, three, four], "top")
    two = _download(store, data_dir, language, channel, 2, index=2, rules={"youtube": "after-show"})
    assert store.item(two)["tier"] == "now"
    assert [i for i in store.ids("now") if i in (one, two, three, four)] == [one, two, three, four]
    store.close()


def test_a_record_names_a_place_only_with_a_list_id_and_a_whole_number():
    assert ls.list_place({"playlist": {"id": LIST_A, "index": 3}}) == (LIST_A, 3)
    for bad in ({"playlist": {"id": LIST_A, "index": True}}, {"playlist": {"id": LIST_A, "index": "3"}},
                {"playlist": {"id": "  ", "index": 3}}, {"playlist": {"index": 3}}, {"playlist": [LIST_A, 3]},
                {"show": {"title": "x", "episode": 3}}, None):
        assert ls.list_place(bad) is None, bad


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("target, tier", [("top", "now"), ("soon", "soon")])
def test_a_top_or_soon_rule_keeps_the_lists_order_in_its_tier(language, target, tier):
    """A8Q-1: with a YouTube rule of `top` (or `soon`), each video was moved to the top of its tier as it came, so 1, 2,
    3 read 3, 2, 1. Now a video goes beside its list's videos there, in order; the first one still goes where the rule
    says."""
    store, data_dir = _arrivals_on(language)
    channel = names(language)[55]
    rules = {"youtube": target}
    got = [_download(store, data_dir, language, channel, index, index=index, rules=rules) for index in (1, 2, 3)]
    assert {store.item(i)["tier"] for i in got} == {tier}
    assert [i for i in store.ids(tier) if i in got] == got
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_goes_after_the_one_before_it_in_the_list_never_above_a_group_holding_both(language):
    """A8Q-2: episodes 1, 2, 3 and 5 grouped in Current with another channel's video; 4 comes with an `after-show`
    rule. Never inside a group (LM11): it went above the whole group (before 5's group: 4 first of all); now after the
    one before it (3), so after the group — the nearest it can stand to its place."""
    store, data_dir = _arrivals_on(language)
    w = names(language)
    channel, other = w[56], w[57]
    stranger = _download(store, data_dir, language, other, 91, folder="Processed")
    eps = {i: _download(store, data_dir, language, channel, i, index=i) for i in (1, 2, 3, 5)}
    block = [stranger, eps[1], eps[2], eps[3], eps[5]]
    store.place(block, "top")
    assert store.group(item_ids=block) is not None
    four = _download(store, data_dir, language, channel, 4, index=4, rules={"youtube": "after-show"})
    now = [i for i in store.ids("now") if i in (*block, four)]
    assert now == block + [four]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_video_with_its_list_in_current_and_no_rule_still_waits_in_new_arrivals(language):
    """D30 (mutant Q2): the learner placed episodes 1 and 3 in Current; episode 2 comes with no rule. It waits in New
    arrivals (an arrival never places itself) — its list's videos in Current are no anchor for it."""
    store, data_dir = _arrivals_on(language)
    channel = names(language)[58]
    one = _download(store, data_dir, language, channel, 1, index=1)
    three = _download(store, data_dir, language, channel, 3, index=3)
    store.place([one, three], "top")
    two = _download(store, data_dir, language, channel, 2, index=2)
    assert store.item(two)["tier"] == "arrivals" and store.ids("arrivals")[-1] == two
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_top_rule_never_puts_a_video_inside_a_group_holding_the_one_before_it(language):
    """LM11 (mutant Q7): episodes 1–3 grouped in NOW with another channel's video after them; episode 4 comes with a
    `top` rule: after the whole group, never between 3 and the group's last row."""
    store, data_dir = _arrivals_on(language)
    w = names(language)
    channel, other = w[59], w[60]
    eps = [_download(store, data_dir, language, channel, i, index=i) for i in (1, 2, 3)]
    stranger = _download(store, data_dir, language, other, 92, folder="Processed")
    block = eps + [stranger]
    store.place(block, "top")
    assert store.group(item_ids=block) is not None
    four = _download(store, data_dir, language, channel, 4, index=4, rules={"youtube": "top"})
    assert [i for i in store.ids("now") if i in (*block, four)] == block + [four]
    store.close()
