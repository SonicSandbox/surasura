"""Exporting the reading-only words as a Yomitan frequency list.

Loaded next to your other dictionaries, PRESENCE in this list is the signal — if the popup shows
it, the word is one you'll read but hardly ever hear. So the export must be complete (not cut at
the selection band's floor) and must never invent an entry.
"""

import json
import os
import zipfile

import pytest

from app.frequency_exporter import FrequencyExporter


# Real narration vocabulary, in the shape the analyzer's sidecar writes: [word, library count].
READING_WORDS = [
    ["覗き込む", 99],
    ["睨み付ける", 96],
    ["震わせる", 83],
    ["付け加える", 79],
    ["吐息", 71],
]


@pytest.fixture
def sidecar(tmp_path):
    path = tmp_path / "reading_words.json"
    path.write_text(json.dumps(READING_WORDS, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _read_zip(path):
    with zipfile.ZipFile(path) as zf:
        return (json.loads(zf.read("index.json").decode("utf-8")),
                json.loads(zf.read("term_meta_bank_1.json").decode("utf-8")))


def test_exports_a_valid_yomitan_dictionary(sidecar, tmp_path):
    out = tmp_path / "reading.zip"
    FrequencyExporter.export_reading_words(sidecar, str(out))

    index, terms = _read_zip(str(out))
    assert index["format"] == 3
    assert index["title"]
    assert len(terms) == len(READING_WORDS)
    assert all(t[1] == "freq" for t in terms)


def test_rank_is_position_by_library_frequency(sidecar, tmp_path):
    """The badge should say both 'this is a reading word' and 'how often you'll meet it'."""
    out = tmp_path / "reading.zip"
    FrequencyExporter.export_reading_words(sidecar, str(out))

    _index, terms = _read_zip(str(out))
    assert terms[0][0] == "覗き込む" and terms[0][2] == 1      # most frequent -> rank 1
    assert [t[2] for t in terms] == [1, 2, 3, 4, 5]


def test_missing_sidecar_tells_the_user_to_run_an_analysis(tmp_path):
    """A fresh install has no results yet; that's a normal state, not a crash."""
    with pytest.raises(ValueError, match="Generate your Vocab Journey"):
        FrequencyExporter.export_reading_words(str(tmp_path / "nope.json"),
                                               str(tmp_path / "out.zip"))


def test_empty_list_is_reported_rather_than_shipping_an_empty_dictionary(tmp_path):
    """An empty Yomitan dict imports silently and looks broken — say why instead."""
    empty = tmp_path / "reading_words.json"
    empty.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="reading-only words"):
        FrequencyExporter.export_reading_words(str(empty), str(tmp_path / "out.zip"))


def test_blank_and_malformed_entries_are_skipped(tmp_path):
    """Mirrors the NaN/blank guard the other exporters use, so no empty vocabulary entries."""
    path = tmp_path / "reading_words.json"
    path.write_text(json.dumps([["覗き込む", 5], ["", 4], ["  ", 3], ["-", 2], ["吐息", 1]],
                               ensure_ascii=False), encoding="utf-8")

    out = tmp_path / "reading.zip"
    FrequencyExporter.export_reading_words(str(path), str(out))

    _index, terms = _read_zip(str(out))
    assert [t[0] for t in terms] == ["覗き込む", "吐息"]
    assert [t[2] for t in terms] == [1, 2]


def test_mixed_scripts_and_long_entries_survive_the_round_trip(tmp_path):
    """Encoding edge cases: kanji+okurigana, pure katakana, and a long compound."""
    words = [["引っ繰り返す", 9], ["コンテンツ", 7], ["取り繕う", 5]]
    path = tmp_path / "reading_words.json"
    path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")

    out = tmp_path / "reading.zip"
    FrequencyExporter.export_reading_words(str(path), str(out))

    _index, terms = _read_zip(str(out))
    assert [t[0] for t in terms] == ["引っ繰り返す", "コンテンツ", "取り繕う"]


def test_analyzer_writes_the_sidecar_alongside_its_other_outputs():
    """The exporter reads a file the analyzer must actually produce — guard the contract."""
    import inspect
    from app import analyzer

    source = inspect.getsource(analyzer.main)
    assert "reading_words.json" in source
    # Built from word_stats, NOT the floor-filtered rows — a word met five times is exactly
    # where knowing "you'll never hear this" matters most.
    assert "_modality_of(lemma, data) == \"reading\"" in source
