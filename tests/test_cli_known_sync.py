"""`surasura-cli known-sync` (P0.3 03; P1.2 row 1.2.4): the window's automatic sync, headless, with its gates
(`anki_sync.may_sync`) and under the `known-words-<lang>` lock.

What a wrong answer would cost, in order:
  * words read into the user's known words behind their back — the FIRST sync is always their own "Sync now" in the
    Anki window (appends can't be taken back): never synced -> `needs-you`, exit 4;
  * Anki hammered by a caller polling it — the 5-minute limit counts from the last sync on disk, across programs;
  * KnownWord.json written by two programs at once, or half-written by a kill — the lock, and an atomic replace.

The Anki sync suite's own fake AnkiConnect (real Japanese words), in this process; never a live Anki.
"""
import datetime
import json
import os
from unittest import mock

import pytest

from app import anki_sync, locks
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.test_anki_sync import FakeCollection

WORDS = ["老婆", "図書館", "引きずる", "隠れ家"]      # none of them in the seeded known words yet
URL = "http://127.0.0.1:18765"              # nothing listens here: only the patched transport answers


@pytest.fixture
def anki(monkeypatch):
    """Decks chosen, synced once from the window an hour ago, Anki open with three studied notes and a new card."""
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    h.seed_library("ja", templates=False)
    h.write_settings(anki_connect_url=URL, anki_sync_decks={"ja": ["TheBank"]}, anki_sync_fields={"ja": []})
    hour_ago = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat(timespec="seconds")
    anki_sync._save_state("ja", {"last_sync": hour_ago})
    fake = FakeCollection()
    for word in WORDS[:3]:
        fake.add(word)
    fake.add(WORDS[3], new=True)
    return fake


def _known_forms():
    with open(os.path.join(h.root(), "User Files", "ja", "KnownWord.json"), encoding="utf-8") as f:
        data = json.load(f)
    return {w["dictForm"] for w in (data if isinstance(data, list) else data["words"])}


def test_a_sync_appends_the_studied_words_and_reads_the_new_cards(anki):
    before = len(_known_forms())
    with mock.patch("urllib.request.urlopen", anki):
        code, line = h.call("known-sync")
    assert code == 0, line
    assert set(WORDS[:3]) <= _known_forms() and WORDS[3] not in _known_forms(), "a new card is never known"
    assert line["added"] == len(_known_forms()) - before > 0 and line["total"] >= line["added"]
    assert line["backlog"] == 1, "the new card is in the backlog"
    assert line["last_sync"] == anki_sync.load_state("ja")["last_sync"]


def test_never_synced_from_the_window_needs_you(anki):
    os.remove(os.path.join(h.root(), "User Files", "ja", anki_sync.STATE_FILE))
    with mock.patch("urllib.request.urlopen", anki):
        code, line = h.call("known-sync")
    assert code == 4 and line["code"] == "needs-you" and "Sync once" in line["message"]
    assert anki.requests == [], "Anki is not even asked"


def test_no_decks_chosen_needs_you(anki):
    h.write_settings(anki_connect_url=URL)
    with mock.patch("urllib.request.urlopen", anki):
        code, line = h.call("known-sync")
    assert code == 4 and line["code"] == "needs-you" and "decks" in line["message"]


def test_a_sync_under_five_minutes_ago_is_skipped_unless_full(anki):
    recent = (datetime.datetime.now() - datetime.timedelta(seconds=60)).isoformat(timespec="seconds")
    anki_sync._save_state("ja", {"last_sync": recent})
    with mock.patch("urllib.request.urlopen", anki):
        code, line = h.call("known-sync")
        assert code == 0 and line["skipped"].startswith("synced 6") and anki.requests == []
        code, line = h.call("known-sync", "--full")
    assert code == 0 and "skipped" not in line and line["added"] > 0


def test_anki_closed_is_anki_closed(anki):
    closed = FakeCollection(offline=True)
    with mock.patch("urllib.request.urlopen", closed):
        code, line = h.call("known-sync")
    assert code == 3 and line["code"] == "anki-closed"


def test_another_program_updating_known_words_makes_it_busy(anki):
    from tests.test_cli_locks import Holder
    with Holder("known-words-ja", "Anki import"), mock.patch("urllib.request.urlopen", anki):
        code, line = h.call("known-sync")
    assert code == 3 and line["code"] == "busy" and line["lock"] == "known-words-ja"
    assert line["held_by"]["verb"] == "Anki import" and anki.requests == []


def test_the_words_are_written_atomically_holding_the_lock(anki, monkeypatch):
    """Every write of KnownWord.json happens with `known-words-ja` held by the writing thread, by temp + replace."""
    seen = []
    real = anki_sync._atomic_write_bytes

    def write(path, data):
        seen.append((os.path.basename(path), locks.held_here("known-words-ja")))
        return real(path, data)
    monkeypatch.setattr(anki_sync, "_atomic_write_bytes", write)
    with mock.patch("urllib.request.urlopen", anki):
        code, _line = h.call("known-sync")
    assert code == 0
    assert ("KnownWord.json", True) in seen and all(held for name, held in seen if name == "KnownWord.json")


def test_an_unreadable_known_words_file_is_bad_data_and_untouched(anki):
    path = os.path.join(h.root(), "User Files", "ja", "KnownWord.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"words": [{"dictForm": "冒険"')
    before = open(path, "rb").read()
    with mock.patch("urllib.request.urlopen", anki):
        code, line = h.call("known-sync")
    assert code == 1 and line["code"] == "bad-data"
    assert open(path, "rb").read() == before


def test_the_test_switch_keeps_anki_out(anki, monkeypatch):
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    with mock.patch("urllib.request.urlopen", anki):
        code, line = h.call("known-sync")
    assert code == 0 and "SURASURA_NO_ANKI_SYNC" in line["skipped"] and anki.requests == []
