# SPDX-License-Identifier: GPL-3.0-or-later
"""The answers store — `User Files/<lang>/junban_pairs.json` (Junban_Backlog_Spec §16.3).

What the user ticked in "Same word as one on your list?" is their own work, kept under `User Files/`:
it must survive a restart, stay per language, never be overwritten when it cannot be read, and never
be half-written. The words are the real backlog's (§12).
"""

import json
import os

from modules.junban import pairs


def test_answers_survive_a_restart_and_a_later_answer_replaces_an_earlier_one():
    pairs.record("ja", [("見とれる", "見惚れる", True, "L6"), ("過熱する", "過熱", False, "L7")])
    loaded = pairs.load("ja")
    assert loaded["見とれる"]["target"] == "見惚れる" and loaded["見とれる"]["answer"] == "yes"
    assert loaded["過熱する"]["answer"] == "no"
    # Changed their mind about one word: that one changes, the other is kept.
    pairs.record("ja", [("過熱する", "過熱", True, "L7")])
    loaded = pairs.load("ja")
    assert loaded["過熱する"]["answer"] == "yes" and loaded["見とれる"]["answer"] == "yes"


def test_no_file_is_no_answers_and_each_language_keeps_its_own():
    assert pairs.load("ja") == {}
    pairs.record("zh", [("學習", "学习", True, "L6")])
    assert pairs.load("ja") == {}
    assert pairs.load("zh")["學習"]["target"] == "学习"


def test_a_file_that_cannot_be_read_is_moved_aside_never_overwritten():
    """The user's answers may still be recoverable by hand; replacing the file would lose them."""
    path = pairs.pairs_path("ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"pairs": {"見とれる": ')
    assert pairs.load("ja") == {}
    folder = os.path.dirname(path)
    kept = [name for name in os.listdir(folder) if name.startswith(pairs.FILENAME + ".corrupt-")]
    assert len(kept) == 1
    with open(os.path.join(folder, kept[0]), encoding="utf-8") as handle:
        assert handle.read() == '{"pairs": {"見とれる": '


def test_an_entry_this_code_cannot_use_is_skipped_not_trusted():
    path = pairs.pairs_path("ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "pairs": {"見とれる": {"target": "見惚れる", "answer": "yes"},
                                           "きゅっと": {"target": "きゅっ", "answer": "maybe"},
                                           "同行する": {"answer": "yes"}}}, handle, ensure_ascii=False)
    assert list(pairs.load("ja")) == ["見とれる"]


def test_the_write_is_atomic_and_leaves_no_temporary_file():
    path = pairs.record("ja", [("なり代わる", "成り代わる", True, "L6")])
    assert os.path.isfile(path) and not os.path.exists(path + ".tmp")
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle)["version"] == pairs.VERSION
