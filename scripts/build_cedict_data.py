"""Distil CC-CEDICT into app/cedict_data.py (DEV ONLY — never shipped).

Why this exists
---------------
jieba, the Chinese cutter, works from a dictionary of its own that holds phrases no dictionary lists as words — 吃了饭
'ate (a meal)', 一碗 'a bowl (of)', 电影吧 'the film, then', 很快 'very fast' — and counts each as a word: the words inside
(吃饭, 碗, 电影) lose those uses, and the list fills with phrases. What a word IS is judged from Chinese as a whole —
here CC-CEDICT, the community Chinese–English dictionary MDBG publishes, and the Universal Dependencies Chinese
treebanks — never from the user's own content. So the tables are built HERE, once, from those sources and jieba's own
dictionary, and the app ships only the result:

  SPLITS   jieba's dictionary entries that are read as their words, with the length of each word: an entry CC-CEDICT
           doesn't list is cut the way jieba's own route cuts it through the words both dictionaries hold, when those
           words hold grammar where grammar stands —
             an aspect marker (了 着 过) after a verb or an adjective, or inside an entry jieba tags a verb: 吃了饭,
               看过, 想着, 结了婚;
             的 after a word: 漂亮的, 我的;
             the adverb-making 地 after an adjective, an adverb or a doubled word of two characters or more:
               认真地, 慢慢地 — never after a verb, a noun or one character (用地 'land use', 满地, 地安门 stay whole);
             the complement 得 between a verb or an adjective (or inside a verb entry) and its complement: 跑得快,
               好得多 — never after a noun, never last (种瓜得瓜, 录得 'record (a figure)', 募得 stay whole);
             a sentence-final particle after a verb, an adjective, a noun or a pronoun: 电影吧, 走吧 — never after an
               adverb (甚么 'what' stays whole);
             the degree adverb 很 before a word: 很多, 很着急;
             a number, or a one-character pronoun (这, 那, 每), before a measure word: 一碗, 这次, 两杯.
           A name jieba tags as one (王小明), and a doubled word whose single form CC-CEDICT lists (开开心心, 休息休息),
           stay whole. A number written in several pieces is one piece (一万二千 + 名, never 一 + 万一 + 千 + 名).
           Where CC-CEDICT lists a number + a measure word, the dictionary still wins — unless it is a count: one the
           treebanks cut after the number in most of their uses, at least twice (一个, 一次, 一种, 一家 are cut; 一下,
           一些, 一样, 一起 are kept whole by the treebanks, the months, 一方面, 两岸 have no measure word).
  NOT_COUNTS  the words made only of numerals (GB/T 15835's, with 两) that are no number: a common word CC-CEDICT lists
           (its pinyin in lower case — 十一 'National Day' is a name, 十一 'eleven' a number) with a sense that is
           neither a number (twelve, 12, ten million, 5-1) nor a quantity (countless, a few, a hundred or so) — 千万
           'by all means', 万一 'just in case', 一一 'one by one', 二百五 'idiot'. Every other numbers-only token is
           a number, never a word (the app: analyzer.chinese_word).
  FOLDS    jieba's doubled forms (AABB) that are their word said doubled — 开开心心 is 开心, 高高兴兴 is 高兴: the form's
           first and third characters make a word CC-CEDICT lists, and the form has no meaning of its own — fewer than
           half of CC-CEDICT's senses for it share no word, by stem, with the base's (马马虎虎 'so-so', 形形色色 'all
           kinds of' stay whole; 方方面面 'all aspects' is 方面 'aspect'). A form made only of numerals is a number's
           (三三两两: NOT_COUNTS decides).
  SOUNDS   the sounds and laughs a run of one character is read as: for each character CC-CEDICT lists said over, its
           shortest such word, when that word has a sound or a laugh among its senses (哈哈, 呵呵, 汪汪 — never 好好 'well',
           太太 'wife', 爱爱 'make love'): 哈哈哈哈哈 is one 哈哈.

  SURNAMES, GRAMMAR_CHARS, VERB_CHARS  what the guard on jieba's guessed names reads (app/analyzer.py chinese_cut):
           the single characters CC-CEDICT gives a surname sense (李 'surname Li', 王, 龙), and those jieba's tag table
           files as grammar (prepositions, conjunctions, particles, modal particles, interjections, onomatopoeia,
           pronouns, adverbs, numerals, measure words, localisers) or as verbs.

Inputs live in docs/assets/zh_gold/ (gitignored; fetched by fetch_gold.py, each checked against FETCHED.json's
sha256): cedict_1_0_ts_utf-8_mdbg.zip and ud/*.conllu (GSDSimp, HK, CFL). jieba's dictionary and its tag table are
read from the installed jieba (0.42.1 when this was written): an entry of another jieba version that the table
doesn't name is simply cut as jieba cuts it. Output is committed and ships: app/cedict_data.py. Rebuilding it
changes what the token store caches: bump SCHEMA_VERSION (app/token_index.py) and ENGINE_REVISION
(app/analyzer.py) with it, and the Chinese パターン builder's BUILDER_VERSION (modules/junban/patterns_zh.py).

Usage:  python scripts/build_cedict_data.py
"""

import hashlib
import json
import math
import os
import re
import sys
import zipfile
from collections import Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GOLD_DIR = os.path.join(ROOT, "docs", "assets", "zh_gold")
CEDICT = "cedict_1_0_ts_utf-8_mdbg.zip"
OUTPUT = os.path.join(ROOT, "app", "cedict_data.py")
_ENTRY = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")
_DATE = re.compile(r"^#! date=(\S+)", re.M)

# The numerals of Chinese running text (GB/T 15835-2011, 出版物上数字用法: 〇 一 … 九 十 百 千 万 亿, with 零 and the
# Traditional 萬 億) and 两 / 兩, the numeral a count takes (两个). Unicode's numeric property is no test: it numbers the
# financial forms (拾 10, 陆 6, 参 3 — also the words 'pick up', 'land', 'take part') and gives 两 no value.
NUMERALS = frozenset("〇零一二三四五六七八九十百千万亿萬億两兩")
# jieba's tags for names: people, places, organisations, other proper nouns — an entry so tagged stays whole.
NAME_TAGS = frozenset(("nr", "nrfg", "nrt", "ns", "nt", "nz"))
ASPECT_TAGS = frozenset(("ul", "uz", "ug", "uguo"))      # 了 着 过
DE_TAG, DI_TAG, DE2_TAG, MODAL_TAG = "uj", "uv", "ud", "y"   # 的, 地, 得, sentence-final particles
# jieba's tags for grammar: prepositions, conjunctions, particles, modal particles, interjections, onomatopoeia,
# pronouns, adverbs, numerals, measure words, localisers — a character tagged so is no piece of a name.
GRAMMAR_TAGS = frozenset(("p", "c", "u", "uj", "ul", "uz", "ug", "uguo", "uv", "ud", "y", "e", "o", "r", "d", "m", "q",
                          "f"))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_fetched(gold_dir, name):
    """Stop when FETCHED.json records `name` with another sha256 than the file has (a changed download)."""
    try:
        with open(os.path.join(gold_dir, "FETCHED.json"), encoding="utf-8") as handle:
            fetched = {item["file"]: item for item in json.load(handle)}
    except (OSError, ValueError):
        return
    want = fetched.get(name, {}).get("sha256")
    if want and _sha256(os.path.join(gold_dir, name)) != want:
        sys.exit(f"{name} differs from the download FETCHED.json records — fetch it again (fetch_gold.py)")


def parse_cedict(text):
    """CC-CEDICT's lines -> ({Simplified headword: [(Traditional, pinyin, [senses])]}, its date)."""
    entries = {}
    for line in text.splitlines():
        found = None if line.startswith("#") else _ENTRY.match(line)
        if found:
            traditional, simplified, pinyin, senses = found.groups()
            entries.setdefault(simplified, []).append(
                (traditional, pinyin, [sense.strip() for sense in senses.split("/") if sense.strip()]))
    dated = _DATE.search(text)
    return entries, (dated.group(1)[:10] if dated else "")


def load_cedict(gold_dir=GOLD_DIR):
    check_fetched(gold_dir, CEDICT)
    with zipfile.ZipFile(os.path.join(gold_dir, CEDICT)) as archive:
        return parse_cedict(archive.read("cedict_ts.u8").decode("utf-8"))


def classifier_chars(entries):
    """The single characters CC-CEDICT gives a measure-word sense — "classifier for books …", or "(classifier used
    before a noun that has no specific classifier)" as it writes 个."""
    return frozenset(word for word, held in entries.items() if len(word) == 1 and any(
        sense.lstrip("(").startswith("classifier") for _t, _p, senses in held for sense in senses))


def ud_number_cuts(ud_dir, to_simplified):
    """(whole, cut) Counters over the UD Chinese treebanks: how often a word is one token, and how often it is a
    number token followed by the rest of it (一 + 个 counts 一个 as cut). The Traditional treebank (HK) is read as
    Simplified."""
    whole, cut = Counter(), Counter()

    def tally(forms):
        whole.update(forms)
        for first, second in zip(forms, forms[1:]):
            if first and all(ch in NUMERALS for ch in first):
                cut[first + second] += 1
    for name in sorted(os.listdir(ud_dir)):
        if not name.endswith(".conllu"):
            continue
        check_fetched(os.path.dirname(ud_dir), "ud/" + name)
        forms = []
        with open(os.path.join(ud_dir, name), encoding="utf-8") as handle:
            for line in handle:
                columns = line.rstrip("\n").split("\t")
                if len(columns) > 1 and columns[0].isdigit():
                    forms.append(to_simplified(columns[1]))
                elif not line.strip():
                    tally(forms)
                    forms = []
        tally(forms)
    return whole, cut


def is_number(text):
    return bool(text) and all(ch in NUMERALS for ch in text)


def numeral_units(entries, whole, cut, tags, measure):
    """The counts CC-CEDICT lists: a number + a measure word (jieba tags it one, or CC-CEDICT gives it a classifier
    sense) that the treebanks cut after the number in most of their uses, at least twice. -> {word: number length}"""
    units = {}
    for word in entries:
        k = 0
        while k < len(word) and word[k] in NUMERALS:
            k += 1
        rest = word[k:]
        if not k or not rest or (tags.get(rest) != "q" and rest not in measure):
            continue
        if cut[word] >= 2 and cut[word] > whole[word]:
            units[word] = k
    return units


def recut(token, freq, logtotal, listed):
    """jieba's own route through `token` (its frequencies, its sum of logs) over the words jieba's dictionary and
    CC-CEDICT both hold and single characters — never the whole token. -> the pieces."""
    n = len(token)
    route = [None] * n + [(0.0, n)]
    for i in range(n - 1, -1, -1):
        route[i] = max((math.log(freq.get(token[i:j]) or 1) - logtotal + route[j][0], j)
                       for j in range(i + 1, n + 1)
                       if j == i + 1 or ((i, j) != (0, n) and token[i:j] in listed and freq.get(token[i:j])))
    pieces, i = [], 0
    while i < n:
        j = route[i][1]
        pieces.append(token[i:j])
        i = j
    return pieces


def join_numbers(pieces):
    """A number written in several pieces is one piece: 一 + 万 + 二 + 千 + 名 -> 一万二千 + 名 (and never 一 + 万一 + 千)."""
    out = []
    for piece in pieces:
        if out and is_number(piece) and is_number(out[-1]):
            out[-1] += piece
        else:
            out.append(piece)
    return out


_NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                 "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundreds "
                 "hundred thousands thousand millions million billions billion trillions trillion and an a or of the")
_COUNT = re.compile(r"^(?:[\d.,%+/:;\s\-–]|(?:" + "|".join(_NUMBER_WORDS.split()) + r")\b|giga-|mega-)+$", re.I)
_QUANTITY = re.compile(r"\b(?:numbers?|numerous|innumerable|countless|many|myriads?|multitud\w*|several|few|lots?|"
                       r"plenty|little|bit|some|untold|dozens?|enormous quantity|or so)\b", re.I)


def counts_nothing(sense):
    """Is a CC-CEDICT sense no count — neither a number (twelve, 12, ten million, 5-1) nor a quantity (countless, a
    few, a hundred or so)? 'one by one', 'by all means', 'just in case', 'idiot' count nothing."""
    sense = re.sub(r"\([^)]*\)", "", sense).strip(" ;,")
    return bool(sense) and not _COUNT.match(sense) and not _QUANTITY.search(sense)


def not_counts(entries):
    """NOT_COUNTS (this module's docstring): the numbers-only headwords that are a common word counting nothing."""
    return frozenset(word for word, held in entries.items() if len(word) > 1 and is_number(word)
                     and any(pinyin[:1].islower() and any(counts_nothing(sense) for sense in senses)
                             for _t, pinyin, senses in held))


_STOP = frozenset("the and for with sth one ones very not".split())
_SUFFIXES = (("iedly", "y"), ("ingly", ""), ("iness", "y"), ("edly", ""), ("ness", ""), ("ment", ""), ("ies", "y"),
             ("ied", "y"), ("ily", "y"), ("ing", ""), ("ed", ""), ("ly", ""), ("es", ""), ("s", ""))


def stem(word):
    """An English gloss word without its endings (two at most), so a meaning matches however it is worded: aspects ~
    aspect, hurriedly ~ hurried, happiness ~ happy, families ~ family, movements ~ moving ~ move."""
    for _ in range(2):
        for suffix, keep in _SUFFIXES:
            if (word.endswith(suffix) and len(word) - len(suffix) >= 3
                    and not (suffix in ("s", "es") and word.endswith("ss"))):    # class, glass
                word = word[:-len(suffix)] + keep
                break
        else:
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def gloss_words(sense):
    """A sense's words, by stem — no bracketed note, nothing under three letters, no 'the', 'sth' or 'one'."""
    return {stem(word) for word in re.findall(r"[a-z]{3,}", re.sub(r"\([^)]*\)", "", sense.lower()))
            if word not in _STOP}


def own_meaning(form, base, entries):
    """Does CC-CEDICT list the doubled `form` with meanings mostly its base lacks — fewer than half of its senses
    sharing a word (by stem) with any of the base's? 马马虎虎 'careless / casual / vague / not so bad / so-so /
    tolerable / fair' shares one of seven with 马虎 'careless / sloppy': a word of its own. 方方面面 'all aspects'
    shares 'aspect' with 方面: 方面 said doubled."""
    if form not in entries or base not in entries:
        return False
    base_words = set().union(*(gloss_words(sense) for _t, _p, senses in entries[base] for sense in senses))
    senses = [sense for _t, _p, held in entries[form] for sense in held]
    return sum(1 for sense in senses if gloss_words(sense) & base_words) * 2 < len(senses)


def fold_table(entries, freq, to_simplified):
    """(FOLDS, the forms kept whole for a meaning of their own) — FOLDS as this module's docstring says, over jieba's
    entries as the cut meets them (in Simplified)."""
    listed = frozenset(word for word in entries if len(word) > 1)
    folds, own = set(), set()
    for word, count in freq.items():
        if (not count or len(word) != 4 or word[0] != word[1] or word[2] != word[3] or word[0] == word[2]
                or is_number(word) or word[0] + word[2] not in listed or to_simplified(word) != word):
            continue
        (own if own_meaning(word, word[0] + word[2], entries) else folds).add(word)
    return frozenset(folds), frozenset(own)


_SOUND = re.compile(r"onom|\blaugh|giggl|chuckl|titter|snicker|guffaw|hee hee|boo hoo|\bsound (?:of|made)\b|"
                    r"\b\w+ing sound\b", re.I)


def sound_runs(entries):
    """SOUNDS (this module's docstring): each character's shortest word of itself said over, when it is a sound."""
    shortest = {}
    for word in entries:
        if len(word) > 1 and word == word[0] * len(word):
            known = shortest.get(word[0])
            if known is None or len(word) < len(known):
                shortest[word[0]] = word
    return frozenset(word for word in shortest.values()
                     if any(_SOUND.search(sense) for _t, _p, senses in entries[word] for sense in senses))


def surnames(entries):
    """SURNAMES: the single characters CC-CEDICT gives a surname sense (李 'surname Li', 王, 龙)."""
    return frozenset(word for word, held in entries.items() if len(word) == 1 and any(
        sense.startswith("surname ") for _t, _p, senses in held for sense in senses))


def name_characters(tags):
    """(GRAMMAR_CHARS, VERB_CHARS): the single characters jieba's tag table files as grammar (GRAMMAR_TAGS) and as
    verbs (a tag starting v)."""
    return (frozenset(word for word, tag in tags.items() if len(word) == 1 and tag in GRAMMAR_TAGS),
            frozenset(word for word, tag in tags.items() if len(word) == 1 and str(tag).startswith("v")))


def _verbal(tag):
    return bool(tag) and tag[0] in "va"


def _doubled(word):
    return len(word) >= 2 and (len(set(word)) == 1 or (len(word) == 4 and word[0] == word[1] and word[2] == word[3]))


def grammar(pieces, tags, measure, token_tag=None):
    """Do `pieces` hold grammar where grammar stands (the list in this module's docstring)? `token_tag` is jieba's tag
    for the whole entry: an aspect marker or a complement 得 inside an entry jieba tags as a verb follows its verb,
    however the verb's own character is tagged alone (结了婚 is a verb; 结 alone is tagged a noun, 'knot')."""
    verb_entry = bool(token_tag) and token_tag[0] == "v"
    for i, piece in enumerate(pieces):
        tag = tags.get(piece)
        prev = pieces[i - 1] if i else None
        prev_tag = tags.get(prev) if prev else None
        last = i == len(pieces) - 1
        if piece == "很" and not last:
            return True
        if not prev:
            continue
        if tag in ASPECT_TAGS and (_verbal(prev_tag) or verb_entry):
            return True
        if tag == DE_TAG:
            return True
        if tag == DI_TAG and (_doubled(prev) or (len(prev) >= 2 and bool(prev_tag) and prev_tag[0] in "adz")):
            return True
        if tag == DE2_TAG and not last and (_verbal(prev_tag) or verb_entry):
            return True
        if tag == MODAL_TAG and last and bool(prev_tag) and prev_tag[0] in "vanr":
            return True
    return any((is_number(first) or (len(first) == 1 and tags.get(first) == "r"))
               and (tags.get(second) == "q" or second in measure)
               for first, second in zip(pieces, pieces[1:]))


def doubled_form(word, listed):
    """Is `word` a doubled form of a word CC-CEDICT lists — AABB (开开心心: 开心), ABAB (休息休息), a run of one character —
    left whole here for the fold (app/analyzer.py chinese_base) to read as its word?"""
    n = len(word)
    if n == 4 and word[0] == word[1] and word[2] == word[3] and word[0] != word[2]:
        return word[0] + word[2] in listed
    if n == 4 and word[:2] == word[2:] and word[0] != word[1]:
        return word[:2] in listed
    return n >= 3 and len(set(word)) == 1


def split_table(entries, units, freq, total, tags, measure):
    """{jieba entry: the lengths of its words} — the rule of SPLITS (this module's docstring)."""
    listed = frozenset(word for word in entries if len(word) > 1)
    logtotal = math.log(total)
    table = {}
    for token, count in freq.items():
        if not count or len(token) < 2:
            continue
        if token in units:
            k = units[token]
            table[token] = (k, len(token) - k)
            continue
        if token in listed or tags.get(token) in NAME_TAGS or doubled_form(token, listed):
            continue
        pieces = join_numbers(recut(token, freq, logtotal, listed))
        if len(pieces) > 1 and grammar(pieces, tags, measure, tags.get(token)):
            table[token] = tuple(len(piece) for piece in pieces)
    return table


def jieba_tables():
    """jieba's dictionary (word -> frequency), its total, and its tag table (posseg's word_tag_tab)."""
    import jieba
    import jieba.posseg as posseg
    jieba.setLogLevel(60)
    jieba.initialize()
    import importlib.metadata as metadata
    try:
        version = metadata.version("jieba")
    except Exception:
        version = getattr(jieba, "__version__", "?")
    return jieba.dt.FREQ, jieba.dt.total, posseg.dt.word_tag_tab, version


def _chars(chars, width=60):
    """A set of characters as a string literal's lines, in code-point order, `width` to a line."""
    text = "".join(sorted(chars))
    return "\n".join(f'    "{text[at:at + width]}"' for at in range(0, len(text), width)) or '    ""'


def _hex(lines):
    import zlib
    return zlib.compress("\n".join(lines).encode("utf-8"), 9).hex()


_REVISION_LINE = re.compile(r'^(Revision: |REVISION = ").*$', re.M)


def _write(path, text):
    """Write `text` to `path` — unless the file there differs only in its Revision lines (a rebuild from unchanged
    inputs then moves nothing). -> whether it was written."""
    try:
        with open(path, encoding="utf-8") as handle:
            old = handle.read()
    except OSError:
        old = None
    if old is not None and _REVISION_LINE.sub("", old) == _REVISION_LINE.sub("", text):
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return True


def build(gold_dir=GOLD_DIR, jieba_data=None):
    """Every table, from the sources -> a dict of tables and counts (main writes them; tests read them)."""
    from app import zh_script
    entries, cedict_date = load_cedict(gold_dir)
    freq, total, tags, jieba_version = jieba_data or jieba_tables()
    measure = classifier_chars(entries)
    whole, cut = ud_number_cuts(os.path.join(gold_dir, "ud"), zh_script.to_simplified)
    units = numeral_units(entries, whole, cut, tags, measure)
    splits = split_table(entries, units, freq, total, tags, measure)
    folds, own = fold_table(entries, freq, zh_script.to_simplified)
    grammar_chars, verb_chars = name_characters(tags)
    return {"entries": entries, "cedict_date": cedict_date, "jieba_version": jieba_version, "measure": measure,
            "units": units, "splits": splits, "not_counts": not_counts(entries), "folds": folds, "own_meaning": own,
            "sounds": sound_runs(entries), "surnames": surnames(entries), "grammar_chars": grammar_chars,
            "verb_chars": verb_chars}


def main(gold_dir=GOLD_DIR, output=OUTPUT, jieba_data=None):
    print(f"CC-CEDICT and the UD Chinese treebanks from {gold_dir}")
    tables = build(gold_dir, jieba_data)
    splits = tables["splits"]
    lines = [f"{token}\t{','.join(str(n) for n in cuts)}" for token, cuts in sorted(splits.items())]
    revision = date.today().isoformat()
    text = TEMPLATE.format(revision=revision, cedict_date=tables["cedict_date"], jieba=tables["jieba_version"],
                           n_splits=len(splits), n_units=len(tables["units"]), splits_hex=_hex(lines),
                           n_not_counts=len(tables["not_counts"]),
                           not_counts=", ".join(sorted(tables["not_counts"])),
                           not_counts_tuple="".join(f'"{word}", ' for word in sorted(tables["not_counts"])),
                           n_folds=len(tables["folds"]), folds_hex=_hex(sorted(tables["folds"])),
                           n_own=len(tables["own_meaning"]), own=", ".join(sorted(tables["own_meaning"])),
                           n_sounds=len(tables["sounds"]), sounds=", ".join(sorted(tables["sounds"])),
                           sounds_tuple="".join(f'"{word}", ' for word in sorted(tables["sounds"])),
                           n_surnames=len(tables["surnames"]), surnames=_chars(tables["surnames"]),
                           grammar_chars=_chars(tables["grammar_chars"]), verb_chars=_chars(tables["verb_chars"]))
    wrote = _write(output, text)
    print(f"{'Wrote' if wrote else 'Kept (unchanged)'} {output} ({os.path.getsize(output) / 1024:,.0f} KB): "
          f"{len(splits):,} jieba entries read as their words")
    print(f"The counts CC-CEDICT lists that are cut ({len(tables['units'])}): "
          + " ".join(sorted(tables["units"])))
    print(f"The numbers that are words ({len(tables['not_counts'])}): " + " ".join(sorted(tables["not_counts"])))
    print(f"{len(tables['folds']):,} doubled forms read as their word; kept whole for a meaning of their own "
          f"({len(tables['own_meaning'])}): " + " ".join(sorted(tables["own_meaning"])))
    print(f"The sounds a run is read as ({len(tables['sounds'])}): " + " ".join(sorted(tables["sounds"])))


TEMPLATE = '''"""Chinese words distilled from CC-CEDICT — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_cedict_data.py

Revision: {revision}   CC-CEDICT: {cedict_date}   jieba: {jieba}
  SPLITS  {n_splits:,} entries of jieba's dictionary that are read as their words, with each word's length: an entry
          CC-CEDICT doesn't list whose words hold grammar where grammar stands (吃了饭 is 吃 + 了 + 饭, 一碗 is 一 + 碗,
          电影吧 is 电影 + 吧), and the {n_units} counts CC-CEDICT lists that the Universal Dependencies Chinese
          treebanks cut after the number (一个 is 一 + 个). Names and doubled words stay whole.
  NOT_COUNTS  the {n_not_counts} words made only of numerals that are no number (a common CC-CEDICT word with a sense
          that counts nothing): {not_counts}. Every other numbers-only token is a number, never a word.
  FOLDS   the {n_folds:,} doubled forms of jieba's dictionary read as their word (开开心心 is 开心, 高高兴兴 is 高兴): the
          form's first and third characters make a word CC-CEDICT lists, and the form has no meaning of its own. The
          {n_own} kept whole for one: {own}.
  SOUNDS  the {n_sounds} sounds and laughs a longer run of their character is read as (哈哈哈哈哈 is 哈哈): {sounds}.
  SURNAMES, GRAMMAR_CHARS, VERB_CHARS  what the guard on jieba's guessed names reads: the {n_surnames} characters
          CC-CEDICT gives a surname sense, and those jieba's tag table files as grammar or as verbs.

Derived from CC-CEDICT, the community Chinese–English dictionary published by MDBG (https://cc-cedict.org/wiki/),
licensed under the Creative Commons Attribution-ShareAlike 4.0 International License
(https://creativecommons.org/licenses/by-sa/4.0/); the counts read from the Universal Dependencies Chinese treebanks
GSDSimp, HK and CFL (CC BY-SA 4.0); the cut itself is jieba's (MIT). Changes: only headword spellings kept, filtered
and combined as scripts/build_cedict_data.py says. This table is shared under the same licence, CC BY-SA 4.0.

Stored compressed (zlib, as hexadecimal text) and decoded lazily: only a Chinese cut reads it.
"""

import zlib

REVISION = "{revision}"

_SPLITS = (
    "{splits_hex}"
)


def _lines(text):
    return zlib.decompress(bytes.fromhex(text)).decode("utf-8").split("\\n")


_FOLDS = (
    "{folds_hex}"
)

NOT_COUNTS = ({not_counts_tuple})

SOUNDS = ({sounds_tuple})

SURNAMES = (
{surnames}
)

GRAMMAR_CHARS = (
{grammar_chars}
)

VERB_CHARS = (
{verb_chars}
)


def splits():
    """{{jieba entry: the lengths of its words, in order}}."""
    table = {{}}
    for line in _lines(_SPLITS):
        token, _tab, cuts = line.partition("\\t")
        if token:
            table[token] = tuple(int(n) for n in cuts.split(","))
    return table


def not_counts():
    """The words made only of numerals that are no number (frozen: small, written out above)."""
    return frozenset(NOT_COUNTS)


def folds():
    """The doubled forms (AABB) read as their word — the form's first and third characters."""
    return frozenset(line for line in _lines(_FOLDS) if line)


def sounds():
    """The sounds and laughs a longer run of their character is read as (frozen: small, written out above)."""
    return frozenset(SOUNDS)


def surnames():
    """The characters CC-CEDICT gives a surname sense."""
    return frozenset(SURNAMES)


def grammar_chars():
    """The characters jieba's tag table files as grammar."""
    return frozenset(GRAMMAR_CHARS)


def verb_chars():
    """The characters jieba's tag table files as verbs."""
    return frozenset(VERB_CHARS)
'''

if __name__ == "__main__":
    main()
