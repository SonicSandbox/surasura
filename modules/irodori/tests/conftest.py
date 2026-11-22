# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared setup for the Irodori (AI voice) suite: the project root on sys.path, the suites' shared guards, and every path
the module writes moved under the test's own root (`SURASURA_TEST_ROOT`: the runtime's home is <root>/local/irodori).
No network: the downloads, the uv runs and the server are faked; Anki is a patched urlopen; the shared writer
is the real one (`app/connect/sentence_audio.py`)."""
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests.quiet_windows import quiet_windows  # noqa: E402
from tests.tk_on_github import skip_tk_tests  # noqa: E402
from tests.network_guard import around_a_test  # noqa: E402
from tests.harness_guards import (_guard_real_local_data, _guard_anki_port,  # noqa: E402,F401
                                  pytest_collection, pytest_runtest_protocol, pytest_runtest_teardown,
                                  pytest_runtestloop, pytest_sessionfinish, pytest_configure)
os.environ.setdefault("SURASURA_NO_IDLE_EXPORT", "1")
quiet_windows()


def pytest_collection_modifyitems(items):
    skip_tk_tests(items)


@pytest.fixture(autouse=True)
def network_guard():
    yield from around_a_test()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path))
    monkeypatch.delenv("SURASURA_IRODORI_HOME", raising=False)
    yield


@pytest.fixture
def ja_sentences():
    """Real Japanese sentences from the shared test resources — never dummy ASCII."""
    path = os.path.join(_ROOT, "tests", "Test Resources", "ja", "context_test.txt")
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


@pytest.fixture
def installed():
    """A runtime that reads as installed (its files there, empty): what `status()` checks, nothing runnable."""
    from modules.irodori import runtime
    base = runtime.home()
    for path in (runtime.env_python(base), runtime.model_path(base), runtime.codec_path(base)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
    open(os.path.join(base, runtime.MARKER), "w").close()
    with open(os.path.join(base, "installed.json"), "w", encoding="utf-8") as f:
        json.dump({"version": runtime.RUNTIME_VERSION, "backend": "cpu", "size_bytes": 4_900_000_000}, f)
    return base


@pytest.fixture
def shared_writer():
    """The shared writer (`app/connect/sentence_audio.py`) itself — never a stand-in: its Undo records go to a
    Connect ledger under the test's root."""
    from modules.irodori import writer
    shared = writer._shared()
    assert shared is not None, "the shared writer isn't in this tree with the seam's contract"
    return shared
