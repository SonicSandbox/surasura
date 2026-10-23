"""W-1: Connect reads a watched mark as the window's re-order host does — the cards follow the Generate the mark starts,
in both directions (`replan.current`: the set-aside files are the run signature's "reference" part, and
`plan_engine.check`, the one classifier, sends a part it can't re-plan to a Generate first).

On RP-2's libraries (tests/plan_file_cases.py: real Japanese and Chinese text across NOW, Soon and 6+ Months),
generated per test:

  - a stone → Generate "first", no re-plan (never mined or ordered from a plan that still counts the episode, nor
    from one that has dropped its words before the Generate); after the Generate, nothing owed;
  - its un-marking → the same (never "new files" mined around the Generate);
  - *Keep studying watched episodes* flipped either way → the same;
  - a stone and a Finished drag together → Generate "first" (the stricter wins);
  - a Finished drag alone → today's re-plan now, Generate "after" (unchanged); so is a show finished with a watched
    episode in it, or the watched episode alone: an episode that only leaves the set-aside files moves nothing ahead.

What a wrong answer would cost: Connect ordering Anki (and suspending) from a list the mark already changed while the
window waits for the Generate — the two disagreeing about the same cards.
"""
import pytest

from tests.connect.test_replan_current import _current, _generate, _library

FIRST = ("generate-first", "reference")


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


def test_a_stone_and_its_un_marking_each_generate_first(lib):
    root, store, case, language = lib
    episode = store.ids("now")[0]
    store.set_watched([episode])
    _waits(store, language)
    _generate(root, case, language)
    assert _current(store, language).verdict is None, "the Generate's plan is the library's"
    store.set_watched([episode], False)
    _waits(store, language)
    _generate(root, case, language)
    assert _current(store, language).verdict is None


def test_keep_studying_watched_episodes_flipped_either_way_generates_first(lib):
    root, store, case, language = lib
    store.set_watched([store.ids("now")[0]])
    _generate(root, case, language)
    store.set_library_options(keep_watched=True)
    _waits(store, language)
    _generate(root, case, language)
    store.set_library_options(keep_watched=False)
    _waits(store, language)


def test_a_stone_with_a_finished_drag_generates_first(lib):
    _root, store, _case, language = lib
    now = store.ids("now")
    store.set_watched([now[0]])
    store.finish([now[1]])
    _waits(store, language)


def test_a_finished_drag_alone_still_re_plans_now(lib):
    # why: a tier move keeps today's fast re-plan exactly — only a mark waits for the Generate
    _root, store, _case, language = lib
    store.finish([store.ids("now")[0]])
    got = _current(store, language)
    assert got.verdict == ("replan-now", ("files-removed",)) and got.generate == "after", got.verdict
    assert got.result is not None


@pytest.mark.parametrize("finished", ["the show", "its watched episode"])
def test_finishing_a_watched_episode_after_its_generate_still_re_plans_now(lib, finished):
    # why: stone, Generate, then Finish is the usual order; the watched episode only leaves the set-aside files (it
    # counted for nothing ahead already), so the Finished drag keeps today's fast re-plan
    root, store, case, language = lib
    now = store.ids("now")
    store.set_watched([now[0]])
    _generate(root, case, language)
    store.finish([now[0], now[1]] if finished == "the show" else [now[0]])
    got = _current(store, language)
    want = ("files-removed", "reference-removed") if finished == "the show" else ("reference-removed",)
    assert got.verdict == ("replan-now", want) and got.generate == "after", got.verdict
    assert got.result is not None
