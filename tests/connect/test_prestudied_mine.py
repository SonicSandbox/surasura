"""PRESTUDIED-MINE (3.0.20, Sonic § 101 2; PROVISIONAL words): *Mine only episodes I've pre-studied*.

A learner who goes through an episode in the journey first (marking the words he knows and the ones to leave out)
asks that Connect make that episode's cards only then — never cards he wasn't ready for. The switch (Settings › Anki,
beside *Keep up to*, off by default) holds every episode Connect would mine on its own until the journey marks it
pre-studied (the library store's J-STORE mark): it waits, named on its stone, never dropped or deleted. A press is the
yes (*Mine now*, *Mine anyway*, the journey's ⇄ / *Add now*), and Best's own jobs and REMAKE's re-mines (`level.BEST`)
carry words of an episode already let through. A mark — a press on the stone, or the end card — kicks Connect, and
the parked wait goes again at once.

What a wrong answer would cost the learner: cards made from an episode he hasn't studied yet (the thing he asked to
avoid); an episode he marked that never gets its cards, or only at the next start; a switch that is off changing
what Connect mines; a waiting episode dropped, so it never comes back; a *Mine now* ignored.

The runner tests use `FakeSteps` (real Japanese words, synthetic titles); the store and route tests the suite's real
Japanese and Chinese subtitles under the per-test SURASURA_TEST_ROOT. Never a live Anki.
"""
import pytest

from app import settings_manager
from app.connect import level, runner
from app.connect.ledger import ASKED, SHOW, Ledger
from app.services import prestudied
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import WORDS, FakeSteps

KEY = "connect_prestudied_only"


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan, looks=1, sleep=None):
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=sleep or (lambda s: None), looks=looks)
    return steps, summary


def _jobs(ledger):
    return {j["item_id"]: (j["state"], j.get("reason")) for j in ledger.jobs("ja")}


def _mined(steps):
    return [e[1] for e in steps.log if e[0] == "mine"]


# --- the runner's gate ----------------------------------------------------------------------------------------- #

def test_off_by_default_every_episode_mines_as_before(tmp_path, ledger):
    # the switch off (and absent from the plan): nothing waits for a mark — results and cards as before
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}}
    steps, summary = _run(tmp_path, ledger, plan)
    assert sorted(summary["languages"]["ja"]["done"]) == [1, 2]
    assert sorted(_mined(steps)) == [1, 2]
    plan = {"line": {"ja": [3]}, "queue": {"ja": [3]}, "prestudied_only": False, "prestudied": []}
    steps, summary = _run(tmp_path, ledger, plan)
    assert summary["languages"]["ja"]["done"] == [3]


def test_on_only_the_marked_episode_mines_the_others_wait_named_never_dropped(tmp_path, ledger):
    # 1 and 3 never marked, 2 marked: 2 mines though it is below 1 in the line; 1 and 3 wait with the reason
    plan = {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}, "prestudied_only": True, "prestudied": [2]}
    steps, summary = _run(tmp_path, ledger, plan)
    out = summary["languages"]["ja"]
    assert out["done"] == [2] and _mined(steps) == [2]
    assert out["waiting"] == {1: runner.NOT_PRESTUDIED, 3: runner.NOT_PRESTUDIED}
    assert out["dropped"] == [] and out["skipped"] == []
    jobs = _jobs(ledger)
    assert jobs[1] == jobs[3] == ("waiting", runner.NOT_PRESTUDIED)
    assert not any(e[0] == "pick" and e[1] in (1, 3) for e in steps.log), "a waiting episode is never picked"
    assert not runner.holds_every(runner.NOT_PRESTUDIED), "one episode's wait, never the language's"


def test_a_run_whose_every_episode_waits_for_a_mark_ends_no_2_minute_look(tmp_path, ledger):
    # the wait is parked for the run: no surasura-cli looking every 2 minutes for a mark that may never come
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "prestudied_only": True, "prestudied": []}

    def no_pause(seconds):
        raise AssertionError(f"Connect paused {seconds} s to look again for a mark")
    steps, summary = _run(tmp_path, ledger, plan, looks=None, sleep=no_pause)
    assert summary["looks"] == 1 and summary["languages"]["ja"]["waiting"] == {1: runner.NOT_PRESTUDIED,
                                                                               2: runner.NOT_PRESTUDIED}


def test_marked_later_it_mines_at_the_next_start_and_a_kick_lets_a_parked_wait_go(tmp_path, ledger):
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "prestudied_only": True, "prestudied": []}
    _run(tmp_path, ledger, plan)
    assert _jobs(ledger)[1] == ("waiting", runner.NOT_PRESTUDIED)
    # a Connect still running: the journey's mark kicks it, and the parked wait goes again at once (`_woken`)
    steps = FakeSteps(str(tmp_path), plan)
    job = ledger.jobs("ja")[0]
    parked = {job["id"]: None}
    steps.kicked = lambda: True
    runner._woken(steps, ledger, parked)
    assert parked == {}, "a kick lets a pre-study wait go again"
    # the next look (or the next start) mines it, now marked
    plan["prestudied"] = [1]
    steps, summary = _run(tmp_path, ledger, plan)
    assert summary["languages"]["ja"]["done"] == [1] and _mined(steps) == [1]


def test_un_marked_before_its_mining_it_waits_again_and_the_switch_off_lets_it_go(tmp_path, ledger):
    # 2 marked, then un-marked before Connect came to it: it waits; 1 mines
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}, "prestudied_only": True, "prestudied": [1]}
    steps, summary = _run(tmp_path, ledger, plan)
    assert summary["languages"]["ja"]["done"] == [1] and _jobs(ledger)[2] == ("waiting", runner.NOT_PRESTUDIED)
    # the switch turned off: the waiting one goes (Settings' write kicks: RELEASE_KEYS)
    plan["prestudied_only"] = False
    steps, summary = _run(tmp_path, ledger, plan)
    assert summary["languages"]["ja"]["done"] == [2]


def test_a_press_is_the_yes_mine_now_on_an_unmarked_episode_mines(tmp_path, ledger):
    with ledger.transaction():
        ledger.ask("ja", 1, "2026-11-26T10:00:00.000000Z", store_id="store-1")
    plan = {"line": {"ja": [1]}, "prestudied_only": True, "prestudied": []}
    _steps, summary = _run(tmp_path, ledger, plan)
    assert summary["languages"]["ja"]["done"] == [1]


def test_mine_anyway_on_an_unmarked_episode_is_a_yes_too(tmp_path, ledger):
    # *Mine anyway* (a not-timed episode's press: `actions.mine_anyway` sets the pick's `forced`) — your press
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "prestudied_only": True, "prestudied": []}
    steps = FakeSteps(str(tmp_path), plan)
    steps.consume("ja", ledger)
    job = ledger.jobs("ja")[0]
    ledger.set_state(job["id"], "queued", picked={"forced": True})
    plan.pop("queue")
    _steps, summary = _run(tmp_path, ledger, plan)
    assert summary["languages"]["ja"]["done"] == [1]


def test_held_by_prestudy_is_the_one_rule_connects_own_picks_only():
    assert runner.held_by_prestudy({"kind": "mine"})                        # the line's
    assert runner.held_by_prestudy({"kind": SHOW})                          # a show's earlier part (Michi-EO)
    assert runner.held_by_prestudy({"kind": "level", "source": level.NEW_FILES})
    assert not runner.held_by_prestudy({"kind": ASKED})                     # *Mine now* / *Mine it too*
    assert not runner.held_by_prestudy({"kind": "mine", "asked_at": "2026-11-26T10:00:00Z"})
    assert not runner.held_by_prestudy({"kind": "swap"})                    # ⇄, *Add now*, the loop's swap
    # Best's book line and REMAKE's re-mine: words of an episode already let through (or a card you had)
    assert not runner.held_by_prestudy({"kind": "level", "source": level.BEST})


def test_a_best_sentence_job_on_an_unmarked_book_part_still_mines(tmp_path, ledger):
    # a word of a marked episode whose best line is in an unmarked book part: its BEST job is not held
    with ledger.transaction():
        ledger.queue_level("ja", 7, [WORDS[1][0]], source=level.BEST, store_id="store-1")
    plan = {"line": {"ja": []}, "prestudied_only": True, "prestudied": []}
    steps, summary = _run(tmp_path, ledger, plan)
    assert summary["languages"]["ja"]["done"] == [7] and _mined(steps) == [7]


# --- the real store and settings ----------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", ("ja", "zh"))
def test_steps_read_the_journeys_mark_from_the_real_store(language):
    c.library(language)
    with c.store(language) as s:
        a, b = s.ids("now")[:2]
        s.set_prestudied([a], True, "press")
    on = runner.Steps({KEY: True}, live=False)
    off = runner.Steps({}, live=False)
    assert on.prestudied_only(language) is True and off.prestudied_only(language) is False
    assert on.prestudied(language, a) is True and on.prestudied(language, b) is False
    # the end card's mark counts as a press's; an un-mark is no mark
    with c.store(language) as s:
        s.set_prestudied([b], True, "end")
        s.set_prestudied([a], False, "press")
    assert on.prestudied(language, b) is True and on.prestudied(language, a) is False


def test_the_setting_is_off_by_default_and_read_through_one_helper():
    assert settings_manager.DEFAULT_SETTINGS[KEY] is False
    assert settings_manager.prestudied_only({}) is False
    assert settings_manager.prestudied_only(None) is False
    assert settings_manager.prestudied_only({KEY: True}) is True
    assert settings_manager.prestudied_only({KEY: "yes"}) is False, "only a real True turns it on"


def test_the_switch_never_moves_a_run_and_its_change_lets_waiting_episodes_go():
    from app import analyzer, settings_placement
    from app.qt import settings_store
    base = settings_manager.load_settings()
    assert analyzer.settings_signature(dict(base, **{KEY: True}), "ja") == analyzer.settings_signature(
        dict(base, **{KEY: False}), "ja"), "results/ unchanged: never in the run signature"
    assert settings_placement.PLACED[KEY] == "neither"
    assert KEY in settings_store.RELEASE_KEYS
    assert settings_store.releases({KEY: True}, {KEY: False})
    assert settings_store.releases({KEY: False}, {KEY: True})


def test_the_row_sits_beside_keep_up_to_in_settings_anki_shown_with_connect():
    from app.qt import settings_catalog as catalog
    from app.qt import settings_strings as S
    ids = [r.id for r in catalog.ROWS if r.section == "anki"]
    assert KEY in ids and abs(ids.index(KEY) - ids.index("connect_backlog_cap")) == 1, "beside Keep up to"
    row = next(r for r in catalog.ROWS if r.id == KEY)
    assert row.kind == "toggle" and row.keys == (KEY,) and not row.adv
    label, help_ = S.ROWS[KEY][:2]
    assert label == "Mine only episodes I’ve pre-studied" and help_, "its line behind the ?"


# --- the journey's mark kicks Connect ----------------------------------------------------------------------- #

class _App:
    def __init__(self, language):
        self._language = language

    def language(self):
        return self._language


@pytest.mark.parametrize("language", ("ja", "zh"))
def test_a_mark_from_the_journey_kicks_connect_while_the_switch_is_on(language, monkeypatch):
    from app.connect import kick
    kicks = []
    monkeypatch.setattr(kick, "kick", lambda settings, videos=False: kicks.append(dict(settings)))
    c.library(language, **{KEY: True})
    with c.store(language) as s:
        a, b = s.ids("now")[:2]
    prestudied.door_route({"id": a, "on": True, "why": "end"}, _App(language))
    assert len(kicks) == 1 and kicks[0].get(KEY) is True, "the end card's mark: Connect looks at once"
    prestudied.door_route({"id": a, "on": True, "why": "end"}, _App(language))
    assert len(kicks) == 1, "nothing changed: no kick"
    out = prestudied.door_route({"id": a, "on": False, "why": "press"}, _App(language))
    assert len(kicks) == 1, "an un-mark lets nothing go"
    prestudied.door_undo({"undo_id": out["undo_id"]}, _App(language))
    assert len(kicks) == 2, "its Undo marks it again"
    h.write_settings(target_language=language, connect_enabled=True, **{KEY: False})
    prestudied.door_route({"id": b, "on": True, "why": "press"}, _App(language))
    assert len(kicks) == 2, "the switch off: a mark changes nothing Connect does"
