import os
import json
import csv
import zipfile
import pandas as pd
from datetime import datetime

class FrequencyExporter:
    @staticmethod
    def export_migaku(csv_path, save_path):
        """
        Export as a simple JSON array of words.
        Format: ["word1", "word2", ...]
        This matches the 'EXISTING' logic.
        """
        df = pd.read_csv(csv_path)
        if 'Word' not in df.columns:
            raise ValueError("CSV is missing 'Word' column")
            
        word_list = df['Word'].tolist()
        
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(word_list, f, ensure_ascii=False, indent=2)
            
    @staticmethod
    def export_word_list(csv_path, save_path):
        """
        Export as a palin text list, one word per line.
        """
        df = pd.read_csv(csv_path)
        if 'Word' not in df.columns:
            raise ValueError("CSV is missing 'Word' column")
            
        word_list = df['Word'].tolist()
        
        with open(save_path, 'w', encoding='utf-8') as f:
            for word in word_list:
                f.write(f"{word}\n")

    @staticmethod
    def export_yomitan(csv_path, save_path, language='ja', title="Custom Freq List"):
        """
        Export as a Yomitan-compatible ZIP file.
        Contains:
          - index.json
          - term_meta_bank_1.json
        """
        df = pd.read_csv(csv_path)
        if 'Word' not in df.columns:
            raise ValueError("CSV is missing 'Word' column")
            
        # 1. Create index.json
        index_data = {
            "title": title,
            "format": 3,
            "revision": datetime.now().strftime("%Y%m%d"), # Use date as revision? Or "1"
            "sequenced": True,
            "author": "SonicSandbox",
            "description": f"Generated from Surasura Analysis ({language})"
        }
        
        # 2. Create term_meta_bank_1.json
        term_data = []
        
        # Columns present?
        has_reading = 'Reading' in df.columns
        
        # Iterate with index (1-based rank)
        for idx, row in df.iterrows():
            rank = idx + 1
            term = row['Word']
            
            # Decide on format logic
            # Option B: Japanese Strict (Reading Specific) - Only if language is JA and we have readings
            # Requirement: Reading MUST be Katakana.
            # Analyzer usually provides Katakana in 'Reading' column for JA.
            use_strict = (language == 'ja' and has_reading and pd.notna(row['Reading']) and str(row['Reading']).strip() != "")
            
            if use_strict:
                reading = str(row['Reading'])
                # Yomitan requires Katakana. 
                # If reading is empty or not katakana, it might fail validation if we force it?
                # But let's trust analyzer output for now.
                term_entry = [term, "freq", { "reading": reading, "frequency": rank }]
            else:
                # Option A: Simple
                term_entry = [term, "freq", rank]
                
            term_data.append(term_entry)
            
        # 3. Zip them up
        # We need to write to a zip file.
        with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('index.json', json.dumps(index_data, ensure_ascii=False, indent=2))
            zf.writestr('term_meta_bank_1.json', json.dumps(term_data, ensure_ascii=False))
