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
from modules.junban.tests.test_reposition import URL, _collection, _patched  # noqa: E402
from modules.junban.tests.test_spaced_runs import ModCollection  # noqa: E402
from tests import plan_file_cases as cases  # noqa: E402

CASE = "rp2-ja"
DECK = "TheBank"


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
    settings = {"junban_replan_preview": True, "junban_deck": DECK, "junban_scope": "deck",
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
        path = os.path.join(get_data_path("ja"), "HighPriority", "new_episode.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("新しい話が始まった。今日は学校で友達に会った。\n")
        library_store.sync_for_window(store)
        dash._seen = None
        dash._anki_looked = -1e9
        dash._job("catch-up")
        new_files_alone = list(asked)
        _move_later_to_top(store)
        dash._job("catch-up")
    assert new_files_alone == [], "a new file with no move owed started an automatic Generate"
    assert replan_preview.NEW_CONTENT in lines
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
