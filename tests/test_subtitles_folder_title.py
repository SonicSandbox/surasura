"""A show's subtitles folder is never a title of its own (Kantan-T, 2026-11-18; a tester's library on 3.0.15).

The shape: `<Show> (2024)/Season 01/` holds the videos and a `.srt` beside each, and the show's `.ass` files sit in a
folder of their own below it, `Season 01/ass/`. The sort screen offered `<Show> (2024)/Season 01/ass` as a new title of
24 episodes: the look's named-folder rule (`sources._subtitle_folder`) knew `Subs`, `Subtitles` and a language's folder,
not a folder named for the subtitles' format, so `ass/` was read as a folder of its own — its own `Library/…/ass` copy,
its own title, every episode a second time.

The rule now: a folder named for a subtitle format (`ass`, `ssa`, `srt`, `[ASS]`, `ASS Subs`, `jpn_ass`) is a subtitles
folder like `Subs`: listed with the folder above, one subtitle per episode (as `.ass` + `.srt` side by side). The store's
title grouping reads the same rule (`library_store.subtitles_home`): a file placed by hand in such a folder (a 2.x tier,
`Library`) takes the title of the folder above it, named as that folder — never `…/ass`.

What a wrong answer costs: a phantom title in New arrivals and the sort screen, every episode counted twice; or a real
folder (`Part 2`, `Movie`, `English`) swallowed into its parent. Japanese and Chinese, real texts from tests/Test
Resources/ under the per-test SURASURA_TEST_ROOT.
"""
import json
import os

import pytest

from app import library_store as ls
from app import sources
from tests.test_library_store_support import LANGUAGES, names, pieces_ok, touch
from tests.test_sources_scan import (_OURS, _drive, _empty, _fresh_module_state, _look, _settle, _text,  # noqa: F401
                                     _video, _write)

_SHOW = {"ja": "月影の旅人 (2024)", "zh": "夜市小记 (2024)"}            # made-up shows, a year in the name as his
_TAG = {"ja": "jpn", "zh": "chs"}                                      # the release's language tag, as his `.jpn.ass`


def _stem(language, n):
    show = _SHOW[language]
    return f"{show} - S01E{n:02d} - Episode {n} [WEBRip-1080p][10bit][x265][EAC3 2.0]-EMBER"


def _works(store):
    return {w: (t, fk) for w, t, fk in store.conn.execute("SELECT id, title, folder_key FROM works")}


def _paths(store):
    return [r[0] for r in store.conn.execute("SELECT rel_path FROM items ORDER BY id")]


# --- the one rule, pure ----------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("name, language, kind", [
    ("ass", "ja", "subs"), ("ASS", "zh", "subs"), ("ssa", "ja", "subs"), ("srt", "zh", "subs"), ("SRT", "ja", "subs"),
    ("[ASS]", "ja", "subs"), ("ASS Subs", "zh", "subs"), ("Subs (ASS)", "ja", "subs"), ("ass_srt", "ja", "subs"),
    ("jpn_ass", "ja", "ja"), ("ass ja", "ja", "ja"), ("Japanese ASS", "ja", "ja"), ("chs_ass", "zh", "zh"),
    ("ass_ja", "ja", "ja"), ("ASS-Japanese", "ja", "ja"), ("ja-JP_ass", "ja", "ja"), ("srt_zh-Hans", "zh", "zh"),
    ("CHS srt", "zh", "zh"),
    # never a subtitles folder: another language's, a word that only starts like a format, a show's own name
    ("eng_ass", "ja", None), ("English ASS", "zh", None), ("assets", "ja", None), ("Assassins", "ja", None),
    ("Part 2", "ja", None), ("srt Movie", "zh", None), ("chs_ass", "ja", None),
])
def test_a_folder_named_for_a_subtitle_format_is_a_subtitles_folder(name, language, kind):
    """The named-folder rule reads `ass` / `ssa` / `srt` as `Subs` (alone, with subtitle marks, or beside our
    language's word); a folder of another language, or any other word in the name, stays a folder of its own."""
    assert sources._subtitle_folder(name, "Season 01", language) == kind


def test_the_store_homes_a_subtitles_folder_to_the_folder_above_it():
    """`subtitles_home`: the last part a subtitles folder (by the look's rule) with a folder above it -> that folder,
    as written; down through nested ones (`Subs/ja`); never a season, a specials folder, a folder alone or a folder of
    its own."""
    assert ls.subtitles_home("Show (2024)/Season 01/ass", "ja") == "Show (2024)/Season 01"
    assert ls.subtitles_home("show (2024)/season 01/ass", "ja") == "show (2024)/season 01"
    assert ls.subtitles_home("Show/Subs/ja", "ja") == "Show"
    assert ls.subtitles_home("Show/Subtitles", "zh") == "Show"
    assert ls.subtitles_home("Show/中文字幕", "zh") == "Show"
    assert ls.subtitles_home("Show/Subs/ja/ass", "ja") == "Show"                  # nested, all the way up
    assert ls.subtitles_home("节目/字幕/中文/ass", "zh") == "节目"
    assert ls.subtitles_home("Show/Show/ass", "ja") == "Show"                     # a folder named as the one above
    for folder in ("ass", "Show/Season 2", "Show/Extras", "Show/Part 2", "Show/English", "Show/assets", "", None):
        assert ls.subtitles_home(folder, "ja") is None, folder


# --- a look at a source folder (the tester's way in) ------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("folder", ["ass", "SRT", "[ASS]", "lang_ass"])
def test_an_ass_folder_beside_the_videos_srt_is_read_once_as_the_shows(language, folder):
    """His shape: `<Show>/Season 01/` holds the videos and a `.srt` each, `Season 01/ass/` the same episodes' `.ass`.
    One look: one title (`<Show> Season 1`), one item per episode, every copy in the season's `Library` folder —
    never `…/ass`, never a second title, never an episode twice."""
    if folder == "lang_ass":
        folder = f"{_TAG[language]}_ass"
    store, data_dir = _empty(language)
    show = _SHOW[language]
    src = _drive("driveA")
    season = os.path.join(src, show, "Season 01")
    for n in (1, 2):
        _video(os.path.join(season, _stem(language, n) + ".mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska %d" % n)
        _write(os.path.join(season, _stem(language, n) + f".{_TAG[language]}.srt"), _text(language, n))
        _write(os.path.join(season, folder, _stem(language, n) + f".{_TAG[language]}.ass"), _text(language, n))
    _settle(src)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["shows"] == 1
        paths = _paths(store)
        assert len(paths) == 2, paths
        assert {p.rsplit("/", 1)[0] for p in paths} == {f"Library/{show}/Season 01"}
        works = _works(store)
        assert list(works.values()) == [(f"{show} Season 1", ls.path_key(f"{show}/Season 01"))], works
        again = _look(store, language, root, full=True)
        assert again["added"] == 0 and len(_paths(store)) == 2
        assert pieces_ok(store) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_ass_folder_whose_season_holds_only_videos_is_still_the_seasons_title(language):
    """The videos alone in `Season 01/`, every subtitle in `Season 01/ass/`: the subtitles are the season's, paired
    with its videos by name — one title, nothing waiting for subtitles, nothing in a folder `ass`."""
    store, data_dir = _empty(language)
    show = _SHOW[language]
    src = _drive("driveA")
    season = os.path.join(src, show, "Season 01")
    for n in (1, 2):
        _video(os.path.join(season, _stem(language, n) + ".mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska %d" % n)
        _write(os.path.join(season, "ass", _stem(language, n) + f".{_TAG[language]}.ass"), _text(language, n))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        paths = _paths(store)
        assert len(paths) == 2 and all("/ass/" not in p for p in paths), paths
        assert store.conn.execute("SELECT COUNT(*) FROM items WHERE availability = 'waiting'").fetchone()[0] == 0
        assert len(_works(store)) == 1


# --- files placed by hand (a 2.x tier folder, `Library`): the store's grouping ---------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_hand_placed_ass_folder_joins_the_title_of_the_folder_above(language):
    """A 2.x tier's `<show>/Season 01/` with an `ass/` below it, added together and found by the sync after: one
    title, `<show> Season 1`, whatever came first (the `ass/` file listed FIRST here)."""
    store, data_dir = _empty(language)
    show = names(language)[90]
    with store:
        paths = [touch(data_dir, f"HighPriority/{show}/Season 01/ass/{show} - 01.ass", _text(language, 1)),
                 touch(data_dir, f"HighPriority/{show}/Season 01/{show} - 02.srt", _text(language, 2))]
        store.insert(paths, "now")
        ids = [store.item_id(os.path.relpath(p, data_dir).replace(os.sep, "/")) for p in paths]
        assert None not in ids
        assert len({store.item(i)["work_id"] for i in ids}) == 1
        touch(data_dir, f"HighPriority/{show}/Season 01/ass/{show} - 03.ass", _text(language, 3))
        later = store.sync_disk()["added"]
        assert {store.item(i)["work_id"] for i in later} == {store.item(ids[0])["work_id"]}
        assert [t for t, _fk in _works(store).values()] == [f"{show} Season 1"]
        assert pieces_ok(store) is None


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("folder", ["ass", "Subs/ja"])
def test_a_hand_placed_subtitles_folder_with_nothing_above_it_is_named_and_keyed_as_that_folder(language, folder):
    """`Library/<show>/Season 01/ass/` (or `Subs/<language>/`) with no file in `Season 01/` itself: its title is the
    season's — `<show> Season 1`, the season's folder key — so a file put in `Season 01/` later joins it too."""
    if folder == "Subs/ja":
        folder = f"Subs/{_OURS[language]}"
    store, data_dir = _empty(language)
    show = names(language)[91]
    with store:
        first = touch(data_dir, f"Library/{show}/Season 01/{folder}/{show} - 01.srt", _text(language, 1))
        store.insert([first], "now")
        wid = store.item(store.item_id(os.path.relpath(first, data_dir).replace(os.sep, "/")))["work_id"]
        assert _works(store)[wid] == (f"{show} Season 1", ls.path_key(f"{show}/Season 01"))
        second = touch(data_dir, f"Library/{show}/Season 01/{show} - 02.srt", _text(language, 2))
        store.insert([second], "now")                    # (`Library` is the looks' copy: added as the first was)
        later = store.item_id(os.path.relpath(second, data_dir).replace(os.sep, "/"))
        assert later is not None and store.item(later)["work_id"] == wid
        assert len(_works(store)) == 1
        titles = json.loads(store.conn.execute("SELECT titles FROM works WHERE id = ?", (wid,)).fetchone()[0])
        assert all(not t.endswith(folder) for t in titles), titles


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_of_its_own_below_a_show_stays_its_own_title(language):
    """The guard: `Part 2/` and `English/` below a show are folders of their own, as before (never homed)."""
    store, data_dir = _empty(language)
    show = names(language)[92]
    with store:
        paths = [touch(data_dir, f"HighPriority/{show}/{show} - 01.srt", _text(language, 1)),
                 touch(data_dir, f"HighPriority/{show}/Part 2/{show} - 01.srt", _text(language, 2))]
        store.insert(paths, "now")
        assert len(_works(store)) == 2
