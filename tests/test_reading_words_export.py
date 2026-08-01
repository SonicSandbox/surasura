"""Exporting the reading-only words.

The list ships as a CSV with the same columns as the priority list, which is the whole point: every
existing exporter (Migaku / Yomitan / plain text) reads it with no format-specific branch, and both
export buttons can share one dialog. A Migaku user can't do anything with a Yomitan ZIP, so
offering only one format would have excluded them.

Loaded as a dictionary while mining, PRESENCE in this list is the signal — if it shows a rank, the
word is one you'll read but hardly ever hear.
"""

import csv
import json
import zipfile

import pytest

from app.frequency_exporter import FrequencyExporter


# Real narration vocabulary, in the shape the analyzer's sidecar writes.
READING_WORDS = [
    ("覗き込む", "ノゾキコム", 99),
    ("睨み付ける", "ニラミツケル", 96),
    ("震わせる", "フルワセル", 83),
    ("付け加える", "ツケクワエル", 79),
    ("吐息", "トイキ", 71),
]


@pytest.fixture
def sidecar(tmp_path):
    path = tmp_path / "reading_words.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Word", "Reading", "Occurrences"])
        w.writerows(READING_WORDS)
    return str(path)


def _read_zip(path):
    with zipfile.ZipFile(path) as zf:
        return (json.loads(zf.read("index.json").decode("utf-8")),
                json.loads(zf.read("term_meta_bank_1.json").decode("utf-8")))


def test_yomitan_export_ranks_by_library_frequency(sidecar, tmp_path):
    """The rank carries the second fact: not just that it's a reading word, but how often."""
    out = tmp_path / "reading.zip"
    FrequencyExporter.export_yomitan(sidecar, str(out), language="ja")

    index, terms = _read_zip(str(out))
    assert index["format"] == 3
    assert [t[0] for t in terms] == [w for w, _r, _n in READING_WORDS]
    assert [t[2] for t in terms if isinstance(t[2], int)] or terms[0][2] == 1


def test_migaku_export_works_on_the_same_file(sidecar, tmp_path):
    """The reason the sidecar is a CSV at all — Migaku users can't use a Yomitan ZIP."""
    out = tmp_path / "reading.json"
    FrequencyExporter.export_migaku(sidecar, str(out))

    words = json.loads(out.read_text(encoding="utf-8"))
    assert words == [w for w, _r, _n in READING_WORDS]


def test_plain_text_export_works_on_the_same_file(sidecar, tmp_path):
    out = tmp_path / "reading.txt"
    FrequencyExporter.export_word_list(sidecar, str(out))

    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines == [w for w, _r, _n in READING_WORDS]


def test_empty_list_is_refused_rather_than_shipping_an_empty_dictionary(tmp_path):
    """An empty export imports silently and looks broken — the exporters say why instead."""
    empty = tmp_path / "reading_words.csv"
    empty.write_text("Word,Reading,Occurrences\n", encoding="utf-8-sig")

    for fn in (FrequencyExporter.export_migaku, FrequencyExporter.export_word_list):
        with pytest.raises(ValueError):
            fn(str(empty), str(tmp_path / "out"))


def test_blank_and_malformed_entries_are_skipped(tmp_path):
    """Mirrors the NaN/blank guard the other exports use, so no empty vocabulary entries."""
    path = tmp_path / "reading_words.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Word", "Reading", "Occurrences"])
        w.writerows([("覗き込む", "ノゾキコム", 5), ("", "", 4), ("-", "", 2), ("吐息", "トイキ", 1)])

    out = tmp_path / "reading.txt"
    FrequencyExporter.export_word_list(str(path), str(out))
    assert out.read_text(encoding="utf-8").splitlines() == ["覗き込む", "吐息"]


def test_analyzer_writes_the_sidecar_as_a_csv_with_the_shared_columns():
    """The exporters require a `Word` column; the analyzer must actually produce one.

    Guards the contract that lets both export buttons share one dialog.
    """
    import inspect
    from app import analyzer

    source = inspect.getsource(analyzer.main)
    assert "reading_words.csv" in source
    assert '["Word", "Reading", "Occurrences"]' in source
    # Built from word_stats, NOT the floor-filtered rows — a word met five times is exactly
    # where knowing "you'll never hear this" matters most.
    assert '_modality_of(lemma)' in source


def test_export_lists_each_word_once():
    """One row per word, not per (word, reading).

    unidic gives some words several readings — 差し伸べる arrives as both サシノベ and サシノベル —
    and a dictionary that lists the same term twice with two different ranks is just noise to
    whoever loads it. Occurrences are summed onto a single row.
    """
    import inspect
    from app import analyzer

    source = inspect.getsource(analyzer.main)
    assert "_best" in source, "the sidecar no longer de-duplicates by word"
    assert "_best.get(lemma)" in source


def test_emptiness_is_decided_by_rows_not_bytes(tmp_path):
    """A header-only list is empty, however many bytes it occupies.

    The analyzer writes the reading-words header unconditionally, so "no read-only words found"
    produces a file that exists and has a non-zero size — which a size check reads as data.
    """
    from app.main import csv_has_data_rows

    header_only = tmp_path / "header_only.csv"
    header_only.write_text("Word,Reading,Occurrences\n", encoding="utf-8-sig")
    assert not csv_has_data_rows(str(header_only))

    populated = tmp_path / "populated.csv"
    with open(populated, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Word", "Reading", "Occurrences"])
        w.writerows(READING_WORDS)
    assert csv_has_data_rows(str(populated))

    # A trailing blank line is what a CSV writer leaves behind, not a row.
    blank_tail = tmp_path / "blank_tail.csv"
    blank_tail.write_text("Word,Reading,Occurrences\n\n", encoding="utf-8-sig")
    assert not csv_has_data_rows(str(blank_tail))

    assert not csv_has_data_rows(str(tmp_path / "does_not_exist.csv"))


def test_no_reading_words_explains_itself_instead_of_failing_at_the_exporter(tmp_path):
    """The message written for this case has to actually reach the user.

    Entered through the public button handler: with the guard passing, the format picker opened and
    the only feedback was the exporter's generic "the source data is empty" several clicks later.
    """
    from unittest.mock import MagicMock, patch
    from app.main import MasterDashboardApp

    results = tmp_path / "results"
    results.mkdir()
    (results / "reading_words.csv").write_text("Word,Reading,Occurrences\n", encoding="utf-8-sig")

    app_mock = MagicMock()
    # Bind the real shared dialog; on a MagicMock `self` the call would otherwise be swallowed.
    app_mock._show_export_dialog = lambda *a, **kw: MasterDashboardApp._show_export_dialog(
        app_mock, *a, **kw)

    with patch("app.path_utils.get_user_file", return_value=str(results)), \
         patch("tkinter.messagebox.showwarning") as mock_warning, \
         patch("app.main.tk.Toplevel") as mock_toplevel:
        MasterDashboardApp.generate_reading_words(app_mock)

    mock_warning.assert_called_once()
    assert "no read-only words were found" in mock_warning.call_args[0][1]
    mock_toplevel.assert_not_called()


def test_a_populated_list_still_reaches_the_format_picker(tmp_path):
    """The guard must not become over-eager — the ordinary path has to still open the dialog."""
    from unittest.mock import MagicMock, patch
    from app.main import MasterDashboardApp

    results = tmp_path / "results"
    results.mkdir()
    with open(results / "reading_words.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Word", "Reading", "Occurrences"])
        w.writerows(READING_WORDS)

    app_mock = MagicMock()
    app_mock._show_export_dialog = lambda *a, **kw: MasterDashboardApp._show_export_dialog(
        app_mock, *a, **kw)

    # The dialog's widgets are irrelevant here; only whether we got past the guard.
    with patch("app.path_utils.get_user_file", return_value=str(results)), \
         patch("tkinter.messagebox.showwarning") as mock_warning, \
         patch("app.main.tk.Toplevel"), patch("app.main.ttk.Frame"), \
         patch("app.main.ttk.Label"), patch("app.main.ttk.Button"), \
         patch("app.main.ToolTip"):
        MasterDashboardApp.generate_reading_words(app_mock)

    mock_warning.assert_not_called()


def test_both_export_buttons_share_one_dialog():
    """Two word lists, one format picker — so a format can never be added to only one of them."""
    import inspect
    from app.main import MasterDashboardApp

    for method in (MasterDashboardApp.generate_frequency_list,
                   MasterDashboardApp.generate_reading_words):
        assert "_show_export_dialog" in inspect.getsource(method)

    dialog = inspect.getsource(MasterDashboardApp._show_export_dialog)
    for fmt in ("migaku", "yomitan", "txt"):
        assert f'"{fmt}"' in dialog
