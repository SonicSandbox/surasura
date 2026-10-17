"""Connect's step records what *Take its new cards out* changed (P4.1 L2 package T, T-6; L2.2 05 §5.7, D14).

`_junban_auto` is the body of `junban --auto`, `resort` and Connect's step. Only Connect's step (`positions_only`
False) asks the run to act on a taken-out item's cards, and — Junban's own store handle being read-only — writes the
run's record into the store itself (`anki_changes`), whatever the run's outcome, as `_record_planned` writes the plan;
`junban --auto` / `resort` (positions only) ask nothing and record nothing. Junban's run is stood in by a fake `auto`
module here (its own suite runs the real one); the store is a migrated library of real names, Japanese and Chinese.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("modules.junban")

from app.cli import verbs  # noqa: E402
from tests.test_library_store_support import LANGUAGES, migrated  # noqa: E402


def _fake_auto(report, outcome="ran"):
    asked = []

    def reorder(settings, **kwargs):
        asked.append(kwargs)
        return {"outcome": outcome, "report": report}
    return SimpleNamespace(blocked=lambda *a, **k: None, window_open=lambda: False, reorder=reorder), asked


def _run(monkeypatch, language, report, positions_only, outcome="ran"):
    from app import analyzer
    monkeypatch.setattr(analyzer, "journey_is_current", lambda *a, **k: True)
    monkeypatch.setattr(verbs, "_session", lambda loaded: None)
    auto, asked = _fake_auto(report, outcome)
    settings = {"target_language": language, "junban_scope": "all", "enable_junban": True}
    args = SimpleNamespace(wait=0)
    try:
        verbs._junban_auto(args, language, settings, auto, positions_only=positions_only)
    except verbs.CliError:
        pass
    return asked


@pytest.mark.parametrize("language", LANGUAGES)
def test_connects_step_asks_for_the_take_out_and_records_what_landed_even_part_way(monkeypatch, language):
    store = migrated(language)
    a, b = store.ids("now")[:2]
    store.finish([a, b], keep_cards=False)
    old = store.record_anki_changes([(b, "cards_out", [31], {"queue": 0}, {"queue": -1, "suspended": [301]})])[0]
    store.put_back_finished([b])
    row = (a, "cards_out", [21, 22], {"queue": 0, "tagged": []},
           {"queue": -1, "suspended": [201, 202], "tag": "Surasura::out", "tagged": [21, 22]})
    report = {"ok": False, "problems": ["Anki stopped answering"], "cards_out": [row], "put_back": [old]}
    asked = _run(monkeypatch, language, report, positions_only=False, outcome="refused")
    assert asked[0]["cards_out"] is True and asked[0]["positions_only"] is False
    records = store.anki_changes_of([a, b])
    assert [(r["item_id"], r["action"], r["notes"], r["after"]["suspended"]) for r in records] == \
        [(a, "cards_out", [21, 22], [201, 202])], "recorded though the run stopped part way; b's record closed"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_junban_auto_and_resort_positions_only_ask_nothing_and_record_nothing(monkeypatch, language):
    store = migrated(language)
    a = store.ids("now")[0]
    store.finish([a], keep_cards=False)
    row = (a, "cards_out", [21], {"queue": 0}, {"queue": -1, "suspended": [201]})
    asked = _run(monkeypatch, language, {"ok": True, "cards_out": [row]}, positions_only=True)
    assert asked[0]["cards_out"] is False
    assert store.anki_changes_of([a]) == []
    store.close()
