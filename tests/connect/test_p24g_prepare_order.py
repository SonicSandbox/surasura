"""The order of one run's steps per language: `Steps.prepare` runs the session's known-sync, then reads the plan's
verdict (P3.3: `current`), then Generates **only when the plan can't serve the library as it stands** ("first": a new
file, no plan) and reads the plan again, then the deleted-notes check, then the shelf look, each once; a move alone
("no") Generates nothing; known words or the level moved ("after") Generate after mining (marked here, F11). A shelf
look that fails (Junban missing) still leaves the deleted-notes check done and names the shelf as off (mutants
P2.4-E14: Generate's call dropped; P2.4-E15: the check moved after the shelf look).

What a wrong answer would cost: a new episode's words never counted before Connect mines from the list (cards made
from a stale list), a full Generate for every move holding the cards back (K78), a deleted card made again because
the deleted-notes check ran too late, or a missing Junban that stops the whole run instead of naming the shelf as off.

Anki is always a fake (the session, known-sync and Generate are replaced); no network, no sleeps.
"""
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.connect import anki_session, runner


def _plan(calls, generate="first", reason="files"):
    """`Steps.current` replaced: logs "current" and answers the verdict `generate` ("first" · "after" · "no")."""
    def current(lang, fresh=False):
        calls.append("current")
        return SimpleNamespace(generate=generate, reason=reason, result=None, listed=None)
    return current


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
    # why: when the plan can't serve the library (a new file), Generate must run before anything reads the list, the
    # plan is read again from it, and the deleted-notes check runs before the shelf look
    calls = run_order
    s = runner.Steps({})
    s.current = _plan(calls, "first")
    s.notes_gone = lambda lang: calls.append("notes_gone")
    s.shelf_session = lambda lang, ledger: calls.append("shelf_session")
    s.prepare("ja", None)
    assert calls == ["known_sync", "current", ("generate", "ja"), "current", "notes_gone", "shelf_session"], \
        "each step runs once, in this order: the list is current before the shelf and the deleted-notes check read it"
    assert s._after == {}, "nothing owed after mining"


@pytest.mark.parametrize("generate", ["no", "after"])
def test_a_plan_that_serves_the_library_runs_no_generate_before_mining(run_order, generate):
    # why (K78): a move ("no") is the re-plan's, and known words or the level ("after") are mined first — a Generate
    # here would hold every card back for a whole analysis; "after" is marked for the Generate after mining (F11)
    calls = run_order
    s = runner.Steps({})
    s.current = _plan(calls, generate, "known")
    s.notes_gone = lambda lang: calls.append("notes_gone")
    s.shelf_session = lambda lang, ledger: calls.append("shelf_session")
    s.prepare("ja", None)
    assert calls == ["known_sync", "current", "notes_gone", "shelf_session"], calls
    assert s._after == ({"ja": "known"} if generate == "after" else {})


def test_a_failing_shelf_look_still_leaves_the_deleted_notes_check_done_and_names_the_shelf_off(run_order):
    # why: the shelf needs Junban; without it the run must go on, the deleted-notes check must already be done,
    # and the learner is told the shelf is off (SHELF_NO_JUNBAN) rather than the run failing
    calls = run_order
    s = runner.Steps({})
    s.current = _plan(calls)
    s.notes_gone = lambda lang: calls.append("notes_gone")

    def no_junban(lang, ledger):
        calls.append("shelf_session")
        raise ImportError("No module named 'modules.junban'")

    s.shelf_session = no_junban
    s.prepare("ja", None)
    assert "notes_gone" in calls, "the deleted-notes check runs even though the shelf look fails"
    assert calls.index("notes_gone") < calls.index("shelf_session"), "the check comes before the shelf look"
    assert s.said["ja"] == [runner.SHELF_NO_JUNBAN], "the shelf is named as off, once"


def test_settings_that_cant_be_read_just_now_make_the_run_wait_never_needs_you(monkeypatch):
    # why: 09-hato-layer v2 Q5 — a settings.json caught half-way through a save is exit 3 (`settings-unreadable`):
    # a moment's state. Read as Needs you, one torn read would stop an episode until the learner clicked it.
    from app.cli.contract import CliError
    monkeypatch.setattr(verbs, "_results_language", lambda: None)
    monkeypatch.setattr(anki_session, "begin", lambda url, loaded: None)

    def torn(ns):
        raise CliError("settings-unreadable", "Surasura's settings (settings.json) can't be read.")

    for step in ("known_sync", "generate"):
        monkeypatch.setattr(verbs, "known_sync", torn if step == "known_sync" else (lambda ns: None))
        monkeypatch.setattr(verbs, "generate", torn)
        s = runner.Steps({})
        s.current = _plan([])                   # the plan can't serve the library: Generate first
        with pytest.raises(runner.Wait):
            s.prepare("ja", None)
    assert isinstance(runner._wait_or_needs(CliError("settings-unreadable", "x"), "mining"), runner.Wait)
