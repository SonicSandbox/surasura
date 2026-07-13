"""Covers the background-indexer SUBPROCESS entry point (app/indexer.py -> indexer.main()).

The indexer is what keeps the word-selection preview *always fresh* without a full analysis run:
the GUI detects a delta (stat only) and launches this to reconcile the token store + refresh the
tokenizer-normalized known-words cache, then exits. These tests drive main() directly (no real
subprocess) against real Japanese content and a real KnownWord.json, and assert both halves land
in the store — including the known-words edge cases the change is required to catch (edit/delete).
"""

import os
import sys
import json
import pytest
from unittest.mock import patch

from app import indexer, token_index as ti

# '冒険' recurs; '今日' is marked KNOWN. Enough to exercise counts + the known-filter both ways.
JA = "冒険。冒険する。冒険だ。今日は良い天気。今日も冒険。"


@pytest.fixture
def env(tmp_path):
    """Real data/ja/HighPriority content + a KnownWord.json marking '今日' KNOWN.

    (The SQLite token store itself is isolated to a temp dir by the autouse conftest fixture, so
    open_store("ja") here and inside indexer.main() resolve to the same throwaway DB.)"""
    high = tmp_path / "data" / "ja" / "HighPriority"; high.mkdir(parents=True)
    (high / "t.txt").write_text(JA, encoding="utf-8")
    uf = tmp_path / "User Files" / "ja"; uf.mkdir(parents=True)
    known = uf / "KnownWord.json"
    known.write_text(json.dumps({"words": [{"dictForm": "今日", "knownStatus": "KNOWN"}]}),
                     encoding="utf-8")

    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"root": tmp_path, "known": known, "gdp": gdp, "gufp": gufp}


def _run_indexer(env, language="ja"):
    # main() re-imports get_data_path/get_user_files_path at call time, so patching the attrs on
    # app.path_utils takes effect; --language is read from argv exactly as the subprocess would.
    with patch("app.path_utils.get_data_path", side_effect=env["gdp"]), \
         patch("app.path_utils.get_user_files_path", side_effect=env["gufp"]), \
         patch.object(sys, "argv", ["indexer.py", "--language", language]):
        indexer.main()


def _learnable(store, known=None):
    """The learnable-unknown lemmas as the *preview* sees them: unknown_frequencies() is a pure
    projection, so — exactly like the GUI — the caller passes the (tuples, lemmas) the indexer
    cached. Pass known=None for the raw distribution (nothing filtered)."""
    kt, kl = known if known else (set(), set())
    return {ti.split_key(k)[0] for k, _ in store.unknown_frequencies(kt, kl)["unknown"]}


def test_indexer_reconciles_content_into_store(env):
    """main() tokenizes the content delta into the aggregate (no analysis run required)."""
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        assert store.total_tokens() > 0
        assert store.file_count() == 1
        assert "冒険" in _learnable(store)
    finally:
        store.close()


def test_indexer_caches_known_and_filters_it(env):
    """main() populates the tokenizer-normalized known cache; the known word drops out of unknown."""
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        cached = store.get_cached_known(ti.known_signature(str(env["known"])))
        assert cached is not None, "known cache must be populated for the current signature"
        _tuples, lemmas = cached
        assert "今日" in lemmas
        assert "今日" not in _learnable(store, cached), "a known word must not appear as learnable-unknown"
    finally:
        store.close()


def test_indexer_reruns_are_idempotent(env):
    """A warm re-run (nothing changed) reuses cached tokens + cached known -> identical aggregate."""
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        before = (store.total_tokens(), store.file_count(), sorted(_learnable(store)))
    finally:
        store.close()
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        after = (store.total_tokens(), store.file_count(), sorted(_learnable(store)))
    finally:
        store.close()
    assert before == after


def test_indexer_catches_edited_known_file(env):
    """An edit to KnownWord.json (new known word) must invalidate + refresh the cache on next run."""
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        assert "冒険" in _learnable(store)   # not known yet
    finally:
        store.close()
    # Mark '冒険' known too (edit changes the file's mtime/size -> signature differs).
    env["known"].write_text(json.dumps({"words": [
        {"dictForm": "今日", "knownStatus": "KNOWN"},
        {"dictForm": "冒険", "knownStatus": "KNOWN"},
    ]}), encoding="utf-8")
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        cached = store.get_cached_known(ti.known_signature(str(env["known"])))
        assert cached is not None, "the edited-file signature must have a fresh cache"
        assert "冒険" in cached[1]
        assert "冒険" not in _learnable(store, cached), "the newly-known word must be filtered out"
    finally:
        store.close()


def test_indexer_catches_deleted_known_file(env):
    """User's explicit ask: deleting KnownWord.json must be caught. The previously-known word
    resurfaces as learnable-unknown, and the (empty) cache is keyed to the deleted signature."""
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        cached = store.get_cached_known(ti.known_signature(str(env["known"])))
        assert "今日" not in _learnable(store, cached)   # known while the file exists
    finally:
        store.close()

    os.remove(env["known"])          # simulate a deletion outside the app
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        sig = ti.known_signature(str(env["known"]))   # encodes exists=False
        cached = store.get_cached_known(sig)
        assert cached is not None, "the deleted-file signature must have its own fresh (empty) cache"
        assert "今日" not in cached[1]
        assert "今日" in _learnable(store, cached), "an un-known word must resurface as learnable"
    finally:
        store.close()


def test_indexer_drops_removed_content(env):
    """Removing a content file shrinks the aggregate on the next reconcile (delta handles removals)."""
    extra = env["root"] / "data" / "ja" / "HighPriority" / "extra.txt"
    extra.write_text("林檎を食べる。林檎は赤い。", encoding="utf-8")
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        assert store.file_count() == 2
        assert "林檎" in _learnable(store)
    finally:
        store.close()
    os.remove(extra)
    _run_indexer(env)
    store = ti.open_store("ja")
    try:
        assert store.file_count() == 1
        assert "林檎" not in _learnable(store)
    finally:
        store.close()
