import os
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import glob
import re
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
IGNORE_LIST_FILE = os.path.join(USER_FILES_DIR, "IgnoreList.txt")
TIER_1_FILE = os.path.join(USER_FILES_DIR, "Netflix_Frequency_Tier_1.txt")
TIER_2_FILE = os.path.join(USER_FILES_DIR, "Netflix_Frequency_Tier_2.txt")
TIER_3_FILE = os.path.join(USER_FILES_DIR, "Netflix_Frequency_Tier_3.txt")


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

def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext == '.srt':
        try:
            subs = pysrt.open(file_path)
            parts = []
            for sub in subs:
                parts.append(sub.text)
            text = "\n".join(parts)
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

def get_tier_label(word, tiers):
    if word in tiers[1]: return "1"
    if word in tiers[2]: return "2"
    if word in tiers[3]: return "3"
    return "Outside"

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
    parser.add_argument("--min-freq", type=int, default=0, help="Hide words with frequency <= this value (default 0)")
    
    # These are handled manually above but good to have in help
    parser.add_argument("--visualize-only", action="store_true", help="Launch visualizer server")
    parser.add_argument("--static-only", action="store_true", help="Generate static HTML")
    parser.add_argument("--visualize", action="store_true", help="Launch visualizer after analysis")
    parser.add_argument("--static", action="store_true", help="Generate static HTML after analysis")
    parser.add_argument("--theme", type=str, default="default", help="Theme for static HTML (default, world-class, modern-light, zen-focus)")
    parser.add_argument("--zen-limit", type=int, default=50, help="Word limit for Zen Focus mode (25-125)")

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
        print(f"Configuration: Words with frequency <= {MIN_FREQ} EXCLUDED.")
    elif args.exclude_freq_one:
        # Backward compatibility
        MIN_FREQ = 1
        print("Configuration: Frequency 1 words EXCLUDED (via flag).")
    else:
        MIN_FREQ = 0
        print("Configuration: All frequencies INCLUDED (Default).")

    print(f"\nLoading resources...")
    
    # 1. Load Resources
    tokenizer = JapaneseTokenizer()
    known_words_initial, known_lemmas_initial = load_known_words(KNOWN_WORDS_FILE, tokenizer)
    ignore_list = load_simple_list(IGNORE_LIST_FILE)
    
    tiers = {
        1: load_simple_list(TIER_1_FILE),
        2: load_simple_list(TIER_2_FILE),
        3: load_simple_list(TIER_3_FILE)
    }
    
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
        "surface": ""
    })
    
    file_stats = [] 
    
    # 3. Process Files (Aggregation Phase)
    # To handle progressive reporting correctly, we need a consistent order of all files found.
    # We want HighPriority files first, then Low, then Goal.
    # Within each category, sort alphabetically.
    
    found_files = []
    
    priority_order = {
        "HighPriority": 0,
        "LowPriority": 1,
        "GoalContent": 2
    }
    
    for label, folder, weight in scan_targets:
        if not os.path.exists(folder):
            continue
        # Get files
        f = glob.glob(os.path.join(folder, "**"), recursive=True)
        f = [x for x in f if not os.path.isdir(x) and x.lower().endswith(('.txt', '.srt'))]
        
        # Sort ONLY this folder's files alphabetically
        f.sort(key=lambda x: os.path.basename(x))
        
        for path in f:
            found_files.append((path, label, weight))
            
    # found_files is now implicitly sorted by Priority (due to loop order) and then Name (due to sort).
    # We do NOT sort found_files again globally, or we lose priority order.
    
    print(f"Found {len(found_files)} files to process.")

    # --- AGGREGATION PASS ---
    for file_path, label, weight in found_files:
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
                file_total_words += 1
                if lemma in ignore_list: continue
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
                if label == "HighPriority": entry["high_count"] += 1
                elif label == "LowPriority": entry["low_count"] += 1
                elif label == "GoalContent": entry["goal_count"] += 1

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
        if MIN_FREQ > 0 and data["total_count"] <= MIN_FREQ:
            continue

        tier_label = get_tier_label(lemma, tiers)
        source_display = group_sources(data["sources"])

        row = {
            "Word": lemma,
            "Reading": reading,
            "Tier": tier_label,
            "Score": data["score"],
            "Occurrences": data["total_count"],
            "Context 1": data.get("first_context", "").strip(),
            "Context 2": data["best_extra_contexts"][0][1].strip() if len(data["best_extra_contexts"]) > 0 else "",
            "Context 3": data["best_extra_contexts"][1][1].strip() if len(data["best_extra_contexts"]) > 1 else "",
            "Count (High)": data["high_count"],
            "Count (Low)": data["low_count"],
            "Count (Goal)": data["goal_count"],
            "Sources": source_display # Moved to end
        }
        output_rows.append(row)
        
    df = pd.DataFrame(output_rows)
    if not df.empty:
        df = df.sort_values(by="Score", ascending=False)
        df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        print(f"Saved priority list to {OUTPUT_CSV}")
    else:
        print("No unknown words found!")

    # Output Stats
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
            tier_label = get_tier_label(lemma, tiers)
            stats = word_stats.get((lemma, reading), {
                "score": 0, "total_count": 0, 
                "first_context": "", "best_extra_contexts": []
            })
            
            if MIN_FREQ > 0 and stats["total_count"] <= MIN_FREQ:
                continue

            file_rows_buffer.append({
                "Sequence": seq_idx,
                "Source File": filename,
                "Word": lemma,
                "Reading": reading,
                "Tier": tier_label,
                "Score": stats["score"],
                "Occurrences (Global)": stats["total_count"],
                "Occurrences (File)": count,
                "Context 1": stats.get("first_context", "").strip(),
                "Context 2": stats["best_extra_contexts"][0][1].strip() if len(stats["best_extra_contexts"]) > 0 else "",
                "Context 3": stats["best_extra_contexts"][1][1].strip() if len(stats["best_extra_contexts"]) > 1 else "",
            })
            file_new_words.add((lemma, reading))
        
        # 3. Sort by priority
        file_rows_buffer.sort(key=lambda x: (x["Score"], x["Occurrences (Global)"]), reverse=True)
        
        # 4. Calculate Progressive Understanding
        current_known = file_current_start_count
        baseline_pct = (file_baseline_known_count / file_total_tokens * 100) if file_total_tokens > 0 else 0
        
        for row in file_rows_buffer:
            start_pct = (current_known / file_total_tokens * 100) if file_total_tokens > 0 else 0
            
            word_count_in_file = row["Occurrences (File)"]
            current_known += word_count_in_file
            
            end_pct = (current_known / file_total_tokens * 100) if file_total_tokens > 0 else 0
            
            row["Baseline %"] = round(baseline_pct, 2)
            row["Current %"] = round(start_pct, 2)
            row["New %"] = round(end_pct, 2)
            
        progressive_rows.extend(file_rows_buffer)

        # After finishing the file, these words are now "Known" for the next file
        session_known.update(file_new_words)
        session_lemmas.update([x[0] for x in file_new_words])
        
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
