"""The core layers. Each runs the app's OWN code on a case and returns what it sees — never raw fugashi, never a
copy of a rule the app holds (where the app keeps a rule inline in analyzer.main, the mirror is named).

    layer       text is                       expect keys
    tokens_ja   the whole line(s)             units, absent, words, not_words
    tokens_zh   the sentence / line           seg, words, not_words
    text        a file's content (ctx ext)    sentences, contains, not_contains, words, not_words
    card_key    the card's word field         key, via, word
    known       a KnownWord dictForm (or "")  known, unknown, adds
    unknowns    the sentence                  count, unknowns

More layers (Junban placement, the report's label, パターン, 例文 …) go in evaluators_<area>.py beside this file;
docs/agent instructions/Parsing_Suite.md describes every key and how to add one.
"""
import re

from app import analyzer, anki_match, zh_script
from tests.parsing.harness import (Token, compare_keys, compare_members, evaluator, key, patched, short,
                                   split_key)


def _has_target(text, lang):
    return analyzer.has_target_language(str(text), lang)


# --- tokens_ja ------------------------------------------------------------------------------------------------- #
class _Tagged(str):
    """A token's surface that carries the token's index through the tokenizer (`_line_tokens`)."""


def _line_tokens(tokenizer, line, unoffered=None):
    """[(token, kept)] for one line: the tokens JapaneseTokenizer.tokenize_sentences sees — fugashi + join_affixes,
    the app's own or a variant's — each with the (lemma, reading, surface, orth) tuple the tokenizer yielded for it,
    or None when it dropped it (its symbol filter; a sentence with no Japanese). Read off the tokenizer's own
    output, never re-derived from a copy of its filter: while it runs, join_affixes is wrapped to hand it tokens
    whose surfaces carry their index, and those surfaces come back inside the tuples. `unoffered`, a set, receives
    the index of every token whose one-character word the list can't offer in its sentence (analyzer.unoffered — the
    app's own rule, with the sentence's text)."""
    real, tokens = analyzer.join_affixes, []

    def tagged(words, joins=None, library=True):
        tokens[:] = []
        for index, word in enumerate(real(words, joins, library)):
            surface = _Tagged(word.surface)
            surface.index = index
            if isinstance(word, analyzer.JoinedWord):
                word.surface = surface
                tokens.append(word)
            else:
                tokens.append(Token(surface, word.feature, word.is_unk))
        return list(tokens)

    kept = {}
    with patched(analyzer, "join_affixes", tagged):
        for s_text, toks in tokenizer.tokenize_sentences(line):
            kept.update((t[2].index, t) for t in toks)
            if unoffered is not None:
                unoffered.update(toks[i][2].index for i in analyzer.unoffered(s_text, toks))
    return [(token, kept.get(index)) for index, token in enumerate(tokens)]


def _ja_units(tokenizer, text):
    """Every token of `text`, line by line as the app reads it: surface, lemma and reading (the lemma's, as the
    list keys the word), pos (pos1), joined (an affix join) and fate — "drop" when the app never counts it (the
    tokenizer drops it, or neither lemma nor surface holds Japanese: analyzer.main's accounting, which
    token_index.make_tokenizer mirrors too), "single" when it counts it but its one-character word is no word the
    list can offer there (the rule on, main's default: a one-character word never listed, or a one-kanji word standing
    as a piece of something else — analyzer.unoffered), "" otherwise. `_at` / `_end` locate it in `text` (-1: not
    found)."""
    units, offset = [], 0
    for line in text.split("\n"):
        at = 0
        unoffered = set() if analyzer.SKIP_SINGLE_CHARS else None
        for index, (token, kept) in enumerate(_line_tokens(tokenizer, line, unoffered)):
            feature, surface = token.feature, str(token.surface)
            if kept is not None:
                lemma, reading = str(kept[0]), kept[1]
            else:       # never counted: shown the way the tokenizer would have named it
                lemma = feature.lemma or surface
                lemma = analyzer._sanitize_term(lemma) if analyzer.SANITIZE_JA else lemma
                reading = feature.lForm or feature.kana or ""
            if kept is None or not (_has_target(lemma, "ja") or _has_target(surface, "ja")):
                fate = "drop"
            elif unoffered is not None and index in unoffered:
                fate = "single"
            else:
                fate = ""
            start = line.find(surface, at) if surface else -1
            if start >= 0:
                at = start + len(surface)
            units.append({"surface": surface, "lemma": lemma, "reading": reading, "pos": feature.pos1,
                          "joined": isinstance(token, analyzer.JoinedWord), "fate": fate,
                          "_at": offset + start if start >= 0 else -1,
                          "_end": offset + start + len(surface) if start >= 0 else -1})
        offset += len(line) + 1
    return units


def _span_range(text, span, nth):
    """(start, end) of the nth (1-based) occurrence of `span` in `text`; all of it for an empty span."""
    if not span:
        return 0, len(text)
    start = -1
    for _ in range(max(nth, 1)):
        start = text.find(span, start + 1)
        if start < 0:
            raise ValueError(f"span {span!r} (occurrence {nth}) is not in the text")
    return start, start + len(span)


_MARKS = {"drop": "⊘", "single": "¹"}


def show_units(observed):
    """The units in the notation expectations use — copy it into `expect` and cut what doesn't matter."""
    return " | ".join(f"{u['surface']}[{u['lemma']},{u['reading']},{u['pos']}]" + ("+" if u["joined"] else "")
                      + _MARKS.get(u["fate"], "") for u in observed["units"]) or "(no token)"


_UNIT_RE = re.compile(r"^(.+?)\[([^\[\]]*)\]$")


def parse_units(notation):
    """"surface[lemma,READING,pos] | ..." -> [(surface, lemma, reading, pos, mark)]. Lemma, READING and pos are
    optional, `*` (or nothing) matches anything; a trailing ⊘ says the app must NOT count the token, ¹ that it
    counts it as a one-character word, no mark that it counts it; + (an affix join) is shown, never checked."""
    out = []
    for part in notation.split(" | "):
        part, mark = part.strip(), ""
        while part and part[-1] in "+⊘¹":
            mark = part[-1] if part[-1] != "+" else mark
            part = part[:-1]
        match = _UNIT_RE.match(part)
        surface, tag = (match.group(1), match.group(2)) if match else (part, "")
        bits = [bit if bit not in ("", "*") else None for bit in tag.split(",")] if tag else []
        bits += [None] * (3 - len(bits))
        out.append((surface, bits[0], bits[1], bits[2], mark))
    return out


def _unit_matches(unit, surface, lemma, reading, pos, mark):
    fate_ok = {"⊘": unit["fate"] == "drop", "¹": unit["fate"] == "single"}.get(mark, unit["fate"] != "drop")
    return (unit["surface"] == surface and fate_ok and (lemma is None or unit["lemma"] == lemma)
            and (reading is None or unit["reading"] == reading) and (pos is None or unit["pos"] == pos))


def compare_units(observed, expect):
    problems, units = [], observed["units"]
    if "units" in expect:
        want = parse_units(expect["units"])
        if len(want) != len(units) or not all(_unit_matches(u, *w) for u, w in zip(units, want)):
            problems.append(f"units: expected {expect['units']}, got {show_units(observed)}")
    if "absent" in expect and expect["absent"] != all(u["fate"] == "drop" for u in units):
        problems.append(f"absent: expected {expect['absent']}, got {show_units(observed)}")
    counted = {u["lemma"] for u in units if u["fate"] != "drop"}
    return compare_members(problems, "counted words", counted, expect, "words", "not_words")


@evaluator("tokens_ja", expects=("units", "absent", "words", "not_words"), compare=compare_units, show=show_units)
def tokens_ja(case, ctx):
    """The tokens covering the span, as JapaneseTokenizer tokenizes the case's text line by line (MeCab reads the
    whole line: 3% of sentences tokenize differently alone) — and whether the app counts each one."""
    start, end = _span_range(case.text, case.span, case.nth)
    units = _ja_units(ctx.tokenizer("ja"), case.text)
    covering = [u for u in units if u["_at"] >= 0 and u["_at"] < end and u["_end"] > start]
    return {"units": [{name: value for name, value in u.items() if not name.startswith("_")} for u in covering]}


# --- tokens_zh ------------------------------------------------------------------------------------------------- #
def _zh_render(s_text, tokens, a, b):
    """The counted words of `s_text` overlapping [a, b) joined " / ", with the text the tokenizer dropped between
    them (no CJK ideograph, or kana) in [brackets] — the zh adversary's notation (debug/parsing_suite/zh)."""
    located, pos = [], 0
    for token in tokens:
        surface = token[2]
        found = s_text.find(surface, pos) if surface else -1
        if found < 0:
            continue
        located.append((found, found + len(surface), str(token[0])))
        pos = found + len(surface)
    over = [item for item in located if item[0] < b and item[1] > a]
    low, high = min([a] + [item[0] for item in over]), max([b] + [item[1] for item in over])
    pieces, words, cursor = [], [], low
    for start, end, lemma in over:
        gap = s_text[cursor:start].strip()
        if gap:
            pieces.append(f"[{gap}]")
        pieces.append(lemma)
        words.append(lemma)
        cursor = end
    gap = s_text[cursor:high].strip()
    if gap:
        pieces.append(f"[{gap}]")
    return " / ".join(pieces) if pieces else "(nothing)", words


@evaluator("tokens_zh", expects=("seg", "words", "not_words"),
           compare=lambda observed, expect: compare_members(
               compare_keys(observed, {k: v for k, v in expect.items() if k == "seg"}),
               "counted words", set(observed["words"]), expect, "words", "not_words"),
           show=lambda observed: observed["seg"])
def tokens_zh(case, ctx):
    """What ChineseTokenizer counts for the span, read in the case's script (ctx["script"]) with the case's
    reinforce setting (ctx["reinforce"], pinned). The span is converted in context — the whole text converted, then
    sliced (conversion is length-preserving) — as the tokenizer converts it: 係 alone is 系 under t, 我係 keeps 係."""
    script = ctx.script(case)
    sentences = list(ctx.tokenizer("zh", script).tokenize_sentences(case.text))
    if not case.span:
        rendered = [_zh_render(s_text, toks, 0, len(s_text)) for s_text, toks in sentences]
        return {"seg": " ‖ ".join(seg for seg, _w in rendered) or "(no sentence: dropped)",
                "words": [word for _seg, words in rendered for word in words]}
    start, end = _span_range(case.text, case.span, case.nth)
    want = zh_script.convert(case.text, script)[start:end] if script != "asis" else case.span
    seen = 0
    for s_text, toks in sentences:
        found = s_text.find(want)
        while found >= 0:
            seen += 1
            if seen == case.nth:
                seg, words = _zh_render(s_text, toks, found, found + len(want))
                return {"seg": seg, "words": words}
            found = s_text.find(want, found + 1)
    if not sentences:
        return {"seg": "(no sentence: dropped)", "words": []}
    return {"seg": "(span split: " + " ‖ ".join(s_text for s_text, _t in sentences) + ")", "words": []}


# --- text -------------------------------------------------------------------------------------------------------- #
def compare_text(observed, expect):
    problems = compare_keys(observed, {k: v for k, v in expect.items() if k == "sentences"})
    sentences = observed["sentences"]
    for piece in expect.get("contains", ()):
        if not any(piece in sentence for sentence in sentences):
            problems.append(f"contains: {piece!r} is in no sentence of {short(sentences)}")
    for piece in expect.get("not_contains", ()):
        holding = [sentence for sentence in sentences if piece in sentence]
        if holding:
            problems.append(f"not_contains: {piece!r} is in {short(holding)}")
    return compare_members(problems, "counted words", set(observed["words"]), expect, "words", "not_words")


@evaluator("text", expects=("sentences", "contains", "not_contains", "words", "not_words"), compare=compare_text,
           show=lambda observed: " ⏎ ".join(f"「{s}」" for s in observed["sentences"]) or "(no sentence)")
def text(case, ctx):
    """A file through the app's own reading and splitting: the case's text written as a file (ctx: ext, default
    .txt; encoding, default utf-8 — bytes as a real file holds them; name), then analyzer.extract_text and the
    tokenizer's tokenize_sentences — exactly the token store's path (token_index.make_tokenizer). -> the sentences
    it yields and the words it counts (sorted, once each)."""
    ext = case.ctx.get("ext", ".txt")
    path = ctx.write(case.ctx.get("name") or "case" + ext, case.text.encode(case.ctx.get("encoding", "utf-8")))
    tokenizer = ctx.tokenizer(case.lang, ctx.script(case))
    sentences, words = [], set()
    for s_text, toks in tokenizer.tokenize_sentences(analyzer.extract_text(path, case.lang)):
        sentences.append(s_text)
        words.update(str(lemma) for lemma, _r, surface, _o in toks
                     if _has_target(lemma, case.lang) or _has_target(surface, case.lang))
    return {"sentences": sentences, "words": sorted(words)}


# --- card_key ---------------------------------------------------------------------------------------------------- #
@evaluator("card_key", expects=("key", "via", "word"),
           show=lambda observed: f"{observed['word']} → {observed['key'] or '—'} ({observed['via'] or 'no key'})")
def card_key(case, ctx):
    """Where a card's word lands on the list with no question asked (anki_match.card_key — Junban's placement and
    the report's "In Anki" label): the field read as Junban reads a card (anki_match.card_word in the case's
    language; a Chinese list read in one script converts the lookup key), matched against ctx.index (its rank_of,
    and each row's own word and spelling) with ctx.answers, and the tokenizer of the case's language and script."""
    word = anki_match.card_word(case.text, case.lang)
    script = ctx.script(case)
    if case.lang == "zh" and script != "asis":
        word = zh_script.convert(word, script)
    tokenize = ctx.tokenizer(case.lang, script).tokenize
    index = ctx.index(case)
    verb = analyzer.chinese_verb if case.lang == "zh" else None      # as Junban hands it in
    found, via = anki_match.card_key(word, index.rank_of, case.lang, ctx.answers(case), tokenize, index.words,
                                     index.orths, verb=verb)
    return {"word": word, "key": found, "via": via}


# --- known ------------------------------------------------------------------------------------------------------- #
def _known_rule(sets, word_key):
    """The analyzer's test for a word in a sentence (analyzer.main's aggregation, mirrored): ignored, or its
    (lemma, reading) known, or its lemma known."""
    tuples, lemmas, ignore = sets
    lemma, reading = split_key(word_key)
    return lemma in ignore or (lemma, reading) in tuples or lemma in lemmas


def compare_known(observed, expect):
    problems = []
    for name in ("known", "unknown"):
        if name in expect and sorted(expect[name]) != observed[name]:
            problems.append(f"{name}: expected {short(sorted(expect[name]))}, got {short(observed[name])}")
    if "adds" in expect and sorted(expect["adds"]) != observed.get("adds"):
        problems.append(f"adds: expected {short(sorted(expect['adds']))}, got {short(observed.get('adds'))}")
    return problems


@evaluator("known", expects=("known", "unknown", "adds"), compare=compare_known)
def known(case, ctx):
    """What a KnownWord entry makes known: the case's text (a dictForm, "" for none) loaded as KNOWN with the case's
    other entries and ignore lines, or on top of the snapshot's (ctx) — analyzer.load_known_words, as a run loads
    KnownWord.json. -> which of the "lemma|reading" keys the case asks about (its expect's known + unknown) the
    analyzer counts as known, and `adds`: every lemma the entry alone makes known."""
    sets = ctx.known_sets(case, extra=[case.text] if case.text else ())
    asked = list(case.expect.get("known", ())) + list(case.expect.get("unknown", ()))
    observed = {"known": sorted(k for k in asked if _known_rule(sets, k)),
                "unknown": sorted(k for k in asked if not _known_rule(sets, k))}
    if case.text:
        observed["adds"] = sorted(str(lemma) for lemma in ctx.load_known(case, [case.text])[1])
    return observed


# --- unknowns ---------------------------------------------------------------------------------------------------- #
# How many words of a sentence the learner doesn't know, per consumer. The analyzer's rule is here; 例文 / the
# sentence dictionary (sentence_corpus.collect) and Junban count their own way (Parsing_Robustness_Suite_Scope.md
# §2 L) — their counters are registered from evaluators_<area>.py with @counter("sentence_corpus") /
# @counter("junban") and chosen by ctx["counter"].
UNKNOWN_COUNTERS = {}


def counter(name):
    """Register `count(case, ctx, sets) -> {(lemma, reading), ...}` — the unknown words of case.text as consumer
    `name` counts them; `sets` is ctx.known_sets(case): (known_tuples, known_lemmas, ignore)."""
    def register(count):
        UNKNOWN_COUNTERS[name] = count
        return count
    return register


def target_of(case):
    """A predicate for the word the sentence is an example FOR (ctx["target"]: "lemma|reading", or a bare lemma
    for any reading) — never one of its unknowns."""
    wanted = case.ctx.get("target")
    if not wanted:
        return lambda lr: False
    lemma, reading = split_key(wanted)
    return (lambda lr: lr == (lemma, reading)) if "|" in wanted else (lambda lr: lr[0] == lemma)


def library_of(case, ctx):
    """(uses per word, the list's cut-off) that the learning rule (analyzer.LearningView) reads for a case with a
    snapshot — which compounds are too rare for the list: the snapshot's library_frequency.json (what the last
    Generate counted; it predates compounds, so each compound's own uses come from the measurement under B, frozen
    in data/variants/compounds.json "library"). None without a snapshot: no compound is rare (B's units)."""
    path = ctx.snapshot(case, "library_frequency.json")
    if path is None or case.lang != "ja":
        return None

    def load():
        counts, floor = analyzer.library_counts(path)
        if counts is None:
            return None
        from tests.parsing.variants_ja_tokens import table
        for name, uses in table()["library"].items():
            counts[split_key(name)] = uses
        return counts, floor
    return ctx.memo(("counted", path), load)


@counter("analyzer")
def analyzer_unknowns(case, ctx, sets):
    """analyzer.main's count for a candidate example sentence (inline there, mirrored here step for step): every
    token with Japanese / Chinese in its lemma or surface, not ignored and not known, once per (lemma, reading) — a
    Japanese one-character word only where the list can offer it (analyzer.unoffered, the app's own: a one-kanji
    dictionary word standing on its own; the rule is the pinned default) — read through the list's learning rule
    (analyzer.LearningView, the app's own: a compound too rare for the list is its parts when all are free —
    `library_of`), less the target word and, Japanese, any word read already (through its known word: 利用者 with
    利用 known; or a compound none of whose parts is an unknown)."""
    known_tuples, known_lemmas, ignore = sets
    tokenizer = ctx.tokenizer(case.lang, ctx.script(case))
    japanese = case.lang == "ja"
    is_target = target_of(case)

    def known(lr):
        return lr[0] in ignore or lr in known_tuples or lr[0] in known_lemmas
    view = analyzer.LearningView(*(library_of(case, ctx) or (None, 0)), known=known,
                                 tagger=tokenizer.tagger if japanese else None,
                                 parts=None if japanese else {}, joins=None if japanese else {})
    rule = japanese and analyzer.SKIP_SINGLE_CHARS
    found = set()
    for s_text, toks in tokenizer.tokenize_sentences(case.text):
        skip = analyzer.unoffered(s_text, toks, rule)
        for n, (lemma, reading, surface, _orth) in enumerate(toks):
            if not _has_target(lemma, case.lang) and not _has_target(surface, case.lang):
                continue
            if known((lemma, reading)) or n in skip:
                continue
            found.add((str(lemma), reading))
    units = {unit for lr in found for unit in view.units(lr)
             if not known(unit) and analyzer.single_kind(unit, rule) != 1}
    return {lr for lr in units if not is_target(lr) and not view.readable(lr)}


def compare_unknowns(observed, expect):
    problems = compare_keys(observed, {k: v for k, v in expect.items() if k == "count"})
    if "unknowns" in expect and sorted(expect["unknowns"]) != observed["unknowns"]:
        problems.append(f"unknowns: expected {short(sorted(expect['unknowns']))}, got {short(observed['unknowns'])}")
    return problems


@evaluator("unknowns", expects=("count", "unknowns"), compare=compare_unknowns,
           show=lambda observed: f"{observed['count']}: {', '.join(observed['unknowns']) or '—'}")
def unknowns(case, ctx):
    """The unknown words of the case's sentence under a known set (ctx: snapshot, known, ignore), as the consumer
    ctx["counter"] counts them (default "analyzer") -> {"count", "unknowns": sorted "lemma|reading" keys}."""
    name = case.ctx.get("counter", "analyzer")
    if name not in UNKNOWN_COUNTERS:
        raise KeyError(f"no unknowns counter {name!r} — register one with @counter in evaluators_<area>.py")
    found = UNKNOWN_COUNTERS[name](case, ctx, ctx.known_sets(case))
    keys = sorted(key(lemma, reading) for lemma, reading in found)
    return {"count": len(keys), "unknowns": keys}
