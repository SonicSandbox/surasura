"""P2.4-A24: Connect's loop kicks itself again only after a loop that ended normally with work still pending. After a
loop that was stopped (`stopped` in its summary) it never kicks, even with work pending; a normal end with work pending
does kick. Mutant P2.4-A24 drops the `not summary.get("stopped")` guard in `connect_verbs._loop`.

What a wrong answer would cost: a stopped Connect (the user cancelled it, or a battery or time limit ended it) would
start itself again straight away, so the user's stop would not stick and Connect would keep mining in the background.
The kick and the run are fakes here; no process starts and nothing touches Anki.
"""
from app.cli import connect_verbs
from app.connect import runner


def test_a_stopped_loop_never_kicks_itself_again_even_with_work_pending(monkeypatch):
    # A stopped loop (the user or a limit ended it) must not start Connect again, however much work waits:
    # the stop has to stick until the user starts Connect.
    kicked = []
    monkeypatch.setattr(connect_verbs, "_kick", lambda loaded: kicked.append(1))
    monkeypatch.setattr(connect_verbs, "_pending", lambda lang: True)
    monkeypatch.setattr(runner, "run", lambda loaded, languages, looks=None: {"stopped": "cancelled"})

    summary = connect_verbs._loop({}, ["ja"])

    assert summary == {"stopped": "cancelled"}
    assert kicked == [], "a stopped loop must not kick itself again"


def test_a_loop_that_ended_normally_with_work_pending_kicks_the_next_one(monkeypatch):
    # The other side of the same guard: a loop that finished on its own with work still waiting hands over to the
    # next Connect, so no backlog is left behind until the user starts Connect again.
    kicked = []
    monkeypatch.setattr(connect_verbs, "_kick", lambda loaded: kicked.append(1))
    monkeypatch.setattr(connect_verbs, "_pending", lambda lang: True)
    monkeypatch.setattr(runner, "run", lambda loaded, languages, looks=None: {})

    connect_verbs._loop({}, ["ja"])

    assert kicked == [1], "a normal end with work pending must kick the next Connect"
