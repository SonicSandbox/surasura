"""Surasura Corpus — up to 8 of the best sentences for EVERY word in the library, as a Yomitan
dictionary (docs/agent instructions/Sentence_Dictionary_Spec.md).

Its own run, launched by Settings → Data & System → Export Sentence Dictionary as a subprocess
(`app_entry.py sentence_corpus`). It needs no analysis: the token store already holds every library
file's sentences, tokenized, and keeps itself current — so this is one pass over that cache, and the
report, the CSVs and Generate are untouched (no ENGINE_REVISION bump).

Built for laptops (spec I7): only one file's sentences are ever in memory, each word keeps at most 8
sentences plus 8 spares, and the term banks go into the zip as they fill. Holding the library in
memory instead measured 2.2 GB on a 1,924-file library; streaming it, ~230 MB.
"""

import os
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import re
import zipfile
from datetime import datetime

SENTENCES_PER_WORD = 8
# Variety: at most this many sentences from any one file, so the eight come from different episodes —
# unless there aren't enough other files, when the best of the rest fill the remaining places.
PER_FILE = 2
# The good-length window is the user's own range (Settings → logic.context) widened by this much on
# each side — their choice of "a bit more leeway" for a dictionary (D2).
LENGTH_LEEWAY = 5
PROGRESS_EVERY = 100
TERMS_PER_BANK = 10000       # what the installed dictionaries use; Yomitan reads any number of banks
MAX_SPELLINGS = 3

_MARKERS = "①②③④⑤⑥⑦⑧"
_PRIVATE_USE = re.compile("[-]")    # invisible glyphs some subtitle tools leave behind
_KANJI = re.compile("[㐀-䶿一-鿿々]")
_KANA_ONLY = re.compile("^[ぁ-ゟ゠-ヿ]+$")

# A verb's potential form is its own UniDic entry under the SAME lemma — 辿り着ける is filed as
# 辿り着く — so it shows up among a word's spellings. Its dictionary reading is the lemma's with the
# final u-row kana moved to the e-row plus ル (タドリツク -> タドリツケル). Yomitan de-inflects it back
# to 辿り着く on its own, so it must not become a second entry for the same sentences.
_U_TO_E = dict(zip("ウクグスツヌブムル", "エケゲセテネベメレ"))

# The divider between sentences is an INLINE style on each sentence (all but the last), so it shows
# wherever the entry is rendered — a stylesheet only applies inside Yomitan's own popup. A faint grey
# reads on light and dark themes alike.
_DIVIDER = {"borderColor": "rgba(128, 128, 128, 0.35)", "borderStyle": "solid", "borderWidth": "0 0 1px 0",
            "paddingBottom": "0.3em", "marginBottom": "0.3em"}
_SOURCE_STYLE = {"fontSize": "0.8em", "color": "var(--text-color-light3, #888)"}

# Yomitan-only touches on top (the popup applies a dictionary's styles.css; nothing else does): the
# number muted, the word in the accent colour, the source on a line of its own.
CORPUS_CSS = (
    '[data-sc-surasura="sentence"]::first-letter{color:var(--text-color-light3,#888)}\n'
    '[data-sc-surasura="target"]{color:var(--accent-color,#bb86fc)}\n'
    '[data-sc-surasura="source"]{display:block}\n'
)

# The short name shown when the user asks for sources: file names carry a lot that says nothing about
# where a sentence is from — fansub release tags, YouTube ids, CRCs, resolution and codec tags,
# subtitle language suffixes, and the timestamps a Graduate / Demote name clash appends.
_LEADING_TAGS = re.compile(r"^(?:\[[^\]]*\][\s_.-]*)+")
_RENAME_STAMPS = re.compile(r"(?:_\d{14})+$")
_TRAILING_BRACKETS = re.compile(r"[\s_.-]*\[[^\]]*\]$")
_TRAILING_PARENS = re.compile(r"[\s_.-]*\(([^)]*)\)$")
# Not \b: fansub names join tags with underscores ('1920x1080_Blu-ray_FLAC'), which \b treats as part
# of the word.
_TECHNICAL = re.compile(r"(?i)(?<![a-z0-9])(?:\d{3,4}p|\d{3,4}x\d{3,4}|x26[45]|hevc|avc|aac|flac|opus|"
                        r"web-?dl|web-?rip|bd-?rip|blu-?ray|\d+bit)(?![a-z0-9])")
# A subtitle language (with the one-digit track number an extractor adds: '.3.und') or a release tag.
_TRAILING_TOKEN = re.compile(r"(?i)(?:(?:\.\d)?[._-](?:ja|jp|jpn|jap|und|zh|chs|cht|zho|chi)|"
                             r"[._-](?:webrip|web-dl|netflix|nf|amzn|1080p|720p|x264|x265))$")
# 'Series.S01E01.Episode title' keeps 'Series.S01E01': the episode's own title is what a length cap
# would otherwise keep instead of its number.
_EPISODE_TITLE = re.compile(r"(?i)^(.+?[._ -]S\d{1,2}E\d{1,3})[._ -].+$")
LABEL_MAX = 30


def dictionary_title(language):
    return f"Surasura Corpus ({language})"


def length_range(settings):
    """(lo, hi, own_lo, own_hi) in characters: the user's own `logic.context` range — read from THEIR
    settings on every export, since they may change it — widened by LENGTH_LEEWAY on each side. Never
    below 1, never past the hard cap `max_chars` (longer sentences are never examples anywhere)."""
    context = (settings.get("logic") or {}).get("context") or {}
    own_lo = int(context.get("min_chars", 10))
    own_hi = int(context.get("preferred_max_chars", 50))
    cap = int(context.get("max_chars", 150))
    return max(1, own_lo - LENGTH_LEEWAY), min(cap, own_hi + LENGTH_LEEWAY), own_lo, own_hi


class _Best:
    """The best sentences for one word, kept as it streams past: at most SENTENCES_PER_WORD, at most
    PER_FILE from any one file — plus, while the list isn't full yet, the best of the ones that cap
    pushed out, so a word met in only one or two files still gets its eight.

    A candidate is (key, text, file_index, surface); a lower key is better. Both lists stay sorted, so
    the worst is always last. Adding an element and dropping the worst of whatever it overfills is the
    standard way to keep the best set under a per-group cap, so the order candidates arrive in never
    changes the result."""
    __slots__ = ("kept", "spare")

    def __init__(self):
        self.kept = []
        self.spare = []

    def offer(self, cand):
        kept = self.kept
        full = len(kept) >= SENTENCES_PER_WORD
        if full and cand[0] >= kept[-1][0]:
            return                      # no better than the worst of a full list — the common case
        text, fidx = cand[1], cand[2]
        if any(c[1] == text for c in kept) or any(c[1] == text for c in self.spare):
            return                      # the same line again (a repeated song, a re-used subtitle)
        same = [c for c in kept if c[2] == fidx]
        if len(same) >= PER_FILE:
            worst = same[-1]
            if cand[0] < worst[0]:
                kept.remove(worst)
                self._insert(kept, cand)
                self._to_spare(worst)
            else:
                self._to_spare(cand)
            return
        self._insert(kept, cand)
        if len(kept) > SENTENCES_PER_WORD:
            kept.pop()
        if len(kept) >= SENTENCES_PER_WORD:
            self.spare = []             # a full list never needs one

    def _to_spare(self, cand):
        if len(self.kept) >= SENTENCES_PER_WORD:
            return
        self._insert(self.spare, cand)
        del self.spare[SENTENCES_PER_WORD:]

    @staticmethod
    def _insert(lst, cand):
        # At most nine elements: a linear walk beats bisect (whose `key=` needs Python 3.10).
        i = len(lst)
        while i and lst[i - 1][0] > cand[0]:
            i -= 1
        lst.insert(i, cand)

    def result(self):
        best = list(self.kept)
        best.extend(self.spare[:SENTENCES_PER_WORD - len(best)])
        best.sort(key=lambda c: c[0])
        return best


class _Word:
    __slots__ = ("best", "orths", "count", "listed")

    def __init__(self, listed):
        self.best = _Best() if listed else None
        self.orths = {}
        self.count = 0
        self.listed = listed        # False: counted (so sentences know it) but never an entry


def collect(files, file_tokens, language, known, window, progress=None, wanted=None, young=None,
            phrases=None):
    """The streaming pass. `files` are the library's paths in library order; `file_tokens(path)` returns
    that file's cached sentences [(text, [[lemma, reading, surface, orth], ...]), ...] — called once per
    file, and nothing of a file outlives its turn except the few sentences a word keeps (I7).

    `known` = (known_tuples, known_lemmas, ignore), the analyzer's own sets; `window` = length_range().
    `wanted`, a set of (lemma, reading), keeps sentences for those words only — the same ranking, a
    fraction of the memory (`best_for`). `young`, a set of keys the learner is still learning, puts a
    sentence with more of them first among equally easy ones of a good length (the user, 2026-09-24:
    "even better if the words are NOT mature"); without it the order is as it always was. `phrases`,
    {name: (lemma, …)}, finds several-word targets (当事者, 気を取り直す) as that run of lemmas, however
    inflected, ranked the same with their own words not counted against them; they come back under
    their name. Returns {(lemma, reading) or name: _Word}."""
    from app.analyzer import has_target_language

    known_tuples, known_lemmas, ignore = known
    lo, hi, own_lo, own_hi = window
    words = {}
    lang_ok = {}                # memo: a string -> has target-language characters
    known_memo = {}             # memo: (lemma, reading) -> known / ignored
    starts = {}                 # a phrase's first lemma -> [(name, lemmas)]
    for name, lemmas in (phrases or {}).items():
        if len(lemmas) > 1:
            starts.setdefault(lemmas[0], []).append((name, tuple(lemmas)))

    def _lang(text):
        ok = lang_ok.get(text)
        if ok is None:
            ok = lang_ok[text] = has_target_language(text, language)
        return ok

    total = len(files)
    for fidx, path in enumerate(files):
        for sidx, (text, tokens) in enumerate(file_tokens(path)):
            present = {}        # (lemma, reading) -> the surface it has in THIS sentence
            unknown = 0
            for lemma, reading, surface, orth in tokens:
                if not (_lang(lemma) or _lang(surface)):
                    continue    # markup, numbers, ASCII — never a word (the analyzer skips them too)
                key = (lemma, reading)
                word = words.get(key)
                if word is None:
                    # One-character kana in Japanese are particles and endings — never an entry, but
                    # still words a sentence can be hard for. Chinese keeps single characters, as the
                    # analyzer does (most of its common words are one character).
                    listed = not (language == "ja" and len(lemma) == 1 and _KANA_ONLY.match(lemma)) \
                        and (wanted is None or key in wanted)
                    word = words[key] = _Word(listed)
                word.count += 1
                word.orths[orth] = word.orths.get(orth, 0) + 1
                if key not in present:
                    present[key] = surface
                    is_known = known_memo.get(key)
                    if is_known is None:
                        is_known = known_memo[key] = (lemma in ignore or lemma in known_lemmas
                                                      or key in known_tuples)
                    if not is_known:
                        unknown += 1

            size = len(text)
            if not (lo <= size <= hi) or not present:
                continue
            margin = 0 if own_lo <= size <= own_hi else 1
            fresh = sum(1 for key in present if key in young) if young else 0
            for key, surface in present.items():
                word = words[key]
                if not word.listed:
                    continue
                others = unknown - (0 if known_memo[key] else 1)
                # Its own word never counts toward the young words it practises.
                recent = fresh - (1 if young and key in young else 0)
                word.best.offer(((others, margin, -recent, fidx, sidx), text, fidx, surface))
            if starts:
                for name, span in _phrases_in(tokens, starts):
                    inside = {(t[0], t[1]) for t in span}
                    others = unknown - sum(1 for k in inside if known_memo.get(k) is False)
                    recent = fresh - sum(1 for k in inside if young and k in young)
                    word = words.get(name)
                    if word is None:
                        word = words[name] = _Word(True)
                    word.best.offer(((others, margin, -recent, fidx, sidx), text, fidx,
                                     "".join(t[2] for t in span)))

        if progress and ((fidx + 1) % PROGRESS_EVERY == 0 or fidx + 1 == total):
            progress(f"Reading your library: {fidx + 1:,} / {total:,} files…")
    return words


def _phrases_in(tokens, starts):
    """Each phrase of `starts` found in a sentence's tokens, once: (name, its tokens there)."""
    found = set()
    for i, token in enumerate(tokens):
        for name, lemmas in starts.get(token[0], ()):
            if name not in found and tuple(t[0] for t in tokens[i:i + len(lemmas)]) == lemmas:
                found.add(name)
                yield name, tokens[i:i + len(lemmas)]


# --------------------------------------------------------------------------------------------- #
# The dictionary
# --------------------------------------------------------------------------------------------- #
def _clean(text):
    """A sentence or label as it can be shown: Yomitan keeps line breaks, and private-use glyphs are
    invisible boxes."""
    return _PRIVATE_USE.sub("", str(text).replace("\r", " ").replace("\n", " ")).strip()


def _short_label(stem):
    """'[NanakoRaws] Seihantai na Kimi to Boku - 09 (WEBRip 1080p AAC)' -> 'Seihantai na Kimi to Boku
    - 09'. Long names lose their MIDDLE, not their end, so an episode number survives
    ('The Irregular at M…hool.S01E25'). Nothing left -> the original name, cut the same way."""
    label = _LEADING_TAGS.sub("", _RENAME_STAMPS.sub("", stem))
    while True:
        before = label
        label = _TRAILING_BRACKETS.sub("", label)
        paren = _TRAILING_PARENS.search(label)
        if paren and _TECHNICAL.search(paren.group(1)):
            label = label[:paren.start()]
        label = _TRAILING_TOKEN.sub("", label)
        if label == before:
            break
    label = _EPISODE_TITLE.sub(r"\1", label)
    label = " ".join(label.strip(" _.-").split()) or stem
    if len(label) > LABEL_MAX:
        label = label[:18] + "…" + label[-(LABEL_MAX - 19):]
    return label


def short_name(stem):
    """A file's short name as the dictionary shows it — release tags, video ids and quality tags
    trimmed (`_short_label`) — for anyone else naming a library file in a few words (Junban's
    "why" column)."""
    return _short_label(_clean(stem))


def _hiragana(kana):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in kana)


def _rules(ctype, spelling):
    """Yomitan's de-inflection class from UniDic's conjugation type, so 辿り着いた finds 辿り着く. Taken
    from cType rather than the part of speech: やがる is an auxiliary that conjugates like 五段."""
    if not ctype:
        return ""
    if ctype.startswith("五段"):
        return "v5"
    if ctype.startswith(("上一段", "下一段")):
        return "v1"
    if ctype.startswith("カ行変格"):
        return "vk"
    if ctype.startswith("サ行変格"):
        return "vz" if spelling.endswith("ずる") else "vs"
    if ctype == "形容詞":
        return "adj-i"
    return ""


def _japanese_terms(lemma, lform, orths, tag):
    """[(term, reading, rules)] for one word: the spellings the content uses, most common first.

    Each spelling is tagged ALONE (`tag(text)` -> (lemma, lForm, kanaBase, cType), or None when it
    doesn't come back as one word), because a spelling can read differently from its lemma: 感じる is
    filed under 感ずる, so its own reading (かんじる) and class (v1) are what group it with JMdict's
    感じる. The tag is trusted only when it is the SAME word — same lemma and lemma reading — since a
    homograph tagged alone comes back as its commonest reading (上手 -> ジョウズ even for the カミテ one).
    Anything else (スドウ splits into symbols) keeps the word's own reading and no rules."""
    from app.analyzer import _sanitize_term, has_target_language

    ordered = [o for o, _n in sorted(orths.items(), key=lambda kv: (-kv[1], kv[0]))
               if o and has_target_language(o, "ja")] or [lemma]
    terms = []
    for orth in ordered:
        info = tag(orth)
        if info and _sanitize_term(info[0]) == lemma and info[1] == lform:
            base, ctype = info[2], info[3]
            if lform and lform[-1] in _U_TO_E and base == lform[:-1] + _U_TO_E[lform[-1]] + "ル" \
                    and ctype.startswith("下一段"):
                continue        # the potential form (辿り着ける) — Yomitan finds it via 辿り着く
            reading, rules = base or lform, _rules(ctype, orth)
        else:
            reading, rules = lform, ""
        terms.append((orth, reading, rules))
    # Hovering kana already finds the kanji entry by its reading, so a kana-only spelling is only
    # worth an entry when there is no kanji one.
    if any(_KANJI.search(t) for t, _r, _x in terms):
        terms = [t for t in terms if not _KANA_ONLY.match(t[0])]
    if not terms and ordered:
        terms = [(ordered[0], lform, "")]
    return [(t, "" if _KANA_ONLY.match(t) else _hiragana(r), x) for t, r, x in terms[:MAX_SPELLINGS]]


def _content(best, sources, language, show_source=False):
    """One word's sentences as ONE structured-content block, text first (spec §5.2, I8): each sentence
    a div (a line of its own everywhere), the marker ①–⑧ plain text (CSS mutes it via ::first-letter —
    a span would cost a space in Yomitan's plain-text conversion), and the word the one inline span
    inside the sentence. A thin divider line runs between sentences.

    Where each sentence came from is always its hover text (the file's path). With `show_source` it is
    also written after it — a span at the end, '　（short name）', the full-width space being the gap —
    which Yomitan puts on a small grey line of its own."""
    lines = []
    for n, (_key, text, fidx, surface) in enumerate(best):
        text = _clean(text)
        label, rel = sources[fidx]
        at = text.find(surface) if surface else -1
        if at >= 0:
            parts = [_MARKERS[n] + " " + text[:at],
                     {"tag": "span", "data": {"surasura": "target"}, "style": {"fontWeight": "bold"},
                      "content": surface}]
            if text[at + len(surface):]:
                parts.append(text[at + len(surface):])
        else:
            parts = [_MARKERS[n] + " " + text]      # not found as written — never guess a highlight
        if show_source:
            parts.append({"tag": "span", "data": {"surasura": "source"}, "style": dict(_SOURCE_STYLE),
                          "content": f"　（{label}）"})
        line = {"tag": "div", "data": {"surasura": "sentence"}, "title": rel, "content": parts}
        if n < len(best) - 1:
            line["style"] = dict(_DIVIDER)
        lines.append(line)
    return {"tag": "div", "lang": language, "data": {"surasura": "sentences"}, "content": lines}


def _default_tagger():
    """tag(text) -> (lemma, lForm, kanaBase, cType) when `text` is exactly one Japanese word, else
    None."""
    import fugashi   # lazy: only a Japanese export pays this import
    tagger = fugashi.Tagger()

    def tag(text):
        tokens = list(tagger(text))
        if len(tokens) != 1:
            return None
        f = tokens[0].feature
        return (f.lemma or text, f.lForm or "", f.kanaBase or "",
                f.cType if f.cType and f.cType != "*" else "")
    return tag


def export_dictionary(words, sources, save_path, language, tag=None, progress=None, show_source=False):
    """Write the Yomitan dictionary for `words` (from collect()) to `save_path`. `sources[i]` is
    (short name, relative path) of the i-th library file; `show_source` writes the short name after
    each sentence (the path is always its hover text). Returns the number of words written; writes
    NOTHING when there are none. Built in `<save_path>.tmp` and renamed, so a failed run can never
    leave half a dictionary where the user expects one."""
    listed = [(key, w) for key, w in words.items() if w.listed and w.best.kept]
    if not listed:
        return 0
    if language == "ja" and tag is None:
        tag = _default_tagger()
    # A word's rank by library count is its sequence: every spelling of it shares one number, the
    # way 大辞林 and JMdict group alternate spellings.
    listed.sort(key=lambda kw: (-kw[1].count, kw[0]))

    def _json(value):
        return json.dumps(value, ensure_ascii=False)

    tmp = save_path + ".tmp"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            # Each bank is STREAMED into the zip one entry at a time — nothing bank-sized is ever held
            # (I7). Building a bank first measured 413 MB of private memory at peak against 102 MB for
            # the whole pass: 10,000 entries of text, joined, then encoded, and a single emoji in a
            # video title makes Python store the entire joined text at four bytes a character. The
            # sentences are serialized once per word and shared by all of its spellings.
            banks, in_bank, handle = 0, 0, None
            try:
                for rank, ((lemma, reading), word) in enumerate(listed, 1):
                    glossary = _json([{"type": "structured-content",
                                       "content": _content(word.best.result(), sources, language,
                                                           show_source)}])
                    if language == "ja":
                        terms = _japanese_terms(lemma, reading, word.orths, tag)
                    else:
                        terms = [(max(word.orths, key=word.orths.get) if word.orths else lemma, "", "")]
                    for term, term_reading, rules in terms:
                        if handle is None:
                            banks += 1
                            handle = zf.open(f"term_bank_{banks}.json", "w")
                            handle.write(b"[")
                            in_bank = 0
                        entry = (f'[{_json(term)},{_json(term_reading)},"",{_json(rules)},0,'
                                 f'{glossary},{rank},""]')
                        handle.write((b"," if in_bank else b"") + entry.encode("utf-8"))
                        in_bank += 1
                        if in_bank >= TERMS_PER_BANK:
                            handle.write(b"]")
                            handle.close()
                            handle = None
            finally:
                if handle is not None:
                    handle.write(b"]")
                    handle.close()
            index = {
                "title": dictionary_title(language),
                "format": 3,
                "revision": datetime.now().strftime("%Y%m%d"),
                "sequenced": True,
                "author": "SonicSandbox",
                "description": (f"Example sentences from your own immersion library — {len(listed):,} "
                                f"words, best first. Generated by Surasura ({language})."),
                "attribution": "Sentences quoted from your personal library, for personal study only.",
                "sourceLanguage": language,
                "targetLanguage": language,
            }
            zf.writestr("index.json", json.dumps(index, ensure_ascii=False, indent=2))
            zf.writestr("styles.css", CORPUS_CSS)
        os.replace(tmp, save_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    if progress:
        progress(f"Wrote {len(listed):,} words in {banks} term bank(s).")
    return len(listed)


# --------------------------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------------------------- #
def known_sets(language, store, settings):
    """(known_tuples, known_lemmas, ignore): the analyzer's own sets — the known words as the token
    store caches them (by KnownWord.json's signature), and the Ignore, Blacklist and Graduated lists."""
    import sqlite3
    from app import analyzer, token_index
    from app.path_utils import get_user_files_path
    from app.zh_script import effective

    reinforce = bool(settings.get("reinforce_segmentation", False))
    script = effective(language, settings.get("zh_script", "asis"))
    user_files = get_user_files_path(language)
    known_file = os.path.join(user_files, "KnownWord.json")
    signature = token_index.known_signature(known_file, script)
    cached = store.get_cached_known(signature)
    if cached is None:
        tok = (analyzer.ChineseTokenizer(reinforce_segmentation=reinforce, script=script)
               if language == "zh" else analyzer.JapaneseTokenizer())
        cached = analyzer.load_known_words(known_file, tok)
        try:
            store.set_cached_known(signature, *cached)
        except sqlite3.Error:
            pass
    ignore = set()
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        ignore |= analyzer.load_simple_list(os.path.join(user_files, name), script)
    return cached[0], cached[1], ignore


def best_for(language, wanted, progress=None, young=None, phrases=None):
    """The best sentences of the words in `wanted` — {(lemma, reading)} — ranked as the dictionary ranks
    them (`collect`), so a card's added sentence is the one the Surasura Corpus shows first; `young`
    (keys still being learned) breaks ties toward sentences that practise them; `phrases` ({name:
    lemmas}) finds several-word targets too, under their name. For Anki Backfill's 例文
    (`modules/junban/backfill.py`). Reads the token store as it stands and never tokenizes the
    library: the background indexer keeps it current.

    -> {key or name: [(others, text, surface, file)]}, best first — `others` is how many words besides
    the target's own the learner doesn't know; `file` tells two sentences' episodes apart. A target
    with no sentence of a good length is absent."""
    from app import analyzer, settings_manager, token_index

    if not wanted and not phrases:
        return {}
    settings = settings_manager.load_settings()
    # As every run sets it, before the known words are read (a new cache is tokenized with it).
    analyzer.SANITIZE_JA = (language == "ja")
    files = [p for p, _label, _weight, _type in analyzer.resolve_found_files(language, verbose=False)]
    if not files:
        return {}
    store = token_index.open_store(language)
    try:
        words = collect(files, store.file_tokens, language, known_sets(language, store, settings),
                        length_range(settings), progress=progress, wanted=set(wanted or ()),
                        young=set(young or ()), phrases=phrases)
    finally:
        store.close()
    found = {}
    for key, word in words.items():
        best = word.best.result() if word.best is not None else []
        if best:
            found[key] = [(rank[0], text, surface, fidx) for rank, text, fidx, surface in best]
    return found


def build(language, save_path, progress=print, show_source=False):
    """Library -> token store (only new or changed files tokenized) -> one pass -> the dictionary.
    Returns the number of words written (0: nothing to export, nothing written)."""
    import sqlite3
    from app import analyzer, settings_manager, token_index
    from app.path_utils import get_data_path
    from app.zh_script import effective

    settings = settings_manager.load_settings()
    reinforce = bool(settings.get("reinforce_segmentation", False))
    script = effective(language, settings.get("zh_script", "asis"))
    window = length_range(settings)
    # The same normalization a run uses, before anything is tokenized or any list is read.
    analyzer.SANITIZE_JA = (language == "ja")

    files = [p for p, _label, _weight, _type in analyzer.resolve_found_files(language, verbose=False)]
    if not files:
        progress("Your library is empty — add content first.")
        return 0
    progress(f"Sentences of {window[0]}–{window[1]} characters "
             f"(your {window[2]}–{window[3]}, ±{LENGTH_LEEWAY}), up to {SENTENCES_PER_WORD} per word.")

    store = token_index.open_store(language)
    try:
        progress("Checking your library for new or changed files…")
        try:
            store.reconcile(files, token_index.make_tokenizer(language, reinforce=reinforce, script=script),
                            build_signature=token_index.build_signature(language, reinforce, script))
        except sqlite3.OperationalError as e:
            # Another process (the background indexer, a Generate) holds the store. What is cached is
            # still whole; only the newest files may be missing — never block on it, and never fall
            # back to tokenizing the whole library here.
            progress(f"Your library is being indexed right now ({e}); using what is ready — files "
                     "added in the last few minutes may be missing.")

        words = collect(files, store.file_tokens, language, known_sets(language, store, settings),
                        window, progress=progress)
    finally:
        store.close()

    data_dir = get_data_path(language)
    sources = [(_short_label(_clean(os.path.splitext(os.path.basename(p))[0])),
                _clean(os.path.relpath(p, data_dir).replace("\\", "/"))) for p in files]
    progress("Writing the dictionary…")
    written = export_dictionary(words, sources, save_path, language, progress=progress,
                                show_source=show_source)
    if not written:
        progress("No sentences of a good length were found, so there is nothing to export.")
    return written


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Surasura sentence dictionary (Yomitan) export")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--output", required=True, help="the .zip to write")
    parser.add_argument("--show-source", action="store_true",
                        help="write a short file name after each sentence (it is always the hover text)")
    args, _unknown = parser.parse_known_args()
    try:
        written = build(args.language, args.output, show_source=args.show_source)
    except Exception as e:
        print(f"Error: the sentence dictionary could not be made: {e}")
        sys.exit(1)
    if not written:
        sys.exit(1)
    print(f"Saved {dictionary_title(args.language)} — {written:,} words — to {args.output}")


if __name__ == "__main__":
    main()
