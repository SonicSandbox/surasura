"""The three 2.4 word-list exports, callable without Tk (`app/exports.py`, W3.3 P11).

A pure move: Export Freq List, Export Reading Words and Generate Sentence List write what 2.4 wrote. Checked three ways
on a real Generate of a small Japanese library from `tests/Test Resources/ja`: the Tk-free function against 2.4's own
`FrequencyExporter` calls, and against the Tk button path (export_wrapper) now routed through it. Then what a Qt row
meets: nothing to export yet (2.4's words), a destination that can't be written, a cancel before anything is written.
"""
import csv
import json
import os
import shutil
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from app import exports
from app.frequency_exporter import FrequencyExporter

# Real files from the shared resources: a dialogue transcript, short narration sentences and a subtitle file — mixed
# kanji / kana / katakana and a full-width ？.
LIBRARY = ("context_test.txt", "runaway_transcript.txt", "phrases_sample.srt")

# Narration the spoken corpora rarely hear (as in test_reading_words_export), so the reading-words list has rows.
NARRATION = """彼は静かに囁く。
彼女は小さな声で囁いた。
老人が窓の外を見ながら囁いている。
少女は囁きながらゆっくりと歩いた。
男はもう一度だけ囁きます。
彼は深い吐息をついた。
彼女もまた深い吐息をついた。
老人は静かに深い吐息をついた。
"""


def _user_file(root):
    return lambda p: str(root / p)


@pytest.fixture
def generated(tmp_path, ja_resources_dir):
    """A real Generate of the small library into `tmp_path/results`; `app.path_utils.get_user_file` points there for
    the test (the exports find `results/` through it). Patch `app.analyzer.*` too: it holds its own references."""
    from app import analyzer

    high = tmp_path / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (tmp_path / "User Files" / "ja").mkdir(parents=True)
    results = tmp_path / "results"
    results.mkdir()
    for name in LIBRARY:
        shutil.copy(os.path.join(ja_resources_dir, name), high / name)
    (high / "narration.txt").write_text(NARRATION, encoding="utf-8")

    with patch("app.analyzer.get_user_file", side_effect=_user_file(tmp_path)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(tmp_path / "data" / l) if l else str(tmp_path / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(tmp_path / "User Files" / l) if l else str(tmp_path / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()

    with patch("app.path_utils.get_user_file", side_effect=_user_file(tmp_path)):
        yield results


def _same_file(a, b, fmt):
    """Byte for byte; a Yomitan ZIP member by member (a zip stamps each member with the second it was written)."""
    if fmt != "yomitan":
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        return (za.namelist() == zb.namelist()
                and all(za.read(n) == zb.read(n) for n in za.namelist()))


def _tk_export(fmt, csv_path, dest, initial_name, language="ja"):
    """The Tk button path as a click runs it: export_wrapper with the Save-as answered. Returns (showinfo, showerror,
    the Save-as call)."""
    from app.main import MasterDashboardApp
    app_mock = MagicMock()
    app_mock.var_language.get.return_value = language
    with patch("tkinter.filedialog.asksaveasfilename", return_value=str(dest)) as save_as, \
         patch("tkinter.messagebox.showinfo") as info, patch("tkinter.messagebox.showerror") as error:
        MasterDashboardApp.export_wrapper(app_mock, MagicMock(), fmt, str(csv_path), initial_name)
    return info, error, save_as


# 2.4's export_wrapper, its calls as they were: what each format wrote.
_2_4 = {
    "migaku": lambda src, dest: FrequencyExporter.export_migaku(src, dest),
    "yomitan": lambda src, dest: FrequencyExporter.export_yomitan(src, dest, language="ja"),
    "txt": lambda src, dest: FrequencyExporter.export_word_list(src, dest),
    "anki": lambda src, dest: FrequencyExporter.export_anki_sentences(src, dest),
}


def test_each_export_writes_what_2_4_wrote_through_both_paths(generated, tmp_path):
    """Seven exports (two lists × three formats, and the sentence list): the Tk-free function, 2.4's own exporter call
    and the Tk button path write the same file, with 2.4's Save-as and its success box; the count is the entries."""
    out = tmp_path / "out"
    out.mkdir()
    priority = generated / "priority_learning_list.csv"
    reading = generated / "reading_words.csv"
    assert exports.csv_has_data_rows(str(priority)) and exports.csv_has_data_rows(str(reading)), \
        "the sample library should give both lists rows"

    cases = [("frequency_list", fmt, priority) for fmt in exports.FORMATS] \
        + [("reading_words", fmt, reading) for fmt in exports.FORMATS] \
        + [("sentence_list", "anki", priority)]
    for export, fmt, src in cases:
        ext = exports.save_as(fmt)[0]
        core, old, tk = (out / f"{export}-{fmt}-{who}{ext}" for who in ("core", "2.4", "tk"))
        if export == "sentence_list":
            outcome = exports.sentence_list("ja", str(core))
        else:
            outcome = getattr(exports, export)("ja", fmt, str(core))
        _2_4[fmt](str(src), str(old))
        info, error, save_as = _tk_export(fmt, src, tk, exports.INITIAL_NAMES[export])

        assert outcome.kind == "done" and outcome.path == str(core), (export, fmt, outcome)
        assert outcome.message == f"List generated successfully!\n\nSaved to: {core}"
        assert _same_file(core, old, fmt), f"{export} as {fmt} differs from 2.4's exporter"
        assert _same_file(core, tk, fmt), f"{export} as {fmt} differs from the Tk button's file"
        info.assert_called_once_with("Success", f"List generated successfully!\n\nSaved to: {tk}")
        error.assert_not_called()
        # 2.4's Save-as, word for word: the sentence list always suggests its own name.
        expected_name = ("Anki_Sentence_List" if fmt == "anki" else exports.INITIAL_NAMES[export]) + ext
        assert save_as.call_args.kwargs["initialfile"] == expected_name
        assert save_as.call_args.kwargs["title"] == f"Save {fmt.capitalize()} List"

        with open(src, encoding="utf-8-sig", newline="") as f:
            rows = sum(1 for _ in csv.DictReader(f))
        assert 0 < outcome.count <= rows, (export, fmt, outcome.count, rows)


def test_the_yomitan_dictionary_is_named_for_the_language_asked(generated, tmp_path):
    """The Tk path passes the dashboard's language; the function its `language` — a Chinese run's list says (zh)."""
    dest = tmp_path / "zh.zip"
    assert exports.frequency_list("zh", "yomitan", str(dest)).kind == "done"
    with zipfile.ZipFile(dest) as zf:
        assert json.loads(zf.read("index.json"))["description"] == "Generated from Surasura Analysis (zh)"


def test_nothing_to_export_yet_says_generate_first_in_2_4s_words(tmp_path):
    """No list (never Generated), or a header-only one: "no data", 2.4's message, nothing written. The sentence list
    keeps 2.4's byte check — a header-only priority list reaches the exporter, which refuses it ("failed")."""
    results = tmp_path / "results"
    results.mkdir()
    dest = tmp_path / "out.json"
    with patch("app.path_utils.get_user_file", side_effect=_user_file(tmp_path)):
        for outcome in (exports.frequency_list("ja", "migaku", str(dest)),
                        exports.sentence_list("ja", str(dest))):
            assert outcome == exports.Outcome("no data", None, 0, "You need to run an analysis first to generate data.")
        assert exports.reading_words("ja", "txt", str(dest)).kind == "no data"

        (results / "reading_words.csv").write_text("Word,Orth,Reading,Occurrences\n", encoding="utf-8-sig")
        (results / "priority_learning_list.csv").write_text("Word,Orth,Reading,Score\n\n", encoding="utf-8-sig")
        reading = exports.reading_words("ja", "yomitan", str(dest))
        assert reading.kind == "no data" and "no read-only words were found" in reading.message
        assert exports.frequency_list("ja", "txt", str(dest)).kind == "no data"
        sentences = exports.sentence_list("ja", str(dest))
        assert sentences.kind == "failed"
        assert sentences.message == "Failed to export:\nThe source data is empty. Cannot generate Anki list."
    assert not dest.exists()


def test_a_destination_that_cannot_be_written_fails_with_2_4s_message(generated, tmp_path):
    """A folder that isn't there: "failed", "Failed to export:" and the reason, no path; the Tk path shows the same
    words in its error box."""
    dest = tmp_path / "no such folder" / "list.txt"
    outcome = exports.frequency_list("ja", "txt", str(dest))
    assert outcome.kind == "failed" and outcome.path is None
    assert outcome.message.startswith("Failed to export:\n")
    assert not dest.exists()

    info, error, _save_as = _tk_export("txt", generated / "priority_learning_list.csv", dest,
                                       exports.INITIAL_NAMES["frequency_list"])
    info.assert_not_called()
    error.assert_called_once_with("Error", outcome.message)


def test_cancel_before_writing_writes_nothing_and_progress_reports_the_one_step(generated, tmp_path):
    dest = tmp_path / "list.json"
    assert exports.reading_words("ja", "migaku", str(dest), cancel=lambda: True).kind == "cancelled"
    assert not dest.exists()

    steps = []
    assert exports.reading_words("ja", "migaku", str(dest), progress=lambda d, t: steps.append((d, t)),
                                 cancel=lambda: False).kind == "done"
    assert steps == [(0, 1), (1, 1)]


def test_what_each_export_asks_is_data_a_row_can_show():
    """NEEDS names one entry per export function; a word list asks a format of the three, the sentence list its
    warning — and an unknown format is refused before anything is read."""
    assert set(exports.NEEDS) == {"frequency_list", "reading_words", "sentence_list"}
    assert all(callable(getattr(exports, name)) for name in exports.NEEDS)
    assert exports.NEEDS["sentence_list"] == ("confirm", "dest")
    assert set(exports.FORMAT_LABELS) == set(exports.FORMAT_TIPS) == set(exports.FORMATS)
    assert exports.SENTENCE_WARNING.startswith("WARNING:") and exports.SENTENCE_CONFIRM == "I understand"
    with pytest.raises(ValueError):
        exports.frequency_list("ja", "anki", "unused.csv")


def test_the_module_needs_neither_tk_nor_qt():
    """Callable from the Qt window's worker and the command line: importing it pulls in no GUI toolkit."""
    import subprocess
    import sys
    code = ("import sys, app.exports; "
            "print(any(m.split('.')[0] in ('tkinter', 'PyQt6') for m in sys.modules))")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
    assert result.stdout.strip() == "False", result.stderr
