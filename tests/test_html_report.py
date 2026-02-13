
import pytest
import os
import shutil
from unittest.mock import patch, MagicMock
from app.static_html_generator import generate_static_html

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
    with patch("app.static_html_generator.RESULTS_DIR", str(results_dir)), \
         patch("app.static_html_generator.OUTPUT_FILE", str(output_html)), \
         patch("app.static_html_generator.WEB_APP_FILE", str(template_path)), \
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
