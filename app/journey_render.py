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
import gzip
import hashlib
import json
import os
import time
from collections import namedtuple

SHAPE = 1                       # the shape's version (SHAPE.md); a change is a NOTE to the page first
MARKER = "<!--JOURNEY-DATA-->"  # where the page's template takes the data, once
CHUNK_EPISODES = 100
CHUNK_BYTES = 240_000           # a chunk's JSON closes past this (≈ 60–80 KB gzipped for Japanese sentences)
AHEAD = 3                       # "its count in the next few episodes": its own and the next two
GZIP_LEVEL = 6
MEANINGS = ("en", "yours_en", "yours")      # English · Yours, then English · Yours only (SPEC §1.4)
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

_Ep = namedtuple("_Ep", "watched cards status missing removed in_top")
StoreFacts = namedtuple("StoreFacts", "items works order cards pre growth library")
#   items {id: feed row} · works {id: row} · order [id] (the study order, set-aside watched items in their place) ·
#   cards {id: n} · pre {id: (day, by)} · growth {id: {kind: {...}}} · library: the queue's key (D31)


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
    value = _clean(value)
    return "" if value is None else str(value)


def _num(value, default=0):
    value = _clean(value)
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _json(obj):
    """UTF-8 JSON as the page reads it: never ASCII-escaped, never NaN (raises instead), `</` written `<\\/`."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("</", "<\\/")


def _gz(obj):
    return gzip.compress(_json(obj).encode("utf-8"), GZIP_LEVEL, mtime=0)


def _hira(text):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text or "")


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

def _table(module):
    import lzma
    return lzma.decompress(base64.b64decode("".join(module.DATA.split()))).decode("utf-8").split("\n")


class Meanings:
    """The shipped English meanings (app/gloss_ja_data.py · app/gloss_zh_data.py), read once a process and only for
    the words asked: `of(word, reading, orth)` -> [[pos, [gloss, …]], …] or None; `pinyin(word)` (zh) -> the first
    entry's pinyin."""
    _lines = {}

    def __init__(self, language):
        self.language = language
        self._index = None

    def _load(self, wanted):
        lines = Meanings._lines.get(self.language)
        if lines is None:
            if self.language == "ja":
                from app import gloss_ja_data as module
            else:
                from app import gloss_zh_data as module
            lines = Meanings._lines[self.language] = _table(module)
        index = {}
        for n, line in enumerate(lines):
            if self.language == "ja":
                kanji, readings, _rest = line.split("\t", 2)
                keys = (kanji.split(",") if kanji else []) + readings.split(",")
            else:
                simplified, traditional, _rest = line.split("\t", 2)
                keys = (simplified, traditional)
            for key in keys:
                if key in wanted:
                    index.setdefault(key, []).append(n)
        self._index = (lines, index)

    def prepare(self, words):
        """Index the table for these spellings only (a page's words and their spellings)."""
        self._load(set(words))

    def _entries(self, key):
        lines, index = self._index
        return [lines[n].split("\t") for n in index.get(key, ())]

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
            out.append([" · ".join(dict.fromkeys(POS_WORDS.get(p, p) for p in pos.split(";") if p)),
                        glosses.split("; ")])
        return out

    def pinyin(self, word):
        entry = self._pick(word, "", "")
        return entry[2] if entry else ""


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


def known_with(chars, known, ranks=None):
    """{kanji: the learner's most frequent known word holding it}: the known word with the best spoken rank
    (`reference_data.spoken_ranks`, 0 = unranked, last), then the shortest, then the first in the file."""
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
    """A word's pitch (SPEC §5.1, ruled r4): unidic-lite's `aType` for a word it knows as one token (a memo by word, so
    no engine bump); else Kanjium — the learner's own copy (`own_dicts.kanjium`) — else None, *No pitch data*, never
    平板. Chinese: the tones of its pinyin. `tagger`: the run's fugashi tagger (None: made on first ask)."""

    def __init__(self, language, tagger=None, kanjium=None):
        self.language = language
        self.tagger = tagger
        self.kanjium = kanjium
        self.memo = {}

    def _unidic(self, word, reading):
        if self.tagger is None:
            import fugashi
            self.tagger = fugashi.Tagger()
        nodes = [n for n in self.tagger(word)]
        if len(nodes) != 1:
            return None
        node = nodes[0]
        if getattr(node, "is_unk", False):
            return None
        feature = node.feature
        accent = getattr(feature, "aType", None)
        if not accent or accent == "*":
            return None
        kana = getattr(feature, "kana", None) or getattr(feature, "pron", None)
        if reading and kana and _hira(kana) != _hira(reading) and getattr(feature, "lemma", word) != word:
            return None
        return _digits(accent) or None

    def _kanjium(self, word, reading):
        if self.kanjium is None:
            from app import own_dicts
            self.kanjium = own_dicts.kanjium()
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
        if key not in self.memo:
            try:
                value = self._unidic(word, reading)
            except Exception:
                value = None
            if value is None:
                try:
                    value = self._kanjium(word, reading)
                except Exception:
                    value = None
            self.memo[key] = value
        return self.memo[key]


# --- the store's facts (read-only, through its own readers) ---------------------------------------------------------- #

def store_facts(language, data_dir=None, user_files_dir=None):
    """The episodes' facts from the library store, read in one go through its readers (`read_feed`, `scheduled_ids`,
    `cards_of`, and — once their lanes land — `prestudied_marks`, `growth_of`), or None with no ready store (the page
    then names episodes by file only). Never writes, never raises."""
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
        feed = store.read_feed()
        items = {row["id"]: row for row in feed["items"]}
        works = {row["id"]: row for row in feed["works"]}
        counted = [i for i, _tier in store.scheduled_ids()]
        order = _with_aside(counted, items)
        cards = {i: len(notes) for i, notes in store.cards_of(order).items() if notes}
        pre = {}
        reader = getattr(store, "prestudied_marks", None)        # J-STORE's reader (SPEC §2.2)
        if reader is not None:
            for item, mark in (reader() or {}).items():
                pre[item] = (mark[0], mark[1]) if isinstance(mark, (list, tuple)) else (mark, None)
        growth = {}
        grower = getattr(store, "growth_of", None)               # Kura-GS's reader (#585)
        if grower is not None:
            growth = grower(order, kinds=("added", "done", "last")) or {}
        return StoreFacts(items, works, order, cards, pre, growth, str(feed.get("epoch") or ""))
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


def _stone_state(watched, cards):
    """The episode's stone — the seam J-STONES fills: `stone_plan.state_of` once it is public (one rule, never a copy),
    `stone_plan.tip_state` until then (cut · raw · nothing · rock)."""
    from app.services import stone_plan
    ep = _Ep(bool(watched), cards, None, False, False, True)
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
    counted = snap.get("counted") if snap else None
    if not counted:
        return None
    return round(100.0 * (snap.get("known") or 0) / counted, 1)


def growth_row(snaps):
    """[added_pct, added_unknown, added_day, prior, done_pct, done_unknown, done_day, now_unknown] (each None when
    absent), or None with no snapshot at all (OPEN 43: never a made-up figure)."""
    if not snaps:
        return None
    added, done, last = snaps.get("added"), snaps.get("done"), snaps.get("last")
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
        self.ep_of = ep_of or {}
        self.media = media or {}
        self.timer = timer
        self._rows = {}

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
            found = self._rows[rel] = [shown_name(name), kind, self.ep_of.get(name, -1), play, link]
        return found

    def times(self, rel, sentence):
        if self.timer is None or not (self.media.get(rel) or ("",))[0]:
            return None, None
        meta = self.map.get(rel) or {}
        try:
            return self.timer.times(meta.get("abs") or rel, sentence)
        except Exception:
            return None, None


# --- the render ---------------------------------------------------------------------------------------------------- #

Render = namedtuple("Render", "head chunks blobs stones")
#   head: dict · chunks: [bytes gz] · blobs: {name: bytes gz} · stones: dict


def _ahead(plan, names):
    """{episode index: {(Word, Reading): count}} from the plan's per-file counts (`plan_engine.Plan`), for the
    episodes it holds; None without a plan (each word's count ahead is then its count in its own episode)."""
    if plan is None:
        return None
    try:
        from app.path_utils import report_name
        by_name = {}
        for f, entry in enumerate(plan.files):
            by_name.setdefault(report_name(entry[0]), f)
        keys = plan.keys
        out = {}
        for e, name in enumerate(names):
            f = by_name.get(name)
            if f is None:
                continue
            line = plan.per_file[f]
            counts = {}
            for table in (line["main"], line["ph"]):
                for k, n in zip(table[0::2], table[1::2]):
                    key = (keys[k][0], keys[k][1])
                    counts[key] = counts.get(key, 0) + n
            out[e] = counts
        return out
    except Exception:
        return None


def build(language, rows, stats=(), priority=None, facts=None, settings=None, *, backlog=(), known=(), ranks=None,
          pitch=None, sources=None, plan=None, own=None, stamp=None):
    """The page's data (`Render`) from a Generate's outputs, every input given (`render` gathers them):
    `rows` the progressive list's records in order, `stats` file_statistics.json's entries in order, `priority` the
    priority list's records (*Most frequent first*; None: no such order), `facts` `store_facts`' (None: no store),
    `backlog` the Anki backlog's keys, `known` the learner's known terms, `pitch` a `Pitch`, `sources` a `Sources`,
    `plan` the plan file (the count ahead), `own` a callable [(word, reading)] -> {key: (title, text)} (Yours)."""
    settings = settings or {}
    logic = settings.get("logic") if isinstance(settings.get("logic"), dict) else {}
    context = logic.get("context") if isinstance(logic.get("context"), dict) else {}
    try:
        per_word = max(1, int(context.get("max_contexts", 3)))
    except (TypeError, ValueError):
        per_word = 3
    meanings_mode = settings.get("journey_meanings", "en")
    if meanings_mode not in MEANINGS:
        meanings_mode = "en"
    thresholds = logic.get("priority_markers") if isinstance(logic.get("priority_markers"), dict) else {}
    from app.path_utils import infer_source_type, report_name
    from app.services import stone_plan

    # The episodes, in the study order: the store's (by id) when there is one, else the run's files by name
    stats = [s for s in (stats or ()) if isinstance(s, dict) and s.get("File")]
    stat_of = {}
    for s in stats:
        stat_of.setdefault(s["File"], s)
    shows, show_index, eps, ep_of_name = [], {}, [], {}

    def show_of(key, title, kind):
        if key not in show_index:
            show_index[key] = len(shows)
            shows.append([key, title, kind, stone_plan.gem_of(kind if kind in stone_plan._KIND else None)])
        return show_index[key]

    def add_ep(item_id, name, tier, kind, show, watched, cards, missing, pre, growth):
        stat = stat_of.get(name) or {}
        coverage = _clean(stat.get("Coverage (%)"))
        flags = (1 if watched else 0) | (2 if missing else 0) | (4 if cards else 0)
        ep_of_name.setdefault(name, len(eps))
        eps.append([item_id, name, None, show, tier, kind, coverage, 0, 0, _stone_state(watched, cards), flags,
                    pre, growth])

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
            add_ep(item_id, name, tiers.get(item.get("tier")), kind, show_of(key, _show_name(work, item), kind),
                   item.get("watched"), facts.cards.get(item_id, 0), item.get("availability") == "missing",
                   [_day(pre[0]) or pre[0], pre[1]] if pre else None, growth_row(facts.growth.get(item_id)))
    named = {e[1] for e in eps}
    for s in stats:
        if s["File"] not in named:
            named.add(s["File"])
            kind = infer_source_type(s["File"])
            add_ep(None, s["File"], None, kind, show_of(f"n{s['File']}", s["File"], kind), False, 0, False, None, None)
    from app.static_html_generator import shown_name
    for e in eps:
        e[2] = shown_name(e[1])

    # The words, each once, at the episode it is first met in
    by_file = {}
    for row in rows or ():
        by_file.setdefault(_text(row.get("Source File")), []).append(row)
    for name in by_file:
        if name not in ep_of_name:
            kind = infer_source_type(name)
            add_ep(None, name, None, kind, show_of(f"n{name}", name, kind), False, 0, False, None, None)
            eps[-1][2] = shown_name(name)
    ahead = _ahead(plan, [e[1] for e in eps])
    owners = anki_owners(priority if priority is not None else (rows or ()), language) if backlog else {}
    keys = set(backlog or ())
    seen, words, word_rows, word_id = set(), [], [], {}
    for e, ep in enumerate(eps):
        ep[8] = len(words)
        for row in by_file.get(ep[1], ()) if ep_of_name.get(ep[1]) == e else ():
            key = (_text(row.get("Word")), _text(row.get("Reading")))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            word_id[key] = len(words)
            words.append((e, row))
        ep[7] = len(words) - ep[8]

    meanings = Meanings(language)
    spellings = set()
    for _e, row in words:
        spellings.update(s for s in (_text(row.get("Word")), _text(row.get("Orth"))) if s)
    if words:
        try:
            meanings.prepare(spellings)
        except Exception as e:
            print(f"Warning: the journey's meanings couldn't be read: {e}")
            meanings = None
    pitch = pitch or Pitch(language)
    sources = sources or Sources(language)
    if not sources.ep_of:
        sources.ep_of = ep_of_name              # each source's episode, as this head numbers them

    # The chunks: at most CHUNK_EPISODES episodes or CHUNK_BYTES of JSON; one episode alone past it is split
    chunks, ranges, glosses, chars = [], [], {}, set()
    cur, cur_src, cur_rows, cur_bytes, cur_eps, cur_w0 = [], {}, [], 0, set(), 0

    def close():
        nonlocal cur, cur_src, cur_rows, cur_bytes, cur_eps, cur_w0
        if cur:
            chunks.append(_gz({"w0": cur_w0, "src": cur_rows, "w": cur}))
            ranges.append([cur_w0, len(cur)])
        cur_w0 += len(cur)
        cur, cur_src, cur_rows, cur_bytes, cur_eps = [], {}, [], 0, set()

    for wid, (e, row) in enumerate(words):
        if e not in cur_eps and len(cur_eps) >= CHUNK_EPISODES:
            close()
        word, orth, reading = _text(row.get("Word")), _text(row.get("Orth")), _text(row.get("Reading"))
        pinyin = ""
        if language == "zh" and meanings is not None:
            pinyin = meanings.pinyin(word) or meanings.pinyin(orth)
            reading = reading or pinyin
        found_lines = []
        for n in range(1, per_word + 1):
            text = _text(row.get(f"Context {n}"))
            if text:
                rel = _text(row.get(f"Src {n}"))
                found_lines.append((text, rel) + (sources.times(rel, text) if rel else (None, None)))
        marks = marks_of(row, thresholds) | (8 if in_anki(row, keys, owners, language) else 0)
        here = ahead.get(e, {}).get((word, _text(row.get("Reading")))) if ahead else None
        count = int(_num(row.get("Occurrences (File)"))) if here is None else sum(
            (ahead.get(e + d) or {}).get((word, _text(row.get("Reading"))), 0) for d in range(AHEAD))
        try:
            pitched = pitch.of(word, reading, pinyin)
        except Exception:
            pitched = None
        forms = [f for f in _text(row.get("Forms")).split("|") if f]
        record = [word, "" if orth == word else orth, reading, _text(row.get("Kana")), forms, e, marks, count,
                  pitched, [[text, 0 if rel else None, at, end] for text, rel, at, end in found_lines]]
        size = len(_json(record).encode("utf-8"))
        if cur and cur_bytes + size > CHUNK_BYTES:
            close()                             # before its sources are numbered: they go in the new chunk's table
        lines = []
        for text, rel, at, end in found_lines:
            src = None
            if rel:
                src = cur_src.get(rel)
                if src is None:
                    src = cur_src[rel] = len(cur_rows)
                    cur_rows.append(sources.row(rel))
            line = [text, src, at, end]
            while line[-1] is None:
                line.pop()
            lines.append(line)
        record[9] = lines
        cur.append(record)
        cur_bytes += size
        cur_eps.add(e)
        if meanings is not None:
            found = meanings.of(word, _text(row.get("Reading")), orth)
            if found:
                glosses[str(wid)] = found
        chars.update(ch for ch in word + orth if is_kanji(ch))
    close()

    blobs = {}
    if glosses:
        blobs["meanings"] = _gz(glosses)
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
    head = {"v": SHAPE, "lang": language, "stamp": str(stamp if stamp is not None else time.time_ns()),
            "library": library, "settings": {"sentences": per_word, "meanings": meanings_mode},
            "shows": shows, "eps": eps, "finished": [], "orders": {"freq": freq if freq is not None else []},
            "chunks": ranges, "dirs": [], "blobs": sorted(blobs),
            "counts": {"eps": len(eps), "words": len(words), "shows": len(shows),
                       "with_new": sum(1 for e in eps if e[7])}}
    return Render(head, chunks, blobs, stone_pictures())


def _records(path):
    """A list CSV's rows as dicts (NaN -> None), or None when there is none."""
    if not os.path.exists(path):
        return None
    import pandas as pd
    df = pd.read_csv(path)
    return [{k: _clean(v) for k, v in rec.items()} for rec in df.to_dict(orient="records")]


def _known_terms(language):
    """The learner's known terms, as KnownWord.json lists them (known, or with a card), in its order; [] when none."""
    try:
        from app.path_utils import get_user_files_path, read_text
        path = os.path.join(get_user_files_path(language), "KnownWord.json")
        if not os.path.exists(path):
            return []
        data = json.loads(read_text(path, language))
        entries = data.get("words", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        return [e.get("dictForm") for e in entries
                if isinstance(e, dict) and (e.get("knownStatus") == "KNOWN" or e.get("hasCard") == 1)
                and isinstance(e.get("dictForm"), str)]
    except Exception:
        return []


def render(language, rows=None, priority=None, stats=None, *, settings=None, facts=None, plan=None, tagger=None,
           stamp=None):
    """The page's data for this language's last Generate: the analyzer's rows in-process when it has them (G11), the
    results' CSVs otherwise; the store, the Anki backlog, the known words and the ▶'s memos read here, read-only."""
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
        priority = _records(gen.PRIORITY_CSV)
    if stats is None:
        try:
            with open(os.path.join(gen.RESULTS_DIR, "file_statistics.json"), encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            stats = []
    if facts is None:
        facts = store_facts(language)
    backlog = gen.anki_backlog_keys(language, settings, gen.PRIORITY_CSV)
    source_map = gen._load_source_map()
    rels = set()
    for row in rows:
        for n in range(1, 10):
            rel = row.get(f"Src {n}")
            if rel:
                rels.add(str(rel))
    timed = {rel for rel in rels if isinstance(source_map.get(rel), dict)
             and source_map[rel].get("type") in gen.TIMED_TYPES}
    media, dirs, timer = {}, [], None
    if settings.get("line_player", True) and timed:
        media, dirs = gen._line_media(language, timed, os.path.join(gen.RESULTS_DIR, gen.LINE_MEDIA_MEMO))
        if any(where for where, _why in media.values()):
            from app.zh_script import effective
            timer = gen.AnchorFinder(cache_path=os.path.join(gen.RESULTS_DIR, gen.LINE_TIMES_MEMO),
                                     script=effective(language, settings.get("zh_script")), language=language)
    ranks = {}
    if language == "ja":
        try:
            from app import reference_data
            ranks = reference_data.spoken_ranks()
        except Exception:
            ranks = {}
    own = None
    if settings.get("journey_meanings", "en") != "en":
        from app import own_dicts
        own = own_dicts.lookup
    out = build(language, rows, stats, priority, facts, settings, backlog=backlog, known=_known_terms(language),
                ranks=ranks, pitch=Pitch(language, tagger), sources=Sources(language, source_map, None, media, timer),
                plan=plan, own=own, stamp=stamp)
    out.head["dirs"] = dirs
    if timer is not None:
        timer.save_memo()
    if not out.head.get("library"):
        out.head["library"] = hashlib.sha1(os.path.abspath(gen.RESULTS_DIR).encode("utf-8")).hexdigest()[:12]
    return out


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
