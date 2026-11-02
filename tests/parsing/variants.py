"""Prototype variants — a candidate parsing rule the app doesn't have yet, run over the whole registry by the
scorecard (`--variant NAME`), so a design is judged by what it fixes and what it breaks before it is built.

A variant is a context manager that patches the pipeline for the run: a token post-process after the app's own
joins (`after_join` — compound B, the っ rule), or any function of the app replaced where the app looks it up
(`patched` — a consumer's rule). Register one with:

    @variant("name", "one line: what it changes and why")
    def _name():
        with after_join(my_post_process):
            yield

Everything reaches every layer: the tokenizer, the known words (load_known_words tokenizes through it), U9's
see-through, the matchers. Only the pins are outside its reach: a variant changes code, not the frozen settings.
Tokens a post-process makes: `harness.Token(surface, feature)` for one piece, `analyzer._joined(parts, key, pos1,
(lemma, reading))` for several joined into one word (a JoinedWord, shown with + and counted as one word).

An area adds its variants in `variants_<area>.py` beside this file (imported by `load_variants`, as
evaluators_<area>.py and decisions_<area>.py are) — so areas never edit one file at once; a name registered twice
fails. The scorecard loads them before it builds `--variant`'s choices.
"""
import contextlib
import importlib
import os
import pkgutil
from collections import namedtuple

from app import analyzer
from tests.parsing.harness import Token, patched

Variant = namedtuple("Variant", "name about manager")
VARIANTS = {}
HERE = os.path.dirname(os.path.abspath(__file__))


def variant(name, about):
    """Register the generator function it decorates as the context manager of variant `name`."""
    def register(fn):
        held = VARIANTS.get(name)
        if held and (held.manager.__module__, held.manager.__qualname__) != (fn.__module__, fn.__qualname__):
            raise ValueError(f"variant {name!r} is already registered by {held.manager.__module__}")
        VARIANTS[name] = Variant(name, about, contextlib.contextmanager(fn))
        return fn
    return register


def load_variants():
    """Import every variants_<area>.py beside this file (each registers its variants) -> VARIANTS. Importing is
    cheap: a variant reads its data when it is entered, never at import."""
    for info in sorted(pkgutil.iter_modules([HERE]), key=lambda info: info.name):
        if info.name.startswith("variants_"):
            importlib.import_module(f"tests.parsing.{info.name}")
    return VARIANTS


def after_join(post):
    """Patch analyzer.join_affixes so every caller gets `post(tokens)`: the tokens of one tagger call after the app's
    own prefix / suffix joins, post-processed — where compound B and the っ rule would go (Compound_Join_Measurement
    §9 item 2: after the affix runs)."""
    real = analyzer.join_affixes
    return patched(analyzer, "join_affixes",
                   lambda words, joins=None, library=True: post(real(words, joins, library)))


# --- an example: the post-process hook, doing something trivial ----------------------------------------------- #
@variant("no-affix-joins",
         "Words back in UniDic's short units — every affix join split into its pieces again, as before 2.3. "
         "Shows exactly the cases 2.3's joins decide (Patterns_Quality_Spec.md Part A).")
def _no_affix_joins():
    def split(tokens):
        out = []
        for token in tokens:
            if isinstance(token, analyzer.JoinedWord):
                out.extend(Token(surface, feature) for surface, feature in token.parts)
            else:
                out.append(token)
        return out
    with after_join(split):
        yield
