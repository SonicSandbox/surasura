"""Kyou-SH (a tester's report, 2026-11-20; the lead's GO, PROVISIONAL until Sonic rules): Connect's shelf follows
Junban's *Suspend them*, and a shelving is said where Connect's activity shows.

A tester had *Suspend them* off in 順 and found 236 of the cards Connect made suspended and tagged `surasura::shelf`:
the shelf (P2.4-1) sets aside the lowest-ranked waiting cards at the card cap, and nothing he could see said so or
let him say no. Now:

- **(b) the shelf follows *Suspend them*** (`junban_later_suspend`): off — the default — nothing goes to the shelf,
  and Connect waits at the cap as it always did (*Your N cards are waiting*); on, the shelf works as before.
- **(a) it is said**: *Needs you* holds ONE card while cards Connect made sit on the shelf — *N cards made for you
  went to the shelf* · *Put back* (every restore point still holding cards, the put-back Connect's switch already
  uses) · *Leave them* (answered; the next shelving asks again).

What a wrong answer costs: cards suspended in Anki by a switch the learner turned off (the report), a shelving no one
sees, or a *Put back* that puts back what wasn't shelved. Against `runner.Steps` with its Anki reads stubbed and the
needs service's pure entries; no Anki, no network.
"""
import pytest

from app.connect import runner
from app.services import needs


class _Shelf:
    """Stands in for `Steps._shelve` (the plan and Anki's writes): counts the tries and frees `frees` cards."""

    def __init__(self, frees=5):
        self.calls, self.frees = 0, frees

    def __call__(self, lang, ledger, todo, count, cap):
        self.calls += 1
        return self.frees


def _steps(**settings):
    """A run's steps at the cap: 12 cards waiting for a cap of 10, five of them shelvable."""
    steps = runner.Steps(dict({"connect_enabled": True}, **settings))
    steps.cap = lambda lang: 10
    waiting = iter([12, 7])                         # before the shelf, then after it freed five
    steps.waiting_count = lambda lang: next(waiting)
    steps._shelve = _Shelf()
    return steps


TODO = [{"word": "撒く", "reading": "まく"}, {"word": "血塗れ", "reading": "ちまみれ"}]


# --- (b) the shelf follows *Suspend them* ---------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_with_suspend_them_off_nothing_goes_to_the_shelf_and_connect_waits_at_the_cap(value):
    # why: the report — Suspend them off, 236 cards suspended anyway; off (or not explicitly on) means no shelving
    steps = _steps(**({} if value is None else {"junban_later_suspend": value}))
    held = runner._at_cap(steps, None, "ja", TODO)
    assert isinstance(held, runner.Wait) and "12 cards are waiting" in held.reason, "waits at the cap, as before the shelf"
    assert steps._shelve.calls == 0, "the shelf never asked: nothing suspended"


def test_with_suspend_them_on_the_shelf_works_as_before():
    steps = _steps(junban_later_suspend=True)
    assert runner._at_cap(steps, None, "ja", TODO) is None, "the shelf freed room under the cap: the batch goes on"
    assert steps._shelve.calls == 1


def test_the_shelf_reads_suspend_them_as_settings_json_holds_it_now(monkeypatch):
    # a live run (Connect's own) reads settings.json at each look, as the cap does: switching Suspend them off in
    # Settings reaches a Connect already running
    steps = runner.Steps({"connect_enabled": True, "junban_later_suspend": True})
    steps.live = True
    monkeypatch.setattr(steps, "_settings", lambda lang: {"junban_later_suspend": False, "target_language": lang})
    assert steps.shelf_on("ja") is False


def test_with_suspend_them_off_the_next_job_waits_before_its_pick():
    # the review: off counts as the run's one try (as a missing Junban does), so `_full` holds the next job at the cap
    # before its pick — never picked again at every look
    steps = _steps(junban_later_suspend=False)
    assert isinstance(runner._at_cap(steps, None, "ja", TODO), runner.Wait)
    assert steps.shelf_tried("ja") is True
    steps.waiting_count = lambda lang: 12
    held = runner._full(steps, "ja")
    assert isinstance(held, runner.Wait) and "12 cards are waiting" in held.reason
    assert runner._full(steps, "ja", asked=True) is None, "Mine now is never held"


def test_below_the_cap_the_switch_is_never_asked():
    steps = _steps(junban_later_suspend=False)
    steps.waiting_count = lambda lang: 3
    asked = []
    steps.shelf_on = lambda lang: asked.append(lang) or False
    assert runner._at_cap(steps, None, "ja", TODO) is None and asked == []


# --- (a) said in *Needs you* ------------------------------------------------------------------------------------------ #
def _connect(on_shelf=236, runs=None):
    runs = runs if runs is not None else [
        {"run": "shelf-20261120-171012", "cards": 236, "back": 0, "why": "the cap", "at": "2026-11-20T17:10:12Z",
         "words": ["撒く", "血塗れ"]},
        {"run": "shelf-20261118-090000", "cards": 12, "back": 12, "why": "the cap", "at": "2026-11-18T09:00:00Z",
         "words": ["眼鏡"]}]
    return {"shelf": {"on_shelf": on_shelf, "runs": runs, "swap_ins": 0}, "needs": [], "gaps": []}


def _shelf_entries(connect, cards_on=True, answered=frozenset(), seen=frozenset()):
    return [e for e in needs.entries(None, connect=connect, cards_on=cards_on, answered=answered, seen=seen)
            if e.kind == needs.SHELVED]


def test_cards_on_the_shelf_are_one_card_with_put_back_and_leave_them():
    [entry] = _shelf_entries(_connect())
    assert entry.title == "236 cards made for you went to the shelf."
    assert entry.actions == ("put_back_shelf", "leave_shelf")
    assert entry.unseen, "a new shelving counts on the tab"
    assert entry.data["runs"] == ["shelf-20261120-171012"], "only restore points still holding cards are put back"
    assert entry.data["cards"] == 236
    assert "surasura::shelf" in entry.say


def test_one_card_says_so_in_the_singular():
    connect = _connect(on_shelf=1, runs=[{"run": "shelf-1", "cards": 1, "back": 0, "words": ["撒く"]}])
    [entry] = _shelf_entries(connect)
    assert entry.title == "A card made for you went to the shelf."


def test_nothing_on_the_shelf_is_no_card():
    assert _shelf_entries(_connect(on_shelf=0, runs=[{"run": "shelf-1", "cards": 4, "back": 4}])) == []
    assert _shelf_entries({"shelf": {"on_shelf": 0, "runs": []}}) == []
    assert _shelf_entries({}) == [] and _shelf_entries(None) == []


def test_with_cards_made_for_you_off_there_is_no_card():
    # Put back is Connect's own restore: with its switch off it can't run (the switch's own put-back asks then)
    assert _shelf_entries(_connect(), cards_on=False) == []


def test_leave_them_is_answered_until_the_shelf_takes_more():
    [entry] = _shelf_entries(_connect())
    answered = frozenset(needs.answer_keys(entry))
    assert _shelf_entries(_connect(), answered=answered) == []
    newer = _connect(on_shelf=250, runs=[{"run": "shelf-20261121-080000", "cards": 14, "back": 0}]
                     + _connect()["shelf"]["runs"])
    [again] = _shelf_entries(newer, answered=answered)
    assert again.title == "250 cards made for you went to the shelf."
    assert again.data["runs"] == ["shelf-20261121-080000", "shelf-20261120-171012"]


def test_leave_them_holds_when_the_newest_restore_point_is_back_and_an_older_one_still_holds_cards():
    # the review: the key names the newest restore point, never falling back to an older one once it is put back
    older = {"run": "shelf-20261118-090000", "cards": 12, "back": 0}
    [entry] = _shelf_entries(_connect(on_shelf=248, runs=[_connect()["shelf"]["runs"][0], older]))
    answered = frozenset(needs.answer_keys(entry))
    newest_back = dict(_connect()["shelf"]["runs"][0], back=236)
    assert _shelf_entries(_connect(on_shelf=12, runs=[newest_back, older]), answered=answered) == []


def test_a_seen_card_stops_counting():
    [entry] = _shelf_entries(_connect())
    [seen] = _shelf_entries(_connect(), seen=frozenset({entry.key}))
    assert not seen.unseen and needs.badge([seen]) == 0
