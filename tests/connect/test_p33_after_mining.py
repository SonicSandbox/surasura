"""P3.3 row 3.3.5 (F11): the Generate after mining and its follow-up re-order. When known words moved or the level was
raised since the plan, Connect mines first — from the provisional re-plan, or the list as it is — and only then, once the
language's jobs have run this pass, Generates; then reads the plan again, re-orders Anki once from it (the re-sort
owed until that lands) and looks at the level on the new run, whose jobs it mines in the same run. Never while
stopped; once a run.

What a wrong answer would cost: every card held back for a whole analysis after a known-words sync (K78); a list
never refreshed after Connect mined from a provisional one (the next day's cards in yesterday's order); a level raise
whose new words wait for another start; a Generate started while an update waits to swap the files.

Against `FakeSteps` (real Japanese words, a real ledger) for the loop, and the real `Steps` with its verbs replaced
for the step itself; never a live Anki, no sleeps.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.cli.contract import CliError
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WORDS = {"1": [["上層部", "ジョウソウブ"], ["一生懸命", "イッショウケンメイ"]], "2": [["約束", "ヤクソク"], ["勇気", "ユウキ"]]}


def _run(tmp_path, plan, looks=1):
    steps = FakeSteps(str(tmp_path), dict({"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "words": WORDS}, **plan))
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=looks)
        owed = ledger.resort_owed("ja")
        needs = [n["kind"] for n in ledger.needs("ja")]
    return steps, summary, owed, needs


def _calls(steps):
    return [e for e in steps.log if e[0] in ("prepare", "pick", "mine", "order", "generate")]


def test_known_words_moved_mine_first_then_generate_then_one_follow_up_order(tmp_path):
    steps, summary, owed, _needs = _run(tmp_path, {"generate_after": True})
    calls = [e[:2] for e in _calls(steps)]
    assert calls == [("prepare", "ja"), ("pick", 1), ("mine", 1), ("order", 1), ("pick", 2), ("mine", 2),
                     ("order", 2), ("generate", "ja"), ("order", None)], calls
    assert summary["languages"]["ja"]["done"] == [1, 2]
    assert owed is None, "the follow-up re-order paid the re-sort"


def test_b6_the_follow_up_re_order_is_no_episodes_turn(tmp_path):
    """B-6: after the last episode, Connect's Generate and its follow-up re-order (an Anki write) run with the look's
    *working through the episodes* mark cleared — a job the window queues then waits for Connect's next look, never
    "its turn: Connect is making another episode's cards now"; the level look's next job marks it again."""
    seen = {}

    class Steps(FakeSteps):
        def order(self, lang, job):
            if job is None:
                seen["follow-up"] = ledger.working(lang)
            else:
                seen.setdefault("episode", ledger.working(lang))
            return super().order(lang, job)

    steps = Steps(str(tmp_path), {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "words": WORDS,
                                  "generate_after": True})
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None)
    assert seen["episode"] is not None, "an episode's own re-order: the look is working through them"
    assert seen["follow-up"] is None


def test_a_move_alone_runs_no_generate_in_the_loop(tmp_path):
    steps, _summary, _owed, _needs = _run(tmp_path, {})
    assert ("generate", "ja") not in steps.log and ("order", None) not in steps.log


def test_a_level_raise_mines_from_the_list_as_it_is_then_mines_the_new_words_in_the_same_run(tmp_path):
    # the band raised: the Generate after mining re-cuts the list; its level look queues item 1's new words, mined
    # in this run (no second prepare)
    steps, summary, _owed, _needs = _run(tmp_path, {"generate_after": True,
                                                    "level_after": [["ja", 1, [["気配", "ケハイ"]]]]})
    calls = [e[:2] for e in _calls(steps)]
    at = calls.index(("generate", "ja"))
    assert calls[at:] == [("generate", "ja"), ("order", None), ("pick", 1), ("mine", 1), ("order", 1)], calls
    assert calls.count(("prepare", "ja")) == 1
    assert any(e[0] == "mine" and e[3] == ["気配"] for e in steps.log), "the newly listed word, mined"


def test_a_failing_generate_is_named_once_and_mining_is_kept(tmp_path):
    steps, summary, owed, needs = _run(tmp_path, {"generate_after": True, "generate_after_error": "needs"})
    assert summary["languages"]["ja"]["done"] == [1, 2], "the cards made stand"
    assert needs.count("generate") == 1 and summary["languages"]["ja"]["needs"] == [
        "Generate didn't finish after Connect made its cards."]
    assert ("order", None) not in steps.log and owed is not None, "the re-sort stays owed"


def test_a_generate_that_waits_leaves_the_re_sort_owed_and_needs_nobody(tmp_path):
    steps, summary, owed, needs = _run(tmp_path, {"generate_after": True, "generate_after_error": "busy"})
    assert summary["languages"]["ja"]["done"] == [1, 2] and needs == [] and owed is not None


def test_a_generate_that_crashes_never_ends_the_run_and_leaves_the_re_sort_owed(tmp_path):
    # R15: mining is done; a fault in the list's refresh is logged, never the run's end
    steps, summary, owed, _needs = _run(tmp_path, {"generate_after": True, "generate_after_error": "crash"})
    assert summary["languages"]["ja"]["done"] == [1, 2] and owed is not None
    assert ("order", None) not in steps.log


def test_an_update_staged_mid_run_starts_no_generate(tmp_path):
    steps, summary, _owed, _needs = _run(tmp_path, {"generate_after": True, "staged_after_pick": True})
    assert summary.get("stopped") == runner.STOPPED_FOR_UPDATE
    assert ("generate", "ja") not in steps.log


def test_switched_off_mid_run_starts_no_generate(tmp_path):
    steps, summary, _owed, _needs = _run(tmp_path, {"generate_after": True, "switch_off_after": "mine"})
    assert ("generate", "ja") not in steps.log


@pytest.mark.parametrize("stop", [{"switch_off_after": "generate"},      # you switched Connect off meanwhile
                                  {"staged_after": "generate"}])         # an update was staged meanwhile
def test_stopped_during_the_generate_after_mining_writes_nothing_to_anki_and_owes_the_re_sort(tmp_path, stop):
    # why (S16, D29, E26): the Generate takes seconds to minutes — the off switch and a staged update
    # are looked at again before the follow-up re-order writes Anki
    steps, _summary, owed, _needs = _run(tmp_path, dict({"generate_after": True}, **stop))
    assert ("generate", "ja") in steps.log, "the Generate itself ran (mining was done before the stop)"
    assert ("order", None) not in steps.log, "no follow-up write after the stop"
    assert owed is not None, "the re-sort stays owed"


class _FailingLedger(Ledger):
    """A real ledger whose re-sort marks fail once `failing` names them (a full disk, an sqlite I/O error)."""
    failing = ()

    def owe_resort(self, language):
        if "owe" in self.failing:
            raise sqlite3.OperationalError("disk I/O error")
        return super().owe_resort(language)

    def resort_paid(self, language):
        if "paid" in self.failing:
            raise sqlite3.OperationalError("disk I/O error")
        return super().resort_paid(language)


@pytest.mark.parametrize("failing", ["owe", "paid"])
def test_a_ledger_write_failing_after_the_generate_never_ends_the_run(tmp_path, failing):
    # why (final adversary #3, R15): the re-sort marks after the Generate sat outside every guard — a ledger error
    # there ended the whole run, not one step; logged, the run goes on, and a re-sort that can't be marked paid stays
    # owed
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "words": WORDS,
                                      "generate_after": True})
    real = steps.generate_after

    def generate_after(lang, ledger):
        ran = real(lang, ledger)
        ledger.failing = (failing,)                 # the ledger fails from the Generate on
        return ran
    steps.generate_after = generate_after
    with _FailingLedger(str(tmp_path / "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        ledger.failing = ()
        owed = ledger.resort_owed("ja")
    assert summary["languages"]["ja"]["done"] == [1, 2] and not summary.get("stopped"), summary
    assert ("order", None) in steps.log, "the follow-up re-order still ran"
    if failing == "paid":
        assert owed is not None, "a re-sort that can't be marked paid stays owed"


def test_once_a_run_however_many_looks(tmp_path):
    steps, _summary, _owed, _needs = _run(tmp_path, {"generate_after": True, "blocked": None}, looks=3)
    assert steps.log.count(("generate", "ja")) == 1


# --------------------------------------------------------------------------------------------------------------- #
# The real step
# --------------------------------------------------------------------------------------------------------------- #

def _real(monkeypatch, generate):
    steps = runner.Steps({})
    seen = []
    monkeypatch.setattr(verbs, "generate", lambda ns: (seen.append(ns.lang), generate(ns))[1])
    steps.current = lambda lang, fresh=False: seen.append(("current", fresh))
    return steps, seen


def test_the_step_generates_once_when_marked_and_reads_the_plan_again(monkeypatch):
    steps, seen = _real(monkeypatch, lambda ns: {"ran": True})
    assert steps.generate_after("ja", None) is False and seen == [], "nothing owed: nothing run"
    steps._after["ja"] = "known"
    assert steps.generate_after("ja", None) is True
    assert seen == ["ja", ("current", True)] and steps._after == {}
    assert steps.generate_after("ja", None) is False, "once a run"


@pytest.mark.parametrize("code,raised", [("busy", runner.Wait), ("settings-unreadable", runner.Wait),
                                         ("crashed-child", runner.Needs)])
def test_the_steps_generate_failing_is_a_wait_or_needs_you_and_clears_the_mark(monkeypatch, code, raised):
    def fail(ns):
        raise CliError(code, "Generate failed")
    steps, _seen = _real(monkeypatch, fail)
    steps._after["ja"] = "settings"
    with pytest.raises(raised) as got:
        steps.generate_after("ja", None)
    if raised is runner.Needs:
        assert got.value.kind == "generate" and "after Connect made its cards" in got.value.say
    assert steps._after == {}


def test_the_step_defers_the_re_order_while_the_level_waits_for_its_generate(monkeypatch):
    # no re-plan to order from (the level raised): the Generate after mining's follow-up orders, never the stale list
    steps = runner.Steps({})
    steps._after["ja"] = "settings"
    steps.current = lambda lang, fresh=False: SimpleNamespace(generate="after", result=None, listed=None)
    monkeypatch.setattr(verbs, "junban", lambda ns: pytest.fail("no re-order from the list as it is"))
    assert steps.order("ja", {"id": 8, "item_id": 1}) == runner.DEFERRED


def test_a_wait_reading_the_plan_after_a_generate_that_went_through_still_follows_up(monkeypatch, tmp_path):
    # why (review H5): the Generate's success is what counts — a busy store at the re-read skipped the follow-up
    # re-order and the level look; the follow-up reads its own plan
    steps, seen = _real(monkeypatch, lambda ns: {"ran": True})

    def busy(lang, fresh=False):
        seen.append(("current", fresh))
        raise runner.Wait(runner.LIBRARY_BUSY)
    steps.current = busy
    steps._after["ja"] = "known"
    assert steps.generate_after("ja", None) is True
    assert seen == ["ja", ("current", True)]
    # through the loop's own step: the follow-up re-order runs and pays the re-sort
    steps._after["ja"] = "known"
    steps.update_staged = lambda: False
    steps.enabled = lambda: True
    steps.blocked = lambda lang: None
    steps.order = lambda lang, job: seen.append(("order", job))
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert runner._after_mining(steps, ledger, "ja", {"needs": []}) is True
        assert ledger.resort_owed("ja") is None, "the follow-up landed"
    assert seen[-1] == ("order", None)
