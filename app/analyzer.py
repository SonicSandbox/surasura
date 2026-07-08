import os
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import re
import csv
import pandas as pd
import fugashi
import pysrt
import jieba
import bisect
from collections import defaultdict, Counter
from datetime import datetime
import abc

from app.path_utils import get_user_file, get_resource, get_data_path, get_user_files_path
from app import settings_manager

# Default Weights (Overwritten by settings.json if present)
WEIGHT_HIGH = 10
WEIGHT_LOW = 5
WEIGHT_GOAL = 2

# Filters
SKIP_SINGLE_CHARS = True
MIN_FREQ = 0  # Hide words with frequency <= MIN_FREQ
SANITIZE_JA = False # Strip -suffixes for Japanese

# Load Logic Settings from settings.json
LOGIC = {
    "weights": {"high": 10, "low": 5, "goal": 2},
    "tiers": {"thresholds": [2500, 5000, 7500, 10000]},
    "context": {"search_range": 20, "min_words": 4, "max_extra": 2, "preferred_max_chars": 50},
    "sentence_boundaries": {
        "ja": "。！？!?\n",
        "zh": "。！？!?\n；;……"
    },
    "priority_markers": {
        "priority_threshold": 0.5,
        "priority_min": 3,
        "lopsided_threshold": 0.8
    }
}

try:
    full_settings = settings_manager.load_settings()
    LOGIC.update(full_settings.get("logic", {}))
    
    # Update global weights for backward compatibility in the script
    WEIGHT_HIGH = LOGIC["weights"].get("high", 10)
    WEIGHT_LOW = LOGIC["weights"].get("low", 5)
    WEIGHT_GOAL = LOGIC["weights"].get("goal", 2)
except Exception as e:
    print(f"Warning: Could not load logic settings: {e}")

# Paths - Now determined dynamically in main()
# RESULTS_DIR remains shared for the "Active" analysis result
RESULTS_DIR = get_user_file("results")
os.makedirs(RESULTS_DIR, exist_ok=True)

OUTPUT_CSV = os.path.join(RESULTS_DIR, "priority_learning_list.csv")
OUTPUT_STATS = os.path.join(RESULTS_DIR, "file_statistics.txt")
OUTPUT_PROGRESSIVE = os.path.join(RESULTS_DIR, "progressive_learning_list.csv")


# --- Classes & Functions ---

class Tokenizer(abc.ABC):
    @abc.abstractmethod
    def tokenize(self, text):
        pass

    @abc.abstractmethod
    def tokenize_sentences(self, text):
        pass

class JapaneseTokenizer(Tokenizer):
    def __init__(self):
        self.tagger = fugashi.Tagger()

    def tokenize(self, text):
        """Returns a list of (lemma, parsing_reading, original_surface) tuples."""
        # Simple wrapper around sentences
        all_tokens = []
        for _, tokens in self.tokenize_sentences(text):
            all_tokens.extend(tokens)
        return all_tokens

    def tokenize_sentences(self, text):
        """Yields (sentence_string, list_of_filtered_tokens).

        Fugashi consumes newlines, so '\\n' in the boundary set never fired and separate lines
        (e.g. a transcript's title / URL / '----' header) merged into one giant sentence. We
        therefore process the text line by line, treating each line break as a hard boundary.
        """
        # Unidic-lite pos1: '補助記号' (punctuation), '空白' (spaces)
        boundaries = LOGIC.get("sentence_boundaries", {}).get("ja", "。！?！？!\n")

        for line in text.split("\n"):
            current_sentence_tokens = []
            current_sentence_surface = []

            for word in self.tagger(line):
                surface = word.surface
                pos = word.feature.pos1
                is_boundary = surface in boundaries

                lemma = word.feature.lemma if word.feature.lemma else word.surface
                if SANITIZE_JA:
                    lemma = _sanitize_term(lemma)
                reading = word.feature.kana if word.feature.kana else ""

                current_sentence_surface.append(surface)
                if pos not in ['记号', '補助記号', '空白']:
                    current_sentence_tokens.append((lemma, reading, word.surface))

                if is_boundary:
                    s_text = "".join(current_sentence_surface).lstrip("」』”'\" ").strip()
                    if s_text:
                        yield s_text, current_sentence_tokens
                    current_sentence_tokens = []
                    current_sentence_surface = []

            # End of a line is itself a hard sentence boundary — flush any remainder.
            if current_sentence_surface:
                s_text = "".join(current_sentence_surface).lstrip("」』”'\" ").strip()
                if s_text:
                    yield s_text, current_sentence_tokens

class ChineseTokenizer(Tokenizer):
    def __init__(self, reinforce_segmentation=False):
        # Force separation of common collocations that users prefer to see split
        # e.g. "就把" -> "就", "把" instead of "就把"
        if reinforce_segmentation:
            jieba.suggest_freq(('就', '把'), tune=True)
            jieba.suggest_freq(('您', '不'), tune=True)
            print("Configuration: Chinese segmentation reinforcement ENABLED.")
        else:
            # We can't easily "undo" suggest_freq cleanly without reloading jieba or messing with internal dicts
            # but since strictness is usually preferred, we can just leave it or rely on script restart.
            # In this architecture, analyzer.py is run as a subprocess, so it starts fresh each time.
            pass

    def tokenize(self, text):
        """Returns a list of (lemma, pinyin_placeholder, original_surface) tuples."""
        all_tokens = []
        for _, tokens in self.tokenize_sentences(text):
            all_tokens.extend(tokens)
        return all_tokens

    def tokenize_sentences(self, text):
        """Yields (sentence_string, list_of_filtered_tokens)"""
        # jieba.cut returns a generator
        # We need to manually handle sentence splitting because jieba just streams tokens
        
        # 1. Split text into blocks by punctuation (broadly) to avoid feeding massive text to jieba if needed,
        # but jieba is fast. However, we need to reconstruct sentences for context.
        
        # Simple approach: Tokenize everything, then buffer into sentences based on punctuation tokens
        
        seg_list = jieba.cut(text, cut_all=False)
        
        current_sentence_tokens = []
        current_sentence_surface = []
        
        punctuation_str = LOGIC.get("sentence_boundaries", {}).get("zh", "。！?！？!\n；;……")
        punctuation = set(list(punctuation_str))
        # Common particles/punctuation to skip in "meaningful token" list might be needed,
        # but for now we include everything that isn't strict punctuation/space.
        
        for word in seg_list:
            surface = word
            is_boundary = surface in punctuation or surface.strip() == '' and '\n' in surface # Handle newline
            
            # Strict filtering: Must contain at least one CJK character.
            # AND must NOT contain any Japanese Hiragana/Katakana (to avoid mixed JA text noise).
            has_cjk = re.search(r'[\u4E00-\u9FFF]', surface)
            has_kana = re.search(r'[\u3040-\u30FF]', surface)
            
            is_skippable = (not has_cjk) or (has_kana is not None) 
            
            # For Chinese, "lemma" is just the word. "Reading" (Pinyin) requires pypinyin, 
            # but user didn't ask for Pinyin injection yet, and existing data might not have it.
            # We will use empty string for reading for now, or the word itself if that helps matching.
            # Surasura uses (lemma, reading) as unique key.
            # If we use "" for reading, we might merge homophones? 
            # Japanese relies on reading for disambiguation sometimes? 
            # Actually, (lemma, reading) tuple is the key. 
            # For Chinese, (Word, "") is fine. Distinct words are distinct characters.
            
            current_sentence_surface.append(surface)
            
            if not is_skippable:
                current_sentence_tokens.append((surface, "", surface))
            
            if is_boundary:
                s_text = "".join(current_sentence_surface).strip()
                if s_text:
                    yield s_text, current_sentence_tokens
                current_sentence_tokens = []
                current_sentence_surface = []
                
        # Flush
        if current_sentence_surface:
            s_text = "".join(current_sentence_surface).strip()
            if s_text:
                yield s_text, current_sentence_tokens


def rolling_context_cost(target_freq, sorted_unknown_freqs):
    """Approximate the i+1 cost of a candidate sentence for a target word.

    A candidate's true i+1 quality depends on which of its OTHER unknown words are still
    unknown once the learner reaches the target. More-common co-words are learned first
    (higher priority), so they won't make the sentence harder — only RARER co-words remain.
    Approximate that with running frequency: count the sentence's unknowns whose frequency is
    strictly below the target's. `sorted_unknown_freqs` must be ascending. O(log n).
    """
    return bisect.bisect_left(sorted_unknown_freqs, target_freq)


def _sanitize_term(term):
    """
    Strip all characters starting from the hyphen - or space in the Term field.
    Example: \"アイリス-iris\" -> \"アイリス\"
    """
    if not isinstance(term, str):
        return term
    
    # If sanitization is DISABLED and we aren't loading an external frequency list, 
    # we should just strip whitespace. 
    # Actually, let's keep _sanitize_term as a raw helper and have the CALLERS decide.
    # No, wait. The user wants the toggle to affect analysis AND loading.
    
    # First strip leading/trailing whitespace
    term = term.strip()
    
    # Match anything before the first hyphen or space
    # re.split returns a list, we take the first element
    parts = re.split(r'[-\s]', term)
    return parts[0] if parts else term

def load_simple_list(file_path):
    if not os.path.exists(file_path):
        return set()
    with open(file_path, 'r', encoding='utf-8') as f:
        # Ignore comments starting with # and empty lines
        return set((_sanitize_term(line.strip()) if SANITIZE_JA else line.strip()) for line in f if line.strip() and not line.strip().startswith("#"))

def discover_yomitan_frequency_lists(user_files_dir, language='ja'):
    """
    Scan User Files directory for frequency_list_{lang}_*.csv files.
    Returns a dictionary mapping frequency list name -> filepath.
    """
    freq_lists = {}
    if not os.path.exists(user_files_dir):
        return freq_lists
    
    prefix = f"frequency_list_{language}_"
    
    try:
        for filename in os.listdir(user_files_dir):
            if filename.startswith(prefix) and filename.endswith(".csv"):
                # Extract name: frequency_list_ja_Novel.csv -> Novel
                list_name = filename.replace(prefix, "").replace(".csv", "")
                filepath = os.path.join(user_files_dir, filename)
                freq_lists[list_name] = filepath
    except Exception as e:
        print(f"Warning: Error scanning frequency lists: {e}")
    
    return freq_lists

def load_yomitan_frequency_list(csv_path):
    """
    Load a frequency list from a CSV file.
    Returns a dictionary mapping word -> rank (int).
    
    CSV format: Two columns: Word, Rank
    Example:
    Word,Rank
    の,1
    は,2
    ...
    
    Note: Multiple words can have the same rank value.
    Uses csv module for fast loading of large files.
    """
    word_to_rank = {}
    
    if not os.path.exists(csv_path):
        print(f"Warning: Frequency list not found: {csv_path}")
        return word_to_rank
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Sanitize to match analysis lemmas ONLY when JA term sanitization is active.
                    # _sanitize_term strips from the first hyphen/space (a Japanese-only cleanup);
                    # Chinese (and JA with the toggle off) must keep the raw word.
                    word = _sanitize_term(row['Word']) if SANITIZE_JA else (row['Word'] or '').strip()
                    rank = int(row['Rank'])
                    word_to_rank[word] = rank
                except (ValueError, KeyError):
                    continue  # Skip malformed rows
    except Exception as e:
        print(f"Warning: Error loading frequency list {csv_path}: {e}")
    
    print(f"Loaded {len(word_to_rank)} words from {os.path.basename(csv_path)}")
    return word_to_rank

def get_tier_from_rank(rank):
    """
    Determine tier from frequency rank.
    Tier ranges:
    - Tier 1: 1-2500 (most common)
    - Tier 2: 2501-5000
    - Tier 3: 5001-7500
    - Tier 4: 7501-10000
    - Tier 5: 10001+ (least common)
    """
    thresholds = LOGIC.get("tiers", {}).get("thresholds", [2500, 5000, 7500, 10000])
    
    if not isinstance(rank, int) or rank <= 0:
        return "Outside"
    
    for i, threshold in enumerate(thresholds):
        if rank <= threshold:
            return str(i + 1)
            
    return str(len(thresholds) + 1)

def load_known_words(json_path, tokenizer):
    try:
        print(f"Loading known words from {json_path}...")
    except UnicodeEncodeError:
        print("Loading known words (path contains non-ASCII characters)...")
    if not os.path.exists(json_path):
        print("Warning: Known words file not found.")
        return set(), set()
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    known_tuples = set()
    known_lemmas = set()
    # Handle both Dict (list in 'words') and List formats
    if isinstance(data, dict):
         word_list = data.get("words", [])
    elif isinstance(data, list):
         word_list = data
    else:
         word_list = []

    for entry in word_list:
        status = entry.get("knownStatus", "")
        has_card = entry.get("hasCard", 0)
        
        is_known = (status == "KNOWN") or (has_card == 1)
        
        if is_known:
            term = entry.get("dictForm", "")
            if SANITIZE_JA:
                term = _sanitize_term(term)
            
            if term:
                # Normalize using the same tokenizer
                try:
                    tokens = tokenizer.tokenize(term)
                    
                    # 0. Trust the explicit dictForm as a lemma (catches cases where tokenizer normalizes "その" -> "其の")
                    known_lemmas.add(term) 

                    # 1. Add individual tokens
                    for lemma, reading, _ in tokens:
                        known_tuples.add((lemma, reading))
                        known_lemmas.add(lemma)
                        
                    # 2. Heuristic: If multiple tokens, add the combined form too.
                    # This fixes issues like "まで" (which tokenizer might split as "Ma"+"De" in isolation, 
                    # but find as "Made" particle in context).
                    if len(tokens) > 1:
                        full_reading = "".join([t[1] for t in tokens if t[1]]) # Concat readings
                        known_tuples.add((term, full_reading))
                        known_lemmas.add(term)
                        
                except Exception:
                    # Fallback if tokenization fails
                    pass
                
    print(f"Loaded {len(known_tuples)} known word variations and {len(known_lemmas)} unique lemmas.")
    return known_tuples, known_lemmas

def has_target_language(text, language='ja'):
    if language == 'ja':
        # Ranges for Hiragana, Katakana, and Kanji (Common and Rare)
        pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]')
        return bool(pattern.search(text))
    elif language == 'zh':
        # Chinese: Mostly Kanji (Hanzi) \u4E00-\u9FFF
        # We can also check for common Chinese punctuation if needed, but Hanzi is the main indicator.
        # Japanese also uses Hanzi, but usually mixed with Kana. 
        # Pure Chinese text will be almost all Hanzi + Punctuation.
        # This check basically asks: "Is there any CJK character?"
        pattern = re.compile(r'[\u4E00-\u9FFF]')
        return bool(pattern.search(text))
    return False

def clean_subtitle_text(text, language='ja'):
    # first remove ASS tags like {\pos(10,20)}
    text = re.sub(r'\{.*?\}', '', text)
    
    # Remove furigana in parens
    text = re.sub(r'[\(（].*?[\)）]', '', text)
    
    if language == 'ja':
        # Keep: Kanji, Hiragana, Katakana, and Japanese-style punctuation
        # Strip: ASCII letters and numbers (modeling the "Saturation Point" and "Noise Removal")
        text = re.sub(r'[a-zA-Z0-9]', '', text)
        
        # Strip common subtitle noise like - or > if they are alone at start
        text = re.sub(r'^[ \->]+', '', text)
        text = text.strip()
    elif language == 'zh':
        text = re.sub(r'[a-zA-Z0-9]', '', text)
        text = text.strip()
        
    return text

def parse_ass(file_path, language='ja'):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading ASS/SSA {file_path}: {e}")
        return ""

    lines = content.splitlines()
    events_section = False
    format_line = None
    text_index = 9 # Default for standard ASS
    
    output_parts = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line == '[Events]':
            events_section = True
            continue
        
        if events_section:
            if line.startswith('Format:'):
                format_line = line[7:].split(',')
                format_line = [f.strip() for f in format_line]
                try:
                    text_index = format_line.index('Text')
                except ValueError:
                    pass
                continue
            
            if line.startswith('Dialogue:'):
                # Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
                # Split by comma but only up to text_index
                comma_parts = line.split(',', text_index)
                if len(comma_parts) > text_index:
                    original_text = comma_parts[text_index]
                    if has_target_language(original_text, language):
                        cleaned = clean_subtitle_text(original_text, language)
                        if cleaned:
                            if not cleaned or cleaned[-1] not in '。！？!?':
                                cleaned += "。"
                            output_parts.append(cleaned)
                            
    return " ".join(output_parts)

def extract_text(file_path, language='ja'):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext == '.srt':
        try:
            subs = pysrt.open(file_path)
            parts = []
            for sub in subs:
                # Filter out lines without Target characters
                lines = sub.text.splitlines()
                filtered_lines = []
                for l in lines:
                    if not has_target_language(l, language):
                        continue
                    
                    cleaned = clean_subtitle_text(l, language)
                    if cleaned:
                        filtered_lines.append(cleaned)

                if filtered_lines:
                    block_text = " ".join(filtered_lines)
                    if not block_text or block_text[-1] not in '。！？!?':
                        block_text += "。"
                    parts.append(block_text)
            text = "".join(parts)
        except Exception as e:
            print(f"Error reading SRT {file_path}: {e}")
    elif ext in ['.ass', '.ssa']:
        text = parse_ass(file_path, language)
    else:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
                
    return text

def find_context_sentence(full_text, target_surface):
    sentences = re.split(r'([。！？\n])', full_text)
    current_sent = ""
    for part in sentences:
        current_sent += part
        if any(d in part for d in '。！？\n'):
            if target_surface in current_sent:
                return current_sent.strip()
            current_sent = ""
            
    idx = full_text.find(target_surface)
    if idx != -1:
        search_range = LOGIC.get("context", {}).get("search_range", 20)
        start = max(0, idx - search_range)
        end = min(len(full_text), idx + search_range)
        return "..." + full_text[start:end].replace("\n", " ") + "..."
    return ""

def group_sources(source_list):
    """
    Groups similar filenames.
    Less picky: Removes trailing digits, brackets, etc.
    """
    if not source_list: return ""
    
    sorted_sources = sorted(list(source_list))
    groups = defaultdict(int)
    
    for src in sorted_sources:
        base = os.path.splitext(src)[0]
        # Regex: Remove any sequence of digits, brackets, parens at the end
        # Also remove spaces/underscores/hyphens immediately preceding them
        group_key = re.sub(r'[\s_\-\.\(\)\[\]\d]+$', '', base)
        
        if len(group_key) < 2: group_key = base # Fallback if aggressive strip leaves nothing
        
        groups[group_key] += 1

    simplified_sources = []
    for s in source_list:
        base = os.path.splitext(s)[0]
        
        # 1. Simplify CRC/Hash like [A1B2C3D4] or (1920x1080)
        # Remove standard CRC [8 chars hex]
        base = re.sub(r'\s*\[[0-9a-fA-F]{8}\]\s*$', '', base)
        
        # 2. Heuristic: Remove trailing number sequence (likely episode/volume number)
        # Matches: Optional separators + Digits + Optional separators + End
        # This keeps "861" from "861_1" (removes _1)
        # But "861" -> Removes "861" -> Becomes empty -> Reverts to "861" below.
        simple = re.sub(r'[\s_\-\(\)\[\]]*\d+[\s_\-\(\)\[\]]*$', '', base)
        
        if not simple: 
             simple = base
             
        simplified_sources.append(simple)
    
    groups = Counter(simplified_sources)
    result_parts = []
    # Sort groups by count desc, then name? Or just name. 
    # Counter.items() is arbitrary order. Sort for consistency.
    sorted_groups = sorted(groups.items(), key=lambda x: (-x[1], x[0]))
    
    for key, count in sorted_groups:
        if count > 1:
            result_parts.append(f"{key} ({count})")
        else:
            result_parts.append(key)
            
    return ", ".join(result_parts)

def get_tier_label(word, freq_data):
    """
    Get tier labels for a word from all frequency lists.
    Returns a list of (source_name, tier_number) tuples.
    Example: [("Novel", "1"), ("Anime", "2")]
    Empty list means word is not in any frequency list (Outside).
    """
    tiers_found = []
    
    # Check all frequency lists and collect all tiers
    for source_name in sorted(freq_data.keys()):
        if word in freq_data[source_name]:
            rank = freq_data[source_name][word]
            tier = get_tier_from_rank(rank)
            if tier != "Outside":
                tiers_found.append((source_name, tier))
    
    return tiers_found

def main():
    import sys
    
    # --- VISUALIZER REMOVED ---
    # Legacy interactive visualizer logic removed.

    # --- STATIC ONLY MODE ---
    if "--static-only" in sys.argv:
        try:
            import static_html_generator
            print("\n---------------------------------------------------")
            print("Generating Static HTML (Skipping Analysis)...")
            static_html_generator.generate_static_html()
            return
        except ImportError:
            print("Error: static_html_generator.py not found.")
            return

    # --- ARGUMENT PARSING ---
    import argparse
    parser = argparse.ArgumentParser(description="Japanese Text Analyzer")
    
    # Flags for standard run
    parser.add_argument("--include-single-chars", action="store_true", help="Include 1-character words (overrides default skip)")
    parser.add_argument("--exclude-freq-one", action="store_true", help="Backward compat: Exclude words with frequency of 1")

    parser.add_argument("--min-freq", type=int, default=0, help="Hide words with frequency < this value (default 0)")
    parser.add_argument("--reinforce", action="store_true", help="Force strict segmentation for Chinese (e.g. split common collocations like 'jiu ba')")
    
    # These are handled manually above but good to have in help
    parser.add_argument("--visualize-only", action="store_true", help="Launch visualizer server")
    parser.add_argument("--static-only", action="store_true", help="Generate static HTML")
    parser.add_argument("--visualize", action="store_true", help="Launch visualizer after analysis")
    parser.add_argument("--static", action="store_true", help="Generate static HTML after analysis")
    parser.add_argument("--theme", type=str, default="default", help="Theme for static HTML (default, world-class, modern-light, zen-focus)")
    parser.add_argument("--target-coverage", type=int, default=0, help="Target cumulative coverage percent (0-100)")
    parser.add_argument("--language", type=str, default="ja", help="Target language code (ja, zh)")
    parser.add_argument("--zen-limit", type=int, default=0, help="Limit words for Zen Mode")
    parser.add_argument("--only-i-plus-one", action="store_true", help="Only include words with i+1 sentences")
    parser.add_argument("--context-min", type=int, default=None, help="Ideal sentence minimum words/characters")
    parser.add_argument("--context-max", type=int, default=None, help="Ideal sentence maximum words/characters")
    parser.add_argument("--max-contexts", type=int, default=3, help="Maximum number of example sentences exported per word")

    args, unknown = parser.parse_known_args()
    
    global SKIP_SINGLE_CHARS, MIN_FREQ, SANITIZE_JA, ONLY_I_PLUS_ONE
    ONLY_I_PLUS_ONE = args.only_i_plus_one

    # Override logic settings if supplied
    if args.context_min is not None:
        if "context" not in LOGIC:
            LOGIC["context"] = {}
        LOGIC["context"]["min_chars"] = args.context_min
        print(f"Configuration: Context Min Length = {args.context_min}")
        
    if args.context_max is not None:
        if "context" not in LOGIC:
            LOGIC["context"] = {}
        LOGIC["context"]["preferred_max_chars"] = args.context_max
        print(f"Configuration: Context Max Length = {args.context_max}")
    
    # Logic: Default SKIP_SINGLE_CHARS is True. 
    # If --include-single-chars is present, set to False.
    if args.include_single_chars:
        SKIP_SINGLE_CHARS = False
        print("Configuration: Single character words INCLUDED.")
    else:
        SKIP_SINGLE_CHARS = True
        print("Configuration: Single character words SKIPPED (Default).")

    # Min Frequency Logic
    if args.min_freq > 0:
        MIN_FREQ = args.min_freq
        print(f"Configuration: Words with frequency < {MIN_FREQ} EXCLUDED.")
    elif args.exclude_freq_one:
        # Backward compatibility
        MIN_FREQ = 1
        print("Configuration: Frequency < 1 words EXCLUDED (via flag).")
    else:
        MIN_FREQ = 0
        print("Configuration: All frequencies INCLUDED (Default).")
        
    language = args.language
    print(f"Configuration: Target Language = {language}")

    # Japanese Unidic lemmas carry a gloss suffix (e.g. テスト-test); always strip it for JA so
    # lemmas match the (clean) frequency lists and a word never splits into -suffix variants.
    SANITIZE_JA = (language == 'ja')
    print(f"Configuration: Japanese term sanitization = {SANITIZE_JA}")

    # Single-char tokens are skippable noise in Japanese (particles), but in Chinese most
    # high-frequency words ARE single characters — never skip them for zh.
    skip_singles = SKIP_SINGLE_CHARS and language == 'ja'

    print(f"\nLoading resources...")
    
    # Resolve Paths based on Language
    data_dir = get_data_path(language)
    user_files_dir = get_user_files_path(language)
    
    # 1. Load Resources
    if language == 'zh':
        tokenizer = ChineseTokenizer(reinforce_segmentation=args.reinforce)
        # For consistency, we might look for KnownWord.json in the zh folder too?
        # Legacy: KnownWord_zh.json in User Files?
        # New Plan: User Files/zh/KnownWord.json
        known_file = os.path.join(user_files_dir, "KnownWord.json")
    else:
        tokenizer = JapaneseTokenizer()
        known_file = os.path.join(user_files_dir, "KnownWord.json")
        
    known_words_initial, known_lemmas_initial = load_known_words(known_file, tokenizer)
    
    ignore_list_file = os.path.join(user_files_dir, "IgnoreList.txt")
    black_list_file = os.path.join(user_files_dir, "Blacklist.txt")
    graduated_list_file = os.path.join(user_files_dir, "GraduatedList.txt")
    
    ignore_list = load_simple_list(ignore_list_file)
    black_list = load_simple_list(black_list_file)
    graduated_list = load_simple_list(graduated_list_file)
    
    ignore_list.update(black_list) # Merge blacklist into ignore list
    ignore_list.update(graduated_list) # Merge graduated list into ignore list
    
    # Discover and load all yomitan frequency lists from User Files
    print(f"Scanning for {language} frequency lists in {user_files_dir}...")
    available_freq_lists = discover_yomitan_frequency_lists(user_files_dir, language)
    
    if not available_freq_lists:
        print("Warning: No frequency lists found in User Files/")
        print("Expected format: frequency_list_{lang}_*.csv")
    
    freq_data = {}
    for list_name, filepath in sorted(available_freq_lists.items()):
        freq_data[list_name] = load_yomitan_frequency_list(filepath)
    
    print(f"Found {len(freq_data)} frequency lists: {', '.join(sorted(freq_data.keys()))}")
    
    # 2. Define Scanning targets
    # ORDER MATTERS: High -> Low -> Goal
    scan_targets = [
        ("HighPriority", os.path.join(data_dir, "HighPriority"), WEIGHT_HIGH),
        ("LowPriority", os.path.join(data_dir, "LowPriority"), WEIGHT_LOW),
        ("GoalContent", os.path.join(data_dir, "GoalContent"), WEIGHT_GOAL)
    ]
    
    word_stats = defaultdict(lambda: {
        "score": 0, "total_count": 0, "sources": set(), 
        "high_count": 0, "low_count": 0, "goal_count": 0,
        "candidate_contexts": [], # List of (is_too_short, is_too_long, initial_cost, unique_lrs, s_text)
        "first_context": None,
        "surface": "",
        "min_seq": float('inf') # Track first appearance sequence index
    })
    
    words_skipped_i_plus_one = 0 # Track skips explicitly for visibility

    file_stats = [] 
    
    # 3. Process Files (Aggregation Phase)
    # Check for legacy migration first
    try:
        from modules.immersion_architect.immersion_architect import ImmersionArchitect
        architect = ImmersionArchitect(language=language)
        architect.migrate_legacy_order_if_needed()
    except (ImportError, ModuleNotFoundError):
        print("Note: Immersion Architect module not found. Skipping legacy migration check.")


    # New Logic: Use master_manifest.json if available.
    # Fallback: Alphabetical scan (Phase 0 behavior)
    
    found_files = []
    
    # Check for master_manifest.json
    manifest_path = os.path.join(user_files_dir, "master_manifest.json")
    
    if os.path.exists(manifest_path):
        try:
            print(f"Loading Sort Order from Manifest: {manifest_path}")
        except UnicodeEncodeError:
            print("Loading Sort Order from Manifest (path contains non-ASCII characters)")
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
                
            schedule = manifest.get("schedule", {})
            phases = ["PHASE_1_NOW", "PHASE_2_SOON", "PHASE_3_LATER"] # order matters
            
            seen_paths = set()
            
            for phase_key in phases:
                items = schedule.get(phase_key, [])
                for item in items:
                    # Logic: We need the absolute path.
                    # Manifest stores "physical_path" relative to data_dir usually? 
                    # Immersion Architect stores: "./01_NOW/..." relative to data root
                    # logic: os.path.join(data_dir, item["physical_path"])
                    
                    # Need to handle potential "../" or "./" in the stored path
                    # "physical_path": "./01_NOW/HarryPotter/HP_01.txt"
                    # data_dir is "User Data/data/ja"
                    # We need to resolve this carefully.
                    
                    rel_path = item.get("physical_path", "")
                    
                    # Hack/Fix: Immersion Architect uses:
                    # self.buckets = { "01_NOW": .../HighPriority, ... }
                    # and indexes files there. 
                    # But the manifest path stored might be raw path?
                    # Let's check Immersion Architect implementation.
                    # It stores: os.path.relpath(winner["file_path"], self.data_root)
                    # So "./HighPriority/Book/File.txt" -> "HighPriority/Book/File.txt" roughly
                    
                    if rel_path.startswith("./"):
                        rel_path = rel_path[2:]
                        
                    abs_path = os.path.join(data_dir, rel_path)
                    
                    if not os.path.exists(abs_path):
                        # Try matching by title if path fails (moved files?)
                        # For now, just skip or warn
                        print(f"Warning: Manifest file not found: {abs_path}")
                        continue
                        
                    if abs_path in seen_paths: continue
                    seen_paths.add(abs_path)
                    
                    # Determine Weight based on Phase
                    weight = WEIGHT_GOAL # Default
                    if phase_key == "PHASE_1_NOW": weight = WEIGHT_HIGH
                    elif phase_key == "PHASE_2_SOON": weight = WEIGHT_LOW
                    
                    # Label? "HighPriority" etc is used for stats. 
                    # We can infer label from original path or just use phase?
                    # Logic: origin_source in manifest: "01_NOW", "02_SOON", "03_LATER"
                    # We should Probably map these back to "HighPriority", "LowPriority", "GoalContent"
                    # for consistency in output reporting? 
                    # Actually, the user might want to see "NOW" in the report.
                    # But let's map for backward compat first.
                    
                    origin = item.get("origin_source", "03_LATER")
                    label = "GoalContent"
                    if origin == "01_NOW": label = "HighPriority"
                    elif origin == "02_SOON": label = "LowPriority"
                    
                    found_files.append((abs_path, label, weight))
                    
            print(f"Manifest Loaded: {len(found_files)} files scheduled.")
            
        except Exception as e:
            print(f"Error reading manifest: {e}. Falling back to default scan.")
            found_files = [] # Trigger fallback
            
    if not found_files:
        # Fallback to recursively scanning folders (No _order.json support anymore per user request)
        print("Scaning folders recursively (Default Order)...")
        
        def get_files_recursive(directory):
            results = []
            if not os.path.exists(directory): return []
            
            # Simple os.walk to get files
            for root, dirs, files in os.walk(directory):
                # Sort for deterministic behavior
                files.sort()
                dirs.sort()
                
                for file in files:
                    # Filter extensions
                    if file.lower().endswith(('.txt', '.md', '.srt', '.epub', '.ass', '.html')):
                         full_path = os.path.join(root, file)
                         results.append(full_path)
            return results

        for label, folder, weight in scan_targets:
            if not os.path.exists(folder): continue
            
            paths = get_files_recursive(folder)
            for path in paths:
                found_files.append((path, label, weight))

    print(f"Final Count: Found {len(found_files)} files to process.")

    # Per-file (lemma, reading) counts captured during aggregation and reused by the
    # progressive pass, so the whole library is tokenized once instead of twice.
    file_token_cache = {}

    # --- AGGREGATION PASS ---
    for seq_idx, (file_path, label, weight) in enumerate(found_files, 1):
        try:
            print(f"Processing {os.path.basename(file_path)}...")
        except UnicodeEncodeError:
            print(f"Processing file {found_files.index((file_path, label, weight)) + 1}...")
        text = extract_text(file_path, language)
        
        file_total_words = 0
        file_known_words = 0
        # Multiset of every (lemma, reading) this file yields — mirrors tokenizer.tokenize()
        # exactly (built in first-appearance order) for the progressive pass to reuse.
        file_counter = Counter()

        for s_text, s_tokens in tokenizer.tokenize_sentences(text):
            # 1. Identify unknowns and calculate cost (relative to constant initial knowns)
            sentence_unknowns = []
            for lemma, reading, surface in s_tokens:
                # Cache EVERY token (before the target-language filter below) so the cached
                # multiset matches what tokenizer.tokenize() yields for the progressive pass.
                file_counter[(lemma, reading)] += 1
                # Skip tokens that contain no Target characters (e.g. SSA/ASS tags like {\an8},
                # timestamps, markup, or other ASCII-only tokens). These should not count
                # toward totals or be considered unknown words.
                if not has_target_language(lemma, language) and not has_target_language(surface, language):
                    continue

                file_total_words += 1
                if lemma in ignore_list:
                    file_known_words += 1
                    continue
                
                # Check if it's considered "Known" by dictionary
                is_known = (lemma, reading) in known_words_initial or (lemma in known_lemmas_initial)
                if is_known:
                    file_known_words += 1
                    continue
                
                # It's an unknown word!
                # Even if we skip learning it (e.g. single chars), it makes the sentence harder, 
                # so it must be part of `sentence_unknowns`.
                sentence_unknowns.append((lemma, reading, surface))

            # Unique unknowns in this sentence.
            unique_lrs = set((l, r) for l, r, s in sentence_unknowns)

            # 2. Update Stats for all unknown tokens in this sentence
            for lemma, reading, surface in sentence_unknowns:
                # If we are skipping single characters for learning, do not add it to word_stats
                if skip_singles and len(lemma) == 1:
                    continue
                    
                entry = word_stats[(lemma, reading)]
                entry["score"] += weight
                entry["total_count"] += 1
                entry["sources"].add(os.path.basename(file_path))
                entry["surface"] = surface
                if label == "HighPriority": entry["high_count"] += 1
                elif label == "LowPriority": entry["low_count"] += 1
                elif label == "GoalContent": entry["goal_count"] += 1
                
                # Track first appearance sequence
                if seq_idx < entry["min_seq"]:
                    entry["min_seq"] = seq_idx

            # 3. Update Best Contexts (once per unique unknown per sentence)
            min_chars = LOGIC.get("context", {}).get("min_chars", 10)
            is_too_short = 1 if len(s_text) < min_chars else 0
            
            preferred_max_chars = LOGIC.get("context", {}).get("preferred_max_chars", 50)
            is_too_long = 1 if len(s_text) > preferred_max_chars else 0
            # Hard cap: sentences longer than this are excluded from the candidate pool (they
            # make poor examples); a word's own/original sentence is still kept as a fallback.
            is_over_hard_max = len(s_text) > LOGIC.get("context", {}).get("max_chars", 150)

            # Running frequency of each of this sentence's unknowns (ascending) — used to score
            # each candidate by its rarer-than-target co-words (see rolling_context_cost).
            unk_freqs = sorted(
                word_stats[lr]["total_count"] if lr in word_stats else 0
                for lr in unique_lrs
            )

            for (lemma, reading) in unique_lrs:
                # If we skipped this word for learning, don't try to store candidate contexts for it
                if skip_singles and len(lemma) == 1:
                    continue
                    
                entry = word_stats[(lemma, reading)]

                # Rank this candidate by how many of the sentence's OTHER unknown words are
                # rarer than this word — a proxy for how many stay unknown when the learner
                # reaches it (common co-words are learned first). Same buffer / fast-exit.
                cost = rolling_context_cost(entry["total_count"], unk_freqs)
                new_ctx = (is_too_short, is_too_long, cost, unique_lrs, s_text)
                
                # Optimization 1: Insertion Caching - Fast exit if list is full and new sentence is worse
                if len(entry["candidate_contexts"]) >= 30:
                    worst_stored_ctx = entry["candidate_contexts"][-1]
                    # Compare only the first three sorting tuples (is_too_short, is_too_long, cost)
                    new_sorting_tuple = (new_ctx[0], new_ctx[1], new_ctx[2])
                    worst_sorting_tuple = (worst_stored_ctx[0], worst_stored_ctx[1], worst_stored_ctx[2])
                    
                    if new_sorting_tuple >= worst_sorting_tuple:
                        continue # No chance of beating the top 30, discard early!

                # Check if this exact sentence is already in candidate_contexts (Moved AFTER fast-path)
                if any(c[4] == s_text for c in entry["candidate_contexts"]):
                    continue

                if not entry["first_context"]:
                    entry["first_context"] = new_ctx

                # Very long sentences make poor secondary examples — keep them only as the
                # word's own/original fallback (first_context above), not in the candidate pool.
                if is_over_hard_max:
                    continue

                entry["candidate_contexts"].append(new_ctx)
                # Sort initially by: length validity, then initial cost
                entry["candidate_contexts"].sort(key=lambda x: (x[0], x[1], x[2]))
                # Keep up to 30 promising candidates
                entry["candidate_contexts"] = entry["candidate_contexts"][:30]
        
        file_token_cache[file_path] = file_counter
        coverage = (file_known_words / file_total_words * 100) if file_total_words > 0 else 0
        file_stats.append({
            "File": os.path.basename(file_path),
            "Total Words": file_total_words,
            "Known Count": file_known_words,
            "Coverage (%)": round(coverage, 2)
        })

    # Output Priority CSV
    rolling_known_tuples = set(known_words_initial)
    rolling_known_lemmas = set(known_lemmas_initial)
    
    preliminary_rows = []
    for (lemma, reading), data in word_stats.items():
        if MIN_FREQ > 0 and data["total_count"] < MIN_FREQ:
            continue

        tier_labels = get_tier_label(lemma, freq_data)
        # Format tiers as "Source1:Tier1;Source2:Tier2" or "Outside" if not in any list
        tier_str = ";".join([f"{source}:{tier}" for source, tier in tier_labels]) if tier_labels else "Outside"
        source_display = group_sources(data["sources"])

        row = {
            "Word": lemma,
            "Reading": reading,
            "Tier": tier_str,
            "Score": data["score"],
            "Occurrences": data["total_count"],
            "Count (High)": data["high_count"],
            "Count (Low)": data["low_count"],
            "Count (Goal)": data["goal_count"],
            "Sources": source_display, # Moved to end
            "_MinSeq": data["min_seq"], # Helper for sorting
            "_CandidateContexts": data["candidate_contexts"],
            "_FirstContext": data["first_context"]
        }
        preliminary_rows.append(row)
        
    # Sort Logic: Primary = Score (Desc), Secondary = First Appearance (Asc)
    preliminary_rows.sort(key=lambda x: (-x["Score"], x["_MinSeq"]))
    
    output_rows = []
    for r in preliminary_rows:
        target_lr = (r["Word"], r["Reading"])
        target_lemma = r["Word"]
        
        # Evaluate candidate contexts against rolling knowns
        evaluated_candidates = []
        seen_sentences = set()
        
        ctx_list = r["_CandidateContexts"]
        first_ctx_data = r.get("_FirstContext")
        if first_ctx_data and first_ctx_data not in ctx_list:
            ctx_list.insert(0, first_ctx_data)
            
        for ctx in ctx_list:
            sentence_text = ctx[4].strip()
            if not sentence_text or sentence_text in seen_sentences:
                continue
            seen_sentences.add(sentence_text)
            
            unique_lrs = ctx[3]
            unknown_count = 0
            for lr in unique_lrs:
                if lr == target_lr: continue
                if lr not in rolling_known_tuples and lr[0] not in rolling_known_lemmas:
                    unknown_count += 1
                    # Optimization 4: Fast-Fail Evaluation
                    # If strict i+1 mode is ON, any sentence > 0 unknowns is guaranteed garbage
                    if ONLY_I_PLUS_ONE and unknown_count > 0:
                        break
            
            # If we fast-failed, don't even bother appending the evaluated candidate
            if ONLY_I_PLUS_ONE and unknown_count > 0:
                continue

            evaluated_candidates.append((ctx[0], ctx[1], unknown_count, sentence_text))
            
            # Optimization 2: Early Exit
            # If we found enough "perfect" contexts (0 unknowns AND perfectly sized) we can stop evaluating
            if unknown_count == 0 and ctx[0] == 0 and ctx[1] == 0:
                perfect_count = sum(1 for c in evaluated_candidates if c[2] == 0 and c[0] == 0 and c[1] == 0)
                if perfect_count >= args.max_contexts:
                     # Stop scanning constraints - we already have max perfect i+1s ready
                     break
            
        first_evaluated = None
        if first_ctx_data:
            first_text = first_ctx_data[4].strip()
            for c in evaluated_candidates:
                if c[3] == first_text:
                    first_evaluated = c
                    break

        i_plus_one_candidates = [c for c in evaluated_candidates if c[2] == 0]
        
        if ONLY_I_PLUS_ONE:
            if not i_plus_one_candidates:
                words_skipped_i_plus_one += 1
                continue # Skip this word entirely
                
            # Optimization 3: Explicit Length Sorting for Strict Mode
            # Ensure we still prioritize the best length even if all are i+1s
            i_plus_one_candidates.sort(key=lambda x: (x[0], x[1]))
            selected_contexts = i_plus_one_candidates[:args.max_contexts]
        else:
            # Sort by: Fewest Unknowns, then Not Too Short, then Not Too Long
            evaluated_candidates.sort(key=lambda x: (x[2], x[0], x[1]))
            
            selected_contexts = []
            if first_evaluated:
                selected_contexts.append(first_evaluated)
                if first_evaluated in evaluated_candidates:
                    evaluated_candidates.remove(first_evaluated)
                    
            for c in evaluated_candidates:
                if len(selected_contexts) >= args.max_contexts:
                    break
                selected_contexts.append(c)
            
        for i in range(args.max_contexts):
            context_key = f"Context {i+1}"
            context_val = selected_contexts[i][3].strip() if len(selected_contexts) > i else ""
            r[context_key] = context_val
            
            # Save back to data dictionary for progressive report and json dumping
            data = word_stats[(r["Word"], r["Reading"])]
            data[f"final_context_{i+1}"] = context_val
        # Add to rolling known list and output
        rolling_known_tuples.add(target_lr)
        rolling_known_lemmas.add(target_lemma)
        
        del r["_CandidateContexts"] # Cleanup
        if "_FirstContext" in r:
            del r["_FirstContext"]
        output_rows.append(r)
        
    df = pd.DataFrame(output_rows)
    if not df.empty:
        # Drop the helper key if we added it (we need to add it to row first)
        df_display = df.drop(columns=["_MinSeq"])
        
        # TARGET COVERAGE LOGIC
        if args.target_coverage > 0:
            total_tokens = sum(s['Total Words'] for s in file_stats)
            current_known = sum(s['Known Count'] for s in file_stats)
            
            if total_tokens > 0:
                current_pct = (current_known / total_tokens) * 100
                print(f"Current Cumulative Coverage: {current_pct:.2f}% (Target: {args.target_coverage}%)")
                
                if current_pct >= args.target_coverage:
                    print(f"Goal Achieved: Target coverage of {args.target_coverage}% is already met ({current_pct:.2f}%).")
                    df = df.iloc[0:0] # Empty dataframe
                else:
                    # Greedy selection logic
                    needed_rows = []
                    running_known = current_known
                    target_tokens = (args.target_coverage / 100) * total_tokens
                    
                    for index, row in df.iterrows():
                        needed_rows.append(row)
                        running_known += row['Occurrences']
                        if running_known >= target_tokens:
                            break
                    
                    final_pct = (running_known / total_tokens) * 100
                    df = pd.DataFrame(needed_rows)
                    
                    if final_pct >= args.target_coverage:
                        print(f"Successfully reached {final_pct:.2f}% coverage by adding {len(df)} words.")
                    else:
                        print(f"Note: Could only reach {final_pct:.2f}% coverage after adding ALL {len(df)} unknown words.")
                        print(f"  (This is because some unique tokens remain that were not in the candidate list.)")
            
            # Use the filtered DF for output, but make sure to drop _MinSeq
            df_display = df.drop(columns=["_MinSeq"], errors='ignore')
            
        valid_lrs = set(zip(df_display['Word'], df_display['Reading']))
        df_display.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        try:
            print(f"Saved priority list to {OUTPUT_CSV}")
        except UnicodeEncodeError:
            print("Saved priority list to CSV.")
    else:
        print("No unknown words found!")

    OUTPUT_STATS_JSON = os.path.join(RESULTS_DIR, "file_statistics.json")
    with open(OUTPUT_STATS, 'w', encoding='utf-8') as f:
        f.write("--- File Statistics ---\n")
        f.write(f"Configuration: Skip Single Chars = {skip_singles}\n")
        if ONLY_I_PLUS_ONE:
             f.write(f"i+1 Constraint: {words_skipped_i_plus_one} Words Evaluated & Skipped\n")
        f.write("\n")
        for stat in file_stats:
            f.write(f"File: {stat['File']}\n")
            f.write(f"  Total Words: {stat['Total Words']}\n")
            f.write(f"  Known Words: {stat['Known Count']}\n")
            f.write(f"  Coverage: {stat['Coverage (%)']}%\n")
            f.write("\n")
        try:
            print(f"Saved stats to {OUTPUT_STATS}")
        except UnicodeEncodeError:
            print("Saved stats to file.")
    
    with open(OUTPUT_STATS_JSON, 'w', encoding='utf-8') as f:
        json.dump(file_stats, f, indent=4, ensure_ascii=False)
    try:
        print(f"Saved JSON stats to {OUTPUT_STATS_JSON}")
    except UnicodeEncodeError:
        print("Saved JSON stats.")

    # Output Raw Word Stats for GUI
    OUTPUT_WORD_STATS = os.path.join(RESULTS_DIR, "word_stats.json")
    # Convert word_stats to JSON-serializable format
    # Keys are (lemma, reading) tuples -> Convert to string "lemma|reading"
    # Values have sets -> Convert to lists
    serializable_stats = {}
    for (lemma, reading), data in word_stats.items():
        if 'valid_lrs' in locals() and (lemma, reading) not in valid_lrs:
            continue
            
        key = f"{lemma}|{reading}"
        serializable_data = data.copy()
        serializable_data["sources"] = list(data["sources"])
        
        # Convert unique_lrs sets to lists inside candidate_contexts
        if "candidate_contexts" in serializable_data:
            serializable_data["candidate_contexts"] = [
                (ctx[0], ctx[1], ctx[2], list(ctx[3]), ctx[4]) for ctx in serializable_data["candidate_contexts"]
            ]
        
        if "first_context" in serializable_data and serializable_data["first_context"]:
            ctx = serializable_data["first_context"]
            serializable_data["first_context"] = (ctx[0], ctx[1], ctx[2], list(ctx[3]), ctx[4])
            
        serializable_stats[key] = serializable_data
        
    with open(OUTPUT_WORD_STATS, 'w', encoding='utf-8') as f:
        json.dump(serializable_stats, f, indent=2, ensure_ascii=False)
    try:
        print(f"Saved raw word stats to {OUTPUT_WORD_STATS}")
    except UnicodeEncodeError:
        print("Saved raw word stats.")

    # --- Additive (optional): full library frequency map for the YouTube Preview feature ---
    # Gated behind the 'enable_youtube_preview' toggle so standard runs are completely
    # unaffected (no extra file, no extra time). This reuses the SAME in-memory word_stats
    # data — including the sub-threshold words the other outputs drop — written as a compact
    # counts-only map. It is a separate file (library_frequency.json); it never modifies
    # word_stats.json or any existing output, and is wrapped so a failure can't break a run.
    try:
        _preview_enabled = settings_manager.load_settings().get("enable_youtube_preview", False)
    except Exception:
        _preview_enabled = False
    if _preview_enabled:
        try:
            OUTPUT_LIB_FREQ = os.path.join(RESULTS_DIR, "library_frequency.json")
            _weights = LOGIC.get("weights", {})
            _lib_words = {}
            for (lemma, reading), data in word_stats.items():
                _lib_words[f"{lemma}|{reading}"] = [
                    data.get("total_count", 0), data.get("high_count", 0),
                    data.get("low_count", 0), data.get("goal_count", 0),
                ]
            _lib_payload = {
                "settings": {
                    "min_freq": MIN_FREQ,
                    "weights": {
                        "high": _weights.get("high", 10),
                        "low": _weights.get("low", 5),
                        "goal": _weights.get("goal", 2),
                    },
                },
                "words": _lib_words,
            }
            with open(OUTPUT_LIB_FREQ, 'w', encoding='utf-8') as f:
                json.dump(_lib_payload, f, ensure_ascii=False)
            try:
                print(f"Saved library frequency map to {OUTPUT_LIB_FREQ} ({len(_lib_words)} words)")
            except UnicodeEncodeError:
                print("Saved library frequency map.")
        except Exception as e:
            # Never let the optional preview cache interfere with a normal run.
            print(f"Warning: Could not write library frequency map: {e}")

    # --- PROGRESSIVE REPORT PASS ---
    print("Generating Progressive Report...")
    progressive_rows = []
    # Work with a COPY of known words so we don't pollute the global set if we re-run logic, 
    # but here we just have one run.
    # We need a new set tracking "Learned in this session" to exclude from later files.
    
    # Start with initial known
    session_known = set(known_words_initial)
    session_lemmas = set(known_lemmas_initial) 
    
    for seq_idx, (file_path, label, weight) in enumerate(found_files, 1):
        filename = os.path.basename(file_path)
        # Reuse the (lemma, reading) multiset captured during the aggregation pass instead of
        # re-tokenizing. Deterministic: same tokenizer + same text => same tokens. The rare
        # cache-miss branch re-tokenizes, so behaviour is never wrong, only slower.
        file_counter = file_token_cache.get(file_path)
        if file_counter is None:
            file_counter = Counter((l, r) for (l, r, s) in tokenizer.tokenize(extract_text(file_path, language)))

        # 1. Calculate File Baselines
        file_total_tokens = 0
        file_baseline_known_count = 0     # Strictly initial known (JSON + Ignore)
        file_current_start_count = 0      # Baseline + Learned in previous files

        file_unknown_token_counts = Counter() # Count of each (lemma, reading) in THIS file

        for (lemma, reading), count in file_counter.items():
            file_total_tokens += count
            is_ignored = lemma in ignore_list
            is_single = skip_singles and len(lemma) == 1

            # Check strictly against initial known list
            is_baseline = is_ignored or is_single or ((lemma, reading) in known_words_initial) or (lemma in known_lemmas_initial)

            # Check against cumulative session known (includes previous files)
            is_session_known = is_ignored or is_single or ((lemma, reading) in session_known) or (lemma in session_lemmas)

            if is_baseline:
                file_baseline_known_count += count

            if is_session_known:
                file_current_start_count += count
            else:
                file_unknown_token_counts[(lemma, reading)] += count
        
        # 2. Identify and prepare unknown words
        file_new_words = set()
        file_rows_buffer = []
        
        for (lemma, reading), count in file_unknown_token_counts.items():
            if 'valid_lrs' in locals() and (lemma, reading) not in valid_lrs:
                continue
                
            # It's a new word for this progressive sequence
            tier_labels = get_tier_label(lemma, freq_data)
            tier_str = ";".join([f"{source}:{tier}" for source, tier in tier_labels]) if tier_labels else "Outside"
            stats = word_stats.get((lemma, reading), {
                "score": 0, "total_count": 0, 
                "high_count": 0, "low_count": 0, "goal_count": 0,
                "final_context_1": "", "final_context_2": "", "final_context_3": ""
            })
            
            if MIN_FREQ > 0 and stats["total_count"] < MIN_FREQ:
                continue

            file_rows_buffer.append({
                "Sequence": seq_idx,
                "Source File": filename,
                "Word": lemma,
                "Reading": reading,
                "Tier": tier_str,
                "Score": stats["score"],
                "Occurrences (Global)": stats["total_count"],
                "Occurrences (File)": count,
                "Count (High)": stats.get("high_count", 0),
                "Count (Low)": stats.get("low_count", 0),
                "Count (Goal)": stats.get("goal_count", 0),
            })
            
            # Dynamically attach all context strings currently tracked
            for k, v in stats.items():
                if k.startswith("final_context_"):
                    # Map final_context_N -> Context N
                    idx_str = k.replace("final_context_", "")
                    file_rows_buffer[-1][f"Context {idx_str}"] = v
                    
            file_new_words.add((lemma, reading))
        
        # 3. Sort by priority
        # This determines the order we "learn" them to reach coverage
        file_rows_buffer.sort(key=lambda x: (x["Score"], x["Occurrences (Global)"]), reverse=True)
        
        # 4. Calculate Progressive Understanding with Target Coverage
        current_known = file_current_start_count
        baseline_pct = (file_baseline_known_count / file_total_tokens * 100) if file_total_tokens > 0 else 0
        
        words_learned_this_file = set()
        
        for row in file_rows_buffer:
            start_pct = (current_known / file_total_tokens * 100) if file_total_tokens > 0 else 0
            
            # Helper to check if we met target
            if args.target_coverage > 0 and start_pct >= args.target_coverage:
                # Target met for this file! valid to stop here.
                # Words skipped here remain "unknown" for future files.
                break

            word_count_in_file = row["Occurrences (File)"]
            current_known += word_count_in_file
            
            end_pct = (current_known / file_total_tokens * 100) if file_total_tokens > 0 else 0
            
            row["Baseline %"] = round(baseline_pct, 2)
            row["Current %"] = round(start_pct, 2)
            row["New %"] = round(end_pct, 2)
            row["Known Count"] = current_known
            row["Total Count"] = file_total_tokens
            
            progressive_rows.append(row)
            
            # Track what we actually learned
            lemma = row["Word"]
            reading = row["Reading"]
            words_learned_this_file.add((lemma, reading))
            
        # After finishing the file, these words are now "Known" for the next file
        session_known.update(words_learned_this_file)
        session_lemmas.update([x[0] for x in words_learned_this_file])
        
    df_prog = pd.DataFrame(progressive_rows)
    if not df_prog.empty:
        df_prog.to_csv(OUTPUT_PROGRESSIVE, index=False, encoding='utf-8-sig')
        print(f"Saved progressive report to {OUTPUT_PROGRESSIVE}")
    else:
        print("No progressive words found (all known).")

    # --- VISUALIZER REMOVED ---
            
    # --- STATIC GENERATION ---
    if "--static" in sys.argv:
        try:
            try:
                from app import static_html_generator
            except ImportError:
                import static_html_generator
                
            print("\n---------------------------------------------------")
            print("Generating Static HTML...")
            static_html_generator.generate_static_html(theme=args.theme, zen_limit=args.zen_limit)
        except Exception as e:
            print(f"Error: Could not generate static HTML: {e}")

    if "--visualize" not in sys.argv and "--static" not in sys.argv:
        print("\nAnalysis complete.")
        print("Use '--visualize' to run the interactive server.")
        print("Use '--static' to generate a standalone HTML file.")

if __name__ == "__main__":
    main()
