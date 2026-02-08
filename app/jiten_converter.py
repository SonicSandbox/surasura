import json
from datetime import datetime
import sys
import os
import requests

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file

def fetch_jiten_vocabulary(api_key, output_json=None):
    if not output_json:
        output_json = get_user_file("User Files/KnownWord.json")

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
        
        words = []
        for card in cards:
            word_text = card.get('wordText', '').strip()
            if not word_text:
                continue
            
            state = card.get('state')
            status = map_state_to_status(state)
            
            words.append({
                'wordText': word_text,
                'wordId': card.get('wordId'),
                'cardId': card.get('cardId'),
                'frequencyRank': card.get('frequencyRank'),
                'readingType': card.get('readingType'),
                'knownStatus': status,
                'lastReview': card.get('lastReview'),
                'due': card.get('due'),
                'state': state
            })
        
        print(f"Processed {len(words)} words")
        
        # Calculate statistics
        stats = {
            'totalWords': len(words),
            'knownWords': sum(1 for w in words if w['knownStatus'] == "KNOWN"),
            'learningWords': sum(1 for w in words if w['knownStatus'] == "LEARNING"),
            'unknownWords': sum(1 for w in words if w['knownStatus'] == "UNKNOWN"),
        }
        
        print("\nStatistics:")
        print(f"  Total Words: {stats['totalWords']}")
        print(f"  Known Words: {stats['knownWords']}")
        print(f"  Learning Words: {stats['learningWords']}")
        print(f"  Unknown Words: {stats['unknownWords']}")
        
        print(f"\nWriting JSON to: {output_json}")
        
        json_data = {
            'exportDate': datetime.now().isoformat(),
            'source': 'Jiten API',
            'statistics': stats,
            'words': words
        }
        
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
    if len(sys.argv) < 2:
        print("Usage: python jiten_converter.py <api-key> [output.json]")
        return
    
    api_key = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else None
    fetch_jiten_vocabulary(api_key, out_file)

if __name__ == "__main__":
    main()
