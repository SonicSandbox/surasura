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


# --- a share whose folder times don't move (P3.1 row 3.1.7): the capped re-list, once a run -------------------------

def _hold(folder, stamp):
    """Put `folder`'s times back as `stamp` had them: a NAS or FAT share whose folder time doesn't move on a new file."""
    os.utime(folder, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert os.stat(folder).st_mtime_ns == stamp.st_mtime_ns


def test_a_video_moved_into_a_folder_whose_time_did_not_move_is_found_by_the_relist(tmp_path):
    """The index skips a folder whose time hasn't moved (one stat); on such a share a moved video would be *No video*
    for ever. The first miss of the run lists the folders again, and the moved video is found."""
    added = str(tmp_path / "NAS" / "ぼっち・ざ・ろっく")
    _video(os.path.join(added, "Bocchi - 01.mkv"))
    index = _index(tmp_path, shallow=[], deep=[added])
    held = os.stat(added)
    moved = _video(os.path.join(added, "Bocchi - 04.mkv"))
    _hold(added, held)

    assert _same(index.find(["Bocchi - 04.mkv"]), moved)
    assert index.relisted


def test_the_relist_reads_at_most_its_cap_and_a_folder_past_it_keeps_what_it_had(tmp_path, monkeypatch):
    """Two folders of three entries each (two old, one moved in, times held) and a cap of four entries: one folder is
    listed again, the other keeps what it had — so exactly one moved video is found, and the old ones still are."""
    monkeypatch.setattr(videos, "RELIST_MAX", 4)
    first, second = str(tmp_path / "NAS" / "一期"), str(tmp_path / "NAS" / "二期")
    for folder, n in ((first, 1), (second, 13)):
        _video(os.path.join(folder, f"Bocchi - {n:02d}.mkv"))
        _video(os.path.join(folder, f"Bocchi - {n + 1:02d}.mkv"))
    index = _index(tmp_path, shallow=[first, second], deep=[])
    held = {f: os.stat(f) for f in (first, second)}
    _video(os.path.join(first, "Bocchi - 03.mkv"))
    _video(os.path.join(second, "Bocchi - 15.mkv"))
    for folder, stamp in held.items():
        _hold(folder, stamp)
    read = []
    real_list = videos._list

    def counted(folder, limit=None):
        got = real_list(folder, limit)
        read.append(got[2] if got else 0)
        return got
    monkeypatch.setattr(videos, "_list", counted)

    found = [index.find(["Bocchi - 03.mkv"]), index.find(["Bocchi - 15.mkv"])]
    assert len([f for f in found if f]) == 1, "the cap let only one folder be listed again"
    assert sum(read) <= videos.RELIST_MAX
    assert index.find(["Bocchi - 01.mkv"]) and index.find(["Bocchi - 13.mkv"]), "a folder past the cap kept its videos"


def test_a_second_miss_in_the_same_run_lists_nothing_again(tmp_path, monkeypatch):
    """The re-list is once a run: a second missing video in the run is a stat-free lookup, never another listing."""
    added = str(tmp_path / "NAS" / "結束バンド")
    _video(os.path.join(added, "Bocchi - 01.mkv"))
    index = _index(tmp_path, shallow=[], deep=[added])
    assert index.find(["Bocchi - 99.mkv"]) is None             # the first miss: listed again, still not there
    held = os.stat(added)
    _video(os.path.join(added, "Bocchi - 06.mkv"))
    _hold(added, held)
    listed = []
    monkeypatch.setattr(videos, "_list", lambda *a, **k: listed.append(a) or None)

    assert index.find(["Bocchi - 06.mkv"]) is None
    assert listed == [], "nothing is listed again in the same run"


def test_a_folder_over_the_cap_keeps_what_it_had_and_the_rest_goes_on_to_later_folders(tmp_path, monkeypatch):
    """Adversary #9: one huge folder on the share (more entries than the whole re-list may read) must not use the re-list
    up: it keeps its old listing, and the allowance goes on to the folders after it — the moved video is found."""
    monkeypatch.setattr(videos, "RELIST_MAX", 4)
    big, small = str(tmp_path / "NAS" / "全話"), str(tmp_path / "NAS" / "二期")
    for n in range(1, 6):
        _video(os.path.join(big, f"Bocchi - {n:02d}.mkv"))
    _video(os.path.join(small, "Bocchi - 13.mkv"))
    index = _index(tmp_path, shallow=[small, big], deep=[])       # the big folder is walked first
    held = {f: os.stat(f) for f in (big, small)}
    moved = _video(os.path.join(small, "Bocchi - 14.mkv"))
    for folder, stamp in held.items():
        _hold(folder, stamp)

    assert _same(index.find(["Bocchi - 14.mkv"]), moved), "the later folder was listed again"
    assert _same(index.find(["Bocchi - 05.mkv"]), os.path.join(big, "Bocchi - 05.mkv")), "the big one kept its videos"
