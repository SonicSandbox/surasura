import os
import sqlite3
import json
from datetime import datetime
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file

def convert_db_to_json(db_path, output_json=None):
    if not output_json:
        output_json = get_user_file("User Files/KnownWord.json")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        print(f"Opening database: {db_path}")

        # Migaku export databases typically have a 'WordList' table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='WordList'")
        if not cursor.fetchone():
            print("Error: Table 'WordList' not found in database.")
            conn.close()
            return False

        cursor.execute("SELECT * FROM WordList")
        rows = cursor.fetchall()

        words = []
        for row in rows:
            # Map Migaku internal status to simple KNOWN/UNKNOWN/IGNORED/LEARNING
            status = row['knownStatus']
            final_status = "UNKNOWN"
            
            if status == "KNOWN":
                final_status = "KNOWN"
            elif status == "LEARNING":
                final_status = "LEARNING"
            elif status == "IGNORED":
                final_status = "IGNORED"

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

def main():
    if len(sys.argv) < 2:
        print("Usage: python migaku_converter.py <database-file.db> [output.json]")
        return
    
    db_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else None
    convert_db_to_json(db_file, out_file)

if __name__ == "__main__":
    main()
