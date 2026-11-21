"""A placing rule never stacks a show's new episodes reversed (Kura-SO; train 44's intent keeper, D-2).

Why these matter: an airing show brings one episode a week, and a placing rule the learner turned on (Settings → *Where
new arrivals go*) places each as it arrives. Every rule target was exact since 3.0.16, so a *Soon* rule put each new
episode at Soon's first slot, above its own show: Frieren's 8 and 9 in Soon, then 10, then 11, read 11, 10, 8, 9.
Sonic's ruling (2026-11-19): a new episode joins its own show in episode order — never ahead of an earlier episode (6
lands after 5: "they wouldn't consume ep 6 before 5") — and an item with no episode order (a YouTube video) goes to
the end of the list it is placed in, after what is already there ("it would come after the content that they have").
So every rule target reads the show's order where it places (*Top of Current* and *Soon* in Current, NOW then Soon;
*Goal* in 6+ Months), by the numbers the records name (hato's / the browser's `show.episode`, a folder's file by its
name), gaps (8, 9, 11 → 10 between 9 and 11) and a season's episodes arriving out of order too; the store's rule at
`register` and Connect's (`connect.rules.apply`) alike. What must not change: an episode of a show not there (still
the rule's own place: the very top, Soon's first slot, the top of 6+ Months), another title's rows, a *Soon* rule
never above the Soon line, one Undo. Every test runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT,
with real words from tests/Test Resources/.
"""

import hashlib
import os
import shutil

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, names, pieces_ok, roots, touch

SUBTITLE = {"ja": "phrases_sample.srt", "zh": "night_market.srt"}      # real subtitles, a folder show's episodes


def _record(language, show, n, season=1):
    """(the file's path under the data folder, the browser extension's record) for one episode of `show`."""
    video = str(81903033 + 100 * season + n)
    rel = f"{ls.PROCESSED_FOLDER}/{show} S{season:02d}E{n:02d} {show} [netflix-{video}].txt"
    return rel, {"schema": 1, "producer": "browser", "language": language, "content_key": f"netflix:{video}",
                 "video_id": video, "title": show, "show": {"title": show, "season": season, "episode": n}}


def _arrive(store, language, show, n, rules=None, season=1):
    """One episode handed over by the browser extension, placed by `rules` ({source: target}) at `register` as the
    store reads them (None: it waits in New arrivals). -> its item id."""
    data_dir, _u = roots(language)
    rel, record = _record(language, show, n, season)
    change = store.register(touch(data_dir, rel, f"{show} {season} {n}\n"), record, rules=rules)
    return change.added[0]


def _video(store, language, channel, vid, word, rules):
    """One video of a YouTube channel (no episode number, no playlist place), placed by `rules`. -> its item id."""
    data_dir, _u = roots(language)
    record = {"schema": 1, "producer": "youtube", "language": language, "media_type": "youtube",
              "content_key": f"youtube:{vid}", "video_id": vid, "title": word, "channel_id": channel,
              "show": {"title": channel}}
    return store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{channel} - {word} [{vid}].txt"), record,
                          rules=rules).added[0]


def _in(ids, order):
    """`ids` as they stand in `order` (a tier's ids), read top to bottom."""
    return [i for i in order if i in set(ids)]


def _current(store):
    return store.ids("now") + store.ids("soon")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_soon_rule_puts_an_airing_shows_new_episodes_after_its_earlier_ones_in_soon(language):
    """The keeper's report (D-2): 8 and 9 in Soon, a *Soon* rule brings 10, then 11 — Soon reads 8, 9, 10, 11, never
    11, 10, 8, 9; Connect's rule (a held drop placed on resume) the same for 12. Another title's rows never move; each
    Undo puts its episode back in New arrivals."""
    from app.connect import rules
    store = migrated(language, shows=2, episodes=3)
    show = names(language)[180]
    ep8, ep9 = (_arrive(store, language, show, n) for n in (8, 9))
    store.place([ep8], "soon")
    store.place([ep9], "soon")
    assert _in((ep8, ep9), store.ids("soon")) == [ep8, ep9], "the setup: 8, 9 in Soon"
    others = [i for i in _current(store) if i not in (ep8, ep9)]
    ep10 = _arrive(store, language, show, 10, rules={"browser": "soon"})
    ep11 = _arrive(store, language, show, 11, rules={"browser": "soon"})
    soon = store.ids("soon")
    assert _in((ep8, ep9, ep10, ep11), soon) == [ep8, ep9, ep10, ep11]
    assert soon.index(ep11) == soon.index(ep8) + 3, "one run, nothing of another title between"
    ep12 = _arrive(store, language, show, 12)                                   # waits: Connect's rule places it
    _rel, record12 = _record(language, show, 12)
    assert rules.apply(store, ep12, record12, {"placing_rules": {"browser": "soon"}}) == "soon"
    assert _in((ep8, ep9, ep10, ep11, ep12), store.ids("soon")) == [ep8, ep9, ep10, ep11, ep12]
    assert [i for i in _current(store) if i not in (ep8, ep9, ep10, ep11, ep12)] == others
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_soon_rule_never_lands_above_the_soon_line_and_a_show_not_there_takes_soons_first_slot(language):
    """The rule's own place stays where its show has nothing to follow: a new show's episode at Soon's first slot (as
    before), and an episode whose show is in NOW goes to Soon's first slot — below its show, never above the Soon line
    into NOW."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    first = store.ids("soon")[0]
    one = _arrive(store, language, w[181], 1, rules={"browser": "soon"})
    assert store.ids("soon")[0] == one and store.ids("soon")[1] == first, "a show not there: Soon's first slot"
    ep4 = _arrive(store, language, w[182], 4)
    store.place([ep4], "top")
    ep5 = _arrive(store, language, w[182], 5, rules={"browser": "soon"})
    assert store.item(ep5)["tier"] == "soon" and store.ids("soon")[0] == ep5, "below the line, after its show's 4"
    assert store.ids("now")[0] == ep4
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_top_of_current_rule_never_puts_an_episode_ahead_of_an_earlier_one(language):
    """*Top of Current* is the very top for an episode with nothing earlier of its show in Current (D-1 kept there);
    with its show there it joins it in episode order (6 lands after 5): 8 placed, then 9 and 11 by the rule, then 10 —
    read 8, 9, 10, 11 (the gap filled between 9 and 11), and 7 before 8; an earlier episode left in Soon is followed
    across the Soon line (Current is one order). The store's rule and Connect's alike."""
    from app.connect import rules
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[183]
    ep8 = _arrive(store, language, show, 8, rules={"browser": "top"})
    assert store.ids("now")[0] == ep8, "nothing of its show in Current: the very top"
    ep9 = _arrive(store, language, show, 9, rules={"browser": "top"})
    ep11 = _arrive(store, language, show, 11, rules={"browser": "top"})
    ep10 = _arrive(store, language, show, 10)
    _rel, record10 = _record(language, show, 10)
    assert rules.apply(store, ep10, record10, {"placing_rules": {"browser": "top"}}) == "top"
    ep7 = _arrive(store, language, show, 7, rules={"browser": "top"})
    assert store.ids("now")[:5] == [ep7, ep8, ep9, ep10, ep11]
    other = w[184]
    two = _arrive(store, language, other, 2)
    store.place([two], "soon")
    three = _arrive(store, language, other, 3, rules={"browser": "top"})
    soon = store.ids("soon")
    assert store.item(three)["tier"] == "soon" and soon.index(three) == soon.index(two) + 1, \
        "its 2 is in Soon: 3 follows it there, never the top of NOW ahead of it"
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_goal_rule_joins_its_show_in_episode_order_in_6_months(language):
    """*Goal* (6+ Months) reads the show's order there too: 3 and 4 in 6+ Months, the rule brings 6, then 5 — read
    3, 4, 5, 6; a show not there still goes to the top of 6+ Months."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[185]
    ep3, ep4 = (_arrive(store, language, show, n) for n in (3, 4))
    store.place([ep4], "goal")
    store.place([ep3], "goal")                                       # (the setup: each to the top) 3, 4
    assert store.ids("goal")[:2] == [ep3, ep4]
    ep6 = _arrive(store, language, show, 6, rules={"browser": "goal"})
    ep5 = _arrive(store, language, show, 5, rules={"browser": "goal"})
    goal = store.ids("goal")
    assert goal[:4] == [ep3, ep4, ep5, ep6]
    new = _arrive(store, language, w[186], 1, rules={"browser": "goal"})
    assert store.ids("goal")[0] == new, "a show not there: the top of 6+ Months, as before"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_with_no_episode_order_goes_after_what_is_already_there(language):
    """A channel's videos name no episode and no list place: a *Soon* rule puts each at the end of Soon and a *Goal*
    rule at the end of 6+ Months, after what is there, in the order they came; *Top of Current* puts the first at the
    very top and the next after it, never above its channel's video (PROVISIONAL)."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    channel = w[187]
    soon_rule = {"youtube": "soon"}
    v1 = _video(store, language, channel, "pitFobM6z80", w[188], soon_rule)
    v2 = _video(store, language, channel, "IIqUltT_x0c", w[189], soon_rule)
    assert store.ids("soon")[-2:] == [v1, v2], "the end of Soon, in the order they came"
    goal_channel = w[190]
    g1 = _video(store, language, goal_channel, "f3Z0Kx8qLmA", w[191], {"youtube": "goal"})
    g2 = _video(store, language, goal_channel, "q9Wd2RtYb4E", w[192], {"youtube": "goal"})
    assert store.ids("goal")[-2:] == [g1, g2], "the end of 6+ Months"
    top_channel = w[193]
    t1 = _video(store, language, top_channel, "Zk3vB7nQp1s", w[194], {"youtube": "top"})
    assert store.ids("now")[0] == t1, "nothing of its channel in Current: the very top"
    t2 = _video(store, language, top_channel, "Lr8mC2xJd6w", w[195], {"youtube": "top"})
    assert store.ids("now")[:2] == [t1, t2], "after its channel's video, never above it"
    t3 = _video(store, language, top_channel, "Hc5yN0aWe9T", w[202], {"youtube": "top"})
    assert store.ids("now")[:3] == [t1, t2, t3], "after its channel's LAST video there"
    assert pieces_ok(store) is None
    store.close()


def _source():
    """The source folder the folder shows are read from (outside Surasura's own folders)."""
    return os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "Shows")


def _found(language, show, n, k4=False):
    """One episode file of `show` in the source folder, as the look finds it (real subtitle bytes): its record names no
    episode number, the file name does (`Show - 01`) — or (`k4`) the record names it (the look's K4 number) and the
    name holds none (`Show - <a word>`)."""
    data_dir, _u = roots(language)
    sample = os.path.join(os.path.dirname(__file__), "Test Resources", language, SUBTITLE[language])
    origin = os.path.join(_source(), show, f"{show} - {names(language)[210 + n] if k4 else f'{n:02d}'}.srt")
    os.makedirs(os.path.dirname(origin), exist_ok=True)
    with open(sample, "rb") as f, open(origin, "wb") as out:
        out.write(f.read() + f"\nscan {n}\n".encode("utf-8"))
    rel = f"{ls.CONTENT_FOLDER}/{show}/{os.path.basename(origin)}"
    os.makedirs(os.path.join(data_dir, ls.CONTENT_FOLDER, show), exist_ok=True)
    shutil.copyfile(origin, os.path.join(data_dir, *rel.split("/")))
    with open(origin, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    st = os.stat(origin)
    return {"origin": origin, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha, "show": show,
            "rel": rel, **({"episode": n} if k4 else {})}


def _folder_show(store, language, show, numbers, k4=False):
    """`show`'s episodes taken in from a source folder by setup's scan (`_found`). -> (their item ids, the root)."""
    os.makedirs(_source(), exist_ok=True)
    root = store.add_source(_source())
    return store.take_in(root, [_found(language, show, n, k4) for n in numbers], first=True).added, root


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("k4", [False, True])
def test_an_episode_joins_a_folder_shows_run_by_the_number_in_its_file_names(language, k4):
    """A show a folder scan brought in (1, 2, 3, numbered only by their file names — or by the look's K4 number in
    their records, `k4`) and the browser's episode 4 by a *Top of Current* rule: 4 goes after 3, never the very top
    above 1 (a folder record names no season: it never sets the rows apart)."""
    store = migrated(language, shows=2, episodes=3)
    show = names(language)[196]
    scanned, _root = _folder_show(store, language, show, (1, 2, 3), k4)
    current = _current(store)
    assert _in(scanned, current) == scanned
    ep4 = _arrive(store, language, show, 4, rules={"browser": "top"})
    current = _current(store)
    assert current.index(ep4) == current.index(scanned[-1]) + 1
    assert store.item(ep4)["work_id"] == store.item(scanned[0])["work_id"], "the setup: one title"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("target", ["top", "soon"])
def test_a_season_dropped_at_once_in_any_order_lands_in_episode_order(language, target):
    """A season pack: hato hands its 12 episodes over in whatever order it finished them (here 7, 3, 12, 1, …) and
    each is placed by the rule as it comes — the show reads 1 … 12, one run."""
    store = migrated(language, shows=2, episodes=3)
    show = names(language)[197]
    came = (7, 3, 12, 1, 9, 5, 2, 11, 4, 8, 10, 6)
    ids = {n: _arrive(store, language, show, n, rules={"browser": target}) for n in came}
    order = _current(store)
    run = [ids[n] for n in range(1, 13)]
    assert _in(run, order) == run
    assert order.index(run[-1]) - order.index(run[0]) == 11, "one run, nothing between"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_re_air_of_episodes_already_watched_lands_after_them_in_order(language):
    """A re-air (the same episodes again, new files) by a *Soon* rule: 1 and 2 of the first airing in Soon, the
    re-air's 1, 2, 3 come in — each new one after the episodes before it, the re-air's own read 1, 2, 3, never 3, 2, 1,
    and none lands ahead of an earlier episode."""
    store = migrated(language, shows=2, episodes=3)
    show = names(language)[198]
    old1, old2 = (_arrive(store, language, show, n) for n in (1, 2))
    store.place([old1], "soon")
    store.place([old2], "soon")
    again = []
    for n in (1, 2, 3):
        data_dir, _u = roots(language)
        rel, record = _record(language, show, n)
        video = str(91903033 + n)                                     # the re-air's own videos
        record.update(content_key=f"netflix:{video}", video_id=video)
        rel = rel.replace("[netflix-", "[re-air netflix-")
        again.append(store.register(touch(data_dir, rel, f"{show} re-air {n}\n"), record,
                                    rules={"browser": "soon"}).added[0])
    soon = store.ids("soon")
    assert _in(again, soon) == again, "the re-air's own episodes in order"
    assert soon.index(again[1]) > soon.index(old1) and soon.index(again[2]) > soon.index(old2), \
        "never ahead of an earlier episode"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_undo_puts_a_ruled_episode_back_in_new_arrivals(language):
    """The rule's placement is inside `register`'s one command: Undo takes the episode out as an Add, the show's rows
    as they were."""
    store = migrated(language, shows=2, episodes=3)
    show = names(language)[199]
    ep8 = _arrive(store, language, show, 8)
    store.place([ep8], "soon")
    before = store.ids("soon")
    data_dir, _u = roots(language)
    rel, record = _record(language, show, 9)
    change = store.register(touch(data_dir, rel, f"{show} 9\n"), record, rules={"browser": "soon"})
    assert store.ids("soon").index(change.added[0]) == before.index(ep8) + 1
    store.undo(change)
    assert store.ids("soon") == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_record_naming_no_episode_is_read_by_the_number_in_its_file_name(language):
    """("it probably says it in the name") The browser's record of episode 10 lost its number (only the show's title):
    a *Soon* rule reads `S01E10` in its file name and puts it after 9, never at Soon's first slot above 8."""
    store = migrated(language, shows=2, episodes=3)
    show = names(language)[200]
    ep8, ep9 = (_arrive(store, language, show, n) for n in (8, 9))
    store.place([ep8], "soon")
    store.place([ep9], "soon")
    data_dir, _u = roots(language)
    rel, record = _record(language, show, 10)
    record["show"] = {"title": show}
    ep10 = store.register(touch(data_dir, rel, f"{show} 10\n"), record, rules={"browser": "soon"}).added[0]
    soon = store.ids("soon")
    assert _in((ep8, ep9, ep10), soon) == [ep8, ep9, ep10] and soon.index(ep10) == soon.index(ep9) + 1
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_soon_rule_follows_its_shows_rows_in_soon_even_when_a_later_one_sits_in_now(language):
    """(Review, bounds) A *Soon* rule reads its show's rows in Soon: 5 moved up into NOW by hand, 4 left in Soon — 6
    goes right after 4 in Soon, never to Soon's first slot above it."""
    store = migrated(language, shows=2, episodes=3)
    show = names(language)[201]
    ep4, ep5 = (_arrive(store, language, show, n) for n in (4, 5))
    store.move([ep5], "now", in_order=False)
    store.move([ep4], "soon", after_id=store.ids("soon")[2], in_order=False)
    ep6 = _arrive(store, language, show, 6, rules={"browser": "soon"})
    soon = store.ids("soon")
    assert soon.index(ep6) == soon.index(ep4) + 1
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folders_next_file_placed_by_a_soon_rule_joins_its_shows_run(language):
    """A folder's file names its place by its show's run (S3): the show's 1, 2, 3 in Soon, a channel's video at Soon's
    end after them, then the folder's 4 found later and placed by a *Soon* rule for folders — after 3, never at the
    end of Soon after the video (an item with no order's place)."""
    store = migrated(language, shows=2, episodes=3)
    w = names(language)
    show = w[203]
    scanned, root = _folder_show(store, language, show, (1, 2, 3))
    assert all(store.item(i)["tier"] == "soon" for i in scanned), "the setup: the scan put the show in Soon"
    video = _video(store, language, w[204], "Rt7bKe2mQx0", w[205], {"youtube": "soon"})
    assert store.ids("soon")[-1] == video
    four = store.take_in(root, [_found(language, show, 4)], rules={"source": "soon"}).added[0]
    soon = store.ids("soon")
    assert soon.index(four) == soon.index(scanned[-1]) + 1 and soon[-1] == video
    store.close()
