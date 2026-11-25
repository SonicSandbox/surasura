"""E-L2G: the level-2 Generate's gaps closed before the flip (SPEC § 6; inert at `plan_rules.SENTENCE_TABLE = 0`).

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py), each Generated at level 2 in a child process
as the dashboard runs it. What these prove:
  - **the redraw's word_stats.json is written whole or not at all** (E-REDRAW's crash drill: a redraw killed while it
    wrote the file left it empty, and the next look ran a whole Generate): a redraw that dies part-way through that
    write leaves the last one as it was, and the next look redraws.
"""
import json
import os
import subprocess
import sys

import pytest

from tests import plan_file_cases as cases
from tests.test_e_redraw import _env, _generated, _move, _redraw

# Loaded first in the child (a sitecustomize on its path): the first write to word_stats.json — the file itself or a
# temp beside it — writes half its text and the process dies there, as a crash would.
_DIE_IN_WORD_STATS = r"""
import builtins, os
_open = builtins.open


class _Dying:
    def __init__(self, f):
        self._f = f

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._f.__exit__(*exc)

    def write(self, text):
        self._f.write(text[:len(text) // 2])
        self._f.flush()
        os._exit(9)

    def __getattr__(self, name):
        return getattr(self._f, name)


def _opened(file, mode="r", *args, **kwargs):
    f = _open(file, mode, *args, **kwargs)
    if "w" in mode and os.path.basename(str(file)).startswith("word_stats.json"):
        return _Dying(f)
    return f


builtins.open = _opened
"""


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_redraw_killed_while_it_writes_word_stats_leaves_the_last_one_and_the_next_look_redraws(language,
                                                                                                    tmp_path):
    root = _generated(language, tmp_path / "lib")
    _move(root, language, "top")
    stats = os.path.join(root, "results", "word_stats.json")
    with open(stats, encoding="utf-8") as f:
        before = f.read()
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_DIE_IN_WORD_STATS, encoding="utf-8")
    env = _env(root)
    env["PYTHONPATH"] = str(hook) + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), f"--language={language}",
                        "--static", "--no-open", "--from-plan"], cwd=cases.REPO, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 9, "the redraw died inside word_stats.json's write: " + (p.stdout + p.stderr)[-1500:]
    with open(stats, encoding="utf-8") as f:
        after = f.read()
    assert after == before, "a redraw killed mid-write leaves the last word_stats.json whole"
    json.loads(after)
    out = _redraw(root, language)               # the next look: a redraw, never a whole Generate
    assert "Redrew the journey" in out and "generating" not in out.lower(), out[-1500:]
