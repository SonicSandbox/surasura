"""P3.3's planted-bug pass (research/mutants JUDGED-P3.3): the re-plan's gaps the change's own tests missed — the plan
kept for the run (no re-plan per pick, the plan file not loaded again for a move), settings.json changing while the
level look reads it, and settings that can't be signed.

What a wrong answer would cost (S19, "update only what changed"): every pick and re-order paying a re-plan, and every
move a reload of the whole plan file; a band guessed from a settings.json that changed mid-read (cards made from the
wrong list); a plan read failing on a settings dict it couldn't sign instead of reading again later.

On a real library (tests/plan_file_cases.py's RP-2 Japanese library, generated once: `test_replan_current`'s `lib`);
never a live Anki.
"""
import os
from types import SimpleNamespace

from app import analyzer, plan_engine, replan_preview, settings_manager
from app.connect import replan, runner
from tests.connect.test_replan_current import (_current, _generate, _loaded, _move_later_to_top,  # noqa: F401
                                               _settings_file, lib)


def _steps():
    return runner.Steps(dict(settings_manager.load_settings()))


def test_the_pick_and_the_re_order_reuse_the_runs_plan_while_nothing_moved(lib):
    # why (P3.3 B31 / B30): `_plan_now` (the pick, the shelf, the re-order) reads the kept plan; only a move, a new plan
    # or another run re-plans
    root, store = lib
    steps = _steps()
    first = steps._plan_now("ja")
    assert first is not None and first.generate == "no", first.reason
    assert steps._plan_now("ja") is first, "nothing moved: the kept plan"
    assert steps._plan_now("ja") is first


def test_a_move_re_plans_without_loading_the_plan_file_again(lib, monkeypatch):
    # why (P3.3 B29): the plan file didn't change — the loaded plan is handed on (`previous`), never parsed again
    root, store = lib
    steps = _steps()
    first = steps.current("ja")
    loads = []
    real = plan_engine.load
    monkeypatch.setattr(plan_engine, "load", lambda path: (loads.append(path), real(path))[1])
    _move_later_to_top(store)
    again = steps.current("ja")
    assert again is not first and again.generate == "no" and again.listed != first.listed
    assert loads == [], "the same plan file: never loaded again"


def test_settings_json_changing_while_the_level_look_reads_it_generates_first(lib, monkeypatch):
    # why (P3.3 B79): the band in force is read again for the look — a settings.json saved between the signature's
    # parts and that read is not the parts' settings: Generate first, never a band guessed from the newer file
    root, store = lib
    _settings_file(root, "ja", logic={"selection": {"band": "uncommon"}})          # a raise: "after" on its own
    assert _current(store).generate == "after"
    real = analyzer.run_signature_parts

    def parts_then_saved_again(*args, **kwargs):
        parts = real(*args, **kwargs)
        _settings_file(root, "ja", logic={"selection": {"band": "rare"}})            # saved again meanwhile
        return parts
    monkeypatch.setattr(analyzer, "run_signature_parts", parts_then_saved_again)
    _settings_file(root, "ja", logic={"selection": {"band": "uncommon"}})
    got = replan.current("ja", _loaded("ja"), store)
    assert got.generate == "first", got.reason


def test_a_word_with_two_rows_keeps_its_first_place_in_the_picks_ranks(monkeypatch):
    # why (P3.3 B63): the pick's ranks follow the CSV reader's own rule (`verbs._listed`: the first row of a (Word,
    # Reading) is its place) — a later duplicate never pushes a word down the list
    monkeypatch.setattr(replan_preview, "places", lambda plan, ids, result: {})
    rows = [{"Word": "約束", "Reading": "ヤクソク"}, {"Word": "勇気", "Reading": "ユウキ"},
            {"Word": "約束", "Reading": "ヤクソク"}]
    got = replan.Current(None, "no", "only the order moved", result=SimpleNamespace(priority=rows))
    assert got.listed == {("約束", "ヤクソク"): 0, ("勇気", "ユウキ"): 1}


def test_junbans_rows_come_in_its_own_order_and_an_unknown_one_reads_as_content(monkeypatch):
    # why (P3.3 B64 / B65): 順's order as settings.json may hold it (any case, spaces) — and a value it doesn't know
    # is the progressive (content) order, never the priority list by accident
    monkeypatch.setattr(replan_preview, "places", lambda plan, ids, result: {})
    asked = []
    result = SimpleNamespace(priority=[], rows=lambda mode: asked.append(mode) or [])
    got = replan.Current(None, "no", "only the order moved", result=result)
    for mode in (" Priority ", "frequency", None, "CONTENT"):
        got.rows(mode)
    assert asked == ["priority", "content", "content", "content"]


def test_a_pins_change_alone_is_another_key(lib):
    # why (P3.3 B67): pinning an episode moves only the pins version — the plan kept for the run is read again
    root, store = lib
    versions = store.versions()
    pinned = dict(versions, pins_version=versions["pins_version"] + 1)
    assert replan.key(store, versions) != replan.key(store, pinned)


def test_a_plan_file_rewritten_within_the_same_second_is_another_plan(tmp_path):
    # why (P3.3 B66): the plan file's stat is to the nanosecond — a Generate rewriting it at the same size within one
    # second is never mistaken for the plan already loaded
    path = tmp_path / "plan.json"
    path.write_text('{"header": {}}', encoding="utf-8")
    base = (os.stat(path).st_mtime_ns // 1_000_000_000) * 1_000_000_000 + 100_000_000
    os.utime(path, ns=(base, base))
    first = replan._stat(str(path))
    os.utime(path, ns=(base + 500_000_000, base + 500_000_000))
    assert replan._stat(str(path)) != first


def test_a_file_gone_from_the_disk_keeps_its_place_and_needs_no_generate(lib):
    # why (P3.3 B71): a missing item keeps counting until you decide (E2.2's K2) — signed as Generate signs it, a file
    # gone from the disk (a drive unplugged) is no reason to hold mining back for a whole Generate
    root, store = lib
    from app import library_store
    phase = library_store.TIERS["soon"][0]
    from app.path_utils import get_data_path
    path = store.schedule()[phase][0]["physical_path"]          # relative to the language's data folder
    os.remove(os.path.join(get_data_path("ja"), path))
    assert path in [entry["physical_path"] for entry in store.schedule()[phase]], "still scheduled: missing, kept"
    _generate(root, "rp2-ja", "ja")                                 # the plan signed with the file missing
    assert not os.path.exists(os.path.join(get_data_path("ja"), path))
    got = _current(store)
    assert got.generate == "no" and got.result is not None, (got.verdict, got.reason)
    assert library_store.path_key(path) in {library_store.path_key(entry[0]) for entry in got.plan.files}


def test_an_episode_graduated_since_the_plan_is_dropped_from_the_re_plan_never_a_generate_first(lib):
    # why (P3.3 B75): a plan file that left the counted tiers (graduated) is dropped from the re-plan — it is still
    # served (mined from now, a Generate after mining), never a KeyError read as "the plan couldn't be read"
    root, store = lib
    item = store.ids("soon")[0]
    store.move([item], "graduated")
    got = _current(store)
    assert got.result is not None and got.generate in ("no", "after"), (got.verdict, got.reason)


def test_a_pin_or_a_new_store_during_junbans_write_counts_as_the_plan_moved(lib):
    # why (P3.3 B85): `_junban_auto` reads the store again after its write — a pin made meanwhile (or the store set up
    # again: another epoch) means the rows it wrote are no longer the plan's: ordered once more / deferred, never paid
    from app.cli import verbs
    root, store = lib
    got = _current(store)
    after = dict(got.versions)
    assert verbs._plan_moved(got, after) is False, "nothing moved"
    assert verbs._plan_moved(got, dict(after, pins_version=after["pins_version"] + 1)) is True
    assert verbs._plan_moved(got, dict(after, epoch="another store")) is True


def test_settings_that_cant_be_signed_never_fail_the_plans_read(lib, monkeypatch):
    # why (P3.3 B89): the settings key only decides when to read again — an error signing them leaves it None (read
    # again next time), never an error out of the plan's read
    root, store = lib

    def unsignable(settings, language):
        raise TypeError("a settings value the signature can't encode")
    monkeypatch.setattr(replan, "settings_key", unsignable)
    got = replan.current("ja", _loaded("ja"), store)
    assert got.generate == "no" and got.result is not None, got.reason
    assert got.settings_key is None
