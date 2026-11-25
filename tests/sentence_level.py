"""A test's sentence-choice level (`plan_rules.SENTENCE_TABLE`, 2 in the tree since the flip), for its own process and
the children it starts (a Generate reads SURASURA_SENTENCE_TABLE once, at import).

A test of the path level 0 runs — the plan's format 4 and its pick tables, the shortlists, the first sentences a
file, Connect's list rows — pins itself there until E-RETIRE removes that path and its tests together (SPEC § 10.3):

    pytestmark = pytest.mark.usefixtures("level_0")     # every test of the file (both fixtures are conftest's)
    # a module-scoped fixture that Generates: `module_level_0` first in its arguments

The values worked out from the level at import (the plan's format) are set with it."""
import pytest


def pin(mp, level):
    """`mp` (a pytest MonkeyPatch) sets `level` for this process and its children."""
    from app import analyzer, plan_engine, plan_rules       # (here, not at import: conftest imports this module)
    mp.setattr(plan_rules, "SENTENCE_TABLE", level)
    mp.setattr(plan_engine, "FORMAT", 5 if level >= 2 else 4)
    mp.setattr(plan_engine, "FORMATS", (1, 2, 3, 4, 5) if level >= 2 else (1, 2, 3, 4))
    mp.setattr(analyzer, "PLAN_FORMAT", 5 if level >= 2 else 4)
    mp.setenv("SURASURA_SENTENCE_TABLE", str(level))


@pytest.fixture
def level_0(monkeypatch):
    pin(monkeypatch, 0)


@pytest.fixture(scope="module")
def module_level_0():
    """Level 0 for a whole module, its module-scoped fixtures included (list it first in their arguments)."""
    with pytest.MonkeyPatch.context() as mp:
        pin(mp, 0)
        yield
