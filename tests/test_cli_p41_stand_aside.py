"""P4.1 row 4.1.8 (C8, FT-1): the automatic re-order that waited for `anki-writer` while you put the deck back.

FT-1: after *Put Anki back the way it was…* Surasura stops re-ordering that deck by itself — the recorded (language,
deck) pair is cleared. A run that read its settings before the put-back and then waited for the Anki-write lock finds,
holding it at last, the pair gone (`reposition._put_back_since`: `stands_aside`). That is the user's own choice, not a
failure: `junban --auto` and `resort` answer it as a plain line (exit 0, `stood_aside`, nothing written), and
Connect's order step ends done with the line in its run's summary and owes no re-sort. Any other refusal of Junban's
stays a failure.

The Junban suite's fake collection (real Japanese words, a list in the results); never Anki. What a wrong answer would
cost: a put-back answered as an error — *Needs you* (or a red exit for a program) for the one thing the user chose,
and a re-sort owed that every later job tries to pay into the deck they took back.
"""
import os
from types import SimpleNamespace

import pytest

from app import anki_connect, settings_manager
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

FAKE_URL = "http://127.0.0.1:18765"         # nothing listens here: only the patched transport answers
DECK_PAIR = {"junban_replan_deck": "TheBank", "junban_replan_language": "ja"}


@pytest.fixture
def deck(monkeypatch):
    """A Japanese deck 順 recorded (3.0's pair), a current list in the results, Connect on: (fake, patched)."""
    rep = pytest.importorskip("modules.junban.tests.test_reposition")
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    rep._results(h.root(), progressive=rep._JOURNEY, library=rep._LIBRARY, floor=11)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    cards, notes, _ = rep._collection(["須藤", "散歩", "図書館", "冒険", "眼鏡", "老婆"])
    fake = rep.FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend"))
    saved = rep._settings(junban_order="content", enable_junban=True, connect_enabled=True, **DECK_PAIR)
    saved.pop("junban_url", None)
    h.write_settings(**{**saved, "anki_connect_url": FAKE_URL})
    return fake, rep._patched(fake)


@pytest.fixture
def put_back_while_waiting(monkeypatch):
    """FT C1's race: the put-back held `anki-writer` first and cleared the recorded deck (K11) — what the waiting run
    finds the moment it takes the lock. `fired` counts the takes it cleared the pair in."""
    real_take = anki_connect.take_writer
    fired = []

    def take_writer(*args, **kwargs):
        held = real_take(*args, **kwargs)
        settings_manager.save_keys({"junban_replan_deck": ""})       # what the put-back did meanwhile
        fired.append(args[0] if args else kwargs.get("verb"))
        return held
    monkeypatch.setattr(anki_connect, "take_writer", take_writer)
    return fired


def _said_line():
    """The line Junban's run says for a put-back deck (FT C1's own, from the file as it is now)."""
    from modules.junban import reposition
    return reposition._put_back_since(dict(DECK_PAIR))


@pytest.mark.parametrize("verb", [("junban", "--auto"), ("resort",)])
def test_a_put_back_while_the_run_waited_for_the_writer_is_a_plain_answer_and_nothing_is_written(
        deck, put_back_while_waiting, verb):
    # why: the user took the deck back while the run waited — exit 0 with the line, never `failed`
    fake, patched = deck
    with patched:
        code, line = h.call(*verb)
    assert put_back_while_waiting, "the run took the writer lock (the race happened)"
    assert code == 0 and line["ok"] is True and line["type"] == "result", line
    assert line["stood_aside"] and line["stood_aside"] == _said_line(), line
    assert "skipped" not in line and line["moves"] == 0 and line["undo"] is None, line
    assert fake.writes == [], "nothing written into the deck you put back"
    if verb == ("resort",):
        assert line["numbering"] is None and line["pinned_first"] == 0, "nothing numbered"


def test_without_the_put_back_the_same_run_writes_as_ever(deck):
    # the guard for the test above: the deck and list are ones the run re-orders when nothing took the deck back
    fake, patched = deck
    with patched:
        code, line = h.call("junban", "--auto")
    assert code == 0 and "stood_aside" not in line and line["moves"] > 0 and fake.writes, line


def test_any_other_refusal_of_junbans_is_still_a_failure(deck, monkeypatch):
    # why: only the put-back is the user's choice; a refusal for another reason (an unfinished snapshot, a deck gone)
    # must still say Junban made no changes, exit non-zero
    from modules.junban import auto
    monkeypatch.setattr(auto, "reorder", lambda settings, **kwargs: {
        "outcome": "refused", "report": {"ok": False, "problems": ["The last reorder did not finish."]}})
    fake, patched = deck
    with patched:
        code, line = h.call("junban", "--auto")
    assert code != 0 and line["ok"] is False and line["code"] == "failed", line
    assert "The last reorder did not finish." in line["message"]


class _OrderOnly:
    """Connect's real order step (`runner.Steps.order` → `verbs.junban`), on the list as today (no plan: Connect's
    plan read is P3.3's own suites'), Anki looked at as free (`blocked` None)."""

    def __new__(cls, loaded):
        from app.connect import runner

        class Steps(runner.Steps):
            def _plan_now(self, lang):
                return None

            def blocked(self, lang):
                return None
        return Steps(loaded)


def test_connects_order_step_ends_done_with_the_line_and_owes_no_re_sort(deck, put_back_while_waiting, tmp_path):
    # why: a job error and a re-sort owed would make every later job pay it — into the deck you took back — and
    # name your own choice in *Needs you*
    from app.connect import runner
    from app.connect.ledger import Ledger
    fake, patched = deck
    steps = _OrderOnly(settings_manager.load_settings())
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger, patched:
        jid = ledger.queue("ja", 7, "user", None)
        with ledger.transaction():
            ledger.owe_resort("ja")                 # the list moved: this job's order step pays the re-sort
        runner._order(steps, ledger, "ja", ledger.job_by_id(jid))
        job = ledger.job_by_id(jid)
        assert ledger.resort_owed("ja") is None, "no re-sort owed for a deck you put back"
        assert ledger.needs("ja") == [], "no Needs you entry"
        assert not job.get("skipped"), job          # not a skipped step: the step ended as you asked
    assert put_back_while_waiting and fake.writes == []
    out = runner._empty()
    runner._said(steps, "ja", out)
    assert out["stood_aside"] == _said_line(), "a plain line in the run's summary"


def test_connects_order_step_still_names_any_other_failure(deck, monkeypatch, tmp_path):
    from app.connect import runner
    from app.connect.ledger import Ledger
    from modules.junban import auto
    monkeypatch.setattr(auto, "reorder", lambda settings, **kwargs: {
        "outcome": "refused", "report": {"ok": False, "problems": ["The last reorder did not finish."]}})
    fake, patched = deck
    steps = _OrderOnly(settings_manager.load_settings())
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger, patched:
        jid = ledger.queue("ja", 7, "user", None)
        with ledger.transaction():
            ledger.owe_resort("ja")
        runner._order(steps, ledger, "ja", ledger.job_by_id(jid))
        assert ledger.resort_owed("ja") is not None, "a failed re-order stays owed"
        assert [n["kind"] for n in ledger.needs("ja")] == ["failed"]
    assert not getattr(steps, "stood_aside", None)


def test_the_run_summary_carries_no_stand_aside_line_when_none_happened():
    from app.connect import runner
    out = runner._empty()
    runner._said(SimpleNamespace(), "ja", out)
    assert "stood_aside" not in out


# --- N2 (the intent keeper's): Connect's fill step and FT-1's Backfill-off ------------------------------------ #
# FT-1 also switches Backfill's automatic step off when a put-back brings its deck's fields back (C16), and the put-back
# takes Connect's own journalled fills off its notes too (C18). Connect's fill step (`runner._fill` → `Steps.fill` →
# `surasura-cli backfill` → `backfill.run_named`, which takes `anki-writer`) read none of it: it filled the deck again
# at its next job. Now `backfill._fields_put_back`, read inside the writer's hold, stands it aside (a plain line) until
# you switch *Fill new cards automatically* on again.
from tests.test_cli_backfill import TAG, anki  # noqa: E402,F401  (the job's three new Lapis notes, real fields)


def _put_back_line(deck=("TheBank",), fields=True):
    """The journal's `put_back` line as `first_touch.put_back` writes it (the profile open, the order files' decks)."""
    from modules.junban import first_touch
    put = {str(1789712000000): {"Patterns": {"before": "", "after": "<div>Surasura's</div>"}}} if fields else {}
    first_touch.note("ja", "put_back", "DevTest", list(deck), landed=True, fields=put,
                     done={"cards": 0, "added_after": 0, "made_after": 0, "unsuspended": 0, "tags_off": 0, "flags": 0,
                           "fields": 1 if fields else 0})


def _fill_said():
    return ("Backfill won't fill TheBank by itself: you put its fields back the way they were. Turn on Fill new cards "
            "automatically to fill it again.")


def test_connects_fill_stands_aside_for_a_deck_whose_fields_you_put_back(anki):
    _put_back_line()
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
        dry_code, dry = h.call("backfill", "--tag", TAG, "--dry-run")
    assert code == 0 and line["ok"] is True and line["skipped"] == _fill_said(), line
    assert line["filled"] == 0 and line["undo"] is None and anki.fake.note_writes == []
    assert dry_code == 0 and dry["skipped"] == _fill_said(), "the dry run says the same"


def test_a_put_back_while_the_fill_waited_for_the_writer_is_seen_inside_the_lock(anki, monkeypatch):
    # FT C1's race for the fill: the put-back held `anki-writer` first, brought the fields back and switched the
    # automatic step off (K11, C16); the waiting fill takes the lock and must see it before it writes a field
    h.write_settings(anki_connect_url=FAKE_URL, connect_enabled=True, enable_junban=True,
                     junban_backfill_deck="TheBank", junban_backfill_fills=["patterns"], junban_auto_backfill=True)
    real_take = anki_connect.take_writer
    fired = []

    def take_writer(verb, *args, **kwargs):
        held = real_take(verb, *args, **kwargs)
        if not fired:
            _put_back_line()
            settings_manager.save_keys({"junban_auto_backfill": False})
            fired.append(verb)
        return held
    monkeypatch.setattr(anki_connect, "take_writer", take_writer)
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert fired and code == 0 and line["skipped"] == _fill_said(), line
    assert anki.fake.note_writes == [], "no field written into the deck you put back"


@pytest.mark.parametrize("case", ["switched-on-again", "no-fields", "another-deck", "none"])
def test_otherwise_connects_fill_fills_as_ever(anki, case):
    # the guards: Backfill's automatic step on again, a put-back that left the fields, another deck's, or none at all
    if case == "switched-on-again":
        _put_back_line()
        h.write_settings(anki_connect_url=FAKE_URL, connect_enabled=True, enable_junban=True,
                         junban_backfill_deck="TheBank", junban_backfill_fills=["patterns"], junban_auto_backfill=True)
    elif case == "no-fields":
        _put_back_line(fields=False)
    elif case == "another-deck":
        _put_back_line(deck=("Kaishi 1.5k",))
    with anki.patched(anki.fake):
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 0 and line["filled"] == 3 and isinstance(line["skipped"], dict), (case, line)


def test_connects_fill_step_names_the_line_and_goes_on(anki):
    # Connect's step reads a skipped line as the step skipped and named on the job (`runner._fill`), never Needs you
    from app.connect import runner
    _put_back_line()
    steps = runner.Steps(settings_manager.load_settings())
    with anki.patched(anki.fake), pytest.raises(runner.Skip) as skipped:
        steps.fill("ja", {"id": 1, "tag": TAG.rsplit("::", 1)[-1]}, [1789712000000, 1789712000002])
    assert skipped.value.why == _fill_said() and anki.fake.note_writes == []
