"""The full library frequency map (`results/library_frequency.json`) — every word, the sub-threshold
ones included.

Since ENGINE_REVISION 11 every run writes it (it used to wait for the YouTube preview toggle), and
each entry carries what Junban needs to place a mined word below the list's cut-off exactly where the
journey would meet it (Junban_Backlog_Spec §11.1): the word's first file in study order, its score,
and the spelling the content uses. The map has to agree with the journey itself, so the listed
word is checked against the progressive list's own `Sequence` and `Score`.
"""

import csv
import json
from unittest.mock import patch

import pytest

from app import analyzer

NOW_1 = "明日から冒険に出かけよう。彼は足を引きずって歩いていた。"
NOW_2 = "冒険は続く。猫が窓の外を見ている。"
SOON_3 = "非常に有名な冒険の話を聞いた。"


@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    now = tmp_path / "data" / "ja" / "HighPriority"
    now.mkdir(parents=True)
    (now / "第01話.txt").write_text(NOW_1, encoding="utf-8")
    (now / "第02話.txt").write_text(NOW_2, encoding="utf-8")
    soon = tmp_path / "data" / "ja" / "LowPriority"
    soon.mkdir(parents=True)
    (soon / "第03話.txt").write_text(SOON_3, encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    return {"root": tmp_path, "results": results}


def _run(env):
    """One analyzer run, as tests/test_results_stamp.py runs it. `--min-freq 2`: a word met once is
    below the list's cut-off — the case the map exists for."""
    root, results = env["root"], env["results"]
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda lang=None: str(root / "data" / lang) if lang else str(root / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda lang=None: str(root / "User Files" / lang) if lang else str(root / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "2"]):
        analyzer.main()


def _entries(env, lemma):
    with open(env["results"] / "library_frequency.json", encoding="utf-8") as f:
        words = json.load(f)["words"]
    return [value for key, value in words.items() if key.split("|")[0] == lemma]


def test_every_run_writes_the_map_with_first_file_score_and_spelling(env):
    """No preview toggle anywhere in the sandbox's settings: the map is written all the same. 冒険 is
    on the list (met three times) and the map agrees with the journey's own numbers for it."""
    _run(env)

    [adventure] = _entries(env, "冒険")
    total, high, low, goal, first_file, score, spelling = adventure
    assert (total, high, low, goal) == (3, 2, 1, 0)
    assert (first_file, score, spelling) == (1, 2 * 10 + 5, "冒険")

    with open(env["results"] / "progressive_learning_list.csv", encoding="utf-8-sig", newline="") as f:
        [row] = [r for r in csv.DictReader(f) if r["Word"] == "冒険"]
    assert (int(row["Sequence"]), int(row["Score"])) == (first_file, score)


def test_a_word_below_the_cut_off_is_in_the_map_with_its_spelling_and_first_file(env):
    """引きずって is met once, in the first file: never on the list, and exactly the kind of word a
    learner mines. anki_miner writes 引きずる — the content's spelling — not the lemma 引き摺る, so
    the map carries it; 非常 is only in the Soon file, so it starts there and scores 5."""
    _run(env)

    [drag] = _entries(env, "引き摺る")
    assert drag[4:] == [1, 10, "引きずる"]
    [very] = _entries(env, "非常")
    assert very[4:] == [3, 5, "非常"]

    with open(env["results"] / "priority_learning_list.csv", encoding="utf-8-sig", newline="") as f:
        listed = {r["Word"] for r in csv.DictReader(f)}
    assert "引き摺る" not in listed and "非常" not in listed
