"""3.0's Sources, a show moved (D3, the moves scope §1 — PROVISIONAL, Sonic's MV-1): a show the learner moves to a
folder Surasura reads joins the show it is, never a second one — even when the move adds a folder level
(`Downloads/Show` → `NAS/2024 Fall/Show`). The rule: a folder's show is the show of the items its files already are —
their origins recorded there, else (a folder whose own name holds no show yet) its files' bytes or videos found in the
store — and a moved waiting video is its waiting item.

Why these matter: a move that splits a show puts the learner's next episode in a second title in New arrivals, counts a
v2 of an episode he read as a new episode, and gives a video waiting for its subtitle a second waiting row — the same
show twice, its words counted twice. The guards matter as much: a folder holding two shows' files, a show of the same
name with other bytes, a stray copy and a source's loose files keep the show they had (never guessed by a name).

Every look runs through `_look` (nothing under either source written). Real Japanese / Chinese texts from
tests/Test Resources/, made-up show names, a few bytes as a fake video.
"""
import os
import shutil

import pytest

from app import library_store as ls
from app import sources
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import (_OURS, _SHOWS, _current, _drive, _empty, _fresh_module_state, _items,  # noqa: F401
                                     _library_files, _look, _settle, _sha, _text, _versions, _video,
                                     _write)

LEVEL = "2024 Fall"


def _name(show, n, language, group="Grp"):
    return f"[{group}] {show} - {n:02d}.{_OURS[language]}.srt"


def _seed(language, src, show, episodes=(1, 2, 3, 4)):
    folder = os.path.join(src, show)
    for n in episodes:
        _write(os.path.join(folder, _name(show, n, language)), _text(language, n))
    return folder


def _move(folder, to):
    """The learner's move: the folder cut and pasted (its files' times kept), its new place a minute old."""
    os.makedirs(os.path.dirname(to), exist_ok=True)
    shutil.move(folder, to)
    _settle(os.path.dirname(to))


def _work(store, item_id):
    return store.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone()[0]


def _works(store):
    return store.conn.execute("SELECT COUNT(DISTINCT work_id) FROM items").fetchone()[0]


def _waiting(store):
    return [r[0] for r in store.conn.execute("SELECT id FROM items WHERE availability = 'waiting' ORDER BY id")]


def _origin(store, path):
    return store.origins().get(ls.path_key(os.path.abspath(path)))


def _moved_show(language, level=LEVEL):
    """A/Show 01–04 taken in, then the folder moved to B/<level>/Show and B added -> (store, data_dir, a, b, show,
    the new folder, the items by episode, B's root, B's look)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, show)
    store.__enter__()
    root_a = store.add_source(a)
    first = _look(store, language, root_a, first=True)
    ids = {store.item(i)["rel_path"].rsplit(" - ", 1)[1][:2]: i for i in first["ids"]}
    moved = os.path.join(b, level, show) if level else os.path.join(b, show)
    _move(os.path.join(a, show), moved)
    root_b = store.add_source(b)
    result = _look(store, language, root_b)
    return store, data_dir, a, b, show, moved, ids, root_a, root_b, result


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("level", [LEVEL, ""])
def test_a_show_moved_under_a_new_folder_level_stays_one_show_and_its_next_episode_joins_it(language, level):
    """MV-1: the moved files are their items (no new row); the show's next episode, found in its new place, joins the
    show — the same title, its copy beside the others in `Library/<show>/`, after episode 4 in Current."""
    store, data_dir, a, b, show, moved, ids, _ra, root_b, result = _moved_show(language, level)
    try:
        assert (result["added"], result["attached"]) == (0, 4) and _items(store) == 4
        for n in ("01", "02", "03", "04"):
            assert _origin(store, os.path.join(moved, _name(show, int(n), language))).item_id == ids[n]
        _write(os.path.join(moved, _name(show, 5, language)), _text(language, 5))
        _settle(b)
        again = _look(store, language, root_b)
        assert again["added"] == 1 and _items(store) == 5
        new = again["ids"][0]
        assert _work(store, new) == _work(store, ids["01"]) and _works(store) == 1
        assert store.item(new)["rel_path"] == f"Library/{show}/{_name(show, 5, language)}"
        current = _current(store)
        assert current.index(store.item(new)["rel_path"]) == current.index(store.item(ids["04"])["rel_path"]) + 1
        assert store.ordered("arrivals") == []
    finally:
        store.__exit__(None, None, None)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("level", [LEVEL, ""])
def test_a_waiting_video_moved_keeps_its_one_waiting_item(language, level):
    """D3 (a): a video waiting for its subtitle, moved — still one waiting row (its id), its new place recorded on it;
    its subtitle, come in the new place, fills that row in place."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    a, b = _drive("driveA"), _drive("driveB")
    _video(os.path.join(a, show, f"[Grp] {show} - 01.mkv"))
    with store:
        first = _look(store, language, store.add_source(a), first=True)
        assert first["added"] == 1 and _waiting(store) == first["ids"]
        gap = first["ids"][0]
        moved = os.path.join(b, level, show) if level else os.path.join(b, show)
        _move(os.path.join(a, show), moved)
        root_b = store.add_source(b)
        result = _look(store, language, root_b)
        assert (result["added"], result["attached"]) == (0, 1) and _items(store) == 1 and _waiting(store) == [gap]
        assert _origin(store, os.path.join(moved, f"[Grp] {show} - 01.mkv")).item_id == gap
        assert [i for i, _e, _a in store.ordered("arrivals")] == [gap]
        _write(os.path.join(moved, f"[Grp] {show} - 01.{_OURS[language]}.srt"), _text(language, 1))
        _settle(b)
        filled = _look(store, language, root_b)
        assert filled["added"] == 0 and _items(store) == 1 and _waiting(store) == []
        assert store.item(gap)["availability"] == "available"
        assert store.item(gap)["rel_path"] == f"Library/{show}/[Grp] {show} - 01.{_OURS[language]}.srt"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_v2_of_a_moved_episode_is_followed_never_a_second_item(language):
    """D3 (c), S5: after the move, `- 03v2` is episode 3's text — its copy takes the v2's bytes — never a new item."""
    store, data_dir, a, b, show, moved, ids, _ra, root_b, _r = _moved_show(language)
    try:
        v2 = _write(os.path.join(moved, f"[Grp] {show} - 03v2.{_OURS[language]}.srt"), _text(language, 3, "、訂正"))
        _settle(b)
        result = _look(store, language, root_b)
        assert (result["added"], result["attached"], result["recopied"]) == (0, 1, 1) and _items(store) == 4
        assert _origin(store, v2).item_id == ids["03"]
        assert _sha(os.path.join(data_dir, *store.item(ids["03"])["rel_path"].split("/"))) == _sha(v2)
    finally:
        store.__exit__(None, None, None)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_refresh_after_the_move_changes_nothing(language):
    """A Refresh (`full=True`) of both sources after the move and the next episode: nothing added, attached, copied
    or trashed — one show still."""
    store, data_dir, a, b, show, moved, ids, root_a, root_b, _r = _moved_show(language)
    try:
        _write(os.path.join(moved, _name(show, 5, language)), _text(language, 5))
        _settle(b)
        _look(store, language, root_b)
        files, count = _library_files(data_dir), _items(store)
        for root in (root_a, root_b):
            again = _look(store, language, root, full=True)
            assert (again["added"], again["attached"], again["recopied"]) == (0, 0, 0)
        assert _library_files(data_dir) == files and _items(store) == count == 5 and _works(store) == 1
    finally:
        store.__exit__(None, None, None)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("picked", ["the show's folder", "the folder above it"])
def test_a_show_moved_where_surasura_doesnt_read_joins_it_once_its_folder_is_added(language, picked):
    """MV-1's bound and MV-2: `[Grp] Show` moved to a folder no source holds — nothing joins, nothing is added (its
    items keep their copies); the folder picked (*Find its folder*: the show's folder itself, its files then at the
    source's top and read by their names, or the folder above it) is added as a read folder — its files are their
    items, its next episode joins the show."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    folder = f"[Grp] {show}"
    a, c = _drive("driveA"), _drive("driveC")
    _seed(language, a, folder)
    with store:
        root_a = store.add_source(a)
        ids = _look(store, language, root_a, first=True)["ids"]
        work = _work(store, ids[0])
        assert all(store.item(i)["rel_path"].startswith(f"Library/{folder}/") for i in ids)
        moved = os.path.join(c, LEVEL, folder)
        _move(os.path.join(a, folder), moved)
        unread = _look(store, language, root_a, full=True)
        assert (unread["added"], unread["attached"]) == (0, 0) and _items(store) == 4
        root_c = store.add_source(moved if picked == "the show's folder" else os.path.dirname(moved))
        found = _look(store, language, root_c)
        assert (found["added"], found["attached"]) == (0, 4) and _items(store) == 4
        _write(os.path.join(moved, _name(show, 5, language)), _text(language, 5))
        _settle(c)
        again = _look(store, language, root_c)
        assert again["added"] == 1 and _items(store) == 5 and _works(store) == 1
        assert _work(store, again["ids"][0]) == work
        assert store.item(again["ids"][0])["rel_path"].startswith(f"Library/{folder}/")


# --- the guards: never a guess ------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_folder_holding_two_shows_files_joins_neither(language):
    """Its files are two shows' items: the folder's show is its own (as today), and stays so after a look recorded
    them — its new episode is a show of its own, never one of the two."""
    store, data_dir = _empty(language)
    x, y = _SHOWS[language]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, x, (1,))
    _write(os.path.join(a, y, _name(y, 1, language)), _text(language, 2))
    mixed = os.path.join(b, LEVEL, "Mixed")
    with store:
        _look(store, language, store.add_source(a), first=True)
        os.makedirs(mixed)
        shutil.copy2(os.path.join(a, x, _name(x, 1, language)), mixed)
        shutil.copy2(os.path.join(a, y, _name(y, 1, language)), mixed)
        _write(os.path.join(mixed, _name("Mixed", 2, language)), _text(language, 3))
        _settle(b)
        root_b = store.add_source(b)
        result = _look(store, language, root_b)
        assert (result["added"], result["attached"]) == (1, 2)
        assert store.item(result["ids"][0])["rel_path"].startswith(f"Library/{LEVEL}/Mixed/")
        _write(os.path.join(mixed, _name("Mixed", 3, language)), _text(language, 4))
        _settle(b)
        later = _look(store, language, root_b)
        assert later["added"] == 1 and store.item(later["ids"][0])["rel_path"].startswith(f"Library/{LEVEL}/Mixed/")
        assert _works(store) == 3


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_show_named_like_an_old_one_with_no_shared_bytes_is_its_own_show(language):
    """A name is never the proof (the rejected name rule): `B/2024 Fall/Show` holding other texts than `A/Show`'s is a
    show of its own."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, show, (1, 2))
    with store:
        first = _look(store, language, store.add_source(a), first=True)
        for n in (1, 2):
            _write(os.path.join(b, LEVEL, show, _name(show, n, language)), _text(language, n, " 別の版"))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        assert result["added"] == 2 and _works(store) == 2
        assert all(store.item(i)["rel_path"].startswith(f"Library/{LEVEL}/{show}/") for i in result["ids"])
        assert _work(store, result["ids"][0]) != _work(store, first["ids"][0])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_of_a_show_already_in_is_never_re_aliased_by_a_stray_copy(language):
    """A folder whose own show has items already keeps it: a byte copy of another show's episode in it never moves
    that show's next episode into the other show."""
    store, data_dir = _empty(language)
    x, y = _SHOWS[language]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, x, (1,))
    _seed(language, a, y, (1,))
    with store:
        _look(store, language, store.add_source(a), first=True)
        os.makedirs(os.path.join(b, y))
        shutil.copy2(os.path.join(a, x, _name(x, 1, language)), os.path.join(b, y, "stray copy.srt"))
        _write(os.path.join(b, y, _name(y, 2, language)), _text(language, 3))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        assert (result["added"], result["attached"]) == (1, 1)
        assert store.item(result["ids"][0])["rel_path"] == f"Library/{y}/{_name(y, 2, language)}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_of_a_show_already_in_keeps_it_though_most_of_its_texts_are_another_shows_copies(language):
    """A folder whose own show has items already keeps it, though two of its three texts are byte copies of another
    show's episodes: the majority of texts would name that other show, but a show already in never moves (the guard
    at the top of `_joined`), so Y's next episode stays in Y."""
    store, data_dir = _empty(language)
    x, y = _SHOWS[language]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, x, (2, 3))                         # texts of their own: Y's episode 1 shares no bytes with X's
    _seed(language, a, y, (1,))
    with store:
        _look(store, language, store.add_source(a), first=True)
        os.makedirs(os.path.join(b, y))
        shutil.copy2(os.path.join(a, x, _name(x, 2, language)), os.path.join(b, y, "stray copy 1.srt"))
        shutil.copy2(os.path.join(a, x, _name(x, 3, language)), os.path.join(b, y, "stray copy 2.srt"))
        _write(os.path.join(b, y, _name(y, 2, language)), _text(language, 7))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        rows = [store.item(i)["rel_path"] for i in result["ids"]]
        ep2 = [r for r in rows if r.endswith(_name(y, 2, language))]
        assert ep2 == [f"Library/{y}/{_name(y, 2, language)}"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_loose_files_at_a_sources_top_keep_the_show_their_names_give(language):
    """A loose file's show is its name's (S12), never its neighbours' items: a byte copy of an episode beside it at
    the source's top never pulls a file of another name into that show."""
    store, data_dir = _empty(language)
    x = _SHOWS[language][0]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, x, (1,))
    with store:
        _look(store, language, store.add_source(a), first=True)
        shutil.copy2(os.path.join(a, x, _name(x, 1, language)), b)
        _write(os.path.join(b, _name("Kawabe", 1, language)), _text(language, 2))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        assert (result["added"], result["attached"]) == (1, 1)
        assert store.item(result["ids"][0])["rel_path"] == f"Library/Kawabe/{_name('Kawabe', 1, language)}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_moved_folder_holding_only_another_release_of_an_episode_joins_its_show_that_release_a_version(language):
    """PROVISIONAL: another release's bytes prove the folder's show too (a version's record names its episode's
    item): `B/2024 Fall/Show` holding only `[ZZ] - 01` (a version of episode 1) and a new `[ZZ] - 02` — the release
    stays a version of episode 1, never a second episode 1, and 02 joins the show."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    pick = _write(os.path.join(a, show, _name(show, 1, language)), _text(language, 1))
    alt = _write(os.path.join(a, show, _name(show, 1, language, group="ZZ")), _text(language, 1, " ZZ"))
    with store:
        first = _look(store, language, store.add_source(a), first=True)
        assert first["added"] == 1 and _origin(store, alt).version and not _origin(store, pick).version
        moved = os.path.join(b, LEVEL, show)
        os.makedirs(moved)
        shutil.move(alt, moved)
        _write(os.path.join(moved, _name(show, 2, language, group="ZZ")), _text(language, 2))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        assert result["added"] == 1 and _items(store) == 2 and _works(store) == 1
        assert store.item(result["ids"][0])["rel_path"] == f"Library/{show}/{_name(show, 2, language, group='ZZ')}"
        release = _origin(store, os.path.join(moved, os.path.basename(alt)))
        assert release.version and release.item_id == first["ids"][0]


# --- FIX1 (the moves review set): one stray file never decides a folder's show (MV-A1, MV-A2) ----------------------- #
# Why: a single byte copy of another show's episode (a backup, a misfiled file) in a new show's folder, or in a mixed
# folder below a source (`NAS/Anime/`), filed the whole folder under that other show — its episodes copied into the
# other show's `Library` folder and studied as its words, for good (the recorded origins kept pulling the next ones
# in), and with generic names (`Episode 01`) swallowed as that show's versions: never counted, never shown. The rule
# now: most of the folder's texts are the show's items, or the folder's name ends in the show's name.

def _stray_copy_beside_a_new_show(language, store, name):
    """X's 01–02 taken in from A; `B/<name>/` gets a byte copy of X's 01 and Y's own 01–02 -> (X's work, B's root
    id, the folder)."""
    x, y = _SHOWS[language]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, x, (1, 2))
    first = _look(store, language, store.add_source(a), first=True)
    folder = os.path.join(b, name)
    os.makedirs(folder)
    shutil.copy2(os.path.join(a, x, _name(x, 1, language)), os.path.join(folder, "stray copy.srt"))
    _write(os.path.join(folder, _name(y, 1, language)), _text(language, 7))
    _write(os.path.join(folder, _name(y, 2, language)), _text(language, 8))
    _settle(b)
    return _work(store, first["ids"][0]), store.add_source(b), folder


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("where", ["a new show's folder", "a mixed folder below the source"])
def test_one_stray_copy_of_another_shows_episode_never_files_a_folder_under_that_show(language, where):
    """MV-A1: `B/<Y>/` (or `B/Anime/`) holding one byte copy of X's episode 1 and Y's two episodes: Y's episodes are
    a show of their own — their copies never in `Library/<X>/`, never X's title — and stay so on the next look, when
    the copy is recorded on X's item (its next episode too). The copy itself is X's episode 1 found again."""
    store, data_dir = _empty(language)
    x, y = _SHOWS[language]
    with store:
        name = "Anime" if where.startswith("a mixed") else y
        xwork, root_b, folder = _stray_copy_beside_a_new_show(language, store, name)
        result = _look(store, language, root_b)
        assert (result["added"], result["attached"]) == (2, 1)
        new = [i for i in result["ids"] if _work(store, i) != xwork]
        assert len(new) == 2 and all(store.item(i)["rel_path"].startswith(f"Library/{name}/") for i in new)
        assert _works(store) == 2
        _write(os.path.join(folder, _name(y, 3, language)), _text(language, 9))
        _settle(os.path.dirname(folder))
        later = _look(store, language, root_b)
        assert later["added"] == 1 and store.item(later["ids"][0])["rel_path"].startswith(f"Library/{name}/")
        assert _work(store, later["ids"][0]) == _work(store, new[0]) != xwork


@pytest.mark.parametrize("language", LANGUAGES)
def test_half_of_a_folders_texts_is_not_most_of_them(language):
    """FIX1's majority is MORE than half: `B/<Y>/` holding a byte copy of X's episode 1 and Y's one episode (one of
    two) is still Y's own show."""
    store, data_dir = _empty(language)
    x, y = _SHOWS[language]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, x, (1,))
    with store:
        xwork = _work(store, _look(store, language, store.add_source(a), first=True)["ids"][0])
        os.makedirs(os.path.join(b, y))
        shutil.copy2(os.path.join(a, x, _name(x, 1, language)), os.path.join(b, y, "stray copy.srt"))
        _write(os.path.join(b, y, _name(y, 1, language)), _text(language, 7))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        new = [i for i in result["ids"] if _work(store, i) != xwork]
        assert result["added"] == 1 and len(new) == 1
        assert store.item(new[0])["rel_path"] == f"Library/{y}/{_name(y, 1, language)}"


ENGLISH = ("1\n00:00:01,000 --> 00:00:03,000\nWhere are you going so late at night?\n\n"
           "2\n00:00:04,000 --> 00:00:06,500\nJust to the station. I'll be back soon.\n\n"
           "3\n00:00:07,000 --> 00:00:09,000\nTake an umbrella, it looks like rain.\n")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_moved_renamed_show_with_an_english_subtitle_per_episode_stays_one_show(language):
    """The moves check (FC-1): `A/<X>/` holds each episode's subtitle of ours beside an English one (refused on the
    first look, so the store keeps no bytes of it). Moved to `B/Renamed by hand/`, only the moved texts of ours vote:
    the English ones never outvote them, so episodes 5 and 6 arriving there are X's, never a second show."""
    store, data_dir = _empty(language)
    x = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, x)
    english = lambda n: f"[Grp] {x} - {n:02d}.en.srt"
    for n in (1, 2, 3, 4):
        _write(os.path.join(a, x, english(n)), ENGLISH + f"\n4\n00:00:10,000 --> 00:00:11,000\nEpisode {n}.\n")
    with store:
        ids = _look(store, language, store.add_source(a), first=True)["ids"]
        moved = os.path.join(b, "Renamed by hand")
        _move(os.path.join(a, x), moved)
        _write(os.path.join(moved, _name(x, 5, language)), _text(language, 5))
        _write(os.path.join(moved, english(5)), ENGLISH)
        _settle(b)
        root_b = store.add_source(b)
        result = _look(store, language, root_b)
        new = [store.item(i)["rel_path"] for i in result["ids"] if i not in ids]
        assert _works(store) == 1 and new and all(r.startswith(f"Library/{x}/") for r in new), new
        _write(os.path.join(moved, _name(x, 6, language)), _text(language, 6))
        _settle(b)
        later = _look(store, language, root_b)
        assert _works(store) == 1, "the next episode too"
        assert all(store.item(i)["rel_path"].startswith(f"Library/{x}/") for i in later["ids"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_show_with_generic_episode_names_beside_one_stray_copy_is_items_never_versions(language):
    """MV-A2: names that carry no show (`Episode 01`, common for rips). X's `Episode 01–02` taken in; a new show Y's
    folder with its own `Episode 01–02` and one byte copy of X's episode 1 — Y's episodes are two new items, never
    recorded as other versions of X's episodes (no reader's: never counted, nothing to Remove)."""
    store, data_dir = _empty(language)
    x, y = _SHOWS[language]
    a, b = _drive("driveA"), _drive("driveB")
    ours = _OURS[language]
    for n in (1, 2):
        _write(os.path.join(a, x, f"Episode {n:02d}.{ours}.srt"), _text(language, n))
    with store:
        assert _look(store, language, store.add_source(a), first=True)["added"] == 2
        os.makedirs(os.path.join(b, y))
        shutil.copy2(os.path.join(a, x, f"Episode 01.{ours}.srt"), os.path.join(b, y, f"backup.{ours}.srt"))
        for n in (1, 2):
            _write(os.path.join(b, y, f"Episode {n:02d}.{ours}.srt"), _text(language, 6 + n))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        assert result["added"] == 2 and _items(store) == 4, (result, _versions(store))
        top = ls.path_key(os.path.abspath(os.path.join(b, y))) + "/"
        assert not [k for k in _versions(store) if k.startswith(top)], "never X's versions"
        assert all(store.item(i)["rel_path"].startswith(f"Library/{y}/") for i in result["ids"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_renamed_moved_folder_joins_its_show_by_most_of_its_texts(language):
    """FIX1's other half: a moved show whose folder the learner renamed (no longer the show's name) still joins it
    when most of its texts are the show's items — 4 of 5 here, its new episode with them."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, show)
    with store:
        ids = _look(store, language, store.add_source(a), first=True)["ids"]
        moved = os.path.join(b, "Renamed by hand")
        _move(os.path.join(a, show), moved)
        _write(os.path.join(moved, _name(show, 5, language)), _text(language, 5))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        assert (result["added"], result["attached"]) == (1, 4) and _works(store) == 1
        new = [i for i in result["ids"] if i not in ids]
        assert store.item(new[0])["rel_path"] == f"Library/{show}/{_name(show, 5, language)}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_named_like_a_season_of_another_show_never_joins_it_by_its_last_name(language):
    """FIX1's name rule reads the show's WHOLE name at the end of the folder's: `B/<Y>/Season 1` holding one byte
    copy of `<X>/Season 1`'s episode is never `<X>/Season 1` (both end in `Season 1`)."""
    store, data_dir = _empty(language)
    x, y = _SHOWS[language]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, os.path.join(a, x), "Season 1", (1, 2))
    with store:
        first = _look(store, language, store.add_source(a), first=True)
        assert store.item(first["ids"][0])["rel_path"].startswith(f"Library/{x}/Season 1/")
        folder = os.path.join(b, y, "Season 1")
        os.makedirs(folder)
        shutil.copy2(os.path.join(a, x, "Season 1", _name("Season 1", 1, language)), os.path.join(folder, "copy.srt"))
        _write(os.path.join(folder, _name(y, 1, language)), _text(language, 7))
        _write(os.path.join(folder, _name(y, 2, language)), _text(language, 8))
        _settle(b)
        result = _look(store, language, store.add_source(b))
        assert result["added"] == 2
        new = [i for i in result["ids"] if i not in first["ids"]]
        assert len(new) == 2 and all(store.item(i)["rel_path"].startswith(f"Library/{y}/Season 1/") for i in new)


# --- FIX1: a moved waiting video that is a cloud placeholder (MV-A4); D3 (a) by its key (M3 mutants 7, 8) ----------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_moved_waiting_video_that_is_a_cloud_placeholder_keeps_its_one_waiting_item(language, monkeypatch):
    """MV-A4: a waiting video moved under a new folder level and now a cloud placeholder (its download not here: its
    key is never read, B3) is its waiting item by its name and size — never a second waiting row in New arrivals."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][0]
    a, b = _drive("driveA"), _drive("driveB")
    _video(os.path.join(a, show, f"[Grp] {show} - 01.mkv"), body=b"\x1a\x45\xdf\xa3 placeholder video body")
    with store:
        gap = _look(store, language, store.add_source(a), first=True)["ids"][0]
        moved = os.path.join(b, LEVEL, show)
        _move(os.path.join(a, show), moved)
        size = os.path.getsize(os.path.join(moved, f"[Grp] {show} - 01.mkv"))
        monkeypatch.setattr(ls, "is_placeholder", lambda st: st.st_size == size)
        result = _look(store, language, store.add_source(b))
        assert (result["added"], result["attached"]) == (0, 1) and _waiting(store) == [gap]
        assert _origin(store, os.path.join(moved, f"[Grp] {show} - 01.mkv")).item_id == gap
        assert [i for i, _e, _a in store.ordered("arrivals")] == [gap]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_moved_waiting_video_is_its_own_item_never_another_waiting_one_of_its_size(language):
    """D3 (a) by content key (M3 mutant 7): two shows' waiting videos of one size, other bytes — Y's moved under a new
    level is Y's waiting item; X's stays where it was, its own."""
    store, data_dir = _empty(language)
    x, y = _SHOWS[language]
    a, b = _drive("driveA"), _drive("driveB")
    _video(os.path.join(a, x, f"[Grp] {x} - 01.mkv"), body=b"\x1a\x45\xdf\xa3 video of the first show")
    _video(os.path.join(a, y, f"[Grp] {y} - 01.mkv"), body=b"\x1a\x45\xdf\xa3 video of the other show")
    with store:
        first = _look(store, language, store.add_source(a), first=True)
        by_show = {store.item(i)["rel_path"].split("/")[1]: i for i in first["ids"]}
        moved = os.path.join(b, LEVEL, y)
        _move(os.path.join(a, y), moved)
        result = _look(store, language, store.add_source(b))
        assert (result["added"], result["attached"]) == (0, 1)
        assert _origin(store, os.path.join(moved, f"[Grp] {y} - 01.mkv")).item_id == by_show[y]
        assert _origin(store, os.path.join(a, x, f"[Grp] {x} - 01.mkv")).item_id == by_show[x]
        assert sorted(_waiting(store)) == sorted(by_show.values())


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_of_a_moved_waiting_video_with_its_subtitle_never_takes_the_waiting_item_unfilled(language):
    """M3 mutant 8 (`_videos_taken`): the moved waiting video recorded on its waiting item maps no video to it — so a
    copy of that video elsewhere with its subtitle, later in the same look, never attaches its text to the waiting
    item while it stays waiting (a text no reader would see): it fills the gap, or is an item of its own."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]                               # sorted before `zz copy`: its batch is first
    a, b = _drive("driveA"), _drive("driveB")
    _video(os.path.join(a, show, f"[Grp] {show} - 01.mkv"))
    with store:
        gap = _look(store, language, store.add_source(a), first=True)["ids"][0]
        moved = os.path.join(b, LEVEL, show)
        _move(os.path.join(a, show), moved)
        other = os.path.join(b, "zz copy")
        os.makedirs(other)
        shutil.copy2(os.path.join(moved, f"[Grp] {show} - 01.mkv"), os.path.join(other, "zz copy - 01.mkv"))
        _write(os.path.join(other, f"zz copy - 01.{_OURS[language]}.srt"), _text(language, 1))
        _settle(b)
        _look(store, language, store.add_source(b))
        assert _origin(store, os.path.join(moved, f"[Grp] {show} - 01.mkv")).item_id == gap
        texts = [o for o in store.origins().values() if o.item_id == gap and ls.is_content_name(o.origin.lower())]
        assert store.item(gap)["availability"] == "available" or not texts, texts


# --- FIX1: D5's mark only for a move (MV-A5, G5; M4 mutants 8, 9) --------------------------------------------------- #

def _counts(store):
    return [s["items"] for s in store.sources(all=True)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_v2_found_elsewhere_while_the_original_is_briefly_gone_marks_nothing(language):
    """MV-A5: an original briefly absent (mid-move in Explorer, a sync client rewriting it) while another file of its
    item turns up — a `v2` in B's folder of the show — is no move: the v2's bytes are not the original's, so its
    record stays live and A still counts it."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, show, (1,))
    original = os.path.join(a, show, _name(show, 1, language))
    with store:
        _look(store, language, store.add_source(a), first=True)
        aside = os.path.join(os.environ["SURASURA_TEST_ROOT"], "away.srt")
        os.replace(original, aside)
        try:
            _write(os.path.join(b, show, f"[Grp] {show} - 01v2.{_OURS[language]}.srt"), _text(language, 1, "、訂正"))
            _settle(b)
            result = _look(store, language, store.add_source(b))
            assert result["attached"] == 1
            assert _origin(store, original).moved_to is None
        finally:
            os.replace(aside, original)
        assert _counts(store) == [1, 1]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_original_that_cant_be_read_is_never_marked_moved(language, monkeypatch):
    """D5 (M4 mutant 9): only a file GONE from a reachable folder moved; one that can't be read (access denied, a
    share's hiccup) may be there — its record stays live."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, show, (1, 2))
    with store:
        _look(store, language, store.add_source(a), first=True)
        olds = [os.path.join(a, show, _name(show, n, language)) for n in (1, 2)]
        shutil.copytree(os.path.join(a, show), os.path.join(b, show), copy_function=shutil.copy2)
        _settle(b)
        real = os.stat
        denied = {ls.path_key(os.path.abspath(p)) for p in olds}

        def stat(path, *args, **kw):
            if isinstance(path, str) and ls.path_key(os.path.abspath(path)) in denied:
                raise PermissionError(13, "Access is denied", path)
            return real(path, *args, **kw)
        monkeypatch.setattr(os, "stat", stat)
        try:
            result = sources.scan(store, language, store.add_source(b))
        finally:
            monkeypatch.setattr(os, "stat", real)
        assert result["attached"] == 2
        assert all(_origin(store, p).moved_to is None for p in olds)


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_version_left_behind_is_never_marked_moved(language):
    """D5 (M4 mutant 8): the item's other version (`[ZZ] - 01`, no reader's) gone from A while its pick moved to B —
    only the pick's record says it moved; a version's record is never marked (Connect never reads it)."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    pick = _write(os.path.join(a, show, _name(show, 1, language)), _text(language, 1))
    alt = _write(os.path.join(a, show, _name(show, 1, language, group="ZZ")), _text(language, 1, " ZZ"))
    with store:
        _look(store, language, store.add_source(a), first=True)
        assert _origin(store, alt).version
        os.makedirs(os.path.join(b, show))
        shutil.move(pick, os.path.join(b, show))
        os.remove(alt)
        _settle(b)
        assert _look(store, language, store.add_source(b))["attached"] == 1
        assert _origin(store, pick).moved_to is not None, "the pick moved"
        assert _origin(store, alt).moved_to is None, "a version is never marked"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unplugged_old_folder_is_asked_once_before_any_of_its_files(language, monkeypatch):
    """G5: a show copied to B while A's share is unplugged — every new link would stat its old original on the
    dead share first (a network timeout each). The source folder's reach is asked first, once a look, and none of its
    files is touched."""
    store, data_dir = _empty(language)
    show = _SHOWS[language][1]
    a, b = _drive("driveA"), _drive("driveB")
    _seed(language, a, show)
    with store:
        _look(store, language, store.add_source(a), first=True)
        shutil.copytree(os.path.join(a, show), os.path.join(b, show), copy_function=shutil.copy2)
        _settle(b)
        root_b = store.add_source(b)
        os.rename(a, a + " (unplugged)")
        try:
            top = ls.path_key(os.path.abspath(a)).rstrip("/") + "/"
            asked, touched = [], []
            real_lost, real_stat = sources._lost, os.stat

            def lost(root):
                asked.append(ls.path_key(os.path.abspath(root)))
                return real_lost(root)

            def stat(path, *args, **kw):
                if isinstance(path, str) and ls.path_key(os.path.abspath(path)).startswith(top):
                    touched.append(path)
                return real_stat(path, *args, **kw)
            monkeypatch.setattr(sources, "_lost", lost)
            monkeypatch.setattr(os, "stat", stat)
            try:
                result = sources.scan(store, language, root_b)
            finally:
                monkeypatch.setattr(os, "stat", real_stat)
            assert result["attached"] == 4
            assert asked.count(ls.path_key(os.path.abspath(a))) == 1, asked
            assert touched == [], "no file on the unplugged share was asked about"
        finally:
            os.rename(a + " (unplugged)", a)


# --- FIX1 (S19): a look where nothing changed writes nothing -------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_look_after_the_move_where_nothing_changed_writes_nothing_to_the_store(language):
    """S19: after the move is taken in, the next looks of both sources (a quick one and a Refresh) find nothing new —
    and write nothing: no row, no record, no meta (the store's change counter unmoved)."""
    store, data_dir, a, b, show, moved, ids, root_a, root_b, _r = _moved_show(language)
    try:
        _look(store, language, root_b)
        _look(store, language, root_a)
        before = store.conn.total_changes, store.meta()
        for root in (root_a, root_b):
            for full in (False, True):
                again = _look(store, language, root, full=full)
                assert (again["added"], again["attached"], again["recopied"]) == (0, 0, 0)
        assert (store.conn.total_changes, store.meta()) == before, "a look that found nothing wrote nothing"
    finally:
        store.__exit__(None, None, None)
