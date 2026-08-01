
import pytest
import os
import shutil
import pandas as pd
from unittest.mock import patch, MagicMock
from app.static_html_generator import generate_static_html


def _fixture_csvs(tmp_path):
    """A one-word priority list for the generator to render.

    Without patching PRIORITY_CSV the generator falls through to the developer's real
    results/priority_learning_list.csv — 14 MB parsed by pandas and rendered in full. Two tests here
    did exactly that, which made this the slowest file in the suite (7.8s for 3 tests, 21% of the
    whole run) and quietly coupled them to whatever library the machine happened to hold.

    The progressive path is left non-existent on purpose: the generator guards it with
    os.path.exists, and none of these assertions need the per-file view."""
    priority = tmp_path / "priority_learning_list.csv"
    pd.DataFrame([
        {"Word": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 30, "Occurrences": 3,
         "Count (High)": 3, "Count (Low)": 0, "Count (Goal)": 0, "Sources": "a_novel.txt",
         "Context 1": "彼は毎日冒険に出かけます。"},
    ]).to_csv(priority, index=False, encoding="utf-8-sig")
    return priority, tmp_path / "progressive_learning_list.csv"


def test_html_generation(tmp_path):
    """
    Test that generate_static_html creates an output file and injects data.
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    
    output_html = results_dir / "reading_list_static.html"
    
    # Needs a template file to read
    template_path = tmp_path / "web_app.html"
    with open(template_path, "w", encoding="utf-8") as f:
        f.write("<html><head></head><body><h1>Surasura List</h1><script>let globalData = null;</script></body></html>")
        
    # Mock paths and settings
    mock_settings = {
        "theme": "Default (Dark)",
        "target_language": "ja",
        "words_per_day": 5,
        "show_words_per_day": True,
        "logic": {"test": "data"}
    }
    priority_csv, progressive_csv = _fixture_csvs(tmp_path)
    with patch("app.static_html_generator.RESULTS_DIR", str(results_dir)), \
         patch("app.static_html_generator.OUTPUT_FILE", str(output_html)), \
         patch("app.static_html_generator.WEB_APP_FILE", str(template_path)), \
         patch("app.static_html_generator.PRIORITY_CSV", str(priority_csv)), \
         patch("app.static_html_generator.PROGRESSIVE_CSV", str(progressive_csv)), \
         patch("app.static_html_generator.settings_manager.load_settings", return_value=mock_settings), \
         patch("app.path_utils.get_icon_path", return_value="dummy_icon.png"):

         # Run generator
         generate_static_html(theme="default")
         
         assert output_html.exists()
         
         with open(output_html, "r", encoding="utf-8") as f:
             content = f.read()
             
         # Verify injection
         assert "let globalData = {" in content
         assert "let globalTheme = 'default';" in content
         assert "let globalLogic = {\"test\": \"data\"};" in content
         # Verify logo injection wasn't attempted if icon missing (mocked exists check? no, we didn't mock os.path.exists)
         # That's fine, we just want to ensure it runs without crashing.


def test_report_is_still_opened_after_generation(tmp_path):
    """Opening the report is INTENDED behaviour, not an accident of the tests.

    The suite-wide `no_browser_launch` fixture suppresses the real launch (several tests call
    generate_static_html purely to inspect the HTML, and a run used to spawn a browser tab each
    time). This test asserts the behaviour it suppresses still happens — and picks the right one
    for the window mode — so the fixture can never quietly turn the feature off.
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    output_html = results_dir / "reading_list_static.html"
    template_path = tmp_path / "web_app.html"
    with open(template_path, "w", encoding="utf-8") as f:
        f.write("<html><head></head><body><script>let globalData = null;</script></body></html>")

    priority_csv, progressive_csv = _fixture_csvs(tmp_path)
    common = [
        patch("app.static_html_generator.RESULTS_DIR", str(results_dir)),
        patch("app.static_html_generator.OUTPUT_FILE", str(output_html)),
        patch("app.static_html_generator.WEB_APP_FILE", str(template_path)),
        patch("app.static_html_generator.PRIORITY_CSV", str(priority_csv)),
        patch("app.static_html_generator.PROGRESSIVE_CSV", str(progressive_csv)),
        patch("app.static_html_generator.settings_manager.load_settings", return_value={}),
    ]

    # Default: hand the report to the user's normal browser.
    with common[0], common[1], common[2], common[3], common[4], common[5], \
         patch("webbrowser.open") as mock_browser, \
         patch("app.static_html_generator.open_as_app") as mock_app:
        generate_static_html(theme="default")
        assert mock_browser.called, "the finished report must still be opened"
        assert not mock_app.called
        assert str(output_html) in mock_browser.call_args[0][0]

    # "Open in New Window": route through the app-mode launcher instead.
    with common[0], common[1], common[2], common[3], common[4], common[5], \
         patch("webbrowser.open") as mock_browser, \
         patch("app.static_html_generator.open_as_app") as mock_app:
        generate_static_html(theme="default", app_mode=True)
        assert mock_app.called, "app-mode must use the dedicated window launcher"
        assert not mock_browser.called


def test_injected_data_escapes_script_close(tmp_path):
    """A literal </script> in user content (a context sentence pulled from subtitles/ebooks)
    must be escaped so it cannot close the inline <script> block and blank the whole report
    (finding output-html-01)."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    output_html = results_dir / "reading_list_static.html"
    template_path = tmp_path / "web_app.html"
    with open(template_path, "w", encoding="utf-8") as f:
        f.write("<html><head></head><body><script>let globalData = null;</script></body></html>")

    # Priority CSV whose context tries to break out of the <script> block.
    priority_csv = results_dir / "priority_learning_list.csv"
    breakout = "</script><script>alert(1)</script>"
    pd.DataFrame([{"Word": "テスト", "Context 1": f"これは{breakout}です"}]).to_csv(
        priority_csv, index=False, encoding="utf-8"
    )

    mock_settings = {
        "theme": "Default (Dark)", "target_language": "ja",
        "words_per_day": 5, "show_words_per_day": True, "logic": {},
    }
    with patch("app.static_html_generator.RESULTS_DIR", str(results_dir)), \
         patch("app.static_html_generator.OUTPUT_FILE", str(output_html)), \
         patch("app.static_html_generator.WEB_APP_FILE", str(template_path)), \
         patch("app.static_html_generator.PRIORITY_CSV", str(priority_csv)), \
         patch("app.static_html_generator.PROGRESSIVE_CSV", str(tmp_path / "progressive_learning_list.csv")), \
         patch("app.static_html_generator.settings_manager.load_settings", return_value=mock_settings), \
         patch("app.path_utils.get_icon_path", return_value="dummy_icon.png"):
        generate_static_html(theme="default")

    content = output_html.read_text(encoding="utf-8")
    # The data still carries the text, but its closing tag is neutralised to <\/script>.
    assert "<\\/script>" in content
    # The raw breakout sequence must NOT survive into the document.
    assert breakout not in content
