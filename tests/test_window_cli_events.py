"""The window and the command line beside it (P0.3 02 §4, 04 §2; P1.2 row 1.2.7; ✅ G0.3-1, Sonic: "if the GUI is up it
should not force quit the GUI, just should show the error down below and write to logs").

What a wrong answer would cost, in order:
  * a background job's failure that nobody sees — a Connect run whose Generate crashed, the list silently stale;
  * a failure that takes the window down, or a box that blocks it;
  * a settings click lost, or the window frozen, while another program holds the settings lock.

A real command-line call writes the events file; the real dashboard (Tk, withdrawn) reads it.
"""
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app import settings_manager
from app.cli import events as cli_events
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.test_settings_signatures import start_dashboard  # noqa: F401  (fixture)


def _fail_a_call():
    """A real failing call: settings.json cut short -> `bad-data`, exit 1 (an event)."""
    with open(os.path.join(h.root(), "settings.json"), "w", encoding="utf-8") as f:
        f.write('{"target_language": "ja",')
    code, lines = h.run_cli("status")
    assert code == 1 and h.answer(lines)["code"] == "bad-data"


def test_a_failing_call_lands_in_the_events_file_and_a_reader_started_before_sees_it():
    h.seed_library("ja", templates=False)
    reader = cli_events.Reader()                            # the window opens: earlier history is not news
    h.run_cli("nope")                                      # a wrong command: an event, never shown
    assert reader.changed()
    _fail_a_call()
    event = reader.newest_to_show()
    assert event["code"] == "bad-data" and event["verb"] == "status" and event["exit"] == 1
    assert cli_events.plain(event).startswith("Command line (status): Surasura's settings")
    assert reader.newest_to_show() is None and not reader.changed(), "shown once"


def test_busy_and_wrong_commands_are_not_shown():
    reader = cli_events.Reader()
    h.run_cli("nope")
    from tests.test_cli_locks import Holder
    h.seed_library("ja", templates=False)
    h.write_settings()
    with Holder("results", "Generate"):
        assert h.run_cli("list")[0] == 3
    assert reader.newest_to_show() is None


def test_a_cut_back_events_file_is_read_again_keeping_only_newer_events(tmp_path):
    path = tmp_path / "cli-events.jsonl"
    path.write_text('{"time":"2026-10-05T10:00:00","pid":1,"verb":"generate","exit":1,"code":"failed","message":"a"}\n',
                    encoding="utf-8")
    reader = cli_events.Reader(from_start=True, events_path=str(path))
    assert [e["message"] for e in reader.new()] == ["a"]
    path.write_text('{"time":"2026-10-05T10:00:00","pid":1,"verb":"generate","exit":1,"code":"failed","message":"a"}\n'
                    '{"time":"2026-10-05T10:00:05","pid":2,"verb":"generate","exit":1,"code":"failed","message":"b"}\n'
                    '{"time":"2026-10-05T10:00:06","pid":3,"verb":"junb', encoding="utf-8")   # the newest half-written
    assert [e["message"] for e in reader.new()] == ["b"]
    path.write_text('{"time":"2026-10-05T10:00:06","pid":3,"verb":"junban","exit":4,"code":"needs-you","message":"c"}\n',
                    encoding="utf-8")                       # cut back (shorter): read again, only newer
    assert [e["message"] for e in reader.new()] == ["c"]


def test_the_dashboards_bottom_bar_shows_the_failure_without_a_box(start_dashboard, monkeypatch):
    h.seed_library("ja", templates=False)
    h.write_settings()
    app = start_dashboard()
    boxes = []
    for name in ("showerror", "showwarning", "showinfo", "askyesno", "askokcancel"):
        monkeypatch.setattr(f"tkinter.messagebox.{name}", lambda *a, **k: boxes.append(a))
    _fail_a_call()
    started = time.perf_counter()
    app._check_cli_events()                                 # the timer's step on the window's thread
    assert time.perf_counter() - started <= 0.004, "a stat, then a worker"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and app._cli_events_reading:
        try:
            app.gui_queue.get(timeout=0.1)()
        except Exception:
            pass
    assert app.status_var.get().startswith("Command line (status): Surasura's settings (settings.json) can't be read")
    assert boxes == []
    assert app.root.winfo_exists(), "the window is still up"


def test_the_windows_settings_save_queues_while_another_program_holds_the_lock(start_dashboard, monkeypatch):
    """In use (no test shortcut): a toggle's save returns at once while the lock is held elsewhere; the setting lands
    once it is free — never dropped — and the journey check follows the write."""
    from tests.test_cli_locks import Holder
    h.seed_library("ja", templates=False)
    h.write_settings()
    app = start_dashboard()
    app._settings_writer = settings_manager.SettingsWriter(
        delay=0.05, wait=0.1, on_saved=lambda _s: app.gui_queue.put(app._schedule_journey_state))
    with Holder("settings", "saving settings") as other:
        monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)
        app.var_only_i_plus_one.set(True)                  # its trace saves
        started = time.perf_counter()
        app.save_settings(skip_ui=True)
        assert time.perf_counter() - started <= 0.004
        monkeypatch.setenv("SURASURA_NO_UI_TIMERS", "1")
        time.sleep(0.4)
        assert settings_manager.load_settings().get("only_i_plus_one") is not True, "held: not written yet"
        other.release()
    assert app._settings_writer.flush(timeout=10)
    assert settings_manager.load_settings()["only_i_plus_one"] is True
