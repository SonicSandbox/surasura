"""Prototype joins for Japanese tokenizing (scope P6) — the approved compound leans as token post-processes after
the app's own affix joins (`after_join`), so every caller of analyzer.join_affixes gets them: the tokenizer, known
words, U9's see-through, the matchers, パターン, the sentence dictionary, Junban. Nothing in app/ changes.

    compound-b     the noun + noun join B (Compound_Join_Measurement.md §1, §9 item 2), gated by §12.6's H + form
    r2q-same       the っ rule R2Q (§12.3), the same word shown with と — UniDic's lemma kept
    r2q-separate   the っ rule R2Q, a separate word — its own lemma, the と-form (ざっと beside ざっ)
    names-katakana         decision 9: a katakana run JPDB 2024 and Jiten don't list is one word (トゥー + リ -> トゥーリ)
    names-katakana-pieces  the same, but a run made only of common listed words stays split (パーキング + スペース)
    names-recurrence       names layers 1 + 2: -pieces, and a run it leaves split that recurs in the library is one
                           word (リム + ハイ -> リムハイ; a frozen table of the user's library)
    names-kanji            names layer 3: a run UniDic cuts whose spelling is a listed person's name is one word
                           (一 + 護 -> 一護), guarded; names-all = 1 + 2 + 3, names-katakana-kanji = 1 + 3
    names-interjection-runs  names layer 1 as built, but a run made only of interjections stays in pieces (アッ + ハハ)
    phrases-and-titles-off   the switch "Phrases and titles as one word" off: the fringe compounds split

The rules are the adversary's simulation (debug/parsing_suite/ja_tokens/harness.py `planned`), run as the app's
own tokens: a joined word is `analyzer._joined(...)`, a JoinedWord with its parts. Their data is frozen in
data/variants/compounds.json (debug/parsing_suite/variants_data.py wrote it from debug/compound_join/): B's
candidate table, the gate's verdicts, the R flag and the library's compound counts (the last two are read by
variants_ja_consumers.py). The names variants read data/variants/katakana_headwords.json (katakana_headwords.py
beside it wrote it from docs/assets/reference_lists/); names-recurrence also data/variants/names_recurrence.json
(names_recurrence_measure.py), names-kanji data/variants/name_spellings.json (name_spellings.py).
"""
import json
import os
import re
from collections import namedtuple

from app import analyzer
from tests.parsing import harness
from tests.parsing.harness import patched
from tests.parsing.variants import after_join, variant

DATA = os.path.join(harness.DATA, "variants", "compounds.json")

Part = namedtuple("Part", "lemma reading surface free")
Compound = namedtuple("Compound", "lemma reading refused parts")
_TABLE = {}


def table():
    """{"spellings": {headword: Compound}, "library": {"lemma|reading": uses}} — read once, when a variant first
    needs it (never at import: the guard imports this file)."""
    if not _TABLE:
        if not os.path.isfile(DATA):
            raise FileNotFoundError(f"{DATA} is missing — PYTHONIOENCODING=utf-8 python "
                                    "debug/parsing_suite/variants_data.py")
        with open(DATA, encoding="utf-8") as handle:
            raw = json.load(handle)
        _TABLE["spellings"] = {word: Compound(lemma, reading, bool(refused),
                                              tuple(Part(pl, pr, ps, bool(free)) for pl, pr, ps, free in parts))
                               for word, (lemma, reading, refused, parts) in raw["spellings"].items()}
        _TABLE["library"] = raw["library"]
    return _TABLE


# --- compound B ----------------------------------------------------------------------------------------------- #
def _plain_noun(word):
    """A B part: a 名詞 that is no name and no number, and a word the dictionary knows (candidates.py `eligible`)."""
    f = word.feature
    return (not word.is_unk) and f.pos1 == "名詞" and f.pos2 not in ("固有名詞", "数詞")


def join_compounds(tokens, gate=True):
    """B on one tagger call's tokens: at each token the longest run of 3, then 2, plain nouns whose surfaces spell a
    candidate headword becomes one word — its group's lemma and the list's reading (株式会社 カブシキガイシャ) — not
    after a 数詞 (join_affixes' number guard), and not when the gate refuses the headword (a longer run refused
    still lets a shorter one join)."""
    spellings = table()["spellings"]
    out, i, n = [], 0, len(tokens)
    while i < n:
        found = None
        for k in (3, 2):
            if i + k > n:
                continue
            run = tokens[i:i + k]
            word = "".join(x.surface for x in run)
            entry = spellings.get(word)
            if entry is None or not all(_plain_noun(x) for x in run):
                continue
            if i and tokens[i - 1].feature.pos2 == "数詞":
                continue
            if gate and entry.refused:
                continue
            found = (k, word, run, entry)
            break
        if found:
            k, word, run, entry = found
            out.append(analyzer._joined(run, word, "名詞", (entry.lemma, entry.reading)))
            i += k
        else:
            out.append(tokens[i])
            i += 1
    return out


def compound_of(token):
    """The Compound a tokenizer tuple (lemma, reading, surface, orth) is — B's word: its surface a candidate
    spelling, its lemma and reading that candidate's — else None."""
    entry = table()["spellings"].get(token[2])
    if entry is None or entry.refused or (str(token[0]), token[1]) != (entry.lemma, entry.reading):
        return None
    return entry


@variant("compound-b",
         "B: noun + noun dictionary compounds join (上層部, 秘密結社, 中途半端) — the longest run of 3 then 2 plain nouns "
         "spelling a gated JPDB/Jiten headword, not after a number, refused by the §12.6 gate (H + form, median); "
         "lemma one per spelling group, the list's reading (Compound_Join_Measurement.md §1, §12.6).")
def _compound_b():
    table()
    with after_join(join_compounds):
        yield


# --- the っ rule, R2Q ------------------------------------------------------------------------------------------ #
_KANA_SOKUON = re.compile(r"^[ぁ-ゖァ-ヺー]+[っッ]$")


def _hiragana(text):
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text)


def _katakana(text):
    return "".join(chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in text)


def join_sokuon_to(tokens, separate):
    """R2Q on one tagger call's tokens: a kana sound word tagged 副詞 that ends in っ / ッ, directly followed by the
    case particle と, is one word (ドキッ + と -> ドキッと). `separate`: the と-form is a word of its own — lemma the
    sound word's spelling in hiragana + と (どきっと, as §12.3's measurement keyed it), its reading from that
    spelling; else the same word shown with と — UniDic's lemma and reading kept (どき / ドキ), the と-form only
    its spelling."""
    out, i, n = [], 0, len(tokens)
    while i < n:
        w = tokens[i]
        f = w.feature
        if (f.pos1 == "副詞" and _KANA_SOKUON.match(w.surface) and i + 1 < n
                and tokens[i + 1].surface == "と" and tokens[i + 1].feature.pos2 == "格助詞"):
            if separate:
                lemma = _hiragana(w.surface) + "と"
                entry = (lemma, _katakana(lemma))
            else:
                entry = (f.lemma or w.surface, f.lForm or f.kana or "")
            out.append(analyzer._joined(tokens[i:i + 2], (f.orthBase or w.surface) + "と", "副詞", entry))
            i += 2
            continue
        out.append(w)
        i += 1
    return out


@variant("r2q-same",
         "The っ rule, same word: a kana 副詞 ending in っ/ッ + the case particle と is one token (ドキッと, ざっと), "
         "keeping UniDic's lemma (どき, ざっ) — one row, one known status (§12.3, §12.7 decision 1).")
def _r2q_same():
    with after_join(lambda tokens: join_sokuon_to(tokens, separate=False)):
        yield


@variant("r2q-separate",
         "The っ rule, separate word: the same join, the と-form its own word — lemma どきっと / ざっと beside the "
         "bare どき / ざっ (§12.3's other build).")
def _r2q_separate():
    with after_join(lambda tokens: join_sokuon_to(tokens, separate=True)):
        yield


# --- names: a katakana run the lists don't carry (Parsing_Fixes_Plan.md decision 9) ------------------------------- #
KATAKANA_DATA = os.path.join(harness.DATA, "variants", "katakana_headwords.json")
# Katakana letters, ー and the iteration marks ヽヾ — never ・, which separates names (ローゼマイン・エーレンフェスト).
_KATAKANA = re.compile(r"^[ァ-ヺー-ヾ]+$")
_LISTED = set()


def katakana_headwords():
    """Every kana headword of JPDB 2024 and Jiten, at any rank, in katakana (ドキドキ is listed through どきどき) —
    read once, when a names variant is first entered (never at import: the guard imports this file)."""
    if not _LISTED:
        if not os.path.isfile(KATAKANA_DATA):
            raise FileNotFoundError(f"{KATAKANA_DATA} is missing — PYTHONIOENCODING=utf-8 python "
                                    "tests/parsing/data/variants/katakana_headwords.py")
        with open(KATAKANA_DATA, encoding="utf-8") as handle:
            _LISTED.update(json.load(handle)["spellings"])
    return _LISTED


def _common_word(word, listed):
    """A piece the tagger reads as a common word: a 普通名詞 or a な-word its dictionary knows, two letters or more,
    spelled as a headword of the lists (パーキング, スペース, スマート) — not a name (グリム, ナイ), a symbol (ファイ φ),
    a particle (サ), an unknown word or a single letter (リ, ヤ, コ)."""
    f = word.feature
    return (((f.pos1 == "名詞" and f.pos2 == "普通名詞") or f.pos1 == "形状詞") and not word.is_unk
            and len(word.surface) >= 2 and word.surface in listed)


def katakana_runs(tokens, least=2):
    """(start, end) of every run of `least`+ tokens written only in katakana, with no space between them (MeCab leaves
    an ASCII space out of the surfaces, in `white_space`), trimmed of the ー / ッ marks the tagger leaves at its ends
    (ダメーーッ is ダメ + marks: no run) — the runs decision 9 judges, read by the measurement too
    (data/variants/katakana_runs_measure.py)."""
    i, n = 0, len(tokens)
    while i < n:
        if not _KATAKANA.match(tokens[i].surface or ""):
            i += 1
            continue
        j = i + 1
        while j < n and _KATAKANA.match(tokens[j].surface or "") and not getattr(tokens[j], "white_space", ""):
            j += 1
        a, b = i, j
        while a < b and tokens[a].feature.pos1 == "補助記号":
            a += 1
        while b > a and tokens[b - 1].feature.pos1 == "補助記号":
            b -= 1
        if b - a >= least:
            yield a, b
        i = j


def kept_whole(run, listed, pieces=False):
    """Does decision 9 make `run` (its tokens) one word? When no JPDB 2024 / Jiten headword is spelled like it —
    and, with `pieces`, when some piece is no common word (a run of common listed words is a compound the lists
    don't carry: it stays split, as B leaves it)."""
    return ("".join(t.surface for t in run) not in listed
            and not (pieces and all(_common_word(t, listed) for t in run)))


def repeated(run):
    """Guard (a), 2026-09-28: the run is one piece repeated — ブンブン + ブンブン, ワン + ワン + ワン, アア + アッ: its
    spelling, less a final ッ / ー, is one unit written twice or more. A reduplicated sound, not a name."""
    spelling = "".join(t.surface for t in run).rstrip("ッー")
    n = len(spelling)
    return n >= 2 and any(n % k == 0 and spelling == spelling[:k] * (n // k) for k in range(1, n // 2 + 1))


def stutter(run):
    """Guard (b), 2026-09-28: a stutter — a piece cut off with ッ, then a word starting with the same sound: バッ +
    バカ, ヤッ + ヤバイ, or the ッ its own token (バ + ッ + バカ)."""
    s = [t.surface for t in run]
    for k in range(len(s) - 1):
        if s[k].endswith("ッ") and len(s[k]) > 1:
            stem = s[k][:-1]
        elif s[k] == "ッ" and k:
            stem = s[k - 1]
        else:
            continue
        if stem and s[k + 1].startswith(stem):
            return True
    return False


def join_katakana_runs(tokens, pieces=False, guards=False):
    """Decision 9 on one tagger call's tokens, after the app's own joins: a katakana run (katakana_runs) whose spelling
    no JPDB 2024 / Jiten headword has is ONE word — トゥー + リ -> トゥーリ, モーサ + ヤ -> モーサヤ, ナイ + ッ + シュー
    -> ナイッシュー — keyed as UniDic keys a word its dictionary lacks (サテラ read whole: lemma the spelling, no
    reading, unknown), so a name is one row whether the tagger cuts it or not. A listed run keeps today's tokens
    (ホストファミリー, トートバッグ); so does, with `pieces`, a run made only of common listed words (パーキング +
    スペース)."""
    listed = katakana_headwords()
    out, last = [], 0
    for a, b in katakana_runs(tokens):
        run = tokens[a:b]
        if not kept_whole(run, listed, pieces) or (guards and (repeated(run) or stutter(run))):
            continue
        spelling = "".join(t.surface for t in run)
        word = analyzer._joined(run, spelling, "名詞", (spelling, ""))
        word.is_unk = True
        out.extend(tokens[last:a])
        out.append(word)
        last = b
    out.extend(tokens[last:])
    return out


@variant("names-katakana",
         "Decision 9 as the user put it: a katakana run JPDB 2024 and Jiten don't list (any rank) stays ONE word "
         "instead of being cut into listed pieces — トゥーリ, グリムジョー, リムハイ, モーサヤ — keyed as UniDic keys an "
         "unknown word; no name list (Parsing_Fixes_Plan.md §1).")
def _names_katakana():
    katakana_headwords()
    with after_join(join_katakana_runs):
        yield


@variant("names-katakana-pieces",
         "names-katakana, except a run made only of common listed words (普通名詞 / な-words of 2+ letters the lists "
         "carry) stays split, as B leaves a compound the lists don't carry — パーキング + スペース; a run with a name, "
         "symbol, particle, unknown or one-letter piece is one word (トゥー + リ, モーサ + ヤ, グリム + ジョー).")
def _names_katakana_pieces():
    katakana_headwords()
    with after_join(lambda tokens: join_katakana_runs(tokens, pieces=True)):
        yield


@variant("names-katakana-guarded",
         "names-katakana-pieces with the two guards the user approved (2026-09-28): a run that is one piece repeated "
         "stays split (ブンブン + ブンブン, アア + アッ), and so does a stutter — a piece cut off with ッ, then a word "
         "starting with the same sound (バッ + バカ).")
def _names_katakana_guarded():
    katakana_headwords()
    with after_join(lambda tokens: join_katakana_runs(tokens, pieces=True, guards=True)):
        yield


# --- names layer 2: a leftover katakana run that recurs in the library (2026-09-27, measured, not built) --------- #
# Layer 1 (names-katakana-pieces) leaves split a run made only of common listed words — リム + ハイ, ヒラ + マン. The
# user's idea: such a run that keeps recurring in the user's own content is likely a name. The gauge measured best
# (data/variants/names_recurrence_measure.py): of the uses, as a word, of the run's least-used piece (a piece inside a
# run layer 1 keeps whole is no use of it as a word), the share inside this run — "stickiness" — with a floor of uses.
# It depends on the whole library, so the variant reads a frozen table: the runs it joins in the library as scanned
# (names_layers_scan.py), written by names_recurrence_measure.py --out.
RECURRENCE_DATA = os.path.join(harness.DATA, "variants", "names_recurrence.json")
_RECURRING = set()


def recurring_runs():
    """The katakana runs the recurrence gauge joins in the user's library (frozen) — read once, when the variant is
    first entered (never at import)."""
    if not _RECURRING:
        if not os.path.isfile(RECURRENCE_DATA):
            raise FileNotFoundError(f"{RECURRENCE_DATA} is missing — PYTHONIOENCODING=utf-8 python "
                                    "tests/parsing/data/variants/names_recurrence_measure.py --scan <scan> --out <it>")
        with open(RECURRENCE_DATA, encoding="utf-8") as handle:
            _RECURRING.update(json.load(handle)["joined"])
    return _RECURRING


def join_recurring_runs(tokens):
    """Layer 1 (names-katakana-pieces), then layer 2: a katakana run it leaves split whose spelling is in the frozen
    recurrence table is ONE word too, keyed as layer 1 keys a word (the spelling, no reading, unknown)."""
    listed, recurring = katakana_headwords(), recurring_runs()
    out, last = [], 0
    for a, b in katakana_runs(tokens):
        run = tokens[a:b]
        spelling = "".join(t.surface for t in run)
        if not (kept_whole(run, listed, pieces=True) or (spelling in recurring and spelling not in listed)):
            continue
        word = analyzer._joined(run, spelling, "名詞", (spelling, ""))
        word.is_unk = True
        out.extend(tokens[last:a])
        out.append(word)
        last = b
    out.extend(tokens[last:])
    return out


@variant("names-recurrence",
         "Names layers 1 + 2: names-katakana-pieces, and a katakana run it leaves split (only common listed pieces: "
         "リム + ハイ, ヒラ + マン) is ONE word when it recurs in the library — 3+ uses, and 80%+ of its least-used "
         "piece's uses as a word are inside the run (a frozen table of the user's library, 2026-09-27).")
def _names_recurrence():
    katakana_headwords()
    recurring_runs()
    with after_join(join_recurring_runs):
        yield


# --- names layer 3: a kanji name UniDic cuts into pieces (2026-09-27, measured, not built) ------------------------ #
# anki_miner's name wordsets (JMnedict, CC BY-SA 4.0) know names UniDic cuts: 一護 (一 + 護), 玖渚 (玖 + 渚), 赤音
# (赤 + 音), 雪緒 (雪 + 緒). A run of 2-5 tokens, 8 characters at most, with a kanji, whose whole spelling is a listed
# person's name, is ONE word — the longest such run from the left — unless a guard says the pieces are words there:
#   - the spelling is also a JPDB 2024 headword (JPDB's headwords are JMdict's: 冬月 トウゲツ, 伊吹, 一葉) within
#     `rank` (None: at any rank);
#   - a piece is grammar — a particle, an auxiliary, a verb, an adjective, a determiner, a pronoun — except a name's
#     linking letter inside it (卯ノ花); the run starts with a suffix (日前 of 三日前) or ends with a prefix;
#   - a piece is a number and none is a person's name (四年, 三番, 二十一, 栄 + 二丁目 — numbers are no words; 一 + 護
#     keeps 一護), or the run comes right after a number (１０ + 円玉: join_affixes' number guard);
#   - a person's name UniDic reads, then a suffix (マリア + 様, 司 + 氏, 小野 + 家, 寅 + さん — a person's name is no
#     base: _is_base), or a plural suffix last (お光 + 達: analyzer._NEVER_JOINED);
#   - the pieces are a surname and a given name UniDic reads as such, and the whole is no listed surname (宮崎 + 駿:
#     a full name is two words; 司 + 波 read as a surname and a given name is the surname 司波).
NAME_DATA = os.path.join(harness.DATA, "variants", "name_spellings.json")
PERSON_LISTS = 1 | 2           # surnames, given names (name_spellings.json's bits); 4 places, 8 organisations
_NAMES = {}
_HAN = re.compile(r"[々〇㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f]")
_NOT_IN_A_NAME = frozenset(("助詞", "助動詞", "動詞", "形容詞", "連体詞", "代名詞", "接続詞", "感動詞"))
_NAME_LINKS = frozenset(("ノ", "ヶ", "ケ", "之"))
KANJI_DEFAULTS = {"lists": PERSON_LISTS, "rank": None, "grammar": True, "numbers": True, "full_names": True,
                  "gate": None}


def name_spellings():
    """{"names": {spelling: list bits}, "words": {spelling: JPDB 2024 rank}} — read once, when a variant first
    needs it (never at import)."""
    if not _NAMES:
        if not os.path.isfile(NAME_DATA):
            raise FileNotFoundError(f"{NAME_DATA} is missing — PYTHONIOENCODING=utf-8 python "
                                    "tests/parsing/data/variants/name_spellings.py --lists <reference_lists>")
        with open(NAME_DATA, encoding="utf-8") as handle:
            raw = json.load(handle)
        _NAMES.update(names=raw["names"], words=raw["words"])
    return _NAMES


def kanji_name_guard(run, spelling, options):
    """Is `run` (its tokens, spelling a listed name) ONE name here? The guards above, each switchable (`options`)."""
    words = name_spellings()["words"]
    if spelling in words and (options["rank"] is None or words[spelling] <= options["rank"]):
        return False
    if options["grammar"]:
        if run[0].feature.pos1 == "接尾辞" or run[-1].feature.pos1 == "接頭辞":
            return False
        for k, t in enumerate(run):
            if t.feature.pos1 in _NOT_IN_A_NAME and not (0 < k < len(run) - 1 and t.surface in _NAME_LINKS):
                return False
    if options["numbers"] and any(t.feature.pos2 == "数詞" for t in run) \
            and not any(t.feature.pos3 == "人名" for t in run):
        return False
    if options["grammar"]:
        last = run[-1]
        if last.feature.pos1 == "接尾辞" and (all(t.feature.pos3 == "人名" for t in run[:-1])
                                            or last.surface in analyzer._NEVER_JOINED):
            return False
    if options["full_names"]:
        f = run[0].feature
        if f.pos3 == "人名" and f.pos4 == "姓" and not name_spellings()["names"].get(spelling, 0) & 1 \
                and any(t.feature.pos3 == "人名" and t.feature.pos4 == "名" for t in run[1:]):
            return False
    return True


def _number(token):
    return token.feature.pos2 == "数詞" or token.surface.isdigit()


def kanji_name_runs(tokens, options=None):
    """(start, end) of every run names layer 3 joins in one tagger call's tokens — the longest from the left.
    `options["gate"]`, a set of spellings, keeps only runs spelled as one of them (a library gate)."""
    options = dict(KANJI_DEFAULTS, **(options or {}))
    names = name_spellings()["names"]
    gate = options["gate"]
    i, n = 0, len(tokens)
    while i < n:
        best = None
        if tokens[i].feature.pos1 not in ("補助記号", "空白") \
                and not (options["numbers"] and i and _number(tokens[i - 1])):
            spelling = tokens[i].surface
            for j in range(i + 1, min(n, i + 5)):
                t = tokens[j]
                if getattr(t, "white_space", "") or t.feature.pos1 in ("補助記号", "空白"):
                    break
                spelling += t.surface
                if len(spelling) > 8:
                    break
                if names.get(spelling, 0) & options["lists"] and _HAN.search(spelling) \
                        and (gate is None or spelling in gate) and kanji_name_guard(tokens[i:j + 1], spelling, options):
                    best = j + 1
        if best:
            yield i, best
            i = best
        else:
            i += 1


def join_kanji_names(tokens, options=None):
    """Names layer 3 on one tagger call's tokens, after the app's joins: each run kanji_name_runs finds is ONE word,
    keyed as layer 1 keys a word the dictionary lacks (the spelling, no reading, unknown)."""
    out, last = [], 0
    for a, b in kanji_name_runs(tokens, options):
        run = tokens[a:b]
        spelling = "".join(t.surface for t in run)
        word = analyzer._joined(run, spelling, "名詞", (spelling, ""))
        word.is_unk = True
        out.extend(tokens[last:a])
        out.append(word)
        last = b
    out.extend(tokens[last:])
    return out


@variant("names-kanji",
         "Names layer 3: a run of 2-5 tokens UniDic cuts (一 + 護, 玖 + 渚, 赤 + 音) whose whole spelling is a person's "
         "name in anki_miner's JMnedict wordsets is ONE word — unless it is also a JPDB 2024 headword (冬月, 伊吹), a "
         "piece is grammar (上の, 流され), a number without a proper noun (四年, 三番), or UniDic reads a surname + a "
         "given name (宮崎 + 駿).")
def _names_kanji():
    name_spellings()
    with after_join(join_kanji_names):
        yield


@variant("names-all",
         "Names layers 1 + 2 + 3 together: names-recurrence (katakana), then names-kanji.")
def _names_all():
    katakana_headwords()
    recurring_runs()
    name_spellings()
    with after_join(lambda tokens: join_kanji_names(join_recurring_runs(tokens))):
        yield


@variant("names-katakana-kanji",
         "Names layers 1 + 3: names-katakana-pieces, then names-kanji (no library-wide step).")
def _names_katakana_kanji():
    katakana_headwords()
    name_spellings()
    with after_join(lambda tokens: join_kanji_names(join_katakana_runs(tokens, pieces=True))):
        yield


# --- step 3 (WP-4): the interjection guard on names layer 1, and the phrases-and-titles switch off ----------------- #
def interjections_only(run):
    """The user's answer 2 (2026-09-28): every piece of the katakana run is UniDic's 感動詞, as the tagger tags it
    (アッ + ハハ, ウワ + アア) — laughter and cries, not a name."""
    return all(t.feature.pos1 == "感動詞" for t in run)


@variant("names-interjection-runs",
         "Names layer 1 as built (app/names.py katakana_kind), plus the user's answer 2 (2026-09-28): a katakana run "
         "made only of interjections — every piece UniDic's 感動詞 (アッ + ハハ, ウワ + アア) — stays in pieces, as a "
         "repeated sound does; a run with any other piece (a name, a letter, a mark) is judged as today.")
def _names_interjection_runs():
    from app import names
    real = names.katakana_kind

    def kind(run, listed):
        found = real(run, listed)
        return "sound" if found == "name" and interjections_only(run) else found
    with patched(names, "katakana_kind", kind):
        yield


@variant("phrases-and-titles-off",
         "JT-B-FRINGE's switch off (Settings → 'Phrases and titles as one word', logic.phrases_and_titles = false): a "
         "compound flagged fringe — a phrase pattern, 元 + a noun, a title (予想通り, こと自体, 元首相, もののけ姫) — "
         "counts as its parts; every other compound stays joined. Set as settings.json would (the frozen settings the "
         "pins apply, as paren-readings-off does); it moves nothing until the compound join reads the key.")
def _phrases_and_titles_off():
    real = harness.frozen_logic
    with patched(harness, "frozen_logic", lambda: dict(real(), phrases_and_titles=False)):
        yield


# --- step 3, lane KN (2026-09-29): a katakana compound inside a run names layer 1 would keep whole ----------------- #
KATAKANA_JMDICT = os.path.join(harness.DATA, "variants", "katakana_compounds_jmdict.json")


def _name_runs(words, listed):
    """(a, b) of every katakana run names layer 1 keeps whole ("name") judged on `words` — the tokens before the
    compound joins."""
    from app import names
    return [(a, b) for a, b in names.katakana_runs(words) if names.katakana_kind(words[a:b], listed) == "name"]


def _run_before_compound(yields):
    """analyzer._join_compounds patched: a katakana-only compound that `yields(spelling)` never cuts a longer katakana
    run names layer 1 keeps whole on the tokens before the compounds (its pieces go back); every other compound joins
    as today. Only while logic.names_katakana is on."""
    from app import names
    real = analyzer._join_compounds

    def guarded(words, table, pos1s=None, at=None):
        landed = []
        joined = real(words, table, pos1s, landed)
        listed = names.katakana_headwords() if analyzer.LOGIC.get("names_katakana", True) else None
        runs = _name_runs(words, listed) if joined is not words and listed else ()
        if not runs:
            if at is not None:
                at.extend(landed)
            return joined
        out, i, compounds = [], 0, set(landed)
        for k, word in enumerate(joined):
            n = len(word.parts) if k in compounds else 1
            text = word.feature.orthBase if k in compounds else ""
            if (k in compounds and names._KATAKANA.match(text or "") and yields(text)
                    and any(a <= i and i + n <= b and (a, b) != (i, i + n) for a, b in runs)):
                out.extend(words[i:i + n])                      # layer 1 keeps the whole run: the pieces go back
            else:
                if k in compounds and at is not None:
                    at.append(len(out))
                out.append(word)
            i += n
        return out if len(out) != len(joined) else joined
    return patched(analyzer, "_join_compounds", guarded)


@variant("katakana-run-before-compound",
         "Lane G's lean (2026-09-29): a katakana-only compound join never cuts a longer katakana run that names "
         "layer 1 would keep as one word on its original pieces — layer 1's judgement on the whole run wins there "
         "(ビルデイング stays one word instead of ビルデ + イング; but フジテレビアナウンサー too, instead of フジテレビ + "
         "アナウンサー); a compound covering the whole run, one with kanji, and one inside a run layer 1 leaves in pieces "
         "(トランスジェンダー + アスリート) join as today. Only while logic.names_katakana is on.")
def _katakana_run_before_compound():
    with _run_before_compound(lambda spelling: True):
        yield


@variant("katakana-run-before-unlisted-compound",
         "katakana-run-before-compound, narrowed (lane KN, 2026-09-29): only a katakana-only compound JMdict has as no "
         "headword or reading (ビルデ, ローデ, バンデ — fragments of foreign names deep in the lists' tails) yields to "
         "layer 1's whole run; one JMdict lists (フジテレビ, クラウドファンディング, イートイン) still cuts it. Reads "
         "data/variants/katakana_compounds_jmdict.json (katakana_compounds_jmdict.py beside it).")
def _katakana_run_before_unlisted_compound():
    if not os.path.isfile(KATAKANA_JMDICT):
        raise FileNotFoundError(f"{KATAKANA_JMDICT} is missing — PYTHONIOENCODING=utf-8 python "
                                "tests/parsing/data/variants/katakana_compounds_jmdict.py")
    with open(KATAKANA_JMDICT, encoding="utf-8") as handle:
        unlisted = frozenset(json.load(handle)["unlisted"])
    with _run_before_compound(unlisted.__contains__):
        yield


# --- names layer 4: a work's own kanji terms (NAMES-WORK-TERMS, 2026-09-29; staged in work_terms/spec_staging) ---- #
# A run of one-kanji tokens the compound build and layers 1-3 leave in pieces (斬 + 魄 + 刀) is one word when the
# library keeps using it as one. It depends on the whole library, so the pre-build variant reads a frozen table: the
# trial's 67 (debug/parsing_fixes_run/work_terms/proposed.json — stickiness >= 0.7, 3+ uses, the three guards).
WORK_TERMS_DATA = os.path.join(harness.DATA, "variants", "work_terms.json")
_TERMS = set()


def work_terms():
    """The trial's terms (frozen) — read once, when the variant is first entered."""
    if not _TERMS:
        if not os.path.isfile(WORK_TERMS_DATA):
            raise FileNotFoundError(f"{WORK_TERMS_DATA} is missing — python debug/parsing_fixes_run/work_terms/"
                                    "spec_staging/variant_draft.py")
        with open(WORK_TERMS_DATA, encoding="utf-8") as handle:
            _TERMS.update(json.load(handle)["joined"])
    return _TERMS


def _one_kanji(word, first):
    """A token read as exactly one kanji, no joined word — after the first of a run, with no space before it."""
    text = word.feature.orth or word.surface
    return (len(text) == 1 and _HAN.match(text) is not None and not isinstance(word, analyzer.JoinedWord)
            and (first or not getattr(word, "white_space", "")))


def join_work_terms(tokens):
    """Every maximal run of one-kanji tokens left after the app's joins (the frozen names tables applied) whose
    spelling is a frozen term, made one word as layer 3 makes a name (names.one_word)."""
    from app import names
    terms = work_terms()
    out, i, n = [], 0, len(tokens)
    while i < n:
        if not _one_kanji(tokens[i], True):
            out.append(tokens[i])
            i += 1
            continue
        j = i + 1
        while j < n and _one_kanji(tokens[j], False):
            j += 1
        run = tokens[i:j]
        spelling = "".join(t.feature.orth or t.surface for t in run)
        if j - i >= 2 and spelling in terms:
            out.append(names.one_word(run))
        else:
            out.extend(run)
        i = j
    return out


@variant("names-work-terms",
         "Names layer 4 before the build: a run of one-kanji tokens the compound build and layers 1-3 leave in pieces "
         "(斬 + 魄 + 刀, 霊 + 圧) is ONE word when the library keeps using it as one — stickiness >= 0.7, 3+ uses, no "
         "grammar piece or suffix last, not from auto captions, no JMdict word (the trial's 67, frozen, 2026-09-29).")
def _names_work_terms():
    work_terms()
    real = analyzer.join_affixes

    def joined(words, joins=None, library=True, **kw):     # **kw: join_affixes also takes compounds=
        out = real(words, joins, library, **kw)
        return join_work_terms(out) if library else out
    with patched(analyzer, "join_affixes", joined):
        yield


@variant("names-work-terms-off",
         "The switch \"Kanji terms your library repeats as one word\" off (logic.names_work_terms = False in the frozen "
         "settings the pins apply, as phrases-and-titles-off does): the terms split, nothing else moves.")
def _names_work_terms_off():
    real = harness.frozen_logic
    with patched(harness, "frozen_logic", lambda: dict(real(), names_work_terms=False)):
        yield
