"""`surasura-cli setup` (P2.3 row 2.3.2; P0.3 03-verbs' *setup checks* row) as a caller runs it: exit 0 with every
check in order whatever is missing, the setup record written only while Connect's preview is on, and
`--use-anki-profile` for Connect's preview only. Anki is a closed loopback port, or a stand-in in-process; Anki Miner
is the fake one.
"""
import json
import os

import pytest

from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_anki_miner import FEATURES_37


@pytest.fixture
def set_up():
    for lang in ("ja", "zh"):
        os.makedirs(os.path.join(h.root(), "User Files", lang), exist_ok=True)


def _record():
    path = os.path.join(h.root(), "local", "connect", "setup.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_setup_answers_every_check_in_order_and_exits_0_whatever_is_missing(set_up, fake_miner):
    h.write_settings(connect_anki_miner_path=fake_miner.path, connect_enabled=True)
    fake_miner.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}])
    code, lines = h.run_cli("setup", "--lang", "ja", env={"SURASURA_NO_ANKI_SYNC": None})
    result = h.answer(lines)
    assert code == 0 and result["ok"] and result["ready"] is False, result
    assert [c["id"] for c in result["checks"]][:4] == ["anki", "anki_profile", "ankiweb", "first_known_sync"]
    anki = result["checks"][0]
    assert anki["state"] == "waiting" and anki["do"] == "Open Anki"           # the closed port: Anki closed
    assert result["anki_miner"]["app"] == "3.7.0" and result["connect"] is True
    record = _record()
    assert record and record["anki_miner"]["app"] == "3.7.0" and "anki_profile" not in record


def test_with_connects_preview_off_setup_writes_nothing(set_up, fake_miner):
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    code, lines = h.run_cli("setup", "--lang", "zh")
    result = h.answer(lines)
    assert code == 0 and result["recorded"] is False and result["connect"] is False
    assert _record() is None and not os.path.exists(os.path.join(h.root(), "local", "connect"))


def test_use_anki_profile_is_for_connects_preview_only(set_up):
    h.write_settings()
    code, lines = h.run_cli("setup", "--use-anki-profile")
    assert code == 2 and h.answer(lines)["code"] == "usage"


def test_use_anki_profile_with_anki_closed_says_so(set_up):
    h.write_settings(connect_enabled=True)
    code, lines = h.run_cli("setup", "--use-anki-profile", env={"SURASURA_NO_ANKI_SYNC": None})
    assert code == 3 and h.answer(lines)["code"] == "anki-closed"
    assert "Anki isn't open" in h.answer(lines)["message"]


def test_use_anki_profile_with_anki_switched_off_for_the_run_says_that(set_up):
    h.write_settings(connect_enabled=True)
    code, lines = h.run_cli("setup", "--use-anki-profile")
    assert code == 3 and "isn't asked in this run" in h.answer(lines)["message"]


def test_use_anki_profile_moves_connect_to_the_open_profile(set_up, monkeypatch):
    # In-process, so the stand-in Anki can answer: set up with 日本語, then DevTest is open and the user says use it
    from app import anki_connect
    from app.connect import setup
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    opened = {"profile": "日本語"}
    monkeypatch.setattr(anki_connect, "probe", lambda url, required=(), timeout=5: {"ok": True, "missing": []})
    monkeypatch.setattr(anki_connect, "invoke", lambda action, url, timeout=30, **p: opened["profile"])
    h.write_settings(connect_enabled=True)
    code, result = h.call("setup")
    assert code == 0 and result["anki_profile"] == "日本語"
    opened["profile"] = "DevTest"
    code, result = h.call("setup")
    assert code == 0 and result["anki_profile"] == "日本語" and result["checks"][1]["state"] == "waiting"
    code, result = h.call("setup", "--use-anki-profile")
    assert code == 0 and result["anki_profile"] == "DevTest" and setup.anki_profile() == "DevTest"


def test_setup_is_listed_in_the_command_lines_help():
    from app.cli import __main__ as cli
    assert cli.VERBS["setup"][2] is True
