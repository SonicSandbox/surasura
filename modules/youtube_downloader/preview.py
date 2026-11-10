# SPDX-License-Identifier: GPL-3.0-or-later
"""
YouTube Preview — score a single transcript against your existing library, fast.

Instead of re-running the whole library, this:
  1. tokenizes ONE transcript with the real analyzer tokenizer,
  2. filters known / ignore / blacklist / graduated words exactly like a full run,
  3. overlays each word's *library* value from the cached frequency map
     (results/library_frequency.json, written by every full run since ENGINE_REVISION 11),
  4. re-applies the last run's min-frequency threshold using library + in-video counts
     (so a word the video pushes over the threshold appears), and
  5. emits a single-file report (same template/UX, cached ignore/completed/sort).

Pure helpers here are unit-tested; the analyzer-backed scoring reuses stable helpers.
"""

import os
import re
import glob
import json
import shutil
import tempfile
import threading
import traceback
from collections import namedtuple

from app import settings_manager
from app.path_utils import get_user_file, get_user_files_path, get_data_path, get_resource, list_reader

YOUTUBE_ID_RE = re.compile(r'(?:v=|/shorts/|/embed/|youtu\.be/|/watch\?v=)([0-9A-Za-z_-]{11})')
# A bilibili.tv episode (/play/<season>/<episode>) or upload (/video/<aid>). A bare season link has
# no id of its own — it is a playlist.
BILIBILI_TV_ID_RE = re.compile(
    r'bili(?:bili\.tv|intl\.com)/(?:[a-zA-Z]{2}/)?(?:play/\d+/(\d+)|video/(\d+))', re.I)

_THEME_MAP = {
    'Default (Dark)': 'default', 'Dark Flow': 'world-class',
    'Midnight (Vibrant)': 'midnight-vibrant', 'Modern Light': 'modern-light',
    'Zen Mode': 'zen-focus',
}


class PreviewError(Exception):
    """Raised for user-facing preview failures (missing cache, duplicate, etc.)."""


# Marks a sentence as coming from the video being previewed rather than from a library file.
# Resolved to a real source when the report is written, because only there do we know WHICH video
# an entry belongs to (a playlist preview holds several). Not a real path, so it can never collide
# with one.
VIDEO_SOURCE = "\x00video"


# --------------------------------------------------------------------------- #
# Pure helpers (no analyzer / no network) — unit-tested.
# --------------------------------------------------------------------------- #
def extract_video_id(url):
    """The id a transcript of this link is filed under, else None: the 11-char YouTube video id, or
    "bilibili-<id>" for a bilibili.tv episode — the token the downloader writes into its filenames,
    so the "already in your library" check works for both. Checked first: a bilibili.tv query
    string could happen to contain "v="."""
    m = BILIBILI_TV_ID_RE.search(url or "")
    if m:
        return "bilibili-" + (m.group(1) or m.group(2))
    m = YOUTUBE_ID_RE.search(url or "")
    return m.group(1) if m else None


def score_from_counts(high, low, goal, weights):
    return (weights.get("high", 10) * high
            + weights.get("low", 5) * low
            + weights.get("goal", 2) * goal)


def resolve_min_floor(lib_settings):
    """The minimum combined (library + in-video) count for a word to still surface.

    New runs write 'min_count' (the active word-selection band's effective count floor); older
    caches wrote 'min_freq'. Prefer the new field, fall back to the old, default 0 (keep all).
    """
    return lib_settings.get("min_count", lib_settings.get("min_freq", 0)) or 0


def passes_threshold(lib_total, video_count, min_freq):
    """A word is kept if library + in-video occurrences meet the last run's selection floor.

    This is the answer to 'would a below-floor word appear if the video pushes it over?' — yes:
    we combine the cached library count with the in-video count.
    """
    if not min_freq or min_freq <= 0:
        return True
    return (lib_total + video_count) >= min_freq


def pick_contexts(candidates, min_chars, pref_max, limit):
    """candidates: list of (other_unknowns, length, sentence). Prefer i+1 (0 others),
    then sentences inside the ideal length band, then closest to the band midpoint."""
    mid = (min_chars + pref_max) / 2
    ordered = sorted(
        candidates,
        key=lambda c: (c[0], 0 if min_chars <= c[1] <= pref_max else 1, abs(c[1] - mid)),
    )
    return [c[2] for c in ordered[:limit]]


# --------------------------------------------------------------------------- #
# Library cache + guard + workspace
# --------------------------------------------------------------------------- #
def library_index_path():
    return get_user_file(os.path.join("results", "library_frequency.json"))


def load_library_index():
    """Return (words_map, settings_dict). words_map is None if the cache is absent."""
    path = library_index_path()
    if not os.path.exists(path):
        return None, {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("words", {}), data.get("settings", {})
    except Exception:
        return None, {}


def has_library_cache():
    return os.path.exists(library_index_path())


def library_contexts_path():
    return get_user_file(os.path.join("results", "priority_learning_list.csv"))


def load_library_contexts():
    """Library example sentences from the last run's priority list.

    Returns (by_lr, by_lemma): {(Word, Reading): [(sentence, source), ...]} keyed both ways.
    These are the curated i+1 contexts the analyzer already chose for each library word — used to
    fill a preview word's 'additional' sentences when the video itself only uses it once or twice.

    `source` is the matching `Src N` (the library file that sentence came from) so the preview can
    show the same source badge as the main report. It is "" for results generated before that
    column existed.
    """
    path = library_contexts_path()
    by_lr, by_lemma = {}, {}
    if not os.path.exists(path):
        return by_lr, by_lemma

    def _ctxnum(c):
        try:
            return int(c.rsplit(" ", 1)[1])
        except Exception:
            return 999

    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in list_reader(f):
                cols = sorted([c for c in row if c.startswith("Context ")], key=_ctxnum)
                pairs = []
                for col in cols:
                    sentence = (row.get(col) or "").strip()
                    if not sentence:
                        continue
                    src = (row.get("Src " + col.rsplit(" ", 1)[1]) or "").strip()
                    pairs.append((sentence, src))
                if not pairs:
                    continue
                w, rd = row.get("Word", ""), row.get("Reading", "")
                by_lr[(w, rd)] = pairs
                by_lemma.setdefault(w, pairs)
    except Exception:
        return {}, {}
    return by_lr, by_lemma


def video_in_library(video_id, language):
    """Fast guard: is a file for this video id already anywhere in the library?

    Scans filenames only (the [id] is embedded in every downloaded transcript name);
    no file contents are read, short-circuits on first hit.
    """
    if not video_id:
        return False
    token = f"[{video_id}]"
    base = get_data_path(language)
    for sub in ("HighPriority", "LowPriority", "GoalContent", "Processed", "Graduated", "Library"):   # Library: 3.0's copies
        d = os.path.join(base, sub)
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in files:
                if token in fn:
                    return True
    return False


def workspace():
    return os.path.join(tempfile.gettempdir(), "surasura_preview")


def reset_workspace():
    """Clear & recreate the single preview workspace (never more than one at a time)."""
    d = workspace()
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def cleanup_workspace():
    shutil.rmtree(workspace(), ignore_errors=True)


# --------------------------------------------------------------------------- #
# The scorer (reuses the analyzer's tokenizer + known-words loading)
# --------------------------------------------------------------------------- #
def _az():
    """The analyzer, imported where the scoring runs (3.0: the scoring child, never the window's process — AD4-2)."""
    from app import analyzer
    return analyzer


def __getattr__(name):
    """`preview.az`: the analyzer, imported on first use."""
    if name == "az":
        return _az()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _build_tokenizer_and_known(language, settings):
    # Match a full run: set the analyzer globals the tokenizer/loaders read.
    az = _az()
    az.SANITIZE_JA = (language == "ja")  # JA lemmas are always sanitized now (matches a full run)
    az.SKIP_SINGLE_CHARS = bool(settings.get("exclude_single", True))
    try:
        az.LOGIC.update(settings.get("logic", {}))
    except Exception:
        pass

    # The Chinese script the library is read in (`zh_script`): the video's words must be spelled like
    # the library's cached ones, or every word would look new. Known words convert via the tokenizer.
    from app.zh_script import effective
    script = effective(language, settings.get("zh_script"))
    if language == "zh":
        tokenizer = az.ChineseTokenizer(reinforce_segmentation=settings.get("reinforce_segmentation", False),
                                        script=script)
    else:
        tokenizer = az.JapaneseTokenizer()

    uf = get_user_files_path(language)
    known_tuples, known_lemmas = az.load_known_words(os.path.join(uf, "KnownWord.json"), tokenizer)
    ignore = az.load_simple_list(os.path.join(uf, "IgnoreList.txt"), script, language)
    ignore |= az.load_simple_list(os.path.join(uf, "Blacklist.txt"), script, language)
    ignore |= az.load_simple_list(os.path.join(uf, "GraduatedList.txt"), script, language)
    ignore |= az.load_ignored_entries(uf, script, language)       # KnownWord.json's IGNORED entries (+ names)
    return tokenizer, known_tuples, known_lemmas, ignore


def _names_in(text):
    """With Ignore names on, the video's own names — what the token store will record for it once it is in the
    library (app/names.py): read as the store reads a file, so a new episode's new names are ignored here as they will
    be on the list. The library's names are already in the ignore set (`load_ignored_entries`)."""
    from app import names
    az = _az()
    record = names.Record()
    for _sentence in az.JapaneseTokenizer(library=False).tokenize_sentences(text, names=record):
        pass
    return set(record.data()["n"])


def analyze_transcript(transcript_path, language):
    """Return (words_rows, stats) for the report, scored against the cached library."""
    az = _az()
    settings = settings_manager.load_settings()
    lib_words, lib_settings = load_library_index()
    if lib_words is None:
        raise PreviewError("No library frequency cache yet — run a full analysis first.")

    # Minimum combined count for a word to surface (may be fractional — a band's ppm->count
    # floor — so keep it numeric rather than int()). Prefers the new 'min_count' field.
    min_freq = resolve_min_floor(lib_settings)
    weights = lib_settings.get("weights", {"high": 10, "low": 5, "goal": 2})
    lib_ctx_lr, lib_ctx_lemma = load_library_contexts()

    tokenizer, known_tuples, known_lemmas, ignore = _build_tokenizer_and_known(language, settings)
    skip_single = az.SKIP_SINGLE_CHARS
    logic = settings.get("logic", {})
    ctx_cfg = logic.get("context", {})
    min_chars = ctx_cfg.get("min_chars", 10)
    pref_max = ctx_cfg.get("preferred_max_chars", 50)
    max_contexts = ctx_cfg.get("max_contexts", 3)

    def is_known(l, r):
        return (l, r) in known_tuples or l in known_lemmas or l in ignore

    text = az.extract_text(transcript_path, language)
    if language == "ja" and (settings.get("logic") or {}).get("ignore_names"):
        ignore = ignore | _names_in(text)

    total_instances = 0
    known_instances = 0
    counts, surfaces, contexts = {}, {}, {}

    for s_text, tokens in tokenizer.tokenize_sentences(text):
        sent_unknowns = []
        # Japanese: a one-character word counts only where the list can offer it (analyzer.unoffered: a one-kanji
        # dictionary word standing on its own) — the rest is nothing to learn, as the report's progressive list
        # counts it.
        skip = az.unoffered(s_text, tokens) if skip_single and language == "ja" else ()
        for t_no, (l, r, surf, _orth) in enumerate(tokens):
            total_instances += 1
            if is_known(l, r):
                known_instances += 1
                continue
            if t_no in skip:
                known_instances += 1
                continue  # not learnable here; leave out of the candidate set
            if skip_single and language != "ja" and len(l) == 1:
                continue  # not learnable; leave out of the candidate set
            sent_unknowns.append((l, r, surf))
        unique_unknown = set((l, r) for (l, r, _) in sent_unknowns)
        for (l, r, surf) in sent_unknowns:
            key = (l, r)
            counts[key] = counts.get(key, 0) + 1
            surfaces[key] = surf
            others = len(unique_unknown - {key})
            contexts.setdefault(key, []).append((others, len(s_text), s_text))

    rows = []
    for (l, r), cnt in counts.items():
        lib = lib_words.get(f"{l}|{r}", [0, 0, 0, 0])
        lib_total, lib_high, lib_low, lib_goal = (lib + [0, 0, 0, 0])[:4]
        if not passes_threshold(lib_total, cnt, min_freq):
            continue
        # Examples: the video's own sentence(s) first (most relevant to what you're about to
        # watch), then the library's curated sentences for this word fill the rest.
        # The video's own sentences carry no library file — their source IS the video, which the
        # report renders as a ▶ badge linking back to it. Library sentences keep their own file.
        video_ctx = [(s, None) for s in
                     pick_contexts(contexts[(l, r)], min_chars, pref_max, max_contexts)]
        # Tolerate a bare sentence as well as (sentence, source): the pairing is new, and a plain
        # list is what an older cache — or a caller supplying its own contexts — still hands over.
        lib_ctx = [c if isinstance(c, (tuple, list)) else (c, "")
                   for c in (lib_ctx_lr.get((l, r)) or lib_ctx_lemma.get(l) or [])]
        merged, seen = [], set()
        for sent, src in list(video_ctx) + list(lib_ctx):
            if sent and sent not in seen:
                seen.add(sent)
                merged.append((sent, src))
            if len(merged) >= max_contexts:
                break
        rows.append({
            "Word": l, "Reading": r,
            # The list's own score where the library has one — it halves a word read through its known
            # word (利用者 with 利用 known, U9) — so the order matches the list; else from the counts.
            "Score": lib[5] if len(lib) > 5 else score_from_counts(lib_high, lib_low, lib_goal, weights),
            "Occurrences (Global)": lib_total + cnt,
            "Count (High)": lib_high, "Count (Low)": lib_low,
            "_video": cnt,
            "_ctx": merged,
        })

    # Library leverage first (your normal priority order), then in-video repetition.
    rows.sort(key=lambda x: (-x["Score"], -x["_video"]))

    total = total_instances or 1
    baseline = round(known_instances / total * 100, 2)
    running = known_instances
    out = []
    for row in rows:
        cur = round(running / total * 100, 2)
        running += row["_video"]
        new = round(running / total * 100, 2)
        w = {
            "Word": row["Word"], "Reading": row["Reading"], "Score": row["Score"],
            "Occurrences (Global)": row["Occurrences (Global)"],
            "Count (High)": row["Count (High)"], "Count (Low)": row["Count (Low)"],
            "Baseline %": baseline, "Current %": cur, "New %": new,
            "Known Count": known_instances, "Total Count": total,
        }
        for i, (ctx, src) in enumerate(row["_ctx"], 1):
            w[f"Context {i}"] = ctx
            # None => the video itself; a path => the library file that sentence came from.
            w[f"Src {i}"] = VIDEO_SOURCE if src is None else src
        out.append(w)

    return out, {"total": total, "known": known_instances, "learnable": len(out)}


# --------------------------------------------------------------------------- #
# Report generation (reuses the web_app template + compression)
# --------------------------------------------------------------------------- #
def _applied_theme(settings):
    return _THEME_MAP.get(settings.get("theme", "Dark Flow"), "world-class")


def _resolve_preview_sources(files, settings):
    """Turn every `Src N` on a preview word into an index in the report's source table.

    Two kinds of source appear in a preview: the VIDEO you're previewing (its own sentences) and the
    library files the extra sentences were borrowed from. The first becomes a ▶ badge that opens the
    video; the second behaves exactly as it does in the main report.

    Returns the source table. Mutates the word rows in place, as the generator does."""
    from app.static_html_generator import (AnchorFinder, _group_label, _load_source_map,
                                           _video_link)
    from app.path_utils import infer_source_type
    from app.zh_script import effective
    source_map = _load_source_map()
    # Sentences are in the library's Chinese script; the finder maps them back to the file's wording.
    language = settings.get("target_language", "ja")
    script = effective(language, settings.get("zh_script"))
    finder = (AnchorFinder(script=script, language=language)
              if settings.get("source_display", "off") != "off" else None)
    table, index = [], {}

    def _idx(key, name, path):
        # A VIDEO_SOURCE means "this entry's own video", so it must be keyed per file — every
        # transcript in a playlist preview resolves to a different video.
        cache_key = (key, name) if key == VIDEO_SOURCE else key
        if cache_key in index:
            return index[cache_key]
        if key == VIDEO_SOURCE:
            # The video being previewed: YouTube, or bilibili.tv (whose badge opens the episode
            # page recorded in the transcript's cue sidecar).
            stype = "bilibili" if infer_source_type(name) == "bilibili" else "youtube"
            side = AnchorFinder().sidecar(path) if path else None
            row = [name, stype, path or name, name, _video_link(name, stype, side)]
        else:
            meta = source_map.get(key, {})
            row = [meta.get("name") or os.path.basename(key), meta.get("type") or "text",
                   meta.get("abs") or key, _group_label(key), ""]
        index[cache_key] = len(table)
        table.append(row)
        return index[cache_key]

    for name, words, path in files:
        for word in words:
            for col in [c for c in list(word) if c.startswith("Src ")]:
                key = word.get(col)
                if not key:
                    word[col] = None
                    continue
                word[col] = _idx(key, name, path)
                # The video's own sentence: its anchor, and when its line starts and ends (Connect's line reader,
                # E5.1), when the transcript still has its sidecar.
                num = col.rsplit(" ", 1)[1]
                if finder is not None and key == VIDEO_SOURCE and path:
                    sentence = word.get(f"Context {num}") or ""
                    anchor = finder.anchor(path, sentence)
                    if anchor:
                        word[f"Frag {num}"] = anchor
                    at, end = finder.line(path, sentence)
                    if at is not None:
                        word[f"At {num}"] = at
                        word[f"End {num}"] = end
    return table


def generate_preview_html(files, language, out_path):
    """Inject a dataset into the web_app template and write out_path.

    `files` is a list of (filename, words_rows) or (filename, words_rows, transcript_path). One
    entry per transcript (a single video → one entry; a playlist → one entry per video, shown in the
    progressive sidebar). The priority view merges all words, ranked by Score. The path is optional
    so older callers keep working; without it a sentence can still link to its video, just not to
    the exact moment.
    """
    from app.static_html_generator import compress_list_of_dicts
    settings = settings_manager.load_settings()
    files = [(f[0], f[1], f[2] if len(f) > 2 else None) for f in files]

    # Resolve source badges BEFORE compressing — compression freezes the column set.
    source_table = _resolve_preview_sources(files, settings)

    progressive = [{
        "filename": fn,
        "words": compress_list_of_dicts(words),
        "total_words": len(words),
        "is_goal_content": False,
    } for fn, words, _p in files]
    merged = sorted((w for _fn, ws, _p in files for w in ws),
                    key=lambda x: -x.get("Score", 0))
    data = {
        "progressive": progressive,
        "priority": compress_list_of_dicts(merged),
        "completed_files": [],
        "file_order": [fn for fn, _w, _p in files],
    }
    template_path = get_resource(os.path.join("templates", "web_app.html"))
    with open(template_path, encoding="utf-8") as f:
        html = f.read()

    wpd = settings.get("words_per_day", 5)
    show_wpd = settings.get("show_words_per_day", True)
    display = settings.get("source_display", "off")
    if display not in ("off", "icon", "filename", "full"):
        display = "off"
    injected = (
        f"let globalData = {json.dumps(data, ensure_ascii=False)};\n"
        f"        let globalTheme = '{_applied_theme(settings)}';\n"
        f"        let globalLogic = {json.dumps(settings.get('logic', {}), ensure_ascii=False)};\n"
        f"        let globalLanguage = '{language}';\n"
        f"        let globalWordsPerDay = {wpd};\n"
        f"        let globalShowWordsPerDay = {'true' if show_wpd else 'false'};\n"
        f"        let globalSources = {json.dumps(source_table, ensure_ascii=False)};\n"
        f"        let globalSourceDisplay = '{display}';"
    )
    html = html.replace("let globalData = null;", injected)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


# --------------------------------------------------------------------------- #
# Commit to front (optional, off by default)
# --------------------------------------------------------------------------- #
def build_manifest_entry(rel_path, title):
    """One PHASE_1_NOW manifest entry, mirroring the content importer's shape."""
    return {
        "title": title,
        "physical_path": rel_path,
        "parent_folder": "",
        "origin_source": "YouTube Preview",
        "type": "File",
        "status": "active",
    }


def _library_mode(language, data_root):
    """The library store's mode for `language` ('store' | 'read-only' | 'json'); 'json' when it can't tell."""
    try:
        from app import library_store
        return library_store.check_mode(language, data_root, busy_wait=0.0)[0]
    except Exception:
        return "json"


def commit_to_front(transcript_paths, language):
    """Copy transcripts into HighPriority and prepend them to PHASE_1_NOW (front of NOW).

    File-only: does NOT mark any words known. Returns the list of added filenames.

    With a library store (2.5, Library_Store_Spec §7): one `insert` at the top of NOW, with the same entry
    fields (it runs on the preview's worker). Read-only mode refuses, adding nothing. JSON mode (no store yet):
    the manifest, as before, its replace under the store's copy lock.
    """
    data_root = get_data_path(language)
    user_files_root = get_user_files_path(language)
    mode = _library_mode(language, data_root)
    if mode == "read-only":
        raise PreviewError("Your library can't take new files until it's repaired (see the dashboard's notice), "
                           "so nothing was added.")
    high_dir = os.path.join(data_root, "HighPriority")
    os.makedirs(high_dir, exist_ok=True)
    if mode == "store":
        return _commit_to_store(transcript_paths, language, data_root, user_files_root, high_dir)
    manifest_path = os.path.join(user_files_root, "master_manifest.json")

    manifest = {}
    if os.path.exists(manifest_path):
        # An order we can't read (locked by antivirus or sync, caught mid-write, saved with a BOM)
        # must stop here. Treating it as empty used to write the preview's entries OVER the whole
        # library order — the single source of truth for it.
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            raise PreviewError(f"Couldn't read your library order, so nothing was added: {e}")
        if not isinstance(manifest, dict):
            raise PreviewError("Your library order file isn't in the expected shape, so nothing was added.")
    schedule = manifest.setdefault("schedule", {})
    now = schedule.setdefault("PHASE_1_NOW", [])
    if not isinstance(now, list):
        now = []

    new_entries, added = [], []
    existing = {e.get("physical_path") for e in now if isinstance(e, dict)}
    for src in transcript_paths:
        name = os.path.basename(src)
        dest = os.path.join(high_dir, name)
        if not os.path.exists(dest):
            shutil.copy2(src, dest)
        rel = os.path.relpath(dest, data_root).replace("\\", "/")
        if rel in existing or any(e["physical_path"] == rel for e in new_entries):
            continue
        new_entries.append(build_manifest_entry(rel, name))
        added.append(name)

    schedule["PHASE_1_NOW"] = new_entries + now  # prepend, preserving order
    manifest["schedule"] = schedule
    try:
        # Atomic, like every other writer of this file: an interrupted write can't truncate it. The swap takes the
        # library store's copy lock (§6.7), so it never lands between the store's helper's look and its replace.
        from app import library_store
        if library_store.json_mode_save(language, data_root, user_files_root, manifest) == "unlocked":
            print("Saved the library order without the copy lock (its lock file couldn't be opened).")
    except Exception as e:
        raise PreviewError(f"Saved the file(s) but couldn't update the library order: {e}")
    return added


def _commit_to_store(transcript_paths, language, data_root, user_files_root, high_dir):
    """Store mode: copy the transcripts in (the file work), then one `insert` at the top of NOW; a file already in
    the library is left where it is. Returns the names added."""
    from app import library_store
    store = library_store.open_store(language, data_root, user_files_root, role="window")
    if store is None:
        raise PreviewError("Your library is busy for a moment, so nothing was added. Try again.")
    with store:
        started_at = library_store._now()
        dests, entries = [], []
        for src in transcript_paths:
            name = os.path.basename(src)
            dest = os.path.join(high_dir, name)
            if not os.path.exists(dest):
                shutil.copy2(src, dest)
            rel = os.path.relpath(dest, data_root).replace("\\", "/")
            if dest in dests:
                continue
            dests.append(dest)
            entries.append(build_manifest_entry(rel, name))
        try:
            change = store.insert(dests, "now", "top", started_at=started_at, entries=entries)
        except Exception as e:
            raise PreviewError(f"Saved the file(s) but couldn't add them to your library: {e}")
        if change is None or not change.added:
            return []
        library_store.spawn_maintain(language)           # the copy, written by the helper
        return [os.path.basename(store.item(i)["rel_path"]) for i in change.added]


# --------------------------------------------------------------------------- #
# The 3.0 window's pipeline (W3.4 row 4): the Tk PreviewGui._run, moved here Qt-free
# --------------------------------------------------------------------------- #
# The 3.0 window's lines live in its strings table (`qt_strings`, AD4-13); the pipeline answers with them.
from modules.youtube_downloader.qt_strings import (  # noqa: E402
    ALREADY_IN_LIBRARY, BILIBILI_COM_REFUSED, FETCHING, LOOKING_UP, NO_CACHE, NO_TRANSCRIPT, NO_TRANSCRIPT_BILIBILI,
    NO_YTDLP, OTHER_LANGUAGE, SCORE_FAILED, SCORING, STORE_BUSY, STORE_DAMAGED, UNEXPECTED)

# html: the preview to open (None: nothing to open); added: the names added to the front of Current; note: why the add
# was refused (the preview still opens); error: why there is nothing to open; generate: a Generate would fix it;
# workspace: the run's own folder (None until made) — its caller removes it once nothing needs it (AD4-3).
Outcome = namedtuple("Outcome", "html added note error generate workspace",
                     defaults=(None, (), None, None, False, None))
KIND = "youtube"                                       # the job kind of a preview's fetch and scoring (jobs.RESOURCES)
RESULT = "@result "                                    # the scoring child's answer line
CHILD_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview_child.py")


def cache_problem(language):
    """Why the library's cached list can't score a video in `language`, or None: no cache yet, or the cache is another
    language's (results/ holds one language's run; the Tk preview never looked: inv defect 6). A cache that names no
    language (written before it did) is taken as it is."""
    if not has_library_cache():
        return NO_CACHE
    _words, settings = load_library_index()
    cached = (settings or {}).get("language")
    if cached and cached != language:
        return OTHER_LANGUAGE
    return None


def add_to_front(transcript_paths, language, busy_wait=None):
    """3.0's add to the front of Current: **only in the library store's mode** (G1.2-18: no JSON mode in 3.0; IK-2).
    A store that can't be read as ready right now, or no store, says "busy, try again" and copies nothing; a store
    marked damaged says it needs repair and copies nothing. Otherwise `_commit_to_store`: the files copied in and one
    `insert` at the top of Current. -> the names added. Raises PreviewError."""
    from app import library_store
    data_root = get_data_path(language)
    user_files_root = get_user_files_path(language)
    try:
        mode, reason = library_store.check_mode(
            language, data_root, busy_wait=library_store.BUSY_AT_OPEN if busy_wait is None else busy_wait)
    except Exception:
        mode, reason = None, None
    if mode != "store":
        if mode == "read-only" and reason == "damaged":
            raise PreviewError(STORE_DAMAGED)
        raise PreviewError(STORE_BUSY)
    high_dir = os.path.join(data_root, "HighPriority")
    os.makedirs(high_dir, exist_ok=True)
    return _commit_to_store(transcript_paths, language, data_root, user_files_root, high_dir)


def new_workspace():
    """A preview's own workspace: one per run, so a closed window's run that is still ending never shares a folder with
    a newer one (the one shared `surasura_preview` let a close delete a newer run's files: AD4-3)."""
    return tempfile.mkdtemp(prefix="surasura_preview_")


def remove_workspaces(paths):
    """(A worker.) The workspaces removed (a preview the user may still have open goes with its window)."""
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


def fetch_here(target_url, url, lang, ws, should_stop=None, extract=None, ensure=None):
    """(A worker.) The transcript(s) of `target_url` fetched into `ws`: yt-dlp made ready, then the download — its
    child ended by a stop (`downloader.stopping`). -> (sorted .txt paths, the line saying why there are none, or None)."""
    from modules.youtube_downloader import downloader as core
    from modules.youtube_downloader import ytdlp_manager
    extract = extract or core.extract
    ensure = ensure or ytdlp_manager.ensure_available

    def quiet(*_args):
        return None
    with core.stopping(should_stop):
        if not ensure(quiet):
            return [], NO_YTDLP
        extract([target_url], ws, lang=core.LANG_BY_CODE.get(lang, core.DEFAULT_LANG), channel_first=True, log=quiet,
                should_stop=should_stop)
    txts = sorted(glob.glob(os.path.join(ws, "**", "*.txt"), recursive=True))
    if not txts:
        return [], NO_TRANSCRIPT_BILIBILI if core.site_of(url) == 'bilibili' else NO_TRANSCRIPT
    return txts, None


def score_here(transcripts, lang, out_html):
    """Each transcript scored against the library's list, and the preview written to `out_html` — the CPU work (the
    tokenizer, the analyzer's globals): 3.0 runs it in the scoring child (`child_main`). -> out_html. Raises
    PreviewError."""
    files = []
    for t in transcripts:
        words, _ = analyze_transcript(t, lang)
        files.append((os.path.splitext(os.path.basename(t))[0], words, t))
    generate_preview_html(files, lang, out_html)
    return out_html


def run_preview(url, lang, add_front, ask_playlist, status, should_stop=None, probe=None, extract=None,
                ensure=None, fetch=None, score=None):
    """(A worker.) One preview, in the Tk pipeline's order (preview_gui.py:220-282), with 3.0's fixes:

    1. bilibili.com refused; 2. the cached list checked for this language (none, or another's → a Generate is asked
    for, nothing fetched); 3. the link looked up; a video inside a playlist → `ask_playlist(count)` (True: the whole
    playlist; False: just this video; None: the window closed — nothing more happens); 4. a single video already in the
    library → nothing fetched; 5. the transcript(s) fetched into the run's own workspace (`fetch(target_url, ws)` ->
    (transcripts, why none)); 6. scored, and the preview written (`score(transcripts, out_html)` -> (html, why not));
    7. only then, with `add_front`, the add to the front of Current (store mode only) — **a refused add never hides the
    preview** (its line is the outcome's `note`). The fetch and the scoring run here by default (`fetch_here`,
    `score_here`); the 3.0 window hands its own (`Runs`: the fetch a youtube job, the scoring a child). `status(line)`
    names each step; `should_stop()` (the window closed) ends the run between steps and ends the lookup's yt-dlp
    child. -> an Outcome (its `workspace` the caller's to remove)."""
    from modules.youtube_downloader import downloader as core
    probe = probe or core._probe
    stopped = should_stop or (lambda: False)
    fetch = fetch or (lambda target, ws: fetch_here(target, url, lang, ws, should_stop, extract, ensure))
    score = score or (lambda transcripts, out: (score_here(transcripts, lang, out), None))
    ws = None

    def quiet(*_args):
        return None
    try:
        if core.site_of(url) == 'bilibili.com':
            return Outcome(error=BILIBILI_COM_REFUSED)
        problem = cache_problem(lang)
        if problem:
            return Outcome(error=problem, generate=True)
        vid = extract_video_id(url)
        status(LOOKING_UP)
        with core.stopping(should_stop):
            info = probe(url, quiet)
        is_playlist = bool(info and (info.get('_type') == 'playlist' or info.get('entries') is not None))
        target_url, single = url, True
        if is_playlist:
            if vid:                                            # watch?v=…&list=…: the user chooses
                whole = ask_playlist(len(info.get('entries') or []))
                if whole is None or stopped():
                    return Outcome()
                if whole:
                    single = False
                else:
                    target_url = f"https://www.youtube.com/watch?v={vid}"
            else:
                single = False                                 # a pure playlist
        if single and vid and video_in_library(vid, lang):
            return Outcome(error=ALREADY_IN_LIBRARY)
        if stopped():
            return Outcome()
        status(FETCHING)
        ws = new_workspace()
        txts, problem = fetch(target_url, ws)
        if stopped():
            return Outcome(workspace=ws)
        if problem:
            return Outcome(error=problem, workspace=ws)
        status(SCORING)
        out_html, problem = score(txts, os.path.join(ws, "preview.html"))
        if problem or not out_html:
            return Outcome(error=problem, workspace=ws) if problem else Outcome(workspace=ws)
        added, note = (), None
        if add_front and not stopped():
            try:
                added = tuple(add_to_front(txts, lang))
            except PreviewError as e:
                note = str(e)
        return Outcome(html=out_html, added=added, note=note, workspace=ws)
    except PreviewError as e:
        return Outcome(error=str(e), workspace=ws)
    except Exception as e:
        return Outcome(error=UNEXPECTED.format(why=e), workspace=ws)


# --------------------------------------------------------------------------- #
# The 3.0 window's runs: the fetch a youtube job, the scoring a child (AD4-2, IK-29, IK-31)
# --------------------------------------------------------------------------- #
def child_argv(lang, out_html, transcripts, frozen=None):
    """The scoring child's command, for `tools.run` (whose `command` maps it): frozen, app_entry's `youtube_preview`;
    from source, this module's script (`preview_child.py`, the project on the child's PYTHONPATH)."""
    from app import path_utils
    frozen = path_utils.is_frozen() if frozen is None else frozen
    return ["youtube_preview" if frozen else CHILD_SCRIPT, "--language", lang, "--out", out_html] + list(transcripts)


def child_main(argv):
    """The scoring child (`youtube_preview --language <l> --out <html> <transcript>…`): `score_here`, then one RESULT
    line — JSON, `{"html": path}` or `{"error": line}`. -> its exit code: 0, or 1 on an unexpected failure (its trace
    in the tool's log)."""
    import argparse
    parser = argparse.ArgumentParser(prog="youtube_preview")
    parser.add_argument("--language", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("transcripts", nargs="+")
    args = parser.parse_args(argv)
    try:
        answer = {"html": score_here(args.transcripts, args.language, args.out)}
    except PreviewError as e:
        answer = {"error": str(e)}
    except Exception:
        traceback.print_exc()
        return 1
    print(RESULT + json.dumps(answer, ensure_ascii=False), flush=True)
    return 0


class Runs:
    """A 3.0 preview's jobs (Qt-free): `fetch` (for `run_preview`) runs `fetch_here` as a youtube job on a thread of its
    own, `score` the scoring child through `tools.run` (a youtube job too) — each shown in the bottom bar, each waited
    for on the asking (worker) thread, each ended by `cancel()` (the window closed), by a cancel in the bar or by the
    app's quit (`on_quit="cancel"`: a stop ends the fetch's yt-dlp child, the scoring child is terminated). `before`:
    run in the scoring child's tool thread just before it starts (the settings written first)."""

    def __init__(self, registry, lang, url, label, before=None, extract=None, ensure=None):
        self.registry, self.lang, self.url, self.label = registry, lang, url, label
        self.before, self.extract, self.ensure = before, extract, ensure
        self.cancelled = False
        self.current = None
        self._lock = threading.Lock()

    def cancel(self):
        with self._lock:
            self.cancelled = True
            job = self.current
        if job is not None:
            job.cancel()

    def _submitted(self, job):
        with self._lock:
            self.current = job
            stop_now = self.cancelled
        if stop_now:
            job.cancel()

    def fetch(self, target_url, ws):
        if self.cancelled:
            return [], None
        box = {"answer": ([], None), "started": False}
        stop, done = threading.Event(), threading.Event()

        def start(job):
            box["started"] = True
            threading.Thread(target=body, args=(job,), name="youtube-preview-fetch", daemon=True).start()

        def cancel(_job):
            stop.set()
            if not box["started"]:
                done.set()

        def body(job):
            try:
                job.progress(FETCHING)
                box["answer"] = fetch_here(target_url, self.url, self.lang, ws, stop.is_set, self.extract, self.ensure)
                job.finish(ok=True, cancelled=stop.is_set())
            except Exception as e:
                box["answer"] = ([], UNEXPECTED.format(why=e))
                job.finish(ok=False, message=UNEXPECTED.format(why=e))
            finally:
                done.set()
        self._submitted(self.registry.submit(KIND, self.label, start, cancel=cancel, on_quit="cancel"))
        done.wait()
        return ([], None) if stop.is_set() else box["answer"]

    def score(self, transcripts, out_html):
        from app.services import tools
        if self.cancelled:
            return None, None
        box = {"answer": None}
        done = threading.Event()

        def line(text):
            if text.startswith(RESULT):
                try:
                    box["answer"] = json.loads(text[len(RESULT):])
                except ValueError:
                    pass

        def ended(result):
            box["result"] = result
            done.set()
        job = tools.run(self.registry, KIND, self.label, child_argv(self.lang, out_html, transcripts),
                        on_line=line, on_result=ended, before=self.before, on_quit="cancel")
        job.progress(SCORING)
        self._submitted(job)
        done.wait()
        result, answer = box["result"], box["answer"] or {}
        if result.cancelled:
            return None, None
        if result.code == 0 and answer.get("html"):
            return answer["html"], None
        if result.code == 0 and answer.get("error"):
            return None, answer["error"]
        return None, SCORE_FAILED.format(why=result.why or f"code {result.code}", log=result.log or "")


def open_report(path, app_mode=False):
    """(A worker.) Open the preview: an app window with `open_app_mode`, else the browser (the Tk `_open_report`)."""
    if app_mode:
        try:
            from app.static_html_generator import open_as_app
            open_as_app(path)
            return
        except Exception:
            pass
    import webbrowser
    webbrowser.open(f"file://{os.path.abspath(path)}")
