import pytest
import os
import json
import zipfile
import pandas as pd
from app.frequency_exporter import FrequencyExporter

@pytest.fixture
def mock_csv(tmp_path):
    csv_path = tmp_path / "test_data.csv"
    data = {
        "Word": ["apple", "banana", "cherry"],
        "Reading": ["アップル", "バナナ", "チェリー"], # Katakana for JA tests
        "Score": [10, 5, 1]
    }
    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)
    return csv_path

def test_export_migaku(mock_csv, tmp_path):
    save_path = tmp_path / "migaku_list.json"
    FrequencyExporter.export_migaku(str(mock_csv), str(save_path))
    
    assert save_path.exists()
    with open(save_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    assert isinstance(data, list)
    assert data == ["apple", "banana", "cherry"]

def test_export_word_list(mock_csv, tmp_path):
    save_path = tmp_path / "word_list.txt"
    FrequencyExporter.export_word_list(str(mock_csv), str(save_path))
    
    assert save_path.exists()
    with open(save_path, 'r', encoding='utf-8') as f:
        content = f.read().splitlines()
        
    assert content == ["apple", "banana", "cherry"]

def test_export_yomitan_simple(mock_csv, tmp_path):
    save_path = tmp_path / "yomitan_simple.zip"
    # Use 'en' or 'zh' to force simple format (Option A)
    FrequencyExporter.export_yomitan(str(mock_csv), str(save_path), language='en')
    
    assert save_path.exists()
    assert zipfile.is_zipfile(save_path)
    
    with zipfile.ZipFile(save_path, 'r') as zf:
        # Check files exist
        assert "index.json" in zf.namelist()
        assert "term_meta_bank_1.json" in zf.namelist()
        
        # Check index
        index_data = json.loads(zf.read("index.json"))
        assert index_data["format"] == 3
        
        # Check terms (Simple format)
        term_data = json.loads(zf.read("term_meta_bank_1.json"))
        # Expected: ["apple", "freq", 1]
        assert term_data[0] == ["apple", "freq", 1]
        assert term_data[1] == ["banana", "freq", 2]

def test_export_yomitan_strict(tmp_path):
    # Use actual Katakana words for this test to trigger reading object
    csv_path = tmp_path / "ja_data.csv"
    data = {
        "Word": ["バナナ", "アップル"],
        "Reading": ["バナナ", "アップル"]
    }
    pd.DataFrame(data).to_csv(csv_path, index=False)
    
    save_path = tmp_path / "yomitan_strict.zip"
    # Use 'ja' with readings present -> Option B
    FrequencyExporter.export_yomitan(str(csv_path), str(save_path), language='ja')
    
    assert save_path.exists()
    with zipfile.ZipFile(save_path, 'r') as zf:
        term_data = json.loads(zf.read("term_meta_bank_1.json"))
        # Expected: ["バナナ", "freq", {"reading": "バナナ", "frequency": 1}]
        entry = term_data[0]
        assert entry[0] == "バナナ"
        assert entry[1] == "freq"
        assert isinstance(entry[2], dict)
        assert entry[2]["reading"] == "バナナ"
        assert entry[2]["frequency"] == 1

def test_export_yomitan_missing_reading_fallback(tmp_path):
    # CSV without Reading column
    csv_path = tmp_path / "no_reading.csv"
    pd.DataFrame({"Word": ["apple"]}).to_csv(csv_path, index=False)
    
    save_path = tmp_path / "yomitan_fallback.zip"
    # Even if JA, if reading is missing, should fallback to Option A or handle gracefully
    FrequencyExporter.export_yomitan(str(csv_path), str(save_path), language='ja')
    
    with zipfile.ZipFile(save_path, 'r') as zf:
        term_data = json.loads(zf.read("term_meta_bank_1.json"))
        # Fallback to simple format: ["apple", "freq", 1]
        assert term_data[0] == ["apple", "freq", 1]


# --- D4: exports carry the spelling the content uses, not the canonical lemma -------------------
# `Word` is UniDic's lemma — an identity key, and frequently a spelling nobody writes (スドウ for
# 須藤, 引き摺る for 引きずる). `Orth` is how the user's own content spells it, so that is what goes
# on the card front / into the frequency list. Results made before the column existed have no
# `Orth` at all, so every export has to fall back to `Word`.

@pytest.fixture
def orth_csv(tmp_path):
    """A priority list as the analyzer writes it since D4.

    Real rows, not placeholders: スドウ/須藤 is the most visible form of the bug (UniDic lemmatizes
    proper nouns to their reading) and 引き摺る/引きずる is the case that started it. 冒険 is the
    ordinary case where the two agree, which must keep working unchanged."""
    csv_path = tmp_path / "priority_learning_list.csv"
    pd.DataFrame([
        {"Word": "スドウ", "Orth": "須藤", "Reading": "スドウ", "Context 1": "須藤は鳥取へ行く。"},
        {"Word": "引き摺る", "Orth": "引きずる", "Reading": "ヒキズル",
         "Context 1": "初めてなんか引きずってしまった恋だった。"},
        {"Word": "冒険", "Orth": "冒険", "Reading": "ボウケン", "Context 1": "彼は毎日冒険に出かけます。"},
    ]).to_csv(csv_path, index=False, encoding="utf-8")
    return csv_path


@pytest.fixture
def pre_orth_csv(tmp_path):
    """The same list as an OLDER result folder wrote it — no `Orth` column anywhere."""
    csv_path = tmp_path / "legacy_priority.csv"
    pd.DataFrame([
        {"Word": "スドウ", "Reading": "スドウ", "Context 1": "須藤は鳥取へ行く。"},
        {"Word": "冒険", "Reading": "ボウケン", "Context 1": "彼は毎日冒険に出かけます。"},
    ]).to_csv(csv_path, index=False, encoding="utf-8")
    return csv_path


def _yomitan_terms(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        return json.loads(zf.read("term_meta_bank_1.json"))


def test_all_three_word_exports_agree_on_the_orth(orth_csv, tmp_path):
    """Migaku, Yomitan and the plain txt list must name a word identically — a user who imports
    two of them must not end up with 須藤 in one and スドウ in the other."""
    migaku = tmp_path / "migaku.json"
    txt = tmp_path / "words.txt"
    yomi = tmp_path / "yomitan.zip"
    FrequencyExporter.export_migaku(str(orth_csv), str(migaku))
    FrequencyExporter.export_word_list(str(orth_csv), str(txt))
    FrequencyExporter.export_yomitan(str(orth_csv), str(yomi), language='ja')

    expected = ["須藤", "引きずる", "冒険"]
    assert json.loads(migaku.read_text(encoding="utf-8")) == expected
    assert txt.read_text(encoding="utf-8").splitlines() == expected
    assert [entry[0] for entry in _yomitan_terms(yomi)] == expected


def test_anki_sentence_export_fronts_the_spelling_the_sentence_uses(orth_csv, tmp_path):
    """The card front has to match the sentence on the back: a card reading スドウ over
    「須藤は鳥取へ行く。」 is unreviewable."""
    save_path = tmp_path / "anki.csv"
    FrequencyExporter.export_anki_sentences(str(orth_csv), str(save_path))

    out = pd.read_csv(save_path, encoding="utf-8-sig")
    assert out["Word"].tolist() == ["須藤", "引きずる", "冒険"]
    # The example sentence is untouched, and now actually contains the word on the front.
    assert out["Sentence 1"].iloc[0] == "須藤は鳥取へ行く。"


def test_exports_fall_back_to_the_lemma_when_the_result_predates_the_orth_column(pre_orth_csv, tmp_path):
    """Backward compatibility: an older results/ folder has no `Orth` column at all. Every export
    must still produce the lemma rather than a blank line / an empty card."""
    migaku = tmp_path / "legacy_migaku.json"
    txt = tmp_path / "legacy_words.txt"
    yomi = tmp_path / "legacy_yomitan.zip"
    anki = tmp_path / "legacy_anki.csv"
    FrequencyExporter.export_migaku(str(pre_orth_csv), str(migaku))
    FrequencyExporter.export_word_list(str(pre_orth_csv), str(txt))
    FrequencyExporter.export_yomitan(str(pre_orth_csv), str(yomi), language='ja')
    FrequencyExporter.export_anki_sentences(str(pre_orth_csv), str(anki))

    expected = ["スドウ", "冒険"]
    assert json.loads(migaku.read_text(encoding="utf-8")) == expected
    assert txt.read_text(encoding="utf-8").splitlines() == expected
    assert [entry[0] for entry in _yomitan_terms(yomi)] == expected
    assert pd.read_csv(anki, encoding="utf-8-sig")["Word"].tolist() == expected


def test_a_blank_orth_cell_falls_back_to_the_lemma_rather_than_exporting_nothing(tmp_path):
    """A hand-edited or partially-written CSV can carry the column with empty cells. pandas reads
    those as NaN, which must not become an empty entry or a literal "nan"."""
    csv_path = tmp_path / "partial.csv"
    pd.DataFrame([
        {"Word": "冒険", "Orth": ""},
        {"Word": "須藤", "Orth": "   "},
    ]).to_csv(csv_path, index=False, encoding="utf-8")

    save_path = tmp_path / "partial.txt"
    FrequencyExporter.export_word_list(str(csv_path), str(save_path))
    assert save_path.read_text(encoding="utf-8").splitlines() == ["冒険", "須藤"]


def test_yomitan_reading_rule_follows_the_exported_term(orth_csv, tmp_path):
    """The katakana-only rule is about the term that ships, not the lemma behind it. スドウ is pure
    katakana and used to earn a reading object; 須藤 is not, so this row now takes the plain rank
    format — otherwise Yomitan would key a reading onto a word it was never exported under."""
    save_path = tmp_path / "yomitan_orth.zip"
    FrequencyExporter.export_yomitan(str(orth_csv), str(save_path), language='ja')

    terms = _yomitan_terms(save_path)
    assert terms[0] == ["須藤", "freq", 1]
