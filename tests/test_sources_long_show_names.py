"""One show, one title, however long its name (Kura-NA, a Send report of 2026-11-18: New arrivals showed hato's find and
Surasura's own find of the same show as two rows). A loose episode's `Library/<show>` folder name is cut to
`extract.NAME_LIMIT` characters (Windows' 260-character paths), and the "same show?" key was taken from the CUT name —
so a show named longer than that never met its own folder in the source (a8: `Show/` beside `Show - 15.mkv`), its
title already in the library, or hato's title of it (hato names it by its record's show, uncut). Each became a second
title of one show: two rows in New arrivals, two places in Current.

Why these matter: a second title splits one show's episodes, its order and its cards between two rows, and a learner
who removes or skips one row still sees the other. Every test runs for Japanese and Chinese with real subtitles from
tests/Test Resources/, made-up show names longer than the cut, and a few bytes as a fake video, under the per-test
SURASURA_TEST_ROOT.
"""
import os

import pytest

from app import extract
from app import library_store as ls
from app import sources
from app.connect import videos
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _look, _text, _video, _write

# made-up show names longer than the folder-name cut, as release groups write them
_LONG = {"ja": "Hoshizora Kissa no Tensei Juukishi wa Game Chishiki de Musou suru",
         "zh": "Lanterns of Qinghe and the Night Market Scholar Who Remembered Spring"}


@pytest.fixture(autouse=True)
def _fresh_module_state():
    """Each test starts as a new run of the app: no look made yet this run, no scan running."""
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


def _release(show, episode, tag):
    return f"[SubsPlease] {show} - {episode:02d} (1080p) [{tag}]"


def _episode(folder, language, episode, tag, video=True):
    """A release's subtitle (and its fake video) in `folder` -> the subtitle's path."""
    name = _release(_LONG[language], episode, tag)
    if video:
        _video(os.path.join(folder, name + ".mkv"), body=b"\x1a\x45\xdf\xa3 fake matroska %d " % episode)
    return _write(os.path.join(folder, name + ".srt"), _text(language, episode))


def _titles(store):
    """{work id: [item ids]} of the live items."""
    out = {}
    for item_id, work in store.conn.execute("SELECT id, work_id FROM items ORDER BY id"):
        out.setdefault(work, []).append(item_id)
    return out


def _hato(language, data_dir, episode, tag):
    """hato's hand-over of one more episode: its subtitle in its drop folder, its record naming the show uncut."""
    show = _LONG[language]
    name = _release(show, episode, tag)
    path = _write(os.path.join(data_dir, *ls.HATO_FOLDER.split("/"), show, name + ".srt"), _text(language, episode),
                  age=0)
    record = {"schema": 1, "content_key": f"v1-kura-na-{language}-{episode}", "producer": "hato",
              "video_path": f"D:/Downloads/{name}.mkv", "video_size": 1473922811,
              "show": {"title": show, "season": 1, "episode": episode}}
    return path, record


def test_the_names_here_are_longer_than_the_cut():
    """(The other tests prove nothing unless the cut changes these names.)"""
    for show in _LONG.values():
        assert len(show) > extract.NAME_LIMIT and extract.clean_name(show) != show


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_loose_episode_of_a_long_named_show_joins_its_folder_in_the_same_source(language):
    """a8 with a long name: the batch in `<show>/`, the week's release loose beside it — one title, its copy in the
    folder's `Library/<show>`."""
    store, data_dir = _empty(language)
    with store:
        src = _drive("downloads")
        _episode(os.path.join(src, _LONG[language]), language, 14, "DCA181BE")
        _episode(src, language, 15, "3EF0C59F")
        root = store.add_source(src)
        _look(store, language, root, first=True)
        titles = _titles(store)
        assert len(titles) == 1 and len(next(iter(titles.values()))) == 2
        folders = {os.path.dirname(r) for (r,) in store.conn.execute("SELECT rel_path FROM items")}
        assert folders == {f"{ls.CONTENT_FOLDER}/{_LONG[language]}"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_loose_episode_of_a_long_named_show_joins_the_title_already_in(language):
    """The show's title came in from another folder (its batch read earlier, from another source): the loose release
    found later is that title's, not a second one named by the cut."""
    store, data_dir = _empty(language)
    with store:
        batch = _drive("batches")
        _episode(os.path.join(batch, _LONG[language]), language, 14, "DCA181BE")
        _look(store, language, store.add_source(batch), first=True)
        weekly = _drive("weekly")
        _episode(weekly, language, 15, "3EF0C59F")
        _look(store, language, store.add_source(weekly))
        titles = _titles(store)
        assert len(titles) == 1 and len(next(iter(titles.values()))) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_hato_after_a_loose_long_named_release_joins_its_title(language):
    """Surasura's look found the week's release first (loose: its copy's folder named by the cut); hato then hands over
    the next episode naming the show uncut — the same title, never a second row in New arrivals."""
    store, data_dir = _empty(language)
    with store:
        src = _drive("downloads")
        _episode(src, language, 15, "3EF0C59F")
        _look(store, language, store.add_source(src))
        path, record = _hato(language, data_dir, 16, "019F4E4B")
        change = store.register(path, record)
        assert change.added
        titles = _titles(store)
        assert len(titles) == 1 and len(next(iter(titles.values()))) == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_loose_long_named_release_after_hato_joins_hatos_title(language):
    """hato handed over an episode first (its title named by its record, uncut, no folder of its own); Surasura's look
    then finds the next release loose — that title's."""
    store, data_dir = _empty(language)
    with store:
        path, record = _hato(language, data_dir, 14, "DCA181BE")
        assert store.register(path, record).added
        src = _drive("downloads")
        _episode(src, language, 15, "3EF0C59F")
        _look(store, language, store.add_source(src))
        titles = _titles(store)
        assert len(titles) == 1 and len(next(iter(titles.values()))) == 2
