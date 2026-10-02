"""Tests for the band-preview (slider) cache key — MasterDashboardApp._preview_signature.

The slider preview reads the token store + known words on a worker thread; on a big library that
stutters the UI. The refresh now skips the worker when nothing that affects the preview changed,
keyed on this stat-only signature. These tests pin that the signature is STABLE when inputs are
unchanged and CHANGES when the known words, an ignore list, or the selection settings change.
"""
import os
import sys
import json

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import MasterDashboardApp


@pytest.fixture
def uf_env(tmp_path, monkeypatch):
    """A temp User Files/ja with the known-words file + lists, exposed via SURASURA_TEST_ROOT."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path))
    uf = tmp_path / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        (uf / name).write_text("", encoding="utf-8")
    return uf


def _app():
    # No Tk: _preview_signature uses only its args + module imports, no instance state.
    return MasterDashboardApp.__new__(MasterDashboardApp)


def test_signature_stable_when_nothing_changes(uf_env):
    app = _app()
    sel = {"band": "occasional", "min_count": 2}
    assert app._preview_signature("ja", sel) == app._preview_signature("ja", sel)
    assert app._preview_signature("ja", sel) is not None


def test_signature_changes_when_known_words_change(uf_env):
    app = _app()
    sel = {"band": "occasional"}
    before = app._preview_signature("ja", sel)
    # Grow the known-words file so its stat-based signature moves.
    (uf_env / "KnownWord.json").write_text(
        json.dumps({"words": [{"dictForm": "学校", "knownStatus": "KNOWN"}]}), encoding="utf-8")
    assert app._preview_signature("ja", sel) != before


def test_signature_changes_when_ignore_list_changes(uf_env):
    app = _app()
    sel = {"band": "occasional"}
    before = app._preview_signature("ja", sel)
    (uf_env / "IgnoreList.txt").write_text("する\n", encoding="utf-8")
    assert app._preview_signature("ja", sel) != before


def test_an_ignore_list_edit_within_one_clock_tick_still_changes_it(uf_env):
    # Windows moves a file's time in steps: two writes close together can share an mtime, so the size tells them apart
    # (here the old time is put back on purpose, so the test never depends on how fast the machine is).
    app = _app()
    sel = {"band": "occasional"}
    path = uf_env / "IgnoreList.txt"
    before = app._preview_signature("ja", sel)
    stamp = os.stat(path).st_mtime
    path.write_text("する\n", encoding="utf-8")
    os.utime(path, (stamp, stamp))
    assert app._preview_signature("ja", sel) != before


def test_signature_changes_when_selection_changes(uf_env):
    app = _app()
    assert app._preview_signature("ja", {"band": "core"}) != app._preview_signature("ja", {"band": "rare"})


def test_signature_changes_when_ignore_names_flips(uf_env):
    """Ignore names makes the library's names ignored words — the slider's numbers change with no file re-read, so the
    cached ones must not stand."""
    app = _app()
    sel = {"band": "occasional"}
    app._current_settings = {"logic": {"ignore_names": False}}
    off = app._preview_signature("ja", sel)
    app._current_settings = {"logic": {"ignore_names": True}}
    assert app._preview_signature("ja", sel) != off
    app._current_settings = {"logic": {}}
    assert app._preview_signature("ja", sel) == off, "a missing key reads as off"


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


def test_a_refresh_waits_for_the_tables_the_window_decodes_and_a_superseded_one_never_counts(uf_env, monkeypatch):
    """As the dashboard opens, what the slider's first refresh reads besides the store is decoded in the background
    while the window is built (token_index.prepare_preview). A refresh's worker waits for that — the window's thread
    never does — and a refresh a newer one replaced before it began counting does not count at all: only the newest
    numbers were ever shown, now without the work of the ones before (two refreshes start as the window opens)."""
    import queue
    import threading
    from unittest.mock import MagicMock

    started = []
    real_thread = threading.Thread

    class Recording(real_thread):
        def start(self):
            started.append(self)
            return super().start()

    monkeypatch.setattr(threading, "Thread", Recording)
    app = _app()
    ready = threading.Event()
    app._preview_prepared = real_thread(target=ready.wait, daemon=True)
    app._preview_prepared.start()
    counted = []

    def compute(lang, sel, script):
        counted.append(sel["band"])
        return {"rare": {"word_count": 3}}

    app._compute_band_previews = compute
    app.var_language, app.var_zh_script = _Var("ja"), _Var("asis")
    app.var_band_coverage, app.gui_queue = MagicMock(), queue.Queue()
    app._current_settings = {"logic": {"selection": {"band": "core"}}}
    app._refresh_band_preview()
    app._current_settings = {"logic": {"selection": {"band": "rare"}}}
    app._refresh_band_preview()
    assert len(started) == 2 and counted == [], "both wait for the window's tables"
    ready.set()
    for worker in started:
        worker.join(10)
    assert counted == ["rare"], "the first was replaced before it began: only the newest counts"
    assert app.gui_queue.qsize() == 1, "one result goes to the window"


def test_with_nothing_to_wait_for_a_refresh_counts_at_once(uf_env):
    """Under test (and before the window's own decode is started) there is nothing to wait for: the worker counts."""
    import queue
    import threading
    from unittest.mock import MagicMock

    app = _app()
    done = threading.Event()
    app._compute_band_previews = lambda lang, sel, script: done.set() or {}
    app.var_language, app.var_zh_script = _Var("ja"), _Var("asis")
    app.var_band_coverage, app.gui_queue = MagicMock(), queue.Queue()
    app._current_settings = {"logic": {}}
    app._refresh_band_preview()
    assert done.wait(10)
