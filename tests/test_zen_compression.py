import pytest
import os
import json
import pandas as pd
from unittest.mock import patch

from app.static_html_generator import generate_static_html, compress_list_of_dicts

def test_compress_list_of_dicts():
    """Verify dictionary list compression works."""
    data = [
        {"Word": "apple", "Freq": 10},
        {"Word": "banana", "Freq": 5, "Tier": 1}
    ]
    compressed = compress_list_of_dicts(data)
    
    # Keys must be sorted for determinism
    assert compressed["keys"] == ["Freq", "Tier", "Word"]
    
    # Check rows mapped correctly
    assert compressed["rows"][0] == [10, None, "apple"]
    assert compressed["rows"][1] == [5, 1, "banana"]

def test_zen_mode_static_html_compression(tmp_path):
    """
    Test that generate_static_html correctly limits words for Zen mode
    and outputs the expected compressed format.
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    
    output_html = results_dir / "reading_list_static.html"
    zen_template = tmp_path / "zen_app.html"
    
    with open(zen_template, "w", encoding="utf-8") as f:
        f.write("<html><body><script>let globalData = null;</script></body></html>")
        
    # Create mock CSV data
    df_prog = pd.DataFrame([
        {"Source File": "book1.txt", "Word": "apple", "Occurrences": 10, "Sequence": 1},
        {"Source File": "book1.txt", "Word": "banana", "Occurrences": 5, "Sequence": 2},
        {"Source File": "book1.txt", "Word": "cherry", "Occurrences": 1, "Sequence": 3}
    ])
    
    prog_csv = tmp_path / "progressive_report.csv"
    df_prog.to_csv(prog_csv, index=False)

    # PRIORITY_CSV must be patched too. It is a module constant resolved at IMPORT time, so no
    # environment fixture reaches it — and with os.path.exists forced True below, leaving it alone
    # made the generator read the developer's real priority_learning_list.csv (14 MB, parsed by
    # pandas) and render the whole library just to check Zen truncation.
    prio_csv = tmp_path / "priority_report.csv"
    pd.DataFrame([
        {"Word": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 30, "Occurrences": 3,
         "Count (High)": 3, "Count (Low)": 0, "Count (Goal)": 0, "Sources": "book1.txt",
         "Context 1": "彼は毎日冒険に出かけます。"},
    ]).to_csv(prio_csv, index=False, encoding="utf-8-sig")

    mock_settings = {
        "theme": "zen",
        "logic": {}
    }

    with patch("app.static_html_generator.RESULTS_DIR", str(results_dir)), \
         patch("app.static_html_generator.OUTPUT_FILE", str(output_html)), \
         patch("app.static_html_generator.WEB_APP_FILE", str(zen_template)), \
         patch("app.static_html_generator.PROGRESSIVE_CSV", str(prog_csv)), \
         patch("app.static_html_generator.PRIORITY_CSV", str(prio_csv)), \
         patch("app.static_html_generator.settings_manager.load_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=True): # Pretend progressive CSV exists
         
         # Run generator in Zen mode limit to 2 words
         generate_static_html(theme="zen", zen_limit=2)
         
         assert output_html.exists()
         
         with open(output_html, "r", encoding="utf-8") as f:
             content = f.read()
             
         # Extract the JSON payload from the constructed HTML string
         # Using simple string splitting to isolate the JSON string
         start_str = "let globalData = "
         end_str = ";\n        let globalTheme"
         
         if start_str in content and end_str in content:
             start_idx = content.find(start_str) + len(start_str)
             end_idx = content.find(end_str, start_idx)
             json_str = content[start_idx:end_idx]
             
             data = json.loads(json_str)
             
             # Assert properties of Zen Mode generation
             prog = data.get("progressive", [])
             assert len(prog) == 1
             
             # Validate that Zen mode logic properly truncated and compressed it
             words_data = prog[0]["words"]
             
             # Under new compression it should look like: {"keys": [...], "rows": [...]}
             assert "keys" in words_data
             assert "rows" in words_data
             
             # And length should be exactly 2 rows
             assert len(words_data["rows"]) == 2
         else:
             pytest.fail("Could not find globalData injected string in HTML output.")
