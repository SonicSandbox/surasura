"""A10 in the look (Kura-G, 2026-11-07, PROVISIONAL): his Code Geass R2 holds `Code Geass Hangyaku no Lelouch 01.srt`
… `10.srt` beside `Code_Geass_Ep01_<title>_[720p,BluRay,x264]_-_gg-THORA.mkv` … `Ep25`. The subtitles write a bare
number (no ` - `, `Ep`, `E` before it), so the look read no episode in them and paired none; the window, which reads
every bare number, called them episodes 1–10. The look now reads a bare number where the show's names prove it
(`episode_names.numbered`: two or more names that differ only by it). The scenario matrix holds the new-file rows; this
file holds his library as it is: the ten already in, unpaired, are paired at the next look — the same items, their
order and marks untouched, nothing new made.

What a wrong answer would cost: his R2 never opening its videos (Connect finds no video, no card audio); or a subtitle
paired with another episode's video. Every test runs for Japanese and Chinese, with real texts from
tests/Test Resources/ under the per-test SURASURA_TEST_ROOT.
"""
import os

import pytest

from app import episode_names as en
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look  # noqa: F401
from tests.test_sources_scenarios import _NAMES, _make, _state


def _items(store):
    return store.conn.execute("SELECT id, rel_path, tier, ord, watched, work_id FROM items ORDER BY id").fetchall()


@pytest.mark.parametrize("language", LANGUAGES)
def test_his_unpaired_bare_numbered_subtitles_are_paired_at_the_next_look_and_nothing_else_moves(language,
                                                                                                 monkeypatch):
    """The first look as the build before this one read it (no bare number: `numbered` answers nothing): two items,
    no video. The next look pairs each with its episode's video (A19's late video, recorded on its origin): the same
    items, tiers, order, watched marks and titles; no new item; a Refresh after changes nothing."""
    store, data_dir = _empty(language)
    drive = _drive("Anime")
    show = _NAMES[language]["S"]
    vids = [f"{show}_Ep{n:02d}_The_Title_[720p,BluRay,x264]_-_gg" for n in (1, 2)]
    made = {}
    _make(drive, [(f"{show}/{v}.mkv", "V") for v in vids]
          + [(f"{show}/{show} Hangyaku {n:02d}.srt", "J") for n in (1, 2)], language, made)
    with store:
        rid = store.add_source(drive)
        with monkeypatch.context() as m:
            m.setattr(en, "numbered", lambda names: set())
            _look(store, language, rid, first=True)
        before = _state(store, data_dir, drive, made)
        assert all(" @ " not in v for v in before[1].values()), "the build before: none paired"
        store.set_watched([store.conn.execute("SELECT MIN(id) FROM items").fetchone()[0]])
        items = _items(store)
        _look(store, language, rid, full=True)
        after = _state(store, data_dir, drive, made)
        assert after[1] == {f"{show}/{show} Hangyaku {n:02d}.srt":
                            f"{show}/{show} Hangyaku {n:02d}.srt @ {show}/{vids[n - 1]}.mkv" for n in (1, 2)}
        assert _items(store) == items
        _look(store, language, rid, full=True)
        assert _state(store, data_dir, drive, made) == after and _items(store) == items


@pytest.mark.parametrize("language", LANGUAGES)
def test_setups_choose_a_file_offers_a_videos_bare_numbered_subtitle(language):
    """Setup's *Choose a file…* given a video (`subtitles_for_video`) reads the same rule from the video's folder: the
    subtitle of its episode, never another's."""
    from app.sources import subtitles_for_video
    drive = _drive("Anime")
    show = _NAMES[language]["S"]
    vids = [f"{show}_Ep{n:02d}_The_Title_[720p,BluRay,x264]_-_gg" for n in (1, 2, 3)]
    made = {}
    _make(drive, [(f"{show}/{v}.mkv", "V") for v in vids]
          + [(f"{show}/{show} Hangyaku {n:02d}.srt", "J") for n in (1, 2)], language, made)
    folder = os.path.join(drive, show)
    got = [os.path.basename(p) for p in subtitles_for_video(os.path.join(folder, vids[1] + ".mkv"), language)]
    assert got == [f"{show} Hangyaku 02.srt"]
    assert subtitles_for_video(os.path.join(folder, vids[2] + ".mkv"), language) == []
