"""The readers that list the tier folders know the content folder too (3.0 Sources, K2).

Every new copy Surasura makes goes into one content folder, `data/<lang>/Library/<show>/…`, whatever its place. A
reader that lists the tier folders by name must read a `Library/<show>/file` as it reads its tier-folder twin
(`HighPriority/<show>/file`), and a library with no `Library` folder must come out exactly as before.
"""
import os

import pytest

from app import extract, static_html_generator as shg
from tests.test_extract import _store_library

# The buckets as they were before the content folder: the "before" every unchanged answer is held to.
_OLD_BUCKETS = ("HighPriority", "LowPriority", "GoalContent", "Graduated", "Processed")

_TIER_PATHS = [
    "HighPriority/星の旅人/第01話.srt",
    "HighPriority/第01話.srt",                              # a loose file in a tier
    "LowPriority/深夜特急/巻1/ch01.txt",                     # a show's sub-folder kept
    "GoalContent/三体/chapter_1.txt",
    "Graduated/旅/ep01.ass",
    "Processed/旅/part_001.txt",
    "HighPriority/Library/ep01.srt",                       # a show named Library under a tier: only the tier goes
    "stray.txt",                                           # an unbucketed path is left alone
    "HighPriority\\星の旅人\\第02話.srt",            # Windows separators
]


# --- the report: a file's group label ----------------------------------------------------------------------------- #
@pytest.mark.parametrize("rel", _TIER_PATHS)
def test_the_report_labels_every_tier_path_as_it_did_before_the_content_folder(rel, monkeypatch):
    """No `Library` in the path: the label is the one the old bucket list gave, character for character."""
    now = shg._group_label(rel)
    monkeypatch.setattr(shg, "_TIER_BUCKETS", _OLD_BUCKETS)
    assert now == shg._group_label(rel)


@pytest.mark.parametrize("tier", ["HighPriority", "LowPriority", "GoalContent", "Graduated"])
@pytest.mark.parametrize("rel", ["星の旅人/第01話.srt", "深夜特急/巻1/ch01.txt", "三体/chapter_1.txt"])
def test_a_library_copy_is_labelled_by_its_show_as_its_tier_twin_is(tier, rel):
    """The content folder is plumbing like a tier folder: the learner sees the show and the file."""
    assert shg._group_label(f"Library/{rel}") == shg._group_label(f"{tier}/{rel}") == rel
    assert shg._group_label(f"Library\\{rel}".replace("/", "\\")) == rel


def test_a_loose_file_in_the_content_folder_is_just_itself():
    assert shg._group_label("Library/第01話.srt") == "第01話.srt"


# --- Extract: the names already taken ----------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_name_used_in_the_content_folder_is_taken_as_one_in_a_section_is(tmp_path, language):
    """A show the library keeps as `Library/旅`: a split named 旅 would merge into it, so the next free name is offered."""
    data_dir, _uf = _store_library(language)
    os.makedirs(os.path.join(data_dir, "Library", "旅"))
    assert extract.check_name("旅", language) == extract.Name("旅", True, "旅 2")
    os.makedirs(os.path.join(data_dir, "HighPriority", "旅 2"))     # its tier twin is taken the same way
    assert extract.check_name("旅", language) == extract.Name("旅", True, "旅 3")


def test_a_file_of_that_name_in_the_content_folder_is_taken_too(tmp_path):
    data_dir, _uf = _store_library("ja")
    os.makedirs(os.path.join(data_dir, "Library"))
    open(os.path.join(data_dir, "Library", "第01話.srt"), "w", encoding="utf-8").close()
    assert extract.check_name("第01話.srt", "ja").taken


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_with_no_content_folder_the_names_taken_are_unchanged(tmp_path, language):
    """A 2.x-shaped library (no `Library` folder): a free name is free, a taken one proposes what it did."""
    data_dir, _uf = _store_library(language)
    assert not os.path.exists(os.path.join(data_dir, "Library"))
    assert extract.check_name("新しい本", language) == extract.Name("新しい本", False, None)
    os.makedirs(os.path.join(data_dir, "Processed", "旅"))
    assert extract.check_name("旅", language) == extract.Name("旅", True, "旅 2")


def test_the_content_folder_is_one_of_the_folders_a_name_is_checked_in_once(tmp_path):
    _store_library("ja")
    _data_dir, folders = extract._folders("ja")
    assert folders.count("Library") == 1 and folders[0] == "Processed"
