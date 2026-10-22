"""Automatic Anki sync, automatic Generate and 順's automatic reorder (`app/services/automation.py`) — W3.5 row 3.

What a wrong answer would cost:
  * two syncs at once, or one per click — `<FocusIn>` fires for every widget, so a focus storm must sync once, and a
    sync asked for while one runs must not start a second append to KnownWord.json;
  * a sync behind the user's back — the first sync is the user's own *Sync now*; no decks, the test switch or an
    update waiting must keep Anki untouched;
  * two Generates, or the user's own cancelled — an automatic Generate yields to the user's, and joins it when the user
    presses while it waits;
  * a Generate every few seconds — at most every 10 minutes, with one alarm for the moment the limit is up;
  * a window that dies with an optional module — 順 absent, the service still runs.

Anki is never reached: `anki_connect.probe`, `anki_sync.sync` and `sync_backlog` are fakes; the gates are the real
`anki_sync.may_sync` over a real sync-state file, the counts the real `count_known` over the suite's Japanese and Chinese
KnownWord.json. Generate's child is a launcher that records each run (the real controller and registry decide).
"""
import os
import sys
import threading
import time
import types

import pytest

from app import anki_connect, anki_sync
from app.services import automation as A
from app.services import generate as G
from app.services import jobs as J
from app.services.generate import GenerateController
from app.services.jobs import JobRegistry
from tests import services_helpers as h


# --- stand-ins ------------------------------------------------------------------------------------------------- #
class _Settings:
    """The settings service's shape: `get`, `set`, `flush`."""

    def __init__(self, **values):
        self.values = dict(values)
        self.flushes = 0

    def get(self):
        return dict(self.values)

    def set(self, changes):
        self.values.update(changes)

    def flush(self, timeout=None):
        self.flushes += 1


class _Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class _Timer:
    def __init__(self, delay, call):
        self.delay, self.call, self.cancelled = delay, call, False

    def cancel(self):
        self.cancelled = True


class _Timers(list):
    def __call__(self, delay, call):
        timer = _Timer(delay, call)
        self.append(timer)
        return timer

    def live(self):
        return [t for t in self if not t.cancelled]


class _Child:
    returncode = None

    def poll(self):
        return self.returncode


class _Launches:
    """The controller's launcher: records each run; the test ends it."""

    def __init__(self):
        self.runs = []
        self.lock = threading.Lock()

    def __call__(self, run):
        run.cancel_file = os.path.join(h.root(), f"auto-cancel-{len(self.runs)}.flag")
        with self.lock:
            self.runs.append(run)
        run.started(_Child())

    def count(self):
        with self.lock:
            return len(self.runs)


class _Anki:
    """AnkiConnect and the sync, faked: `open` Anki or closed, each call counted; `gate` holds a sync mid-way."""

    def __init__(self, monkeypatch, added=3, open_=True):
        self.open, self.added = open_, added
        self.syncs, self.backlogs = [], []
        self.gate = None
        self.lock = threading.Lock()
        monkeypatch.setattr(anki_connect, "probe", lambda url, *a, **k: {"ok": self.open})
        monkeypatch.setattr(anki_sync, "sync", self._sync)
        monkeypatch.setattr(anki_sync, "sync_backlog", self._backlog)

    def _sync(self, language, url, decks, fields, include_suspended=False, full=False):
        with self.lock:
            self.syncs.append((language, tuple(decks)))
        if self.gate is not None:
            self.gate.wait(10)
        return anki_sync.SyncResult(added=self.added, total_known=anki_sync.count_known(language))

    def _backlog(self, language, url, decks, fields):
        with self.lock:
            self.backlogs.append((language, tuple(decks)))


def _synced_once(language):
    """The user's own first *Sync now* happened (the real state file `may_sync` reads)."""
    anki_sync._save_state(language, {"last_sync": "2026-10-01T10:00:00"})


def _settings(lang="ja", **extra):
    values = {"target_language": lang, "anki_sync_auto": True, "anki_auto_generate": True,
              "anki_sync_decks": {lang: ["Mining"]}, "anki_sync_fields": {lang: ["Word"]},
              "anki_connect_url": "http://127.0.0.1:9"}
    values.update(extra)
    return _Settings(**values)


@pytest.fixture
def live(monkeypatch):
    """The switches the suite sets, off: the service decides as it would for a user."""
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)


def _make(settings, lang="ja", staged=lambda: False, indexes=None, content=True, clock=None, timers=None,
          journey=lambda s, l: True):
    registry = JobRegistry()
    controller = GenerateController(registry, settle=0)
    launches = _Launches()
    auto = A.Automation(registry, controller, settings, lang, update_staged=staged,
                        index=(lambda: indexes.append(1)) if indexes is not None else None, launcher=launches,
                        clock=clock or _Clock(), timer=timers if timers is not None else _Timers(),
                        has_content=lambda language: content, journey_current_fn=journey)
    return auto, registry, controller, launches


def _settle(auto, registry, seconds=10):
    """Everything asked has run: the worker idle and no automatic job left live."""
    def quiet():
        return auto.worker.idle(0.05) and not [v for v in registry.live() if v.kind in ("anki-sync", "junban",
                                                                                         "anki-backlog")]
    assert h.until(quiet, seconds=seconds)
    assert auto.worker.idle(5)


# --- the sync ---------------------------------------------------------------------------------------------------- #
def test_a_focus_storm_syncs_once(live, monkeypatch):
    """`_maybe_anki_sync`'s 5-minute limit: twenty activations in a moment are one sync, one job."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch)
    auto, registry, _c, _l = _make(_settings(anki_auto_generate=False))
    for _ in range(20):
        auto.activated()
    _settle(auto, registry)
    assert anki.syncs == [("ja", ("Mining",))]
    assert anki.backlogs == [("ja", ("Mining",))], "the Tk work()'s order: the sync, then the backlog"
    assert [v.kind for v in registry.snapshot()].count("anki-sync") == 1
    auto.close()


def test_a_sync_asked_for_while_one_runs_never_starts_a_second(live, monkeypatch):
    """The Tk `_anki_sync_lock.acquire(blocking=False)`: a forced trigger (a language switch) during a sync starts
    nothing; once it ends, the next forced trigger syncs again."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch)
    anki.gate = threading.Event()
    auto, registry, _c, _l = _make(_settings(anki_auto_generate=False))
    auto.language_changed("ja")
    assert h.until(lambda: len(anki.syncs) == 1, seconds=5)
    assert auto.state().sync == A.SYNCING
    for _ in range(5):
        auto.language_changed("ja")
        auto.activated()
    assert auto.worker.idle(5)
    assert len(anki.syncs) == 1 and len(registry.live("anki-sync")) == 1, "never a second sync beside the first"
    anki.gate.set()
    _settle(auto, registry)
    auto.language_changed("ja")
    _settle(auto, registry)
    assert len(anki.syncs) == 2, "forced, after the first ended: it syncs"
    auto.close()


def test_the_throttle_counts_from_never_and_holds_five_minutes(live, monkeypatch):
    """`_last_anki_sync = float("-inf")`: at the computer's start (monotonic 0) the first activation syncs; then not
    before 300 s; a forced trigger passes the limit."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch, added=0)
    clock = _Clock(0.0)
    auto, registry, _c, _l = _make(_settings(), clock=clock)
    auto.activated()
    _settle(auto, registry)
    assert len(anki.syncs) == 1, "0.0 is not 'just now'"
    clock.now = 299.0
    auto.activated()
    _settle(auto, registry)
    assert len(anki.syncs) == 1
    clock.now = 300.0
    auto.activated()
    _settle(auto, registry)
    assert len(anki.syncs) == 2
    clock.now = 301.0
    auto.language_changed("ja")
    _settle(auto, registry)
    assert len(anki.syncs) == 3, "forced"
    auto.close()


@pytest.mark.parametrize("gate", ["switch", "auto-off", "no-decks", "first-sync", "update-staged"])
def test_each_gate_keeps_anki_untouched(live, monkeypatch, gate):
    """The gates `_maybe_anki_sync` asks (`anki_sync.may_sync`'s, the setting, `updater.children_held`): Anki is never
    reached, no job is made, and the limit isn't used up — the sync runs as soon as the gate opens."""
    h.seed_library("ja")
    anki = _Anki(monkeypatch)
    settings = _settings(anki_auto_generate=False)
    staged = [False]
    if gate == "switch":
        monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    if gate != "first-sync":
        _synced_once("ja")
    if gate == "auto-off":
        settings.values["anki_sync_auto"] = False
    if gate == "no-decks":
        settings.values["anki_sync_decks"] = {"zh": ["中文"]}
    if gate == "update-staged":
        staged[0] = True
    auto, registry, _c, _l = _make(settings, staged=lambda: staged[0])
    auto.activated()
    _settle(auto, registry)
    assert anki.syncs == [] and not [v for v in registry.snapshot() if v.kind == "anki-sync"]
    assert auto.state().sync == A.IDLE
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    settings.values.update(_settings(anki_auto_generate=False).values)
    _synced_once("ja")
    staged[0] = False
    auto.activated()
    _settle(auto, registry)
    assert len(anki.syncs) == 1, "a refused gate doesn't use up the 5 minutes"
    auto.close()


def test_anki_closed_is_a_state_and_nothing_is_read(live, monkeypatch):
    """A closed AnkiConnect port: silent, no sync, the bar's mark reads *Anki closed*."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch, open_=False)
    auto, registry, _c, _l = _make(_settings())
    auto.activated()
    _settle(auto, registry)
    assert anki.syncs == [] and anki.backlogs == []
    assert auto.state().sync == A.CLOSED
    job = [v for v in registry.snapshot() if v.kind == "anki-sync"][0]
    assert job.state == J.DONE
    auto.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_sync_reports_what_it_added_and_the_known_count(live, monkeypatch, lang):
    """The bar's state after a sync: synced, the words added, and the known-words count of the real KnownWord.json
    (read on the worker), for Japanese and Chinese."""
    h.seed_library(lang)
    _synced_once(lang)
    _Anki(monkeypatch, added=5)
    seen = []
    auto, registry, _c, _l = _make(_settings(lang, anki_auto_generate=False), lang=lang)
    auto.subscribe(seen.append)
    auto.started()
    assert auto.worker.idle(5)
    expected = anki_sync.count_known(lang)
    assert expected > 0, "a real known-words file"
    assert auto.state().known == expected and auto.state().sync == A.IDLE
    auto.activated()
    _settle(auto, registry)
    state = auto.state()
    assert (state.sync, state.added, state.known, state.language) == (A.SYNCED, 5, expected, lang)
    assert [s.sync for s in seen].count(A.SYNCING) == 1
    assert [s.seq for s in seen] == sorted(set(s.seq for s in seen)), "in order, each once"
    auto.close()


def test_started_forces_the_sync_two_seconds_on_and_never_under_test(live, monkeypatch):
    """`root.after(2000, lambda: self._maybe_anki_sync(force=True))`, skipped under `SURASURA_NO_UI_TIMERS`."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch, added=0)
    timers = _Timers()
    auto, registry, _c, _l = _make(_settings(), timers=timers)
    auto.started()
    auto.started()
    assert [t.delay for t in timers] == [A.START_DELAY], "one start timer"
    timers[0].call()
    _settle(auto, registry)
    assert len(anki.syncs) == 1
    auto.close()
    monkeypatch.setenv("SURASURA_NO_UI_TIMERS", "1")
    timers2 = _Timers()
    auto2, registry2, _c, _l = _make(_settings(), timers=timers2)
    auto2.started()
    assert auto2.worker.idle(5) and timers2 == []
    auto2.close()


# --- after a sync: Generate, or the indexer ---------------------------------------------------------------------- #
def test_new_known_words_ask_for_one_quiet_generate(live, monkeypatch):
    """`_on_anki_sync_result` → `_maybe_auto_generate`: a quiet run (written, not opened), through the controller, the
    backlog read beside it; the journey asked again."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch)
    checks = []
    timers = _Timers()
    auto, registry, controller, launches = _make(_settings(), timers=timers)
    monkeypatch.setattr(controller, "check", lambda settings, language, then=None: checks.append(language))
    auto.activated()
    assert h.until(lambda: launches.count() == 1, seconds=10)
    run = launches.runs[0]
    assert run.quiet and "--no-open" in run.argv
    assert h.until(lambda: len(anki.backlogs) == 2, seconds=5), "the sync's own read, then Generate's"
    assert auto.worker.idle(5)
    rechecks = [t for t in timers if t.delay == A.CHECK_SETTLE]
    assert len(rechecks) == 2 and len([t for t in rechecks if not t.cancelled]) == 1, "focus, then the words: one"
    [t for t in rechecks if not t.cancelled][0].call()
    assert auto.worker.idle(5) and checks == ["ja"]
    assert auto.generate.pending is False
    run.ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    _settle(auto, registry)
    assert launches.count() == 1
    auto.close()


def test_without_automatic_generate_the_indexer_is_asked_instead(live, monkeypatch):
    """`if not self._maybe_auto_generate(): self._maybe_launch_indexer(force=True)`."""
    h.seed_library("ja")
    _synced_once("ja")
    _Anki(monkeypatch)
    indexes = []
    auto, registry, _c, launches = _make(_settings(anki_auto_generate=False), indexes=indexes)
    auto.activated()
    _settle(auto, registry)
    assert indexes == [1] and launches.count() == 0
    auto.close()


def test_a_sync_that_added_nothing_asks_for_nothing(live, monkeypatch):
    h.seed_library("ja")
    _synced_once("ja")
    _Anki(monkeypatch, added=0)
    indexes = []
    auto, registry, _c, launches = _make(_settings(), indexes=indexes)
    auto.activated()
    _settle(auto, registry)
    assert indexes == [] and launches.count() == 0
    auto.close()


def test_the_ten_minute_limit_and_its_alarm(live):
    """`_maybe_auto_generate`'s 600 s and `_auto_generate_alarm`: words 100 s after an automatic run wait; one alarm
    for the moment the limit is up (replaced, never stacked); it rings and the run goes."""
    clock = _Clock(1000.0)
    timers = _Timers()
    auto, registry, controller, launches = _make(_settings(), clock=clock, timers=timers)
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].ended(0)
    assert h.until(lambda: controller._run is None, seconds=5)
    clock.now = 1100.0
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert auto.worker.idle(5)
    clock.now = 1200.0
    auto.activated()
    assert auto.worker.idle(5)
    assert launches.count() == 1
    alarms = [t for t in timers if t.delay > 1]
    assert [round(t.delay) for t in alarms] == [500, 400]
    assert len([t for t in alarms if not t.cancelled]) == 1, "one alarm, the newest"
    clock.now = 1600.0
    [t for t in alarms if not t.cancelled][0].call()
    assert h.until(lambda: launches.count() == 2, seconds=5)
    launches.runs[1].ended(0)
    auto.close()


def test_the_alarm_is_never_set_under_test(live, monkeypatch):
    monkeypatch.setenv("SURASURA_NO_UI_TIMERS", "1")
    clock = _Clock(0.0)
    timers = _Timers()
    auto, registry, controller, launches = _make(_settings(), clock=clock, timers=timers)
    auto.generate._last = -100.0
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert auto.worker.idle(5)
    assert timers == [] and launches.count() == 0
    auto.close()


@pytest.mark.parametrize("hold", ["child", "update", "empty", "other-language", "switch"])
def test_the_automatic_generate_waits_while_something_holds_it(live, monkeypatch, hold):
    """`_maybe_auto_generate`'s gates: a child process alive (asked again when it ends), an update waiting, an empty
    library, words for the other language (they run once it is open again), the test switch."""
    staged = [hold == "update"]
    auto, registry, controller, launches = _make(_settings(), staged=lambda: staged[0], content=hold != "empty")
    child = registry.record("child", "Content Importer") if hold == "child" else None
    if hold == "switch":
        monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    auto.worker.put(auto.generate.known_words_changed, "zh" if hold == "other-language" else "ja")
    assert auto.worker.idle(5)
    # Never asked for: its launch is a worker's, so the job is what tells.
    assert launches.count() == 0 and not registry.live("generate")
    if hold == "child":
        child.finish(ok=True)
        assert h.until(lambda: launches.count() == 1, seconds=5), "the child's end asks again"
    elif hold == "other-language":
        auto.language_changed("zh")
        assert h.until(lambda: launches.count() == 1, seconds=5)
        assert launches.runs[0].language == "zh"
    elif hold == "update":
        staged[0] = False
        auto.update_cancelled()
        assert h.until(lambda: launches.count() == 1, seconds=5)
    else:
        auto.activated()
        assert auto.worker.idle(5) and launches.count() == 0 and not registry.live("generate")
    for run in launches.runs:
        run.ended(0)
    auto.close()


def test_an_automatic_generate_yields_to_the_users_running_one(live):
    """Words wait while the user's Generate runs; a Generate that started after they came includes them (the Tk
    `run_analyzer` clears the pending language as any Generate of it starts) — one run, the user's."""
    staged = [True]
    auto, registry, controller, launches = _make(_settings(), staged=lambda: staged[0])
    auto.worker.put(auto.generate.known_words_changed, "ja")      # held back (an update waits): the words wait
    assert auto.worker.idle(5) and auto.generate.pending == "ja" and launches.count() == 0
    staged[0] = False
    time.sleep(0.05)
    user = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches, settle=0)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    auto.activated()
    assert auto.worker.idle(5)
    assert launches.count() == 1 and auto.generate.pending == "ja"
    user.ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    assert h.until(lambda: auto.generate.pending is False, seconds=5)
    auto.activated()
    assert auto.worker.idle(5)
    assert launches.count() == 1, "never a second run for words the user's already took in"
    auto.close()


def test_words_that_come_while_a_generate_runs_wait_for_the_next_one(live):
    """HR-1: the Tk `run_analyzer` cleared the pending language as a Generate of it *started* — words a sync brings in
    after that are not in that run, so they stay pending and its end asks for the quiet run (never lost until some
    other trigger)."""
    auto, registry, controller, launches = _make(_settings())
    user = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches, settle=0)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    time.sleep(0.05)
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert auto.worker.idle(5) and auto.generate.pending == "ja"
    user.ended(0)
    assert h.until(lambda: launches.count() == 2, seconds=5)
    assert launches.runs[1].quiet and launches.runs[1].language == "ja"
    launches.runs[1].ended(0)
    auto.close()


def test_the_controllers_state_says_when_a_run_is_automatic(live):
    """IK-20: the Generate button tells an automatic run from the user's (a click on an automatic one is the user's
    own request, never its cancel) — the controller's state carries `quiet` while the run is asked for and running."""
    auto, registry, controller, launches = _make(_settings())
    seen = []
    controller.subscribe(seen.append)
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert controller.state().state == G.RUNNING and controller.state().quiet is True
    assert all(s.quiet for s in seen if s.state in (G.QUEUED, G.RUNNING))
    launches.runs[0].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    assert controller.state().quiet is False
    user = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches, settle=0)
    assert h.until(lambda: launches.count() == 2, seconds=5)
    assert controller.state().state == G.RUNNING and controller.state().quiet is False
    user.ended(0)
    auto.close()


def test_the_automatic_generate_sets_up_the_language_folders_first(live, monkeypatch):
    """IK-21: `run_analyzer` (quiet too) called `ensure_data_setup(language)` before every Generate — the tier folders,
    the word lists, the 30-day .trash clean-up — on the worker."""
    from app import path_utils
    calls = []
    monkeypatch.setattr(path_utils, "ensure_data_setup", lambda language=None: calls.append(
        (language, threading.current_thread().name)))
    auto, registry, controller, launches = _make(_settings())
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert calls == [("ja", "automation")]
    launches.runs[0].ended(0)
    auto.close()


def test_a_journey_check_running_never_loses_the_newer_timer(live, monkeypatch):
    """HR-21: a check that rings while a newer burst armed the next timer forgets only its own timer — `close()` still
    takes the newer one back, and the burst after it replaces it (one check per burst)."""
    timers = _Timers()
    auto, registry, controller, _l = _make(_settings(anki_sync_auto=False), timers=timers)
    monkeypatch.setattr(controller, "check", lambda settings, language, then=None: None)
    hold = threading.Event()
    auto.worker.put(hold.wait, 10)                       # the worker busy: the first check waits its turn
    auto.recheck()
    first = timers[-1]
    first.call()                                         # it rings: its check is queued
    auto.recheck()
    second = timers[-1]
    assert second is not first
    hold.set()
    assert auto.worker.idle(5)                           # the first timer's check ran
    auto.recheck()
    assert second.cancelled, "the burst after it replaced the newer timer"
    third = timers[-1]
    auto.close()
    assert third.cancelled, "close takes the armed timer back"


def test_the_level_of_a_hand_edited_line_is_your_own_band(monkeypatch):
    """IK-28 (`_auto_band_choice`): an Automatic line the rule can't compare with ("850" in quotes, hand-edited into
    settings.json) makes the analyzer keep your own band — so that is the band the level chip shows."""
    from app import analyzer, library_store, token_index, word_selection
    for key in ("names_recurring", "names_kanji", "names_work_terms"):
        monkeypatch.setitem(analyzer.LOGIC, key, analyzer.LOGIC.get(key, True))

    class Store:
        def file_count(self):
            return 4

        def close(self):
            pass
    monkeypatch.setattr(token_index, "open_store", lambda language: Store())
    monkeypatch.setattr(token_index, "preview_frequencies", lambda *a, **k: {"total_tokens": 4000})
    monkeypatch.setattr(word_selection, "band_previews", lambda *a, **k: {
        band: {"word_count": 100 * (n + 1)} for n, band in enumerate(word_selection.BANDS_ORDER)})
    monkeypatch.setattr(library_store, "read_auto_band", lambda *a, **k: None)
    selection = {"auto": True, "band": "uncommon", "auto_max_words": 300}
    assert A.level({"logic": {"selection": selection}}, "ja") == ("occasional", True)
    selection["auto_max_words"] = "850"
    assert A.level({"logic": {"selection": selection}}, "ja") == ("uncommon", True)


@pytest.mark.parametrize("keys, moves", [
    (["logic.selection.band"], True), (["logic.selection.auto_max_words"], True), (["logic.names_kanji"], True),
    (["zh_script"], True), (["logic"], True), (["logic.ignore_names"], False), (["logic.phrase_rows"], False),
    (["anki_sync_auto", "theme"], False)])
def test_only_what_the_level_reads_reads_it_again(keys, moves):
    """IK-28 (S19): the level chip is read again (a token store read) only after a write of what `level` reads — the
    selection, the names layers the Tk refresh sets, the Chinese script — never after any other `logic` key."""
    assert A.moves_level(keys) is moves


def test_a_users_press_while_the_automatic_one_waits_its_turn_joins_it(live):
    """The automatic run waits for another program's Generate (`results`); the user presses: one run, the user's."""
    h.seed_library("ja")
    auto, registry, controller, launches = _make(_settings())
    with h.Holder("results", "Generate"):
        auto.worker.put(auto.generate.known_words_changed, "ja")
        assert h.until(lambda: controller.state().message == "Waiting for Generate to finish", seconds=10)
        controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches)
    assert h.until(lambda: launches.count() == 1, seconds=10)
    assert not launches.runs[0].quiet, "the user's run"
    launches.runs[0].ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    _settle(auto, registry)
    assert launches.count() == 1
    generates = [v for v in registry.snapshot() if v.kind == "generate"]
    assert [v.automatic for v in generates] == [True, False] and generates[0].cancelled
    auto.close()


# --- 順 -------------------------------------------------------------------------------------------------------- #
def _junban(monkeypatch, enabled=True, window=False, blocked=None):
    calls = []
    fake = types.ModuleType("modules.junban.auto")
    fake.enabled = lambda settings: enabled
    fake.blocked = lambda settings, window=True: blocked
    fake.window_open = lambda: window
    fake.run_quietly = lambda settings, list_current=None, job=None: (
        calls.append((settings["target_language"], list_current)) or "順 (automatic): 12 cards moved")
    monkeypatch.setitem(sys.modules, "modules.junban.auto", fake)
    return calls


def test_junban_runs_after_a_generate_and_on_focus_at_most_every_five_minutes(live, monkeypatch):
    """`_maybe_junban_auto`: forced after a Generate that wrote the list, else every 5 minutes on focus; a `junban`
    job; the settings written first; its line in the state."""
    calls = _junban(monkeypatch)
    settings = _settings(anki_sync_auto=False)
    clock = _Clock(0.0)
    auto, registry, controller, launches = _make(settings, clock=clock, journey=lambda s, l: True)
    for _ in range(10):
        auto.activated()
    _settle(auto, registry)
    assert calls == [("ja", True)] and settings.flushes == 1
    assert auto.state().junban == "順 (automatic): 12 cards moved"
    clock.now = 10.0
    auto.activated()
    _settle(auto, registry)
    assert len(calls) == 1
    run = controller.request("ja", argv=["analyzer.py", "--progress-json"], launcher=launches, settle=0)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    run.ended(0)
    assert h.until(lambda: len(calls) == 2, seconds=5), "forced after the Generate"
    _settle(auto, registry)
    assert [v.kind for v in registry.snapshot()].count("junban") == 2
    auto.close()


@pytest.mark.parametrize("why", ["absent", "off", "blocked", "window", "update-staged"])
def test_junban_held_back_writes_nothing_and_the_service_runs(live, monkeypatch, why):
    """順 absent (RD-S10), switched off, blocked by its own guards, its window open (a lock look on the worker), an
    update waiting: nothing written; the sync still runs."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch, added=0)
    if why == "absent":
        monkeypatch.setitem(sys.modules, "modules.junban.auto", None)
        calls = []
    else:
        calls = _junban(monkeypatch, enabled=why != "off", window=why == "window",
                        blocked="順 is switched off" if why == "blocked" else None)
    auto, registry, _c, _l = _make(_settings(), staged=lambda: why == "update-staged")
    auto.activated()
    _settle(auto, registry)
    assert calls == []
    assert len(anki.syncs) == (0 if why == "update-staged" else 1)
    auto.close()


def test_backlog_read_before_a_generate_only_with_decks(live, monkeypatch):
    """`_maybe_backlog_sync`: the decks' new cards beside a Generate; nothing without decks, or with it off."""
    anki = _Anki(monkeypatch)
    settings = _settings()
    auto, registry, _c, _l = _make(settings)
    auto.before_generate()
    _settle(auto, registry)
    assert anki.backlogs == [("ja", ("Mining",))]
    settings.values["anki_sync_decks"] = {}
    auto.before_generate()
    settings.values.update(anki_sync_decks={"ja": ["Mining"]}, anki_backlog_on_generate=False)
    auto.before_generate()
    _settle(auto, registry)
    assert len(anki.backlogs) == 1
    auto.close()


def test_close_leaves_nothing(live, monkeypatch):
    """After `close`: no alarm, no start timer, no trigger acting, the controller's listener gone."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch)
    clock = _Clock(0.0)
    timers = _Timers()
    auto, registry, controller, launches = _make(_settings(), clock=clock, timers=timers)
    auto.generate._last = -100.0
    auto.started()
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert auto.worker.idle(5)
    assert len(timers.live()) == 2
    auto.close()
    assert timers.live() == []
    auto.activated()
    auto.language_changed("ja")
    assert anki.syncs == [] and launches.count() == 0
    assert auto._ended not in controller._end_listeners


def test_triggers_return_at_once_and_read_nothing(live, monkeypatch):
    """The window's thread never waits: a trigger only queues (the worker is held here, so a read would hang)."""
    h.seed_library("ja")
    auto, registry, _c, _l = _make(_settings())
    hold = threading.Event()
    auto.worker.put(hold.wait, 10)
    for call in (auto.started, auto.activated, lambda: auto.language_changed("zh"), auto.before_generate,
                 auto.update_cancelled):
        _result, ms = h.timed(call)
        assert ms < 50, ms
    hold.set()
    _settle(auto, registry)
    auto.close()


# --- the intent keeper's list (IK-4, IK-10, IK-11) ------------------------------------------------------------- #
def test_recheck_asks_the_journey_once_for_a_burst(live, monkeypatch):
    """`_schedule_journey_state`: focus and an indexer's end (the window wires the chores' `on_indexed` to `recheck`)
    ask the Generate button's question once, 0.6 s after the last; never under the test switch; nothing after close."""
    checks = []
    timers = _Timers()
    auto, registry, controller, _l = _make(_settings(anki_sync_auto=False), timers=timers)
    monkeypatch.setattr(controller, "check", lambda settings, language, then=None: checks.append(language))
    for _ in range(10):
        auto.activated()
        auto.recheck()
    assert auto.worker.idle(5)
    armed = [t for t in timers if t.delay == A.CHECK_SETTLE and not t.cancelled]
    assert len(armed) == 1
    armed[0].call()
    assert auto.worker.idle(5) and checks == ["ja"]
    monkeypatch.setenv("SURASURA_NO_UI_TIMERS", "1")
    before = len(timers)
    auto.recheck()
    assert len(timers) == before
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    auto.recheck()
    auto.close()
    assert timers[-1].cancelled, "the recheck armed last is taken back"


def test_an_update_waiting_holds_every_automatic_start(live, monkeypatch):
    """`updater.children_held()` (K75), the `update_staged` callable: no sync, no Generate, no 順 — whatever asks."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch)
    calls = _junban(monkeypatch)
    timers = _Timers()
    auto, registry, controller, launches = _make(_settings(), staged=lambda: True, timers=timers)
    auto.started()
    for t in list(timers):
        t.call()
    auto.activated()
    auto.language_changed("ja")
    auto.worker.put(auto.generate.known_words_changed, "ja")
    auto.worker.put(auto.junban.maybe, True)
    auto.update_cancelled()
    _settle(auto, registry)
    assert anki.syncs == [] and calls == [] and launches.count() == 0
    assert not [v for v in registry.snapshot() if v.kind in ("anki-sync", "junban", "generate")]
    auto.close()


def test_japanese_words_wait_through_a_chinese_generate(live):
    """main.py's `_auto_generate_pending == self.var_language.get()`: words Anki brought for Japanese are not used up
    by a Chinese Generate; they run once Japanese is open again."""
    auto, registry, controller, launches = _make(_settings(), lang="zh")
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert auto.worker.idle(5)
    run = controller.request("zh", argv=["analyzer.py", "--progress-json"], launcher=launches, settle=0)
    assert h.until(lambda: launches.count() == 1, seconds=5)
    run.ended(0)
    assert h.until(lambda: controller.state().state == G.CURRENT, seconds=5)
    assert auto.worker.idle(5)
    assert auto.generate.pending == "ja" and launches.count() == 1
    auto.language_changed("ja")
    assert h.until(lambda: launches.count() == 2, seconds=5)
    assert launches.runs[1].quiet and launches.runs[1].language == "ja"
    launches.runs[1].ended(0)
    auto.close()


def test_a_second_program_writing_known_words_is_never_written_across(live, monkeypatch):
    """The registry is this process's; the Tk dashboard (or the command line) open at once is kept apart by the lock
    both take — `known-words-<lang>` (`anki_sync.hold_known_words`): the sync is refused, KnownWord.json untouched,
    the bar names the other program."""
    h.seed_library("ja")
    _synced_once("ja")
    monkeypatch.setattr(anki_connect, "probe", lambda url, *a, **k: {"ok": True})
    monkeypatch.setattr(anki_sync, "sync_backlog", lambda *a, **k: None)
    monkeypatch.setattr(anki_sync, "KNOWN_LOCK_WAIT", 0.3)
    path = os.path.join(h.root(), "User Files", "ja", "KnownWord.json")
    before = open(path, "rb").read()
    auto, registry, _c, launches = _make(_settings())
    with h.Holder(anki_sync.known_lock_name("ja"), "the Anki window"):
        auto.activated()
        _settle(auto, registry)
    state = auto.state()
    assert state.sync == A.FAILED and "the Anki window" in (state.message or "")
    assert open(path, "rb").read() == before and launches.count() == 0
    job = [v for v in registry.snapshot() if v.kind == "anki-sync"][0]
    assert job.state == J.FAILED and job.on_quit == "detach", "read-only on Anki: closing never waits for it"
    auto.close()


@pytest.mark.parametrize("guard", ["panel-open", "reviewing", "all-decks", "list-stale", "ok"])
def test_junbans_own_guards_hold(live, monkeypatch, guard):
    """The real `modules/junban/auto.py` (IK-4): its panel open in another program (the `junban-window` lock), the user
    reviewing in Anki, *All decks* chosen, the list behind — no write reaches Anki; with none of them, one."""
    pytest.importorskip("modules.junban.auto")
    from modules.junban import ankiconnect as junban_anki
    from modules.junban import reposition
    writes = []
    monkeypatch.setattr(junban_anki, "probe", lambda url, *a, **k: {"ok": True})
    monkeypatch.setattr(junban_anki, "invoke", lambda action, url, timeout=None, **k: guard == "reviewing"
                        if action == "guiReviewActive" else None)
    monkeypatch.setattr(reposition, "run", lambda settings, **k: writes.append(settings.get("junban_deck")) or
                        {"ok": True, "written": 3, "message": "3 cards moved"})
    # W3.5 row 7: 順's own re-order runs only where the re-order host can't (Coverage) and to the deck recorded for
    # this language (Haya G3) — so both are set, and every guard below is still Junban's own.
    settings = _settings(anki_sync_auto=False, enable_junban=True, junban_auto_reorder=True,
                         junban_scope="all" if guard == "all-decks" else "deck", junban_deck="Mining",
                         strategy="coverage", **RECORDED_JA)
    auto, registry, _c, _l = _make(settings, journey=lambda s, l: guard != "list-stale")
    if guard == "panel-open":
        with h.Holder("junban-window", "順"):
            auto.worker.put(auto.junban.maybe, True)
            _settle(auto, registry)
    else:
        auto.worker.put(auto.junban.maybe, True)
        _settle(auto, registry)
    assert writes == (["Mining"] if guard == "ok" else [])
    if guard == "ok":
        assert auto.state().junban == "順 (automatic): 3 cards moved"
        assert [v.on_quit for v in registry.snapshot() if v.kind == "junban"] == ["wait"]
    auto.close()


# --- W3.5 worker K: the Haiku mutant list's survivors ------------------------------------------------------------ #
def test_started_after_close_arms_no_start_timer(live):
    """`started()` once closed (a late call from a closing window): no start timer — `close()` leaves nothing behind
    to sync."""
    timers = _Timers()
    auto, registry, _c, _l = _make(_settings(), timers=timers)
    auto.close()
    auto.started()
    assert timers == []


def test_after_close_focus_arms_no_journey_check(live):
    """`close()` marks the service closed: a focus or a recheck after it arms no timer (nothing acts on a gone
    window)."""
    timers = _Timers()
    auto, registry, _c, _l = _make(_settings(anki_sync_auto=False), timers=timers)
    auto.close()
    auto.activated()
    auto.recheck()
    assert timers == []


def test_a_generate_check_queued_before_close_sets_no_alarm_after_it(live):
    """`_arm`'s closed check: the worker still runs what was queued before `close()`; a Generate check inside the
    10-minute limit then arms no alarm that would outlive the window."""
    clock = _Clock(1000.0)
    timers = _Timers()
    auto, registry, controller, launches = _make(_settings(), clock=clock, timers=timers)
    auto.generate._last = 900.0                     # inside the limit: only an alarm could follow
    hold = threading.Event()
    auto.worker.put(hold.wait, 10)
    auto.worker.put(auto.generate.known_words_changed, "ja")
    auto.close()
    hold.set()
    assert auto.worker.idle(5)
    assert timers.live() == [] and launches.count() == 0


def test_a_stale_state_is_never_delivered_after_a_newer_one(live):
    """`publish`'s "only while it is the newest": a state made on another thread while a listener runs, then overtaken,
    is never delivered after the newer one — the bar never ends on a stale line."""
    auto, registry, _c, _l = _make(_settings(anki_sync_auto=False))
    heard, threads = [], []

    def listener(snap):
        heard.append(snap.junban)
        if snap.junban == "first":
            other = threading.Thread(target=auto.publish, kwargs={"junban": "stale"})
            other.start()
            threads.append(other)
            assert h.until(lambda: auto.state().junban == "stale", seconds=5)
            auto.publish(junban="newest")       # delivered now (this thread holds the delivery)
    auto.subscribe(listener)
    auto.publish(junban="first")
    threads[0].join(5)
    assert not threads[0].is_alive()
    assert heard == ["first", "newest"] and auto.state().junban == "newest"
    auto.close()


def test_the_sync_and_the_backlog_read_never_keep_the_window_at_quit_and_are_never_cancelled(live, monkeypatch):
    """Both only read Anki, and write their local files atomically under the known-words lock (temp + replace), so the
    exit may cut them; the Tk `on_closing` never waited for them. Closing the window waits for neither (`detach`: only
    a job writing Anki keeps it, E20's "a few seconds"), and the quit never marks one cancelled half-way — they have
    no cancel, so the update's wait list gives them no *Stop it* either."""
    entered, gate = threading.Event(), threading.Event()
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch, added=0)
    anki.gate = gate
    monkeypatch.setattr(anki_sync, "sync_backlog", lambda *a, **k: (entered.set(), gate.wait(10)))
    auto, registry, _c, _l = _make(_settings())
    auto.before_generate()
    auto.language_changed("ja")
    assert entered.wait(5) and h.until(lambda: anki.syncs, seconds=5)
    running = [v for v in registry.live() if v.kind in ("anki-sync", "anki-backlog")]
    assert sorted((v.kind, v.on_quit, v.can_cancel) for v in running) == [
        ("anki-backlog", "detach", False), ("anki-sync", "detach", False)]
    assert J.waits_at_quit(registry.snapshot()) == ()
    still = [v for v in registry.quit(timeout=0, wait_timeout=0) if v.kind in ("anki-sync", "anki-backlog")]
    assert sorted((v.kind, v.state, v.cancelled) for v in still) == [
        ("anki-backlog", J.RUNNING, False), ("anki-sync", J.RUNNING, False)]
    gate.set()
    _settle(auto, registry)
    assert all(v.state == J.DONE and not v.cancelled for v in registry.snapshot()
               if v.kind in ("anki-sync", "anki-backlog"))
    auto.close()


def test_a_sync_that_ends_after_a_language_switch_shows_the_open_languages_count(live, monkeypatch):
    """D31 (a language switch re-reads what it shows): a Japanese sync that ends after the user opened Chinese never
    puts Japanese's known count in the Chinese window's bar — the count shown is Chinese's."""
    h.seed_library("ja")
    h.seed_library("zh")
    _synced_once("ja")
    anki = _Anki(monkeypatch, added=2)
    anki.gate = threading.Event()
    auto, registry, _c, _l = _make(_settings(anki_auto_generate=False))
    auto.language_changed("ja")
    assert h.until(lambda: len(anki.syncs) == 1, seconds=5)
    auto.language_changed("zh")
    assert auto.worker.idle(5)
    zh = anki_sync.count_known("zh")
    assert zh != anki_sync.count_known("ja"), "two different counts"
    anki.gate.set()
    _settle(auto, registry)
    assert h.until(lambda: auto.worker.idle(0.05) and auto.state().known == zh, seconds=5), auto.state()
    auto.close()



def test_a_sync_that_ends_after_a_language_switch_never_shows_its_count_even_for_a_moment(live, monkeypatch):
    """S19 and D31 together: once Chinese is open, no state the window hears carries Japanese's count — not even one
    corrected a moment later (the bar's number would flicker to the wrong language's)."""
    h.seed_library("ja")
    h.seed_library("zh")
    _synced_once("ja")
    anki = _Anki(monkeypatch, added=2)
    anki.gate = threading.Event()
    auto, registry, _c, _l = _make(_settings(anki_auto_generate=False))
    auto.language_changed("ja")
    assert h.until(lambda: len(anki.syncs) == 1, seconds=5)
    auto.language_changed("zh")
    assert auto.worker.idle(5)
    zh = anki_sync.count_known("zh")
    heard = []
    auto.subscribe(lambda state: heard.append(state.known))
    anki.gate.set()
    _settle(auto, registry)
    assert auto.worker.idle(5)
    assert heard and set(heard) == {zh}, heard
    auto.close()


def test_a_switch_that_lands_while_a_sync_says_its_count_is_read_again_after_it(live, monkeypatch):
    """The narrow case: the sync saw its own language still open, and the switch (with its count read) lands just
    before the sync says Japanese's count. That count is the last word unless the open language's is read again after
    it."""
    h.seed_library("ja")
    h.seed_library("zh")
    _synced_once("ja")
    _Anki(monkeypatch, added=2)
    auto, registry, _c, _l = _make(_settings(anki_auto_generate=False))
    zh = anki_sync.count_known("zh")
    publish, switched = auto.publish, []

    def publish_after_a_switch(**changes):
        if changes.get("sync") == A.SYNCED and not switched:
            switched.append(1)
            with auto.lock:                                # the switch's first half: Chinese open, its count read
                auto.language = "zh"
            auto._read_known()
        publish(**changes)
    monkeypatch.setattr(auto, "publish", publish_after_a_switch)
    auto.language_changed("ja")
    assert h.until(lambda: switched, seconds=5)
    _settle(auto, registry)
    assert h.until(lambda: auto.worker.idle(0.05) and auto.state().known == zh, seconds=5), auto.state()
    auto.close()

def test_the_automatic_generate_launches_only_once_its_folders_are_set_up(live, monkeypatch):
    """`run_analyzer`'s order: the folders and word lists set up, then the run — a slow set-up (the 30-day .trash
    clean-up) is over before the analyzer starts, never raced by it."""
    from app import path_utils
    seen, holder = [], {}

    def slow_setup(language=None):
        time.sleep(0.3)
        seen.append(holder["launches"].count())
    monkeypatch.setattr(path_utils, "ensure_data_setup", slow_setup)
    auto, registry, controller, launches = _make(_settings())
    holder["launches"] = launches
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert h.until(lambda: launches.count() == 1, seconds=5)
    assert seen == [0]
    launches.runs[0].ended(0)
    auto.close()


def test_words_a_sync_brought_count_for_its_own_language_after_a_switch(live, monkeypatch):
    """`_on_anki_sync_result(result, language)`: a Japanese sync that ends after the user switched to Chinese leaves
    its words waiting for Japanese — no quiet Chinese Generate for words Chinese never got."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch, added=3)
    anki.gate = threading.Event()
    indexes = []
    auto, registry, controller, launches = _make(_settings(), indexes=indexes)
    auto.language_changed("ja")
    assert h.until(lambda: len(anki.syncs) == 1, seconds=5)
    auto.language_changed("zh")
    assert auto.worker.idle(5)
    anki.gate.set()
    _settle(auto, registry)
    assert auto.generate.pending == "ja"
    assert launches.count() == 0 and not registry.live("generate") and indexes == [1]
    auto.close()


# --- W3.5 row 7: 順's automatic reorder beside the re-order host (D29, Haya G3) ------------------------------------ #
def _junban_settings_seen(monkeypatch):
    """The fake `modules.junban.auto` with its real `enabled` rule (a step switched on); `run_quietly` keeps the
    settings it was given — which steps it would run."""
    seen = []
    fake = types.ModuleType("modules.junban.auto")
    fake.enabled = lambda settings: settings.get("enable_junban") is True and (
        settings.get("junban_auto_reorder") is True or settings.get("junban_auto_backfill") is True)
    fake.blocked = lambda settings, window=True: None
    fake.window_open = lambda: False
    fake.run_quietly = lambda settings, list_current=None, job=None: seen.append(dict(settings)) or ""
    monkeypatch.setitem(sys.modules, "modules.junban.auto", fake)
    from app import replan_preview
    # Junban installed, whatever this checkout holds (GitHub's has no `modules/`): the host's gate asks for it
    monkeypatch.setattr(replan_preview, "junban_present", lambda: True)
    return seen


RECORDED_JA = {"junban_replan_language": "ja", "junban_replan_deck": "Mining"}


@pytest.mark.parametrize("case, extra, reorders", [
    ("automation off (D29)", dict(RECORDED_JA, logic={"automation": False}, strategy="coverage"), False),
    ("the host re-orders this language", dict(RECORDED_JA), False),
    ("the deck is recorded for Chinese", {"junban_replan_language": "zh", "junban_replan_deck": "Mining",
                                          "strategy": "coverage"}, False),
    ("no deck recorded", {"strategy": "coverage"}, False),
    ("the host can't run here (Coverage), the deck recorded", dict(RECORDED_JA, strategy="coverage"), True),
])
def test_junbans_automatic_reorder_steps_aside_but_its_backfill_runs(live, monkeypatch, case, extra, reorders):
    """The map's fix 3 (W3.5 row 7): 2.5's automatic reorder never writes beside the re-order host (one re-order per
    Generate, as the Tk `_maybe_junban_auto` at main.py ~4171), never with automation off (D29: every automatic Anki
    write), and never to a deck recorded for another language, or none (Haya G3) — its Backfill runs all the same."""
    seen = _junban_settings_seen(monkeypatch)
    settings = _settings(anki_sync_auto=False, enable_junban=True, junban_auto_reorder=True, junban_auto_backfill=True,
                         junban_scope="deck", junban_deck="Mining", **extra)
    auto, registry, _c, _l = _make(settings)
    auto.worker.put(auto.junban.maybe, True)
    _settle(auto, registry)
    assert len(seen) == 1, case
    assert seen[0]["junban_auto_reorder"] is reorders, case
    assert seen[0]["junban_auto_backfill"] is True, case
    assert settings.values["junban_auto_reorder"] is True, "the user's own setting was changed"
    auto.close()


def test_with_its_reorder_set_aside_and_no_backfill_junban_starts_no_job(live, monkeypatch):
    """Nothing left to run (the host re-orders, Backfill off): no `junban` job at all — no empty write in the bar."""
    seen = _junban_settings_seen(monkeypatch)
    settings = _settings(anki_sync_auto=False, enable_junban=True, junban_auto_reorder=True, junban_scope="deck",
                         junban_deck="Mining", **RECORDED_JA)
    auto, registry, _c, _l = _make(settings)
    assert auto.junban.maybe(force=True) == "off"
    _settle(auto, registry)
    assert seen == [] and not [v for v in registry.snapshot() if v.kind == "junban"]
    auto.close()


def test_junbans_reorder_reads_the_deck_juns_own_window_recorded_behind_the_windows_settings(live, monkeypatch):
    """順 records the (language, deck) pair with its own `save_keys` — to settings.json, behind the window's settings
    service (its copy is read again only after the window's own writes). `reorders` reads the file on the worker, so
    the next automatic run sees the pick: before it, the re-order stands aside (no deck recorded); after it, with the
    host unable to run here (Coverage), 順's own re-order runs to that deck."""
    from app.services import settings as settings_service
    seen = _junban_settings_seen(monkeypatch)
    h.write_settings({"target_language": "ja", "anki_sync_auto": False, "enable_junban": True,
                      "junban_auto_reorder": True, "junban_auto_backfill": True, "junban_scope": "deck",
                      "junban_deck": "Mining", "strategy": "coverage"})
    service = settings_service.SettingsService()
    auto, registry, _c, _l = _make(service)
    auto.worker.put(auto.junban.maybe, True)
    _settle(auto, registry)
    assert seen[-1]["junban_auto_reorder"] is False                         # no deck recorded yet
    h.write_settings(dict(h.read_settings(), **RECORDED_JA))                # 順's own save, behind the service
    assert not service.get().get("junban_replan_deck")
    auto.worker.put(auto.junban.maybe, True)
    _settle(auto, registry)
    assert len(seen) == 2 and seen[-1]["junban_auto_reorder"] is True and seen[-1]["junban_replan_deck"] == "Mining"
    auto.close()


# --- the importers (W3.4 row 2) ---------------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["known-import", "extract"])
def test_the_automatic_generate_waits_for_an_import_or_an_extract(live, kind):
    """IK-54: the Tk tooltip's "never while … an import … is running" — a known-words import or an Extract is a child
    process the automatic Generate waits for, and asks again once it ends."""
    auto, registry, controller, launches = _make(_settings())
    child = registry.record(kind, "Known words from Migaku")
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert auto.worker.idle(5)
    assert launches.count() == 0 and not registry.live("generate")     # its launch is a worker's: the job tells
    child.finish(ok=True)
    assert h.until(lambda: launches.count() == 1, seconds=5), "the child's end asks again"
    for run in launches.runs:
        run.ended(0)
    auto.close()


def test_an_import_that_ended_reads_the_known_words_count_again(live):
    """IK-54: a replace took the list from many words to few; the bar's count follows at once, not at the next sync."""
    h.seed_library("ja")
    auto, _registry, _c, _l = _make(_settings(anki_auto_generate=False))
    auto.known_changed()
    assert h.until(lambda: auto.worker.idle(0.05) and auto.state().known == anki_sync.count_known("ja"), seconds=5)
    assert auto.state().known > 0
    auto.close()


def test_the_automatic_generate_waits_while_the_setup_wizard_is_up(live):
    """W3.5 part 3 (AD-8): no quiet Generate while the setup wizard is up (its last page sets the level); its close asks
    again (the window's `setup_ended` → `activated`)."""
    up = [True]
    auto, registry, controller, launches = _make(_settings())
    auto.held = lambda: up[0]
    auto.worker.put(auto.generate.known_words_changed, "ja")
    assert auto.worker.idle(5)
    assert launches.count() == 0 and not registry.live("generate")
    assert auto.generate.pending == "ja"                          # the words wait, never dropped
    up[0] = False
    auto.activated()
    assert h.until(lambda: launches.count() == 1, seconds=5)
    launches.runs[0].ended(0)
    auto.close()


# --- a sync by hand ends as the automatic one does (row 30) ------------------------------------------------------- #
def _by_hand(auto, registry, result, language="ja"):
    """The Anki window's *Sync now* (and the setup wizard's first sync): `anki_window.submit` with the real service."""
    from app import anki_window as AW
    done = threading.Event()
    AW.submit(registry, "Syncing", lambda: result, lambda r: done.set(), auto, language)
    assert done.wait(10), "the job ended"
    assert auto.worker.idle(5)


@pytest.mark.parametrize("auto_generate", [True, False])
def test_a_sync_by_hand_ends_on_the_automatic_syncs_own_path(live, monkeypatch, auto_generate):
    """Row 30: *Sync now* told `Automation.anki_synced`, which didn't exist; the error was swallowed, so a sync by hand
    ran no quiet Generate, started no indexer, never said the bar's new count and never restarted the 5-minute wait.
    Every sync, by hand or automatic, now ends through `AutoSync.ended`."""
    h.seed_library("ja")
    _synced_once("ja")
    anki = _Anki(monkeypatch)
    clock, indexes = _Clock(1000.0), []
    auto, registry, _c, launches = _make(_settings(anki_auto_generate=auto_generate), clock=clock, indexes=indexes)
    known = anki_sync.count_known("ja")
    _by_hand(auto, registry, anki_sync.SyncResult(added=4, total_known=known + 4, mode="delta"))
    state = auto.state()
    assert (state.sync, state.added, state.known) == (A.SYNCED, 4, known + 4), "the bar says the new count"
    if auto_generate:
        assert h.until(lambda: launches.count() == 1, seconds=10) and indexes == [], "the quiet Generate"
        launches.runs[0].ended(0)
    else:
        assert indexes == [1] and launches.count() == 0, "no Generate: the indexer"
    clock.now = 1000.0 + A.SYNC_EVERY - 1
    auto.activated()
    _settle(auto, registry)
    assert anki.syncs == [], "the 5-minute wait counts from the sync by hand"
    clock.now = 1000.0 + A.SYNC_EVERY
    auto.activated()
    _settle(auto, registry)
    assert len(anki.syncs) == 1
    auto.close()


def test_a_sync_by_hand_that_failed_says_so_and_asks_for_nothing(live, monkeypatch):
    h.seed_library("ja")
    indexes = []
    auto, registry, _c, launches = _make(_settings(), indexes=indexes)
    _by_hand(auto, registry, anki_sync.SyncResult(error="Anki refused the request"))
    assert (auto.state().sync, auto.state().message) == (A.FAILED, "Anki refused the request")
    assert indexes == [] and launches.count() == 0
    auto.close()


def _stand_in_methods():
    """Every test stand-in of the automation service: a class named for it, or a `type(...)` set as `.automation`
    (or handed in as `automation=`) — and the methods each defines itself."""
    import ast
    import glob
    root = os.path.dirname(os.path.abspath(__file__))
    found = []
    for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        name = os.path.relpath(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "Automation" in node.name:
                found.append((f"{name}::{node.name}", [n.name for n in node.body
                                                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]))
            elif isinstance(node, ast.Assign) and any(getattr(t, "attr", getattr(t, "id", "")) == "automation"
                                                      for t in node.targets):
                made = node.value
                if isinstance(made, ast.Call) and isinstance(made.func, ast.Call):
                    made = made.func                                # type(...)(): the class, then its one object
                if isinstance(made, ast.Call) and getattr(made.func, "id", None) == "type" and len(made.args) == 3 \
                        and isinstance(made.args[2], ast.Dict):
                    found.append((f"{name}:{node.lineno}", [k.value for k in made.args[2].keys
                                                            if isinstance(k, ast.Constant)]))
    return found


def test_every_stand_in_of_the_automation_service_has_only_its_real_methods():
    """Row 30's guard: a stand-in that answers a method the real `Automation` lacks hides a call that fails for the
    user (swallowed, as `anki_synced` was). Every stand-in's own public method must be the real service's."""
    found = _stand_in_methods()
    assert len(found) >= 4, f"the scan finds the stand-ins: {found}"
    wrong = [(where, m) for where, methods in found for m in methods
             if not m.startswith("_") and not callable(getattr(A.Automation, m, None))]
    assert wrong == [], f"stand-ins answering what Automation lacks: {wrong}"


def test_a_sync_by_hand_with_no_language_named_is_the_windows_language_and_nothing_once_closed(live, monkeypatch):
    """Row 30 (planted-bug pass): the setup wizard's first sync names no language — its end is the window's language's;
    and a sync by hand that ends after the window closed tells the closed service nothing (no bar, no queued work)."""
    h.seed_library("ja")
    auto, _registry, _c, _launches = _make(_settings())
    ended = []
    monkeypatch.setattr(auto.sync, "ended", lambda *a, **k: ended.append(a))
    result = anki_sync.SyncResult(added=1, total_known=1, mode="delta")
    auto.anki_synced(result, None)
    assert ended == [(result, auto.language)], "no language named: the window's"
    auto.anki_synced(result, "zh")
    assert ended[-1] == (result, "zh"), "a language named: that one (D31)"
    auto.close()
    auto.anki_synced(result, "ja")
    assert len(ended) == 2, "closed: nothing"
