# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pytest setup for 鵜飼 Ukai's module tests (`pytest modules/ukai/tests`): the project root on sys.path,
the harness guards every suite shares, a library store on a temp SURASURA_TEST_ROOT."""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from tests.quiet_windows import quiet_windows  # noqa: E402  (the project root is on sys.path just above)
from tests.tk_on_github import skip_tk_tests  # noqa: E402
from tests.network_guard import around_a_test  # noqa: E402
# The guards every suite shares, as the core suite's (tests/harness_guards.py): the real data roots, the gap between
# tests, Tk interpreters freed on the main thread, no child process left running, no real Anki reached.
from tests.harness_guards import (_guard_real_local_data, _guard_anki_port,  # noqa: E402,F401
                                  pytest_collection, pytest_runtest_protocol, pytest_runtest_teardown,
                                  pytest_runtestloop, pytest_sessionfinish, pytest_configure)
# The library store's copy trigger after Connect's writes (L3.3) starts a detached helper: never from a test,
# nor from a command line a test starts (it inherits the switch)
os.environ.setdefault("SURASURA_NO_IDLE_EXPORT", "1")

quiet_windows()                             # test windows open on a desktop of their own: never seen, never typed into


def pytest_collection_modifyitems(items):
    skip_tk_tests(items)                    # GitHub's runner only: the Tk window tests run in the local --all


@pytest.fixture(autouse=True)
def network_guard():
    """Every test stays on this machine (W2.1 G-3; tests/network_guard.py, as tests/conftest.py installs it): a
    connection or a name lookup past loopback is refused as the app meets it offline, and the test fails at its end
    naming the address. The door's loopback is allowed."""
    yield from around_a_test()


@pytest.fixture(autouse=True)
def _isolate_library_store(tmp_path, monkeypatch):
    """The library store (2.5) keys its database by SURASURA_TEST_ROOT, which this suite's tests never set
    (Library_Store_Spec K5). Without one, a store opened under pytest refuses.
    The variable also moves the bundled resources (get_base_path), so the report templates come along, as in the
    core suite's conftest."""
    import shutil
    root = tmp_path / "test_root"
    root.mkdir()
    src = os.path.join(_ROOT, "templates")
    if os.path.isdir(src):
        shutil.copytree(src, str(root / "templates"))
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))
