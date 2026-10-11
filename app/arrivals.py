"""Arrivals counted early (E2.2, RUNBOOK D6): a file's plan line, as the next full Generate would write it, from its
tokens and a *view* of the last Generate — without a Generate.

A full Generate (`analyzer.main()`) writes, per counted file, the line the fast re-plan reads (`plan_lines`, E1.1 01 §7):
`main` (its uses of each list word, first counted first), `ph` (its phrase rows' own uses), `sp` (the tied spellings
met there, in order) and `prog` (what the progressive pass reads of it). `record` gives that line for one file's
sentences — a file that has just arrived, before any Generate has counted it — plus what the engine and the gates add
it by: its spelling counts per list word (`spc`), its counted uses of every word, list or not (`uses`), its phrases'
uses (`phrases`) and its token total (`tokens`).

    view = arrivals.View.build(language, plan, store, args)      # once, in a process that has the tokenizer
    line = arrivals.record(view.sentences(path), view, path, source_type)

**One rule set with `main()`** (D6): the view is built from `main()`'s own loaders (`analyzer.read_known_words`,
`load_ignore_set`, `file_sentences`, `word_flags`), the run's floor and the store's counts; `record` follows the
aggregation's per-file counting step by step. The oracle (`tests/test_arrivals_record.py`, T6) holds the two together:
for every counted file of the test libraries, `record` gives the plan file's own line, byte for byte.

**Pure** except `View.build` (the tokenizer, the store, the user's lists) and `View.sentences`: `record` reads only its
arguments and writes nothing.
"""
import json
import math
import os
from bisect import bisect_left
from collections import Counter

from app import analyzer


class View:
    """Everything a counted file's plan line depends on, fixed from the last Generate (`build`): the plan's keys, the
    known and ignored words as `main()` starts with them, the one-character rule, the compounds too rare for the list,
    the set phrases and which of them hold a row."""

    def __init__(self, **values):
        self.__dict__.update(values)

    @classmethod
    def build(cls, language, plan, store, args=None, tokenizer=None):
        """The view of `plan` (a `plan_engine.Plan` the last Generate wrote) for `language`, over the token store
        `store` that Generate read (its counts, its name tables, its known-words cache). `args`: the Generate's
        (`analyzer.parse_analysis_args`; default: the language's defaults). Builds the tokenizer as `main()` does
        unless one is handed in. Reads only: the known-words cache is never written."""
        from app import names, token_index, zh_script
        from app.path_utils import get_user_files_path

        args = args or analyzer.parse_analysis_args([f"--language={language}"])
        script = zh_script.effective(language, args.zh_script)
        analyzer.SANITIZE_JA = language == "ja"
        skip_singles = not args.include_single_chars and language == "ja"      # main(): SKIP_SINGLE_CHARS, ja only
        if tokenizer is None:
            tokenizer = (analyzer.ChineseTokenizer(reinforce_segmentation=args.reinforce, script=script)
                         if language == "zh" else analyzer.JapaneseTokenizer())
        tables = None
        if language == "ja":
            # Every word read from here on — the known words included — is read with the tables the Generate read.
            tables = store.names_tables() if store is not None else token_index.read_names_tables(language)
            names.use_library_tables(tables)
        user_files_dir = get_user_files_path(language)
        known_file = os.path.join(user_files_dir, "KnownWord.json")
        known_tuples, known_lemmas = analyzer.read_known_words(
            store, known_file, token_index.known_signature(known_file, script), tokenizer, keep=False)
        ignore = analyzer.load_ignore_set(user_files_dir, script, language)

        def known(lr):
            return lr in known_tuples or lr[0] in known_lemmas or lr[0] in ignore

        # The compounds too rare for the list, as main() fixes them before its aggregation: the store's counts, the
        # plan's floor.
        joins = analyzer.affix_joins() if language == "ja" else {}
        parts = analyzer.compound_parts() if language == "ja" else {}
        floor = plan.header["floor"]
        counts, total = store.word_counts() if store is not None else (None, 0)
        learning = analyzer.LearningView(counts, floor or 0, known, parts=parts, joins=joins,
                                         tagger=tokenizer.tagger if language == "ja" else None)
        rare = frozenset(key for key in parts if learning.rare(key)) if counts is not None else frozenset()

        phrase_set = None
        if language == "ja" and analyzer.LOGIC.get("phrase_rows", True):
            from app import phrases
            phrase_set = phrases.load()

        keys = [(key[0], key[1]) for key in plan.keys]
        index = {key: k for k, key in enumerate(keys)}
        phrase_rows = {key: k for k, key in enumerate(keys) if plan.keys[k][2]}
        # The phrase whose entry holds each phrase row: the plan names it (format 2). A format-1 plan doesn't: a row
        # that only one phrase of the set can hold is that phrase's; any other is left out and named in `unsure`.
        unsure = set()
        if "phrase_entries" in plan.header:
            entry_of = {index_: k for k, index_ in plan.header["phrase_entries"]}
        else:
            entry_of = {}
            if phrase_set is not None and phrase_rows:
                holders = {}
                for i, entry in enumerate(phrase_set.entries):
                    if (entry.word, entry.reading) in phrase_rows:
                        holders.setdefault((entry.word, entry.reading), []).append(i)
                for key, k in phrase_rows.items():
                    if len(holders.get(key, ())) == 1:
                        entry_of[holders[key][0]] = k
                    else:
                        unsure.add(k)
        # Spellings: which an order can change (`_spelling_ties`, on the counts the plan holds), and the counts of
        # every key that has them, each in the order first met — its first key is the spelling first met anywhere.
        ties, spellings = {}, {}
        for k, orths, surfaces, _tiers in plan.ties:
            ties[k] = analyzer._spelling_ties(keys[k][0], orths, surfaces)
            spellings[k] = {"orths": orths, "surfaces": surfaces}
        for k, (orths, surfaces) in plan.spell.items():
            spellings[k] = {"orths": orths, "surfaces": surfaces}

        return cls(language=language, plan=plan, store=store, tokenizer=tokenizer, args=args, script=script,
                   known_tuples=known_tuples, known_lemmas=known_lemmas, ignore=ignore, known=known,
                   skip_singles=skip_singles, learning=learning, rare=rare, floor=floor, counts=counts, total=total,
                   phrase_set=phrase_set, keys=keys, index=index, phrase_rows=phrase_rows, entry_of=entry_of,
                   unsure=unsure, lemmas={key[0] for k, key in enumerate(keys) if not plan.keys[k][2]},
                   listed={k for k, row in enumerate(plan.rows) if row is not None},
                   halved={k for k, key in enumerate(plan.keys) if key[3]},
                   ties=ties, spellings=spellings, states={}, phrase_bound={}, names_tables=tables)

    def never(self, lr):
        """A one-character word the list can never offer (main()'s `_never`)."""
        return self.skip_singles and analyzer.single_kind(lr) == 1

    def state(self, key):
        """`analyzer.word_flags` of `key`, asked once per word."""
        state = self.states.get(key)
        if state is None:
            state = self.states[key] = analyzer.word_flags(key, self.language, self.known_tuples, self.known_lemmas,
                                                           self.ignore, self.skip_singles)
        return state

    def names_record(self, path):
        """A file's name record as the token store holds it (counted or kept; Japanese), or None."""
        return self.store.names_record(path) if self.store is not None and self.language == "ja" else None

    def sentences(self, path):
        """A file's tokenized sentences as a Generate reads them (`analyzer.file_sentences`: the store's, the name
        tables applied)."""
        return analyzer.file_sentences(self.store, self.tokenizer, path, self.language)


def record(sentences, view, file_path=None, source_type=None, names=None):
    """The plan line a full Generate would write for one file's `sentences` were it counted, with `view` the last
    Generate's (`View.build`): {"main", "ph", "sp", "prog"} — as `analyzer.plan_lines` writes them, the same k numbers,
    the same order — and {"spc": {k: [{orth: n}, {surface: n}]} (this file's spellings of each list word, each in the
    order met), "uses": {(lemma, reading): n} (every word's counted uses here, list or not, rare compounds' credits
    included), "phrases": {phrase index: uses}, "tokens": the file's counted tokens} — and what the gates
    (`Gates.check`) add it to the library by, each as the token store counts a file: "counts" {(lemma, reading): its
    tokens with target-language characters}, "bound" (Japanese: {(lemma, reading): uses as pieces of something else},
    `analyzer.bound_uses`), "tally" (`phrases.tally`'s), "names" (its name record, handed in: `View.names_record`);
    "plan" and "keys" (the plan it was read against, which `plan_engine.Engine.add` checks) and "name" (its file's
    name, the progressive list's Source File). `file_path` and `source_type` name the file; no part of its line
    depends on them."""
    language = view.language
    has_target = analyzer.has_target_language
    bound_uses = analyzer.bound_uses
    state_of, index, learning, rare_set = view.state, view.index, view.learning, view.rare
    known, never = view.known, view.never
    phrase_set = view.phrase_set
    if phrase_set is not None:
        from app import phrases

    file_counter = Counter()        # every token, in first-met order (the progressive pass's multiset)
    tokens = 0
    credits = Counter()             # the words met inside a rare compound
    pieces = Counter()              # one-kanji list words' uses here that are pieces of something else
    phrase_uses = Counter()         # phrase index -> uses
    given = Counter()               # (lemma, reading) -> uses given to a phrase (a word living only inside it)
    uses = {}                       # (lemma, reading) -> counted uses, first counted first
    spelled = {}                    # (lemma, reading) -> (orth, surface) | [{orth: None}, {surface: None}], as met
    phrase_spelled = {}             # phrase index -> likewise
    spc = {}                        # k -> [{orth: n}, {surface: n}]
    counts = Counter()              # every token with target-language characters (the token store's aggregate)
    bound_all = Counter()           # every one-kanji word's uses as a piece of something else (the store's bound)
    tally, taken_names = {}, {}     # phrases.tally's: {index: [uses, [spellings]]}, {"lemma|reading": uses given}
    japanese = language == "ja"

    def spell(k, orth, surface):
        counts = spc.get(k)
        if counts is None:
            counts = spc[k] = [{}, {}]
        counts[0][orth] = counts[0].get(orth, 0) + 1
        counts[1][surface] = counts[1].get(surface, 0) + 1

    for s_text, s_tokens in sentences:
        unknown = []                # (key, surface, orth) of the sentence's unknown words
        for t_no, (lemma, reading, surface, orth) in enumerate(s_tokens):
            key = (lemma, reading)
            state = state_of(key)
            file_counter[key] += 1
            if state & 2 and not has_target(surface, language):
                continue
            tokens += 1
            counts[key] += 1
            if state & 1:
                continue
            if state & 12:
                if state & 4:
                    continue
                if bound_uses(s_text, s_tokens, only=(t_no,)):
                    pieces[key] += 1
                    continue
            unknown.append((key, surface, orth))
        if japanese:
            for i in bound_uses(s_text, s_tokens):
                bound_all[(s_tokens[i][0], s_tokens[i][1])] += 1
        rare = None
        if unknown and not rare_set.isdisjoint([u[0] for u in unknown]):
            rare = {u[0] for u in unknown if u[0] in rare_set}

        found = phrase_set.find(s_tokens, s_text) if phrase_set is not None else ()
        taken = None
        for start, end, p_index in found:
            phrase = phrase_set.entry(p_index)
            bound = view.phrase_bound.get(p_index)
            if bound is None:
                bound = view.phrase_bound[p_index] = phrases.bound_at(phrase)
            if bound:
                if taken is None:
                    taken = Counter()
                for k in bound:
                    taken[(s_tokens[start + k][0], s_tokens[start + k][1])] += 1
                    name = f"{s_tokens[start + k][0]}|{s_tokens[start + k][1]}"
                    taken_names[name] = taken_names.get(name, 0) + 1
            orth, written = phrases.spellings(s_tokens, start, end, phrase)
            phrase_uses[p_index] += 1
            met = tally.get(p_index)
            if met is None:
                met = tally[p_index] = [0, []]
            met[0] += 1
            for text in (orth, written):
                if text not in met[1]:
                    met[1].append(text)
            met = phrase_spelled.get(p_index)
            if met is None:
                phrase_spelled[p_index] = (orth, written)
            elif met.__class__ is tuple:
                if met[0] != orth or met[1] != written:
                    phrase_spelled[p_index] = [{met[0]: None, orth: None}, {met[1]: None, written: None}]
            else:
                met[0][orth] = None
                met[1][written] = None
            row = view.entry_of.get(p_index)
            if row is not None:
                spell(row, orth, written)
        if taken:
            given.update(taken)

        for key, surface, orth in unknown:
            if taken and taken.get(key):
                taken[key] -= 1         # a use its phrase has taken
                continue
            uses[key] = uses.get(key, 0) + 1
            met = spelled.get(key)
            if met is None:
                spelled[key] = (orth, surface)
            elif met.__class__ is tuple:
                if met[0] != orth or met[1] != surface:
                    spelled[key] = [{met[0]: None, orth: None}, {met[1]: None, surface: None}]
            else:
                met[0][orth] = None
                met[1][surface] = None
            k = index.get(key)
            if k is not None:
                spell(k, orth, surface)

        if rare:
            # Each use of a rare compound is also a use of its free parts on the list (every unknown of the sentence,
            # a use a phrase took too, as main() reads them).
            for key, _surface, _orth in unknown:
                if key not in rare:
                    continue
                for part in learning.credits(key):
                    credits[part] += 1
                    if known(part) or never(part):
                        continue
                    uses[part] = uses.get(part, 0) + 1

    # The line, as `plan_lines` writes it.
    ties, spellings = view.ties, view.spellings
    main, sp = [], []
    for key, n in uses.items():
        k = index.get(key)
        if k is None:
            continue
        main += (k, n)
        if k in ties:
            found = analyzer._plan_spellings(key, k, n > credits.get(key, 0), spelled, spellings[k], ties[k])
            if found:
                sp.append(found)
    ph, met = [], []
    for p_index, n in phrase_uses.items():
        entry = phrase_set.entry(p_index)
        named = view.phrase_rows.get((entry.word, entry.reading))
        if named is not None:
            met += (named, n)
        k = view.entry_of.get(p_index)
        if k is None:
            continue
        ph += (k, n)
        if k in ties:
            found = analyzer._plan_spellings(p_index, k, True, phrase_spelled, spellings[k], ties[k])
            if found:
                sp.append(found)

    # The progressive pass's record of the file (main()'s `_progressive_files`).
    baseline, prog_tokens, prog_given, siblings = 0, [], {}, {}
    lemmas = view.lemmas
    for key, count in file_counter.items():
        if state_of(key) & 5:
            baseline += count
            continue
        p = pieces.get(key)
        if p:
            baseline += p
            count -= p
            if count <= 0:
                continue
        if key[0] in lemmas:
            k = index.get(key)
            if k is None:
                siblings[key[0]] = siblings.get(key[0], 0) + count
            else:
                prog_tokens += (k, count)
                if key in given:
                    prog_given[k] = given[key]
    prog_credits = []
    for key, n in credits.items():
        k = index.get(key)
        if k is not None:
            prog_credits += (k, n)
    prog = [sum(file_counter.values()), baseline, prog_tokens, [x for k, n in prog_given.items() for x in (k, n)],
            prog_credits, met, [[lemma, n] for lemma, n in siblings.items()]]
    return {"main": main, "ph": ph, "sp": sp, "prog": prog, "spc": spc, "uses": uses, "phrases": dict(phrase_uses),
            "tokens": tokens, "counts": counts, "bound": bound_all, "tally": (tally, taken_names), "names": names,
            "plan": view.plan.header["run_signature"], "keys": len(view.keys),
            "name": os.path.basename(file_path) if file_path else None}


# --------------------------------------------------------------------------------------------------------------- #
# The gates (E2.2 D7, K6): is an arrival's placement the next Generate's?
# --------------------------------------------------------------------------------------------------------------- #

GATES = ("band", "floor", "compounds", "names", "phrases", "spellings")


class Gates:
    """Whether the plan's library plus some arrivals would give a Generate whose list is the plan's — the same words
    and phrase rows, the same compounds too rare for it, the same name tables and spellings — so that the engine,
    adding each arrival's record (`plan_engine.Engine.add`), gives that Generate's plan columns exactly. Built once per
    view (`build`), from the token store's counted aggregate, its one-kanji pieces, its phrase tallies and its files'
    name records, kept warm (K6); `check(records)` adds only the arrivals.

      band       automatic rarity picks the plan's band again (`word_selection.auto_band`, the remembered band
                 honoured, on the distribution `main()`'s `_floor_count` reads, the arrivals added); a manual band or
                 --min-freq never moves;
      floor      every list word stays at or over the new cut-off, and no other word reaches it (its uses before are
                 under the plan's cut-off and at most the store's count less its pieces plus what rare compounds can
                 give it; the arrivals' uses are exact);
      compounds  no compound's rarity flips (`LearningView.rare`: its count and the cut-off, both new);
      names      the name tables, worked out again with the arrivals' name records, are the same (their stamp; only
                 the spellings a record touches are decided again), and with Ignore names on no new name;
      phrases    no phrase row comes or goes: its uses against the new cut-off, a word of its lemmas joined arriving,
                 a spelling the learner knows it by;
      spellings  no list word's Orth / Forms moves and no tie appears that the plan doesn't hold."""

    def __init__(self, **values):
        self.__dict__.update(values)

    @classmethod
    def build(cls, view, store, remembered=False, user_files_dir=None):
        """The gates for `view` (`View.build`) over the token store it was built on. `remembered`: the band automatic
        rarity last chose (Q4-3; default: as `main()` reads it, from the library store)."""
        from app import names, phrases, word_selection
        from app.path_utils import get_data_path, get_user_files_path
        language, plan, args = view.language, view.plan, view.args
        # The cut-off's rule, as main() reads it (its MIN_FREQ and SELECT_* globals, `_floor_count`).
        sel = analyzer.LOGIC.get("selection", {})
        min_freq = args.min_freq if args.min_freq > 0 else (1 if args.exclude_freq_one else 0)
        auto = sel.get("auto") is True and not min_freq and not args.target_coverage > 0
        user_files_dir = user_files_dir or get_user_files_path(language)
        if auto and remembered is False:
            try:
                from app import library_store
                remembered = library_store.read_auto_band(language, get_data_path(language))
            except Exception:
                remembered = None
        counts, total = view.counts, view.total
        bound = store.bound_counts() if language == "ja" else {}
        gates = cls(view=view, min_freq=min_freq, coverage=args.target_coverage, auto=auto,
                    band=sel.get("band", "occasional"), ppm=sel.get("bands_ppm") or word_selection.DEFAULT_BANDS_PPM,
                    min_count=sel.get("min_count", word_selection.DEFAULT_MIN_COUNT),
                    max_words=sel.get("auto_max_words", word_selection.DEFAULT_AUTO_MAX_WORDS),
                    remembered=remembered, counts=counts, total=total, bound=bound,
                    pieces=bound if view.skip_singles else {},     # main(): pieces count when the one-kanji rule is on
                    floor0=plan.header["floor"], lemmas={key[0] for key in counts}, stale=None)
        # Automatic rarity's own inputs: the learner's lists as the Rarity slider reads them, the phrase table.
        gates.band0 = gates.band
        if auto:
            gates._warm_band(store, user_files_dir)
            gates.band0 = gates._auto_band(gates._band_words(Counter(), Counter(), (), total))
        if gates._floor(total, gates.band0) != gates.floor0 or total != plan.header.get("total_tokens"):
            gates.stale = "the token store isn't the plan's library"
        # What rare compounds can give a word (main()'s `_room`), and every unknown compound's count, ascending.
        room = Counter()
        for compound in view.rare:
            n = counts.get(compound)
            if n:
                for part in view.learning.credits(compound):
                    room[part] += n
        gates.room = room
        parts = view.learning.parts
        gates.compound_counts = sorted(n for key, n in counts.items() if key in parts and not view.known(key))
        # Each k's Occurrences, the list's lowest, and each phrase row's phrase.
        gates.occ = [key[4] for key in plan.keys]
        gates.occ_min = min(gates.occ, default=0)
        gates.row_of_phrase = dict(view.entry_of)
        # The phrases one by one (the store's per-file tallies): uses, and the spellings met.
        gates.phrase_uses = gates.phrase_spellings = None
        if view.phrase_set is not None:
            tallies = store.phrase_tallies()
            if tallies is not None:
                uses, spellings = Counter(), {}
                for file_uses, _given in tallies.values():
                    for index, (n, spelled) in file_uses.items():
                        uses[int(index)] += n
                        held = spellings.setdefault(int(index), [])
                        held.extend(x for x in spelled if x not in held)
                gates.phrase_uses, gates.phrase_spellings = uses, spellings
        # The name tables' sums over the counted files' records, and the tables as they stand.
        gates.tables = gates.table_sums = gates.term_sums = gates.records = None
        gates.names_words = set()
        if language == "ja":
            tables = store.names_tables()
            records = store.names_records()
            gates.records = records                     # the whole rule's input when the store holds no tables
            if tables:
                gates.tables = tables
                gates.table_sums = names.TableSums(records)
                gates.term_sums = names.TermSums(records, tables)
            try:
                gates.names_words = set(json.loads(store.get_meta("names_words") or "[]"))
            except ValueError:
                pass
        gates.known_whole = phrases.known_whole if view.phrase_set is not None else None
        return gates

    def _floor(self, total, band):
        """The cut-off for a library of `total` tokens (main()'s `_floor_count`)."""
        from app import word_selection
        if self.min_freq > 0:
            return self.min_freq
        if self.coverage > 0:
            return self.min_count
        return word_selection.band_floor_count(band, total, self.ppm, self.min_count)

    def _auto_band(self, words):
        """The band automatic rarity picks from each band's word count (`word_selection.auto_band`, the remembered band
        honoured)."""
        from app import word_selection
        return word_selection.auto_band({band: {"word_count": n} for band, n in words.items()}, self.max_words,
                                        remembered=self.remembered)

    def _warm_band(self, store, user_files_dir):
        """Automatic rarity's inputs, kept: the Rarity slider's distribution of the library as it stands (main()'s
        `_floor_count` reads `token_index.preview_frequencies`) — each unknown's count, sorted, and the compounds that
        give their parts — so an arrival is counted in by what it touches (`_band_words`)."""
        from app import token_index
        language = self.view.language
        self.lists = lists = token_index.preview_lists(store, language, user_files_dir, self.view.script)
        self.phrase_table = store.phrase_table() or {}
        freqs = token_index.unknown_distribution(
            self.counts, self.total, lists["known_tuples"], lists["known_lemmas"], lists["ignore_set"],
            lists["skip_singles"], language, self.phrase_table or None,
            self.bound if lists["skip_singles"] and language == "ja" else None)
        self.entries = dict(freqs["unknown"])
        self.ranked = sorted(self.entries.values())
        self.compounds = freqs.get("compounds") or ({}, {}, {})
        self.holders = {}                               # a part -> the compounds that hold it
        for compound, parts in self.compounds[1].items():
            for lemma, reading, _free in parts:
                self.holders.setdefault((lemma, reading), []).append(compound)
        self.rows_of_word = {}                          # a phrase row's Word -> its rows' names
        for name in self.phrase_table.get("rows") or {}:
            self.rows_of_word.setdefault(name.partition("|")[0], []).append(name)

    def _band_words(self, counts_add, bound_add, tallies, total):
        """{band: its word count} on the Rarity slider's numbers with the arrivals added (`word_selection.preview`'s
        count, every band's): the unknowns the arrivals touch — their words, every compound holding one, those
        compounds' parts, the phrase rows they meet or whose Word they bring — counted again by
        `token_index.unknown_distribution`'s own rule over just those, the rest as kept (`_warm_band`)."""
        from app import token_index, word_selection
        language, lists = self.view.language, self.lists
        skip = lists["skip_singles"] and language == "ja"
        known_tuples, known_lemmas = lists["known_tuples"] or set(), lists["known_lemmas"] or set()
        ignore = lists["ignore_set"] or set()
        rows0, taken0 = self.phrase_table.get("rows") or {}, self.phrase_table.get("taken") or {}
        rows, taken_add = {}, Counter()
        entries = self.view.phrase_set
        for uses, given in tallies:
            for index, (n, spelled) in uses.items():
                phrase = entries.entry(int(index))
                name = phrase.word + "|" + phrase.reading
                row = rows.get(name)
                if row is None:
                    held = rows0.get(name)
                    row = rows[name] = [held[0], list(held[1])] if held else [0, [phrase.display]]
                row[0] += n
                row[1].extend(x for x in spelled if x not in row[1])
            taken_add.update(given)
        touched = set(counts_add) | set(bound_add) | {tuple(name.split("|", 1)) for name in taken_add}
        table = analyzer.compound_parts() if language == "ja" else {}
        todo = list(touched) + [c for key in touched for c in self.holders.get(key, ())]
        near = set()
        while todo:
            key = todo.pop()
            if key in near:
                continue
            near.add(key)
            todo.extend((lemma, reading) for lemma, reading, _free in table.get(key, ()))
        counts = {key: self.counts.get(key, 0) + counts_add.get(key, 0) for key in near}
        counts = {key: n for key, n in counts.items() if n > 0}
        names = {f"{key[0]}|{key[1]}": key for key in near}
        part = token_index.unknown_distribution(
            counts, total, known_tuples, known_lemmas, ignore, lists["skip_singles"], language,
            {"taken": {name: taken0.get(name, 0) + taken_add.get(name, 0) for name in names
                       if name in taken0 or name in taken_add}},
            {key: self.bound.get(key, 0) + bound_add.get(key, 0) for key in counts} if skip else None)
        moved = dict.fromkeys(names)                    # name -> its count as an unknown now, None: none
        moved.update(part["unknown"])
        arriving = {key[0] for key in counts_add} - self.lemmas
        lemmas = self.lemmas | arriving
        for name in set(rows).union(*(self.rows_of_word.get(word, ()) for word in arriving)):
            row = rows.get(name) or rows0[name]
            moved[name] = token_index.phrase_row_uses(name, row, lemmas, known_tuples, known_lemmas, ignore)
        uses, parts, bases = self.compounds
        if part.get("compounds"):
            uses, parts, bases = dict(uses), dict(parts), dict(bases)
            uses.update(part["compounds"][0])
            parts.update(part["compounds"][1])
            bases.update(part["compounds"][2])
        floors = {band: word_selection.band_floor_count(band, total, self.ppm, self.min_count)
                  for band in word_selection.BANDS_ORDER}
        given = word_selection._given_back((uses, parts, bases) if uses else None, floors.values())
        out = {}
        for band, floor in floors.items():
            n = len(self.ranked) - bisect_left(self.ranked, floor)
            for name, now in moved.items():
                before = self.entries.get(name)
                n += (now is not None and now >= floor) - (before is not None and before >= floor)
            for name, credit in (given.get(floor) or {}).items():
                base = bases.get(name, 0)
                if base < floor <= base + credit:
                    n += 1
            out[band] = n
        return out

    def check(self, records):
        """(exact, moved): `exact` True when no gate moves for the plan's library plus these arrivals (`record`'s
        results, each with its name record for Japanese); `moved` names the gates that did (`GATES`' names, in that
        order; "stale" when the token store no longer holds the plan's library)."""
        records = list(records)
        if self.stale:
            return False, ["stale"]
        view = self.view
        moved = set()
        counts_add, uses_add, phrases_add, bound_add, spc_add = Counter(), Counter(), Counter(), Counter(), {}
        tallies = []
        for rec in records:
            counts_add.update(rec["counts"])
            uses_add.update(rec["uses"])
            phrases_add.update(rec["phrases"])
            bound_add.update(rec["bound"])
            tallies.append(rec["tally"])
            for k, (orths, surfaces) in rec["spc"].items():
                o, s = spc_add.setdefault(int(k), (Counter(), Counter()))
                o.update(orths)
                s.update(surfaces)
        total = self.total + sum(counts_add.values())

        # band
        band = self.band0
        if self.auto:
            band = self._auto_band(self._band_words(counts_add, bound_add, tallies, total))
            if band != self.band0:
                moved.add("band")
        floor = self._floor(total, band)
        floor0 = self.floor0

        # floor: the list's words stay on it, no other word reaches it.
        index = view.index
        row_of_phrase = self.row_of_phrase
        if self.occ_min < floor:
            add = [0] * len(self.occ)
            for key, n in uses_add.items():
                k = index.get(key)
                if k is not None:
                    add[k] += n
            for p_index, n in phrases_add.items():
                k = row_of_phrase.get(p_index)
                if k is not None:
                    add[k] += n
            for k, (occ, n) in enumerate(zip(self.occ, add)):
                if occ + n < floor:
                    moved.add("phrases" if view.plan.keys[k][2] else "floor")
        under = math.ceil(floor0) - 1               # every word off the plan was used fewer times than its cut-off
        for key, n in uses_add.items():
            if key in index:
                continue
            most = self.counts.get(key, 0) - self.pieces.get(key, 0) + self.room.get(key, 0)
            if min(most, under) + n >= floor:
                moved.add("floor")
                break

        # compounds: none flips between rare and not.
        parts, known, rare = view.learning.parts, view.known, view.rare
        crossing = 0
        for key, n in counts_add.items():
            if key in parts and not known(key):
                count = self.counts.get(key, 0)
                if (key in rare) != (count + n < floor):
                    moved.add("compounds")
                if floor0 <= count < floor:
                    crossing += 1
        if floor > floor0:
            held = self.compound_counts
            if bisect_left(held, floor) - bisect_left(held, floor0) > crossing:
                moved.add("compounds")          # a compound none of these arrivals holds falls under the cut-off

        # names
        if view.language == "ja" and self._names_move([rec.get("names") for rec in records]):
            moved.add("names")

        # phrases
        if view.phrase_set is not None and self._phrases_move(tallies, phrases_add, counts_add, floor):
            moved.add("phrases")
        if view.unsure and phrases_add:             # a format-1 plan's row more than one phrase can hold: can't tell
            for p_index in phrases_add:
                entry = view.phrase_set.entry(p_index)
                if view.phrase_rows.get((entry.word, entry.reading)) in view.unsure:
                    moved.add("phrases")
                    break

        # spellings
        if self._spellings_move(spc_add):
            moved.add("spellings")
        return not moved, [name for name in GATES if name in moved]

    def _names_move(self, held):
        """Do the arrivals' name records change the name tables (or, Ignore names on, the library's names)?"""
        from app import names
        if any(record is None for record in held):
            return True                                 # a Japanese arrival without its record: can't tell
        if analyzer.LOGIC.get("ignore_names") and any(set(record.get("n", ())) - self.names_words for record in held):
            return True
        sanitize = analyzer._sanitize_term
        if self.tables is None:
            # No tables kept (none computed yet): the whole rule over the counted files' records, with and without the
            # arrivals — a name the library holds twice joins with an arrival's third use.
            base = list(self.records or ())
            before = getattr(self, "names_before", None)
            if before is None:                          # the library alone: worked out once per view
                before = self.names_before = names.compute_tables(base, None, sanitize)
            made = names.compute_tables(base + held, None, sanitize)
            return any(made[t] != before[t] for t in ("k", "j", "w"))
        sums, terms, tables = self.table_sums, self.term_sums, self.tables
        katakana, kanji = set(), set()
        for record in held:
            k, j = sums.touched(record)
            katakana |= k
            kanji |= j
        for record in held:
            sums.add(record)
        try:
            now = names.tables_from(sums, tables, sanitize, only=(katakana, kanji))
        finally:
            for record in held:
                sums.add(record, -1)
        if any(now["k"].get(s) != tables.get("k", {}).get(s) for s in katakana) or \
                any(now["j"].get(s) != tables.get("j", {}).get(s) for s in kanji):
            return True
        stretches = set()
        for record in held:
            stretches |= terms.touched(record)
        if not stretches:
            return False
        for record in held:
            terms.add(record)
        try:
            now = names._terms_table(terms, tables, tables.get("w", {}), sanitize, only=stretches)
        finally:
            for record in held:
                terms.add(record, -1)
        return any(now.get(s) != tables.get("w", {}).get(s) for s in stretches)

    def _phrases_move(self, tallies, phrases_add, counts_add, floor):
        """Does a phrase row come or go (main()'s phrase rows: uses at the cut-off, not known as a whole, no word of
        its lemmas joined in the library)?"""
        view = self.view
        arriving = {key[0] for key in counts_add} - self.lemmas
        if any(view.keys[k][0] in arriving for k in self.row_of_phrase.values()):
            return True                                 # a word of a row's lemmas joined arrives: the word keeps it
        if not phrases_add:
            return False
        if self.phrase_uses is None:
            return True                                 # the store's tallies aren't current: can't tell
        entries, known_whole = view.phrase_set, self.known_whole
        spelled = {}
        for uses, _given in tallies:
            for index, (_n, met) in uses.items():
                held = spelled.setdefault(int(index), [])
                held.extend(x for x in met if x not in held)
        for p_index, n in phrases_add.items():
            phrase = entries.entry(p_index)
            if p_index in self.row_of_phrase:
                if known_whole(phrase, tuple(spelled.get(p_index, ())), view.known_tuples, view.known_lemmas,
                               view.ignore):
                    return True                         # met in a spelling the learner knows it by: no row
                continue
            if self.phrase_uses.get(p_index, 0) + n < floor or phrase.word in self.lemmas or phrase.word in arriving:
                continue
            if not known_whole(phrase, tuple(self.phrase_spellings.get(p_index, ())) + tuple(spelled.get(p_index, ())),
                               view.known_tuples, view.known_lemmas, view.ignore):
                return True                             # a new row
        return False

    def _spellings_move(self, spc_add):
        """Does a list word's Orth / Forms move, or a tie appear the plan doesn't hold?"""
        from app import plan_rules
        view = self.view
        plan = view.plan
        ties = {tie[0]: tie for tie in plan.ties}
        for k, (orths, surfaces) in spc_add.items():
            row = plan.rows[k]
            if row is None:
                continue
            word = view.keys[k][0]
            tie = ties.get(k)
            if tie is not None:
                now_orths, now_surfaces = _added(tie[1], orths), _added(tie[2], surfaces)
                tied_orths, tied_surfaces = analyzer._spelling_ties(word, now_orths, now_surfaces)
                held_orths, held_surfaces = view.ties[k]
                if not (set(tied_orths) <= set(held_orths) and set(tied_surfaces) <= set(held_surfaces)):
                    return True
                if tie[3] is not None and not tied_orths:
                    orth = plan_rules.display_orth(word, now_orths)
                    if orth not in tie[3] and orth != row[4]:
                        return True                     # a phrase's Tier follows its spelling
                continue
            held = plan.spell.get(k)
            if held is None:
                return True                             # a format-1 plan: the counts aren't known
            now_orths, now_surfaces = _added(held[0], orths), _added(held[1], surfaces)
            tied_orths, tied_surfaces = analyzer._spelling_ties(word, now_orths, now_surfaces)
            if tied_orths or tied_surfaces:
                return True
            if plan_rules.display_orth(word, now_orths) != row[4] or \
                    plan_rules.display_forms(word, now_orths, now_surfaces) != row[5]:
                return True
        return False


def _added(counts, more):
    """`counts` with `more` added, as a new dict (keys in the order first met)."""
    out = dict(counts)
    for key, n in more.items():
        out[key] = out.get(key, 0) + n
    return out


# --------------------------------------------------------------------------------------------------------------- #
# The estimate (E2.2 D10) and the pick (D11): what the window shows of an arrival, worked out in the warm worker
# (`app/arrivals_worker.py`).
# --------------------------------------------------------------------------------------------------------------- #

RECORD_FIELDS = ("main", "ph", "sp", "prog", "spc", "plan", "keys", "name")     # what `Engine.add` reads


def read(view, path):
    """(sentences, name record) of the file at `path`, read here as the token store would read and serve it — the
    store's tokenizer reading the file alone, its name candidates recorded (Japanese), then the library's name tables
    the view was built with applied (`Store.file_tokens`) — so `record` gives what it gives over the store's tokens,
    and the gates get the record the store would keep. Writes nothing."""
    facts = {}
    return read_text(view, analyzer.extract_text(path, view.language, facts), facts)


def read_text(view, text, facts=None):
    """`read` for a file's text (`analyzer.extract_text`'s) and what the file said of itself (`facts`)."""
    language = view.language
    facts = facts or {}
    if language != "ja":
        return list(view.tokenizer.tokenize_sentences(text)), None
    import copy
    from app import names, token_index
    record_ = names.Record()
    record_.auto = bool(facts.get("auto")) or facts.get("captions") in analyzer.AUTO_CAPTIONS
    alone = copy.copy(view.tokenizer)               # the same tagger, reading as the token store reads (no tables)
    alone.library = False
    sentences = [(s_text, list(s_tokens)) for s_text, s_tokens in alone.tokenize_sentences(text, names=record_)]
    data = json.loads(json.dumps(record_.data(), ensure_ascii=False))      # as the store keeps it (JSON)
    switches = token_index._library_switches(language)
    spans = data.get("s")
    if spans and view.names_tables and any(switches):
        names.apply_spans(sentences, spans, view.names_tables, *switches)
    return sentences, data


class Order:
    """The last Generate's order, as an arrival is placed in it (D10's *N new*): each plan file's id, tier and folder
    (`library_store.folder_key_of`: a work's folder below its tier folder; None for a loose file) and each key's first
    file — read once from the plan's per-file lines."""

    def __init__(self, plan):
        from app.library_store import CURRENT, folder_key_of
        self.folder_key_of = folder_key_of
        self.current = CURRENT
        self.ids = [entry[0] for entry in plan.files]
        self.tiers = [entry[1] for entry in plan.files]
        self.folders = [folder_key_of(rel) for rel in self.ids]
        first = [None] * len(plan.keys)
        for f, line in enumerate(plan.per_file):
            for table in (line["main"], line["ph"]):
                for k in table[0::2]:
                    if first[k] is None:
                        first[k] = f
        self.first = first

    def n_new(self, keys, rel=None, placed=()):
        """(N new placed at the top of NOW, N new placed after the last item of its folder in Current (NOW and Soon) or
        None when it has none there, that item's id) for an arrival holding `keys` (its record's k numbers, words and
        phrase rows), the files `placed` since the plan ([(id, keys, tier, before_id, after_id)], in the order placed; a
        tier of None: after its folder's last item in Current, else the top of NOW) placed first — what
        `plan_engine.Engine.add` gives the item (`Result.n_new`) placed in the plan's order, counted without an engine:
        a key is new where no file before it in the order holds it. A show whose items are all in 6+ Months has no
        "after its show" (D28: its new episode leads Current, the top-of-NOW figure). The window's moves since the plan
        aren't in the plan's order: after one, the engine's own figure (`Engine.add`) is the one to show."""
        keys = list(keys)
        top = len(keys)                     # at the top of NOW it comes before every file
        folder = self.folder_key_of(rel) if rel else None
        if folder is None:
            return top, None, None
        if not placed:
            at = None
            for f in range(len(self.ids) - 1, -1, -1):
                if self.folders[f] == folder and self.ids[f] != rel and self.tiers[f] in self.current:
                    at = f
                    break
            if at is None:
                return top, None, None
            first = self.first
            return top, sum(1 for k in keys if first[k] is None or first[k] > at), self.ids[at]
        # Files placed since the plan: the order with them in it (plan files by index, placed ones by their keys).
        items = [(self.ids[f], self.tiers[f], self.folders[f], f) for f in range(len(self.ids))]
        for item_id, item_keys, tier, before, after in placed:
            own = self.folder_key_of(item_id) if isinstance(item_id, str) else None
            at = None
            if tier is None:
                last = self._last_of(items, own, item_id, self.current)
                at = None if last is None else last + 1
                tier = "now" if last is None else items[last][1]
            elif before is not None or after is not None:
                anchor = before if before is not None else after
                found = next((i for i, item in enumerate(items) if item[0] == anchor), None)
                if found is not None:
                    at = found + (0 if before is not None else 1)
            if at is None:                  # the top of its tier
                rank = {"now": 0, "soon": 1, "goal": 2}
                at = next((i for i, item in enumerate(items) if rank.get(item[1], 0) >= rank.get(tier, 0)),
                          len(items))
            items.insert(at, (item_id, tier, own, frozenset(item_keys)))
        last = self._last_of(items, folder, rel, self.current)
        if last is None:
            return top, None, None
        before_it = sum(1 for item in items[:last + 1] if not isinstance(item[3], frozenset))
        held = set().union(*(item[3] for item in items[:last + 1] if isinstance(item[3], frozenset)))
        first = self.first
        return (top, sum(1 for k in keys if (first[k] is None or first[k] >= before_it) and k not in held),
                items[last][0])

    @staticmethod
    def _last_of(items, folder, rel, tiers):
        if folder is None:
            return None
        for i in range(len(items) - 1, -1, -1):
            if items[i][2] == folder and items[i][0] != rel and items[i][1] in tiers:
                return i
        return None


def estimate(view, gates, order, rec, rel=None, placed=()):
    """What the window shows of an arrival (D10), from its record (`record`, read by `read`) and the warm view:
    {"words": [[Word, Reading], …] (its list words, none known, in the order met — words, then phrase rows),
    "n_new_top": N new placed at the top of NOW, "n_new_after_show": N new placed after the last item of its folder
    in Current (None when it has none there; "after": that item's id), "known_pct": % known (QT-E8, Sonic's E2.2-3:
    known tokens ÷ counted tokens, pieces by sums — the record's progressive total and baseline, as Baseline % rounds
    it), "known" / "counted" (the two sums), "exact" / "moved" (`Gates.check` over the files `placed` since the plan
    and this one; "stand-aside" when the engine can't replay the plan at all, `plan_engine.stands_aside`: coverage,
    i+1, shared phrases), "record" (what `plan_engine.Engine.add` reads)}. `placed`: [{"id", "record", "tier", "before", "after"}] in the order
    placed (tier None: after its folder's last item, else the top of NOW). Pure."""
    plan = view.plan
    keys = list(rec["main"][0::2]) + list(rec["ph"][0::2])
    words = [[view.keys[k][0], view.keys[k][1]] for k in keys if plan.rows[k] is not None]
    from app import plan_engine
    if gates is None:
        exact, moved = False, ["stale"]
    elif plan_engine.stands_aside(plan):
        exact, moved = False, ["stand-aside"]   # Engine(plan) refuses it: no number it gives is the next Generate's
    else:
        exact, moved = gates.check([p["record"] for p in placed] + [rec])
    top, after, anchor = order.n_new(
        keys, rel, [(p["id"], list(p["record"]["main"][0::2]) + list(p["record"]["ph"][0::2]), p.get("tier"),
                     p.get("before"), p.get("after")) for p in placed])
    total, baseline = rec["prog"][0], rec["prog"][1]
    return {"words": words, "n_new_top": top, "n_new_after_show": after, "after": anchor,
            "known_pct": round(baseline / total * 100, 2) if total else None, "known": baseline, "counted": total,
            "exact": exact, "moved": moved, "record": {name: rec[name] for name in RECORD_FIELDS}}


def pick_words(view, path, listed, send_grammar=True):
    """D11, the pick prepared at arrival: for a subtitle (.srt, .ass, .ssa), `app.connect.pick.pick` in "list" mode
    over its cues (`cues.read` / `cues.tokens`, read with the view's tokenizer) with the view's known words, the last
    Generate's list (`listed`: {(Word, Reading): its place}) and no cards (`carded=None`: the live "no card yet" check
    is mining's) — {"words", "not_offered"}; None for any other file. The rest as Connect's pick passes it."""
    from app import cues
    if not str(path).lower().endswith(cues.SUBTITLES):
        return None
    return pick_cues(view, cues.read(path, view.language), listed, send_grammar)


def pick_cues(view, read_, listed, send_grammar=True):
    """`pick_words` for a subtitle's cues (`cues.read`'s)."""
    from app import cues
    from app.connect import pick
    language = view.language
    tokens = cues.tokens(read_, language, view.script, view.tokenizer)
    readable = analyzer.LearningView(known=view.known).readable if language == "ja" else None
    return pick.pick(read_, tokens, language, view.known, mode="list", listed=listed, carded=None,
                     readable=readable, ignore_names=bool(analyzer.LOGIC.get("ignore_names", False)),
                     send_grammar=send_grammar, skip_single=not view.args.include_single_chars,
                     phrase_set=view.phrase_set)
