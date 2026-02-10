import os
import sqlite3
import json
from datetime import datetime
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, get_user_files_path

def convert_db_to_json(db_path, output_json=None, language=None):
    if not output_json:
        # Save to User Files/<lang>/KnownWord.json
        user_files_dir = get_user_files_path(language)
        output_json = os.path.join(user_files_dir, "KnownWord.json")


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

        if language:
            print(f"Filtering words for language: {language}")
            cursor.execute("SELECT * FROM WordList WHERE language=?", (language,))
        else:
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
    import argparse
    parser = argparse.ArgumentParser(description="Migaku DB to JSON Converter")
    parser.add_argument("db_file", help="Path to Migaku .db file")
    parser.add_argument("out_file", nargs='?', help="Optional output JSON path")
    parser.add_argument("--language", help="Optional language filter (e.g., ja, zh)")
    
    args = parser.parse_args()
    convert_db_to_json(args.db_file, args.out_file, args.language)

if __name__ == "__main__":
    main()
