"""Names are one word, not pieces (Settings -> Language & Parsing).

A name the dictionary lacks is cut by the tagger into pieces that are words or letters of their own — トゥー
(read ツー) + リ, グリム + ジョー, モーサ + ヤ — and the pieces then count as those words: a name's syllables fill the
head of the list, and a learner who knows ジョー meets グリムジョー as nothing new. `analyzer.join_affixes`, the one
place every Japanese caller reads words through, keeps such a name ONE word:

  Katakana names (logic.names_katakana) — Japanese-wide, no name list: a run of katakana the tagger cuts into
    pieces is ONE word when neither JPDB 2024 nor Jiten has a headword spelled like it and at least one piece is
    no common word (a name, a letter, a particle, a word the dictionary lacks: トゥー + リ, グリム + ジョー). A run
    of common words the lists don't carry as one (パーキング + スペース) stays in pieces, as a compound does; so does
    a run that is one piece repeated (ブンブン + ブンブン, アア + アッ) and a stutter — a piece cut off with ッ, then
    a word starting with the same sound (バッ + バカ).

  Names that recur in the library (logic.names_recurring) — a run of common words the katakana rule leaves in pieces
    (リム + ハイ, ヒラ + マン) is ONE word when the library keeps using it as one: its least-used piece is, as a word,
    at least 70% of the time inside this run ("stickiness"), and the run has 3+ uses. A run once joined stays joined
    until its stickiness falls below 50%, so a growing library doesn't make a name flicker in and out.

  Kanji names (logic.names_kanji) — a run of 2-5 tokens the tagger cuts (一 + 護, 赤 + 音, 巫 + 女子) whose whole
    spelling is a person's name in JMnedict (a surname or a given name) and no dictionary word, 8 characters at most,
    is ONE word where nothing says its pieces are words there: no piece is grammar (a particle, a verb, an adjective…
    — except a name's linking ノ / ヶ / 之 inside it: 卯ノ花), it doesn't start with a suffix or end with a prefix, a
    number in it comes with a person's name (夜 + 一) and none comes right before it (１０ + 円玉), it is not a name the
    tagger knows + a suffix (マリア + 様) or a plural suffix last (お光 + 達), and not a surname + a given name the
    tagger reads as such whose whole is no surname (宮崎 + 駿 is a full name, two words). JMnedict's long tail spells
    many chance meetings of two words, so the library decides too: the name joins once the library holds it 3+ times.

These use the whole library, not one sentence, so they are tables: at index time each file's candidates are recorded
in the token store (`Record`); after indexing the tables are computed (`compute_tables`) and stored there; and every
caller applies the same tables — join_affixes on live text (`join_library`), the token store on its cached tokens
(`apply_spans`). Before the first index, or with an empty library, there is no table and names split as the rules
above leave them. Library-made joins never reach shared data: the パターン builder and the reference-data build read
text without them (join_affixes(..., library=False)).

A joined name is keyed as the tagger keys that spelling when it reads it whole: as that word, when the tagger reads
the spelling alone as one word it knows (so a name read whole in one sentence and cut in the next is one row); else
as a word its dictionary lacks — the spelling as the lemma, no reading (never the pieces' readings run together).
"""
import hashlib
import json
import re
import time
from array import array
from bisect import bisect_left
from collections import Counter, namedtuple
from itertools import accumulate

from app.unicode_ranges import HAN

# Katakana letters, ー and the iteration marks ヽヾ — never ・, which separates the parts of a name.
_KATAKANA = re.compile(r"^[ァ-ヺー-ヾ]+$")
_KATAKANA_TEXT = re.compile(r"[ァ-ヺー-ヾ]+")
# Any katakana in a line's text (half-width too, which is read as katakana): most lines hold none, and skip the rest.
_ANY_KATAKANA = re.compile("[ァ-ヺー-ヾ\uff66-\uff9f]")
# What stays in pieces whatever the run: the marks the tagger leaves at a run's ends (ダメーーッ is ダメ + marks).
_MARKS = "補助記号"

_katakana_headwords = []    # [Spellings] once read; [None] when the table can't be read
_person_names = []          # [PersonNames] once read (only where files are indexed); [None] when it can't be read
_whole = {}                 # spelling -> the tagger's feature for it read alone as one known word, or None
_tagger = []                # the tagger that reads a spelling alone, made on the first join

# Names that recur in the library.
STICKY = 0.7        # a run joins once this share of its least-used piece's uses (as a word) are inside it...
KEEP = 0.5          # ...and, joined, stays joined down to this share: a growing library doesn't flip it back and forth
FLOOR = 3           # uses in the library before a run can join (a coincidence rarely recurs)
REFRESH = 30.0      # seconds: how often a long-lived process (the dashboard, Junban) looks for newer tables

# Kanji names.
SURNAME, GIVEN = 1, 2
_HAN = re.compile(f"[{HAN}]")
_NOT_IN_A_NAME = frozenset(("助詞", "助動詞", "動詞", "形容詞", "連体詞", "代名詞", "接続詞", "感動詞"))
_NAME_LINKS = frozenset(("ノ", "ヶ", "ケ", "之"))
_BREAKS = ("補助記号", "空白")
_NO_START = frozenset(_BREAKS) | _NOT_IN_A_NAME | {"接尾辞"}     # what no name starts with (kanji_name's guards)
_library = {"tables": None, "at": None, "pinned": False}


class Spellings:
    """A set of spellings kept as the sorted hashes of their text, looked up by bisection: a few MB for hundreds of
    thousands of spellings where a set of strings takes tens. The hashes are this process's own (made as the table is
    read), so nothing is stored but the spellings."""
    __slots__ = ("_keys",)

    def __init__(self, spellings):
        self._keys = array("q", sorted(map(hash, spellings)))

    def __contains__(self, text):
        keys, key = self._keys, hash(text)
        at = bisect_left(keys, key)
        return at < len(keys) and keys[at] == key

    def __len__(self):
        return len(self._keys)


class PersonNames:
    """JMnedict's surnames and given names: `get(spelling)` -> its bits (1 a surname, 2 a given name), 0 for none."""
    __slots__ = ("_surnames", "_given")

    def __init__(self, surnames, given):
        self._surnames, self._given = Spellings(surnames), Spellings(given)

    def starts(self, text):
        return True             # a name can start with anything: the search leans on the guards instead

    def get(self, text):
        return (SURNAME if text in self._surnames else 0) | (GIVEN if text in self._given else 0)


class _Names(dict):
    """A library table's kanji names ({spelling: bits}) with every shorter start of one (0), for live text: a run whose
    spelling so far starts no name stops there; `get` is None for such a spelling."""

    def starts(self, text):
        return text in self


def katakana_headwords():
    """Every kana headword of JPDB 2024 and Jiten, in katakana (app/katakana_data.py), as `Spellings` — or None when
    the table can't be read: then no katakana run is joined (a missing table must never make every run a name)."""
    if not _katakana_headwords:
        try:
            from app import katakana_data
            _katakana_headwords.append(Spellings(katakana_data.katakana_headwords()))
        except Exception:
            _katakana_headwords.append(None)
    return _katakana_headwords[0]


def person_names():
    """JMnedict's surnames and given names with a kanji that are no dictionary word (app/name_data.py), as
    `PersonNames` — read only where files are indexed (the token store records the candidates; a process that only
    applies a library's tables never reads it); None when the table can't be read: no kanji run is then a
    candidate."""
    if not _person_names:
        try:
            from app import name_data
            _person_names.append(PersonNames(name_data.surnames(), name_data.given_names()))
        except Exception:
            _person_names.append(None)
    return _person_names[0]


def _read(word):
    """A node's text as the tagger read it (analyzer._read): ﾄｩｰﾘ is read トゥーリ."""
    return word.feature.orth or word.surface


def katakana_runs(words):
    """(start, end) of every run of two or more tokens written only in katakana with nothing between them, trimmed of
    the marks the tagger leaves at its ends. Found in the line's text as read, then mapped back to its tokens: the
    tokens wholly inside a stretch of katakana."""
    texts = [w.feature.orth or w.surface for w in words]
    line = "".join(texts)
    if not _KATAKANA_TEXT.search(line):
        return
    ends = list(accumulate(map(len, texts)))
    for m in _KATAKANA_TEXT.finditer(line):
        start, end = m.span()
        i = bisect_left(ends, start + 1)                # the token the stretch starts in...
        if ends[i] - len(texts[i]) < start:
            i += 1                                      # ...only in part: not a katakana token
        j = bisect_left(ends, end)                      # the token it ends in
        if j >= len(ends) or ends[j] > end:
            j -= 1                                      # ...only in part
        while i <= j:                                   # tokens i..j are katakana; a space keeps two apart
            k = i + 1
            while k <= j and not getattr(words[k], "white_space", ""):
                k += 1
            a, b = i, k
            while a < b and words[a].feature.pos1 == _MARKS:
                a += 1
            while b > a and words[b - 1].feature.pos1 == _MARKS:
                b -= 1
            if b - a >= 2:
                yield a, b
            i = k


def _common_word(word, listed):
    """A piece the tagger reads as a common word: a 普通名詞 or a な-word its dictionary knows, two letters or more,
    spelled as a headword of the lists (パーキング, スペース) — not a name (グリム), a letter (リ), a particle, a symbol
    or a word the dictionary lacks."""
    f = word.feature
    text = _read(word)
    return (((f.pos1 == "名詞" and f.pos2 == "普通名詞") or f.pos1 == "形状詞") and not word.is_unk
            and len(text) >= 2 and text in listed)


def repeated(pieces):
    """One piece repeated — ブンブン + ブンブン, ワン + ワン + ワン, アア + アッ: the run, less a final ッ or ー, is one
    unit written twice or more. A sound, not a name."""
    spelling = "".join(pieces).rstrip("ッー")
    n = len(spelling)
    return n >= 2 and any(n % k == 0 and spelling == spelling[:k] * (n // k) for k in range(1, n // 2 + 1))


def stutter(pieces):
    """A stutter: a piece cut off with ッ, then a word starting with the same sound — バッ + バカ, ヤッ + ヤバイ, or the
    ッ a token of its own (バ + ッ + バカ)."""
    for k in range(len(pieces) - 1):
        piece = pieces[k]
        if piece.endswith("ッ") and len(piece) > 1:
            stem = piece[:-1]
        elif piece == "ッ" and k:
            stem = pieces[k - 1]
        else:
            continue
        if stem and pieces[k + 1].startswith(stem):
            return True
    return False


def katakana_kind(run, listed):
    """What a katakana run is: "listed" (a headword spells it: the word it is), "common" (only common words the lists
    don't carry as one: a compound, in pieces), "sound" (one piece repeated, or a stutter: in pieces) or "name" (one
    word)."""
    pieces = [_read(t) for t in run]
    if "".join(pieces) in listed:
        return "listed"
    if all(_common_word(t, listed) for t in run):
        return "common"
    if repeated(pieces) or stutter(pieces):
        return "sound"
    return "name"


def _read_whole(spelling):
    """The tagger's feature for `spelling` read alone, when it reads it as ONE word its dictionary knows — else None.
    Asked once per spelling."""
    if spelling not in _whole:
        from app.analyzer import Tagger, word_lemma
        if not _tagger:
            _tagger.append(Tagger())
        nodes = _tagger[0](spelling)
        _whole[spelling] = (nodes[0].feature if len(nodes) == 1 and not nodes[0].is_unk
                            and word_lemma(nodes[0]) is not None else None)
    return _whole[spelling]


def one_word(run):
    """`run` (its tokens) as ONE word (§ above): the word the tagger reads the spelling as alone, or — when it cuts it
    alone too, or doesn't know it — a word its dictionary lacks: the spelling (as read) is the lemma, there is no
    reading, it is unknown."""
    from app.analyzer import JoinedWord, _joined
    spelling = "".join(_read(t) for t in run)
    whole = _read_whole(spelling)
    if whole is not None:
        return JoinedWord("".join(t.surface for t in run), whole, tuple((t.surface, t.feature) for t in run))
    word = _joined(run, spelling, "名詞", (spelling, ""))
    word.is_unk = True
    return word


def _has_katakana(words):
    return _ANY_KATAKANA.search("".join([w.surface for w in words])) is not None


def join_katakana(words):
    """`words` — one tagger call's tokens, after the affix joins — with every katakana name made one word (§ above)."""
    listed = katakana_headwords()
    if not listed or not _has_katakana(words):
        return words
    out, last = [], 0
    for a, b in katakana_runs(words):
        if katakana_kind(words[a:b], listed) != "name":
            continue
        out.extend(words[last:a])
        out.append(one_word(words[a:b]))
        last = b
    if not last:
        return words
    out.extend(words[last:])
    return out


# --- Names from the whole library: the tables ----------------------------------------------------------------------- #
Candidate = namedtuple("Candidate", "i j kind spelling pieces")     # kind: "k" katakana, "j" kanji


def _number(word):
    return word.feature.pos2 == "数詞" or word.surface.isdigit()


def kanji_name(run, bits):
    """Is `run` (2-5 tokens spelling a person's name, `bits` its lists) ONE name here? The guards (§ above)."""
    first, last = run[0].feature, run[-1].feature
    if first.pos1 == "接尾辞" or last.pos1 == "接頭辞":
        return False
    for k, t in enumerate(run):
        if t.feature.pos1 in _NOT_IN_A_NAME and not (0 < k < len(run) - 1 and t.surface in _NAME_LINKS):
            return False
    if any(t.feature.pos2 == "数詞" for t in run) and not any(t.feature.pos3 == "人名" for t in run):
        return False
    if last.pos1 == "接尾辞":
        from app.analyzer import _NEVER_JOINED
        if all(t.feature.pos3 == "人名" for t in run[:-1]) or run[-1].surface in _NEVER_JOINED:
            return False
    if (first.pos3 == "人名" and first.pos4 == "姓" and not bits & SURNAME
            and any(t.feature.pos3 == "人名" and t.feature.pos4 == "名" for t in run[1:])):
        return False
    return True


def kanji_candidates(words, table):
    """Every run of 2-5 of `words` (8 characters at most, a kanji in it) that `table` (JMnedict's `PersonNames`, or a
    library table's `_Names`) spells and the guards let be one name — every one, overlapping ones too: `choose` takes
    the longest from the left. The guards' cheap tests come first, so only a run that can still be a name is looked
    up: no run starts at grammar or a suffix, or after a number, and none goes on through grammar but a name's
    linking ノ / ヶ / 之."""
    out, n = [], len(words)
    features = [w.feature for w in words]
    pos1s = [f.pos1 for f in features]
    starts = table.starts
    for i in range(n):
        if pos1s[i] in _NO_START or (i and _number(words[i - 1])):
            continue
        spelling = features[i].orth or words[i].surface
        if not starts(spelling):
            continue
        for j in range(i + 1, min(n, i + 5)):
            t, pos1 = words[j], pos1s[j]
            link = pos1 in _NOT_IN_A_NAME
            if pos1 in _BREAKS or (link and t.surface not in _NAME_LINKS) or getattr(t, "white_space", ""):
                break
            spelling += features[j].orth or t.surface
            if len(spelling) > 8:
                break
            if link or not _HAN.search(spelling):   # not a name yet (a link ends none; a name holds a kanji)
                if not table.starts(spelling):
                    break
                continue
            bits = table.get(spelling)
            if bits is None:
                break                               # no name starts so: no longer run is one either
            if bits and kanji_name(words[i:j + 1], bits):
                out.append(Candidate(i, j + 1, "j", spelling, None))
    return out


def candidates(words, kanji=None):
    """Every run in one tagger call's tokens (after the katakana rule) that a library table could make one word: each
    katakana run of common words the rule leaves in pieces, and — with `kanji`, a names table (`kanji_candidates`) —
    each kanji run spelled as one of its names."""
    out = []
    listed = katakana_headwords()
    if listed and _has_katakana(words):
        for a, b in katakana_runs(words):
            run = words[a:b]
            if katakana_kind(run, listed) == "common":
                pieces = tuple(_read(t) for t in run)
                out.append(Candidate(a, b, "k", "".join(pieces), pieces))
    if kanji:
        out.extend(kanji_candidates(words, kanji))
    return out


def _longest_from_left(cands, taken=()):
    """Of kanji candidates, the ones read as names: at each start the longest, then on past its end — none
    overlapping a run in `taken` ((start, end) pairs)."""
    out, end = [], 0
    for c in sorted(cands, key=lambda c: (c.i, -c.j)):
        if c.i < end or any(c.i < b and a < c.j for a, b in taken):
            continue
        out.append(c)
        end = c.j
    return out


def choose(cands, tables, recurring=True, kanji=True):
    """The candidates the tables make one word, in order: every katakana run the recurring table holds, then the
    kanji runs the kanji table holds, the longest from the left, overlapping none of those."""
    chosen = [c for c in cands if c.kind == "k" and recurring and c.spelling in tables.get("k", ())]
    if kanji and tables.get("j"):
        chosen += _longest_from_left([c for c in cands if c.kind == "j" and c.spelling in tables["j"]],
                                     [(c.i, c.j) for c in chosen])
    return sorted(chosen)


_gates = {}


def _gate(tables):
    """The kanji table's names, searchable, for live text — made once per table."""
    key = (tables.get("stamp"), id(tables["j"]))
    if key not in _gates:
        _gates.clear()
        names = _Names((spelling, entry[0]) for spelling, entry in tables["j"].items())
        for spelling in tables["j"]:
            for k in range(1, len(spelling)):
                names.setdefault(spelling[:k], 0)
        _gates[key] = names
    return _gates[key]


def join_library(words, recurring=True, kanji=True):
    """`words` with every run the library's tables name made one word (§ above) — as they are when there is no table
    yet, or both switches are off."""
    tables = library_tables()
    if not tables or not ((recurring and tables.get("k")) or (kanji and tables.get("j"))):
        return words
    gate = _gate(tables) if kanji and tables.get("j") else None
    chosen = choose(candidates(words, gate), tables, recurring, kanji)
    if not chosen:
        return words
    out, last = [], 0
    for c in chosen:
        out.extend(words[last:c.i])
        out.append(one_word(words[c.i:c.j]))
        last = c.j
    out.extend(words[last:])
    return out


def key_of(spelling, sanitize=None):
    """(lemma, reading, orth) of `spelling` made one word (`one_word`), as the tokenizer keys it — for the token
    store's cached tokens, which hold no tagger nodes. `sanitize` is the analyzer's lemma cleaning (a Japanese run)."""
    whole = _read_whole(spelling)
    if whole is None:
        lemma, reading, orth = spelling, "", spelling
    else:
        lemma, reading, orth = whole.lemma or spelling, whole.lForm or whole.kana or "", whole.orthBase or spelling
    return (sanitize(lemma), reading, sanitize(orth)) if sanitize else (lemma, reading, orth)


class Record:
    """What one file tells the library's tables, gathered as the token store tokenizes it (JapaneseTokenizer with
    `names=`): every candidate run with where it sits among its sentence's counted tokens ("s"), how often each
    katakana run is used in pieces and by which pieces ("ks") and whole ("k1"), how often each katakana word of two
    letters or more is used as a token ("p") — a piece's uses as a word — and how often each kanji name is read,
    the longest from the left ("jc", with its lists' bits in "jb")."""

    def __init__(self):
        self.spans, self.ks, self.k1, self.p = [], {}, Counter(), Counter()
        self.jc, self.jb = Counter(), {}

    def read_line(self, words):
        """The candidates of one tagger call's tokens (after the katakana rule), counted."""
        from app.analyzer import JoinedWord
        if _has_katakana(words):
            p, k1, katakana = self.p, self.k1, _KATAKANA.match
            for w in words:
                text = w.feature.orth or w.surface
                if len(text) >= 2 and katakana(text):
                    p[text] += 1
                    if isinstance(w, JoinedWord):
                        k1[text] += 1
        persons = person_names()
        cands = candidates(words, persons)
        for c in cands:
            if c.kind == "k":
                self.ks.setdefault(c.spelling, Counter())["|".join(c.pieces)] += 1
        for c in _longest_from_left([c for c in cands if c.kind == "j"]):
            self.jc[c.spelling] += 1
            self.jb[c.spelling] = persons.get(c.spelling)
        return cands

    def span(self, sentence, cand, a, b, surface):
        """Candidate `cand` sits in yielded sentence `sentence`, over its counted tokens [a, b), written `surface`."""
        self.spans.append([sentence, cand.i, cand.j, a, b, cand.kind, cand.spelling,
                           surface if surface != cand.spelling else 0])

    def data(self):
        return {"s": self.spans, "ks": self.ks, "k1": self.k1, "p": self.p, "jc": self.jc, "jb": self.jb}


def compute_tables(records, previous=None, sanitize=None):
    """The library's tables from every file's `Record` data (`records`, an iterable of dicts): {"k": {spelling:
    [stickiness, lemma, reading, orth]}, "j": {spelling: [bits, lemma, reading, orth]}, "stamp": …} — a katakana run
    joins at STICKY with FLOOR uses, and a run in `previous` (the last tables) stays while its stickiness is KEEP or
    more; a kanji name joins with FLOOR uses."""
    uses, segs, pieces, kanji_uses, kanji_bits = Counter(), {}, Counter(), Counter(), {}
    for data in records:
        pieces.update(data.get("p", {}))
        uses.update(data.get("k1", {}))
        kanji_uses.update(data.get("jc", {}))
        kanji_bits.update(data.get("jb", {}))
        for spelling, by_pieces in data.get("ks", {}).items():
            for joined_pieces, n in by_pieces.items():
                uses[spelling] += n
                segs.setdefault(spelling, set()).add(joined_pieces)
    before = (previous or {}).get("k", {})
    katakana = {}
    for spelling, ways in segs.items():
        stick = 0.0
        for way in ways:
            least = min(pieces[p] for p in way.split("|"))
            if least > 0:
                stick = max(stick, min(1.0, uses[spelling] / least))
        if (stick >= STICKY and uses[spelling] >= FLOOR) or (spelling in before and stick >= KEEP):
            katakana[spelling] = [round(stick, 3), *key_of(spelling, sanitize)]
    kanji = {spelling: [kanji_bits.get(spelling, 0), *key_of(spelling, sanitize)]
             for spelling, n in kanji_uses.items() if n >= FLOOR}
    tables = {"k": katakana, "j": kanji}
    tables["stamp"] = hashlib.sha1(json.dumps(tables, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return tables


def chosen(sentences, spans, tables, recurring=True, kanji=True):
    """The joins `apply_spans` makes, without making them: (sentence, a, b, [lemma, reading, surface, orth]) for every
    recorded span the tables choose — tokens a..b of that sentence become the one token. Each sentence's joins come in
    order and never overlap."""
    by_sentence = {}
    for s, i, j, a, b, kind, spelling, surface in spans:
        by_sentence.setdefault(s, []).append(Candidate(i, j, kind, spelling, (a, b, surface or spelling)))
    for s, cands in by_sentence.items():
        if s >= len(sentences):
            continue
        for c in choose(cands, tables, recurring, kanji):
            a, b, surface = c.pieces
            lemma, reading, orth = tables[c.kind][c.spelling][1:]
            yield s, a, b, [lemma, reading, surface, orth]


def apply_spans(sentences, spans, tables, recurring=True, kanji=True):
    """The token store's cached `sentences` ([text, [[lemma, reading, surface, orth], …]], as recorded) with every
    recorded span the tables choose made one token — the same choice `join_library` makes on live text."""
    for s, a, b, token in reversed(list(chosen(sentences, spans, tables, recurring, kanji))):
        sentences[s][1][a:b] = [token]
    return sentences


def library_tables():
    """The library's tables this process applies: those the last index stored in the Japanese token store (read
    again every REFRESH seconds, so a window open across a Generate picks up the new ones), or those a caller set
    (`use_library_tables`). None before the first index."""
    if not _library["pinned"]:
        now = time.monotonic()
        if _library["at"] is None or now - _library["at"] > REFRESH:
            _library["at"] = now
            try:
                from app import token_index
                _library["tables"] = token_index.read_names_tables("ja")
            except Exception:
                _library["tables"] = None
    return _library["tables"]


def use_library_tables(tables, pin=False):
    """Apply `tables` in this process from now on — the ones an index just computed; `pin`: never read the store for
    newer ones (a measurement that must not move)."""
    _library.update(tables=tables, at=time.monotonic(), pinned=pin)


def forget_library_tables():
    """Back to reading the tables from the token store on next use."""
    _library.update(tables=None, at=None, pinned=False)
