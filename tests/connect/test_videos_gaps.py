"""The re-list's cap at its edge (P3.1 row 3.1.7), a gap the P3.1 mutant pass found (2026-10-11).

What a wrong answer would cost: a folder holding exactly as many entries as the re-list has left is skipped as "over
the cap", so a video moved into it on a NAS share stays *No video* for the run. Real files in a temp folder."""
import os

from app.connect import videos
from tests.connect.test_videos import _hold, _index, _same, _video


def test_a_folder_with_exactly_the_entries_left_is_listed_again(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "RELIST_MAX", 3)
    added = str(tmp_path / "NAS" / "ぼっち・ざ・ろっく")
    _video(os.path.join(added, "Bocchi - 01.mkv"))
    _video(os.path.join(added, "Bocchi - 02.mkv"))
    index = _index(tmp_path, shallow=[added], deep=[])
    held = os.stat(added)
    moved = _video(os.path.join(added, "Bocchi - 03.mkv"))    # three entries now: exactly the cap
    _hold(added, held)
    assert _same(index.find(["Bocchi - 03.mkv"]), moved)
