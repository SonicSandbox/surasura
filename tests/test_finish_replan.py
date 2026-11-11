"""Haya-FN (Sonic 2026-11-09, the 3.0.1 speed items; provisional choices 27, 28, 118): a finish moves Anki's order at
once, by the watched mark's rule — never a second one. A drag to Finished (or a title finishing by itself) sets its
counted files aside with the digests their plan lines hold, as a watched mark does (`plan_engine._only_joined`:
"files-removed" + "reference-joined"): the engine drops their uses, Anki's order follows in the host's next job, and
the Generate still runs after, quietly, for the list's edge and the journey. A title of watched episodes finished
moves only the set-aside files' ranks as sentence sources (F7's "finished"): nothing the order reads, so it re-plans
at once too.

On RP-2's libraries (tests/plan_file_cases.py: real Japanese and Chinese text across NOW, Soon and 6+ Months),
generated per test, your 順 actions on (tag + suspend, as Sonic runs them) and a fake AnkiConnect holding a card for
every listed word (and for the words met only in the finished episode). What these prove, ja and zh:

  - a drag to Finished: in the host's next job its own words' cards step back and the rest re-order, by the watched
    mark's rule (the same verdict; Current then fills from Soon as the store keeps it, which a watched mark — still in
    Current — doesn't); Connect reads the same re-plan ("after"), and the window's numbers follow a fresh load. The
    order Anki gets at once is the Generate's for every card but the list's edge, as for a watched mark: the Generate
    after moves only the cards whose word it moves in the list — a word the smaller library drops under the cut-off
    (parked), or a neighbour whose tie it orders the other way — and then nothing;
  - a title finishing by itself (its last episode's Done, then the finish, no Generate between): at once, never a
    Generate first; a title of watched episodes finished after their Generate: at once, and exactly the Generate's
    order (no file left the counted ones);
  - Undo before the Generate: the library is the plan's again — the cards back at once; after it, the new plan has no
    line for a set-aside file, so a Generate first (as a watched mark's un-marking, Haya-W's S2);
  - Anki closed: the finish's job writes nothing and says so (the host's line ends the press), the order still owed;
  - a file the plan never counted (edited since), finished: still a Generate first.

What a wrong answer would cost a learner: a finished show's cards at the front of Anki's queue for a minute or two
(the whole Generate at 20k files), or an at-once order the Generate then moves beyond the list's edge.
"""
import os

import pytest

pytest.importorskip("modules.junban")

from app import replan_preview  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402
from tests.test_replan_preview import _generate, _host, _language, lib  # noqa: E402,F401
from tests.test_replan_preview_watched import _acting, _job, _suspended  # noqa: E402
from tests.test_watched_replan import _connect, _verdict  # noqa: E402

FINISH = ("replan-now", ("files-removed", "reference-joined"))


def _anki(fake):
    """Where every card stands: {card id: (due, queue, tags)}."""
    return {card_id: (card["due"], card["queue"], tuple(sorted(fake.notes[card["note"]].get("tags") or ())))
            for card_id, card in fake.cards.items()}


def _placed(fake):
    """Anki's new-card order as the learner meets it: (the cards in the queue, in order; the cards parked) — Junban
    spaces the positions it writes anew each time, so the order is compared, never the numbers."""
    cards = fake.cards.values()
    queued = tuple(c["cardId"] for c in sorted(cards, key=lambda c: (c["due"], c["cardId"])) if c["queue"] != -1)
    return queued, frozenset(c["cardId"] for c in cards if c["queue"] == -1)


def _word_of(fake):
    return {card_id: next(iter(fake.notes[card["note"]]["fields"].values()))["value"]
            for card_id, card in fake.cards.items()}


def _list(result):
    """The progressive list's words (Junban's content order), each as a card carries it."""
    out = []
    for row in result.progressive:
        word, orth = (row.get("Word") or "").strip(), (row.get("Orth") or "").strip()
        key = orth or word
        out.append(word if len(key) == 1 and key != word else key)
    return out


def _edge(at_once, truth):
    """The words the Generate places otherwise than the re-plan did: gone from (or new to) its list, or moved among the
    words both lists hold — those outside their longest common order (the fewest words that must move; one word moved
    never marks the words it passed)."""
    kept = set(at_once) & set(truth)
    mine, theirs = [w for w in at_once if w in kept], [w for w in truth if w in kept]
    n = len(theirs)
    best = [[0] * (n + 1) for _ in range(len(mine) + 1)]
    for i in range(len(mine) - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            best[i][j] = best[i + 1][j + 1] + 1 if mine[i] == theirs[j] else max(best[i + 1][j], best[i][j + 1])
    still, i, j = set(), 0, 0
    while i < len(mine) and j < n:
        if mine[i] == theirs[j]:
            still.add(mine[i])
            i, j = i + 1, j + 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return (set(at_once) ^ set(truth)) | (kept - still)


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_a_finish_moves_anki_at_once_and_the_generate_after_moves_only_the_lists_edge(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    asked = []
    host, _lines = _host(generate=asked.append)
    with _patched(fake):
        host._job("catch-up")                          # the ladder laid, the plan recorded: nothing owed
        assert not _suspended(fake, own)
        before = _connect(store)
        shared = [key for key, item in before.result.first.items() if item == episode]
        asked.clear()

        store.finish([episode])                        # a drag to Finished
        assert _verdict(host, store) == FINISH
        assert _job(fake, host), "the finish's job wrote nothing: Anki waits for the Generate"
        assert _suspended(fake, own) == set(own), "the finished show's own words' cards step back at once"
        assert asked == ["replan-now: files-removed,reference-joined"], "the Generate still runs after, quietly"
        at_once = _placed(fake)

        got = _connect(store)
        assert got.verdict == FINISH and got.generate == "after" and got.result is not None, (got.verdict, got.reason)
        assert episode not in got.result.sequence, "the finished episode left the order"
        moved = {key: got.result.first[key] for key in shared if key in got.result.first}
        assert moved and episode not in moved.values(), "a word still first met in the finished episode"

        from app.services import moves as M
        fresh = M.Numbers(M.store_opener(_language()), _language(), check=M.plan_check(_language(), host._settings()))
        fresh._load()
        assert fresh.why() is None, "a window opened after the finish follows the order (never faded)"

        # the Generate the finish asked for, then its re-order: only the list's edge moves, then nothing
        _generate(root)
        _job(fake, host, "generate")
        truth = _connect(store)
        assert truth.verdict is None, "the Generate's plan is the library's"
        assert _job(fake, host) == [], "after the Generate's re-order, Anki holds the Generate's own order"
        words = _word_of(fake)
        after = _placed(fake)
        differ = _edge([words[c] for c in at_once[0]], [words[c] for c in after[0]])
        differ |= {words[c] for c in at_once[1] ^ after[1]}
        edge = _edge(_list(got.result), _list(truth.result))
        assert differ <= edge, f"the Generate moved cards the list kept in place: {sorted(differ - edge)}"
        agree = {key: item for key, item in moved.items() if key in truth.result.first}
        assert agree and all(truth.result.first[key] == item for key, item in agree.items())
    assert _suspended(fake, own) == set(own)


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_a_title_finishing_by_itself_moves_anki_at_once(lib, monkeypatch):
    # why: L6.3's finish by itself is two commands — the last episode's Done (a watched mark), then the finish of the
    # whole title (`drag.when_done` → `DragMoves.to_finished`); the second must not turn the first's at-once re-plan
    # into a wait for the Generate
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    host, _lines = _host(generate=lambda reason: None)
    title = [episode, next(item for item in store.ids("now") if item != episode)]
    with _patched(fake):
        host._job("catch-up")
        store.set_watched([title[1]])                  # an earlier episode, watched and Generated
        _job(fake, host)
        _generate(root)
        _job(fake, host, "generate")

        store.set_watched([episode])                   # the last episode's Done …
        store.finish(title)                            # … and the title finishes by itself
        verdict = _verdict(host, store)
        assert verdict[0] == "replan-now" and "reference-joined" in verdict[1], verdict
        assert _job(fake, host), "the finish by itself waited for the Generate"
        assert _suspended(fake, own) == set(own)
        _generate(root)
        _job(fake, host, "generate")
        assert _job(fake, host) == [], "after the Generate's re-order, Anki holds the Generate's own order"
    assert _suspended(fake, own) == set(own)


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_a_title_of_watched_episodes_finished_after_their_generate_never_waits_for_one(lib, monkeypatch):
    # why: every episode already set aside as watched, the finish moves only their ranks as sentence sources (F7's
    # "finished" part, newest finished first) and the order around them (Current fills from Soon): nothing the plan
    # can't re-plan exactly — the press must not wait a whole Generate, and the Generate after moves no card
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    title = [episode] + [item for item in store.ids("now") if item != episode][:2]
    host, _lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        store.set_watched(title)
        _job(fake, host)
        _generate(root)
        _job(fake, host, "generate")

        store.finish(title)
        verdict = _verdict(host, store)
        assert verdict == ("replan-now", ("finished",)), verdict
        _job(fake, host)
        versions = store.versions()
        assert versions["planned_order_version"] >= versions["order_version"], "the press still owed a Generate"
        at_once = _placed(fake)
        _generate(root)
        _job(fake, host, "generate")
        assert _placed(fake) == at_once, "the order Anki got at once is not the Generate's"
    assert _suspended(fake, own) == set(own)


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_undo_of_a_finish_before_the_generate_brings_the_cards_back_at_once_after_it_waits_for_one(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    asked = []
    host, _lines = _host(generate=asked.append)
    with _patched(fake):
        host._job("catch-up")
        start = _placed(fake)
        change = store.finish([episode])
        _job(fake, host)
        assert _suspended(fake, own) == set(own)

        asked.clear()
        store.undo(change)                             # the toast's Undo, before the Generate ran
        assert _verdict(host, store) is None, "the library is the plan's again"
        assert _job(fake, host), "the Undo wrote nothing"
        assert not _suspended(fake, own), "the cards come back at once"
        assert _placed(fake) == start, "every card back where it stood"
        assert asked == []

        change = store.finish([episode])
        _job(fake, host)
        _generate(root)                                # the Generate the finish asked for (the keeper's)
        _job(fake, host, "generate")
        store.undo(change)                             # after it: its plan has no line for the episode
        assert _verdict(host, store)[0] == "generate-first"
        assert _job(fake, host) == [], "the Undo after the Generate re-ordered before its own Generate"
        assert _suspended(fake, own) == set(own)
        _generate(root)
        _job(fake, host, "generate")
    assert not _suspended(fake, own), "after that Generate the cards are back"


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_a_finish_with_anki_closed_writes_nothing_says_so_and_stays_owed(lib, monkeypatch):
    root, store = lib
    episode, own, fake = _acting(root, store, monkeypatch)
    host, lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        store.finish([episode])
        fake.offline = True
        host._job("move")
        assert lines[-1] == replan_preview.CLOSED and isinstance(lines[-1], replan_preview.GivesUp), lines[-1:]
        assert not _suspended(fake, own)
        versions = store.versions()
        assert versions["planned_order_version"] < versions["order_version"], "still owed"
        fake.offline = False
        assert _job(fake, host), "Anki back: the owed re-order writes"
    assert _suspended(fake, own) == set(own)


@pytest.mark.parametrize("lib", ["ja", "zh"], indirect=True)
def test_finishing_a_file_the_plan_never_counted_still_generates_first(lib):
    # why: its text is new to the name tables' evidence — only the Generate can say what it changes
    root, store = lib
    from app.path_utils import get_data_path
    episode = store.ids("now")[0]
    path = os.path.join(get_data_path(_language()), *store.item(episode)["rel_path"].split("/"))
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + ("今日はいい天気ですね。" if _language() == "ja" else "今天天气很好。") + "\n")
    store.finish([episode])
    host, _lines = _host()
    assert _verdict(host, store) == ("generate-first", "reference")
