"""W-1: Connect reads a watched mark as the window's re-order host does (`replan.current`: the set-aside files are the
run signature's "reference" part, and `plan_engine.check` is the one classifier) — since Haya-W (2026-11-06) a stone
re-plans at once, as the host does: the episode leaves the counted files with the digest its plan line holds; since
Haya-FN (2026-11-09) a finish does too, by the same rule.

On RP-2's libraries (tests/plan_file_cases.py: real Japanese and Chinese text across NOW, Soon and 6+ Months),
generated per test:

  - a stone → re-plan now ("after": mined and ordered from the plan without the episode, the Generate after); after
    the Generate, nothing owed;
  - its un-marking after that Generate → Generate "first" (the new plan has no line for it: never "new files" mined
    around the Generate);
  - *Keep studying watched episodes* turned on → Generate "first" (the watched episodes come back: the plan has no
    line for them); turned off → re-plan now, as their marks would (each leaves the counted files as it was planned);
  - a stone and a Finished drag together → re-plan now (both counted files set aside, one rule);
  - a Finished drag alone → re-plan now too (W-1b: Finished is set aside, as a watched episode is; Haya-FN: by the
    watched mark's rule), its Undo before the Generate → the plan's library again, after it → Generate "first"; so is
    a show finished with a watched episode in it; the watched episode alone, finished after its Generate, moves
    nothing a run reads (it stays set aside): the plan is current;
  - Put back out of Finished after its Generate → Generate "first" (the plan has no line for it counted); its Undo, a
    finish again → re-plan now;
  - a set-aside file removed from the library → re-plan now, Generate "after" (it only leaves the set-aside files).

What a wrong answer would cost: Connect ordering Anki (and suspending) from a list the mark already changed while the
window waits for the Generate — the two disagreeing about the same cards.
"""
import os

import pytest

from tests.connect.test_replan_current import _current, _generate, _library

FIRST = ("generate-first", "reference")
SET_ASIDE = ("replan-now", ("files-removed", "reference-joined"))


@pytest.fixture(params=[("rp2-ja", "ja"), ("rp2-zh", "zh")], ids=["ja", "zh"])
def lib(request, tmp_path, monkeypatch):
    case, language = request.param
    root, store = _library(tmp_path, monkeypatch, case, language)
    yield root, store, case, language
    store.close()


def _waits(store, language):
    got = _current(store, language)
    assert got.verdict == FIRST and got.generate == "first", (got.verdict, got.generate)
    assert got.result is None and got.listed is None, "nothing mined or ordered from the plan before the Generate"


def test_a_stone_re_plans_now_and_its_un_marking_after_the_generate_generates_first(lib):
    root, store, case, language = lib
    episode = store.ids("now")[0]
    store.set_watched([episode])
    got = _current(store, language)
    assert got.verdict == SET_ASIDE and got.generate == "after", got.verdict
    assert got.result is not None and episode not in got.result.sequence, "mined and ordered without the episode"
    _generate(root, case, language)
    assert _current(store, language).verdict is None, "the Generate's plan is the library's"
    store.set_watched([episode], False)
    _waits(store, language)
    _generate(root, case, language)
    assert _current(store, language).verdict is None


def test_keep_studying_watched_episodes_turned_on_generates_first_and_turned_off_re_plans_now(lib):
    root, store, case, language = lib
    store.set_watched([store.ids("now")[0]])
    _generate(root, case, language)
    store.set_library_options(keep_watched=True)
    _waits(store, language)
    _generate(root, case, language)
    store.set_library_options(keep_watched=False)
    got = _current(store, language)
    assert got.verdict == SET_ASIDE and got.generate == "after", got.verdict


def _re_plans(store, language, *gone):
    got = _current(store, language)
    assert got.verdict == SET_ASIDE and got.generate == "after", (got.verdict, got.reason)
    assert got.result is not None and not set(gone) & set(got.result.sequence), "mined and ordered without them"


def test_a_stone_with_a_finished_drag_re_plans_now(lib):
    _root, store, _case, language = lib
    now = store.ids("now")
    store.set_watched([now[0]])
    store.finish([now[1]])
    _re_plans(store, language, now[0], now[1])


def test_a_finished_drag_alone_re_plans_now_its_undo_after_the_generate_generates_first(lib):
    # why: Finished is reference, like a watched episode (W-1b): a show dragged in joins the set-aside files with the
    # digests its plan lines hold — its text was the name tables' evidence already (counted), so nothing new joins it
    # (Haya-FN: the watched mark's rule); the Undo after the Generate brings back a file its plan has no line for
    root, store, case, language = lib
    episode = store.ids("now")[0]
    change = store.finish([episode])
    _re_plans(store, language, episode)
    store.undo(change)
    assert _current(store, language).verdict is None, "the Undo before the Generate: the plan's library again"
    change = store.finish([episode])
    _generate(root, case, language)
    assert _current(store, language).verdict is None
    store.undo(change)
    got = _current(store, language)
    assert got.verdict[0] == "generate-first" and got.generate == "first", got.verdict
    assert got.result is None


def test_put_back_out_of_finished_generates_first_and_its_undo_re_plans_now(lib):
    root, store, case, language = lib
    episode = store.ids("now")[0]
    store.finish([episode])
    _generate(root, case, language)
    change = store.put_back_finished([episode])
    got = _current(store, language)
    assert got.verdict[0] == "generate-first" and got.generate == "first" and got.result is None, got.verdict
    _generate(root, case, language)
    store.undo(change)                                  # back into Finished: a finish, the plan counts it
    _re_plans(store, language, episode)


@pytest.mark.parametrize("finished", ["the show", "its watched episode"])
def test_finishing_a_watched_episode_after_its_generate(lib, finished):
    # why: stone, Generate, then Finish is the usual order; the watched episode stays set aside in Finished (nothing a
    # run reads moves: the plan is current), while a show's counted episode joins the set-aside files (re-plan now)
    root, store, case, language = lib
    now = store.ids("now")
    store.set_watched([now[0]])
    _generate(root, case, language)
    store.finish([now[0], now[1]] if finished == "the show" else [now[0]])
    if finished == "the show":
        _re_plans(store, language, now[0], now[1])
    else:
        got = _current(store, language)
        assert got.verdict is None and got.generate == "no", got.verdict


def test_a_set_aside_file_removed_from_the_library_still_re_plans_now(lib):
    # why: a file that only leaves the set-aside files moves nothing ahead of the learner: today's fast re-plan
    root, store, case, language = lib
    episode = store.ids("now")[0]
    store.finish([episode])
    _generate(root, case, language)
    from app.path_utils import get_data_path
    from tests.test_token_store_kept import _remove
    data_dir = get_data_path(language)
    _remove(store, data_dir, episode, os.path.join(data_dir, *store.item(episode)["rel_path"].split("/")))
    got = _current(store, language)
    assert got.verdict == ("replan-now", ("reference-removed",)) and got.generate == "after", got.verdict
    assert got.result is not None
