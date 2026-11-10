"""A stranded episode's show from its name (SRC-11).

Why these matter: an episode downloaded without its series — loose in hato's drop folder, or straight into a tier
folder — has no show folder, so through 2.x and 3.0's first cut every one became a title of its own (seven episodes of
one show, seven rows). Sonic's rule: such a file gets its show from its file name; only where no show matches is it
shown to him as a new title (New arrivals). A season stays part of the name, as hato's records keep seasons apart. New
items only: an existing title is never regrouped or renamed, and the 2.x upgrade seeds as it always did.

The release names are made up (made-up hashes, no library's titles); the store tests build them from real words of the
language's test texts, under the per-test SURASURA_TEST_ROOT, for Japanese and Chinese.
"""

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, entry, library, migrated, names, pieces_ok, roots, touch,
                                              write_manifest)


# --- show_of_name (pure) ---------------------------------------------------------------------------- #

@pytest.mark.parametrize("file_name", [
    "[SubsPlease] Hoshizora Kissa - 16 (1080p) [ABCD1234].ja.ass",
    "[SubsPlease] Hoshizora Kissa - 12v2 (1080p) [0F1E2D3C].ass",
    "[NanakoRaws] Hoshizora Kissa S01E13 (1080p).ass",
    "Hoshizora Kissa E13.srt",
    "Hoshizora Kissa #13.srt",
    "Hoshizora_Kissa_-_14_[720p].ja-JP.srt",
    "Hoshizora.Kissa.S01E15.1080p.WEB.mkv",
    "HighPriority/Hato/[SubsPlease] Hoshizora Kissa - 17 (1080p) [9A8B7C6D].ja.ass",
])
def test_release_names_of_one_show_read_as_one_show(file_name):
    """Every way a release names an episode — a leading [group], (resolution) / [hash] tags, ` - 16`, `v2`, `S01E13`,
    `E13`, `#13`, a language tag and the extension; scene names with dots or underscores for spaces — comes off,
    and what is left is the show, as written."""
    assert ls.show_of_name(file_name) == "Hoshizora Kissa"


def test_japanese_and_chinese_episode_markers_and_full_width_forms():
    """第05話 / 第13集 are episode markers; a full-width ＃ and digits read as their ASCII forms (NFKC); a Japanese
    title's own 【】 brackets are part of its name, not a tag."""
    assert ls.show_of_name("月影の旅人 第05話.srt") == "月影の旅人"
    assert ls.show_of_name("月影の旅人　＃０５.ja.srt") == "月影の旅人"
    assert ls.show_of_name("某部电视剧 第13集.zh.srt") == "某部电视剧"
    assert ls.show_of_name("【星の歌】 第05話.ass") == "【星の歌】"


def test_a_season_stays_part_of_the_name():
    """Another season is another title (as `_work_by_record` keeps them): `S2`, `2期`, `II`, `2nd Season` stay in the
    name, and `S02E05` reads as `… S2` — the same show a `… S2 - 05` release names; season 1 is the show itself."""
    s2 = ls.show_of_name("[SubsPlease] Hoshizora Kissa S2 - 05 (1080p) [ABCD1234].ass")
    assert s2 == ls.show_of_name("[NanakoRaws] Hoshizora Kissa S02E05 (1080p).ass") == "Hoshizora Kissa S2"
    assert ls.search_fold(s2, "ja") != ls.search_fold(ls.show_of_name("Hoshizora Kissa S01E05.ass"), "ja")
    assert ls.show_of_name("月影の旅人 第2期 第05話.srt") == "月影の旅人 第2期"
    assert ls.show_of_name("[Group] Some Show II - 03 (720p).ass") == "Some Show II"
    assert ls.show_of_name("[Group] Some Show 2nd Season - 03.ass") == "Some Show 2nd Season"


def test_a_number_inside_the_title_is_kept():
    """Only a marked episode number comes off: a number that is part of the title stays."""
    assert ls.show_of_name("[Group] Robo Kissa 100 - 05 (1080p).ass") == "Robo Kissa 100"


@pytest.mark.parametrize("file_name", ["05.srt", "[SubsPlease] - 05 (1080p) [ABCD1234].ass", "第05話.srt",
                                       "(1080p).ja.srt", "", None, "2024 - 01.srt"])
def test_no_show_when_nothing_or_only_digits_is_left(file_name):
    """A name that is only an episode number, tags or digits names no show: None (the file stays a title of its own)."""
    assert ls.show_of_name(file_name) is None


# --- the store: a new loose file joins its show ---------------------------------------------------------- #

def _work(store, item_id):
    return store.item(item_id)["work_id"]


def _titles(store):
    return dict(store.conn.execute("SELECT id, title FROM works"))


def _ext(language):
    return "ja.ass" if language == "ja" else "zh.srt"


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_hato_drops_of_one_show_are_one_title_and_another_show_stays_apart(language):
    """Two episodes of one show dropped loose in hato's folder, found by the disk sync, are one title named by the show;
    a third from another release group in the tier folder itself joins it; another show, and the show's season 2, are
    titles of their own; a name with no show in it stays a title of its own, by its file."""
    store = migrated(language, shows=2, episodes=2)
    data_dir, _u = roots(language)
    w = names(language)
    show, other = w[130], w[131]
    touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {show} - 16 (1080p) [ABCD1234].{_ext(language)}")
    touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {show} - 17 (1080p) [1A2B3C4D].{_ext(language)}")
    first, second = sorted(store.sync_disk()["added"])
    assert _work(store, first) == _work(store, second), "one show: one title"
    assert _titles(store)[_work(store, first)] == show
    third = store.insert([touch(data_dir, f"HighPriority/[NanakoRaws] {show} S01E13 (1080p).ass")], "now").added[0]
    assert _work(store, third) == _work(store, first), "loose in a tier folder, another group: the same title"
    touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {other} - 01 (1080p) [5E6F7A8B].{_ext(language)}")
    touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {show} S2 - 01 (1080p) [9C0D1E2F].{_ext(language)}")
    touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] - 05 (1080p) [3A4B5C6D].{_ext(language)}")
    found = store.sync_disk()["added"]
    assert len(found) == 3
    works = {store.item(i)["rel_path"].rsplit("/", 1)[-1]: _work(store, i) for i in found}
    assert len(set(works.values()) | {_work(store, first)}) == 4, "another show, season 2 and no show: apart"
    titles = _titles(store)
    nameless = next(i for i in found if "] - 05 (" in store.item(i)["rel_path"])
    assert sorted(titles[wid] for wid in works.values()) == sorted([other, f"{show} S2", store.item(nameless)["title"]])
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_drop_joins_an_existing_title_by_its_name_and_the_title_is_kept(language):
    """A show already in the library as a folder (its title the folder's name) takes a stranded episode of it; so does a
    title the user renamed, by the show's name among its other titles' fold (katakana / hiragana, case); the title,
    its folder key and its other episodes stay as they were."""
    store = migrated(language, shows=2, episodes=2)
    data_dir, _u = roots(language)
    w = names(language)
    show = next(i for i in store.ids("goal") if store.item(i)["parent_folder"])
    wid = _work(store, show)
    before = store._work_row(wid)
    title = before["title"]
    mates = sorted(i for i in store.ids("goal") if _work(store, i) == wid)
    touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {title} - 09 (1080p) [ABCD1234].{_ext(language)}")
    drop = store.sync_disk()["added"][0]
    assert _work(store, drop) == wid
    after = store._work_row(wid)
    assert (after["title"], after["folder_key"]) == (before["title"], before["folder_key"]), "the title is kept"
    assert sorted(i for i in store.ids("goal") if _work(store, i) == wid) == mates, "its episodes stay"
    renamed = store._work_row(_work(store, next(i for i in store.ids("soon") if store.item(i)["parent_folder"])))
    store.rename_work(renamed["id"], w[140])
    touch(data_dir, f"HighPriority/{w[140]} 第03話.srt")
    found = store.sync_disk()["added"][0]
    assert _work(store, found) == renamed["id"]
    assert store._work_row(renamed["id"])["title"] == w[140]
    assert pieces_ok(store) is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_upgrade_seeds_stranded_2x_files_as_before_and_regroups_nothing(language):
    """New items only: a 2.x library's loose hato drops are seeded as they always were — each a title of its own,
    named by its file — and a later drop of the same show never pulls them into its title (Sonic starts from
    scratch; the store never regroups an existing title)."""
    data_dir, user_files_dir, doc = library(language, shows=1, episodes=2)
    w = names(language)
    show = w[150]
    old = [f"{ls.HATO_FOLDER}/[SubsPlease] {show} - {n:02d} (1080p) [ABCD123{n}].{_ext(language)}" for n in (1, 2)]
    for rel in old:
        touch(data_dir, rel)
    doc["schedule"][ls.TIERS["now"][0]] = [entry(rel, origin="Disk Sync") for rel in old] + \
        doc["schedule"][ls.TIERS["now"][0]]
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    rows = {store.item(i)["rel_path"]: i for i in store.ids("now")}
    seeded = [_work(store, rows[rel]) for rel in old]
    assert len(set(seeded)) == 2, "2.x's loose drops: a title each, as seeded before"
    works_before = store.conn.execute("SELECT id, title, folder_key FROM works ORDER BY id").fetchall()
    touch(data_dir, f"{ls.HATO_FOLDER}/[SubsPlease] {show} - 03 (1080p) [ABCD1233].{_ext(language)}")
    new = store.sync_disk()["added"][0]
    assert _work(store, new) not in seeded
    assert [_work(store, rows[rel]) for rel in old] == seeded, "the old drops are not regrouped"
    kept = store.conn.execute("SELECT id, title, folder_key FROM works WHERE id <= ? ORDER BY id",
                              (works_before[-1][0],)).fetchall()
    assert kept == works_before, "no existing title renamed or taken away"
    assert pieces_ok(store) is None
    store.close()
