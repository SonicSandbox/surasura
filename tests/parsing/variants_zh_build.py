"""Trial variants for step 4 (Chinese) — each decision of docs/agent instructions/Chinese_Build_Spec.md as a patch of
how the app reads Chinese, for one scorecard run (Parsing_Suite.md §10). Nothing in app/ or modules/ changes.

Goes into tests/parsing/ as variants_zh_build.py (STAGING.md): load_variants imports every variants_*.py, sorted, so
this file loads after variants_zh.py, whose zh-hmm-off and zh-asis-via-simplified the composites below enter.

    zh-boundaries-gb            ZH-BOUNDARIES: the zh sentence-end set without …… ； ; — 。｡！？!?\\n (GB/T 15834-2011:
                                省略号 and 分号 sit inside a sentence), set through the frozen settings as
                                paren-readings-any sets its option
    zh-hmm-off-via-simplified   ZH-HMM + ZH-TRAD-ASIS as they are built together (Z3): zh-hmm-off inside
                                zh-asis-via-simplified
    zh-hmm-off-names-surname    the same, with a names guard (ZH-HMM's condition): a run jieba's HMM keeps whole stays
                                whole when it is 2-3 characters, not a dictionary word, led by a character CC-CEDICT
                                gives a surname, with no character that is grammar by jieba's own tag table, and — at 3
                                characters — not ending in a verb; else its 2-character head is tried (龙仁 + 用)
    zh-cedict-split             ZH-DICTIONARY: a jieba dictionary entry CC-CEDICT doesn't list is split into the words
                                jieba then finds among those CC-CEDICT lists (吃了饭 -> 吃 / 了 / 饭), jieba's name-tagged
                                entries spared; and a CC-CEDICT unit of a numeral + what follows that the UD treebanks
                                cut after the numeral in most of their uses is cut too (一个 -> 一 / 个; 一下, 一些, 一眼
                                stay whole)
    zh-cedict-split-all         the same, no entry spared for its name tag — what the tags spare, and what junk they keep
                                (喝咖啡 and 考完试 are tagged as names)
    zh-cedict-grammar           the narrow form (the decisions doc calls it zh-cedict-split-grammar): only a split whose
                                pieces hold grammar — an aspect marker or particle by jieba's tags (了 过 着 的 地 得 吧),
                                the degree adverb 很, or a numeral or demonstrative + a measure word
    zh-numerals-not-words       ZH-NUMERALS: a token of numeral characters only (GB/T 15835-2011's, with 两) is no word,
                                unless CC-CEDICT lists it as a common word with a meaning that counts nothing (千万 'by
                                all means', 万一 'just in case', 一一 'one by one')
    zh-cedict-split-numerals    zh-cedict-split + zh-numerals-not-words: the numeral inside 一碗 needs the split first
    zh-redup-lemma              ZH-LEMMA: a doubled form counts as its base when the base is a CC-CEDICT word — an AABB
                                token (开开心心 -> 开心), a two-character word said twice (休息休息 -> one 休息), a run of
                                one character cut by length (哈哈哈 + 哈哈 -> one 哈哈)
    zh-redup-lemma-own-meaning  the same, except an AABB form CC-CEDICT lists with meanings mostly its base lacks
                                (马马虎虎 'so-so, tolerable' beside 马虎 'careless') — OGO-EXCEPTIONS' own-meaning test
    zh-t-taiwan-variants        ZH-S2T-CHI option (c): the Traditional setting writes Taiwan's standard character where
                                OpenCC's form is its variant (喫 -> 吃, 爲 -> 為, 裏 -> 裡, 麪 -> 麵) — OpenCC's own
                                TWVariants.txt, not in docs/assets/opencc/ until the user OKs the download

Data is read when a variant is entered, once per process (the guard enters every variant, so the first entry pays about
2 s): CC-CEDICT from docs/assets/zh_gold/cedict_1_0_ts_utf-8_mdbg.zip, the UD Chinese treebanks from
docs/assets/zh_gold/ud/, jieba's tag table from jieba.posseg — never at import. zh-t-taiwan-variants reads its table on
entry when the file is there; without it the variant still enters and leaves cleanly (the guard runs it on every
machine), and a scorecard run under it errors on every Traditional case, naming the missing file.

What they can't show: the numeral, doubling and boundary variants patch the tokenizer (or the settings) — the パターン
builder's cut (patterns_zh, through jieba.cut) is reached only by the HMM, script and split variants; and nothing
list-level (every list a layer reads is the snapshot's).
"""
import math
import os
import re
import zipfile
from collections import Counter

from app import analyzer, zh_script
from tests.parsing import harness, variants_zh  # noqa: F401 — variants_zh registers zh-hmm-off, zh-asis-via-simplified
from tests.parsing.harness import ROOT, patched
from tests.parsing.variants import VARIANTS, variant

GOLD = os.path.join(ROOT, "docs", "assets", "zh_gold")
CEDICT = os.path.join(GOLD, "cedict_1_0_ts_utf-8_mdbg.zip")
UD = os.path.join(GOLD, "ud")
TW_VARIANTS = os.path.join(ROOT, "docs", "assets", "opencc", "TWVariants.txt")

# ZH-BOUNDARIES' set: a sentence ends at 。 (and the half-width ｡), ！ ？ ! ? and a line end — no longer at …… or ；;.
GB_BOUNDARIES = "。｡！？!?\n"
# The numerals of Chinese running text (GB/T 15835-2011, 出版物上数字用法: 〇 一 … 九 十 百 千 万 亿, with 零 and the
# Traditional 萬 億) and 两 / 兩, the numeral a count takes (两个). Unicode's numeric property is no test: it numbers the
# financial forms (拾 10, 陆 6, 参 3 — also the words 'pick up', 'land', 'take part') and gives 兩 2 but 两 nothing.
NUMERALS = frozenset("〇零一二三四五六七八九十百千万亿萬億两兩")
# jieba's tags for names (people, places, organisations, other proper nouns) — what zh-cedict-split spares.
NAME_TAGS = frozenset(("nr", "nrfg", "nrt", "ns", "nt", "nz"))
# jieba's tags for grammar — a character of a guessed run tagged so is no piece of a name (NAMES-KANJI's "not when a
# piece is grammar"): prepositions, conjunctions, particles, modal particles, interjections, onomatopoeia, pronouns,
# adverbs, numerals, measure words, localisers.
GRAMMAR_TAGS = frozenset(("p", "c", "u", "uj", "ul", "uz", "ug", "uguo", "uv", "ud", "y", "e", "o", "r", "d", "m", "q",
                          "f"))
# The aspect markers and particles by jieba's tags (了 ul, 着 uz, 过 ug, 的 uj, 地 uv, 得 ud, 吧 y) — zh-cedict-grammar.
PARTICLE_TAGS = frozenset(("ul", "uz", "ug", "uguo", "uj", "uv", "ud", "y"))
_DATA = {}


# --- data, read when a variant is entered ---------------------------------------------------------------------- #
_ENTRY = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")


def cedict():
    """{Simplified headword: [(pinyin, [senses]), ...]} — every CC-CEDICT entry, read once."""
    if "cedict" not in _DATA:
        if not os.path.isfile(CEDICT):
            raise FileNotFoundError(f"{CEDICT} is missing — python docs/assets/zh_gold/fetch_gold.py")
        with zipfile.ZipFile(CEDICT) as archive:
            text = archive.read("cedict_ts.u8").decode("utf-8")
        entries = {}
        for line in text.splitlines():
            found = None if line.startswith("#") else _ENTRY.match(line)
            if found:
                _traditional, simplified, pinyin, senses = found.groups()
                entries.setdefault(simplified, []).append(
                    (pinyin, [sense.strip() for sense in senses.split("/") if sense.strip()]))
        _DATA["cedict"] = entries
    return _DATA["cedict"]


def words():
    """CC-CEDICT's Simplified headwords of two characters or more — the words the dictionary lists."""
    if "words" not in _DATA:
        _DATA["words"] = frozenset(word for word in cedict() if len(word) > 1)
    return _DATA["words"]


def surnames():
    """The single characters CC-CEDICT gives a surname sense (李 'surname Li', 王, 龙 — 744 on 2026-09-23)."""
    if "surnames" not in _DATA:
        _DATA["surnames"] = frozenset(word for word, entries in cedict().items() if len(word) == 1 and any(
            sense.startswith("surname ") for _pinyin, senses in entries for sense in senses))
    return _DATA["surnames"]


def classifiers():
    """The single characters CC-CEDICT gives a measure-word sense ('classifier for books …': 本, 碗, 个)."""
    if "classifiers" not in _DATA:
        _DATA["classifiers"] = frozenset(word for word, entries in cedict().items() if len(word) == 1 and any(
            sense.startswith("classifier") for _pinyin, senses in entries for sense in senses))
    return _DATA["classifiers"]


_NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                 "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundreds "
                 "hundred thousands thousand millions million billions billion trillions trillion and an a or of the")
_COUNT = re.compile(r"^(?:[\d.,%+/:;\s\-–]|(?:" + "|".join(_NUMBER_WORDS.split()) + r")\b|giga-|mega-)+$", re.I)
_QUANTITY = re.compile(r"\b(?:numbers?|numerous|innumerable|countless|many|myriads?|multitud\w*|several|few|lots?|"
                       r"plenty|little|bit|some|untold|dozens?|enormous quantity)\b", re.I)


def counts_nothing(sense):
    """Is a CC-CEDICT sense no count — neither a number (twelve, 12, ten million, 5-1) nor a quantity (countless, a
    few, a great number)? 'one by one', 'by all means', 'just in case', 'idiot' count nothing."""
    sense = re.sub(r"\([^)]*\)", "", sense).strip(" ;,")
    return bool(sense) and not _COUNT.match(sense) and not _QUANTITY.search(sense)


def not_counts():
    """The words made only of numerals that CC-CEDICT lists as a common word (lower-case pinyin — 十一 'National Day' is
    a name, 十一 'eleven' a number) with a meaning that counts nothing: 千万, 万一, 一一, 二百五 — the short list the
    user reads with the build."""
    if "not_counts" not in _DATA:
        _DATA["not_counts"] = frozenset(
            word for word, entries in cedict().items() if len(word) > 1 and all(ch in NUMERALS for ch in word)
            and any(pinyin[:1].islower() and any(counts_nothing(sense) for sense in senses)
                    for pinyin, senses in entries))
    return _DATA["not_counts"]


def numeral_units():
    """The CC-CEDICT words made of a numeral and what follows it that the UD Chinese treebanks cut after the numeral in
    most of their uses, at least twice — a count, kept apart as Japanese counts are: 一个 (cut 342 times, whole never),
    一次, 一种, 一名. One they keep whole (一些, 一样, 一起, 一下) or never meet (一眼) stays whole: the dictionary wins.
    The treebanks' Traditional (HK) is read as Simplified."""
    if "units" not in _DATA:
        if not os.path.isdir(UD):
            raise FileNotFoundError(f"{UD} is missing — python docs/assets/zh_gold/fetch_gold.py")
        whole, cut = Counter(), Counter()

        def tally(forms):
            whole.update(forms)
            for first, second in zip(forms, forms[1:]):
                if first and all(ch in NUMERALS for ch in first):
                    cut[first + second] += 1
        for name in sorted(os.listdir(UD)):
            if not name.endswith(".conllu"):
                continue
            forms = []
            with open(os.path.join(UD, name), encoding="utf-8") as handle:
                for line in handle:
                    columns = line.rstrip("\n").split("\t")
                    if len(columns) > 1 and columns[0].isdigit():
                        forms.append(zh_script.to_simplified(columns[1]))
                    elif not line.strip():
                        tally(forms)
                        forms = []
            tally(forms)
        _DATA["units"] = frozenset(word for word in words() if word[0] in NUMERALS
                                   and not all(ch in NUMERALS for ch in word) and cut[word] >= 2
                                   and cut[word] > whole[word])
    return _DATA["units"]


def tag_table():
    """jieba's own tag for each dictionary word (posseg's word_tag_tab), loaded once — posseg is never asked to cut."""
    if "tags" not in _DATA:
        import jieba.posseg as posseg
        _DATA["tags"] = posseg.dt.word_tag_tab
    return _DATA["tags"]


def tw_variants():
    """OpenCC's Taiwan variants (TWVariants.txt: OpenCC's standard form -> Taiwan's, one character to one), as a
    str.translate table — read once; FileNotFoundError while the file isn't there."""
    if "tw" not in _DATA:
        if not os.path.isfile(TW_VARIANTS):
            raise FileNotFoundError(f"{TW_VARIANTS} is missing — OpenCC ver.1.4.2's data/dictionary/TWVariants.txt, "
                                    "fetched once with the user's OK (Chinese_Build_Spec.md Z7)")
        table = {}
        with open(TW_VARIANTS, encoding="utf-8") as handle:
            for line in handle:
                key, _tab, values = line.rstrip("\r\n").partition("\t")
                first = values.split(" ")[0] if values else ""
                if len(key) == 1 and len(first) == 1 and key not in table:
                    table[key] = first
        _DATA["tw"] = str.maketrans(table)
    return _DATA["tw"]


def _jieba():
    import jieba
    with harness.quiet():
        jieba.initialize()
    return jieba


# --- the cut: every Chinese caller's jieba.cut (the tokenizer, the パターン builder, its lookup) ------------------- #
def _cut_through(post):
    """Patch jieba.cut where every caller looks it up, so each cut's tokens pass through `post`."""
    jieba = _jieba()
    real = jieba.cut

    def cut(sentence, cut_all=False, HMM=True, use_paddle=False):
        return iter(post(list(real(sentence, cut_all=cut_all, HMM=HMM, use_paddle=use_paddle))))
    return patched(jieba, "cut", cut)


def _recut(token):
    """jieba's own route through `token` read as Simplified (its dictionary frequencies, its sum of logs), over the words
    jieba's dictionary and CC-CEDICT both hold and single characters — never the whole token — sliced back out of the
    token as written (conversion is length-preserving)."""
    held = _DATA.setdefault("recut", {})
    if token not in held:
        jieba = _jieba()
        simplified, freq, listed = zh_script.to_simplified(token), jieba.dt.FREQ, words()
        n, logtotal = len(simplified), math.log(jieba.dt.total)
        route = [None] * n + [(0.0, n)]
        for i in range(n - 1, -1, -1):
            route[i] = max((math.log(freq.get(simplified[i:j]) or 1) - logtotal + route[j][0], j)
                           for j in range(i + 1, n + 1)
                           if j == i + 1 or ((i, j) != (0, n) and simplified[i:j] in listed
                                             and freq.get(simplified[i:j])))
        pieces, i = [], 0
        while i < n:
            j = route[i][1]
            pieces.append(token[i:j])
            i = j
        held[token] = pieces
    return held[token]


def _grammar(pieces):
    """Do a split's pieces hold grammar: an aspect marker or particle by jieba's tags, 很, or a numeral or a one-character
    pronoun (这, 那, 每) followed by a measure word (tagged q, or one CC-CEDICT calls a classifier)?"""
    tags, measure = tag_table(), classifiers()
    read = [zh_script.to_simplified(piece) for piece in pieces]
    if any(piece == "很" or tags.get(piece) in PARTICLE_TAGS for piece in read):
        return True
    return any((all(ch in NUMERALS for ch in first) or (len(first) == 1 and tags.get(first) == "r"))
               and (tags.get(second) == "q" or second in measure)
               for first, second in zip(read, read[1:]))


def _splitting(spare_names=True, narrow=False):
    """The cut post-process of ZH-DICTIONARY: a token jieba made from its own dictionary (two characters or more, in
    its frequency table) that CC-CEDICT doesn't list — or a numeral unit the treebanks cut — becomes its pieces;
    every other token as it is. A doubled form of a CC-CEDICT word (开开心心, 干干净净 — jieba entries CC-CEDICT lacks)
    is spared: it is ZH-LEMMA's to fold, and cut first it could never be. Reads its data now, when entered."""
    jieba = _jieba()
    freq, listed, units = jieba.dt.FREQ, words(), numeral_units()
    tags = tag_table() if (spare_names or narrow) else {}

    def split(tokens):
        out = []
        for token in tokens:
            simplified = zh_script.to_simplified(token)
            if len(token) > 1 and freq.get(token) and (simplified in units or (
                    simplified not in listed and not (spare_names and tags.get(token) in NAME_TAGS)
                    and _base_of(token, own_meaning=False) is None)):
                pieces = _recut(token)
                if len(pieces) > 1 and (not narrow or _grammar(pieces)):
                    out.extend(pieces)
                    continue
            out.append(token)
        return out
    return split


@variant("zh-boundaries-gb",
         "ZH-BOUNDARIES: …… and ；/ ; no longer end a Chinese sentence (GB/T 15834-2011: 省略号 and 分号 sit inside one), "
         "．stays out, a line end still ends one — the zh set 。｡！？!?\\n, set through the frozen settings.")
def _zh_boundaries_gb():
    real = harness.frozen_logic

    def logic():
        held = real()
        held["sentence_boundaries"] = dict(held.get("sentence_boundaries") or {}, zh=GB_BOUNDARIES)
        return held
    with patched(harness, "frozen_logic", logic):
        yield


@variant("zh-hmm-off-via-simplified",
         "ZH-HMM + ZH-TRAD-ASIS as built together: jieba's HMM off, and as-is Chinese cut through Simplified with the "
         "text as written (為什麼 stays one word where HMM off alone shreds it to 為 / 什 / 麼).")
def _zh_hmm_off_via_simplified():
    with VARIANTS["zh-hmm-off"].manager(), VARIANTS["zh-asis-via-simplified"].manager():
        yield


@variant("zh-hmm-off-names-surname",
         "zh-hmm-off-via-simplified with a names guard: a run jieba's HMM keeps whole stays whole when it is 2-3 "
         "characters, no dictionary word, led by a CC-CEDICT surname, with no grammar character (by jieba's tags) and "
         "no verb last at 3 — 李明 kept, 我要 / 他来 / 别生 split, 龙仁用 -> 龙仁 + 用.")
def _zh_hmm_off_names_surname():
    jieba = _jieba()
    real, freq, family, tags = jieba.cut, jieba.dt.FREQ, surnames(), tag_table()

    def named(run):
        read = zh_script.to_simplified(run)
        return (2 <= len(read) <= 3 and read[0] in family and not freq.get(read)
                and not any(tags.get(ch) in GRAMMAR_TAGS for ch in read)
                and not (len(read) == 3 and str(tags.get(read[-1]) or "").startswith("v")))

    def cut(sentence, cut_all=False, HMM=True, use_paddle=False):
        out = []
        for token in real(sentence, cut_all=cut_all, HMM=True, use_paddle=use_paddle):
            if named(token):
                out.append(token)
            elif len(token) == 3 and named(token[:2]):
                out.append(token[:2])
                out.extend(real(token[2:], cut_all=cut_all, HMM=False, use_paddle=use_paddle))
            else:
                out.extend(real(token, cut_all=cut_all, HMM=False, use_paddle=use_paddle))
        return iter(out)
    with patched(jieba, "cut", cut), VARIANTS["zh-asis-via-simplified"].manager():
        yield


@variant("zh-cedict-split",
         "ZH-DICTIONARY (the lean): a jieba entry CC-CEDICT doesn't list splits into the words jieba then finds among "
         "CC-CEDICT's (吃了饭 -> 吃 / 了 / 饭, 一碗 -> 一 / 碗), name-tagged entries spared; a numeral unit the UD treebanks "
         "cut is cut (一个 -> 一 / 个), one they keep whole stays (一下, 一些, 一眼).")
def _zh_cedict_split():
    with _cut_through(_splitting(spare_names=True)):
        yield


@variant("zh-cedict-split-all",
         "zh-cedict-split with no entry spared for jieba's name tag — shows what the noisy tags spare (王小明, but also "
         "喝咖啡 and 考完试, tagged as names).")
def _zh_cedict_split_all():
    with _cut_through(_splitting(spare_names=False)):
        yield


@variant("zh-cedict-grammar",
         "ZH-DICTIONARY, the narrow form: only a split whose pieces hold grammar — 了 过 着 的 地 得 吧 (jieba's tags), 很, "
         "or a numeral or demonstrative + a measure word (吃了饭, 一碗, 很着急); 喝咖啡 stays whole.")
def _zh_cedict_grammar():
    with _cut_through(_splitting(spare_names=True, narrow=True)):
        yield


def _dropping(keep):
    """Patch ChineseTokenizer.tokenize_sentences so a token whose word `keep` refuses is no word: it leaves the tokens
    every tokenizer caller reads (the list, the known words, the unknowns), as analyzer.word_lemma drops a Japanese
    number."""
    real = analyzer.ChineseTokenizer.tokenize_sentences

    def tokenize_sentences(self, text):
        for s_text, tokens in real(self, text):
            yield s_text, [token for token in tokens if keep(token[0])]
    return patched(analyzer.ChineseTokenizer, "tokenize_sentences", tokenize_sentences)


@variant("zh-numerals-not-words",
         "ZH-NUMERALS: a token of numeral characters only (〇 零 一 … 十 百 千 万 亿 萬 億 两 兩) is no word — 三千五百, 二十五, 一 "
         "— unless CC-CEDICT lists it with a meaning that counts nothing (千万 'by all means', 万一, 一一, 二百五).")
def _zh_numerals_not_words():
    spared = not_counts()

    def keep(word):
        read = zh_script.to_simplified(word)
        return not (read and all(ch in NUMERALS for ch in read)) or read in spared
    with _dropping(keep):
        yield


@variant("zh-cedict-split-numerals",
         "zh-cedict-split + zh-numerals-not-words, as Z4 and Z5 land: the split frees the numeral (一碗 -> 一 / 碗) and "
         "the numeral is no word ([一] / 碗).")
def _zh_cedict_split_numerals():
    with VARIANTS["zh-cedict-split"].manager(), VARIANTS["zh-numerals-not-words"].manager():
        yield


# --- doubled forms ---------------------------------------------------------------------------------------------- #
_STOP = frozenset("the and for with sth one ones very not".split())


def _content(sense):
    return {word for word in re.findall(r"[a-z]{3,}", re.sub(r"\([^)]*\)", "", sense.lower())) if word not in _STOP}


def _own_meaning(form, base):
    """Does CC-CEDICT list `form` with meanings mostly its base lacks — fewer than half of its senses sharing a word
    with any of the base's? 马马虎虎 (careless / casual / vague / not so bad / so-so / tolerable / fair) shares one of
    seven with 马虎 — its own word; 高高兴兴 (cheerful and optimistic / in a good mood / gaily) shares two of three with
    高兴 (… in a cheerful mood) — the base's. OGO-EXCEPTIONS' test: a listed form with a meaning the bare word lacks."""
    entries = cedict()
    if form not in entries or base not in entries:
        return False
    base_words = set().union(*(_content(sense) for _pinyin, senses in entries[base] for sense in senses))
    senses = [sense for _pinyin, held in entries[form] for sense in held]
    shared = sum(1 for sense in senses if _content(sense) & base_words)
    return shared * 2 < len(senses)


def _base_of(form, own_meaning):
    """The base a doubled form counts as, or None — read on the Simplified form, sliced from `form` so it keeps the
    text's own script. AABB (开开心心 -> 开心), ABAB (休息休息 -> 休息), a run of one character (哈哈哈哈哈 -> 哈哈, the
    shortest run CC-CEDICT lists); the base must be a CC-CEDICT word. Two characters (人人, 看看) are never folded."""
    read, listed = zh_script.to_simplified(form), words()
    n = len(read)
    if n == 4 and read[0] == read[1] and read[2] == read[3] and read[0] != read[2]:
        base = read[0] + read[2]
        if base in listed and not (own_meaning and _own_meaning(read, base)):
            return form[0] + form[2]
        return None
    if n == 4 and read[:2] == read[2:] and read[0] != read[1]:
        return form[:2] if read[:2] in listed else None
    if n >= 3 and len(set(read)) == 1:
        for size in range(2, n):
            if read[:size] in listed:
                return form[:size]
    return None


def _fold(s_text, tokens, own_meaning):
    """One sentence's tokens with each doubled form as one token of its base: (base, "", the text's own stretch, base).
    Two tokens join only where they touch in the sentence: a word said twice (休息 休息), or a run of one character
    jieba cut by length (哈哈哈 哈哈)."""
    placed, cursor = [], 0
    for token in tokens:
        start = s_text.find(token[2], cursor) if token[2] else -1
        placed.append((start, start + len(token[2]) if start >= 0 else -1))
        if start >= 0:
            cursor = start + len(token[2])
    groups, i = [], 0
    while i < len(tokens):
        j, first = i + 1, tokens[i][0]
        if placed[i][0] >= 0 and first:
            if len(set(first)) == 1:
                while j < len(tokens) and placed[j][0] == placed[j - 1][1] and set(tokens[j][0]) == set(first):
                    j += 1
            elif (len(first) == 2 and j < len(tokens) and placed[j][0] == placed[i][1]
                  and tokens[j][0] == first):
                j += 1
        groups.append(tokens[i:j])
        i = j
    out = []
    for group in groups:
        base = _base_of("".join(token[0] for token in group), own_meaning)
        if base is None:
            out.extend(group)
        else:
            out.append((base, group[0][1], "".join(token[2] for token in group), base))
    return out


def _folding(own_meaning):
    real = analyzer.ChineseTokenizer.tokenize_sentences

    def tokenize_sentences(self, text):
        for s_text, tokens in real(self, text):
            yield s_text, _fold(s_text, tokens, own_meaning)
    return patched(analyzer.ChineseTokenizer, "tokenize_sentences", tokenize_sentences)


@variant("zh-redup-lemma",
         "ZH-LEMMA: a doubled form counts as its base when the base is a CC-CEDICT word — 开开心心 -> 开心, 高高兴兴 -> "
         "高兴, 休息休息 -> one 休息, 哈哈哈哈哈 -> one 哈哈; 一个个人, 人人, 看看 untouched.")
def _zh_redup_lemma():
    words()
    with _folding(own_meaning=False):
        yield


@variant("zh-redup-lemma-own-meaning",
         "zh-redup-lemma, except an AABB form CC-CEDICT lists with meanings mostly its base lacks — 马马虎虎 'so-so' "
         "stays whole beside 马虎 'careless'; 高高兴兴 still folds to 高兴.")
def _zh_redup_lemma_own_meaning():
    words()
    with _folding(own_meaning=True):
        yield


# --- script ----------------------------------------------------------------------------------------------------- #
@variant("zh-t-taiwan-variants",
         "ZH-S2T-CHI (c): under Traditional, Taiwan's standard character where OpenCC's generic form is its variant "
         "(喫 -> 吃, 爲 -> 為, 裏 -> 裡, 麪 -> 麵) — OpenCC's TWVariants.txt, fetched only with the user's OK.")
def _zh_t_taiwan_variants():
    if os.path.isfile(TW_VARIANTS):
        tw_variants()
    real = zh_script.to_traditional

    def to_traditional(text):
        return real(text).translate(tw_variants()) if text else text
    with patched(zh_script, "to_traditional", to_traditional):
        yield
