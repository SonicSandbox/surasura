"""An Anki Miner older than the approved one, while books wait for it (Michi-U, alpha 9.1 try; Sonic 2026-11-02: "i
have a book without audio (and one with) and it says it waits for Anki miner. this was because it was out of date ...
if anki miner has an update, it would show in needs you right?" and "i updated anki miner, but there was no update in
surasura for the books ... after i stepped away it began working").

The one rule (`am_release.opens`), *Needs you*'s one line (`services.needs.miner_update` / MINER_UPDATE), the rows' tip
(`view_rows._wait_tip`) and a hand update followed at once (`setup.follow_install`, `feed.Provider`).

What a wrong answer would cost: a learner whose books never make cards and nothing says why (the old tip promised "a
later update" that already exists); an *Update* offered for an Anki Miner already new enough (a needless 180 MB and an
installer for nothing), or offered for audio that no Anki Miner can open in this Surasura; an update done by hand that
does nothing for 15 minutes (Sonic's "after i stepped away"); a follow that loops (Anki Miner asked every 3 s, for ever)
or reads the record on every tick (S19). Anki Miner is never run here: the checks and the kick are stood in for.
"""
import threading
import time

import pytest

from app.connect import am_release, anki_miner, feed, runner, setup
from app.connect.ledger import Ledger
from app.services import needs as service
from app.services import view_rows as vr
from tests.test_view_rows import WORKS, eps, items_of, work

OLD = "3.10.1"
NO_READING = ["word-from-line", "dry-run", "settings-import", "setup"]
READING = NO_READING + ["reading"]


def _record(app, features):
    """Connect's setup record naming the Anki Miner its last look found (its `version` answer)."""
    assert setup.write_record({"anki_miner": {"path": "C:/x/AnkiMiner.exe", "app": app, "schema": 1,
                                              "features": list(features)}})


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """Each test's own memos (the record's last read, the opens look, the version followed); the installer's version
    none until a test sets one; nothing kicked for real."""
    monkeypatch.setattr(anki_miner, "_NOW", {})
    monkeypatch.setattr(am_release, "_OPENS", {})
    monkeypatch.setattr(setup, "_FOLLOWED", {})
    monkeypatch.setattr(anki_miner, "installed_version", lambda: None)
    WORKS.clear()
    work(1, "星降る街の小さな工房")
    work(3, "白銀の書庫番", media="lightnovel")
    work(7, "銀河鉄道の夜 朗読", media="audiobook")


def _registry(monkeypatch, version):
    monkeypatch.setattr(anki_miner, "installed_version", lambda: version)


def _view(*spec):
    return vr.build(items_of(list(spec)), dict(WORKS), {"mine_line": 20})


BOOK = ("now", 3, 30, ["白銀の書庫番 01 章.epub", "白銀の書庫番 02 章.epub"],
        {0: {"source_type": "epub"}, 1: {"source_type": "epub"}})
ANIME = ("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {})
AUDIO = ("now", 7, 70, eps("銀河鉄道の夜 朗読", 1, 2), {})


# --------------------------------------------------------------------------- #
# The one rule
# --------------------------------------------------------------------------- #
def test_an_anki_miner_older_than_the_approved_one_that_cant_read_books_is_opened_by_the_update(monkeypatch):
    """Sonic's case: 3.10.1 found, no `reading` — the approved release opens books; nothing for audio while this
    Surasura doesn't know its ask."""
    _record(OLD, NO_READING)
    assert am_release.opens("books") == am_release.APPROVED
    assert am_release.update_for({"books", "audio"}) == {"version": am_release.APPROVED, "kinds": ("books",)}
    if not anki_miner.mines("audio"):
        assert am_release.opens("audio") is None, "no Anki Miner opens audio in a Surasura that doesn't mine it"


@pytest.mark.parametrize("registry, recorded, features, why", [
    (None, None, None, "Anki Miner not known at all: nothing to offer (Settings' card installs it)"),
    (am_release.APPROVED, OLD, NO_READING, "updated by hand: the installer's version is the approved one already"),
    ("3.12.0", OLD, NO_READING, "a newer one installed by hand: never offered an older one"),
    (None, am_release.APPROVED, NO_READING, "the approved one found: an update to it opens nothing"),
    (None, OLD, READING, "it reads books already: nothing waits on the update"),
    (None, "unknown", NO_READING, "a version with no digits is no version"),
])
def test_no_update_is_offered_unless_it_is_what_the_books_wait_for(monkeypatch, registry, recorded, features, why):
    _registry(monkeypatch, registry)
    if recorded is not None:
        _record(recorded, features)
    assert am_release.opens("books") is None, why
    assert am_release.update_for({"books"}) is None


def test_audio_is_offered_once_surasura_knows_its_ask(monkeypatch):
    """The rule names no kind by hand: once this Surasura knows audio's ask (Michi-AB's `audio-episodes`), an Anki
    Miner older than the approved one is offered the update for audiobooks and podcasts too, in WAITS' order."""
    monkeypatch.setitem(anki_miner.FEATURES, "audio-episodes", anki_miner.WAITS["audio"])
    _record(OLD, NO_READING)
    assert am_release.update_for({"audio", "books"}) == {"version": am_release.APPROVED, "kinds": ("books", "audio")}
    assert am_release.update_for({"audio"})["kinds"] == ("audio",)
    assert am_release.update_for(()) is None and am_release.update_for(None) is None


def test_opens_reads_the_record_again_only_once_it_changed(monkeypatch):
    """S19: a view of many waiting rows asks once a row — the record is read once while it stays as it is, and again
    the moment it changes (a check wrote it)."""
    _record(OLD, NO_READING)
    reads = []
    real = setup.read_record
    monkeypatch.setattr(setup, "read_record", lambda: reads.append(1) or real())
    for _ in range(50):
        assert am_release.opens("books") == am_release.APPROVED
    assert len(reads) <= 2, f"read {len(reads)} times for 50 rows (once for `mines_now`, once for `installed`)"
    time.sleep(0.02)
    _record(am_release.APPROVED, NO_READING)        # (a found Anki Miner at the approved version: nothing to offer)
    assert am_release.opens("books") is None


# --------------------------------------------------------------------------- #
# The rows' tip says what's true
# --------------------------------------------------------------------------- #
def test_the_books_tip_names_the_update_and_where_its_button_is(monkeypatch):
    _record(OLD, NO_READING)
    book = {r.title: r for r in _view(BOOK, ANIME).rows}["白銀の書庫番"]
    assert book.status.kind == "books" and book.status.label == vr.STRINGS["books_wait"]
    assert book.status.tip == vr.STRINGS["tip_wait_update"].format(version=am_release.APPROVED,
                                                                   what="books and texts")
    assert f"Needs Anki Miner {am_release.APPROVED}" in book.status.tip and "Update in Needs you" in book.status.tip
    assert "later update" not in book.status.tip, "the old promise of an update that already exists"


def test_with_no_update_to_offer_the_tip_names_the_anki_miner_it_waits_for(monkeypatch):
    """No Anki Miner known (none found yet, or a look still to come after a hand update): never "Update in Needs you"
    where Needs you has no line."""
    book = {r.title: r for r in _view(BOOK).rows}["白銀の書庫番"]
    assert book.status.tip == vr.STRINGS["tip_books_wait"].format(version=am_release.APPROVED)
    assert "Needs you" not in book.status.tip and "later update" not in book.status.tip


def test_audio_before_surasura_mines_it_says_so_and_a_paired_title_names_only_what_the_update_opens(monkeypatch):
    _record(OLD, NO_READING)
    if anki_miner.mines("audio"):
        monkeypatch.delitem(anki_miner.FEATURES, next(k for k, v in anki_miner.FEATURES.items()
                                                      if v == anki_miner.WAITS["audio"]))
    audio = {r.title: r for r in _view(AUDIO).rows}["銀河鉄道の夜 朗読"]
    assert audio.status.tip == vr.STRINGS["tip_audio_wait"]
    assert vr._wait_tip({"books", "audio"}) == vr.STRINGS["tip_wait_update"].format(
        version=am_release.APPROVED, what="books and texts"), "a book with its audiobook: the update opens the book"


# --------------------------------------------------------------------------- #
# Needs you: one line, gone once updated
# --------------------------------------------------------------------------- #
def _entries(view, cards_on=True, **kw):
    return service.entries(view, miner_update=service.miner_update(view), cards_on=cards_on, **kw)


def test_needs_you_has_one_update_line_while_books_wait_on_an_old_anki_miner(monkeypatch):
    _record(OLD, NO_READING)
    view = _view(BOOK, ANIME)
    out = [e for e in _entries(view) if e.kind == service.MINER_UPDATE]
    assert len(out) == 1
    line = out[0]
    assert line.title == f"Update Anki Miner to {am_release.APPROVED} to make cards from your books and texts"
    assert line.actions == ("update_miner",), "one button, no Dismiss: it goes by itself once updated"
    assert line.unseen and line.data["titles"] == 1 and "1 title waits for it" in line.say
    assert line.key == f"{service.MINER_UPDATE}:{am_release.APPROVED}:books"


def test_the_line_goes_once_anki_miner_is_updated_by_hand_before_any_check(monkeypatch):
    """The installer's version moved to the approved one: the line goes at the next gather, even before Connect's
    checks read the new Anki Miner (the rows' tip then names no button)."""
    _record(OLD, NO_READING)
    view = _view(BOOK)
    assert any(e.kind == service.MINER_UPDATE for e in _entries(view))
    _registry(monkeypatch, am_release.APPROVED)
    assert not any(e.kind == service.MINER_UPDATE for e in _entries(view))
    assert "Needs you" not in {r.title: r for r in _view(BOOK).rows}["白銀の書庫番"].status.tip


def test_with_connect_off_no_line_and_no_tip_sends_you_to_one(monkeypatch):
    """Review r1 #2: Connect off (or never set up) makes no card whatever Anki Miner can do — no 180 MB offer, and the
    rows' tip names no button in Needs you (`line_n` None: Connect off)."""
    _record(OLD, NO_READING)
    view = _view(BOOK)
    assert not any(e.kind == service.MINER_UPDATE for e in _entries(view, cards_on=False))
    off = vr.build(items_of([BOOK]), dict(WORKS), {"mine_line": 20}, connect=feed._off({}))
    tip = {r.title: r for r in off.rows}["白銀の書庫番"].status.tip
    assert "Needs you" not in tip and tip == vr.STRINGS["tip_books_wait"].format(version=am_release.APPROVED)


def test_the_line_offers_no_not_now_or_stop_asking():
    """Review r1 #3: the rows' tip points at it — hidden, the tip would send you to nothing."""
    assert service.MINER_UPDATE in service.NO_LATER


def test_no_line_without_a_title_waiting_or_for_a_book_already_mined(monkeypatch):
    _record(OLD, NO_READING)
    assert service.miner_update(_view(ANIME)) is None, "nothing waits: no line"
    assert service.miner_update(None) is None
    assert not any(e.kind == service.MINER_UPDATE for e in service.entries(_view(BOOK), miner_update=None))
    view = vr.build(items_of([BOOK]), dict(WORKS), {"mine_line": 20}, cards={1: 4, 2: 3})
    assert service.miner_update(view) is None, "every part in Anki already: nothing waits"


def test_two_waiting_titles_are_counted_and_seen_keeps_the_line_quiet(monkeypatch):
    _record(OLD, NO_READING)
    work(9, "灰色の図書館", media="lightnovel")
    second = ("now", 9, 90, ["灰色の図書館 01.epub"], {0: {"source_type": "epub"}})
    view = _view(BOOK, second, ANIME)
    line = next(e for e in _entries(view) if e.kind == service.MINER_UPDATE)
    assert line.data["titles"] == 2 and "2 titles wait for it" in line.say
    again = next(e for e in _entries(view, seen={line.key}) if e.kind == service.MINER_UPDATE)
    assert not again.unseen


# --------------------------------------------------------------------------- #
# A hand update followed at once
# --------------------------------------------------------------------------- #
class Checks:
    """`setup.checks` stood in for: each call counted; it writes the record as a look finding `found` would."""

    def __init__(self, app=am_release.APPROVED, features=READING):
        self.app, self.features, self.calls = app, features, []

    def __call__(self, settings, language, keep=None, use_open_profile=False):
        self.calls.append((language, threading.current_thread().name))
        found = {"path": "C:/x/AnkiMiner.exe", "app": self.app, "features": list(self.features)}
        record = setup.read_record()
        record["anki_miner"] = found
        setup.write_record(record)
        return {"ready": True, "checks": [], "anki_miner": found, "recorded": True}


@pytest.fixture
def follow(monkeypatch):
    checks, kicks = Checks(), []
    monkeypatch.setattr(setup, "checks", checks)
    from app.connect import kick
    monkeypatch.setattr(kick, "kick", lambda settings, videos=False: kicks.append(dict(settings)))
    return checks, kicks


def test_a_hand_update_reruns_the_checks_and_kicks_connect_once(follow, monkeypatch):
    checks, kicks = follow
    _record(OLD, NO_READING)
    assert not setup.to_follow(None) and not setup.to_follow(OLD), "unknown, or the one the record holds: nothing"
    assert setup.to_follow(am_release.APPROVED)
    assert setup.follow_install({"connect_enabled": True}, "ja", am_release.APPROVED)
    assert len(checks.calls) == 1 and kicks == [{"connect_enabled": True}]
    assert anki_miner.mines_now("books"), "the record names the new Anki Miner: books open"
    assert not setup.to_follow(am_release.APPROVED), "followed: never again for this version"
    assert not setup.follow_install({}, "ja", am_release.APPROVED) and len(checks.calls) == 1


def test_a_look_that_didnt_find_the_new_version_is_tried_again_a_few_times_never_in_a_loop(follow, monkeypatch):
    """Anki Miner busy (or Connect pointed at another Anki Miner): the look finds the old one — tried again after
    FOLLOW_RETRY_S, FOLLOW_TRIES times at most, never every tick."""
    checks, kicks = follow
    checks.app = OLD
    _record(OLD, NO_READING)
    clock = [1000.0]
    monkeypatch.setattr(setup.time, "monotonic", lambda: clock[0])
    assert setup.follow_install({}, "ja", am_release.APPROVED)
    assert not setup.to_follow(am_release.APPROVED), "within FOLLOW_RETRY_S: not again"
    for _ in range(setup.FOLLOW_TRIES + 3):
        clock[0] += setup.FOLLOW_RETRY_S + 1
        setup.follow_install({}, "ja", am_release.APPROVED)
    assert len(checks.calls) == setup.FOLLOW_TRIES
    assert setup.to_follow("3.12.0"), "another version installed: followed again"


@pytest.mark.parametrize("installed", ["3.9.0", OLD])
def test_a_downgrade_or_the_same_version_is_never_followed(follow, installed):
    """Review r1 #4: Connect pointed at another Anki Miner (a newer one by path), or one downgraded by hand: the
    installer's version is no update — no checks at every start, no kicks."""
    checks, kicks = follow
    _record(OLD, NO_READING)
    assert not setup.to_follow(installed)
    assert not setup.follow_install({}, "ja", installed) and checks.calls == [] and kicks == []


def test_the_update_buttons_end_forces_the_follow(follow):
    checks, kicks = follow
    _record(am_release.APPROVED, READING)
    assert not setup.to_follow(am_release.APPROVED)
    assert setup.follow_install({}, "ja", am_release.APPROVED, force=True) and len(checks.calls) == 1


def test_follow_in_background_runs_off_the_callers_thread_one_at_a_time(follow, monkeypatch):
    checks, kicks = follow
    _record(OLD, NO_READING)
    gate = threading.Event()
    real = checks.__call__
    monkeypatch.setattr(setup, "checks", lambda *a, **k: gate.wait(5) and real(*a, **k))
    t = setup.follow_in_background({}, "ja", am_release.APPROVED)
    assert t is not None and t.name == "anki-miner-follow" and t is not threading.current_thread()
    assert setup.follow_in_background({}, "ja", "3.12.0") is None, "one follow at a time"
    gate.set()
    t.join(5)
    assert not t.is_alive() and anki_miner.mines_now("books")
    assert setup.follow_in_background({}, "ja", am_release.APPROVED) is None, "followed already"


def test_the_feed_follows_the_installers_version_in_its_stamp_without_reading_twice(monkeypatch):
    """`feed.Provider`'s 3 s look: the stamp's last part is the installer's version — a new one starts the follow (the
    settings copied, the window's language), the same one next tick starts nothing (in memory)."""
    from app import settings_manager
    monkeypatch.setattr(settings_manager, "connect_on", lambda s: True)
    started = []
    monkeypatch.setattr(setup, "follow_in_background", lambda s, lang, v: started.append((dict(s), lang, v)))
    _record(OLD, NO_READING)
    stamp = [[1, 2], None, False, "2026-11-02", None, None, None, None, OLD]
    from app.connect import status
    monkeypatch.setattr(status, "stamp", lambda languages=None: list(stamp))     # (Connect's own stamp: a stand-in
    monkeypatch.setattr(status, "read", lambda languages=None: {"languages": {"ja": {}}})     # handed in follows nothing)
    provider = feed.Provider("ja", lambda: {"connect_enabled": True})
    provider.feed()
    assert started == [], "the record holds the installer's version: nothing to follow"
    stamp[-1] = am_release.APPROVED
    provider.feed()
    assert started == [({"connect_enabled": True}, "ja", am_release.APPROVED)]
    setup._FOLLOWED.update(version=am_release.APPROVED, at=time.monotonic(), ok=True, tries=1)
    provider.feed()
    assert len(started) == 1
    stamp[-1] = None                                     # an Anki Miner its installer didn't put in place
    provider.feed()
    assert len(started) == 1


def test_the_feed_moves_when_the_anki_miner_connect_knows_of_does(monkeypatch):
    """Review r1 #1: a hand update followed rewrites the setup record — the Feed carries it (`miner`), so a Feed that
    is otherwise the same tells its listener (the reader builds the rows' tip again, Needs you gathers again)."""
    from app import settings_manager
    monkeypatch.setattr(settings_manager, "connect_on", lambda s: True)
    monkeypatch.setattr(setup, "follow_in_background", lambda *a: None)     # (no record: OLD would be followed)
    stamp = [[1, 2], None, False, "2026-11-02", None, None, None, [10, 100], OLD]
    provider = feed.Provider("ja", lambda: {}, stamp=lambda languages: list(stamp),
                             read=lambda languages: {"languages": {"ja": {}}, "stamp": list(stamp)})
    told = []
    provider.on_change = lambda: told.append(1)
    first = provider.feed()
    assert first.miner == ((10, 100), OLD) and len(told) == 1
    stamp[0] = [1, 3]                                   # the ledger moved, nothing Anki Miner: the same Feed
    assert provider.feed() is first and len(told) == 1
    stamp[-2] = [11, 140]                               # the follow's checks wrote the record
    assert provider.feed().miner == ((11, 140), OLD) and len(told) == 2
    assert feed.miner_of(None) is None and feed.miner_of([1]) is None


def test_a_book_set_aside_for_an_old_anki_miner_is_mined_once_the_hand_update_is_followed(follow, tmp_path):
    """End to end over the real store and ledger: the book's job is set aside (*Waits for Anki Miner*) with 3.10.1;
    the installer's version moves to the approved one; the follow's checks write the record; Connect's next look (the
    kick) queues the same job again and mines it as a book — nothing to undo, no Settings visit."""
    from tests.connect.test_p41_asked import _jobs, _library, _place_top, _run
    from tests.connect.test_z9_books import WORDS, BookSteps, _parts_in_store
    checks, kicks = follow
    _library()
    epub, parts, _records = _parts_in_store(tmp_path)
    steps = BookSteps(str(tmp_path), "ja", {"words": {str(parts[0]): WORDS}})
    steps.mines = lambda lang, kind: anki_miner.mines_now(kind)       # the real rule, read from the record
    _record(OLD, NO_READING)
    _place_top(parts[0])
    _run(steps)
    assert (_jobs(parts[0])[-1]["state"], _jobs(parts[0])[-1]["reason"]) == ("skipped", runner.BOOKS_WAIT)
    assert setup.follow_install({"connect_enabled": True}, "ja", am_release.APPROVED)
    assert kicks, "Connect kicked"
    _run(steps)                                         # the kicked Connect's look
    assert len(_jobs(parts[0])) == 1 and _jobs(parts[0])[-1]["state"] == "done"
    assert ("reading", parts[0], None, epub) in steps.log
    with Ledger() as ledger:
        assert not ledger.skipped_for("ja", runner.BOOKS_WAIT)
