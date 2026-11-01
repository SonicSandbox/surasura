"""JMdict's flags as variants (WP-5, 2026-09-28) — what scripts/jmdict_flags.py decides, scored before the build
carries it (the fringe needs lane K's compound join and T's table; the お / ご exceptions need T's dictionary_data.py
and K's affix_joins() merge). Nothing in app/ changes.

    ogo-jmdict              the お / ご exceptions join: reference_data's affix table plus `ogo_exceptions`' words
                            (お守り, お帰り, お笑い, おかわり — Compound_Build_Spec.md §2.13 with the abbreviation lean)
    compound-b-fringe-off   compound-b with the switch "Phrases and titles as one word" off: every compound JMdict
                            makes fringe (a title, a phrase, a prefix + a word — §2.12) stays in its parts

Both read data/variants/jmdict_flags.json (jmdict_flags_data.py beside it wrote it from JMdict_e.gz).
"""
import json
import os

from app import reference_data
from tests.parsing import harness
from tests.parsing.harness import patched
from tests.parsing.variants import after_join, variant

DATA = os.path.join(harness.DATA, "variants", "jmdict_flags.json")
_DATA = {}


def data():
    """{"fringe": {spelling: flags}, "ogo": {spelling: [lemma, reading]}} — read once, when a variant needs it."""
    if not _DATA:
        if not os.path.isfile(DATA):
            raise FileNotFoundError(f"{DATA} is missing — PYTHONIOENCODING=utf-8 python "
                                    "tests/parsing/data/variants/jmdict_flags_data.py")
        with open(DATA, encoding="utf-8") as handle:
            _DATA.update(json.load(handle))
    return _DATA


@variant("ogo-jmdict",
         "お / ご exceptions: an お / ご word U1's share leaves split joins when JMdict lists it as a word of its own "
         "with a meaning the bare word lacks, a bare sense marked abbreviation not counting against it (お守り, お帰り, "
         "お笑い, おかわり; not お名前, お仕事, お部屋) — Compound_Build_Spec.md §2.13.")
def _ogo_jmdict():
    merged = {**reference_data.affix_joins(), **data()["ogo"]}
    with patched(reference_data, "affix_joins", lambda: merged):
        yield


@variant("compound-b-fringe-off",
         "compound-b with 'Phrases and titles as one word' off: the compounds JMdict makes fringe — a title, a phrase "
         "JMdict never lists as a noun, a JMdict prefix + a word; never a loanword — stay in their parts "
         "(Compound_Build_Spec.md §2.12).")
def _compound_b_fringe_off():
    from tests.parsing import variants_ja_tokens as tokens
    fringe = data()["fringe"]
    full = tokens.table()
    kept = {"spellings": {w: c for w, c in full["spellings"].items() if w not in fringe}, "library": full["library"]}
    with patched(tokens, "table", lambda: kept), after_join(tokens.join_compounds):
        yield


@variant("ogo-jmdict-main",
         "ogo-jmdict narrowed (a question for the user): an お / ご word joins only when JMdict's first sense is a "
         "meaning the bare word lacks (お守り, お笑い), or it has an interjection / expression sense the bare word "
         "lacks (お帰り 'welcome home', ご苦労, お疲れ) — a polite form with a rarer second meaning (お友達 'another "
         "child', お天気 'mood') stays split.")
def _ogo_jmdict_main():
    merged = {**reference_data.affix_joins(), **data()["ogo_main"]}
    with patched(reference_data, "affix_joins", lambda: merged):
        yield
