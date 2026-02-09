import zipfile
import sqlite3
import tempfile
import os
import json
import re
import shutil

def load_anki_data(apkg_path):
    """
    Extracts collection.anki2 from .apkg and discovers all unique fields across models.
    Returns (sorted_fields, notes, model_field_map, temp_dir)
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "collection.anki2")
    
    try:
        with zipfile.ZipFile(apkg_path, 'r') as z:
            # Anki 2.1+ might use 'collection.anki21' or just 'collection.anki2'
            filenames = z.namelist()
            db_file = "collection.anki21" if "collection.anki21" in filenames else "collection.anki2"
            if db_file not in filenames:
                # Fallback: look for sqlite header in all files? 
                # Usually it's either anki2 or anki21
                raise FileNotFoundError("Could not find collection.anki2 or collection.anki21 in .apkg")
            z.extract(db_file, temp_dir)
            if db_file != "collection.anki2":
                os.rename(os.path.join(temp_dir, db_file), db_path)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. Map all available fields across all models
        cursor.execute('SELECT models FROM col')
        row = cursor.fetchone()
        if not row:
            raise ValueError("Invalid Anki database: 'col' table missing models.")
            
        models = json.loads(row[0])
        
        all_fields = set()
        model_field_map = {}
        for mid, m in models.items():
            fields = [f['name'] for f in m['flds']]
            model_field_map[int(mid)] = fields
            all_fields.update(fields)
            
        # 2. Extract notes
        cursor.execute('SELECT mid, flds FROM notes')
        notes = cursor.fetchall()
        
        conn.close()
        return sorted(list(all_fields)), notes, model_field_map, temp_dir
    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise e

def extract_field_text(notes, model_field_map, target_field):
    """
    Extracts cleaned text from target_field across all notes.
    """
    extracted_lines = []
    # Simplified regex for HTML cleaning
    tag_re = re.compile(r'<[^<]+?>')
    sound_re = re.compile(r'\[sound:[^\]]+?\]')
    
    for mid, flds in notes:
        fields = model_field_map.get(mid, [])
        if target_field in fields:
            idx = fields.index(target_field)
            values = flds.split('\x1f')
            if idx < len(values):
                raw_text = values[idx]
                # Clean text
                text = tag_re.sub('', raw_text)
                text = sound_re.sub('', text)
                text = text.replace('&nbsp;', ' ').replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
                if text.strip():
                    extracted_lines.append(text.strip())
    
    return "\n".join(extracted_lines)

def cleanup_temp_dir(temp_dir):
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
