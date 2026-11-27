"""The journey v3 page's data (SPEC §5; its shape, fixed for the page: TheForge `tracks/window/work/j-data/SHAPE.md`).

One function makes the page's data from a Generate's outputs, read-only on every piece it reads:

- **the head** — every episode in the study order (the library store's item id, its title, show, tier, kind, % known,
  *N new*, stone state, pre-studied, growth), the shows, the two orders as index lists, the chunks' word ranges;
- **the words**, each once, at the episode it is first met in, in gzip chunks of at most `CHUNK_EPISODES` episodes or
  `CHUNK_BYTES` of JSON (the heaviest chunk stays under 100 KB gzipped): word, reading, dictionary form, marks, its count
  ahead, pitch, and its sentences with a chunk-local source table (never a path);
- **meanings** (JMdict EN / CC-CEDICT, app/gloss_*_data.py) and **kanji** (KANJIDIC2, app/kanji_data.py, with the
  learner's most frequent known word for each) for the page's words only, and **Yours** (the learner's own Anki Miner
  dictionaries, `app/own_dicts.py`) only when *Meanings* asks for them.

**Qt-free** (Charter S17; the keeper runs it headless): nothing here imports PyQt6, Tk or the window — `stone_plan` and
`view_rows` are the services' pure modules; `tests/test_journey_render_shape.py` holds it.

**Seams** (one place each, until their owners land): the stone's state (`_stone_state`: `stone_plan.state_of` once
J-STONES makes it public, `tip_state` until then), its pictures (`stone_pictures`: `app/stone_shapes`, J-STONES),
pre-studied (`Store.prestudied_marks`, J-STORE), growth (`Store.growth_of`, Kura-GS #585) — each read through
`getattr`, so a store without it is an honest empty state, never an error.

Not wired yet: J-CUT makes `generate_static_html`'s journey call `render` and `write_page`. Until then nothing calls
this module, so a 3.0.18 learner's journey is what it was.
"""
import base64
import math
import gzip
import json
import os
import re
import time
import zlib
from array import array
from collections import namedtuple
from itertools import accumulate

SHAPE = 1                       # the shape's version (SHAPE.md); a change is a NOTE to the page first
SHAPE_MINOR = 1                 # 1.1 (2026-11-22): additive only — the head's `minor`, a source's item id, the seven
#                                 settings, `stamp` in ms; a v1 reader reads a 1.1 page as before
MARKER = "<!--JOURNEY-DATA-->"  # where the page's template takes the data, once
WORD_MEMO = "journey_words.json"   # in results/, beside the ▶'s memos: `WordMemo`
SHOWN_FILE = "shown.json.gz"        # in results/: the list reader's shown lines (`analyzer.SHOWN_FILE`), its silent ones
PLAN_FILE = "plan.json.gz"          # in results/: the plan file (`analyzer.PLAN_FILE`), its header the run's signature
MEMO_FORMAT = 1                 # in the memo's keys: bump when a meaning's JSON or a pitch is written another way
CHUNK_EPISODES = 100
CHUNK_BYTES = 240_000           # a chunk's JSON closes past this (≈ 60–80 KB gzipped for Japanese sentences)
AHEAD = 3                       # "its count in the next few episodes": its own and the next two
GZIP_LEVEL = 4                  # level 6 took 2.5x as long for 9 % less (2k: 0.36 s -> 0.14 s)
KIND_TIERS = ("now", "soon", "goal")        # `library_store.ANALYSED`: the head's tier 0 · 1 · 2

# JMdict's part-of-speech codes, as the page says them (the rest are shown as their code)
POS_WORDS = {"n": "noun", "pn": "pronoun", "adv": "adverb", "adv-to": "adverb (と)", "exp": "expression",
             "int": "interjection", "prt": "particle", "conj": "conjunction", "ctr": "counter", "num": "numeric",
             "pref": "prefix", "suf": "suffix", "aux-v": "auxiliary verb", "aux-adj": "auxiliary adjective",
             "cop": "copula", "adj-i": "い-adjective", "adj-ix": "い-adjective (いい)", "adj-na": "な-adjective",
             "adj-no": "の-adjective", "adj-pn": "pre-noun adjectival", "adj-t": "たる-adjective",
             "adj-f": "noun or verb acting prenominally", "vs": "suru verb", "vs-i": "suru verb", "vs-s": "suru verb",
             "vk": "kuru verb", "vz": "zuru verb", "v1": "ichidan verb", "v1-s": "ichidan verb",
             "vi": "intransitive", "vt": "transitive", "n-suf": "noun (suffix)", "n-pref": "noun (prefix)",
             "n-adv": "adverbial noun", "n-t": "noun (temporal)"}

# The head's `settings` (SHAPE 1.1: the page reads them by these names) -> the journey's settings keys. Every value is
# `journey_settings.page_values`' (J-SET: the one reader of the journey's settings, its choices, defaults and how an
# older value reads); nothing here reads a setting itself. A key J-SET adds needs its name here (a test holds it).
HEAD_SETTINGS = {
    "sentences": "logic.context.max_contexts",      # 0 = All
    "meanings": "journey_meanings",
    "pitch": "journey_pitch",
    "source": "source_display",
    "word_size": "journey_word_size",
    "sentence_size": "journey_sentence_size",
    "theme": "theme",
    "keys": "journey_keys",                         # or the learner's own map {action: key}
    "first_meeting": "journey_first_meeting",       # the page marks the shown line from the word's own episode (J-PAGE 5)
}

_Ep = namedtuple("_Ep", "watched cards status missing removed in_top")
StoreFacts = namedtuple("StoreFacts", "items works order cards pre growth library counted marks",
                        defaults=(None, None))
#   items {id: feed row} · works {id: row} · order [id] (the study order, set-aside watched items in their place) ·
#   cards {id: n} · pre {id: (day, by)} · growth {id: {kind: {...}}} · library: the queue's key (D31) ·
#   counted {id}: the items Generate's list reads (None: all of `order`) · marks: `Store.watched_marks`' from the same
#   read (`library_store.UNREAD` when they couldn't be read), what the page is signed with (`_write_journey`)


# --- values --------------------------------------------------------------------------------------------------------- #

def _clean(value):
    """A CSV cell as the page takes it: NaN / None / "" -> None; a whole float -> int."""
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:
            return None
        return int(value) if value.is_integer() else value
    return value


def _text(value):
    if value.__class__ is str:                  # a CSV cell (the common case): as it is
        return value
    value = _clean(value)
    return "" if value is None else str(value)


def _num(value, default=0):
    value = _clean(value)
    try:
        number = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default        # "nan" / "inf" as text: as an empty cell


_ENCODE = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode   # made once


def _json(obj):
    """UTF-8 JSON as the page reads it: never ASCII-escaped, never NaN (raises instead), `</` written `<\\/`."""
    return _ENCODE(obj).replace("</", "<\\/")


def _gz(obj):
    return gzip.compress(_json(obj).encode("utf-8"), GZIP_LEVEL, mtime=0)


_TO_HIRA = {c: c - 0x60 for c in range(ord("ァ"), ord("ヶ") + 1)}


def _hira(text):
    return (text or "").translate(_TO_HIRA)


def page_settings(settings):
    """The head's `settings`: every row of SPEC §1.4 with its value at this render (`journey_settings.page_values`),
    and ⌕'s switch and category (`journey_settings.lookup_values`: Settings' rows, not the page's ⚙)."""
    from app.services.journey_settings import lookup_values, page_values
    values = page_values(settings)
    return {**{name: values[key] for name, key in HEAD_SETTINGS.items()}, **lookup_values(settings)}


def sentences_of(row, per_word):
    """The word's sentences as the page shows them, first to last: [(text, its source's rel path or "")], at most
    `per_word` (0 = All: every one the row has). **The one place the page's sentence choice is read**: today the
    list's own, as it keeps them (`Context n` / `Src n` in its order, Context 1 first). Sonic is deciding which
    sentence comes first (the sentence-choice study, 2026-11-22): his ruling changes this function, nothing else."""
    if 0 < per_word <= 50:
        columns = _columns(per_word)
    else:                                       # All (or a hand-edited number past any list): the row's own columns
        numbers = {int(k[8:]) for k in row if k.startswith("Context ") and k[8:].isdecimal()}   # "Context 01" is 1
        columns = [(f"Context {n}", f"Src {n}") for n in sorted(numbers) if n and (not per_word or n <= per_word)]
    found = []
    for context, src in columns:
        text = _text(row.get(context))
        if text:
            found.append((text, _text(row.get(src))))
    return found


_COLUMNS = {}


def _columns(n):
    if n not in _COLUMNS:
        _COLUMNS[n] = tuple((f"Context {i}", f"Src {i}") for i in range(1, n + 1))
    return _COLUMNS[n]


def _day(stamp):
    """A store stamp ("2026-11-03T…") -> its day, "2026-11-03"; None stays None."""
    return stamp[:10] if isinstance(stamp, str) and len(stamp) >= 10 else None


# --- the marks: ✦ ⚖ 文 and the green Anki icon (today's page's rules, moved here so the page only reads bits) ------- #

def marks_of(row, thresholds):
    """The word's marks as bits: 1 ✦ high leverage · 2 ⚖ lots soon, rare later · 4 文 a reading word (the page's
    rule, web_app.html's createWordCard: `priority_markers`). The Anki bit (8) is `in_anki`'s."""
    high, low = _num(row.get("Count (High)")), _num(row.get("Count (Low)"))
    total = _num(row.get("Occurrences (Global)", row.get("Occurrences")))
    lopsided = total > 0 and high / total >= thresholds.get("lopsided_threshold", 0.85)
    priority = (not lopsided and total >= thresholds.get("priority_min", 3)
                and (high + low) / total >= thresholds.get("priority_threshold", 0.5)) if total > 0 else False
    return (1 if priority else 0) | (2 if lopsided else 0) | (4 if row.get("Modality") == "reading" else 0)


def _fold(key):
    from app.anki_match import _KANA_ONLY_RE, fold_kana
    return fold_kana(key) if _KANA_ONLY_RE.match(key) else key


def anki_owners(rows, language):
    """{spelling: (Word, Reading)}: the row each spelling belongs to — Junban's index as today's page reads it
    (web_app.html's ankiOwners): every row's own word (its Orth, then its Word) before any row's Forms, an earlier row
    before a later one, then each kana spelling's hiragana fold where no row holds it; a one-character spelling only
    as the row's own word (Japanese)."""
    owners = {}
    japanese = language == "ja"

    def claim(raw, owner, lemma):
        key = _text(raw).strip()
        if not key or key in owners:
            return
        if japanese and len(key) == 1 and key != lemma:
            return
        owners[key] = owner

    for row in rows:
        lemma = _text(row.get("Word")).strip()
        owner = (_text(row.get("Word")), _text(row.get("Reading")))
        claim(row.get("Orth"), owner, lemma)
        claim(row.get("Word"), owner, lemma)
    for row in rows:
        owner = (_text(row.get("Word")), _text(row.get("Reading")))
        for form in _text(row.get("Forms")).split("|"):
            claim(form, owner, None)
    if japanese:
        for key, owner in list(owners.items()):
            folded = _fold(key)
            if folded != key and folded not in owners:
                owners[folded] = owner
    return owners


def in_anki(row, keys, owners, language):
    """Is the row's word one of a waiting card's keys that this row owns (web_app.html's inAnkiBacklog)?"""
    if not keys:
        return False
    owner = (_text(row.get("Word")), _text(row.get("Reading")))
    forms = _text(row.get("Forms")).split("|")
    for raw in [row.get("Word"), row.get("Orth"), *forms]:
        key = _text(raw).strip()
        if not key:
            continue
        for spelling in ((key, _fold(key)) if language == "ja" else (key,)):
            if spelling in keys and owners.get(spelling) == owner:
                return True
    return False


# --- meanings, kanji, pitch ----------------------------------------------------------------------------------------- #

def _table_lines(module, piece=1 << 20):
    """A data module's table, line by line as UTF-8 bytes, decompressed a piece at a time (the whole table at once is
    ~17 MB of bytes and its lines as many again)."""
    import lzma
    dec = lzma.LZMADecompressor()
    out = dec.decompress(base64.b64decode(module.DATA), piece)
    rest = b""
    while True:
        lines = (rest + out).split(b"\n")
        rest = lines.pop()
        yield from lines
        if dec.eof or dec.needs_input:          # needs_input before eof: a cut table, its last line kept
            break
        out = dec.decompress(b"", piece)
    if rest:
        yield rest


def _table(module):
    return [line.decode("utf-8") for line in _table_lines(module)]


def _line_keys(line):
    """The keys a meanings line (UTF-8 bytes) is found by, each once: its fields before the second tab, split at
    commas (ja: kanji forms, readings · zh: 简, 繁). [] for a line without them. The build's INDEX holds these."""
    first = line.find(b"\t")
    second = line.find(b"\t", first + 1)
    if first < 0 or second < 0:
        return []
    return [key for key in dict.fromkeys(line[:second].replace(b"\t", b",").split(b",")) if key]


_GLOSS_INDEX = {}           # {module name: (each bucket's start in the block numbers, the block numbers, DICT)}


def _gloss_lines(module, wanted):
    """A meanings module's lines (bytes) in the blocks that may hold one of `wanted` (UTF-8 keys) — every line that
    does among them, in the table's order — from its INDEX (each key's bucket names its blocks): only those blocks
    decompressed (each a zstd frame against the table's DICT), the caller checks each line (G4;
    scripts/build_gloss_data.py). The index is read once a process; a decompressor is made each call (one is never
    shared between threads)."""
    import zstandard
    index = _GLOSS_INDEX.get(module.__name__)
    if index is None:
        raw = zlib.decompress(base64.b64decode(module.INDEX))
        buckets = module.BUCKETS
        index = _GLOSS_INDEX[module.__name__] = (array("I", accumulate(raw[:buckets], initial=0)), raw[buckets:],
                                                 base64.b64decode(module.DICT))
    starts, named, trained = index
    buckets, found = module.BUCKETS, set()
    for key in wanted:
        b = zlib.crc32(key) % buckets
        found.update(named[starts[b]:starts[b + 1]])
    if not found:
        return
    data, blocks = base64.b64decode(module.DATA), module.BLOCKS
    reader = (zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(trained)) if trained
              else zstandard.ZstdDecompressor())
    for block in sorted(found):
        yield from reader.decompress(data[blocks[block]:blocks[block + 1]]).split(b"\n")


class WordMemo:
    """The meanings and pitch the last page looked up (`results/journey_words.json`, beside the ▶'s memos): a render
    with the same words reads them here instead of looking them up in the table and tagging every word again (SPEC
    §5.4's warm row) — and each file's shown name (`shown`: a render is a process of its own, so LM1a's reading of 20,000 names
    was made from nothing at every redraw, 0.8 s at 20,000 files; L2-WASTE), kept while the code that reads them is
    the same (`names_key`). A word's meaning is kept as the page's own JSON for it ("" = none), so a warm render writes it as it is.
    Each half is kept only while its key holds (the meanings table's revision; unidic's dictionary file and the
    learner's Kanjium copy), pruned at `save` to the words this page asked; a missing or unreadable memo is an empty
    one (the render is the same, only slower). Holds only what the shipped table and unidic say — never the learner's
    own dictionaries' text."""

    def __init__(self, path, gloss_key, pitch_key, names_key="?"):
        self.path, self.gloss_key, self.pitch_key, self.names_key = path, gloss_key, pitch_key, names_key
        self.meanings, self.pinyins, self.pitch, self.names, self.dirty = {}, {}, {}, {}, False
        self._asked = (set(), set(), set(), set())
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("v") == SHAPE and data.get("g_key") == gloss_key and "?" not in gloss_key:
                self.meanings = data["m"] if isinstance(data.get("m"), dict) else {}
                self.pinyins = data["y"] if isinstance(data.get("y"), dict) else {}
            if (data.get("v") == SHAPE and data.get("p_key") == pitch_key and "?" not in pitch_key
                    and isinstance(data.get("p"), dict)):
                self.pitch = data["p"]
            if (data.get("v") == SHAPE and data.get("n_key") == names_key and "?" not in names_key
                    and isinstance(data.get("n"), dict)):
                self.names = data["n"]
        except Exception:
            pass
        self._held = (len(self.meanings), len(self.pinyins), len(self.pitch), len(self.names))

    @staticmethod
    def _key(*parts):
        return "\t".join(parts)

    def meaning(self, word, reading, orth):
        """The word's meaning as the page's JSON ("" = none), or None when the memo doesn't hold it."""
        key = self._key(word, reading, orth)
        self._asked[0].add(key)
        return self.meanings.get(key)

    def add_meaning(self, word, reading, orth, text):
        self.meanings[self._key(word, reading, orth)] = text
        self.dirty = True

    def pinyin(self, spelling):
        self._asked[1].add(spelling)
        return self.pinyins.get(spelling)

    def add_pinyin(self, spelling, value):
        self.pinyins[spelling] = value
        self.dirty = True

    def pitch_of(self, pairs):
        """{(word, reading): its pitch} for the pairs the memo holds (None = no pitch data, as looked up)."""
        out = {}
        for word, reading in pairs:
            key = self._key(word, reading)
            self._asked[2].add(key)
            if key in self.pitch:
                out[(word, reading)] = self.pitch[key]
        return out

    def add_pitch(self, found):
        for (word, reading), value in found.items():
            self.pitch[self._key(word, reading)] = value
        self.dirty = self.dirty or bool(found)

    def shown(self, name):
        """A file's shown name (`static_html_generator.shown_name`), the memo's when it holds it."""
        self._asked[3].add(name)
        found = self.names.get(name)
        if not isinstance(found, str):
            from app.static_html_generator import shown_name
            found = self.names[name] = shown_name(name)
            self.dirty = True
        return found

    def save(self):
        """Write the memo, pruned to this page's words, when anything was added or dropped. Best-effort."""
        kept = [{k: v for k, v in held.items() if k in asked}
                for held, asked in zip((self.meanings, self.pinyins, self.pitch, self.names), self._asked)]
        if not self.dirty and tuple(len(k) for k in kept) == self._held:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps({"v": SHAPE, "g_key": self.gloss_key, "m": kept[0], "y": kept[1],
                                    "p_key": self.pitch_key, "p": kept[2], "n_key": self.names_key, "n": kept[3]},
                                   ensure_ascii=False,
                                   separators=(",", ":")))
            os.replace(tmp, self.path)
        except Exception as e:
            print(f"Warning: could not save the journey's word memo: {e}")
            try:
                os.remove(tmp)
            except OSError:
                pass


def names_key():
    """`WordMemo`'s key for the files' shown names: the code that reads them (`static_html_generator.shown_name`, LM1a's
    `episode_names.identity`, the rows' `view_rows`) — a freeze's own build (`build_info.BUILD_ID`), from source those
    three files (each by size and time). "?" when it can't be read: no memo holds it."""
    try:
        import sys
        if getattr(sys, "frozen", False):
            from app import build_info
            return f"{MEMO_FORMAT}:build:{build_info.BUILD_ID}" if build_info.BUILD_ID else "?"
        from app import episode_names, static_html_generator
        from app.services import view_rows
        stamps = (os.stat(module.__file__) for module in (episode_names, view_rows, static_html_generator))
        return f"{MEMO_FORMAT}:" + "|".join(f"{st.st_size}:{st.st_mtime_ns}" for st in stamps)
    except Exception:
        return "?"


def memo_keys(language):
    """(gloss key, pitch key) for `WordMemo`: the meanings table's revision; unidic's dictionary file and the
    learner's Kanjium copy (each by size and time). A part that can't be read keys as "?", which no memo holds."""
    try:
        if language == "ja":
            from app import gloss_ja_data as module
        else:
            from app import gloss_zh_data as module
        gloss = f"{language}:{module.REVISION}:{MEMO_FORMAT}"
    except Exception:
        gloss = "?"
    if language != "ja":
        return gloss, ""

    def stamp(path):
        st = os.stat(path)
        return f"{st.st_size}:{st.st_mtime_ns}"
    try:
        import unidic_lite
        pitch = f"{MEMO_FORMAT}:unidic:" + stamp(os.path.join(unidic_lite.DICDIR, "sys.dic"))
        from app import own_dicts
        found = own_dicts.kanjium_path()
        pitch += "|kanjium:" + (stamp(found) if found else "none")
    except Exception:
        pitch = "?"
    return gloss, pitch


_POS_TEXT = {}


def _pos_text(codes):
    """JMdict's codes ("n;vs") as the page says them ("noun · suru verb"), each list worked out once."""
    found = _POS_TEXT.get(codes)
    if found is None:
        found = _POS_TEXT[codes] = " · ".join(dict.fromkeys(POS_WORDS.get(p, p) for p in codes.split(";") if p))
    return found


class Meanings:
    """The shipped English meanings (app/gloss_ja_data.py · app/gloss_zh_data.py), read for the words asked only:
    `of(word, reading, orth)` -> [[pos, [gloss, …]], …] or None; `pinyin(word)` (zh) -> the first entry's pinyin.
    The table's index names the lines a page's words are on: only their blocks are decompressed and only those
    entries decoded and kept (the whole table decoded is ~85 MB of strings; the page's part, a few MB); with a
    `WordMemo`, only for the words it lacks.
    `of_json` is `of` as the page's JSON ("" = none), through the memo."""

    def __init__(self, language, memo=None):
        self.language = language
        self.memo = memo
        self._index = {}

    def _load(self, wanted):
        if self.language == "ja":
            from app import gloss_ja_data as module
        else:
            from app import gloss_zh_data as module
        wanted = {key.encode("utf-8") for key in wanted}
        index, isdisjoint = {}, wanted.isdisjoint
        for line in _gloss_lines(module, wanted):       # (the index's blocks only: each line checked here)
            # `_line_keys` inline and its dedupe only on a hit: this runs for every line of the blocks read (all of
            # them for a memo-less page), so a call and a dict a line cost a third more than the scan it replaced
            second = line.find(b"\t", line.find(b"\t") + 1)
            if second < 0:
                continue
            keys = line[:second].replace(b"\t", b",").split(b",")   # ja: kanji forms, readings · zh: 简, 繁
            if isdisjoint(keys):
                continue
            entry = line.decode("utf-8").split("\t")
            for key in dict.fromkeys(keys):
                if key in wanted:
                    index.setdefault(key.decode("utf-8"), []).append(entry)
        return index

    def prepare(self, words):
        """Index the table for these words' spellings only ([(word, reading, orth)], a page's words), looked up once —
        none of it for a word the memo holds."""
        memo, wanted = self.memo, set()
        for word, reading, orth in words:
            if memo is None or memo.meaning(word, reading, orth) is None:
                wanted.update(k for k in (word, orth) if k)
            elif self.language == "zh":                 # as `build` asks: the word's pinyin, then its orth's
                first = memo.pinyin(word) if word else ""
                if first is None or (not first and orth and memo.pinyin(orth) is None):
                    wanted.update(k for k in (word, orth) if k)
        self._index = self._load(wanted) if wanted else {}

    def _entries(self, key):
        return self._index.get(key, ())

    def _pick(self, word, reading, orth):
        if self.language == "zh":
            for key in (word, orth):
                found = self._entries(key) if key else []
                if found:
                    return found[0]
            return None
        hira = _hira(reading)
        for key in dict.fromkeys(k for k in (word, orth) if k):
            found = self._entries(key)
            if found:
                for entry in found:
                    if hira and hira in entry[1].split(","):
                        return entry
                return found[0]
        return None

    def of(self, word, reading="", orth=""):
        entry = self._pick(word, reading, orth)
        if entry is None:
            return None
        if self.language == "zh":
            return [["", [g.strip() for g in sense.split(";") if g.strip()][:3]] for sense in entry[3:]]
        out = []
        for sense in entry[2:]:
            pos, _, glosses = sense.partition("|")
            out.append([_pos_text(pos), glosses.split("; ")])
        return out

    def pinyin(self, word):
        if self.memo is not None:
            found = self.memo.pinyin(word)
            if found is not None:
                return found
        entry = self._pick(word, "", "")
        found = entry[2] if entry else ""
        if self.memo is not None:
            self.memo.add_pinyin(word, found)
        return found

    def of_json(self, word, reading="", orth=""):
        """`of` as the page's JSON for the word ("" when there is none), the memo's when it holds it."""
        if self.memo is not None:
            found = self.memo.meaning(word, reading, orth)
            if found is not None:
                return found
        meant = self.of(word, reading, orth)
        found = _json(meant) if meant else ""
        if self.memo is not None:
            self.memo.add_meaning(word, reading, orth, found)
        return found


class Kanji:
    """KANJIDIC2's meanings and readings (app/kanji_data.py), read once a process: `of(char)` -> [meanings, on, kun]
    or None."""
    _table = None

    def of(self, char):
        if Kanji._table is None:
            from app import kanji_data
            Kanji._table = {line.split("\t", 1)[0]: line.split("\t")[1:] for line in _table(kanji_data) if line}
        return Kanji._table.get(char)


def is_kanji(char):
    return "㐀" <= char <= "鿿" or "豈" <= char <= "﫿" or "\U00020000" <= char <= "\U0002fa1f"


_KANJI = re.compile("[\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")    # is_kanji's ranges, as one pattern


def known_with(chars, known, ranks=None):
    """{kanji: the learner's most frequent known word holding it}: the known word with the best spoken rank
    (`reference_data.spoken_ranks`, 0 = unranked, last), then the shortest, then the first in `known`."""
    ranks = ranks or {}
    best = {}
    for n, term in enumerate(known):
        if not isinstance(term, str) or len(term) < 2:
            continue
        rank = ranks.get(term) or 10 ** 9
        key = (rank, len(term), n)
        for char in set(term):
            if char in chars and (char not in best or key < best[char][0]):
                best[char] = (key, term)
    return {char: term for char, (_key, term) in best.items()}


def _digits(text):
    """Kanjium's positions ("0", "2,0", "(副)0,(名)3") -> "0" / "2,0"; "" when none."""
    out, cur = [], ""
    for ch in str(text) + ",":
        if ch.isdigit():
            cur += ch
        elif ch == ",":
            if cur:
                out.append(cur)
            cur = ""
    return ",".join(dict.fromkeys(out))


class Pitch:
    """A word's pitch as the card holds it (SPEC §5.1; one rule with the card's, 2026-11-22): the learner's own
    Kanjium copy (`own_dicts.kanjium`, what Anki Miner fills PitchPosition from) first, then UniDic's `aType` by the
    card's own fill (`modules/junban/readings.pitch`), else None, *No pitch data*, never 平板. Nothing new is shipped.
    Chinese: the tones of its pinyin. `tagger`: the run's fugashi tagger (None: made on first ask)."""

    def __init__(self, language, tagger=None, kanjium=None):
        self.language = language
        self.tagger = tagger
        self.kanjium = kanjium
        self._read_for = None if kanjium is not None else set()   # the words read from the copy (None: all of it)
        self.memo = {}

    def prepare(self, pairs, memo=None):
        """Fill the memo for these (word, reading) pairs in one go: UniDic's answers from a `WordMemo`, then UniDic for
        the rest, then the learner's Kanjium copy read once (only when it exists) over them (`of` then only reads the
        memo)."""
        if self.language != "ja":
            return
        pairs = list(dict.fromkeys(pairs))
        if memo is not None:
            self.memo.update(memo.pitch_of(pairs))
        fresh = [key for key in pairs if key not in self.memo]
        for key in fresh:
            try:
                self.memo[key] = self._unidic(*key)
            except Exception:
                self.memo[key] = None
        if memo is not None:                    # UniDic's answers only: the learner's copy is never kept in results/
            memo.add_pitch({key: self.memo[key] for key in fresh})
        self._read({word for word, _reading in pairs})          # then the copy over them, as the card holds it
        if self.kanjium:
            for key in pairs:
                try:
                    found = self._kanjium(*key)
                except Exception:
                    found = None
                if found:
                    self.memo[key] = found

    def _read(self, words):
        """Read the copy for the words not read yet (no copy: nothing read, every miss is *No pitch data*)."""
        if self._read_for is None:
            return
        words = set(words) - self._read_for
        if not words:
            return
        from app import own_dicts
        if self.kanjium is None:
            self.kanjium = {}
        if own_dicts.kanjium_path() is not None:
            self.kanjium.update(own_dicts.kanjium(words=words))
        self._read_for |= words

    def _unidic(self, word, reading):
        """UniDic's accent by the card's own rule (`modules/junban/readings.pitch`, Backfill's アクセント fill): one
        dictionary word read as the list reads it — never a name, a cry or a part of a word. One rule for the page and
        the card; without the module, no UniDic pitch (the copy's, or *No pitch data*)."""
        try:
            from modules.junban import readings
        except Exception:
            return None
        if self.tagger is None:
            import fugashi
            self.tagger = fugashi.Tagger()
        accent, _why = readings.pitch(word, reading, self.tagger)
        return _digits(accent) or None

    def _kanjium(self, word, reading):
        self._read((word,))
        entry = self.kanjium.get(word)
        if not entry:
            return None
        found = entry.get(_hira(reading)) if reading else None
        found = found or next(iter(entry.values()))
        digits = _digits(found)
        return f"k:{digits}" if digits else None

    def of(self, word, reading="", pinyin=""):
        if self.language == "zh":
            tones = "".join(ch for ch in pinyin if ch in "12345")
            return tones or None
        key = (word, reading)
        if key not in self.memo:                # the learner's copy first, then UniDic: the card's order
            try:
                value = self._kanjium(word, reading)
            except Exception:
                value = None
            if value is None:
                try:
                    value = self._unidic(word, reading)
                except Exception:
                    value = None
            self.memo[key] = value
        return self.memo[key]


# --- the store's facts (read-only, through its own readers) ---------------------------------------------------------- #

_ITEM_FIELDS = ("id", "rel_path", "tier", "work_id", "parent_folder", "watched", "availability", "ord",
                "source_type", "title")      # what the head reads of an item (and `view_rows._show_name`)
_WORK_FIELDS = ("id", "media_type", "title", "youtube_channel")


def store_facts(language, data_dir=None, user_files_dir=None):
    """The episodes' facts from the library store, read in one go through its readers (`read_feed`, `scheduled_ids`,
    `cards_of`, and — once their lanes land — `prestudied_marks`, `growth_of`), or None with no ready store (the page
    then names episodes by file only). One read transaction (`_reading`), the stones' marks (`watched_marks`) in it:
    the page and the render signature it is signed with read the same store (J-FIX 3: a mark landing between two reads
    was drawn but not signed, so its Undo left the stone). Never writes, never raises."""
    try:
        from app import library_store
        from app.path_utils import get_data_path, get_user_files_path
        data_dir = data_dir or get_data_path(language)
        user_files_dir = user_files_dir or get_user_files_path(language)
        store = library_store.open_store(language, data_dir, user_files_dir, role="analyzer", busy_wait=0.5)
    except Exception:
        return None
    if store is None:
        return None
    try:
        with store._reading():                  # one read: what the page draws is what it is signed with
            feed = store.read_feed()
            items = {row["id"]: {k: row.get(k) for k in _ITEM_FIELDS} for row in feed["items"]}
            works = {row["id"]: {k: row.get(k) for k in _WORK_FIELDS} for row in feed["works"]}
            epoch = feed.get("epoch")
            del feed                                # the rest of the feed (each item's ~40 fields) isn't held
            counted = [i for i, _tier in store.scheduled_ids()]
            order = _with_aside(counted, items)
            cards = {i: len(notes) for i, notes in store.cards_of(order).items() if notes}
            pre = {}
            reader = getattr(store, "prestudied_marks", None)        # J-STORE's reader (SPEC §2.2)
            try:                                                     # a seam that fails is its empty state, alone
                for item, mark in ((reader() or {}) if reader is not None else {}).items():
                    pre[item] = (mark[0], mark[1]) if isinstance(mark, (list, tuple)) else (mark, None)
            except Exception as e:
                pre = {}
                print(f"Warning: the journey couldn't read what was pre-studied: {e}")
            growth = {}
            grower = getattr(store, "growth_of", None)               # Kura-GS's reader (#585)
            try:
                if grower is not None:
                    growth = grower(order, kinds=("added", "done", "last")) or {}
            except Exception as e:
                growth = {}
                print(f"Warning: the journey couldn't read the growth snapshots: {e}")
            try:
                marks = store.watched_marks()
            except Exception:
                marks = library_store.UNREAD        # drawn, never signed as current (`analyzer.signed_render`)
        return StoreFacts(items, works, order, cards, pre, growth, str(epoch or ""), frozenset(counted), marks)
    except Exception as e:
        print(f"Warning: the journey couldn't read the library store: {e}")
        return None
    finally:
        try:
            store.close()
        except Exception:
            pass


def _with_aside(counted, items):
    """The study order with the watched items that don't count (set aside) in their place: each before the first
    counted item of its tier that the library orders after it, the rest at their tier's end."""
    tiers = {t: n for n, t in enumerate(KIND_TIERS)}
    place = {i: (tiers.get(items[i]["tier"], 9), items[i].get("ord") or 0, i) for i in counted if i in items}
    seen = set(counted)
    aside = sorted((place_of, i) for i, row in items.items()
                   if i not in seen and row.get("watched") and row.get("tier") in tiers
                   and row.get("availability") != "waiting"
                   for place_of in [(tiers[row["tier"]], row.get("ord") or 0, i)])
    out, k = [], 0
    for i in counted:
        at = place.get(i)
        while at is not None and k < len(aside) and aside[k][0][0] == at[0] and aside[k][0] < at:
            out.append(aside[k][1])
            k += 1
        while at is not None and k < len(aside) and aside[k][0][0] < at[0]:
            out.append(aside[k][1])
            k += 1
        out.append(i)
    out.extend(i for _p, i in aside[k:])
    return out


_NOTHING_NEW = namedtuple("_Status", "kind")("nothing")    # Connect's *Nothing new to mine* (`feed.NOTHING`), as a status


def nothing_new(language, path=None):
    """The items Connect mined with nothing new to make (`status.nothing`, Kura-NT) as a set — the rail draws them as
    the window does; empty with no Connect, no ledger or one that can't be read."""
    try:
        from app.connect import status
        return set(status.nothing(language, path))
    except Exception:
        return set()


def _stone_state(watched, cards, nothing=False):
    """The episode's stone — the seam J-STONES fills: `stone_plan.state_of` once it is public (one rule, never a copy),
    `stone_plan.tip_state` until then (cut · raw · nothing · rock). `nothing`: Connect mined it with nothing new to make
    (`nothing_new`), the status the window's rows hand the same rule."""
    from app.services import stone_plan
    ep = _Ep(bool(watched), cards, _NOTHING_NEW if nothing else None, False, False, True)
    state_of = getattr(stone_plan, "state_of", None)
    return state_of(ep) if state_of is not None else stone_plan.tip_state(ep)


def stone_pictures():
    """The stone pictures (SVG by state × size × gem × add) — J-STONES's `app/stone_shapes`; {} until it lands."""
    try:
        from app import stone_shapes
    except ImportError:
        return {}
    pictures = getattr(stone_shapes, "journey_pictures", None)
    try:
        return pictures() if pictures is not None else {}
    except Exception:
        return {}


def _pct(snap):
    return _known_pct(snap.get("known") or 0, snap.get("counted")) if snap else None


def _known_pct(known, counted):
    """*% known* as the window shows it (`view_rows.pct_of`: known tokens ÷ counted tokens, one number everywhere),
    to a tenth; None with nothing counted (never 0 %)."""
    from app.services.view_rows import pct_of
    pct = pct_of(known, counted)
    return None if pct is None else round(pct, 1)


def growth_row(snaps):
    """[added_pct, added_unknown, added_day, prior, done_pct, done_unknown, done_day, now_unknown] (each None when
    absent), or None with no snapshot at all (OPEN 43: never a made-up figure)."""
    if not snaps:
        return None
    added, done, last = (snap if snap and snap.get("counted") else None    # "0 of 0" (a file with no words): no bar
                         for snap in (snaps.get("added"), snaps.get("done"), snaps.get("last")))
    if not added and not done:
        return None
    return [_pct(added), added.get("unknown") if added else None, _day(added.get("at")) if added else None,
            (1 if added.get("prior") else 0) if added else None,
            _pct(done), done.get("unknown") if done else None, _day(done.get("at")) if done else None,
            last.get("unknown") if last else None]


# --- the sources a chunk names ----------------------------------------------------------------------------------- #

class Sources:
    """Each sentence's source as a chunk-local row [label, kind, ep, play, link] (never a path), and its ▶ times when
    the browser can play it — the old journey's helpers reused (`static_html_generator`: the source map, `_line_media`'s
    memo, the times-only `AnchorFinder`, `shown_name`, `_video_link`), so their memos stay one."""

    def __init__(self, language, source_map=None, ep_of=None, media=None, timer=None):
        self.language = language
        self.map = source_map or {}
        self.ep_of = ep_of or {}               # {an episode's key: its index} (`build`'s: its path, or an older
        self.by_path = False                    # run's lists, its name alone — `by_path` False)
        self.media = media or {}
        self.timer = timer
        self.titles = {}                        # {file name: its shown name}: the head's, so each is made once
        self.items = {}                         # {rel path: the store's item id}: a line id's first half
        self._rows = {}
        self.saved = False                      # the timer's memo written with every answer (`prepare`); a line
                                                # asked of the timer after it sets this back

    def row(self, rel):
        found = self._rows.get(rel)
        if found is None:
            from app.path_utils import report_name
            from app.static_html_generator import _video_link, shown_name
            meta = self.map.get(rel) or {}
            kind = meta.get("type") or "text"
            link = ""
            if kind in ("youtube", "bilibili"):
                try:
                    link = _video_link(rel, kind, None) or ""
                except Exception:
                    link = ""
            name = report_name(rel)
            play = (self.media.get(rel) or ("", ""))[0]
            title = self.titles.get(name)
            if title is None:
                title = self.titles[name] = shown_name(name)
            ep = self.ep_of.get(rel.replace("\\", "/") if self.by_path else name, -1)
            found = self._rows[rel] = [title, kind, ep, play, link, self.items.get(rel.replace("\\", "/"))]
        return found

    def prepare(self, texts, rels):
        """Each ▶ line's answer, the page's lines in its order (`texts[i]` said in `rels[i]`; "" no source): [the timer's
        memo answer — (start, end) made this render, [anchor, start, end] as read —, or None where nothing plays] — one memo lookup a line, so `build` reads the
        list rather than asking again (at 20,000 files a lookup costs ~3 µs: a second one was a slower warm render).
        A line the memo lacks is asked of the line reader a file at a time, and that file's lines let go before the
        next (J-TIMES: holding every subtitle's `cues.Timeline` to the render's end was 78 MB at 20,000 files); the
        folder listings the freshness check reads go once every file is checked (31 MB of entries). The same calls
        `times` makes, so the same answers and the same memo."""
        hits = [None] * len(texts)
        timer = self.timer
        # AnchorFinder's own (static_html_generator): each file's memo answers, its lines let go, the folder listings
        answers_in = getattr(timer, "answers", None)
        if answers_in is None:
            return hits
        answer = timer.answer
        media, smap = self.media, self.map
        answers_of, missing = {}, {}
        for i, rel in enumerate(rels):
            if not rel:
                continue
            answers = answers_of.get(rel)
            if answers is None:
                answers = answers_of[rel] = answers_in((smap.get(rel) or {}).get("abs") or rel) \
                    if (media.get(rel) or ("",))[0] else False
            if answers is False:
                continue
            hit = answers.get(texts[i])
            if answer(hit) is not None:
                hits[i] = hit                   # the memo's own answer (`build` reads its times: `AnchorFinder.answer`)
            else:
                missing.setdefault(rel, []).append(i)
        timer.forget_listings()                 # every file is checked: a later one lists its folder again
        for rel, lines in missing.items():
            answers = answers_of[rel]
            for i in lines:
                self.times(rel, texts[i])       # the line reader's answer, kept in `answers`
                hit = answers.get(texts[i])
                hits[i] = hit if answer(hit) is not None else None
            timer.forget((smap.get(rel) or {}).get("abs") or rel)
        # Written now, before the meanings and the pitch, rather than at the render's end: its one string (10 MB at
        # 20,000 files) was the first render's peak there. The same memo — `build` asks nothing more.
        save = getattr(timer, "save_memo", None)
        if save is not None:
            save()
            self.saved = True
        return hits

    def times(self, rel, sentence):
        if self.timer is None or not (self.media.get(rel) or ("",))[0]:
            return None, None
        meta = self.map.get(rel) or {}
        self.saved = False                      # a line `prepare` didn't ask: the memo is written again at the end
        try:
            return self.timer.times(meta.get("abs") or rel, sentence)
        except Exception:
            return None, None


# --- the render ---------------------------------------------------------------------------------------------------- #

Render = namedtuple("Render", "head chunks blobs stones")
#   head: dict · chunks: [bytes gz] · blobs: {name: bytes gz} · stones: dict


def _plan_files(plan, by_path=True):
    """{file's path: its index in the plan} (the plan's `files`, the counts table's: E-NAMES), what `_plan_pcts` and
    `_ahead` look a page's episode up by — `by_path` False (an older run's lists, names alone): {file name: a name's
    first file}; None without a plan."""
    if plan is None:
        return None
    try:
        from app.path_utils import report_name
        by_name = {}
        for f, entry in enumerate(plan.files):
            by_name.setdefault(entry[0] if by_path else report_name(entry[0]), f)
        return by_name
    except Exception:
        return None


def _plan_pcts(plan, by_name=None):
    """{file's key (`_plan_files`'): *% known*} from the plan's per-file `prog` (the tokens known before any file over
    the tokens counted) — the very count the window's rows read (`moves.Numbers`); None without a plan. `by_name`: `_plan_files`'
    (made here when not handed in)."""
    if plan is None:
        return None
    try:
        by_name = _plan_files(plan) if by_name is None else by_name
        progs = getattr(plan.per_file, "prog", None)     # the counts table's (`plan_engine.read_counts`): no line made
        out = {}
        for name, f in by_name.items():
            prog = progs(f) if progs is not None else plan.per_file[f]["prog"]
            out[name] = _known_pct(prog[1], prog[0])
        return out
    except Exception:
        return None


def _ahead(plan, names, word_eps, word_id, by_name=None):
    """Each page word's count ahead -> array, one number a word: its uses in its own episode and the next AHEAD - 1,
    from the plan's per-file counts (`plan_engine.Plan`, `Counts`), or -1 where its own episode has no count for it (no
    line in the plan, or the word not met there: the page then shows its count in its own episode); None without a
    plan. `names` the page's episodes' keys in order (`_plan_files`'), `word_eps` each word's episode index (in word
    order), `word_id` {(Word, Reading): its word index} (`build`'s); the plan's keys are distinct. At 20,000 files the
    {episode: {key: count}} dicts this was, and the asked sets that cut them, were 12.5 MB of the render's peak (J-CUT
    5's gate); here a window of AHEAD episodes' words at a time. `by_name`: `_plan_files`' (made here when not handed
    in)."""
    if plan is None:
        return None
    try:
        by_name = _plan_files(plan) if by_name is None else by_name
        n = len(word_eps)
        kw = array("i", [-1]) * n                  # each word's key in the plan
        for k, key in enumerate(plan.keys):
            wid = word_id.get((key[0], key[1]))
            if wid is not None and wid < n:
                kw[wid] = k
        out = array("i", [-1]) * n
        order = sorted(range(n), key=word_eps.__getitem__)
        lo = hi = 0
        for e, name in enumerate(names):
            while hi < n and word_eps[order[hi]] <= e:
                hi += 1
            while lo < hi and word_eps[order[lo]] <= e - AHEAD:
                lo += 1
            f = by_name.get(name) if lo < hi else None
            if f is None:
                continue
            line, uses = plan.per_file[f], {}
            for table in (line["main"], line["ph"]):
                for k, m in zip(table[0::2], table[1::2]):
                    uses[k] = uses.get(k, 0) + m
            for i in range(lo, hi):
                wid = order[i]
                m = uses.get(kw[wid]) if kw[wid] >= 0 else None
                if word_eps[wid] == e:
                    if m is not None:
                        out[wid] = m
                elif m and out[wid] >= 0:
                    out[wid] += m
        return out
    except Exception:
        return None


def build(language, rows, stats=(), priority=None, facts=None, settings=None, *, backlog=(), known=(), ranks=None,
          pitch=None, sources=None, plan=None, own=None, stamp=None, memo=None, nothing=(), silent=()):
    """The page's data (`Render`) from a Generate's outputs, every input given (`render` gathers them):
    `rows` the progressive list's records in order, `stats` file_statistics.json's entries in order, `priority` the
    priority list's records (*Most frequent first*; None: no such order), `facts` `store_facts`' (None: no store),
    `backlog` the Anki backlog's keys, `known` the learner's known terms, `pitch` a `Pitch`, `sources` a `Sources`,
    `plan` the plan file (the count ahead), `own` a callable [(word, reading)] -> {key: (title, text)} (Yours),
    `memo` a `WordMemo` (the meanings and pitch looked up last time; None: everything looked up), `nothing` the
    items Connect mined with nothing new to make (`nothing_new`: their stones), `silent` the shown lines no audio is
    heard from, {(Src, Context)} (`silent_lines`: each such line's 5th field is 1, the page's mark)."""
    settings = settings or {}
    logic = settings.get("logic") if isinstance(settings.get("logic"), dict) else {}
    shown_settings = page_settings(settings)
    per_word = shown_settings["sentences"]                         # 0 = All (the page's choice): every kept one
    meanings_mode = shown_settings["meanings"]
    thresholds = logic.get("priority_markers") if isinstance(logic.get("priority_markers"), dict) else {}
    from app.path_utils import infer_source_type, report_name
    from app.services import stone_plan

    # The episodes, in the study order: the store's (by id) when there is one, else the run's files. Each is told by
    # its path from the data folder (E-NAMES: the store's rel_path, the lists' Source Path, file statistics' Path), so
    # two shows' 第01集, both counted, keep their own words, *% known* and count ahead. An older run's lists name a file
    # by its name alone (`by_path` False): there a name is the episode the run COUNTED of that name, never a set-aside
    # one (J-FIX 3)
    stats = [s for s in (stats or ()) if isinstance(s, dict) and s.get("File")]
    first_row = next(iter(rows or ()), None)
    by_path = "Source Path" in first_row if first_row is not None else (not stats or "Path" in stats[0])

    def key_of(path, name):
        return (path or name) if by_path else name

    shows, show_index, eps, ep_keys, ep_of, aside = [], {}, [], [], {}, set()

    def show_of(key, title, kind):
        if key not in show_index:
            show_index[key] = len(shows)
            shows.append([key, title, kind, stone_plan.gem_of(kind if kind in stone_plan._KIND else None)])
        return show_index[key]

    # *% known*: the window's own figure (the plan's count), never the stats file's Coverage (%) — the plan when the
    # caller hands it in, else the store's 'last' snapshot (the same count, kept by that Generate); else none
    plan_files = _plan_files(plan, by_path)
    plan_pcts = _plan_pcts(plan, plan_files) if plan_files is not None else None

    def add_ep(item_id, name, key, tier, kind, show, watched, cards, missing, pre, growth, last=None, counted=True):
        coverage = plan_pcts.get(key) if plan_pcts is not None else _pct(last)
        flags = (1 if watched else 0) | (2 if missing else 0) | (4 if cards else 0)
        if key not in ep_of or (counted and ep_of[key] in aside):
            ep_of[key] = len(eps)
        if not counted:
            aside.add(len(eps))
        ep_keys.append(key)
        eps.append([item_id, name, None, show, tier, kind, coverage, 0, 0,
                    _stone_state(watched, cards, item_id is not None and item_id in nothing), flags, pre, growth])

    if facts is not None:
        from app import library_store
        from app.services.view_rows import _show_name
        tiers = {t: n for n, t in enumerate(KIND_TIERS)}
        for item_id in facts.order:
            item = facts.items.get(item_id)
            if item is None:
                continue
            work = facts.works.get(item.get("work_id")) or {}
            name = report_name(item["rel_path"])
            kind = work.get("media_type") or item.get("source_type") or infer_source_type(item["rel_path"])
            key = library_store._show_of(item_id, item.get("work_id"), item.get("parent_folder"))
            pre = facts.pre.get(item_id)
            add_ep(item_id, name, key_of(item["rel_path"].replace("\\", "/"), name), tiers.get(item.get("tier")),
                   kind, show_of(key, _show_name(work, item), kind), item.get("watched"), facts.cards.get(item_id, 0), item.get("availability") == "missing",
                   [_day(pre[0]) or pre[0], pre[1]] if pre else None, growth_row(facts.growth.get(item_id)),
                   (facts.growth.get(item_id) or {}).get("last"), facts.counted is None or item_id in facts.counted)
    named = set(ep_keys)
    for s in stats:
        key = key_of(s.get("Path"), s["File"])
        if key not in named:
            named.add(key)
            kind = infer_source_type(s["File"])
            add_ep(None, s["File"], key, None, kind, show_of(f"n{key}", s["File"], kind), False, 0, False, None, None)
    from app.static_html_generator import shown_name
    shown_name = memo.shown if memo is not None else shown_name      # (the last render's names, when it kept them)
    for n, e in enumerate(eps):
        e[2] = shown_name(e[1])
        if plan_pcts is not None and n in aside and ep_of[ep_keys[n]] != n:
            e[6] = None                         # the plan's figure is its counted namesake's (an older run's lists)

    # The words, each once, at the episode it is first met in
    by_file = {}
    for row in rows or ():
        by_file.setdefault(key_of(_text(row.get("Source Path")), _text(row.get("Source File"))), []).append(row)
    for key in by_file:
        if key not in ep_of:
            name = report_name(key)
            kind = infer_source_type(name)
            add_ep(None, name, key, None, kind, show_of(f"n{key}", name, kind), False, 0, False, None, None)
            eps[-1][2] = shown_name(name)
    owners = anki_owners(priority if priority is not None else (rows or ()), language) if backlog else {}
    keys = set(backlog or ())
    seen, words, word_rows, word_id = set(), [], [], {}
    for e, ep in enumerate(eps):
        ep[8] = len(words)
        for row in by_file.get(ep_keys[e], ()) if ep_of.get(ep_keys[e]) == e else ():
            key = (_text(row.get("Word")), _text(row.get("Reading")))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            word_id[key] = len(words)
            words.append((e, row))
        ep[7] = len(words) - ep[8]
    # The count ahead, one number a word: its uses in its own episode and the next AHEAD - 1
    names = [k if ep_of.get(k) == n else None for n, k in enumerate(ep_keys)]    # a set-aside namesake: none
    ahead = _ahead(plan, names, [e for e, _row in words], word_id, plan_files) if plan_files is not None else None
    del names
    del plan_files

    sources = sources or Sources(language)
    if not sources.ep_of:
        sources.ep_of, sources.by_path = ep_of, by_path     # each source's episode, as this head numbers them
    # Every word's lines, read once: [text] and [its source] side by side (a tuple a line held to the loop below was
    # 6 MB at 20,000 files), and each word's first line in them
    texts, rels, first = [], [], []
    for _e, row in words:
        first.append(len(texts))
        for text, rel in sentences_of(row, per_word):
            texts.append(text)
            rels.append(rel)
    first.append(len(texts))
    # The ▶ times before the meanings and the pitch: the heap the subtitles' reading grew is theirs to reuse
    try:
        hits = sources.prepare(texts, rels) or [None] * len(texts)
    except Exception:
        hits = [None] * len(texts)              # `times` then asks line by line

    meanings = Meanings(language, memo)
    if words:
        try:
            meanings.prepare([(_text(row.get("Word")), _text(row.get("Reading")), _text(row.get("Orth")))
                              for _e, row in words])
        except Exception as e:
            print(f"Warning: the journey's meanings couldn't be read: {e}")
            meanings = None
    pitch = pitch or Pitch(language)
    try:
        pitch.prepare([(_text(row.get("Word")), _text(row.get("Reading"))) for _e, row in words], memo)
    except Exception:
        pass                                    # `of` then asks word by word
    for e in eps:
        sources.titles.setdefault(e[1], e[2])
    if facts is not None and not sources.items:
        sources.items = {item["rel_path"]: item_id for item_id, item in facts.items.items() if item.get("rel_path")}

    # The chunks: at most CHUNK_EPISODES episodes or CHUNK_BYTES of JSON; one episode alone past it is split. Each
    # word and each source row is written as JSON and encoded once (its bytes are what the cap counts); a chunk is
    # their bytes joined (G11: each was encoded again in the chunk's text, each row's JSON written twice).
    chunks, ranges, glosses, chars = [], [], [], set()
    row_json = {}                       # {rel: its source row's JSON as UTF-8}: once a build, though each chunk lists it
    cur, cur_src, cur_rows, cur_bytes, cur_eps, cur_w0 = [], {}, [], 0, set(), 0

    def close():
        nonlocal cur, cur_src, cur_rows, cur_bytes, cur_eps, cur_w0
        if cur:
            text = b'{"w0":%d,"src":[%s],"w":[%s]}' % (cur_w0, b",".join(cur_rows), b",".join(cur))
            chunks.append(gzip.compress(text, GZIP_LEVEL, mtime=0))
            ranges.append([cur_w0, len(cur)])
        cur_w0 += len(cur)
        cur, cur_src, cur_rows, cur_bytes, cur_eps = [], {}, [], 0, set()

    def numbered(found_lines):
        """The word's lines with their sources numbered in the open chunk's table, and the sources it adds."""
        lines, added = [], {}
        for text, rel, at, end in found_lines:
            src = None
            if rel:
                src = cur_src.get(rel)
                if src is None:
                    src = added.get(rel)
                    if src is None:
                        src = added[rel] = len(cur_rows) + len(added)
            line = [text, src, at, end]
            if silent and (rel, text) in silent:
                line.append(1)                  # marked silent (SPEC § 4.5): its ▶ time, if any, stays where it is
            while line[-1] is None:
                line.pop()
            lines.append(line)
        return lines, added

    for wid, (e, row) in enumerate(words):
        if e not in cur_eps and len(cur_eps) >= CHUNK_EPISODES:
            close()
        word, orth, listed = _text(row.get("Word")), _text(row.get("Orth")), _text(row.get("Reading"))
        reading, key = listed, (word, listed)
        pinyin = ""
        if language == "zh" and meanings is not None:
            pinyin = meanings.pinyin(word) or meanings.pinyin(orth)
            reading = reading or pinyin
        found_lines = []
        for i in range(first[wid], first[wid + 1]):
            text, rel, hit = texts[i], rels[i], hits[i]
            if hit is None:
                hit = sources.times(rel, text) if rel else (None, None)
            elif type(hit) is not tuple:
                hit = hit[1], hit[2]            # [anchor, start, end], as the memo was read
            found_lines.append((text, rel) + hit)
        marks = marks_of(row, thresholds) | (8 if in_anki(row, keys, owners, language) else 0)
        here = ahead[wid] if ahead is not None else -1
        count = int(_num(row.get("Occurrences (File)"))) if here < 0 else here
        try:
            pitched = pitch.of(word, reading, pinyin)
        except Exception:
            pitched = None
        forms = [f for f in _text(row.get("Forms")).split("|") if f]
        record = [word, "" if orth == word else orth, reading, _text(row.get("Kana")), forms, e, marks, count,
                  pitched, None]
        def sized():
            """The word's JSON and that of the source rows it adds, as UTF-8, and their bytes together (the chunk's
            table counts)."""
            lines, added = numbered(found_lines)
            record[9] = lines
            text = _json(record).encode("utf-8")
            rows = [row_json[rel] if rel in row_json else row_json.setdefault(rel, _json(sources.row(rel)).encode("utf-8"))
                    for rel in added]           # (`numbered` adds them in their numbers' order)
            return text, added, rows, len(text) + sum(len(r) + 1 for r in rows)
        text, added, new_rows, size = sized()
        if cur and cur_bytes + size > CHUNK_BYTES:
            close()                             # its sources then go in the new chunk's table, numbered again
            text, added, new_rows, size = sized()
        for rel, source_row in zip(added, new_rows):
            cur_src[rel] = len(cur_rows)
            cur_rows.append(source_row)
        cur.append(text)
        cur_bytes += size
        cur_eps.add(e)
        if meanings is not None:
            found = meanings.of_json(word, listed, orth)
            if found:
                glosses.append(f'"{wid}":{found}')
        chars.update(_KANJI.findall(word + orth))
    close()

    blobs = {}
    if glosses:
        blobs["meanings"] = gzip.compress(("{" + ",".join(glosses) + "}").encode("utf-8"), GZIP_LEVEL, mtime=0)
    if language == "ja" and chars:
        try:
            kanji, near = Kanji(), known_with(chars, known, ranks)
            table = {}
            for ch in sorted(chars):
                entry = kanji.of(ch)
                if entry:
                    table[ch] = entry[:3] + [near.get(ch, "")]
            if table:
                blobs["kanji"] = _gz(table)
        except Exception as e:
            print(f"Warning: the journey's kanji couldn't be read: {e}")
    if meanings_mode != "en" and own is not None and words:
        try:
            keys_of = {(_text(r.get("Word")), _text(r.get("Reading"))): str(i) for i, (_e, r) in enumerate(words)}
            found = own(list(keys_of))
            if found:
                blobs["yours"] = _gz({keys_of[k]: list(v) for k, v in found.items() if k in keys_of})
        except Exception:
            pass                                # a private format: a failed read is English, quietly

    freq = None
    if priority is not None:
        freq = []
        for row in priority:
            wid = word_id.get((_text(row.get("Word")), _text(row.get("Reading"))))
            if wid is not None:
                freq.append(wid)
                word_id.pop((_text(row.get("Word")), _text(row.get("Reading"))))
    library = facts.library if facts is not None and facts.library else ""
    head = {"v": SHAPE, "minor": SHAPE_MINOR, "lang": language,
            "stamp": str(stamp if stamp is not None else time.time_ns() // 1_000_000),
            "library": library, "settings": shown_settings,
            "shows": shows, "eps": eps, "finished": [], "orders": {"freq": freq if freq is not None else []},
            "chunks": ranges, "dirs": [], "blobs": sorted(blobs),
            "counts": {"eps": len(eps), "words": len(words), "shows": len(shows),
                       "with_new": sum(1 for e in eps if e[7])}}
    return Render(head, chunks, blobs, stone_pictures())


ROW_COLUMNS = frozenset(("Source File", "Source Path", "Word", "Orth", "Forms", "Reading", "Kana", "Modality",
                         "Occurrences", "Occurrences (Global)", "Occurrences (File)", "Count (High)", "Count (Low)"))
PRIORITY_COLUMNS = frozenset(("Word", "Orth", "Forms", "Reading"))


def _records(path, columns=ROW_COLUMNS, contexts=True):
    """A list CSV's rows as dicts of the columns the page reads (`columns`, and every `Context n` / `Src n` with
    `contexts`), each cell its text ("" when empty: `_text` and `_num` read it as NaN was), or None when there is
    none. The csv module, not pandas: a word spelled like a number or like "NA" stays the word. A cell that repeats
    down the list (a source's path, a file's name, a count) is held once; a sentence never is looked for."""
    if not os.path.exists(path):
        return None
    from app.path_utils import list_reader
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = list_reader(f, header=False)    # the shared reader: its field limit raised (a long context)
        header = next(reader, None) or []
        keep = [(n, name, name.startswith("Context ")) for n, name in enumerate(header)
                if name in columns or (contexts and name.startswith(("Context ", "Src ")))]
        width = len(header)
        held = {}
        once = held.setdefault
        out = []
        for line in reader:
            if not line:                        # a blank line (a list ending in two newlines): no row
                continue
            if len(line) < width:
                line += [""] * (width - len(line))
            out.append({name: line[n] if sentence else once(line[n], line[n]) for n, name, sentence in keep})
        return out


def _known_terms(language, script="asis", store=None, settings=None):
    """The learner's known words as the list counts them — the known lemmas of its one known-word test
    (`analyzer.read_known_words`: KnownWord.json's known and carded entries, a sentence read into its words), the very
    sets the last Generate kept in the token store (`get_cached_known`), read only, never a second rule over the file.
    Sorted (the hover's last tie-break); [] with no store, or a file changed since that Generate (the next one reads it
    again: no hover word meanwhile, never a guess). `store`: the run's open token store (the redraw's: ONE-READ), read
    and left open; None: a reader of its own. `settings`: the run's one read, for the known-words key."""
    try:
        from app import token_index
        from app.path_utils import get_user_files_path
        held = store
        store = held or token_index.open_reader(language)
        if store is None:
            return []
        try:
            known_file = os.path.join(get_user_files_path(language), "KnownWord.json")
            cached = store.get_cached_known(token_index.known_signature(known_file, script), store.known_suffix(settings))
        finally:
            if store is not held:
                store.close()
        return sorted(cached[1]) if cached else []
    except Exception:
        return []


def render(language, rows=None, priority=None, stats=None, *, settings=None, facts=None, plan=None, tagger=None,
           stamp=None, known=None, store=None):
    """The page's data for this language's last Generate: the analyzer's rows in-process when it has them (G11), the
    results' CSVs otherwise; the store, the Anki backlog, the known words and the ▶'s memos read here, read-only.
    `known`: the run's known lemmas when the Generate hands them (the sets its list was decided by: no store opened
    for them, STORE-KEY 3 — so also when the store couldn't keep them, where the lookup found none), else read
    (`_known_terms`: through `store`, the run's open token store, when handed — the redraw's, ONE-READ)."""
    from app import settings_manager
    from app import static_html_generator as gen
    if settings is None:
        try:
            settings = settings_manager.load_settings()
        except Exception:
            settings = {}
    if rows is None:
        rows = _records(gen.PROGRESSIVE_CSV) or []
    if priority is None:
        priority = _records(gen.PRIORITY_CSV, PRIORITY_COLUMNS, contexts=False)
    if stats is None:
        try:
            with open(os.path.join(gen.RESULTS_DIR, "file_statistics.json"), encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            stats = []
    if facts is None:
        facts = store_facts(language)
    elif facts is False:                        # the caller's read found no store: never a second read (J-FIX 3)
        facts = None
    backlog = gen.anki_backlog_keys(language, settings, gen.PRIORITY_CSV)
    source_map = gen._load_source_map()
    rels = set()
    for row in rows:
        for column, rel in row.items():
            if rel and column.startswith("Src "):
                rels.add(str(rel))
    timed = {rel for rel in rels if isinstance(source_map.get(rel), dict)
             and source_map[rel].get("type") in gen.TIMED_TYPES}
    from app.zh_script import effective
    script = effective(language, settings.get("zh_script"))
    media, dirs, timer = {}, [], None
    if settings.get("line_player", True) and timed:
        from app.connect.runner import VIDEO_EXTENSIONS     # the one cutter's videos: the page cuts their lines (J-CLIP)
        media, dirs = gen._line_media(language, timed, os.path.join(gen.RESULTS_DIR, gen.LINE_MEDIA_MEMO),
                                      cut_kinds=VIDEO_EXTENSIONS)
        if any(where for where, _why in media.values()):
            timer = gen.AnchorFinder(cache_path=os.path.join(gen.RESULTS_DIR, gen.LINE_TIMES_MEMO),
                                     script=script, language=language)
    ranks = {}
    if language == "ja":
        try:
            from app import reference_data
            ranks = reference_data.spoken_ranks()
        except Exception:
            ranks = {}

    def own(keys):                              # Yours: `build` asks only when *Meanings* is not English
        from app import own_dicts
        return own_dicts.lookup(keys)
    memo = WordMemo(os.path.join(gen.RESULTS_DIR, WORD_MEMO), *memo_keys(language), names_key())
    sources = Sources(language, source_map, None, media, timer)
    out = build(language, rows, stats, priority, facts, settings, backlog=backlog,
                known=sorted(known) if known is not None else _known_terms(language, script, store, settings),
                ranks=ranks, pitch=Pitch(language, tagger), sources=sources,
                plan=plan, own=own, stamp=stamp, memo=memo, nothing=nothing_new(language),
                silent=silent_lines(gen.RESULTS_DIR, settings))
    out.head["dirs"] = dirs
    if timer is not None and not sources.saved:
        timer.save_memo()
    memo.save()
    if not out.head.get("library"):
        from app import library_store           # the store's own key (the scrub knows it as the install's)
        from app.path_utils import get_data_path
        out.head["library"] = library_store.library_key(get_data_path(language))
    return out


def silent_lines(results_dir, settings):
    """The shown lines no audio is heard from, {(Src, Context)}, as the list's one reader kept them beside the lines it
    showed (`analyzer.ListSentences.keep`, results/`SHOWN_FILE`'s "silent") — only while *Ensure an audio example* is
    on (SPEC § 4.5: they stay in their true order, marked silent) and the list is the reader's (release 2); set()
    otherwise, with none kept, or kept by another run than the plan's (a Generate whose reader kept nothing leaves the
    last one's: never its marks). Read here, not through the analyzer: a run's analyzer is `__main__`."""
    from app import plan_rules
    if plan_rules.SENTENCE_TABLE < 2 or not (settings or {}).get("ensure_audio_example"):
        return set()
    try:
        with gzip.open(os.path.join(results_dir, SHOWN_FILE), "rb") as f:
            data = json.loads(f.read())
        with gzip.open(os.path.join(results_dir, PLAN_FILE), "rb") as f:
            run = json.loads(f.readline()).get("run_signature")    # (its first line only: the header)
        if not run or data.get("run_signature") != run:
            return set()
        return {(_text(rel), _text(text)) for rel, text in data.get("silent") or ()}
    except Exception:
        return set()


# --- the page ------------------------------------------------------------------------------------------------------ #

def elements(out):
    """The page's data elements (SHAPE.md), in order, as text pieces: the head, the chunks, the blobs, the stones."""
    yield f'<script type="application/json" id="j-head">{_json(out.head)}</script>\n'
    for n, chunk in enumerate(out.chunks):
        yield f'<script type="application/gzip-base64" id="j-c{n}">{base64.b64encode(chunk).decode("ascii")}</script>\n'
    for name in sorted(out.blobs):
        yield (f'<script type="application/gzip-base64" id="j-{name}">'
               f'{base64.b64encode(out.blobs[name]).decode("ascii")}</script>\n')
    yield f'<script type="application/json" id="j-stones">{_json(out.stones)}</script>\n'


def write_page(out, template, path):
    """Write the page: `template` (the page's HTML, holding MARKER once) with the data in its place, in pieces (G5:
    never one joined string), to a temp file then replaced (a page open in a browser is never half written)."""
    at = template.find(MARKER)
    if at < 0 or template.find(MARKER, at + 1) >= 0:
        raise ValueError("the journey's template must hold its data marker once")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(template[:at])
        for piece in elements(out):
            f.write(piece)
        f.write(template[at + len(MARKER):])
    os.replace(tmp, path)
    return path
