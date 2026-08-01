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
    # Rank is ROW POSITION — the exporter preserves the order it is given and never sorts. The
    # frequency meaning comes from the analyzer, which writes the sidecar sorted by descending
    # occurrences; break that sort and these ranks stop meaning anything, without any error.
    # Every fixture word contains kanji, so each entry takes the plain-integer form (the reading
    # object is reserved for pure-katakana words — see _is_pure_katakana).
    assert [t[2] for t in terms] == list(range(1, len(READING_WORDS) + 1))


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


# --- end-to-end: what the analyzer actually writes -------------------------------------------- #

# 囁く is the discriminating fixture. Unidic hands it THREE readings across ordinary conjugations
# (ササヤク / ササヤイ / ササヤキ), and the spoken corpora rank it ~37,000 — about one encounter per
# 168 hours of listening, comfortably a reading word. That combination is the whole point: split
# three ways, no single reading reaches logic.modality.min_lib_count (3), so judged per
# (word, reading) the word earns no badge at all. Rolled up per LEMMA it is correctly flagged, once.
# 吐息 is the single-reading control that must behave identically either way.
NARRATION = """彼は静かに囁く。
彼女は小さな声で囁いた。
老人が窓の外を見ながら囁いている。
少女は囁きながらゆっくりと歩いた。
男はもう一度だけ囁きます。
彼は深い吐息をついた。
彼女もまた深い吐息をついた。
老人は静かに深い吐息をついた。
"""


def _analyze(root):
    """Run a real analysis against `root`, and only against `root`. Returns the results dir.

    Patch `app.analyzer.*`, never `app.path_utils.*`: the analyzer does
    `from app.path_utils import get_data_path`, so it holds its own reference and patching
    path_utils leaves it walking the developer's real library (testing.md §5.2).

    `--min-freq 1` pins the selection floor to a raw count, bypassing the density bands — otherwise
    the fixture's verdict would depend on whichever band the developer's settings.json happens to
    hold.
    """
    from unittest.mock import patch
    from app import analyzer

    high = root / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (root / "User Files" / "ja").mkdir(parents=True)
    results = root / "results"
    results.mkdir()
    (high / "narration.txt").write_text(NARRATION, encoding="utf-8")

    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(root / "data" / l) if l else str(root / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(root / "User Files" / l) if l else str(root / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()
    return results


def _sidecar_rows(results):
    with open(results / "reading_words.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_the_analyzer_writes_a_sidecar_the_ordinary_exporters_can_read(tmp_path):
    """The contract that lets both export buttons share one format picker.

    The exporters key off a `Word` column and nothing else, so the sidecar has to be a CSV shaped
    exactly like the priority list. Checked against a real run rather than the source text: the
    columns are what an exporter consumes, and a rename that kept the header would be harmless
    while one that changed it would not.
    """
    results = _analyze(tmp_path)

    with open(results / "reading_words.csv", encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f))
    assert header == ["Word", "Reading", "Occurrences"]

    # ...and the real exporters must actually consume the real file.
    out = tmp_path / "reading.txt"
    FrequencyExporter.export_word_list(str(results / "reading_words.csv"), str(out))
    assert out.read_text(encoding="utf-8").splitlines() == [r["Word"] for r in _sidecar_rows(results)]


def test_the_lemma_is_the_unit_of_judgement_not_the_reading(tmp_path):
    """One verdict and one entry per WORD, however many readings unidic files it under.

    Both halves of the same fix. 囁く arrives as three readings; judged separately each sees only a
    share of the evidence and falls under min_lib_count, so the word was missed entirely — and any
    word that did clear the floor twice was listed twice at two different ranks, which is just
    noise to whatever dictionary loads it.
    """
    results = _analyze(tmp_path)

    words = [r["Word"] for r in _sidecar_rows(results)]
    assert "囁く" in words, (
        "a rare-in-speech word was missed — evidence is being split across its readings again")
    assert words.count("囁く") == 1, f"listed more than once: {words}"
    assert len(words) == len(set(words)), f"duplicate entries: {words}"

    # The same roll-up drives the report's 文 badge, so every row for a word must agree.
    with open(results / "priority_learning_list.csv", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["Word"] == "囁く"]
    assert len(rows) > 1, "fixture no longer produces a multi-reading lemma; pick another word"
    assert {r["Modality"] for r in rows} == {"reading"}, (
        "the verdict differs between two readings of one word: "
        f"{[(r['Reading'], r['Modality']) for r in rows]}")


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
