"""The set phrases on the list (Phrase_Bundle_Spec.md; app/phrases.py) — which phrases a sentence holds, and a phrase's
state under a case's known words.

    layer    text is                     expect keys
    phrases  the sentence(s), as the     found, not_found, ready, waits_for, score, bound
             app reads a line

The shipped phrase data (app/phrase_data.py) and the app's own matcher, on the case's text read by the case's
tokenizer (the pins: the frozen settings and name tables). A list row also needs the library's count — no snapshot
holds the library's phrases, so the row itself is the analyzer's tests' (tests/test_phrase_counting.py); this layer
judges what is a phrase, where it is found, and when it is ready.
"""
from app import analyzer
from tests.parsing.harness import compare_keys, evaluator


def _show(observed):
    bits = ["found " + ("、".join(observed["found"]) or "nothing")]
    if observed.get("ready") is not None:
        bits.append(("ready" if observed["ready"] else "waits for " + "、".join(observed["waits_for"]))
                    + f" · {observed['score']}" + (" · bound " + "、".join(observed["bound"]) if observed["bound"] else ""))
    return "; ".join(bits)


def _compare(observed, expect):
    """found / not_found: phrases that are / aren't among those found — by the spelling shown, the row's Word or the
    words as written there; every other key exact."""
    problems = []
    found = set(observed["found"]) | set(observed.get("words", ())) | set(observed.get("written", ()))
    for name in expect.get("found", ()):
        if name not in found:
            problems.append(f"{name} not found (found: {observed['found']})")
    for name in expect.get("not_found", ()):
        if name in found:
            problems.append(f"{name} found")
    problems += compare_keys(observed, {k: v for k, v in expect.items() if k not in ("found", "not_found")})
    return problems


@evaluator("phrases", expects=("found", "not_found", "ready", "waits_for", "score", "bound"), compare=_compare,
           show=_show)
def phrases_layer(case, ctx):
    """The set phrases `text` holds — app.phrases.load()'s find over each sentence the case's tokenizer reads, longest
    first, never across a dropped mark — by the spelling each is shown in (its JMdict spelling); and, for the phrase
    found where `span` stands, its state under the case's known words (ctx snapshot / known / ignore): ready (it waits
    for no word), waits_for (the lemmas of the real words it waits for: new, not living only inside it, two
    characters or more), score ("half" when every real word in it is known, as the list scores it, else "full"),
    bound (the lemmas that live only inside it).
    -> {found, ready, waits_for, score, bound} (the last four None without a span or a phrase there)."""
    from app import phrases
    found_in = phrases.load()
    tokenizer = ctx.tokenizer("ja")
    met = []                    # (the phrase, its words as written there)
    for sentence, tokens in tokenizer.tokenize_sentences(case.text):
        met += [(found_in.entry(index), "".join(t[2] for t in tokens[a:b]))
                for a, b, index in found_in.find(tokens, sentence)]
    out = {"found": [p.display for p, _w in met], "words": [p.word for p, _w in met], "written": [w for _p, w in met],
           "ready": None, "waits_for": None, "score": None, "bound": None}
    if not case.span:
        return out
    target = next((p for p, written in met if case.span in written or written in case.span), None)
    if target is None:
        return out
    known_tuples, known_lemmas, ignore = ctx.known_sets(case)

    def known(key):
        return key[0] in ignore or key[0] in known_lemmas or key in known_tuples
    view = analyzer.LearningView(None, 0, known=known, tagger=tokenizer.tagger)
    waits, all_known = phrases.waiting(target, lambda key: known(key) or view.readable(key))
    out.update(ready=not waits, waits_for=[lemma for lemma, _reading in waits],
               score="half" if all_known else "full",
               bound=[target.key[k] for k in phrases.bound_at(target)])
    return out
