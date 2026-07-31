
import os
import sys
import pytest
from unittest.mock import patch

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture
def test_resources_dir():
    """Returns the path to the 'tests/Test Resources' directory."""
    return os.path.join(os.path.dirname(__file__), "Test Resources")

@pytest.fixture
def ja_resources_dir(test_resources_dir):
    return os.path.join(test_resources_dir, "ja")

@pytest.fixture
def zh_resources_dir(test_resources_dir):
    return os.path.join(test_resources_dir, "zh")

@pytest.fixture(scope="session", autouse=True)
def mock_messagebox():
    """Globally mock tkinter.messagebox for all tests to prevent blocking dialogs."""
    with patch("tkinter.messagebox.showinfo"), \
         patch("tkinter.messagebox.showwarning"), \
         patch("tkinter.messagebox.showerror"), \
         patch("tkinter.messagebox.askyesno", return_value=True), \
         patch("tkinter.messagebox.askokcancel", return_value=True):
        yield


@pytest.fixture(scope="session", autouse=True)
def no_browser_launch():
    """Never open a real browser during a test run.

    generate_static_html() ends by opening the report — correct in the app, but several tests call it
    just to inspect the generated HTML, so a full run used to spawn a browser tab per test. Same
    rationale as mock_messagebox above: suppress the side effect, not the behaviour under test.
    Tests that assert on OPENING patch static_html_generator.open_report, which is untouched here.
    """
    with patch("webbrowser.open"), \
         patch("app.static_html_generator.open_as_app"):
        yield

@pytest.fixture
def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _no_gui_autoindex(monkeypatch):
    """Stop the dashboard from spawning a real background-indexer subprocess during tests.

    Constructing MasterDashboardApp runs update_ui_for_language(), which calls
    _maybe_launch_indexer(); that guard-checks this env var and no-ops. The indexer's own logic
    is covered directly by test_indexer.py (it calls indexer.main()), not via the GUI auto-launch."""
    monkeypatch.setenv("SURASURA_NO_AUTOINDEX", "1")


@pytest.fixture(autouse=True)
def _isolate_token_store(tmp_path_factory, monkeypatch):
    """Point the SQLite token store at a fresh temp dir per test, so analyzer runs never write to
    the real %APPDATA% store (and tests never couple through a shared DB)."""
    d = tmp_path_factory.mktemp("token_store")
    monkeypatch.setattr(
        "app.token_index.store_path_for",
        lambda language: str(d / f"token_store_{language}.db"),
        raising=False,
    )


@pytest.fixture(autouse=True)
def _isolate_analyzer_module_state():
    """Keep the analyzer's module-level state from leaking between tests.

    Many analyzer tests reassign module attributes (get_data_path, RESULTS_DIR, OUTPUT_CSV, ...)
    and analyzer.main() mutates config globals (LOGIC via --context-min/max, SANITIZE_JA,
    SKIP_SINGLE_CHARS, MIN_FREQ, ONLY_I_PLUS_ONE) without restoring them. Snapshot and restore
    all of that around every test so the suite is order-independent.
    """
    import copy
    try:
        from app import analyzer
    except Exception:
        yield
        return

    attrs = [
        "get_data_path", "get_user_files_path", "get_user_file",
        "RESULTS_DIR", "OUTPUT_CSV", "OUTPUT_STATS", "OUTPUT_PROGRESSIVE",
        "SANITIZE_JA", "SKIP_SINGLE_CHARS", "MIN_FREQ", "ONLY_I_PLUS_ONE",
    ]
    saved = {a: getattr(analyzer, a) for a in attrs if hasattr(analyzer, a)}
    saved_logic = copy.deepcopy(analyzer.LOGIC) if hasattr(analyzer, "LOGIC") else None
    try:
        yield
    finally:
        for a, v in saved.items():
            setattr(analyzer, a, v)
        if saved_logic is not None:
            analyzer.LOGIC.clear()
            analyzer.LOGIC.update(saved_logic)
