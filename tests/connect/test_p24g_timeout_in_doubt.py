"""P2.4-E22: a timed-out Anki Miner batch is in doubt, the same as a crash.

Rule: when Anki Miner stops a batch by timeout (its run may or may not have written cards), the batch is
read as in doubt: `doubt` is True and every word comes back `uncertain`, never failed and never a Wait or
a Needs. Mutant P2.4-E22 drops "timeout" from the doubt branch, so a timeout falls through to
`_miner_wait_or_needs` and stops the job with "anki-miner-timeout" instead.
What a wrong answer would cost: a word that did reach Anki would be marked failed (and mined again, or
left out of the list), or the whole job would stop for a batch that only ran slowly.
"""
from types import SimpleNamespace

from app.cli import verbs
from app.connect import anki_miner, runner
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

MAPPING = SimpleNamespace(word="Word")


def _steps():
    return runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT})


def test_a_timeout_leaves_the_batch_in_doubt_like_a_crash(monkeypatch):
    # Like a crash (test_runner_steps.py), a timeout is "the run may have written cards": the batch is in doubt,
    # every word is uncertain, and nothing is raised (a raise would stop the job or mark its words failed).
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "AnkiMiner.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir, held=None: ({}, "p1", MAPPING))

    def stopped(*a, **k):
        raise anki_miner.AnkiMinerError("timeout", "Anki Miner didn't finish in time")
    monkeypatch.setattr(anki_miner, "mine_batch", stopped)
    # Two words, so "every word" is checked for a whole batch: a regression that marks only the first word,
    # or drops one, fails here.
    words = [{"word": "気配", "reading": "ケハイ", "line_start": 3.0},
             {"word": "見る", "reading": "ミル", "line_start": 7.5}]
    got = _steps().mine("ja", {"id": 3, "item_id": 1}, {"video": "v", "subtitle": "s", "profile": "p1"},
                        words, 1)
    assert got["doubt"] is True
    assert len(got["outcomes"]) == 2
    assert [o["word"] for o in got["outcomes"]] == ["気配", "見る"]
    assert [o["outcome"] for o in got["outcomes"]] == ["uncertain", "uncertain"]
