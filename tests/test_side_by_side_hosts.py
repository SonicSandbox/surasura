"""Kyou-C: every host of a Junban run records its count of the side-by-side titles' still-new cards into the store
(`pins.record_side` -> `Store.set_side_cards`; Junban's own store handle is read-only): Connect's step and
`junban --auto` (`verbs._junban_auto`, positions only too), the window's re-order host (`replan_preview`) and the 順
window's Reorder (`junban_view.reorder_work`) — so the window and Connect's top N follow the titles Anki was just given.

What a wrong answer would cost a learner: the store keeping an old count after a run (the window and Anki apart again
until some other run), a host that crashes or loses its run's answer when the store can't be written, or a store
opened for nothing on every run that counted nothing. Junban's run is stood in by its report (its own suite runs the
real one); the store is a library of real names, Japanese and Chinese.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("modules.junban")

from app import library_store as ls  # noqa: E402
from app import replan_preview  # noqa: E402
from app.cli import verbs  # noqa: E402
from modules.junban import junban_view, reposition  # noqa: E402
from tests.test_library_store_support import LANGUAGES  # noqa: E402
from tests.test_side_by_side import _library  # noqa: E402


def _report(a, b, loose, d):
    return {"ok": True, "written": [], "left": [],
            "stats": {"side_cards": [[a, 0], [b, 2], [[loose], 1], [d, 1]]}}


def _counted(store):
    """The store's count without its time (Kyou-E: `SIDE_AT`, when the run began reading Anki)."""
    return {k: v for k, v in (store._side_cards() or {}).items() if k != ls.SIDE_AT}


def _want(store, a, b, loose, d):
    work = {i: store.item(i)["work_id"] for i in (a[0], b[0], loose, d[0])}
    return {ls.card_key(ls.title_key(i, work[i])): n for i, n in ((a[0], 0), (b[0], 1), (loose, 1), (d[0], 1))}


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("positions_only", [True, False])
def test_connects_step_and_junban_auto_record_the_count(monkeypatch, language, positions_only):
    from app import analyzer
    store, a, b, loose, d = _library(language)
    store.set_library_options(side_by_side=True)
    monkeypatch.setattr(analyzer, "journey_is_current", lambda *args, **kw: True)
    monkeypatch.setattr(verbs, "_session", lambda loaded: None)
    report = _report(a, b, loose, d)
    auto = SimpleNamespace(blocked=lambda *args, **kw: None, window_open=lambda: False,
                           reorder=lambda settings, **kw: {"outcome": "ran", "report": report})
    settings = {"target_language": language, "junban_scope": "all", "enable_junban": True}
    try:
        verbs._junban_auto(SimpleNamespace(wait=0), language, settings, auto, positions_only=positions_only)
    except verbs.CliError:
        pass
    assert _counted(store) == _want(store, a, b, loose, d)
    store.close()


def test_a_run_that_counted_nothing_opens_no_store_and_a_store_that_fails_is_only_logged(monkeypatch):
    from app.connect import library
    opened = []
    monkeypatch.setattr(library, "open_store", lambda *args, **kw: opened.append(args) or None)
    verbs._record_side("ja", {"ok": True, "stats": {}})
    junban_view.record_side("ja", {"ok": True})
    assert opened == []

    def broken(*args, **kw):
        raise ls.StoreBusy("held")
    monkeypatch.setattr(library, "open_store", broken)
    report = {"stats": {"side_cards": [[[1], 0]]}}
    verbs._record_side("ja", report)                    # logged, never raised: the next run counts again
    junban_view.record_side("ja", report)

    class Held:
        def set_side_cards(self, groups, by):
            raise ls.StoreBusy("held")
    replan_preview._record_side(Held(), report)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_window_re_order_host_records_the_count_as_the_replan(language):
    store, a, b, loose, d = _library(language)
    store.set_library_options(side_by_side=True)
    replan_preview._record_side(store, _report(a, b, loose, d))
    assert _counted(store) == _want(store, a, b, loose, d)
    replan_preview._record_side(store, {"ok": True})    # nothing counted: nothing written
    assert _counted(store) == _want(store, a, b, loose, d)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_junban_windows_reorder_records_the_count_and_returns_its_report(monkeypatch, language):
    store, a, b, loose, d = _library(language)
    store.set_library_options(side_by_side=True)
    report = _report(a, b, loose, d)
    monkeypatch.setattr(reposition, "run", lambda settings, **kw: report)
    monkeypatch.setattr(junban_view, "window_job", lambda settings: None)
    assert junban_view.reorder_work({"target_language": language}, language, {}) is report
    assert _counted(store) == _want(store, a, b, loose, d)
    store.close()
