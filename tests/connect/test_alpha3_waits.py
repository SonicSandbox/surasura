"""Alpha 2's first try (Sonic, 2026-10-24; `_work/alpha2-try/FEEDBACK-2026-10-24.md` T1–T3): what the phase strip's
Anki and Anki Miner (鉱) circles say of Connect's episodes, and the row of the episode being mined.

- T1: the Anki circle turned amber ("needs you") with Anki open, "Waiting for Anki (19)" — Connect was waiting while
  he reviewed. Amber only for a wait he must act on (Anki closed, a permission prompt, another profile or none named);
  one that clears by itself (you reviewing, Anki busy, another program writing, one slow answer) is a still arc. Its
  words are the wait's own reason and what the number counts: "Waiting while you review in Anki · 19 episodes".
- T2: "Waiting to make its cards (2)" read as 2 cards. It is 2 episodes, and the words say why they wait (their turn,
  Connect's next look, its next start, Anki Miner's window open …), from Connect's record.
- T3: the 鉱 circle's hover names the episode being mined; that episode's row shows *Mining* — also when it is an
  episode already in Anki that a level raise mines again.

What a wrong answer would cost: amber that sends the learner looking for a problem that isn't there (or none when
Anki is closed and nothing will ever be made); a count read as cards; a strip that mines while no row says where.

Real ledgers under the test root with the runner's own reasons, Japanese and Chinese stores built from the suite's
files (`connect_helpers`); the rows from `view_rows.build` over Connect's feed as the window gets it.
"""
import os
import time

import pytest

from app.connect import anki_session, feed, runner, status
from app.connect.ledger import Ledger
from app.services import phase as P
from app.services import status as S
from app.services import view_rows as vr
from app.services.jobs import JobRegistry
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

ON = {"connect_enabled": True}
WORDS = [{"word": "冒険", "reading": "ボウケン"}, {"word": "散歩", "reading": "サンポ"}]

# Every wait on Anki the runner and the Anki session name, and whether it waits on you (amber)
NEEDS_YOU = [runner.ANKI_CLOSED, anki_session.CLOSED, anki_session.UNUSABLE,
             anki_session.OTHER_PROFILE.format("日本語", "User 1"), anki_session.NO_PROFILE_YET,
             anki_session.NO_PROFILE_DECKS]
CLEARS_BY_ITSELF = [runner.REVIEWING, anki_session.REVIEWING, anki_session.BUSY, runner.WRITER_BUSY,
                    runner.ANKI_SLOW]


@pytest.fixture
def running(monkeypatch):
    state = {"on": True}
    monkeypatch.setattr(status, "running", lambda: state["on"])
    return state


def _items(lang, n=10):
    c.library(lang, extra=n)
    with c.store(lang) as s:
        return s.ids("now")


def _job(ledger, lang, item, state, reason=None):
    jid = ledger.queue(lang, item, "user", None)
    if state != "queued":
        ledger.set_state(jid, state, **({"reason": reason} if reason else {}))
    return jid


def _strip(got):
    """The phase strip as the window draws it from this feed: Connect's waits mirrored into a registry, read a few
    seconds on (an automatic wait shows after REVEAL_S)."""
    registry = JobRegistry()
    S.mirror_connect(registry, got)
    return P.read(registry.snapshot(), now=time.time() + 5)


# --- T1: which waits on Anki are amber ---------------------------------------------------------------------------- #
@pytest.mark.parametrize("reason", NEEDS_YOU)
def test_an_anki_wait_you_must_act_on_is_needs_you(reason):
    assert runner.anki_wait(reason) and runner.anki_needs_you(reason)


@pytest.mark.parametrize("reason", CLEARS_BY_ITSELF)
def test_an_anki_wait_that_clears_by_itself_never_needs_you(reason):
    assert runner.anki_wait(reason) and not runner.anki_needs_you(reason)


@pytest.mark.parametrize("reason", [runner.ON_BATTERY, runner.ANKI_MINER_OPEN, runner.TURN, None, ""])
def test_no_other_wait_is_an_anki_wait_you_must_act_on(reason):
    assert not runner.anki_needs_you(reason)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_you_reviewing_is_a_still_arc_on_the_anki_circle_saying_why_and_how_many_episodes(running, lang):
    """T1: Sonic's 19 episodes waiting while he reviewed: the Anki circle waits (a still arc), never amber; its line is
    the wait's own reason and the count in episodes."""
    ids = _items(lang)
    with Ledger() as ledger:
        for item in ids[:3]:
            _job(ledger, lang, item, "waiting", runner.REVIEWING)
    got = feed.Provider(lang, lambda: ON).feed()
    assert {got.items[i].kind for i in ids[:3]} == {feed.ANKI_WAIT}
    anki = _strip(got)[P.ANKI]
    assert anki.waiting and not anki.needs, "a wait that clears by itself is a still arc, never amber"
    assert anki.lines == (f"{S.CONNECT_WAIT_LABEL} · Waiting while you review in Anki · 3 episodes",)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_anki_closed_is_amber_and_says_so_beside_the_ones_that_clear_by_themselves(running, lang):
    ids = _items(lang)
    with Ledger() as ledger:
        _job(ledger, lang, ids[0], "waiting", runner.REVIEWING)
        _job(ledger, lang, ids[1], "waiting", anki_session.BUSY)
        _job(ledger, lang, ids[2], "waiting", runner.ANKI_CLOSED)
        _job(ledger, lang, ids[3], "waiting", runner.ANKI_CLOSED)
    got = feed.Provider(lang, lambda: ON).feed()
    assert [got.items[i].kind for i in ids[:4]] == [feed.ANKI_WAIT, feed.ANKI_WAIT, feed.ANKI, feed.ANKI]
    anki = _strip(got)[P.ANKI]
    assert anki.needs == "Waiting for Anki: it isn't open · 2 episodes", "amber names only what waits on you"
    assert set(anki.lines) == {f"{S.CONNECT_WAIT_LABEL} · Waiting for Anki: it isn't open · 2 episodes",
                               f"{S.CONNECT_WAIT_LABEL} · Waiting while you review in Anki · 1 episode; "
                               f"Waiting for Anki: it's busy · 1 episode"}


def test_a_row_waiting_while_you_review_is_a_plain_waiting_and_one_waiting_on_closed_anki_is_amber():
    """The rows follow the same rule: *Waiting* amber only while Anki waits on you; both keep *Mine now*'s hover."""
    items = items_of([("now", 1, 1, ["星降る街の小さな工房 - 01.srt", "星降る街の小さな工房 - 02.srt"], {})])
    connect = _feed([_job_row(1, reason=runner.REVIEWING), _job_row(2, reason=runner.ANKI_CLOSED)])
    st = {e.id: e.status for r in vr.build(items, {}, {"mine_line": 20}, connect=connect).rows for e in r.episodes}
    assert (st[1].kind, st[1].tone, st[1].tip) == (
        "waiting", "dim", vr.STRINGS["tip_ask_anki"].format(tip=runner.REVIEWING))
    assert (st[2].kind, st[2].tone, st[2].tip) == (
        "waiting", "warn", vr.STRINGS["tip_ask_anki"].format(tip=runner.ANKI_CLOSED))


# --- T2: the count is episodes, and the reason is Connect's -------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_episodes_waiting_their_turn_say_so_and_count_episodes_never_cards(running, lang):
    ids = _items(lang)
    with Ledger() as ledger:
        jid = _job(ledger, lang, ids[0], "mining")
        ledger.set_state(jid, "mining", picked={"words": WORDS})
        _job(ledger, lang, ids[1], "queued")
        _job(ledger, lang, ids[2], "queued")
    got = feed.Provider(lang, lambda: ON).feed()
    miner = _strip(got)[P.MINER]
    waiting = [ln for ln in miner.lines if ln.startswith(S.CONNECT_WAIT_LABEL)]
    assert waiting == [f"{S.CONNECT_WAIT_LABEL} · {runner.TURN.rstrip('.')} · 2 episodes"]
    assert "(2)" not in " ".join(miner.lines) and "cards (" not in " ".join(miner.lines)


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("is_running, name", [(True, "NEXT_LOOK"), (False, "NEXT_START")])
def test_an_episode_with_no_reason_yet_says_when_connect_comes_to_it(running, lang, is_running, name):
    """No reason of its own and nothing in flight: queued since Connect's last look. While Connect runs it is read at
    its next look (within its 2 minutes); while it isn't, at its next start (a *Mine now* starts it)."""
    words = getattr(feed, name)
    running["on"] = is_running
    ids = _items(lang)
    with Ledger() as ledger:
        _job(ledger, lang, ids[0], "queued")
        _job(ledger, lang, ids[1], "queued")
    got = feed.Provider(lang, lambda: ON).feed()
    assert got.items[ids[0]].tip == words, "the row's hover says it too"
    miner = _strip(got)[P.MINER]
    assert miner.waiting and not miner.needs
    assert miner.lines == (f"{S.CONNECT_WAIT_LABEL} · {words.rstrip('.')} · 2 episodes",)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_other_reasons_pass_through_grouped_one_episode_said_as_one(running, lang):
    """Anki Miner's own window open, on battery: each its own words and count (battery stays a still arc)."""
    ids = _items(lang)
    with Ledger() as ledger:
        _job(ledger, lang, ids[0], "waiting", runner.ANKI_MINER_OPEN)
        _job(ledger, lang, ids[1], "waiting", runner.ANKI_MINER_OPEN)
        _job(ledger, lang, ids[2], "waiting", runner.ON_BATTERY)
    miner = _strip(feed.Provider(lang, lambda: ON).feed())[P.MINER]
    assert miner.waiting and not miner.needs
    assert miner.lines == (f"{S.CONNECT_WAIT_LABEL} · Anki Miner is open: close it to make cards · 2 episodes; "
                           f"On battery: cards are made once this computer is plugged in · 1 episode",)


# --- T3: the episode being mined is named, and its row shows it ----------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_miner_circles_line_names_the_episode_being_mined(running, lang):
    ids = _items(lang)
    with Ledger() as ledger:
        jid = _job(ledger, lang, ids[0], "mining")
        ledger.set_state(jid, "mining", picked={"words": WORDS})
    with c.store(lang) as s:
        name = os.path.basename(s.item(ids[0])["rel_path"])
    got = feed.Provider(lang, lambda: ON).feed()
    assert got.items[ids[0]].title == name
    miner = _strip(got)[P.MINER]
    assert miner.running
    assert len(miner.lines) == 1 and miner.lines[0].startswith(f"{S.CONNECT_JOB_LABEL} · {name}")


def test_the_mining_line_names_the_episode_with_its_step_and_percent():
    item = feed.Item(feed.MINING, feed.WORDS[feed.MINING], "", 7, 0, 0, 94, "Filling fields", title="Re:Zero 52")
    miner = _strip(feed.Feed(on=True, mining=frozenset({1}), items={1: item}, line="", state="working", unseen=0,
                             updating=False))[P.MINER]
    assert miner.lines == ("Making cards · Re:Zero 52 · Filling fields 94%",)


def items_of(spec):
    out, iid, ord_ = {}, 1, 0.0
    for tier, wid, pid, names, extra in spec:
        for k, name in enumerate(names):
            ord_ += 1024.0
            row = {"id": iid, "tier": tier, "ord": ord_, "rel_path": f"HighPriority/{name}", "title": name,
                   "parent_folder": None, "source_type": "subtitle", "availability": "available", "work_id": wid,
                   "piece_id": pid, "watched": 0, "mined_at": None, "pinned": None, "mine_asked": None,
                   "graduated_at": None, "in_learning_order": 1, "added_at": "2026-10-01T00:00:00Z", "feed_in": 1}
            row.update(extra.get(k, {}))
            out[iid] = row
            iid += 1
    return out


def _feed(jobs, running=True, language="ja"):
    return feed.build({"running": running, "languages": {language: {"line": "", "state": "working",
                                                                    "jobs": list(jobs), "needs": []}}}, language)


def _job_row(item, state="waiting", reason=None, kind="mine", made=0, words=0, title=None):
    return {"item": item, "job": 100 + item, "state": state, "reason": reason, "kind": kind, "made": made,
            "words": words, "title": title}


@pytest.mark.parametrize("language, show_a, show_b", [
    ("ja", "Re ゼロから始める異世界生活", "無職転生"), ("zh", "琅琊榜", "甄嬛传")])
def test_the_row_of_the_episode_being_mined_shows_mining_and_the_ones_behind_it_wait_their_turn(language, show_a,
                                                                                                 show_b):
    """T3 (Sonic's Re:Zero above Mushoku Tensei in Current): Connect mines the first show's episode; that episode and
    its show's row say *Mining*, the second show's episodes *Waiting* with their turn as the hover (never amber)."""
    items = items_of([("now", 1, 1, [f"{show_a} - 03.srt", f"{show_a} - 04.srt"], {}),
                      ("now", 2, 2, [f"{show_b} - 04.srt", f"{show_b} - 05.srt"], {})])
    connect = _feed([_job_row(1, state="mining", made=2, words=9, title=f"{show_a} - 03"),
                     _job_row(3, reason=runner.TURN), _job_row(4, reason=runner.TURN)], language=language)
    view = vr.build(items, {}, {"mine_line": 20}, connect=connect, language=language)
    first, second = view.rows
    assert first.episodes[0].status.kind == "mining" and first.status.kind == "mining"
    assert [(e.status.kind, e.status.tone, e.status.tip) for e in second.episodes] == [
        ("waiting", "dim", runner.TURN)] * 2


def test_an_episode_already_in_anki_that_a_level_raise_mines_again_shows_mining_until_its_job_ends():
    """T3's check: an episode mined before, mined again for a level raise's new words, is the one Connect is working
    on — its row says *Mining* (it showed only ✓, so no row said where the strip's arc was); back to ✓ after."""
    items = items_of([("now", 1, 1, ["無職転生 - 01.srt", "無職転生 - 02.srt"], {})])
    mining = _feed([_job_row(1, state="mining", kind="level", made=1, words=3)])
    view = vr.build(items, {}, {"mine_line": 20}, cards={1: 18}, connect=mining)
    assert view.rows[0].episodes[0].status.kind == "mining", "the episode being mined says so"
    assert view.rows[0].status.kind == "mining"
    waiting = _feed([_job_row(1, reason=runner.REVIEWING, kind="level")])
    after = vr.build(items, {}, {"mine_line": 20}, cards={1: 18}, connect=waiting)
    assert after.rows[0].episodes[0].status.kind == "in_anki", "a level job that waits keeps ✓ (P4.1 WF)"
