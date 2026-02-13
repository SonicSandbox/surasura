import os
import pytest
import pandas as pd
from app.frequency_exporter import FrequencyExporter

class TestFrequencyExporterBug:
    def test_export_word_list_non_empty(self, tmp_path):
        """Verify that export_word_list generates a non-empty file from valid CSV."""
        csv_path = tmp_path / "priority_learning_list.csv"
        out_path = tmp_path / "output.txt"
        
        # Create Dummy CSV
        df = pd.DataFrame({
            'Word': ['apple', 'banana', 'cherry-fruit'],
            'Frequency': [100, 50, 10],
            'Reading': ['apple', 'banana', 'cherry']
        })
        df.to_csv(csv_path, index=False)
        
        # Run Export
        FrequencyExporter.export_word_list(str(csv_path), str(out_path))
        
        # Check Output
        assert os.path.exists(out_path)
        with open(out_path, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f.readlines()]
            
        print(f"Generated lines: {lines}")
        assert len(lines) == 3
        assert lines[0] == "apple"
        assert lines[2] == "cherry" # Should strip -fruit

    def test_export_word_list_with_nan(self, tmp_path):
        """Check behavior with NaN or empty words."""
        csv_path = tmp_path / "priority_learning_list.csv"
        out_path = tmp_path / "output_nan.txt"
        
        df = pd.DataFrame({
            'Word': ['apple', None, '', 'date'],
            'Frequency': [10, 5, 2, 1]
        })
        df.to_csv(csv_path, index=False)
        
        try:
            FrequencyExporter.export_word_list(str(csv_path), str(out_path))
        except Exception as e:
            print(f"Caught expected error or bug: {e}")

        if os.path.exists(out_path):
            with open(out_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            print(f"Lines with NaN input: {lines}")
