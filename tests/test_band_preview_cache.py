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


def test_signature_changes_when_selection_changes(uf_env):
    app = _app()
    assert app._preview_signature("ja", {"band": "core"}) != app._preview_signature("ja", {"band": "rare"})
