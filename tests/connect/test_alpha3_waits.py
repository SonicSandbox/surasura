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
    shown = vr.stem(name)                               # the episode's name, never its file's extension (review A6)
    assert shown and "." + name.rsplit(".", 1)[-1] not in miner.lines[0]
    assert len(miner.lines) == 1 and miner.lines[0].startswith(f"{S.CONNECT_JOB_LABEL} · {shown}")


def test_the_mining_line_names_the_episode_with_its_step_and_percent():
    item = feed.Item(feed.MINING, feed.WORDS[feed.MINING], "", 7, 0, 0, 94, "Filling fields", title="白銀の書庫番 52")
    miner = _strip(feed.Feed(on=True, mining=frozenset({1}), items={1: item}, line="", state="working", unseen=0,
                             updating=False))[P.MINER]
    assert miner.lines == ("Making cards · 白銀の書庫番 52 · Filling fields 94%",)


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
    ("ja", "星降る街の小さな工房", "雲の上の郵便屋さん"), ("zh", "琅琊榜", "甄嬛传")])
def test_the_row_of_the_episode_being_mined_shows_mining_and_the_ones_behind_it_wait_their_turn(language, show_a,
                                                                                                 show_b):
    """T3 (one show above another in Current): Connect mines the first show's episode; that episode and
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
    items = items_of([("now", 1, 1, ["雲の上の郵便屋さん - 01.srt", "雲の上の郵便屋さん - 02.srt"], {})])
    mining = _feed([_job_row(1, state="mining", kind="level", made=1, words=3)])
    view = vr.build(items, {}, {"mine_line": 20}, cards={1: 18}, connect=mining)
    assert view.rows[0].episodes[0].status.kind == "mining", "the episode being mined says so"
    assert view.rows[0].status.kind == "mining"
    waiting = _feed([_job_row(1, reason=runner.REVIEWING, kind="level")])
    after = vr.build(items, {}, {"mine_line": 20}, cards={1: 18}, connect=waiting)
    assert after.rows[0].episodes[0].status.kind == "in_anki", "a level job that waits keeps ✓ (P4.1 WF)"


# --- T2 as it happened (Sonic's correction, 2026-10-24 night): a refused episode he dismissed is no waiting one ----- #
def _steps(tmp_path, plan, untimed):
    """FakeSteps whose timing check refuses the items in `untimed` (as hato / tsubasa would: *Not timed to its
    video*) and passes the others."""
    from tests.connect.fake_steps import FakeSteps

    class Steps(FakeSteps):
        def fit(self, lang, job, pairing, video, subtitle):
            self.log.append(("fit", job["item_id"]))
            if job["item_id"] in untimed:
                return ("untimed", "hato", "Not timed to its video, so no cards.", 0.0)
            return ("timed", "hato", None, 0.0)
    words = {"22": [("冒険", "ボウケン")], "23": [("散歩", "サンポ")], "24": [("図書館", "トショカン")],
             "25": [("約束", "ヤクソク")]}             # each its own word: one carded is never picked again
    return Steps(str(tmp_path), dict(plan, words=words))


def test_a_refused_episode_whose_needs_you_entry_you_dismissed_is_neither_counted_nor_shown_as_waiting(tmp_path,
                                                                                                      monkeypatch):
    """His sequence: two episodes (22, 23) refused as not timed to their video (right, as he wanted) → *Needs you*
    names them, the 鉱 circle amber → he dismisses both → Connect goes on and mines the next episode (24) → the circle
    no longer says "Waiting to make its cards (2)": the two are skipped until something changes (a re-time, a new
    subtitle, *Mine anyway*). At Connect's next start they are refused again quietly (still dismissed), and the next
    episode (25) is mined; still nothing counts them."""
    path = str(tmp_path / "ledger.sqlite")
    monkeypatch.setattr(status, "running", lambda: False)
    with Ledger(path) as ledger:
        steps = _steps(tmp_path, {"line": {"ja": [22, 23, 24]}, "queue": {"ja": [22, 23, 24]}}, {22, 23})
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert any(e[0] == "mine" and e[1] == 24 for e in steps.log), "Connect went on to the next episode"
        refused = {n["item_id"]: n["id"] for n in ledger.needs("ja") if n["kind"] == "not-timed"}
        assert set(refused) == {22, 23}

    got = feed.build(status.read(languages=["ja"], path=path), "ja")
    assert {got.items[i].kind for i in (22, 23)} == {feed.NOT_TIMED}
    assert _strip(got)[P.MINER].needs, "refused: Needs you, amber, until he answers"

    for need_id in refused.values():                   # *Dismiss* on both entries
        assert status.dismiss(need_id, path=path)
    got = feed.build(status.read(languages=["ja"], path=path), "ja")
    miner = _strip(got)[P.MINER]
    assert not miner.needs and not miner.waiting and miner.lines == (), "dismissed: no wait counted, nothing lit"
    assert {got.items[i].kind for i in (22, 23)} == {feed.SKIPPED}

    with Ledger(path) as ledger:                       # Connect's next start: a new episode came
        steps = _steps(tmp_path, {"line": {"ja": [22, 23, 25]}, "queue": {"ja": [25]}}, {22, 23})
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert any(e[0] == "mine" and e[1] == 25 for e in steps.log), "the next one is mined"
        assert not ledger.needs("ja"), "refused again: still dismissed, nothing new in Needs you"
    miner = _strip(feed.build(status.read(languages=["ja"], path=path), "ja"))[P.MINER]
    assert not miner.needs and not miner.waiting and miner.lines == ()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_dismissed_refusal_is_skipped_on_its_row_too_and_a_blanket_wait_doesnt_count_it_again(running, lang):
    """The row of a dismissed refusal says *Not timed* quietly (no amber, no *Mine now* promise of making it by itself),
    and a later wait every episode is given (on battery: `_waiting_all`) doesn't count it among the waiting."""
    ids = _items(lang)
    with Ledger() as ledger:
        jid = _job(ledger, lang, ids[0], "waiting", runner.ON_BATTERY)
        ledger.need(lang, "not-timed", "Not timed to its video, so no cards.", item_id=ids[0], job_id=jid)
        need_id = ledger.needs(lang)[0]["id"]
        ledger.dismiss(need_id)
        _job(ledger, lang, ids[1], "waiting", runner.ON_BATTERY)
    got = feed.Provider(lang, lambda: ON).feed()
    assert got.items[ids[0]].kind == feed.SKIPPED and got.items[ids[1]].kind == feed.BATTERY
    assert _strip(got)[P.MINER].lines == (
        f"{S.CONNECT_WAIT_LABEL} · {runner.ON_BATTERY.rstrip('.')} · 1 episode",)
    item = got.items[ids[0]]
    st = vr._connected(vr.Status("waiting", vr.STRINGS["waiting"], "", "dim"), item, "video")
    assert (st.label, st.tone) == (vr.STRINGS["not_timed"], "faint") and st.tip == vr.STRINGS["tip_skipped"]


# --- the review's fixes (reviews/alpha3-waits-adversary.md A1–A6) -------------------------------------------------- #
def _item(kind, tip, i):
    return feed.Item(kind, feed.WORDS[kind], tip, i, 0, 0)


def _looked(*items):
    return feed.Feed(on=True, mining=frozenset(), items={i: it for i, it in enumerate(items)}, line="",
                     state="waiting", unseen=0, updating=False)


def test_what_waits_on_you_says_its_kind_and_count_never_one_clause_an_episode():
    """A1: twelve refusals, each naming its episode, are one short clause on the amber circle (Needs you and the
    rows name each one)."""
    says = [f"雲の上の郵便屋さん - {n:02d}: Not timed to its video, so no cards. Mine anyway…" for n in range(1, 13)]
    miner = _strip(_looked(*[_item(feed.NOT_TIMED, say, i) for i, say in enumerate(says)]))[P.MINER]
    assert miner.needs == "Not timed to its video · 12 episodes"


def test_an_episode_held_by_another_needs_you_entry_is_amber_with_short_words(running):
    """A3: a job held by one of Connect's *Needs you* entries (Anki turned a deck down) waits on you: amber, and its
    words point at Needs you instead of repeating the entry."""
    say = "Anki turned down Connect's cards: deck was not found. Choose your deck in Settings."
    rec = {"running": True, "languages": {"ja": {"jobs": [{"item": i, "job": i, "state": "waiting", "reason": say}
                                                          for i in (1, 2, 3)],
                                                 "needs": [{"kind": "anki-refused", "say": say, "item": None}]}}}
    got = feed.build(rec, "ja")
    assert {it.kind for it in got.items.values()} == {feed.HELD}
    miner = _strip(got)[P.MINER]
    assert miner.needs == "Waiting for you: see Needs you · 3 episodes" and say not in " ".join(miner.lines)
    row = vr._connected(vr.Status("waiting", vr.STRINGS["waiting"], "", "dim"), got.items[1], "video")
    assert row.tone == "warn" and row.tip == say


def test_anki_opened_while_you_review_ends_the_amber_at_once():
    """A4: the same episodes move from *Anki closed* to *you reviewing*: the amber wait ends at that look, never a
    tick of amber beside the still arc."""
    registry = JobRegistry()
    S.mirror_connect(registry, _looked(_item(feed.ANKI, runner.ANKI_CLOSED, 1)))
    S.mirror_connect(registry, _looked(_item(feed.ANKI_WAIT, runner.REVIEWING, 1)))
    anki = P.read(registry.snapshot(), now=time.time() + 5)[P.ANKI]
    assert not anki.needs and anki.waiting


def test_a_profile_question_anki_doesnt_answer_in_time_is_busy_never_a_wait_on_you(monkeypatch):
    """A5: Anki answered the look, then not the profile question in time: *busy* (clears by itself), not *no profile
    named* (amber for the runner's whole 2-minute pause). A refusal of the question keeps the old answer."""
    from app import anki_connect
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(anki_session, "look", lambda url: "open")
    errors = {"kind": "offline"}

    def invoke(action, url, timeout=None, **_):
        raise anki_connect.AnkiError("timed out", errors["kind"])
    monkeypatch.setattr(anki_connect, "invoke", invoke)
    settings = {"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:8765"}
    assert anki_session.waiting("http://127.0.0.1:8765", settings) == anki_session.BUSY
    errors["kind"] = "action"
    assert anki_session.waiting("http://127.0.0.1:8765", settings) == anki_session.NO_PROFILE_YET


def test_the_next_look_words_name_connects_own_pause():
    assert runner.LOOK_EVERY_S == 120 and "within 2 minutes" in feed.NEXT_LOOK


@pytest.mark.parametrize("lang", ["zh"])
def test_chinese_episodes_say_why_they_wait_and_how_many(running, lang):
    """A8: what Connect really writes for Chinese today (E24): every episode waits with *Chinese cards come later*."""
    ids = _items(lang)
    with Ledger() as ledger:
        for item in ids[:4]:
            _job(ledger, lang, item, "waiting", runner.CHINESE)
    miner = _strip(feed.Provider(lang, lambda: ON).feed())[P.MINER]
    assert miner.waiting and not miner.needs
    assert miner.lines == (f"{S.CONNECT_WAIT_LABEL} · Chinese cards come later · 4 episodes",)


def test_connect_logs_the_reason_a_wait_changes_to_once_never_each_look(tmp_path, caplog):
    """The next bundle shows why an episode waited (alpha 2's log never did): one line when its reason changes."""
    import logging
    steps = _steps(tmp_path, {"line": {"ja": [22]}, "queue": {"ja": [22]}, "blocked": runner.REVIEWING}, set())
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger, caplog.at_level(logging.INFO, logger="surasura-cli"):
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    said = [r.getMessage() for r in caplog.records if "waits:" in r.getMessage()]
    assert said == [f"Connect: job 1 (item 22) waits: {runner.REVIEWING}"]


def test_a_show_whose_episodes_are_all_in_anki_says_mining_without_a_count_beside_its_episodes_cards():
    """Intent keeper #5: a level raise mining one episode of a show fully in Anki — the show reads *Mining…*, never
    "Mining · 2/2" (episodes) beside its episode's "Mining · 1/3" (cards)."""
    items = items_of([("now", 1, 1, ["雲の上の郵便屋さん - 01.srt", "雲の上の郵便屋さん - 02.srt"], {})])
    mining = _feed([_job_row(1, state="mining", kind="level", made=1, words=3)])
    row = vr.build(items, {}, {"mine_line": 20}, cards={1: 18, 2: 20}, connect=mining).rows[0]
    assert (row.status.kind, row.status.label) == ("mining", vr.STRINGS["mining"])


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("is_running, words", [(True, "within 2 minutes"), (False, "at its next start")])
def test_connects_own_line_agrees_with_the_strip_on_when_it_comes_to_them(running, lang, is_running, words):
    """Intent keeper #8: Connect's line never says "at its next start" while Connect runs."""
    running["on"] = is_running
    ids = _items(lang)
    with Ledger() as ledger:
        _job(ledger, lang, ids[0], "queued")
        _job(ledger, lang, ids[1], "queued")
    line = status.read(languages=[lang])["languages"][lang]["line"]
    assert line.startswith("2 episodes wait for their cards") and words in line


# --- A2 (alpha 3's adversary, the lead 2026-10-25): one reason per wait until the wait truly changes --------------- #
def _waiting_lines(got):
    return [ln for ln in _strip(got)[P.MINER].lines if ln.startswith(S.CONNECT_WAIT_LABEL)]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_between_two_episodes_of_one_look_the_waiting_ones_keep_their_turn(running, lang):
    """Between two episodes Connect makes in one look, nothing is in flight for a moment (one job ended, the next not
    yet choosing its words). The episodes behind still wait their turn: the 鉱 hover and their rows keep saying so,
    never "within 2 minutes" for a few seconds at every episode's end."""
    ids = _items(lang)
    with Ledger() as ledger:
        first = _job(ledger, lang, ids[0], "mining")
        ledger.set_state(first, "mining", picked={"words": WORDS})
        _job(ledger, lang, ids[1], "queued")
        _job(ledger, lang, ids[2], "queued")
        with ledger.transaction():
            ledger.mark_working(lang)           # the runner's mark: this look is working through the episodes
    while_mining = _waiting_lines(feed.Provider(lang, lambda: ON).feed())
    with Ledger() as ledger:
        ledger.set_state(first, "done")
    got = feed.Provider(lang, lambda: ON).feed()
    assert got.items[ids[1]].tip == got.items[ids[2]].tip == runner.TURN, "the rows' hover keeps the same words"
    assert _waiting_lines(got) == while_mining == [f"{S.CONNECT_WAIT_LABEL} · {runner.TURN.rstrip('.')} · 2 episodes"]
    line = status.read(languages=[lang])["languages"][lang]["line"]
    assert "within 2 minutes" not in line, "Connect's own line never says its next look while it works through them"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_once_the_look_is_over_the_ones_left_wait_for_the_next_look(running, lang):
    """The look's work ended (the mark cleared before Connect's pause): an episode queued since waits for Connect's
    next look — that wait truly changed."""
    ids = _items(lang)
    with Ledger() as ledger:
        _job(ledger, lang, ids[0], "queued")
        with ledger.transaction():
            ledger.mark_working(lang)
        with ledger.transaction():
            ledger.worked(lang)
    assert feed.Provider(lang, lambda: ON).feed().items[ids[0]].tip == feed.NEXT_LOOK


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_while_connect_updates_your_list_after_mining_the_ones_queued_say_so_not_their_turn(running, lang):
    """The look's episodes made, Connect's own Generate runs (F11, its *updating your list* mark) and an episode you
    queued meanwhile waits for it: it says so, never "its turn" (no episode's cards are being made)."""
    ids = _items(lang)
    with Ledger() as ledger:
        _job(ledger, lang, ids[0], "queued")
        with ledger.transaction():
            ledger.mark_working(lang)
            ledger.mark_updating(lang)
    assert feed.Provider(lang, lambda: ON).feed().items[ids[0]].tip == feed.NEXT_UPDATING


def test_a_mark_a_crash_left_says_nothing_once_connect_has_stopped(running):
    """Connect killed mid-look leaves its mark: with Connect not running the episode waits for its next start."""
    ids = _items("ja")
    with Ledger() as ledger:
        _job(ledger, "ja", ids[0], "queued")
        with ledger.transaction():
            ledger.mark_working("ja")
    running["on"] = False
    assert feed.Provider("ja", lambda: ON).feed().items[ids[0]].tip == feed.NEXT_START


def test_a_run_marks_its_work_between_episodes_and_clears_it_before_its_pause(tmp_path, running):
    """The runner's own run: three episodes in one look, the third waiting on Anki Miner's open window (a wait that
    may end while Connect runs: a pause, then a second look). At each step between two episodes (the next one's line
    read) the episodes still queued wait their turn; at the pause between looks, and once the run ends, no mark is
    left."""
    from tests.connect.fake_steps import FakeSteps
    path = str(tmp_path / "ledger.sqlite")
    seen, paused = [], []

    class Steps(FakeSteps):
        def mine_line(self, lang):
            if self.records:                    # an episode made in this look: the next one's line read now
                rec = status.read(languages=[lang], path=path)["languages"][lang]
                got = feed.build({"running": True, "languages": {lang: rec}}, lang)
                seen.append({j["item"]: got.items[j["item"]].tip for j in rec["jobs"] if j["state"] == "queued"})
            return super().mine_line(lang)

        def mine(self, lang, job, picked, words, attempt):
            if job["item_id"] == 3:
                raise runner.Wait(runner.ANKI_MINER_OPEN)
            return super().mine(lang, job, picked, words, attempt)

    steps = Steps(str(tmp_path), {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [1, 2, 3]}, "absent": ["junban"]})
    with Ledger(path) as ledger:
        def pause(_seconds):
            paused.append(ledger.working("ja"))
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=pause, looks=2)
        left = ledger.working("ja")
    between = [tips for tips in seen if tips]               # the ones still queued after an episode
    assert between and all(tip == runner.TURN for tips in between for tip in tips.values())
    assert paused == [None], "the look's mark is cleared before Connect's pause"
    assert left is None, "and none is left once the run ends"


def test_a_mark_a_crash_left_is_cleared_when_connect_starts_again(tmp_path, running):
    """B-5: Connect killed mid-look left its mark; the next run clears it before its first pass's preparing (the sync,
    known words, Generate), so the queued episodes never say "its turn" while nothing is being made."""
    from tests.connect.fake_steps import FakeSteps
    path = str(tmp_path / "ledger.sqlite")
    seen = []

    class Steps(FakeSteps):
        def prepare(self, lang, ledger):
            seen.append(ledger.working(lang))
            return super().prepare(lang, ledger)

    with Ledger(path) as ledger:
        with ledger.transaction():
            ledger.mark_working("ja")
        steps = Steps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "absent": ["junban"]})
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert seen == [None]
