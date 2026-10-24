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
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import (_OURS, _SHOWS, _current, _drive, _empty, _fresh_module_state, _items,  # noqa: F401
                                     _library_files, _look, _settle, _sha, _text, _video, _write)

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
def test_loose_files_at_a_sources_top_keep_the_show_their_names_give(language):
    """A loose file's show is its name's (S12), never its neighbours' items: a byte copy of an episode beside it at
    the source's top never pulls it into that show."""
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
