"""The dashboard's part of the fast re-plan's preview (E1.1 04 §3; RUNBOOK E3.1.3): its host started, re-aimed and
stopped with 順's switch; the catch-up on focus (never while the Content Manager, or any program of this window, runs);
the re-order after every Generate (the host's) with the Backfill step left as it was; the automatic Generate the
preview asks for — quiet, shown working, never with the Content Manager open, during a Generate or an update, or for
the other language; the close waiting for a re-order or a sync (at most CLOSE_WAIT_S). Off: no host, 2.5's dashboard.

The dashboard's methods run on a stand-in window (its attributes only); the host is a recording stand-in — the real
one has its own file (tests/test_replan_preview.py).
"""
import inspect
import types
from unittest import mock

import pytest

from app import main as main_module
from app import replan_preview

Dash = main_module.MasterDashboardApp
METHODS = ("_replan_start", "replan_preview_changed", "_replan_runs", "_child_running", "_replan_focus",
           "_replan_after_child", "_replan_said", "_want_replan_generate", "_maybe_replan_generate",
           "_replan_finishing", "_maybe_junban_auto")


class Host:
    def __init__(self, language="ja", busy=False):
        self.language = language
        self._busy = busy
        self.calls = []

    def catch_up(self):
        self.calls.append("catch-up")

    def after_generate(self):
        self.calls.append("generate")

    def close(self):
        self.calls.append("close")

    def stop(self):
        self.calls.append("stop")

    def busy(self):
        return self._busy


class Proc:
    def __init__(self, running):
        self.running = running

    def poll(self):
        return None if self.running else 0


def _dash(language="ja", children=(), generating=None):
    d = types.SimpleNamespace()
    for name in METHODS:
        raw = inspect.getattr_static(Dash, name)
        setattr(d, name, raw.__func__ if isinstance(raw, staticmethod) else types.MethodType(getattr(Dash, name), d))
    d.var_language = mock.MagicMock()
    d.var_language.get.return_value = language
    d.var_enable_junban = mock.MagicMock()
    d.var_enable_junban.get.return_value = True
    d.active_processes = list(children)
    d._generate_running = generating
    d.status_var = mock.MagicMock()
    d.gui_queue = mock.MagicMock()
    d.root = mock.MagicMock()
    d.log_to_terminal = mock.MagicMock()
    d._journey_spinner = mock.MagicMock()
    d._junban_spinner = mock.MagicMock()
    d._library_has_content = lambda: True
    d._last_junban_auto = float("-inf")
    d._junban_auto_lock = mock.MagicMock()
    d._junban_auto_lock.acquire.return_value = False      # the 2.5 step's own thread: not under test here
    d.junban_window = None
    d.on_closing = mock.MagicMock()                       # what the close's wait comes back to

    def run_analyzer(quiet=False):
        d.ran = quiet
        d._generate_running = "quiet"
    d.run_analyzer = run_analyzer
    return d


ON = {"junban_replan_preview": True, "enable_junban": True, "junban_scope": "deck", "junban_deck": "TheBank"}


def test_off_there_is_no_host(monkeypatch):
    d = _dash()
    monkeypatch.setattr(main_module.settings_manager, "load_settings", lambda: {"junban_replan_preview": False})
    d._replan_start()
    assert d.__dict__.get("_replan_host") is None
    d._replan_focus()                             # nothing to call
    assert d._maybe_replan_generate() is False


def test_switched_on_a_host_starts_and_catches_up_and_off_again_it_stops(monkeypatch):
    d = _dash()
    made = []
    monkeypatch.setattr(main_module.settings_manager, "load_settings", lambda: dict(ON))
    monkeypatch.setattr(replan_preview, "Host", lambda language, **kw: made.append(Host(language)) or made[-1])
    d.replan_preview_changed()
    host = d._replan_host
    assert made and host.calls == ["catch-up"]
    d.var_language.get.return_value = "zh"        # the language changes: the Japanese preview's host stops
    d._replan_start()
    assert host.calls[-1] == "stop" and d._replan_host is None
    monkeypatch.setattr(main_module.settings_manager, "load_settings",
                        lambda: dict(ON, junban_replan_language="zh"))
    d._replan_start()                             # switched on in the Chinese window: a host for Chinese
    assert d._replan_host.language == "zh"
    monkeypatch.setattr(main_module.settings_manager, "load_settings", lambda: {"junban_replan_preview": False})
    d._replan_start()
    assert d._replan_host is None


def test_the_catch_up_waits_while_the_content_manager_runs():
    d = _dash(children=[Proc(True)])
    d._replan_host = Host()
    d._replan_focus()
    assert d._replan_host.calls == []
    d.active_processes = [Proc(False)]            # it closed: the next focus (or its end) catches up
    d._replan_after_child()
    assert d._replan_host.calls == ["catch-up"]


@pytest.mark.parametrize("why", ["content-manager", "generating", "update", "other-language"])
def test_the_automatic_generate_waits_for_whatever_holds_it_back(monkeypatch, why):
    d = _dash(children=[Proc(why == "content-manager")], generating="manual" if why == "generating" else None)
    d._replan_host = Host("zh" if why == "other-language" else "ja")
    monkeypatch.setattr(main_module.updater, "children_held", lambda: why == "update")
    d._want_replan_generate("moves")
    assert not hasattr(d, "ran")
    assert d._replan_generate_reason == "moves"   # kept: focus or the next program's end asks again


def test_the_automatic_generate_runs_quietly_and_shows_it_is_working(monkeypatch):
    d = _dash()
    d._replan_host = Host()
    monkeypatch.setattr(main_module.updater, "children_held", lambda: False)
    d._want_replan_generate("moves")
    assert d.ran is True                          # quiet: written, not opened
    assert d._generate_running == "automatic"
    d._journey_spinner.assert_called_with(True)   # the check mark's spot spins (✅ G1.5-2: it shows it's working)
    assert "Generate" in d.status_var.set.call_args[0][0]
    assert d._replan_generate_reason is None
    assert d._maybe_replan_generate() is False    # asked once, run once


def test_after_a_generate_the_host_reorders_and_the_backfill_step_is_left_as_it_was(monkeypatch):
    d = _dash()
    d._replan_host = Host()
    seen = {}
    auto = types.SimpleNamespace(enabled=lambda s: seen.setdefault("settings", s) and False,
                                 blocked=lambda s, window=True: None)
    monkeypatch.setitem(__import__("sys").modules, "modules.junban.auto", auto)
    import modules.junban
    monkeypatch.setattr(modules.junban, "auto", auto, raising=False)
    monkeypatch.setattr(main_module.settings_manager, "load_settings",
                        lambda: dict(ON, junban_auto_reorder=True, junban_auto_backfill=True))
    d._maybe_junban_auto(force=True)
    assert d._replan_host.calls == ["generate"]
    assert seen["settings"]["junban_auto_reorder"] is False     # the preview re-orders; 2.5's step doesn't too
    assert seen["settings"]["junban_auto_backfill"] is True


def test_closing_waits_for_a_reorder_then_goes_on():
    d = _dash()
    host = d._replan_host = Host(busy=True)
    with mock.patch.dict("os.environ", {"SURASURA_NO_UI_TIMERS": ""}):
        assert d._replan_finishing() is True              # waits: the bottom bar says so
        d.status_var.set.assert_called_with("Finishing the re-order in Anki…")
        d.root.after.assert_called_with(100, d.on_closing)
        assert host.calls == ["close"]
        host._busy = False
        assert d._replan_finishing() is False             # done: the close goes on
    assert host.calls == ["close", "stop"] and d._replan_host is None


def test_a_dashboard_save_never_writes_the_previews_keys_into_a_file_without_them():
    """Off = 2.5's settings.json too: the dashboard's save carries the switch, its language and the sync minute only
    as the file holds them (JUNBAN_AS_WRITTEN, `as_written`) — never a default into a 2.5 user's file."""
    from tests.test_settings_signatures import _dashboard_saved, _write
    _write({"target_language": "ja"})
    saved = _dashboard_saved()
    for key in ("junban_replan_preview", "junban_replan_language", "junban_replan_deck", "anki_sync_delay_min"):
        assert key not in saved, key
    _write({"target_language": "ja", "junban_replan_preview": True, "junban_replan_language": "ja",
            "anki_sync_delay_min": "off"})
    saved = _dashboard_saved()
    assert saved["junban_replan_preview"] is True and saved["junban_replan_language"] == "ja"
    assert saved["anki_sync_delay_min"] == "off"


def test_the_host_is_only_for_the_language_the_preview_was_switched_on_in(monkeypatch):
    d = _dash(language="zh")
    monkeypatch.setattr(main_module.settings_manager, "load_settings",
                        lambda: dict(ON, junban_replan_language="ja"))
    monkeypatch.setattr(replan_preview, "Host", lambda language, **kw: Host(language))
    d._replan_start()
    assert d.__dict__.get("_replan_host") is None          # a Chinese window never re-orders the Japanese deck
    d.var_language.get.return_value = "ja"
    d._replan_start()
    assert d._replan_host.language == "ja"


def test_update_now_stops_the_helper_and_a_cancel_starts_it_again(monkeypatch):
    """Pass 4 #1: the preview's helper is a Surasura process the update would wait for (and this window's hold isn't
    its own) — "Update now" stops it; a cancelled update starts it again."""
    d = _dash()
    d._replan_stop_for_update = types.MethodType(Dash._replan_stop_for_update, d)
    d._end_update = types.MethodType(Dash._end_update, d)
    made = []
    monkeypatch.setattr(main_module.settings_manager, "load_settings", lambda: dict(ON))
    monkeypatch.setattr(replan_preview, "Host", lambda language, **kw: made.append(Host(language)) or made[-1])
    d._replan_start()
    first = d._replan_host
    d._replan_stop_for_update()
    assert first.calls[-1] == "stop" and d._replan_host is None
    d._update_job = None
    d._end_update({"after": None, "window": None, "done": False}, start_held=True)
    assert d._replan_host is not None and d._replan_host is not first
    assert "_replan_stop_for_update()" in inspect.getsource(Dash._start_update)
