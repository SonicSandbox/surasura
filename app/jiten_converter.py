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
# argv to logs/app_debug_log.txt, and a command line is visible to other programs on the machine.
API_KEY_ENV = "SURASURA_JITEN_API_KEY"

# Jiten's words are Japanese: every word is stamped 'ja', so another language's file is never replaced with them
# (W3.4 row 2: refused here, before any fetch, as well as by the window).
LANGUAGE = "ja"
API_URL = "https://api.jiten.moe/api/user/vocabulary/cards"


def _known_json(language, output_json=None):
    return output_json or os.path.join(get_user_files_path(language), "KnownWord.json")


def refuse_language(language):
    """A refusal line when `language` isn't Jiten's (Japanese), else None."""
    if language != LANGUAGE:
        return f"Error: Jiten holds Japanese words only, so nothing was fetched or changed for '{language}'."
    return None


ERROR_BODY = 100                 # characters of an error reply kept for the status line


def fetch_cards(api_key):
    """Jiten's cards for `api_key` -> (cards, None), or (None, the line that says why). Prints its progress; never
    the key."""
    try:
        print(f"Fetching vocabulary from Jiten API...")
        headers = {"Authorization": f"ApiKey {api_key}"}
        response = requests.get(API_URL, headers=headers, timeout=30)
        if response.status_code == 401:
            return None, "Error: Invalid API key. Please check your API key and try again."
        elif response.status_code != 200:
            said = " ".join(str(response.text or "").split())[:ERROR_BODY]   # one short line: never a whole page
            return None, f"Error: API returned status {response.status_code}" + (f" ({said})" if said else "")
        cards = response.json()
        if not isinstance(cards, list):
            return None, "Error: Unexpected API response format."
        print(f"Retrieved {len(cards)} cards from Jiten API")
        return cards, None
    except requests.exceptions.Timeout:
        return None, "Error: Request timed out. Please check your internet connection."
    except requests.exceptions.ConnectionError:
        return None, "Error: Could not connect to Jiten API. Please check your internet connection."
    except requests.exceptions.RequestException as e:
        return None, f"Request error: {e}"
    except json.JSONDecodeError:
        return None, "Error: Could not parse API response as JSON."


def words_from_cards(cards):
    """Jiten's cards as KnownWord.json entries, in Migaku's schema so the analyzer and the other tools that expect
    Migaku exports read them."""
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

    words = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        word_text = (card.get('wordText') or '').strip()
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
            'language': LANGUAGE,
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
    return words


def replace_known(words, language=LANGUAGE, output_json=None, expect=None):
    """Replace KnownWord.json with Jiten's `words`, holding its lock: a dated backup first (none made: nothing
    written), then the words of past Graduates kept (`anki_sync.replaced_words`: the words the user dismissed are
    dropped, the backup keeps them), written atomically. -> True when written. Prints each step. `expect`: the
    numbers the user confirmed (`anki_sync.replace_numbers`); moved by now, nothing is written and
    `anki_sync.NumbersChanged` is raised."""
    refused_language = refuse_language(language)
    if refused_language:
        print(refused_language)
        return False
    output_json = _known_json(language, output_json)
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

    # KnownWord.json is replaced holding its lock (P0.3 04 §2): never beside the Anki sync's or surasura-cli's write.
    from app.anki_sync import hold_known_words
    held, refused = hold_known_words(language, "Jiten import")
    if refused is not None:
        print(f"Error: {refused[0]}")
        return False
    try:
        # A file that exists but can't be read is never replaced: what it keeps can't be kept (AD2-1).
        from app.anki_sync import known_file_refusal
        unreadable = known_file_refusal(language, output_json)
        if unreadable:
            print(f"Error: {unreadable}")
            return False
        from app.anki_sync import check_numbers
        check_numbers(language, words, output_json, expect)
        # This import REPLACES the file. Keep a dated copy of what it replaces first
        # (User Files/<lang>/.trash/KnownWord.<YYYYmmdd-HHMMSS>.json); no copy, no overwrite.
        try:
            backup = backup_to_trash(output_json)
        except OSError as e:
            print(f"Error: could not back up your current known words, so nothing was changed ({e}).")
            return False
        if backup:
            print(f"Backed up your previous known words to: {backup}")

        # The words the old GraduatedList.txt gave the file stay known words (S3.1 D13); nothing else of the old file
        # stays (a clean slate from Jiten: the words the user dismissed are dropped, the backup above keeps them).
        from app.anki_sync import replaced_words
        words, graduated, _dropped = replaced_words(output_json, language, words)
        stats['totalWords'] += graduated
        stats['knownWords'] += graduated

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
        # Atomically (temp + fsync + replace): a reader never sees half a file, a kill leaves old or new.
        from app.anki_sync import _atomic_write_json
        _atomic_write_json(output_json, json_data)
    finally:
        if held is not None:
            held.release()
    print(f"JSON exported: {output_json}")
    print("\nConversion complete!")
    return True


def fetch_jiten_vocabulary(api_key, output_json=None, language='ja'):
    """Fetch the account's cards and replace KnownWord.json with them (`replace_known`). -> True when written."""
    refused_language = refuse_language(language)
    if refused_language:
        print(refused_language)
        return False
    try:
        cards, error = fetch_cards(api_key)
        if error:
            print(error)
            return False
        return replace_known(words_from_cards(cards), language, output_json)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def save_cards(api_key, path, language='ja'):
    """The window's first step (W3.4 row 2): fetch the cards and keep them at `path` (atomically), so the replace
    the user then confirms writes exactly what its confirmation counted. Changes no known words. -> True when kept.
    Known words that can't be read refuse it before anything is fetched (AD2-1: their replace would be refused)."""
    refused_language = refuse_language(language)
    if refused_language:
        print(refused_language)
        return False
    from app.anki_sync import known_file_refusal
    unreadable = known_file_refusal(language)
    if unreadable:
        print(f"Error: {unreadable}")
        return False
    try:
        cards, error = fetch_cards(api_key)
        if error:
            print(error)
            return False
        from app.anki_sync import _atomic_write_json
        _atomic_write_json(path, cards, indent=None)
        print(f"Fetched {len(cards)} cards; nothing changed yet.")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def load_cards(path):
    """The cards `save_cards` kept -> the list, or None when the file can't be read as one."""
    try:
        with open(path, encoding="utf-8") as f:
            cards = json.load(f)
    except (OSError, ValueError):
        return None
    return cards if isinstance(cards, list) else None


def replace_from_cards(path, language='ja', output_json=None, expect=None):
    """The window's second step: replace KnownWord.json with the cards kept at `path` (no second fetch)."""
    refused_language = refuse_language(language)
    if refused_language:
        print(refused_language)
        return False
    cards = load_cards(path)
    if cards is None:
        print("Error: the fetched cards could not be read, so nothing was changed.")
        return False
    from app.anki_sync import NumbersChanged
    try:
        return replace_known(words_from_cards(cards), language, output_json, expect)
    except NumbersChanged:
        raise
    except Exception as e:
        print(f"Error: {e}")
        return False


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Jiten API Importer")
    parser.add_argument("api_key", nargs='?',
                        help=f"Jiten API Key (default: the {API_KEY_ENV} environment variable)")
    parser.add_argument("out_file", nargs='?', help="Optional output JSON path")
    parser.add_argument("--language", default='ja', help="Target language (default: ja)")
    parser.add_argument("--save-cards", default=None,
                        help="Fetch only: keep the cards in this file, change no known words (the window's step 1)")
    parser.add_argument("--cards", default=None,
                        help="Replace from the cards --save-cards kept, with no fetch (the window's step 2)")
    parser.add_argument("--expect", default=None,
                        help="With --cards: the numbers the user confirmed (now,after,graduated,ignored); moved by "
                             "then, nothing is replaced and the exit code is 4")

    args = parser.parse_args(argv)
    refused_language = refuse_language(args.language)
    if refused_language:                                  # before any key is read or anything fetched
        print(refused_language)
        sys.exit(1)
    if args.cards:
        from app.anki_sync import EXIT_CHANGED, NumbersChanged, parse_expect
        try:
            ok = replace_from_cards(args.cards, args.language, args.out_file, parse_expect(args.expect))
        except NumbersChanged as e:
            print(f"Error: {e}")
            sys.exit(EXIT_CHANGED)
        sys.exit(0 if ok else 1)
    api_key = args.api_key or os.environ.get(API_KEY_ENV)
    if not api_key:
        print("Error: No Jiten API key was given.")
        sys.exit(1)
    if args.save_cards:
        sys.exit(0 if save_cards(api_key, args.save_cards, args.language) else 1)
    ok = fetch_jiten_vocabulary(api_key, args.out_file, args.language)
    # The importer window reads the exit code to choose between "Success" and "Error"; returning
    # normally on a failure (e.g. a rejected key) made it announce success for nothing written.
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
