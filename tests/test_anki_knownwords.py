import pytest
import os
import json
import shutil
from app.anki_utils import load_anki_data, extract_field_text, cleanup_temp_dir
from app.analyzer import JapaneseTokenizer, ChineseTokenizer
from app.path_utils import get_user_files_path, ensure_data_setup

def test_anki_to_knownwords_ja(ja_resources_dir, tmp_path):
    """
    Test extraction of known words from a Japanese Anki deck.
    """
    apkg_path = os.path.join(ja_resources_dir, "testAnki.apkg")
    if not os.path.exists(apkg_path):
        pytest.skip("testAnki.apkg not found")

    # 1. Load and Extract
    all_fields, notes, model_field_map, temp_dir = load_anki_data(apkg_path)
    try:
        # Use 'Expression' or first field
        field = "Expression" if "Expression" in all_fields else all_fields[0]
        text = extract_field_text(notes[:10], model_field_map, field) # Small sample for speed
        
        assert len(text) > 0
        
        # 2. Tokenize
        tokenizer = JapaneseTokenizer()
        tokens = tokenizer.tokenize(text)
        assert len(tokens) > 0
        
        # 3. Verify unique lemmas
        lemmas = set(t[0] for t in tokens if t[0].strip())
        assert len(lemmas) > 0
        
        # Verify specific words if we know what's in the deck
        # For testAnki.apkg, it usually contains some basic JA words.
        
    finally:
        cleanup_temp_dir(temp_dir)

def test_anki_knownword_json_update(ja_resources_dir, tmp_path, monkeypatch):
    """
    Mock the KnownWord.json update logic.
    """
    # Create a dummy KnownWord.json
    language = "ja"
    
    # We need to mock get_user_files_path to use a temp directory
    mock_user_files = tmp_path / "User Files" / language
    mock_user_files.mkdir(parents=True)
    
    monkeypatch.setattr("app.anki_db_importer_gui.get_user_files_path", lambda lang: str(mock_user_files))
    
    from app.anki_db_importer_gui import AnkiImporterApp
    import tkinter as tk
    
    root = tk.Tk()
    app = AnkiImporterApp(root, language=language)
    
    # Simulate finding words
    test_words = {("食べる", "たべる"), ("飲む", "のむ")}
    app.update_known_words(test_words)
    
    output_file = mock_user_files / "KnownWord.json"
    assert output_file.exists()
    
    with open(output_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        words = data['words']
        lemmas = [w['dictForm'] for w in words]
        assert "食べる" in lemmas
        assert "飲む" in lemmas
        assert all(w['knownStatus'] == "KNOWN" for w in words)
        assert data['statistics']['knownWords'] == 2

    root.destroy()
