"""Chinese script conversion (Simplified <-> Traditional) for the `zh_script` setting.

A Chinese library can hold both scripts: a Traditional learner adds a Simplified YouTube transcript,
and without this 学习 and 學習 are two unrelated words (counts split, known words miss). The setting
(`asis` | `s` | `t`) makes the analysis read content, known words, lists and frequency lists in ONE
script. Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md.

Everything converts when it is READ. No user file is ever rewritten (spec I1). Two properties the
rest of the app depends on:

  * Length-preserving (I3). Every mapping, character or phrase, keeps its length, so offset k in
    converted text is offset k in the original. That lets the tokenizer segment in Simplified while
    emitting Traditional, and lets the report's deep links point at the file's own wording.
  * Lazy (I4). Importing this module decodes nothing. The tables (app/zh_script_data.py, generated
    from OpenCC by scripts/build_zh_script_data.py) load on the first conversion, so importing
    app.analyzer, which a "nothing changed" Generate does, never pays for them.

How a conversion works: `str.translate` maps every character to its preferred counterpart at C
speed. Context only matters at the few hundred characters some phrase converts differently (发 is
發 in 发现 but 髮 in 头发), so a second pass visits only those positions and overwrites the longest
phrase covering each one. Measured on real news text at about 9 MB/s to Traditional and 40 MB/s to
Simplified. Simplified -> Traditional is inherently ambiguous and phrases fix the common cases, not
all of them, so a rare context can still come out wrong. Traditional -> Simplified is nearly lossless.
"""

import re

# "asis" leaves text exactly as written; "s" reads everything as Simplified, "t" as Traditional.
SCRIPTS = ("asis", "s", "t")


def effective(language, script):
    """The conversion that actually applies. Only a Chinese library converts, and anything that isn't
    a known script counts as as-is, so a hand-edited settings.json can never break a run."""
    return script if language == "zh" and script in ("s", "t") else "asis"


class _Converter:
    def __init__(self, table):
        chars = table.get("chars") or {}
        self.phrases = table.get("phrases") or {}
        self.translation = str.maketrans(chars)
        # Characters some phrase converts differently from `chars` -> the phrase pass visits only
        # these. `offsets[c]` is every position c holds in any phrase (largest first, so a tie between
        # two equally long phrases goes to the leftmost). `lengths[c]` is the phrase lengths that
        # start with c, longest first.
        triggers = set()
        for src, dst in self.phrases.items():
            triggers.update(a for a, b in zip(src, dst) if chars.get(a, a) != b)
        offsets, lengths = {}, {}
        for src in self.phrases:
            lengths.setdefault(src[0], set()).add(len(src))
            for k, ch in enumerate(src):
                if ch in triggers:
                    offsets.setdefault(ch, set()).add(k)
        self.offsets = {ch: sorted(ks, reverse=True) for ch, ks in offsets.items()}
        self.lengths = {ch: sorted(ls, reverse=True) for ch, ls in lengths.items()}
        self.trigger_re = (re.compile("[" + "".join(re.escape(ch) for ch in sorted(triggers)) + "]")
                           if triggers else None)

    def _phrase_at(self, text, i, lo):
        """(start, length) of the longest phrase covering position i that starts at or after `lo`, or
        (0, 0). Starting at `lo` or later keeps it clear of the phrase applied just before it."""
        best_start, best_len = 0, 0
        for k in self.offsets.get(text[i], ()):
            start = i - k
            if start < lo:
                continue
            for length in self.lengths.get(text[start], ()):
                if length <= k or length <= best_len:
                    break              # can't reach past i, or can't beat what we already have
                if text[start:start + length] in self.phrases:
                    best_start, best_len = start, length
                    break
        return best_start, best_len

    def convert(self, text):
        out = text.translate(self.translation)
        if self.trigger_re is None:
            return out
        chars, end = None, 0
        for match in self.trigger_re.finditer(text):
            i = match.start()
            if i < end:
                continue               # inside a phrase already applied
            start, length = self._phrase_at(text, i, end)
            if length:
                if chars is None:
                    chars = list(out)
                chars[start:start + length] = self.phrases[text[start:start + length]]
                end = start + length
        return "".join(chars) if chars is not None else out


_converters = {}


def _converter(direction):
    conv = _converters.get(direction)
    if conv is None:
        try:
            from app import zh_script_data
            conv = _Converter(getattr(zh_script_data, direction)())
        except Exception as e:
            # Degrade to no conversion rather than fail a run: the library then reads as written.
            print(f"Warning: Chinese script tables unavailable ({e}); reading text as written.")
            conv = _Converter({})
        _converters[direction] = conv
    return conv


def to_simplified(text):
    return _converter("t2s").convert(text) if text else text


def to_traditional(text):
    return _converter("s2t").convert(text) if text else text


def convert(text, script):
    """`text` in `script` ("s" or "t"). "asis" or anything else returns the SAME string, untouched.

    Traditional goes THROUGH Simplified rather than straight from the original. OpenCC's phrase keys
    are Simplified, so a Traditional source only gets its context read once it is Simplified (准許
    stays 准許; converted directly it became 準許, and 里長 became 裏長). It also puts every word on ONE
    Traditional spelling whichever script it came from: converting the original directly left 牛肉麵
    from a Traditional file and 牛肉麪 from a Simplified one as two words, the exact split this setting
    exists to remove. The price is that Traditional text comes out in OpenCC's standard forms (爲, 裏),
    which is what "generic Traditional" means (spec Q2)."""
    if script == "s":
        return to_simplified(text)
    if script == "t":
        return to_traditional(to_simplified(text))
    return text
