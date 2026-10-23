"""path_utils.backup_to_trash(): a dated copy of a user-data file is either whole and verified, or absent.

Why these matter: the copy is the user's way back after a file is replaced (KnownWord.json, the word lists, the
library's manifest), and `User Files/<lang>/.trash` is never purged. Written in place, a copy cut off part way — the
store's helper ended by Stop and quit, a crash, a power cut — left a short file under the dated name, which looks
exactly like a good backup. The copy is now written under a temporary `.part` name, flushed to disk and checked, and
only then renamed to its dated name. Real Japanese and Chinese words stand in the files.
"""
import json
import os
import re
import shutil

import pytest

from app import path_utils


def _known_words(tmp_path, language):
    """A KnownWord.json of real words (CRLF line ends, as Notepad saves it), big enough to cut in half."""
    words = ["食べる", "勉強", "新幹線", "一生懸命"] if language == "ja" else ["学习", "开心", "电脑", "一路平安"]
    folder = tmp_path / "User Files" / language
    folder.mkdir(parents=True)
    path = folder / "KnownWord.json"
    body = json.dumps({w * (n + 1): "KNOWN" for n, w in enumerate(words * 50)}, ensure_ascii=False, indent=1)
    path.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
    return str(path)


def _dated(trash):
    """The names in `.trash` that look like a finished backup: `KnownWord.<YYYYmmdd-HHMMSS>[-n].json`."""
    if not os.path.isdir(trash):
        return []
    return [n for n in os.listdir(trash) if re.fullmatch(r"KnownWord\.\d{8}-\d{6}(-\d+)?\.json", n)]


def _cut_copy(seen, trash):
    """A copy that writes half the file and dies: the process stopped mid-write. Before it dies it notes the dated
    names already in `.trash` (what a kill at that instant would leave behind)."""
    def copy(src, dst):
        with open(src, "rb") as f:
            data = f.read()
        with open(dst, "wb") as f:
            f.write(data[:len(data) // 2])
        seen.extend(_dated(trash))
        raise KeyboardInterrupt("stopped mid-copy")
    return copy


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_copy_cut_off_part_way_never_sits_under_a_dated_name(tmp_path, monkeypatch, language):
    """The laptop's Stop and quit ends the helper during its copy: at that instant, and after, no dated name holds a
    short file, nothing is left in `.trash`, and the original is untouched."""
    path = _known_words(tmp_path, language)
    before = open(path, "rb").read()
    trash = os.path.join(os.path.dirname(path), ".trash")
    seen = []
    monkeypatch.setattr(shutil, "copyfile", _cut_copy(seen, trash))
    with pytest.raises(KeyboardInterrupt):
        path_utils.backup_to_trash(path)
    assert seen == [], f"a kill mid-copy would have left a dated backup: {seen}"
    assert os.listdir(trash) == [], "the cut-off copy was left in .trash"
    assert open(path, "rb").read() == before


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_copy_that_does_not_match_is_refused_and_left_nowhere(tmp_path, monkeypatch, language):
    """A copy whose bytes differ from the original (a disk error, a file changed under it) raises OSError, so the
    caller leaves the original alone, and leaves no file in `.trash`."""
    path = _known_words(tmp_path, language)
    trash = os.path.join(os.path.dirname(path), ".trash")

    def wrong_copy(src, dst):
        with open(src, "rb") as f:
            data = f.read()
        with open(dst, "wb") as f:
            f.write(data[:-10])
    monkeypatch.setattr(shutil, "copyfile", wrong_copy)
    with pytest.raises(OSError, match="did not match"):
        path_utils.backup_to_trash(path)
    assert os.listdir(trash) == []


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_backup_is_whole_under_its_dated_name_and_flushed_before_the_rename(tmp_path, monkeypatch, language):
    """The success path: the dated copy holds every byte, no `.part` is left beside it, and the copy was flushed to
    disk (fsync) before it took the dated name — a power cut after the rename can't leave it short."""
    path = _known_words(tmp_path, language)
    trash = os.path.join(os.path.dirname(path), ".trash")
    order = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: order.append("fsync") or real_fsync(fd))
    monkeypatch.setattr(os, "replace", lambda a, b: order.append(("replace", os.path.basename(b))) or real_replace(a, b))
    dst = path_utils.backup_to_trash(path)
    assert os.listdir(trash) == [os.path.basename(dst)] == _dated(trash)
    assert open(dst, "rb").read() == open(path, "rb").read()
    assert order == ["fsync", ("replace", os.path.basename(dst))], order


def test_a_part_left_by_an_earlier_kill_does_not_stop_the_next_backup(tmp_path):
    """A `.part` an earlier kill left behind is no backup and no obstacle: the next backup takes a dated name of its
    own, whole, and never reads the leftover."""
    path = _known_words(tmp_path, "ja")
    trash = os.path.join(os.path.dirname(path), ".trash")
    os.makedirs(trash)
    leftover = os.path.join(trash, "KnownWord.20261022-210000.json.4242-1.part")
    with open(leftover, "wb") as f:
        f.write(b'{"\xe9\xa3\x9f')                    # half a word: what a cut copy holds
    dst = path_utils.backup_to_trash(path)
    assert open(dst, "rb").read() == open(path, "rb").read()
    assert _dated(trash) == [os.path.basename(dst)]


def test_two_backups_in_one_second_keep_both_whole(tmp_path):
    """Two backups of one file in the same second take two dated names (`-1` for the second), both whole."""
    path = _known_words(tmp_path, "zh")
    first = path_utils.backup_to_trash(path)
    with open(path, "ab") as f:
        f.write("\r\n".encode("utf-8"))
    second = path_utils.backup_to_trash(path)
    assert first != second
    assert open(second, "rb").read() == open(path, "rb").read()
    assert open(first, "rb").read() == open(path, "rb").read()[:-2]


def test_a_missing_file_has_no_backup_and_makes_no_folder(tmp_path):
    """No file, nothing to keep: None, and no `.trash` made beside it (empty state)."""
    folder = tmp_path / "User Files" / "ja"
    folder.mkdir(parents=True)
    assert path_utils.backup_to_trash(str(folder / "KnownWord.json")) is None
    assert not (folder / ".trash").exists()


def test_move_sets_the_file_aside_whole(tmp_path):
    """`move=True` (a file set aside, not overwritten) still moves it in one rename: the original goes, the dated name
    holds every byte."""
    path = _known_words(tmp_path, "ja")
    before = open(path, "rb").read()
    dst = path_utils.backup_to_trash(path, move=True)
    assert not os.path.exists(path)
    assert open(dst, "rb").read() == before
