"""The three 2.4 word-list exports, callable without Tk (W3.3 P11): *Export Freq List*, *Export Reading Words* and
*Generate Sentence List*.

Each reads one CSV the last Generate wrote into `results/` — whichever language that run was (2.4 never checks) —
and writes one file where the user chose, in-process through `FrequencyExporter` (2.4 ran no child for them):

- `frequency_list(language, fmt, dest)` — `priority_learning_list.csv` as Migaku JSON, a Yomitan frequency ZIP or a
  plain word list;
- `reading_words(language, fmt, dest)` — `reading_words.csv` (the words you'll read but hardly ever hear), the same
  three formats;
- `sentence_list(language, dest)` — `priority_learning_list.csv` as the Anki sentence CSV, after 2.4's warning.

Each returns an `Outcome`: `kind` "done" (`path`, `count` entries written) · "no data" (Generate first) · "failed"
(the file couldn't be written) · "cancelled"; `message` is 2.4's own words for it. What each asks before it runs is
data (`NEEDS`, the format labels, the warning) so a Qt row can show it; the Tk dashboard's dialogs read the same words.
"""
import csv
import json
import os
import zipfile
from collections import namedtuple

Outcome = namedtuple("Outcome", "kind path count message")

FORMATS = ("migaku", "yomitan", "txt")
FORMAT_LABELS = {"migaku": "Migaku", "yomitan": "Yomichan / Yomitan", "txt": "Word List (Text)"}
FORMAT_TIPS = {"migaku": "Export as a JSON array (Standard Migaku Format).",
               "yomitan": "Export as a frequency dict ZIP file (v3 format).",
               "txt": "Export as a plain text file (one word per line)."}
FORMAT_QUESTION = "Which format would you like to create?"

# What each export needs from the user before it runs: a format (one of FORMATS), a confirmed warning, a destination.
NEEDS = {
    "frequency_list": ("format", "dest"),
    "reading_words": ("format", "dest"),
    "sentence_list": ("confirm", "dest"),
}
SOURCES = {
    "frequency_list": "priority_learning_list.csv",
    "reading_words": "reading_words.csv",
    "sentence_list": "priority_learning_list.csv",
}
INITIAL_NAMES = {
    "frequency_list": "MY Immersion FreqList",
    "reading_words": "Surasura Reading Words",
    "sentence_list": "Anki_Sentence_List",
}
_NO_ANALYSIS = "You need to run an analysis first to generate data."
EMPTY = {
    "frequency_list": _NO_ANALYSIS,
    "reading_words": ("Generate your Vocab Journey first — the reading-words list is built "
                      "during analysis.\n\nIf you have already run one, then no read-only "
                      "words were found yet, which usually means there isn't enough content "
                      "for the comparison to be confident."),
    "sentence_list": _NO_ANALYSIS,
}

SENTENCE_WARNING_TITLE = "Anki Export Warning"
SENTENCE_WARNING = (
    "WARNING: You will learn words faster with higher retention practice "
    "if you mine directly from the スラスラ list. You can see multiple "
    "examples and mine with Yomitan / Migaku.\n\n"
    "FORMAT: This will generate a list to import into Anki / SRS software. "
    "Columns included: Index, Word, Reading, Main Sentence, Second Sentence, Tier, Sources.\n\n"
    "Are you sure you want to do this?"
)
SENTENCE_CONFIRM = "I understand"
SENTENCE_UNCONFIRMED = "Please check the box to confirm you understand."
SENTENCE_BUTTON = "Generate Sentence List"

TITLES = {"done": "Success", "no data": "No Data", "failed": "Error"}
SUCCESS = "List generated successfully!\n\nSaved to: {path}"
FAILED = "Failed to export:\n{error}"

_FILES = {"migaku": (".json", "JSON Files"), "yomitan": (".zip", "Zip Files"),
          "txt": (".txt", "Text Files"), "anki": (".csv", "CSV Files")}


def csv_has_data_rows(path):
    """True if `path` is a CSV holding at least one row BELOW the header.

    File size can't answer this. The analyzer writes the reading-words header unconditionally, so a
    library with no read-only words leaves a small file that exists and is non-empty — a size check
    passed it, the format picker opened, and the user only learned there was nothing to export when
    the exporter failed with its own generic message. The explanation written for exactly that case
    was unreachable.

    Short-circuits on the first data row, so a multi-megabyte priority list costs one line.
    A missing or unreadable file is reported as "no data" rather than raised: this only gates a
    warning dialog, and the exporters validate their input again anyway.

    Module-level rather than a method on purpose: the export dialog is exercised with a MagicMock
    `self`, whose every attribute is a truthy Mock, so a `self.`-qualified check would be silently
    faked and the guard would never fire (see docs/agent instructions/testing.md §5.3).
    """
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            next(reader, None)                                   # header
            return any(any(cell.strip() for cell in row) for row in reader)
    except (OSError, UnicodeDecodeError, csv.Error):
        return False


def source(export):
    """The `results/` CSV an export reads."""
    from app.path_utils import get_user_file
    return os.path.join(get_user_file("results"), SOURCES[export])


def ready(export):
    """None when `export` has something to export, else its "no data" Outcome (2.4's check before any dialog).
    The sentence list asks only for a non-empty file, as 2.4 did: a header-only list passes, and the exporter
    refuses it ("failed")."""
    path = source(export)
    if export == "sentence_list":
        has = os.path.exists(path) and os.path.getsize(path) > 0
    else:
        has = csv_has_data_rows(path)
    return None if has else Outcome("no data", None, 0, EMPTY[export])


def save_as(fmt, initial_name=INITIAL_NAMES["frequency_list"]):
    """2.4's Save-as for a format: (extension, file types, suggested file name, title). The sentence list's name is
    always its own."""
    ext, label = _FILES[fmt]
    if fmt == "anki":
        initial_name = INITIAL_NAMES["sentence_list"]
    return ext, [(label, f"*{ext}")], f"{initial_name}{ext}", f"Save {fmt.capitalize()} List"


def frequency_list(language, fmt, dest, progress=None, cancel=None):
    """Export Freq List: the priority list as `fmt` (one of FORMATS) at `dest`."""
    return _export("frequency_list", fmt, language, dest, progress, cancel)


def reading_words(language, fmt, dest, progress=None, cancel=None):
    """Export Reading Words: the reading-only words as `fmt` (one of FORMATS) at `dest`."""
    return _export("reading_words", fmt, language, dest, progress, cancel)


def sentence_list(language, dest, progress=None, cancel=None):
    """Generate Sentence List: the Anki sentence CSV at `dest` (the caller has had SENTENCE_WARNING confirmed)."""
    return _export("sentence_list", "anki", language, dest, progress, cancel)


def _export(export, fmt, language, dest, progress, cancel):
    if fmt not in (("anki",) if export == "sentence_list" else FORMATS):
        raise ValueError(f"{export} has no format {fmt!r}")
    not_ready = ready(export)
    if not_ready is not None:
        return not_ready
    if cancel is not None and cancel():
        return Outcome("cancelled", None, 0, "")
    return write(fmt, source(export), dest, language=language, progress=progress)


def write(fmt, csv_path, dest, language=None, progress=None):
    """`csv_path` written as `fmt` ("migaku" · "yomitan" · "txt" · "anki") at `dest` — 2.4's one writer, shared by
    the Tk dashboard's dialogs. `language` names the Yomitan dictionary's language. `progress(done, total)`."""
    from app.frequency_exporter import FrequencyExporter
    if progress is not None:
        progress(0, 1)
    try:
        if fmt == "migaku":
            FrequencyExporter.export_migaku(csv_path, dest)
        elif fmt == "yomitan":
            FrequencyExporter.export_yomitan(csv_path, dest, language=language)
        elif fmt == "txt":
            FrequencyExporter.export_word_list(csv_path, dest)
        elif fmt == "anki":
            FrequencyExporter.export_anki_sentences(csv_path, dest)
        else:
            raise ValueError(f"no export format {fmt!r}")
    except Exception as e:
        return Outcome("failed", None, 0, FAILED.format(error=e))
    if progress is not None:
        progress(1, 1)
    return Outcome("done", dest, _count(fmt, dest), SUCCESS.format(path=dest))


def _count(fmt, path):
    """How many entries the written file holds (None if it can't be read back — the export itself succeeded)."""
    try:
        if fmt == "migaku":
            with open(path, encoding="utf-8") as f:
                return len(json.load(f))
        if fmt == "yomitan":
            with zipfile.ZipFile(path) as zf:
                return len(json.loads(zf.read("term_meta_bank_1.json")))
        if fmt == "txt":
            with open(path, encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        with open(path, encoding="utf-8-sig", newline="") as f:
            return sum(1 for _ in csv.DictReader(f))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, csv.Error):
        return None
