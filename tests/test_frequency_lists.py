"""The frequency lists' rules (W3.4 row 1; `app/frequency_lists.py`, moved out of the Tk `FrequencyListGUI`).

What a wrong answer would cost (inv-importers §5.9): a removed list gone for good (the Tk window's `os.remove`); a list
silently overwritten by one of the same name, with no copy; another language's lists shown as this one's (and removable
from it); a list named so the analyzer never reads it; a list "added" over itself, losing it.
"""
import os
import shutil

import pytest

from app import analyzer, frequency_lists, path_utils


def _user_files(language):
    return path_utils.get_user_files_path(language)


def _trash(language):
    folder = os.path.join(_user_files(language), ".trash")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


@pytest.fixture
def ja_list(ja_resources_dir):
    return os.path.join(ja_resources_dir, "frequency_list_novels.csv")


@pytest.fixture
def zh_list(zh_resources_dir):
    return os.path.join(zh_resources_dir, "frequency_list_subtitles.csv")


# --- names ------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("base, language, name", [
    ("Novels.csv", "ja", "frequency_list_ja_Novels.csv"),                   # no prefix: the language's added
    ("frequency_list_Novels.csv", "ja", "frequency_list_ja_Novels.csv"),    # a bare prefix made the language's
    ("frequency_list_ja_Novels.csv", "ja", "frequency_list_ja_Novels.csv"),  # a right one kept
    ("frequency_list_ja_夜市.csv", "zh", "frequency_list_zh_ja_夜市.csv"),     # the Tk rule: another language's kept inside
    ("字幕 频率.csv", "zh", "frequency_list_zh_字幕 频率.csv"),
])
def test_a_list_takes_the_name_the_analyzer_reads(base, language, name):
    assert frequency_lists.dest_name(base, language) == name


def test_an_added_list_is_one_the_analyzer_finds_and_reads(ja_list):
    name, kept = frequency_lists.add(ja_list, "ja")
    assert name == "frequency_list_ja_novels.csv"          # its bare prefix made the language's
    assert kept is None
    assert os.listdir(_user_files("ja")) == [name]          # moved in whole: no temporary copy left beside it
    found = analyzer.discover_yomitan_frequency_lists(_user_files("ja"), "ja")
    assert found == {"novels": os.path.join(_user_files("ja"), name)}
    ranks = analyzer.load_yomitan_frequency_list(found["novels"], language="ja")
    assert ranks["冒険"] == 1500 and ranks["宿屋"] == 8800


# --- listing: this language's only --------------------------------------------------------------------------------- #
def test_the_list_shows_this_languages_lists_only(ja_list, zh_list):
    frequency_lists.add(ja_list, "ja")
    frequency_lists.add(zh_list, "zh")
    # a stray file of another language's name in the ja folder (the Tk glob showed it): the analyzer ignores it
    shutil.copyfile(zh_list, os.path.join(_user_files("ja"), "frequency_list_zh_subtitles.csv"))
    open(os.path.join(_user_files("ja"), "frequency_list_ja_notes.txt"), "w", encoding="utf-8").close()
    os.makedirs(os.path.join(_user_files("ja"), "frequency_list_ja_folder.csv"))
    assert frequency_lists.listed("ja") == ["frequency_list_ja_novels.csv"]
    assert frequency_lists.listed("zh") == ["frequency_list_zh_subtitles.csv"]


def test_no_folder_yet_lists_nothing_and_writes_nothing():
    assert frequency_lists.listed("zh") == []
    assert not os.path.exists(_user_files("zh"))


# --- adding -------------------------------------------------------------------------------------------------------- #
def test_a_list_added_over_a_same_named_one_keeps_the_old_one_in_the_trash(ja_list, tmp_path):
    frequency_lists.add(ja_list, "ja")
    newer = tmp_path / "novels.csv"
    newer.write_text("Word,Rank\n冒険,1499\n", encoding="utf-8")
    name, kept = frequency_lists.add(str(newer), "ja")
    assert name == "frequency_list_ja_novels.csv"
    dest = os.path.join(_user_files("ja"), name)
    assert open(dest, encoding="utf-8").read() == "Word,Rank\n冒険,1499\n"
    assert kept is not None and os.path.dirname(kept) == os.path.join(_user_files("ja"), ".trash")
    with open(kept, "rb") as a, open(ja_list, "rb") as b:
        assert a.read() == b.read()                     # the old list, whole
    assert frequency_lists.listed("ja") == [name]       # the copy in the trash is never listed or read
    assert set(analyzer.discover_yomitan_frequency_lists(_user_files("ja"), "ja")) == {"novels"}


def test_adding_a_list_that_is_that_list_already_changes_nothing(ja_list):
    name, _ = frequency_lists.add(ja_list, "ja")
    dest = os.path.join(_user_files("ja"), name)
    before = open(dest, "rb").read()
    with pytest.raises(shutil.SameFileError):
        frequency_lists.add(dest, "ja")
    assert open(dest, "rb").read() == before            # still there, unchanged
    assert _trash("ja") == []                           # never moved aside


def test_a_list_whose_old_copy_cant_be_made_is_not_added_and_the_old_one_stays(ja_list, tmp_path, monkeypatch):
    frequency_lists.add(ja_list, "ja")
    dest = os.path.join(_user_files("ja"), "frequency_list_ja_novels.csv")
    before = open(dest, "rb").read()
    newer = tmp_path / "novels.csv"
    newer.write_text("Word,Rank\n冒険,1\n", encoding="utf-8")

    def refuse(path, move=False):
        raise OSError("the trash folder is read-only")
    monkeypatch.setattr(path_utils, "backup_to_trash", refuse)
    with pytest.raises(OSError):
        frequency_lists.add(str(newer), "ja")
    assert open(dest, "rb").read() == before
    assert sorted(os.listdir(_user_files("ja"))) == ["frequency_list_ja_novels.csv"]   # no half-copy left behind


def test_a_source_that_cant_be_read_adds_nothing(tmp_path):
    with pytest.raises(OSError):
        frequency_lists.add(str(tmp_path / "gone.csv"), "ja")
    assert frequency_lists.listed("ja") == []
    assert [n for n in os.listdir(_user_files("ja")) if n.endswith(".adding")] == []


def test_a_copy_that_fails_part_way_leaves_the_old_list_and_no_temporary(ja_list, tmp_path, monkeypatch):
    frequency_lists.add(ja_list, "ja")
    dest = os.path.join(_user_files("ja"), "frequency_list_ja_novels.csv")
    before = open(dest, "rb").read()
    newer = tmp_path / "novels.csv"
    newer.write_text("Word,Rank\n冒険,1\n", encoding="utf-8")
    real = shutil.copyfile

    def half(src, dst, *a, **k):
        with open(dst, "w", encoding="utf-8") as f:
            f.write("Word,Ra")
        raise OSError("the disk is full")
    monkeypatch.setattr(shutil, "copyfile", half)
    with pytest.raises(OSError):
        frequency_lists.add(str(newer), "ja")
    monkeypatch.setattr(shutil, "copyfile", real)
    assert open(dest, "rb").read() == before
    assert sorted(os.listdir(_user_files("ja"))) == ["frequency_list_ja_novels.csv"]
    assert _trash("ja") == []


# --- removing ------------------------------------------------------------------------------------------------------ #
def test_a_removed_list_lands_in_the_trash_never_deleted(ja_list):
    name, _ = frequency_lists.add(ja_list, "ja")
    went = frequency_lists.remove(name, "ja")
    assert frequency_lists.listed("ja") == []
    assert os.path.dirname(went) == os.path.join(_user_files("ja"), ".trash")
    with open(went, "rb") as a, open(ja_list, "rb") as b:
        assert a.read() == b.read()
    assert analyzer.discover_yomitan_frequency_lists(_user_files("ja"), "ja") == {}


def test_removing_never_touches_another_languages_lists(ja_list, zh_list):
    frequency_lists.add(ja_list, "ja")
    zh_name, _ = frequency_lists.add(zh_list, "zh")
    with pytest.raises(FileNotFoundError):
        frequency_lists.remove(zh_name, "ja")           # a zh list asked for in ja: nothing moves
    assert frequency_lists.listed("zh") == [zh_name]
    assert frequency_lists.listed("ja") == ["frequency_list_ja_novels.csv"]
    assert _trash("ja") == [] and _trash("zh") == []


@pytest.mark.parametrize("name", ["../zh/frequency_list_zh_subtitles.csv", "frequency_list_ja_missing.csv",
                                  "KnownWord.json", ""])
def test_only_a_listed_name_can_be_removed(ja_list, zh_list, name):
    frequency_lists.add(ja_list, "ja")
    frequency_lists.add(zh_list, "zh")
    known = os.path.join(_user_files("ja"), "KnownWord.json")
    open(known, "w", encoding="utf-8").write("{}")
    with pytest.raises(FileNotFoundError):
        frequency_lists.remove(name, "ja")
    assert os.path.exists(known) and len(frequency_lists.listed("zh")) == 1 and _trash("ja") == []


def test_a_list_that_cant_be_moved_stays_where_it_was(ja_list, monkeypatch):
    name, _ = frequency_lists.add(ja_list, "ja")

    def refuse(path, move=False):
        raise OSError("held open by another program")
    monkeypatch.setattr(path_utils, "backup_to_trash", refuse)
    with pytest.raises(OSError):
        frequency_lists.remove(name, "ja")
    assert frequency_lists.listed("ja") == [name]


def test_removing_two_lists_of_one_name_twice_keeps_both_copies(ja_list, tmp_path):
    # Remove, add the same name again, remove again: two dated copies, neither overwriting the other.
    name, _ = frequency_lists.add(ja_list, "ja")
    frequency_lists.remove(name, "ja")
    frequency_lists.add(ja_list, "ja")
    frequency_lists.remove(name, "ja")
    assert len(_trash("ja")) == 2
