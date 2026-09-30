"""Names are one word, not pieces (Settings -> Language & Parsing).

A name the dictionary lacks is cut by the tagger into pieces that are words or letters of their own — トゥー
(read ツー) + リ, グリム + ジョー, モーサ + ヤ — and the pieces then count as those words: a name's syllables fill the
head of the list, and a learner who knows ジョー meets グリムジョー as nothing new. `analyzer.join_affixes`, the one
place every Japanese caller reads words through, keeps such a name ONE word:

  Katakana names (logic.names_katakana) — Japanese-wide, no name list: a run of katakana the tagger cuts into
    pieces is ONE word when neither JPDB 2024 nor Jiten has a headword spelled like it and at least one piece is
    no common word (a name, a letter, a particle, a word the dictionary lacks: トゥー + リ, グリム + ジョー). A run
    of common words the lists don't carry as one (パーキング + スペース) stays in pieces, as a compound does; so does
    a run that is one piece repeated (ブンブン + ブンブン, アア + アッ), a stutter — a piece cut off with ッ, then
    a word starting with the same sound (バッ + バカ) — and a run made only of interjections, every piece one the
    tagger reads as an interjection (アッ + ハハ, ウワ + アア): laughter and cries, not a name. A run a headword
    spells is that dictionary word: the compound and affix joins make it one where their tables hold it; where they
    don't (a word too rare for them), it is one word as an unlisted run is, when a piece is no common word (ブ, read
    as the prefix 無, + シン: the word ブシン). A run's last piece that heads a word the text goes on writing in
    hiragana is that word's, not the name's: サクサク + ジャ + がいも is サクサク and ジャがいも (ジャガイモ, a headword).

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

  A work's own kanji terms (logic.names_work_terms) — a story coins kanji words no dictionary holds (斬魄刀, 霊圧,
    写輪眼) and names the names dictionary lacks, and the tagger cuts them into single kanji (斬 + 魄 + 刀). A run of
    two or more tokens read as one kanji each (a word, a number or a kanji the tagger reads as a symbol) that the
    rules above leave in pieces is ONE word when the library keeps using it as one — the katakana gauge: its uses are
    at least 70% of the uses of its least-used kanji standing alone, with 3+ uses, and once joined it stays until that
    falls below 50% — and nothing says it is words: no piece is grammar (a name's linking 之 aside, as above), it
    doesn't end in an honorific, a plural or a position word (谷 + 君, 前), it is not numbers alone, and no
    dictionary lists the spelling — JMdict (鄭寧 is Sōseki's 丁寧), the compound and affix joins, a kanji name.
    Transcripts whose captions YouTube generated count toward nothing (the captioner misspells a word the same way
    every time), though a term joins there too.

These use the whole library, not one sentence, so they are tables: at index time each file's candidates are recorded
in the token store (`Record`); after indexing the tables are computed (`compute_tables`) and stored there; and every
caller applies the same tables — join_affixes on live text (`join_library`), the token store on its cached tokens
(`apply_spans`). Before the first index, or with an empty library, there is no table and names split as the rules
above leave them. Library-made joins never reach shared data: the パターン builder and the reference-data build read
text without them (join_affixes(..., library=False)).

A joined name is keyed as the tagger keys that spelling when it reads it whole: as that word, when the tagger reads
the spelling alone as one word it knows (so a name read whole in one sentence and cut in the next is one row); else
as a word its dictionary lacks — the spelling as the lemma, no reading (never the pieces' readings run together).

Ignore names (logic.ignore_names, off by default) — a learner still learns names, unless they choose not to: then a
name is an ignored word everywhere, off the list and never an unknown in a sentence. What is a name: a word the
tagger's dictionary knows and tags as a person's name (固有名詞 人名), a katakana name made one word above, and a kanji name
the library's table joins. Not a name: a spelling UniDic also lists as a common word said the same way (ひかり is 光
'light', 悪魔 'devil' — the tag there is the tagger's guess between two words that look and sound alike), a name keyed
as a common word is (麻衣 is keyed マイ, as マイ 'my' is: ignoring it would hide the word), a single kana, a word the
dictionary doesn't know at all (its tag is a guess), a katakana word the lists carry, one word above only because its
pieces are no words (ブシン, ハアッ, コスパ — as often a word as a name), and the katakana runs and kanji terms the library
repeats, which are as often terms, places and titles as people. The token store records each file's names as it
indexes it (`Record`), keeps the library's after indexing (`name_words`), and token_index.ignored_names is the one
reader every ignore set calls.
"""
import hashlib
import json
import re
import threading
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
# A piece the tagger reads as an interjection (アッ, ハハ): a run of nothing else is laughter or a cry, in pieces.
_INTERJECTION = "感動詞"

_katakana_headwords = []    # [Spellings] once read; [None] when the table can't be read
_person_names = []          # [PersonNames] once read (only where files are indexed); [None] when it can't be read
_whole = {}                 # spelling -> the tagger's feature for it read alone as one known word, or None
_listed = {}                # spelling -> the features of every word UniDic lists spelled so (`_listed_as`)
_tagger = []                # the tagger that reads a spelling alone, made on the first join

# Names that recur in the library.
STICKY = 0.7        # a run joins once this share of its least-used piece's uses (as a word) are inside it...
KEEP = 0.5          # ...and, joined, stays joined down to this share: a growing library doesn't flip it back and forth
FLOOR = 3           # uses in the library before a run can join (a coincidence rarely recurs)
REFRESH = 30.0      # seconds: how often a long-lived process (the dashboard, Junban) looks for newer tables

# Ignore names: how many of the tagger's best readings of a spelling alone are looked through for the words UniDic
# lists spelled so — a short spelling has only a handful.
READINGS = 10
_PROPER = "固有名詞"

# Kanji names.
SURNAME, GIVEN = 1, 2
_HAN = re.compile(f"[{HAN}]")
_NOT_IN_A_NAME = frozenset(("助詞", "助動詞", "動詞", "形容詞", "連体詞", "代名詞", "接続詞", "感動詞"))
_NAME_LINKS = frozenset(("ノ", "ヶ", "ケ", "之"))
_BREAKS = ("補助記号", "空白")
_NO_START = frozenset(_BREAKS) | _NOT_IN_A_NAME | {"接尾辞"}     # what no name starts with (kanji_name's guards)
_HIRAGANA = re.compile(r"^[ぁ-ゖー]+$")
_library = {"tables": None, "at": None, "pinned": False}

# A work's own kanji terms.
_TERM_LAST = frozenset("君様殿氏達等共方内中外上下前後間")   # an honorific, a plural or a position word ends no term
_COUNTED = frozenset("cg")      # a piece's kind (term_runs): c a word, g grammar — counted; n a number, x no word
_RIDERS = []                    # [what may ride on a kanji and read as nothing], made on first use (`_riders`)
# What no reading makes a kanji, tested first on each one-character token: ASCII, punctuation, kana, the full-width
# forms (々 and 〇, U+3005 and U+3007, are Han), and anything before the CJK radicals (U+2E80).
_NO_KANJI = frozenset(map(chr, [*range(0x80), *range(0x2000, 0x2070), *range(0x3000, 0x3100),
                                *range(0xFF00, 0xFFF0)])) - {chr(0x3005), chr(0x3007)}
_RADICALS = chr(0x2E80)
_jmdict_kanji = []              # [{spelling asked: does JMdict spell it}]; [None] when the list can't be read
_JMDICT_LOCK = threading.Lock()  # one reading of the list at a time, whichever thread asks


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


def jmdict_words(spellings):
    """Which of `spellings` JMdict spells — a kanji form of one of its entries (app/jmdict_data.py) — a frozenset: a
    run of kanji spelled as one is a dictionary word, never a work's own term. Asked only where the library's tables
    are computed, and only of spellings that could be a term: the list is read for a spelling not asked before, and
    only the answers are kept — never the list's 233,000 forms, for a few dozen answers. None when the list can't be
    read (or holds nothing): then no run is a term — an unreadable list must never pass every spelling."""
    with _JMDICT_LOCK:
        if not _jmdict_kanji:
            _jmdict_kanji.append({})
        answers = _jmdict_kanji[0]
        if answers is None:
            return None
        new = set(spellings).difference(answers)
        if new:
            found = _jmdict_find(new)
            if found is None:
                _jmdict_kanji[0] = None
                return None
            answers.update((spelling, spelling in found) for spelling in new)
        return frozenset(spelling for spelling in spellings if answers[spelling])


def _jmdict_find(spellings):
    """Those of `spellings` (a set) that are a kanji form in app/jmdict_data.py's list, read now — None when the list
    can't be read or holds nothing."""
    try:
        from app import jmdict_data
        forms = jmdict_data.kanji_forms().replace("\t", "\n").split("\n")
    except Exception:
        return None
    return spellings.intersection(forms) if any(forms) else None


def _read(word):
    """A node's text as the tagger read it (analyzer._read): ﾄｩｰﾘ is read トゥーリ."""
    return word.feature.orth or word.surface


def _katakana(text):
    """ひらがな in カタカナ: one spelling for a headword lookup (the headwords are kept in katakana)."""
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


def _heads_a_kana_word(words, last):
    """Does words[last] — a katakana run's last piece — head a word the text goes on writing in hiragana? ジャ +
    がい + も (or ジャ + が + いも) is ジャがいも, the headword ジャガイモ written half in each script: two or more tokens
    of the hiragana right after it, up to the next break, spell a headword with it — the tagger cutting that hiragana
    too, as it cuts no particle or suffix that follows a name — ending where a word can end (never on a prefix: お
    belongs to the 話 after it). Never one token alone, and never grammar alone: a name's own particle or honorific
    (トゥーリは, ミロナイと, ダンさん) makes no word with its last piece, though リハ, ナイト and ダンサン are words."""
    nxt = last + 1
    if nxt >= len(words) or getattr(words[nxt], "white_space", "") or not _HIRAGANA.match(_read(words[nxt])):
        return False
    listed = katakana_headwords()
    spelling, content = _read(words[last]), False
    for k in range(nxt, len(words)):
        w = words[k]
        text = _read(w)
        if not _HIRAGANA.match(text) or (k > nxt and getattr(w, "white_space", "")):
            break
        spelling += _katakana(text)
        content = content or w.feature.pos1 not in _NOT_IN_A_NAME
        if k > nxt and content and w.feature.pos1 != "接頭辞" and spelling in listed:
            return True
    return False


def katakana_runs(words):
    """(start, end) of every run of two or more tokens written only in katakana with nothing between them, trimmed of
    the marks the tagger leaves at its ends — and of a last piece that heads a word the text goes on writing in
    hiragana (`_heads_a_kana_word`). Found in the line's text as read, then mapped back to its tokens: the tokens
    wholly inside a stretch of katakana."""
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
            if b - a >= 2 and _heads_a_kana_word(words, b - 1):
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


def _joined_by_the_dictionary(spelling):
    """Is `spelling` the compound or affix joins' own — a word their tables hold (joined there, or kept apart by their
    guards and switches)? True too when the compound table can't be read: without it, a headword stays as the tagger
    cuts it."""
    from app.analyzer import affix_joins, compound_joins
    compounds = compound_joins()
    return not compounds or spelling in compounds or spelling in affix_joins()


def katakana_kind(run, listed):
    """What a katakana run is: "listed" (a headword spells it: the word it is, the dictionary joins' to make), "common"
    (only common words the lists don't carry as one: a compound, in pieces), "sound" (one piece repeated, a stutter,
    or only interjections: in pieces) or "name" (one word). A run with any piece that is no interjection — a name, a
    letter, a mark — may still be a name (ハイ + ミロ). A headword the dictionary joins don't hold, with a piece that
    is no common word (ブ, read as the prefix 無, + シン), is one word as an unlisted run is: its pieces are no words."""
    pieces = [_read(t) for t in run]
    common = [_common_word(t, listed) for t in run]
    spelling = "".join(pieces)
    if spelling in listed and (all(common) or _joined_by_the_dictionary(spelling)):
        return "listed"
    if all(common):
        return "common"
    if repeated(pieces) or stutter(pieces) or all(t.feature.pos1 == _INTERJECTION for t in run):
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


def _has_katakana(words, surfaces=None):
    """Any katakana in the line — `surfaces`, its tokens' text as written, when the caller already has it."""
    return _ANY_KATAKANA.search("".join([w.surface for w in words] if surfaces is None else surfaces)) is not None


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


# --- Ignore names: which words are names ------------------------------------------------------------------------- #
def _listed_as(spelling):
    """The features of every word UniDic's dictionary lists spelled `spelling`: each reading of the spelling alone as
    ONE word the tagger knows, among its best READINGS. Asked once per spelling."""
    found = _listed.get(spelling)
    if found is None:
        from app.analyzer import Tagger
        if not _tagger:
            _tagger.append(Tagger())
        found = _listed[spelling] = tuple(
            path[0].feature for path in _tagger[0]._tagger.nbestToNodeList(spelling, READINGS)
            if len(path) == 1 and not path[0].is_unk and path[0].feature.lemma)
    return found


def _said(f):
    """How a word is said: UniDic's pronunciation of its dictionary form — シャドウ and シャドー alike are シャドー."""
    return f.pronBase or f.lForm or f.kana or ""


def _common_word_listed(spelling, said=None, lemma=None, sanitize=None):
    """Does UniDic list a common word — no proper noun — spelled `spelling`, said `said` (`_said`) and with the lemma
    `lemma` (each when given; `sanitize` cleans UniDic's lemma as the tokenizer does)?"""
    for f in _listed_as(spelling):
        if f.pos2 == _PROPER:
            continue
        if said is not None and _said(f) != said:
            continue
        if lemma is not None and (sanitize(f.lemma) if sanitize else f.lemma) != lemma:
            continue
        return True
    return False


def name_lemma(word, sanitize=None):
    """The lemma under which `word` — one of join_affixes' words, read without the library's tables, as the token store
    reads a file — is a person's name, or None (§ Ignore names). A katakana name made one word here is one, keyed as
    a word its dictionary lacks — unless the lists carry its spelling as a word (ブシン: one word only because its
    pieces are no words); so is a word the tagger's dictionary knows and tags as a person's name, two characters
    or more — unless UniDic lists a common word spelled and said the same (ひかり is 光 'light') or keyed the same
    (麻衣 is keyed マイ, as マイ 'my' is). `sanitize` is the analyzer's lemma cleaning, as the tokenizer applies it."""
    f = word.feature
    if word.is_unk:
        from app.analyzer import JoinedWord
        if not isinstance(word, JoinedWord) or not f.lemma:
            return None                     # a word the dictionary doesn't know: its tag is the tagger's guess
        if f.lemma in (katakana_headwords() or ()):
            return None                     # a word the lists carry, one word because its pieces are no words
        return sanitize(f.lemma) if sanitize else f.lemma
    if f.pos3 != "人名" or f.pos2 != _PROPER:
        return None
    from app.analyzer import word_lemma
    lemma = word_lemma(word)
    lemma = sanitize(lemma) if sanitize and lemma else lemma
    if (not lemma or len(lemma) < 2
            or _common_word_listed(f.orthBase or word.surface, said=_said(f))
            or _common_word_listed(lemma, lemma=lemma, sanitize=sanitize)):
        return None
    return lemma


# --- Names from the whole library: the tables ----------------------------------------------------------------------- #
Candidate = namedtuple("Candidate", "i j kind spelling pieces")     # kind: "k" katakana, "j" kanji, "w" a work's term


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


def candidates(words, kanji=None, terms=False, surfaces=None):
    """Every run in one tagger call's tokens (after the katakana rule) that a library table could make one word: each
    katakana run of common words the rule leaves in pieces, — with `kanji`, a names table (`kanji_candidates`) —
    each kanji run spelled as one of its names, and — with `terms` — each run of one-kanji tokens (`term_runs`).
    `surfaces`: the tokens' text as written, when the caller already has it."""
    out = []
    listed = katakana_headwords()
    if surfaces is None:
        surfaces = [w.surface for w in words]
    if listed and _has_katakana(words, surfaces):
        for a, b in katakana_runs(words):
            run = words[a:b]
            if katakana_kind(run, listed) == "common":
                pieces = tuple(_read(t) for t in run)
                out.append(Candidate(a, b, "k", "".join(pieces), pieces))
    if kanji:
        out.extend(kanji_candidates(words, kanji))
    if terms:
        out.extend(term_runs(words, surfaces=surfaces))
    return out


def term_runs(words, lone=None, surfaces=None):
    """Every run of two or more tokens each read as exactly one kanji — a word, a number or a kanji the tagger reads as
    a symbol, never a joined word — with no space inside (斬 + 魄 + 刀): a work's term may be one. As candidates of
    kind "w", `pieces` each token's kind: "n" a number, "x" no word (a symbol), "g" grammar, "c" a word — the last
    two counted. `lone`, a Counter, also receives every such kanji token, in a run or alone: how often each kanji
    stands on its own. `surfaces`: the tokens' text as written, when the caller already has it."""
    from app.analyzer import JoinedWord, word_lemma
    if surfaces is None:
        surfaces = [w.surface for w in words]
    pieces, riders = [], _RIDERS[0] if _RIDERS else _riders()
    # Most tokens are longer than one character, or kana or punctuation — no reading makes those a kanji — and pass in
    # one sweep on their text as written (a kanji may carry what is read as nothing: a variation selector, a
    # zero-width space); each one left is read.
    for k in [k for k, s in enumerate(surfaces) if len(s) == 1 and s not in _NO_KANJI and s >= _RADICALS
              or len(s) > 1 and s[1] in riders]:
        w = words[k]
        text = w.feature.orth or w.surface
        if len(text) == 1 and _HAN.match(text) is not None and not isinstance(w, JoinedWord):
            pieces.append(k)
            if lone is not None:
                lone[text] += 1
    out, i, n = [], 0, len(pieces)
    while i < n:
        j = i + 1
        while j < n and pieces[j] == pieces[j - 1] + 1 and not getattr(words[pieces[j]], "white_space", ""):
            j += 1
        if j - i >= 2:
            run = words[pieces[i]:pieces[j - 1] + 1]
            out.append(Candidate(pieces[i], pieces[j - 1] + 1, "w", "".join(_read(t) for t in run),
                                 "".join(_term_kind(t, word_lemma) for t in run)))
        i = j
    return out


def _riders():
    """What may follow a kanji inside its token yet be read as nothing (analyzer.tagger_text): a default-ignorable
    character — a variation selector, a zero-width space, a soft hyphen — or a stretched vowel's mark."""
    if not _RIDERS:
        from app.analyzer import _IGNORABLE
        _RIDERS.append(frozenset([chr(p) for first, last in _IGNORABLE for p in range(first, last + 1)]
                                 + ["\u30fc", "\u301c", "\uff5e"]))
    return _RIDERS[0]


def _term_kind(word, word_lemma):
    """A one-kanji piece's kind, one letter (term_runs): a number, no word, grammar or a word."""
    f = word.feature
    if f.pos2 == "数詞":
        return "n"
    if word_lemma(word) is None:
        return "x"
    return "g" if f.pos1 in _NOT_IN_A_NAME else "c"


def _term_shape(spelling, kinds):
    """May a stretch of one-kanji pieces (`spelling`, their `kinds`) be a work's term at all? Not when a piece is
    grammar — a name's linking 之 inside it aside (星之宮), as a kanji name's — nor numbers alone, nor ending in an
    honorific, a plural or a position word (谷 + 君, 三 + 年 + 前)."""
    if spelling[-1] in _TERM_LAST or all(k == "n" for k in kinds):
        return False
    return all(k != "g" or (0 < m < len(kinds) - 1 and spelling[m] in _NAME_LINKS) for m, k in enumerate(kinds))


def _stretches(i, j, taken):
    """(start, end), offsets into the run [i, j), of each stretch of it that no (a, b) in `taken` covers."""
    out, start = [], None
    for k in range(i, j + 1):
        free = k < j and not any(a <= k < b for a, b in taken)
        if free and start is None:
            start = k
        elif not free and start is not None:
            out.append((start - i, k - i))
            start = None
    return out


def _terms(runs, taken, table):
    """The work's terms in `runs` (kind "w" candidates): each stretch of 2+ pieces the joins in `taken` ((start, end)
    pairs) leave that `table` holds, as a candidate whose pieces are (the run, start, end)."""
    out = []
    for c in runs:
        for start, end in _stretches(c.i, c.j, taken):
            if end - start >= 2 and c.spelling[start:end] in table:
                out.append(Candidate(c.i + start, c.i + end, "w", c.spelling[start:end], (c, start, end)))
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


def choose(cands, tables, recurring=True, kanji=True, terms=True):
    """The candidates the tables make one word, in order: every katakana run the recurring table holds, then the
    kanji runs the kanji table holds, the longest from the left, overlapping none of those, then the work's terms the
    terms table holds in what those leave of each run of one-kanji tokens (a term is a candidate whose pieces are
    (its run, start, end))."""
    chosen = [c for c in cands if c.kind == "k" and recurring and c.spelling in tables.get("k", ())]
    if kanji and tables.get("j"):
        chosen += _longest_from_left([c for c in cands if c.kind == "j" and c.spelling in tables["j"]],
                                     [(c.i, c.j) for c in chosen])
    if terms and tables.get("w"):
        chosen += _terms([c for c in cands if c.kind == "w"], [(c.i, c.j) for c in chosen], tables["w"])
    return sorted(chosen, key=lambda c: (c.i, c.j))


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


_term_starts = {}


def _term_starts_of(tables):
    """The first two kanji of each of the terms table's words, as a pattern, and the analyzer's test for a line read
    otherwise than it is written — made once per table."""
    key = (tables.get("stamp"), id(tables["w"]))
    if key not in _term_starts:
        _term_starts.clear()
        from app.analyzer import _reads_differently
        starts = re.compile("|".join(sorted({re.escape(spelling[:2]) for spelling in tables["w"]})))
        _term_starts[key] = (starts, _reads_differently)
    return _term_starts[key]


def _may_hold_a_term(tables, line):
    """Can `line` (one tagger call's text as written) hold one of the terms table's words? Only where the first two
    kanji of one stand side by side — each piece is a one-character token, its own text — or where the line reads
    otherwise than it is written (a compatibility ideograph, a character read as nothing): then every line is looked
    at. The same joins as looking at every line; most lines hold no term and skip the search for runs."""
    starts, reads_differently = _term_starts_of(tables)
    return starts.search(line) is not None or reads_differently(line)


def join_library(words, recurring=True, kanji=True, terms=True):
    """`words` with every run the library's tables name made one word (§ above) — as they are when there is no table
    yet, or every switch is off."""
    tables = library_tables()
    if not tables or not ((recurring and tables.get("k")) or (kanji and tables.get("j"))
                          or (terms and tables.get("w"))):
        return words
    gate = _gate(tables) if kanji and tables.get("j") else None
    surfaces = [w.surface for w in words]
    runs = bool(terms and tables.get("w")) and _may_hold_a_term(tables, "".join(surfaces))
    chosen = choose(candidates(words, gate, runs, surfaces), tables, recurring, kanji, terms)
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
    letters or more is used as a token ("p") — a piece's uses as a word — how often each kanji name is read, the
    longest from the left ("jc", with its lists' bits in "jb"), how often each word is a person's name there ("n", by
    lemma: `name_lemma`), how often each kanji stands as a token of its own ("q": the gauge of a work's terms), and
    whether the file is a transcript of auto-generated captions ("a", set by the token store from what the file
    says of itself: `auto`)."""

    def __init__(self):
        self.spans, self.ks, self.k1, self.p = [], {}, Counter(), Counter()
        self.jc, self.jb, self.q, self.auto = Counter(), {}, Counter(), False
        self.n = Counter()

    def read_line(self, words):
        """The candidates of one tagger call's tokens (after the katakana rule), counted."""
        from app import analyzer
        from app.analyzer import JoinedWord
        sanitize = analyzer._sanitize_term if analyzer.SANITIZE_JA else None
        for w in words:
            if w.is_unk or w.feature.pos3 == "人名":
                lemma = name_lemma(w, sanitize)
                if lemma:
                    self.n[lemma] += 1
        surfaces = [w.surface for w in words]
        if _has_katakana(words, surfaces):
            p, k1, katakana = self.p, self.k1, _KATAKANA.match
            for w in words:
                text = w.feature.orth or w.surface
                if len(text) >= 2 and katakana(text):
                    p[text] += 1
                    if isinstance(w, JoinedWord):
                        k1[text] += 1
        persons = person_names()
        cands = candidates(words, persons, surfaces=surfaces)
        for c in cands:
            if c.kind == "k":
                self.ks.setdefault(c.spelling, Counter())["|".join(c.pieces)] += 1
        for c in _longest_from_left([c for c in cands if c.kind == "j"]):
            self.jc[c.spelling] += 1
            self.jb[c.spelling] = persons.get(c.spelling)
        return cands + term_runs(words, self.q, surfaces)

    def span(self, sentence, cand, a, b, surfaces):
        """Candidate `cand` sits in yielded sentence `sentence`, over its counted tokens [a, b), written as `surfaces`
        (each token's text as written). A run of one-kanji tokens keeps its pieces' kinds, and each piece's text
        where the run is written otherwise than it reads (a compatibility ideograph), so any stretch of it can be
        cut out."""
        surface = "".join(surfaces)
        if cand.kind == "w":
            self.spans.append([sentence, cand.i, cand.j, a, b, "w", cand.spelling,
                               list(surfaces) if surface != cand.spelling else 0, cand.pieces])
        else:
            self.spans.append([sentence, cand.i, cand.j, a, b, cand.kind, cand.spelling,
                               surface if surface != cand.spelling else 0])

    def data(self):
        data = {"s": self.spans, "ks": self.ks, "k1": self.k1, "p": self.p, "jc": self.jc, "jb": self.jb,
                "n": self.n, "q": self.q}
        if self.auto:
            data["a"] = 1
        return data


def compute_tables(records, previous=None, sanitize=None):
    """The library's tables from every file's `Record` data (`records`, an iterable of dicts): {"k": {spelling:
    [stickiness, lemma, reading, orth]}, "j": {spelling: [bits, lemma, reading, orth]}, "w": {spelling: [stickiness,
    lemma, reading, orth]}, "stamp": …} — a katakana run joins at STICKY with FLOOR uses, and a run in `previous` (the
    last tables) stays while its stickiness is KEEP or more; a kanji name joins with FLOOR uses; a work's term as a
    katakana run does (`_work_terms`)."""
    records = list(records)
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
    tables["w"] = _work_terms(records, tables, (previous or {}).get("w", {}), sanitize)
    tables["stamp"] = hashlib.sha1(json.dumps(tables, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return tables


def name_words(records, tables=None, sanitize=None):
    """The library's names, as the lemmas Ignore names ignores (§ Ignore names), sorted: every word the files' records
    name ("n") and each kanji name the library's table joins — keyed as that table keys it — that no common word shares
    (`_common_word_listed`). Never the katakana runs the library repeats: as many are terms, places and titles."""
    words = set()
    for data in records:
        words.update(data.get("n", ()))
    for entry in ((tables or {}).get("j") or {}).values():
        lemma = entry[1]
        if lemma and not _common_word_listed(lemma, lemma=lemma, sanitize=sanitize):
            words.add(lemma)
    return sorted(words)


def _cut(spans, runs=True):
    """A record's recorded spans as candidates, by sentence ({sentence: [Candidate]}), each keeping (a, b, its text as
    written, a run's kinds) as its pieces. `runs`: which runs of one-kanji pieces to keep — True every run, False
    none, or a test of a run's spelling."""
    by_sentence = {}
    for span in spans:
        s, i, j, a, b, kind, spelling, surface = span[:8]
        if kind == "w" and runs is not True and not (runs and runs(spelling)):
            continue
        by_sentence.setdefault(s, []).append(
            Candidate(i, j, kind, spelling, (a, b, surface or spelling, span[8] if kind == "w" else None)))
    return by_sentence


def _work_terms(records, tables, before, sanitize):
    """The terms table ({spelling: [stickiness, lemma, reading, orth]}) from every record's runs of one-kanji tokens.
    Each run is cut by what layers 2-3 take there (`tables`' katakana runs and kanji names, both applied); every stretch
    of 2+ pieces left is a use of that spelling. Its stickiness is its uses over the lone uses ("q") of its least-used
    kanji, less that kanji's uses inside the kanji names taken in runs. A spelling joins at STICKY with FLOOR uses, or
    stays while KEEP when `before` (the last terms table) holds it — when its shape, as the tagger reads it in most of
    its uses, may be a term (`_term_shape`) and no dictionary spells it (a kanji name, the compound and affix joins,
    JMdict). A record of auto-generated captions ("a") counts toward nothing. Empty when JMdict's spellings can't be
    read."""
    uses, kinds, lone, gone = Counter(), {}, Counter(), Counter()
    taken_tables = {"k": tables["k"], "j": tables["j"]}
    for data in records:
        if data.get("a"):
            continue
        lone.update(data.get("q", {}))
        spans = data.get("s", ())
        if not any(span[5] == "w" for span in spans):
            continue
        for cands in _cut(spans).values():
            runs = [c for c in cands if c.kind == "w"]
            if not runs:
                continue
            taken = [(c.i, c.j) for c in choose(cands, taken_tables, True, True, False)]
            for c in runs:
                run_kinds = c.pieces[3]
                for start, end in _stretches(c.i, c.j, taken):
                    if end - start >= 2:
                        spelling = c.spelling[start:end]
                        uses[spelling] += 1
                        kinds.setdefault(spelling, Counter())[run_kinds[start:end]] += 1
                for k in range(c.i, c.j):
                    if any(a <= k < b for a, b in taken):
                        gone[c.spelling[k - c.i]] += 1
    passed = {}
    for spelling, n in uses.items():
        read = max(kinds[spelling].items(), key=lambda way: (way[1], way[0]))[0]     # its most common reading
        if spelling in tables["j"] or not _term_shape(spelling, read):
            continue
        least = min(lone[c] - gone[c] for c in spelling)
        if least <= 0:
            continue
        stick = min(1.0, n / least)
        if (stick >= STICKY and n >= FLOOR) or (spelling in before and stick >= KEEP):
            passed[spelling] = stick
    if not passed:
        return {}
    dictionary = jmdict_words(passed)           # asked only of the spellings that got this far
    if dictionary is None:
        return {}
    from app.analyzer import affix_joins, compound_joins
    joins, compounds = affix_joins(), compound_joins()
    return {spelling: [round(stick, 3), *key_of(spelling, sanitize)] for spelling, stick in passed.items()
            if spelling not in dictionary and spelling not in joins and spelling not in compounds}


def _counted(kinds):
    """How many of a run's pieces (`kinds`, their letters) the tokenizer counts as words."""
    return sum(k in _COUNTED for k in kinds)


def chosen(sentences, spans, tables, recurring=True, kanji=True, terms=True):
    """The joins `apply_spans` makes, without making them: (sentence, a, b, [lemma, reading, surface, orth]) for every
    recorded span the tables choose — tokens a..b of that sentence become the one token (a == b: every piece was
    dropped as no word, and the term goes in there). Each sentence's joins come in order and never overlap. A run of
    one-kanji pieces in which no term starts is left out first: it can hold none (most runs are counts: 一度, 十番隊)."""
    runs = _term_starts_of(tables)[0].search if terms and tables.get("w") else False
    for s, cands in _cut(spans, runs).items():
        if s >= len(sentences):
            continue
        for c in choose(cands, tables, recurring, kanji, terms):
            if c.kind == "w":                   # a stretch of a run: its counted tokens and text, cut out of the run's
                run, start, end = c.pieces
                a, _b, written, run_kinds = run.pieces
                a += _counted(run_kinds[:start])
                b, surface = a + _counted(run_kinds[start:end]), "".join(written[start:end])
            else:
                a, b, surface, _kinds = c.pieces
            lemma, reading, orth = tables[c.kind][c.spelling][1:]
            yield s, a, b, [lemma, reading, surface, orth]


def apply_spans(sentences, spans, tables, recurring=True, kanji=True, terms=True):
    """The token store's cached `sentences` ([text, [[lemma, reading, surface, orth], …]], as recorded) with every
    recorded span the tables choose made one token — the same choice `join_library` makes on live text."""
    for s, a, b, token in reversed(list(chosen(sentences, spans, tables, recurring, kanji, terms))):
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
