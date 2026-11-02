"""Measurement variants for step 4 (Chinese), beside the staged ones in variants_zh_build.py (copied byte for byte —
this file holds what the measurement found the staged ones need, and the other names guards it measured).

    zh-hmm-off-names-guard           the names guard exactly as Chinese_Build_Spec.md §2.3 states it: only a run
                                     jieba's HMM made — a token of the HMM-on cut that the HMM-off cut doesn't hold —
                                     is a candidate. The staged zh-hmm-off-names-surname also tries the 2-character
                                     head of every 3-character token, a dictionary word included, so it cuts 王小明
                                     (a jieba entry) into 王小 + 明 — and on general text 新加坡, 洛杉矶, 习近平 (247
                                     dictionary words in 3,000 lines). A run can be a guess and a dictionary entry at
                                     once (不累: the dictionary's route takes 不 + 累, the HMM regroups them), so "not
                                     in the dictionary" is no test of a guess: the two cuts are compared. Same guard
                                     otherwise: 2-3 characters, led by a CC-CEDICT surname, no jieba dictionary word,
                                     no character jieba's tags file as grammar, no verb last at 3; else the 2-character
                                     head.
    zh-hmm-off-names-posseg          a guessed run stays whole when jieba's own part-of-speech tagger (posseg, its
                                     name model) reads the same stretch as one name — a person (nr, nrfg, nrt), a
                                     place (ns), an organisation (nt) or another proper noun (nz).
    zh-hmm-off-names-surname-posseg  both: the surname guard's test and posseg's name reading.
    zh-hmm-off-names-person          posseg's person-name reading only (nr, nrfg, nrt) — its place reading (ns)
                                     takes direction + place characters for names (南临, 东依, 六省).
    zh-hmm-off-names-surname-person  the surname test and posseg's person-name reading.

The groups as they would land together (each step the staged variant's own code, composed in the order the one
Chinese cut runs them — the names guard on the dictionary's cut, the narrow split after it, the text read through
Simplified, then numbers and doubled forms on the tokens):
    zh-cedict-grammar-numerals       Z4 narrow + Z5: zh-cedict-grammar and zh-numerals-not-words
    zh-chain                         Z3 (#10 + HMM off + the surname guard) + Z4 narrow + Z5 + Z6 (own-meaning)
    zh-chain-no-guard                the same with HMM off and no names guard
    zh-chain-hmm-on                  the same with the HMM left on (Z3 = #10 alone)

N1, phase 2 (ZH-ZHE-READING), patching the Traditional→Simplified table's phrases:
    zh-zhe-pairs                     CC-CEDICT's own pairs whose Traditional holds 著 where the Simplified holds 着
                                     (睡著 -> 睡着, 著急 -> 着急, 隨著 -> 随着; 著名 stays), as phrases — the spec's N1
    zh-zhe-pairs-noword              the same, and every pair whose Simplified reading by OpenCC is no word of jieba's
                                     dictionary nor of CC-CEDICT (砲擊 -> 砲击, read 炮击; 姪女 -> 侄女; 暱稱 -> 昵称)

N2, phase 2 (ZH-COMPOUND-JOIN):
    zh-compound-join                 a run of 2-6 pieces of the cut spelling a CC-CEDICT word jieba's dictionary lacks
                                     is one piece, when the even-odds gate let it through on general text (e >= 1 and
                                     o < 2e refuses: 是的, 中的 stay apart; 不可能, 新冠肺炎, 蔡英文 join) — the table
                                     debug/parsing_fixes_run/step4/measure/n2_joins.py wrote (n2_joins.json)
    zh-compound-join-ud              the same, with the UD Chinese treebanks as a second witness: a word they write as
                                     several tokens (at least twice, more often than whole) is refused — 到了, 我去,
                                     每个人, 得很 stay apart (n2_joins_ud.json)

Loads after variants_zh_build.py (sorted), whose data readers it uses; data is read on entry, never at import.
"""
import os

from tests.parsing import harness, variants_zh_build as build
from tests.parsing.harness import patched
from tests.parsing.variants import VARIANTS, variant


def surname_test():
    """The guard's test, as staged: 2-3 characters, led by a CC-CEDICT surname, no jieba dictionary word, no
    grammar character by jieba's tags, and no verb last at 3 characters."""
    jieba = build._jieba()
    freq, family, tags = jieba.dt.FREQ, build.surnames(), build.tag_table()

    def named(run):
        read = build.zh_script.to_simplified(run)
        return (2 <= len(read) <= 3 and read[0] in family and not freq.get(read)
                and not any(tags.get(ch) in build.GRAMMAR_TAGS for ch in read)
                and not (len(read) == 3 and str(tags.get(read[-1]) or "").startswith("v")))
    return named


PERSON_TAGS = frozenset(("nr", "nrfg", "nrt"))


def posseg_names(sentence, tags=build.NAME_TAGS):
    """The (start, end) stretches jieba's part-of-speech tagger reads as one name (of `tags`) in `sentence`."""
    import jieba.posseg as posseg
    spans, pos = set(), 0
    for pair in posseg.dt.cut(sentence):
        if pair.flag in tags:
            spans.add((pos, pos + len(pair.word)))
        pos += len(pair.word)
    return spans


def guarded_cut(real, keep, sentence, cut_all=False, use_paddle=False):
    """The HMM-off cut, except a run the HMM-on cut keeps whole that `keep(run, start, end)` accepts (or whose
    2-character head it accepts): the HMM regroups only runs of single characters of the dictionary's route, so
    such a run spans pieces of the HMM-off cut."""
    off = list(real(sentence, cut_all=cut_all, HMM=False, use_paddle=use_paddle))
    pieces, pos = {}, 0
    for piece in off:
        pieces[pos] = piece
        pos += len(piece)

    def off_pieces(start, end):
        held = []
        while start < end and start in pieces:
            held.append(pieces[start])
            start += len(pieces[start])
        return held if start == end else None

    out, pos = [], 0
    for token in real(sentence, cut_all=cut_all, HMM=True, use_paddle=use_paddle):
        start, end = pos, pos + len(token)
        pos = end
        inside = off_pieces(start, end)
        if inside is None or len(inside) == 1:
            out.append(token)                 # the same token in both cuts (or no clean alignment: as the HMM cut)
        elif keep(token, start, end):
            out.append(token)
        elif len(token) == 3 and off_pieces(start, start + 2) is not None and keep(token[:2], start, start + 2):
            out.append(token[:2])
            out.extend(off_pieces(start + 2, end))
        else:
            out.extend(inside)                # its pieces in the HMM-off cut
    return out


def _guarded(make_keep):
    jieba = build._jieba()
    real = jieba.cut

    def cut(sentence, cut_all=False, HMM=True, use_paddle=False):
        return iter(guarded_cut(real, make_keep(sentence), sentence, cut_all=cut_all, use_paddle=use_paddle))
    return patched(jieba, "cut", cut)


@variant("zh-hmm-off-names-guard",
         "zh-hmm-off-via-simplified with the names guard as the spec states it: a run jieba's HMM made (a token of the "
         "HMM-on cut the HMM-off cut lacks) stays whole when it is 2-3 characters led by a CC-CEDICT surname, no "
         "dictionary word, with no grammar character and no verb last at 3; else its 2-character head is tried — "
         "李明 whole, 王小明 untouched (a jieba entry), 我要 split.")
def _zh_hmm_off_names_guard():
    named = surname_test()
    with _guarded(lambda sentence: lambda run, start, end: named(run)), \
            VARIANTS["zh-asis-via-simplified"].manager():
        yield


@variant("zh-hmm-off-names-posseg",
         "zh-hmm-off-via-simplified with jieba's own name model as the guard: a run its HMM made stays whole when "
         "jieba's part-of-speech tagger reads the same stretch as one name (nr nrfg nrt ns nt nz).")
def _zh_hmm_off_names_posseg():
    build._jieba()

    def make_keep(sentence):
        spans = posseg_names(sentence)
        return lambda run, start, end: (start, end) in spans
    with _guarded(make_keep), VARIANTS["zh-asis-via-simplified"].manager():
        yield


@variant("zh-hmm-off-names-surname-posseg",
         "zh-hmm-off-via-simplified with both guards at once: a run its HMM made stays whole when it passes the "
         "surname test AND jieba's part-of-speech tagger reads the same stretch as one name.")
def _zh_hmm_off_names_surname_posseg():
    named = surname_test()

    def make_keep(sentence):
        spans = posseg_names(sentence)
        return lambda run, start, end: (start, end) in spans and named(run)
    with _guarded(make_keep), VARIANTS["zh-asis-via-simplified"].manager():
        yield


@variant("zh-hmm-off-names-person",
         "zh-hmm-off-via-simplified with jieba's person-name model as the guard: a run its HMM made stays whole when "
         "jieba's part-of-speech tagger reads the same stretch as one person's name (nr nrfg nrt).")
def _zh_hmm_off_names_person():
    build._jieba()

    def make_keep(sentence):
        spans = posseg_names(sentence, PERSON_TAGS)
        return lambda run, start, end: (start, end) in spans
    with _guarded(make_keep), VARIANTS["zh-asis-via-simplified"].manager():
        yield


@variant("zh-hmm-off-names-surname-person",
         "zh-hmm-off-via-simplified with the surname test AND jieba's person-name reading of the same stretch.")
def _zh_hmm_off_names_surname_person():
    named = surname_test()

    def make_keep(sentence):
        spans = posseg_names(sentence, PERSON_TAGS)
        return lambda run, start, end: (start, end) in spans and named(run)
    with _guarded(make_keep), VARIANTS["zh-asis-via-simplified"].manager():
        yield


def _surname_guard():
    named = surname_test()
    return _guarded(lambda sentence: lambda run, start, end: named(run))


@variant("zh-cedict-grammar-numerals",
         "Z4 narrow + Z5 as they land together: zh-cedict-grammar's split, then zh-numerals-not-words (一碗 -> [一] / 碗).")
def _zh_cedict_grammar_numerals():
    with VARIANTS["zh-cedict-grammar"].manager(), VARIANTS["zh-numerals-not-words"].manager():
        yield


def _chain(cut_first):
    """The groups composed: `cut_first` (a context manager for jieba.cut, or None), the narrow split on top of it,
    as-is through Simplified, then numbers no words and doubled forms at their base (the own-meaning test)."""
    import contextlib
    with contextlib.ExitStack() as stack:
        if cut_first is not None:
            stack.enter_context(cut_first)
        for name in ("zh-cedict-grammar", "zh-asis-via-simplified", "zh-numerals-not-words",
                     "zh-redup-lemma-own-meaning"):
            stack.enter_context(VARIANTS[name].manager())
        yield


@variant("zh-chain",
         "Z3 (#10 + HMM off + the surname names guard) + Z4 narrow + Z5 + Z6 own-meaning — every Chinese group as the "
         "spec chains them, with the guard as the spec states it.")
def _zh_chain():
    yield from _chain(_surname_guard())


@variant("zh-chain-no-guard",
         "zh-chain with HMM off and no names guard (#4 without a guard).")
def _zh_chain_no_guard():
    yield from _chain(VARIANTS["zh-hmm-off"].manager())


@variant("zh-chain-hmm-on",
         "zh-chain with the HMM left on — Z3 ships #10 alone (#4 not built).")
def _zh_chain_hmm_on():
    yield from _chain(None)



# --- N1: CC-CEDICT's own Traditional / Simplified pairs, as phrases of the Traditional→Simplified table ------- #
def cedict_pairs():
    """{Traditional headword: Simplified} — CC-CEDICT's own pairs of two characters or more with one Simplified
    spelling, length-preserving, read once."""
    if "pairs" not in build._DATA:
        import zipfile
        with zipfile.ZipFile(build.CEDICT) as archive:
            text = archive.read("cedict_ts.u8").decode("utf-8")
        held = {}
        for line in text.splitlines():
            found = None if line.startswith("#") else build._ENTRY.match(line)
            if found and len(found.group(1)) == len(found.group(2)) > 1:
                held.setdefault(found.group(1), set()).add(found.group(2))
        build._DATA["pairs"] = {t: next(iter(s)) for t, s in held.items() if len(s) == 1}
    return build._DATA["pairs"]


def zhe_pairs():
    """The pairs whose Traditional holds 著 where the Simplified holds 着 — 睡著 -> 睡着, 著急 -> 着急."""
    return {t: s for t, s in cedict_pairs().items() if any(a == "著" and b == "着" for a, b in zip(t, s))}


def noword_pairs():
    """The pairs OpenCC reads as no word — neither jieba's dictionary nor CC-CEDICT holds its Simplified reading —
    where CC-CEDICT pairs another (砲擊: OpenCC 砲击, CC-CEDICT 炮击)."""
    jieba = build._jieba()
    listed, to_simplified = build.words(), build.zh_script.to_simplified
    out = {}
    for traditional, simplified in cedict_pairs().items():
        opencc = to_simplified(traditional)
        if opencc != simplified and not jieba.dt.FREQ.get(opencc) and opencc not in listed:
            out[traditional] = simplified
    return out


def _with_phrases(extra):
    """zh_script's Traditional→Simplified table with `extra` phrases beside OpenCC's own (OpenCC's win a tie)."""
    from app import zh_script, zh_script_data
    table = zh_script_data.t2s()
    phrases = dict(extra)
    phrases.update(table["phrases"])
    converter = zh_script._Converter({"chars": table["chars"], "phrases": phrases})
    return patched(zh_script, "_converters", {**zh_script._converters, "t2s": converter})


@variant("zh-zhe-pairs",
         "N1 (ZH-ZHE-READING): 著 read as 着 where CC-CEDICT pairs the spellings — 睡著 -> 睡着, 著急 -> 着急, 隨著 -> "
         "随着 — as phrases of the Traditional→Simplified table; 著名 stays.")
def _zh_zhe_pairs():
    pairs = zhe_pairs()
    with _with_phrases(pairs):
        yield


@variant("zh-zhe-pairs-noword",
         "zh-zhe-pairs, and every CC-CEDICT pair OpenCC reads as no word of either dictionary: 砲擊 -> 炮击, 姪女 -> "
         "侄女, 暱稱 -> 昵称.")
def _zh_zhe_pairs_noword():
    pairs = {**noword_pairs(), **zhe_pairs()}
    with _with_phrases(pairs):
        yield



# --- N2: CC-CEDICT words the cut writes in pieces, joined where the even-odds gate allows ----------------------- #
N2_TABLE = os.path.join(harness.ROOT, "debug", "parsing_fixes_run", "step4", "measure", "n2_joins{}.json")


def compound_joins(tag=""):
    """The words n2_joins.py's gate let through (`tag` "_ud": with the treebank witness), read once."""
    if "joins" + tag not in build._DATA:
        import json
        with open(N2_TABLE.format(tag), encoding="utf-8") as handle:
            verdicts = json.load(handle)["verdicts"]
        joins = frozenset(word for word, verdict in verdicts.items() if verdict["join"])
        build._DATA["joins" + tag] = (joins, frozenset(word[:k] for word in joins for k in range(1, len(word))))
    return build._DATA["joins" + tag]


def join_words(pieces, joins, prefixes, longest=6):
    """`pieces` with every run of 2-6 spelling a word of `joins` one piece — the longest at each place, left to right."""
    out, i, n = [], 0, len(pieces)
    while i < n:
        best, text, j = None, pieces[i], i + 1
        while j < n and j - i < longest and text in prefixes:
            text += pieces[j]
            j += 1
            if text in joins:
                best = j
        if best:
            out.append("".join(pieces[i:best]))
            i = best
        else:
            out.append(pieces[i])
            i += 1
    return out


@variant("zh-compound-join",
         "N2 (ZH-COMPOUND-JOIN): a CC-CEDICT word jieba's dictionary lacks, cut into 2-6 pieces, is one piece where the "
         "even-odds gate let it through on general text — 不可能, 新冠肺炎, 蔡英文; 是的 and 中的 stay apart.")
def _zh_compound_join():
    yield from _joining("")


def _joining(tag):
    from app import analyzer
    joins, prefixes = compound_joins(tag)
    real = analyzer.chinese_cut

    def chinese_cut(text):
        return join_words(real(text), joins, prefixes)
    with patched(analyzer, "chinese_cut", chinese_cut):
        yield


@variant("zh-compound-join-ud",
         "zh-compound-join with the UD Chinese treebanks as a second witness: a word they write as several tokens (at "
         "least twice, more often than whole) is refused — 到了, 我去, 每个人 and 得很 stay apart.")
def _zh_compound_join_ud():
    yield from _joining("_ud")
