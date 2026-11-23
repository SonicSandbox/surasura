"""The sentence table (the sentence choice): Generate keeps every candidate sentence of every list word as numbers.

What these prove, so far — the switch, `plan_rules.SENTENCE_TABLE`, before anything reads it:
  - it is 0 in the tree, and a level is only ever one of 0, 1, 2;
  - a child process (a Generate is one) takes its level from SURASURA_SENTENCE_TABLE, read once at import; any other
    value is the tree's;
  - off is today: a Generate with the switch at 0 writes every file in results/ the same bytes as one with no switch
    set at all, and no table.

What a wrong answer would cost a learner: a build half switched on in a release that was meant to change nothing —
sentences on their cards or their list moving before the release that says so.
"""
import ast
import hashlib
import os
import subprocess
import sys

import pytest

from app import plan_rules

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _child_level(env_value):
    """The switch as a fresh interpreter sees it, with SURASURA_SENTENCE_TABLE `env_value` (None: not set)."""
    env = dict(os.environ)
    env.pop("SURASURA_SENTENCE_TABLE", None)
    if env_value is not None:
        env["SURASURA_SENTENCE_TABLE"] = env_value
    p = subprocess.run([sys.executable, "-c", "from app import plan_rules; print(plan_rules.SENTENCE_TABLE)"],
                       cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return int(p.stdout.strip())


# --------------------------------------------------------------------------- #
# 1. The switch
# --------------------------------------------------------------------------- #
def test_the_switch_is_off_in_the_tree():
    # why: every lane of the build lands inert; a flip is its own commit (with ENGINE_REVISION), never a side effect
    with open(os.path.join(REPO, "app", "plan_rules.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    literals = [node.value.value for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(isinstance(t, ast.Name) and t.id == "SENTENCE_TABLE" for t in node.targets)]
    assert literals == [0]
    assert plan_rules.SENTENCE_TABLE_LEVELS == (0, 1, 2)


@pytest.mark.parametrize("env_value, level", [(None, 0), ("0", 0), ("1", 1), ("2", 2)])
def test_a_child_process_takes_its_level_from_the_environment(env_value, level):
    # why: a Generate is a subprocess; the harness runs a level by its environment, read once at import
    assert _child_level(env_value) == level


@pytest.mark.parametrize("raw", ["", " ", "3", "-1", "1.0", "on", "true", "２", "0x1"])
def test_anything_but_a_level_reads_as_the_trees_value(raw):
    # why: a typo or a stray value must never switch a release on (the full-width ２ included: int() would take it)
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": raw}) == plan_rules.SENTENCE_TABLE_LEVELS[0]
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": raw}, default=2) == 2


def test_a_level_with_spaces_around_it_is_that_level():
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": " 2\r\n"}) == 2
    assert plan_rules.sentence_table_level({}) == plan_rules.SENTENCE_TABLE


# --------------------------------------------------------------------------- #
# 2. Off is today
# --------------------------------------------------------------------------- #
def _outputs():
    from tests import services_helpers as h
    folder = os.path.join(h.root(), "results")
    return {name: hashlib.sha256(open(os.path.join(folder, name), "rb").read()).hexdigest()
            for name in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, name))}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_generate_with_the_switch_off_writes_what_one_without_it_writes(language, monkeypatch):
    # why: at 0 every file in results/ is byte for byte the code before (the build's inert rule); a reader of the
    # switch that leaks into a run at 0 shows up here as a changed file or a table
    from tests import services_helpers as h
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    from tests.test_services_progress import _analyzer
    h.seed_library(language)
    h.write_settings({"target_language": language, "anki_connect_url": "http://127.0.0.1:9"})
    # one hash seed for both runs: word_stats.json and file_words.json list a word's files from a set, so their bytes
    # follow the seed (as test_services_progress.py's flag test fixes it) — the switch is what this compares
    found = []
    for env in ({}, {"SURASURA_SENTENCE_TABLE": "0"}):
        proc = _analyzer(language, env=dict(env, SURASURA_FORCE_RUN="1", PYTHONHASHSEED="0"))
        assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-2000:]
        found.append(_outputs())
    assert found[0] == found[1]
    assert "plan.json.gz" in found[0] and "sentences.bin" not in found[0]
