"""The match index — how a word on an Anki card is recognised as a word on Surasura's list.

Core since the Anki backlog became something the report shows too (Junban_Backlog_Spec §5.1): the
report's backlog badge and Junban's reorder must give the same answer, and core never imports
`modules/`. `modules/junban/match.py` re-exports every name — the `app/anki_connect.py` /
`modules/junban/ankiconnect.py` precedent — so Junban's call sites and tests read it unchanged.

Two sides that never agreed until now. anki_miner writes UniDic's **`orth_base`** onto the card for
verbs and adjectives (the surface form otherwise); Surasura's analyser writes UniDic's canonical
**`lemma`**. They disagree systematically, and not rarely — measured on the live collection, **20.6%
of mined words can only ever match through the orth**:

    引きずって  ->  lemma 引き摺る   orth 引きずる    <- the card says 引きずる
    お伽話      ->  lemma 御伽話     orth お伽話
    スドウ      ->  lemma スドウ     orth 須藤        <- the show writes 須藤

That is why `priority_learning_list.csv` grew an `Orth` column (spec §4, "D4"), and why the index
below keys **`Orth` first and `Word` second**: the orth is the spelling the user actually sees, so it
is the primary key, and the lemma catches every noun and anything unconjugated.

Scope and cost
--------------
Pure: no network, no tkinter, no writes, and deliberately **no fugashi**. `settings_manager` imports
the junban package on every settings load, and that package reaches this file, so a tokenizer must
never become reachable from it. The
tokenizer fallback described in spec §6 (tokenize the Anki word, look the lemma up against `Word`) is
therefore *not* here — it belongs to whoever already holds a tokenizer, and it is a secondary key
anyway: it mis-tokenises isolated words (`まく` -> `膜`) and 15.6% of real mined expressions are
multi-token.

The shape of `analyzer.load_known_words` is the model followed here — trust the explicit string
first, then the derived forms — because it solves the same problem from the other end.
"""

import csv
import html
import json
import os
import re
import unicodedata
from collections import namedtuple

# --- normalisation ---------------------------------------------------------------------------- #
# Ruby readings go BEFORE tags, or stripping <ruby>漢字<rt>かんじ</rt></ruby> fuses the reading onto
# the word and yields 漢字かんじ, which matches nothing on either side. Mirrors the same guard in
# `app/anki_utils.extract_field_text`.
_RUBY_RE = re.compile(r'<rp>.*?</rp>|<rt>.*?</rt>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r'<[^<]+?>')
# An unterminated <img (a truncated field, a hand-edited note) survives the tag pass. It is the one
# residue worth naming: a picture-only field is common on mined cards and must reduce to "".
_IMG_RE = re.compile(r'<img[^>]*>?', re.IGNORECASE)
_SOUND_RE = re.compile(r'\[sound:[^\]]*\]?', re.IGNORECASE)
# Anki furigana: a bracket binds to the token immediately before it, and each ruby segment after the
# first is introduced by a space. Consuming that separator here is what turns 日本[にほん] 語[ご]
# into 日本語 rather than "日本 語" — a mined word never contains a space.
_FURIGANA_RE = re.compile(r'\s*([^\s\[\]]+)\[[^\]]*\]')
_STRAY_BRACKET_RE = re.compile(r'\[[^\]]*\]')
# Zero-width joiners and a stray BOM ride along in copied-and-pasted fields and are invisible in the
# Anki editor, so a mismatch caused by one is impossible to see and impossible to fix by hand.
_ZERO_WIDTH_RE = re.compile('[\u200b\u200c\u200d\u2060\ufeff\u00ad]')
_WHITESPACE_RE = re.compile(r'\s+')
# Hiragana and katakana only (\u30fc included) \u2014 the words the kana fold (L4) may compare.
_KANA_ONLY_RE = re.compile('^[\u3041-\u309f\u30a0-\u30ff]+$')

# The columns `priority_learning_list.csv` carries example sentences in, best first. Read by NAME —
# an older results folder that predates them simply offers no sentence (WP-L).
CONTEXT_COLUMNS = ("Context 1", "Context 2", "Context 3")


def normalize_word(raw):
    """The one spelling both sides agree on, or `""` when the field holds no word at all.

    Mirrors anki_miner's own known-words scan step for step (spec §5), because a normalisation the
    two sides do differently is worse than none: it produces confident, silent mismatches.

      1. drop ruby readings, then HTML tags, then `<img>` and `[sound:…]` residue
      2. unescape entities — *after* the tags, so an escaped `&lt;b&gt;` stays literal text
      3. drop zero-width characters
      4. strip Anki furigana brackets (食べる[たべる] -> 食べる)
      5. NFC, collapse whitespace, strip

    **Never lowercased.** Case carries no meaning in Japanese or Chinese, and folding it would
    quietly damage the romaji and Latin entries that do turn up in real decks.
    """
    if not isinstance(raw, str) or not raw:
        return ""

    text = _RUBY_RE.sub('', raw)
    text = _TAG_RE.sub('', text)
    text = _IMG_RE.sub('', text)
    text = _SOUND_RE.sub('', text)
    text = html.unescape(text)
    text = _ZERO_WIDTH_RE.sub('', text)
    text = _FURIGANA_RE.sub(r'\1', text)
    text = _STRAY_BRACKET_RE.sub('', text)
    text = unicodedata.normalize('NFC', text)
    # `\s` covers the no-break space `&nbsp;` just unescaped into, and CRLF from a pasted field.
    return _WHITESPACE_RE.sub(' ', text).strip()


def fold_kana(text):
    """Katakana to hiragana, everything else as it is: スルリ -> するり, ピカピカ -> ぴかぴか.

    The same word is written in either script — a sound word in katakana on one card and in
    hiragana in the subtitles — and neither side is wrong. ー has no hiragana form and stays.
    """
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text)


# --- WP-N: the report's own markers ✦ / ⚖ / 📖 -------------------------------------------------- #
# The three names, in the order the panel lists them. **ASCII on purpose**: these become Anki tags
# (`Surasura::star`), and a tag has to be typable in Anki's search box — `tag:Surasura::✦` is
# miserable to use and impossible to remember. The glyph belongs in the UI, never in the data.
MARKERS = ("star", "lopsided", "reading")

# The fallback thresholds, matching the shipped `settings.json` `logic.priority_markers` block
# exactly. They exist for a settings dict that has no `logic` section at all (a hand-built one, or a
# profile written before the block existed) — the live values are always read from settings, because
# these marks are a RENDER-time decision: changing a threshold re-renders the report, it does not
# force a re-analysis, and baking the marks into a CSV column would turn it into one (spec WP-N).
MARKER_DEFAULTS = {"priority_threshold": 0.5, "priority_min": 3, "lopsided_threshold": 0.85}

# `Occurrences` on the priority list, `Occurrences (Global)` on the progressive one. The same word,
# the same number, two names — and WP-M means junban now reads both files, so both are honoured
# exactly as `templates/web_app.html` honours them.
TOTAL_COLUMNS = ("Occurrences (Global)", "Occurrences")

_LEADING_INT_RE = re.compile(r'-?\d+')


def marker_thresholds(settings):
    """`logic.priority_markers`, read defensively. Never the hardcoded numbers when settings have them.

    The report computes ✦ / ⚖ live in the browser from this same block, so a user who moves a
    threshold sees the report and the Junban preview agree without re-analysing anything. A missing
    or malformed value falls back per-key rather than wholesale: half a block is still worth half a
    block.
    """
    block = (settings or {}).get("logic")
    block = block.get("priority_markers") if isinstance(block, dict) else None
    out = dict(MARKER_DEFAULTS)
    if isinstance(block, dict):
        for key, fallback in MARKER_DEFAULTS.items():
            value = block.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            out[key] = value
    return out


def normalize_markers(value):
    """The `junban_only_markers` subset, as a stable tuple of known names in `MARKERS` order.

    Unknown names are dropped here and reported separately by `unknown_markers` — silently widening
    a filter to "everything" because of a typo would reorder cards the user asked to leave alone.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    chosen = {str(name).strip().lower() for name in value}
    return tuple(name for name in MARKERS if name in chosen)


def unknown_markers(value):
    """The names in `junban_only_markers` this version does not recognise, for preflight to refuse."""
    if value is None or isinstance(value, str):
        value = [value] if isinstance(value, str) else []
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return sorted({str(name).strip() for name in value
                   if str(name).strip() and str(name).strip().lower() not in MARKERS})


def _count(value):
    """`parseInt(x) || 0`, in Python — the templates' own reading of these columns.

    A blank cell, a missing column and a stray `"1,234"` all have to become a number rather than a
    traceback: this runs over every row of a 3,700-row list on the way to a collection write.
    """
    found = _LEADING_INT_RE.match(str("" if value is None else value).strip())
    return int(found.group()) if found else 0


def row_total(row):
    """The word's total occurrences, whichever of the two column names this file uses."""
    for column in TOTAL_COLUMNS:
        if column in (row or {}):
            return _count(row.get(column))
    return 0


def row_markers(row, thresholds=None):
    """`frozenset` of the markers one CSV row carries — the same rule as `web_app.html:2405-2412`.

    ```js
    isLopsided = pTotal > 0 && (pHigh / pTotal) >= lopsided_threshold
    isPriority = !isLopsided && pTotal >= priority_min
                 && ((pHigh + pLow) / pTotal) >= priority_threshold
    isReading  = data.Modality === 'reading'
    ```

    ⚠ **`star` requires `not lopsided`.** They are mutually exclusive: a word that is overwhelmingly
    from one tier does NOT also get a star, however good its combined ratio looks. Treating them as
    independent flags is wrong in a way that looks entirely plausible — on the live library it would
    star all 39 lopsided words, because every one of them also clears the star ratio.

    A blank `Modality` means "hearable **or** not enough evidence". It is deliberately not a claim
    either way, so it is never asserted as "not a reading word" beyond the absence of the mark.
    """
    row = row or {}
    limits = thresholds if isinstance(thresholds, dict) else MARKER_DEFAULTS
    high = _count(row.get("Count (High)"))
    low = _count(row.get("Count (Low)"))
    total = row_total(row)

    lopsided = total > 0 and (high / total) >= limits.get(
        "lopsided_threshold", MARKER_DEFAULTS["lopsided_threshold"])
    star = (not lopsided
            and total >= limits.get("priority_min", MARKER_DEFAULTS["priority_min"])
            and total > 0
            and ((high + low) / total) >= limits.get(
                "priority_threshold", MARKER_DEFAULTS["priority_threshold"]))
    reading = str(row.get("Modality") or "").strip().lower() == "reading"

    marks = set()
    if star:
        marks.add("star")
    if lopsided:
        marks.add("lopsided")
    if reading:
        marks.add("reading")
    return frozenset(marks)


# --- the index -------------------------------------------------------------------------------- #
# One pass over one list. `rank_of` is what the planner needs, `contexts_of` what WP-L's sentence
# needs, `marks_of` what WP-N's preview column and marker tags need — all three off the same read,
# because the file is 14 MB on a real library and reading it twice to answer two questions about the
# same row is work for no one. `journey_of` is each key's `(file, score, total)` — the numbers the
# journey orders by — so a word below the list's cut-off can be placed among the listed ones
# (Junban_Backlog_Spec §11.1).
Index = namedtuple("Index", "rank_of contexts_of marks_of journey_of")


def load_rank_index(csv_path):
    """`{normalized_word: rank}` — `build_index`'s first third, and the only one the planner needs."""
    return build_index(csv_path).rank_of


def load_index(csv_path, want_contexts=False):
    """`(rank_of, contexts_of)` — the two-value view WP-L's callers already read."""
    return tuple(build_index(csv_path, want_contexts=want_contexts))[:2]


def build_index(csv_path, want_contexts=False, thresholds=None, only=None, language=None):
    """`Index(rank_of, contexts_of, marks_of, journey_of)` from an ordered Surasura list.

    **Either list** (WP-M): `results/priority_learning_list.csv`, whose row order is raw leverage,
    or `results/progressive_learning_list.csv`, whose row order is file order then within-file score
    — literally "in the order you will meet it". The reader is the same for both because the two
    files name a word the same way (`Word` + `Orth`, pinned by
    `tests/test_orth_column.py::test_both_output_lists_name_a_word_the_same_way`); the only
    difference is that a word recurs across files in the progressive list, and there **first
    occurrence wins**, which the "never overwrite a lower rank" rule below already gives for free.

    **The row index IS the rank.** The file is already in learn order — row 0 is rank 0 — so no
    column is consulted for it, and a row that yields no usable key still consumes its rank rather
    than shifting every row beneath it.

    Per row, in this precedence, and **never overwriting a lower rank**: `Orth` (the spelling
    anki_miner writes onto the card), then `Word` (the lemma). A key reached from several rows keeps
    the best rank it ever had; the same rank reached by several keys is the point — that is what
    clusters a word's cards together (spec §7).

    Read as `utf-8-sig`: the CSV carries a BOM, and without this the first column name comes back as
    `\\ufeffWord` and every lookup by name misses. Columns are read by NAME, never by position —
    `Orth` is second today and was absent entirely before D4, so older result folders load fine and
    simply match on the lemma alone.

    `contexts_of` maps the same keys to that row's `Context 1..3` — the example sentences WP-L's
    optional touch-up offers the card — and is built **only** when `want_contexts` is on. Those
    three columns are the bulk of a real priority list, so a run with the sentence feature off must
    not pay to hold them. An older results folder that predates the columns simply yields no
    contexts, which is not an error: there is nothing to add, and nothing to add is fine.

    `marks_of` maps the same keys to that row's ✦ / ⚖ / 📖 (WP-N) and is built for **every** row,
    filter or no filter: the preview's marker column should show the user why a word was left out,
    not go blank on the words the filter removed.

    `only`, when non-empty, is the `junban_only_markers` subset. A row carrying none of the wanted
    markers simply **contributes no key**, so its word is unmatched — which already means "keeps its
    existing relative order, at the back" (spec §7). That is the whole implementation of the filter:
    no new ordering concept, no stranded cards, and the contiguous block from `min(due)` is
    untouched.

    Returns empty dicts for a missing, empty or unreadable file. Whether the list is present at all
    is preflight's question (spec §18.0/WP-G), not this function's, and raising here would take the
    panel down over a first run that has never been analysed.

    **The spellings the content used (L3, Junban_Backlog_Spec §5.1).** A row's `Forms` — every
    other way the word was written in the library (`|`-joined) — become keys too, but only AFTER
    every `Orth` and `Word`: a spelling that is some other row's own word belongs to that row
    (生き the noun is not 生きる's 生き). With `language="ja"` two more rules apply:

      * **one-character keys are only a row's own word.** 49 one-character `Orth` keys stood in the
        live index — surnames whose commonest spelling is one kanji (タニ -> 谷, アズマ -> 東) and
        interjections (おー -> お) — and a real 谷 card matched the surname. A one-character lemma
        (with single characters switched on) is still its own key. Chinese keeps them all: most of
        its commonest words are one character.
      * **the kana fold (L4).** Every kana-only key is also filed under its hiragana form, so スルリ
        on a card finds するり in the list; `lookup` folds the card's side. Added last, so it never
        displaces a word that is really spelled that way.
    """
    index = {}
    contexts = {}
    marks_of = {}
    journey_of = {}
    empty = Index(index, contexts, marks_of, journey_of)
    if not csv_path or not os.path.isfile(csv_path):
        return empty

    wanted_marks = set(normalize_markers(only))
    limits = thresholds if isinstance(thresholds, dict) else MARKER_DEFAULTS
    japanese = language == "ja"
    later = []                  # (rank, [Forms keys], contexts, marks, ranked, numbers) — the L3 pass

    def _add(key, rank, row_contexts, marks, ranked, numbers):
        marks_of.setdefault(key, marks)
        if ranked and key not in index:
            index[key] = rank
            journey_of[key] = numbers
            if want_contexts and row_contexts:
                contexts[key] = row_contexts

    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
            for rank, row in enumerate(csv.DictReader(handle)):
                row_contexts = None
                if want_contexts:
                    # Read by NAME and in order, best first. A blank cell is skipped rather than
                    # offered as an empty sentence.
                    row_contexts = [str(row.get(column) or "").strip()
                                    for column in CONTEXT_COLUMNS]
                    row_contexts = [text for text in row_contexts if text]
                marks = row_markers(row, limits)
                ranked = not wanted_marks or bool(marks & wanted_marks)
                # The journey's own sort key for this row: its file (`Sequence`, the progressive
                # list only — 0 on the priority list), its `Score`, its total occurrences.
                numbers = (_count(row.get("Sequence")), _count(row.get("Score")), row_total(row))
                lemma = normalize_word(row.get("Word"))
                for column in ("Orth", "Word"):
                    key = normalize_word(row.get(column))
                    if not key or (japanese and len(key) == 1 and key != lemma):
                        continue
                    _add(key, rank, row_contexts, marks, ranked, numbers)
                forms = [normalize_word(form) for form in str(row.get("Forms") or "").split("|")]
                forms = [form for form in forms if form and not (japanese and len(form) == 1)]
                if forms:
                    later.append((rank, forms, row_contexts, marks, ranked, numbers))
    except (OSError, UnicodeError, csv.Error):
        # A truncated or unreadable list means "no matches", which the planner already handles by
        # leaving every card where it is. It must never mean "crash on the way to a write".
        return Index({}, {}, {}, {})

    for rank, forms, row_contexts, marks, ranked, numbers in later:
        for key in forms:
            if key not in marks_of:     # a word some row IS keeps that row, marks included
                _add(key, rank, row_contexts, marks, ranked, numbers)

    if japanese:
        for key in [key for key in marks_of if _KANA_ONLY_RE.match(key)]:
            folded = fold_kana(key)
            if folded != key and folded not in marks_of:
                marks_of[folded] = marks_of[key]
                if key in index:
                    index[folded] = index[key]
                    journey_of[folded] = journey_of[key]
                    if key in contexts:
                        contexts[folded] = contexts[key]

    return Index(index, contexts, marks_of, journey_of)


def lookup(word, rank_of, language=None):
    """The list key a card's word reaches — L1 to L4 of the match ladder — or `""` for none.

    `Orth`, `Word` and `Forms` keys all live in `rank_of`, so one exact test covers the first
    three; for Japanese, a kana-only word that misses is tried again folded to hiragana, the other
    half of `build_index`'s fold.
    """
    if not isinstance(word, str) or not word or not rank_of:
        return ""
    if word in rank_of:
        return word
    if language == "ja" and _KANA_ONLY_RE.match(word):
        folded = fold_kana(word)
        if folded in rank_of:
            return folded
    return ""


def library_floor(path):
    """The list's own cut-off — the occurrences a word needs to be on it (the run's `min_count`) —
    from the library map, or None when there is no map to read it from. What "frequent enough" means
    for a phrase the list cannot hold (Junban's "List first", 2026-09-23)."""
    try:
        with open(path, encoding="utf-8") as handle:
            floor = (json.load(handle).get("settings") or {}).get("min_count")
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    return floor if isinstance(floor, (int, float)) and not isinstance(floor, bool) else None


def load_library(path, language=None):
    """`{key: (file, score, total)}` for every word in the library — below the list's cut-off
    included — from `results/library_frequency.json`, which every run writes since ENGINE_REVISION
    11 (Junban_Backlog_Spec §11.1). `file` is the word's first file in study order and `score` its
    weighted count: the journey's own sort key, so a mined word the list cut off can still be placed
    exactly where the journey would meet it.

    Keyed like `build_index`: by the word (UniDic's lemma) and by the spelling the content uses —
    the one anki_miner writes onto the card — with the same Japanese rules (a one-character key only
    for a one-character word; every kana-only key also under its hiragana form). A key two of a
    word's readings share keeps the higher-scoring one: the sense the library leans on.

    `{}` for a missing or unreadable file, or one written before revision 11 (its entries stop at
    the four counts): there is then no journey to place by, and the caller says so.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            words = json.load(handle).get("words") or {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}
    if not isinstance(words, dict):
        return {}
    japanese = language == "ja"
    out = {}
    # The names are the analyzer's own lemma and spelling, never a card field, so NFC is all the
    # cleaning they need — `normalize_word` on every one of ~25k entries was half a preview.
    nfc = unicodedata.normalize

    def number(value):          # the map holds plain ints; anything else is read the careful way
        return value if type(value) is int else _count(value)

    for key, entry in words.items():
        if not isinstance(key, str) or not isinstance(entry, list) or len(entry) < 7:
            continue
        lemma = nfc("NFC", key.split("|")[0]).strip()
        numbers = (number(entry[4]), number(entry[5]), number(entry[0]))
        spelling = nfc("NFC", entry[6]).strip() if isinstance(entry[6], str) else ""
        for name in (spelling, lemma):
            if not name or (japanese and len(name) == 1 and name != lemma):
                continue
            held = out.get(name)
            if held is None or numbers[1] > held[1]:
                out[name] = numbers
    if japanese:
        for name in [name for name in out if _KANA_ONLY_RE.match(name)]:
            folded = fold_kana(name)
            if folded != name and folded not in out:
                out[folded] = out[name]
    return out


# --- the card's own sentence (Junban_Backlog_Spec §5.4: i+1 and multi-unknown) ------------------ #
_BOLD_OPEN, _BOLD_CLOSE = "\x01", "\x02"
_BOLD_RE = re.compile(r'<b\b[^>]*>(.*?)</b>', re.IGNORECASE | re.DOTALL)


def sentence_span(raw, word):
    """`(text, start, end)`: a card's sentence field as plain text, and where the card's word sits
    in it — the `<b>` span anki_miner marks (268 of 376 real cards carry one; it holds the word as
    conjugated: <b>多すぎます</b>), else the word's first occurrence. `None` when the field is empty
    or the word cannot be found, rather than a guess."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    marked = _BOLD_RE.sub(lambda m: _BOLD_OPEN + m.group(1) + _BOLD_CLOSE, raw, count=1)
    text = normalize_word(marked)
    if not text:
        return None
    start = text.find(_BOLD_OPEN)
    if start >= 0:
        end = text.find(_BOLD_CLOSE, start)
        plain = text.replace(_BOLD_OPEN, "").replace(_BOLD_CLOSE, "")
        if end > start + 1:
            return plain, start, end - 1
        text = plain
    text = text.replace(_BOLD_OPEN, "").replace(_BOLD_CLOSE, "")
    at = text.find(word) if isinstance(word, str) and word else -1
    return (text, at, at + len(word)) if at >= 0 else None


def unknowns_beside(word, raw, tokenize, unknown):
    """How many words of the card's sentence the learner does not know yet OUTSIDE the card's own
    word: 0 makes the card i+1 — the one new thing in its sentence is the card (a phrase made of
    known words counts, D1). `None` when there is no sentence to read or no word to find in it.

    `tokenize(text)` yields the analyzer's `(lemma, reading, surface, orth)`; `unknown(token)` is
    the caller's verdict on one token — its known words, ignore lists and skips — so this stays
    free of them. Tokens are located by their surfaces in order, since the tokenizer drops
    punctuation.
    """
    found = sentence_span(raw, word)
    if found is None:
        return None
    text, start, end = found
    count, at = 0, 0
    for token in tokenize(text):
        surface = token[2]
        pos = text.find(surface, at) if surface else -1
        if pos < 0:
            continue
        at = pos + len(surface)
        if pos < end and at > start:
            continue                    # inside the card's own word
        if unknown(token):
            count += 1
    return count


# --- Check matches (Junban_Backlog_Spec §16): the same word, spelled another way ------------------ #
# A suggestion, never a match: the user ticks it or it moves nothing (§16.1 — the user reversed I6).
Suggestion = namedtuple("Suggestion", "key via evidence reading")
_KANJI_RE = re.compile('[㐀-鿿豈-﫿]')


def suggest(word, raw_sentence, tokenize, rank_of, language):
    """The list word a card's word may be, when the exact keys (L1–L4) found none — or None.

    **L6, the sentence bridge.** The card's word is found in its own sentence (the `<b>` span, else
    its first occurrence) and tokenized there, exactly as the library was: the token that IS the
    card's word (its orthBase or surface equals it) gives its dictionary spelling and UniDic lemma,
    and either may be on the list — 見とれる -> 見惚れる, なり代わる -> 成り代わる. With no sentence to
    read it in, the word is tokenized alone, but only when it holds a kanji: a kana word alone is
    read wrong too often (まく -> 膜, §8 gotcha 2).

    **L7, affixes.** 同行する / 過熱する -> the noun on the list; きゅっと -> きゅっ (Yomitan cards;
    real と-adverbs — ずっと, やっと — are single tokens and match exactly first).

    Japanese only; nothing for a word the list already has. `tokenize(text)` yields the analyzer's
    `(lemma, reading, surface, orth)`. `reading` is the matched word's, in hiragana, for the user to
    check at a glance. Deliberately absent (§4.4, §16.1): reading-only matches, containment either
    way, and a compound's parts (伊勢海老 is not 伊勢).
    """
    if language != "ja" or not tokenize or not isinstance(word, str) or not word or not rank_of:
        return None
    if lookup(word, rank_of, language):
        return None
    located = _in_sentence(raw_sentence, word, tokenize)
    token = located[3] if located else None
    if token is None and _KANJI_RE.search(word):
        alone = list(tokenize(word))
        if len(alone) == 1 and word in (alone[0][3], alone[0][2]):
            token = alone[0]
    if token is not None:
        for name in (token[3], token[0]):      # the dictionary spelling, then the lemma
            key = lookup(name, rank_of, language)
            if key and key != word:
                return Suggestion(key, "L6", "same word, other spelling", fold_kana(token[1] or ""))
    for ending, evidence in (("する", "+ する"), ("と", "+ と")):
        stem = word[:-len(ending)]
        if word.endswith(ending) and stem:
            key = lookup(stem, rank_of, language)
            if key:
                alone = list(tokenize(stem))
                reading = fold_kana(alone[0][1] or "") if len(alone) == 1 else ""
                return Suggestion(key, "L7", evidence, reading)
    return None


def _in_sentence(raw, word, tokenize):
    """`(text, start, end, token)` — the token of the card's sentence that IS the card's word (its
    orthBase or surface equals it), inside the `<b>` span when there is one, else anywhere: a
    sentence without bold may still say なり代わろう for なり代わる. None when no token is the word."""
    found = sentence_span(raw, word)
    if found is not None:
        text, start, end = found
    else:
        text = normalize_word(raw) if isinstance(raw, str) else ""
        start, end = 0, len(text)
    if not text or not tokenize:
        return None
    at = 0
    for candidate in tokenize(text):
        surface = candidate[2]
        pos = text.find(surface, at) if surface else -1
        if pos < 0:
            continue
        at = pos + len(surface)
        if pos < end and at > start and word in (candidate[3], surface):
            return text, pos, at, candidate
    return None


def sentence_excerpt(raw, word, width=48, tokenize=None):
    """The card's sentence as one line, its word in 【】 — what the user reads to judge a suggestion:
    the `<b>` span or the word as written, else (with `tokenize`) the word as conjugated there. Cut to
    about `width` characters around the word; "" when there is no sentence to show."""
    found = sentence_span(raw, word)
    if found is None and tokenize:
        located = _in_sentence(raw, word, tokenize)
        found = located[:3] if located else None
    if found is None:
        text = normalize_word(raw) if isinstance(raw, str) else ""
        return text if len(text) <= width else text[:width - 1] + "…"
    text, start, end = found
    marked = text[:start] + "【" + text[start:end] + "】" + text[end:]
    if len(marked) <= width:
        return marked
    left = max(0, start - (width - (end - start) - 2) // 2)
    piece = marked[left:left + width - 2]
    return ("…" if left else "") + piece + ("…" if left + width - 2 < len(marked) else "")


# --- a word written with its tail (Patterns_Quality_Spec §7) ------------------------------------ #
# A card writes some words with what follows them attached — 同行する, 斬新な, 一気に — where the list
# has 同行, 斬新, 一気. Read on its own such a word is two tokens, and the second is the tail. Known by
# its LEMMA, because the analyzer's tokens carry no part of speech: 為る is する, だ the copula's な / に,
# に the particle — the same three tails パターン's lookup drops (`modules/junban/patterns.py`).
ATTACHED_TAILS = frozenset(("為る", "だ", "に"))


def is_attached_tail(lemma):
    """True when a token with this lemma, second in a word read on its own, is written ONTO the word
    rather than being a word of its own: する (為る), the copula's な / に (だ), the particle に."""
    return lemma in ATTACHED_TAILS


# --- phrases (L9, Junban_Backlog_Spec §11.1 item 2) --------------------------------------------- #
# Half of a real backlog is phrases and compounds — 気がつく, 俺たち, 騎士団. anki_miner and the
# analyzer produce the SAME tokens; anki_miner then glues them into one card word when the result is
# a headword in the user's dictionary, and Surasura counts the parts. So a phrase card is looked up
# as the run of words it is made of, in the library's own cached tokens: measured on the real
# library, 207 of 221 phrase cards occur that way, and one pass over 1,987 files took 3.6 s — fine
# in the background, too slow to repeat, hence the cache below.
def phrase_lemmas(words, tokenize):
    """`{word: (lemma, ...)}` for the card words `tokenize` splits into two or more words.

    `tokenize(text)` yields the analyzer's `(lemma, reading, surface, orth)` tuples — the same
    tokenizer a run uses, so a phrase's lemmas are the ones the library's tokens carry.
    """
    out = {}
    for word in words:
        if not isinstance(word, str) or not word:
            continue
        lemmas = tuple(token[0] for token in tokenize(word))
        if len(lemmas) >= 2:
            out[word] = lemmas
    return out


def find_phrases(phrases, files, file_tokens, progress=None):
    """`{word: (file, score, total)}` for the phrases met in the library — the journey's own key,
    from one pass over `files` (`[(path, weight)]` in study order) with every phrase checked at once.

    `file_tokens(path)` returns a file's cached sentences `[(text, [[lemma, ...], ...])]`, as the
    token store keeps them. `file` is 1-based like the progressive list's `Sequence`; `score` adds the
    file's weight per occurrence, as the analyzer's does. A phrase never met is simply absent.
    """
    by_first = {}
    for word, lemmas in phrases.items():
        by_first.setdefault(lemmas[0], []).append((word, lemmas))
    found = {}
    total_files = len(files)
    for number, (path, weight) in enumerate(files, 1):
        for _text, tokens in file_tokens(path):
            lemmas = [token[0] for token in tokens]
            for start, lemma in enumerate(lemmas):
                for word, sequence in by_first.get(lemma, ()):
                    if tuple(lemmas[start:start + len(sequence)]) == sequence:
                        entry = found.setdefault(word, [number, 0, 0])
                        entry[1] += weight
                        entry[2] += 1
        if progress and (number % 100 == 0 or number == total_files):
            progress(number, total_files)
    return {word: tuple(entry) for word, entry in found.items()}


def _fingerprint(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return [stat.st_mtime, stat.st_size]


def phrase_places(words, language, cache_path, library_path, progress=None):
    """`{word: (file, score, total)}` for the multi-token card `words` the library holds — L9.

    Cached in `cache_path` against the library map's fingerprint: every Generate rewrites that map,
    and the files, their order and their weights can only change through one. So a preview pays for
    the pass once per Generate, and only when a phrase it has not seen turns up. Japanese only (the
    tokenizer is fugashi's, imported here and nowhere at import time — spec I4); `{}` for Chinese,
    for no map, and whenever the store or the tokenizer cannot be had — a phrase card then simply
    stays where it is.
    """
    if language != "ja":
        return {}
    library = _fingerprint(library_path)
    if library is None:
        return {}
    wanted = sorted({word for word in words if isinstance(word, str) and word})
    cache = {}
    try:
        with open(cache_path, encoding="utf-8") as handle:
            cache = json.load(handle)
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict) or cache.get("library") != library:
        cache = {"library": library, "checked": [], "places": {}}
    checked = set(cache.get("checked") or [])
    places = cache.get("places") or {}
    fresh = [word for word in wanted if word not in checked]
    if fresh:
        try:
            from app import analyzer, token_index
            analyzer.SANITIZE_JA = True
            tokenizer = analyzer.JapaneseTokenizer()
            phrases = phrase_lemmas(fresh, tokenizer.tokenize)
            if phrases:
                files = [(path, weight) for path, _label, weight, _type
                         in analyzer.resolve_found_files(language, verbose=False)]
                store = token_index.open_store(language)
                try:
                    for word, numbers in find_phrases(phrases, files, store.file_tokens,
                                                      progress=progress).items():
                        places[word] = list(numbers)
                finally:
                    store.close()
        except Exception:
            return {word: tuple(places[word]) for word in wanted if word in places}
        checked.update(fresh)
        cache = {"library": library, "checked": sorted(checked), "places": places}
        tmp = cache_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(cache, handle, ensure_ascii=False)
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return {word: tuple(places[word]) for word in wanted if word in places}


# --- reading the word off a note ---------------------------------------------------------------- #
def resolve_word_field(model_name, field_names, overrides):
    """Which field of `model_name` holds the target word. `field_names` is in Anki's own field order.

    1. an explicit override for this note type, if it names a field the type actually has;
    2. otherwise **field 0**.

    Field 0 is an **anki_miner** invariant, not an Anki one — its preflight refuses any other layout
    because Anki dedups on field 0 — so it is the right default and the wrong assumption. Verified on
    the live collection: `Lapis` and `Kiku` put `Expression` at 0 and `Senren` puts `word` at 0, but
    `Migaku Japanese` has `Sentence` at 0 while its word lives in `Target Word`. Ordering a backlog
    by whole sentences would match nothing and look like the feature is broken.

    A stale or misspelled override falls back to field 0 rather than resolving to a field that does
    not exist. That is not silent: the panel shows the resolved field per note type before any write,
    so an override that is being ignored reads as the wrong field name on screen.
    """
    names = [name for name in (field_names or []) if isinstance(name, str)]
    if not names:
        return ""

    wanted = (overrides or {}).get(model_name)
    if isinstance(wanted, str) and wanted.strip():
        wanted = wanted.strip()
        if wanted in names:
            return wanted
        # Anki's own field lookup is case-insensitive in practice, and a user typing an override by
        # hand should not lose to "expression" vs "Expression".
        lowered = wanted.lower()
        for name in names:
            if name.lower() == lowered:
                return name

    return names[0]


def target_word(note, overrides):
    """The normalised target word of one `notesInfo` note, or `""` when there isn't one.

    `""` is an ordinary answer, not a failure: an image-only field, an empty note, a note type with
    no fields at all. The planner treats such a card as unmatched and leaves its position alone,
    which is exactly right — better a card that does not move than a card moved by a guess.

    Everything is read with `.get()`: `cardsInfo`/`notesInfo` payloads are version-dependent, and a
    missing key here must not become a traceback in front of a collection write.
    """
    if not isinstance(note, dict):
        return ""

    fields = note.get("fields")
    if not isinstance(fields, dict) or not fields:
        return ""

    # Anki's field ORDER is the `order` value, not the dict's insertion order — JSON round-trips have
    # no obligation to preserve it, and "field 0" is meaningless if we trust the wrong one. An entry
    # missing its order sorts last rather than pretending to be field 0.
    def _order(name):
        value = fields.get(name)
        if isinstance(value, dict) and isinstance(value.get("order"), int):
            return value["order"]
        return len(fields)

    names = sorted(fields.keys(), key=lambda name: (_order(name), name))
    chosen = resolve_word_field(note.get("modelName", ""), names, overrides)
    if not chosen:
        return ""

    value = fields.get(chosen)
    if isinstance(value, dict):
        value = value.get("value")
    return normalize_word(value)
