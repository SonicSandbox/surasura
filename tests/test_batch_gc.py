"""The batch runs — a Generate, the background indexer, the sentence dictionary — pause Python's cycle collector while
they work (their long-lived tables were re-walked dozens of times a run for cycles that aren't there), and leave it as
they found it: the dashboard and this test session never go on without it."""

import gc
import sys

import pytest

from app import analyzer, indexer, sentence_corpus
from app.batch_gc import without_cycle_collection


def test_collector_is_paused_during_the_run_and_back_after():
    seen = []

    @without_cycle_collection
    def run(words):
        seen.append(gc.isenabled())
        return len(words)

    assert gc.isenabled()
    assert run(["勉強", "上層部"]) == 2          # the run's own result comes back
    assert seen == [False]
    assert gc.isenabled()


def test_collector_is_back_when_the_run_fails():
    # A run that raises (a damaged file, a full disk) must not leave the process without its collector.
    @without_cycle_collection
    def run():
        raise OSError("disk full")

    with pytest.raises(OSError):
        run()
    assert gc.isenabled()


def test_a_collector_already_off_stays_off():
    # Whoever switched it off switches it back on — the run doesn't do it for them.
    @without_cycle_collection
    def run():
        return gc.isenabled()

    gc.disable()
    try:
        assert run() is False
        assert not gc.isenabled()
    finally:
        gc.enable()


def test_every_batch_entry_point_runs_with_the_collector_paused(monkeypatch, tmp_path):
    # Each entry point's first step records whether the collector is on, then stops the run there.
    seen = {}

    def stop(name):
        def first_step(*args, **kwargs):
            seen[name] = gc.isenabled()
            raise SystemExit(0)
        return first_step

    monkeypatch.setattr(analyzer, "parse_analysis_args", stop("Generate"))
    monkeypatch.setattr(indexer, "_content_files", stop("indexer"))
    monkeypatch.setattr(sentence_corpus, "build", stop("sentence dictionary"))
    for name, entry, argv in (("Generate", analyzer.main, ["analyzer.py", "--language=ja"]),
                              ("indexer", indexer.main, ["indexer.py", "--language", "ja"]),
                              ("sentence dictionary", sentence_corpus.main,
                               ["sentence_corpus.py", "--language", "ja", "--output", str(tmp_path / "corpus.zip")])):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit):
            entry()
        assert gc.isenabled(), name
    assert seen == {"Generate": False, "indexer": False, "sentence dictionary": False}
