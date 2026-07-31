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
    def _clean_term(term):
        """Sanitize a Word cell and validate it for export.

        Returns the cleaned term, or None when the cell is NaN/blank or sanitizes down to
        nothing (e.g. a leading '-'). Callers skip None so a stray empty/NaN row can never
        emit an invalid JSON `NaN` token, a "nan"/blank line, or an empty vocabulary entry.
        """
        cleaned = FrequencyExporter._sanitize_term(term)
        if not isinstance(cleaned, str):
            return None
        cleaned = cleaned.strip()
        return cleaned or None

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
            
        # Sanitize words, dropping NaN/blank rows so the JSON array can't contain a bare
        # `NaN` token (invalid JSON) or empty strings.
        word_list = [t for t in (FrequencyExporter._clean_term(w) for w in df['Word'].tolist()) if t]

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
            
        # Sanitize words, dropping NaN/blank rows so we never write a stray "nan" or blank line.
        word_list = [t for t in (FrequencyExporter._clean_term(w) for w in df['Word'].tolist()) if t]

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
            # Sanitize + validate the term; skip NaN/blank rows so we never emit an invalid
            # entry. Rank stays tied to the original frequency position (skipped ranks just gap).
            term = FrequencyExporter._clean_term(row['Word'])
            if not term:
                continue

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

    @staticmethod
    def export_anki_sentences(csv_path, save_path):
        """
        Export as a CSV suitable for Anki/SRS import.
        Includes Word, Reading, Context 1 (main sentence), Context 2 (i+1/second sentence), Tier,
        Sources, and the source FILE behind each sentence.

        'Source 1'/'Source 2' are appended LAST so an existing Anki field mapping keeps working —
        importers match by column order, so adding at the end can only leave the new fields unmapped,
        never shift an existing one. They're empty for results generated before the badge existed.
        """
        df = pd.read_csv(csv_path)
        if df.empty:
            raise ValueError("The source data is empty. Cannot generate Anki list.")
        if 'Word' not in df.columns:
            raise ValueError("CSV is missing 'Word' column")
            
        # Determine available columns
        available_cols = df.columns.tolist()
        
        # Prepare output data
        output_data = []
        for _, row in df.iterrows():
            word = FrequencyExporter._clean_term(row.get('Word', ''))
            if not word:
                continue  # skip NaN/blank rows so they don't become empty Anki cards
            reading = row.get('Reading', '') if 'Reading' in available_cols else ''
            
            # Context Sentences
            sentence_1 = row.get('Context 1', '') if 'Context 1' in available_cols else ''
            sentence_2 = row.get('Context 2', '') if 'Context 2' in available_cols else ''
            
            # Extra fields
            tier = row.get('Tier', '') if 'Tier' in available_cols else ''
            sources = row.get('Sources', '') if 'Sources' in available_cols else ''

            # Which file each sentence came from (blank on pre-badge results).
            src_1 = row.get('Src 1', '') if 'Src 1' in available_cols else ''
            src_2 = row.get('Src 2', '') if 'Src 2' in available_cols else ''

            output_data.append({
                'Index': len(output_data) + 1,
                'Word': word,
                'Reading': reading,
                'Sentence 1': sentence_1,
                'Sentence 2': sentence_2,
                'Tier': tier,
                'Sources': sources,
                'Source 1': src_1,
                'Source 2': src_2
            })
            
        # Write properly formatted CSV using pandas to ensure delimiter safety
        out_df = pd.DataFrame(output_data)
        out_df.to_csv(save_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_MINIMAL)

