"""P3.3 row 3.3.7: the proofs — Connect's whole loop on the fast re-plan (K78; F11; E2.2-1 (b)).

On a real library (tests/plan_file_cases.py's RP-2 Japanese library, generated once, as `tests/test_replan_preview.py`'s
`lib` builds it) with the Junban suite's fake AnkiConnect (`ModCollection`: real state, every write checked) and
Connect's own steps — the session's known-sync, the pick, the store, Junban's re-order — real; only where Anki Miner
sits (the video, the fit check, the batch, Backfill) a stand-in that makes one note a word. What these prove:

  (a) a burst of five moves → one Connect run: no Generate and no analyzer child in the loop; every pick ranks by the
      engine; Anki ordered from its rows (Anki holds them after); `record_planned` at the order it wrote;
  (b) parity: a full Generate afterwards writes the very lists Connect used (the plan columns), and the re-order from
      its plan writes nothing;
  (c) E2.2-1 (b)'s overlaps: a move made during the Generate after mining is served by the follow-up at its time, and
      Anki ends where a full Generate of the final order puts it; a Generate landing between Connect's re-plan and its
      write → `record_planned` never claims the newer order, the step orders once more from the newer plan, Anki ends
      at the final order;
  (d) the first review's M1: a newer order the window's host planned and wrote while Connect waited for the writer
      lock → Connect re-plans and orders once more — once, never a loop — and Anki ends at the newest order's
      Generate; one recipe: the window's re-order host and Connect re-plan by one recipe (the same rows and places).

What a wrong answer would cost: a full Generate for every move holding the cards back; cards made or ordered by ranks
no list ever had; an order recorded as planned that Anki doesn't hold (the window's host then never fixes it).
"""
import json
import os
import time
from unittest import mock

import pytest

pytest.importorskip("modules.junban")

from app import settings_manager  # noqa: E402
from app.cli import verbs  # noqa: E402
from app.connect import anki_session, fit_check, runner  # noqa: E402
from app.connect.ledger import Ledger  # noqa: E402
from app.services import journey  # noqa: E402
from modules.junban import auto, reposition, spaced  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402
from tests.test_replan_preview import (_deck, _generate, _junban_settings, _move_later_to_top,  # noqa: E402,F401
                                       _settings_file, lib)

EPISODES = ("gotoubun_ep01.srt", "gotoubun_ep02.srt", "gotoubun_ep03.srt", "phrases_sample.srt")


class AnkiMinerStandIn(runner.Steps):
    """Connect's real steps, with a stand-in where Anki Miner and the outside world sit: the jobs queued for the
    library's four subtitles (the inbox), no video or fit check to look at, one made note a word, no Backfill, no
    shelf. Every pick's words and the plan it ranked by are kept (`picks`)."""

    def __init__(self, loaded, items):
        super().__init__(loaded)
        self.items, self.queued, self.picks, self.note = list(items), set(), [], 900000

    def lower_priority(self):
        pass

    def blocked(self, lang):
        return None

    def after_write(self, lang):
        pass

    def miner_found(self):
        return True

    def cap(self, lang=None):
        return 0

    def consume(self, lang, ledger):
        store_id = self.store_id(lang)
        for item in self.items:
            if item not in self.queued:
                self.queued.add(item)
                with ledger.transaction():
                    ledger.queue(lang, item, "user", None, store_id=store_id)

    def notes_gone(self, lang):
        return []

    def shelf_session(self, lang, ledger):
        pass

    def video(self, lang, job):
        return f"episode-{job['item_id']}.mkv"

    def pick(self, lang, job, video):
        got = super().pick(lang, job, None)         # no video: no Anki Miner asked at the pick
        plan = self.current(lang)
        self.picks.append(([(w["word"], w["reading"]) for w in got["words"]], plan.listed))
        return dict(got, profile="p1", anki_miner="3.7.0", absent=False)

    def fit(self, lang, job, pairing, video, subtitle):
        return (fit_check.TIMED, "hato", None, 0.0)

    def mine(self, lang, job, picked, words, attempt):
        out = []
        for w in words:
            self.note += 1
            out.append({"word": w["word"], "reading": w["reading"], "outcome": "made", "note_id": self.note,
                        "line_start": w.get("line_start")})
        return {"outcomes": out, "app": "3.7.0", "doubt": False, "tag_pending": []}

    def name_media(self, lang, job, picked, lines):
        return None

    def fill(self, lang, job, note_ids):
        pass


def _burst(store, moves=5):
    """A burst of moves in the window: 6+ Months' last item to the top of NOW, then NOW's last to its top, by turns."""
    for n in range(moves):
        if n % 2 == 0 and store.ids("goal"):
            _move_later_to_top(store)
        else:
            store.move([store.ids("now")[-1]], "now", before_id=store.ids("now")[0])


def _episodes(store):
    by_name = {}
    for tier in ("now", "soon", "goal"):
        for item in store.ids(tier):
            name = str((store.item(item) or {}).get("rel_path") or "").replace("\\", "/").rsplit("/", 1)[-1]
            by_name[name] = item
    return [by_name[name] for name in EPISODES]


@pytest.fixture
def connect(lib, monkeypatch, tmp_path):
    """Connect on, its session's Anki parts out of the way (P2.3's own suites), the Generate and its child spied."""
    root, store = lib
    _settings_file(root, connect_enabled=True)
    from app.cli import contract
    os.makedirs(contract.log_folder(), exist_ok=True)       # the command line's own start makes it
    monkeypatch.setattr(runner, "_release_check", lambda loaded: None)
    monkeypatch.setattr(anki_session, "begin", lambda url, loaded: None)
    monkeypatch.setattr(verbs, "_session", lambda loaded: None)
    monkeypatch.setattr(verbs, "known_sync", lambda ns: {"added": 0})
    generates = []
    real = verbs.generate

    def generate(ns):
        generates.append(ns.lang)
        return real(ns)
    monkeypatch.setattr(verbs, "generate", generate)
    return root, store, generates, str(tmp_path / "ledger.sqlite")


def _run(steps, ledger_path):
    with Ledger(ledger_path) as ledger:
        summary = runner.run(steps.loaded, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        owed = ledger.resort_owed("ja")
    return summary, owed


def _anki_holds(rows):
    """Does Anki hold the order `rows` give (Junban plans no write from them)?"""
    writes, _stats = reposition.dry_run(_junban_settings(), job=spaced.Job(automatic=True, rows=rows))
    return not writes


def _loaded():
    return dict(settings_manager.load_settings())


def test_a_burst_of_moves_is_one_run_with_no_generate_picks_by_the_engine_and_anki_ordered_from_its_rows(
        connect, monkeypatch):
    root, store, generates, ledger_path = connect
    fake = _deck(root)
    items = _episodes(store)
    children = []
    _burst(store)
    steps = AnkiMinerStandIn(_loaded(), items)
    with _patched(fake), mock.patch.object(verbs, "child_command", lambda argv: children.append(argv)):
        summary, owed = _run(steps, ledger_path)
        used = steps.current("ja")
        held = _anki_holds(used.rows("content"))
    assert sorted(summary["languages"]["ja"]["done"]) == sorted(items), summary     # in the top 20's order
    assert generates == [] and children == [], "no Generate in the loop for moves (K78)"
    assert len(steps.picks) == 4 and all(words for words, _plan in steps.picks)
    for words, listed in steps.picks:
        ranks = [listed[k] for k in words]
        assert ranks == sorted(ranks), "every pick ranked by the engine"
    assert used.generate == "no" and fake.writes and held, "Anki holds the engine's rows"
    versions = store.versions()
    assert versions["planned_order_version"] == versions["order_version"], "record_planned at the order written"
    assert owed is None
    # (b) parity: a full Generate of the same order writes the lists Connect used, and its re-order writes nothing
    store.close()
    _generate(root)
    assert journey._differs(used.result, journey._lists()) == "", "the plan columns are the Generate's"
    fake.write_requests.clear()
    after = AnkiMinerStandIn(_loaded(), [])
    with _patched(fake):
        assert after.current("ja").generate == "no"
        after.order("ja", None)
    assert not fake.write_requests, "the follow-up after the Generate wrote nothing: Anki already held it"


def _known_changed(root):
    known = os.path.join(root, "User Files", "ja", "KnownWord.json")
    with open(known, encoding="utf-8") as f:
        data = json.load(f)
    with open(known, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)          # a new stat: the known words "changed"
    os.utime(known, (time.time() + 5, time.time() + 5))


def test_a_move_during_the_generate_after_mining_is_served_by_the_follow_up_at_its_time(connect, monkeypatch):
    root, store, generates, ledger_path = connect
    fake = _deck(root)
    items = _episodes(store)
    _known_changed(root)                             # known words came in: re-plan now, Generate after mining
    real = verbs.generate
    moved = []

    def generate_then_move(ns):
        out = real(ns)
        moved.append(_move_later_to_top(store))      # the analyzer read the order; you move again meanwhile
        return out
    monkeypatch.setattr(verbs, "generate", generate_then_move)
    steps = AnkiMinerStandIn(_loaded(), items)
    with _patched(fake):
        summary, owed = _run(steps, ledger_path)
        follow_up = steps.current("ja")
    assert moved and sorted(summary["languages"]["ja"]["done"]) == sorted(items), summary
    assert follow_up.generate == "no" and follow_up.versions["order_version"] == store.versions()["order_version"]
    assert owed is None, "the follow-up re-order landed"
    # Anki ends where a full Generate of the final order puts it
    store.close()
    _generate(root)
    from app.connect import replan
    from app.connect import library
    with library.open_store("ja") as fresh:
        final = replan.current("ja", dict(_loaded(), target_language="ja"), fresh)
    assert final.generate == "no"
    with _patched(fake):
        assert _anki_holds(final.rows("content")), "Anki holds the final order's Generate"


def test_a_generate_landing_between_the_re_plan_and_its_write_is_never_recorded_as_written(connect, monkeypatch):
    root, store, generates, ledger_path = connect
    fake = _deck(root)
    steps = AnkiMinerStandIn(_loaded(), [])
    _move_later_to_top(store)
    real = auto.reorder
    landed = []

    def window_meanwhile(settings, **kwargs):
        if not landed:                               # the window's keeper: a move and its Generate, before the write
            landed.append(_move_later_to_top(store))
            _generate(root)
        return real(settings, **kwargs)
    monkeypatch.setattr(auto, "reorder", window_meanwhile)
    recorded = []
    real_record = verbs._record_planned
    monkeypatch.setattr(verbs, "_record_planned", lambda lang, versions: recorded.append(versions["order_version"])
                        or real_record(lang, versions))
    with _patched(fake):
        first = steps.current("ja")
        steps.order("ja", None)                      # the store moved while it wrote: re-planned, ordered once more
        versions = store.versions()
        assert versions["order_version"] > first.versions["order_version"]
        assert recorded == [first.versions["order_version"], versions["order_version"]], \
            "each write recorded at the order it wrote, never a newer one"
        again = steps.current("ja")
        assert again is not first and again.versions["order_version"] == versions["order_version"]
        versions = store.versions()
        assert versions["planned_order_version"] == versions["order_version"]
        assert _anki_holds(again.rows("content")), "Anki holds the final order's"
    store.close()
    _generate(root)                                  # nothing moved since: the final order's Generate is the same run
    from app.connect import library, replan
    with library.open_store("ja") as fresh:
        final = replan.current("ja", dict(_loaded(), target_language="ja"), fresh)
    with _patched(fake):
        assert _anki_holds(final.rows("content"))
    assert journey._differs(again.result, journey._lists()) == ""


def _newer_meanwhile(store, monkeypatch, times=1):
    """The window's re-order host while Connect waits for `anki-writer`: you move, it plans and writes that newer order
    (recorded planned) — during the first `times` of Connect's writes. Returns the jobs Connect's writes ran."""
    real = auto.reorder
    jobs = []

    def host_meanwhile(settings, **kwargs):
        jobs.append(kwargs.get("job"))
        if len(jobs) <= times:
            store.move([store.ids("now")[-1]], "now", before_id=store.ids("now")[0])
            versions = store.versions()
            store.record_planned(versions["order_version"], versions["pins_version"])
        return real(settings, **kwargs)
    monkeypatch.setattr(auto, "reorder", host_meanwhile)
    return jobs


def test_a_newer_order_the_window_wrote_while_connect_waited_is_ordered_once_more(connect, monkeypatch):
    # why (review M1): `record_planned` keeps the larger value, so the store said "planned" at the host's newer order
    # while Anki held Connect's older one — and nobody re-ordered until the next move
    root, store, generates, ledger_path = connect
    fake = _deck(root)
    steps = AnkiMinerStandIn(_loaded(), [])
    _move_later_to_top(store)
    jobs = _newer_meanwhile(store, monkeypatch)
    with _patched(fake):
        first = steps.current("ja")
        steps.order("ja", None)
        final = steps.current("ja")
        assert len(jobs) == 2, "ordered once more, from the newer plan"
        assert jobs[1].rows == final.rows("content") != first.rows("content")
        assert final.versions["order_version"] == store.versions()["order_version"] > first.versions["order_version"]
        assert _anki_holds(final.rows("content")), "Anki holds the newest order"
    versions = store.versions()
    assert versions["planned_order_version"] == versions["order_version"]
    store.close()
    _generate(root)                                  # the newest order's full Generate: Anki holds its order
    from app.connect import library, replan
    with library.open_store("ja") as fresh:
        newest = replan.current("ja", dict(_loaded(), target_language="ja"), fresh)
    assert newest.generate == "no"
    with _patched(fake):
        assert _anki_holds(newest.rows("content"))


def test_ordering_once_more_is_once_never_a_loop(connect, monkeypatch):
    root, store, generates, ledger_path = connect
    fake = _deck(root)
    steps = AnkiMinerStandIn(_loaded(), [])
    _move_later_to_top(store)
    jobs = _newer_meanwhile(store, monkeypatch, times=5)     # the host writes a newer order during every write
    with _patched(fake):
        assert steps.order("ja", None) is None
    assert len(jobs) == 2, "once more, then it's the next look's"


def test_the_window_and_connect_re_plan_by_one_recipe(lib):
    # why (S5 / S11): were Connect's ranking to drift from the window's re-order host's, each would undo
    # the other's order in Anki on every move
    root, store = lib
    fake = _deck(root)
    from tests.test_replan_preview import _host
    _burst(store)
    host, _lines = _host()
    jobs = []
    real_write = host._write

    def write(settings, job, kind):
        jobs.append(job)
        return real_write(settings, job, kind)
    host._write = write
    with _patched(fake):
        host._job("catch-up")
    from app.connect import library, replan
    with library.open_store("ja") as fresh:
        got = replan.current("ja", dict(_loaded(), target_language="ja"), fresh)
    assert jobs and got.generate == "no", got.reason
    assert jobs[-1].rows == got.rows("content"), "the same Junban rows"
    assert jobs[-1].places == got.places, "the same RP-10 places"
