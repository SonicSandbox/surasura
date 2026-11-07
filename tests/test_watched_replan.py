"""Haya-W (Sonic 2026-11-06: "what is the behavior if they mark an ep done but still have the cards for it not yet
studied … Responsiveness is key"): a watched mark re-plans at once, like a move — the episode is a counted file leaving
(`plan_engine.check`'s "files-removed") that joins the set-aside files with the digest its plan line holds
("reference-watched"): the engine drops its uses, Anki's order follows in the host's next job, and the Generate still
runs after, in the background, for the list's edge (a word crossing the cut-off).

On RP-2's libraries (tests/plan_file_cases.py: real Japanese and Chinese text across NOW, Soon and 6+ Months),
generated per test, your 順 actions on (tag + suspend, as Sonic runs them) and a fake AnkiConnect holding a card for
every listed word (and for the words met only in the episode). What these prove, ja and zh:

  - a stone on an episode whose cards aren't studied yet: in the same job as a move's, its own words' cards step back
    (tagged, suspended) and a word it shares moves its first place to the next episode it appears in — Connect reads
    the same re-plan ("after": mined from it, the Generate after) and the window's numbers follow a fresh load;
  - un-marking before the Generate (a mis-click's Undo): the library is the plan's again — the cards back at once;
    un-marking after it: the new plan has no line for a set-aside episode, so a Generate first (as before);
  - *Keep studying watched episodes* on: a stone moves nothing that counts — no Anki write, no Generate asked;
  - the background Generate the mark asked for corrects the edge: after its re-order, Anki holds the Generate's own
    order (the next job writes nothing).

What a wrong answer would cost a learner: a stone that leaves its episode's cards at the front of Anki's queue for a
minute or two (the whole Generate at 20k files), or a re-plan that never meets the Generate's list again.
"""
import pytest

pytest.importorskip("modules.junban")

from app import plan_engine, replan_preview  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402
from tests.test_replan_preview import _generate, _host, _language, lib  # noqa: E402,F401
from tests.test_replan_preview_watched import _acting, _job, _suspended  # noqa: E402

MARK = ("replan-now", ("files-removed", "reference-watched"))


def _verdict(host, store):
    plan = plan_engine.load(replan_preview.plan_path())
    return host._verdict(plan, host._parts(host._settings(), store), store)


def _connect(store):
    import json
    import os
    from app.connect import replan as connect_replan
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    return connect_replan.current(_language(), settings, store)


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_a_stone_with_unstudied_cards_moves_its_words_on_and_its_cards_back_at_once(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    asked = []
    host, lines = _host(generate=asked.append)
    with _patched(fake):
        host._job("catch-up")                          # the ladder laid, the plan recorded: nothing owed
        assert not _suspended(fake, own)
        before = _connect(store)
        assert before.generate == "no"
        shared = [key for key, item in before.result.first.items() if item == episode]
        asked.clear()

        store.set_watched([episode])
        assert _verdict(host, store) == MARK
        written = _job(fake, host)
        assert written, "the stone's job wrote nothing: Anki waits for the Generate"
        assert _suspended(fake, own) == set(own), "the stone's own words' cards step back at once"
        assert asked == ["replan-now: files-removed,reference-watched"], "the Generate still runs after, for the edge"

        got = _connect(store)
        assert got.verdict == MARK and got.generate == "after" and got.result is not None, (got.verdict, got.reason)
        assert episode not in got.result.sequence, "the episode left the order"
        moved = {key: got.result.first[key] for key in shared if key in got.result.first}
        assert moved, "RP-2's episode shares words with later episodes"
        assert episode not in moved.values(), "a word still first met in the watched episode"

        from app.services import moves as M
        fresh = M.Numbers(M.store_opener(_language()), _language(), check=M.plan_check(_language(), host._settings()))
        fresh._load()
        assert fresh.why() is None, "a window opened after the mark follows the order (never faded)"

        # its next episode is the one the Generate finds: the run the stone asked for, on the marked library
        _generate(root)
        truth = _connect(store)
        assert truth.verdict is None, truth.verdict
        agree = {key: item for key, item in moved.items() if key in truth.result.first}
        assert agree and all(truth.result.first[key] == item for key, item in agree.items()),             {key: (item, truth.result.first[key]) for key, item in agree.items() if truth.result.first[key] != item}


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_un_marking_before_the_generate_brings_the_cards_back_at_once_after_it_waits_for_one(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    asked = []
    host, _lines = _host(generate=asked.append)
    with _patched(fake):
        host._job("catch-up")
        store.set_watched([episode])
        _job(fake, host)
        assert _suspended(fake, own) == set(own)

        asked.clear()
        store.set_watched([episode], False)            # the mis-click's Undo, before the Generate ran
        assert _verdict(host, store) is None, "the library is the plan's again"
        assert _job(fake, host), "un-marking wrote nothing"
        assert not _suspended(fake, own), "the cards come back at once"
        assert asked == []

        store.set_watched([episode])
        _job(fake, host)
        _generate(root)                                # the Generate the mark asked for (the keeper's)
        _job(fake, host, "generate")
        assert _suspended(fake, own) == set(own)
        asked.clear()
        store.set_watched([episode], False)            # after it: its plan has no line for the episode
        assert _verdict(host, store)[0] == "generate-first"
        assert _job(fake, host) == [], "un-marking after the Generate re-ordered before its own Generate"
        assert _suspended(fake, own) == set(own)
        _generate(root)
        _job(fake, host, "generate")
    assert not _suspended(fake, own), "after that Generate the cards are back"


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_with_keep_studying_watched_episodes_on_a_stone_moves_nothing(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    store.set_library_options(keep_watched=True)       # Keep studying: a mark counts on
    _generate(root)
    asked = []
    host, _lines = _host(generate=asked.append)
    with _patched(fake):
        host._job("catch-up")
        asked.clear()
        store.set_watched([episode])
        assert _verdict(host, store) is None, "nothing that counts moved"
        assert _job(fake, host) == [] and asked == []
        assert not _suspended(fake, own)
        assert _connect(store).generate == "no"


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_the_background_generate_after_a_stone_brings_anki_to_its_own_order(lib, monkeypatch):
    # why: the re-plan can't see the list's edge (a word crossing the cut-off: the cut-off is a share of the library's
    # tokens); the Generate the stone asked for can, and its re-order must leave Anki exactly at the Generate's order
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    host, _lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        store.set_watched([episode])
        assert _job(fake, host)
        _generate(root)
        _job(fake, host, "generate")
        assert _verdict(host, store) is None, "the Generate's plan is the library's"
        assert _job(fake, host) == [], "after the Generate's re-order, Anki holds the Generate's own order"
    assert _suspended(fake, own) == set(own)
