"""Connect's two locks (SORT-BAR, 3.0.19): `connect` is its one-instance lock, held for the whole run (a kick starts no
second Connect, an update waits for its process, the profile move and Start over refuse while it lives);
`connect-mining` (`kick.MINING`) means "mining now" — held by each look while it reads the inbox and works its jobs,
let go before the pause between looks and at the run's end. *Sort again* (`start_fresh`) and both Put backs take
`connect-mining` for their whole run, never `connect`.

What a wrong answer would cost a learner:
  * a laptop on battery, Connect waiting all session for the plug: Sort again and Put back refused all session, in
    words that say Connect is making cards when it makes none (Send report, 3.0.18);
  * a Sort again that runs while Connect really mines: cards made for an order that is being set aside;
  * a look that starts while a Sort again is half-way: Connect reading a library that is neither old nor new;
  * a second Connect started by a kick while the first only waits (two writers into one Anki).

Against `FakeSteps` (real Japanese words, never a live Anki) and a real store in the test's own root with real
Japanese and Chinese subtitles (`test_library_reset`'s world); the 2-minute pause is stood in for.
"""
import pytest

from app import library_store as ls
from app import locks
from app.connect import kick, runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps
from tests.test_library_put_back import _rows, _sorted_again
from tests.test_library_reset import _fresh_module_state, _world  # noqa: F401  (each test a new run of the app)
from tests.test_library_store_support import LANGUAGES


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def test_the_store_and_connect_name_one_mining_lock():
    # the store can't import Connect (the layering): the name is written twice, and must stay one lock
    assert ls.CONNECT_MINING == kick.MINING != kick.LOCK


def _steps(tmp_path, language, **plan):
    return FakeSteps(str(tmp_path), dict({"line": {language: [1]}, "queue": {language: [1]}}, **plan))


def _pauses(monkeypatch, *answers):
    """Connect's pause between looks stood in for: the n-th pause calls `answers[n]` (-> True: look again, False: the
    pause cancelled, the run ends); what each saw of the two locks is recorded."""
    seen = []

    def pause(seconds, sleep, cancel, staged):
        seen.append({"mining": locks.in_use(kick.MINING, looks=1, gap=0.0), "instance": kick.running()})
        return answers[len(seen) - 1]() if len(seen) <= len(answers) else False
    monkeypatch.setattr(runner, "_pause", pause)
    return seen


def _as_connects_loop(language, steps, ledger, looks=None):
    """`connect_verbs._loop`'s shape: the one-instance lock for the whole run, the loop under it."""
    with locks.take(kick.LOCK, "Connect"):
        return runner.run({}, [language], steps=steps, ledger=ledger, looks=looks)


@pytest.mark.parametrize("language", LANGUAGES)
def test_sort_again_runs_while_connect_waits_on_battery_and_connect_looks_again_after(tmp_path, ledger, monkeypatch,
                                                                                    language):
    store, _data, _uf, _src, _root = _world(language)
    before = store.ids("now")
    assert before
    answers = []
    seen = _pauses(monkeypatch, lambda: answers.append(ls.start_fresh(store)) or True)
    steps = _steps(tmp_path, language, blocked=runner.ON_BATTERY)
    try:
        summary = _as_connects_loop(language, steps, ledger)
        assert answers and answers[0]["backup"], "Sort again ran in the pause: Connect only waited on battery"
        assert store.ids("now") == [], "the old order set aside: the library starts fresh"
        assert summary["looks"] == 2, "Connect looked again after the Sort again (it sees the new order)"
        assert seen[0] == {"mining": False, "instance": True}, "waiting: mining let go, still the one Connect"
        assert summary["languages"][language]["waiting"] == {1: runner.ON_BATTERY}
        assert not locks.in_use(kick.MINING, looks=1, gap=0.0), "the run's end lets go of it"
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_put_back_runs_while_connect_waits_on_battery(tmp_path, ledger, monkeypatch, language):
    store, _data, _uf, backup, before = _sorted_again(language)
    put = []
    _pauses(monkeypatch, lambda: put.append(ls.put_back_library(store, backup)) or True)
    try:
        _as_connects_loop(language, _steps(tmp_path, language, blocked=runner.ON_BATTERY), ledger)
        assert put and put[0]["put_back"] == backup, "Put back ran while Connect only waited"
        assert _rows(store) == before[0], "the library as it was before the Sort again"
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_while_a_look_mines_sort_again_and_put_back_are_refused_in_words_that_say_so(tmp_path, ledger, monkeypatch,
                                                                                   language):
    monkeypatch.setattr(ls, "RESET_WAIT", 0.0)        # no wait: the look mining on this thread ends after it
    store, _data, _uf, backup, _before = _sorted_again(language)
    steps = _steps(tmp_path, language)
    refused = []
    mine = steps.mine

    def mining(*args):
        rows = _rows(store)
        for press in (lambda: ls.start_fresh(store), lambda: ls.put_back_library(store, backup)):
            with pytest.raises(ls.ResetRefused) as e:
                press()
            refused.append(e.value.reason)
        assert _rows(store) == rows, "a refusal changes nothing"
        return mine(*args)
    steps.mine = mining
    try:
        _as_connects_loop(language, steps, ledger, looks=1)
        assert refused == [ls.RESET_CONNECT, ls.RESET_CONNECT]
        assert "making cards" in ls.RESET_CONNECT
        assert any(e[0] == "mine" for e in steps.log), "the job was mined"
        assert ls.start_fresh(store)["backup"], "the look over: Sort again runs"
    finally:
        store.close()


def test_a_look_waits_while_a_sort_again_holds_the_mining_lock_and_goes_once_it_ends(tmp_path, ledger, monkeypatch):
    held = locks.take(kick.MINING, "Sorting your library again", owner=object())     # start_fresh's hold
    looked = []

    def sort_ends():
        looked.append([e[0] for e in steps.log])
        held.release()
        return True
    seen = _pauses(monkeypatch, sort_ends)
    steps = _steps(tmp_path, "ja")
    try:
        summary = _as_connects_loop("ja", steps, ledger, looks=1)
    finally:
        held.release()
    assert looked == [["lower"]], "nothing of the look ran while the Sort again held it"
    assert seen[0]["mining"] and seen[0]["instance"]
    assert any(e[0] == "mine" for e in steps.log) and summary["languages"]["ja"]["done"] == [1]
    assert summary["looks"] == 1, "the wait for the Sort again is no look"


@pytest.mark.parametrize("plan", [{"staged": True}, {"switched_off": True}, {}])
def test_the_run_lets_go_of_the_mining_lock_however_it_ends(tmp_path, ledger, plan):
    # stopped mid-look (an update staged, switched off) or ended with nothing left: never a hold that outlives the run
    steps = _steps(tmp_path, "zh", **plan)
    _as_connects_loop("zh", steps, ledger, looks=1)
    assert not locks.in_use(kick.MINING, looks=1, gap=0.0)


def test_a_look_holds_the_mining_lock_while_it_works_and_never_in_its_pause(tmp_path, ledger, monkeypatch):
    seen = _pauses(monkeypatch, lambda: True, lambda: False)
    steps = _steps(tmp_path, "ja", blocked=runner.ON_BATTERY)
    during = []
    blocked = steps.blocked
    steps.blocked = lambda lang: during.append(locks.held_here(kick.MINING)) or blocked(lang)
    _as_connects_loop("ja", steps, ledger)
    assert during and all(during), "the look holds it while it works"
    assert [s["mining"] for s in seen] == [False, False], "every pause lets it go"


@pytest.mark.parametrize("language", LANGUAGES)
def test_sort_again_holds_the_mining_lock_at_every_step_so_no_look_starts_half_way(language):
    # a check alone (`in_use`) would let a look begin while the old order is being set aside
    store, _data, _uf, _src, _root = _world(language)
    seen = []
    try:
        ls.start_fresh(store, _step=lambda name: seen.append((name, locks.held_in_process(ls.CONNECT_MINING))))
    finally:
        store.close()
    assert seen and all(held for _name, held in seen), seen
    assert not locks.in_use(ls.CONNECT_MINING, looks=1, gap=0.0), "let go at its end"
