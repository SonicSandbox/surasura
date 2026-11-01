"""Chinese layers — the consumers of jieba's parse the core layers don't reach. Each runs the app's OWN code on a
case and returns what it sees (JSON, never a judgement); where the app keeps the rule inline (analyzer.main's 文
badge gate, reposition.known_test's conversion), the evaluator mirrors it and says so.

    layer            text is                              expect keys                      ctx it reads
    zh_conv          any text                             out                              script (s | t)
    zh_note_lang     one field of a note                  language                         field, fields, languages, notes
    zh_pat_key       a card's word field                  key, reason                      store
    zh_pat_lines     a card's word field                  lines, first, has, not_has,      store, script
                                                          reason
    zh_pat_count     a sentence (the builder's input)     uses, patterns, has, not_has     word (default: span)
    zh_pat_rows      lemmas, space-separated              forms                            store
    zh_key_parity    a line                               same, builder                    script, reinforce
    zh_known_card    a card's word field                  known                            script, known, ignore
    zh_badge         a list word                          badge, ranked, ja_rank           —
    zh_tier          a list word                          tiers                            freq
    zh_cache_sig     a KnownWord dictForm                 build_moves, known_moves         from, to

`store` (the パターン database a lookup reads): "shared" — the shipped Chinese shared data
(release_assets/patterns/patterns_zh_shared.zip, v2 at f996b2c), extracted once per run into the run's scratch
folder — or a store made from rows: a list of words, or {"words": [[word, tag, count]], "patterns": [[word, kind,
item, count, logdice, section]], "aliases": [[spelling, word, count]]}. A store is opened per case and closed before
the case returns: the scorecard's scratch folder must be deletable (Windows keeps an open database locked).

Nothing here writes outside the run's scratch folder, opens the token store, Anki or the network; modules/junban is
imported inside each layer, so a machine without the module loses those cases, not the suite.
"""
import inspect
import json
import os
import re
import tempfile
import zipfile

from app import analyzer, anki_match, modality, token_index, zh_script
from tests.parsing.harness import ROOT, Skip, compare_keys, compare_members, evaluator, short

SHARED_ZIP = os.path.join(ROOT, "release_assets", "patterns", "patterns_zh_shared.zip")


def _boundaries():
    """The zh sentence boundaries as a run reads them (LOGIC, pinned to the frozen settings)."""
    return frozenset(analyzer.LOGIC.get("sentence_boundaries", {}).get("zh", "。！？!?\n；;……｡"))


# --- zh_conv ------------------------------------------------------------------------------------------------ #
@evaluator("zh_conv", expects=("out",), show=lambda observed: observed["out"])
def zh_conv(case, ctx):
    """The zh_script setting's conversion (zh_script.convert, ctx["script"]: s | t) — how every Chinese reader
    under the setting sees the text: content, known words, lists, report sentences. Through Simplified to
    Traditional (t = s2t(t2s(x))), length-preserving, OpenCC's standard forms."""
    return {"out": zh_script.convert(case.text, ctx.script(case))}


# --- zh_note_lang ------------------------------------------------------------------------------------------- #
@evaluator("zh_note_lang", expects=("language",),
           show=lambda observed: f"note type language = {observed['language']!r}")
def zh_note_lang(case, ctx):
    """backfill.note_language (Patterns_Chinese_Spec D7, S3): the language Backfill reads a note type as — the
    user's choice (ctx["languages"], the junban_backfill_note_languages setting; default none), else Japanese by its
    notes' kana (most notes since 2026-09-29, ZH-NOTE-KANA), else not set (never filled). The note type "Chinese Vocab"
    holds the case's note — its field ctx["field"] (default "Hanzi") holds the case's text, ctx["fields"] its other
    fields — and ctx["notes"], its other notes in scope, each {field: value}: the flat shape gather hands over
    (reposition._note_values)."""
    from modules.junban import backfill
    fields = {str(name): str(value) for name, value in case.ctx.get("fields", {}).items()}
    fields[case.ctx.get("field", "Hanzi")] = case.text
    notes = [{"fields": fields}] + [{"fields": {str(name): str(value) for name, value in note.items()}}
                                    for note in case.ctx.get("notes", ())]
    settings = {"junban_backfill_note_languages": dict(case.ctx.get("languages", {}))}
    return {"language": backfill.note_language("Chinese Vocab", notes, settings)}


# --- the パターン stores ------------------------------------------------------------------------------------- #
def _extract_shared(ctx):
    with zipfile.ZipFile(SHARED_ZIP) as archive:
        return ctx.write("patterns_zh_shared.db", archive.read("patterns_zh_shared.db"))


def _build_store(ctx, spec):
    """A Chinese store made from rows, the way test_patterns_zh_lookup.py makes its exact stores."""
    from modules.junban import patterns_build as pb
    if isinstance(spec, list):
        spec = {"words": [[word, "n", 40] for word in spec]}
    words = [tuple(row) for row in spec.get("words", ())]
    lemmas = [(word, "", word, tag, count) for word, tag, count in words]
    alias = [(word, word, "", count) for word, _tag, count in words] + \
        [(spelling, word, "", count) for spelling, word, count in spec.get("aliases", ())]
    rows = [(word, "", kind, item, count, logdice, section)
            for word, kind, item, count, logdice, section in spec.get("patterns", ())]
    path = os.path.join(tempfile.mkdtemp(prefix="zh_store_", dir=ctx.scratch), "patterns_zh.db")
    pb.write_rows(path, lemmas, alias, rows, {"floor": 1, "tokens": 1000, "language": "zh"})
    return path


def _store_path(case, ctx):
    spec = case.ctx.get("store", "shared")
    if spec == "shared":
        return ctx.memo(("zh_store", "shared"), lambda: _extract_shared(ctx))
    return ctx.memo(("zh_store", json.dumps(spec, ensure_ascii=False, sort_keys=True)),
                    lambda: _build_store(ctx, spec))


def _open_store(case, ctx):
    """The case's Chinese store, opened as the app opens it — skipped (Skip) while the shared data in
    release_assets predates the code's builder, as the Japanese cases reading installed databases are: the app
    refuses it until it is rebuilt and published again, and the case runs again by itself then."""
    from modules.junban.patterns_store import Store, open_store, required_builder
    path = _store_path(case, ctx)
    store = open_store(path, language="zh", quiet=True)
    if store is None:
        if case.ctx.get("store", "shared") == "shared":
            plain = Store(path)
            try:
                built = plain.builder_version()
            finally:
                plain.close()
            need = required_builder("zh")
            if built is not None and built < need:
                raise Skip(f"the shared Chinese パターン data (release_assets/patterns/patterns_zh_shared.zip) predates "
                           f"builder {need} — rebuild and publish it, and this case runs again")
        raise RuntimeError(f"the Chinese store {case.ctx.get('store', 'shared')!r} did not open (another "
                           "language, or an older builder)")
    return store


# --- zh_pat_key --------------------------------------------------------------------------------------------- #
@evaluator("zh_pat_key", expects=("key", "reason"),
           show=lambda observed: f"key {observed['key']}" if observed["key"] else f"refused: {observed['reason']}")
def zh_pat_key(case, ctx):
    """patterns_zh.resolve_key — a Chinese card's word to its パターン key (Patterns_Chinese_Spec §7): the field as
    Backfill reads a card (normalize_word), the kana guard (S4), to_simplified, jieba.cut; one word or a compound
    the store keeps whole, else a spelling the corpus wrote (the alias table), else "phrase" / "not found"."""
    from modules.junban import patterns_zh
    store = _open_store(case, ctx)
    try:
        key, reason = patterns_zh.resolve_key(anki_match.normalize_word(case.text), store)
    finally:
        store.close()
    return {"key": key[0] if key else "", "reason": reason or ""}


# --- zh_pat_lines ------------------------------------------------------------------------------------------- #
_DIV_RE = re.compile(r'<div class="([^"]*)">(.*?)</div>', re.S)


def _lines_text(observed):
    return [line.split(": ", 1)[1] if ": " in line else line for line in observed["lines"]]


def compare_lines(observed, expect):
    problems = compare_keys(observed, {k: v for k, v in expect.items() if k in ("lines", "reason")})
    texts = _lines_text(observed)
    if "first" in expect and not (texts and texts[0].startswith(expect["first"])):
        problems.append(f"first: line 1 should start {expect['first']!r}, got {short(texts[:1])}")
    field = " ‖ ".join(texts)
    missing = [piece for piece in expect.get("has", ()) if piece not in field]
    if missing:
        problems.append(f"has: {short(missing)} not in the field {short(field)}")
    extra = [piece for piece in expect.get("not_has", ()) if piece in field]
    if extra:
        problems.append(f"not_has: {short(extra)} in the field {short(field)}")
    return problems


@evaluator("zh_pat_lines", expects=("lines", "first", "has", "not_has", "reason"), compare=compare_lines,
           show=lambda observed: " ‖ ".join(_lines_text(observed)) or f"(nothing: {observed['reason']})")
def zh_pat_lines(case, ctx):
    """patterns_zh.from_sources — the パターン field Backfill writes on a Chinese card, line by line ("kind: text",
    one per <div>, markup gone), in the card's own script (ctx["script"] is the user's zh_script), from ctx["store"]
    (default the shipped shared data). `first` is what line 1 starts with; `has` / `not_has` pieces of the field."""
    from modules.junban import patterns_zh
    store = _open_store(case, ctx)
    try:
        html, reason, _source = patterns_zh.from_sources(anki_match.normalize_word(case.text), [("shared", store)],
                                                         ctx.script(case))
    finally:
        store.close()
    lines = [f"{kind.split()[0].replace('pat-', '')}: {re.sub(r'<[^>]+>', '', body).strip()}"
             for kind, body in _DIV_RE.findall(html or "")]
    return {"lines": lines, "reason": reason or ""}


# --- zh_pat_count ------------------------------------------------------------------------------------------- #
def compare_count(observed, expect):
    problems = compare_keys(observed, {k: v for k, v in expect.items() if k in ("uses", "patterns")})
    return compare_members(problems, "patterns", set(observed["patterns"]), expect, "has", "not_has")


@evaluator("zh_pat_count", expects=("uses", "patterns", "has", "not_has"), compare=compare_count,
           show=lambda observed: f"{observed['word']} ×{observed['uses']}: "
                                 + (", ".join(f"{k}×{n}" if n > 1 else k for k, n in observed["patterns"].items())
                                    or "no pattern"))
def zh_pat_count(case, ctx):
    """What the Chinese パターン builder counts for one word of the text (patterns_zh.iter_tokens + count — its rules,
    before any floor): the word's uses and its patterns as "RULE:item" → times — Q:本 a measure word, P:跟 a coverb,
    W:{w}了 a form (a separable verb's split is W:洗了个澡), VO / AN / SP / AD / DV pairings, F1–F5 frames, cand.
    ctx["word"] is the word (Simplified, as keyed), default the span."""
    from modules.junban import patterns_build, patterns_zh
    word = case.ctx.get("word") or case.span
    counts = patterns_build.Counts()
    patterns_zh.count(list(patterns_zh.iter_tokens(case.text, _boundaries())), counts)
    x = counts.ids.get((word, ""))
    patterns = {}
    if x is not None:
        for (target, key), n in counts.pattern.items():
            if target == x:
                name = f"{key[0]}:{key[2]}"
                patterns[name] = patterns.get(name, 0) + n
    return {"word": word, "uses": counts.word[x] if x is not None else 0, "patterns": dict(sorted(patterns.items()))}


# --- zh_pat_rows -------------------------------------------------------------------------------------------- #
@evaluator("zh_pat_rows", expects=("forms",),
           show=lambda observed: " · ".join(f"{lemma}: " + (", ".join(forms) or "—")
                                           for lemma, forms in observed["forms"].items()))
def zh_pat_rows(case, ctx):
    """The form rows a Chinese store holds (Store.patterns(lemma, "", "form")) for each lemma of the text
    (space-separated) — the DATA a card of that word would read, whatever the builder does today."""
    store = _open_store(case, ctx)
    try:
        return {"forms": {lemma: [f"{row[0]} ×{row[1]}" for row in store.patterns(lemma, "", "form")]
                          for lemma in case.text.split()}}
    finally:
        store.close()


# --- zh_key_parity ------------------------------------------------------------------------------------------ #
@evaluator("zh_key_parity", expects=("same", "builder"),
           show=lambda observed: ("same: " if observed["same"] else "DIFFERENT: builder ") + observed["builder"]
                                 + ("" if observed["same"] else "  ≠ analyzer " + observed["analyzer"]))
def zh_key_parity(case, ctx):
    """The key-space contract (Patterns_Chinese_Spec §8.2; test_the_zh_builder_keys_every_word_exactly_as_the_
    analyzer_does; exp7_contract.py): the パターン builder's words for the text (patterns_zh.iter_tokens) against
    the analyzer's lemmas (ChineseTokenizer) — under s both Simplified; under t the builder's cut sliced from the
    line converted to Traditional, in context (test_traditional_text_is_keyed_through_simplified); as-is as
    written. Reinforce is the case's (pinned): the builder cuts with the same process-wide jieba."""
    from modules.junban import patterns_zh
    script = ctx.script(case)
    built = []
    for line in case.text.split("\n"):
        out = zh_script.to_traditional(zh_script.to_simplified(line)) if script == "t" else line
        pos = 0
        for sentence in patterns_zh.iter_tokens(line, _boundaries()):
            for tok in sentence:
                if tok.key:
                    built.append(out[pos:pos + len(tok.text)] if script == "t"
                                 else tok.orig if script == "asis" else tok.key)
                pos += len(tok.text)
    lemmas = [str(t[0]) for _s, toks in ctx.tokenizer("zh", script).tokenize_sentences(case.text) for t in toks]
    return {"builder": " / ".join(built), "analyzer": " / ".join(lemmas), "same": built == lemmas}


# --- zh_known_card ------------------------------------------------------------------------------------------ #
@evaluator("zh_known_card", expects=("known",),
           show=lambda observed: f"{observed['word']} known: {observed['known']}")
def zh_known_card(case, ctx):
    """Junban's "known" tier and Backfill's skip for a Chinese card: reposition.known_test's zh branch, mirrored
    (known_test itself reads the live User Files and the token store) — the card's field normalized, converted to
    the user's script (ctx["script"]), then reposition.is_known_word itself over the case's known sets
    (ctx["known"], ["ignore"], a snapshot), with no tokenizer (Chinese in v1)."""
    from modules.junban import reposition
    tuples, lemmas, ignore = ctx.known_sets(case)

    def known(lemma, reading):
        return lemma in ignore or lemma in lemmas or (lemma, reading) in tuples
    word = zh_script.convert(anki_match.normalize_word(case.text), ctx.script(case))
    return {"word": word, "known": reposition.is_known_word(word, known, lemmas, ignore, None)}


# --- zh_badge ----------------------------------------------------------------------------------------------- #
_BADGE_GATE = "spoken_ranks() if language == 'ja' else {}"


@evaluator("zh_badge", expects=("badge", "ranked", "ja_rank"),
           show=lambda observed: f"badge={observed['badge']!r} (rank {observed['rank']}; the Japanese table has "
                                 f"it at {observed['table_rank']})")
def zh_badge(case, ctx):
    """The 文 (reading-word) badge a run of the case's language gives a word — analyzer.main's inline rule,
    mirrored: the spoken-rank table (reference_data.spoken_ranks, Japanese words') is loaded for a Japanese run
    only (ENGINE 14), and modality.classify judges the rank on the strongest library evidence for a badge (met 100
    times in 5 of 5 series, never heard). The mirror checks analyzer.main still holds the gate it copies and fails
    loudly when it doesn't. `ja_rank` is the Japanese rank the run applies; `ranked` whether the word has a rank of
    its own language at all."""
    from app import reference_data
    if _BADGE_GATE not in inspect.getsource(analyzer.main):
        raise AssertionError(f"analyzer.main no longer holds {_BADGE_GATE!r} — revisit the zh_badge mirror")
    table = reference_data.spoken_ranks()
    ranks = table if case.lang == "ja" else {}
    rank = ranks.get(case.text)
    badge = None
    if ranks:
        badge = modality.classify(rank, 100, spoken_count=0, series_count=5, library_series=5,
                                  listening_hours_total=100.0, config=analyzer.LOGIC.get("modality", {}))
    return {"badge": badge, "rank": rank, "ranked": rank is not None, "ja_rank": rank if case.lang != "ja" else None,
            "table_rank": table.get(case.text)}


# --- zh_tier ------------------------------------------------------------------------------------------------ #
@evaluator("zh_tier", expects=("tiers",), show=lambda observed: ", ".join(observed["tiers"]) or "Outside")
def zh_tier(case, ctx):
    """analyzer.get_tier_label — the frequency-list tiers the report shows for a word, from ctx["freq"] ({list name:
    {word: rank}}, as load_yomitan_frequency_list gives them), with the analyzer's own spelling-alias fallback."""
    return {"tiers": [f"{source}:{tier}" for source, tier in analyzer.get_tier_label(case.text,
                                                                                      case.ctx.get("freq", {}))]}


# --- zh_cache_sig ------------------------------------------------------------------------------------------- #
@evaluator("zh_cache_sig", expects=("build_moves", "known_moves"),
           show=lambda observed: f"token store {'rebuilds' if observed['build_moves'] else 'kept'}, known words "
                                 f"{'re-read' if observed['known_moves'] else 'served from cache'}")
def zh_cache_sig(case, ctx):
    """Do the Chinese caches notice a settings change from ctx["from"] to ctx["to"] ({"reinforce": bool, "script":
    asis | s | t})? The token store keys on token_index.build_signature("zh", reinforce, script); the known-words
    cache on token_index.known_signature(KnownWord.json, script) — every caller passes the file and the effective
    script (analyzer, indexer, dashboard, sentence_corpus). The text is the KnownWord dictForm the cache holds."""
    path = ctx.write("KnownWord.json", json.dumps({"words": [{"dictForm": case.text, "knownStatus": "KNOWN"}]},
                                                  ensure_ascii=False))
    sides = []
    for side in (case.ctx.get("from", {}), case.ctx.get("to", {})):
        script = zh_script.effective("zh", side.get("script", "asis"))
        sides.append((token_index.build_signature("zh", bool(side.get("reinforce")), script),
                      token_index.known_signature(path, script)))
    return {"build_moves": sides[0][0] != sides[1][0], "known_moves": sides[0][1] != sides[1][1]}
