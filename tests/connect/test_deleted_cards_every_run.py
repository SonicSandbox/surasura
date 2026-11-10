"""Cards deleted in Anki are looked for in every Connect run (P2.4 row 2.4.14, "once a run"), not only in a run that
has an episode to mine (Mattias, alpha 3: "I tried to delete all the words in Anki it just created. Surasura still
think they all exists and that the episode is mined" — the look lived in `prepare` alone, so with nothing left to mine
the episode kept its ✓ *N in Anki*). `runner._gone_look` asks `Steps.notes_gone` for a language with no open job;
`Steps.notes_gone` looks once a run per language, and a look Anki didn't answer is asked again.

What a wrong answer would cost: a row that says "in Anki" for cards the learner deleted (the status lies until some
other episode is mined), or a run that asks Anki the same thing twice (S19), or a deleted card's word made again (the
deliberate rule — cards you deleted stay blocked — is `test_fix_l33_deleted_card_level_job`'s, untouched here).
"""
import json

import pytest

from app.connect import anki_session, library, runner
from app.connect.ledger import Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps
from tests.connect.test_level import _line, _mine

NOTE_ID = 1700000000041         # the card Connect made for 眼鏡 (Anki note ids are millisecond timestamps)
KEPT_ID = 1700000000042         # the card made for 老婆, still in Anki


class FakeAnki:
    """Only what `Steps.notes_gone` calls through `shelf.gone_notes`: find_notes("nid:a,b,...") answers the ids still
    in Anki; `down` raises as AnkiConnect does when Anki is closed."""

    def __init__(self, still_there, down=0):
        self.still_there, self.down, self.asked = set(still_there), down, 0

    def find_notes(self, query):
        self.asked += 1
        if self.down:
            self.down -= 1
            raise ConnectionRefusedError("Anki isn't open")
        assert query.startswith("nid:"), query
        return [n for n in map(int, query[len("nid:"):].split(",")) if n in self.still_there]


@pytest.fixture(autouse=True)
def _anki_open_here(monkeypatch):
    # Anki is open on Connect's profile: the profile check never answers by accident.
    monkeypatch.setattr(anki_session, "waiting", lambda url, settings: None)


class LookingSteps(FakeSteps):
    """FakeSteps with the deleted-cards look recorded (`raises`: its first look fails, as with Anki gone)."""

    def __init__(self, folder, plan=None, raises=False):
        super().__init__(folder, plan)
        self.looked, self.raises = [], raises

    def notes_gone(self, lang):
        self.looked.append(lang)
        if self.raises:
            self.raises = False
            raise ConnectionRefusedError("Anki isn't open")
        return []


def test_a_run_with_nothing_to_mine_still_looks_for_deleted_cards_in_each_language(tmp_path):
    steps = LookingSteps(str(tmp_path))
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja", "zh"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert steps.looked == ["ja", "zh"], "each language looked at once, though neither has an episode to mine"
    assert not [e for e in steps.log if e[0] == "prepare"], "nothing else of a mining run is asked"
    assert summary["looks"] == 1


def test_a_look_that_fails_never_ends_the_run_with_a_traceback(tmp_path):
    steps = LookingSteps(str(tmp_path), raises=True)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert steps.looked == ["ja"] and "stopped" not in summary


def _made_two():
    """Connect made 眼鏡 and 老婆 for the line's first episode (mined) -> its item id."""
    (a, _fa), _b, _d = _line()
    _mine(a)
    with c.store() as s:
        library.record_batch(s, a, {"眼鏡": [NOTE_ID], "老婆": [KEPT_ID]}, "2026-10-29T17:49:00Z", batch="1")
    return a


def test_the_real_step_takes_a_deleted_card_off_the_row_with_nothing_to_mine(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)     # Anki reachable here (a fake one)
    a = _made_two()
    steps = runner.Steps({"connect_enabled": True})
    anki = FakeAnki(still_there={KEPT_ID})
    steps._anki = lambda: anki
    runner._gone_look(steps, "ja")
    with c.store() as s:
        assert s.cards_of([a])[a] == [KEPT_ID], "the row counts only the card still in Anki"
        row = s.conn.execute("SELECT note_ids FROM made_words WHERE item_id = ? AND word = ?", (a, "眼鏡")).fetchone()
    assert row is not None and json.loads(row[0]) == [], "the word stays made (never made again by itself)"
    assert steps.notes_gone("ja") == [] and anki.asked == 1, "once a run: prepare's look later asks Anki nothing"


def test_a_look_anki_did_not_answer_is_asked_again_in_the_same_run(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    a = _made_two()
    steps = runner.Steps({"connect_enabled": True})
    anki = FakeAnki(still_there=set(), down=1)
    steps._anki = lambda: anki
    runner._gone_look(steps, "ja")                       # Anki closed: nothing marked, nothing said
    with c.store() as s:
        assert s.cards_of([a])[a] == [NOTE_ID, KEPT_ID]
    assert sorted(steps.notes_gone("ja")) == [NOTE_ID, KEPT_ID], "asked again once Anki answers"
    with c.store() as s:
        assert s.cards_of([a])[a] == [], "every card deleted: the row reads *No cards in Anki*"
    assert anki.asked == 2


def test_a_run_whose_anki_is_closed_or_switched_off_looks_at_nothing(tmp_path):
    # Anki's own state gates the look as it gates every Anki touch of a run (the adversary's MUST): never a request
    # to Anki while it is closed, on another profile, or switched off for the run.
    steps = LookingSteps(str(tmp_path), {"blocked": runner.ANKI_CLOSED})
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert steps.looked == []


def test_the_real_step_asks_anki_nothing_under_no_anki_sync():
    # The suites' (and a developer's) SURASURA_NO_ANKI_SYNC: Anki is never reached, whatever the store holds.
    a = _made_two()
    steps = runner.Steps({"connect_enabled": True})
    anki = FakeAnki(still_there=set())
    steps._anki = lambda: anki
    runner._gone_look(steps, "ja")
    assert anki.asked == 0
    with c.store() as s:
        assert s.cards_of([a])[a] == [NOTE_ID, KEPT_ID]


def test_anki_on_another_profile_marks_nothing_and_is_asked_again(monkeypatch):
    # Anki switched to another profile between the look and its answer: nothing marked gone, and the language is
    # not counted as looked — the next look this run asks again (the adversary's SHOULD).
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    a = _made_two()
    answers = ["Anki is open on another profile", None]
    monkeypatch.setattr(anki_session, "waiting", lambda url, settings: answers.pop(0) if answers else None)
    steps = runner.Steps({"connect_enabled": True})
    anki = FakeAnki(still_there={KEPT_ID})
    steps._anki = lambda: anki
    assert steps.notes_gone("ja") == []
    with c.store() as s:
        assert s.cards_of([a])[a] == [NOTE_ID, KEPT_ID]
    assert steps.notes_gone("ja") == [NOTE_ID] and anki.asked == 2
