"""Kantan-G (Sonic 2026-11-19: "a pause stops all a circle runs by itself"): Connect's own steps that belong to another
circle wait on that circle's pause — ス its Generate (before mining, and the one after it), 順 its Backfill and its
re-order (an episode's and F11's follow-up), Anki its syncs (the session's sync and the known-words sync at its start,
the pending AnkiWeb sync at its exit). A job parked on one goes on from its step once that circle resumes, in the same
run (the resume's kick) or at the next start — never a Stop of yours, nothing lost. Anki Miner's own pause is
Mado-PZ's (`test_pz_paused.py`).

What a wrong answer would cost: the learner pauses 順 (or ス, or Anki) to keep Anki and the PC quiet, and Connect
re-orders their Anki, runs a Generate or syncs AnkiWeb anyway; or, resumed, an episode's Backfill and re-order never
happen (its cards left unfilled, the deck out of order).

The test's own root and settings.json; Anki, Anki Miner, Backfill and 順 are stand-ins (`FakeSteps`), the real
`Steps` with its Anki, sync and Generate calls replaced.
"""
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.connect import anki_session, runner
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps

EPISODE_WORDS = {
    "ja": [("上層部", "ジョウソウブ"), ("一生懸命", "イッショウケンメイ"), ("走り出す", "ハシリダス")],
    "zh": [("认真", "ren4 zhen1"), ("约定", "yue1 ding4"), ("勇气", "yong3 qi4")],
}


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _queue(ledger, lang, item_id):
    with ledger.transaction():
        return ledger.queue(lang, item_id, "user", None, store_id="store-1")


def _steps(tmp_path, lang, paused=(), plan_extra=None):
    plan = {"line": {lang: [1]}, "words": {"1": EPISODE_WORDS[lang]}}
    plan.update(plan_extra or {})
    steps = FakeSteps(str(tmp_path), plan)
    held = set(paused)
    steps.circle_paused = lambda circle: circle in held
    steps.held = held
    return steps


def _run(steps, ledger, lang, looks=1):
    return runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=looks)


# --- 順: Backfill and the re-order -------------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_with_junban_paused_the_cards_are_made_and_backfill_and_the_reorder_wait_for_its_resume(tmp_path, ledger,
                                                                                                lang):
    """鉱 isn't paused: the episode's cards are made. 順 is: neither Backfill nor the re-order touches them; the job
    waits at its Backfill step, in the shared line's words, never a Stop — and the resume goes on from there."""
    job_id = _queue(ledger, lang, 1)
    steps = _steps(tmp_path, lang, paused={"junban"})
    _run(steps, ledger, lang)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.JUNBAN_PAUSED, "filling")
    assert sorted(steps.anki.words()) == sorted(w for w, _r in EPISODE_WORDS[lang]), "its cards are made"
    assert not [e for e in steps.log if e[0] in ("fill", "order")], "nothing of 順's ran while it was paused"
    assert not ledger.is_stopped(job_id) and not ledger.held_by_stop(job)
    after = _steps(tmp_path, lang)              # resumed: the next start (the resume's kick)
    _run(after, ledger, lang)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert [e[0] for e in after.log if e[0] in ("fill", "order", "mine")] == ["fill", "order"], \
        "it goes on from Backfill: nothing mined twice"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_junban_paused_after_backfill_holds_only_the_reorder(tmp_path, ledger, lang):
    job_id = _queue(ledger, lang, 1)
    steps = _steps(tmp_path, lang)
    real_fill = steps.fill

    def fill_then_pause(*a):
        real_fill(*a)
        steps.held.add("junban")                # the click on 順 while Backfill wrote
    steps.fill = fill_then_pause
    _run(steps, ledger, lang)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.JUNBAN_PAUSED, "ordering")
    assert not [e for e in steps.log if e[0] == "order"]
    after = _steps(tmp_path, lang)
    _run(after, ledger, lang)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert [e[0] for e in after.log if e[0] in ("fill", "order")] == ["order"], "Backfill isn't run twice"


def test_a_resume_of_junban_while_connect_still_runs_lets_the_waiting_episode_go_on_in_that_run(tmp_path, ledger):
    """The episode waits at Backfill; the click that resumes 順 kicks Connect before its run ends: it goes on there,
    never only at a later start that might not come."""
    job_id = _queue(ledger, "ja", 1)
    steps = _steps(tmp_path, "ja")
    state = {"paused": True, "kicked": False}

    def look(circle):
        if circle == "junban" and state["paused"]:
            state.update(paused=False, kicked=True)     # held once, then the click again at once (its kick)
            return True
        return False

    def kicked():
        was, state["kicked"] = state["kicked"], False
        return was
    steps.circle_paused, steps.kicked = look, kicked
    _run(steps, ledger, "ja", looks=3)
    assert ledger.job_by_id(job_id)["state"] == "done", "resumed in the same run: Backfill and the re-order ran"
    assert [e[0] for e in steps.log if e[0] in ("fill", "order")] == ["fill", "order"]


def test_with_junban_paused_f11s_follow_up_reorder_waits_and_stays_owed(tmp_path, ledger):
    """The Generate after mining ran (ス isn't paused); its follow-up re-order is 順's: it waits, owed."""
    _queue(ledger, "ja", 1)
    steps = _steps(tmp_path, "ja", paused={"junban"}, plan_extra={"generate_after": True})
    _run(steps, ledger, "ja")
    assert ("generate", "ja") in steps.log
    assert ("order", None) not in steps.log, "no follow-up re-order while 順 is paused"
    assert ledger.resort_owed("ja"), "the re-sort stays owed: the next job's step pays it"


def test_another_circles_pause_never_holds_backfill_or_the_reorder(tmp_path, ledger):
    job_id = _queue(ledger, "ja", 1)
    steps = _steps(tmp_path, "ja", paused={"arrivals", "anki"})
    _run(steps, ledger, "ja")
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert [e[0] for e in steps.log if e[0] in ("fill", "order")] == ["fill", "order"]


# --- ス: the Generate before mining, parked, and released by its resume ------------------------------------------ #
class _GenerateSteps(FakeSteps):
    """`prepare` as the real one answers a plan that needs a Generate first: ス paused, the run's jobs wait."""

    def prepare(self, lang, ledger):
        self.log.append(("prepare", lang))
        if self.circle_paused("surasura"):
            raise runner.Wait(runner.GENERATE_PAUSED, look=False)
        self.log.append(("generate-first", lang))


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_with_surasura_paused_the_episodes_wait_and_its_resume_lets_them_go_on_in_that_run(tmp_path, ledger, lang):
    job_id = _queue(ledger, lang, 1)
    plan = {"line": {lang: [1]}, "words": {"1": EPISODE_WORDS[lang]}}
    steps = _GenerateSteps(str(tmp_path), plan)
    held = {"surasura"}
    state = {"kicked": False, "looks": 0}
    steps.circle_paused = lambda circle: circle in held

    def kicked():
        was, state["kicked"] = state["kicked"], False
        return was
    steps.kicked = kicked
    real_blocked = steps.blocked

    def blocked(l):
        state["looks"] += 1
        return real_blocked(l)
    steps.blocked = blocked
    _run(steps, ledger, lang)
    job = ledger.job_by_id(job_id)
    assert (job["state"], job["reason"]) == ("waiting", runner.GENERATE_PAUSED)
    assert not [e for e in steps.log if e[0] in ("mine", "generate-first")], "nothing mined, no Generate"
    held.clear()                                # the resume: its kick wakes the run, the parked job goes again
    state["kicked"] = True
    again = _GenerateSteps(str(tmp_path), plan)
    again.circle_paused = lambda circle: False
    again.kicked = kicked
    _run(again, ledger, lang)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert ("generate-first", lang) in again.log


def test_a_parked_episode_is_let_go_by_its_own_circles_resume_only(tmp_path, ledger):
    """`_woken`: a job parked on ス's pause goes again once ス resumed — not when another circle did."""
    job_id = _queue(ledger, "ja", 1)
    with ledger.transaction():
        ledger.set_state(job_id, "waiting", reason=runner.GENERATE_PAUSED)
    held = {"surasura"}
    steps = SimpleNamespace(kicked=lambda: True, circle_paused=lambda c: c in held, paused=lambda: False)
    parked = {job_id: None}
    runner._woken(steps, ledger, parked)
    assert job_id in parked, "ス still paused: it stays parked"
    held.clear()
    runner._woken(steps, ledger, parked)
    assert job_id not in parked


# --- the real Steps: its Generate, its syncs --------------------------------------------------------------------- #
@pytest.fixture
def real(monkeypatch):
    """`runner.Steps` with every call off the machine replaced and recorded."""
    calls = []
    monkeypatch.setattr(verbs, "_results_language", lambda: None)
    monkeypatch.setattr(anki_session, "begin", lambda url, loaded: calls.append("session-sync"))
    monkeypatch.setattr(verbs, "known_sync", lambda ns: calls.append("known-sync"))
    steps = runner.Steps({"connect_enabled": True})
    verdict = {"generate": "first"}
    steps.current = lambda lang, fresh=False: SimpleNamespace(generate=verdict["generate"], reason="known",
                                                              result=None)
    steps._generate = lambda ns, say, ledger=None: calls.append("generate")
    steps.notes_gone = lambda lang: None
    steps.shelf_session = lambda lang, ledger: None
    return steps, calls, verdict


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_with_surasura_paused_connects_generate_first_waits_parked_and_never_runs(real, lang):
    steps, calls, _verdict = real
    h.write_settings(connect_enabled=True, paused=["surasura"])
    with pytest.raises(runner.Wait) as w:
        steps.prepare(lang, None)
    assert w.value.reason == runner.GENERATE_PAUSED and w.value.look is False
    assert "generate" not in calls and calls == ["session-sync", "known-sync"], "Anki's syncs aren't ス's"
    h.write_settings(connect_enabled=True, paused=[])
    steps.prepare(lang, None)
    assert calls[-1] == "generate"


def test_with_anki_paused_connect_neither_syncs_the_session_nor_known_words_and_still_prepares(real):
    steps, calls, verdict = real
    verdict["generate"] = "no"
    h.write_settings(connect_enabled=True, paused=["anki"])
    steps.prepare("ja", None)
    assert calls == [], "no session sync, no known-words sync"
    h.write_settings(connect_enabled=True, paused=["junban", "miner"])
    steps.prepare("ja", None)
    assert calls == ["session-sync", "known-sync"], "another circle's pause leaves them"


def test_with_surasura_paused_the_generate_after_mining_waits_and_stays_owed(real, monkeypatch):
    steps, calls, _verdict = real
    steps._after["ja"] = "known"
    monkeypatch.setattr(steps, "_serves", lambda lang, got: None)
    h.write_settings(connect_enabled=True, paused=["surasura"])
    with pytest.raises(runner.Wait) as w:
        steps.generate_after("ja", None)
    assert w.value.reason == runner.GENERATE_PAUSED and "generate" not in calls
    assert steps._after.get("ja") == "known", "still owed"
    h.write_settings(connect_enabled=True, paused=[])
    assert steps.generate_after("ja", None) is True and calls == ["generate"]


def test_with_anki_paused_connects_pending_ankiweb_sync_at_its_exit_waits(monkeypatch):
    settled = []
    monkeypatch.setattr(verbs, "_session", lambda loaded: SimpleNamespace(
        settle=lambda url, loaded: settled.append(url)))
    steps = runner.Steps({"connect_enabled": True})
    h.write_settings(connect_enabled=True, paused=["anki"])
    steps.settle()
    assert settled == []
    h.write_settings(connect_enabled=True, paused=["surasura"])
    steps.settle()
    assert len(settled) == 1


def test_steps_reads_every_circles_pause_from_one_read_of_settings_json(monkeypatch):
    """S19: the watch asks every second, each step boundary asks for its circle — one read until the file changes."""
    import os
    import time
    h.write_settings(connect_enabled=True, paused=["junban", "anki"])
    reads = []
    real_settings = verbs.settings
    monkeypatch.setattr(verbs, "settings", lambda: reads.append(1) or real_settings())
    steps = runner.Steps({"connect_enabled": True})
    assert [steps.circle_paused(c) for c in ("miner", "surasura", "junban", "anki", "arrivals")] == \
        [False, False, True, True, False]
    assert steps.paused() is False and len(reads) == 1
    time.sleep(0.02)
    h.write_settings(connect_enabled=True, paused=["miner"])
    os.utime(os.path.join(h.root(), "settings.json"))
    assert steps.paused() is True and not steps.circle_paused("junban") and len(reads) == 2


def test_a_settings_file_that_cant_be_read_keeps_the_last_pause_read(monkeypatch):
    """Review (Haiku state, confirmed): an unreadable settings.json (held by another program) read as nothing paused,
    cached until the file changed — Connect would run what the learner paused."""
    from app.cli.contract import CliError
    h.write_settings(connect_enabled=True, paused=["junban"])
    steps = runner.Steps({"connect_enabled": True})
    assert steps.circle_paused("junban")
    steps._paused_seen = (("another stamp",), steps._paused_seen[1])      # the file moved: read again ...

    def unreadable():
        raise CliError("settings-unreadable", "held by another program")
    monkeypatch.setattr(verbs, "settings", unreadable)
    assert steps.circle_paused("junban"), "... and unreadable: the last pause read holds"
    fresh = runner.Steps({"connect_enabled": True})
    assert not fresh.circle_paused("junban"), "never read: no pause (`enabled` says the file can't be read)"
