"""Guard: a test that renders a report must not read the developer's real library.

This closes the single most expensive gap this suite has had. `app/static_html_generator.py`
resolves its inputs and outputs into module constants at IMPORT time:

    RESULTS_DIR     = get_user_file("results")
    PRIORITY_CSV    = os.path.join(RESULTS_DIR, "priority_learning_list.csv")
    PROGRESSIVE_CSV = os.path.join(RESULTS_DIR, "progressive_learning_list.csv")
    OUTPUT_FILE     = os.path.join(RESULTS_DIR, "reading_list_static.html")

Because they are bound at import, NO environment fixture can redirect them — not
SURASURA_TEST_ROOT, not conftest's `_isolate_user_data_root`. A test that forgets to patch
PRIORITY_CSV silently parses the real priority_learning_list.csv (14 MB on this machine) with
pandas and renders the entire library.

Nothing failed when that happened; the tests just got slow and coupled themselves to whatever
library the machine held. Five separate files had it — test_html_report, test_html_regression,
test_completed_files_feature, test_sort_filter_feature and test_zen_compression — and together
they were most of the suite's runtime.

So the rule is checked mechanically rather than left to reviewers, in the same spirit as
test_analyzer_globals_are_isolated.py.
"""
import ast
import os

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Patching any of these redirects the generator's inputs; a renderer must claim the input CSV.
REQUIRED_WHEN_RENDERING = "PRIORITY_CSV"
GENERATOR = "generate_static_html"


def _test_files():
    for name in sorted(os.listdir(TESTS_DIR)):
        if name.startswith("test_") and name.endswith(".py"):
            yield name, os.path.join(TESTS_DIR, name)


def _renders_a_report(tree):
    """True if the module actually CALLS the generator (an import alone is not a render)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == GENERATOR:
                return True
            if isinstance(func, ast.Attribute) and func.attr == GENERATOR:
                return True
    return False


def _patched_targets(tree):
    """Every string literal handed to a redirecting call.

    Both spellings are legitimate and both are used in this suite, so the check accepts either:
        patch("app.static_html_generator.PRIORITY_CSV", ...)      -> the name is arg 0
        monkeypatch.setattr(static_html_generator, "PRIORITY_CSV", ...) -> the name is arg 1
    Matching only the first form made test_modality_badge.py a false positive — a guard that
    rejects a correct pattern is worse than no guard, because the fix is to weaken the test."""
    targets = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name not in ("patch", "object", "setattr"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                targets.add(arg.value)
    return targets


def test_every_report_rendering_test_patches_its_input_csv():
    """Rendering without patching PRIORITY_CSV reads the real library. Fail loudly, not slowly."""
    offenders = []
    for name, path in _test_files():
        with open(path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, name)
        if not _renders_a_report(tree):
            continue
        if not any(t.endswith(REQUIRED_WHEN_RENDERING) for t in _patched_targets(tree)):
            offenders.append(name)

    assert not offenders, (
        "These tests call generate_static_html() without patching "
        f"app.static_html_generator.{REQUIRED_WHEN_RENDERING}, so they parse and render the real "
        f"results/priority_learning_list.csv: {offenders}. Point it at a small fixture CSV — see "
        "tests/test_html_regression.py for the pattern."
    )


def test_the_generator_still_resolves_its_inputs_at_import_time():
    """The guard above exists BECAUSE these are import-time constants. If the generator ever
    resolves them lazily instead, this rule stops being necessary and should be revisited rather
    than left in place as cargo."""
    from app import static_html_generator as gen

    for const in ("RESULTS_DIR", "PRIORITY_CSV", "PROGRESSIVE_CSV", "OUTPUT_FILE"):
        assert isinstance(getattr(gen, const), str), (
            f"{const} is no longer a plain import-time string — if the generator now resolves "
            "paths per call, an environment fixture can isolate it and this guard can go.")
