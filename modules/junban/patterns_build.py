# SPDX-License-Identifier: GPL-3.0-or-later
"""パターン builder — count, once, how every word in a corpus is used (Patterns_Spec.md WP-P2).

The Lapis card's `Patterns` field shows three lines under a word — the particles it takes, the words
it pairs with, the frames it sits in. This module computes the evidence for all three in one pass
over a corpus and stores it in a small SQLite, `patterns_ja.db`, next to the token store. The panel
(`patterns.py`) only ever reads that file; nothing here touches Anki.

The key-space contract
----------------------
Everything is counted by **(lemma, reading)** — exactly the pair `analyzer.JapaneseTokenizer` keys a
word on, or every lookup silently misses (spec §12 #1):

* lemma = `feature.lemma or surface`, then `_sanitize_term` **always**. `SANITIZE_JA` is False at
  import and only switched on inside `analyzer.main()`, so borrowing the tokenizer here would get
  unsanitised lemmas and miss every loanword.
* reading = `feature.lForm or feature.kana or ""` — the lemma's reading since `ENGINE_REVISION 10`:
  感じた and 感じる are one key.
* what a word is *shown* as is its commonest `orthBase` — the spelling the text used. Never the lemma:
  UniDic's lemma for する is 為る and for ある is 有る, and 期待を為る is not something a learner reads.

The tokenizer itself cannot be reused: it drops punctuation and carries no part of speech, and both
are needed here — punctuation as a barrier (nothing pairs across 、 or 。) and POS to know a noun from
a verb. So this runs its own fugashi pass with the identical lemma and reading rules; a test
holds the two to the same keys over real text.

The corpus
----------
The user's library is the four content folders under `data/ja` — `HighPriority`, `LowPriority`,
`GoalContent`, `Graduated` — with **each distinct file content counted once**. The rest of `data/ja`
is staging and copies: measured 2026-09-22, `Pre-YT` held 1,938 files of which 1,896 were
byte-identical to a tier file, and walking it would have doubled most counts (F13). A general corpus
(WP-P10) is any folder, walked whole under the same once-per-content rule.

Runs as a subprocess (`Surasura.exe junban_patterns`, CLAUDE.md §6) and writes atomically: a build
that dies leaves the previous database exactly as it was, never a half one the panel would trust.
"""

import hashlib
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter, namedtuple
from pathlib import Path

from app.batch_gc import without_cycle_collection
from app.unicode_ranges import HAN, KANA

# 2: every pattern row names its construction (`section`), so the lookup can spread a card's
#    collocations and frames over different ways of using the word (user, 2026-09-24).
# 3: a pairing is written as the text writes it — 目に遭う, 期待に応える, with its voice (緑に囲まれる) —
#    in the modern じる form (神を信じる), never a classical spelling (実り多い, not 実り多し): `score`.
# 4: the forms the word itself takes (`form` rows: 囲まれる, 構わない, 大切な, 期待する).
# 5: a word's own part of speech is its commonest use of a class the rules count — 目 is 名詞 even where
#    the counter 〜目 (三回目) outnumbers it, as it does in news (`score`).
# 6: words keep their prefixes and suffixes (不自然, 可能性: `analyzer.join_affixes`); a particle row says
#    its side (`section`), a する-noun counts the particle before its する; the documents a pattern was
#    seen in (`files`); する-nouns' objects (C6), adverbs' predicates (A1), compound partners (F4),
#    として / について as written, できる forms, no name as a partner (Patterns_Quality_Spec.md §8.1).
# 7: the same rules over the sweep's join table (Patterns_Quality_Spec.md §15.9) — おやすみ and お休み one word,
#    お話し and お帰り お + a word, 複雑さ 複雑 + さ: a builder-6 file keys those words the old way.
# 8: words made of words are one word, keyed by the dictionary's reading (株式会社 カブシキガイシャ, 二十歳, 走り出す);
#    a sound word + と is its word (ドキッと is どき); お守り and お帰り are words of their own; katakana names stay
#    whole and laughter in pieces; and what counts is what the list counts (`analyzer.word_lemma`, in Japanese
#    script) — no number, symbol or Latin word (FBI), a letter spelled out (デルタ) under its name: a builder-7 file
#    keys those words the old way.
# 9: a one-kanji word counts only where it stands on its own, as the list counts it (`_piece`: not 斬 in 斬魄刀, not
#    年 in 三年); words the tagger cut at their endings are whole (くだらない, 思わず, 知らせる), a word + particle the
#    dictionary lists is its own word (いつも, 何か, 一緒に), a pronoun with a suffix one word (何様, お前さん), and a
#    spelling the dictionary keeps apart from UniDic's lemma a word of its own (揚げる, 建てる, 撮る: `_entry`): a
#    builder-8 file keys those words the old way.
BUILDER_VERSION = 9

# The word floor, by corpus kind (D5): 12 for the user's own library — about 4.2M tokens, so 20 would
# leave too many of their cards blank — and 20 for a general corpus, which is far bigger.
FLOOR_LIBRARY = 12
FLOOR_GENERAL = 20
# A collocation or a frame needs this many occurrences to be stored at all (§6).
MIN_PATTERN = 3
# The fourth line, the forms the word itself takes (the user, 2026-09-24): measured on the
# conversational corpus, 囲む is 囲まれる 76% of the time, 構う is 構わない 56%, 大切 is 大切な 59%, 期待
# is 期待する 65% — usage a learner would otherwise miss. A form is kept only when it covers at least
# this share of the word's uses; the plain dictionary form is never listed. 5%, the one line every share
# on a card is held to (Patterns_Quality_Spec.md decision 2: 利用できる 8%).
FORM_SHARE = 0.05

# The tier folders, then the content folder every new copy goes into whatever its place (3.0's Sources: Library/<show>).
LIBRARY_FOLDERS = ("HighPriority", "LowPriority", "GoalContent", "Graduated", "Library")

# One token, with what the rules need. `cform` is the conjugation form: 深い (連体形) modifies a noun,
# 深く (連用形) modifies a verb. `ctype` is the conjugation type: a `文語…` one is a classical
# inflection (実り多き), whose base spelling (多し) is never shown. `parts` are the tokens a word with its
# prefix or suffix was joined from (利用者 = 利用 + 者: `analyzer.join_affixes`), else (). `pos3` tells an
# adverbial noun (再度, 毎日: 副詞可能) and a person's name (人名).
# `word` is whether the list counts it: a word to the tokenizer (`analyzer.word_lemma`) that holds Japanese script,
# as `analyzer.main` counts. Punctuation, spaces, symbols, numbers and Latin words (FBI, OK) stay in place as
# barriers and neighbours but are never content; a letter spelled out (デルタ) is a word, under its name.
# `entry` is the spelling when the dictionary keeps it apart from the lemma (`_entry`: 揚げる, filed by UniDic under
# 上げる) — the word is counted under it as well (`_count_token`) — else ""; the rules read `lemma`, as grammar sees it.
Tok = namedtuple("Tok", "surface lemma reading orth pos1 pos2 cform ctype parts pos3 word entry",
                 defaults=((), "", True, ""))

NOUN, NA_ADJ, VERB, I_ADJ = "noun", "na-adj", "verb", "i-adj"
_CLASS_OF_POS1 = {"名詞": NOUN, "形状詞": NA_ADJ, "動詞": VERB, "形容詞": I_ADJ}

# Which card line each counting rule feeds. K1-K5 are the four additions the WP-P4 quality check
# put to the user (2026-09-23: all four in) — 目の前, 深い関係 / 大切な人, 深く考える join the
# collocations; 貴重な〜 joins the frames. C6, A1 and F4 came with builder 6 (Patterns_Quality_Spec
# §8.1): サービスを利用する, 再度確認する, 反省〜会.
_KIND = {"C1": "colloc", "C2": "colloc", "C3": "colloc", "C4": "colloc", "C5": "colloc", "C6": "colloc",
         "K1": "colloc", "K2": "colloc", "K3": "colloc", "K4": "colloc", "A1": "colloc",
         "F1": "frame", "F2": "frame", "F3": "frame", "F4": "frame", "K5": "frame"}
# Where a particle sits, stored as the particle row's `section`: after a noun (探検に), before a
# predicate (…を受ける) — and before a する-noun where it takes the する (サービスを利用する).
AFTER, BEFORE = "after", "before"
# Where the collocate's id sits in each rule's key (the y of logDice). C1 is (rule, particle, y).
_Y = {"C1": 2}


# --- tokens ------------------------------------------------------------------------------------- #
_ENTRIES = {}       # (lemma, spelling) -> `_entry`'s answer, asked once per pair


def _entry(lemma, orth, ctype):
    """The spelling a word written `orth` is counted under as a word of its own as well, or "". UniDic files several
    dictionary words under one lemma — 揚げる 'deep-fry' and 挙げる 'raise (a hand)' under 上げる, 建てる under 立てる, 撮る
    under 取る — and a card that says 揚げる must find 揚げる's own uses, never 上げる's. Where JMdict gives the spelling
    an entry of its own, apart from the lemma's (`anki_match.two_words`, the test the card lookup asks), the word is
    counted under its spelling too (`_count_token`): its own row, spelling and pairings — while the lemma keeps the use
    and the words around it read it as UniDic does, so no row they had moves. A spelling in kana alone never: written
    in kana, a word is no entry of its own (あげる stays 上げる's). Nor a classical inflection (`ctype` 文語…): 多き's
    base spelling 多し is 多い in an older conjugation, never a spelling the writer chose — and never shown
    (`_spelling`). Nor a す verb under its する verb: one verb conjugated two ways, as a じる verb and its ずる form are
    (`two_words`) — 愛さない is 愛する's negative. Nor a spelling UniDic lists as a word of its own: then UniDic told
    the two apart where the text stands — the adverb たとえ written 例え is still 'even if', not the noun 例え 'simile',
    and 切れる under 切る is 'can cut', not 切れる 'snap'."""
    if ctype.startswith("文語"):
        return ""
    pair = (lemma, orth)
    found = _ENTRIES.get(pair)
    if found is None:
        found = _ENTRIES[pair] = orth if _own_entry(lemma, orth) else ""
    return found


def _own_entry(lemma, orth):
    if orth == lemma or not _KANJI.search(orth) or (orth[-1:] == "す" and lemma == orth[:-1] + "する"):
        return False
    from app.anki_match import two_words
    if not two_words(orth, lemma):
        return False
    from app.analyzer import _sanitize_term
    from app.names import _listed_as
    return not any(_sanitize_term(f.lemma) == orth for f in _listed_as(orth))


def iter_tokens(text, tagger, sanitize, boundaries):
    """Yield one list of `Tok` per sentence, punctuation kept in place as barriers.

    Sentences split exactly as `JapaneseTokenizer.tokenize_sentences` splits them: line by line
    (fugashi eats newlines), then at any token containing a boundary character — character-wise,
    because the tokenizer glues a terminator to an adjacent symbol ('➡。'). Words keep their prefixes
    and suffixes the analyzer's way (`join_affixes`: 不自然, 新幹線, 可能性)."""
    from app.analyzer import JoinedWord, ReadNode, affix_joins, has_target_language, join_affixes, word_lemma
    joins = affix_joins()
    intern = sys.intern     # one copy of each spelling in the counters, not one per token (laptops)

    def tok(node, parts=()):
        surface, f = intern(node.surface), node.feature
        lemma = word_lemma(node)    # None: no word to the tokenizer — kept in place, never counted
        key = intern(sanitize(lemma or f.lemma or surface))
        # Nor a word in no Japanese script (FBI, OK): the list counts one only when its key or its text holds some.
        word = lemma is not None and (has_target_language(key, "ja") or has_target_language(surface, "ja"))
        orth = intern(sanitize(f.orthBase or surface))
        return Tok(surface, key, intern(f.lForm or f.kana or ""), orth,
                   intern(f.pos1), intern(f.pos2), f.cForm, f.cType, parts, intern(f.pos3 or ""), word,
                   _entry(key, orth, f.cType) if orth != key else "")

    for line in text.split("\n"):
        sentence = []
        # Never the library's name tables: パターン data is shared, and one user's library must not shape it.
        for word in join_affixes(tagger(line), joins, library=False):
            parts = (tuple(tok(ReadNode(s, f, False)) for s, f in word.parts) if isinstance(word, JoinedWord)
                     else ())
            sentence.append(tok(word, parts))
            if not boundaries.isdisjoint(word.surface):
                yield sentence
                sentence = []
        if sentence:
            yield sentence


# --- counting (pure) ---------------------------------------------------------------------------- #
class Counts:
    """Plain counters, keyed by small integers so a library's worth of pairs stays in memory."""

    def __init__(self):
        self.ids = {}                 # (lemma, reading) -> id
        self.keys = []                # id -> (lemma, reading)
        self.word = Counter()         # id -> occurrences
        self.orth = Counter()         # (id, orthBase) -> occurrences
        self.pos = Counter()          # (id, pos1) -> occurrences
        self.pattern = Counter()      # (target id, rule key tuple) -> occurrences
        self.spell = Counter()        # (target id, rule key, other, target) -> how the pairing wrote
                                      # its two words (目に遭う, never 目に会う: see `score`)
        self.teiu = 0                 # という / っていう chunks — the y of the という〜 frame
        self.tokens = 0
        # How many documents each pattern was seen in — a card's pairing must be common, not one book
        # saying it thirty times (再度生老人: Patterns_Quality_Spec.md §8.1 h). `doc` holds the current
        # document's patterns until `end_document`.
        self.docs = Counter()         # (target id, rule key) -> documents
        self.doc = set()
        # A one-kanji word standing as a piece of something else (`_piece`: 斬 in 斬魄刀, 年 in 三年) is no use of
        # that word: no count and no line on its row. It is still a token of the text its neighbours pair with, so
        # their strength (logDice) weighs it by every time it appears, as the pairing's own count does.
        self.bound = Counter()        # (lemma, reading) -> uses as a piece

    def end_document(self):
        for key in self.doc:
            self.docs[key] += 1
        self.doc.clear()

    def kid(self, tok):
        key = (tok.lemma, tok.reading)
        i = self.ids.get(key)
        if i is None:
            i = self.ids[key] = len(self.keys)
            self.keys.append(key)
        return i


def _is_particle(tok):
    """A particle the lines count: a case particle, or は / も — never の (D4)."""
    return (tok is not None and tok.pos1 == "助詞" and tok.lemma != "の"
            and (tok.pos2 == "格助詞" or tok.lemma in ("は", "も")))


def _is_da(tok, surface):
    """The copula's に / な — how a な-adjective attaches (大切にする, 大切な人). UniDic tags them
    助動詞 だ, not particles, which is why a な-adjective takes its particle from the LEFT."""
    return tok is not None and tok.pos1 == "助動詞" and tok.lemma == "だ" and tok.surface == surface


_COMPOUND_POS1 = frozenset(("名詞", "接頭辞", "接尾辞"))

# "X の + an empty noun" says nothing about X: 〜のこと ("about X"), 〜のもの, 〜のため, 〜のところ…
# go with almost any noun, and 実りのこと ×6 made the card's collocation line (2026-09-24 preview).
# UniDic has no part of speech for them, so they are listed by lemma. 目の前 / 心の中 stay: 前 and
# 中 carry meaning.
_EMPTY_NOUNS = frozenset(("事", "物", "所", "為", "訳", "筈", "方", "内", "時", "様", "儘", "頃", "辺"))

# A name honorific after a word is usually a NAME that happens to share its spelling: 実り picked up
# 〜ちゃん from a character called みのり. It is real only when the word itself takes it — 母さん,
# 兄ちゃん, 神様 — so such a frame must cover at least HONORIFIC_SHARE of the word's uses.
_HONORIFICS = frozenset(("ちゃん", "さん", "君", "くん", "殿", "氏", "様"))
HONORIFIC_SHARE = 0.10
# Kana and kanji: Unicode's own ranges (app/unicode_ranges.py), shared with the analyzer.
_KANA = re.compile(f"^[{KANA}]+$")
_KANJI = re.compile(f"[{HAN}]")


def _name_like(tok):
    """A word written in plain kana though its dictionary form has kanji — the shape of a name that
    UniDic misread as a word: 28 of 84 subtitle lines with みのりちゃん came out as 実り + ちゃん."""
    return bool(_KANA.match(tok.surface)) and bool(_KANJI.search(tok.lemma))


def _run(toks, j):
    """The compound noun `toks[j]` belongs to -> (start, end), or None when it is not one: a lone
    noun, a run with no noun in it, a number (3人, 第2話 — every count would be a word of its own), or a run of
    no word at all (Game Over: the list counts neither piece; DNA鑑定 holds a word and is a compound)."""
    s = e = j
    while s > 0 and toks[s - 1].pos1 in _COMPOUND_POS1:
        s -= 1
    while e + 1 < len(toks) and toks[e + 1].pos1 in _COMPOUND_POS1:
        e += 1
    run = toks[s:e + 1]
    if (e == s or not any(t.pos1 == "名詞" for t in run) or any(t.pos2 == "数詞" for t in run)
            or not any(t.word for t in run)):
        return None
    return s, e


def _compound(toks, s, e):
    """One `Tok` for the compound toks[s..e], keyed by its spelling and its parts' readings — so a
    card's 奨学金 / しょうがくきん finds it (ショウ + ガク + キン)."""
    run = toks[s:e + 1]
    text = "".join(t.surface for t in run)
    name = "人名" if any(t.pos3 == "人名" for t in run) else ""      # 田中先生 is no partner either
    return Tok(text, text, "".join(t.reading for t in run), text, "名詞", "複合", "*", "*", (), name)


def _noun(toks, j):
    """The noun at `toks[j]` as a collocate — the whole compound when it is one. UniDic splits 違和感
    into 違和 + 感, and the head alone put 感を感じる ×22 on the 感じる card (measured, 2026-09-23). None
    for what a number counts (2003年, 10ヶ国, 3人): alone, the counter printed 年に設立する, ヶ国で実施する."""
    run = _run(toks, j)
    if run:
        return _compound(toks, *run)
    before = _at(toks, j - 1)
    return None if before is not None and before.pos2 == "数詞" else toks[j]


# A passive or causative after a verb changes what a pairing says — 緑に囲まれる is not 緑に囲む,
# 雰囲気にのまれる not 雰囲気にのむ — so it stays in the pairing's spelling.
_VOICE = frozenset(("れる", "られる", "せる", "させる"))


def _at(toks, j):
    return toks[j] if 0 <= j < len(toks) else None


def _spelling(tok, nxt=None):
    """How a pairing writes `tok`: its base spelling (遭う, 応える), with its voice when a passive or
    causative auxiliary `nxt` follows it (囲まれる). None for a classical inflection: 実り多き's base
    spelling is 多し, which no learner should see — the word's usual spelling stands in for it."""
    if tok.ctype.startswith("文語"):
        return None
    if tok.pos1 == "動詞" and nxt is not None and nxt.pos1 == "助動詞" and nxt.lemma in _VOICE:
        return tok.surface + nxt.lemma
    return tok.orth


def _voiced(toks, i):
    """The verb at toks[i] with the passive or causative that follows it (囲まれる), else ""."""
    spelled = _spelling(toks[i], _at(toks, i + 1))
    return spelled if spelled and spelled != toks[i].orth else ""


def _pair(counts, x, key, other=None, target=""):
    """Count one pattern of word `x`. `other` is how this pairing wrote the word `x` pairs with;
    `target` how it wrote `x` itself when not plainly (a verb in the passive). `score` shows the
    commonest writing of each pattern."""
    counts.pattern[(x, key)] += 1
    counts.doc.add((x, key))
    if other is not None:
        counts.spell[(x, key, other, target)] += 1


_KANA_KANJI = re.compile(f"[{KANA}{HAN}]")


def _partner(tok):
    """Can `tok` be a pairing's or a frame's partner? Never a person's name — a series' names pass
    every count (船長のアーチャー, 王の手) — never a number, and never a token with no kana or kanji in it
    (a stray number or Latin word). Place names stay: 日本に降り立つ (Patterns_Quality_Spec.md §8.1 j).
    None — no noun to pair with (`_noun`) — is none."""
    return (tok is not None and tok.pos3 != "人名" and tok.pos2 != "数詞"
            and bool(_KANA_KANJI.search(tok.surface)))


def _adverbial(tok):
    """Can `tok` be used as an adverb — UniDic's 副詞, or a noun it marks 副詞可能 (再度, 毎日)? Its
    labels decide, not its uses: casual speech drops particles everywhere (俺行く)."""
    return tok.pos1 == "副詞" or (tok.pos1 == "名詞" and tok.pos3 == "副詞可能")


def _is_suru(tok):
    return tok is not None and tok.pos1 == "動詞" and tok.lemma == "為る"


def _tally(counts, tok):
    x = counts.kid(tok)
    counts.word[x] += 1
    # 多し is how 実り多き is filed, never how 多い is shown; 揚げる is 揚げる's own spelling (`_count_token`), so a
    # card that says 揚げる finds that word alone.
    if not tok.ctype.startswith("文語") and not tok.entry:
        counts.orth[(x, tok.orth)] += 1
    counts.pos[(x, tok.pos1)] += 1
    return x


def _around(toks, s, e):
    n = len(toks)
    return (toks[s - 1] if s >= 1 else None, toks[s - 2] if s >= 2 else None,
            toks[e + 1] if e + 1 < n else None, toks[e + 2] if e + 2 < n else None)


# UniDic splits four compound particles into a particle, a verb and て — として is と + し(為る) + て — and the
# verb's dictionary form printed 啓示とする, 利用につく, 利用におく, 子供にとる. Those are printed as the text
# writes them (Patterns_Quality_Spec.md F4): 啓示として, 利用について, 利用において, 子供にとって — and における
# (於け + る), which printed 利用におく the same way. について's verb is filed つく, or 付く when spelled 就いて.
_COMPOUND_PARTICLES = {"と": ("為る",), "に": ("付く", "つく", "於く", "取る")}


def _noun_rules(counts, x, toks, s, e):
    """Lines 1-2 for the noun — or compound noun — spanning toks[s..e]."""
    p1, p2, n1, n2 = _around(toks, s, e)
    if _is_particle(n1):                                             # line 1: 気持ちが
        _pair(counts, x, ("P", n1.surface, AFTER))
        # Line 2 pairs only through case particles: は / も stand in for が / を, so
        # 影響は受ける would only repeat 影響を受ける with a thinner count.
        if n1.pos2 == "格助詞" and n2 is not None and n2.pos1 in ("動詞", "形容詞"):
            n3 = _at(toks, e + 3)
            if (n2.lemma in _COMPOUND_PARTICLES.get(n1.surface, ()) and n3 is not None
                    and (n3.surface in ("て", "って") or (n2.lemma == "於く" and n3.lemma == "り"))):
                written = n2.surface + n3.surface                    # 啓示として, 利用について
            else:
                written = _spelling(n2, n3)
            _pair(counts, x, ("C1", n1.surface, counts.kid(n2)), written)     # 影響を受ける
    if _is_suru(n1) and _is_particle(p1):     # a する-noun used as a verb: the particle before it
        _pair(counts, x, ("P", p1.surface, BEFORE))                  # を〜 on 利用 (サービスを利用する)
        if p1.pos2 == "格助詞" and p2 is not None and p2.pos1 == "名詞":
            noun = _noun(toks, s - 2)
            if _partner(noun):                                       # サービスを利用する, 自分を反省する
                # …with the する's voice as the text has it: 死亡が確認される, never 死亡が確認する.
                _pair(counts, x, ("C6", counts.kid(noun), p1.surface), _spelling(noun), _voiced(toks, e + 1))
    if n1 is not None and n1.pos1 == "形容詞":                        # 気持ち悪い
        _pair(counts, x, ("C2", counts.kid(n1)), _spelling(n1))
    if (n1 is not None and n1.pos1 == "助詞" and n1.lemma == "の"
            and n2 is not None and n2.pos1 == "名詞"
            and n2.lemma not in _EMPTY_NOUNS):                        # 目の前, never 実りのこと
        noun = _noun(toks, e + 2)
        if _partner(noun):
            _pair(counts, x, ("K1", counts.kid(noun)), _spelling(noun))
    if _is_da(p1, "な") and p2 is not None and p2.pos1 == "形状詞":   # 貴重な〜
        _pair(counts, x, ("K5", counts.kid(p2)), _spelling(p2))


def _predicate_rules(counts, x, toks, i, cls):
    """Lines 1-2 for a verb, an い-adjective or a な-adjective at toks[i]."""
    t = toks[i]
    p1, p2, n1, n2 = _around(toks, i, i)
    if _is_particle(p1):                                             # line 1: を受ける
        _pair(counts, x, ("P", p1.surface, BEFORE))
        if p2 is not None and p2.pos1 == "名詞" and p1.pos2 == "格助詞":
            noun = _noun(toks, i - 2)
            if _partner(noun):
                if cls == VERB:                                      # 影響を受ける, 緑に囲まれる
                    _pair(counts, x, ("C3", counts.kid(noun), p1.surface), _spelling(noun),
                          _voiced(toks, i))
                elif p1.surface == "が":                             # 気持ちがいい, 時間が大切
                    _pair(counts, x, ("C4", counts.kid(noun)), _spelling(noun))
    if cls == I_ADJ and n1 is not None:
        if t.cform.startswith("連体形") and n1.pos1 == "名詞":         # 深い関係
            noun = _noun(toks, i + 1)
            if _partner(noun):
                _pair(counts, x, ("K2", counts.kid(noun)), _spelling(noun))
        elif t.cform.startswith("連用形") and n1.pos1 == "動詞":       # 深く考える
            _pair(counts, x, ("K4", counts.kid(n1), t.surface), _spelling(n1, _at(toks, i + 2)))
    if cls == NA_ADJ:
        if _is_da(n1, "に") and n2 is not None and n2.pos1 == "動詞":   # 大切にする
            _pair(counts, x, ("C5", counts.kid(n2)), _spelling(n2, _at(toks, i + 3)))
        if _is_da(n1, "な") and n2 is not None and n2.pos1 == "名詞":   # 大切な人
            noun = _noun(toks, i + 2)
            if _partner(noun):
                _pair(counts, x, ("K3", counts.kid(noun)), _spelling(noun))


def _adverb_rules(counts, x, toks, i):
    """An adverb's lines (再度, やっぱり — `_adverbial`): the predicate it goes with — 再度確認する, 再度
    見直す — and the の after it (再度の襲撃), which only an adverb's particle row shows (decision 6)."""
    n1, n2 = _at(toks, i + 1), _at(toks, i + 2)
    if n1 is None:
        return
    if n1.pos1 in ("動詞", "形容詞"):
        written = _spelling(n1, n2)
        if written:
            _pair(counts, x, ("A1", counts.kid(n1)), written)
    elif n1.pos1 == "名詞" and n1.pos3.startswith("サ変") and _is_suru(n2) and _partner(n1):
        _pair(counts, x, ("A1", counts.kid(n1)), _spelling(n1) + "する")      # 再度確認する
    elif n1.pos1 == "助詞" and n1.lemma == "の":
        _pair(counts, x, ("P", "の", AFTER))


# The auxiliaries that make a verb's form: the negative (ない, ぬ, and ん, which UniDic files under
# ず), the progressive てる, the completive ちゃう / じゃう, and the wish たい. Passive and causative are
# `_VOICE`.
_NEGATIVE = frozenset(("ない", "ぬ", "ず"))


def _verb_form(t, n1, n2):
    """-> (form, how the text writes it) for the verb `t` followed by `n1`, `n2`; None when plain.
    Always the full standard form — 知ってる is 知っている, 忘れちゃう is 忘れてしまう."""
    if n1.pos1 == "助動詞":
        if n1.lemma in _VOICE:
            return ("passive" if n1.lemma in ("れる", "られる") else "causative"), t.surface + n1.lemma
        if n1.lemma in _NEGATIVE:
            return "negative", t.surface + "ない"
        if n1.lemma == "たい":
            return "want", t.surface + "たい"
        if n1.lemma == "てる":
            return "progressive", t.surface + n1.surface[:1] + "いる"
        if n1.lemma == "ちゃう":
            return "completive", t.surface + ("で" if n1.surface.startswith("じ") else "て") + "しまう"
    if n1.pos1 == "助詞" and n1.lemma == "て" and n2 is not None:
        if n2.lemma == "居る":
            return "progressive", t.surface + n1.surface + "いる"
        if n2.lemma in ("仕舞う", "しまう"):
            return "completive", t.surface + n1.surface + "しまう"
    return None


def _form_rules(counts, x, toks, s, e, cls):
    """Line 4 — the form the word spanning toks[s..e] takes, when it is not its plain dictionary
    form: a verb's voice, negative, progressive or wish (囲まれる, 構わない, 知っている); an
    い-adjective's く / くない / さ (深く, 大きさ); a な-adjective's or noun's な / に / だ and a noun's
    する (大切な, 無理だ, 期待する). `{w}` stands for the card's own word, as in a collocation."""
    t, n1, n2 = toks[e], _at(toks, e + 1), _at(toks, e + 2)
    found = None
    if cls == VERB and n1 is not None:
        found = _verb_form(t, n1, n2)
    elif cls == I_ADJ:
        if t.cform.startswith("語幹") and n1 is not None and n1.pos1 == "接尾辞" and n1.surface == "さ":
            found = "sa", t.surface + "さ"
        elif t.cform.startswith("連用形") and t.surface.endswith("く"):
            negative = n1 is not None and n1.lemma in ("無い", "ない")
            found = ("ku-nai", t.surface + "ない") if negative else ("ku", t.surface)
    elif cls in (NA_ADJ, NOUN) and n1 is not None:
        if n1.pos1 == "助動詞" and n1.lemma == "だ" and n1.surface in ("な", "に"):
            found = n1.surface, "{w}" + n1.surface
        elif n1.pos1 == "助動詞" and (n1.lemma == "です"
                                      or (n1.lemma == "だ" and n1.cform.startswith("終止形"))):
            found = "da", "{w}だ"
        elif cls == NOUN and n1.pos1 == "動詞" and n1.lemma == "為る":
            found = "suru", "{w}する"
        elif cls == NOUN and n1.pos1 == "動詞" and n1.lemma == "出来る":     # 利用できる, however spelled
            found = "dekiru", "{w}できる"
    if found:
        _pair(counts, x, ("W", found[0]), found[1])


def _frame_rules(counts, x, toks, s, e):
    """Line 3 for a noun, compound noun or な-adjective spanning toks[s..e]."""
    p1, p2, n1, _ = _around(toks, s, e)
    if p1 is not None and (p1.pos1 == "連体詞"
                           or (p1.pos1 == "形容詞" and p1.cform.startswith("連体形"))):
        _pair(counts, x, ("F1", counts.kid(p1)), _spelling(p1))       # そんな〜, 深い〜
    if p1 is not None and p1.lemma == "言う" and p2 is not None and p2.surface in ("と", "って"):
        _pair(counts, x, ("F2",))                                    # という〜, never いう〜
    if n1 is not None and n1.pos1 == "接尾辞":
        if not (n1.lemma in _HONORIFICS and s == e and _name_like(toks[s])):
            _pair(counts, x, ("F3", counts.kid(n1)), _spelling(n1))   # 〜的, 〜さ, 〜者
    # A compound partner: the noun a noun builds a word with — 反省会, 反省点, 旅行先 (the user, U6). Never
    # a number, a proper noun or a pronoun (代名詞 is its own pos1), and never after an adverbial word: the
    # noun after 再度, 最近, 毎日 is where the sentence goes next (再度攻撃を行う, 最近旅行に行った), not a word
    # built with it — measured on the rebuilt data: 以前 〜正真, 明日 〜奈, 最近 〜旅行. Its pairings say
    # what it goes with (A1's 再度確認する).
    if (n1 is not None and n1.pos1 == "名詞" and n1.pos2 not in ("数詞", "固有名詞") and _partner(n1)
            and toks[e].pos1 == "名詞" and toks[e].pos2 != "数詞" and not _adverbial(toks[e])):
        _pair(counts, x, ("F4", counts.kid(n1)), _spelling(n1))       # 〜会, 〜点, 〜政策


def _count_token(counts, toks, i):
    """The word at toks[i]: its count, and the lines of its class. A spelling the dictionary keeps apart from its lemma
    (`_entry`: 揚げる, UniDic's 上げる) is a word of its own as well — counted and given its lines under that spelling —
    while its lemma keeps the use, as a compound noun's parts keep theirs: nothing any word had before is lost, and to
    the words around it, it is the word UniDic reads."""
    t = toks[i]
    if t.lemma == "言う" and i >= 1 and toks[i - 1].surface in ("と", "って"):
        counts.teiu += 1
    cls = _CLASS_OF_POS1.get(t.pos1)
    for word in ((t, t._replace(lemma=t.entry, entry="")) if t.entry else (t,)):
        x = _tally(counts, word)
        if cls == NOUN:
            _noun_rules(counts, x, toks, i, i)
        elif cls is not None:
            _predicate_rules(counts, x, toks, i, cls)
        if cls in (NOUN, NA_ADJ):
            _frame_rules(counts, x, toks, i, i)
        if cls is not None:
            _form_rules(counts, x, toks, i, i, cls)
        if _adverbial(t):
            _adverb_rules(counts, x, toks, i)


def _piece(toks, i, analyzer):
    """Is the one-kanji word at toks[i] (a sentence, or a joined word's parts in place: `count`) a piece of something
    else there — glued to another one-kanji piece (斬 + 魄 + 刀: the builder reads a work's terms apart, as it never
    applies one library's name tables) or right after a number (三 + 年, 二十 + 歳)? The list's own test
    (`analyzer.bound_uses`), so a word's lines come from the uses the list counts it by. It looks only at what touches
    the word: first whether a number or a kanji touches it at all (the test's first look, `analyzer._may_be_bound`;
    most uses stand beside kana or punctuation: 手を, 私は, 何？), then the test's own verdict on the word, its two
    neighbours and the token before the left one (`analyzer._bound_at`, given where each of them stands: the window's
    text is their surfaces end to end, so the builder knows it without searching) — a counter written in kanji right
    after a number makes the word after it a piece of the count, and the number is two tokens back (２ + 時間 + 目).
    """
    # A piece the tagger reads from inside one character (an accent mark after a kanji) keeps no text of its own.
    before = toks[i - 1].surface[-1:] if i else ""
    after = toks[i + 1].surface[:1] if i + 1 < len(toks) else ""
    if not (before.isnumeric() or _KANJI.match(before) or _KANJI.match(after)) or not _KANJI.match(toks[i].lemma):
        return False
    start = max(i - 2, 0)
    window = toks[start:i + 2]
    spans, at = [], 0                   # where each counted word of the window stands in its text
    for t in window:
        if t.word:
            spans.append((at, at + len(t.surface)))
        at += len(t.surface)
    return analyzer._bound_at("".join([t.surface for t in window]), spans, sum(1 for t in toks[start:i] if t.word))


def count(sentences, counts):
    """Accumulate §6's patterns from `sentences` (lists of `Tok`) into `counts`. Pure."""
    from app import analyzer
    for toks in sentences:
        for i, t in enumerate(toks):
            if not t.word:
                continue
            counts.tokens += 1
            # A one-kanji word (one character from U+3400, where Han begins: kana and grammar sort below it) standing
            # as a piece of something else is no use of the word: no count, no line on its row.
            if t.lemma >= "\u3400" and len(t.lemma) == 1 and _piece(toks, i, analyzer):
                counts.bound[(t.lemma, t.reading)] += 1
                continue
            _count_token(counts, toks, i)
        # A word that took a suffix (利用者, 可能性, 奨学金) is a word of its own AND its base keeps the
        # use: the base and its suffixes are counted as the text has them, so 利用 still gets 〜者 and 〜料
        # (Patterns_Quality_Spec.md §8.1 a). A prefix makes another word (不自然 is not 自然): its base
        # does not count that use. Nor is a word shown with its ending counted again as its first part:
        # ドキッと is どき itself (the sound word + と, one token), already counted above. A one-kanji part is
        # judged as the parts stand (`_piece`): 歳 after 二十 in 二十歳 is a piece, as 年 is in 三年.
        for i, t in enumerate(toks):
            if (t.parts and t.parts[0].pos1 != "接頭辞"
                    and (t.parts[0].lemma, t.parts[0].reading) != (t.lemma, t.reading)):
                view = toks[:i] + list(t.parts) + toks[i + 1:]
                for j in range(i, i + len(t.parts)):
                    part = view[j]
                    if not part.word:       # a number inside a word (二十歳's 二十) is no word here either
                        continue
                    if part.lemma >= "\u3400" and len(part.lemma) == 1 and _piece(view, j, analyzer):
                        counts.bound[(part.lemma, part.reading)] += 1
                        continue
                    _count_token(counts, view, j)
        # A compound noun is a word of its own as well (奨学金, 時間帯 — 156 of the user's Lapis
        # notes were skipped as "phrases" without this): counted and given a noun's lines as one
        # unit. Its parts keep their own counts, so nothing a single word had before is lost.
        i = 0
        while i < len(toks):
            run = _run(toks, i) if toks[i].pos1 in _COMPOUND_POS1 else None
            if run:
                x = _tally(counts, _compound(toks, *run))
                _noun_rules(counts, x, toks, *run)
                _frame_rules(counts, x, toks, *run)
                _form_rules(counts, x, toks, *run, NOUN)
                i = run[1] + 1
            else:
                i += 1
    return counts


# --- scoring (pure) ----------------------------------------------------------------------------- #
def log_dice(fxy, fx, fy):
    """`14 + log2(2·f(x,y) / (f(x) + f(y)))` — Sketch Engine's and NLT's association score.

    It is what stops every word's top collocate being する or ある: raw counts favour whatever is
    common everywhere; logDice favours what is common *with this word*."""
    return 14.0 + math.log2(2.0 * fxy / (fx + fy))


def score(counts, floor):
    """-> (lemma_rows, alias_rows, pattern_rows) for the store.

    Only words with at least `floor` occurrences get pattern rows (D5); every word keeps its lemma
    and alias rows, so the panel can still say "too rare (7 < 12)" instead of "not found"."""
    # Commonest spelling / part of speech; a tie goes to the smaller string, never to whichever was
    # counted first — a parallel build merges its workers in no fixed order, and the database must
    # come out the same however many processes made it.
    best_orth, best_pos = {}, {}
    for best, counter in ((best_orth, counts.orth), (best_pos, counts.pos)):
        for (i, value), c in counter.items():
            cur = best.get(i)
            if cur is None or c > cur[1] or (c == cur[1] and value < cur[0]):
                best[i] = (value, c)

    def orth_of(i):
        return best_orth.get(i, (counts.keys[i][0], 0))[0]

    def pos_of(i):
        return best_pos.get(i, ("", 0))[0]

    # A word's OWN part of speech — the side its card puts the particles on — is its commonest use of a
    # class the rules count, when it has one: the particles were counted from those uses alone. 目 is 名詞
    # though the counter 〜目 (三回目, 二年目 — a suffix, same lemma, same reading) outnumbers it in news,
    # which filed it 接尾辞 and put its を on the wrong side (Patterns_Spec.md §19.1). A frame's
    # construction still takes `pos_of`, every use.
    own_pos = {}
    for (i, value), c in counts.pos.items():
        cur = own_pos.get(i)
        if value in _CLASS_OF_POS1 and (cur is None or c > cur[1] or (c == cur[1] and value < cur[0])):
            own_pos[i] = (value, c)
    # An adverbial word used more as an adverb than with its particles is filed 副詞, so its card shows
    # 〜の and its predicates (再度: 76% adverbial) — only such words ever carry an A1 row (§8.1 e).
    adverb_uses, particle_uses = Counter(), Counter()
    for (x, key), c in counts.pattern.items():
        if key[0] == "A1":
            adverb_uses[x] += c
        elif key[0] == "P":
            particle_uses[x] += c
    for i in adverb_uses:
        if adverb_uses[i] > particle_uses[i]:
            own_pos[i] = ("副詞", adverb_uses[i])

    # How each pairing wrote its two words, by the same tie rule: 目に遭う is written 遭う although
    # 会う is the lemma's commonest spelling overall, 期待に応える 応える rather than 答える, and the
    # 囲む card's 緑に… is 緑に囲まれる. Only for the pairings that can reach a card — a small share of
    # them all — so a laptop's library build does not hold a second copy of every pair it counted.
    wanted = {(x, key) for (x, key), c in counts.pattern.items()
              if c >= MIN_PATTERN and counts.word[x] >= floor and key[0] != "P"}
    best_spell = {}
    for (x, key, other, target), c in counts.spell.items():
        if (x, key) not in wanted:
            continue
        cur = best_spell.get((x, key))
        if cur is None or c > cur[1] or (c == cur[1] and (other, target) < cur[0]):
            best_spell[(x, key)] = ((other, target), c)

    def shown(x, key, y):
        """-> (word `y`, word `x` or "") as pattern `key` of `x` writes them — `y` in the modern
        じる form where the text has that spelling too. UniDic files 信じて / 感じた under 信ずる /
        感ずる, so the ずる spelling outnumbers the じる one about five to one, though nobody writes
        神を信ずる today. "" for `x` is its plain form, which the card's own word stands in for."""
        (other, target), _ = best_spell.get((x, key), ((orth_of(y), ""), 0))
        if other.endswith("ずる") and counts.orth.get((y, other[:-2] + "じる")):
            other = other[:-2] + "じる"
        return other, target

    lemma_rows = [(lemma, reading, orth_of(i), own_pos.get(i, (pos_of(i), 0))[0], counts.word[i])
                  for i, (lemma, reading) in enumerate(counts.keys)]
    alias_rows = [(orth, counts.keys[i][0], counts.keys[i][1], c) for (i, orth), c in counts.orth.items()]

    pattern_rows = []
    for (x, key), c in counts.pattern.items():
        fx = counts.word[x]
        if fx < floor:
            continue
        lemma, reading = counts.keys[x]
        rule = key[0]
        files = counts.docs.get((x, key), 0)
        if rule == "P":                      # the particle's side is its section (§8.1 b)
            pattern_rows.append((lemma, reading, "particle", key[1], c, None, key[2] if len(key) > 2 else None,
                                 files))
            continue
        if rule == "W":                      # a form, kept when common enough to say something
            if c >= MIN_PATTERN and c >= FORM_SHARE * fx:
                (text, _), _ = best_spell.get((x, key), ((key[1], ""), 0))
                pattern_rows.append((lemma, reading, "form", text, c, None, "W", files))
            continue
        if c < MIN_PATTERN:
            continue
        if rule == "F3" and counts.keys[key[1]][0] in _HONORIFICS and c < HONORIFIC_SHARE * fx:
            continue                         # a name's honorific, not the word's own (実りちゃん)
        # The collocate's own count. C1's key is (rule, particle, y): reading key[1] there took the
        # particle as y, found no count, and so scored every 気持ちになる-type item as if なる were
        # rare — common verbs (なる, する, ある) floated to the top of line 2.
        # A one-kanji piece (`Counts.bound`) is still the text's token: y is weighed by every time it appears.
        y = None if rule == "F2" else key[_Y.get(rule, 1)]
        fy = counts.teiu if y is None else counts.word[y] + counts.bound.get(counts.keys[y], 0)
        other, target = ("", "") if y is None else shown(x, key, y)
        item = _render(rule, key, other)
        if target:                           # the text's own passive / causative: 緑に囲まれる, and
            # a する-noun's する in it: 死亡が確認される (the word itself stays {w})
            item = item.replace("{w}する", "{w}" + target) if rule == "C6" else item.replace("{w}", target)
        pattern_rows.append((lemma, reading, _KIND[rule], item, c,
                             round(log_dice(c, fx, max(fy, c)), 3), _section(rule, key, pos_of, other), files))
    return lemma_rows, alias_rows, pattern_rows


def _section(rule, key, pos_of, other=""):
    """The construction an item comes from — NLT's pattern groups: …を受ける and …に受ける are two,
    この〜 (a 連体詞) and 深い〜 (an adjective) are two. The lookup gives each common construction a
    slot before a second item of any one of them, so four collocations show four ways the word is
    used rather than four objects of one verb."""
    if rule == "C1":                         # (rule, particle, head)
        return "C1" + key[1]
    if rule in ("C3", "C6"):                 # (rule, noun, particle)
        return rule + key[2]
    if rule == "F1":                         # (rule, modifier)
        return "F1" + pos_of(key[1])
    if rule == "F4":                         # one character builds a word (〜会); a longer one is a
        return "F4" if len(other) == 1 else "F4m"     # compound (〜政策), capped in the lookup (U10)
    return rule


def _render(rule, key, other):
    """The item as a card shows it; `other` is the word it pairs with, spelled as the pairing writes
    it. `{w}` stands for the card's own word — filled in by the formatter, so a card that says 感じる
    shows 影響を感じる even where the library wrote 感じ."""
    if rule == "C1":
        return "{w}" + key[1] + other
    if rule == "C2":
        return "{w}" + other
    if rule == "C3":
        return other + key[2] + "{w}"
    if rule == "C4":
        return other + "が{w}"
    if rule == "C5":
        return "{w}に" + other
    if rule == "C6":
        return other + key[2] + "{w}する"
    if rule == "A1":
        return "{w}" + other
    if rule == "F4":
        return "〜" + other
    if rule == "F1":
        return other + "〜"
    if rule == "F2":
        return "という〜"
    if rule == "F3":
        return "〜" + other
    if rule == "K1":
        return "{w}の" + other
    if rule == "K2":
        return "{w}" + other
    if rule == "K3":
        return "{w}な" + other
    if rule == "K4":
        return key[2] + other
    if rule == "K5":
        return other + "な〜"
    raise ValueError(rule)


# --- I/O ---------------------------------------------------------------------------------------- #
def default_db_path(language="ja", name=None):
    """`patterns_ja.db` for the library; `patterns_ja_<name>.db` for a named general corpus."""
    # Imported here, not at module level: the tests redirect this name by patching app.path_utils.
    from app.path_utils import get_persistent_user_data_path
    suffix = f"_{name}" if name else ""
    return os.path.join(get_persistent_user_data_path(), f"patterns_{language}{suffix}.db")


def library_size(language="ja"):
    """(words, files) in `language`'s library as the token store counts them now — the words a Generate counts, summed
    in one query, read without writing anything — or None before there is a store. A library build records what it was
    built from (`build`: `library_tokens`, `library_files`), and Backfill compares the two to rebuild a set the library
    has outgrown (`backfill.growth`). The store holds the three tiers a Generate reads; Graduated is the build's own."""
    from app.token_index import store_path_for
    path = store_path_for(language)
    if not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)
        try:
            words, files = con.execute("SELECT COALESCE(SUM(total), 0), COUNT(*) FROM files").fetchone()
        finally:
            con.close()
        return int(words), int(files)
    except sqlite3.Error:
        return None


def corpus_files(corpus_dir=None, language="ja"):
    """-> (kind, root, [paths]). `corpus_dir` empty = the user's library (F13); a folder, or a list
    of folders read as one corpus (a general set made of several sources, WP-P10)."""
    from app.path_utils import get_data_path, is_content_file
    if corpus_dir:
        roots = [corpus_dir] if isinstance(corpus_dir, str) else list(corpus_dir)
        kind, root = "general", " + ".join(roots)
    else:
        root = get_data_path(language)
        roots, kind = [os.path.join(root, name) for name in LIBRARY_FOLDERS], "library"
    paths = []
    for base in roots:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d != ".trash")
            paths.extend(os.path.join(dirpath, f) for f in sorted(filenames) if is_content_file(f))
    return kind, root, paths


def _write_db(path, counts, floor, meta):
    if meta.get("language") == "zh":                  # Chinese counts its own way, into the same rows
        from modules.junban import patterns_zh
        lemma_rows, alias_rows, pattern_rows = patterns_zh.score(counts, floor)
    else:
        lemma_rows, alias_rows, pattern_rows = score(counts, floor)
    write_rows(path, lemma_rows, alias_rows, pattern_rows, meta)
    return len(pattern_rows)


def write_rows(path, lemma_rows, alias_rows, pattern_rows, meta):
    """Create the §WP-P2 schema at `path` and fill it. The tests build exact stores through this; a
    pattern row written without its `section` or `files` (a store made by hand) gets none."""
    con = sqlite3.connect(path)
    try:
        con.executescript("""
            CREATE TABLE lemma   (lemma TEXT, reading TEXT, orth TEXT, pos TEXT, count INTEGER,
                                  PRIMARY KEY (lemma, reading));
            CREATE TABLE alias   (orth TEXT, lemma TEXT, reading TEXT, count INTEGER);
            CREATE TABLE pattern (lemma TEXT, reading TEXT, kind TEXT, item TEXT, count INTEGER,
                                  logdice REAL, section TEXT, files INTEGER);
            CREATE TABLE meta    (key TEXT PRIMARY KEY, value TEXT);
        """)
        con.executemany("INSERT INTO lemma VALUES (?,?,?,?,?)", lemma_rows)
        con.executemany("INSERT INTO alias VALUES (?,?,?,?)", alias_rows)
        con.executemany("INSERT INTO pattern VALUES (?,?,?,?,?,?,?,?)",
                        (tuple(row) + (None,) * (8 - len(row)) for row in pattern_rows))
        con.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
        con.executescript("""
            CREATE INDEX ix_pattern ON pattern(lemma, reading, kind, logdice DESC);
            CREATE INDEX ix_alias   ON alias(orth);
        """)
        con.commit()
    finally:
        con.close()


def merge(into, part):
    """Add the counts of `part` (a worker's) to `into`. Ids differ between processes, so every id is
    mapped through its (lemma, reading) key; strings inside a rule key (particles, a surface) stay."""
    remap = [into.kid(Tok("", lemma, reading, "", "", "", "", "")) for lemma, reading in part.keys]
    for i, c in part.word.items():
        into.word[remap[i]] += c
    for (i, orth), c in part.orth.items():
        into.orth[(remap[i], orth)] += c
    for (i, pos1), c in part.pos.items():
        into.pos[(remap[i], pos1)] += c
    for (x, key), c in part.pattern.items():
        into.pattern[(remap[x], tuple(remap[v] if isinstance(v, int) else v for v in key))] += c
    for (x, key, other, target), c in part.spell.items():
        into.spell[(remap[x], tuple(remap[v] if isinstance(v, int) else v for v in key), other, target)] += c
    for (x, key), c in part.docs.items():           # a document never spans two files: plain addition
        into.docs[(remap[x], tuple(remap[v] if isinstance(v, int) else v for v in key))] += c
    into.bound.update(part.bound)                   # keyed by (lemma, reading): no ids to map
    into.teiu += part.teiu
    into.tokens += part.tokens
    return into


_WORKER = {}


def _init_worker(language, reinforce=False, kind="library"):
    """One tagger per worker process, made once (spawned on Windows, so nothing is inherited) — and the
    counting for the language: fugashi and this module's rules for Japanese; jieba and patterns_zh's for
    Chinese (`reinforce` is retired and ignored, as by the analyzer). `kind` says what a document is
    (`_count_file`)."""
    from app import analyzer
    boundaries = analyzer.LOGIC.get("sentence_boundaries", {})
    if language == "zh":
        from modules.junban import patterns_zh
        stops = frozenset(boundaries.get("zh", "。！？!?\n；;……｡"))
        _WORKER.update(language=language, analyzer=analyzer, kind=kind,
                       count=lambda text, counts: patterns_zh.count(patterns_zh.iter_tokens(text, stops), counts))
        return
    # The analyzer's tagger: it reads text as the tokenizer does (ﾅｲﾌ is ナイフ, analyzer.tagger_text).
    tagger, stops = analyzer.Tagger(), frozenset(boundaries.get("ja", "。！？!?\n"))
    _WORKER.update(language=language, analyzer=analyzer, kind=kind,
                   count=lambda text, counts: count(iter_tokens(text, tagger, analyzer._sanitize_term, stops), counts))


_BLANK_LINE = re.compile(r"\n[ \t　]*\n")


def _count_file(path, counts):
    """Count one file, a document at a time (§8.1 h). A library file is one document — a subtitle file's
    cues are blank-line separated, so it is never split. A general corpus is prepare.py's staged text,
    which ends every document (a work, an article, a dialogue) with a blank line."""
    w = _WORKER
    text = w["analyzer"].extract_text(path, w["language"])
    for document in ([text] if w.get("kind") == "library" else _BLANK_LINE.split(text)):
        w["count"](document, counts)
        counts.end_document()


def _count_paths(paths):
    """Count a batch of files in a worker; the parent merges the result (see `merge`)."""
    counts = Counts()
    for path in paths:
        _count_file(path, counts)
    return counts, len(paths)


def _batches(paths, target_bytes=4_000_000):
    """Group files into ~4 MB batches: small enough to spread over the workers and to merge as they
    finish (the parent never holds more than one worker's batch besides the total), big enough that
    process traffic stays small next to the tokenising."""
    batch, size = [], 0
    for path in paths:
        batch.append(path)
        size += os.path.getsize(path)
        if size >= target_bytes:
            yield batch
            batch, size = [], 0
    if batch:
        yield batch


def build(corpus_dir=None, db_path=None, progress=None, language="ja", floor=None, workers=1,
          name=None, reinforce=False):
    """Walk the corpus, count, and write the database atomically. -> the meta dict it stored.

    Built into `<db>.tmp` and moved over the real file only once complete, so an interrupted build
    leaves the previous database untouched (spec WP-P2). `floor` overrides D5's choice (tests).
    `workers` > 1 counts in that many processes — for preparing a large general corpus on a strong
    machine (WP-P10); the app's own library build keeps one. `name` picks the database's file
    (`patterns_ja_<name>.db`), so the library and each general corpus live side by side. `language` zh
    counts Chinese (patterns_zh.py) into `patterns_zh[_<name>].db`, keyed as the token store keys it
    (Patterns_Chinese_Spec.md §8); `reinforce` is retired and ignored (an old command line may pass it).
    A library build records how big the library was as it read it, as the token store counts it (`library_tokens`,
    `library_files`): Backfill builds the set again once the library has grown well past that (`backfill.growth`)."""
    db_path = db_path or default_db_path(language, name)
    kind, root, paths = corpus_files(corpus_dir, language)
    size = library_size(language) if kind == "library" else None     # a general corpus is no one's library
    if floor is None:
        floor = FLOOR_GENERAL if kind == "general" else FLOOR_LIBRARY

    unique, seen, duplicates = [], set(), 0
    for path in paths:
        try:
            with open(path, "rb") as f:
                digest = hashlib.sha1(f.read()).hexdigest()
        except OSError:
            continue
        if digest in seen:
            duplicates += 1
        else:
            seen.add(digest)
            unique.append(path)

    counts = Counts()
    if workers <= 1:
        _init_worker(language, reinforce, kind)
        for n, path in enumerate(unique, 1):
            _count_file(path, counts)
            if progress:
                progress(n, len(unique))
    else:
        # ProcessPoolExecutor, not multiprocessing.Pool: when a worker dies (it cannot import, it
        # runs out of memory) the executor raises BrokenProcessPool and the build stops with the old
        # database intact. Pool silently starts a replacement worker, which dies the same way,
        # forever — measured 2026-09-24: 64 MB of tracebacks before it was killed.
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor, as_completed
        done = 0
        with ProcessPoolExecutor(workers, multiprocessing.get_context("spawn"),
                                 _init_worker, (language, reinforce, kind)) as pool:
            for future in as_completed([pool.submit(_count_paths, b) for b in _batches(unique)]):
                part, n = future.result()
                merge(counts, part)
                done += n
                if progress:
                    progress(done, len(unique))

    meta = {"corpus": root, "corpus_kind": kind, "files": len(seen), "duplicates": duplicates,
            "tokens": counts.tokens, "floor": floor, "language": language,
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "builder_version": BUILDER_VERSION}
    if language == "zh":            # keyed in Simplified, cut as the analyzer cuts (Chinese spec §7)
        from modules.junban import patterns_zh
        meta.update(builder_version=patterns_zh.BUILDER_VERSION, script="s", reinforce=False)   # retired
    if size is not None:
        meta.update(library_tokens=size[0], library_files=size[1])
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    tmp = db_path + ".tmp"
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        meta["patterns"] = _write_db(tmp, counts, floor, meta)
        os.replace(tmp, db_path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return meta


@without_cycle_collection
def main(argv=None):
    """CLI for the subprocess: `junban_patterns [--corpus DIR] [--db PATH]`. Prints PROGRESS n/total."""
    import argparse
    parser = argparse.ArgumentParser(description="Build the パターン database (Patterns_Spec.md).")
    parser.add_argument("--corpus", default="", help="a folder to read instead of the library")
    parser.add_argument("--db", default="", help="where to write (default: next to the token store)")
    parser.add_argument("--name", default="", help="a general corpus's name: patterns_ja_<name>.db")
    parser.add_argument("--workers", type=int, default=1, help="processes to count in (default 1)")
    parser.add_argument("--language", default="ja", choices=("ja", "zh"), help="the library's language")
    parser.add_argument("--reinforce", action="store_true", help="Retired: ignored (an old command line may pass it)")
    args = parser.parse_args(argv)

    def _progress(done, total):
        if done == total or done % 25 == 0:
            print(f"PROGRESS {done}/{total}", flush=True)

    try:
        meta = build(args.corpus or None, args.db or None, progress=_progress, language=args.language,
                     workers=args.workers, name=args.name or None, reinforce=args.reinforce)
    except Exception as e:
        print(f"Error: the パターン build failed ({e}). The previous database is unchanged.")
        return 1
    print(f"Built: {meta['files']} files ({meta['duplicates']} duplicates skipped), "
          f"{meta['tokens']:,} tokens, {meta['patterns']:,} patterns, floor {meta['floor']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
