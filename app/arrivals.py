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
        import os
        from app import names, token_index, zh_script
        from app.path_utils import get_user_files_path

        args = args or analyzer.parse_analysis_args([f"--language={language}"])
        script = zh_script.effective(language, args.zh_script)
        analyzer.SANITIZE_JA = language == "ja"
        skip_singles = not args.include_single_chars and language == "ja"      # main(): SKIP_SINGLE_CHARS, ja only
        if tokenizer is None:
            tokenizer = (analyzer.ChineseTokenizer(reinforce_segmentation=args.reinforce, script=script)
                         if language == "zh" else analyzer.JapaneseTokenizer())
        if language == "ja":
            # Every word read from here on — the known words included — is read with the tables the Generate read.
            names.use_library_tables(store.names_tables() if store is not None
                                     else token_index.read_names_tables(language))
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
        counts = store.word_counts()[0] if store is not None else None
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
                   skip_singles=skip_singles, learning=learning, rare=rare, floor=floor, counts=counts,
                   phrase_set=phrase_set, keys=keys, index=index, phrase_rows=phrase_rows, entry_of=entry_of,
                   unsure=unsure, lemmas={key[0] for k, key in enumerate(keys) if not plan.keys[k][2]},
                   listed={k for k, row in enumerate(plan.rows) if row is not None},
                   halved={k for k, key in enumerate(plan.keys) if key[3]},
                   ties=ties, spellings=spellings, states={}, phrase_bound={})

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

    def sentences(self, path):
        """A file's tokenized sentences as a Generate reads them (`analyzer.file_sentences`: the store's, the name
        tables applied)."""
        return analyzer.file_sentences(self.store, self.tokenizer, path, self.language)


def record(sentences, view, file_path=None, source_type=None):
    """The plan line a full Generate would write for one file's `sentences` were it counted, with `view` the last
    Generate's (`View.build`): {"main", "ph", "sp", "prog"} — as `analyzer.plan_lines` writes them, the same k numbers,
    the same order — and {"spc": {k: [{orth: n}, {surface: n}]} (this file's spellings of each list word, each in the
    order met), "uses": {(lemma, reading): n} (every word's counted uses here, list or not, rare compounds' credits
    included), "phrases": {phrase index: uses}, "tokens": the file's counted tokens}. `file_path` and `source_type`
    name the file; no part of its line depends on them."""
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
            if state & 1:
                continue
            if state & 12:
                if state & 4:
                    continue
                if bound_uses(s_text, s_tokens, only=(t_no,)):
                    pieces[key] += 1
                    continue
            unknown.append((key, surface, orth))
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
            orth, written = phrases.spellings(s_tokens, start, end, phrase)
            phrase_uses[p_index] += 1
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
            "tokens": tokens}
