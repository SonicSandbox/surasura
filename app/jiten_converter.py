import json
from datetime import datetime
import sys
import os
import requests

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, get_user_files_path, backup_to_trash

# The key reaches this process through its environment, never its command line: app_entry logs every
# argv to debug/app_debug_log.txt, and a command line is visible to other programs on the machine.
API_KEY_ENV = "SURASURA_JITEN_API_KEY"

def fetch_jiten_vocabulary(api_key, output_json=None, language='ja'):
    if not output_json:
        user_files_dir = get_user_files_path(language)
        output_json = os.path.join(user_files_dir, "KnownWord.json")

    try:
        print(f"Fetching vocabulary from Jiten API...")
        
        # Jiten API endpoint
        api_url = "https://api.jiten.moe/api/user/vocabulary/cards"
        headers = {"Authorization": f"ApiKey {api_key}"}
        
        # Make the request
        response = requests.get(api_url, headers=headers, timeout=30)
        
        if response.status_code == 401:
            print("Error: Invalid API key. Please check your API key and try again.")
            return False
        elif response.status_code != 200:
            print(f"Error: API returned status {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        cards = response.json()
        
        if not isinstance(cards, list):
            print("Error: Unexpected API response format.")
            return False
        
        print(f"Retrieved {len(cards)} cards from Jiten API")
        
        # Map Jiten card states to our status format
        # State meanings (inferred from typical SRS systems):
        # 0-4: Learning states
        # 5+: Learned/Known states
        def map_state_to_status(state):
            if state is None:
                return "UNKNOWN"
            elif state >= 5:
                return "KNOWN"
            else:
                return "LEARNING"
        
        # Convert Jiten cards into Migaku-like JSON schema so analyzer and other tools
        # that expect Migaku exports can consume the result.
        words = []
        for card in cards:
            word_text = card.get('wordText', '').strip()
            if not word_text:
                continue

            state = card.get('state')
            status = map_state_to_status(state)

            # Determine hasCard flag (Migaku uses hasCard)
            has_card = 1 if card.get('cardId') else 0

            words.append({
                # Migaku-compatible fields
                'dictForm': word_text,
                'secondary': card.get('reading', '') or card.get('furigana', '') or '',
                'partOfSpeech': card.get('partOfSpeech', ''),
                'language': 'ja',
                'knownStatus': status,
                'hasCard': has_card,
                'tracked': 0,
                'created': card.get('created') or card.get('lastReview'),
                'mod': card.get('lastReview'),
                'isModern': 1,

                # Original Jiten metadata retained for reference
                'wordId': card.get('wordId'),
                'cardId': card.get('cardId'),
                'frequencyRank': card.get('frequencyRank'),
                'readingType': card.get('readingType'),
                'lastReview': card.get('lastReview'),
                'due': card.get('due'),
                'state': state
            })
        
        print(f"Processed {len(words)} words")
        
        # Calculate statistics
        stats = {
            'totalWords': len(words),
            'knownWords': sum(1 for w in words if w.get('knownStatus') == "KNOWN"),
            'learningWords': sum(1 for w in words if w.get('knownStatus') == "LEARNING"),
            'unknownWords': sum(1 for w in words if w.get('knownStatus') == "UNKNOWN"),
            'ignoredWords': sum(1 for w in words if w.get('knownStatus') == "IGNORED"),
            'languages': sorted(list(set(w.get('language', '') for w in words)))
        }
        
        print("\nStatistics:")
        print(f"  Total Words: {stats['totalWords']}")
        print(f"  Known Words: {stats['knownWords']}")
        print(f"  Learning Words: {stats['learningWords']}")
        print(f"  Unknown Words: {stats['unknownWords']}")
        
        # An import that found nothing must never wipe the known words already there — the backup
        # below would keep them, but the list would still be empty.
        if not words and os.path.exists(output_json) and os.path.getsize(output_json) > 0:
            print("Error: Jiten returned no words, so your existing known words were left unchanged.")
            return False

        # This import REPLACES the file. Keep a dated copy of what it replaces first
        # (User Files/<lang>/.trash/KnownWord.<YYYYmmdd-HHMMSS>.json); no copy, no overwrite.
        try:
            backup = backup_to_trash(output_json)
        except OSError as e:
            print(f"Error: could not back up your current known words, so nothing was changed ({e}).")
            return False
        if backup:
            print(f"Backed up your previous known words to: {backup}")

        print(f"\nWriting JSON to: {output_json}")

        json_data = {
            'exportDate': datetime.now().isoformat(),
            'source': 'Jiten API',
            'statistics': stats,
            'words': words
        }
        
        out_dir = os.path.dirname(output_json)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        print(f"JSON exported: {output_json}")
        print("\nConversion complete!")
        return True
        
    except requests.exceptions.Timeout:
        print("Error: Request timed out. Please check your internet connection.")
        return False
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to Jiten API. Please check your internet connection.")
        return False
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return False
    except json.JSONDecodeError:
        print("Error: Could not parse API response as JSON.")
        return False
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Jiten API Importer")
    parser.add_argument("api_key", nargs='?',
                        help=f"Jiten API Key (default: the {API_KEY_ENV} environment variable)")
    parser.add_argument("out_file", nargs='?', help="Optional output JSON path")
    parser.add_argument("--language", default='ja', help="Target language (default: ja)")

    args = parser.parse_args()
    api_key = args.api_key or os.environ.get(API_KEY_ENV)
    if not api_key:
        print("Error: No Jiten API key was given.")
        sys.exit(1)
    ok = fetch_jiten_vocabulary(api_key, args.out_file, args.language)
    # The importer window reads the exit code to choose between "Success" and "Error"; returning
    # normally on a failure (e.g. a rejected key) made it announce success for nothing written.
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
