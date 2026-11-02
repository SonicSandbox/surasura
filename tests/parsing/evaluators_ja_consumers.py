"""Layers for the Japanese consumers of the parse — what Junban, the report's "In Anki" label, パターン, 例文, the
sentence dictionary and the caches do with a card or a sentence. Each runs the app's OWN functions on in-memory or
snapshot inputs, returns JSON, never writes outside the run's scratch folder, and never needs Anki, the network or
the live token store (docs/agent instructions/Parsing_Suite.md §6).

    layer       text is                          expect keys
    junban      the card's word field, raw       tier, key, via, row, why, known, phrase, phrase_uses, unknowns,
                                                 suggest, library_key, blockers
    label       the card's word field, raw       keys, has_keys, no_keys, rows, marks, not_marks
    patterns    the card's word                  key, reason, source, lines, has, lacks, shown, thin
    reibun      the card's word                  key, found, sentences, first, reason, has, lacks
    dictionary  the word's lemma                 terms, has, lacks
    cache       the cache key's name             moves

Unknowns counters for the core `unknowns` layer (ctx["counter"]): "sentence_corpus" (例文 and the sentence
dictionary) and "junban" (the count beside a card).

ctx keys these layers read, beyond the core ones (snapshot, list, list_file, answers, known, ignore, target):
    sentence      junban: the card's Sentence field, raw (<b> included)
    freqsort      junban: the card's FreqSort
    phrase_uses   junban: how often the library meets the card's run of words — what `anki_match.phrase_places`
                  finds in the live token store, which no snapshot holds, so it is FROZEN per case (the adversary's
                  2026-09-26 measurement, read-only)
    documents     junban (phrase uses over these texts), patterns (a database built from them), reibun (the
                  library): each a file / document, in study order
    unlisted      junban: "journey" — a word the list cut off is placed by the snapshot's library map
    ready_first   junban: True — run the panel's "i+1 first" pass on the card
    cards         label: more card word fields in the same backlog
    reading       patterns, reibun: the card's reading (ExpressionReading); dictionary: the word's lForm
    floor         patterns: the built database's word floor (default 1)
    db            patterns: "installed" — the user's installed databases, read-only (they change when rebuilt);
                  "installed:<name>" (conversational, balanced, shared, library) — that one alone. A case whose
                  databases an older builder wrote is skipped, saying so (`_stale_installed`): the app refuses them;
                  so is one with none installed (under pytest the roaming root is the test root's, never the user's)
    fields        reibun: the card's other fields (its own sentences are never picked)
    orths         dictionary: {spelling: uses}, as sentence_corpus.collect gathers them
    change        cache: what changes
"""
import contextlib
import csv
import json
import os
import re
from collections import Counter
from unittest import mock

from app import analyzer, anki_match, path_utils, settings_manager, token_index
from app.unicode_ranges import KANA
from tests.parsing import harness
from tests.parsing.evaluators import counter, library_of, target_of
from tests.parsing.harness import compare_keys, compare_members, evaluator, patched, split_key


def _has(text):
    return analyzer.has_target_language(str(text), "ja")


def _tagger(ctx):
    return ctx.tokenizer("ja").tagger


@contextlib.contextmanager
def _shared_tagger(ctx):
    """`fugashi.Tagger()` hands back the run's own tagger for the duration — sentence_corpus.collect makes a fresh
    one for its see-through test (`_readable`), and one per case would cost more than the case. Same dictionary,
    same answers. The run's fugashi tagger (analyzer.Tagger's `_tagger`), which the new analyzer.Tagger wraps."""
    import fugashi
    tagger = _tagger(ctx)._tagger
    with patched(fugashi, "Tagger", lambda *args, **kwargs: tagger):
        yield


def _frozen_settings():
    """The whole frozen settings.json (harness.SETTINGS_SNAPSHOT) as the app's settings_manager loads it — the same
    file harness.frozen_logic reads; never the live one."""
    path = os.path.join(harness.DATA, harness.SETTINGS_SNAPSHOT, "settings.json")
    with mock.patch.object(settings_manager, "get_settings_path", lambda: path), harness.quiet():
        return settings_manager.load_settings()


# --- lists and the library map ------------------------------------------------------------------------------- #
def _index(case, ctx, default_file):
    """(Index, path of the library map or None): the list a consumer reads, indexed by anki_match.build_index —
    ctx["list"] inline (words or Word / Orth / Forms / Reading rows), else the snapshot's ctx["list_file"] (default:
    `default_file`)."""
    rows = case.ctx.get("list")
    snap_map = ctx.snapshot(case, "library_frequency.json")
    if rows is not None:
        path = ctx.write("list.csv", harness._list_csv(rows))
        return anki_match.build_index(path, language="ja"), snap_map
    name = case.ctx.get("list_file", default_file)
    path = ctx.snapshot(case, f"{name}_learning_list.csv")
    if path is None:
        return anki_match.Index({}, {}, {}, {}), None
    return ctx.memo(("index", path), lambda: anki_match.build_index(path, language="ja")), snap_map


def _list_rows(case, ctx, default_file="priority"):
    """The list's rows as dicts (Word, Orth, Forms, Reading), in list order — for the label's template mirror."""
    rows = case.ctx.get("list")
    if rows is not None:
        return [{"Word": row} if isinstance(row, str) else dict(row) for row in rows]
    path = ctx.snapshot(case, f"{case.ctx.get('list_file', default_file)}_learning_list.csv")
    if path is None:
        return []

    def read():
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return [{name: row.get(name) or "" for name in ("Word", "Orth", "Forms", "Reading")}
                    for row in csv.DictReader(handle)]
    return ctx.memo(("rows", path), read)


def _library_entries(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("words") or {}


# --- junban: where a new card goes ---------------------------------------------------------------------------- #
def _junban_show(observed):
    bits = [observed["tier"] or "—"]
    if observed["key"]:
        bits.append(f"{observed['key']} ({observed['via']}, #{observed['rank']} {observed['row']})")
    if observed["phrase"]:
        bits.append("phrase " + "+".join(observed["phrase"])
                    + (f" {observed['phrase_uses']}×" if observed["phrase_uses"] is not None else ""))
    bits.append(f"known={observed['known']}")
    if observed["unknowns"] is not None:
        bits.append(f"unknowns={observed['unknowns']}")
    if observed["suggest"]:
        bits.append(f"asks {observed['suggest']}")
    if observed["library_key"]:
        bits.append(f"library {observed['library_key']}")
    if observed["blockers"] is not None:
        bits.append(f"i+1 first: waits for {'、'.join(observed['blockers']) or 'nothing'}")
    return " · ".join(bits)


@evaluator("junban", expects=("tier", "key", "via", "row", "why", "known", "phrase", "phrase_uses", "unknowns",
                              "suggest", "library_key", "blockers"),
           show=_junban_show)
def junban(case, ctx):
    """Where Junban puts one new card — modules/junban/reposition._plan_scope's steps with the user's settings
    ("List first", phrases on), in its order: the card's list key (anki_match.card_key: exact keys, the user's "yes",
    one word + one ending) -> tier "list"; else ("journey" only) the library map; else a phrase the library meets as
    often as the list's own cut-off (L9: anki_match.phrase_lemmas; the floor as _plan_scope reads it —
    library_floor, never below the list's lowest count) -> "phrase"; then reposition._place_the_rest ITSELF, its
    known sets being the case's (`_known_sets` would open the token store): known (last), or by the card's own
    sentence -> "i+1" / "multi" / "rest".

    text: the card's word field, raw (anki_match.card_word, as Junban reads a note). ctx: snapshot; list /
    list_file (default: the progressive list — Junban's default order, "content"); answers; known / ignore;
    sentence; freqsort; phrase_uses (frozen, see the module docstring) or documents (phrase uses counted over those
    texts by anki_match.find_phrases); unlisted: "journey"; ready_first: True — the panel's "i+1 first"
    (reposition._ready_first_pass ITSELF, the card alone in the backlog, so a word it needs has no card to bring).
    -> {tier, key, via, rank, row (the list row the key reaches, Word|Reading), why (the preview's column: "list
    #1,727", "known", "i+1", "2 unknown", "FreqSort 12,034", "no sentence", "phrase · 72×"), known (reposition.is_known_word —
    Junban's known tier and Backfill's known skip, asked whatever the key), phrase (the card's lemma run when it is
    two or more words), phrase_uses, unknowns (the count beside the card's word in its sentence: 0 is i+1, None no
    sentence), suggest (the "Same word?" question), library_key, blockers (i+1 first: the later list words the
    card's sentence waits for; None when not asked)}."""
    from modules.junban import reposition
    word = anki_match.card_word(case.text, "ja")
    index, map_path = _index(case, ctx, "progressive")
    rank_of = index.rank_of
    answers = ctx.answers(case)
    tokenize = ctx.tokenizer("ja").tokenize
    sets = ctx.known_sets(case)
    known_tuples, known_lemmas, ignore = sets

    # Settings' "Idioms and set phrases on your list" as the frozen settings have it (on): the list's phrase rows take
    # a phrase card by its lemma run, and a phrase card waiting for a new word is no i+1 card (PHRASE-ROWS).
    settings = {"logic": {"phrase_rows": analyzer.LOGIC.get("phrase_rows", True)}}
    key, via = anki_match.card_key(word, rank_of, "ja", answers, tokenize, index.words, index.orths,
                                   phrases=settings["logic"]["phrase_rows"])
    card = {"card_id": 1, "note": 1, "word": word, "key": key}
    tier, library_key, library_numbers = ("list" if key else ""), "", None
    if via == "yes":
        card["matched"] = True
    if not key and case.ctx.get("unlisted") == "journey" and map_path:
        library = ctx.memo(("library", map_path), lambda: anki_match.load_library(map_path, "ja"))
        library_word = anki_match.card_key(word, library, "ja", None, tokenize)[0]
        if library_word:
            tier = card["tier"] = "library"
            library_numbers = library[library_word]
            library_key = next((name for name, entry in ctx.memo(("entries", map_path),
                                                                  lambda: _library_entries(map_path)).items()
                                if (entry[4], entry[5], entry[0]) == library_numbers
                                and library_word in (name.split("|")[0], entry[6])), "")
    phrase = list(anki_match.phrase_lemmas([word], tokenize).get(word, ()))
    uses = None
    if phrase:
        if "documents" in case.ctx:
            paths = [path for path, _text in _document_files(case, ctx)]
            numbers = anki_match.find_phrases({word: tuple(phrase)}, [(path, 10) for path in paths],
                                              _file_tokens(ctx, paths).__getitem__).get(word)
            uses = numbers[2] if numbers else 0
        else:
            uses = case.ctx.get("phrase_uses")
    if not tier and phrase and uses:
        if case.ctx.get("unlisted") == "journey":
            tier = card["tier"] = "library"             # "journey": every phrase the library meets is placed
        else:                                           # "List first": held to the list's own bar
            floor = anki_match.library_floor(map_path) if map_path else case.ctx.get("floor")
            listed = [numbers[2] for numbers in index.journey_of.values()]
            if floor is not None and listed:
                floor = max(floor, min(listed))
            if floor is not None and uses >= floor:
                tier = card["tier"] = "phrase"
    fields = {"Sentence": case.ctx.get("sentence", "")}
    if case.ctx.get("freqsort") is not None:
        fields["FreqSort"] = str(case.ctx["freqsort"])
    with patched(reposition, "_known_sets", lambda language, settings: sets):
        reposition._place_the_rest([card], {1: {"fields": fields}}, "ja", settings, rank_of=rank_of, answers=answers,
                                   tokenize=tokenize, library=library_of(case, ctx))
    placed = card.get("fallback") if (key or tier in ("phrase", "library")) else None
    by_sentence = placed or ((card.get("tier"), card.get("sort"), card.get("why")) if card.get("sort") is not None
                             else (None, None, None))
    if not tier or card.get("tier") == "known":
        tier = card.get("tier") or ""
    unknowns = None
    if by_sentence[0] == "i+1":
        unknowns = 0
    elif by_sentence[0] == "multi":
        unknowns = by_sentence[1][0]
    found = (card.get("check") or {}).get("found")
    blockers = None
    if case.ctx.get("ready_first") and key:
        # as _plan_scope sorts a list card, then the pass itself (its tagger and known sets the run's / the case's)
        card["sort"] = reposition.journey_sort("content", index.journey_of.get(key), rank_of[key])
        card["why"] = f"list #{rank_of[key] + 1:,}"
        tokenizer = ctx.tokenizer("ja")
        with patched(reposition, "_known_sets", lambda language, settings: sets), \
                patched(analyzer, "JapaneseTokenizer", lambda: tokenizer):
            reposition._ready_first_pass([card], {1: {"fields": fields}}, rank_of, index.journey_of, "content",
                                         "ja", {}, library_of(case, ctx))
        # the pass writes what a card needs into its "why": "waits for A、B · …" (held) or "after A、B · …"
        why, blockers = card.get("why") or "", []
        for lead in ("waits for ", "after "):
            if why.startswith(lead):
                blockers = why[len(lead):].split(" · ")[0].split("、")
                break

    def known(lemma, reading):
        return lemma in ignore or lemma in known_lemmas or (lemma, reading) in known_tuples
    row = ""
    if key:
        rows = _list_rows(case, ctx, "progressive")
        if 0 <= rank_of[key] < len(rows):
            row = _row_name(rows[rank_of[key]])
    # the preview's "why" column, in the app's own words (_plan_scope's for the list / library / phrase tiers, with no
    # file names to hand: reposition._where names the file by number)
    if tier == "list":
        why = f"list #{rank_of[key] + 1:,}" + (reposition.MATCHED_BY_YOU if card.get("matched") else "")
    elif tier == "library" and library_numbers:
        why = reposition._where(library_numbers, [])
    elif tier in ("phrase", "library"):
        why = f"phrase · {uses:,}×"
    else:
        why = card.get("why") or ""
    if blockers:
        why = f"waits for {'、'.join(blockers)} · {why}"
    return {"tier": tier, "key": key, "via": via, "rank": rank_of[key] + 1 if key else None, "row": row, "why": why,
            "known": bool(reposition.is_known_word(word, known, known_lemmas, ignore, tokenize, known_tuples)),
            "phrase": phrase, "phrase_uses": uses, "unknowns": unknowns,
            "suggest": found.key if found is not None and not card.get("matched") else "",
            "library_key": library_key, "blockers": blockers}


def _document_files(case, ctx):
    """[(path, text)] — ctx["documents"] written as .txt files in the scratch folder (a document is a file)."""
    return [(ctx.write(f"doc{number:03d}.txt", text), text) for number, text in enumerate(case.ctx["documents"], 1)]


def _file_tokens(ctx, files):
    """{path: [(sentence, [[lemma, reading, surface, orth], ...]), ...]} — each file read as the token store reads
    it (token_index.make_tokenizer: analyzer.extract_text, then tokenize_sentences)."""
    tokenizer = ctx.tokenizer("ja")
    return {path: [(text, [list(token) for token in tokens])
                   for text, tokens in tokenizer.tokenize_sentences(analyzer.extract_text(path, "ja"))]
            for path in files}


# --- label: the report's "In Anki" mark ---------------------------------------------------------------------- #
_JS_KANA_ONLY = re.compile(f"^[{KANA}]+$")    # foldKana's /^[\u3040-\u30ff\u31f0-\u31ff\u{1aff0}-\u{1b16f}]+$/u


def _js_fold(text):
    """templates/web_app.html foldKana: katakana to hiragana, only for a word written in kana alone."""
    if not _JS_KANA_ONLY.match(text):
        return text
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text)


def _js_row_id(row):
    """templates/web_app.html ankiRowId: a row by its Word and Reading."""
    reading = row.get("Reading")
    return f"{row.get('Word')}|{reading if isinstance(reading, str) else ''}"


def _js_owners(rows):
    """MIRROR of templates/web_app.html `ankiOwners()` (JavaScript — this suite has no JS engine): which row each
    spelling belongs to — every row's Orth then Word, in list order, before any row's Forms, then each kana
    spelling's hiragana fold where no row holds it; a one-character spelling (Array.from: code points) only as the
    row's own Word. Japanese. Keep it in step with the template."""
    owners = {}

    def claim(raw, row, lemma):
        key = str(raw or "").strip()
        if not key or key in owners or (len(key) == 1 and key != lemma):
            return
        owners[key] = _js_row_id(row)
    for row in rows:
        lemma = row["Word"].strip() if isinstance(row.get("Word"), str) else ""
        claim(row.get("Orth"), row, lemma)
        claim(row.get("Word"), row, lemma)
    for row in rows:
        for form in (row["Forms"].split("|") if isinstance(row.get("Forms"), str) else []):
            claim(form, row, None)
    for key, owner in list(owners.items()):
        folded = _js_fold(key)
        if folded != key and folded not in owners:
            owners[folded] = owner
    return owners


def _in_anki(row, keys, owners):
    """MIRROR of templates/web_app.html `inAnkiBacklog(data)`: a row is marked when its Word, Orth or a Forms entry,
    trimmed — or that spelling's fold — is a key AND a spelling the row owns (`_js_owners`)."""
    row_id = _js_row_id(row)
    forms = row["Forms"].split("|") if isinstance(row.get("Forms"), str) else []
    for raw in [row.get("Word"), row.get("Orth")] + forms:
        key = str(raw or "").strip()
        if key and any(spelling in keys and owners.get(spelling) == row_id for spelling in (key, _js_fold(key))):
            return True
    return False


def _row_name(row):
    return f"{row['Word']}|{row['Reading']}" if row.get("Reading") else row["Word"]


def compare_label(observed, expect):
    problems = compare_keys(observed, {k: v for k, v in expect.items() if k in ("keys", "rows")})
    compare_members(problems, "keys", set(observed["keys"]), expect, "has_keys", "no_keys")
    return compare_members(problems, "marked rows", set(observed["rows"]), expect, "marks", "not_marks")


@evaluator("label", expects=("keys", "has_keys", "no_keys", "rows", "marks", "not_marks"), compare=compare_label,
           show=lambda observed: f"keys {', '.join(observed['keys']) or '—'} → rows {', '.join(observed['rows']) or '—'}")
def label(case, ctx):
    """The report's "In Anki" label for a backlog holding the case's card (text: its word field, raw; ctx["cards"]:
    more cards in the same backlog): app/static_html_generator.anki_backlog_keys ITSELF — each card keyed as the
    Anki sync keys it (anki_sync._backlog_entry: card_word + the kana fold), read through the dictionary
    (_dictionary_keys), the user's "yes" answers (_confirmed_keys) — fed this backlog, the case's answers
    (ctx answers / the snapshot's junban_pairs.json) in place of the User Files ones, the run's tokenizer in place of
    a fresh one, and the list the report shows (ctx list, else the snapshot's priority list; none without either).
    Then the rows of that list those keys MARK: that test is templates/web_app.html's `inAnkiBacklog` over
    `ankiOwners`, JavaScript this suite cannot run, so it is mirrored here (`_js_owners`, `_in_anki`) — a case that
    depends on which rows are marked depends on the mirror, and says so.
    -> {keys: every key injected (sorted), rows: the marked rows as Word|Reading, in list order}."""
    from app import anki_sync, static_html_generator
    notes = {}
    for number, raw in enumerate([case.text] + list(case.ctx.get("cards", ())), 1):
        entry = anki_sync._backlog_entry({"fields": {"Expression": {"value": raw, "order": 0}}}, [], "ja")
        if entry is not None:
            notes[str(number)] = entry
    backlog = {"version": 1, "notes": notes}
    answers = ctx.answers(case)
    tokenizer = ctx.tokenizer("ja")
    if case.ctx.get("list") is not None:
        list_path = ctx.write("priority_learning_list.csv", harness._list_csv(case.ctx["list"]))
    else:
        list_path = ctx.snapshot(case, "priority_learning_list.csv")
    with patched(anki_sync, "load_backlog", lambda language: backlog), \
            patched(static_html_generator, "_pair_answers", lambda language: answers), \
            patched(analyzer, "JapaneseTokenizer", lambda: tokenizer):
        keys = set(static_html_generator.anki_backlog_keys("ja", {"anki_backlog_on_generate": True}, list_path))
    rows = _list_rows(case, ctx)
    owners = (_js_owners(rows) if case.ctx.get("list") is not None
              else ctx.memo(("owners", list_path), lambda: _js_owners(rows)))
    return {"keys": sorted(keys), "rows": [_row_name(row) for row in rows if _in_anki(row, keys, owners)]}


# --- unknowns counters: 例文 / the sentence dictionary, and Junban ---------------------------------------------- #
@counter("sentence_corpus")
def sentence_corpus_unknowns(case, ctx, sets):
    """例文 and the sentence dictionary's count (app/sentence_corpus.collect): every word of the sentence with
    Japanese in its lemma or surface, once per (lemma, reading), read through the list's learning rule
    (analyzer.LearningView: a compound too rare for the list is its parts when all are free — `library_of` — but
    never the target's own), that is not ignored, not known and not read already (through its known word, or a
    compound of such words) — a one-character word only where the list can offer it (analyzer.unoffered; the rule
    on, the default) — less the target. collect keeps that count inline, so it is MIRRORED here step for step, then
    CHECKED against collect's own `others`, run for real on the sentence as a one-file library: a mirror that drifts
    from the app raises, never passes."""
    from app import sentence_corpus
    known_tuples, known_lemmas, ignore = sets
    library = library_of(case, ctx)
    sentences = [(text, [list(token) for token in tokens])
                 for text, tokens in ctx.tokenizer("ja").tokenize_sentences(case.text)]

    def known(key):
        return key[0] in ignore or key[0] in known_lemmas or key in known_tuples
    view = analyzer.LearningView(*(library or (None, 0)), known=known, tagger=_tagger(ctx))
    present = {}
    for text, tokens in sentences:
        skip = analyzer.unoffered(text, tokens)
        for n, (lemma, reading, surface, _orth) in enumerate(tokens):
            if not (_has(lemma) or _has(surface)) or n in skip:
                continue
            key = (lemma, reading)
            if key not in present:
                present[key] = known(key) or view.readable(key)
    is_target = target_of(case)
    def unknowns_for(keep):
        return {(str(u[0]), u[1]) for k in present for u in view.units(k, keep)
                if not (known(u) or view.readable(u)) and not is_target(u) and analyzer.single_kind(u) != 1}
    unknown = unknowns_for(next((k for k in present if is_target(k)), None))
    # collect's own number, for the target (or any word of the sentence that can be an entry)
    if len(sentences) == 1:
        probe = next((k for k in present if is_target(k)), None) \
            or next((k for k in present if not (len(k[0]) == 1 and sentence_corpus._KANA_ONLY.match(k[0]))), None)
        if probe is not None:
            with _shared_tagger(ctx):
                words = sentence_corpus.collect(["case"], lambda path: sentences, "ja", sets,
                                                (1, 10 ** 9, 1, 10 ** 9), wanted={probe}, library=library)
            best = words[probe].best.result() if probe in words and words[probe].best is not None else []
            mine = len(unknowns_for(probe) - {probe})
            if not best or best[0][0][0] != mine:
                raise AssertionError(f"the sentence_corpus mirror counts {mine} for {probe}, collect "
                                     f"{best[0][0][0] if best else None} — update the mirror")
    return unknown


@counter("junban")
def junban_unknowns(case, ctx, sets):
    """Junban's count beside a card (reposition._place_the_rest -> anki_match.unknowns_beside): the tokens of the
    card's sentence (text: the Sentence field, raw — <b> included) OUTSIDE the card's own word — its <b> span, else
    the first place its word is written; ctx["target"] is the card's word as its field says it — that have
    Japanese, are words the list can offer there (a one-character word only a one-kanji dictionary word standing on
    its own: reposition._skip), and are neither ignored nor known nor read already — each token as the
    list's learning rule counts it (a compound too rare for the list is its parts when all are free; `library_of`).
    unknowns_beside, its tokens and the verdict (reposition._learning) are the app's own. Every TOKEN counts, so a
    word said twice counts twice: the second shows as lemma|reading#2. A sentence the card's word can't be found in
    (no <b>, not written as the card writes it) raises — Junban then goes by FreqSort ("rest"): the junban layer
    shows that."""
    from modules.junban import reposition
    word = split_key(case.ctx.get("target", ""))[0]
    seen, found = Counter(), set()
    verdict, units, _view = reposition._learning("ja", sets, library_of(case, ctx), _tagger(ctx))

    def unknown(token):
        if not verdict(token[0], token[1], token[2]):
            return False
        lemma, reading = token[0], token[1]
        seen[(lemma, reading)] += 1
        n = seen[(lemma, reading)]
        found.add((str(lemma), reading if n == 1 else f"{reading}#{n}"))
        return True
    count = anki_match.unknowns_beside(word, case.text, ctx.tokenizer("ja").tokenize, unknown, units,
                                       reposition._skip("ja"))
    if count is None:
        raise ValueError(f"Junban finds no span for {word!r} in the sentence (no <b>, not written that way)")
    return found


# --- patterns: パターン ------------------------------------------------------------------------------------------ #
_LINE_RE = re.compile(r'<div class="pat-(\w+)[^"]*">([^<]*)</div>')


def _lines(html_text):
    """The field's HTML -> {kind: [items]} (particle, form, colloc, frame; register)."""
    out = {}
    for kind, text in _LINE_RE.findall(html_text or ""):
        items = [item for item in text.replace("&amp;", "&").split(" · ") if item]
        out.setdefault(kind, []).extend(items)
    return out


def compare_patterns(observed, expect):
    """key / reason / source / lines / shown / thin exact; `has` / `lacks` against every item shown — an expected
    item also matches an item that carries its share after it ("集いする" is "集いする 45%", "〜を" is "〜を 22%")."""
    problems = compare_keys(observed, {k: v for k, v in expect.items() if k in ("key", "reason", "source", "lines",
                                                                               "shown", "thin")})
    items = [item for items in observed["lines"].values() for item in items]

    def shown(wanted):
        return any(item == wanted or item.startswith(wanted + " ") for item in items)
    missing = [item for item in expect.get("has", ()) if not shown(item)]
    if missing:
        problems.append(f"has: {missing} not among the items {items}")
    extra = [item for item in expect.get("lacks", ()) if shown(item)]
    if extra:
        problems.append(f"lacks: {extra} found among the items {items}")
    return problems


def _built_store(case, ctx):
    """A パターン database made by the builder's own pure functions from ctx["documents"] (patterns_build.iter_tokens
    -> count -> score; each text one document, as a library file is), written by write_rows to a scratch file."""
    from modules.junban import patterns_build, patterns_store
    stops = frozenset(analyzer.LOGIC.get("sentence_boundaries", {}).get("ja", "。！？!?\n"))
    counts = patterns_build.Counts()
    for text in case.ctx["documents"]:
        patterns_build.count(patterns_build.iter_tokens(text, _tagger(ctx), analyzer._sanitize_term, stops), counts)
        counts.end_document()
    floor = case.ctx.get("floor", 1)
    path = ctx.write("patterns_ja.db", b"")
    os.remove(path)
    patterns_build.write_rows(path, *patterns_build.score(counts, floor),
                              {"floor": floor, "language": "ja", "builder_version": patterns_build.BUILDER_VERSION,
                               "tokens": counts.tokens, "corpus_kind": "library"})
    return patterns_store.Store(path)


_NONE_INSTALLED = ("no installed パターン database here (under pytest: the test root's, never the user's) — build or "
                   "download one and this case runs again")


def _stale_installed(ctx, db):
    """The installed パターン databases a case with ctx db `db` reads ("installed" all of them, "installed:<name>" that
    one) that an older builder wrote — the app refuses them (patterns_store.open_store, required_builder), so until
    they are rebuilt the case would judge "no database" instead of the lookup. Read-only; a database not there is not
    stale (it was never built). -> (names, the builder the code needs)."""
    from modules.junban import patterns, patterns_build, patterns_store
    wanted = db.split(":", 1)[1] if ":" in db else None
    need = patterns_store.required_builder("ja")

    def find():
        stale = []
        for name in patterns.sources_for("ja"):
            path = patterns_build.default_db_path("ja", None if name == "library" else name)
            if (wanted and name != wanted) or not os.path.exists(path):
                continue
            store = patterns_store.Store(path)
            try:
                built = store.builder_version()
            finally:
                store.close()
            if built is not None and built < need:
                stale.append(name)
        return stale
    return ctx.memo(("patterns_stale", wanted), find), need


@evaluator("patterns", expects=("key", "reason", "source", "lines", "has", "lacks", "shown", "thin"),
           compare=compare_patterns,
           show=lambda o: f"{o['key'] or '—'} [{o['source'] or o['reason']}{' thin' if o['thin'] else ''}] "
                          + " | ".join(f"{kind}: {' · '.join(items)}" for kind, items in o["lines"].items()))
def patterns_layer(case, ctx):
    """パターン for a card: modules/junban/patterns.patterns_from_sources — the lookup Anki Backfill runs (resolve_key,
    the floors, the line rules, the source order) — over ONE database the builder's pure functions make from
    ctx["documents"] (named "library"; floor ctx["floor"], default 1), or with ctx["db"] = "installed" over the
    user's installed databases, read-only (patterns.open_sources — they change when rebuilt or downloaded again: a
    case that reads them says so; "installed:<name>" reads that one alone) — skipped (harness.Skip) while one it reads
    predates the code's builder. text: the card's word; ctx reading: its ExpressionReading.
    -> {key: the lemma|reading resolve_key reaches in the source used (else in the first), reason, source,
    lines: {kind: [items]}, shown: whether the card gets any line, thin: whether they are marked as resting on few
    uses (pat-thin)}."""
    from modules.junban import patterns
    word = anki_match.normalize_word(case.text)
    reading = case.ctx.get("reading", "")
    tokenize = ctx.memo(("patterns_tokenizer",), lambda: patterns.tokenizer(tagger=_tagger(ctx)))
    built = None
    db = str(case.ctx.get("db") or "")
    if db.startswith("installed"):
        if not os.path.isdir(path_utils.persistent_root()):
            # Read only, so no folder made: a scorecard run (no test root) made the user's real, empty
            # %APPDATA%\Houseki\Surasura, and every test run's real-root guard on this PC failed the tests running then.
            raise harness.Skip(_NONE_INSTALLED)
        stale, need = _stale_installed(ctx, db)
        if stale:
            raise harness.Skip(f"the installed パターン database{'s' if len(stale) > 1 else ''} ({', '.join(stale)}) "
                               f"predate{'' if len(stale) > 1 else 's'} builder {need} — rebuild "
                               f"{'them' if len(stale) > 1 else 'it'} and this case runs again")
        stores = ctx.memo(("patterns_installed",), lambda: patterns.open_sources("ja"))
        if ":" in db:                                   # "installed:library" — that one database alone
            stores = [(name, store) for name, store in stores if name == db.split(":", 1)[1]]
        if not any(store is not None for _name, store in stores):
            # Nothing to judge against: under pytest the roaming root is the test root's (path_utils), never the
            # user's %APPDATA%; outside it, no database has been built or downloaded yet.
            raise harness.Skip(_NONE_INSTALLED)
    else:
        built = _built_store(case, ctx)
        stores = [("library", built)]
    try:
        with harness.quiet():
            html_text, reason, source = patterns.patterns_from_sources(word, reading, stores, tokenize, language="ja")
        store = dict(stores).get(source) if source else next((s for _n, s in stores if s is not None), None)
        found = patterns.resolve_key(word, reading, store, tokenize)[0] if store is not None else None
    finally:
        if built is not None:
            built.close()
    return {"key": harness.key(*found) if found else "", "reason": reason or "", "source": source or "",
            "lines": _lines(html_text), "shown": bool(html_text), "thin": "pat-thin" in (html_text or "")}


# --- reibun: 例文 ----------------------------------------------------------------------------------------------- #
def _session(case, ctx):
    """A modules/junban/backfill.Session holding only what its 例文 methods read — the run's tokenizer and a パターン
    tokenizer on the same tagger; no databases, no Anki (its constructor opens both, and the token store) — its known
    test (reposition.known_test's, over the case's known sets: a known card takes no key from the list) and the list
    it looks a card up in first (backfill.list_index, as the constructor reads the list Junban follows): ctx "list"
    inline, else the snapshot's ctx "list_file" (default: the progressive list, Junban's order, as the junban layer
    reads), with the case's answers."""
    from modules.junban import backfill, patterns, reposition
    session = object.__new__(backfill.Session)
    session.language, session.stores, session.zh_script = "ja", [], None
    session.sentences, session._looked_up = {}, set()
    session._words = ctx.tokenizer("ja")
    session.tokenize = ctx.memo(("patterns_tokenizer",), lambda: patterns.tokenizer(tagger=_tagger(ctx)))
    known_tuples, known_lemmas, ignore = ctx.known_sets(case)

    def known(lemma, reading):
        return lemma in ignore or lemma in known_lemmas or (lemma, reading) in known_tuples
    session.is_known = lambda word: reposition.is_known_word(word, known, known_lemmas, ignore,
                                                             session._words.tokenize, known_tuples)
    rows = case.ctx.get("list")
    path = (ctx.write("list.csv", harness._list_csv(rows)) if rows is not None
            else ctx.snapshot(case, f"{case.ctx.get('list_file', 'progressive')}_learning_list.csv"))
    session._list = ({}, [], []) if path is None else ctx.memo(("list_index", path),
                                                               lambda: backfill.list_index(path))
    session._answers = ctx.answers(case)
    return session


def _plain(line):
    """A field line as text, its bold word shown as 【word】 — where the card will highlight it."""
    line = line.replace("<b>", "【").replace("</b>", "】")
    return re.sub(r"<[^>]*>", "", line).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def compare_reibun(observed, expect):
    problems = compare_keys(observed, {k: v for k, v in expect.items() if k in ("key", "found", "sentences", "first",
                                                                               "reason")})
    return compare_members(problems, "chosen sentences", set(observed["sentences"]), expect, "has", "lacks")


@evaluator("reibun", expects=("key", "found", "sentences", "first", "reason", "has", "lacks"), compare=compare_reibun,
           show=lambda o: f"key {o['key'] or '—'} · {len(o['found'])} found · "
                          + (" ⏎ ".join(f"「{s}」" for s in o["sentences"]) or o["reason"] or "—"))
def reibun(case, ctx):
    """例文 for a card — Anki Backfill's sentence step: backfill.Session.sentence_key (what the library is searched
    for: the list row the card reaches as Junban places it — ctx list / list_file / answers, see _session — else one
    word as the token store keys it, else the card's word as a run of lemmas — or, for a card the dictionary keeps
    apart from the word it is read as (CARD-SENSE), its run, or one word found as it is written), the ranking of
    sentence_corpus.best_for (sentence_corpus.collect over the library, the case's known sets, the frozen settings'
    length window), then Session._sentence (the easy ones, never the card's own, variety). The library is
    ctx["documents"] (each a file, in study order, read as the token store reads it); no token store and no パターン
    databases — so no `prefer`, which only breaks ties among equally easy sentences.
    -> {key, found: [[others, sentence], ...] best first, sentences: the lines the field gets (plain text, the
    highlighted word in 【】), first, reason (why none)}."""
    from app import sentence_corpus
    session = _session(case, ctx)
    word = anki_match.normalize_word(case.text)
    key = session.sentence_key(word)
    shown = harness.key(*key) if isinstance(key, tuple) else (key or "")
    found = []
    if key is not None:
        files = [path for path, _text in _document_files(case, ctx)] if case.ctx.get("documents") else []
        cache = _file_tokens(ctx, files)
        phrases = {key: session._lemmas(key)} if isinstance(key, str) else None
        with _shared_tagger(ctx):
            words = sentence_corpus.collect(files, cache.__getitem__, "ja", ctx.known_sets(case),
                                            sentence_corpus.length_range({"logic": dict(analyzer.LOGIC)}),
                                            wanted={key} if isinstance(key, tuple) else set(), phrases=phrases,
                                            library=library_of(case, ctx))
        entry = words.get(key)
        best = entry.best.result() if entry is not None and entry.best is not None else []
        # best_for's own shape: (others, text, surface, file)
        found = [(rank[0], text, surface, fidx) for rank, text, fidx, surface in best]
        session.sentences = {key: found}
    note = {"word": word, "reading": case.ctx.get("reading", ""), "fields": dict(case.ctx.get("fields", {}))}
    value, reason = session._sentence(note, "例文")          # the field being filled: never one of ctx fields
    sentences = [_plain(line) for line in value.split("<br>")] if value else []
    return {"key": shown, "found": [[others, text] for others, text, _s, _f in found], "sentences": sentences,
            "first": sentences[0] if sentences else "", "reason": reason or ""}


# --- dictionary: the sentence dictionary's headwords ------------------------------------------------------------ #
@evaluator("dictionary", expects=("terms", "has", "lacks"),
           compare=lambda observed, expect: compare_members(
               compare_keys(observed, {k: v for k, v in expect.items() if k == "terms"}),
               "terms", set(observed["terms"]), expect, "has", "lacks"),
           show=lambda observed: ", ".join(observed["terms"]) or "(none)")
def dictionary(case, ctx):
    """The Yomitan sentence dictionary's headwords for one word — app/sentence_corpus._japanese_terms with its own
    tagger (_default_tagger, made once per run): text = the word's lemma, ctx reading = its lForm, ctx orths =
    {spelling: uses} as collect() gathers them. -> {"terms": ["term【reading】rules", ...]} ("" reading: kana)."""
    from app import sentence_corpus
    tag = ctx.memo(("dictionary_tagger",), sentence_corpus._default_tagger)
    terms = sentence_corpus._japanese_terms(case.text, case.ctx.get("reading", ""), dict(case.ctx.get("orths", {})),
                                            tag)
    return {"terms": [f"{term}【{reading}】{rules}" for term, reading, rules in terms]}


# --- cache: does a cache key notice a change? ----------------------------------------------------------------- #
_CACHES = ("token store", "known words", "report", "run")
_CHANGES = ("join table", "sentence boundaries", "KnownWord.json edited", "junban_pairs.json written",
            "anki_backlog.json written")


def _signature(name, ctx, folder):
    """The key `name` computes right now (its inputs read under `folder`, a scratch User Files/ja)."""
    if name == "token store":
        return token_index.build_signature("ja")
    if name == "known words":
        return token_index.known_signature(os.path.join(folder, "KnownWord.json"), "asis")
    args = analyzer.parse_analysis_args(["--language", "ja", "--static"])
    if name == "report":
        return analyzer.compute_render_signature(args)
    return analyzer.compute_run_signature("ja", [], args)


@evaluator("cache", expects=("moves",), show=lambda observed: f"moves={observed['moves']}")
def cache(case, ctx):
    """Does a cache key notice a change? text names the key — "token store" (token_index.build_signature: the
    cached tokens), "known words" (token_index.known_signature: the cached known-word sets), "report"
    (analyzer.compute_render_signature: re-render), "run" (analyzer.compute_run_signature: re-analyse) — and
    ctx["change"] what changes: "join table" (analyzer.affix_joins patched to the table minus one word),
    "sentence boundaries" (the ja boundary set gains "…" — in analyzer.LOGIC, which a run splits with, and in the
    settings the app loads, which the token store's signature reads), "KnownWord.json edited", "junban_pairs.json written",
    "anki_backlog.json written" (files in a scratch User Files/ja the app's paths are pointed at; the frozen settings
    in place of the live ones). -> {"moves": the key before != after}."""
    name, change = case.text, case.ctx.get("change")
    if name not in _CACHES or change not in _CHANGES:
        raise KeyError(f"cache layer: text is one of {_CACHES}, ctx['change'] one of {_CHANGES}")
    folder = os.path.dirname(ctx.write("KnownWord.json", json.dumps({"words": [{"dictForm": "冒険",
                                                                                 "knownStatus": "KNOWN"}]})))
    settings = ctx.memo(("frozen_settings",), _frozen_settings)
    frozen_file = os.path.join(harness.DATA, harness.SETTINGS_SNAPSHOT, "settings.json")
    with patched(analyzer, "get_user_files_path", lambda language: folder), \
            patched(analyzer, "get_user_file",
                    lambda name: frozen_file if name == "settings.json" else os.path.join(folder, name)), \
            patched(settings_manager, "load_settings", lambda: json.loads(json.dumps(settings))):
        before = _signature(name, ctx, folder)
        if change == "join table":
            table = analyzer.affix_joins()
            smaller = dict(table)
            smaller.pop(next(iter(smaller)), None)
            with patched(analyzer, "affix_joins", lambda: smaller):
                after = _signature(name, ctx, folder)
        elif change == "sentence boundaries":
            boundaries = dict(analyzer.LOGIC.get("sentence_boundaries", {}))
            boundaries["ja"] = boundaries.get("ja", "") + "…"
            edited = json.loads(json.dumps(settings))
            edited["logic"]["sentence_boundaries"]["ja"] += "…"
            with mock.patch.dict(analyzer.LOGIC, {"sentence_boundaries": boundaries}), \
                    patched(settings_manager, "load_settings", lambda: json.loads(json.dumps(edited))):
                after = _signature(name, ctx, folder)
        else:
            target = {"KnownWord.json edited": "KnownWord.json", "junban_pairs.json written": "junban_pairs.json",
                      "anki_backlog.json written": "anki_backlog.json"}[change]
            path = os.path.join(folder, target)
            data = {"KnownWord.json": {"words": [{"dictForm": "冒険", "knownStatus": "KNOWN"},
                                                 {"dictForm": "努力", "knownStatus": "KNOWN"}]},
                    "junban_pairs.json": {"version": 1, "pairs": {"あおぐ": {"target": "仰ぐ", "answer": "yes"}}},
                    "anki_backlog.json": {"version": 1, "notes": {"1": {"word": "冒険", "keys": ["冒険"]}}}}[target]
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.utime(path, (1_700_000_000, 1_700_000_000))
            after = _signature(name, ctx, folder)
    return {"moves": before != after}
