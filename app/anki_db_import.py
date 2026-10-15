"""The .apkg known-words import (W3.4 row 2): every word in one field of an exported Anki deck becomes a known word.

Qt-free and Tk-free, beside the engine. The window (`app/qt/importers.py`) reads the deck's fields and a few notes on a
worker (`read_deck`); the import itself — the tokenizing, CPU work — runs in a child, `app_entry.py apkg_known_import
--language L --file F --field N` (`main`, headless and dialog-free, its exit code the result), as a `known-import`
job. The merge (`merge_known`) is the Tk window's `update_known_words` (`app/anki_db_importer_gui.py`, left as it is)
with the data-safety floor raised:

  * KnownWord.json's lock (`anki_sync.hold_known_words`) is held from the read to the write, **waited for** (this runs
    in a child, never on a window's thread: the Tk window's `wait=0` refused whenever a sync was mid-write); a lock
    another program keeps refuses and writes nothing;
  * a file that can't be read or isn't a recognised list is never replaced;
  * the existing list is kept whole and in order (first entry per key wins); a word still being learned is raised to
    KNOWN, an IGNORED word stays ignored; other top-level keys are kept;
  * a **dated backup first** (`path_utils.backup_to_trash`; none made: nothing written), then a temp file, **fsync**
    and an atomic replace (`anki_sync._atomic_write_json`); nothing new to add or raise: nothing written at all.

Entries are keyed by (lemma, tokenizer reading), as the Tk window keyed them (the sync writes an empty `secondary`:
IK-19, for the lead).
"""
import json
import os
import sys
from collections import namedtuple
from datetime import datetime

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import backup_to_trash, get_user_files_path, read_text

# The field picked first when a deck has it (the Tk window's order), else the deck's first field.
FIELD_PREFERENCE = ("Sentence", "Expression", "Word", "Front", "Text")
SAMPLE_NOTES = 5
RESULT_MARK = "RESULT "            # the child's last line: what it did, as JSON (the window's result line)
EXIT_DONE, EXIT_FAILED, EXIT_BUSY = 0, 1, 5

Deck = namedtuple("Deck", "fields notes samples default")
Merge = namedtuple("Merge", "added raised total backup error busy")


def pick_field(fields, prefer=FIELD_PREFERENCE):
    """The field chosen for the user at first: the first of `prefer` the deck has, else its first field, else None."""
    for name in prefer:
        if name in fields:
            return name
    return fields[0] if fields else None


def read_deck(path, sample=SAMPLE_NOTES, prefer=FIELD_PREFERENCE):
    """The deck at `path`: its fields (only those its notes use), how many notes it holds, the first `sample` notes'
    text of each field (the preview) and the field chosen first. Its temporary copy is removed before this returns.
    Raises whatever the deck's read raises (the window says it). A worker's call: it unzips and reads SQLite."""
    from app.anki_utils import cleanup_temp_dir, extract_field_text, load_anki_data
    fields, notes, model_map, temp_dir = load_anki_data(path)
    try:
        samples = {f: extract_field_text(notes[:sample], model_map, f) for f in fields}
    finally:
        cleanup_temp_dir(temp_dir)
    return Deck(fields, len(notes), samples, pick_field(fields, prefer))


def words_of(path, field, language):
    """Every (lemma, reading) the tokenizer finds in `field` of every note in the deck at `path` — CPU work: the
    child's. Its temporary copy is removed before this returns."""
    from app.anki_utils import cleanup_temp_dir, extract_field_text, load_anki_data
    from app.analyzer import ChineseTokenizer, JapaneseTokenizer
    _fields, notes, model_map, temp_dir = load_anki_data(path)
    try:
        full_text = extract_field_text(notes, model_map, field)
    finally:
        cleanup_temp_dir(temp_dir)
    tokenizer = JapaneseTokenizer() if language == 'ja' else ChineseTokenizer()
    unique_words = set()
    for lemma, reading, _surface, _orth in tokenizer.tokenize(full_text):
        if not lemma.strip():
            continue
        unique_words.add((lemma, reading))
    return unique_words


def known_path(language):
    return os.path.join(get_user_files_path(language), "KnownWord.json")


def merge_known(language, pairs, wait=None):
    """Add `pairs` ((lemma, reading)s) to KnownWord.json as known words, holding its lock (waiting up to `wait` s,
    the sync's wait by default) -> Merge(added, raised, total, backup, error, busy). `error` set: nothing written."""
    from app.anki_sync import hold_known_words
    held, refused = hold_known_words(language, "Anki import", wait=wait)
    if refused is not None:
        return Merge(0, 0, 0, None, refused[0], True)
    try:
        return _merge_held(language, pairs)
    finally:
        if held is not None:
            held.release()


def _merge_held(language, pairs):
    output_json = known_path(language)
    existing_data = {"words": [], "statistics": {}}
    if os.path.exists(output_json):
        # A file we cannot parse must never be replaced by an Anki-only list. Its own encoding (a BOM, UTF-16,
        # CP932 / GBK), strictly: the file is written back.
        try:
            existing_data = json.loads(read_text(output_json, language, errors="strict"))
        except Exception as e:
            return Merge(0, 0, 0, None, f"Your known words file could not be read, so nothing was changed ({e}).",
                         False)

    # Handle both list and dict formats for backward compat
    if isinstance(existing_data, list):
        existing_words = existing_data
        existing_data = {"words": existing_words, "statistics": {}}
    elif isinstance(existing_data, dict) and isinstance(existing_data.get("words", []), list):
        existing_words = existing_data.get("words", [])
    else:
        return Merge(0, 0, 0, None, "Your known words file is not in a format Surasura recognises, so nothing was "
                                    "changed.", False)

    # Map for quick lookup; the existing list itself is kept whole and in order (first entry per key wins)
    word_map = {}
    for w in existing_words:
        if isinstance(w, dict):
            word_map.setdefault((w.get('dictForm'), w.get('secondary', '')), w)
    updated_words = list(existing_words)

    now_str = datetime.now().isoformat()
    added = raised = 0
    for lemma, reading in sorted(pairs):
        key = (lemma, reading)
        if key in word_map:
            # Only upgrade words still being learned; an IGNORED word stays ignored
            if word_map[key].get('knownStatus') in ("LEARNING", "UNKNOWN"):
                word_map[key]['knownStatus'] = "KNOWN"
                raised += 1
        else:
            word_map[key] = {
                'dictForm': lemma,
                'secondary': reading,
                'partOfSpeech': '',
                'language': language,
                'knownStatus': "KNOWN",
                'hasCard': 1,  # Since it came from Anki
                'tracked': 0,
                'created': now_str,
                'mod': now_str,
                'isModern': 1
            }
            updated_words.append(word_map[key])
            added += 1
    if not added and not raised:
        return Merge(0, 0, len(updated_words), None, None, False)     # nothing new: the file is left as it is

    stats = {
        'totalWords': len(updated_words),
        'knownWords': sum(1 for w in updated_words if isinstance(w, dict) and w.get('knownStatus') == "KNOWN"),
        'learningWords': sum(1 for w in updated_words if isinstance(w, dict) and w.get('knownStatus') == "LEARNING"),
        'unknownWords': sum(1 for w in updated_words if isinstance(w, dict) and w.get('knownStatus') == "UNKNOWN"),
        'ignoredWords': sum(1 for w in updated_words if isinstance(w, dict) and w.get('knownStatus') == "IGNORED"),
        'languages': sorted(set(str(w.get('language', language)) for w in updated_words if isinstance(w, dict)))
    }
    # Keep every other top-level key (e.g. Migaku's databaseFile) instead of rewriting the header
    json_data = dict(existing_data)
    json_data['exportDate'] = now_str
    json_data.setdefault('source', 'Anki Extraction')
    json_data['statistics'] = stats
    json_data['words'] = updated_words

    # A dated copy of the file this replaces first (CLAUDE.md §4): none made, nothing written.
    try:
        backup = backup_to_trash(output_json)
    except OSError as e:
        return Merge(0, 0, 0, None, f"Your known words could not be backed up, so nothing was changed ({e}).", False)
    from app.anki_sync import _atomic_write_json
    try:
        _atomic_write_json(output_json, json_data)        # temp + fsync + replace: a reader sees old or new
    except OSError as e:
        return Merge(0, 0, 0, backup, f"Your known words could not be saved, so nothing was changed ({e}).", False)
    return Merge(added, raised, len(updated_words), backup, None, False)


def result_line(merge):
    """The child's last line: the merge as JSON after RESULT_MARK (the window's `parse_result`)."""
    return RESULT_MARK + json.dumps({"added": merge.added, "raised": merge.raised, "total": merge.total,
                                     "backup": os.path.basename(merge.backup) if merge.backup else None},
                                    ensure_ascii=False)


def parse_result(line):
    """A child's line -> the dict `result_line` wrote, or None for any other line."""
    if not line.startswith(RESULT_MARK):
        return None
    try:
        value = json.loads(line[len(RESULT_MARK):])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def main(argv=None):
    """`apkg_known_import --language L --file F --field N`: read, tokenize, merge. Headless; prints what it does
    (never a dialog). Exit 0 done (its RESULT line last), 5 the known words held by another program, 1 failed."""
    import argparse
    parser = argparse.ArgumentParser(description="Add the words of an Anki deck's field to your known words")
    parser.add_argument("--language", default="ja", choices=("ja", "zh"))
    parser.add_argument("--file", required=True, help="The exported deck (.apkg)")
    parser.add_argument("--field", required=True, help="The field whose words become known words")
    args = parser.parse_args(argv)
    try:
        print(f"Reading {os.path.basename(args.file)}")
        pairs = words_of(args.file, args.field, args.language)
        print(f"Found {len(pairs)} words in '{args.field}'")
        merge = merge_known(args.language, pairs)
    except Exception as e:
        print(f"Error: the deck could not be read, so nothing was changed ({e}).")
        return EXIT_FAILED
    if merge.error:
        print(f"Error: {merge.error}")
        return EXIT_BUSY if merge.busy else EXIT_FAILED
    print(result_line(merge))
    return EXIT_DONE


if __name__ == "__main__":
    sys.exit(main())
