"""E-JOURNEY (part 2): the level-2 list carries every column level 0 writes (the lead's note, 2026-11-24, before the
flip 0 → 2; SPEC § 10.3 *E-JOURNEY*).

At release 2 the list's sentences come from the one reader (`analyzer.ListSentences`) in the Generate and in the
redraw after a move, by another path than today's pick. Whatever else today's writer puts in a row or a file's
statistics — the Source File, its path from the data folder, the counts, the marks — must still be there at level 2, or
a reader of those files (the journey page, Junban, Connect, the window's word lists, an export) loses a column on the
day the switch flips. So the column lists are read from what level 0 writes, never typed here: a column a later lane
adds to level 0's writer and not to level 2's turns this red.

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py), each through a full Generate in a child
process as the dashboard runs it, then a move and the keeper's redraw (`--from-plan`), once at level 0 and once at
level 2.
"""
import csv
import json
import os
import subprocess
import sys

import pytest

from tests import plan_file_cases as cases
from tests.test_e_redraw import _MOVE

STATS = "file_statistics.json"


def _shape(results):
    """{file name: its columns} for every list results/ holds — a CSV's header in its order, file_statistics.json's
    keys of each file's entry (the set of distinct key lists: every entry is one file's) — what a reader reads by
    name."""
    out = {}
    for name in sorted(os.listdir(results)):
        path = os.path.join(results, name)
        if name.endswith(".csv"):
            with open(path, encoding="utf-8-sig", newline="") as f:
                out[name] = next(csv.reader(f), [])
        elif name == STATS:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            entries = data if isinstance(data, list) else list(data.values())
            out[name] = sorted({tuple(sorted(e)) for e in entries if isinstance(e, dict)})
    return out


def _env(root, level):
    env = cases.child_env(root)
    env["SURASURA_SENTENCE_TABLE"] = str(level)
    return env


def _child(root, level, cmd):
    p = subprocess.run(cmd, cwd=cases.REPO, env=_env(root, level), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]


def _run(root, case, level):
    """A Generate, then a show moved to the top (test_e_redraw's move) and the keeper's redraw (`--from-plan`, as the
    window starts it), at `level` -> (the Generate's shape, the redraw's shape)."""
    language = cases.ALL_CASES[case][0]
    cases.build(root, case)
    cases.generate(root, case, extra_env={"SURASURA_SENTENCE_TABLE": str(level)})
    results = os.path.join(root, "results")
    generated = _shape(results)
    _child(root, level, [sys.executable, "-c", _MOVE, language, root, "top"])
    _child(root, level, [sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), f"--language={language}",
                         "--static", "--no-open", "--from-plan"])
    return generated, _shape(results)


@pytest.fixture(scope="module", params=["ja", "zh"])
def shapes(request, tmp_path_factory):
    """RP-2's library of one language, Generated and redrawn at level 0 and at level 2 (two roots: the same library)."""
    case = f"rp2-{request.param}"
    got = {}
    for level in (0, 2):
        root = str(tmp_path_factory.mktemp(f"e-journey-cols-{request.param}-{level}"))
        got[level] = _run(root, case, level)
    return request.param, got


def test_the_level_2_generate_writes_every_column_level_0_writes(shapes):
    # why: the flip must take no column from a reader — the list's rows (Word … Source File, its path, the counts,
    # Context / Src) and file_statistics.json's per-file keys, read from today's writer, are all in level 2's output
    language, got = shapes
    level0, level2 = got[0][0], got[2][0]
    assert "priority_learning_list.csv" in level0 and STATS in level0, (language, sorted(level0))
    for name, columns in level0.items():
        assert name in level2, (language, name, "level 0 writes it, level 2 doesn't")
        assert level2[name] == columns, (language, name, "level 0:", columns, "level 2:", level2[name])


def test_the_level_2_redraw_after_a_move_writes_every_column_level_0_writes(shapes):
    # why: the redraw after a move writes the lists again by its own path (the engine's re-plan, its rows handed to the
    # one reader at level 2) — its columns must be today's too, and the same as its own Generate's
    language, got = shapes
    level0, level2 = got[0][1], got[2][1]
    for name, columns in level0.items():
        assert name in level2, (language, name, "level 0's redraw writes it, level 2's doesn't")
        assert level2[name] == columns, (language, name, "level 0:", columns, "level 2:", level2[name])
    for name, columns in got[2][0].items():
        if name in level2:
            assert level2[name] == columns, (language, name, "the level-2 Generate's and its redraw's differ")
