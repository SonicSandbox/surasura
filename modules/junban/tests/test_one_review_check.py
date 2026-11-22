"""One function answers "is a review on in Anki" for 順 too (the dup audit 2026-11-22, Evidence 5; OPEN 40).

`app.anki_connect.reviewing` — or `review_on`, for an answer 順 read in the same request as the cards it guards — is
the one check; OPEN 40 gave it an idle rule (the same card REVIEW_IDLE_S: no review). 順 asked `guiReviewActive` by
itself in five places, so after a card sat open ten minutes Connect and Tidy would write while 順 still held: two
answers to one question. Each caller here is driven with Anki answering *reviewing* while the one rule says *idle* —
it must follow the rule — and with the rule saying *reviewing* — it must hold.

What a wrong answer costs: 順 holding its re-order all night behind a card left open while the rest of Surasura writes,
or 順 writing into a live review.
"""
import pytest

from app import anki_connect
from modules.junban import ankiconnect, auto, reposition, unlisted

URL = "http://127.0.0.1:8765"


@pytest.fixture
def rule(monkeypatch):
    """The one rule stood in: `answer` is what it says; `asked` what each caller handed it."""
    state = {"answer": True, "asked": []}

    def reviewing(url, cancel=None, errors=False):
        state["asked"].append(("reviewing", url, errors))
        return state["answer"]

    def review_on(url, answer, cancel=None):
        state["asked"].append(("review_on", url, answer))
        return state["answer"] and answer is True
    monkeypatch.setattr(anki_connect, "reviewing", reviewing)
    monkeypatch.setattr(anki_connect, "review_on", review_on)
    return state


@pytest.fixture
def anki_up(monkeypatch):
    monkeypatch.setattr(ankiconnect, "probe", lambda url, *a, **k: {"ok": True})
    monkeypatch.setattr(reposition, "_url", lambda settings: URL)


@pytest.mark.parametrize("on", [True, False], ids=["a-review", "idle-by-the-rule"])
def test_the_automatic_backfill_follows_the_one_check(rule, anki_up, monkeypatch, on):
    from modules.junban import backfill
    rule["answer"] = on
    ran = []
    monkeypatch.setattr(backfill, "run_auto", lambda settings: ran.append(1) or {"added": 0})
    line, went = auto._backfill_report({})
    assert ("reviewing", URL, True) in rule["asked"], "the one check, its busy error kept for the caller"
    assert bool(ran) is (not on)


@pytest.mark.parametrize("on", [True, False], ids=["a-review", "idle-by-the-rule"])
def test_the_automatic_reorder_follows_the_one_check(rule, anki_up, monkeypatch, on):
    rule["answer"] = on
    monkeypatch.setattr(reposition, "list_is_stale", lambda *a, **k: True)
    monkeypatch.setattr(reposition, "_language", lambda settings: "ja")
    got = auto.reorder({"junban_scope": "deck", "junban_deck": "日本語::Mining"})
    assert ("reviewing", URL, True) in rule["asked"]
    assert got["outcome"] == ("reviewing" if on else "list-stale")


@pytest.mark.parametrize("on", [True, False], ids=["a-review", "idle-by-the-rule"])
def test_the_re_check_with_only_touch_ups_follows_the_one_check(rule, on):
    rule["answer"] = on
    later = {"cards": []}
    got = reposition._still_new(URL, later, touchups=True)
    assert ("reviewing", URL, True) in rule["asked"]
    assert (got is None) is on


@pytest.mark.parametrize("on", [True, False], ids=["a-review", "idle-by-the-rule"])
def test_the_re_check_of_its_cards_judges_the_requests_own_answer_by_the_one_rule(rule, monkeypatch, on):
    # the review rides in the same request as the cards' read (one answer); the owner judges it
    rule["answer"] = on
    monkeypatch.setattr(unlisted, "has_work", lambda later: True)
    monkeypatch.setattr(ankiconnect, "multi", lambda actions, url: [{"result": [], "error": None},
                                                                    {"result": True, "error": None}])
    got = reposition._still_new(URL, {"cards": [1795289274699]})
    assert ("review_on", URL, True) in rule["asked"]
    if on:
        assert got is None, "a review: nothing acted on"
    else:
        assert got is not None, "idle by the rule: the run goes on"


@pytest.mark.parametrize("on", [True, False], ids=["a-review", "idle-by-the-rule"])
def test_the_due_re_check_judges_the_requests_own_answer_by_the_one_rule(rule, monkeypatch, on):
    rule["answer"] = on
    monkeypatch.setattr(ankiconnect, "multi", lambda actions, url: [{"result": True, "error": None}])
    reviewing, _sure, _now = ankiconnect._checked(URL, [], {}, None, True)
    assert ("review_on", URL, True) in rule["asked"]
    assert reviewing is on
