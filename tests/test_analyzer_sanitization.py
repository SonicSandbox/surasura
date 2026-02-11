import app.analyzer as analyzer
from app.analyzer import _sanitize_term, load_yomitan_frequency_list, load_simple_list
import os
import tempfile
import pytest

@pytest.fixture(autouse=True)
def reset_sanitize_ja():
    """Ensure SANITIZE_JA is reset after each test."""
    original = analyzer.SANITIZE_JA
    yield
    analyzer.SANITIZE_JA = original

def test_sanitize_term_analyzer():
    # Helper should always work when called directly
    assert _sanitize_term("アイリス-iris") == "アイリス"
    assert _sanitize_term("apple-fruit") == "apple"
    assert _sanitize_term(" 精霊 ") == "精霊"

def test_load_simple_list_toggle():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as tmp:
        tmp.write("アイリス-iris\n")
        tmp.write("精霊-spirit\n")
        tmp_path = tmp.name
    
    try:
        # Case 1: SANITIZE_JA = False
        analyzer.SANITIZE_JA = False
        results = load_simple_list(tmp_path)
        assert "アイリス-iris" in results
        assert "アイリス" not in results
        
        # Case 2: SANITIZE_JA = True
        analyzer.SANITIZE_JA = True
        results = load_simple_list(tmp_path)
        assert "アイリス" in results
        assert "アイリス-iris" not in results
    finally:
        os.remove(tmp_path)

def test_load_yomitan_frequency_list_always_sanitizes():
    # Frequency lists should always sanitize regardless of toggle (Fix 1)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as tmp:
        tmp.write("Word,Rank\n")
        tmp.write("アイリス-iris,1\n")
        tmp_path = tmp.name
    
    try:
        analyzer.SANITIZE_JA = False
        freq_data = load_yomitan_frequency_list(tmp_path)
        assert "アイリス" in freq_data
        
        analyzer.SANITIZE_JA = True
        freq_data = load_yomitan_frequency_list(tmp_path)
        assert "アイリス" in freq_data
    finally:
        os.remove(tmp_path)

if __name__ == "__main__":
    test_sanitize_term_analyzer()
    test_load_simple_list_toggle()
    test_load_yomitan_frequency_list_always_sanitizes()
    print("Sanitization tests for analyzer.py PASSED.")
