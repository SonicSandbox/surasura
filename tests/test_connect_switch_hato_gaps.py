"""The Connect switch's hato back-fill and surasura.json refresh: the gaps the P3.2 mutant pass found
(research/mutants/JUDGED-P3.2.md) — planted bugs in app/main.py that test_connect_switch.py let through. Each test
names its mutant.

The real dashboard on a hidden root (the switch suite's fixture), the test's own root and its own shared tools folder;
`hato.backfill` stood in for; real subtitles in the library."""
import os

import pytest

from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.test_connect_switch import _hato_connected, _pump, _settings_open, _summary, _switch, \
    dashboard  # noqa: F401  (the fixture)


@pytest.fixture(autouse=True)
def tools(tmp_path, monkeypatch):
    folder = tmp_path / "houseki-tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    return folder


def test_chinese_set_up_alone_is_back_filled_though_japanese_comes_first(dashboard, monkeypatch, tmp_path):
    """P3.2-W15. Japanese not set up (no User Files/ja) is skipped, and the languages after it still are asked for:
    a Chinese-only learner's switch-on back-fills Chinese."""
    from app.connect import hato
    _hato_connected(tmp_path)
    c.library("zh")
    assert not os.path.isdir(os.path.join(h.root(), "User Files", "ja"))
    calls = []
    monkeypatch.setattr(hato, "backfill", lambda lang, settings, **k: (calls.append(lang), _summary(lang))[1])
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert _pump(app.root, lambda: "hato's pairings (Chinese): 3 new, 0 already there." in lines)
    assert calls == ["zh"]


def test_surasura_json_offers_register_before_the_back_fill_asks_hato(dashboard, monkeypatch, tmp_path, tools):
    """P3.2-B61. The back-fill takes up to a minute a language; hato goes on copying drops meanwhile and registers
    each one only while surasura.json lists `register`. So the entry is rewritten (register listed) before hato is
    asked, never after the back-fill."""
    import json
    from app.connect import hato
    cli = tmp_path / "surasura-cli.exe"
    cli.write_bytes(b"MZ")
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(cli))
    _hato_connected(tmp_path)
    c.library(connect=False)
    seen = []

    def backfill(lang, settings, **k):
        with open(tools / "surasura.json", encoding="utf-8") as f:
            seen.append(json.load(f)["verbs"])
        return _summary(lang)
    monkeypatch.setattr(hato, "backfill", backfill)
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert _pump(app.root, lambda: seen)
    assert seen == [["status", "register"]]


def test_the_switch_shows_on_before_the_back_fill_ends(dashboard, monkeypatch, tmp_path):
    """P3.2-B62. The switch is saved on, then shown on (usable again, its controls built) while hato's back-fill still
    runs on the worker — never greyed for the minute a language hato may take."""
    import threading
    from app.connect import hato
    _hato_connected(tmp_path)
    c.library()
    shown, answered = threading.Event(), []
    app, lines = _settings_open(dashboard, monkeypatch)
    real_done = app._connect_switch_done

    def done(*a, **k):
        shown.set()
        return real_done(*a, **k)
    monkeypatch.setattr(app, "_connect_switch_done", done)

    def backfill(lang, settings, **k):
        answered.append(shown.wait(5))            # the Tk thread shows the switch while hato is still being asked
        return _summary(lang)
    monkeypatch.setattr(hato, "backfill", backfill)
    _switch(app, True)
    assert _pump(app.root, lambda: answered)
    assert answered == [True]


def test_a_start_up_refresh_that_fails_with_any_error_is_only_printed(monkeypatch, capsys):
    """P3.2-B67. surasura.json's refresh failing with something other than an OSError (tools_dir's RuntimeError, a
    settings error) is only printed: the window's start, and the switch after its save, go on."""
    from app import tools_entry
    from app.main import MasterDashboardApp

    def boom(settings=None):
        raise RuntimeError("a test reached the real shared tools folder")
    monkeypatch.setattr(tools_entry, "refresh", boom)
    MasterDashboardApp._refresh_tools_entry({"connect_enabled": True})
    assert "Shared tools file (surasura.json): a test reached the real shared tools folder" in capsys.readouterr().out


def test_a_back_fill_failing_with_any_error_is_said_and_the_next_language_still_runs(dashboard, monkeypatch, tmp_path):
    """P3.2-B66. Japanese's back-fill failing with something other than an OSError (a RuntimeError of Surasura's
    own) is said in the Processing Log, and Chinese is still asked for; the switch stays on."""
    from app.connect import hato
    _hato_connected(tmp_path)
    c.library()
    os.makedirs(os.path.join(h.root(), "User Files", "zh"), exist_ok=True)
    calls = []

    def backfill(lang, settings, **k):
        calls.append(lang)
        if lang == "ja":
            raise RuntimeError("a fault of Surasura's own")
        return _summary(lang)
    monkeypatch.setattr(hato, "backfill", backfill)
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert _pump(app.root, lambda: "hato's pairings (Chinese): 3 new, 0 already there." in lines)
    assert any(x.startswith("hato's pairings (Japanese) weren't read: a fault of Surasura's own") for x in lines)
    assert calls == ["ja", "zh"] and app.var_connect_enabled.get() is True
