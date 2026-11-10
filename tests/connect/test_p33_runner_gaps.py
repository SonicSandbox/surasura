"""P3.3's planted-bug pass (research/mutants JUDGED-P3.3): the loop's gaps the change's own tests missed — the inbox
read again between two jobs, the Generate after mining failing in a way other than an OSError, a stop during that
Generate, and a follow-up re-order the new plan still can't serve.

What a wrong answer would cost: an episode you queued while Connect mined waiting for the next start; a run ended by
one unexpected error after its cards were made; jobs mined after you switched Connect off; Anki's order marked paid
while it is still the stale one.

Against `FakeSteps` (real Japanese words, a real ledger); never a live Anki, no sleeps.
"""
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps

WORDS = {"1": [["上層部", "ジョウソウブ"], ["一生懸命", "イッショウケンメイ"]], "2": [["約束", "ヤクソク"], ["勇気", "ユウキ"]],
         "3": [["気配", "ケハイ"], ["退屈", "タイクツ"]]}


def _run(tmp_path, steps, looks=1):
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=looks)
        owed = ledger.resort_owed("ja")
    return summary, owed


def _picks(steps):
    return [e[1] for e in steps.log if e[0] == "pick"]


class QueuedWhileItemOneMines(FakeSteps):
    """You queue item 2 (higher in the top 20 than item 3) while item 1 is being mined."""

    def mine(self, lang, job, picked, words, attempt):
        result = super().mine(lang, job, picked, words, attempt)
        if job["item_id"] == 1 and 2 not in self.plan["queue"][lang]:
            self.plan["queue"][lang].append(2)
        return result


def test_an_episode_queued_while_another_mines_is_read_before_the_next_job_and_goes_in_its_place(tmp_path):
    # why (P3.3 B03): `_language` reads the inbox again after every job (`look`), so a new episode higher in the top
    # 20 goes next in this run — not after the rest, and not only at the next start
    steps = QueuedWhileItemOneMines(str(tmp_path), {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 3]},
                                                    "words": WORDS})
    summary, _owed = _run(tmp_path, steps)
    assert _picks(steps) == [1, 2, 3], steps.log
    assert summary["languages"]["ja"]["done"] == [1, 2, 3]


class GenerateRaises(FakeSteps):
    """The Generate after mining fails with an error no step names (a RuntimeError, not an OSError)."""

    def generate_after(self, lang, ledger):
        if lang not in getattr(self, "after", ()):
            return False
        self.after.discard(lang)
        self.log.append(("generate", lang))
        raise RuntimeError("the analyzer's child couldn't be started")


def test_any_error_from_the_generate_after_mining_never_ends_the_run_and_leaves_the_re_sort_owed(tmp_path):
    # why (P3.3 B07, R15): mining is done when it runs — any fault there is logged, never a run-ending error, and no
    # follow-up re-order is written from a list that wasn't refreshed
    steps = GenerateRaises(str(tmp_path), {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "words": WORDS,
                                           "generate_after": True})
    summary, owed = _run(tmp_path, steps)
    assert summary["languages"]["ja"]["done"] == [1, 2] and not summary.get("stopped"), summary
    assert ("order", None) not in steps.log, "no follow-up from a list that wasn't refreshed"
    assert owed is not None, "the re-sort stays owed"


def test_switched_off_during_the_generate_after_mining_mines_none_of_the_level_looks_jobs(tmp_path):
    # why (P3.3 B11, S16 / D29): stopped during the Generate after mining, the run looks at nothing more — the jobs
    # its new run would queue (the level look) wait for the next start, never mined after you switched Connect off
    steps = FakeSteps(str(tmp_path), {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "words": WORDS,
                                      "generate_after": True, "level_after": [["ja", 1, [["気配", "ケハイ"]]]],
                                      "switch_off_after": "generate"})
    summary, owed = _run(tmp_path, steps)
    assert _picks(steps) == [1, 2], steps.log
    assert summary.get("stopped") == runner.SWITCHED_OFF, summary
    assert owed is not None


class FollowUpDeferred(FakeSteps):
    """The Generate's new plan still can't be served (its follow-up answers DEFERRED)."""

    def order(self, lang, job):
        super().order(lang, job)
        return runner.DEFERRED if job is None else None


def test_a_follow_up_the_new_plan_cant_serve_leaves_the_re_sort_owed(tmp_path):
    # why (P3.3 B13): only a follow-up that wrote Anki's order pays the re-sort; DEFERRED keeps it owed, so the next
    # look re-orders
    steps = FollowUpDeferred(str(tmp_path), {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "words": WORDS,
                                             "generate_after": True})
    _summary, owed = _run(tmp_path, steps)
    assert ("order", None) in steps.log
    assert owed is not None, "a deferred follow-up never pays the re-sort"
