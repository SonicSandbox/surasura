"""The video index lists a folder only when its modified time moved (P2.5 row 2.5.8, `app/connect/videos.py`
`Index.refresh`; 06-edges E15, the lean held: "checked when Connect starts"; S19 *update only what changed*).

What each test holds still:

  * a second Connect start, with nothing changed, lists no folder again: one stat per folder, `listed == 0`,
    `refresh` says nothing changed, and the index file is not written. A wrong answer re-reads every folder of a
    large library at every start;
  * a video added to one folder moves only that folder's time: exactly that folder is listed again (`listed == 1`,
    the other folder is only stat-ed), and the new video is found by its name. A wrong answer either misses the new
    video or re-lists the whole library for one file.

The video files are tiny real files in `tmp_path` (nothing is opened); the names are real episode names.
"""
import os

from app.connect import videos


def _video(folder, name, size=16):
    """A small file with the Matroska magic (never opened by the index, only sized and named)."""
    path = os.path.join(str(folder), name)
    with open(path, "wb") as f:
        f.write(b"\x1aE\xdf\xa3" + b"0" * (size - 4))
    return path


def _moved_forward(folder):
    """Set the folder's modified time a second past its current one, so the change is never lost to the clock's
    resolution."""
    t = os.stat(folder).st_mtime_ns + 10 ** 9
    os.utime(folder, ns=(t, t))


def test_unchanged_folder_is_not_listed_again_and_index_file_is_not_rewritten(tmp_path):
    # the first start lists the folder and saves the index; a second start on the same index file, with the same
    # folder and no change in it, must do nothing at all
    folder = tmp_path / "動画"
    folder.mkdir()
    _video(folder, "上層部 - 03.mkv")
    index_file = str(tmp_path / "videos-ja.json")

    first = videos.Index("ja", path=index_file)
    assert first.refresh([str(folder)], []) is True
    assert first.listed == 1
    saved_at = os.stat(index_file).st_mtime_ns

    second = videos.Index("ja", path=index_file)
    assert second.refresh([str(folder)], []) is False, "nothing changed: the index is not saved again"
    assert second.listed == 0, "an unchanged folder is one stat, never a listing"
    assert os.stat(index_file).st_mtime_ns == saved_at


def test_added_video_lists_only_its_own_folder_and_is_found_by_name(tmp_path):
    # two folders are indexed; a video added to one moves that folder's time. Only that folder is listed again,
    # and the new video is found; the other folder is left alone (its own stat only)
    episodes = tmp_path / "動画"
    other = tmp_path / "別の動画"
    episodes.mkdir()
    other.mkdir()
    _video(episodes, "上層部 - 03.mkv")
    _video(other, "気配 - 01.mkv")
    index_file = str(tmp_path / "videos-ja.json")

    first = videos.Index("ja", path=index_file)
    assert first.refresh([str(episodes), str(other)], []) is True
    assert first.listed == 2

    _video(episodes, "上層部 - 04.mkv")
    _moved_forward(episodes)

    second = videos.Index("ja", path=index_file)
    assert second.refresh([str(episodes), str(other)], []) is True
    assert second.listed == 1, "only the folder whose time moved is listed again"
    found = second.find(["上層部 - 04.mkv"])
    assert found is not None
    assert os.path.basename(found) == "上層部 - 04.mkv"
