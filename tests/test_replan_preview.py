"""The fast re-plan's preview (app/replan_preview.py; E1.1-fast-replan/04-preview.md, RUNBOOK E3.1.2–E3.1.4).

On a real library (tests/plan_file_cases.py's RP-2 Japanese library: twelve files of real text across NOW, Soon and
6+ Months), generated once per test with the preview on (so the plan file is written), its library store as the
Generate left it, and a fake AnkiConnect holding one new card per word of the library's own list (the Junban suite's
`ModCollection`: real state, every write checked under the 999,999 ceiling). What these tests prove:

  - a move in the store → one job → the engine's re-plan → Junban's spaced delta: tomorrow's cards in the first
    requests, the moved content's words first, `record_planned` with the versions read before the order;
  - the parity that matters to a learner: after the job, the next full Generate's own re-order writes nothing — Anki
    already holds the order the Generate's list gives (05 §1, through Junban);
  - the settle (two quick moves → one job; a move during a job → one more), the close (a pending settle runs at
    once), and every 04 §4 case's line: Anki closed, a review, 順's window open, no plan, new files, known words;
  - the dashboard's catch-up and its automatic Generate (asked for moves, a missing plan; never for new files alone);
  - RP-10: a sub-floor word's file number read through the new order;
  - shadow mode (05 §3): an injected difference writes one line; none, no line.
"""
import csv
import json
import os
import threading
import time

import pytest

pytest.importorskip("modules.junban")

from app import analyzer, anki_sync_rule, library_store, plan_engine, replan_preview  # noqa: E402
from modules.junban import reposition, spaced, undo  # noqa: E402
from modules.junban.tests.test_reposition import _collection, _patched  # noqa: E402
from modules.junban.tests.test_spaced_runs import ModCollection  # noqa: E402
from tests import plan_file_cases as cases  # noqa: E402

CASE = "rp2-ja"
DECK = "TheBank"
URL = "http://127.0.0.1:18765"      # nothing listens here: only the patched transport answers (never Anki's own port)


class SyncCollection(ModCollection):
    """The fake collection, plus `sync` (E1.1 04 §3): counted; refused like AnkiConnect's when not signed in."""

    def __init__(self, *args, signed_in=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.signed_in = signed_in
        self.syncs = 0

    def _dispatch(self, action, params):
        if action == "sync":
            from modules.junban.tests.test_reposition import AnkiRefusal
            if not self.signed_in:
                return AnkiRefusal("sync: auth not configured")
            self.syncs += 1
            return None
        return super()._dispatch(action, params)


# --------------------------------------------------------------------------------------------------------------- #
# The library
# --------------------------------------------------------------------------------------------------------------- #

def _settings_file(root, **over):
    # 3.0: the host runs when 順 recorded the (language, deck) pair (its deck save does: W3.5 row 7) — the box is
    # 2.x's and kept on here only so the 2.x tests read the same.
    settings = {"junban_replan_preview": True, "junban_deck": DECK, "junban_scope": "deck",
                "junban_replan_language": "ja", "junban_replan_deck": DECK,
                "junban_order": "content", "anki_connect_url": URL, "target_language": "ja"}
    settings.update(over)
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)


def _generate(root):
    """A full Generate as the dashboard starts it (`run_args.analyzer_args`: its context arguments too), so the run
    signature the preview computes in this process is the run's."""
    from app import run_args
    with open(os.path.join(root, "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    cases.generate(root, CASE, argv=run_args.analyzer_args(settings, "ja", headless=True)[1:])


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """A generated library with the preview on, this test's data root: (root, store)."""
    root = str(tmp_path / "lib")
    env = cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, env[name])
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    cases.needs_junban()                         # the preview needs Junban (3.0: the plan doesn't)
    cases.build(root, CASE)
    _settings_file(root)
    from app.path_utils import ensure_data_setup
    ensure_data_setup("ja")                      # what every window's open makes sure of (the word lists' files)
    _generate(root)
    from app.path_utils import get_data_path, get_user_files_path
    store = library_store.open_store("ja", get_data_path("ja"), get_user_files_path("ja"))
    assert store is not None, "the Generate left no library store"
    yield root, store
    store.close()


def _list_words(root, n=None):
    """The library's own list in Junban's order (the progressive list), each as the word a card carries."""
    with open(os.path.join(root, "results", "progressive_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    seen = []
    for row in rows:
        word, orth = (row.get("Word") or "").strip(), (row.get("Orth") or "").strip()
        key = orth or word
        if len(key) == 1 and key != word:
            key = word
        if key and key not in seen:
            seen.append(key)
    return seen[:n] if n else seen


def _deck(root, n=60, **kwargs):
    """One new card per list word (the first `n`), queued in the REVERSE of the list's order, dense as 2.5 left it."""
    words = _list_words(root, n)
    dues = list(range(3000 + len(words) - 1, 2999, -1))
    cards, notes, _ = _collection(words, dues=dues, deck=DECK)
    return SyncCollection(cards, notes)


def _ids(store, tier):
    return store.ids(tier)


def _host(**kwargs):
    lines = []
    host = replan_preview.Host("ja", say=lines.append, **kwargs)
    return host, lines


def _move_later_to_top(store):
    """A move in the Content Manager: 6+ Months' last item to the top of NOW."""
    item = _ids(store, "goal")[-1]
    store.move([item], "now", before_id=_ids(store, "now")[0])
    return item


def _word_cards(fake, words):
    by_word = {}
    for card in fake.cards.values():
        note = fake.notes[card["note"]]
        by_word[next(iter(note["fields"].values()))["value"]] = card["cardId"]
    return [by_word[w] for w in words if w in by_word]


# --------------------------------------------------------------------------------------------------------------- #
# The switch and what it needs
# --------------------------------------------------------------------------------------------------------------- #

def test_the_switch_is_on_only_with_junban_on_and_it_names_why_it_cant_run():
    on = {"junban_replan_preview": True, "enable_junban": True}
    assert replan_preview.is_on(on)
    assert not replan_preview.is_on(dict(on, junban_replan_preview=False))
    assert not replan_preview.is_on(dict(on, enable_junban=False))
    assert not replan_preview.is_on({"junban_replan_preview": "true", "enable_junban": True})   # True only
    deck = dict(on, junban_scope="deck", junban_deck="TheBank")
    assert replan_preview.unavailable(deck) is None
    assert "one deck" in replan_preview.unavailable(dict(deck, junban_scope="all"))
    assert "one deck" in replan_preview.unavailable(dict(deck, junban_deck=" "))
    assert "Coverage" in replan_preview.unavailable(dict(deck, strategy="coverage"))
    assert "i+1" in replan_preview.unavailable(dict(deck, only_i_plus_one=True))


def test_without_junban_the_preview_is_off_whatever_settings_json_says(monkeypatch):
    """Junban removed (RD-S10): `is_on` asks for the package without importing it, and says no."""
    monkeypatch.setattr(replan_preview, "junban_present", lambda: False)
    assert not replan_preview.is_on({"junban_replan_preview": True, "enable_junban": True})


# --------------------------------------------------------------------------------------------------------------- #
# 3.0's gate (W3.5 row 7; Haya's G2a / G3): D29, Junban, D7, and the recorded (language, deck) pair
# --------------------------------------------------------------------------------------------------------------- #

ON_3_0 = {"enable_junban": True, "junban_scope": "deck", "junban_deck": DECK,
          "junban_replan_language": "ja", "junban_replan_deck": DECK}


def test_on_3_0_the_host_runs_with_d29_on_junban_on_one_deck_and_the_pair_recorded():
    """Every condition holds: the host may run, and the deck it may write to is the recorded one."""
    assert replan_preview.stands_aside(ON_3_0, "ja") is None
    assert replan_preview.automation_on(ON_3_0, "ja") is True
    assert replan_preview.recorded_deck(ON_3_0, "ja") == DECK


def test_on_3_0_the_previews_box_is_never_read():
    """2.x-dev keeps `is_on` False with 順's box off (test_the_switch_is_on_only_with_junban_on_and_it_names_why_it_cant_run);
    3.0: D29 is the one switch, so the box — on, off or never written — changes nothing (W3.4 removes it)."""
    for box in (True, False, None, "true"):
        settings = dict(ON_3_0, junban_replan_preview=box)
        assert replan_preview.automation_on(settings, "ja") is True, box


@pytest.mark.parametrize("logic,on", [
    ({"automation": False}, False),
    ({}, True),                                       # absent: on (the default)
    ({"automation": True}, True),
    (None, True),                                     # a malformed block never turns it off
])
def test_d29_off_stands_the_host_aside_and_says_automation_is_off(logic, on):
    """D29 (`logic.automation`): only False stands the host aside; read through `settings_manager.automation`."""
    settings = dict(ON_3_0, logic=logic)
    assert replan_preview.automation_on(settings, "ja") is on
    assert replan_preview.stands_aside(settings, "ja") == (None if on else replan_preview.AUTOMATION_OFF)


def test_junban_off_or_absent_stands_the_host_aside(monkeypatch):
    """Junban switched off (or the key missing: `enable_junban is True` only), or removed (RD-S10)."""
    for value in (False, None, "true"):
        settings = dict(ON_3_0, enable_junban=value)
        assert replan_preview.stands_aside(settings, "ja") == replan_preview.JUNBAN_OFF, value
    settings = dict(ON_3_0)
    del settings["enable_junban"]
    assert not replan_preview.automation_on(settings, "ja")
    monkeypatch.setattr(replan_preview, "junban_present", lambda: False)
    assert replan_preview.stands_aside(ON_3_0, "ja") == replan_preview.JUNBAN_ABSENT
    assert not replan_preview.automation_on(ON_3_0, "ja")


def test_what_d7_rules_out_is_said_in_its_own_words():
    """All decks, Coverage, Only i+1: `unavailable`'s reasons, returned as they are."""
    for change, words in (({"junban_scope": "all"}, "one deck"), ({"strategy": "coverage"}, "Coverage"),
                          ({"only_i_plus_one": True}, "i+1")):
        settings = dict(ON_3_0, **change)
        assert replan_preview.stands_aside(settings, "ja") == replan_preview.unavailable(settings)
        assert words in replan_preview.stands_aside(settings, "ja")
        assert not replan_preview.automation_on(settings, "ja")


def test_with_no_pair_recorded_the_host_stands_aside_and_names_the_deck_and_language():
    """G3: never `preview_language`'s "" → "ja" default. With nothing recorded, `junban_deck` can be a Chinese deck
    last picked in a Chinese 順 window, and a Japanese host would re-order it by the Japanese plan."""
    for missing in ("junban_replan_language", "junban_replan_deck"):
        settings = dict(ON_3_0)
        del settings[missing]
        assert replan_preview.recorded_deck(settings, "ja") is None, missing
        line = replan_preview.stands_aside(settings, "ja")
        assert DECK in line and "isn't recorded for Japanese" in line and "順's window in Japanese" in line, line
    blank = dict(ON_3_0, junban_replan_language=" ", junban_replan_deck="")
    assert replan_preview.recorded_deck(blank, "ja") is None


def test_a_pair_recorded_for_chinese_never_lets_a_japanese_host_reorder_that_deck():
    """The hazard (2.x review 3 R3/R4): 順's deck was picked in its Chinese window; the Japanese window stands aside and
    says the deck is Chinese's, while the Chinese window's host may run."""
    zh = dict(ON_3_0, junban_deck="中文", junban_replan_language="zh", junban_replan_deck="中文")
    assert replan_preview.recorded_deck(zh, "ja") is None
    line = replan_preview.stands_aside(zh, "ja")
    assert "中文" in line and "recorded for Chinese" in line and "順's window in Japanese" in line, line
    assert replan_preview.stands_aside(zh, "zh") is None
    assert replan_preview.recorded_deck(zh, "zh") == "中文"


def test_a_recorded_deck_that_isnt_juns_deck_now_stands_aside():
    """順's deck changed since the pair was recorded (a hand edit, another program): the deck written to must be the
    recorded one, so the host stands aside and names 順's deck now."""
    settings = dict(ON_3_0, junban_deck="中文")
    assert replan_preview.recorded_deck(settings, "ja") is None
    line = replan_preview.stands_aside(settings, "ja")
    assert "中文" in line and "isn't recorded for Japanese" in line, line
    assert not replan_preview.automation_on(settings, "ja")


def test_the_pair_is_read_with_case_and_spaces_forgiven_and_from_a_frozen_copy():
    """The recorded language normalised, the decks stripped; the settings service's frozen mapping reads the same."""
    from types import MappingProxyType
    settings = dict(ON_3_0, junban_replan_language=" JA ", junban_replan_deck=f" {DECK} ", junban_deck=f"{DECK} ")
    assert replan_preview.recorded_deck(settings, "ja") == DECK
    frozen = MappingProxyType(dict(ON_3_0, logic=MappingProxyType({"automation": False})))
    assert replan_preview.stands_aside(frozen, "ja") == replan_preview.AUTOMATION_OFF
    assert replan_preview.automation_on(MappingProxyType(dict(ON_3_0)), "ja") is True


def test_the_reasons_come_in_order_d29_junban_d7_then_the_deck(monkeypatch):
    """One line, the first that holds: D29 off → Junban off → D7 → the pair."""
    everything = dict(ON_3_0, logic={"automation": False}, enable_junban=False, junban_scope="all",
                      junban_replan_language="zh")
    assert replan_preview.stands_aside(everything, "ja") == replan_preview.AUTOMATION_OFF
    everything["logic"] = {}
    assert replan_preview.stands_aside(everything, "ja") == replan_preview.JUNBAN_OFF
    everything["enable_junban"] = True
    assert "one deck" in replan_preview.stands_aside(everything, "ja")
    everything["junban_scope"] = "deck"
    assert "recorded for Chinese" in replan_preview.stands_aside(everything, "ja")


# --------------------------------------------------------------------------------------------------------------- #
# A move → the job
# --------------------------------------------------------------------------------------------------------------- #

def test_a_move_reorders_anki_from_the_engine_tomorrows_cards_first_and_records_the_plan(lib):
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")                    # switched on: the first job lays the ladder (every card once)
        assert fake.syncs == 1                   # S1: the session's first write synced first
        first = fake.queue()
        versions = store.versions()
        assert versions["planned_order_version"] == versions["order_version"]
        moved = _move_later_to_top(store)
        fake.write_requests.clear()
        host._job("move")
        after = fake.queue()
        # What Junban plans from the engine's rows for this order, read back (no write): Anki already holds it.
        rows = host._engine.result().rows("content")
        writes, stats = reposition.dry_run(_junban_settings(), job=spaced.Job(automatic=True, rows=rows))
    assert after != first, "the move changed nothing in Anki"
    assert not writes, "the job left cards where the plan doesn't put them"
    planned = [row.card_id for row in stats["order"]]
    assert after[:20] == planned[:20], "Anki's first 20 new cards are the plan's first 20"
    # The moved file's own words lead the engine's progressive list now.
    moved_file = store.item(moved)["rel_path"].rsplit("/", 1)[-1]
    assert rows[0]["Source File"].replace("\\", "/").rsplit("/", 1)[-1] == moved_file
    # Tomorrow's cards went in the first request(s); a move writes tens of cards, not the deck.
    assert fake.write_requests, "no write"
    written = sum(len(batch) for batch in fake.write_requests)
    assert written < len(fake.cards)
    assert store.versions()["planned_order_version"] == store.versions()["order_version"]
    assert lines[-1].startswith("Anki: tomorrow's 20 cards placed") or lines[-1].startswith("Anki: ")
    assert moved in _ids(store, "now")


def _junban_settings():
    from app import settings_manager
    settings = dict(settings_manager.load_settings())
    settings["target_language"] = "ja"
    return settings


def test_a_missing_item_keeps_the_run_current_for_the_preview(lib):
    """The 3.0 line (E2.2's K2): an item whose file is gone from the disk keeps counting until the user decides, so
    Generate and the journey checks sign the library with it (`resolve_found_files(..., missing=True)`). The preview
    signs it the same way — else, after every Generate, it read the run as stale and asked for a Generate again."""
    root, store = lib
    from app import plan_rules, settings_manager
    from app.path_utils import get_data_path, get_user_file, get_user_files_path
    entry = store.schedule()[library_store.TIERS["goal"][0]][0]
    os.remove(os.path.join(get_data_path("ja"), entry["physical_path"]))
    store.close()
    _generate(root)                              # the Generate keeps the missing item (its cached words)
    store = library_store.open_store("ja", get_data_path("ja"), get_user_files_path("ja"))
    try:
        host, _lines = _host()
        parts = host._parts(dict(settings_manager.load_settings()), store)
    finally:
        store.close()
    assert plan_rules.signature_digest(parts) == analyzer.read_run_stamp(get_user_file("results"))


def test_after_the_job_the_next_generate_reorders_nothing(lib):
    """The parity a learner feels (05 §1 through Junban): the fast path left Anki where the next full Generate's own
    list puts it — the after-Generate re-order, from the new plan, writes no card."""
    root, store = lib
    fake = _deck(root)
    host, _lines = _host()
    with _patched(fake):
        host._job("catch-up")
        _move_later_to_top(store)
        host._job("move")
        before = dict((card_id, card["due"]) for card_id, card in fake.cards.items())
    store.close()
    _generate(root)                              # the Generate of the moved order (the store is the source)
    fake.write_requests.clear()
    host2, lines2 = _host()
    with _patched(fake):
        host2._job("generate")
    assert not fake.write_requests, f"the Generate's list moved cards the fast path had placed: {lines2}"
    assert {card_id: card["due"] for card_id, card in fake.cards.items()} == before


def test_no_move_owed_reads_nothing_and_writes_nothing(lib, monkeypatch):
    root, store = lib
    fake = _deck(root)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
        fake.requests.clear()
        stats = []
        monkeypatch.setattr(host, "_parts", lambda *a: stats.append(1))
        host._job("move")
    assert not fake.requests and not stats, "a settle with nothing owed asked Anki or stat'd the library"


# --------------------------------------------------------------------------------------------------------------- #
# The settle, the worker, the close (04 §2.2, §2.5)
# --------------------------------------------------------------------------------------------------------------- #

def test_two_quick_moves_make_one_job_and_a_move_during_a_job_makes_one_more(lib, monkeypatch):
    root, store = lib
    monkeypatch.setattr(replan_preview, "SETTLE_S", 0.15)
    jobs, gate, started = [], threading.Event(), threading.Event()
    host, _ = _host()

    def job(kind):
        jobs.append(kind)
        started.set()
        gate.wait(5)
    monkeypatch.setattr(host, "_job", job)
    host.poke()
    host.poke()                                  # within the settle: the same job
    deadline = time.monotonic() + 5
    while not started.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert jobs == ["move"]
    host.poke()                                  # during the job: one more, after it
    host.poke()
    gate.set()
    deadline = time.monotonic() + 5
    while (len(jobs) < 2 or host.busy()) and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.3)
    assert jobs == ["move", "move"]
    host.stop()


def test_each_move_restarts_the_settle(lib, monkeypatch):
    """04 §2.2: the job waits for the moves to settle — a second move inside the settle pushes it back, so a burst of
    moves runs once, after the last."""
    root, store = lib
    monkeypatch.setattr(replan_preview, "SETTLE_S", 30.0)
    jobs = []
    host, _ = _host()
    monkeypatch.setattr(host, "_job", lambda kind: jobs.append(kind))
    try:
        host.poke()
        first = host._due
        time.sleep(0.05)
        host.poke()
        assert host._due > first and jobs == []
    finally:
        host.stop()


def test_closing_runs_a_pending_settle_at_once(lib, monkeypatch):
    root, store = lib
    monkeypatch.setattr(replan_preview, "SETTLE_S", 30.0)      # a settle that would outlast the window
    jobs = []
    host, _ = _host()
    monkeypatch.setattr(host, "_job", lambda kind: jobs.append(kind))
    host.poke()
    time.sleep(0.1)
    assert jobs == []
    host.close()
    deadline = time.monotonic() + 5
    while host.busy() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert jobs == ["move"] and not host.busy()
    host.poke()                                  # closing: nothing new
    time.sleep(0.1)
    assert jobs == ["move"]
    host.stop()


# --------------------------------------------------------------------------------------------------------------- #
# Every 04 §4 case says its line
# --------------------------------------------------------------------------------------------------------------- #

def test_anki_closed_writes_nothing_says_so_and_starts_a_new_session(lib):
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
        _move_later_to_top(store)
        fake.offline = True
        host._job("move")
    assert lines[-1] == replan_preview.CLOSED
    assert store.versions()["planned_order_version"] < store.versions()["order_version"]    # still owed
    assert anki_sync_rule.read_state().get("closed_at")      # the next write starts a session (S1)


def test_a_review_in_progress_waits_and_looks_again(lib):
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
        _move_later_to_top(store)
        fake.reviewing = True
        fake.write_requests.clear()
        host._job("move")
    assert lines[-1] == replan_preview.REVIEWING and not fake.write_requests
    assert host._retry_at is not None and host._retry_kind == "move"


def test_the_junban_window_open_waits_for_it(lib):
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    from app import locks
    with _patched(fake):
        _move_later_to_top(store)
        with locks.take("junban-window", "順 window"):
            host._job("move")
    assert lines[-1] == replan_preview.BUSY and host._retry_at is not None


def test_a_job_a_put_back_stood_aside_writes_nothing_and_says_why_without_retrying(monkeypatch):
    """FT C1: the job waited for the Anki-write lock while a put-back cleared its deck; Junban's run, reading the
    settings again, wrote nothing (`stands_aside`). The host shows that line and leaves it there — picking the deck
    in 順 again is the user's — never a retry, never "Anki not re-ordered"."""
    line = "順's deck TheBank isn't recorded for Japanese — pick it in 順's window in Japanese"
    monkeypatch.setattr(reposition, "run", lambda *args, **kwargs: {"ok": False, "stands_aside": True,
                                                                   "problems": [line], "written": []})
    host, lines = _host()
    assert host._write({"junban_deck": "TheBank", "target_language": "ja"}, spaced.Job(automatic=True),
                       "move") is None
    assert lines[-1] == line and host._retry_at is None


def test_no_plan_file_asks_for_a_generate_first(lib):
    root, store = lib
    os.remove(os.path.join(root, "results", analyzer.PLAN_FILE))
    fake = _deck(root)
    asked = []
    cm, cm_lines = _host()
    dash, dash_lines = _host(generate=asked.append)
    with _patched(fake):
        _move_later_to_top(store)
        cm._job("move")
        dash._job("catch-up")
    assert cm_lines[-1] == replan_preview.GENERATE_FIRST_CM
    assert dash_lines[-1] == replan_preview.GENERATE_FIRST
    assert asked and asked[0].startswith("generate-first")
    assert not fake.write_requests


def test_a_new_file_alone_starts_nothing_but_a_move_with_it_asks_for_a_generate(lib):
    root, store = lib
    fake = _deck(root)
    asked = []
    dash, lines = _host(generate=asked.append)
    with _patched(fake):
        dash._job("catch-up")                    # placed: nothing owed
        asked.clear()
        from app.path_utils import get_data_path
        # 6+ Months, not NOW: on the 3.0 line Current's tiers follow the Soon line (L2.2 05 §5.1), so a file placed at
        # NOW's top pushes NOW's last row into Soon — a move of a planned file. 6+ Months' top moves no row's tier.
        path = os.path.join(get_data_path("ja"), "GoalContent", "new_episode.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("新しい話が始まった。今日は学校で友達に会った。\n")
        library_store.sync_for_window(store)
        dash._seen = None
        dash._anki_looked = -1e9
        dash._job("catch-up")
        new_files_alone = list(asked)
        said_alone = lines[-1] if lines else None
        placed = store.versions()
        _move_later_to_top(store)
        dash._job("catch-up")
    assert new_files_alone == [], "a new file with no move owed started an automatic Generate"
    # 2.x-dev keeps NEW_CONTENT in lines; 3.0 (G4): the new file is placed in the store (6+ Months' order
    # moved since the plan), so the window's hook runs the keeper's Generate — and the line says it runs first.
    assert placed["order_version"] > placed["planned_order_version"]
    assert said_alone == replan_preview.GENERATE_FIRST, said_alone
    assert replan_preview.NEW_CONTENT not in lines and replan_preview.GENERATE_FIRST in lines
    assert asked and asked[0].startswith("generate-first"), asked
    assert lines[-1] == replan_preview.GENERATE_FIRST


def test_known_words_changed_reorders_now_then_asks_for_a_generate(lib):
    root, store = lib
    fake = _deck(root)
    asked = []
    dash, lines = _host(generate=asked.append)
    with _patched(fake):
        dash._job("catch-up")
        asked.clear()
        known = os.path.join(root, "User Files", "ja", "KnownWord.json")
        with open(known, encoding="utf-8") as f:
            data = json.load(f)
        with open(known, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)          # a new stat: the known words "changed"
        os.utime(known, (time.time() + 5, time.time() + 5))
        _move_later_to_top(store)
        fake.write_requests.clear()
        dash._job("catch-up")
    assert fake.write_requests, "re-order now, from the plan"
    assert any(line == replan_preview.REPLAN_THEN_GENERATE for line in lines)
    assert asked and asked[0].startswith("replan-now"), asked


def test_known_words_changed_without_a_move_asks_for_no_journey(lib):
    """The journey's Generate is for moves (04 §3, G1.5-5): known words changed with nothing moved leave the run's
    signature behind the library's, but no move is pending — nothing is asked for on focus (mutant "journey asks
    without moves")."""
    root, store = lib
    fake = _deck(root)
    asked = []
    dash, _ = _host(generate=asked.append)
    with _patched(fake):
        dash._job("catch-up")
        asked.clear()
        known = os.path.join(root, "User Files", "ja", "KnownWord.json")
        with open(known, encoding="utf-8") as f:
            data = json.load(f)
        with open(known, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)          # a new stat: the known words "changed"
        os.utime(known, (time.time() + 5, time.time() + 5))
        dash._seen = None                        # focus again (the look's memo holds no known words)
        dash._job("catch-up")
    assert not store.journey_pending()
    assert "moves" not in asked, asked


def test_a_stand_aside_plan_says_generate_reorders(lib, monkeypatch):
    root, store = lib
    fake = _deck(root)
    monkeypatch.setattr(plan_engine, "stands_aside", lambda plan: "weights")
    host, lines = _host()
    with _patched(fake):
        _move_later_to_top(store)
        host._job("move")
    assert lines[-1] == replan_preview.STAND_ASIDE["weights"] and not fake.write_requests


# --------------------------------------------------------------------------------------------------------------- #
# The dashboard: catch-up and the journey's automatic Generate
# --------------------------------------------------------------------------------------------------------------- #

def test_catch_up_places_newly_mined_cards_and_asks_for_the_journey_after_moves(lib):
    root, store = lib
    fake = _deck(root)
    asked = []
    dash, _ = _host(generate=asked.append)
    with _patched(fake):
        dash._job("catch-up")
        assert asked == []                       # nothing moved since the Generate: no Generate
        # A card mined since (Anki's counter puts it near the front): the next catch-up places it.
        word = _list_words(root)[70]
        cards, notes, _ = _collection([word], dues=[2995], deck=DECK, start=500)
        for card in cards:
            card["mod"] = 1_700_000_000
            fake.cards[card["cardId"]] = card
        for note in notes:
            fake.notes[note["noteId"]] = note
            fake.note_mods[note["noteId"]] = 1_700_000_000
        dash._anki_looked = -1e9
        fake.write_requests.clear()
        dash._job("catch-up")
        assert fake.write_requests, "the newly mined card wasn't placed"
        # A move made elsewhere (the Content Manager), then focus: re-ordered, and the journey asked for.
        _move_later_to_top(store)
        dash._job("catch-up")
    assert asked == ["moves"]
    assert store.versions()["planned_order_version"] == store.versions()["order_version"]


class EditedCollection(SyncCollection):
    """`SyncCollection` plus `findNotes` for the catch-up's `edited:n` look: the notes `edited` names, in scope."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.edited = set()

    def _dispatch(self, action, params):
        if action == "findNotes" and " edited:" in (params.get("query") or ""):
            return sorted(self.edited)
        return super()._dispatch(action, params)


def test_catch_up_re_places_a_card_whose_note_was_edited_since_the_last_run(lib):
    """Drill A3 gap 3 (the lead, 2026-10-23): a note's word edited in Anki after a re-order (its mod time only) moved
    nothing — the host owed nothing. Now the catch-up holds the notes Anki says were edited lately (`edited:n`)
    against the mod time its card map read: an edit makes it owed, the card goes where its new word belongs, and the
    next catch-up owes nothing again."""
    root, store = lib
    words = _list_words(root, 60)
    cards, notes, _ = _collection(words, dues=list(range(3059, 2999, -1)), deck=DECK)
    fake = EditedCollection(cards, notes)
    dash, _ = _host(generate=lambda reason: None)
    with _patched(fake):
        dash._job("catch-up")
        last = max(fake.notes, key=lambda n: words.index(fake.notes[n]["fields"]["Expression"]["value"]))
        card = next(c for c in fake.cards.values() if c["note"] == last)
        due_before = card["due"]
        fake.notes[last]["fields"]["Expression"]["value"] = words[0]          # the card is now the list's first word
        fake.note_mods[last] += 7
        fake.edited = {last}
        dash._anki_looked = -1e9
        fake.write_requests.clear()
        dash._job("catch-up")
        assert fake.write_requests, "the edited note's card wasn't re-placed"
        first_dues = sorted(c["due"] for c in fake.cards.values())[:2]
        assert card["due"] != due_before and card["due"] in first_dues, "beside the list's first word now"
        dash._anki_looked = -1e9
        fake.requests.clear()
        dash._job("catch-up")
    sent = [r for r in fake.requests if r["action"] == "multi" and "setSpecificValueOfCard" in str(r)]
    assert not sent, "read again: nothing owed"


def test_after_a_restart_an_edit_made_meanwhile_is_placed_by_the_first_look(lib):
    """Gap 3, review G3-1: the card map lives in memory, so after the app starts again it has read nothing. An edit
    made meanwhile (since Junban's last spaced run, its ladder file's time) makes the first look owe one job, which
    places it and fills the map; with no edit the first look owes nothing. The look reaches back in whole days since
    then plus two (review G3-2: an edit before Anki's day rollover, a phone edit synced the next morning)."""
    root, store = lib
    words = _list_words(root, 60)
    cards, notes, _ = _collection(words, dues=list(range(3059, 2999, -1)), deck=DECK)
    fake = EditedCollection(cards, notes)
    with _patched(fake):
        first, _ = _host(generate=lambda reason: None)
        first._job("catch-up")                          # the ladder recorded: Junban's last spaced run
        again, _ = _host(generate=lambda reason: None)  # the app started again: an empty card map
        again._anki_looked = -1e9
        fake.write_requests.clear()
        again._job("catch-up")
        assert not fake.write_requests, "no edit meanwhile: nothing owed"
        last = max(fake.notes, key=lambda n: words.index(fake.notes[n]["fields"]["Expression"]["value"]))
        card = next(c for c in fake.cards.values() if c["note"] == last)
        fake.notes[last]["fields"]["Expression"]["value"] = words[0]
        fake.note_mods[last] += 7
        fake.edited = {last}
        fake.requests.clear()
        third, _ = _host(generate=lambda reason: None)
        third._anki_looked = -1e9
        third._job("catch-up")
    assert fake.write_requests and card["due"] in sorted(c["due"] for c in fake.cards.values())[:2]
    asked = [r["params"]["query"] for r in fake.requests if r["action"] == "findNotes"]
    assert asked and all(" edited:2" in q for q in asked), asked


def test_no_plan_at_all_asks_for_one_generate_once(lib):
    root, store = lib
    os.remove(os.path.join(root, "results", analyzer.PLAN_FILE))
    asked = []
    dash, _ = _host(generate=asked.append)
    fake = _deck(root)
    with _patched(fake):
        dash._job("catch-up")
        dash._seen = None
        dash._job("catch-up")
    assert len(asked) == 1 and "no-plan" in asked[0]   # once per run: a Generate that left no plan isn't asked again


# --------------------------------------------------------------------------------------------------------------- #
# RP-10 and shadow mode
# --------------------------------------------------------------------------------------------------------------- #

def test_rp10_reads_the_last_runs_file_numbers_through_the_new_order(lib):
    root, store = lib
    host, _ = _host()
    plan, _why = host._load_plan()
    engine, ids = host._engine_for(store)
    moved = _move_later_to_top(store)
    order = [(i, t) for t in replan_preview.TIERS for i in store.ids(t) if i in set(ids)]
    result = engine.replan(order)
    places = replan_preview.places(plan, ids, result)
    old = ids.index(moved) + 1                   # its number in the last run (6+ Months' last: 12)
    assert old == len(ids) and places[old] == 1  # first now
    assert places[1] == 2                        # NOW's first moved down one
    assert sorted(places.values()) == list(range(1, len(ids) + 1))


def test_shadow_mode_logs_one_line_for_a_difference_and_none_without(lib, monkeypatch):
    root, store = lib
    host, _ = _host()
    previous, _why = host._load_plan()
    log = []
    monkeypatch.setattr(replan_preview, "_log_shadow", log.append)
    # The same plan as "new" but with another run signature: the comparison runs, the lists agree.
    other = plan_engine.Plan(dict(previous.header, run_signature="another run"), previous.files, previous.keys,
                             previous.rows, previous.ties, previous.per_file)
    host._shadow(previous, other)
    assert log == []
    real = replan_preview._lists

    def tampered():
        lists = real()
        lists["priority"][0] = dict(lists["priority"][0], Score="999999")
        return lists
    monkeypatch.setattr(replan_preview, "_lists", tampered)
    host._shadow(previous, other)
    assert len(log) == 1 and "Score" in log[0]


# --------------------------------------------------------------------------------------------------------------- #
# The review's fixes (tracks/engine/reviews/E3.1-adversary.md)
# --------------------------------------------------------------------------------------------------------------- #

def test_the_preview_runs_only_for_the_language_it_was_switched_on_in():
    """`junban_deck` is one key for both languages: a Chinese Generate or Content Manager must never re-order the
    Japanese deck by the Chinese list (review #1)."""
    on = {"junban_replan_preview": True, "enable_junban": True}
    assert replan_preview.is_on(on, "ja") and not replan_preview.is_on(on, "zh")      # unsaid: Japanese
    zh = dict(on, junban_replan_language="zh")
    assert replan_preview.is_on(zh, "zh") and not replan_preview.is_on(zh, "ja")
    assert replan_preview.is_on(zh)                          # no language asked: the switch alone


def test_another_languages_host_never_touches_the_deck_and_says_why_once(lib):
    """2.x-dev keeps `lines == []` here (is_on False: the host silent); 3.0: the host stands aside on the recorded pair
    (Haya's G3) and its line names the deck and the language it is recorded for — once per reason, never per job."""
    root, store = lib
    _settings_file(root, junban_replan_language="zh")
    fake = _deck(root)
    host, lines = _host()                                    # a Japanese window
    with _patched(fake):
        _move_later_to_top(store)
        host._job("move")
        host._job("move")
        host._job("catch-up")
        host._warm()
    assert not fake.requests
    assert lines == [replan_preview.stands_aside(host._settings(), "ja")], lines
    assert "recorded for Chinese" in lines[0] and DECK in lines[0]
    assert host._engine is None, "a host standing aside warmed the engine"


def test_with_d29_off_the_host_writes_nothing_warms_nothing_and_never_syncs(lib, monkeypatch):
    """D29 off (Haya's G2a: "every automatic Anki write and sync"): all three gates — `_warm`, `_job`, `_sync_step` —
    stand aside, on the in-process host with Junban's fake Anki, even with 2.x's box on and a sync armed by 順's run."""
    root, store = lib
    _settings_file(root, logic={"automation": False})
    fake = _deck(root)
    monkeypatch.setenv(replan_preview.IN_PROCESS_ENV, "1")
    lines = []
    host = replan_preview.open_host("ja", say=lines.append)
    assert isinstance(host, replan_preview.Host)
    with _patched(fake):
        host._warm()
        host._job("catch-up")
        _move_later_to_top(store)
        host._job("move")
        host._job("generate")
        anki_sync_rule.wrote(True, {"anki_sync_delay_min": 1})     # 順's own run armed S3
        host._sync_at = time.time() - 1
        host._sync_step()
        host._sync_at = time.time() - 1
        host._sync_step(force=True)                              # the window closing
    assert not fake.requests, [r["action"] for r in fake.requests]
    assert fake.syncs == 0 and host._sync_at is None
    assert host._engine is None
    versions = store.versions()
    assert versions["planned_order_version"] < versions["order_version"], "nothing recorded as planned"
    assert lines == [], "D29 off is the user's own choice: the host says nothing about it"


def test_d29_is_read_fresh_every_job_never_when_the_host_opens(lib):
    """Never cached at `open_host`: switched off between two jobs, the next writes nothing; on again, it writes."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
        assert fake.write_requests, "D29 on, the pair recorded: the first job lays the ladder"
        _settings_file(root, logic={"automation": False})
        _move_later_to_top(store)
        fake.write_requests.clear()
        host._job("move")
        assert not fake.write_requests
        _settings_file(root, logic={"automation": True})
        host._job("move")
    assert fake.write_requests
    versions = store.versions()
    assert versions["planned_order_version"] == versions["order_version"]


# --------------------------------------------------------------------------------------------------------------- #
# 3.0: the host's re-order applies your 順 actions (Sonic, 2026-10-13: "it just works")
# --------------------------------------------------------------------------------------------------------------- #

OFF = ("須藤", "洗濯機")                             # two words the library's list never has
ACTIONS = ("setSpecificValueOfCard", "multi", "suspend", "unsuspend")


class MarkingCollection(SyncCollection):
    """The fake collection, plus the mod times Anki moves when a note is tagged or a card flagged or (un)suspended —
    so the next job's warm read (`CardMap`) sees what the last one did, as it would in Anki."""

    def _tags(self, action, params):
        for note_id in params.get("notes") or []:
            if note_id in self.note_mods:
                self.note_mods[note_id] = int(time.time())
        return super()._tags(action, params)

    def _suspend(self, action, card_ids):
        for card_id in card_ids:
            if card_id in self.cards:
                self.cards[card_id]["mod"] = int(time.time())
        return super()._suspend(action, card_ids)

    def _multi(self, actions):
        for entry in actions:
            params = entry.get("params") or {}
            if entry.get("action") == "setSpecificValueOfCard" and params.get("keys") == ["flags"]:
                self.cards[params["card"]]["mod"] = int(time.time())
        return super()._multi(actions)


def _acting_deck(root, off=OFF, yours=()):
    """40 of the list's words and the cards off it (`off`, then `yours` — suspended by the user), queued in the reverse
    of the list's order, dense as 2.5 left it."""
    listed = set(_list_words(root))
    assert not [word for word in tuple(off) + tuple(yours) if word in listed], "the cards are off the library's list"
    words = _list_words(root, 40) + list(off) + list(yours)
    cards, notes, _ = _collection(words, dues=list(range(3000 + len(words) - 1, 2999, -1)), deck=DECK)
    fake = MarkingCollection(cards, notes, actions=ACTIONS)
    for card_id in _word_cards(fake, yours):
        fake.cards[card_id]["queue"] = -1
    return fake


def _listed_deck(root):
    """60 cards, every one a word of the list (`_deck`), the fake that moves mod times as Anki does."""
    words = _list_words(root, 60)
    cards, notes, _ = _collection(words, dues=list(range(3000 + len(words) - 1, 2999, -1)), deck=DECK)
    return MarkingCollection(cards, notes, actions=ACTIONS)


def _kinds(requests, off_ids=()):
    """Each request as what it does: "position" (a multi of due writes), "flag" (a multi of flag writes), "re-check"
    (a `cardsInfo` of exactly the cards off the list, alone or in a `multi`), else its action."""
    out = []
    for request in requests:
        action, params = request["action"], request.get("params") or {}
        keys = {tuple((entry.get("params") or {}).get("keys") or ()) for entry in params.get("actions") or ()
                if action == "multi" and entry.get("action") == "setSpecificValueOfCard"}
        if ("due",) in keys:
            out.append("position")
        elif ("flags",) in keys:
            out.append("flag")
        elif action == "cardsInfo" and off_ids and set(params.get("cards") or ()) == set(off_ids):
            out.append("re-check")
        elif action == "multi" and off_ids and [
                set((entry.get("params") or {}).get("cards") or ()) for entry in params.get("actions") or ()
                if entry.get("action") == "cardsInfo"] == [set(off_ids)]:
            out.append("re-check")                  # with `guiReviewActive` in the same request (04 §6)
        else:
            out.append(action)
    return out


def _warm_read(request):
    """A request as compared across two worlds: a warm read's `multi` (`cardsInfo` / `notesInfo` of what changed) by
    its actions alone — which ids it carries follows Anki's whole-second mod times (`CardMap`: anything modified within
    a second of the last read is read again), so the clock, not the run; every other request as it is."""
    entries = (request.get("params") or {}).get("actions") or ()
    if request["action"] == "multi" and entries and all(
            entry.get("action") in ("cardsInfo", "notesInfo") for entry in entries):
        return ["multi"] + sorted({entry["action"] for entry in entries})
    actions = [entry.get("action") for entry in entries] if request["action"] == "multi" else []
    if actions[:1] == ["guiReviewActive"] and len(actions) > 1 and all(
            action in ("cardsModTime", "cardsInfo") for action in actions[1:]):
        # A write's re-check (`ankiconnect._checked`): the same cards, asked by `cardsModTime` when their mod time is
        # older than the read's second less one, else by `cardsInfo` — the clock again (beside other test runs, a
        # job straddling a second asked one where the other world asked the other). Compared by the cards it re-checks.
        return ["multi", "guiReviewActive", "re-check",
                sorted(card for entry in entries[1:] for card in (entry.get("params") or {}).get("cards") or ())]
    return request


def _logged(fake, host, kind, force=False):
    """One host job -> the requests it sent."""
    start = len(fake.requests)
    host._force = force or host._force
    host._job(kind)
    return fake.requests[start:]


def _start_again(store, moved):
    """A second world in the same library: the moves taken back (the newest first, each to 6+ Months' end, where it
    came from), and Junban's snapshot, baseline and ladder and the sync rule's session gone."""
    for item in reversed(moved):
        store.move([item], "goal", after_id=_ids(store, "goal")[-1])
    from app.path_utils import get_user_files_path
    for name in (undo.FILENAMES["reorder"], undo.FILENAMES["baseline"], undo.LADDER_FILENAME):
        path = os.path.join(get_user_files_path("ja"), name)
        if os.path.exists(path):
            os.remove(path)
    if os.path.exists(anki_sync_rule._path()):
        os.remove(anki_sync_rule._path())


def _positions_only(over):
    """The same settings with every action switched off: what today's host sends, `_POSITIONS_ONLY` laid over them."""
    return dict(over, junban_auto_actions=False, junban_later_tag=False, junban_later_flag=False,
                junban_later_suspend=False)


def _three_jobs(root, store, fake_of, **settings):
    """A catch-up (the ladder laid: every card once), then two moves (deltas) -> (each job's requests, the fake, the
    items moved)."""
    _settings_file(root, **settings)
    fake = fake_of(root)
    host, _ = _host()
    logs, moved = [], []
    with _patched(fake):
        logs.append(_logged(fake, host, "catch-up", force=True))
        for _ in range(2):
            moved.append(_move_later_to_top(store))
            logs.append(_logged(fake, host, "move"))
    return logs, fake, moved


@pytest.mark.parametrize("over,acted", [
    (dict(junban_auto_actions=True, junban_later_tag=True, junban_later_flag=True, junban_later_suspend=True),
     ("addTags", "flag", "suspend")),
    # Connect's preview on — HY-6 (P3.3, `connect.UNATTENDED_ACTIONS` on the 3.0 line): Connect being on strips
    # nothing any more; your actions apply as with it off (2.x-dev keeps the positions and the suspend's say only).
    (dict(junban_auto_actions=True, connect_enabled=True, junban_later_tag=True, junban_later_flag=True,
          junban_later_suspend=True), ("addTags", "flag", "suspend")),
], ids=["actions-on", "connect-unattended-suspend"])
def test_on_3_0_the_hosts_job_applies_your_actions_after_its_positions_suspend_last(lib, monkeypatch, over, acted):
    """2.x-dev keeps the host's job positions only; 3.0 (Sonic, 2026-10-13: "it just works"): the window's re-order
    applies your 順 settings as 順's automatic step decides them — every position first, then the tag and the flag,
    the suspend last — under the window's snapshot (one restore point: today's baseline is not kept beside it)."""
    from modules.junban import connect
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", True)
    root, store = lib
    _settings_file(root, **over)
    fake = _acting_deck(root)
    off_ids = _word_cards(fake, OFF)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
    kinds = _kinds(fake.requests, off_ids)
    assert "position" in kinds, "the host still re-orders"
    last_position = max(index for index, kind in enumerate(kinds) if kind == "position")
    assert not [kind for kind in kinds[:last_position] if kind in ("addTags", "flag", "suspend", "re-check")], kinds
    after = [kind for kind in kinds[last_position + 1:] if kind in ("addTags", "flag", "suspend", "re-check")]
    assert after[0] == "re-check" and after[-1] == "suspend", after         # read again first, suspend last
    assert [kind for kind in dict.fromkeys(after[1:])] == list(acted), after
    assert [ids for action, ids in fake.suspend_calls if action == "suspend"] == [sorted(off_ids)]
    assert all(fake.cards[card_id]["queue"] == -1 for card_id in off_ids)
    later = [sorted(notes) for _action, notes, tag in fake.tag_calls if tag == "Surasura::later"]
    assert later == [sorted(fake.cards[card_id]["note"] for card_id in off_ids)]
    assert sorted(card_id for card_id, _flag in fake.flag_writes) == (sorted(off_ids) if "flag" in acted else [])
    # HY-6 (P3.3): the touch-ups' Surasura tag too, Connect on or off
    assert "Surasura" in {tag for _action, _notes, tag in fake.tag_calls}
    saved = undo.load("ja")
    assert saved and saved["complete"] is True and saved["suspended"] == sorted(off_ids), "the window's snapshot"
    baseline = undo.load("ja", "baseline")
    assert baseline is None or baseline.get("ended_at"), "one restore point: never also today's baseline"


@pytest.mark.parametrize("deck_of,over", [
    # The actions switched off (`junban_auto_actions` False, no Connect: no unattended suspend), cards off the list.
    (_acting_deck, dict(junban_later_tag=True, junban_later_flag=True, junban_later_suspend=True)),
    # Connect's preview on with the actions and the suspend setting off — HY-6 (P3.3): with the actions on, Connect
    # on now tags and flags as with it off (test_on_3_0_the_hosts_job_applies_your_actions_…); off: positions only.
    (_acting_deck, dict(junban_auto_actions=False, connect_enabled=True, junban_later_tag=True,
                        junban_later_flag=True)),
    # The actions on, every card on the list and no Surasura tag: nothing to act on.
    (_listed_deck, dict(junban_auto_actions=True, junban_tag="", junban_later_tag=True, junban_later_flag=True,
                        junban_later_suspend=True)),
], ids=["actions-off", "connect-suspend-off", "nothing-to-act-on"])
def test_on_3_0_a_host_run_with_nothing_to_act_on_sends_todays_positions_only_requests(lib, monkeypatch, deck_of, over):
    """The move budget (E2.1): a catch-up that lays the ladder and two moves (deltas) send, request for request, what
    today's positions-only host sends in the same library and deck — no re-check read, no action, today's baseline."""
    from modules.junban import connect
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", True)
    root, store = lib
    today, _plain, moved = _three_jobs(root, store, deck_of, **_positions_only(over))
    _start_again(store, moved)
    acting, fake, _moved = _three_jobs(root, store, deck_of, **over)
    assert [_kinds(log) for log in acting] == [_kinds(log) for log in today]
    for job, (sent_log, today_log) in enumerate(zip(acting, today)):
        for index, (sent, positions_only) in enumerate(zip(sent_log, today_log)):
            if sent["action"] == "apiReflect" and over.get("junban_later_suspend") and not over.get("connect_enabled"):
                # The one difference, and no write: with the suspend setting saved, the probe (the same request)
                # also names `suspend` / `unsuspend`, asked before the plan knows there's nothing to suspend.
                asked = sent["params"]["actions"]
                # The probe is the run's own, on the job's settings as `_write` decides them (the actions on: they
                # name the suspend), never positions-only's
                assert not over.get("junban_auto_actions") or {"suspend", "unsuspend"} <= set(asked), asked
                assert [name for name in asked if name not in ("suspend", "unsuspend")] == \
                    positions_only["params"]["actions"], asked
                continue
            assert _warm_read(sent) == _warm_read(positions_only), f"job {job}, request {index} differs"
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == []
    assert undo.load("ja") is None and undo.load("ja", "baseline"), "today's baseline alone"


def test_on_3_0_a_move_after_the_actions_landed_sends_no_action_request_and_no_re_check(lib):
    """A drag whose actions are unchanged adds no request: the plan asks only what differs from Anki now (a note
    already tagged, a card already purple or suspended is no work), so after the catch-up acted, two moves send what
    today's positions-only host sends for them — no action, no re-check read. (The tag and the flag alone here, so
    both worlds keep the same cards in the queue.)"""
    root, store = lib
    over = dict(junban_auto_actions=True, junban_later_tag=True, junban_later_flag=True)
    today, _fake, moved = _three_jobs(root, store, _acting_deck, **_positions_only(over))
    _start_again(store, moved)
    acting, fake, _moved = _three_jobs(root, store, _acting_deck, **over)
    off_ids = _word_cards(fake, OFF)
    first = _kinds(acting[0], off_ids)
    assert "re-check" in first and "addTags" in first and "flag" in first, first
    for job in (1, 2):
        kinds = _kinds(acting[job], off_ids)
        assert "position" in kinds, f"move {job} re-ordered nothing"
        assert not {"addTags", "flag", "suspend", "re-check"} & set(kinds), kinds
        assert kinds == _kinds(today[job], off_ids), f"move {job} sent other requests than today's"
        # The same positions, request for request. A read may carry more ids — the notes the catch-up tagged and the
        # cards it flagged, read again in the one request the move sends anyway (Anki moved their mod times).
        assert [sent for sent, kind in zip(acting[job], kinds) if kind == "position"] == \
            [sent for sent, kind in zip(today[job], kinds) if kind == "position"]
    assert len(fake.flag_writes) == len(off_ids), "each card flagged once"


def test_on_3_0_anki_stopping_during_the_hosts_re_check_means_no_action_and_the_positions_stand(lib):
    """The re-check read fails (Anki stopped answering after the positions): nothing is known about the cards off the
    list, so nothing is tagged, flagged or suspended this run — the Surasura tag neither; the positions stand, the
    window's snapshot is complete (the next job may go) and the re-order is recorded as done."""
    import urllib.error
    root, store = lib
    _settings_file(root, junban_auto_actions=True, junban_later_tag=True, junban_later_flag=True,
                   junban_later_suspend=True)
    fake = _acting_deck(root)
    off_ids = _word_cards(fake, OFF)
    failed = []

    def anki_stops(ids):
        if fake.write_requests and not failed and set(ids) == set(off_ids):
            failed.append(sorted(ids))
            raise urllib.error.URLError("[WinError 10061] No connection could be made")
    fake.before_cards_info = anki_stops
    before = fake.queue()
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
    assert failed, "the re-check read went out after the positions"
    assert fake.write_requests and fake.queue() != before, "the positions stand"
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == []
    saved = undo.load("ja")
    assert saved["complete"] is True and not saved.get("suspended"), saved
    versions = store.versions()
    assert versions["planned_order_version"] == versions["order_version"]


def test_on_3_0_restore_after_a_host_run_puts_positions_back_and_unsuspends_only_its_own_suspends(lib):
    """One Restore after the host acted: every position back, the run's suspends unsuspended, its tags and flags
    off — and 掃除機, which you suspended yourself, stays suspended (the run never touched it)."""
    root, store = lib
    _settings_file(root, junban_auto_actions=True, junban_later_tag=True, junban_later_flag=True,
                   junban_later_suspend=True)
    fake = _acting_deck(root, yours=("掃除機",))
    off_ids, yours = _word_cards(fake, OFF), _word_cards(fake, ("掃除機",))
    before = {card_id: (card["due"], card["queue"]) for card_id, card in fake.cards.items()}
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
        assert all(fake.cards[card_id]["queue"] == -1 for card_id in off_ids)
        restored = reposition.restore(_junban_settings())
    assert restored["ok"], restored["problems"]
    assert {card_id: (card["due"], card["queue"]) for card_id, card in fake.cards.items()} == before
    assert [ids for action, ids in fake.suspend_calls if action == "unsuspend"] == [sorted(off_ids)]
    assert not [ids for _action, ids in fake.suspend_calls if set(ids) & set(yours)]
    assert all("Surasura::later" not in (fake.notes[fake.cards[card_id]["note"]].get("tags") or [])
               for card_id in off_ids)
    assert all(not fake.cards[card_id].get("flags") for card_id in off_ids)


def test_on_3_0_after_an_acting_host_run_cut_by_anki_closing_the_next_move_goes_on(lib):
    """2.x-dev keeps I3 for every run; 3.0: a run nobody started never stops the automation it belongs to. The host's
    acting run is cut by Anki closing after its first position request: its window snapshot, marked as an automatic
    run's, stays unfinished. The next move still re-orders and acts — no "did not finish", no Restore asked of you —
    and its snapshot takes the cut one over, complete."""
    root, store = lib
    _settings_file(root, junban_auto_actions=True, junban_later_tag=True, junban_later_flag=True,
                   junban_later_suspend=True, junban_chunk_size=5)      # several position requests
    fake = _acting_deck(root)
    off_ids = _word_cards(fake, OFF)
    fake.on_write = lambda: setattr(fake, "offline", True)     # Anki closes as the first position request lands
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
    cut = undo.load("ja")
    assert cut["complete"] is False and cut["automatic"] is True, cut
    assert fake.suspend_calls == []

    fake.offline = False
    _move_later_to_top(store)
    start = len(lines)
    with _patched(fake):
        host._job("move")
    assert not [line for line in lines[start:] if "did not finish" in line or "Undo the last reorder" in line], lines[start:]
    assert [ids for action, ids in fake.suspend_calls if action == "suspend"] == [sorted(off_ids)]
    saved = undo.load("ja")
    assert saved["complete"] is True and saved["cards"] == {**saved["cards"], **cut["cards"]}, "taken over"
    versions = store.versions()
    assert versions["planned_order_version"] == versions["order_version"]


def test_a_cut_manual_juns_run_still_refuses_every_automatic_job_and_the_bar_says_where_restore_is(lib):
    """I3 is kept wherever you started the run: 順's own run, cut by Anki closing, leaves the only way back to how
    your cards were. Every automatic job then refuses — the host's, AutoJunban's and Connect's — writing nothing, and
    the host's line tells you where the Restore is (順, until the new window has its own), said once, not retried."""
    from modules.junban import auto
    root, store = lib
    _settings_file(root, junban_auto_actions=True, junban_later_tag=True, junban_later_flag=True,
                   junban_later_suspend=True)
    fake = _acting_deck(root)
    fake.on_write = lambda: setattr(fake, "offline", True)
    with _patched(fake):
        manual = reposition.run(_junban_settings(), refresh=False)
    assert not manual["ok"] and undo.load("ja")["complete"] is False
    assert "automatic" not in undo.load("ja"), "順's own run carries no automatic mark"
    fake.offline = False
    written = list(fake.writes)

    host, lines = _host()
    _move_later_to_top(store)
    with _patched(fake):
        host._job("move")
        autojunban = auto.reorder(_junban_settings(), list_current=True)
        connects = auto.reorder(dict(_junban_settings(), connect_enabled=True), list_current=True, positions_only=True,
                                run_id=undo.new_run_id("reorder"), job=spaced.Job(automatic=True))
    assert lines[-1] == replan_preview.RESTORE_FIRST, lines
    assert "Open 順 and press Undo the last reorder" in replan_preview.RESTORE_FIRST
    assert host._retry_at is None, "only you can clear it: said once, not retried"
    for done in (autojunban, connects):
        assert done["outcome"] == "refused" and "did not finish" in done["report"]["problems"][0], done
    assert fake.writes == written and fake.suspend_calls == [] and fake.tag_calls == []
    assert undo.load("ja")["complete"] is False


def test_on_3_0_the_host_reorders_with_2x_box_off(lib):
    """2.x-dev keeps the box as the switch (a box-off host never writes: test_the_switch_is_on_only_with_junban_on_and_
    it_names_why_it_cant_run); 3.0: D29 on and the pair recorded is enough — the host never reads
    `junban_replan_preview`."""
    root, store = lib
    _settings_file(root, junban_replan_preview=False)
    fake = _deck(root)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
    assert fake.write_requests
    assert store.versions()["planned_order_version"] == store.versions()["order_version"]


def test_a_new_deck_reason_is_said_once_more_and_d29_off_says_nothing(lib):
    """The stand-aside line once per distinct reason: the pair's deck changed → its own line once; D29 off then → no
    line; the host running again and standing aside again → the reason is news again."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        _settings_file(root, junban_replan_deck="中文")
        host._job("catch-up")
        host._job("catch-up")
        _settings_file(root, junban_replan_deck="中文", logic={"automation": False})
        host._job("catch-up")
        assert len(lines) == 1 and "isn't recorded for Japanese" in lines[0], lines
        _settings_file(root)
        host._job("catch-up")                                 # runs: the ladder laid
        ran = len(lines)
        _settings_file(root, junban_replan_deck="中文")
        host._job("catch-up")
    assert lines[ran:] == [lines[0]], lines


def test_tomorrows_cards_are_anki_first_once_the_first_request_lands(lib):
    """Front first, per request (05 §5): after the move's first write request, Anki's first 20 new cards are the
    plan's first 20 — whatever the rest of the job does after it."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
        _move_later_to_top(store)
        fake.after_first_write = None
        host._job("move")
        rows = host._engine.result().rows("content")
        _writes, stats = reposition.dry_run(_junban_settings(), job=spaced.Job(automatic=True, rows=rows))
    planned = [row.card_id for row in stats["order"]][:20]
    first = fake.after_first_write
    assert first is not None
    queue = [card_id for card_id, _due in sorted(first.items(), key=lambda pair: (pair[1], pair[0]))
             if fake.cards[card_id]["type"] == 0][:20]
    assert queue == planned


def test_a_run_that_writes_nothing_never_syncs(lib):
    """S1 just before the first request (review #5): a session whose first job finds Anki in order sends no sync."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
        assert fake.syncs == 1
        os.remove(anki_sync_rule._path())                    # a new session
        fake.write_requests.clear()
        host._job("generate")                                # re-orders from the plan: everything already in place
    assert not fake.write_requests and fake.syncs == 1


def test_a_newer_order_planned_meanwhile_runs_the_job_once_more(lib, monkeypatch):
    """Two windows (review #3): when another job planned (or the user made) a newer order while this one was being
    written, this write may have landed over it — one more job, owed or not."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host()
    real = library_store.Store.record_planned

    def planned_meanwhile(self, order_version, pins_version):
        real(self, order_version + 1, pins_version)          # as if a newer order's job recorded first
    with _patched(fake):
        host._job("catch-up")
        _move_later_to_top(store)
        monkeypatch.setattr(library_store.Store, "record_planned", planned_meanwhile)
        host._job("move")
    assert host._force and "move" in host._want


def test_the_catch_up_asks_anki_for_the_cards_a_run_places(lib):
    """Suspended, buried and filtered-deck cards are never placed, so they never count as newly mined (review #4)."""
    root, store = lib
    fake = _deck(root)
    dash, _ = _host(generate=lambda reason: None)
    with _patched(fake):
        dash._job("catch-up")
        dash._anki_looked = -1e9
        fake.requests.clear()
        dash._job("catch-up")
    queries = [r["params"]["query"] for r in fake.requests if r["action"] == "findCards"]
    assert any("-is:suspended" in q and "-is:buried" in q and "-deck:filtered" in q for q in queries), queries


def test_a_pending_sync_another_writer_armed_is_picked_up(lib):
    """順's own run (or a window that closed) armed S3; the next job of any host schedules it (review #6)."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
        anki_sync_rule.wrote(True, {"anki_sync_delay_min": 1})
        host._sync_at = None
        host._job("catch-up")
    assert host._sync_at is not None


def test_after_a_generate_a_plan_the_engine_stands_aside_from_reorders_from_the_list(lib, monkeypatch):
    """Review #7: "Generate re-orders Anki" holds — with a stand-aside plan the step after a Generate runs from the
    list itself, as 2.5's did."""
    root, store = lib
    fake = _deck(root)
    monkeypatch.setattr(plan_engine, "stands_aside", lambda plan: "weights")
    host, lines = _host()
    with _patched(fake):
        host._job("generate")
    assert fake.write_requests and replan_preview.STAND_ASIDE["weights"] not in lines


def test_after_a_generate_a_reorder_from_the_list_cut_short_records_no_plan(lib, monkeypatch):
    """The list path after a Generate (a stand-aside plan) records the order planned only when every card landed:
    cut short by a review after request 1, nothing is recorded, and the job is retried (mutant "records after a
    failure")."""
    root, store = lib
    _settings_file(root, junban_chunk_size=5)
    fake = _deck(root)
    monkeypatch.setattr(plan_engine, "stands_aside", lambda plan: "weights")
    recorded = []
    real_record = library_store.Store.record_planned

    def record(self, order_version, pins_version):
        recorded.append((order_version, pins_version))
        real_record(self, order_version, pins_version)
    monkeypatch.setattr(library_store.Store, "record_planned", record)
    real = fake._multi

    def multi(actions):
        replies = real(actions)
        if any(a.get("action") == "setSpecificValueOfCard" for a in actions):
            fake.reviewing = True                            # a review begins once the first request landed
        return replies
    fake._multi = multi
    host, _ = _host()
    with _patched(fake):
        host._job("generate")
    assert len(fake.write_requests) == 1, "the list's re-order never started, or wrote on through the review"
    assert recorded == [] and host._retry_at is not None


def test_a_review_beginning_mid_write_stops_the_automatic_job_between_requests(lib):
    """04 §6 (review #9): an automatic job asks for a review before every request, the first too; the rest wait."""
    root, store = lib
    _settings_file(root, junban_chunk_size=5)
    fake = _deck(root)
    real = fake._multi

    def multi(actions):
        replies = real(actions)
        if any(a.get("action") == "setSpecificValueOfCard" for a in actions):
            fake.reviewing = True                            # a review begins once the first request landed
        return replies
    fake._multi = multi
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
    assert len(fake.write_requests) == 1, "it wrote on through the review"
    assert host._retry_at is not None


def test_auto_reorder_numbers_spaced_while_the_preview_is_on(lib):
    """Rule 8 (review #8): the command line's `junban --auto` and 2.5's step number spaced while the preview is on."""
    root, store = lib
    fake = _deck(root)
    from modules.junban import auto
    with _patched(fake):
        done = auto.reorder(_junban_settings(), list_current=True, positions_only=True)
    assert done["outcome"] == "ran", done
    assert done["report"].get("numbering"), "dense numbering with the preview on"


# --------------------------------------------------------------------------------------------------------------- #
# The second review's fixes (tracks/engine/reviews/E3.1-adversary-2.md)
# --------------------------------------------------------------------------------------------------------------- #

def test_a_deck_changed_since_the_switch_stands_aside():
    """Pass 2 A1: the deck is recorded with the switch; 順's deck changed since (in the other language's window)
    and the preview stands aside, never re-ordering that deck by this language's list."""
    on = {"junban_replan_preview": True, "enable_junban": True, "junban_scope": "deck", "junban_deck": "TheBank",
          "junban_replan_deck": "TheBank"}
    assert replan_preview.unavailable(on) is None
    line = replan_preview.unavailable(dict(on, junban_deck="中文"))
    assert "deck changed" in line and "TheBank" in line and "中文" in line      # both decks named (review 3 R4)
    assert replan_preview.deck_set_aside(dict(on, junban_deck="中文")) == "TheBank"
    assert replan_preview.deck_set_aside(on) is None
    assert replan_preview.unavailable(dict(on, junban_replan_deck="")) is None     # a hand edit: no record, no check


def test_after_a_failed_generate_nothing_is_written_from_a_list_that_isnt_this_librarys(lib):
    """Pass 2 A2: a Generate that failed leaves the last run's list (maybe the other language's): the step after it
    writes from a list only when it is this library's latest run."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host(generate=lambda reason: None)
    os.remove(os.path.join(root, "results", analyzer.PLAN_FILE))     # as a failed Generate leaves no plan
    with open(os.path.join(root, "results", "run_signature.txt"), "w", encoding="utf-8") as f:
        f.write("another run")                                         # and the list is another run's
    with _patched(fake):
        host._job("generate")
    assert not fake.write_requests
    assert lines[-1] in (replan_preview.GENERATE_FIRST, "New content or settings: press Generate, then Anki is re-ordered")


def test_a_refusal_only_the_user_can_clear_is_said_once_not_retried(lib):
    """Pass 2 S3: an unfinished manual run refuses every automatic re-order (03 §9.7) — said, not retried every 20 s."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
        undo.save([(cid, card["due"]) for cid, card in fake.cards.items()], ["TheBank"], language="ja")  # unfinished
        _move_later_to_top(store)
        host._job("move")
    assert lines[-1].startswith("Anki not re-ordered:")
    assert host._retry_at is None


def test_with_anki_closed_the_journeys_generate_is_still_asked_for(lib):
    """Pass 2 S4: moves made with Anki closed still refresh the list (the automatic Generate never waits on Anki)."""
    root, store = lib
    fake = _deck(root)
    asked = []
    dash, lines = _host(generate=asked.append)
    with _patched(fake):
        dash._job("catch-up")
        _move_later_to_top(store)
        fake.offline = True
        dash._job("catch-up")
    assert replan_preview.CLOSED in lines and asked == ["moves"]


def test_a_generates_reorder_that_met_anki_closed_runs_at_the_next_catch_up(lib):
    """Pass 2 S5: known words (or a band) changed, no move: the step after the Generate found Anki closed — the next
    catch-up re-orders, though nothing is owed by the store."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        fake.offline = True
        host._job("generate")
        assert host._force
        fake.offline = False
        calls = []
        real = host._replan
        host._replan = lambda *a, **k: calls.append(a[5] if len(a) > 5 else k.get("kind")) or real(*a, **k)
        host._job("catch-up")
    assert calls == ["catch-up"]


def test_an_owed_reorder_the_plan_cant_serve_is_looked_at_once_per_change(lib, monkeypatch):
    """Pass 2 S6: new content not yet Generated: one look, one line — not a stat of every file at every focus."""
    root, store = lib
    fake = _deck(root)
    dash, lines = _host(generate=lambda reason: None)
    with _patched(fake):
        dash._job("catch-up")
        from app.path_utils import get_data_path
        with open(os.path.join(get_data_path("ja"), "HighPriority", "new_episode.txt"), "w", encoding="utf-8") as f:
            f.write("新しい話が始まった。\n")
        library_store.sync_for_window(store)
        dash._anki_looked = -1e9
        dash._job("catch-up")
        said, looks = len(lines), []
        monkeypatch.setattr(dash, "_parts", lambda *a: looks.append(1))
        dash._anki_looked = -1e9
        dash._job("catch-up")
    assert len(lines) == said and not looks


def test_a_run_with_nothing_to_write_records_its_cards_as_placed(lib):
    """Pass 2 N1: a run that finds every card in place records the ladder's `seen`, so a card mined into its place
    doesn't make every later focus a job."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")
        extra, notes, _ = _collection([_list_words(root)[0]], dues=[999], deck=DECK, start=900)
        for card in extra:
            card["mod"] = 1_700_000_000
            fake.cards[card["cardId"]] = card
        for note in notes:
            fake.notes[note["noteId"]] = note
            fake.note_mods[note["noteId"]] = 1_700_000_000
        host._job("generate")
    assert undo.ladder("ja", [DECK])["seen"] >= extra[0]["cardId"]


def test_a_warm_move_asks_anki_in_few_round_trips_and_nothing_twice(lib):
    """E3.1-B2: a request costs a round trip of Anki's 25 ms timer. Before a warm move's first write: one probe (the
    host's, reused by the run), the review check once (then with each request's re-check), the profile only inside
    the map's first read (S1 takes it), and the reads in their few requests."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host()
    with _patched(fake):
        host._job("catch-up")                    # the first job: the ladder laid, S1's sync
        for card in fake.cards.values():
            card["mod"] = 1_700_000_500          # written long ago, as far as the next read can tell
        _move_later_to_top(store)
        fake.requests.clear()
        host._job("move")
    assert fake.write_requests, "the move wrote nothing"
    top = [request["action"] for request in fake.requests]
    first = next(i for i, request in enumerate(fake.requests) if request["action"] == "multi"
                 and any(entry.get("action") == "setSpecificValueOfCard" for entry in request["params"]["actions"]))
    before = top[:first]
    assert before.count("requestPermission") == 1 and before.count("apiReflect") == 1, before
    assert before.count("guiReviewActive") == 1 and "getActiveProfile" not in before, before
    assert before.count("cardsInfo") == 0 and before.count("cardsModTime") == 0, before
    assert len(before) <= 8, before              # 17 before E3.1-B2 (the DevTest drill's warm moves)
    last = fake.requests[first - 1]["params"]["actions"]
    assert [entry["action"] for entry in last] == ["guiReviewActive", "cardsModTime"]


def test_a_generates_reorder_survives_every_look_while_anki_stays_closed(lib):
    """Review 3 R1: the dashboard queues a catch-up right after every Generate's own job (its child's end), and every
    focus is one more: while Anki stays closed none of them may use up the re-order the Generate still owes. Anki
    opens: the next catch-up re-orders."""
    root, store = lib
    fake = _deck(root)
    host, _ = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        fake.offline = True
        host._job("generate")
        for _focus in range(3):
            host._job("catch-up")                    # Anki still closed: nothing written, the re-order still owed
            assert host._force, "a look while Anki was closed used the Generate's re-order up"
        fake.offline = False
        fake.write_requests.clear()
        calls = []
        real = host._replan
        host._replan = lambda *a, **k: calls.append(a[5] if len(a) > 5 else k.get("kind")) or real(*a, **k)
        host._job("catch-up")
    assert calls == ["catch-up"] and not host._force


def test_a_retry_is_never_swallowed_by_the_last_looks_memo(lib):
    """Review 3 R2, as pass 4 #3 asks: the review begins after the job's guards (the run itself meets it), so the first
    look and its retry share the memo's key ("owed", writable, …) — the retry runs all the same."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")
        for card in fake.cards.values():
            card["mod"] = 1_700_000_500
        _move_later_to_top(store)
        calls = []

        def start_review(ids):
            calls.append(ids)
            if len(calls) == 1:                      # the map's read: past the guards, before request 1
                fake.reviewing = True
        fake.before_mod_times = start_review
        fake.write_requests.clear()
        host._job("catch-up")
        assert not fake.write_requests and host._retry_at is not None
        fake.before_mod_times = None
        fake.reviewing = False
        host._retry_at = time.monotonic() - 1        # the retry is due
        host.run_pending()
    assert fake.write_requests, "the retry returned at once"


def test_a_read_that_lost_anki_is_tried_again(lib):
    """Review 3 R2's second half: Anki goes away during the map's read — the run says `anki_error`, and the job is
    retried (a refusal only the user can clear is the one said once)."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
        _move_later_to_top(store)

        def go_away(ids):
            fake.offline = True                      # the next request finds Anki gone
        fake.before_mod_times = go_away
        fake.write_requests.clear()
        host._job("move")
    assert not fake.write_requests and host._retry_at is not None
    assert lines[-1].startswith("Anki not re-ordered: Could not reach Anki")


def test_a_generates_reorder_cut_short_places_the_rest_at_its_retry(lib):
    """Pass 4 #2: a Generate's re-order owes nothing to the store's versions. Cut short by a review after request 1,
    it is retried as itself (not as a move that finds nothing owed), and the retry places the rest."""
    root, store = lib
    _settings_file(root, junban_chunk_size=5)
    fake = _deck(root)
    host, lines = _host(generate=lambda reason: None)
    with _patched(fake):
        host._job("catch-up")                        # the ladder laid: Anki in the plan's order
        queue = fake.queue()
        dues = [fake.cards[card_id]["due"] for card_id in queue[:40]]
        for card_id, due in zip(queue[:40], reversed(dues)):
            fake.cards[card_id].update(due=due, mod=int(time.time()))     # reversed by hand in Anki
        real = fake._multi

        def multi(actions):
            replies = real(actions)
            if any(a.get("action") == "setSpecificValueOfCard" for a in actions):
                fake.reviewing = True                # a review begins once the first request landed
            return replies
        fake._multi = multi
        fake.write_requests.clear()
        host._job("generate")
        # the host's own lines say why when it wrote nothing (a load flake on 2026-10-15 left no line to read)
        assert len(fake.write_requests) == 1 and host._retry_at is not None, (lines, host._retry_at)
        fake._multi = real
        fake.reviewing = False
        host._retry_at = time.monotonic() - 1
        host.run_pending()
    assert len(fake.write_requests) > 1, "the retry found nothing owed: the rest was never placed"
    assert fake.queue()[:40] == queue[:40]


def test_an_update_another_process_started_stops_every_write(lib, monkeypatch):
    """Pass 4 #1: "Update now" in the dashboard holds its own process only; the helper sees the update's lock (any
    process) — it says so and writes nothing, and no S3 sync goes either."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
        _move_later_to_top(store)
        monkeypatch.setattr(replan_preview, "_update_staged", lambda: True)
        fake.write_requests.clear()
        syncs = fake.syncs
        host._job("move")
        host._sync_step(force=True)
    assert lines[-1] == replan_preview.UPDATE and not fake.write_requests and fake.syncs == syncs


def test_a_sync_due_while_an_update_waits_is_looked_at_again_later_not_on_every_turn(lib, monkeypatch):
    """Pass 5 #2: an S3 sync falls due while an update waits — it stays pending, but its time moves RETRY_S on, so the
    worker sleeps between looks instead of spinning (each turn reads settings.json twice)."""
    import time
    root, _store = lib
    fake = _deck(root)
    host, _lines = _host()
    monkeypatch.setattr(replan_preview, "_update_staged", lambda: True)
    host._sync_at = time.time() - 1.0
    with _patched(fake):
        syncs = fake.syncs
        host._sync_step()
    assert fake.syncs == syncs
    assert host._sync_at is not None and host._sync_at > time.time() + replan_preview.RETRY_S - 2.0
    assert host._next_wait() > 0.5


def test_with_nothing_moved_the_line_names_what_the_plan_waits_for(lib):
    """Pass 4 #13, and on 3.0 (Haya's G4) two cases. Nothing the plan holds moved:
      * and nothing in the store either since the plan (new or changed files alone, a setting) — no Generate is
        coming (the journey keeper is asked on a start, a store move and the host's own ask, never on a file or a
        setting): 2.x's words stand, new content says so, a setting says press Generate;
      * but the store's order or pins moved since the plan (a placement) — the window's hook turns that into the
        keeper's background Generate, then `after_generate`: the line says Generate runs first."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
    versions, order = replan_preview._snapshot(store)
    assert versions["planned_order_version"] == versions["order_version"]
    assert versions["planned_pins_version"] == versions["pins_version"]
    settings = host._settings()
    asked = []
    dash, dash_lines = _host(generate=asked.append)
    dash._load_plan()                                        # the dashboard's host, its plan read (as after a job)
    # Nothing in the store moved since the plan: no Generate is coming — 2.x's words, the CM's and the window's alike.
    for who, said in ((host, lines), (dash, dash_lines)):
        assert who._replan(settings, store, versions, order, ("generate-first", "files"), "catch-up") is False
        assert said[-1] == replan_preview.NEW_CONTENT
        assert who._replan(settings, store, versions, order, ("generate-first", "settings"), "catch-up") is False
        assert said[-1] == replan_preview.PRESS_GENERATE
    # The store's order (a file placed) or its pins moved since the plan: the keeper's Generate is coming.
    placed = dict(versions, order_version=versions["planned_order_version"] + 1)
    pinned = dict(versions, pins_version=versions["planned_pins_version"] + 1)
    for moved in (placed, pinned):
        for why in ("files", "settings"):
            assert host._replan(settings, store, moved, order, ("generate-first", why), "catch-up") is False
            assert lines[-1] == replan_preview.GENERATE_FIRST_CM
            assert dash._replan(settings, store, moved, order, ("generate-first", why), "catch-up") is False
            assert dash_lines[-1] == replan_preview.GENERATE_FIRST
    assert asked == [], "nothing the plan holds moved: the host asks for no Generate (the keeper's own runs)"


def test_a_probe_that_times_out_is_anki_busy_not_closed(lib, monkeypatch):
    """Review 3 R6: Anki open but slow to answer (its own sync, Check Database) is never "closed": a pending S3 stays
    pending, the line says it'll try again, and it does."""
    from app import anki_connect
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
        _move_later_to_top(store)
        real = anki_connect.probe
        monkeypatch.setattr(anki_connect, "probe", lambda url, required=(), timeout=5: {
            "ok": False, "version": None, "missing": [], "error": "timed out", "timed_out": True})
        closed = []
        monkeypatch.setattr(anki_sync_rule, "closed_seen", lambda now=None: closed.append(now))
        host._job("move")
        assert lines[-1] == replan_preview.NOT_ANSWERING and host._retry_at is not None and not closed
        monkeypatch.setattr(anki_connect, "probe", real)


def test_a_review_beginning_before_the_first_request_writes_nothing(lib):
    """Review 3 R12 (S2): a review that starts after the job's guards but before its first request — the review check
    that goes with request 1's re-check stops it: nothing written, the line says so, and the job is retried."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
        for card in fake.cards.values():
            card["mod"] = 1_700_000_500
        _move_later_to_top(store)
        calls = []

        def start_review(ids):
            calls.append(ids)
            if len(calls) == 1:                      # the map's read: the review begins right after it
                fake.reviewing = True
        fake.before_mod_times = start_review
        fake.write_requests.clear()
        host._job("move")
    assert not fake.write_requests, "it wrote into a review"
    assert lines[-1] == replan_preview.REVIEWING and host._retry_at is not None


def test_a_move_behind_tomorrows_cards_says_they_are_already_in_place_while_the_rest_moves():
    """E3.3: a move that leaves tomorrow's cards where they are (nothing pushed out of them, so no front request) never
    says they are being placed — they were in place before the first request; a move that changes them says
    they're placed once their request lands."""
    from types import SimpleNamespace
    from modules.junban import spaced
    host, lines = _host()
    behind = host._progress(SimpleNamespace(front_size=20, kind=spaced.DELTA, front_ids=frozenset()))
    behind(105, 210)
    assert lines[-1] == "Anki: tomorrow's 20 already in place · moving 105 more…"
    ahead = host._progress(SimpleNamespace(front_size=20, kind=spaced.DELTA, front_ids=frozenset(range(20))))
    ahead(10, 140)
    assert lines[-1] == "Anki: placing tomorrow's 20 cards…"
    ahead(20, 140)
    assert lines[-1] == "Anki: tomorrow's 20 cards placed · moving 120 more…"


def test_the_done_line_says_tomorrows_cards_were_placed_whenever_any_of_them_moved():
    """E3.3: a move that placed tomorrow's 20 and moved 120 more says so — however many more there were — and one
    that moved none of tomorrow's says they were already in place."""
    from types import SimpleNamespace
    from modules.junban import spaced
    host, lines = _host()
    job = SimpleNamespace(front_size=20, kind=spaced.DELTA, front_ids=frozenset(range(20)))
    host._said_done({"written": list(range(140))}, job)
    assert lines[-1] == "Anki: tomorrow's 20 cards placed · 120 more moved"
    host._said_done({"written": list(range(100, 205))}, job)
    assert lines[-1] == "Anki: 105 cards moved · tomorrow's 20 already in place"
