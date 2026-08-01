"""Every global analyzer.main() assigns must be restored between tests.

This exists because forgetting one is silent and expensive. `ENSURE_AUDIO_EXAMPLE` was added
without being registered, so the first test that switched it on left it on for the whole session:
every later analyzer test then built an extra candidate pool for every word. Nothing failed at the
point of the mistake — instead an unrelated test broke much later and the run grew steadily
heavier, which is a miserable thing to track down.

Reading the `global` statements out of the source is deliberate: a list maintained by hand is
exactly what already went wrong.
"""

import ast
import inspect

from app import analyzer

from tests.conftest import ANALYZER_MUTABLE_GLOBALS


def _globals_assigned_by_main():
    """Names declared `global` inside analyzer.main() — i.e. module state a run mutates."""
    tree = ast.parse(inspect.getsource(analyzer.main))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            names.update(node.names)
    return names


def test_every_global_main_mutates_is_restored_between_tests():
    declared = _globals_assigned_by_main()
    assert declared, "couldn't read any `global` statements out of analyzer.main()"

    missing = declared - set(ANALYZER_MUTABLE_GLOBALS)
    assert not missing, (
        "analyzer.main() mutates module state that conftest doesn't restore: "
        f"{sorted(missing)}.\n"
        "Add it to ANALYZER_MUTABLE_GLOBALS in tests/conftest.py — otherwise it leaks into every "
        "later test in the session."
    )


def test_registered_globals_all_exist():
    """A stale name in the list would silently protect nothing."""
    for name in ANALYZER_MUTABLE_GLOBALS:
        assert hasattr(analyzer, name), f"{name} is registered for isolation but no longer exists"


def test_audio_example_defaults_off_at_module_level():
    """The default must be off, so a fresh process never builds the extra pool unasked."""
    assert analyzer.ENSURE_AUDIO_EXAMPLE is False
