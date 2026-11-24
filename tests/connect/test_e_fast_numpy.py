"""numpy's BLAS held to one thread in Connect's process (the sentence choice, E-FAST; SPEC § 8.4): numpy's own
OpenBLAS starts a thread and reserves a buffer for every CPU thread at numpy's first import (759 MB of private memory
on a 24-thread desktop, 20 MB held to one: measured), and nothing the score or the table does calls BLAS. So the first
import through the score's door (`sentence_score._table`) or Connect's (`sentences.known_since`, which reads the
table's file name) is made with the BLAS variables at one — and they are put back at once, so a child process Connect
starts (Anki Miner's speech model) never inherits them; one the learner set is left as it is.

Each test runs a fresh interpreter (numpy is long imported in pytest's own), watching the import itself: a finder at
the front of `sys.meta_path` notes the variables at the moment numpy is looked for."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAMES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
SPY = """
import json, os, sys
NAMES = %r
seen = {}
class Spy:
    def find_spec(self, name, path=None, target=None):
        if name == "numpy" and "numpy" not in seen:
            seen["numpy"] = {n: os.environ.get(n) for n in NAMES}
        return None
sys.meta_path.insert(0, Spy())
from app.connect import sentences
from app import sentence_score
door, language = sys.argv[1], sys.argv[2]
if door == "known_since":
    sentences.known_since(language)
else:
    sentence_score.choose(language, (), moment=sentence_score.Moment(), length=(1, 1))
print(json.dumps({"at_import": seen.get("numpy"), "after": {n: os.environ.get(n) for n in NAMES},
                  "loaded": "numpy" in sys.modules}))
""" % (NAMES,)


def _run(tmp_path, door, language, extra=None):
    env = {k: v for k, v in os.environ.items() if k not in NAMES}
    env.update(PYTHONPATH=ROOT, SURASURA_TEST_ROOT=str(tmp_path), APPDATA=str(tmp_path / "appdata"),
               LOCALAPPDATA=str(tmp_path / "local"), XDG_DATA_HOME=str(tmp_path / "xdg"), SURASURA_SENTENCE_TABLE="1",
               PYTHONIOENCODING="utf-8", **(extra or {}))
    done = subprocess.run([sys.executable, "-c", SPY, door, language], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("door", ["score", "known_since"])
def test_numpys_first_import_through_the_score_or_connects_door_holds_blas_to_one_thread(tmp_path, door, language):
    # why: Connect's process reads the table through these two doors; numpy's first import there reserved a BLAS
    # buffer per CPU thread (759 MB private on 24 threads) for calls the score never makes
    got = _run(tmp_path, door, language)
    assert got["loaded"]
    assert got["at_import"] == {n: "1" for n in NAMES}
    assert got["after"] == {n: None for n in NAMES}       # put back: Anki Miner, started later, gets none of them


def test_a_blas_thread_count_the_learner_set_is_left_as_it_is(tmp_path):
    # why: a variable already there (set by the learner or a launcher) is theirs: neither changed nor removed
    got = _run(tmp_path, "score", "ja", extra={"OPENBLAS_NUM_THREADS": "4"})
    assert got["at_import"] == {"OPENBLAS_NUM_THREADS": "4", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    assert got["after"] == {"OPENBLAS_NUM_THREADS": "4", "OMP_NUM_THREADS": None, "MKL_NUM_THREADS": None}
