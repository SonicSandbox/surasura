import zipfile
import sqlite3
import tempfile
import os
import json
import re
import html
import shutil
try:
    import zstandard
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False


def load_anki_data(apkg_path):
    """
    Extracts collection.anki2 from .apkg and discovers all unique fields across models.
    Returns (sorted_fields, notes, model_field_map, temp_dir)
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "collection.anki2")
    
    try:
        with zipfile.ZipFile(apkg_path, 'r') as z:
            filenames = z.namelist()
            # Priority: 21b (Zstd), 21 (v2), 2 (Legacy)
            if "collection.anki21b" in filenames:
                db_file = "collection.anki21b"
            elif "collection.anki21" in filenames:
                db_file = "collection.anki21"
            elif "collection.anki2" in filenames:
                db_file = "collection.anki2"
            else:
                raise FileNotFoundError("Could not find collection.anki2, anki21, or anki21b in .apkg")
                
            z.extract(db_file, temp_dir)
            extracted_path = os.path.join(temp_dir, db_file)
            
            if db_file == "collection.anki21b":
                if not HAS_ZSTD:
                    raise ImportError("zstandard library is required to open newer Anki decks (.anki21b). Please run 'pip install zstandard'.")
                
                # Decompress Zstd
                with open(extracted_path, 'rb') as f_in:
                    dctx = zstandard.ZstdDecompressor()
                    with open(db_path, 'wb') as f_out:
                        dctx.copy_stream(f_in, f_out)
                
                # Close files explicitly before removal
                try:
                    os.remove(extracted_path)
                except Exception as e:
                    print(f"Warning: Could not remove {extracted_path}: {e}")
            elif db_file != "collection.anki2":
                os.rename(extracted_path, db_path)
        
        # Now that ZIP is closed, connect to the DB
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            
            # 1. Map all available fields across all models
            model_field_map = {}
            
            # Check for newer schema (v18+) where notetypes are in a separate table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notetypes'")
            has_notetypes_table = cursor.fetchone() is not None
            
            if has_notetypes_table:
                # Get all notetype IDs
                cursor.execute("SELECT id FROM notetypes")
                ntids = [r[0] for r in cursor.fetchall()]
                for ntid in ntids:
                    model_field_map[ntid] = []
                
                # Get field names from 'fields' table
                # ord is the 0-indexed position within the note field string
                cursor.execute("SELECT ntid, name, ord FROM fields ORDER BY ntid, ord")
                for ntid, f_name, ord in cursor.fetchall():
                    if ntid not in model_field_map:
                        model_field_map[ntid] = []
                    # Ensure we place the field at the correct ordinal position
                    while len(model_field_map[ntid]) <= ord:
                        model_field_map[ntid].append("")
                    model_field_map[ntid][ord] = f_name


                
            # If we didn't get models from tables, try the legacy 'col' column
            if not model_field_map:
                cursor.execute('SELECT models FROM col')
                row = cursor.fetchone()
                if row and row[0]:
                    models = json.loads(row[0])
                    if isinstance(models, dict):
                        for mid, m in models.items():
                            fields = [f['name'] for f in m['flds']]
                            model_field_map[int(mid)] = fields
                    elif isinstance(models, list):
                        for m in models:
                            mid = m['id']
                            fields = [f['name'] for f in m['flds']]
                            model_field_map[int(mid)] = fields
                
            if not model_field_map:
                raise ValueError("Could not find any model/notetype definitions in Anki database.")
                
            # 2. Extract notes
            cursor.execute('SELECT mid, flds FROM notes')
            notes = cursor.fetchall()
            
            # 3. Refine all_fields to ONLY those actually used in notes
            active_mids = set(n[0] for n in notes)
            refined_fields = set()
            for mid in active_mids:
                if mid in model_field_map:
                    refined_fields.update(model_field_map[mid])
            
            return sorted(list(refined_fields)), notes, model_field_map, temp_dir

        finally:
            conn.close()


    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise e

# Field-cleaning patterns (see clean_field_html).
# Line-ending markup becomes a newline BEFORE tags are stripped, or "<div>食べる</div><div>飲む</div>"
# fuses into one word.
_BREAK_RE = re.compile(r'<br\s*/?>|</div\s*>|</p\s*>', re.IGNORECASE)
# Drop furigana ruby readings (<rt>/<rp> contents) BEFORE stripping tags, so the kana
# reading (e.g. かんじ in <ruby>漢字<rt>かんじ</rt></ruby>) doesn't fuse onto the word.
_RUBY_RE = re.compile(r'<rp>.*?</rp>|<rt>.*?</rt>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r'<[^<]+?>')
_SOUND_RE = re.compile(r'\[sound:[^\]]+?\]')
# Anki's bracket furigana: " 漢字[かんじ]" -> "漢字". The reading must follow a kanji/々 directly and
# be kana only, so other bracketed text survives; the single ASCII space {{furigana:}} puts before
# the kanji group goes with it.
_BRACKET_FURIGANA_RE = re.compile(r' ?([㐀-䶿一-鿿豈-﫿々]+)\[[ぁ-ヿー]+\]')


def clean_field_html(raw):
    """
    Turns one raw Anki field value (HTML, ruby, bracket furigana, [sound:] tags, entities)
    into plain text. Lines are kept on separate lines; whitespace runs within a line collapse.
    """
    text = _BREAK_RE.sub('\n', str(raw or ''))
    text = _RUBY_RE.sub('', text)
    text = _TAG_RE.sub('', text)
    text = _SOUND_RE.sub('', text)
    text = _BRACKET_FURIGANA_RE.sub(r'\1', text)
    text = html.unescape(text)
    lines = (' '.join(line.split()) for line in text.split('\n'))
    return '\n'.join(line for line in lines if line)


def extract_field_text(notes, model_field_map, target_field):
    """
    Extracts cleaned text from target_field across all notes.
    """
    extracted_lines = []

    target_field_lower = target_field.lower()
    
    for mid, flds in notes:
        fields = model_field_map.get(mid, [])
        # Search for field case-insensitively
        idx = -1
        for i, f_name in enumerate(fields):
            if f_name.lower() == target_field_lower:
                idx = i
                break
                
        if idx != -1:
            values = flds.split('\x1f')
            if idx < len(values):
                text = clean_field_html(values[idx])
                if text:
                    extracted_lines.append(text)





    
    return "\n".join(extracted_lines)

def cleanup_temp_dir(temp_dir):
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
