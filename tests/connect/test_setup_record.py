"""Connect's setup record and the AnkiWeb note (P2.3 row 2.3.1; N12 `setup.json`; 04-onboarding §1 E4 / S2): the record is
replaced whole or not at all, a write that fails is an answer and never a crash, and the AnkiWeb check says what Anki's
own sync found without ever blocking Connect.

The record lives under the test's own SURASURA_TEST_ROOT (tests/conftest.py's sandbox), so nothing real is touched.
Anki is the stand-in from test_setup.py (read-only questions only); Anki Miner is the fake one.
"""
import datetime
import os
import sys
import types

import pytest

import app
from app.connect import setup
from tests.connect.test_setup import StandInAnki, _settings, _synced_once, FEATURES_37


@pytest.fixture
def ready_37(fake_miner):
    """Anki Miner 3.7 with its features, the user's own profile active (no "Surasura" one: optional from 3.7)."""
    fake_miner.plan(app="3.7.0", features=FEATURES_37,
                    profiles=[{"id": "p-main", "name": "メイン", "active": True}])
    _synced_once()
    return fake_miner


def _fake_sync_rule(monkeypatch, state):
    """A stand-in for app.anki_sync_rule that answers the given sync state; the real rule is never run here."""
    fake = types.SimpleNamespace(read_state=lambda: state)
    monkeypatch.setitem(sys.modules, "app.anki_sync_rule", fake)
    monkeypatch.setattr(app, "anki_sync_rule", fake, raising=False)


# --------------------------------------------------------------------------- #
# The AnkiWeb note (E4)
# --------------------------------------------------------------------------- #
def test_ankiweb_not_signed_in_is_named_but_never_blocks(monkeypatch):
    # E4: a missing AnkiWeb login is named with its one action, and the cards are still made (blocks stays False)
    _fake_sync_rule(monkeypatch, {"sync": "not-signed-in"})
    result = setup._ankiweb()
    assert result["state"] == setup.NEEDS_YOU
    assert result["blocks"] is False
    assert "AnkiWeb" in result["say"]


def test_ankiweb_wanting_a_full_sync_is_named_but_never_blocks(monkeypatch):
    # E4: only the user can choose a full sync, so it is named as theirs to do, and it never stops Connect
    _fake_sync_rule(monkeypatch, {"sync": "full-sync"})
    result = setup._ankiweb()
    assert result["state"] == setup.NEEDS_YOU
    assert result["blocks"] is False
    assert "full sync" in result["say"]


def test_ankiweb_last_sync_time_is_shown(monkeypatch):
    # E4: the last sync is shown in the learner's own clock as HH:MM, so they can see whether the order got up
    synced_at = 1791380100.0
    _fake_sync_rule(monkeypatch, {"synced_at": synced_at})
    result = setup._ankiweb()
    at = datetime.datetime.fromtimestamp(synced_at).strftime("%H:%M")
    assert result["state"] == setup.OK
    assert at in result["say"]


# --------------------------------------------------------------------------- #
# The record (N12): a write that fails is an answer, not a crash
# --------------------------------------------------------------------------- #
def test_a_record_that_cant_be_replaced_says_so_and_leaves_no_temp_file(monkeypatch):
    # N12: when the replace is refused, write_record answers False and removes the temp file it had written
    def refuse(src, dst):
        raise PermissionError("the file is open in another program")
    monkeypatch.setattr(setup.os, "replace", refuse)
    assert setup.write_record({"anki_profile": "日本語"}) is False
    folder = os.path.dirname(setup.record_path())
    if os.path.isdir(folder):
        assert not [n for n in os.listdir(folder) if n.endswith(".tmp")], "no temp file left behind"


def test_a_record_written_reads_back_with_its_version(monkeypatch):
    # N12: what Connect writes is what it reads back, stamped with the record's version
    assert setup.write_record({"anki_profile": "中文"}) is True
    record = setup.read_record()
    assert record["anki_profile"] == "中文"
    assert record["version"] == setup.RECORD_VERSION


def test_checks_report_recorded_false_when_the_record_cant_be_written(monkeypatch, ready_37):
    # N12: every check is still answered when the record can't be saved; `recorded` tells the window so
    StandInAnki(monkeypatch, profile="日本語")

    def refuse(src, dst):
        raise PermissionError("the file is open in another program")
    monkeypatch.setattr(setup.os, "replace", refuse)
    result = setup.checks(_settings(ready_37), "ja")
    assert result["recorded"] is False
