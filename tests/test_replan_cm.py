"""The fast re-plan's preview in the Content Manager (E1.1 04 §2; RUNBOOK E3.1.2, E3.1.5): a real window on a real
generated library (tests/test_replan_preview.py's), its store, and the Junban suite's fake AnkiConnect.

  - off (the default): no host, no line, Esc closes at once — 2.5's window;
  - on: a move (the window's own store command, `_store_did`) → after the settle one job on the host's worker → the
    line at the bottom right says what Anki got; the window's thread is never held (a timer probe while the job
    runs: ≤ 4 ms in the timed run, `SURASURA_STORE_BENCH=1`, loosely otherwise);
  - closing while a job runs says *finishing…* and closes once it's done;
  - Junban removed: the switch in settings.json is read as off, and the window moves as 2.5's.
"""
import os
import time

import pytest
import tkinter as tk

pytest.importorskip("modules.junban")

from app import content_importer_gui as cig  # noqa: E402
from app import replan_preview  # noqa: E402
from app.content_importer_gui import ContentImporterApp  # noqa: E402
from tests.test_replan_preview import (_deck, _move_later_to_top, _patched, _settings_file, lib)  # noqa: E402,F401

BENCH = bool(os.environ.get("SURASURA_STORE_BENCH"))


@pytest.fixture
def window():
    made = []

    def make():
        cig._DIALOGS[0] = 0
        root = tk.Tk()
        app = ContentImporterApp(root, "ja")
        made.append((root, app))
        return app
    yield make
    for root, app in made:
        host = app.__dict__.get("_replan")
        if host is not None:
            host.stop()
        try:
            root.destroy()
        except Exception:
            pass


def _pump(app, until, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.root.update()
        if until():
            return True
        time.sleep(0.005)
    return False


def _move_in_window(app, store):
    """A move as the window makes one: the store command, then the window's own hook."""
    item = store.ids("goal")[-1]
    change = app._store().move([item], "now", before_id=app._store().ids("now")[0])
    app._store_did(change, "Move")
    return item


def test_off_the_window_is_2_5s(lib, window):
    root_dir, store = lib
    _settings_file(root_dir, junban_replan_preview=False)
    app = window()
    app._start_replan()
    assert app.__dict__.get("_replan") is None
    _move_in_window(app, store)                  # the hook is a no-op
    assert app.replan_var.get() == ""
    app._close_window()                          # Esc / X: at once
    with pytest.raises(tk.TclError):
        app.root.winfo_exists()


def test_a_move_in_the_window_reorders_anki_and_says_so_without_holding_the_window(lib, window, monkeypatch):
    root_dir, store = lib
    monkeypatch.setattr(replan_preview, "SETTLE_S", 0.05)
    fake = _deck(root_dir)
    app = window()
    with _patched(fake):
        app._start_replan()
        host = app._replan
        assert host is not None
        assert _pump(app, lambda: not host.busy(), 60), "the open's warm-up and catch-up never finished"
        fake.write_requests.clear()
        gaps, last = [], [time.perf_counter()]

        def tick():
            now = time.perf_counter()
            gaps.append(now - last[0])
            last[0] = now
            app.root.after(1, tick)
        app.root.after(1, tick)
        _move_in_window(app, store)
        assert _pump(app, lambda: fake.write_requests and not host.busy(), 60), "no re-order after the move"
        app._drain_replan(once=True)
    line = app.replan_var.get()
    assert line.startswith("Anki: "), line
    worst = max(gaps[1:]) * 1000 if len(gaps) > 1 else 0
    # The window's thread does one queue look per 100 ms; the job runs on the host's worker. A timer probe while it
    # runs: 4 ms in the timed run (the machine alone), loosely in a busy suite.
    assert worst <= (4.0 + 1.0 if BENCH else 250.0), f"the window's thread was held {worst:.1f} ms"
    assert store.versions()["planned_order_version"] == store.versions()["order_version"]


def test_closing_while_a_job_runs_says_finishing_and_waits_for_it(lib, window, monkeypatch):
    root_dir, store = lib
    monkeypatch.setattr(replan_preview, "SETTLE_S", 30.0)      # pending when the window closes
    fake = _deck(root_dir)
    app = window()
    with _patched(fake):
        app._start_replan()
        host = app._replan
        assert _pump(app, lambda: not host.busy(), 60)
        fake.write_requests.clear()
        _move_in_window(app, store)
        assert host.busy()                       # the settle is pending
        app._close_window()
        assert app.replan_var.get() == "Anki: finishing…"
        deadline = time.monotonic() + 60
        closed = False
        while time.monotonic() < deadline and not closed:
            try:
                app.root.update()
                app.root.winfo_exists()          # update() on a destroyed root is quiet; this isn't
                time.sleep(0.005)
            except tk.TclError:
                closed = True                    # destroyed: the window went once the job was done
    assert closed, "the window never closed"
    assert fake.write_requests, "the pending settle didn't run at the close"
    assert store.versions()["planned_order_version"] == store.versions()["order_version"]


def test_junban_removed_reads_the_switch_as_off(lib, window, monkeypatch):
    root_dir, store = lib
    monkeypatch.setattr(replan_preview, "junban_present", lambda: False)
    app = window()
    app._start_replan()
    assert app.__dict__.get("_replan") is None
    _move_in_window(app, store)
    assert app.replan_var.get() == ""
