"""The Connect switch's gaps the P3.1 mutant pass found (2026-10-11): each test pins one rule a planted bug got past.

What a wrong answer would cost:
  * a switch-on that leaves a ledger file behind with nothing made (a made ledger reads as "Connect has run here"), or
    a library handle open on a worker (its close is never left to the collector, §6.12);
  * Chinese treated as Japanese: a Chinese library that won't open switched on anyway, Chinese's last list never
    forgotten (a level raise while off mined), Chinese's shelf never offered back;
  * a switch-off that puts back only the first of two restore points, or turns off with a put-back skipped;
  * a session look (it may open Anki) after a switch that stayed on, or a panel built after the switch went off;
  * a Connect window left open after the switch went off.
The real dashboard on a hidden root (the switch suite's fixture); Connect's status record and `undo.act` stood in
for."""
import os
import sys
import tkinter as tk
from unittest.mock import patch

from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect_tk_helpers import read_settings, settings_bytes
from tests.test_connect_switch import (SHELF, _act_refusing, _answers, _pump, _settings_open, _shelf, _switch,
                                       dashboard)  # noqa: F401  (the fixture)


def _no_session(app, monkeypatch):
    sessions = []
    monkeypatch.setattr(app, "_connect_session", lambda *a, **k: sessions.append(1))
    return sessions


# --- switching on ---------------------------------------------------------------------------------------------------

def test_switching_on_with_no_ledger_yet_makes_no_ledger(dashboard, monkeypatch):
    # Nothing made yet: there is no list to forget, and a look must never create the ledger file
    from app.connect.ledger import path
    app, _lines = _settings_open(dashboard, monkeypatch)
    _no_session(app, monkeypatch)
    assert not os.path.exists(path())
    _switch(app, True)
    assert read_settings()["connect_enabled"] is True
    assert not os.path.exists(path()), "the switch-on made no ledger"


def test_switching_on_closes_the_library_it_opened(dashboard, monkeypatch):
    from app.connect import library
    c.library()
    app, _lines = _settings_open(dashboard, monkeypatch)
    _no_session(app, monkeypatch)
    opened, closed, real = [], [], library.open_store

    def open_store(lang, role="connect"):
        store = real(lang, role=role)
        if store is not None:
            opened.append(store)
            close = store.close
            store.close = lambda: (closed.append(store), close())[1]
        return store
    monkeypatch.setattr(library, "open_store", open_store)
    _switch(app, True)
    assert opened, "Japanese's library was opened for its watermark"
    assert closed == opened, "every library the switch-on opened is closed (never left to the collector)"


def test_a_chinese_library_there_but_not_opening_is_named_and_the_switch_stays_off(dashboard, monkeypatch):
    # Chinese's own library file is what decides "busy", never Japanese's (here Japanese has none)
    from app import library_store
    from app.connect import library
    from app.path_utils import get_data_path
    app, lines = _settings_open(dashboard, monkeypatch)
    db = library_store.library_db_path("zh", get_data_path("zh"))
    os.makedirs(os.path.dirname(db), exist_ok=True)
    open(db, "wb").close()
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": None)
    before = settings_bytes()
    _switch(app, True)
    assert settings_bytes() == before and app.var_connect_enabled.get() is False
    assert [line for line in lines if line.startswith("Connect wasn't switched on")] == [
        "Connect wasn't switched on: Chinese: the library is busy; try again in a moment. Nothing changed; try again."]


def test_switched_on_again_chineses_last_list_is_forgotten_too(dashboard, monkeypatch):
    # G1.1-2 for each language: 一生懸命 joined Chinese's list while Connect was off; a first look mines nothing
    from app.connect import level
    from app.connect.ledger import Ledger
    with Ledger() as ledger, ledger.transaction():
        ledger.record_list("zh", "generate-1", {("电视剧", "dian4 shi4 ju4")})
    app, _lines = _settings_open(dashboard, monkeypatch)
    _no_session(app, monkeypatch)
    _switch(app, True)
    listed = {("电视剧", "dian4 shi4 ju4"), ("一生懸命", "yi1 sheng1 xuan2 ming4")}
    out = level.check(None, "zh", listed, "generate-2", {})
    assert out["first"] is True and out["new"] == 0 and out["queued"] == [], "Chinese's list was forgotten"


def test_connects_modules_failing_to_import_leave_the_switch_off(dashboard, monkeypatch):
    app, lines = _settings_open(dashboard, monkeypatch)
    sessions = _no_session(app, monkeypatch)
    import app.connect as package
    monkeypatch.delattr(package, "level", raising=False)
    monkeypatch.setitem(sys.modules, "app.connect.level", None)        # an install missing a piece of Connect
    before = settings_bytes()
    _switch(app, True)
    assert settings_bytes() == before and app.var_connect_enabled.get() is False and sessions == []
    assert any(line.startswith("Connect wasn't switched on: ") for line in lines)
    assert not any(line.startswith("Connect is on") for line in lines)


def test_switched_off_while_settings_were_read_no_panel_is_built_and_it_can_be_built_again(dashboard, monkeypatch):
    from app import main
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    app._connect_panel_drop()
    workers = []

    class Held:                                     # the read's worker, started by the test when it chooses
        def __init__(self, target=None, args=(), daemon=None):
            self.target = target

        def start(self):
            workers.append(self.target)
    with patch.object(main.threading, "Thread", Held):
        app._connect_panel_build()
    assert len(workers) == 1 and app._connect_panel is None
    app._current_settings = dict(app._current_settings, connect_enabled=False)    # switched off meanwhile
    workers[0]()
    _pump(app.root, lambda: False, timeout=0.5)
    assert app._connect_panel is None, "off by the time the read came back: no panel"
    app._current_settings = dict(app._current_settings, connect_enabled=True)     # on again: it can be built
    app._connect_panel_build()
    assert _pump(app.root, lambda: app._connect_panel is not None)


# --- switching off --------------------------------------------------------------------------------------------------

def test_every_restore_point_with_cards_on_it_is_put_back(dashboard, monkeypatch):
    from tkinter import messagebox
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    two = {"ja": {"shelf": {"on_shelf": 5, "swap_ins": 0, "runs": [
               {"run": "shelf-2026-10-11-a", "cards": 3, "back": 0, "why": "the cap", "at": "2026-10-11T09:00:00Z",
                "words": ["上層部"]},
               {"run": "shelf-2026-10-10-a", "cards": 2, "back": 0, "why": "the cap", "at": "2026-10-10T09:00:00Z",
                "words": ["気配"]}]}}}
    acts = _shelf(monkeypatch, two)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    _switch(app, False)
    assert [a[1] for a in acts] == ["shelf-2026-10-11-a", "shelf-2026-10-10-a"], "both restore points"
    assert read_settings()["connect_enabled"] is False


def test_a_chinese_shelf_is_asked_about_and_put_back(dashboard, monkeypatch):
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    zh = {"ja": {"shelf": {"on_shelf": 0, "runs": [], "swap_ins": 0}},
          "zh": {"shelf": {"on_shelf": 2, "swap_ins": 0, "runs": [
              {"run": "shelf-2026-10-11-z", "cards": 2, "back": 0, "why": "the cap", "at": "2026-10-11T09:00:00Z",
               "words": ["电视剧"]}]}}}
    acts = _shelf(monkeypatch, zh)
    from app.connect import status
    monkeypatch.setattr(status, "read",                  # each language read as asked: Chinese must be asked too
                        lambda languages=None, **k: {"languages": {lang: zh[lang] for lang in languages}})
    asked = _answers(monkeypatch, True)
    _switch(app, False)
    assert [t for t, _m in asked] == ["Put the 2 shelved cards back into your new cards?"]
    assert [(a[0], a[1]) for a in acts] == [("zh", "shelf-2026-10-11-z")]


def test_without_junban_the_switch_off_asks_nothing_about_the_shelf(dashboard, monkeypatch):
    # Nothing could put the cards back: no question, and the switch goes off
    from app.connect import setup
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    acts = _shelf(monkeypatch, SHELF)
    monkeypatch.setattr(setup, "_present", lambda module: False)
    asked = _answers(monkeypatch)
    _switch(app, False)
    assert asked == [] and acts == [] and read_settings()["connect_enabled"] is False


def test_a_put_back_skipped_keeps_connect_on_and_asks(dashboard, monkeypatch):
    from app.connect import undo
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    _shelf(monkeypatch, SHELF)
    monkeypatch.setattr(undo, "act", lambda settings, language, **k: {"skipped": undo.NO_ANKI})
    asked = _answers(monkeypatch, True, False)
    _switch(app, False)
    assert len(asked) == 2 and f"Not done: {undo.NO_ANKI}." in asked[1][0]
    assert read_settings()["connect_enabled"] is True and app.var_connect_enabled.get() is True


def test_a_switch_off_whose_save_fails_starts_no_session_look(dashboard, monkeypatch):
    # The session look may open Anki: only a fresh switch-on starts one
    from app import settings_manager
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    sessions = _no_session(app, monkeypatch)
    monkeypatch.setattr(settings_manager, "save_settings", lambda *a, **k: False)
    _switch(app, False)
    assert app.var_connect_enabled.get() is True and sessions == []


def test_staying_on_after_a_failed_put_back_starts_no_session_look(dashboard, monkeypatch):
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    sessions = _no_session(app, monkeypatch)
    _shelf(monkeypatch, SHELF)
    _act_refusing(monkeypatch)
    _answers(monkeypatch, True, False)              # put back: yes; Anki refuses; off anyway: no
    _switch(app, False)
    assert app.var_connect_enabled.get() is True and sessions == []


def test_switching_off_closes_connects_window(dashboard, monkeypatch):
    import types
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    _shelf(monkeypatch, {"ja": {"shelf": {"on_shelf": 0, "runs": [], "swap_ins": 0}}})
    win = tk.Toplevel(app.root)
    app._connect_window = types.SimpleNamespace(win=win)
    _switch(app, False)
    assert not win.winfo_exists() and app._connect_window is None
