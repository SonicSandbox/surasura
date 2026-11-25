"""E-L2W (3.0.19): the window's numbers load with Python's collector paused, through the library reader's one pause.

What a wrong answer would cost a learner: at 20,000 files the window opens while the numbers' worker reads the plan
and builds its engine; every full collection that load set off walked the whole library under Python's lock, and the
window's own thread waited for it (the open's worst gap 68-102 ms at level 2 against 51-73 at level 0). The window's
process pauses the collector for that load and freezes what it built after, as its library reader does for each view
(A4 P-gil) — and the two share ONE pause: a reader's look that ends while the numbers still load (or the other way
round) never turns the collector back on under the other.

Runs on a real `library_store` (a small migrated library; Japanese and Chinese show names from tests/Test Resources)
and a plan file shaped like a Generate's whose words are real (a learner's known words; the Chinese tokenizer's golden
cut of real text). The collector's thresholds are lowered so an unpaused load collects many times: the count is the
proof, never a timing.
"""
import gc
import json
import os
import threading
import time

import pytest

from app.services import library_reader
from app.services import moves as M
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES, migrated, roots
from tests.test_services_moves import write_plan

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")


def _real_words(language):
    """[(form, reading)]: a learner's known words (ja), every word of the tokenizer's golden cut of real Chinese text
    (zh)."""
    if language == "ja":
        with open(os.path.join(RESOURCES, "ja", "KnownWord.json"), encoding="utf-8") as f:
            words = json.load(f)["words"]
        return list(dict.fromkeys((w["dictForm"], w["secondary"]) for w in words))[:3000]
    with open(os.path.join(RESOURCES, "zh", "asis_tokens_golden.json"), encoding="utf-8") as f:
        files = json.load(f)["files"]
    out = []
    for sentences in files.values():
        for _text, tokens in sentences:
            out += [(t[0], t[1]) for t in tokens if any("一" <= ch <= "鿿" for ch in t[0])]
    return list(dict.fromkeys(out))


def _wait(pred, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


@pytest.fixture
def window_library(language, monkeypatch):
    """The window's library over a migrated store and a plan of real words: (numbers, reader) from `open_library` with
    the window process's `freeze_gc` — nothing started. The collector is put back as it was, whatever the test did."""
    monkeypatch.setattr(library_reader, "_THAWED", [False])     # this process: no reader stopped yet
    monkeypatch.setattr(library_reader, "_PAUSES", [0], raising=False)  # (a red test's stuck pause never outlives it)
    store = migrated(language)
    with store:
        order = store.scheduled_ids()
        rel = {i: store.item(i)["rel_path"] for i, _t in order}
    plan_file = os.path.join(roots(language)[1], "plan.json.gz")
    write_plan(plan_file, [rel[i] for i, _t in order], [t for _i, t in order], language=language,
               words=_real_words(language))
    made = []

    def make(freeze_gc=True):
        _opener, numbers, reader = M.open_library(language, cache_file=None, poll=0.02, freeze_gc=freeze_gc)
        numbers.plan_file = plan_file
        made.append((numbers, reader))
        return numbers, reader
    threshold = gc.get_threshold()
    gc.unfreeze()
    try:
        yield make
    finally:
        try:
            for numbers, reader in made:                      # (each ended before the patched switch goes back: a
                reader.stop(timeout=30)                       # look or a load still running would give its pause
                numbers.idle(30)                              # back to the module's own count)
                numbers.close()
        finally:
            gc.set_threshold(*threshold)
            gc.unfreeze()
            gc.enable()


def _count_collections(monkeypatch, from_start=True):
    """Every collection (any generation) Python runs on the numbers' worker while its `_load` runs — from its start, or
    from when the test's own hook sets `on` (a hook's wait isn't the load). -> {"runs": n, "on", "cb"}: the caller
    removes `cb` from `gc.callbacks`."""
    out = {"runs": 0, "on": False}
    real = M.Numbers._load

    def load(self):
        out["thread"] = threading.get_ident()
        out["on"] = from_start
        try:
            return real(self)
        finally:
            out["on"] = False

    def cb(phase, info):
        if phase == "start" and out["on"] and threading.get_ident() == out.get("thread"):
            out["runs"] += 1
    monkeypatch.setattr(M.Numbers, "_load", load)
    gc.callbacks.append(cb)
    out["cb"] = cb
    return out


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_windows_numbers_load_runs_with_the_collector_paused_and_frozen_after(language, window_library,
                                                                                  monkeypatch):
    """The window process's numbers (`freeze_gc`) read the plan and build the engine with no collection at all, then
    move what they built out of the collector's sight (`gc.freeze()`) and turn it back on; the same load without
    `freeze_gc` (any other process, the tests) collects as it always did — the referee that the count means something —
    and gives the same figures."""
    figures = {}
    for freeze in (False, True):
        gc.unfreeze()
        numbers, _reader = window_library(freeze_gc=freeze)
        counted = _count_collections(monkeypatch)
        gc.set_threshold(50, 1, 1)
        try:
            numbers.load()
            assert numbers.idle(60) and numbers.why() is None, numbers.why()
        finally:
            gc.callbacks.remove(counted["cb"])
        figures[freeze] = numbers.numbers()[1]
        if freeze:
            assert counted["runs"] == 0, f"{counted['runs']} collections during the window's numbers' load"
            assert gc.get_freeze_count() > 0, "what the load built is out of the collector's sight"
        else:
            assert counted["runs"] > 0, "the referee: an unpaused load collects at these thresholds"
            assert gc.get_freeze_count() == 0, "a load that isn't the window's never freezes"
        assert gc.isenabled(), "the collector on again after the load"
    assert figures[True] == figures[False] and figures[True], "the same figures either way"


@pytest.mark.parametrize("language", LANGUAGES)
def test_after_a_readers_stop_the_numbers_load_neither_pauses_nor_freezes(language, window_library, monkeypatch):
    """A language switch: a reader has stopped (everything thawed) and the switch may still hold the library it left —
    the new numbers' load then freezes nothing (a left library's cycles would stay in memory until the next switch)
    and leaves the collector as it was; the reader's own next freeze collects first and takes the engine too."""
    library_reader._THAWED[0] = True                          # a reader stopped since the last freeze
    numbers, _reader = window_library()
    counted = _count_collections(monkeypatch)
    gc.set_threshold(50, 1, 1)
    try:
        numbers.load()
        assert numbers.idle(60) and numbers.why() is None, numbers.why()
    finally:
        gc.callbacks.remove(counted["cb"])
    assert gc.get_freeze_count() == 0, "nothing frozen while a left library may still be held"
    assert counted["runs"] > 0, "not paused either: a pause is for a build that will be frozen"
    assert gc.isenabled() and library_reader._PAUSES[0] == 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_readers_stop_during_the_numbers_load_leaves_nothing_frozen_after_it(language, window_library, monkeypatch):
    """A language switch mid-load: the reader shows its first view (frozen) and stops while the numbers still load —
    everything goes back to the collector, and the load's end then freezes nothing (the switch may still hold the
    library it left); the collector is on again."""
    numbers, reader = window_library()
    views = []
    reader.subscribe(views.append)
    seen = {}
    real_stale = M.Numbers._stale

    def stale(self, *a, **k):                                 # the numbers' worker, its load half done
        reader.start()
        seen["viewed"] = _wait(lambda: views and views[-1].state == "full", 30)
        seen["frozen_by_reader"] = _wait(lambda: gc.get_freeze_count() > 0, 30)
        reader.stop(timeout=30)                               # the switch: everything given back to the collector
        seen["frozen_after_stop"] = gc.get_freeze_count()
        return real_stale(self, *a, **k)
    monkeypatch.setattr(M.Numbers, "_stale", stale)
    numbers.load()
    assert numbers.idle(60) and numbers.why() is None, numbers.why()
    assert seen["viewed"] and seen["frozen_by_reader"] and seen["frozen_after_stop"] == 0, seen
    assert gc.get_freeze_count() == 0, "nothing frozen at the end of a load a reader's stop crossed"
    assert gc.isenabled() and library_reader._PAUSES[0] == 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reader_look_ending_before_the_numbers_load_ends_leaves_the_collector_paused_for_the_rest(
        language, window_library, monkeypatch):
    """One pause, two users, crossing: the reader's look starts (its build paused), the numbers' load starts inside it,
    and the look ends first — the collector stays paused for the rest of the numbers' load (no collection in it), and
    is on again once both are done."""
    numbers, reader = window_library()
    in_load, look_done = threading.Event(), threading.Event()
    seen = {}
    real_build, real_stale, real_wait = view_rows.build, M.Numbers._stale, reader._wait

    def build(*a, **k):                                       # the reader's thread, inside its paused look
        if not in_load.is_set():
            numbers.load()
            seen["in_load"] = in_load.wait(30)                # the numbers' load has started
        return real_build(*a, **k)

    def wait():
        look_done.set()                                       # (the look's own `finally` has run)
        return real_wait()

    def stale(self, *a, **k):                                 # the numbers' worker, its load half done
        in_load.set()
        seen["look_done"] = look_done.wait(30)
        seen["on_after_look"] = gc.isenabled()
        counted["on"] = True                                  # the rest of the load is counted from here
        return real_stale(self, *a, **k)
    monkeypatch.setattr(view_rows, "build", build)
    monkeypatch.setattr(M.Numbers, "_stale", stale)
    reader._wait = wait
    counted = _count_collections(monkeypatch, from_start=False)
    gc.set_threshold(50, 1, 1)
    try:
        reader.start()
        assert _wait(lambda: "on_after_look" in seen, 60)
        assert numbers.idle(60) and numbers.why() is None, numbers.why()
    finally:
        gc.callbacks.remove(counted["cb"])
    assert seen.get("in_load") and seen.get("look_done"), seen
    assert seen["on_after_look"] is False, "still paused for the numbers after the reader's look ended"
    assert counted["runs"] == 0, f"{counted['runs']} collections in the rest of the numbers' load"
    assert _wait(gc.isenabled, 5), "on again once both are done"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_numbers_load_ending_before_the_reader_look_ends_leaves_the_collector_paused_for_the_rest(
        language, window_library, monkeypatch):
    """The other crossing: the numbers' load starts, the reader's look starts inside it (its build), and the load ends
    first — the collector stays paused for the rest of the reader's build (no collection in it), and is on again once
    both are done."""
    numbers, reader = window_library()
    in_build, load_done = threading.Event(), threading.Event()
    seen = {"runs": 0}
    real_build, real_stale, real_load = view_rows.build, M.Numbers._stale, M.Numbers._load

    def stale(self, *a, **k):                                 # the numbers' worker, inside its load
        if not in_build.is_set():
            reader.start()
            seen["in_build"] = in_build.wait(30)              # the reader's look is building
        return real_stale(self, *a, **k)

    def load(self):
        try:
            return real_load(self)
        finally:
            load_done.set()

    def build(*a, **k):                                       # the reader's thread, inside its look
        if "on_after_load" in seen:
            return real_build(*a, **k)
        in_build.set()
        seen["load_done"] = load_done.wait(30)
        seen["on_after_load"] = gc.isenabled()
        me = threading.get_ident()

        def cb(phase, info):
            if phase == "start" and threading.get_ident() == me:
                seen["runs"] += 1
        gc.callbacks.append(cb)
        try:
            return real_build(*a, **k)                        # the rest of the reader's build, counted
        finally:
            gc.callbacks.remove(cb)
    monkeypatch.setattr(view_rows, "build", build)
    monkeypatch.setattr(M.Numbers, "_stale", stale)
    monkeypatch.setattr(M.Numbers, "_load", load)
    views = []
    reader.subscribe(views.append)
    gc.set_threshold(50, 1, 1)
    numbers.load()
    assert _wait(lambda: views and views[-1].state == "full" and "on_after_load" in seen, 60)
    assert numbers.idle(60) and numbers.why() is None, numbers.why()
    assert seen.get("in_build") and seen.get("load_done"), seen
    assert seen["on_after_load"] is False, "still paused for the reader's build after the numbers' load ended"
    assert seen["runs"] == 0, f"{seen['runs']} collections in the rest of the reader's build"
    assert _wait(gc.isenabled, 5), "on again once both are done"
