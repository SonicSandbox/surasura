"""The known-word importers' and Extract's rules, for their Qt windows (W3.4 row 2; `app/qt/importers.py` paints
the answers). Qt-free: what each window's button may do now, the numbers a replacing import's confirmation states (read
before it runs: IK-18), and what a finished child's exit code and lines mean. The Tk windows these replace kept the
same rules inside their classes (`AnkiImporterApp.on_file_change`, `MigakuImporterGUI.scan_downloads` /
`process_file_path`, `JitenImporterGUI.fetch_and_import`, `FileImporterApp.update_btn_state` / `process_import`).
"""
import os
from collections import namedtuple
from datetime import datetime

from app import anki_db_import, extract

# What a replacing import's confirmation states: the file it reads (or the fetched cards), its words, the known words
# now and after, how many past Graduates' words it keeps and how many ignored words it drops (they come back on the
# list); `saved` is the export's time (Migaku's).
Plan = namedtuple("Plan", "path words now after graduated ignored saved")


class KnownUnreadable(Exception):
    """The known-words file exists but can't be read: a replace would write nothing, so nothing is asked (AD2-1)."""


def _refuse_unreadable(language):
    from app import anki_sync
    why = anki_sync.known_file_refusal(language)
    if why:
        raise KnownUnreadable(why)


def is_deck(path):
    return str(path or "").lower().endswith(".apkg")


def default_name(path):
    """The output name Extract fills in for a file when its name field is empty (the file's own name)."""
    return os.path.splitext(os.path.basename(str(path or "")))[0]


def can_import_deck(path, deck, field, busy):
    """The .apkg window's Import: a deck read, one of its fields chosen, nothing running."""
    return bool(is_deck(path) and deck is not None and field and field in deck.fields and not busy)


def can_extract(path, name, field, understood, busy, deck=None):
    """Extract's button: a file and a name; a deck also needs its field and the "I understand" tick."""
    if busy or not path or not str(name or "").strip():
        return False
    if is_deck(path):
        return bool(deck is not None and field and understood)
    return True


def split_value(by_length, value, length):
    """The split's value when its method changes (the Tk window's reset) -> the new value, or None to keep it: by length,
    a pattern gives way to the saved `length`; by pattern, an empty field or a number to the default pattern."""
    if by_length and not value.isdigit():
        return length
    if not by_length and (not value or value.isdigit()):
        return extract.DEFAULT_DELIMITER
    return None


def extract_field(fields):
    """The deck field Extract offers first: Sentence, else Expression, else none (the Tk window chose these two only)."""
    default = anki_db_import.pick_field(fields, ("Sentence", "Expression"))
    return default if default in ("Sentence", "Expression") else None


def error_of(line):
    """A child's printed line -> its words when it says why something failed ("Error: …"), else None."""
    line = (line or "").strip()
    for mark in ("Error: ", "SQLite error: ", "Request error: "):
        if line.startswith(mark):
            return line[len(mark):].strip() or None
    return None


# --- the replacing imports' numbers (read first, then one confirmation: IK-18) --------------------------------------- #
def migaku_plan(db_path, language):
    """Migaku's export at `db_path` read for `language` -> Plan (its replace drops the dismissed words Migaku doesn't
    name, as every replace). Raises `migaku_converter.NotMigaku` when it holds no
    word list, sqlite3.Error when it can't be read, KnownUnreadable when the known words can't be. A worker's call."""
    from app import anki_sync, migaku_converter
    _refuse_unreadable(language)
    words = migaku_converter.read_words(db_path, language)
    now, after, graduated, ignored = anki_sync.replace_numbers(language, words)
    try:
        saved = datetime.fromtimestamp(os.path.getmtime(db_path))
    except OSError:
        saved = None
    return Plan(db_path, len(words), now, after, graduated, ignored, saved)


def find_migaku(folder=None):
    """The newest Migaku export in the user's Downloads -> (its path or None, how many .db files are there)."""
    from app import migaku_converter
    return migaku_converter.find_export(folder)


def jiten_plan(cards_path, language):
    """The cards Jiten's first step kept at `cards_path` -> Plan (None when they can't be read). Raises
    KnownUnreadable when the known words can't be read. A worker's call."""
    from app import anki_sync, jiten_converter
    _refuse_unreadable(language)
    cards = jiten_converter.load_cards(cards_path)
    if cards is None:
        return None
    words = jiten_converter.words_from_cards(cards)
    now, after, graduated, ignored = anki_sync.replace_numbers(language, words)
    return Plan(cards_path, len(words), now, after, graduated, ignored, None)


# --- what a finished child means --------------------------------------------------------------------------------- #
def deck_outcome(code, result, why):
    """The .apkg import's end -> ('done' | 'nothing' | 'failed', values). `result`: its RESULT line's dict."""
    if code == anki_db_import.EXIT_DONE and result is not None:
        if not result.get("added") and not result.get("raised"):
            return "nothing", {}
        return "done", {"added": result.get("added", 0), "raised": result.get("raised", 0),
                        "total": result.get("total", 0)}
    return "failed", {"why": why}


def replace_outcome(code, why):
    """Migaku's or Jiten's replace -> ('done' | 'changed' | 'failed', values): the exit code decides ('changed': the
    known words moved since the confirmation, nothing written — read again and ask again)."""
    from app import anki_sync
    if code == anki_sync.EXIT_CHANGED:
        return "changed", {}
    return ("done", {}) if code == 0 else ("failed", {"why": why})


def expect_arg(plan):
    """The numbers a confirmation stated, as the replace's `--expect` takes them."""
    return f"{plan.now},{plan.after},{plan.graduated},{plan.ignored}"


def extract_outcome(code, result, why):
    """Extract's end -> (key, values): 'done' (in the library), 'processed' (no section asked), 'processed-only' (the
    library didn't take them), 'already' (its parts are in the library already: `title`, SRC K3), 'taken', 'name',
    'empty', or 'failed'."""
    if result is not None:
        values = {"parts": result.parts, "name": result.folder or "", "section": result.section,
                  "title": result.title or ""}
        if result.code == extract.EXIT_DONE:
            return ("done" if result.in_library else "processed"), values
        if result.code == extract.EXIT_PROCESSED_ONLY:
            return ("already" if result.note == "already" else "processed-only"), values
        if result.code == extract.EXIT_REFUSED:
            return ("taken" if result.note == "taken" else "name"), values
        if result.note == "empty":
            return "empty", values
    return "failed", {"why": why}
