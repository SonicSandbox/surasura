import os
import pathlib
import re
import sys
import json
import urllib.parse
import webbrowser

from app.path_utils import get_user_file, get_resource, SIDECAR_SUFFIX, read_text
from app import settings_manager

# Configuration
RESULTS_DIR = get_user_file("results")
PROGRESSIVE_CSV = os.path.join(RESULTS_DIR, "progressive_learning_list.csv")
PRIORITY_CSV = os.path.join(RESULTS_DIR, "priority_learning_list.csv")
REPORT_NAME = "reading_list_static.html"
OUTPUT_FILE = os.path.join(RESULTS_DIR, REPORT_NAME)

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


OPEN_ON_NAME = "journey_open.html"     # the small page that opens the report on one file (`open_report(file=)`)


def report_holds(file, item=None):
    """Whether the report on disk lists `file` (a name as the report names it, `path_utils.report_name`) — a counted,
    set-aside or Target-met file alike: each is an entry with that `"filename"` in its data, written as
    `generate_static_html` writes it (`json.dumps`). `item` (the file's library item id): a v3 page whose episodes
    carry ids holds it only by that id — two shows' 第01集 are two items, one name (E-NAMES). False with no report."""
    try:
        text = read_text(os.path.join(get_user_file("results"), REPORT_NAME))
    except OSError:
        return False
    head = _journey_head(text)
    if head is not None:                                   # a v3 page: its episodes' ids or names, as `#file=` reads them
        eps = [e for e in head.get("eps") or () if isinstance(e, list) and len(e) > 1]
        if item is not None and any(e[0] is not None for e in eps):
            return any(e[0] == item for e in eps)
        return any(e[1] == file for e in eps)
    return f'"filename": {json.dumps(file)}' in text      # (a name holds no "/", so no "</" for the dump to escape)


_HEAD_OPEN = '<script type="application/json" id="j-head">'


def _journey_head(text):
    """A v3 page's head (`journey_render.elements`' first element, JSON) out of the page's text; None for any other
    page (one written before the cut-over, the YouTube preview's) or a head that doesn't read."""
    at = text.find(_HEAD_OPEN)
    if at < 0:
        return None
    end = text.find("</script>", at)
    try:
        head = json.loads(text[at + len(_HEAD_OPEN):end])
    except ValueError:
        return None
    return head if isinstance(head, dict) else None


def open_report(app_mode=False, file=None, item=None):
    """Open the ALREADY-generated report without re-rendering it — the fast path when neither the
    analysis nor what the page draws (the render signature) changed. Returns False if there is
    no report on disk yet (caller should render instead). The file is looked for in `results` as it is now, where the
    window's journey check looks — never by the path fixed when this module was first imported (AD-4: a test's
    earlier root, whose report then opened a browser in the next test).

    `file` (a file's name as the report names it, its basename; Sonic 2026-10-24): open the report ON that file, its
    tab clicked (`#file=<name>`, read as the report loads; `item`, the file's library item id: `&id=<item>` after it,
    which the page opens by — two shows' 第01集 share a name, E-NAMES). Windows drops a file URL's fragment on its way
    to the default browser, so a small page beside the report carries it (`OPEN_ON_NAME`): it replaces itself with the report
    at that fragment. Written at each such open (~200 bytes; cheaper than checking whether it already holds the name),
    and left beside the report. A name the report doesn't hold opens where it opens by itself; a page that can't be
    written (results read-only, a lock) opens the report itself.

    With the journey's door open in this process (the window's, `app/door.py`), it opens through the door's one-time
    page instead, which hands the report the door's address and token (and `file=` after them)."""
    path = os.path.join(get_user_file("results"), REPORT_NAME)
    if not os.path.exists(path):
        return False
    from urllib.parse import quote
    fragment = f"file={quote(file, safe='')}" + (f"&id={int(item)}" if item is not None else "") if file else ""
    door = sys.modules.get("app.door")      # (not imported: no door is open here, and none is imported to find that)
    launched = door.launch_page(os.path.dirname(path), REPORT_NAME, fragment) if door is not None else None
    if launched:
        path = launched
    elif file:
        target = json.dumps(f"{REPORT_NAME}#{fragment}")     # (quoted: no < or / left in it)
        page = os.path.join(os.path.dirname(path), OPEN_ON_NAME)
        try:
            with open(page, "w", encoding="utf-8") as f:
                f.write(f'<!DOCTYPE html><meta charset="utf-8"><title>Surasura</title>'
                        f'<body style="background:#1e1e1e"><script>location.replace({target});</script>\n')
            path = page
        except OSError as e:
            print(f"Warning: the journey's page couldn't be written ({e!r}); opening the report itself")
    if app_mode:
        open_as_app(path)
    else:
        webbrowser.open(f"file://{os.path.abspath(path)}")
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
    # The memo's answers: [anchor, start, end] — a times-only answer made this render is held as (start, end) and
    # written as [None, start, end] (`save_memo`; 92,000 of them at 20,000 files: 3 MB less). A memo written before
    # the times came from Connect's line reader (E5.1) holds [anchor, whole seconds] found otherwise, and is
    # recomputed: its files' signatures differ. The signature also names the engine: the reader cleans lines as a
    # Generate does, and that changes only with it.
    LINES = "cues-1"

    def __init__(self, cache_path=None, script="asis", language=None):
        # The Chinese script the report's sentences were converted to (`zh_script`, already
        # effective). With one chosen, sentences are searched in a converted copy of each file and
        # the anchor handed back is the file's OWN wording at the same offsets (conversion is
        # length-preserving), because the browser searches the real file.
        self._script = script if script in ("s", "t") else "asis"
        # The library's language: a file is read in its own encoding, as the analyzer read it
        # (path_utils.read_text) — a CP932 or UTF-16 subtitle's sentences find their cue too.
        self._language = language
        self._converted = {}
        self._cache = {}
        self._timelines = {}
        self._sidecars = {}
        # Where each anchor was found, so _original() hands back the file's own wording at that place.
        self._pos = {}
        # Optional on-disk memo so a RE-render (theme change, Words Per Day) doesn't redo the work.
        self._cache_path = cache_path
        self._memo = self._load_memo()
        self._memo_dirty = False
        self._sigs = {}        # path -> (mtime, size[, script], lines), so the freshness check is one stat per file
        self._version = None   # `_lines()`, made once a finder
        self._dirs = {}        # folder -> its listing's entries ({name: DirEntry}): `_dir_stat`
        self._entries = {}     # path -> its validated memo entry, so that check happens once too

    def _raw(self, path):
        if path not in self._cache:
            try:
                self._cache[path] = read_text(path, self._language)
            except OSError:
                self._cache[path] = ""
        return self._cache[path]

    def _hay(self, path):
        """What a sentence is searched in: the file's own text, or a converted copy when a Chinese
        script is chosen (cached — converting is the costly part)."""
        if self._script == "asis":
            return self._raw(path)
        if path not in self._converted:
            from app import zh_script
            self._converted[path] = zh_script.convert(self._raw(path), self._script)
        return self._converted[path]

    def _original(self, path, needle, pos=None):
        """The file's own wording for `needle`, found at `pos` in the searched text (default: where
        _unique recorded it). As-is that IS `needle`. Remembers the position under the original
        wording too."""
        if self._script == "asis":
            return needle
        if pos is None:
            pos = self._pos.get((path, needle), -1)
        if pos < 0:
            return ""
        wording = self._raw(path)[pos:pos + len(needle)]
        self._pos[(path, wording)] = pos
        return wording

    def _unique(self, raw, needle, path=None):
        """Present exactly once — anything else could scroll to the wrong line. Remembers where."""
        first = raw.find(needle)
        if first == -1 or raw.find(needle, first + 1) != -1:
            return False
        if path is not None:
            self._pos[(path, needle)] = first
        return True

    # What the loose search lets sit between two of a sentence's characters, one piece at a time: whitespace alone,
    # then whitespace or one of the reader's removals. Built once — a pattern with a gap between every character of
    # the sentence took about 10 ms to build, for each sentence (10 s of a report's first render).
    _GAPS = None

    @staticmethod
    def _loose(raw, needle):
        """The file's own wording for `needle`, allowing whitespace the tokenizer dropped — and what the
        reader removed from inside a line (a footnote mark ①, a ruby reading 《かんじ》, a caption's
        [音楽]: analyzer.REMOVED_INLINE; a transcript's group in parentheses, （笑）:
        analyzer._TRANSCRIPT_GROUP_RE), which the sentence no longer holds. Empty if absent or
        ambiguous."""
        if AnchorFinder._GAPS is None:
            from app.analyzer import REMOVED_INLINE, _TRANSCRIPT_GROUP_RE
            AnchorFinder._GAPS = (re.compile(r"\s"),
                                  re.compile(rf"\s|{REMOVED_INLINE}|{_TRANSCRIPT_GROUP_RE.pattern}"))
        # Whitespace alone first; the removals too only when that doesn't place the sentence exactly once.
        for gap in AnchorFinder._GAPS:
            found = AnchorFinder._only_match(raw, needle, gap)
            if found:
                return found
        return ""

    @staticmethod
    def _only_match(raw, needle, gap):
        """The text in `raw` spelling `needle` with any run of `gap` pieces between two of its characters, if there
        is exactly one such place; "" if none or more than one.

        The same answer as searching with the pattern needle[0] (gap)* needle[1] (gap)* ... needle[-1] and Python's
        re.finditer, found the way that search finds it: starts are tried left to right; from a start, each gap takes
        as many pieces as it can and gives them back one at a time until the rest of the sentence fits, the earlier
        gap first; the next start is looked for where a match ended. It gives the same text because a gap piece
        fits in one way at a place — every mark ends at its first closing mark, and the two that can both fit at one
        place (an editor's note ［＃…］ and a full-width sound cue ［…］) end at the same one — so a gap is a single
        chain of pieces, and the pattern's own backtracking tries exactly these ends, in this order."""
        if not needle:
            return ""
        dead = set()        # (index in the needle, position) already known not to lead to a match
        found = None
        start = raw.find(needle[0])
        while start != -1:
            # Most starts fail at once — the next character is neither the sentence's next one nor a gap piece.
            if len(needle) > 1 and not raw.startswith(needle[1], start + 1) and not gap.match(raw, start + 1):
                end = -1
            else:
                end = AnchorFinder._match_end(raw, needle, gap, 1, start + 1, dead)
            if end == -1:
                start = raw.find(needle[0], start + 1)
                continue
            if found is not None:
                return ""       # more than one place it could be
            found = raw[start:end]
            start = raw.find(needle[0], end)
        return found or ""

    @staticmethod
    def _match_end(raw, needle, gap, i, pos, dead):
        """Where a match of needle[i:] ends when the gap before it starts at `pos` — the gap's longest end tried first
        — or -1. A static method rather than a closure calling itself: that would be a reference cycle on every
        search, left until the run ends, since a Generate runs with the cycle collector paused (app/batch_gc.py)."""
        if i == len(needle):
            return pos
        if (i, pos) in dead:
            return -1
        ends = [pos]
        piece = gap.match(raw, pos)
        while piece and piece.end() > ends[-1]:
            ends.append(piece.end())
            piece = gap.match(raw, piece.end())
        for end in reversed(ends):
            if raw.startswith(needle[i], end):
                found = AnchorFinder._match_end(raw, needle, gap, i + 1, end + 1, dead)
                if found != -1:
                    return found
        dead.add((i, pos))
        return -1

    # -- on-disk memo ------------------------------------------------------------------------- #
    # A re-render (a setting the page draws, a template) reruns this whole pass over unchanged files for
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
            if self._version is None:
                self._version = self._lines()
            try:
                st = self._dir_stat(path)
                # Answers found through a conversion are re-verified after a script switch. A tuple: the memo's JSON
                # writes it as the list it is read back as (`_entry` compares the two).
                self._sigs[path] = (st.st_mtime, st.st_size) + \
                    ((self._script,) if self._script != "asis" else ()) + (self._version,)
            except OSError:
                self._sigs[path] = None
        return self._sigs[path]

    def _dir_stat(self, path):
        """`os.stat(path)` as its folder's one listing gives it (Kiku-L): on Windows a listing carries each file's times
        and size, so a render's freshness checks cost one call a folder, not one a file (20k subtitles in 1.7k folders:
        2.6 s of stats). A file the listing doesn't name (another spelling, a race) is stat'ed itself; raises OSError
        as `os.stat` does."""
        folder, name = os.path.split(path)
        entries = self._dirs.get(folder)
        if entries is None:
            try:
                with os.scandir(folder or ".") as it:
                    entries = {e.name: e for e in it}
            except OSError:
                entries = {}
            self._dirs[folder] = entries
        entry = entries.get(name)
        return entry.stat() if entry is not None else os.stat(path)

    def _lines(self):
        """The memo signature's last part: the line reader's version and the engine's (`LINES`)."""
        from app.analyzer import ENGINE_REVISION
        return f"{self.LINES}/{ENGINE_REVISION}"

    def resolve(self, abs_path, sentence):
        """(anchor, start, end) for a sentence, memoised across renders: the scroll-to-text anchor, and the
        seconds (millisecond precision) its lines start and end at — None for a file with no timed lines.

        A file's entries are dropped whenever its (mtime, size) changes, so an edited source can
        never serve a stale anchor."""
        entry = self._entry(abs_path)
        hit = entry["a"].get(sentence)
        if isinstance(hit, list) and len(hit) == 3 and hit[0] is not None:   # (a gone file's entry: its sig is None)
            return hit[0], hit[1], hit[2]

        anchor = self.anchor(abs_path, sentence)
        # A times-only answer (`times`: (start, end), or [None, start, end] as written) keeps its times; its anchor is
        # looked for now.
        found = self.answer(hit)
        start, end = found if found is not None else self.line(abs_path, sentence)
        entry["a"][sentence] = [anchor, start, end]
        self._memo_dirty = True
        return anchor, start, end

    def times(self, abs_path, sentence):
        """(start, end) alone, for the journey's ▶ with the sources hidden (Kiku-L): the memo's answer when it has one,
        else the line reader's — kept as [None, start, end], its anchor never looked for (that reads the whole file:
        only `resolve`, for the badge, does)."""
        entry = self._entry(abs_path)
        found = self.answer(entry["a"].get(sentence))
        if found is not None:
            return found
        found = self.line(abs_path, sentence)
        entry["a"][sentence] = found
        self._memo_dirty = True
        return found

    @staticmethod
    def answer(hit):
        """A memo answer's (start, end): held as (start, end) when made this render, [anchor, start, end] as written;
        None for anything else (a damaged or older memo's: asked again)."""
        if type(hit) is tuple:
            return hit
        if isinstance(hit, list) and len(hit) == 3:
            return hit[1], hit[2]
        return None

    def answers(self, abs_path):
        """A file's memo answers, {sentence: answer} (`answer` reads one), checked against the file once a render: the
        journey's `Sources.prepare` reads a whole page's lines through it."""
        return self._entry(abs_path)["a"]

    def forget(self, abs_path):
        """Let go of a file's lines (`line` reads them again if asked): the journey asks a file at a time."""
        self._timelines.pop(abs_path, None)

    def forget_listings(self):
        """Let go of the folder listings the freshness check read (31 MB of entries at 20,000 files): once every file
        is checked, a later one lists its folder again."""
        self._dirs.clear()

    def _entry(self, abs_path):
        """The memo's entry for a file, checked against its signature once a render."""
        entry = self._entries.get(abs_path)
        if entry is None:
            entry = self._memo.get(abs_path)
            sig = self._file_sig(abs_path)
            old = entry.get("sig") if isinstance(entry, dict) else None
            if not isinstance(entry, dict) or not isinstance(entry.get("a"), dict) or \
                    (tuple(old) if isinstance(old, list) else old) != sig:
                entry = {"sig": sig, "a": {}}
                self._memo[abs_path] = entry
                self._memo_dirty = True
            self._entries[abs_path] = entry
        return entry

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
                # A file's entry at a time (the whole memo as one string was +10 to +30 MB at 20,000 files); a
                # times-only answer held as (start, end) is written [None, start, end], as it is read back
                held, size, sep = ["{"], 0, ""
                for path, entry in live.items():
                    answers = entry["a"]
                    if any(type(hit) is tuple for hit in answers.values()):
                        entry = {"sig": entry["sig"], "a": {sentence: [None, hit[0], hit[1]] if type(hit) is tuple
                                                            else hit for sentence, hit in answers.items()}}
                    piece = f"{sep}{json.dumps(path, ensure_ascii=False)}:{json.dumps(entry, ensure_ascii=False)}"
                    held.append(piece)
                    size += len(piece)
                    sep = ","
                    if size >= 1 << 20:
                        f.write("".join(held))
                        held, size = [], 0
                held.append("}")
                f.write("".join(held))
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

    def line(self, abs_path, sentence):
        """(start, end) in seconds, millisecond precision, of the lines `sentence` is said in, or (None, None).

        The times are Connect's line reader's (`cues.timeline`, E5.1): the cues a card is cut from, read once per
        file, so the journey, a card and a clip name one line. A sentence said across several lines runs from the
        first one's start to the last one's end; one said more than once is its first time."""
        timeline = self._timelines.get(abs_path)
        if timeline is None:
            from app import cues
            try:
                timeline = cues.timeline(abs_path, self._language or "ja", self._script)
            except OSError:             # gone since the run: no times, as it has no anchor
                timeline = cues.Timeline()
            except Exception as e:      # an unreadable file: no times, never a failed report
                print(f"Warning: could not read the lines of {abs_path}: {e}")
                timeline = cues.Timeline()
            self._timelines[abs_path] = timeline
        found = timeline.line(sentence)
        if found is None:
            return None, None
        from app.cues import seconds
        return seconds(found[0]), seconds(found[1])

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

        # Searched in the converted copy when a Chinese script is chosen; `raw` itself otherwise.
        hay = self._hay(abs_path)

        # 1. Verbatim. Prose is stored exactly as written, so books and transcripts stop here.
        for chunk in chunks:
            if self._unique(hay, chunk, abs_path):
                return self._original(abs_path, chunk)

        # 2. Whitespace-tolerant. Anime subtitles space their phrases ('そうだ 女｡ お前に話がある｡')
        #    and the tokenizer removed those spaces, so match with optional gaps.
        for chunk in chunks:
            verbatim = self._loose(hay, chunk[:self.MAX_ANCHOR])
            if not verbatim:
                continue
            # Prefer a gap-free run of what we matched: a fragment with no whitespace in it is the
            # most reliable thing to hand a browser.
            for run in sorted(verbatim.split(), key=len, reverse=True):
                if len(run) >= self.MIN_LEN and self._unique(hay, run, abs_path):
                    return self._original(abs_path, run)
            return " ".join(self._original(abs_path, verbatim, hay.find(verbatim)).split())
        return ""


# Tier folders are plumbing, not something the learner thinks in — they think in books and series. So is the
# content folder every new copy goes into whatever its place (`Library/<show>/…`, 3.0's Sources), and the downloader's
# own (`YouTube/<channel>/…`, 3.0.12).
_TIER_BUCKETS = ("HighPriority", "LowPriority", "GoalContent", "Graduated", "Processed", "Library", "YouTube")


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


def _video_link(rel_path, stype, meta=None):
    """What a source's ▶ badge opens (the source table's 5th column), or "" for nothing.

    A YouTube source gives its video id; the template builds the youtu.be link and the timestamp. A
    bilibili.tv source gives the episode page URL recorded in its cue sidecar. There is no verified
    start-time parameter for that site, so the badge opens the episode and its hover names the
    moment."""
    if stype == "youtube":
        return _video_id(rel_path, meta)
    if stype == "bilibili":
        url = str((meta or {}).get("url") or "").split("#", 1)[0]
        return url if url.startswith(("https://", "http://")) else ""
    return ""


def _group_label(rel_path):
    """Badge hover text: the file plus the group (folder) it belongs to, e.g.
    'test_book/chapter_1.txt'. A loose file in a tier just shows its own name."""
    parts = [p for p in str(rel_path).replace("\\", "/").split("/") if p]
    if parts and parts[0] in _TIER_BUCKETS:
        parts = parts[1:]
    return "/".join(parts) if parts else str(rel_path)


_YOUTUBE_ID = re.compile(r"\[[0-9A-Za-z_-]{11}\]\s*$")    # a downloaded video's `[id]` (or a release's 11-character
                                                            # tag): only a strong episode mark counts then


def shown_name(filename):
    """Fresh-U 13 (Sonic 2026-11-13; PROVISIONAL): what the journey shows for a file — its show and its episode as the
    window's rows say them (`Hoshikuzu Station S01E01.ja.srt` → *Hoshikuzu Station · Ep 1*; a text's part *· Part 1*; a
    book's part named by its chapter, that chapter), read from the name alone (LM1a's `episode_names.identity`, the
    rows' `view_rows.chapter_part`); a special, a name with no number, or one ending in an 11-character tag (a YouTube
    `[id]` — `Top 10 …` is no episode 10, as on the window's rows — unless a strong mark names one: `- 05`, `S01E05`,
    `第05話`), its stem without its marks; nothing to read,
    the name as it is. Never raises. Shown only: the file name stays the report's key."""
    name = filename or ""
    try:
        from app.episode_names import identity
        from app.services import view_rows
        chapter = view_rows.chapter_part(name)
        n = identity(name, bare_numbers=True)
        show = (n.show or "").strip()
        if chapter is not None:
            return f"{show} · {chapter[1]}" if show else chapter[1]
        if n.special or n.episode is None or (_YOUTUBE_ID.search(n.stem) and identity(name).episode is None):
            return view_rows.stem(n.stem).strip() or name
        number = int(n.episode) if float(n.episode).is_integer() else n.episode
        label = view_rows.STRINGS["part" if name.lower().endswith(".txt") else "ep"].format(n=number)
        return f"{show} · {label}" if show else label
    except Exception:
        return name


# The journey's ▶ (Kiku-L): the files a browser's <audio> plays from the report's file:// page — `play.PLAYABLE`, the
# one list (`play.files`' gate reads it too). Those it doesn't hold get no ▶, and the badge's hover says why.
from app.services.play import PLAYABLE  # noqa: E402


LINE_MEDIA_MEMO = "line_media.json"     # results/: `play.files`' answers kept between renders (the anchor memo's twin)
LINE_TIMES_MEMO = "line_times.json"     # results/: a playable line's times with the badge off (`AnchorFinder.times`)
TIMED_TYPES = ("subtitle", "audio")     # a source with timed lines: a subtitle; an audiobook's transcript (its item's)


def _line_media(language, rel_paths, memo_path=None, explain=False, cut_kinds=()):
    """({rel path: [where, why not]}, [folder URI, ...]) for the journey's ▶ (Kiku-L): the file `play.files` finds for
    each — when a browser plays it (`PLAYABLE`), `where` is "<its folder's place in the list>/<its name as it is>" (the
    page puts the URI together: a folder's URI once, a name never percent-encoded in the page — 20k sources were 2 MB
    more), else ["", its extension] (".mkv": the badge's hover says why; "vbr": an mp3 whose bit rate varies); nothing
    found, no row. `memo_path`: its answers kept between renders (only this render's sources: one that left the lists
    leaves the file). `explain`: the badge is shown, so a line with no ▶ says why (`play.files`' hint). `cut_kinds`:
    the journey's render (J-CLIP) — a file of these kinds (the one cutter's videos) is looked for and gets its `where` too,
    though no browser plays it: the page cuts its lines (`clip/cut`); this page asks none. Never raises: a lookup that
    fails is no ▶, never a failed report; a memo that can't be read or written only costs time."""
    if not rel_paths:
        return {}, []
    memo = {}
    if memo_path:
        try:
            with open(memo_path, encoding="utf-8") as f:
                loaded = json.load(f)
            memo = loaded if isinstance(loaded, dict) else {}
        except Exception:
            memo = {}
    before = dict(memo)                         # (`play.files` replaces an entry, never changes one in place)
    try:
        from app.services import play
        found = play.files(language, sorted(rel_paths), memo=memo, explain=explain, cut_kinds=cut_kinds)
    except Exception as e:
        print(f"Warning: could not look for the lines' audio: {e}")
        return {}, []
    from app import audiobooks
    folders, dirs, out = {}, [], {}
    for rel, path in found.items():
        if not isinstance(path, str) or not os.path.isabs(path):
            continue                             # nothing found (or never a relative path: no URI, no ▶)
        ext = os.path.splitext(path)[1].lower()
        if ext not in PLAYABLE and ext not in cut_kinds:
            out[rel] = ["", ext]
            continue
        if ext == ".mp3":
            # A browser seeks in a VBR mp3 only roughly (±1–2 s): never the wrong words. The verdict is kept with the
            # answer (a 4th field), read again only when the answer is looked for again; one that couldn't be read
            # (None: a share's hiccup) plays and is never kept.
            kept = memo.get(rel)
            if isinstance(kept, list) and len(kept) == 4 and kept[0] == path and isinstance(kept[3], bool):
                variable = kept[3]
            else:
                variable = audiobooks.mp3_variable(path)
                if variable is not None and isinstance(kept, list) and len(kept) == 3 and kept[0] == path:
                    memo[rel] = kept + [variable]
            if variable:
                out[rel] = ["", "vbr"]
                continue
        cut = max(path.rfind("\\"), path.rfind("/"))
        folder, name = (path[:cut], path[cut + 1:]) if cut > 2 else os.path.split(path)
        try:
            if folder not in folders:            # each folder's URI once (20k files, 1.7k folders)
                dirs.append(pathlib.Path(folder).as_uri().rstrip("/"))
                folders[folder] = len(dirs) - 1
            out[rel] = [f"{folders[folder]}/{name}", ""]
        except ValueError:                       # a path no URI can name: no ▶, never a failed report
            continue
    if memo_path:
        memo = {rel: memo[rel] for rel in rel_paths if rel in memo}
        if memo != before:
            try:
                tmp = memo_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(json.dumps(memo, ensure_ascii=False))
                os.replace(tmp, memo_path)
            except Exception as e:
                print(f"Warning: could not save the lines' audio memo: {e}")
    return out, dirs


def anki_backlog_keys(language, settings, list_path=None):
    """The words of the new cards already waiting in Anki, for the report's label — "Label backlogged
    Anki words" (`anki_backlog_on_generate`; Junban_Backlog_Spec WP-B8). Keys only, never card
    content: each card's word and its hiragana fold, as the Anki sync wrote them
    (`User Files/<lang>/anki_backlog.json`), and for Japanese the word the dictionary reads each card
    as (`_dictionary_keys`). Chinese keys are read in the script the report is in, as the list is, and a Chinese
    card whose word is no key of the list as written is labelled where Junban places it (`_chinese_keys`: 认真地 on
    认真).
    `[]` when switched off, with no backlog file, or on any error — the report then has no label, no
    filter entry and no count: a user without Anki sees nothing different.

    `list_path` is the list the report shows. A Japanese card whose own spelling is a word on it
    (`anki_match.lookup`, L1–L4) is placed there by Junban, and so is labelled there only: the
    dictionary's reading and the user's "yes" are for the cards the list does not hold as written —
    a 解す card is 解す's row, not also 解する's; 生き the noun's, not also 生きる's — and a kana
    spelling's fold for the cards the list does not hold as spelled (`_own_keys`: スレ, not also
    擦れる's すれ) — Junban's ladder, `anki_match.card_key`. A hiragana card whose letters reach a name's
    or a loanword's row it is not (ひかり 'light' and the name ヒカリ, だいぶ and ダイブ 'dive': `_name_cards`)
    is labelled on its own word's row, or on none; nor is a card the dictionary keeps apart from the row its
    spelling reaches or the word it is read as (`anki_match.another_word`, `word_of_its_own`: 生き is not 生きる's
    row, 心する not 心's). Without a list, every card's keys are given."""
    if not (settings or {}).get("anki_backlog_on_generate", True):
        return []
    try:
        from app import anki_sync
        keys = anki_sync.backlog_keys(language)
        if keys and language == "zh":
            from app.zh_script import convert, effective
            script = effective(language, (settings or {}).get("zh_script"))
            if script != "asis":
                keys = {convert(key, script) for key in keys}
            if list_path:
                keys |= _chinese_keys(keys, script, list_path, _pair_answers(language))
        if keys and language == "ja":
            from app import anki_match
            backlog = anki_sync.load_backlog(language)
            answers = _pair_answers(language)
            index = anki_match.build_index(list_path, language="ja") if list_path else None
            listed = index.rank_of if index else {}
            made = _connect_rows(language, backlog, index, answers)
            if made:        # alpha 4 M3: labelled on the row Connect made it for, only there (as Junban places it)
                backlog = dict(backlog, notes={n: e for n, e in (backlog.get("notes") or {}).items()
                                               if n not in made})
            names = _name_cards(backlog, index, answers) if listed else {}
            keys = _own_keys(backlog, listed, names, index) if listed else keys
            phrases = bool(((settings or {}).get("logic") or {}).get("phrase_rows", True))
            keys |= _dictionary_keys(backlog, answers, listed, names, index, phrases)
            keys |= _confirmed_keys(backlog, answers, listed, names)
            keys |= set(made.values())
        return sorted(keys)
    except Exception as e:
        print(f"Warning: could not read the Anki backlog for the report: {e}")
        return []


# How a card's ending is written — する, な, に, と (`anki_match.CARD_ENDINGS`): a kana-only card word is
# read alone only when it ends in one of these, or starts or ends in the word's own grammar or an inflected
# する / copula (`anki_match.AFFIX_SPELLINGS`: おへや, おれたち, べんきょうした), so a bare kana word never is.
_ENDING_SPELLINGS = ("する", "な", "に", "と")


def _connect_rows(language, backlog, index, answers=None):
    """{backlog note id (as the file keys it): the listed word Connect made its card for} — alpha 4 M3, as Junban
    places it (`anki_match.connect_row` after `card_key`, with Connect's record `connect.library.made_notes_of`):
    ヒトリ's card, mined as ひとり, is labelled on ヒトリ; never over the card's exact row, a "yes" or a "no". The
    tokenizer is built only for a card the record names. {} without a list or Connect's record."""
    if index is None or not index.rank_of:
        return {}
    from app import anki_match
    from app.connect import library
    made = library.made_notes_of(language)
    if not made:
        return {}
    tokenizers = []

    def tokenize(text):
        if not tokenizers:
            from app import analyzer
            analyzer.SANITIZE_JA = True         # as every Japanese run sets it (see _dictionary_keys)
            tokenizers.append(analyzer.JapaneseTokenizer().tokenize)
        return tokenizers[0](text)
    out = {}
    for note, entry in (backlog.get("notes") or {}).items():
        try:
            row = made.get(int(note))
        except (TypeError, ValueError):
            continue
        word = entry.get("word") if isinstance(entry, dict) else None
        if row is None or not isinstance(word, str):
            continue
        key, via = anki_match.card_key(word, index.rank_of, "ja", answers, tokenize, index.words, index.orths)
        key, via = anki_match.connect_row(row, key, via, word, index.rank_of, answers, index.words)
        if via == "connect":
            out[note] = key
    return out


def _name_cards(backlog, index, answers=None):
    """`{card word: the key it is labelled by, or ""}` for the waiting cards written in hiragana alone whose letters
    reach a name's or a loanword's row they are not — ひかり ('light', 光) and the list's ヒカリ, a name read from
    ひかりさん; だいぶ and ダイブ 'dive' — where Junban places them (`anki_match.card_key`, `not_the_name`): the
    user's "yes", else the row of the word they are, else none. The tokenizer is built only when a card's letters
    reach a row whose own word is those letters in katakana; one that can't be had leaves every card as before."""
    from app import anki_match
    notes = backlog.get("notes")
    words = {entry["word"] for entry in (notes.values() if isinstance(notes, dict) else ())
             if isinstance(entry, dict) and isinstance(entry.get("word"), str)}
    made = []

    def tokenize(text):
        if not made:
            from app import analyzer
            analyzer.SANITIZE_JA = True         # as every Japanese run sets it (see _dictionary_keys)
            made.append(analyzer.JapaneseTokenizer().tokenize)
        return made[0](text)
    found = {}
    try:
        for word in words:
            key = anki_match.lookup(word, index.rank_of, "ja")
            if key and anki_match.not_the_name(word, key, index.rank_of, index.words, tokenize) is not None:
                found[word] = anki_match.card_key(word, index.rank_of, "ja", answers, tokenize, index.words,
                                                  index.orths)[0]
    except Exception as e:
        print(f"Warning: could not read the Anki backlog's kana cards: {e}")
        return {}
    return found


def _own_keys(backlog, listed, names=None, index=None):
    """Each card's own keys as the Anki sync wrote them — its word, and the word's hiragana fold — but the
    word alone when the list (`listed`) holds it as written: Junban tries the fold (L4) only when the
    spelling misses, so a スレ card is スレ's row, never also the row that holds すれ (擦れる's Forms). A card
    in `names` (`_name_cards`) holds only the key of the word it is, if any: its letters are a name's it is not.
    A card whose spelling reaches its row only as another dictionary word's (`anki_match.another_word`, with the
    list's `index`: 生き in 生きる's Forms) holds none: Junban places it by its own sentence."""
    from app import anki_match
    keys = set()
    names = names or {}
    words, orths = (index.words, index.orths) if index else (None, None)
    notes = backlog.get("notes")
    for entry in (notes.values() if isinstance(notes, dict) else ()):
        if not isinstance(entry, dict):
            continue
        if entry.get("word") in names:
            keys.update(key for key in (names[entry["word"]],) if key)
            continue
        word = entry.get("word")
        key = anki_match.lookup(word, listed, "ja") if isinstance(word, str) else ""
        if key and anki_match.another_word(word, key, listed, words, orths):
            continue
        if isinstance(entry.get("word"), str) and entry["word"] in listed:
            keys.add(entry["word"])
        else:
            keys.update(str(key) for key in entry.get("keys") or [] if key)
    return keys


def _on_the_list(word, answers, listed, names=None, index=None):
    """Whether Junban places this card with no reading of its own: its spelling is on the list (L1–L4) — for a
    hiragana card whose letters are a name's it is not (`names`, `_name_cards`): the word it is; never a spelling of
    another dictionary word's (`anki_match.another_word`) — or the user said "yes" to a word that is
    (`anki_match.card_key`'s first rungs)."""
    from app import anki_match
    if not listed:
        return False
    answer = (answers or {}).get(word) or {}
    if names and word in names:
        spelled = bool(names[word])
    else:
        key = anki_match.lookup(word, listed, "ja")
        words, orths = (index.words, index.orths) if index else (None, None)
        spelled = bool(key) and not anki_match.another_word(word, key, listed, words, orths)
    return spelled or (answer.get("answer") == "yes" and answer.get("target") in listed)


def _dictionary_keys(backlog, answers=None, listed=None, names=None, index=None, phrases=False):
    """The list words a Japanese backlog's cards ARE, read through the dictionary
    (Patterns_Quality_Spec §7). Each card word holding a kanji is tokenized alone, as the list's
    content was, and when it is one word its lemma — the list row's `Word` — is a key too: 逃げだす
    labels 逃げ出す and 引き伸ばす 引き延ばす, spellings the card's own keys never meet. An ending written
    onto the word is dropped first (`anki_match.one_word`: 同行する labels 同行); anything longer is a
    phrase or a compound, not one row — unless `phrases` (Settings' "Idioms and set phrases on your list")
    lists set phrases as rows: then its words' lemmas joined are a key, the row's `Word` (興味をもつ labels
    興味を持つ), as Junban places it (`anki_match.card_key`).

    A kana-only word alone is read wrong too often (まく -> 膜, Junban_Backlog_Spec §8 gotcha 2), so it is
    read only when an ending or the word's own grammar comes off it — バシッと, ひょいと (Anki_Match_Consistency_Scope.md
    item 1), おれたち, べんきょうした —
    and then keyed by the letters it is written in, as Junban looks it up (`anki_match.card_key`). The
    user's "no" to a card's word being that list word (`answers`) keeps it from being labelled, as it
    keeps Junban from placing it there. A card the list (`listed`, its `rank_of`) holds as written, or
    by a "yes", is not read at all (`_on_the_list`): alone, 解す reads 解する and 生き 生きる. Nor is a card the
    dictionary keeps apart from the word it is read as, or from the row that word's spelling reaches
    (`anki_match.word_of_its_own`, `another_word` with the list's `index`): 心する is no 心, 揚げる no 上げる.

    The tokenizer is built only when a card needs it, here where the report renders — never in the
    dashboard (Anki_Known_Sync_Spec I6). One that cannot be had leaves the cards' own keys, as
    before."""
    from app import anki_match
    notes = backlog.get("notes")
    words = {entry["word"] for entry in (notes.values() if isinstance(notes, dict) else ())
             if isinstance(entry, dict) and isinstance(entry.get("word"), str)
             and (anki_match._KANJI_RE.search(entry["word"]) or entry["word"].endswith(_ENDING_SPELLINGS)
                  or entry["word"].startswith(anki_match.AFFIX_SPELLINGS[0])
                  or entry["word"].endswith(anki_match.AFFIX_SPELLINGS[1]))
             and not _on_the_list(entry["word"], answers, listed, names, index)}
    if not words:
        return set()
    rows, orths = (index.words, index.orths) if index else (None, None)
    keys = set()
    try:
        from app import analyzer
        # As every Japanese run sets it. The report can render in a process of its own, where it is
        # still off, and a glossed lemma (同行-連れ立つ, 私-代名詞) is no row's Word.
        analyzer.SANITIZE_JA = True
        tokenize = analyzer.JapaneseTokenizer().tokenize
        phrase_set = None
        if phrases:
            from app import phrases as phrase_rules     # a set phrase's row is its words' lemmas joined
            phrase_set = phrase_rules.load()
        for word in words:
            tokens = anki_match.ending_apart(tokenize(word))    # バシッと: the sound word + と, as Junban reads it
            token = anki_match.one_word(tokens)
            if token is None or anki_match.word_of_its_own(word, tokens, token):
                if token is None and phrase_set is not None and len(tokens) >= 2 and anki_match._KANJI_RE.search(word):
                    run = "".join(t[0] for t in tokens)
                    answer = (answers or {}).get(word) or {}
                    if phrase_set.of_word(run) is not None and not (answer.get("answer") == "no"
                                                                    and answer.get("target") == run):
                        keys.add(run)
                continue                # none, or a word of its own the dictionary keeps apart: 心する is no 心
            if len(tokens) == 1 and not anki_match.whole_word_alone(word, tokens):
                continue                # 見 alone is 見る's stem, 1人 is not 人 — Junban places neither
            if anki_match._KANJI_RE.search(word):
                found = {token[0]} if token[0] else set()
            elif len(tokens) >= 2 and token[2]:     # read from two tokens or more: ごあんないする, べんきょうした
                found = ({token[2]} if token[2] in (listed or {})
                         else {token[2], anki_match.fold_kana(token[2])})
            else:
                continue
            answer = (answers or {}).get(word) or {}
            if answer.get("answer") == "no" and answer.get("target") in found | {token[0], token[3]}:
                continue
            if listed and not anki_match._grammar_off(tokens):
                found = {key for key in found if not anki_match.another_word(word, key, listed, rows, orths)}
            keys |= found
    except Exception as e:
        print(f"Warning: could not read the Anki backlog through the dictionary: {e}")
        return set()
    return keys


def _chinese_keys(words, script, list_path, answers=None):
    """The list words Chinese backlog cards ARE when their word is no list key as written: the card read alone as ONE
    word, a 的 or 地 written on it taken off (认真地 is 认真), a 了 / 过 / 着 after a verb (吃了 is 吃) or a doubled form
    at its word — where Junban places it
    (`anki_match.card_key`, L7), the user's "no" kept. The tokenizer, in the report's script, is built only when a
    card needs it; one that can't be had leaves the cards' own keys, as before."""
    from app import anki_match
    listed = anki_match.build_index(list_path, language="zh").rank_of
    wanted = [word for word in words if word not in listed]
    if not listed or not wanted:
        return set()
    try:
        from app import analyzer
        tokenize = analyzer.ChineseTokenizer(script=script).tokenize
        return {key for key in (anki_match.card_key(word, listed, "zh", answers, tokenize, verb=analyzer.chinese_verb)[0]
                                for word in wanted) if key}
    except Exception as e:
        print(f"Warning: could not read the Chinese backlog's cards: {e}")
        return set()


def _pair_answers(language):
    """`{card word: {"target", "answer", …}}` — the user's answers to Junban's "Same word as one on your
    list?" (`User Files/<lang>/junban_pairs.json`). Read as plain JSON, so the label needs no Junban
    module; a file that won't read is no answers."""
    try:
        from app.path_utils import get_user_files_path
        with open(os.path.join(get_user_files_path(language), "junban_pairs.json"), encoding="utf-8") as f:
            pairs = json.load(f).get("pairs")
    except (OSError, ValueError, AttributeError):
        return {}
    return {word: pair for word, pair in pairs.items() if isinstance(pair, dict)} if isinstance(pairs, dict) else {}


def _confirmed_keys(backlog, answers, listed=None, names=None):
    """The list words the user said a waiting card IS — their "yes" (`_pair_answers`): あおぐ is 仰ぐ.
    Junban places the card there, so the label marks it there — unless the card's own spelling is on
    the list (`listed`; a name's row it is not aside, `names`): Junban's exact keys come before any answer."""
    from app import anki_match
    notes = backlog.get("notes")
    words = {entry.get("word") for entry in (notes.values() if isinstance(notes, dict) else ())
             if isinstance(entry, dict) and not (listed and entry.get("word") not in (names or {})
                                                 and anki_match.lookup(entry.get("word"), listed, "ja"))}
    return {str(pair["target"]) for word, pair in (answers or {}).items()
            if word in words and pair.get("answer") == "yes" and pair.get("target")}


# --- The journey: v3's page (J-CUT; SPEC §7, §8), for every look (J-RETIRE) ----------------------------------------- #
# The journey is v3's page: J-DATA's data (`app/journey_render.py`) in J-PAGE's page (`templates/journey/`), written to
# the same file (`REPORT_NAME`), so *Journey ↗*, a page open in a browser and its storage keep their name. The old page
# and Zen are retired whole (J-RETIRE, Sonic 2026-11-23): no look and no switch writes another page. The old page's
# template (`web_app.html`) stays for the YouTube preview alone, which loads it and this module's helpers above
# (`compress_list_of_dicts`, `AnchorFinder`, `_load_source_map`, `_group_label`, `_video_link`, `open_as_app`) itself
# (Charter S10; the dup audit's row 13).
JOURNEY_DIR = os.path.join("templates", "journey")
JOURNEY_RAIL = "stepper"                       # SPEC §1.1b; D13: Stepper only at first launch, the rail stays swappable
RAIL_MARK = "<!--JOURNEY-RAIL-->"              # where the page takes its rail, once (its data: `journey_render.MARKER`)
JOURNEY_FILES = ("page.html", f"rail-{JOURNEY_RAIL}.css", f"rail-{JOURNEY_RAIL}.js")   # what the page is made of


def journey_template():
    """The v3 page's HTML with its rail inlined — the rail's own `.css` and `.js` in place of `RAIL_MARK` and nothing else
    changed (SPEC §1.1b) — and the data's marker left for `journey_render.write_page`."""
    texts = []
    for name in JOURNEY_FILES:
        with open(get_resource(os.path.join(JOURNEY_DIR, name)), encoding="utf-8") as f:
            texts.append(f.read())
    page, css, js = texts
    if page.count(RAIL_MARK) != 1:
        raise ValueError("the journey's template must hold its rail marker once")
    return page.replace(RAIL_MARK, f"<style>\n{css}\n</style>\n<script>\n{js}\n</script>")


def _write_journey(language, app_mode=False, open_browser=True, tagger=None, plan=None):
    """Write the v3 journey: `journey_render.render` over this language's last Generate (the CSVs in results, the
    library store, the ▶'s memos), with the run's own fugashi `tagger` (speed row 1: the pitch makes no second one), in
    `journey_template()`, to `OUTPUT_FILE` (a temp file replaced: a page open in a browser is never half written).
    Returns the watched marks it was drawn with — the very read of the store the page draws from
    (`journey_render.store_facts`' `marks`: J-FIX 3, a mark between two reads was drawn but not signed) — for the run's
    render signature: None with no library store, `library_store.UNREAD` when a store is there and its read failed."""
    from app import journey_render
    if language is None:
        try:
            language = settings_manager.load_settings().get("target_language", "ja")
        except Exception:
            language = "ja"
    facts = journey_render.store_facts(language)
    if facts is not None:
        marks = facts.marks
    else:                                       # no store, or one that couldn't be read: never signed with stones
        from app import analyzer, library_store   # (here only: a run's analyzer is __main__, not loaded twice)
        marks = None if analyzer.journey_marks(language) is None else library_store.UNREAD
    out = journey_render.render(language, facts=facts or False, tagger=tagger if language == "ja" else None, plan=plan)
    path = OUTPUT_FILE                          # the old page's file and name (as `open_report` and the window find it)
    journey_render.write_page(out, journey_template(), path)
    print(f"Journey written at: {path} ({out.head['counts']['eps']} episodes, {out.head['counts']['words']} words)")
    if open_browser:
        if app_mode:
            open_as_app(path)
        else:
            webbrowser.open(f"file://{os.path.abspath(path)}")
    return marks


def generate_static_html(app_mode=False, open_browser=True, language=None, tagger=None, plan=None):
    """Write the journey: v3's page (`_write_journey`) for every look — the look is applied in the page (J-SET), and
    a look saved before it (Zen's too) reads as its new meaning (`journey_settings.page_value`). `language`: the run's
    (the analyzer's `--language`; None: settings.json's); `tagger`: the run's fugashi tagger, `plan`: the plan file,
    both for the render. Returns the marks the journey was drawn from (the page's own read of the store) — None
    without a library store, `library_store.UNREAD` when they couldn't be read — for the run's render signature
    (`analyzer.signed_render`)."""
    print("Writing the journey (v3)...")
    return _write_journey(language, app_mode=app_mode, open_browser=open_browser, tagger=tagger, plan=plan)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-mode", action="store_true", help="Launch in professional app mode")
    args, _unknown = parser.parse_known_args()     # an older argv's --theme / --zen-limit: no page of their own now
    generate_static_html(app_mode=args.app_mode)

if __name__ == "__main__":
    main()
