
import pytest
import os
import sqlite3
from app.anki_utils import load_anki_data, extract_field_text, cleanup_temp_dir

def test_anki_loader_legacy(ja_resources_dir):
    """Test loading a legacy Anki deck (testAnki.apkg)."""
    apkg_path = os.path.join(ja_resources_dir, "testAnki.apkg")
    if not os.path.exists(apkg_path):
        pytest.skip("testAnki.apkg not found")
        
    temp_dir = None
    try:
        fields, notes, model_map, temp_dir = load_anki_data(apkg_path)
        assert len(notes) > 0
        # Legacy testAnki has "Expression"
        assert "Expression" in fields or "Front" in fields
        
        print(f"Legacy fields: {fields}")
    finally:
        cleanup_temp_dir(temp_dir)

def test_anki_loader_modern_zstd_testAnki2(ja_resources_dir):
    """Test loading testAnki2.apkg (Modern Zstd)."""
    apkg_path = os.path.join(ja_resources_dir, "testAnki2.apkg")
    if not os.path.exists(apkg_path):
        pytest.skip("testAnki2.apkg not found")
        
    temp_dir = None
    try:
        fields, notes, model_map, temp_dir = load_anki_data(apkg_path)
    
        # Verify content matches actual deck (ずんぐりむっくり)
        text = extract_field_text(notes, model_map, "Front")
        assert "ずんぐりむっくり" in text
        assert "Update Anki" not in text
        
        # Verify field filtering (case-insensitive in map)
        assert "front" in fields or "Front" in fields
        
        print(f"testAnki2 fields: {fields}")
    finally:
        cleanup_temp_dir(temp_dir)

def test_anki_loader_modern_zstd_ankiTest3(ja_resources_dir):
    """Test loading ankiTest3.apkg (Modern Zstd)."""
    apkg_path = os.path.join(ja_resources_dir, "ankiTest3.apkg")
    if not os.path.exists(apkg_path):
        pytest.skip("ankiTest3.apkg not found")
        
    temp_dir = None
    try:
        fields, notes, model_map, temp_dir = load_anki_data(apkg_path)
    
        # Verify content matches actual deck (よこ糸)
        text = extract_field_text(notes, model_map, "Front")
        assert "よこ糸" in text
        assert "所信" in text
        assert "Update Anki" not in text
        
        # Verify field filtering
        assert "front" in fields
        assert "Reading" in fields
        
        print(f"ankiTest3 fields: {fields}")
    finally:
        cleanup_temp_dir(temp_dir)

def test_empty_deck_handling(tmp_path):
    """Test handling of a deck with no notes."""
    pass
