import glob
import os
import sqlite3
import json
from datetime import datetime
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.anki_sync import EXIT_CHANGED, NumbersChanged, parse_expect
from app.path_utils import get_user_file, get_user_files_path, backup_to_trash

# The browser console line that downloads Migaku's database (the importer's step 1: without it there is no .db).
CONSOLE_CODE = "await coreApi.Database_downloadAsFile({})"
# "Find it for me" looks at this many of the newest .db files in Downloads.
DOWNLOADS_LOOK = 3


class NotMigaku(Exception):
    """The file has no WordList table: not a Migaku export."""


def is_migaku_db(db_path):
    """Whether `db_path` holds Migaku's WordList table (read only; never raises). Moved from the Tk window's
    `is_valid_migaku_db`."""
    for target, uri in ((f"file:{os.path.abspath(db_path)}?mode=ro", True), (db_path, False)):
        conn = None
        try:
            conn = sqlite3.connect(target, uri=uri)
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='WordList'").fetchone()
            return row is not None
        except Exception:
            continue
        finally:
            if conn is not None:
                conn.close()
    return False


def find_export(folder=None, look=DOWNLOADS_LOOK):
    """The newest Migaku export among the `look` newest `.db` files in `folder` (the user's Downloads) -> (its path or
    None, how many .db files the folder holds). Moved from the Tk window's `scan_downloads`."""
    folder = folder or os.path.join(os.path.expanduser("~"), "Downloads")
    found = glob.glob(os.path.join(folder, "*.db"))
    for path in sorted(found, key=os.path.getmtime, reverse=True)[:look]:
        if is_migaku_db(path):
            return path, len(found)
    return None, len(found)


def read_words(db_path, language=None):
    """The WordList's rows (only `language`'s when given) as KnownWord.json entries. Raises NotMigaku when the
    file has no WordList table, sqlite3.Error when it can't be read. The connection is always closed."""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Migaku export databases typically have a 'WordList' table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='WordList'")
        if not cursor.fetchone():
            raise NotMigaku("Table 'WordList' not found in database.")

        if language:
            cursor.execute("SELECT * FROM WordList WHERE language=?", (language,))
        else:
            cursor.execute("SELECT * FROM WordList")
        rows = cursor.fetchall()

        words = []
        for row in rows:
            # Tolerate schema drift between Migaku export versions: a plain dict lets a missing
            # column default to None instead of raising IndexError on row['<missing>'].
            rowd = {k: row[k] for k in row.keys()}
            # Map Migaku internal status to simple KNOWN/UNKNOWN/IGNORED/LEARNING
            status = rowd.get('knownStatus')
            final_status = "UNKNOWN"

            if status == "KNOWN":
                final_status = "KNOWN"
            elif status == "LEARNING":
                final_status = "LEARNING"
            elif status == "IGNORED":
                final_status = "IGNORED"

            words.append({
                'dictForm': rowd.get('dictForm'),
                'secondary': rowd.get('secondary'),
                'partOfSpeech': rowd.get('partOfSpeech'),
                'language': rowd.get('language'),
                'knownStatus': final_status,
                'hasCard': rowd.get('hasCard'),
                'tracked': rowd.get('tracked'),
                'created': rowd.get('created'),
                'mod': rowd.get('mod'),
                'isModern': rowd.get('isModern')
            })
        return words
    finally:
        conn.close()


def convert_db_to_json(db_path, output_json=None, language=None, expect=None):
    """Replace KnownWord.json with the export's words, holding its lock: refused when the file can't be read, a dated
    backup first, past Graduates' words kept (the dismissed words this export doesn't name dropped), written
    atomically. -> True when written. `expect`: the numbers the user confirmed; moved by now, nothing is written and
    `anki_sync.NumbersChanged` is raised."""
    if not output_json:
        # Save to User Files/<lang>/KnownWord.json
        user_files_dir = get_user_files_path(language)
        output_json = os.path.join(user_files_dir, "KnownWord.json")


    try:
        print(f"Opening database: {db_path}")
        if language:
            print(f"Filtering words for language: {language}")
        try:
            words = read_words(db_path, language)
        except NotMigaku as e:
            print(f"Error: {e}")
            return False

        print(f"Found {len(words)} words")

        # Calculate statistics
        stats = {
            'totalWords': len(words),
            'knownWords': sum(1 for w in words if w['knownStatus'] == "KNOWN"),
            'unknownWords': sum(1 for w in words if w['knownStatus'] == "UNKNOWN"),
            'ignoredWords': sum(1 for w in words if w['knownStatus'] == "IGNORED"),
            'learningWords': sum(1 for w in words if w['knownStatus'] == "LEARNING"),
            'languages': sorted(list(set(w['language'] for w in words)))
        }

        print("\nStatistics:")
        print(f"  Total Words: {stats['totalWords']}")
        print(f"  Known Words: {stats['knownWords']}")
        print(f"  Learning Words: {stats['learningWords']}")
        print(f"  Unknown Words: {stats['unknownWords']}")
        print(f"  Ignored Words: {stats['ignoredWords']}")

        languages_list = stats.get('languages', [])
        languages_str = ", ".join([str(l) for l in languages_list])
        print(f"  Languages: {languages_str}")

        # An import that found nothing (no rows for this language, say) must never wipe the known
        # words already there — the backup below would keep them, but the list would still be empty.
        if not words and os.path.exists(output_json) and os.path.getsize(output_json) > 0:
            print("Error: the database has no words for this language, so your existing known "
                  "words were left unchanged.")
            return False

        # KnownWord.json is replaced holding its lock (P0.3 04 §2): never beside the Anki sync's or surasura-cli's write.
        from app.anki_sync import hold_known_words
        lock_language = language or os.path.basename(os.path.dirname(os.path.abspath(output_json)))
        held, refused = hold_known_words(lock_language, "Migaku import")
        if refused is not None:
            print(f"Error: {refused[0]}")
            return False
        try:
            # A file that exists but can't be read is never replaced: what it keeps can't be kept (AD2-1).
            from app.anki_sync import known_file_refusal
            unreadable = known_file_refusal(lock_language, output_json)
            if unreadable:
                print(f"Error: {unreadable}")
                return False
            from app.anki_sync import check_numbers
            check_numbers(lock_language, words, output_json, expect)
            # This import REPLACES the file. Keep a dated copy of what it replaces first
            # (User Files/<lang>/.trash/KnownWord.<YYYYmmdd-HHMMSS>.json); no copy, no overwrite.
            try:
                backup = backup_to_trash(output_json)
            except OSError as e:
                print(f"Error: could not back up your current known words, so nothing was changed ({e}).")
                return False
            if backup:
                print(f"Backed up your previous known words to: {backup}")

            # The words the old GraduatedList.txt gave the file stay known words (S3.1 D13); nothing else of the old
            # file stays (a clean slate from Migaku: dismissed words it doesn't name are dropped, the backup keeps them).
            from app.anki_sync import replaced_words
            words, graduated, _dropped = replaced_words(output_json, lock_language, words)
            stats['totalWords'] += graduated
            stats['knownWords'] += graduated

            print(f"\nWriting JSON to: {output_json}")
            json_data = {
                'exportDate': datetime.now().isoformat(),
                'databaseFile': str(db_path),
                'statistics': stats,
                'words': words
            }

            out_dir = os.path.dirname(output_json)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            # Atomically (temp + fsync + replace): a reader never sees half a file, a kill leaves old or new.
            from app.anki_sync import _atomic_write_json
            _atomic_write_json(output_json, json_data)
        finally:
            if held is not None:
                held.release()
        print(f"JSON exported: {output_json}")

        print("\nConversion complete!")
        return True

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return False
    except NumbersChanged:
        raise
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migaku DB to JSON Converter")
    parser.add_argument("db_file", help="Path to Migaku .db file")
    parser.add_argument("out_file", nargs='?', help="Optional output JSON path")
    parser.add_argument("--language", help="Optional language filter (e.g., ja, zh)")
    parser.add_argument("--expect", default=None,
                        help="The numbers the user confirmed (now,after,graduated,ignored); moved by then, nothing is "
                             "replaced and the exit code is 4")

    args = parser.parse_args()
    try:
        ok = convert_db_to_json(args.db_file, args.out_file, args.language, parse_expect(args.expect))
    except NumbersChanged as e:
        print(f"Error: {e}")
        sys.exit(EXIT_CHANGED)
    # The importer window reads the exit code to choose between "Success" and "Error"; returning
    # normally on a failure made it announce success for an import that wrote nothing.
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
