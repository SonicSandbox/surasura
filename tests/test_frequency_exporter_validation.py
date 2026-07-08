import os
import json
import zipfile
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


# --- Regression: NaN / blank / hyphen-only Word cells must never reach the output ---
# A real frequency CSV can carry a stray empty or NaN Word (a half-written row) or a term that
# sanitizes down to nothing (a leading "-"). Those must be dropped, never emitted as a bare
# `NaN` JSON token, a "nan"/blank line, or an empty vocabulary entry (frequency-01/02/08).

def _csv_with_dirty_words(tmp_path):
    """Real JA words interleaved with a NaN, a whitespace-only, and a leading-hyphen cell."""
    csv_path = tmp_path / "dirty.csv"
    pd.DataFrame({
        "Word":    ["猫",   None,  "   ", "-です", "走る",   "日本語"],
        "Reading": ["ねこ", "x",   "y",   "z",     "はしる", "にほんご"],
    }).to_csv(csv_path, index=False)
    return csv_path


def test_export_migaku_drops_nan_blank_and_hyphen(tmp_path):
    csv_path = _csv_with_dirty_words(tmp_path)
    out_path = tmp_path / "migaku.json"
    FrequencyExporter.export_migaku(str(csv_path), str(out_path))
    # Must be valid JSON: a bare NaN token would make json.load raise.
    with open(out_path, encoding="utf-8") as f:
        words = json.load(f)
    assert words == ["猫", "走る", "日本語"]


def test_export_word_list_drops_nan_blank_and_hyphen(tmp_path):
    csv_path = _csv_with_dirty_words(tmp_path)
    out_path = tmp_path / "list.txt"
    FrequencyExporter.export_word_list(str(csv_path), str(out_path))
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["猫", "走る", "日本語"]
    assert "nan" not in lines and "" not in lines


def test_export_yomitan_drops_nan_and_stays_valid_json(tmp_path):
    csv_path = _csv_with_dirty_words(tmp_path)
    out_path = tmp_path / "yomitan.zip"
    FrequencyExporter.export_yomitan(str(csv_path), str(out_path), language="ja")
    with zipfile.ZipFile(out_path) as zf:
        terms = json.loads(zf.read("term_meta_bank_1.json").decode("utf-8"))
    assert [t[0] for t in terms] == ["猫", "走る", "日本語"]  # dirty rows skipped
    # Rank stays tied to the original frequency position (row indices 0,4,5 -> ranks 1,5,6).
    ranks = {t[0]: t[2] for t in terms}
    assert ranks["猫"] == 1 and ranks["走る"] == 5 and ranks["日本語"] == 6


def test_export_anki_drops_nan_and_keeps_contiguous_index(tmp_path):
    csv_path = _csv_with_dirty_words(tmp_path)
    out_path = tmp_path / "anki.csv"
    FrequencyExporter.export_anki_sentences(str(csv_path), str(out_path))
    out = pd.read_csv(out_path)
    assert out["Word"].tolist() == ["猫", "走る", "日本語"]
    # Index counts only kept rows, so skipped ones leave no gaps.
    assert out["Index"].tolist() == [1, 2, 3]
