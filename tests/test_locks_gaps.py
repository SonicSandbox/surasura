"""S3.1 (app/locks.py): gaps the Haiku mutant list found in the cross-process locks (tests/test_cli_locks.py and
tests/test_path_layout.py hold the rest). Every lock lives under the test root (conftest)."""
import os

from app import locks


def test_only_a_permission_failure_makes_a_lock_unopenable():
    # `unopenable` is a fail-open door: settings_manager saves settings.json WITHOUT its lock when the lock file can't
    # be opened for this program's permissions, rather than lose the setting. Any other failure to open — here the
    # lock's folder not made yet — is no reason to skip the lock: the answer is None, and the caller waits as usual.
    assert not os.path.isdir(locks.folder("settings"))
    assert locks.unopenable("settings") is None
