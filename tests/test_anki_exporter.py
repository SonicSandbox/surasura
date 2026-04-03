import os
import pandas as pd
import pytest
from app.frequency_exporter import FrequencyExporter

def test_anki_exporter_format(tmp_path):
    """
    Test that the Anki exporter correctly reads a mocked priority_learning_list.csv
    and outputs a safe CSV with the required columns:
    Word, Reading, Sentence 1, Sentence 2, Tier, Sources
    """
    mock_csv = tmp_path / "priority_learning_list.csv"
    out_csv = tmp_path / "anki_output.csv"
    
    # Create mock CSV
    mock_data = {
        "Word": ["食べる", "猫-neko", "走る"],
        "Reading": ["たべる", "ねこ", "はしる"],
        "Context 1": ["リンゴを食べる。", "猫が可愛い！", "早く走る。"],
        "Context 2": ["一緒に食べる？", "", "彼は走るのが早い。"],
        "Context 3": ["", "", ""],
        "Tier": ["Anime:1", "Anime:2", "Outside"],
        "Score": [10.5, 5.0, 2.0],
        "Sources": ["Book A;Book B", "Book A", "Book C"]
    }
    
    df = pd.DataFrame(mock_data)
    df.to_csv(mock_csv, index=False)
    
    # Run exporter
    FrequencyExporter.export_anki_sentences(str(mock_csv), str(out_csv))
    
    # Verify export
    assert out_csv.exists()
    
    # Load exported CSV and check formatting
    out_df = pd.read_csv(out_csv)
    
    # Assert expected columns
    expected_cols = ["Index", "Word", "Reading", "Sentence 1", "Sentence 2", "Tier", "Sources"]
    assert list(out_df.columns) == expected_cols
    
    # Assert Index was added correctly (1-indexed)
    assert out_df.iloc[0]["Index"] == 1
    assert out_df.iloc[1]["Index"] == 2
    assert out_df.iloc[2]["Index"] == 3
    
    # Assert Sanitize Term was applied ('猫-neko' -> '猫')
    assert out_df.iloc[1]["Word"] == "猫"
    assert out_df.iloc[0]["Word"] == "食べる"
    
    # Assert Sentences mapped correctly
    assert out_df.iloc[0]["Sentence 1"] == "リンゴを食べる。"
    assert out_df.iloc[0]["Sentence 2"] == "一緒に食べる？"
    
    # Assert handling of blank sentences (nan in pandas reading from csv)
    # pandas reads empty strings as NaN inside pd.read_csv by default
    sentence_2_for_cat = out_df.iloc[1]["Sentence 2"]
    assert pd.isna(sentence_2_for_cat) or sentence_2_for_cat == ""
    
    # Assert Extra fields
    assert out_df.iloc[0]["Tier"] == "Anime:1"
    assert out_df.iloc[0]["Sources"] == "Book A;Book B"

def test_anki_exporter_missing_fields(tmp_path):
    """
    Test robust handling if the input CSV lacks Optional columns (e.g. Context 2 or Tier)
    """
    mock_csv = tmp_path / "priority_learning_list_minimal.csv"
    out_csv = tmp_path / "anki_output_minimal.csv"
    
    # Minimal mock CSV
    mock_data = {
        "Word": ["食べる"],
        "Reading": ["たべる"],
        "Context 1": ["リンゴを食べる。"]
    }
    
    df = pd.DataFrame(mock_data)
    df.to_csv(mock_csv, index=False)
    
    FrequencyExporter.export_anki_sentences(str(mock_csv), str(out_csv))
    
    out_df = pd.read_csv(out_csv)
    
    # Columns should still be produced, even if blank
    assert "Tier" in out_df.columns
    assert "Sentence 2" in out_df.columns
    assert pd.isna(out_df.iloc[0]["Tier"]) or out_df.iloc[0]["Tier"] == ""
    assert pd.isna(out_df.iloc[0]["Sentence 2"]) or out_df.iloc[0]["Sentence 2"] == ""
