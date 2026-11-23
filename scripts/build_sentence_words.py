"""Build the sentence table's grammar words — the fixed lists `app/sentence_table.py` counts "words besides the word"
with (SPEC § 3.2, decision 9b) — and write them into that file's generated block.

    python scripts/build_sentence_words.py [--corpus <the reference text's _text folder>] [--mb 8]

The token store keeps no part of speech, so a line's words are told apart by their base form alone: a word is grammar
when the tagger calls it grammar in most of its uses in general Japanese — the shared reference text's spoken sources
(persona chat, film subtitles, the Nagoya conversation corpus; `--mb` megabytes of each), read as the app reads a
file (the tagger, then `join_affixes` without the library's tables) and judged by each word's head as the sentence
study judged them: particles, auxiliaries, prefixes, suffixes and an auxiliary's stem are grammar; interjections and
conjunctions are said, not content; anything else is content. A helping verb (UniDic's 非自立可能: いる, しまう, くれる)
is grammar only right after て / で / って / ちゃ / じゃ — kept apart, judged by its place. A katakana word is never
grammar (a loanword or a name). Chinese: jieba's own tag
table (`dict.txt`) — its particles (u*), modal particles (y), interjections (e), prepositions (p) and conjunctions (c)
that it counts 2,000 times or more. Nothing of a user's library is read. The lists change no tokenization: rebuilding
them changes only the table's counts (a `sentence_table.VERSION` bump).
"""
import argparse
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TARGET = os.path.join(ROOT, "app", "sentence_table.py")
SPOKEN = ("realpersonachat", "opensubtitles", "nucc")
TE = ("て", "で", "って", "ちゃ", "じゃ")
KATAKANA = re.compile(r"[\u30a0-\u30ff]+")
MIN_USES = 5                    # a base form met fewer times is left to the default (content)
ZH_MIN_COUNT = 2000             # jieba's own count
ZH_TAGS = ("u", "y", "e", "p", "c")
BEGIN, END = "# --- grammar words: scripts/build_sentence_words.py writes this block ---", "# --- end of the block ---"


def japanese(corpus, mb):
    from app import analyzer
    tagger, joins = analyzer.Tagger(), analyzer.affix_joins()
    kinds = collections.defaultdict(collections.Counter)      # lemma -> {"C", "F", "I"}
    pos1s = collections.defaultdict(collections.Counter)      # lemma -> its grammar uses by part of speech
    helpers = collections.Counter()
    for source in SPOKEN:
        budget, folder = int(mb * 1e6), os.path.join(corpus, source)
        for name in sorted(os.listdir(folder)):
            if budget <= 0:
                break
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    budget -= len(line.encode("utf-8"))
                    words = analyzer.join_affixes(tagger(line), joins, library=False)
                    for i, word in enumerate(words):
                        lemma = analyzer.word_lemma(word)
                        if not lemma:
                            continue
                        lemma = analyzer._sanitize_term(lemma)
                        f_ = word.feature
                        if isinstance(word, analyzer.JoinedWord):   # its head: the first piece that is no prefix
                            f_ = next((pf for _s, pf in word.parts if pf.pos1 != "接頭辞"), word.parts[0][1])
                        p1, p2 = f_.pos1, f_.pos2
                        if p1 in ("動詞", "形容詞") and p2 == "非自立可能" and not isinstance(word, analyzer.JoinedWord):
                            helpers[lemma] += 1
                            prev = words[i - 1] if i else None
                            if prev is not None and prev.feature.pos1 == "助詞" and prev.surface in TE:
                                continue                        # grammar by its place, never by its form
                        if p1 in ("助詞", "助動詞", "接尾辞", "接頭辞") or (p1 == "名詞" and p2 == "助動詞語幹"):
                            kinds[lemma]["F"] += 1
                            pos1s[lemma][p1] += 1
                        elif p1 in ("感動詞", "接続詞"):
                            kinds[lemma]["I"] += 1
                        else:
                            kinds[lemma]["C"] += 1
                if budget <= 0:
                    break
    grammar = {lemma for lemma, c in kinds.items() if sum(c.values()) >= MIN_USES and c["F"] + c["I"] > c["C"]
               and not KATAKANA.fullmatch(lemma)}         # a katakana word is a loanword or a name: content
    particles = {lemma for lemma in grammar if pos1s[lemma] and pos1s[lemma].most_common(1)[0][0] == "助詞"}
    suffixes = {lemma for lemma in grammar if pos1s[lemma] and pos1s[lemma].most_common(1)[0][0] == "接尾辞"}
    return (sorted(particles), sorted(suffixes), sorted(grammar - particles - suffixes),
            sorted(lemma for lemma, n in helpers.items() if n >= MIN_USES))


def chinese():
    import jieba
    out = set()
    with open(os.path.join(os.path.dirname(jieba.__file__), "dict.txt"), encoding="utf-8") as f:
        for line in f:
            word, count, tag = line.split()
            if tag[0] in ZH_TAGS and int(count) >= ZH_MIN_COUNT:
                out.add(word)
    return sorted(out)


def literal(name, words, comment):
    text, lines, line = " ".join(words), [], ""
    for word in words:
        if len(line) + len(word) + 1 > 100:
            lines.append(line)
            line = ""
        line = f"{line} {word}" if line else word
    lines.append(line)
    body = "\n".join(f'    "{x} "' for x in lines[:-1]) + ("\n" if len(lines) > 1 else "") + f'    "{lines[-1]}"'
    assert " ".join(lines) == text
    return f"{name} = (  # {comment}: {len(words)}\n{body}\n)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(ROOT, "docs", "assets", "corpora", "_text"))   # as build_reference_data
    ap.add_argument("--mb", type=float, default=8)
    args = ap.parse_args()
    particles, suffixes, grammar, helpers = japanese(args.corpus, args.mb)
    zh = chinese()
    block = "\n".join((BEGIN,
                       literal("_JA_PARTICLES", particles, "ja particles (UniDic 助詞)"),
                       literal("_JA_SUFFIXES", suffixes, "ja suffixes (接尾辞)"),
                       literal("_JA_GRAMMAR", grammar, "ja other grammar: auxiliaries, prefixes, interjections, conjunctions"),
                       literal("_JA_HELPERS", helpers, "ja helping verbs (非自立可能): grammar right after て / で"),
                       literal("_ZH_GRAMMAR", zh, "zh: jieba's particles, prepositions, conjunctions, interjections"),
                       END))
    with open(TARGET, encoding="utf-8") as f:
        source = f.read()
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pattern.search(source):
        sys.exit(f"{TARGET}: the generated block's markers are missing")
    with open(TARGET, "w", encoding="utf-8") as f:     # the platform's line ends, as git checks it out
        f.write(pattern.sub(lambda _m: block, source))
    print(f"ja: {len(particles)} particles, {len(suffixes)} suffixes, {len(grammar)} other, {len(helpers)} helpers · "
          f"zh: {len(zh)}")


if __name__ == "__main__":
    main()
