import os
import json
import csv
import zipfile
import re
import pandas as pd
from datetime import datetime

class FrequencyExporter:
    @staticmethod
    def _sanitize_term(term):
        """
        Strip all characters starting from the hyphen - or space in the Term field.
        Example: "アイリス-iris" -> "アイリス"
        """
        if not isinstance(term, str):
            return term
        
        # First strip leading/trailing whitespace
        term = term.strip()
        
        # Match anything before the first hyphen or space
        # re.split returns a list, we take the first element
        parts = re.split(r'[-\s]', term)
        return parts[0] if parts else term

    @staticmethod
    def _is_pure_katakana(text):
        """
        Check if the text consists only of Katakana characters.
        """
        if not isinstance(text, str) or not text:
            return False
        # Katakana range: \u30A0-\u30FF + Prolonged sound mark \u30FC
        return all(('\u30A0' <= char <= '\u30FF') or char == '\u30FC' for char in text)

    @staticmethod
    def export_migaku(csv_path, save_path):
        """
        Export as a simple JSON array of words.
        Format: ["word1", "word2", ...]
        """
        df = pd.read_csv(csv_path)
        if df.empty:
            raise ValueError("The source data is empty. Cannot generate frequency list.")
        if 'Word' not in df.columns:
            raise ValueError("CSV is missing 'Word' column")
            
        # Sanitize words
        word_list = [FrequencyExporter._sanitize_term(w) for w in df['Word'].tolist()]
        
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(word_list, f, ensure_ascii=False, indent=2)
            
    @staticmethod
    def export_word_list(csv_path, save_path):
        """
        Export as a plain text list, one word per line.
        """
        df = pd.read_csv(csv_path)
        if df.empty:
            raise ValueError("The source data is empty. Cannot generate frequency list.")
        if 'Word' not in df.columns:
            raise ValueError("CSV is missing 'Word' column")
            
        # Sanitize words
        word_list = [FrequencyExporter._sanitize_term(w) for w in df['Word'].tolist()]
        
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
        if df.empty:
            raise ValueError("The source data is empty. Cannot generate frequency list.")
        if 'Word' not in df.columns:
            raise ValueError("CSV is missing 'Word' column")
            
        # 1. Create index.json
        index_data = {
            "title": title,
            "format": 3,
            "revision": datetime.now().strftime("%Y%m%d"),
            "sequenced": True,
            "author": "SonicSandbox",
            "description": f"Generated from Surasura Analysis ({language})"
        }
        
        # 2. Create term_meta_bank_1.json
        term_data = []
        
        has_reading = 'Reading' in df.columns
        
        for idx, row in df.iterrows():
            rank = idx + 1
            # Sanitize the term (Fix 1)
            term = FrequencyExporter._sanitize_term(row['Word'])
            
            # Rule B (Simpler/Safer): 
            # Keep Katakana readings ONLY for words that are actually Katakana.
            # Otherwise, use integer format.
            is_katakana_word = FrequencyExporter._is_pure_katakana(term)
            
            use_reading_object = (
                language == 'ja' and 
                has_reading and 
                pd.notna(row['Reading']) and 
                str(row['Reading']).strip() != "" and
                is_katakana_word
            )
            
            if use_reading_object:
                reading = str(row['Reading'])
                term_entry = [term, "freq", { "reading": reading, "frequency": rank }]
            else:
                # Simple format: ["term", "freq", rank]
                term_entry = [term, "freq", rank]
                
            term_data.append(term_entry)
            
        # 3. Zip them up (Flat compression - Fix 3)
        with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('index.json', json.dumps(index_data, ensure_ascii=False, indent=2))
            zf.writestr('term_meta_bank_1.json', json.dumps(term_data, ensure_ascii=False))
