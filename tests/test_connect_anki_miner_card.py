"""The Anki Miner card and the star (P3.1 row 3.1.3; P1.5 05-surface U5, U6, 04-onboarding §2–§3).

What a wrong answer would cost: a card that says *Ready* while Anki Miner's setup is missing leaves the user waiting
for cards that never come; *Install* that downloads by itself is a network call nobody approved (2.x opens the
releases page in the browser); a star suggestion that keeps coming back after *Not now* — or one written into
settings.json, which ships — nags and leaks. `setup.checks` is faked (each state as it answers); the browser is
mocked; no socket may open."""
import os
import socket
from unittest import mock

import pytest

from app.connect import ledger, settings_panel, setup
from tests import cli_helpers as h
from tests.connect_tk_helpers import Pump, Tips, on_main, settings_bytes, tk_root, widgets


def _checks(*states, version="3.6.0"):
    ids = ("anki_miner", "anki_miner_version", "anki_miner_profile", "anki_miner_setup")
    says = {"anki_miner": "Anki Miner isn't installed.", "anki_miner_version": f"Anki Miner {version} answers.",
            "anki_miner_profile": "Anki Miner has no profile named Surasura yet.",
            "anki_miner_setup": "Anki Miner's own setup isn't finished (deck: not chosen)."}
    checks = [{"id": i, "state": s, "say": says[i] if s != "ok" else "fine"} for i, s in zip(ids, states)]
    for c in checks:            # an Anki Miner before 3.7 lacking its "Surasura" profile: the update first (setup.py)
        if c["id"] == "anki_miner_profile" and c["state"] == "needs-you":
            c["update"] = True
    found = {"path": "C:\\Programs\\AnkiMiner\\AnkiMiner.exe", "app": version} if states[0] == "ok" else None
    return {"checks": checks, "anki_miner": found}


NOT_INSTALLED = _checks("needs-you", "not-checked", "not-checked", "not-checked")
NEEDS_SETUP = _checks("ok", "ok", "needs-you", "not-checked")
READY = _checks("ok", "ok", "ok", "ok", version="3.7.0")


@pytest.fixture
def root():
    r = tk_root()
    try:
        yield r
    finally:
        r.destroy()


@pytest.fixture(autouse=True)
def no_socket(monkeypatch):
    """No call leaves the machine: a socket that connects fails the test."""
    def refuse(*_a, **_k):
        raise AssertionError("a socket was opened")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _card(root, answer):
    h.write_settings(connect_enabled=True)
    calls, pump, tips = [], Pump(), Tips()

    def checks(settings, language):
        calls.append((language, on_main()))
        return answer
    panel = settings_panel.build(root, lambda: "ja", tips, {"connect_enabled": True}, checks=checks, post=pump.put)
    assert pump.run(root, lambda: panel.lbl_state.cget("text") != "Checking…")
    return panel, calls, pump, tips


def _texts(widget):
    from tkinter import ttk
    return [w.cget("text") for w in widgets(widget, (ttk.Label, ttk.Button))]


def test_not_installed_offers_install_in_the_browser_and_no_star(root):
    panel, calls, _pump, tips = _card(root, NOT_INSTALLED)
    assert calls == [("ja", False)], "checked once, on a worker"
    assert panel.lbl_state.cget("text") == "Not installed"
    assert set(panel.card_buttons) == {"Install", "Browse…", "Check again"}
    assert panel.star_box is None, "the star comes once Anki Miner is found installed"
    with mock.patch("webbrowser.open") as opened:
        panel.card_buttons["Install"].invoke()
    opened.assert_called_once_with(setup.RELEASES)
    assert all(tips.has(b) for b in panel.card_buttons.values())


def test_installed_but_not_set_up_names_the_pieces_and_the_two_steps(root):
    panel, _calls, _pump, _tips = _card(root, NEEDS_SETUP)
    assert panel.lbl_state.cget("text") == "Installed 3.6.0 — needs setup"
    texts = _texts(panel.card_frame)
    assert "Anki Miner has no profile named Surasura yet." in texts
    assert any(t.startswith("1. In Anki Miner: Manage profiles") for t in texts)
    assert "Copy path" in texts and "Open Anki Miner" in panel.card_buttons
    from app.connect import anki_miner
    panel.btn_copy.invoke()
    assert root.clipboard_get() == anki_miner.whitelist_path("ja")
    assert panel.star_box is not None, "found installed: the star suggestion shows"


def test_ready_says_so_with_its_version(root):
    panel, _calls, _pump, _tips = _card(root, READY)
    assert panel.lbl_state.cget("text") == "Ready — Anki Miner 3.7.0"
    assert not any(t.startswith("1. In Anki Miner") for t in _texts(panel.card_frame))


def test_not_now_is_kept_in_local_data_never_in_settings(root):
    panel, _calls, pump, _tips = _card(root, READY)
    before = settings_bytes()
    panel.btn_not_now.invoke()
    star = os.path.join(ledger.folder(), settings_panel.STAR_FILE)
    assert pump.run(root, lambda: os.path.exists(star))
    assert panel.star_box is None
    assert settings_bytes() == before, "settings.json untouched"
    panel.card_buttons["Check again"].invoke()
    assert pump.run(root, lambda: "Open Anki Miner" in panel.card_buttons and
                    panel.lbl_state.cget("text").startswith("Ready"))
    assert panel.star_box is None, "answered: never suggested again"
    assert panel.link_star.winfo_exists() and panel.link_star.cget("text") == "⭐ Anki Miner on GitHub"


def test_the_star_opens_anki_miners_page_and_is_answered(root):
    panel, _calls, pump, tips = _card(root, NEEDS_SETUP)
    assert tips.has(panel.btn_star) and "needs a GitHub account" in dict((id(w), t) for w, t in tips)[id(panel.btn_star)]
    with mock.patch("webbrowser.open") as opened:
        panel.btn_star.invoke()
    opened.assert_called_once_with(settings_panel.STAR_URL)
    assert pump.run(root, settings_panel.star_answered)
