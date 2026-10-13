"""The order of one run's steps per language: `Steps.prepare` runs the session's known-sync, then Generate, then
the deleted-notes check, then the shelf look, each once; a shelf look that fails (Junban missing) still leaves the
deleted-notes check done and names the shelf as off (mutants P2.4-E14: Generate's call dropped; P2.4-E15: the check
moved after the shelf look).

What a wrong answer would cost: a list that is never regenerated before Connect mines from it (cards made from a
stale list), a deleted card made again because the deleted-notes check ran too late, or a missing Junban that stops
the whole run instead of naming the shelf as off.

Anki is always a fake (the session, known-sync and Generate are replaced); no network, no sleeps.
"""
import pytest

from app.cli import verbs
from app.connect import anki_session, runner


@pytest.fixture
def run_order(monkeypatch):
    """Replaces the steps `prepare` calls and records their order in `calls`."""
    calls = []
    monkeypatch.setattr(verbs, "_results_language", lambda: None)   # no other language's list is held
    monkeypatch.setattr(anki_session, "begin", lambda url, loaded: None)
    monkeypatch.setattr(verbs, "known_sync", lambda ns: calls.append("known_sync"))
    monkeypatch.setattr(verbs, "generate", lambda ns: calls.append(("generate", ns.lang)))
    return calls


def test_prepare_runs_known_sync_then_generate_then_deleted_notes_then_shelf_once_each(run_order):
    # why: Generate must run before anything reads the list, and the deleted-notes check before the shelf look
    calls = run_order
    s = runner.Steps({})
    s.notes_gone = lambda lang: calls.append("notes_gone")
    s.shelf_session = lambda lang, ledger: calls.append("shelf_session")
    s.prepare("ja", None)
    assert calls == ["known_sync", ("generate", "ja"), "notes_gone", "shelf_session"], \
        "each step runs once, in this order: the list is current before the shelf and the deleted-notes check read it"


def test_a_failing_shelf_look_still_leaves_the_deleted_notes_check_done_and_names_the_shelf_off(run_order):
    # why: the shelf needs Junban; without it the run must go on, the deleted-notes check must already be done,
    # and the learner is told the shelf is off (SHELF_NO_JUNBAN) rather than the run failing
    calls = run_order
    s = runner.Steps({})
    s.notes_gone = lambda lang: calls.append("notes_gone")

    def no_junban(lang, ledger):
        calls.append("shelf_session")
        raise ImportError("No module named 'modules.junban'")

    s.shelf_session = no_junban
    s.prepare("ja", None)
    assert "notes_gone" in calls, "the deleted-notes check runs even though the shelf look fails"
    assert calls.index("notes_gone") < calls.index("shelf_session"), "the check comes before the shelf look"
    assert s.said["ja"] == [runner.SHELF_NO_JUNBAN], "the shelf is named as off, once"
