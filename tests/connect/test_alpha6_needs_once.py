"""Alpha 6 try #6 (Sonic: *Needs you* is only for a decision): a trouble of the whole language is named once for the
language, never once per episode, and a moment's state is a wait, never *Needs you*.

  * a list a Generate left unfinished (no run stamp) is one wait for every episode of the language — no *Needs you*
    entry, however many episodes are queued — and it ends by itself once a finished list is there (the next look
    prepares again, so Connect Generates if no one else has);
  * no Backfill deck, no 順 deck, Anki Miner not set up: one entry for the language (no item), counted once while it
    stands, fixed once that step goes through; Backfill's and 順's never hold an episode (its cards are made);
  * the per-episode entries an alpha 6 Connect left (*The last Generate didn't finish…*, *Backfill runs for one deck
    only…*) are fixed, so an upgraded ledger doesn't keep them for good.

What a wrong answer would cost: Sonic's alpha 6 *Needs you* listed "The last Generate didn't finish…" twenty times in
a minute, each "fixed by itself" and raised again — the real decisions buried under a state nothing asked of him.

Against `FakeSteps` (real words); the CLI errors are the verbs' own shapes, read through `runner._wait_or_needs`.
Never a live Anki, no sleeps.
"""
import pytest

from app.cli import verbs
from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import JUNBAN_NO_DECK, MINER_SETUP, NO_DECK, READ_ONLY, FakeSteps

SIX = [1, 2, 3, 4, 5, 6]
# Each episode its own real words (a word carded once is never picked again: one with none never reaches its fill)
WORDS = {"1": [["約束", "ヤクソク"], ["勇気", "ユウキ"]], "2": [["気配", "ケハイ"], ["溜め息", "タメイキ"]],
         "3": [["上層部", "ジョウソウブ"]], "4": [["一生懸命", "イッショウケンメイ"]], "5": [["走り出す", "ハシリダス"]],
         "6": [["心配", "シンパイ"]], "7": [["景色", "ケシキ"]], "8": [["秘密", "ヒミツ"]]}


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan, looks=1, clear=None, items=SIX):
    steps = FakeSteps(str(tmp_path), dict({"line": {"ja": list(items)}, "queue": {"ja": list(items)},
                                           "words": WORDS}, **plan))

    def sleep(_seconds):
        for key in clear or ():
            steps.plan.pop(key, None)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=sleep, looks=looks)
    return steps, summary


def _open(ledger):
    return [(n["kind"], n["item_id"], n["say"]) for n in ledger.needs("ja", listed=False)]


def _calls(steps, name):
    return [e for e in steps.log if e[0] == name]


# --- the unfinished list: a wait -----------------------------------------------------------------------------------

def test_an_unfinished_list_is_one_wait_for_six_episodes_and_no_needs_you_entry(tmp_path, ledger):
    steps, summary = _run(tmp_path, ledger, {"list_unfinished": True})
    assert _open(ledger) == [] and summary["languages"]["ja"]["needs"] == [], "nothing for the learner to decide"
    jobs = ledger.jobs("ja")
    assert len(jobs) == 6 and {(j["state"], j["reason"]) for j in jobs} == {("waiting", runner.NO_LIST)}, \
        "every episode waits on the language's list, with one line"
    assert len(_calls(steps, "pick")) == 1, "the first episode's look tells it: the other five aren't tried"
    assert summary["looks"] == 1 and runner.holds_every(runner.NO_LIST)


def test_the_wait_ends_by_itself_once_a_finished_list_is_there(tmp_path, ledger):
    # the first look meets the unfinished list; between the two looks the next Generate stamps it
    steps, summary = _run(tmp_path, ledger, {"list_unfinished": True}, looks=2, clear=["list_unfinished"])
    assert [j["state"] for j in ledger.jobs("ja")] == ["done"] * 6
    assert not any(j["reason"] == runner.NO_LIST for j in ledger.jobs("ja")) and _open(ledger) == []
    assert _calls(steps, "prepare") == [("prepare", "ja")] * 2, \
        "the look after the wait prepares again (Connect's own Generate when no one else has made the list)"


def test_a_finished_list_needs_no_second_prepare(tmp_path, ledger):
    steps, _summary = _run(tmp_path, ledger, {}, looks=2)
    assert _calls(steps, "prepare") == [("prepare", "ja")], "once a run (02 §4) unless the list was unfinished"


def test_alpha_6s_per_episode_unfinished_entries_are_fixed_once_a_list_is_read(tmp_path, ledger):
    for item in (1, 2, 3, 7):
        ledger.need("ja", "bad-data", verbs.UNFINISHED, item_id=item)
    ledger.need("ja", "mine-failed", "Example Show 07: Anki Miner stopped twice", item_id=7)
    _run(tmp_path, ledger, {})
    assert _open(ledger) == [("mine-failed", 7, "Example Show 07: Anki Miner stopped twice")], \
        "every old *Generate didn't finish* entry goes — an episode not queued now too — and nothing else"


def test_an_unfinished_list_leaves_alpha_6s_entries_until_a_list_is_read(tmp_path, ledger):
    ledger.need("ja", "bad-data", verbs.UNFINISHED, item_id=1)
    _run(tmp_path, ledger, {"list_unfinished": True})
    assert _open(ledger) == [("bad-data", 1, verbs.UNFINISHED)], "a pick that read no list fixes nothing"


# --- Backfill's deck: once for the language, never holding an episode -------------------------------------------

def test_no_backfill_deck_is_one_need_for_the_language_and_every_episodes_cards_are_made(tmp_path, ledger):
    steps, _summary = _run(tmp_path, ledger, {"fill_no_deck": True})
    assert _open(ledger) == [("backfill-deck", None, NO_DECK)], "one entry, the language's"
    assert len(ledger.needs("ja", unseen=True)) == 1, "counted once in the badge"
    assert [j["state"] for j in ledger.jobs("ja")] == ["done"] * 6, "no episode waits for a deck"
    assert all("filling" in (j["skipped"] or "") for j in ledger.jobs("ja")), "each names the step it ended without"
    assert len(_calls(steps, "order")) == 6, "ordered all the same"


def test_a_seen_backfill_deck_need_is_never_counted_again_while_it_stands(tmp_path, ledger):
    _run(tmp_path, ledger, {"fill_no_deck": True}, items=[1, 2])
    ledger.mark_seen([n["id"] for n in ledger.needs("ja")])
    _steps, summary = _run(tmp_path, ledger, {"fill_no_deck": True}, items=[3, 4])
    assert summary["languages"]["ja"]["needs"] == [] and ledger.needs("ja", unseen=True) == []
    assert _open(ledger) == [("backfill-deck", None, NO_DECK)]


def test_the_backfill_deck_need_goes_once_a_fill_goes_through(tmp_path, ledger):
    _run(tmp_path, ledger, {"fill_no_deck": True}, items=[1, 2])
    _run(tmp_path, ledger, {}, items=[3])
    assert _open(ledger) == [], "a deck chosen: the next fill fixes it by itself"


def test_alpha_6s_per_episode_backfill_entries_become_the_one(tmp_path, ledger):
    for item in (1, 2, 3):
        ledger.need("ja", "needs-you", NO_DECK, item_id=item)
    _run(tmp_path, ledger, {"fill_no_deck": True}, items=[4])
    assert _open(ledger) == [("backfill-deck", None, NO_DECK)]


# --- 順's deck and Anki Miner's setup ----------------------------------------------------------------------------

def test_no_junban_deck_is_one_need_for_the_language(tmp_path, ledger):
    _run(tmp_path, ledger, {"order_no_deck": True})
    assert _open(ledger) == [("junban-deck", None, JUNBAN_NO_DECK)]
    assert [j["state"] for j in ledger.jobs("ja")] == ["done"] * 6
    _run(tmp_path, ledger, {}, items=[7])
    assert _open(ledger) == [], "順 ordered once a deck is chosen: fixed by itself"


def test_anki_miner_not_set_up_is_one_need_and_every_episode_waits_on_it(tmp_path, ledger):
    steps, summary = _run(tmp_path, ledger, {"miner_setup": True})
    assert _open(ledger) == [("anki-miner-setup", None, MINER_SETUP)]
    assert summary["languages"]["ja"]["needs"] == [MINER_SETUP]
    assert len(_calls(steps, "mine")) == 1, "the first episode tells it: the others aren't sent to Anki Miner"
    assert {(j["state"], j["reason"]) for j in ledger.jobs("ja")} == {("waiting", MINER_SETUP)}, \
        "every episode waits on the one entry (the feed's *held*)"
    _run(tmp_path, ledger, {}, items=SIX)
    assert _open(ledger) == [] and [j["state"] for j in ledger.jobs("ja")] == ["done"] * 6, \
        "set up: the next start mines them all, and the entry is fixed by itself"


# --- the shapes the verbs and Anki answer -------------------------------------------------------------------------

def test_the_runner_reads_each_cli_error_as_the_wait_or_the_need_it_is():
    from app.cli.contract import CliError
    unfinished = runner._wait_or_needs(CliError("busy", verbs.UNFINISHED, list="unfinished"), "ordering")
    assert isinstance(unfinished, runner.Wait) and unfinished.reason == runner.NO_LIST and unfinished.look
    assert unfinished.resume == "ordering"
    held = runner._wait_or_needs(CliError("busy", "Generate is running. Try again when it has finished.",
                                          lock="results"), None)
    assert isinstance(held, runner.Wait) and held.reason.startswith("Generate is running")
    deck = runner._wait_or_needs(CliError("needs-you", NO_DECK, ask="choose a deck in Backfill",
                                          need="backfill-deck"), "filling")
    assert isinstance(deck, runner.Needs) and (deck.kind, deck.say, deck.whole) == ("backfill-deck", NO_DECK, True)
    own = runner._wait_or_needs(CliError("failed", "Nothing was filled: it could not finish"), "filling")
    assert isinstance(own, runner.Needs) and not own.whole, "an episode's own failure stays the episode's"


@pytest.mark.parametrize("message, whole", [
    ("deck was not found: 日本語::Mining", True),
    ("model was not found: Lapis", True),
    ("field was not found: Expression", True),
    ("note was not found: 1730000000000", False),
    ("cannot create note because it is a duplicate", False),
])
def test_a_lasting_anki_refusal_is_the_languages_unless_it_names_one_note(message, whole):
    from app import anki_connect
    need = runner._anki_wait("http://127.0.0.1:8765", "mining", anki_connect.AnkiError(message, "action"))
    assert isinstance(need, runner.Needs) and need.kind == "anki-refused" and need.whole is whole


def test_anki_miners_own_needs_are_the_languages_and_its_moments_are_waits():
    from app.connect import anki_miner
    blocked = runner._miner_wait_or_needs(anki_miner.AnkiMinerError("quarantined", "Windows Security blocked it."))
    assert isinstance(blocked, runner.Needs) and blocked.whole and blocked.kind == "anki-miner-quarantined"
    failed = runner._miner_wait_or_needs(anki_miner.AnkiMinerError("failed", "the run failed"))
    assert isinstance(failed, runner.Needs) and not failed.whole
    assert isinstance(runner._miner_wait_or_needs(anki_miner.AnkiMinerError("busy", "open")), runner.Wait)
    error = verbs._miner_error(anki_miner.AnkiMinerError("too-old", "Anki Miner 3.5 is too old."))
    assert error.code == "needs-you" and error.context["need"] == "anki-miner-too-old"
    assert "need" not in verbs._miner_error(anki_miner.AnkiMinerError("crashed", "it stopped")).context


# --- an upgraded ledger, a deferred order, a list that stays unfinished, new words -----------------------------

def test_the_fakes_deck_words_are_the_verbs_own():
    assert (NO_DECK, JUNBAN_NO_DECK) == (verbs.BACKFILL_ONE_DECK, verbs.JUNBAN_ONE_DECK)


def test_alpha_6s_per_episode_deck_entries_go_once_a_deck_is_chosen(tmp_path, ledger):
    # the deck chosen before Connect fills again — the old rows' jobs are done, nothing raises them again
    for item in (1, 2, 3):
        ledger.need("ja", "needs-you", NO_DECK, item_id=item)
    for item in (4, 5):
        ledger.need("ja", "needs-you", JUNBAN_NO_DECK, item_id=item)
    _run(tmp_path, ledger, {}, items=[6])
    assert _open(ledger) == [], "a fill and an order that went through end the old copies too"


def test_a_deferred_order_never_clears_the_junban_deck_need(tmp_path, ledger):
    # a re-order the plan defers to the Generate after mining never asked 順: its deck is still not chosen
    _run(tmp_path, ledger, {"order_no_deck": True}, items=[1])
    ledger.mark_seen([n["id"] for n in ledger.needs("ja")])
    _run(tmp_path, ledger, {"order_deferred": True}, items=[2])
    assert _open(ledger) == [("junban-deck", None, JUNBAN_NO_DECK)]
    assert ledger.needs("ja", unseen=True) == [], "never fixed and raised again: nothing new in the badge"


def test_a_list_that_stays_unfinished_is_prepared_again_once_a_run(tmp_path, ledger):
    # Connect's own Generate once, then it waits for the next one — never a Generate every look
    steps, summary = _run(tmp_path, ledger, {"list_unfinished": True}, looks=4)
    assert summary["looks"] == 4
    assert _calls(steps, "prepare") == [("prepare", "ja")] * 2
    assert {j["reason"] for j in ledger.jobs("ja")} == {runner.NO_LIST} and _open(ledger) == []


def test_a_standing_need_in_new_words_follows_them_and_counts_again(ledger):
    # the deck fixed, the note type now missing — the entry must name what is open now
    deck = "Anki turned down Connect's request: deck was not found: 日本語::Mining"
    model = "Anki turned down Connect's request: model was not found: Lapis"
    assert ledger.need("ja", "anki-refused", deck, standing=True)
    ledger.mark_seen([n["id"] for n in ledger.needs("ja")])
    assert not ledger.need("ja", "anki-refused", deck, standing=True), "the same words: nothing written (S19)"
    assert ledger.needs("ja", unseen=True) == []
    assert ledger.need("ja", "anki-refused", model, standing=True), "new words: a new decision, counted"
    assert _open(ledger) == [("anki-refused", None, model)]
    ledger.dismiss(ledger.needs("ja")[0]["id"])
    assert not ledger.need("ja", "anki-refused", deck, standing=True), "dismissed stays dismissed (03 §4)"
    assert [n["say"] for n in ledger.needs("ja", listed=False)] == [deck], "its words still follow"


def test_a_library_that_cant_take_the_record_is_one_entry_gone_once_a_record_goes_through(tmp_path, ledger):
    # the language's, once (the old window's *Show me how* keys on `no-store`); a record that goes through ends it
    _run(tmp_path, ledger, {"library_read_only": True}, items=[1, 2])
    assert _open(ledger) == [("no-store", None, READ_ONLY)]
    _run(tmp_path, ledger, {"library_read_only": True}, items=[3])
    assert len(ledger.needs("ja", listed=False)) == 1
    _run(tmp_path, ledger, {}, items=[4])
    assert _open(ledger) == [], "a record that went through fixes it by itself"
