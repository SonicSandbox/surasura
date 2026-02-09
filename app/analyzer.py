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
from collections import defaultdict, Counter
from datetime import datetime

from app.path_utils import get_user_file, get_resource

# --- Configuration ---
# Weights
WEIGHT_HIGH = 10
WEIGHT_LOW = 5
WEIGHT_GOAL = 2

# Filters
SKIP_SINGLE_CHARS = True
MIN_FREQ = 0  # Hide words with frequency <= MIN_FREQ

# Paths
USER_FILES_DIR = get_user_file("User Files")
DATA_DIR = get_user_file("data")

KNOWN_WORDS_FILE = os.path.join(USER_FILES_DIR, "KnownWord.json") 
BLACK_LIST_FILE = os.path.join(USER_FILES_DIR, "Blacklist.txt")
IGNORE_LIST_FILE = os.path.join(USER_FILES_DIR, "IgnoreList.txt")

RESULTS_DIR = get_user_file("results")
os.makedirs(RESULTS_DIR, exist_ok=True)

OUTPUT_CSV = os.path.join(RESULTS_DIR, "priority_learning_list.csv")
OUTPUT_STATS = os.path.join(RESULTS_DIR, "file_statistics.txt")
OUTPUT_PROGRESSIVE = os.path.join(RESULTS_DIR, "progressive_learning_list.csv")


# --- Classes & Functions ---

class JapaneseTokenizer:
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
        """Yields (sentence_string, list_of_filtered_tokens)"""
        current_sentence_tokens = []
        current_sentence_surface = []
        
        # Unidic-lite pos1: 
        # '補助記号' (punctuation)
        # '空白' (spaces)
        
        for word in self.tagger(text):
            surface = word.surface
            pos = word.feature.pos1
            
            # Boundary check
            is_boundary = surface in ['。', '！', '？', '!', '?', '\n']
            
            lemma = word.feature.lemma if word.feature.lemma else word.surface
            reading = word.feature.kana if word.feature.kana else ""
            
            current_sentence_surface.append(surface)
            if pos not in ['记号', '補助記号', '空白']:
                current_sentence_tokens.append((lemma, reading, word.surface))
            
            if is_boundary:
                s_text = "".join(current_sentence_surface).strip()
                if s_text:
                    yield s_text, current_sentence_tokens
                current_sentence_tokens = []
                current_sentence_surface = []
        
        # Flush remaining
        if current_sentence_surface:
            s_text = "".join(current_sentence_surface).strip()
            if s_text:
                yield s_text, current_sentence_tokens

def load_simple_list(file_path):
    if not os.path.exists(file_path):
        return set()
    with open(file_path, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())

def discover_yomitan_frequency_lists(user_files_dir):
    """
    Scan User Files directory for frequency_list_*.csv files.
    Returns a dictionary mapping frequency list name -> filepath.
    Example: frequency_list_Anime.csv -> {"Anime": "/path/to/frequency_list_Anime.csv"}
    """
    freq_lists = {}
    if not os.path.exists(user_files_dir):
        return freq_lists
    
    try:
        for filename in os.listdir(user_files_dir):
            if filename.startswith("frequency_list_") and filename.endswith(".csv"):
                # Extract name: frequency_list_Novel.csv -> Novel
                list_name = filename.replace("frequency_list_", "").replace(".csv", "")
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
                    word = row['Word']
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
    if not isinstance(rank, int) or rank <= 0:
        return "Outside"
    if rank <= 2500:
        return "1"
    elif rank <= 5000:
        return "2"
    elif rank <= 7500:
        return "3"
    elif rank <= 10000:
        return "4"
    else:
        return "5"

def load_known_words(json_path, tokenizer):
    print(f"Loading known words from {json_path}...")
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

def has_japanese(text):
    # Ranges for Hiragana, Katakana, and Kanji (Common and Rare)
    pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]')
    return bool(pattern.search(text))

def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext == '.srt':
        try:
            subs = pysrt.open(file_path)
            parts = []
            for sub in subs:
                # Filter out lines without Japanese characters
                # This removes English-only credits or technical markings
                lines = sub.text.splitlines()
                filtered_lines = []
                for l in lines:
                    if not has_japanese(l):
                        continue
                    # Remove furigana in parens: (れい) or （れい）
                    # Matches: (anything), （anything）
                    l = re.sub(r'[\(（].*?[\)）]', '', l)
                    filtered_lines.append(l)

                if filtered_lines:
                    # Join lines within a subtitle block with spaces to preserve word boundaries
                    block_text = " ".join(filtered_lines)
                    # Add a period (。) at the end only if it doesn't already end with sentence punctuation
                    if not block_text or block_text[-1] not in '。！？!?':
                        block_text += "。"
                    parts.append(block_text)
            text = "".join(parts)
        except Exception as e:
            print(f"Error reading SRT {file_path}: {e}")
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
        start = max(0, idx - 20)
        end = min(len(full_text), idx + 20)
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
    
    # These are handled manually above but good to have in help
    parser.add_argument("--visualize-only", action="store_true", help="Launch visualizer server")
    parser.add_argument("--static-only", action="store_true", help="Generate static HTML")
    parser.add_argument("--visualize", action="store_true", help="Launch visualizer after analysis")
    parser.add_argument("--static", action="store_true", help="Generate static HTML after analysis")
    parser.add_argument("--theme", type=str, default="default", help="Theme for static HTML (default, world-class, modern-light, zen-focus)")
    parser.add_argument("--zen-limit", type=int, default=50, help="Word limit for Zen Focus mode (25-125)")
    parser.add_argument("--target-coverage", type=int, default=0, help="Target cumulative coverage percent (0-100)")

    args, unknown = parser.parse_known_args()

    global SKIP_SINGLE_CHARS, MIN_FREQ
    
    # Logic: Default SKIP_SINGLE_CHARS is True. 
    # If --include-single-chars is present, set to False.
    if args.include_single_chars:
        SKIP_SINGLE_CHARS = False
        print("Configuration: Single character words INCLUDED.")
    else:
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

    print(f"\nLoading resources...")
    
    # 1. Load Resources
    tokenizer = JapaneseTokenizer()
    known_words_initial, known_lemmas_initial = load_known_words(KNOWN_WORDS_FILE, tokenizer)
    ignore_list = load_simple_list(IGNORE_LIST_FILE)
    black_list = load_simple_list(BLACK_LIST_FILE)
    ignore_list.update(black_list) # Merge blacklist into ignore list
    
    # Discover and load all yomitan frequency lists from User Files
    print("Scanning for frequency lists...")
    available_freq_lists = discover_yomitan_frequency_lists(USER_FILES_DIR)
    
    if not available_freq_lists:
        print("Warning: No frequency lists found in User Files/")
        print("Expected format: jiten_freq_*.zip")
    
    freq_data = {}
    for list_name, filepath in sorted(available_freq_lists.items()):
        freq_data[list_name] = load_yomitan_frequency_list(filepath)
    
    print(f"Found {len(freq_data)} frequency lists: {', '.join(sorted(freq_data.keys()))}")
    
    # 2. Define Scanning targets
    # ORDER MATTERS: High -> Low -> Goal
    scan_targets = [
        ("HighPriority", os.path.join(DATA_DIR, "HighPriority"), WEIGHT_HIGH),
        ("LowPriority", os.path.join(DATA_DIR, "LowPriority"), WEIGHT_LOW),
        ("GoalContent", os.path.join(DATA_DIR, "GoalContent"), WEIGHT_GOAL)
    ]
    
    word_stats = defaultdict(lambda: {
        "score": 0, "total_count": 0, "sources": set(), 
        "high_count": 0, "low_count": 0, "goal_count": 0,
        "first_context": "", 
        "best_extra_contexts": [], # List of (unknown_count, sentence_text)
        "surface": "",
        "min_seq": float('inf') # Track first appearance sequence index
    })
    
    file_stats = [] 
    
    # 3. Process Files (Aggregation Phase)
    # To handle progressive reporting correctly, we need a consistent order of all files found.
    # We want HighPriority files first, then Low, then Goal.
    # Within each category, we must respect the user's custom order from _order.json.

    def get_ordered_files(directory):
        """
        Recursively Get files from directory, respecting _order.json at each level.
        Returns a list of absolute file paths.
        """
        if not os.path.exists(directory):
            return []

        results = []
        
        # 1. Get all actual items in this directory
        try:
            items = os.listdir(directory)
        except Exception:
            return []
            
        # 2. Load order file
        order_file = os.path.join(directory, "_order.json")
        order = []
        if os.path.exists(order_file):
            try:
                with open(order_file, 'r', encoding='utf-8') as f:
                    order = json.load(f)
            except Exception:
                pass
        
        # 3. Sort items: Ordered items first, then the rest alphabetically
        # Create a map for rank to support fast lookup
        rank_map = {name: i for i, name in enumerate(order)}
        
        def sort_key(name):
            # Returns (is_unordered, rank_or_name)
            # Ordered items: (0, rank)
            # Unordered items: (1, name)
            if name in rank_map:
                return (0, rank_map[name])
            return (1, name)
            
        items.sort(key=sort_key)
        
        # 4. Process items
        for item in items:
            if item == "_order.json": continue
            
            full_path = os.path.join(directory, item)
            
            if os.path.isdir(full_path):
                # Recurse
                results.extend(get_ordered_files(full_path))
            elif os.path.isfile(full_path):
                if full_path.lower().endswith(('.txt', '.srt', '.epub', '.md')): # Added more extensions to be safe
                    results.append(full_path)
                    
        return results

    found_files = []
    
    for label, folder, weight in scan_targets:
        if not os.path.exists(folder):
            continue
            
        ordered_paths = get_ordered_files(folder)
        
        for path in ordered_paths:
            found_files.append((path, label, weight))
            
    print(f"Found {len(found_files)} files to process.")
    
    # --- AGGREGATION PASS ---
    for seq_idx, (file_path, label, weight) in enumerate(found_files, 1):
        try:
            print(f"Processing {os.path.basename(file_path)}...")
        except UnicodeEncodeError:
            print(f"Processing file {found_files.index((file_path, label, weight)) + 1}...")
        text = extract_text(file_path)
        
        file_total_words = 0
        file_known_words = 0
        
        for s_text, s_tokens in tokenizer.tokenize_sentences(text):
            # 1. Identify unknowns and calculate cost (relative to constant initial knowns)
            sentence_unknowns = []
            for lemma, reading, surface in s_tokens:
                # Skip tokens that contain no Japanese characters (e.g. SSA/ASS tags like {\an8},
                # timestamps, markup, or other ASCII-only tokens). These should not count
                # toward totals or be considered unknown words.
                if not has_japanese(lemma) and not has_japanese(surface):
                    continue

                file_total_words += 1
                if lemma in ignore_list:
                    file_known_words += 1
                    continue
                if SKIP_SINGLE_CHARS and len(lemma) == 1:
                    file_known_words += 1
                    continue
                is_known = (lemma, reading) in known_words_initial or (lemma in known_lemmas_initial)
                if is_known:
                    file_known_words += 1
                    continue
                sentence_unknowns.append((lemma, reading, surface))

            # Unique unknowns in this sentence for cost calculation
            unique_lrs = set((l, r) for l, r, s in sentence_unknowns)
            cost = len(unique_lrs)

            # 2. Update Stats for all unknown tokens in this sentence
            for lemma, reading, surface in sentence_unknowns:
                entry = word_stats[(lemma, reading)]
                entry["score"] += weight
                entry["total_count"] += 1
                entry["sources"].add(os.path.basename(file_path))
                entry["surface"] = surface
                entry["surface"] = surface
                if label == "HighPriority": entry["high_count"] += 1
                elif label == "LowPriority": entry["low_count"] += 1
                elif label == "GoalContent": entry["goal_count"] += 1
                
                # Track first appearance sequence
                if seq_idx < entry["min_seq"]:
                    entry["min_seq"] = seq_idx

            # 3. Update Best Contexts (once per unique unknown per sentence)
            for (lemma, reading) in unique_lrs:
                entry = word_stats[(lemma, reading)]
                if not entry["first_context"]:
                    entry["first_context"] = s_text
                else:
                    if s_text == entry["first_context"]: continue
                    
                    # Maintain top 2 easiest sentences (lowest cost)
                    best = entry["best_extra_contexts"]
                    best.append((cost, s_text))
                    best.sort(key=lambda x: x[0])
                    entry["best_extra_contexts"] = best[:2]
        
        coverage = (file_known_words / file_total_words * 100) if file_total_words > 0 else 0
        file_stats.append({
            "File": os.path.basename(file_path),
            "Total Words": file_total_words,
            "Known Count": file_known_words,
            "Coverage (%)": round(coverage, 2)
        })

    # Output Priority CSV
    output_rows = []
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
            "Context 1": data.get("first_context", "").strip(),
            "Context 2": data["best_extra_contexts"][0][1].strip() if len(data["best_extra_contexts"]) > 0 else "",
            "Context 3": data["best_extra_contexts"][1][1].strip() if len(data["best_extra_contexts"]) > 1 else "",
            "Count (High)": data["high_count"],
            "Count (Low)": data["low_count"],
            "Count (Goal)": data["goal_count"],
            "Sources": source_display, # Moved to end
            "_MinSeq": data["min_seq"] # Helper for sorting
        }
        output_rows.append(row)
        
    df = pd.DataFrame(output_rows)
    if not df.empty:
        # Sort Logic: Primary = Score (Desc), Secondary = First Appearance (Asc)
        # To do mixed sort in pandas:
        # We can sort by ["Score", "MinSeq"], with ascending=[False, True]
        # But we need "MinSeq" column first.
        
        # Add MinSeq to DF temporarily for sorting if not present (it isn't in output_rows)
        # Actually, let's just make sure output_rows has it or sort before DF creation.
        # It's easier to sort the list of dicts.
        output_rows.sort(key=lambda x: (-x["Score"], x["_MinSeq"]))
        
        # Re-create DF from sorted list
        df = pd.DataFrame(output_rows)
        
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

        df_display.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        print(f"Saved priority list to {OUTPUT_CSV}")
    else:
        print("No unknown words found!")

    # Output Stats
    OUTPUT_STATS_JSON = os.path.join(RESULTS_DIR, "file_statistics.json")
    with open(OUTPUT_STATS, 'w', encoding='utf-8') as f:
        f.write("--- File Statistics ---\n")
        f.write(f"Configuration: Skip Single Chars = {SKIP_SINGLE_CHARS}\n\n")
        for stat in file_stats:
            f.write(f"File: {stat['File']}\n")
            f.write(f"  Total Words: {stat['Total Words']}\n")
            f.write(f"  Known Words: {stat['Known Count']}\n")
            f.write(f"  Coverage: {stat['Coverage (%)']}%\n")
            f.write("\n")
    print(f"Saved stats to {OUTPUT_STATS}")
    
    with open(OUTPUT_STATS_JSON, 'w', encoding='utf-8') as f:
        json.dump(file_stats, f, indent=4, ensure_ascii=False)
    print(f"Saved JSON stats to {OUTPUT_STATS_JSON}")
    
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
        text = extract_text(file_path)
        tokens = tokenizer.tokenize(text)
        
        # 1. Calculate File Baselines
        file_total_tokens = 0
        file_baseline_known_count = 0     # Strictly initial known (JSON + Ignore)
        file_current_start_count = 0      # Baseline + Learned in previous files
        
        file_unknown_token_counts = Counter() # Count of each (lemma, reading) in THIS file
        
        for lemma, reading, surface in tokens:
            file_total_tokens += 1
            is_ignored = lemma in ignore_list
            is_single = SKIP_SINGLE_CHARS and len(lemma) == 1
            
            # Check strictly against initial known list
            is_baseline = is_ignored or is_single or ((lemma, reading) in known_words_initial) or (lemma in known_lemmas_initial)
            
            # Check against cumulative session known (includes previous files)
            is_session_known = is_ignored or is_single or ((lemma, reading) in session_known) or (lemma in session_lemmas)
            
            if is_baseline:
                file_baseline_known_count += 1
            
            if is_session_known:
                file_current_start_count += 1
            else:
                file_unknown_token_counts[(lemma, reading)] += 1
        
        # 2. Identify and prepare unknown words
        file_new_words = set()
        file_rows_buffer = []
        
        for (lemma, reading), count in file_unknown_token_counts.items():
            # It's a new word for this progressive sequence
            tier_labels = get_tier_label(lemma, freq_data)
            tier_str = ";".join([f"{source}:{tier}" for source, tier in tier_labels]) if tier_labels else "Outside"
            stats = word_stats.get((lemma, reading), {
                "score": 0, "total_count": 0, 
                "first_context": "", "best_extra_contexts": []
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
                "Context 1": stats.get("first_context", "").strip(),
                "Context 2": stats["best_extra_contexts"][0][1].strip() if len(stats["best_extra_contexts"]) > 0 else "",
                "Context 3": stats["best_extra_contexts"][1][1].strip() if len(stats["best_extra_contexts"]) > 1 else "",
            })
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
