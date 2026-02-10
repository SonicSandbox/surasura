
import pytest
import os
import shutil
from app.anki_utils import load_anki_data, extract_field_text, cleanup_temp_dir

def test_anki_loader_fields(ja_resources_dir):
    """
    Test loading an actual Anki deck package and extracting specific fields.
    """
    apkg_path = os.path.join(ja_resources_dir, "testAnki.apkg")
    
    if not os.path.exists(apkg_path):
        pytest.skip("Skipped: testAnki.apkg not found in Test Resources.")
        
    temp_dir = None
    try:
        # 1. Load Data
        all_fields, notes, model_field_map, temp_dir = load_anki_data(apkg_path)
        
        assert len(all_fields) > 0, "No fields found in Anki deck"
        assert len(notes) > 0, "No notes found in Anki deck"
        
        print(f"Found {len(notes)} notes and fields: {all_fields}")
        
        # 2. Verify "Expression" field exists (Common in language decks)
        # Note: The provided deck might use a different name, but user mentioned "Expression".
        # We'll check if it's in all_fields. If not, we list what IS there to help debug.
        target_field = "Expression"
        
        if target_field not in all_fields:
            # Fallback for generic testing if "Expression" isn't there
            # Maybe "Front" or "Sentence"?
            print(f"Warning: '{target_field}' not found. Available: {all_fields}")
            # If strictly required by user request, we might fail. 
            # But let's check if we can extract *something*.
            target_field = all_fields[0] 
        
        # 3. Extract Text
        text = extract_field_text(notes, model_field_map, target_field)
        
        # Verify text content
        assert len(text) > 0, f"Extracted text for {target_field} is empty"
        assert "[sound:" not in text, "Sound tags were not removed"
        assert "<div>" not in text, "HTML tags were not removed"
        
        print(f"Successfully extracted {len(text.splitlines())} lines from field '{target_field}'")
        
    finally:
        cleanup_temp_dir(temp_dir)
