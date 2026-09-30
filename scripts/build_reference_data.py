"""Distil the reference corpora into app/reference_data.py (DEV ONLY — never shipped).

Why this exists
---------------
Deciding whether a word is one you'll READ or one you'll HEAR is a question about Japanese,
not about any particular user: it depends only on the reference corpora and the tokenizer, both
of which are fixed when we build. So all of that work happens HERE, once, and the app ships a
small lookup table. The user's machine never loads a corpus, never tokenizes a word list, and
pays nothing at Generate time beyond a dict lookup.

These tables come out of it:

  AFFIX_JOINS  written form -> [lemma, reading]: the dictionary words that UniDic cuts into a
               prefix + a word or a word + suffixes (新幹線 = 新 + 幹線, 可能性 = 可能 + 性), which
               `analyzer.join_affixes` joins back (Patterns_Quality_Spec.md Part A). Every
               JPDB 2024 / Jiten headword — in both, or in one's top 60,000 — whose own tokens that
               join reproduces, with the list's reading (日本人 ニホンジン — unidic-lite reads the
               suffix 人 as ニン), and the spellings of one word under one lemma (おすすめ -> お勧め).
               A word with the polite お / ご / 御 joins only when that is a usual form of it (the
               user, U1: OGO_SHARE, OGO_TALK_SHARE). Built first: the other tables are keyed
               through the join. A second pass adds the words a compound makes with its affixes
               (同性愛者 = 同性愛 + 者).

  COMPOUND_JOINS  written form -> [lemma, reading, kind, 0]: the dictionary words UniDic cuts into words
               of their own (上層部 = 上層 + 部, 一生懸命, 二十歳, 取り掛かる), which the tokenizer joins back
               — see "Compounds" below; COMPOUND_PARTS, apart, each one's parts. COUNTERS: the words the
               lists count with that UniDic doesn't always file as counters (人, 冊).

  ALIASES      lemma -> the spelling frequency lists actually use.
               Unidic hands the analyzer orthographic lemmas (為る, 矢張り, 其れ); every
               frequency list on earth stores する, やっぱり, それ. Without this bridge the
               most common verb in the language reports as "Outside" in the Tier column.

  SPOKEN_RANK  lemma -> its rank in spoken Japanese (0 = rarer than the corpora can see).
               Only words that are real WRITTEN vocabulary get an entry — see the filters
               below. app/modality.py turns the rank into "hours of listening between
               encounters" and compares that to the user's threshold.

What the dictionaries themselves say about the compounds — a title of a work, a product or an
organization (JMnedict), and JMdict's word when its file is here — goes to app/dictionary_data.py:
its licence (CC BY-SA 4.0) is not this module's.

Inputs live in docs/assets/reference_lists/ — gitignored, and deliberately NOT under scripts/,
which packaging/Surasura.spec bundles wholesale: left there they would add ~78 MB of dead
corpora to every release. The お / ご shares, and the counts that vouch for a compound, are counted
over the text of the shared パターン set, staged in docs/assets/corpora/_text/ (also gitignored;
prepare.py makes it). Output (app/reference_data.py, app/dictionary_data.py) is committed and ships.

The build reads text the way the app does — `analyzer.Tagger`, the affix joins, the compounds, a
compound's own affixes — from the tables it is making, never from the ones installed now: a build
is a function of its inputs, not of the last build.

Usage:  python scripts/build_reference_data.py
"""

import base64
import bisect
import json
import math
import os
import random
import re
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analyzer import (_SAME_CHARACTER, _STRETCH_DROPPED_RE, JoinedWord, ReadNode, _compound_part,  # noqa: E402
                          _join_affix_runs, _join_compounds, _lone_marks, _plural, _read, _sanitize_term, _stretched,
                          join_affixes, tagger_text)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTS_DIR = os.path.join(ROOT, "docs", "assets", "reference_lists")
OUTPUT = os.path.join(ROOT, "app", "reference_data.py")
DICTIONARY_OUTPUT = os.path.join(ROOT, "app", "dictionary_data.py")

# The four corpora that carry a role. Everything else in reference_lists/ is unused —
# see docs: Wikipedia's "written" signal is encyclopedia furniture (一覧/出典/編曲), and
# Aozora is kanji-only (0% kana), so neither can serve as a pole.
SPOKEN_LISTS = ["TMW Netflix", "TMW Anime & J-drama"]
WRITTEN_LIST = "TMW Novels"
VETO_LIST = "TMW VN Freq v2"

# Only the top of the written corpus. Past ~50k the vocabulary turns archaic and obscure
# (訣る, 綺譚, 髣髴) — words no learner meets often enough for the badge to be worth showing.
WRITTEN_RANK_CAP = 50_000

# Parts of speech that are never "vocabulary worth a reading card". 固有名詞 (proper nouns)
# is the important one: absence from a spoken corpus is overwhelmingly evidence of being a
# character name, not of being literary — without this filter the output is アルマ/ルッツ/エミリア.
DROP_POS1 = {"補助記号", "記号", "空白", "感動詞", "接頭辞", "接尾辞", "助詞", "助動詞", "フィラー"}
DROP_POS2 = {"固有名詞"}

# Mimetics (さらり/ふわり) are spoken language that subtitle corpora simply don't transcribe,
# so they look "written" on rank alone. Visual novels are dialogue-heavy TEXT and do record
# them, which makes VN a reliable detector. Restricted to kana-only words on purpose: VN
# narration is literary prose, so without that guard it also vetoes 佇む (19x) — a genuine
# reading word.
VETO_RATIO = 5.0

_JP = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")

# The dictionaries a joined word must be a headword of (Patterns_Quality_Spec.md §6.1). Each kanji word
# comes with its reading (["日本人", "ニホンジン"]); a kana-only word is its own reading.
JOIN_LISTS = ["JPDB 2024", "Jiten"]
_KANA_ONLY = re.compile(r"^[ぁ-ゟ゠-ヿー]+$")
# ...and in both of them, or in one's top JOIN_ONE_LIST_RANK (the user, checkpoint A): the lists' long
# tails are names and misreadings (霊子 read タマコ, 新大橋 シンオオハ, 金家 カナヤ), which the rule drops
# while it keeps 宇宙人, 母上 and 情熱的.
JOIN_ONE_LIST_RANK = 60_000
# A word that ends in an honorific is a word of its own (お母さん, お客様, お疲れ様 — the user, checkpoint A),
# not a polite way of saying the word inside it, so the お / ご share below never applies to it.
HONORIFICS = frozenset(("さん", "様", "さま", "ちゃん", "君", "くん", "殿", "氏"))

# お / ご / 御 + a word joins only where that is a usual form of the word (the user, 2026-09-25, U1 "C at
# 30%"): at least OGO_MIN_USES uses, and at least OGO_SHARE of the word's uses — the prefixed form over
# the prefixed form plus the bare word. So お茶, お菓子, お金, お店 become words; お名前, お仕事, お部屋 stay a
# prefix and a word. Counted over the text of the shared パターン set — licence-clean, since this table
# ships inside the app (statistics only): docs/assets/corpora/build_shared.py's SOURCES, the same slices.
OGO_SHARE = 0.30
OGO_MIN_USES = 20
CORPUS_TEXT = os.path.join(ROOT, "docs", "assets", "corpora", "_text")
OGO_SOURCES = {"realpersonachat": None, "aozora": 23_000_000, "wikipedia": 25_000_000, "leipzig_news": None}
# The set is mostly written text, where お is rarer than in speech: お祭り is 14% of its uses there, 76% in
# the set's conversation. So a word people say with the お most of the time joins too — at least
# OGO_TALK_SHARE of its uses in OGO_TALK, with OGO_MIN_USES there (the user, checkpoint A: "ideally お祭り
# is able to be joined"). Half, not 30%: persona chat is polite, so お話 (34%) and お仕事 (30%) stay split.
OGO_TALK = "realpersonachat"
OGO_TALK_SHARE = 0.50
OGO_REPORT = os.path.join(ROOT, "debug", "ogo_joins.md")
_KANJI = re.compile(r"[一-鿿々]")
# The passes over the shared set's text (~44M tokens) run in this many processes.
WORKERS = min(12, os.cpu_count() or 1)

# --- Compounds: dictionary words that UniDic cuts into words ------------------------------------------------ #
# UniDic's short units cut a compound into the words it is made of — 上層部 is 上層 + 部, 一生懸命 一生 + 懸命,
# 二十歳 二十 + 歳, and 取り掛かる, whole on its own, is 取り + 掛かる in a sentence — so the list counted the pieces
# and never offered the word the content says. The tokenizer joins such a run back where it spells a headword from
# the same pool as the affix joins, with the list's reading (株式会社 カブシキガイシャ, not カブシキ + カイシャ). The
# kinds (COMPOUND_JOINS' third field):
#   N  2-3 words, each a noun that is no number and no person's name — a place is fine (日本語, 鳥取県) — or a
#      な-word (一生懸命, 自信満々); never a grammar word UniDic files as a な-word (みたい, そう: バカみたい stays
#      バカ + みたい). A word the affix joins made is a part like any noun (お味噌 + 汁).
#   Q  up to 4 words holding a number, the others parts or a noun's suffixes (二十歳, 十人十色, 一日中) — only
#      where the number counts nothing (NumeralTest): the numbers of a count (三日, 五分, 十円玉) stay apart.
#   V  a verb's stem + a verb (取り掛かる, 見つめ合う, 走り出す), keyed by the stem as written and the second verb's
#      dictionary form — only where the second verb makes words of its own, not where it goes with any verb
#      (食べ始める and 勉強し始める stay two words: ASPECT_VERBS).
# Kept out whatever the lists say: a plural (先生方 センセイガタ: 方 is the honourable plural there, though UniDic
# reads it ホウ; 等 read トウ is no plural), and a noun compound the text shows only as two words meeting by chance
# (今頭, as 今、頭が痛い reads without its comma — GATE_MARGIN).
COMPOUND_KINDS = ("N", "Q", "V")
_VOICED = str.maketrans("ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポ", "カキクケコサシスセソタチツテトハヒフヘホハヒフヘホ")
# Even odds (a noun compound): its parts A and B meet by chance about e = f(A)·f(B) / N times in the reference text
# (at the most likely split of three parts). A compound is refused when chance could account for it — e >= 1 and
# the text joins it fewer than GATE_MARGIN × e times — and the lists don't vouch for it either: both lists must
# carry it, as often as chance would give — its rank read as a count on the same text (the median, at that rank,
# of the lists' compounds whose parts almost never meet by chance) times the share of its spelling's occurrences
# the text reads as the compound (時半 is almost always 3時半). Either witness is enough: a real word has one, a
# coincidence (今頭, 今手, 間話) has neither. Build time only — the tokenizer never consults a count. The share of a
# spelling's occurrences is taken on more text, FORM_SOURCES too (the rest of the same licence-clean sources: Aozora
# is public domain, Wikipedia CC BY-SA, Leipzig's web corpus CC BY 4.0, statistics only): a rare spelling needs it.
GATE_MARGIN = 2.0
CALIBRATION_CHANCE = 0.05
FORM_SOURCES = ("aozora", "wikipedia", "leipzig_web")
# Verb + verb: a second verb is grammar, not word-making, when it takes a verbal noun + し as its first verb
# (勉強し始める, 説明し続ける — a lexical compound never does). How often it does, in the reference text: its uses
# after a verbal noun + し over all its uses after a verb's stem. The verbs that give a verb its aspect (始める,
# 続ける, 終わる / 終える, 過ぎる) are grammar, those that make new verbs (込む, 上げる, 付ける, 回す, and 出す: 走り出す
# joins) are not: the user's choice, 2026-09-28. The cut sits at the lowest aspect verb's share (終わる), not in the
# gap below it (the user's choice, 2026-09-29): a second verb in the gap — 掛かる, 忘れる, 返す, 置く, 倒す, 切れる —
# makes words (斬りかかる, 言い忘れる, 見つめ返す join). A share is read only from OGO_MIN_USES uses or more, as the
# お / ご share is: a rarer second verb makes words.
# A word UniDic reads whole (見える, 取り掛かる, 思い切る) is never a compound, even where a sentence shows it cut
# (み + える, 取り + 掛かっ): the table's word would carry that word's own key, and its parts would make every use
# of the word look like a compound (見える = 見る + 得る) — `own_words` keeps such entries out.
ASPECT_VERBS = ("始める", "続ける", "終わる", "終える", "過ぎる")
WORD_MAKING_VERBS = ("込む", "上げる", "付ける", "回す", "出す")
VERBAL_NOUNS = ("サ変可能", "サ変形状詞可能")
COUNTER_CLASSES = ("助数詞", "助数詞可能")
# A word the lists read as no count (二十歳 ハタチ, 七節 ナナフシ) joins only where JMdict agrees (`jmdict_counts`;
# the user's choice, 2026-09-29). JMdict's marks of a common word: its priority tags.
PRIORITY_TAGS = ("ichi", "news", "spec", "gai", "nf")
# The organizations, products and works of JMnedict (anki_miner's name wordsets, CC BY-SA 4.0): a compound that
# names one is a title (もののけ姫, 人間失格, 仮面ライダー) — joined, but behind the "Phrases and titles" switch.
# Never a loanword spelled in katakana alone (ソフトバンク, アイフォン): one word either way.
TITLES = os.path.join(LISTS_DIR, "anki_miner_wordsets", "org-product.txt")
JMDICT = os.path.join(LISTS_DIR, "JMdict_e.gz")
FLAG_FRINGE, FLAG_TITLE = 1, 3        # a title is fringe too: the switch's one test (flags & 1) hides both
FLAG_UNLISTED = 4                     # a katakana compound JMdict doesn't list: gives way to a katakana name around it
COMPOUND_REPORT = os.path.join(ROOT, "debug", "compound_joins.md")
SAMPLE = 50
# The switches the tokenizer's joins read (logic.*): shared data never follows the builder's own settings.json.
PARSING_SWITCHES = ("names_katakana", "names_recurring", "names_kanji", "names_work_terms", "phrases_and_titles")


def pin_parsing_defaults():
    """Every switch the joins read at its default (all on): the tables are the same whoever builds them."""
    from app import analyzer, settings_manager
    defaults = settings_manager.DEFAULT_SETTINGS.get("logic", {})
    analyzer.LOGIC.update({name: defaults.get(name, True) for name in PARSING_SWITCHES})


def use_counters(counters):
    """Read text with the counters this build is making (the tokenizer reads reference_data's), never the
    installed table's: a build is a function of its inputs."""
    from app import reference_data
    reference_data._counters = sorted(counters)


def load_list(name):
    """Ranked JSON array -> {word: rank}. Handles the three shapes these lists ship in:
    bare strings, [word, reading] pairs, and (in a couple of files) both mixed together."""
    path = os.path.join(LISTS_DIR, name + ".json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    ranks = {}
    for i, entry in enumerate(raw):
        word = entry[0] if isinstance(entry, list) else entry
        if word not in ranks:          # first occurrence wins = best rank
            ranks[word] = i + 1
    return ranks


def _katakana(text):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


def load_headwords(names):
    """headword -> (its reading (katakana), its best rank) for every headword the join may use: one in
    all the lists, or in one list's top JOIN_ONE_LIST_RANK. The first list's reading where two lists
    disagree; a kanji word listed without a reading is left out: the join takes its reading from the list."""
    readings, ranks = {}, []
    for name in names:
        with open(os.path.join(LISTS_DIR, name + ".json"), "r", encoding="utf-8") as f:
            raw = json.load(f)
        rank = {}
        for i, entry in enumerate(raw):
            word, reading = (entry[0], entry[1]) if isinstance(entry, list) else (entry, None)
            if not word or word in rank:
                continue
            rank[word] = i + 1
            if word in readings:
                continue
            if not reading:
                if not _KANA_ONLY.match(word):
                    continue
                reading = _katakana(word)
            readings[word] = reading
        ranks.append(rank)
    out = {}
    for word, reading in readings.items():
        best = min(r[word] for r in ranks if word in r)
        if best <= JOIN_ONE_LIST_RANK or all(word in r for r in ranks):
            out[word] = (reading, best)
    return out


class ListReadings:
    """One frequency list, read for ranks: (word, reading) -> rank, word -> its best rank, the words it gives a
    reading, and every reading of a spelling (katakana) — 五分 is both ゴブ and ゴフン in JPDB 2024."""

    def __init__(self, name):
        with open(os.path.join(LISTS_DIR, name + ".json"), "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.name, self.pairs, self.words, self.paired, self.readings = name, {}, {}, set(), defaultdict(set)
        for i, entry in enumerate(raw):
            if isinstance(entry, list):
                word, reading = entry[0], (entry[1] if len(entry) > 1 else None)
            else:
                word, reading = entry, None
            if not word:
                continue
            self.words.setdefault(word, i + 1)
            if isinstance(entry, list):
                self.paired.add(word)
            if reading:
                self.pairs.setdefault((word, _katakana(reading)), i + 1)
                self.readings[word].add(_katakana(reading))
            elif _KANA_ONLY.match(word):
                self.readings[word].add(_katakana(word))

    def rank(self, spellings, reading):
        """The best rank of a word spelled any of `spellings` and read `reading` — reading-aware (音 オン is not
        音 おと); a kana word, or one the list keeps without readings, by its spelling alone."""
        best = None
        for s in spellings:
            r = self.pairs.get((s, reading))
            if r is None and (_KANA_ONLY.match(s) or s not in self.paired):
                r = self.words.get(s)
            if r is not None and (best is None or r < best):
                best = r
        return best


class _Every(dict):
    """Every written form, as a join table: what `join_affixes` would join if the dictionary allowed it."""

    def __contains__(self, key):
        return True

    def __getitem__(self, key):
        return [key, ""]

    def __bool__(self):
        return True


def build_joins(tagger, headwords):
    """written form -> [lemma, reading]: each headword that the join, allowed everything, rebuilds from
    its own tokens into exactly one word of that spelling — so the table and `join_affixes` agree by
    construction (a prefix + a word, a word + suffixes; never after a number, never a name's honorific)."""
    every, joins = _Every(), {}
    for word, (reading, _rank) in headwords.items():
        tokens = tagger(word)
        if len(tokens) < 2:
            continue
        joined = _join_affix_runs(tokens, every)
        if len(joined) == 1 and isinstance(joined[0], JoinedWord) and joined[0].feature.orthBase == word:
            joins[word] = [word, reading]
    return joins


def one_lemma_per_spelling(tagger, joins, headwords):
    """`joins` with every spelling of a word under one lemma, the best-ranked spelling's (the user,
    checkpoint A): お勧め / おすすめ / オススメ, ご存じ / 御存じ, 面倒くさい / 面倒臭い are one list word, and
    knowing one knows them all; the text keeps its own spelling (orth). Spellings are one word when
    their pieces have the same lemmas and the lists give them the same reading."""
    groups = defaultdict(list)
    for word, entry in joins.items():
        groups[(tuple(t.feature.lemma for t in tagger(word)), entry[1])].append(word)
    for words in groups.values():
        best = min(words, key=lambda w: (headwords[w][1], w))
        for word in words:
            joins[word][0] = best
    print(f"  {sum(len(w) > 1 for w in groups.values()):,} words written more than one way")
    return joins


# --- Compounds (see above): the parts, the candidates, and the text read with them ---------------------------- #
# The tokenizer's own test of a part (analyzer._compound_part) and its own join (analyzer._join_compounds,
# join_affixes) read the candidates, the text and the parts here, so the table and the tokenizer agree by
# construction.

def _number(word):
    return word.feature.pos2 == "数詞"


def _noun_suffix(word):
    f = word.feature
    return f.pos1 == "接尾辞" and f.pos2 == "名詞的"


def _counter_class(word):
    return word.feature.pos3 in COUNTER_CLASSES


def _counter(word, counters):
    """Does `word` count what a number before it counts? One UniDic files as a counter, or one the lists count
    with (`counters`) — the tokenizer's test (analyzer._counter), with this build's counters."""
    return _counter_class(word) or _read(word) in counters


def _stem(word):
    """A verb's stem that can start a verb + verb compound (走り in 走り出す) — never する's (勉強し始める)."""
    return _compound_part(word, "V") and str(word.feature.cForm).startswith("連用形")


def _verb(word):
    return not word.is_unk and word.feature.pos1 == "動詞"


def _spaced(word):
    return bool(getattr(word, "white_space", ""))


def _base_form(word):
    return word.feature.orthBase or _read(word)


def _snap(word):
    """`word` kept past the tagger's next call (a fugashi node is only valid until then)."""
    if isinstance(word, (JoinedWord, ReadNode)):
        return word
    return ReadNode(word.surface, word.feature, word.is_unk, getattr(word, "white_space", ""))


def _key_lemma(word):
    """A word's lemma as the tokenizer keys it (sanitized: アイリス-iris is アイリス)."""
    return _sanitize_term(word.feature.lemma or word.surface)


def _unvoiced(kana):
    return kana.translate(_VOICED)


def compound_shape(words, word):
    """The kind of compound `words` — `word` read alone, its affixes joined — make of it, or None (see above)."""
    n = len(words)
    if n == 2 and _stem(words[0]) and _compound_part(words[1], "V") and _read(words[0]) + _base_form(words[1]) == word:
        return "V"
    if not 2 <= n <= 4 or "".join(_read(w) for w in words) != word:
        return None
    if n <= 3 and all(_compound_part(w, "N") for w in words):
        return "N"
    if (any(_number(w) for w in words) and not _number(words[-1]) and not _noun_suffix(words[0])
            and all(_compound_part(w, "Q") for w in words)):
        return "Q"
    return None


def plural(words, reading):
    """Does the last word make a plural here — as the list reads it (先生方 センセイガタ, though the tagger reads 方
    ホウ there)? A plural is never joined, as the affix joins never take a plural suffix (analyzer._plural: 等 read
    トウ is none)."""
    return _plural(_read(words[-1]), reading)


def compound_candidates(tagger, headwords, affix):
    """-> ({headword: (kind, its words)}, {verb headword UniDic keeps whole}, {shape: count}, [plurals]): every
    gated headword not in `affix` that the tagger, with the affix joins, reads alone as a compound; and the verbs it
    reads as one word, which a sentence may still show split (取り掛かる, whole alone, is 取り + 掛かる in some)."""
    candidates, verbs, shapes, plurals = {}, set(), Counter(), []
    for word, (reading, _rank) in headwords.items():
        if word in affix:
            continue
        words = [_snap(w) for w in _join_affix_runs(tagger(word), affix)]
        if len(words) == 1:
            if _verb(words[0]) and _base_form(words[0]) == word:
                verbs.add(word)
            shapes["1 word"] += 1
            continue
        kind = compound_shape(words, word)
        if kind is None:
            shapes[f"{min(len(words), 5)} words, no compound"] += 1
            continue
        if plural(words, reading):
            plurals.append(word)
            continue
        candidates[word] = (kind, words)
        shapes[kind + " " + subkind(kind, words)] += 1
    return candidates, verbs, shapes, plurals


def subkind(kind, words):
    """What a candidate's parts are, for the report: plain nouns, with a place, with another proper noun, with a
    な-word."""
    if kind != "N":
        return ""
    f = [w.feature for w in words]
    if any(x.pos1 == "形状詞" for x in f):
        return "na-word"
    if any(x.pos2 == "固有名詞" and x.pos3 == "地名" for x in f):
        return "place"
    if any(x.pos2 == "固有名詞" for x in f):
        return "proper"
    return "plain"


def read_words(tagger, text, affix, compounds=None):
    """`text` as the app reads it from these tables (analyzer.join_affixes: the affix joins, the compounds, a
    compound's own affixes, a sound word + と, a katakana name) — without the library's names."""
    return join_affixes(tagger(text), affix, library=False, compounds=compounds or {})


# --- Numbers: which words holding one join --------------------------------------------------------------------- #

def _lead(words):
    """How many numbers a word's words start with (二十 in 二十歳 is one, 十 + 八 in 十八番 two)."""
    j = 0
    while j < len(words) and _number(words[j]):
        j += 1
    return j


def _number_of(words):
    """The number a word's leading numbers make, by their lemmas (ひと安心 and 一安心 hold the same 一)."""
    return "".join(w.feature.lemma or _read(w) for w in words)


def counters_of(numerals):
    """-> (the counters, the ones the table names): a word the lists carry right after two or more different
    numbers among the words holding one (三人 / 五人, 一冊 / 十冊). UniDic files 人 and 冊 as plain suffixes there,
    so the table names every such word UniDic doesn't always file as a counter; the tokenizer also reads UniDic's own
    class (助数詞) off a word."""
    numbers, unfiled = defaultdict(set), set()
    for words in numerals.values():
        j = _lead(words)
        if 0 < j < len(words):
            x = words[j]
            numbers[_read(x)].add(_number_of(words[:j]))
            if not _counter_class(x):
                unfiled.add(_read(x))
    counters = {x for x, found in numbers.items() if len(found) >= 2}
    return counters, counters & unfiled


class NumeralTest:
    """Which words holding a number join: those whose number counts nothing in them. In order —
      inside        a number after a word of its own (十人十色, 一石二鳥, 世界一周): no count starts there.
      no counter    the word after the number counts nothing (一 + 大事, 一 + 時期).
      not a count   no reading the lists give the word reads its number and counter the way the lists' other
                    counts of that number and that counter do (二十歳 ハタチ against 二十日 ハツカ and 十歳 ジッサイ;
                    十八番 オハコ against 二番 ニバン) — up to voicing (匹 ヒキ / ビキ / ピキ) — and both lists carry
                    the word: a reading only one list gives is often a name's that one parser matched (五十人
                    イソンド, 三千人 ミチト), as the even-odds test found. A spelling that is both a word and a count
                    reads as a count too (五分 ゴブ / ゴフン, 一日 イチニチ / ツイタチ) and stays apart: counts stay
                    apart.
      fixed count   a count built into a longer word whose frame the lists carry with no other number (一日中 — no
                    二日中; 三日坊主, 万年筆), while 十円玉 (百円玉), 三年生 (一年生), 二枚目 (三枚目) stay apart.
      count         the rest: 三日, 五分, 一匹, 三人, 十円玉 — apart.
    A number's readings come from the lists' other counts of it (三 is ミ in 三つ ミッツ), a counter's from their
    other counts of it and from how UniDic reads it in this word — never a number + counter reading made up of
    UniDic's own readings, which miss how Japanese says a count (一匹 is イッピキ, not イチ + ヒキ; 四日 ヨッカ)."""

    CLAUSES = ("inside", "no counter", "not a count", "fixed count", "count")

    def __init__(self, numerals, readings, counters, both=None):
        self.numerals, self.readings, self.counters = numerals, readings, counters
        self.both = both if both is not None else set(numerals)
        self.prefixes = defaultdict(lambda: defaultdict(set))   # number -> counter -> starts of its counts' readings
        self.suffixes = defaultdict(lambda: defaultdict(set))   # counter -> number -> ends of them
        self.frames = defaultdict(set)                           # "#" + the counter and what follows -> numbers
        self.heads, self._clauses = {}, {}
        for word, words in numerals.items():
            j = _lead(words)
            if j == 0 or j >= len(words):
                continue
            number, counter = _number_of(words[:j]), _read(words[j])
            self.frames["#" + "".join(_read(w) for w in words[j:])].add(number)
            heads, clean = self._heads(word, words[j + 1:])
            self.heads[word] = heads
            for head in clean:
                for k in range(1, len(head)):
                    self.prefixes[number][counter].add(head[:k])
                    self.suffixes[counter][number].add(head[k:])

    def _heads(self, word, rest):
        """-> (the readings of `word`'s number and counter, those read cleanly): every list reading of it, unvoiced,
        less the reading of what follows the counter — or, where no reading of that ends it, every start of it (so
        a count stays a count)."""
        readings = {_unvoiced(r) for r in self.readings.get(word, ())}
        if not rest:
            return readings, readings
        tails = {_unvoiced("".join(w.feature.kana or "" for w in rest)),
                 _unvoiced("".join(w.feature.lForm or "" for w in rest))}
        tails |= {_unvoiced(r) for r in self.readings.get("".join(_read(w) for w in rest), ())}
        tails.discard("")
        heads, clean = set(), set()
        for r in readings:
            cut = {r[:-len(t)] for t in tails if r.endswith(t) and len(r) > len(t)}
            if cut:
                heads |= cut
                clean |= cut
            else:
                heads |= {r[:k] for k in range(1, len(r))}
        return heads, clean

    def _starts(self, words, counter):
        """How the number `words` may start a count by another counter than `counter`: as the lists' other counts
        of it start, as the lists and UniDic read it on its own — and, for a number of several words, its first
        words as read on their own and its last as it starts a count (十四日: ジュウ + ヨッ of 四日 ヨッカ)."""
        starts = set().union(*(p for c, p in self.prefixes[_number_of(words)].items() if c != counter))
        starts |= {_unvoiced(r) for r in self.readings.get("".join(_read(w) for w in words), ())}
        starts.add(_unvoiced("".join(w.feature.kana or "" for w in words)))
        if len(words) > 1:
            first = {_unvoiced("".join(w.feature.kana or "" for w in words[:-1]))}
            first |= {_unvoiced(r) for r in self.readings.get("".join(_read(w) for w in words[:-1]), ())}
            starts |= {a + b for a in first for b in self._starts(words[-1:], counter) if a}
        starts.discard("")
        return starts

    def reads_as_count(self, word, words, j):
        number, x = _number_of(words[:j]), words[j]
        counter = _read(x)
        readings = [_unvoiced(r) for r in self.readings.get(word, ())]
        for k in range(len(word) - 1, 1, -1):
            # a count built into a longer word, read as that count is on its own (数日間: 数日 スウジツ + 間)
            head = word[:k]
            if head in self.numerals and self.clause(head) == "count" and any(
                    r.startswith(_unvoiced(c)) for r in readings for c in self.readings.get(head, ())):
                return True
        starts = self._starts(words[:j], counter)
        ends = set().union(*(s for m, s in self.suffixes[counter].items() if m != number))
        ends |= {_unvoiced(x.feature.kana or ""), _unvoiced(x.feature.lForm or "")}
        ends.discard("")
        return any(head[:k] in starts and head[k:] in ends
                   for head in self.heads.get(word, ()) for k in range(1, len(head)))

    def reads_as_count_by(self, word, reading):
        """Does `reading` (katakana) read `word` — a number and its counter, nothing after — as a count, the way the
        lists read that counter's other counts (a reading JMdict gives: `jmdict_counts`)?"""
        words = self.numerals[word]
        j = _lead(words)
        if j != len(words) - 1:
            return False
        x, head = words[j], _unvoiced(reading)
        counter, number = _read(x), _number_of(words[:j])
        starts = self._starts(words[:j], counter)
        ends = set().union(*(s for m, s in self.suffixes[counter].items() if m != number))
        ends |= {_unvoiced(x.feature.kana or ""), _unvoiced(x.feature.lForm or "")}
        ends.discard("")
        return any(head[:k] in starts and head[k:] in ends for k in range(1, len(head)))

    def clause(self, word):
        if word in self._clauses:
            return self._clauses[word]
        self._clauses[word] = clause = self._clause(word)
        return clause

    def _clause(self, word):
        words = self.numerals[word]
        j = _lead(words)
        if any(_number(words[k]) and not _number(words[k - 1]) for k in range(1, len(words))):
            return "inside"
        if not _counter(words[j], self.counters):
            return "no counter"
        if word in self.both and not self.reads_as_count(word, words, j):
            return "not a count"
        if j + 1 < len(words) and len(self.frames["#" + "".join(_read(w) for w in words[j:])]) < 2:
            return "fixed count"
        return "count"


def jmdict_counts(test, clauses, headwords):
    """{word: why} — the words the lists read as no count ("not a count") that JMdict reads as counts
    — they go apart: JMdict lists the spelling read as a count as a word of its own (一期 いっき 'one term', 二七日
    'the 27th'); or gives the word itself a count reading (三位 さんい, 六体 ろくたい) and doesn't mark
    it common — a priority tag on its spelling or its reading, as 二十歳 はたち and 十八番 carry; or says it is usually
    written in kana (七節 ナナフシ, 八町 ハマチ) and doesn't mark it common: its kanji then spell the count. An archaic
    entry reads nothing (二十歳 はたとせ 'twenty years'). A count reading: a number + its counter, read the way the
    lists read that counter's other counts (`NumeralTest.reads_as_count_by`)."""
    try:
        import jmdict_flags
    except ImportError:
        print("  (scripts/jmdict_flags.py is not here: no word holding a number checked against JMdict)")
        return {}
    if not os.path.isfile(JMDICT):
        print(f"  ({os.path.relpath(JMDICT, ROOT)} is not here: no word holding a number checked against JMdict)")
        return {}
    by_kanji, by_kana = index = jmdict_flags.index(jmdict_flags.load(JMDICT))
    hiragana, out = jmdict_flags.hiragana, {}
    for word, clause in clauses.items():
        if clause != "not a count":
            continue
        reading = headwords[word][0]
        read, own = hiragana(reading), jmdict_flags.lookup(index, word, reading)
        common = (any(p.startswith(PRIORITY_TAGS) for e in own for keb, pri, _inf in e["kanji"] if keb == word
                      for p in pri)
                  or any(p.startswith(PRIORITY_TAGS) for e in own for reb, pri, restr, _no, _inf in e["kana"]
                         if hiragana(reb) == read and (not restr or word in restr) for p in pri))
        senses = [s for e in own for s in e["senses"]]
        if senses and all("uk" in s["misc"] for s in senses) and not common:
            out[word] = "usually written in kana"
            continue
        mine = {id(e) for e in own}
        for entry in by_kanji.get(word, ()) or by_kana.get(word, ()):
            if all("arch" in s["misc"] for s in entry["senses"]):
                continue
            for reb, _pri, restr, _no, _inf in entry["kana"]:
                if ((restr and word not in restr) or hiragana(reb) == read
                        or not test.reads_as_count_by(word, _katakana(reb))):
                    continue
                if id(entry) not in mine:
                    out[word] = f"a count of its own ({reb})"
                elif not common:
                    out.setdefault(word, f"read as a count too ({reb})")
    print(f"  JMdict reads {len(out):,} of the words the lists read as no count as counts: "
          + ", ".join(f"{w} {headwords[w][0]} ({why})" for w, why in sorted(out.items())))
    return out


# --- The corpus pass: what the reference text says about each candidate ------------------------------------------ #

def _corpus_texts(rest=False):
    """The shared set's text files, sliced as build_shared.py slices them — or, with `rest`, the rest of
    FORM_SOURCES' files: those past the shared set's slice, and whole sources outside it."""
    paths = []
    for source in (FORM_SOURCES if rest else OGO_SOURCES):
        budget, total = OGO_SOURCES.get(source, 0), 0
        folder = os.path.join(CORPUS_TEXT, source)
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            shared = source in OGO_SOURCES and (budget is None or total < budget)
            if budget:
                with open(path, encoding="utf-8") as f:
                    total += len(f.read())
            if shared != rest:
                paths.append(path)
    return paths


_COUNT = {}


def _count_init(affix, table, counters, parts, pairs, spellings, split_verbs):
    from app.analyzer import Tagger
    pin_parsing_defaults()
    use_counters(counters)
    lengths = defaultdict(set)
    for s in spellings:
        lengths[s[0]].add(len(s))
    _COUNT.update(tagger=Tagger(), affix=affix, table=table, parts=parts, pairs=pairs, spellings=spellings,
                  lengths={c: sorted(v) for c, v in lengths.items()}, split_verbs=split_verbs)


def _count_file(job):
    """-> the counts of one text file: tokens (no punctuation, no space); each noun candidate's part spellings used
    as parts, and a 3-part one's parts side by side; each candidate's joins in the text (read ungated); each noun
    candidate's spelling anywhere in the text; each second verb's uses after a verb's stem, and after a verbal noun +
    し; and the verbs a sentence shows split, with their words."""
    path, form_only = job
    c = _COUNT
    tagger, affix, table = c["tagger"], c["affix"], c["table"]
    parts, pairs, spellings, lengths, split_verbs = c["parts"], c["pairs"], c["spellings"], c["lengths"], c["split_verbs"]
    tokens, uni, big, joined, raw = 0, Counter(), Counter(), Counter(), Counter()
    vv, vv_noun, split = Counter(), Counter(), Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            words = _join_affix_runs(tagger(line), affix)
            n = len(words)
            prev = None
            for i, w in enumerate(() if form_only else words):
                f_ = w.feature
                if f_.pos1 in ("補助記号", "空白"):
                    prev = None
                    continue
                tokens += 1
                s = _read(w)
                if s in parts and _compound_part(w):
                    uni[s] += 1
                    if prev is not None and (prev, s) in pairs and not _spaced(w):
                        big[(prev, s)] += 1
                    prev = s
                else:
                    prev = None
                if f_.pos1 == "動詞" and i + 1 < n and not w.is_unk and str(f_.cForm).startswith("連用形") \
                        and _verb(words[i + 1]) and not _spaced(words[i + 1]):
                    v2 = words[i + 1]
                    vv[v2.feature.lemma] += 1
                    if f_.lemma == "為る":
                        if i and words[i - 1].feature.pos1 == "名詞" and words[i - 1].feature.pos3 in VERBAL_NOUNS:
                            vv_noun[v2.feature.lemma] += 1
                    elif s + _base_form(v2) in split_verbs and _compound_part(v2, "V"):
                        split[(s + _base_form(v2), _key_lemma(w), f_.lForm or "", _key_lemma(v2),
                               v2.feature.lForm or "")] += 1
            before = {id(w) for w in words}
            for w in _join_compounds(words, table):
                if id(w) not in before:
                    joined[w.feature.orthBase] += 1
            text = tagger_text(line)[0]
            for i, ch in enumerate(text):
                for size in lengths.get(ch, ()):
                    if text[i:i + size] in spellings:
                        raw[text[i:i + size]] += 1
    return path, form_only, tokens, uni, big, joined, raw, vv, vv_noun, split


def corpus_pass(affix, candidates, counters, split_verbs, workers=WORKERS):
    """One pass over the shared set's text (`_count_file`), read with the affix joins and every candidate ungated —
    and over the rest of FORM_SOURCES for the compounds' joins and spellings alone (form_join, form_raw: the form
    share). -> {name: the summed counts}."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    table = {w: [w, "", kind, 0, []] for w, (kind, _words) in candidates.items()}
    table.update({v: [v, "", "V", 0, []] for v in split_verbs})
    nouns = {w: words for w, (kind, words) in candidates.items() if kind == "N"}
    parts = frozenset(_read(x) for words in nouns.values() for x in words)
    pairs = frozenset((_read(a), _read(b)) for words in nouns.values() if len(words) == 3
                      for a, b in zip(words, words[1:]))
    jobs = [(p, False) for p in _corpus_texts()] + [(p, True) for p in _corpus_texts(rest=True)]
    jobs.sort(key=lambda job: -os.path.getsize(job[0]))
    out = {"tokens": 0, "uni": Counter(), "big": Counter(), "join": Counter(), "raw": Counter(), "vv": Counter(),
           "vv_noun": Counter(), "split": Counter(), "form_join": Counter(), "form_raw": Counter(),
           "files": sum(not form for _p, form in jobs), "form_files": sum(form for _p, form in jobs)}
    t0 = time.time()
    with ProcessPoolExecutor(workers, multiprocessing.get_context("spawn"), _count_init,
                             (affix, table, frozenset(counters), parts, pairs, frozenset(nouns),
                              frozenset(split_verbs))) as pool:
        for done, result in enumerate(pool.map(_count_file, jobs), 1):
            path, form_only, tokens = result[0], result[1], result[2]
            out["form_join"].update(result[5])
            out["form_raw"].update(result[6])
            if not form_only:
                out["tokens"] += tokens
                for name, counts in zip(("uni", "big", "join", "raw", "vv", "vv_noun", "split"), result[3:]):
                    out[name].update(counts)
            print(f"    {done}/{len(jobs)} {os.path.relpath(path, CORPUS_TEXT)} ({time.time() - t0:.0f} s)", flush=True)
    out["seconds"] = time.time() - t0
    return out


# --- The even-odds test (noun compounds) ------------------------------------------------------------------------- #

class Calibration:
    """rank -> the median count, in the reference text, of a list's compounds at that rank whose parts almost never
    meet by chance (so what the text joins is the word): binned by log-rank, the median per bin, interpolated in
    log-rank, never rarer at a better rank. Compounds occur ~8× less than single words at the same rank, so a curve
    drawn on single words would vouch for almost anything."""

    def __init__(self, points, per_decade=8):
        bins = defaultdict(list)
        for rank, count in points:
            bins[int(math.log10(rank) * per_decade)].append(count)
        xs, ys = [], []
        for b in sorted(bins):
            vals = sorted(bins[b])
            if len(vals) < 15:
                continue
            xs.append((b + 0.5) / per_decade)
            ys.append(vals[len(vals) // 2])
        for i in range(1, len(ys)):
            ys[i] = min(ys[i], ys[i - 1])
        self.xs, self.ys = xs, ys

    def __call__(self, rank):
        if rank is None or not self.xs:
            return 0.0
        x = math.log10(rank)
        if x <= self.xs[0]:
            return float(self.ys[0])
        if x >= self.xs[-1]:
            return float(self.ys[-1])
        i = bisect.bisect_right(self.xs, x)
        x0, x1, y0, y1 = self.xs[i - 1], self.xs[i], self.ys[i - 1], self.ys[i]
        if y0 > 0 and y1 > 0:
            return 10 ** (math.log10(y0) + (math.log10(y1) - math.log10(y0)) * (x - x0) / (x1 - x0))
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def chance(counts, parts):
    """How often the parts (their spellings) would meet side by side by chance: f(A)·f(B) / N, at the split of
    three parts most likely by chance (A + BC or AB + C, a pair counted side by side)."""
    uni, big, total = counts["uni"], counts["big"], counts["tokens"]
    best = 0.0
    for k in range(1, len(parts)):
        left = uni[parts[0]] if k == 1 else big[(parts[0], parts[1])]
        right = uni[parts[-1]] if k == len(parts) - 1 else big[(parts[1], parts[2])]
        if left and right and total:
            best = max(best, left * right / total)
    return best


def even_odds(nouns, counts, lists):
    """-> ({refused headword: its evidence}, {headword: its evidence}) for the noun candidates (`nouns`: headword ->
    its words), by the even-odds test (GATE_MARGIN). The evidence: o the text's joins, e chance's, raw the spelling's
    occurrences anywhere, jpdb / jiten its ranks, est the lists' count, form the share of raw the text joins."""
    first, second = lists
    evidence = {}
    for word, words in nouns.items():
        evidence[word] = {"o": counts["join"][word], "e": chance(counts, [_read(w) for w in words]),
                          "raw": counts.get("form_raw", counts["raw"])[word],
                          "joined": counts.get("form_join", counts["join"])[word],
                          "jpdb": first.words.get(word), "jiten": second.words.get(word)}
    cals = [Calibration([(ev[name], ev["o"]) for ev in evidence.values() if ev[name] and ev["e"] < CALIBRATION_CHANCE])
            for name in ("jpdb", "jiten")]
    refused = {}
    for word, ev in evidence.items():
        both = bool(ev["jpdb"] and ev["jiten"])
        ev["est"] = min(cals[0](ev["jpdb"]), cals[1](ev["jiten"])) if both else 0.0
        ev["form"] = min(1.0, ev["joined"] / ev["raw"]) if ev["raw"] else 1.0
        if ev["e"] < 1 or ev["o"] >= GATE_MARGIN * ev["e"]:
            continue                                    # the text vouches, or chance can't account for it
        if both and ev["est"] * ev["form"] >= ev["e"]:
            continue                                    # the lists vouch
        refused[word] = ev
    return refused, evidence


def aspect_verbs(counts, min_uses=OGO_MIN_USES):
    """-> (the second verbs that are grammar, the cut, {verb: (uses after a stem, after a verbal noun + し, share)},
    (the highest word-making share, the lowest aspect share)) — see ASPECT_VERBS."""
    table = {v: (n, counts["vv_noun"][v], counts["vv_noun"][v] / n) for v, n in counts["vv"].items() if n}
    share = {v: table[v][2] if v in table and table[v][0] >= min_uses else 0.0
             for v in ASPECT_VERBS + WORD_MAKING_VERBS}
    low, high = max(share[v] for v in WORD_MAKING_VERBS), min(share[v] for v in ASPECT_VERBS)
    if high <= low:
        print(f"  !! the aspect verbs ({high:.2%}) are not all above the word-making ones ({low:.2%})")
    cut = high
    grammar = {v for v, (n, _m, s) in table.items() if n >= min_uses and s >= cut}
    return grammar, cut, table, (low, high)


# --- Parts, and whether each is free ----------------------------------------------------------------------------- #

def own_words(tagger, table, affix):
    """The entries of `table` that are no compound: their key — (lemma, reading), as the tokenizer keys a word — is
    the key of a word the tagger reads whole on its own (見える: 見える ミエル). A compound keyed like a plain word
    would make every use of that word look like the compound to whatever reads the compounds' parts."""
    out = []
    for word, entry in table.items():
        words = read_words(tagger, entry[0], affix)
        if len(words) == 1:
            f = words[0].feature
            if (_sanitize_term(f.lemma or words[0].surface), f.lForm or f.kana or "") == \
                    (_sanitize_term(entry[0]), entry[1]):
                out.append(word)
    return out


def own_parts(table):
    """The entries of `table` one of whose parts is the entry itself (its key among its parts' keys) — no word is
    made of itself."""
    return [w for w, e in table.items() if any((p[0], p[1]) == (_sanitize_term(e[0]), e[1]) for p in e[4])]


def kana_non_verbs(table):
    """The verb + verb entries of `table` spelled in kana alone that JMdict lists at their reading, but never as a
    verb: the tagger found two verbs in the kana by chance (きおく 'memory' read 来 + 置く, くんいく 'education' read
    呉れる + 行く). Kanji say which verbs a spelling holds (滅びゆく, which JMdict lists only as a noun's modifier, is
    滅びる + 行く all the same); kana alone doesn't. A kana spelling JMdict doesn't list keeps its entry. A verb, in
    JMdict: a part of speech of a verb's class (v1, v5k, vs-i …) — not vs (a noun that takes する) nor vt / vi."""
    try:
        import jmdict_flags
    except ImportError:
        print("  (scripts/jmdict_flags.py is not here: no kana verb checked against JMdict)")
        return []
    if not os.path.isfile(JMDICT):
        print(f"  ({os.path.relpath(JMDICT, ROOT)} is not here: no kana verb checked against JMdict)")
        return []
    index = jmdict_flags.index(jmdict_flags.load(JMDICT))
    out = []
    for word, entry in table.items():
        if entry[2] != "V" or not _KANA_ONLY.match(word):
            continue
        found = jmdict_flags.lookup(index, word, entry[1])
        if found and not any(p.startswith("v") and p not in ("vs", "vt", "vi")
                             for e in found for sense in e["senses"] for p in sense["pos"]):
            out.append(word)
    return out


def compound_parts(table, words_of, lists):
    """Fill each entry's parts: the spelling as the tokenizer reads it with every other entry of the table (so a
    3-part word shows a 2-part word inside it: 経済成長期 -> 経済成長 + 期), each [lemma, reading, free] — free when
    JPDB 2024 or Jiten ranks the part (reading-aware) no worse than the compound: the lists count a word only where
    it isn't inside a longer headword, so a part ranked at least as well lives outside the compound (撤回 in
    前言撤回); one ranked worse, or in neither list, is bound (千載一遇's 千載 and 一遇). A number is never free: it
    is no word. A compound neither list knows keeps a part free when some list knows the part."""
    parts_of, surfaces, order = {}, defaultdict(set), list(table)
    for word, entry in list(table.items()):
        words = words_of[word]
        if entry[2] != "V" and len(words) > 2:
            del table[word]                 # read without itself (the tokenizer's lookups stay cached on the table)
            words = _join_compounds(words, table)
            table[word] = entry
        parts = []
        for w in words:
            lemma = w.feature.lemma if isinstance(w, JoinedWord) else _key_lemma(w)
            reading = w.feature.lForm or w.feature.kana or ""
            parts.append((lemma, reading, _number(w)))
            surfaces[(lemma, reading)].add(_read(w))
        parts_of[word] = parts
    entries = dict(table)
    table.clear()
    table.update((word, entries[word]) for word in order)
    spellings = defaultdict(set)
    for word, entry in table.items():
        spellings[(entry[0], entry[1])].add(word)
    for word, entry in table.items():
        group = spellings[(entry[0], entry[1])]
        out = []
        for lemma, reading, number in parts_of[word]:
            free = 0
            if not number:
                names = {lemma} | surfaces[(lemma, reading)]
                verdicts = []
                for lst in lists:
                    whole = lst.rank(group, entry[1])
                    if whole is not None:
                        part = lst.rank(names, reading)
                        verdicts.append(part is not None and part <= whole)
                free = int(any(verdicts) if verdicts else any(lst.rank(names, reading) for lst in lists))
            out.append([lemma, reading, free])
        entry[4] = out
    return table


def affix_pass_two(tagger, headwords, affix, compounds):
    """written form -> [lemma, reading]: each headword not yet a word that a compound makes with its affixes
    (同性愛 + 者 = 同性愛者, 新 + 自由主義): read with the affix joins, then the compounds, then the affix join
    allowed everything, it comes out one word of its own spelling. The tokenizer joins it the same way — the compound
    first, then its affixes."""
    every, found = _Every(), {}
    for word, (reading, _rank) in headwords.items():
        if word in affix or word in compounds:
            continue
        words = [_snap(w) for w in _join_affix_runs(tagger(word), affix)]
        if len(words) < 2:
            continue
        joined = _join_compounds(words, compounds)
        if joined is words:
            continue
        out = _join_affix_runs(joined, every)
        if len(out) == 1 and isinstance(out[0], JoinedWord) and out[0].feature.orthBase == word:
            found[word] = [word, reading]
    return found


# --- お / ご / 御 ------------------------------------------------------------------------------------------------ #

_OGO = {}


def _ogo_init(joins, bases, affix=None, compounds=None, counters=frozenset()):
    from app.analyzer import Tagger
    pin_parsing_defaults()
    use_counters(counters)
    _OGO.update(tagger=Tagger(), joins=joins if affix is None else affix, bases=bases, compounds=compounds)


def _noun_use(nxt):
    """Is a verb's 連用形 (願い) used as a noun here — before a particle, the copula, punctuation or the
    end — rather than as a verb (願います, 願いたい, 願って)?"""
    if nxt is None:
        return True
    f = nxt.feature
    return (f.pos1 in ("補助記号", "空白") or (f.pos1 == "助詞" and f.pos2 != "接続助詞")
            or (f.pos1 == "助動詞" and f.lemma in ("だ", "です")))


def _ogo_count(path):
    """-> (Counter of お/ご words, Counter of their bare words) in one text file. A bare noun is counted
    by its key, a verb's 連用形 used as a noun by its key and surface (お願い's 願い, not every ねがい), a
    compound (味噌汁, for お味噌汁) by its key."""
    tagger, joins, bases, compounds = _OGO["tagger"], _OGO["joins"], _OGO["bases"], _OGO["compounds"]
    prefixed, bare = Counter(), Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            words = read_words(tagger, line.rstrip("\n"), joins, compounds)
            for i, w in enumerate(words):
                if isinstance(w, JoinedWord):
                    if w.feature.orthBase in bases["words"]:
                        prefixed[w.feature.orthBase] += 1
                        continue
                    if not compounds:
                        continue
                f_ = w.feature
                key = (f_.lemma, f_.lForm)
                if key not in bases["nouns"] and key not in bases["verbs"]:
                    continue
                prev = words[i - 1] if i else None
                if prev is not None and not isinstance(prev, JoinedWord) and prev.feature.lemma == "御":
                    continue            # お名前 not joined: neither the prefixed word nor the bare one
                if key in bases["nouns"]:
                    bare[key] += 1
                if (key in bases["verbs"] and str(f_.cForm).startswith("連用形") and w.surface in bases["verbs"][key]
                        and _noun_use(words[i + 1] if i + 1 < len(words) else None)):
                    bare[key + (w.surface,)] += 1
    return prefixed, bare


def _bare_keys(tagger, word, reading, affix=None, compounds=None):
    """-> (what follows the prefix, the keys its bare word is counted under) for an お / ご / 御 word, with
    the keys None for a word of its own that has more than a word after the prefix (お調子者); None for any
    other word, and for one that ends in an honorific — a word of its own that keeps its own lemma too:
    grouped across tags, お義母さん (read おかあさん) would fall in with お母さん. The prefix is any 御 (UniDic
    files it as a noun in 御内, 御付き). A noun base is counted under its key; a verb's 連用形 under its key
    and surface (お願い's 願い, not every ねがい) and, written with a kanji, under the common noun of the same
    written form too (お帰り: 帰りが遅い) — each only where it reads as the お word ends (ご利益 is no 利益 りえき).
    With `compounds`, a compound after the prefix is its base (お味噌汁's 味噌汁), weighed like any
    noun."""
    tokens = tagger(word)
    if len(tokens) < 2 or tokens[0].feature.lemma != "御" \
            or tokens[-1].surface in HONORIFICS or tokens[-1].feature.lemma in HONORIFICS:
        return None
    rest = "".join(t.surface for t in tokens[1:])
    if len(tokens) > 2:
        if compounds:
            inner = _join_affix_runs([_snap(t) for t in tokens[1:]], affix or {})
            inner = _join_compounds(inner, compounds)
            if len(inner) == 1 and isinstance(inner[0], JoinedWord) and inner[0].feature.orthBase in compounds \
                    and inner[0].feature.pos1 == "名詞":
                base = inner[0].feature
                return rest, {(base.lemma, base.lForm)} if reading.endswith(base.lForm) else set()
        return rest, None
    base, surface = tokens[1].feature, tokens[1].surface
    key = (base.lemma, base.lForm)
    if base.pos1 != "動詞":
        return rest, {key} if reading.endswith(base.lForm) else set()
    keys = {key + (surface,)}
    alone = tagger(surface)
    if len(alone) == 1 and alone[0].feature.pos2 == "普通名詞" and _KANJI.search(surface) \
            and reading.endswith(alone[0].feature.lForm):
        keys.add((alone[0].feature.lemma, alone[0].feature.lForm))
    return rest, keys


def _ogo_groups(joins, rest):
    """The お / ご / 御 spellings of one word, decided together and listed under one lemma (U16): the
    spellings `one_lemma_per_spelling` put under one lemma, and — however UniDic tags each one's base — the
    words the lists read alike whose bases share a kanji (お話 / お話し, お休み / 御休み, お願い / 御願い),
    with a kana base joining the one such word of its reading (おやすみ). `rest` maps a word to what
    follows its prefix. Homophones keep apart (お腰 / お越し), and so does a kana spelling of two (おだい)."""
    parent = {w: w for w in rest}

    def find(w):
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w

    by_lemma, by_reading = defaultdict(list), defaultdict(list)
    for word in rest:
        by_lemma[joins[word][0]].append(word)
        by_reading[joins[word][1]].append(word)
    for words in by_lemma.values():
        for word in words[1:]:
            parent[find(word)] = find(words[0])
    for words in by_reading.values():
        kanji = [w for w in words if _KANJI.search(rest[w])]
        for n, a in enumerate(kanji):
            for b in kanji[n + 1:]:
                if set(_KANJI.findall(rest[a])) & set(_KANJI.findall(rest[b])):
                    parent[find(a)] = find(b)
        roots = {find(w) for w in kanji}
        if len(roots) == 1:
            for word in words:
                if not _KANJI.search(rest[word]):
                    parent[find(word)] = find(kanji[0])
    groups = defaultdict(list)
    for word in rest:
        groups[find(word)].append(word)
    return list(groups.values())


def ogo_filter(tagger, joins, headwords, workers=WORKERS, affix=None, compounds=None, counters=frozenset(),
               report=OGO_REPORT):
    """-> (`joins` without the お / ご / 御 words that are not a usual form of their word, {each word left split:
    [its word's lemma, reading]}) — by OGO_SHARE, U1, or OGO_TALK_SHARE in conversation, each word decided once
    for all its spellings, which share its best-ranked spelling's lemma (`_ogo_groups`), its bare word counted
    however UniDic tags it (`_bare_keys`). A word of its own stays whatever its share: one that ends in an
    honorific, one with more than a word after its prefix (お調子者, お墨付き — or a kana word the tagger cut up:
    おこりっぽい), and one whose base the text never reads as the お word does (ご利益 ごりやく is no 利益 りえき).
    The sweep of 2026-09-25 found the first version counted a verb's 連用形 by its last spelling's surface only —
    お帰り 86% against it, 20% against all of 帰り's uses — and decided spellings the tagger files differently
    apart (お休み joined, おやすみ split). The text is read with `affix` (default `joins`) and, when given, the
    `compounds`, which also make a compound after the prefix its base (お味噌汁 against 味噌汁).
    Writes the table it decided by to `report` (debug/, gitignored) for the user to read."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    rest, keys, nouns, verbs = {}, {}, set(), defaultdict(set)
    for word, (_lemma, reading) in joins.items():
        found = _bare_keys(tagger, word, reading, affix or joins, compounds)
        if found is None:
            continue
        rest[word], word_keys = found
        if word_keys is None:
            continue                    # a word of its own, unless a spelling of it is a prefix + a word
        keys[word] = word_keys
        for k in word_keys:
            if len(k) == 3:
                verbs[k[:2]].add(k[2])
            else:
                nouns.add(k)
    bases = {"words": frozenset(rest), "nouns": frozenset(nouns),
             "verbs": {k: frozenset(v) for k, v in verbs.items()}}
    paths = _corpus_texts()
    prefixed, bare, talk_prefixed, talk_bare = Counter(), Counter(), Counter(), Counter()
    with ProcessPoolExecutor(workers, multiprocessing.get_context("spawn"), _ogo_init,
                             (joins, bases, affix, compounds, frozenset(counters))) as pool:
        for path, (p, b) in zip(paths, pool.map(_ogo_count, paths)):
            prefixed.update(p)
            bare.update(b)
            if os.path.basename(os.path.dirname(path)) == OGO_TALK:
                talk_prefixed.update(p)
                talk_bare.update(b)
    kept, split, rows, own, members = dict(joins), {}, [], 0, defaultdict(list)
    for word, (lemma, _reading) in joins.items():
        members[lemma].append(word)
    for words in _ogo_groups(joins, rest):
        best = min(words, key=lambda w: (headwords[w][1], w))
        lemmas, lemma = {joins[w][0] for w in words}, joins[best][0]
        pairs = [w for w in words if w in keys]
        group_keys = set().union(*(keys[w] for w in pairs)) if pairs else set()
        if group_keys:
            uses, talk = sum(prefixed[w] for w in words), sum(talk_prefixed[w] for w in words)
            b, tb = sum(bare[k] for k in group_keys), sum(talk_bare[k] for k in group_keys)
            share = uses / (uses + b) if uses + b else 0.0
            talk_share = talk / (talk + tb) if talk + tb else 0.0
            joined = ((uses >= OGO_MIN_USES and share >= OGO_SHARE)
                      or (talk >= OGO_MIN_USES and talk_share >= OGO_TALK_SHARE))
            if uses >= OGO_MIN_USES or talk >= OGO_MIN_USES:
                rows.append((" / ".join(sorted(words, key=lambda w: (w != best, w))), uses, b, share,
                             talk, talk_share, joined))
        else:
            joined, own = True, own + 1
        # every table word of them (御内 is おうち), in one order whatever the set's: the tables come out the same
        for word in (w for old in sorted(lemmas) for w in members[old]):
            if joined:
                kept[word] = [lemma, joins[word][1]]
            else:
                kept.pop(word, None)
                split[word] = [lemma, joins[word][1]]
    rows.sort(key=lambda r: (-max(r[3], r[5]), r[0]))
    os.makedirs(os.path.dirname(report), exist_ok=True)
    with open(report, "w", encoding="utf-8") as f:
        f.write(f"# お / ご / 御 words — joined at a share of at least {OGO_SHARE:.0%}, or {OGO_TALK_SHARE:.0%} "
                f"in conversation ({date.today()})\n\n"
                f"Over the shared set's text, and its conversation ({OGO_TALK}) alone; words with at least "
                f"{OGO_MIN_USES} prefixed uses in either, all spellings of a word together (the first is the "
                f"list word). {sum(r[6] for r in rows)} join, {sum(not r[6] for r in rows)} stay a prefix + a "
                f"word. Words of their own always join and are not listed: those that end in an honorific "
                f"(お母さん, お客様), and {own:,} more — a compound after the prefix (お調子者) or a reading of its "
                f"own (ご利益 ごりやく).\n\n"
                "| word | prefixed | bare | share | in conversation | share there | joined |\n"
                "| :-- | --: | --: | --: | --: | --: | :-- |\n")
        f.writelines(f"| {w} | {u:,} | {b:,} | {s:.0%} | {t:,} | {ts:.0%} | {'yes' if j else 'no'} |\n"
                     for w, u, b, s, t, ts, j in rows)
    print(f"  お/ご words: {len(rest):,} in the lists, {len(rows):,} words with ≥ {OGO_MIN_USES} uses, "
          f"{sum(r[6] for r in rows):,} joined, {own:,} words of their own (report: {report})")
    return kept, split


# --- The dictionaries' flags (app/dictionary_data.py) ------------------------------------------------------------ #

_KATAKANA = re.compile(r"^[゠-ヿー]+$")


def titles(compounds):
    """{spelling: FLAG_TITLE} for the compounds that name an organization, a product or a work in JMnedict — never a
    loanword spelled in katakana alone (ソフトバンク): it stays one word with the switch off too. Where JMdict is here,
    a title it also lists as a word is left out (`dictionary_flags`)."""
    if not os.path.isfile(TITLES):
        print(f"  ({os.path.relpath(TITLES, ROOT)} is not here: no titles flagged)")
        return {}
    with open(TITLES, encoding="utf-8") as f:
        names = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    return {word: FLAG_TITLE for word in compounds if word in names and not _KATAKANA.match(word)}


def dictionary_flags(compounds, ogo_split):
    """-> (flags {spelling: int}, お / ご words JMdict makes words of their own {spelling: [lemma, reading]},
    JMdict's date or None, what was skipped): JMnedict's titles; and JMdict's phrases, the katakana compounds it
    doesn't list and the お / ご words of their own when both its file and its reader (scripts/jmdict_flags.py) are
    here."""
    flags, ogo, created, skipped = titles(compounds), {}, None, []
    try:
        import jmdict_flags
    except ImportError:
        jmdict_flags = None
        skipped.append("scripts/jmdict_flags.py is not here")
    if not os.path.isfile(JMDICT):
        skipped.append(f"{os.path.relpath(JMDICT, ROOT)} is not here")
    if skipped:
        print("  JMdict skipped (" + "; ".join(skipped) + "): the switch hides titles only, and no お / ご word "
              "joins by JMdict")
        return flags, ogo, created, skipped
    created = jmdict_flags.created(JMDICT)
    entries = jmdict_flags.load(JMDICT)
    index = jmdict_flags.index(entries)
    for word in list(flags):
        # a title JMdict also lists as a word of its own (威風堂々 'majestic', 赤ずきん) is a word first: never hidden
        if any(not jmdict_flags.NAME_TAGS.intersection(sense["misc"])
               for entry in jmdict_flags.lookup(index, word, compounds[word][1]) for sense in entry["senses"]):
            del flags[word]
    for word, bits in jmdict_flags.fringe(entries, compounds).items():
        flags[word] = flags.get(word, 0) | bits
    for word, bits in jmdict_flags.unlisted(entries, compounds).items():
        flags[word] = flags.get(word, 0) | bits
    ogo = dict(jmdict_flags.ogo_exceptions(entries, ogo_split))
    print(f"  JMdict ({created}): {sum(1 for b in flags.values() if b & FLAG_FRINGE):,} behind the switch, "
          f"{sum(1 for b in flags.values() if b & FLAG_UNLISTED):,} katakana compounds it doesn't list, "
          f"{len(ogo):,} お / ご words of their own")
    return flags, ogo, created, skipped


def stretched(tagger, word):
    """Is `word` a stretched spelling — one the analyzer reads as another word's spelling, its stretched vowel
    taken as one ー or dropped (analyzer § A stretched vowel)? シリ〜ズ is read シリーズ, ド〜ン ドーン, しゃーない
    without its ー. Such a spelling is its word said longer, never the spelling a list uses for the word."""
    if _stretched("".join(_SAME_CHARACTER.get(c, c) for c in word)):
        return True
    read, at = tagger_text(word)
    return bool(_STRETCH_DROPPED_RE.search(read)) and bool(_lone_marks(read, at, tagger._tagger(read)))


def build_aliases(tagger, vocabularies, joins=None, compounds=None):
    """lemma -> the best-ranked spelling that produces it.

    Collisions are the subtle part: many spellings collapse to one lemma (する, し, しぃ all
    give 為る), and taking the LAST one seen yields nonsense like 為る -> しぃ. Keep the
    lowest-ranked (most common) spelling instead, so 為る -> する. Words are read as the
    analyzer reads them (`read_words`: the affix joins and the compounds); a stretched spelling is
    skipped (`stretched`).
    """
    best = {}
    for ranks in vocabularies:
        for word, rank in ranks.items():
            if stretched(tagger, word):
                continue               # read as its word said longer: シリ〜ズ would become シリーズ's spelling
            tokens = read_words(tagger, word, joins or {}, compounds)
            if len(tokens) != 1:
                continue               # multi-token entries would key on a misleading lemma
            lemma = tokens[0].feature.lemma or word
            lemma = lemma.split("-")[0]        # unidic gloss suffix, as the analyzer strips it
            if lemma == word:
                continue               # no bridge needed
            if lemma not in best or rank < best[lemma][1]:
                best[lemma] = (word, rank)
    return {lemma: word for lemma, (word, _rank) in best.items()}


def geometric_mean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values))


def blob(obj):
    return base64.b64encode(
        zlib.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    ).decode("ascii")


def build_compounds(tagger, headwords, affix, lists, workers=WORKERS):
    """The compound table (see "Compounds") before its parts, and how it was decided (for the report). -> dict."""
    print("\nFinding the compounds (reading the headwords alone)...")
    candidates, verbs, shapes, plurals = compound_candidates(tagger, headwords, affix)
    for shape, n in sorted(shapes.items()):
        print(f"  {shape:<28} {n:>8,}")
    print(f"  plurals kept out: {len(plurals):,}")
    numerals = {w: words for w, (kind, words) in candidates.items() if kind == "Q"}
    counters, named = counters_of(numerals)
    print(f"  counters: {len(counters):,} after two or more numbers, {len(named):,} of them for the table")

    print(f"\nReading the reference text ({workers} processes)...")
    counts = corpus_pass(affix, candidates, named, verbs, workers)
    print(f"  {counts['tokens']:,} tokens in {counts['files']} files (and {counts['form_files']} more for the form "
          f"share), {counts['seconds']:.0f} s")

    nouns = {w: words for w, (kind, words) in candidates.items() if kind == "N"}
    refused, evidence = even_odds(nouns, counts, lists)
    print(f"  even odds: {len(refused):,} of {len(nouns):,} noun compounds refused")

    readings = defaultdict(set)
    for lst in lists:
        for word, rs in lst.readings.items():
            readings[word] |= rs
    test = NumeralTest(numerals, readings, counters, {w for w in numerals if all(lst.words.get(w) for lst in lists)})
    clauses = {w: test.clause(w) for w in numerals}
    jmdict_apart = jmdict_counts(test, clauses, headwords)
    clauses.update((w, "count") for w in jmdict_apart)
    print("  numbers: " + ", ".join(f"{c} {sum(1 for x in clauses.values() if x == c):,}" for c in test.CLAUSES))

    grammar, cut, verb_table, gap = aspect_verbs(counts)
    print(f"  verb + verb: cut at {cut:.2%} (the aspect verbs' lowest; the word-making verbs' highest {gap[0]:.2%}); "
          "second verbs that are grammar: "
          + ", ".join(f"{v} {verb_table[v][2]:.1%}" for v in sorted(grammar, key=lambda v: -verb_table[v][2])))
    split = {}
    for (key, l1, r1, l2, r2), n in counts["split"].most_common():
        if key not in split:
            split[key] = [n, [(l1, r1), (l2, r2)]]
        else:
            split[key][0] += n

    table, words_of, in_context = {}, {}, {}
    for word, (kind, words) in candidates.items():
        if ((kind == "N" and word in refused) or (kind == "V" and words[1].feature.lemma in grammar)
                or (kind == "Q" and clauses[word] == "count")):
            continue
        table[word] = [word, headwords[word][0], kind, 0, []]
        words_of[word] = words
    for word, (n, _parts) in split.items():
        if word not in table and word in headwords:
            in_context[word] = n            # reported, never joined: a word UniDic reads whole (see ASPECT_VERBS)
    one_lemma_per_spelling(tagger, table, headwords)
    own = own_words(tagger, table, affix)
    for word in own:
        del table[word]
    not_verbs = kana_non_verbs(table)
    for word in not_verbs:
        del table[word]
    print(f"  kana spellings JMdict lists but never as a verb, kept out: {len(not_verbs):,}"
          + (" (" + ", ".join(not_verbs) + ")" if not_verbs else ""))
    fixed = {w for w, c in clauses.items() if c == "fixed count"}
    print(f"  table: {len(table):,} (" + ", ".join(f"{k} {sum(1 for e in table.values() if e[2] == k):,}"
                                                   for k in COMPOUND_KINDS)
          + f"); {len(own):,} kept out as words UniDic reads whole; {len(in_context):,} such verbs a sentence shows "
            f"split, not joined; {len(fixed):,} fixed counts")
    return {"table": table, "candidates": candidates, "verbs": verbs, "shapes": shapes, "plurals": plurals,
            "counters": counters, "named": named, "counts": counts, "refused": refused, "evidence": evidence,
            "clauses": clauses, "fixed": fixed, "grammar": grammar, "cut": cut, "verb_table": verb_table,
            "gap": gap, "split": split, "in_context": in_context, "words_of": words_of, "own": own,
            "jmdict_apart": jmdict_apart, "not_verbs": not_verbs}


def main():
    from app.analyzer import Tagger
    t_start = time.time()
    pin_parsing_defaults()
    use_counters(())
    tagger = Tagger()

    print("Loading reference lists...")
    spoken = [load_list(n) for n in SPOKEN_LISTS]
    written = load_list(WRITTEN_LIST)
    veto = load_list(VETO_LIST)
    for name, lst in zip(SPOKEN_LISTS + [WRITTEN_LIST, VETO_LIST], spoken + [written, veto]):
        print(f"  {name:<24} {len(lst):>8,} entries")

    # Ranks are only comparable where both corpora can see: a word past the shorter list's
    # end isn't "rarer", it's unmeasured.
    horizon = min(len(l) for l in spoken)
    print(f"\nSpoken horizon: {horizon:,}")

    print("\nBuilding the affix joins (tokenizing the dictionaries' headwords)...")
    headwords = load_headwords(JOIN_LISTS)
    affix, ogo_split = ogo_filter(tagger, one_lemma_per_spelling(tagger, build_joins(tagger, headwords), headwords),
                                  headwords)
    print(f"  {len(headwords):,} headwords, {len(affix):,} joins")

    lists = [ListReadings(name) for name in JOIN_LISTS]
    built = build_compounds(tagger, headwords, affix, lists)
    table, counters = built["table"], built["counters"]
    use_counters(built["named"])
    compound_parts(table, built["words_of"], lists)
    for word in own_parts(table):
        print(f"  !! {word} holds itself among its parts: kept out")
        del table[word]
    compounds = table

    print("\nA compound's affixes (the affix joins' second pass)...")
    second = affix_pass_two(tagger, headwords, affix, compounds)
    # one lemma per spelling among the new words only: the first pass's words already have theirs, and the お / ご
    # words theirs across UniDic's tags (おやすみ with お休み), which grouping by the tagger's lemmas again would undo
    one_lemma_per_spelling(tagger, second, headwords)
    union = {w: list(e) for w, e in affix.items()}
    union.update(second)
    decided, split_two = ogo_filter(tagger, {w: union[w] for w in second}, headwords, affix=union,
                                    compounds=compounds, counters=built["named"],
                                    report=OGO_REPORT.replace(".md", "_compounds.md"))
    joins = {w: e for w, e in union.items() if w not in second}
    joins.update(decided)
    ogo_split.update(split_two)
    print(f"  {len(second):,} words a compound makes with its affixes, {len(decided):,} of them kept; "
          f"{len(joins):,} joins")

    print("\nThe dictionaries' flags...")
    flags, ogo, created, skipped = dictionary_flags(table, ogo_split)
    # From here words are read with the flags merged in, as the app merges them (analyzer.compound_joins): a katakana
    # compound JMdict doesn't list gives way to a katakana name around it. The table as stored keeps its 0s.
    compounds = {w: e[:3] + [e[3] | flags.get(w, 0)] for w, e in table.items()}

    print("\nBuilding alias map (tokenizing reference vocabulary)...")
    aliases = build_aliases(tagger, spoken + [written], joins, compounds)
    print(f"  {len(aliases):,} aliases")

    print("\nBuilding spoken-rank table...")
    spoken_rank = {}
    dropped = {"cap": 0, "nonjp": 0, "multi": 0, "pos": 0, "veto": 0}
    for word, w_rank in written.items():
        if w_rank > WRITTEN_RANK_CAP:
            dropped["cap"] += 1
            continue
        if len(word) < 2 or not _JP.search(word):
            dropped["nonjp"] += 1
            continue

        present = [r[word] for r in spoken if word in r and r[word] <= horizon]
        rank = int(geometric_mean(present)) if present else 0     # 0 = beyond the corpora

        v = veto.get(word)
        if v and all("぀" <= c <= "ヿ" or c == "ー" for c in word):
            effective = rank if rank else horizon * 2
            if effective / v >= VETO_RATIO:
                dropped["veto"] += 1
                continue

        tokens = read_words(tagger, word, joins, compounds)
        if len(tokens) != 1:
            dropped["multi"] += 1
            continue
        feature = tokens[0].feature
        if feature.pos1 in DROP_POS1 or feature.pos2 in DROP_POS2:
            dropped["pos"] += 1
            continue

        spoken_rank[word] = rank

    for key, n in dropped.items():
        print(f"  dropped ({key:<6}) {n:>8,}")
    print(f"  KEPT              {len(spoken_rank):>8,}")

    b64 = {"aliases": blob(aliases), "spoken": blob(spoken_rank), "joins": blob(joins),
           "compounds": blob(compact_compounds(table)), "parts": blob(compact_parts(table)),
           "counters": blob(sorted(built["named"]))}
    print("\nEncoded: " + ", ".join(f"{name} {len(v) / 1024:,.0f} KB" for name, v in b64.items()))

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(MODULE_TEMPLATE.format(
            revision=date.today().isoformat(),
            n_aliases=len(aliases),
            n_spoken=len(spoken_rank),
            n_joins=len(joins),
            n_compounds=len(table),
            n_kinds=", ".join(f"{sum(1 for e in table.values() if e[2] == k):,} {k}" for k in COMPOUND_KINDS),
            n_counters=len(built["named"]),
            cap=f"{WRITTEN_RANK_CAP:,}",
            spoken_lists=" + ".join(SPOKEN_LISTS),
            written_list=WRITTEN_LIST,
            join_lists=" + ".join(JOIN_LISTS),
            one_list_rank=f"{JOIN_ONE_LIST_RANK:,}",
            ogo_share=f"{OGO_SHARE:.0%}",
            talk_share=f"{OGO_TALK_SHARE:.0%}",
            aliases_b64=b64["aliases"],
            spoken_b64=b64["spoken"],
            joins_b64=b64["joins"],
            compounds_b64=b64["compounds"],
            parts_b64=b64["parts"],
            counters_b64=b64["counters"],
        ))
    print(f"\nWrote {OUTPUT} ({os.path.getsize(OUTPUT)/1024:,.0f} KB)")
    write_dictionary_data(flags, ogo, created)
    built.update(affix=affix, second=second, decided=decided, flags=flags, ogo=ogo, created=created,
                 skipped=skipped, joins=joins, aliases=aliases, spoken_rank=spoken_rank, headwords=headwords,
                 seconds=time.time() - t_start, sizes={k: len(v) for k, v in b64.items()})
    write_report(built, COMPOUND_REPORT)
    print(f"\nDone in {time.time() - t_start:.0f} s")
    return built


def compact_compounds(table):
    """COMPOUND_JOINS as stored: each lemma as the tokenizer keys it (sanitized, as with SANITIZE_JA), and "" for a
    lemma that is the spelling itself (the module puts the spelling's own string back: one object in memory)."""
    out = {}
    for w, e in table.items():
        lemma = _sanitize_term(e[0])
        out[w] = ["" if lemma == w else lemma, e[1], e[2], e[3]]
    return out


def compact_parts(table):
    """COMPOUND_PARTS as stored: every distinct part once, and each compound's parts as indexes into that list (the
    module shares one list per part — 部, 会 and 的 stand in thousands of compounds)."""
    unique, index, of = [], {}, {}
    for word, entry in table.items():
        ids = []
        for part in entry[4]:
            key = (_sanitize_term(part[0]), part[1], part[2])
            if key not in index:
                index[key] = len(unique)
                unique.append(list(key))
            ids.append(index[key])
        of[word] = ids
    return {"parts": unique, "of": of}


def write_dictionary_data(flags, ogo, created):
    sources = "JMnedict" + (f" and JMdict (JMdict created {created})" if created else "")
    with open(DICTIONARY_OUTPUT, "w", encoding="utf-8") as f:
        f.write(DICTIONARY_TEMPLATE.format(
            revision=date.today().isoformat(), created=created or "", sources=sources, n_flags=len(flags),
            n_titles=sum(1 for b in flags.values() if b & FLAG_TITLE == FLAG_TITLE),
            n_unlisted=sum(1 for b in flags.values() if b & FLAG_UNLISTED), n_ogo=len(ogo),
            flags_b64=blob(flags), ogo_b64=blob(ogo)))
    print(f"Wrote {DICTIONARY_OUTPUT} ({os.path.getsize(DICTIONARY_OUTPUT)/1024:,.0f} KB)")


def write_report(built, path):
    """debug/compound_joins.md (gitignored): how the compound table was decided, for the user to read — the counts
    per kind and test, the refused compounds, the numbers' clauses, the second verbs' shares, the flags, and random
    samples to read by hand."""
    table, cands, rng = built["table"], built["candidates"], random.Random(20260928)
    headwords, ev, clauses, vt = built["headwords"], built["evidence"], built["clauses"], built["verb_table"]
    kinds = Counter(e[2] for e in table.values())

    def sample(words, k=SAMPLE):
        words = sorted(words)
        return sorted(rng.sample(words, min(k, len(words))), key=lambda w: headwords[w][1] if w in headwords else 0)

    def show(words):
        return " · ".join(f"{w} {headwords[w][0]}" for w in words) or "—"

    out = [f"# Compounds — how the table was decided ({date.today()})", "",
           f"Build: {built['seconds']:.0f} s; the reference text {built['counts']['tokens']:,} tokens in "
           f"{built['counts']['files']} files, read in {built['counts']['seconds']:.0f} s. COMPOUND_JOINS "
           f"{len(table):,} entries (" + ", ".join(f"{k} {kinds[k]:,}" for k in COMPOUND_KINDS) + f"), "
           f"{built['sizes']['compounds'] / 1024:,.0f} KB encoded; COUNTERS {len(built['named']):,}; AFFIX_JOINS "
           f"{len(built['joins']):,} ({len(built['second']):,} a compound + its affixes, {len(built['decided']):,} "
           f"kept).", "", "## The headwords read alone", "", "| shape | headwords |", "| :-- | --: |"]
    out += [f"| {s} | {n:,} |" for s, n in sorted(built["shapes"].items())]
    out += ["", f"Plurals kept out ({len(built['plurals']):,}): " + show(sorted(built["plurals"]))]

    refused = built["refused"]
    out += ["", f"## Even odds: {len(refused):,} noun compounds refused", "",
            "o = joins in the text, e = chance's, est = the lists' count (both lists), form = the share of the "
            "spelling's occurrences the text joins.", "", "| word | reading | o | e | est | form | JPDB | Jiten |",
            "| :-- | :-- | --: | --: | --: | --: | --: | --: |"]
    for w in sorted(refused, key=lambda w: -refused[w]["e"]):
        r = refused[w]
        out.append(f"| {w} | {headwords[w][0]} | {r['o']:,} | {r['e']:.1f} | {r['est']:.1f} | {r['form']:.2f} | "
                   f"{r['jpdb'] or ''} | {r['jiten'] or ''} |")

    out += ["", "## Words holding a number", "",
            f"Counters (after two or more numbers): {len(built['counters']):,}; named in the table (UniDic doesn't "
            f"always file them as counters): " + " ".join(sorted(built["named"])), "",
            "| clause | words | joins |", "| :-- | --: | :-- |"]
    for c in NumeralTest.CLAUSES:
        out.append(f"| {c} | {sum(1 for x in clauses.values() if x == c):,} | "
                   f"{'no' if c == 'count' else ('yes (no when fixed counts stay apart)' if c == 'fixed count' else 'yes')} |")
    apart = built["jmdict_apart"]
    out += ["", f"Read as no count by the lists but as a count by JMdict (apart, among the counts): {len(apart):,}: "
            + " · ".join(f"{w} {headwords[w][0]} ({why})" for w, why in sorted(apart.items()))]
    for c in NumeralTest.CLAUSES:
        words = [w for w, x in clauses.items() if x == c]
        best = sorted(words, key=lambda w: headwords[w][1])[:40]
        out += ["", f"### {c} ({len(words):,})", "", "Best-ranked: " + show(best), "",
                f"Random {min(SAMPLE, len(words))}: " + show(sample(words))]

    grammar, low, high = built["grammar"], built["gap"][0], built["gap"][1]
    out += ["", "## Verb + verb: the second verbs", "",
            f"Share = uses after a verbal noun + し / uses after a verb's stem. Cut {built['cut']:.2%}: the aspect "
            f"verbs' lowest ({high:.2%}; the word-making verbs' highest {low:.2%}); a share is read from "
            f"{OGO_MIN_USES} uses or more. Grammar (the compound stays two words): {len(grammar)}.", "",
            "| second verb | after a stem | after a verbal noun + し | share | side | headwords |",
            "| :-- | --: | --: | --: | :-- | --: |"]
    v2_of = Counter(words[1].feature.lemma for w, (k, words) in cands.items() if k == "V")
    shown = {v for v, (n, m, s) in vt.items() if (n >= OGO_MIN_USES and m) or v2_of[v]} \
        | set(ASPECT_VERBS + WORD_MAKING_VERBS)
    for v in sorted(shown, key=lambda v: (-vt.get(v, (0, 0, 0))[2], v)):
        n, m, s = vt.get(v, (0, 0, 0.0))
        side = "grammar" if v in grammar else ("too few uses" if n < OGO_MIN_USES else "makes words")
        out.append(f"| {v} | {n:,} | {m:,} | {s:.2%} | {side} | {v2_of[v]:,} |")
    vv = {w: words for w, (k, words) in cands.items() if k == "V"}
    apart = [w for w, words in vv.items() if words[1].feature.lemma in grammar]
    joined = [w for w in vv if w not in apart]
    out += ["", f"Verb + verb headwords: {len(vv):,}; apart {len(apart):,}, joined {len(joined):,}. Words UniDic reads "
            f"whole kept out of the table: {len(built['own']):,}" + (": " + " · ".join(built["own"]) if built["own"] else "")
            + f". Kana spellings JMdict lists but never as a verb, kept out: {len(built['not_verbs']):,}"
            + (": " + " · ".join(built["not_verbs"]) if built["not_verbs"] else "") + ".", "",
            f"Apart, random {min(SAMPLE, len(apart))}: " + show(sample(apart)), "",
            f"Joined, random {min(SAMPLE, len(joined))}: " + show(sample(joined)), "",
            "Verbs UniDic reads whole that a sentence shows cut (not joined; most met first): " + " · ".join(
                f"{w} {n}" for w, n in sorted(built["in_context"].items(), key=lambda x: -x[1])[:80])]

    free = Counter(p[2] for e in table.values() for p in e[4])
    bound = sum(1 for e in table.values() if not all(p[2] for p in e[4]))
    out += ["", "## Parts", "", f"Parts free {free[1]:,}, bound {free[0]:,}; compounds with a bound part {bound:,}."]
    out += ["", "## A compound + its affixes (the affix joins' second pass)", "",
            f"{len(built['second']):,} words; kept {len(built['decided']):,}: " + show(sorted(built["decided"])[:120])]
    flags = built["flags"]
    out += ["", "## The dictionaries' flags", "",
            f"Titles (JMnedict organizations, products, works): {sum(1 for b in flags.values() if b == FLAG_TITLE):,} — "
            + " · ".join(sorted(w for w, b in flags.items() if b == FLAG_TITLE))]
    if built["skipped"]:
        out.append("JMdict skipped: " + "; ".join(built["skipped"]))
    else:
        out += [f"JMdict (created {built['created']}): behind the switch "
                f"{sum(1 for b in flags.values() if b & FLAG_FRINGE):,}: "
                + " · ".join(sorted(w for w, b in flags.items() if b == FLAG_FRINGE)), "",
                f"Katakana compounds JMdict doesn't list — each gives way to a katakana name around it "
                f"({sum(1 for b in flags.values() if b & FLAG_UNLISTED):,}): "
                + " · ".join(sorted(w for w, b in flags.items() if b & FLAG_UNLISTED)), "",
                f"お / ご words of their own ({len(built['ogo']):,}): "
                + " · ".join(f"{w} {e[1]}" for w, e in sorted(built["ogo"].items()))]
    out += ["", "## Random samples per kind", ""]
    groups = defaultdict(list)
    for w, e in table.items():
        groups[e[2] + " " + (subkind(e[2], cands[w][1]) if w in cands else "")].append(w)
    for g in sorted(groups):
        out += [f"**{g.strip()}** ({len(groups[g]):,}): " + show(sample(groups[g])), ""]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"Wrote {path}")


MODULE_TEMPLATE = '''"""Reference data distilled from the corpora — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_reference_data.py

Revision: {revision}
  ALIASES      {n_aliases:,} entries — unidic lemma -> the spelling frequency lists use.
  SPOKEN_RANK  {n_spoken:,} entries — written vocabulary (top {cap} of {written_list}, proper
               nouns and interjections removed) -> its rank in {spoken_lists}.
               A rank of 0 means the spoken corpora never saw it, i.e. rarer than they can measure.
  AFFIX_JOINS  {n_joins:,} entries — a written form -> [lemma, reading]: the {join_lists} headwords
               (in both, or in one's top {one_list_rank}) that UniDic splits into a prefix + a word
               or a word + suffixes (or a compound + its affixes), joined back by analyzer.join_affixes;
               every spelling of a word shares its lemma (お / ご words only where the prefixed form is at
               least {ogo_share} of the word's uses, or {talk_share} in conversation).
  COMPOUND_JOINS  {n_compounds:,} entries ({n_kinds}) — a written form -> [lemma, reading, kind, 0]:
               the same headwords that UniDic splits into words of their own — N nouns and な-words
               (上層部, 日本語, 一生懸命), Q a word holding a number that counts nothing (二十歳,
               十人十色), V a verb + a verb that makes a word (取り掛かる) — joined back by
               analyzer.join_affixes, keyed as the tokenizer reads their words (a verb by its first
               verb as written and its second's dictionary form).
               Every lemma, here and in COMPOUND_PARTS, is as the tokenizer keys it — already through
               analyzer._sanitize_term (アイリス-iris is アイリス) — and every reading is its lForm.
  COMPOUND_PARTS  the same written forms -> [[lemma, reading, free], ...]: what each is made of, free (1)
               when a list ranks the part on its own at least as well as the compound. Apart from the
               joins, so a process that only tokenizes never decodes it.
  COUNTERS     {n_counters:,} words the lists count with (after two or more different numbers) that
               UniDic does not always file as counters (人, 冊).

The tables are stored compressed and decoded lazily, so importing this module is cheap and a
process that never asks for them never pays for them.
"""

import base64
import json
import threading
import zlib

REVISION = "{revision}"

_ALIASES_B64 = (
    "{aliases_b64}"
)

_SPOKEN_RANK_B64 = (
    "{spoken_b64}"
)

_AFFIX_JOINS_B64 = (
    "{joins_b64}"
)

_COMPOUND_JOINS_B64 = (
    "{compounds_b64}"
)

_COMPOUND_PARTS_B64 = (
    "{parts_b64}"
)

_COUNTERS_B64 = (
    "{counters_b64}"
)

_aliases = None
_spoken_rank = None
_affix_joins = None
_compound_joins = None
_compound_parts = None
_counters = None
_LOCK = threading.Lock()     # one decode per table, whichever thread asks first


def _take(name):
    """The table stored as `name`, decoded — or None when it cannot be read. Its text is dropped from the module:
    nothing reads it again, and it held about the table's compressed size for the process's life."""
    text, globals()[name] = globals()[name], None
    try:
        return json.loads(zlib.decompress(base64.b64decode(text)).decode("utf-8"))
    except Exception:
        return None


def aliases():
    """lemma -> common spelling. Empty dict is a valid (degraded) answer, never an exception."""
    global _aliases
    if _aliases is None:
        with _LOCK:
            if _aliases is None:
                _aliases = _take("_ALIASES_B64") or {{}}
    return _aliases


def spoken_ranks():
    """lemma -> spoken rank (0 = beyond the reference corpora)."""
    global _spoken_rank
    if _spoken_rank is None:
        with _LOCK:
            if _spoken_rank is None:
                _spoken_rank = _take("_SPOKEN_RANK_B64") or {{}}
    return _spoken_rank


def affix_joins():
    """written form -> (lemma, reading) (analyzer.join_affixes). Empty when it cannot be read: words then
    stay as UniDic cuts them, never an exception. (Each entry a tuple: smaller than the list it is stored as.)"""
    global _affix_joins
    if _affix_joins is None:
        with _LOCK:
            if _affix_joins is None:
                table = _take("_AFFIX_JOINS_B64") or {{}}
                try:
                    for word, entry in table.items():
                        table[word] = tuple(entry)
                except Exception:
                    table = {{}}
                _affix_joins = table
    return _affix_joins


def compound_joins():
    """written form -> (lemma, reading, kind, 0) (analyzer.join_affixes, which ORs the dictionaries' flags into
    this table in place). Empty when it cannot be read: compounds then stay in UniDic's words, never an
    exception. (Stored with "" for a lemma that is the spelling itself; each entry a tuple.)"""
    global _compound_joins
    if _compound_joins is None:
        with _LOCK:
            if _compound_joins is None:
                table = _take("_COMPOUND_JOINS_B64") or {{}}
                try:
                    for word, entry in table.items():
                        table[word] = (entry[0] or word, entry[1], entry[2], entry[3])
                except Exception:
                    table = {{}}
                _compound_joins = table
    return _compound_joins


def compound_parts():
    """written form -> [[lemma, reading, free], ...]: each compound's parts. Empty when it cannot be read,
    never an exception. A part met in many compounds (部, 会) is one shared list. (Stored as each distinct
    part once and each compound's parts as indexes.)"""
    global _compound_parts
    if _compound_parts is None:
        with _LOCK:
            if _compound_parts is None:
                data = _take("_COMPOUND_PARTS_B64")
                try:
                    parts = data["parts"]
                    _compound_parts = {{word: [parts[i] for i in ids] for word, ids in data["of"].items()}}
                except Exception:
                    _compound_parts = {{}}
    return _compound_parts


def counters():
    """The words the lists count with that UniDic does not always file as counters (a frozenset)."""
    global _counters
    if _counters is None:
        with _LOCK:
            if _counters is None:
                _counters = frozenset(_take("_COUNTERS_B64") or ())
    return _counters
'''


DICTIONARY_TEMPLATE = '''"""The dictionaries' word on the compounds — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_reference_data.py

Revision: {revision}
  COMPOUND_FLAGS  {n_flags:,} compounds of app/reference_data.py -> flags: 1 a phrase more than a word of
                  its own, 3 the title of a work, a product or an organization ({n_titles:,}) — both joined
                  only while "Phrases and titles as one word" is on. Never a loanword spelled in katakana
                  alone: one word either way. 4 a word spelled in katakana alone that JMdict doesn't list
                  ({n_unlisted:,}; ビルデ = ビル + デ): joined, but inside a longer katakana name (ビルデイング)
                  it gives way and the name stays one word.
  OGO_JOINS       {n_ogo:,} お / ご words that are words of their own, with a meaning the bare word lacks ->
                  [lemma, reading]: joined as affix words whatever their share.

Derived from {sources}, dictionaries of the JMdict/EDICT project, property of the Electronic
Dictionary Research and Development Group (EDRDG), used in conformance with the Group's licence: Creative
Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0),
https://creativecommons.org/licenses/by-sa/4.0/ — https://www.edrdg.org/edrdg/licence.html,
https://www.edrdg.org/jmdict/j_jmdict.html, https://www.edrdg.org/enamdict/enamdict_doc.html. Changes: only
spellings and flags are kept (no glosses), matched to the compound and affix tables of
app/reference_data.py. This table is shared under the same licence.

Stored compressed and decoded lazily; each table is empty when it cannot be read, never an exception.
"""

import base64
import json
import zlib

REVISION = "{revision}"
JMDICT_CREATED = "{created}"

_COMPOUND_FLAGS_B64 = (
    "{flags_b64}"
)

_OGO_JOINS_B64 = (
    "{ogo_b64}"
)

_flags = None
_ogo = None


def _decode(b64):
    return json.loads(zlib.decompress(base64.b64decode(b64)).decode("utf-8"))


def compound_flags():
    """compound spelling -> flags (1 a phrase, 3 a title: both behind the switch; 4 a katakana word JMdict doesn't
    list, which gives way to a katakana name around it). Empty when unreadable."""
    global _flags
    if _flags is None:
        try:
            _flags = _decode(_COMPOUND_FLAGS_B64)
        except Exception:
            _flags = {{}}
    return _flags


def ogo_joins():
    """お / ご word -> [lemma, reading], joined as affix words (analyzer.affix_joins merges them). Empty when
    unreadable."""
    global _ogo
    if _ogo is None:
        try:
            _ogo = _decode(_OGO_JOINS_B64)
        except Exception:
            _ogo = {{}}
    return _ogo
'''


if __name__ == "__main__":
    main()
