"""Layers for Japanese tokenizing beyond the core tokens_ja (docs/agent instructions/Parsing_Suite.md §6).

    layer             text is                                   expect keys
    see_through       a joined word: "lemma" or "lemma|READING"  base
    tokens_ja_table   the whole line(s), as tokens_ja            units, absent, words, not_words  (+ ctx["table"])

Both run the app's own code: `analyzer.see_through_base` (U9) and the app's tokenizer + `join_affixes`.
"""
from app import analyzer
from tests.parsing import evaluators
from tests.parsing.harness import evaluator, key, patched, split_key


# --- see_through ------------------------------------------------------------------------------------------------ #
@evaluator("see_through", expects=("base",),
           show=lambda observed: f"{observed['word']} → {observed['base'] or '(none)'}")
def see_through(case, ctx):
    """The word a joined word is read through (U9, Patterns_Quality_Spec.md §6.8): analyzer.see_through_base on the
    case's text — "lemma|READING", or a bare lemma, whose reading is then the join table's (the key the list gives a
    joined word). Observed {"word", "base"}: base is "lemma|READING" (the key a known word must hold), "" for none —
    a prefix word (不自然), a suffix that makes no noun (具体的), no joined word (公園), a reading not the table's."""
    lemma, reading = split_key(case.text)
    if "|" not in case.text:
        entry = analyzer.affix_joins().get(lemma)
        reading = entry[1] if entry else ""
    base = analyzer.see_through_base(lemma, reading, ctx.tokenizer("ja").tagger)
    return {"word": key(lemma, reading), "base": key(*base) if base else ""}


# --- tokens_ja_table ---------------------------------------------------------------------------------------------- #
@evaluator("tokens_ja_table", expects=("units", "absent", "words", "not_words"), compare=evaluators.compare_units,
           show=evaluators.show_units)
def tokens_ja_table(case, ctx):
    """tokens_ja with the join table replaced by ctx["table"] ({written form: [lemma, reading]}) for the duration:
    the app's own tokenizer and join_affixes, judged where the dictionary WOULD allow a join — so a guard (a name, a
    plural, a number, a nominalizer after a な-word) is shown to be the rule's doing, not the table's
    (tests/test_affix_join.py's custom-table tests). The table goes through analyzer.affix_joins, where the tokenizer
    looks it up; a variant's post-process still runs after it."""
    table = {written: list(entry) for written, entry in case.ctx["table"].items()}
    with patched(analyzer, "affix_joins", lambda: table):
        return evaluators.tokens_ja(case, ctx)
