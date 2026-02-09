# Anki APKG Technical Implementation Overview

This document provides a deep dive into the code logic for the Anki APKG import feature.

## 1. APKG Extraction Logic
Since `.apkg` files are essentially zip archives, we use Python's `zipfile` and `sqlite3` libraries.

```python
import zipfile
import sqlite3
import tempfile
import os
import json

def load_anki_data(apkg_path):
    # Create a temporary directory for extraction
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "collection.anki2")
    
    with zipfile.ZipFile(apkg_path, 'r') as z:
        z.extract("collection.anki2", temp_dir)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Map all available fields across all models
    cursor.execute('SELECT models FROM col')
    models = json.loads(cursor.fetchone()[0])
    
    all_fields = set()
    model_field_map = {}
    for mid, m in models.items():
        fields = [f['name'] for f in m['flds']]
        model_field_map[int(mid)] = fields
        all_fields.update(fields)
        
    # 2. Extract notes
    cursor.execute('SELECT mid, flds FROM notes')
    notes = cursor.fetchall()
    
    return sorted(list(all_fields)), notes, model_field_map
```

## 2. Model-Agnostic Extraction
To handle decks with multiple card types, we dynamically find the index of the user-selected field for each note.

```python
def extract_field_text(notes, model_field_map, target_field):
    extracted_lines = []
    for mid, flds in notes:
        fields = model_field_map.get(mid, [])
        if target_field in fields:
            idx = fields.index(target_field)
            values = flds.split('\x1f') # Anki fields are \x1f separated
            if idx < len(values):
                raw_text = values[idx]
                # CLEANING: Remove HTML and Anki tags
                clean_text = re.sub(r'<[^<ctrl42>]+?>', '', raw_text)
                clean_text = re.sub(r'\[sound:[^\]]+?\]', '', clean_text)
                extracted_lines.append(clean_text.strip())
    return "\n".join(extracted_lines)
```

## 3. Dynamic UI Structure
The UI will use conditional `tk.Frame`s that are packed/unpacked based on the file extension.

```python
def on_file_selected(self, *args):
    path = self.file_path_var.get()
    if path.lower().endswith('.apkg'):
        self.standard_options_frame.pack_forget()
        self.anki_options_frame.pack(fill='x', pady=10)
        # Load fields into combobox
        fields, self.anki_notes, self.anki_model_map = load_anki_data(path)
        self.field_dropdown['values'] = fields
    else:
        self.anki_options_frame.pack_forget()
        self.standard_options_frame.pack(fill='x', pady=10)
```

## 4. Safety Constraints
- **Validation**: The `process_import` method will verify `self.understand_var.get() == True` if an Anki file is selected.
- **Button State**: A `trace` on the checkbox variable will call `self.update_button_state()`.

```python
def update_button_state(self, *args):
    if self.file_path_var.get().lower().endswith('.apkg'):
        if self.understand_var.get():
            self.import_btn.config(state='normal')
        else:
            self.import_btn.config(state='disabled')
    else:
        self.import_btn.config(state='normal') # Standard files don't need checkbox
```
