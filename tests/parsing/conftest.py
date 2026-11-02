"""Fixtures for the parsing-robustness suite (docs/agent instructions/Parsing_Suite.md).

Determinism lives in harness.pinned(), applied to every case by harness.evaluate — in this guard and in the
scorecard alike: SANITIZE_JA and SKIP_SINGLE_CHARS as a run of the case's language sets them, LOGIC from the frozen
settings (tests/parsing/data/<SETTINGS_SNAPSHOT>/settings.json, never the live file) and jieba's reinforce tuning,
each put back after the case. On top, tests/conftest.py restores the analyzer's globals after every test.

Here: one run context per session — one fugashi tagger, one jieba initialisation, each snapshot read once — and
the core conftest's sandbox shared across the session instead of rebuilt per test.
"""
import os
import shutil

import pytest

from tests.parsing import harness


@pytest.fixture(scope="session")
def _parsing_sandbox(tmp_path_factory):
    """One sandboxed data root and token-store folder for the whole suite. The core conftest builds a fresh one
    per test — a copy of templates/ and samples/ each time, ~12 ms — which for a thousand cases would cost more
    than the cases themselves. The suite only reads (snapshots are copies, scratch files live in its own temp
    folder), so one shared sandbox isolates it from the real library just as well."""
    root = tmp_path_factory.mktemp("parsing_user_root")
    for resource in ("templates", "samples"):
        source = os.path.join(harness.ROOT, resource)
        if os.path.isdir(source):
            shutil.copytree(source, str(root / resource))
    return str(root), str(tmp_path_factory.mktemp("parsing_token_store"))


@pytest.fixture(autouse=True)
def _isolate_user_data_root(_parsing_sandbox, monkeypatch):
    """Overrides tests/conftest.py's fixture of the same name, for this folder only: the same sandbox, made once."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", _parsing_sandbox[0])


@pytest.fixture(autouse=True)
def _isolate_token_store(_parsing_sandbox, monkeypatch):
    """Overrides tests/conftest.py's fixture of the same name, for this folder only: never the real %APPDATA%
    store, in one temp folder for the session."""
    folder = _parsing_sandbox[1]
    monkeypatch.setattr("app.token_index.store_path_for",
                        lambda language: os.path.join(folder, f"token_store_{language}.db"), raising=False)


@pytest.fixture(scope="session")
def parsing_ctx(tmp_path_factory):
    """The run context every case of the session shares (harness.Context)."""
    harness.load_evaluators()
    return harness.Context(str(tmp_path_factory.mktemp("parsing_files")))
