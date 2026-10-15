"""P3.3's planted-bug pass (research/mutants JUDGED-P3.3): the real `Steps`' gaps the change's own tests missed — the
Generate after mining as an ordinary one, its failure's own words, a plan that can't be read after it, the settings
read now, the plan kept for the run, the follow-up re-order held back or failing, and `junban --auto`'s record of the
order planned failing.

What a wrong answer would cost: a full forced re-analysis after every mining run; a *Needs you* that doesn't say why
the Generate failed; a Generate that went through counted as failed (no follow-up re-order, the level look skipped);
a band you changed mid-run never seen; a re-plan (or the plan file read again) for every pick; Anki written while you
review; a run ended by one error after its cards were made.

The real `Steps` with its verbs replaced, a real ledger, and (for the kept plan) a real library (`tests/
test_replan_preview.py`'s `lib`); never a live Anki, no sleeps.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.cli.contract import CliError
from app.connect import runner
from app.connect.ledger import Ledger


def _real(monkeypatch, generate, current=None):
    steps = runner.Steps({})
    seen = []
    monkeypatch.setattr(verbs, "generate", lambda ns: (seen.append(ns), generate(ns))[1])
    steps.current = current or (lambda lang, fresh=False: SimpleNamespace(generate="no", result=None))
    return steps, seen


def test_the_generate_after_mining_is_an_ordinary_one_never_forced_or_full(monkeypatch):
    # why (P3.3 B33): a forced Generate re-analyses every file even when nothing changed — after every mining run
    steps, seen = _real(monkeypatch, lambda ns: {"ran": True})
    steps._after["ja"] = "known"
    assert steps.generate_after("ja", None) is True
    assert [(ns.lang, ns.force, ns.full) for ns in seen] == [("ja", False, False)]


def test_a_failing_generate_names_its_own_reason_in_the_needs_you(monkeypatch):
    # why (P3.3 B23): the *Needs you* carries why the Generate failed (its message), not only that it did
    def fail(ns):
        raise CliError("failed", "The analyzer stopped: 作品フォルダ「進撃の巨人」が読めません。")
    steps, _seen = _real(monkeypatch, fail)
    steps._after["ja"] = "known"
    with pytest.raises(runner.Needs) as got:
        steps.generate_after("ja", None)
    assert "作品フォルダ「進撃の巨人」が読めません" in got.value.say, got.value.say


def test_a_generate_that_went_through_counts_even_when_no_store_is_there_to_read_its_plan(monkeypatch):
    # why (P3.3 B34): the Generate's success is what counts (review H5) — a plan that can't be read after it (no
    # store: Needs) is the follow-up's to read, never a failed Generate that skips the follow-up and the level look
    def no_store(lang, fresh=False):
        raise runner.Needs("no-store", "Surasura's library can't be opened.")
    steps, _seen = _real(monkeypatch, lambda ns: {"ran": True}, current=no_store)
    steps._after["ja"] = "known"
    assert steps.generate_after("ja", None) is True


def test_the_plan_reads_settings_json_as_it_is_now_and_the_runs_own_when_it_cant_be_read(monkeypatch):
    # why (P3.3 B24 / B25): a band changed mid-run is part of the verdict; settings.json caught mid-save
    # (settings-unreadable) falls back to the run's own settings, never an error out of the plan's read
    steps = runner.Steps({"target_language": "ja", "logic": {"selection": {"band": "occasional"}}})
    monkeypatch.setattr(verbs, "settings", lambda: {"logic": {"selection": {"band": "uncommon"}}})
    assert steps._settings("zh") == {"logic": {"selection": {"band": "uncommon"}}, "target_language": "zh"}

    def unreadable():
        raise CliError("settings-unreadable", "Surasura's settings (settings.json) can't be read.")
    monkeypatch.setattr(verbs, "settings", unreadable)
    assert steps._settings("ja") == {"target_language": "ja", "logic": {"selection": {"band": "occasional"}}}


def test_the_shelf_ranks_from_the_list_as_it_is_when_the_plan_has_no_re_plan(monkeypatch):
    # why (P3.3 B35): the level raised ("after", no engine rows) — the shelf's ranks are the list's, never None (which
    # would shelve by no rank at all)
    steps = runner.Steps({})
    steps._plan_now = lambda lang: SimpleNamespace(generate="after", result=None, listed=None)
    listed = {("約束", "ヤクソク"): 0, ("勇気", "ユウキ"): 1}
    monkeypatch.setattr(verbs, "_listed", lambda args, lang: listed)
    assert steps._list_order("ja") == listed


def test_a_generate_owed_with_no_store_to_read_the_plan_from_defers_the_re_order(monkeypatch):
    # why (P3.3 B38, review H12): mined from the list as it is, the Generate after mining still owed and no plan to
    # read: the re-order waits for that Generate's follow-up — never Anki ordered from the stale list
    steps = runner.Steps({})
    steps._after["ja"] = "the level raised (occasional -> uncommon)"

    def no_store(lang, fresh=False):
        raise runner.Needs("no-store", "Surasura's library can't be opened.")
    steps.current = no_store
    called = []
    monkeypatch.setattr(verbs, "junban", lambda ns: called.append(ns) or {})
    assert steps.order("ja", {"id": 8, "item_id": 1}) == runner.DEFERRED
    assert called == []


def test_switching_to_coverage_mid_run_moves_the_settings_key(monkeypatch):
    # why (P3.3 B88): the coverage target reaches a run only through the analyzer's args (`--target-coverage`; the
    # settings part leaves `strategy` / `target_coverage` out) — switched mid-run, the verdict is read again
    from app.connect import replan
    rarity = {"target_language": "ja", "strategy": "freq", "target_coverage": 90}
    coverage = dict(rarity, strategy="coverage", target_coverage=95)
    assert replan.settings_key(rarity, "ja") == replan.settings_key(dict(rarity), "ja")
    assert replan.settings_key(rarity, "ja") != replan.settings_key(coverage, "ja")


def test_a_language_whose_plan_was_never_served_orders_from_the_list(monkeypatch):
    # why (P3.3 B90, the final adversary's #4): only a run whose own plan the engine served defers when a later read
    # can't be served — a language never served (no plan yet, another engine) orders from the list as today
    steps = runner.Steps({})
    steps.current = lambda lang, fresh=False: SimpleNamespace(generate="first", result=None, listed=None)
    called = []
    monkeypatch.setattr(verbs, "junban", lambda ns: called.append(ns.current) or {"moves": 3})
    assert steps.order("ja", {"id": 8, "item_id": 1}) is None
    assert len(called) == 1


def test_the_generate_after_minings_plan_sets_and_clears_served(monkeypatch):
    # why (P3.3 B92 / B94): the follow-up re-order asks whether the run's plan is served — the Generate after mining's
    # new plan answers it: served -> marked; one the engine can't serve -> cleared (the re-order reads the list)
    served = SimpleNamespace(generate="no", result=object(), listed={})
    unserved = SimpleNamespace(generate="first", result=None, listed=None)
    for plan, before, expect in ((served, set(), {"ja"}), (unserved, {"ja"}, set())):
        steps, _seen = _real(monkeypatch, lambda ns: {"ran": True}, current=lambda lang, fresh=False, p=plan: p)
        steps._served = set(before)
        steps._after["ja"] = "known"
        assert steps.generate_after("ja", None) is True
        assert steps._served == expect


# --------------------------------------------------------------------------------------------------------------- #
# The follow-up re-order (F11), held back or failing
# --------------------------------------------------------------------------------------------------------------- #

@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        with led.transaction():
            led.owe_resort("ja")
        yield led


def _follow_steps(blocked=None, order=None):
    return SimpleNamespace(blocked=lambda lang: blocked, order=order or (lambda lang, job: None))


def test_the_follow_up_writes_nothing_while_anki_is_closed_or_you_review(ledger):
    # why (P3.3 B12): never a write while you review or Anki is closed — the re-sort stays owed for the next look
    ordered = []
    runner._follow_up(_follow_steps(blocked="You're reviewing in Anki.", order=lambda lang, job: ordered.append(lang)),
                      "ja", ledger)
    assert ordered == [], "no follow-up re-order while blocked"
    assert ledger.resort_owed("ja") is not None


def test_any_error_in_the_follow_up_never_ends_the_run_and_leaves_the_re_sort_owed(ledger):
    # why (P3.3 B14, R15): mining is done; a fault in the follow-up re-order is logged, never a run-ending error
    def order(lang, job):
        raise RuntimeError("Junban's rows couldn't be built")
    runner._follow_up(_follow_steps(order=order), "ja", ledger)
    assert ledger.resort_owed("ja") is not None


# --------------------------------------------------------------------------------------------------------------- #
# `_junban_auto`'s record of the order planned, and its after-write look
# --------------------------------------------------------------------------------------------------------------- #

def test_a_store_that_cant_record_the_order_planned_is_only_logged(monkeypatch):
    # why (P3.3 B56 / Z11): the order is already in Anki — a store that can't be written now (database locked) never
    # turns a clean run into a failure; the window's host re-orders once more, never wrongly
    from app.connect import library

    def locked(lang, role="connect"):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(library, "open_store", locked)
    assert verbs._record_planned("ja", {"order_version": 4, "pins_version": 1}) is None


def test_a_plan_key_that_cant_be_read_after_the_write_counts_as_moved(monkeypatch):
    # why (P3.3 B86): unsure whether the plan moved during the write -> ordered once more / deferred, never paid
    from app.connect import replan

    def broken(store, versions=None):
        raise OSError("the plan file can't be read")
    monkeypatch.setattr(replan, "key", broken)
    current = SimpleNamespace(key=(4, 1, "e1", (1, 2), "stamp"))
    assert verbs._plan_moved(current, {"order_version": 4, "pins_version": 1, "epoch": "e1"}) is True
