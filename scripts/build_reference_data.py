"""Distil the reference corpora into app/reference_data.py (DEV ONLY — never shipped).

Why this exists
---------------
Deciding whether a word is one you'll READ or one you'll HEAR is a question about Japanese,
not about any particular user: it depends only on the reference corpora and the tokenizer, both
of which are fixed when we build. So all of that work happens HERE, once, and the app ships a
small lookup table. The user's machine never loads a corpus, never tokenizes a word list, and
pays nothing at Generate time beyond a dict lookup.

Three tables come out of it:

  AFFIX_JOINS  written form -> [lemma, reading]: the dictionary words that UniDic cuts into a
               prefix + a word or a word + suffixes (新幹線 = 新 + 幹線, 可能性 = 可能 + 性), which
               `analyzer.join_affixes` joins back (Patterns_Quality_Spec.md Part A). Every
               JPDB 2024 / Jiten headword — in both, or in one's top 60,000 — whose own tokens that
               join reproduces, with the list's reading (日本人 ニホンジン — unidic-lite reads the
               suffix 人 as ニン), and the spellings of one word under one lemma (おすすめ -> お勧め).
               A word with the polite お / ご / 御 joins only when that is a usual form of it (the
               user, U1: OGO_SHARE, OGO_TALK_SHARE). Built first: the other two tables are keyed
               through the join.

  ALIASES      lemma -> the spelling frequency lists actually use.
               Unidic hands the analyzer orthographic lemmas (為る, 矢張り, 其れ); every
               frequency list on earth stores する, やっぱり, それ. Without this bridge the
               most common verb in the language reports as "Outside" in the Tier column.

  SPOKEN_RANK  lemma -> its rank in spoken Japanese (0 = rarer than the corpora can see).
               Only words that are real WRITTEN vocabulary get an entry — see the filters
               below. app/modality.py turns the rank into "hours of listening between
               encounters" and compares that to the user's threshold.

Inputs live in docs/assets/reference_lists/ — gitignored, and deliberately NOT under scripts/,
which packaging/Surasura.spec bundles wholesale: left there they would add ~78 MB of dead
corpora to every release. The お / ご shares are counted over the text of the shared パターン
set, staged in docs/assets/corpora/_text/ (also gitignored; prepare.py makes it). Output
(app/reference_data.py) is committed and ships.

Usage:  python scripts/build_reference_data.py
"""

import base64
import json
import os
import re
import sys
import zlib
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LISTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "docs", "assets", "reference_lists")
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "app", "reference_data.py")

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
CORPUS_TEXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "docs", "assets", "corpora", "_text")
OGO_SOURCES = {"realpersonachat": None, "aozora": 23_000_000, "wikipedia": 25_000_000, "leipzig_news": None}
# The set is mostly written text, where お is rarer than in speech: お祭り is 14% of its uses there, 76% in
# the set's conversation. So a word people say with the お most of the time joins too — at least
# OGO_TALK_SHARE of its uses in OGO_TALK, with OGO_MIN_USES there (the user, checkpoint A: "ideally お祭り
# is able to be joined"). Half, not 30%: persona chat is polite, so お話 (34%) and お仕事 (30%) stay split.
OGO_TALK = "realpersonachat"
OGO_TALK_SHARE = 0.50
OGO_REPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug", "ogo_joins.md")


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
                reading = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in word)
            readings[word] = reading
        ranks.append(rank)
    out = {}
    for word, reading in readings.items():
        best = min(r[word] for r in ranks if word in r)
        if best <= JOIN_ONE_LIST_RANK or all(word in r for r in ranks):
            out[word] = (reading, best)
    return out


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
    from app.analyzer import JoinedWord, join_affixes
    every, joins = _Every(), {}
    for word, (reading, _rank) in headwords.items():
        tokens = tagger(word)
        if len(tokens) < 2:
            continue
        joined = join_affixes(tokens, every)
        if len(joined) == 1 and isinstance(joined[0], JoinedWord) and joined[0].feature.orthBase == word:
            joins[word] = [word, reading]
    return joins


def one_lemma_per_spelling(tagger, joins, headwords):
    """`joins` with every spelling of a word under one lemma, the best-ranked spelling's (the user,
    checkpoint A): お勧め / おすすめ / オススメ, ご存じ / 御存じ, 面倒くさい / 面倒臭い are one list word, and
    knowing one knows them all; the text keeps its own spelling (orth). Spellings are one word when
    their pieces have the same lemmas and the lists give them the same reading."""
    from collections import defaultdict
    groups = defaultdict(list)
    for word, (_lemma, reading) in joins.items():
        groups[(tuple(t.feature.lemma for t in tagger(word)), reading)].append(word)
    for words in groups.values():
        best = min(words, key=lambda w: (headwords[w][1], w))
        for word in words:
            joins[word] = [best, joins[word][1]]
    print(f"  {sum(len(w) > 1 for w in groups.values()):,} words written more than one way")
    return joins


def _ogo_texts():
    """The shared set's text files, sliced as build_shared.py slices them."""
    paths = []
    for source, budget in OGO_SOURCES.items():
        folder, total = os.path.join(CORPUS_TEXT, source), 0
        for name in sorted(os.listdir(folder)):
            if budget is not None and total >= budget:
                break
            path = os.path.join(folder, name)
            if budget is not None:
                with open(path, encoding="utf-8") as f:
                    total += len(f.read())
            paths.append(path)
    return paths


_OGO = {}


def _ogo_init(joins, bases):
    import fugashi
    _OGO.update(tagger=fugashi.Tagger(), joins=joins, bases=bases)


def _noun_use(nxt):
    """Is a verb's 連用形 (願い) used as a noun here — before a particle, the copula, punctuation or the
    end — rather than as a verb (願います, 願いたい, 願って)?"""
    if nxt is None:
        return True
    f = nxt.feature
    return (f.pos1 in ("補助記号", "空白") or (f.pos1 == "助詞" and f.pos2 != "接続助詞")
            or (f.pos1 == "助動詞" and f.lemma in ("だ", "です")))


def _ogo_count(path):
    """-> (Counter of お/ご words, Counter of their bare bases) in one text file."""
    from collections import Counter
    from app.analyzer import JoinedWord, join_affixes
    tagger, joins, bases = _OGO["tagger"], _OGO["joins"], _OGO["bases"]
    prefixed, bare = Counter(), Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            words = join_affixes(tagger(line.rstrip("\n")), joins)
            for i, w in enumerate(words):
                if isinstance(w, JoinedWord):
                    if w.feature.orthBase in bases.get("words", ()):
                        prefixed[w.feature.orthBase] += 1
                    continue
                f_ = w.feature
                key = (f_.lemma, f_.lForm)
                if key in bases["nouns"]:
                    noun = True
                elif key in bases["verbs"]:
                    noun = (str(f_.cForm).startswith("連用形") and w.surface == bases["verbs"][key]
                            and _noun_use(words[i + 1] if i + 1 < len(words) else None))
                else:
                    continue
                prev = words[i - 1] if i else None
                if prev is not None and not isinstance(prev, JoinedWord) and prev.feature.pos1 == "接頭辞" \
                        and prev.feature.lemma == "御":
                    continue            # お名前 not joined: neither the prefixed word nor the bare one
                if noun:
                    bare[key] += 1
    return prefixed, bare


def ogo_filter(tagger, joins, workers=10):
    """`joins` without the お / ご / 御 words that are not a usual form of their word (OGO_SHARE, U1, or
    OGO_TALK_SHARE in conversation), decided once for all the spellings of a word; a word that ends in an
    honorific stays (HONORIFICS). Writes the table it decided by to OGO_REPORT (debug/, gitignored) for
    the user to read."""
    import multiprocessing
    from collections import Counter, defaultdict
    from concurrent.futures import ProcessPoolExecutor
    ogo, nouns, verbs = {}, {}, {}
    for word in joins:
        tokens = tagger(word)
        first, last = tokens[0].feature, tokens[-1]
        if (first.pos1 != "接頭辞" or first.lemma != "御"
                or last.surface in HONORIFICS or last.feature.lemma in HONORIFICS):
            continue
        base = tokens[1]
        key = (base.feature.lemma, base.feature.lForm)
        ogo[word] = key
        if base.feature.pos1 == "動詞":
            verbs[key] = base.surface
        else:
            nouns[key] = base.surface
    bases = {"words": frozenset(ogo), "nouns": nouns, "verbs": verbs}
    paths = _ogo_texts()
    prefixed, bare, talk_prefixed, talk_bare = Counter(), Counter(), Counter(), Counter()
    with ProcessPoolExecutor(workers, multiprocessing.get_context("spawn"), _ogo_init, (joins, bases)) as pool:
        for path, (p, b) in zip(paths, pool.map(_ogo_count, paths)):
            prefixed.update(p)
            bare.update(b)
            if os.path.basename(os.path.dirname(path)) == OGO_TALK:
                talk_prefixed.update(p)
                talk_bare.update(b)
    spellings = defaultdict(list)           # lemma -> its お/ご spellings (one_lemma_per_spelling)
    for word in ogo:
        spellings[joins[word][0]].append(word)
    kept, rows = dict(joins), []
    for lemma, words in spellings.items():
        key = ogo.get(lemma, ogo[words[0]])
        uses, talk = sum(prefixed[w] for w in words), sum(talk_prefixed[w] for w in words)
        share = uses / (uses + bare[key]) if uses + bare[key] else 0.0
        talk_share = talk / (talk + talk_bare[key]) if talk + talk_bare[key] else 0.0
        joined = ((uses >= OGO_MIN_USES and share >= OGO_SHARE)
                  or (talk >= OGO_MIN_USES and talk_share >= OGO_TALK_SHARE))
        if not joined:
            for word in words:
                del kept[word]
        if uses >= OGO_MIN_USES or talk >= OGO_MIN_USES:
            rows.append((" / ".join(sorted(words, key=lambda w: w != lemma)), uses, bare[key], share,
                         talk, talk_share, joined))
    rows.sort(key=lambda r: (-max(r[3], r[5]), r[0]))
    os.makedirs(os.path.dirname(OGO_REPORT), exist_ok=True)
    with open(OGO_REPORT, "w", encoding="utf-8") as f:
        f.write(f"# お / ご / 御 words — joined at a share of at least {OGO_SHARE:.0%}, or {OGO_TALK_SHARE:.0%} "
                f"in conversation ({date.today()})\n\n"
                f"Over the shared set's text, and its conversation ({OGO_TALK}) alone; words with at least "
                f"{OGO_MIN_USES} prefixed uses in either. {sum(r[6] for r in rows)} join, "
                f"{sum(not r[6] for r in rows)} stay a prefix + a word. Words that end in an honorific "
                "(お母さん, お客様) always join and are not listed.\n\n"
                "| word | prefixed | bare | share | in conversation | share there | joined |\n"
                "| :-- | --: | --: | --: | --: | --: | :-- |\n")
        f.writelines(f"| {w} | {u:,} | {b:,} | {s:.0%} | {t:,} | {ts:.0%} | {'yes' if j else 'no'} |\n"
                     for w, u, b, s, t, ts, j in rows)
    print(f"  お/ご words: {len(spellings):,} in the lists, {len(rows):,} with ≥ {OGO_MIN_USES} uses, "
          f"{sum(r[6] for r in rows):,} joined (report: {OGO_REPORT})")
    return kept


def build_aliases(tagger, vocabularies, joins=None):
    """lemma -> the best-ranked spelling that produces it.

    Collisions are the subtle part: many spellings collapse to one lemma (する, し, しぃ all
    give 為る), and taking the LAST one seen yields nonsense like 為る -> しぃ. Keep the
    lowest-ranked (most common) spelling instead, so 為る -> する. Words are read through the
    affix join (`joins`), as the analyzer reads them.
    """
    from app.analyzer import join_affixes
    best = {}
    for ranks in vocabularies:
        for word, rank in ranks.items():
            tokens = join_affixes(tagger(word), joins or {})
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
    import math
    return math.exp(sum(math.log(v) for v in values) / len(values))


def main():
    import fugashi
    tagger = fugashi.Tagger()

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
    joins = ogo_filter(tagger, one_lemma_per_spelling(tagger, build_joins(tagger, headwords), headwords))
    print(f"  {len(headwords):,} headwords, {len(joins):,} joins")

    print("\nBuilding alias map (tokenizing reference vocabulary)...")
    aliases = build_aliases(tagger, spoken + [written], joins)
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

        from app.analyzer import join_affixes
        tokens = join_affixes(tagger(word), joins)
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

    def blob(obj):
        return base64.b64encode(
            zlib.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
        ).decode("ascii")

    aliases_b64, spoken_b64, joins_b64 = blob(aliases), blob(spoken_rank), blob(joins)
    print(f"\nEncoded: aliases {len(aliases_b64)/1024:,.0f} KB, spoken_rank {len(spoken_b64)/1024:,.0f} KB, "
          f"affix joins {len(joins_b64)/1024:,.0f} KB")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(MODULE_TEMPLATE.format(
            revision=date.today().isoformat(),
            n_aliases=len(aliases),
            n_spoken=len(spoken_rank),
            n_joins=len(joins),
            cap=f"{WRITTEN_RANK_CAP:,}",
            spoken_lists=" + ".join(SPOKEN_LISTS),
            written_list=WRITTEN_LIST,
            join_lists=" + ".join(JOIN_LISTS),
            one_list_rank=f"{JOIN_ONE_LIST_RANK:,}",
            ogo_share=f"{OGO_SHARE:.0%}",
            talk_share=f"{OGO_TALK_SHARE:.0%}",
            aliases_b64=aliases_b64,
            spoken_b64=spoken_b64,
            joins_b64=joins_b64,
        ))
    print(f"\nWrote {OUTPUT} ({os.path.getsize(OUTPUT)/1024:,.0f} KB)")


MODULE_TEMPLATE = '''"""Reference data distilled from the corpora — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_reference_data.py

Revision: {revision}
  ALIASES      {n_aliases:,} entries — unidic lemma -> the spelling frequency lists use.
  SPOKEN_RANK  {n_spoken:,} entries — written vocabulary (top {cap} of {written_list}, proper
               nouns and interjections removed) -> its rank in {spoken_lists}.
               A rank of 0 means the spoken corpora never saw it, i.e. rarer than they can measure.
  AFFIX_JOINS  {n_joins:,} entries — a written form -> [lemma, reading]: the {join_lists} headwords
               (in both, or in one's top {one_list_rank}) that UniDic splits into a prefix + a word
               or a word + suffixes, joined back by analyzer.join_affixes; every spelling of a word
               shares its lemma (お / ご words only where the prefixed form is at least {ogo_share}
               of the word's uses, or {talk_share} in conversation).

The tables are stored compressed and decoded lazily, so importing this module is cheap and a
process that never asks for them never pays for them.
"""

import base64
import json
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

_aliases = None
_spoken_rank = None
_affix_joins = None


def _decode(b64):
    return json.loads(zlib.decompress(base64.b64decode(b64)).decode("utf-8"))


def aliases():
    """lemma -> common spelling. Empty dict is a valid (degraded) answer, never an exception."""
    global _aliases
    if _aliases is None:
        try:
            _aliases = _decode(_ALIASES_B64)
        except Exception:
            _aliases = {{}}
    return _aliases


def spoken_ranks():
    """lemma -> spoken rank (0 = beyond the reference corpora)."""
    global _spoken_rank
    if _spoken_rank is None:
        try:
            _spoken_rank = _decode(_SPOKEN_RANK_B64)
        except Exception:
            _spoken_rank = {{}}
    return _spoken_rank


def affix_joins():
    """written form -> [lemma, reading] (analyzer.join_affixes). Empty when it cannot be read: words then
    stay as UniDic cuts them, never an exception."""
    global _affix_joins
    if _affix_joins is None:
        try:
            _affix_joins = _decode(_AFFIX_JOINS_B64)
        except Exception:
            _affix_joins = {{}}
    return _affix_joins
'''


if __name__ == "__main__":
    main()
