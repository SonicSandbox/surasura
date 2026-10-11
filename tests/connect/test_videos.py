"""Where Connect looks for a moved video (P2.5 row 2.5.8; G1.3-12, 06-edges E15): a video is found by its name in the
folders the library's pairs use and the folders you add, and Connect never guesses between two.

What a wrong answer would cost:
  * a video moved into an added folder (two subfolders deep) must be found, or the card waits for a file that is
    there; a video beside another paired video must be found too;
  * a video that is gone, or a cloud placeholder (never opened: a read would download it), is *No video*, never a
    file Connect couldn't play;
  * two files of one name in two indexed folders is *No video* — a guess would mine the wrong episode into the
    learner's cards. Only a size that picks exactly one of them may choose.

The folders and video files are real files in a temp folder (names like `Bocchi - 03.mkv`, tiny bytes); the
placeholder is simulated by patching `runner._on_disk` for that one path only.
"""
import os

from app.connect import runner, videos

VIDEO_HEADER = b"\x1aE\xdf\xa3"          # the Matroska magic: the bytes a real .mkv starts with


def _video(path, size=120):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(VIDEO_HEADER + b"\0" * (size - len(VIDEO_HEADER)))
    return path


def _index(tmp_path, shallow, deep):
    index = videos.Index("ja", path=str(tmp_path / "videos-ja.json"))
    index.refresh(shallow=shallow, deep=deep)
    return index


def _same(path, expected):
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(expected))


def test_moved_and_beside_videos_are_found_while_gone_and_placeholder_are_not(tmp_path, monkeypatch):
    """Of four names, exactly two are found: the one moved two subfolders deep into an added folder and the one
    beside a paired video. The gone one and the cloud placeholder give None — a placeholder is never opened."""
    paired = str(tmp_path / "Bocchi the Rock" / "S01")
    added = str(tmp_path / "Moved")
    _video(os.path.join(paired, "Bocchi - 01.mkv"))
    beside = _video(os.path.join(paired, "Bocchi - 05.mkv"))
    moved = _video(os.path.join(added, "season two", "extras", "Bocchi - 03.mkv"))
    placeholder = _video(os.path.join(added, "Bocchi - 07.mkv"))
    gone = _video(os.path.join(added, "Bocchi - 09.mkv"))
    index = _index(tmp_path, shallow=[paired], deep=[added])
    os.remove(gone)     # indexed, then deleted: its stale entry must not be found

    real_on_disk = runner._on_disk

    def on_disk(path):
        # a cloud placeholder: there, but never opened (RD-S1)
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(placeholder)):
            return False
        return real_on_disk(path)

    monkeypatch.setattr(runner, "_on_disk", on_disk)

    assert _same(index.find(["Bocchi - 03.mkv"]), moved)
    assert _same(index.find(["Bocchi - 05.mkv"]), beside)
    assert index.find(["Bocchi - 07.mkv"]) is None      # placeholder
    assert index.find(["Bocchi - 09.mkv"]) is None      # gone: indexed, then removed from disk


def test_same_name_in_two_indexed_folders_is_no_video_unless_size_picks_one(tmp_path):
    """Two files named `Bocchi - 03.mkv` (sizes 100 and 200) in the paired folder and the added folder: without a
    size Connect guesses nothing (None); with the pairing's size exactly one fits and is returned."""
    paired = str(tmp_path / "Bocchi the Rock" / "S01")
    added = str(tmp_path / "Moved")
    first = _video(os.path.join(paired, "Bocchi - 03.mkv"), size=100)
    _video(os.path.join(added, "Bocchi - 03.mkv"), size=200)
    index = _index(tmp_path, shallow=[paired], deep=[added])

    assert index.find(["Bocchi - 03.mkv"]) is None
    assert _same(index.find(["Bocchi - 03.mkv"], size=100), first)
