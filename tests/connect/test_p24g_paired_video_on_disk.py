"""A video that hato's pairing names counts only when it is really on disk (P2.4 gap E09, mutant P2.4-E09).

Rule: a paired video that is missing from the disk is no video. Connect must not hand back the missing path (the
job would then try to mine a file that is not there); it falls through to the video index, which may find the same
episode under another folder, and returns None when it can't. Once the file is written, the paired path comes back.

What a wrong answer would cost: a job fails half way through an episode whose video was moved or never downloaded,
or Connect is told a video exists when it does not.
"""
import os

from app.connect import runner
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _steps():
    return runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT})


class _NoVideoIndex:
    """A video index that finds nothing, so only the paired path itself could make `video` return a path."""

    def __init__(self):
        self.calls = []

    def find(self, names, size=None):
        self.calls.append((list(names), size))
        return None


def test_a_paired_video_missing_from_disk_is_no_video_and_its_path_is_never_handed_back(tmp_path):
    s = _steps()
    missing = str(tmp_path / "Example Show - 05.mkv")
    s.pairing = lambda lang, job: {"video_path": missing}
    index = _NoVideoIndex()
    s._videos = lambda lang: index          # the fallback is looked at, and finds nothing
    assert s.video("ja", {"id": 1, "item_id": 5}) is None, "a missing paired file is not a video"
    assert index.calls, "the index is asked for the same episode before giving up"


def test_a_paired_video_on_disk_is_the_video_once_the_file_is_written(tmp_path):
    s = _steps()
    path = tmp_path / "Example Show - 05.mkv"
    s.pairing = lambda lang, job: {"video_path": str(path)}
    s._videos = lambda lang: _NoVideoIndex()
    path.write_bytes(b"\x1aE\xdf\xa3")      # an EBML header: a real Matroska file's first bytes
    assert s.video("ja", {"id": 1, "item_id": 5}) == str(path)


def test_a_paired_cloud_placeholder_is_no_video_and_the_index_is_asked(tmp_path, monkeypatch):
    # A cloud placeholder is a file the disk lists but holds no bytes for: opening it would download the episode
    # mid-job, so the paired path must not come back even though the file is there.
    path = tmp_path / "Example Show - 05.mkv"
    path.write_bytes(b"\x1aE\xdf\xa3")
    real_stat = os.stat

    class Placeholder:
        def __init__(self, st):
            self.st = st
            self.st_file_attributes = 0x400000           # RECALL_ON_DATA_ACCESS: reading it would download it

        def __getattr__(self, name):
            return getattr(self.st, name)
    monkeypatch.setattr(runner.os, "stat", lambda p, *a, **k: Placeholder(real_stat(p, *a, **k)))
    s = _steps()
    s.pairing = lambda lang, job: {"video_path": str(path)}
    index = _NoVideoIndex()
    s._videos = lambda lang: index
    assert s.video("ja", {"id": 1, "item_id": 5}) is None, "a cloud placeholder is not a video"
    assert index.calls, "the index is asked for the same episode before giving up"


# --------------------------------------------------------------------------- #
# P3.2 row 3.2.3: a paired video found away from its named path is the paired one only when its bytes say so
# --------------------------------------------------------------------------- #
EPISODE = b"\x1aE\xdf\xa3" + bytes(i % 251 for i in range(200_000))     # a Matroska header, then 200 KB


def _key(data):
    """hato's `video_hash`, written out here so the test doesn't check the code with itself (09-hato-layer v2 §1.1)."""
    import hashlib
    import struct
    body = data if len(data) <= 131072 else data[:65536] + data[-65536:]
    return "v1-" + hashlib.sha256(struct.pack("<Q", len(data)) + body).hexdigest()


def _moved(tmp_path, data):
    """The paired episode gone from where hato saw it, and a file of its name and size in an indexed folder holding
    `data` -> (the steps, the moved file's path)."""
    from app.connect import videos
    named = str(tmp_path / "Downloads" / "Bocchi - 05.mkv")              # where hato paired it: gone now
    moved = tmp_path / "Anime" / "Bocchi the Rock" / "Bocchi - 05.mkv"
    moved.parent.mkdir(parents=True)
    moved.write_bytes(data)
    index = videos.Index("ja", path=str(tmp_path / "videos-ja.json"))
    index.refresh(shallow=[], deep=[str(tmp_path / "Anime")])
    s = _steps()
    s.pairing = lambda lang, job: {"video_path": named, "video_size": len(EPISODE), "content_key": _key(EPISODE)}
    s._videos = lambda lang: index
    return s, str(moved)


def test_a_moved_video_of_the_same_name_and_size_but_other_bytes_is_not_the_paired_one(tmp_path):
    # why: another episode (or a re-encode) under the same file name and size would be mined as this one — its lines'
    # audio cut from the wrong video. Only the tail differs: the key reads the last 64 KiB too.
    other = EPISODE[:-1] + bytes([(EPISODE[-1] + 1) % 256])
    s, _moved_path = _moved(tmp_path, other)
    assert s.video("ja", {"id": 1, "item_id": 5}) is None, "same name and size, other content: not found"


def test_a_moved_video_whose_bytes_hash_to_the_pairings_key_is_used(tmp_path, monkeypatch):
    # why: a video the learner moved to another folder is still the paired episode: its key matches, so it is mined
    from app.connect import videos
    read = []
    real = videos.content_key
    monkeypatch.setattr(videos, "content_key", lambda path: read.append(path) or real(path))
    s, moved = _moved(tmp_path, EPISODE)
    assert os.path.normcase(s.video("ja", {"id": 1, "item_id": 5})) == os.path.normcase(moved)
    assert len(read) == 1, "the found file's key read once"


def test_the_named_video_on_disk_is_trusted_without_reading_its_key(tmp_path, monkeypatch):
    # why: the named path is hato's own word (a stat only); reading 128 KiB of every episode at every look would cost
    # the disk (or a cloud folder's download) for nothing
    from app.connect import videos
    read = []
    monkeypatch.setattr(videos, "content_key", lambda path: read.append(path) or "v1-" + "0" * 64)
    path = tmp_path / "Bocchi - 05.mkv"
    path.write_bytes(EPISODE)
    s = _steps()
    s.pairing = lambda lang, job: {"video_path": str(path), "video_size": len(EPISODE), "content_key": _key(b"x")}
    s._videos = lambda lang: _NoVideoIndex()
    assert s.video("ja", {"id": 1, "item_id": 5}) == str(path)
    assert read == [], "no key computed for the named path"
