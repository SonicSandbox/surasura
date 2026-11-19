"""Mado-PZ (2026-11-18, a tester's ask: the work Surasura runs by itself taxes the PC): one model for what a circle's
pause holds — `settings_manager.paused` (settings.json's `paused`, kept across a restart), read by every gate that starts
work by itself: the window's job registry (its automatic jobs only), the re-order host and 順's automatic step, hato's
look, Connect (`tests/connect/test_pz_paused.py`). D29's *Run things by themselves* stays the master switch; a pause is
the quick, temporary hold over each automation's own switch, which it never changes.

What a wrong answer would cost a learner: the PC still working hard after they paused it to do something else; a job
they pressed themselves held back by it; a pause lost (resumed by itself) at a restart or a settings import, or carried
to another PC by an export; 順 re-ordering Anki twice when it is resumed.
"""
import json
import os

import pytest

from app import analyzer, path_utils, replan_preview, settings_manager, settings_placement
from app.services import automation, jobs as J, phase, settings_io
from app.services.jobs import JobRegistry


# --- the one predicate ------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("held, paused", [
    (["miner", "junban"], {"miner", "junban"}),
    (("surasura",), {"surasura"}),                       # a window's frozen copy holds a tuple
    (["miner", "not-a-circle", 3], {"miner"}),           # a hand-edited value: only the circles it names
    ("miner", set()),                                    # not a list: nothing paused (never a letter-by-letter read)
    ({"miner": True}, set()),                            # nor a mapping's keys
    (3, set()),                                          # nor a number (never a raise: every gate reads it)
    (None, set()),
])
def test_paused_reads_only_the_circles_a_list_names(held, paused):
    assert settings_manager.paused({"paused": held}) == frozenset(paused)
    assert settings_manager.paused({}) == frozenset() == settings_manager.paused(None)
    for circle in settings_manager.PAUSABLE:
        assert settings_manager.paused({"paused": held}, circle) is (circle in paused)


def test_the_pausable_circles_are_the_phase_strips_five():
    assert settings_manager.PAUSABLE == phase.CIRCLES


def test_nothing_is_paused_by_default_and_a_pause_is_no_run_setting():
    """A pause never costs a Generate: it is placed `neither` and the run signature leaves it out."""
    assert settings_manager.DEFAULT_SETTINGS["paused"] == []
    assert settings_placement.kind("paused", "ja") == settings_placement.kind("paused", "zh") == "neither"
    base = settings_manager.load_settings()
    for language in ("ja", "zh"):
        assert analyzer.settings_signature(dict(base, paused=["miner", "surasura"]), language) == \
            analyzer.settings_signature(base, language)


# --- the window's registry: a paused circle's automatic jobs wait, a job you asked for never does ------------------ #
def _gate(paused):
    return lambda kind: "paused" if phase.KINDS.get(kind) in paused else None


def test_a_paused_circles_automatic_job_waits_paused_and_starts_on_the_resume():
    paused, started = {"surasura"}, []
    registry = JobRegistry()
    registry.gate(_gate(paused), automatic=True)
    quiet = registry.submit("generate", "Generating", lambda job: started.append("quiet"), automatic=True)
    index = registry.submit("indexer", "Reading your files", lambda job: started.append("index"), automatic=True)
    sync = registry.submit("anki-sync", "Updating known words", lambda job: started.append("sync"), automatic=True)
    assert quiet.state == index.state == J.WAITING and quiet.reason == "paused" == index.reason
    assert sync.state == J.RUNNING, "another circle's job runs"
    paused.clear()
    registry.reschedule()
    assert quiet.state == J.RUNNING and started == ["sync", "quiet"], "resumed: what waited starts, in order"
    quiet.finish()
    assert index.state == J.RUNNING


def test_a_job_you_ask_for_is_never_held_by_a_pause_and_absorbs_the_waiting_automatic_one():
    started = []
    registry = JobRegistry()
    registry.gate(_gate({"surasura"}), automatic=True)
    quiet = registry.submit("generate", "Generating", lambda job: started.append("quiet"), automatic=True)
    yours = registry.submit("generate", "Generating", lambda job: started.append("yours"))
    assert yours.state == J.RUNNING and started == ["yours"]
    assert quiet.state == J.DONE and quiet.cancelled, "one run, yours: the waiting automatic one is absorbed"


def test_the_updates_gate_still_holds_every_job():
    registry = JobRegistry()
    registry.gate(lambda kind: "an update waits")
    yours = registry.submit("generate", "Generating", lambda job: None)
    assert yours.state == J.WAITING and yours.reason == "an update waits"


def test_a_pause_stops_only_what_started_by_itself():
    registry = JobRegistry()
    auto = registry.submit("indexer", "Reading your files", lambda job: None, cancel=lambda job: None, automatic=True)
    yours = registry.submit("generate", "Generating", lambda job: None, cancel=lambda job: None)
    views = registry.live()
    assert phase.stoppable(views, phase.SURASURA, automatic=True) == (auto.id,)
    assert set(phase.stoppable(views, phase.SURASURA)) == {auto.id, yours.id}, "the menu's Stop: both, as before"


# --- 順: the re-order host stands aside, and its automatic step never re-orders too ---------------------------------- #
JUNBAN = {"target_language": "ja", "enable_junban": True, "junban_scope": "deck", "junban_deck": "日本語::Mining",
          "junban_replan_language": "ja", "junban_replan_deck": "日本語::Mining", "logic": {"automation": True}}


def test_a_paused_junban_stands_the_reorder_host_aside_quietly(monkeypatch):
    monkeypatch.setattr(replan_preview, "junban_present", lambda: True)
    monkeypatch.setattr(replan_preview, "unavailable", lambda settings: None)
    settings = dict(JUNBAN, paused=["junban"])
    assert replan_preview.stands_aside(settings, "ja") == replan_preview.JUNBAN_PAUSED
    assert replan_preview.aside_line(settings, "ja") is replan_preview.OFF, "the circle says it: no line of its own"
    assert replan_preview.stands_aside(dict(JUNBAN, paused=["miner"]), "ja") is None
    off = dict(settings, logic={"automation": False})
    assert replan_preview.stands_aside(off, "ja") == replan_preview.AUTOMATION_OFF, "the master switch first"


def test_a_paused_junbans_automatic_step_never_reorders_beside_the_hosts_catch_up(monkeypatch):
    """Paused, the host stands aside — and `reorders` must not read that as *the host can't, so 順's step may*: the
    step's job, held at the gate, would re-order on the resume beside the host's own catch-up."""
    monkeypatch.setattr(replan_preview, "automation_on", lambda settings, language: False)
    assert automation.reorders(dict(JUNBAN), "ja") is True
    assert automation.reorders(dict(JUNBAN, paused=["junban"]), "ja") is False
    assert automation.reorders(dict(JUNBAN, paused=["arrivals"]), "ja") is True


# --- 届: hato's look ----------------------------------------------------------------------------------------------- #
def test_a_paused_arrivals_circle_hands_hato_nothing(monkeypatch):
    from app import no_subs
    asked = []
    monkeypatch.setattr(no_subs, "hato_finds", lambda language="ja": asked.append(language) or "hato-cli")
    for language, key in (("ja", no_subs.SETTING), ("zh", no_subs.SETTING_ZH)):
        assert no_subs.find(None, language, {key: True, "paused": ["arrivals"]}) == {"paused": True}
    assert asked == [], "nothing looked for, nothing started"


# --- settings export and import: a pause is this PC's ---------------------------------------------------------- #
def _install(settings):
    with open(path_utils.get_settings_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)


def _file():
    with open(path_utils.get_settings_path(), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_an_export_never_carries_a_pause_and_an_import_keeps_this_pcs(tmp_path, language):
    out = str(tmp_path / "設定.json")
    _install({"target_language": language, "text_size": "S", "paused": ["miner", "surasura"]})
    assert settings_io.export(out).ok
    with open(out, encoding="utf-8") as f:
        assert "paused" not in json.load(f)["settings"]
    _install({"target_language": language, "paused": ["junban"]})
    assert settings_io.apply(settings_io.read(out)).ok
    assert _file() == {"target_language": language, "text_size": "S", "paused": ["junban"]}, \
        "resumed only by a click: never by an import"
    _install({"target_language": language})
    assert settings_io.apply(settings_io.read(out)).ok
    assert "paused" not in _file()
