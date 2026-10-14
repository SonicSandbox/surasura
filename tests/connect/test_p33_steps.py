"""P3.3 rows 3.3.2–3.3.4: Connect's real steps on the fast re-plan — `Steps.prepare` Generates only when the plan
can't serve the library, the pick ranks by the re-plan, and the ordering step re-orders Anki from the engine's rows
with your 順 actions (HY-6) and records the order planned.

On a real library (tests/plan_file_cases.py's RP-2 Japanese library, as `tests/test_replan_preview.py`'s `lib`
builds it: generated once, its store as the Generate left it) and the Junban suite's fake AnkiConnect
(`ModCollection`: real state, every write checked). What these prove:

  - a burst of moves → `prepare` runs no Generate and starts no analyzer child; a move mid-run is re-planned before
    the next pick;
  - the pick after a move ranks the episode's words as the engine does (never the last Generate's list), and a
    background Generate holding `results` doesn't hold back a pick that has a plan;
  - the ordering step after a move leaves Anki where the engine's rows put it (no `list-stale` skip), records
    `record_planned`; with `junban_auto_actions` on and Connect on, it tags, flags and suspends (suspend last) — off,
    positions and the unattended suspend only; `junban --auto` itself stays positions only.

What a wrong answer would cost: every move a full Generate holding the cards back (K78); cards made in the last
Generate's order after you moved an episode up; Anki left unordered after a move ("the list is out of date"); your
own 順 actions never applied while Connect is on (HY-6), or applied by `junban --auto` behind a program's back.
"""
import os
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("modules.junban")

from app import locks, settings_manager  # noqa: E402
from app.cli import verbs  # noqa: E402
from app.connect import anki_session, runner  # noqa: E402
from modules.junban import reposition, spaced  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402
from tests.test_replan_preview import (OFF, _acting_deck, _deck, _ids, _junban_settings, _kinds,  # noqa: E402,F401
                                       _move_later_to_top, _settings_file, _word_cards, lib)


def _steps():
    loaded = dict(settings_manager.load_settings())
    return runner.Steps(loaded)


def _prepared(monkeypatch, steps, calls):
    """`prepare`'s Anki-facing steps replaced (the session, known-sync, the shelf), Generate and its child spied."""
    monkeypatch.setattr(anki_session, "begin", lambda url, loaded: None)
    monkeypatch.setattr(verbs, "known_sync", lambda ns: calls.append("known_sync"))
    monkeypatch.setattr(verbs, "generate", lambda ns: calls.append("generate"))

    def no_child(argv):
        calls.append("analyzer child")
        raise AssertionError("no analyzer child in Connect's loop for a move")
    monkeypatch.setattr(verbs, "child_command", no_child)
    steps.notes_gone = lambda lang: calls.append("notes_gone")
    steps.shelf_session = lambda lang, ledger: calls.append("shelf_session")


# --------------------------------------------------------------------------------------------------------------- #
# 3.3.2 prepare: no Generate for moves
# --------------------------------------------------------------------------------------------------------------- #

def test_a_burst_of_moves_runs_no_generate_and_no_analyzer_child_in_prepare(lib, monkeypatch):
    root, store = lib
    from tests.connect.test_p33_replan import _burst
    _burst(store)
    steps, calls = _steps(), []
    _prepared(monkeypatch, steps, calls)
    steps.prepare("ja", None)
    assert calls == ["known_sync", "notes_gone", "shelf_session"], calls
    got = steps.current("ja")
    assert got.generate == "no" and got.result is not None, got.reason
    assert steps._after == {}, "nothing owed after mining for a move"


def test_a_move_mid_run_is_re_planned_before_the_next_pick(lib, monkeypatch):
    root, store = lib
    steps, calls = _steps(), []
    _prepared(monkeypatch, steps, calls)
    steps.prepare("ja", None)
    first = steps.current("ja")
    assert steps.current("ja") is first, "nothing moved: the kept plan, no new read"
    _move_later_to_top(store)
    again = steps.current("ja")
    assert again is not first and again.listed != first.listed and again.generate == "no"
    assert "generate" not in calls


def test_a_new_file_still_generates_first(lib, monkeypatch):
    # C3: a new episode's words exist only after a Generate (E1.1 04 §4 row 2): today's path
    root, store = lib
    from app import library_store
    from app.path_utils import get_data_path
    with open(os.path.join(get_data_path("ja"), "GoalContent", "new_episode.txt"), "w", encoding="utf-8") as f:
        f.write("新しい話が始まった。今日は学校で友達に会った。\n")
    library_store.sync_for_window(store)
    steps, calls = _steps(), []
    _prepared(monkeypatch, steps, calls)
    steps.prepare("ja", None)
    assert calls == ["known_sync", "generate", "notes_gone", "shelf_session"], calls


# --------------------------------------------------------------------------------------------------------------- #
# 3.3.3 the pick reads the current plan
# --------------------------------------------------------------------------------------------------------------- #

def _episode(store, name):
    for tier in ("now", "soon", "goal"):
        for item in store.ids(tier):
            if str((store.item(item) or {}).get("rel_path") or "").replace("\\", "/").endswith("/" + name):
                return item
    raise AssertionError(name)


def _picked_keys(steps, item):
    out = steps.pick("ja", {"id": 8, "item_id": item}, None)
    return [(w["word"], w["reading"]) for w in out["words"]]


def test_after_a_move_the_pick_ranks_the_episodes_words_as_the_engine_does(lib):
    # why: the pick sends Anki Miner the episode's words best first; after a move the last Generate's ranks are the
    # old order's — the words you meet next would be mined behind words you meet later
    root, store = lib
    episode = _episode(store, "phrases_sample.srt")
    stale = verbs._listed(SimpleNamespace(wait=5.0), "ja")
    store.move([episode], "now", before_id=store.ids("now")[0])         # Soon's subtitle to the top of NOW
    steps = _steps()
    got = steps.current("ja")
    assert got.generate == "no", got.reason
    keys = _picked_keys(steps, episode)
    assert len(keys) > 5, keys
    ranks = [got.listed[k] for k in keys]
    assert ranks == sorted(ranks), "the engine's order: the re-plan's ranks"
    assert [stale[k] for k in keys] != sorted(stale[k] for k in keys), "not the last Generate's order"


def test_a_background_generate_holding_results_never_stalls_a_pick_that_has_a_plan(lib):
    root, store = lib
    episode = _episode(store, "phrases_sample.srt")
    steps = _steps()
    steps.current("ja")
    with locks.take("results", "a Generate (the test's)"):
        started = time.monotonic()
        keys = _picked_keys(steps, episode)
        took = time.monotonic() - started
    assert keys and took < runner.WAIT_S, f"the pick waited {took:.1f} s for the list"


def test_the_shelfs_ranks_are_the_re_plans_too(lib):
    root, store = lib
    _move_later_to_top(store)
    steps = _steps()
    assert steps._list_order("ja") == steps.current("ja").listed


# --------------------------------------------------------------------------------------------------------------- #
# 3.3.4 the ordering step from the engine, HY-6
# --------------------------------------------------------------------------------------------------------------- #

@pytest.fixture
def no_session(monkeypatch):
    """Connect's session sync is P2.3's (its own suites): here the step's re-order alone."""
    monkeypatch.setattr(verbs, "_session", lambda loaded: None)


def test_after_a_move_the_step_orders_anki_from_the_engine_and_records_the_plan(lib, no_session):
    root, store = lib
    _settings_file(root, connect_enabled=True)
    fake = _deck(root)
    with _patched(fake):
        _move_later_to_top(store)
        steps = _steps()
        got = steps.current("ja")
        assert got.generate == "no"
        steps.order("ja", {"id": 8, "item_id": 1})
        writes, stats = reposition.dry_run(_junban_settings(), job=spaced.Job(automatic=True, rows=got.rows("content")))
    assert fake.writes, "the step re-ordered Anki"
    assert not writes, "Anki holds the engine's order for the store's order"
    versions = store.versions()
    assert versions["planned_order_version"] == versions["order_version"] == got.versions["order_version"]


def _connect_actions(root, store, monkeypatch, **over):
    from modules.junban import connect
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", True)
    _settings_file(root, connect_enabled=True, junban_later_tag=True, junban_later_flag=True,
                   junban_later_suspend=True, **over)
    fake = _acting_deck(root)
    off_ids = _word_cards(fake, OFF)
    with _patched(fake):
        _move_later_to_top(store)
        _steps().order("ja", {"id": 8, "item_id": 1})
    return fake, off_ids, _kinds(fake.requests, off_ids)


def test_with_your_actions_on_connects_step_tags_flags_and_suspends_after_its_positions(lib, no_session, monkeypatch):
    # HY-6 (Sonic 2026-10-13: "it just works"): Connect on no longer makes the step positions only on 3.0
    root, store = lib
    fake, off_ids, kinds = _connect_actions(root, store, monkeypatch, junban_auto_actions=True)
    last_position = max(i for i, kind in enumerate(kinds) if kind == "position")
    after = [kind for kind in kinds[last_position + 1:] if kind in ("addTags", "flag", "suspend")]
    assert after and after[-1] == "suspend" and "flag" in after and "addTags" in after, kinds
    assert sorted(card_id for card_id, _flag in fake.flag_writes) == sorted(off_ids)
    assert all(fake.cards[card_id]["queue"] == -1 for card_id in off_ids)


def test_with_your_actions_off_connects_step_writes_positions_and_the_unattended_suspend_only(lib, no_session,
                                                                                               monkeypatch):
    root, store = lib
    fake, off_ids, kinds = _connect_actions(root, store, monkeypatch, junban_auto_actions=False)
    assert "position" in kinds and fake.flag_writes == []
    assert {tag for _action, _notes, tag in fake.tag_calls} <= {"Surasura::later"}, "no Surasura tag, no flag"
    assert [ids for action, ids in fake.suspend_calls if action == "suspend"] == [sorted(off_ids)]


def test_junban_auto_itself_stays_positions_only_with_your_actions_and_connect_on(lib, no_session, monkeypatch):
    # P0.3 03: `junban --auto` and `resort` are verbs a program or you run, not the automation — positions only
    from modules.junban import connect
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", True)
    root, store = lib
    _settings_file(root, connect_enabled=True, junban_auto_actions=True, junban_later_tag=True,
                   junban_later_flag=True, junban_later_suspend=False)
    fake = _acting_deck(root)
    monkeypatch.setattr("app.analyzer.journey_is_current", lambda argv, lang: True)
    with _patched(fake):
        out = verbs.junban(SimpleNamespace(lang="ja", wait=0.0, auto=True, dry_run=False))
    assert out.get("moves", 0) > 0 and not out.get("skipped"), out
    assert fake.flag_writes == [] and fake.tag_calls == [] and fake.suspend_calls == []
