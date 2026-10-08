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


def test_another_languages_host_never_touches_the_deck(lib):
    root, store = lib
    _settings_file(root, junban_replan_language="zh")
    fake = _deck(root)
    host, lines = _host()                                    # a Japanese window
    with _patched(fake):
        _move_later_to_top(store)
        host._job("move")
    assert not fake.requests and lines == []


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
        assert len(fake.write_requests) == 1 and host._retry_at is not None
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
    """Pass 4 #13: nothing the plan holds moved — new content says so; a setting (or an update) says press Generate."""
    root, store = lib
    fake = _deck(root)
    host, lines = _host()
    with _patched(fake):
        host._job("catch-up")
    versions, order = replan_preview._snapshot(store)
    settings = host._settings()
    assert host._replan(settings, store, versions, order, ("generate-first", "files"), "catch-up") is False
    assert lines[-1] == replan_preview.NEW_CONTENT
    assert host._replan(settings, store, versions, order, ("generate-first", "settings"), "catch-up") is False
    assert lines[-1] == replan_preview.PRESS_GENERATE


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
