"""P4.1 row 4.1.2: the window's Connect feed (`app/connect/feed.py`) — each library row's Connect stone and its words
from Connect's status record, read only when Connect's stamp moved (S19), nothing at all while Connect may not run
(`connect_on`), and the line saying why nothing runs while the automation is off (IK N4).

What a wrong answer would cost: a row saying *Mining* for an episode Anki is keeping waiting (so the user never opens
Anki), or *Waiting* for one whose video is gone (so they never link it); a window that reads the ledger every three
seconds for nothing (the laptop's battery, S19); a stone offering *Mine now* while the automation is off (a click that
does nothing, S16); a feed that raises when the ledger is busy, taking the window's tick with it.

A real ledger under the test root, its jobs in each state as the runner leaves them (its own reasons: `runner.*`,
`anki_session.*`); the suite's real Japanese and Chinese files in a store built from folders (`connect_helpers`).
"""
import os

import pytest

from app.connect import anki_session, feed, runner, status
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

ON = {"connect_enabled": True}
WORDS = [{"word": "冒険", "reading": "ボウケン"}, {"word": "散歩", "reading": "サンポ"},
         {"word": "図書館", "reading": "トショカン"}]


def _items(lang="ja", n=12):
    c.library(lang, extra=n)
    with c.store(lang) as s:
        return s.ids("now")


def _job(ledger, lang, item, state, reason=None, picked=None, kind=None):
    jid = ledger.queue(lang, item, "user", None)
    if kind:            # row 4.1.3 queues an ask's job as kind `asked` (package A): written as it will be
        ledger.conn.execute("UPDATE jobs SET kind = ? WHERE id = ?", (kind, jid))
    columns = {"picked": picked} if picked else {}
    if reason:
        columns["reason"] = reason
    if state != "queued":
        ledger.set_state(jid, state, **columns)
    return jid


@pytest.fixture
def running(monkeypatch):
    """Connect's lock looked at: running unless the test says otherwise."""
    state = {"on": True}
    monkeypatch.setattr(status, "running", lambda: state["on"])
    return state


def _every_state(lang="ja"):
    """One job per state the window draws -> {name: item id}."""
    ids = _items(lang)
    at = dict(zip(["mining", "picking", "closed", "reviewing", "busy", "profile", "no_video", "battery",
                   "not_timed", "asked", "queued", "miner_open"], ids))
    with Ledger() as ledger:
        jid = _job(ledger, lang, at["mining"], "mining", picked={"words": WORDS})
        ledger.start_batch(jid, 1, "run")
        ledger.end_batch(jid, 1, "done", [dict(WORDS[0], outcome="made", note_id=1)])
        _job(ledger, lang, at["picking"], "picking")
        _job(ledger, lang, at["closed"], "waiting", runner.ANKI_CLOSED)
        _job(ledger, lang, at["reviewing"], "waiting", runner.REVIEWING)
        _job(ledger, lang, at["busy"], "waiting", anki_session.BUSY)
        _job(ledger, lang, at["profile"], "waiting", anki_session.OTHER_PROFILE.format("日本語", "User 1"))
        _job(ledger, lang, at["no_video"], "waiting", runner.NO_VIDEO)
        _job(ledger, lang, at["battery"], "waiting", runner.ON_BATTERY)
        say = "ぼっち・ざ・ろっく！ 05: Not timed to its video, so no cards."
        jid = _job(ledger, lang, at["not_timed"], "waiting", say)
        ledger.need(lang, "not-timed", say, item_id=at["not_timed"], job_id=jid)
        _job(ledger, lang, at["asked"], "queued", kind="asked")
        _job(ledger, lang, at["queued"], "queued")
        _job(ledger, lang, at["miner_open"], "waiting", runner.ANKI_MINER_OPEN)
    return at


EXPECTED = {"mining": feed.MINING, "picking": feed.MINING, "closed": feed.ANKI, "reviewing": feed.ANKI,
            "busy": feed.ANKI, "profile": feed.ANKI, "no_video": feed.NO_VIDEO, "battery": feed.BATTERY,
            "not_timed": feed.NOT_TIMED, "asked": feed.ASKED, "queued": feed.WAITING, "miner_open": feed.WAITING}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_each_jobs_state_is_its_kind_with_its_own_reason_as_the_tip(running, lang):
    at = _every_state(lang)
    got = feed.Provider(lang, lambda: ON).feed()
    assert got.on is True
    assert {name: got.items[item].kind for name, item in at.items()} == EXPECTED
    assert got.mining == frozenset({at["mining"], at["picking"]})
    assert got.items[at["closed"]].tip == runner.ANKI_CLOSED, "C7: a waiting stone's hover is its own job's reason"
    assert got.items[at["no_video"]].tip == runner.NO_VIDEO
    assert got.items[at["not_timed"]].tip.endswith("Not timed to its video, so no cards.")
    # laptop round 9 #56: no reason of its own while Connect mines another episode: waiting its turn (was the kind's
    # own words; those stay for a job with no reason while nothing is in flight)
    assert got.items[at["queued"]].tip == runner.TURN, "no reason, another in flight: waiting its turn"
    mining = got.items[at["mining"]]
    assert (mining.made, mining.total, mining.words) == (1, 3, feed.WORDS[feed.MINING]), "*Mining 1 of 3*"
    assert all(item.words == feed.WORDS[item.kind] for item in got.items.values()), "read out as words (RS-6)"
    assert got.line.startswith("Making cards") and got.state == "working" and got.unseen == 1


def test_a_job_left_mid_way_with_connect_not_running_is_waiting_never_mining(running):
    at = _every_state()
    running["on"] = False
    got = feed.Provider("ja", lambda: ON).feed()
    assert got.mining == frozenset() and got.items[at["mining"]].kind == feed.WAITING


def test_the_line_names_the_episode_being_mined_by_its_title(running):
    at = _every_state()
    with c.store() as s:
        name = os.path.basename(s.item(at["mining"])["rel_path"])
    got = feed.Provider("ja", lambda: ON).feed()
    assert name in got.line, "the store's title (here its file's name), as the record names it"


def test_an_unchanged_stamp_reads_nothing_and_hands_back_the_same_feed(running):
    _every_state()
    reads = []

    def read(languages=None):
        reads.append(languages)
        return status.read(languages)
    provider = feed.Provider("ja", lambda: ON, read=read)
    provider.feed()
    # a ledger nobody holds open: SQLite makes its -wal file at the first read, which moves the stamp once
    first = provider.feed()
    assert len(reads) == 2
    assert provider.feed() is first and provider.mining() is first.mining and provider.line() == first.line
    assert len(reads) == 2, "S19: the stamp unchanged, the record never read again"
    with Ledger() as ledger:
        job = ledger.jobs("ja")[0]
        ledger.set_state(job["id"], "waiting", reason=runner.ANKI_CLOSED)       # the mining job stopped for Anki
    second = provider.feed()
    assert len(reads) == 3 and second is not first, "the ledger moved: read again"
    assert job["item_id"] not in second.mining and second.items[job["item_id"]].kind == feed.ANKI


@pytest.mark.parametrize("settings,line", [
    ({"connect_enabled": True, "logic": {"automation": False}}, feed.OFF_AUTOMATION),
    ({"connect_enabled": False}, feed.OFF_CONNECT),
])
def test_connect_off_is_the_empty_feed_saying_why_and_nothing_is_read(running, settings, line):
    _every_state()
    looked = []
    provider = feed.Provider("ja", lambda: settings, stamp=lambda **k: looked.append("stamp"),
                             read=lambda **k: looked.append("read"))
    got = provider.feed()
    assert (got.on, got.mining, got.items, got.line, got.state) == (False, frozenset(), {}, line, "off")
    assert looked == [], "off: not even the stamp"
    assert provider.every() is None, "no tick once a look found it off"


def test_turned_on_again_its_first_look_reads():
    settings = {"value": {"connect_enabled": False}}
    reads = []
    provider = feed.Provider("ja", lambda: settings["value"], stamp=lambda **k: ["same"],
                             read=lambda **k: reads.append(1) or {"stamp": ["same"], "languages": {}})
    provider.feed()
    settings["value"] = ON
    assert provider.feed().on is True and reads == [1] and provider.every() == feed.EVERY_S


def test_no_ledger_is_up_to_date():
    c.library()
    got = feed.Provider("ja", lambda: ON).feed()
    assert (got.on, got.items, got.line, got.state) == (True, {}, "Up to date", "idle")


def test_an_unreadable_ledger_is_the_records_own_line_never_a_raise(running):
    c.library()
    from app.connect import ledger as book
    os.makedirs(os.path.dirname(book.path()), exist_ok=True)
    with open(book.path(), "wb") as f:
        f.write(b"not a ledger, a torn file" * 40)
    got = feed.Provider("ja", lambda: ON).feed()
    own = status.read(["ja"])["languages"]["ja"]
    assert got.on is True and got.items == {} and (got.line, got.state) == (own["line"], own["state"]) ==         (own["line"], "waiting"), "the record's own words (here: a ledger it can't read as its own)"


def test_a_read_that_raises_is_said_and_read_again_next_look():
    calls = []

    def read(**k):
        calls.append(1)
        raise OSError("the ledger is held")
    provider = feed.Provider("ja", lambda: ON, stamp=lambda **k: ["same"], read=read)
    assert provider.feed().line == feed.UNREADABLE
    provider.feed()
    assert len(calls) == 2, "a failed read is never kept as the stamp's feed"


def test_the_untimed_warning_names_the_risk():
    # row 4.1.9: *Mine anyway* on hato's name-only pairing carries a warning (09-hato-layer v2 §1.2)
    assert "another episode" in feed.UNTIMED_WARNING or "episode's" in feed.UNTIMED_WARNING


def test_settings_that_cant_be_read_are_the_unreadable_line_never_a_raise():
    # why (Haiku review, failures): the settings service raising (settings.json caught mid-save) reached the window's
    # worker as an exception instead of the feed's own line
    def settings_get():
        raise OSError("settings.json is being written")
    got = feed.Provider("ja", settings_get, stamp=lambda **k: 1, read=lambda **k: {}).feed()
    assert got.line == feed.UNREADABLE and got.on is True
