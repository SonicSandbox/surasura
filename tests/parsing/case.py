"""A case of the parsing-robustness suite — one input, the answer it should get, and why.

Cases are plain data in `cases/cases_<area>.py` (`CASES = [Case(...), ...]`); the evaluator named by `layer` runs
the app's own code on `text` and compares what it sees with `expect`. Every field is documented in
docs/agent instructions/Parsing_Suite.md; the short version:

    Case(id="JA-CMP-001", lang="ja", layer="tokens_ja", category="F",
         text="上層部に確認を取る必要がある。",          # exactly what the app feeds: the whole LINE for MeCab
         span="上層部",                                  # the part judged (its `nth` occurrence, 1-based)
         expect={"units": "上層部[上層部]"},              # layer-specific, see the layer's `expects`
         basis="JPDB 2024 / Jiten / BCCWJ headword ...",  # why that answer is right — from the language as a whole
         status="TARGET",                                # LOCK | TARGET | LIMIT | DISPUTED
         decision="CJ-B",                                # a decisions.py id (LIMIT: a decided one; DISPUTED: an open one)
         source="library: 陰の実力者-3_31.txt",           # library | corpus | constructed | doc, then any detail
         refs=("Compound_Join_Measurement.md §3",))
"""
from dataclasses import dataclass, field

# LOCK: right today — the guard asserts it. TARGET: wrong today — the guard expects it to fail, strictly, so the
# change that fixes it fails the run until it is promoted to LOCK. LIMIT: wrong (or partly) and accepted — a
# decided decision says why. DISPUTED: the user's call — an open decision holds both sides. LIMIT and DISPUTED are
# reported by the scorecard, never asserted.
STATUSES = ("LOCK", "TARGET", "LIMIT", "DISPUTED")

# Where a case's input came from; `source` starts with one of these, e.g. "library: bleach - 359.srt".
SOURCES = ("library", "corpus", "constructed", "doc")

LANGUAGES = ("ja", "zh")

# Parsing_Robustness_Suite_Scope.md §2 — what a case is about, whichever layer judges it.
CATEGORIES = {
    "A": "Reading files and cleaning text",
    "B": "Sentence splitting",
    "C": "Script and characters",
    "D": "Symbols and numerals",
    "E": "Affix joins and お / ご",
    "F": "Compounds and coincidences",
    "G": "Sound words + と",
    "H": "Verbs, readings and lemmas",
    "I": "Names",
    "J": "Known words",
    "K": "Card matching",
    "L": "Difficulty and i+1",
    "M": "パターン, 例文 and the sentence dictionary",
    "N": "Caches and versions",
    "O": "Chinese segmentation and script",
    "P": "Ordinary text (random audit, verified)",
}


@dataclass(frozen=True)
class Case:
    id: str             # stable, <LANG>-<GROUP>-<NNN> (JA-CMP-012); a GROUP belongs to one area file
    lang: str           # "ja" | "zh"
    layer: str          # the evaluator that judges it (evaluators.py, evaluators_<area>.py)
    category: str       # a CATEGORIES letter
    text: str           # the input exactly as the app feeds it (see the layer)
    span: str           # the part being judged ("" = all of it, where the layer allows)
    expect: dict        # the layer's expectation keys
    basis: str          # why the expectation is right, from the language as a whole
    status: str         # a STATUSES value
    decision: str = None    # a decisions.py id this case trades on (or will be fixed by)
    source: str = "constructed"
    refs: tuple = ()    # spec sections, adversary rows (debug/parsing_suite/ja_tokens A51), tests
    note: str = ""
    nth: int = 1        # which occurrence of `span` in `text`, 1-based
    ctx: dict = field(default_factory=dict)     # the case's own context data — keys in Parsing_Suite.md
    area: str = ""      # set by the collector from the file name (cases_<area>.py)


# --- builders for `text` cases: a subtitle file around the cues, the way a player's file holds them ------------ #
def srt(*cues, crlf=True):
    """An .srt file's content holding `cues` (each one cue's text; a "\\n" inside is a second line of the cue),
    numbered and timed like a real file. Use with ctx={"ext": ".srt"}."""
    blocks = []
    for number, cue in enumerate(cues, 1):
        start, end = number * 2, number * 2 + 1
        blocks.append(f"{number}\n00:00:{start:02d},000 --> 00:00:{end:02d},500\n{cue}\n")
    text = "\n".join(blocks)
    return text.replace("\n", "\r\n") if crlf else text


def ass(*lines):
    """An .ass file's content holding one Dialogue line per entry of `lines` (the Text field, override tags and \\N
    included). Use with ctx={"ext": ".ass"}."""
    head = ("[Script Info]\nScriptType: v4.00+\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    body = "".join(f"Dialogue: 0,0:00:{n * 2:02d}.00,0:00:{n * 2 + 1:02d}.50,Default,,0,0,0,,{line}\n"
                   for n, line in enumerate(lines, 1))
    return head + body
