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


# The rename that gives a backup its dated name: on Windows one that refuses a name already taken
_RENAME = os.rename if os.name == "nt" else os.replace


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
    order, flushed = [], []
    real_fsync, real_rename = os.fsync, _RENAME
    monkeypatch.setattr(os, "fsync", lambda fd: order.append("fsync") or flushed.append(os.fstat(fd).st_ino)
                        or real_fsync(fd))
    monkeypatch.setattr(os, _RENAME.__name__,
                        lambda a, b: order.append(("rename", os.path.basename(b))) or real_rename(a, b))
    dst = path_utils.backup_to_trash(path)
    assert os.listdir(trash) == [os.path.basename(dst)] == _dated(trash)
    assert open(dst, "rb").read() == open(path, "rb").read()
    assert order == ["fsync", ("rename", os.path.basename(dst))], order
    # The file flushed is the copy (the rename keeps its file id), never the original
    assert flushed == [os.stat(dst).st_ino] and flushed != [os.stat(path).st_ino]


def test_two_writers_at_once_never_share_one_temporary_copy(tmp_path, monkeypatch):
    """Two threads backing up one file in the same second each write a `.part` of their own: shared, one could rename
    the copy the other is still writing into its dated name, and a kill then would leave that name short."""
    import threading
    path = _known_words(tmp_path, "ja")
    real_copy = shutil.copyfile
    both_copying = threading.Barrier(2, timeout=10)
    parts = []

    def copy(src, dst):
        parts.append(dst)
        both_copying.wait()                          # both writers are mid-copy at the same instant
        return real_copy(src, dst)
    monkeypatch.setattr(shutil, "copyfile", copy)
    done = []
    writers = [threading.Thread(target=lambda: done.append(path_utils.backup_to_trash(path))) for _ in range(2)]
    for w in writers:
        w.start()
    for w in writers:
        w.join(15)
    assert len(set(parts)) == 2, parts
    assert len(done) == 2 and all(open(d, "rb").read() == open(path, "rb").read() for d in done)
    if os.name == "nt":                              # Windows' rename refuses a taken name: both backups kept
        assert len(set(done)) == 2 and sorted(_dated(os.path.dirname(done[0]))) == sorted(map(os.path.basename, done))


def test_a_rename_held_by_a_scanner_is_waited_out(tmp_path, monkeypatch):
    """Antivirus or a cloud folder's client holds a just-written file for a moment: the rename to the dated name is
    tried again, and the backup is made."""
    path = _known_words(tmp_path, "zh")
    real_rename, calls = _RENAME, []

    def held_twice(a, b):
        calls.append(b)
        if len(calls) <= 2:
            raise PermissionError("held by a scanner")
        return real_rename(a, b)
    monkeypatch.setattr(os, _RENAME.__name__, held_twice)
    monkeypatch.setattr(path_utils.time, "sleep", lambda _s: None)
    dst = path_utils.backup_to_trash(path)
    assert len(calls) == 3 and open(dst, "rb").read() == open(path, "rb").read()
    assert os.listdir(os.path.dirname(dst)) == [os.path.basename(dst)]


def test_a_rename_that_stays_held_fails_and_leaves_nothing(tmp_path, monkeypatch):
    """A rename refused every time: OSError, so the caller leaves the original alone, and no `.part` and no dated
    name in `.trash`."""
    path = _known_words(tmp_path, "ja")
    before = open(path, "rb").read()

    def held(a, b):
        raise PermissionError("held by a scanner")
    monkeypatch.setattr(os, _RENAME.__name__, held)
    monkeypatch.setattr(path_utils.time, "sleep", lambda _s: None)
    with pytest.raises(OSError):
        path_utils.backup_to_trash(path)
    assert os.listdir(os.path.join(os.path.dirname(path), ".trash")) == []
    assert open(path, "rb").read() == before


def test_a_temporary_copy_is_short_named_so_a_deep_folder_still_backs_up(tmp_path, monkeypatch):
    """The `.part` name is no longer than the dated one, so a file whose backup fits a deep folder (a cloud-synced
    User Files) still gets one."""
    path = _known_words(tmp_path, "ja")
    parts = []
    real_copy = shutil.copyfile
    monkeypatch.setattr(shutil, "copyfile", lambda a, b: parts.append(b) or real_copy(a, b))
    dst = path_utils.backup_to_trash(path)
    assert parts and len(os.path.basename(parts[0])) <= len(os.path.basename(dst))


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


@pytest.mark.skipif(os.name != "nt", reason="only Windows' rename refuses a taken name")
def test_a_name_taken_between_the_look_and_the_rename_steps_to_the_next(tmp_path, monkeypatch):
    """Another writer takes the dated name after this one looked (exists() said free): Windows' rename refuses it, and
    the backup steps to `-1` instead of failing or overwriting the other backup."""
    path = _known_words(tmp_path, "ja")
    first = path_utils.backup_to_trash(path)
    real_exists = os.path.exists
    monkeypatch.setattr(path_utils.os.path, "exists", lambda p: False if p.endswith(".json") and ".trash" in p
                        else real_exists(p))
    monkeypatch.setattr(path_utils.time, "strftime", lambda _f: os.path.basename(first).split(".")[1])
    second = path_utils.backup_to_trash(path)
    assert second == first[:-len(".json")] + "-1.json"
    assert open(first, "rb").read() == open(second, "rb").read() == open(path, "rb").read()
