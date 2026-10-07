"""`surasura-cli list --file <subtitle> --order encounter` (P1.3 row 1.3.7; the contract's P1.3 row and P1.2's deferral):
the subtitle's list words in the order first said, each with its line's start and end, read from the file itself — so
a file is the path given, and two shows' `phrases_sample.srt` never merge.
"""
import os
import shutil

import pytest

from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OTHER_SHOW = os.path.join(PROJECT_ROOT, "samples", "ja", "HighPriority", "H_priority_sample_2.srt")


@pytest.fixture
def generated():
    folder = h.seed_library("ja")
    h.write_settings()
    code, lines = h.run_cli("generate")
    assert code == 0, lines
    return folder


def test_a_subtitles_list_words_in_the_order_said_with_their_times(generated):
    path = os.path.join(generated, "phrases_sample.srt")
    code, lines = h.run_cli("list", "--file", path, "--order", "encounter")
    result = h.answer(lines)
    assert code == 0 and result["words"], result
    starts = [w["start"] for w in result["words"]]
    assert starts == sorted(starts) and all(w["end"] > w["start"] for w in result["words"])
    assert [w["file_order"] for w in result["words"]] == list(range(1, len(starts) + 1))
    assert all(w["file_occurrences"] >= 1 for w in result["words"])
    # in the library's only subtitle, the journey meets some of its words here first
    assert any(w["new"] for w in result["words"])
    code, lines = h.run_cli("list", "--file", path, "--order", "encounter", "--limit", "2")
    assert [w["word"] for w in h.answer(lines)["words"]] == [w["word"] for w in result["words"][:2]]


def test_a_file_is_its_path_never_a_name_two_shows_share(generated, tmp_path):
    # Another show's episode with the same file name, outside the library: its own words, none "new" here
    other = tmp_path / "別の番組" / "phrases_sample.srt"
    other.parent.mkdir()
    shutil.copy2(OTHER_SHOW, other)
    mine = h.answer(h.run_cli("list", "--file", os.path.join(generated, "phrases_sample.srt"),
                              "--order", "encounter")[1])
    theirs = h.answer(h.run_cli("list", "--file", str(other), "--order", "encounter")[1])
    assert theirs["file"] == str(other) and theirs["words"] != mine["words"]
    assert all(w["new"] is None for w in theirs["words"])      # not the library's file of that name: can't tell
    assert not any(w["new"] for w in theirs["words"] if (w["word"], w["reading"]) not in
                   {(m["word"], m["reading"]) for m in mine["words"]})


def test_a_text_file_keeps_the_journeys_rows(generated):
    # .txt: no lines to time; --file still means P1.2's rows for that file name
    code, lines = h.run_cli("list", "--file", "context_test.txt", "--order", "encounter")
    result = h.answer(lines)
    assert code == 0 and result["file"] == "context_test.txt" and "start" not in (result["words"] or [{}])[0]


def test_a_missing_subtitle_is_bad_data(generated, tmp_path):
    code, lines = h.run_cli("list", "--file", str(tmp_path / "ない.srt"), "--order", "encounter")
    assert code == 1 and h.answer(lines)["code"] == "bad-data"
