"""The verbs on Connect's Anki session (P2.3 row 2.3.5; ✅ Q4-1, Q4-4; E1.1 04 §3's one sync rule): with Connect's
preview on, `known-sync`, `junban --auto`, `resort` and `backfill` ask for the session's one sync before they read or
write Anki — your phone's reviews come in first — and never again inside the session; a writer that leaves an S3 sync
pending kicks Connect, whose run sends it before it exits (`connect` → `settle`). Off, no sync is asked and nothing of
the session is looked at: every request as before. A dry run never syncs (it changes nothing, and a sync would).

What a wrong answer would cost: a position or a field written over a card studied on the phone (the desktop's write
wins the next sync and the review is lost); a sync per verb call (AnkiWeb's "sync too often", the phone's battery);
a 2.5 user's Anki asked to sync behind their back.

Each suite's own fake collection (real Japanese words) behind one wrapper that answers the session's questions (the
open profile, a sync) and logs every action, in this process; never a live Anki.
"""
import datetime
import json
import os
from types import SimpleNamespace
from unittest import mock

import pytest

anki_sync_rule = pytest.importorskip("app.anki_sync_rule")      # E3.1's
from app.connect import kick
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

URL = "http://127.0.0.1:18765"              # nothing listens here: only the patched transport answers
JOB = "job-20261008-1"
TAG = "surasura::connect::" + JOB


class _Response:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Session:
    """A suite's fake collection with the session's two questions answered: Anki's open profile and a sync (which
    counts). Every action, in order, in `log`."""

    def __init__(self, inner, profile="日本語"):
        self.inner, self.profile, self.log, self.syncs = inner, profile, [], 0

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        self.log.append(payload["action"])
        if payload["action"] == "getActiveProfile":
            return _Response(json.dumps({"result": self.profile, "error": None}).encode("utf-8"))
        if payload["action"] == "sync":
            self.syncs += 1
            return _Response(json.dumps({"result": None, "error": None}).encode("utf-8"))
        return self.inner(request, timeout)

    def first(self, *actions):
        return min(i for i, a in enumerate(self.log) if a in actions)


@pytest.fixture
def kicks(monkeypatch):
    """Connect's kicks, recorded: no process is started under a test root anyway."""
    started = []
    monkeypatch.setattr(kick, "kick", lambda settings: started.append(bool(settings.get("connect_enabled"))))
    return started


# --------------------------------------------------------------------------- #
# junban --auto, resort (Junban's fake collection, as tests/test_cli_resort.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def deck(monkeypatch):
    rep = pytest.importorskip("modules.junban.tests.test_reposition")
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    rep._results(h.root(), progressive=rep._JOURNEY, library=rep._LIBRARY, floor=11)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)

    def setup(**over):
        cards, notes, _ = rep._collection(["須藤", "散歩", "図書館", "冒険", "眼鏡", "老婆"])
        fake = rep.FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend"))
        saved = rep._settings(**{**dict(junban_order="content", enable_junban=True), **over})
        saved.pop("junban_url", None)
        h.write_settings(**{**saved, "anki_connect_url": URL})
        wrapped = Session(fake)
        return wrapped, mock.patch("urllib.request.urlopen", wrapped)
    return setup


def test_resort_syncs_once_before_it_reads_anki_and_never_again_in_the_session(deck, kicks):
    anki, patched = deck(connect_enabled=True)
    with patched:
        code, line = h.call("resort")
        assert code == 0 and line["moves"] > 0, line
        assert anki.syncs == 1, anki.log
        assert anki.log.index("sync") < anki.first("findCards", "cardsInfo"), "the phone's reviews in before the read"
        code, again = h.call("resort")
    assert code == 0 and anki.syncs == 1, "inside a session nothing re-syncs (Q4-4)"


def test_a_dense_run_that_changed_tomorrows_cards_kicks_connect_to_send_the_sync(deck, kicks):
    # The re-plan preview off: 2.5's dense block, whose front the verb reads itself (`front_changed`); the S3 sync is
    # left pending for Connect's run, never waited for here
    anki, patched = deck(connect_enabled=True)
    with patched:
        code, line = h.call("junban", "--auto")
    assert code == 0 and line["moves"] > 0, line
    assert anki_sync_rule.read_state().get("front_pending") is True
    assert kicks == [True] and anki.syncs == 1, "only the session's sync: S3's waits for its minute"


def test_a_spaced_run_tells_the_rule_itself_and_the_verb_kicks_connect_for_it(deck, kicks):
    anki, patched = deck(connect_enabled=True, junban_replan_preview=True)
    with patched:
        code, line = h.call("resort")
    assert code == 0 and line["numbering"] == "full" and line["moves"] > 0, line
    assert anki.syncs == 1 and anki_sync_rule.read_state().get("front_pending") is True and kicks == [True]


def test_with_connect_off_junban_asks_no_sync_and_nothing_of_the_session(deck, kicks):
    anki, patched = deck(connect_enabled=False)
    with patched:
        code, line = h.call("junban", "--auto")
    assert code == 0 and line["moves"] > 0, line
    assert "sync" not in anki.log and "getActiveProfile" not in anki.log, anki.log
    assert kicks == [] and anki_sync_rule.read_state() == {}


def test_off_the_verbs_never_import_the_session(monkeypatch):
    # Connect's preview off, or Anki switched off for the run: nothing of Connect's session is reached at all
    from app.cli import verbs
    from app.connect import anki_session
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    assert verbs._session({"connect_enabled": False}) is None and verbs._session({}) is None
    assert verbs._session({"connect_enabled": True}) is anki_session
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    assert verbs._session({"connect_enabled": True}) is None


def test_a_dry_run_never_syncs(deck, kicks):
    anki, patched = deck(connect_enabled=True)
    with patched:
        code, line = h.call("resort", "--dry-run")
        assert code == 0 and line["moves"] > 0 and line["undo"] is None, line
        code, line = h.call("junban", "--dry-run")
    assert code == 0 and anki.syncs == 0 and "getActiveProfile" not in anki.log and kicks == []


def test_a_review_in_progress_holds_the_sync_and_the_run_alike(deck, kicks):
    # Never during a review (E1.1 04 §3): the session stays due, and the run itself refuses (`anki-busy`)
    anki, patched = deck(connect_enabled=True)
    anki.inner.reviewing = True
    with patched:
        code, line = h.call("resort")
    assert anki.syncs == 0 and line["code"] == "anki-busy", line
    assert anki_sync_rule.read_state().get("session_due") is True


# --------------------------------------------------------------------------- #
# known-sync (the Anki sync suite's fake, as tests/test_cli_known_sync.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def known(monkeypatch):
    from tests.test_anki_sync import FakeCollection
    from app import anki_sync
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    h.seed_library("ja", templates=False)
    hour_ago = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat(timespec="seconds")
    anki_sync._save_state("ja", {"last_sync": hour_ago})
    fake = FakeCollection()
    for word in ("老婆", "図書館", "引きずる"):
        fake.add(word)

    def setup(**over):
        h.write_settings(anki_connect_url=URL, anki_sync_decks={"ja": ["TheBank"]}, anki_sync_fields={"ja": []},
                         **over)
        wrapped = Session(fake)
        return wrapped, mock.patch("urllib.request.urlopen", wrapped)
    return setup


def test_known_sync_reads_what_you_studied_only_after_the_sessions_sync(known, kicks):
    anki, patched = known(connect_enabled=True)
    with patched:
        code, line = h.call("known-sync")
        assert code == 0 and line["added"] > 0, line
        assert anki.syncs == 1 and anki.log.index("sync") < anki.first("findNotes", "notesInfo"), anki.log
        code, line = h.call("known-sync", "--full")
    assert code == 0 and anki.syncs == 1, "the same session: no second sync"
    assert kicks == [], "a reader leaves no sync pending"


def test_known_sync_with_connect_off_is_as_before(known, kicks):
    anki, patched = known(connect_enabled=False)
    with patched:
        code, line = h.call("known-sync")
    assert code == 0 and line["added"] > 0, line
    assert "sync" not in anki.log and "getActiveProfile" not in anki.log, anki.log


# --------------------------------------------------------------------------- #
# backfill (Junban's Backfill fake, as tests/test_cli_backfill.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def notes(monkeypatch):
    tb = pytest.importorskip("modules.junban.tests.test_backfill")
    from modules.junban import backfill
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(backfill, "Session", lambda settings: tb._Session())

    class Tagged(tb.BackfillCollection):
        def _find_notes(self, query):
            if '"tag:' in query:
                tag = query.split('"tag:')[1].split('"')[0].lower()
                return sorted(n for n, note in self.notes.items()
                              if tag in [str(t).lower() for t in note.get("tags") or ()])
            return super()._find_notes(query)

    pairs = [tb._lapis(0, "探検", "たんけん"), tb._lapis(1, "囲む", "かこむ")]
    for note, _card in pairs:
        note["tags"] = [TAG]
    fake = Tagged([p[1] for p in pairs], [p[0] for p in pairs], {"Lapis": tb.LAPIS})
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)

    def setup(**over):
        h.write_settings(anki_connect_url=URL, enable_junban=True, junban_backfill_deck="TheBank",
                         junban_backfill_fills=["patterns"], **over)
        wrapped = Session(fake)
        return SimpleNamespace(anki=wrapped, patched=mock.patch("urllib.request.urlopen", wrapped))
    return setup


def test_backfill_syncs_before_it_reads_the_notes_and_a_fill_never_starts_s3(notes, kicks):
    run = notes(connect_enabled=True)
    with run.patched:
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 0 and line["filled"] > 0, line
    assert run.anki.syncs == 1 and run.anki.log.index("sync") < run.anki.first("findNotes", "notesInfo")
    state = anki_sync_rule.read_state()
    assert state.get("front_pending") is not True and state.get("last_write"), "the session's last write, no S3"
    assert kicks == []


def test_a_fill_inside_a_session_is_its_last_write_and_never_syncs_again(notes, kicks):
    # The session started ten minutes ago (the window's look): the fill asks no sync, and counts as the session's
    # last write — so the hour without a Surasura write that starts the next session counts from it
    import time
    started = time.time() - 600
    anki_sync_rule._write_state({"profile": "日本語", "session_at": started, "last_write": started, "sync": "synced"})
    run = notes(connect_enabled=True)
    with run.patched:
        code, line = h.call("backfill", "--tag", TAG)
    assert code == 0 and line["filled"] > 0 and run.anki.syncs == 0, line
    assert anki_sync_rule.read_state()["last_write"] > started + 500


def test_backfill_dry_run_never_syncs(notes, kicks):
    run = notes(connect_enabled=True)
    with run.patched:
        code, line = h.call("backfill", "--tag", TAG, "--dry-run")
    assert code == 0 and line["dry_run"] is True, line
    assert run.anki.syncs == 0 and "getActiveProfile" not in run.anki.log


# --------------------------------------------------------------------------- #
# connect: the pending sync sent before it exits
# --------------------------------------------------------------------------- #
def _connect_library(**settings):
    from tests import connect_helpers as c
    c.library("ja", anki_connect_url=URL, **settings)


def _idle_anki():
    """An Anki that answers the session's questions and nothing else asked of it here."""
    from modules.junban.tests.test_reposition import FakeCollection
    return Session(FakeCollection([], []))


def test_connect_sends_the_pending_sync_before_it_exits(monkeypatch):
    pytest.importorskip("modules.junban.tests.test_reposition")
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    _connect_library(anki_sync_delay_min=0)
    anki = _idle_anki()
    with mock.patch("urllib.request.urlopen", anki):
        anki_sync_rule.wrote(True, {"anki_sync_delay_min": 0})      # a writer verb's S3, left for Connect
        code, line = h.call("connect", "--consume-only")
    assert code == 0, line
    assert anki.syncs == 1 and anki_sync_rule.read_state().get("front_pending") is False


def test_connect_with_nothing_pending_asks_anki_nothing(monkeypatch):
    pytest.importorskip("modules.junban.tests.test_reposition")
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    _connect_library()
    anki = _idle_anki()
    with mock.patch("urllib.request.urlopen", anki):
        code, line = h.call("connect", "--consume-only")
    assert code == 0 and anki.log == [], anki.log
