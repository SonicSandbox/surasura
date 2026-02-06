#!/usr/bin/env python3
"""
Migaku Database to JSON Converter
Converts the extracted SQLite database to JSON format
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
import sys

def get_backup_path(base_path):
    """Generate a backup path like KnownWord_old_1.json"""
    path = Path(base_path)
    if not path.exists():
        return None
    
    i = 1
    while True:
        backup_path = path.parent / f"{path.stem}_old_{i}{path.suffix}"
        if not backup_path.exists():
            return backup_path
        i += 1

def convert_db_to_json(db_path, output_json=None):
    """Convert Migaku SQLite database to JSON and text formats"""

    print(f"Opening database: {db_path}")

    # Default output path
    if output_json is None:
        # Try to find 'User Files' directory relative to the script
        script_parent = Path(__file__).resolve().parent.parent
        user_files_dir = script_parent / "User Files"
        
        if not user_files_dir.exists():
            print(f"Creating missing directory: {user_files_dir}")
            user_files_dir.mkdir(parents=True, exist_ok=True)
            
        output_json = user_files_dir / "KnownWord.json"
    else:
        output_json = Path(output_json)

    # Backup existing file
    if output_json.exists():
        backup_path = get_backup_path(output_json)
        if backup_path:
            print(f"Backing up existing file to: {backup_path.name}")
            output_json.rename(backup_path)

    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query WordList table
        print("Querying WordList table...")
        cursor.execute("""
            SELECT
                dictForm, secondary, partOfSpeech, language,
                knownStatus, hasCard, tracked, created, mod, isModern
            FROM WordList
            WHERE del = 0
            ORDER BY created DESC
        """)

        # Status mapping
        STATUS_MAP = {
            0: "UNKNOWN",
            1: "KNOWN",
            2: "IGNORED",
            3: "LEARNING"
        }

        # Convert to list of dictionaries
        words = []
        debug_count = 0
        warning_shown = False
        
        for row in cursor.fetchall():
            status_raw = row['knownStatus']
            
            # Debug: Print raw status for first 5 rows
            if debug_count < 5:
                print(f"DEBUG Row {debug_count}: knownStatus={status_raw} (type: {type(status_raw)})")
                debug_count += 1
            
            final_status = "UNKNOWN"
            
            # Handle different types
            if isinstance(status_raw, int):
                final_status = STATUS_MAP.get(status_raw, "UNKNOWN")
            elif isinstance(status_raw, str):
                # Check if it's already a valid status string
                if status_raw in ["KNOWN", "UNKNOWN", "IGNORED", "LEARNING"]:
                    final_status = status_raw
                # Check if it's a digit string like "1"
                elif status_raw.isdigit():
                    final_status = STATUS_MAP.get(int(status_raw), "UNKNOWN")
                else:
                    # Fallback for unknown strings
                    if not warning_shown:
                        print(f"Warning: Unexpected status string '{status_raw}' found. Defaulting to UNKNOWN. (This warning is shown only once)")
                        warning_shown = True
                    final_status = "UNKNOWN"
            else:
                if not warning_shown:
                    print(f"Warning: Unexpected status type {type(status_raw)} for '{status_raw}'. Defaulting to UNKNOWN. (This warning is shown only once)")
                    warning_shown = True
                final_status = "UNKNOWN"

            words.append({
                'dictForm': row['dictForm'],
                'secondary': row['secondary'],
                'partOfSpeech': row['partOfSpeech'],
                'language': row['language'],
                'knownStatus': final_status,
                'hasCard': row['hasCard'],
                'tracked': row['tracked'],
                'created': row['created'],
                'mod': row['mod'],
                'isModern': row['isModern']
            })

        print(f"✓ Found {len(words)} words")

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
        if isinstance(languages_list, list):
            languages_str = ", ".join([str(l) for l in languages_list])
        else:
            languages_str = str(languages_list)
        print(f"  Languages: {languages_str}")

        print(f"\nWriting JSON to: {output_json}")
        json_data = {
            'exportDate': datetime.now().isoformat(),
            'databaseFile': str(db_path),
            'statistics': stats,
            'words': words
        }

        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        print(f"JSON exported: {output_json}")

        conn.close()
        print("\nConversion complete!")
        return True

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert-db-to-json.py <database-file.db> [output.json]")
        print("\nExample:")
        print("  python convert-db-to-json.py migaku-dictionary-OSgSaZn1apXewxVFrtNW6VTCK6r1.db")
        sys.exit(1)

    db_file = sys.argv[1]
    output_json = sys.argv[2] if len(sys.argv) > 2 else None

    if not Path(db_file).exists():
        print(f"Error: File not found: {db_file}")
        sys.exit(1)

    success = convert_db_to_json(db_file, output_json)
    sys.exit(0 if success else 1)
