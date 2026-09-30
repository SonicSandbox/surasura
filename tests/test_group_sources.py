"""The priority list's Sources column: a word's files grouped by series — an episode or volume number and a trailing
checksum dropped, the largest group first. Each file name is worked out once per run (a common word lists the same
files as thousands of others), and the answer must not depend on it having been seen before."""

from app.analyzer import group_sources


def test_episodes_of_one_series_are_one_group_and_the_largest_group_comes_first():
    sources = {"銀河鉄道の夜 01.srt", "銀河鉄道の夜 02.srt", "銀河鉄道の夜 03 [A1B2C3D4].srt", "吾輩は猫である.txt"}
    assert group_sources(sources) == "銀河鉄道の夜 (3), 吾輩は猫である"
    assert group_sources(sources) == "銀河鉄道の夜 (3), 吾輩は猫である"       # asked again: the same


def test_a_name_that_is_only_a_number_keeps_it_and_no_sources_is_blank():
    assert group_sources({"861.txt", "861_1.txt"}) == "861 (2)"
    assert group_sources({"羅生門.txt"}) == "羅生門"
    assert group_sources(set()) == ""
