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
