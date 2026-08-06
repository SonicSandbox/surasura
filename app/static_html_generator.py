import os
import re
import sys
import json
import bisect
import pandas as pd
import webbrowser

from app.path_utils import get_user_file, get_resource, SIDECAR_SUFFIX
from app import settings_manager

# Configuration
RESULTS_DIR = get_user_file("results")
PROGRESSIVE_CSV = os.path.join(RESULTS_DIR, "progressive_learning_list.csv")
PRIORITY_CSV = os.path.join(RESULTS_DIR, "priority_learning_list.csv")
OUTPUT_FILE = os.path.join(RESULTS_DIR, "reading_list_static.html")
# Resources (Templates)
WEB_APP_FILE = get_resource(os.path.join("templates", "web_app.html"))

def open_as_app(file_path):
    """
    Attempts to open the HTML file in a 'tightened' browser window (App Mode).
    Falls back to the default browser if Chrome is not found.
    """
    import subprocess
    url = f"file://{os.path.abspath(file_path)}"
    
    if sys.platform == "win32":
        # Search for Chrome which supports the --app flag
        possible_browsers = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        ]
        
        for browser_path in possible_browsers:
            if os.path.exists(browser_path):
                try:
                    # Launch in app mode
                    subprocess.Popen([browser_path, f"--app={url}"])
                    return
                except Exception as e:
                    print(f"Warning: Failed to launch {browser_path} in app mode: {e}")
    
    # Fallback to standard browser behavior
    webbrowser.open(url)


def open_report(app_mode=False):
    """Open the ALREADY-generated report without re-rendering it — the fast path when neither the
    analysis nor the presentation (theme / Zen limit / window) changed. Returns False if there is
    no report on disk yet (caller should render instead)."""
    if not os.path.exists(OUTPUT_FILE):
        return False
    if app_mode:
        open_as_app(OUTPUT_FILE)
    else:
        webbrowser.open(f"file://{os.path.abspath(OUTPUT_FILE)}")
    return True


def compress_list_of_dicts(data_list):
    """
    Compresses a list of dictionaries into a compact format:
    {"keys": ["key1", "key2", ...], "rows": [["val1", "val2", ...], ...]}
    Reduces JSON payload size by removing repetitive keys.
    """
    if not data_list:
        return {"keys": [], "rows": []}
    
    # Extract superset of all keys in case some dicts are missing keys
    keys_set = set()
    for item in data_list:
        keys_set.update(item.keys())
    
    keys = list(keys_set)
    # Important: sort keys to ensure consistent ordering though not strictly required
    keys.sort() 
    
    rows = []
    for item in data_list:
        row = []
        for key in keys:
            row.append(item.get(key, None))
        rows.append(row)
        
    return {"keys": keys, "rows": rows}

def _load_source_map():
    """results/sources.json — {relative path: {name, type}} written by the analyzer. Absent for
    results produced before the source badge existed; the report then just shows no badges."""
    path = os.path.join(RESULTS_DIR, "sources.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"Warning: could not read source table: {e}")
        return {}


class AnchorFinder:
    """Finds a snippet of a sentence that appears VERBATIM in its source file.

    The sentence in the report is not the sentence in the file. The tokenizer drops every space when
    it rebuilds a sentence, so a subtitle line written as

        そうだ 女｡ お前に話がある｡

    is stored as `そうだ女｡お前に話がある。` — and the analyzer also appends `。` to cues that lack
    punctuation and strips Latin characters. Any anchor guessed from the stored text alone therefore
    spans a gap the file doesn't have, and a short guess can land on the WRONG line.

    So we check candidate windows against the real bytes and return one only if it occurs EXACTLY
    once — a unique anchor cannot scroll to the wrong place. No match means no deep link, which is
    the honest outcome rather than a link that silently misses.

    Files are read once and cached; work is bounded to a few `str.find` calls per sentence, and the
    whole pass only runs when the source badge is switched on.
    """

    MIN_LEN = 5          # shorter than this is too generic to point at anything
    MAX_ANCHOR = 40      # bounds the whitespace-tolerant pattern
    MAX_CHUNKS = 6       # a sentence can span a dozen cues; a few of the longest is plenty

    # Subtitle cue headers. SRT: '00:01:31,083 --> 00:01:33,118'.
    # ASS/SSA: 'Dialogue: 0,0:01:31.08,0:01:33.11,Default,,...'.
    _SRT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->")
    _ASS_TIME = re.compile(r"^Dialogue:[^,]*,\s*(\d{1,2}):(\d{2}):(\d{2})[.:](\d{1,2})", re.M)

    def __init__(self, cache_path=None):
        self._cache = {}
        self._cues = {}
        self._sidecars = {}
        # Where each anchor was found. anchor() already located it; cue_time() used to scan the
        # whole file again to rediscover the same offset, which was the single biggest cost in the
        # pass (0.82s of 1.66s on a 1,500-file library).
        self._pos = {}
        # Optional on-disk memo so a RE-render (theme change, Words Per Day) doesn't redo the work.
        self._cache_path = cache_path
        self._memo = self._load_memo()
        self._memo_dirty = False
        self._sigs = {}        # path -> (mtime, size), so the freshness check is one stat per file
        self._entries = {}     # path -> its validated memo entry, so that check happens once too

    def _raw(self, path):
        if path not in self._cache:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    self._cache[path] = f.read()
            except OSError:
                self._cache[path] = ""
        return self._cache[path]

    def _unique(self, raw, needle, path=None):
        """Present exactly once — anything else could scroll to the wrong line. Remembers where."""
        first = raw.find(needle)
        if first == -1 or raw.find(needle, first + 1) != -1:
            return False
        if path is not None:
            self._pos[(path, needle)] = first
        return True

    @staticmethod
    def _loose(raw, needle):
        """The file's own wording for `needle`, allowing whitespace the tokenizer dropped. Empty if
        absent or ambiguous."""
        pattern = r"\s*".join(re.escape(ch) for ch in needle)
        found = None
        for match in re.finditer(pattern, raw):
            if found is not None:
                return ""       # more than one place it could be
            found = match.group(0)
        return found or ""

    # -- on-disk memo ------------------------------------------------------------------------- #
    # A re-render (theme, Zen limit, Words Per Day) reruns this whole pass over unchanged files for
    # unchanged sentences. Remembering the answers turns every render after the first into a lookup.
    #
    # Deliberately NOT stored as CSV columns from the analyzer: `source_display` is excluded from the
    # run-signature on purpose, so turning the badge on would not re-run the analysis and the columns
    # would never appear. A memo sidesteps that — no analysis change, no forced re-analysis.
    def _load_memo(self):
        if not self._cache_path:
            return {}
        try:
            with open(self._cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}          # absent or corrupt: just recompute

    def _file_sig(self, path):
        """(mtime, size), cached — this is asked once per SENTENCE, and a stat each time was
        measurably worse than the lookup it guards."""
        if path not in self._sigs:
            try:
                st = os.stat(path)
                self._sigs[path] = [st.st_mtime, st.st_size]
            except OSError:
                self._sigs[path] = None
        return self._sigs[path]

    def resolve(self, abs_path, sentence):
        """(anchor, cue_seconds) for a sentence, memoised across renders.

        A file's entries are dropped whenever its (mtime, size) changes, so an edited source can
        never serve a stale anchor."""
        entry = self._entries.get(abs_path)
        if entry is None:
            entry = self._memo.get(abs_path)
            if entry is None or entry.get("sig") != self._file_sig(abs_path):
                entry = {"sig": self._file_sig(abs_path), "a": {}}
                self._memo[abs_path] = entry
                self._memo_dirty = True
            self._entries[abs_path] = entry

        hit = entry["a"].get(sentence)
        if hit is not None:
            return hit[0], hit[1]

        anchor = self.anchor(abs_path, sentence)
        at = self.cue_time(abs_path, anchor) if anchor else None
        entry["a"][sentence] = [anchor, at]
        self._memo_dirty = True
        return anchor, at

    def save_memo(self):
        """Persist the memo, keeping ONLY the files this render actually used.

        Content leaves a library constantly — graduated, removed, renamed by a tier move — and
        without this the file would accumulate their entries forever. Best-effort: losing the memo
        only costs time on the next render."""
        if not self._cache_path:
            return
        live = {path: entry for path, entry in self._memo.items() if path in self._entries}
        # Write when something was computed OR when files dropped out — a render that only REMOVES
        # entries leaves nothing "dirty", and skipping it would keep them forever.
        if not self._memo_dirty and len(live) == len(self._memo):
            return
        try:
            tmp = self._cache_path + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(live, f, ensure_ascii=False)
            os.replace(tmp, self._cache_path)
        except Exception as e:
            print(f"Warning: could not save the anchor cache: {e}")

    def sidecar(self, path):
        """The cue sidecar beside a YouTube transcript ('foo.txt' -> 'foo.surasura.json'), or {}.

        Written by the downloader. Absent for transcripts pulled before the feature existed — those
        fall back to opening the video at 0:00 via the [videoID] in the filename."""
        if path not in self._sidecars:
            data = {}
            try:
                with open(os.path.splitext(path)[0] + SIDECAR_SUFFIX, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                pass
            self._sidecars[path] = data
        return self._sidecars[path]

    def _cue_index(self, path):
        """(offsets, seconds) for every cue in a timed file — parallel ascending lists.

        Subtitles carry their timings inline; a YouTube transcript is plain prose whose timings live
        in its sidecar, so the cue texts are located in the file to give them offsets. Anything with
        neither returns empty, which is how prose opts out of timestamps."""
        if path not in self._cues:
            offsets, seconds = [], []
            low = path.lower()
            if low.endswith(('.srt', '.ass', '.ssa')):
                raw = self._raw(path)
                pattern = self._ASS_TIME if low.endswith(('.ass', '.ssa')) else self._SRT_TIME
                for match in pattern.finditer(raw):
                    hh, mm, ss, _frac = match.groups()
                    offsets.append(match.end())
                    seconds.append(int(hh) * 3600 + int(mm) * 60 + int(ss))
            else:
                cues = self.sidecar(path).get('cues') or []
                if cues:
                    raw, pos = self._raw(path), 0
                    for entry in cues:
                        try:
                            text, sec = entry[0], int(entry[1])
                        except (TypeError, ValueError, IndexError, KeyError):
                            continue
                        if not isinstance(text, str) or not text:
                            continue      # a hand-edited or truncated sidecar must not crash a render
                        at = raw.find(text, pos)
                        if at == -1:
                            continue      # cue text was cleaned differently — skip, don't guess
                        offsets.append(at)
                        seconds.append(sec)
                        pos = at + len(text)
            self._cues[path] = (offsets, seconds)
        return self._cues[path]

    def cue_time(self, abs_path, anchor):
        """Start time in whole seconds of the subtitle cue containing `anchor`, or None.

        The anchor is verbatim file text, so its offset places it inside exactly one cue — no
        guesswork, and no change to how the file was tokenized."""
        offsets, seconds = self._cue_index(abs_path)
        if not offsets or not anchor:
            return None
        # anchor() already located this; only fall back to scanning when called standalone.
        pos = self._pos.get((abs_path, anchor))
        if pos is None:
            pos = self._raw(abs_path).find(anchor)
        if pos == -1:
            return None
        i = bisect.bisect_right(offsets, pos) - 1
        return seconds[i] if i >= 0 else None

    def anchor(self, abs_path, sentence):
        """A snippet of `sentence` that occurs exactly once in the file, or "" if there is none."""
        raw = self._raw(abs_path)
        text = (sentence or "").strip()
        if not raw or len(text) < self.MIN_LEN:
            return ""

        # The analyzer appends '。' at every cue boundary, so splitting there recovers the original
        # per-cue chunks — each of which was one line (or one line's worth) of the file.
        chunks = sorted({c for c in text.split("。") if len(c) >= self.MIN_LEN},
                        key=len, reverse=True)[:self.MAX_CHUNKS]
        if not chunks:
            return ""

        # 1. Verbatim. Prose is stored exactly as written, so books and transcripts stop here.
        for chunk in chunks:
            if self._unique(raw, chunk, abs_path):
                return chunk

        # 2. Whitespace-tolerant. Anime subtitles space their phrases ('そうだ 女｡ お前に話がある｡')
        #    and the tokenizer removed those spaces, so match with optional gaps.
        for chunk in chunks:
            verbatim = self._loose(raw, chunk[:self.MAX_ANCHOR])
            if not verbatim:
                continue
            # Prefer a gap-free run of what we matched: a fragment with no whitespace in it is the
            # most reliable thing to hand a browser.
            for run in sorted(verbatim.split(), key=len, reverse=True):
                if len(run) >= self.MIN_LEN and self._unique(raw, run, abs_path):
                    return run
            return " ".join(verbatim.split())
        return ""


# Tier folders are plumbing, not something the learner thinks in — they think in books and series.
_TIER_BUCKETS = ("HighPriority", "LowPriority", "GoalContent", "Graduated", "Processed")


# The 11-char video id ends the filename, allowing for the `_<timestamp>` suffixes Graduate/Demote
# add on a name collision. Anchored so a fansub release tag can't be mistaken for one — same rule as
# path_utils.infer_source_type, which decides whether a file is a YouTube source in the first place.
_VIDEO_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\][\s_()\-.\d]*$")


def _video_id(rel_path, meta=None):
    """The YouTube video id for a source, or "".

    Prefers what the downloader recorded in the cue sidecar; falls back to the filename, which is
    how transcripts pulled before sidecars existed can still open their video (at 0:00)."""
    if meta and meta.get("video_id"):
        return str(meta["video_id"])
    stem = os.path.splitext(os.path.basename(str(rel_path)))[0]
    match = _VIDEO_ID_RE.search(stem)
    return match.group(1) if match else ""


def _group_label(rel_path):
    """Badge hover text: the file plus the group (folder) it belongs to, e.g.
    'test_book/chapter_1.txt'. A loose file in a tier just shows its own name."""
    parts = [p for p in str(rel_path).replace("\\", "/").split("/") if p]
    if parts and parts[0] in _TIER_BUCKETS:
        parts = parts[1:]
    return "/".join(parts) if parts else str(rel_path)


def _intern_sources(records, source_map, table, index, finder=None, audio_probe=None):
    """Replace every 'Src N' path in `records` with an index into `table` (built as we go).

    The CSVs carry the readable relative path so exports stay human-readable, but a big library
    repeats the same few hundred paths across tens of thousands of sentences — interning keeps the
    injected payload to one small int per sentence instead of a full path string.

    Table rows are compact arrays: [name, type, fullPath, groupLabel]. The badge DISPLAYS `name`,
    HOVERS `groupLabel` (group/file — enough to place the sentence without a wall of path), and
    COPIES `fullPath` (absolute), so the clipboard contents paste straight into Explorer. Results
    made before sources.json carried absolute paths fall back to the relative one.

    With a `finder`, each sentence also gets a `Frag N` — a snippet verified to occur exactly once
    in the source file, which the report turns into a scroll-to-text link. Deliberately NOT named
    "Context …": both templates collect example sentences with startsWith('Context ')."""
    for rec in records:
        for key in [k for k in rec if k.startswith("Src ")]:
            val = rec.get(key)
            if val is None or val == "" or (isinstance(val, float) and pd.isna(val)):
                rec[key] = None
                continue
            val = str(val)
            idx = index.get(val)
            if idx is None:
                idx = len(table)
                index[val] = idx
                meta = source_map.get(val, {})
                abs_path = meta.get("abs") or val
                # A YouTube source gets its video id, which turns the badge into a link that opens
                # the video (at the sentence's moment when the cue times are known).
                vid = ""
                if (meta.get("type") or "") == "youtube":
                    side = finder.sidecar(abs_path) if finder is not None else None
                    vid = _video_id(val, side)
                table.append([meta.get("name") or os.path.basename(val),
                              meta.get("type") or "text",
                              abs_path,
                              _group_label(val),
                              vid])
            rec[key] = idx

            n = key[4:]                                      # "Src 2" -> "2"
            sentence = rec.get(f"Context {n}") if (finder is not None or audio_probe is not None) else None

            if finder is not None:
                if isinstance(sentence, str) and sentence:
                    frag, at = finder.resolve(table[idx][2], sentence)
                    if frag:
                        rec[f"Frag {n}"] = frag
                        # Subtitles/transcripts: the cue this sentence sits in, shown on hover.
                        if at is not None:
                            rec[f"At {n}"] = at

            # Optional speech module: mark sentences whose audio is already on disk, so the badge
            # can show that clicking will play instantly instead of pausing to generate. Named
            # "Aud N", NOT "Context …" — both templates collect example sentences with
            # startsWith('Context ') and would render such a column as another example.
            if audio_probe is not None and isinstance(sentence, str) and sentence:
                if audio_probe(sentence):
                    rec[f"Aud {n}"] = 1


def generate_static_html(theme="default", app_mode=False, zen_limit=0):
    print(f"Generating static HTML (Theme: {theme})...")
    
    # Pre-load settings
    try:
        settings = settings_manager.load_settings()
        target_lang = settings.get("target_language", "ja")
    except Exception:
        settings = {}
        target_lang = "ja"
    data = {
        "progressive": [],
        "priority": []
    }

    # Per-sentence source badge: build ONE interned table shared by both views (see _intern_sources).
    source_map = _load_source_map()
    source_table = []
    source_index = {}
    # Verifying scroll-to-text anchors means reading every source file, so only do it when the badge
    # is actually switched on — a run with it off pays nothing.
    source_finder = (AnchorFinder(cache_path=os.path.join(RESULTS_DIR, "anchor_cache.json"))
                     if settings.get("source_display", "off") != "off" else None)

    # Optional speech module: which sentences already have generated audio. Gated on the badge
    # being visible, since the badge is the only thing that would show it.
    audio_probe = None
    if settings.get("source_display", "off") != "off":
        try:
            import modules.koe as _koe_probe
            audio_probe = _koe_probe.cached_probe(target_lang)
        except Exception:
            audio_probe = None

    # Load File Statistics
    STATS_JSON = os.path.join(RESULTS_DIR, "file_statistics.json")
    stats_map = {}
    if os.path.exists(STATS_JSON):
        try:
            with open(STATS_JSON, 'r', encoding='utf-8') as f:
                stats = json.load(f)
                for s in stats:
                    stats_map[s["File"]] = s
        except Exception as e:
            print(f"Error loading stats JSON: {e}")

    # Track overall order from statistics
    all_files_order = []
    if os.path.exists(STATS_JSON):
        try:
            with open(STATS_JSON, 'r', encoding='utf-8') as f:
                stats = json.load(f)
                all_files_order = [s["File"] for s in stats]
        except: pass

    # Load Progressive
    if os.path.exists(PROGRESSIVE_CSV):
        try:
            df = pd.read_csv(PROGRESSIVE_CSV)
            # Group by Source File
            files_order = df.groupby("Source File")["Sequence"].min().sort_values().index.tolist()
            
                
            grouped = df.groupby("Source File")
            for filename in files_order:
                group = grouped.get_group(filename)
                words = group.to_dict(orient="records")
                _intern_sources(words, source_map, source_table, source_index, source_finder,
                                audio_probe)
                compressed_words = compress_list_of_dicts(words)
                
                # Get total words from stats if available
                total_words = stats_map.get(filename, {}).get("Total Words", 0)
                
                # Determine if Goal Content
                is_goal_content = False
                try:
                    from app.path_utils import get_user_files_path
                    # GoalContent is in User Files/<lang>/GoalContent
                    goal_dir = os.path.join(get_user_files_path(target_lang), "GoalContent")
                    
                    # Check if file exists in GoalContent
                    if os.path.exists(os.path.join(goal_dir, filename)):
                        is_goal_content = True
                except Exception:
                    pass

                data["progressive"].append({
                    "filename": filename,
                    "words": compressed_words,
                    "total_words": total_words,
                    "is_goal_content": is_goal_content
                })
        except Exception as e:
            print(f"Error loading progressive CSV: {e}")

    data["completed_files"] = []
    
    # specific progressive files
    prog_filenames = {item["filename"] for item in data["progressive"]}
    
    # Find files in stats but not in progressive
    for fname, fstat in stats_map.items():
        if fname not in prog_filenames:
            data["completed_files"].append({
                "filename": fname,
                "stats": fstat
            })

    # Load Priority
    if os.path.exists(PRIORITY_CSV):
        try:
            df = pd.read_csv(PRIORITY_CSV)
            raw_priority = df.to_dict(orient="records")
            _intern_sources(raw_priority, source_map, source_table, source_index, source_finder,
                            audio_probe)
            data["priority"] = compress_list_of_dicts(raw_priority)
        except Exception as e:
            print(f"Error loading priority CSV: {e}")

    # Every source is resolved by now — persist so the next render is a lookup, not a rescan.
    if source_finder is not None:
        source_finder.save_memo()

    data["file_order"] = all_files_order

    # Zen Mode Limit (Slicing)
    if "zen" in theme.lower() and zen_limit > 0:
        print(f"Applying Zen Mode Limit: {zen_limit} words")
        count = 0
        new_progressive = []
        for item in data["progressive"]:
            if count >= zen_limit:
                break
            
            if 'rows' in item["words"]:
                # Compressed dictionary
                words = item["words"]["rows"]
            else:
                words = item["words"]
                
            needed = zen_limit - count
            
            if len(words) > needed:
                if 'rows' in item["words"]:
                    item["words"]["rows"] = words[:needed]
                else:
                    item["words"] = words[:needed]
                new_progressive.append(item)
                count += needed
                break
            else:
                new_progressive.append(item)
                count += len(words)
        
        data["progressive"] = new_progressive

    # 2. Read Template
    # Accept the display name ("Zen Mode", from View Vocab Journey) and the theme id
    # ("zen-focus", forwarded by the analyzer on Generate Journey) so both paths pick Zen.
    if theme in ("Zen Mode", "zen-focus"):
        WEB_APP_FILE = get_resource(os.path.join("templates", "zen_app.html"))
    else:
        WEB_APP_FILE = get_resource(os.path.join("templates", "web_app.html"))

    if not os.path.exists(WEB_APP_FILE):
        print(f"Error: Template file {WEB_APP_FILE} not found.")
        return

    with open(WEB_APP_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 3. Inject Data, Theme, and Favicon
    import base64
    from app.path_utils import get_icon_path
    
    # Load Logic Settings for injection
    logic_settings = {}
    target_lang = "ja" # Default
    theme_map = {
        'Default (Dark)': 'default',
        'Dark Flow': 'world-class',
        'Midnight (Vibrant)': 'midnight-vibrant',
        'Modern Light': 'modern-light',
        'Zen Mode': 'zen-focus',
        'default': 'default',
        'world-class': 'world-class',
        'midnight-vibrant': 'midnight-vibrant',
        'modern-light': 'modern-light'
    }
    applied_theme = theme_map.get(theme, theme)

    try:
        settings = settings_manager.load_settings()
        logic_settings = settings.get("logic", {})
        target_lang = settings.get("target_language", "ja")
        
        # If theme is 'default', try to load from settings and MAP it
        if applied_theme == "default":
            raw_theme = settings.get("theme", "default")
            applied_theme = theme_map.get(raw_theme, 'default')
    except Exception as e:
        print(f"Warning: Could not load logic settings for HTML injection: {e}")

    # Escape "</" so a literal "</script>" in user content (filenames / context sentences)
    # cannot close the inline <script> block early and blank the whole report.
    json_str = json.dumps(data).replace("</", "<\\/")
    logic_json_str = json.dumps(logic_settings).replace("</", "<\\/")
    words_per_day = settings.get("words_per_day", 5) if 'settings' in locals() else 5
    show_words_per_day = settings.get("show_words_per_day", True) if 'settings' in locals() else True
    # Per-sentence source badge: the interned table + the display mode chosen in Advanced Settings.
    sources_json_str = json.dumps(source_table, ensure_ascii=False).replace("</", "<\\/")
    # Word lookup button (⌕). Validated here rather than trusted, exactly like source_display: a
    # hand-edited settings.json must not be able to put arbitrary text into the report's URL.
    _ws = settings if 'settings' in locals() else {}
    word_search_category = _ws.get("word_search_category", "all")
    if word_search_category not in ("all", "anime", "liveaction", "youtube"):
        word_search_category = "all"
    word_search_json_str = json.dumps({
        "enabled": bool(_ws.get("word_search_enabled", True)),
        "category": word_search_category,
    }, ensure_ascii=False).replace("</", "<\\/")
    source_display = settings.get("source_display", "off") if 'settings' in locals() else "off"
    if source_display not in ("off", "icon", "filename", "full"):
        source_display = "off"

    # Optional speech module: how the report reaches the local helper that speaks a sentence.
    # Only ever the loopback port and a token — never the API key, which stays in the user's data
    # folder so it can't be copied into every report ever generated. Absent module (or feature off)
    # leaves this null and the badge behaves exactly as it always has.
    koe_config = None
    try:
        import modules.koe as _koe        # not `from modules import koe` — see main.apply_koe_state
        koe_config = _koe.report_config()
    except Exception:
        koe_config = None
    koe_json_str = json.dumps(koe_config, ensure_ascii=False).replace("</", "<\\/")

    html_content = html_content.replace(
        "let globalData = null;",
        f"let globalData = {json_str};\n        let globalTheme = '{applied_theme}';\n        let globalLogic = {logic_json_str};\n        let globalLanguage = '{target_lang}';\n        let globalWordsPerDay = {words_per_day};\n        let globalShowWordsPerDay = {'true' if show_words_per_day else 'false'};\n        let globalSources = {sources_json_str};\n        let globalSourceDisplay = '{source_display}';\n        let globalWordSearch = {word_search_json_str};\n        let globalKoe = {koe_json_str};"
    )

    # Embed Icon as Favicon and Header Logo
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        try:
            with open(icon_path, "rb") as icon_file:
                encoded_string = base64.b64encode(icon_file.read()).decode()
                
                # Injects favicon
                favicon_tag = f'<link rel="icon" type="image/png" href="data:image/png;base64,{encoded_string}">'
                html_content = html_content.replace("<head>", f"<head>\n    {favicon_tag}")
                
                # Injects logo into header
                logo_html = f'<img src="data:image/png;base64,{encoded_string}" alt="Logo" class="header-logo" style="height: 32px; width: 32px; margin-right: 15px; border-radius: 4px;">'
                html_content = html_content.replace("<h1>Surasura List</h1>", 
                                                 f'<div style="display:flex; align-items:center;">{logo_html}<h1>Surasura List</h1></div>')
        except Exception as e:
            print(f"Warning: Could not embed icon in HTML: {e}")

    # 4. Write Output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Static HTML generated at: {OUTPUT_FILE}")
    if app_mode:
        open_as_app(OUTPUT_FILE)
    else:
        url = f"file://{os.path.abspath(OUTPUT_FILE)}"
        webbrowser.open(url)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="default", help="Theme name")
    parser.add_argument("--app-mode", action="store_true", help="Launch in professional app mode")
    parser.add_argument("--zen-limit", type=int, default=0, help="Limit words for Zen Mode")
    args = parser.parse_args()
    generate_static_html(theme=args.theme, app_mode=args.app_mode, zen_limit=args.zen_limit)

if __name__ == "__main__":
    main()
