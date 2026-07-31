"""Distil the reference corpora into app/reference_data.py (DEV ONLY — never shipped).

Why this exists
---------------
Deciding whether a word is one you'll READ or one you'll HEAR is a question about Japanese,
not about any particular user: it depends only on the reference corpora and the tokenizer, both
of which are fixed when we build. So all of that work happens HERE, once, and the app ships a
small lookup table. The user's machine never loads a corpus, never tokenizes a word list, and
pays nothing at Generate time beyond a dict lookup.

Two tables come out of it:

  ALIASES      lemma -> the spelling frequency lists actually use.
               Unidic hands the analyzer orthographic lemmas (為る, 矢張り, 其れ); every
               frequency list on earth stores する, やっぱり, それ. Without this bridge the
               most common verb in the language reports as "Outside" in the Tier column.

  SPOKEN_RANK  lemma -> its rank in spoken Japanese (0 = rarer than the corpora can see).
               Only words that are real WRITTEN vocabulary get an entry — see the filters
               below. app/modality.py turns the rank into "hours of listening between
               encounters" and compares that to the user's threshold.

Inputs live in scripts/reference_lists/ (gitignored; see .gitignore). Output is committed.

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

LISTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference_lists")
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


def build_aliases(tagger, vocabularies):
    """lemma -> the best-ranked spelling that produces it.

    Collisions are the subtle part: many spellings collapse to one lemma (する, し, しぃ all
    give 為る), and taking the LAST one seen yields nonsense like 為る -> しぃ. Keep the
    lowest-ranked (most common) spelling instead, so 為る -> する.
    """
    best = {}
    for ranks in vocabularies:
        for word, rank in ranks.items():
            tokens = list(tagger(word))
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

    print("\nBuilding alias map (tokenizing reference vocabulary)...")
    aliases = build_aliases(tagger, spoken + [written])
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

        tokens = list(tagger(word))
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

    aliases_b64, spoken_b64 = blob(aliases), blob(spoken_rank)
    print(f"\nEncoded: aliases {len(aliases_b64)/1024:,.0f} KB, spoken_rank {len(spoken_b64)/1024:,.0f} KB")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(MODULE_TEMPLATE.format(
            revision=date.today().isoformat(),
            n_aliases=len(aliases),
            n_spoken=len(spoken_rank),
            cap=f"{WRITTEN_RANK_CAP:,}",
            spoken_lists=" + ".join(SPOKEN_LISTS),
            written_list=WRITTEN_LIST,
            aliases_b64=aliases_b64,
            spoken_b64=spoken_b64,
        ))
    print(f"\nWrote {OUTPUT} ({os.path.getsize(OUTPUT)/1024:,.0f} KB)")


MODULE_TEMPLATE = '''"""Reference data distilled from the corpora — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_reference_data.py

Revision: {revision}
  ALIASES      {n_aliases:,} entries — unidic lemma -> the spelling frequency lists use.
  SPOKEN_RANK  {n_spoken:,} entries — written vocabulary (top {cap} of {written_list}, proper
               nouns and interjections removed) -> its rank in {spoken_lists}.
               A rank of 0 means the spoken corpora never saw it, i.e. rarer than they can measure.

Both tables are stored compressed and decoded lazily, so importing this module is cheap and a
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

_aliases = None
_spoken_rank = None


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
'''


if __name__ == "__main__":
    main()
