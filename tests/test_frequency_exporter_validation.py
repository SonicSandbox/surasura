import os
import pytest
import pandas as pd
from app.frequency_exporter import FrequencyExporter

def test_export_empty_dataframe(tmp_path):
    # Create an empty CSV
    csv_path = tmp_path / "empty.csv"
    with open(csv_path, "w") as f:
        f.write("Word,Reading,Frequency\n") # Header only
        
    out_path = tmp_path / "out.txt"
    
    # Should raise ValueError because it's empty
    with pytest.raises(ValueError, match="The source data is empty"):
        FrequencyExporter.export_word_list(str(csv_path), str(out_path))

def test_export_no_word_column(tmp_path):
    csv_path = tmp_path / "bad.csv"
    pd.DataFrame({"Other": [1, 2, 3]}).to_csv(csv_path, index=False)
    
    out_path = tmp_path / "out.txt"
    
    with pytest.raises(ValueError, match="CSV is missing 'Word' column"):
        FrequencyExporter.export_word_list(str(csv_path), str(out_path))

def test_export_valid_dataframe(tmp_path):
    csv_path = tmp_path / "valid.csv"
    pd.DataFrame({"Word": ["test"], "Reading": ["test"]}).to_csv(csv_path, index=False)
    
    out_path = tmp_path / "out.txt"
    
    # Should NOT raise
    FrequencyExporter.export_word_list(str(csv_path), str(out_path))
    assert os.path.exists(out_path)

def test_export_migaku_empty(tmp_path):
    csv_path = tmp_path / "empty.csv"
    with open(csv_path, "w") as f:
        f.write("Word,Reading,Frequency\n")
    out_path = tmp_path / "migaku.json"
    
    with pytest.raises(ValueError, match="The source data is empty"):
        FrequencyExporter.export_migaku(str(csv_path), str(out_path))

def test_export_yomitan_empty(tmp_path):
    csv_path = tmp_path / "empty.csv"
    with open(csv_path, "w") as f:
        f.write("Word,Reading,Frequency\n")
    out_path = tmp_path / "yomitan.zip"
    
    with pytest.raises(ValueError, match="The source data is empty"):
        FrequencyExporter.export_yomitan(str(csv_path), str(out_path))
