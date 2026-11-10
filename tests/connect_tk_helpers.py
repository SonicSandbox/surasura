"""Shared by P3.1's window suites (the Connect switch, its settings, the Anki Miner card, the line and badge, the
Connect window, the kick after a move): a hidden Tk root, the app's tooltip and the dashboard's queue stood in for,
and the widgets found however deep they sit."""
import json
import os
import threading
import time
import tkinter as tk

import pytest


class Tips(list):
    """Stands in for the app's ToolTip: records every (widget, text) call."""

    def __call__(self, widget, text):
        self.append((widget, text))

    def has(self, widget):
        return any(w is widget for w, _t in self)


class Pump:
    """Stands in for the dashboard's queue (`gui_queue.put`): a worker puts a job, the test runs it on the main (Tk)
    thread — a worker never touches Tk itself."""

    def __init__(self):
        self.jobs, self._lock = [], threading.Lock()

    def put(self, job):
        with self._lock:
            self.jobs.append(job)

    def run(self, root, until=lambda: False, timeout=5.0):
        """Runs what the workers put until `until()` holds -> whether it did."""
        deadline = time.monotonic() + timeout
        while True:
            root.update()
            with self._lock:
                jobs, self.jobs = self.jobs, []
            for job in jobs:
                job()
            if until():
                return True
            if time.monotonic() > deadline:
                return False
            time.sleep(0.01)


def on_main():
    return threading.current_thread() is threading.main_thread()


def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    root.withdraw()
    return root


def widgets(widget, kinds):
    """Every widget of `kinds` under `widget`, however deep."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, kinds):
            found.append(child)
        found.extend(widgets(child, kinds))
    return found


def settings_path():
    return os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")


def read_settings():
    with open(settings_path(), encoding="utf-8") as f:
        return json.load(f)


def settings_bytes():
    with open(settings_path(), "rb") as f:
        return f.read()
